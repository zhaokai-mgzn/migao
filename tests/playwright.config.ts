import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// 本地开发无后端 SMS API，默认 mock。CI 由 workflow env 覆盖
if (!process.env.CI) process.env.E2E_MOCK_AUTH = 'true'

// ── 本地「服务身份」前置断言（issue #4313；配置加载期 ⇒ 早于 webServer 启动）──
// 病根：下面 webServer 曾写 `reuseExistingServer: !process.env.CI`（本地 = true）⇒ 只要 3001 上
// 已有服务在听（**另一个 checkout** / 上一轮跑留下的进程），Playwright 直接复用它、一条命令都不执行
// ⇒ 断言与截图都在本检出上判定，页面却来自别的检出 ⇒ 本地/CI 行为分叉 + 静默假绿。
// 与 #4249（xiaobu H5）同族但病根不同：这里是 `npm run dev`（按请求编译**当前源码**的 dev server），
// **没有「构建产物」这一层** ⇒ `tests/xiaobu_dist_freshness.py` 的内容指纹不适用（它判的是
// 「dist 是不是当前源码的产物」）。dev server 形态下的等价判据 = **服务身份**：
// 听 3001 的进程，其 cwd 是不是本检出的 frontend/admin-web。
const ADMIN_WEB_PORT = 3001
const ADMIN_WEB_DIR = path.resolve(__dirname, '../frontend/admin-web')
const IDENTITY_GUARD = path.resolve(__dirname, 'admin_web_devserver_identity.py')

// 三态（tests/admin_web_devserver_identity.py）：0 = 无外来服务风险 / 1 = 端口被**别的检出**占用
// ⇒ 失败关闭 / 3 = 未判定（无 lsof）⇒ 只告警不阻塞（硬拦面是下面的 reuseExistingServer: false，
// 任何已存在的监听者都会被它拒绝复用）。CI：整块不执行 ⇒ CI 侧零新增行为。
if (!process.env.CI) {
  const identity = spawnSync('python3', [IDENTITY_GUARD, 'check', '--project', ADMIN_WEB_DIR, '--port', String(ADMIN_WEB_PORT)], {
    encoding: 'utf8',
  })
  if (identity.stdout) process.stdout.write(identity.stdout)
  if (identity.stderr) process.stderr.write(identity.stderr)
  // spawn 失败（如本机没有 python3）等同「未判定」：不阻塞本地 E2E，硬拦面仍在 reuseExistingServer。
  const undecidable = identity.status === 3 || identity.error !== undefined
  if (identity.status !== 0 && !undecidable) {
    throw new Error(
      `[admin-web-e2e] 本地起服务前的「服务身份」前置断言未通过（exit ${identity.status}）：` +
        '拒绝在「3001 已被可能是另一个检出的服务占用」的状态下跑 E2E —— ' +
        '那会让断言与截图在本检出上判定、却跑在别人的代码上（静默假绿，issue #4313）。' +
        '请先停掉占用 3001 的进程再重跑。'
    )
  }
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts|.*auth\.setup\.ts/,
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 4 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    // 本地开发默认 mock SMS API（无后端），CI 通过 env 传入真实 API 地址
    testIdAttribute: 'data-testid',
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

    // 注：'real' project（tests/e2e/real，真实 LLM UI 测试）已于 2026-08-29 删除——
    // 与 backend pytest e2e/real（API 层，e2e-real.yml 每日调度）1:1 重复但从未入 CI，维护成本双倍。
    // 真实 LLM 能力验证以 pytest 层为准；chat.page.ts 等被 specs/chat 复用的资源保留。

    // 注：曾经的 'chromium' 项目与 'web' 筛选结果完全等价（同跑 specs/ 除 auth），
    // 会导致每个 spec 执行两遍，已于 2026-08-28 删除。显式传文件路径时 'web' 已兼容。
  ],

  // CI 也启动本地 Next.js dev server，E2E 测的是 PR 新代码而非旧部署
  webServer: {
    command: 'npm run dev',
    cwd: '../frontend/admin-web',
    port: ADMIN_WEB_PORT,
    // issue #4313：字面量 false（**本地也不再静默复用**）。复用「已在 3001 上监听的服务」时
    // Playwright 不执行任何 webServer 命令，可能跑在**另一个 checkout** 的代码上 ⇒ 静默假绿。
    // 端口被占 ⇒ 报错退出（可行动），而不是复用。CI 侧原本即为 false（旧写法 `!process.env.CI`）⇒ 行为不变。
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      // 前端 API 请求走远程 dev admin-api（CI 里没有本地 Java 后端）
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080',
    },
  },
});
