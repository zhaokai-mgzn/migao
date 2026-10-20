// case_ids: SP-001
// 供应商档案页（issue #7369，P0-1 段 1）：列表 / 账期口径 / 建档 / 停用 四条判据。

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

// UI 原语：**先摊开真值再覆盖**（issue #7007 的教训 —— 整模块 mock 会让页面新增原语时报错）
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    Button: ({ children, onClick, loading, ...props }: any) => (
      <button onClick={onClick} disabled={loading} {...props}>{children}</button>
    ),
  }
})

vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return { ...actual, Plus: stub('plus'), Search: stub('search'), Truck: stub('truck') }
})

const mockList = vi.fn()
const mockCreate = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/lib/api', () => ({
  supplierApi: {
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
  },
}))

import SuppliersPage, { paymentTermsLabel } from '@/app/(dashboard)/suppliers/page'
import { toast } from 'sonner'

const ROWS = [
  { id: 'sup-1', name: '杭州染整一厂', contactName: '张厂长', contactPhone: '13900000000', paymentTermsDays: 30, status: 'active', remark: null },
  { id: 'sup-2', name: '绍兴现结布行', contactName: null, contactPhone: null, paymentTermsDays: 0, status: 'inactive', remark: null },
]

describe('供应商档案页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: { data: ROWS } })
    mockCreate.mockResolvedValue({ data: { data: ROWS[0] } })
    mockUpdate.mockResolvedValue({ data: { data: ROWS[0] } })
  })

  it('第一屏拉取服务端列表并如实渲染（不自己造数）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('supplier-row-sup-1')).toBeInTheDocument()
    })
    expect(screen.getByText('杭州染整一厂')).toBeInTheDocument()
    expect(screen.getByText('张厂长')).toBeInTheDocument()
    // 账期口径：30 天 / 现结（0 不是「未设置」）
    expect(screen.getByTestId('supplier-terms-sup-1')).toHaveTextContent('30 天')
    expect(screen.getByTestId('supplier-terms-sup-2')).toHaveTextContent('现结')
  })

  it('账期展示口径：未设置 / 现结 / N 天 三态可分', () => {
    expect(paymentTermsLabel(null)).toBe('未设置')
    expect(paymentTermsLabel(undefined)).toBe('未设置')
    expect(paymentTermsLabel(0)).toBe('现结')
    expect(paymentTermsLabel(45)).toBe('45 天')
  })

  it('建档：名称去空白后提交，账期留空发 null（不是 0）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新建供应商'))
    fireEvent.change(screen.getByTestId('supplier-form-name'), { target: { value: '  南通织造厂  ' } })
    fireEvent.change(screen.getByTestId('supplier-form-terms'), { target: { value: '' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({
        name: '南通织造厂',
        paymentTermsDays: null,
        status: 'active',
      }))
    })
  })

  it('停用：走同一条更新写面，带上原字段与 inactive', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('supplier-toggle-sup-1'))

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith('sup-1', expect.objectContaining({
        name: '杭州染整一厂',
        status: 'inactive',
        paymentTermsDays: 30,
      }))
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('已停用「杭州染整一厂」')
    })
  })

  it('账期越界在前端就拦下（不发请求）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新建供应商'))
    fireEvent.change(screen.getByTestId('supplier-form-name'), { target: { value: '越界厂' } })
    fireEvent.change(screen.getByTestId('supplier-form-terms'), { target: { value: '400' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('账期天数须在 0~365 之间（0 = 现结，留空 = 未设置）')
    })
    expect(mockCreate).not.toHaveBeenCalled()
  })
})
