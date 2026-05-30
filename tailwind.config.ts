import type { Config } from "tailwindcss";

// Issue #14 facelift. Phase 1 stands Tailwind up ALONGSIDE the existing
// static/style.css with NO visual change: `preflight` (the reset) is disabled so
// the current look is untouched, and only utilities actually used in templates
// are emitted (purged via `content`). The visual-language refresh + the token
// expansion land in Phase 6; the tokens below are the initial port of the
// style.css :root palette so utilities resolve to the brand colors.
export default {
  content: ["./hyrule_web/templates/**/*.html", "./frontend/src/**/*.{ts,js}"],
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        bg: "#0e0e0f",
        "bg-2": "#141416",
        "bg-3": "#18181b",
        accent: "#f9a8d4",
        "accent-strong": "#ff7dc4",
        ok: "#86efac",
        warn: "#fcd34d",
        error: "#fb7185",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "IBM Plex Mono", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
