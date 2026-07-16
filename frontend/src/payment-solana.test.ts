import { describe, expect, it } from "vitest";

import { compatibleSolanaWallets, validateSolanaQuote } from "./payment-solana";
import type { PaymentNetwork } from "./types";
import type { X402Quote } from "./x402";

const chain = "solana:mainnet";
const receiver = "9xQeWvG816bUx9EPfEZRzHLrqvRQmkmSBmGE4kc9x9C";
const mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

const network: PaymentNetwork = {
  key: "solana",
  family: "svm",
  display_name: "Solana",
  asset: "USDC",
  caip2: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
  chain_id: null,
  token_address: mint,
  token_decimals: 6,
  wallet_chain: chain,
  pay_to: receiver,
  rpc_url: "https://api.mainnet-beta.solana.com",
};

function quote(overrides: Record<string, unknown> = {}): X402Quote {
  const accept = {
    scheme: "exact",
    network: network.caip2!,
    amount: "1250000",
    asset: mint,
    payTo: receiver,
    maxTimeoutSeconds: 300,
    extra: { feePayer: "Vote111111111111111111111111111111111111111" },
    ...overrides,
  };
  return {
    request: { url: "/api/vm/create", method: "POST", body: "{}" },
    requirements: {
      x402Version: 2,
      resource: { url: "https://cloud.hyrule.host/v1/vm/create" },
      accepts: [accept],
    },
    accept,
  };
}

describe("validateSolanaQuote", () => {
  it("accepts an exact facilitator-enriched Solana USDC quote", () => {
    expect(() => validateSolanaQuote(quote(), network)).not.toThrow();
  });

  it("rejects network, mint, recipient, and fee-payer substitution", () => {
    expect(() => validateSolanaQuote(quote({ network: "solana:devnet" }), network)).toThrow(
      /network/,
    );
    expect(() => validateSolanaQuote(quote({ asset: receiver }), network)).toThrow(/mint/);
    expect(() => validateSolanaQuote(quote({ payTo: mint }), network)).toThrow(/recipient/);
    expect(() =>
      validateSolanaQuote(quote({ extra: { feePayer: "not-base58" } }), network),
    ).toThrow(/fee payer/);
  });
});

describe("compatibleSolanaWallets", () => {
  function wallet(name: string, accounts: number, chains = [chain]) {
    return {
      version: "1.0.0",
      name,
      icon: "data:image/png;base64,AA==",
      chains,
      accounts: Array.from({ length: accounts }, () => ({
        address: receiver,
        publicKey: new Uint8Array(32),
        chains: [chain],
        features: ["solana:signTransaction"],
      })),
      features: {
        "standard:connect": { version: "1.0.0", connect: async () => ({ accounts: [] }) },
        "solana:signTransaction": {
          version: "1.0.0",
          supportedTransactionVersions: ["legacy", 0],
          signTransaction: async () => [],
        },
      },
    } as never;
  }

  it("prefers an already-authorized compatible wallet and filters other chains", () => {
    const wallets = [
      wallet("Alpha", 0),
      wallet("Zulu", 1),
      wallet("Other", 1, ["eip155:1"]),
    ] as const;
    expect(compatibleSolanaWallets(chain, wallets).map((candidate) => candidate.name)).toEqual([
      "Zulu",
      "Alpha",
    ]);
  });
});
