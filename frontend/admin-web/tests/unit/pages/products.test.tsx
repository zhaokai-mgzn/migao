// case_ids: PR-010
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ===== Override next/navigation mock with mutable searchParams (issue #660) =====
const { mockReplace, getSearchParams, resetSearchParams } = vi.hoisted(() => {
  let searchParams = new URLSearchParams()
  return {
    mockReplace: vi.fn((url: string | URL) => {
      const urlStr = typeof url === 'string' ? url : url.toString()
      const qs = urlStr.split('?')[1] || ''
      searchParams = new URLSearchParams(qs)
    }),
    getSearchParams: () => searchParams,
    resetSearchParams: () => { searchParams = new URLSearchParams() },
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: mockReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/products',
  useSearchParams: () => getSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

// Mock API
const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
const mockDeleteProduct = vi.fn()
const mockUpdateProductStatus = vi.fn()
// issue #4783：导出链路（原测试**零覆盖** ⇒ 该页导出文件名无任何断言）
const mockExportProducts = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    deleteProduct: (...args: any[]) => mockDeleteProduct(...args),
    updateProductStatus: (...args: any[]) => mockUpdateProductStatus(...args),
    exportProducts: (...args: any[]) => mockExportProducts(...args),
  },
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock ProductTable
vi.mock('@/components/products/ProductTable', () => ({
  default: ({ products, loading, total, page, pageSize, onPageChange, onDelete }: any) => (
    <div data-testid="product-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {!loading && products.length === 0 && <div data-testid="table-empty">暂无数据</div>}
      {products.map((p: any) => (
        <div key={p.id} data-testid={`product-${p.id}`}>
          <span>{p.name}</span>
          <button onClick={() => onDelete(p)} data-testid={`delete-${p.id}`}>删除</button>
        </div>
      ))}
      <div data-testid="table-info">共 {total} 条, 第 {page} 页</div>
    </div>
  ),
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>,
  Select: ({ label, options, value, onChange, ...props }: any) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={onChange} data-testid={`select-${label}`}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
  Input: ({ label, value, onChange, onKeyDown, ...props }: any) => (
    <div>
      <label htmlFor={`input-${label}`}>{label}</label>
      <input id={`input-${label}`} value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
    </div>
  ),
  Modal: ({ open, onClose, title, children, footer }: any) => (
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null
  ),
  EmptyState: ({ title, description, action }: any) => (
    <div data-testid="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  ),
}))

import ProductsPage from '@/app/(dashboard)/products/page'

const mockProducts = [
  { id: '1', name: '遮光窗帘A', sku: 'SKU001', status: 'on_sale', price: 199 },
  { id: '2', name: '纱帘B', sku: 'SKU002', status: 'off_sale', price: 99 },
  { id: '3', name: '卷帘C', sku: 'SKU003', status: 'draft', price: 159 },
]

describe('ProductsPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    resetSearchParams()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: mockProducts, total: 3 } },
    })
    mockGetCategories.mockResolvedValue({
      data: { data: [] },
    })
  })

  it('should render page title', async () => {
    render(<ProductsPage />)
    expect(screen.getByText('商品列表')).toBeInTheDocument()
  })

  it('should render add product button', () => {
    render(<ProductsPage />)
    expect(screen.getByText('新增商品')).toBeInTheDocument()
  })

  it('should load and display products', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('product-1')).toBeInTheDocument()
      expect(screen.getByText('遮光窗帘A')).toBeInTheDocument()
    })
  })

  it('should show product table with correct total', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('table-info')).toHaveTextContent('共 3 条')
    })
  })

  it('should load products on mount', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalled()
    })
  })

  it('should show search/filter section when products exist', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByText('商品ID')).toBeInTheDocument()
    })
  })

  it.skip('should show empty state when no products and no filters', async () => {
    // TODO: ProductTable mock 的 loading 状态与真实组件不同步，
    // 需要重构 mock 或直接用真实 ProductTable 组件
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<ProductsPage />)
    const emptyState = await screen.findByTestId('table-empty')
    expect(emptyState).toBeInTheDocument()
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('should call API with search params', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, size: 10 })
      )
    })
  })

  it('should open delete confirmation modal', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // ═══════════════════════════════════════════════════════════
  // Issue #660: 筛选字段 onChange → 立即查询
  // CONTRACT_JSON business_truths:
  //   1. 切换状态筛选 → 列表立即按新状态重新查询并刷新
  //   2. 切换商品ID/名称/SKU/创建时间 → 列表立即按新条件重新查询
  //   3. 切换任何筛选条件 → 分页自动重置到第 1 页
  //   4. 输入框筛选(名称/SKU/商品ID) → 300ms debounce 后才触发查询
  //   5. 点"搜索"按钮 → 行为与切换筛选条件一致
  // ═══════════════════════════════════════════════════════════

  it('should refetch when status filter changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const statusSelect = screen.getByRole('combobox')
    await user.selectOptions(statusSelect, 'on_sale')

    // 立即触发 syncUrl → router.replace 被调用，包含 status=on_sale&page=1
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('status=on_sale'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should reset page to 1 when status filter changes', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const statusSelect = screen.getByRole('combobox')
    await user.selectOptions(statusSelect, 'off_sale')

    await waitFor(() => {
      const calls = mockReplace.mock.calls
      const lastCall = calls[calls.length - 1]
      const url = lastCall[0] as string
      expect(url).toContain('page=1')
      expect(url).toContain('status=off_sale')
    })
  })

  it('should refetch when createdFrom date changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const dateInput = screen.getByPlaceholderText('开始日期')
    await user.clear(dateInput)
    await user.type(dateInput, '2025-01-01')

    // 日期选择器 onChange 触发 syncUrl
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('createdFrom=2025-01-01'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should refetch when createdTo date changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const dateInput = screen.getByPlaceholderText('结束日期')
    await user.clear(dateInput)
    await user.type(dateInput, '2025-12-31')

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('createdTo=2025-12-31'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should debounce text input changes by 300ms before syncUrl', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const nameInput = screen.getByPlaceholderText('请输入商品标题')
    await user.clear(nameInput)
    await user.type(nameInput, '遮光')

    // 立即检查：syncUrl 不应被调用（还在 300ms debounce 期内）
    expect(mockReplace).not.toHaveBeenCalledWith(
      expect.stringContaining('name='),
      expect.anything()
    )

    // 等待 350ms（超过 300ms debounce）
    await new Promise(r => setTimeout(r, 350))

    // 现在 syncUrl 应该被调用，name 被 URLSearchParams 自动编码
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining('name=%E9%81%AE%E5%85%89'), // encodeURIComponent('遮光')
      expect.anything()
    )
  })

  it('should keep Enter key search working after onChange debounce', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    // 搜索按钮点击仍应立即触发查询（非 debounce）
    const searchButton = screen.getByText('查询')
    await user.click(searchButton)

    // handleSearch → syncUrl({ page: 1 }) 被立即调用
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('page=1'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  // ═══════════════════════════════════════════════════════════
  // Issue #1200: low_stock=true → stockBelow=100 传给 API
  // ═══════════════════════════════════════════════════════════

  it('should pass stockBelow=100 to API when low_stock=true (#1200)', async () => {
    const sp = getSearchParams()
    sp.set('low_stock', 'true')

    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledWith(
        expect.objectContaining({
          stockBelow: 100,
          sortBy: 'stock',
          sortOrder: 'asc',
        })
      )
    })
  })

  it('should NOT pass stockBelow when low_stock is not true (#1200)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      const callArgs = mockGetProducts.mock.calls[0]?.[0]
      expect(callArgs).toBeDefined()
      expect(callArgs.stockBelow).toBeUndefined()
    })
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// issue #4783：导出文件名用**本地日**（原 `new Date().toISOString().slice(0, 10)` = UTC 日）
//
// 缺陷：UTC+8 下每天 00:00~08:00（CST）这 8 小时里 UTC 日 = 前一天 ⇒ 文件名
// `products_YYYY-MM-DD.xlsx` 的日期与商家认知不符（#4772 的「每月 1 日查上一个月」同族）。
//
// 判据形态（把「CST 的 8 小时窗口」在测试内复现 ⇒ CI 与开发机跑**同一条判定**、都有判别力）：
// ① 本 describe 用 `vi.stubEnv('TZ', 'Asia/Shanghai')` 把**进程本地时区**钉成 UTC+8
//    （实测有效：stub 后 `new Date('2026-10-01T00:30:00+08:00').getDate()` = 1、
//    `getTimezoneOffset()` = -480）。**不这么做就没有判别力**：CI runner 是 **UTC**
//    ⇒「UTC 日 == 本地日」⇒ 旧实现也会绿（#4774 的第一版红证就是这样被静默骗过的）。
// ② 固定时刻取**显式 `+08:00` 偏移**（绝对时刻，与机器时区无关）= CST 2026-10-01 00:30，
//    其 UTC 表示是 2026-09-30T16:30:00Z ⇒ **缺陷窗口正中**。
// ③ 期望值 = **同一冻结时刻的本地日**（`expectedLocalDay(冻结时刻)`，与页面
//    `formatLocalDate` 同源派生），**不是硬编码字符串** ⇒ 页面若回退成 UTC 日，两者立刻不等。
// ④ **判别力护栏**：断言是**具体文件名**（`expect.stringMatching(/\d{4}-\d{2}-\d{2}/)` 这类
//    恒真形态**不用**）；并显式断言「该时刻的 UTC 日 ≠ 本地日」以证明窗口真的被复现。
// ═══════════════════════════════════════════════════════════════════════════

// 与页面 `formatLocalDate` 同源派生（同样只用本地 getter）——期望值不得硬编码
const expectedLocalDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

describe('导出文件名 = 本地日（issue #4783 红证）', () => {
  const user = userEvent.setup()
  // 被点击 `<a>` 的 download 值（= 实际文件名）。用**手动原型覆写**而非 `vi.spyOn`：
  // 本文件有模块级 `vi.fn()` 替身，文件级 `vi.restoreAllMocks()` 会把它们清成 undefined
  // （「替身已清空、组件仍挂载」窗口 ⇒ 随机红，issue #4773；守卫
  // tests/unit_ci_workflows/test_restore_all_mocks_scope.py 的 R2）。原型方法在 afterEach 手动还原。
  const originalAnchorClick = HTMLAnchorElement.prototype.click
  let capturedFilename = ''

  beforeEach(() => {
    vi.clearAllMocks()
    resetSearchParams()
    mockGetProducts.mockResolvedValue({ data: { data: { items: mockProducts, total: 3 } } })
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
    // 导出链路在 jsdom 下所需的浏览器 API（缺一则 handleExport 抛错、断言永远看不到文件名）
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:fake'),
      revokeObjectURL: vi.fn(),
    })
    capturedFilename = ''
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      capturedFilename = this.download
    }
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    HTMLAnchorElement.prototype.click = originalAnchorClick
  })

  /** 点「批量导出」并返回实际文件名；调用方负责 unmount（一次只允许一个页面实例在场） */
  async function clickExportAndGetFilename(): Promise<{ filename: string; unmount: () => void }> {
    mockExportProducts.mockClear()
    capturedFilename = ''
    mockExportProducts.mockResolvedValue({ data: new Blob(['xlsx']) })
    const { unmount } = render(<ProductsPage />)
    const [exportButton] = screen.getAllByRole('button', { name: '批量导出' })
    await user.click(exportButton)
    await waitFor(() => expect(mockExportProducts).toHaveBeenCalled())
    await waitFor(() => expect(capturedFilename).not.toBe(''))
    return { filename: capturedFilename, unmount }
  }

  it('🔴 CST 2026-10-01 00:30 ⇒ 文件名日期 = 该时刻的**本地日**（不是 UTC 日 2026-09-30）', async () => {
    vi.stubEnv('TZ', 'Asia/Shanghai')
    const instant = new Date('2026-10-01T00:30:00+08:00') // 绝对时刻，CI 跑 UTC 也是同一个 instant
    vi.setSystemTime(instant)

    const utcDay = instant.toISOString().slice(0, 10)
    const localDay = expectedLocalDay(instant)
    // 判别力前置自断言：此刻 UTC 日 ≠ 本地日（否则本用例无判别力、旧实现也会绿）
    expect(utcDay).toBe('2026-09-30')
    expect(localDay).toBe('2026-10-01')
    expect(utcDay).not.toBe(localDay)

    // 改前（页面用 UTC 日）此断言实测红：expected 'products_2026-10-01.xlsx' / received 'products_2026-09-30.xlsx'
    const { filename, unmount } = await clickExportAndGetFilename()
    expect(filename).toBe(`products_${localDay}.xlsx`)
    unmount()
  })

  it('边界两侧：CST 07:59 与 08:01 都取**本地日**（文件名不得跟着 UTC 翻日）', async () => {
    vi.stubEnv('TZ', 'Asia/Shanghai')
    // 缺陷窗口 = CST 00:00~08:00（UTC 日落后一天）；UTC 翻日的**准确时刻** = CST 08:00
    // ⇒ 两侧各取一点：07:59（窗口内，UTC 仍是 09-30）与 08:01（窗口外，UTC 已翻到 10-01）。
    for (const cst of ['2026-10-01T07:59:00+08:00', '2026-10-01T08:01:00+08:00']) {
      const instant = new Date(cst)
      vi.setSystemTime(instant)
      const localDay = expectedLocalDay(instant)
      const utcDay = instant.toISOString().slice(0, 10)
      expect(localDay).toBe('2026-10-01')
      if (cst.includes('07:59')) {
        // 判别力：窗口内 UTC 日 = 前一天 ⇒ 旧实现（UTC 日）在此必红
        expect(utcDay).toBe('2026-09-30')
        expect(utcDay).not.toBe(localDay)
      } else {
        // 窗口外：UTC 日与本地日恰好相同（旧实现在此**本来就绿** ⇒ 判别力来自上一点）
        expect(utcDay).toBe('2026-10-01')
      }
      const { filename, unmount } = await clickExportAndGetFilename()
      expect(filename).toBe('products_2026-10-01.xlsx')
      unmount()
    }
  })

  it('文件名格式与导出内容口径不变：仍是 products_YYYY-MM-DD.xlsx 且导出参数一字未动', async () => {
    vi.stubEnv('TZ', 'Asia/Shanghai')
    vi.setSystemTime(new Date('2026-10-05T14:20:00+08:00'))
    const { filename, unmount } = await clickExportAndGetFilename()

    expect(filename).toMatch(/^products_\d{4}-\d{2}-\d{2}\.xlsx$/)
    expect(filename).toBe('products_2026-10-05.xlsx')
    // 本单只改日期口径：导出请求参数（= 导出内容的口径）必须与改动前逐字一致
    expect(mockExportProducts).toHaveBeenCalledWith({
      productId: undefined,
      name: undefined,
      skuCode: undefined,
      status: undefined,
      createdFrom: undefined,
      createdTo: undefined,
    })
    unmount()
  })
})
