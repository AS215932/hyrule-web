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
import {
  encodeBase64Json,
  executeX402,
  quoteX402,
  type X402Acceptance,
  type X402Quote,
} from "./x402";

function setStatus(statusEl: HTMLElement | null, msg: string, cls?: string): void {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.className = "payment-status " + (cls || "");
}

interface ProvisionedResult {
  vm_id?: string;
  management_token?: string;
  management_url?: string;
}

function stashManagementToken(result: ProvisionedResult): void {
  if (!result.vm_id || !result.management_token) return;
  try {
    sessionStorage.setItem(
      "hyr_vm_mgmt:" + result.vm_id,
      JSON.stringify({
        token: result.management_token,
        url: result.management_url || null,
        issued: Date.now(),
      }),
    );
  } catch (err) {
    console.warn("Failed to stash management token:", err);
  }
}

export function statusRedirectUrl(result: ProvisionedResult): string {
  return result.vm_id ? "/order/status/" + result.vm_id : "/order";
}

export async function ensureChain(
  network: PaymentNetwork,
  provider: Eip1193Provider,
): Promise<void> {
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
  valueUnits: string | number,
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

function sameAddress(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}

/** Sign one exact x402 acceptance with the configured browser wallet. */
export async function signX402Quote(
  quote: X402Quote,
  network: PaymentNetwork,
  provided?: Eip1193Provider,
): Promise<string> {
  const accept: X402Acceptance = quote.accept;
  if (accept.network !== network.caip2 && accept.network !== network.key) {
    throw new Error("The selected wallet network does not match the live quote.");
  }
  if (accept.asset?.startsWith("0x") && !sameAddress(accept.asset, network.token_address)) {
    throw new Error("The quoted token contract is not enabled for this network.");
  }
  const payTo = accept.payTo || accept.pay_to;
  if (!payTo) throw new Error("The live quote does not contain a payment recipient.");
  if (!/^\d+$/.test(accept.amount))
    throw new Error("The live quote contains an invalid base-unit amount.");

  const provider = provided || (await getEvmProvider());
  if (!provider) throw new Error("No browser wallet is available.");
  const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
  const from = accounts[0];
  if (!from) throw new Error("The wallet did not return an account.");
  await ensureChain(network, provider);

  const timeout = Math.max(60, Math.min(Number(accept.maxTimeoutSeconds || 300), 3600));
  const now = Math.floor(Date.now() / 1000);
  const validAfter = String(now - 60);
  const validBefore = String(now + timeout);
  const nonce = nonceHex32();
  const domainName =
    typeof accept.extra?.name === "string" ? accept.extra.name : network.eip712_domain.name;
  const domainVersion =
    typeof accept.extra?.version === "string"
      ? accept.extra.version
      : network.eip712_domain.version;
  const typedData = buildTypedData(
    { ...network, eip712_domain: { name: domainName, version: domainVersion } },
    from,
    payTo,
    accept.amount,
    validAfter,
    validBefore,
    nonce,
  );
  const signature = (await provider.request({
    method: "eth_signTypedData_v4",
    params: [from, JSON.stringify(typedData)],
  })) as string;
  return encodeBase64Json({
    x402Version: 2,
    scheme: accept.scheme || "exact",
    network: accept.network,
    payload: {
      authorization: {
        from,
        to: payTo,
        value: accept.amount,
        validAfter,
        validBefore,
        nonce,
      },
      signature,
    },
  });
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
  const { network, button, statusEl, orderPath, body, headers = {}, onSuccess } = opts;

  if (button) button.disabled = true;
  setStatus(statusEl, "Requesting exact payment details…", "payment-pending");

  try {
    const quoteResult = await quoteX402(
      {
        url: orderPath,
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body),
      },
      [network.caip2, network.key].filter((value): value is string => Boolean(value)),
    );
    let result: Record<string, unknown>;
    if (quoteResult.kind === "response") {
      result = (await quoteResult.response.json()) as Record<string, unknown>;
    } else {
      setStatus(statusEl, "Connect and sign the exact payment…", "payment-pending");
      const paymentSignature = await signX402Quote(quoteResult.quote, network);
      setStatus(statusEl, "Processing payment…", "payment-pending");
      const paidResp = await executeX402(quoteResult.quote, paymentSignature);
      result = (await paidResp.json()) as Record<string, unknown>;
    }
    setStatus(statusEl, "Payment successful! Redirecting…", "payment-ok");
    if (onSuccess) {
      onSuccess(result);
      return;
    }
    const provisioned = result as ProvisionedResult;
    stashManagementToken(provisioned);
    setTimeout(() => {
      window.location.href = statusRedirectUrl(provisioned);
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
