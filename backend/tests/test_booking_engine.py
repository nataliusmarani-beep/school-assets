from datetime import datetime

import pytest

import booking_engine as be

KK = "YPJ Kuala Kencana"
NOW = datetime(2026, 8, 3, 9, 0)          # a Monday


def add_asset(db, aid, category="AV Equipment", status="active", campus=KK, borrowable=1):
    db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,status,purchase_price,purchase_date,created_at,updated_at) "
               "VALUES (?,?,?,?,?,?,?,0,'2026-01-01','t','t')", (aid, f"Item {aid}", f"T-{aid}", category, campus, "Lab", status))
    db.execute("INSERT INTO asset_loan_settings (asset_id, borrowable, loan_type) VALUES (?,?, 'item')", (aid, borrowable))
    db.commit()


def add_resource(db, rid="cart1", capacity=30):
    db.execute("INSERT INTO resources (id,campus,name,kind,capacity,created_at) VALUES (?,?,?,?,?,'t')", (rid, KK, "Laptop Cart A", "laptop_cart", capacity))
    for no, (a, b) in enumerate([("07:30", "08:10"), ("08:10", "08:50"), ("08:50", "09:30"), ("09:30", "10:10")], start=1):
        db.execute("INSERT OR IGNORE INTO school_periods (id,campus,period_no,start_time,end_time) VALUES (?,?,?,?,?)", (be.new_id(), KK, no, a, b))
    db.commit()


def add_fixed(db, rid="cart1", weekday=0, p_from=3, p_to=4, units=30):
    sid = be.new_id()
    db.execute("""INSERT INTO fixed_schedules (id,campus,academic_year,semester,resource_id,class_name,subject,teacher_name,weekday,
                  period_from,period_to,units,valid_from,valid_to,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'t')""",
               (sid, KK, "2026-2027", "Ganjil", rid, "7A", "Informatika", "Bu Sari", weekday, p_from, p_to, units, "2026-07-20", "2026-12-18"))
    db.commit()
    return sid


def req(**kw):
    base = dict(campus=KK, kind="item", category="AV Equipment", requester_id="u1", requester_name="Guru A",
                start_at="2026-08-05T08:00", end_at="2026-08-06T15:00", units=1, purpose="Dokumentasi", terms_accepted=True)
    base.update(kw)
    return base


def test_item_loan_is_pending_and_numbered(db):
    add_asset(db, "cam1")
    b = be.reserve(db, data=req(asset_id="cam1"), now=NOW)
    assert b["status"] == "pending_ict" and b["number"] == "PJM-2026-0001"
    b2 = be.reserve(db, data=req(asset_id="cam1", requester_id="u2", start_at="2026-08-10T08:00", end_at="2026-08-10T15:00"), now=NOW)
    assert b2["number"] == "PJM-2026-0002"


def test_terms_required(db):
    add_asset(db, "cam1")
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(asset_id="cam1", terms_accepted=False), now=NOW)
    assert e.value.code == "terms"


def test_no_approval_category_is_auto_approved(db):
    add_asset(db, "cam1")
    db.execute("UPDATE asset_loan_settings SET requires_approval = 0 WHERE asset_id = 'cam1'")
    b = be.reserve(db, data=req(asset_id="cam1"), now=NOW)
    assert b["status"] == "approved" and b["units_approved"] == 1


def test_double_booking_blocked_after_approval(db):
    add_asset(db, "cam1")
    first = be.reserve(db, data=req(asset_id="cam1"), now=NOW)
    be.decide(db, booking_id=first["id"], decision="approved", by_id="ict", by_name="ICT", now=NOW)
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(asset_id="cam1", requester_id="u2", start_at="2026-08-05T10:00", end_at="2026-08-05T12:00"), now=NOW)
    assert e.value.code == "conflict"
    # adjacent (back-to-back) is fine
    be.reserve(db, data=req(asset_id="cam1", requester_id="u2", start_at="2026-08-06T15:00", end_at="2026-08-06T16:00"), now=NOW)


def test_approval_rechecks_conflicts(db):
    add_asset(db, "cam1")
    a = be.reserve(db, data=req(asset_id="cam1"), now=NOW)
    b = be.reserve(db, data=req(asset_id="cam1", requester_id="u2"), now=NOW)       # both pending: allowed
    be.decide(db, booking_id=a["id"], decision="approved", by_id="ict", by_name="ICT", now=NOW)
    with pytest.raises(be.BookingError) as e:
        be.decide(db, booking_id=b["id"], decision="approved", by_id="ict", by_name="ICT", now=NOW)
    assert e.value.code == "conflict"


def test_partial_approval_reduces_units_and_moves_time(db):
    add_resource(db, capacity=30)
    r = be.reserve(db, data=req(kind="off_schedule", category="IT Equipment", resource_id="cart1", units=30,
                                start_at="2026-08-05T08:10", end_at="2026-08-05T09:30"), now=NOW)
    with pytest.raises(be.BookingError):          # needs a reason
        be.decide(db, booking_id=r["id"], decision="partially_approved", by_id="i", by_name="I", now=NOW, units=20)
    d = be.decide(db, booking_id=r["id"], decision="partially_approved", by_id="i", by_name="I", now=NOW, units=20,
                  start_at="2026-08-05T08:50", note="Hanya 20 unit tersedia")
    assert d["units_approved"] == 20 and d["start_at"] == "2026-08-05T08:50"
    with pytest.raises(be.BookingError):          # cannot approve more than requested
        be.decide(db, booking_id=r["id"], decision="approved", by_id="i", by_name="I", now=NOW, units=40)


def test_fixed_schedule_blocks_resource_and_holiday_frees_it(db):
    add_resource(db, capacity=30)
    sid = add_fixed(db)                            # Monday periods 3-4 = 08:50-10:10, all 30 units
    mon = dict(start=datetime(2026, 8, 10, 9, 0), end=datetime(2026, 8, 10, 10, 0))
    assert be.check_availability(db, resource_id="cart1", units=1, **mon)["free"] == 0
    tue = dict(start=datetime(2026, 8, 11, 9, 0), end=datetime(2026, 8, 11, 10, 0))
    assert be.check_availability(db, resource_id="cart1", units=30, **tue)["ok"]
    db.execute("INSERT INTO schedule_exceptions (id,schedule_id,date,kind) VALUES (?,?,?,'cancelled')", (be.new_id(), sid, "2026-08-10"))
    db.commit()
    assert be.check_availability(db, resource_id="cart1", units=30, **mon)["ok"]


def test_off_schedule_cannot_displace_fixed_class(db):
    add_resource(db, capacity=30)
    add_fixed(db, units=20)                        # 10 units remain on Mondays 08:50-10:10
    ok = be.reserve(db, data=req(kind="off_schedule", category="IT Equipment", resource_id="cart1", units=10,
                                 start_at="2026-08-10T09:00", end_at="2026-08-10T10:00"), now=NOW)
    assert ok["status"] == "pending_ict"
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(kind="off_schedule", category="IT Equipment", resource_id="cart1", units=11,
                                start_at="2026-08-10T09:00", end_at="2026-08-10T10:00"), now=NOW)
    assert e.value.code == "conflict"


def test_notice_window_and_override(db):
    add_asset(db, "cam1")
    far = req(asset_id="cam1", start_at="2026-08-25T08:00", end_at="2026-08-25T15:00")   # 22 days ahead
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=far, now=NOW)
    assert e.value.code == "advance"
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=far, now=NOW, override=True)                                 # reason required
    assert e.value.code == "override_reason"
    b = be.reserve(db, data=far, now=NOW, override=True, override_reason="Acara sekolah")
    assert b["override_reason"] == "Acara sekolah"


def test_same_day_request_is_late_and_needs_ict(db):
    add_asset(db, "cam1")
    db.execute("UPDATE asset_loan_settings SET requires_approval = 0 WHERE asset_id = 'cam1'")
    b = be.reserve(db, data=req(asset_id="cam1", start_at="2026-08-03T13:00", end_at="2026-08-03T15:00"), now=NOW)
    assert b["is_late_request"] == 1 and b["status"] == "pending_ict"


def test_max_loan_days_and_holiday(db):
    add_asset(db, "cam1")
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(asset_id="cam1", start_at="2026-08-05T08:00", end_at="2026-08-12T08:00"), now=NOW)
    assert e.value.code == "max_days"
    db.execute("INSERT INTO holidays (id,campus,date,name) VALUES (?,'', '2026-08-05','Libur')", (be.new_id(),))
    db.commit()
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(asset_id="cam1", start_at="2026-08-05T08:00", end_at="2026-08-05T10:00"), now=NOW)
    assert e.value.code == "holiday"


def test_laptops_stay_on_campus_unless_supervisor_approves(db):
    add_asset(db, "lap1", category="IT Equipment")
    base = req(asset_id="lap1", category="IT Equipment", take_home=True, start_at="2026-08-05T15:00", end_at="2026-08-07T08:00")
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=base, now=NOW)
    assert e.value.code in ("take_home", "supervisor")
    b = be.reserve(db, data=dict(base, supervisor_id="sup1"), now=NOW)
    assert b["status"] == "pending_supervisor"


def test_blocked_assets_and_overdue_borrower(db):
    add_asset(db, "bad", status="in_repair")
    add_asset(db, "off", borrowable=0)
    add_asset(db, "ok")
    for aid in ("bad", "off"):
        with pytest.raises(be.BookingError) as e:
            be.reserve(db, data=req(asset_id=aid), now=NOW)
        assert e.value.code == "asset"
    first = be.reserve(db, data=req(asset_id="ok", start_at="2026-08-04T08:00", end_at="2026-08-04T10:00"), now=NOW)
    db.execute("UPDATE bookings SET status = 'in_use' WHERE id = ?", (first["id"],))
    db.commit()
    assert be.mark_overdue(db, datetime(2026, 8, 5, 8, 0)) == 1
    with pytest.raises(be.BookingError) as e:
        be.reserve(db, data=req(asset_id="ok", start_at="2026-08-10T08:00", end_at="2026-08-10T10:00"), now=datetime(2026, 8, 5, 8, 0))
    assert e.value.code == "overdue"


def test_second_request_for_last_unit_refused(db):
    """Two requests for the same single unit on separate connections: only the first gets it."""
    import server
    add_asset(db, "cam1")
    db.execute("UPDATE asset_loan_settings SET requires_approval = 0 WHERE asset_id = 'cam1'")
    db.commit()
    c1, c2 = server.get_conn(), server.get_conn()
    results = []
    for c, uid in ((c1, "u1"), (c2, "u2")):
        try:
            results.append(be.reserve(c, data=req(asset_id="cam1", requester_id=uid), now=NOW)["status"])
        except be.BookingError as e:
            results.append(e.code)
    assert sorted(results) == ["approved", "conflict"]


def test_legacy_loans_are_migrated_once(db):
    add_asset(db, "cam1")
    ts = "2026-03-02T10:00:00+00:00"
    db.execute("""INSERT INTO loan_requests (id,asset_id,asset_name,asset_tag,requested_by,requested_by_name,purpose,start_date,end_date,
                  status,created_at,pre_condition,pre_image_path,post_condition,post_image_path,delivered_at,returned_at)
                  VALUES ('L1','cam1','Item cam1','T-cam1','u1','Guru A','Acara','2026-03-03','2026-03-04','returned',?,
                  'good','loans/L1/pre.jpg','broken','loans/L1/post.jpg',?,?)""", (ts, ts, ts))
    db.execute("""INSERT INTO loan_requests (id,asset_id,asset_name,asset_tag,requested_by,requested_by_name,status,created_at)
                  VALUES ('L2','cam1','Item cam1','T-cam1','u2','Guru B','pending',?)""", (ts,))
    db.commit()
    assert be.migrate_legacy_loans(db) == 2
    assert be.migrate_legacy_loans(db) == 0                      # idempotent
    done = dict(db.execute("SELECT * FROM bookings WHERE legacy_loan_id = 'L1'").fetchone())
    assert done["status"] == "completed" and done["campus"] == KK and done["category"] == "AV Equipment"
    assert done["start_at"] == "2026-03-03T08:00" and done["end_at"] == "2026-03-04T17:00"
    unit = dict(db.execute("SELECT * FROM booking_units WHERE booking_id = ?", (done["id"],)).fetchone())
    assert unit["pre_photo"] == "loans/L1/pre.jpg" and unit["post_photo"] == "loans/L1/post.jpg" and unit["condition_changed"] == 1
    pending = dict(db.execute("SELECT * FROM bookings WHERE legacy_loan_id = 'L2'").fetchone())
    assert pending["status"] == "pending_ict" and pending["units_approved"] is None
    assert db.execute("SELECT COUNT(*) FROM loan_requests").fetchone()[0] == 2      # old table untouched


# ---- hand-over / return ----
NOW_USE = datetime(2026, 8, 5, 8, 30)


def add_file(db, path="loans/x.jpg"):
    db.execute("INSERT OR IGNORE INTO files (id,storage_path,original_filename,content_type,size,uploaded_by,is_deleted,created_at) VALUES (?,?,?,?,1,'u',0,'t')",
               (path, path, "x.jpg", "image/jpeg"))
    db.commit()
    return path


def approved_loan(db, aid="cam1", accessories=None):
    add_asset(db, aid)
    if accessories:
        import json
        db.execute("UPDATE asset_loan_settings SET accessories = ? WHERE asset_id = ?", (json.dumps(accessories), aid))
        db.commit()
    b = be.reserve(db, data=req(asset_id=aid), now=NOW)
    return be.decide(db, booking_id=b["id"], decision="approved", by_id="ict", by_name="ICT", now=NOW)


def unit(**kw):
    base = dict(asset_id="cam1", physical="baik", function="normal", accessories=[], note="", photo="loans/x.jpg")
    base.update(kw)
    return base


def test_checkout_requires_photo_and_complete_checklist(db):
    b = approved_loan(db, accessories=["Charger", "Tas"])
    add_file(db)
    with pytest.raises(be.BookingError) as e:
        be.check_out(db, booking_id=b["id"], units=[unit(photo="", accessories=[{"name": "Charger", "ok": True}, {"name": "Tas", "ok": True}])],
                     now=NOW_USE, by_id="ict", by_name="ICT")
    assert e.value.code == "photo"
    with pytest.raises(be.BookingError) as e:                                   # checklist not fully answered
        be.check_out(db, booking_id=b["id"], units=[unit(accessories=[{"name": "Charger", "ok": True}])], now=NOW_USE, by_id="ict", by_name="ICT")
    assert e.value.code == "accessories"
    with pytest.raises(be.BookingError) as e:                                   # missing item needs a note
        be.check_out(db, booking_id=b["id"], units=[unit(accessories=[{"name": "Charger", "ok": True}, {"name": "Tas", "ok": False}])],
                     now=NOW_USE, by_id="ict", by_name="ICT")
    assert e.value.code == "note"
    out = be.check_out(db, booking_id=b["id"], units=[unit(accessories=[{"name": "Charger", "ok": True}, {"name": "Tas", "ok": True}])],
                       now=NOW_USE, by_id="ict", by_name="ICT")
    assert out["status"] == "in_use"


def test_cannot_checkout_before_start_day_or_twice(db):
    b = approved_loan(db)
    add_file(db)
    with pytest.raises(be.BookingError) as e:
        be.check_out(db, booking_id=b["id"], units=[unit()], now=datetime(2026, 8, 4, 9, 0), by_id="i", by_name="I")
    assert e.value.code == "too_early"
    be.check_out(db, booking_id=b["id"], units=[unit()], now=NOW_USE, by_id="i", by_name="I")
    with pytest.raises(be.BookingError) as e:
        be.check_out(db, booking_id=b["id"], units=[unit()], now=NOW_USE, by_id="i", by_name="I")
    assert e.value.code == "state"


def test_clean_return_completes_loan(db):
    b = approved_loan(db)
    add_file(db)
    be.check_out(db, booking_id=b["id"], units=[unit()], now=NOW_USE, by_id="i", by_name="I")
    res = be.check_in(db, booking_id=b["id"], units=[unit(result="ok")], now=datetime(2026, 8, 6, 14, 0), by_id="i", by_name="I")
    assert res["booking"]["status"] == "completed" and res["faults"] == []
    assert db.execute("SELECT status FROM assets WHERE id = 'cam1'").fetchone()[0] == "active"


def test_damaged_return_opens_fault_and_blocks_asset(db):
    b = approved_loan(db)
    add_file(db)
    be.check_out(db, booking_id=b["id"], units=[unit()], now=NOW_USE, by_id="i", by_name="I")
    with pytest.raises(be.BookingError) as e:                                  # must describe the damage
        be.check_in(db, booking_id=b["id"], units=[unit(result="damaged", physical="retak")], now=NOW_USE, by_id="i", by_name="I")
    assert e.value.code == "note"
    res = be.check_in(db, booking_id=b["id"], units=[unit(result="damaged", physical="retak", note="Layar retak")],
                      now=NOW_USE, by_id="i", by_name="I")
    assert res["booking"]["status"] == "problem" and len(res["faults"]) == 1
    assert db.execute("SELECT status FROM assets WHERE id = 'cam1'").fetchone()[0] == "in_repair"
    assert db.execute("SELECT status FROM faults WHERE id = ?", (res["faults"][0],)).fetchone()[0] == "open"
    with pytest.raises(be.BookingError) as e:                                  # cannot be borrowed until ICT fixes the status
        be.reserve(db, data=req(asset_id="cam1", requester_id="u9", start_at="2026-08-12T08:00", end_at="2026-08-12T10:00"), now=NOW)
    assert e.value.code == "asset"


def test_lost_item_needs_no_photo_and_marks_asset_lost(db):
    b = approved_loan(db)
    add_file(db)
    be.check_out(db, booking_id=b["id"], units=[unit()], now=NOW_USE, by_id="i", by_name="I")
    res = be.check_in(db, booking_id=b["id"], units=[unit(result="lost", photo="", note="Hilang saat acara")], now=NOW_USE, by_id="i", by_name="I")
    assert res["booking"]["status"] == "problem"
    assert db.execute("SELECT status FROM assets WHERE id = 'cam1'").fetchone()[0] == "lost"


def test_supervisor_and_cancel_flow(db):
    add_asset(db, "lap1", category="IT Equipment")
    b = be.reserve(db, data=req(asset_id="lap1", category="IT Equipment", take_home=True, supervisor_id="sup1",
                                start_at="2026-08-05T15:00", end_at="2026-08-07T08:00"), now=NOW)
    with pytest.raises(be.BookingError) as e:
        be.supervisor_decide(db, booking_id=b["id"], approve=True, by_id="someone", now=NOW)
    assert e.value.code == "forbidden"
    ok = be.supervisor_decide(db, booking_id=b["id"], approve=True, by_id="sup1", now=NOW)
    assert ok["status"] == "pending_ict"
    with pytest.raises(be.BookingError):
        be.cancel(db, booking_id=b["id"], by_id="stranger", can_manage=False, now=NOW)
    assert be.cancel(db, booking_id=b["id"], by_id="u1", can_manage=False, now=NOW)["status"] == "cancelled"
