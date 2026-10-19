from conftest import auth
import server

OK = {"version": server.POLICY_VERSION, "read_all": True, "will_comply": True, "accept_sanctions": True, "text_hash": "abc", "lang": "ID"}


def test_me_reports_policy_not_accepted_then_accepted(client, make_user):
    u = make_user("staff", accepted=False)
    me = client.get("/api/auth/me", headers=auth(u)).json()
    assert me["policy_required"] and not me["policy_accepted"]
    r = client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "  STAFF   user "})
    assert r.status_code == 200 and r.json()["policy_accepted"]
    assert client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]


def test_requires_all_statements_and_matching_name(client, make_user):
    u = make_user("staff", accepted=False)
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user", "accept_sanctions": False}).status_code == 400
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "Someone Else"}).status_code == 400
    assert not client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]


def test_new_version_forces_reconfirmation(client, make_user, monkeypatch):
    u = make_user("staff", accepted=False)
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user"}).status_code == 200
    monkeypatch.setattr(server, "POLICY_VERSION", "9999.1")
    assert not client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user"}).status_code == 409


def test_leader_not_required_and_admin_lists(client, make_user):
    leader, admin, staff = make_user("leader"), make_user("admin", accepted=False), make_user("staff", accepted=False)
    me = client.get("/api/auth/me", headers=auth(leader)).json()
    assert not me["policy_required"] and me["policy_accepted"]
    client.post("/api/policy/accept", headers=auth(staff), json={**OK, "signed_name": "staff user"})
    items = {i["id"]: i for i in client.get("/api/policy/acceptances", headers=auth(admin)).json()["items"]}
    assert items[staff["id"]]["current"] and not items[admin["id"]]["current"]
    assert client.get("/api/policy/acceptances", headers=auth(staff)).status_code == 403
    assert client.get("/api/reports/policy-acceptances", headers=auth(admin)).status_code == 200


def _shared_asset(db, campus="YPJ Kuala Kencana"):
    aid = server.uuid.uuid4().hex
    db.execute("""INSERT INTO assets (id,name,asset_tag,category,campus,location,status,purchase_price,purchase_date,user_type,created_at,updated_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
               (aid, "Laptop", "TAG-" + aid[:4], "IT Equipment", campus, "Lab", "active", 1, "2024-01-01", "shared", server.now_iso(), server.now_iso()))
    db.commit()
    return aid


def test_cannot_borrow_before_accepting_policy(client, make_user, db):
    aid = _shared_asset(db)
    unsigned, signed = make_user("staff", accepted=False), make_user("staff")
    r = client.post(f"/api/assets/{aid}/loan-request", headers=auth(unsigned), json={"purpose": "kelas"})
    assert r.status_code == 403 and "kebijakan" in r.json()["detail"]
    assert client.post(f"/api/assets/{aid}/loan-request", headers=auth(signed), json={"purpose": "kelas"}).status_code == 200


def test_cannot_assign_to_user_without_policy(client, make_user, db):
    aid = _shared_asset(db)
    admin, unsigned, signed = make_user("super_admin"), make_user("staff", accepted=False), make_user("staff")
    r = client.post(f"/api/assets/{aid}/transfer", headers=auth(admin), json={"new_owner_name": "x", "new_owner_user_id": unsigned["id"]})
    assert r.status_code == 403 and "belum menyetujui" in r.json()["detail"]
    r = client.post("/api/assignments/bulk", headers=auth(admin), json={"asset_ids": [aid], "to_user_id": signed["id"], "kind": "personal"})
    assert r.status_code == 200 and r.json()["created"] == 1


def test_loan_photo_upload_limited_to_50kb(client, make_user):
    u = make_user("staff")
    small, big = b"x" * 40_000, b"x" * 60_000
    ok = client.post("/api/upload?purpose=loan", headers=auth(u), files={"file": ("a.jpg", small, "image/jpeg")})
    assert ok.status_code == 200
    r = client.post("/api/upload?purpose=loan", headers=auth(u), files={"file": ("b.jpg", big, "image/jpeg")})
    assert r.status_code == 413 and "50 KB" in r.json()["detail"]
    assert client.post("/api/upload", headers=auth(u), files={"file": ("b.jpg", big, "image/jpeg")}).status_code == 200  # other uploads unchanged
