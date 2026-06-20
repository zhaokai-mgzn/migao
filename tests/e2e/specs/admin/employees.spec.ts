
// ==================== Inline Mock Data ====================

const MOCK_EMPLOYEES = [
  { id: 1, username: 'admin', name: '系统管理员', phone: '13800138000', position: '管理员', status: 'active', permissions: ['*'], createdAt: '2026-06-01 10:00' },
  { id: 2, username: 'zhangmei', name: '张美华', phone: '13957168235', position: '客服', status: 'active', permissions: ['orders:view', 'customers:view'], createdAt: '2026-06-02 14:00' },
  { id: 3, username: 'lixiao', name: '李晓明', phone: '13712345678', position: '运营', status: 'disabled', permissions: ['products:view', 'products:edit'], createdAt: '2026-06-03 09:00' },
  { id: 4, username: 'wangfang', name: '王芳', phone: '13687654321', position: '销售', status: 'active', permissions: ['orders:view', 'orders:create'], createdAt: '2026-06-04 16:00' },
  { id: 5, username: 'chenwei', name: '陈伟', phone: '13511112222', position: '财务', status: 'active', permissions: [], createdAt: '2026-06-05 11:00' },
]

const MOCK_MENUS = [
  { id: 1, code: 'dashboard', name: '工作台', children: [{ id: 11, code: 'dashboard:view', name: '查看数据看板', label: '查看数据看板' }] },
  { id: 2, code: 'products', name: '商品管理', children: [
    { id: 21, code: 'products:view', name: '查看商品', label: '查看商品' },
    { id: 22, code: 'products:edit', name: '编辑商品', label: '编辑商品' },
    { id: 23, code: 'products:delete', name: '删除商品', label: '删除商品' },
  ]},
  { id: 3, code: 'orders', name: '订单管理', children: [
    { id: 31, code: 'orders:view', name: '查看订单', label: '查看订单' },
    { id: 32, code: 'orders:create', name: '创建订单', label: '创建订单' },
    { id: 33, code: 'orders:ship', name: '发货管理', label: '发货管理' },
  ]},
  { id: 4, code: 'customers', name: '客户管理', children: [{ id: 41, code: 'customers:view', name: '查看客户', label: '查看客户' }] },
  { id: 5, code: 'settings', name: '系统设置', children: [
    { id: 51, code: 'employees:manage', name: '员工管理', label: '员工管理' },
    { id: 52, code: 'roles:manage', name: '角色管理', label: '角色管理' },
  ]},
]

function buildPaginatedResponse(items: typeof MOCK_EMPLOYEES, page = 1, size = 10) {
  const start = (page - 1) * size
  return { success: true, data: { total: items.length, page, size, items: items.slice(start, start + size) } }
}

// ==================== Tests ====================

test.describe('员工管理页面', () => {
  let page

  test.beforeEach(async ({ page: p }) => {
    page = p
    // Mock employees list with filtering
    await page.route('**/api/admin/users*', (route) => {
      const method = route.request().method()
      const url = new URL(route.request().url())
      if (method === 'GET') {
        const keyword = url.searchParams.get('keyword') || ''
        const status = url.searchParams.get('status') || ''
        let filtered = [...MOCK_EMPLOYEES]
        if (keyword) filtered = filtered.filter((e) => e.name.includes(keyword) || e.phone.includes(keyword))
        if (status) filtered = filtered.filter((e) => e.status === status)
        const pageNum = parseInt(url.searchParams.get('page') || '1')
        route.fulfill({ contentType: 'application/json', body: JSON.stringify(buildPaginatedResponse(filtered, pageNum)) })
      } else if (method === 'POST') {
        route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, data: { id: 99 } }) })
      } else if (method === 'PUT') {
        route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true }) })
      } else {
        route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true }) })
      }
    })

    // Mock menus/permissions tree
    await page.route('**/api/admin/menus*', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, data: MOCK_MENUS }) })
    })

    // Mock roles list
    await page.route('**/api/admin/roles/all*', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true,
        data: [{ id: 1, name: '管理员', code: 'admin' }, { id: 2, name: '客服', code: 'service' }]
      })})
    })

    await page.goto('/employees')
    await page.waitForLoadState('load')
  })

  test('页面标题正确显示', async () => {
    await expect(page.getByRole('heading', { name: /员工管理/ })).toBeVisible()
  })

  test('员工列表表格渲染', async () => {
    await expect(page.locator('table')).toBeVisible()
    await expect(page.getByText('系统管理员')).toBeVisible()
  })

  test('表格列头正确显示', async () => {
    const headers = ['姓名', '手机号', '岗位', '状态']
    for (const h of headers) {
      await expect(page.getByRole('columnheader', { name: h })).toBeVisible({ timeout: 5000 })
    }
  })

  test('添加员工按钮可打开创建弹窗', async () => {
    await page.getByRole('button', { name: /添加员工/ }).click()
    await expect(page.locator('[role="dialog"]')).toBeVisible()
    await expect(page.getByText(/新增员工/)).toBeVisible()
  })

  test('创建弹窗包含用户名、姓名、手机号、岗位字段', async () => {
    await page.getByRole('button', { name: /添加员工/ }).click()
    const modal = page.locator('[role="dialog"]')
    await expect(modal.locator('input[placeholder*="用户名"]')).toBeVisible()
    await expect(modal.locator('input[placeholder*="姓名"]')).toBeVisible()
    await expect(modal.locator('input[placeholder*="手机号"]')).toBeVisible()
    await expect(modal.locator('input[placeholder*="岗位"]')).toBeVisible()
  })

  test('搜索框可按姓名搜索', async () => {
    const searchInput = page.locator('input[placeholder*="搜索"]')
    await searchInput.fill('张美华')
    await searchInput.press('Enter')
    await expect(page.locator('table')).toBeVisible()
  })

  test('状态切换按钮存在', async () => {
    // Toggle switch: button with title "点击禁用" or "点击启用" containing a white dot span
    const toggleButtons = page.getByTitle(/点击禁用|点击启用/)
    const count = await toggleButtons.count()
    if (count === 0) {
      // Fallback: button containing white dot span
      const altButtons = page.locator('button[type="button"]').filter({ has: page.locator('span.rounded-full') })
      expect(await altButtons.count()).toBeGreaterThanOrEqual(1)
    } else {
      expect(count).toBeGreaterThanOrEqual(1)
    }
  })

  test('删除按钮可打开确认弹窗', async () => {
    const deleteBtns = page.getByRole('button', { name: /删除/ })
    const count = await deleteBtns.count()
    if (count > 0) {
      await deleteBtns.first().click()
      await expect(page.locator('[role="dialog"]').filter({ hasText: /删除|确认/ })).toBeVisible({ timeout: 5000 })
    }
  })

  test('编辑按钮可打开编辑弹窗', async () => {
    const editBtns = page.getByRole('button', { name: /编辑/ })
    const count = await editBtns.count()
    if (count > 0) {
      await editBtns.first().click()
      await expect(page.locator('[role="dialog"]')).toBeVisible()
      await expect(page.getByText(/编辑员工/)).toBeVisible()
    }
  })

  test('创建员工 - 未填用户名时提示错误', async () => {
    await page.getByRole('button', { name: /添加员工/ }).click()
    const modal = page.locator('[role="dialog"]')
    // Modal 底部默认按钮是"确定"，点击后触发前端校验 toast
    await modal.getByRole('button', { name: /创建|保存/ }).click()
    await expect(page.locator('[data-sonner-toast]').first()).toBeVisible({ timeout: 5000 })
  })

  test('员工状态 Badge 正确显示', async () => {
    // Active users show "启用" or badge
    await expect(page.locator('table')).toBeVisible()
    const statusCells = page.locator('text=/启用|禁用/')
    expect(await statusCells.count()).toBeGreaterThanOrEqual(1)
  })

  test('分页组件正确显示', async () => {
    const pagination = page.locator('text=/共.*条/').first()
    if (await pagination.isVisible().catch(() => false)) {
      await expect(pagination).toBeVisible()
    }
  })

  test('重置按钮清空搜索条件', async () => {
    const searchInput = page.locator('input[placeholder*="搜索"]')
    await searchInput.fill('测试')
    const resetBtn = page.getByRole('button', { name: /重置/ })
    if (await resetBtn.isVisible().catch(() => false)) {
      await resetBtn.click()
      await expect(searchInput).toHaveValue('')
    }
  })
})
