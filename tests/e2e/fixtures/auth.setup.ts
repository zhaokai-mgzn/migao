/**
 * Auth Setup — Global setup that runs once before all authenticated tests.
 *
 * Playwright config (playwright.config.ts):
 *   - Project 'auth-setup' matches this file: testMatch: /auth\.setup\.ts/
 *   - Project 'chromium' depends on 'auth-setup' and loads:
 *       storageState: './tests/e2e/.auth/admin.json'
 *
 * This setup:
 *   1. Logs in via the backend API to get tokens
 *   2. Pre-sets cookies and localStorage via addCookies / addInitScript
 *      (must happen before first navigation — AuthGuard checks on page load)
 *   3. Navigates to dashboard to verify sidebar is visible
 *   4. Saves browser storage state to tests/e2e/.auth/admin.json
 *
 * 本地使用 E2E_MOCK_AUTH=true（playwright.config 非CI默认开启）跳过 SMS API。
 * CI 使用真实 SMS API 获取 token。
 */
import { test as setup, expect } from '@playwright/test'
import { loginViaApi, type AuthTokens } from '../helpers/auth.helper'
// 复用判据（issue #6411）：登录态是否还有效由 token 自己的 `exp` 决定，不是文件 mtime。
// 无依赖 `.mjs` 是刻意的（与 helpers/api-base-url.mjs 同一范式）—— 判定要能被
// tests/unit_ci_workflows/ 的判据用**真 node** 跑一次（行为面），那边不装 tests/node_modules。
import { decideAuthStateReuse } from '../helpers/auth-state-freshness.mjs'
import * as path from 'path'
import * as fs from 'fs'

const AUTH_DIR = path.join(__dirname, '..', '.auth')
const AUTH_FILE = path.join(AUTH_DIR, 'admin.json')

const TEST_PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const TEST_SMS_CODE = process.env.E2E_SMS_CODE || '123456'

setup('authenticate as admin', async ({ page, baseURL }) => {
  // issue #6729：本机负载高时（实测 load average 14~36 / 8 核）`(dashboard)` 组**首次**编译
  // 76~151s；原 120s 的**测试级**上限会先于导航超时到点（报错形态 = net::ERR_ABORTED /
  // frame detached，很容易被误读成「页面坏了」）⇒ 测试级预算随之放宽。**断言一字未放宽**（aside 必须可见）。
  setup.setTimeout(600_000)

  // 从 baseURL 提取域名，与应用的 COOKIE_DOMAIN 对齐
  let cookieDomain = 'localhost'
  if (baseURL) {
    const hostname = new URL(baseURL).hostname
    cookieDomain = hostname.endsWith('.migaozn.com') || hostname === 'migaozn.com'
      ? '.migaozn.com'
      : hostname
    // 如果是 IP 地址，cookie 不需要 domain 前缀
    if (/^\d+\.\d+\.\d+\.\d+$/.test(cookieDomain)) {
      cookieDomain = cookieDomain
    }
  }

  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
  }

  // 复用判据（issue #6411）：**先看登录态自己的有效期（JWT `exp`）**，mtime 只在解不出 `exp` 时兜底
  // （且出声）。原实现只看 mtime 的 1h 窗口 ⇒ 复用窗口（1h）> 登录态真实有效期（实测约 30min）
  // ⇒ 复用一个已失效的 token，所有 spec 连带红，而没有任何一句话指向「登录态过期」。
  // 判定为「需重登」时**直接走下面的真登录**（自愈），不报错退出。
  if (fs.existsSync(AUTH_FILE)) {
    let storageState: unknown = null
    try {
      storageState = JSON.parse(fs.readFileSync(AUTH_FILE, 'utf8'))
    } catch (e) {
      console.warn(`[auth-setup] admin.json 解析失败（${e}）⇒ 不复用，重新登录`)
    }
    const decision = decideAuthStateReuse({
      storageState,
      mtimeMs: fs.statSync(AUTH_FILE).mtimeMs,
    })
    // 结论一行出声：好让「莫名全红」的第一句话就是「是登录态过期」，而不是某个无关断言
    console.log(`[auth-setup] admin.json 复用判定 ${decision.reason}：${decision.message}`)
    if (decision.reuse) return
  }

  let tokens: AuthTokens
  try {
    tokens = await loginViaApi(TEST_PHONE, TEST_SMS_CODE)
  } catch (e) {
    // 仍保留占位 token 继续（CI / fixture 模式的既有容错），但**必须出声**：本机没有 admin-api 时，
    // 「重新登录也拿不到真 token」就是 issue #6411 的另一半，出路是 fixture 模式，不是删文件碰运气。
    console.warn(
      `[auth-setup] SMS login failed: ${e}. Using fallback token. ` +
        '（本机无 admin-api 时改用 fixture 模式：E2E_MOCK_AUTH=true 且 ' +
        'npx playwright test --no-deps <spec>，见 issue #6411）',
    )
    tokens = {
      accessToken: 'e2e-fallback-token',
      refreshToken: 'e2e-fallback-refresh',
      expiresIn: 3600,
      tokenType: 'Bearer',
    }
  }

  // 拦截 /api/auth/me — fixture 模式下无后端，返回 mock 用户信息
  // 防止 AuthProvider.initialize() 中 fetchUserInfo() 失败清空认证状态
  // 格式对齐 auth.ts:202 — const { data } = response.data，data 直接是 User 对象
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          id: '1',
          username: TEST_PHONE,
          name: '管理员',
          roles: ['admin'],
          // 黄金策唤出能力位（issue #5642 功能⑤）：admin 角色在后端恒为 ["*"] ⇒ 能力位为真。
          // 真实 /api/auth/me 就下发它；fixture 不补 ⇒ 授权门渲染成「需要管理员授权」、页面无面板。
          capabilities: { mibaoChat: true },
          tenantId: 1,
          tenantName: '测试企业',
        },
      }),
    })
  })

  // Pre-set auth BEFORE first navigation
  await page.context().addCookies([{
    name: 'access_token', value: tokens.accessToken, domain: cookieDomain, path: '/', sameSite: 'Lax' as const,
  }])
  await page.context().addInitScript((authJson: string) => {
    localStorage.setItem('auth-storage', authJson)
  }, JSON.stringify({
    state: {
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
      user: { id: '1', username: TEST_PHONE, name: '管理员', roles: ['admin'], capabilities: { mibaoChat: true }, tenantId: 1, tenantName: '测试企业' },
      isAuthenticated: true,
      rememberMe: true,
    },
    version: 0,
  }))

  // 用 load 而非 networkidle — SSE 会阻止 network idle
  // 注意：/dashboard 是路由组 (dashboard) 的布局，无独立 page.tsx，需导航到子页面
  // aside 超时 60s：Next.js dev 冷启动首屏编译慢（CI 曾 20s 超时 flaky，2026-08-29 加固）
  // 🔴 issue #6729 实测：**只放宽时间预算，断言一字未放宽**。本机高负载时 `next dev` 对
  // `(dashboard)` 组的**首次**编译实测 76~151s（curl 直测 `/products`：76.7s / 87.3s / 150.9s），
  // 而这里原来是 60s ⇒ **本地任何 E2E 都跑不起来**，且失败信息指向 `/products` 超时
  // （看起来像「页面坏了」，实际是「编译没编完」）。CI 跑的是构建后的静态服务，不受影响。
  // `domcontentloaded` 而非 `load`：本判据只要求「仪表盘外壳渲染出来（aside 可见）」，
  // 不必等全部子资源（图片/字体/SSE）—— 后者在 dev 下的等待时长不可控。
  await page.goto('/products', { waitUntil: 'domcontentloaded', timeout: 300_000 })
  await expect(page.locator('aside')).toBeVisible({ timeout: 120_000 })
  await page.context().storageState({ path: AUTH_FILE })
})
