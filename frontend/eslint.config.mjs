import { defineConfig } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    ignores: [".next/**", "node_modules/**", "out/**", "build/**"],
    rules: {
      // BFF/admin pages intentionally hydrate local UI state from async effects.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);
