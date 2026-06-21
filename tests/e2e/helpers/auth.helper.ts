/**
 * Auth Helper — E2E authentication utilities
 *
 * Mirrors the auth flow in src/store/auth.ts and src/app/login/page.tsx:
 *   - POST /api/auth/sms/login with { phone, code }
 *   - zustand persist store key: 'auth-storage' (localStorage)
 *   - Cookie name: 'access_token'
 */
import { type Page, type APIRequestContext, request as pwRequest } from '@playwright/test'
import { withRetry } from './retry.helper'

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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080'

/**
 * Login via the backend SMS API (bypasses the UI).
 * Uses universal dev SMS code 123456 — works across all environments.
 *
 * 设 E2E_MOCK_AUTH=true 可跳过真实 API 调用，用 mock token 直接注入。
 * 适用于本地开发（无后端）或 CI 网络受限场景。
 * mock token 配合 addCookies + addInitScript 可正常通过 AuthGuard。
 */
export async function loginViaApi(
  phone = '13800138000',
  code = '123456',
): Promise<AuthTokens> {
  // Mock 模式：跳过真实 API，直接返回 mock token
  if (process.env.E2E_MOCK_AUTH === 'true') {
    return {
      accessToken: 'e2e-mock-token',
      refreshToken: 'e2e-mock-refresh',
      expiresIn: 3600,
      tokenType: 'Bearer',
    }
  }

  // Retry on 5xx (transient server errors) — dev server may be briefly unavailable
  return withRetry(
    async () => {
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
    },
    {
      maxRetries: 3,
      baseDelayMs: 2000,
      // Only retry on 5xx or network errors — 4xx errors are permanent
      shouldRetry: (err) => {
        const msg = (err as Error).message || ''
        // 5xx, 503, 502, 504, or network errors (ECONNREFUSED, ETIMEDOUT, etc.)
        return /5\d\d|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EPIPE/.test(msg)
      },
    },
  )
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

