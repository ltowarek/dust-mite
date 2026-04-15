import { defineConfig } from "vite";

export default defineConfig({
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
  },
});
