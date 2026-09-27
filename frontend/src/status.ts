/**
 * Status-page entry (status.html). Issue #26.
 *
 * Progressive enhancement: polls the launch-proof /v1/vm/{id}/status
 * endpoint. Renders each lifecycle state (payment_required → provisioning →
 * provisioned → failed → rolled_back) with customer-safe copy.
 */

import type { LaunchProofStatus, VmStatus } from "./types";

const POLL_INTERVAL_MS = 2000;
const LIFECYCLE_POLL_INTERVAL_MS = 60000;
export type DisplayState =
  | LaunchProofStatus
  | "expired"
  | "deletion_eligible"
  | "deleting"
  | "retaining"
  | "retained"
  | "restoring"
  | "suspended"
  | "destroyed";

const lifecycleCopy = {
  retaining: [
    "RETENTION PENDING",
    "VM retention is being verified.",
    "Contact support for recovery.",
  ],
  retained: [
    "DATA RETAINED",
    "Your VM is retained for recovery.",
    "Contact support to restore your VM.",
  ],
  restoring: [
    "RECOVERY IN PROGRESS",
    "Your VM is being recovered.",
    "This page will update as recovery progresses.",
  ],
  expired: [
    "EXPIRED",
    "Your VM has expired.",
    "Renew before the grace period ends to avoid deletion.",
  ],
  deletion_eligible: [
    "GRACE PERIOD ENDED",
    "The grace period has ended.",
    "This VM is eligible for deletion. Contact support immediately for recovery options.",
  ],
  deleting: [
    "DELETION STARTED",
    "VM deletion has started.",
    "Contact support for the remaining recovery options.",
  ],
  suspended: [
    "SUSPENDED",
    "Your VM is suspended.",
    "Check the expiry information below and contact support for recovery.",
  ],
  destroyed: ["DESTROYED", "Your VM is destroyed.", "Contact support if you need assistance."],
} as const;

function isLifecycleState(state: DisplayState): state is keyof typeof lifecycleCopy {
  return Object.prototype.hasOwnProperty.call(lifecycleCopy, state);
}

function pageCopy(state: DisplayState): readonly [string, string] {
  if (isLifecycleState(state)) return [lifecycleCopy[state][1], lifecycleCopy[state][2]];
  switch (state) {
    case "provisioned":
      return ["Your VM is online.", "Connection details are below."];
    case "failed":
      return ["Provisioning failed.", "See the failure message and support path below."];
    case "rolled_back":
      return ["Order rolled back.", "See the status card for details."];
    case "payment_required":
      return ["Payment required.", "Complete payment to begin the build."];
    default:
      return [
        "Your VM is being provisioned.",
        "This page checks for provisioning updates automatically.",
      ];
  }
}

function dateText(value: string): string {
  // Legacy API datetimes without an offset represent UTC, as on the server.
  const normalized =
    /[T ]/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function renderExpiry(vm: VmStatus): string {
  const grace =
    vm.status !== "destroyed" &&
    vm.status !== "failed" &&
    ["active", "expired", "deletion_eligible"].includes(vm.expiry?.state ?? "")
      ? vm.expiry?.grace_ends_at
      : null;
  const retained =
    vm.status !== "destroyed" &&
    ["retaining", "retained", "restoring"].includes(vm.expiry?.state ?? "")
      ? vm.expiry?.retained_until
      : null;
  if (!vm.expires_at && !grace && !retained) return "";
  return `<div class="kv-block mt-4">
    ${vm.expires_at ? `<div class="kv"><span class="k">Term expires</span><span class="v">${escapeHtml(dateText(vm.expires_at))}</span></div>` : ""}
    ${grace ? `<div class="kv"><span class="k">Grace period ends</span><span class="v">${escapeHtml(dateText(grace))}</span></div><p class="text-text-soft mt-2">After this deadline, the VM is eligible for deletion. Recovery is not guaranteed.</p>` : ""}
    ${retained ? `<div class="kv"><span class="k">Minimum retention until</span><span class="v">${escapeHtml(dateText(retained))}</span></div><p class="text-text-soft mt-2">Contact support for recovery. This is not a scheduled deletion date.</p>` : ""}
  </div>`;
}

/** Collapse the API's two status vocabularies into one display state.
 *
 * Current expiry and terminal runtime states outrank historical launch proof.
 * Otherwise map VMStatus, whose values (`ready`, `running`, …)
 * are NOT launch-proof values — reading `status` as if they were is what left
 * a finished VM rendering "Building your VM…" indefinitely.
 */
export function displayState(vm: VmStatus): DisplayState {
  if (vm.status === "destroyed" || vm.expiry?.state === "destroyed") return "destroyed";
  if (vm.expiry?.state === "deleting") return "deleting";
  if (
    vm.expiry?.state === "retaining" ||
    vm.expiry?.state === "retained" ||
    vm.expiry?.state === "restoring"
  )
    return vm.expiry.state;
  if (vm.status === "failed")
    return vm.launch_proof_status === "rolled_back" ? "rolled_back" : "failed";
  if (vm.expiry?.state === "expired" || vm.expiry?.state === "deletion_eligible")
    return vm.expiry.state;
  if (vm.status === "suspended") return "suspended";
  if (vm.launch_proof_status) return vm.launch_proof_status;
  switch (vm.status) {
    case "ready":
    case "running":
      return "provisioned";
    default:
      return "provisioning";
  }
}

/** True once the state cannot change without user action — stop polling. */
export function isTerminalState(state: DisplayState): boolean {
  return state === "failed" || state === "rolled_back" || state === "destroyed";
}

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
  // The API field is `hostname`; this used to read a `fqdn` that the response
  // has never carried, so the ready card showed "—" for host and ssh.
  const fqdn = vm.hostname ?? "—";
  const ipv6 = vm.ipv6 ?? "—";
  const ssh = fqdn !== "—" ? `ssh root@${fqdn}` : "—";
  const resources = vm.resources
    ? `${vm.resources.vcpu}C / ${vm.resources.ram_mb / 1024}G RAM / ${vm.resources.disk_gb}G SSD`
    : "—";
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
        <div class="kv"><span class="k">resources</span><span class="v"><code>${escapeHtml(resources)}</code></span></div>
      </div>
      ${renderExpiry(vm)}
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
  const state = displayState(vm);
  if (isLifecycleState(state)) {
    const [label, , message] = lifecycleCopy[state];
    return `<div class="status-card error"><div class="status-row"><span class="status-dot"></span><span class="status-label">${label}</span></div>
      <div class="mt-4"><p>${message}</p><p class="mt-2">VM status: ${escapeHtml(vm.status ?? "unknown")}</p>
      ${renderExpiry(vm)}<p class="mt-2">Contact <a href="mailto:support@hyrule.host">support@hyrule.host</a> for help.</p></div></div>`;
  }
  switch (state) {
    case "payment_required":
      return renderPaymentRequired();
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

  let stopped = false;
  let timer: number | null = null;
  let interval = POLL_INTERVAL_MS;

  async function poll(): Promise<void> {
    if (stopped) return;
    try {
      const resp = await fetch(`/api/v1/vm/${encodeURIComponent(vmId)}/status`);
      if (stopped) return;
      if (resp.ok) {
        const data = (await resp.json()) as VmStatus;
        const container = document.createElement("div");
        container.innerHTML = renderStatus(data).trim();
        const state = displayState(data);
        const heading = document.querySelector<HTMLElement>("[data-status-title]");
        const blurb = document.querySelector<HTMLElement>("[data-status-blurb]");
        const details = document.querySelector<HTMLElement>("#status-connections");
        if (details) {
          details.hidden = state !== "provisioned";
          details.style.display = state === "provisioned" ? "" : "none";
          details.innerHTML =
            state === "provisioned"
              ? `
            <div class="terminal">
              <div class="terminal-bar"><span class="terminal-title">SSH</span><span class="terminal-tag">online</span></div>
              <div class="terminal-body">
                <div class="t-line"><span class="prompt">$</span><span class="output">ssh root@${escapeHtml(data.hostname ?? "")}</span></div>
                <div class="t-line"><span class="prompt">✓</span><span class="output">authenticating with your public key</span></div>
              </div>
            </div>
            <div class="mini-card p-[18px]">
              <h4>Management</h4>
              <p>Lifecycle mutations require the save-once management URL or an account that owns this VM. The public status URL intentionally cannot reboot, extend, snapshot, or destroy it.</p>
            </div>`
              : "";
        }
        const [title, description] = pageCopy(state);
        if (heading) heading.textContent = title;
        if (blurb) blurb.textContent = description;
        const step = document.querySelector<HTMLElement>("[data-status-step]");
        if (step) {
          step.textContent =
            state === "provisioned"
              ? "running"
              : state === "payment_required"
                ? "payment"
                : state === "accepted"
                  ? "provisioning"
                  : state.replaceAll("_", " ");
          const wrapper = step.closest(".stp");
          const done =
            state !== "deleting" &&
            state !== "retaining" &&
            state !== "restoring" &&
            state !== "provisioning" &&
            state !== "accepted" &&
            state !== "payment_required";
          wrapper?.classList.toggle("done", done);
          wrapper?.classList.toggle("active", !done);
          const number = wrapper?.querySelector(".num");
          if (number) number.textContent = done ? "✓" : "4";
        }
        const replacement = container.firstElementChild;
        if (replacement instanceof HTMLElement) {
          replacement.id = "status-card";
          replacement.dataset.vmId = vmId;
          replacement.dataset.status = state;
          card.replaceWith(replacement);
          card = replacement;
        }
        attachCopyHandlers(card);
        if (isTerminalState(state)) {
          stop();
          return;
        }
        interval =
          state === "provisioning" ||
          state === "accepted" ||
          state === "payment_required" ||
          state === "retaining" ||
          state === "restoring"
            ? POLL_INTERVAL_MS
            : LIFECYCLE_POLL_INTERVAL_MS;
      }
    } catch (err) {
      console.error("status poll failed", err);
    }
    timer = window.setTimeout(() => void poll(), interval);
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

export function initManagementAccess(): void {
  const root = document.querySelector<HTMLElement>("#management-access");
  if (!root) return;
  const vmId = root.dataset.vmId ?? "";
  // The bare token, never a URL. The API's `management_url` is built from its
  // own request base_url, which behind the proxy is the internal overlay
  // address — so rendering it leaked infrastructure detail and handed the
  // buyer a link they cannot use.
  let managementToken = root.dataset.managementToken ?? "";

  if (!managementToken && vmId) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(`hyr_vm_mgmt:${vmId}`) ?? "null") as {
        token?: string;
      } | null;
      if (saved?.token?.startsWith("hyr_vm_")) managementToken = saved.token;
    } catch {
      managementToken = "";
    }
  }

  if (managementToken && !root.querySelector(".management-card")) {
    root.innerHTML = `
      <div class="mini-card management-card">
        <span class="panel-label">Save once</span>
        <h3>VM management token</h3>
        <p>This credential is required to reboot, extend, inspect, or destroy an order that is not attached to an account. Save it now.</p>
        <div class="credential-row">
          <code id="mgmt-token">${escapeHtml(managementToken)}</code>
          <button type="button" class="btn btn-secondary btn-xs" data-copy="${escapeHtml(managementToken)}">Copy</button>
          <a class="btn btn-ghost btn-xs" href="data:text/plain;charset=utf-8,${encodeURIComponent(managementToken)}" download="hyrule-${escapeHtml(vmId)}-management-token.txt">Download .txt</a>
        </div>
      </div>`;
  }
  attachCopyHandlers(root);
}

const card = document.querySelector<HTMLElement>("#status-card");
if (card) {
  initStatus(card);
}
initManagementAccess();
