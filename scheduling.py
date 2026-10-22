"""Scheduling engine: working hours, job spans, conflicts and availability.

Pure functions over models - no writes, no side effects. Everything the admin
sees on the schedule board and the assignment picker is derived here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta

from models import Booking, TechnicianLeave, User

# Statuses that still occupy a technician's calendar.
ACTIVE_STATUSES = ("Pending", "Confirmed", "Assigned", "In Progress")
# Statuses that free the calendar up again.
CLOSED_STATUSES = ("Completed", "Cancelled")


# ---------------------------------------------------------------
# Small time helpers
# ---------------------------------------------------------------
def parse_hhmm(value, fallback=None):
    """Parse 'HH:MM' (or 'H:MM AM') into a datetime.time."""
    if isinstance(value, dtime):
        return value
    if value is None:
        return fallback
    raw = str(value).strip()
    if not raw:
        return fallback
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return fallback


def to_minutes(value):
    """Minutes since midnight for a datetime.time."""
    if value is None:
        return None
    return value.hour * 60 + value.minute


def from_minutes(minutes):
    """datetime.time for a minute offset from midnight."""
    minutes = max(0, min(24 * 60 - 1, int(minutes)))
    return dtime(minutes // 60, minutes % 60)


def fmt_time(value):
    """'HH:MM' for a time object."""
    if value is None:
        return ""
    return f"{value.hour:02d}:{value.minute:02d}"


def fmt_duration(minutes):
    """90 -> '1h 30m', 60 -> '1h', 45 -> '45m'."""
    if minutes is None:
        return ""
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h" if mins == 0 else f"{hours}h {mins}m"


# ---------------------------------------------------------------
# Working hours
# ---------------------------------------------------------------
def technician_window(tech, day):
    """(start, end) datetime.time for a technician on a date, or None.

    Falls back to the business default when the technician has no hours set.
    """
    from flask import current_app

    if tech is None:
        return None
    if not tech.works_on(day):
        return None
    start = tech.work_start_time
    end = tech.work_end_time
    if start is None or end is None:
        start = parse_hhmm(current_app.config.get("BUSINESS_WORK_START"), dtime(9, 0))
        end = parse_hhmm(current_app.config.get("BUSINESS_WORK_END"), dtime(20, 0))
    if end <= start:
        return None
    return start, end


def business_window(day):
    """(start, end) for the whole business on a date."""
    from flask import current_app

    start = parse_hhmm(current_app.config.get("BUSINESS_WORK_START"), dtime(9, 0))
    end = parse_hhmm(current_app.config.get("BUSINESS_WORK_END"), dtime(20, 0))
    return start, end


def is_on_leave(tech, day):
    """True when the technician has approved leave covering that date."""
    if tech is None:
        return False
    for leave in tech.leave or ():
        if leave.covers(day):
            return True
    return False


def leave_entries(tech, day):
    """Leave rows covering a date (for the reason text)."""
    if tech is None:
        return []
    return [lv for lv in (tech.leave or ()) if lv.covers(day)]


# ---------------------------------------------------------------
# Job spans
# ---------------------------------------------------------------
@dataclass
class JobBlock:
    """One booking rendered on the timeline."""

    booking: Booking
    start_min: int
    end_min: int
    travel_after: int = 0  # buffer reserved after the job

    @property
    def duration(self):
        return self.end_min - self.start_min

    @property
    def start_label(self):
        return from_minutes(self.start_min).strftime("%I:%M %p").lstrip("0")

    @property
    def end_label(self):
        return from_minutes(self.end_min).strftime("%I:%M %p").lstrip("0")

    @property
    def customer_name(self):
        return self.booking.customer.name if self.booking.customer else "—"

    @property
    def service_name(self):
        return self.booking.service.name if self.booking.service else "—"

    @property
    def status(self):
        return self.booking.status


def job_block(booking):
    """Turn a booking into a JobBlock, or None when it cannot be placed.

    A booking without a parsable time is treated as occupying the whole
    working day so it is still visible on the board.
    """
    window = business_window(booking.booking_date)
    day_start = to_minutes(window[0])
    day_end = to_minutes(window[1])
    duration = booking.duration_minutes
    start = booking.start_time
    if start is None:
        return JobBlock(
            booking=booking,
            start_min=day_start,
            end_min=day_end,
        )
    start_min = to_minutes(start)
    end_min = start_min + duration
    return JobBlock(booking=booking, start_min=start_min, end_min=end_min)


def blocks_for(tech, day, bookings=None):
    """Job blocks for one technician on one date, sorted by start.

    Travel buffers are already applied, so every caller sees the same
    occupied ranges.
    """
    if bookings is None:
        bookings = Booking.query.filter(
            Booking.technician_id == tech.id,
            Booking.booking_date == day,
            Booking.status.notin_(CLOSED_STATUSES),
        ).all()
    blocks = [job_block(b) for b in bookings]
    blocks = [b for b in blocks if b is not None]
    blocks.sort(key=lambda b: (b.start_min, b.end_min))
    return apply_travel_buffers(blocks, _buffer_minutes())


def _needs_travel(a, b):
    """True when two jobs are at different addresses (travel buffer applies)."""
    addr_a = (a.booking.address or "").strip().lower()
    addr_b = (b.booking.address or "").strip().lower()
    if not addr_a or not addr_b:
        return True
    return addr_a != addr_b


def apply_travel_buffers(blocks, buffer_minutes):
    """Reserve a travel gap after jobs that are followed by a job elsewhere."""
    for i, block in enumerate(blocks):
        block.travel_after = 0
        if i + 1 < len(blocks) and _needs_travel(block, blocks[i + 1]):
            block.travel_after = buffer_minutes
    return blocks


def conflicts(blocks, start_min, end_min, ignore_booking_id=None):
    """Blocks that clash with a proposed [start_min, end_min) window.

    The travel buffer of the preceding job is respected.
    """
    hits = []
    for block in blocks:
        if ignore_booking_id and block.booking.id == ignore_booking_id:
            continue
        block_end = block.end_min + block.travel_after
        if start_min < block_end and block.start_min < end_min:
            hits.append(block)
    return hits


def overlapping_bookings(tech, day, start_min, end_min, ignore_booking_id=None):
    """Booking-level conflicts for a technician on a date."""
    blocks = blocks_for(tech, day)
    apply_travel_buffers(blocks, _buffer_minutes())
    return [
        b for b in conflicts(blocks, start_min, end_min, ignore_booking_id)
    ]


def _buffer_minutes():
    from flask import current_app

    return int(current_app.config.get("TRAVEL_BUFFER_MINUTES", 30))


# ---------------------------------------------------------------
# Availability
# ---------------------------------------------------------------
@dataclass
class Availability:
    """Availability of one technician for one date."""

    tech: User
    day: date
    working: bool = True
    on_leave: bool = False
    leave_reason: str = ""
    window_start: dtime | None = None
    window_end: dtime | None = None
    blocks: list = field(default_factory=list)
    booked_minutes: int = 0
    capacity_minutes: int = 0
    free_slots: list = field(default_factory=list)
    next_free: dtime | None = None
    skills_ok: bool = True

    @property
    def load_ratio(self):
        if not self.capacity_minutes:
            return 0.0
        return min(1.0, self.booked_minutes / self.capacity_minutes)

    @property
    def load_percent(self):
        return int(round(self.load_ratio * 100))

    @property
    def is_off(self):
        return not self.working or self.on_leave

    @property
    def state(self):
        """'off' | 'free' | 'busy' | 'full'."""
        if self.is_off:
            return "off"
        if not self.blocks:
            return "free"
        if self.load_ratio >= 0.99:
            return "full"
        return "busy"

    @property
    def state_label(self):
        return {
            "off": "Off",
            "free": "Free",
            "busy": "Part busy",
            "full": "Fully booked",
        }[self.state]

    @property
    def free_label(self):
        if self.is_off:
            return "Not working"
        if self.next_free is None:
            return "No free slot"
        return f"Free from {self.next_free.strftime('%I:%M %p').lstrip('0')}"

    @property
    def next_free_label(self):
        if self.next_free is None:
            return "—"
        return self.next_free.strftime("%I:%M %p").lstrip("0")


def compute_availability(tech, day, bookings=None, service_id=None):
    """Full availability picture for a technician on a date."""
    avail = Availability(tech=tech, day=day)
    avail.on_leave = is_on_leave(tech, day)
    if avail.on_leave:
        entries = leave_entries(tech, day)
        avail.leave_reason = entries[0].reason if entries and entries[0].reason else "On leave"
    window = technician_window(tech, day)
    if window is None:
        avail.working = False
        return avail
    avail.window_start, avail.window_end = window
    avail.working = True
    avail.skills_ok = tech.can_do(service_id) if service_id is not None else True

    blocks = blocks_for(tech, day, bookings=bookings)
    apply_travel_buffers(blocks, _buffer_minutes())
    avail.blocks = blocks
    avail.booked_minutes = sum(b.duration for b in blocks)
    avail.capacity_minutes = to_minutes(window[1]) - to_minutes(window[0])
    avail.free_slots = free_gaps(blocks, window)
    if avail.free_slots:
        avail.next_free = from_minutes(avail.free_slots[0][0])
    return avail


def free_gaps(blocks, window):
    """Free (start, end) minute ranges inside the working window."""
    win_start = to_minutes(window[0])
    win_end = to_minutes(window[1])
    gaps = []
    cursor = win_start
    for block in blocks:
        block_start = block.start_min
        block_end = block.end_min + block.travel_after
        if block_start > cursor:
            gaps.append((cursor, min(block_start, win_end)))
        cursor = max(cursor, block_end)
    if cursor < win_end:
        gaps.append((cursor, win_end))
    return [(s, e) for s, e in gaps if e > s]


def availability_map(techs, day, bookings_by_tech=None, service_id=None):
    """Availability for a list of technicians, keyed by technician id."""
    out = {}
    for tech in techs:
        bookings = (bookings_by_tech or {}).get(tech.id)
        out[tech.id] = compute_availability(tech, day, bookings=bookings, service_id=service_id)
    return out


def bookings_by_technician(day, technician_ids=None):
    """All active bookings on a date, grouped by technician id."""
    query = Booking.query.filter(
        Booking.booking_date == day,
        Booking.status.notin_(CLOSED_STATUSES),
    )
    if technician_ids:
        query = query.filter(Booking.technician_id.in_(technician_ids))
    grouped = {}
    for booking in query.all():
        grouped.setdefault(booking.technician_id, []).append(booking)
    return grouped


# ---------------------------------------------------------------
# Assignment suggestions
# ---------------------------------------------------------------
@dataclass
class Suggestion:
    tech: User
    availability: Availability
    available: bool
    reason: str
    clashes: list = field(default_factory=list)

    @property
    def conflict_count(self):
        return len(self.clashes)


def suggest_technicians(booking, techs=None, exclude_ids=None):
    """Rank technicians for a booking with a human readable reason.

    Ordering: no conflict first, then fewest clashes, then earliest free.
    """
    if techs is None:
        techs = (
            User.query.filter_by(role="TECHNICIAN", is_active=True)
            .order_by(User.name)
            .all()
        )
    exclude_ids = set(exclude_ids or ())
    techs = [t for t in techs if t.id not in exclude_ids]

    day = booking.booking_date
    start = booking.start_time
    start_min = to_minutes(start) if start else to_minutes(business_window(day)[0])
    end_min = start_min + booking.duration_minutes

    suggestions = []
    for tech in techs:
        avail = compute_availability(tech, day, service_id=booking.service_id)
        clashes = []
        if avail.working and not avail.on_leave:
            clashes = [
                b for b in conflicts(avail.blocks, start_min, end_min, booking.id)
            ]
        if not avail.working:
            reason = "Not working that day"
            available = False
        elif avail.on_leave:
            reason = f"On leave - {avail.leave_reason}" if avail.leave_reason else "On leave"
            available = False
        elif not avail.skills_ok:
            reason = "Not qualified for this service"
            available = False
        elif clashes:
            first = clashes[0]
            reason = (
                f"Busy {first.start_label} - {first.service_name}"
            )
            available = False
        else:
            reason = "Free at that time"
            available = True
        suggestions.append(
            Suggestion(
                tech=tech,
                availability=avail,
                available=available,
                reason=reason,
                clashes=clashes,
            )
        )

    suggestions.sort(
        key=lambda s: (
            0 if s.available else 1,
            s.conflict_count,
            s.availability.load_ratio,
            s.tech.name.lower(),
        )
    )
    return suggestions


def conflict_summary(suggestions):
    """Counts for the top strip of the assignment picker."""
    return {
        "free": sum(1 for s in suggestions if s.available),
        "busy": sum(1 for s in suggestions if not s.available and s.conflict_count),
        "off": sum(1 for s in suggestions if s.availability.is_off),
        "unqualified": sum(1 for s in suggestions if not s.availability.skills_ok),
        "total": len(suggestions),
    }


# ---------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------
def week_days(anchor=None):
    """The 7 dates of the week containing `anchor` (Monday first)."""
    anchor = anchor or date.today()
    monday = anchor - timedelta(days=anchor.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------
# Timeline geometry (for the CSS grid board)
# ---------------------------------------------------------------
@dataclass
class Timeline:
    """Geometry of the day board for one date."""

    day: date
    start_min: int
    end_min: int

    @property
    def total(self):
        return max(1, self.end_min - self.start_min)

    def pct(self, minute):
        """Position of a minute offset as a percentage of the track."""
        return (minute - self.start_min) / self.total * 100.0

    def clamp_pct(self, minute):
        return max(0.0, min(100.0, self.pct(minute)))

    def span_pct(self, start_minute, end_minute):
        return max(0.0, (end_minute - start_minute) / self.total * 100.0)

    def hours(self):
        """Hour marks for the ruler: [(minute, '9 AM'), ...]."""
        marks = []
        first = (self.start_min // 60) * 60
        if first < self.start_min:
            first += 60
        minute = first
        while minute <= self.end_min:
            hour = (minute // 60) % 24
            label = f"{hour:02d}:00"
            marks.append((minute, label))
            minute += 60
        return marks

    def label(self, minute):
        return from_minutes(minute).strftime("%I %p").lstrip("0")


def timeline_for(day):
    """Timeline geometry for a date, based on the business hours."""
    start, end = business_window(day)
    return Timeline(day=day, start_min=to_minutes(start), end_min=to_minutes(end))


def block_geometry(block, timeline):
    """(left%, width%) for a job block on the board."""
    left = timeline.clamp_pct(block.start_min)
    width = timeline.span_pct(block.start_min, block.end_min)
    return left, width


def travel_geometry(block, timeline):
    """(left%, width%) of the travel buffer that follows a job."""
    if not block.travel_after:
        return None
    left = timeline.clamp_pct(block.end_min)
    width = timeline.span_pct(block.end_min, block.end_min + block.travel_after)
    if width <= 0:
        return None
    return left, width



def day_load(tech, day, bookings=None):
    """(booked_minutes, capacity_minutes) for one technician on one day."""
    avail = compute_availability(tech, day, bookings=bookings)
    return avail.booked_minutes, avail.capacity_minutes


def technician_summary(tech, day, bookings=None):
    """Everything the technicians list needs about one technician."""
    avail = compute_availability(tech, day, bookings=bookings)
    week = week_days(day)
    week_load = 0
    week_capacity = 0
    for d in week:
        booked, capacity = day_load(tech, d)
        week_load += booked
        week_capacity += capacity
    return {
        "tech": tech,
        "availability": avail,
        "week_load": week_load,
        "week_capacity": week_capacity,
        "week_percent": int(round(week_load / week_capacity * 100)) if week_capacity else 0,
        "skills": sorted(tech.skills, key=lambda s: s.service.name.lower()) if tech.skills else [],
        "skill_names": [s.service.name for s in sorted(tech.skills, key=lambda s: s.service.name.lower())] if tech.skills else [],
        "leave_count": len(tech.leave or ()),
    }


def week_summary(tech, day=None):
    """Per-day availability for a technician over a week."""
    day = day or date.today()
    return technician_week(tech, week_days(day))



def technician_week(tech, days=None):
    """Availability for every day of a week, keyed by ISO date string."""
    days = days or week_days()
    grouped = bookings_by_technician(days[0], [tech.id]) if days else {}
    out = {}
    for day in days:
        out[day.isoformat()] = compute_availability(
            tech, day, bookings=grouped.get(tech.id)
        )
    return out
