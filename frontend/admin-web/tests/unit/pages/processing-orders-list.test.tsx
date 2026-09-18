// case_ids: PG-024
//
// PG-024（issue #4303）：加工单列表页（/processing-orders）的**列表请求时序保护** ——
// 旧的在飞列表响应晚到，**不得**覆盖更新的列表数据（搜索/筛选/刷新/写后刷新皆然）。
// 断言分两层（后续 P3 会把列表页写入口全部移除、唯一入口改订单详情页）：
//   ① 核心/长期：旧请求晚 resolve ⇒ 列表不得回退到旧数据（**红证在这条**，与写入口无关，
//      用「查询（回车）连续两次筛选」造两个并发请求，不依赖任何写操作）；
//   ② 当前 main 有效：写操作成功后**不等**刷新即渲染新状态 —— 列表页写入口移除后（P3），
//      本条断言随对应实现一并移除，由该单更新本测试文件。
//
// 缺陷形态（issue #4303 实测：Playwright + 真后端，本地）：点「发加工」→「确认发加工」，
// 后端写成功（PATCH 200、库里 status=issued），但列表行仍显示「已生成」（DOM 在
// +0.5s/+1.0s/+1.5s 未变，+2.0s 才变）——Resource Timing 显示一个 **4174ms 才返回的旧列表 GET**
// 落在 PATCH（358ms）之后，把新数据**覆盖回旧值**；且写成功后只 loadList()，
// **不用写响应即时更新该行** ⇒ 行要等下一次列表请求返回。
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockList = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
  },
}))

// 弹窗/按钮用轻量替身（与仓内既有页面测试同惯例），断言只看用户可见文案
vi.mock('@/components/ui', () => ({
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div role="dialog" aria-label={title}>
        {children}
        <div>{footer}</div>
      </div>
    ) : null,
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

const PO_ISSUED: ProcessingOrder = { ...PO_GENERATED, status: 'issued', processor: '朝阳加工厂' }
const PO_IN_PROCESSING: ProcessingOrder = { ...PO_GENERATED, status: 'in_processing' }

/** 后端列表/写响应外壳（ApiResponse<ProcessingOrder>） */
const res = (po: ProcessingOrder) => ({ data: { data: po } })
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
    vi.spyOn(window, 'confirm').mockReturnValue(true)
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

  it('② 当前 main：写成功后不等列表刷新，行状态即反映写响应（P3 移除列表写入口后随实现一并移除）', async () => {
    const refresh = deferred() // 写后的列表刷新：保持 pending（不等它）
    mockList.mockResolvedValueOnce(listRes(PO_GENERATED)).mockReturnValueOnce(refresh.promise)
    mockUpdate.mockResolvedValue(res(PO_ISSUED))

    const user = userEvent.setup()
    render(<ProcessingOrdersPage />)
    await waitFor(() => expect(tableText()).toContain('已生成'))

    await user.click(screen.getByRole('button', { name: '发加工' }))
    await user.click(screen.getByRole('button', { name: '确认发加工' }))

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith('po-1', expect.objectContaining({ action: 'issue' }))
    )
    // 刷新请求已发出但**未 resolve** —— 行必须已经反映写响应
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
    await act(async () => {})
    expect(tableText()).toContain('已发加工')
    expect(tableText()).not.toContain('已生成')
  })
})
