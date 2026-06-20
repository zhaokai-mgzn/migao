/**
 * Mock /api/auth/me — AuthProvider.initialize() calls this to validate
 * the stored token. Without this mock, the call fails → clearAuth()
 * → AuthGuard redirects to /login → all page elements not found.
 *
 * Usage: import { mockAuthMe } from '../../helpers/mock-auth-me'
 *        await mockAuthMe(page)
 */
export async function mockAuthMe(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: {
          id: '1', username: 'admin', name: '管理员',
          roles: ['admin'], tenantId: 1, tenantName: '测试企业',
        },
      }),
    })
  })
}
