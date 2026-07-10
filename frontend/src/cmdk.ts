/* Hyrule Cloud command palette — TypeScript port of the vanilla CmdK.
   Trigger: any element with [data-cmdk-trigger], or ⌘K / Ctrl+K.
   Issue #14 / Phase 1: behaviour-preserving port of cmdk.js. */

interface Command {
  section: string;
  icon: string;
  title: string;
  sub?: string;
  href?: string;
}

const COMMANDS: Command[] = [
  { section: "Navigate", icon: "▸", title: "Home", sub: "/", href: "/" },
  { section: "Navigate", icon: "▸", title: "Services", sub: "/services", href: "/services" },
  { section: "Navigate", icon: "▸", title: "For agents", sub: "/agents", href: "/agents" },
  { section: "Navigate", icon: "▸", title: "Deploy a VM", sub: "/order", href: "/order" },
  {
    section: "Navigate",
    icon: "▸",
    title: "VM status",
    sub: "/order/status",
    href: "/order/status",
  },
  {
    section: "Quick deploy",
    icon: "⊕",
    title: "Deploy Starter (1 vCPU · 1 GB)",
    sub: "$0.05/day",
    href: "/order?size=xs",
  },
  {
    section: "Quick deploy",
    icon: "⊕",
    title: "Deploy Basic (1 vCPU · 1 GB)",
    sub: "$0.10/day",
    href: "/order?size=sm",
  },
  {
    section: "Quick deploy",
    icon: "⊕",
    title: "Deploy Standard (2 vCPU · 2 GB)",
    sub: "$0.20/day",
    href: "/order?size=md",
  },
  {
    section: "Quick deploy",
    icon: "⊕",
    title: "Deploy Performance (4 vCPU · 4 GB)",
    sub: "$0.40/day",
    href: "/order?size=lg",
  },
  {
    section: "Documentation",
    icon: "¶",
    title: "REST API reference",
    sub: "openapi.json",
    href: "https://cloud.hyrule.host/openapi.json",
  },
  {
    section: "Documentation",
    icon: "¶",
    title: "x402 manifest",
    sub: "EIP-3009 · Base",
    href: "https://cloud.hyrule.host/.well-known/x402.json",
  },
  {
    section: "Documentation",
    icon: "¶",
    title: "Agent guide (llms.txt)",
    sub: "/llms.txt",
    href: "/llms.txt",
  },
];

let overlay: HTMLDivElement | null = null;
let listEl: HTMLElement | null = null;
let inputEl: HTMLInputElement | null = null;
let items: Command[] = [];
let active = 0;
let query = "";

function escapeHtml(s: unknown): string {
  return String(s).replace(
    /[&<>"']/g,
    (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m] as string,
  );
}

function build(): void {
  overlay = document.createElement("div");
  overlay.className = "cmdk-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="cmdk-modal" role="dialog" aria-label="Command palette">
      <div class="cmdk-input-row">
        <span class="cmdk-prompt">⌕</span>
        <input class="cmdk-input" placeholder="search commands, machines, settings…" autocomplete="off">
        <span class="cmdk-esc"><kbd>esc</kbd></span>
      </div>
      <div class="cmdk-list"></div>
      <div class="cmdk-foot">
        <span><kbd>↑</kbd> <kbd>↓</kbd> navigate · <kbd>↵</kbd> open · <kbd>esc</kbd> close</span>
        <span>hyrule · cmdk</span>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  listEl = overlay.querySelector(".cmdk-list");
  inputEl = overlay.querySelector(".cmdk-input");

  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) close();
  });
  inputEl?.addEventListener("input", () => {
    query = inputEl?.value ?? "";
    active = 0;
    render();
  });
  inputEl?.addEventListener("keydown", (e) => {
    if (e.key === "Escape") return close();
    if (e.key === "ArrowDown") {
      e.preventDefault();
      active = Math.min(items.length - 1, active + 1);
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      active = Math.max(0, active - 1);
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const c = items[active];
      if (c) run(c);
    }
  });
}

function filtered(): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return COMMANDS;
  return COMMANDS.filter(
    (c) =>
      c.title.toLowerCase().includes(q) ||
      (c.sub && c.sub.toLowerCase().includes(q)) ||
      c.section.toLowerCase().includes(q),
  );
}

function render(): void {
  if (!listEl) return;
  items = filtered();
  if (!items.length) {
    listEl.innerHTML = `<div class="cmdk-empty">no matches for <code>${escapeHtml(query)}</code></div>`;
    return;
  }
  let html = "";
  let curSection: string | null = null;
  items.forEach((c, i) => {
    if (c.section !== curSection) {
      curSection = c.section;
      html += `<div class="cmdk-section">${escapeHtml(curSection)}</div>`;
    }
    html += `<div class="cmdk-row" data-active="${i === active}" data-i="${i}">
      <span class="cmdk-icon">${escapeHtml(c.icon)}</span>
      <span><div class="cmdk-title">${escapeHtml(c.title)}</div>${c.sub ? `<div class="cmdk-sub">${escapeHtml(c.sub)}</div>` : ""}</span>
      <span class="cmdk-meta"></span>
    </div>`;
  });
  listEl.innerHTML = html;
  listEl.querySelectorAll<HTMLElement>(".cmdk-row").forEach((r) => {
    r.addEventListener("mouseenter", () => {
      const i = parseInt(r.dataset.i ?? "0", 10);
      if (active !== i) {
        active = i;
        render();
      }
    });
    r.addEventListener("click", () => {
      const c = items[parseInt(r.dataset.i ?? "0", 10)];
      if (c) run(c);
    });
  });
}

function open(): void {
  if (!overlay) build();
  if (!overlay || !inputEl) return;
  overlay.hidden = false;
  query = "";
  active = 0;
  inputEl.value = "";
  render();
  setTimeout(() => inputEl?.focus(), 30);
}

function close(): void {
  if (overlay) overlay.hidden = true;
}

function run(c: Command | undefined): void {
  if (!c) return;
  close();
  if (c.href) window.location.href = c.href;
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (overlay && !overlay.hidden) {
      close();
    } else {
      open();
    }
  }
});
document.addEventListener("click", (e) => {
  const target = e.target as HTMLElement | null;
  const t = target?.closest("[data-cmdk-trigger]");
  if (t) {
    e.preventDefault();
    open();
  }
});

// Status-page copy buttons (small bonus).
document.addEventListener("click", (e) => {
  const target = e.target as HTMLElement | null;
  const b = target?.closest<HTMLElement>("[data-copy]");
  if (b && navigator.clipboard) {
    void navigator.clipboard.writeText(b.dataset.copy ?? "");
    const orig = b.textContent;
    b.textContent = "copied";
    setTimeout(() => {
      b.textContent = orig;
    }, 1200);
  }
});
