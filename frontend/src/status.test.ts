import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initStatus, renderStatus } from "./status";
import type { VmStatus } from "./types";

function makeVm(status: VmStatus["status"], extra: Partial<VmStatus> = {}): VmStatus {
  return { status, ...extra };
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

  it("renders provisioned with FQDN, IPv6, and SSH command", () => {
    const html = renderStatus(
      makeVm("provisioned", { fqdn: "vm-abc.deploy.hyrule.host", ipv6: "2a0c:b641::1" }),
    );
    expect(html).toContain("PROVISIONED");
    expect(html).toContain("vm-abc.deploy.hyrule.host");
    expect(html).toContain("2a0c:b641::1");
    expect(html).toContain("ssh root@vm-abc.deploy.hyrule.host");
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
});

describe("initStatus", () => {
  it("disables htmx attributes on the card", () => {
    const card = document.getElementById("status-card")!;
    card.setAttribute("hx-get", "/old");
    card.setAttribute("hx-trigger", "every 2s");
    card.setAttribute("hx-swap", "outerHTML");
    initStatus(card);
    expect(card.getAttribute("hx-disable")).toBe("true");
    expect(card.hasAttribute("hx-get")).toBe(false);
    expect(card.hasAttribute("hx-trigger")).toBe(false);
    expect(card.hasAttribute("hx-swap")).toBe(false);
  });

  it("polls the API and renders the returned status", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("provisioned", { fqdn: "test.host", ipv6: "::1" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/vm/vm-test/status");
    expect(card.innerHTML).toContain("PROVISIONED");
    expect(card.innerHTML).toContain("test.host");
  });

  it("stops polling once the VM reaches a terminal state", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeVm("provisioned", { fqdn: "t.host" }),
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
      json: async () => makeVm("provisioned", { fqdn: "copy.test", ipv6: "::1" }),
    });
    vi.stubGlobal("fetch", mockFetch);
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const card = document.getElementById("status-card")!;
    initStatus(card);

    await vi.advanceTimersByTimeAsync(100);
    const btn = card.querySelector<HTMLElement>("[data-copy='copy.test']")!;
    btn.click();
    expect(writeText).toHaveBeenCalledWith("copy.test");
  });
});
