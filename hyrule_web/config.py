"""Configuration for the Hyrule Cloud web frontend."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings

# FALLBACK tier catalog, used only when the live GET /v1/products/vms fetch
# fails (see app._refresh_products). The API is the source of truth for what
# actually gets provisioned — this table once drifted (xs shipped 1 GB while
# the site still said 512 MB), which is why pages now render live products.
VM_TIERS: dict[str, dict[str, Any]] = {
    "xs": {"name": "Starter", "vcpu": 1, "ram_mb": 1024, "disk_gb": 10, "price": 0.05},
    "sm": {"name": "Basic", "vcpu": 1, "ram_mb": 1024, "disk_gb": 20, "price": 0.10},
    "md": {"name": "Standard", "vcpu": 2, "ram_mb": 2048, "disk_gb": 40, "price": 0.20},
    "lg": {"name": "Performance", "vcpu": 4, "ram_mb": 4096, "disk_gb": 80, "price": 0.40},
}

DEFAULT_OS_TEMPLATES: list[dict[str, Any]] = [
    {"name": "debian-13", "description": "Debian 13 (Trixie)", "default": True},
    {"name": "alpine-3.21", "description": "Alpine Linux 3.21", "default": False},
    {"name": "freebsd-14", "description": "FreeBSD 14.2", "default": False},
]


class Settings(BaseSettings):
    api_base_url: str = "http://localhost:8402"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # Wave 2 (Block A1): gate the auth UI behind a flag so the deploy can be
    # rolled back to "templates dark" by flipping HYRULE_WEB_ENABLE_AUTH_UI=false
    # without redeploying the backend or running a migration. When false the
    # /signup, /login, /recover, /dashboard routes return 404 and the header
    # falls back to the pre-Wave-2 nav (no Login / Dashboard pills).
    enable_auth_ui: bool = True

    # Dark until hyrule-cloud's dual-stack observers, authoritative DNS feed,
    # STUN service, retention cleanup, and privacy canaries all pass.
    enable_ip_check: bool = False

    # Issue #14 frontend build: in prod, templates load hashed assets from the
    # committed Vite manifest under static/dist/. For local dev, set this to the
    # Vite dev server origin (e.g. http://localhost:5173) AND debug=true to load
    # modules from it with HMR instead of the built bundle.
    vite_dev_server: str = ""

    # Issue #14 (Phase 4): WalletConnect/Reown projectId for mobile EVM payments.
    # This is a PUBLIC client id (Reown dashboard), surfaced to the browser via a
    # <meta> tag — NOT a secret. Empty disables the mobile WalletConnect path
    # (the injected-wallet + BTC/XMR paths still work).
    walletconnect_project_id: str = ""

    # Public origin-trial token. Empty keeps the standards-based toolbox fully
    # functional for humans while WebMCP remains feature-detected and dormant.
    webmcp_origin_trial_token: str = ""

    model_config = {"env_prefix": "HYRULE_WEB_"}


settings = Settings()
