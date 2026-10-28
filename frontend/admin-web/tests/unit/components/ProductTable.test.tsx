// case_ids: PR-001, PR-002, PR-010, UI-055
// 追加（issue #6669 追加任务 3）：「销售额」列小数位唯一口径。
/**
 * ProductTable 组件测试
 * 覆盖：#646 移除 in_warehouse — 状态徽章映射无仓库中、操作按钮正确
 *       #1200 库存飘红阈值
 *       #5877 移除「商品ID」列 — 表头不再有该列，且 colSpan（列数）随之收敛
 *       #6669 追加任务 3 — 「销售额」列小数位口径（同一列不得并存 `¥25,049` 与 `¥26,099.8`）
 */
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ProductTable from '@/components/products/ProductTable'
import type { Product, ProductStatus } from '@/types'
import { ProductStatusLabels } from '@/types'

// Mock next/image
vi.mock('next/image', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('img', { ...props, src: props.src || '' })
  },
}))

const baseProduct: Product = {
  id: 'p001',
  name: '北欧简约遮光窗帘',
  skuCode: 'CL-GY-001',
  images: [],
  colorCount: 3,
  stock: 500,
  salesCount: 120,
  salesAmount: 36000,
  status: 'on_sale',
  createdAt: '2026-06-15T10:00:00Z',
  price: 299,
  unit: '米',
  categoryId: 'c1',
}

const defaultProps = {
  products: [baseProduct],
  loading: false,
  total: 1,
  page: 1,
  pageSize: 20,
  selectedIds: [] as string[],
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
  onSelectChange: vi.fn(),
  onSortChange: vi.fn(),
  onView: vi.fn(),
  onEdit: vi.fn(),
  onPutOnShelf: vi.fn(),
  onTakeOffShelf: vi.fn(),
  onRecommend: vi.fn(),
  onUnrecommend: vi.fn(),
  onDelete: vi.fn(),
}

// ========== 长标题可读全（issue #6662 判据 ⑤ 后半）==========
//
// `line-clamp-2` 是**有意的**版式（行高固定、不随标题长度长高），但必须给一个**读全程**的出口：
// `title` 属性（鼠标悬停可见全文）。改前只有 `line-clamp-2`、没有 `title`。
describe('ProductTable — 长标题可读全（issue #6662）', () => {
  const LONG_NAME = '2026新款高遮光免打孔客厅卧室双面同色加厚隔热遮阳窗帘布定制款'

  it('#6662 标题单元格带 title（悬停可见全文），且截断版式不变', () => {
    render(<ProductTable {...defaultProps} products={[{ ...baseProduct, name: LONG_NAME }]} />)
    const cell = screen.getByText(LONG_NAME)
    expect(cell.getAttribute('title')).toBe(LONG_NAME)
    // 负控：截断版式仍在（不是把 clamp 删了了事）
    expect(cell.className).toContain('line-clamp-2')
  })
})

// ========== 「销售额」列小数位口径（issue #6669 追加任务 3）==========
//
// 缺陷（真机读图实测）：`¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
// —— **只给上限没给下限** ⇒ **同一列**并存 `¥25,049` 与 `¥26,099.8` 两种形态
// （小数位跟着实际值截断，整数不带两位）。
// 口径 = 与财务域/计件域**同一处真值** `@/lib/money`（千分位 + **固定**两位小数）。
//
// 🔴 判别力：给一个 `26099.8` 与一个 `25049`，让它们在**同一列**渲染 ⇒ 逐条断言同形态。
// 红证（修前实测）：`expected '¥26,099.8' to be '¥26,099.80'`。
describe('ProductTable — 「销售额」列小数位唯一口径（issue #6669 追加任务 3）', () => {
  it('同列多行 ⇒ 同形态：固定两位小数 + 千分位（26099.8 与 25049 并存也不许两种写法）', () => {
    render(
      <ProductTable
        {...defaultProps}
        total={2}
        products={[
          { ...baseProduct, id: 'a', name: '甲', salesAmount: 26099.8 },
          { ...baseProduct, id: 'b', name: '乙', salesAmount: 25049 },
        ]}
      />,
    )
    // 逐值断言（不只断言「带逗号」—— 那是弱断言）
    expect(screen.getByText('¥26,099.80')).toBeTruthy()
    expect(screen.getByText('¥25,049.00')).toBeTruthy()
    // 负控：截断形态**必须不存在**
    expect(screen.queryByText('¥26,099.8')).toBeNull()
    expect(screen.queryByText('¥25,049')).toBeNull()
    expect(screen.queryByText('¥0')).toBeNull()
  })

  it('缺失销售额 ⇒ ¥0.00（不是 ¥0 / 空白）', () => {
    render(
      <ProductTable
        {...defaultProps}
        products={[{ ...baseProduct, salesAmount: undefined as unknown as number }]}
      />,
    )
    expect(screen.getByText('¥0.00')).toBeTruthy()
    expect(screen.queryByText('¥0')).toBeNull()
  })
})

describe('ProductTable (#646 — 移除 in_warehouse)', () => {
  it('应渲染商品名称', () => {
    render(<ProductTable {...defaultProps} />)
    expect(screen.getByText('北欧简约遮光窗帘')).toBeTruthy()
  })

  describe('#5877 — 「商品ID」列已移除（用户裁定：不要展示在列表）', () => {
    it('🔴 表头不含「商品ID」（精确到 thead；搜索区那个筛选项不受影响）', () => {
      const { container } = render(<ProductTable {...defaultProps} />)
      const thead = container.querySelector('thead')!
      expect(thead.textContent).not.toContain('商品ID')
      // 判据不能靠「表头整个没了」蒙对：其余列照旧
      expect(thead.textContent).toContain('商品标题')
      expect(thead.textContent).toContain('商品货号')
    })

    it('🔴 行内不再渲染商品 id 文本（title 属性不算展示）', () => {
      render(<ProductTable {...defaultProps} />)
      expect(screen.queryByText('p001')).toBeNull()
    })

    it('🔴 列数 = 10，且加载态/空态的 colSpan 随之收敛（列数变了 colSpan 没跟上 = 表格错位）', () => {
      const loading = render(<ProductTable {...defaultProps} loading products={[]} />)
      expect(loading.container.querySelectorAll('thead th')).toHaveLength(10)
      expect(loading.container.querySelector('tbody td')!.getAttribute('colspan')).toBe('10')
      loading.unmount()

      const empty = render(<ProductTable {...defaultProps} products={[]} />)
      expect(empty.container.querySelectorAll('thead th')).toHaveLength(10)
      expect(empty.container.querySelector('tbody td')!.getAttribute('colspan')).toBe('10')
      empty.unmount()

      const rows = render(<ProductTable {...defaultProps} />)
      expect(rows.container.querySelectorAll('thead th')).toHaveLength(10)
      expect(rows.container.querySelectorAll('tbody tr td')).toHaveLength(10)
    })
  })

  it('应渲染商品货号', () => {
    render(<ProductTable {...defaultProps} />)
    expect(screen.getByText('CL-GY-001')).toBeTruthy()
  })

  it('空列表显示"暂无数据"', () => {
    render(<ProductTable {...defaultProps} products={[]} total={0} />)
    expect(screen.getByText('暂无数据')).toBeTruthy()
  })

  it('加载中显示"加载中…"', () => {
    render(<ProductTable {...defaultProps} products={[]} loading={true} />)
    expect(screen.getByText('加载中...')).toBeTruthy()
  })

  describe('状态徽章映射 — 无 in_warehouse', () => {
    const statusLabels: [ProductStatus, string][] = [
      ['on_sale', '出售中'],
      ['off_sale', '已下架'],
      ['draft', '草稿'],
      ['under_review', '审核中'],
    ]

    for (const [status, label] of statusLabels) {
      it(`status="${status}" 显示「${label}」`, () => {
        const product = { ...baseProduct, status }
        render(<ProductTable {...defaultProps} products={[product]} />)
        expect(screen.getByText(label)).toBeTruthy()
      })
    }

    it('不显示「仓库中」', () => {
      const products: Product[] = [
        { ...baseProduct, id: 'p1', status: 'on_sale' },
        { ...baseProduct, id: 'p2', status: 'off_sale' },
        { ...baseProduct, id: 'p3', status: 'draft' },
        { ...baseProduct, id: 'p4', status: 'under_review' },
      ]
      render(<ProductTable {...defaultProps} products={products} total={4} />)
      expect(screen.queryByText('仓库中')).toBeNull()
    })
  })

  describe('操作列 — 「1 主行动 + ⋯ 菜单」（issue #8038）', () => {
    // issue #8038：行内动作收进共享原语 `ui/RowActions`。**收起态菜单项不进 DOM**
    // （不是 CSS 隐藏）⇒ 判据必须先点开菜单，再断言菜单项。
    const openMenu = (id = 'p001') => {
      fireEvent.click(
        within(screen.getByTestId(`product-actions-${id}`)).getByRole('button', { name: '更多操作' }),
      )
      return screen.getByRole('menu')
    }
    const menuLabels = () => screen.getAllByRole('menuitem').map((m) => m.textContent)
    const primaryOf = (id = 'p001') =>
      within(screen.getByTestId(`product-actions-${id}`)).getAllByRole('button')[0]

    it('每行可点元素 ≤ 2：1 主行动 + 1 个 ⋯ 触发器（改前在架行是 5 个平级文字链）', () => {
      const products: Product[] = [
        { ...baseProduct, id: 'p1', status: 'on_sale' },
        { ...baseProduct, id: 'p2', status: 'off_sale' },
        { ...baseProduct, id: 'p3', status: 'draft' },
        { ...baseProduct, id: 'p4', status: 'under_review' },
      ]
      render(<ProductTable {...defaultProps} products={products} total={4} />)
      for (const id of ['p1', 'p2', 'p3', 'p4']) {
        const cell = screen.getByTestId(`product-actions-${id}`)
        expect(
          within(cell).getAllByRole('button').length,
          `商品 ${id} 的操作区可点元素 > 2（又回到平铺文字链的形态了）`,
        ).toBeLessThanOrEqual(2)
      }
    })

    it('收起态：菜单项**不进 DOM**（不是 CSS 隐藏），屏上只剩主行动 + ⋯', () => {
      render(<ProductTable {...defaultProps} />)
      const cell = screen.getByTestId('product-actions-p001')
      expect(within(cell).queryByRole('menu')).toBeNull()
      expect(within(cell).queryByText('删除')).toBeNull()
      expect(within(cell).queryByText('查看')).toBeNull()
      expect(primaryOf().textContent).toBe('编辑')
    })

    it('主行动按状态派生：在架→编辑、已下架→上架、审核中→查看、草稿→编辑', () => {
      const cases: Array<[ProductStatus, string]> = [
        ['on_sale', '编辑'],
        ['off_sale', '上架'],
        ['under_review', '查看'],
        ['draft', '编辑'],
      ]
      for (const [status, expected] of cases) {
        const { unmount } = render(
          <ProductTable {...defaultProps} products={[{ ...baseProduct, id: 'x', status }]} />,
        )
        expect(primaryOf('x').textContent, `状态 ${status} 的主行动`).toBe(expected)
        unmount()
      }
    })

    it('在架行菜单项：查看 / 推荐 / 下架 / 删除（危险动作进菜单，回调一字未改）', () => {
      const onView = vi.fn()
      const onRecommend = vi.fn()
      const onTakeOffShelf = vi.fn()
      const onDelete = vi.fn()
      render(
        <ProductTable
          {...defaultProps}
          onView={onView}
          onRecommend={onRecommend}
          onTakeOffShelf={onTakeOffShelf}
          onDelete={onDelete}
        />,
      )
      openMenu()
      expect(menuLabels()).toEqual(['查看', '推荐', '下架', '删除'])

      fireEvent.click(screen.getByRole('menuitem', { name: '查看' }))
      expect(onView).toHaveBeenCalledTimes(1)
      // 点了就收起（菜单不赖在屏上）
      expect(screen.queryByRole('menu')).toBeNull()

      openMenu()
      fireEvent.click(screen.getByRole('menuitem', { name: '删除' }))
      // 危险动作只换容器：回调仍是页面那一个（二次确认由页面 Modal 承担，见 products.test.tsx）
      expect(onDelete).toHaveBeenCalledTimes(1)
    })

    it('已推荐商品的菜单项是「取消推荐」（不是两个都出现）', () => {
      const onUnrecommend = vi.fn()
      render(
        <ProductTable
          {...defaultProps}
          products={[{ ...baseProduct, recommended: true }]}
          onUnrecommend={onUnrecommend}
        />,
      )
      openMenu()
      expect(menuLabels()).toEqual(['查看', '取消推荐', '下架', '删除'])
      fireEvent.click(screen.getByRole('menuitem', { name: '取消推荐' }))
      expect(onUnrecommend).toHaveBeenCalledTimes(1)
    })

    it('已下架行：主行动「上架」，菜单里 查看 / 编辑 / 删除（不再出现「下架」）', () => {
      const onPutOnShelf = vi.fn()
      render(
        <ProductTable
          {...defaultProps}
          products={[{ ...baseProduct, status: 'off_sale' }]}
          onPutOnShelf={onPutOnShelf}
        />,
      )
      expect(primaryOf().textContent).toBe('上架')
      fireEvent.click(primaryOf())
      expect(onPutOnShelf).toHaveBeenCalledTimes(1)

      openMenu()
      expect(menuLabels()).toEqual(['查看', '编辑', '删除'])
      expect(screen.queryByRole('menuitem', { name: '下架' })).toBeNull()
    })

    it('审核中：只有「查看」，没有 ⋯ 触发器（items 为空不渲染空菜单）', () => {
      render(<ProductTable {...defaultProps} products={[{ ...baseProduct, status: 'under_review' }]} />)
      const cell = screen.getByTestId('product-actions-p001')
      expect(within(cell).getAllByRole('button').map((b) => b.textContent)).toEqual(['查看'])
      expect(within(cell).queryByRole('button', { name: '更多操作' })).toBeNull()
    })

    it('草稿：主行动「编辑」，菜单里只有「删除」', () => {
      render(<ProductTable {...defaultProps} products={[{ ...baseProduct, status: 'draft' }]} />)
      expect(primaryOf().textContent).toBe('编辑')
      openMenu()
      expect(menuLabels()).toEqual(['删除'])
    })

    it('危险项红字（`danger`）；行内层级不走实心主色（§32.2）', () => {
      render(<ProductTable {...defaultProps} />)
      openMenu()
      expect(screen.getByRole('menuitem', { name: '删除' }).className).toMatch(/text-red-600/)
      // 行内主行动 = ghost：一屏至多一个 primary，那一个是页面头的「新增商品」
      for (const b of within(screen.getByTestId('product-actions-p001')).getAllByRole('button')) {
        expect(b.className).not.toMatch(/bg-primary-600/)
      }
    })
  })

  describe('ProductStatusLabels — 无 in_warehouse', () => {
    it('只有 4 个状态标签', () => {
      const keys = Object.keys(ProductStatusLabels)
      expect(keys).toHaveLength(4)
    })

    it('不包含 in_warehouse', () => {
      expect(ProductStatusLabels).not.toHaveProperty('in_warehouse')
      expect((ProductStatusLabels as any)['in_warehouse']).toBeUndefined()
    })

    it('四个标签值正确', () => {
      expect(ProductStatusLabels.on_sale).toBe('出售中')
      expect(ProductStatusLabels.off_sale).toBe('已下架')
      expect(ProductStatusLabels.draft).toBe('草稿')
      expect(ProductStatusLabels.under_review).toBe('审核中')
    })
  })

  describe('#1400 — 行内动作横排 + whitespace-nowrap（issue #8038 起容器 = 共享原语）', () => {
    it('动作面容器（`ui/RowActions`）有 flex items-center gap-1 whitespace-nowrap', () => {
      render(<ProductTable {...defaultProps} />)
      const cell = screen.getByTestId('product-actions-p001')
      // 容器 = RowActions 的外层 div（同一行内不折行）
      expect(cell.className).toMatch(/\bflex\b/)
      expect(cell.className).toMatch(/\bitems-center\b/)
      expect(cell.className).toMatch(/\bgap-1\b/)
      expect(cell.className).toMatch(/\bwhitespace-nowrap\b/)
    })

    it('主行动走 `Button` ghost（行内层级不用实心主色），不再是自拼文字链', () => {
      render(<ProductTable {...defaultProps} />)
      const primary = within(screen.getByTestId('product-actions-p001')).getAllByRole('button')[0]
      expect(primary.textContent).toBe('编辑')
      // ghost = text-neutral-600；size="sm" = h-8（§32.2）
      expect(primary.className).toMatch(/\btext-neutral-600\b/)
      expect(primary.className).toMatch(/\bh-8\b/)
    })

    it('删除（危险动作）在菜单里是红字', () => {
      render(<ProductTable {...defaultProps} />)
      fireEvent.click(
        within(screen.getByTestId('product-actions-p001')).getByRole('button', { name: '更多操作' }),
      )
      expect(screen.getByRole('menuitem', { name: '删除' }).className).toMatch(/\btext-red-600\b/)
    })
  })

  describe('#1200 — 库存飘红阈值', () => {
    it('stock < stockWarningThreshold → 红色', () => {
      const product = { ...baseProduct, stock: 3, stockWarningThreshold: 5 }
      render(<ProductTable {...defaultProps} products={[product]} />)
      const cells = screen.getAllByText('3')
      const stockCell = cells.find(
        (el) => el.className && el.className.includes('text-red')
      )
      expect(stockCell).toBeTruthy()
    })

    it('stock >= stockWarningThreshold → 默认色', () => {
      const product = { ...baseProduct, stock: 10, stockWarningThreshold: 5 }
      render(<ProductTable {...defaultProps} products={[product]} />)
      const cells = screen.getAllByText('10')
      const stockCell = cells.find(
        (el) => el.className && el.className.includes('text-red')
      )
      expect(stockCell).toBeFalsy()
    })

    it('未配置 stockWarningThreshold → 默认阈值5，stock=3 → 红色', () => {
      const product = { ...baseProduct, stock: 3 }
      delete (product as any).stockWarningThreshold
      render(<ProductTable {...defaultProps} products={[product]} />)
      const cells = screen.getAllByText('3')
      const stockCell = cells.find(
        (el) => el.className && el.className.includes('text-red')
      )
      expect(stockCell).toBeTruthy()
    })

    it('stock = 0 → 红色加粗', () => {
      const product = { ...baseProduct, stock: 0, stockWarningThreshold: 5 }
      render(<ProductTable {...defaultProps} products={[product]} />)
      const cells = screen.getAllByText('0')
      const stockCell = cells.find(
        (el) => el.className && el.className.includes('text-red') && el.className.includes('font-bold')
      )
      expect(stockCell).toBeTruthy()
    })
  })
})
