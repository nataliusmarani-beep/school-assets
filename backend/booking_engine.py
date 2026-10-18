"""ICT media loan & scheduling module: schema + availability/conflict rules.

Everything here works on a plain sqlite3 connection and takes "now" as an argument, so the rules can be
tested without the web app. Times are campus-local, stored as naive ISO strings ("YYYY-MM-DDTHH:MM").
"""
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS asset_loan_settings (
    asset_id TEXT PRIMARY KEY,
    borrowable INTEGER NOT NULL DEFAULT 0,
    loan_type TEXT NOT NULL DEFAULT '',            -- 'item' (pinjam barang) | 'scheduled' (jadwal)
    accessories TEXT NOT NULL DEFAULT '[]',         -- JSON list: standard checklist at check-out / check-in
    storage_slot TEXT NOT NULL DEFAULT '',          -- e.g. "Laptop Cart A slot 12"
    max_loan_days INTEGER,                          -- NULL = use the category policy
    requires_approval INTEGER,                      -- NULL = use the category policy
    can_leave_campus INTEGER,                       -- NULL = use the category policy
    resource_id TEXT                                -- cart / lab this unit belongs to
);

CREATE TABLE IF NOT EXISTS loan_policies (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL DEFAULT '',                -- '' = every campus
    category TEXT NOT NULL,
    max_loan_days INTEGER NOT NULL DEFAULT 3,
    requires_approval INTEGER NOT NULL DEFAULT 1,
    can_leave_campus INTEGER NOT NULL DEFAULT 0,
    min_notice_days INTEGER NOT NULL DEFAULT 1,     -- H-1
    max_advance_days INTEGER NOT NULL DEFAULT 14,   -- H-14
    UNIQUE (campus, category)
);

CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                             -- laptop_cart | ipad_cart | computer_lab | room
    capacity INTEGER NOT NULL DEFAULT 1,
    location TEXT NOT NULL DEFAULT '',
    pic_user_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS school_periods (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    period_no INTEGER NOT NULL,
    start_time TEXT NOT NULL,                       -- "07:30"
    end_time TEXT NOT NULL,
    UNIQUE (campus, period_no)
);

CREATE TABLE IF NOT EXISTS holidays (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL DEFAULT '',                -- '' = every campus
    date TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    UNIQUE (campus, date)
);

CREATE TABLE IF NOT EXISTS fixed_schedules (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    semester TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    teacher_user_id TEXT,
    teacher_name TEXT NOT NULL DEFAULT '',
    weekday INTEGER NOT NULL,                       -- 0 = Monday ... 6 = Sunday
    period_from INTEGER NOT NULL,
    period_to INTEGER NOT NULL,
    units INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',          -- active | cancelled
    created_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_exceptions (
    id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL,
    date TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'cancelled',         -- cancelled (slot shows "Libur" and opens up)
    note TEXT NOT NULL DEFAULT '',
    UNIQUE (schedule_id, date)
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,                    -- PJM-2026-0001
    campus TEXT NOT NULL,
    kind TEXT NOT NULL,                             -- item | off_schedule
    resource_id TEXT,
    asset_id TEXT,                                  -- set for single-item loans
    category TEXT NOT NULL DEFAULT '',
    requester_id TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    units_requested INTEGER NOT NULL DEFAULT 1,
    units_approved INTEGER,
    class_name TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    use_location TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    take_home INTEGER NOT NULL DEFAULT 0,
    supervisor_id TEXT,
    supervisor_decision TEXT NOT NULL DEFAULT '',   -- '' | approved | rejected
    supervisor_note TEXT NOT NULL DEFAULT '',
    is_late_request INTEGER NOT NULL DEFAULT 0,     -- submitted on the day itself
    override_reason TEXT NOT NULL DEFAULT '',       -- ICT bypassed H-1 / H-14 / max days
    status TEXT NOT NULL DEFAULT 'pending_ict',
    decision_note TEXT NOT NULL DEFAULT '',
    decided_by TEXT,
    decided_by_name TEXT,
    decided_at TEXT,
    terms_accepted INTEGER NOT NULL DEFAULT 0,
    legacy_loan_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_asset ON bookings(asset_id, start_at);
CREATE INDEX IF NOT EXISTS idx_bookings_resource ON bookings(resource_id, start_at);
CREATE INDEX IF NOT EXISTS idx_bookings_requester ON bookings(requester_id, status);

CREATE TABLE IF NOT EXISTS booking_units (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    user_label TEXT NOT NULL DEFAULT '',            -- teacher name, or student name / roll number
    student_name TEXT NOT NULL DEFAULT '',
    student_no TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'reserved',        -- reserved | out | returned | not_returned | lost | damaged
    out_at TEXT,
    in_at TEXT,
    out_check TEXT NOT NULL DEFAULT '{}',           -- JSON: physical, function, accessories, note, handed_by, received_by
    in_check TEXT NOT NULL DEFAULT '{}',
    pre_photo TEXT NOT NULL DEFAULT '',
    post_photo TEXT NOT NULL DEFAULT '',
    condition_changed INTEGER NOT NULL DEFAULT 0,
    fault_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_bunits_booking ON booking_units(booking_id);
CREATE INDEX IF NOT EXISTS idx_bunits_asset ON booking_units(asset_id, status);

CREATE TABLE IF NOT EXISTS unit_assignments (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    semester TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    student_name TEXT NOT NULL DEFAULT '',
    student_no TEXT NOT NULL DEFAULT '',
    UNIQUE (academic_year, semester, asset_id)
);

CREATE TABLE IF NOT EXISTS notification_queue (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL DEFAULT 'email',          -- email | whatsapp
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    ref_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',         -- pending | sent | failed
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    sent_at TEXT
);
"""

# Starting rules per ICT category (campus '' = all campuses). Admin ICT can edit them later.
DEFAULT_POLICIES = [
    # category,          max days, approval, may leave campus
    ("IT Equipment",     1,        1,        0),   # laptop / iPad stay on campus; take-home needs the supervisor
    ("AV Equipment",     3,        1,        1),
    ("Music Equipment",  3,        1,        1),
]

# A booking holds its slot / units in these statuses. Pending requests do not (see check_availability).
COMMITTED_STATUSES = ("approved", "partially_approved", "in_use", "overdue")
PENDING_STATUSES = ("submitted", "pending_supervisor", "pending_ict")
FIXED_PRIORITY_NOTE = "Jadwal tetap selalu didahulukan."

FMT = "%Y-%m-%dT%H:%M"


class BookingError(Exception):
    """A rule was broken; the message is shown to the user (Indonesian)."""

    def __init__(self, message: str, code: str = "rule"):
        super().__init__(message)
        self.message, self.code = message, code


def new_id() -> str:
    return str(uuid.uuid4())


def init_booking_schema(conn):
    conn.executescript(SCHEMA_SQL)
    for category, days, approval, leave in DEFAULT_POLICIES:
        conn.execute("""INSERT OR IGNORE INTO loan_policies
                        (id, campus, category, max_loan_days, requires_approval, can_leave_campus)
                        VALUES (?,?,?,?,?,?)""", (new_id(), "", category, days, approval, leave))
    conn.commit()


def parse_dt(value: str) -> datetime:
    try:
        return datetime.strptime(value[:16], FMT)
    except (ValueError, TypeError):
        raise BookingError("Format waktu tidak valid (gunakan YYYY-MM-DDTHH:MM).", "format")


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


# ---- Policy ----
def get_policy(conn, campus: str, category: str, asset_id: Optional[str] = None) -> dict:
    """Effective rules for a category on a campus (campus-specific row wins over the '' default),
    with per-asset overrides from asset_loan_settings applied on top."""
    row = conn.execute("""SELECT * FROM loan_policies WHERE category = ? AND campus IN (?, '')
                          ORDER BY campus = '' LIMIT 1""", (category, campus)).fetchone()
    policy = dict(row) if row else {"max_loan_days": 3, "requires_approval": 1, "can_leave_campus": 0,
                                    "min_notice_days": 1, "max_advance_days": 14}
    if asset_id:
        s = conn.execute("SELECT * FROM asset_loan_settings WHERE asset_id = ?", (asset_id,)).fetchone()
        if s:
            for key in ("max_loan_days", "requires_approval", "can_leave_campus"):
                if s[key] is not None:
                    policy[key] = s[key]
    return policy


def asset_block_reason(conn, asset_id: str) -> Optional[str]:
    """None when the asset can be lent out right now, else why not."""
    a = conn.execute("SELECT status, asset_condition FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not a:
        return "Aset tidak ditemukan."
    s = conn.execute("SELECT borrowable FROM asset_loan_settings WHERE asset_id = ?", (asset_id,)).fetchone()
    if not s or not s["borrowable"]:
        return "Aset ini tidak dapat dipinjam."
    if a["status"] == "in_repair":
        return "Aset sedang dalam perbaikan."
    if a["status"] == "lost":
        return "Aset berstatus hilang."
    if a["status"] != "active":
        return "Aset sedang tidak aktif."
    return None


# ---- Request rules (H-1 / H-14 / max days / holidays) ----
def check_request_rules(conn, *, campus: str, category: str, asset_id: Optional[str], start: datetime, end: datetime,
                        now: datetime, take_home: bool, override: bool = False, exception: bool = False) -> dict:
    """Validate a request against the category rules. Returns {"is_late": bool, "warnings": [...]}.
    `override=True` (ICT Admin, with a reason recorded by the caller) skips the notice window, the 14-day limit,
    the maximum loan length and the take-home block. `exception=True` is a special request (e.g. take-home) that
    a supervisor decides: length and take-home are then settled by the supervisor, not by the category default."""
    if end <= start:
        raise BookingError("Waktu selesai harus setelah waktu mulai.", "time")
    policy = get_policy(conn, campus, category, asset_id)
    warnings, is_late = [], False
    days_ahead = (start.date() - now.date()).days
    if start < now and not override:
        raise BookingError("Waktu mulai sudah lewat.", "past")
    if not override:
        if days_ahead > policy["max_advance_days"]:
            raise BookingError(f"Pemesanan paling jauh H-{policy['max_advance_days']}.", "advance")
        loan_days = (end.date() - start.date()).days + 1
        if loan_days > policy["max_loan_days"] and not exception:
            raise BookingError(f"Lama pinjam maksimal {policy['max_loan_days']} hari untuk kategori ini.", "max_days")
        if take_home and not policy["can_leave_campus"] and not exception:
            raise BookingError("Aset ini tidak boleh dibawa pulang. Ajukan permintaan khusus dengan persetujuan supervisor.", "take_home")
    if days_ahead < policy["min_notice_days"]:
        is_late = True
        warnings.append("Pengajuan mendadak: tergantung ketersediaan dan keputusan Admin ICT.")
    # Holidays block every day the booking touches.
    d = start.date()
    while d <= end.date():
        h = conn.execute("SELECT name FROM holidays WHERE date = ? AND campus IN (?, '')", (d.isoformat(), campus)).fetchone()
        if h and not override:
            raise BookingError(f"{d.isoformat()} adalah hari libur sekolah ({h['name'] or 'libur'}).", "holiday")
        d += timedelta(days=1)
    return {"is_late": is_late, "warnings": warnings, "policy": policy}


# ---- Fixed schedules ----
def period_times(conn, campus: str, period_from: int, period_to: int) -> tuple:
    """("07:30", "09:10") for periods N..M of a campus."""
    a = conn.execute("SELECT start_time FROM school_periods WHERE campus = ? AND period_no = ?", (campus, period_from)).fetchone()
    b = conn.execute("SELECT end_time FROM school_periods WHERE campus = ? AND period_no = ?", (campus, period_to)).fetchone()
    if not a or not b:
        raise BookingError("Master jam pelajaran belum lengkap untuk jam yang dipilih.", "periods")
    return a["start_time"], b["end_time"]


def fixed_occurrences(conn, resource_id: str, day_from: date, day_to: date, campus: Optional[str] = None) -> list:
    """Expand fixed schedules into concrete slots between two dates (inclusive).
    A slot is dropped when the schedule is cancelled, the day is a school holiday, or an exception marks it "Libur"."""
    out = []
    schedules = conn.execute("""SELECT * FROM fixed_schedules WHERE resource_id = ? AND status = 'active'
                                AND valid_from <= ? AND valid_to >= ?""",
                             (resource_id, day_to.isoformat(), day_from.isoformat())).fetchall()
    for s in schedules:
        cam = campus or s["campus"]
        try:
            t_from, t_to = period_times(conn, s["campus"], s["period_from"], s["period_to"])
        except BookingError:
            continue
        skipped = {r["date"] for r in conn.execute("SELECT date FROM schedule_exceptions WHERE schedule_id = ?", (s["id"],))}
        holidays = {r["date"] for r in conn.execute("SELECT date FROM holidays WHERE campus IN (?, '')", (cam,))}
        d = max(day_from, date.fromisoformat(s["valid_from"]))
        last = min(day_to, date.fromisoformat(s["valid_to"]))
        while d <= last:
            if d.weekday() == s["weekday"] and d.isoformat() not in skipped and d.isoformat() not in holidays:
                out.append({"schedule_id": s["id"], "resource_id": resource_id, "units": s["units"],
                            "start": parse_dt(f"{d.isoformat()}T{t_from}"), "end": parse_dt(f"{d.isoformat()}T{t_to}"),
                            "class_name": s["class_name"], "teacher_name": s["teacher_name"]})
            d += timedelta(days=1)
    return out


# ---- Availability ----
def _booking_rows(conn, *, resource_id: Optional[str], asset_id: Optional[str], statuses: tuple, start: datetime,
                  end: datetime, exclude_booking_id: Optional[str]) -> list:
    marks = ",".join("?" * len(statuses))
    sql = f"SELECT * FROM bookings WHERE status IN ({marks}) AND start_at < ? AND end_at > ?"
    params = [*statuses, end.strftime(FMT), start.strftime(FMT)]
    if resource_id:
        sql += " AND resource_id = ?"; params.append(resource_id)
    else:
        sql += " AND asset_id = ?"; params.append(asset_id)
    if exclude_booking_id:
        sql += " AND id != ?"; params.append(exclude_booking_id)
    return [dict(r) for r in conn.execute(sql, params)]


def _peak_usage(slots: list, start: datetime, end: datetime) -> int:
    """Highest number of units in use at the same moment inside [start, end), given (start, end, units) slots."""
    points = {start}
    for s, e, _ in slots:
        for p in (s, e):
            if start <= p < end:
                points.add(p)
    return max((sum(u for s, e, u in slots if s <= p < e) for p in points), default=0)


def check_availability(conn, *, resource_id: Optional[str] = None, asset_id: Optional[str] = None, units: int = 1,
                       start: datetime, end: datetime, exclude_booking_id: Optional[str] = None) -> dict:
    """How many units are free for the whole window. Committed bookings and fixed schedules hold their units;
    pending requests are reported separately (they only hold a slot once approved).
    Returns {"capacity", "used", "free", "pending", "ok", "conflicts": [...]}."""
    if bool(resource_id) == bool(asset_id):
        raise ValueError("pass exactly one of resource_id / asset_id")
    if resource_id:
        r = conn.execute("SELECT capacity, active FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if not r or not r["active"]:
            raise BookingError("Sumber daya (cart/lab) tidak ditemukan atau tidak aktif.", "resource")
        capacity = r["capacity"]
    else:
        capacity = 1
    committed = _booking_rows(conn, resource_id=resource_id, asset_id=asset_id, statuses=COMMITTED_STATUSES,
                              start=start, end=end, exclude_booking_id=exclude_booking_id)
    slots, conflicts = [], []
    for b in committed:
        slots.append((parse_dt(b["start_at"]), parse_dt(b["end_at"]), b["units_approved"] or b["units_requested"]))
        conflicts.append({"type": "booking", "id": b["id"], "number": b["number"], "start": b["start_at"], "end": b["end_at"],
                          "requester": b["requester_name"]})
    if resource_id:
        for occ in fixed_occurrences(conn, resource_id, start.date(), end.date()):
            if overlaps(occ["start"], occ["end"], start, end):
                slots.append((occ["start"], occ["end"], occ["units"]))
                conflicts.append({"type": "fixed", "id": occ["schedule_id"], "start": occ["start"].strftime(FMT),
                                  "end": occ["end"].strftime(FMT), "requester": f"{occ['class_name']} ({occ['teacher_name']})"})
    used = _peak_usage(slots, start, end)
    pending = sum(b["units_requested"] for b in _booking_rows(
        conn, resource_id=resource_id, asset_id=asset_id, statuses=PENDING_STATUSES, start=start, end=end,
        exclude_booking_id=exclude_booking_id))
    free = max(capacity - used, 0)
    return {"capacity": capacity, "used": used, "free": free, "pending": pending,
            "ok": units <= free, "conflicts": conflicts if units > free else []}


def next_booking_number(conn, year: int) -> str:
    """PJM-2026-0001 ... Safe inside the caller's write transaction."""
    prefix = f"PJM-{year}-"
    last = conn.execute("SELECT number FROM bookings WHERE number LIKE ? ORDER BY number DESC LIMIT 1", (prefix + "%",)).fetchone()
    n = int(last["number"].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def reserve(conn, *, data: dict, now: datetime, override: bool = False, override_reason: str = "") -> dict:
    """Create a booking. The whole check-then-insert runs under one write lock (BEGIN IMMEDIATE), so two people
    asking for the last unit at the same moment cannot both succeed.

    `data` keys: campus, kind ('item'|'off_schedule'), resource_id | asset_id, category, requester_id, requester_name,
    start_at, end_at, units (default 1), class_name, subject, purpose, use_location, note, take_home, supervisor_id,
    terms_accepted. Returns the stored booking row (dict)."""
    if override and not override_reason.strip():
        raise BookingError("Alasan wajib diisi untuk pengecualian aturan.", "override_reason")
    if not data.get("terms_accepted"):
        raise BookingError("Pemohon harus menyetujui pernyataan tanggung jawab atas aset.", "terms")
    start, end = parse_dt(data["start_at"]), parse_dt(data["end_at"])
    units = int(data.get("units") or 1)
    if units < 1:
        raise BookingError("Jumlah unit minimal 1.", "units")
    resource_id, asset_id = data.get("resource_id"), data.get("asset_id")
    if bool(resource_id) == bool(asset_id):
        raise BookingError("Pilih satu aset atau satu cart/lab.", "target")
    take_home = bool(data.get("take_home"))
    if take_home and not data.get("supervisor_id") and not override:
        raise BookingError("Permintaan bawa pulang membutuhkan supervisor.", "supervisor")

    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if asset_id:
            reason = asset_block_reason(conn, asset_id)
            if reason:
                raise BookingError(reason, "asset")
        check = check_request_rules(conn, campus=data["campus"], category=data["category"], asset_id=asset_id,
                                    start=start, end=end, now=now, take_home=take_home, override=override,
                                    exception=take_home and bool(data.get("supervisor_id")))
        # A requester with an overdue loan cannot borrow again.
        late = conn.execute("SELECT number FROM bookings WHERE requester_id = ? AND status = 'overdue' LIMIT 1",
                            (data["requester_id"],)).fetchone()
        if late and not override:
            raise BookingError(f"Anda masih memiliki pinjaman terlambat ({late['number']}). Kembalikan terlebih dahulu.", "overdue")
        avail = check_availability(conn, resource_id=resource_id, asset_id=asset_id, units=units, start=start, end=end)
        if not avail["ok"]:
            raise BookingError(f"Tidak tersedia pada waktu tersebut. Tersisa {avail['free']} unit.", "conflict")
        # Pending order: exceptional take-home waits for the supervisor first; otherwise ICT decides, unless the
        # category needs no approval and the request is not a last-minute one.
        policy = check["policy"]
        if take_home and not policy["can_leave_campus"]:
            status = "pending_supervisor"
        elif policy["requires_approval"] or check["is_late"]:
            status = "pending_ict"
        else:
            status = "approved"
        bid, ts = new_id(), now.strftime(FMT)
        number = next_booking_number(conn, now.year)
        conn.execute("""INSERT INTO bookings (id, number, campus, kind, resource_id, asset_id, category, requester_id, requester_name,
            start_at, end_at, units_requested, units_approved, class_name, subject, purpose, use_location, note, take_home,
            supervisor_id, is_late_request, override_reason, status, terms_accepted, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (bid, number, data["campus"], data["kind"], resource_id, asset_id, data["category"], data["requester_id"],
                      data["requester_name"], start.strftime(FMT), end.strftime(FMT), units, units if status == "approved" else None,
                      data.get("class_name", ""), data.get("subject", ""), data.get("purpose", ""), data.get("use_location", ""),
                      data.get("note", ""), int(take_home), data.get("supervisor_id"), int(check["is_late"]),
                      override_reason.strip() if override else "", status, 1, ts, ts))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    row = dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone())
    row["warnings"] = check["warnings"]
    return row


def decide(conn, *, booking_id: str, decision: str, by_id: str, by_name: str, now: datetime, units: Optional[int] = None,
           start_at: Optional[str] = None, end_at: Optional[str] = None, note: str = "") -> dict:
    """ICT decision: 'approved' | 'partially_approved' | 'rejected'. Partial approval may lower the units and/or move
    the time. Availability is re-checked under the write lock because the world may have changed since the request."""
    if decision not in ("approved", "partially_approved", "rejected"):
        raise BookingError("Keputusan tidak valid.", "decision")
    if decision != "approved" and not note.strip():
        raise BookingError("Alasan/catatan wajib diisi bila disetujui sebagian atau ditolak.", "note")
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not b:
            raise BookingError("Pengajuan tidak ditemukan.", "missing")
        if b["status"] not in ("pending_ict", "submitted"):
            raise BookingError("Pengajuan ini tidak sedang menunggu konfirmasi ICT.", "state")
        start, end = parse_dt(start_at or b["start_at"]), parse_dt(end_at or b["end_at"])
        approved_units = b["units_requested"]
        if decision != "rejected":
            approved_units = int(units if units is not None else b["units_requested"])
            if approved_units < 1 or approved_units > b["units_requested"]:
                raise BookingError("Jumlah yang disetujui harus antara 1 dan jumlah yang diminta.", "units")
            if end <= start:
                raise BookingError("Waktu selesai harus setelah waktu mulai.", "time")
            if decision == "partially_approved" and approved_units == b["units_requested"] \
                    and start.strftime(FMT) == b["start_at"] and end.strftime(FMT) == b["end_at"]:
                raise BookingError("Persetujuan sebagian harus mengubah jumlah unit atau waktu.", "partial")
            avail = check_availability(conn, resource_id=b["resource_id"], asset_id=b["asset_id"], units=approved_units,
                                       start=start, end=end, exclude_booking_id=b["id"])
            if not avail["ok"]:
                raise BookingError(f"Bentrok: hanya tersisa {avail['free']} unit pada waktu tersebut.", "conflict")
        conn.execute("""UPDATE bookings SET status = ?, units_approved = ?, start_at = ?, end_at = ?, decision_note = ?,
                        decided_by = ?, decided_by_name = ?, decided_at = ?, updated_at = ? WHERE id = ?""",
                     (decision, None if decision == "rejected" else approved_units, start.strftime(FMT), end.strftime(FMT),
                      note.strip(), by_id, by_name, now.strftime(FMT), now.strftime(FMT), booking_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())


def mark_overdue(conn, now: datetime) -> int:
    """Move loans that passed their end time without being returned to 'overdue'. Returns how many changed."""
    n = conn.execute("UPDATE bookings SET status = 'overdue', updated_at = ? WHERE status = 'in_use' AND end_at < ?",
                     (now.strftime(FMT), now.strftime(FMT))).rowcount
    conn.commit()
    return n


# ---- Migration of the old single-asset loan_requests ----
_LEGACY_STATUS = {"pending": "pending_ict", "approved": "approved", "rejected": "rejected", "active": "in_use",
                  "returned": "completed", "cancelled": "cancelled"}


def _legacy_dt(value: Optional[str], default_time: str, fallback_date: str) -> str:
    v = (value or "").strip()
    if not v:
        return f"{fallback_date}T{default_time}"
    return v[:16] if "T" in v else f"{v[:10]}T{default_time}"


def migrate_legacy_loans(conn) -> int:
    """Copy old loan_requests into bookings (+ one booking_unit with the before/after photos and condition notes).
    Safe to run on every start: rows already copied (legacy_loan_id) are skipped and the old table is left untouched.
    Old date-only loans become 08:00-17:00 on their dates. Returns the number copied."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='loan_requests'").fetchone():
        return 0
    rows = conn.execute("""SELECT lr.*, a.campus AS a_campus, a.category AS a_category FROM loan_requests lr
                           LEFT JOIN assets a ON a.id = lr.asset_id
                           WHERE lr.id NOT IN (SELECT legacy_loan_id FROM bookings WHERE legacy_loan_id IS NOT NULL)
                           ORDER BY lr.created_at""").fetchall()
    if not rows:
        return 0
    import json
    conn.execute("BEGIN IMMEDIATE")
    try:
        for r in rows:
            created = (r["created_at"] or "")[:10] or "2026-01-01"
            status = _LEGACY_STATUS.get(r["status"], "completed")
            start_at = _legacy_dt(r["start_date"], "08:00", created)
            end_at = _legacy_dt(r["end_date"], "17:00", start_at[:10])
            if end_at <= start_at:
                end_at = f"{start_at[:10]}T17:00" if start_at[11:] < "17:00" else f"{start_at[:10]}T23:59"
            bid = new_id()
            number = next_booking_number(conn, int(created[:4]))
            conn.execute("""INSERT INTO bookings (id, number, campus, kind, asset_id, category, requester_id, requester_name, start_at,
                end_at, units_requested, units_approved, purpose, status, decision_note, decided_by, decided_by_name, decided_at,
                terms_accepted, legacy_loan_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,1,?,?,?)""",
                         (bid, number, r["a_campus"] or "", "item", r["asset_id"], r["a_category"] or "", r["requested_by"],
                          r["requested_by_name"], start_at, end_at, 1 if status not in ("rejected", "pending_ict") else None,
                          r["purpose"] or "", status, r["reject_reason"] or "", r["reviewed_by"], r["reviewed_by_name"], r["reviewed_at"],
                          r["id"], r["created_at"], r["reviewed_at"] or r["created_at"]))
            if r["delivered_at"] or r["pre_image_path"] or r["returned_at"]:
                out_check = {"condition": r["pre_condition"] or "", "note": r["pre_condition_note"] or ""}
                in_check = {"condition": r["post_condition"] or "", "note": r["post_condition_note"] or ""}
                changed = int(bool(r["post_condition"]) and r["post_condition"] != "good")
                conn.execute("""INSERT INTO booking_units (id, booking_id, asset_id, user_label, status, out_at, in_at, out_check,
                    in_check, pre_photo, post_photo, condition_changed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (new_id(), bid, r["asset_id"], r["requested_by_name"], "returned" if r["returned_at"] else "out",
                              r["delivered_at"], r["returned_at"], json.dumps(out_check), json.dumps(in_check),
                              r["pre_image_path"] or "", r["post_image_path"] or "", changed))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return len(rows)
