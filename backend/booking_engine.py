"""ICT media loan & scheduling module: schema + availability/conflict rules.

Everything here works on a plain sqlite3 connection and takes "now" as an argument, so the rules can be
tested without the web app. Times are campus-local, stored as naive ISO strings ("YYYY-MM-DDTHH:MM").
"""
import re
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
    category TEXT NOT NULL DEFAULT 'IT Equipment',  -- decides the rules and who confirms (ICT Admin for ICT categories)
    location TEXT NOT NULL DEFAULT '',
    pic_user_id TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT ''                   -- school unit: PAUD | SD | SMP ('' = follows the campus-wide periods)
);

CREATE TABLE IF NOT EXISTS school_periods (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    period_no INTEGER NOT NULL,
    start_time TEXT NOT NULL,                       -- "07:30"
    end_time TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',                  -- PAUD | SD | SMP ('' = campus-wide default)
    UNIQUE (campus, unit, period_no)
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
    schedule_id TEXT,                               -- set for a fixed-schedule session that was handed over (kind 'fixed')
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


def _ensure_column(conn, table: str, column: str, ddl: str):
    if column not in [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_school_periods_unit(conn):
    """Periods used to be one list per campus; they are now one list per campus and school unit (PAUD / SD / SMP)."""
    if "unit" in [r[1] for r in conn.execute("PRAGMA table_info(school_periods)").fetchall()]:
        return
    conn.executescript("""
        ALTER TABLE school_periods RENAME TO school_periods_old;
        CREATE TABLE school_periods (
            id TEXT PRIMARY KEY, campus TEXT NOT NULL, period_no INTEGER NOT NULL,
            start_time TEXT NOT NULL, end_time TEXT NOT NULL, unit TEXT NOT NULL DEFAULT '',
            UNIQUE (campus, unit, period_no));
        INSERT INTO school_periods (id, campus, period_no, start_time, end_time, unit)
            SELECT id, campus, period_no, start_time, end_time, '' FROM school_periods_old;
        DROP TABLE school_periods_old;
    """)


def init_booking_schema(conn):
    conn.executescript(SCHEMA_SQL)
    _migrate_school_periods_unit(conn)
    # columns added after the first release of the module
    _ensure_column(conn, "resources", "unit", "TEXT NOT NULL DEFAULT ''")
    # carts / labs created before school units existed: take the unit from the name ("Lab Komputer SD")
    for r in conn.execute("SELECT id, name FROM resources WHERE unit = ''").fetchall():
        found = [u for u in ("PAUD", "SD", "SMP") if re.search(rf"\b{u}\b", r["name"], re.I)]
        if len(found) == 1:
            conn.execute("UPDATE resources SET unit = ? WHERE id = ?", (found[0], r["id"]))
    _ensure_column(conn, "resources", "category", "TEXT NOT NULL DEFAULT 'IT Equipment'")
    _ensure_column(conn, "bookings", "schedule_id", "TEXT")
    _ensure_column(conn, "bookings", "device_type", "TEXT NOT NULL DEFAULT ''")          # 'laptop' | 'ipad' for kind 'pool'
    _ensure_column(conn, "loan_policies", "max_units", "INTEGER NOT NULL DEFAULT 10")      # most units one request may ask for
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_fixed_session ON bookings(schedule_id, start_at) WHERE schedule_id IS NOT NULL")
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
                                    "min_notice_days": 1, "max_advance_days": 14, "max_units": 10}
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
def resource_unit(conn, resource_id: Optional[str]) -> str:
    r = conn.execute("SELECT unit FROM resources WHERE id = ?", (resource_id,)).fetchone() if resource_id else None
    return (r["unit"] if r else "") or ""


def periods_for(conn, campus: str, unit: str = "") -> list:
    """Lesson periods of a school unit; a unit without its own list follows the campus-wide one."""
    for u in ([unit, ""] if unit else [""]):
        rows = conn.execute("SELECT period_no, start_time, end_time FROM school_periods WHERE campus = ? AND unit = ? ORDER BY period_no", (campus, u)).fetchall()
        if rows:
            return [dict(r) for r in rows]
    return []


def period_times(conn, campus: str, period_from: int, period_to: int, unit: str = "") -> tuple:
    """("07:30", "09:10") for periods N..M of a campus (and school unit)."""
    by_no = {p["period_no"]: p for p in periods_for(conn, campus, unit)}
    a, b = by_no.get(period_from), by_no.get(period_to)
    if not a or not b:
        where = f" unit {unit}" if unit else ""
        raise BookingError(f"Master jam pelajaran{where} belum lengkap untuk jam yang dipilih (jam ke-{period_from}–{period_to}). "
                           "Isi dulu di tab Jam pelajaran.", "periods")
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
            t_from, t_to = period_times(conn, s["campus"], s["period_from"], s["period_to"], resource_unit(conn, s["resource_id"]))
        except BookingError:
            continue
        skipped = {r["date"] for r in conn.execute("SELECT date FROM schedule_exceptions WHERE schedule_id = ?", (s["id"],))}
        holidays = {r["date"] for r in conn.execute("SELECT date FROM holidays WHERE campus IN (?, '')", (cam,))}
        d = max(day_from, date.fromisoformat(s["valid_from"]))
        last = min(day_to, date.fromisoformat(s["valid_to"]))
        while d <= last:
            if d.weekday() == s["weekday"] and d.isoformat() not in skipped and d.isoformat() not in holidays:
                start_dt = parse_dt(f"{d.isoformat()}T{t_from}")
                done = conn.execute("SELECT id, status FROM bookings WHERE schedule_id = ? AND start_at = ?",
                                    (s["id"], start_dt.strftime(FMT))).fetchone()
                out.append({"schedule_id": s["id"], "resource_id": resource_id, "units": s["units"],
                            "materialized": bool(done), "booking_id": done["id"] if done else None,
                            "booking_status": done["status"] if done else None,
                            "subject": s["subject"], "period_from": s["period_from"], "period_to": s["period_to"],
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


# ---- Pool loans: a teacher asks for "N laptops / iPads"; ICT picks the exact units that are still free ----
POOL_TYPES = {
    "laptop": ("Laptop", ("laptop", "notebook", "macbook", "chromebook")),
    "ipad": ("iPad", ("ipad", "tablet")),
}
POOL_CATEGORY = "IT Equipment"


def pool_label(device_type: str) -> str:
    return POOL_TYPES.get(device_type, (device_type or "", ()))[0]


def _committed_marks() -> str:
    return ",".join("?" * len(COMMITTED_STATUSES))


def pool_free_units(conn, campus: str, device_type: str, start: datetime, end: datetime,
                    exclude_booking_id: Optional[str] = None) -> list:
    """Borrowable, active laptops / iPads of the campus that nobody holds during [start, end).
    A unit is busy when it is out on loan, reserved for another approved pool request, or booked as a single item.
    Units inside a cart also carry `cart_free`: how many more of that cart may be taken for this window."""
    if device_type not in POOL_TYPES:
        raise BookingError("Jenis perangkat tidak dikenal.", "device_type")
    words = POOL_TYPES[device_type][1]
    rows = conn.execute("""SELECT a.id, a.name, a.asset_tag, a.item_type, a.brand, a.model, a.serial_number, s.resource_id, r.name AS resource_name
                           FROM assets a JOIN asset_loan_settings s ON s.asset_id = a.id LEFT JOIN resources r ON r.id = s.resource_id
                           WHERE s.borrowable = 1 AND a.status = 'active' AND a.campus = ? AND a.category = ?
                           ORDER BY a.asset_tag""", (campus, POOL_CATEGORY)).fetchall()
    cands = []
    for r in rows:
        hay = f"{r['item_type']} {r['name']} {r['model']}".lower()
        if any(w in hay for w in words):
            cands.append(dict(r))
    if not cands:
        return []
    ex, exp = (" AND b.id != ?", [exclude_booking_id]) if exclude_booking_id else ("", [])
    fs, fe = end.strftime(FMT), start.strftime(FMT)
    busy = {r[0] for r in conn.execute(f"SELECT u.asset_id FROM booking_units u JOIN bookings b ON b.id = u.booking_id WHERE u.status = 'out'{ex}", exp)}
    busy |= {r[0] for r in conn.execute(
        f"""SELECT u.asset_id FROM booking_units u JOIN bookings b ON b.id = u.booking_id
            WHERE u.status = 'reserved' AND b.status IN ({_committed_marks()}) AND b.start_at < ? AND b.end_at > ?{ex}""",
        [*COMMITTED_STATUSES, fs, fe, *exp])}
    busy |= {r[0] for r in conn.execute(
        f"""SELECT b.asset_id FROM bookings b WHERE b.asset_id IS NOT NULL AND b.status IN ({_committed_marks()})
            AND b.start_at < ? AND b.end_at > ?{ex}""", [*COMMITTED_STATUSES, fs, fe, *exp])}
    free, cart_cache = [], {}
    for c in cands:
        if c["id"] in busy:
            continue
        rid = c["resource_id"]
        if rid:
            if rid not in cart_cache:
                try:
                    cart_cache[rid] = check_availability(conn, resource_id=rid, units=1, start=start, end=end,
                                                         exclude_booking_id=exclude_booking_id)["free"]
                except BookingError:
                    cart_cache[rid] = 0
            c["cart_free"] = cart_cache[rid]
            if c["cart_free"] <= 0:
                continue
        else:
            c["cart_free"] = None
        free.append(c)
    return free


def validate_pool_selection(conn, booking: dict, unit_ids: list, start: datetime, end: datetime) -> None:
    """ICT's pick must be free units of the right kind, within what each cart can still give for that window."""
    if len(set(unit_ids)) != len(unit_ids):
        raise BookingError("Unit terpilih terduplikasi.", "units")
    free = {u["id"]: u for u in pool_free_units(conn, booking["campus"], booking["device_type"], start, end, booking["id"])}
    per_cart = {}
    for uid in unit_ids:
        u = free.get(uid)
        if not u:
            raise BookingError("Ada unit terpilih yang tidak tersedia pada waktu tersebut (sudah dipinjam/dipesan, rusak, atau bukan "
                               f"{pool_label(booking['device_type'])}).", "units")
        if u["resource_id"]:
            per_cart[u["resource_id"]] = per_cart.get(u["resource_id"], 0) + 1
            if per_cart[u["resource_id"]] > u["cart_free"]:
                raise BookingError(f"Cart {u['resource_name']} hanya dapat memberi {u['cart_free']} unit pada waktu tersebut "
                                   "(sisanya dipakai jadwal tetap/peminjaman lain).", "conflict")


def _pool_slots(conn, *, asset_id=None, resource_id=None, start: datetime, end: datetime, exclude_booking_id=None) -> list:
    """(start, end, units, row) for approved pool requests that hold this asset / part of this cart."""
    ex, exp = (" AND b.id != ?", [exclude_booking_id]) if exclude_booking_id else ("", [])
    base = f"""FROM booking_units u JOIN bookings b ON b.id = u.booking_id {{join}}
               WHERE b.kind = 'pool' AND u.status IN ('reserved', 'out') AND b.status IN ({_committed_marks()})
               AND b.start_at < ? AND b.end_at > ?{ex} AND {{cond}}"""
    args = [*COMMITTED_STATUSES, end.strftime(FMT), start.strftime(FMT), *exp]
    if asset_id:
        q = "SELECT b.id, b.number, b.start_at, b.end_at, b.requester_name, 1 AS n " + base.format(join="", cond="u.asset_id = ?")
        args.append(asset_id)
    else:
        q = ("SELECT b.id, b.number, b.start_at, b.end_at, b.requester_name, COUNT(*) AS n "
             + base.format(join="JOIN asset_loan_settings s ON s.asset_id = u.asset_id", cond="s.resource_id = ?") + " GROUP BY b.id")
        args.append(resource_id)
    return [dict(r) for r in conn.execute(q, args)]


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
        capacity = resource_capacity(conn, resource_id)
    else:
        capacity = 1
    committed = _booking_rows(conn, resource_id=resource_id, asset_id=asset_id, statuses=COMMITTED_STATUSES,
                              start=start, end=end, exclude_booking_id=exclude_booking_id)
    slots, conflicts = [], []
    for b in committed:
        slots.append((parse_dt(b["start_at"]), parse_dt(b["end_at"]), b["units_approved"] or b["units_requested"]))
        conflicts.append({"type": "booking", "id": b["id"], "number": b["number"], "start": b["start_at"], "end": b["end_at"],
                          "requester": b["requester_name"]})
    for pb in _pool_slots(conn, asset_id=asset_id, resource_id=resource_id, start=start, end=end, exclude_booking_id=exclude_booking_id):
        slots.append((parse_dt(pb["start_at"]), parse_dt(pb["end_at"]), pb["n"]))
        conflicts.append({"type": "booking", "id": pb["id"], "number": pb["number"], "start": pb["start_at"], "end": pb["end_at"],
                          "requester": pb["requester_name"]})
    if resource_id:
        for occ in fixed_occurrences(conn, resource_id, start.date(), end.date()):
            if occ["materialized"]:
                continue            # already handed over: the booking above (if still active) holds the units instead
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


def resource_capacity(conn, resource_id: str) -> int:
    """Units that can be used right now: the active borrowable units assigned to the cart / lab,
    or the configured capacity when no individual units are registered."""
    r = conn.execute("SELECT capacity FROM resources WHERE id = ?", (resource_id,)).fetchone()
    n = conn.execute("""SELECT COUNT(*) FROM asset_loan_settings s JOIN assets a ON a.id = s.asset_id
                        WHERE s.resource_id = ? AND s.borrowable = 1 AND a.status = 'active'""", (resource_id,)).fetchone()[0]
    return n if n else (r["capacity"] if r else 0)


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
    device_type = data.get("device_type") or ""
    if device_type:
        if device_type not in POOL_TYPES or resource_id or asset_id:
            raise BookingError("Pilih jenis perangkat (laptop/iPad) saja, tanpa memilih aset tertentu.", "target")
        if data.get("take_home"):
            raise BookingError("Laptop/iPad tidak dapat dibawa keluar sekolah.", "take_home")
    elif bool(resource_id) == bool(asset_id):
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
        if device_type:
            max_units = int(check["policy"].get("max_units") or 10)
            if units > max_units and not override:
                raise BookingError(f"Satu permintaan maksimal {max_units} unit untuk kategori ini.", "max_units")
            free_n = len(pool_free_units(conn, data["campus"], device_type, start, end))
            if units > free_n:
                raise BookingError(f"Tidak tersedia pada waktu tersebut. Tersisa {free_n} {pool_label(device_type)}.", "conflict")
        else:
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
            supervisor_id, is_late_request, override_reason, status, terms_accepted, created_at, updated_at, device_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (bid, number, data["campus"], data["kind"], resource_id, asset_id, data["category"], data["requester_id"],
                      data["requester_name"], start.strftime(FMT), end.strftime(FMT), units, units if status == "approved" else None,
                      data.get("class_name", ""), data.get("subject", ""), data.get("purpose", ""), data.get("use_location", ""),
                      data.get("note", ""), int(take_home), data.get("supervisor_id"), int(check["is_late"]),
                      override_reason.strip() if override else "", status, 1, ts, ts, device_type))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    row = dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone())
    row["warnings"] = check["warnings"]
    return row


def decide(conn, *, booking_id: str, decision: str, by_id: str, by_name: str, now: datetime, units: Optional[int] = None,
           start_at: Optional[str] = None, end_at: Optional[str] = None, note: str = "",
           unit_ids: Optional[list] = None) -> dict:
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
            if b["kind"] == "pool":
                unit_ids = list(unit_ids or [])
                if len(unit_ids) != approved_units:
                    raise BookingError(f"Pilih tepat {approved_units} unit {pool_label(b['device_type'])} yang akan dipinjamkan.", "units")
                validate_pool_selection(conn, dict(b), unit_ids, start, end)
            else:
                avail = check_availability(conn, resource_id=b["resource_id"], asset_id=b["asset_id"], units=approved_units,
                                           start=start, end=end, exclude_booking_id=b["id"])
                if not avail["ok"]:
                    raise BookingError(f"Bentrok: hanya tersisa {avail['free']} unit pada waktu tersebut.", "conflict")
        conn.execute("""UPDATE bookings SET status = ?, units_approved = ?, start_at = ?, end_at = ?, decision_note = ?,
                        decided_by = ?, decided_by_name = ?, decided_at = ?, updated_at = ? WHERE id = ?""",
                     (decision, None if decision == "rejected" else approved_units, start.strftime(FMT), end.strftime(FMT),
                      note.strip(), by_id, by_name, now.strftime(FMT), now.strftime(FMT), booking_id))
        if b["kind"] == "pool":      # the chosen units are held for this request from now on
            conn.execute("DELETE FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (booking_id,))
            if decision != "rejected":
                for uid in unit_ids:
                    conn.execute("INSERT INTO booking_units (id, booking_id, asset_id, user_label, status) VALUES (?,?,?,?, 'reserved')",
                                 (new_id(), booking_id, uid, b["requester_name"]))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())


def mark_overdue(conn, now: datetime) -> int:
    """Move loans that passed their end time without being returned to 'overdue'. Returns how many changed."""
    return len(newly_overdue(conn, now))


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


# ---- Supervisor step, cancel ----
def supervisor_decide(conn, *, booking_id: str, approve: bool, by_id: str, now: datetime, note: str = "") -> dict:
    """The requester's supervisor settles a special request (e.g. take-home). Approved goes on to ICT."""
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not b:
        raise BookingError("Pengajuan tidak ditemukan.", "missing")
    if b["status"] != "pending_supervisor":
        raise BookingError("Pengajuan ini tidak menunggu persetujuan supervisor.", "state")
    if b["supervisor_id"] != by_id:
        raise BookingError("Hanya supervisor yang ditunjuk yang dapat memutuskan.", "forbidden")
    if not approve and not note.strip():
        raise BookingError("Alasan wajib diisi bila menolak.", "note")
    status = "pending_ict" if approve else "rejected"
    conn.execute("""UPDATE bookings SET supervisor_decision = ?, supervisor_note = ?, status = ?, updated_at = ?,
                    decision_note = CASE WHEN ? THEN decision_note ELSE ? END WHERE id = ?""",
                 ("approved" if approve else "rejected", note.strip(), status, now.strftime(FMT), int(approve),
                  "Ditolak supervisor: " + note.strip(), booking_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())


def cancel(conn, *, booking_id: str, by_id: str, can_manage: bool, now: datetime, reason: str = "") -> dict:
    """Requester (or ICT) cancels a booking that has not been handed over yet."""
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not b:
        raise BookingError("Pengajuan tidak ditemukan.", "missing")
    if b["requester_id"] != by_id and not can_manage:
        raise BookingError("Anda tidak dapat membatalkan pengajuan ini.", "forbidden")
    if b["status"] not in PENDING_STATUSES + ("approved", "partially_approved"):
        raise BookingError("Pengajuan yang sudah diserahkan atau selesai tidak dapat dibatalkan.", "state")
    conn.execute("UPDATE bookings SET status = 'cancelled', decision_note = ?, updated_at = ? WHERE id = ?",
                 (reason.strip() or b["decision_note"], now.strftime(FMT), booking_id))
    conn.execute("DELETE FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (booking_id,))
    conn.commit()
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())


# ---- Check-out / check-in ----
PHYSICAL = ("baik", "lecet", "retak", "lainnya")
FUNCTION = ("normal", "masalah")
RETURN_RESULTS = ("ok", "changed", "damaged", "lost")


def accessory_names(conn, asset_id: str) -> list:
    import json
    s = conn.execute("SELECT accessories FROM asset_loan_settings WHERE asset_id = ?", (asset_id,)).fetchone()
    try:
        return list(json.loads(s["accessories"])) if s else []
    except (ValueError, TypeError):
        return []


def _photo_ok(conn, path: str) -> bool:
    return bool(path) and bool(conn.execute("SELECT 1 FROM files WHERE storage_path = ? AND is_deleted = 0", (path,)).fetchone())


def _check_accessories(conn, asset_id: str, given: list) -> list:
    """Every standard accessory must be ticked present or absent. Returns the list of missing ones."""
    expected = accessory_names(conn, asset_id)
    answers = {str(a.get("name")): bool(a.get("ok")) for a in (given or [])}
    unanswered = [n for n in expected if n not in answers]
    if unanswered:
        raise BookingError("Kelengkapan belum diperiksa: " + ", ".join(unanswered), "accessories")
    return [n for n in expected if not answers[n]]


def check_out(conn, *, booking_id: str, units: list, now: datetime, by_id: str, by_name: str, group_photo: str = "") -> dict:
    """Hand the asset(s) over. Each unit: {asset_id, physical, function, accessories:[{name, ok}], note, photo,
    user_label, student_name, student_no, class_name}. A before-photo is mandatory for every unit of an item loan
    (for a cart / lab one `group_photo` covering all slots is enough)."""
    import json
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not b:
            raise BookingError("Pengajuan tidak ditemukan.", "missing")
        if b["status"] not in ("approved", "partially_approved"):
            raise BookingError("Hanya pengajuan yang sudah disetujui yang dapat diserahkan.", "state")
        if parse_dt(b["start_at"]).date() > now.date():
            raise BookingError("Belum waktunya: penyerahan baru dapat dilakukan pada tanggal mulai.", "too_early")
        if not units:
            raise BookingError("Pilih unit yang diserahkan.", "units")
        allowed = b["units_approved"] or b["units_requested"]
        if len(units) > allowed:
            raise BookingError(f"Jumlah unit melebihi yang disetujui ({allowed}).", "units")
        seen = set()
        reserved = {}
        free_ids = set()
        if b["kind"] == "pool":
            reserved = {r["asset_id"]: r["id"] for r in conn.execute(
                "SELECT id, asset_id FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (booking_id,))}
            free_ids = {x["id"] for x in pool_free_units(conn, b["campus"], b["device_type"], parse_dt(b["start_at"]), parse_dt(b["end_at"]), booking_id)}
        for u in units:
            aid = u.get("asset_id")
            if not aid or aid in seen:
                raise BookingError("Unit tidak valid atau terduplikasi.", "units")
            seen.add(aid)
            if b["kind"] == "pool" and aid not in reserved and aid not in free_ids:
                raise BookingError("Unit pengganti tidak tersedia pada waktu pinjam ini.", "units")
            if b["asset_id"] and aid != b["asset_id"]:
                raise BookingError("Unit tidak sesuai dengan aset yang disetujui.", "units")
            if b["resource_id"]:
                st = conn.execute("SELECT resource_id FROM asset_loan_settings WHERE asset_id = ?", (aid,)).fetchone()
                if not st or st["resource_id"] != b["resource_id"]:
                    raise BookingError("Unit bukan bagian dari cart/lab yang dipinjam.", "units")
            reason = asset_block_reason(conn, aid)
            if reason:
                raise BookingError(reason, "asset")
            if conn.execute("SELECT 1 FROM booking_units WHERE asset_id = ? AND status = 'out'", (aid,)).fetchone():
                raise BookingError("Unit ini masih tercatat dipinjam oleh pengajuan lain.", "already_out")
            if u.get("physical") not in PHYSICAL or u.get("function") not in FUNCTION:
                raise BookingError("Kondisi fisik dan fungsi wajib diisi.", "condition")
            missing = _check_accessories(conn, aid, u.get("accessories"))
            if (missing or u["physical"] != "baik" or u["function"] != "normal") and not (u.get("note") or "").strip():
                raise BookingError("Catatan wajib diisi bila kondisi tidak sempurna atau kelengkapan kurang.", "note")
            photo = u.get("photo") or group_photo
            if not _photo_ok(conn, photo):
                raise BookingError("Foto sebelum wajib diunggah.", "photo")
            u["_photo"], u["_missing"] = photo, missing
        ts = now.strftime(FMT)
        for u in units:
            check = {"physical": u["physical"], "function": u["function"], "accessories": u.get("accessories") or [],
                     "missing": u["_missing"], "note": (u.get("note") or "").strip(), "handed_by": by_name,
                     "received_by": b["requester_name"]}
            if u["asset_id"] in reserved:      # pool loan: the reserved row becomes the hand-over record
                conn.execute("""UPDATE booking_units SET status = 'out', out_at = ?, out_check = ?, pre_photo = ?, user_label = ?, class_name = ?
                                WHERE id = ?""", (ts, json.dumps(check), u["_photo"], u.get("user_label") or b["requester_name"],
                                                  u.get("class_name", ""), reserved[u["asset_id"]]))
                continue
            conn.execute("""INSERT INTO booking_units (id, booking_id, asset_id, user_label, student_name, student_no, class_name,
                status, out_at, out_check, pre_photo) VALUES (?,?,?,?,?,?,?,'out',?,?,?)""",
                         (new_id(), booking_id, u["asset_id"], u.get("user_label") or b["requester_name"], u.get("student_name", ""),
                          u.get("student_no", ""), u.get("class_name", ""), ts, json.dumps(check), u["_photo"]))
        if b["kind"] == "pool":            # reserved units that were not handed over are released
            conn.execute("DELETE FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (booking_id,))
        conn.execute("UPDATE bookings SET status = 'in_use', updated_at = ? WHERE id = ?", (ts, booking_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone())


def check_in(conn, *, booking_id: str, units: list, now: datetime, by_id: str, by_name: str, group_photo: str = "") -> dict:
    """Take the asset(s) back. Each unit: {asset_id, physical, function, accessories, photo, result, note}.
    result: ok | changed (small change, asset stays usable) | damaged (-> In Repair) | lost (-> Lost).
    Anything but ok needs a description, opens a Fault and marks the booking 'problem'. Units not listed stay out
    (the booking stays in use). Returns {"booking": row, "faults": [fault ids], "still_out": n}."""
    import json
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    faults = []
    try:
        b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not b:
            raise BookingError("Pengajuan tidak ditemukan.", "missing")
        if b["status"] not in ("in_use", "overdue"):
            raise BookingError("Pengajuan ini tidak sedang dipinjam.", "state")
        if not units:
            raise BookingError("Pilih unit yang dikembalikan.", "units")
        rows = {r["asset_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM booking_units WHERE booking_id = ? AND status = 'out'", (booking_id,))}
        for u in units:
            if u.get("asset_id") not in rows:
                raise BookingError("Unit tidak tercatat keluar pada pengajuan ini.", "units")
            result = u.get("result") or "ok"
            if result not in RETURN_RESULTS:
                raise BookingError("Hasil pemeriksaan tidak valid.", "result")
            if u.get("physical") not in PHYSICAL or u.get("function") not in FUNCTION:
                raise BookingError("Kondisi fisik dan fungsi wajib diisi.", "condition")
            missing = _check_accessories(conn, u["asset_id"], u.get("accessories")) if result != "lost" else []
            if result == "ok" and (missing or u["physical"] != "baik" or u["function"] != "normal"):
                raise BookingError("Ada perubahan kondisi atau kelengkapan kurang: ubah hasil pemeriksaan dan jelaskan.", "result")
            if result != "ok" and not (u.get("note") or "").strip():
                raise BookingError("Keterangan kerusakan/kehilangan wajib diisi bila ada perubahan kondisi.", "note")
            photo = u.get("photo") or group_photo
            if result != "lost" and not _photo_ok(conn, photo):
                raise BookingError("Foto sesudah wajib diunggah.", "photo")
            u["_photo"], u["_missing"] = photo or "", missing
        ts = now.strftime(FMT)
        for u in units:
            result, aid = u.get("result") or "ok", u["asset_id"]
            check = {"physical": u["physical"], "function": u["function"], "accessories": u.get("accessories") or [],
                     "missing": u["_missing"], "note": (u.get("note") or "").strip(), "received_by": by_name, "result": result}
            status = {"ok": "returned", "changed": "returned", "damaged": "damaged", "lost": "lost"}[result]
            fault_id = None
            if result != "ok":
                a = conn.execute("SELECT name, asset_tag FROM assets WHERE id = ?", (aid,)).fetchone()
                label = {"changed": "Perubahan kondisi", "damaged": "Rusak", "lost": "Hilang"}[result]
                fault_id = new_id()
                conn.execute("""INSERT INTO faults (id, asset_id, title, description, severity, status, reported_by, reported_by_name, created_at)
                                VALUES (?,?,?,?,?,'open',?,?,?)""",
                             (fault_id, aid, f"{label} setelah dipinjam ({b['number']})",
                              f"Peminjam: {rows[aid]['user_label']}. {check['note']}".strip(),
                              "low" if result == "changed" else "high", by_id, by_name, ts))
                faults.append(fault_id)
                if result == "damaged":
                    conn.execute("UPDATE assets SET status = 'in_repair', updated_at = ? WHERE id = ?", (ts, aid))
                elif result == "lost":
                    conn.execute("UPDATE assets SET status = 'lost', updated_at = ? WHERE id = ?", (ts, aid))
            conn.execute("""UPDATE booking_units SET status = ?, in_at = ?, in_check = ?, post_photo = ?, condition_changed = ?, fault_id = ?
                            WHERE id = ?""", (status, ts, json.dumps(check), u["_photo"], int(result != "ok"), fault_id, rows[aid]["id"]))
        still_out = conn.execute("SELECT COUNT(*) FROM booking_units WHERE booking_id = ? AND status = 'out'", (booking_id,)).fetchone()[0]
        if not still_out:
            problem = conn.execute("SELECT 1 FROM booking_units WHERE booking_id = ? AND condition_changed = 1", (booking_id,)).fetchone()
            conn.execute("UPDATE bookings SET status = ?, updated_at = ? WHERE id = ?", ("problem" if problem else "completed", ts, booking_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"booking": dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()),
            "faults": faults, "still_out": still_out}


# ---- Fixed schedules ----
def validate_schedule(conn, data: dict, exclude_id: Optional[str] = None, now: Optional[datetime] = None) -> list:
    """Problems with a fixed schedule: bad periods / dates, too many units, another fixed class on the same cart at the
    same time, or already-approved bookings in the way. Returns a list of Indonesian messages (empty = fine)."""
    problems = []
    r = conn.execute("SELECT capacity, campus, active, kind, unit FROM resources WHERE id = ?", (data["resource_id"],)).fetchone()
    if not r or not r["active"]:
        return ["Cart/lab tidak ditemukan atau tidak aktif."]
    # iPads belong to the unit that owns the cart (SD): another unit's class only gets them through a special loan request
    g = re.match(r"\s*(\d+)", data.get("class_name") or "")
    class_unit = ("SD" if 1 <= int(g.group(1)) <= 6 else "SMP" if 7 <= int(g.group(1)) <= 9 else "") if g else ""
    if r["kind"] == "ipad_cart" and r["unit"] and class_unit and class_unit != r["unit"]:
        return [f"iPad hanya untuk jadwal tetap unit {r['unit']}. Kelas {data['class_name'].strip()} ({class_unit}) memakai iPad lewat pengajuan peminjaman khusus."]
    if r["campus"] != data["campus"]:
        problems.append("Cart/lab bukan milik kampus ini.")
    if not 0 <= int(data["weekday"]) <= 6:
        problems.append("Hari tidak valid.")
    if int(data["period_from"]) > int(data["period_to"]):
        problems.append("Jam mulai harus sebelum atau sama dengan jam selesai.")
    try:
        period_times(conn, data["campus"], int(data["period_from"]), int(data["period_to"]), resource_unit(conn, data["resource_id"]))
    except BookingError as e:
        problems.append(e.message)
    try:
        v_from, v_to = date.fromisoformat(data["valid_from"]), date.fromisoformat(data["valid_to"])
        if v_to < v_from:
            problems.append("Tanggal berakhir harus setelah tanggal mulai.")
    except ValueError:
        return problems + ["Tanggal berlaku tidak valid."]
    capacity = resource_capacity(conn, data["resource_id"])
    if int(data["units"]) < 1 or int(data["units"]) > capacity:
        problems.append(f"Jumlah unit harus 1 sampai {capacity}.")
    if problems:
        return problems
    # another fixed class on the same cart, same weekday, overlapping periods and validity
    for o in conn.execute("""SELECT * FROM fixed_schedules WHERE resource_id = ? AND status = 'active' AND weekday = ? AND id != ?
                             AND valid_from <= ? AND valid_to >= ? AND period_from <= ? AND period_to >= ?""",
                          (data["resource_id"], data["weekday"], exclude_id or "", data["valid_to"], data["valid_from"],
                           data["period_to"], data["period_from"])):
        if int(data["units"]) + o["units"] > capacity:
            problems.append(f"Bentrok dengan jadwal tetap kelas {o['class_name']} ({o['teacher_name']}) pada jam yang sama.")
    # approved bookings that would be displaced: ICT must settle those first
    today = (now or datetime.now()).date()
    t_from, t_to = period_times(conn, data["campus"], int(data["period_from"]), int(data["period_to"]), resource_unit(conn, data["resource_id"]))
    d = max(v_from, today)
    while d <= v_to:
        if d.weekday() == int(data["weekday"]):
            start, end = parse_dt(f"{d.isoformat()}T{t_from}"), parse_dt(f"{d.isoformat()}T{t_to}")
            for b in _booking_rows(conn, resource_id=data["resource_id"], asset_id=None, statuses=COMMITTED_STATUSES,
                                   start=start, end=end, exclude_booking_id=None):
                problems.append(f"Sudah ada pengajuan disetujui {b['number']} ({b['requester_name']}) pada {b['start_at'].replace('T', ' ')}.")
        d += timedelta(days=1)
    return problems[:10]


def materialize_fixed(conn, *, schedule_id: str, day: date, by_id: str, by_name: str, now: datetime) -> dict:
    """Turn one session of a fixed schedule into a booking so it can be handed over and returned like any loan.
    Idempotent: the same session always returns the same booking."""
    s = conn.execute("SELECT * FROM fixed_schedules WHERE id = ?", (schedule_id,)).fetchone()
    if not s:
        raise BookingError("Jadwal tidak ditemukan.", "missing")
    occ = [o for o in fixed_occurrences(conn, s["resource_id"], day, day) if o["schedule_id"] == schedule_id]
    if not occ:
        raise BookingError("Tidak ada sesi jadwal ini pada tanggal tersebut (libur, dibatalkan, atau di luar masa berlaku).", "no_session")
    o = occ[0]
    if o["booking_id"]:
        return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (o["booking_id"],)).fetchone())
    res = conn.execute("SELECT category FROM resources WHERE id = ?", (s["resource_id"],)).fetchone()
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        bid, ts = new_id(), now.strftime(FMT)
        conn.execute("""INSERT INTO bookings (id, number, campus, kind, resource_id, category, requester_id, requester_name, start_at, end_at,
            units_requested, units_approved, class_name, subject, purpose, status, decided_by, decided_by_name, decided_at, terms_accepted,
            schedule_id, created_at, updated_at) VALUES (?,?,?,'fixed',?,?,?,?,?,?,?,?,?,?,?,'approved',?,?,?,1,?,?,?)""",
                     (bid, next_booking_number(conn, now.year), s["campus"], s["resource_id"], res["category"],
                      s["teacher_user_id"] or by_id, s["teacher_name"] or by_name, o["start"].strftime(FMT), o["end"].strftime(FMT),
                      s["units"], s["units"], s["class_name"], s["subject"], f"Jadwal tetap {s['class_name']} {s['subject']}".strip(),
                      by_id, by_name, ts, s["id"], ts, ts))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone())


def resource_units(conn, resource_id: str, active_only: bool = True) -> list:
    sql = """SELECT a.id, a.name, a.asset_tag, a.status, a.serial_number FROM asset_loan_settings s JOIN assets a ON a.id = s.asset_id
             WHERE s.resource_id = ?"""
    if active_only:
        sql += " AND a.status = 'active' AND s.borrowable = 1"
    return [dict(r) for r in conn.execute(sql + " ORDER BY a.asset_tag", (resource_id,))]


def bulk_units(conn, booking: dict, exclude: Optional[list] = None, only_unreturned: bool = False) -> list:
    """Unit rows for "all units of the cart" flows. Check-out: every active unit of the resource (minus `exclude`),
    all marked fine, with the semester's student pairing filled in. Check-in: every unit currently out."""
    exclude = set(exclude or [])
    if only_unreturned:
        ids = [r["asset_id"] for r in conn.execute("SELECT asset_id FROM booking_units WHERE booking_id = ? AND status = 'out'", (booking["id"],))]
    elif booking.get("kind") == "pool":      # the units ICT reserved when approving
        ids = [r["asset_id"] for r in conn.execute("SELECT asset_id FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (booking["id"],))]
    else:
        ids = [u["id"] for u in resource_units(conn, booking["resource_id"])]
    out = []
    for aid in ids:
        if aid in exclude:
            continue
        pair = conn.execute("""SELECT * FROM unit_assignments WHERE resource_id = ? AND asset_id = ?
                               ORDER BY academic_year DESC, semester DESC LIMIT 1""", (booking["resource_id"], aid)).fetchone()
        out.append({"asset_id": aid, "physical": "baik", "function": "normal", "note": "", "result": "ok",
                    "accessories": [{"name": n, "ok": True} for n in accessory_names(conn, aid)],
                    "student_name": pair["student_name"] if pair else "", "student_no": pair["student_no"] if pair else "",
                    "class_name": (pair["class_name"] if pair else "") or booking.get("class_name", ""),
                    "user_label": (f"{pair['student_name']} (No. {pair['student_no']})".strip() if pair and pair["student_name"] else booking["requester_name"])})
    return out


# ---- Weekly calendar ----
def week_cells(conn, res: dict, monday: date, periods: list, holidays: dict) -> list:
    """For each day of the week and each lesson period: capacity, units used / free, and what occupies the slot.
    Fixed sessions marked "Libur" are listed too (kind 'libur') but hold nothing."""
    capacity = resource_capacity(conn, res["id"])
    week_start = datetime.combine(monday, datetime.min.time())
    week_end = week_start + timedelta(days=7)
    committed = _booking_rows(conn, resource_id=res["id"], asset_id=None, statuses=COMMITTED_STATUSES, start=week_start, end=week_end,
                              exclude_booking_id=None)
    pending = _booking_rows(conn, resource_id=res["id"], asset_id=None, statuses=PENDING_STATUSES, start=week_start, end=week_end,
                            exclude_booking_id=None)
    fixed = [o for o in fixed_occurrences(conn, res["id"], monday, monday + timedelta(days=6)) if not o["materialized"]]
    libur = []
    for s in conn.execute("SELECT * FROM fixed_schedules WHERE resource_id = ? AND status = 'active'", (res["id"],)).fetchall():
        for e in conn.execute("SELECT date, note FROM schedule_exceptions WHERE schedule_id = ? AND date >= ? AND date <= ?",
                              (s["id"], monday.isoformat(), (monday + timedelta(days=6)).isoformat())):
            try:
                t_from, t_to = period_times(conn, s["campus"], s["period_from"], s["period_to"], resource_unit(conn, s["resource_id"]))
            except BookingError:
                continue
            libur.append({"schedule_id": s["id"], "exception": e["date"], "start": parse_dt(f"{e['date']}T{t_from}"), "end": parse_dt(f"{e['date']}T{t_to}"),
                          "class_name": s["class_name"], "note": e["note"]})
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        cells = []
        for p in periods:
            start, end = parse_dt(f"{d.isoformat()}T{p['start_time']}"), parse_dt(f"{d.isoformat()}T{p['end_time']}")
            slots, items = [], []
            for b in committed:
                bs, be_ = parse_dt(b["start_at"]), parse_dt(b["end_at"])
                if overlaps(bs, be_, start, end):
                    n = b["units_approved"] or b["units_requested"]
                    slots.append((bs, be_, n))
                    items.append({"type": "fixed" if b["kind"] == "fixed" else "booking", "booking_id": b["id"], "number": b["number"], "units": n,
                                  "label": (f"{b['class_name']} · {b['requester_name']}" if b["kind"] == "fixed" else b["requester_name"]),
                                  "status": b["status"], "schedule_id": b["schedule_id"]})
            for o in fixed:
                if overlaps(o["start"], o["end"], start, end):
                    slots.append((o["start"], o["end"], o["units"]))
                    items.append({"type": "fixed", "schedule_id": o["schedule_id"], "units": o["units"], "date": d.isoformat(),
                                  "label": f"{o['class_name']} · {o['teacher_name']}" + (f" ({o['subject']})" if o.get("subject") else ""), "status": "scheduled"})
            for x in libur:
                if overlaps(x["start"], x["end"], start, end):
                    items.append({"type": "libur", "schedule_id": x["schedule_id"], "units": 0, "label": f"{x['class_name']} · Libur", "date": x["exception"]})
            waiting = [{"type": "pending", "booking_id": b["id"], "number": b["number"], "units": b["units_requested"], "label": b["requester_name"]}
                       for b in pending if overlaps(parse_dt(b["start_at"]), parse_dt(b["end_at"]), start, end)]
            used = _peak_usage(slots, start, end)
            cells.append({"period_no": p["period_no"], "start": start.strftime(FMT), "end": end.strftime(FMT), "used": used,
                          "free": max(capacity - used, 0), "capacity": capacity, "items": items, "pending": waiting})
        days.append({"date": d.isoformat(), "weekday": i, "holiday": holidays.get(d.isoformat()), "cells": cells})
    return days


# ---- Overdue + reminders ----
def newly_overdue(conn, now: datetime) -> list:
    """Move loans past their end time (still out) to 'overdue' and return the rows that changed."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM bookings WHERE status = 'in_use' AND end_at < ?", (now.strftime(FMT),))]
    if rows:
        conn.execute("UPDATE bookings SET status = 'overdue', updated_at = ? WHERE status = 'in_use' AND end_at < ?",
                     (now.strftime(FMT), now.strftime(FMT)))
        conn.commit()
    return rows


def reminder_targets(conn, now: datetime) -> dict:
    """What to remind about today: pick-ups tomorrow (H-1), returns due today, and loans already overdue."""
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    today = now.date().isoformat()
    return {
        "pickup_tomorrow": [dict(r) for r in conn.execute(
            "SELECT * FROM bookings WHERE status IN ('approved','partially_approved') AND kind != 'fixed' AND substr(start_at,1,10) = ?", (tomorrow,))],
        "due_today": [dict(r) for r in conn.execute(
            "SELECT * FROM bookings WHERE status = 'in_use' AND substr(end_at,1,10) = ?", (today,))],
        "overdue": [dict(r) for r in conn.execute("SELECT * FROM bookings WHERE status = 'overdue'")],
    }


# ---- Scan resolution ----
def resolve_scan(conn, code: str, now: datetime) -> Optional[dict]:
    """Find the asset behind a scanned QR / typed code and what can be done with it right now."""
    c = (code or "").strip()
    if "=" in c:                       # QR holds a link like https://host/scan?code=YPJ-KAM-005
        c = c.rsplit("=", 1)[1]
    c = c.split("/")[-1].strip()
    a = conn.execute("SELECT * FROM assets WHERE LOWER(asset_tag) = LOWER(?) OR (asset_code != '' AND LOWER(asset_code) = LOWER(?)) "
                     "ORDER BY LOWER(asset_tag) = LOWER(?) DESC LIMIT 1", (c, c, c)).fetchone()
    if not a:
        return None
    a = dict(a)
    out = conn.execute("""SELECT u.id AS unit_id, u.out_at, u.user_label, b.id AS booking_id, b.number, b.status, b.end_at, b.requester_name
                          FROM booking_units u JOIN bookings b ON b.id = u.booking_id
                          WHERE u.asset_id = ? AND u.status = 'out' LIMIT 1""", (a["id"],)).fetchone()
    s = conn.execute("SELECT borrowable, resource_id FROM asset_loan_settings WHERE asset_id = ?", (a["id"],)).fetchone()
    today = now.date().isoformat()
    pickup = conn.execute("""SELECT id, number, requester_name, start_at, end_at FROM bookings
                             WHERE status IN ('approved','partially_approved') AND substr(start_at,1,10) <= ? AND substr(end_at,1,10) >= ?
                             AND (asset_id = ? OR (resource_id IS NOT NULL AND resource_id = ?)
                                  OR id IN (SELECT booking_id FROM booking_units WHERE asset_id = ? AND status = 'reserved'))
                             ORDER BY start_at LIMIT 1""",
                          (today, today, a["id"], s["resource_id"] if s else None, a["id"])).fetchone()
    return {"asset": {k: a[k] for k in ("id", "name", "asset_tag", "category", "campus", "location", "brand", "model", "serial_number", "status")},
            "borrowable": bool(s and s["borrowable"]), "resource_id": s["resource_id"] if s else None,
            "out": dict(out) if out else None, "pickup": dict(pickup) if pickup else None,
            "state": ("repair" if a["status"] == "in_repair" else "lost" if a["status"] == "lost" else "on_loan" if out else "available")}
