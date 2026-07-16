import { purgeCSSPlugin } from "@fullhuman/postcss-purgecss";
import autoprefixer from "autoprefixer";
import tailwindcss from "tailwindcss";

export default {
  plugins: [
    tailwindcss(),
    autoprefixer(),
    purgeCSSPlugin({
      content: ["./hyrule_web/templates/**/*.html", "./frontend/src/**/*.ts"],
      defaultExtractor: (content) => content.match(/[A-Za-z0-9-_:/.[\]%]+/g) || [],
      safelist: {
        standard: [
          /^status-/,
          /^payment-/,
          /^finding-/,
          "pending",
          "ok",
          "error",
          "warning",
          "hidden",
        ],
        deep: [/^toolbox-/, /^domain-/, /^intent-/],
      },
    }),
  ],
};
