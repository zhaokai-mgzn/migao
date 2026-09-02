// case_ids: PP-002
import { test, expect } from '../../fixtures'

/**
 * 分类管理 E2E 测试
 *
 * 验证分类树渲染、增删改查、对话框交互等完整流程。
 */

const MOCK_CATEGORIES = [
  {
    id: 'cat_001',
    name: '窗帘布艺',
    sort: 1,
    children: [
      { id: 'cat_002', name: '遮光帘', sort: 1, children: [] },
      { id: 'cat_003', name: '纱帘', sort: 2, children: [] },
    ],
  },
  {
    id: 'cat_004',
    name: '沙发面料',
    sort: 2,
    children: [],
  },
]

interface MockCategory {
  id: string
  name: string
  sort: number
  children?: MockCategory[]
}

// 可变的 mock「后端」状态：PUT 落库、GET 读取（等价 sort_order 列持久化）
let mockState: MockCategory[] = []

// 等价后端列表查询 ORDER BY sort ASC, id ASC：深拷贝并按 sort 升序重排
function sortedClone(nodes: MockCategory[]): MockCategory[] {
  return [...nodes]
    .map((n) => ({ ...n, children: n.children ? sortedClone(n.children) : [] }))
    .sort((a, b) => a.sort - b.sort || (a.id < b.id ? -1 : 1))
}

// 递归更新指定分类的 sort（模拟 UPDATE categories SET sort_order = ?）
function setNodeSort(nodes: MockCategory[], id: string, sort: number): boolean {
  for (const n of nodes) {
    if (n.id === id) {
      n.sort = sort
      return true
    }
    if (n.children && setNodeSort(n.children, id, sort)) return true
  }
  return false
}

test.describe('分类管理', () => {
  test.beforeEach(async ({ page }) => {
    // 每个用例从初始数据重置 mock 后端
    mockState = sortedClone(MOCK_CATEGORIES)
    // 拦截分类列表 API
    await page.route('**/api/admin/categories*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 200, data: mockState }),
        })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      }
    })

    await page.goto('/categories')
    await expect(page.getByRole('heading', { name: '分类管理' })).toBeVisible()
  })

  test.describe('页面加载', () => {
    test('应显示页面标题和描述', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '分类管理' })).toBeVisible()
      await expect(page.getByText('管理商品分类，支持对分类进行新增、编辑、删除和排序')).toBeVisible()
    })

    test('应渲染分类树结构', async ({ page }) => {
      await expect(page.getByText('窗帘布艺')).toBeVisible()
      await expect(page.getByText('沙发面料')).toBeVisible()
    })

    test('子分类应默认展开显示', async ({ page }) => {
      await expect(page.getByText('遮光帘')).toBeVisible()
      await expect(page.getByText('纱帘')).toBeVisible()
    })
  })

  test.describe('分类树交互', () => {
    test('折叠按钮应隐藏子分类', async ({ page }) => {
      // 找到窗帘布艺旁边的折叠按钮
      const treeNode = page.locator('text=窗帘布艺').locator('..')
      const toggleBtn = treeNode.locator('button').first()
      await toggleBtn.click()
      // 子分类应被隐藏
      await expect(page.getByText('遮光帘')).toBeHidden()
    })

    test('再次展开应重新显示子分类', async ({ page }) => {
      const treeNode = page.locator('text=窗帘布艺').locator('..')
      const toggleBtn = treeNode.locator('button').first()
      await toggleBtn.click()
      await expect(page.getByText('遮光帘')).toBeHidden()
      await toggleBtn.click()
      await expect(page.getByText('遮光帘')).toBeVisible()
    })

    test('hover 应显示编辑和删除操作', async ({ page }) => {
      const treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await expect(treeNode.getByTitle('编辑')).toBeVisible()
      await expect(treeNode.getByTitle('删除')).toBeVisible()
    })
  })

  test.describe('添加分类', () => {
    test('点击添加分类按钮应打开对话框', async ({ page }) => {
      // 精确匹配 header 按钮（避免 CategoryTree 中 title="添加子分类" 的按钮干扰）
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      // 对话框标题也为"添加分类"，取第一个可见元素
      await expect(page.getByText('添加分类').first()).toBeVisible()
      // 对话框应包含名称输入框
      await expect(page.locator('input[placeholder="请输入分类名称"]')).toBeVisible()
    })

    test('分类名称为空提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      // 点击对话框内的添加按钮
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '添加' }).click()
      await expect(page.getByText('请输入分类名称')).toBeVisible()
    })

    test('填写名称后应成功创建', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.locator('input[placeholder="请输入分类名称"]').fill('新分类')
      await dialog.getByRole('button', { name: '添加' }).click()
      // 成功后对话框关闭
      await expect(dialog).toBeHidden()
    })

    test('对话框应包含分类名称输入', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      await expect(page.getByText('分类名称')).toBeVisible()
    })

    test('对话框应包含排序字段', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      await expect(page.getByText('排序', { exact: true })).toBeVisible()
    })
  })

  test.describe('编辑分类', () => {
    test('编辑对话框应回填分类名称', async ({ page }) => {
      // 拦截更新 API
      await page.route('**/api/admin/categories/cat_001', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      })

      // hover 并点击编辑
      const treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('编辑').click()

      // 对话框标题为"编辑分类"
      await expect(page.getByText('编辑分类')).toBeVisible()
      // 名称应回填
      const nameInput = page.locator('input[placeholder="请输入分类名称"]')
      await expect(nameInput).toHaveValue('窗帘布艺')
    })
  })

  test.describe('删除分类', () => {
    test('点击删除应弹出确认对话框', async ({ page }) => {
      const treeNode = page.locator('text=沙发面料').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('删除').click()
      // 取第一个"确认删除"（Modal 标题），避免 strict mode
      await expect(page.getByText('确认删除').first()).toBeVisible()
      await expect(page.getByText(/确定要删除分类/)).toBeVisible()
    })

    test('含子分类的删除应显示警告', async ({ page }) => {
      const treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('删除').click()
      await expect(page.getByText(/该分类下还有.*子分类/)).toBeVisible()
    })

    test('确认删除应调用 API', async ({ page }) => {
      let deleteCalled = false
      await page.route('**/api/admin/categories/cat_004', async (route) => {
        if (route.request().method() === 'DELETE') {
          deleteCalled = true
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
        } else {
          await route.fallback()
        }
      })

      const treeNode = page.locator('text=沙发面料').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('删除').click()
      await page.getByRole('button', { name: '确认删除' }).click()
      await page.waitForTimeout(500)
      expect(deleteCalled).toBe(true)
    })
  })

  test.describe('排序持久化（issue #1832）', () => {
    // 修改 cat_001（窗帘布艺）sort → 保存 → 刷新，断言仍为修改值
    test('修改排序值保存后刷新仍保留', async ({ page }) => {
      let putSort: number | undefined
      await page.route('**/api/admin/categories/cat_001', async (route) => {
        if (route.request().method() === 'PUT') {
          const body = route.request().postDataJSON()
          putSort = Number(body?.sort)
          setNodeSort(mockState, 'cat_001', Number.isFinite(putSort) ? putSort : 0)
          mockState = sortedClone(mockState)
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
        } else {
          await route.fallback()
        }
      })

      // 打开「窗帘布艺」编辑对话框，把排序从 1 改为 10
      let treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('编辑').click()
      const sortInput = page.getByRole('spinbutton')
      await expect(sortInput).toHaveValue('1')
      await sortInput.fill('10')

      // 保存
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(dialog).toBeHidden()

      // 提交 payload 必带 sort
      expect(putSort).toBe(10)

      // 刷新页面后排序值保留
      await page.reload()
      await expect(page.getByRole('heading', { name: '分类管理' })).toBeVisible()
      treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('编辑').click()
      await expect(page.getByRole('spinbutton')).toHaveValue('10')
    })

    // 排序值调大后列表按 sort 升序重排（等价后端 ORDER BY sort ASC）
    test('调整排序保存后刷新，列表按 sort 升序展示', async ({ page }) => {
      await page.route('**/api/admin/categories/cat_001', async (route) => {
        if (route.request().method() === 'PUT') {
          const body = route.request().postDataJSON()
          const sort = Number(body?.sort)
          setNodeSort(mockState, 'cat_001', Number.isFinite(sort) ? sort : 0)
          mockState = sortedClone(mockState)
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
        } else {
          await route.fallback()
        }
      })

      // 窗帘布艺 sort 1 → 10（沙发面料保持 sort 2），保存
      let treeNode = page.locator('text=窗帘布艺').locator('..')
      await treeNode.hover()
      await treeNode.getByTitle('编辑').click()
      // 先等对话框表单完成回填（useEffect 填充 name/sort），避免提交空表单
      const sortInput = page.getByRole('spinbutton')
      await expect(sortInput).toHaveValue('1')
      await sortInput.fill('10')
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(dialog).toBeHidden()

      // 刷新 → 沙发面料(sort=2) 应在 窗帘布艺(sort=10) 上方
      await page.reload()
      const sofa = page.getByText('沙发面料', { exact: true })
      const curtain = page.getByText('窗帘布艺', { exact: true })
      await expect(sofa).toBeVisible()
      await expect(curtain).toBeVisible()
      const sofaBox = await sofa.boundingBox()
      const curtainBox = await curtain.boundingBox()
      expect(sofaBox!.y).toBeLessThan(curtainBox!.y)
    })
  })

})
