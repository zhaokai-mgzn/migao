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
import { loginViaApi, injectAuth, type AuthTokens } from '../helpers/auth.helper'
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

  // Step 1: Login via SMS API（CI 网络不稳时 fallback 到本地 token）
  let tokens: AuthTokens
  try {
    tokens = await loginViaApi(TEST_PHONE, TEST_SMS_CODE)
  } catch (e) {
    console.warn(`SMS login failed: ${e}. Using fallback token for mocked E2E tests.`)
    // CI 中使用 mock token — E2E 测试已 mock API 响应，不需要真实 JWT
    tokens = {
      accessToken: 'e2e-fallback-token',
      refreshToken: 'e2e-fallback-refresh',
      expiresIn: 3600,
      tokenType: 'Bearer',
    }
  }

  // Step 2: Navigate to the app so we're on the correct origin
  // Next.js dev server 首次编译较慢，用 domcontentloaded + 30s 超时
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })

  // Step 3: Inject auth state into the browser
  await injectAuth(page, tokens, {
    id: '1',
    username: TEST_PHONE,
    name: '管理员',
    roles: ['admin'],
    tenantId: 1,
    tenantName: '测试企业',
  })

  // Step 4: Navigate to dashboard to let the app pick up the auth state
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded', timeout: 30_000 })

  // Step 5: Verify we're authenticated — should see the sidebar / dashboard
  // The sidebar renders with class 'fixed left-0' and contains navigation links
  await expect(page.locator('aside')).toBeVisible({ timeout: 20_000 })

  // Step 6: Save storage state (localStorage + cookies) for other tests
  await page.context().storageState({ path: AUTH_FILE })
})
