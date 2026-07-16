"""Block A1 (Wave 2) — auth page handlers in the frontend.

These tests cover the server-side rendering layer only: the frontend posts
forms, the backend is mocked. The backend's own /v1/auth/* contract is
exercised in hyrule-cloud/tests/test_auth.py — here we only verify that:

  - the frontend mirrors password-strength rules client-server-side so the
    backend per-IP quota is not burned on a typo,
  - 429/5xx/unreachable map to inline errors rather than 500s,
  - the recovery code is rendered exactly once on the success page,
  - Set-Cookie issued by the backend on register/login/logout actually
    reaches the browser,
  - the feature flag (HYRULE_WEB_ENABLE_AUTH_UI=false) dark-mounts the
    entire auth surface.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from hyrule_web.config import settings

# --- GET pages render -------------------------------------------------------


def test_signup_page_renders(client: TestClient) -> None:
    r = client.get("/signup")
    assert r.status_code == 200
    assert "Create a Hyrule Cloud account" in r.text
    assert 'name="password"' in r.text
    assert 'name="password_confirm"' in r.text


def test_login_page_renders(client: TestClient) -> None:
    r = client.get("/login?next=%2Fdomains%2Fcheckout%2Fdq_test")
    assert r.status_code == 200
    assert 'name="account_id"' in r.text
    assert 'name="password"' in r.text
    assert 'name="next" value="/domains/checkout/dq_test"' in r.text
    assert 'data-next="/domains/checkout/dq_test"' in r.text


def test_recover_page_renders(client: TestClient) -> None:
    r = client.get("/recover")
    assert r.status_code == 200
    assert 'name="recovery_code"' in r.text


# --- signup happy path + Set-Cookie round-trip ------------------------------


def test_signup_happy_path_renders_recovery_code(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: /signup posts to backend /v1/auth/register, success page
    shows both account_id and recovery_code, Set-Cookie from backend reaches
    the browser."""
    mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(
        200,
        headers={"set-cookie": "hyr_sess=newsess; HttpOnly; Path=/; SameSite=Lax"},
        json={"account_id": "ACCT_NEW1", "recovery_code": "hyr-rec-zzzzz"},
    ))
    r = client.post(
        "/signup",
        data={
            "password": "correcthorsebattery",
            "password_confirm": "correcthorsebattery",
            "next": "/domains/checkout/dq_signup",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "ACCT_NEW1" in r.text
    assert "hyr-rec-zzzzz" in r.text
    assert "save this once" in r.text.lower()
    assert 'href="/domains/checkout/dq_signup"' in r.text
    assert r.cookies.get("hyr_sess") == "newsess"


# --- signup form-side validation (don't burn the backend quota on typos) ----


def test_signup_password_mismatch_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    backend = mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(200))
    r = client.post(
        "/signup",
        data={"password": "correcthorsebatteryA", "password_confirm": "wrongdifferent12"},
    )
    assert r.status_code == 200
    assert "Passwords do not match" in r.text
    assert not backend.called  # backend not hit at all


def test_signup_short_password_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    backend = mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(200))
    # FastAPI's Form() rejects empty; we need at least 1 char that fails our >=12 check.
    r = client.post(
        "/signup",
        data={"password": "short", "password_confirm": "short"},
    )
    assert r.status_code == 200
    assert "at least 12 characters" in r.text
    assert not backend.called


def test_signup_rate_limited_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(429))
    r = client.post(
        "/signup",
        data={"password": "correcthorsebattery", "password_confirm": "correcthorsebattery"},
    )
    assert r.status_code == 200
    assert "too many" in r.text.lower()


def test_signup_backend_unreachable_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/register").mock(side_effect=httpx.ConnectError("down"))
    r = client.post(
        "/signup",
        data={"password": "correcthorsebattery", "password_confirm": "correcthorsebattery"},
    )
    assert r.status_code == 200
    assert "Backend unreachable" in r.text


def test_signup_backend_400_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """A 400 from the backend (e.g. policy mismatch) becomes a generic 'try
    again' rather than a 500 to the user."""
    mocked_api.post("/v1/auth/register").mock(return_value=httpx.Response(400, json={}))
    r = client.post(
        "/signup",
        data={"password": "correcthorsebattery", "password_confirm": "correcthorsebattery"},
    )
    assert r.status_code == 200
    assert "Signup failed" in r.text


# --- login --------------------------------------------------------------------


def test_login_happy_path_redirects_to_dashboard(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: successful login forwards Set-Cookie and redirects to
    /dashboard via 303 — the browser's POST becomes a GET on the next page."""
    mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(
        200,
        headers={"set-cookie": "hyr_sess=loginsess; HttpOnly; Path=/; SameSite=Lax"},
        json={"account_id": "ACCT_BBB"},
    ))
    r = client.post(
        "/login",
        data={"account_id": "acct_bbb", "password": "correcthorsebattery"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert r.cookies.get("hyr_sess") == "loginsess"


def test_login_returns_to_safe_checkout_and_rejects_external_redirects(
    client: TestClient,
    mocked_api: respx.MockRouter,
) -> None:
    mocked_api.post("/v1/auth/login").mock(
        return_value=httpx.Response(200, json={"account_id": "ACCT_RETURN"})
    )
    checkout = client.post(
        "/login",
        data={
            "account_id": "acct_return",
            "password": "correcthorsebattery",
            "next": "/domains/checkout/dq_return",
        },
        follow_redirects=False,
    )
    assert checkout.status_code == 303
    assert checkout.headers["location"] == "/domains/checkout/dq_return"

    external = client.post(
        "/login",
        data={
            "account_id": "acct_return",
            "password": "correcthorsebattery",
            "next": "https://attacker.example/steal",
        },
        follow_redirects=False,
    )
    assert external.status_code == 303
    assert external.headers["location"] == "/dashboard"


def test_login_uppercases_account_id_before_calling_backend(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Account IDs are stored upper-cased by the backend; we normalise here
    so typing `acct_xyz` works the same as `ACCT_XYZ`."""
    route = mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(
        200, json={"account_id": "ACCT_XYZ"},
    ))
    client.post(
        "/login",
        data={"account_id": "  acct_xyz  ", "password": "correcthorsebattery"},
        follow_redirects=False,
    )
    body = route.calls.last.request.read()
    assert b'"account_id":"ACCT_XYZ"' in body


def test_login_bad_creds_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(401))
    r = client.post(
        "/login",
        data={"account_id": "ACCT_X", "password": "wrongwrongwrong"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "Invalid credentials" in r.text


def test_login_rate_limited_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/login").mock(return_value=httpx.Response(429))
    r = client.post(
        "/login",
        data={"account_id": "ACCT_X", "password": "wrongwrongwrong"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "too many" in r.text.lower()


def test_login_backend_unreachable_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/login").mock(side_effect=httpx.ConnectError("down"))
    r = client.post(
        "/login",
        data={"account_id": "ACCT_X", "password": "wrongwrongwrong"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "Backend unreachable" in r.text


# --- logout -------------------------------------------------------------------


def test_logout_redirects_home_and_forwards_set_cookie(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """/logout calls backend /v1/auth/logout and forwards the expiring
    Set-Cookie so the browser drops the stale session cookie."""
    mocked_api.post("/v1/auth/logout").mock(return_value=httpx.Response(
        200,
        headers={"set-cookie": "hyr_sess=; Max-Age=0; Path=/"},
        json={},
    ))
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # An expiring Set-Cookie has empty value — TestClient still records the call.
    set_cookie = r.headers.get("set-cookie", "")
    assert "hyr_sess" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_logout_when_backend_unreachable_still_redirects_home(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """If the backend is down the user still gets bounced to /, even though
    we can't tell the backend to revoke the session — the cookie outlives
    the brief outage but the user is at least off the dashboard."""
    mocked_api.post("/v1/auth/logout").mock(side_effect=httpx.ConnectError("down"))
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


# --- recover ------------------------------------------------------------------


def test_recover_happy_path_renders_new_code(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: successful recovery renders the new one-time recovery code
    on the same page — the user must save it now."""
    mocked_api.post("/v1/auth/recover/code").mock(return_value=httpx.Response(
        200, json={"account_id": "ACCT_R", "new_recovery_code": "hyr-rec-newnewnew"},
    ))
    r = client.post(
        "/recover",
        data={
            "account_id": "acct_r",
            "recovery_code": "hyr-rec-oldoldold",
            "new_password": "correcthorsebattery",
            "new_password_confirm": "correcthorsebattery",
        },
    )
    assert r.status_code == 200
    assert "hyr-rec-newnewnew" in r.text
    assert "Password reset" in r.text


def test_recover_password_mismatch_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    backend = mocked_api.post("/v1/auth/recover/code").mock(return_value=httpx.Response(200))
    r = client.post(
        "/recover",
        data={
            "account_id": "ACCT_R",
            "recovery_code": "hyr-rec-old",
            "new_password": "correcthorsebattery",
            "new_password_confirm": "differentdifferent",
        },
    )
    assert r.status_code == 200
    assert "Passwords do not match" in r.text
    assert not backend.called


def test_recover_bad_code_inline_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.post("/v1/auth/recover/code").mock(return_value=httpx.Response(401))
    r = client.post(
        "/recover",
        data={
            "account_id": "ACCT_R",
            "recovery_code": "hyr-rec-wrong",
            "new_password": "correcthorsebattery",
            "new_password_confirm": "correcthorsebattery",
        },
    )
    assert r.status_code == 200
    assert "Invalid recovery code" in r.text


# --- feature flag dark-mount -------------------------------------------------


def test_feature_flag_off_404s_signup(client: TestClient) -> None:
    """HYRULE_WEB_ENABLE_AUTH_UI=false: every auth route returns 404. The
    backend can still serve /v1/auth/* directly to agents and external
    callers; only the browser-facing surface is dark."""
    settings.enable_auth_ui = False
    try:
        for path in ("/signup", "/login", "/recover", "/dashboard"):
            r = client.get(path, follow_redirects=False)
            assert r.status_code == 404, f"{path} should 404 under flag-off"
        for path, data in (
            ("/signup", {"password": "x" * 12, "password_confirm": "x" * 12}),
            ("/login", {"account_id": "ACCT_X", "password": "x" * 12}),
            ("/logout", {}),
        ):
            r = client.post(path, data=data, follow_redirects=False)
            assert r.status_code == 404, f"POST {path} should 404 under flag-off"
    finally:
        settings.enable_auth_ui = True


# --- dashboard actions -------------------------------------------------------


def test_dashboard_reboot_proxies_and_redirects(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: POST /dashboard/vms/{id}/reboot proxies to /v1/vm/{id}/reboot
    with the session cookie forwarded, then 303s back to /dashboard."""
    route = mocked_api.post("/v1/vm/vm-x/reboot").mock(return_value=httpx.Response(200))
    r = client.post(
        "/dashboard/vms/vm-x/reboot",
        headers={"Cookie": "hyr_sess=abc"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert route.called
    assert "hyr_sess=abc" in route.calls.last.request.headers.get("cookie", "")


def test_dashboard_destroy_proxies_and_redirects(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    route = mocked_api.delete("/v1/vm/vm-x").mock(return_value=httpx.Response(200))
    r = client.post(
        "/dashboard/vms/vm-x/destroy",
        headers={"Cookie": "hyr_sess=abc"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert route.called


def test_dashboard_claim_proxies_and_redirects(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A1: claim posts {token} to /v1/me/vms/{id}/claim."""
    route = mocked_api.post("/v1/me/vms/vm-x/claim").mock(return_value=httpx.Response(200))
    r = client.post(
        "/dashboard/claim",
        data={"vm_id": "vm-x", "token": "hyr_vm_aaaaa"},
        headers={"Cookie": "hyr_sess=abc"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert route.called
    body = route.calls.last.request.read()
    assert b"hyr_vm_aaaaa" in body
