import os
from pathlib import Path
from dotenv import load_dotenv

basedir = Path(__file__).resolve().parent
load_dotenv(basedir / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + str(basedir / "instance" / "onestep.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Mail settings
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER",
        os.environ.get("MAIL_USERNAME", "noreply@onestepmultiservices.com"),
    )

    # Business settings
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "OneStep MultiServices")
    BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "+91-9876543210")
    BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "care@onestepmultiservices.com")
    BUSINESS_WHATSAPP = os.environ.get("BUSINESS_WHATSAPP", "919876543210")
    BUSINESS_ADDRESS = os.environ.get(
        "BUSINESS_ADDRESS", "123 Service Lane, Pune, Maharashtra, India"
    )
    BUSINESS_CITY = os.environ.get("BUSINESS_CITY", "Pune")

    # Warranty in days
    WARRANTY_DAYS = int(os.environ.get("WARRANTY_DAYS", 90))
    WARRANTY_REMINDER_DAYS_BEFORE = int(
        os.environ.get("WARRANTY_REMINDER_DAYS_BEFORE", 7)
    )
