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
  },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.js", "tests/integration/**/*.test.js"],
    coverage: {
      provider: "v8",
      reporter: ["cobertura"],
      include: ["src/**"],
      reportsDirectory: "./coverage",
    },
  },
});
