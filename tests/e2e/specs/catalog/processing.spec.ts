import { test, expect } from '@playwright/test'

/**
 * 加工项配置 E2E 测试
 *
 * 验证加工项列表、新增/编辑弹窗、删除确认等完整 CRUD 流程。
 */

const MOCK_PROCESSING_ITEMS = [
  {
    id: 'proc_001',
    name: '韩式打褶定型',
    categoryId: 'cat_proc_001',
    pricingMethod: 'per_meter',
    unitPrice: 25.0,
    unit: '米',
    status: 'active',
  },
  {
    id: 'proc_002',
    name: '打孔',
    categoryId: 'cat_proc_001',
    pricingMethod: 'per_meter',
    unitPrice: 15.0,
    unit: '米',
    status: 'active',
  },
  {
    id: 'proc_003',
    name: '铅坠线',
    categoryId: 'cat_proc_001',
    pricingMethod: 'per_piece',
    unitPrice: 8.0,
    unit: '套',
    status: 'active',
  },
]

test.describe('加工项配置', () => {
  test.beforeEach(async ({ page }) => {
    // 拦截加工项列表 API
    await page.route('**/api/admin/processing-items*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            code: 200,
            data: { items: MOCK_PROCESSING_ITEMS, total: 3, page: 1, size: 999 },
          }),
        })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      }
    })

    // 拦截加工分类 API
    await page.route('**/api/admin/processing-categories*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: [{ id: 'cat_proc_001', name: '窗帘加工' }],
        }),
      })
    })

    await page.goto('/processing')
    await page.waitForSelector('text=加工项配置')
  })

  test.describe('页面加载', () => {
    test('应显示页面标题', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '加工项配置' })).toBeVisible()
    })

    test('应渲染加工项列表表格', async ({ page }) => {
      const table = page.locator('table')
      await expect(table).toBeVisible()
      // 验证表头
      await expect(table.getByText('加工项名称')).toBeVisible()
      await expect(table.getByText('加工项价格')).toBeVisible()
      await expect(table.getByText('加工项计价方式')).toBeVisible()
      await expect(table.getByText('操作')).toBeVisible()
    })

    test('应显示所有加工项数据', async ({ page }) => {
      await expect(page.getByText('韩式打褶定型')).toBeVisible()
      await expect(page.getByText('打孔')).toBeVisible()
      await expect(page.getByText('铅坠线')).toBeVisible()
    })

    test('应正确显示价格', async ({ page }) => {
      await expect(page.getByText('25.00')).toBeVisible()
      await expect(page.getByText('15.00')).toBeVisible()
      await expect(page.getByText('8.00')).toBeVisible()
    })

    test('应正确显示计价方式', async ({ page }) => {
      await expect(page.getByText('按购买米数计价').first()).toBeVisible()
      await expect(page.getByText('按购买套数计价')).toBeVisible()
    })
  })

  test.describe('新增加工项', () => {
    test('点击添加按钮应打开新增弹窗', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      await expect(page.getByText('新增加工项')).toBeVisible()
    })

    test('弹窗应包含名称、价格、计价方式字段', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      await expect(page.getByText('加工项名称')).toBeVisible()
      await expect(page.getByText('加工项价格')).toBeVisible()
      await expect(page.getByText('加工项计价方式')).toBeVisible()
    })

    test('名称为空提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('请输入加工项名称')).toBeVisible()
    })

    test('价格为空提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.locator('input[type="text"]').fill('测试加工项')
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('请输入加工项价格')).toBeVisible()
    })

    test('计价方式未选提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      // 填写名称和价格
      const inputs = dialog.locator('input')
      await inputs.nth(0).fill('测试加工项')
      await inputs.nth(1).fill('20.00')
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('请选择计价方式')).toBeVisible()
    })

    test('完整填写后应成功创建', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()

      // 填写名称
      await dialog.locator('input[type="text"]').fill('新加工项')
      // 填写价格
      await dialog.locator('input[type="number"]').fill('30.00')
      // 选择计价方式
      await dialog.locator('select').first().selectOption('per_meter')

      await dialog.getByRole('button', { name: '保存' }).click()
      // 成功后弹窗关闭
      await expect(dialog).toBeHidden()
    })

    test('弹窗应包含优惠设置', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      await expect(page.getByText('设置优惠')).toBeVisible()
    })

    test('选择优惠类型应展开折扣配置', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      // 选择"按金额满减"优惠
      const discountSelect = dialog.locator('select').nth(1)
      await discountSelect.selectOption('amount_off')
      // 应显示满X件选择和折扣力度输入
      await expect(dialog.getByText('折')).toBeVisible()
    })
  })

  test.describe('编辑加工项', () => {
    test('点击编辑应打开编辑弹窗并回填数据', async ({ page }) => {
      await page.locator('text=编辑').first().click()
      await expect(page.getByText('编辑加工项')).toBeVisible()

      const dialog = page.locator('.fixed.inset-0.z-50').last()
      // 名称应回填
      const nameInput = dialog.locator('input[type="text"]')
      await expect(nameInput).toHaveValue('韩式打褶定型')
    })

    test('编辑保存应调用更新 API', async ({ page }) => {
      let updateCalled = false
      await page.route('**/api/admin/processing-items/proc_001', async (route) => {
        if (route.request().method() === 'PUT' || route.request().method() === 'PATCH') {
          updateCalled = true
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
        } else {
          await route.fallback()
        }
      })

      await page.locator('text=编辑').first().click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '保存' }).click()
      await page.waitForTimeout(500)
      expect(updateCalled).toBe(true)
    })
  })

  test.describe('删除加工项', () => {
    test('点击删除应弹出确认对话框', async ({ page }) => {
      // 点击第一行的删除按钮
      const rows = page.locator('tbody tr')
      const firstRow = rows.first()
      await firstRow.getByText('删除').click()
      await expect(page.getByText('确认删除')).toBeVisible()
      await expect(page.getByText(/确定要删除当前加工项/)).toBeVisible()
    })

    test('确认删除应调用 API', async ({ page }) => {
      let deleteCalled = false
      await page.route('**/api/admin/processing-items/proc_001', async (route) => {
        if (route.request().method() === 'DELETE') {
          deleteCalled = true
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
        } else {
          await route.fallback()
        }
      })

      const rows = page.locator('tbody tr')
      await rows.first().getByText('删除').click()
      await page.getByRole('button', { name: '确定' }).click()
      await page.waitForTimeout(500)
      expect(deleteCalled).toBe(true)
    })

    test('取消删除应关闭对话框', async ({ page }) => {
      const rows = page.locator('tbody tr')
      await rows.first().getByText('删除').click()
      await page.getByRole('button', { name: '取消' }).click()
      await expect(page.getByText('确认删除')).toBeHidden()
    })
  })

  test.describe('空状态', () => {
    test('无数据时应显示空状态提示', async ({ page }) => {
      // 拦截空数据
      await page.route('**/api/admin/processing-items*', async (route) => {
        if (route.request().method() === 'GET') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ code: 200, data: { items: [], total: 0 } }),
          })
        } else {
          await route.fallback()
        }
      }, { times: 1 })

      await page.reload()
      await expect(page.getByText(/暂无加工项/)).toBeVisible()
    })
  })
})
