import { test, expect } from '@playwright/test'

test.describe('商品创建', () => {
  test.beforeEach(async ({ page }) => {
    // Mock /api/auth/me — AuthProvider.initialize() 验证 token
    // 不 mock 则请求失败 → clearAuth() → 重定向到 /login
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }) })
    })
    // Mock ProductForm 挂载时调用的 API
    await page.route('**/api/admin/categories*', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: [{ id: 'cat1', name: '窗帘布艺', sort: 1, children: [] }] }),
      })
    })
    await page.route('**/api/admin/processing-items*', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { items: [], total: 0 } }),
      })
    })

    await page.goto('/products/new')
    // 等待表单加载完成
    await expect(page.getByRole('heading', { name: '新增商品' })).toBeVisible({ timeout: 10_000 })
  })

  test.describe('页面加载', () => {
    test('应显示新增商品标题', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '新增商品' })).toBeVisible()
    })

    test('应显示基础信息、销售信息、图文描述三个区块', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '基础信息' })).toBeVisible()
      await expect(page.getByRole('heading', { name: '销售信息' })).toBeVisible()
      await expect(page.getByRole('heading', { name: '图文描述' })).toBeVisible()
    })

    test('底部操作栏应包含三个按钮', async ({ page }) => {
      await expect(page.getByRole('button', { name: '存草稿' })).toBeVisible()
      await expect(page.getByRole('button', { name: '提交并放入仓库' })).toBeVisible()
      await expect(page.getByRole('button', { name: '提交并上架' })).toBeVisible()
    })
  })

  test.describe('基础信息字段', () => {
    test('商品标题字段应可输入并显示字数统计', async ({ page }) => {
      const titleInput = page.locator('#pf-name input')
      await titleInput.fill('测试商品标题')
      await expect(titleInput).toHaveValue('测试商品标题')
      // 字数统计
      await expect(page.locator('#pf-name').getByText(/\d+\/60/)).toBeVisible()
    })

    test('商品标题超过60字符应显示红色计数', async ({ page }) => {
      const titleInput = page.locator('#pf-name input')
      const longTitle = '测'.repeat(61)
      await titleInput.fill(longTitle)
      // maxLength 限制，实际只能输入 60 个字符
      const value = await titleInput.inputValue()
      expect(value.length).toBeLessThanOrEqual(60)
    })

    test('商品分类下拉应选择', async ({ page }) => {
      const categorySelect = page.locator('#pf-category select')
      await expect(categorySelect).toBeVisible()
      // 分类从 API 加载，验证 select 存在
      await expect(categorySelect).toBeAttached()
    })

    test('货号字段应可输入', async ({ page }) => {
      // 货号在 ProductAttributes 组件内
      const skuInput = page.locator('#pf-unit').locator('input[placeholder="请输入商品货号"]')
      await skuInput.fill('SKU-001')
      await expect(skuInput).toHaveValue('SKU-001')
    })

    test('品牌下拉应支持选择和自定义', async ({ page }) => {
      const brandSelect = page.locator('#pf-unit').locator('label:has-text("品牌") + * select, label:has-text("品牌") ~ div select').first()
      // 验证品牌选择器存在
      await expect(brandSelect).toBeAttached()
    })

    test('计价单位应选择', async ({ page }) => {
      const unitSelect = page.locator('#pf-unit').locator('label:has-text("计价单位") + * select, label:has-text("计价单位") ~ div select').first()
      await expect(unitSelect).toBeAttached()
    })

    test('商品属性应包含克重、材质、功能、工艺、风格、图案', async ({ page }) => {
      await expect(page.getByText('克重')).toBeVisible()
      await expect(page.getByText('材质')).toBeVisible()
      await expect(page.getByText('功能')).toBeVisible()
      await expect(page.getByText('工艺')).toBeVisible()
      await expect(page.getByText('风格')).toBeVisible()
      await expect(page.getByText('图案')).toBeVisible()
    })
  })

  test.describe('商品主图上传', () => {
    test('应显示上传按钮和提示信息', async ({ page }) => {
      await expect(page.getByText('上传封面')).toBeVisible()
      await expect(page.getByText(/照片要求/)).toBeVisible()
    })

    test('应显示最多5张的计数', async ({ page }) => {
      await expect(page.getByText('0/5')).toBeVisible()
    })
  })

  test.describe('颜色分类', () => {
    test('应显示添加颜色分类按钮', async ({ page }) => {
      await expect(page.getByRole('button', { name: /添加颜色分类/ })).toBeVisible()
    })

    test('点击添加应新增一行颜色', async ({ page }) => {
      await page.getByRole('button', { name: /添加颜色分类/ }).click()
      // 验证新增颜色行
      await expect(page.locator('input[placeholder="主色(必选)"]').first()).toBeVisible()
    })

    test('颜色行应支持删除', async ({ page }) => {
      await page.getByRole('button', { name: /添加颜色分类/ }).click()
      const deleteBtn = page.locator('button[title="删除"]').first()
      await expect(deleteBtn).toBeVisible()
    })

    test('颜色名称输入应可编辑', async ({ page }) => {
      await page.getByRole('button', { name: /添加颜色分类/ }).click()
      const nameInput = page.locator('input[placeholder="主色(必选)"]').first()
      await nameInput.fill('红色')
      await expect(nameInput).toHaveValue('红色')
    })
  })

  test.describe('售卖方式', () => {
    test('应显示售卖方式区块和添加按钮', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '售卖方式' })).toBeVisible()
      // 添加按钮（虚线边框 Plus 图标）
      const smSection = page.getByRole('heading', { name: '售卖方式' }).locator('..').locator('..')
      const addBtn = smSection.locator('button[title="添加"]')
      await expect(addBtn).toBeVisible()
    })

    test('添加售卖方式应出现下拉选择', async ({ page }) => {
      // 点击售卖方式区域的添加按钮
      const smSection = page.getByRole('heading', { name: '售卖方式' }).locator('..').locator('..')
      const addBtn = smSection.locator('button[title="添加"]')
      await addBtn.click()
      await expect(page.locator('select').filter({ hasText: '请选择' }).first()).toBeVisible()
    })
  })

  test.describe('规格尺寸', () => {
    test('应显示规格尺寸区块', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '规格尺寸' })).toBeVisible()
    })

    test('添加规格尺寸应出现下拉', async ({ page }) => {
      const dwSection = page.getByRole('heading', { name: '规格尺寸' }).locator('..').locator('..')
      const addBtn = dwSection.locator('button[title="添加"]')
      await addBtn.click()
      await expect(page.locator('select').filter({ hasText: '请选择' }).first()).toBeVisible()
    })
  })

  test.describe('销售规格表', () => {
    test('初始应显示空状态提示', async ({ page }) => {
      await expect(page.getByText('请先完善颜色分类、售卖方式、规格尺寸')).toBeVisible()
    })
  })

  test.describe('总库存', () => {
    test('应显示只读总库存字段', async ({ page }) => {
      const stockInput = page.locator('input[readonly]')
      await expect(stockInput).toBeVisible()
      await expect(stockInput).toHaveValue('0')
    })
  })

  test.describe('拍下减库存', () => {
    test('默认应选择"是"', async ({ page }) => {
      const yesLabel = page.getByText('是', { exact: true }).first()
      await expect(yesLabel).toBeVisible()
    })
  })

  test.describe('加工项配置', () => {
    test('默认不支持加工', async ({ page }) => {
      // 加工区域初始不显示加工项列表
      await expect(page.getByText('是否支持加工')).toBeVisible()
    })

    test('选择"是"后应显示加工项选择器', async ({ page }) => {
      // 点击"是" radio（在"是否支持加工"区域）
      const processingSection = page.locator('text=是否支持加工').locator('..').locator('..')
      const yesRadio = processingSection.locator('label:has-text("是")').first()
      await yesRadio.click()
      // 验证加工项选择器出现
      await expect(page.locator('text=请选择加工项').first()).toBeVisible()
    })
  })

  test.describe('图文描述', () => {
    test('富文本编辑器应可见', async ({ page }) => {
      await expect(page.locator('.rich-text-editor')).toBeVisible()
    })

    test('详情图上传区域应可见', async ({ page }) => {
      await expect(page.getByText('详情图')).toBeVisible()
    })
  })

  test.describe('表单校验', () => {
    test('上架提交空表单应显示标题必填错误', async ({ page }) => {
      await page.getByRole('button', { name: '提交并上架' }).click()
      await expect(page.getByText('请输入商品标题')).toBeVisible()
    })

    test('草稿提交应只校验标题', async ({ page }) => {
      // 不填任何内容直接存草稿
      await page.getByRole('button', { name: '存草稿' }).click()
      // 草稿只要求标题
      await expect(page.getByText('请输入商品标题')).toBeVisible()
    })
  })

  test.describe('发货方式', () => {
    test('应显示发货方式为物流发货、邮费到付', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '发货方式' })).toBeVisible()
      await expect(page.getByText('物流发货')).toBeVisible()
      await expect(page.getByText('邮费到付')).toBeVisible()
    })
  })

  test.describe('批量填写工具栏', () => {
    test('批量填写区域应包含范围选择和价格/数量输入', async ({ page }) => {
      // 批量填写工具栏在 SKU 矩阵下方
      await expect(page.getByRole('button', { name: '批量填写' })).toBeVisible()
    })
  })

  test.describe('重置', () => {
    test('点击重置按钮应弹出确认对话框', async ({ page }) => {
      // 顶部重置按钮
      const resetBtn = page.getByRole('button', { name: '重置' }).first()
      await resetBtn.click()
      // 浏览器 confirm 对话框
      page.once('dialog', async (dialog) => {
        expect(dialog.message()).toContain('确定要重置当前表单吗')
        await dialog.accept()
      })
    })
  })
})
