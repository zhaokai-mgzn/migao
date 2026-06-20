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
 *   2. Navigates to the app origin (so localStorage/cookies target the right domain)
 *   3. Injects zustand persist state ('auth-storage') + access_token cookie
 *   4. Saves browser storage state to tests/e2e/.auth/admin.json
 *
 * NOTE: If the playwright config testDir does not cover this fixture directory,
 *       move this file to tests/e2e/specs/auth.setup.ts or adjust testDir.
 */
import { test as setup, expect } from '@playwright/test'
import { loginViaApi, type AuthTokens } from '../helpers/auth.helper'
import * as path from 'path'
import * as fs from 'fs'

const AUTH_DIR = path.join(__dirname, '..', '.auth')
const AUTH_FILE = path.join(AUTH_DIR, 'admin.json')

// 固定测试账号（SMS 验证码登录，dev 万能码 123456）
const TEST_PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const TEST_SMS_CODE = process.env.E2E_SMS_CODE || '123456'

setup('authenticate as admin', async ({ page }) => {
  // CI 冷启动时 Next.js dev server 首次编译需 15-25s，确保不超时
  setup.setTimeout(120_000)

  // Ensure .auth directory exists
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
  }

  // Step 1: Login via SMS API
  let tokens: AuthTokens
  try {
    tokens = await loginViaApi(TEST_PHONE, TEST_SMS_CODE)
  } catch (e) {
    console.warn(`SMS login failed: ${e}. Using fallback token for mocked E2E tests.`)
    tokens = {
      accessToken: 'e2e-fallback-token',
      refreshToken: 'e2e-fallback-refresh',
      expiresIn: 3600,
      tokenType: 'Bearer',
    }
  }

  // Step 2: Set cookies BEFORE first navigation so AuthGuard sees them on load
  await page.context().addCookies([
    {
      name: 'access_token',
      value: tokens.accessToken,
      domain: 'localhost',
      path: '/',
      sameSite: 'Lax' as const,
    },
  ])

  // Step 3: Also pre-populate localStorage via addInitScript (runs before any page script)
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

  // Step 4: Navigate directly to dashboard (auth is pre-set before page load)
  await page.goto('/dashboard', { waitUntil: 'networkidle', timeout: 60_000 })

  // DEBUG
  console.log('DEBUG page URL:', page.url())
  console.log('DEBUG page title:', await page.title())

  // Step 5: Verify sidebar is visible
  await expect(page.locator('aside, nav, [class*="sidebar"], [class*="Sidebar"]').first()).toBeVisible({ timeout: 20_000 })

  // Step 6: Save storage state (localStorage + cookies) for other tests
  await page.context().storageState({ path: AUTH_FILE })
})
