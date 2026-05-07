from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import uuid
import sqlite3
import json
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, UploadFile, File, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr


# ---- Config ----
# In production Railway sets DATA_DIR to a mounted volume path
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / os.environ.get("DB_FILE", "schoolassets.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

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


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'staff',
        department TEXT,
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
    """)
    conn.commit()
    # Migrations for existing databases
    cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()]
    if "campus" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN campus TEXT NOT NULL DEFAULT ''")
        conn.commit()
    conn.close()


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


async def admin_required(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ---- Models ----
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["admin", "staff"] = "staff"
    department: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AssetIn(BaseModel):
    name: str
    asset_tag: str
    category: str
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


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    asset_tag: Optional[str] = None
    category: Optional[str] = None
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


def calc_depreciation(purchase_price: float, purchase_date: str, useful_life_years: int) -> dict:
    try:
        pdate = datetime.fromisoformat(purchase_date.replace("Z", "+00:00"))
        if pdate.tzinfo is None:
            pdate = pdate.replace(tzinfo=timezone.utc)
    except Exception:
        return {"current_value": purchase_price, "accumulated": 0, "annual": 0, "age_years": 0}
    age = (datetime.now(timezone.utc) - pdate).days / 365.25
    annual = purchase_price / max(useful_life_years, 1)
    accumulated = min(annual * age, purchase_price)
    current = max(purchase_price - accumulated, 0)
    return {
        "current_value": round(current, 2),
        "accumulated": round(accumulated, 2),
        "annual": round(annual, 2),
        "age_years": round(age, 2),
    }


# ---- Auth endpoints ----
@api.post("/auth/register")
async def register(body: UserCreate, response: Response):
    conn = get_conn()
    email = body.email.lower()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id,email,name,role,department,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
        (uid, email, body.name, body.role, body.department, hash_password(body.password), now_iso()),
    )
    conn.commit()
    conn.close()
    token = create_token(uid, email, body.role)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=7*24*3600, path="/")
    return {"id": uid, "email": email, "name": body.name, "role": body.role, "department": body.department, "token": token}


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
    rows = conn.execute("SELECT id,email,name,role,department,created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@api.post("/users")
async def create_user(body: UserCreate, _: dict = Depends(admin_required)):
    return await register(body, Response())


@api.delete("/users/{uid}")
async def delete_user(uid: str, _: dict = Depends(admin_required)):
    conn = get_conn()
    res = conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    if res.rowcount == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True}


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
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"SELECT * FROM assets {where} ORDER BY created_at DESC", params).fetchall()
    conn.close()
    assets = [row_to_dict(r) for r in rows]
    for a in assets:
        a["depreciation"] = calc_depreciation(a["purchase_price"], a["purchase_date"], a.get("useful_life_years", 5))
    return assets


@api.post("/assets")
async def create_asset(body: AssetIn, user: dict = Depends(get_current_user)):
    aid = str(uuid.uuid4())
    ts = now_iso()
    conn = get_conn()
    conn.execute("""
        INSERT INTO assets (id,name,asset_tag,category,description,campus,location,status,
            purchase_price,purchase_date,useful_life_years,warranty_end_date,
            serial_number,supplier,assigned_to_user_id,assigned_to_name,
            photo_path,documents,created_at,updated_at,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        aid, body.name, body.asset_tag, body.category, body.description or "",
        body.campus or "", body.location, body.status, body.purchase_price, body.purchase_date,
        body.useful_life_years, body.warranty_end_date, body.serial_number or "",
        body.supplier or "", body.assigned_to_user_id, body.assigned_to_name,
        body.photo_path, json.dumps(body.documents), ts, ts, user["id"],
    ))
    if body.assigned_to_name:
        conn.execute("""
            INSERT INTO ownership_logs (id,asset_id,from_name,from_user_id,to_name,to_user_id,note,by,by_name,at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (str(uuid.uuid4()), aid, None, None, body.assigned_to_name,
              body.assigned_to_user_id, "Initial assignment", user["id"], user["name"], ts))
    conn.commit()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    conn.close()
    doc = row_to_dict(row)
    doc["depreciation"] = calc_depreciation(doc["purchase_price"], doc["purchase_date"], doc.get("useful_life_years", 5))
    return doc


@api.get("/assets/{aid}")
async def get_asset(aid: str, user: dict = Depends(get_current_user)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Asset not found")
    asset = row_to_dict(row)
    asset["depreciation"] = calc_depreciation(asset["purchase_price"], asset["purchase_date"], asset.get("useful_life_years", 5))
    asset["ownership_history"] = [
        dict(r) for r in conn.execute("SELECT * FROM ownership_logs WHERE asset_id = ? ORDER BY at DESC", (aid,)).fetchall()
    ]
    asset["faults"] = [
        dict(r) for r in conn.execute("SELECT * FROM faults WHERE asset_id = ? ORDER BY created_at DESC", (aid,)).fetchall()
    ]
    asset["compliance"] = [
        dict(r) for r in conn.execute("SELECT * FROM compliance WHERE asset_id = ? ORDER BY due_date ASC", (aid,)).fetchall()
    ]
    conn.close()
    return asset


@api.put("/assets/{aid}")
async def update_asset(aid: str, body: AssetUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates["updated_at"] = now_iso()
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
    conn.execute("DELETE FROM faults WHERE asset_id = ?", (aid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@api.post("/assets/{aid}/transfer")
async def transfer_asset(aid: str, body: TransferIn, user: dict = Depends(get_current_user)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Asset not found")
    asset = row_to_dict(row)
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
    if status:
        rows = conn.execute("SELECT * FROM faults WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM faults ORDER BY created_at DESC").fetchall()
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
    a = conn.execute("SELECT id FROM assets WHERE id = ?", (body.asset_id,)).fetchone()
    if not a:
        conn.close()
        raise HTTPException(404, "Asset not found")
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
async def update_fault(fid: str, body: FaultUpdate, user: dict = Depends(get_current_user)):
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
    rows = conn.execute("SELECT * FROM compliance ORDER BY due_date ASC").fetchall()
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


# ---- Dashboard ----
@api.get("/dashboard/stats")
async def dashboard_stats(user: dict = Depends(get_current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM assets").fetchall()
    assets = [row_to_dict(r) for r in rows]
    total_assets = len(assets)
    total_value = sum(a.get("purchase_price", 0) for a in assets)
    current_value = 0
    by_category: dict = {}
    by_status: dict = {}
    for a in assets:
        d = calc_depreciation(a["purchase_price"], a["purchase_date"], a.get("useful_life_years", 5))
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

    open_faults = conn.execute(
        "SELECT COUNT(*) FROM faults WHERE status IN ('open','in_progress')"
    ).fetchone()[0]
    recent_fault_rows = conn.execute("SELECT * FROM faults ORDER BY created_at DESC LIMIT 5").fetchall()
    recent_faults = []
    for f in recent_fault_rows:
        fd = dict(f)
        a = conn.execute("SELECT name FROM assets WHERE id = ?", (fd["asset_id"],)).fetchone()
        fd["asset_name"] = a["name"] if a else "(deleted)"
        recent_faults.append(fd)

    compliance_rows = conn.execute("SELECT * FROM compliance").fetchall()
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
    }


@api.get("/backup")
async def backup_db(user: dict = Depends(admin_required)):
    if not DB_PATH.exists():
        raise HTTPException(404, "Database file not found")
    return FileResponse(
        str(DB_PATH),
        media_type="application/octet-stream",
        filename=f"ypj-backup-{datetime.now().strftime('%Y%m%d')}.db",
    )


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

    admin = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
    if not admin:
        admin_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id,email,name,role,department,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
            (admin_id, admin_email, "Admin User", "admin", "Administration", hash_password(admin_password), now_iso()),
        )
        logger.info(f"Seeded admin: {admin_email}")
    else:
        admin_id = admin["id"]

    staff = conn.execute("SELECT id FROM users WHERE email = ?", (staff_email,)).fetchone()
    if not staff:
        staff_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id,email,name,role,department,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
            (staff_id, staff_email, "Maria Hernandez", "staff", "Science Department", hash_password(staff_password), now_iso()),
        )
        logger.info(f"Seeded staff: {staff_email}")
    else:
        staff_id = staff["id"]

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
            """, (aid, name, tag, cat, desc, campus, loc, status, price, pdate, life, warranty,
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
    mode = "production" if BUILD_DIR.exists() else "development"
    logger.info(f"Startup complete [{mode}] — DB: {DB_PATH}")
