import { defineConfig, devices } from '@playwright/test'

/**
 * 小布 H5 视觉回归专用配置
 *
 * 目标：验证 C 端 mini-app 的视觉/布局（无会话 UX、新品推荐、订单卡片），
 * 用 mock 数据保证确定性（不依赖真实 LLM/后端）。
 *
 * 运行：
 *   1. cd frontend/mini-app && npm run build:h5   # 产出 dist/（H5 产物）
 *   2. npx playwright test specs/xiaobu/ --config=playwright.xiaobu.config.ts
 *
 * webServer：用静态服务器提供 mini-app/dist/（Taro H5 产物）。
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /specs\/xiaobu\/.*\.spec\.ts/,
  outputDir: 'test-results/xiaobu',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    testIdAttribute: 'data-testid',
    baseURL: process.env.XIAOBU_H5_URL || 'http://localhost:10086',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    viewport: { width: 390, height: 844 }, // iPhone 12/13 尺寸
    // 视觉基线路径：tests/e2e/specs/xiaobu/__screenshots__
    snapshotPathTemplate: '{testDir}/specs/xiaobu/__screenshots__/{arg}{ext}',
  },

  projects: [
    {
      name: 'xiaobu-h5',
      testMatch: /specs\/xiaobu\/.*\.spec\.ts/,
      // 使用本地已安装 Chrome（同 admin-web E2E），避免下载 Playwright 浏览器
      use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 390, height: 844 } },
    },
  ],

  // 静态托管 mini-app H5 产物。
  // 关键：测试专用 env 覆盖 .env.local 的生产 URL（否则 H5 请求 app.migaozn.com 被 CORS 拦截），
  // 先 taro build 注入 localhost 地址到 dist/，再 python http.server 托管（hash 路由，SPA 无需 rewrite）。
  webServer: {
    command: [
      'TARO_APP_API_URL=http://localhost:8080 TARO_APP_AI_API_URL=http://localhost:8001',
      'npx taro build --type h5 >/dev/null 2>&1;',
      'python3 -m http.server 10086 --directory dist',
    ].join(' '),
    cwd: '../frontend/mini-app',
    port: 10086,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
