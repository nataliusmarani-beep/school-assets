import os
import sys
import tempfile
from pathlib import Path

import pytest

# Use a throwaway data dir so tests never touch the real database/uploads.
_TMP = tempfile.mkdtemp(prefix="ypj-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


@pytest.fixture()
def db():
    """Fresh schema for every test."""
    for f in Path(_TMP).glob("schoolassets.db*"):
        f.unlink()
    server.init_db()
    conn = server.get_conn()
    yield conn
    conn.close()


@pytest.fixture()
def make_user(db):
    def _make(role="staff", campus="YPJ Kuala Kencana", email=None):
        uid = server.uuid.uuid4().hex
        email = email or f"{role}-{uid[:6]}@example.com"
        db.execute("INSERT INTO users (id,email,name,role,campus,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                   (uid, email, f"{role} user", role, campus, server.hash_password("secret123"), server.now_iso()))
        db.commit()
        return {"id": uid, "email": email, "role": role, "campus": campus}
    return _make


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    return TestClient(server.app)


def auth(user):
    return {"Authorization": "Bearer " + server.create_token(user["id"], user["email"], user["role"])}
