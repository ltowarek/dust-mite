import { defineConfig } from "vite";

export default defineConfig({
  build: {
    rollupOptions: {
      onwarn(warning, defaultHandler) {
        if (warning.code === "EVAL" && warning.id?.includes("@protobufjs/inquire")) {
          return;
        }
        defaultHandler(warning);
      },
    },
  },
  fmt: {
    ignorePatterns: [],
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: ["js"],
    proxy: {
      // Mimir has no CORS support, so the browser's OTLP metrics exporter
      // can't POST to it cross-origin. Proxying keeps the request
      // same-origin (to this dev server) so no CORS header is needed.
      "/otlp": {
        target: "http://mimir:8080",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    reporters: ["default", "junit"],
    outputFile: { junit: "./test-report.junit.xml" },
    include: ["tests/unit/**/*.test.js", "tests/integration/**/*.test.js"],
    coverage: {
      provider: "v8",
      reporter: ["cobertura"],
      include: ["src/**"],
      reportsDirectory: "./coverage",
    },
  },
});
