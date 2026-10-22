"""Admin portal blueprint."""
from datetime import datetime, date, time, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from sqlalchemy.orm import subqueryload

from extensions import db
from models import (
    User, Customer, Service, Lead, Booking, Feedback, Notification,
    TechnicianService, TechnicianLeave,
)
from blueprints.auth import role_required
from notifications import (
    notify_booking_created, notify_technician_assigned, notify_service_completed,
    notify_lead_assigned, notify_admin_new_lead, notify_customer_appointment_booked,
    notify_new_booking, notify_new_enquiry,
)
from warranty import expiring_warranties, all_warranties
import scheduling
from scheduling import (
    availability_map, bookings_by_technician, compute_availability,
    conflict_summary, suggest_technicians, timeline_for, week_days,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_date_arg(name, default=None):
    raw = request.args.get(name, "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return default or date.today()


def _booking_conflicts(booking, technician, ignore_booking_id=None):
    """Conflicts for a technician on a booking's date."""
    if booking is None or technician is None:
        return []
    start = booking.start_time
    if start is None:
        return []
    start_min = scheduling.to_minutes(start)
    end_min = start_min + booking.duration_minutes
    return scheduling.overlapping_bookings(
        technician, booking.booking_date, start_min, end_min,
        ignore_booking_id=ignore_booking_id or booking.id,
    )



PERIODS = [
    ("today", "Today"),
    ("week", "This Week"),
    ("month", "This Month"),
    ("quarter", "This Quarter"),
    ("year", "This Year"),
    ("all", "All Time"),
]
PERIOD_LABELS = dict(PERIODS)


def _resolve_range(period, date_from=None, date_to=None):
    """Resolve a period preset (or custom from/to dates) into bounds.

    Returns (start_dt, end_dt, label) where bounds are datetimes and
    end_dt is an exclusive upper bound. Any bound may be None (open ended).
    """
    today = date.today()
    start = end = None
    label = "All Time"

    if period in (None, "", "custom"):
        if date_from:
            try:
                start = datetime.strptime(date_from, "%Y-%m-%d").date()
            except ValueError:
                start = None
        if date_to:
            try:
                end = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                end = None
        if start or end:
            label = "Custom Range"
    elif period == "today":
        start = end = today
        label = "Today"
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        label = "This Week"
    elif period == "month":
        start = today.replace(day=1)
        label = "This Month"
    elif period == "quarter":
        start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        label = "This Quarter"
    elif period == "year":
        start = date(today.year, 1, 1)
        label = "This Year"

    start_dt = datetime.combine(start, time.min) if start else None
    end_dt = datetime.combine(end + timedelta(days=1), time.min) if end else None
    return start_dt, end_dt, label


def _in_range(column, start_dt, end_dt):
    """Build a filter expression for column between start_dt and end_dt."""
    from sqlalchemy import and_

    clauses = []
    if start_dt is not None:
        clauses.append(column >= start_dt)
    if end_dt is not None:
        clauses.append(column < end_dt)
    return and_(*clauses) if clauses else True


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

    period = request.args.get("period", "month")
    if period not in PERIOD_LABELS:
        period = "month"
    start_dt, end_dt, period_label = _resolve_range(
        period,
        request.args.get("from"),
        request.args.get("to"),
    )

    def within(column):
        return _in_range(column, start_dt, end_dt)

    def count_leads(**extra):
        q = Lead.query.filter(within(Lead.created_at))
        if extra:
            q = q.filter_by(**extra)
        return q.count()

    def count_bookings(**extra):
        q = Booking.query.filter(within(Booking.created_at))
        if extra:
            q = q.filter_by(**extra)
        return q.count()

    feedback_q = Feedback.query.filter(within(Feedback.created_at))

    stats = {
        "total_leads": count_leads(),
        "new_leads": count_leads(status="New"),
        "bookings_created": count_bookings(),
        "upcoming_bookings": Booking.query.filter(
            Booking.booking_date >= today,
            Booking.status.in_(["Pending", "Confirmed", "Assigned", "In Progress"]),
        ).count(),
        "completed": Booking.query.filter(
            Booking.completed_at.isnot(None), within(Booking.completed_at)
        ).count(),
        "pending_jobs": Booking.query.filter(
            Booking.status.in_(["Confirmed", "Assigned", "In Progress"]),
            within(Booking.created_at),
        ).count(),
        "feedback_count": feedback_q.count(),
        "avg_rating": db.session.query(db.func.avg(Feedback.rating))
        .filter(within(Feedback.created_at))
        .scalar()
        or 0,
    }

    recent_leads = (
        Lead.query.filter(within(Lead.created_at))
        .order_by(Lead.created_at.desc())
        .limit(5)
        .all()
    )
    upcoming = (
        Booking.query.filter(Booking.booking_date >= today)
        .order_by(Booking.booking_date.asc())
        .limit(5)
        .all()
    )
    ex_warranties = expiring_warranties()[:5]

    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_leads=recent_leads,
        upcoming=upcoming,
        ex_warranties=ex_warranties,
        greeting=greeting,
        today=today,
        periods=PERIODS,
        period=period,
        period_label=period_label,
        period_start=start_dt,
    )


# ---------- Leads ----------
@bp.route("/leads")
@_admin_required
def leads():
    q = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    status = request.args.get("status", "").strip()
    period = request.args.get("period", "all")
    if period not in PERIOD_LABELS and period != "custom":
        period = "all"
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    start_dt, end_dt, period_label = _resolve_range(period, date_from, date_to)

    query = Lead.query.options(subqueryload(Lead.booking)).filter(_in_range(Lead.created_at, start_dt, end_dt))
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
        "admin/leads_list.html",
        leads=leads,
        q=q,
        source=source,
        status=status,
        periods=PERIODS,
        period=period,
        period_label=period_label,
        date_from=date_from,
        date_to=date_to,
        total=len(leads),
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
        notify_admin_new_lead(lead)
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
    if lead.assigned_to:
        notify_lead_assigned(lead)
    db.session.commit()
    flash("Technician assigned to lead.", "success")
    return redirect(url_for("admin.lead_detail", lead_id=lead.id))


# ---------- Bookings ----------
def _flash_whatsapp_result(result):
    """Tell the admin when the customer did not receive the WhatsApp."""
    if not result:
        return
    whatsapp_result = result.get("whatsapp")
    if whatsapp_result is not None and not whatsapp_result.ok:
        flash(
            f"WhatsApp was NOT sent to the customer - {whatsapp_result.detail}",
            "warning",
        )


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
            # The customer gets their "appointment booked" message here.
            _flash_whatsapp_result(notify_booking_created(b))
        else:
            # Still pending: tell the admins a booking request exists, but do
            # not message the customer until an admin confirms it.
            notify_new_booking(b)
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
    technicians = User.query.filter_by(role="TECHNICIAN", is_active=True).order_by(User.name).all()
    # Availability-aware suggestions for the assignment picker.
    suggestions = suggest_technicians(b, techs=technicians)
    summary = conflict_summary(suggestions)
    return render_template(
        "admin/booking_detail.html",
        booking=b,
        technicians=technicians,
        suggestions=suggestions,
        suggestion_summary=summary,
    )


@bp.route("/bookings/<int:booking_id>/assign", methods=["POST"])
@_admin_required
def booking_assign(booking_id):
    """Assign a technician, refusing a double booking."""
    b = Booking.query.get_or_404(booking_id)
    tech = User.query.get_or_404(request.form.get("technician_id", type=int))

    if tech.role != "TECHNICIAN":
        flash("That user is not a technician.", "danger")
        return redirect(url_for("admin.booking_detail", booking_id=b.id))

    clashes = _booking_conflicts(b, tech)
    if clashes:
        first = clashes[0]
        flash(
            f"{tech.name} is already booked {first.start_label} - {first.end_label} "
            f"({first.service_name}). Not assigned.",
            "warning",
        )
        return redirect(url_for("admin.booking_detail", booking_id=b.id))

    if not tech.can_do(b.service_id):
        flash(
            f"{tech.name} is not qualified for {b.service.name}. Not assigned.",
            "warning",
        )
        return redirect(url_for("admin.booking_detail", booking_id=b.id))

    b.technician_id = tech.id
    if b.status in ("Pending", "Confirmed"):
        b.status = "Assigned"
    if b.lead_id:
        lead = Lead.query.get(b.lead_id)
        if lead and lead.status != "Booking Created":
            lead.status = "Booking Created"
    db.session.commit()

    notify_technician_assigned(b)
    flash(f"Booking #{b.id} assigned to {tech.name}.", "success")
    return redirect(url_for("admin.booking_detail", booking_id=b.id))



@bp.route("/bookings/<int:booking_id>/resend-whatsapp", methods=["POST"])
@_admin_required
def booking_resend_whatsapp(booking_id):
    """Re-send the 'appointment booked' WhatsApp to the customer."""
    b = Booking.query.get_or_404(booking_id)
    result = notify_customer_appointment_booked(b)
    if result.ok:
        flash(f"WhatsApp sent to {b.customer.phone} - {result.detail}", "success")
    else:
        flash(f"WhatsApp not sent - {result.detail}", "warning")
    return redirect(url_for("admin.booking_detail", booking_id=b.id))


@bp.route("/bookings/<int:booking_id>/update", methods=["POST"])
@_admin_required
def booking_update(booking_id):
    b = Booking.query.get_or_404(booking_id)
    action = request.form.get("action")
    notify = False
    previous_status = b.status

    if action == "confirm":
        b.status = "Confirmed"
        notify = True
    elif action == "assign":
        tid = request.form.get("technician_id", type=int)
        if tid:
            tech = User.query.get(tid)
            clashes = _booking_conflicts(b, tech) if tech else []
            if clashes:
                first = clashes[0]
                flash(
                    f"{tech.name} is already booked {first.start_label} - {first.end_label} "
                    f"({first.service_name}). Not assigned.",
                    "warning",
                )
                db.session.rollback()
                return redirect(url_for("admin.booking_detail", booking_id=b.id))
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
        # Moving a job must not create a double booking.
        if b.technician_id:
            tech = User.query.get(b.technician_id)
            clashes = _booking_conflicts(b, tech) if tech else []
            if clashes:
                first = clashes[0]
                flash(
                    f"{tech.name} is already booked {first.start_label} - {first.end_label} "
                    f"({first.service_name}). Change not saved.",
                    "warning",
                )
                db.session.rollback()
                return redirect(url_for("admin.booking_detail", booking_id=b.id))

    db.session.commit()

    if notify == True:
        if b.status != previous_status:
            # Status changed -> the appointment is confirmed, tell the customer.
            _flash_whatsapp_result(notify_booking_created(b))
        else:
            flash(
                f"Booking is already '{b.status}' - no new message sent.",
                "info",
            )
        if b.technician_id:
            notify_technician_assigned(b)
    elif notify == "completed":
        notify_service_completed(b)

    flash("Booking updated.", "success")
    return redirect(url_for("admin.booking_detail", booking_id=b.id))


# ---------- Schedule board ----------
@bp.route("/schedule")
@_admin_required
def schedule():
    """Visual day board: who is free, who is busy, and what is unassigned."""
    day = _parse_date_arg("date", date.today())
    tech_filter = request.args.get("tech", "").strip()

    techs = (
        User.query.filter_by(role="TECHNICIAN")
        .order_by(User.name)
        .all()
    )
    if tech_filter:
        try:
            techs = [t for t in techs if t.id == int(tech_filter)]
        except ValueError:
            techs = []

    visible_ids = [t.id for t in techs]
    grouped = bookings_by_technician(day, visible_ids)

    # Unassigned jobs for the day.
    unassigned = (
        Booking.query.filter(
            Booking.booking_date == day,
            Booking.technician_id.is_(None),
            Booking.status.notin_(scheduling.CLOSED_STATUSES),
        )
        .order_by(Booking.booking_time.is_(None), Booking.booking_time, Booking.id)
        .all()
    )

    # Every technician (including filtered-out ones) so the assign menu can
    # offer a good technician even when the board is filtered.
    all_techs = User.query.filter_by(role="TECHNICIAN").order_by(User.name).all()
    all_grouped = bookings_by_technician(day, [t.id for t in all_techs])

    rows = []
    for tech in techs:
        avail = compute_availability(tech, day, bookings=grouped.get(tech.id))
        rows.append({"tech": tech, "availability": avail})

    # Suggestions per unassigned booking (used by the quick-assign menu).
    assign_options = {}
    for booking in unassigned:
        options = []
        for tech in all_techs:
            if not tech.is_active:
                continue
            avail = compute_availability(
                tech, day, bookings=all_grouped.get(tech.id), service_id=booking.service_id
            )
            clash = []
            start = booking.start_time
            if start is not None and avail.working and not avail.on_leave:
                s_min = scheduling.to_minutes(start)
                e_min = s_min + booking.duration_minutes
                clash = scheduling.conflicts(avail.blocks, s_min, e_min, booking.id)
            options.append({
                "tech": tech,
                "availability": avail,
                "busy": bool(clash),
                "off": avail.is_off,
                "unqualified": not avail.skills_ok,
                "reason": (
                    "On leave" if avail.on_leave
                    else ("Not working" if not avail.working
                          else ("Not qualified" if not avail.skills_ok
                                else ("Busy" if clash else "Free")))
                ),
            })
        assign_options[booking.id] = options

    timeline = timeline_for(day)
    week = week_days(day)

    # Day totals for the summary strip.
    total_booked = sum(r["availability"].booked_minutes for r in rows)
    total_capacity = sum(r["availability"].capacity_minutes for r in rows)
    free_techs = sum(1 for r in rows if r["availability"].state == "free")
    busy_techs = sum(1 for r in rows if r["availability"].state in ("busy", "full"))
    off_techs = sum(1 for r in rows if r["availability"].is_off)

    return render_template(
        "admin/schedule.html",
        day=day,
        timeline=timeline,
        rows=rows,
        unassigned=unassigned,
        assign_options=assign_options,
        all_techs=all_techs,
        tech_filter=tech_filter,
        week=week,
        today=date.today(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        total_booked=total_booked,
        total_capacity=total_capacity,
        free_techs=free_techs,
        busy_techs=busy_techs,
        off_techs=off_techs,
        travel_buffer=current_app.config.get("TRAVEL_BUFFER_MINUTES", 30),
    )


@bp.route("/schedule/assign", methods=["POST"])
@_admin_required
def schedule_assign():
    """Assign a job to a technician straight from the board."""
    booking_id = request.form.get("booking_id", type=int)
    technician_id = request.form.get("technician_id", type=int)
    booking = Booking.query.get_or_404(booking_id)
    tech = User.query.get_or_404(technician_id)

    if tech.role != "TECHNICIAN":
        flash("That user is not a technician.", "danger")
        return redirect(url_for("admin.schedule", date=booking.booking_date.isoformat()))

    clashes = _booking_conflicts(booking, tech)
    if clashes:
        first = clashes[0]
        flash(
            f"{tech.name} is already booked {first.start_label} - {first.end_label} "
            f"({first.service_name}). Not assigned.",
            "warning",
        )
        return redirect(url_for("admin.schedule", date=booking.booking_date.isoformat()))

    if not tech.can_do(booking.service_id):
        flash(
            f"{tech.name} is not qualified for {booking.service.name}. Not assigned.",
            "warning",
        )
        return redirect(url_for("admin.schedule", date=booking.booking_date.isoformat()))

    was_unassigned = booking.technician_id is None
    booking.technician_id = tech.id
    if booking.status == "Pending":
        booking.status = "Assigned"
    if booking.lead_id:
        lead = Lead.query.get(booking.lead_id)
        if lead:
            lead.status = "Booking Created"
    db.session.commit()

    if was_unassigned:
        notify_technician_assigned(booking)
    flash(f"Booking #{booking.id} assigned to {tech.name}.", "success")
    return redirect(url_for("admin.schedule", date=booking.booking_date.isoformat()))


@bp.route("/schedule/unassign", methods=["POST"])
@_admin_required
def schedule_unassign():
    booking_id = request.form.get("booking_id", type=int)
    booking = Booking.query.get_or_404(booking_id)
    booking.technician_id = None
    if booking.status == "Assigned":
        booking.status = "Pending"
    db.session.commit()
    flash(f"Booking #{booking.id} is unassigned again.", "info")
    return redirect(url_for("admin.schedule", date=booking.booking_date.isoformat()))


@bp.route("/schedule/reschedule", methods=["POST"])
@_admin_required
def schedule_reschedule():
    """Move a job to another technician and/or another time."""
    booking_id = request.form.get("booking_id", type=int)
    booking = Booking.query.get_or_404(booking_id)
    technician_id = request.form.get("technician_id", type=int)
    new_date_raw = request.form.get("booking_date", "").strip()
    new_time = request.form.get("booking_time", "").strip()

    new_date = booking.booking_date
    if new_date_raw:
        try:
            new_date = datetime.strptime(new_date_raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    if new_time:
        booking.booking_time = new_time
    booking.booking_date = new_date

    tech = User.query.get(technician_id) if technician_id else None
    if tech:
        clashes = _booking_conflicts(booking, tech)
        if clashes:
            first = clashes[0]
            booking.booking_date = new_date
            flash(
                f"{tech.name} is already booked {first.start_label} - {first.end_label} "
                f"({first.service_name}). Not moved.",
                "warning",
            )
            db.session.commit()
            return redirect(url_for("admin.schedule", date=new_date.isoformat()))
        booking.technician_id = tech.id
        if booking.status == "Pending":
            booking.status = "Assigned"

    db.session.commit()
    flash(f"Booking #{booking.id} rescheduled to {new_date.strftime('%d %b %Y')}.", "success")
    return redirect(url_for("admin.schedule", date=new_date.isoformat()))


# ---------- Technicians ----------
@bp.route("/technicians")
@_admin_required
def technicians():
    techs = User.query.filter_by(role="TECHNICIAN").order_by(User.name).all()
    day = _parse_date_arg("date", date.today())
    grouped = bookings_by_technician(day, [t.id for t in techs])
    summaries = [
        scheduling.technician_summary(t, day, bookings=grouped.get(t.id))
        for t in techs
    ]
    services = Service.query.order_by(Service.name).all()
    leaves = (
        TechnicianLeave.query.join(User, TechnicianLeave.technician_id == User.id)
        .order_by(TechnicianLeave.start_date.desc())
        .all()
    )
    return render_template(
        "admin/technicians_list.html",
        techs=techs,
        summaries=summaries,
        services=services,
        leaves=leaves,
        day=day,
        today=date.today(),
    )



@bp.route("/technicians/new", methods=["GET", "POST"])
@_admin_required
def technician_new():
    services = Service.query.order_by(Service.name).all()
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        whatsapp = request.form.get("whatsapp", "").strip()
        password = request.form["password"]
        u = User(name=name, email=email, phone=phone, whatsapp=whatsapp or None,
                 role="TECHNICIAN", is_active=True)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        _apply_schedule_settings(u, request.form)
        db.session.commit()
        flash("Technician added.", "success")
        return redirect(url_for("admin.technicians"))
    return render_template("admin/technician_form.html", tech=None, services=services)


def _apply_schedule_settings(user, form):
    """Copy working hours / skills from a submitted form."""
    work_start = (form.get("work_start") or "").strip()
    work_end = (form.get("work_end") or "").strip()
    if work_start:
        user.work_start = work_start
    if work_end:
        user.work_end = work_end

    days = form.getlist("work_days")
    if days:
        user.work_days = ",".join(str(d) for d in sorted({int(d) for d in days if str(d).isdigit()}))
    elif "work_days" in form:
        user.work_days = ""

    # Skills: the form always posts the full list of selected services.
    # Only the difference is written - replacing the whole collection would
    # delete and re-insert the same primary keys.
    if "skills" in form:
        wanted = {int(s) for s in form.getlist("skills") if str(s).isdigit()}
        current = {row.service_id for row in user.skills}
        for row in list(user.skills):
            if row.service_id not in wanted:
                db.session.delete(row)
        for sid in sorted(wanted - current):
            user.skills.append(TechnicianService(service_id=sid))


@bp.route("/technicians/<int:tech_id>/edit", methods=["GET", "POST"])
@_admin_required
def technician_edit(tech_id):
    tech = User.query.get_or_404(tech_id)
    services = Service.query.order_by(Service.name).all()
    if request.method == "POST":
        tech.name = request.form["name"].strip()
        tech.email = request.form["email"].strip().lower()
        tech.phone = request.form.get("phone", "").strip()
        tech.whatsapp = request.form.get("whatsapp", "").strip() or None
        # An unticked box must not silently deactivate the technician.
        tech.is_active = request.form.get("is_active") in ("on", "true", "1", "yes")
        pw = request.form.get("password", "")
        if pw:
            tech.set_password(pw)
        _apply_schedule_settings(tech, request.form)
        db.session.commit()
        flash("Technician updated.", "success")
        return redirect(url_for("admin.technicians"))
    return render_template(
        "admin/technician_form.html", tech=tech, services=services
    )


@bp.route("/technicians/<int:tech_id>/leave", methods=["POST"])
@_admin_required
def technician_leave_add(tech_id):
    """Add a time-off entry for a technician."""
    tech = User.query.get_or_404(tech_id)
    start_raw = request.form.get("start_date", "").strip()
    end_raw = request.form.get("end_date", "").strip() or start_raw
    reason = request.form.get("reason", "").strip()
    try:
        start = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid leave dates.", "danger")
        return redirect(url_for("admin.technicians"))
    if end < start:
        start, end = end, start
    leave = TechnicianLeave(
        technician_id=tech.id, start_date=start, end_date=end, reason=reason or None
    )
    db.session.add(leave)
    db.session.commit()
    flash(
        f"Time off added for {tech.name} "
        f"({start.strftime('%d %b')} – {end.strftime('%d %b')}).",
        "success",
    )
    return redirect(url_for("admin.technicians"))


@bp.route("/technicians/leave/add", methods=["POST"])
@_admin_required
def technician_leave_add_any():
    """Add time off for the technician chosen in the form."""
    tech_id = request.form.get("technician_id", type=int)
    if not tech_id:
        flash("Pick a technician first.", "danger")
        return redirect(url_for("admin.technicians"))
    return technician_leave_add(tech_id)



@bp.route("/technicians/leave/<int:leave_id>/delete", methods=["POST"])
@_admin_required
def technician_leave_delete(leave_id):
    leave = TechnicianLeave.query.get_or_404(leave_id)
    tech = leave.technician
    db.session.delete(leave)
    db.session.commit()
    flash(f"Time off removed for {tech.name if tech else 'technician'}.", "info")
    return redirect(url_for("admin.technicians"))



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
        minutes = request.form.get("estimated_minutes", type=int) or current_app.config.get(
            "DEFAULT_JOB_MINUTES", 90
        )
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
            estimated_minutes=minutes,
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
        minutes = request.form.get("estimated_minutes", type=int)
        if minutes and minutes > 0:
            s.estimated_minutes = minutes
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
    # Remember which ones were unread *before* clearing the flag, so the page
    # can still highlight them.
    unread_ids = {
        n.id for n in notes if n.status == "unread"
    }
    Notification.query.filter_by(user_id=current_user.id, status="unread").update(
        {"status": "read"})
    db.session.commit()
    return render_template(
        "admin/notifications.html", notes=notes, unread_ids=unread_ids
    )
