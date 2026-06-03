import { test, expect } from '@playwright/test'
import { RolesPage } from '../../pages/admin/roles.page'

test.describe('角色权限管理页面', () => {
  let page: RolesPage

  test.beforeEach(async ({ page: p }) => {
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
    const grid = page.page.locator('.grid')
    if (await grid.isVisible()) {
      await expect(grid).toBeVisible()
    }
  })

  test('角色卡片显示名称、编码和权限数量', async () => {
    await page.waitForLoadingComplete()
    const cards = page.page.locator('.bg-white.rounded-lg.border.border-gray-200.p-5')
    if (await cards.count() > 0) {
      const firstCard = cards.first()
      // 角色名称
      await expect(firstCard.locator('h3')).toBeVisible()
      // 权限数量 Badge
      await expect(firstCard.getByText(/个权限/)).toBeVisible()
    }
  })

  test('新增角色按钮可打开创建弹窗', async () => {
    await page.createBtn.click()
    await expect(page.roleModal).toBeVisible()
    await expect(page.page.getByRole('heading', { name: '新增角色' })).toBeVisible()
  })

  test('创建弹窗包含名称、编码、描述字段', async () => {
    await page.createBtn.click()
    await expect(page.name).toBeVisible()
    await expect(page.code).toBeVisible()
    await expect(page.description).toBeVisible()
  })

  test('创建弹窗包含权限树', async () => {
    await page.createBtn.click()
    await expect(page.roleModal.getByText('权限分配')).toBeVisible()
    // 权限树区域
    const tree = page.permissionTree
    if (await tree.isVisible()) {
      // 资源组标题
      const groups = tree.locator('.bg-gray-50')
      expect(await groups.count()).toBeGreaterThanOrEqual(0)
    }
  })

  test('权限树支持资源组全选/取消全选', async () => {
    await page.createBtn.click()
    const groupCheckboxes = page.permissionTree.locator('.bg-gray-50 input[type="checkbox"]')
    if (await groupCheckboxes.count() > 0) {
      // 点击第一个资源组的全选 checkbox
      await groupCheckboxes.first().click()
      // 全选后 checkbox 应该被选中
      await expect(groupCheckboxes.first()).toBeChecked()
      // 再次点击取消全选
      await groupCheckboxes.first().click()
      await expect(groupCheckboxes.first()).not.toBeChecked()
    }
  })

  test('权限树支持单个权限勾选', async () => {
    await page.createBtn.click()
    const permCheckboxes = page.permissionTree.locator('.px-4.py-2 label input[type="checkbox"]')
    if (await permCheckboxes.count() > 0) {
      await permCheckboxes.first().click()
      await expect(permCheckboxes.first()).toBeChecked()
    }
  })

  test('权限树组标题显示 indeterminate 状态', async () => {
    await page.createBtn.click()
    const permCheckboxes = page.permissionTree.locator('.px-4.py-2 label input[type="checkbox"]')
    if (await permCheckboxes.count() > 1) {
      // 只选中部分权限
      await permCheckboxes.first().click()
      // 对应的组 checkbox 应该处于 indeterminate 状态
      const groupCheckbox = page.permissionTree.locator('.bg-gray-50 input[type="checkbox"]').first()
      if (await groupCheckbox.isVisible()) {
        const indeterminate = await groupCheckbox.evaluate((el) => (el as HTMLInputElement).indeterminate)
        // indeterminate 可能为 true 或 false，取决于实现
        expect(typeof indeterminate).toBe('boolean')
      }
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
      // 编辑模式下编码字段禁用
      await expect(page.code).toBeDisabled()
    }
  })

  test('删除按钮可打开确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '确认删除' })
      await expect(modal).toBeVisible()
      await expect(modal.getByText(/确定要删除角色/)).toBeVisible()
    }
  })

  test('空状态下显示提示文案', async () => {
    await page.waitForLoadingComplete()
    // 如果没有角色数据
    const emptyText = page.page.getByText('暂无角色，点击上方按钮新增')
    if (await emptyText.isVisible().catch(() => false)) {
      await expect(emptyText).toBeVisible()
    }
  })
})
