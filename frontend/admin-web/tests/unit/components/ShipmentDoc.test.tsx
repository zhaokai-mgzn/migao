// case_ids: UI-040
// @vitest-environment jsdom

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ShipmentDoc from '@/components/orders/ShipmentDoc'
import type { Order } from '@/types'

/**
 * 发货单（可打印纸质文档，issue #3768 / UI-040）
 *
 * 断言的是**纸面内容**：收货信息、商品明细、合计、经手人、运单号（有则印、无则留空）。
 * 屏幕隐藏/打印可见由组件内置的 @media print 控制，jsdom 不解析媒体查询，
 * 故此处只锁定「文档结构与内容 + 打印 CSS 契约存在」（真实打印渲染见 §15.2 浏览器走查）。
 */

function buildOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: 'order-1',
    orderNo: 'ORD20260915001',
    customerName: '张三',
    customerPhone: '13800138000',
    customerAddress: '浙江省杭州市余杭区某某路 1 号',
    totalAmount: 1500,
    actualAmount: 1500,
    status: 'shipped',
    hasProcessing: false,
    createdAt: '2026-09-15T10:00:00+08:00',
    remark: '客户要求工作日送达',
    items: [
      {
        id: 'item-1',
        productId: 'p-1',
        productName: '布艺遮光帘A',
        productCode: '0012',
        color: '米白',
        specification: '门幅2.8米',
        quantity: 12.5,
        unitPrice: 100,
        amount: 1250,
        subtotal: 1250,
      },
      {
        id: 'item-2',
        productId: 'p-2',
        productName: '纱帘B',
        productCode: '0020',
        color: '象牙白',
        specification: '门幅3.0米',
        quantity: 5,
        unitPrice: 50,
        amount: 250,
        subtotal: 250,
      },
    ],
    ...overrides,
  }
}

describe('ShipmentDoc — 发货单纸面内容', () => {
  it('渲染单据头：标题 + 订单号 + 下单时间', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    expect(screen.getByText('发货单')).toBeInTheDocument()
    expect(screen.getAllByText('ORD20260915001').length).toBeGreaterThan(0)
    expect(screen.getByText('下单时间')).toBeInTheDocument()
  })

  it('渲染收货信息（收货人/电话/地址）', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    expect(screen.getByText('收货人')).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.getByText('13800138000')).toBeInTheDocument()
    expect(screen.getByText(/余杭区某某路 1 号/)).toBeInTheDocument()
  })

  it('渲染商品明细每一行（品名/货号/颜色/规格/数量/金额）', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    expect(screen.getByText('布艺遮光帘A')).toBeInTheDocument()
    expect(screen.getByText('0012')).toBeInTheDocument()
    expect(screen.getByText('米白')).toBeInTheDocument()
    expect(screen.getByText('门幅2.8米')).toBeInTheDocument()
    expect(screen.getByText('纱帘B')).toBeInTheDocument()
    expect(screen.getByText('0020')).toBeInTheDocument()
  })

  it('合计行给出总数量与总金额（拣货/打包据此点件）', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    // 12.5 + 5 = 17.5；1250 + 250 = 1500
    expect(screen.getByText('合计')).toBeInTheDocument()
    expect(screen.getByText('17.5')).toBeInTheDocument()
    expect(screen.getByText('1,500.00')).toBeInTheDocument()
  })

  it('含加工项时输出加工项区块与加工费合计', () => {
    const order = buildOrder({
      hasProcessing: true,
      processingItems: [
        { id: 'pr-1', name: '打孔', unitPrice: 3, quantity: 12.5, amount: 37.5 },
      ],
    })
    render(<ShipmentDoc order={order} />)

    // 「加工项」既是区块标题也是表头 → 命中多处是预期
    expect(screen.getAllByText('加工项').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('打孔')).toBeInTheDocument()
    expect(screen.getByText('加工费合计')).toBeInTheDocument()
    // 37.50 同时是明细行金额与加工费合计（只有一项）→ 命中多处是预期
    expect(screen.getAllByText('37.50').length).toBeGreaterThanOrEqual(1)
  })

  it('备注为空时不编造内容，表头仍在（纸面留白供手写）', () => {
    render(<ShipmentDoc order={buildOrder({ remark: undefined })} />)

    expect(screen.getByText('备注')).toBeInTheDocument()
  })

  it('发货页传入的当前输入发货人优先印在纸面（尚未保存也可见）', () => {
    render(<ShipmentDoc order={buildOrder()} shipperName="王五" />)

    expect(screen.getByText('发货人')).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
  })

  it('补打时取已落库的发货人 + 承运商 + 运单号', () => {
    render(
      <ShipmentDoc
        order={buildOrder()}
        logistics={{ logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '李四' }}
      />
    )

    expect(screen.getByText('李四')).toBeInTheDocument()
    expect(screen.getByText('顺丰速运')).toBeInTheDocument()
    expect(screen.getByText('SF20260915001')).toBeInTheDocument()
  })

  it('存量订单无发货人/无运单号：不编造（纸面留空供手写），且不抛错', () => {
    const { container } = render(<ShipmentDoc order={buildOrder()} logistics={null} />)

    // 物流栏位存在但没有值
    expect(screen.getByText('物流公司')).toBeInTheDocument()
    expect(screen.getByText('运单号')).toBeInTheDocument()
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
    expect(container.textContent).not.toContain('internal-service')
  })

  it('内置打印契约：A4 页面尺寸 + print-area 隔离选择器（防"打印出一整页后台外壳"）', () => {
    const { container } = render(<ShipmentDoc order={buildOrder()} />)

    const style = container.querySelector('style')?.textContent || ''
    expect(style).toContain('shipment-print-area')
    expect(style).toContain('@page')
    expect(style).toContain('size: A4')
    expect(style).toContain('@media print')
    // 屏幕上隐藏（页面已有屏幕布局，避免重复呈现）
    expect(style).toMatch(/\.shipment-print-area\s*\{\s*display:\s*none/)
    // 打印时只显示本单据
    expect(style).toContain('body * { visibility: hidden; }')
  })
})
