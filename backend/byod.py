"""Bring Your Own Device (BYOD) approval for students: schema + pure rules.

Flow: teacher opens a project with its students -> each parent signs through a one-time link (no account) ->
the supervising teacher signs -> the campus ICT Admin approves and grants school WiFi to the listed devices.
Only laptops, iPads and tablets are accepted. Dates are campus-local (WIT).
"""
import hashlib
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

TERMS_VERSION = "2026.1"            # bump when the BYOD terms text changes
MAX_DAYS = 92                       # longest period of one approval (about 3 months)
MAX_EXTEND_DAYS = 92                # one extension, at most this many days beyond the current end
MAX_DEVICES = 2                     # devices per student
DEVICE_KINDS = ("laptop", "ipad", "tablet")
TOKEN_DAYS = 7
OPEN_STATUSES = ("waiting_parent", "waiting_teacher", "waiting_ict", "approved")   # statuses that still hold a MAC address

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS byod_projects (
    id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    hour_from TEXT NOT NULL DEFAULT '07:30',
    hour_to TEXT NOT NULL DEFAULT '15:30',
    teacher_id TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS byod_requests (
    id TEXT PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,                    -- BYOD-2026-0001
    project_id TEXT NOT NULL,
    campus TEXT NOT NULL,
    teacher_id TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    student_name TEXT NOT NULL,
    student_class TEXT NOT NULL DEFAULT '',
    student_no TEXT NOT NULL DEFAULT '',
    parent_name TEXT NOT NULL DEFAULT '',
    parent_relation TEXT NOT NULL DEFAULT '',
    parent_email TEXT NOT NULL DEFAULT '',
    parent_phone TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'waiting_parent',  -- waiting_parent | waiting_teacher | waiting_ict | approved | rejected | cancelled | revoked
    token_hash TEXT NOT NULL DEFAULT '',            -- sha256 of the one-time link token; cleared once signed
    token_expires_at TEXT NOT NULL DEFAULT '',
    terms_version TEXT NOT NULL DEFAULT '',
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    pending_end_date TEXT,                          -- requested extension waiting for ICT
    extended_count INTEGER NOT NULL DEFAULT 0,
    parent_signed_at TEXT, parent_signed_name TEXT NOT NULL DEFAULT '', parent_signature TEXT NOT NULL DEFAULT '',
    parent_ip TEXT NOT NULL DEFAULT '', parent_ua TEXT NOT NULL DEFAULT '', parent_text_hash TEXT NOT NULL DEFAULT '', parent_lang TEXT NOT NULL DEFAULT '',
    teacher_signed_at TEXT, teacher_signed_name TEXT NOT NULL DEFAULT '', teacher_signature TEXT NOT NULL DEFAULT '',
    teacher_ip TEXT NOT NULL DEFAULT '', teacher_ua TEXT NOT NULL DEFAULT '',
    ict_by TEXT, ict_by_name TEXT NOT NULL DEFAULT '', ict_at TEXT, ict_note TEXT NOT NULL DEFAULT '',
    end_reason TEXT NOT NULL DEFAULT '',            -- why it was cancelled / revoked
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_byod_req_token ON byod_requests(token_hash);
CREATE INDEX IF NOT EXISTS idx_byod_req_teacher ON byod_requests(teacher_id, status);
CREATE INDEX IF NOT EXISTS idx_byod_req_project ON byod_requests(project_id);

CREATE TABLE IF NOT EXISTS byod_devices (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    kind TEXT NOT NULL,                             -- laptop | ipad | tablet
    brand TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT '',
    os_version TEXT NOT NULL DEFAULT '',
    mac TEXT NOT NULL,                              -- AA:BB:CC:DD:EE:FF
    serial TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_byod_dev_req ON byod_devices(request_id);
CREATE INDEX IF NOT EXISTS idx_byod_dev_mac ON byod_devices(mac);

-- Append-only trail of who did what (signatures, decisions, resends)
CREATE TABLE IF NOT EXISTS byod_events (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_byod_ev_req ON byod_events(request_id, at);
"""


class ByodError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def init_schema(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def new_token() -> tuple:
    """(token for the link, hash to store, expiry)."""
    tok = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)).isoformat()
    return tok, hash_token(tok), exp


def hash_token(tok: str) -> str:
    return hashlib.sha256((tok or "").encode()).hexdigest()


_MAC_RE = re.compile(r"^[0-9A-F]{12}$")


def normalize_mac(value: str) -> str:
    raw = re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()
    if not _MAC_RE.match(raw):
        raise ByodError("MAC address tidak valid (contoh: A1:B2:C3:D4:E5:F6).", "mac")
    if raw == "000000000000" or raw == "FFFFFFFFFFFF":
        raise ByodError("MAC address tidak valid.", "mac")
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def parse_date(value: str) -> date:
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ByodError("Tanggal tidak valid (YYYY-MM-DD).", "date")


def check_period(start: str, end: str, today: date) -> None:
    s, e = parse_date(start), parse_date(end)
    if s < today:
        raise ByodError("Tanggal mulai tidak boleh sudah lewat.", "date")
    if e < s:
        raise ByodError("Tanggal selesai harus sama atau setelah tanggal mulai.", "date")
    if (e - s).days + 1 > MAX_DAYS:
        raise ByodError(f"Rentang waktu maksimal {MAX_DAYS} hari (sekitar 3 bulan).", "date")


def check_hours(hour_from: str, hour_to: str) -> None:
    ok = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
    if not (ok.match(hour_from or "") and ok.match(hour_to or "")) or hour_from >= hour_to:
        raise ByodError("Jam yang diizinkan tidak valid (HH:MM, jam mulai sebelum jam selesai).", "hours")


def validate_devices(devices: list) -> list:
    """Clean list of {kind, brand, model, os, os_version, mac, serial}; only laptops, iPads and tablets."""
    if not devices:
        raise ByodError("Isi minimal satu perangkat.", "devices")
    if len(devices) > MAX_DEVICES:
        raise ByodError(f"Maksimal {MAX_DEVICES} perangkat per siswa.", "devices")
    out, macs = [], set()
    for d in devices:
        kind = (d.get("kind") or "").strip().lower()
        if kind not in DEVICE_KINDS:
            raise ByodError("Hanya Laptop, iPad, atau Tablet yang diizinkan.", "kind")
        # optional: parents often cannot find it; ICT can fill it in when approving
        mac = normalize_mac(d.get("mac")) if (d.get("mac") or "").strip() else ""
        if mac:
            if mac in macs:
                raise ByodError("MAC address perangkat terduplikasi.", "mac")
            macs.add(mac)
        brand, model = (d.get("brand") or "").strip(), (d.get("model") or "").strip()
        if not brand or not model:
            raise ByodError("Merek dan model perangkat wajib diisi.", "device")
        out.append({"kind": kind, "brand": brand[:60], "model": model[:80], "os": (d.get("os") or "").strip()[:40],
                    "os_version": (d.get("os_version") or "").strip()[:40], "mac": mac, "serial": (d.get("serial") or "").strip()[:80]})
    return out


def mac_in_use(conn, macs: list, exclude_request_id: Optional[str] = None, today: Optional[date] = None) -> Optional[str]:
    """First MAC already registered on another open request that has not ended."""
    today = today or date.today()
    marks = ",".join("?" * len(OPEN_STATUSES))
    for mac in filter(None, macs):
        row = conn.execute(f"""SELECT r.number FROM byod_devices d JOIN byod_requests r ON r.id = d.request_id
                               WHERE d.mac = ? AND r.status IN ({marks}) AND r.valid_to >= ? AND r.id != ? LIMIT 1""",
                           (mac, *OPEN_STATUSES, today.isoformat(), exclude_request_id or "")).fetchone()
        if row:
            return mac
    return None


def effective_status(row: dict, today: date) -> str:
    """'approved' splits by date into scheduled / active / expired; the other statuses are shown as they are."""
    if row["status"] != "approved":
        return row["status"]
    if today < parse_date(row["valid_from"]):
        return "scheduled"
    if today > parse_date(row["valid_to"]):
        return "expired"
    return "active"


def next_number(conn, year: int) -> str:
    prefix = f"BYOD-{year}-"
    last = conn.execute("SELECT number FROM byod_requests WHERE number LIKE ? ORDER BY number DESC LIMIT 1", (prefix + "%",)).fetchone()
    n = int(last["number"].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def add_event(conn, request_id: str, actor: str, action: str, detail: str = "", ip: str = "") -> None:
    conn.execute("INSERT INTO byod_events (id, request_id, at, actor, action, detail, ip) VALUES (?,?,?,?,?,?,?)",
                 (secrets.token_hex(16), request_id, datetime.now(timezone.utc).isoformat(), actor, action, detail, ip))
