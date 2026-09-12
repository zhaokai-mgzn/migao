// @vitest-environment jsdom
// case_ids: PG-001, PG-005

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProcessingOrderBlock from '@/components/orders/ProcessingOrderBlock'

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    detail: vi.fn(),
    generate: vi.fn(),
    update: vi.fn(),
  },
}))

import { processingOrderApi } from '@/lib/api'

const mockedDetail = processingOrderApi.detail as unknown as ReturnType<typeof vi.fn>
const mockedGenerate = processingOrderApi.generate as unknown as ReturnType<typeof vi.fn>

const poIssued = {
  id: 'po-1',
  orderId: 'order-001',
  orderNo: 'ORD-1',
  customerName: '张三',
  processingOrderNo: 'JG-20260912-0001',
  processor: '朝阳加工厂',
  expectedDeliveryDate: '2026-09-20',
  status: 'issued',
  items: [
    {
      productName: '布艺遮光帘A',
      colorName: '米白',
      doorWidth: '2.8米',
      sellingMethod: '散剪',
      width: 2.5,
      height: 2.8,
      quantity: 2,
      unit: '米',
      processingItems: [{ id: 'p1', name: '打孔', quantity: 2, unit: '米', options: ['四爪钩'] }],
    },
  ],
}

describe('ProcessingOrderBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('含加工项且无加工单 → 展示「生成加工单」入口（PG-001）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing />)
    expect(await screen.findByText('生成加工单')).toBeInTheDocument()
  })

  it('生成成功 → 结果可见：加工单号 + 状态时间线 + 快照明细 + 复制全部（PG-001）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedGenerate.mockResolvedValueOnce({
      data: { data: [{ orderRef: 'order-001', success: true, processingOrderNo: 'JG-20260912-0001' }] },
    })
    // 生成后重新拉取详情 → 已生成状态
    mockedDetail.mockResolvedValueOnce({ data: { data: { ...poIssued, status: 'generated', processor: undefined, expectedDeliveryDate: undefined } } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing />)
    await userEvent.click(await screen.findByText('生成加工单'))

    expect(mockedGenerate).toHaveBeenCalledWith(['order-001'])
    expect(await screen.findByText('JG-20260912-0001')).toBeInTheDocument()
    expect(screen.getAllByText('已生成').length).toBeGreaterThan(0)
    expect(screen.getByText(/打孔/)).toBeInTheDocument()
    expect(screen.getByText(/四爪钩/)).toBeInTheDocument()
    expect(screen.getByText('复制全部')).toBeInTheDocument()
  })

  it('已有加工单 issued → 展示加工方/交期/状态 + 开始加工按钮（PG-005）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    expect(await screen.findByText('JG-20260912-0001')).toBeInTheDocument()
    expect(screen.getByText(/朝阳加工厂/)).toBeInTheDocument()
    expect(screen.getByText(/2026-09-20/)).toBeInTheDocument()
    expect(screen.getAllByText('已发加工').length).toBeGreaterThan(0)
    expect(screen.getByText('开始加工')).toBeInTheDocument()
  })

  it('复制全部 → 剪贴板文本含加工单号与加工项 options（PG-005）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('JG-20260912-0001')
    expect(text).toContain('朝阳加工厂')
    expect(text).toContain('打孔（四爪钩）')
  })
})
