# OneStep MultiServices — Pest Control Management System

A complete web-based Pest Control Service Management System built with **Flask + SQLAlchemy + Flask-Login**.

The system handles the entire customer journey:

```
Customer discovery  →  Enquiry (Lead)  →  Booking  →  Technician dispatch  →
Service completion  →  Customer feedback  →  Warranty tracking  →  Renewal
```

---

## Features

### Customer website (public)
- Home with services overview, "Why choose us", testimonials, CTA
- About Us page (story, mission, vision, certifications)
- Services list + per-service detail (description, benefits, process, FAQ)
- Contact page with Google Map and enquiry form
- Floating Call + WhatsApp buttons
- One-click feedback link sent after service completion

### Admin portal
- Dashboard with stats (leads, bookings, completed, feedback, avg rating, expiring warranties)
- Lead management: list, search, filter by source/status, update status, assign technician, convert to booking
- Booking management: list, filter by status, create, confirm, assign technician, edit date/time/address, complete, cancel
- Technician management: add, edit, activate/deactivate, view jobs
- Service catalogue management
- Feedback dashboard (with star ratings)
- **Warranty management**: view all warranties, see days left, expired vs active
- Notifications inbox

### Technician portal
- Dashboard (pending / active / completed jobs)
- Job detail with customer info, address, service details
- Accept / start / complete actions with optional service notes

### Notifications (Phase 1 — email)
- Booking confirmed → email to customer + in-app to admins
- Technician assigned → email + in-app to technician
- Service completed → thank-you email with feedback link
- Warranty reminder → email to customer + in-app to admins
  (driven by `warranty.scan_and_notify(app)` — designed to run daily via cron)

### Warranty Management (Section 13)
- Every completed booking gets a configurable warranty (default 90 days)
- `Booking.warranty_end` / `is_under_warranty` helpers
- Admin warranty dashboard showing days left, expired/active state, reminders sent
- Cron job sends reminders 7 days and 1 day before expiry (configurable)
- Each reminder is logged in the `warranty_reminders` table — never sent twice

---

## Project structure

```
OneStepMultiservices/
├── app/                     # Application package
│   ├── __init__.py          # Application factory (create_app)
│   ├── static/css/style.css
│   ├── static/js/main.js
│   └── templates/
│       ├── base.html        # Public base layout
│       ├── partials/        # _navbar, _topbar, _footer
│       ├── auth/login.html
│       ├── public/          # home, about, services, contact, feedback
│       ├── admin/           # admin layout + all admin pages
│       ├── technician/      # technician layout + job pages
│       └── emails/          # booking_confirmed, technician_assigned,
│                            # service_completed, warranty_reminder
├── blueprints/
│   ├── __init__.py
│   ├── auth.py              # Login / logout / role_required
│   ├── public.py            # Customer-facing pages + enquiry + feedback
│   ├── admin.py             # Admin dashboard + leads/bookings/technicians/services/feedback/warranties/notifications
│   └── technician.py        # Technician dashboard + job actions
├── models.py                # SQLAlchemy models for all 7 tables + WarrantyReminder
├── extensions.py            # db / login_manager / mail singletons
├── config.py                # Env-driven config (mail, business, warranty)
├── notifications.py         # Email + in-app notification helpers
├── warranty.py              # Daily reminder scanner + dashboard helpers
├── seed.py                  # Initial admin + technicians + services
├── run.py                   # Entry point: `python run.py`
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup (Development)

### 1. Create a virtual environment and install

```bash
python -m venv onestep
# Windows
onestep\Scripts\activate
# Linux / macOS
source onestep/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and DATABASE_URL.
# For Gmail, set MAIL_USERNAME and MAIL_PASSWORD (use an App Password).
```

### 3. Initialize database + seed

```bash
set FLASK_APP=app        # Windows
export FLASK_APP=app     # macOS / Linux

flask init-db
flask seed               # creates admin, technicians, 6 services
```

You will be prompted for the admin email + password. Defaults:
- Admin  → `admin@onestep.local` / `Admin@123`
- Techs  → `ravi@onestep.local` / `Tech@123`, `suresh@onestep.local` / `Tech@123`

### 4. Run

```bash
python run.py
# or
flask run --debug
```

Open:
- Customer site → http://localhost:5000
- Admin         → http://localhost:5000/auth/login
- Technician    → same login URL, redirects by role

---

## Production (PostgreSQL + Render / Hostinger)

### Database
Set `DATABASE_URL=postgresql://user:pass@host:5432/dbname` in `.env`. The same code works for both SQLite (dev) and PostgreSQL (prod).

### Entry point
```bash
gunicorn 'app:create_app()' --bind 0.0.0.0:$PORT --workers 3
```

For **Render**: set the build command to `pip install -r requirements.txt` and the start command to the gunicorn line above. Add the env vars in the dashboard.

For **Hostinger VPS**: same gunicorn invocation behind nginx + systemd (see Render's docs — same pattern).

### Daily warranty scanner (cron)
The warranty reminder scanner is designed to run once per day:

```bash
flask shell
>>> from warranty import scan_and_notify
>>> from app import create_app
>>> scan_and_notify(create_app())
```

Or via the standalone module:
```bash
python -m warranty
```

Add a daily cron entry on the host:
```cron
5 9 * * * cd /srv/onestep && FLASK_APP=app python -m warranty >> /var/log/warranty.log 2>&1
```

---

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-secret-change-in-prod` | Flask session signing |
| `DATABASE_URL` | `sqlite:///instance/onestep.db` | SQLAlchemy URI (SQLite or Postgres) |
| `MAIL_SERVER` / `MAIL_PORT` | `smtp.gmail.com` / `587` | SMTP |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | — | SMTP credentials |
| `BUSINESS_NAME` / `BUSINESS_PHONE` / `BUSINESS_EMAIL` / `BUSINESS_WHATSAPP` / `BUSINESS_ADDRESS` | — | Used in templates/emails |
| `WARRANTY_DAYS` | `90` | Length of service warranty |
| `WARRANTY_REMINDER_DAYS_BEFORE` | `7` | First reminder offset before expiry (also sends at 1 day) |

---

## Future enhancements (built-in roadmap)
- WhatsApp Business API integration
- Online payments (Razorpay / Stripe)
- Invoice generation
- Customer login portal
- AMC management
- Technician mobile application
- GPS tracking
- AI chatbot
- Analytics dashboard
