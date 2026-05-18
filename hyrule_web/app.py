"""Hyrule Cloud web frontend — lightweight, server-rendered, Tor-friendly."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import DEFAULT_OS_TEMPLATES, VM_TIERS, settings
from .seo import LLMS_TXT, ROBOTS_TXT, render_sitemap_xml

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
    """Render a template with common context variables."""
    ctx: dict[str, Any] = {"vm_tiers": VM_TIERS, **kwargs}
    return templates.TemplateResponse(request, name, ctx)


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


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> Response:
    runtime = {
        "api_ms": 24, "queue": 3, "avg_provision": 58, "live_vms": 1284
    }
    return _render(request, "index.html", runtime=runtime)

@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request) -> Response:
    return _render(request, "dashboard.html")



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
        # agent or curl would use.
        management_url = (
            f"{scheme}://cloud.{host.removeprefix('www.')}/v1/vm/{vm_id}?token={token}"
        )
    return _render(
        request, "status.html",
        vm_id=vm_id, vm=data, management_url=management_url,
    )


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


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    return Response(content=render_sitemap_xml(app), media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms() -> str:
    return LLMS_TXT


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

    resp_headers: dict[str, str] = {}
    for key, value in resp.headers.items():
        if key.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
            resp_headers[key] = value

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
    )


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
