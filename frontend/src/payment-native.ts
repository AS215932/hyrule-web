/**
 * Native crypto (BTC / XMR) payment driver for Hyrule Cloud checkout.
 *
 * Exposes window.HyrulePaymentNative.pay(asset, opts). Flow:
 *   1. POST /api/v1/intent/create with order_payload + client_order_id
 *      (idempotency key persisted to sessionStorage so a reload doesn't
 *      allocate a second address).
 *   2. Render the deposit address + amount + countdown + QR.
 *   3. Poll GET /api/v1/intent/{id} every 5s. On PROVISIONED, stash the
 *      one-shot management_token and redirect to /order/status/{vm_id}.
 *
 * Issue #14 / Phase 1: behaviour-preserving TypeScript port of payment-native.js.
 */

import type { NativePayOptions } from "./types";

const POLL_MS = 5000;
// Stop polling after ~30 min (server-side intents TTL at 60 min).
const MAX_POLL_ATTEMPTS = 360;
const QR_LIB_URL = "https://cdn.jsdelivr.net/npm/qrcode-svg@1.1.0/dist/qrcode.min.js";

let qrLibPromise: Promise<unknown> | null = null;

function loadQRLib(): Promise<unknown> {
  if (qrLibPromise) return qrLibPromise;
  qrLibPromise = new Promise((resolve, reject) => {
    if (typeof window.QRCode === "function") {
      resolve(window.QRCode);
      return;
    }
    const s = document.createElement("script");
    s.src = QR_LIB_URL;
    s.async = true;
    s.onload = () => resolve(window.QRCode);
    s.onerror = () => reject(new Error("Failed to load QR library"));
    document.head.appendChild(s);
  });
  return qrLibPromise;
}

async function drawQR(container: HTMLElement, content: string): Promise<void> {
  try {
    await loadQRLib();
    const QR = window.QRCode;
    if (!QR) throw new Error("QR library unavailable");
    const qr = new QR({
      content,
      padding: 2,
      width: 256,
      height: 256,
      color: "#000",
      background: "#fff",
      ecl: "M",
    });
    // qr.svg() is library-generated markup from the QR matrix (the URI is
    // encoded as modules, not embedded as text), so this innerHTML is safe.
    container.innerHTML = qr.svg();
  } catch {
    // Fallback: show the URI as a copyable string via textContent (never parsed
    // as markup — no escaping, no injection surface).
    container.textContent = "";
    const code = document.createElement("code");
    code.style.cssText = "word-break:break-all;font-size:.85rem";
    code.textContent = String(content);
    container.appendChild(code);
  }
}

function newClientOrderId(): string {
  // Browser-side UUID v4-ish; just an idempotency key scoped to one payment.
  const arr = new Uint8Array(16);
  crypto.getRandomValues(arr);
  arr[6] = (arr[6] & 0x0f) | 0x40;
  arr[8] = (arr[8] & 0x3f) | 0x80;
  return Array.from(arr)
    .map((b, i) => {
      const hex = b.toString(16).padStart(2, "0");
      return i === 4 || i === 6 || i === 8 || i === 10 ? "-" + hex : hex;
    })
    .join("");
}

function gatherOrderPayload(formEl: HTMLFormElement): Record<string, unknown> {
  const fd = new FormData(formEl);
  const payload: Record<string, unknown> = {
    os: fd.get("os"),
    size: fd.get("size"),
    duration_days: parseInt(String(fd.get("duration_days")), 10),
    ssh_pubkey: fd.get("ssh_pubkey"),
    domain_mode: fd.get("domain_mode") || "auto",
  };
  if (fd.get("hostname")) payload.hostname = fd.get("hostname");
  if (fd.get("domain") && fd.get("domain_mode") === "custom") {
    payload.domain = fd.get("domain");
  }
  return payload;
}

interface IntentBody {
  intent_id: string;
  asset: string;
  address: string;
  amount_crypto: string;
  amount_usd?: string;
  rate_valid_until?: string;
  status: string;
  confirmations?: number;
  qr_code_uri?: string;
  expires_at?: string;
  vm_id?: string;
  management_token?: string;
  management_url?: string;
}

function stashManagementToken(intentBody: IntentBody): void {
  if (intentBody && intentBody.vm_id && intentBody.management_token) {
    try {
      sessionStorage.setItem(
        "hyr_vm_mgmt:" + intentBody.vm_id,
        JSON.stringify({
          token: intentBody.management_token,
          url: intentBody.management_url || null,
          issued: Date.now(),
        }),
      );
    } catch (e) {
      console.warn("Failed to stash management token:", e);
    }
  }
}

export function statusRedirectUrl(intentBody: IntentBody): string {
  const vmId = intentBody.vm_id;
  if (!vmId) return "/order";
  const token = intentBody.management_token;
  return "/order/status/" + vmId + (token ? "?token=" + encodeURIComponent(token) : "");
}

function setStatusLine(container: HTMLElement, status: unknown, confirmations: unknown): void {
  const el = container.querySelector("#hyr-status");
  if (!el) return;
  el.textContent = "Status: ";
  const strong = document.createElement("strong");
  strong.textContent = String(status == null ? "" : status);
  el.appendChild(strong);
  el.appendChild(document.createTextNode(" · confirmations: " + (confirmations || 0)));
}

export function renderDepositCard(container: HTMLElement, intent: IntentBody): void {
  const label = intent.asset === "BTC" ? "Bitcoin" : "Monero";
  const expires = intent.expires_at ? new Date(intent.expires_at) : null;
  // Static skeleton ONLY — no backend data interpolated into innerHTML. All
  // dynamic fields are set via textContent below (XSS-safe).
  // Issue #8: responsive layout — the QR caps at the container width and the
  // text column gets `min-w-0` so a long deposit address wraps instead of
  // forcing the card wider than a narrow viewport. The two stack below `xs`.
  container.innerHTML =
    '<div class="mini-card p-5">' +
    '<div class="flex flex-col gap-[18px] xs:flex-row xs:items-start">' +
    '<div id="hyr-qr" class="aspect-square w-[256px] max-w-full shrink-0 self-center rounded-lg bg-white xs:self-auto [&>svg]:h-full [&>svg]:w-full"></div>' +
    '<div class="flex min-w-0 flex-1 flex-col gap-2.5">' +
    '<div><span class="panel-label">send</span><div class="mt-1 text-[1.4em]"><strong id="hyr-amt"></strong></div></div>' +
    '<div><span class="panel-label">to address</span><div class="mt-1"><code id="hyr-addr" class="break-all text-[0.85em]"></code></div></div>' +
    '<div class="flex gap-1.5"><button id="hyr-copy-addr" class="btn btn-secondary btn-xs">copy address</button><button id="hyr-copy-amt" class="btn btn-secondary btn-xs">copy amount</button></div>' +
    '<div class="text-[0.85em] text-text-soft" id="hyr-rate"></div>' +
    '<div id="hyr-status" class="text-[0.85em]"></div>' +
    '<div class="text-[0.78em] text-text-soft" id="hyr-expires"></div>' +
    "</div>" +
    "</div>" +
    '<p class="mt-3.5 text-[0.78em] text-text-soft" id="hyr-policy"></p>' +
    "</div>";

  const set = (sel: string, text: string): void => {
    const el = container.querySelector(sel);
    if (el) el.textContent = text;
  };
  set("#hyr-amt", intent.amount_crypto + " " + intent.asset);
  set("#hyr-addr", intent.address);
  set(
    "#hyr-rate",
    "≈ $" + intent.amount_usd + " · rate locked until " + (intent.rate_valid_until || "—"),
  );
  setStatusLine(container, intent.status, intent.confirmations);
  if (expires) set("#hyr-expires", "Intent expires " + expires.toISOString());
  set(
    "#hyr-policy",
    label +
      ": pay the exact amount or more — overpay is fine (becomes a tip). " +
      "If the rate snapshot expires before you broadcast, we'll re-quote within " +
      "1% slippage. Underpayment triggers a manual review.",
  );

  container.querySelector("#hyr-copy-addr")?.addEventListener("click", () => {
    void navigator.clipboard.writeText(intent.address);
  });
  container.querySelector("#hyr-copy-amt")?.addEventListener("click", () => {
    void navigator.clipboard.writeText(intent.amount_crypto);
  });

  const qrTarget = container.querySelector<HTMLElement>("#hyr-qr");
  if (qrTarget) {
    void drawQR(qrTarget, intent.qr_code_uri || intent.asset.toLowerCase() + ":" + intent.address);
  }
}

async function pollUntilTerminal(
  intentId: string,
  container: HTMLElement,
  setStatus: (msg: string, cls?: string) => void,
): Promise<void> {
  let done = false;
  let attempts = 0;
  while (!done && attempts < MAX_POLL_ATTEMPTS) {
    attempts++;
    await new Promise((r) => setTimeout(r, POLL_MS));
    let resp: Response;
    try {
      resp = await fetch("/api/v1/intent/" + intentId);
    } catch {
      continue; // transient; retry next tick
    }
    if (!resp.ok) continue;
    const body: IntentBody | null = await resp.json().catch(() => null);
    if (!body) continue;

    setStatusLine(container, body.status, body.confirmations);

    switch (body.status) {
      case "PROVISIONED":
        setStatus("Payment received. Redirecting…", "payment-ok");
        stashManagementToken(body);
        setTimeout(() => {
          window.location.href = statusRedirectUrl(body);
        }, 800);
        done = true;
        break;
      case "REFUND_MANUAL":
        setStatus(
          "Payment received but amount/rate didn't match. Contact the operator with intent ID " +
            intentId +
            ".",
          "payment-warn",
        );
        done = true;
        break;
      case "EXPIRED":
        setStatus("Intent expired with no payment seen. Refresh to start over.", "payment-warn");
        done = true;
        break;
      case "FAILED":
        setStatus(
          "Provisioning failed after payment. Contact the operator with intent ID " +
            intentId +
            ".",
          "payment-error",
        );
        done = true;
        break;
      default:
        // CREATED / WAITING_PAYMENT / SETTLED / PROVISIONING — keep polling.
        break;
    }
  }

  if (!done) {
    setStatus(
      "Couldn't confirm payment status in time. Your deposit is still valid — check back later or " +
        "contact the operator with intent ID " +
        intentId +
        ".",
      "payment-warn",
    );
  }
}

async function pay(asset: string, opts: NativePayOptions): Promise<void> {
  const setStatus = opts.onStatus || (() => {});
  const render = opts.render;
  const orderForm = opts.orderForm;
  if (!render || !orderForm) {
    throw new Error("HyrulePaymentNative.pay: render + orderForm required");
  }

  // Idempotent intent creation: a per-asset client_order_id is stashed so a
  // reload doesn't allocate a fresh deposit.
  const stashKey = "hyr_intent_client_order_id:" + asset;
  let clientOrderId = sessionStorage.getItem(stashKey);
  if (!clientOrderId) {
    clientOrderId = newClientOrderId();
    sessionStorage.setItem(stashKey, clientOrderId);
  }

  setStatus("Allocating deposit address…", "payment-pending");
  const createResp = await fetch("/api/v1/intent/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      asset,
      client_order_id: clientOrderId,
      order_payload: gatherOrderPayload(orderForm),
    }),
  });
  if (!createResp.ok) {
    const err = await createResp.json().catch(() => ({}));
    throw new Error(err.detail || err.error || "Intent create failed: " + createResp.status);
  }
  const intent: IntentBody = await createResp.json();

  renderDepositCard(render, intent);

  setStatus("Awaiting payment…", "payment-pending");
  await pollUntilTerminal(intent.intent_id, render, setStatus);
}

window.HyrulePaymentNative = { pay };
