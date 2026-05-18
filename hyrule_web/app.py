"""Hyrule Cloud web frontend — lightweight, server-rendered, Tor-friendly."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import DEFAULT_OS_TEMPLATES, VM_TIERS, settings
from .seo import ROBOTS_TXT, build_llms_txt, render_sitemap_xml

# Newline-delimited JSON to stdout per AS215932's application logging
# contract (hyrule-infra/docs/application-logging.md). systemd-journald
# captures it; the host's Vector agent ships to Loki.
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.contextvars.merge_contextvars,
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    cache_logger_on_first_use=True,
)
log = structlog.get_logger().bind(service="hyrule-web")

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=30,
    )
    yield
    await app.state.http.aclose()


app = FastAPI(title="Hyrule Cloud", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _render(request: Request, name: str, **kwargs: Any) -> Response:
    """Render a template with common context variables.

    Always injects `runtime` so every template can pull live numbers from
    the header pill / footer / inline mentions without each handler having
    to fetch them. When the runtime fetch fails the value is None and
    templates fall back to sensible placeholders.
    """
    ctx: dict[str, Any] = {"vm_tiers": VM_TIERS, **kwargs}
    if "runtime" not in ctx:
        ctx["runtime"] = _RUNTIME_CACHE.get("value")
    return templates.TemplateResponse(request, name, ctx)


# Frontend-side 15s cache so per-page renders never call the backend directly
# in a hot loop. The backend already caches at 20s in /v1/stats/runtime; we
# stack a smaller TTL here so the homepage stays responsive even if the
# backend is briefly unavailable (the previous value lingers as a fallback).
_RUNTIME_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_RUNTIME_TTL_SECONDS = 15
_RUNTIME_FALLBACK = {
    "api_p50_ms": None,
    "api_p50_source": "fallback",
    "build_queue": None,
    "live_vms": None,
    "avg_provision_seconds": None,
    "updated_at": None,
}

# Block H: same pattern for /v1/stats/network — 30s frontend TTL, stale-on-error.
_NETWORK_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_NETWORK_TTL_SECONDS = 30


async def _refresh_runtime(request: Request) -> dict[str, Any] | None:
    """Pull /v1/stats/runtime, cache for 15s. Stale-on-error: if the fetch
    fails we serve the last good value rather than punching a hole through
    to None — better UX than a flicker."""
    now = time.time()
    cached = _RUNTIME_CACHE.get("value")
    if cached is not None and now < float(_RUNTIME_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/stats/runtime")
    if data is not None:
        _RUNTIME_CACHE["value"] = data
        _RUNTIME_CACHE["expires_at"] = now + _RUNTIME_TTL_SECONDS
        return data
    # Hold the last good value past its TTL when the backend is down.
    return cached


async def _refresh_network(request: Request) -> dict[str, Any] | None:
    """Pull /v1/stats/network, cache for 30s. Stale-on-error, same as runtime.
    The backend itself returns _source="fallback" on Prometheus failure, so
    None here only means the backend itself is unreachable."""
    now = time.time()
    cached = _NETWORK_CACHE.get("value")
    if cached is not None and now < float(_NETWORK_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/stats/network")
    if data is not None:
        _NETWORK_CACHE["value"] = data
        _NETWORK_CACHE["expires_at"] = now + _NETWORK_TTL_SECONDS
        return data
    return cached


async def _fetch_api(request: Request, path: str) -> dict[str, Any] | None:
    """GET a JSON endpoint from the backend API, return parsed dict or None."""
    try:
        resp = await request.app.state.http.get(path)
        if resp.status_code == 200:
            data: dict[str, Any] = resp.json()
            return data
        log.warn("api_non_200", path=path, status=resp.status_code)
    except httpx.HTTPError as exc:
        log.error(
            "api_fetch_failed",
            path=path,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
    return None


async def _api_request(
    request: Request,
    path: str,
    *,
    method: str = "GET",
    json: dict | None = None,
    forward_cookie: bool = True,
) -> httpx.Response | None:
    """Issue a backend call from a server-side handler, optionally forwarding
    the browser's session cookie so account-scoped endpoints work."""
    client: httpx.AsyncClient = request.app.state.http
    headers: dict[str, str] = {}
    if forward_cookie:
        cookie = request.headers.get("cookie")
        if cookie:
            headers["cookie"] = cookie
    try:
        return await client.request(method=method, url=path, headers=headers, json=json)
    except httpx.HTTPError as exc:
        log.error("api_request_failed", path=path, method=method, error=str(exc))
        return None


def _copy_set_cookie(backend_resp: httpx.Response, response: Response) -> None:
    """Copy backend Set-Cookie headers onto our outgoing response so login/
    register sessions reach the browser. Preserves multiple Set-Cookie values."""
    for k, v in backend_resp.headers.multi_items():
        if k.lower() == "set-cookie":
            response.raw_headers.append((b"set-cookie", v.encode("latin-1")))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> Response:
    runtime = await _refresh_runtime(request)
    return _render(request, "index.html", runtime=runtime)


@app.get("/transparency", response_class=HTMLResponse)
async def page_transparency(request: Request) -> Response:
    """Infra-truth page: ASN, hosts, peering, jurisdiction. Block G.

    Block H: live fleet numbers (BGP peers, NAT64 sessions, IPv6 prefixes)
    come from /v1/stats/network. Falls back to the static shape when
    Prometheus on the `mon` VM is unreachable.
    """
    await _refresh_runtime(request)
    network = await _refresh_network(request)
    return _render(request, "transparency.html", network=network)


@app.get("/faq", response_class=HTMLResponse)
async def page_faq(request: Request) -> Response:
    """FAQ + JSON-LD. Only mentions live payment methods. Block G."""
    await _refresh_runtime(request)
    networks = await _fetch_api(request, "/v1/payments/networks") or {"networks": []}
    return _render(request, "faq.html", networks=networks.get("networks", []))

@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request) -> Response:
    me_resp = await _api_request(request, "/v1/me")
    if me_resp is None or me_resp.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if me_resp.status_code != 200:
        return _render(request, "dashboard.html", me=None, vms=[], error="Could not load account info.")

    me = me_resp.json()
    vms_resp = await _api_request(request, "/v1/me/vms")
    vms = vms_resp.json().get("vms", []) if (vms_resp and vms_resp.status_code == 200) else []
    return _render(request, "dashboard.html", me=me, vms=vms)


# --- Auth pages ---


@app.get("/signup", response_class=HTMLResponse)
async def page_signup(request: Request) -> Response:
    return _render(request, "signup.html", error=None)


@app.post("/signup", response_class=HTMLResponse)
async def do_signup(
    request: Request,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    if password != password_confirm:
        return _render(request, "signup.html", error="Passwords do not match.")
    if len(password) < 12:
        return _render(request, "signup.html", error="Password must be at least 12 characters.")

    backend = await _api_request(
        request, "/v1/auth/register", method="POST", json={"password": password}
    )
    if backend is None:
        return _render(request, "signup.html", error="Backend unreachable. Try again.")
    if backend.status_code == 429:
        return _render(request, "signup.html", error="Too many signups from your network; try later.")
    if backend.status_code != 200:
        return _render(request, "signup.html", error="Signup failed. Try again.")

    body = backend.json()
    rendered = _render(
        request, "signup_success.html",
        account_id=body["account_id"],
        recovery_code=body["recovery_code"],
    )
    _copy_set_cookie(backend, rendered)
    return rendered


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request) -> Response:
    return _render(request, "login.html", error=None)


@app.post("/login", response_class=HTMLResponse)
async def do_login(
    request: Request,
    account_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    backend = await _api_request(
        request, "/v1/auth/login", method="POST",
        json={"account_id": account_id.strip().upper(), "password": password},
    )
    if backend is None:
        return _render(request, "login.html", error="Backend unreachable.")
    if backend.status_code == 429:
        return _render(request, "login.html", error="Too many login attempts; try later.")
    if backend.status_code != 200:
        return _render(request, "login.html", error="Invalid credentials.")

    redirect = RedirectResponse("/dashboard", status_code=303)
    _copy_set_cookie(backend, redirect)
    return redirect


@app.post("/logout", response_class=HTMLResponse)
async def do_logout(request: Request) -> Response:
    backend = await _api_request(request, "/v1/auth/logout", method="POST")
    redirect = RedirectResponse("/", status_code=303)
    if backend is not None:
        _copy_set_cookie(backend, redirect)
    return redirect


@app.get("/recover", response_class=HTMLResponse)
async def page_recover(request: Request) -> Response:
    return _render(request, "recover.html", error=None, success=None)


@app.post("/recover", response_class=HTMLResponse)
async def do_recover(
    request: Request,
    account_id: Annotated[str, Form()],
    recovery_code: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
) -> Response:
    if new_password != new_password_confirm:
        return _render(request, "recover.html", error="Passwords do not match.", success=None)
    if len(new_password) < 12:
        return _render(request, "recover.html", error="Password must be at least 12 characters.", success=None)

    backend = await _api_request(
        request, "/v1/auth/recover/code", method="POST",
        json={
            "account_id": account_id.strip().upper(),
            "recovery_code": recovery_code.strip(),
            "new_password": new_password,
        },
    )
    if backend is None:
        return _render(request, "recover.html", error="Backend unreachable.", success=None)
    if backend.status_code == 429:
        return _render(request, "recover.html", error="Too many recovery attempts; try later.", success=None)
    if backend.status_code != 200:
        return _render(request, "recover.html", error="Invalid recovery code or account ID.", success=None)

    body = backend.json()
    return _render(
        request, "recover.html",
        error=None,
        success={"account_id": body["account_id"], "new_recovery_code": body["new_recovery_code"]},
    )


# --- Dashboard actions (HTMX-friendly, all server-side) ---


@app.post("/dashboard/vms/{vm_id}/reboot", response_class=HTMLResponse)
async def dash_reboot(request: Request, vm_id: str) -> Response:
    await _api_request(request, f"/v1/vm/{vm_id}/reboot", method="POST")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/vms/{vm_id}/destroy", response_class=HTMLResponse)
async def dash_destroy(request: Request, vm_id: str) -> Response:
    await _api_request(request, f"/v1/vm/{vm_id}", method="DELETE")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/claim", response_class=HTMLResponse)
async def dash_claim(
    request: Request,
    vm_id: Annotated[str, Form()],
    token: Annotated[str, Form()],
) -> Response:
    await _api_request(
        request, f"/v1/me/vms/{vm_id.strip()}/claim", method="POST",
        json={"proof": "management_token", "token": token.strip()},
    )
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/password", response_class=HTMLResponse)
async def dash_change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> Response:
    await _api_request(
        request, "/v1/me/password", method="POST",
        json={"current_password": current_password, "new_password": new_password},
    )
    return RedirectResponse("/dashboard", status_code=303)



@app.get("/services", response_class=HTMLResponse)
async def page_services(request: Request) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    return _render(request, "services.html", os_templates=os_list)


@app.get("/order", response_class=HTMLResponse)
async def page_order(request: Request) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    return _render(request, "order.html", os_templates=os_list)


@app.post("/order/review", response_class=HTMLResponse)
async def page_review(
    request: Request,
    os: Annotated[str, Form()],
    size: Annotated[str, Form()],
    duration: Annotated[int, Form()],
    ssh_pubkey: Annotated[str, Form()],
    hostname: Annotated[str, Form()] = "",
    domain_mode: Annotated[str, Form()] = "auto",
    domain: Annotated[str, Form()] = "",
) -> Response:
    tier = VM_TIERS.get(size, VM_TIERS["sm"])
    daily = tier["price"]
    total = daily * duration

    order = {
        "os": os,
        "size": size,
        "duration": duration,
        "ssh_pubkey": ssh_pubkey,
        "hostname": hostname,
        "domain_mode": domain_mode,
        "domain": domain,
        "id": "order-draft",
    }

    return _render(
        request, "review.html",
        order=order, tier=tier, total=total,
    )


@app.get("/order/status/{vm_id}", response_class=HTMLResponse)
async def page_status(request: Request, vm_id: str) -> Response:
    data = await _fetch_api(request, f"/v1/vm/{vm_id}/status")
    return _render(request, "status.html", vm_id=vm_id, vm=data)


# ---------------------------------------------------------------------------
# HTMX partials
# ---------------------------------------------------------------------------


@app.post("/partials/price", response_class=HTMLResponse)
async def partial_price(
    size: Annotated[str, Form()] = "sm",
    duration: Annotated[str, Form()] = "30",
) -> HTMLResponse:
    tier = VM_TIERS.get(size, VM_TIERS["sm"])
    daily = tier["price"]
    days = max(1, min(365, int(duration) if duration.isdigit() else 30))
    total = daily * days
    return HTMLResponse(
        f'<span class="price-amount">${total:.2f}</span>'
        f'<span class="price-detail">{days} days &times; ${daily:.2f}/day</span>'
    )


@app.get("/order/status/{vm_id}/partial", response_class=HTMLResponse)
async def partial_status(request: Request, vm_id: str) -> Response:
    data = await _fetch_api(request, f"/v1/vm/{vm_id}/status")
    return _render(request, "_status_partial.html", vm_id=vm_id, vm=data)


# ---------------------------------------------------------------------------
# SEO surface — robots.txt, sitemap.xml, llms.txt
# ---------------------------------------------------------------------------


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return ROBOTS_TXT


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    return Response(content=render_sitemap_xml(app), media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request) -> str:
    """LLMS_TXT is built from the live PaymentConfig — never hardcoded.

    Reads /v1/payments/networks so we only ever advertise chains that are
    actually default-enabled (or feature-flagged on) in the backend. If the
    backend is unreachable, fall back to a chains-unknown variant — better
    than lying about a chain that isn't shipped.
    """
    networks_data = await _fetch_api(request, "/v1/payments/networks")
    networks = networks_data.get("networks", []) if networks_data else None
    return build_llms_txt(networks=networks)


# ---------------------------------------------------------------------------
# API proxy — browser talks to same origin, we forward to the backend API
# ---------------------------------------------------------------------------


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_api(request: Request, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.http
    api_path = path[3:] if path.startswith("v1/") else path

    forward_headers: dict[str, str] = {}
    for key in request.headers:
        lower = key.lower()
        if lower in (
            "content-type", "accept",
            "x-payment", "x-dev-bypass", "payment-signature",
            # Block A0: Bearer auth for hyr_vm_ management tokens (and
            # future hyr_sk_ account API keys in Block D).
            "authorization",
            # Block A1: forward session cookies so the backend can resolve
            # the current account on /me/* calls coming through the browser.
            "cookie",
        ):
            forward_headers[key] = request.headers[key]

    body = await request.body()

    try:
        resp = await client.request(
            method=request.method,
            url=f"/v1/{api_path}",
            headers=forward_headers,
            content=body if body else None,
        )
    except httpx.HTTPError as exc:
        return Response(
            content=f'{{"error": "API unreachable: {exc}"}}',
            status_code=502,
            media_type="application/json",
        )

    # Build the proxied response. Starlette's Response constructor takes a
    # dict for headers, which collapses duplicates — so we put the standard
    # headers there and then append any Set-Cookie values via raw_headers,
    # which preserves multiplicity (a session POST can set both hyr_sess and
    # hyr_csrf in one response).
    skip = ("transfer-encoding", "content-encoding", "content-length", "set-cookie")
    base_headers: dict[str, str] = {
        k: v for k, v in resp.headers.items() if k.lower() not in skip
    }
    proxied = Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=base_headers,
    )
    for k, v in resp.headers.multi_items():
        if k.lower() == "set-cookie":
            proxied.raw_headers.append((b"set-cookie", v.encode("latin-1")))
    return proxied


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    import uvicorn

    uvicorn.run(
        "hyrule_web.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
