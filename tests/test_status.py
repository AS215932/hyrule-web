"""The durable /order/status/{vm_id} page renders across every VM state.

Block A0 (2026-05-18): the upstream API now serves the sanitized status
shape at `/v1/vm/{id}/status` (the legacy `/v1/vm/{id}` is management-
gated). The fixtures + URL patterns below were updated accordingly. Plus
a new test covers the post-order management-URL banner.

Issue #26 (2026-06-16): launch-proof contract states — payment_required,
provisioning, provisioned, failed, rolled_back.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

# These fixtures mirror the REAL GET /v1/vm/{id}/status contract
# (VMPublicStatusResponse). They previously used `status: "provisioned"` and
# `fqdn`, neither of which the API ever emits — so the suite passed while
# production sat on "Building your VM." forever. `status` is VMStatus
# (provisioning|ready|running|suspended|failed|destroyed); the launch-proof
# words live in `launch_proof_status`; the host field is `hostname`.
_VM_PROVISIONED = {
    "status": "ready",
    "launch_proof_status": "provisioned",
    "hostname": "test.deploy.hyrule.host",
    "ipv6": "2a0c:b641::1",
}

# A VM that has been running a while: `status` moves on to "running" and must
# still display as provisioned.
_VM_RUNNING = {
    "status": "running",
    "launch_proof_status": "provisioned",
    "hostname": "test.deploy.hyrule.host",
    "ipv6": "2a0c:b641::1",
}

# Older API builds omit launch_proof_status entirely; the lifecycle status
# alone must still resolve to a terminal display state.
_VM_READY_NO_PROOF = {
    "status": "ready",
    "hostname": "test.deploy.hyrule.host",
    "ipv6": "2a0c:b641::1",
}

_VM_PROVISIONING = {
    "status": "provisioning",
    "launch_proof_status": "provisioning",
}

_VM_PAYMENT_REQUIRED = {
    "status": "provisioning",
    "launch_proof_status": "payment_required",
    "payment_status": "pending",
}

_VM_FAILED = {
    "status": "failed",
    "launch_proof_status": "failed",
    "customer_message": "Disk image corrupt.",
}

# `rolled_back` exists only in the launch-proof vocabulary — VMStatus has no
# such value, so this state is reachable only via launch_proof_status.
_VM_ROLLED_BACK = {
    "status": "failed",
    "launch_proof_status": "rolled_back",
    "customer_message": "Payment timeout. Refund issued.",
    "rollback_available": True,
}


@pytest.mark.parametrize(("runtime", "expiry_state", "label", "title"), [
    ("suspended", "active", "SUSPENDED", "Your VM is suspended."),
    ("ready", "expired", "EXPIRED", "Your VM has expired."),
    ("suspended", "deletion_eligible", "GRACE PERIOD ENDED", "The grace period has ended."),
    ("failed", "deleting", "DELETION STARTED", "VM deletion has started."),
    ("destroyed", "destroyed", "DESTROYED", "Your VM is destroyed."),
])
def test_lifecycle_status_is_visible_without_javascript(
    client, mocked_api, runtime, expiry_state, label, title
):
    vm = {
        **_VM_PROVISIONED, "status": runtime, "customer_message": "Your VM is ready.",
        "expires_at": "2026-09-08T12:00:00+02:00",
        "expiry": {"state": expiry_state, "grace_ends_at": "2026-09-10T10:00:00Z"},
    }
    mocked_api.get("/v1/vm/vm-abc/status").mock(return_value=httpx.Response(200, json=vm))
    response = client.get("/order/status/vm-abc")
    assert response.status_code == 200
    assert label in response.text and title in response.text
    assert "2026-09-08 10:00 UTC" in response.text
    if expiry_state in ("deleting", "destroyed"):
        assert "Grace period ends" not in response.text
    else:
        assert "2026-09-10 10:00 UTC" in response.text
    assert "Your VM is online." not in response.text
    assert "Your VM is ready." not in response.text
    assert "ssh root@test.deploy.hyrule.host" not in response.text
    assert "support@hyrule.host" in response.text
    assert 'id="status-connections"' in response.text
    assert 'hidden style="display: none"' in response.text


def test_expiry_dates_do_not_invent_deadlines_or_render_invalid_input():
    from hyrule_web.app import vm_expiry_dates

    assert vm_expiry_dates(None) == {"expires_at": None, "grace_ends_at": None}
    assert vm_expiry_dates({"expires_at": "2026-09-08T10:00:00"}) == {
        "expires_at": "2026-09-08 10:00 UTC", "grace_ends_at": None,
    }
    assert vm_expiry_dates({"expires_at": "not a date", "expiry": "invalid"}) == {
        "expires_at": "Unavailable", "grace_ends_at": None,
    }


def test_status_page_with_provisioned_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONED)
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "PROVISIONED" in r.text
    assert "ssh root@test.deploy.hyrule.host" in r.text


def test_status_page_with_provisioning_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONING)
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "PROVISIONING" in r.text
    assert "progress-bar" in r.text


def test_status_page_with_payment_required(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PAYMENT_REQUIRED)
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "PAYMENT REQUIRED" in r.text
    assert "Pay now" in r.text


def test_status_page_with_failed_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_FAILED)
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "FAILED" in r.text
    assert "Disk image corrupt" in r.text
    assert "support@hyrule.host" in r.text


def test_status_page_with_rolled_back_vm(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_ROLLED_BACK)
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "ROLLED BACK" in r.text
    assert "Payment timeout" in r.text
    assert "support@hyrule.host" in r.text


def test_status_page_with_missing_vm_renders_anyway(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-missing/status").mock(return_value=httpx.Response(404))
    r = client.get("/order/status/vm-missing")
    assert r.status_code == 200  # template handles vm=None


def test_status_page_with_backend_error(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-err/status").mock(side_effect=httpx.ConnectError("boom"))
    r = client.get("/order/status/vm-err")
    assert r.status_code == 200


# --- Block A0 management-token banner ---


def test_status_page_renders_management_banner_when_token_query_present(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """When the post-order redirect carries ?token=hyr_vm_..., the status
    page renders the save-once banner containing the bare token — not a
    URL. The API's own management_url is built from its request base_url,
    which behind the proxy is the internal overlay address, so no URL is
    surfaced to the buyer at all."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONED),
    )
    r = client.get(
        "/order/status/vm-abc?token=hyr_vm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        headers={"host": "www.example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "save once" in body.lower()
    # The banner offers a copy button + download link.
    assert "download" in body.lower()
    assert "hyr_vm_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in body
    # The credential is the token alone: no endpoint URL is rendered.
    assert "/v1/vm/vm-abc?token=" not in body
    assert "cloud.example.com" not in body


def test_status_page_never_leaks_the_internal_api_address(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Regression: the banner used to render the API's management_url,
    which behind the proxy resolves to the internal overlay address and
    port. A buyer must never see infrastructure detail."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(
            200,
            json={
                **_VM_PROVISIONED,
                "management_url": "http://[2a0c:b641:b50:2::20]:8402/v1/vm/vm-abc?token=hyr_vm_x",
            },
        ),
    )
    r = client.get("/order/status/vm-abc?token=hyr_vm_cccccccccccccccccccccccccccccccc")
    assert r.status_code == 200
    # The VM's own IPv6 is shown legitimately, so assert on the API's
    # internal overlay endpoint specifically, not the shared /48 prefix.
    assert "2a0c:b641:b50:2::20" not in r.text
    assert ":8402" not in r.text
    assert "management_url" not in r.text


def test_status_page_renders_management_banner_even_when_api_404s(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: a transient API outage (or eventual-consistency gap)
    between order success and the redirect must not eat the one-time
    management URL. The banner must render even when /status returns
    404 — it's the user's only chance to capture the token."""
    mocked_api.get("/v1/vm/vm-late/status").mock(
        return_value=httpx.Response(404),
    )
    r = client.get(
        "/order/status/vm-late?token=hyr_vm_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    assert r.status_code == 200
    body = r.text
    assert "save once" in body.lower()
    assert "hyr_vm_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in body


def test_status_page_no_banner_without_token(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: the banner only renders when ?token= is present. A
    regular status check (e.g. polled later, or shared link) must NOT
    leak any management hint."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONED),
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert "save this once" not in r.text.lower()


def test_status_page_session_storage_fallback_uses_same_origin_api_proxy(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONED),
    )
    r = client.get("/order/status/vm-abc")
    assert r.status_code == 200
    assert 'data-vm-id="vm-abc"' in r.text
    assert "/assets/status-" in r.text
    assert "data-management-token=" not in r.text


def test_status_page_ignores_malformed_token_query(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Block A0: ?token= must start with `hyr_vm_` to be surfaced. Random
    junk in the query string does not cause a banner to render with that
    junk embedded."""
    mocked_api.get("/v1/vm/vm-abc/status").mock(
        return_value=httpx.Response(200, json=_VM_PROVISIONED),
    )
    r = client.get("/order/status/vm-abc?token=not-a-real-token")
    assert r.status_code == 200
    assert "save this once" not in r.text.lower()
    assert "not-a-real-token" not in r.text


# --- Status vocabulary regression (a paid, ready VM must not read as building) ---

# Captured verbatim from production for a VM that had finished provisioning
# while the page still showed "Building your VM. Most builds finish in under
# 60 seconds." Nothing here is hand-written.
_VM_LIVE_READY = {
    "vm_id": "vm_UuhXLRUdceH7d29UZERbEU",
    "status": "ready",
    "ipv6": "2a0c:b641:b51:392f::2",
    "ipv6_prefix": "2a0c:b641:b51:392f::/64",
    "hostname": "4ab37305.deploy.hyrule.host",
    "expires_at": "2026-08-20T19:56:54.374634Z",
    "profile": "md",
    "resources": {"vcpu": 2, "ram_mb": 4096, "disk_gb": 20},
    "launch_proof_status": "provisioned",
    "payment_status": "paid",
    "dns_aaaa_verified": True,
    "ssh_smoke_status": "passed",
    "dns_resolution_status": "passed",
    "rollback_available": False,
    "operator_message": None,
    "customer_message": "Your VM is ready.",
}


def test_live_ready_vm_renders_as_provisioned(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """The real production payload must render the ready card, with the
    connection details a buyer needs — not the provisioning spinner."""
    mocked_api.get("/v1/vm/vm-live/status").mock(
        return_value=httpx.Response(200, json=_VM_LIVE_READY),
    )
    r = client.get("/order/status/vm-live")
    assert r.status_code == 200
    assert "PROVISIONED" in r.text
    assert "Building your VM" not in r.text
    assert "4ab37305.deploy.hyrule.host" in r.text
    assert "ssh root@4ab37305.deploy.hyrule.host" in r.text
    assert "2a0c:b641:b51:392f::2" in r.text
    # The card must advertise a terminal state so the poller stops.
    assert 'data-status="provisioned"' in r.text


def test_running_vm_still_renders_as_provisioned(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    mocked_api.get("/v1/vm/vm-run/status").mock(
        return_value=httpx.Response(200, json=_VM_RUNNING),
    )
    r = client.get("/order/status/vm-run")
    assert r.status_code == 200
    assert "PROVISIONED" in r.text
    assert "Building your VM" not in r.text


def test_ready_without_launch_proof_status_still_resolves(
    client: TestClient, mocked_api: respx.MockRouter
) -> None:
    """Fallback path: map VMStatus when launch_proof_status is absent."""
    mocked_api.get("/v1/vm/vm-old/status").mock(
        return_value=httpx.Response(200, json=_VM_READY_NO_PROOF),
    )
    r = client.get("/order/status/vm-old")
    assert r.status_code == 200
    assert "PROVISIONED" in r.text
    assert "ssh root@test.deploy.hyrule.host" in r.text


def test_vm_display_state_mapping() -> None:
    from hyrule_web.app import vm_display_state

    # launch_proof_status wins when present.
    assert vm_display_state({"status": "ready", "launch_proof_status": "rolled_back"}) == (
        "rolled_back"
    )
    # VMStatus fallback.
    assert vm_display_state({"status": "ready"}) == "provisioned"
    assert vm_display_state({"status": "running"}) == "provisioned"
    assert vm_display_state({"status": "suspended"}) == "suspended"
    assert vm_display_state({"status": "failed"}) == "failed"
    assert vm_display_state({"status": "destroyed"}) == "destroyed"
    assert vm_display_state({"status": "provisioning"}) == "provisioning"
    # Unknown / missing payloads stay on the safe non-terminal state.
    assert vm_display_state({"status": "something_new"}) == "provisioning"
    assert vm_display_state(None) == "provisioning"
    assert vm_display_state({}) == "provisioning"
