"""Admin portal blueprint."""
from datetime import datetime, date, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from extensions import db
from models import User, Customer, Service, Lead, Booking, Feedback, Notification
from blueprints.auth import role_required
from notifications import (
    notify_booking_created, notify_technician_assigned, notify_service_completed,
)
from warranty import expiring_warranties, all_warranties

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _admin_required(view):
    @login_required
    def wrapped(*a, **kw):
        if not current_user.is_admin:
            abort(403)
        return view(*a, **kw)
    wrapped.__name__ = view.__name__
    return wrapped


# ---------- Dashboard ----------
@bp.route("/")
@_admin_required
def dashboard():
    today = date.today()

    stats = {
        "total_leads": Lead.query.count(),
        "new_leads": Lead.query.filter_by(status="New").count(),
        "upcoming_bookings": Booking.query.filter(
            Booking.booking_date >= today,
            Booking.status.in_(["Pending", "Confirmed", "Assigned", "In Progress"]),
        ).count(),
        "completed": Booking.query.filter_by(status="Completed").count(),
        "pending_jobs": Booking.query.filter(
            Booking.status.in_(["Confirmed", "Assigned", "In Progress"])
        ).count(),
        "feedback_count": Feedback.query.count(),
        "avg_rating": db.session.query(db.func.avg(Feedback.rating)).scalar() or 0,
    }

    recent_leads = Lead.query.order_by(Lead.created_at.desc()).limit(5).all()
    upcoming = (
        Booking.query.filter(Booking.booking_date >= today)
        .order_by(Booking.booking_date.asc())
        .limit(5)
        .all()
    )
    ex_warranties = expiring_warranties()[:5]

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_leads=recent_leads,
        upcoming=upcoming,
        ex_warranties=ex_warranties,
    )


# ---------- Leads ----------
@bp.route("/leads")
@_admin_required
def leads():
    q = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    status = request.args.get("status", "").strip()

    query = Lead.query
    if q:
        like = f"%{q}%"
        query = query.join(Customer).filter(
            or_(
                Customer.name.ilike(like),
                Customer.phone.ilike(like),
                Customer.email.ilike(like),
                Lead.message.ilike(like),
            )
        )
    if source:
        query = query.filter(Lead.source == source)
    if status:
        query = query.filter(Lead.status == status)
    leads = query.order_by(Lead.created_at.desc()).all()
    return render_template(
        "admin/leads_list.html", leads=leads, q=q, source=source, status=status
    )


@bp.route("/leads/new", methods=["GET", "POST"])
@_admin_required
def lead_new():
    services = Service.query.filter_by(status="ACTIVE").all()
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        service_id = request.form.get("service_id") or None
        source = request.form.get("source", "Phone Call")
        message = request.form.get("message", "").strip()
        preferred_date_raw = request.form.get("preferred_date", "").strip()

        cust = Customer.query.filter_by(phone=phone).first()
        if not cust:
            cust = Customer(name=name, phone=phone, email=email or None,
                            address=address, city=city)
            db.session.add(cust); db.session.flush()
        else:
            if email and not cust.email: cust.email = email
            if address and not cust.address: cust.address = address

        preferred_date = None
        if preferred_date_raw:
            try: preferred_date = datetime.strptime(preferred_date_raw, "%Y-%m-%d").date()
            except ValueError: pass

        lead = Lead(
            customer_id=cust.id,
            service_id=int(service_id) if service_id else None,
            source=source, message=message, preferred_date=preferred_date,
            status="New",
        )
        db.session.add(lead); db.session.commit()
        flash("Lead created.", "success")
        return redirect(url_for("admin.lead_detail", lead_id=lead.id))
    return render_template("admin/lead_form.html", services=services, lead=None)


@bp.route("/leads/<int:lead_id>")
@_admin_required
def lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    technicians = User.query.filter_by(role="TECHNICIAN", is_active=True).order_by(User.name).all()
    services = Service.query.filter_by(status="ACTIVE").all()
    return render_template(
        "admin/lead_detail.html", lead=lead, technicians=technicians, services=services
    )


@bp.route("/leads/<int:lead_id>/status", methods=["POST"])
@_admin_required
def lead_status(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    new_status = request.form.get("status")
    if new_status:
        lead.status = new_status
        db.session.commit()
        flash("Lead status updated.", "success")
    return redirect(url_for("admin.lead_detail", lead_id=lead.id))


@bp.route("/leads/<int:lead_id>/assign", methods=["POST"])
@_admin_required
def lead_assign(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    uid = request.form.get("assigned_to")
    lead.assigned_to = int(uid) if uid else None
    db.session.commit()
    flash("Technician assigned to lead.", "success")
    return redirect(url_for("admin.lead_detail", lead_id=lead.id))


# ---------- Bookings ----------
@bp.route("/bookings")
@_admin_required
def bookings():
    status = request.args.get("status", "").strip()
    q = Booking.query
    if status:
        q = q.filter(Booking.status == status)
    bookings = q.order_by(Booking.booking_date.desc(), Booking.id.desc()).all()
    return render_template("admin/bookings_list.html", bookings=bookings, status=status)


@bp.route("/bookings/new", methods=["GET", "POST"])
@_admin_required
def booking_new():
    services = Service.query.filter_by(status="ACTIVE").all()
    technicians = User.query.filter_by(role="TECHNICIAN", is_active=True).all()
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        service_id = int(request.form["service_id"])
        booking_date = datetime.strptime(request.form["booking_date"], "%Y-%m-%d").date()
        booking_time = request.form.get("booking_time", "")
        technician_id = request.form.get("technician_id") or None
        lead_id = request.form.get("lead_id") or None
        status = request.form.get("status", "Pending")

        cust = Customer.query.filter_by(phone=phone).first()
        if not cust:
            cust = Customer(name=name, phone=phone, email=email or None,
                            address=address, city=city)
            db.session.add(cust); db.session.flush()

        b = Booking(
            customer_id=cust.id,
            service_id=service_id,
            booking_date=booking_date,
            booking_time=booking_time,
            address=address,
            technician_id=int(technician_id) if technician_id else None,
            lead_id=int(lead_id) if lead_id else None,
            status="Assigned" if technician_id and status == "Pending" else status,
        )
        db.session.add(b); db.session.flush()

        # Mark lead as converted
        if b.lead_id:
            lead = Lead.query.get(b.lead_id)
            if lead:
                lead.status = "Booking Created"

        db.session.commit()

        if b.status in ("Confirmed", "Assigned"):
            notify_booking_created(b)
        if b.technician_id:
            notify_technician_assigned(b)

        flash(f"Booking #{b.id} created.", "success")
        return redirect(url_for("admin.booking_detail", booking_id=b.id))

    lead_id = request.args.get("lead_id", type=int)
    lead = Lead.query.get(lead_id) if lead_id else None
    return render_template(
        "admin/booking_form.html",
        services=services, technicians=technicians, lead=lead,
    )


@bp.route("/bookings/<int:booking_id>")
@_admin_required
def booking_detail(booking_id):
    b = Booking.query.get_or_404(booking_id)
    technicians = User.query.filter_by(role="TECHNICIAN", is_active=True).all()
    return render_template("admin/booking_detail.html", booking=b, technicians=technicians)


@bp.route("/bookings/<int:booking_id>/update", methods=["POST"])
@_admin_required
def booking_update(booking_id):
    b = Booking.query.get_or_404(booking_id)
    action = request.form.get("action")
    notify = False

    if action == "confirm":
        b.status = "Confirmed"
        notify = True
    elif action == "assign":
        tid = request.form.get("technician_id", type=int)
        if tid:
            b.technician_id = tid
            b.status = "Assigned"
            notify = True
            if b.lead_id:
                lead = Lead.query.get(b.lead_id)
                if lead: lead.status = "Booking Created"
    elif action == "start":
        b.status = "In Progress"
    elif action == "complete":
        b.status = "Completed"
        b.completed_at = datetime.utcnow()
        notify = "completed"
    elif action == "cancel":
        b.status = "Cancelled"
    elif action == "edit":
        b.booking_date = datetime.strptime(request.form["booking_date"], "%Y-%m-%d").date()
        b.booking_time = request.form.get("booking_time", "")
        b.address = request.form.get("address", "")

    db.session.commit()

    if notify == True:
        notify_booking_created(b)
        if b.technician_id:
            notify_technician_assigned(b)
    elif notify == "completed":
        notify_service_completed(b)

    flash("Booking updated.", "success")
    return redirect(url_for("admin.booking_detail", booking_id=b.id))


# ---------- Technicians ----------
@bp.route("/technicians")
@_admin_required
def technicians():
    techs = User.query.filter_by(role="TECHNICIAN").order_by(User.name).all()
    return render_template("admin/technicians_list.html", techs=techs)


@bp.route("/technicians/new", methods=["GET", "POST"])
@_admin_required
def technician_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        u = User(name=name, email=email, phone=phone, role="TECHNICIAN", is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()
        flash("Technician added.", "success")
        return redirect(url_for("admin.technicians"))
    return render_template("admin/technician_form.html", tech=None)


@bp.route("/technicians/<int:tech_id>/edit", methods=["GET", "POST"])
@_admin_required
def technician_edit(tech_id):
    tech = User.query.get_or_404(tech_id)
    if request.method == "POST":
        tech.name = request.form["name"].strip()
        tech.email = request.form["email"].strip().lower()
        tech.phone = request.form.get("phone", "").strip()
        tech.is_active = bool(request.form.get("is_active"))
        pw = request.form.get("password", "")
        if pw:
            tech.set_password(pw)
        db.session.commit()
        flash("Technician updated.", "success")
        return redirect(url_for("admin.technicians"))
    return render_template("admin/technician_form.html", tech=tech)


@bp.route("/technicians/<int:tech_id>/toggle", methods=["POST"])
@_admin_required
def technician_toggle(tech_id):
    t = User.query.get_or_404(tech_id)
    t.is_active = not t.is_active
    db.session.commit()
    flash(f"Technician {'activated' if t.is_active else 'deactivated'}.", "info")
    return redirect(url_for("admin.technicians"))


@bp.route("/technicians/<int:tech_id>")
@_admin_required
def technician_jobs(tech_id):
    t = User.query.get_or_404(tech_id)
    jobs = Booking.query.filter_by(technician_id=t.id).order_by(Booking.booking_date.desc()).all()
    return render_template("admin/technician_jobs.html", tech=t, jobs=jobs)


# ---------- Services ----------
@bp.route("/services")
@_admin_required
def services():
    services = Service.query.order_by(Service.name).all()
    return render_template("admin/services_list.html", services=services)


@bp.route("/services/new", methods=["GET", "POST"])
@_admin_required
def service_new():
    if request.method == "POST":
        s = Service(
            name=request.form["name"].strip(),
            slug=(request.form.get("slug") or request.form["name"].lower().replace(" ", "-")).strip(),
            short_description=request.form.get("short_description", "").strip(),
            description=request.form.get("description", "").strip(),
            benefits=request.form.get("benefits", "").strip(),
            process=request.form.get("process", "").strip(),
            faq=request.form.get("faq", "").strip(),
            icon=request.form.get("icon", "bi-bug-fill").strip(),
            status="ACTIVE",
        )
        db.session.add(s); db.session.commit()
        flash("Service added.", "success")
        return redirect(url_for("admin.services"))
    return render_template("admin/service_form.html", service=None)


@bp.route("/services/<int:sid>/edit", methods=["GET", "POST"])
@_admin_required
def service_edit(sid):
    s = Service.query.get_or_404(sid)
    if request.method == "POST":
        s.name = request.form["name"].strip()
        s.slug = request.form.get("slug") or s.slug
        s.short_description = request.form.get("short_description", "")
        s.description = request.form.get("description", "")
        s.benefits = request.form.get("benefits", "")
        s.process = request.form.get("process", "")
        s.faq = request.form.get("faq", "")
        s.icon = request.form.get("icon", s.icon)
        s.status = request.form.get("status", s.status)
        db.session.commit()
        flash("Service updated.", "success")
        return redirect(url_for("admin.services"))
    return render_template("admin/service_form.html", service=s)


# ---------- Feedback ----------
@bp.route("/feedback")
@_admin_required
def feedback():
    fb = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template("admin/feedback_list.html", feedback=fb)


# ---------- Warranties ----------
@bp.route("/warranties")
@_admin_required
def warranties():
    items = all_warranties()
    return render_template("admin/warranties.html", items=items)


# ---------- Notifications ----------
@bp.route("/notifications")
@_admin_required
def notifications():
    notes = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()).limit(50).all()
    Notification.query.filter_by(user_id=current_user.id, status="unread").update(
        {"status": "read"})
    db.session.commit()
    return render_template("admin/notifications.html", notes=notes)
