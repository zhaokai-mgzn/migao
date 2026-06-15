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

    // Web 页面 E2E（CI 自动跑，不含 LLM 依赖的 ai-agent/chat）
    {
      name: 'web',
      testMatch: /specs\/.*\.spec\.ts/,
      testIgnore: /specs\/auth\/|auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        storageState: './e2e/.auth/admin.json',
      },
      dependencies: ['auth-setup'],
    },

    // AI Agent 能力测试（手动触发，依赖 LLM，跑远程 dev 环境）
    {
      name: 'real',
      testMatch: /real\/.*\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        baseURL: process.env.E2E_REAL_BASE_URL || 'https://admin.migaozn.com',
        storageState: './e2e/.auth/admin.json',
      },
      dependencies: ['auth-setup'],
    },

    // 向后兼容：全部 authenticated 测试（不含 auth 页面和 real/）
    {
      name: 'chromium',
      testIgnore: /specs\/auth\/|real\/|auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome', // 使用本地已安装的 Chrome，而不是下载 Chromium
        storageState: './e2e/.auth/admin.json',
      },
      dependencies: ['auth-setup'],
    },
  ],

  // CI 也启动本地 Next.js dev server，E2E 测的是 PR 新代码而非旧部署
  webServer: {
    command: 'npm run dev',
    cwd: '../frontend/admin-web',
    port: 3001,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      // 前端 API 请求走远程 dev admin-api（CI 里没有本地 Java 后端）
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080',
    },
  },
});
