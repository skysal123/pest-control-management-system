"""Technician portal blueprint."""
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from extensions import db
from models import Booking, Lead, Notification
from notifications import notify_service_completed
import scheduling

bp = Blueprint("technician", __name__, url_prefix="/technician")


def _tech_required(view):
    @login_required
    def wrapped(*a, **kw):
        if not current_user.is_technician:
            abort(403)
        return view(*a, **kw)
    wrapped.__name__ = view.__name__
    return wrapped


@bp.route("/")
@_tech_required
def dashboard():
    tech_id = current_user.id
    active = Booking.query.filter(
        Booking.technician_id == tech_id,
        Booking.status.in_(["Assigned", "In Progress"]),
    ).order_by(Booking.booking_date.asc()).all()
    completed = Booking.query.filter_by(technician_id=tech_id, status="Completed") \
        .order_by(Booking.completed_at.desc()).limit(10).all()
    pending = Booking.query.filter_by(technician_id=tech_id, status="Pending") \
        .order_by(Booking.booking_date.asc()).all()

    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    from datetime import date
    today = date.today()
    due_today = [b for b in (active + pending) if b.booking_date == today]

    # Enquiries assigned directly to this technician (not yet closed or
    # converted into a booking — converted ones show up as normal jobs)
    assigned_leads = [
        l
        for l in Lead.query.filter(
            Lead.assigned_to == tech_id,
            ~Lead.status.in_(["Closed", "Cancelled"]),
        )
        .order_by(Lead.created_at.desc())
        .all()
        if not l.booking
    ]

    notifications = (
        Notification.query.filter_by(user_id=tech_id)
        .order_by(Notification.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "technician/dashboard.html",
        active=active, completed=completed, pending=pending,
        assigned_leads=assigned_leads, notifications=notifications,
        greeting=greeting, today=today, due_today=due_today,
    )


@bp.route("/schedule")
@_tech_required
def schedule():
    """My own week: days, jobs and free slots."""
    anchor = date.today()
    raw = request.args.get("week", "").strip()
    if raw:
        try:
            anchor = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass

    days = scheduling.week_days(anchor)
    grouped = scheduling.bookings_by_technician(days[0], [current_user.id])
    for day in days[1:]:
        for tid, rows in scheduling.bookings_by_technician(day, [current_user.id]).items():
            grouped.setdefault(tid, []).extend(rows)

    week = []
    total_jobs = 0
    total_minutes = 0
    for day in days:
        avail = scheduling.compute_availability(
            current_user, day, bookings=grouped.get(current_user.id)
        )
        total_jobs += len(avail.blocks)
        total_minutes += avail.booked_minutes
        week.append({"day": day, "availability": avail})

    return render_template(
        "technician/schedule.html",
        week=week,
        anchor=anchor,
        today=date.today(),
        prev_week=days[0] - timedelta(days=7),
        next_week=days[0] + timedelta(days=7),
        total_jobs=total_jobs,
        total_minutes=total_minutes,
    )


@bp.route("/jobs/<int:booking_id>")
@_tech_required
def job_detail(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.technician_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template("technician/job_detail.html", booking=b)


@bp.route("/jobs/<int:booking_id>/action", methods=["POST"])
@_tech_required
def job_action(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.technician_id != current_user.id and not current_user.is_admin:
        abort(403)
    action = request.form.get("action")
    notes = request.form.get("notes", "")

    if action == "accept":
        b.status = "In Progress"
    elif action == "start":
        b.status = "In Progress"
    elif action == "complete":
        b.status = "Completed"
        b.completed_at = datetime.utcnow()
        if notes:
            b.notes = (b.notes or "") + f"\n[{datetime.utcnow():%Y-%m-%d %H:%M}] {notes}"
        db.session.commit()
        notify_service_completed(b)
        flash("Service marked complete.", "success")
        return redirect(url_for("technician.dashboard"))
    elif action == "notes":
        if notes:
            b.notes = (b.notes or "") + f"\n[{datetime.utcnow():%Y-%m-%d %H:%M}] {notes}"

    db.session.commit()
    flash("Job updated.", "success")
    return redirect(url_for("technician.job_detail", booking_id=b.id))
