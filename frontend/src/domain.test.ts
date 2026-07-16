import { afterEach, describe, expect, it, vi } from "vitest";

import { domainOrderPayload, setupCheckout } from "./domain";

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("domain order payload", () => {
  it("omits VM failure policy for a standalone domain order", () => {
    expect(domainOrderPayload("dq_test", "usdc", "terms-v1")).toEqual({
      quote_id: "dq_test",
      payment_method: "usdc",
      terms_version: "terms-v1",
    });
  });

  it("normalizes the required native refund address", () => {
    expect(domainOrderPayload("dq_test", "btc", "terms-v1", "  bc1qrefund  ")).toEqual({
      quote_id: "dq_test",
      payment_method: "btc",
      terms_version: "terms-v1",
      refund_address: "bc1qrefund",
    });
    expect(() => domainOrderPayload("dq_test", "xmr", "terms-v1", "  ")).toThrow(
      "A refund address is required",
    );
  });
});

describe("domain checkout controls", () => {
  it("wires native checkout before the EVM network catalog resolves", async () => {
    document.body.innerHTML = `
      <div id="domain-checkout" data-quote-id="dq_pending_catalog" data-terms-version="v1">
        <input name="domain-payment-method" type="radio" value="btc" checked>
        <div id="domain-refund-wrap" style="display:none"></div>
        <div id="domain-chain-wrap"></div>
        <input id="domain-refund-address" value="bc1qrefund">
        <input id="domain-terms" type="checkbox">
        <button id="domain-pay" type="button">Pay and place order</button>
        <div id="domain-payment-status"></div>
        <div id="domain-native-payment"></div>
      </div>
    `;
    const catalogPending = new Promise<Response>(() => undefined);
    const fetchMock = vi.fn().mockReturnValue(catalogPending);
    vi.stubGlobal("fetch", fetchMock);
    const checkout = document.getElementById("domain-checkout") as HTMLElement;

    void setupCheckout(checkout);

    expect(fetchMock).toHaveBeenCalledWith("/api/payments/networks");
    expect(document.getElementById("domain-refund-wrap")?.style.display).toBe("block");
    expect(document.getElementById("domain-chain-wrap")?.style.display).toBe("none");
    (document.getElementById("domain-pay") as HTMLButtonElement).click();
    await vi.waitFor(() => {
      expect(document.getElementById("domain-payment-status")?.textContent).toContain(
        "Accept the domain terms",
      );
    });
  });
});
