"""Configuration for the Hyrule Cloud web frontend."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings

VM_TIERS: dict[str, dict[str, Any]] = {
    "xs": {"name": "Starter", "vcpu": 1, "ram_mb": 512, "disk_gb": 10, "price": 0.05},
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

    model_config = {"env_prefix": "HYRULE_WEB_"}


settings = Settings()
