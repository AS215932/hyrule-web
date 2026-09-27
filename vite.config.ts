/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";

// Assets are served by FastAPI StaticFiles at /static/dist/ (uvicorn on the web
// VM behind Caddy). Vite emits a manifest so the Jinja `vite_asset()` helper can
// resolve the hashed filenames. The built bundle is committed and shipped by the
// Ansible deploy (issue #14) — there is no Node on the web host.
export default defineConfig({
  base: "/static/dist/",
  // Keep manifest module IDs repository-relative when dependencies come from a
  // shared symlinked cache instead of a physical node_modules directory.
  resolve: {
    preserveSymlinks: true,
  },
  build: {
    outDir: "hyrule_web/static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        // CSS-only global entry. Informational pages intentionally ship no JS.
        styles: "frontend/src/styles/app.css",
        // Loaded on the review/checkout page: the payment dispatcher.
        payment: "frontend/src/payment.ts",
        // Loaded on the status page: launch-proof status polling.
        status: "frontend/src/status.ts",
        // Loaded only where a one-time credential benefits from copy affordance.
        secrets: "frontend/src/secret-copy.ts",
        // Domain quote checkout, native payment polling, and signed transfer-out.
        domain: "frontend/src/domain.ts",
        // Passwordless login plus primary-wallet link and two-signature rotation.
        wallet_auth: "frontend/src/wallet-auth.ts",
        // Enabled-only x402 diagnostics, autonomous WebMCP, and browser wallets.
        toolbox: "frontend/src/toolbox.ts",
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["frontend/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["frontend/src/**/*.ts"],
      // No failing threshold in Phase 1 (entries are DOM-wiring); raised later.
      reporter: ["text-summary"],
    },
  },
});
