// case_ids: OR-071, OR-072
/**
 * 打印流水区块（issue #7902）—— 打印预览层内的「打印流水」视图（issue #7964 搬入，入口在预览表头）。
 *
 * 判据四件事：
 * ① **一条记录 = 六个事实**：时间 / 单据 / 操作人 / 纸型 / 张数 / 结果（用户 2026-10-27 点名
 *    「能看到打印时间，操作人，单据类型」；其余是本单可解释「为什么、打废了几张」的补充列）；
 * ② **缺值不猜**：操作人 / 纸型缺 ⇒ `—`；`docTitle` 优先用**打印当时的快照**，快照缺才回落到类型名；
 * ③ **折叠态不渲染 DOM**（产品设计原则 P1）：超过 5 条时只渲染 5 行，展开后才全渲染
 *    —— CSS 隐藏不算（`queryAllByTestId` 必须真的少）；
 * ④ **读失败 ≠ 没打印过**：失败给「读取失败 + 重试」，不给「还没有打印记录」。
 *
 * ⚠️ 本文件必须是 **`.ts`**（`.github/tech-stack.yml` 的 `src/components/(.+/)?(\w+)\.tsx
 * → tests/unit/components/{2}.test.ts` 逐字映射；改成 `.tsx` 会让 QA Growth Gate 判「缺测」）⇒
 * JSX 用 `createElement` 写。
 */
import { createElement } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockListPrintLogs = vi.fn()
vi.mock('@/lib/api', () => ({
  orderApi: {
    listPrintLogs: (...args: unknown[]) => mockListPrintLogs(...args),
  },
}))

import PrintLogPanel from '@/components/orders/PrintLogPanel'
import type { PrintLogView } from '@/types'

function buildLog(overrides: Partial<PrintLogView> = {}): PrintLogView {
  return {
    id: 'pl-1',
    docType: 'sales',
    docTitle: '销售单',
    mediaId: 'continuous-241x140',
    sheets: 1,
    channel: 'browser',
    status: 'fired',
    operatorName: '王五',
    orderStatus: 'shipped',
    createdAt: '2026-10-27T15:22:00+08:00',
    ...overrides,
  }
}

function ok(data: PrintLogView[]) {
  return { data: { data } }
}

describe('打印流水区块（issue #7902）', () => {
  beforeEach(() => {
    cleanup()
    mockListPrintLogs.mockReset()
  })

  it('① 一条流水 = 时间 / 单据 / 操作人 / 纸型 / 张数 / 通道 / 结果', async () => {
    mockListPrintLogs.mockResolvedValue(ok([buildLog({ sheets: 3 })]))
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))

    const row = await screen.findByTestId('print-log-pl-1')
    expect(row).toHaveTextContent('销售单')
    expect(row).toHaveTextContent('王五')
    expect(row).toHaveTextContent('241×140mm')
    expect(row).toHaveTextContent('3') // 张数
    expect(row).toHaveTextContent('系统打印')
    expect(row).toHaveTextContent('已出纸')
    // 读面按订单 id + 默认 20 条
    expect(mockListPrintLogs).toHaveBeenCalledWith('o-1', 20)
  })

  it('② 缺值不猜：操作人缺 ⇒ `—`；docTitle 快照优先，缺快照才回落类型名', async () => {
    mockListPrintLogs.mockResolvedValue(
      ok([
        buildLog({ id: 'pl-a', operatorName: null, mediaId: null, docTitle: '面料单', docType: 'processing' }),
        buildLog({ id: 'pl-b', operatorName: '', mediaId: null, docTitle: null, docType: 'quotation' }),
      ]),
    )
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))

    const a = await screen.findByTestId('print-log-pl-a')
    // 快照名优先（加工单/面料单是同一份纸的两种名字，历史必须按当时的名字读）
    expect(a).toHaveTextContent('面料单')
    expect(a).toHaveTextContent('—') // 操作人缺 + 纸型缺
    const b = screen.getByTestId('print-log-pl-b')
    expect(b).toHaveTextContent('报价单') // 快照缺 ⇒ 回落类型名
  })

  it('③ 折叠态**不渲染**逐条 DOM：> 5 条只渲染 5 行，展开后全渲染（产品设计原则 P1）', async () => {
    const logs = Array.from({ length: 8 }, (_, i) => buildLog({ id: `pl-${i}` }))
    mockListPrintLogs.mockResolvedValue(ok(logs))
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))

    await screen.findByTestId('print-log-pl-0')
    expect(screen.getAllByTestId(/^print-log-pl-/)).toHaveLength(5)
    expect(screen.getByTestId('order-print-logs-toggle')).toHaveTextContent('查看全部 8 条')

    await userEvent.click(screen.getByTestId('order-print-logs-toggle'))
    expect(screen.getAllByTestId(/^print-log-pl-/)).toHaveLength(8)
    expect(screen.getByTestId('order-print-logs-toggle')).toHaveTextContent('收起')
  })

  it('④ 从未打印 ⇒ 空态；读失败 ⇒ 失败态 + 重试（不是空态）', async () => {
    mockListPrintLogs.mockResolvedValueOnce(ok([]))
    const { unmount } = render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))
    expect(await screen.findByTestId('order-print-logs-empty')).toHaveTextContent('还没有打印记录')
    unmount()

    mockListPrintLogs.mockRejectedValueOnce(new Error('500'))
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))
    const retry = await screen.findByTestId('order-print-logs-retry')
    expect(screen.queryByTestId('order-print-logs-empty')).toBeNull()

    mockListPrintLogs.mockResolvedValueOnce(ok([buildLog()]))
    await userEvent.click(retry)
    expect(await screen.findByTestId('print-log-pl-1')).toBeInTheDocument()
  })

  it('⑥ 读面形状异常（不是数组）⇒ 当空态处理，**不许把页面渲染打崩**', async () => {
    // 实测（CI Demo path specs）：替身把订单对象当流水返回 ⇒ 组件里 `.slice` 抛错 ⇒ 整页白屏
    mockListPrintLogs.mockResolvedValue({ data: { data: { orderNo: 'ORD-1', shipments: [] } } })
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))

    expect(await screen.findByTestId('order-print-logs-empty')).toHaveTextContent('还没有打印记录')
    // 反向自证：组件仍在（不是整体崩掉之后的空 DOM）
    expect(screen.getByTestId('order-print-logs')).toBeInTheDocument()
  })

  it('⑤ 联合打印的批次读数与蓝牙通道照实显示（同一张纸的两条通道不混为一谈）', async () => {
    mockListPrintLogs.mockResolvedValue(
      ok([buildLog({ id: 'pl-ble', channel: 'ble', batchId: 'b-1', batchIndex: 2, batchSize: 3 })]),
    )
    render(createElement(PrintLogPanel, { orderId: 'o-1', refreshKey: 0 }))

    const row = await screen.findByTestId('print-log-pl-ble')
    expect(row).toHaveTextContent('蓝牙直连')
    expect(row).toHaveTextContent('联合 2/3')
  })
})
