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
                           ("fx7", "Lenovo 11th Gen", ""), ("fx8", "MSI 12th Gen", "Desktop"), ("fx9", "MSI Optix 24", "Monitor")):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,item_type,campus,location,serial_number,unit,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,?,?,?,'B3 TRC Room','','',0,'2026-01-01','t','t')", (aid, name, aid, "Furniture" if aid == "fx1" else "IT Equipment", typ, KK))
    db.commit()
    admin = make_user("super_admin", "")
    def ids(g):
        r = client.get("/api/assets/label-list", headers=auth(admin), params={"campus": KK, "group": g})
        assert r.status_code == 200, r.text
        return {x["id"] for x in r.json()}
    assert ids("fixed") == {"fx1", "fx3", "fx4"}
    assert ids("loan") == {"laptop0", "fx2", "fx5", "fx6", "fx7", "fx8", "fx9"}


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
