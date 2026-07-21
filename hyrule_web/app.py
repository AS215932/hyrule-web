"""Hyrule Cloud web frontend — lightweight, server-rendered, Tor-friendly."""

from __future__ import annotations

import json
import logging
import re
import secrets
import sys
import time
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import httpx
import structlog
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .catalog import browser_catalog, catalog_resources, normalize_openapi
from .config import DEFAULT_OS_TEMPLATES, VM_CUSTOMIZATION, VM_TIERS, settings
from .journeys import CAMPAIGN_LAUNCH, JOURNEYS, JOURNEYS_BY_SLUG
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

DOMAIN_RECORD_TYPES = frozenset(
    {"A", "AAAA", "CNAME", "MX", "TXT", "CAA", "SRV", "NS", "TLSA", "SVCB", "HTTPS"}
)
DNS_RECORD_LABEL_RE = re.compile(r"^(?:\*|[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?)$")
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _safe_next_path(value: str | None, *, fallback: str = "/dashboard") -> str:
    """Return a same-origin absolute path suitable for an auth redirect."""
    if not value or "\\" in value or any(ord(char) < 32 for char in value):
        return fallback
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return fallback
    if parsed.path.startswith("//"):
        return fallback
    return urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=30,
    )
    yield
    await app.state.http.aclose()


app = FastAPI(title="Hyrule Cloud", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def response_policy(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Apply origin isolation plus explicit caching for dynamic/static assets."""
    response = await call_next(request)
    path = request.url.path
    response.headers.setdefault("Origin-Agent-Cluster", "?1")
    response.headers.setdefault("Permissions-Policy", "tools=(self)")
    response.headers.setdefault("Vary", "Accept-Encoding")
    if path.startswith("/static/dist/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400, must-revalidate"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif response.headers.get("content-type", "").startswith("text/html") or path in {
        "/llms.txt",
        "/sitemap.xml",
    }:
        response.headers["Cache-Control"] = "no-cache"
    return response


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
    "styles": "frontend/src/styles/app.css",
    "payment": "frontend/src/payment.ts",
    "status": "frontend/src/status.ts",
    "secrets": "frontend/src/secret-copy.ts",
    "domain": "frontend/src/domain.ts",
    "wallet_auth": "frontend/src/wallet-auth.ts",
    "toolbox": "frontend/src/toolbox.ts",
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


def vite_styles(entry: str = "styles") -> Markup:
    """Render a Vite CSS entry without adding an executable module script."""
    key = _VITE_ENTRIES.get(entry, entry)
    if settings.debug and settings.vite_dev_server:
        base = settings.vite_dev_server.rstrip("/")
        return Markup(f'<link rel="stylesheet" href="{base}/{key}">')

    chunk = _vite_manifest().get(key)
    if not chunk:
        return Markup("")
    files: list[str] = []
    output = chunk.get("file")
    if isinstance(output, str) and output.endswith(".css"):
        files.append(output)
    files.extend(css for css in chunk.get("css", []) if isinstance(css, str))
    return Markup(
        "\n".join(
            f'<link rel="stylesheet" href="/static/dist/{path}">' for path in dict.fromkeys(files)
        )
    )


templates.env.globals["vite_styles"] = vite_styles


# Block B: frontend-side 15s cache for the homepage runtime panel. The backend
# already caches /v1/stats/runtime at 20s; the previous value lingers as a
# stale-on-error fallback when the backend is briefly unavailable.
_RUNTIME_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_RUNTIME_TTL_SECONDS = 15
# Customer-facing aggregate health from hyrule-cloud's curated /v1/status
# contract. The header is server-rendered, so every informational page remains
# useful with JavaScript disabled.
_SERVICE_STATUS_CACHE: dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
    "successful_at": 0.0,
}
_SERVICE_STATUS_TTL_SECONDS = 15
_SERVICE_STATUS_STALE_SECONDS = 120
# Block G (Wave 6): payment-networks catalog for /faq + /llms.txt. Crawlers hit
# llms.txt frequently — cache so we don't re-query the backend chain list per
# request.
_CATALOG_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_CATALOG_TTL_SECONDS = 60
# Overhaul: live VM product catalog (GET /v1/products/vms) for the tier grids.
# The hardcoded config.VM_TIERS once drifted from what the API provisions
# (512 MB vs 1 GB xs) — pages render the live catalog, config is fallback-only.
_PRODUCTS_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_PRODUCTS_TTL_SECONDS = 300
# Enabled-only x402 OpenAPI catalog. A stale snapshot may be displayed with a
# warning, but only a fresh snapshot can enable toolbox execution.
_TOOL_CATALOG_CACHE: dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
    "successful_at": 0.0,
}
_TOOL_CATALOG_TTL_SECONDS = 300
# Overhaul: /v1/pricing (proxy route prices + currency/network) for /services.
_PRICING_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}
_PRICING_TTL_SECONDS = 300
# Agent Mail is launch-gated. A stale success may be displayed as last-known
# copy, but it can never keep the public availability badge green.
_MAIL_PRODUCTS_CACHE: dict[str, Any] = {
    "value": None,
    "expires_at": 0.0,
    "retry_at": 0.0,
}
_MAIL_PRODUCTS_TTL_SECONDS = 60
_MAIL_PRODUCTS_NEGATIVE_TTL_SECONDS = 5

_SERVICE_COMPONENTS = (
    ("api_checkout", "API & checkout", "Purchasing and management API"),
    ("compute", "Compute", "VM provisioning and reachability"),
    ("intelligence", "Network intelligence", "Network diagnostics endpoints"),
    ("domains_dns", "Domains & DNS", "Registration and authoritative DNS"),
    ("network_proxy", "Network proxy", "Direct, Tor, I2P, and Yggdrasil egress"),
)


def _unknown_service_status(
    message: str = "Current service health could not be confirmed.",
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "checked_at": None,
        "stale": True,
        "feed_unavailable": True,
        "components": [
            {"id": key, "name": name, "status": "unknown", "message": message}
            for key, name, _description in _SERVICE_COMPONENTS
        ],
        "incidents": [],
    }


def _service_status_view(status: dict[str, Any] | None) -> dict[str, Any]:
    status = status or _unknown_service_status()
    state = status.get("status", "unknown")
    raw_components = status.get("components")
    components: list[Any] = raw_components if isinstance(raw_components, list) else []
    affected = [
        component
        for component in components
        if isinstance(component, dict) and component.get("status") in {"degraded", "outage"}
    ]
    # An unknown response is not a last-known snapshot. Calling it merely
    # "delayed" implies that the component states below are trustworthy when
    # the monitoring feed may never have returned a usable state at all.
    if state == "unknown":
        return {"label": "Status unavailable", "tone": "unknown", "affected": []}
    if status.get("stale"):
        return {"label": "Status feed delayed", "tone": "degraded", "affected": affected}
    if state == "outage":
        return {"label": "Major outage", "tone": "outage", "affected": affected}
    if state == "degraded":
        suffix = ""
        if len(affected) == 1:
            suffix = f" · {affected[0].get('name', 'service')}"
        elif affected:
            suffix = f" · {len(affected)} services"
        return {"label": f"Degraded{suffix}", "tone": "degraded", "affected": affected}
    if state == "operational":
        return {"label": "Operational", "tone": "operational", "affected": []}
    return {"label": "Status unavailable", "tone": "unknown", "affected": []}


async def _refresh_service_status(request: Request) -> dict[str, Any]:
    now = time.time()
    cached = _SERVICE_STATUS_CACHE.get("value")
    if isinstance(cached, dict) and now < float(_SERVICE_STATUS_CACHE["expires_at"]):
        successful_at = float(_SERVICE_STATUS_CACHE.get("successful_at", 0.0))
        stale_too_old = (
            cached.get("stale")
            and successful_at > 0
            and now - successful_at > _SERVICE_STATUS_STALE_SECONDS
        )
        if stale_too_old:
            unknown = _unknown_service_status("The live status feed is unavailable.")
            _SERVICE_STATUS_CACHE.update(
                value=unknown,
                expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
                successful_at=0.0,
            )
            return unknown
        return cached

    client: httpx.AsyncClient | None = getattr(request.app.state, "http", None)
    data: dict[str, Any] | None = None
    if client is not None:
        try:
            response = await client.get("/v1/status", timeout=3.0)
            candidate = response.json() if response.status_code == 200 else None
            if isinstance(candidate, dict) and candidate.get("status") in {
                "operational",
                "degraded",
                "outage",
                "unknown",
            }:
                data = candidate
        except (httpx.HTTPError, ValueError):
            data = None

    if data is not None:
        _SERVICE_STATUS_CACHE.update(
            value=data,
            expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
            successful_at=now,
        )
        return data

    successful_at = float(_SERVICE_STATUS_CACHE.get("successful_at", 0.0))
    if isinstance(cached, dict) and now - successful_at <= _SERVICE_STATUS_STALE_SECONDS:
        stale = {**cached, "stale": True, "feed_unavailable": True}
        _SERVICE_STATUS_CACHE.update(value=stale, expires_at=now + _SERVICE_STATUS_TTL_SECONDS)
        return stale
    unknown = _unknown_service_status("The live status feed is unavailable.")
    _SERVICE_STATUS_CACHE.update(
        value=unknown,
        expires_at=now + _SERVICE_STATUS_TTL_SECONDS,
        successful_at=0.0,
    )
    return unknown


@app.middleware("http")
async def refresh_service_status_for_pages(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    path = request.url.path
    excluded = (
        path.startswith("/api/")
        or path.startswith("/static/")
        or path
        in {
            "/favicon.ico",
            "/apple-touch-icon.png",
            "/apple-touch-icon-precomposed.png",
            "/robots.txt",
            "/sitemap.xml",
            "/llms.txt",
        }
    )
    if request.method == "GET" and not excluded:
        await _refresh_service_status(request)
    return await call_next(request)


def _copy(*parts: str) -> str:
    return " ".join(parts)


_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)


def _normalise_custom_domain(value: str) -> str | None:
    domain = value.strip().lower().rstrip(".")
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2:
        return None
    if any(not _DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        return None
    return domain


LEGAL_PAGES: dict[str, dict[str, Any]] = {
    "terms": {
        "title": "Terms",
        "description": "Terms for Hyrule Cloud compute, domain, DNS, and Agent Mail services.",
        "updated": "2026-07-19",
        "sections": [
            (
                "Service",
                [
                    _copy(
                        "Hyrule Cloud sells prepaid virtual machines on AS215932.",
                        "Orders include root SSH access, IPv6 connectivity, NAT64/DNS64",
                        "egress, and an automatic deploy.hyrule.host subdomain.",
                    ),
                    _copy(
                        "Runtime is prepaid for 1 to 365 days. Expired VMs may be",
                        "suspended or destroyed after the published grace period.",
                    ),
                ],
            ),
            (
                "Customer Responsibilities",
                [
                    _copy(
                        "You are responsible for activity from your VM, your SSH key,",
                        "and any management token or account credentials.",
                    ),
                    _copy(
                        "Do not use the service for malware command and control,",
                        "phishing, credential theft, DDoS, spam, CSAM, terrorism,",
                        "sanctions evasion, or activity that violates applicable law.",
                    ),
                ],
            ),
            (
                "Enforcement",
                [
                    _copy(
                        "We may suspend or destroy VMs after a precise abuse report,",
                        "credible security signal, court order, or law-enforcement request.",
                    ),
                    _copy(
                        "Where practical, we notify the customer and preserve an appeal",
                        "path. Some urgent safety or infrastructure cases require",
                        "immediate action.",
                    ),
                ],
            ),
            (
                "Payments",
                [
                    _copy(
                        "Crypto is accepted only as payment for hosting. Hyrule Cloud",
                        "does not custody, exchange, broker, transmit, or administer",
                        "crypto-assets for customers.",
                    ),
                    "Refunds and credits are handled manually and may require a support request.",
                ],
            ),
            (
                "Domain Registration And Renewal",
                [
                    _copy(
                        "Hyrule is the legal registrant of domains bought through the service.",
                        "The customer receives the exclusive contractual right to use the domain,",
                        "manage its DNS, renew it while eligible, and transfer it to",
                        "another registrar.",
                    ),
                    _copy(
                        "Registration and renewal are separate prepaid transactions. Registrar",
                        "auto-renew is disabled; you must purchase a renewal before expiry.",
                        "Availability and provider cost are checked again after",
                        "payment settlement.",
                    ),
                    _copy(
                        "If registration cannot complete after payment, the order becomes a manual",
                        "refund obligation. Crypto refunds are not automatic and require a valid",
                        "refund address for Bitcoin or Monero payments.",
                    ),
                ],
            ),
            (
                "Agent Mail",
                [
                    _copy(
                        "Agent Mail is an API-only conversational email service. It does not",
                        "provide public SMTP submission, IMAP, POP, or webmail. Each outbound",
                        "message has one recipient; CC, BCC, outbound attachments, marketing,",
                        "and bulk use are prohibited.",
                    ),
                    _copy(
                        "Activation lasts 30 days and does not auto-renew. Outbound access",
                        "stops at expiry. Inbound delivery and reads remain available for a",
                        "seven-day grace period, after which the mailbox and Agent Mail-owned",
                        "DNS records are deleted. A purchased domain remains registered.",
                    ),
                    _copy(
                        "The launch limits are five new recipients and twenty outbound messages",
                        "per mailbox per UTC day. Complaints, malware signals, or material bounce",
                        "rates may suspend outbound access immediately. Local acceptance does not",
                        "guarantee remote delivery or inbox placement.",
                    ),
                ],
            ),
        ],
    },
    "privacy": {
        "title": "Privacy",
        "description": "Privacy details for Hyrule Cloud orders.",
        "updated": "2026-07-19",
        "sections": [
            (
                "Ordering Model",
                [
                    _copy(
                        "Hyrule Cloud uses a no-KYC ordering model and does not",
                        "require identity verification for hosting orders.",
                    ),
                    _copy(
                        "Anonymous checkout returns a one-time management token.",
                        "Account signup uses a random handle and a password you set.",
                    ),
                ],
            ),
            (
                "Data We Store",
                [
                    _copy(
                        "VM configuration, SSH public key, generated VM identifiers,",
                        "hostname, timestamps, payment status, and expiry state.",
                    ),
                    _copy(
                        "For domains we store the requested name, registrar status, DNS records,",
                        "renewal and transfer events, and the account or wallet that controls it.",
                        "Hyrule's operator contact is supplied to the registrar as registrant.",
                    ),
                    _copy(
                        "For x402 orders we store payer wallet metadata needed to",
                        "reconcile payment. For abuse rate-limiting we store a sha256",
                        "hash of your IPv6 /64 prefix with a private pepper.",
                    ),
                    _copy(
                        "For Agent Mail we store the mailbox address, encrypted backend",
                        "credential, lifecycle and payment state, recipient/send counters,",
                        "delivery events, webhook configuration, message index, message bodies,",
                        "and inbound attachments needed to provide the service.",
                    ),
                ],
            ),
            (
                "Data We Do Not Inspect",
                [
                    _copy(
                        "We do not run a monitoring agent inside customer VMs and do",
                        "not proactively inspect VM contents.",
                    ),
                    _copy(
                        "Network and host telemetry is used for reliability, abuse",
                        "response, and capacity planning.",
                    ),
                    _copy(
                        "Agent Mail necessarily processes message content and attachments for",
                        "delivery, API retrieval, malware controls, and abuse response. This is",
                        "separate from customer VM contents, which are not proactively inspected.",
                    ),
                ],
            ),
            (
                "Retention",
                [
                    _copy(
                        "Operational records are kept only as long as needed for service",
                        "operation, accounting, abuse handling, and legal obligations.",
                    ),
                    _copy(
                        "Abuse reports may be retained with evidence, action taken,",
                        "customer notice, and appeal result.",
                    ),
                    _copy(
                        "Agent Mail message bodies and attachments use a 30-day rolling",
                        "retention window. After activation expiry they remain readable during",
                        "the seven-day grace period and are then deleted. Payment, security,",
                        "delivery, and abuse records may be retained longer where necessary.",
                    ),
                ],
            ),
        ],
    },
    "abuse": {
        "title": "Abuse",
        "description": "Report abuse involving Hyrule Cloud infrastructure.",
        "updated": "2026-07-19",
        "sections": [
            (
                "Report Channels",
                [
                    _copy(
                        "Send abuse reports, operational issues, and customer support",
                        "requests to support@hyrule.host. Use 'Abuse report' in the",
                        "subject for abuse cases.",
                    ),
                    _copy(
                        "Include a reporter contact, URL or hostname or IP, allegation,",
                        "evidence, timestamp with timezone, and any urgency indicators.",
                    ),
                ],
            ),
            (
                "Immediate Suspension Categories",
                [
                    _copy(
                        "Malware command and control, phishing, credential theft, DDoS,",
                        "spam, CSAM, terrorism, and valid court or law-enforcement orders",
                        "may result in immediate suspension.",
                    ),
                    _copy(
                        "We do not require broad personal data to act on precise,",
                        "technically actionable reports.",
                    ),
                    _copy(
                        "For Agent Mail, a recipient complaint, detected malware, or sustained",
                        "hard-bounce pattern can suspend outbound API access before manual review.",
                        "Reads may remain available unless preserving access would create risk.",
                    ),
                ],
            ),
            (
                "Notice And Appeal",
                [
                    _copy(
                        "When it is safe and practical, we notify the customer through",
                        "their management surface or account and record the action taken.",
                    ),
                    _copy(
                        "Appeals can be sent to support@hyrule.host with the VM ID,",
                        "report reference, and remediation details.",
                    ),
                ],
            ),
            (
                "Queue Fields",
                [
                    _copy(
                        "The abuse queue tracks reporter contact, URL/hostname/IP,",
                        "allegation, evidence, timestamp, action taken, customer notice,",
                        "and appeal/result.",
                    ),
                ],
            ),
        ],
    },
    "legal": {
        "title": "Legal",
        "description": "Legal contact and service posture for Hyrule Cloud.",
        "updated": "2026-07-19",
        "sections": [
            (
                "Operator And Jurisdiction",
                [
                    _copy(
                        "Hyrule Cloud is operated from the Netherlands. Compute currently",
                        "runs at OVH France, with AS215932 network operations in the EU.",
                    ),
                    _copy(
                        "Hyrule Cloud is a hosting/intermediary service. It publishes",
                        "contact points, terms, and a notice/action flow for abuse handling.",
                    ),
                ],
            ),
            (
                "Crypto Payment Posture",
                [
                    _copy(
                        "Crypto payment support is limited to paying for hosting.",
                        "Hyrule Cloud does not provide customer wallets, exchange services,",
                        "brokerage, transmission, or custody.",
                    ),
                    _copy(
                        "New crypto-asset services such as stored balances, custody,",
                        "exchange, or wallet administration require legal review before launch.",
                    ),
                ],
            ),
            (
                "Domains",
                [
                    _copy(
                        "Every VM may receive a deploy.hyrule.host subdomain. For purchased",
                        "domains Hyrule remains the legal registrant and grants the customer",
                        "the contractual rights to use, manage, renew, and transfer the name.",
                    ),
                ],
            ),
            (
                "Agent Mail",
                [
                    _copy(
                        "Agent Mail is operated as a communications hosting service on dedicated",
                        "mail infrastructure separate from Hyrule's corporate email. Public launch",
                        "requires recorded legal, privacy, and abuse-policy approval in",
                        "addition to",
                        "technical readiness and a controlled production canary.",
                    ),
                ],
            ),
            (
                "Authorities",
                [
                    _copy(
                        "Serious life, safety, or criminal reports may be escalated to",
                        "competent authorities as required by applicable law.",
                    ),
                ],
            ),
        ],
    },
}


def _render(request: Request, name: str, *, status_code: int = 200, **kwargs: Any) -> Response:
    """Render a template with common context variables.

    Injects the most recent runtime and customer-safe service-status snapshots.
    Templates stay useful when either backend feed is temporarily unavailable.
    """
    ctx: dict[str, Any] = {
        "vm_tiers": VM_TIERS,
        # Issue #14: public WalletConnect projectId for the base.html meta tag.
        "wc_project_id": settings.walletconnect_project_id,
        "webmcp_origin_trial_token": settings.webmcp_origin_trial_token,
        **kwargs,
    }
    if "runtime" not in ctx:
        ctx["runtime"] = _RUNTIME_CACHE.get("value")
    service_status = _SERVICE_STATUS_CACHE.get("value")
    if not isinstance(service_status, dict):
        service_status = _unknown_service_status()
    ctx["service_status"] = service_status
    ctx["status_view"] = _service_status_view(service_status)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _catalog_networks(catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    networks = catalog.get("networks") if catalog else []
    return (
        [network for network in networks if isinstance(network, dict)]
        if isinstance(networks, list)
        else []
    )


def _catalog_native(catalog: dict[str, Any] | None) -> list[str]:
    native = catalog.get("native") if catalog else []
    return [str(x).upper() for x in native] if isinstance(native, list) else []


def _sane_provision_seconds(value: Any) -> int | None:
    """Sanity-gate the advertised provision time. The backend's rolling
    average can be polluted by stuck/simulated builds (observed: 4720.3s
    while real provisions finish in seconds) — outside a plausible window
    we render the templates' honest "~60s" fallback instead of telemetry
    we don't believe."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < v <= 300:
        return round(v)
    return None


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
        data = {
            **data,
            "avg_provision_seconds": _sane_provision_seconds(data.get("avg_provision_seconds")),
        }
        _RUNTIME_CACHE["value"] = data
        _RUNTIME_CACHE["expires_at"] = now + _RUNTIME_TTL_SECONDS
        return data
    # Hold the last good value past its TTL when the backend is down.
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


async def _refresh_cached(
    request: Request, cache: dict[str, Any], ttl_seconds: int, path: str
) -> dict[str, Any] | None:
    """Generic TTL + stale-on-error fetch for product and pricing catalogs."""
    now = time.time()
    cached: dict[str, Any] | None = cache.get("value")
    if cached is not None and now < float(cache["expires_at"]):
        return cached
    data = await _fetch_api(request, path)
    if data is not None:
        cache["value"] = data
        cache["expires_at"] = now + ttl_seconds
        return data
    return cached


async def _refresh_products(request: Request) -> dict[str, Any] | None:
    return await _refresh_cached(
        request, _PRODUCTS_CACHE, _PRODUCTS_TTL_SECONDS, "/v1/products/vms"
    )


async def _refresh_tool_catalog(request: Request) -> dict[str, Any]:
    """Fetch and normalize enabled OpenAPI operations with fail-closed freshness."""
    now = time.time()
    cached = _TOOL_CATALOG_CACHE.get("value")
    if isinstance(cached, dict) and now < float(_TOOL_CATALOG_CACHE["expires_at"]):
        return {**cached, "status": "live"}

    document = await _fetch_api(request, "/openapi.json")
    if document is not None:
        normalized = normalize_openapi(document)
        tools = normalized.get("tools")
        if isinstance(document.get("paths"), dict) and isinstance(tools, list):
            normalized["fetched_at"] = now
            _TOOL_CATALOG_CACHE["value"] = normalized
            _TOOL_CATALOG_CACHE["expires_at"] = now + _TOOL_CATALOG_TTL_SECONDS
            _TOOL_CATALOG_CACHE["successful_at"] = now
            return {**normalized, "status": "live"}
        log.warning("x402_openapi_invalid")

    if isinstance(cached, dict):
        return {**cached, "status": "stale"}
    return {"status": "unavailable", "fetched_at": None, "tools": []}


async def _refresh_pricing(request: Request) -> dict[str, Any] | None:
    return await _refresh_cached(request, _PRICING_CACHE, _PRICING_TTL_SECONDS, "/v1/pricing")


def _mail_catalog_available(catalog: dict[str, Any]) -> bool:
    products = catalog.get("products")
    return (
        catalog.get("available") is True
        and isinstance(products, list)
        and any(
            isinstance(product, dict) and product.get("available") is True for product in products
        )
    )


def _available_mail_product(catalog: dict[str, Any], product_id: str) -> dict[str, Any] | None:
    products = catalog.get("products")
    if not isinstance(products, list):
        return None
    return next(
        (
            product
            for product in products
            if isinstance(product, dict)
            and product.get("id") == product_id
            and product.get("available") is True
        ),
        None,
    )


async def _refresh_mail_products(request: Request) -> dict[str, Any]:
    now = time.time()
    cached = _MAIL_PRODUCTS_CACHE.get("value")
    if isinstance(cached, dict) and now < float(_MAIL_PRODUCTS_CACHE["expires_at"]):
        return {
            **cached,
            "available": _mail_catalog_available(cached),
            "catalog_status": "live",
        }
    if now < float(_MAIL_PRODUCTS_CACHE.get("retry_at", 0.0)):
        if isinstance(cached, dict):
            return {**cached, "available": False, "catalog_status": "stale"}
        return {
            "available": False,
            "products": [],
            "terms_version": None,
            "catalog_status": "unavailable",
        }
    data = await _fetch_api(request, "/v1/mail/products")
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        normalized = {**data, "available": _mail_catalog_available(data)}
        _MAIL_PRODUCTS_CACHE.update(
            value=normalized,
            expires_at=now + _MAIL_PRODUCTS_TTL_SECONDS,
            retry_at=0.0,
        )
        return {**normalized, "catalog_status": "live"}
    _MAIL_PRODUCTS_CACHE["retry_at"] = now + _MAIL_PRODUCTS_NEGATIVE_TTL_SECONDS
    if isinstance(cached, dict):
        return {**cached, "available": False, "catalog_status": "stale"}
    return {
        "available": False,
        "products": [],
        "terms_version": None,
        "catalog_status": "unavailable",
    }


def _live_vm_tiers(products: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map GET /v1/products/vms onto the template tier shape. Malformed rows
    are skipped (pr-agent #32: one bad row must not discard the whole live
    catalog); the static config mirror is the fallback only when nothing
    valid parses — the API is the source of truth for what actually gets
    provisioned."""
    rows = (products or {}).get("products")
    if not isinstance(rows, list):
        return VM_TIERS
    tiers: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            tiers[str(row["size"])] = {
                "name": str(row["name"]),
                "vcpu": int(row["vcpu"]),
                "ram_mb": int(row["ram_mb"]),
                "disk_gb": int(row["disk_gb"]),
                "price": float(row["price_usd_day"]),
            }
        except (KeyError, TypeError, ValueError):
            log.warn("products_row_malformed", row=str(row)[:200])
            continue
    return tiers or VM_TIERS


def _live_vm_customization(products: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return a validated order-control contract, falling back fail-closed."""
    value = (products or {}).get("customization")
    if not isinstance(value, dict):
        return VM_CUSTOMIZATION
    try:
        contract: dict[str, dict[str, Any]] = {
            "minimum": {key: int(value["minimum"][key]) for key in ("vcpu", "ram_mb", "disk_gb")},
            "maximum": {key: int(value["maximum"][key]) for key in ("vcpu", "ram_mb", "disk_gb")},
            "increments": {
                key: int(value["increments"][key]) for key in ("vcpu", "ram_mb", "disk_gb")
            },
            "addon_prices": {
                key: str(value["addon_prices"][key])
                for key in ("vcpu_usd_day", "ram_gb_usd_day", "disk_10gb_usd_day")
            },
        }
        for key in ("vcpu", "ram_mb", "disk_gb"):
            minimum = contract["minimum"][key]
            maximum = contract["maximum"][key]
            increment = contract["increments"][key]
            if (
                minimum <= 0
                or maximum < minimum
                or increment <= 0
                or (maximum - minimum) % increment
                or (maximum - minimum) // increment > 256
            ):
                raise ValueError(f"invalid {key} customization range")
        prices = [Decimal(price) for price in contract["addon_prices"].values()]
        if any(not price.is_finite() or price < 0 for price in prices):
            raise ValueError("invalid VM add-on price")
        return contract
    except (InvalidOperation, KeyError, TypeError, ValueError):
        log.warning("products_customization_malformed")
        return VM_CUSTOMIZATION


def _proxy_prices(pricing: dict[str, Any] | None) -> dict[str, str]:
    """Per-route proxy prices from GET /v1/pricing; unavailable means hidden."""
    prices = (pricing or {}).get("proxy_prices")
    if isinstance(prices, dict) and prices:
        return {str(k): str(v) for k, v in prices.items()}
    return {}


async def _fetch_api(request: Request, path: str) -> dict[str, Any] | None:
    """GET a JSON endpoint from the backend API, return parsed dict or None."""
    try:
        resp = await request.app.state.http.get(path)
        if resp.status_code == 200:
            data: Any = resp.json()
            if isinstance(data, dict):
                return data
            log.warn("api_invalid_shape", path=path, shape=type(data).__name__)
            return None
        log.warn("api_non_200", path=path, status=resp.status_code)
    except (httpx.HTTPError, ValueError) as exc:
        log.error(
            "api_fetch_failed",
            path=path,
            error={"type": type(exc).__name__, "message": str(exc)},
        )
    return None


async def _fetch_vm_status(request: Request, vm_id: str) -> dict[str, Any] | None:
    """Fetch the launch-proof status for a single VM."""
    return await _fetch_api(request, f"/v1/vm/{vm_id}/status")


async def _api_request(
    request: Request,
    path: str,
    *,
    method: str = "GET",
    json: dict[str, Any] | None = None,
    forward_cookie: bool = True,
    extra_headers: dict[str, str] | None = None,
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
    if extra_headers:
        headers.update(extra_headers)
    try:
        return await client.request(method=method, url=path, headers=headers, json=json)
    except httpx.HTTPError as exc:
        log.error("api_request_failed", path=path, method=method, error=str(exc))
        return None


def _backend_detail(response: httpx.Response | None, fallback: str) -> str:
    if response is None:
        return "The Hyrule Cloud API is temporarily unreachable."
    try:
        body = response.json()
    except ValueError:
        return fallback
    if not isinstance(body, dict):
        return fallback
    detail = body.get("detail") or body.get("error")
    return str(detail)[:300] if detail else fallback


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
    """Block B: the homepage renders backend runtime stats in its infrastructure
    panel, cached for 15s and stale-on-error.

    Issue #14: the settlement-chain copy is also driven from the live
    /v1/payments/networks list (single source of truth, same as /faq and
    llms.txt) — never hardcoded — per [[feedback_verified_payment_chains]]."""
    runtime = await _refresh_runtime(request)
    catalog = await _refresh_networks(request)
    tool_catalog = await _refresh_tool_catalog(request)
    return _render(
        request,
        "index.html",
        runtime=runtime,
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        vm_tiers=_live_vm_tiers(await _refresh_products(request)),
        x402_resources=catalog_resources(tool_catalog),
        catalog_status=tool_catalog["status"],
        mail=await _refresh_mail_products(request),
    )


@app.get("/services", response_class=HTMLResponse)
async def page_services(request: Request) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    tool_catalog = await _refresh_tool_catalog(request)
    proxy_enabled = tool_catalog["status"] == "live" and any(
        isinstance(tool, dict) and tool.get("group") == "proxy" for tool in tool_catalog["tools"]
    )
    proxy_prices = _proxy_prices(await _refresh_pricing(request)) if proxy_enabled else {}
    mail = await _refresh_mail_products(request)
    return _render(
        request,
        "services.html",
        os_templates=os_list,
        vm_tiers=_live_vm_tiers(await _refresh_products(request)),
        x402_resources=catalog_resources(tool_catalog),
        catalog_status=tool_catalog["status"],
        proxy_enabled=proxy_enabled,
        proxy_prices=proxy_prices,
        mail=mail,
        hosted_mail_product=_available_mail_product(mail, "agent-mail-hosted"),
    )


@app.get("/agent-mail", response_class=HTMLResponse)
async def page_agent_mail(request: Request) -> Response:
    """API-only agent identity offer, availability sourced from live backend."""
    await _refresh_runtime(request)
    products = await _refresh_mail_products(request)
    return _render(
        request,
        "agent_mail.html",
        mail=products,
        hosted_mail_product=_available_mail_product(products, "agent-mail-hosted"),
        campaign_launch=CAMPAIGN_LAUNCH,
    )


@app.get("/blog", response_class=HTMLResponse)
async def page_blog(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(
        request,
        "blog.html",
        journeys=JOURNEYS,
        campaign_launch=CAMPAIGN_LAUNCH,
    )


async def _render_journey(request: Request, slug: str) -> Response:
    journey = JOURNEYS_BY_SLUG.get(slug)
    if journey is None:
        raise HTTPException(status_code=404)
    await _refresh_runtime(request)
    mail = (
        await _refresh_mail_products(request)
        if slug == "agent-email-domain-deliverability"
        else None
    )
    return _render(
        request,
        "journey.html",
        journey=journey,
        journeys=JOURNEYS,
        mail=mail,
        campaign_launch=CAMPAIGN_LAUNCH,
    )


@app.get(
    "/blog/explain-broken-website-tls",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def page_journey_web(request: Request) -> Response:
    return await _render_journey(request, "explain-broken-website-tls")


@app.get(
    "/blog/agent-email-domain-deliverability",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def page_journey_mail(request: Request) -> Response:
    return await _render_journey(request, "agent-email-domain-deliverability")


@app.get(
    "/blog/deploy-fresh-vm",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def page_journey_vm(request: Request) -> Response:
    return await _render_journey(request, "deploy-fresh-vm")


@app.get("/blog/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def page_journey(request: Request, slug: str) -> Response:
    return await _render_journey(request, slug)


@app.get("/agents", response_class=HTMLResponse)
async def page_agents(request: Request) -> Response:
    """Direct x402 and browser-agent integration documentation."""
    catalog = await _refresh_networks(request)
    tool_catalog = await _refresh_tool_catalog(request)
    return _render(
        request,
        "agents.html",
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        x402_resources=catalog_resources(tool_catalog),
        tools=tool_catalog["tools"],
        catalog_status=tool_catalog["status"],
    )


@app.get("/toolbox", response_class=HTMLResponse)
async def page_toolbox(request: Request) -> Response:
    """Human and browser-agent x402 diagnostics driven by enabled OpenAPI."""
    network_catalog = await _refresh_networks(request)
    networks = _catalog_networks(network_catalog)
    tool_catalog = await _refresh_tool_catalog(request)
    networks_fresh = time.time() < float(_CATALOG_CACHE.get("expires_at", 0.0))
    execution_enabled = (
        tool_catalog["status"] == "live"
        and networks_fresh
        and any(network.get("family") == "evm" for network in networks)
        and any(
            isinstance(tool, dict) and bool(tool.get("executable"))
            for tool in tool_catalog["tools"]
        )
    )
    return _render(
        request,
        "toolbox.html",
        tools=tool_catalog["tools"],
        tool_catalog=browser_catalog({**tool_catalog, "execution_enabled": execution_enabled}),
        catalog_status=tool_catalog["status"],
        execution_enabled=execution_enabled,
        networks=networks,
    )


@app.get("/domains", response_class=HTMLResponse)
async def page_domains(request: Request, domain: str = "") -> Response:
    """Public search and live eligible-TLD catalog."""
    catalog_response = await _api_request(request, "/v1/domains/tlds", forward_cookie=False)
    tlds: list[dict[str, Any]] = []
    catalog_error: str | None = None
    if catalog_response is not None and catalog_response.status_code == 200:
        body = catalog_response.json()
        tlds = body.get("tlds", []) if isinstance(body, dict) else []
    else:
        catalog_error = _backend_detail(
            catalog_response, "The live TLD catalog is temporarily unavailable."
        )

    searched = domain.strip().lower().rstrip(".")
    check: dict[str, Any] | None = None
    check_error: str | None = None
    if searched:
        check_response = await _api_request(
            request,
            "/v1/domains/check?domain=" + urllib.parse.quote(searched, safe=""),
            forward_cookie=False,
        )
        if check_response is not None and check_response.status_code == 200:
            check = check_response.json()
        else:
            check_error = _backend_detail(
                check_response, "That domain could not be checked right now."
            )
    return _render(
        request,
        "domains.html",
        searched_domain=searched,
        check=check,
        check_error=check_error,
        catalog_error=catalog_error,
        tlds=tlds,
    )


@app.post("/domains/quote")
async def create_domain_quote(
    request: Request,
    domain: Annotated[str, Form()],
    action: Annotated[str, Form()] = "register",
) -> Response:
    action = action if action in {"register", "renew"} else "register"
    response = await _api_request(
        request,
        "/v1/domains/quotes",
        method="POST",
        json={"domain": domain.strip(), "action": action},
    )
    if response is not None and response.status_code == 201:
        quote_id = response.json()["quote_id"]
        return RedirectResponse(f"/domains/checkout/{quote_id}", status_code=303)
    catalog_response = await _api_request(request, "/v1/domains/tlds", forward_cookie=False)
    catalog = (
        catalog_response.json().get("tlds", [])
        if catalog_response is not None and catalog_response.status_code == 200
        else []
    )
    return _render(
        request,
        "domains.html",
        searched_domain=domain.strip(),
        check=None,
        check_error=_backend_detail(response, "A quote could not be created."),
        catalog_error=None,
        tlds=catalog,
        status_code=(
            response.status_code if response is not None and response.status_code < 500 else 503
        ),
    )


@app.get("/domains/checkout/{quote_id}", response_class=HTMLResponse)
async def domain_checkout(request: Request, quote_id: str) -> Response:
    quote_response = await _api_request(
        request,
        f"/v1/domains/quotes/{urllib.parse.quote(quote_id, safe='')}",
        forward_cookie=False,
    )
    if quote_response is None or quote_response.status_code != 200:
        return _render(
            request,
            "domain_checkout.html",
            quote=None,
            authenticated=False,
            networks=[],
            native=[],
            error=_backend_detail(quote_response, "This domain quote is unavailable or expired."),
            status_code=quote_response.status_code if quote_response is not None else 503,
        )
    me_response = await _api_request(request, "/v1/me")
    authenticated = bool(me_response is not None and me_response.status_code == 200)
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "domain_checkout.html",
        quote=quote_response.json(),
        authenticated=authenticated,
        networks=[
            network
            for network in _catalog_networks(catalog)
            if isinstance(network, dict) and network.get("family") == "evm"
        ],
        native=_catalog_native(catalog),
        error=None,
    )


@app.get("/domains/orders/{order_id}", response_class=HTMLResponse)
async def domain_order_status(request: Request, order_id: str) -> Response:
    order_path = "/domains/orders/" + urllib.parse.quote(order_id, safe="")
    response = await _api_request(
        request,
        f"/v1/domains/orders/{urllib.parse.quote(order_id, safe='')}",
    )
    if response is None:
        return _render(
            request,
            "domain_order.html",
            order=None,
            error=_backend_detail(response, "The domain order could not be loaded."),
            status_code=503,
        )
    if response.status_code == 401:
        return RedirectResponse(
            "/login?" + urllib.parse.urlencode({"next": order_path}),
            status_code=303,
        )
    if response.status_code != 200:
        return _render(
            request,
            "domain_order.html",
            order=None,
            error=_backend_detail(response, "The domain order could not be loaded."),
            status_code=response.status_code,
        )
    return _render(
        request,
        "domain_order.html",
        order=response.json(),
        error=None,
    )


async def _render_order_form(
    request: Request,
    *,
    products: dict[str, Any] | None = None,
    form_values: dict[str, Any] | None = None,
    order_error: str | None = None,
    status_code: int = 200,
) -> Response:
    os_data = await _fetch_api(request, "/v1/os/list")
    os_list = os_data.get("templates", DEFAULT_OS_TEMPLATES) if os_data else DEFAULT_OS_TEMPLATES
    catalog = await _refresh_networks(request)
    products = products if products is not None else await _refresh_products(request)
    return _render(
        request,
        "order.html",
        os_templates=os_list,
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
        vm_tiers=_live_vm_tiers(products),
        vm_customization=_live_vm_customization(products),
        order_error=order_error,
        form_values=form_values or {},
        status_code=status_code,
    )


@app.get("/order", response_class=HTMLResponse)
async def page_order(request: Request) -> Response:
    return await _render_order_form(request)


@app.post("/order/profile", response_class=HTMLResponse)
async def page_order_profile(
    request: Request,
    profile: Annotated[str, Form()],
    os: Annotated[str, Form()] = "",
    duration: Annotated[int, Form()] = 30,
    ssh_pubkey: Annotated[str, Form()] = "",
    hostname: Annotated[str, Form()] = "",
    domain_mode: Annotated[str, Form()] = "auto",
    domain: Annotated[str, Form()] = "",
) -> Response:
    """Switch profile defaults without discarding the rest of the order form."""
    products = await _refresh_products(request)
    vm_tiers = _live_vm_tiers(products)
    valid_profile = profile in vm_tiers
    selected_profile = (
        profile if valid_profile else ("sm" if "sm" in vm_tiers else next(iter(vm_tiers)))
    )
    return await _render_order_form(
        request,
        products=products,
        form_values={
            "os": os,
            "size": selected_profile,
            "duration": duration,
            "ssh_pubkey": ssh_pubkey,
            "hostname": hostname,
            "domain_mode": domain_mode,
            "domain": domain,
        },
        order_error=None if valid_profile else "Choose a valid server size.",
        status_code=200 if valid_profile else 422,
    )


@app.get("/status", response_class=HTMLResponse)
async def page_service_status(request: Request) -> Response:
    await _refresh_service_status(request)
    return _render(request, "service_status.html")


@app.get("/order/status", include_in_schema=False)
async def legacy_service_status_redirect() -> RedirectResponse:
    return RedirectResponse("/status", status_code=308)


@app.post("/order/review")
async def page_review(
    request: Request,
    os: Annotated[str, Form()],
    size: Annotated[str, Form()],
    duration: Annotated[int, Form()],
    ssh_pubkey: Annotated[str, Form()],
    hostname: Annotated[str, Form()] = "",
    domain_mode: Annotated[str, Form()] = "auto",
    domain: Annotated[str, Form()] = "",
    vcpu: Annotated[int | None, Form()] = None,
    ram_mb: Annotated[int | None, Form()] = None,
    disk_gb: Annotated[int | None, Form()] = None,
) -> Response:
    products = await _refresh_products(request)
    vm_tiers = _live_vm_tiers(products)
    customization = _live_vm_customization(products)
    selected_tier = vm_tiers.get(size, VM_TIERS["sm"])
    final_resources = {
        "vcpu": vcpu if vcpu is not None else int(selected_tier["vcpu"]),
        "ram_mb": ram_mb if ram_mb is not None else int(selected_tier["ram_mb"]),
        "disk_gb": disk_gb if disk_gb is not None else int(selected_tier["disk_gb"]),
    }
    form_values = {
        "os": os,
        "size": size,
        "duration": duration,
        "ssh_pubkey": ssh_pubkey,
        "hostname": hostname,
        "domain_mode": domain_mode,
        "domain": domain,
        **final_resources,
    }
    custom_domain = _normalise_custom_domain(domain) if domain_mode == "custom" else None
    error: str | None = None
    if size not in vm_tiers:
        error = "Choose a valid server size."
    elif not 1 <= duration <= 365:
        error = "Duration must be between 1 and 365 days."
    elif domain_mode not in {"auto", "custom"}:
        error = "Choose automatic or custom domain setup."
    elif domain_mode == "custom" and custom_domain is None:
        error = "Enter a valid fully-qualified domain name."
    else:
        for key, label in (("vcpu", "vCPU"), ("ram_mb", "RAM"), ("disk_gb", "SSD")):
            minimum = int(customization["minimum"][key])
            maximum = int(customization["maximum"][key])
            increment = int(customization["increments"][key])
            value = final_resources[key]
            if not minimum <= value <= maximum or (value - minimum) % increment:
                error = f"Choose {label} within the available order limits."
                break

    if error is None:
        order_payload: dict[str, Any] = {
            "os": os,
            "size": size,
            "duration_days": duration,
            "ssh_pubkey": ssh_pubkey,
            "domain_mode": domain_mode,
            "resources": final_resources,
        }
        if custom_domain is not None:
            order_payload["domain"] = custom_domain
        backend = await _api_request(
            request,
            "/v1/vm/quote",
            method="POST",
            json={"order_payload": order_payload},
        )
        if backend is not None and backend.status_code in {200, 201}:
            try:
                quote_id = backend.json().get("quote_id")
            except ValueError:
                quote_id = None
            if isinstance(quote_id, str) and quote_id:
                review_path = f"/order/review/{urllib.parse.quote(quote_id, safe='')}"
                return RedirectResponse(review_path, status_code=303)
        if backend is not None:
            try:
                detail = backend.json().get("detail")
            except ValueError:
                detail = None
            error = (
                str(detail)
                if detail
                else "The quote could not be created. Check the form and try again."
            )
        else:
            error = "The ordering API is temporarily unavailable. Your form has not been submitted."

    return await _render_order_form(
        request,
        products=products,
        order_error=error,
        form_values=form_values,
        status_code=422,
    )


@app.get("/order/review/{quote_id}", response_class=HTMLResponse)
async def page_review_quote(request: Request, quote_id: str) -> Response:
    """Issue #14: reload-safe review page backed by a durable quote.

    The order form (order.ts) creates a quote and sends the browser here, so a
    mobile wallet handoff that reloads the page just re-GETs this URL and the
    order is re-rendered from the backend — no lost POST body. Unknown quote →
    back to the order form; expired quote → render with a restart banner."""
    quote = await _fetch_api(request, f"/v1/vm/quote/{quote_id}")
    if not quote:
        return RedirectResponse("/order", status_code=303)

    payload: dict[str, Any] = quote.get("order_payload") or {}
    size = payload.get("size", "sm")
    duration = payload.get("duration_days", 30)
    vm_tiers = _live_vm_tiers(await _refresh_products(request))
    catalog_tier = vm_tiers.get(size, VM_TIERS["sm"])
    resources = (
        quote.get("resources")
        or payload.get("resources")
        or {
            "vcpu": catalog_tier["vcpu"],
            "ram_mb": catalog_tier["ram_mb"],
            "disk_gb": catalog_tier["disk_gb"],
        }
    )
    pricing_value = quote.get("pricing")
    pricing: dict[str, Any] = pricing_value if isinstance(pricing_value, dict) else {}
    tier = {
        **catalog_tier,
        "name": pricing.get("base_label") or catalog_tier["name"],
        "vcpu": int(resources["vcpu"]),
        "ram_mb": int(resources["ram_mb"]),
        "disk_gb": int(resources["disk_gb"]),
        "price": float(pricing.get("daily_price_usd") or catalog_tier["price"]),
    }
    try:
        total = Decimal(str(quote["amount_usd"]))
    except (KeyError, InvalidOperation):
        total = Decimal(str(tier["price"])) * duration
    order = {
        "os": payload.get("os"),
        "size": size,
        "duration": duration,
        "ssh_pubkey": payload.get("ssh_pubkey", ""),
        # hostname is not part of the backend VM spec; the quote doesn't carry it.
        "hostname": "",
        "domain_mode": payload.get("domain_mode", "auto"),
        "domain": payload.get("domain") or "",
        "id": quote_id,
        "quote_id": quote_id,
        "amount_usd": total,
        "resources": resources,
        "pricing": pricing,
        "expired": quote.get("status") == "expired",
        "payment_methods": quote.get("accepted_payment_methods") or {},
    }
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "review.html",
        order=order,
        tier=tier,
        total=total,
        vm_tiers=vm_tiers,
        networks=_catalog_networks(catalog),
    )


@app.get("/order/status/{vm_id}", response_class=HTMLResponse)
async def page_status(request: Request, vm_id: str) -> Response:
    # Block A0: status page calls the sanitized public endpoint. The
    # legacy /v1/vm/{id} is now management-gated and would 404 here.
    data = await _fetch_vm_status(request, vm_id)
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
        request,
        "status.html",
        vm_id=vm_id,
        vm=data,
        management_url=management_url,
    )


# ---------------------------------------------------------------------------
# Block A1 — auth pages (signup / login / logout / recover / dashboard)
# ---------------------------------------------------------------------------


@app.get("/signup", response_class=HTMLResponse)
async def page_signup(request: Request) -> Response:
    _require_auth_ui()
    return _render(
        request,
        "signup.html",
        error=None,
        next_path=_safe_next_path(request.query_params.get("next")),
    )


@app.post("/signup", response_class=HTMLResponse)
async def do_signup(
    request: Request,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    next_path: Annotated[str, Form(alias="next")] = "/dashboard",
) -> Response:
    """Mirror the backend's password rules (min 12 chars) before round-tripping
    so we can return an inline error without burning the per-IP signup quota
    on /v1/auth/register."""
    _require_auth_ui()
    next_path = _safe_next_path(next_path)
    if password != password_confirm:
        return _render(
            request,
            "signup.html",
            error="Passwords do not match.",
            next_path=next_path,
        )
    if len(password) < 12:
        return _render(
            request,
            "signup.html",
            error="Password must be at least 12 characters.",
            next_path=next_path,
        )

    backend = await _api_request(
        request, "/v1/auth/register", method="POST", json={"password": password}
    )
    if backend is None:
        return _render(
            request,
            "signup.html",
            error="Backend unreachable. Try again.",
            next_path=next_path,
        )
    if backend.status_code == 429:
        return _render(
            request,
            "signup.html",
            error="Too many signups from your network; try later.",
            next_path=next_path,
        )
    if backend.status_code != 200:
        return _render(
            request,
            "signup.html",
            error="Signup failed. Try again.",
            next_path=next_path,
        )

    body = backend.json()
    # signup_success is the *only* place the recovery code is ever shown.
    # Render via _render so the Set-Cookie from /v1/auth/register can be
    # attached to the same response object (browser is now logged in).
    rendered = _render(
        request,
        "signup_success.html",
        account_id=body["account_id"],
        recovery_code=body["recovery_code"],
        next_path=next_path,
    )
    _copy_set_cookie(backend, rendered)
    return rendered


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request) -> Response:
    _require_auth_ui()
    return _render(
        request,
        "login.html",
        error=None,
        next_path=_safe_next_path(request.query_params.get("next")),
    )


@app.post("/login", response_class=HTMLResponse)
async def do_login(
    request: Request,
    account_id: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_path: Annotated[str, Form(alias="next")] = "/dashboard",
) -> Response:
    _require_auth_ui()
    next_path = _safe_next_path(next_path)
    backend = await _api_request(
        request,
        "/v1/auth/login",
        method="POST",
        json={"account_id": account_id.strip().upper(), "password": password},
    )
    if backend is None:
        return _render(
            request,
            "login.html",
            error="Backend unreachable.",
            next_path=next_path,
        )
    if backend.status_code == 429:
        return _render(
            request,
            "login.html",
            error="Too many login attempts; try later.",
            next_path=next_path,
        )
    if backend.status_code != 200:
        return _render(
            request,
            "login.html",
            error="Invalid credentials.",
            next_path=next_path,
        )

    redirect = RedirectResponse(next_path, status_code=303)
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
            request,
            "recover.html",
            error="Password must be at least 12 characters.",
            success=None,
        )

    backend = await _api_request(
        request,
        "/v1/auth/recover/code",
        method="POST",
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
            request,
            "recover.html",
            error="Too many recovery attempts; try later.",
            success=None,
        )
    if backend.status_code != 200:
        return _render(
            request,
            "recover.html",
            error="Invalid recovery code or account ID.",
            success=None,
        )

    body = backend.json()
    return _render(
        request,
        "recover.html",
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
            request,
            "dashboard.html",
            me=None,
            vms=[],
            domains=[],
            wallet=None,
            error="Could not load account info.",
        )
    me = me_resp.json()
    vms_resp = await _api_request(request, "/v1/me/vms")
    vms = vms_resp.json().get("vms", []) if (vms_resp and vms_resp.status_code == 200) else []
    domains_resp = await _api_request(request, "/v1/domains")
    domains = (
        domains_resp.json().get("domains", [])
        if domains_resp is not None and domains_resp.status_code == 200
        else []
    )
    wallet_resp = await _api_request(request, "/v1/auth/wallet")
    wallet = (
        wallet_resp.json()
        if wallet_resp is not None and wallet_resp.status_code == 200
        else {"address": None, "chain_id": None}
    )
    return _render(
        request,
        "dashboard.html",
        me=me,
        vms=vms,
        domains=domains,
        wallet=wallet,
        error=None,
    )


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
        request,
        f"/v1/me/vms/{vm_id.strip()}/claim",
        method="POST",
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
        request,
        "/v1/me/password",
        method="POST",
        json={"current_password": current_password, "new_password": new_password},
    )
    return RedirectResponse("/dashboard", status_code=303)


def _domain_redirect(domain: str, response: httpx.Response | None, success: str) -> Response:
    if response is not None and response.status_code < 300:
        message = success
    else:
        message = _backend_detail(response, "The domain change could not be applied.")
    return _domain_notice(domain, message)


def _domain_notice(domain: str, message: str) -> Response:
    target = "/dashboard/domains/" + urllib.parse.quote(domain, safe="")
    return RedirectResponse(
        target + "?notice=" + urllib.parse.quote(message, safe=""), status_code=303
    )


def _valid_form_idempotency_key(value: str) -> str | None:
    value = value.strip()
    return value if 8 <= len(value) <= 128 else None


def _valid_record_name(value: str) -> str | None:
    value = value.strip().lower().rstrip(".") or "@"
    if value == "@":
        return value
    labels = value.split(".")
    if any(not DNS_RECORD_LABEL_RE.fullmatch(label) for label in labels):
        return None
    if any(label == "*" for label in labels[1:]):
        return None
    return value


def _valid_nameserver(value: str) -> str | None:
    value = value.strip().lower().rstrip(".")
    return value if HOSTNAME_RE.fullmatch(value) else None


@app.get("/dashboard/domains/{domain}", response_class=HTMLResponse)
async def dashboard_domain(request: Request, domain: str) -> Response:
    _require_auth_ui()
    encoded = urllib.parse.quote(domain, safe="")
    domain_path = f"/dashboard/domains/{encoded}"
    detail_response = await _api_request(request, f"/v1/domains/{encoded}")
    if detail_response is None:
        return _render(
            request,
            "dashboard.html",
            me=None,
            vms=[],
            domains=[],
            wallet=None,
            error=_backend_detail(detail_response, "The domain could not be loaded."),
            status_code=503,
        )
    if detail_response.status_code == 401:
        return RedirectResponse(
            "/login?" + urllib.parse.urlencode({"next": domain_path}),
            status_code=303,
        )
    if detail_response.status_code != 200:
        return RedirectResponse("/dashboard", status_code=303)
    zone_response = await _api_request(request, f"/v1/domains/{encoded}/dns")
    zone = (
        zone_response.json()
        if zone_response is not None and zone_response.status_code == 200
        else None
    )
    wallet_response = await _api_request(request, "/v1/auth/wallet")
    wallet = (
        wallet_response.json()
        if wallet_response is not None and wallet_response.status_code == 200
        else {"address": None, "chain_id": None}
    )
    records = zone.get("records", []) if isinstance(zone, dict) else []
    mutation_keys = {
        "dns_upsert": secrets.token_urlsafe(24),
        "dns_delete": {
            f"{record.get('name', '')}:{record.get('type', '')}": secrets.token_urlsafe(24)
            for record in records
            if isinstance(record, dict)
        },
        "nameservers": secrets.token_urlsafe(24),
        "dnssec": secrets.token_urlsafe(24),
    }
    return _render(
        request,
        "domain_detail.html",
        domain=detail_response.json(),
        zone=zone,
        wallet=wallet,
        mutation_keys=mutation_keys,
        notice=request.query_params.get("notice"),
    )


@app.post("/dashboard/domains/{domain}/renew")
async def dashboard_domain_renew(request: Request, domain: str) -> Response:
    _require_auth_ui()
    response = await _api_request(
        request,
        "/v1/domains/quotes",
        method="POST",
        json={"domain": domain, "action": "renew"},
    )
    if response is not None and response.status_code == 201:
        return RedirectResponse(f"/domains/checkout/{response.json()['quote_id']}", status_code=303)
    return _domain_redirect(domain, response, "Renewal quote created.")


@app.post("/dashboard/domains/{domain}/dns")
async def dashboard_domain_dns(
    request: Request,
    domain: str,
    revision: Annotated[int, Form()],
    action: Annotated[str, Form()],
    name: Annotated[str, Form()],
    record_type: Annotated[str, Form()],
    ttl: Annotated[int, Form()],
    values: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    key = _valid_form_idempotency_key(idempotency_key)
    if key is None:
        return _domain_notice(domain, "This form expired. Reload the page and try again.")
    normalized_action = action.strip().lower()
    if normalized_action not in {"upsert", "delete"}:
        return _domain_notice(domain, "The DNS change action is invalid.")
    normalized_name = _valid_record_name(name)
    if normalized_name is None:
        return _domain_notice(domain, "The DNS record name is invalid.")
    normalized_type = record_type.strip().upper()
    if normalized_type not in DOMAIN_RECORD_TYPES:
        return _domain_notice(domain, "The DNS record type is not supported.")
    value_list = [line.strip() for line in values.splitlines() if line.strip()]
    if normalized_action == "upsert":
        if not 60 <= ttl <= 86400:
            return _domain_notice(domain, "TTL must be between 60 and 86400 seconds.")
        if not value_list:
            return _domain_notice(domain, "At least one DNS record value is required.")
    rrset: dict[str, Any] = {
        "name": normalized_name,
        "type": normalized_type,
        "values": value_list,
    }
    if normalized_action == "upsert":
        rrset["ttl"] = ttl
    response = await _api_request(
        request,
        f"/v1/domains/{urllib.parse.quote(domain, safe='')}/dns/changesets",
        method="POST",
        json={
            "changes": [
                {
                    "action": normalized_action,
                    "rrset": rrset,
                }
            ]
        },
        extra_headers={
            "If-Match": str(revision),
            "Idempotency-Key": key,
        },
    )
    return _domain_redirect(domain, response, "DNS zone updated.")


@app.post("/dashboard/domains/{domain}/nameservers")
async def dashboard_domain_nameservers(
    request: Request,
    domain: str,
    mode: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    nameservers: Annotated[str, Form()] = "",
) -> Response:
    _require_auth_ui()
    key = _valid_form_idempotency_key(idempotency_key)
    if key is None:
        return _domain_notice(domain, "This form expired. Reload the page and try again.")
    mode = mode.strip().lower()
    if mode not in {"managed", "external"}:
        return _domain_notice(domain, "The nameserver mode is invalid.")
    raw_servers = [item for item in re.split(r"[\s,]+", nameservers.strip()) if item]
    servers = [_valid_nameserver(item) for item in raw_servers]
    if any(server is None for server in servers):
        return _domain_notice(domain, "Every nameserver must be a valid hostname.")
    normalized_servers = [server for server in servers if server is not None]
    if len(set(normalized_servers)) != len(normalized_servers):
        return _domain_notice(domain, "Nameservers must be unique.")
    if mode == "external" and not 2 <= len(normalized_servers) <= 13:
        return _domain_notice(domain, "External mode requires between 2 and 13 nameservers.")
    response = await _api_request(
        request,
        f"/v1/domains/{urllib.parse.quote(domain, safe='')}/nameservers",
        method="PUT",
        json={"mode": mode, "nameservers": normalized_servers if mode == "external" else []},
        extra_headers={"Idempotency-Key": key},
    )
    return _domain_redirect(domain, response, "Nameserver change queued.")


@app.post("/dashboard/domains/{domain}/dnssec")
async def dashboard_domain_dnssec(
    request: Request,
    domain: str,
    mode: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    ds_records: Annotated[str, Form()] = "",
) -> Response:
    _require_auth_ui()
    key = _valid_form_idempotency_key(idempotency_key)
    if key is None:
        return _domain_notice(domain, "This form expired. Reload the page and try again.")
    mode = mode.strip().lower()
    if mode not in {"managed", "external", "off"}:
        return _domain_notice(domain, "The DNSSEC mode is invalid.")
    records: list[dict[str, Any]] = []
    if mode == "external":
        try:
            for line in ds_records.splitlines():
                if not line.strip():
                    continue
                key_tag, algorithm, digest_type, digest = line.split(maxsplit=3)
                key_tag_value = int(key_tag)
                algorithm_value = int(algorithm)
                digest_type_value = int(digest_type)
                digest = digest.strip().upper()
                if not (
                    0 <= key_tag_value <= 65535
                    and 1 <= algorithm_value <= 255
                    and 1 <= digest_type_value <= 255
                    and 16 <= len(digest) <= 256
                    and re.fullmatch(r"[0-9A-F]+", digest)
                ):
                    raise ValueError("invalid DS record")
                records.append(
                    {
                        "key_tag": key_tag_value,
                        "algorithm": algorithm_value,
                        "digest_type": digest_type_value,
                        "digest": digest,
                    }
                )
        except (ValueError, TypeError):
            return _domain_notice(
                domain,
                "Each external DS line must contain: key-tag algorithm digest-type digest.",
            )
        if not records:
            return _domain_notice(domain, "External DNSSEC requires at least one DS record.")
        if len(records) > 8:
            return _domain_notice(domain, "External DNSSEC accepts at most 8 DS records.")
    response = await _api_request(
        request,
        f"/v1/domains/{urllib.parse.quote(domain, safe='')}/dnssec",
        method="PUT",
        json={"mode": mode, "ds_records": records},
        extra_headers={"Idempotency-Key": key},
    )
    return _domain_redirect(domain, response, "DNSSEC change queued.")


@app.post("/dashboard/domains/claim")
async def dashboard_domain_claim(
    request: Request,
    domain: Annotated[str, Form()],
    token: Annotated[str, Form()],
) -> Response:
    _require_auth_ui()
    response = await _api_request(
        request,
        f"/v1/domains/{urllib.parse.quote(domain.strip(), safe='')}/claim",
        method="POST",
        json={"token": token.strip()},
    )
    if response is not None and response.status_code == 200:
        return RedirectResponse(
            "/dashboard/domains/" + urllib.parse.quote(domain.strip(), safe=""),
            status_code=303,
        )
    return RedirectResponse("/dashboard?domain_claim=failed", status_code=303)


# ---------------------------------------------------------------------------
# SEO surface — robots.txt, sitemap.xml, llms.txt
# ---------------------------------------------------------------------------


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return ROBOTS_TXT


# Serve the brand icons at the well-known root paths too (browsers and crawlers
# request /favicon.ico directly, not just the <link>-referenced /static path).
# Brand marks change rarely, so cache for a week; no `immutable` because the URL
# is stable (not content-hashed) and we want a rebrand to still revalidate.
_ICON_CACHE_CONTROL = "public, max-age=604800"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "favicon.ico",
        media_type="image/x-icon",
        headers={"Cache-Control": _ICON_CACHE_CONTROL},
    )


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "apple-touch-icon.png",
        media_type="image/png",
        headers={"Cache-Control": _ICON_CACHE_CONTROL},
    )


@app.get("/about", response_class=HTMLResponse)
async def page_about(request: Request) -> Response:
    """Mission, operating principles, and abuse-handling overview."""
    await _refresh_runtime(request)
    return _render(request, "about.html")


@app.get("/transparency", include_in_schema=False)
async def page_transparency_redirect() -> RedirectResponse:
    """Keep old inbound links working without indexing duplicate content."""
    return RedirectResponse(url="/about", status_code=308)


@app.get("/faq", response_class=HTMLResponse)
async def page_faq(request: Request) -> Response:
    """FAQ + FAQPage JSON-LD (Block G). Only mentions live payment methods —
    the chain list comes from /v1/payments/networks, never hardcoded."""
    await _refresh_runtime(request)
    catalog = await _refresh_networks(request)
    return _render(
        request,
        "faq.html",
        networks=_catalog_networks(catalog),
        native=_catalog_native(catalog),
    )


@app.get("/terms", response_class=HTMLResponse)
async def page_terms(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["terms"])


@app.get("/privacy", response_class=HTMLResponse)
async def page_privacy(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["privacy"])


@app.get("/abuse", response_class=HTMLResponse)
async def page_abuse(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["abuse"])


@app.get("/legal", response_class=HTMLResponse)
async def page_legal(request: Request) -> Response:
    await _refresh_runtime(request)
    return _render(request, "legal_page.html", page=LEGAL_PAGES["legal"])


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    return Response(content=render_sitemap_xml(app), media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request) -> str:
    # Build from live backend state so the doc never advertises a disabled
    # chain (feedback_verified_payment_chains). None → "ask the API" note.
    networks_resp = await _refresh_networks(request)
    networks = networks_resp.get("networks") if networks_resp else None
    native = networks_resp.get("native") if networks_resp else None
    tool_catalog = await _refresh_tool_catalog(request)
    network_fresh = time.time() < float(_CATALOG_CACHE.get("expires_at", 0.0))
    catalog_fresh = tool_catalog.get("status") == "live"
    mail = await _refresh_mail_products(request)
    return build_llms_txt(
        networks,
        native=native,
        diagnostics_live=network_fresh and catalog_fresh,
        payments_live=network_fresh,
        tools=tool_catalog.get("tools"),
        mail=mail if mail.get("catalog_status") == "live" else None,
    )


# ---------------------------------------------------------------------------
# API proxy — browser talks to same origin, we forward to the backend API
# ---------------------------------------------------------------------------


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(request: Request, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.http
    api_path = path[3:] if path.startswith("v1/") else path

    forward_headers: dict[str, str] = {}
    for key in request.headers:
        lower = key.lower()
        if lower in (
            "content-type",
            "accept",
            "x-payment",
            "x-payment-signature",
            "x-dev-bypass",
            "payment-signature",
            "x-payment-required",
            "idempotency-key",
            "if-match",
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
        backend_url = f"/v1/{api_path}"
        if request.url.query:
            backend_url += "?" + request.url.query
        resp = await client.request(
            method=request.method,
            url=backend_url,
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
    base_headers: dict[str, str] = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
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
