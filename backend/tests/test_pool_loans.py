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


def test_availability_counts_only_what_the_cart_can_still_give(client, make_user, db, monkeypatch):
    """A cart of 5 laptops whose fixed schedule holds 4 of them: only 1 may be lent, not all 5."""
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    seed(db, n_laptops=5, n_ipads=0)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,created_at) VALUES ('c1',?,'Laptop Cart A','laptop_cart',5,'IT Equipment','t')", (KK,))
    db.execute("UPDATE asset_loan_settings SET resource_id = 'c1'")
    db.execute("INSERT INTO school_periods (id,campus,period_no,start_time,end_time,unit) VALUES ('p1',?,1,'08:00','09:00','')", (KK,))
    db.execute("INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,weekday,period_from,period_to,units,valid_from,valid_to,created_at) "
               "VALUES ('s1',?,'2026/2027','1','c1','7A',2,1,1,4,'2026-07-01','2026-12-31','t')", (KK,))   # 2026-08-05 is a Wednesday
    db.commit()
    teacher = make_user("staff", KK)
    q = {"device_type": "laptop", "start_at": "2026-08-05T08:00", "end_at": "2026-08-05T09:00"}
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q).json()["free"] == 1
    assert ask(client, teacher, 2, start=q["start_at"], end=q["end_at"]).status_code == 409
    assert ask(client, teacher, 1, start=q["start_at"], end=q["end_at"]).status_code == 200
    q2 = {**q, "start_at": "2026-08-05T10:00", "end_at": "2026-08-05T11:00"}       # outside the scheduled period
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q2).json()["free"] == 5


def test_scan_reports_unit_held_by_cart_schedule(client, make_user, db, monkeypatch):
    """A unit of a cart whose fixed schedule holds every unit right now is not 'available'."""
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 8, 30))
    seed(db, n_laptops=0, n_ipads=2)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,created_at) VALUES ('c1',?,'iPad Cart','ipad_cart',2,'IT Equipment','t')", (KK,))
    db.execute("UPDATE asset_loan_settings SET resource_id = 'c1'")
    db.execute("INSERT INTO school_periods (id,campus,period_no,start_time,end_time,unit) VALUES ('p1',?,1,'08:00','09:00','')", (KK,))
    db.execute("INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,weekday,period_from,period_to,units,valid_from,valid_to,created_at) "
               "VALUES ('s1',?,'2026/2027','1','c1','7A',2,1,1,2,'2026-07-01','2026-12-31','t')", (KK,))
    db.commit()
    ict = make_user("ict_admin", KK)
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "YPJ-IPAD-0"}).json()["state"] == "scheduled"
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 10, 0))
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "YPJ-IPAD-0"}).json()["state"] == "available"


def test_unit_out_now_but_back_before_window_is_free(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db, n_laptops=0, n_ipads=2)
    teacher, ict = make_user("staff", KK), make_user("ict_admin", KK)
    loan = ask(client, teacher, 2, device="ipad", start="2026-08-05T08:00", end="2026-08-05T11:00").json()
    client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved", "unit_ids": ids["ipad"]})
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 8, 30))
    assert client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [unit(i) for i in ids["ipad"]]}).status_code == 200
    q = {"device_type": "ipad", "start_at": "2026-08-05T09:00", "end_at": "2026-08-05T10:00"}
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q).json()["free"] == 0
    q = {**q, "start_at": "2026-08-05T11:00", "end_at": "2026-08-05T12:00"}
    assert client.get("/api/loans/pool/availability", headers=auth(teacher), params=q).json()["free"] == 2


def test_scan_cart_unit_scheduled_even_if_cart_not_full(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 8, 30))
    seed(db, n_laptops=0, n_ipads=3)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,created_at) VALUES ('c1',?,'Cart G','ipad_cart',3,'IT Equipment','t')", (KK,))
    db.execute("UPDATE asset_loan_settings SET resource_id = 'c1'")
    db.execute("INSERT INTO school_periods (id,campus,period_no,start_time,end_time,unit) VALUES ('p1',?,1,'08:00','09:00','')", (KK,))
    db.execute("INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,weekday,period_from,period_to,units,valid_from,valid_to,created_at) "
               "VALUES ('s1',?,'2026/2027','1','c1','7A',2,1,1,2,'2026-07-01','2026-12-31','t')", (KK,))
    db.commit()
    r = client.get("/api/loans/scan", headers=auth(make_user("ict_admin", KK)), params={"code": "YPJ-IPAD-0"}).json()
    assert r["state"] == "scheduled" and r["cart"]["used"] == 2 and r["cart"]["capacity"] == 3
    assert r["suggest"]["action"] == "open_session" and r["session"]["class_name"] == "7A"
    sid, day = r["suggest"]["schedule_id"], r["suggest"]["date"]
    ict = make_user("ict_admin", KK)
    b = client.post(f"/api/loans/schedules/{sid}/session", headers=auth(ict), json={"date": day})
    assert b.status_code == 200, b.text
    r = client.get("/api/loans/scan", headers=auth(ict), params={"code": "YPJ-IPAD-0"}).json()
    assert r["suggest"] == {"action": "check_out", "booking_id": b.json()["id"]}
    assert client.get("/api/loans/scan", headers=auth(make_user("staff", KK)), params={"code": "YPJ-IPAD-0"}).json()["suggest"] is None


def test_single_unit_loan_respects_cart_schedule_and_counts_in_cart(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ids = seed(db, n_laptops=0, n_ipads=3)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,created_at) VALUES ('c1',?,'Cart G','ipad_cart',3,'IT Equipment','t')", (KK,))
    db.execute("UPDATE asset_loan_settings SET resource_id = 'c1'")
    db.execute("INSERT INTO school_periods (id,campus,period_no,start_time,end_time,unit) VALUES ('p1',?,1,'08:00','09:00','')", (KK,))
    db.execute("INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,weekday,period_from,period_to,units,valid_from,valid_to,created_at) "
               "VALUES ('s1',?,'2026/2027','1','c1','7A',2,1,1,2,'2026-07-01','2026-12-31','t')", (KK,))
    db.commit()
    a, b = make_user("staff", KK), make_user("staff", KK)
    body = lambda aid: {"asset_id": aid, "start_at": "2026-08-05T08:00", "end_at": "2026-08-05T09:00", "terms_accepted": True, "purpose": "x"}
    first = client.post("/api/loans", headers=auth(a), json=body(ids["ipad"][0]))                         # the one spare unit
    assert first.status_code == 200
    if first.json()["status"] != "approved":
        assert client.put(f"/api/loans/{first.json()['id']}/decide", headers=auth(make_user("ict_admin", KK)),
                          json={"decision": "approved"}).status_code == 200
    assert client.post("/api/loans", headers=auth(b), json=body(ids["ipad"][1])).status_code == 409     # cart now full


def test_scan_finds_asset_by_encoded_link_serial_or_loose_spelling(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 10, 0))
    seed(db, n_laptops=0, n_ipads=0)
    db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,purchase_price,purchase_date,created_at,updated_at) "
               "VALUES ('x1',?,?,?,?,?,'ICT','HX1G26C5F6',0,'2026-01-01','t','t')", ("YPJ's iPad24", "YPJ's iPad24", "IT Equipment", "iPad", KK))
    db.commit()
    ict = make_user("ict_admin", KK)
    for code in ("YPJ's iPad24", "https://x.example/scan?code=YPJ%27s%20iPad24", "ypj's-ipad24", "HX1G26C5F6", "hx1g26c5f6"):
        r = client.get("/api/loans/scan", headers=auth(ict), params={"code": code})
        assert r.status_code == 200 and r.json()["asset"]["id"] == "x1", code
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "NOPE-1"}).status_code == 404


def test_scan_finds_asset_by_numeric_name(client, make_user, db, monkeypatch):
    """Labels carry the numeric asset number (the asset's name); scanning it resolves the asset, unless it is ambiguous."""
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 10, 0))
    seed(db, n_laptops=0, n_ipads=0)
    for i, (aid, name) in enumerate((("n1", "9661732"), ("n2", "5550001"), ("n3", "5550001"))):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'ICT','',0,'2026-01-01','t','t')", (aid, name, f"Student's Desktop #{i}", "IT Equipment", "Desktop", KK))
    db.commit()
    ict = make_user("ict_admin", KK)
    r = client.get("/api/loans/scan", headers=auth(ict), params={"code": "9661732"})
    assert r.status_code == 200 and r.json()["asset"]["id"] == "n1"
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "5550001"}).status_code == 404


def test_barcode_ids_are_generated_locked_and_backfilled(client, make_user, db):
    seed(db, n_laptops=0, n_ipads=0)
    admin = make_user("super_admin", "")
    body = {"name": "Meja A", "asset_tag": "MANUAL-1", "category": "Furniture", "location": "R1", "purchase_price": 1, "purchase_date": "2026-01-01", "campus": KK}
    a = client.post("/api/assets", headers=auth(admin), json=body).json()
    b = client.post("/api/assets", headers=auth(admin), json={**body, "name": "Meja B"}).json()
    assert a["asset_tag"].isdigit() and len(a["asset_tag"]) == 7 and b["asset_tag"].isdigit() and a["asset_tag"] != b["asset_tag"]
    client.put(f"/api/assets/{a['id']}", headers=auth(admin), json={"asset_tag": "HACK", "location": "R2"})
    got = client.get(f"/api/assets/{a['id']}", headers=auth(admin)).json()
    assert got["asset_tag"] == a["asset_tag"] and got["location"] == "R2"
    # backfill: text tags become numbers (numeric names are reused), numeric tags stay, duplicates are renumbered
    for aid, name, tag in (("o1", "9661732", "Student's Desktop #15"), ("o2", "Kursi", "KURSI-1"), ("o3", "Kursi 2", a["asset_tag"])):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','',0,'2026-01-01','t','t')", (aid, name, tag, "Furniture", "Chair", KK))
    db.commit()
    assert server.ensure_barcode_ids(db) == 3        # o1, o2 and one of the two assets sharing a tag
    tags = {r["id"]: r["asset_tag"] for r in db.execute("SELECT id, asset_tag FROM assets")}
    assert tags["o1"] == "9661732" and tags["o2"].isdigit() and tags["o3"].isdigit()
    assert len(set(tags.values())) == len(tags)
    assert server.ensure_barcode_ids(db) == 0


def test_restore_asset_names_from_old_records(client, db):
    seed(db, n_laptops=0, n_ipads=0)
    for aid, name in (("r1", "9669707"), ("r2", "8880001")):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','',0,'2026-01-01','t','t')", (aid, name, name, "IT Equipment", "Desktop", KK))
    db.execute("INSERT INTO loan_requests (id,asset_id,asset_name,asset_tag,requested_by,requested_by_name,purpose,start_date,end_date,status,created_at) "
               "VALUES ('l1','r1','9669707',?,'u','U','p','2026-01-01','2026-01-02','returned','t')", ("Student's Desktop #15",))
    db.commit()
    assert server.restore_asset_names(db) == 1
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM assets WHERE id IN ('r1','r2')")}
    assert names == {"r1": "Student's Desktop #15", "r2": "8880001"}
    assert server.restore_asset_names(db) == 0


def test_bulk_unit_by_selection_and_by_name_rules(client, make_user, db):
    seed(db, n_laptops=0, n_ipads=0)
    rows = (("b1", "Student's Desktop #22", "Desktop"), ("b2", "Student's Laptop #3", "Laptop"), ("b3", "PAUD iPad 1", "iPad"),
            ("b4", "SDBos's iPad 10", "iPad"), ("b5", "YPJ-FI's iPad43", "iPad"), ("b6", "Printer", "Printer"))
    for aid, name, typ in rows:
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','','',0,'2026-01-01','t','t')", (aid, name, aid, "IT Equipment", typ, KK))
    db.commit()
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/bulk-unit", headers=auth(admin), json={}).json()
    assert r["updated"] == 4 and r["skipped"] == 2
    units = {x["id"]: x["unit"] for x in db.execute("SELECT id, unit FROM assets")}
    assert units["b1"] == "smp" and units["b2"] == "sd" and units["b3"] == "paud" and units["b4"] == "sd" and units["b5"] == "" and units["b6"] == ""
    r = client.post("/api/assets/bulk-unit", headers=auth(admin), json={"unit": "sd", "asset_ids": ["b5", "b6"]}).json()
    assert r["updated"] == 2
    assert client.post("/api/assets/bulk-unit", headers=auth(admin), json={"unit": "xx", "asset_ids": ["b5"]}).status_code == 400


def test_bulk_unit_follows_cart_or_lab_unit(client, make_user, db):
    seed(db, n_laptops=0, n_ipads=0)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,location,active,created_at,unit) VALUES ('cx',?,'Laptop Cart SD','laptop_cart',2,'IT Equipment','',1,'t','SD')", (KK,))
    for aid, name, cur in (("c1", "9661732", ""), ("c2", "Student's Desktop #1", "smp"), ("c3", "Student's Desktop #2", "")):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','',?,0,'2026-01-01','t','t')", (aid, name, aid, "IT Equipment", "Laptop", KK, cur))
    for aid in ("c1", "c2"):
        db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type, resource_id) VALUES (?,1,'scheduled','cx')", (aid,))
    db.commit()
    admin = make_user("super_admin", "")
    assert client.post("/api/assets/bulk-unit", headers=auth(admin), json={}).json()["updated"] == 3
    units = {x["id"]: x["unit"] for x in db.execute("SELECT id, unit FROM assets WHERE id LIKE 'c%'")}
    assert units == {"c1": "sd", "c2": "sd", "c3": "smp"}


def test_restore_names_from_asset_export_file(client, make_user, db):
    import io, openpyxl
    seed(db, n_laptops=0, n_ipads=0)
    for aid, name, tag, ser, loc in (("e1", "9661732", "9661732", "SER1", "Lab Komputer SMP"), ("e2", "1002880_GRS", "5550123", "SER2", "Lab Komputer SMP"),
                                     ("e3", "7770001", "7770001", "SER3", "Lab Komputer SMP")):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,?,?,'',0,'2026-01-01','t','t')", (aid, name, tag, "IT Equipment", "Monitor", KK, loc, ser))
    db.commit()
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Asset Name", "Tag", "Serial Number"])
    ws.append(["9661732", "Student's Desktop #15", "SER1"]); ws.append(["1002880_GRS", "Student's Monitor #9", "SER2"]); ws.append(["ghost", "Nope", "ZZZ"])
    buf = io.BytesIO(); wb.save(buf)
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/restore-names", headers=auth(admin), files={"file": ("x.xlsx", buf.getvalue())}).json()
    assert r == {"restored": 2, "unmatched": 1, "skipped": 0}
    got = {x["id"]: (x["name"], x["asset_code"], x["asset_tag"]) for x in db.execute("SELECT id, name, asset_code, asset_tag FROM assets")}
    assert got["e1"] == ("Student's Desktop #15", "", "9661732") and got["e2"] == ("Student's Monitor #9", "1002880_GRS", "5550123") and got["e3"][0] == "7770001"
    # lab room decides the unit even when the name says nothing
    assert client.post("/api/assets/bulk-unit", headers=auth(admin), json={}).json()["by_unit"] == {"smp": 3}


def test_restore_names_keeps_descriptive_names_and_repairs_swap(client, make_user, db):
    import io, openpyxl
    seed(db, n_laptops=0, n_ipads=0)
    for aid, name, code, ser in (("d1", "Lenovo 11th Gen", "", "S1"), ("d2", "SDYPJKK-LENOVO2", "Lenovo 11th Gen", "S2"), ("d3", "MSI Modern", "", ""), ("d4", "MSI Modern", "", "")):
        db.execute("INSERT INTO assets (id,name,asset_tag,asset_code,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,?,'R',?,'',0,'2026-01-01','t','t')", (aid, name, "55500" + aid[1], code, "IT Equipment", "Laptop", KK, ser))
    db.commit()
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Asset Name", "Tag", "Serial Number"])
    ws.append(["Lenovo 11th Gen", "SDYPJKK-LENOVO1", "S1"]); ws.append(["Lenovo 11th Gen", "SDYPJKK-LENOVO2", "S2"])
    ws.append(["MSI Modern", "SMP-1", ""]); ws.append(["MSI Modern", "SMP-2", ""])
    buf = io.BytesIO(); wb.save(buf)
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/restore-names", headers=auth(admin), files={"file": ("x.xlsx", buf.getvalue())}).json()
    assert r["restored"] == 2 and r["unmatched"] == 2
    got = {x["id"]: (x["name"], x["asset_code"]) for x in db.execute("SELECT id, name, asset_code FROM assets")}
    assert got["d1"] == ("Lenovo 11th Gen", "SDYPJKK-LENOVO1") and got["d2"] == ("Lenovo 11th Gen", "SDYPJKK-LENOVO2")


def test_counter_loan_turns_scanned_units_into_one_loan(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 10, 0))
    ids = seed(db)
    teacher, ict, other = make_user("staff", KK), make_user("ict_admin", KK), make_user("staff", KK)
    pick = ids["laptop"][:3]
    body = {"asset_ids": pick, "borrower_id": teacher["id"], "end_at": "2026-08-05T14:00", "purpose": "Ujian", "class_name": "7A"}
    assert client.post("/api/loans/counter", headers=auth(teacher), json=body).status_code == 403          # only ICT
    r = client.post("/api/loans/counter", headers=auth(ict), json=body)
    assert r.status_code == 200, r.text
    assert r.json()["units"] == 3 and r.json()["status"] == "approved"
    view = client.get(f"/api/loans/{r.json()['id']}", headers=auth(ict)).json()
    assert view["requester_name"] == "staff user" and sorted(u["asset_id"] for u in view["units"]) == sorted(pick)
    # the three laptops are taken; the same ones cannot be scanned into a second loan
    again = client.post("/api/loans/counter", headers=auth(ict), json={**body, "asset_ids": pick[:1], "borrower_id": other["id"]})
    assert again.status_code == 409
    # mixed kinds are refused
    mixed = client.post("/api/loans/counter", headers=auth(ict), json={**body, "asset_ids": [ids["laptop"][3], ids["ipad"][0]]})
    assert mixed.status_code == 400
    # the normal hand-over works on it
    out = client.post(f"/api/loans/{r.json()['id']}/check-out", headers=auth(ict), json={"units": [unit(a) for a in pick]})
    assert out.status_code == 200 and out.json()["status"] == "in_use"


def test_counter_loan_handed_over_in_one_step_with_group_photo(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 5, 10, 0))
    ids = seed(db)
    teacher, ict = make_user("staff", KK), make_user("ict_admin", KK)
    pick = ids["laptop"][:5 - 1]
    r = client.post("/api/loans/counter", headers=auth(ict), json={"asset_ids": pick, "borrower_id": teacher["id"], "end_at": "2026-08-05T14:00"}).json()
    out = client.post(f"/api/loans/{r['id']}/check-out", headers=auth(ict), json={"all_units": True, "group_photo": "loans/p.jpg", "units": []})
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "in_use" and sorted(u["asset_id"] for u in out.json()["units"] if u["status"] == "out") == sorted(pick)


def test_import_template_excel_download(client, make_user):
    import io, openpyxl
    admin = make_user("super_admin", "")
    r = client.get("/api/assets/import-template", headers=auth(admin), params={"format": "xlsx"})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Aset", "Petunjuk"] and wb["Aset"]["A1"].value == "name" and wb["Aset"]["B1"].value == "asset_tag"
    assert client.get("/api/assets/import-template", headers=auth(admin)).headers["content-type"].startswith("text/csv")


def test_export_and_import_template_share_columns_and_order(client, make_user, db):
    import io, openpyxl
    seed(db, n_laptops=1, n_ipads=0)
    admin = make_user("super_admin", "")
    exp = openpyxl.load_workbook(io.BytesIO(client.get("/api/assets/export", headers=auth(admin)).content)).active
    tpl = openpyxl.load_workbook(io.BytesIO(client.get("/api/assets/import-template", headers=auth(admin), params={"format": "xlsx"}).content))["Aset"]
    h_exp = [c.value for c in exp[1]]
    h_tpl = [c.value for c in tpl[1]]
    assert h_exp[:len(h_tpl)] == h_tpl and h_exp[-1] == "created_at"
    csv_head = client.get("/api/assets/import-template", headers=auth(admin)).text.splitlines()[0].split(",")
    assert csv_head == h_tpl
    # an exported file can be fed back to the import (dry run): the row is read with its real column names
    buf = io.BytesIO(); wb = openpyxl.Workbook(); ws = wb.active; ws.append(h_tpl)
    row = {k: "" for k in h_tpl}; row.update(name="Meja", category="Furniture", location="R1", status="active", campus=KK)
    ws.append([row[k] for k in h_tpl]); wb.save(buf)
    r = client.post("/api/assets/import?dry_run=true", headers=auth(admin), files={"file": ("a.xlsx", buf.getvalue())}).json()
    assert r["valid"] == 1 and r["invalid"] == 0, r


def test_share_photo_to_numbered_copies(client, make_user, db):
    seed(db, n_laptops=0, n_ipads=0)
    rows = (("p1", "Seiko wall clock #1", "photos/a.jpg"), ("p2", "Seiko wall clock #2", ""), ("p3", "Seiko wall clock #30", "photos/old.jpg"),
            ("p4", "Seiko wall clock", ""), ("p5", "Casio wall clock #1", ""))
    for aid, name, ph in rows:
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,photo_path,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','','',?,0,'2026-01-01','t','t')", (aid, name, aid, "Furniture", "", KK, ph))
    db.commit()
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/p1/share-photo", headers=auth(admin), json={"dry_run": True}).json()
    assert r["count"] == 3 and not r["applied"]
    assert db.execute("SELECT photo_path FROM assets WHERE id='p2'").fetchone()[0] == ""
    assert client.post("/api/assets/p1/share-photo", headers=auth(admin), json={"only_empty": True}).json()["count"] == 2
    assert db.execute("SELECT photo_path FROM assets WHERE id='p3'").fetchone()[0] == "photos/old.jpg"
    assert client.post("/api/assets/p1/share-photo", headers=auth(admin), json={}).json()["count"] == 1
    got = {x[0]: x[1] for x in db.execute("SELECT id, photo_path FROM assets")}
    assert got["p3"] == "photos/a.jpg" and got["p4"] == "photos/a.jpg" and got["p5"] == ""
    assert client.post("/api/assets/p5/share-photo", headers=auth(admin), json={}).status_code == 400


def test_label_list_splits_lent_from_fixed(client, make_user, db):
    seed(db, n_laptops=1, n_ipads=0)
    for aid, name, typ in (("fx1", "Seiko wall clock #1", ""), ("fx2", "Lenovo 11th Gen", "Laptop"), ("fx3", "Student's Desktop #1", "Desktop"),
                           ("fx4", "Samsung 24", "Monitor"), ("fx5", "Canon", "Camera"), ("fx6", "SDBos's iPad 10", "iPad"),
                           ("fx7", "Lenovo 11th Gen", ""), ("fx8", "MSI 12th Gen", "Desktop"), ("fx9", "MSI Optix 24", "Monitor"),
                           ("fxa", "DELL MONITOR P2311H", "Monitor"), ("fxb", "Dell Precision 5820 Tower", ""),
                           ("fxc", "Dell Latitude 5440", "Laptop"), ("fxd", "Dell Latitude 5450", "Laptop")):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'B3 TRC Room','','',0,'2026-01-01','t','t')", (aid, name, aid, "Furniture" if aid == "fx1" else "IT Equipment", typ, KK))
    for aid in ("fxa", "fxb"):    # explicitly set to "not lendable"
        db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type) VALUES (?,0,'item')", (aid,))
    db.execute("UPDATE assets SET assigned_to_name = 'Bu Sari — B3 — YPJ Kuala Kencana' WHERE id IN ('fxc','fxd')")
    db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type) VALUES ('fxd',1,'item')")    # assigned but explicitly lendable
    db.commit()
    admin = make_user("super_admin", "")
    def ids(g):
        r = client.get("/api/assets/label-list", headers=auth(admin), params={"campus": KK, "group": g})
        assert r.status_code == 200, r.text
        return {x["id"] for x in r.json()}
    assert ids("fixed") == {"fx1", "fx3", "fx4", "fxa", "fxb", "fxc"}
    assert ids("loan") == {"laptop0", "fx2", "fx5", "fx6", "fx7", "fx8", "fx9", "fxd"}


def test_bulk_loanable_keeps_other_settings(client, make_user, db):
    seed(db, n_laptops=1, n_ipads=0)
    for aid in ("m1", "m2"):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'R','','',0,'2026-01-01','t','t')", (aid, aid, aid, "IT Equipment", "Laptop", KK))
    db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type, storage_slot) VALUES ('m2',0,'scheduled','A1')")
    db.commit()
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/bulk-loanable", headers=auth(admin), json={"asset_ids": ["m1", "m2", "zz"], "borrowable": True}).json()
    assert r["updated"] == 2 and r["skipped"] == 1
    rows = {x["asset_id"]: x for x in db.execute("SELECT * FROM asset_loan_settings WHERE asset_id IN ('m1','m2')")}
    assert rows["m1"]["borrowable"] == 1 and rows["m2"]["borrowable"] == 1 and rows["m2"]["loan_type"] == "scheduled" and rows["m2"]["storage_slot"] == "A1"
    client.post("/api/assets/bulk-loanable", headers=auth(admin), json={"asset_ids": ["m1"], "borrowable": False})
    assert db.execute("SELECT borrowable FROM asset_loan_settings WHERE asset_id='m1'").fetchone()[0] == 0
    assert client.post("/api/assets/bulk-loanable", headers=auth(admin), json={"asset_ids": [], "borrowable": True}).status_code == 400


def _approval_setup(db, make_user, monkeypatch):
    sent = []
    monkeypatch.setattr(server, "send_email", lambda to, subject, html, cc=None: sent.append({"to": to, "subject": subject, "cc": list(cc or [])}) or True)
    boss = make_user("staff", "YPJ Kuala Kencana", email="kepsek@example.com")
    teacher = make_user("staff", "YPJ Kuala Kencana", email="guru@example.com")
    db.execute("UPDATE users SET supervisor = 'kepsek@example.com' WHERE id = ?", (teacher["id"],))
    for nm, em in (("Maria Jacadewa", "maria@example.com"), ("Petrick Richard", "petrick@example.com"), ("Jeni Mansawan", "jeni@example.com")):
        db.execute("INSERT INTO users (id,email,name,role,campus,password_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                   (server.uuid.uuid4().hex, em, nm, "staff", "YPJ Kuala Kencana", "x", "t"))
    db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at,requires_assign_approval) "
               "VALUES ('mu1','Keyboard Yamaha','5550001','Music Equipment','Keyboard',?,'Ruang Musik','','smp',0,'2026-01-01','t','t',1)", (KK,))
    db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
               "VALUES ('mu2','Gitar','5550002','Music Equipment','Guitar',?,'Ruang Musik','','smp',0,'2026-01-01','t','t')", (KK,))
    db.commit()
    return sent, boss, teacher


def test_assign_with_approval_goes_supervisor_then_teacher(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    r = client.post("/api/assignments/bulk", headers=auth(admin), json={"to_user_id": teacher["id"], "asset_ids": ["mu1", "mu2"], "kind": "class"}).json()
    assert r["created"] == 2 and r["awaiting_approval"] == 1 and r["cc_missing"] == ["Abidin Nur Rahmat", "Damianus Muyapa", "Tomas Sutejo"]
    rows = {x["asset_id"]: x for x in db.execute("SELECT * FROM assignments")}
    assert rows["mu1"]["status"] == "awaiting_approval" and rows["mu2"]["status"] == "pending"
    to_boss = [m for m in sent if m["to"] == "kepsek@example.com"]
    assert len(to_boss) == 1 and {"maria@example.com", "petrick@example.com", "jeni@example.com"} <= set(to_boss[0]["cc"])
    assert [m for m in sent if m["to"] == "guru@example.com" and "Konfirmasi" in m["subject"] and "mu1" in str(m)] == []
    # the teacher cannot accept before approval; only the supervisor can approve
    assert client.post("/api/assignments/respond", headers=auth(teacher), json={"ids": [rows["mu1"]["id"]], "action": "accept"}).json()["errors"][0]["error"] == "not_pending"
    assert client.get("/api/assignments/pending-count", headers=auth(boss)).json()["mine"] == 1
    assert client.get("/api/assignments/approvals", headers=auth(teacher)).json() == []
    assert client.post("/api/assignments/approve", headers=auth(teacher), json={"ids": [rows["mu1"]["id"]], "action": "approve"}).json()["errors"][0]["error"] == "not_approver"
    assert len(client.get("/api/assignments/approvals", headers=auth(boss)).json()) == 1
    sent.clear()
    assert client.post("/api/assignments/approve", headers=auth(boss), json={"ids": [rows["mu1"]["id"]], "action": "approve"}).json()["approved"] == 1
    to_teacher = [m for m in sent if m["to"] == "guru@example.com"]
    assert len(to_teacher) == 1 and "maria@example.com" in to_teacher[0]["cc"] and "kepsek@example.com" in to_teacher[0]["cc"]
    assert client.post("/api/assignments/respond", headers=auth(teacher), json={"ids": [rows["mu1"]["id"]], "action": "accept"}).json()["done"] == 1
    assert db.execute("SELECT assigned_to_user_id FROM assets WHERE id='mu1'").fetchone()[0] == teacher["id"]


def test_assign_approval_reject_and_missing_supervisor(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    client.post("/api/assignments/bulk", headers=auth(admin), json={"to_user_id": teacher["id"], "asset_ids": ["mu1"], "kind": "class"})
    rid = db.execute("SELECT id FROM assignments").fetchone()[0]
    assert client.post("/api/assignments/approve", headers=auth(boss), json={"ids": [rid], "action": "reject", "reason": ""}).status_code == 400
    assert client.post("/api/assignments/approve", headers=auth(boss), json={"ids": [rid], "action": "reject", "reason": "Belum perlu"}).json()["rejected"] == 1
    assert db.execute("SELECT status FROM assignments WHERE id=?", (rid,)).fetchone()[0] == "rejected"
    assert db.execute("SELECT assigned_to_user_id FROM assets WHERE id='mu1'").fetchone()[0] in (None, "")
    # a teacher without a supervisor cannot receive an approval-controlled asset
    lone = make_user("staff", "YPJ Kuala Kencana", email="lone@example.com")
    r = client.post("/api/assignments/bulk", headers=auth(admin), json={"to_user_id": lone["id"], "asset_ids": ["mu1"], "kind": "class"}).json()
    assert r["created"] == 0 and r["skipped"][0]["reason"] == "no_supervisor"
    assert client.post("/api/assets/mu1/transfer", headers=auth(admin), json={"new_owner_user_id": lone["id"], "new_owner_name": "x"}).status_code == 409


def test_bulk_assign_approval_toggle_and_asset_field(client, make_user, db, monkeypatch):
    _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    r = client.post("/api/assets/bulk-assign-approval", headers=auth(admin), json={"asset_ids": ["mu2", "zz"], "enabled": True}).json()
    assert r["updated"] == 1 and r["skipped"] == 1
    assert db.execute("SELECT requires_assign_approval FROM assets WHERE id='mu2'").fetchone()[0] == 1
    assert client.put("/api/assets/mu2", headers=auth(admin), json={"requires_assign_approval": False}).json()["requires_assign_approval"] == 0


def test_approval_level_two_copies_admins_but_not_leaders(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    campus_admin = make_user("campus_admin", KK, email="kampus@example.com")
    r = client.post("/api/assets/bulk-assign-approval", headers=auth(admin), json={"asset_ids": ["mu1"], "level": 2}).json()
    assert r["updated"] == 1 and r["level"] == 2
    assert db.execute("SELECT requires_assign_approval FROM assets WHERE id='mu1'").fetchone()[0] == 2
    r = client.post("/api/assignments/bulk", headers=auth(admin), json={"to_user_id": teacher["id"], "asset_ids": ["mu1"], "kind": "class"}).json()
    assert r["awaiting_approval"] == 1 and r["cc_missing"] == ["Damianus Muyapa", "Tomas Sutejo"]
    cc = [m for m in sent if m["to"] == "kepsek@example.com"][0]["cc"]
    assert {"maria@example.com", "jeni@example.com", "kampus@example.com"} <= set(cc)
    assert "petrick@example.com" not in cc
    assert admin["email"] in cc      # super admins are always copied
    # the asset form can pick the level directly
    assert client.put("/api/assets/mu2", headers=auth(admin), json={"requires_assign_approval": 2}).json()["requires_assign_approval"] == 2


def test_invite_discards_old_password(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "email_configured", lambda: True)
    monkeypatch.setattr(server, "send_email", lambda *a, **k: True)
    admin = make_user("super_admin", "")
    u = make_user("staff", KK, email="baru@example.com")
    before = db.execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    r = client.post(f"/api/users/{u['id']}/invite", headers=auth(admin)).json()
    assert r["sent"] and "/set-password?token=" in r["link"]
    assert db.execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()[0] != before
    tok = r["link"].split("token=")[1]
    assert client.post("/api/auth/set-password", json={"token": tok, "password": "KataSandiBaru1!"}).status_code == 200


def test_cc_name_match_ignores_middle_names(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    db.execute("UPDATE users SET name = 'Maria Gabriella Jacadewa' WHERE name = 'Maria Jacadewa'")
    db.commit()
    emails, missing = server.assign_cc(db, KK, 2)
    assert "maria@example.com" in emails and "Maria Jacadewa" not in missing


def test_cc_follows_roles_not_only_names(client, make_user, db, monkeypatch):
    _approval_setup(db, make_user, monkeypatch)
    adm = make_user("admin", "", email="resources@example.com")
    lead = make_user("leader", KK, email="lead@example.com")
    other_lead = make_user("leader", "YPJ Tembagapura", email="otherlead@example.com")
    full, _ = server.assign_cc(db, KK, 1)
    admins_only, _ = server.assign_cc(db, KK, 2)
    assert {"resources@example.com", "lead@example.com"} <= set(full) and "otherlead@example.com" not in full
    assert "resources@example.com" in admins_only and "lead@example.com" not in admins_only


def test_unit_scope_limits_cc_and_assigning(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    tomas = make_user("admin", KK, email="tsutejo@example.com")
    maria2 = make_user("admin", KK, email="maria2@example.com")
    db.execute("UPDATE users SET name='Tomas Tresno Sutejo', unit_scope='paud' WHERE id=?", (tomas["id"],))
    db.execute("UPDATE users SET unit_scope='sd,smp' WHERE id=?", (maria2["id"],))
    db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at,requires_assign_approval) "
               "VALUES ('pa1','Balok','5550003','Learning Tools','Blocks',?,'Kelas PAUD','','paud',0,'2026-01-01','t','t',1)", (KK,))
    db.execute("UPDATE assets SET category='Furniture' WHERE id IN ('mu1','mu2')")   # Admins handle non-ICT assets
    db.commit()
    # copied only on the units they look after
    assert "tsutejo@example.com" not in server.assign_cc(db, KK, 2, {"smp"})[0]
    assert "tsutejo@example.com" in server.assign_cc(db, KK, 2, {"paud"})[0]
    assert "maria2@example.com" in server.assign_cc(db, KK, 2, {"sd"})[0] and "maria2@example.com" not in server.assign_cc(db, KK, 2, {"paud"})[0]
    # and they can only assign those units
    bt = client.post("/api/assignments/bulk", headers=auth(tomas), json={"to_user_id": teacher["id"], "asset_ids": ["mu1", "pa1"], "kind": "class"}).json()
    assert bt["created"] == 1 and bt["skipped"][0]["reason"] == "unit_scope" and bt["skipped"][0]["asset_id"] == "mu1"
    assert client.post("/api/assets/mu1/transfer", headers=auth(tomas), json={"new_owner_user_id": teacher["id"], "new_owner_name": "x"}).status_code == 409
    # a campus admin is not tied to a unit
    jeni = make_user("campus_admin", KK, email="jeni2@example.com")
    assert client.post("/api/assets/mu2/transfer", headers=auth(jeni), json={"new_owner_user_id": teacher["id"], "new_owner_name": "x"}).status_code == 200


def test_leaders_sign_policy_and_answer_handovers(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    lead = make_user("leader", KK, email="abidin2@example.com")
    assert client.get("/api/auth/me", headers=auth(lead)).json()["policy_required"] is True
    r = client.post("/api/policy/accept", headers=auth(lead), json={"version": server.POLICY_VERSION, "signed_name": db.execute("SELECT name FROM users WHERE id=?", (lead["id"],)).fetchone()[0],
                                                                      "text_hash": "x", "lang": "ID", "read_all": True, "will_comply": True, "accept_sanctions": True})
    assert r.status_code == 200
    admin = make_user("super_admin", "")
    assert client.post("/api/assignments/bulk", headers=auth(admin), json={"to_user_id": lead["id"], "asset_ids": ["mu2"], "kind": "personal"}).json()["created"] == 1
    rid = db.execute("SELECT id FROM assignments WHERE to_user_id=?", (lead["id"],)).fetchone()[0]
    assert client.post("/api/assignments/respond", headers=auth(lead), json={"ids": [rid], "action": "accept"}).json()["done"] == 1
    assert client.post("/api/assets", headers=auth(lead), json={"name": "x"}).status_code == 403   # still view-only elsewhere


def test_transfer_and_new_asset_can_be_class_assets(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    assert client.post("/api/assets/mu2/transfer", headers=auth(admin), json={"new_owner_user_id": teacher["id"], "new_owner_name": "x", "kind": "class"}).status_code == 200
    assert db.execute("SELECT kind FROM assignments WHERE asset_id='mu2'").fetchone()[0] == "class"
    body = {"name": "Cajon", "category": "Music Equipment", "campus": KK, "location": "Room H1", "purchase_price": 1, "purchase_date": "2026-01-01",
            "assigned_to_user_id": teacher["id"], "assigned_to_name": "Guru", "assignment_kind": "class"}
    r = client.post("/api/assets", headers=auth(admin), json=body)
    assert r.status_code == 200 and r.json()["pending_assignment"]["kind"] == "class"


def test_assignment_email_shows_asset_photo(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    photo = server.UPLOADS_DIR / "t" / "p.jpg"
    photo.parent.mkdir(exist_ok=True)
    photo.write_bytes(b"\xff\xd8\xff\xe0fake")
    db.execute("UPDATE assets SET photo_path='t/p.jpg' WHERE id='mu1'")
    db.commit()
    html = server._assignment_items_html([{"asset_id": "mu1", "asset_name": "Keyboard", "asset_tag": "5550001", "kind": "class", "location": "Ruang Musik"}])
    assert "/api/email-photo/mu1?s=" in html and "5550001" in html
    path = server.email_photo_url("mu1").replace(server.APP_URL, "")
    assert client.get(path).status_code == 200
    assert client.get("/api/email-photo/mu1?s=wrong").status_code == 404
    no_photo = server._assignment_items_html([{"asset_id": "mu2", "asset_name": "Gitar", "asset_tag": "5550002", "kind": "personal", "location": ""}])
    assert "email-photo" not in no_photo and "No photo" in no_photo
    photo.unlink()


def _room_asset_body(location, **kw):
    return {"name": "Meja", "category": "Furniture", "campus": KK, "location": location, "purchase_price": 1, "purchase_date": "2026-01-01", **kw}


def test_room_master_list_guards_against_near_duplicates(client, make_user, db):
    admin = make_user("super_admin", "")
    h = auth(admin)
    assert client.post("/api/assets", headers=h, json=_room_asset_body("Lab Komputer SMP")).status_code == 200
    # same name up to case / spaces -> the master's spelling
    r = client.post("/api/assets", headers=h, json=_room_asset_body("  lab  komputer smp "))
    assert r.status_code == 200 and r.json()["location"] == "Lab Komputer SMP"
    # a name that reads like an existing room is refused until confirmed
    r = client.post("/api/assets", headers=h, json=_room_asset_body("Lab Komputer-SMP"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "similar_room" and "Lab Komputer SMP" in r.json()["detail"]["suggestions"]
    assert client.post("/api/assets", headers=h, json=_room_asset_body("Lab Komputer-SMP", allow_new_room=True)).status_code == 200
    assert client.post("/api/assets", headers=h, json=_room_asset_body("Gudang Utama")).status_code == 200
    names = [x["name"] for x in client.get("/api/rooms", headers=h, params={"campus": KK}).json()]
    assert "Gudang Utama" in names and "Lab Komputer SMP" in names
    # editing an asset without touching its room never trips the guard; moving it to a look-alike does
    aid = client.post("/api/assets", headers=h, json=_room_asset_body("Gudang Utama")).json()["id"]
    assert client.put(f"/api/assets/{aid}", headers=h, json={"name": "Meja 2", "location": "Gudang Utama"}).status_code == 200
    assert client.put(f"/api/assets/{aid}", headers=h, json={"location": "Gudang  utama 2"}).status_code == 409


def test_merge_and_delete_rooms(client, make_user, db):
    admin = make_user("super_admin", "")
    h = auth(admin)
    for loc in ("B3 TRC Room", "B3 TRC"):
        client.post("/api/assets", headers=h, json=_room_asset_body(loc, allow_new_room=True))
    rooms = {r["name"]: r for r in client.get("/api/classrooms", headers=h).json()}
    assert client.delete(f"/api/classrooms/{rooms['B3 TRC']['id']}", headers=h).status_code == 409      # still has an asset
    r = client.post(f"/api/classrooms/{rooms['B3 TRC']['id']}/merge", headers=h, json={"target_id": rooms["B3 TRC Room"]["id"]})
    assert r.status_code == 200 and r.json()["moved_assets"] == 1
    assert db.execute("SELECT COUNT(*) FROM assets WHERE location='B3 TRC Room'").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM classrooms WHERE name='B3 TRC'").fetchone()[0] == 0
    assert client.post(f"/api/classrooms/{rooms['B3 TRC Room']['id']}/merge", headers=h, json={"target_id": rooms["B3 TRC Room"]["id"]}).status_code == 400
    empty = client.post("/api/classrooms", headers=h, json={"name": "Ruang Kosong", "campus": KK}).json()
    assert client.delete(f"/api/classrooms/{empty['id']}", headers=h).status_code == 200


def test_new_room_with_similar_name_needs_confirmation(client, make_user, db):
    admin = make_user("super_admin", "")
    h = auth(admin)
    assert client.post("/api/classrooms", headers=h, json={"name": "Lab Bahasa", "campus": KK}).status_code == 200
    r = client.post("/api/classrooms", headers=h, json={"name": "Lab-Bahasa 2", "campus": KK})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "similar_room"
    assert client.post("/api/classrooms", headers=h, json={"name": "Lab-Bahasa 2", "campus": KK, "allow_similar": True}).status_code == 200


def test_photos_are_inlined_into_the_mail(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    photo = server.UPLOADS_DIR / "t" / "q.jpg"
    photo.parent.mkdir(exist_ok=True)
    photo.write_bytes(b"\xff\xd8\xff\xe0smallfake")
    db.execute("UPDATE assets SET photo_path='t/q.jpg' WHERE id='mu1'")
    db.commit()
    html = server._assignment_items_html([{"asset_id": "mu1", "asset_name": "Keyboard", "asset_tag": "5550001", "kind": "class", "location": "R"}])
    new_html, inline = server._inline_photos("<p>" + html + "</p>")
    assert len(inline) == 1 and f"cid:{inline[0]['cid']}" in new_html and "email-photo" not in new_html and inline[0]["data"].startswith(b"\xff\xd8")
    # a photo that is too big stays a normal link
    photo.write_bytes(b"x" * (server.INLINE_PHOTO_MAX_BYTES + 1))
    big_html, big_inline = server._inline_photos(html)
    assert big_inline == [] and "email-photo" in big_html
    photo.unlink()


def test_create_many_numbered_copies_with_one_mail(client, make_user, db, monkeypatch):
    sent, boss, teacher = _approval_setup(db, make_user, monkeypatch)
    admin = make_user("super_admin", "")
    h = auth(admin)
    body = _room_asset_body("Room H1", assigned_to_user_id=teacher["id"], assigned_to_name="Guru", assignment_kind="class", quantity=10, name="Bel Kuis",
                            category="Learning Tools", requires_assign_approval=2)
    r = client.post("/api/assets", headers=h, json=body)
    assert r.status_code == 200 and r.json()["created_count"] == 10 and r.json()["created_names"][0] == "Bel Kuis #1" and r.json()["created_names"][-1] == "Bel Kuis #10"
    rows = db.execute("SELECT name, asset_tag FROM assets WHERE name LIKE 'Bel Kuis #%'").fetchall()
    assert len(rows) == 10 and len({x["asset_tag"] for x in rows}) == 10
    assert db.execute("SELECT COUNT(*) FROM assignments WHERE status='awaiting_approval' AND kind='class'").fetchone()[0] == 10   # approval applies to the first hand-over too
    to_boss = [m for m in sent if m["to"] == "kepsek@example.com"]
    assert len(to_boss) == 1                                                                                                       # one mail for all ten
    # adding more later continues the numbering
    r = client.post("/api/assets", headers=h, json=_room_asset_body("Room H1", name="Bel Kuis", quantity=3, category="Learning Tools"))
    assert r.json()["created_names"] == ["Bel Kuis #11", "Bel Kuis #12", "Bel Kuis #13"]
    # approval needed but the recipient has no supervisor -> nothing is created
    lone = make_user("staff", KK, email="lone2@example.com")
    before = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    r = client.post("/api/assets", headers=h, json=_room_asset_body("Room H1", name="Bel Lain", quantity=2, assigned_to_user_id=lone["id"], assigned_to_name="x", requires_assign_approval=1, category="Learning Tools"))
    assert r.status_code == 409 and db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == before


def test_blank_asset_id_is_generated_in_sequence(client, make_user):
    headers = auth(make_user("super_admin", ""))
    mk = lambda **k: client.post("/api/assets", headers=headers, json=_room_asset_body("", **k))
    a, b = mk(), mk(name="Meja 2")
    c = mk(name="Meja 3", asset_code="MY-OWN-1")
    assert a.status_code == 200 and b.status_code == 200 and c.status_code == 200
    assert a.json()["asset_code"].startswith("YPJ-KK-FUR-")
    assert int(b.json()["asset_code"][-4:]) == int(a.json()["asset_code"][-4:]) + 1
    assert c.json()["asset_code"] == "MY-OWN-1"                                          # a super admin may type one
    assert mk(name="Meja 4", asset_code="my-own-1").status_code == 409                   # but not a duplicate
    put = client.put(f"/api/assets/{a.json()['id']}", headers=headers, json={"asset_code": "CHANGED-1"})
    assert put.status_code == 200 and put.json()["asset_code"] == "CHANGED-1"
    assert client.put(f"/api/assets/{b.json()['id']}", headers=headers, json={"asset_code": "CHANGED-1"}).status_code == 409
    adm = auth(make_user("admin", ""))                                                   # other admins cannot
    r = client.post("/api/assets", headers=adm, json=_room_asset_body("", name="Meja 5", asset_code="NOPE-1"))
    assert r.status_code == 200 and r.json()["asset_code"].startswith("YPJ-KK-FUR-")
    put = client.put(f"/api/assets/{b.json()['id']}", headers=adm, json={"asset_code": "HACK", "description": "x"})
    assert put.status_code == 200 and put.json()["asset_code"] == b.json()["asset_code"]


def test_backfill_fills_only_blank_asset_ids(client, make_user, db):
    headers = auth(make_user("super_admin", ""))
    keep = client.post("/api/assets", headers=headers, json=_room_asset_body("", name="A")).json()["id"]
    db.execute("UPDATE assets SET asset_code = 'KEEP-1' WHERE id = ?", (keep,))
    db.commit()
    blank = client.post("/api/assets", headers=headers, json=_room_asset_body("", name="B")).json()["id"]
    db.execute("UPDATE assets SET asset_code = '' WHERE id = ?", (blank,))
    db.commit()
    assert server.ensure_asset_codes(db) == 1
    code = lambda i: db.execute("SELECT asset_code FROM assets WHERE id = ?", (i,)).fetchone()[0]
    assert code(keep) == "KEEP-1" and code(blank).startswith("YPJ-KK-FUR-")
    assert server.ensure_asset_codes(db) == 0
