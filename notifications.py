"""Email + in-app + WhatsApp notification helpers."""
import logging
from datetime import datetime
from flask import current_app, render_template, url_for
from flask_mail import Message
from extensions import db, mail
from models import Notification
from whatsapp import (
    send_whatsapp,
    send_whatsapp_result,
    admin_numbers,
    display_phone,
    wait_for_delivery,
    error_hint,
)

log = logging.getLogger(__name__)

# -----------------------------
# Notification types (in-app)
# -----------------------------
NT_NEW_ENQUIRY = "new_enquiry"
NT_NEW_BOOKING = "new_booking"
NT_BOOKING_CREATED = "booking_created"
NT_TECHNICIAN_ASSIGNED = "technician_assigned"
NT_LEAD_ASSIGNED = "lead_assigned"
NT_SERVICE_COMPLETED = "service_completed"
NT_WARRANTY_REMINDER = "warranty_reminder"
NT_WHATSAPP_FAILED = "whatsapp_failed"


def send_email(subject: str, recipients: list[str], html_body: str, text_body: str = ""):
    """Best-effort email send. Logs failures instead of raising."""
    if not recipients:
        log.warning("No recipients - skipping email '%s'", subject)
        return False
    username = current_app.config.get("MAIL_USERNAME") or ""
    if not username:
        log.warning(
            "MAIL_USERNAME is not set - skipping email '%s'. "
            "Set MAIL_USERNAME/MAIL_PASSWORD in .env to enable email.",
            subject,
        )
        return False
    if "your-email" in username or "your-app-password" in (
        current_app.config.get("MAIL_PASSWORD") or ""
    ):
        log.warning(
            "Mail credentials are still the placeholder values from .env - "
            "skipping email '%s'. Set a real Gmail address + App Password.",
            subject,
        )
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
    """Add an in-app notification to the session (NOT committed)."""
    n = Notification(
        user_id=user_id,
        type=ntype,
        message=message,
        link=link,
    )
    db.session.add(n)
    return n


# -----------------------------
# Core notification layer
# -----------------------------

def _admin_users():
    from models import User

    return User.query.filter_by(role="ADMIN", is_active=True).all()


def notify_users(user_ids, ntype: str, message: str, link: str | None = None,
                 commit: bool = True) -> int:
    """Create in-app notifications for the given users.

    The rows are committed here, otherwise Flask-SQLAlchemy discards them
    when the request ends (an uncommitted session is rolled back).
    """
    count = 0
    for uid in user_ids:
        if not uid:
            continue
        inapp_notify(uid, ntype, message[:255], link)
        count += 1
    if count and commit:
        db.session.commit()
    return count


def notify_admins(ntype: str, message: str, link: str | None = None,
                   commit: bool = True) -> int:
    """Create an in-app notification for every active admin."""
    return notify_users(
        [u.id for u in _admin_users()], ntype, message, link, commit
    )


def admin_emails() -> list[str]:
    """Addresses that receive the admin notification emails."""
    raw = (
        current_app.config.get("ADMIN_EMAIL")
        or current_app.config.get("BUSINESS_EMAIL")
        or ""
    )
    return [e.strip() for e in raw.split(",") if "@" in e]


def email_admins(subject: str, template: str, **context) -> bool:
    """Email every admin using the given template. Best effort."""
    if not current_app.config.get("NOTIFY_ADMIN_EMAIL", True):
        log.info("Admin email notifications disabled - skipping '%s'", subject)
        return False
    recipients = admin_emails()
    if not recipients:
        log.warning("No ADMIN_EMAIL configured - skipping email '%s'", subject)
        return False
    html = render_template(
        template,
        business_name=current_app.config["BUSINESS_NAME"],
        **context,
    )
    return send_email(subject, recipients, html)


def whatsapp_admins(body: str) -> bool:
    """Send a WhatsApp alert to every configured admin number."""
    sent = False
    for number in admin_numbers():
        if send_whatsapp(number, body):
            sent = True
    return sent


# -----------------------------
# New enquiry
# -----------------------------

def enquiry_received_message(lead) -> str:
    """The 'we have your enquiry' message sent to the customer."""
    customer = lead.customer
    service = (
        lead.service.name
        if lead.service
        else (getattr(lead, "service_category", None) or "our services")
    )
    business = current_app.config["BUSINESS_NAME"]
    business_wa = display_phone(
        current_app.config.get("BUSINESS_WHATSAPP")
        or current_app.config.get("BUSINESS_PHONE")
    )
    minutes = current_app.config.get("CUSTOMER_ACK_CALLBACK_MINUTES", 60)
    from_call = (lead.source or "").lower() == "phone call"

    if from_call:
        lines = [
            f"Hi {customer.name}, thank you for calling {business}.",
            "",
            f"We have noted your request for {service}.",
        ]
    else:
        lines = [
            f"Hi {customer.name}, thank you for contacting {business}.",
            "",
            f"We have received your enquiry for {service}.",
        ]
    if lead.preferred_date:
        lines.append(
            "Your preferred date is "
            f"{lead.preferred_date.strftime('%d %b %Y')}."
        )
    lines += [
        "",
        f"Our team will call you back on {customer.phone} within "
        f"{minutes} minutes to confirm the details and slot.",
        "",
        f"- {business} ({business_wa})",
    ]
    return "\n".join(lines)


def enquiry_received_email_context(lead) -> dict:
    """Context shared by the enquiry acknowledgement templates."""
    customer = lead.customer
    return {
        "lead": lead,
        "customer": customer,
        "service": (
            lead.service.name
            if lead.service
            else (getattr(lead, "service_category", None) or "General enquiry")
        ),
        "source": lead.source or "Website",
        "callback_minutes": current_app.config.get(
            "CUSTOMER_ACK_CALLBACK_MINUTES", 60
        ),
    }


def notify_customer_enquiry_received(lead):
    """Acknowledge the customer's enquiry (WhatsApp + email)."""
    customer = lead.customer
    if not customer:
        return None
    if not current_app.config.get("NOTIFY_CUSTOMER_ACK", True):
        log.info("Customer acknowledgement disabled - skipping lead %s", lead.id)
        return None

    body = enquiry_received_message(lead)
    result = send_whatsapp_result(getattr(customer, "phone", None), body)
    if result.ok:
        log.info("Enquiry acknowledgement sent to %s", customer.phone)
    else:
        log.warning(
            "Enquiry acknowledgement to %s failed: %s", customer.phone, result.detail
        )
        # Let the admins know the customer was not reached automatically.
        notify_admins(
            NT_WHATSAPP_FAILED,
            f"Enquiry acknowledgement to {customer.name} ({customer.phone}) "
            f"failed for enquiry #{lead.id}: {result.detail[:120]}",
            link=url_for("admin.lead_detail", lead_id=lead.id),
        )

    if customer.email:
        ctx = enquiry_received_email_context(lead)
        html = render_template(
            "emails/enquiry_received.html",
            business_name=current_app.config["BUSINESS_NAME"],
            **ctx,
        )
        send_email(
            f"We received your enquiry - {ctx['service']} "
            f"({current_app.config['BUSINESS_NAME']})",
            [customer.email],
            html,
        )
    return result


def notify_new_enquiry(lead, acknowledge_customer: bool = True) -> dict:
    """Notify everyone who needs to know about a brand-new enquiry.

    - in-app notification for every admin
    - WhatsApp alert for every admin number
    - email for every admin address
    - acknowledgement to the customer (WhatsApp + email)

    Returns a dict describing what was sent.
    """
    customer = lead.customer
    service = (
        lead.service.name
        if lead.service
        else (getattr(lead, "service_category", None) or "General enquiry")
    )
    source = lead.source or "Website"

    inapp = notify_admins(
        NT_NEW_ENQUIRY,
        f"New enquiry ({source}): {service} from {customer.name} ({customer.phone})",
        link=url_for("admin.lead_detail", lead_id=lead.id),
    )

    wa = whatsapp_admins(
        f"New enquiry ({source})\n"
        f"Service: {service}\n"
        f"Customer: {customer.name} ({customer.phone})"
        + (f"\nNote: {lead.message}" if lead.message else "")
    )

    email = email_admins(
        f"New enquiry: {service} - {customer.name}",
        "emails/admin_new_enquiry.html",
        **enquiry_received_email_context(lead),
    )

    ack = None
    if acknowledge_customer:
        ack = notify_customer_enquiry_received(lead)

    return {
        "inapp": inapp,
        "whatsapp": wa,
        "email": email,
        "customer_ack": ack,
    }


# -----------------------------
# New booking
# -----------------------------

def notify_new_booking(booking) -> dict:
    """Notify everyone who needs to know about a brand-new booking.

    The customer is *not* messaged here - the 'your appointment is booked'
    message only goes out once an admin confirms the booking
    (``notify_booking_created``).
    """
    customer = booking.customer
    service = booking.service

    inapp = notify_admins(
        NT_NEW_BOOKING,
        f"New booking #{booking.id} ({booking.status}) for {service.name} "
        f"by {customer.name} ({customer.phone})",
        link=url_for("admin.booking_detail", booking_id=booking.id),
    )

    wa = whatsapp_admins(
        f"New booking request #{booking.id}\n"
        f"Service: {service.name}\n"
        f"Customer: {customer.name} ({customer.phone})\n"
        f"Date: {booking.booking_date} {booking.booking_time or ''}".strip()
    )

    email = email_admins(
        f"New booking #{booking.id}: {service.name} - {customer.name}",
        "emails/admin_new_booking.html",
        booking=booking,
        customer=customer,
        service=service,
    )

    return {"inapp": inapp, "whatsapp": wa, "email": email}


def booking_ref(booking) -> str:
    """Human friendly booking reference, e.g. 'SPMS-42'."""
    prefix = current_app.config.get("BOOKING_REF_PREFIX") or "SPMS"
    return f"{prefix}-{booking.id}"


def appointment_booked_message(booking) -> str:
    """Build the 'your appointment is booked' WhatsApp text for the customer."""
    customer = booking.customer
    service = booking.service
    business = current_app.config["BUSINESS_NAME"]
    business_wa = display_phone(
        current_app.config.get("BUSINESS_WHATSAPP")
        or current_app.config.get("BUSINESS_PHONE")
    )

    if booking.booking_date:
        date_str = booking.booking_date.strftime("%d %b %Y")
    else:
        date_str = "to be confirmed"
    if booking.booking_time:
        date_str = f"{date_str} at {booking.booking_time}"

    lines = [
        f"Hi {customer.name}, your appointment is booked.",
        "",
        f"Service: {service.name}",
        f"Date: {date_str}",
        f"Booking Ref: {booking_ref(booking)}",
    ]

    address = booking.address or customer.address
    if address:
        lines.append(f"Address: {address}")

    lines += [
        "",
        "Our team will visit on the scheduled date. If you need to reschedule, "
        f"reply to this message or call {business_wa}.",
        "",
        f"- {business}",
    ]
    return "\n".join(lines)


def appointment_template_params(booking) -> dict:
    """Variables for the approved 'appointment booked' template.

    The keys map to the {{1}}..{{6}} placeholders of the WhatsApp template.
    """
    customer = booking.customer
    if booking.booking_date:
        date_str = booking.booking_date.strftime("%d %b %Y")
    else:
        date_str = "to be confirmed"
    if booking.booking_time:
        date_str = f"{date_str} at {booking.booking_time}"

    business_wa = display_phone(
        current_app.config.get("BUSINESS_WHATSAPP")
        or current_app.config.get("BUSINESS_PHONE")
    )
    return {
        "1": customer.name,
        "2": booking.service.name,
        "3": date_str,
        "4": booking_ref(booking),
        "5": booking.address or customer.address or "-",
        "6": business_wa,
    }


def _appointment_template():
    """The approved template name to use, if one is configured."""
    name = (current_app.config.get("WHATSAPP_TEMPLATE_APPOINTMENT") or "").strip()
    if not name:
        return None
    if not current_app.config.get("TWILIO_CONTENT_SID"):
        log.warning(
            "WHATSAPP_TEMPLATE_APPOINTMENT is set but TWILIO_CONTENT_SID is "
            "empty - falling back to a free-form message."
        )
        return None
    return name


def notify_customer_appointment_booked(booking, verify=True):
    """Send the customer their 'appointment booked' WhatsApp message.

    Twilio only confirms that a message was *queued* - the real delivery
    outcome arrives a moment later. When ``verify`` is set the delivery
    status is polled so the admin sees the real result (and a reason when it
    failed) instead of a false "sent".

    Returns the :class:`whatsapp.WhatsAppResult` so the caller can tell the
    admin whether the message actually went out.
    """
    from whatsapp import WhatsAppResult

    customer = booking.customer
    if not customer:
        return WhatsAppResult(False, "Booking has no customer attached.")

    if not current_app.config.get("WHATSAPP_CUSTOMER_MESSAGES", True):
        log.info("Customer WhatsApp messages disabled — skipping booking %s", booking.id)
        return WhatsAppResult(False, "Customer WhatsApp messages are disabled.")

    body = appointment_booked_message(booking)
    template = _appointment_template()
    params = appointment_template_params(booking) if template else None

    result = send_whatsapp_result(
        getattr(customer, "phone", None), body, template=template, params=params
    )

    if result.ok and verify and result.sid:
        result = _verify_delivery(result)

    # Free-form messages are rejected outside the 24-hour customer service
    # window - retry with the approved template when one is available.
    if (
        not result.ok
        and result.error_code == 63016
        and current_app.config.get("TWILIO_CONTENT_SID")
    ):
        log.info("Free-form message rejected (63016) - retrying with template.")
        result = send_whatsapp_result(
            getattr(customer, "phone", None),
            body,
            template=template or "appointment_booked",
            params=params or appointment_template_params(booking),
        )
        if result.ok and verify and result.sid:
            result = _verify_delivery(result)

    if result.ok:
        log.info(
            "Appointment booked WhatsApp sent to %s (sid=%s)", customer.phone, result.sid
        )
    else:
        log.warning(
            "Appointment booked WhatsApp to %s failed: %s", customer.phone, result.detail
        )
        _notify_admins_whatsapp_failed(booking, customer, result.detail)
    return result


def _verify_delivery(result):
    """Turn a 'queued' send into its real delivery outcome."""
    from whatsapp import WhatsAppResult

    info = wait_for_delivery(result.sid)
    if not info:
        return result
    status = (info.get("status") or "").lower()
    if status == "failed":
        code = info.get("error_code") or 0
        message = info.get("error_message") or "delivery failed"
        detail = f"Twilio error {code}: {message}" if code else message
        hint = error_hint(code)
        if hint:
            detail = f"{detail} {hint}"
        return WhatsAppResult(False, detail, result.sid, code)
    if status in ("sent", "delivered", "read"):
        return WhatsAppResult(True, f"Delivered ({status}).", result.sid)
    return result


def _notify_admins_whatsapp_failed(booking, customer, detail):
    """Tell the admins in-app that the customer did not get the WhatsApp."""
    notify_admins(
        NT_WHATSAPP_FAILED,
        f"WhatsApp to {customer.name} ({customer.phone}) failed for booking "
        f"#{booking.id}: {detail[:120]}",
        link=url_for("admin.booking_detail", booking_id=booking.id),
    )


def notify_booking_created(booking):
    """Customer + admin notifications when a booking is confirmed."""
    business = current_app.config["BUSINESS_NAME"]
    customer = booking.customer
    service = booking.service

    # In-app notification to all admins (created by whoever)
    notify_admins(
        NT_BOOKING_CREATED,
        f"New booking #{booking.id} for {service.name} by {customer.name}",
        link=url_for("admin.booking_detail", booking_id=booking.id),
    )

    # WhatsApp alert to admins
    whatsapp_admins(
        f"New booking #{booking.id}\n"
        f"Service: {service.name}\n"
        f"Customer: {customer.name} ({customer.phone})\n"
        f"Date: {booking.booking_date} {booking.booking_time or ''}".strip()
    )

    # WhatsApp to the customer: their appointment is booked
    whatsapp_result = notify_customer_appointment_booked(booking)

    # Email customer
    email_ok = False
    if customer.email:
        html = render_template(
            "emails/booking_confirmed.html",
            booking=booking,
            customer=customer,
            service=service,
            business_name=business,
        )
        email_ok = send_email(
            f"Booking confirmed — {service.name} ({business})",
            [customer.email],
            html,
        )

    return {"whatsapp": whatsapp_result, "email": email_ok}


def notify_admin_new_booking(booking):
    """Admin in-app + WhatsApp + email alert for a new booking.

    Thin wrapper around :func:`notify_new_booking` kept for the existing
    call sites.
    """
    return notify_new_booking(booking)


def notify_admin_new_lead(lead):
    """Admin in-app + WhatsApp + email alert for a new enquiry.

    Thin wrapper around :func:`notify_new_enquiry` kept for the existing
    call sites.
    """
    return notify_new_enquiry(lead)


def notify_technician_assigned(booking):
    technician = booking.technician
    if not technician:
        return
    customer = booking.customer
    service = booking.service
    notify_users(
        [technician.id],
        NT_TECHNICIAN_ASSIGNED,
        f"New job assigned: {service.name} for {customer.name} on {booking.booking_date}",
        link=url_for("technician.job_detail", booking_id=booking.id),
    )
    send_whatsapp(
        getattr(technician, "whatsapp", None),
        f"New job assigned\n"
        f"Service: {service.name}\n"
        f"Customer: {customer.name} ({customer.phone})\n"
        f"Date: {booking.booking_date} {booking.booking_time or ''}\n"
        f"Address: {booking.address or customer.address or '-'}".strip(),
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


def notify_lead_assigned(lead):
    """Notify a technician that a lead/enquiry has been assigned to them."""
    technician = lead.assigned_technician
    if not technician:
        return
    customer = lead.customer
    service = lead.service.name if lead.service else "Service enquiry"
    notify_users(
        [technician.id],
        NT_LEAD_ASSIGNED,
        f"New enquiry assigned: {service} for {customer.name} ({customer.phone})",
        link=url_for("technician.dashboard"),
    )
    send_whatsapp(
        getattr(technician, "whatsapp", None),
        f"New enquiry assigned\n"
        f"Service: {service}\n"
        f"Customer: {customer.name} ({customer.phone})",
    )


def notify_customer_feedback(booking):
    """Send the customer their feedback link over WhatsApp after completion."""
    customer = booking.customer
    if not customer:
        return
    service = booking.service.name if booking.service else "your recent service"
    business = current_app.config["BUSINESS_NAME"]
    feedback_url = url_for("public.feedback", booking_id=booking.id, _external=True)
    send_whatsapp(
        getattr(customer, "phone", None),
        f"Thank you for choosing {business}!\n"
        f"Your {service} service is complete. Please share your feedback here:\n"
        f"{feedback_url}",
    )


def notify_service_completed(booking):
    business = current_app.config["BUSINESS_NAME"]
    customer = booking.customer
    service = booking.service

    feedback_url = url_for("public.feedback", booking_id=booking.id, _external=True)

    # Customer: thank-you + feedback link over WhatsApp
    notify_customer_feedback(booking)

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
    notify_admins(
        NT_SERVICE_COMPLETED,
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
