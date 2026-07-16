import { afterEach, describe, expect, it, vi } from "vitest";

import { domainOrderPayload, setupCheckout, setupTransfer } from "./domain";

afterEach(() => {
  document.body.replaceChildren();
  sessionStorage.clear();
  vi.useRealTimers();
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

describe("domain transfer retry", () => {
  it("rotates the idempotency key after a terminal failed operation", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <div id="domain-transfer" data-domain="example.dev" data-wallet="0xabc" data-chain-id="8453">
        <button id="domain-transfer-button" type="button">Transfer</button>
        <div id="domain-transfer-status"></div>
        <div id="domain-transfer-secret" class="hidden"><code></code></div>
      </div>
    `;
    const provider = {
      request: vi.fn(async ({ method }: { method: string }) => {
        if (method === "eth_requestAccounts") return ["0xAbC"];
        if (method === "personal_sign") return "0xsigned";
        throw new Error(`Unexpected wallet method: ${method}`);
      }),
    };
    vi.stubGlobal("ethereum", provider);

    let attempt = 0;
    const submittedKeys: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/challenge")) {
        return {
          ok: true,
          json: async () => ({ nonce: `nonce-${attempt + 1}`, message: "sign me" }),
        } as Response;
      }
      if (url.endsWith("/transfer-out")) {
        attempt += 1;
        submittedKeys.push((init?.headers as Record<string, string>)["Idempotency-Key"]);
        return {
          ok: true,
          json: async () => ({ operation_id: `operation-${attempt}` }),
        } as Response;
      }
      if (url.includes("/api/domains/operations/")) {
        return {
          ok: true,
          json: async () =>
            attempt === 1
              ? { status: "failed", error_detail: "Registrar rejected transfer." }
              : { status: "succeeded", secret: "auth-code" },
        } as Response;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const container = document.getElementById("domain-transfer") as HTMLElement;
    await setupTransfer(container);
    const button = document.getElementById("domain-transfer-button") as HTMLButtonElement;

    button.click();
    await vi.runAllTimersAsync();
    expect(document.getElementById("domain-transfer-status")?.textContent).toContain(
      "Registrar rejected transfer",
    );
    const rotated = sessionStorage.getItem("hyr_domain_idempotency:transfer:example.dev");
    expect(rotated).toBeTruthy();
    expect(rotated).not.toBe(submittedKeys[0]);

    button.click();
    await vi.runAllTimersAsync();
    expect(document.getElementById("domain-transfer-status")?.textContent).toContain(
      "Domain unlocked",
    );
    expect(submittedKeys).toEqual([submittedKeys[0], rotated]);
  });
});
