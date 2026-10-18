from conftest import auth
import server

OK = {"version": server.POLICY_VERSION, "read_all": True, "will_comply": True, "accept_sanctions": True, "text_hash": "abc", "lang": "ID"}


def test_me_reports_policy_not_accepted_then_accepted(client, make_user):
    u = make_user("staff")
    me = client.get("/api/auth/me", headers=auth(u)).json()
    assert me["policy_required"] and not me["policy_accepted"]
    r = client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "  STAFF   user "})
    assert r.status_code == 200 and r.json()["policy_accepted"]
    assert client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]


def test_requires_all_statements_and_matching_name(client, make_user):
    u = make_user("staff")
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user", "accept_sanctions": False}).status_code == 400
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "Someone Else"}).status_code == 400
    assert not client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]


def test_new_version_forces_reconfirmation(client, make_user, monkeypatch):
    u = make_user("staff")
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user"}).status_code == 200
    monkeypatch.setattr(server, "POLICY_VERSION", "9999.1")
    assert not client.get("/api/auth/me", headers=auth(u)).json()["policy_accepted"]
    assert client.post("/api/policy/accept", headers=auth(u), json={**OK, "signed_name": "staff user"}).status_code == 409


def test_leader_not_required_and_admin_lists(client, make_user):
    leader, admin, staff = make_user("leader"), make_user("admin"), make_user("staff")
    me = client.get("/api/auth/me", headers=auth(leader)).json()
    assert not me["policy_required"] and me["policy_accepted"]
    client.post("/api/policy/accept", headers=auth(staff), json={**OK, "signed_name": "staff user"})
    items = {i["id"]: i for i in client.get("/api/policy/acceptances", headers=auth(admin)).json()["items"]}
    assert items[staff["id"]]["current"] and not items[admin["id"]]["current"]
    assert client.get("/api/policy/acceptances", headers=auth(staff)).status_code == 403
    assert client.get("/api/reports/policy-acceptances", headers=auth(admin)).status_code == 200
