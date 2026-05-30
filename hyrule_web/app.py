"""Hyrule Cloud web frontend — lightweight, server-rendered, Tor-friendly."""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

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


# ---------------------------------------------------------------------------
# Vite asset manifest (issue #14)
#
# The frontend is built by Vite into static/dist/ with a manifest mapping entry
# names to hashed filenames. `vite_asset()` renders the <script>/<link> tags for
# an entry so templates don't hardcode hashed names. The built bundle is
# committed and shipped by the Ansible deploy (no Node on the web host).
# ---------------------------------------------------------------------------

_DIST_DIR = BASE_DIR / "static" / "dist"
_VITE_MANIFEST_PATH = _DIST_DIR / ".vite" / "manifest.json"
# Friendly entry aliases → manifest keys (the Vite rollup input paths).
_VITE_ENTRIES = {
    "main": "frontend/src/main.ts",
    "payment": "frontend/src/payment.ts",
}


@lru_cache(maxsize=1)
def _vite_manifest() -> dict[str, Any]:
    try:
        data: Any = json.loads(_VITE_MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        # No build present (e.g. fresh checkout before `npm run build`): render
        # nothing rather than 500. CI's drift guard ensures dist/ is committed.
        log.warning("vite_manifest_missing", path=str(_VITE_MANIFEST_PATH))
        return {}
    return data if isinstance(data, dict) else {}


def vite_asset(entry: str) -> Markup:
    """Render the module <script> (+ its CSS and preloads) for a Vite entry.

    `entry` is a friendly alias (see `_VITE_ENTRIES`) or a raw manifest key.
    In dev (settings.debug + settings.vite_dev_server) it points at the Vite dev
    server for HMR instead of the built bundle.
    """
    key = _VITE_ENTRIES.get(entry, entry)

    if settings.debug and settings.vite_dev_server:
        base = settings.vite_dev_server.rstrip("/")
        return Markup(
            f'<script type="module" src="{base}/@vite/client"></script>\n'
            f'<script type="module" src="{base}/{key}"></script>'
        )

    manifest = _vite_manifest()
    chunk = manifest.get(key)
    if not chunk:
        return Markup("")
    tags: list[str] = []
    for css in chunk.get("css", []):
        tags.append(f'<link rel="stylesheet" href="/static/dist/{css}">')
    for imp in chunk.get("imports", []):
        dep = manifest.get(imp)
        if dep and dep.get("file"):
            tags.append(f'<link rel="modulepreload" href="/static/dist/{dep["file"]}">')
    tags.append(f'<script type="module" src="/static/dist/{chunk["file"]}"></script>')
    return Markup("\n".join(tags))


templates.env.globals["vite_asset"] = vite_asset


# Block B: frontend-side 15s cache so per-page renders never hit the backend
# in a hot loop. The backend already caches /v1/stats/runtime at 20s; we stack
# a smaller TTL here so the header pill stays responsive even if the backend
# is briefly unavailable (the previous value lingers as a stale-on-error
# fallback).
_RUNTIME_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_RUNTIME_TTL_SECONDS = 15
# Block H (Wave 5/6): fleet stats for /transparency. Longer TTL — these move
# slowly and the backend already caches /v1/stats/network for 30s.
_NETWORK_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_NETWORK_TTL_SECONDS = 30
# Block G (Wave 6): payment-networks catalog for /faq + /llms.txt. Crawlers hit
# llms.txt frequently — cache so we don't re-query the backend chain list per
# request.
_CATALOG_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_CATALOG_TTL_SECONDS = 60


def _render(request: Request, name: str, **kwargs: Any) -> Response:
    """Render a template with common context variables.

    Injects the most recent `runtime` value (Block B) into every template so
    `base.html`'s header pill can render without each handler having to fetch
    /v1/stats/runtime itself. When the runtime fetch fails the value is None
    and the template falls back to the `api · —` placeholder.
    """
    ctx: dict[str, Any] = {"vm_tiers": VM_TIERS, **kwargs}
    if "runtime" not in ctx:
        ctx["runtime"] = _RUNTIME_CACHE.get("value")
    return templates.TemplateResponse(request, name, ctx)


async def _refresh_runtime(request: Request) -> dict[str, Any] | None:
    """Pull /v1/stats/runtime, cache for 15s. Stale-on-error: if the fetch
    fails we serve the last good value rather than punching a hole through
    to None — better UX than a flicker between a real number and a dash."""
    now = time.time()
    cached: dict[str, Any] | None = _RUNTIME_CACHE.get("value")
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
    cached: dict[str, Any] | None = _NETWORK_CACHE.get("value")
    if cached is not None and now < float(_NETWORK_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/stats/network")
    if data is not None:
        _NETWORK_CACHE["value"] = data
        _NETWORK_CACHE["expires_at"] = now + _NETWORK_TTL_SECONDS
        return data
    return cached


async def _refresh_networks(request: Request) -> dict[str, Any] | None:
    """Pull /v1/payments/networks, cache 60s, stale-on-error. Shared by /faq and
    /llms.txt so crawlers hitting llms.txt don't re-query the chain list each time."""
    now = time.time()
    cached: dict[str, Any] | None = _CATALOG_CACHE.get("value")
    if cached is not None and now < float(_CATALOG_CACHE["expires_at"]):
        return cached
    data = await _fetch_api(request, "/v1/payments/networks")
    if data is not None:
        _CATALOG_CACHE["value"] = data
        _CATALOG_CACHE["expires_at"] = now + _CATALOG_TTL_SECONDS
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
    json: dict[str, Any] | None = None,
    forward_cookie: bool = True,
) -> httpx.Response | None:
    """Issue a backend call from a server-side handler, optionally forwarding
    the browser's session cookie so account-scoped endpoints work.

    Returns the raw httpx.Response (not just parsed JSON) so the caller can
    inspect status codes and pass Set-Cookie back via _copy_set_cookie."""
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
    register sessions reach the browser. Preserves multiple Set-Cookie values
    via raw_headers (a single Response.headers dict would collapse duplicates)."""
    for k, v in backend_resp.headers.multi_items():
        if k.lower() == "set-cookie":
            response.raw_headers.append((b"set-cookie", v.encode("latin-1")))


def _require_auth_ui() -> None:
    """Wave 2 kill-switch — flip HYRULE_WEB_ENABLE_AUTH_UI=false to dark the
    /signup /login /recover /dashboard surface without redeploying."""
    if not settings.enable_auth_ui:
        raise HTTPException(status_code=404)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> Response:
    """Block B: homepage pulls live runtime stats. Replaces the hardcoded
    `api · 24ms / queue 3 / 58s / 1284 VMs` block with values from the
    backend, cached for 15s and stale-on-error."""
    runtime = await _refresh_runtime(request)
    return _render(request, "index.html", runtime=runtime)


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
    # Block A0: status page calls the sanitized public endpoint. The
    # legacy /v1/vm/{id} is now management-gated and would 404 here.
    data = await _fetch_api(request, f"/v1/vm/{vm_id}/status")
    # If the URL carries ?token=hyr_vm_..., the user just landed from a
    # fresh anon order. Surface the management URL banner exactly once.
    token = request.query_params.get("token")
    management_url = None
    if token and token.startswith("hyr_vm_"):
        scheme = request.url.scheme
        host = request.headers.get("host", "")
        # Routed via Caddy on proxy → api:8402. The cloud subdomain serves
        # the api directly so the management URL is the canonical form an
        # agent or curl would use. Token is URL-encoded — current tokens are
        # `hyr_vm_<32 base62>` (no reserved chars), but encoding now keeps the
        # URL well-formed if the token shape ever picks up `&`, `?`, or `=`.
        management_url = (
            f"{scheme}://cloud.{host.removeprefix('www.')}/v1/vm/{vm_id}"
            f"?token={urllib.parse.quote(token, safe='')}"
        )
    return _render(
        request, "status.html",
        vm_id=vm_id, vm=data, management_url=management_url,
    )


# ---------------------------------------------------------------------------
# Block A1 — auth pages (signup / login / logout / recover / dashboard)
# ---------------------------------------------------------------------------


@app.get("/signup", response_class=HTMLResponse)
async def page_signup(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "signup.html", error=None)


@app.post("/signup", response_class=HTMLResponse)
async def do_signup(
    request: Request,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    """Mirror the backend's password rules (min 12 chars) before round-tripping
    so we can return an inline error without burning the per-IP signup quota
    on /v1/auth/register."""
    _require_auth_ui()
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
        return _render(
            request, "signup.html",
            error="Too many signups from your network; try later.",
        )
    if backend.status_code != 200:
        return _render(request, "signup.html", error="Signup failed. Try again.")

    body = backend.json()
    # signup_success is the *only* place the recovery code is ever shown.
    # Render via _render so the Set-Cookie from /v1/auth/register can be
    # attached to the same response object (browser is now logged in).
    rendered = _render(
        request, "signup_success.html",
        account_id=body["account_id"],
        recovery_code=body["recovery_code"],
    )
    _copy_set_cookie(backend, rendered)
    return rendered


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "login.html", error=None)


@app.post("/login", response_class=HTMLResponse)
async def do_login(
    request: Request,
    account_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
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
    _require_auth_ui()
    backend = await _api_request(request, "/v1/auth/logout", method="POST")
    redirect = RedirectResponse("/", status_code=303)
    # Even if the backend call fails (e.g. session already expired) the
    # /v1/auth/logout endpoint sets an expiring cookie; forward it so the
    # browser drops the stale hyr_sess cookie.
    if backend is not None:
        _copy_set_cookie(backend, redirect)
    return redirect


@app.get("/recover", response_class=HTMLResponse)
async def page_recover(request: Request) -> Response:
    _require_auth_ui()
    return _render(request, "recover.html", error=None, success=None)


@app.post("/recover", response_class=HTMLResponse)
async def do_recover(
    request: Request,
    account_id: Annotated[str, Form()],
    recovery_code: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    if new_password != new_password_confirm:
        return _render(request, "recover.html", error="Passwords do not match.", success=None)
    if len(new_password) < 12:
        return _render(
            request, "recover.html",
            error="Password must be at least 12 characters.", success=None,
        )

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
        return _render(
            request, "recover.html",
            error="Too many recovery attempts; try later.", success=None,
        )
    if backend.status_code != 200:
        return _render(
            request, "recover.html",
            error="Invalid recovery code or account ID.", success=None,
        )

    body = backend.json()
    return _render(
        request, "recover.html",
        error=None,
        success={
            "account_id": body["account_id"],
            "new_recovery_code": body["new_recovery_code"],
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request) -> Response:
    """Renders the signed-in dashboard. /v1/me 401 → redirect to /login. Any
    other backend failure renders the shell with an error banner so the user
    can still log out / claim a VM without a forced loop."""
    _require_auth_ui()
    me_resp = await _api_request(request, "/v1/me")
    if me_resp is None or me_resp.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if me_resp.status_code != 200:
        return _render(
            request, "dashboard.html",
            me=None, vms=[], error="Could not load account info.",
        )
    me = me_resp.json()
    vms_resp = await _api_request(request, "/v1/me/vms")
    vms = vms_resp.json().get("vms", []) if (vms_resp and vms_resp.status_code == 200) else []
    return _render(request, "dashboard.html", me=me, vms=vms, error=None)


# Block A1: dashboard mutation handlers — all server-side, all redirect back
# to /dashboard on completion so the browser's history stays clean and the
# user always lands on a fresh table read.


@app.post("/dashboard/vms/{vm_id}/reboot")
async def dash_reboot(request: Request, vm_id: str) -> Response:
    _require_auth_ui()
    await _api_request(request, f"/v1/vm/{vm_id}/reboot", method="POST")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/vms/{vm_id}/destroy")
async def dash_destroy(request: Request, vm_id: str) -> Response:
    _require_auth_ui()
    await _api_request(request, f"/v1/vm/{vm_id}", method="DELETE")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/claim")
async def dash_claim(
    request: Request,
    vm_id: Annotated[str, Form()],
    token: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    await _api_request(
        request, f"/v1/me/vms/{vm_id.strip()}/claim", method="POST",
        json={"token": token.strip()},
    )
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/password")
async def dash_change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    await _api_request(
        request, "/v1/me/password", method="POST",
        json={"current_password": current_password, "new_password": new_password},
    )
    return RedirectResponse("/dashboard", status_code=303)


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
    # Block A0: same sanitized public endpoint as the full page.
    data = await _fetch_api(request, f"/v1/vm/{vm_id}/status")
    return _render(request, "_status_partial.html", vm_id=vm_id, vm=data)


# ---------------------------------------------------------------------------
# SEO surface — robots.txt, sitemap.xml, llms.txt
# ---------------------------------------------------------------------------


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return ROBOTS_TXT


@app.get("/transparency", response_class=HTMLResponse)
async def page_transparency(request: Request) -> Response:
    """Infra-truth page: ASN, hosts, peering, jurisdiction (Block G). Live fleet
    numbers (BGP peers, NAT64 sessions, IPv6 prefixes) come from
    /v1/stats/network; falls back to the static shape when it's unreachable."""
    await _refresh_runtime(request)
    network = await _refresh_network(request)
    return _render(request, "transparency.html", network=network)


@app.get("/faq", response_class=HTMLResponse)
async def page_faq(request: Request) -> Response:
    """FAQ + FAQPage JSON-LD (Block G). Only mentions live payment methods —
    the chain list comes from /v1/payments/networks, never hardcoded."""
    await _refresh_runtime(request)
    networks = await _refresh_networks(request) or {"networks": []}
    return _render(request, "faq.html", networks=networks.get("networks", []))


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    return Response(content=render_sitemap_xml(app), media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request) -> str:
    # Build from live backend state so the doc never advertises a disabled
    # chain (feedback_verified_payment_chains). None → "ask the API" note.
    networks_resp = await _refresh_networks(request)
    networks = networks_resp.get("networks") if networks_resp else None
    return build_llms_txt(networks)


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
            # the current account on /me/* calls coming from the browser.
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
    # which preserves multiplicity (login can set hyr_sess + hyr_csrf in one).
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
