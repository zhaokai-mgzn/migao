// case_ids: UI-053
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'

// 组件在未注入收款码时会自取 `GET /api/admin/settings/payment-qrcodes` ——
// 本文件多数用例用注入的 `paymentQrcodes` 覆盖该路径；这里把 API 打桩成「无码」，
// 避免 jsdom 真发 XHR（噪音）。「无码 ⇒ 整块不出现」的判据仍由组件行为决定。
const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))

import QuotationDoc from '@/components/orders/QuotationDoc'
import ShipmentDoc from '@/components/orders/ShipmentDoc'
import type { Order, OrderItem } from '@/types'
/**
 * 报价单（可打印纸质文档，issue #4965）—— 照真实报价单 A4 制式（亿家纺织 CSO260918-03182）。
 *
 * 断言的是**纸面内容**：表头（单号/货运/客户·电话·地址/备注）→ 每个商品行一段
 * （`第N套/共M套` + `本套金额` + 一张 10 列表）→ 汇总（本单总金额/优惠金额/本单应收）
 * → 页脚（温馨提示 + 扫码支付码）。
 *
 * 用户裁定（2026-09-21，勿自行改）：
 * ① 我们真没有的字段（上期余额/预存抵扣/账户余额/交付日期/制单人）**先不印** —— 缺值不渲染；
 * ② **每个商品行自成一套**（与洗水码「商品行 = 部位」同粒度），不做樘窗分组；
 * ③ 参照物把加工费并进面料单价，而我们 `unitPrice` / `processingFee` 是**两笔真实金额**
 *    ⇒ 必须**分别列示**（否则商家对不上账）。
 *
 * 展示真值：`部位信息` / `部位备注` 一律走 `lib/craft-display.ts` 的 `craftSpecRows()`
 * （§4.9「一份 spec，三处渲染」）—— 本文件不另写一份推导，只断言「渲染了同一份真值」。
 */

function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
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
    processingFee: 0,
    width: 3.2,
    height: 2.6,
    processingInfo: {
      curtainType: '布帘',
      craft: '韩褶',
      cuttingMode: '定高买宽',
      openCount: 2,
      isShaped: true,
      formula: 'pleat',
      pleatCount: 36,
      perPanelPleats: 18,
      colorName: '米白',
      componentRole: '主布',
    },
    ...overrides,
  }
}

function buildOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: 'order-1',
    orderNo: 'CSO260918-03182',
    customerName: '张三',
    customerPhone: '13800138000',
    customerAddress: '浙江省杭州市余杭区某某路 1 号',
    totalAmount: 1500,
    actualAmount: 1400,
    discountAmount: 100,
    status: 'shipped',
    hasProcessing: false,
    createdAt: '2026-09-18T10:00:00+08:00',
    remark: '客户要求工作日送达',
    logisticsType: 'express',
    logisticsCompany: '顺丰速运',
    items: [buildItem()],
    ...overrides,
  }
}

const doc = () => document.querySelector('.quotation-print-area') as HTMLElement
/** 单据内文本（限定在单据子树内查询，避免与测试外壳/页面其它节点歧义） */
const docText = () => doc()?.textContent || ''

describe('QuotationDoc — 报价单纸面内容（issue #4965）', () => {
  describe('① 表头', () => {
    it('印标题「报价单」与单号', () => {
      render(<QuotationDoc order={buildOrder()} />)
      expect(docText()).toContain('报价单')
      expect(docText()).toContain('CSO260918-03182')
    })

    it('印客户 / 电话 / 地址', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const text = docText()
      expect(text).toContain('张三')
      expect(text).toContain('13800138000')
      expect(text).toContain('浙江省杭州市余杭区某某路 1 号')
    })

    it('印备注', () => {
      render(<QuotationDoc order={buildOrder()} />)
      expect(docText()).toContain('客户要求工作日送达')
    })

    it('货运：物流方式 + 物流公司（issue #4874 字段）—— 原样印，不套「未知 ⇒ 快递」兜底', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const text = docText()
      // 报价单是给客户的报价凭证：未知/自定义物流方式**不得**被印成「快递」（编值）
      expect(text).toContain('express')
      expect(text).toContain('顺丰速运')
    })

    it('货运缺值 ⇒ 不印该栏（不编值、不留空标签）', () => {
      render(
        <QuotationDoc
          order={buildOrder({ logisticsType: null, logisticsCompany: null, logistics: undefined })}
        />
      )
      const text = docText()
      expect(text).not.toContain('货运')
      expect(text).not.toContain('undefined')
      expect(text).not.toContain('null')
    })

    it('客户地址缺值 ⇒ 不印（不留「undefined」）', () => {
      render(<QuotationDoc order={buildOrder({ customerAddress: undefined })} />)
      expect(docText()).not.toContain('undefined')
      expect(docText()).not.toContain('null')
    })

    it('备注缺值 ⇒ 不印备注栏', () => {
      render(<QuotationDoc order={buildOrder({ remark: undefined })} />)
      expect(docText()).not.toContain('备注：')
    })
  })

  describe('② 正文：每个商品行自成一套（用户裁定 ②，不做樘窗分组）', () => {
    it('3 个商品行 ⇒ 3 套，段头为「第N套/共M套」', () => {
      render(
        <QuotationDoc
          order={buildOrder({
            items: [
              buildItem({ id: 'a' }),
              buildItem({ id: 'b' }),
              buildItem({ id: 'c' }),
            ],
          })}
        />
      )
      const text = docText()
      expect(text).toContain('第1套/共3套')
      expect(text).toContain('第2套/共3套')
      expect(text).toContain('第3套/共3套')
    })

    it('10 列表头齐全（部位/部位信息/部位备注/宽*高/组件/货号/用料/价格/小计/备注）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      for (const col of [
        '部位',
        '部位信息',
        '部位备注',
        '宽*高',
        '组件',
        '货号',
        '用料',
        '价格',
        '小计',
        '备注',
      ]) {
        expect(screen.getAllByText(col).length).toBeGreaterThanOrEqual(1)
      }
    })

    it('面料行：部位 = curtainType / 组件 = componentRole / 货号 = productCode + colorName / 用料 = quantity 米 / 价格 = unitPrice / 小计 = subtotal', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const text = docText()
      expect(text).toContain('布帘')
      expect(text).toContain('主布')
      expect(text).toContain('0012')
      expect(text).toContain('米白')
      expect(text).toContain('12.5')
      expect(text).toContain('100.00')
      expect(text).toContain('1,250.00')
    })

    it('组件缺 componentRole ⇒ 按主布印（缺省即主布）', () => {
      render(
        <QuotationDoc
          order={buildOrder({
            items: [
              buildItem({
                processingInfo: { curtainType: '布帘', colorName: '米白' },
              }),
            ],
          })}
        />
      )
      expect(docText()).toContain('主布')
    })

    it('宽*高 = width × height（米）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      expect(docText()).toContain('3.2×2.6')
    })

    it('宽或高缺值 ⇒ 不印该栏（不印 0×0、不印 undefined）', () => {
      render(<QuotationDoc order={buildOrder({ items: [buildItem({ width: undefined })] })} />)
      expect(docText()).not.toContain('undefined')
      expect(docText()).not.toContain('×2.6')
    })

    it('部位信息 / 部位备注 来自 craftSpecRows（§4.9 单一真值）：工艺/加工类型/打开方式/是否定型 + 总褶数/折数（每片）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const text = docText()
      // 部位信息列
      expect(text).toContain('韩褶')
      expect(text).toContain('定高买宽')
      expect(text).toContain('双开')
      expect(text).toContain('是')
      // 部位备注列（算料口径）
      expect(text).toContain('36')
      expect(text).toContain('18')
    })

    it('缺工艺键 ⇒ 部位信息/部位备注两列留空，不渲染 undefined/null/NaN', () => {
      render(
        <QuotationDoc
          order={buildOrder({
            items: [buildItem({ processingInfo: { curtainType: '布帘' } })],
          })}
        />
      )
      const text = docText()
      expect(text).not.toContain('undefined')
      expect(text).not.toContain('null')
      expect(text).not.toContain('NaN')
      expect(text).not.toContain('否')
    })

    it('加工费行：processingFee > 0 才出，组件 = 加工费 / 用料 = quantity 米 / 价格 = 小计 = processingFee', () => {
      render(
        <QuotationDoc
          order={buildOrder({ items: [buildItem({ processingFee: 250, subtotal: 1250 })] })}
        />
      )
      const text = docText()
      expect(text).toContain('加工费')
      expect(text).toContain('250.00')
    })

    it('processingFee = 0 / 缺省 ⇒ 不出现加工费行', () => {
      render(<QuotationDoc order={buildOrder({ items: [buildItem({ processingFee: 0 })] })} />)
      expect(docText()).not.toContain('加工费')
    })

    it('本套金额 = subtotal + processingFee（与 OrderItemList 行小计同一份口径，不各算一套）', () => {
      render(
        <QuotationDoc
          order={buildOrder({ items: [buildItem({ subtotal: 1250, processingFee: 250 })] })}
        />
      )
      expect(docText()).toContain('本套金额')
      expect(docText()).toContain('1,500.00')
    })

    it('无商品行 ⇒ 不崩、不印假套号', () => {
      render(<QuotationDoc order={buildOrder({ items: [] })} />)
      expect(docText()).not.toContain('第1套')
      expect(docText()).not.toContain('undefined')
    })
  })

  describe('③ 汇总：只读订单字段，不自己求和（用户裁定 ①）', () => {
    it('印本单总金额 / 优惠金额 / 本单应收（= totalAmount / discountAmount / actualAmount）', () => {
      render(
        <QuotationDoc
          order={buildOrder({ totalAmount: 1500, discountAmount: 100, actualAmount: 1400 })}
        />
      )
      const text = docText()
      expect(text).toContain('本单总金额')
      expect(text).toContain('1,500.00')
      expect(text).toContain('优惠金额')
      expect(text).toContain('100.00')
      expect(text).toContain('本单应收')
      expect(text).toContain('1,400.00')
    })

    it('汇总数字只读订单字段：与明细之和不一致时以订单字段为准（不自己求和）', () => {
      render(
        <QuotationDoc
          order={buildOrder({
            totalAmount: 9999,
            discountAmount: 0,
            actualAmount: 9999,
            items: [buildItem({ subtotal: 1250, processingFee: 0 })],
          })}
        />
      )
      expect(docText()).toContain('9,999.00')
    })

    it('上期余额 / 预存抵扣 / 账户余额 / 交付日期 / 制单人 一律不印（我们没有客户账本 —— 用户裁定 ①）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const text = docText()
      for (const absent of ['上期余额', '预存抵扣', '账户余额', '交付日期', '制单人']) {
        expect(text).not.toContain(absent)
      }
    })

    it('discountAmount 缺值 ⇒ 不印优惠金额（不印 ¥0.00 假优惠）', () => {
      render(<QuotationDoc order={buildOrder({ discountAmount: undefined })} />)
      expect(docText()).not.toContain('优惠金额')
    })
  })

  describe('④ 页脚：温馨提示 + 扫码支付码', () => {
    it('印温馨提示常量（照参照物口径）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      expect(docText()).toContain(
        '收到货后先验货，若有质量问题务必在七天内联系客服，如已开剪不予退换！'
      )
    })

    it('有收款码 ⇒ 印图片 + 收款方', () => {
      render(
        <QuotationDoc
          order={buildOrder()}
          paymentQrcodes={{
            wechat: { imageUrl: 'https://oss.example.com/wx.png', payeeName: '亿家纺织' },
          }}
        />
      )
      const img = doc()?.querySelector('img') as HTMLImageElement
      expect(img).not.toBeNull()
      expect(img.getAttribute('src')).toContain('wx.png')
      expect(docText()).toContain('亿家纺织')
    })

    it('没有收款码 ⇒ 整块不出现、不画假码（不出现 img 占位）', () => {
      render(<QuotationDoc order={buildOrder()} paymentQrcodes={{}} />)
      expect(doc()?.querySelector('img')).toBeNull()
      expect(docText()).not.toContain('扫码支付')
    })

    it('收款码缺 imageUrl ⇒ 不画假码（只有 payeeName 也不出图）', () => {
      render(
        <QuotationDoc
          order={buildOrder()}
          paymentQrcodes={{ wechat: { payeeName: '亿家纺织' } }}
        />
      )
      expect(doc()?.querySelector('img')).toBeNull()
    })

    it('未注入收款码 ⇒ 不挂载即拉（常驻组件不该在每次打开订单详情页都发请求）', () => {
      mockGetPaymentQrcodes.mockClear()
      render(<QuotationDoc order={buildOrder()} />)
      expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
    })

    it('打印时（beforeprint）自取收款码并印出；拉取失败 ⇒ 仍不画假码', async () => {
      mockGetPaymentQrcodes.mockClear()
      mockGetPaymentQrcodes.mockResolvedValue({
        data: { data: { wechat: { imageUrl: 'https://oss.example.com/wx.png', payeeName: '亿家纺织' } } },
      })
      render(<QuotationDoc order={buildOrder()} />)
      await act(async () => {
        window.dispatchEvent(new Event('beforeprint'))
      })
      expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
      expect(doc()?.querySelector('img')?.getAttribute('src')).toContain('wx.png')

      // 失败路径：抛错 ⇒ 按「无码」处理（整块不出现），不画假码
      mockGetPaymentQrcodes.mockReset()
      mockGetPaymentQrcodes.mockRejectedValue(new Error('403'))
      cleanup()
      render(<QuotationDoc order={buildOrder()} />)
      await act(async () => {
        window.dispatchEvent(new Event('beforeprint'))
      })
      expect(doc()?.querySelector('img')).toBeNull()
    })
  })

  describe('打印隔离（ShipmentDoc 范式 6 条约束，勿随手改）', () => {
    it('portal 到 document.body 的直接子级 + 容器自身 class + 每页只挂一份 + 屏幕态 display:none', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const el = doc()
      expect(el).not.toBeNull()
      expect(el.parentElement).toBe(document.body)
      expect(document.querySelectorAll('.quotation-print-area')).toHaveLength(1)
      expect(getComputedStyle(el).display).toBe('none')
    })

    it('内置打印契约：A4 + @media print + body 级隔离选择器 + visibility 防御', () => {
      render(<QuotationDoc order={buildOrder()} />)
      const style = doc()?.querySelector('style')?.textContent || ''
      expect(style).toContain('@page')
      expect(style).toContain('size: A4')
      expect(style).toContain('@media print')
      expect(style).toMatch(/\.quotation-print-area\s*\{\s*display:\s*none/)
      expect(style).toMatch(
        /body > \*:not\(\.quotation-print-area\)\s*\{\s*display:\s*none\s*!important/
      )
      // visibility 防御（订单详情页 ProcessingOrderBlock 残留的 body * { visibility: hidden }）
      // —— 形态见下一条：必须限定本次打印目标
      expect(style).toMatch(/\.quotation-print-area\[data-print-target='quotation'\]/)
      expect(style).toMatch(/visibility:\s*visible/)
    })

    // 🔴 回归守卫（issue #4965 实测：CI `Demo path specs` 因这条判据缺失而红）：
    // 订单详情页**同时挂着**发货单（`ShipmentDoc`）—— 两个单据是 body 的兄弟节点，
    // 各自的 `visibility: visible` 打印防御**同特异性** ⇒ 后渲染者胜，报价单会把发货单
    // 重新藏掉（纸面空白）。故防御必须限定「本次打印目标」。
    it('visibility 防御限定本次打印目标（否则会把同页发货单藏掉）', () => {
      render(<QuotationDoc order={buildOrder()} printTarget="quotation" />)
      const el = doc()
      expect(el.getAttribute('data-print-target')).toBe('quotation')
      const styleEl = el.querySelector('style') as HTMLStyleElement
      const css = styleEl.textContent || ''
      expect(css).toMatch(
        /\.quotation-print-area\[data-print-target='quotation'\],\s*\.quotation-print-area\[data-print-target='quotation'\] \*/
      )
      // 不加限定的旧形态必须**不存在**于**生效规则**里（它正是把发货单藏掉的那条）——
      // 只看 CSSOM 规则文本，不看原文（注释里会引到旧形态做说明，字符串匹配会误判）
      const printBlock = Array.from(styleEl.sheet!.cssRules).find(
        (r): r is CSSMediaRule => (r as CSSMediaRule).media?.mediaText?.includes('print') === true
      )
      expect(printBlock).toBeDefined()
      const effective = Array.from(printBlock!.cssRules).map((r) => r.cssText).join('\n')
      expect(effective).toMatch(/\[data-print-target='quotation'\]/)
      expect(effective).not.toMatch(
        /(^|[\s,])\.quotation-print-area,\s*\.quotation-print-area \*\s*\{[^}]*visibility/
      )
    })

    it('未置位打印目标 ⇒ 不加 data-print-target（点「打印发货单」时报价单不参与显形）', () => {
      render(<QuotationDoc order={buildOrder()} />)
      expect(doc()?.getAttribute('data-print-target')).toBeNull()
    })

    // 🔴 端到端回归复现（issue #4965 实测：CI `Demo path specs` 红在
    // `expect('.shipment-print-area').toBeVisible()`）：订单详情页**同时挂着**两份单据，
    // 且页面上有 `ProcessingOrderBlock` 的遗留隔离 `@media print { body * { visibility: hidden } }`
    // —— 两份单据各自都写 `visibility: visible` 防御，**同特异性、后渲染者胜** ⇒
    // 后挂的报价单会把先挂的发货单重新藏掉（补打纸面空白）。
    // 这里按真实 DOM 顺序把三块 print 规则并到样式表末尾（jsdom 不解析媒体查询，故为等价仿真，
    // 同 ShipmentDoc.test.tsx 的 ② 手法），断言「点谁只显谁」。
    it('两单共存（含遗留 body * 隔离）：点谁只显谁，不把对方藏掉', () => {
      // 遗留隔离（订单详情页 ProcessingOrderBlock 的真实形态）—— 防抖动的靶子
      const legacy = document.createElement('style')
      legacy.textContent = '@media print { body * { visibility: hidden; } }'
      document.head.appendChild(legacy)

      const inlinePrintBlocks = () => {
        const els = [
          legacy,
          ...Array.from(
            document.querySelectorAll<HTMLStyleElement>(
              '.shipment-print-area style, .quotation-print-area style'
            )
          ),
        ]
        // 按 DOM 顺序（legacy 在最前、两份单据按挂载顺序）把 print 块内规则并入样式表末尾
        for (const el of els) {
          const block = Array.from(el.sheet!.cssRules).find(
            (r): r is CSSMediaRule => (r as CSSMediaRule).media?.mediaText?.includes('print') === true
          )
          if (block) {
            el.textContent = `${el.textContent}\n${Array.from(block.cssRules)
              .map((r) => r.cssText)
              .join('\n')}`
          }
        }
      }
      const clear = () => {
        for (const el of Array.from(document.querySelectorAll('style'))) el.textContent = ''
      }

      // ── 场景 A：点「打印报价单」──
      let view = render(
        <>
          <ShipmentDoc order={buildOrder()} printTarget="quotation" />
          <QuotationDoc order={buildOrder()} printTarget="quotation" />
        </>
      )
      inlinePrintBlocks()
      const shipment = document.querySelector('.shipment-print-area') as HTMLElement
      const quotation = document.querySelector('.quotation-print-area') as HTMLElement
      expect(getComputedStyle(quotation).visibility).toBe('visible')
      // 发货单**不得**被报价单的防御带成 visible（这正是 CI 那条红的形态）
      expect(getComputedStyle(shipment).visibility).toBe('hidden')
      view.unmount()
      clear()

      // ── 场景 B：点「打印发货单」（反向：发货单显形、报价单保持 hidden）──
      // 遗留隔离复位（`clear()` 把它清空了；它必须与两份单据一起参与本次级联）
      legacy.textContent = '@media print { body * { visibility: hidden; } }'
      view = render(
        <>
          <ShipmentDoc order={buildOrder()} printTarget="shipment" />
          <QuotationDoc order={buildOrder()} printTarget="shipment" />
        </>
      )
      inlinePrintBlocks()
      const shipment2 = document.querySelector('.shipment-print-area') as HTMLElement
      const quotation2 = document.querySelector('.quotation-print-area') as HTMLElement
      expect(getComputedStyle(shipment2).visibility).toBe('visible')
      expect(getComputedStyle(quotation2).visibility).toBe('hidden')

      view.unmount()
      clear()
      legacy.remove()
    })

    it('纸面绝不出现 undefined / null / NaN（整单缺值扫描）', () => {
      render(
        <QuotationDoc
          order={buildOrder({
            customerAddress: undefined,
            remark: undefined,
            logisticsType: null,
            logisticsCompany: null,
            discountAmount: undefined,
            items: [
              buildItem({
                productCode: undefined,
                width: undefined,
                height: undefined,
                processingInfo: { curtainType: '布帘' },
              }),
            ],
          })}
        />
      )
      const text = docText()
      expect(text).not.toContain('undefined')
      expect(text).not.toContain('null')
      expect(text).not.toContain('NaN')
    })
  })

  // 反向护栏：删掉上面的 portal/隔离断言后，本判据必须仍能区分「单据真的挂上了」
  it('单据确实被渲染（护栏：上面的断言不是对着空 DOM 恒真）', () => {
    render(<QuotationDoc order={buildOrder()} />)
    expect(doc()).not.toBeNull()
    cleanup()
    expect(document.querySelector('.quotation-print-area')).toBeNull()
  })
})
