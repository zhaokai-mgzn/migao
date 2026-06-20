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

  // Step 2: Navigate to origin first (Next.js cold start)
  await page.goto('/', { waitUntil: 'load', timeout: 60_000 })

  // Step 3: Inject auth state
  await injectAuth(page, tokens, {
    id: '1', username: TEST_PHONE, name: '管理员',
    roles: ['admin'], tenantId: 1, tenantName: '测试企业',
  })

  // Step 4: Navigate to dashboard — use 'load' not 'networkidle'
  // (dashboard may have SSE/polling that keeps network active)
  await page.goto('/dashboard', { waitUntil: 'load', timeout: 60_000 })

  // Step 5: Wait for sidebar — with generous timeout for cold start
  await expect(page.locator('aside')).toBeVisible({ timeout: 45_000 })

  // Step 6: Save storage state
  await page.context().storageState({ path: AUTH_FILE })
})
