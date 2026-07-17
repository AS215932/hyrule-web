"""Configuration for the Hyrule Cloud web frontend."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings

# FALLBACK tier catalog, used only when the live GET /v1/products/vms fetch
# fails (see app._refresh_products). The API is the source of truth for what
# actually gets provisioned — this table once drifted (xs shipped 1 GB while
# the site still said 512 MB), which is why pages now render live products.
VM_TIERS: dict[str, dict[str, Any]] = {
    "xs": {"name": "1C-1G-10G", "vcpu": 1, "ram_mb": 1024, "disk_gb": 10, "price": 0.20},
    "sm": {"name": "1C-2G-20G", "vcpu": 1, "ram_mb": 2048, "disk_gb": 20, "price": 0.40},
    "md": {"name": "2C-4G-20G", "vcpu": 2, "ram_mb": 4096, "disk_gb": 20, "price": 0.60},
    "lg": {"name": "4C-4G-40G", "vcpu": 4, "ram_mb": 4096, "disk_gb": 40, "price": 0.80},
}

VM_CUSTOMIZATION: dict[str, dict[str, Any]] = {
    "minimum": {"vcpu": 1, "ram_mb": 1024, "disk_gb": 10},
    "maximum": {"vcpu": 4, "ram_mb": 8192, "disk_gb": 40},
    "increments": {"vcpu": 1, "ram_mb": 1024, "disk_gb": 10},
    "addon_prices": {
        "vcpu_usd_day": "0.10",
        "ram_gb_usd_day": "0.15",
        "disk_10gb_usd_day": "0.05",
    },
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
