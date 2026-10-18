from datetime import datetime, timedelta

import booking_engine as be
import server
from conftest import auth

KK, TPRA = "YPJ Kuala Kencana", "YPJ TPRA"
NOW = datetime(2026, 8, 5, 8, 30)


def freeze(monkeypatch, dt=NOW):
    monkeypatch.setattr(server, "_local_now", lambda: dt)


def add_asset(db, aid="cam1", tag="YPJ-KAM-005", campus=KK, category="AV Equipment"):
    db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,purchase_price,purchase_date,created_at,updated_at) "
               "VALUES (?,?,?,?,?,'ICT',0,'2026-01-01','t','t')", (aid, f"Item {aid}", tag, category, campus))
    db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type) VALUES (?,1,'item')", (aid,))
    db.execute("INSERT OR IGNORE INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES ('f','loans/p.jpg','p.jpg','image/jpeg',1,'u',0,'t')")
    db.commit()


def make_loan(client, teacher, ict, aid="cam1", start="2026-08-06T08:00", end="2026-08-06T15:00", approve=True, today=NOW):
    body = {"asset_id": aid, "start_at": start, "end_at": end, "purpose": "Acara", "terms_accepted": True}
    loan = client.post("/api/loans", headers=auth(teacher), json=body).json()
    if approve:
        client.put(f"/api/loans/{loan['id']}/decide", headers=auth(ict), json={"decision": "approved"})
    return loan


UNIT = {"asset_id": "cam1", "physical": "baik", "function": "normal", "photo": "loans/p.jpg", "accessories": []}


def test_scan_resolves_codes_and_suggests_action(client, make_user, db, monkeypatch):
    freeze(monkeypatch)
    add_asset(db)
    ict, teacher = make_user("ict_admin", KK), make_user("staff", KK)
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "nope"}).status_code == 404
    loan = make_loan(client, teacher, ict, start="2026-08-05T09:00", end="2026-08-05T15:00")
    r = client.get("/api/loans/scan", headers=auth(ict), params={"code": "ypj-kam-005"}).json()          # case-insensitive
    assert r["asset"]["id"] == "cam1" and r["suggest"] == {"action": "check_out", "booking_id": loan["id"]}
    # the QR may hold a link
    assert client.get("/api/loans/scan", headers=auth(ict), params={"code": "https://x.y/scan?code=YPJ-KAM-005"}).json()["asset"]["id"] == "cam1"
    client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [dict(UNIT, asset_id="cam1")]})
    r = client.get("/api/loans/scan", headers=auth(ict), params={"code": "YPJ-KAM-005"}).json()
    assert r["state"] == "on_loan" and r["suggest"]["action"] == "check_in"
    # a teacher sees the state but no booking details or actions
    t = client.get("/api/loans/scan", headers=auth(teacher), params={"code": "YPJ-KAM-005"}).json()
    assert t["suggest"] is None and t["pickup"] is None and "booking_id" not in (t["out"] or {})
    assert client.get("/api/loans/scan", headers=auth(make_user("staff", TPRA)), params={"code": "YPJ-KAM-005"}).status_code == 403


def test_reminders_pickup_due_overdue_and_no_duplicates(client, make_user, db, monkeypatch):
    freeze(monkeypatch)
    add_asset(db)
    add_asset(db, "cam2", "YPJ-KAM-006")
    add_asset(db, "cam3", "YPJ-KAM-007")
    ict, teacher = make_user("ict_admin", KK), make_user("staff", KK)
    make_loan(client, teacher, ict, "cam1", "2026-08-06T08:00", "2026-08-06T15:00")                    # pick-up tomorrow
    due = make_loan(client, teacher, ict, "cam2", "2026-08-05T09:00", "2026-08-05T17:00")              # due today
    late = make_loan(client, teacher, ict, "cam3", "2026-08-05T08:30", "2026-08-05T09:00")
    for b, a in ((due, "cam2"), (late, "cam3")):
        client.post(f"/api/loans/{b['id']}/check-out", headers=auth(ict), json={"units": [dict(UNIT, asset_id=a)]})
    freeze(monkeypatch, datetime(2026, 8, 5, 9, 30))
    server.mark_overdue_loans()                                                                       # cam3 is late now
    kinds = lambda: sorted(r[0] for r in db.execute("SELECT kind FROM notification_queue WHERE kind LIKE 'loan_remind%' OR kind = 'loan_overdue'"))
    assert kinds() == ["loan_overdue"]
    server.send_loan_reminders()
    assert kinds() == ["loan_overdue", "loan_remind_due", "loan_remind_pickup"]
    server.send_loan_reminders()                                                                      # same day again: nothing new
    assert len(kinds()) == 3


def test_phone_normalization_and_whatsapp_queue(client, make_user, db):
    import pytest
    from fastapi import HTTPException
    assert server.normalize_phone("0812-3456-7890") == "6281234567890"
    assert server.normalize_phone("+62 812 3456 7890") == "6281234567890"
    assert server.normalize_phone("") == ""
    with pytest.raises(HTTPException):
        server.normalize_phone("123")
    teacher = make_user("staff", KK, email="guru@example.com")
    db.execute("UPDATE users SET phone = '6281234567890' WHERE id = ?", (teacher["id"],))
    db.commit()
    server.queue_email(db, "guru@example.com", "[YPJ Assets] Tes", "<h2>Halo</h2><table><tr><td>Aset</td><td>Kamera</td></tr></table>", "test", "ref1")
    wa = dict(db.execute("SELECT * FROM notification_queue WHERE channel = 'whatsapp'").fetchone())
    assert wa["to_addr"] == "6281234567890" and wa["status"] == "skipped"          # no gateway token configured
    assert "Aset: Kamera" in wa["body"] and wa["body"].startswith("*YPJ Assets*")


def test_user_phone_saved_via_api(client, make_user):
    admin = make_user("admin")
    r = client.post("/api/auth/register", headers=auth(admin), json={"email": "t@example.com", "password": "secret123", "name": "T", "phone": "0812 999 8888"})
    assert r.status_code == 200
    users = client.get("/api/users", headers=auth(admin)).json()
    assert [u["phone"] for u in users if u["email"] == "t@example.com"] == ["62812999888"[:0] + "628129998888"]


def test_dashboard_lists_unreturned_with_contact_and_scopes(client, make_user, db, monkeypatch):
    freeze(monkeypatch)
    add_asset(db)
    add_asset(db, "cam9", "YPJ-KAM-099", campus=TPRA)
    ict, teacher, other = make_user("ict_admin", KK), make_user("staff", KK, email="guru@example.com"), make_user("ict_admin", TPRA)
    db.execute("UPDATE users SET phone = '6281234567890' WHERE id = ?", (teacher["id"],))
    db.commit()
    loan = make_loan(client, teacher, ict, start="2026-08-05T08:30", end="2026-08-05T09:00")
    client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [dict(UNIT)]})
    pending = make_loan(client, teacher, ict, start="2026-08-10T08:00", end="2026-08-10T10:00", approve=False)
    freeze(monkeypatch, datetime(2026, 8, 5, 10, 0))
    d = client.get("/api/loans/dashboard", headers=auth(ict)).json()
    assert d["counts"]["pending"] == 1 and d["counts"]["not_returned"] == 1
    row = d["not_returned"][0]
    assert row["asset_tag"] == "YPJ-KAM-005" and row["email"] == "guru@example.com" and row["phone"] == "6281234567890"
    assert client.get("/api/loans/dashboard", headers=auth(other)).json()["counts"] == {"pending": 0, "out": 0, "not_returned": 0, "broken": 0, "today": 0}
    assert client.get("/api/loans/dashboard", headers=auth(teacher)).status_code == 403
    assert client.get("/api/loans/dashboard", headers=auth(make_user("leader", ""))).json()["counts"]["not_returned"] == 1
    assert pending["status"] == "pending_ict"


def test_reports_usage_and_incidents_and_leader_access(client, make_user, db, monkeypatch):
    freeze(monkeypatch)
    add_asset(db)
    ict, teacher, leader = make_user("ict_admin", KK), make_user("staff", KK), make_user("leader", "")
    loan = make_loan(client, teacher, ict, start="2026-08-05T09:00", end="2026-08-05T15:00")
    client.post(f"/api/loans/{loan['id']}/check-out", headers=auth(ict), json={"units": [dict(UNIT)]})
    client.post(f"/api/loans/{loan['id']}/check-in", headers=auth(ict),
                json={"units": [dict(UNIT, result="damaged", physical="retak", note="Layar retak")]})
    u = client.get("/api/loans/reports/usage", headers=auth(leader), params={"month": "2026-08"}).json()
    assert u["items"][0]["loans"] == 1 and u["items"][0]["problems"] == 1
    inc = client.get("/api/loans/reports/incidents", headers=auth(leader), params={"date_from": "2026-08-01", "date_to": "2026-08-31"}).json()
    assert len(inc) == 1 and inc[0]["asset_tag"] == "YPJ-KAM-005" and inc[0]["follow_up"] == "Dalam perbaikan" and inc[0]["chronology"] == "Layar retak"
    x = client.get("/api/loans/reports/usage", headers=auth(leader), params={"month": "2026-08", "format": "xlsx"})
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert client.get("/api/loans/reports/usage", headers=auth(teacher), params={"month": "2026-08"}).status_code == 403
    assert client.get("/api/loans/reports/usage", headers=auth(leader), params={"month": "bad"}).status_code == 400
    # the standard reports are open to leaders (read only) but not to teachers
    assert client.get("/api/reports/faults", headers=auth(leader)).status_code == 200
    assert client.get("/api/reports/faults", headers=auth(teacher)).status_code == 403


def test_usage_report_counts_cart_sessions_by_class(client, make_user, db, monkeypatch):
    be.init_booking_schema(db)
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,created_at) VALUES ('c1',?,'Cart A','laptop_cart',30,'t')", (KK,))
    for i, (a, b) in enumerate([("07:30", "08:10"), ("08:10", "08:50")], start=1):
        db.execute("INSERT INTO school_periods (id,campus,period_no,start_time,end_time) VALUES (?,?,?,?,?)", (be.new_id(), KK, i, a, b))
    db.execute("""INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,subject,teacher_name,weekday,period_from,period_to,units,valid_from,valid_to,created_at)
                  VALUES ('s1',?,'2026-2027','Ganjil','c1','7A','Info','Bu Sari',2,1,2,10,'2026-07-20','2026-12-18','t')""", (KK,))
    db.commit()
    b = be.materialize_fixed(db, schedule_id="s1", day=datetime(2026, 8, 5).date(), by_id="i", by_name="I", now=datetime(2026, 8, 5, 7, 0))
    db.execute("UPDATE bookings SET status = 'completed' WHERE id = ?", (b["id"],))
    db.commit()
    ict = make_user("ict_admin", KK)
    u = client.get("/api/loans/reports/usage", headers=auth(ict), params={"month": "2026-08"}).json()
    assert u["by_class"] == [{"campus": KK, "class_name": "7A", "resource": "Cart A", "fixed_sessions": 1, "extra_sessions": 0, "hours": 1.3}]
