import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { baseForMode } from "./buildConfig.ts";

export default defineConfig(({ mode }) => ({
  base: baseForMode(mode),
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        proof: "proof/index.html",
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
}));
