/**
 * WalletConnect provider (issue #14, Phase 4).
 *
 * Returns an EIP-1193 provider over WalletConnect so the EVM/x402 flow works on
 * mobile browsers that have no injected window.ethereum: the provider opens a
 * QR / mobile-wallet deep-link modal on connect, then exposes the same
 * `.request()` surface the injected path uses, so payment-evm.ts is unchanged
 * downstream of getEvmProvider().
 *
 * This module is loaded lazily (dynamic import from payment-evm.ts) only when
 * there's no injected wallet, so the heavy WalletConnect bundle never loads on
 * desktop or on non-checkout pages.
 *
 * The WalletConnect projectId is a PUBLIC client id (Reown dashboard), surfaced
 * via the <meta name="walletconnect-project-id"> tag rendered from backend
 * config — never a secret. Networks come from the live /api/payments/networks
 * list, never hardcoded.
 */

import type { Eip1193Provider, PaymentNetwork } from "./types";

let providerPromise: Promise<Eip1193Provider | null> | null = null;

function projectId(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="walletconnect-project-id"]');
  return meta?.content?.trim() ?? "";
}

async function enabledEvmChainIds(): Promise<number[]> {
  try {
    const resp = await fetch("/api/payments/networks");
    if (!resp.ok) return [];
    const body = await resp.json();
    const nets: PaymentNetwork[] = body.networks || [];
    return nets
      .filter(
        (network): network is PaymentNetwork & { family: "evm" } =>
          network.family === "evm" && Number.isSafeInteger(network.chain_id),
      )
      .map((network) => network.chain_id);
  } catch {
    return [];
  }
}

async function init(): Promise<Eip1193Provider | null> {
  const pid = projectId();
  if (!pid) {
    console.warn(
      "WalletConnect projectId not configured (meta walletconnect-project-id) — " +
        "mobile WalletConnect disabled.",
    );
    return null;
  }
  const chains = await enabledEvmChainIds();
  if (!chains.length) return null;

  const { EthereumProvider } = await import("@walletconnect/ethereum-provider");
  const provider = await EthereumProvider.init({
    projectId: pid,
    chains: [chains[0]], // required chain (first enabled, e.g. Base)
    optionalChains: chains as [number, ...number[]], // allow the rest
    showQrModal: true, // QR on desktop; wallet deep-links on mobile
    metadata: {
      name: "Hyrule Cloud",
      description: "IPv6-native VM provisioning on AS215932",
      url: "https://hyrule.host", // must match the production domain
      icons: ["https://hyrule.host/static/icon.png"],
    },
  });
  // Opens the modal and resolves once the user connects a wallet.
  await provider.enable();
  return provider as unknown as Eip1193Provider;
}

/** Resolve (and cache) a connected WalletConnect EIP-1193 provider, or null. */
export async function getWalletConnectProvider(): Promise<Eip1193Provider | null> {
  if (!providerPromise) {
    providerPromise = init().catch((err) => {
      providerPromise = null; // allow a retry on the next attempt
      console.error("WalletConnect init failed", err);
      return null;
    });
  }
  return providerPromise;
}
