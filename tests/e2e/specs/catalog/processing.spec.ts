// case_ids: PP-002, PP-006
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：原声明 `PP-001, PP-003, PP-004` 三条用例
// **已整条删除** —— 它们驱动的是「给**商品**增删加工项」（`product_processing_item_manage`），
// 该能力随「商品不再持有加工项」退场（工具文件与注册行都删）。
// 本 spec 行使的是**加工项目录 CRUD**（列表/新增/编辑/删除），对应仍在线且仍有用例的
// `PP-002`（分类/目录查询）与 `PP-006`（新增加工项 => 只需名称 + 加工分类），故声明改锚这两条。
// 2026-09-21（issue #4882，用户裁定「移除加工项单价和计价方式」）：本 spec 同步删除两列/两表单
// 字段的断言，并**反向**加防回退锁（列/字段一旦被加回来即红）—— 断言只增不减。
import { test, expect } from '../../fixtures'

/**
 * 加工项配置 E2E 测试
 *
 * 验证加工项列表、新增/编辑弹窗、删除确认等完整 CRUD 流程。
 */

// #4882：加工项目录已无 `pricingMethod` / `unitPrice`（V101 删列）⇒ mock 只留名称/分类/单位/状态。
const MOCK_PROCESSING_ITEMS = [
  {
    id: 'proc_001',
    name: '韩式打褶定型',
    categoryId: 'cat_proc_001',
    unit: '米',
    status: 'active',
  },
  {
    id: 'proc_002',
    name: '打孔',
    categoryId: 'cat_proc_001',
    unit: '米',
    status: 'active',
  },
  {
    id: 'proc_003',
    name: '铅坠线',
    categoryId: 'cat_proc_001',
    unit: '米',
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

    // 拦截商品分类 API（防御性保留；**#4371 解耦后页面已不再请求它**）
    // 沿革：加工项列表原有一列「适用商品分类」，页面为此在 loadData 的 `Promise.all` 里并发拉
    // `categoryApi.getCategories()`；解耦后该列与过滤链路整体退场，页面不再请求商品分类
    // ⇒ 本 mock 现在**命中不到任何请求**（不是失败，只是空转）。保留它是为了让本 spec
    // 对「页面将来又去拉商品分类」这一形态不产生真连后端的抖动；不影响任何断言。
    await page.route('**/api/admin/categories*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: [] }),
      })
    })

    // issue #4490：加工项管理并入 /production/processing（默认 tab 就是「加工项」）；
    // 旧 /processing 改为重定向，这里直接走唯一入口。
    await page.goto('/production/processing')
    // ⚠️ 标题契约：页面 H1 是**菜单名**「加工项管理」（§15.2 面包屑/标题与侧边栏菜单名一致；
    //    历史：#3079「命名统一」曾把「加工项配置」改成「加工项管理」，#4490 合并后改名，
    //    #4542 又改回「加工项管理」并与服务端同名；页面**仍是两个 tab**，功能一条没减）。
    //    断言旧名会让本文件全红在 beforeEach —— 与加工项功能无关。
    await expect(page.getByRole('heading', { name: '加工项管理' })).toBeVisible()
  })

  test.describe('页面加载', () => {
    test('应显示页面标题', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '加工项管理' })).toBeVisible()
    })

    test('应渲染加工项列表表格', async ({ page }) => {
      const table = page.locator('table')
      await expect(table).toBeVisible()
      // 验证表头（#4882 后只剩 名称 / 加工分类 / 操作）
      await expect(table.getByText('加工项名称')).toBeVisible()
      await expect(table.getByText('加工分类')).toBeVisible()
      await expect(table.getByText('操作')).toBeVisible()
      // #4882 防回退锁（用户裁定）：这两列**必须不存在** —— 反向断言才能把「有人把列加回来」
      // 也变成红（旧写法 `toBeVisible()` 在列被删后直接失败，但挡不住回归）。
      await expect(table.getByText('加工项价格')).toHaveCount(0)
      await expect(table.getByText('加工项计价方式')).toHaveCount(0)
    })

    test('应显示所有加工项数据', async ({ page }) => {
      await expect(page.getByText('韩式打褶定型')).toBeVisible()
      await expect(page.locator('table').getByText('打孔')).toBeVisible()
      await expect(page.locator('table').getByText('铅坠线')).toBeVisible()
    })

    test('列表不展示单价与计价方式（加工项已无价，R10 / #4882）', async ({ page }) => {
      const table = page.locator('table')
      // 旧界面的逐项价与计价方式文案一律不得再出现
      await expect(table.getByText('25.00')).toHaveCount(0)
      await expect(table.getByText('15.00')).toHaveCount(0)
      await expect(table.getByText('8.00')).toHaveCount(0)
      await expect(table.getByText('按购买米数计价')).toHaveCount(0)
      await expect(table.getByText('按购买套数计价')).toHaveCount(0)
      // 删的是价与计价方式，不是目录本身 —— 名称仍在
      await expect(table.getByText('韩式打褶定型')).toBeVisible()
    })
  })

  test.describe('新增加工项', () => {
    test('点击添加按钮应打开新增弹窗', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      await expect(page.getByText('新增加工项')).toBeVisible()
    })

    test('弹窗只含名称 / 加工分类（单价与计价方式字段已退场，#4882）', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      // Scope to dialog to avoid strict mode with table headers
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await expect(dialog.getByText('加工项名称')).toBeVisible()
      await expect(dialog.getByText('加工分类')).toBeVisible()
      // 防回退锁：两个已退场的表单项不得再出现
      await expect(dialog.getByText('加工项价格')).toHaveCount(0)
      await expect(dialog.getByText('加工项计价方式')).toHaveCount(0)
    })

    test('名称为空提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('请输入加工项名称')).toBeVisible()
    })

    test('弹窗不再有价格输入框（#4882）', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await expect(dialog.locator('input[type="number"]')).toHaveCount(0)
    })

    test('弹窗不再有计价方式选项（#4882）', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await expect(dialog.locator('option', { hasText: '请选择计价方式' })).toHaveCount(0)
      await expect(dialog.getByText('请选择计价方式')).toHaveCount(0)
    })

    test('完整填写后应成功创建', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()

      // 填写名称（#4882 后表单只剩名称 + 加工分类两个必填项，分类已默认选中第一个）
      await dialog.locator('input[type="text"]').fill('新加工项')

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
      // select 顺序（#4882 去计价方式后）：0=加工分类, 1=优惠
      const discountSelect = dialog.locator('select').nth(1)
      await discountSelect.selectOption('amount_off')
      // 应显示满X件选择和折扣力度输入
      await expect(dialog.getByText('折')).toBeVisible()
    })

    test('新增弹窗应含加工分类下拉且默认选中第一个分类', async ({ page }) => {
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      // 加工分类字段可见（P0 验证：此前该字段缺失，提交强取 categories[0]，新租户空列表时提交 'default' 报「加工分类不存在」）
      await expect(dialog.getByText('加工分类')).toBeVisible()
      const categorySelect = dialog.locator('select').nth(0)
      await expect(categorySelect).toHaveValue('cat_proc_001')
      await expect(categorySelect.locator('option')).toContainText('窗帘加工')
    })

    test('无加工分类时弹窗显示创建引导并可一键创建', async ({ page }) => {
      // 覆盖：加工分类接口返回空列表 → 弹窗应显示内联创建区（P0-2 流程断点修复）
      await page.route('**/api/admin/processing-categories*', async (route) => {
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ code: 200, data: { id: 'cat_new_001', name: '基础加工' } }),
          })
        } else {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ code: 200, data: [] }),
          })
        }
      })
      // 重新加载使空分类生效
      await page.goto('/production/processing')
      await page.getByRole('button', { name: /添加加工项/ }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await expect(dialog.getByText(/还没有加工分类/)).toBeVisible()
      await dialog.getByPlaceholder('请输入加工分类名称，如：基础加工').fill('基础加工')
      await dialog.getByRole('button', { name: '创建' }).click()
      // 创建后分类 select 出现且选中新分类
      const categorySelect = dialog.locator('select').nth(0)
      await expect(categorySelect).toBeVisible()
      await expect(categorySelect).toHaveValue('cat_new_001')
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
    test.skip('无数据时应显示空状态提示', async ({ page }) => {
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
      await expect(page.getByText('暂无加工项，点击右上角「添加加工项」开始创建')).toBeVisible()
    })
  })
})
