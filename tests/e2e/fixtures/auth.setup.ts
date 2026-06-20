/**
 * Auth Setup — Global setup that runs once before all authenticated tests.
 *
 * 本地使用 E2E_MOCK_AUTH=true（playwright.config 非CI默认开启）跳过 SMS API。
 * CI 使用真实 SMS API 获取 token。
 */
import { test as setup, expect } from '@playwright/test'
import { loginViaApi, injectAuth, type AuthTokens } from '../helpers/auth.helper'
import * as path from 'path'
import * as fs from 'fs'

const AUTH_DIR = path.join(__dirname, '..', '.auth')
const AUTH_FILE = path.join(AUTH_DIR, 'admin.json')
const TEST_PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const TEST_SMS_CODE = process.env.E2E_SMS_CODE || '123456'

setup('authenticate as admin', async ({ page }) => {
  setup.setTimeout(120_000)
  if (!fs.existsSync(AUTH_DIR)) fs.mkdirSync(AUTH_DIR, { recursive: true })

  // admin.json 已存在且 1h 内有效 → 跳过登录
  if (fs.existsSync(AUTH_FILE)) {
    const age = Date.now() - fs.statSync(AUTH_FILE).mtimeMs
    if (age < 3600_000) { console.log('[auth-setup] 复用已有 admin.json'); return }
  }

  let tokens: AuthTokens
  try {
    tokens = await loginViaApi(TEST_PHONE, TEST_SMS_CODE)
  } catch (e) {
    console.warn(`SMS login failed: ${e}. Using fallback token.`)
    tokens = { accessToken: 'e2e-fallback-token', refreshToken: 'e2e-fallback-refresh', expiresIn: 3600, tokenType: 'Bearer' }
  }

  // Navigate to login page to establish origin, then inject auth
  await page.goto('/login', { waitUntil: 'load', timeout: 30_000 })
  await injectAuth(page, tokens, { id: '1', username: TEST_PHONE, name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' })

  // Reload to let zustand hydrate from localStorage + cookie
  await page.reload({ waitUntil: 'load', timeout: 15_000 })

  // Go directly to dashboard — AuthGuard sees cookie + hydrated zustand state
  await page.goto('/dashboard', { waitUntil: 'load', timeout: 30_000 })
  await expect(page.locator('aside')).toBeVisible({ timeout: 20_000 })
  await page.context().storageState({ path: AUTH_FILE })
})
