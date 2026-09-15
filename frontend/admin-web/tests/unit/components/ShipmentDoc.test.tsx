// case_ids: UI-040, UI-019
// @vitest-environment jsdom

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen, cleanup } from '@testing-library/react'
import ShipmentDoc from '@/components/orders/ShipmentDoc'
import type { Order } from '@/types'

/**
 * 发货单（可打印纸质文档，issue #3768 / UI-040）
 *
 * 断言的是**纸面内容**：收货信息、商品明细、合计、经手人、运单号（有则印、无则留空）。
 * 发货人栏口径见下方「存量已发货订单的发货人栏口径」（issue #3818 裁定：显示「-」）。
 *
 * 打印隔离（`@media print` 只印单据、不印后台外壳）：单据经 `createPortal` 渲染到
 * document.body（body 直接子级），打印时用
 * `body > *:not(.shipment-print-area) { display: none !important; }` 把整页外壳藏掉 ——
 * **display:none 不占版面高度**，不会把分页撑出空白第二页
 * （旧方案 `visibility:hidden` 仍占高度 → 底层页面高于一页 A4 时第 2 页空白，issue #3896）。
 * jsdom 不解析媒体查询，因此分两层守 —— ① 本文件用 CSSOM + 级联**仿真**打印媒体，
 * 断言单据显形/外壳被隐藏（把 print 块的规则并到样式表末尾后 getComputedStyle 真算）；
 * ② 真实 `emulateMedia({media:'print'})` 走查见 tests/e2e/specs/orders/shipment-doc.spec.ts
 * （⚠️ 该 e2e 从未被 CI 执行，issue #3817）。
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

  it('发货前无物流（无发货人/无运单号）：不编造，运单号/物流公司留空供手写，且不抛错', () => {
    render(<ShipmentDoc order={buildOrder()} logistics={null} />)

    // 物流栏位存在但没有值（单据已 portal 到 body，查 body 全文确认无编造文本）
    expect(screen.getByText('物流公司')).toBeInTheDocument()
    expect(screen.getByText('运单号')).toBeInTheDocument()
    expect(screen.queryByText('undefined')).not.toBeInTheDocument()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('internal-service')
  })

  // ===== 存量已发货订单的发货人栏口径（issue #3818 裁定）=====
  // 裁定：存量（shipper_name 为 NULL/空）时纸面发货人栏显示「-」，与 #3768 判据一致；
  // 不得留白、不得显示 undefined/null。留空仅供 **运单号/物流公司**（发货前手写用）。
  // ⚠️ 断言按「标签单元格的相邻单元格」取值，与被测实现的写法解耦。
  const shipperCell = () => screen.getByText('发货人').nextElementSibling as HTMLElement

  it('存量已发货订单（物流存在但 shipperName 为空）：发货人栏显示「-」，不留白', () => {
    render(
      <ShipmentDoc
        order={buildOrder()}
        logistics={{ logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '' }}
      />
    )

    expect(shipperCell().textContent).toBe('-')
  })

  it('存量已发货订单（完全没有物流记录）：发货人栏同样显示「-」', () => {
    render(<ShipmentDoc order={buildOrder()} logistics={null} />)

    expect(shipperCell().textContent).toBe('-')
  })

  it('反向断言：发货人有值时印真实姓名，绝不退化成「-」', () => {
    render(
      <ShipmentDoc
        order={buildOrder()}
        logistics={{ logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '李四' }}
      />
    )
    expect(shipperCell().textContent).toBe('李四')
    expect(shipperCell().textContent).not.toBe('-')

    cleanup()
    // 发货页草稿值（尚未保存）同样不得被「-」吃掉
    render(<ShipmentDoc order={buildOrder()} shipperName="王五" />)
    expect(shipperCell().textContent).toBe('王五')
  })

  // ===== portal 渲染载体（issue #3896：打印隔离的物理前提）=====
  it('通过 portal 渲染到 document.body（打印时外壳整体隐藏的前提；屏幕态 display:none 不占版面）', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    const doc = document.querySelector('.shipment-print-area') as HTMLElement
    expect(doc).not.toBeNull()
    // portal 到 body：单据与页面外壳（body 下其他子树）同级，
    // 打印时才能用 `body > *:not(.shipment-print-area)` 整体藏掉外壳
    expect(doc.parentElement).toBe(document.body)
    // 每页只挂一份（.shipment-print-area 是全局选择器，挂两份会打印两套单据）
    expect(document.querySelectorAll('.shipment-print-area')).toHaveLength(1)
    // 屏幕态 display:none（portal 后仍是隐藏的，页面屏幕布局零改动）
    expect(getComputedStyle(doc).display).toBe('none')
  })

  it('内置打印契约：A4 页面尺寸 + body 级隔离选择器（防"打印出一整页后台外壳"）', () => {
    render(<ShipmentDoc order={buildOrder()} />)

    const style = document.querySelector('.shipment-print-area style')?.textContent || ''
    expect(style).toContain('shipment-print-area')
    expect(style).toContain('@page')
    expect(style).toContain('size: A4')
    expect(style).toContain('@media print')
    // 屏幕上隐藏（页面已有屏幕布局，避免重复呈现）
    expect(style).toMatch(/\.shipment-print-area\s*\{\s*display:\s*none/)
    // 打印时只显示本单据：隐藏 body 下所有非单据直系子级。
    // display:none 不占版面高度 —— 旧 `visibility:hidden` 会按隐藏内容高度分页，
    // 底层页面高于一页 A4 时第 2 页空白（issue #3896）。
    expect(style).toMatch(/body > \*:not\(\.shipment-print-area\)\s*\{\s*display:\s*none\s*!important/)
  })

  // ===== 打印隔离：从「CSS 字符串存在」升级为「级联算出来的可见性」（issue #3817 收尾）=====
  // 旧断言只查字符串（把整块 @media print 删掉也只红那一条，且分不清
  // 「隔离被删」与「隔离写了但选不中节点」）。这里改用真实 CSSOM + jsdom 级联：
  //   ① 结构：隔离规则确实写在 @media print 块内；
  //   ② 仿真打印媒体：把 print 块内的规则按原顺序并到同一样式表末尾，让
  //      getComputedStyle 真算一遍「打印时会是什么样」—— 单据显形、非单据兄弟节点
  //      （页面外壳 = body 直接子级）被隐藏。
  // jsdom 不解析媒体查询本身（屏幕态 = 非打印态），故 ② 是等价仿真；真实
  // emulateMedia({media:'print'}) 的浏览器走查见 tests/e2e/specs/orders/shipment-doc.spec.ts
  // （⚠️ 该 spec 不在任何 PR 门禁清单里，亦不在 nightly（schedule 已停）——issue #3817）。
  function mountDocWithShell() {
    // 外壳包在 RTL 的 container div 里 —— 该 div 是 body 的直接子级，
    // 对应真实页面里整页应用所在的 body 直系子树（打印时被整体 display:none）
    const { container } = render(
      <div>
        <aside>侧边栏</aside>
        <button type="button">确认发货</button>
        <ShipmentDoc order={buildOrder()} />
      </div>
    )
    return {
      styleEl: document.querySelector('.shipment-print-area style') as HTMLStyleElement,
      doc: document.querySelector('.shipment-print-area') as HTMLElement,
      shell: container as HTMLElement,
      confirmBtn: screen.getByRole('button', { name: '确认发货' }),
    }
  }

  it('打印隔离（计算样式）：打印时单据显形、页面外壳被隐藏；删掉隔离规则即红', () => {
    const { styleEl, doc, shell, confirmBtn } = mountDocWithShell()

    // 屏幕上：单据不参与屏幕布局（页面已有自己的布局，避免重复呈现）
    expect(getComputedStyle(doc).display).toBe('none')
    expect(getComputedStyle(shell).display).not.toBe('none')
    expect(getComputedStyle(confirmBtn).display).not.toBe('none')

    // ① 隔离规则必须写在 @media print 里（否则屏幕上就把整个后台外壳藏掉了）——删掉整块即红
    const sheet = styleEl.sheet
    expect(sheet).not.toBeNull()
    const printRule = Array.from(sheet!.cssRules).find(
      (r): r is CSSMediaRule => (r as CSSMediaRule).media?.mediaText?.includes('print') === true
    )
    expect(printRule).toBeDefined()

    // ② 仿真打印媒体（jsdom 不解析媒体查询）：把 print 块内规则按原顺序并入样式表末尾
    const inner = Array.from(printRule!.cssRules).map((r) => r.cssText).join('\n')
    styleEl.textContent = `${styleEl.textContent}\n${inner}`

    // 页面外壳（body 直接子级）被隐藏
    // ⇒ 删掉 `body > *:not(.shipment-print-area) { display: none !important; }` 即红（且红在具体节点上）
    expect(getComputedStyle(shell).display).toBe('none')
    // display:none 让整棵外壳子树在打印时都不再呈现（渲染层面整体隐藏；
    // 不同于 visibility，display 不继承到子节点 computed 值，故只断外壳本身）

    // 单据自身显形（display:block 覆盖屏幕态 display:none，同特异性、后声明者胜）
    // ⇒ 删掉 print 块的 `.shipment-print-area { display: block; }` 即红
    expect(getComputedStyle(doc).visibility).toBe('visible')
    expect(getComputedStyle(doc).display).toBe('block')
    expect(getComputedStyle(screen.getByText('发货单')).visibility).toBe('visible')

    // 纸面从页首自然排版（position: static；旧方案 absolute 锚定左上角，
    // 底层页面高度仍会撑出第二页空白 #3896）⇒ 若回归 position:absolute 即红
    expect(getComputedStyle(doc).position).toBe('static')
  })

  it('A4 纸面尺寸写在 @page 块里（jsdom 里以 CSSOM 断言，不靠字符串匹配）', () => {
    const { styleEl } = mountDocWithShell()
    const pageRule = Array.from(styleEl.sheet!.cssRules).find((r) => r.cssText.includes('@page'))

    expect(pageRule).toBeDefined()
    expect(pageRule!.cssText).toContain('size: A4')
  })

  // ===== 单据挂在页面级，不得放进 Modal（issue #3818 收尾）=====
  // 为什么断言源码结构而不是 DOM 祖先：Modal 关闭时**不渲染任何节点**，
  // 「查单据祖先里有没有 [role=dialog]」在默认状态下恒真 = 空断言（改了也绿）。
  // 这里直接断言两个调用方（发货页 / 订单详情页）的 JSX：单据不在任何
  // <Modal>…</Modal> 内，且每页只挂一份 ⇒ 把单据塞进弹窗、或挂两份，必红。
  const CALL_SITES = [
    'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
    'src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
  ]

  it.each(CALL_SITES)('%s：发货单挂在页面级（不在 <Modal> 内）且只挂一份', (rel) => {
    const src = readFileSync(join(process.cwd(), rel), 'utf-8')

    // 每页只挂一份（.shipment-print-area 是全局选择器，挂两份会打印两套单据）
    expect(src.match(/<ShipmentDoc/g) || []).toHaveLength(1)

    // 不在 <Modal>…</Modal> 之间（Modal 面板 max-h-full + 内部 overflow-y-auto，
    // 打印只会打出可视一屏、多页明细被裁）
    const at = src.indexOf('<ShipmentDoc')
    const lastOpen = src.lastIndexOf('<Modal', at)
    const lastClose = src.lastIndexOf('</Modal>', at)
    expect(lastOpen !== -1 && lastOpen > lastClose).toBe(false)
  })
})
