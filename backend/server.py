from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import hashlib
import html as html_mod
import secrets
import re
import uuid
import sqlite3
import json
import logging
import io
import csv
import time
import threading
import urllib.request
import smtplib
import socket
from email.utils import formataddr
import bcrypt
import jwt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, UploadFile, File, Query, Form
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from apscheduler.schedulers.background import BackgroundScheduler


# ---- Config ----
# In production Railway sets DATA_DIR to a mounted volume path
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / os.environ.get("DB_FILE", "schoolassets.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Email config (set in Railway environment variables)
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = (os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or "").replace(" ", "")
SMTP_HOST     = os.environ.get("SMTP_HOST") or ("smtp.gmail.com" if SMTP_USER else "")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_FROM     = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "YPJ Assets Management")
# Resend (HTTPS API) — preferred on Railway, which blocks outbound SMTP ports
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM_DOMAIN = os.environ.get("MAIL_FROM_DOMAIN", "ypj.sch.id")
_RAILWAY_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
APP_URL       = (os.environ.get("APP_URL")
                 or (f"https://{_RAILWAY_DOMAIN}" if _RAILWAY_DOMAIN else "http://localhost:8001")).rstrip("/")

# Loan notification recipients (set in Railway environment variables)
# General inbox that receives new-request and return-complete alerts
LOAN_NOTIFY_EMAIL  = os.environ.get("LOAN_NOTIFY_EMAIL", "")
# Campus heads — keyed by campus slug (KK = Kuala Kencana, TB = Tembagapura)
HEAD_KK_EMAIL       = os.environ.get("HEAD_KK_EMAIL", "")        # Head of Campus – YPJ Kuala Kencana
HEAD_TB_EMAIL       = os.environ.get("HEAD_TB_EMAIL", "")        # Head of Campus – YPJ Tembagapura
HEAD_ADMIN_KK_EMAIL = os.environ.get("HEAD_ADMIN_KK_EMAIL", "")  # Head of Administration – YPJ Kuala Kencana
HEAD_ADMIN_TB_EMAIL = os.environ.get("HEAD_ADMIN_TB_EMAIL", "")  # Head of Administration – YPJ Tembagapura

# Map campus name → (head-of-campus email, head-of-admin email)
CAMPUS_HEAD_EMAILS: dict = {
    "YPJ Kuala Kencana": [HEAD_KK_EMAIL, HEAD_ADMIN_KK_EMAIL],
    "YPJ Tembagapura":   [HEAD_TB_EMAIL, HEAD_ADMIN_TB_EMAIL],
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="School Assets Management API")
api = APIRouter(prefix="/api")


# ---- Database ----
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---- Extended asset register fields (all optional; added via safe migration) ----
# (column, sqlite type, default)
EXTRA_ASSET_FIELDS = [
    # Identity
    ("asset_code", "TEXT", ""), ("item_type", "TEXT", ""), ("brand", "TEXT", ""), ("model", "TEXT", ""),
    # Location
    ("unit", "TEXT", ""), ("building", "TEXT", ""),
    # Custodian
    ("department", "TEXT", ""), ("user_type", "TEXT", ""),
    # Acquisition
    ("acquisition_type", "TEXT", ""), ("po_number", "TEXT", ""), ("funding_source", "TEXT", ""),
    # Condition & inspection
    ("asset_condition", "TEXT", ""), ("condition_notes", "TEXT", ""),
    ("last_inspection_date", "TEXT", ""), ("next_inspection_date", "TEXT", ""),
    # Maintenance
    ("maintenance_required", "INTEGER", 0), ("last_maintenance_date", "TEXT", ""),
    ("next_maintenance_date", "TEXT", ""), ("maintenance_provider", "TEXT", ""),
    ("maintenance_cost", "REAL", 0),
    # Warranty
    ("warranty_start_date", "TEXT", ""), ("warranty_provider", "TEXT", ""),
    # Financial
    ("residual_value", "REAL", 0),
]
EXTRA_ASSET_KEYS = [f[0] for f in EXTRA_ASSET_FIELDS]
EXTRA_DATE_KEYS = [k for k, _, _ in EXTRA_ASSET_FIELDS if k.endswith("_date")]


MONEY_COLUMNS = ("purchase_price", "maintenance_cost", "residual_value")


def migrate_money_to_idr(conn):
    """One-time migration: amounts used to be stored in USD, they are now stored in whole Rupiah.

    - Runs once; afterwards app_meta.money_currency = 'IDR' and this is a no-op.
    - Empty database: nothing to convert, just sets the flag.
    - Rate: MIGRATION_USD_IDR_RATE env var if set, otherwise the live rate (falls back to
      USD_IDR_RATE / built-in estimate when the live source is unreachable). It is recorded in app_meta.
    - A consistent copy of the database is written next to it first (<db>.pre-idr-<time>.bak).
    - Conversion + flag happen in one transaction; on any error nothing is changed and startup fails
      (the previous deployment keeps running).
    """
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'money_currency'").fetchone():
        return
    n_assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    if n_assets == 0:
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('money_currency', 'IDR')")
        conn.commit()
        return

    override = (os.environ.get("MIGRATION_USD_IDR_RATE") or "").strip()
    if override:
        rate, source = float(override), "env"
    else:
        info = get_usd_idr_rate()
        rate, source = info["rate"], info["source"]
    if not (5000 < rate < 50000):
        raise RuntimeError(f"Refusing to migrate amounts to IDR with implausible rate {rate}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = DB_PATH.with_name(f"{DB_PATH.name}.pre-idr-{stamp}.bak")
    dst = sqlite3.connect(str(backup_path))
    try:
        conn.backup(dst)
    finally:
        dst.close()

    try:
        conn.execute(
            "UPDATE assets SET purchase_price = ROUND(COALESCE(purchase_price, 0) * ?), "
            "maintenance_cost = ROUND(COALESCE(maintenance_cost, 0) * ?), "
            "residual_value = ROUND(COALESCE(residual_value, 0) * ?)",
            (rate, rate, rate),
        )
        for k, v in (("money_currency", "IDR"), ("money_migrated_at", now_iso()),
                     ("money_migration_rate", str(rate)), ("money_migration_rate_source", source),
                     ("money_migration_backup", backup_path.name)):
            conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    logger.warning("Converted %d asset(s) from USD to IDR at %.2f (%s). Backup: %s",
                   n_assets, rate, source, backup_path.name)


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'staff',
        department TEXT,
        campus TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS assets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        asset_tag TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT DEFAULT '',
        campus TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        purchase_price REAL NOT NULL,
        purchase_date TEXT NOT NULL,
        useful_life_years INTEGER NOT NULL DEFAULT 5,
        warranty_end_date TEXT,
        serial_number TEXT DEFAULT '',
        supplier TEXT DEFAULT '',
        assigned_to_user_id TEXT,
        assigned_to_name TEXT,
        photo_path TEXT,
        documents TEXT DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT
    );

    CREATE TABLE IF NOT EXISTS ownership_logs (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        from_name TEXT,
        from_user_id TEXT,
        to_name TEXT,
        to_user_id TEXT,
        note TEXT DEFAULT '',
        by TEXT NOT NULL,
        by_name TEXT NOT NULL,
        at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS faults (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'open',
        reported_by TEXT NOT NULL,
        reported_by_name TEXT NOT NULL,
        resolution_note TEXT,
        resolved_at TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS compliance (
        id TEXT PRIMARY KEY,
        asset_id TEXT,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT NOT NULL,
        due_date TEXT NOT NULL,
        frequency TEXT NOT NULL DEFAULT 'annual',
        status TEXT NOT NULL DEFAULT 'pending',
        completed_date TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        storage_path TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size INTEGER NOT NULL,
        uploaded_by TEXT NOT NULL,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS loan_requests (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        asset_name TEXT NOT NULL,
        asset_tag TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        requested_by_name TEXT NOT NULL,
        purpose TEXT DEFAULT '',
        start_date TEXT,
        end_date TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        reviewed_at TEXT,
        reject_reason TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS transfer_requests (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        asset_name TEXT NOT NULL,
        asset_tag TEXT NOT NULL,
        from_name TEXT,
        to_name TEXT NOT NULL,
        note TEXT DEFAULT '',
        requested_by TEXT NOT NULL,
        requested_by_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        reviewed_at TEXT,
        reject_reason TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS assignments (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_name TEXT NOT NULL,
        asset_tag TEXT NOT NULL,
        from_user_id TEXT,
        from_name TEXT,
        to_user_id TEXT NOT NULL,
        to_name TEXT NOT NULL,
        to_label TEXT,
        kind TEXT NOT NULL DEFAULT 'personal',
        source TEXT NOT NULL DEFAULT 'transfer',
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_by TEXT NOT NULL,
        created_by_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        responded_at TEXT,
        reject_reason TEXT,
        last_reminded_at TEXT,
        transfer_request_id TEXT
    );
    CREATE TABLE IF NOT EXISTS password_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_pwtok_user ON password_tokens(user_id);
    CREATE INDEX IF NOT EXISTS idx_assign_to ON assignments(to_user_id, status);
    CREATE INDEX IF NOT EXISTS idx_assign_asset ON assignments(asset_id, status);
    """)
    conn.commit()
    # Migrations for existing databases
    cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()]
    if "campus" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN campus TEXT NOT NULL DEFAULT ''")
        conn.commit()
    if "asset_type" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'School Asset'")
        conn.commit()
    user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "campus" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN campus TEXT NOT NULL DEFAULT ''")
        conn.commit()
    if "supervisor" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN supervisor TEXT DEFAULT ''")
        conn.commit()
    if "employee_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN employee_id TEXT DEFAULT ''")
        conn.commit()
    if "supervisor_name" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN supervisor_name TEXT DEFAULT ''")
        conn.commit()
    # Loan request workflow columns (deliver / return / reminder)
    loan_cols = [r[1] for r in conn.execute("PRAGMA table_info(loan_requests)").fetchall()]
    for col, defn in [
        ("pre_condition",      "TEXT DEFAULT ''"),
        ("pre_condition_note", "TEXT DEFAULT ''"),
        ("pre_image_path",     "TEXT DEFAULT ''"),
        ("post_condition",     "TEXT DEFAULT ''"),
        ("post_condition_note","TEXT DEFAULT ''"),
        ("post_image_path",    "TEXT DEFAULT ''"),
        ("delivered_at",       "TEXT"),
        ("returned_at",        "TEXT"),
    ]:
        if col not in loan_cols:
            conn.execute(f"ALTER TABLE loan_requests ADD COLUMN {col} {defn}")
    conn.commit()
    # Extended asset register columns
    asset_cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()]
    for col, sqltype, default in EXTRA_ASSET_FIELDS:
        if col not in asset_cols:
            lit = f"'{default}'" if isinstance(default, str) else str(default)
            conn.execute(f"ALTER TABLE assets ADD COLUMN {col} {sqltype} NOT NULL DEFAULT {lit}")
    conn.commit()
    # Hand-over confirmation: kind of custody + link transfer requests to a user account
    asset_cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()]
    if "assignment_kind" not in asset_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN assignment_kind TEXT NOT NULL DEFAULT 'personal'")
    tr_cols = [r[1] for r in conn.execute("PRAGMA table_info(transfer_requests)").fetchall()]
    if "to_user_id" not in tr_cols:
        conn.execute("ALTER TABLE transfer_requests ADD COLUMN to_user_id TEXT")
    conn.commit()
    backfill_assignee_user_ids(conn)
    migrate_money_to_idr(conn)
    conn.close()


def backfill_assignee_user_ids(conn):
    """One time: link existing owner names (free text) to user accounts so per-user dashboards work.
    Only unambiguous matches are linked (name or e-mail, before the first ' — '); already-recorded
    ownership is kept as accepted - no confirmation is requested for historical data."""
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'assignee_backfill_v1'").fetchone():
        return
    users = [dict(r) for r in conn.execute("SELECT id, name, email FROM users").fetchall()]
    keys: dict = {}
    for u in users:
        for k in (u["name"], u["email"]):
            k = " ".join((k or "").split()).casefold()
            if k:
                keys.setdefault(k, set()).add(u["id"])
    linked = 0
    for a in conn.execute("SELECT id, assigned_to_name FROM assets "
                          "WHERE (assigned_to_user_id IS NULL OR assigned_to_user_id = '') "
                          "AND assigned_to_name IS NOT NULL AND assigned_to_name != ''").fetchall():
        k = " ".join((a["assigned_to_name"] or "").split(" — ")[0].split()).casefold()
        if len(keys.get(k, ())) == 1:
            conn.execute("UPDATE assets SET assigned_to_user_id = ? WHERE id = ?", (next(iter(keys[k])), a["id"]))
            linked += 1
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('assignee_backfill_v1', ?)",
                 (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    if linked:
        logger.warning("Linked %d asset owner name(s) to user accounts", linked)


def row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    if "documents" in d and isinstance(d["documents"], str):
        try:
            d["documents"] = json.loads(d["documents"])
        except Exception:
            d["documents"] = []
    return d


# ---- Auth helpers ----
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "User not found")
    user = row_to_dict(row)
    user.pop("password_hash", None)
    return user


ADMIN_ROLES = ("admin", "super_admin")  # super_admin can do everything an admin can, plus manage admin accounts


async def admin_required(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(403, "Admin access required")
    return user


async def super_admin_required(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super Admin access required")
    return user


# ---- Models ----
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["super_admin", "admin", "staff"] = "staff"
    department: Optional[str] = None
    campus: Optional[str] = ""
    supervisor: Optional[str] = ""
    supervisor_name: Optional[str] = ""
    employee_id: Optional[str] = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AssetIn(BaseModel):
    name: str
    asset_tag: str
    category: str
    asset_type: Optional[str] = "School Asset"
    description: Optional[str] = ""
    campus: Optional[str] = ""
    location: str
    status: Literal["active", "in_repair", "retired", "lost"] = "active"
    purchase_price: float
    purchase_date: str
    useful_life_years: int = 5
    warranty_end_date: Optional[str] = None
    serial_number: Optional[str] = ""
    supplier: Optional[str] = ""
    assigned_to_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    photo_path: Optional[str] = None
    documents: List[dict] = []
    # Extended register fields
    asset_code: Optional[str] = ""
    item_type: Optional[str] = ""
    brand: Optional[str] = ""
    model: Optional[str] = ""
    unit: Optional[str] = ""
    building: Optional[str] = ""
    department: Optional[str] = ""
    user_type: Optional[str] = ""
    acquisition_type: Optional[str] = ""
    po_number: Optional[str] = ""
    funding_source: Optional[str] = ""
    asset_condition: Optional[str] = ""
    condition_notes: Optional[str] = ""
    last_inspection_date: Optional[str] = ""
    next_inspection_date: Optional[str] = ""
    maintenance_required: Optional[bool] = False
    last_maintenance_date: Optional[str] = ""
    next_maintenance_date: Optional[str] = ""
    maintenance_provider: Optional[str] = ""
    maintenance_cost: Optional[float] = 0
    warranty_start_date: Optional[str] = ""
    warranty_provider: Optional[str] = ""
    residual_value: Optional[float] = 0


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_tag: Optional[str] = None
    category: Optional[str] = None
    asset_type: Optional[str] = None
    description: Optional[str] = None
    campus: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[str] = None
    useful_life_years: Optional[int] = None
    warranty_end_date: Optional[str] = None
    serial_number: Optional[str] = None
    supplier: Optional[str] = None
    photo_path: Optional[str] = None
    documents: Optional[List[dict]] = None
    asset_code: Optional[str] = None
    item_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    unit: Optional[str] = None
    building: Optional[str] = None
    department: Optional[str] = None
    user_type: Optional[str] = None
    acquisition_type: Optional[str] = None
    po_number: Optional[str] = None
    funding_source: Optional[str] = None
    asset_condition: Optional[str] = None
    condition_notes: Optional[str] = None
    last_inspection_date: Optional[str] = None
    next_inspection_date: Optional[str] = None
    maintenance_required: Optional[bool] = None
    last_maintenance_date: Optional[str] = None
    next_maintenance_date: Optional[str] = None
    maintenance_provider: Optional[str] = None
    maintenance_cost: Optional[float] = None
    warranty_start_date: Optional[str] = None
    warranty_provider: Optional[str] = None
    residual_value: Optional[float] = None


class TransferIn(BaseModel):
    new_owner_user_id: Optional[str] = None
    new_owner_name: str
    note: Optional[str] = ""


class FaultIn(BaseModel):
    asset_id: str
    title: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"


class FaultUpdate(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved"]] = None
    resolution_note: Optional[str] = None


class ComplianceIn(BaseModel):
    asset_id: Optional[str] = None
    title: str
    description: Optional[str] = ""
    category: str
    due_date: str
    frequency: Literal["once", "monthly", "quarterly", "annual"] = "annual"


class ComplianceUpdate(BaseModel):
    status: Optional[Literal["pending", "completed", "overdue"]] = None
    completed_date: Optional[str] = None
    note: Optional[str] = None
    due_date: Optional[str] = None


# ---- Utility ----
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def calc_depreciation(purchase_price: float, purchase_date: str, useful_life_years: int, residual_value: float = 0) -> dict:
    try:
        pdate = datetime.fromisoformat(purchase_date.replace("Z", "+00:00"))
        if pdate.tzinfo is None:
            pdate = pdate.replace(tzinfo=timezone.utc)
    except Exception:
        return {"current_value": purchase_price, "accumulated": 0, "annual": 0, "age_years": 0}
    age = (datetime.now(timezone.utc) - pdate).days / 365.25
    residual = min(max(residual_value or 0, 0), purchase_price)
    depreciable = purchase_price - residual
    annual = depreciable / max(useful_life_years, 1)
    accumulated = min(annual * age, depreciable)
    current = max(purchase_price - accumulated, residual)
    return {
        "current_value": round(current, 2),
        "accumulated": round(accumulated, 2),
        "annual": round(annual, 2),
        "age_years": round(age, 2),
    }


# ---- Email helper ----
class _SMTP4(smtplib.SMTP):
    """SMTP over IPv4 only (Railway has no outbound IPv6 route -> Errno 101)."""
    def _get_socket(self, host, port, timeout):
        ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        return socket.create_connection((ip, port), timeout, self.source_address)


class _SMTP4_SSL(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        ip = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        sock = socket.create_connection((ip, port), timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


def email_configured() -> bool:
    return bool(RESEND_API_KEY or (SMTP_HOST and SMTP_USER and SMTP_PASSWORD))


def _send_via_resend(to_addr: str, subject: str, body_html: str, cc: list) -> None:
    import json as _json, urllib.request, urllib.error
    payload = {
        "from": formataddr((SMTP_FROM_NAME, f"noreply@{MAIL_FROM_DOMAIN}")),
        "to": [to_addr], "subject": subject, "html": body_html,
    }
    if cc:
        payload["cc"] = cc
    # Embed the logo inline (CID) so Outlook shows it without "download pictures" prompts.
    try:
        logo_url = _email_logo_url()
        if logo_url and logo_url in body_html:
            import base64
            f = next((BUILD_DIR / "static" / "media").glob("ypj-logo*.png"))
            payload["html"] = body_html.replace(logo_url, "cid:ypjlogo")
            payload["attachments"] = [{"filename": "ypj-logo.png", "content_id": "ypjlogo",
                                       "content": base64.b64encode(f.read_bytes()).decode()}]
    except Exception as exc:
        logger.warning("Inline logo skipped: %s", exc)
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=_json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "ypj-assets/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Resend API {e.code}: {e.read().decode(errors='replace')[:300]}")


def _email_logo_url() -> str:
    """Public URL of the YPJ logo bundled with the frontend build (hashed filename)."""
    try:
        f = next((BUILD_DIR / "static" / "media").glob("ypj-logo*.png"), None)
        return f"{APP_URL}/static/media/{f.name}" if f else ""
    except Exception:
        return ""


def _email_shell(body: str, eyebrow: str = "", cta_label: str = "Buka Asset Registry", cta_url: str = None) -> str:
    """Common look for all emails — matches the SchoolAssets app theme (navy, yellow action, mono labels)."""
    logo = _email_logo_url()
    url = cta_url or APP_URL
    logo_html = (f'<td style="width:44px;padding-right:12px;vertical-align:middle">'
                 f'<img src="{logo}" width="40" height="40" alt="YPJ" style="display:block;border:0"></td>') if logo else ""
    mono = "'IBM Plex Mono',Menlo,Consolas,monospace"
    eyebrow_html = (f'<div style="font-family:{mono};font-size:11px;letter-spacing:.14em;text-transform:uppercase;'
                    f'color:#64748b;margin-bottom:6px">{eyebrow}</div>') if eyebrow else ""
    return f"""
  <div style="background:#f8fafc;padding:24px 12px;font-family:'IBM Plex Sans',Segoe UI,Arial,sans-serif;color:#0f172a">
    <div style="max-width:600px;margin:0 auto;border:1px solid #e2e8f0;background:#ffffff">
      <table role="presentation" width="100%" style="background:#0f172a;border-collapse:collapse"><tr>
        <td style="padding:18px 24px"><table role="presentation" style="border-collapse:collapse"><tr>
          {logo_html}
          <td style="vertical-align:middle">
            <div style="color:#ffffff;font-size:16px;font-weight:700;line-height:1.2">Yayasan Pendidikan Jayawijaya</div>
            <div style="font-family:{mono};color:#94a3b8;font-size:10px;letter-spacing:.16em;text-transform:uppercase;margin-top:3px">Manajemen Aset Sekolah</div>
          </td></tr></table></td>
      </tr></table>
      <div style="padding:28px 24px">
        {eyebrow_html}
        {body}
        <p style="margin:28px 0 0"><a href="{url}" style="display:inline-block;background:#f2c14e;color:#0f172a;padding:11px 22px;text-decoration:none;font-size:14px;font-weight:700;border-radius:4px">{cta_label} &rarr;</a></p>
        <p style="margin:10px 0 0;font-size:12px;color:#64748b">Atau buka: <a href="{url}" style="color:#0f3ea3">{url}</a></p>
      </div>
      <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:14px 24px;font-size:12px;color:#94a3b8">
        YPJ Assets Management &mdash; Kuala Kencana Campus &middot; Pesan otomatis, mohon tidak membalas langsung.
      </div>
    </div>
  </div>"""


# ---- Email helper ----
def send_email(to_addr: str, subject: str, body_html: str, cc: list = None) -> bool:
    """Send an HTML email through Gmail SMTP (or any SMTP). Returns True on success."""
    if not email_configured():
        logger.warning("Email not configured (SMTP_USER / SMTP_PASSWORD) — skipping send to %s", to_addr)
        return False
    try:
        clean_cc = [a for a in (cc or []) if a and a != to_addr]
        if RESEND_API_KEY:
            _send_via_resend(to_addr, subject, body_html, clean_cc)
            logger.info("Email sent via Resend to %s (CC: %s) — %s", to_addr, clean_cc, subject)
            return True
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = formataddr((SMTP_FROM_NAME, SMTP_FROM or SMTP_USER))
        msg["To"]      = to_addr
        if clean_cc:
            msg["Cc"] = ", ".join(clean_cc)
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        all_recipients = [to_addr] + clean_cc
        if SMTP_PORT == 465:
            smtp = _SMTP4_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        else:
            smtp = _SMTP4(SMTP_HOST, SMTP_PORT, timeout=20)
        with smtp as s:
            s.ehlo()
            if SMTP_PORT != 465:
                s.starttls()
                s.ehlo()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM or SMTP_USER, all_recipients, msg.as_string())
        logger.info("Email sent to %s (CC: %s) — %s", to_addr, clean_cc, subject)
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False


def get_loan_cc(req: dict, conn, extra: list = None) -> list:
    """
    Build the CC list for a loan-related email.

    Includes:
      - The borrower's supervisor (stored in users.supervisor)
      - Head of campus and head of administration for the asset's campus
      - Any extra addresses (e.g. LOAN_NOTIFY_EMAIL for new-request / return alerts)
    """
    cc = list(extra or [])

    # Supervisor of the borrower
    u = conn.execute("SELECT supervisor FROM users WHERE id=?", (req["requested_by"],)).fetchone()
    if u and u["supervisor"]:
        cc.append(u["supervisor"])

    # Campus heads based on the asset's campus
    asset = conn.execute("SELECT campus FROM assets WHERE id=?", (req["asset_id"],)).fetchone()
    campus = (asset["campus"] if asset else "") or ""
    for addr in CAMPUS_HEAD_EMAILS.get(campus, []):
        if addr:
            cc.append(addr)

    # Deduplicate, preserve order, drop blanks
    seen: set = set()
    result = []
    for a in cc:
        if a and a not in seen:
            seen.add(a)
            result.append(a)
    return result


def _loan_html(req: dict, heading: str, detail_lines: list, footer: str = "") -> str:
    """Generic HTML body for loan notification emails."""
    rows = "".join(
        f"<tr><td style='padding:4px 8px;color:#64748b;'>{k}</td>"
        f"<td style='padding:4px 8px;font-weight:500;'>{v}</td></tr>"
        for k, v in detail_lines
    )
    return _email_shell(f"""
        <h2 style="margin:0 0 4px;font-size:22px;color:#0f172a;">{heading}</h2>
        <table style="border-collapse:collapse;margin:16px 0;font-size:14px;">
          {rows}
        </table>
        {footer}""")


# ---- Scheduler: return-date reminders ----
def send_return_reminders():
    """Runs daily at 08:00; emails borrowers whose return date is tomorrow, with CC chain."""
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    conn = get_conn()
    rows = conn.execute(
        """SELECT lr.*, u.email AS borrower_email
           FROM loan_requests lr
           LEFT JOIN users u ON u.id = lr.requested_by
           WHERE lr.status = 'active'
             AND substr(lr.end_date, 1, 10) = ?""",
        (tomorrow,),
    ).fetchall()
    for r in rows:
        req = dict(r)
        email = req.get("borrower_email", "")
        if not email:
            continue
        asset_name = req["asset_name"]
        subject = f'[YPJ Assets] Reminder: Please return "{asset_name}" tomorrow'
        body = _loan_html(req, "Return Reminder", [
            ("Asset",     f"{req['asset_name']} ({req['asset_tag']})"),
            ("Borrower",  req["requested_by_name"]),
            ("Return by", tomorrow),
        ], "<p>Please return the asset to the admin before the end of the day.</p>")
        cc = get_loan_cc(req, conn, extra=[LOAN_NOTIFY_EMAIL] if LOAN_NOTIFY_EMAIL else [])
        send_email(email, subject, body, cc=cc)
    conn.close()
    logger.info("Return reminders checked — %d sent", len(rows))


# ---- Due-date reminders: inspection / maintenance / warranty ----
LOCAL_TZ = timezone(timedelta(hours=7))   # same wall clock as the scheduler (Asia/Jakarta)
# Recipients: campus heads (CAMPUS_HEAD_EMAILS) + this general inbox (falls back to LOAN_NOTIFY_EMAIL)
ASSET_REMINDER_EMAIL = os.environ.get("ASSET_REMINDER_EMAIL", "") or LOAN_NOTIFY_EMAIL
REMINDER_MILESTONES = (30, 14, 7, 1, 0)   # days before the due date on which an email goes out
DUE_KINDS = (
    ("inspection",  "next_inspection_date"),
    ("maintenance", "next_maintenance_date"),
    ("warranty",    "warranty_end_date"),
)
DUE_KIND_LABELS = {"inspection": "Inspection", "maintenance": "Maintenance", "warranty": "Warranty expiry"}
DUE_KIND_LABELS_ID = {"inspection": "Inspeksi", "maintenance": "Pemeliharaan", "warranty": "Garansi berakhir"}
_MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _fmt_day_id(value) -> str:
    d = _parse_day(value)
    return f"{d.day} {_MONTHS_ID[d.month - 1]} {d.year}" if d else (value or "—")


def _parse_day(value):
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def collect_due_items(assets: list, within_days: int = 60, kinds=None, today=None) -> list:
    """Items due within `within_days` (overdue ones included, days_left < 0), soonest first.
    Retired and lost assets are ignored."""
    today = today or datetime.now(LOCAL_TZ).date()
    items = []
    for a in assets:
        if a.get("status") in ("retired", "lost"):
            continue
        for kind, col in DUE_KINDS:
            if kinds and kind not in kinds:
                continue
            d = _parse_day(a.get(col))
            if not d:
                continue
            days_left = (d - today).days
            if days_left <= within_days:
                items.append({
                    "asset_id": a["id"], "name": a["name"], "asset_tag": a["asset_tag"],
                    "campus": a.get("campus") or "", "location": a.get("location") or "",
                    "kind": kind, "due_date": d.isoformat(), "days_left": days_left,
                })
    items.sort(key=lambda i: (i["days_left"], i["name"]))
    return items


def _reminder_html(campus: str, items: list) -> str:
    import html as _h
    def when(i):
        n = i["days_left"]
        if n < 0:
            return f"<span style='color:#e11d48;'>terlambat {-n} hari</span>"
        return "<strong>hari ini</strong>" if n == 0 else f"dalam {n} hari"
    rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_h.escape(DUE_KIND_LABELS_ID[i['kind']])}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_h.escape(i['name'])}<br>"
        f"<span style='color:#64748b;font-size:12px;'>{_h.escape(i['asset_tag'])} · {_h.escape(i['location'])}</span></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_fmt_day_id(i['due_date'])}<br>"
        f"<span style='font-size:12px;'>{when(i)}</span></td>"
        f"</tr>"
        for i in items
    )
    return _email_shell(f"""
        <h2 style="margin:0 0 14px;font-size:22px;color:#0f172a;">Inspeksi &amp; pemeliharaan jatuh tempo{f' — {_h.escape(campus)}' if campus else ''}</h2>
        <div style="border-left:3px solid #f2c14e;background:#fffbeb;padding:10px 14px;font-size:13px;color:#78350f;margin-bottom:16px">
          Aset berikut memerlukan tindakan.
        </div>
        <table style="border-collapse:collapse;width:100%;font-size:14px;">
          <tr style="text-align:left;color:#64748b;font-size:11px;letter-spacing:.1em;text-transform:uppercase;border-bottom:1px solid #e2e8f0;">
            <th style="padding:8px;">Jenis</th><th style="padding:8px;">Aset</th><th style="padding:8px;">Jatuh tempo</th>
          </tr>
          {rows}
        </table>""", eyebrow="Tindakan diperlukan")


def send_asset_due_reminders(force: bool = False, today=None) -> dict:
    """Runs daily. One digest email per campus (campus heads + general inbox).

    Normal run: items exactly 30 / 14 / 7 / 1 / 0 days before the due date, plus overdue
    inspections and maintenance every Monday. Expired warranties are not nagged.
    force=True: everything due within 30 days or overdue (for manual sends / testing).
    """
    today = today or datetime.now(LOCAL_TZ).date()
    conn = get_conn()
    assets = [row_to_dict(r) for r in conn.execute("SELECT * FROM assets").fetchall()]
    conn.close()

    picked = []
    for it in collect_due_items(assets, within_days=30, today=today):
        n = it["days_left"]
        if n < 0 and it["kind"] == "warranty":
            continue
        if force or (n in REMINDER_MILESTONES) or (n < 0 and today.weekday() == 0):
            picked.append(it)

    by_campus: dict = {}
    for it in picked:
        by_campus.setdefault(it["campus"], []).append(it)

    configured = email_configured()
    sent = 0
    for campus, group in by_campus.items():
        recipients = [a for a in CAMPUS_HEAD_EMAILS.get(campus, []) if a]
        if ASSET_REMINDER_EMAIL:
            recipients.append(ASSET_REMINDER_EMAIL)
        recipients = list(dict.fromkeys(recipients))   # dedupe, keep order
        if not recipients:
            logger.warning("Asset reminders for %r skipped — no recipients configured", campus)
            continue
        overdue = sum(1 for i in group if i["days_left"] < 0)
        subject = f"[YPJ Assets] {len(group)} pengingat aset" + (f" — {campus}" if campus else "")
        if overdue:
            subject += f" ({overdue} terlambat)"
        if send_email(recipients[0], subject, _reminder_html(campus, group), cc=recipients[1:]):
            sent += 1
    logger.info("Asset due reminders: %d item(s), %d email(s)", len(picked), sent)
    return {"items": len(picked), "emails": sent, "email_configured": configured}


@api.get("/reminders/due")
async def list_due_reminders(days: int = 30, _: dict = Depends(admin_required)):
    conn = get_conn()
    assets = [row_to_dict(r) for r in conn.execute("SELECT * FROM assets").fetchall()]
    conn.close()
    return {"days": days, "items": collect_due_items(assets, within_days=days)}


@api.post("/reminders/send-now")
async def send_reminders_now(_: dict = Depends(admin_required)):
    return send_asset_due_reminders(force=True)


# ---- Exchange rate (USD -> IDR) for the Indonesian-language view ----
# Amounts are stored in USD; the UI multiplies by this rate when the language is ID.
# Live source: ExchangeRate-API open endpoint (no key, refreshed daily). Cached for 12 h;
# if it cannot be reached we keep the last good rate, else USD_IDR_RATE, else a built-in estimate.
FX_API_URL = os.environ.get("FX_API_URL", "https://open.er-api.com/v6/latest/USD")
FX_CACHE_TTL = 12 * 3600        # seconds a fetched rate is considered fresh
FX_RETRY_AFTER = 15 * 60        # seconds to wait before retrying after a failed fetch
try:
    FX_FALLBACK_RATE = float(os.environ.get("USD_IDR_RATE") or 17950)
except ValueError:
    FX_FALLBACK_RATE = 17950.0
_fx_cache = {"rate": None, "as_of": None, "fetched_at": 0.0, "last_attempt": 0.0}
_fx_lock = threading.Lock()


def _fetch_live_usd_idr() -> tuple:
    """Return (rate, as_of 'YYYY-MM-DD'). Raises on any problem."""
    req = urllib.request.Request(FX_API_URL, headers={"User-Agent": "ypj-school-assets/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("result") != "success":
        raise ValueError(f"unexpected response: {data.get('result')}")
    rate = float(data["rates"]["IDR"])
    if not (5000 < rate < 50000):                      # sanity check
        raise ValueError(f"implausible IDR rate {rate}")
    as_of = None
    try:
        as_of = datetime.strptime(data["time_last_update_utc"], "%a, %d %b %Y %H:%M:%S %z").date().isoformat()
    except Exception:
        as_of = datetime.now(timezone.utc).date().isoformat()
    return rate, as_of


def get_usd_idr_rate(now: float = None) -> dict:
    now = time.time() if now is None else now
    with _fx_lock:
        c = _fx_cache
        fresh = c["rate"] is not None and now - c["fetched_at"] < FX_CACHE_TTL
        may_retry = now - c["last_attempt"] >= FX_RETRY_AFTER
        if not fresh and may_retry:
            c["last_attempt"] = now
            try:
                c["rate"], c["as_of"] = _fetch_live_usd_idr()
                c["fetched_at"] = now
                fresh = True
            except Exception as exc:
                logger.warning("USD/IDR rate fetch failed: %s", exc)
        if c["rate"] is not None:
            return {"currency": "IDR", "rate": round(c["rate"], 2), "as_of": c["as_of"],
                    "source": "live" if fresh else "cached"}
    return {"currency": "IDR", "rate": FX_FALLBACK_RATE, "as_of": None, "source": "fallback"}


@api.get("/fx")
def get_fx_rate():
    """Public (no secrets). Sync def so FastAPI runs the blocking fetch in a worker thread."""
    return get_usd_idr_rate()


# ---- Auth endpoints ----
def _guard_privileged_role(actor: dict, *roles):
    """Only a Super Admin may create, promote, demote or change a Super Admin account."""
    if "super_admin" in roles and actor.get("role") != "super_admin":
        raise HTTPException(403, "Only a Super Admin can manage Super Admin accounts")


@api.post("/auth/register")
async def register(body: UserCreate, actor: dict = Depends(admin_required)):
    """Creating accounts is an admin action (there is no public sign-up)."""
    _guard_privileged_role(actor, body.role)
    conn = get_conn()
    email = body.email.lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,password_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (uid, email, body.name, body.role, body.department, body.campus or "", body.supervisor or "", body.supervisor_name or "", body.employee_id or "", hash_password(body.password), now_iso()),
    )
    conn.commit()
    conn.close()
    return {"id": uid, "email": email, "name": body.name, "role": body.role, "department": body.department}


@api.post("/auth/login")
async def login(body: LoginIn, response: Response):
    conn = get_conn()
    email = body.email.lower()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    user = row_to_dict(row)
    token = create_token(user["id"], user["email"], user["role"])
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=7*24*3600, path="/")
    return {
        "id": user["id"], "email": user["email"], "name": user["name"],
        "role": user["role"], "department": user.get("department"),
        "campus": user.get("campus"),
        "token": token,
    }


@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ---- Users ----
@api.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.post("/users")
async def create_user(body: UserCreate, actor: dict = Depends(admin_required)):
    return await register(body, actor)


USER_IMPORT_COLUMNS = ["name", "email", "role", "department", "campus", "supervisor_name", "supervisor", "employee_id", "password"]
_USER_COL_ALIASES = {
    "nama": "name", "full_name": "name", "email_address": "email", "peran": "role", "jabatan": "department",
    "departemen": "department", "unit": "department", "kampus": "campus", "nama_atasan": "supervisor_name",
    "atasan": "supervisor_name", "supervisor_email": "supervisor", "email_atasan": "supervisor",
    "nip": "employee_id", "id_karyawan": "employee_id", "kata_sandi": "password",
}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_password(n: int = 10) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(n))


def _norm_user_row(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        key = re.sub(r"[\s\-]+", "_", (k or "").strip().lower())
        key = _USER_COL_ALIASES.get(key, key)
        if key in USER_IMPORT_COLUMNS and key not in out:
            out[key] = (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v).strip())
    return {c: out.get(c, "") for c in USER_IMPORT_COLUMNS}


def _validate_user_rows(conn, rows: list) -> list:
    """Normalise + validate parsed rows. Returns [{row, data, errors}]."""
    existing = {r["email"].lower(): r for r in conn.execute("SELECT email, name FROM users").fetchall()}
    by_name = {}
    for r in conn.execute("SELECT email, name FROM users").fetchall():
        by_name.setdefault(_name_key(r["name"]), set()).add(r["email"].lower())
    file_emails = {}
    parsed = []
    for i, raw in enumerate(rows, start=2):  # row 1 = header
        d = _norm_user_row(raw)
        if not any(d.values()):
            continue
        parsed.append((i, d))
        if _EMAIL_RE.match(d["email"]):
            by_name.setdefault(_name_key(d["name"]), set()).add(d["email"].lower())
    campuses = {c.casefold(): c for c in VALID_CAMPUSES if c}
    out = []
    for i, d in parsed:
        errs = []
        d["email"] = d["email"].lower()
        if not d["name"]:
            errs.append("name is required")
        if not _EMAIL_RE.match(d["email"]):
            errs.append("email is missing or invalid")
        elif d["email"] in existing:
            errs.append(f'email "{d["email"]}" is already registered')
        elif d["email"] in file_emails:
            errs.append(f'email "{d["email"]}" is duplicated (row {file_emails[d["email"]]})')
        else:
            file_emails[d["email"]] = i
        role = (d["role"] or "staff").casefold()
        role = {"administrator": "admin", "staf": "staff", "user": "staff"}.get(role, role)
        if role not in ("admin", "staff"):
            errs.append('role must be "admin" or "staff"')
        d["role"] = role
        if d["campus"]:
            c = campuses.get(d["campus"].casefold())
            if c:
                d["campus"] = c
            else:
                errs.append('campus must be "YPJ Kuala Kencana" or "YPJ Tembagapura"')
        if d["password"] and len(d["password"]) < 6:
            errs.append("password must be at least 6 characters")
        if d["supervisor"] and not _EMAIL_RE.match(d["supervisor"]):
            errs.append("supervisor e-mail is invalid")
        if not d["supervisor"] and d["supervisor_name"]:  # fill the e-mail from a registered / listed user with that name
            hits = by_name.get(_name_key(d["supervisor_name"]), set())
            if len(hits) == 1:
                d["supervisor"] = next(iter(hits))
        out.append({"row": i, "data": d, "errors": errs})
    return out


def _welcome_email_html(name: str, email: str, password: str, generated: bool) -> str:
    pw_line = (f'<tr><td style="padding:6px 0;color:#64748b;width:120px">Kata sandi sementara</td>'
               f'<td style="padding:6px 0;font-family:monospace;font-size:15px"><b>{html_mod.escape(password)}</b></td></tr>') if password else ""
    body = f"""
      <h2 style="margin:0 0 10px;font-size:20px">Akun Anda sudah dibuat</h2>
      <p style="margin:0 0 14px;font-size:14px;line-height:1.6">Halo {html_mod.escape(name)}, Anda sekarang terdaftar di aplikasi manajemen aset YPJ.
      Aset yang diserahkan kepada Anda akan diberitahukan lewat email ini dan perlu Anda konfirmasi di menu <b>Aset Saya</b>.</p>
      <table role="presentation" style="border-collapse:collapse;font-size:14px;margin:0 0 10px">
        <tr><td style="padding:6px 0;color:#64748b;width:120px">Email</td><td style="padding:6px 0"><b>{html_mod.escape(email)}</b></td></tr>
        {pw_line}
      </table>
      {'<p style="margin:0;font-size:13px;color:#b45309">Segera ganti kata sandi setelah masuk.</p>' if generated else ''}"""
    return _email_shell(body, eyebrow="Akun baru", cta_label="Masuk ke Asset Registry")


@api.get("/users/import-template")
async def users_import_template(_: dict = Depends(admin_required)):
    ex1 = "Budi Santoso,budi@fmi.com,staff,SD Administration,YPJ Kuala Kencana,Jeni Mansawan,jnelcema@fmi.com,0000123456,"
    ex2 = "Sari Dewi,sari@fmi.com,staff,SMP,YPJ Tembagapura,,,,"
    buf = io.BytesIO(("﻿" + ",".join(USER_IMPORT_COLUMNS) + f"\n{ex1}\n{ex2}\n").encode("utf-8"))
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="user-import-template.csv"'})


@api.post("/users/import")
async def users_import(file: UploadFile = File(...), dry_run: bool = Query(True),
                       send_invite: bool = Query(False), admin: dict = Depends(admin_required)):
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 2 MB)")
    rows = _parse_import_file(content, file.filename or "upload.csv")
    if not rows:
        raise HTTPException(400, "File is empty or has no data rows")
    if len(rows) > 500:
        raise HTTPException(400, "Too many rows (max 500 per file)")
    conn = get_conn()
    checked = _validate_user_rows(conn, rows)
    if not checked:
        conn.close()
        raise HTTPException(400, "File is empty or has no data rows")
    preview = [{"row": c["row"], "name": c["data"]["name"], "email": c["data"]["email"], "role": c["data"]["role"],
                "department": c["data"]["department"], "campus": c["data"]["campus"],
                "supervisor": c["data"]["supervisor"], "errors": c["errors"]} for c in checked]
    total = len(preview)
    invalid = sum(1 for p in preview if p["errors"])
    if dry_run:
        conn.close()
        return {"dry_run": True, "total": total, "valid": total - invalid, "invalid": invalid, "preview": preview}
    created = []
    ts = now_iso()
    for c in checked:
        if c["errors"]:
            continue
        d = c["data"]
        generated = not d["password"]
        pw = d["password"] or _gen_password()
        uid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,password_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (uid, d["email"], d["name"], d["role"], d["department"], d["campus"], d["supervisor"], d["supervisor_name"],
             d["employee_id"], hash_password(pw), ts))
        created.append({"id": uid, "name": d["name"], "email": d["email"], "role": d["role"],
                        "password": pw, "generated": generated})
    conn.commit()
    conn.close()
    invited = 0
    if send_invite and email_configured():
        for u in created:
            if send_email(u["email"], "[YPJ Assets] Akun Anda sudah dibuat",
                          _welcome_email_html(u["name"], u["email"], u["password"], u["generated"])):
                invited += 1
    logger.info("Bulk user import by %s: %d created, %d skipped, %d invited", admin.get("email"), len(created), invalid, invited)
    return {"dry_run": False, "created": len(created), "skipped": invalid, "invited": invited,
            "invite_requested": bool(send_invite), "email_configured": email_configured(), "users": created,
            "errors": [p for p in preview if p["errors"]]}


# ---- Invitations & password reset (single-use, expiring links; only a hash of the token is stored) ----
INVITE_HOURS = 7 * 24
ADMIN_RESET_HOURS = 24
FORGOT_RESET_HOURS = 2


class SetPasswordIn(BaseModel):
    token: str
    password: str


class ForgotPasswordIn(BaseModel):
    email: str


def _token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _make_password_token(conn, uid: str, kind: str, hours: int) -> str:
    conn.execute("DELETE FROM password_tokens WHERE user_id = ? AND used_at IS NULL", (uid,))
    tok = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO password_tokens (token_hash,user_id,kind,expires_at,created_at) VALUES (?,?,?,?,?)",
                 (_token_hash(tok), uid, kind, (now + timedelta(hours=hours)).isoformat(), now.isoformat()))
    return tok


def _password_link_email(name: str, kind: str, link: str, hours: int) -> tuple:
    days = hours // 24
    valid = f"{days} hari" if hours >= 24 else f"{hours} jam"
    if kind == "invite":
        subject = "[YPJ Assets] Undangan: buat kata sandi akun Anda"
        title, intro, cta, eyebrow = ("Selamat datang di YPJ Assets",
            "Akun Anda di aplikasi manajemen aset YPJ sudah dibuat. Klik tombol di bawah untuk membuat kata sandi, lalu masuk. "
            "Aset yang diserahkan kepada Anda akan diberitahukan lewat email dan dikonfirmasi di menu <b>Aset Saya</b>.",
            "Buat kata sandi", "Undangan")
    else:
        subject = "[YPJ Assets] Atur ulang kata sandi Anda"
        title, intro, cta, eyebrow = ("Atur ulang kata sandi",
            "Kami menerima permintaan untuk mengatur ulang kata sandi akun Anda. Klik tombol di bawah untuk membuat kata sandi baru.",
            "Atur ulang kata sandi", "Keamanan akun")
    body = (f'<h2 style="margin:0 0 10px;font-size:20px">{title}</h2>'
            f'<p style="margin:0 0 14px;font-size:14px;line-height:1.6">Halo {html_mod.escape(name)}, {intro}</p>'
            f'<p style="margin:0;font-size:12px;color:#64748b">Tautan berlaku {valid} dan hanya dapat dipakai sekali. '
            f'Jika Anda tidak merasa memintanya, abaikan email ini.</p>')
    return subject, _email_shell(body, eyebrow=eyebrow, cta_label=cta, cta_url=link)


def _send_password_link(conn, u: dict, kind: str, hours: int) -> dict:
    tok = _make_password_token(conn, u["id"], kind, hours)
    conn.commit()
    link = f"{APP_URL}/set-password?token={tok}"
    sent = False
    if email_configured():
        subject, html_body = _password_link_email(u["name"], kind, link, hours)
        sent = bool(send_email(u["email"], subject, html_body))
    return {"sent": sent, "link": link, "email_configured": email_configured(), "email": u["email"]}


@api.post("/users/{uid}/invite")
async def invite_user(uid: str, admin: dict = Depends(admin_required)):
    conn = get_conn()
    u = conn.execute("SELECT id,name,email FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")
    res = _send_password_link(conn, dict(u), "invite", INVITE_HOURS)
    conn.close()
    logger.info("Invitation for %s created by %s (sent=%s)", u["email"], admin.get("email"), res["sent"])
    return res


@api.post("/users/{uid}/reset-password")
async def admin_reset_password(uid: str, admin: dict = Depends(admin_required)):
    conn = get_conn()
    u = conn.execute("SELECT id,name,email FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")
    res = _send_password_link(conn, dict(u), "reset", ADMIN_RESET_HOURS)
    conn.close()
    logger.info("Password reset link for %s created by %s (sent=%s)", u["email"], admin.get("email"), res["sent"])
    return res


@api.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    """Always answers the same way so it cannot be used to discover which e-mails are registered."""
    conn = get_conn()
    u = conn.execute("SELECT id,name,email FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
    if u:
        recent = conn.execute("SELECT created_at FROM password_tokens WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                              (u["id"],)).fetchone()
        too_soon = False
        if recent:
            try:
                too_soon = (datetime.now(timezone.utc) - datetime.fromisoformat(recent["created_at"])).total_seconds() < 60
            except ValueError:
                pass
        if not too_soon:
            _send_password_link(conn, dict(u), "reset", FORGOT_RESET_HOURS)
    conn.close()
    return {"ok": True}


def _lookup_password_token(conn, tok: str):
    r = conn.execute("SELECT t.*, u.name, u.email FROM password_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?",
                     (_token_hash(tok or ""),)).fetchone()
    if not r or r["used_at"]:
        return None
    try:
        if datetime.fromisoformat(r["expires_at"]) < datetime.now(timezone.utc):
            return None
    except ValueError:
        return None
    return dict(r)


@api.get("/auth/password-token/{tok}")
async def check_password_token(tok: str):
    conn = get_conn()
    r = _lookup_password_token(conn, tok)
    conn.close()
    if not r:
        return {"valid": False}
    return {"valid": True, "kind": r["kind"], "name": r["name"], "email": r["email"]}


@api.post("/auth/set-password")
async def set_password(body: SetPasswordIn):
    if len(body.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    conn = get_conn()
    r = _lookup_password_token(conn, body.token)
    if not r:
        conn.close()
        raise HTTPException(400, "Tautan tidak valid atau sudah kedaluwarsa. Minta tautan baru.")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.password), r["user_id"]))
    conn.execute("UPDATE password_tokens SET used_at = ? WHERE token_hash = ?", (now_iso(), r["token_hash"]))
    conn.execute("DELETE FROM password_tokens WHERE user_id = ? AND used_at IS NULL", (r["user_id"],))
    conn.commit()
    conn.close()
    return {"ok": True, "email": r["email"]}


@api.delete("/users/{uid}")
async def delete_user(uid: str, actor: dict = Depends(admin_required)):
    conn = get_conn()
    t = conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
    if t and t["role"] == "super_admin":
        if actor.get("role") != "super_admin":
            conn.close()
            raise HTTPException(403, "Only a Super Admin can delete a Super Admin account")
        if conn.execute("SELECT COUNT(*) FROM users WHERE role='super_admin'").fetchone()[0] <= 1:
            conn.close()
            raise HTTPException(400, "Cannot delete the last Super Admin")
    res = conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    if res.rowcount == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True}


class UserPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    campus: Optional[str] = None
    supervisor: Optional[str] = None
    supervisor_name: Optional[str] = None
    employee_id: Optional[str] = None
    password: Optional[str] = None


@api.put("/users/{uid}")
async def update_user(uid: str, body: UserPatch, actor: dict = Depends(admin_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    if "role" in updates and updates["role"] not in ("super_admin", "admin", "staff"):
        raise HTTPException(400, "Invalid role")
    chk = get_conn()
    target = chk.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
    if target:
        _guard_privileged_role(actor, target["role"], updates.get("role"))
        if target["role"] == "super_admin" and updates.get("role", "super_admin") != "super_admin" \
                and chk.execute("SELECT COUNT(*) FROM users WHERE role='super_admin'").fetchone()[0] <= 1:
            chk.close()
            raise HTTPException(400, "Cannot remove the last Super Admin")
    chk.close()
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [uid]
    conn = get_conn()
    res = conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", params)
    if res.rowcount == 0:
        conn.close()
        raise HTTPException(404, "User not found")
    conn.commit()
    row = conn.execute("SELECT id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,created_at FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row)


# ---- File upload ----
@api.post("/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    file_id = str(uuid.uuid4())
    rel_path = f"{user['id']}/{file_id}.{ext}"
    dest = UPLOADS_DIR / user['id']
    dest.mkdir(exist_ok=True)
    full_path = dest / f"{file_id}.{ext}"
    data = await file.read()
    full_path.write_bytes(data)
    content_type = file.content_type or "application/octet-stream"
    conn = get_conn()
    conn.execute(
        "INSERT INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES (?,?,?,?,?,?,0,?)",
        (file_id, rel_path, file.filename, content_type, len(data), user["id"], now_iso()),
    )
    conn.commit()
    conn.close()
    return {"path": rel_path, "name": file.filename, "size": len(data), "content_type": content_type}


@api.get("/files/{path:path}")
async def download_file(path: str, request: Request, auth: Optional[str] = Query(None)):
    token = request.cookies.get("access_token")
    if not token:
        ah = request.headers.get("Authorization", "")
        if ah.startswith("Bearer "):
            token = ah[7:]
    if not token and auth:
        token = auth
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        raise HTTPException(401, "Invalid token")
    full_path = UPLOADS_DIR / path
    if not full_path.exists():
        raise HTTPException(404, "File not found")
    conn = get_conn()
    row = conn.execute("SELECT * FROM files WHERE storage_path = ? AND is_deleted = 0", (path,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "File not found")
    return FileResponse(str(full_path), media_type=row["content_type"], filename=row["original_filename"])


# ---- Assets ----
# ---- Staff access rules ----
# Staff see only assets of their own campus (plus anything assigned to them), may report faults / request transfers
# only for assets they hold (or have on loan), and may borrow only "shared" assets nobody holds personally.
def is_admin_user(user: dict) -> bool:
    return user.get("role") in ADMIN_ROLES


def asset_scope(user: dict, prefix: str = "") -> tuple:
    """(sql_condition, params) limiting an assets query to what this user may see; ("", []) for admins."""
    if is_admin_user(user):
        return "", []
    campus = (user.get("campus") or "").strip()
    if campus:
        return f"({prefix}campus = ? OR {prefix}assigned_to_user_id = ?)", [campus, user["id"]]
    return f"({prefix}assigned_to_user_id = ?)", [user["id"]]


def can_view_asset(user: dict, asset: dict) -> bool:
    if is_admin_user(user):
        return True
    campus = (user.get("campus") or "").strip()
    return asset.get("assigned_to_user_id") == user["id"] or bool(campus and asset.get("campus") == campus)


def has_active_loan(conn, user: dict, asset_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM loan_requests WHERE asset_id = ? AND requested_by = ? AND status = 'active' LIMIT 1",
                             (asset_id, user["id"])).fetchone())


def loan_block_reason(user: dict, asset: dict):
    """None when this user may request a loan on the asset, else a user-facing reason (Indonesian)."""
    if is_admin_user(user):
        return None
    if not can_view_asset(user, asset):
        return "Aset ini bukan di kampus Anda."
    if (asset.get("user_type") or "") != "shared":
        return "Hanya aset kategori Bersama (Shared) yang dapat dipinjam, misalnya laptop, kamera, atau perangkat di Lab Komputer."
    if asset.get("status") != "active":
        return "Aset ini sedang tidak aktif dan tidak dapat dipinjam."
    holder_id, holder = asset.get("assigned_to_user_id"), (asset.get("assigned_to_name") or "").strip()
    if holder_id == user["id"]:
        return "Aset ini sudah di-assign kepada Anda."
    if (holder_id or holder) and (asset.get("assignment_kind") or "personal") == "personal":
        return "Aset ini di-assign personal kepada pengguna lain dan tidak dapat dipinjam."
    return None


def asset_permissions(conn, user: dict, asset: dict) -> dict:
    admin = is_admin_user(user)
    holder = asset.get("assigned_to_user_id") == user["id"]
    return {
        "can_report": admin or holder or has_active_loan(conn, user, asset["id"]),
        "can_transfer": admin or holder,
        "can_loan": loan_block_reason(user, asset) is None,
        "loan_block_reason": loan_block_reason(user, asset),
    }


@api.get("/assets")
async def list_assets(
    user: dict = Depends(get_current_user),
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    location: Optional[str] = None,
    campus: Optional[str] = None,
    assigned_to: Optional[str] = None,
):
    conn = get_conn()
    conditions = []
    params = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if campus:
        conditions.append("campus = ?")
        params.append(campus)
    if location:
        conditions.append("location = ?")
        params.append(location)
    if assigned_to:
        conditions.append("assigned_to_user_id = ?")
        params.append(assigned_to)
    if search:
        conditions.append("(name LIKE ? OR asset_tag LIKE ? OR serial_number LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    sc, sp = asset_scope(user)
    if sc:
        conditions.append(sc)
        params.extend(sp)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"SELECT * FROM assets {where} ORDER BY created_at DESC", params).fetchall()
    conn.close()
    assets = [row_to_dict(r) for r in rows]
    for a in assets:
        a["depreciation"] = calc_depreciation(a["purchase_price"], a["purchase_date"], a.get("useful_life_years", 5), a.get("residual_value") or 0)
    return assets


@api.post("/assets")
async def create_asset(body: AssetIn, user: dict = Depends(admin_required)):
    aid = str(uuid.uuid4())
    ts = now_iso()
    conn = get_conn()
    # An owner that is a real user must confirm receipt first; the asset starts unassigned until then.
    to_user = (require_user(conn, body.assigned_to_user_id, body.assigned_to_name)
               if (body.assigned_to_name or body.assigned_to_user_id) else None)
    direct_uid, direct_name = (None, None) if to_user else (body.assigned_to_user_id, body.assigned_to_name)
    conn.execute("""
        INSERT INTO assets (id,name,asset_tag,category,asset_type,description,campus,location,status,
            purchase_price,purchase_date,useful_life_years,warranty_end_date,
            serial_number,supplier,assigned_to_user_id,assigned_to_name,
            photo_path,documents,created_at,updated_at,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        aid, body.name, body.asset_tag, body.category, body.asset_type or "School Asset",
        body.description or "", body.campus or "", body.location, body.status,
        body.purchase_price, body.purchase_date, body.useful_life_years, body.warranty_end_date,
        body.serial_number or "", body.supplier or "", direct_uid, direct_name,
        body.photo_path, json.dumps(body.documents), ts, ts, user["id"],
    ))
    extras = {k: getattr(body, k) for k in EXTRA_ASSET_KEYS}
    extras["maintenance_required"] = 1 if extras["maintenance_required"] else 0
    for k, _t, d in EXTRA_ASSET_FIELDS:
        if extras[k] is None:
            extras[k] = d
    conn.execute(
        "UPDATE assets SET " + ", ".join(f"{k}=?" for k in extras) + " WHERE id=?",
        list(extras.values()) + [aid],
    )
    if direct_name:
        conn.execute("""
            INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), aid, None, None, direct_name,
              direct_uid, "Initial assignment", user["id"], user["name"], ts))
    pending = None
    if to_user:
        pending = create_assignment(conn, row_to_dict(conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()),
                                    to_user, "personal", "new", user, to_label=body.assigned_to_name or to_user["name"])
    conn.commit()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    conn.close()
    doc = row_to_dict(row)
    doc["depreciation"] = calc_depreciation(doc["purchase_price"], doc["purchase_date"], doc.get("useful_life_years", 5), doc.get("residual_value") or 0)
    if pending:
        notify_assignees([pending])
        doc["pending_assignment"] = pending
    return doc


IMPORT_COLUMNS = [
    "name", "asset_tag", "category", "asset_type", "description",
    "campus", "location", "status", "purchase_price", "purchase_date",
    "useful_life_years", "warranty_end_date", "serial_number", "supplier",
    "assigned_to_name",
] + EXTRA_ASSET_KEYS

VALID_CATEGORIES = [
    "IT Equipment", "AV Equipment", "Furniture", "Lab Equipment",
    "Vehicles", "Books", "Sports", "Music Equipment", "Other",
]
# Suggested useful life (years) per category. Used when a CSV/Excel import leaves the column empty;
# the New Asset form mirrors this table (frontend/src/pages/AssetFormPage.jsx) - keep them in sync.
DEFAULT_USEFUL_LIFE = {
    "IT Equipment": 4, "AV Equipment": 5, "Furniture": 8, "Lab Equipment": 8, "Vehicles": 8,
    "Books": 5, "Sports": 5, "Music Equipment": 8, "Other": 5,
}
VALID_STATUSES = ["active", "in_repair", "retired", "lost"]
VALID_CAMPUSES = ["YPJ Kuala Kencana", "YPJ Tembagapura", ""]


def _validate_import_row(row: dict, row_num: int, seen_tags: set) -> list:
    """Return a list of error strings for this row (empty = valid)."""
    errors = []
    name = (row.get("name") or "").strip()
    tag  = (row.get("asset_tag") or "").strip()
    cat  = (row.get("category") or "").strip()
    loc  = (row.get("location") or "").strip()
    status = (row.get("status") or "active").strip()
    campus = (row.get("campus") or "").strip()

    if not name:
        errors.append("name is required")
    if not tag:
        errors.append("asset_tag is required")
    elif tag in seen_tags:
        errors.append(f'duplicate asset_tag "{tag}" within file')
    if not cat:
        errors.append("category is required")
    elif cat not in VALID_CATEGORIES:
        errors.append(f'unknown category "{cat}" — must be one of: {", ".join(VALID_CATEGORIES)}')
    if not loc:
        errors.append("location is required")
    if status not in VALID_STATUSES:
        errors.append(f'invalid status "{status}" — must be: active, in_repair, retired, lost')
    if campus and campus not in VALID_CAMPUSES:
        errors.append(f'unknown campus "{campus}"')

    price_str = (row.get("purchase_price") or "").strip()
    if price_str:
        try:
            float(price_str)
        except ValueError:
            errors.append(f'purchase_price "{price_str}" is not a number')

    life_str = (row.get("useful_life_years") or "").strip()
    if life_str:
        try:
            int(life_str)
        except ValueError:
            errors.append(f'useful_life_years "{life_str}" must be an integer')

    for num_col in ("maintenance_cost", "residual_value"):
        val = (row.get(num_col) or "").strip()
        if val:
            try:
                float(val)
            except ValueError:
                errors.append(f'{num_col} "{val}" is not a number')

    for date_col in ("purchase_date", "warranty_end_date", *EXTRA_DATE_KEYS):
        val = (row.get(date_col) or "").strip()
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                errors.append(f'{date_col} "{val}" must be YYYY-MM-DD')

    return errors


def _parse_import_file(content: bytes, filename: str) -> list:
    """
    Parse CSV or XLSX bytes. Returns list of dicts, each with the IMPORT_COLUMNS keys.
    Raises HTTPException 400 for unparseable files.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header = [str(c).strip() if c else "" for c in next(rows_iter, [])]
            rows = []
            for r in rows_iter:
                rows.append({header[i]: (str(r[i]).strip() if r[i] is not None else "") for i in range(len(header))})
        except Exception as exc:
            raise HTTPException(400, f"Could not parse Excel file: {exc}")
    else:
        try:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            rows = [dict(r) for r in reader]
        except Exception as exc:
            raise HTTPException(400, f"Could not parse CSV file: {exc}")
    return rows


@api.get("/assets/export")
async def export_assets(
    user: dict = Depends(get_current_user),
    search:      Optional[str] = None,
    category:    Optional[str] = None,
    status:      Optional[str] = None,
    campus:      Optional[str] = None,
    location:    Optional[str] = None,
    assigned_to: Optional[str] = None,
):
    import openpyxl
    conn = get_conn()
    conditions, params = [], []
    if category:    conditions.append("category = ?");              params.append(category)
    if status:      conditions.append("status = ?");                params.append(status)
    if campus:      conditions.append("campus = ?");                params.append(campus)
    if location:    conditions.append("location = ?");              params.append(location)
    if assigned_to: conditions.append("assigned_to_user_id = ?");   params.append(assigned_to)
    _sc, _sp = asset_scope(user)
    if _sc:         conditions.append(_sc);                         params.extend(_sp)
    if search:
        conditions.append("(name LIKE ? OR asset_tag LIKE ? OR serial_number LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM assets {where} ORDER BY name", params
    ).fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Assets"
    headers = [
        "Tag", "Asset Name", "Serial Number", "Category", "Asset Type",
        "Campus", "Room / Location", "Status", "Assigned To",
        "Purchase Price (IDR)", "Purchase Date", "Useful Life (yrs)",
        "Warranty End", "Supplier", "Description", "Created At",
        "Asset ID", "Item Type", "Brand", "Model", "Unit", "Building", "Department", "User Type",
        "Acquisition Type", "PO / Contract No.", "Funding Source", "Condition", "Condition Notes",
        "Last Inspection", "Next Inspection", "Maintenance Required", "Last Maintenance",
        "Next Maintenance", "Maintenance Provider", "Maintenance Cost", "Warranty Start",
        "Warranty Provider", "Residual Value",
    ]
    ws.append(headers)
    _style_header(ws)

    for r in rows:
        d = dict(r)
        ws.append([
            d.get("asset_tag") or "",
            d.get("name") or "",
            d.get("serial_number") or "",
            d.get("category") or "",
            d.get("asset_type") or "",
            d.get("campus") or "",
            d.get("location") or "",
            d.get("status") or "",
            d.get("assigned_to_name") or "",
            d.get("purchase_price") or 0,
            d["purchase_date"][:10] if d.get("purchase_date") else "",
            d.get("useful_life_years") or "",
            d["warranty_end_date"][:10] if d.get("warranty_end_date") else "",
            d.get("supplier") or "",
            d.get("description") or "",
            d["created_at"][:10] if d.get("created_at") else "",
            d.get("asset_code") or "", d.get("item_type") or "", d.get("brand") or "", d.get("model") or "",
            d.get("unit") or "", d.get("building") or "", d.get("department") or "", d.get("user_type") or "",
            d.get("acquisition_type") or "", d.get("po_number") or "", d.get("funding_source") or "",
            d.get("asset_condition") or "", d.get("condition_notes") or "",
            d.get("last_inspection_date") or "", d.get("next_inspection_date") or "",
            "Yes" if d.get("maintenance_required") else "No",
            d.get("last_maintenance_date") or "", d.get("next_maintenance_date") or "",
            d.get("maintenance_provider") or "", d.get("maintenance_cost") or 0,
            d.get("warranty_start_date") or "", d.get("warranty_provider") or "",
            d.get("residual_value") or 0,
        ])

    # Auto-size columns
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"assets-export-{today}.xlsx")


@api.get("/assets/import-template")
async def download_import_template(_: dict = Depends(admin_required)):
    header = ",".join(IMPORT_COLUMNS)
    example = (
        'Dell Latitude 5430,IT-LAP-0001,IT Equipment,School Asset,'
        'Example laptop,YPJ Kuala Kencana,Computer Lab A,active,'
        '19500000,2023-08-15,4,2026-08-15,DL5430X01,Dell Technologies,Maria Hernandez'
        + "," * len(EXTRA_ASSET_KEYS)
    )
    buf = io.BytesIO(f"{header}\n{example}\n".encode())
    headers = {"Content-Disposition": 'attachment; filename="asset-import-template.csv"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)


@api.post("/assets/import")
async def bulk_import_assets(
    file: UploadFile = File(...),
    dry_run: bool = Query(True),
    user: dict = Depends(admin_required),
):
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 5 MB)")

    rows = _parse_import_file(content, file.filename or "upload.csv")
    if not rows:
        raise HTTPException(400, "File is empty or has no data rows")

    # --- validate ---
    conn = get_conn()
    existing_tags = {
        r[0] for r in conn.execute("SELECT asset_tag FROM assets").fetchall()
    }

    seen_tags: set = set()
    preview = []
    for i, row in enumerate(rows, start=2):  # row 1 = header
        errs = _validate_import_row(row, i, seen_tags)
        tag = (row.get("asset_tag") or "").strip()
        if tag and tag in existing_tags:
            errs.append(f'asset_tag "{tag}" already exists in the database')
        if tag:
            seen_tags.add(tag)
        preview.append({
            "row": i,
            "name": (row.get("name") or "").strip(),
            "asset_tag": tag,
            "category": (row.get("category") or "").strip(),
            "campus": (row.get("campus") or "").strip(),
            "location": (row.get("location") or "").strip(),
            "status": (row.get("status") or "active").strip(),
            "errors": errs,
        })

    total   = len(preview)
    invalid = sum(1 for p in preview if p["errors"])
    valid   = total - invalid

    if dry_run:
        conn.close()
        return {"dry_run": True, "total": total, "valid": valid, "invalid": invalid, "preview": preview}

    # --- actual import ---
    ts = now_iso()
    imported = 0
    skipped  = 0
    import_errors = []

    for i, row in enumerate(rows, start=2):
        p = preview[i - 2]
        if p["errors"]:
            skipped += 1
            import_errors.append({"row": i, "errors": p["errors"]})
            continue
        try:
            aid = str(uuid.uuid4())
            name      = (row.get("name") or "").strip()
            tag       = (row.get("asset_tag") or "").strip()
            cat       = (row.get("category") or "").strip()
            atype     = (row.get("asset_type") or "School Asset").strip()
            desc      = (row.get("description") or "").strip()
            campus    = (row.get("campus") or "").strip()
            loc       = (row.get("location") or "").strip()
            status    = (row.get("status") or "active").strip()
            price_s   = (row.get("purchase_price") or "0").strip()
            price     = float(price_s) if price_s else 0.0
            pdate     = (row.get("purchase_date") or "").strip() or None
            life_s    = (row.get("useful_life_years") or "").strip()
            life      = int(life_s) if life_s else DEFAULT_USEFUL_LIFE.get(cat, 5)
            wdate     = (row.get("warranty_end_date") or "").strip() or None
            serial    = (row.get("serial_number") or "").strip()
            supplier  = (row.get("supplier") or "").strip()
            owner     = (row.get("assigned_to_name") or "").strip()

            conn.execute("""
                INSERT INTO assets
                  (id,name,asset_tag,category,asset_type,description,campus,location,status,
                   purchase_price,purchase_date,useful_life_years,warranty_end_date,
                   serial_number,supplier,assigned_to_user_id,assigned_to_name,
                   photo_path,documents,created_at,updated_at,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                aid, name, tag, cat, atype, desc, campus, loc, status,
                price, pdate, life, wdate, serial, supplier,
                None, owner or None,
                None, "[]", ts, ts, user["id"],
            ))
            extras = {}
            for k, _t, d in EXTRA_ASSET_FIELDS:
                raw = (row.get(k) or "").strip()
                if k == "maintenance_required":
                    extras[k] = 1 if raw.lower() in ("1", "yes", "y", "true", "ya") else 0
                elif isinstance(d, (int, float)):
                    extras[k] = float(raw) if raw else d
                else:
                    extras[k] = raw
            conn.execute(
                "UPDATE assets SET " + ", ".join(f"{k}=?" for k in extras) + " WHERE id=?",
                list(extras.values()) + [aid],
            )
            if owner:
                conn.execute("""
                    INSERT INTO ownership_logs
                      (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (str(uuid.uuid4()), aid, None, None, owner, None,
                      "Bulk import", user["id"], user["name"], ts))
            imported += 1
        except Exception as exc:
            skipped += 1
            import_errors.append({"row": i, "errors": [str(exc)]})

    conn.commit()
    conn.close()
    return {"dry_run": False, "imported": imported, "skipped": skipped, "errors": import_errors}


@api.get("/assets/{aid}")
async def get_asset(aid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Asset not found")
    asset = row_to_dict(row)
    if not can_view_asset(user, asset):
        conn.close()
        raise HTTPException(403, "Aset ini bukan di kampus Anda.")
    asset["permissions"] = asset_permissions(conn, user, asset)
    asset["depreciation"] = calc_depreciation(asset["purchase_price"], asset["purchase_date"], asset.get("useful_life_years", 5), asset.get("residual_value") or 0)
    asset["ownership_history"] = [
        dict(r) for r in conn.execute("SELECT * FROM ownership_logs WHERE asset_id = ? ORDER BY at DESC", (aid,)).fetchall()
    ]
    asset["faults"] = [
        dict(r) for r in conn.execute("SELECT * FROM faults WHERE asset_id = ? ORDER BY created_at DESC", (aid,)).fetchall()
    ]
    asset["compliance"] = [
        dict(r) for r in conn.execute("SELECT * FROM compliance WHERE asset_id = ? ORDER BY due_date ASC", (aid,)).fetchall()
    ]
    asset["pending_assignment"] = pending_assignment(conn, aid)
    conn.close()
    return asset


@api.put("/assets/{aid}")
async def update_asset(aid: str, body: AssetUpdate, user: dict = Depends(admin_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates["updated_at"] = now_iso()
    if "maintenance_required" in updates:
        updates["maintenance_required"] = 1 if updates["maintenance_required"] else 0
    if "documents" in updates:
        updates["documents"] = json.dumps(updates["documents"])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [aid]
    conn = get_conn()
    res = conn.execute(f"UPDATE assets SET {set_clause} WHERE id = ?", params)
    if res.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Asset not found")
    conn.commit()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    conn.close()
    return row_to_dict(row)


@api.delete("/assets/{aid}")
async def delete_asset(aid: str, _: dict = Depends(admin_required)):
    conn = get_conn()
    conn.execute("DELETE FROM assets WHERE id = ?", (aid,))
    conn.execute("DELETE FROM ownership_logs WHERE asset_id = ?", (aid,))
    conn.execute("DELETE FROM assignments WHERE asset_id = ?", (aid,))
    conn.execute("DELETE FROM faults WHERE asset_id = ?", (aid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.post("/assets/{aid}/transfer")
async def transfer_asset(aid: str, body: TransferIn, user: dict = Depends(admin_required)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Asset not found")
    asset = row_to_dict(row)
    to_user = require_user(conn, body.new_owner_user_id, body.new_owner_name)
    if to_user:  # the recipient has to confirm before ownership changes
        try:
            a = create_assignment(conn, asset, to_user, asset.get("assignment_kind") or "personal", "transfer", user,
                                  note=body.note or "", to_label=body.new_owner_name)
        except ValueError as e:
            conn.close()
            raise HTTPException(409, "This asset already has a hand-over waiting for confirmation"
                                if str(e) == "pending" else "Asset is already assigned to this person")
        conn.commit()
        conn.close()
        notify_assignees([a])
        return {**a, "pending": True}
    log_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute("""
        INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (log_id, aid, asset.get("assigned_to_name"), asset.get("assigned_to_user_id"),
          body.new_owner_name, body.new_owner_user_id, body.note or "", user["id"], user["name"], ts))
    conn.execute(
        "UPDATE assets SET assigned_to_name=?, assigned_to_user_id=?, updated_at=? WHERE id=?",
        (body.new_owner_name, body.new_owner_user_id, ts, aid)
    )
    conn.commit()
    log = dict(conn.execute("SELECT * FROM ownership_logs WHERE id = ?", (log_id,)).fetchone())
    conn.close()
    return log


# ---- Faults ----
@api.get("/faults")
async def list_faults(user: dict = Depends(get_current_user), status: Optional[str] = None):
    conn = get_conn()
    sc, sp = asset_scope(user)
    conds, params = [], []
    if status:
        conds.append("status = ?"); params.append(status)
    if sc:
        conds.append(f"(reported_by = ? OR asset_id IN (SELECT id FROM assets WHERE {sc}))"); params += [user["id"]] + sp
    rows = conn.execute("SELECT * FROM faults" + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY created_at DESC", params).fetchall()
    faults = [dict(r) for r in rows]
    for f in faults:
        a = conn.execute("SELECT name, asset_tag FROM assets WHERE id = ?", (f["asset_id"],)).fetchone()
        f["asset_name"] = a["name"] if a else "(deleted)"
        f["asset_tag"] = a["asset_tag"] if a else ""
    conn.close()
    return faults


@api.post("/faults")
async def create_fault(body: FaultIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    a = conn.execute("SELECT * FROM assets WHERE id = ?", (body.asset_id,)).fetchone()
    if not a:
        conn.close()
        raise HTTPException(404, "Asset not found")
    if not asset_permissions(conn, user, dict(a))["can_report"]:
        conn.close()
        raise HTTPException(403, "Anda hanya dapat melaporkan kerusakan untuk aset yang di-assign kepada Anda atau sedang Anda pinjam.")
    fid = str(uuid.uuid4())
    ts = now_iso()
    conn.execute("""
        INSERT INTO faults (id,asset_id,title,description,severity,status,
            reported_by,reported_by_name,resolution_note,resolved_at,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (fid, body.asset_id, body.title, body.description, body.severity, "open",
          user["id"], user["name"], None, None, ts))
    conn.commit()
    row = conn.execute("SELECT * FROM faults WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return dict(row)


@api.put("/faults/{fid}")
async def update_fault(fid: str, body: FaultUpdate, user: dict = Depends(admin_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if updates.get("status") == "resolved":
        updates["resolved_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [fid]
    conn = get_conn()
    res = conn.execute(f"UPDATE faults SET {set_clause} WHERE id = ?", params)
    if res.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Fault not found")
    conn.commit()
    row = conn.execute("SELECT * FROM faults WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return dict(row)


# ---- Compliance ----
@api.get("/compliance")
async def list_compliance(user: dict = Depends(get_current_user)):
    conn = get_conn()
    sc, sp = asset_scope(user)
    rows = conn.execute("SELECT * FROM compliance" + (f" WHERE (asset_id IS NULL OR asset_id = '' OR asset_id IN (SELECT id FROM assets WHERE {sc}))" if sc else "")
                        + " ORDER BY due_date ASC", sp).fetchall()
    items = [dict(r) for r in rows]
    today = datetime.now(timezone.utc)
    for c in items:
        try:
            due = datetime.fromisoformat(c["due_date"].replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if c.get("status") == "pending" and due < today:
                c["status"] = "overdue"
        except Exception:
            pass
        if c.get("asset_id"):
            a = conn.execute("SELECT name FROM assets WHERE id = ?", (c["asset_id"],)).fetchone()
            c["asset_name"] = a["name"] if a else None
    conn.close()
    return items


@api.post("/compliance")
async def create_compliance(body: ComplianceIn, _: dict = Depends(admin_required)):
    conn = get_conn()
    cid = str(uuid.uuid4())
    ts = now_iso()
    conn.execute("""
        INSERT INTO compliance (id,asset_id,title,description,category,due_date,frequency,
            status,completed_date,note,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (cid, body.asset_id, body.title, body.description or "", body.category,
          body.due_date, body.frequency, "pending", None, None, ts))
    conn.commit()
    row = conn.execute("SELECT * FROM compliance WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row)


@api.put("/compliance/{cid}")
async def update_compliance(cid: str, body: ComplianceUpdate, _: dict = Depends(admin_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if updates.get("status") == "completed" and not updates.get("completed_date"):
        updates["completed_date"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [cid]
    conn = get_conn()
    res = conn.execute(f"UPDATE compliance SET {set_clause} WHERE id = ?", params)
    if res.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Compliance item not found")
    conn.commit()
    row = conn.execute("SELECT * FROM compliance WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return dict(row)


@api.delete("/compliance/{cid}")
async def delete_compliance(cid: str, _: dict = Depends(admin_required)):
    conn = get_conn()
    conn.execute("DELETE FROM compliance WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---- Activity log ----
@api.get("/activity")
async def get_activity(
    _: dict = Depends(admin_required),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    event_type: Optional[str] = None,
):
    conn = get_conn()
    offset = (page - 1) * limit

    type_filter = ""
    if event_type and event_type != "all":
        type_filter = f"WHERE type = '{event_type}'"

    rows = conn.execute(f"""
        SELECT * FROM (
            SELECT
                'asset_created' AS type,
                a.id AS ref_id,
                a.name AS subject,
                u.name AS actor,
                a.category AS detail,
                a.campus AS campus,
                a.created_at AS at
            FROM assets a
            LEFT JOIN users u ON u.id = a.created_by

            UNION ALL

            SELECT
                'ownership_transfer' AS type,
                ol.asset_id AS ref_id,
                a.name AS subject,
                ol.by_name AS actor,
                ol.to_name AS detail,
                a.campus AS campus,
                ol.at AS at
            FROM ownership_logs ol
            LEFT JOIN assets a ON a.id = ol.asset_id

            UNION ALL

            SELECT
                'fault_reported' AS type,
                f.asset_id AS ref_id,
                a.name AS subject,
                f.reported_by_name AS actor,
                f.title AS detail,
                a.campus AS campus,
                f.created_at AS at
            FROM faults f
            LEFT JOIN assets a ON a.id = f.asset_id

            UNION ALL

            SELECT
                'fault_resolved' AS type,
                f.asset_id AS ref_id,
                a.name AS subject,
                f.reported_by_name AS actor,
                f.title AS detail,
                a.campus AS campus,
                f.resolved_at AS at
            FROM faults f
            LEFT JOIN assets a ON a.id = f.asset_id
            WHERE f.resolved_at IS NOT NULL

            UNION ALL

            SELECT
                'compliance_added' AS type,
                c.id AS ref_id,
                c.title AS subject,
                NULL AS actor,
                c.category AS detail,
                NULL AS campus,
                c.created_at AS at
            FROM compliance c

            UNION ALL

            SELECT
                'user_created' AS type,
                u.id AS ref_id,
                u.name AS subject,
                NULL AS actor,
                u.role AS detail,
                u.campus AS campus,
                u.created_at AS at
            FROM users u
        ) events
        {type_filter}
        ORDER BY at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()

    total = conn.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT created_at AS at, 'asset_created' AS type FROM assets
            UNION ALL SELECT at, 'ownership_transfer' FROM ownership_logs
            UNION ALL SELECT created_at, 'fault_reported' FROM faults
            UNION ALL SELECT resolved_at, 'fault_resolved' FROM faults WHERE resolved_at IS NOT NULL
            UNION ALL SELECT created_at, 'compliance_added' FROM compliance
            UNION ALL SELECT created_at, 'user_created' FROM users
        ) e {type_filter}
    """).fetchone()[0]

    conn.close()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


# ---- Dashboard ----
@api.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    conn = get_conn()
    sc, sp = asset_scope(user)
    rows = conn.execute("SELECT * FROM assets" + (" WHERE " + sc if sc else ""), sp).fetchall()
    assets = [row_to_dict(r) for r in rows]
    total_assets = len(assets)
    total_value = sum(a.get("purchase_price", 0) for a in assets)
    current_value = 0
    by_category: dict = {}
    by_status: dict = {}
    for a in assets:
        d = calc_depreciation(a["purchase_price"], a["purchase_date"], a.get("useful_life_years", 5), a.get("residual_value") or 0)
        current_value += d["current_value"]
        by_category[a["category"]] = by_category.get(a["category"], 0) + 1
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1

    today = datetime.now(timezone.utc)
    soon = today + timedelta(days=60)
    warranty_alerts = []
    for a in assets:
        we = a.get("warranty_end_date")
        if not we:
            continue
        try:
            d = datetime.fromisoformat(we.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d <= soon:
                warranty_alerts.append({
                    "id": a["id"], "name": a["name"], "asset_tag": a["asset_tag"],
                    "warranty_end_date": we, "expired": d < today,
                })
        except Exception:
            pass

    fscope = f" AND asset_id IN (SELECT id FROM assets WHERE {sc})" if sc else ""
    open_faults = conn.execute(
        "SELECT COUNT(*) FROM faults WHERE status IN ('open','in_progress')" + fscope, sp
    ).fetchone()[0]
    recent_fault_rows = conn.execute(
        "SELECT * FROM faults" + (f" WHERE asset_id IN (SELECT id FROM assets WHERE {sc})" if sc else "") + " ORDER BY created_at DESC LIMIT 5", sp).fetchall()
    recent_faults = []
    for f in recent_fault_rows:
        fd = dict(f)
        a = conn.execute("SELECT name FROM assets WHERE id = ?", (fd["asset_id"],)).fetchone()
        fd["asset_name"] = a["name"] if a else "(deleted)"
        recent_faults.append(fd)

    compliance_rows = conn.execute(
        "SELECT * FROM compliance" + (f" WHERE asset_id IN (SELECT id FROM assets WHERE {sc})" if sc else ""), sp).fetchall()
    overdue = 0
    upcoming = 0
    for c in compliance_rows:
        try:
            d = datetime.fromisoformat(c["due_date"].replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if c["status"] == "completed":
                continue
            if d < today:
                overdue += 1
            elif d <= today + timedelta(days=30):
                upcoming += 1
        except Exception:
            pass

    timeline = []
    if assets:
        for yr_offset in range(0, 6):
            ts = today + timedelta(days=365 * yr_offset)
            total = 0
            for a in assets:
                try:
                    pdate = datetime.fromisoformat(a["purchase_date"].replace("Z", "+00:00"))
                    if pdate.tzinfo is None:
                        pdate = pdate.replace(tzinfo=timezone.utc)
                    age = (ts - pdate).days / 365.25
                    annual = a["purchase_price"] / max(a.get("useful_life_years", 5), 1)
                    accumulated = min(annual * age, a["purchase_price"])
                    val = max(a["purchase_price"] - accumulated, 0)
                    total += val
                except Exception:
                    pass
            timeline.append({"year": ts.year, "value": round(total, 2)})

    conn.close()
    return {
        "total_assets": total_assets,
        "total_purchase_value": round(total_value, 2),
        "current_book_value": round(current_value, 2),
        "depreciated_value": round(total_value - current_value, 2),
        "by_category": by_category,
        "by_status": by_status,
        "warranty_alerts": warranty_alerts,
        "open_faults": open_faults,
        "recent_faults": recent_faults,
        "compliance_overdue": overdue,
        "compliance_upcoming": upcoming,
        "depreciation_timeline": timeline,
        "due_items": collect_due_items(assets, within_days=60, kinds=("inspection", "maintenance")),
    }


# ---- Transfer requests ----
class TransferRequestIn(BaseModel):
    new_owner_name: str
    new_owner_user_id: Optional[str] = None
    note: Optional[str] = ""


@api.post("/transfer-requests")
async def create_transfer_request(asset_id: str, body: TransferRequestIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    asset = conn.execute("SELECT id, name, asset_tag, assigned_to_name, assigned_to_user_id FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not asset:
        conn.close()
        raise HTTPException(404, "Asset not found")
    if not is_admin_user(user) and asset["assigned_to_user_id"] != user["id"]:
        conn.close()
        raise HTTPException(403, "Anda hanya dapat meminta transfer untuk aset yang di-assign kepada Anda.")
    require_user(conn, body.new_owner_user_id, body.new_owner_name)
    rid = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO transfer_requests
            (id, asset_id, asset_name, asset_tag, from_name, to_name, to_user_id, note,
             requested_by, requested_by_name, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)
    """, (rid, asset_id, asset["name"], asset["asset_tag"], asset["assigned_to_name"],
          body.new_owner_name, body.new_owner_user_id, body.note or "", user["id"], user["name"], now_iso()))
    conn.commit()
    row = conn.execute("SELECT * FROM transfer_requests WHERE id = ?", (rid,)).fetchone()
    conn.close()
    return dict(row)


@api.get("/transfer-requests")
async def list_transfer_requests(user: dict = Depends(get_current_user), status: Optional[str] = None):
    conn = get_conn()
    if user["role"] in ADMIN_ROLES:
        base = "SELECT * FROM transfer_requests"
        rows = conn.execute(base + (" WHERE status = ?" if status else "") + " ORDER BY created_at DESC",
                            ([status] if status else [])).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM transfer_requests WHERE requested_by = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.get("/transfer-requests/pending-count")
async def pending_count(_: dict = Depends(admin_required)):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM transfer_requests WHERE status = 'pending'").fetchone()[0]
    conn.close()
    return {"count": n}


@api.put("/transfer-requests/{rid}/approve")
async def approve_transfer(rid: str, user: dict = Depends(admin_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM transfer_requests WHERE id = ?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Request not found")
    req = dict(req)
    if req["status"] != "pending":
        conn.close()
        raise HTTPException(400, "Request is not pending")
    ts = now_iso()
    to_user = require_user(conn, req.get("to_user_id"), req["to_name"])
    if to_user:  # approved by admin; the recipient still has to confirm receipt
        asset = row_to_dict(conn.execute("SELECT * FROM assets WHERE id = ?", (req["asset_id"],)).fetchone())
        try:
            a = create_assignment(conn, asset, to_user, asset.get("assignment_kind") or "personal", "transfer_request",
                                  user, note=req.get("note") or "", to_label=req["to_name"], transfer_request_id=rid)
        except ValueError as e:
            conn.close()
            raise HTTPException(409, "This asset already has a hand-over waiting for confirmation"
                                if str(e) == "pending" else "Asset is already assigned to this person")
        conn.execute("""
            UPDATE transfer_requests SET status='approved', reviewed_by=?, reviewed_by_name=?, reviewed_at=? WHERE id=?
        """, (user["id"], user["name"], ts, rid))
        conn.commit()
        conn.close()
        notify_assignees([a])
        return {"ok": True, "pending_confirmation": True}
    # Perform the actual ownership transfer
    log_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (log_id, req["asset_id"], req["from_name"], None, req["to_name"], None,
          req["note"], user["id"], user["name"], ts))
    conn.execute("UPDATE assets SET assigned_to_name=?, updated_at=? WHERE id=?",
                 (req["to_name"], ts, req["asset_id"]))
    conn.execute("""
        UPDATE transfer_requests SET status='approved', reviewed_by=?, reviewed_by_name=?, reviewed_at=? WHERE id=?
    """, (user["id"], user["name"], ts, rid))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.put("/transfer-requests/{rid}/reject")
async def reject_transfer(rid: str, reason: Optional[str] = None, user: dict = Depends(admin_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM transfer_requests WHERE id = ?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Request not found")
    if dict(req)["status"] != "pending":
        conn.close()
        raise HTTPException(400, "Request is not pending")
    ts = now_iso()
    conn.execute("""
        UPDATE transfer_requests SET status='rejected', reviewed_by=?, reviewed_by_name=?, reviewed_at=?, reject_reason=? WHERE id=?
    """, (user["id"], user["name"], ts, reason or "", rid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ===================================================================
# Assignments: hand-over of assets that the recipient must confirm
# ===================================================================
# An asset only becomes "owned" by the recipient (and shows up in their asset data) after they confirm.
# Until then the asset keeps its previous holder (or stays unassigned for a brand-new asset).
ASSIGNMENT_REMIND_DAYS = 3
ASSIGN_KINDS = ("personal", "class")
ASSIGN_KIND_LABEL_ID = {"personal": "Aset pribadi", "class": "Aset kelas"}
INACTIVE_STATUSES = ("retired", "lost")


def _name_key(s) -> str:
    return " ".join((s or "").split()).casefold()


def resolve_user(conn, user_id=None, label=None):
    """Find the app user a hand-over is addressed to: by id, else by unique name/email in the label."""
    cols = "id,email,name,role,department,campus"
    if user_id:
        r = conn.execute(f"SELECT {cols} FROM users WHERE id = ?", (user_id,)).fetchone()
        if r:
            return dict(r)
    key = _name_key((label or "").split(" — ")[0])
    if not key:
        return None
    hits = [dict(r) for r in conn.execute(f"SELECT {cols} FROM users").fetchall()
            if _name_key(r["name"]) == key or _name_key(r["email"]) == key]
    return hits[0] if len(hits) == 1 else None


def require_user(conn, user_id=None, label=None):
    """Hand-overs go only to users registered in the app (HTTP 422 otherwise)."""
    u = resolve_user(conn, user_id, label)
    if not u:
        conn.close()
        raise HTTPException(422, "Penerima harus pengguna yang sudah terdaftar di aplikasi. Tambahkan dulu di menu Users.")
    return u


def _supervisor_cc(conn, user_ids, exclude=()) -> list:
    """Supervisor e-mail addresses (users.supervisor) of the given users, de-duplicated."""
    skip = {(e or "").strip().casefold() for e in exclude}
    out, seen = [], set(skip)
    for uid in user_ids:
        if not uid:
            continue
        r = conn.execute("SELECT supervisor FROM users WHERE id = ?", (uid,)).fetchone()
        addr = ((r["supervisor"] if r else "") or "").strip()
        if "@" in addr and addr.casefold() not in seen:
            seen.add(addr.casefold())
            out.append(addr)
    return out


def pending_assignment(conn, asset_id):
    r = conn.execute("SELECT * FROM assignments WHERE asset_id = ? AND status = 'pending'", (asset_id,)).fetchone()
    return dict(r) if r else None


def create_assignment(conn, asset: dict, to_user: dict, kind: str, source: str, by_user: dict,
                      note: str = "", batch_id: str = None, to_label: str = None,
                      transfer_request_id: str = None) -> dict:
    """Insert a pending assignment (caller commits). Raises ValueError('pending'|'same_holder')."""
    if kind not in ASSIGN_KINDS:
        kind = "personal"
    if pending_assignment(conn, asset["id"]):
        raise ValueError("pending")
    if asset.get("assigned_to_user_id") == to_user["id"] and (asset.get("assignment_kind") or "personal") == kind:
        raise ValueError("same_holder")
    rid = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO assignments
            (id, batch_id, asset_id, asset_name, asset_tag, from_user_id, from_name,
             to_user_id, to_name, to_label, kind, source, note, status,
             created_by, created_by_name, created_at, transfer_request_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)
    """, (rid, batch_id or rid, asset["id"], asset["name"], asset["asset_tag"],
          asset.get("assigned_to_user_id"), asset.get("assigned_to_name"),
          to_user["id"], to_user["name"], to_label or to_user["name"], kind, source, note or "",
          by_user["id"], by_user["name"], now_iso(), transfer_request_id))
    return dict(conn.execute("SELECT * FROM assignments WHERE id = ?", (rid,)).fetchone())


def apply_assignment(conn, a: dict, ts: str):
    """Make the recipient the owner (called when they confirm). Caller commits."""
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (a["asset_id"],)).fetchone()
    if not asset:
        raise HTTPException(404, "Asset not found")
    asset = dict(asset)
    label = a.get("to_label") or a["to_name"]
    conn.execute("""
        INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (str(uuid.uuid4()), a["asset_id"], asset.get("assigned_to_name"), asset.get("assigned_to_user_id"),
          label, a["to_user_id"], ((a.get("note") or "") + " — dikonfirmasi penerima").strip(" —"),
          a["created_by"], a["created_by_name"], ts))
    conn.execute(
        "UPDATE assets SET assigned_to_name=?, assigned_to_user_id=?, assignment_kind=?, updated_at=? WHERE id=?",
        (label, a["to_user_id"], a["kind"], ts, a["asset_id"]))


# ---- E-mails ----
def _assignment_items_html(items: list) -> str:
    import html as _h
    rows = "".join(
        "<tr>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_h.escape(i['asset_name'])}<br>"
        f"<span style='color:#64748b;font-size:12px;'>{_h.escape(i['asset_tag'])}"
        f"{' · ' + _h.escape(i['location']) if i.get('location') else ''}</span></td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;white-space:nowrap;'>"
        f"{_h.escape(ASSIGN_KIND_LABEL_ID.get(i['kind'], i['kind']))}</td>"
        "</tr>" for i in items)
    return ("<table style='border-collapse:collapse;width:100%;font-size:14px;margin:14px 0;'>"
            "<tr style='text-align:left;color:#64748b;font-size:11px;letter-spacing:.1em;text-transform:uppercase;"
            "border-bottom:1px solid #e2e8f0;'><th style='padding:8px;'>Aset</th><th style='padding:8px;'>Jenis</th></tr>"
            f"{rows}</table>")


def _assignment_request_html(to_name: str, items: list, by_name: str, note: str = "", reminder: bool = False) -> str:
    import html as _h
    n = len(items)
    lead = ("Pengingat: ada serah terima aset yang <strong>belum Anda konfirmasi</strong>." if reminder else
            f"<strong>{_h.escape(by_name)}</strong> menyerahkan {n} aset kepada Anda.")
    note_html = (f"<p style='font-size:13px;color:#475569;'>Catatan: {_h.escape(note)}</p>" if note else "")
    return _email_shell(f"""
        <h2 style="margin:0 0 10px;font-size:22px;color:#0f172a;">Konfirmasi penerimaan aset</h2>
        <p style="margin:0 0 8px;">Yth. {_h.escape(to_name)},</p>
        <p style="margin:0 0 8px;">{lead}</p>
        {_assignment_items_html(items)}
        {note_html}
        <div style="border-left:3px solid #f2c14e;background:#fffbeb;padding:10px 14px;font-size:13px;color:#78350f;">
          Aset baru tercatat atas nama Anda setelah Anda memeriksa fisik barangnya dan menekan <strong>Terima</strong>.
          Jika ada yang tidak sesuai, tekan <strong>Tolak</strong> dan tulis alasannya.
        </div>""", eyebrow="Serah terima aset", cta_label="Tinjau & konfirmasi", cta_url=f"{APP_URL}/my-assets")


def _assignment_response_html(a_list: list, accepted: bool, by_name: str, reason: str = "") -> str:
    import html as _h
    color, word = ("#15803d", "menerima") if accepted else ("#b91c1c", "menolak")
    reason_html = (f"<p style='font-size:13px;color:#475569;'>Alasan: {_h.escape(reason)}</p>"
                   if (reason and not accepted) else "")
    return _email_shell(f"""
        <h2 style="margin:0 0 10px;font-size:22px;color:#0f172a;">Serah terima {'diterima' if accepted else 'ditolak'}</h2>
        <p style="margin:0 0 8px;"><strong>{_h.escape(by_name)}</strong>
          <span style="color:{color};font-weight:700;">{word}</span> {len(a_list)} aset berikut:</p>
        {_assignment_items_html(a_list)}{reason_html}""",
        eyebrow="Serah terima aset", cta_label="Buka Asset Registry", cta_url=f"{APP_URL}/user-assets")


def _user_email(conn, uid):
    r = conn.execute("SELECT email, name FROM users WHERE id = ?", (uid,)).fetchone()
    return (r["email"], r["name"]) if r else (None, None)


def notify_assignees(assignments: list, reminder: bool = False):
    """One e-mail per recipient listing all of their pending items."""
    conn = get_conn()
    try:
        by_user: dict = {}
        for a in assignments:
            by_user.setdefault(a["to_user_id"], []).append(a)
        for uid, group in by_user.items():
            email, name = _user_email(conn, uid)
            if not email:
                continue
            for a in group:
                row = conn.execute("SELECT location FROM assets WHERE id = ?", (a["asset_id"],)).fetchone()
                a["location"] = row["location"] if row else ""
            by = ", ".join(sorted({a["created_by_name"] for a in group}))
            n = len(group)
            subject = (f"[YPJ Assets] {'Pengingat: ' if reminder else ''}Konfirmasi penerimaan {n} aset")
            cc = _supervisor_cc(conn, [uid] + [a.get("from_user_id") for a in group], exclude=[email])
            send_email(email, subject,
                       _assignment_request_html(name, group, by, group[0].get("note") or "", reminder), cc=cc)
    finally:
        conn.close()


def notify_responses(responded: list, accepted: bool, by_name: str, reason: str = ""):
    """Tell whoever created the hand-over (and the general inbox) what the recipient decided."""
    conn = get_conn()
    try:
        by_creator: dict = {}
        for a in responded:
            by_creator.setdefault(a["created_by"], []).append(a)
        for uid, group in by_creator.items():
            email, _ = _user_email(conn, uid)
            if not email:
                continue
            for a in group:
                row = conn.execute("SELECT location FROM assets WHERE id = ?", (a["asset_id"],)).fetchone()
                a["location"] = row["location"] if row else ""
            cc = [ASSET_REMINDER_EMAIL] if ASSET_REMINDER_EMAIL else []
            cc += _supervisor_cc(conn, [a["to_user_id"] for a in group] + [a.get("from_user_id") for a in group],
                                 exclude=[email] + cc)
            subject = (f"[YPJ Assets] {by_name} {'menerima' if accepted else 'menolak'} {len(group)} aset")
            send_email(email, subject, _assignment_response_html(group, accepted, by_name, reason), cc=cc)
    finally:
        conn.close()


def send_assignment_reminders(now=None) -> dict:
    """Daily: re-mail recipients whose hand-overs are still unconfirmed after ASSIGNMENT_REMIND_DAYS days."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=ASSIGNMENT_REMIND_DAYS)).isoformat()
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("""
        SELECT * FROM assignments
        WHERE status = 'pending' AND created_at <= ? AND (last_reminded_at IS NULL OR last_reminded_at <= ?)
    """, (cutoff, cutoff)).fetchall()]
    if rows:
        ts = now.isoformat()
        conn.executemany("UPDATE assignments SET last_reminded_at = ? WHERE id = ?", [(ts, r["id"]) for r in rows])
        conn.commit()
    conn.close()
    if rows:
        notify_assignees(rows, reminder=True)
    logger.info("Assignment reminders: %d pending item(s) re-sent", len(rows))
    return {"items": len(rows)}


# ---- API ----
class BulkAssignIn(BaseModel):
    to_user_id: str
    asset_ids: List[str]
    kind: Literal["personal", "class"] = "class"
    note: Optional[str] = ""


class RespondIn(BaseModel):
    ids: List[str]
    action: Literal["accept", "reject"]
    reason: Optional[str] = ""


def _slim_asset(d: dict) -> dict:
    d = dict(d)
    d.pop("documents", None)
    d["depreciation"] = calc_depreciation(d["purchase_price"], d["purchase_date"],
                                          d.get("useful_life_years", 5), d.get("residual_value") or 0)
    return d


def _user_bundle(conn, uid: str) -> dict:
    rows = [row_to_dict(r) for r in conn.execute(
        "SELECT * FROM assets WHERE assigned_to_user_id = ? ORDER BY name", (uid,)).fetchall()]
    assets = [_slim_asset(r) for r in rows]
    personal = [a for a in assets if (a.get("assignment_kind") or "personal") != "class"]
    klass = [a for a in assets if a.get("assignment_kind") == "class"]
    live = [a for a in assets if a["status"] not in INACTIVE_STATUSES]
    pending = []
    for r in conn.execute("SELECT * FROM assignments WHERE to_user_id = ? AND status = 'pending' ORDER BY created_at",
                          (uid,)).fetchall():
        p = dict(r)
        ar = conn.execute("SELECT location, campus, category, purchase_price FROM assets WHERE id = ?",
                          (p["asset_id"],)).fetchone()
        p.update(dict(ar) if ar else {"location": "", "campus": "", "category": "", "purchase_price": 0})
        pending.append(p)
    return {
        "personal": personal, "class": klass, "pending": pending,
        "summary": {
            "personal_count": len([a for a in personal if a["status"] not in INACTIVE_STATUSES]),
            "class_count": len([a for a in klass if a["status"] not in INACTIVE_STATUSES]),
            "pending_count": len(pending),
            "purchase_value": sum(a["purchase_price"] or 0 for a in live),
            "book_value": sum(a["depreciation"]["current_value"] for a in live),
        },
    }


@api.get("/my/assets")
async def my_assets(user: dict = Depends(get_current_user)):
    conn = get_conn()
    out = _user_bundle(conn, user["id"])
    conn.close()
    return out


@api.get("/users/{uid}/assets")
async def user_assets(uid: str, user: dict = Depends(get_current_user)):
    if user["role"] not in ADMIN_ROLES and user["id"] != uid:
        raise HTTPException(403, "Not allowed")
    conn = get_conn()
    u = conn.execute("SELECT id,name,email,department,campus,role FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")
    out = _user_bundle(conn, uid)
    out["user"] = dict(u)
    conn.close()
    return out


@api.get("/dashboard/users")
async def dashboard_users(_: dict = Depends(admin_required)):
    conn = get_conn()
    users = [dict(r) for r in conn.execute(
        "SELECT id,name,email,role,department,campus FROM users ORDER BY name").fetchall()]
    stats = {u["id"]: {"personal_count": 0, "class_count": 0, "pending_count": 0,
                       "purchase_value": 0, "book_value": 0, "oldest_pending": None} for u in users}
    unassigned = 0
    for r in conn.execute("SELECT * FROM assets").fetchall():
        d = row_to_dict(r)
        if d["status"] in INACTIVE_STATUSES:
            continue
        uid = d.get("assigned_to_user_id")
        if not uid or uid not in stats:
            unassigned += 1
            continue
        s = stats[uid]
        s["class_count" if d.get("assignment_kind") == "class" else "personal_count"] += 1
        s["purchase_value"] += d["purchase_price"] or 0
        s["book_value"] += calc_depreciation(d["purchase_price"], d["purchase_date"],
                                             d.get("useful_life_years", 5), d.get("residual_value") or 0)["current_value"]
    total_pending = 0
    for r in conn.execute("SELECT to_user_id, COUNT(*) n, MIN(created_at) oldest FROM assignments "
                          "WHERE status = 'pending' GROUP BY to_user_id").fetchall():
        total_pending += r["n"]
        if r["to_user_id"] in stats:
            stats[r["to_user_id"]]["pending_count"] = r["n"]
            stats[r["to_user_id"]]["oldest_pending"] = r["oldest"]
    conn.close()
    for u in users:
        u.update(stats[u["id"]])
    return {"users": users, "totals": {
        "users": len(users), "unassigned_assets": unassigned, "pending": total_pending,
        "assets_with_users": sum(s["personal_count"] + s["class_count"] for s in stats.values()),
    }}


@api.get("/assignments")
async def list_assignments(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    conn = get_conn()
    sql, params = "SELECT * FROM assignments", []
    cond = []
    if status:
        cond.append("status = ?"); params.append(status)
    if user["role"] not in ADMIN_ROLES:
        cond.append("(to_user_id = ? OR created_by = ?)"); params += [user["id"], user["id"]]
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY created_at DESC LIMIT 500", params).fetchall()]
    conn.close()
    return rows


@api.get("/assignments/pending-count")
async def assignments_pending_count(user: dict = Depends(get_current_user)):
    conn = get_conn()
    mine = conn.execute("SELECT COUNT(*) FROM assignments WHERE status='pending' AND to_user_id = ?",
                        (user["id"],)).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM assignments WHERE status='pending'").fetchone()[0] \
        if user["role"] in ADMIN_ROLES else None
    conn.close()
    return {"mine": mine, "total": total}


@api.post("/assignments/bulk")
async def bulk_assign(body: BulkAssignIn, user: dict = Depends(admin_required)):
    """Hand over several assets (e.g. a whole classroom) to one person; they confirm item by item."""
    if not body.asset_ids:
        raise HTTPException(400, "Select at least one asset")
    conn = get_conn()
    to_user = resolve_user(conn, user_id=body.to_user_id)
    if not to_user:
        conn.close()
        raise HTTPException(404, "Recipient not found")
    batch = str(uuid.uuid4())
    created, skipped = [], []
    for aid in dict.fromkeys(body.asset_ids):
        r = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
        if not r:
            skipped.append({"asset_id": aid, "reason": "not_found"}); continue
        asset = row_to_dict(r)
        if asset["status"] in INACTIVE_STATUSES:
            skipped.append({"asset_id": aid, "name": asset["name"], "reason": "inactive"}); continue
        try:
            created.append(create_assignment(conn, asset, to_user, body.kind, "handover", user,
                                             note=body.note or "", batch_id=batch))
        except ValueError as e:
            skipped.append({"asset_id": aid, "name": asset["name"], "reason": str(e)})
    conn.commit()
    conn.close()
    if created:
        notify_assignees(created)
    return {"created": len(created), "skipped": skipped, "batch_id": batch}


@api.post("/assignments/respond")
async def respond_assignments(body: RespondIn, user: dict = Depends(get_current_user)):
    """The recipient accepts or rejects hand-overs addressed to them."""
    reason = (body.reason or "").strip()
    if body.action == "reject" and len(reason) < 3:
        raise HTTPException(400, "Please give a reason for rejecting")
    conn = get_conn()
    ts = now_iso()
    done, errors = [], []
    for rid in dict.fromkeys(body.ids):
        r = conn.execute("SELECT * FROM assignments WHERE id = ?", (rid,)).fetchone()
        if not r:
            errors.append({"id": rid, "error": "not_found"}); continue
        a = dict(r)
        if a["to_user_id"] != user["id"]:
            errors.append({"id": rid, "error": "not_recipient"}); continue
        if a["status"] != "pending":
            errors.append({"id": rid, "error": "not_pending"}); continue
        if body.action == "accept":
            apply_assignment(conn, a, ts)
            conn.execute("UPDATE assignments SET status='accepted', responded_at=? WHERE id=?", (ts, rid))
        else:
            conn.execute("UPDATE assignments SET status='rejected', responded_at=?, reject_reason=? WHERE id=?",
                         (ts, reason, rid))
        done.append(a)
    conn.commit()
    conn.close()
    if done:
        notify_responses(done, body.action == "accept", user["name"], reason)
    return {"done": len(done), "errors": errors}


@api.put("/assignments/{rid}/cancel")
async def cancel_assignment(rid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = conn.execute("SELECT * FROM assignments WHERE id = ?", (rid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "Assignment not found")
    a = dict(r)
    if user["role"] not in ADMIN_ROLES and a["created_by"] != user["id"]:
        conn.close()
        raise HTTPException(403, "Not allowed")
    if a["status"] != "pending":
        conn.close()
        raise HTTPException(400, "Assignment is not pending")
    conn.execute("UPDATE assignments SET status='cancelled', responded_at=? WHERE id=?", (now_iso(), rid))
    conn.commit()
    conn.close()
    return {"ok": True}


def _xlsx_response(wb, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


def _style_header(ws):
    from openpyxl.styles import Font, PatternFill, Alignment
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
        cell.alignment = Alignment(horizontal="center")


@api.get("/reports/asset-inventory")
async def report_asset_inventory(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("""
        SELECT name, asset_tag, category, campus, location, status,
               assigned_to_name, purchase_price, purchase_date, useful_life_years,
               warranty_end_date, serial_number, supplier, created_at
        FROM assets ORDER BY name
    """).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asset Inventory"
    headers = ["Asset Name", "Tag", "Category", "Campus", "Room/Location", "Status",
               "Assigned To", "Purchase Price (IDR)", "Purchase Date", "Useful Life (yrs)",
               "Warranty End", "Serial Number", "Supplier", "Created At"]
    ws.append(headers)
    _style_header(ws)
    for r in rows:
        d = dict(r)
        dep = calc_depreciation(d["purchase_price"], d["purchase_date"], d.get("useful_life_years", 5), d.get("residual_value") or 0)
        ws.append([
            d["name"], d["asset_tag"], d["category"], d["campus"], d["location"],
            d["status"], d["assigned_to_name"] or "", d["purchase_price"],
            d["purchase_date"][:10] if d["purchase_date"] else "",
            d["useful_life_years"], d["warranty_end_date"][:10] if d["warranty_end_date"] else "",
            d["serial_number"] or "", d["supplier"] or "", d["created_at"][:10],
        ])
    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"asset-inventory-{today}.xlsx")


@api.get("/reports/depreciation")
async def report_depreciation(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("""
        SELECT name, asset_tag, category, campus, purchase_price, purchase_date, useful_life_years, residual_value
        FROM assets ORDER BY name
    """).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Depreciation Schedule"
    headers = ["Asset Name", "Tag", "Category", "Campus", "Purchase Price (IDR)",
               "Purchase Date", "Useful Life (yrs)", "Annual Depreciation (IDR)",
               "Accumulated Depreciation (IDR)", "Current Book Value (IDR)", "Age (yrs)"]
    ws.append(headers)
    _style_header(ws)
    for r in rows:
        d = dict(r)
        dep = calc_depreciation(d["purchase_price"], d["purchase_date"], d.get("useful_life_years", 5), d.get("residual_value") or 0)
        ws.append([
            d["name"], d["asset_tag"], d["category"], d["campus"],
            d["purchase_price"], d["purchase_date"][:10] if d["purchase_date"] else "",
            d["useful_life_years"],
            round(dep["annual"], 2), round(dep["accumulated"], 2),
            round(dep["current_value"], 2), round(dep["age_years"], 2),
        ])
    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"depreciation-schedule-{today}.xlsx")


def _add_years(d, n: int):
    try:
        return d.replace(year=d.year + n)
    except ValueError:                      # 29 Feb -> 28 Feb in a non-leap year
        return d.replace(year=d.year + n, day=28)


@api.get("/reports/fully-depreciated")
async def report_fully_depreciated(_: dict = Depends(admin_required)):
    """Assets still on the books (not retired / lost) that have reached the end of their useful life."""
    import openpyxl
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM assets ORDER BY name").fetchall()]
    conn.close()
    today = datetime.now(LOCAL_TZ).date()
    out = []
    for d in rows:
        if d.get("status") in ("retired", "lost") or (d.get("purchase_price") or 0) <= 0:
            continue
        pd = _parse_day(d.get("purchase_date"))
        life = int(d.get("useful_life_years") or 5)
        if not pd:
            continue
        end = _add_years(pd, max(life, 1))
        if end > today:
            continue
        dep = calc_depreciation(d["purchase_price"], d["purchase_date"], life, d.get("residual_value") or 0)
        out.append((d, end, round((today - end).days / 365.25, 1), dep))
    out.sort(key=lambda x: (-x[2], x[0]["name"]))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fully Depreciated"
    ws.append(["Asset Name", "Tag", "Category", "Campus", "Room/Location", "Status", "Assigned To",
               "Purchase Date", "Useful Life (yrs)", "Fully Depreciated On", "Years Past End of Life",
               "Purchase Price (IDR)", "Residual Value (IDR)", "Current Book Value (IDR)"])
    _style_header(ws)
    for d, end, past, dep in out:
        ws.append([
            d["name"], d["asset_tag"], d["category"], d.get("campus") or "", d.get("location") or "",
            d["status"], d.get("assigned_to_name") or "", d["purchase_date"][:10],
            int(d.get("useful_life_years") or 5), end.isoformat(), past,
            d["purchase_price"], d.get("residual_value") or 0, round(dep["current_value"], 2),
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max((len(str(c.value or "")) for c in col), default=10) + 4, 40)
    return _xlsx_response(wb, f"fully-depreciated-{datetime.now().strftime('%Y%m%d')}.xlsx")


@api.get("/reports/faults")
async def report_faults(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("""
        SELECT f.title, f.description, f.severity, f.status,
               a.name AS asset_name, a.asset_tag, a.campus,
               f.reported_by_name, f.resolution_note, f.resolved_at, f.created_at
        FROM faults f
        LEFT JOIN assets a ON a.id = f.asset_id
        ORDER BY f.created_at DESC
    """).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fault Report"
    headers = ["Fault Title", "Description", "Severity", "Status", "Asset Name",
               "Asset Tag", "Campus", "Reported By", "Resolution Note", "Resolved At", "Reported At"]
    ws.append(headers)
    _style_header(ws)
    for r in rows:
        d = dict(r)
        ws.append([
            d["title"], d["description"], d["severity"], d["status"],
            d["asset_name"] or "", d["asset_tag"] or "", d["campus"] or "",
            d["reported_by_name"],
            d["resolution_note"] or "", d["resolved_at"][:10] if d["resolved_at"] else "",
            d["created_at"][:10],
        ])
    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"fault-report-{today}.xlsx")


@api.get("/reports/compliance")
async def report_compliance(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.title, c.description, c.category, c.frequency, c.due_date,
               c.status, c.completed_date, c.note,
               a.name AS asset_name, a.asset_tag, c.created_at
        FROM compliance c
        LEFT JOIN assets a ON a.id = c.asset_id
        ORDER BY c.due_date
    """).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compliance Register"
    headers = ["Title", "Description", "Category", "Frequency", "Due Date", "Status",
               "Completed Date", "Note", "Asset Name", "Asset Tag", "Created At"]
    ws.append(headers)
    _style_header(ws)
    for r in rows:
        d = dict(r)
        ws.append([
            d["title"], d["description"] or "", d["category"], d["frequency"],
            d["due_date"][:10] if d["due_date"] else "", d["status"],
            d["completed_date"][:10] if d["completed_date"] else "",
            d["note"] or "", d["asset_name"] or "", d["asset_tag"] or "",
            d["created_at"][:10],
        ])
    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"compliance-register-{today}.xlsx")


@api.get("/reports/ownership")
async def report_ownership(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.name AS asset_name, a.asset_tag, a.campus, a.category,
               ol.from_name, ol.to_name, ol.note, ol.by_name, ol.at
        FROM ownership_logs ol
        LEFT JOIN assets a ON a.id = ol.asset_id
        ORDER BY ol.at DESC
    """).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ownership History"
    headers = ["Asset Name", "Asset Tag", "Campus", "Category",
               "Transferred From", "Transferred To", "Note", "Actioned By", "Date"]
    ws.append(headers)
    _style_header(ws)
    for r in rows:
        d = dict(r)
        ws.append([
            d["asset_name"] or "", d["asset_tag"] or "", d["campus"] or "", d["category"] or "",
            d["from_name"] or "", d["to_name"] or "", d["note"] or "",
            d["by_name"], d["at"][:10] if d["at"] else "",
        ])
    today = datetime.now().strftime("%Y%m%d")
    return _xlsx_response(wb, f"ownership-history-{today}.xlsx")


@api.get("/backup")
async def backup_db(user: dict = Depends(admin_required)):
    if not DB_PATH.exists():
        raise HTTPException(404, "Database file not found")
    return FileResponse(
        str(DB_PATH),
        media_type="application/octet-stream",
        filename=f"ypj-backup-{datetime.now().strftime('%Y%m%d')}.db",
    )


# ---- Loan requests ----

class LoanRequestIn(BaseModel):
    purpose: Optional[str] = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@api.post("/assets/{aid}/loan-request")
async def create_loan_request(aid: str, body: LoanRequestIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not asset:
        conn.close()
        raise HTTPException(404, "Asset not found")
    why = loan_block_reason(user, dict(asset))
    if why:
        conn.close()
        raise HTTPException(403, why)
    rid = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        """INSERT INTO loan_requests
           (id,asset_id,asset_name,asset_tag,requested_by,requested_by_name,purpose,start_date,end_date,status,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,'pending',?)""",
        (rid, aid, asset["name"], asset["asset_tag"], user["id"], user["name"],
         body.purpose or "", body.start_date, body.end_date, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM loan_requests WHERE id = ?", (rid,)).fetchone()
    req = dict(row)

    # Email: confirmation to borrower, CC supervisor + campus heads + notify inbox
    subject = f'[YPJ Assets] Loan request submitted: {req["asset_name"]}'
    body_html = _loan_html(req, "Loan Request Submitted", [
        ("Asset",      f'{req["asset_name"]} ({req["asset_tag"]})'),
        ("Requested by", req["requested_by_name"]),
        ("Purpose",    req.get("purpose") or "—"),
        ("From",       req.get("start_date") or "—"),
        ("Until",      req.get("end_date") or "—"),
        ("Status",     "Pending approval"),
    ], "<p>Your request has been submitted and is awaiting admin approval.</p>")
    cc = get_loan_cc(req, conn, extra=[LOAN_NOTIFY_EMAIL] if LOAN_NOTIFY_EMAIL else [])
    send_email(user["email"], subject, body_html, cc=cc)

    conn.close()
    return req


@api.get("/loan-requests")
async def list_loan_requests(user: dict = Depends(get_current_user), status: Optional[str] = None):
    conn = get_conn()
    if user["role"] in ADMIN_ROLES:
        if status and status != "all":
            rows = conn.execute(
                "SELECT * FROM loan_requests WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM loan_requests ORDER BY created_at DESC"
            ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM loan_requests WHERE requested_by=? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.get("/loan-requests/pending-count")
async def loan_pending_count(_: dict = Depends(admin_required)):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM loan_requests WHERE status='pending'").fetchone()[0]
    conn.close()
    return {"count": n}


@api.put("/loan-requests/{rid}/approve")
async def approve_loan(rid: str, user: dict = Depends(admin_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Loan request not found")
    now = now_iso()
    conn.execute(
        "UPDATE loan_requests SET status='approved',reviewed_by=?,reviewed_by_name=?,reviewed_at=? WHERE id=?",
        (user["id"], user["name"], now, rid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    req = dict(row)

    # Email borrower; CC supervisor + campus heads
    borrower = conn.execute("SELECT email FROM users WHERE id=?", (req["requested_by"],)).fetchone()
    if borrower:
        subject = f'[YPJ Assets] Loan approved: {req["asset_name"]}'
        body_html = _loan_html(req, "Loan Request Approved", [
            ("Asset",       f'{req["asset_name"]} ({req["asset_tag"]})'),
            ("Borrower",    req["requested_by_name"]),
            ("Approved by", req["reviewed_by_name"]),
            ("From",        req.get("start_date") or "—"),
            ("Until",       req.get("end_date") or "—"),
        ], "<p>Your loan request has been approved. The asset will be delivered to you soon.</p>")
        cc = get_loan_cc(req, conn)
        send_email(borrower["email"], subject, body_html, cc=cc)

    conn.close()
    return req


@api.put("/loan-requests/{rid}/reject")
async def reject_loan(rid: str, reason: Optional[str] = None, user: dict = Depends(admin_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Loan request not found")
    conn.execute(
        "UPDATE loan_requests SET status='rejected',reviewed_by=?,reviewed_by_name=?,reviewed_at=?,reject_reason=? WHERE id=?",
        (user["id"], user["name"], now_iso(), reason or "", rid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    req = dict(row)

    # Email borrower; CC supervisor only (campus heads not needed for rejections)
    borrower = conn.execute("SELECT email FROM users WHERE id=?", (req["requested_by"],)).fetchone()
    if borrower:
        subject = f'[YPJ Assets] Loan request not approved: {req["asset_name"]}'
        reason_line = req.get("reject_reason") or ""
        detail = [
            ("Asset",       f'{req["asset_name"]} ({req["asset_tag"]})'),
            ("Rejected by", req["reviewed_by_name"]),
        ]
        if reason_line:
            detail.append(("Reason", reason_line))
        body_html = _loan_html(req, "Loan Request Not Approved", detail,
                               "<p>Please contact the admin if you have questions.</p>")
        u = conn.execute("SELECT supervisor FROM users WHERE id=?", (req["requested_by"],)).fetchone()
        cc = [u["supervisor"]] if u and u["supervisor"] else []
        send_email(borrower["email"], subject, body_html, cc=cc)

    conn.close()
    return req


@api.put("/loan-requests/{rid}/deliver")
async def deliver_loan(
    rid: str,
    condition: str = Form(...),
    note: str = Form(""),
    image: Optional[UploadFile] = File(None),
    user: dict = Depends(admin_required),
):
    """Record pre-check condition and optionally upload an image, then mark as active."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Loan request not found")
    if dict(req)["status"] != "approved":
        conn.close()
        raise HTTPException(400, "Loan must be in 'approved' status to deliver")

    img_path = ""
    if image and image.filename:
        ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else "bin"
        file_id = str(uuid.uuid4())
        rel_path = f"loans/{rid}/pre_{file_id}.{ext}"
        dest = UPLOADS_DIR / "loans" / rid
        dest.mkdir(parents=True, exist_ok=True)
        data = await image.read()
        (dest / f"pre_{file_id}.{ext}").write_bytes(data)
        img_path = rel_path
        conn.execute(
            "INSERT INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES (?,?,?,?,?,?,0,?)",
            (file_id, rel_path, image.filename, image.content_type or "application/octet-stream", len(data), user["id"], now_iso()),
        )

    conn.execute(
        """UPDATE loan_requests
           SET status='active', pre_condition=?, pre_condition_note=?, pre_image_path=?, delivered_at=?
           WHERE id=?""",
        (condition, note, img_path, now_iso(), rid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    req = dict(row)

    # Email borrower; CC supervisor + campus heads
    borrower = conn.execute("SELECT email FROM users WHERE id=?", (req["requested_by"],)).fetchone()
    if borrower:
        cond_labels = {"good": "Good", "trouble": "Has issues", "broken": "Broken", "missing": "Missing"}
        subject = f'[YPJ Assets] Asset delivered: {req["asset_name"]}'
        body_html = _loan_html(req, "Asset Delivered", [
            ("Asset",       f'{req["asset_name"]} ({req["asset_tag"]})'),
            ("Borrower",    req["requested_by_name"]),
            ("Condition",   cond_labels.get(condition, condition)),
            ("Note",        note or "—"),
            ("Return by",   req.get("end_date") or "—"),
        ], "<p>The asset is now in your care. Please return it by the agreed date in the same or better condition.</p>")
        cc = get_loan_cc(req, conn)
        send_email(borrower["email"], subject, body_html, cc=cc)

    conn.close()
    return req


@api.put("/loan-requests/{rid}/return")
async def return_loan(
    rid: str,
    condition: str = Form(...),
    note: str = Form(""),
    image: Optional[UploadFile] = File(None),
    user: dict = Depends(admin_required),
):
    """Record post-check condition and optionally upload an image, then mark as returned."""
    conn = get_conn()
    req = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Loan request not found")
    if dict(req)["status"] != "active":
        conn.close()
        raise HTTPException(400, "Loan must be in 'active' status to return")

    img_path = ""
    if image and image.filename:
        ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else "bin"
        file_id = str(uuid.uuid4())
        rel_path = f"loans/{rid}/post_{file_id}.{ext}"
        dest = UPLOADS_DIR / "loans" / rid
        dest.mkdir(parents=True, exist_ok=True)
        data = await image.read()
        (dest / f"post_{file_id}.{ext}").write_bytes(data)
        img_path = rel_path
        conn.execute(
            "INSERT INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES (?,?,?,?,?,?,0,?)",
            (file_id, rel_path, image.filename, image.content_type or "application/octet-stream", len(data), user["id"], now_iso()),
        )

    conn.execute(
        """UPDATE loan_requests
           SET status='returned', post_condition=?, post_condition_note=?, post_image_path=?, returned_at=?
           WHERE id=?""",
        (condition, note, img_path, now_iso(), rid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM loan_requests WHERE id=?", (rid,)).fetchone()
    req = dict(row)

    # Email borrower (confirmation) + CC supervisor + campus heads + loan notify inbox
    borrower = conn.execute("SELECT email FROM users WHERE id=?", (req["requested_by"],)).fetchone()
    if borrower:
        cond_labels = {"good": "Good", "trouble": "Has issues", "broken": "Broken", "missing": "Missing"}
        subject = f'[YPJ Assets] Return recorded: {req["asset_name"]}'
        body_html = _loan_html(req, "Asset Return Recorded", [
            ("Asset",            f'{req["asset_name"]} ({req["asset_tag"]})'),
            ("Borrower",         req["requested_by_name"]),
            ("Return condition", cond_labels.get(condition, condition)),
            ("Note",             note or "—"),
            ("Returned at",      req.get("returned_at") or "—"),
        ], "<p>Thank you for returning the asset. The loan is now closed.</p>")
        cc = get_loan_cc(req, conn, extra=[LOAN_NOTIFY_EMAIL] if LOAN_NOTIFY_EMAIL else [])
        send_email(borrower["email"], subject, body_html, cc=cc)

    conn.close()
    return req


# ---- Mount ----
app.include_router(api)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Serve React build in production (frontend/build lives one level up from backend/)
BUILD_DIR = ROOT_DIR.parent / "frontend" / "build"
if BUILD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(BUILD_DIR / "static")), name="react-static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = BUILD_DIR / "index.html"
        return HTMLResponse(index.read_text())

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', 'http://localhost:3000,http://localhost:8000').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Startup: init DB + seed ----
def seed_data():
    conn = get_conn()
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@school.edu")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    staff_email = os.environ.get("STAFF_EMAIL", "staff@school.edu")
    staff_password = os.environ.get("STAFF_PASSWORD", "staff123")

    # Find the admin by email OR by role (handles email changes)
    admin = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not admin:
        existing_admin = conn.execute("SELECT id, email FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        if existing_admin:
            # Migrate email to new value from env var
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (admin_email, existing_admin["id"]))
            admin_id = existing_admin["id"]
            logger.info(f"Updated admin email to: {admin_email}")
        else:
            admin_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users (id,email,name,role,department,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                (admin_id, admin_email, "Admin User", "admin", "Administration", hash_password(admin_password), now_iso()),
            )
            logger.info(f"Seeded admin: {admin_email}")
    else:
        admin_id = admin["id"]

    # Owner account: gets the Super Admin role once (only while no Super Admin exists), and the
    # placeholder seed name is replaced with the owner's real name.
    if not conn.execute("SELECT 1 FROM users WHERE role = 'super_admin' LIMIT 1").fetchone():
        conn.execute("UPDATE users SET role = 'super_admin' WHERE id = ? AND role = 'admin'", (admin_id,))
        logger.info("Promoted %s to super_admin", admin_email)
    owner_name = os.environ.get("ADMIN_NAME", "Natalius Marani")
    conn.execute("UPDATE users SET name = ? WHERE id = ? AND name = 'Admin User'", (owner_name, admin_id))

    # Remove demo staff user if still present
    demo_staff = conn.execute("SELECT id FROM users WHERE email = ?", (staff_email,)).fetchone()
    if demo_staff:
        conn.execute("DELETE FROM users WHERE id = ?", (demo_staff["id"],))
        logger.info(f"Removed demo staff user: {staff_email}")
    staff_id = admin_id  # fallback so demo asset seeding still works

    asset_count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    if asset_count == 0:
        ts = now_iso()
        # (name, tag, category, desc, campus, location, status, price, pdate, life, warranty, serial, supplier, assignee_id, assignee_name)
        demo = [
            ("Dell Latitude 5430 Laptop", "IT-LAP-0001", "IT Equipment",
             "Teacher laptop with Windows 11 Pro", "YPJ Kuala Kencana", "Computer Lab A", "active",
             1250.00, "2023-08-15", 4, "2026-08-15", "DL5430X01", "Dell Technologies", staff_id, "Maria Hernandez"),
            ("Epson PowerLite Projector", "AV-PRJ-0014", "AV Equipment",
             "Classroom projector 3500 lumens", "YPJ Tembagapura", "Room 204", "active",
             680.00, "2022-03-10", 6, "2025-03-10", "EPL3500-204", "Epson", None, "Room 204"),
            ("Microscope Set Olympus CX23", "LAB-MIC-0007", "Lab Equipment",
             "Set of 8 student microscopes", "YPJ Kuala Kencana", "Biology Lab", "active",
             4200.00, "2021-09-01", 10, "2024-09-01", "OLY-CX23-S8", "Olympus", staff_id, "Maria Hernandez"),
            ("Steelcase Student Desks (40)", "FUR-DSK-0040", "Furniture",
             "Set of 40 height-adjustable desks", "YPJ Kuala Kencana", "Room 112", "active",
             8000.00, "2020-07-20", 12, "2030-07-20", "SC-LOT-112", "Steelcase", None, "Room 112"),
            ("Toyota Hiace School Bus", "VEH-BUS-0001", "Vehicles",
             "16-seater school transport van", "YPJ Tembagapura", "Main Garage", "active",
             35000.00, "2019-04-12", 8, "2024-04-12", "TYT-HIACE-19", "Toyota", None, "Transport Dept"),
            ("iPad Pro 11\" Cart (30 units)", "IT-IPD-0030", "IT Equipment",
             "Mobile cart of iPads for classroom use", "YPJ Kuala Kencana", "Library", "active",
             27000.00, "2024-01-20", 5, "2027-01-20", "IPD-CART-LIB1", "Apple", None, "Library"),
            ("Smart Interactive Whiteboard", "AV-IWB-0003", "AV Equipment",
             "Smart Board 6065 65-inch", "YPJ Tembagapura", "Room 301", "in_repair",
             3500.00, "2022-11-05", 7, "2025-11-05", "SB6065-301", "Smart Technologies", None, "Room 301"),
            ("Casio Digital Piano CDP-S110", "MUS-PIA-0002", "Music Equipment",
             "Compact digital piano for music room", "YPJ Kuala Kencana", "Music Room", "active",
             540.00, "2023-02-14", 8, "2026-02-14", "CDS110-002", "Casio", None, "Music Room"),
        ]
        asset_ids = []
        for row in demo:
            aid = str(uuid.uuid4())
            asset_ids.append(aid)
            (name, tag, cat, desc, campus, loc, status, price, pdate, life, warranty, serial, supplier, assignee_id, assignee_name) = row
            conn.execute("""
                INSERT INTO assets (id,name,asset_tag,category,description,campus,location,status,
                    purchase_price,purchase_date,useful_life_years,warranty_end_date,
                    serial_number,supplier,assigned_to_user_id,assigned_to_name,
                    photo_path,documents,created_at,updated_at,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (aid, name, tag, cat, desc, campus, loc, status, round(price * FX_FALLBACK_RATE, -3), pdate, life, warranty,
                  serial, supplier, assignee_id, assignee_name, None, "[]", ts, ts, admin_id))
            conn.execute("""
                INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (str(uuid.uuid4()), aid, None, None, assignee_name, assignee_id, "Initial assignment", admin_id, "Admin User", ts))

        # Sample faults (whiteboard = index 6, projector = index 1)
        conn.execute("""
            INSERT INTO faults (id,asset_id,title,description,severity,status,reported_by,reported_by_name,resolution_note,resolved_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), asset_ids[6], "Whiteboard touch sensors not responding",
              "Bottom-left quadrant unresponsive to touch input.", "high", "in_progress",
              staff_id, "Maria Hernandez", None, None, ts))
        conn.execute("""
            INSERT INTO faults (id,asset_id,title,description,severity,status,reported_by,reported_by_name,resolution_note,resolved_at,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), asset_ids[1], "Projector lamp dim",
              "Image is noticeably dim, lamp may need replacement.", "medium", "open",
              staff_id, "Maria Hernandez", None, None, ts))

        # Sample compliance
        soon_due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        overdue_due = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        future_due = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
        conn.execute("""
            INSERT INTO compliance (id,asset_id,title,description,category,due_date,frequency,status,completed_date,note,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), asset_ids[4], "Annual School Bus Safety Inspection",
              "Mandatory DOT-equivalent inspection", "Safety", soon_due, "annual", "pending", None, None, ts))
        conn.execute("""
            INSERT INTO compliance (id,asset_id,title,description,category,due_date,frequency,status,completed_date,note,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), None, "Fire Extinguisher Recertification",
              "All campus fire extinguishers to be recertified", "Safety", overdue_due, "annual", "pending", None, None, ts))
        conn.execute("""
            INSERT INTO compliance (id,asset_id,title,description,category,due_date,frequency,status,completed_date,note,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), asset_ids[2], "Lab Equipment Calibration",
              "Annual calibration of microscopes", "Inspection", future_due, "annual", "pending", None, None, ts))

        logger.info("Seeded demo assets, faults, and compliance items")

    conn.commit()
    conn.close()


@app.on_event("startup")
async def on_startup():
    init_db()
    seed_data()
    # Start background scheduler for daily return reminders
    scheduler = BackgroundScheduler(timezone="Asia/Jakarta")
    scheduler.add_job(send_return_reminders, "cron", hour=8, minute=0)
    scheduler.add_job(send_asset_due_reminders, "cron", hour=8, minute=5)
    scheduler.add_job(send_assignment_reminders, "cron", hour=8, minute=10)
    scheduler.start()
    mode = "production" if BUILD_DIR.exists() else "development"
    logger.info(f"Startup complete [{mode}] — DB: {DB_PATH}")
