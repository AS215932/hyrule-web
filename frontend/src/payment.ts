/**
 * Payment dispatcher entry for the review/checkout page (Block C/E).
 *
 * Imports the EVM + native adapters (side-effect: they register
 * window.HyrulePayments / window.HyrulePaymentNative), then wires the
 * payment-method tabs and the chain selector and dispatches the pay button.
 *
 * No chain config or addresses live here — the EVM chain list comes from
 * /api/payments/networks and the BTC/XMR deposit details come from
 * /v1/intent/*, never hardcoded.
 *
 * Issue #14 / Phase 1: behaviour-preserving TypeScript port of payment.js.
 */

import "./payment-evm";
import "./payment-native";
import type { PaymentNetwork } from "./types";

(function () {
  const payBtn = document.getElementById("pay-btn") as HTMLButtonElement | null;
  const statusEl = document.getElementById("payment-status");
  const selector = document.getElementById("payment-chain") as HTMLSelectElement | null;
  const dataForm = document.getElementById("order-data") as HTMLFormElement | null;
  const methodInputs = document.querySelectorAll<HTMLInputElement>('input[name="payment-method"]');
  const nativeRender = document.getElementById("payment-native-render");

  if (!payBtn || !statusEl) return;

  const networksByKey: Record<string, PaymentNetwork> = {};

  function currentMethod(): string {
    for (const input of methodInputs) {
      if (input.checked) return input.value;
    }
    return "evm";
  }

  function setStatus(msg: string, cls?: string): void {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = "payment-status " + (cls || "");
  }

  function renderSelector(networks: PaymentNetwork[]): void {
    if (!selector) return;
    selector.innerHTML = "";
    networks.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n.key;
      opt.textContent = n.display_name + " · " + n.asset + (n.testnet ? " (testnet)" : "");
      selector.appendChild(opt);
    });
  }

  async function loadNetworks(): Promise<void> {
    try {
      // Same-origin: app.py proxies /api/* → backend /v1/*.
      const resp = await fetch("/api/payments/networks");
      if (!resp.ok) throw new Error("networks: HTTP " + resp.status);
      const body = await resp.json();
      const networks: PaymentNetwork[] = body.networks || [];
      networks.forEach((n) => {
        networksByKey[n.key] = n;
      });
      renderSelector(networks);
      if (!networks.length && currentMethod() === "evm") {
        setStatus("No payment chains enabled. Contact ops.", "payment-error");
      }
    } catch (err) {
      if (currentMethod() === "evm") {
        setStatus("Could not load supported chains. Refresh to try again.", "payment-error");
      }
      console.error("network-list fetch failed", err);
    }
  }

  function selectedNetwork(): PaymentNetwork | null {
    if (selector && selector.value) {
      return networksByKey[selector.value] ?? null;
    }
    // No selector on the page (single-chain deployment) → first advertised.
    const keys = Object.keys(networksByKey);
    if (keys.length) return networksByKey[keys[0]] ?? null;
    return null;
  }

  function orderBody(): Record<string, unknown> {
    if (!dataForm) return {};
    const fd = new FormData(dataForm);
    const payload: Record<string, unknown> = {
      os: fd.get("os"),
      size: fd.get("size"),
      duration_days: parseInt(String(fd.get("duration_days")), 10),
      ssh_pubkey: fd.get("ssh_pubkey"),
      domain_mode: fd.get("domain_mode") || "auto",
    };
    const hostname = fd.get("hostname");
    if (hostname) payload.hostname = hostname;
    if (fd.get("domain") && fd.get("domain_mode") === "custom") {
      payload.domain = fd.get("domain");
    }
    // Issue #14: bind to the durable quote so the server provisions the quoted
    // spec at the locked price (and idempotently across the 402 → sign → retry).
    const quoteId = fd.get("quote_id");
    if (quoteId) payload.quote_id = quoteId;
    return payload;
  }

  function refreshMethodUI(): void {
    const m = currentMethod();
    const wrap = document.getElementById("payment-chain-wrap");
    if (wrap) wrap.style.display = m === "evm" ? "block" : "none";
    if (nativeRender) {
      nativeRender.style.display = m === "btc" || m === "xmr" ? "block" : "none";
      if (m === "evm") nativeRender.innerHTML = "";
    }
  }

  methodInputs.forEach((el) => el.addEventListener("change", refreshMethodUI));

  payBtn.addEventListener("click", async () => {
    const method = currentMethod();

    // Native BTC/XMR path — open an intent + poll. No chain.
    if (method === "btc" || method === "xmr") {
      if (!window.HyrulePaymentNative || typeof window.HyrulePaymentNative.pay !== "function") {
        setStatus("Native crypto adapter not loaded.", "payment-error");
        return;
      }
      try {
        await window.HyrulePaymentNative.pay(method.toUpperCase(), {
          orderForm: dataForm!,
          render: nativeRender,
          onStatus: setStatus,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setStatus("Error: " + msg, "payment-error");
        console.error("native payment error:", err);
      }
      return;
    }

    // USDC/x402 path — dispatch by the backend-advertised chain family.
    const network = selectedNetwork();
    if (!network) {
      setStatus("No payment chain selected.", "payment-error");
      return;
    }
    const ns = window.HyrulePayments || {};
    if (network.family === "evm") {
      if (typeof ns.payWithEvm !== "function") {
        setStatus("EVM adapter not loaded.", "payment-error");
        return;
      }
      await ns.payWithEvm({
        network,
        button: payBtn,
        statusEl,
        orderPath: "/api/vm/create",
        body: orderBody(),
      });
      return;
    }
    if (network.family === "svm") {
      await import("./payment-solana");
      if (typeof ns.payWithSolana !== "function") {
        setStatus("Solana payment adapter is unavailable.", "payment-error");
        return;
      }
      await ns.payWithSolana({
        network,
        button: payBtn,
        statusEl,
        orderPath: "/api/vm/create",
        body: orderBody(),
      });
      return;
    }
    setStatus("Unsupported payment network.", "payment-error");
  });

  void loadNetworks();
  refreshMethodUI();
})();
