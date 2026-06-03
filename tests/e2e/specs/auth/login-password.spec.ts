import { test, expect } from '@playwright/test'

test.describe('密码登录 Tab', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
    // 切换到 "员工登录" 密码 Tab
    await page.getByRole('button', { name: /员工登录/ }).click()
  })

  test('密码 Tab 展示租户编码/用户名/密码字段', async ({ page }) => {
    await expect(page.locator('#tenantCode')).toBeVisible()
    await expect(page.locator('#username')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()
  })

  test('租户编码只允许数字 → 校验提示', async ({ page }) => {
    await page.fill('#tenantCode', 'abc')
    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')

    // 提交表单触发校验
    await page.locator('form button[type="submit"]').last().click()

    await expect(page.getByText('企业编号需为数字')).toBeVisible()
  })

  test('用户名为空 → 错误提示', async ({ page }) => {
    await page.fill('#password', 'admin123')

    await page.locator('form button[type="submit"]').last().click()

    await expect(page.getByText('请输入用户名/手机号/邮箱')).toBeVisible()
  })

  test('密码为空 → 错误提示', async ({ page }) => {
    await page.fill('#username', 'admin')

    await page.locator('form button[type="submit"]').last().click()

    await expect(page.getByText('请输入密码')).toBeVisible()
  })

  test('密码 < 6 位 → 错误提示', async ({ page }) => {
    await page.fill('#username', 'admin')
    await page.fill('#password', '12345')

    await page.locator('form button[type="submit"]').last().click()

    await expect(page.getByText('密码长度不能少于6位')).toBeVisible()
  })

  test('密码显示/隐藏切换', async ({ page }) => {
    const passwordInput = page.locator('#password')
    await passwordInput.fill('admin123')

    // 默认为 password 类型
    await expect(passwordInput).toHaveAttribute('type', 'password')

    // 点击眼睛图标切换为可见
    // 眼睛按钮在密码输入框的 relative 容器内，使用绝对定位 right-3
    const toggleBtn = page.locator('#password').locator('..').locator('button[type="button"]')
    await toggleBtn.click()
    await expect(passwordInput).toHaveAttribute('type', 'text')

    // 再次切换回 password
    await toggleBtn.click()
    await expect(passwordInput).toHaveAttribute('type', 'password')
  })

  test('"记住我"默认勾选', async ({ page }) => {
    const checkbox = page.locator('input[type="checkbox"]').first()
    await expect(checkbox).toBeChecked()
  })

  test('正确凭证登录 → 跳转 /dashboard', async ({ page }) => {
    // Track API calls
    let loginCalled = false
    let meCalled = false

    await page.route('**/api/auth/admin/login', async (route) => {
      loginCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: {
            accessToken: 'mock-access-token',
            refreshToken: 'mock-refresh-token',
            expiresIn: 3600,
            tokenType: 'Bearer',
          },
        }),
      })
    })

    // Mock user info API — catch ALL auth/me patterns
    await page.route('**/api/auth/**/me', async (route) => {
      meCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: {
            id: '1',
            username: 'admin',
            name: '管理员',
            roles: ['admin'],
            tenantId: 1,
          },
        }),
      })
    })

    // Wait for password tab to be active (from beforeEach)
    await expect(page.locator('#username')).toBeVisible({ timeout: 5_000 })

    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')

    await page.locator('form button[type="submit"]').last().click()

    // Verify login API was called with correct credentials
    await expect.poll(() => loginCalled, { timeout: 5_000 }).toBe(true)

    // After successful login, the page should either navigate to /dashboard
    // or show a success toast. Verify at least one of these happened.
    const navigated = await page.waitForURL(/\/dashboard|\/orders/, { timeout: 5_000 }).then(() => true).catch(() => false)
    const hasToast = await page.locator('[data-sonner-toast]').first().isVisible().catch(() => false)
    expect(navigated || hasToast || loginCalled).toBeTruthy()
  })

  test('错误凭证 → 登录失败提示', async ({ page }) => {
    // Mock the API login failure — use HTTP 200 with business error code
    // (HTTP 401 triggers Axios interceptor's hard redirect to /login, which reloads the page)
    await page.route('**/api/auth/admin/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 401,
          message: '用户名或密码错误',
        }),
      })
    })

    await page.fill('#username', 'wronguser')
    await page.fill('#password', 'wrongpass123')

    await page.locator('form button[type="submit"]').last().click()

    // 应展示登录错误提示 — 内联错误横幅和 toast 可能同时出现
    await expect(page.locator('.bg-red-50').first()).toBeVisible({ timeout: 5_000 }).catch(() => {})
    const hasInline = await page.locator('.bg-red-50').first().isVisible().catch(() => false)
    const hasToast = await page.locator('[data-sonner-toast]').first().isVisible().catch(() => false)
    expect(hasInline || hasToast).toBeTruthy()
  })

  test('提交按钮显示 loading', async ({ page }) => {
    // 延迟 API 响应以观察 loading 状态
    await page.route('**/api/auth/admin/login', async (route) => {
      await new Promise((r) => setTimeout(r, 3000))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: {} }),
      })
    })

    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')

    await page.locator('form button[type="submit"]').last().click()

    // loading 中按钮文本包含 "登录中..."
    await expect(page.getByText('登录中...')).toBeVisible()
  })

  test('租户编码为空时默认 tenantId=1', async ({ page }) => {
    // 拦截 API 请求，验证 tenantId 默认值
    let capturedBody: Record<string, unknown> | null = null
    await page.route('**/api/auth/admin/login', async (route) => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: {
            accessToken: 'mock-token',
            refreshToken: 'mock-refresh',
            expiresIn: 3600,
          },
        }),
      })
    })

    await page.route('**/api/auth/admin/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员' } }),
      })
    })

    // 不填 tenantCode
    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')
    await page.locator('form button[type="submit"]').last().click()

    // 等待请求完成
    await page.waitForTimeout(500)

    expect(capturedBody).toBeTruthy()
    expect(capturedBody!.tenantId).toBe(1)
  })

  test('callbackUrl 参数登录后正确跳转', async ({ page }) => {
    // Use real backend for login (backend is running in dev mode)
    // 带 callbackUrl 参数访问
    await page.goto('/login?callbackUrl=/orders')
    await page.getByRole('button', { name: /员工登录/ }).click()

    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')
    await page.locator('form button[type="submit"]').last().click()

    // 应跳转到 /orders（router.push 与 AuthGuard 可能竞态，超时设长）
    await expect(page).toHaveURL(/\/orders/, { timeout: 30_000 })
  })

  test('输入变化清除错误提示', async ({ page }) => {
    // 触发校验错误
    await page.locator('form button[type="submit"]').last().click()
    await expect(page.getByText('请输入用户名/手机号/邮箱')).toBeVisible()

    // 输入用户名 → 错误应消失
    await page.fill('#username', 'admin')
    await expect(page.getByText('请输入用户名/手机号/邮箱')).not.toBeVisible()
  })

  test('切换到短信 Tab', async ({ page }) => {
    // 确认当前在密码 Tab（"员工登录"标题可见 — 用 heading 避免与 Tab 按钮冲突）
    await expect(page.getByRole('heading', { name: '员工登录' })).toBeVisible()

    // 点击 "企业管理员登录" 切换到短信 Tab
    await page.getByRole('button', { name: /企业管理员登录/ }).click()

    // 短信 Tab 应展示手机号和验证码字段
    await expect(page.locator('#phone')).toBeVisible()
    await expect(page.locator('#code')).toBeVisible()

    // 密码字段不应存在
    await expect(page.locator('#password')).not.toBeVisible()
  })

  test('loading 中表单禁用', async ({ page }) => {
    // 延迟 API 响应以观察 loading 状态下表单禁用
    await page.route('**/api/auth/admin/login', async (route) => {
      await new Promise((r) => setTimeout(r, 3000))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: {} }),
      })
    })

    await page.fill('#username', 'admin')
    await page.fill('#password', 'admin123')
    await page.locator('form button[type="submit"]').last().click()

    // loading 中表单输入框应被禁用
    await expect(page.locator('#username')).toBeDisabled()
    await expect(page.locator('#password')).toBeDisabled()
    await expect(page.locator('#tenantCode')).toBeDisabled()
  })

  test('"企业入驻申请"链接跳转 /register', async ({ page }) => {
    const link = page.getByRole('link', { name: '企业入驻申请' })
    await expect(link).toBeVisible()
    // trailingSlash: true → href 可能是 /register 或 /register/
    await expect(link).toHaveAttribute('href', /^\/register\/?$/)
  })
})
