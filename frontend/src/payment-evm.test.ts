import { afterEach, describe, expect, it, vi } from "vitest";

import { buildTypedData, getEvmProvider, nonceHex32 } from "./payment-evm";
import type { Eip1193Provider, PaymentNetwork } from "./types";

const network: PaymentNetwork = {
  key: "base",
  family: "evm",
  display_name: "Base",
  asset: "USDC",
  caip2: "eip155:8453",
  chain_id: 8453,
  token_address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  token_decimals: 6,
  eip712_domain: { name: "USD Coin", version: "2" },
};

describe("buildTypedData", () => {
  const td = buildTypedData(network, "0xFROM", "0xTO", 1_500_000, "100", "200", "0xNONCE");

  it("uses the TransferWithAuthorization primary type", () => {
    expect(td.primaryType).toBe("TransferWithAuthorization");
  });

  it("binds the domain to the chain + USDC contract", () => {
    expect(td.domain).toEqual({
      name: "USD Coin",
      version: "2",
      chainId: 8453,
      verifyingContract: network.token_address,
    });
  });

  it("serialises the authorization message with string amounts", () => {
    expect(td.message).toEqual({
      from: "0xFROM",
      to: "0xTO",
      value: "1500000",
      validAfter: "100",
      validBefore: "200",
      nonce: "0xNONCE",
    });
  });

  it("declares the EIP-3009 field order the facilitator expects", () => {
    expect(td.types.TransferWithAuthorization?.map((f) => f.name)).toEqual([
      "from",
      "to",
      "value",
      "validAfter",
      "validBefore",
      "nonce",
    ]);
    expect(td.types.EIP712Domain).toBeDefined();
  });
});

describe("nonceHex32", () => {
  it("returns a 0x-prefixed 32-byte hex string", () => {
    expect(nonceHex32()).toMatch(/^0x[0-9a-f]{64}$/);
  });

  it("is random across calls", () => {
    expect(nonceHex32()).not.toBe(nonceHex32());
  });
});

// Issue #14: getEvmProvider — injected wallet wins; otherwise WalletConnect
// (lazy-loaded); otherwise null.
describe("getEvmProvider", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("returns the injected provider when window.ethereum is present", async () => {
    const injected: Eip1193Provider = { request: vi.fn() };
    vi.stubGlobal("ethereum", injected);
    await expect(getEvmProvider()).resolves.toBe(injected);
  });

  it("falls back to the lazy WalletConnect provider when no injected wallet", async () => {
    vi.stubGlobal("ethereum", undefined);
    const wc: Eip1193Provider = { request: vi.fn() };
    vi.doMock("./walletconnect", () => ({ getWalletConnectProvider: async () => wc }));
    // Re-import so the dynamic import() resolves the mocked module.
    const mod = await import("./payment-evm");
    await expect(mod.getEvmProvider()).resolves.toBe(wc);
  });

  it("returns null when neither injected nor WalletConnect is available", async () => {
    vi.stubGlobal("ethereum", undefined);
    vi.doMock("./walletconnect", () => ({ getWalletConnectProvider: async () => null }));
    const mod = await import("./payment-evm");
    await expect(mod.getEvmProvider()).resolves.toBeNull();
  });
});
