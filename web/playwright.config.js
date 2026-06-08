import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? "./test-results",
  use: { baseURL },
  projects: [
    {
      name: "firefox",
      testIgnore: "**/full_stack.test.js",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      // Requires the headless stack to be running (./scripts/start_headless.sh).
      name: "full_stack",
      testMatch: "**/full_stack.test.js",
      use: { ...devices["Desktop Firefox"] },
    },
  ],
  webServer: process.env.BASE_URL
    ? {
        url: process.env.BASE_URL,
        reuseExistingServer: true,
        timeout: 120_000,
      }
    : {
        command: "npx vp dev --port 5173",
        port: 5173,
        reuseExistingServer: true,
      },
});
