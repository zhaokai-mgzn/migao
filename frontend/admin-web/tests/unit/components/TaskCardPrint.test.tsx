// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：可打印任务卡 —— 加工单号 + 二维码（内容 = qr_token，
// 工人扫码进小程序报工）+ 工序清单（工序名/应做数量/单位 + 手工勾选位）。
// 打印隔离走项目既有范式（ShipmentDoc：portal 到 body + 屏幕 display:none + @media print 显形）。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { ProductionPosition } from '@/types'

const QR_TOKEN = 'qr-token-abc123'

const positions: ProductionPosition[] = [
  {
    position_name: '布帘',
    operations: [
      { id: 'op-1', seq: 1, operation: '精裁-布', unit: '套', qty: 2, status: 'pending', done_qty: 0 },
      { id: 'op-2', seq: 2, operation: '外帘装袋', unit: '件', qty: 2, is_must_finish: true, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '纱帘',
    operations: [
      { id: 'op-3', seq: 1, operation: '韩褶-纱', unit: '折', qty: 24, status: 'pending', done_qty: 0 },
    ],
  },
]

describe('TaskCardPrint', () => {
  it('渲染加工单号与扫码报工说明', () => {
    render(
      <TaskCardPrint processingOrderNo="JG-20260917-0001" orderNo="MG20260917001" qrToken={QR_TOKEN} positions={positions} />
    )

    expect(screen.getByTestId('task-card-no')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('task-card-order-no')).toHaveTextContent('MG20260917001')
    // 纸面必须说清「扫码后在小程序报工」（本卡勾选只是车间纸质标记）
    expect(screen.getByText(/小程序选本工序/)).toBeInTheDocument()
  })

  it('二维码以 qr_token 为内容渲染（svg 内 title = token）', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={QR_TOKEN} positions={positions} />)

    const qr = screen.getByTestId('task-card-qr')
    expect(qr.tagName.toLowerCase()).toBe('svg')
    // qrcode.react 的 title prop → svg <title>；断言 token 真的传进了二维码组件
    expect(within(qr).getByTitle(QR_TOKEN)).toBeInTheDocument()
    expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
  })

  it('渲染工序清单：工序名 + 应做数量与单位 + 每行一个手工勾选位', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={QR_TOKEN} positions={positions} />)

    const row = screen.getByTestId('task-card-op-0')
    expect(within(row).getByText('精裁-布')).toBeInTheDocument()
    expect(within(row).getByTestId('task-card-op-qty')).toHaveTextContent('2 套')
    expect(within(row).getByTestId('task-card-op-position')).toHaveTextContent('布帘')

    expect(screen.getByTestId('task-card-op-2')).toBeInTheDocument()
    // 3 道工序 ⇒ 3 个手工勾选位（纸质勾选，报工仍在小程序完成）
    expect(screen.getAllByTestId('task-card-check')).toHaveLength(3)
    // 必完工序在纸面也标出来（打包前置，工人不能漏）
    expect(within(screen.getByTestId('task-card-op-1')).getByText('必完')).toBeInTheDocument()
  })

  it('qr_token 缺失时给出占位提示而不是空二维码', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={null} positions={positions} />)

    expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
  })
})
