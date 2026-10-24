// case_ids: PRC-005, UI-038
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import CustomerPicker, { type CustomerChoice } from '@/components/customers/CustomerPicker'

/**
 * 客户选择器（公共件，issue #7622）。
 *
 * ## 为什么有它
 *
 * 用户 2026-10-24 两张截图逐字：「允许选择客户，有通用组件」。
 * 改前价格本有两处让人**手打客户 id**（雪花号字符串）—— 那既不可能也不该发生（#5904 同族：
 * 内部标识永远不该交给人填）。本组件把「要一个客户」收敛成一处：搜姓名 / 手机号 → 选中 →
 * 回传 `{ id, label, phone }`，调用方拿得到展示名（列表里不必再印内部 id）。
 *
 * ## 三条判据（会红）
 *
 * 1. 选中回传的是**真实客户 id + 展示名**（姓名三种字段都可能缺 ⇒ 缺名给「未命名客户」，不给空白）；
 * 2. 选中后是**可清除的选择结果**（清除 = 回到搜索，不是把 id 清成空串留给调用方猜）；
 * 3. **读故障 ≠ 没有客户**（#6691 同族）：接口失败要说「没读到」+ 重试，不许写「没有匹配的客户」。
 */
const customerApi = vi.hoisted(() => ({ getCustomers: vi.fn() }))
vi.mock('@/lib/api', () => ({ customerApi }))

const CUSTOMERS = [
  { id: 'c-1', wechatNickname: '王芳', phone: '13800001111' },
  { id: 'c-2', name: '李强', phone: '13900002222' },
]

/** 受控用法（真实页面就是这样用的：值住在调用方，组件不存影子状态） */
function Harness({ onChange }: { onChange: (choice: CustomerChoice | null) => void }) {
  const [value, setValue] = useState<CustomerChoice | null>(null)
  return (
    <CustomerPicker
      value={value}
      testIdPrefix="customer"
      onChange={(choice) => {
        setValue(choice)
        onChange(choice)
      }}
    />
  )
}

async function search(keyword: string) {
  const input = screen.getByTestId('customer-input')
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: keyword } })
}

describe('客户选择器', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    customerApi.getCustomers.mockImplementation(() =>
      Promise.resolve({ data: { success: true, data: { items: CUSTOMERS, total: 2, page: 1, size: 20 } } }),
    )
  })

  it('🔴 搜姓名/手机号 → 选中回传「真实客户 id + 展示名 + 手机号」，列表里不印内部 id', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)

    await search('王')
    fireEvent.click(await screen.findByTestId('customer-option-c-1', undefined, { timeout: 3000 }))

    expect(onChange).toHaveBeenCalledWith({ id: 'c-1', label: '王芳', phone: '13800001111' })
    // 选中后收成一个可读的结论：展示名 + 手机号（**不**显示 c-1 这种内部 id）
    const selected = screen.getByTestId('customer-selected')
    expect(selected).toHaveTextContent('王芳')
    expect(selected).toHaveTextContent('13800001111')
    expect(selected).not.toHaveTextContent('c-1')
    // 发给后端的检索词是**人写的东西**（不是 id）
    expect(customerApi.getCustomers).toHaveBeenCalledWith(expect.objectContaining({ keyword: '王' }))
  })

  it('🔴 选中结果可清除：清除 = 回到搜索框并回传 null（不留一个空串 id 给调用方猜）', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)

    await search('王')
    fireEvent.click(await screen.findByTestId('customer-option-c-1', undefined, { timeout: 3000 }))
    fireEvent.click(screen.getByTestId('customer-clear'))

    expect(onChange).toHaveBeenLastCalledWith(null)
    expect(screen.queryByTestId('customer-selected')).not.toBeInTheDocument()
    expect(screen.getByTestId('customer-input')).toBeInTheDocument()
  })

  it('🔴 读故障 ≠「没有这个客户」：接口失败说「没读到」+ 重试，恢复后能选出人', async () => {
    customerApi.getCustomers.mockRejectedValueOnce(new Error('network'))
    render(<Harness onChange={vi.fn()} />)

    await search('王')
    const error = await screen.findByTestId('customer-error', undefined, { timeout: 3000 })
    expect(error).toHaveTextContent('没读到')
    expect(screen.queryByTestId('customer-empty')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('customer-retry'))
    fireEvent.click(await screen.findByTestId('customer-option-c-1', undefined, { timeout: 3000 }))
    expect(screen.getByTestId('customer-selected')).toHaveTextContent('王芳')
  })
})
