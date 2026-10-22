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

### Notifications
- Booking confirmed → email + WhatsApp to the customer, in-app + WhatsApp to admins
- New enquiry (contact / quote / get-started form) → in-app + WhatsApp to admins
- Technician assigned → email + WhatsApp to the technician
- Service completed → thank-you email + WhatsApp feedback link
- Warranty reminder → email to customer + in-app to admins
  (driven by `warranty.scan_and_notify(app)` — designed to run daily via cron)

### Notification layer — `notifications.py`
Every event fans out over the same four channels: **in-app** (bell + unread
badge in the admin portal), **WhatsApp**, **email**, and — where it makes
sense — a **customer acknowledgement**.

| Event | In-app | WhatsApp | Email | Customer |
|---|---|---|---|---|
| New enquiry (`/contact`, `/get-started`, `/quote`, admin) | admins | admins | admins | acknowledgement |
| New booking request (website) | admins | admins | admins | – |
| New booking created in the admin panel | admins | admins | admins | – |
| Booking confirmed / assigned | admins | admins | – | "appointment booked" |
| Technician assigned | technician | technician | technician | – |
| Enquiry assigned to technician | technician | technician | – | – |
| Service completed | admins | – | – | thank-you + feedback link |
| Warranty expiring | admins | – | customer | – |

Entry points in `notifications.py`:

```python
notify_new_enquiry(lead)             # admins + customer acknowledgement
notify_new_booking(booking)           # admins (customer is messaged on confirm)
notify_booking_created(booking)       # on confirm/assign - also messages the customer
notify_technician_assigned(booking)
notify_lead_assigned(lead)
notify_service_completed(booking)
notify_warranty_reminder(booking, days_left)
```

Helpers: `notify_admins()`, `notify_users()`, `email_admins()`,
`whatsapp_admins()`, `inapp_notify()`.

> In-app notifications are **committed** by the layer, so they survive the
> request. A message that could not be delivered (e.g. WhatsApp rejected) is
> recorded as a `whatsapp_failed` entry so the admin can act on it.

> All sends are **best effort** — a failing channel never breaks the enquiry
> or the booking. Email is skipped with a clear log line while the `.env`
> still holds the placeholder Gmail credentials.

### WhatsApp (Twilio) — `whatsapp.py`
- **Customer message:** when an admin confirms a booking, the customer receives an
  "your appointment is booked" WhatsApp (service, date, booking ref, address and
  the business WhatsApp number). The recipient is the number the customer typed
  into the enquiry form.
- **Admin alerts:** new enquiry / new booking are pushed to every number in
  `ADMIN_WHATSAPP` plus every admin's own "WhatsApp" field.
- **Delivery is verified:** Twilio only reports a message as *queued*, so the
  delivery status is polled right after the send. A failed send shows the
  reason in the admin UI (e.g. "recipient never started the conversation") and
  is also recorded as an in-app notification.
- **Manual resend:** the booking page has a "Send 'Appointment Booked' WhatsApp"
  button for the cases the API cannot deliver.

> **Trial-account limits (read this before going live)**
> The configured Twilio account is a **trial** account using the shared sandbox
> number `+1 415 523 8886`, so:
> - a message only reaches a number that has sent `join <your sandbox keyword>`
>   to the sandbox (the keyword is on the *Twilio Console → WhatsApp Sandbox*
>   page - copy it into `TWATSAPP_SANDBOX_JOIN_KEYWORD` and the admin panel
>   will tell the customer exactly what to send);
> - a sandbox session **expires after 3 days**, so the customer must rejoin;
> - the sender shown to the customer is the Twilio sandbox, **not** your number.
> - a trial account may send only **50 messages per day** (Twilio error 63038
>   when the limit is hit - the admin panel says so explicitly).
>
> Twilio does not sell Indian numbers, so the sandbox can never show
> 9975171729 as the sender.

### Going live with 9975171729 as the sender (Twilio Self Sign-up)

Twilio supports **Bring Your Own Number** for WhatsApp, so your own number can
become a real WhatsApp sender — no aggregator needed:

1. **Upgrade the Twilio account** from Trial to a paid plan.
2. Console → **Messaging → Senders → WhatsApp Senders → Create new sender**.
3. Choose **"Non-Twilio phone number"** and enter `+91 99751 71729`.
   - The number must be able to receive an SMS or voice OTP.
   - It must **not** already be registered on WhatsApp. If the WhatsApp
     Business App is currently running on it, deregister that number first
     (Twilio: *"Can I move my approved WhatsApp Number to Twilio?"*).
4. **Continue with Facebook** → create (or select) a **Meta Business
   Portfolio** and a **WABA**. Complete Meta business verification before you
   need production limits (unverified: max 2 senders, 50 business-initiated
   conversations per sender per 24h).
5. Verify the number with the OTP, then wait for Meta to approve the display
   name.
6. In this project set:
   ```env
   TWILIO_WHATSAPP_FROM=whatsapp:+919975171729
   ```
7. **Create an approved template.** Outside the 24-hour customer service
   window WhatsApp only allows pre-approved templates. In the Console go to
   **Messaging → Content Template Builder**, create a template such as
   `appointment_booked` with body placeholders `{{1}}`..`{{6}}`, and submit it
   for approval. Then set:
   ```env
   TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   WHATSAPP_TEMPLATE_APPOINTMENT=appointment_booked
   ```
   The variables are filled automatically: `{{1}}` customer name,
   `{{2}}` service, `{{3}}` date & time, `{{4}}` booking reference,
   `{{5}}` address, `{{6}}` business WhatsApp number.
8. Free-form messages (no template) keep working **inside** the 24-hour
   window, i.e. when the customer messages you first. If a free-form send is
   rejected with error 63016, the app automatically retries with the approved
   template.

### Manual fallback (works today, no API needed)

If the API cannot deliver (sandbox, or the customer has not joined), the
booking page has an **"Open WhatsApp & send"** button. It opens WhatsApp with
the complete appointment message pre-filled, so you tap *send* from your own
phone and the customer receives it from **9975171729**.

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
├── notifications.py         # Email + in-app + WhatsApp notification helpers
├── whatsapp.py              # WhatsApp sender (Twilio) + phone helpers
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
| `BUSINESS_NAME` / `BUSINESS_PHONE` / `BUSINESS_EMAIL` / `BUSINESS_WHATSAPP` / `BUSINESS_ADDRESS` | — | Used in templates/emails and in the customer WhatsApp message |
| `WARRANTY_DAYS` | `90` | Length of service warranty |
| `WARRANTY_REMINDER_DAYS_BEFORE` | `7` | First reminder offset before expiry (also sends at 1 day) |
| `WHATSAPP_ENABLED` | `true` | Master switch for WhatsApp sends |
| `WHATSAPP_PROVIDER` | `twilio` | `twilio` or `none` (dry run) |
| `WHATSAPP_CUSTOMER_MESSAGES` | `true` | Send the "appointment booked" message to the customer |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | — | Twilio credentials |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` | Sender (sandbox number on a trial account) |
| `TWILIO_CONTENT_SID` | — | Approved template SID (needed for business-initiated messages) |
| `WHATSAPP_TEMPLATE_APPOINTMENT` | — | Name of the approved template for the customer message |
| `TWATSAPP_SANDBOX_JOIN_KEYWORD` | — | Sandbox join keyword, used in the opt-in instructions |
| `ADMIN_WHATSAPP` | — | Comma-separated numbers that receive admin alerts |
| `NOTIFY_ADMIN_EMAIL` | `true` | Email the admins on every new enquiry / booking |
| `ADMIN_EMAIL` | — | Where admin notification emails go (defaults to `BUSINESS_EMAIL`) |
| `NOTIFY_CUSTOMER_ACK` | `true` | Acknowledge the customer when they raise an enquiry |
| `CUSTOMER_ACK_CALLBACK_MINUTES` | `60` | Callback window quoted in the acknowledgement |
| `DEFAULT_COUNTRY_CODE` | `91` | Country code used to normalise 10-digit local numbers |
| `BOOKING_REF_PREFIX` | `SPMS` | Prefix of the booking reference sent to customers |

---

## Future enhancements (built-in roadmap)
- Online payments (Razorpay / Stripe)
- Invoice generation
- Customer login portal
- AMC management
- Technician mobile application
- GPS tracking
- AI chatbot
- Analytics dashboard
