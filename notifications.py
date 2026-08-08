"""Email + in-app notification helpers."""
import logging
from datetime import datetime
from flask import current_app, render_template, url_for
from flask_mail import Message
from extensions import db, mail
from models import Notification

log = logging.getLogger(__name__)


def send_email(subject: str, recipients: list[str], html_body: str, text_body: str = ""):
    """Best-effort email send. Logs failures instead of raising."""
    if not recipients or not current_app.config.get("MAIL_USERNAME"):
        log.warning("Mail not configured or no recipients — skipping email '%s'", subject)
        return False
    try:
        msg = Message(
            subject=subject,
            sender=current_app.config["MAIL_DEFAULT_SENDER"],
            recipients=recipients,
        )
        msg.html = html_body
        if text_body:
            msg.body = text_body
        mail.send(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.exception("Email send failed: %s", exc)
        return False


def inapp_notify(user_id: int, ntype: str, message: str, link: str | None = None):
    n = Notification(
        user_id=user_id,
        type=ntype,
        message=message,
        link=link,
    )
    db.session.add(n)
    return n


def notify_booking_created(booking):
    """Customer + admin notifications when a booking is confirmed."""
    business = current_app.config["BUSINESS_NAME"]
    customer = booking.customer
    service = booking.service

    # In-app notification to all admins (created by whoever)
    from models import User

    for admin in User.query.filter_by(role="ADMIN", is_active=True).all():
        inapp_notify(
            admin.id,
            "booking_created",
            f"New booking #{booking.id} for {service.name} by {customer.name}",
            link=url_for("admin.booking_detail", booking_id=booking.id),
        )

    # Email customer
    if customer.email:
        html = render_template(
            "emails/booking_confirmed.html",
            booking=booking,
            customer=customer,
            service=service,
            business_name=business,
        )
        send_email(
            f"Booking confirmed — {service.name} ({business})",
            [customer.email],
            html,
        )


def notify_technician_assigned(booking):
    technician = booking.technician
    if not technician:
        return
    customer = booking.customer
    service = booking.service
    inapp_notify(
        technician.id,
        "technician_assigned",
        f"New job assigned: {service.name} for {customer.name} on {booking.booking_date}",
        link=url_for("technician.job_detail", booking_id=booking.id),
    )
    if technician.email:
        html = render_template(
            "emails/technician_assigned.html",
            booking=booking,
            customer=customer,
            service=service,
            technician=technician,
            business_name=current_app.config["BUSINESS_NAME"],
        )
        send_email(
            f"New job assigned: {service.name} — {customer.name}",
            [technician.email],
            html,
        )


def notify_service_completed(booking):
    business = current_app.config["BUSINESS_NAME"]
    customer = booking.customer
    service = booking.service

    feedback_url = url_for("public.feedback", booking_id=booking.id, _external=True)

    # Customer: thank-you + feedback link
    if customer.email:
        html = render_template(
            "emails/service_completed.html",
            booking=booking,
            customer=customer,
            service=service,
            business_name=business,
            feedback_url=feedback_url,
            warranty_days=current_app.config["WARRANTY_DAYS"],
        )
        send_email(
            f"Service completed — share your feedback ({business})",
            [customer.email],
            html,
        )

    # In-app for admins
    from models import User

    for admin in User.query.filter_by(role="ADMIN", is_active=True).all():
        inapp_notify(
            admin.id,
            "service_completed",
            f"Service completed: {service.name} for {customer.name}",
            link=url_for("admin.booking_detail", booking_id=booking.id),
        )


def notify_warranty_reminder(booking, days_left: int):
    """Send warranty-expiring reminder to customer."""
    business = current_app.config["BUSINESS_NAME"]
    customer = booking.customer
    service = booking.service
    if not customer or not customer.email:
        return False
    html = render_template(
        "emails/warranty_reminder.html",
        booking=booking,
        customer=customer,
        service=service,
        business_name=business,
        days_left=days_left,
        warranty_end=booking.warranty_end,
        book_url=url_for("public.contact", _external=True),
    )
    ok = send_email(
        f"Your {service.name} warranty expires in {days_left} days",
        [customer.email],
        html,
    )
    return ok
