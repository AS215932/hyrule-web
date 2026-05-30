/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";

// Assets are served by FastAPI StaticFiles at /static/dist/ (uvicorn on the web
// VM behind Caddy). Vite emits a manifest so the Jinja `vite_asset()` helper can
// resolve the hashed filenames. The built bundle is committed and shipped by the
// Ansible deploy (issue #14) — there is no Node on the web host.
export default defineConfig({
  base: "/static/dist/",
  build: {
    outDir: "hyrule_web/static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        // Loaded on every page (base.html): command palette + global styles.
        main: "frontend/src/main.ts",
        // Loaded on the order form (order.html): durable-quote submit.
        order: "frontend/src/order.ts",
        // Loaded on the review/checkout page: the payment dispatcher.
        payment: "frontend/src/payment.ts",
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
