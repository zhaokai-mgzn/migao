// case_ids: PG-024, PG-005
//
// PG-024（issue #4303）：加工单列表页（/processing-orders）的**列表请求时序保护** ——
// 旧的在飞列表响应晚到，**不得**覆盖更新的列表数据（搜索/筛选/刷新皆然）。
//   红证形态（issue #4303 实测：Playwright + 真后端，本地）：一个 **4174ms 才返回的旧列表 GET**
//   落在写请求（358ms）之后，把新数据**覆盖回旧值**；Resource Timing 与 DOM 采样（+0.5s/+1.0s/
//   +1.5s 仍是旧状态）双证。
//
// PG-005（issue #4305，用户裁定「从订单作为发加工的唯一入口」）：列表页**不再提供任何状态流转入口**
//   —— 发加工/开始加工/加工完成/取消 四个按钮都不渲染，只留「查看（跳订单详情）/ 生产明细」。
//   （状态机语义与订单联动改判见 ProcessingOrderServiceTest 的 PG-001/PG-005/PG-007 用例。）
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockList = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    list: (...args: unknown[]) => mockList(...args),
  },
}))

// 按钮用轻量替身（与仓内既有页面测试同惯例），断言只看用户可见文案
vi.mock('@/components/ui', () => ({
  Button: ({ children, variant, size, loading, ...props }: any) => <button {...props}>{children}</button>,
}))

import ProcessingOrdersPage from '@/app/(dashboard)/processing-orders/page'
import type { ProcessingOrder } from '@/types'

const PO_NO = 'JG-20260918-0001'

const PO_GENERATED: ProcessingOrder = {
  id: 'po-1',
  orderId: 'order-1',
  orderNo: 'MG20260918001',
  processingOrderNo: PO_NO,
  customerName: '张三',
  customerPhone: '13800138000',
  status: 'generated',
  generatedAt: '2026-09-18 10:00:00',
  items: [{ productName: '布帘', colorName: '米白', quantity: 3, unit: '米' }],
}

const PO_IN_PROCESSING: ProcessingOrder = { ...PO_GENERATED, status: 'in_processing' }

const listRes = (po: ProcessingOrder) => ({ data: { data: [po] } })

/** 可手动控制 resolve 时机的 promise（模拟「在飞的慢请求」） */
function deferred() {
  let resolve!: (value: unknown) => void
  const promise = new Promise<unknown>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

/** 列表表格的**可见文案**（状态文案是用户可见文本；失败信息里能直接看到当时 DOM 的真实状态） */
const tableText = () => screen.getByRole('table').textContent ?? ''

describe('ProcessingOrdersPage 列表请求时序（PG-024 / issue #4303）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('① 核心：旧的在飞列表响应晚 resolve，不得把列表覆盖回旧数据', async () => {
    const oldSlow = deferred() // 先发出的慢请求（旧数据快照）
    const fresh = deferred() // 后发出的快请求（新数据）
    mockList
      .mockResolvedValueOnce(listRes(PO_GENERATED)) // #1 首屏
      .mockReturnValueOnce(oldSlow.promise) // #2 慢（旧）
      .mockReturnValueOnce(fresh.promise) // #3 快（新）

    const user = userEvent.setup()
    render(<ProcessingOrdersPage />)
    await waitFor(() => expect(tableText()).toContain('已生成'))

    // 连续两次「查询」（回车提交筛选）：#2 仍在飞时又发出 #3
    const keyword = screen.getByPlaceholderText('请输入加工单号或订单号')
    await user.type(keyword, 'JG-20260918{Enter}')
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
    await user.clear(keyword)
    await user.type(keyword, 'MG20260918{Enter}')
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(3))

    // 新请求先回来：列表 = 新数据
    fresh.resolve(listRes(PO_IN_PROCESSING))
    await waitFor(() => expect(tableText()).toContain('加工中'))

    // 旧请求晚到（issue #4303 的 4174ms 形态）：**不得**覆盖已渲染的新数据
    await act(async () => {
      oldSlow.resolve(listRes(PO_GENERATED))
    })

    expect(tableText()).toContain('加工中')
    expect(tableText()).not.toContain('已生成')
  })
})

describe('ProcessingOrdersPage 入口收敛（PG-005 / issue #4305）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue(listRes(PO_GENERATED))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('② 列表页不再提供状态流转入口：四个动作按钮都不渲染', async () => {
    render(<ProcessingOrdersPage />)
    await waitFor(() => expect(tableText()).toContain('已生成'))

    for (const label of ['发加工', '开始加工', '加工完成', '取消加工单']) {
      expect(screen.queryByRole('button', { name: label })).toBeNull()
    }
    // 只留跳转类入口
    expect(screen.getByRole('button', { name: '查看' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '生产明细' })).toBeTruthy()
    // 明确引导到唯一入口（订单详情页）
    expect(tableText()).toContain('状态流转请在订单详情操作')
  })

  it('③ 行内仍渲染状态徽标（入口收敛不得连带丢进度可见性）', async () => {
    render(<ProcessingOrdersPage />)
    await waitFor(() => expect(tableText()).toContain('已生成'))
    expect(screen.getByText(PO_NO)).toBeTruthy()
  })
})
