"""Unscheduled laptop / iPad loans: the teacher asks for N units of a kind, ICT picks the exact free units."""
import server
from conftest import auth

KK = "YPJ Kuala Kencana"


def seed(db, n_laptops=4, n_ipads=2):
    db.execute("INSERT OR IGNORE INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES ('f1','loans/p.jpg','p.jpg','image/jpeg',1,'u',0,'t')")
    ids = {"laptop": [], "ipad": []}
    for kind, n in (("laptop", n_laptops), ("ipad", n_ipads)):
        for i in range(n):
            aid = f"{kind}{i}"
            db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,purchase_price,purchase_date,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,'ICT',0,'2026-01-01','t','t')",
                       (aid, f"{kind} {i}", f"YPJ-{kind.upper()}-{i}", "IT Equipment", "Laptop" if kind == "laptop" else "iPad", KK))
            db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type) VALUES (?,1,'item')", (aid,))
            ids[kind].append(aid)
    db.commit()
    return ids


def ask(client, user, units=2, device="laptop", start="2026-08-05T08:00", end="2026-08-05T15:00"):
    return client.post("/api/loans", headers=auth(user), json={"device_type": device, "units": units, "start_at": start, "end_at": end,
                                                               "purpose": "Kelas", "terms_accepted": True})


def unit(aid):
    return {"asset_id": aid, "physical": "baik", "function": "normal", "photo": "loans/p.jpg", "accessories": []}


def test_ict_picks_units_and_availability_shrinks(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db)
    teacher, other, ict = make_user("staff", KK), make_user("staff", KK), make_user("ict_admin", KK)
    r = ask(client, teacher, 3)
    assert r.status_code == 200, r.text
    loan = r.json()
    assert loan["status"] == "pending_ict" and loan["kind"] == "pool" and loan["units_requested"] == 3
    # cannot ask for more than exists
    assert ask(client, other, 5).status_code == 409

    cand = client.get(f"/api/loans/{loan['id']}/candidates", headers=auth(ict)).json()
    assert {u["id"] for u in cand["units"]} == set(ids["laptop"])           # iPads are not offered for a laptop request
    assert client.get(f"/api/loans/{loan['id']}/candidates", headers=auth(teacher)).status_code == 403

    # must pick exactly the approved number, from free units
    pick = ids["laptop"][:3]
    assert client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": pick[:2]}).status_code == 400
    assert client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": [ids["ipad"][0], *pick[:2]]}).status_code == 400
    d = client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": pick})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    assert sorted(u["asset_id"] for u in d.json()["units"]) == sorted(pick) and all(u["status"] == "reserved" for u in d.json()["units"])

    # the reserved laptops are gone for that window, only one is left
    av = client.get("/api/loans/pool/availability", headers=auth(other),
                    params={"device_type": "laptop", "start_at": "2026-08-05T09:00", "end_at": "2026-08-05T10:00"}).json()
    assert av["free"] == 1
    assert ask(client, other, 2, start="2026-08-05T09:00", end="2026-08-05T10:00").status_code == 409
    assert ask(client, other, 1, start="2026-08-05T09:00", end="2026-08-05T10:00").status_code == 200
    # another day is unaffected
    assert client.get("/api/loans/pool/availability", headers=auth(other),
                      params={"device_type": "laptop", "start_at": "2026-08-06T09:00", "end_at": "2026-08-06T10:00"}).json()["free"] == 4


def test_checkout_checkin_and_release(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db)
    teacher, ict = make_user("staff", KK), make_user("ict_admin", KK)
    loan = ask(client, teacher, 3).json()
    pick = ids["laptop"][:3]
    client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": pick})

    view = client.get(f"/api/loans/{loan['id']}", headers=auth(ict)).json()
    assert sorted(u["id"] for u in view["cart_units"]) == sorted(pick)

    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 8, 30))
    # hand over two of the three: the third reservation is released; a free spare may replace nothing here
    out = client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [unit(pick[0]), unit(pick[1])]})
    assert out.status_code == 200 and out.json()["status"] == "in_use"
    states = {u["asset_id"]: u["status"] for u in out.json()["units"]}
    assert states == {pick[0]: "out", pick[1]: "out"}
    back = client.post(f"/api/loans/{loan['id']}/check-in", headers=auth(ict),
                       json={"units": [{**unit(pick[0]), "result": "ok"}, {**unit(pick[1]), "result": "ok"}]})
    assert back.status_code == 200 and back.json()["status"] == "completed"


def test_rejects_cancel_policy_and_rules(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db, n_laptops=14)
    teacher, ict = make_user("staff", KK), make_user("ict_admin", KK)
    assert ask(client, teacher, 11).status_code == 400                         # default cap: 10 per request
    r = client.put("/api/loans/policies", headers=auth(ict), json={"campus": KK, "category": "IT Equipment", "max_loan_days": 1,
                                                                   "requires_approval": True, "can_leave_campus": False,
                                                                   "min_notice_days": 1, "max_advance_days": 14, "max_units": 12})
    assert r.status_code == 200 and r.json()["max_units"] == 12
    assert ask(client, teacher, 11).status_code == 200
    # take-home is never allowed for laptops / iPads
    bad = client.post("/api/loans", headers=auth(teacher), json={"device_type": "laptop", "units": 1, "take_home": True, "start_at": "2026-08-05T08:00",
                                                                 "end_at": "2026-08-05T09:00", "terms_accepted": True})
    assert bad.status_code == 400
    # unknown kind / mixing with a specific asset
    assert ask(client, teacher, 1, device="phone").status_code == 400
    assert client.post("/api/loans", headers=auth(teacher), json={"device_type": "laptop", "asset_id": ids["laptop"][0], "start_at": "2026-08-05T08:00",
                                                                  "end_at": "2026-08-05T09:00", "terms_accepted": True}).status_code == 400
    # reserving then cancelling frees the units again
    loan = ask(client, teacher, 2, start="2026-08-07T08:00", end="2026-08-07T09:00").json()
    client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": ids["laptop"][:2]})
    q = {"device_type": "laptop", "start_at": "2026-08-07T08:00", "end_at": "2026-08-07T09:00"}
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q).json()["free"] == 12
    client.put(f"/api/loans/{loan['id']}/cancel", headers=auth(teacher), json={"reason": "batal"})
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q).json()["free"] == 14


def test_unit_in_cart_respects_cart_capacity(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db, n_laptops=3, n_ipads=0)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,created_at) VALUES ('c1',?,'Laptop Cart A','laptop_cart',3,'IT Equipment','t')", (KK,))
    db.execute("UPDATE asset_loan_settings SET resource_id = 'c1'")
    db.commit()
    teacher, other, ict = make_user("staff", KK), make_user("staff", KK), make_user("ict_admin", KK)
    loan = ask(client, teacher, 2).json()
    client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": ids["laptop"][:2]})
    # a normal cart booking now sees only one slot left in the cart
    r = client.post("/api/loans", headers=auth(other), json={"resource_id": "c1", "units": 2, "start_at": "2026-08-05T09:00",
                                                             "end_at": "2026-08-05T10:00", "terms_accepted": True})
    assert r.status_code == 409
    assert client.post("/api/loans", headers=auth(other), json={"resource_id": "c1", "units": 1, "start_at": "2026-08-05T09:00",
                                                                "end_at": "2026-08-05T10:00", "terms_accepted": True}).status_code == 200
