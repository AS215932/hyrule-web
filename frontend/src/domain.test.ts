import { describe, expect, it } from "vitest";

import { domainOrderPayload } from "./domain";

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
