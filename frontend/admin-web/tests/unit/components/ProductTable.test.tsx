// case_ids: PR-001, PR-002, PR-010, UI-055, CU-010. 「销售额」列小数位唯一口径（issue #6669 追加任务 3）
/**
 * ProductTable 组件测试
 * 覆盖：#646 移除 in_warehouse — 状态徽章映射无仓库中、操作按钮正确
 *       #1200 库存飘红阈值
 *       #5877 移除「商品ID」列 — 表头不再有该列，且 colSpan（列数）随之收敛
 *       #6669 追加任务 3 — 「销售额」列小数位口径（同一列不得并存 `¥25,049` 与 `¥26,099.8`）
 */
import { render, screen, fireEvent } from '@testing-library/react'
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

  describe('操作按钮 — 按状态', () => {
    it('on_sale 显示：查看 编辑 下架 删除', () => {
      render(<ProductTable {...defaultProps} />)
      expect(screen.getByText('查看')).toBeTruthy()
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('下架')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
    })

    it('on_sale 未推荐时显示「推荐」按钮，点击触发 onRecommend', () => {
      const onRecommend = vi.fn()
      render(<ProductTable {...defaultProps} onRecommend={onRecommend} />)
      const btn = screen.getByText('推荐')
      expect(btn).toBeTruthy()
      fireEvent.click(btn)
      expect(onRecommend).toHaveBeenCalledTimes(1)
    })

    it('on_sale 已推荐时显示「取消推荐」并触发 onUnrecommend', () => {
      const product = { ...baseProduct, recommended: true as const }
      const onUnrecommend = vi.fn()
      render(<ProductTable {...defaultProps} products={[product]} onUnrecommend={onUnrecommend} />)
      const btn = screen.getByText('取消推荐')
      expect(btn).toBeTruthy()
      expect(screen.queryByText('推荐')).toBeNull()
      fireEvent.click(btn)
      expect(onUnrecommend).toHaveBeenCalledTimes(1)
    })

    it('off_sale 不显示推荐按钮', () => {
      const product = { ...baseProduct, status: 'off_sale' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.queryByText('推荐')).toBeNull()
      expect(screen.queryByText('取消推荐')).toBeNull()
    })

    it('off_sale 显示：查看 编辑 上架 删除', () => {
      const product = { ...baseProduct, status: 'off_sale' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('查看')).toBeTruthy()
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('上架')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
      expect(screen.queryByText('下架')).toBeNull()
    })

    it('under_review 仅显示查看', () => {
      const product = { ...baseProduct, status: 'under_review' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('查看')).toBeTruthy()
      expect(screen.queryByText('编辑')).toBeNull()
      expect(screen.queryByText('上架')).toBeNull()
      expect(screen.queryByText('下架')).toBeNull()
      expect(screen.queryByText('删除')).toBeNull()
    })

    it('draft 显示：编辑 删除', () => {
      const product = { ...baseProduct, status: 'draft' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
      expect(screen.queryByText('查看')).toBeNull()
      expect(screen.queryByText('上架')).toBeNull()
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

  describe('#1400 — 操作按钮横排 + whitespace-nowrap', () => {
    it('操作按钮容器应有 flex items-center gap-3 whitespace-nowrap', () => {
      render(<ProductTable {...defaultProps} />)
      const viewBtn = screen.getByText('查看')
      const actionContainer = viewBtn.closest('div.flex')
      expect(actionContainer).toBeTruthy()
      expect(actionContainer!.className).toMatch(/\bflex\b/)
      expect(actionContainer!.className).toMatch(/\bitems-center\b/)
      expect(actionContainer!.className).toMatch(/\bgap-3\b/)
      expect(actionContainer!.className).toMatch(/\bwhitespace-nowrap\b/)
    })

    it('操作按钮应有 text-primary-600 hover:underline 样式（匹配 ActionLink）', () => {
      render(<ProductTable {...defaultProps} />)
      const viewBtn = screen.getByText('查看')
      expect(viewBtn.className).toMatch(/\btext-primary-600\b/)
      expect(viewBtn.className).toMatch(/\bhover:underline\b/)
    })

    it('删除按钮应有 text-red-500 危险样式', () => {
      render(<ProductTable {...defaultProps} />)
      const deleteBtn = screen.getByText('删除')
      expect(deleteBtn.className).toMatch(/\btext-red-500\b/)
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
