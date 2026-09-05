// case_ids: CT-001, CT-002, CT-003
import { test, expect } from '../../fixtures'

/**
 * 分类管理 E2E 测试（issue #2905 — 分类排序重构）
 *
 * 验证扁平分类列表渲染、增删改查、上移/下移排序、对话框交互。
 * - 无父子分类：平铺渲染，无折叠/展开、无「添加子分类」
 * - 排序方式：上移/下移按钮（首行禁上移、末行禁下移）
 * - 对话框无「排序」输入框
 */

const MOCK_CATEGORIES = [
  { id: 'cat_001', name: '窗帘布艺', sort: 0 },
  { id: 'cat_002', name: '遮光帘', sort: 1 },
  { id: 'cat_003', name: '纱帘', sort: 2 },
  { id: 'cat_004', name: '沙发面料', sort: 3 },
]

interface MockCategory {
  id: string
  name: string
  sort: number
}

// 可变的 mock「后端」状态：move 落库并重排、GET 读取（等价 sort_order 列持久化）
let mockState: MockCategory[] = []

// 深拷贝并按 sort 升序重排
function sortedClone(nodes: MockCategory[]): MockCategory[] {
  return [...nodes].map((n) => ({ ...n })).sort((a, b) => a.sort - b.sort)
}

// 等价后端 move：交换相邻位置后重排 sort（0..n-1）
function applyMove(nodes: MockCategory[], id: string, direction: 'up' | 'down'): void {
  const ordered = sortedClone(nodes)
  const idx = ordered.findIndex((n) => n.id === id)
  if (idx < 0) return
  const target = direction === 'up' ? idx - 1 : idx + 1
  if (target < 0 || target >= ordered.length) return
  ;[ordered[idx], ordered[target]] = [ordered[target], ordered[idx]]
  ordered.forEach((n, i) => {
    n.sort = i
  })
  nodes.length = 0
  nodes.push(...ordered)
}

test.describe('分类管理', () => {
  test.beforeEach(async ({ page }) => {
    // 每个用例从初始数据重置 mock 后端
    mockState = sortedClone(MOCK_CATEGORIES)
    // 拦截分类 API：列表（GET）+ 资源操作（PUT/DELETE）+ move（POST /{id}/move）
    // 注意：Playwright glob 中 `*` 不跨 `/`，`categories*` 匹配不到深层 move 路径，
    // 必须用 `categories/**` 兜底资源级请求，否则 move 会穿透到真实后端
    await page.route('**/api/admin/categories**', async (route) => {
      const req = route.request()
      const url = req.url()
      if (req.method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 200, data: sortedClone(mockState) }),
        })
      } else if (req.method() === 'POST' && url.includes('/move')) {
        const body = req.postDataJSON()
        const id = url.split('/categories/')[1]?.split('/')[0]
        applyMove(mockState, id, body?.direction)
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      } else if (req.method() === 'POST') {
        const body = req.postDataJSON()
        // 新分类默认追加到末尾（后端 append 语义）
        const nextSort = mockState.length
        mockState.push({ id: `cat_new_${Date.now()}`, name: body?.name ?? '新分类', sort: nextSort })
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 200, data: { id: 'cat_new', name: body?.name } }),
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

    test('应平铺渲染全部分类', async ({ page }) => {
      await expect(page.getByText('窗帘布艺', { exact: true })).toBeVisible()
      await expect(page.getByText('遮光帘', { exact: true })).toBeVisible()
      await expect(page.getByText('纱帘', { exact: true })).toBeVisible()
      await expect(page.getByText('沙发面料', { exact: true })).toBeVisible()
    })
  })

  test.describe('上移/下移排序（issue #2905）', () => {
    test('点击上移按钮应调 move API 并刷新列表', async ({ page }) => {
      const row = page.locator('text=遮光帘').locator('..')
      await row.getByTitle('上移').click()
      await page.waitForTimeout(300)
      const moved = page.getByText('遮光帘', { exact: true })
      const first = page.getByText('窗帘布艺', { exact: true })
      const movedBox = await moved.boundingBox()
      const firstBox = await first.boundingBox()
      expect(movedBox!.y).toBeLessThan(firstBox!.y)
    })

    test('点击下移按钮应调 move API 并刷新列表', async ({ page }) => {
      const row = page.locator('text=窗帘布艺').locator('..')
      await row.getByTitle('下移').click()
      await page.waitForTimeout(300)
      const moved = page.getByText('窗帘布艺', { exact: true })
      const second = page.getByText('遮光帘', { exact: true })
      const movedBox = await moved.boundingBox()
      const secondBox = await second.boundingBox()
      expect(movedBox!.y).toBeGreaterThan(secondBox!.y)
    })

    test('首行禁用上移、末行禁用下移', async ({ page }) => {
      const firstRow = page.locator('text=窗帘布艺').locator('..')
      await expect(firstRow.getByTitle('已在最前')).toBeDisabled()
      await expect(firstRow.getByTitle('下移')).toBeEnabled()

      const lastRow = page.locator('text=沙发面料').locator('..')
      await expect(lastRow.getByTitle('已在最后')).toBeDisabled()
      await expect(lastRow.getByTitle('上移')).toBeEnabled()
    })

    test('移动后可刷新保持新顺序（持久化）', async ({ page }) => {
      const row = page.locator('text=遮光帘').locator('..')
      await row.getByTitle('上移').click()
      await page.waitForTimeout(300)
      await page.reload()
      await expect(page.getByRole('heading', { name: '分类管理' })).toBeVisible()
      const moved = page.getByText('遮光帘', { exact: true })
      const first = page.getByText('窗帘布艺', { exact: true })
      const movedBox = await moved.boundingBox()
      const firstBox = await first.boundingBox()
      expect(movedBox!.y).toBeLessThan(firstBox!.y)
    })
  })

  test.describe('添加分类', () => {
    test('点击添加分类按钮应打开对话框', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      await expect(page.getByText('添加分类').first()).toBeVisible()
      // 对话框应包含名称输入框
      await expect(page.locator('input[placeholder="请输入分类名称"]')).toBeVisible()
    })

    test('分类名称为空提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.getByRole('button', { name: '添加' }).click()
      await expect(page.getByText('请输入分类名称')).toBeVisible()
    })

    test('填写名称后应成功创建（新分类追加到末尾）', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      const dialog = page.locator('.fixed.inset-0.z-50').last()
      await dialog.locator('input[placeholder="请输入分类名称"]').fill('新分类')
      await dialog.getByRole('button', { name: '添加' }).click()
      await expect(dialog).toBeHidden()
      // 创建后刷新列表，新分类出现在末尾
      await page.waitForTimeout(300)
      const created = page.getByText('新分类', { exact: true })
      await expect(created).toBeVisible()
      const last = page.getByText('沙发面料', { exact: true })
      const createdBox = await created.boundingBox()
      const lastBox = await last.boundingBox()
      expect(createdBox!.y).toBeGreaterThan(lastBox!.y)
    })

    test('对话框不应包含排序输入框（issue #2905）', async ({ page }) => {
      await page.getByRole('button', { name: '添加分类', exact: true }).click()
      await expect(page.getByText('分类名称')).toBeVisible()
      await expect(page.getByText('排序', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('spinbutton')).toHaveCount(0)
    })
  })

  test.describe('编辑分类', () => {
    test('编辑对话框应回填分类名称', async ({ page }) => {
      const row = page.locator('text=窗帘布艺').locator('..')
      await row.hover()
      await row.getByTitle('编辑').click()

      await expect(page.getByText('编辑分类')).toBeVisible()
      const nameInput = page.locator('input[placeholder="请输入分类名称"]')
      await expect(nameInput).toHaveValue('窗帘布艺')
    })
  })

  test.describe('删除分类', () => {
    test('点击删除应弹出确认对话框', async ({ page }) => {
      const row = page.locator('text=沙发面料').locator('..')
      await row.hover()
      await row.getByTitle('删除').click()
      await expect(page.getByText('确认删除').first()).toBeVisible()
      await expect(page.getByText(/确定要删除分类/)).toBeVisible()
    })

    test('删除确认不再提示子分类（扁平结构）', async ({ page }) => {
      const row = page.locator('text=窗帘布艺').locator('..')
      await row.hover()
      await row.getByTitle('删除').click()
      await expect(page.getByText(/该分类下还有.*子分类/)).toHaveCount(0)
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

      const row = page.locator('text=沙发面料').locator('..')
      await row.hover()
      await row.getByTitle('删除').click()
      await page.getByRole('button', { name: '确认删除' }).click()
      await page.waitForTimeout(500)
      expect(deleteCalled).toBe(true)
    })
  })
})