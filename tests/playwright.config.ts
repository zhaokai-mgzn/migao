import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts|.*auth\.setup\.ts/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    // Auth setup: runs once, saves storage state
    {
      name: 'auth-setup',
      testMatch: /auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
      },
    },

    // Unauthenticated tests (login, register)
    {
      name: 'auth-pages',
      testMatch: /specs\/auth\//,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome', // 使用本地已安装的 Chrome，而不是下载 Chromium
      },
    },

    // All authenticated tests use saved auth state
    {
      name: 'chromium',
      testIgnore: /specs\/auth\/|auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome', // 使用本地已安装的 Chrome，而不是下载 Chromium
        storageState: './e2e/.auth/admin.json',
      },
      dependencies: ['auth-setup'],
    },
  ],

  webServer: process.env.CI
    ? undefined
    : {
        command: 'npm run dev',
        cwd: '../frontend/admin-web',
        port: 3001,
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
