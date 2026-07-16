import "./payment-evm";
import { getEvmProvider } from "./payment-evm";
import type { Eip1193Provider, PaymentNetwork } from "./types";

const TERMINAL_ORDERS = new Set([
  "active",
  "refund_due",
  "refunded",
  "failed",
  "cancelled",
  "expired",
]);

function randomKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function storedKey(scope: string): string {
  const storageKey = "hyr_domain_idempotency:" + scope;
  let value = sessionStorage.getItem(storageKey);
  if (!value) {
    value = randomKey();
    sessionStorage.setItem(storageKey, value);
  }
  return value;
}

function setStatus(element: HTMLElement | null, message: string, tone = ""): void {
  if (!element) return;
  element.textContent = message;
  element.className = "payment-status " + tone;
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => ({}));
  return new Error(body.detail || body.error || fallback);
}

function orderRedirect(result: Record<string, unknown>): void {
  const orderId = result.order_id;
  if (typeof orderId !== "string") throw new Error("Order response did not include an order ID.");
  window.location.href = "/domains/orders/" + encodeURIComponent(orderId);
}

interface DomainOrder {
  order_id: string;
  status: string;
  payment?: {
    intent_id: string;
    asset: string;
    address: string;
    amount_crypto: string;
    amount_usd: string;
    qr_code_uri: string;
    expires_at: string;
  } | null;
}

export function domainOrderPayload(
  quoteId: string,
  paymentMethod: string,
  termsVersion: string,
  refundAddress?: string,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    quote_id: quoteId,
    payment_method: paymentMethod,
    terms_version: termsVersion,
  };
  if (paymentMethod !== "usdc") {
    const normalized = refundAddress?.trim() || "";
    if (!normalized) throw new Error("A refund address is required for BTC/XMR.");
    body.refund_address = normalized;
  }
  return body;
}

function renderNative(container: HTMLElement, order: DomainOrder): void {
  const payment = order.payment;
  container.replaceChildren();
  if (!payment) {
    container.textContent = "This order has no deposit instruction. Reload its status page.";
    return;
  }
  const card = document.createElement("div");
  card.className = "mini-card p-5 text-left";
  const heading = document.createElement("strong");
  heading.textContent = `Send exactly ${payment.amount_crypto} ${payment.asset}`;
  const address = document.createElement("code");
  address.className = "mt-3 block break-all";
  address.textContent = payment.address;
  const expiry = document.createElement("p");
  expiry.className = "mt-3 text-[0.82em] text-text-soft";
  expiry.textContent = `Intent ${payment.intent_id} expires ${payment.expires_at}. Keep this order ID for support.`;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "btn btn-secondary btn-xs mt-3";
  copy.textContent = "Copy address";
  copy.addEventListener("click", () => void navigator.clipboard.writeText(payment.address));
  const statusLink = document.createElement("a");
  statusLink.className = "btn btn-ghost btn-xs mt-3 ml-2";
  statusLink.href = "/domains/orders/" + encodeURIComponent(order.order_id);
  statusLink.textContent = "Open order status";
  card.append(heading, address, expiry, copy, statusLink);
  container.append(card);
}

async function pollOrder(orderId: string, statusElement: HTMLElement | null): Promise<void> {
  for (let attempt = 0; attempt < 720; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const response = await fetch("/api/domains/orders/" + encodeURIComponent(orderId));
    if (!response.ok) continue;
    const order = (await response.json()) as DomainOrder;
    setStatus(
      statusElement,
      `Order status: ${order.status.replaceAll("_", " ")}`,
      "payment-pending",
    );
    if (!TERMINAL_ORDERS.has(order.status)) continue;
    if (order.status === "active") orderRedirect(order as unknown as Record<string, unknown>);
    else window.location.href = "/domains/orders/" + encodeURIComponent(orderId);
    return;
  }
  setStatus(
    statusElement,
    "The payment intent is still unresolved. Open the order status before retrying.",
    "payment-warn",
  );
}

export async function setupCheckout(container: HTMLElement): Promise<void> {
  const quoteId = container.dataset.quoteId || "";
  const termsVersion = container.dataset.termsVersion || "";
  const payButton = document.getElementById("domain-pay") as HTMLButtonElement | null;
  const statusElement = document.getElementById("domain-payment-status");
  const chainSelect = document.getElementById("domain-chain") as HTMLSelectElement | null;
  const refundInput = document.getElementById("domain-refund-address") as HTMLInputElement | null;
  const refundWrap = document.getElementById("domain-refund-wrap");
  const chainWrap = document.getElementById("domain-chain-wrap");
  const terms = document.getElementById("domain-terms") as HTMLInputElement | null;
  const nativeContainer = document.getElementById("domain-native-payment");
  const methods = document.querySelectorAll<HTMLInputElement>(
    'input[name="domain-payment-method"]',
  );
  if (!quoteId || !payButton) return;

  const networks = new Map<string, PaymentNetwork>();

  function method(): string {
    return (
      Array.from(methods).find((input) => input.checked)?.value || methods.item(0)?.value || ""
    );
  }

  function refresh(): void {
    const native = method() !== "usdc";
    if (refundWrap) refundWrap.style.display = native ? "block" : "none";
    if (chainWrap) chainWrap.style.display = native ? "none" : "block";
  }
  methods.forEach((input) => input.addEventListener("change", refresh));
  refresh();

  payButton.addEventListener("click", () => {
    void (async () => {
      if (!terms?.checked) throw new Error("Accept the domain terms before paying.");
      const selectedMethod = method();
      if (!selectedMethod) throw new Error("No payment method is currently available.");
      const body = domainOrderPayload(quoteId, selectedMethod, termsVersion, refundInput?.value);
      const idempotencyKey = storedKey(`${quoteId}:${selectedMethod}`);
      if (selectedMethod === "usdc") {
        const network = chainSelect
          ? networks.get(chainSelect.value)
          : networks.values().next().value;
        if (!network) throw new Error("No USDC settlement network is available.");
        const pay = window.HyrulePayments?.payWithEvm;
        if (!pay) throw new Error("The USDC payment adapter is unavailable.");
        await pay({
          network,
          button: payButton,
          statusEl: statusElement,
          orderPath: "/api/domains/orders",
          body,
          headers: { "Idempotency-Key": idempotencyKey },
          onSuccess: orderRedirect,
        });
        return;
      }
      payButton.disabled = true;
      setStatus(statusElement, "Allocating a deposit address…", "payment-pending");
      const response = await fetch("/api/domains/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw await responseError(response, "Could not create the domain order.");
      const order = (await response.json()) as DomainOrder;
      if (nativeContainer) renderNative(nativeContainer, order);
      setStatus(statusElement, "Awaiting payment…", "payment-pending");
      await pollOrder(order.order_id, statusElement);
    })().catch((error: unknown) => {
      payButton.disabled = false;
      setStatus(
        statusElement,
        error instanceof Error ? error.message : String(error),
        "payment-error",
      );
    });
  });

  // Register the controls before waiting on the optional EVM catalog. A slow
  // or unavailable catalog must not leave BTC/XMR checkout with an inert pay
  // button; USDC attempts fail clearly while this map remains empty.
  try {
    const networksResponse = await fetch("/api/payments/networks");
    if (!networksResponse.ok) return;
    const catalog = await networksResponse.json();
    for (const network of (catalog.networks || []) as PaymentNetwork[]) {
      if (network.family === "evm") networks.set(network.key, network);
    }
  } catch {
    return;
  }
}

async function signMessage(
  provider: Eip1193Provider,
  address: string,
  message: string,
): Promise<string> {
  try {
    return (await provider.request({
      method: "personal_sign",
      params: [message, address],
    })) as string;
  } catch (error) {
    if ((error as { code?: number }).code === 4001) throw error;
    return (await provider.request({
      method: "personal_sign",
      params: [address, message],
    })) as string;
  }
}

async function setupTransfer(container: HTMLElement): Promise<void> {
  const button = document.getElementById("domain-transfer-button") as HTMLButtonElement | null;
  const statusElement = document.getElementById("domain-transfer-status");
  if (!button) return;
  button.addEventListener("click", () => {
    void (async () => {
      const domain = container.dataset.domain || "";
      const linked = (container.dataset.wallet || "").toLowerCase();
      const provider = await getEvmProvider();
      if (!provider) throw new Error("No wallet is available.");
      const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
      const address = accounts[0];
      if (!address || address.toLowerCase() !== linked) {
        throw new Error("Select the primary wallet linked to this account.");
      }
      const linkedChainId = Number.parseInt(container.dataset.chainId || "", 10);
      if (!Number.isSafeInteger(linkedChainId) || linkedChainId <= 0) {
        throw new Error("The linked wallet chain is unavailable. Relink the primary wallet.");
      }
      const challengeResponse = await fetch(
        `/api/domains/${encodeURIComponent(domain)}/transfer-out/challenge`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address, chain_id: linkedChainId }),
        },
      );
      if (!challengeResponse.ok) {
        throw await responseError(challengeResponse, "Could not create transfer challenge.");
      }
      const challenge = await challengeResponse.json();
      setStatus(statusElement, "Sign the transfer-out challenge…", "payment-pending");
      const signature = await signMessage(provider, address, challenge.message);
      const transferResponse = await fetch(
        `/api/domains/${encodeURIComponent(domain)}/transfer-out`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": storedKey(`transfer:${domain}`),
          },
          body: JSON.stringify({ nonce: challenge.nonce, signature }),
        },
      );
      if (!transferResponse.ok) {
        throw await responseError(transferResponse, "Transfer-out could not be queued.");
      }
      const operation = await transferResponse.json();
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        const response = await fetch(`/api/domains/operations/${operation.operation_id}`);
        if (!response.ok) continue;
        const current = await response.json();
        setStatus(statusElement, `Transfer status: ${current.status}`, "payment-pending");
        if (current.status === "succeeded") {
          const secret = document.querySelector<HTMLElement>("#domain-transfer-secret code");
          const wrap = document.getElementById("domain-transfer-secret");
          if (secret && current.secret) secret.textContent = current.secret;
          if (wrap) wrap.classList.remove("hidden");
          setStatus(statusElement, "Domain unlocked. Save the one-time code now.", "payment-ok");
          return;
        }
        if (current.status === "failed")
          throw new Error(current.error_detail || "Transfer-out failed.");
      }
      throw new Error("Transfer-out is still pending. Contact support with the operation ID.");
    })().catch((error: unknown) => {
      setStatus(
        statusElement,
        error instanceof Error ? error.message : String(error),
        "payment-error",
      );
    });
  });
}

const checkout = document.getElementById("domain-checkout");
if (checkout) void setupCheckout(checkout);
const transfer = document.getElementById("domain-transfer");
if (transfer) void setupTransfer(transfer);
const statusCard = document.querySelector<HTMLElement>("[data-domain-order-status]");
if (statusCard && !TERMINAL_ORDERS.has(statusCard.dataset.domainOrderStatus || "")) {
  window.setTimeout(() => window.location.reload(), 5000);
}
