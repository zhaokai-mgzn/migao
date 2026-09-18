import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

/**
 * 小布 H5 视觉回归专用配置
 *
 * 目标：验证 C 端 mini-app 的视觉/布局（无会话 UX、新品推荐、订单卡片），
 * 用 mock 数据保证确定性（不依赖真实 LLM/后端）。
 *
 * 运行（一键，本地无需先手动构建）：
 *   cd tests && npx playwright test specs/xiaobu/ --config=playwright.xiaobu.config.ts
 *
 * ## 产物新鲜度（issue #4249 —— 本配置的头号约束）
 *
 * **构建绝不写进 `webServer.command`。** 旧写法把 `taro build` 与起静态服务拼在同一条命令里，
 * 而本地 `reuseExistingServer: true`：只要 10086 上已有服务在听（上次跑遗留 / 另一个会话起的），
 * Playwright 直接复用它 ⇒ **整条命令一步都不执行（含构建）** ⇒ 服务旧 `dist/`。
 * 实测后果：`--update-snapshots` 报 `8 passed` 而基线 PNG 逐字节没变（被写成旧画面）——
 * 「断言绿 + 基线是旧产物」同时发生而没有任何东西变红，错基线提交后真实回归被永久放行。
 *
 * 现在：构建在**配置加载期**显式执行（早于 webServer 启动），并落/校验内容指纹
 * （`tests/xiaobu_dist_freshness.py`，H5 侧的 `assertDistFresh` 等价物，判据不依赖 mtime）。
 * `webServer` 只负责起静态服务；`reuseExistingServer: false` ⇒ 端口被占就**报错退出**，不再静默复用。
 */
const MINI_APP_DIR = path.resolve(__dirname, '../frontend/mini-app')
const DIST_GUARD = path.resolve(__dirname, 'xiaobu_dist_freshness.py')

// 本地：先显式构建（产物已新鲜则跳过）再校验，失败关闭；
// CI：只校验、**不构建**（构建由 mini-app.yml 的 Build H5 步骤单独完成），
//     无指纹（CI 不跑本护栏的构建链）⇒ exit 3「未判定」⇒ 只告警不阻塞 ⇒ CI 行为与改动前等价。
const freshnessMode = process.env.CI ? 'check' : 'ensure'
const freshness = spawnSync('python3', [DIST_GUARD, freshnessMode, '--project', MINI_APP_DIR], {
  encoding: 'utf8',
  env: {
    ...process.env,
    // 测试专用 env 覆盖 .env.local 的生产 URL（否则 H5 请求 app.migaozn.com 被 CORS 拦截）
    TARO_APP_API_URL: process.env.TARO_APP_API_URL || 'http://localhost:8080',
    TARO_APP_AI_API_URL: process.env.TARO_APP_AI_API_URL || 'http://localhost:8001',
  },
})
if (freshness.stdout) process.stdout.write(freshness.stdout)
if (freshness.stderr) process.stderr.write(freshness.stderr)
// exit 3 = 未判定（无构建指纹）：仅 CI 侧容忍（不新增拦截面）；其余非零一律失败关闭
const undecidableButExpected = process.env.CI && freshness.status === 3
if (freshness.status !== 0 && !undecidableButExpected) {
  throw new Error(
    `[xiaobu-h5] 产物新鲜度前置断言未通过（exit ${freshness.status}` +
      `${freshness.error ? `，${freshness.error.message}` : ''}）：` +
      '拒绝用「非当前源码的构建产物」跑视觉腿（issue #4249 —— 那会把基线写成旧画面且全绿）。' +
      '本地请修掉上面的报错后重跑；也可手动 cd frontend/mini-app && npm run build:h5。'
  )
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /specs\/xiaobu\/.*\.spec\.ts/,
  outputDir: 'test-results/xiaobu',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  // CI 冷 runner 首屏加载 10MB+ bundle 较慢（WIP 分支 CI 曾 5s 超时全挂），放宽到 15s
  expect: { timeout: 15_000 },

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

  // 静态托管 mini-app H5 产物 —— **只负责服务，不负责构建**（构建见上面的新鲜度前置断言）。
  // cwd 恒为 ../frontend/mini-app，webServer 命令的相对路径基于该 cwd。
  // reuseExistingServer: false ⇒ 端口被占用时直接报错（可行动），而不是复用「可能是另一个检出/上一次跑的」服务。
  webServer: {
    command: 'python3 -m http.server 10086 --directory dist',
    cwd: '../frontend/mini-app',
    port: 10086,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
