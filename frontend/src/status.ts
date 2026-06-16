/**
 * Status-page entry (status.html). Issue #26.
 *
 * Progressive enhancement: on load, disables htmx polling on #status-card and
 * takes over with client-side fetch from the launch-proof /v1/vm/{id}/status
 * endpoint. Renders each lifecycle state (payment_required → provisioning →
 * provisioned → failed → rolled_back) with customer-safe copy.
 */

import type { VmStatus } from "./types";

const POLL_INTERVAL_MS = 2000;

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderPaymentRequired(): string {
  return `
    <div class="status-card pending">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PAYMENT REQUIRED</span>
      </div>
      <div class="mt-4">
        <p class="text-text-soft">Your VM is reserved. Complete payment to begin provisioning.</p>
        <a href="/order" class="btn btn-primary mt-3">Pay now</a>
      </div>
    </div>
  `;
}

function renderProvisioning(): string {
  return `
    <div class="status-card pending">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONING</span>
      </div>
      <div class="mt-4">
        <p class="text-text-soft">Building your VM. Most builds finish in under 60 seconds.</p>
        <div class="progress-bar"><div class="progress-fill"></div></div>
      </div>
    </div>
  `;
}

function renderProvisioned(vm: VmStatus): string {
  const fqdn = vm.fqdn ?? "—";
  const ipv6 = vm.ipv6 ?? "—";
  const ssh = fqdn !== "—" ? `ssh root@${fqdn}` : "—";
  return `
    <div class="status-card ok">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">PROVISIONED</span>
      </div>
      <div class="kv-block mt-4">
        <div class="kv"><span class="k">hostname</span><span class="v"><code>${escapeHtml(fqdn)}</code></span><button class="copy" data-copy="${escapeHtml(fqdn)}">copy</button></div>
        <div class="kv"><span class="k">ipv6</span><span class="v"><code>${escapeHtml(ipv6)}</code></span><button class="copy" data-copy="${escapeHtml(ipv6)}">copy</button></div>
        <div class="kv"><span class="k">connect</span><span class="v"><code>${escapeHtml(ssh)}</code></span><button class="copy" data-copy="${escapeHtml(ssh)}">copy</button></div>
      </div>
    </div>
  `;
}

function renderFailed(vm: VmStatus): string {
  const msg = vm.customer_message ?? "Something went wrong during provisioning.";
  return `
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">FAILED</span>
      </div>
      <div class="mt-4">
        <p>${escapeHtml(msg)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p>
      </div>
    </div>
  `;
}

function renderRolledBack(vm: VmStatus): string {
  const msg =
    vm.customer_message ?? "Your order has been rolled back and any payment will be refunded.";
  return `
    <div class="status-card error">
      <div class="status-row">
        <span class="status-dot"></span>
        <span class="status-label">ROLLED BACK</span>
      </div>
      <div class="mt-4">
        <p>${escapeHtml(msg)}</p>
        <p class="mt-2 text-text-soft">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> if you need assistance.</p>
      </div>
    </div>
  `;
}

export function renderStatus(vm: VmStatus): string {
  switch (vm.status) {
    case "payment_required":
      return renderPaymentRequired();
    case "provisioning":
      return renderProvisioning();
    case "provisioned":
      return renderProvisioned(vm);
    case "failed":
      return renderFailed(vm);
    case "rolled_back":
      return renderRolledBack(vm);
    default:
      return renderProvisioning();
  }
}

function attachCopyHandlers(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const text = btn.getAttribute("data-copy");
      if (text && text !== "—") {
        void navigator.clipboard.writeText(text);
        const prev = btn.textContent;
        btn.textContent = "copied";
        window.setTimeout(() => {
          if (btn.textContent === "copied") {
            btn.textContent = prev;
          }
        }, 2000);
      }
    });
  });
}

export function initStatus(card: HTMLElement): () => void {
  const vmId = card.getAttribute("data-vm-id") ?? "";
  if (!vmId) return () => {};

  // Disable htmx before it initializes so the custom polling wins.
  card.setAttribute("hx-disable", "true");
  card.removeAttribute("hx-get");
  card.removeAttribute("hx-trigger");
  card.removeAttribute("hx-swap");

  let stopped = false;
  let timer: number | null = null;

  async function poll(): Promise<void> {
    if (stopped) return;
    try {
      const resp = await fetch(`/api/v1/vm/${encodeURIComponent(vmId)}/status`);
      if (resp.ok) {
        const data = (await resp.json()) as VmStatus;
        card.innerHTML = renderStatus(data);
        attachCopyHandlers(card);
        if (
          data.status === "provisioned" ||
          data.status === "failed" ||
          data.status === "rolled_back"
        ) {
          stop();
          return;
        }
      }
    } catch (err) {
      console.error("status poll failed", err);
    }
    timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
  }

  function stop(): void {
    stopped = true;
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  void poll();
  return stop;
}

const card = document.querySelector<HTMLElement>("#status-card");
if (card) {
  initStatus(card);
}
