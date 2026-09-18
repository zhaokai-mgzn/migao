// @vitest-environment jsdom
// case_ids: PG-001, PG-005, PG-019, UI-019, UI-030

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

/**
 * 快照携带工艺规格的加工单（issue #4355 / 设计文档 §4.9 ③）。
 * 键名与 `processing_info` / `items_snapshot` 同口径（camelCase + 算料 snake_case，§4.5）。
 */
const poWithCraft = {
  ...poIssued,
  items: [
    {
      ...poIssued.items[0],
      curtainType: '布帘',
      craft: '韩褶',
      cuttingMode: '定高买宽',
      openCount: 2,
      isShaped: true,
      style: '拼色',
      specialOptions: ['加铅线', '双褶'],
      pleat_count: 52,
      per_panel_pleats: 26,
      pleatSpacing: 0.1,
      panels: 4,
      fullness: 2,
      fullness_actual: 1.86,
      fabric_meters: 13.3,
      processingMeters: 13.3,
      hasPattern: true,
      patternRepeat: 0.32,
    },
  ],
}

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

  // ── issue #4355：加工单展示工艺规格（设计文档 §4.9 ③）─────────────────

  it('快照明细展示工艺规格：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('工艺规格')).toBeInTheDocument()
    expect(within(spec).getByText('布帘')).toBeInTheDocument()
    expect(within(spec).getByText('韩褶')).toBeInTheDocument()
    expect(within(spec).getByText('定高买宽')).toBeInTheDocument()
    expect(within(spec).getByText('双开')).toBeInTheDocument()
    expect(within(spec).getByText('拼色')).toBeInTheDocument()
    expect(within(spec).getByText('加铅线、双褶')).toBeInTheDocument()
    expect(within(spec).getByText('是否定型').parentElement?.textContent).toContain('是')
  })

  it('快照明细展示算料口径：总褶数/折数（每片）/褶距/幅数/褶倍/米数/是否对花/花距（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('52')).toBeInTheDocument()
    expect(within(spec).getByText('26')).toBeInTheDocument()
    expect(within(spec).getByText('0.1米')).toBeInTheDocument()
    expect(within(spec).getByText('4')).toBeInTheDocument()
    expect(within(spec).getByText('2 倍')).toBeInTheDocument()
    expect(within(spec).getByText('1.86 倍')).toBeInTheDocument()
    // 面料米数 / 加工费米数 = §4.9 要求的**两个字段**（§6.1 口径拆两值）⇒ 同值时出现两次
    expect(within(spec).getAllByText('13.3米')).toHaveLength(2)
    expect(within(spec).getByText('是否对花')).toBeInTheDocument()
    expect(within(spec).getByText('0.32米')).toBeInTheDocument()
  })

  it('「复制全部」文本含工艺规格（发给加工方/贴 Excel 时不丢工艺，PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('工艺：韩褶')
    expect(text).toContain('加工类型：定高买宽')
    expect(text).toContain('打开方式：双开')
    expect(text).toContain('总褶数：52')
    expect(text).toContain('是否对花：是')
    expect(text).not.toMatch(/undefined|null|NaN/)
  })

  it('缺值不渲染：存量单无工艺键 ⇒ 无规格块，复制文本也不出现 undefined/null/NaN（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(screen.queryByTestId('po-item-craft-spec')).toBeNull()
    const text = writeText.mock.calls[0][0] as string
    expect(text).not.toMatch(/undefined|null|NaN/)
    expect(text).not.toContain('工艺：')
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
