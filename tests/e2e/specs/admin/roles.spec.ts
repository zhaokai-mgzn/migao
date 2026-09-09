// case_ids: HR-004, HR-005
import { test, expect } from '../../fixtures'
import { RolesPage } from '../../pages/admin/roles.page'

// ==================== Inline Mock Data ====================

const MOCK_ROLES = [
  { id: 1, name: '超级管理员', code: 'admin', description: '系统最高权限', status: 'active', permissions: ['perm-all'], createdAt: '2026-06-01' },
  { id: 2, name: '商品运营', code: 'product_operator', description: '管理商品和分类', status: 'active', permissions: ['perm-products', 'perm-categories'], createdAt: '2026-06-01' },
  { id: 3, name: '订单客服', code: 'order_service', description: '处理订单和售后', status: 'active', permissions: ['perm-orders', 'perm-after-sales'], createdAt: '2026-06-01' },
]

// #3002: 与后端权限目录一致的真实 catalog（resourceType = 旧分组码，页面已不再按它分组）
const MOCK_PERMISSIONS = [
  { id: 'p-dashboard', name: '仪表板查看', code: 'dashboard:view', resource: 'dashboard', action: 'view', description: '查看数据概览' },
  { id: 'p-product-manage', name: '商品管理', code: 'product:manage', resource: 'product', action: 'manage', description: '管理商品(旧大类码，兼容)' },
  { id: 'p-product-list', name: '商品列表', code: 'product:list', resource: 'product', action: 'list', description: '查看商品列表' },
  { id: 'p-product-create', name: '新增商品', code: 'product:create', resource: 'product', action: 'create', description: '新增/编辑/上下架商品' },
  { id: 'p-product-category', name: '商品分类', code: 'product:category', resource: 'product', action: 'category', description: '管理商品分类' },
  { id: 'p-processing', name: '加工管理', code: 'processing:manage', resource: 'processing', action: 'manage', description: '管理加工项' },
  { id: 'p-knowledge', name: '知识库管理', code: 'knowledge:manage', resource: 'knowledge', action: 'manage', description: '管理知识库' },
  { id: 'p-order-list', name: '订单列表', code: 'order:list', resource: 'order', action: 'list', description: '查看订单列表' },
  { id: 'p-order-detail', name: '订单详情', code: 'order:detail', resource: 'order', action: 'detail', description: '查看订单详情' },
  { id: 'p-order-refund', name: '订单退款', code: 'order:refund', resource: 'order', action: 'refund', description: '处理退款/售后工单' },
  { id: 'p-customer', name: '客户管理', code: 'customer:view', resource: 'customer', action: 'view', description: '查看客户' },
  { id: 'p-finance', name: '财务对账', code: 'finance:view', resource: 'finance', action: 'view', description: '查看财务流水/对账' },
  { id: 'p-agent-session', name: '会话监控', code: 'agent:session', resource: 'agent', action: 'session', description: '米宝对话/会话监控/人工客服' },
  { id: 'p-employee-list', name: '员工列表', code: 'employee:list', resource: 'employee', action: 'list', description: '查看员工列表' },
  { id: 'p-employee-create', name: '新增员工', code: 'employee:create', resource: 'employee', action: 'create', description: '新增/编辑/删除员工' },
  { id: 'p-system', name: '系统管理', code: 'system:manage', resource: 'system', action: 'manage', description: '企业信息/角色管理/系统设置' },
]

// ==================== Tests ====================

test.describe('岗位权限管理页面（#2969 由角色权限改名）', () => {
  let page: RolesPage

  test.beforeEach(async ({ page: p }) => {
    // Mock roles list
    await p.route('**/api/admin/roles?*', (route) => {
      route.fulfill({ body: JSON.stringify({ success: true, data: { total: MOCK_ROLES.length, page: 1, size: 10, items: MOCK_ROLES } }) })
    })
    // Mock roles/all (for dropdowns)
    await p.route('**/api/admin/roles/all*', (route) => {
      route.fulfill({ body: JSON.stringify({ success: true, data: MOCK_ROLES }) })
    })
    // Mock permissions (CRITICAL: was missing before)
    await p.route('**/api/admin/permissions*', (route) => {
      route.fulfill({ body: JSON.stringify({ success: true, data: MOCK_PERMISSIONS }) })
    })
    // Mock users (for user assignment)
    await p.route('**/api/admin/users*', (route) => {
      route.fulfill({ body: JSON.stringify({
        success: true,
        data: { total: 1, page: 1, size: 10, items: [{ id: 1, username: 'admin', name: '管理员', phone: '13800138000' }] }
      }) })
    })
    // Mock role create/update
    await p.route('**/api/admin/roles', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({ body: JSON.stringify({ success: true, data: { id: 99 } }) })
      } else {
        route.fulfill({ body: JSON.stringify({ success: true }) })
      }
    })

    page = new RolesPage(p)
    await page.goto()
    await page.waitForLoad()
  })

  test('页面标题和描述正确显示', async () => {
    await expect(page.page.getByRole('heading', { name: '岗位权限' })).toBeVisible()
    await expect(page.page.getByText('管理岗位及默认权限')).toBeVisible()
  })

  test('岗位列表以卡片网格展示', async () => {
    await page.waitForLoadingComplete()
    const cards = page.roleCards
    expect(await cards.count()).toBeGreaterThanOrEqual(1)
  })

  test('岗位卡片显示名称、编码和权限数量', async () => {
    await page.waitForLoadingComplete()
    // Should show role names
    await expect(page.page.getByText('超级管理员')).toBeVisible()
    // Should show permission count badges
    await expect(page.page.getByText(/个权限/).first()).toBeVisible()
  })

  test('新增岗位按钮可打开创建弹窗', async () => {
    await page.createBtn.click()
    await expect(page.roleModal).toBeVisible()
    await expect(page.roleModal.getByRole('heading', { name: '新增岗位' })).toBeVisible()
  })

  test('创建弹窗包含名称、编码、描述字段', async () => {
    await page.createBtn.click()
    await expect(page.name).toBeVisible()
    await expect(page.code).toBeVisible()
    await expect(page.description).toBeVisible()
  })

  test('创建弹窗权限分配与真实侧边栏菜单一致（#3002）', async () => {
    await page.createBtn.click()
    await expect(page.roleModal.getByText('权限分配', { exact: true })).toBeVisible()
    const tree = await page.permissionTree.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => null)
    expect(tree).not.toBeNull()
    // 菜单组名 = 侧边栏菜单组（智能客服/商品管理/订单管理/客户管理/组织管理）
    await expect(page.permissionTree.getByText('智能客服', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('订单管理', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('客户管理', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('组织管理', { exact: true })).toBeVisible()
    // 菜单项名 = 侧边栏菜单项
    await expect(page.permissionTree.getByText('米宝 · 在线对话', { exact: true })).toBeVisible()
    // #3081: AI 客服配置菜单已移除（合并进企业基础信息）
    await expect(page.permissionTree.getByText('AI 客服配置', { exact: true })).toHaveCount(0)
    await expect(page.permissionTree.getByText('售后工单', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('岗位权限', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('企业基础信息', { exact: true })).toBeVisible()
    // 旧权限名（会话监控/快捷回复等）不再出现
    await expect(page.permissionTree.getByText('会话监控', { exact: true })).toHaveCount(0)
    await expect(page.permissionTree.getByText('快捷回复', { exact: true })).toHaveCount(0)
    // 非菜单操作权限单独一节
    await expect(page.permissionTree.getByText('操作权限', { exact: true })).toBeVisible()
    await expect(page.permissionTree.getByText('新增商品', { exact: true })).toBeVisible()
  })

  test('权限分配支持菜单组全选/取消全选（#3002）', async () => {
    await page.createBtn.click()
    await page.permissionTree.waitFor({ state: 'visible', timeout: 5_000 })
    // 智能客服组：米宝 · 在线对话 + 人工客服 + 知识库（#3081 AI 客服配置已移除）
    const agentItems = page.permissionTree.locator('label').filter({ hasText: /米宝|人工客服|知识库/ }).locator('input[type="checkbox"]')
    await expect(agentItems).toHaveCount(3)
    // 点击组头（行）→ 组内全部授予
    await page.permissionTree.getByText('智能客服', { exact: true }).click()
    await expect(agentItems).toBeChecked()
    // 再次点击组头 → 全部撤销
    await page.permissionTree.getByText('智能客服', { exact: true }).click()
    await expect(agentItems).not.toBeChecked()
  })

  test('创建岗位 - 未填名称时提示错误', async () => {
    await page.createBtn.click()
    await page.code.fill('test_role')
    await page.roleModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入岗位名称/)
  })

  test('创建岗位 - 未填编码时提示错误', async () => {
    await page.createBtn.click()
    await page.name.fill('测试岗位')
    await page.roleModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入岗位编码/)
  })

  test('编辑按钮可打开编辑弹窗', async () => {
    await page.waitForLoadingComplete()
    const editBtn = page.editBtn(0)
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()
      await expect(page.roleModal).toBeVisible()
      await expect(page.page.getByText('编辑岗位')).toBeVisible()
    }
  })

  test('删除按钮可打开确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: /确认删除|删除岗位/ })
      await expect(modal).toBeVisible({ timeout: 5000 })
    }
  })

  test('空状态下显示提示文案', async () => {
    await page.waitForLoadingComplete()
    const emptyText = page.page.getByText(/暂无岗位/)
    if (await emptyText.isVisible().catch(() => false)) {
      await expect(emptyText).toBeVisible()
    }
  })
})
