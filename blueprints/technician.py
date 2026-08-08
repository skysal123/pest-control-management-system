"""Technician portal blueprint."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from extensions import db
from models import Booking
from notifications import notify_service_completed

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
    return render_template(
        "technician/dashboard.html",
        active=active, completed=completed, pending=pending,
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
