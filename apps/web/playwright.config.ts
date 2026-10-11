import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against mock providers (plan §13): the full core loop runs with no keys,
 * so CI can exercise every screen deterministically.
 *
 * Starts both servers unless they are already running (local dev).
 */
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8010";
const WEB = process.env.E2E_WEB_URL ?? "http://127.0.0.1:3010";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Grant the microphone so the voice path can be exercised with a fake device.
    permissions: ["microphone"],
    launchOptions: {
      // CI downloads Playwright's own build; locally a system Chromium works too.
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    },
  },
  projects: [
    { name: "mobile", use: { ...devices["Pixel 7"] } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } },
  ],
  webServer: [
    {
      command: `cd ../api && TS_PROVIDER_MODE=mock DATABASE_URL=sqlite+aiosqlite:///:memory: QUOTA_SESSIONS_PER_DAY=0 TS_CORS_ORIGINS=${WEB} .venv/bin/uvicorn talkscene.main:app --port ${new URL(API).port}`,
      url: `${API}/healthz`,
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `NEXT_PUBLIC_API_URL=${API} pnpm build && NEXT_PUBLIC_API_URL=${API} pnpm exec next start -p ${new URL(WEB).port}`,
      url: WEB,
      reuseExistingServer: true,
      timeout: 240_000,
    },
  ],
});
