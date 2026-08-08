"""Public-facing blueprint (Home, About, Services, Contact, Enquiry)."""
from datetime import datetime
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from extensions import db
from models import Customer, Service, Lead, Feedback

bp = Blueprint("public", __name__)


def _get_or_create_customer(name, phone, email, address, city):
    phone = (phone or "").strip()
    customer = Customer.query.filter_by(phone=phone).first() if phone else None
    if not customer:
        customer = Customer(
            name=name.strip(),
            phone=phone,
            email=(email or "").strip().lower() or None,
            address=address,
            city=city,
        )
        db.session.add(customer)
        db.session.flush()
    else:
        # Update known fields if missing/changed
        if email and not customer.email:
            customer.email = email.strip().lower()
        if address and not customer.address:
            customer.address = address
        if city and not customer.city:
            customer.city = city
    return customer


@bp.route("/")
def home():
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    # Latest 5 feedback for testimonials
    testimonials = (
        Feedback.query.order_by(Feedback.created_at.desc()).limit(5).all()
    )
    return render_template(
        "public/home.html", services=services, testimonials=testimonials
    )


@bp.route("/about")
def about():
    return render_template("public/about.html")


@bp.route("/services")
def services():
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    return render_template("public/services.html", services=services)


@bp.route("/services/<slug>")
def service_detail(slug):
    service = Service.query.filter_by(slug=slug, status="ACTIVE").first_or_404()
    return render_template("public/service_detail.html", service=service)


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        service_id = request.form.get("service_id") or None
        preferred_date_raw = request.form.get("preferred_date", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not phone:
            flash("Name and phone are required.", "danger")
            return render_template(
                "public/contact.html", services=services, form=request.form
            )

        preferred_date = None
        if preferred_date_raw:
            try:
                preferred_date = datetime.strptime(preferred_date_raw, "%Y-%m-%d").date()
            except ValueError:
                pass

        customer = _get_or_create_customer(name, phone, email, address, city)

        lead = Lead(
            customer_id=customer.id,
            service_id=int(service_id) if service_id else None,
            source="Website",
            message=message,
            preferred_date=preferred_date,
            status="New",
        )
        db.session.add(lead)
        db.session.commit()

        flash(
            "Thank you! Your enquiry has been received. Our team will contact you shortly.",
            "success",
        )
        return redirect(url_for("public.contact"))

    return render_template("public/contact.html", services=services, form={})


@bp.route("/feedback/<int:booking_id>", methods=["GET", "POST"])
def feedback(booking_id):
    booking = Feedback.query.filter_by(booking_id=booking_id).first()
    if booking:
        flash("Feedback already submitted for this booking. Thank you!", "info")
        return render_template("public/feedback_done.html")
    from models import Booking

    bk = Booking.query.get_or_404(booking_id)
    if bk.status != "Completed":
        flash("Feedback is available only after service completion.", "warning")
        return redirect(url_for("public.home"))

    if request.method == "POST":
        try:
            rating = int(request.form.get("rating", 0))
        except ValueError:
            rating = 0
        comments = request.form.get("comments", "").strip()
        if rating < 1 or rating > 5:
            flash("Please choose a rating between 1 and 5 stars.", "danger")
            return render_template("public/feedback.html", booking=bk)
        fb = Feedback(
            booking_id=bk.id,
            customer_id=bk.customer_id,
            technician_id=bk.technician_id,
            rating=rating,
            comments=comments,
        )
        db.session.add(fb)
        db.session.commit()
        return render_template("public/feedback_done.html")

    return render_template("public/feedback.html", booking=bk)
