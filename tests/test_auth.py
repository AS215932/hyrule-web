"""Block A1: frontend auth pages and dashboard.

These tests stub the hyrule-cloud backend with respx and exercise the
hyrule-web handlers end-to-end through the FastAPI TestClient.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

# --- /signup ---


def test_signup_get_renders_form(client: TestClient) -> None:
    r = client.get("/signup")
    assert r.status_code == 200
    assert 'name="password"' in r.text
    assert 'name="password_confirm"' in r.text


def test_signup_rejects_mismatched_passwords(client: TestClient) -> None:
    r = client.post(
        "/signup",
        data={"password": "correct horse battery", "password_confirm": "different"},
    )
    assert r.status_code == 200
    assert "Passwords do not match" in r.text


def test_signup_rejects_short_password(client: TestClient) -> None:
    r = client.post(
        "/signup",
        data={"password": "short", "password_confirm": "short"},
    )
    assert r.status_code == 200
    assert "at least 12 characters" in r.text


def test_signup_happy_path_shows_recovery_code_and_forwards_cookie(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/register").mock(
        return_value=httpx.Response(
            200,
            json={"account_id": "H1234567890", "recovery_code": "hyr-rec-abcdef234567abcdef234567ab"},
            headers={"set-cookie": "hyr_sess=abc; HttpOnly; SameSite=Lax; Path=/"},
        )
    )
    r = client.post(
        "/signup",
        data={
            "password": "long enough password",
            "password_confirm": "long enough password",
        },
    )
    assert r.status_code == 200
    # The success page reveals both the account_id and recovery code
    assert "H1234567890" in r.text
    assert "hyr-rec-abcdef234567abcdef234567ab" in r.text
    # And the session cookie was forwarded
    assert "hyr_sess=abc" in r.headers.get("set-cookie", "")


def test_signup_surfaces_backend_429(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(429))
    r = client.post(
        "/signup",
        data={"password": "long enough password", "password_confirm": "long enough password"},
    )
    assert r.status_code == 200
    assert "Too many signups" in r.text


# --- /login ---


def test_login_get_renders_form(client: TestClient) -> None:
    r = client.get("/login")
    assert r.status_code == 200
    assert 'name="account_id"' in r.text
    assert 'name="password"' in r.text


def test_login_happy_path_redirects_with_cookie(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/login").mock(
        return_value=httpx.Response(
            200,
            json={"account_id": "H1234567890"},
            headers={"set-cookie": "hyr_sess=xyz; HttpOnly; SameSite=Lax; Path=/"},
        )
    )
    r = client.post(
        "/login",
        data={"account_id": "H1234567890", "password": "right password here"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert "hyr_sess=xyz" in r.headers.get("set-cookie", "")


def test_login_normalizes_account_id_to_uppercase(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(401))
    client.post("/login", data={"account_id": "h1234567890", "password": "any password long"})
    sent = route.calls.last.request.content
    assert b'"H1234567890"' in sent


def test_login_401_shows_generic_error(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(401))
    r = client.post(
        "/login",
        data={"account_id": "H1234567890", "password": "wrong password here"},
    )
    assert r.status_code == 200
    assert "Invalid credentials" in r.text


# --- /logout ---


def test_logout_calls_backend_and_redirects_to_home(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/logout").mock(
        return_value=httpx.Response(
            200,
            json={"status": "ok"},
            headers={"set-cookie": 'hyr_sess=""; Max-Age=0; Path=/'},
        )
    )
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # Forwarded the cookie-clear from backend
    assert "hyr_sess=" in r.headers.get("set-cookie", "")


# --- /recover ---


def test_recover_get_renders_form(client: TestClient) -> None:
    r = client.get("/recover")
    assert r.status_code == 200
    assert 'name="recovery_code"' in r.text


def test_recover_rejects_mismatched_passwords(client: TestClient) -> None:
    r = client.post(
        "/recover",
        data={
            "account_id": "H1234567890",
            "recovery_code": "hyr-rec-abcdefghij",
            "new_password": "first new password ok",
            "new_password_confirm": "different new password",
        },
    )
    assert r.status_code == 200
    assert "Passwords do not match" in r.text


def test_recover_happy_path_shows_new_recovery_code(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/recover/code").mock(
        return_value=httpx.Response(
            200,
            json={
                "account_id": "H1234567890",
                "new_recovery_code": "hyr-rec-newonenewonenewone1234",
            },
        )
    )
    r = client.post(
        "/recover",
        data={
            "account_id": "H1234567890",
            "recovery_code": "hyr-rec-oldoldoldold",
            "new_password": "brand new password yo",
            "new_password_confirm": "brand new password yo",
        },
    )
    assert r.status_code == 200
    assert "hyr-rec-newonenewonenewone1234" in r.text
    assert "Continue to login" in r.text


def test_recover_401_shows_generic_error(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.post("/v1/auth/recover/code").mock(return_value=httpx.Response(401))
    r = client.post(
        "/recover",
        data={
            "account_id": "H1234567890",
            "recovery_code": "hyr-rec-bogusbogusbogus",
            "new_password": "brand new password yo",
            "new_password_confirm": "brand new password yo",
        },
    )
    assert r.status_code == 200
    assert "Invalid recovery code" in r.text


# --- /dashboard ---


def test_dashboard_renders_when_authed(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "account_id": "H1234567890",
                "created_at": "2026-05-16T10:00:00Z",
                "last_login_at": None,
                "is_admin": False,
                "vm_count": 1,
            },
        )
    )
    mocked_api.get("/v1/me/vms").mock(
        return_value=httpx.Response(
            200,
            json={
                "vms": [
                    {
                        "vm_id": "vm_abc123",
                        "status": "ready",
                        "os": "debian-13",
                        "size": "xs",
                        "ipv6": "2a0c:b641:b51::1",
                        "hostname": "abc.deploy.hyrule.host",
                        "expires_at": "2026-06-16T10:00:00Z",
                        "created_at": "2026-05-16T10:00:00Z",
                    }
                ]
            },
        )
    )
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "H1234567890" in r.text
    assert "vm_abc123" in r.text
    assert "debian-13" in r.text


def test_dashboard_renders_empty_state(client: TestClient, mocked_api: respx.MockRouter) -> None:
    mocked_api.get("/v1/me").mock(
        return_value=httpx.Response(200, json={
            "account_id": "H1234567890",
            "created_at": "2026-05-16T10:00:00Z",
            "last_login_at": None,
            "is_admin": False,
            "vm_count": 0,
        })
    )
    mocked_api.get("/v1/me/vms").mock(return_value=httpx.Response(200, json={"vms": []}))
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "No VMs yet" in r.text
    # Claim form is always present
    assert 'action="/dashboard/claim"' in r.text


def test_dashboard_action_reboot_forwards_to_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/vm/vm_xyz/reboot").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    r = client.post("/dashboard/vms/vm_xyz/reboot", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert route.called


def test_dashboard_action_destroy_forwards_to_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.delete("/v1/vm/vm_xyz").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    r = client.post("/dashboard/vms/vm_xyz/destroy", follow_redirects=False)
    assert r.status_code == 303
    assert route.called


def test_dashboard_claim_forwards_to_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/me/vms/vm_xyz/claim").mock(
        return_value=httpx.Response(200, json={"vm_id": "vm_xyz", "owner_account_id": "H1234567890"})
    )
    r = client.post(
        "/dashboard/claim",
        data={"vm_id": "vm_xyz", "token": "hyr_vm_thetokenhere"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    sent = route.calls.last.request.content
    assert b"hyr_vm_thetokenhere" in sent


def test_dashboard_password_change_forwards_to_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.post("/v1/me/password").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    r = client.post(
        "/dashboard/password",
        data={"current_password": "old long pw", "new_password": "newer long pw"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert route.called


# --- Nav state ---


def test_nav_shows_login_link_when_no_session_cookie(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/login"' in r.text
    assert 'href="/dashboard"' not in r.text


def test_nav_shows_dashboard_link_when_session_cookie_present(client: TestClient) -> None:
    r = client.get("/", headers={"Cookie": "hyr_sess=anything"})
    assert r.status_code == 200
    assert 'href="/dashboard"' in r.text


# --- Proxy: cookie forwarding ---


def test_proxy_forwards_cookie_to_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.get("/v1/me").mock(return_value=httpx.Response(200, json={}))
    client.get("/api/me", headers={"Cookie": "hyr_sess=mysess; other=irrelevant"})
    sent = route.calls.last.request.headers
    assert sent.get("cookie") == "hyr_sess=mysess; other=irrelevant"


def test_proxy_preserves_multiple_set_cookie_headers(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    # httpx Response only sets one set-cookie via the dict, but we can verify
    # the proxy-side handling by inspecting the response headers wing-tip.
    mocked_api.post("/v1/auth/login").mock(
        return_value=httpx.Response(
            200,
            json={"account_id": "H1234567890"},
            headers=[
                ("set-cookie", "hyr_sess=abc; HttpOnly; Path=/"),
                ("set-cookie", "hyr_csrf=def; Path=/"),
            ],
        )
    )
    r = client.post("/api/auth/login", json={"account_id": "H1234567890", "password": "x"})
    # The test client's response cookies should reflect both
    cookies = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else [r.headers.get("set-cookie", "")]
    blob = "\n".join(cookies)
    assert "hyr_sess=abc" in blob
    assert "hyr_csrf=def" in blob
