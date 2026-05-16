"""Settings env-override + VM_TIERS shape.

Tests construct fresh Settings() instances rather than mutating the module-level
singleton — pydantic-settings reads env at instantiation, so this matches what
actually happens at process start in prod.
"""

from __future__ import annotations

import pytest

from hyrule_web.config import DEFAULT_OS_TEMPLATES, VM_TIERS, Settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.api_base_url == "http://localhost:8402"
    assert s.host == "0.0.0.0"
    assert s.port == 8080
    assert s.debug is False


@pytest.mark.parametrize(
    ("env_var", "value", "attr", "expected"),
    [
        ("HYRULE_WEB_API_BASE_URL", "http://api.example.test", "api_base_url", "http://api.example.test"),
        ("HYRULE_WEB_HOST", "::", "host", "::"),
        ("HYRULE_WEB_PORT", "9090", "port", 9090),
        ("HYRULE_WEB_DEBUG", "true", "debug", True),
    ],
)
def test_settings_env_override(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    value: str,
    attr: str,
    expected: object,
) -> None:
    monkeypatch.setenv(env_var, value)
    s = Settings()
    assert getattr(s, attr) == expected


def test_vm_tiers_shape() -> None:
    expected_codes = {"xs", "sm", "md", "lg"}
    assert set(VM_TIERS) == expected_codes
    for code, tier in VM_TIERS.items():
        assert {"name", "vcpu", "ram_mb", "disk_gb", "price"} <= set(tier)
        assert tier["vcpu"] >= 1
        assert tier["ram_mb"] >= 512
        assert tier["disk_gb"] >= 10
        assert tier["price"] > 0


def test_default_os_templates_shape() -> None:
    assert len(DEFAULT_OS_TEMPLATES) >= 1
    defaults = [t for t in DEFAULT_OS_TEMPLATES if t["default"]]
    assert len(defaults) == 1
    for tpl in DEFAULT_OS_TEMPLATES:
        assert {"name", "description", "default"} <= set(tpl)
