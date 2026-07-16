import { afterEach, describe, expect, it, vi } from "vitest";

import {
  encodeBase64Json,
  executeX402,
  humanTokenAmount,
  paymentRequirements,
  quoteX402,
  selectAcceptance,
  validateSignedPayment,
  type X402Quote,
} from "./x402";

const requirements = {
  x402Version: 2,
  accepts: [
    {
      scheme: "exact",
      network: "eip155:8453",
      amount: "1000",
      asset: "0xUSDC",
      payTo: "0xPayee",
      maxTimeoutSeconds: 300,
    },
  ],
};

const quote: X402Quote = {
  request: {
    url: "/api/dns/lookup",
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: '{"name":"example.com"}',
  },
  requirements,
  accept: requirements.accepts[0],
};

afterEach(() => vi.unstubAllGlobals());

describe("paymentRequirements", () => {
  it("reads the canonical Payment-Required header", async () => {
    const response = new Response("", {
      status: 402,
      headers: { "Payment-Required": encodeBase64Json(requirements) },
    });
    await expect(paymentRequirements(response)).resolves.toEqual(requirements);
  });

  it("supports the legacy header and JSON body", async () => {
    const legacy = new Response("", {
      status: 402,
      headers: { "X-Payment-Required": encodeBase64Json(requirements) },
    });
    await expect(paymentRequirements(legacy)).resolves.toEqual(requirements);
    await expect(
      paymentRequirements(
        new Response(JSON.stringify(requirements), {
          status: 402,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ).resolves.toEqual(requirements);
  });
});

describe("quote and replay", () => {
  it("selects only the requested enabled network", () => {
    expect(selectAcceptance(requirements, "eip155:8453").amount).toBe("1000");
    expect(() => selectAcceptance(requirements, "eip155:137")).toThrow(/does not accept/);
  });

  it("supports a configured network's CAIP-2 and legacy key identifiers", () => {
    const legacy = {
      ...requirements,
      accepts: [{ ...requirements.accepts[0], network: "base" }],
    };
    expect(selectAcceptance(legacy, ["eip155:8453", "base"]).network).toBe("base");
  });

  it("returns a request-bound quote from 402", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("", {
            status: 402,
            headers: { "Payment-Required": encodeBase64Json(requirements) },
          }),
      ),
    );
    const outcome = await quoteX402(quote.request, "eip155:8453");
    expect(outcome.kind).toBe("quote");
    if (outcome.kind === "quote") expect(outcome.quote.accept.amount).toBe("1000");
  });

  it("replays with canonical and legacy payment headers and an identical body", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await executeX402(quote, "signed-payload");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/dns/lookup",
      expect.objectContaining({
        method: "POST",
        body: '{"name":"example.com"}',
        headers: expect.objectContaining({
          "Payment-Signature": "signed-payload",
          "X-PAYMENT": "signed-payload",
        }),
      }),
    );
  });
});

describe("agent-signed payment validation", () => {
  function payment(overrides: Record<string, unknown> = {}): string {
    return encodeBase64Json({
      x402Version: 2,
      scheme: "exact",
      network: "eip155:8453",
      payload: {
        authorization: { from: "0xAgent", to: "0xPayee", value: "1000" },
        signature: "0xsig",
      },
      ...overrides,
    });
  }

  it("accepts an exact agent-owned payload without a site spend cap", () => {
    expect(() => validateSignedPayment(quote, payment())).not.toThrow();
  });

  it("rejects network, payee, and amount substitution", () => {
    expect(() => validateSignedPayment(quote, payment({ network: "eip155:137" }))).toThrow(
      /network/,
    );
    expect(() =>
      validateSignedPayment(
        quote,
        payment({
          payload: {
            authorization: { from: "0xAgent", to: "0xOther", value: "1000" },
            signature: "0xsig",
          },
        }),
      ),
    ).toThrow(/payee/);
    expect(() =>
      validateSignedPayment(
        quote,
        payment({
          payload: {
            authorization: { from: "0xAgent", to: "0xPayee", value: "999" },
            signature: "0xsig",
          },
        }),
      ),
    ).toThrow(/amount/);
  });

  it("rejects an incomplete or mismatched payment envelope", () => {
    expect(() => validateSignedPayment(quote, payment({ scheme: "upto" }))).toThrow(/scheme/);
    expect(() =>
      validateSignedPayment(
        quote,
        encodeBase64Json({
          x402Version: 2,
          scheme: "exact",
          network: "eip155:8453",
          payload: {
            authorization: { from: "0xAgent", to: "0xPayee", value: "1000" },
          },
        }),
      ),
    ).toThrow(/signature/);
  });

  it("accepts an official Solana x402 v2 transaction envelope", () => {
    const solanaAccept = {
      scheme: "exact",
      network: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
      amount: "1000",
      asset: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      payTo: "9xQeWvG816bUx9EPfEZRzHLrqvRQmkmSBmGE4kc9x9C",
      maxTimeoutSeconds: 300,
    };
    const solanaQuote: X402Quote = {
      ...quote,
      requirements: { x402Version: 2, accepts: [solanaAccept] },
      accept: solanaAccept,
    };
    const signed = encodeBase64Json({
      x402Version: 2,
      accepted: solanaAccept,
      payload: { transaction: btoa("signed-solana-transaction-payload") },
    });
    expect(() => validateSignedPayment(solanaQuote, signed)).not.toThrow();
  });
});

it("formats exact base units without floating point", () => {
  expect(humanTokenAmount("1000", 6)).toBe("0.001");
  expect(humanTokenAmount("1234500", 6)).toBe("1.2345");
});
