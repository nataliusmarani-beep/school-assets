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
import urllib.parse
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

try:  # run as the package (uvicorn backend.server:app) or as a plain module (tests, local scripts)
    from . import booking_engine, byod
except ImportError:
    import booking_engine
    import byod
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
# Campus heads — keyed by campus slug (KK = Kuala Kencana, TPRA). The old *_TB_* variable names still work.
HEAD_KK_EMAIL         = os.environ.get("HEAD_KK_EMAIL", "")        # Head of Campus – YPJ Kuala Kencana
HEAD_TPRA_EMAIL       = os.environ.get("HEAD_TPRA_EMAIL") or os.environ.get("HEAD_TB_EMAIL", "")  # Head of Campus – YPJ TPRA
HEAD_ADMIN_KK_EMAIL   = os.environ.get("HEAD_ADMIN_KK_EMAIL", "")  # Head of Administration – YPJ Kuala Kencana
HEAD_ADMIN_TPRA_EMAIL = os.environ.get("HEAD_ADMIN_TPRA_EMAIL") or os.environ.get("HEAD_ADMIN_TB_EMAIL", "")  # Head of Administration – YPJ TPRA

# Map campus name → (head-of-campus email, head-of-admin email)
CAMPUS_HEAD_EMAILS: dict = {
    "YPJ Kuala Kencana": [HEAD_KK_EMAIL, HEAD_ADMIN_KK_EMAIL],
    "YPJ TPRA":   [HEAD_TPRA_EMAIL, HEAD_ADMIN_TPRA_EMAIL],
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

    -- Append-only e-signed acknowledgements of the school policies (never updated or deleted)
    CREATE TABLE IF NOT EXISTS policy_acceptances (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        user_name TEXT NOT NULL,
        signed_name TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        text_hash TEXT NOT NULL DEFAULT '',
        lang TEXT NOT NULL DEFAULT '',
        ip TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT '',
        accepted_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_policy_acc_user ON policy_acceptances (user_id, policy_version);

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
    CREATE TABLE IF NOT EXISTS classrooms (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        campus TEXT NOT NULL DEFAULT '',
        room_type TEXT NOT NULL DEFAULT 'kelas',
        responsible_user_id TEXT,
        responsible_name TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS classroom_handovers (
        id TEXT PRIMARY KEY,
        classroom_id TEXT NOT NULL,
        classroom_name TEXT NOT NULL,
        from_user_id TEXT,
        from_name TEXT,
        to_user_id TEXT NOT NULL,
        to_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        note TEXT DEFAULT '',
        created_by TEXT NOT NULL,
        created_by_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        accepted_count INTEGER DEFAULT 0,
        discrepancy_count INTEGER DEFAULT 0
    );
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
    if "phone" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")   # WhatsApp number, 62xxxxxxxxxx
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
    if "handover_flag" not in asset_cols:
        conn.execute("ALTER TABLE assets ADD COLUMN handover_flag TEXT NOT NULL DEFAULT ''")
    as_cols = [r[1] for r in conn.execute("PRAGMA table_info(assignments)").fetchall()]
    if "applied" not in as_cols:
        conn.execute("ALTER TABLE assignments ADD COLUMN applied INTEGER NOT NULL DEFAULT 1")
    tr_cols = [r[1] for r in conn.execute("PRAGMA table_info(transfer_requests)").fetchall()]
    if "to_user_id" not in tr_cols:
        conn.execute("ALTER TABLE transfer_requests ADD COLUMN to_user_id TEXT")
    conn.commit()
    backfill_assignee_user_ids(conn)
    reset_free_text_owners(conn)
    migrate_money_to_idr(conn)
    rename_campus_tembagapura_to_tpra(conn)
    booking_engine.init_booking_schema(conn)
    byod.init_schema(conn)
    migrated = booking_engine.migrate_legacy_loans(conn)
    if migrated:
        logger.warning("Copied %d legacy loan request(s) into bookings", migrated)
    sync_classrooms(conn)
    conn.close()


def rename_campus_tembagapura_to_tpra(conn):
    """One time: the campus "YPJ Tembagapura" is now called "YPJ TPRA" (stored as plain text on users, assets, classrooms)."""
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'campus_tpra_rename_v1'").fetchone():
        return
    changed = 0
    for table in ("users", "assets", "classrooms"):
        changed += conn.execute(f"UPDATE {table} SET campus = 'YPJ TPRA' WHERE campus = 'YPJ Tembagapura'").rowcount
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('campus_tpra_rename_v1', ?)",
                 (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    if changed:
        logger.warning("Renamed campus to YPJ TPRA on %d row(s)", changed)


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


def reset_free_text_owners(conn):
    """One time: owners typed as free text (not a registered user) are cleared to "No owner yet".
    Assets whose owner is linked to a user account are left alone. Each change is written to the ownership log."""
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'free_text_owner_reset_v1'").fetchone():
        return
    ts = datetime.now(timezone.utc).isoformat()
    rows = conn.execute("SELECT id, assigned_to_name FROM assets "
                        "WHERE (assigned_to_user_id IS NULL OR assigned_to_user_id = '') "
                        "AND assigned_to_name IS NOT NULL AND TRIM(assigned_to_name) != ''").fetchall()
    for r in rows:
        conn.execute("INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), r["id"], r["assigned_to_name"], None, "(No owner yet)", None,
                      "Owner cleared: free-text name is not a registered user", "system", "System", ts))
    conn.execute("UPDATE assets SET assigned_to_name = NULL, assigned_to_user_id = NULL "
                 "WHERE (assigned_to_user_id IS NULL OR assigned_to_user_id = '') "
                 "AND assigned_to_name IS NOT NULL AND TRIM(assigned_to_name) != ''")
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('free_text_owner_reset_v1', ?)", (ts,))
    conn.commit()
    if rows:
        logger.warning("Cleared %d free-text asset owner(s) to 'No owner yet'", len(rows))


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
    # Leaders are strictly view-only: refuse every write except signing out.
    if user.get("role") == "leader" and request.method not in ("GET", "HEAD", "OPTIONS") \
            and request.url.path not in LEADER_WRITE_ALLOWED:
        raise HTTPException(403, "Leader accounts are view-only")
    return user


ADMIN_ROLES = ("admin", "super_admin")  # super_admin can do everything an admin can, plus manage admin accounts
ALL_ROLES = ("super_admin", "admin", "campus_admin", "ict_admin", "leader", "staff")
# campus_admin: Admin + ICT Admin for ONE campus (backs up the ICT Admin, manages that campus only). ict_admin / campus_admin are campus-bound.
CAMPUS_BOUND = ("ict_admin", "campus_admin")
# ict_admin: PIC of the ICT-media categories for ONE campus (loans, schedules, hand-over). leader: read-only, sees everything.
ICT_CATEGORIES = ("IT Equipment", "AV Equipment", "Music Equipment")
LEADER_WRITE_ALLOWED = ("/api/auth/logout",)  # leaders are view-only, so they do not sign the policy acknowledgement (see policy_status)


async def admin_required(user: dict = Depends(get_current_user)) -> dict:
    """Every admin screen: Admin, Super Admin and Campus Admin (Campus Admin is held to their own campus where a record has one)."""
    if user.get("role") not in ADMIN_ROLES + ("campus_admin",):
        raise HTTPException(403, "Admin access required")
    return user


async def whole_system_admin_required(user: dict = Depends(get_current_user)) -> dict:
    """Actions that expose every campus at once (the full database backup)."""
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(403, "Admin access required")
    return user


def ensure_campus_scope(user: dict, campus: str):
    """A Campus Admin may only touch records of their own campus; other admins are unrestricted here."""
    if user.get("role") == "campus_admin" and (not (user.get("campus") or "") or (campus or "") != user.get("campus")):
        raise HTTPException(403, "Anda hanya dapat mengelola data kampus Anda sendiri.")


def is_ict_pic(user: dict, campus: str, category: str) -> bool:
    """True when this user may run loans for an asset: super_admin always, ict_admin only for ICT categories on their own campus, campus_admin for any category on their own campus."""
    if user.get("role") == "super_admin":
        return True
    role = user.get("role")
    return (role in CAMPUS_BOUND and (role == "campus_admin" or category in ICT_CATEGORIES)
            and bool(user.get("campus")) and user.get("campus") == (campus or ""))


async def ict_pic_required(user: dict = Depends(get_current_user)) -> dict:
    """Any account that may manage ICT loans (campus/category are checked per record with is_ict_pic)."""
    if user.get("role") not in ("super_admin",) + CAMPUS_BOUND:
        raise HTTPException(403, "ICT Admin access required")
    return user


async def asset_manager_required(user: dict = Depends(get_current_user)) -> dict:
    """Admins and campus-bound admins; every asset is checked with ensure_asset_manager (Admin: non-ICT, Campus/ICT Admin: own campus)."""
    if user.get("role") not in ADMIN_ROLES + CAMPUS_BOUND:
        raise HTTPException(403, "Admin access required")
    return user


def ensure_asset_manager(user: dict, campus: str, category: str):
    role = user.get("role")
    if role == "super_admin" or is_ict_pic(user, campus, category):
        return
    if role == "admin" and category not in ICT_CATEGORIES:   # Admin handles every asset except ICT / media
        return
    raise HTTPException(403, "Akses ditolak: Admin hanya mengelola aset non-ICT; Campus Admin dan ICT Admin hanya di kampusnya sendiri.")


async def report_reader_required(user: dict = Depends(get_current_user)) -> dict:
    """Reports are read-only: admins and leaders (management / foundation) may download them."""
    if user.get("role") not in ADMIN_ROLES + ("leader",):
        raise HTTPException(403, "Akses laporan tidak diizinkan")
    return user


async def user_manager_required(user: dict = Depends(get_current_user)) -> dict:
    """Admins, plus Campus Admins (who may only manage staff / ICT Admin accounts of their own campus)."""
    if user.get("role") not in ADMIN_ROLES + ("campus_admin",):
        raise HTTPException(403, "Admin access required")
    return user


CAMPUS_ADMIN_MANAGES = ("staff", "ict_admin")


def _guard_campus_admin_conn(actor: dict, target, conn):
    try:
        _guard_campus_admin(actor, target["role"], target["campus"])
    except HTTPException:
        conn.close()
        raise


def _guard_campus_admin(actor: dict, role: Optional[str], campus: Optional[str], *, existing: bool = False):
    """A Campus Admin may only create / edit / remove staff and ICT Admin accounts of their own campus."""
    if actor.get("role") != "campus_admin":
        return
    own = (actor.get("campus") or "").strip()
    if not own or (campus or "").strip() != own or (role is not None and role not in CAMPUS_ADMIN_MANAGES):
        raise HTTPException(403, "Campus Admin hanya dapat mengelola akun staff dan ICT Admin di kampusnya sendiri.")


def _transfer_in_scope(conn, user: dict, req) -> bool:
    role = user.get("role")
    if role == "super_admin":
        return True
    a = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (req["asset_id"],)).fetchone()
    if not a:
        return role == "admin"
    if role == "admin":
        return a["category"] not in ICT_CATEGORIES
    return bool((user.get("campus") or "") and a["campus"] == user.get("campus"))


async def super_admin_required(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super Admin access required")
    return user


# ---- Models ----
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["super_admin", "admin", "campus_admin", "ict_admin", "leader", "staff"] = "staff"
    department: Optional[str] = None
    campus: Optional[str] = ""
    supervisor: Optional[str] = ""
    supervisor_name: Optional[str] = ""
    employee_id: Optional[str] = ""
    phone: Optional[str] = ""


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
LOCAL_TZ = timezone(timedelta(hours=9))   # WIT (Papua): both campuses; same wall clock as the scheduler (Asia/Jayapura)
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


def normalize_phone(value) -> str:
    """WhatsApp number as digits with the 62 country code ("0812-3456" -> "628123456"); "" when empty."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    if not digits.startswith("62") or not 10 <= len(digits) <= 15:
        raise HTTPException(400, "Nomor WhatsApp tidak valid (contoh: 0812xxxxxxxx).")
    return digits


def _require_campus_for_ict_admin(role: Optional[str], campus: Optional[str]):
    """ICT Admins and Campus Admins run one campus, so the account must have one."""
    if role in CAMPUS_BOUND and not (campus or "").strip():
        raise HTTPException(400, "ICT Admin dan Campus Admin harus memiliki kampus.")


@api.post("/auth/register")
async def register(body: UserCreate, actor: dict = Depends(user_manager_required)):
    """Creating accounts is an admin action (there is no public sign-up)."""
    _guard_privileged_role(actor, body.role)
    _guard_campus_admin(actor, body.role, body.campus)
    _require_campus_for_ict_admin(body.role, body.campus)
    conn = get_conn()
    email = body.email.lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,phone,password_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, email, body.name, body.role, body.department, body.campus or "", body.supervisor or "", body.supervisor_name or "", body.employee_id or "", normalize_phone(body.phone), hash_password(body.password), now_iso()),
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


# ---- Policy acknowledgement (e-signature) ----
# Bump POLICY_VERSION whenever the policy texts change: every user then has to confirm again.
POLICY_VERSION = "2026.1"


def _norm_name(x: str) -> str:
    return re.sub(r"\s+", " ", (x or "").strip()).casefold()


def policy_status(conn, user: dict) -> dict:
    # Leaders are view-only accounts and cannot write, so they are not asked to sign.
    if user.get("role") == "leader":
        return {"policy_required": False, "policy_accepted": True, "policy_version": POLICY_VERSION, "policy_accepted_at": None}
    row = conn.execute("SELECT accepted_at FROM policy_acceptances WHERE user_id = ? AND policy_version = ? ORDER BY accepted_at DESC LIMIT 1",
                       (user["id"], POLICY_VERSION)).fetchone()
    return {"policy_required": True, "policy_accepted": bool(row), "policy_version": POLICY_VERSION,
            "policy_accepted_at": row["accepted_at"] if row else None}


def ensure_policy_compliant(conn, person_id: str, who: str = "self"):
    """Borrowing and being assigned assets both require the current policies to be confirmed.
    `who`: "self" for the signed-in requester, "other" for a recipient/teacher named by someone else.
    Closes `conn` before raising, like require_user."""
    row = conn.execute("SELECT id, name, role FROM users WHERE id = ?", (person_id,)).fetchone() if person_id else None
    if not row:
        return
    if policy_status(conn, dict(row))["policy_accepted"]:
        return
    conn.close()
    if who == "self":
        raise HTTPException(403, "Anda belum menyetujui kebijakan penggunaan aset. Setujui kebijakan terlebih dahulu sebelum meminjam atau menerima aset.")
    raise HTTPException(403, f"{row['name']} belum menyetujui kebijakan penggunaan aset, sehingga aset belum dapat diserahkan atau dijadwalkan atas nama yang bersangkutan. "
                             "Minta yang bersangkutan login dan menyetujui kebijakan terlebih dahulu.")


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    conn = get_conn()
    try:
        return {**user, **policy_status(conn, user)}
    finally:
        conn.close()


class PolicyAcceptIn(BaseModel):
    version: str
    signed_name: str
    text_hash: str = ""
    lang: str = ""
    read_all: bool = False
    will_comply: bool = False
    accept_sanctions: bool = False


@api.post("/policy/accept")
async def accept_policy(body: PolicyAcceptIn, request: Request, user: dict = Depends(get_current_user)):
    if body.version != POLICY_VERSION:
        raise HTTPException(409, "The policies were updated. Please reload the page and read the new version.")
    if not (body.read_all and body.will_comply and body.accept_sanctions):
        raise HTTPException(400, "All three statements must be confirmed")
    if _norm_name(body.signed_name) != _norm_name(user.get("name", "")):
        raise HTTPException(400, "The typed name must match your account name")
    fwd = request.headers.get("x-forwarded-for", "")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]
    ts = now_iso()
    conn = get_conn()
    conn.execute("""INSERT INTO policy_acceptances
                    (id,user_id,user_email,user_name,signed_name,policy_version,text_hash,lang,ip,user_agent,accepted_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (str(uuid.uuid4()), user["id"], user["email"], user.get("name", ""), body.signed_name.strip()[:200],
                  POLICY_VERSION, body.text_hash[:128], body.lang[:8], ip, request.headers.get("user-agent", "")[:300], ts))
    conn.commit()
    status = policy_status(conn, user)
    conn.close()
    return status


@api.get("/policy/acceptances")
async def list_policy_acceptances(_: dict = Depends(admin_required)):
    """Everyone with their latest acknowledgement, plus whether it covers the current version."""
    conn = get_conn()
    users = conn.execute("SELECT id,name,email,role,campus,department FROM users ORDER BY name").fetchall()
    out = []
    for u in users:
        last = conn.execute("SELECT policy_version, accepted_at, signed_name, ip FROM policy_acceptances WHERE user_id = ? ORDER BY accepted_at DESC LIMIT 1",
                            (u["id"],)).fetchone()
        d = dict(u)
        d["required"] = u["role"] != "leader"
        d["accepted_version"] = last["policy_version"] if last else None
        d["accepted_at"] = last["accepted_at"] if last else None
        d["signed_name"] = last["signed_name"] if last else None
        d["current"] = bool(last) and last["policy_version"] == POLICY_VERSION
        out.append(d)
    conn.close()
    return {"version": POLICY_VERSION, "items": out}


@api.get("/reports/policy-acceptances")
async def report_policy_acceptances(_: dict = Depends(admin_required)):
    import openpyxl
    conn = get_conn()
    rows = conn.execute("SELECT * FROM policy_acceptances ORDER BY accepted_at DESC").fetchall()
    pending = [dict(u) for u in conn.execute("SELECT id,name,email,role,campus FROM users WHERE role != 'leader' AND id NOT IN (SELECT user_id FROM policy_acceptances WHERE policy_version = ?) ORDER BY name", (POLICY_VERSION,)).fetchall()]
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Acknowledgements"
    ws.append(["Accepted at (UTC)", "Name", "Email", "Signed name", "Version", "Language", "Text hash", "IP", "User agent"])
    _style_header(ws)
    for r in rows:
        ws.append([r["accepted_at"], r["user_name"], r["user_email"], r["signed_name"], r["policy_version"], r["lang"], r["text_hash"], r["ip"], r["user_agent"]])
    ws2 = wb.create_sheet(f"Pending v{POLICY_VERSION}")
    ws2.append(["Name", "Email", "Role", "Campus"])
    _style_header(ws2)
    for u in pending:
        ws2.append([u["name"], u["email"], u["role"], u["campus"]])
    return _xlsx_response(wb, f"policy-acknowledgements-{datetime.now().strftime('%Y%m%d')}.xlsx")


# ---- Users ----
@api.get("/users")
async def list_users(user: dict = Depends(get_current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,phone,created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.post("/users")
async def create_user(body: UserCreate, actor: dict = Depends(user_manager_required)):
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
    campuses.update({k: v for k, v in CAMPUS_ALIASES.items()})
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
    ex2 = "Sari Dewi,sari@fmi.com,staff,SMP,YPJ TPRA,,,,"
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
async def invite_user(uid: str, admin: dict = Depends(user_manager_required)):
    conn = get_conn()
    u = conn.execute("SELECT id,name,email,role,campus FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")
    _guard_campus_admin_conn(admin, u, conn)
    res = _send_password_link(conn, dict(u), "invite", INVITE_HOURS)
    conn.close()
    logger.info("Invitation for %s created by %s (sent=%s)", u["email"], admin.get("email"), res["sent"])
    return res


@api.post("/users/{uid}/reset-password")
async def admin_reset_password(uid: str, admin: dict = Depends(user_manager_required)):
    conn = get_conn()
    u = conn.execute("SELECT id,name,email,role,campus FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404, "User not found")
    _guard_campus_admin_conn(admin, u, conn)
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
async def delete_user(uid: str, actor: dict = Depends(user_manager_required)):
    conn = get_conn()
    t = conn.execute("SELECT role, campus FROM users WHERE id = ?", (uid,)).fetchone()
    if t:
        _guard_campus_admin_conn(actor, t, conn)
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
    phone: Optional[str] = None
    password: Optional[str] = None


@api.put("/users/{uid}")
async def update_user(uid: str, body: UserPatch, actor: dict = Depends(user_manager_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    if "role" in updates and updates["role"] not in ALL_ROLES:
        raise HTTPException(400, "Invalid role")
    if "phone" in updates:
        updates["phone"] = normalize_phone(updates["phone"])
    chk = get_conn()
    target = chk.execute("SELECT role, campus FROM users WHERE id = ?", (uid,)).fetchone()
    if target:
        _guard_privileged_role(actor, target["role"], updates.get("role"))
        try:
            _guard_campus_admin(actor, target["role"], target["campus"])
            _guard_campus_admin(actor, updates.get("role", target["role"]), updates.get("campus", target["campus"]))
        except HTTPException:
            chk.close()
            raise
        _require_campus_for_ict_admin(updates.get("role", target["role"]), updates.get("campus", target["campus"]))
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
    row = conn.execute("SELECT id,email,name,role,department,campus,supervisor,supervisor_name,employee_id,phone,created_at FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row)


# ---- File upload ----
LOAN_PHOTO_MAX_BYTES = 50 * 1024   # condition photos of the loan module: at most 50 KB each, one before + one after per unit


def _check_loan_photo_size(data: bytes):
    if len(data) > LOAN_PHOTO_MAX_BYTES:
        raise HTTPException(413, f"Foto kondisi maksimal {LOAN_PHOTO_MAX_BYTES // 1024} KB (ukuran foto ini {len(data) // 1024} KB).")


@api.post("/upload")
async def upload_file(file: UploadFile = File(...), purpose: str = Query(""), user: dict = Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    file_id = str(uuid.uuid4())
    rel_path = f"{user['id']}/{file_id}.{ext}"
    dest = UPLOADS_DIR / user['id']
    dest.mkdir(exist_ok=True)
    full_path = dest / f"{file_id}.{ext}"
    data = await file.read()
    if purpose == "loan":
        _check_loan_photo_size(data)
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
    """(sql_condition, params) limiting an assets query to what this user may see; ("", []) for admins and leaders."""
    if is_admin_user(user) or user.get("role") == "leader":
        return "", []
    campus = (user.get("campus") or "").strip()
    if campus:
        return f"({prefix}campus = ? OR {prefix}assigned_to_user_id = ?)", [campus, user["id"]]
    return f"({prefix}assigned_to_user_id = ?)", [user["id"]]


def can_view_asset(user: dict, asset: dict) -> bool:
    if is_admin_user(user) or user.get("role") == "leader":
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
        "can_transfer": admin or (holder and (asset.get("assignment_kind") or "personal") != "class"),
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
    assets = [row_to_dict(r) for r in rows]
    pend = {r["asset_id"]: {"to_name": r["to_name"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT asset_id, to_name, created_at FROM assignments "
                                  "WHERE status = 'pending' OR (status = 'accepted' AND applied = 0)")}
    conn.close()
    for a in assets:
        a["depreciation"] = calc_depreciation(a["purchase_price"], a["purchase_date"], a.get("useful_life_years", 5), a.get("residual_value") or 0)
        a["pending_assignment"] = pend.get(a["id"])
    return assets


@api.post("/assets")
async def create_asset(body: AssetIn, user: dict = Depends(asset_manager_required)):
    ensure_asset_manager(user, body.campus or "", body.category)
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
    "Vehicles", "Books", "Sports", "Music Equipment",
    "Learning Tools", "ERG / Fire Drill Equipment", "Housekeeping Equipment", "First Aid / AED Equipment", "Other",
]
# Suggested useful life (years) per category. Used when a CSV/Excel import leaves the column empty;
# the New Asset form mirrors this table (frontend/src/pages/AssetFormPage.jsx) - keep them in sync.
DEFAULT_USEFUL_LIFE = {
    "IT Equipment": 4, "AV Equipment": 5, "Furniture": 8, "Lab Equipment": 8, "Vehicles": 8,
    "Books": 5, "Sports": 5, "Music Equipment": 8, "Other": 5,
    "Learning Tools": 5, "ERG / Fire Drill Equipment": 5, "Housekeeping Equipment": 4, "First Aid / AED Equipment": 5,
}
VALID_STATUSES = ["active", "in_repair", "retired", "lost"]
VALID_CAMPUSES = ["YPJ Kuala Kencana", "YPJ TPRA", ""]
# The stored value is "YPJ TPRA"; the campus is also known (and shown in the app, and typed in import files) as "YPJ Tembagapura".
CAMPUS_ALIASES = {"ypj tembagapura": "YPJ TPRA", "tembagapura": "YPJ TPRA", "tpra": "YPJ TPRA"}


def normalize_campus(value) -> str:
    v = (value or "").strip()
    return CAMPUS_ALIASES.get(v.casefold(), v)


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
        errors.append(f'unknown campus "{campus}" (use "YPJ Kuala Kencana" or "YPJ Tembagapura")')

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
        if row.get("campus"):
            row["campus"] = normalize_campus(row["campus"])
        errs = _validate_import_row(row, i, seen_tags)
        tag = (row.get("asset_tag") or "").strip()
        if tag and tag in existing_tags:
            errs.append(f'asset_tag "{tag}" already exists in the database')
        if tag:
            seen_tags.add(tag)
        try:
            ensure_asset_manager(user, (row.get("campus") or "").strip(), (row.get("category") or "").strip())
        except HTTPException as e:
            errs.append(e.detail)
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
    new_assignments, owner_ignored = [], []

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
                None, None,
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
            if owner:  # only a registered user can be the owner, and they must confirm receipt
                to_user = resolve_user(conn, None, owner)
                if to_user:
                    new_assignments.append(create_assignment(
                        conn, row_to_dict(conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()),
                        to_user, "personal", "new", user, note="Bulk import", to_label=owner))
                else:
                    owner_ignored.append({"row": i, "asset_tag": tag, "owner": owner})
            imported += 1
        except Exception as exc:
            skipped += 1
            import_errors.append({"row": i, "errors": [str(exc)]})

    conn.commit()
    conn.close()
    if new_assignments:
        notify_assignees(new_assignments)
    return {"dry_run": False, "imported": imported, "skipped": skipped, "errors": import_errors,
            "pending_confirmation": len(new_assignments), "owner_ignored": owner_ignored}


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
async def update_asset(aid: str, body: AssetUpdate, user: dict = Depends(asset_manager_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    if user["role"] != "super_admin":
        conn = get_conn()
        cur = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (aid,)).fetchone()
        conn.close()
        if not cur:
            raise HTTPException(404, "Asset not found")
        ensure_asset_manager(user, cur["campus"], cur["category"])
        ensure_asset_manager(user, updates.get("campus", cur["campus"]), updates.get("category", cur["category"]))
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
async def delete_asset(aid: str, user: dict = Depends(asset_manager_required)):
    conn = get_conn()
    cur = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (aid,)).fetchone()
    if cur:
        try:
            ensure_asset_manager(user, cur["campus"], cur["category"])
        except HTTPException:
            conn.close()
            raise
    conn.execute("DELETE FROM assets WHERE id = ?", (aid,))
    conn.execute("DELETE FROM ownership_logs WHERE asset_id = ?", (aid,))
    conn.execute("DELETE FROM assignments WHERE asset_id = ?", (aid,))
    conn.execute("DELETE FROM faults WHERE asset_id = ?", (aid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.post("/assets/{aid}/transfer")
async def transfer_asset(aid: str, body: TransferIn, user: dict = Depends(asset_manager_required)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Asset not found")
    asset = row_to_dict(row)
    try:
        ensure_asset_manager(user, asset["campus"], asset["category"])
    except HTTPException:
        conn.close()
        raise
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
async def update_fault(fid: str, body: FaultUpdate, user: dict = Depends(asset_manager_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if user["role"] != "super_admin":
        conn = get_conn()
        fa = conn.execute("SELECT a.campus, a.category FROM faults f JOIN assets a ON a.id = f.asset_id WHERE f.id = ?", (fid,)).fetchone()
        conn.close()
        if not fa:
            raise HTTPException(404, "Fault not found")
        ensure_asset_manager(user, fa["campus"], fa["category"])
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


def _compliance_scope(conn, user: dict, asset_id: Optional[str] = None, cid: Optional[str] = None):
    """A Campus Admin only handles compliance items tied to an asset of their own campus."""
    if user.get("role") != "campus_admin":
        return
    own = conn is None
    conn = conn or get_conn()
    if cid:
        row = conn.execute("SELECT asset_id FROM compliance WHERE id = ?", (cid,)).fetchone()
        asset_id = row["asset_id"] if row else None
        if not row:
            conn.close() if own else None
            return
    a = conn.execute("SELECT campus FROM assets WHERE id = ?", (asset_id,)).fetchone() if asset_id else None
    if own:
        conn.close()
    if not a:
        raise HTTPException(403, "Campus Admin hanya dapat mengelola kepatuhan untuk aset di kampusnya.")
    ensure_campus_scope(user, a["campus"])


@api.post("/compliance")
async def create_compliance(body: ComplianceIn, user: dict = Depends(admin_required)):
    conn = get_conn()
    _compliance_scope(conn, user, body.asset_id)
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
async def update_compliance(cid: str, body: ComplianceUpdate, user: dict = Depends(admin_required)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    _compliance_scope(None, user, cid=cid)
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
async def delete_compliance(cid: str, user: dict = Depends(admin_required)):
    _compliance_scope(None, user, cid=cid)
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
    asset = conn.execute("SELECT id, name, asset_tag, assigned_to_name, assigned_to_user_id, assignment_kind FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not asset:
        conn.close()
        raise HTTPException(404, "Asset not found")
    if not is_admin_user(user) and asset["assignment_kind"] == "class":
        conn.close()
        raise HTTPException(403, "Aset kelas hanya dapat dipindahkan oleh Admin lewat serah terima kelas.")
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
    if user["role"] in ADMIN_ROLES + ("campus_admin",):
        base = "SELECT * FROM transfer_requests"
        rows = conn.execute(base + (" WHERE status = ?" if status else "") + " ORDER BY created_at DESC",
                            ([status] if status else [])).fetchall()
        rows = [r for r in rows if _transfer_in_scope(conn, user, r)]
    else:
        rows = conn.execute(
            "SELECT * FROM transfer_requests WHERE requested_by = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.get("/transfer-requests/pending-count")
async def pending_count(user: dict = Depends(user_manager_required)):
    conn = get_conn()
    n = sum(1 for r in conn.execute("SELECT asset_id FROM transfer_requests WHERE status = 'pending'").fetchall()
            if _transfer_in_scope(conn, user, r))
    conn.close()
    return {"count": n}


@api.put("/transfer-requests/{rid}/approve")
async def approve_transfer(rid: str, user: dict = Depends(user_manager_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM transfer_requests WHERE id = ?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Request not found")
    if not _transfer_in_scope(conn, user, req):
        conn.close()
        raise HTTPException(403, "Permintaan ini bukan untuk kampus Anda")
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
async def reject_transfer(rid: str, reason: Optional[str] = None, user: dict = Depends(user_manager_required)):
    conn = get_conn()
    req = conn.execute("SELECT * FROM transfer_requests WHERE id = ?", (rid,)).fetchone()
    if not req:
        conn.close()
        raise HTTPException(404, "Request not found")
    if not _transfer_in_scope(conn, user, req):
        conn.close()
        raise HTTPException(403, "Permintaan ini bukan untuk kampus Anda")
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
    r = conn.execute("SELECT * FROM assignments WHERE asset_id = ? AND (status = 'pending' OR (status = 'accepted' AND applied = 0))",
                     (asset_id,)).fetchone()
    return dict(r) if r else None


def create_assignment(conn, asset: dict, to_user: dict, kind: str, source: str, by_user: dict,
                      note: str = "", batch_id: str = None, to_label: str = None,
                      transfer_request_id: str = None) -> dict:
    """Insert a pending assignment (caller commits). Raises ValueError('pending'|'same_holder')."""
    ensure_policy_compliant(conn, to_user["id"], "other")   # nobody receives assets before confirming the policies
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
        "UPDATE assets SET assigned_to_name=?, assigned_to_user_id=?, assignment_kind=?, handover_flag='', updated_at=? WHERE id=?",
        (label, a["to_user_id"], a["kind"], ts, a["asset_id"]))
    if a["kind"] == "class" and (asset.get("location") or "").strip():
        # first confirmed class holder of a room that has no responsible teacher yet becomes its responsible teacher
        conn.execute("""UPDATE classrooms SET responsible_user_id=?, responsible_name=?, updated_at=? WHERE campus=? AND LOWER(name)=? AND responsible_user_id IS NULL""",
                     (a["to_user_id"], a["to_name"], ts, asset.get("campus") or "", _room_key(asset["location"])))


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


def _assignment_request_html(to_name: str, items: list, by_name: str, note: str = "", reminder: bool = False,
                             room_name: str = None) -> str:
    import html as _h
    n = len(items)
    what = f"serah terima kelas <strong>{_h.escape(room_name)}</strong>" if room_name else "serah terima aset"
    lead = (f"Pengingat: ada {what} yang <strong>belum Anda periksa</strong>." if reminder and room_name else
            "Pengingat: ada serah terima aset yang <strong>belum Anda konfirmasi</strong>." if reminder else
            f"<strong>{_h.escape(by_name)}</strong> menunjuk Anda sebagai penanggung jawab kelas <strong>{_h.escape(room_name)}</strong> ({n} aset)." if room_name else
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
          Jika ada yang tidak sesuai (tidak ada / rusak), tekan <strong>Tolak</strong> dan tulis alasannya.
          {'Penanggung jawab kelas baru berlaku setelah <strong>semua aset</strong> diperiksa; sebelum itu guru sebelumnya tetap bertanggung jawab.' if room_name else ''}
        </div>""", eyebrow="Serah terima kelas" if room_name else "Serah terima aset", cta_label="Tinjau & konfirmasi", cta_url=f"{APP_URL}/my-assets")


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
            room_name = None
            if group[0].get("source") == "class_handover":
                hr = conn.execute("SELECT classroom_name FROM classroom_handovers WHERE id = ?", (group[0]["batch_id"],)).fetchone()
                room_name = hr["classroom_name"] if hr else None
                if room_name:
                    subject = (f"[YPJ Assets] {'Pengingat: ' if reminder else ''}Serah terima kelas {room_name} — periksa {n} aset")
            cc = _supervisor_cc(conn, [uid] + [a.get("from_user_id") for a in group], exclude=[email])
            send_email(email, subject,
                       _assignment_request_html(name, group, by, group[0].get("note") or "", reminder, room_name), cc=cc)
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
        try:
            ensure_asset_manager(user, asset["campus"], asset["category"])
        except HTTPException:
            skipped.append({"asset_id": aid, "name": asset["name"], "reason": "forbidden"}); continue
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
    done, errors, class_batches = [], [], []
    for rid in dict.fromkeys(body.ids):
        r = conn.execute("SELECT * FROM assignments WHERE id = ?", (rid,)).fetchone()
        if not r:
            errors.append({"id": rid, "error": "not_found"}); continue
        a = dict(r)
        if a["to_user_id"] != user["id"]:
            errors.append({"id": rid, "error": "not_recipient"}); continue
        if a["status"] != "pending":
            errors.append({"id": rid, "error": "not_pending"}); continue
        is_class = a.get("source") == "class_handover"
        if body.action == "accept":
            if is_class:  # takes effect when the whole class hand-over is checked
                conn.execute("UPDATE assignments SET status='accepted', responded_at=?, applied=0 WHERE id=?", (ts, rid))
            else:
                apply_assignment(conn, a, ts)
                conn.execute("UPDATE assignments SET status='accepted', responded_at=? WHERE id=?", (ts, rid))
        else:
            conn.execute("UPDATE assignments SET status='rejected', responded_at=?, reject_reason=? WHERE id=?",
                         (ts, reason, rid))
            if is_class:
                conn.execute("UPDATE assets SET handover_flag='discrepancy', updated_at=? WHERE id=?", (ts, a["asset_id"]))
        if is_class:
            class_batches.append(a["batch_id"])
        else:
            done.append(a)
    finished = finish_class_handovers(conn, class_batches)
    conn.commit()
    conn.close()
    if done:
        notify_responses(done, body.action == "accept", user["name"], reason)
    if finished:
        notify_class_handover_done(finished)
    return {"done": len(done) + len(class_batches), "errors": errors}


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
    finished = finish_class_handovers(conn, [a["batch_id"]]) if a.get("source") == "class_handover" else []
    conn.commit()
    conn.close()
    if finished:
        notify_class_handover_done(finished)
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
async def report_asset_inventory(_: dict = Depends(report_reader_required)):
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
async def report_depreciation(_: dict = Depends(report_reader_required)):
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
async def report_fully_depreciated(_: dict = Depends(report_reader_required)):
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
async def report_faults(_: dict = Depends(report_reader_required)):
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
async def report_compliance(_: dict = Depends(report_reader_required)):
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
async def report_ownership(_: dict = Depends(report_reader_required)):
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
async def backup_db(user: dict = Depends(whole_system_admin_required)):
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
    ensure_policy_compliant(conn, user["id"])
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
        _check_loan_photo_size(data)
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
        _check_loan_photo_size(data)
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


# ===================================================================
# Loans module (ICT media): request -> ICT decision -> hand-over -> return
# ===================================================================
# Rules and state changes live in booking_engine.py; this section is the HTTP layer, permissions and e-mails.
def can_manage_loan(user: dict, campus: str, category: str) -> bool:
    """Who confirms requests and runs hand-over / return: super_admin; the campus ICT Admin for ICT categories;
    regular admins for every other category."""
    role = user.get("role")
    if role == "super_admin":
        return True
    if category in ICT_CATEGORIES:
        return is_ict_pic(user, campus, category)
    return role == "admin" or is_ict_pic(user, campus, category)


def loan_manager_emails(conn, campus: str, category: str) -> list:
    if category in ICT_CATEGORIES:
        rows = conn.execute("SELECT email FROM users WHERE role IN ('ict_admin', 'campus_admin') AND campus = ?", (campus,)).fetchall()
    else:
        rows = conn.execute("SELECT email FROM users WHERE (role = 'admin' AND campus IN (?, '')) OR (role = 'campus_admin' AND campus = ?)", (campus, campus)).fetchall()
    emails = [r["email"] for r in rows]
    if LOAN_NOTIFY_EMAIL:
        emails.append(LOAN_NOTIFY_EMAIL)
    return list(dict.fromkeys(emails))


def queue_email(conn, to_addr: str, subject: str, body_html: str, kind: str, ref_id: str, cc: list = None):
    """Record the notification, try to send it now and keep the outcome (so a WhatsApp channel can be added later)."""
    if not to_addr:
        return
    qid = str(uuid.uuid4())
    conn.execute("INSERT INTO notification_queue (id, channel, to_addr, subject, body, kind, ref_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                 (qid, "email", to_addr, subject, body_html, kind, ref_id, now_iso()))
    conn.commit()
    try:
        ok = send_email(to_addr, subject, body_html, cc=cc)
        conn.execute("UPDATE notification_queue SET status = ?, sent_at = ? WHERE id = ?", ("sent" if ok else "failed", now_iso(), qid))
    except Exception as exc:  # never let a mail problem break a loan action
        logger.warning("Loan e-mail failed: %s", exc)
        conn.execute("UPDATE notification_queue SET status = 'failed', error = ? WHERE id = ?", (str(exc)[:300], qid))
    conn.commit()
    # same message by WhatsApp when the person has a number on file
    phone = conn.execute("SELECT phone FROM users WHERE LOWER(email) = LOWER(?)", (to_addr,)).fetchone()
    if phone and phone["phone"]:
        try:
            queue_whatsapp(conn, phone["phone"], subject, body_html, kind, ref_id)
        except Exception as exc:
            logger.warning("Loan WhatsApp failed: %s", exc)


LOAN_STATUS_ID = {
    "submitted": "Diajukan", "pending_supervisor": "Menunggu Supervisor", "pending_ict": "Menunggu Konfirmasi ICT",
    "approved": "Disetujui", "partially_approved": "Disetujui Sebagian", "rejected": "Ditolak", "in_use": "Sedang Digunakan",
    "completed": "Selesai", "cancelled": "Dibatalkan", "overdue": "Terlambat", "problem": "Bermasalah",
}


def _loan_mail(b: dict, asset: dict, heading: str, extra: list, footer: str) -> str:
    lines = [("No. Pengajuan", b["number"]), ("Aset", f'{asset.get("name", "")} ({asset.get("asset_tag", "")})'),
             ("Pemohon", b["requester_name"]), ("Mulai", b["start_at"].replace("T", " ")),
             ("Selesai", b["end_at"].replace("T", " ")), ("Status", LOAN_STATUS_ID.get(b["status"], b["status"]))] + extra
    return _loan_html(b, heading, lines, footer)


def _loan_context(conn, bid: str):
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    if not b:
        raise HTTPException(404, "Pengajuan tidak ditemukan")
    b = dict(b)
    a = conn.execute("SELECT id, name, asset_tag, category, campus, location, brand, model, serial_number, status FROM assets WHERE id = ?",
                     (b["asset_id"],)).fetchone() if b["asset_id"] else None
    if a:
        return b, dict(a)
    if b["kind"] == "pool":
        label = booking_engine.pool_label(b["device_type"])
        return b, {"name": f'{b["units_requested"]} × {label}', "asset_tag": "pool", "category": b["category"], "campus": b["campus"],
                   "location": "", "is_pool": True}
    r = conn.execute("SELECT name, kind, category, campus, location FROM resources WHERE id = ?", (b["resource_id"],)).fetchone() if b["resource_id"] else None
    # a cart / lab loan reads like an asset in titles and e-mails
    return b, ({"name": r["name"], "asset_tag": r["kind"], "category": r["category"], "campus": r["campus"], "location": r["location"], "is_resource": True} if r else {})


def _loan_visible(user: dict, b: dict) -> bool:
    return (user.get("role") == "leader" or b["requester_id"] == user["id"] or b.get("supervisor_id") == user["id"]
            or can_manage_loan(user, b["campus"], b["category"]))


def _loan_view(conn, user: dict, b: dict, asset: dict) -> dict:
    import json as _json
    out = dict(b)
    out["status_label"] = LOAN_STATUS_ID.get(b["status"], b["status"])
    out["asset"] = asset
    units = []
    for r in conn.execute("SELECT * FROM booking_units WHERE booking_id = ? ORDER BY out_at", (b["id"],)).fetchall():
        u = dict(r)
        for k in ("out_check", "in_check"):
            try:
                u[k] = _json.loads(u[k] or "{}")
            except ValueError:
                u[k] = {}
        a = conn.execute("SELECT name, asset_tag, serial_number FROM assets WHERE id = ?", (u["asset_id"],)).fetchone()
        u["asset_name"], u["asset_tag"], u["serial_number"] = (a["name"], a["asset_tag"], a["serial_number"]) if a else ("", "", "")
        units.append(u)
    out["units"] = units
    out["accessories"] = booking_engine.accessory_names(conn, b["asset_id"]) if b["asset_id"] else []
    if b["resource_id"]:
        out["units_out"] = sum(1 for u in units if u["status"] == "out")
        out["units_not_returned"] = out["units_out"] if b["status"] == "overdue" else 0
        out["cart_units"] = booking_engine.resource_units(conn, b["resource_id"])
    elif b["kind"] == "pool":
        out["units_out"] = sum(1 for u in units if u["status"] == "out")
        out["units_not_returned"] = out["units_out"] if b["status"] == "overdue" else 0
        out["device_label"] = booking_engine.pool_label(b["device_type"])
        # what is still to be handed over: the units ICT reserved when approving
        out["cart_units"] = [{"id": u["asset_id"], "name": u["asset_name"], "asset_tag": u["asset_tag"]} for u in units if u["status"] == "reserved"]
    manage = can_manage_loan(user, b["campus"], b["category"])
    out["permissions"] = {
        "can_decide": manage and b["status"] == "pending_ict",
        "can_check_out": manage and b["status"] in ("approved", "partially_approved"),
        "can_check_in": manage and b["status"] in ("in_use", "overdue"),
        "can_cancel": (b["requester_id"] == user["id"] or manage) and b["status"] in (*booking_engine.PENDING_STATUSES, "approved", "partially_approved"),
        "can_supervise": b["supervisor_id"] == user["id"] and b["status"] == "pending_supervisor",
        "can_manage": manage,
    }
    return out


class LoanIn(BaseModel):
    asset_id: Optional[str] = None            # a single item ...
    resource_id: Optional[str] = None         # ... or units of a cart / lab outside the fixed schedule
    device_type: Optional[str] = None         # ... or "N laptops / iPads": ICT picks the exact units when approving
    units: int = Field(1, ge=1)
    date: Optional[str] = None                # with period_from/period_to instead of start_at/end_at
    period_from: Optional[int] = None
    period_to: Optional[int] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    purpose: str = ""
    class_name: str = ""
    subject: str = ""
    use_location: str = ""
    note: str = ""
    take_home: bool = False
    terms_accepted: bool = False
    override_reason: str = ""


def _engine_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except booking_engine.BookingError as e:
        raise HTTPException(409 if e.code in ("conflict", "state", "already_out", "overdue") else 400, e.message)


def _local_now() -> datetime:
    """Campus-local wall clock (WIT, UTC+9), same as the scheduler. Bookings are stored in campus-local time."""
    return datetime.now(LOCAL_TZ).replace(tzinfo=None, second=0, microsecond=0)


@api.get("/loans/assets")
async def loan_catalog(user: dict = Depends(get_current_user), search: Optional[str] = None, category: Optional[str] = None,
                       campus: Optional[str] = None):
    """Borrowable assets with their live state (available / on loan / repair / lost)."""
    conn = get_conn()
    conds, params = ["s.borrowable = 1", "a.status != 'retired'"], []
    own_campus = (user.get("campus") or "").strip()
    if user["role"] in ("staff",) + CAMPUS_BOUND and own_campus:
        conds.append("a.campus = ?"); params.append(own_campus)
    elif campus:
        conds.append("a.campus = ?"); params.append(campus)
    if category:
        conds.append("a.category = ?"); params.append(category)
    if search:
        conds.append("(a.name LIKE ? OR a.asset_tag LIKE ? OR a.brand LIKE ? OR a.model LIKE ?)"); params += [f"%{search}%"] * 4
    rows = conn.execute(f"""SELECT a.id, a.name, a.asset_tag, a.category, a.campus, a.location, a.brand, a.model, a.status, a.photo_path,
                                   s.loan_type, s.storage_slot FROM assets a JOIN asset_loan_settings s ON s.asset_id = a.id
                            WHERE {' AND '.join(conds)} ORDER BY a.category, a.name""", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        loan = conn.execute("""SELECT b.number, b.requester_name, b.end_at FROM booking_units u JOIN bookings b ON b.id = u.booking_id
                               WHERE u.asset_id = ? AND u.status = 'out' LIMIT 1""", (d["id"],)).fetchone()
        d["on_loan"] = dict(loan) if loan else None
        d["state"] = ("repair" if d["status"] == "in_repair" else "lost" if d["status"] == "lost" else
                      "on_loan" if loan else "available" if d["status"] == "active" else "inactive")
        d["policy"] = booking_engine.get_policy(conn, d["campus"], d["category"], d["id"])
        out.append(d)
    conn.close()
    return out


@api.get("/loans/availability")
async def loan_availability(asset_id: str, start_at: str, end_at: str, _: dict = Depends(get_current_user)):
    conn = get_conn()
    try:
        reason = booking_engine.asset_block_reason(conn, asset_id)
        start, end = booking_engine.parse_dt(start_at), booking_engine.parse_dt(end_at)
        info = booking_engine.check_availability(conn, asset_id=asset_id, units=1, start=start, end=end)
    except booking_engine.BookingError as e:
        conn.close()
        raise HTTPException(400, e.message)
    conn.close()
    return {**info, "blocked": reason}


@api.get("/loans/pool/availability")
async def pool_availability(device_type: str, start_at: str, end_at: str, campus: Optional[str] = None, user: dict = Depends(get_current_user)):
    """How many laptops / iPads are free for a window (teachers see the count, ICT also the units)."""
    own = (user.get("campus") or "").strip()
    campus = own if (user["role"] in ("staff",) + CAMPUS_BOUND and own) else (campus or own)
    conn = get_conn()
    try:
        start, end = booking_engine.parse_dt(start_at), booking_engine.parse_dt(end_at)
        free = booking_engine.pool_free_units(conn, campus, device_type, start, end)
        policy = booking_engine.get_policy(conn, campus, booking_engine.POOL_CATEGORY)
    except booking_engine.BookingError as e:
        conn.close()
        raise HTTPException(400, e.message)
    conn.close()
    return {"device_type": device_type, "label": booking_engine.pool_label(device_type), "free": len(free),
            "max_units": int(policy.get("max_units") or 10)}


@api.get("/loans/{bid}/candidates")
async def pool_candidates(bid: str, start_at: Optional[str] = None, end_at: Optional[str] = None, user: dict = Depends(get_current_user)):
    """For ICT: the units that can still be lent for this request's window (plus the ones already reserved)."""
    conn = get_conn()
    b, _ = _loan_context(conn, bid)
    if not can_manage_loan(user, b["campus"], b["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus dan kategori ini")
    if b["kind"] != "pool":
        conn.close()
        raise HTTPException(400, "Pilih unit hanya untuk permintaan laptop/iPad per jenis.")
    try:   # ICT may be looking at a changed window while deciding
        win = (booking_engine.parse_dt(start_at or b["start_at"]), booking_engine.parse_dt(end_at or b["end_at"]))
    except booking_engine.BookingError as e:
        conn.close()
        raise HTTPException(400, e.message)
    free = booking_engine.pool_free_units(conn, b["campus"], b["device_type"], win[0], win[1], bid)
    reserved = [r["asset_id"] for r in conn.execute("SELECT asset_id FROM booking_units WHERE booking_id = ? AND status = 'reserved'", (bid,))]
    conn.close()
    return {"units": free, "reserved": reserved, "units_requested": b["units_requested"], "label": booking_engine.pool_label(b["device_type"])}


@api.post("/loans")
async def create_loan(body: LoanIn, user: dict = Depends(get_current_user)):
    if body.device_type:
        if body.asset_id or body.resource_id:
            raise HTTPException(400, "Pilih jenis perangkat saja, atau satu aset/cart tertentu.")
    elif bool(body.asset_id) == bool(body.resource_id):
        raise HTTPException(400, "Pilih satu aset atau satu cart/lab.")
    if user["role"] not in ADMIN_ROLES + CAMPUS_BOUND + ("staff",):
        raise HTTPException(403, "Akun ini tidak dapat mengajukan peminjaman")
    conn = get_conn()
    ensure_policy_compliant(conn, user["id"])
    if body.device_type:
        if body.device_type not in booking_engine.POOL_TYPES:
            conn.close()
            raise HTTPException(400, "Jenis perangkat harus laptop atau ipad.")
        campus = (user.get("campus") or "").strip()
        if not campus:
            conn.close()
            raise HTTPException(400, "Akun Anda belum memiliki kampus. Hubungi admin.")
        target = {"campus": campus, "category": booking_engine.POOL_CATEGORY, "kind": "pool", "asset_id": None, "resource_id": None}
        info = {"name": f"{body.units} × {booking_engine.pool_label(body.device_type)}", "asset_tag": "pool",
                "category": booking_engine.POOL_CATEGORY, "campus": campus}
    elif body.asset_id:
        a = conn.execute("SELECT * FROM assets WHERE id = ?", (body.asset_id,)).fetchone()
        if not a:
            conn.close()
            raise HTTPException(404, "Aset tidak ditemukan")
        target = {"campus": a["campus"], "category": a["category"], "kind": "item", "asset_id": a["id"], "resource_id": None}
        info = dict(a)
    else:
        r = conn.execute("SELECT * FROM resources WHERE id = ? AND active = 1", (body.resource_id,)).fetchone()
        if not r:
            conn.close()
            raise HTTPException(404, "Cart/lab tidak ditemukan")
        target = {"campus": r["campus"], "category": r["category"], "kind": "off_schedule", "asset_id": None, "resource_id": r["id"]}
        info = {"name": r["name"], "asset_tag": r["kind"], "category": r["category"], "campus": r["campus"]}
    manage = can_manage_loan(user, target["campus"], target["category"])
    if not manage and (user.get("campus") or "") != target["campus"]:
        conn.close()
        raise HTTPException(403, "Aset ini bukan di kampus Anda." if body.asset_id else "Cart/lab ini bukan di kampus Anda.")
    # time window: lesson periods of one day, or free start/end
    start_at, end_at = body.start_at, body.end_at
    if body.date and body.period_from:
        try:
            t_from, t_to = booking_engine.period_times(conn, target["campus"], body.period_from, body.period_to or body.period_from)
        except booking_engine.BookingError as e:
            conn.close()
            raise HTTPException(400, e.message)
        start_at, end_at = f"{body.date}T{t_from}", f"{body.date}T{t_to}"
    if not start_at or not end_at:
        conn.close()
        raise HTTPException(400, "Isi waktu mulai dan selesai, atau pilih tanggal dan jam pelajaran.")
    if (body.resource_id or body.device_type) and body.take_home:
        conn.close()
        raise HTTPException(400, "Laptop/iPad/Lab tidak dapat dibawa keluar sekolah.")
    supervisor_id = None
    if body.take_home:
        sup = user.get("supervisor") or ""
        row = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (sup.lower(),)).fetchone() if sup else None
        if not row:
            conn.close()
            raise HTTPException(400, "Supervisor Anda belum terdaftar di aplikasi. Hubungi admin untuk melengkapi data supervisor.")
        supervisor_id = row["id"]
    override = bool(body.override_reason.strip())
    if override and not manage:
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT yang dapat mengecualikan aturan.")
    data = {"campus": target["campus"], "kind": target["kind"], "asset_id": target["asset_id"], "resource_id": target["resource_id"],
            "category": target["category"], "requester_id": user["id"], "requester_name": user["name"], "start_at": start_at, "end_at": end_at,
            "units": body.units if (body.resource_id or body.device_type) else 1, "device_type": body.device_type or "",
            "class_name": body.class_name, "subject": body.subject, "purpose": body.purpose,
            "use_location": body.use_location, "note": body.note, "take_home": body.take_home, "supervisor_id": supervisor_id,
            "terms_accepted": body.terms_accepted}
    try:
        b = booking_engine.reserve(conn, data=data, now=_local_now(), override=override, override_reason=body.override_reason)
    except booking_engine.BookingError as e:
        conn.close()
        raise HTTPException(409 if e.code in ("conflict", "overdue") else 400, e.message)
    warnings = b.pop("warnings", [])
    a = info
    detail = [("Keperluan", b["purpose"] or "—")] + ([("Jumlah unit", str(b["units_requested"]))] if (body.resource_id or body.device_type) else [])
    queue_email(conn, user["email"], f'[YPJ Assets] Pengajuan {b["number"]}: {a["name"]}',
                _loan_mail(b, a, "Pengajuan Peminjaman Diterima", detail,
                           "<p>Pengajuan Anda telah diterima" + (" dan menunggu persetujuan supervisor." if b["status"] == "pending_supervisor"
                           else " dan menunggu konfirmasi Admin ICT." if b["status"] == "pending_ict" else " dan sudah disetujui.") + "</p>"),
                "loan_submitted", b["id"])
    if b["status"] == "pending_supervisor":
        sup = conn.execute("SELECT email FROM users WHERE id = ?", (b["supervisor_id"],)).fetchone()
        if sup:
            queue_email(conn, sup["email"], f'[YPJ Assets] Persetujuan diperlukan: {b["number"]}',
                        _loan_mail(b, a, "Permintaan Bawa Pulang", detail,
                                   f'<p>{b["requester_name"]} meminta membawa aset ini keluar sekolah. Mohon beri keputusan di aplikasi YPJ Assets.</p>'),
                        "loan_supervisor", b["id"])
    elif b["status"] == "pending_ict":
        for addr in loan_manager_emails(conn, target["campus"], target["category"]):
            queue_email(conn, addr, f'[YPJ Assets] Pengajuan baru {b["number"]}: {a["name"]}',
                        _loan_mail(b, a, "Pengajuan Menunggu Konfirmasi", detail, "<p>Mohon konfirmasi di aplikasi YPJ Assets.</p>"),
                        "loan_new", b["id"])
    view = _loan_view(conn, user, b, a)
    view["warnings"] = warnings
    conn.close()
    return view


POOL_NAME_SQL = ("CASE WHEN b.kind = 'pool' THEN b.units_requested || ' × ' || "
                 "CASE b.device_type WHEN 'ipad' THEN 'iPad' WHEN 'laptop' THEN 'Laptop' ELSE b.device_type END END")


@api.get("/loans")
async def list_loans(user: dict = Depends(get_current_user), scope: str = "mine", status: Optional[str] = None, campus: Optional[str] = None):
    """scope=mine: my requests; scope=manage: what I may decide on (ICT / admin); scope=all: everything (leader, super admin)."""
    conn = get_conn()
    conds, params = [], []
    if scope == "all":
        if user["role"] not in ("leader", "super_admin"):
            conn.close()
            raise HTTPException(403, "Tidak diizinkan")
    elif scope == "manage":
        if user["role"] == "super_admin":
            pass
        elif user["role"] == "campus_admin":
            conds.append("b.campus = ?"); params.append(user.get("campus") or "")
        elif user["role"] in CAMPUS_BOUND:
            conds += ["b.campus = ?", f"b.category IN ({','.join('?' * len(ICT_CATEGORIES))})"]; params += [user.get("campus") or "", *ICT_CATEGORIES]
        elif user["role"] == "admin":
            conds.append(f"b.category NOT IN ({','.join('?' * len(ICT_CATEGORIES))})"); params += list(ICT_CATEGORIES)
        else:
            conn.close()
            raise HTTPException(403, "Tidak diizinkan")
    else:
        conds.append("(b.requester_id = ? OR b.supervisor_id = ?)"); params += [user["id"], user["id"]]
    if status:
        conds.append("b.status = ?"); params.append(status)
    if campus:
        conds.append("b.campus = ?"); params.append(campus)
    booking_engine.mark_overdue(conn, _local_now())
    rows = conn.execute(f"""SELECT b.*, COALESCE(a.name, r.name, {POOL_NAME_SQL}) AS asset_name, COALESCE(a.asset_tag, r.kind, CASE WHEN b.kind = 'pool' THEN 'pool' END) AS asset_tag
                            FROM bookings b LEFT JOIN assets a ON a.id = b.asset_id LEFT JOIN resources r ON r.id = b.resource_id
                            {'WHERE ' + ' AND '.join(conds) if conds else ''} ORDER BY b.created_at DESC LIMIT 500""", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["status_label"] = LOAN_STATUS_ID.get(d["status"], d["status"])
        out.append(d)
    conn.close()
    return out


@api.get("/loans/pending-count")
async def loans_pending_count(user: dict = Depends(get_current_user)):
    conn = get_conn()
    booking_engine.mark_overdue(conn, _local_now())
    mine = conn.execute("SELECT COUNT(*) FROM bookings WHERE supervisor_id = ? AND status = 'pending_supervisor'", (user["id"],)).fetchone()[0]
    manage = 0
    if user["role"] in ("super_admin", "admin") + CAMPUS_BOUND:
        rows = conn.execute("SELECT campus, category FROM bookings WHERE status IN ('pending_ict', 'overdue')").fetchall()
        manage = sum(1 for r in rows if can_manage_loan(user, r["campus"], r["category"]))
    conn.close()
    return {"count": mine + manage, "supervisor": mine, "manage": manage}


class PolicyIn(BaseModel):
    campus: str = ""
    category: str
    max_loan_days: int = Field(3, ge=1)
    requires_approval: bool = True
    can_leave_campus: bool = False
    min_notice_days: int = Field(1, ge=0)
    max_advance_days: int = Field(14, ge=1)
    max_units: int = Field(10, ge=1)          # most laptops / iPads one request may ask for


@api.get("/loans/policies")
async def list_loan_policies(_: dict = Depends(get_current_user)):
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM loan_policies ORDER BY category, campus").fetchall()]
    conn.close()
    return rows


@api.put("/loans/policies")
async def put_loan_policy(body: PolicyIn, user: dict = Depends(get_current_user)):
    """Rules per category (campus '' = every campus). ICT Admin may set them for their own campus."""
    if body.campus and body.campus not in [c for c in VALID_CAMPUSES if c]:
        raise HTTPException(400, "Kampus tidak valid")
    if not (user["role"] in ADMIN_ROLES or (user["role"] in CAMPUS_BOUND and (user["role"] == "campus_admin" or body.category in ICT_CATEGORIES)
                                            and body.campus and body.campus == user.get("campus"))):
        raise HTTPException(403, "Tidak diizinkan mengubah aturan ini")
    conn = get_conn()
    conn.execute("""INSERT INTO loan_policies (id, campus, category, max_loan_days, requires_approval, can_leave_campus, min_notice_days,
                    max_advance_days, max_units) VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(campus, category) DO UPDATE SET max_loan_days = excluded.max_loan_days,
                    requires_approval = excluded.requires_approval, can_leave_campus = excluded.can_leave_campus,
                    min_notice_days = excluded.min_notice_days, max_advance_days = excluded.max_advance_days,
                    max_units = excluded.max_units""",
                 (str(uuid.uuid4()), body.campus, body.category, body.max_loan_days, int(body.requires_approval),
                  int(body.can_leave_campus), body.min_notice_days, body.max_advance_days, body.max_units))
    conn.commit()
    row = dict(conn.execute("SELECT * FROM loan_policies WHERE campus = ? AND category = ?", (body.campus, body.category)).fetchone())
    conn.close()
    return row


# ---- Carts / labs, school periods, holidays, fixed schedules (phase 2) ----
def can_setup_campus(user: dict, campus: str) -> bool:
    """Periods and holidays belong to a campus: its ICT Admin, any admin and the super admin set them up."""
    role = user.get("role")
    if role in ADMIN_ROLES:
        return True
    return role in CAMPUS_BOUND and bool(user.get("campus")) and user.get("campus") == campus


def _visible_campuses(user: dict, campus: Optional[str]) -> list:
    """Campuses a reader may look at. Staff and ICT Admins see their own campus; admins, leaders and the super admin any."""
    own = (user.get("campus") or "").strip()
    if user["role"] in ("staff",) + CAMPUS_BOUND and own:
        return [own]
    if campus:
        return [campus]
    return [c for c in VALID_CAMPUSES if c]


def _resource_or_404(conn, rid: str) -> dict:
    r = conn.execute("SELECT * FROM resources WHERE id = ?", (rid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "Cart/lab tidak ditemukan")
    return dict(r)


def _guard_resource_read(conn, user: dict, res: dict):
    if res["campus"] not in _visible_campuses(user, res["campus"]):
        conn.close()
        raise HTTPException(403, "Cart/lab ini bukan di kampus Anda")


def _resource_view(conn, r) -> dict:
    d = dict(r)
    d["unit_count"] = len(booking_engine.resource_units(conn, d["id"], active_only=False))
    d["effective_capacity"] = booking_engine.resource_capacity(conn, d["id"])
    return d


class ResourceIn(BaseModel):
    campus: str
    name: str = Field(..., min_length=1)
    kind: Literal["laptop_cart", "ipad_cart", "computer_lab", "room"] = "laptop_cart"
    category: str = "IT Equipment"
    capacity: int = Field(1, ge=1)
    location: str = ""
    active: bool = True


@api.get("/loans/resources")
async def list_resources(user: dict = Depends(get_current_user), campus: Optional[str] = None):
    conn = get_conn()
    camps = _visible_campuses(user, campus)
    rows = conn.execute(f"SELECT * FROM resources WHERE campus IN ({','.join('?' * len(camps))}) ORDER BY campus, name", camps).fetchall()
    out = [_resource_view(conn, r) for r in rows]
    conn.close()
    return out


@api.post("/loans/resources")
async def create_resource(body: ResourceIn, user: dict = Depends(get_current_user)):
    if body.campus not in [c for c in VALID_CAMPUSES if c] or not can_manage_loan(user, body.campus, body.category):
        raise HTTPException(403, "Tidak diizinkan membuat cart/lab untuk kampus dan kategori ini")
    conn = get_conn()
    rid = str(uuid.uuid4())
    conn.execute("INSERT INTO resources (id, campus, name, kind, category, capacity, location, active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, body.campus, body.name.strip(), body.kind, body.category, body.capacity, body.location.strip(), int(body.active), now_iso()))
    conn.commit()
    out = _resource_view(conn, conn.execute("SELECT * FROM resources WHERE id = ?", (rid,)).fetchone())
    conn.close()
    return out


@api.put("/loans/resources/{rid}")
async def update_resource(rid: str, body: ResourceIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    res = _resource_or_404(conn, rid)
    if not (can_manage_loan(user, res["campus"], res["category"]) and can_manage_loan(user, res["campus"], body.category)) or body.campus != res["campus"]:
        conn.close()
        raise HTTPException(403, "Tidak diizinkan mengubah cart/lab ini")
    conn.execute("UPDATE resources SET name = ?, kind = ?, category = ?, capacity = ?, location = ?, active = ? WHERE id = ?",
                 (body.name.strip(), body.kind, body.category, body.capacity, body.location.strip(), int(body.active), rid))
    conn.commit()
    out = _resource_view(conn, conn.execute("SELECT * FROM resources WHERE id = ?", (rid,)).fetchone())
    conn.close()
    return out


@api.get("/loans/resources/{rid}/units")
async def resource_units_list(rid: str, user: dict = Depends(get_current_user)):
    """Units of a cart/lab with this semester's student pairing."""
    conn = get_conn()
    res = _resource_or_404(conn, rid)
    _guard_resource_read(conn, user, res)
    out = []
    for u in booking_engine.resource_units(conn, rid, active_only=False):
        pair = conn.execute("""SELECT class_name, student_name, student_no, academic_year, semester FROM unit_assignments
                               WHERE resource_id = ? AND asset_id = ? ORDER BY academic_year DESC, semester DESC LIMIT 1""", (rid, u["id"])).fetchone()
        out.append({**u, "pairing": dict(pair) if pair else None})
    conn.close()
    return out


class ResourceUnitsIn(BaseModel):
    asset_ids: List[str]


@api.put("/loans/resources/{rid}/units")
async def set_resource_units(rid: str, body: ResourceUnitsIn, user: dict = Depends(get_current_user)):
    """Replace which assets belong to the cart / lab. Assets must be on the same campus."""
    conn = get_conn()
    res = _resource_or_404(conn, rid)
    if not can_manage_loan(user, res["campus"], res["category"]):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan mengubah isi cart/lab ini")
    ids = list(dict.fromkeys(body.asset_ids))
    for aid in ids:
        a = conn.execute("SELECT campus FROM assets WHERE id = ?", (aid,)).fetchone()
        if not a or a["campus"] != res["campus"]:
            conn.close()
            raise HTTPException(400, "Semua unit harus berasal dari kampus yang sama dengan cart/lab.")
    conn.execute("UPDATE asset_loan_settings SET resource_id = NULL WHERE resource_id = ?", (rid,))
    for aid in ids:
        conn.execute("""INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type, resource_id) VALUES (?,1,'scheduled',?)
                        ON CONFLICT(asset_id) DO UPDATE SET resource_id = excluded.resource_id""", (aid, rid))
    conn.commit()
    conn.close()
    return {"ok": True, "units": len(ids)}


class PairingItem(BaseModel):
    asset_id: str
    class_name: str = ""
    student_name: str = ""
    student_no: str = ""


class PairingsIn(BaseModel):
    academic_year: str
    semester: str
    items: List[PairingItem]


@api.get("/loans/resources/{rid}/pairings")
async def get_pairings(rid: str, academic_year: str, semester: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    res = _resource_or_404(conn, rid)
    _guard_resource_read(conn, user, res)
    rows = [dict(r) for r in conn.execute("SELECT * FROM unit_assignments WHERE resource_id = ? AND academic_year = ? AND semester = ?",
                                          (rid, academic_year, semester))]
    conn.close()
    return rows


@api.put("/loans/resources/{rid}/pairings")
async def put_pairings(rid: str, body: PairingsIn, user: dict = Depends(get_current_user)):
    """Fix unit <-> student pairs for a semester (e.g. iPad 12 is always the student with roll number 12)."""
    conn = get_conn()
    res = _resource_or_404(conn, rid)
    if not can_manage_loan(user, res["campus"], res["category"]):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    members = {u["id"] for u in booking_engine.resource_units(conn, rid, active_only=False)}
    for it in body.items:
        if it.asset_id not in members:
            conn.close()
            raise HTTPException(400, "Unit bukan bagian dari cart/lab ini")
    conn.execute("DELETE FROM unit_assignments WHERE resource_id = ? AND academic_year = ? AND semester = ?", (rid, body.academic_year, body.semester))
    for it in body.items:
        if not (it.student_name.strip() or it.student_no.strip()):
            continue
        conn.execute("""INSERT OR REPLACE INTO unit_assignments (id, campus, academic_year, semester, resource_id, asset_id, class_name, student_name, student_no)
                        VALUES (?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), res["campus"], body.academic_year, body.semester, rid, it.asset_id,
                                                       it.class_name.strip(), it.student_name.strip(), it.student_no.strip()))
    conn.commit()
    conn.close()
    return {"ok": True}


# -- school periods & holidays --
class PeriodItem(BaseModel):
    period_no: int = Field(..., ge=1, le=20)
    start_time: str
    end_time: str


class PeriodsIn(BaseModel):
    campus: str
    periods: List[PeriodItem]


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@api.get("/loans/periods")
async def list_periods(user: dict = Depends(get_current_user), campus: Optional[str] = None):
    conn = get_conn()
    camps = _visible_campuses(user, campus)
    rows = conn.execute(f"SELECT campus, period_no, start_time, end_time FROM school_periods WHERE campus IN ({','.join('?' * len(camps))}) ORDER BY campus, period_no", camps).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.put("/loans/periods")
async def put_periods(body: PeriodsIn, user: dict = Depends(get_current_user)):
    """Replace the master list of lesson periods of a campus."""
    if body.campus not in [c for c in VALID_CAMPUSES if c] or not can_setup_campus(user, body.campus):
        raise HTTPException(403, "Tidak diizinkan")
    nos = [p.period_no for p in body.periods]
    if len(set(nos)) != len(nos):
        raise HTTPException(400, "Nomor jam pelajaran tidak boleh ganda")
    ordered = sorted(body.periods, key=lambda p: p.period_no)
    prev_end = ""
    for p in ordered:
        if not (_HHMM.match(p.start_time) and _HHMM.match(p.end_time)) or p.end_time <= p.start_time:
            raise HTTPException(400, f"Jam ke-{p.period_no}: format HH:MM dan jam selesai harus setelah jam mulai")
        if p.start_time < prev_end:
            raise HTTPException(400, f"Jam ke-{p.period_no} tumpang tindih dengan jam sebelumnya")
        prev_end = p.end_time
    conn = get_conn()
    used = conn.execute("SELECT DISTINCT period_from, period_to FROM fixed_schedules WHERE campus = ? AND status = 'active'", (body.campus,)).fetchall()
    keep = set(nos)
    for u in used:
        if u["period_from"] not in keep or u["period_to"] not in keep:
            conn.close()
            raise HTTPException(409, "Jam pelajaran yang masih dipakai jadwal tetap tidak boleh dihapus.")
    conn.execute("DELETE FROM school_periods WHERE campus = ?", (body.campus,))
    for p in ordered:
        conn.execute("INSERT INTO school_periods (id, campus, period_no, start_time, end_time) VALUES (?,?,?,?,?)",
                     (str(uuid.uuid4()), body.campus, p.period_no, p.start_time, p.end_time))
    conn.commit()
    conn.close()
    return {"ok": True, "periods": len(ordered)}


class HolidayIn(BaseModel):
    campus: str = ""
    date: str
    name: str = ""


@api.get("/loans/holidays")
async def list_holidays(user: dict = Depends(get_current_user), campus: Optional[str] = None):
    conn = get_conn()
    camps = _visible_campuses(user, campus)
    rows = conn.execute(f"SELECT * FROM holidays WHERE campus IN ('', {','.join('?' * len(camps))}) ORDER BY date", camps).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.post("/loans/holidays")
async def add_holiday(body: HolidayIn, user: dict = Depends(get_current_user)):
    """campus '' = a holiday for every campus (admins only)."""
    try:
        date_obj = datetime.strptime(body.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Tanggal tidak valid")
    if body.campus and body.campus not in [c for c in VALID_CAMPUSES if c]:
        raise HTTPException(400, "Kampus tidak valid")
    if (not body.campus and user["role"] not in ADMIN_ROLES) or (body.campus and not can_setup_campus(user, body.campus)):
        raise HTTPException(403, "Tidak diizinkan")
    conn = get_conn()
    hid = str(uuid.uuid4())
    try:
        conn.execute("INSERT INTO holidays (id, campus, date, name) VALUES (?,?,?,?)", (hid, body.campus, date_obj.strftime("%Y-%m-%d"), body.name.strip()))
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "Hari libur ini sudah ada")
    conn.commit()
    row = dict(conn.execute("SELECT * FROM holidays WHERE id = ?", (hid,)).fetchone())
    conn.close()
    return row


@api.delete("/loans/holidays/{hid}")
async def delete_holiday(hid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    h = conn.execute("SELECT * FROM holidays WHERE id = ?", (hid,)).fetchone()
    if not h:
        conn.close()
        raise HTTPException(404, "Hari libur tidak ditemukan")
    if (not h["campus"] and user["role"] not in ADMIN_ROLES) or (h["campus"] and not can_setup_campus(user, h["campus"])):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    conn.execute("DELETE FROM holidays WHERE id = ?", (hid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# -- fixed schedules --
class ScheduleIn(BaseModel):
    resource_id: str
    academic_year: str
    semester: str
    class_name: str = Field(..., min_length=1)
    subject: str = ""
    teacher_user_id: Optional[str] = None
    teacher_name: str = ""
    weekday: int = Field(..., ge=0, le=6)
    period_from: int = Field(..., ge=1)
    period_to: int = Field(..., ge=1)
    units: int = Field(1, ge=1)
    valid_from: str
    valid_to: str
    status: Literal["active", "cancelled"] = "active"


def _schedule_payload(conn, body: ScheduleIn) -> dict:
    res = _resource_or_404(conn, body.resource_id)
    data = body.model_dump()
    data["campus"] = res["campus"]
    if body.teacher_user_id:
        t = conn.execute("SELECT name FROM users WHERE id = ?", (body.teacher_user_id,)).fetchone()
        if not t:
            conn.close()
            raise HTTPException(400, "Guru pengampu tidak ditemukan")
        data["teacher_name"] = t["name"]
    return {**data, "_res": res}


@api.get("/loans/schedules")
async def list_schedules(user: dict = Depends(get_current_user), resource_id: Optional[str] = None, campus: Optional[str] = None):
    conn = get_conn()
    camps = _visible_campuses(user, campus)
    conds, params = [f"s.campus IN ({','.join('?' * len(camps))})"], list(camps)
    if resource_id:
        conds.append("s.resource_id = ?"); params.append(resource_id)
    rows = conn.execute(f"""SELECT s.*, r.name AS resource_name FROM fixed_schedules s JOIN resources r ON r.id = s.resource_id
                            WHERE {' AND '.join(conds)} ORDER BY s.weekday, s.period_from""", params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["exceptions"] = [dict(e) for e in conn.execute("SELECT * FROM schedule_exceptions WHERE schedule_id = ? ORDER BY date", (d["id"],))]
        out.append(d)
    conn.close()
    return out


@api.post("/loans/schedules")
async def create_schedule(body: ScheduleIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    data = _schedule_payload(conn, body)
    res = data.pop("_res")
    if not can_manage_loan(user, res["campus"], res["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus ini yang dapat mengisi jadwal tetap")
    ensure_policy_compliant(conn, body.teacher_user_id, "other")
    problems = booking_engine.validate_schedule(conn, data, now=_local_now())
    if problems:
        conn.close()
        raise HTTPException(409, " ".join(problems))
    sid = str(uuid.uuid4())
    conn.execute("""INSERT INTO fixed_schedules (id, campus, academic_year, semester, resource_id, class_name, subject, teacher_user_id, teacher_name,
                    weekday, period_from, period_to, units, valid_from, valid_to, status, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (sid, data["campus"], data["academic_year"], data["semester"], data["resource_id"], data["class_name"].strip(), data["subject"].strip(),
                  data["teacher_user_id"], data["teacher_name"].strip(), data["weekday"], data["period_from"], data["period_to"], data["units"],
                  data["valid_from"], data["valid_to"], data["status"], user["id"], now_iso()))
    conn.commit()
    row = dict(conn.execute("SELECT * FROM fixed_schedules WHERE id = ?", (sid,)).fetchone())
    conn.close()
    return row


@api.put("/loans/schedules/{sid}")
async def update_schedule(sid: str, body: ScheduleIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    old = conn.execute("SELECT * FROM fixed_schedules WHERE id = ?", (sid,)).fetchone()
    if not old:
        conn.close()
        raise HTTPException(404, "Jadwal tidak ditemukan")
    data = _schedule_payload(conn, body)
    res = data.pop("_res")
    if not can_manage_loan(user, res["campus"], res["category"]) or res["campus"] != old["campus"]:
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    if body.teacher_user_id and body.teacher_user_id != old["teacher_user_id"]:
        ensure_policy_compliant(conn, body.teacher_user_id, "other")
    if data["status"] == "active":
        problems = booking_engine.validate_schedule(conn, data, exclude_id=sid, now=_local_now())
        if problems:
            conn.close()
            raise HTTPException(409, " ".join(problems))
    conn.execute("""UPDATE fixed_schedules SET academic_year=?, semester=?, resource_id=?, class_name=?, subject=?, teacher_user_id=?, teacher_name=?,
                    weekday=?, period_from=?, period_to=?, units=?, valid_from=?, valid_to=?, status=? WHERE id = ?""",
                 (data["academic_year"], data["semester"], data["resource_id"], data["class_name"].strip(), data["subject"].strip(), data["teacher_user_id"],
                  data["teacher_name"].strip(), data["weekday"], data["period_from"], data["period_to"], data["units"], data["valid_from"],
                  data["valid_to"], data["status"], sid))
    conn.commit()
    row = dict(conn.execute("SELECT * FROM fixed_schedules WHERE id = ?", (sid,)).fetchone())
    conn.close()
    return row


class ExceptionIn(BaseModel):
    date: str
    note: str = ""


@api.post("/loans/schedules/{sid}/exceptions")
async def add_schedule_exception(sid: str, body: ExceptionIn, user: dict = Depends(get_current_user)):
    """Mark one session "Libur": the slot opens up for other requests."""
    conn = get_conn()
    s = conn.execute("SELECT s.*, r.category FROM fixed_schedules s JOIN resources r ON r.id = s.resource_id WHERE s.id = ?", (sid,)).fetchone()
    if not s:
        conn.close()
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if not can_manage_loan(user, s["campus"], s["category"]):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    try:
        d = datetime.strptime(body.date, "%Y-%m-%d").date()
    except ValueError:
        conn.close()
        raise HTTPException(400, "Tanggal tidak valid")
    if d.weekday() != s["weekday"] or not (s["valid_from"] <= body.date <= s["valid_to"]):
        conn.close()
        raise HTTPException(400, "Tanggal ini bukan sesi jadwal tersebut")
    if conn.execute("SELECT 1 FROM bookings WHERE schedule_id = ? AND start_at LIKE ? AND status IN ('in_use','overdue','completed','problem')",
                    (sid, body.date + "%")).fetchone():
        conn.close()
        raise HTTPException(409, "Sesi ini sudah diserahterimakan dan tidak dapat ditandai libur.")
    try:
        conn.execute("INSERT INTO schedule_exceptions (id, schedule_id, date, kind, note) VALUES (?,?,?,'cancelled',?)", (str(uuid.uuid4()), sid, body.date, body.note.strip()))
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "Sesi ini sudah ditandai libur")
    conn.execute("UPDATE bookings SET status = 'cancelled', decision_note = 'Sesi ditandai libur', updated_at = ? WHERE schedule_id = ? AND start_at LIKE ? AND status = 'approved'",
                 (now_iso(), sid, body.date + "%"))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.delete("/loans/schedules/{sid}/exceptions/{eid}")
async def delete_schedule_exception(sid: str, eid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    s = conn.execute("SELECT s.*, r.category FROM fixed_schedules s JOIN resources r ON r.id = s.resource_id WHERE s.id = ?", (sid,)).fetchone()
    if not s or not can_manage_loan(user, s["campus"], s["category"]):
        conn.close()
        raise HTTPException(403 if s else 404, "Tidak diizinkan" if s else "Jadwal tidak ditemukan")
    ex = conn.execute("SELECT * FROM schedule_exceptions WHERE id = ? AND schedule_id = ?", (eid, sid)).fetchone()
    if not ex:
        conn.close()
        raise HTTPException(404, "Pengecualian tidak ditemukan")
    # putting a session back must not exceed the cart's capacity
    t_from, t_to = booking_engine.period_times(conn, s["campus"], s["period_from"], s["period_to"])
    start, end = booking_engine.parse_dt(f"{ex['date']}T{t_from}"), booking_engine.parse_dt(f"{ex['date']}T{t_to}")
    info = booking_engine.check_availability(conn, resource_id=s["resource_id"], units=s["units"], start=start, end=end)
    if not info["ok"]:
        conn.close()
        raise HTTPException(409, "Slot ini sudah dipakai pengajuan lain, sesi tidak dapat dikembalikan.")
    conn.execute("DELETE FROM schedule_exceptions WHERE id = ?", (eid,))
    conn.commit()
    conn.close()
    return {"ok": True}


class SessionIn(BaseModel):
    date: str


@api.post("/loans/schedules/{sid}/session")
async def open_schedule_session(sid: str, body: SessionIn, user: dict = Depends(get_current_user)):
    """Start the hand-over of one fixed-schedule session (creates the booking the check-out works on)."""
    conn = get_conn()
    s = conn.execute("SELECT s.*, r.category FROM fixed_schedules s JOIN resources r ON r.id = s.resource_id WHERE s.id = ?", (sid,)).fetchone()
    if not s:
        conn.close()
        raise HTTPException(404, "Jadwal tidak ditemukan")
    if not can_manage_loan(user, s["campus"], s["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus ini yang dapat melakukan serah terima")
    try:
        day = datetime.strptime(body.date, "%Y-%m-%d").date()
    except ValueError:
        conn.close()
        raise HTTPException(400, "Tanggal tidak valid")
    b = _engine_call(booking_engine.materialize_fixed, conn, schedule_id=sid, day=day, by_id=user["id"], by_name=user["name"], now=_local_now())
    _, a = _loan_context(conn, b["id"])
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


# -- calendar --
@api.get("/loans/calendar")
async def loan_calendar(resource_id: str, week_start: str, user: dict = Depends(get_current_user)):
    """One week of a cart / lab: for every day and lesson period, how many units are used or free and by whom."""
    conn = get_conn()
    res = _resource_or_404(conn, resource_id)
    _guard_resource_read(conn, user, res)
    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    except ValueError:
        conn.close()
        raise HTTPException(400, "Tanggal tidak valid")
    monday -= timedelta(days=monday.weekday())
    periods = [dict(r) for r in conn.execute("SELECT period_no, start_time, end_time FROM school_periods WHERE campus = ? ORDER BY period_no", (res["campus"],))]
    holidays = {r["date"]: r["name"] for r in conn.execute("SELECT date, name FROM holidays WHERE campus IN (?, '')", (res["campus"],))}
    days = booking_engine.week_cells(conn, res, monday, periods, holidays)
    resource = _resource_view(conn, conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone())
    conn.close()
    return {"resource": resource, "week_start": monday.isoformat(), "periods": periods, "days": days}


# ---- Phase 3: scan, reminders, dashboard, reports ----
async def loan_viewer_required(user: dict = Depends(get_current_user)) -> dict:
    """Who may see the ICT dashboard and loan reports (read only): admins, ICT admins and leaders."""
    if user.get("role") not in ("super_admin", "admin", "leader") + CAMPUS_BOUND:
        raise HTTPException(403, "Tidak diizinkan")
    return user


def _loan_scope(user: dict, campus: Optional[str], alias: str = "b") -> tuple:
    """SQL conditions limiting bookings to what this viewer may see: ICT Admin = own campus + ICT categories,
    admin = non-ICT categories, leader / super admin = everything (optionally one campus)."""
    marks = ",".join("?" * len(ICT_CATEGORIES))
    conds, params = [], []
    if user["role"] == "campus_admin":
        conds.append(f"{alias}.campus = ?"); params.append(user.get("campus") or "")
    elif user["role"] == "ict_admin":
        conds += [f"{alias}.campus = ?", f"{alias}.category IN ({marks})"]; params += [user.get("campus") or "", *ICT_CATEGORIES]
    elif user["role"] == "admin":
        conds.append(f"{alias}.category NOT IN ({marks})"); params += list(ICT_CATEGORIES)
    if campus and user["role"] not in CAMPUS_BOUND:
        conds.append(f"{alias}.campus = ?"); params.append(campus)
    return conds, params


@api.get("/loans/scan")
async def loan_scan(code: str, user: dict = Depends(get_current_user)):
    """Resolve a scanned QR code (or typed asset code). Managers also get the booking to hand over / take back."""
    conn = get_conn()
    info = booking_engine.resolve_scan(conn, code, _local_now())
    conn.close()
    if not info:
        raise HTTPException(404, "Kode aset tidak ditemukan")
    a = info["asset"]
    manage = can_manage_loan(user, a["campus"], a["category"])
    if not (manage or user["role"] in ("leader", *ADMIN_ROLES) or (user.get("campus") or "") == a["campus"]):
        raise HTTPException(403, "Aset ini bukan di kampus Anda")
    if not manage:
        info["out"] = {"requester_name": info["out"]["requester_name"], "end_at": info["out"]["end_at"]} if info["out"] else None
        info["pickup"] = None
    info["suggest"] = ({"action": "check_in", "booking_id": info["out"]["booking_id"]} if manage and info["out"]
                       else {"action": "check_out", "booking_id": info["pickup"]["id"]} if manage and info["pickup"] else None)
    return info


# -- notifications: e-mail + WhatsApp --
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_API_URL = os.environ.get("WHATSAPP_API_URL", "https://api.fonnte.com/send")


def html_to_text(html: str, limit: int = 900) -> str:
    t = re.sub(r"(?i)</(tr|p|h\d|div|li)>|<br\s*/?>", "\n", html)
    t = re.sub(r"(?i)</td>\s*<td[^>]*>", ": ", t)
    t = re.sub(r"<style.*?</style>|<[^>]+>", "", t, flags=re.S)
    t = html_mod.unescape(t)
    t = "\n".join(" ".join(line.split()) for line in t.split("\n") if line.strip())
    return t[:limit]


def send_whatsapp(phone: str, message: str) -> tuple:
    """Send through a Fonnte-style gateway (POST target/message with the token in Authorization).
    Returns (ok, error). Does nothing unless WHATSAPP_TOKEN is set."""
    if not WHATSAPP_TOKEN:
        return False, "not configured"
    try:
        data = urllib.parse.urlencode({"target": phone, "message": message}).encode()
        req = urllib.request.Request(WHATSAPP_API_URL, data=data, headers={"Authorization": WHATSAPP_TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read().decode() or "{}")
        ok = body.get("status", True) in (True, "true", 1)
        return ok, "" if ok else str(body.get("reason") or body)[:200]
    except Exception as exc:
        return False, str(exc)[:200]


def queue_whatsapp(conn, phone: str, subject: str, body_html: str, kind: str, ref_id: str):
    qid = str(uuid.uuid4())
    text = f"*YPJ Assets*\n{subject.replace('[YPJ Assets] ', '')}\n\n{html_to_text(body_html)}"
    conn.execute("INSERT INTO notification_queue (id, channel, to_addr, subject, body, kind, ref_id, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (qid, "whatsapp", phone, subject, text, kind, ref_id, "pending" if WHATSAPP_TOKEN else "skipped", now_iso()))
    conn.commit()
    if not WHATSAPP_TOKEN:
        return
    ok, err = send_whatsapp(phone, text)
    conn.execute("UPDATE notification_queue SET status = ?, error = ?, sent_at = ? WHERE id = ?", ("sent" if ok else "failed", err, now_iso(), qid))
    conn.commit()


def _already_notified(conn, kind: str, ref_id: str, hours: int = 20) -> bool:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return bool(conn.execute("SELECT 1 FROM notification_queue WHERE kind = ? AND ref_id = ? AND channel = 'email' AND created_at > ? LIMIT 1",
                             (kind, ref_id, since)).fetchone())


def _remind(conn, b: dict, kind: str, heading: str, footer: str, with_managers: bool):
    _, a = _loan_context(conn, b["id"])
    u = conn.execute("SELECT email, supervisor FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
    if not u:
        return
    cc = [u["supervisor"]] if u["supervisor"] else []
    if with_managers:
        cc += loan_manager_emails(conn, b["campus"], b["category"]) + [x for x in CAMPUS_HEAD_EMAILS.get(b["campus"], []) if x]
    queue_email(conn, u["email"], f'[YPJ Assets] {heading}: {b["number"]}', _loan_mail(b, a, heading, [], footer), kind, b["id"], cc=list(dict.fromkeys(cc)))


def send_loan_reminders():
    """Daily 08:00 WIT: H-1 pick-up reminders, returns due today, and every loan still overdue."""
    conn = get_conn()
    try:
        t = booking_engine.reminder_targets(conn, _local_now())
        for b in t["pickup_tomorrow"]:
            if not _already_notified(conn, "loan_remind_pickup", b["id"]):
                _remind(conn, b, "loan_remind_pickup", "Pengingat: pengambilan besok", "<p>Silakan ambil aset di ruang ICT sesuai jadwal pada pengajuan ini.</p>", False)
        for b in t["due_today"]:
            if not _already_notified(conn, "loan_remind_due", b["id"]):
                _remind(conn, b, "loan_remind_due", "Jatuh tempo hari ini", f'<p>Mohon kembalikan aset paling lambat {b["end_at"].replace("T", " ")}.</p>', False)
        for b in t["overdue"]:
            if not _already_notified(conn, "loan_overdue", b["id"]):
                _remind(conn, b, "loan_overdue", "Peminjaman terlambat", "<p>Aset belum dikembalikan setelah batas waktu. Mohon segera dikembalikan; pengajuan baru tidak dapat dibuat sebelum itu.</p>", True)
    finally:
        conn.close()


def mark_overdue_loans():
    """Every 15 minutes: loans past their end time that are still out become "Terlambat" and the borrower is told at once."""
    conn = get_conn()
    try:
        rows = booking_engine.newly_overdue(conn, _local_now())
        for b in rows:
            _remind(conn, b, "loan_overdue", "Peminjaman terlambat", "<p>Aset belum dikembalikan setelah batas waktu. Mohon segera dikembalikan; pengajuan baru tidak dapat dibuat sebelum itu.</p>", True)
        if rows:
            logger.warning("Marked %d loan(s) overdue", len(rows))
    finally:
        conn.close()


# -- ICT dashboard --
@api.get("/loans/dashboard")
async def loan_dashboard(user: dict = Depends(loan_viewer_required), campus: Optional[str] = None):
    conn = get_conn()
    now = _local_now()
    booking_engine.mark_overdue(conn, now)
    conds, params = _loan_scope(user, campus)
    where = (" AND " + " AND ".join(conds)) if conds else ""

    def rows(sql_extra, extra_params=(), limit=50):
        return [dict(r) for r in conn.execute(
            f"""SELECT b.*, COALESCE(a.name, r.name) AS asset_name, COALESCE(a.asset_tag, r.kind) AS asset_tag
                FROM bookings b LEFT JOIN assets a ON a.id = b.asset_id LEFT JOIN resources r ON r.id = b.resource_id
                WHERE {sql_extra}{where} ORDER BY b.start_at LIMIT {limit}""", [*extra_params, *params]).fetchall()]

    pending = rows("b.status = 'pending_ict'")
    # units that are out and past due: last user + contact
    unret = []
    for r in conn.execute(f"""SELECT u.asset_id, u.user_label, u.out_at, b.id AS booking_id, b.number, b.end_at, b.requester_id, b.requester_name,
                                    b.supervisor_id, a.name AS asset_name, a.asset_tag, us.email, us.phone, us.supervisor
                             FROM booking_units u JOIN bookings b ON b.id = u.booking_id JOIN assets a ON a.id = u.asset_id
                             LEFT JOIN users us ON us.id = b.requester_id
                             WHERE u.status = 'out' AND b.status = 'overdue'{where} ORDER BY b.end_at""", params).fetchall():
        unret.append(dict(r))
    out_now = rows("b.status = 'in_use'")
    for b in out_now + pending:
        b["status_label"] = LOAN_STATUS_ID.get(b["status"], b["status"])
    today = now.date().isoformat()
    today_list = rows("b.status IN ('approved','partially_approved','in_use') AND substr(b.start_at,1,10) <= ? AND substr(b.end_at,1,10) >= ?", (today, today))
    marks = ",".join("?" * len(ICT_CATEGORIES))
    asset_conds, asset_params = ["s.borrowable = 1", "a.status IN ('in_repair','lost')"], []
    if user["role"] == "campus_admin":
        asset_conds.append("a.campus = ?"); asset_params.append(user.get("campus") or "")
    elif user["role"] == "ict_admin":
        asset_conds += ["a.campus = ?", f"a.category IN ({marks})"]; asset_params += [user.get("campus") or "", *ICT_CATEGORIES]
    elif user["role"] == "admin":
        asset_conds.append(f"a.category NOT IN ({marks})"); asset_params += list(ICT_CATEGORIES)
    if campus and user["role"] not in CAMPUS_BOUND:
        asset_conds.append("a.campus = ?"); asset_params.append(campus)
    broken = [dict(r) for r in conn.execute(f"""SELECT a.id, a.name, a.asset_tag, a.status, a.campus, a.category FROM assets a JOIN asset_loan_settings s ON s.asset_id = a.id
                                                WHERE {' AND '.join(asset_conds)} ORDER BY a.status, a.name""", asset_params)]
    out = {
        "counts": {"pending": len(pending), "out": len(out_now), "not_returned": len(unret), "broken": len(broken), "today": len(today_list)},
        "pending": pending[:10], "not_returned": unret, "out": out_now[:20], "today": today_list[:30], "broken": broken,
    }
    conn.close()
    return out


# -- loan reports --
def _month_range(month: str) -> tuple:
    try:
        first = datetime.strptime(month + "-01", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Bulan tidak valid (gunakan YYYY-MM)")
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first.strftime("%Y-%m-%dT00:00"), nxt.strftime("%Y-%m-%dT00:00")


def _usage_report(conn, user: dict, month: str, campus: Optional[str]) -> dict:
    start, end = _month_range(month)
    conds, params = _loan_scope(user, campus)
    where = (" AND " + " AND ".join(conds)) if conds else ""
    base = f"""SELECT b.*, COALESCE(r.name, a.name, {POOL_NAME_SQL}) AS target_name FROM bookings b LEFT JOIN resources r ON r.id = b.resource_id
               LEFT JOIN assets a ON a.id = b.asset_id WHERE b.start_at >= ? AND b.start_at < ?{where}"""
    rows = [dict(r) for r in conn.execute(base, [start, end, *params])]
    used_status = ("in_use", "completed", "problem", "overdue")
    by_class: dict = {}
    for b in rows:
        if b["status"] not in used_status or b["kind"] == "item":
            continue
        key = (b["campus"], b["class_name"] or "—", b["target_name"])
        row = by_class.setdefault(key, {"campus": key[0], "class_name": key[1], "resource": key[2], "fixed_sessions": 0, "extra_sessions": 0, "hours": 0.0})
        hours = (booking_engine.parse_dt(b["end_at"]) - booking_engine.parse_dt(b["start_at"])).total_seconds() / 3600
        row["fixed_sessions" if b["kind"] == "fixed" else "extra_sessions"] += 1
        row["hours"] = round(row["hours"] + hours, 1)
    off: dict = {}
    for b in rows:
        if b["kind"] != "off_schedule":
            continue
        o = off.setdefault((b["campus"], b["target_name"]), {"campus": b["campus"], "resource": b["target_name"], "requests": 0, "approved": 0, "partial": 0,
                                                           "rejected": 0, "cancelled": 0, "pending": 0, "units_requested": 0, "units_approved": 0})
        o["requests"] += 1
        o["units_requested"] += b["units_requested"]
        o["units_approved"] += b["units_approved"] or 0
        if b["status"] == "rejected":
            o["rejected"] += 1
        elif b["status"] == "cancelled":
            o["cancelled"] += 1
        elif b["status"] in booking_engine.PENDING_STATUSES:
            o["pending"] += 1
        elif b["status"] == "partially_approved":
            o["partial"] += 1
        else:
            o["approved"] += 1
    items: dict = {}
    for b in rows:
        if b["kind"] != "item" or b["status"] in ("cancelled", "rejected"):
            continue
        i = items.setdefault((b["campus"], b["category"], b["target_name"]), {"campus": b["campus"], "category": b["category"], "asset": b["target_name"], "loans": 0, "problems": 0})
        i["loans"] += 1
        i["problems"] += int(b["status"] == "problem")
    return {"month": month, "by_class": sorted(by_class.values(), key=lambda x: (x["campus"], x["class_name"])),
            "off_schedule": sorted(off.values(), key=lambda x: (x["campus"], x["resource"])), "items": sorted(items.values(), key=lambda x: -x["loans"])}


def _incident_report(conn, user: dict, date_from: str, date_to: str, campus: Optional[str]) -> list:
    conds, params = _loan_scope(user, campus)
    where = (" AND " + " AND ".join(conds)) if conds else ""
    out = []
    for r in conn.execute(f"""SELECT u.*, b.number, b.campus, b.category, b.requester_name, b.start_at, b.end_at, b.purpose,
                                    a.name AS asset_name, a.asset_tag, a.status AS asset_status, f.status AS fault_status, f.resolution_note
                             FROM booking_units u JOIN bookings b ON b.id = u.booking_id JOIN assets a ON a.id = u.asset_id
                             LEFT JOIN faults f ON f.id = u.fault_id
                             WHERE u.condition_changed = 1 AND substr(u.in_at,1,10) >= ? AND substr(u.in_at,1,10) <= ?{where}
                             ORDER BY u.in_at DESC""", [date_from, date_to, *params]).fetchall():
        d = dict(r)
        try:
            chk = json.loads(d["in_check"] or "{}")
        except ValueError:
            chk = {}
        follow = {"in_repair": "Dalam perbaikan", "lost": "Hilang", "retired": "Dihapuskan"}.get(d["asset_status"])
        if not follow:
            follow = "Diperbaiki / selesai" if d["fault_status"] == "resolved" else "Perlu ditindaklanjuti"
        out.append({"asset_tag": d["asset_tag"], "asset_name": d["asset_name"], "campus": d["campus"], "category": d["category"],
                    "number": d["number"], "last_user": d["user_label"] or d["requester_name"], "out_at": d["out_at"], "in_at": d["in_at"],
                    "result": chk.get("result", ""), "chronology": chk.get("note", ""), "last_photo": d["post_photo"] or d["pre_photo"],
                    "before_photo": d["pre_photo"], "follow_up": follow, "fault_status": d["fault_status"] or "", "resolution_note": d["resolution_note"] or ""})
    return out


@api.get("/loans/reports/usage")
async def loan_report_usage(month: str, campus: Optional[str] = None, format: str = "json", user: dict = Depends(loan_viewer_required)):
    conn = get_conn()
    data = _usage_report(conn, user, month, campus)
    conn.close()
    if format != "xlsx":
        return data
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pemakaian per kelas"
    ws.append(["Kampus", "Kelas", "Cart / Lab", "Sesi jadwal tetap", "Sesi tambahan", "Jam pemakaian"])
    _style_header(ws)
    for r in data["by_class"]:
        ws.append([campus_display(r["campus"]), r["class_name"], r["resource"], r["fixed_sessions"], r["extra_sessions"], r["hours"]])
    ws2 = wb.create_sheet("Di luar jadwal")
    ws2.append(["Kampus", "Cart / Lab", "Pengajuan", "Disetujui", "Disetujui sebagian", "Ditolak", "Dibatalkan", "Menunggu", "Unit diminta", "Unit disetujui"])
    _style_header(ws2)
    for r in data["off_schedule"]:
        ws2.append([campus_display(r["campus"]), r["resource"], r["requests"], r["approved"], r["partial"], r["rejected"], r["cancelled"], r["pending"], r["units_requested"], r["units_approved"]])
    ws3 = wb.create_sheet("Pinjam barang")
    ws3.append(["Kampus", "Kategori", "Aset", "Jumlah pinjaman", "Bermasalah"])
    _style_header(ws3)
    for r in data["items"]:
        ws3.append([campus_display(r["campus"]), r["category"], r["asset"], r["loans"], r["problems"]])
    return _xlsx_response(wb, f"laporan-peminjaman-{month}.xlsx")


@api.get("/loans/reports/incidents")
async def loan_report_incidents(date_from: str, date_to: str, campus: Optional[str] = None, format: str = "json", user: dict = Depends(loan_viewer_required)):
    conn = get_conn()
    data = _incident_report(conn, user, date_from, date_to, campus)
    conn.close()
    if format != "xlsx":
        return data
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kerusakan & kehilangan"
    ws.append(["Kode aset", "Nama", "Kampus", "Kategori", "No. pinjaman", "Pemakai terakhir", "Keluar", "Kembali", "Hasil", "Kronologi", "Tindak lanjut", "Status laporan", "Foto terakhir"])
    _style_header(ws)
    for r in data:
        ws.append([r["asset_tag"], r["asset_name"], campus_display(r["campus"]), r["category"], r["number"], r["last_user"], r["out_at"], r["in_at"],
                   {"changed": "Berubah", "damaged": "Rusak", "lost": "Hilang"}.get(r["result"], r["result"]), r["chronology"], r["follow_up"], r["fault_status"], r["last_photo"]])
    return _xlsx_response(wb, f"kerusakan-kehilangan-{date_from}-{date_to}.xlsx")


def campus_display(c: str) -> str:
    return {"YPJ TPRA": "YPJ Tembagapura"}.get(c, c)


@api.get("/loans/{bid}")
async def get_loan(bid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    b, a = _loan_context(conn, bid)
    if not _loan_visible(user, b):
        conn.close()
        raise HTTPException(403, "Anda tidak dapat melihat pengajuan ini")
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


class SupervisorIn(BaseModel):
    approve: bool
    note: str = ""


@api.put("/loans/{bid}/supervisor")
async def loan_supervisor(bid: str, body: SupervisorIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    _loan_context(conn, bid)
    b = _engine_call(booking_engine.supervisor_decide, conn, booking_id=bid, approve=body.approve, by_id=user["id"],
                     now=_local_now(), note=body.note)
    _, a = _loan_context(conn, bid)
    if body.approve:
        for addr in loan_manager_emails(conn, b["campus"], b["category"]):
            queue_email(conn, addr, f'[YPJ Assets] Pengajuan {b["number"]} disetujui supervisor',
                        _loan_mail(b, a, "Menunggu Konfirmasi ICT", [("Catatan supervisor", body.note or "—")],
                                   "<p>Supervisor menyetujui permintaan khusus ini. Mohon konfirmasi di aplikasi.</p>"), "loan_new", bid)
    else:
        req_user = conn.execute("SELECT email FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
        if req_user:
            queue_email(conn, req_user["email"], f'[YPJ Assets] Pengajuan {b["number"]} ditolak supervisor',
                        _loan_mail(b, a, "Pengajuan Ditolak Supervisor", [("Alasan", body.note)], ""), "loan_decided", bid)
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


class DecideIn(BaseModel):
    decision: Literal["approved", "partially_approved", "rejected"]
    units: Optional[int] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    note: str = ""
    unit_ids: List[str] = []           # laptop / iPad requests: the exact units ICT lends out


@api.put("/loans/{bid}/decide")
async def decide_loan(bid: str, body: DecideIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    b0, _ = _loan_context(conn, bid)
    if not can_manage_loan(user, b0["campus"], b0["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus dan kategori ini yang dapat memutuskan")
    b = _engine_call(booking_engine.decide, conn, booking_id=bid, decision=body.decision, by_id=user["id"], by_name=user["name"],
                     now=_local_now(), units=body.units, start_at=body.start_at, end_at=body.end_at, note=body.note,
                     unit_ids=body.unit_ids)
    _, a = _loan_context(conn, bid)
    req_user = conn.execute("SELECT email FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
    if req_user:
        heading = {"approved": "Pengajuan Disetujui", "partially_approved": "Pengajuan Disetujui Sebagian", "rejected": "Pengajuan Ditolak"}[body.decision]
        queue_email(conn, req_user["email"], f'[YPJ Assets] {heading}: {b["number"]}',
                    _loan_mail(b, a, heading, [("Diputuskan oleh", user["name"]), ("Catatan", body.note or "—")],
                               "<p>Silakan ambil aset di ruang ICT pada waktu yang disetujui.</p>" if body.decision != "rejected" else ""),
                    "loan_decided", bid)
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


class CancelIn(BaseModel):
    reason: str = ""


@api.put("/loans/{bid}/cancel")
async def cancel_loan(bid: str, body: CancelIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    b0, _ = _loan_context(conn, bid)
    b = _engine_call(booking_engine.cancel, conn, booking_id=bid, by_id=user["id"], can_manage=can_manage_loan(user, b0["campus"], b0["category"]),
                     now=_local_now(), reason=body.reason)
    _, a = _loan_context(conn, bid)
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


class UnitCheckIn(BaseModel):
    asset_id: str
    physical: str
    function: str
    accessories: List[dict] = []
    note: str = ""
    photo: str = ""
    result: str = "ok"
    user_label: str = ""
    student_name: str = ""
    student_no: str = ""
    class_name: str = ""


class CheckIn(BaseModel):
    units: List[UnitCheckIn] = []
    group_photo: str = ""
    all_units: bool = False            # cart / lab: every unit at once; `units` then only lists the exceptions
    exclude: List[str] = []            # asset ids that are not handed over / not back


def _bulk_merge(conn, booking: dict, body: "CheckIn", only_unreturned: bool) -> list:
    """Unit rows for a check-out / check-in. With all_units the cart's units are filled in as "fine" and the entries
    in body.units (problem units, with notes / photos) replace their default row."""
    explicit = [u.model_dump() for u in body.units]
    if not body.all_units:
        return explicit
    if not booking["resource_id"] and booking["kind"] != "pool":
        raise HTTPException(400, "Pilihan semua unit hanya untuk cart/lab atau permintaan laptop/iPad.")
    rows = {u["asset_id"]: u for u in booking_engine.bulk_units(conn, booking, exclude=body.exclude, only_unreturned=only_unreturned)}
    for u in explicit:
        rows[u["asset_id"]] = {**rows.get(u["asset_id"], {}), **{k: v for k, v in u.items() if v not in ("", None, [])}}
        rows[u["asset_id"]].setdefault("accessories", [])
    return list(rows.values())


@api.post("/loans/{bid}/check-out")
async def loan_check_out(bid: str, body: CheckIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    b0, _ = _loan_context(conn, bid)
    if not can_manage_loan(user, b0["campus"], b0["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus dan kategori ini yang dapat melakukan serah terima")
    units = _bulk_merge(conn, b0, body, only_unreturned=False)
    b = _engine_call(booking_engine.check_out, conn, booking_id=bid, units=units, now=_local_now(),
                     by_id=user["id"], by_name=user["name"], group_photo=body.group_photo)
    _, a = _loan_context(conn, bid)
    req_user = conn.execute("SELECT email FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
    if req_user:
        queue_email(conn, req_user["email"], f'[YPJ Assets] Aset diserahkan: {b["number"]}',
                    _loan_mail(b, a, "Aset Diserahkan", [("Diserahkan oleh", user["name"]), ("Kembali paling lambat", b["end_at"].replace("T", " "))],
                               "<p>Aset kini menjadi tanggung jawab Anda. Mohon kembalikan tepat waktu dan dalam kondisi yang sama.</p>"),
                    "loan_out", bid)
    view = _loan_view(conn, user, b, a)
    conn.close()
    return view


@api.post("/loans/{bid}/check-in")
async def loan_check_in(bid: str, body: CheckIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    b0, _ = _loan_context(conn, bid)
    if not can_manage_loan(user, b0["campus"], b0["category"]):
        conn.close()
        raise HTTPException(403, "Hanya Admin ICT untuk kampus dan kategori ini yang dapat menerima pengembalian")
    units = _bulk_merge(conn, b0, body, only_unreturned=True)
    res = _engine_call(booking_engine.check_in, conn, booking_id=bid, units=units, now=_local_now(),
                       by_id=user["id"], by_name=user["name"], group_photo=body.group_photo)
    b = res["booking"]
    _, a = _loan_context(conn, bid)
    req_user = conn.execute("SELECT email FROM users WHERE id = ?", (b["requester_id"],)).fetchone()
    cc = [x for x in loan_manager_emails(conn, b["campus"], b["category"])] if res["faults"] else []
    if res["faults"]:
        cc += [x for x in CAMPUS_HEAD_EMAILS.get(b["campus"], []) if x]
    if req_user:
        heading = "Pengembalian Bermasalah" if res["faults"] else "Pengembalian Dicatat"
        queue_email(conn, req_user["email"], f'[YPJ Assets] {heading}: {b["number"]}',
                    _loan_mail(b, a, heading, [("Diterima oleh", user["name"])],
                               "<p>Terdapat perubahan kondisi pada aset. Laporan telah dibuat di modul Faults.</p>" if res["faults"]
                               else "<p>Terima kasih, peminjaman ditutup.</p>"), "loan_in", bid, cc=cc)
    view = _loan_view(conn, user, b, a)
    view["faults"], view["still_out"] = res["faults"], res["still_out"]
    conn.close()
    return view


class LoanSettingsIn(BaseModel):
    borrowable: bool = False
    loan_type: str = "item"
    accessories: List[str] = []
    storage_slot: str = ""
    max_loan_days: Optional[int] = None
    requires_approval: Optional[bool] = None
    can_leave_campus: Optional[bool] = None


@api.get("/loans/assets/{aid}/settings")
async def get_loan_settings(aid: str, user: dict = Depends(get_current_user)):
    import json as _json
    conn = get_conn()
    a = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (aid,)).fetchone()
    if not a:
        conn.close()
        raise HTTPException(404, "Aset tidak ditemukan")
    s = conn.execute("SELECT * FROM asset_loan_settings WHERE asset_id = ?", (aid,)).fetchone()
    policy = booking_engine.get_policy(conn, a["campus"], a["category"])
    conn.close()
    d = dict(s) if s else {"asset_id": aid, "borrowable": 0, "loan_type": "item", "accessories": "[]", "storage_slot": "",
                           "max_loan_days": None, "requires_approval": None, "can_leave_campus": None}
    d["accessories"] = _json.loads(d["accessories"] or "[]")
    d["policy"] = policy
    d["can_edit"] = can_manage_loan(user, a["campus"], a["category"]) or user["role"] in ADMIN_ROLES
    return d


@api.put("/loans/assets/{aid}/settings")
async def put_loan_settings(aid: str, body: LoanSettingsIn, user: dict = Depends(get_current_user)):
    import json as _json
    conn = get_conn()
    a = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (aid,)).fetchone()
    if not a:
        conn.close()
        raise HTTPException(404, "Aset tidak ditemukan")
    if not (can_manage_loan(user, a["campus"], a["category"]) or user["role"] in ADMIN_ROLES):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan mengubah pengaturan peminjaman aset ini")
    if body.loan_type not in ("item", "scheduled"):
        conn.close()
        raise HTTPException(400, "Jenis peminjaman tidak valid")
    if body.max_loan_days is not None and body.max_loan_days < 1:
        conn.close()
        raise HTTPException(400, "Maks. lama pinjam minimal 1 hari")
    acc = [x.strip() for x in body.accessories if x.strip()]
    flag = lambda v: None if v is None else int(v)
    conn.execute("""INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type, accessories, storage_slot, max_loan_days,
                    requires_approval, can_leave_campus) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(asset_id) DO UPDATE SET borrowable = excluded.borrowable, loan_type = excluded.loan_type,
                    accessories = excluded.accessories, storage_slot = excluded.storage_slot, max_loan_days = excluded.max_loan_days,
                    requires_approval = excluded.requires_approval, can_leave_campus = excluded.can_leave_campus""",
                 (aid, int(body.borrowable), body.loan_type, _json.dumps(acc), body.storage_slot.strip(), body.max_loan_days,
                  flag(body.requires_approval), flag(body.can_leave_campus)))
    conn.commit()
    conn.close()
    return await get_loan_settings(aid, user)


@api.get("/loans/assets/{aid}/history")
async def asset_loan_history(aid: str, user: dict = Depends(get_current_user)):
    """Every loan of one asset with borrower, condition notes and before/after photos."""
    import json as _json
    conn = get_conn()
    a = conn.execute("SELECT campus, category FROM assets WHERE id = ?", (aid,)).fetchone()
    if not a:
        conn.close()
        raise HTTPException(404, "Aset tidak ditemukan")
    if not (user["role"] in ("leader", *ADMIN_ROLES) or can_manage_loan(user, a["campus"], a["category"])):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    rows = conn.execute("""SELECT u.*, b.number, b.requester_name, b.status AS booking_status, b.start_at, b.end_at, b.purpose
                           FROM booking_units u JOIN bookings b ON b.id = u.booking_id WHERE u.asset_id = ? ORDER BY u.out_at DESC""", (aid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("out_check", "in_check"):
            try:
                d[k] = _json.loads(d[k] or "{}")
            except ValueError:
                d[k] = {}
        out.append(d)
    conn.close()
    return out


# ===================================================================
# Classrooms: class assets belong to the room, not to the teacher
# ===================================================================
# A classroom is matched to assets by (campus, location). The responsible teacher changes through a
# hand-over: the new teacher checks every asset (accept / missing-or-damaged) and the change only takes
# effect once all items are checked. Items marked missing stay with the previous holder, flagged as a discrepancy.
ROOM_TYPES = ("kelas", "lab", "kantor", "lainnya")
ROOM_TYPE_LABEL_ID = {"kelas": "Kelas", "lab": "Laboratorium", "kantor": "Kantor", "lainnya": "Lainnya"}


def _guess_room_type(name: str) -> str:
    n = (name or "").casefold()
    if "lab" in n:
        return "lab"
    if any(w in n for w in ("kantor", "office", "ruang guru", "tata usaha", "perpus", "library")):
        return "kantor"
    return "kelas"


def _room_key(s) -> str:
    return " ".join((s or "").split()).casefold()


def sync_classrooms(conn):
    """Make sure every (campus, location) used by an asset has a classroom. Idempotent."""
    have = {(_room_key(r["campus"]), _room_key(r["name"])) for r in conn.execute("SELECT campus, name FROM classrooms")}
    ts = now_iso()
    added = False
    for r in conn.execute("""SELECT campus, location FROM assets WHERE TRIM(location) != ''
                             GROUP BY campus, location ORDER BY campus, location""").fetchall():
        key = (_room_key(r["campus"]), _room_key(r["location"]))
        if key in have:
            continue
        have.add(key)
        name = " ".join(r["location"].split())
        holders = conn.execute("""SELECT assigned_to_user_id uid, assigned_to_name nm, COUNT(*) n FROM assets
            WHERE campus = ? AND LOWER(TRIM(location)) = ? AND assignment_kind = 'class' AND assigned_to_user_id IS NOT NULL
            GROUP BY assigned_to_user_id ORDER BY n DESC LIMIT 1""", (r["campus"], key[1])).fetchone()
        conn.execute("""INSERT INTO classrooms (id,name,campus,room_type,responsible_user_id,responsible_name,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (str(uuid.uuid4()), name, r["campus"] or "", _guess_room_type(name),
                      holders["uid"] if holders else None, ownerName_plain(holders["nm"]) if holders else None, ts, ts))
        added = True
    if added:
        conn.commit()


def ownerName_plain(label) -> str:
    return (label or "").split(" — ")[0].strip()


def _room_assets(conn, room: dict) -> list:
    rows = conn.execute("""SELECT * FROM assets WHERE campus = ? AND LOWER(TRIM(location)) = ? ORDER BY name""",
                        (room["campus"], _room_key(room["name"]))).fetchall()
    return [row_to_dict(r) for r in rows]


def _is_class_asset(a: dict) -> bool:
    """Held by the room: marked class, or nobody holds it yet. Personal items of a teacher are not."""
    return (a.get("assignment_kind") == "class") or not (a.get("assigned_to_user_id") or (a.get("assigned_to_name") or "").strip())


def _active_handover(conn, classroom_id):
    r = conn.execute("SELECT * FROM classroom_handovers WHERE classroom_id = ? AND status = 'pending'", (classroom_id,)).fetchone()
    return dict(r) if r else None


def _handover_progress(conn, h: dict) -> dict:
    rows = [dict(r) for r in conn.execute("SELECT status, applied FROM assignments WHERE batch_id = ?", (h["id"],)).fetchall()]
    rows = [r for r in rows if r["status"] != "cancelled"]
    return {"total": len(rows),
            "checked": sum(1 for r in rows if r["status"] in ("accepted", "rejected")),
            "accepted": sum(1 for r in rows if r["status"] == "accepted"),
            "rejected": sum(1 for r in rows if r["status"] == "rejected")}


def _room_summary(conn, room: dict) -> dict:
    assets = _room_assets(conn, room)
    live = [a for a in assets if a["status"] not in INACTIVE_STATUSES]
    out = dict(room)
    out["asset_count"] = len(live)
    out["class_count"] = len([a for a in live if _is_class_asset(a)])
    out["personal_count"] = len(live) - out["class_count"]
    out["purchase_value"] = sum(a["purchase_price"] or 0 for a in live)
    out["discrepancy_count"] = len([a for a in live if a.get("handover_flag") == "discrepancy"])
    h = _active_handover(conn, room["id"])
    out["handover"] = ({**h, **_handover_progress(conn, h)} if h else None)
    return out


class ClassroomIn(BaseModel):
    name: str
    campus: Optional[str] = ""
    room_type: Optional[str] = "kelas"
    responsible_user_id: Optional[str] = None


class ClassroomUpdateIn(BaseModel):
    name: Optional[str] = None
    room_type: Optional[str] = None
    responsible_user_id: Optional[str] = None


class ClassHandoverIn(BaseModel):
    to_user_id: str
    asset_ids: Optional[List[str]] = None
    note: Optional[str] = ""


class ResolveIn(BaseModel):
    asset_ids: List[str]


def _get_room(conn, cid):
    r = conn.execute("SELECT * FROM classrooms WHERE id = ?", (cid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "Classroom not found")
    return dict(r)


def _room_visible(user: dict, room: dict) -> bool:
    if user["role"] in ADMIN_ROLES:
        return True
    campus = (user.get("campus") or "").strip()
    return room.get("responsible_user_id") == user["id"] or bool(campus and room.get("campus") == campus)


@api.get("/classrooms")
async def list_classrooms(user: dict = Depends(get_current_user)):
    conn = get_conn()
    sync_classrooms(conn)
    rooms = [dict(r) for r in conn.execute("SELECT * FROM classrooms ORDER BY campus, name").fetchall()]
    out = [_room_summary(conn, r) for r in rooms if _room_visible(user, r)]
    conn.close()
    return out


def _room_scope(conn, user: dict, room):
    try:
        ensure_campus_scope(user, room["campus"])
    except HTTPException:
        conn.close()
        raise


@api.post("/classrooms")
async def create_classroom(body: ClassroomIn, user: dict = Depends(admin_required)):
    ensure_campus_scope(user, body.campus or "")
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(400, "Nama kelas wajib diisi")
    rt = body.room_type if body.room_type in ROOM_TYPES else "kelas"
    conn = get_conn()
    sync_classrooms(conn)
    campus = body.campus or ""
    if conn.execute("SELECT 1 FROM classrooms WHERE campus = ? AND LOWER(name) = ?", (campus, name.casefold())).fetchone():
        conn.close()
        raise HTTPException(409, "Kelas dengan nama ini sudah ada di kampus tersebut")
    resp = require_user(conn, body.responsible_user_id) if body.responsible_user_id else None
    cid, ts = str(uuid.uuid4()), now_iso()
    conn.execute("""INSERT INTO classrooms (id,name,campus,room_type,responsible_user_id,responsible_name,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (cid, name, campus, rt, resp["id"] if resp else None,
                                                  resp["name"] if resp else None, ts, ts))
    conn.commit()
    room = _room_summary(conn, _get_room(conn, cid))
    conn.close()
    return room


@api.put("/classrooms/{cid}")
async def update_classroom(cid: str, body: ClassroomUpdateIn, user: dict = Depends(admin_required)):
    conn = get_conn()
    room = _get_room(conn, cid)
    _room_scope(conn, user, room)
    ts = now_iso()
    if body.name is not None:
        name = " ".join(body.name.split())
        if not name:
            conn.close()
            raise HTTPException(400, "Nama kelas wajib diisi")
        if _room_key(name) != _room_key(room["name"]) and conn.execute(
                "SELECT 1 FROM classrooms WHERE campus = ? AND LOWER(name) = ? AND id != ?",
                (room["campus"], name.casefold(), cid)).fetchone():
            conn.close()
            raise HTTPException(409, "Kelas dengan nama ini sudah ada di kampus tersebut")
        # assets follow the room name (their location text)
        conn.execute("UPDATE assets SET location = ?, updated_at = ? WHERE campus = ? AND LOWER(TRIM(location)) = ?",
                     (name, ts, room["campus"], _room_key(room["name"])))
        conn.execute("UPDATE classrooms SET name = ?, updated_at = ? WHERE id = ?", (name, ts, cid))
    if body.room_type in ROOM_TYPES:
        conn.execute("UPDATE classrooms SET room_type = ?, updated_at = ? WHERE id = ?", (body.room_type, ts, cid))
    if body.responsible_user_id:
        # only the first assignment is direct; later changes go through a hand-over so the teacher confirms
        if room.get("responsible_user_id") and room["responsible_user_id"] != body.responsible_user_id:
            conn.close()
            raise HTTPException(409, "Penanggung jawab diganti lewat serah terima kelas (dikonfirmasi guru baru)")
        resp = require_user(conn, body.responsible_user_id)
        conn.execute("UPDATE classrooms SET responsible_user_id = ?, responsible_name = ?, updated_at = ? WHERE id = ?",
                     (resp["id"], resp["name"], ts, cid))
    conn.commit()
    out = _room_summary(conn, _get_room(conn, cid))
    conn.close()
    return out


@api.delete("/classrooms/{cid}")
async def delete_classroom(cid: str, user: dict = Depends(admin_required)):
    conn = get_conn()
    room = _get_room(conn, cid)
    _room_scope(conn, user, room)
    if _room_assets(conn, room):
        conn.close()
        raise HTTPException(409, "Kelas masih memiliki aset. Pindahkan asetnya dulu.")
    conn.execute("DELETE FROM classrooms WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.get("/classrooms/{cid}")
async def classroom_detail(cid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    room = _get_room(conn, cid)
    if not _room_visible(user, room):
        conn.close()
        raise HTTPException(403, "Not allowed")
    pend = {r["asset_id"]: dict(r) for r in conn.execute(
        "SELECT asset_id, to_name, status, source FROM assignments WHERE status = 'pending' OR (status = 'accepted' AND applied = 0)")}
    assets = []
    for a in _room_assets(conn, room):
        a = _slim_asset(a)
        a["is_class_asset"] = _is_class_asset(a)
        a["pending_assignment"] = pend.get(a["id"])
        assets.append(a)
    out = _room_summary(conn, room)
    out["assets"] = assets
    out["history"] = [{**dict(r), **_handover_progress(conn, dict(r))} for r in conn.execute(
        "SELECT * FROM classroom_handovers WHERE classroom_id = ? ORDER BY created_at DESC LIMIT 20", (cid,)).fetchall()]
    conn.close()
    return out


@api.post("/classrooms/{cid}/handover")
async def classroom_handover(cid: str, body: ClassHandoverIn, user: dict = Depends(admin_required)):
    conn = get_conn()
    room = _get_room(conn, cid)
    _room_scope(conn, user, room)
    if _active_handover(conn, cid):
        conn.close()
        raise HTTPException(409, "Kelas ini masih punya serah terima yang belum selesai")
    to_user = resolve_user(conn, user_id=body.to_user_id)
    if not to_user:
        conn.close()
        raise HTTPException(404, "Recipient not found")
    room_assets = {a["id"]: a for a in _room_assets(conn, room)}
    ids = body.asset_ids if body.asset_ids else [i for i, a in room_assets.items() if _is_class_asset(a)]
    hid = str(uuid.uuid4())
    created, skipped = [], []
    for aid in dict.fromkeys(ids):
        asset = room_assets.get(aid)
        if not asset:
            skipped.append({"asset_id": aid, "reason": "not_in_room"}); continue
        if asset["status"] in INACTIVE_STATUSES:
            skipped.append({"asset_id": aid, "name": asset["name"], "reason": "inactive"}); continue
        try:
            created.append(create_assignment(conn, asset, to_user, "class", "class_handover", user,
                                             note=body.note or "", batch_id=hid, to_label=to_user["name"]))
        except ValueError as e:
            skipped.append({"asset_id": aid, "name": asset["name"], "reason": str(e)})
    if not created:
        conn.close()
        raise HTTPException(409, "Tidak ada aset yang dapat diserahterimakan (semua sudah menunggu konfirmasi atau sudah atas nama guru ini)")
    conn.execute("""INSERT INTO classroom_handovers (id,classroom_id,classroom_name,from_user_id,from_name,to_user_id,to_name,
                    status,note,created_by,created_by_name,created_at) VALUES (?,?,?,?,?,?,?,'pending',?,?,?,?)""",
                 (hid, cid, room["name"], room.get("responsible_user_id"), room.get("responsible_name"),
                  to_user["id"], to_user["name"], body.note or "", user["id"], user["name"], now_iso()))
    conn.commit()
    conn.close()
    notify_assignees(created)
    return {"created": len(created), "skipped": skipped, "handover_id": hid}


def _close_assignments_of(conn, h: dict, ts: str):
    conn.execute("UPDATE assignments SET status='cancelled', responded_at=? WHERE batch_id = ? AND status = 'pending'",
                 (ts, h["id"]))


@api.post("/classrooms/{cid}/handover/cancel")
async def classroom_handover_cancel(cid: str, user: dict = Depends(admin_required)):
    conn = get_conn()
    _room_scope(conn, user, _get_room(conn, cid))
    h = _active_handover(conn, cid)
    if not h:
        conn.close()
        raise HTTPException(404, "Tidak ada serah terima yang berjalan")
    ts = now_iso()
    _close_assignments_of(conn, h, ts)
    # items already checked but not yet applied are dropped too
    conn.execute("UPDATE assignments SET status='cancelled', responded_at=? WHERE batch_id = ? AND status='accepted' AND applied = 0",
                 (ts, h["id"]))
    conn.execute("UPDATE classroom_handovers SET status='cancelled', completed_at=? WHERE id = ?", (ts, h["id"]))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.post("/classrooms/{cid}/resolve-discrepancy")
async def classroom_resolve(cid: str, body: ResolveIn, user: dict = Depends(admin_required)):
    conn = get_conn()
    room = _get_room(conn, cid)
    _room_scope(conn, user, room)
    ids = {a["id"] for a in _room_assets(conn, room)}
    n = 0
    for aid in body.asset_ids:
        if aid in ids:
            conn.execute("UPDATE assets SET handover_flag = '', updated_at = ? WHERE id = ?", (now_iso(), aid))
            n += 1
    conn.commit()
    conn.close()
    return {"resolved": n}


class SetKindIn(BaseModel):
    asset_ids: List[str]
    kind: Literal["class", "personal"]


@api.post("/classrooms/{cid}/set-kind")
async def classroom_set_kind(cid: str, body: SetKindIn, user: dict = Depends(admin_required)):
    """Mark assets of this room as class assets (follow the room) or personal (stay with their holder)."""
    conn = get_conn()
    room = _get_room(conn, cid)
    _room_scope(conn, user, room)
    in_room = {a["id"]: a for a in _room_assets(conn, room)}
    changed, skipped = 0, []
    for aid in dict.fromkeys(body.asset_ids):
        a = in_room.get(aid)
        if not a:
            skipped.append({"asset_id": aid, "reason": "not_in_room"}); continue
        if pending_assignment(conn, aid):
            skipped.append({"asset_id": aid, "name": a["name"], "reason": "pending"}); continue
        if (a.get("assignment_kind") or "personal") == body.kind:
            continue
        conn.execute("UPDATE assets SET assignment_kind = ?, updated_at = ? WHERE id = ?", (body.kind, now_iso(), aid))
        changed += 1
    conn.commit()
    conn.close()
    return {"changed": changed, "skipped": skipped}


def finish_class_handovers(conn, batch_ids):
    """After items were answered/cancelled: close hand-overs with nothing pending and apply the accepted items.
    Returns the finished hand-over dicts (with counts) so the caller can e-mail after commit."""
    finished, ts = [], now_iso()
    for bid in dict.fromkeys(batch_ids):
        hr = conn.execute("SELECT * FROM classroom_handovers WHERE id = ? AND status = 'pending'", (bid,)).fetchone()
        if not hr:
            continue
        if conn.execute("SELECT 1 FROM assignments WHERE batch_id = ? AND status = 'pending' LIMIT 1", (bid,)).fetchone():
            continue
        h = dict(hr)
        items = [dict(r) for r in conn.execute("SELECT * FROM assignments WHERE batch_id = ? ORDER BY asset_name", (bid,)).fetchall()]
        accepted = [i for i in items if i["status"] == "accepted"]
        rejected = [i for i in items if i["status"] == "rejected"]
        for i in accepted:
            if not i.get("applied"):
                apply_assignment(conn, i, ts)
                conn.execute("UPDATE assignments SET applied = 1 WHERE id = ?", (i["id"],))
        if accepted:
            conn.execute("UPDATE classrooms SET responsible_user_id=?, responsible_name=?, updated_at=? WHERE id = ?",
                         (h["to_user_id"], h["to_name"], ts, h["classroom_id"]))
        conn.execute("UPDATE classroom_handovers SET status='completed', completed_at=?, accepted_count=?, discrepancy_count=? WHERE id = ?",
                     (ts, len(accepted), len(rejected), bid))
        h.update(status="completed", accepted=accepted, rejected=rejected)
        finished.append(h)
    return finished


def _class_complete_html(h: dict) -> str:
    import html as _h
    def rows(items, bad=False):
        return "".join(
            f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_h.escape(i['asset_name'])}<br>"
            f"<span style='color:#64748b;font-size:12px;'>{_h.escape(i['asset_tag'])}</span></td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#b91c1c;'>"
            f"{_h.escape(i.get('reject_reason') or '')}</td></tr>" if bad else
            f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;'>{_h.escape(i['asset_name'])} "
            f"<span style='color:#64748b;font-size:12px;'>({_h.escape(i['asset_tag'])})</span></td></tr>" for i in items)
    ok = h["accepted"]
    bad = h["rejected"]
    bad_html = (f"<h3 style='margin:18px 0 6px;font-size:15px;color:#b91c1c;'>Selisih serah terima ({len(bad)})</h3>"
                "<p style='font-size:13px;color:#475569;margin:0 0 6px;'>Aset berikut ditandai tidak ada / rusak dan "
                "tetap tercatat pada pemegang sebelumnya sampai Admin menindaklanjuti.</p>"
                f"<table style='border-collapse:collapse;width:100%;font-size:14px;'>{rows(bad, True)}</table>") if bad else ""
    ok_html = (f"<h3 style='margin:18px 0 6px;font-size:15px;color:#15803d;'>Diterima ({len(ok)})</h3>"
               f"<table style='border-collapse:collapse;width:100%;font-size:14px;'>{rows(ok)}</table>") if ok else ""
    resp = (f"Penanggung jawab kelas kini: <strong>{_h.escape(h['to_name'])}</strong>." if ok
            else "Tidak ada aset yang diterima, penanggung jawab kelas <strong>tidak berubah</strong>.")
    return _email_shell(f"""
        <h2 style="margin:0 0 10px;font-size:22px;color:#0f172a;">Serah terima kelas selesai</h2>
        <p style="margin:0 0 8px;">Kelas <strong>{_h.escape(h['classroom_name'])}</strong>:
          {_h.escape(h.get('from_name') or '—')} → <strong>{_h.escape(h['to_name'])}</strong></p>
        <p style="margin:0 0 8px;">{resp}</p>{ok_html}{bad_html}""",
        eyebrow="Serah terima kelas", cta_label="Buka kelas", cta_url=f"{APP_URL}/classrooms/{h['classroom_id']}")


def notify_class_handover_done(finished: list):
    """To the previous teacher (or the admin if there was none), CC admin, new teacher and both supervisors."""
    conn = get_conn()
    try:
        for h in finished:
            to_addr, _n = _user_email(conn, h["from_user_id"]) if h.get("from_user_id") else (None, None)
            admin_addr, _a = _user_email(conn, h["created_by"])
            to_addr = to_addr or admin_addr
            if not to_addr:
                continue
            new_addr, _x = _user_email(conn, h["to_user_id"])
            cc = [e for e in (admin_addr, new_addr, ASSET_REMINDER_EMAIL) if e and e != to_addr]
            cc += _supervisor_cc(conn, [h.get("from_user_id"), h["to_user_id"]], exclude=[to_addr] + cc)
            flag = " — ADA SELISIH" if h["rejected"] else ""
            send_email(to_addr, f"[YPJ Assets] Serah terima kelas {h['classroom_name']} selesai{flag}",
                       _class_complete_html(h), cc=list(dict.fromkeys(cc)))
    finally:
        conn.close()


# ---- Mount ----
# ======================================================================================
# BYOD: students may use their own laptop / iPad / tablet on the school WiFi for a project
# ======================================================================================
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def _today_local():
    return _local_now().date()


def can_manage_byod(user: dict, campus: str) -> bool:
    """Approves requests and revokes access: super_admin, or the ICT Admin of that campus."""
    return is_ict_pic(user, campus, "IT Equipment")


def _byod_visible(user: dict, r: dict) -> bool:
    return (user.get("role") in ("leader", "admin", "super_admin") or r["teacher_id"] == user["id"] or can_manage_byod(user, r["campus"]))


class ByodStudentIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    class_name: str = ""
    student_no: str = ""
    parent_name: str = ""
    parent_relation: str = ""
    parent_email: str = ""
    parent_phone: str = ""


class ByodProjectIn(BaseModel):
    name: str = Field(..., min_length=3, max_length=160)
    subject: str = ""
    location: str = ""
    start_date: str
    end_date: str
    hour_from: str = "07:30"
    hour_to: str = "15:30"
    campus: str = ""                  # only needed by accounts without a campus (admin / super admin)
    students: List[ByodStudentIn] = Field(..., min_length=1, max_length=40)


def _byod_err(e: "byod.ByodError"):
    return HTTPException(e.status, e.message)


def _byod_link(token: str) -> str:
    return f"{APP_URL}/byod/sign?token={token}"


def _byod_send_parent_link(conn, req: dict, project: dict, token: str) -> dict:
    """E-mail and/or WhatsApp the one-time link to the parent. Returns what was attempted."""
    link = _byod_link(token)
    subject = f'[YPJ Assets] Persetujuan BYOD untuk {req["student_name"]}'
    lines = [("Siswa", req["student_name"] + (f' ({req["student_class"]})' if req["student_class"] else "")),
             ("Project", project["name"]),
             ("Periode", f'{project["start_date"]} s/d {project["end_date"]}, {project["hour_from"]}–{project["hour_to"]}'),
             ("Guru pendamping", req["teacher_name"])]
    rows = "".join(f"<tr><td style='padding:4px 8px;color:#64748b;'>{k}</td><td style='padding:4px 8px;font-weight:500;'>{v}</td></tr>" for k, v in lines)
    body = _email_shell(f"""
        <h2 style="margin:0 0 4px;font-size:22px;color:#0f172a;">Persetujuan Orang Tua — Bring Your Own Device</h2>
        <p style="font-size:14px;color:#334155;">Yth. Orang Tua/Wali, putra/putri Anda diajukan untuk membawa perangkat pribadi (laptop/iPad/tablet)
        guna mengerjakan project sekolah. Mohon baca ketentuan dan beri persetujuan melalui tautan berikut (berlaku {byod.TOKEN_DAYS} hari, satu kali pakai).</p>
        <table style="border-collapse:collapse;margin:16px 0;font-size:14px;">{rows}</table>
        <p style="font-size:12px;color:#64748b;">Tautan: {link}</p>""", cta_label="Buka Formulir Persetujuan", cta_url=link)
    sent = {"email": False, "whatsapp": False}
    if req["parent_email"]:
        queue_email(conn, req["parent_email"], subject, body, "byod_parent", req["id"])
        sent["email"] = True
    if req["parent_phone"]:
        try:
            queue_whatsapp(conn, req["parent_phone"], subject, body, "byod_parent", req["id"])
            sent["whatsapp"] = bool(WHATSAPP_TOKEN)
        except Exception as exc:
            logger.warning("BYOD WhatsApp failed: %s", exc)
    return sent


def _byod_notify(conn, to_addrs: list, subject: str, heading: str, req: dict, text: str, kind: str):
    rows = [("No. Permohonan", req["number"]), ("Siswa", req["student_name"]), ("Periode", f'{req["valid_from"]} s/d {req["valid_to"]}')]
    body = _loan_html(req, heading, rows, f"<p>{text}</p>")
    for addr in dict.fromkeys(a for a in to_addrs if a):
        queue_email(conn, addr, f"[YPJ Assets] {subject}: {req['number']}", body, kind, req["id"])


def _byod_row(conn, rid: str) -> dict:
    r = conn.execute("SELECT * FROM byod_requests WHERE id = ?", (rid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "Permohonan BYOD tidak ditemukan")
    return dict(r)


def _byod_view(conn, user: dict, r: dict, full: bool = True) -> dict:
    today = _today_local()
    out = {k: v for k, v in r.items() if k not in ("token_hash", "token_expires_at", "parent_signature", "teacher_signature", "parent_ua", "teacher_ua")}
    out["effective_status"] = byod.effective_status(r, today)
    p = conn.execute("SELECT * FROM byod_projects WHERE id = ?", (r["project_id"],)).fetchone()
    out["project"] = dict(p) if p else {}
    out["devices"] = [dict(d) for d in conn.execute("SELECT * FROM byod_devices WHERE request_id = ? ORDER BY created_at", (r["id"],))]
    if full:
        out["parent_signature"], out["teacher_signature"] = r["parent_signature"], r["teacher_signature"]
        out["events"] = [dict(e) for e in conn.execute("SELECT at, actor, action, detail FROM byod_events WHERE request_id = ? ORDER BY at", (r["id"],))]
    owner, manage = r["teacher_id"] == user["id"], can_manage_byod(user, r["campus"])
    st = r["status"]
    out["permissions"] = {
        "can_teacher_sign": owner and st == "waiting_teacher",
        "can_resend": owner and st == "waiting_parent",
        "can_cancel": (owner or manage) and st in ("waiting_parent", "waiting_teacher", "waiting_ict", "approved"),
        "can_decide": manage and (st == "waiting_ict" or (st == "approved" and bool(r["pending_end_date"]))),
        "can_revoke": manage and st == "approved",
        "can_extend": owner and st == "approved" and not r["pending_end_date"] and r["extended_count"] < 1
                      and out["effective_status"] in ("active", "scheduled"),
    }
    return out


@api.post("/byod/projects")
async def create_byod_project(body: ByodProjectIn, user: dict = Depends(get_current_user)):
    if user["role"] not in ("staff", "admin", "super_admin") + CAMPUS_BOUND:
        raise HTTPException(403, "Akun ini tidak dapat membuat permohonan BYOD")
    campus = (user.get("campus") or body.campus or "").strip()
    if campus not in [c for c in VALID_CAMPUSES if c]:
        raise HTTPException(400, "Kampus tidak valid atau belum diisi pada akun Anda.")
    try:
        byod.check_period(body.start_date, body.end_date, _today_local())
        byod.check_hours(body.hour_from, body.hour_to)
    except byod.ByodError as e:
        raise _byod_err(e)
    students = []
    for s in body.students:
        email = s.parent_email.strip().lower()
        if email and not _EMAIL_RE.match(email):
            raise HTTPException(400, f"Email orang tua {s.name} tidak valid.")
        phone = normalize_phone(s.parent_phone)
        if not email and not phone:
            raise HTTPException(400, f"Isi email atau nomor WhatsApp orang tua untuk {s.name}.")
        students.append((s, email, phone))
    conn = get_conn()
    ensure_policy_compliant(conn, user["id"])
    ts, pid = now_iso(), str(uuid.uuid4())
    conn.execute("""INSERT INTO byod_projects (id,campus,name,subject,location,start_date,end_date,hour_from,hour_to,teacher_id,teacher_name,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (pid, campus, body.name.strip(), body.subject.strip(), body.location.strip(),
                                                           body.start_date[:10], body.end_date[:10], body.hour_from, body.hour_to, user["id"], user["name"], ts))
    project = dict(conn.execute("SELECT * FROM byod_projects WHERE id = ?", (pid,)).fetchone())
    created = []
    for s, email, phone in students:
        rid = str(uuid.uuid4())
        tok, tok_hash, exp = byod.new_token()
        conn.execute("""INSERT INTO byod_requests (id,number,project_id,campus,teacher_id,teacher_name,student_name,student_class,student_no,parent_name,
                        parent_relation,parent_email,parent_phone,status,token_hash,token_expires_at,terms_version,valid_from,valid_to,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'waiting_parent',?,?,?,?,?,?,?)""",
                     (rid, byod.next_number(conn, _local_now().year), pid, campus, user["id"], user["name"], s.name.strip(), s.class_name.strip(),
                      s.student_no.strip(), s.parent_name.strip(), s.parent_relation.strip(), email, phone, tok_hash, exp, byod.TERMS_VERSION,
                      body.start_date[:10], body.end_date[:10], ts, ts))
        req = dict(conn.execute("SELECT * FROM byod_requests WHERE id = ?", (rid,)).fetchone())
        byod.add_event(conn, rid, user["name"], "created", "Permohonan dibuat oleh guru pendamping")
        sent = _byod_send_parent_link(conn, req, project, tok)
        byod.add_event(conn, rid, user["name"], "link_sent", ", ".join(k for k, v in sent.items() if v) or "tautan disalin manual")
        created.append({"id": rid, "number": req["number"], "student_name": req["student_name"], "link": _byod_link(tok), "sent": sent})
    conn.commit()
    conn.close()
    return {"project_id": pid, "requests": created}


@api.get("/byod/requests")
async def list_byod_requests(scope: str = "mine", status: Optional[str] = None, user: dict = Depends(get_current_user)):
    """scope=mine: requests I opened as teacher; manage: what my campus ICT handles (all campuses for super admin / admin); all: leaders."""
    conds, params = [], []
    if scope == "all":
        if user["role"] not in ("leader", "super_admin", "admin"):
            raise HTTPException(403, "Tidak diizinkan")
    elif scope == "manage":
        if user["role"] in ("super_admin", "admin"):
            pass
        elif user["role"] in CAMPUS_BOUND:
            conds.append("r.campus = ?"); params.append(user.get("campus") or "")
        else:
            raise HTTPException(403, "Tidak diizinkan")
    else:
        conds.append("r.teacher_id = ?"); params.append(user["id"])
    if status:
        conds.append("r.status = ?"); params.append(status)
    conn = get_conn()
    rows = conn.execute(f"""SELECT r.*, p.name AS project_name FROM byod_requests r JOIN byod_projects p ON p.id = r.project_id
                            {'WHERE ' + ' AND '.join(conds) if conds else ''} ORDER BY r.created_at DESC LIMIT 500""", params).fetchall()
    today = _today_local()
    out = []
    for r in rows:
        d = {k: v for k, v in dict(r).items() if k not in ("token_hash", "token_expires_at", "parent_signature", "teacher_signature", "parent_ua", "teacher_ua")}
        d["effective_status"] = byod.effective_status(dict(r), today)
        out.append(d)
    conn.close()
    return out


@api.get("/byod/requests/{rid}")
async def get_byod_request(rid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = _byod_row(conn, rid)
    if not _byod_visible(user, r):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    view = _byod_view(conn, user, r)
    conn.close()
    return view


@api.post("/byod/requests/{rid}/resend")
async def resend_byod_link(rid: str, user: dict = Depends(get_current_user)):
    """New one-time link (the old one stops working)."""
    conn = get_conn()
    r = _byod_row(conn, rid)
    if r["teacher_id"] != user["id"] or r["status"] != "waiting_parent":
        conn.close()
        raise HTTPException(403 if r["teacher_id"] != user["id"] else 409, "Tautan hanya dapat dikirim ulang oleh guru pendamping saat menunggu orang tua.")
    tok, tok_hash, exp = byod.new_token()
    conn.execute("UPDATE byod_requests SET token_hash = ?, token_expires_at = ?, updated_at = ? WHERE id = ?", (tok_hash, exp, now_iso(), rid))
    project = dict(conn.execute("SELECT * FROM byod_projects WHERE id = ?", (r["project_id"],)).fetchone())
    sent = _byod_send_parent_link(conn, r, project, tok)
    byod.add_event(conn, rid, user["name"], "link_resent", ", ".join(k for k, v in sent.items() if v) or "tautan disalin manual")
    conn.commit()
    conn.close()
    return {"link": _byod_link(tok), "sent": sent}


# ---- public (parent, no account) ----
def _byod_by_token(conn, token: str) -> dict:
    r = conn.execute("SELECT * FROM byod_requests WHERE token_hash = ? AND token_hash != ''", (byod.hash_token(token),)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "Tautan tidak valid atau formulir sudah ditandatangani.")
    r = dict(r)
    if r["status"] != "waiting_parent":
        conn.close()
        raise HTTPException(410, "Formulir ini sudah tidak menunggu persetujuan.")
    if r["token_expires_at"] < now_iso():
        conn.close()
        raise HTTPException(410, "Tautan sudah kedaluwarsa. Mintalah guru pendamping mengirim ulang.")
    return r


@api.get("/public/byod/{token}")
async def public_byod_form(token: str):
    conn = get_conn()
    r = _byod_by_token(conn, token)
    p = dict(conn.execute("SELECT * FROM byod_projects WHERE id = ?", (r["project_id"],)).fetchone())
    conn.close()
    return {"number": r["number"], "student_name": r["student_name"], "student_class": r["student_class"], "student_no": r["student_no"],
            "parent_name": r["parent_name"], "parent_relation": r["parent_relation"], "campus": r["campus"], "teacher_name": r["teacher_name"],
            "terms_version": r["terms_version"], "expires_at": r["token_expires_at"],
            "project": {k: p[k] for k in ("name", "subject", "location", "start_date", "end_date", "hour_from", "hour_to")},
            "valid_from": r["valid_from"], "valid_to": r["valid_to"],
            "max_devices": byod.MAX_DEVICES, "device_kinds": list(byod.DEVICE_KINDS)}


class ByodDeviceIn(BaseModel):
    kind: str
    brand: str = ""
    model: str = ""
    os: str = ""
    os_version: str = ""
    mac: str = ""
    serial: str = ""


class ByodParentSignIn(BaseModel):
    parent_name: str = Field(..., min_length=3, max_length=120)
    parent_relation: str = Field(..., min_length=2, max_length=60)
    devices: List[ByodDeviceIn]
    statements: dict = {}
    signature: str
    text_hash: str = ""
    lang: str = ""


BYOD_STATEMENTS = ("own_device", "liability", "project_only", "rules", "monitoring", "revoke", "privacy")


def _check_signature(data: str):
    if not data.startswith("data:image/png;base64,") or len(data) > 80_000 or len(data) < 400:
        raise HTTPException(400, "Tanda tangan belum diisi atau tidak valid. Gambar tanda tangan Anda pada kotak yang tersedia.")


@api.post("/public/byod/{token}/sign")
async def public_byod_sign(token: str, body: ByodParentSignIn, request: Request):
    if not all(body.statements.get(k) is True for k in BYOD_STATEMENTS):
        raise HTTPException(400, "Semua pernyataan wajib dicentang.")
    _check_signature(body.signature)
    try:
        devices = byod.validate_devices([d.model_dump() for d in body.devices])
    except byod.ByodError as e:
        raise _byod_err(e)
    conn = get_conn()
    r = _byod_by_token(conn, token)
    dup = byod.mac_in_use(conn, [d["mac"] for d in devices], exclude_request_id=r["id"], today=_today_local())
    if dup:
        conn.close()
        raise HTTPException(409, f"MAC address {dup} sudah terdaftar pada permohonan BYOD lain. Periksa kembali atau hubungi guru pendamping.")
    ts, ip = now_iso(), _client_ip(request)
    conn.execute("DELETE FROM byod_devices WHERE request_id = ?", (r["id"],))
    for d in devices:
        conn.execute("""INSERT INTO byod_devices (id,request_id,kind,brand,model,os,os_version,mac,serial,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (str(uuid.uuid4()), r["id"], d["kind"], d["brand"], d["model"], d["os"], d["os_version"], d["mac"], d["serial"], ts))
    conn.execute("""UPDATE byod_requests SET status = 'waiting_teacher', parent_name = ?, parent_relation = ?, parent_signed_at = ?, parent_signed_name = ?,
                    parent_signature = ?, parent_ip = ?, parent_ua = ?, parent_text_hash = ?, parent_lang = ?, token_hash = '', updated_at = ? WHERE id = ?""",
                 (body.parent_name.strip(), body.parent_relation.strip(), ts, body.parent_name.strip(), body.signature, ip,
                  request.headers.get("user-agent", "")[:300], body.text_hash[:128], body.lang[:8], ts, r["id"]))
    byod.add_event(conn, r["id"], body.parent_name.strip(), "parent_signed", f'{len(devices)} perangkat', ip)
    teacher = conn.execute("SELECT email FROM users WHERE id = ?", (r["teacher_id"],)).fetchone()
    r.update(parent_name=body.parent_name.strip())
    if teacher:
        _byod_notify(conn, [teacher["email"]], "Orang tua telah menandatangani", "Giliran Anda menandatangani", r,
                     f'Orang tua {r["student_name"]} sudah menyetujui. Mohon tanda tangani permohonan di aplikasi YPJ Assets agar dilanjutkan ke ICT.', "byod_teacher")
    conn.commit()
    conn.close()
    return {"ok": True, "number": r["number"]}


# ---- teacher ----
class ByodTeacherSignIn(BaseModel):
    signed_name: str
    signature: str
    agree: bool = False


@api.put("/byod/requests/{rid}/teacher-sign")
async def byod_teacher_sign(rid: str, body: ByodTeacherSignIn, request: Request, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = _byod_row(conn, rid)
    if r["teacher_id"] != user["id"]:
        conn.close()
        raise HTTPException(403, "Hanya guru pendamping permohonan ini yang dapat menandatangani.")
    if r["status"] != "waiting_teacher":
        conn.close()
        raise HTTPException(409, "Permohonan ini tidak sedang menunggu tanda tangan guru (orang tua harus menandatangani lebih dulu).")
    if not body.agree:
        conn.close()
        raise HTTPException(400, "Centang pernyataan guru pendamping.")
    if _norm_name(body.signed_name) != _norm_name(user.get("name", "")):
        conn.close()
        raise HTTPException(400, "Nama yang diketik harus sama dengan nama akun Anda.")
    try:
        _check_signature(body.signature)
    except HTTPException:
        conn.close()
        raise
    ts, ip = now_iso(), _client_ip(request)
    conn.execute("""UPDATE byod_requests SET status = 'waiting_ict', teacher_signed_at = ?, teacher_signed_name = ?, teacher_signature = ?, teacher_ip = ?,
                    teacher_ua = ?, updated_at = ? WHERE id = ?""", (ts, body.signed_name.strip(), body.signature, ip, request.headers.get("user-agent", "")[:300], ts, rid))
    byod.add_event(conn, rid, user["name"], "teacher_signed", "", ip)
    _byod_notify(conn, loan_manager_emails(conn, r["campus"], "IT Equipment"), "BYOD menunggu persetujuan ICT", "Permohonan BYOD Menunggu Persetujuan", r,
                 "Orang tua dan guru pendamping sudah menandatangani. Mohon periksa perangkat dan beri keputusan di aplikasi YPJ Assets.", "byod_ict")
    conn.commit()
    r = _byod_row(conn, rid)
    view = _byod_view(conn, user, r)
    conn.close()
    return view


class ByodDecideIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = ""
    devices: List[dict] = []          # corrections by ICT: [{id, mac?, brand?, model?, os?, os_version?}]


@api.put("/byod/requests/{rid}/decide")
async def byod_decide(rid: str, body: ByodDecideIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = _byod_row(conn, rid)
    if not can_manage_byod(user, r["campus"]):
        conn.close()
        raise HTTPException(403, "Hanya ICT Admin kampus ini yang dapat memutuskan.")
    extension = r["status"] == "approved" and bool(r["pending_end_date"])
    if r["status"] != "waiting_ict" and not extension:
        conn.close()
        raise HTTPException(409, "Permohonan ini tidak sedang menunggu keputusan ICT.")
    if body.decision == "rejected" and not body.note.strip():
        conn.close()
        raise HTTPException(400, "Alasan penolakan wajib diisi.")
    ts = now_iso()
    if body.decision == "approved" and not extension:
        try:
            for c in body.devices:
                d = conn.execute("SELECT * FROM byod_devices WHERE id = ? AND request_id = ?", (c.get("id"), rid)).fetchone()
                if not d:
                    raise byod.ByodError("Perangkat tidak ditemukan.", "device", 404)
                fix = {k: (str(c[k]).strip() if k != "mac" else byod.normalize_mac(c[k])) for k in ("mac", "brand", "model", "os", "os_version") if c.get(k)}
                if fix:
                    conn.execute(f"UPDATE byod_devices SET {', '.join(k + ' = ?' for k in fix)} WHERE id = ?", [*fix.values(), d["id"]])
            macs = [x["mac"] for x in conn.execute("SELECT mac FROM byod_devices WHERE request_id = ?", (rid,))]
            dup = byod.mac_in_use(conn, macs, exclude_request_id=rid, today=_today_local())
            if dup:
                raise byod.ByodError(f"MAC address {dup} sudah terdaftar pada permohonan BYOD lain.", "mac", 409)
        except byod.ByodError as e:
            conn.rollback()
            conn.close()
            raise _byod_err(e)
    if extension:
        if body.decision == "approved":
            conn.execute("UPDATE byod_requests SET valid_to = pending_end_date, pending_end_date = NULL, extended_count = extended_count + 1, ict_by = ?, ict_by_name = ?, ict_at = ?, ict_note = ?, updated_at = ? WHERE id = ?",
                         (user["id"], user["name"], ts, body.note.strip(), ts, rid))
        else:
            conn.execute("UPDATE byod_requests SET pending_end_date = NULL, ict_note = ?, updated_at = ? WHERE id = ?", (body.note.strip(), ts, rid))
        byod.add_event(conn, rid, user["name"], "extension_" + body.decision, body.note.strip())
    else:
        conn.execute("UPDATE byod_requests SET status = ?, ict_by = ?, ict_by_name = ?, ict_at = ?, ict_note = ?, updated_at = ? WHERE id = ?",
                     (body.decision, user["id"], user["name"], ts, body.note.strip(), ts, rid))
        byod.add_event(conn, rid, user["name"], body.decision, body.note.strip())
    r = _byod_row(conn, rid)
    teacher = conn.execute("SELECT email FROM users WHERE id = ?", (r["teacher_id"],)).fetchone()
    if teacher:
        approved = body.decision == "approved"
        _byod_notify(conn, [teacher["email"]], "BYOD disetujui ICT" if approved else "BYOD ditolak ICT",
                     "Permohonan BYOD Disetujui" if approved else "Permohonan BYOD Ditolak", r,
                     ("Akses WiFi sekolah akan diberikan untuk perangkat siswa pada periode tersebut." if approved
                      else f'Alasan: {body.note.strip()}'), "byod_decided")
    conn.commit()
    view = _byod_view(conn, user, r)
    conn.close()
    return view


class ByodReasonIn(BaseModel):
    reason: str = ""


@api.put("/byod/requests/{rid}/cancel")
async def byod_cancel(rid: str, body: ByodReasonIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = _byod_row(conn, rid)
    if not (r["teacher_id"] == user["id"] or can_manage_byod(user, r["campus"])):
        conn.close()
        raise HTTPException(403, "Tidak diizinkan")
    if r["status"] not in ("waiting_parent", "waiting_teacher", "waiting_ict", "approved"):
        conn.close()
        raise HTTPException(409, "Permohonan ini tidak dapat dibatalkan lagi.")
    conn.execute("UPDATE byod_requests SET status = 'cancelled', token_hash = '', end_reason = ?, updated_at = ? WHERE id = ?", (body.reason.strip(), now_iso(), rid))
    byod.add_event(conn, rid, user["name"], "cancelled", body.reason.strip())
    conn.commit()
    view = _byod_view(conn, user, _byod_row(conn, rid))
    conn.close()
    return view


@api.put("/byod/requests/{rid}/revoke")
async def byod_revoke(rid: str, body: ByodReasonIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    r = _byod_row(conn, rid)
    if not can_manage_byod(user, r["campus"]):
        conn.close()
        raise HTTPException(403, "Hanya ICT Admin kampus ini yang dapat mencabut akses.")
    if r["status"] != "approved":
        conn.close()
        raise HTTPException(409, "Hanya permohonan yang sudah disetujui yang dapat dicabut.")
    if len(body.reason.strip()) < 3:
        conn.close()
        raise HTTPException(400, "Alasan pencabutan wajib diisi.")
    conn.execute("UPDATE byod_requests SET status = 'revoked', pending_end_date = NULL, end_reason = ?, updated_at = ? WHERE id = ?", (body.reason.strip(), now_iso(), rid))
    byod.add_event(conn, rid, user["name"], "revoked", body.reason.strip())
    r = _byod_row(conn, rid)
    teacher = conn.execute("SELECT email FROM users WHERE id = ?", (r["teacher_id"],)).fetchone()
    if teacher:
        _byod_notify(conn, [teacher["email"]], "Akses BYOD dicabut", "Akses BYOD Dicabut", r, f'Alasan: {body.reason.strip()}', "byod_revoked")
    conn.commit()
    view = _byod_view(conn, user, r)
    conn.close()
    return view


class ByodExtendIn(BaseModel):
    new_end_date: str


@api.put("/byod/requests/{rid}/extend")
async def byod_extend(rid: str, body: ByodExtendIn, user: dict = Depends(get_current_user)):
    """The teacher asks ICT for one extension (no new parent signature: same project, same devices)."""
    conn = get_conn()
    r = _byod_row(conn, rid)
    if r["teacher_id"] != user["id"]:
        conn.close()
        raise HTTPException(403, "Hanya guru pendamping yang dapat meminta perpanjangan.")
    if r["status"] != "approved" or r["pending_end_date"] or r["extended_count"] >= 1:
        conn.close()
        raise HTTPException(409, "Perpanjangan hanya dapat diminta satu kali untuk permohonan yang sedang berlaku.")
    try:
        new_end, cur_end = byod.parse_date(body.new_end_date), byod.parse_date(r["valid_to"])
    except byod.ByodError as e:
        conn.close()
        raise _byod_err(e)
    if new_end <= cur_end or (new_end - cur_end).days > byod.MAX_EXTEND_DAYS:
        conn.close()
        raise HTTPException(400, f"Tanggal baru harus setelah {r['valid_to']} dan paling lama {byod.MAX_EXTEND_DAYS} hari dari tanggal selesai saat ini.")
    if byod.effective_status(r, _today_local()) == "expired":
        conn.close()
        raise HTTPException(409, "Permohonan sudah berakhir. Buat permohonan baru.")
    conn.execute("UPDATE byod_requests SET pending_end_date = ?, updated_at = ? WHERE id = ?", (new_end.isoformat(), now_iso(), rid))
    byod.add_event(conn, rid, user["name"], "extension_requested", new_end.isoformat())
    _byod_notify(conn, loan_manager_emails(conn, r["campus"], "IT Equipment"), "Perpanjangan BYOD", "Permintaan Perpanjangan BYOD", r,
                 f'Guru pendamping meminta perpanjangan sampai {new_end.isoformat()}.', "byod_ict")
    conn.commit()
    view = _byod_view(conn, user, _byod_row(conn, rid))
    conn.close()
    return view


@api.get("/reports/byod-devices")
async def report_byod_devices(user: dict = Depends(get_current_user)):
    """Devices to allow on the school WiFi: approved requests that have not ended yet (for the ICT Admin's campus)."""
    if user["role"] not in ("super_admin", "admin", "leader") + CAMPUS_BOUND:
        raise HTTPException(403, "Tidak diizinkan")
    import openpyxl
    conn = get_conn()
    conds, params = ["r.status = 'approved'", "r.valid_to >= ?"], [_today_local().isoformat()]
    if user["role"] in CAMPUS_BOUND:
        conds.append("r.campus = ?"); params.append(user.get("campus") or "")
    rows = conn.execute(f"""SELECT r.number, r.campus, r.student_name, r.student_class, r.teacher_name, r.valid_from, r.valid_to, p.hour_from, p.hour_to,
                                   p.name AS project, d.kind, d.brand, d.model, d.os, d.os_version, d.mac
                            FROM byod_requests r JOIN byod_projects p ON p.id = r.project_id JOIN byod_devices d ON d.request_id = r.id
                            WHERE {' AND '.join(conds)} ORDER BY r.campus, r.valid_to, r.student_name""", params).fetchall()
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BYOD aktif"
    ws.append(["No. Permohonan", "Kampus", "Siswa", "Kelas", "Guru pendamping", "Project", "Mulai", "Selesai", "Jam dari", "Jam sampai",
               "Jenis", "Merek", "Model", "OS", "Versi OS", "MAC address"])
    _style_header(ws)
    for r in rows:
        ws.append([r["number"], r["campus"], r["student_name"], r["student_class"], r["teacher_name"], r["project"], r["valid_from"], r["valid_to"],
                   r["hour_from"], r["hour_to"], r["kind"], r["brand"], r["model"], r["os"], r["os_version"], r["mac"]])
    return _xlsx_response(wb, f"byod-devices-{datetime.now().strftime('%Y%m%d')}.xlsx")


def send_byod_reminders():
    """Daily: warn teacher + ICT 3 days before a BYOD approval ends, and ICT the day after it ended (remove WiFi access)."""
    conn = get_conn()
    try:
        today = _local_now().date()
        for days, kind, heading, text in (
                (3, "byod_expiring", "BYOD Akan Berakhir", "Izin BYOD akan berakhir dalam 3 hari. Ajukan perpanjangan bila masih diperlukan."),
                (-1, "byod_expired", "BYOD Berakhir", "Izin BYOD telah berakhir. ICT: mohon cabut akses WiFi perangkat siswa.")):
            target = (today + timedelta(days=days)).isoformat()
            for row in conn.execute("SELECT * FROM byod_requests WHERE status = 'approved' AND valid_to = ?", (target,)).fetchall():
                r = dict(row)
                if _already_notified(conn, kind, r["id"], hours=48):
                    continue
                t = conn.execute("SELECT email FROM users WHERE id = ?", (r["teacher_id"],)).fetchone()
                to = ([t["email"]] if t and days > 0 else []) + loan_manager_emails(conn, r["campus"], "IT Equipment")
                _byod_notify(conn, to, heading, heading, r, text, kind)
    finally:
        conn.close()


app.include_router(api)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Serve React build in production (frontend/build lives one level up from backend/)
BUILD_DIR = ROOT_DIR.parent / "frontend" / "build"
if BUILD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(BUILD_DIR / "static")), name="react-static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # root-level build files (favicon, app icons) are served as files; everything else is the SPA
        if full_path and "/" not in full_path and not full_path.startswith(".") and (BUILD_DIR / full_path).is_file() and full_path != "index.html":
            return FileResponse(BUILD_DIR / full_path)
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
             "Classroom projector 3500 lumens", "YPJ TPRA", "Room 204", "active",
             680.00, "2022-03-10", 6, "2025-03-10", "EPL3500-204", "Epson", None, "Room 204"),
            ("Microscope Set Olympus CX23", "LAB-MIC-0007", "Lab Equipment",
             "Set of 8 student microscopes", "YPJ Kuala Kencana", "Biology Lab", "active",
             4200.00, "2021-09-01", 10, "2024-09-01", "OLY-CX23-S8", "Olympus", staff_id, "Maria Hernandez"),
            ("Steelcase Student Desks (40)", "FUR-DSK-0040", "Furniture",
             "Set of 40 height-adjustable desks", "YPJ Kuala Kencana", "Room 112", "active",
             8000.00, "2020-07-20", 12, "2030-07-20", "SC-LOT-112", "Steelcase", None, "Room 112"),
            ("Toyota Hiace School Bus", "VEH-BUS-0001", "Vehicles",
             "16-seater school transport van", "YPJ TPRA", "Main Garage", "active",
             35000.00, "2019-04-12", 8, "2024-04-12", "TYT-HIACE-19", "Toyota", None, "Transport Dept"),
            ("iPad Pro 11\" Cart (30 units)", "IT-IPD-0030", "IT Equipment",
             "Mobile cart of iPads for classroom use", "YPJ Kuala Kencana", "Library", "active",
             27000.00, "2024-01-20", 5, "2027-01-20", "IPD-CART-LIB1", "Apple", None, "Library"),
            ("Smart Interactive Whiteboard", "AV-IWB-0003", "AV Equipment",
             "Smart Board 6065 65-inch", "YPJ TPRA", "Room 301", "in_repair",
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
    scheduler = BackgroundScheduler(timezone="Asia/Jayapura")
    scheduler.add_job(send_return_reminders, "cron", hour=8, minute=0)
    scheduler.add_job(send_asset_due_reminders, "cron", hour=8, minute=5)
    scheduler.add_job(send_assignment_reminders, "cron", hour=8, minute=10)
    scheduler.add_job(send_loan_reminders, "cron", hour=8, minute=15)
    scheduler.add_job(send_byod_reminders, "cron", hour=8, minute=20)
    scheduler.add_job(mark_overdue_loans, "interval", minutes=15)
    scheduler.start()
    mode = "production" if BUILD_DIR.exists() else "development"
    logger.info(f"Startup complete [{mode}] — DB: {DB_PATH}")
