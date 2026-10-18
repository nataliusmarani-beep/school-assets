from datetime import timedelta

import server
from conftest import auth

KK, TPRA = "YPJ Kuala Kencana", "YPJ TPRA"


def day(n):
    return (server._local_now() + timedelta(days=n)).strftime("%Y-%m-%d")


def seed_camera(db, campus=KK, aid="cam1", category="AV Equipment"):
    db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,purchase_price,purchase_date,created_at,updated_at) "
               "VALUES (?,?,?,?,?,'ICT',0,'2026-01-01','t','t')", (aid, "Canon EOS", f"YPJ-KAM-{aid}", category, campus))
    db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type, accessories) VALUES (?,1,'item','[\"Charger\",\"Tas\"]')", (aid,))
    db.execute("INSERT OR IGNORE INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES ('f1','loans/p.jpg','p.jpg','image/jpeg',1,'u',0,'t')")
    db.commit()


def request_body(aid="cam1", **kw):
    body = {"asset_id": aid, "start_at": f"{day(2)}T08:00", "end_at": f"{day(3)}T15:00", "purpose": "Dokumentasi", "terms_accepted": True}
    body.update(kw)
    return body


def full_cycle_unit(**kw):
    u = {"asset_id": "cam1", "physical": "baik", "function": "normal", "photo": "loans/p.jpg",
         "accessories": [{"name": "Charger", "ok": True}, {"name": "Tas", "ok": True}]}
    u.update(kw)
    return u


def test_request_decide_and_return_over_http(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    seed_camera(db)
    teacher = make_user("staff", KK)
    ict = make_user("ict_admin", KK)
    r = client.post("/api/loans", headers=auth(teacher), json=request_body(
        start_at="2026-08-05T08:00", end_at="2026-08-06T15:00"))
    assert r.status_code == 200, r.text
    loan = r.json()
    assert loan["status"] == "pending_ict" and loan["number"] == "PJM-2026-0001"
    assert db.execute("SELECT COUNT(*) FROM notification_queue").fetchone()[0] >= 1

    # a teacher cannot decide, the campus ICT Admin can
    assert client.put(f"/api/loans/{loan['id']}/decide", headers=auth(teacher), json={"decision": "approved"}).status_code == 403
    d = client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved"})
    assert d.status_code == 200 and d.json()["status"] == "approved"

    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 8, 30))
    out = client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [full_cycle_unit()]})
    assert out.status_code == 200 and out.json()["status"] == "in_use"
    back = client.post(f"/api/loans/{loan['id']}/check-in", headers=auth(ict),
                       json={"units": [full_cycle_unit(result="damaged", physical="retak", note="Lensa retak")]})
    assert back.status_code == 200 and back.json()["status"] == "problem" and len(back.json()["faults"]) == 1
    assert client.get("/api/faults", headers=auth(ict)).json()[0]["asset_id"] == "cam1"
    hist = client.get("/api/loans/assets/cam1/history", headers=auth(ict)).json()
    assert hist[0]["pre_photo"] == "loans/p.jpg" and hist[0]["in_check"]["result"] == "damaged"


def test_other_campus_ict_admin_cannot_manage(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    seed_camera(db, campus=KK)
    teacher = make_user("staff", KK)
    loan = client.post("/api/loans", headers=auth(teacher), json=request_body(start_at="2026-08-05T08:00", end_at="2026-08-05T15:00")).json()
    other = make_user("ict_admin", TPRA)
    plain_admin = make_user("admin", KK)
    for u in (other, plain_admin):                       # wrong campus / ICT category belongs to ICT Admin
        assert client.put(f"/api/loans/{loan['id']}/decide", headers=auth(u), json={"decision": "approved"}).status_code == 403
    assert client.get("/api/loans", headers=auth(other), params={"scope": "manage"}).json() == []


def test_teacher_cannot_borrow_other_campus_asset_and_needs_terms(client, make_user, db):
    seed_camera(db, campus=TPRA)
    teacher = make_user("staff", KK)
    assert client.post("/api/loans", headers=auth(teacher), json=request_body()).status_code == 403
    seed_camera(db, campus=KK, aid="cam2")
    assert client.post("/api/loans", headers=auth(teacher), json=request_body("cam2", terms_accepted=False)).status_code == 400


def test_visibility_and_leader_is_read_only(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    seed_camera(db)
    a, b = make_user("staff", KK), make_user("staff", KK)
    loan = client.post("/api/loans", headers=auth(a), json=request_body(start_at="2026-08-05T08:00", end_at="2026-08-05T15:00")).json()
    assert client.get(f"/api/loans/{loan['id']}", headers=auth(b)).status_code == 403
    leader = make_user("leader", "")
    assert client.get(f"/api/loans/{loan['id']}", headers=auth(leader)).status_code == 200
    assert len(client.get("/api/loans", headers=auth(leader), params={"scope": "all"}).json()) == 1
    assert client.put(f"/api/loans/{loan['id']}/decide", headers=auth(leader), json={"decision": "approved"}).status_code == 403


def test_take_home_goes_to_supervisor_first(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    seed_camera(db, aid="lap1", category="IT Equipment")
    sup = make_user("staff", KK, email="boss@example.com")
    teacher = make_user("staff", KK)
    db.execute("UPDATE users SET supervisor = 'boss@example.com' WHERE id = ?", (teacher["id"],))
    db.commit()
    body = request_body("lap1", take_home=True, start_at="2026-08-05T15:00", end_at="2026-08-07T08:00")
    loan = client.post("/api/loans", headers=auth(teacher), json=body).json()
    assert loan["status"] == "pending_supervisor"
    assert client.put(f"/api/loans/{loan['id']}/supervisor", headers=auth(teacher), json={"approve": True}).status_code in (400, 409)
    ok = client.put(f"/api/loans/{loan['id']}/supervisor", headers=auth(sup), json={"approve": True})
    assert ok.status_code == 200 and ok.json()["status"] == "pending_ict"


def test_catalog_and_settings(client, make_user, db):
    seed_camera(db)
    ict = make_user("ict_admin", KK)
    teacher = make_user("staff", KK)
    cat = client.get("/api/loans/assets", headers=auth(teacher)).json()
    assert [c["id"] for c in cat] == ["cam1"] and cat[0]["state"] == "available"
    assert client.put("/api/loans/assets/cam1/settings", headers=auth(teacher),
                      json={"borrowable": False}).status_code == 403
    r = client.put("/api/loans/assets/cam1/settings", headers=auth(ict),
                   json={"borrowable": True, "accessories": ["Charger", " Tas ", ""], "max_loan_days": 2})
    assert r.status_code == 200 and r.json()["accessories"] == ["Charger", "Tas"] and r.json()["max_loan_days"] == 2
    assert client.put("/api/loans/policies", headers=auth(ict), json={"category": "AV Equipment", "campus": TPRA}).status_code == 403
    assert client.put("/api/loans/policies", headers=auth(ict), json={"category": "AV Equipment", "campus": KK, "max_loan_days": 5}).status_code == 200
