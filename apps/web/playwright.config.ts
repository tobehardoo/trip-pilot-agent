import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.PLAYWRIGHT_WEB_PORT ?? 4173)

export default defineConfig({
  testDir: './e2e',
  // qa-real-chain is a zero-mock real-chain spec that exercises the full
  // stack (Web -> Java -> MQ -> Python -> completion). It requires an
  // isolated backend stack, so it runs in the local QA environment but is
  // excluded from CI (no backend services there). The remaining specs mock
  // /api/** and run without a backend.
  ...(process.env.CI ? { testIgnore: /qa-real-chain\.spec\.ts$/ } : {}),
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(process.env.CI ? {} : { channel: 'chrome' }),
      },
    },
  ],
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
