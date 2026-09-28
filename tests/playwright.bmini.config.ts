import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

/**
 * B 端（米宝商家端）H5 的**几何 / 结构 e2e 腿**（issue #5759）
 *
 * ## 为什么要有它
 *
 * C 端（小布）早在 `mini-app.yml` 里有 `xiaobu-h5-visual`；**B 端一条 e2e 都没有** ⇒
 * #5754 的「底部 tabBar 是否真的居中」只能靠人眼 + 手工量（那次连着踩了两条 tabbar 病灶 + 一次构建陷阱）。
 * 本腿把「底栏几何」变成机器判据：`tests/e2e/specs/bmini/bmini-tabbar.spec.ts`。
 *
 * ## 与 C 端那条腿的**有意差别**（照实说明，别当成疏漏）
 *
 * 本腿判**几何数字**（上下留白对称 / 每格图标与文字水平居中 / 条贴底 / 四张图标两两不同），
 * **不做像素基线**：截图的 `darwin` / `linux` 双平台基线无法在本机生成齐全（CI 是 linux），
 * 而几何判据跨平台确定性更好（Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ 数字确定）。
 * ⇒ 「颜色/观感」类回归仍无机器判据（边界登记在 spec 头部）。
 *
 * ## 产物新鲜度（沿用 C 端 #4249 的教训，**不重写第二份实现**）
 *
 * 复用 `tests/xiaobu_dist_freshness.py`（它按 `--project <dir>` 参数化，是本仓唯一的 H5 产物指纹实现）：
 * · 本地 `ensure`：产物不新鲜就**先构建**再跑，构建失败 fail-closed（绝不服务旧 dist）；
 * · CI `check`：只校验（构建由 workflow 步骤单独完成）⇒ 无指纹 exit 3 只告警不阻塞，行为与 C 端一致。
 *
 * 运行（本地一键，无需先手动构建）：
 *   cd tests && npx playwright test specs/bmini/ --config=playwright.bmini.config.ts
 */
const BMINI_DIR = path.resolve(__dirname, '../frontend/bmini-app')
const DIST_GUARD = path.resolve(__dirname, 'xiaobu_dist_freshness.py')

const freshnessMode = process.env.CI ? 'check' : 'ensure'
const freshness = spawnSync('python3', [DIST_GUARD, freshnessMode, '--project', BMINI_DIR], {
  encoding: 'utf8',
  env: {
    ...process.env,
    // 与 C 端同口径：本地构建把接口指到 localhost（视觉腿不依赖后端；避免打到生产域）
    TARO_APP_API_URL: process.env.TARO_APP_API_URL || 'http://localhost:8080',
    TARO_APP_AI_API_URL: process.env.TARO_APP_AI_API_URL || 'http://localhost:8001',
  },
})
if (freshness.stdout) process.stdout.write(freshness.stdout)
if (freshness.stderr) process.stderr.write(freshness.stderr)
// exit 3 = 未判定（无构建指纹）：仅 CI 侧容忍；其余非零一律失败关闭
const undecidableButExpected = process.env.CI && freshness.status === 3
if (freshness.status !== 0 && !undecidableButExpected) {
  throw new Error(
    `[bmini-h5] 产物新鲜度前置断言未通过（exit ${freshness.status}` +
      `${freshness.error ? `，${freshness.error.message}` : ''}）：` +
      '拒绝用「非当前源码的构建产物」跑几何腿（issue #4249 的教训）。' +
      '本地请修掉上面的报错后重跑；也可手动 cd frontend/bmini-app && npm run build:h5。',
  )
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /specs\/bmini\/.*\.spec\.ts/,
  outputDir: 'test-results/bmini',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  expect: { timeout: 15_000 },

  use: {
    testIdAttribute: 'data-testid',
    baseURL: process.env.BMINI_H5_URL || 'http://localhost:10087',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    viewport: { width: 390, height: 844 }, // iPhone 12/13 尺寸
  },

  projects: [
    {
      name: 'bmini-h5',
      testMatch: /specs\/bmini\/.*\.spec\.ts/,
      // 用本地已安装 Chrome（与 C 端那条腿同口径），避免下载 Playwright 浏览器
      use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 390, height: 844 } },
    },
  ],

  // 静态托管 bmini H5 产物 —— **只服务，不构建**（构建见上面的新鲜度前置断言）。
  // reuseExistingServer: false ⇒ 端口被占直接报错（可行动），而不是复用「可能是另一个检出/上一次跑的」服务。
  webServer: {
    command: 'python3 -m http.server 10087 --directory dist',
    cwd: '../frontend/bmini-app',
    port: 10087,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
