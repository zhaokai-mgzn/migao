import { defineConfig, devices } from '@playwright/test';

// 所有测试临时文件统一输出到 tests/tmp/，方便清理：rm -rf tests/tmp/
const TMP_DIR = './tmp';

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts|.*auth\.setup\.ts/,
  outputDir: `${TMP_DIR}/test-results`,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : undefined,
  reporter: [['html', { open: 'never', outputFolder: `${TMP_DIR}/playwright-report` }], ['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    channel: 'chrome',
  },

  projects: [
    // Auth setup: runs once, saves storage state
    { name: 'auth-setup', testMatch: /auth\.setup\.ts/ },

    // Unauthenticated tests (login, register)
    {
      name: 'auth-pages',
      testMatch: /specs\/auth\//,
      use: { ...devices['Desktop Chrome'] },
    },

    // All authenticated tests use saved auth state
    {
      name: 'chromium',
      testIgnore: /specs\/auth\/|auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: `${TMP_DIR}/.auth/admin.json`,
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
