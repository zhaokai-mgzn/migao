// case_ids: PR-060
//
// 商品批量导入的**后台可见面**（issue #5154）：导入入口 + 模板下载 + 逐行校验报告展示。
// 改前 `frontend/admin-web/src` 里「导入」**零命中**（0 处 UI）⇒ 本文件在改前全红。
//
// 判据 3 的可见面就在本文件：报告必须**同时**展示「成功 / 失败 / 空白行」三数 ——
// 只显示"成功 N 条"而把空白行/失败行吞掉，就是「少导了没人知道」的形态。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/products',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
const mockImportProducts = vi.fn()
const mockDownloadImportTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    deleteProduct: vi.fn(),
    updateProductStatus: vi.fn(),
    exportProducts: vi.fn(),
    importProducts: (...args: any[]) => mockImportProducts(...args),
    downloadImportTemplate: (...args: any[]) => mockDownloadImportTemplate(...args),
  },
  categoryApi: { getCategories: (...args: any[]) => mockGetCategories(...args) },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('@/components/products/ProductTable', () => ({
  default: () => <div data-testid="product-table" />,
}))

vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, loading, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>,
  Modal: ({ open, onClose, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Select: () => <div />,
  Input: () => <div />,
  EmptyState: () => <div />,
}))

import ProductsPage from '@/app/(dashboard)/products/page'

/** 后端 ProductImportResult 的 JSON 形态（字段名与 ProductImportResult.java 一致）。 */
const reportFixture = {
  total: 4,
  successCount: 2,
  failCount: 1,
  blankRows: 1,
  createdProducts: 1,
  updatedProducts: 1,
  errors: [
    { row: 3, skuCode: 'MH-001', message: '第 3 行库存 最多支持 1 位小数（库存按 0.1 米粒度记账），当前值 2.755 有 3 位小数 —— 请改为 1 位小数后重试（服务端不做静默取整）' },
  ],
}

describe('ProductsPage 批量导入（#5154）', () => {
  const user = userEvent.setup()
  let capturedFilename = ''

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
    mockDownloadImportTemplate.mockResolvedValue({ data: new Blob(['x']) })
    // jsdom 没有 createObjectURL（缺则 handleDownloadTemplate 抛错、断言看不到调用）
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:fake'),
      revokeObjectURL: vi.fn(),
    })
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
      capturedFilename = this.download
    }
  })

  async function renderPage() {
    render(<ProductsPage />)
    await waitFor(() => expect(mockGetProducts).toHaveBeenCalled())
  }

  function fileInput(): HTMLInputElement {
    const input = document.querySelector('input[type="file"]')
    if (!input) throw new Error('页面上没有导入用的 file input')
    return input as HTMLInputElement
  }

  it('判据1：页面上有「导入商品」入口（对偶于既有「批量导出」）', async () => {
    await renderPage()
    expect(screen.getByText('导入商品')).toBeInTheDocument()
    expect(screen.getByText('批量导出')).toBeInTheDocument()
  })

  it('判据1：选中 xlsx ⇒ 调 importProducts 并把文件原样交给后端', async () => {
    await renderPage()
    mockImportProducts.mockResolvedValue({ data: { data: reportFixture } })
    const file = new File(['x'], '商品导入.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })

    await user.upload(fileInput(), file)

    await waitFor(() => expect(mockImportProducts).toHaveBeenCalledTimes(1))
    expect(mockImportProducts.mock.calls[0][0]).toBe(file)
  })

  it('判据3：报告逐行展示 —— 成功/失败/空白三数齐备 + 行号 + 货号 + 可行动原因', async () => {
    await renderPage()
    mockImportProducts.mockResolvedValue({ data: { data: reportFixture } })

    await user.upload(fileInput(), new File(['x'], '商品导入.xlsx'))

    const modal = await screen.findByTestId('modal')
    expect(modal).toHaveTextContent('导入结果')
    // 三桶口径必须都可见（含空白行 —— 静默跳过就藏在这里）
    expect(modal).toHaveTextContent('成功 2 行')
    expect(modal).toHaveTextContent('失败 1 行')
    expect(modal).toHaveTextContent('空白行 1 行')
    expect(modal).toHaveTextContent('新建 1 个商品')
    expect(modal).toHaveTextContent('更新 1 个商品')
    // 可定位（行号 + 货号）+ 可行动（原因原文，不得被前端改写或截断）
    expect(modal).toHaveTextContent('第 3 行')
    expect(modal).toHaveTextContent('MH-001')
    expect(modal).toHaveTextContent('最多支持 1 位小数')
    expect(modal).toHaveTextContent('2.755')
  })

  it('判据3：失败行数为 0 时也要显式说「无失败行」，不留空让人猜', async () => {
    await renderPage()
    mockImportProducts.mockResolvedValue({
      data: { data: { ...reportFixture, failCount: 0, blankRows: 0, errors: [] } },
    })

    await user.upload(fileInput(), new File(['x'], 'ok.xlsx'))

    const modal = await screen.findByTestId('modal')
    expect(modal).toHaveTextContent('失败 0 行')
    expect(modal).toHaveTextContent('空白行 0 行')
    expect(modal).toHaveTextContent('无失败行')
  })

  it('判据1（对偶）：能下载导入模板，文件名带 .xlsx', async () => {
    await renderPage()
    await user.click(screen.getByText('下载导入模板'))
    await waitFor(() => expect(mockDownloadImportTemplate).toHaveBeenCalledTimes(1))
    expect(capturedFilename).toBe('商品导入模板.xlsx')
  })

  it('接口报错 ⇒ 不弹报告弹窗（不拿空报告冒充成功）', async () => {
    await renderPage()
    mockImportProducts.mockRejectedValue(new Error('解析Excel文件失败'))

    await user.upload(fileInput(), new File(['x'], 'bad.xlsx'))

    await waitFor(() => expect(mockImportProducts).toHaveBeenCalled())
    expect(screen.queryByTestId('modal')).toBeNull()
  })

  it('导入完成后刷新列表（商家立刻能看到落库结果）', async () => {
    await renderPage()
    mockImportProducts.mockResolvedValue({ data: { data: reportFixture } })
    const before = mockGetProducts.mock.calls.length

    await user.upload(fileInput(), new File(['x'], 'ok.xlsx'))

    await waitFor(() => expect(mockGetProducts.mock.calls.length).toBeGreaterThan(before))
  })
})
