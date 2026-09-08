import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { displayState, initManagementAccess, initStatus, renderStatus } from "./status";
import type { LaunchProofStatus, VmStatus } from "./types";

// The launch-proof words belong on `launch_proof_status`. They are NOT valid
// values of `status`, which carries VMStatus — conflating the two is what left
// finished VMs rendering the provisioning spinner forever.
function makeVm(state: LaunchProofStatus, extra: Partial<VmStatus> = {}): VmStatus {
  return { launch_proof_status: state, ...extra };
}

beforeEach(() => {
  document.body.innerHTML = '<div id="status-card" data-vm-id="vm-test"></div>';
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("renderStatus", () => {
  it.each([
    ["suspended", "active", "SUSPENDED"],
    ["ready", "expired", "EXPIRED"],
    ["suspended", "deletion_eligible", "GRACE PERIOD ENDED"],
    ["failed", "deleting", "DELETION STARTED"],
    ["suspended", "retaining", "RETENTION PENDING"],
    ["suspended", "retained", "DATA RETAINED"],
    ["suspended", "restoring", "RECOVERY IN PROGRESS"],
    ["destroyed", "destroyed", "DESTROYED"],
  ] as const)("renders runtime %s and expiry %s truthfully", (status, expiry, label) => {
    const html = renderStatus({
      status,
      launch_proof_status: "provisioned",
      customer_message: "Your VM is ready.",
      hostname: "test.host",
      expires_at: "2026-09-08T12:00:00+02:00",
      expiry: {
        state: expiry,
        grace_ends_at: "2026-09-10T10:00:00Z",
        retained_until: "2026-10-08T10:00:00Z",
      },
    });
    expect(html).toContain(label);
    expect(html).toContain("2026-09-08 10:00 UTC");
    if (["deleting", "destroyed", "retaining", "retained", "restoring"].includes(expiry)) {
      expect(html).not.toContain("Grace period ends");
    } else {
      expect(html).toContain("2026-09-10 10:00 UTC");
    }
    if (["retaining", "retained", "restoring"].includes(expiry)) {
      expect(html).toContain("Minimum retention until");
      expect(html).toContain("2026-10-08 10:00 UTC");
      expect(html).toContain("not a scheduled deletion date");
    }
    expect(html).not.toContain("PROVISIONED");
    expect(html).not.toContain("Your VM is ready.");
    expect(html).not.toContain("ssh root@");
  });

  it("handles absent and invalid expiry dates without inventing a grace period", () => {
    expect(renderStatus({ status: "suspended" })).not.toContain("Grace period ends");
    const html = renderStatus({ status: "ready", expires_at: "invalid" });
    expect(html).toContain("Unavailable");
    expect(html).not.toContain("Grace period ends");
    expect(renderStatus({ status: "ready", expires_at: "2026-09-08T10:00:00" })).toContain(
      "2026-09-08 10:00 UTC",
    );
  });
  it("renders payment_required with pay action", () => {
    const html = renderStatus(makeVm("payment_required"));
    expect(html).toContain("PAYMENT REQUIRED");
    expect(html).toContain("Pay now");
    expect(html).toContain("Complete payment");
  });

  it("renders provisioning with progress bar", () => {
    const html = renderStatus(makeVm("provisioning"));
    expect(html).toContain("PROVISIONING");
    expect(html).toContain("progress-bar");
    expect(html).toContain("Most builds finish in under 60 seconds");
  });

  it("renders provisioned with hostname, IPv6, and SSH command", () => {
    const html = renderStatus(
      makeVm("provisioned", {
        hostname: "vm-abc.deploy.hyrule.host",
        ipv6: "2a0c:b641::1",
        profile: "md",
        resources: { vcpu: 3, ram_mb: 5120, disk_gb: 30 },
      }),
    );
    expect(html).toContain("PROVISIONED");
    expect(html).toContain("vm-abc.deploy.hyrule.host");
    expect(html).toContain("2a0c:b641::1");
    expect(html).toContain("ssh root@vm-abc.deploy.hyrule.host");
    expect(html).toContain("3C / 5G RAM / 30G SSD");
    expect(html).toContain("copy");
  });

  it("renders provisioned with fallbacks when fields are missing", () => {
    const html = renderStatus(makeVm("provisioned"));
    expect(html).toContain("PROVISIONED");
    expect(html).toContain("—");
  });

  it("renders failed with customer-safe message and support contact", () => {
    const html = renderStatus(makeVm("failed", { customer_message: "Disk image corrupt." }));
    expect(html).toContain("FAILED");
    expect(html).toContain("Disk image corrupt");
    expect(html).toContain("support@hyrule.host");
  });

  it("renders failed with default message when customer_message is absent", () => {
    const html = renderStatus(makeVm("failed"));
    expect(html).toContain("FAILED");
    expect(html).toContain("Something went wrong");
  });

  it("renders rolled_back with refund copy", () => {
    const html = renderStatus(
      makeVm("rolled_back", { customer_message: "Payment timeout. Refund issued." }),
    );
    expect(html).toContain("ROLLED BACK");
    expect(html).toContain("Payment timeout");
    expect(html).toContain("support@hyrule.host");
  });

  it("renders rolled_back with default message when customer_message is absent", () => {
    const html = renderStatus(makeVm("rolled_back"));
    expect(html).toContain("ROLLED BACK");
    expect(html).toContain("rolled back");
  });

  it("falls back to provisioning for unknown status values", () => {
    const html = renderStatus({ status: "unknown" as VmStatus["status"] });
    expect(html).toContain("PROVISIONING");
  });

  // Regression: a paid VM finished provisioning and the API reported
  // status:"ready", which matched no case and rendered the spinner forever.
  it("renders a live ready VM as provisioned, not as building", () => {
    const html = renderStatus({
      status: "ready",
      launch_proof_status: "provisioned",
      hostname: "4ab37305.deploy.hyrule.host",
      ipv6: "2a0c:b641:b51:392f::2",
    });
    expect(html).toContain("PROVISIONED");
    expect(html).not.toContain("Most builds finish in under 60 seconds");
    expect(html).toContain("ssh root@4ab37305.deploy.hyrule.host");
    expect(html).toContain("2a0c:b641:b51:392f::2");
  });

  it("renders a ready VM even when launch_proof_status is absent", () => {
    const html = renderStatus({ status: "ready", hostname: "h.deploy.hyrule.host" });
    expect(html).toContain("PROVISIONED");
    expect(html).toContain("ssh root@h.deploy.hyrule.host");
  });
});

describe("displayState", () => {
  it("prefers launch_proof_status over the lifecycle status", () => {
    expect(displayState({ status: "ready", launch_proof_status: "rolled_back" })).toBe(
      "rolled_back",
    );
  });

  it("maps every VMStatus value to a display state", () => {
    expect(displayState({ status: "ready" })).toBe("provisioned");
    expect(displayState({ status: "running" })).toBe("provisioned");
    expect(displayState({ status: "suspended" })).toBe("suspended");
    expect(displayState({ status: "failed" })).toBe("failed");
    expect(displayState({ status: "destroyed" })).toBe("destroyed");
    expect(displayState({ status: "provisioning" })).toBe("provisioning");
  });

  it("stays on the non-terminal state for unknown or empty payloads", () => {
    expect(displayState({})).toBe("provisioning");
    expect(displayState({ status: "surprise" as VmStatus["status"] })).toBe("provisioning");
  });
});

describe("initStatus", () => {
  it("polls active recovery quickly and hides connections until the VM is ready", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<span class="stp"><span class="num">4</span><span data-status-step></span></span><div id="status-connections" hidden></div>',
    );
    const states: VmStatus[] = [
      { status: "suspended", expiry: { state: "retaining" } },
      { status: "suspended", expiry: { state: "restoring" } },
      { status: "suspended", expiry: { state: "retained" } },
      { status: "ready", hostname: "recovered.hyrule.host", expiry: { state: "active" } },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => ({ ok: true, json: async () => states.shift() })),
    );
    const stop = initStatus(document.getElementById("status-card")!);
    await vi.advanceTimersByTimeAsync(100);
    expect(document.querySelector("[data-status-step]")?.textContent).toBe("retaining");
    expect(document.querySelector(".stp")?.classList.contains("active")).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(document.querySelector("[data-status-step]")?.textContent).toBe("restoring");
    expect(document.getElementById("status-connections")?.textContent).not.toContain("ssh root@");
    await vi.advanceTimersByTimeAsync(2000);
    expect(document.querySelector("[data-status-step]")?.textContent).toBe("retained");
    expect(document.getElementById("status-connections")?.textContent).not.toContain("ssh root@");
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.getElementById("status-connections")?.textContent).toContain(
      "ssh root@recovered.hyrule.host",
    );
    stop();
  });

  it("restores initially empty connections on renewal and updates the whole stepper", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<span class="stp done"><span class="num">✓</span><span data-status-step>expired</span></span><div id="status-connections" hidden style="display: none"></div>',
    );
    const states: VmStatus[] = [
      { status: "suspended", expiry: { state: "expired" } },
      { status: "ready", hostname: "renewed.deploy.hyrule.host", expiry: { state: "active" } },
      { status: "suspended", expiry: { state: "deletion_eligible" } },
      { status: "suspended", expiry: { state: "deleting" } },
      { status: "destroyed" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => ({ ok: true, json: async () => states.shift() })),
    );
    initStatus(document.getElementById("status-card")!);
    await vi.advanceTimersByTimeAsync(100);
    expect(document.getElementById("status-connections")?.innerHTML).toBe("");
    await vi.advanceTimersByTimeAsync(60000);
    const details = document.getElementById("status-connections")!;
    expect(details.hidden).toBe(false);
    expect(details.textContent).toContain("ssh root@renewed.deploy.hyrule.host");
    expect(document.querySelector("[data-status-step]")?.textContent).toBe("running");
    await vi.advanceTimersByTimeAsync(60000);
    expect(details.hidden).toBe(true);
    expect(details.innerHTML).toBe("");
    expect(document.querySelector(".stp")?.classList.contains("done")).toBe(true);
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector(".stp")?.classList.contains("active")).toBe(true);
    expect(document.querySelector(".num")?.textContent).toBe("4");
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector(".stp")?.classList.contains("done")).toBe(true);
    expect(document.querySelector(".stp")?.classList.contains("active")).toBe(false);
    expect(document.querySelector(".num")?.textContent).toBe("✓");
  });
  it("refreshes an open provisioned page through expiry, renewal and destruction", async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<h1 data-status-title>Your VM is online.</h1><p data-status-blurb></p><span data-status-step>running</span><div id="status-connections">SSH online</div>',
    );
    const states: VmStatus[] = [
      { status: "ready", launch_proof_status: "provisioned" },
      { status: "suspended", launch_proof_status: "provisioned", expiry: { state: "expired" } },
      { status: "ready", launch_proof_status: "provisioned", expiry: { state: "active" } },
      { status: "destroyed", launch_proof_status: "provisioned" },
    ];
    const fetcher = vi
      .fn()
      .mockImplementation(async () => ({ ok: true, json: async () => states.shift() }));
    vi.stubGlobal("fetch", fetcher);
    const stop = initStatus(document.getElementById("status-card")!);
    await vi.advanceTimersByTimeAsync(100);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector("[data-status-title]")?.textContent).toContain("expired");
    expect(document.getElementById("status-connections")?.hidden).toBe(true);
    expect(document.querySelector("[data-status-step]")?.textContent).toBe("expired");
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector("[data-status-title]")?.textContent).toContain("online");
    expect(document.getElementById("status-connections")?.hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(60000);
    expect(document.querySelector("[data-status-title]")?.textContent).toContain("destroyed");
    expect(document.getElementById("status-connections")?.hidden).toBe(true);
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetcher).toHaveBeenCalledTimes(4);
    stop();
  });
  it("polls the API and renders the returned status", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("provisioned", { hostname: "test.host", ipv6: "::1" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/vm/vm-test/status");
    const rendered = document.getElementById("status-card")!;
    expect(rendered.innerHTML).toContain("PROVISIONED");
    expect(rendered.innerHTML).toContain("test.host");
  });

  it("stops polling once the VM reaches a terminal state", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("failed", { hostname: "t.host" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // After 10s the timer should not fire again.
    await vi.advanceTimersByTimeAsync(10000);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("continues polling while the VM is still provisioning", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("provisioning"),
    });
    vi.stubGlobal("fetch", mockFetch);

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2500);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("handles network errors gracefully and retries", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("network down"));
    vi.stubGlobal("fetch", mockFetch);

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    expect(mockFetch).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2500);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("does not poll when vm-id is missing", () => {
    const card = document.getElementById("status-card")!;
    card.removeAttribute("data-vm-id");
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
    initStatus(card);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("copies text to clipboard when copy buttons are clicked", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("provisioned", { hostname: "copy.test", ipv6: "::1" }),
    });
    vi.stubGlobal("fetch", mockFetch);
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    const btn = document.querySelector<HTMLElement>("[data-copy='copy.test']")!;
    btn.click();
    expect(writeText).toHaveBeenCalledWith("copy.test");
  });
});

describe("initManagementAccess", () => {
  it("restores a save-once management credential from session storage", () => {
    document.body.innerHTML = '<section id="management-access" data-vm-id="vm-test"></section>';
    sessionStorage.setItem("hyr_vm_mgmt:vm-test", JSON.stringify({ token: "hyr_vm_secret" }));

    initManagementAccess();

    expect(document.body.textContent).toContain("VM management token");
    expect(document.body.textContent).toContain("hyr_vm_secret");
    sessionStorage.clear();
  });

  it("shows the bare token and never a URL, even if a stale url was stashed", () => {
    document.body.innerHTML = '<section id="management-access" data-vm-id="vm-test"></section>';
    // Bundles cached from before the token-only change stashed the API's
    // management_url, which carries the internal overlay address.
    sessionStorage.setItem(
      "hyr_vm_mgmt:vm-test",
      JSON.stringify({
        token: "hyr_vm_secret",
        url: "http://[2a0c:b641:b50:2::20]:8402/v1/vm/vm-test?token=hyr_vm_secret",
      }),
    );

    initManagementAccess();

    const rendered = document.body.textContent ?? "";
    expect(rendered).toContain("hyr_vm_secret");
    expect(rendered).not.toContain("2a0c:b641");
    expect(rendered).not.toContain("8402");
    expect(rendered).not.toContain("/v1/vm/");
    sessionStorage.clear();
  });

  it("renders the server-provided token from the dataset", () => {
    document.body.innerHTML =
      '<section id="management-access" data-vm-id="vm-test" data-management-token="hyr_vm_from_server"></section>';

    initManagementAccess();

    expect(document.body.textContent).toContain("hyr_vm_from_server");
    sessionStorage.clear();
  });
});
