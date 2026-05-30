/**
 * EVM payment adapter for Hyrule Cloud (Block C / Wave 3).
 *
 * Chain-agnostic: takes a `network` config object describing the target chain
 * and signs an EIP-712 TransferWithAuthorization against the USDC contract on
 * that chain. The caller (payment.ts dispatcher) fetches the network list from
 * /v1/payments/networks and passes the chosen entry through. NEVER hardcode a
 * chain here — that's the dispatcher's job and the backend's source of truth.
 *
 * Issue #14 / Phase 1: behaviour-preserving TypeScript port of payment-evm.js.
 * Still injected-wallet only (window.ethereum); the provider abstraction +
 * WalletConnect land in Phase 4. The pure helpers (buildTypedData, nonceHex32)
 * are exported for unit tests.
 */

import type {
  Eip1193Provider,
  EvmPayOptions,
  PaymentNetwork,
  TransferWithAuthorizationTypedData,
} from "./types";

function setStatus(statusEl: HTMLElement | null, msg: string, cls?: string): void {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.className = "payment-status " + (cls || "");
}

async function ensureChain(network: PaymentNetwork, provider: Eip1193Provider): Promise<void> {
  // EIP-1193: wallet_switchEthereumChain. If the chain isn't yet known to the
  // wallet, fall back to wallet_addEthereumChain with the explorer/rpc info.
  const chainIdHex = "0x" + network.chain_id.toString(16);
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: chainIdHex }],
    });
  } catch (switchErr) {
    if ((switchErr as { code?: number }).code === 4902) {
      // Native gas token comes from the backend's /payments/networks (Polygon =
      // POL, not ETH). Fall back to ETH only for an older backend.
      const nativeCurrency = network.native_currency || {
        name: "Ether",
        symbol: "ETH",
        decimals: 18,
      };
      await provider.request({
        method: "wallet_addEthereumChain",
        params: [
          {
            chainId: chainIdHex,
            chainName: network.display_name,
            nativeCurrency,
            rpcUrls: [network.rpc_url].filter(Boolean),
            blockExplorerUrls: [network.block_explorer_url].filter(Boolean),
          },
        ],
      });
    } else {
      throw switchErr;
    }
  }
}

export function nonceHex32(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return (
    "0x" +
    Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
  );
}

export function buildTypedData(
  network: PaymentNetwork,
  from: string,
  payTo: string,
  valueUnits: number,
  validAfter: string,
  validBefore: string,
  nonce: string,
): TransferWithAuthorizationTypedData {
  return {
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" },
      ],
      TransferWithAuthorization: [
        { name: "from", type: "address" },
        { name: "to", type: "address" },
        { name: "value", type: "uint256" },
        { name: "validAfter", type: "uint256" },
        { name: "validBefore", type: "uint256" },
        { name: "nonce", type: "bytes32" },
      ],
    },
    domain: {
      name: network.eip712_domain.name,
      version: network.eip712_domain.version,
      chainId: network.chain_id,
      verifyingContract: network.token_address,
    },
    primaryType: "TransferWithAuthorization",
    message: {
      from,
      to: payTo,
      value: String(valueUnits),
      validAfter,
      validBefore,
      nonce,
    },
  };
}

/**
 * Resolve an EIP-1193 provider: the injected wallet (desktop / wallet in-app
 * browser) if present, otherwise WalletConnect (lazy-loaded — mobile), otherwise
 * null. This is the issue-#14 fix for mobile, where there is no window.ethereum.
 */
export async function getEvmProvider(): Promise<Eip1193Provider | null> {
  if (window.ethereum) return window.ethereum;
  const { getWalletConnectProvider } = await import("./walletconnect");
  return getWalletConnectProvider();
}

async function payWithEvm(opts: EvmPayOptions): Promise<void> {
  const { network, button, statusEl, orderPath, body } = opts;

  if (button) button.disabled = true;
  setStatus(statusEl, "Connecting wallet…", "payment-pending");

  try {
    const provider = await getEvmProvider();
    if (!provider) {
      setStatus(
        statusEl,
        "No wallet available. On mobile, tap Pay to connect with WalletConnect or use the " +
          "BTC/XMR tab; on desktop, install MetaMask or Rabby.",
        "payment-error",
      );
      if (button) button.disabled = false;
      return;
    }
    const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
    const from = accounts[0];

    await ensureChain(network, provider);

    // First request: 402 with payment requirements.
    setStatus(statusEl, "Requesting payment details…", "payment-pending");
    const firstResp = await fetch(orderPath, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (firstResp.status !== 402) {
      if (firstResp.ok) {
        // Some test/dev paths bypass payment — still honour management-token forwarding.
        const okResult = await firstResp.json();
        const okTok = okResult.management_token
          ? "?token=" + encodeURIComponent(okResult.management_token)
          : "";
        window.location.href = "/order/status/" + okResult.vm_id + okTok;
        return;
      }
      const errBody = await firstResp.json().catch(() => ({}));
      throw new Error(errBody.detail || errBody.error || "API error: " + firstResp.status);
    }

    const paymentHeader = firstResp.headers.get("x-payment-required");
    if (!paymentHeader) throw new Error("Missing X-PAYMENT-REQUIRED header");
    const paymentReq = JSON.parse(atob(paymentHeader));
    // Pick the accept entry that matches OUR chain — fall back to first.
    const accept =
      (paymentReq.accepts || []).find(
        (a: { network?: string }) => a.network === network.caip2 || a.network === network.key,
      ) || (paymentReq.accepts || [])[0];
    if (!accept) throw new Error("No matching `accepts` entry for " + network.caip2);

    const priceStr = (accept.price || "0").replace("$", "");
    const valueUnits = Math.round(parseFloat(priceStr) * Math.pow(10, network.token_decimals));

    const nonce = nonceHex32();
    const now = Math.floor(Date.now() / 1000);
    const validAfter = String(now - 600);
    const validBefore = String(now + 3600);
    const payTo = accept.payTo || accept.pay_to;
    if (!payTo) throw new Error("Facilitator response missing payTo");

    const typedData = buildTypedData(
      network,
      from,
      payTo,
      valueUnits,
      validAfter,
      validBefore,
      nonce,
    );

    setStatus(statusEl, "Please sign the payment in your wallet…", "payment-pending");
    const signature = (await provider.request({
      method: "eth_signTypedData_v4",
      params: [from, JSON.stringify(typedData)],
    })) as string;

    const paymentPayload = {
      x402Version: 2,
      scheme: accept.scheme || "exact",
      network: accept.network,
      payload: {
        authorization: {
          from,
          to: payTo,
          value: String(valueUnits),
          validAfter,
          validBefore,
          nonce,
        },
        signature,
      },
    };
    const paymentB64 = btoa(JSON.stringify(paymentPayload));

    setStatus(statusEl, "Processing payment…", "payment-pending");
    const paidResp = await fetch(orderPath, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-PAYMENT": paymentB64,
      },
      body: JSON.stringify(body),
    });

    if (!paidResp.ok) {
      const paidErr = await paidResp.json().catch(() => ({}));
      throw new Error(paidErr.detail || paidErr.error || "Payment failed: " + paidResp.status);
    }

    const result = await paidResp.json();
    setStatus(statusEl, "Payment successful! Redirecting…", "payment-ok");
    setTimeout(() => {
      const tok = result.management_token
        ? "?token=" + encodeURIComponent(result.management_token)
        : "";
      window.location.href = "/order/status/" + result.vm_id + tok;
    }, 1000);
  } catch (err) {
    if ((err as { code?: number }).code === 4001) {
      setStatus(statusEl, "Payment cancelled.", "payment-warn");
    } else {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus(statusEl, "Error: " + msg, "payment-error");
      console.error("EVM payment error:", err);
    }
    if (button) button.disabled = false;
  }
}

const ns = (window.HyrulePayments = window.HyrulePayments || {});
ns.payWithEvm = payWithEvm;
