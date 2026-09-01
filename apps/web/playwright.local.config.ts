// 本地分析用：复用已运行的 Vite dev server，使用 Playwright 自带 Chromium
// （本机未安装 channel 'chrome'）。不参与 CI。
import { defineConfig, devices } from '@playwright/test'
import base from './playwright.config'

export default defineConfig({
  ...base,
  use: {
    ...base.use,
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
  },
  webServer: undefined,
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
