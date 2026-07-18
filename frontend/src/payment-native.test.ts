import { describe, expect, it } from "vitest";

import {
  gatherOrderPayload,
  intentClientOrderStorageKey,
  renderDepositCard,
  statusRedirectUrl,
} from "./payment-native";

describe("native quote binding", () => {
  it("carries the durable quote id into intent creation payloads", () => {
    const form = document.createElement("form");
    form.innerHTML = `
      <input name="os" value="debian-13">
      <input name="size" value="sm">
      <input name="duration_days" value="30">
      <input name="ssh_pubkey" value="ssh-ed25519 AAAA">
      <input name="domain_mode" value="auto">
      <input name="quote_id" value="q_locked">
      <input name="vcpu" value="3">
      <input name="ram_mb" value="5120">
      <input name="disk_gb" value="30">
    `;

    const payload = gatherOrderPayload(form);

    expect(payload.quote_id).toBe("q_locked");
    expect(payload.resources).toEqual({ vcpu: 3, ram_mb: 5120, disk_gb: 30 });
    expect(intentClientOrderStorageKey("BTC", payload)).toBe(
      "hyr_intent_client_order_id:BTC:q_locked",
    );
  });

  it("does not reuse an unquoted intent key for a later quote", () => {
    expect(intentClientOrderStorageKey("XMR", {})).toBe("hyr_intent_client_order_id:XMR:legacy");
    expect(intentClientOrderStorageKey("XMR", { quote_id: "q_next" })).not.toBe(
      "hyr_intent_client_order_id:XMR:legacy",
    );
  });
});

// Issue #8: the BTC/XMR deposit card must stay overflow-safe on narrow viewports
// (the old layout was a fixed 256px QR + a 220px min-width text column ≈ 476px).
// These assert the responsive CLASS contract, not pixel rendering (jsdom has no
// layout), and that no fixed-width inline styles linger on the skeleton.
describe("renderDepositCard responsive layout", () => {
  it("renders an overflow-safe, stacking skeleton", () => {
    const c = document.createElement("div");
    renderDepositCard(c, {
      intent_id: "int-1",
      asset: "BTC",
      address: "bc1qexamplelongdepositaddressxxxxxxxxxxxxxxxxxxxxxxxxxx",
      amount_crypto: "0.0012",
      status: "PENDING",
    });

    const qr = c.querySelector<HTMLElement>("#hyr-qr")!;
    const row = qr.parentElement!;
    const textCol = row.querySelector<HTMLElement>("div.flex-1")!;
    const addr = c.querySelector<HTMLElement>("#hyr-addr")!;

    // QR caps at the container width and stays square — no fixed 256px overflow.
    expect(qr.className).toContain("max-w-full");
    expect(qr.className).toContain("aspect-square");
    // Row stacks on mobile, goes side-by-side at the xs breakpoint.
    expect(row.className).toContain("flex-col");
    expect(row.className).toContain("xs:flex-row");
    // Text column can shrink so a long address wraps instead of widening the card.
    expect(textCol.className).toContain("min-w-0");
    expect(addr.className).toContain("break-all");
    // The fixed-width inline styles that caused the overflow are gone.
    expect(c.innerHTML).not.toContain("min-width:220px");
    expect(c.innerHTML).not.toContain("width:256px");
  });

  it("populates amount + address via textContent (XSS-safe)", () => {
    const c = document.createElement("div");
    renderDepositCard(c, {
      intent_id: "int-2",
      asset: "XMR",
      address: "4SAMPLEMONEROADDRESS",
      amount_crypto: "0.5",
      status: "PENDING",
    });
    expect(c.querySelector("#hyr-amt")!.textContent).toBe("0.5 XMR");
    expect(c.querySelector("#hyr-addr")!.textContent).toBe("4SAMPLEMONEROADDRESS");
  });

  it("keeps the one-time management token out of the status redirect URL", () => {
    expect(
      statusRedirectUrl({
        intent_id: "int-3",
        asset: "BTC",
        address: "bc1qaddr",
        amount_crypto: "0.001",
        status: "PROVISIONED",
        vm_id: "vm_abc",
        management_token: "hyr_vm_token with spaces",
      }),
    ).toBe("/order/status/vm_abc");
  });
});
