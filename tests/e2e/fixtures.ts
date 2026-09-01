/**
 * E2E 公共 fixture — fixture 模式（E2E_MOCK_AUTH=true，无后端）下统一 mock 认证接口。
 *
 * 审计 07 P1-F1 后前端认证模型变更：登录态仅由 store（/api/auth/me 校验后置位）判定，
 * 不再读取 localStorage/可读 cookie。因此每个测试页面加载时 AuthProvider.initialize()
 * 都会请求 /api/auth/me —— fixture 模式必须 mock 它，否则会话无法恢复、守卫跳转登录页。
 */
import { test as base, expect } from '@playwright/test'

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            id: '1',
            username: '13800138000',
            name: '管理员',
            roles: ['admin'],
            tenantId: 1,
            tenantName: '测试企业',
          },
        }),
      })
    })
    await use(page)
  },
})

export { expect }
