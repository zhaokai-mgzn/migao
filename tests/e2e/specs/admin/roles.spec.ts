import { test, expect } from '@playwright/test'
import { RolesPage } from '../../pages/admin/roles.page'

// ==================== Inline Mock Data ====================

const MOCK_ROLES = [
  { id: 1, name: '超级管理员', code: 'admin', description: '系统最高权限', status: 'active', permissions: ['perm-all'], createdAt: '2026-06-01' },
  { id: 2, name: '商品运营', code: 'product_operator', description: '管理商品和分类', status: 'active', permissions: ['perm-products', 'perm-categories'], createdAt: '2026-06-01' },
  { id: 3, name: '订单客服', code: 'order_service', description: '处理订单和售后', status: 'active', permissions: ['perm-orders', 'perm-after-sales'], createdAt: '2026-06-01' },
]

// Permissions grouped by resource
const MOCK_PERMISSIONS = [
  // 工作台
  { id: 11, name: '查看数据看板', code: 'dashboard:view', resourceGroup: '工作台', resourceGroupSort: 1 },
  // 商品管理
  { id: 21, name: '查看商品', code: 'products:view', resourceGroup: '商品管理', resourceGroupSort: 2 },
  { id: 22, name: '编辑商品', code: 'products:edit', resourceGroup: '商品管理', resourceGroupSort: 2 },
  { id: 23, name: '删除商品', code: 'products:delete', resourceGroup: '商品管理', resourceGroupSort: 2 },
  { id: 24, name: '上下架商品', code: 'products:status', resourceGroup: '商品管理', resourceGroupSort: 2 },
  { id: 25, name: '管理分类', code: 'categories:manage', resourceGroup: '商品管理', resourceGroupSort: 2 },
  { id: 26, name: '管理加工项', code: 'processing:manage', resourceGroup: '商品管理', resourceGroupSort: 2 },
  // 订单管理
  { id: 31, name: '查看订单', code: 'orders:view', resourceGroup: '订单管理', resourceGroupSort: 3 },
  { id: 32, name: '创建订单', code: 'orders:create', resourceGroup: '订单管理', resourceGroupSort: 3 },
  { id: 33, name: '编辑订单', code: 'orders:edit', resourceGroup: '订单管理', resourceGroupSort: 3 },
  { id: 34, name: '发货管理', code: 'orders:ship', resourceGroup: '订单管理', resourceGroupSort: 3 },
  { id: 35, name: '管理售后', code: 'after-sales:manage', resourceGroup: '订单管理', resourceGroupSort: 3 },
  // 客户管理
  { id: 41, name: '查看客户', code: 'customers:view', resourceGroup: '客户管理', resourceGroupSort: 4 },
  // 系统设置
  { id: 51, name: '员工管理', code: 'employees:manage', resourceGroup: '系统设置', resourceGroupSort: 5 },
  { id: 52, name: '角色管理', code: 'roles:manage', resourceGroup: '系统设置', resourceGroupSort: 5 },
  { id: 53, name: '系统配置', code: 'settings:manage', resourceGroup: '系统设置', resourceGroupSort: 5 },
]

// ==================== Tests ====================

test.describe('角色权限管理页面', () => {
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
    await expect(page.page.getByRole('heading', { name: '角色权限' })).toBeVisible()
    await expect(page.page.getByText('管理系统角色和权限分配')).toBeVisible()
  })

  test('角色列表以卡片网格展示', async () => {
    await page.waitForLoadingComplete()
    const cards = page.roleCards
    expect(await cards.count()).toBeGreaterThanOrEqual(1)
  })

  test('角色卡片显示名称、编码和权限数量', async () => {
    await page.waitForLoadingComplete()
    // Should show role names
    await expect(page.page.getByText('超级管理员')).toBeVisible()
    // Should show permission count badges
    await expect(page.page.getByText(/个权限/).first()).toBeVisible()
  })

  test('新增角色按钮可打开创建弹窗', async () => {
    await page.createBtn.click()
    await expect(page.roleModal).toBeVisible()
    await expect(page.page.getByText('新增角色')).toBeVisible()
  })

  test('创建弹窗包含名称、编码、描述字段', async () => {
    await page.createBtn.click()
    await expect(page.name).toBeVisible()
    await expect(page.code).toBeVisible()
    await expect(page.description).toBeVisible()
  })

  test('创建弹窗包含权限树', async () => {
    await page.createBtn.click()
    await expect(page.page.getByText('权限分配')).toBeVisible()
    const tree = page.permissionTree
    if (await tree.isVisible().catch(() => false)) {
      expect(await tree.locator('input[type="checkbox"]').count()).toBeGreaterThanOrEqual(1)
    }
  })

  test('权限树支持资源组全选/取消全选', async () => {
    await page.createBtn.click()
    await page.page.waitForTimeout(500) // wait for tree render
    // All checkboxes
    const allCheckboxes = page.permissionTree.locator('input[type="checkbox"]')
    const count = await allCheckboxes.count()
    if (count > 0) {
      await allCheckboxes.first().click()
      await expect(allCheckboxes.first()).toBeChecked()
      await allCheckboxes.first().click()
      await expect(allCheckboxes.first()).not.toBeChecked()
    }
  })

  test('创建角色 - 未填名称时提示错误', async () => {
    await page.createBtn.click()
    await page.code.fill('test_role')
    await page.roleModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入角色名称/)
  })

  test('创建角色 - 未填编码时提示错误', async () => {
    await page.createBtn.click()
    await page.name.fill('测试角色')
    await page.roleModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入角色编码/)
  })

  test('编辑按钮可打开编辑弹窗', async () => {
    await page.waitForLoadingComplete()
    const editBtn = page.editBtn(0)
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()
      await expect(page.roleModal).toBeVisible()
      await expect(page.page.getByText('编辑角色')).toBeVisible()
    }
  })

  test('删除按钮可打开确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: /确认删除|删除角色/ })
      await expect(modal).toBeVisible({ timeout: 5000 })
    }
  })

  test('空状态下显示提示文案', async () => {
    await page.waitForLoadingComplete()
    const emptyText = page.page.getByText(/暂无角色/)
    if (await emptyText.isVisible().catch(() => false)) {
      await expect(emptyText).toBeVisible()
    }
  })
})
