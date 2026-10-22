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
    jsonify,
)
from catalog import group_services_map
from extensions import db
from models import Customer, Service, Lead, Booking, Feedback
from notifications import (
    notify_admin_new_lead,
    notify_admin_new_booking,
)
from whatsapp import digits_only

bp = Blueprint("public", __name__)


def _phone_error(phone):
    """Return an error message when the captured number is obviously unusable."""
    digits = digits_only(phone)
    if len(digits) < 10:
        return "Please enter a valid mobile number (at least 10 digits)."
    if len(digits) > 15:
        return "That mobile number looks too long - please check it."
    return None


def _phone_digits_expr(column):
    """SQL expression that strips common separators from a stored phone."""
    expr = column
    for ch in (" ", "-", "+", "(", ")", "."):
        expr = db.func.replace(expr, ch, "")
    return expr


def _find_customer_by_phone(digits):
    """Find a customer by phone, ignoring spacing/format differences."""
    if not digits:
        return None
    candidates = {digits}
    cc = str(current_app.config.get("DEFAULT_COUNTRY_CODE", "91")).lstrip("+")
    if len(digits) == 10:
        candidates.add(cc + digits)
    expr = _phone_digits_expr(Customer.phone)
    return Customer.query.filter(expr.in_(list(candidates))).first()


def _get_or_create_customer(name, phone, email, address, city):
    raw = (phone or "").strip()
    digits = digits_only(raw)
    customer = _find_customer_by_phone(digits)
    if not customer:
        customer = Customer(
            name=name.strip(),
            phone=digits or raw,
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


def _service_map():
    """Active services grouped into {category: [{id, name, slug}]} for the picker."""
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    return group_services_map(services)


def _parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


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


@bp.route("/services/cleaning")
def cleaning_services():
    cleaning_options = [
        {"name": "Commercial Cleaning", "icon": "bi-building", "slug": "commercial-cleaning",
         "image": "images/cleaning/commercial cleaning.png",
         "description": "End-to-end cleaning for offices, gyms, restaurants, and event venues that meet health and safety standards."},
        {"name": "Industrial Cleaning", "icon": "bi-factory", "slug": "industrial-cleaning",
         "image": "images/cleaning/Industrial Cleaning.png",
         "description": "Heavy-duty cleaning of machinery, tanks, and plants with safety-first crews and rapid turnaround."},
        {"name": "Society Cleaning", "icon": "bi-houses", "slug": "society-cleaning",
         "image": "images/cleaning/Society Cleaning.png",
         "description": "Complete housekeeping for corridors, terraces, and gardens to keep residential societies spotless."},
        {"name": "House Cleaning", "icon": "bi-house-heart", "slug": "house-cleaning",
         "image": "images/cleaning/house cleaning.png",
         "description": "Deep home cleaning covering rooms, carpets, upholstery, and high-speed floor scrubbing and polishing."},
        {"name": "Water Tank Cleaning", "icon": "bi-droplet", "slug": "water-tank-cleaning",
         "image": "images/cleaning/Water Tank Cleaning.png",
         "description": "Sludge and algae removal by vetted professionals to keep your stored water pure and hygienic."},
    ]
    return render_template("public/cleaning_services.html", options=cleaning_options)


@bp.route("/services/pest-control")
def pest_control_services():
    pest_options = [
        {"name": "Ant Management", "icon": "\U0001F41C", "slug": "ant-management",
         "image": "images/pests/ant-management.jpg",
         "description": "Targeted gel and spray treatments that eliminate ant colonies at the source and block re-entry."},
        {"name": "Bed Bug Management", "icon": "\U0001F6CF\uFE0F", "slug": "bed-bug-management",
         "image": "images/pests/bed-bug-management.jpg",
         "description": "Discreet heat and chemical treatments that eradicate bed bugs from mattresses, furniture, and upholstery."},
        {"name": "Cockroach Management", "icon": "\U0001FAB3", "slug": "cockroach-management",
         "image": "images/pests/cockroach-management.jpg",
         "description": "Advanced gel baits and surface sprays that wipe out cockroaches and prevent further breeding."},
        {"name": "Fly Management", "icon": "\U0001FAB0", "slug": "fly-management",
         "image": "images/pests/fly-management.jpg",
         "description": "Traps, misting, and residual treatments that control flying insects in homes and commercial spaces."},
        {"name": "Lizard Management", "icon": "\U0001F98E", "slug": "lizard-management",
         "image": "images/pests/lizard-management.jpg",
         "description": "Safe repellent treatments that drive lizards out of living and work areas without harming them."},
        {"name": "Mosquito Management", "icon": "\U0001F99F", "slug": "mosquito-management",
         "image": "images/pests/mosquito-management.jpg",
         "description": "Larviciding and fogging solutions that break the mosquito breeding cycle and prevent diseases."},
        {"name": "Prophylactic Treatment", "icon": "\U0001F6E1\uFE0F", "slug": "prophylactic-treatment",
         "image": "images/pests/prophylactic-treatment.jpg",
         "description": "Preventive barrier treatment for new and renovated properties to stop infestations before they start."},
        {"name": "Termite Treatment", "icon": "\U0001F3E0", "slug": "termite-treatment",
         "image": "images/pests/termite-treatment.jpg",
         "description": "Anti-termite soil treatment and wall injection that protects your structure from costly termite damage."},
        {"name": "Rodent Management", "icon": "\U0001F400", "slug": "rodent-management",
         "image": "images/pests/rodent-management.jpg",
         "description": "Baiting, trapping, and proofing systems that remove rats and mice and seal their entry points."},
        {"name": "Spider Management", "icon": "\U0001F577\uFE0F", "slug": "spider-management",
         "image": "images/pests/spider-management.jpg",
         "description": "Cobweb removal and residual treatment that keeps webs and spiders away from walls and ceilings."},
        {"name": "Wood Borer Management", "icon": "\U0001FAB5", "slug": "wood-borer-management",
         "image": "images/pests/wood-borer-management.jpg",
         "description": "Targeted treatment that eliminates wood borers and protects furniture, doors, and wooden fixtures."},
    ]
    return render_template("public/pest_control_services.html", options=pest_options)


@bp.route("/services/bird-netting")
def bird_netting_services():
    netting_options = [
        {"name": "Society Bird Netting", "slug": "society-bird-netting",
         "image": "images/netting/society bird netting.jpg",
         "description": "Full-coverage netting for society balconies, terraces, and common areas to keep birds away safely."},
        {"name": "Industrial Bird Netting", "slug": "industrial-bird-netting",
         "image": "images/netting/Industrial Bird Netting.png",
         "description": "Heavy-duty netting for warehouses, factories, and industrial sheds that protects goods and machinery."},
        {"name": "Residential Bird Netting", "slug": "residential-bird-netting",
         "image": "images/netting/Residential Bird netting.png",
         "description": "Discreet, durable netting for homes and apartments that keeps balconies and windows bird-free."},
    ]
    return render_template("public/bird_netting_services.html", options=netting_options)


@bp.route("/services/<slug>")
def service_detail(slug):
    service = Service.query.filter_by(slug=slug, status="ACTIVE").first_or_404()
    return render_template("public/service_detail.html", service=service)


@bp.route("/get-started", methods=["GET", "POST"])
def get_started():
    """Shareable customer form — Enquire Now or Book Now in one page."""
    service_map = _service_map()

    mode = (request.form.get("mode") or request.args.get("mode") or "enquire").lower()
    if mode not in ("enquire", "book"):
        mode = "enquire"
    preselect_slug = request.args.get("service", "").strip()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        service_id = request.form.get("service_id") or None
        preferred_date_raw = request.form.get("preferred_date", "").strip()
        preferred_time = request.form.get("preferred_time", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not phone:
            flash("Name and mobile number are required.", "danger")
            return render_template(
                "public/get_started.html", service_map=service_map,
                mode=mode, form=request.form, preselect_slug=preselect_slug,
            )

        phone_error = _phone_error(phone)
        if phone_error:
            flash(phone_error, "danger")
            return render_template(
                "public/get_started.html", service_map=service_map,
                mode=mode, form=request.form, preselect_slug=preselect_slug,
            )

        preferred_date = _parse_date(preferred_date_raw)
        customer = _get_or_create_customer(name, phone, email, address, city)

        if mode == "book":
            if not service_id:
                flash("Please select the service you want to book.", "danger")
                return render_template(
                    "public/get_started.html", service_map=service_map,
                    mode=mode, form=request.form, preselect_slug=preselect_slug,
                )
            if not preferred_date:
                flash("Please choose a preferred date for your booking.", "danger")
                return render_template(
                    "public/get_started.html", service_map=service_map,
                    mode=mode, form=request.form, preselect_slug=preselect_slug,
                )
            booking = Booking(
                customer_id=customer.id,
                service_id=int(service_id),
                booking_date=preferred_date,
                booking_time=preferred_time,
                address=address,
                notes=message or None,
                status="Pending",
            )
            db.session.add(booking)
            db.session.commit()
            notify_admin_new_booking(booking)
            flash(
                f"Thank you! Booking request #{booking.id} received. "
                "Our team will confirm your slot shortly.",
                "success",
            )
            return redirect(url_for("public.get_started", mode="book", done=1))

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
        notify_admin_new_lead(lead)
        flash(
            "Thank you! Your enquiry has been received. Our team will contact you shortly.",
            "success",
        )
        return redirect(url_for("public.get_started", mode="enquire", done=1))

    return render_template(
        "public/get_started.html", service_map=service_map,
        mode=mode, form={}, preselect_slug=preselect_slug,
    )


@bp.route("/quote", methods=["POST"])
def quote():
    """Quick 'Get Quote' capture (name + mobile + service type) -> creates a Lead."""
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    service_id = request.form.get("service_id") or None
    service_category = request.form.get("service_category", "").strip()
    service_name = request.form.get("service_name", "").strip()

    if not name or not phone:
        return jsonify(ok=False, error="Please enter your name and mobile number."), 400

    phone_error = _phone_error(phone)
    if phone_error:
        return jsonify(ok=False, error=phone_error), 400

    service = None
    if service_id:
        try:
            service = db.session.get(Service, int(service_id))
        except (TypeError, ValueError):
            service = None

    if service is None and not service_category:
        return jsonify(ok=False, error="Please select the service type."), 400

    if service is not None:
        service_name = service.name
    elif not service_name:
        service_name = service_category

    customer = _get_or_create_customer(name, phone, "", "", "")
    lead = Lead(
        customer_id=customer.id,
        service_id=service.id if service else None,
        service_category=service_category or None,
        source="Get Quote",
        message=f"Quote request: {service_name}" if service_name else "Quote request",
        status="New",
    )
    db.session.add(lead)
    db.session.commit()
    notify_admin_new_lead(lead)
    return jsonify(ok=True, message="Thank you! Our team will shortly reach out to you.")


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    service_map = _service_map()
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
                "public/contact.html", services=services,
                service_map=service_map, form=request.form,
            )

        phone_error = _phone_error(phone)
        if phone_error:
            flash(phone_error, "danger")
            return render_template(
                "public/contact.html", services=services,
                service_map=service_map, form=request.form,
            )

        preferred_date = _parse_date(preferred_date_raw)

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

        notify_admin_new_lead(lead)

        flash(
            "Thank you! Your enquiry has been received. Our team will contact you shortly.",
            "success",
        )
        return redirect(url_for("public.contact"))

    return render_template(
        "public/contact.html", services=services,
        service_map=service_map, form={},
    )


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
