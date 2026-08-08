/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    // Hot-reload dev flow: `npm run dev` serves src/ with HMR and proxies
    // API calls to a separately running FastAPI backend (serve.py, default
    // port 8770). Override with OVERSEER_API for a non-default port, e.g.
    //   OVERSEER_API=http://127.0.0.1:8771 npm run dev
    proxy: {
      "/api": process.env.OVERSEER_API ?? "http://127.0.0.1:8770",
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    // RTL's auto-cleanup-between-tests detection checks for a GLOBAL
    // `afterEach` (see @testing-library/react/dist/index.js) — without this,
    // multi-`it()` component test files silently accumulate every render in
    // the same jsdom document, and role/text queries start matching stale
    // nodes from earlier tests (found while writing Chunk 4's TileShell
    // tests). Existing test files use unique query text per test so the gap
    // never surfaced before.
    globals: true,
  },
});
