"""Database models for OneStep MultiServices pest control management."""
from datetime import datetime, timedelta
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Share the SQLAlchemy instance defined in extensions.py so init_app is applied.
from extensions import db


# -----------------------------
# User (Admin / Technician)
# -----------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(32))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="TECHNICIAN")  # ADMIN / TECHNICIAN
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    notifications = db.relationship("Notification", backref="user", lazy=True)
    bookings = db.relationship("Booking", backref="technician", lazy=True)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def is_technician(self):
        return self.role == "TECHNICIAN"

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# -----------------------------
# Customer
# -----------------------------
class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(32), nullable=False, index=True)
    email = db.Column(db.String(180), index=True)
    address = db.Column(db.String(255))
    city = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    leads = db.relationship("Lead", backref="customer", lazy=True)
    bookings = db.relationship("Booking", backref="customer", lazy=True)
    feedback = db.relationship("Feedback", backref="customer", lazy=True)

    def __repr__(self):
        return f"<Customer {self.name}>"


# -----------------------------
# Service
# -----------------------------
class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    slug = db.Column(db.String(120), unique=True, index=True)
    short_description = db.Column(db.String(255))
    description = db.Column(db.Text)
    benefits = db.Column(db.Text)
    process = db.Column(db.Text)
    faq = db.Column(db.Text)  # JSON-encoded Q&A list
    image = db.Column(db.String(255))  # static/images/<file>
    icon = db.Column(db.String(80))  # bootstrap-icons class e.g. bi-bug
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / INACTIVE
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    leads = db.relationship("Lead", backref="service", lazy=True)
    bookings = db.relationship("Booking", backref="service", lazy=True)

    @property
    def faq_list(self):
        """Parse FAQ text into a list of {"q": ..., "a": ...} dicts.

        Format: lines starting with "Q:" / "A:" — every Q is paired with the next A.
        """
        if not self.faq:
            return []
        items, q, a = [], None, []
        for raw in self.faq.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("Q:"):
                if q is not None:
                    items.append({"q": q, "a": " ".join(a).strip()})
                q = line[2:].strip()
                a = []
            elif line.startswith("A:"):
                a.append(line[2:].strip())
            else:
                if q is not None:
                    a.append(line)
        if q is not None:
            items.append({"q": q, "a": " ".join(a).strip()})
        return items

    def __repr__(self):
        return f"<Service {self.name}>"


# -----------------------------
# Lead
# -----------------------------
class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"))
    source = db.Column(db.String(30), default="Website")  # Website/WhatsApp/Phone Call/Referral
    message = db.Column(db.Text)
    preferred_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="New")  # New/Contacted/Follow-up Required/Booking Created/Closed/Cancelled
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking = db.relationship("Booking", backref="lead", uselist=False, lazy=True)

    def __repr__(self):
        return f"<Lead #{self.id} {self.status}>"


# -----------------------------
# Booking
# -----------------------------
class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"))
    technician_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    booking_date = db.Column(db.Date, nullable=False)
    booking_time = db.Column(db.String(20))  # HH:MM
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="Pending")  # Pending/Confirmed/Assigned/In Progress/Completed/Cancelled
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    feedback = db.relationship("Feedback", backref="booking", uselist=False, lazy=True)

    @property
    def warranty_end(self):
        if self.completed_at:
            from flask import current_app
            return self.completed_at + timedelta(
                days=current_app.config["WARRANTY_DAYS"]
            )
        return None

    @property
    def is_under_warranty(self):
        end = self.warranty_end
        return bool(end and end >= datetime.utcnow())

    def __repr__(self):
        return f"<Booking #{self.id} {self.status}>"


# -----------------------------
# Feedback
# -----------------------------
class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    technician = db.relationship("User", foreign_keys=[technician_id])

    def __repr__(self):
        return f"<Feedback #{self.id} {self.rating}*>"


# -----------------------------
# Notification
# -----------------------------
class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(50))  # booking_created/technician_assigned/service_completed/warranty_reminder
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255))
    status = db.Column(db.String(20), default="unread")  # unread/read
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Notification #{self.id} {self.type}>"


# -----------------------------
# Warranty Reminder log (so we don't send twice)
# -----------------------------
class WarrantyReminder(db.Model):
    __tablename__ = "warranty_reminders"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    days_before = db.Column(db.Integer)
    customer_email = db.Column(db.String(180))

    booking = db.relationship("Booking", backref="reminders", lazy=True)
