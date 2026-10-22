"""WhatsApp notifications (Twilio) — best-effort, mirrors notifications.send_email.

Uses only the Python standard library so no extra dependency is required.
Configure via environment variables (see config.Config). When not configured
(or WHATSAPP_ENABLED=false) messages are logged instead of sent, so the app
works fine in local development.
"""
import base64
import json
import logging
import time
from typing import NamedTuple
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from flask import current_app

log = logging.getLogger(__name__)


class WhatsAppResult(NamedTuple):
    """Outcome of a send attempt. Truthy when the message was accepted."""

    ok: bool
    detail: str = ""
    sid: str = ""
    error_code: int = 0

    def __bool__(self):
        return self.ok


# Twilio error codes we can turn into something actionable for the admin.
_TWILIO_ERROR_HINTS = {
    21606: (
        "Trial account: this number is not a verified recipient. Add it in the "
        "Twilio console under Phone Numbers > Senders > WhatsApp trial recipients "
        "(max 5 on a trial account)."
    ),
    63015: (
        "The customer has not joined the WhatsApp sandbox, so the sandbox "
        "cannot deliver to them."
    ),
    63016: (
        "This message was sent outside the 24-hour customer service window, so "
        "WhatsApp only allows a pre-approved template."
    ),
    21211: "'To' number is not a valid phone number - check the mobile number.",
    13200: "That number is not a valid WhatsApp mobile number.",
    21610: "The customer has not opted in to receive messages from this number.",
    63038: (
        "The Twilio account has hit its daily message limit (50 messages per "
        "day on a trial account). The message will go out tomorrow - or "
        "upgrade the account to a paid plan to remove the limit."
    ),
    63040: (
        "The Twilio account has hit its monthly message limit. Upgrade the "
        "account to a paid plan to remove the limit."
    ),
}


def sandbox_join_instruction():
    """Instructions the admin can give the customer to join the sandbox."""
    try:
        sender = current_app.config.get("TWILIO_WHATSAPP_FROM") or ""
    except RuntimeError:
        sender = ""
    sender = sender.replace("whatsapp:", "").strip()
    keyword = ""
    try:
        keyword = (current_app.config.get("TWATSAPP_SANDBOX_JOIN_KEYWORD") or "").strip()
    except RuntimeError:
        pass

    parts = []
    if keyword:
        parts.append(f'Ask the customer to send "join {keyword}"')
    else:
        parts.append(
            "Ask the customer to send \"join <your sandbox keyword>\" (found on "
            "the Twilio Console > WhatsApp Sandbox page)"
        )
    if sender:
        parts.append(f"to {sender} on WhatsApp")
    parts.append(
        "- a sandbox session expires after 3 days, so they must rejoin to be "
        "messaged again"
    )
    return " ".join(parts)


def digits_only(phone):
    """Strip everything but digits from a phone number."""
    if phone is None:
        return ""
    return "".join(ch for ch in str(phone) if ch.isdigit())


def _country_code(default_cc=None):
    if default_cc:
        return str(default_cc).lstrip("+")
    try:
        return str(current_app.config.get("DEFAULT_COUNTRY_CODE", "91")).lstrip("+")
    except RuntimeError:
        return "91"


def normalize_phone(phone, default_cc=None):
    """Normalise a phone number to E.164 digits (no '+'), e.g. 917385765171."""
    digits = digits_only(phone)
    if not digits:
        return ""
    cc = _country_code(default_cc)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        digits = cc + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = cc + digits[1:]
    return digits


def is_valid_phone(phone, default_cc=None):
    """True when the number looks like a dialable mobile number.

    Indian mobiles must be 10 digits starting 6-9; anything else is accepted
    as long as it is a plausible E.164 length.
    """
    digits = digits_only(phone)
    if not digits:
        return False
    if digits.startswith("00"):
        digits = digits[2:]
    cc = _country_code(default_cc)
    if len(digits) == 10:
        return digits[0] in "6789"
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1] in "6789"
    if len(digits) == 12 and digits.startswith(cc) and len(cc) == 2:
        return digits[2] in "6789"
    return 10 <= len(digits) <= 15


def display_phone(phone, default_cc=None):
    """Human friendly rendering, e.g. 919975171729 -> '+91 99751 71729'."""
    digits = normalize_phone(phone, default_cc)
    if not digits:
        return ""
    cc = _country_code(default_cc)
    if len(cc) == 2 and digits.startswith(cc) and len(digits) == 12:
        return f"+{cc} {digits[2:7]} {digits[7:]}"
    if len(digits) == 10:
        return f"+{cc} {digits[:5]} {digits[5:]}"
    return f"+{digits}"


def wa_link(phone, text=""):
    """Build a click-to-chat https://wa.me link (fallback when API is off)."""
    num = normalize_phone(phone)
    if not num:
        return ""
    url = f"https://wa.me/{num}"
    if text:
        url += "?text=" + urlparse.quote(text)
    return url


def is_configured():
    provider = (current_app.config.get("WHATSAPP_PROVIDER") or "none").lower()
    if provider == "twilio":
        return all(
            current_app.config.get(k)
            for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM")
        )
    return False


def send_whatsapp(to, body, template=None, params=None):
    """Send a WhatsApp message. Returns True on success, False otherwise.

    Never raises — failures are logged so a notification problem can never
    break a booking or a page render.
    """
    return send_whatsapp_result(to, body, template, params).ok


def send_whatsapp_result(to, body, template=None, params=None):
    """Send a WhatsApp message and report why it failed.

    Returns a :class:`WhatsAppResult` so the caller can surface the reason
    (invalid number, unverified trial recipient, ...) to the admin.
    """
    if not current_app.config.get("WHATSAPP_ENABLED", True):
        log.info("WhatsApp disabled — skipping message to %s", to)
        return WhatsAppResult(False, "WhatsApp is disabled (WHATSAPP_ENABLED=false).")

    to_num = normalize_phone(to)
    if not to_num:
        log.warning("WhatsApp: invalid recipient number %r", to)
        return WhatsAppResult(False, "Invalid recipient phone number.")
    if not is_valid_phone(to_num):
        log.warning("WhatsApp: recipient number %r does not look like a mobile", to)
        return WhatsAppResult(
            False, f"{to} is not a valid mobile number - message not sent."
        )

    provider = (current_app.config.get("WHATSAPP_PROVIDER") or "none").lower()
    if provider == "twilio":
        if not is_configured():
            log.info(
                "WhatsApp (twilio) not configured — dry run. to=%s body=%s",
                to_num, body,
            )
            return WhatsAppResult(False, "Twilio is not configured — message not sent.")
        return _send_twilio(to_num, body, template, params)

    log.info(
        "WhatsApp provider '%s' unknown — dry run. to=%s body=%s",
        provider, to_num, body,
    )
    return WhatsAppResult(False, f"Unknown WhatsApp provider '{provider}'.")


def error_hint(code):
    """Return an actionable hint for a Twilio error code ('' when unknown)."""
    if code == 63015:
        return sandbox_join_instruction()
    return _TWILIO_ERROR_HINTS.get(code, "")


def _twilio_error_detail(exc):
    """Turn a Twilio HTTPError into a short, human readable reason.

    Returns (detail, error_code).
    """
    code = None
    message = ""
    try:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
            code = payload.get("code")
            message = payload.get("message") or ""
        except ValueError:
            message = raw[:200]
    except Exception:  # noqa: BLE001
        pass

    parts = []
    if code:
        parts.append(f"Twilio error {code}")
    if message:
        parts.append(message)
    hint = error_hint(code)
    if hint:
        parts.append(hint)
    if not parts:
        parts.append(f"Twilio HTTP {exc.code}")
    return " ".join(parts), (code or 0)


def _send_twilio(to_num, body, template=None, params=None):
    sid = current_app.config["TWILIO_ACCOUNT_SID"]
    token = current_app.config["TWILIO_AUTH_TOKEN"]
    sender = current_app.config["TWILIO_WHATSAPP_FROM"]
    if not sender.startswith("whatsapp:"):
        sender = "whatsapp:" + sender

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": sender, "To": f"whatsapp:+{to_num}"}
    content_sid = current_app.config.get("TWILIO_CONTENT_SID")
    if template and content_sid:
        data["ContentSid"] = content_sid
        if params:
            data["ContentVariables"] = json.dumps(params)
    else:
        data["Body"] = body

    payload = urlparse.urlencode(data).encode("utf-8")
    token_b64 = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    req = urlrequest.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Basic {token_b64}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                msg_sid = ""
                try:
                    msg_sid = json.loads(resp.read().decode("utf-8", "replace")).get("sid", "")
                except Exception:  # noqa: BLE001
                    pass
                return WhatsAppResult(True, "Accepted by Twilio.", msg_sid)
            log.warning("Twilio WhatsApp returned HTTP %s", resp.status)
            return WhatsAppResult(False, f"Twilio returned HTTP {resp.status}.")
    except urlerror.HTTPError as exc:
        detail, code = _twilio_error_detail(exc)
        log.error("Twilio WhatsApp HTTP %s: %s", exc.code, detail)
        return WhatsAppResult(False, detail, "", code)
    except Exception as exc:  # noqa: BLE001
        log.exception("Twilio WhatsApp send failed: %s", exc)
        return WhatsAppResult(False, f"WhatsApp send failed: {exc}")


def message_status(sid):
    """Fetch the delivery status of a Twilio message.

    Returns a dict with 'status', 'error_code' and 'error_message', or None
    when the status cannot be read.
    """
    if not sid:
        return None
    account_sid = current_app.config.get("TWILIO_ACCOUNT_SID")
    token = current_app.config.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not token:
        return None

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json"
    token_b64 = base64.b64encode(f"{account_sid}:{token}".encode("utf-8")).decode("ascii")
    req = urlrequest.Request(url, method="GET")
    req.add_header("Authorization", f"Basic {token_b64}")
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read Twilio message status %s: %s", sid, exc)
        return None
    return {
        "status": payload.get("status"),
        "error_code": payload.get("error_code"),
        "error_message": payload.get("error_message") or "",
    }


def wait_for_delivery(sid, timeout=3.0, interval=0.6):
    """Poll Twilio until the message leaves the queue.

    Twilio accepts a message with HTTP 201 and then reports the real outcome
    asynchronously, so a send that looks successful can still fail (for
    example when the recipient never started the conversation). Returns the
    final status dict, or None when it could not be read.
    """
    if not sid:
        return None
    deadline = time.time() + timeout
    info = None
    while True:
        info = message_status(sid)
        if not info:
            return None
        if info.get("status") not in ("queued", "sending", "accepted"):
            return info
        if time.time() >= deadline:
            return info
        time.sleep(interval)


def admin_numbers():
    """Configured + per-admin WhatsApp recipients (deduped, digits only)."""
    from models import User

    numbers = set()
    configured = current_app.config.get("ADMIN_WHATSAPP") or ""
    for part in str(configured).replace(";", ",").split(","):
        num = normalize_phone(part.strip())
        if num:
            numbers.add(num)
    try:
        for admin in User.query.filter_by(role="ADMIN", is_active=True).all():
            num = normalize_phone(getattr(admin, "whatsapp", None))
            if num:
                numbers.add(num)
    except Exception:  # noqa: BLE001
        pass
    return sorted(numbers)
