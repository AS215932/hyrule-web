"""Private Admin dashboard role gates, live sources, and mutation safeguards."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

ADMIN = {
    "account_id": "ACCT_ADMIN1",
    "is_admin": True,
    "vm_count": 1,
    "created_at": "2026-07-01T00:00:00+00:00",
}


def _admin_sources(mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/admin/overview?window=24h").mock(
        return_value=httpx.Response(
            200,
            json={
                "window": "24h",
                "generated_at": "2026-07-19T12:00:00+00:00",
                "accounts": {"total": 4, "enabled": 3, "disabled": 1, "admins": 1},
                "resources": {"vms": 2, "running_vms": 1, "domains": 3, "mailboxes": 2},
                "payments": {
                    "settled_count": 2,
                    "revenue_usd": "4.00",
                    "admin_waiver_count": 3,
                    "admin_waived_retail_usd": "1.50",
                    "refund_owed_count": 1,
                },
                "waivers": {
                    "enabled": True,
                    "diagnostic_limit_per_minute": 120,
                    "real_cost_limit_per_hour": 10,
                    "step_up_seconds": 600,
                },
                "operations": {"failed_jobs": 1},
            },
        )
    )
    mocked_api.get("/v1/admin/accounts?limit=50").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "account_id": "ACCT_ADMIN1",
                        "is_admin": True,
                        "disabled": False,
                        "created_at": "2026-07-01T00:00:00+00:00",
                        "last_login_at": "2026-07-19T11:00:00+00:00",
                    }
                ]
            },
        )
    )
    mocked_api.get("/v1/admin/vms?limit=50").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "vm_id": "vm_admin",
                        "owner_account_id": "ACCT_ADMIN1",
                        "status": "running",
                        "hostname": "vm-admin.deploy.hyrule.host",
                        "vcpu": 1,
                        "memory_mb": 1024,
                        "disk_gb": 10,
                        "billing_mode": "admin_waived",
                        "charged_usd": "0.00",
                        "retail_usd": "1.00",
                    }
                ]
            },
        )
    )
    mocked_api.get("/v1/admin/domains?limit=50").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    mocked_api.get("/v1/admin/payment-events?limit=40").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "created_at": "2026-07-19T11:30:00+00:00",
                        "event_type": "admin_bypass",
                        "method": "POST",
                        "resource_path": "/v1/dns/lookup",
                        "service_group": "dns",
                        "amount_usd": "0.50",
                        "network": "admin-bypass",
                        "asset": "USD",
                        "actor_account_id": "ACCT_ADMIN1",
                        "tx_hash": "admin_bypass_test",
                    }
                ]
            },
        )
    )
    for path in (
        "/v1/admin/refunds?limit=40",
        "/v1/admin/jobs?limit=40",
        "/v1/admin/operations?limit=40",
        "/v1/admin/audit?limit=60",
    ):
        mocked_api.get(path).mock(return_value=httpx.Response(200, json={"items": []}))


def test_admin_dashboard_requires_login(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(401, json={"detail": "no"}))
    response = client.get("/dashboard/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fdashboard%2Fadmin"


def test_admin_dashboard_does_not_treat_backend_outage_as_logout(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/me").mock(side_effect=httpx.ConnectError("cloud unavailable"))
    response = client.get("/dashboard/admin", headers={"Cookie": "hyr_sess=admin"})
    assert response.status_code == 503
    assert "Administration unavailable" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_admin_dashboard_rejects_non_admin_and_is_not_cacheable(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "ACCT_USER01", "is_admin": False})
    )
    response = client.get("/dashboard/admin", headers={"Cookie": "hyr_sess=user"})
    assert response.status_code == 403
    assert "Administrator access required" in response.text
    assert 'content="noindex, nofollow, noarchive"' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_admin_dashboard_renders_live_metrics_and_waiver_as_non_revenue(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json=ADMIN))
    _admin_sources(mocked_api)
    response = client.get(
        "/dashboard/admin",
        headers={"Cookie": "hyr_sess=admin; hyr_csrf=hyr_csrf_test"},
    )
    assert response.status_code == 200
    assert "Settled revenue" in response.text
    assert "$4.00" in response.text
    assert "Admin-waived retail" in response.text
    assert "excluded from revenue" in response.text
    assert "vm_admin" in response.text
    assert "vm-admin.deploy.hyrule.host" in response.text
    assert 'value="hyr_csrf_test"' in response.text
    assert 'aria-current="page">Administration' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_admin_mutation_forwards_valid_csrf_and_requires_step_up(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/admin/accounts/ACCT_TARGET/disable").mock(
        return_value=httpx.Response(403, json={"detail": "admin_step_up_required"})
    )
    response = client.post(
        "/dashboard/admin/accounts/ACCT_TARGET/disable",
        headers={"Cookie": "hyr_sess=admin; hyr_csrf=hyr_csrf_test"},
        data={"reason": "abuse response", "csrf_token": "hyr_csrf_test"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard/admin/step-up?")
    request = route.calls.last.request
    assert request.headers["x-csrf-token"] == "hyr_csrf_test"
    assert json.loads(request.content) == {"reason": "abuse response"}


def test_admin_mutation_rejects_csrf_mismatch_before_cloud_call(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/admin/accounts/ACCT_TARGET/disable").mock(
        return_value=httpx.Response(200)
    )
    response = client.post(
        "/dashboard/admin/accounts/ACCT_TARGET/disable",
        headers={"Cookie": "hyr_sess=admin; hyr_csrf=hyr_csrf_real"},
        data={"reason": "abuse response", "csrf_token": "forged"},
    )
    assert response.status_code == 403
    assert not route.called


def test_admin_password_step_up_uses_same_session_csrf(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json=ADMIN))
    route = mocked_api.post("/v1/admin/step-up").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    response = client.post(
        "/dashboard/admin/step-up",
        headers={"Cookie": "hyr_sess=admin; hyr_csrf=hyr_csrf_test"},
        data={
            "password": "correct horse battery staple",
            "csrf_token": "hyr_csrf_test",
            "next": "/dashboard/admin",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard/admin?notice=")
    assert route.calls.last.request.headers["x-csrf-token"] == "hyr_csrf_test"
    assert json.loads(route.calls.last.request.content) == {
        "password": "correct horse battery staple"
    }
