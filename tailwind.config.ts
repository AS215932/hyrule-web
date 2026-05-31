import type { Config } from "tailwindcss";

// Issue #14 stood Tailwind up ALONGSIDE static/style.css with NO visual change
// (preflight disabled; only utilities used in `content` are emitted).
//
// Issue #8 (Phase 6, PR 2) expands the token port and adds the mobile-first
// breakpoint + fluid type scales — still config-only: NO preflight flip, NO
// template churn. Because no template uses the new tokens yet, Tailwind emits no
// new CSS (the built bundle is unchanged); the tokens become available for the
// template/component work in later PRs.
//
// Mode-sensitive values reference the style.css `:root` CSS variables rather than
// hardcoded literals, so the body-attribute modes keep flowing through any utility
// that uses them: `bg-bg` → `var(--bg)`, `p-pad-panel` → `var(--pad-panel)` (which
// body[data-density] overrides), `font-*` stays driven by `--font-body` in the base
// layer. The vars remain the single source of truth during the migration.
export default {
  content: ["./hyrule_web/templates/**/*.html", "./frontend/src/**/*.{ts,js}"],
  // `preflight` off: coexist with style.css's reset (flipped on in the final
  // Phase 6 PR). `container` off: Tailwind's built-in `.container` utility
  // collides with the legacy `.container` class used across the templates and
  // was overriding its fluid `width: min(var(--container), 100% - 2*gutter)`
  // with `width:100%` + stepped max-widths. Disabling it lets the intended
  // legacy container govern and stops this PR's `screens` change from re-pinning
  // the container width at the new breakpoints.
  corePlugins: { preflight: false, container: false },
  theme: {
    // Override (not extend) so the legacy desktop-first cutoffs (720/1024 in
    // style.css) and this mobile-first scale agree and Tailwind's default
    // sm:640 doesn't introduce a competing tier. md:720 matches the nav cutoff
    // used by the PR 1 drawer; xs:480 is the new small-phone tier.
    screens: {
      xs: "480px",
      md: "720px",
      lg: "1024px",
      xl: "1280px",
    },
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-2": "var(--bg-2)",
        "bg-3": "var(--bg-3)",
        panel: "var(--panel)",
        "panel-strong": "var(--panel-strong)",
        line: "var(--line)",
        "line-2": "var(--line-2)",
        "line-bright": "var(--line-bright)",
        text: "var(--text)",
        "text-muted": "var(--text-muted)",
        "text-soft": "var(--text-soft)",
        "text-dim": "var(--text-dim)",
        accent: "var(--accent)",
        "accent-strong": "var(--accent-strong)",
        "accent-soft": "var(--accent-soft)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        error: "var(--error)",
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
        sm: "var(--radius-sm)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        1: "var(--shadow-1)",
        2: "var(--shadow-2)",
      },
      spacing: {
        // `gutter` is fixed; row/pad-panel/gap-panel are density-driven (set by
        // body[data-density]) so utilities built on them respond to the mode.
        gutter: "var(--gutter)",
        row: "var(--row)",
        "pad-panel": "var(--pad-panel)",
        "gap-panel": "var(--gap-panel)",
      },
      maxWidth: {
        container: "var(--container)",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "IBM Plex Mono", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      // Fluid type scale for the refresh. Names mirror Tailwind's so utilities
      // read naturally; the lower clamp bounds keep today's compact body size.
      fontSize: {
        xs: ["clamp(0.72rem, 0.7rem + 0.1vw, 0.78rem)", { lineHeight: "1.5" }],
        sm: ["clamp(0.8rem, 0.77rem + 0.15vw, 0.875rem)", { lineHeight: "1.55" }],
        base: ["clamp(0.84rem, 0.8rem + 0.2vw, 0.95rem)", { lineHeight: "1.65" }],
        lg: ["clamp(1rem, 0.95rem + 0.3vw, 1.15rem)", { lineHeight: "1.55" }],
        xl: ["clamp(1.2rem, 1.1rem + 0.5vw, 1.5rem)", { lineHeight: "1.4" }],
        "2xl": ["clamp(1.5rem, 1.3rem + 1vw, 2.1rem)", { lineHeight: "1.25" }],
        "3xl": ["clamp(1.9rem, 1.5rem + 2vw, 3rem)", { lineHeight: "1.15" }],
        display: ["clamp(2.4rem, 1.8rem + 3vw, 4rem)", { lineHeight: "1.05" }],
      },
    },
  },
  plugins: [],
} satisfies Config;
