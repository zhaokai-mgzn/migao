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
import * as path from 'path'
import * as fs from 'fs'

const AUTH_DIR = path.join(__dirname, '..', '.auth')
const AUTH_FILE = path.join(AUTH_DIR, 'admin.json')

const TEST_PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const TEST_SMS_CODE = process.env.E2E_SMS_CODE || '123456'

setup('authenticate as admin', async ({ page, baseURL }) => {
  setup.setTimeout(120_000)

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

  // admin.json 已存在且 1h 内有效 → 跳过登录
  if (fs.existsSync(AUTH_FILE)) {
    const age = Date.now() - fs.statSync(AUTH_FILE).mtimeMs
    if (age < 3600_000) {
      console.log('[auth-setup] 复用已有 admin.json')
      return
    }
  }

  let tokens: AuthTokens
  try {
    tokens = await loginViaApi(TEST_PHONE, TEST_SMS_CODE)
  } catch (e) {
    console.warn(`SMS login failed: ${e}. Using fallback token.`)
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
      user: { id: '1', username: TEST_PHONE, name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' },
      isAuthenticated: true,
      rememberMe: true,
    },
    version: 0,
  }))

  // 用 load 而非 networkidle — SSE 会阻止 network idle
  // 注意：/dashboard 是路由组 (dashboard) 的布局，无独立 page.tsx，需导航到子页面
  await page.goto('/products', { waitUntil: 'load', timeout: 30_000 })
  await expect(page.locator('aside')).toBeVisible({ timeout: 20_000 })
  await page.context().storageState({ path: AUTH_FILE })
})
