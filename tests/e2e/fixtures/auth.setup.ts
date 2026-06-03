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
import { loginViaApi, injectAuth } from '../helpers/auth.helper'
import * as path from 'path'
import * as fs from 'fs'

// Align with playwright.config.ts: TMP_DIR = './tmp' (relative to tests/)
// __dirname = tests/e2e/fixtures → ../../tmp/.auth
const AUTH_DIR = path.join(__dirname, '..', '..', 'tmp', '.auth')
const AUTH_FILE = path.join(AUTH_DIR, 'admin.json')

// Test credentials — override via environment variables in CI
const TEST_USERNAME = process.env.TEST_USERNAME || 'admin'
const TEST_PASSWORD = process.env.TEST_PASSWORD || 'admin123'
const TEST_TENANT_ID = Number(process.env.TEST_TENANT_ID) || 1

setup('authenticate as admin', async ({ page }) => {
  // Ensure .auth directory exists
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
  }

  // Step 1: Login via API to get tokens
  const tokens = await loginViaApi(TEST_USERNAME, TEST_PASSWORD, TEST_TENANT_ID)

  // Step 2: Navigate to the app origin so localStorage/cookie target the right domain.
  // NOTE: '/' is a public corporate landing page — it does NOT redirect to dashboard.
  // We navigate to '/dashboard/' (protected route) so AuthGuard can verify auth state.
  await page.goto('/dashboard/')

  // Step 3: Inject auth state into the browser
  await injectAuth(page, tokens, {
    id: '1',
    username: TEST_USERNAME,
    name: '管理员',
    roles: ['admin'],
    tenantId: TEST_TENANT_ID,
    tenantName: '测试企业',
  })

  // Step 4: Reload to let the app pick up the auth state
  await page.reload()

  // Step 5: Verify we're authenticated — should see the sidebar / dashboard
  // The sidebar renders with class 'fixed left-0' and contains navigation links
  await expect(page.locator('aside')).toBeVisible({ timeout: 15_000 })

  // Step 6: Save storage state (localStorage + cookies) for other tests
  await page.context().storageState({ path: AUTH_FILE })
})
