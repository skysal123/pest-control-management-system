"""Warranty reminder scanner.

Run this from a cron / scheduled task daily:

    python -m warranty    # uses Flask app context via FLASK_APP

Or in-process via:
    from warranty import scan_and_notify
    scan_and_notify(app)
"""
from datetime import datetime, timedelta
import logging

from extensions import db
from models import Booking, WarrantyReminder, User
from notifications import notify_warranty_reminder, inapp_notify
from flask import url_for

log = logging.getLogger(__name__)


def _already_reminded(booking_id: int, days_before: int) -> bool:
    return WarrantyReminder.query.filter_by(
        booking_id=booking_id, days_before=days_before
    ).first() is not None


def scan_and_notify(app):
    """Scan all completed bookings whose warranty is about to expire.

    Sends one email per (booking, days_before) combo — never twice.
    """
    with app.app_context():
        cfg = app.config
        days = cfg["WARRANTY_REMINDER_DAYS_BEFORE"]
        warranty_days = cfg["WARRANTY_DAYS"]
        now = datetime.utcnow()
        sent = 0

        # Candidates: completed bookings where completed_at + warranty_days is within
        # the reminder window (now + days .. now + days + 1 day).
        # We schedule reminders at: 7 days, 1 day before expiry.
        reminder_offsets = [days, 1]

        completed = Booking.query.filter(Booking.completed_at.isnot(None)).all()
        for b in completed:
            if not b.completed_at:
                continue
            warranty_end = b.completed_at + timedelta(days=warranty_days)
            for offset in reminder_offsets:
                target_send_at = warranty_end - timedelta(days=offset)
                # Fire if target_send_at is within the last 24 hours (covers daily cron)
                if 0 <= (now - target_send_at).total_seconds() < 24 * 3600:
                    if _already_reminded(b.id, offset):
                        continue
                    ok = notify_warranty_reminder(b, offset)
                    if ok:
                        rem = WarrantyReminder(
                            booking_id=b.id,
                            days_before=offset,
                            customer_email=b.customer.email if b.customer else None,
                        )
                        db.session.add(rem)
                        # Also in-app notify all admins
                        for admin in User.query.filter_by(role="ADMIN", is_active=True).all():
                            inapp_notify(
                                admin.id,
                                "warranty_reminder",
                                f"Warranty for booking #{b.id} ({b.service.name}) "
                                f"expires in {offset} day(s)",
                                link=url_for("admin.booking_detail", booking_id=b.id),
                            )
                        sent += 1
        if sent:
            db.session.commit()
        log.info("Warranty scan complete: %s reminder(s) sent", sent)
        return sent


def expiring_warranties():
    """Return bookings whose warranty ends within reminder window but not yet reminded."""
    from flask import current_app

    cfg = current_app.config
    now = datetime.utcnow()
    days = cfg["WARRANTY_REMINDER_DAYS_BEFORE"]
    warranty_days = cfg["WARRANTY_DAYS"]
    out = []
    for b in Booking.query.filter(Booking.completed_at.isnot(None)).all():
        end = b.completed_at + timedelta(days=warranty_days)
        days_left = (end - now).days
        if 0 <= days_left <= days:
            out.append((b, days_left))
    return out


def all_warranties():
    """Return all completed bookings + warranty state, for admin overview."""
    from flask import current_app

    cfg = current_app.config
    warranty_days = cfg["WARRANTY_DAYS"]
    now = datetime.utcnow()
    out = []
    for b in Booking.query.filter(Booking.completed_at.isnot(None)).order_by(
        Booking.completed_at.desc()
    ).all():
        end = b.completed_at + timedelta(days=warranty_days)
        days_left = (end - now).days
        out.append(
            {
                "booking": b,
                "warranty_end": end,
                "days_left": days_left,
                "expired": days_left < 0,
                "reminded": len(b.reminders) > 0,
            }
        )
    return out


if __name__ == "__main__":
    # CLI entry: FLASK_APP=app.py python -m warranty
    from app import create_app

    application = create_app()
    scan_and_notify(application)
    print("Warranty scan done.")
