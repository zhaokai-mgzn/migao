/**
 * OrderTable 组件测试
 * 覆盖：基本渲染、采购商品列、采购明细列、加工项计费、空状态、加载状态
 */
// case_ids: UI-002, UI-020, UI-019, UI-030, OR-072
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import OrderTable from '@/components/orders/OrderTable'
import type { Order, OrderStatus } from '@/types'

const mockOrder = {
  id: 'order-001',
  orderNo: 'ORD-001',
  status: 'pending_shipment' as const,
  totalAmount: 299,
  actualAmount: 299,
  customerName: '测试客户',
  customerPhone: '13800000000',
  hasProcessing: false,
  createdAt: '2026-06-15T10:00:00Z',
  updatedAt: '2026-06-15T10:00:00Z',
  items: [
    {
      id: 'item-1',
      productId: 'prod-1',
      productName: '窗帘',
      productCode: 'CL-001',
      unitPrice: 99,
      quantity: 3,
      subtotal: 297,
      amount: 297,
    },
  ],
}

describe('OrderTable', () => {
  const defaultProps = {
    orders: [mockOrder],
    loading: false,
    selectedIds: [] as string[],
    onSelectChange: vi.fn(),
    onView: vi.fn(),
    onRemark: vi.fn(),
    onClose: vi.fn(),
    onShip: vi.fn(),
  }

  it('应渲染订单列表表头', () => {
    render(<OrderTable {...defaultProps} />)
    expect(screen.getByText('订单ID')).toBeTruthy()
    expect(screen.getByText('采购商品')).toBeTruthy()
    expect(screen.getByText('采购明细')).toBeTruthy()
    expect(screen.getByText('状态')).toBeTruthy()
  })

  it('应显示订单ID', () => {
    render(<OrderTable {...defaultProps} />)
    expect(screen.getByText('ORD-001')).toBeTruthy()
  })

  it('应显示采购商品名称和货号', () => {
    render(<OrderTable {...defaultProps} />)
    const names = screen.getAllByText('窗帘')
    expect(names.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/货号/)).toBeTruthy()
  })

  // issue #4908（真库实证 20260921973550001 三个商品）：改前「采购商品」列只渲染 `items[0]`
  // ⇒ 多商品订单的其余商品在列表上完全看不见（同行的「采购明细」列却是 3 行）
  it('多商品订单：采购商品列逐条渲染全部商品（名称 + 货号），不是只渲染第一条', () => {
    const multiItemOrder = {
      ...mockOrder,
      items: [
        { ...mockOrder.items[0], id: 'item-1', productName: '2699系列雪尼尔窗帘面料', productCode: '2699' },
        { ...mockOrder.items[0], id: 'item-2', productName: '金刚棉', productCode: '金刚棉-02' },
        { ...mockOrder.items[0], id: 'item-3', productName: '9231 遮光窗帘', productCode: '9231-05' },
      ],
    }
    render(<OrderTable {...defaultProps} orders={[multiItemOrder]} />)

    // 「名称 + 货号」是采购商品列的形态 ⇒ 先用 `货号 X` 定位该列，再断言三条都落在**同一个单元格**里
    // （改前这里只有 1 条 —— 这正是红证）
    const skuLines = screen.getAllByText(/^货号 /)
    expect(skuLines).toHaveLength(3)
    const goodsCell = skuLines[0].closest('td')!
    expect(within(goodsCell).getByText('2699系列雪尼尔窗帘面料')).toBeTruthy()
    expect(within(goodsCell).getByText('金刚棉')).toBeTruthy()
    expect(within(goodsCell).getByText('9231 遮光窗帘')).toBeTruthy()
    expect(within(goodsCell).getByText('货号 9231-05')).toBeTruthy()
  })

  // issue #3889：producing（生产中）不再以「待发货」展示，避免用户误以为可直接发货
  it('producing 订单状态徽标展示「生产中」而非「待发货」', () => {
    render(
      <OrderTable
        {...defaultProps}
        orders={[{ ...mockOrder, status: 'producing' as unknown as OrderStatus }]}
      />
    )
    expect(screen.getByText('生产中')).toBeTruthy()
    expect(screen.queryByText('待发货')).toBeNull()
  })

  it('应显示采购明细（名称/单价×数量=金额）', () => {
    render(<OrderTable {...defaultProps} />)
    // 采购明细包含商品名称、单价、数量 — 使用 getAllByText 因为名称出现在两列
    const names = screen.getAllByText(/窗帘/)
    expect(names.length).toBeGreaterThanOrEqual(1)
  })

  it('采购明细分隔符应为 : 而非 /', () => {
    render(<OrderTable {...defaultProps} />)
    // 采购明细列在 min-w-[280px] 的 td 中，取该列文本验证分隔符
    const detailCells = document.querySelectorAll('td.min-w-\\[280px\\]')
    expect(detailCells.length).toBeGreaterThan(0)
    const cellText = detailCells[0].textContent || ''
    // 产品名后应紧跟 ' : 数字' 模式（如 窗帘 : 99元）
    expect(cellText).toMatch(/窗帘\s*:\s*\d/)
    // 不应出现 ' / 数字' 模式（在采购明细列上下文中）
    expect(cellText).not.toMatch(/窗帘\s*\/\s*\d/)
  })

  // #2916: 订单列表「采购明细」列漏掉加工项计费。
  // 根因：组件读 processingInfo.totalAmount/totalFee（字段从未写入），真实数据在
  // processingInfo.processingFee（该项加工费合计）+ processingInfo.processingItems（加工项明细）。
  describe('采购明细列加工项计费（#2916）', () => {
    const processingOrder = {
      ...mockOrder,
      items: [
        {
          ...mockOrder.items![0],
          processingInfo: {
            processingFee: 50,
            processingItems: [
              { id: 'pi-1', name: '打孔', unitPrice: 10, quantity: 5, subtotal: 50 },
            ],
          },
        },
      ],
    }
    const detailCell = () => document.querySelector('td.min-w-\\[280px\\]') as HTMLElement

    it('含加工项订单：商品行后展示 + 加工费{金额}元', () => {
      render(<OrderTable {...defaultProps} orders={[processingOrder]} />)
      const cellText = detailCell().textContent || ''
      // 商品行：窗帘 : 99元 × 3米 = 297元 + 加工费50元（加工费与商品行同行展示）
      expect(cellText).toMatch(/窗帘\s*:\s*99元\s*×\s*3米\s*=\s*297元/)
      expect(cellText).toMatch(/\+\s*加工费50元/)
    })

    it('#4882：加工项明细块**整块退场**（不再渲染 名称 × 单价元/米 × 数量米 = 金额元）', () => {
      render(<OrderTable {...defaultProps} orders={[processingOrder]} />)
      const cellText = detailCell().textContent || ''
      // 红证：旧形态是「打孔 × 10元/米 × 5米 = 50元」——把明细块加回来这两句即红
      expect(cellText).not.toMatch(/打孔\s*×\s*10元\/米/)
      expect(cellText).not.toMatch(/元\/米/)
      // 退场的是**逐项明细**，不是加工费本身：行尾 `+ 加工费50元` 聚合必须照旧
      expect(cellText).toMatch(/\+\s*加工费50元/)
    })

    it('不含加工项订单：采购明细列不出现加工费字样', () => {
      render(<OrderTable {...defaultProps} />)
      expect(detailCell().textContent).not.toMatch(/加工费/)
    })

    it('#2916 兼容旧数据：processingInfo 无 processingFee 但带加工项明细时按明细求和展示', () => {
      const noFeeFieldOrder = {
        ...mockOrder,
        items: [
          {
            ...mockOrder.items![0],
            processingInfo: {
              // #4882：明细条目只剩金额键（`amount` / `subtotal`）—— 逐项单价 / 数量已不落库
              processingItems: [{ id: 'pi-1', name: '定型', subtotal: 32 }],
            },
          },
        ],
      }
      render(<OrderTable {...defaultProps} orders={[noFeeFieldOrder]} />)
      const cellText = detailCell().textContent || ''
      expect(cellText).toMatch(/\+\s*加工费32元/)
    })
  })

  // issue #7138：列表「采购明细」的加工费必须与订单详情**同一份权威值**
  // （`processingInfo.processingFeeDetail.amount`，服务端取价落库）。
  // `processingInfo.processingFee` 是**客户端副本**（下单页 / 探针脚本写进来，服务端既不校验
  // 也不覆盖）⇒ 采信它就会与详情自相矛盾（dev 实证：副本 15 元 / 权威 0 元·unpriced）。
  describe('采购明细列加工费口径（#7138：权威 detail 优先）', () => {
    const detailCell = () => document.querySelector('td.min-w-\\[280px\\]') as HTMLElement
    const orderWith = (processingInfo: Record<string, unknown>) => ({
      ...mockOrder,
      items: [{ ...mockOrder.items![0], processingInfo }],
    })

    it('副本 15 元 / 权威 0 元·未定价 ⇒ 不渲染「加工费15元」（与详情「未定价」同口径）', () => {
      render(
        <OrderTable
          {...defaultProps}
          orders={[
            orderWith({
              processingFee: 15,
              processingItems: [{ id: 'pi-1', name: '锁边', quantity: 2 }],
              processingFeeDetail: { fee_source: 'unpriced', amount: 0, composition: '锁边' },
            }),
          ]}
        />
      )
      const cellText = detailCell().textContent || ''
      // 红证：改前这里渲染「+ 加工费15元」——那正是与详情「未定价」打架的那一行
      expect(cellText).not.toMatch(/加工费/)
      expect(cellText).not.toMatch(/15/)
    })

    it('权威命中（amount 15 元）⇒ 渲染「+ 加工费15元」，不采信副本里的别的数', () => {
      render(
        <OrderTable
          {...defaultProps}
          orders={[
            orderWith({
              processingFee: 99,
              processingFeeDetail: {
                fee_source: 'matched',
                amount: 15,
                unit_price: 7.5,
                meters: 2,
              },
            }),
          ]}
        />
      )
      const cellText = detailCell().textContent || ''
      expect(cellText).toMatch(/\+\s*加工费15元/)
      // 副本里的 99 不得被当成加工费（`99元` 只允许出现在商品单价位）
      expect(cellText).not.toMatch(/加工费99元/)
    })
  })

  // issue #7138（第二处）：空数据态下表头「采购明细」被压成一字一行（竖排）。
  // 有数据时是数据格的 `min-w-[280px]` 撑住列宽 ⇒ 规则必须是**表头与数据格共用同一宽度下限**。
  it('空数据态：采购明细表头与数据格共用同一宽度下限（不被压成竖排）', () => {
    render(<OrderTable {...defaultProps} orders={[]} />)
    const th = screen.getByText('采购明细').closest('th') as HTMLElement
    expect(th).toBeTruthy()
    expect(th.className).toContain('min-w-[280px]')
    expect(th.className).toContain('whitespace-nowrap')
  })

  it('空列表显示"暂无数据"', () => {
    render(<OrderTable {...defaultProps} orders={[]} />)
    expect(screen.getByText('暂无数据')).toBeTruthy()
  })

  it('加载中显示"加载中..."', () => {
    render(<OrderTable {...defaultProps} orders={[]} loading={true} />)
    expect(screen.getByText('加载中…')).toBeTruthy()
  })

  it('应渲染复选框列', () => {
    render(<OrderTable {...defaultProps} />)
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes.length).toBeGreaterThan(0)
  })

  // #1290: 订单ID 行顶格 — 左侧无 padding
  it('订单ID 列 data cell 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const orderIdCell = screen.getByText('ORD-001').closest('td')
    expect(orderIdCell).toBeTruthy()
    expect(orderIdCell!.className).toMatch(/\bpl-0\b/)
    expect(orderIdCell!.className).not.toMatch(/\bpx-4\b/)
  })

  // #1290: 商品货号行顶格 — 左侧无 padding
  it('采购商品列 data cell 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const skuCell = screen.getByText(/货号/).closest('td')
    expect(skuCell).toBeTruthy()
    expect(skuCell!.className).toMatch(/\bpl-0\b/)
    expect(skuCell!.className).not.toMatch(/\bpx-4\b/)
  })

  // #1290: 订单ID 列 header 也应顶格，保证 header/data 对齐
  it('订单ID 列 header 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const headerCell = screen.getByText('订单ID').closest('th')
    expect(headerCell).toBeTruthy()
    expect(headerCell!.className).toMatch(/\bpl-0\b/)
    expect(headerCell!.className).not.toMatch(/\bpx-4\b/)
  })

  it('有备注时显示备注预览文本（去除时间戳前缀）', () => {
    const orderWithRemark = {
      ...mockOrder,
      remark: '[2026-07-01 10:00] 客户催单',
    }
    render(<OrderTable {...defaultProps} orders={[orderWithRemark]} />)
    // 应该显示去除时间戳前缀后的内容
    expect(screen.getByText(/客户催单/)).toBeTruthy()
    // 不应直接显示原始时间戳
    expect(screen.queryByText(/2026-07-01 10:00/)).toBeNull()
  })

  it('无备注时显示 - 占位符', () => {
    const orderNoRemark = {
      ...mockOrder,
      remark: undefined,
    }
    render(<OrderTable {...defaultProps} orders={[orderNoRemark]} />)
    expect(screen.getByText('-')).toBeTruthy()
  })

  // #2539: 采购明细列与采购商品列的 items 为空时渲染「暂无数据」，整表无裸 '-' 占位
  // （原判据文字写「采购商品列无 firstItem」—— 该实现期局部变量已随 issue #4908 的修复删除，
  //   2026-09-25 随 #4916 一并改为按 `items` 判空，文案不再引用已不存在的实现标识符）
  it('采购明细列与采购商品列的 items 为空时渲染「暂无数据」，无裸 - 占位', () => {
    const emptyItemsOrder = {
      ...mockOrder,
      items: [],
      processingItems: [],
      remark: '有备注',
      customerAddress: '测试地址',
    }
    render(<OrderTable {...defaultProps} orders={[emptyItemsOrder]} />)
    const emptyLabels = screen.getAllByText('暂无数据')
    expect(emptyLabels.length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('-')).toBeNull()
  })

  // #1289: 订单有 remarks[] 数组但 remark 字符串为空时，触发显示最新备注预览
  it('#1289: remarks 数组有数据但 remark 为空时，应显示最新备注预览', () => {
    const orderWithRemarksArray = {
      ...mockOrder,
      remark: undefined,
      remarks: [
        { id: '1', content: '最新备注内容', createdAt: '2026-07-13T10:00:00Z', operator: '张三' },
        { id: '2', content: '旧备注', createdAt: '2026-07-10T09:00:00Z' },
      ],
    }
    render(<OrderTable {...defaultProps} orders={[orderWithRemarksArray]} />)
    // 应显示最新备注的预览内容（按 createdAt 降序取第一条）
    expect(screen.getByText(/最新备注内容/)).toBeTruthy()
    // 备注列不应显示 - 占位符
    expect(screen.queryByText('-')).toBeNull()
  })

describe('OrderTable 退款按钮（基于真实状态 + refundAmount）', () => {
  const refundProps = {
    ...defaultProps,
    onRefund: vi.fn(),
    onConfirmPayment: vi.fn(),
    onConfirmReceive: vi.fn(),
  }

  /**
   * issue #8011：「处理退款」已从行内文字链收进「⋯」菜单 ⇒ 先展开菜单再取。
   * 🔴 展开这一步不能省 —— 省掉后 `queryByText('处理退款')` 恒为 null，
   * 「可退状态不显示退款」那条会**空跑通过**（负控变成假绿）。
   */
  const openActionsMenu = () => {
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
  }

  it('confirmed 订单（未退款）：「⋯」菜单里有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'confirmed' as unknown as OrderStatus, refundAmount: 0 }]} />)
    openActionsMenu()
    expect(screen.getByRole('menuitem', { name: '处理退款' })).toBeTruthy()
  })

  it('shipped 订单（未退款）：「⋯」菜单里有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'shipped' as unknown as OrderStatus, refundAmount: 0 }]} />)
    openActionsMenu()
    expect(screen.getByRole('menuitem', { name: '处理退款' })).toBeTruthy()
  })

  it('completed 订单（未退款）：「⋯」菜单里有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'completed' as unknown as OrderStatus, refundAmount: 0 }]} />)
    openActionsMenu()
    expect(screen.getByRole('menuitem', { name: '处理退款' })).toBeTruthy()
  })

  it('已退款订单（refundAmount > 0）菜单里没有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'completed' as unknown as OrderStatus, refundAmount: 99 }]} />)
    openActionsMenu()
    expect(screen.queryByText('处理退款')).toBeNull()
  })

  it('pending（待付款）订单菜单里没有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'pending_payment' as unknown as OrderStatus, refundAmount: 0 }]} />)
    openActionsMenu()
    expect(screen.queryByText('处理退款')).toBeNull()
  })

  it('cancelled（已关闭）订单菜单里没有 处理退款', () => {
    render(<OrderTable {...refundProps} orders={[{ ...mockOrder, status: 'closed' as unknown as OrderStatus, refundAmount: 0 }]} />)
    openActionsMenu()
    expect(screen.queryByText('处理退款')).toBeNull()
  })
})
})

/**
 * 「打印」列（issue #7902）—— 列表要能一眼看出这单打过没有。
 *
 * 读数**全部来自服务端聚合**（`printedAt` / `printCount` / `printedDocTypes`，真值 = print_logs
 * 里 status='fired' 的行）⇒ 换台电脑打过的纸也看得见；前端不拿本地状态冒充。
 */
describe('打印列（issue #7902）', () => {
  const baseProps = {
    orders: [] as never[],
    loading: false,
    selectedIds: [] as string[],
    onSelectChange: () => {},
    onView: () => {},
    onRemark: () => {},
    onClose: () => {},
    onShip: () => {},
  }

  it('已打印 ⇒ 勾 + 最近打印时间；悬浮说明有次数与打过的单据', () => {
    render(
      <OrderTable
        {...baseProps}
        orders={[
          {
            ...mockOrder,
            id: 'order-printed',
            // 🔴 用**本机时区**构造（CI 跑在 UTC）：直接写 `+08:00` 的串会让「15:22」在
            // UTC runner 上渲染成 07:22 ⇒ 判据在本地绿、CI 红（本判据只关心"显示的是哪个时刻"，
            // 不关心时区本身；时刻身份由 `new Date(...)` 的本地分量固定）
            printedAt: new Date(2026, 9, 27, 15, 22).toISOString(),
            printCount: 3,
            printedDocTypes: ['sales', 'processing', 'labels'],
          } as never,
        ]}
      />,
    )

    const cell = screen.getByTestId('order-printed-order-printed')
    expect(cell).toHaveTextContent('已打印')
    // 今年内的紧凑形态：MM-DD HH:mm（与完整时间戳分开：列表列宽有限，"多久以前"才是要看的那一面）
    expect(cell).toHaveTextContent('10-27 15:22')
    const title = cell.querySelector('span')?.getAttribute('title') ?? ''
    expect(title).toContain('已打印 3 次')
    expect(title).toContain('销售单')
    expect(title).toContain('加工单')
    expect(title).toContain('水洗唛')
  })

  it('从未打印 ⇒ 灰字「未打印」（不是空白，也不是 0 次）', () => {
    render(<OrderTable {...baseProps} orders={[{ ...mockOrder, id: 'order-fresh' } as never]} />)

    const cell = screen.getByTestId('order-printed-order-fresh')
    expect(cell).toHaveTextContent('未打印')
    expect(cell).not.toHaveTextContent('已打印')
  })
})
