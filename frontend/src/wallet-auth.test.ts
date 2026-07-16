import { afterEach, describe, expect, it, vi } from "vitest";

import { personalMessageHex, resolveWalletAuthChain, signWalletMessage } from "./wallet-auth";
import type { Eip1193Provider, PaymentNetwork } from "./types";

const base: PaymentNetwork = {
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

const polygon: PaymentNetwork = {
  ...base,
  key: "polygon",
  display_name: "Polygon",
  caip2: "eip155:137",
  chain_id: 137,
  token_address: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
};

afterEach(() => {
  document.body.replaceChildren();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
  vi.resetModules();
  vi.restoreAllMocks();
});

describe("wallet authentication chain selection", () => {
  it("keeps an active chain that the live catalog supports", async () => {
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_chainId") return "0x89";
      throw new Error(`Unexpected wallet method: ${method}`);
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ networks: [base, polygon] }) })),
    );

    await expect(resolveWalletAuthChain({ request } as Eip1193Provider)).resolves.toBe(137);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("switches Phantom from Ethereum to the first enabled authentication chain", async () => {
    let selectedChain = 1;
    const request = vi.fn(
      async ({
        method,
        params,
      }: {
        method: string;
        params?: unknown[] | Record<string, unknown>;
      }) => {
        if (method === "eth_chainId") return `0x${selectedChain.toString(16)}`;
        if (method === "wallet_switchEthereumChain") {
          selectedChain = Number.parseInt(
            String((params as { chainId: string }[])[0]?.chainId),
            16,
          );
          return null;
        }
        throw new Error(`Unexpected wallet method: ${method}`);
      },
    );
    const onSwitch = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ networks: [base, polygon] }) })),
    );

    await expect(resolveWalletAuthChain({ request } as Eip1193Provider, onSwitch)).resolves.toBe(
      8453,
    );
    expect(onSwitch).toHaveBeenCalledWith(base);
    expect(request).toHaveBeenCalledWith({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: "0x2105" }],
    });
  });

  it("adds an enabled chain when a wallet does not know it yet", async () => {
    const addableBase = {
      ...base,
      rpc_url: "https://mainnet.base.org",
      block_explorer_url: "https://basescan.org",
      native_currency: { name: "Ether", symbol: "ETH", decimals: 18 },
    };
    let selectedChain = 1;
    let switchAttempts = 0;
    const unknownChain = Object.assign(new Error("unknown chain"), { code: 4902 });
    const request = vi.fn(
      async ({
        method,
        params,
      }: {
        method: string;
        params?: unknown[] | Record<string, unknown>;
      }) => {
        if (method === "eth_chainId") return `0x${selectedChain.toString(16)}`;
        if (method === "wallet_switchEthereumChain") {
          switchAttempts += 1;
          if (switchAttempts === 1) throw unknownChain;
          selectedChain = Number.parseInt(
            String((params as { chainId: string }[])[0]?.chainId),
            16,
          );
          return null;
        }
        if (method === "wallet_addEthereumChain") return null;
        throw new Error(`Unexpected wallet method: ${method}`);
      },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ networks: [addableBase] }) })),
    );

    await expect(resolveWalletAuthChain({ request } as Eip1193Provider)).resolves.toBe(8453);
    expect(request).toHaveBeenCalledWith({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: "0x2105",
          chainName: "Base",
          nativeCurrency: addableBase.native_currency,
          rpcUrls: [addableBase.rpc_url],
          blockExplorerUrls: [addableBase.block_explorer_url],
        },
      ],
    });
    expect(request.mock.calls.map(([call]) => call.method)).toEqual([
      "eth_chainId",
      "wallet_switchEthereumChain",
      "wallet_addEthereumChain",
      "wallet_switchEthereumChain",
      "eth_chainId",
    ]);
  });

  it("fails clearly instead of adding a chain without an RPC URL", async () => {
    const unknownChain = Object.assign(new Error("unknown chain"), { code: 4902 });
    const request = vi.fn(async ({ method }: { method: string }) => {
      if (method === "eth_chainId") return "0x1";
      if (method === "wallet_switchEthereumChain") throw unknownChain;
      throw new Error(`Unexpected wallet method: ${method}`);
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ networks: [base] }) })),
    );

    await expect(resolveWalletAuthChain({ request } as Eip1193Provider)).rejects.toThrow(
      "Could not switch this wallet to an enabled chain: Cannot add Base: no RPC URL is configured.",
    );
    expect(request).not.toHaveBeenCalledWith(
      expect.objectContaining({ method: "wallet_addEthereumChain" }),
    );
  });

  it("fails clearly when the backend has no enabled EVM chains", async () => {
    const provider = {
      request: vi.fn(async () => "0x1"),
    } as Eip1193Provider;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ networks: [] }) })),
    );

    await expect(resolveWalletAuthChain(provider)).rejects.toThrow(
      "No EVM wallet chains are currently enabled.",
    );
  });
});

describe("wallet authentication signatures", () => {
  it("encodes the UTF-8 challenge as standard personal_sign hex", () => {
    expect(personalMessageHex("Hyrule ✓")).toBe("0x487972756c6520e29c93");
  });

  it("sends the encoded challenge to the wallet", async () => {
    const request = vi.fn(async () => "0xsignature");

    await expect(
      signWalletMessage({ request } as Eip1193Provider, "0xabc", "Sign in"),
    ).resolves.toBe("0xsignature");
    expect(request).toHaveBeenCalledWith({
      method: "personal_sign",
      params: ["0x5369676e20696e", "0xabc"],
    });
  });

  it("retains the reversed-parameter fallback for legacy providers", async () => {
    const request = vi
      .fn()
      .mockRejectedValueOnce(new Error("unsupported parameter order"))
      .mockResolvedValueOnce("0xsignature");

    await expect(
      signWalletMessage({ request } as Eip1193Provider, "0xabc", "Sign in"),
    ).resolves.toBe("0xsignature");
    expect(request).toHaveBeenLastCalledWith({
      method: "personal_sign",
      params: ["0xabc", "0x5369676e20696e"],
    });
  });
});

describe("wallet login", () => {
  it("switches an unsupported Phantom chain before requesting the challenge", async () => {
    document.body.innerHTML = `
      <button id="wallet-login" data-next="#signed-in">Sign in with wallet</button>
      <div id="wallet-auth-status"></div>
    `;
    const address = "0x1234567890123456789012345678901234567890";
    let selectedChain = 1;
    const walletRequest = vi.fn(
      async ({ method }: { method: string; params?: unknown[] | Record<string, unknown> }) => {
        if (method === "eth_requestAccounts") return [address];
        if (method === "eth_chainId") return `0x${selectedChain.toString(16)}`;
        if (method === "wallet_switchEthereumChain") {
          selectedChain = base.chain_id;
          return null;
        }
        if (method === "personal_sign") return "0xsignature";
        throw new Error(`Unexpected wallet method: ${method}`);
      },
    );
    vi.stubGlobal("ethereum", { request: walletRequest });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/payments/networks") {
        return { ok: true, json: async () => ({ networks: [base, polygon] }) } as Response;
      }
      if (url === "/api/auth/wallet/challenge") {
        return {
          ok: true,
          json: async () => ({ nonce: "nonce", message: "Sign in", expires_at: "later" }),
        } as Response;
      }
      if (url === "/api/auth/wallet/verify") {
        return { ok: true, json: async () => ({}) } as Response;
      }
      throw new Error(`Unexpected fetch: ${url} ${init?.method || "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.resetModules();
    await import("./wallet-auth");

    (document.getElementById("wallet-login") as HTMLButtonElement).click();

    await vi.waitFor(() => {
      expect(document.getElementById("wallet-auth-status")?.textContent).toBe(
        "Signed in. Redirecting…",
      );
    });
    const challengeCall = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/auth/wallet/challenge",
    );
    expect(JSON.parse(String(challengeCall?.[1]?.body))).toEqual({
      action: "login",
      address,
      chain_id: 8453,
    });
    expect(walletRequest).toHaveBeenCalledWith({
      method: "personal_sign",
      params: ["0x5369676e20696e", address],
    });
  });
});
