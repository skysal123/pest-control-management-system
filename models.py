"""Database models for OneStep MultiServices pest control management."""
from datetime import datetime, timedelta, time as dtime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Share the SQLAlchemy instance defined in extensions.py so init_app is applied.
from extensions import db


def _parse_hhmm(value, fallback=None):
    """Best-effort parse of an "HH:MM" string into a datetime.time."""
    if isinstance(value, dtime):
        return value
    if not value:
        return fallback
    raw = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return fallback


# -----------------------------
# User (Admin / Technician)
# -----------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(32))
    whatsapp = db.Column(db.String(32))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="TECHNICIAN")  # ADMIN / TECHNICIAN
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- Scheduling ---
    # Per-technician working window. Defaults come from config
    # (BUSINESS_WORK_START / BUSINESS_WORK_END / BUSINESS_WORK_DAYS).
    work_start = db.Column(db.String(5), default="09:00")
    work_end = db.Column(db.String(5), default="20:00")
    # Comma separated weekday numbers, Monday=0 .. Sunday=6.
    work_days = db.Column(db.String(30), default="0,1,2,3,4,5,6")

    notifications = db.relationship("Notification", backref="user", lazy=True)
    bookings = db.relationship("Booking", backref="technician", lazy=True)
    skills = db.relationship(
        "TechnicianService",
        backref="technician",
        cascade="all, delete-orphan",
        lazy=True,
    )
    leave = db.relationship(
        "TechnicianLeave",
        backref="technician",
        cascade="all, delete-orphan",
        lazy=True,
    )

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

    # --- Scheduling helpers -------------------------------------------
    @property
    def work_start_time(self):
        return _parse_hhmm(self.work_start, dtime(9, 0))

    @property
    def work_end_time(self):
        return _parse_hhmm(self.work_end, dtime(20, 0))

    @property
    def work_day_numbers(self):
        """Set of weekday numbers (Mon=0) this technician works."""
        if not self.work_days:
            return {0, 1, 2, 3, 4, 5, 6}
        out = set()
        for part in str(self.work_days).split(","):
            part = part.strip()
            if part.isdigit() and 0 <= int(part) <= 6:
                out.add(int(part))
        return out or {0, 1, 2, 3, 4, 5, 6}

    def works_on(self, day):
        """True when the given date falls on one of this technician's days."""
        return day.weekday() in self.work_day_numbers

    @property
    def service_ids(self):
        """Ids of the services this technician is qualified for."""
        return {row.service_id for row in self.skills}

    def can_do(self, service_id):
        """True when qualified for the service (or when no skills are set)."""
        if service_id is None:
            return True
        if not self.skills:
            return True  # no skills configured -> no restriction
        return int(service_id) in self.service_ids

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# -----------------------------
# Technician <-> Service (skills)
# -----------------------------
class TechnicianService(db.Model):
    __tablename__ = "technician_services"

    technician_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), primary_key=True)

    service = db.relationship("Service", backref="technicians", lazy=True)

    def __repr__(self):
        return f"<TechnicianService {self.technician_id}-{self.service_id}>"


# -----------------------------
# Technician time off / leave
# -----------------------------
class TechnicianLeave(db.Model):
    __tablename__ = "technician_leave"

    id = db.Column(db.Integer, primary_key=True)
    technician_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def covers(self, day):
        return self.start_date <= day <= self.end_date

    def __repr__(self):
        return f"<TechnicianLeave tech={self.technician_id} {self.start_date}..{self.end_date}>"



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
    # How long one job of this service blocks a technician (minutes).
    estimated_minutes = db.Column(db.Integer, default=90)
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
    service_category = db.Column(db.String(60))  # e.g. Pest Control / Cleaning Services
    source = db.Column(db.String(30), default="Website")  # Website/WhatsApp/Phone Call/Referral
    message = db.Column(db.Text)
    preferred_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="New")  # New/Contacted/Follow-up Required/Booking Created/Closed/Cancelled
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking = db.relationship("Booking", backref="lead", uselist=False, lazy=True)
    assigned_technician = db.relationship("User", foreign_keys=[assigned_to], lazy=True)

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
    def duration_minutes(self):
        """Length of the visit in minutes, taken from the service."""
        if self.service and self.service.estimated_minutes:
            return int(self.service.estimated_minutes)
        from flask import current_app
        return int(current_app.config.get("DEFAULT_JOB_MINUTES", 90))

    @property
    def start_time(self):
        """Parsed start time of the visit, or None when unset/unparseable."""
        return _parse_hhmm(self.booking_time)

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
