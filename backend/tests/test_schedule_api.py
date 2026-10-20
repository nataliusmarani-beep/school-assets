from datetime import timedelta

import booking_engine as be
import server
from conftest import auth

KK, TPRA = "YPJ Kuala Kencana", "YPJ TPRA"
PERIODS = [{"period_no": i, "start_time": a, "end_time": b} for i, (a, b) in
           enumerate([("07:30", "08:10"), ("08:10", "08:50"), ("08:50", "09:30"), ("09:30", "10:10")], start=1)]


def setup_cart(client, ict, n_units=3, db=None):
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "periods": PERIODS}).status_code == 200
    r = client.post("/api/loans/resources", headers=auth(ict), json={"campus": KK, "name": "Laptop Cart A", "kind": "laptop_cart", "capacity": 30})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    ids = []
    for i in range(1, n_units + 1):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,purchase_price,purchase_date,created_at,updated_at) "
                   "VALUES (?,?,?,'IT Equipment',?,'Cart A',0,'2026-01-01','t','t')", (f"lap{i}", f"Laptop {i}", f"YPJ-LAP-{i:03d}", KK))
        ids.append(f"lap{i}")
    db.execute("INSERT OR IGNORE INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES ('f','loans/cart.jpg','c.jpg','image/jpeg',1,'u',0,'t')")
    db.commit()
    assert client.put(f"/api/loans/resources/{rid}/units", headers=auth(ict), json={"asset_ids": ids}).status_code == 200
    return rid


def schedule_body(rid, **kw):
    b = dict(resource_id=rid, academic_year="2026-2027", semester="Ganjil", class_name="7A", subject="Informatika", teacher_name="Bu Sari",
             weekday=0, period_from=3, period_to=4, units=2, valid_from="2026-07-20", valid_to="2026-12-18")
    b.update(kw)
    return b


def test_setup_permissions(client, make_user, db):
    ict, other, teacher = make_user("ict_admin", KK), make_user("ict_admin", TPRA), make_user("staff", KK)
    assert client.put("/api/loans/periods", headers=auth(teacher), json={"campus": KK, "periods": PERIODS}).status_code == 403
    assert client.put("/api/loans/periods", headers=auth(other), json={"campus": KK, "periods": PERIODS}).status_code == 403
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "periods": PERIODS}).status_code == 200
    bad = [{"period_no": 1, "start_time": "07:30", "end_time": "08:10"}, {"period_no": 2, "start_time": "08:00", "end_time": "08:50"}]
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "periods": bad}).status_code == 400
    assert client.post("/api/loans/resources", headers=auth(other), json={"campus": KK, "name": "X", "kind": "laptop_cart"}).status_code == 403
    rid = setup_cart(client, ict, 2, db)
    assert client.post("/api/loans/schedules", headers=auth(teacher), json=schedule_body(rid)).status_code == 403
    assert len(client.get("/api/loans/resources", headers=auth(teacher)).json()) == 1
    assert client.get("/api/loans/resources", headers=auth(other)).json() == []        # other campus sees nothing of KK


def test_schedule_crud_and_conflicts(client, make_user, db):
    ict = make_user("ict_admin", KK)
    rid = setup_cart(client, ict, 3, db)
    ok = client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, units=2))
    assert ok.status_code == 200, ok.text
    clash = client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, class_name="7B", units=2, period_from=4, period_to=4))
    assert clash.status_code == 409 and "Bentrok" in clash.json()["detail"]
    assert client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, class_name="7B", units=1, period_from=4, period_to=4)).status_code == 200
    too_many = client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, units=9, weekday=2))
    assert too_many.status_code == 409
    assert client.post("/api/loans/periods", headers=auth(ict)).status_code in (404, 405)
    # periods used by a fixed schedule cannot be deleted
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "periods": PERIODS[:2]}).status_code == 409


def test_calendar_shows_used_free_and_libur_opens_slot(client, make_user, db):
    ict, teacher = make_user("ict_admin", KK), make_user("staff", KK)
    rid = setup_cart(client, ict, 3, db)
    sid = client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, units=3)).json()["id"]
    cal = client.get("/api/loans/calendar", headers=auth(teacher), params={"resource_id": rid, "week_start": "2026-08-10"}).json()
    mon = cal["days"][0]
    p3 = [c for c in mon["cells"] if c["period_no"] == 3][0]
    assert p3["used"] == 3 and p3["free"] == 0 and p3["items"][0]["type"] == "fixed"
    assert [c for c in mon["cells"] if c["period_no"] == 1][0]["free"] == 3
    # a teacher cannot mark libur; ICT can, and the slot becomes free
    assert client.post(f"/api/loans/schedules/{sid}/exceptions", headers=auth(teacher), json={"date": "2026-08-10"}).status_code == 403
    assert client.post(f"/api/loans/schedules/{sid}/exceptions", headers=auth(ict), json={"date": "2026-08-10", "note": "Ujian"}).status_code == 200
    assert client.post(f"/api/loans/schedules/{sid}/exceptions", headers=auth(ict), json={"date": "2026-08-11"}).status_code == 400   # not a class day
    cal = client.get("/api/loans/calendar", headers=auth(teacher), params={"resource_id": rid, "week_start": "2026-08-10"}).json()
    p3 = [c for c in cal["days"][0]["cells"] if c["period_no"] == 3][0]
    assert p3["free"] == 3 and p3["items"][0]["type"] == "libur"


def test_off_schedule_request_for_cart_by_periods(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ict, teacher = make_user("ict_admin", KK), make_user("staff", KK)
    rid = setup_cart(client, ict, 3, db)
    client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, units=2))
    body = {"resource_id": rid, "units": 2, "date": "2026-08-10", "period_from": 3, "period_to": 4, "purpose": "Remedial", "class_name": "8B", "terms_accepted": True}
    full = client.post("/api/loans", headers=auth(teacher), json=body)            # only 1 free while 7A has 2 of 3
    assert full.status_code == 409 and "Tersisa 1" in full.json()["detail"]
    ok = client.post("/api/loans", headers=auth(teacher), json={**body, "units": 1})
    assert ok.status_code == 200, ok.text
    loan = ok.json()
    assert loan["kind"] == "off_schedule" and loan["start_at"] == "2026-08-10T08:50" and loan["end_at"] == "2026-08-10T10:10"
    assert loan["asset"]["name"] == "Laptop Cart A"
    assert client.post("/api/loans", headers=auth(teacher), json={**body, "take_home": True}).status_code == 400
    assert client.post("/api/loans", headers=auth(teacher), json={"asset_id": "x", "resource_id": rid, "purpose": "x", "terms_accepted": True}).status_code == 400
    # another campus' teacher cannot book this cart
    assert client.post("/api/loans", headers=auth(make_user("staff", TPRA)), json=body).status_code == 403


def test_fixed_session_handover_with_all_units_and_missing_unit(client, make_user, db, monkeypatch):
    ict = make_user("ict_admin", KK)
    rid = setup_cart(client, ict, 3, db)
    sid = client.post("/api/loans/schedules", headers=auth(ict), json=schedule_body(rid, units=3)).json()["id"]
    pairs = {"academic_year": "2026-2027", "semester": "Ganjil", "items": [
        {"asset_id": "lap1", "class_name": "7A", "student_name": "Ani", "student_no": "1"},
        {"asset_id": "lap2", "class_name": "7A", "student_name": "Budi", "student_no": "2"}]}
    assert client.put(f"/api/loans/resources/{rid}/pairings", headers=auth(ict), json=pairs).status_code == 200
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 10, 8, 40))
    opened = client.post(f"/api/loans/schedules/{sid}/session", headers=auth(ict), json={"date": "2026-08-10"})
    assert opened.status_code == 200, opened.text
    bid = opened.json()["id"]
    assert client.post(f"/api/loans/schedules/{sid}/session", headers=auth(ict), json={"date": "2026-08-10"}).json()["id"] == bid
    assert client.post(f"/api/loans/schedules/{sid}/session", headers=auth(ict), json={"date": "2026-08-11"}).status_code == 400
    out = client.post(f"/api/loans/{bid}/check-out", headers=auth(ict), json={"all_units": True, "group_photo": "loans/cart.jpg"})
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "in_use" and len(out.json()["units"]) == 3
    assert {u["student_name"] for u in out.json()["units"]} >= {"Ani", "Budi"}
    # end of class: lap3 is not back yet
    back = client.post(f"/api/loans/{bid}/check-in", headers=auth(ict), json={"all_units": True, "exclude": ["lap3"], "group_photo": "loans/cart.jpg"})
    assert back.status_code == 200, back.text
    assert back.json()["still_out"] == 1 and back.json()["status"] == "in_use"
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 10, 11, 0))
    listed = client.get("/api/loans", headers=auth(ict), params={"scope": "manage"}).json()
    assert listed[0]["status"] == "overdue" and listed[0]["asset_name"] == "Laptop Cart A"
    assert client.get("/api/loans/pending-count", headers=auth(ict)).json()["manage"] == 1
    last = client.post(f"/api/loans/{bid}/check-in", headers=auth(ict), json={"all_units": True, "group_photo": "loans/cart.jpg"})
    assert last.status_code == 200 and last.json()["status"] == "completed"


def test_holidays_block_requests(client, make_user, db, monkeypatch):
    monkeypatch.setattr(server, "_local_now", lambda: server.datetime(2026, 8, 3, 9, 0))
    ict, teacher = make_user("ict_admin", KK), make_user("staff", KK)
    rid = setup_cart(client, ict, 2, db)
    assert client.post("/api/loans/holidays", headers=auth(teacher), json={"campus": KK, "date": "2026-08-12"}).status_code == 403
    assert client.post("/api/loans/holidays", headers=auth(ict), json={"campus": "", "date": "2026-08-12"}).status_code == 403      # all-campus: admins only
    h = client.post("/api/loans/holidays", headers=auth(ict), json={"campus": KK, "date": "2026-08-12", "name": "Libur"})
    assert h.status_code == 200
    body = {"resource_id": rid, "units": 1, "date": "2026-08-12", "period_from": 1, "purpose": "x", "terms_accepted": True}
    assert client.post("/api/loans", headers=auth(teacher), json=body).status_code == 400
    assert client.delete(f"/api/loans/holidays/{h.json()['id']}", headers=auth(ict)).status_code == 200
    assert client.post("/api/loans", headers=auth(teacher), json=body).status_code == 200


def test_pairings_must_belong_to_cart(client, make_user, db):
    ict = make_user("ict_admin", KK)
    rid = setup_cart(client, ict, 2, db)
    bad = {"academic_year": "2026-2027", "semester": "Ganjil", "items": [{"asset_id": "nope", "student_name": "X", "student_no": "1"}]}
    assert client.put(f"/api/loans/resources/{rid}/pairings", headers=auth(ict), json=bad).status_code == 400
    assert client.put(f"/api/loans/resources/{rid}/units", headers=auth(ict), json={"asset_ids": ["nope"]}).status_code == 400


def test_periods_are_separate_per_school_unit(client, make_user):
    ict = make_user("ict_admin", KK)
    paud = [{"period_no": 1, "start_time": "08:00", "end_time": "08:30"}]
    smp = [{"period_no": 1, "start_time": "07:00", "end_time": "07:45"}, {"period_no": 2, "start_time": "07:45", "end_time": "08:30"}]
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "unit": "PAUD", "periods": paud}).status_code == 200
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "unit": "SMP", "periods": smp}).status_code == 200
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "unit": "TK", "periods": paud}).status_code == 422
    rows = client.get("/api/loans/periods", headers=auth(ict), params={"campus": KK}).json()
    assert {(r["unit"], r["period_no"]) for r in rows} == {("PAUD", 1), ("SMP", 1), ("SMP", 2)}
    # replacing one unit leaves the others alone
    assert client.put("/api/loans/periods", headers=auth(ict), json={"campus": KK, "unit": "PAUD", "periods": []}).status_code == 200
    rows = client.get("/api/loans/periods", headers=auth(ict), params={"campus": KK}).json()
    assert {r["unit"] for r in rows} == {"SMP"}


def test_holiday_date_range(client, make_user):
    ict = make_user("ict_admin", KK)
    r = client.post("/api/loans/holidays", headers=auth(ict), json={"campus": KK, "date": "2026-12-21", "end_date": "2026-12-25", "name": "Natal"})
    assert r.status_code == 200 and r.json()["created"] == 5
    days = [h["date"] for h in client.get("/api/loans/holidays", headers=auth(ict), params={"campus": KK}).json()]
    assert days == ["2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24", "2026-12-25"]
    assert client.post("/api/loans/holidays", headers=auth(ict), json={"campus": KK, "date": "2026-12-21", "end_date": "2026-12-25"}).status_code == 409
    assert client.post("/api/loans/holidays", headers=auth(ict), json={"campus": KK, "date": "2026-12-25", "end_date": "2026-12-20"}).status_code == 400


def test_existing_cart_gets_unit_from_name_and_error_names_unit(db):
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,category,location,active,created_at) VALUES ('r_old',?,?,?,30,'IT Equipment','',1,'t')",
               (KK, "Lab Komputer SD", "computer_lab"))
    db.commit()
    be.init_booking_schema(db)
    assert be.resource_unit(db, "r_old") == "SD"
    try:
        be.period_times(db, KK, 1, 3, "SD")
    except be.BookingError as e:
        assert "unit SD" in e.message and "Jam pelajaran" in e.message
    else:
        raise AssertionError("expected BookingError")
