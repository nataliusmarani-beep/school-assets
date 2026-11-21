"""RAB & Request reverse proxy (backend/rab_proxy.py): header/cookie hygiene, prefix handling, error mapping."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.rab_proxy import register_rab_proxy


def make_client(handler, key="k3y"):
    app = FastAPI()
    register_rab_proxy(app, upstream="http://rab.test", prefix="/request", key=key,
                       transport=httpx.MockTransport(handler))
    return TestClient(app, follow_redirects=False)


def test_prefix_is_stripped_and_proxy_headers_are_sent():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["headers"] = str(req.url), req.headers
        return httpx.Response(200, text="ok")

    r = make_client(handler).get("/request/rab/5?x=1", headers={"host": "ypjassets.ypj.sch.id"})
    assert r.status_code == 200
    assert seen["url"] == "http://rab.test/rab/5?x=1"
    assert seen["headers"]["x-proxy-prefix"] == "/request"
    assert seen["headers"]["x-proxy-host"] == "ypjassets.ypj.sch.id"
    assert seen["headers"]["x-proxy-key"] == "k3y"


def test_only_rab_cookies_and_no_authorization_reach_upstream():
    seen = {}

    def handler(req: httpx.Request):
        seen["headers"] = req.headers
        return httpx.Response(200)

    c = make_client(handler)
    c.get("/request/x", headers={"cookie": "auth_token=SECRET; connect.sid=abc; lang=id", "authorization": "Bearer T0KEN"})
    assert seen["headers"]["cookie"] == "connect.sid=abc; lang=id"
    assert "authorization" not in seen["headers"]


def test_client_cannot_spoof_proxy_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen["headers"] = req.headers
        return httpx.Response(200)

    make_client(handler).get("/request/x", headers={"x-proxy-prefix": "/evil", "x-proxy-key": "guess", "host": "h.example"})
    assert seen["headers"]["x-proxy-prefix"] == "/request"
    assert seen["headers"]["x-proxy-key"] == "k3y"


def test_only_allow_listed_set_cookies_pass_back():
    def handler(req: httpx.Request):
        return httpx.Response(200, headers=[("set-cookie", "connect.sid=s1; Path=/request; HttpOnly"),
                                            ("set-cookie", "asset_session=evil; Path=/"),
                                            ("set-cookie", "lang=id; Path=/request")])

    r = make_client(handler).get("/request/login")
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("connect.sid=") for c in cookies)
    assert any(c.startswith("lang=") for c in cookies)
    assert not any(c.startswith("asset_session=") for c in cookies)


def test_post_body_status_and_redirects_pass_through():
    def handler(req: httpx.Request):
        assert req.method == "POST" and req.content == b"a=1&b=2"
        return httpx.Response(302, headers={"location": "/request/rab"})

    r = make_client(handler).post("/request/login", content=b"a=1&b=2",
                                  headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 302 and r.headers["location"] == "/request/rab"


def test_bare_prefix_redirects_to_trailing_slash():
    r = make_client(lambda req: httpx.Response(200)).get("/request")
    assert r.status_code == 308 and r.headers["location"].endswith("/request/")


def test_upstream_down_is_a_502_not_a_traceback():
    def handler(req: httpx.Request):
        raise httpx.ConnectError("boom")

    r = make_client(handler).get("/request/x")
    assert r.status_code == 502


def test_bad_prefix_is_rejected_and_empty_prefix_disables():
    with pytest.raises(ValueError):
        register_rab_proxy(FastAPI(), upstream="http://x", prefix='/a"><b')
    assert register_rab_proxy(FastAPI(), upstream="http://x", prefix="") is False
