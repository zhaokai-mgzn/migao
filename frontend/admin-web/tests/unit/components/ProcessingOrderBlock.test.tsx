// @vitest-environment jsdom
// case_ids: PG-001, PG-005, UI-019, UI-030

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
const mockedUpdate = processingOrderApi.update as unknown as ReturnType<typeof vi.fn>

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

// 待发加工（generated）状态：展示「发加工」入口
const poGenerated = { ...poIssued, id: 'po-gen', status: 'generated', processor: undefined, expectedDeliveryDate: undefined }

/** 本地时区今天（yyyy-MM-dd），与组件 min/防御校验同口径（issue #3901） */
function todayLocal(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
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

  // issue #3889：onStatusChange 上报加工单状态（详情页据此守卫发货入口）；查询失败上报 null
  it('onStatusChange 携带加载到的加工单状态', async () => {
    const onStatusChange = vi.fn()
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing onStatusChange={onStatusChange} />)

    await screen.findByText('JG-20260912-0001')
    expect(onStatusChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'issued' }))
  })

  it('onStatusChange 查询失败时上报 null', async () => {
    const onStatusChange = vi.fn()
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing onStatusChange={onStatusChange} />)

    await screen.findByText('生成加工单')
    expect(onStatusChange).toHaveBeenCalledWith(null)
  })

  // ── issue #3901：发加工交期改日期控件且禁止过去日期 ──────────────

  it('发加工表单：交期为 date 控件且 min=今天（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    const dateInput = screen.getByPlaceholderText('交期 yyyy-MM-dd')
    expect(dateInput).toHaveAttribute('type', 'date')
    expect(dateInput).toHaveAttribute('min', todayLocal())
  })

  it('发加工：过去交期提交被拦截（setError、不发请求）（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    fireEvent.change(screen.getByPlaceholderText('交期 yyyy-MM-dd'), { target: { value: '2020-01-01' } })
    await userEvent.click(screen.getByText('确认发加工'))

    expect(await screen.findByText('交付日期不能早于今天')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()
  })

  it('发加工：今天/未来交期放行并提交，结果可见状态更新（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    mockedUpdate.mockResolvedValueOnce({
      data: { data: { ...poGenerated, status: 'issued', processor: '朝阳加工厂', expectedDeliveryDate: todayLocal() } },
    })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    fireEvent.change(screen.getByPlaceholderText('加工方（如：朝阳加工厂）'), { target: { value: '朝阳加工厂' } })
    fireEvent.change(screen.getByPlaceholderText('交期 yyyy-MM-dd'), { target: { value: todayLocal() } })
    await userEvent.click(screen.getByText('确认发加工'))

    await waitFor(() =>
      expect(mockedUpdate).toHaveBeenCalledWith('po-gen', {
        action: 'issue',
        processor: '朝阳加工厂',
        expectedDeliveryDate: todayLocal(),
        reason: undefined,
      }),
    )
    // 结果可见：提交成功后状态时间线/头部渲染「已发加工」，表单收起
    await waitFor(() => expect(screen.getAllByText('已发加工').length).toBeGreaterThan(0))
    expect(screen.queryByPlaceholderText('交期 yyyy-MM-dd')).not.toBeInTheDocument()
  })
})
