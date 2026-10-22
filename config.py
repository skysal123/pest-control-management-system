import os
from pathlib import Path
from dotenv import load_dotenv

basedir = Path(__file__).resolve().parent
load_dotenv(basedir / ".env")


def _database_uri() -> str:
    """Resolve DATABASE_URL, rebasing relative SQLite paths onto the project.

    SQLAlchemy resolves ``sqlite:///instance/onestep.db`` against the *process
    working directory*, so the app fails with "unable to open database file"
    whenever it is started from anywhere other than the project root
    (``flask run``, ``python run.py``, IDE launchers, cron jobs, gunicorn...).
    Relative paths are therefore anchored to this file's folder instead.
    """
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        return "sqlite:///" + (basedir / "instance" / "onestep.db").as_posix()
    if not raw.startswith("sqlite:///"):
        return raw  # postgres / mysql / any other dialect
    path = raw[len("sqlite:///"):]
    if not path or path == ":memory:":
        return raw
    if path.startswith("/"):
        # POSIX absolute path (keep). Windows drive path written with an extra
        # slash ("/C:/db.sqlite") is normalised to "C:/db.sqlite".
        return raw if not (len(path) > 2 and path[2] == ":") else "sqlite:///" + path[1:]
    if len(path) > 1 and path[1] == ":":  # already absolute (C:/...)
        return raw
    return "sqlite:///" + (basedir / path).as_posix()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Mail settings
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER",
        os.environ.get("MAIL_USERNAME", "noreply@spms.in"),
    )

    # Business settings
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Seva Pest Management Services (SPMS)")
    BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "8600503040")
    BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "info@spms.in")
    BUSINESS_WHATSAPP = os.environ.get("BUSINESS_WHATSAPP", "919975171729")
    BUSINESS_ADDRESS = os.environ.get(
        "BUSINESS_ADDRESS",
        "Shop no. 25, Gurukrupa CHS, Near Datta Mandir, Ruston Colony, Chinchwad, Pune - 411033",
    )
    BUSINESS_CITY = os.environ.get("BUSINESS_CITY", "Pune")

    # Warranty in days
    WARRANTY_DAYS = int(os.environ.get("WARRANTY_DAYS", 90))
    WARRANTY_REMINDER_DAYS_BEFORE = int(
        os.environ.get("WARRANTY_REMINDER_DAYS_BEFORE", 7)
    )

    # ---------------------------------------------------------------
    # Scheduling
    # ---------------------------------------------------------------
    # Business working window, used as the default for every technician.
    # Days are weekday numbers, Monday=0 .. Sunday=6.
    BUSINESS_WORK_START = os.environ.get("BUSINESS_WORK_START", "09:00")
    BUSINESS_WORK_END = os.environ.get("BUSINESS_WORK_END", "20:00")
    BUSINESS_WORK_DAYS = os.environ.get("BUSINESS_WORK_DAYS", "0,1,2,3,4,5,6")
    # Fallback job length when a service has no duration set (minutes).
    DEFAULT_JOB_MINUTES = int(os.environ.get("DEFAULT_JOB_MINUTES", 90))
    # Gap required between two jobs at different addresses (minutes).
    TRAVEL_BUFFER_MINUTES = int(os.environ.get("TRAVEL_BUFFER_MINUTES", 30))

    # WhatsApp notifications (Twilio)
    WHATSAPP_ENABLED = os.environ.get("WHATSAPP_ENABLED", "true").lower() == "true"
    WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "twilio")  # twilio | none
    # Send the "your appointment is booked" message to the customer on
    # WhatsApp when an admin confirms a booking.
    WHATSAPP_CUSTOMER_MESSAGES = os.environ.get(
        "WHATSAPP_CUSTOMER_MESSAGES", "true"
    ).lower() == "true"
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM = os.environ.get(
        "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
    )
    # Optional: Twilio Content template SID for approved templates
    TWILIO_CONTENT_SID = os.environ.get("TWILIO_CONTENT_SID", "")
    # Name of the approved WhatsApp template used for the customer
    # "appointment booked" message (required for business-initiated messages,
    # i.e. anything outside the 24-hour customer service window).
    WHATSAPP_TEMPLATE_APPOINTMENT = os.environ.get(
        "WHATSAPP_TEMPLATE_APPOINTMENT", ""
    )
    # Sandbox join keyword, shown on the Twilio Console > WhatsApp Sandbox
    # page. Used to tell the customer how to opt in to the sandbox.
    TWATSAPP_SANDBOX_JOIN_KEYWORD = os.environ.get(
        "TWATSAPP_SANDBOX_JOIN_KEYWORD", ""
    )
    # Number(s) that receive admin alerts (comma-separated), e.g. 917385765171
    ADMIN_WHATSAPP = os.environ.get("ADMIN_WHATSAPP", "919975171729")
    # Country code used to normalise 10-digit local numbers to E.164
    DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "91")
    # Prefix used in the booking reference shown to customers, e.g. SPMS-42
    BOOKING_REF_PREFIX = os.environ.get("BOOKING_REF_PREFIX", "SPMS")

    # -----------------------------
    # Notification layer
    # -----------------------------
    # Email the admins whenever a new enquiry or booking comes in.
    NOTIFY_ADMIN_EMAIL = os.environ.get(
        "NOTIFY_ADMIN_EMAIL", "true"
    ).lower() == "true"
    # Where the admin notification emails go (comma-separated).
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    # Send the customer an acknowledgement when they raise an enquiry.
    NOTIFY_CUSTOMER_ACK = os.environ.get(
        "NOTIFY_CUSTOMER_ACK", "true"
    ).lower() == "true"
    # Ask the admin to call back within this many minutes (shown in the
    # customer acknowledgement message).
    CUSTOMER_ACK_CALLBACK_MINUTES = int(
        os.environ.get("CUSTOMER_ACK_CALLBACK_MINUTES", 60)
    )
