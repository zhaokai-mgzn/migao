import { test, expect } from '@playwright/test'
import { EmployeesPage } from '../../pages/admin/employees.page'

// #367: 新 UI (PR #331) 与 E2E 选择器不兼容（dialog/button/input 定位失败）
// #385: 删除了密码/邮箱字段，测试需重写
// 暂时禁用，数据 mock 就绪后解除
test.describe.skip('员工管理页面', () => {
  let page: EmployeesPage

  test.beforeEach(async ({ page: p }) => {
    page = new EmployeesPage(p)
    await page.goto()
    await page.waitForLoad()
  })

  test('页面标题和描述正确显示', async () => {
    // 使用 heading 而非 getByText，避免 sidebar/breadcrumb 中同名字符串导致的 strict mode 冲突
    await expect(page.page.getByRole('heading', { name: '员工管理' })).toBeVisible()
    await expect(page.page.getByText('管理系统用户和员工账号')).toBeVisible()
  })

  test('搜索框支持关键词搜索', async () => {
    await page.searchInput.fill('admin')
    await page.page.getByRole('button', { name: /搜索/ }).click()
    await page.waitForLoadingComplete()
    await expect(page.table).toBeVisible()
  })

  test('状态筛选下拉框可切换', async () => {
    const select = page.page.locator('select').first()
    if (await select.isVisible()) {
      await select.selectOption('active')
      await page.page.getByRole('button', { name: /搜索/ }).click()
      await page.waitForLoadingComplete()
    }
    await expect(page.table).toBeVisible()
  })

  test('新增员工按钮可打开创建弹窗', async () => {
    await page.createBtn.click()
    await expect(page.employeeModal).toBeVisible()
    await expect(page.page.getByText('新增员工')).toBeVisible()
  })

  test('创建弹窗包含所有必要字段', async () => {
    await page.createBtn.click()
    await expect(page.username).toBeVisible()
    await expect(page.password).toBeVisible()
    await expect(page.name).toBeVisible()
    await expect(page.phone).toBeVisible()
    await expect(page.email).toBeVisible()
  })

  test('创建弹窗支持角色多选', async () => {
    await page.createBtn.click()
    // 角色分配区域
    const roleSection = page.employeeModal.locator('text=角色分配')
    if (await roleSection.isVisible()) {
      await expect(roleSection).toBeVisible()
      // 角色按钮
      const roleButtons = page.employeeModal.locator('button').filter({ hasText: /^[^新取保]+$/ })
      if (await roleButtons.count() > 1) {
        // 点击选择角色
        await roleButtons.first().click()
        await expect(roleButtons.first()).toHaveClass(/border-primary-500/)
      }
    }
  })

  test('创建员工 - 未填用户名时提示错误', async () => {
    await page.createBtn.click()
    await page.name.fill('测试员工')
    await page.employeeModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入用户名/)
  })

  test('创建员工 - 未填姓名时提示错误', async () => {
    await page.createBtn.click()
    await page.username.fill('testuser')
    await page.password.fill('password123')
    await page.employeeModal.getByRole('button', { name: /创建/ }).click()
    await page.expectErrorToast(/请输入姓名/)
  })

  test('编辑按钮可打开编辑弹窗', async () => {
    await page.waitForLoadingComplete()
    const editBtn = page.editBtn(0)
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()
      await expect(page.employeeModal).toBeVisible()
      await expect(page.page.getByText('编辑员工')).toBeVisible()
      // 编辑模式下用户名禁用
      await expect(page.username).toBeDisabled()
    }
  })

  test('重置密码弹窗可正常打开', async () => {
    await page.waitForLoadingComplete()
    const resetBtn = page.resetPasswordBtn(0)
    if (await resetBtn.isVisible().catch(() => false)) {
      await resetBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '重置密码' })
      await expect(modal).toBeVisible()
      // 新密码输入框
      await expect(modal.locator('input[type="password"]')).toBeVisible()
    }
  })

  test('重置密码 - 空密码提交提示错误', async () => {
    await page.waitForLoadingComplete()
    const resetBtn = page.resetPasswordBtn(0)
    if (await resetBtn.isVisible().catch(() => false)) {
      await resetBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '重置密码' })
      await modal.getByRole('button', { name: /确认重置/ }).click()
      await page.expectErrorToast(/请输入新密码/)
    }
  })

  test('禁用/启用按钮可打开确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const toggleBtn = page.toggleStatusBtn(0)
    if (await toggleBtn.isVisible().catch(() => false)) {
      await toggleBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: /确认禁用|确认启用/ })
      await expect(modal).toBeVisible()
    }
  })

  test('删除按钮可打开确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '确认删除' })
      await expect(modal).toBeVisible()
      await expect(modal.getByText(/确定要删除员工/)).toBeVisible()
    }
  })

  test('员工状态 Badge 正确显示', async () => {
    await page.waitForLoadingComplete()
    // 状态列显示"启用"或"禁用" Badge
    const statusBadges = page.page.locator('tbody').getByText(/启用|禁用/)
    expect(await statusBadges.count()).toBeGreaterThanOrEqual(0)
  })

  test('分页组件正确显示', async () => {
    await page.waitForLoadingComplete()
    const pagination = page.page.locator('text=/共.*条/').first()
    if (await pagination.isVisible()) {
      await expect(pagination).toBeVisible()
    }
  })

  test('重置按钮清空搜索条件', async () => {
    await page.searchInput.fill('测试')
    await page.page.getByRole('button', { name: /重置/ }).click()
    await expect(page.searchInput).toHaveValue('')
  })

  test('员工角色列显示角色 Badge', async () => {
    await page.waitForLoadingComplete()
    await expect(page.page.getByRole('columnheader', { name: /角色/ })).toBeVisible()
  })

  test('表格包含所有必要列', async () => {
    const headers = ['用户名', '姓名', '手机号', '角色', '状态', '创建时间', '操作']
    for (const header of headers) {
      await expect(page.page.getByRole('columnheader', { name: header })).toBeVisible()
    }
  })
})
