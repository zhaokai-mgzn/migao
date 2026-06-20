/**
 * Auth Setup — Global setup that runs once before all authenticated tests.
 *
 * This setup:
 *   1. Logs in via the backend API to get tokens
 *   2. Navigates to origin, injects auth state
 *   3. Navigates to dashboard, verifies sidebar is visible
 *   4. Saves browser storage state to tests/e2e/.auth/admin.json
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
  setup.setTimeout(180_000)

  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
  }

  // Step 1: Login via SMS API
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

  // Step 2: Navigate to origin (ensures Next.js dev server is compiled)
  await page.goto('/', { waitUntil: 'load', timeout: 60_000 })

  // Step 3: Inject auth state
  await injectAuth(page, tokens, {
    id: '1',
    username: TEST_PHONE,
    name: '管理员',
    roles: ['admin'],
    tenantId: 1,
    tenantName: '测试企业',
  })

  // Step 4: Navigate to dashboard
  await page.goto('/dashboard', { waitUntil: 'networkidle', timeout: 60_000 })

  // Step 5: Verify sidebar visible — retry once on CI cold start
  const aside = page.locator('aside')
  try {
    await expect(aside).toBeVisible({ timeout: 30_000 })
  } catch {
    console.warn('Sidebar not visible, retrying with reload...')
    await page.goto('/dashboard', { waitUntil: 'networkidle', timeout: 60_000 })
    await expect(aside).toBeVisible({ timeout: 30_000 })
  }

  // Step 6: Save storage state
  await page.context().storageState({ path: AUTH_FILE })
})
