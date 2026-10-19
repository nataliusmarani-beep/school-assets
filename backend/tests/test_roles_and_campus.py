import server
from conftest import auth


def test_campus_rename_migrates_existing_rows(db):
    db.execute("INSERT INTO users (id,email,name,role,campus,password_hash,created_at) VALUES ('u1','a@x.y','A','staff','YPJ Tembagapura','h','t')")
    db.execute("DELETE FROM app_meta WHERE key = 'campus_tpra_rename_v1'")
    db.commit()
    server.rename_campus_tembagapura_to_tpra(db)
    assert db.execute("SELECT campus FROM users WHERE id='u1'").fetchone()[0] == "YPJ TPRA"
    # running again is a no-op
    db.execute("UPDATE users SET campus = 'YPJ Tembagapura' WHERE id='u1'")
    db.commit()
    server.rename_campus_tembagapura_to_tpra(db)
    assert db.execute("SELECT campus FROM users WHERE id='u1'").fetchone()[0] == "YPJ Tembagapura"


def test_leader_can_read_but_not_write(client, make_user):
    leader = make_user("leader")
    assert client.get("/api/assets", headers=auth(leader)).status_code == 200
    r = client.post("/api/assets/x/loan-request", headers=auth(leader), json={})
    assert r.status_code == 403
    assert client.post("/api/auth/logout", headers=auth(leader)).status_code != 403


def test_leader_sees_all_campuses(client, make_user, db):
    for i, campus in enumerate(["YPJ Kuala Kencana", "YPJ TPRA"]):
        db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,purchase_price,purchase_date,created_at,updated_at) VALUES (?,?,?,?,?,?,0,'2026-01-01',?,?)",
                   (f"a{i}", f"Asset {i}", f"T-{i}", "IT Equipment", campus, "Lab", "t", "t"))
    db.commit()
    leader = make_user("leader", campus="")
    staff = make_user("staff", campus="YPJ TPRA")
    assert len(client.get("/api/assets", headers=auth(leader)).json()) == 2
    assert len(client.get("/api/assets", headers=auth(staff)).json()) == 1


def test_ict_pic_scope(make_user):
    kk = make_user("ict_admin", "YPJ Kuala Kencana")
    assert server.is_ict_pic(kk, "YPJ Kuala Kencana", "IT Equipment")
    assert server.is_ict_pic(kk, "YPJ Kuala Kencana", "Music Equipment")
    assert not server.is_ict_pic(kk, "YPJ TPRA", "IT Equipment")           # other campus
    assert not server.is_ict_pic(kk, "YPJ Kuala Kencana", "Furniture")      # other category
    assert not server.is_ict_pic(make_user("admin"), "YPJ Kuala Kencana", "IT Equipment")
    assert server.is_ict_pic(make_user("super_admin", ""), "YPJ TPRA", "Furniture")


def test_ict_admin_requires_campus(client, make_user):
    admin = make_user("admin")
    body = {"email": "ict@example.com", "password": "secret123", "name": "ICT", "role": "ict_admin", "department": "ICT"}
    assert client.post("/api/auth/register", headers=auth(admin), json=body).status_code == 400
    body["campus"] = "YPJ TPRA"
    assert client.post("/api/auth/register", headers=auth(admin), json=body).status_code == 200


def test_campus_alias_accepts_tembagapura_label():
    assert server.normalize_campus("YPJ Tembagapura") == "YPJ TPRA"
    assert server.normalize_campus(" ypj tembagapura ") == "YPJ TPRA"
    assert server.normalize_campus("YPJ TPRA") == "YPJ TPRA"
    assert server.normalize_campus("YPJ Kuala Kencana") == "YPJ Kuala Kencana"


def test_user_import_accepts_tembagapura_label(db):
    rows = [{"name": "Sari", "email": "sari@example.com", "role": "staff", "campus": "YPJ Tembagapura"}]
    checked = server._validate_user_rows(db, rows)
    assert checked[0]["errors"] == [] and checked[0]["data"]["campus"] == "YPJ TPRA"


def test_clock_is_wit():
    from datetime import datetime, timezone
    assert server.LOCAL_TZ.utcoffset(None).total_seconds() == 9 * 3600
    diff = (server._local_now() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
    assert 9 * 3600 - 120 < diff < 9 * 3600 + 120


def test_ict_admin_manages_only_own_campus_ict_assets(client, make_user, db):
    for aid, cat, campus in [("a1", "IT Equipment", "YPJ Kuala Kencana"), ("a2", "Furniture", "YPJ Kuala Kencana"), ("a3", "IT Equipment", "YPJ TPRA")]:
        db.execute("INSERT INTO assets (id,name,asset_tag,category,campus,location,purchase_price,purchase_date,created_at,updated_at) VALUES (?,?,?,?,?,?,0,'2026-01-01','t','t')",
                   (aid, aid, f"T-{aid}", cat, campus, "Lab"))
    db.commit()
    ict = make_user("ict_admin", "YPJ Kuala Kencana")
    h = auth(ict)
    assert client.put("/api/assets/a1", headers=h, json={"name": "Renamed"}).status_code == 200
    assert client.put("/api/assets/a2", headers=h, json={"name": "x"}).status_code == 403   # not ICT category
    assert client.put("/api/assets/a3", headers=h, json={"name": "x"}).status_code == 403   # other campus
    assert client.put("/api/assets/a1", headers=h, json={"category": "Furniture"}).status_code == 403
    assert client.delete("/api/assets/a3", headers=h).status_code == 403
    assert client.delete("/api/assets/a1", headers=h).status_code == 200
    assert client.get("/api/users", headers=h).status_code in (200, 403)
    assert client.post("/api/users/x/invite", headers=h).status_code == 403
