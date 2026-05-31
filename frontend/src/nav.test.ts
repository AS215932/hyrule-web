import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { initNav } from "./nav";

// Minimal stand-in for the base.html header + drawer markup. nav.ts derives all
// state from the live DOM, so we just rebuild this between tests.
function setup(): void {
  document.documentElement.className = "";
  document.body.className = "";
  document.body.innerHTML = `
    <header>
      <button class="nav-toggle" type="button" data-nav-toggle
              aria-expanded="false" aria-controls="mobile-nav"
              aria-label="Open navigation">menu</button>
    </header>
    <div class="mobile-nav-backdrop" data-nav-backdrop hidden></div>
    <nav id="mobile-nav" class="mobile-nav" aria-label="Mobile primary" hidden>
      <button class="mobile-nav-close" type="button" data-nav-close
              aria-label="Close navigation">close</button>
      <div class="mobile-nav-links">
        <a href="#home">Home</a>
        <a href="#services">Services</a>
      </div>
    </nav>
    <main><a href="#elsewhere" id="outside">outside</a></main>`;
  initNav();
}

const toggle = (): HTMLElement => document.querySelector<HTMLElement>("[data-nav-toggle]")!;
const drawer = (): HTMLElement => document.getElementById("mobile-nav")!;
const backdrop = (): HTMLElement => document.querySelector<HTMLElement>("[data-nav-backdrop]")!;

function click(el: Element): void {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
}
function keydown(key: string, init: KeyboardEventInit = {}): void {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
  );
}

beforeEach(() => setup());
afterEach(() => {
  document.body.innerHTML = "";
  document.documentElement.className = "";
  document.body.className = "";
});

describe("mobile nav drawer", () => {
  it("starts closed", () => {
    expect(drawer().hidden).toBe(true);
    expect(backdrop().hidden).toBe(true);
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(document.documentElement.classList.contains("nav-open")).toBe(false);
  });

  it("opens on toggle click: drawer + backdrop shown, aria-expanded, scroll lock, focus moved in", () => {
    click(toggle());
    expect(drawer().hidden).toBe(false);
    expect(backdrop().hidden).toBe(false);
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(document.documentElement.classList.contains("nav-open")).toBe(true);
    expect(document.body.classList.contains("nav-open")).toBe(true);
    expect(drawer().contains(document.activeElement)).toBe(true);
  });

  it("closes on a second toggle click and restores focus to the toggle", () => {
    toggle().focus();
    click(toggle()); // open
    click(toggle()); // close
    expect(drawer().hidden).toBe(true);
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle());
  });

  it("closes on Escape", () => {
    click(toggle());
    keydown("Escape");
    expect(drawer().hidden).toBe(true);
  });

  it("closes on backdrop click", () => {
    click(toggle());
    click(backdrop());
    expect(drawer().hidden).toBe(true);
  });

  it("closes the close button", () => {
    click(toggle());
    click(drawer().querySelector("[data-nav-close]")!);
    expect(drawer().hidden).toBe(true);
  });

  it("closes when a drawer link is clicked", () => {
    click(toggle());
    click(drawer().querySelector("a")!);
    expect(drawer().hidden).toBe(true);
  });

  it("closes and clears the scroll lock on an htmx route change", () => {
    click(toggle());
    document.dispatchEvent(new Event("htmx:beforeSwap", { bubbles: true }));
    expect(drawer().hidden).toBe(true);
    expect(document.documentElement.classList.contains("nav-open")).toBe(false);
    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("clears the scroll lock on every close path", () => {
    click(toggle());
    expect(document.documentElement.classList.contains("nav-open")).toBe(true);
    keydown("Escape");
    expect(document.documentElement.classList.contains("nav-open")).toBe(false);
    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("traps focus within the drawer (Tab wraps last→first, Shift+Tab first→last)", () => {
    click(toggle());
    const focusables = drawer().querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    last.focus();
    keydown("Tab");
    expect(document.activeElement).toBe(first);

    first.focus();
    keydown("Tab", { shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("does not double-bind handlers when initNav runs repeatedly", () => {
    // A second binding would turn one click into open→close (net closed).
    initNav();
    initNav();
    click(toggle());
    expect(drawer().hidden).toBe(false);
  });
});
