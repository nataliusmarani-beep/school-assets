"""Reverse proxy: serve the RAB & Request app under /request on this host.

Why: some corporate networks only allow known host names. This app's host name is already allowed, so the
RAB & Request app (separate Railway service) is exposed at <this host>/request/... and fetched server-side.

The upstream app is told the public prefix via X-Proxy-Prefix (+ X-Proxy-Host, X-Proxy-Key) and emits URLs
under it. Only a fixed upstream is ever contacted (never a user-supplied URL), and only the RAB app's own
cookies are passed through, so this app's cookies never reach the upstream and vice versa.

Env:
  RAB_UPSTREAM      upstream base URL            (default https://request.ypj.sch.id)
  RAB_PROXY_PREFIX  public path prefix            (default /request; empty disables the proxy)
  RAB_PROXY_KEY     shared secret the upstream checks (optional but recommended)
"""
import os
import re
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

PREFIX_RE = re.compile(r"^/[a-z0-9][a-z0-9_-]{0,31}$")
# Cookies of the RAB app that may travel in either direction (name allow-list).
COOKIE_ALLOW = {"connect.sid", "lang"}
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "host", "content-length",
}
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _filter_cookie_header(value: str) -> str:
    kept = []
    for part in value.split(";"):
        name = part.split("=", 1)[0].strip()
        if name in COOKIE_ALLOW:
            kept.append(part.strip())
    return "; ".join(kept)


def _cookie_name(set_cookie: str) -> str:
    return set_cookie.split("=", 1)[0].strip()


def register_rab_proxy(app: FastAPI, upstream: Optional[str] = None, prefix: Optional[str] = None,
                       key: Optional[str] = None, transport: Optional[httpx.AsyncBaseTransport] = None) -> bool:
    """Attach the proxy routes to `app`. Must be called BEFORE the SPA catch-all route is defined."""
    prefix = os.environ.get("RAB_PROXY_PREFIX", "/request") if prefix is None else prefix
    if not prefix:
        return False
    if not PREFIX_RE.match(prefix):
        raise ValueError(f"RAB_PROXY_PREFIX must look like /request, got {prefix!r}")
    upstream = (upstream or os.environ.get("RAB_UPSTREAM", "https://request.ypj.sch.id")).rstrip("/")
    key = key if key is not None else os.environ.get("RAB_PROXY_KEY", "")

    client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(60.0, connect=10.0), transport=transport)

    @app.on_event("shutdown")
    async def _close_rab_client():
        await client.aclose()

    @app.api_route(prefix, methods=["GET", "HEAD"], include_in_schema=False)
    async def _rab_root_redirect(request: Request):
        return RedirectResponse(prefix + "/", status_code=308)

    @app.api_route(prefix + "/{path:path}", methods=METHODS, include_in_schema=False)
    async def _rab_proxy(path: str, request: Request):
        url = f"{upstream}/{path}"
        if request.url.query:
            url += "?" + request.url.query

        headers = {}
        for name, value in request.headers.items():
            n = name.lower()
            if n in HOP_BY_HOP or n in {"cookie", "authorization", "x-proxy-prefix", "x-proxy-host", "x-proxy-key",
                                        "x-forwarded-host", "x-forwarded-prefix"}:
                continue
            headers[name] = value
        cookie = _filter_cookie_header(request.headers.get("cookie", ""))
        if cookie:
            headers["cookie"] = cookie
        headers["x-proxy-prefix"] = prefix
        headers["x-proxy-host"] = request.headers.get("host", "")
        if key:
            headers["x-proxy-key"] = key

        body = None if request.method in ("GET", "HEAD") else await request.body()
        try:
            upstream_resp = await client.send(
                client.build_request(request.method, url, headers=headers, content=body), stream=True
            )
        except httpx.HTTPError:
            return Response("RAB & Request is temporarily unavailable.", status_code=502, media_type="text/plain")

        out_headers = {}
        for name, value in upstream_resp.headers.items():
            n = name.lower()
            if n in HOP_BY_HOP or n == "set-cookie":
                continue
            out_headers[name] = value
        # Real responses stream raw bytes (content-encoding is passed through untouched). A response whose body is
        # already in memory (e.g. an in-process test transport) cannot be re-streamed, so send its content as is.
        async def _once(data: bytes):
            yield data

        body_iter = _once(upstream_resp.content) if upstream_resp.is_stream_consumed else upstream_resp.aiter_raw()
        response = StreamingResponse(
            body_iter, status_code=upstream_resp.status_code, headers=out_headers,
            background=BackgroundTask(upstream_resp.aclose),
        )
        # Only pass through the RAB app's own cookies (names are allow-listed).
        for name, value in upstream_resp.headers.multi_items():
            if name.lower() == "set-cookie" and _cookie_name(value) in COOKIE_ALLOW:
                response.raw_headers.append((b"set-cookie", value.encode("latin-1")))
        response.headers["x-content-type-options"] = "nosniff"
        return response

    return True
