/**
 * Auth Helper — E2E authentication utilities
 *
 * Mirrors the auth flow in src/store/auth.ts and src/app/login/page.tsx:
 *   - POST /api/auth/admin/login with { username, password, tenantId }
 *   - zustand persist store key: 'auth-storage' (localStorage)
 *   - Cookie name: 'access_token'
 */
import { type Page, type APIRequestContext, request as pwRequest } from '@playwright/test'

/** Tokens returned by the login API */
export interface AuthTokens {
  accessToken: string
  refreshToken: string
  expiresIn: number
  tokenType: string
}

/** Subset of User stored in zustand persist state */
export interface AuthUser {
  id: string
  username: string
  name: string
  nickname?: string
  email?: string
  phone?: string
  roles?: string[]
  permissions?: string[]
  tenantId?: number
  tenantName?: string
}

/** The shape zustand persist writes to localStorage under 'auth-storage' */
interface ZustandPersistState {
  state: {
    accessToken: string
    refreshToken: string
    user: AuthUser | null
    isAuthenticated: boolean
    rememberMe: boolean
  }
  version: number
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080'

/**
 * Login via the backend API (bypasses the UI).
 * Returns the tokens from the LoginResponse.
 */
export async function loginViaApi(
  phone = '13800138000',
  code = '123456',
): Promise<AuthTokens> {
  const ctx: APIRequestContext = await pwRequest.newContext()
  try {
    const response = await ctx.post(`${API_BASE_URL}/api/auth/sms/login`, {
      data: { phone, code },
    })

    if (!response.ok()) {
      const body = await response.text()
      throw new Error(
        `loginViaApi failed (${response.status()}): ${body}`,
      )
    }

    const json = await response.json()
    // Backend wraps in { code: 200, data: { accessToken, refreshToken, ... } }
    const data = json.data ?? json
    return {
      accessToken: data.accessToken,
      refreshToken: data.refreshToken,
      expiresIn: data.expiresIn ?? 3600,
      tokenType: data.tokenType ?? 'Bearer',
    }
  } finally {
    await ctx.dispose()
  }
}

/**
 * Inject authentication state into the browser context.
 *
 * 1. Writes zustand persist JSON to localStorage under key 'auth-storage'
 * 2. Sets the 'access_token' cookie that middleware reads
 *
 * Must be called AFTER navigating to the app origin so localStorage/cookie
 * are set on the correct domain.
 */
export async function injectAuth(
  page: Page,
  tokens: AuthTokens,
  user: AuthUser | null = null,
): Promise<void> {
  const persistState: ZustandPersistState = {
    state: {
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
      user: user ?? {
        id: '1',
        username: 'admin',
        name: '管理员',
        roles: ['admin'],
        tenantId: 1,
        tenantName: '测试企业',
      },
      isAuthenticated: true,
      rememberMe: true,
    },
    version: 0,
  }

  // Write zustand persist state to localStorage
  await page.evaluate(
    ({ key, value }) => {
      localStorage.setItem(key, JSON.stringify(value))
    },
    { key: 'auth-storage', value: persistState },
  )

  // Set the cookie that Next.js middleware reads for route protection
  await page.evaluate((token) => {
    document.cookie = `access_token=${encodeURIComponent(token)}; path=/; SameSite=Lax; max-age=${7 * 86400}`
  }, tokens.accessToken)
}

/**
 * Full UI login flow through the login page (password tab).
 *
 * Login page structure (src/app/login/page.tsx):
 *   - Two tabs: "企业管理员登录" (SMS) | "员工登录" (password)
 *   - Password tab fields: #tenantCode, #username, #password
 *   - Submit button text: "登 录"
 *   - On success: redirects to /dashboard (or callbackUrl)
 */
export async function loginViaUI(
  page: Page,
  username: string,
  password: string,
  options?: { tenantCode?: string; expectSuccess?: boolean },
): Promise<void> {
  const { tenantCode = '', expectSuccess = true } = options ?? {}

  await page.goto('/login')

  // Click the "员工登录" tab to switch to password login
  await page.getByRole('button', { name: /员工登录/ }).click()

  // Fill tenant code if provided
  if (tenantCode) {
    await page.fill('#tenantCode', tenantCode)
  }

  // Fill username and password
  await page.fill('#username', username)
  await page.fill('#password', password)

  // Click the submit button — text is "登 录" (with a space)
  // Use a flexible locator that handles both "登 录" and "登录中..."
  const submitBtn = page.locator('form button[type="submit"]').last()
  await submitBtn.click()

  if (expectSuccess) {
    // Wait for successful redirect to dashboard
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 })
  }
}
