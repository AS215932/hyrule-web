/* Hyrule Cloud mobile navigation drawer — issue #8, Phase 6 (PR 1).
 *
 * Below 720px the desktop `.site-nav` is hidden (static/style.css), leaving the
 * primary nav unreachable. This wires the header hamburger (`[data-nav-toggle]`)
 * to an accessible off-canvas drawer (`#mobile-nav`): aria-expanded sync, focus
 * trap + restore, Esc, backdrop click, body scroll-lock, and close-on-route-change
 * (hx-boost swaps the body, so we clear state on `htmx:beforeSwap`).
 *
 * Handlers are bound ONCE on `document` (delegation, mirroring cmdk.ts) and all
 * open/closed state is derived from the live DOM (`#mobile-nav[hidden]`), so the
 * module is robust to hx-boost body swaps and never double-binds on re-init. */

const TOGGLE_SEL = "[data-nav-toggle]";
const CLOSE_SEL = "[data-nav-close]";
const BACKDROP_SEL = "[data-nav-backdrop]";
const DRAWER_ID = "mobile-nav";
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

// htmx fires these on boosted navigations; closing on the first clears the
// scroll-lock + state before the body content is swapped out.
const ROUTE_EVENTS = ["htmx:beforeSwap", "htmx:pushedIntoHistory", "htmx:historyRestore"];

let lastFocused: HTMLElement | null = null;
let bound = false;

function drawer(): HTMLElement | null {
  return document.getElementById(DRAWER_ID);
}
function toggleBtn(): HTMLElement | null {
  return document.querySelector<HTMLElement>(TOGGLE_SEL);
}
function backdrop(): HTMLElement | null {
  return document.querySelector<HTMLElement>(BACKDROP_SEL);
}
function isOpen(): boolean {
  const d = drawer();
  return !!d && !d.hidden;
}

function open(): void {
  const d = drawer();
  if (!d || isOpen()) return;
  const active = document.activeElement;
  lastFocused = active instanceof HTMLElement ? active : toggleBtn();
  d.hidden = false;
  const bd = backdrop();
  if (bd) bd.hidden = false;
  toggleBtn()?.setAttribute("aria-expanded", "true");
  document.documentElement.classList.add("nav-open");
  document.body.classList.add("nav-open");
  d.querySelector<HTMLElement>(FOCUSABLE)?.focus();
}

function close(restoreFocus = true): void {
  const d = drawer();
  const wasOpen = isOpen();
  if (d) d.hidden = true;
  const bd = backdrop();
  if (bd) bd.hidden = true;
  toggleBtn()?.setAttribute("aria-expanded", "false");
  document.documentElement.classList.remove("nav-open");
  document.body.classList.remove("nav-open");
  if (restoreFocus && wasOpen) {
    const target = lastFocused && document.contains(lastFocused) ? lastFocused : toggleBtn();
    target?.focus();
  }
  lastFocused = null;
}

function trapFocus(e: KeyboardEvent): void {
  const d = drawer();
  if (!d) return;
  const nodes = Array.from(d.querySelectorAll<HTMLElement>(FOCUSABLE));
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  const activeInDrawer = d.contains(document.activeElement);
  if (e.shiftKey && (document.activeElement === first || !activeInDrawer)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (document.activeElement === last || !activeInDrawer)) {
    e.preventDefault();
    first.focus();
  }
}

function onClick(e: MouseEvent): void {
  const t = e.target as HTMLElement | null;
  if (!t) return;
  if (t.closest(TOGGLE_SEL)) {
    e.preventDefault();
    if (isOpen()) close();
    else open();
    return;
  }
  if (!isOpen()) return;
  if (t.closest(CLOSE_SEL)) {
    e.preventDefault();
    close();
    return;
  }
  if (t.closest(BACKDROP_SEL)) {
    close();
    return;
  }
  // A link inside the drawer navigates away — close (no focus restore, we're leaving).
  const d = drawer();
  if (d && d.contains(t) && t.closest("a")) close(false);
}

function onKeydown(e: KeyboardEvent): void {
  if (!isOpen()) return;
  if (e.key === "Escape") {
    e.preventDefault();
    close();
  } else if (e.key === "Tab") {
    trapFocus(e);
  }
}

function onRouteChange(): void {
  close(false);
}

/** Bind the document-level delegated handlers. Idempotent — safe to call more
 *  than once (subsequent calls are no-ops), so re-imports never double-bind. */
export function initNav(): void {
  if (bound) return;
  bound = true;
  document.addEventListener("click", onClick);
  document.addEventListener("keydown", onKeydown);
  for (const evt of ROUTE_EVENTS) document.addEventListener(evt, onRouteChange);
}
