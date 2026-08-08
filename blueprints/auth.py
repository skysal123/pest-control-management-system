"""Authentication blueprint (admin + technician login)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User
from functools import wraps

bp = Blueprint("auth", __name__, url_prefix="/auth")


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _role_redirect(current_user)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(db.func.lower(User.email) == email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", email=email)
        if not user.is_active:
            flash("This account has been deactivated. Contact admin.", "warning")
            return render_template("auth/login.html", email=email)

        login_user(user, remember=remember)
        flash(f"Welcome back, {user.name}.", "success")
        return _role_redirect(user)

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.home"))


def _role_redirect(user):
    if user.is_admin:
        return redirect(url_for("admin.dashboard"))
    if user.is_technician:
        return redirect(url_for("technician.dashboard"))
    return redirect(url_for("public.home"))
