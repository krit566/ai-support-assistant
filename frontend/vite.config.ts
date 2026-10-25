import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // in development the API runs separately; /api is forwarded to it so the browser sees one origin (no CORS)
  server: { port: 5183, proxy: { "/api": "http://127.0.0.1:8103", "/health": "http://127.0.0.1:8103" } },
  preview: { port: 5183, proxy: { "/api": "http://127.0.0.1:8103" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
