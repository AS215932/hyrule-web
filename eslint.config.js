import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["hyrule_web/static/dist/**", "node_modules/**"] },
  {
    files: ["frontend/**/*.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      // TypeScript already errors on undefined identifiers and understands DOM
      // lib globals; eslint's no-undef only produces false positives on TS.
      "no-undef": "off",
    },
  },
);
