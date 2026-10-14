import { defineConfig, devices } from "@playwright/test";

/**
 * E2E smoke against a RUNNING stack (no mocks):
 *   local dev : API :8000 + DB worker + Vite :5173  →  E2E_BASE_URL=http://localhost:5173 (default)
 *   compose   : nginx :8080                          →  E2E_BASE_URL=http://localhost:8080
 * Locally the installed Microsoft Edge is used (PW_CHANNEL=msedge); CI installs Chromium.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 60_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
    locale: "ko-KR",
  },
  projects: [
    {
      name: "desktop",
      use: process.env.PW_CHANNEL ? { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL, viewport: { width: 1440, height: 900 } } : { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
