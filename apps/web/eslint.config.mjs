import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  globalIgnores([
    ".agents/**",
    ".next/**",
    ".playwright-cli/**",
    "output/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);
