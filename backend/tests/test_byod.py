"""BYOD approval: parent (link) -> teacher -> ICT, laptops / iPads / tablets only."""
import re
from datetime import timedelta

import server
from conftest import auth

KK = "YPJ Kuala Kencana"
SIG = "data:image/png;base64," + "A" * 600
STATEMENTS = {k: True for k in server.BYOD_STATEMENTS}


def day(n):
    return (server._local_now() + timedelta(days=n)).strftime("%Y-%m-%d")


def project(**kw):
    body = {"name": "Pameran Sains", "subject": "IPA", "location": "Lab IPA", "start_date": day(1), "end_date": day(30),
            "students": [{"name": "Budi Santoso", "class_name": "8A", "parent_email": "ortu@example.com", "parent_phone": "0812345678"}]}
    body.update(kw)
    return body


def parent_body(mac="a1:b2:c3:d4:e5:f6", kind="laptop", **kw):
    body = {"parent_name": "Ibu Budi", "parent_relation": "Ibu", "signature": SIG, "statements": STATEMENTS, "lang": "ID",
            "devices": [{"kind": kind, "brand": "Apple", "model": "MacBook Air", "os": "macOS", "os_version": "14", "mac": mac}]}
    body.update(kw)
    return body


def token_of(res):
    return res["requests"][0]["link"].split("token=")[1]


def test_full_flow_parent_teacher_ict(client, make_user, db):
    teacher, ict = make_user("staff", KK), make_user("ict_admin", KK)
    r = client.post("/api/byod/projects", headers=auth(teacher), json=project())
    assert r.status_code == 200, r.text
    res = r.json()
    rid, tok = res["requests"][0]["id"], token_of(res)
    assert res["requests"][0]["sent"]["email"] and re.match(r"BYOD-\d{4}-0001", res["requests"][0]["number"])

    # teacher / ICT cannot jump ahead of the parent
    assert client.put(f"/api/byod/requests/{rid}/teacher-sign", headers=auth(teacher), json={"signed_name": "staff user", "signature": SIG, "agree": True}).status_code == 409
    assert client.put(f"/api/byod/requests/{rid}/decide", headers=auth(ict), json={"decision": "approved"}).status_code == 409

    form = client.get(f"/api/public/byod/{tok}")
    assert form.status_code == 200 and form.json()["student_name"] == "Budi Santoso" and "parent_email" not in form.json()
    assert client.get("/api/public/byod/bogus").status_code == 404

    s = client.post(f"/api/public/byod/{tok}/sign", json=parent_body())
    assert s.status_code == 200, s.text
    assert client.get(f"/api/public/byod/{tok}").status_code == 404                      # one-time link
    assert client.post(f"/api/public/byod/{tok}/sign", json=parent_body()).status_code == 404

    v = client.get(f"/api/byod/requests/{rid}", headers=auth(teacher)).json()
    assert v["status"] == "waiting_teacher" and v["devices"][0]["mac"] == "A1:B2:C3:D4:E5:F6" and v["parent_signature"]

    assert client.put(f"/api/byod/requests/{rid}/teacher-sign", headers=auth(teacher), json={"signed_name": "wrong", "signature": SIG, "agree": True}).status_code == 400
    t = client.put(f"/api/byod/requests/{rid}/teacher-sign", headers=auth(teacher), json={"signed_name": "Staff User", "signature": SIG, "agree": True})
    assert t.status_code == 200 and t.json()["status"] == "waiting_ict"

    # only the campus ICT Admin decides; a teacher or another campus cannot
    assert client.put(f"/api/byod/requests/{rid}/decide", headers=auth(teacher), json={"decision": "approved"}).status_code == 403
    other = make_user("ict_admin", "YPJ TPRA")
    assert client.put(f"/api/byod/requests/{rid}/decide", headers=auth(other), json={"decision": "approved"}).status_code == 403
    dev_id = v["devices"][0]["id"]
    d = client.put(f"/api/byod/requests/{rid}/decide", headers=auth(ict),
                   json={"decision": "approved", "note": "OK", "devices": [{"id": dev_id, "mac": "11-22-33-44-55-66"}]})
    assert d.status_code == 200 and d.json()["status"] == "approved" and d.json()["effective_status"] == "scheduled"
    assert d.json()["devices"][0]["mac"] == "11:22:33:44:55:66"
    assert [e["action"] for e in d.json()["events"]][-3:] == ["parent_signed", "teacher_signed", "approved"]
    x = client.get("/api/reports/byod-devices", headers=auth(ict))
    assert x.status_code == 200 and client.get("/api/reports/byod-devices", headers=auth(teacher)).status_code == 403


def test_validation_devices_signature_statements(client, make_user):
    teacher = make_user("staff", KK)
    tok = token_of(client.post("/api/byod/projects", headers=auth(teacher), json=project()).json())
    path = f"/api/public/byod/{tok}/sign"
    assert client.post(path, json=parent_body(kind="phone")).status_code == 400                       # only laptop / ipad / tablet
    assert client.post(path, json=parent_body(mac="zz")).status_code == 400
    assert client.post(path, json=parent_body(signature="data:image/png;base64,AA")).status_code == 400
    assert client.post(path, json=parent_body(statements={**STATEMENTS, "liability": False})).status_code == 400
    three = parent_body()["devices"] * 3
    assert client.post(path, json=parent_body(devices=three)).status_code == 400
    assert client.post(path, json=parent_body(kind="tablet")).status_code == 200


def test_project_rules_and_duplicate_mac(client, make_user):
    teacher = make_user("staff", KK)
    h = auth(teacher)
    assert client.post("/api/byod/projects", headers=h, json=project(start_date=day(-2))).status_code == 400
    assert client.post("/api/byod/projects", headers=h, json=project(end_date=day(120))).status_code == 400             # over ~3 months
    assert client.post("/api/byod/projects", headers=h, json=project(hour_from="16:00", hour_to="08:00")).status_code == 400
    assert client.post("/api/byod/projects", headers=h, json=project(students=[{"name": "Ani"}])).status_code == 400    # no way to reach the parent
    a = client.post("/api/byod/projects", headers=h, json=project()).json()
    b = client.post("/api/byod/projects", headers=h, json=project(students=[{"name": "Citra", "parent_email": "c@example.com"}])).json()
    assert client.post(f"/api/public/byod/{token_of(a)}/sign", json=parent_body()).status_code == 200
    # the same MAC cannot be registered for a second student
    assert client.post(f"/api/public/byod/{token_of(b)}/sign", json=parent_body()).status_code == 409


def test_resend_cancel_revoke_extend(client, make_user):
    teacher, ict, other_teacher = make_user("staff", KK), make_user("ict_admin", KK), make_user("staff", KK)
    res = client.post("/api/byod/projects", headers=auth(teacher), json=project()).json()
    rid, old = res["requests"][0]["id"], token_of(res)
    assert client.post(f"/api/byod/requests/{rid}/resend", headers=auth(other_teacher)).status_code == 403
    new = client.post(f"/api/byod/requests/{rid}/resend", headers=auth(teacher)).json()["link"].split("token=")[1]
    assert client.get(f"/api/public/byod/{old}").status_code == 404 and client.get(f"/api/public/byod/{new}").status_code == 200
    client.post(f"/api/public/byod/{new}/sign", json=parent_body())
    client.put(f"/api/byod/requests/{rid}/teacher-sign", headers=auth(teacher), json={"signed_name": "staff user", "signature": SIG, "agree": True})
    client.put(f"/api/byod/requests/{rid}/decide", headers=auth(ict), json={"decision": "approved"})

    # one extension, decided by ICT
    e = client.put(f"/api/byod/requests/{rid}/extend", headers=auth(teacher), json={"new_end_date": day(60)})
    assert e.status_code == 200 and e.json()["pending_end_date"] == day(60)
    assert client.put(f"/api/byod/requests/{rid}/extend", headers=auth(teacher), json={"new_end_date": day(70)}).status_code == 409
    ok = client.put(f"/api/byod/requests/{rid}/decide", headers=auth(ict), json={"decision": "approved"}).json()
    assert ok["valid_to"] == day(60) and ok["status"] == "approved" and ok["extended_count"] == 1
    assert client.put(f"/api/byod/requests/{rid}/extend", headers=auth(teacher), json={"new_end_date": day(90)}).status_code == 409

    assert client.put(f"/api/byod/requests/{rid}/revoke", headers=auth(teacher), json={"reason": "x" * 5}).status_code == 403
    assert client.put(f"/api/byod/requests/{rid}/revoke", headers=auth(ict), json={"reason": ""}).status_code == 400
    rv = client.put(f"/api/byod/requests/{rid}/revoke", headers=auth(ict), json={"reason": "Pelanggaran aturan"})
    assert rv.status_code == 200 and rv.json()["status"] == "revoked"
    # after revoking, the MAC is free again
    res2 = client.post("/api/byod/projects", headers=auth(teacher), json=project(students=[{"name": "Dedi", "parent_email": "d@example.com"}])).json()
    assert client.post(f"/api/public/byod/{token_of(res2)}/sign", json=parent_body()).status_code == 200


def test_visibility_and_policy_gate(client, make_user):
    teacher, stranger, leader = make_user("staff", KK), make_user("staff", KK), make_user("leader", KK)
    unsigned = make_user("staff", KK, accepted=False)
    assert client.post("/api/byod/projects", headers=auth(unsigned), json=project()).status_code == 403          # must confirm policies first
    rid = client.post("/api/byod/projects", headers=auth(teacher), json=project()).json()["requests"][0]["id"]
    assert client.get(f"/api/byod/requests/{rid}", headers=auth(stranger)).status_code == 403
    assert client.get(f"/api/byod/requests/{rid}", headers=auth(leader)).status_code == 200
    assert client.get("/api/byod/requests?scope=mine", headers=auth(stranger)).json() == []
    assert len(client.get("/api/byod/requests?scope=mine", headers=auth(teacher)).json()) == 1
    assert client.post("/api/byod/projects", headers=auth(leader), json=project()).status_code == 403             # leaders are view-only


def test_mac_is_optional_but_must_be_valid_when_given():
    import byod
    base = {"kind": "laptop", "brand": "Apple", "model": "MacBook Air"}
    assert byod.validate_devices([{**base}])[0]["mac"] == ""
    assert byod.validate_devices([{**base, "mac": "  "}, {**base, "mac": ""}])[1]["mac"] == ""     # blanks are not duplicates
    assert byod.validate_devices([{**base, "mac": "a1-b2-c3-d4-e5-f6"}])[0]["mac"] == "A1:B2:C3:D4:E5:F6"
    try:
        byod.validate_devices([{**base, "mac": "zz"}])
    except byod.ByodError:
        pass
    else:
        raise AssertionError("invalid MAC must still be rejected")
