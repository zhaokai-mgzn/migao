// case_ids: PR-081
//
// PR-081（issue #5177）：智能派单的**纯前端薄助手** —— 池化派单请求体 + 服务端值的展示格式化。
//
// 本文件只钉两件**前端口径红线**（真值源 = `ProductionPoolViews.Preview` 的五个 BigDecimal 字段
// + `migao-dev-flow` §15）：
//   ① **不重算米数**：`formulaMeters` / `pooledPlannedMeters` / `savedMeters` /
//      `perOrderPlannedMeters` / `poolingGainMeters` —— **五个都是服务端聚合**，一律**原样渲染**
//      （要求是「口径必须与落账逐值相等」，在浏览器里再算一次 = 第二份会漂的口径）。
//      ⚠️ `perOrderPlannedMeters` 是**一个数**（逐单派的应领**合计**，对照读数），
//      **不是** orderId → 米数 的映射 ⇒ 预览区没有逐单明细表（API 不下发）。
//      红证两条：① 用**故意不自洽**的服务端数字（`formulaMeters − pooledPlannedMeters ≠ savedMeters`）
//      ⇒ 前端一旦自己相减就红；② 删掉「对照·逐单派应领」行（= 把它当 map 处理的后果）⇒ 红。
//   ② **不重排**：本模块**不导出**任何排序器；顺序由页面按接口数组顺序渲染（DOM 序判据在
//      `tests/unit/pages/production-pool-batch.test.tsx`，那里才是顺序的消费者）。
import { describe, it, expect } from 'vitest'
import {
  buildPoolRequest,
  formatDeliveryDaysLeft,
  formatMeters,
  formatRequiredDeliveryDate,
  formatWaitHours,
  previewSummaryRows,
  singleDispatchLines,
  singleDispatchLinesOfOrder,
  singleDispatchOrders,
} from '@/lib/pool-board'
import type { PoolBoard, PoolLine, PoolPreview } from '@/types'

describe('buildPoolRequest（/preview 与 /dispatch 同体）', () => {
  const L = (orderId: string, itemId: string) => ({ orderId, itemId })

  it('成批池化：pooled=true，**逐行带指派**（orderId+itemId）+ 显式给 fifo（issue #6408）', () => {
    expect(buildPoolRequest([L('o1', 'i1'), L('o2', 'i2')], true)).toEqual({
      orderIds: ['o1', 'o2'],
      batches: [
        { orderId: 'o1', itemId: 'i1' },
        { orderId: 'o2', itemId: 'i2' },
      ],
      assignmentRule: 'fifo',
      pooled: true,
    })
  })

  it('加急插队：**同一个端点 + 单订单 + pooled=false**（一个动作，不批）', () => {
    const body = buildPoolRequest([L('u1', 'iu1')], false)
    expect(body.pooled).toBe(false)
    expect(body.orderIds).toEqual(['u1'])
    // 加急插队是「一单一派」—— 批内混加急会被服务端整批拒绝（422），前端不制造那种请求
    expect(body.orderIds).toHaveLength(1)
  })

  it('🔴 类级自证：**非空行 ⇒ 指派非空、规则非空、每条指派都落在请求声明的单号里**（空指派 = #6408 的缺陷形态）', () => {
    // 缺陷形态（2026-10-06 实测，300 单四臂对照）：`batches: []` ⇒ 服务端 `buildDesignations`
    // 直接返回空 ⇒ 排料求解器一次都不跑 ⇒ 消耗行 0 行、`saved = 0`、页面「预计节省」恒 0.00。
    // 本断言让「又变回空指派 / 规则又给 null」当场红，而不是等到真库上看不见扣料才发现。
    // 🔴 2026-10-27 改判（issue #7904）：原先这里断言 `batches.map(orderId) === orderIds`（**逐行 1:1**）——
    // 它对「多套订单」这一形态把缺陷钉成了正确（见下一条）。`batches` 是**逐池行**的，
    // `orderIds` 是**去重后的订单集合**，两者只在「一单一行」时巧合相等。
    for (const pooled of [true, false]) {
      const body = buildPoolRequest([L('a', 'ia'), L('b', 'ib'), L('c', 'ic')], pooled)
      expect(body.batches).toHaveLength(3)
      expect(body.orderIds).toEqual(['a', 'b', 'c'])
      expect(body.batches.every((b) => body.orderIds.includes(b.orderId))).toBe(true)
      expect(body.batches.every((b) => b.itemId !== '')).toBe(true)
      // 规则必须显式给值：`null` ⇒ 未指定批次的行**不补位**（服务端口径）⇒ 等于白带指派
      expect(body.assignmentRule).toBe('fifo')
    }
  })

  it('🔴 多套订单：同一 orderId 的 N 行 ⇒ `orderIds` **去重**、`batches` 仍逐行（issue #7904）', () => {
    // 池行是**逐商品行**的（`PoolLine` 带 `orderId` + `itemId`），而服务端是「**一单一加工单**」：
    // 重复单号被当成 N 张单各派一次 ⇒ 第 2 份撞部分唯一索引 `uk_processing_orders_active`，
    // 而 PG 事务已被这条失败语句中止 ⇒ 第 3 份抛 25P02（不是 `DuplicateKeyException`）⇒
    // 逸出兜底 ⇒ **500「服务器内部错误」**（用户 2026-10-27 现场）。
    // N=2 时更糟：接口 200 + 「合并派单完成：1 单」，而整批在提交时静默回滚 —— 一张加工单都没生成。
    const body = buildPoolRequest([L('o1', 'i1'), L('o1', 'i2'), L('o1', 'i3'), L('o2', 'i4')], true)
    expect(body.orderIds).toEqual(['o1', 'o2'])
    // 指派一条都不能丢（丢了 = 那一套不参与排料，`saved` 少算）
    expect(body.batches).toEqual([
      { orderId: 'o1', itemId: 'i1' },
      { orderId: 'o1', itemId: 'i2' },
      { orderId: 'o1', itemId: 'i3' },
      { orderId: 'o2', itemId: 'i4' },
    ])
  })
})

describe('等待时长 / 到货日 文案（入参 = 服务端值，不重算）', () => {
  it('等待时长 < 24 小时按小时显示，≥ 24 小时进位成「X 天 Y 小时」', () => {
    expect(formatWaitHours(3)).toBe('3 小时')
    expect(formatWaitHours(12.5)).toBe('12.5 小时')
    expect(formatWaitHours(24)).toBe('1 天')
    expect(formatWaitHours(50)).toBe('2 天 2 小时')
  })

  it('到货日剩余天数：null = 未指定、负数 = 已逾期、0 = 今天到期', () => {
    expect(formatDeliveryDaysLeft(null)).toBe('未指定')
    expect(formatDeliveryDaysLeft(-2)).toBe('已逾期 2 天')
    expect(formatDeliveryDaysLeft(0)).toBe('今天到期')
    expect(formatDeliveryDaysLeft(3)).toBe('剩 3 天')
  })

  it('到货日：null/空 = 未指定（不猜一个日期）', () => {
    expect(formatRequiredDeliveryDate(null)).toBe('未指定')
    expect(formatRequiredDeliveryDate(undefined)).toBe('未指定')
    expect(formatRequiredDeliveryDate('2026-09-30')).toBe('2026-09-30')
  })

  it('米数：缺失值显示 -（不是 0.00 —— 0 与「没有值」是两件事）', () => {
    expect(formatMeters(0)).toBe('0.00')
    expect(formatMeters(12.345)).toBe('12.35')
    expect(formatMeters(null)).toBe('-')
    expect(formatMeters(undefined)).toBe('-')
  })
})

describe('成批预览摘要：渲染服务端值，绝不自己相减', () => {
  // ⚠️ 真值源 = `ProductionPoolViews.Preview`：**五个米数字段全是 BigDecimal**（都是聚合）。
  // `perOrderPlannedMeters` 是**一个数**（逐单派的应领**合计**，对照读数），**不是** map ——
  // 当成 `Object.entries(...)` 会静默渲染出 0 行（本仓库明令禁止的「空转」形态）。
  const preview = {
    orderCount: 2,
    assignmentRule: 'best-fit',
    formulaMeters: 10,
    pooledPlannedMeters: 6.5,
    // 🔴 **故意不自洽**：真实服务端会给 3.5，这里给 99 —— 只要前端自己算
    // `formulaMeters − pooledPlannedMeters`，下面的断言立刻红（= 判据不会被自己的文案喂绿）
    savedMeters: 99,
    perOrderPlannedMeters: 8, // 对照读数（逐单派应领合计），**一个数**
    poolingGainMeters: 1.5, // = 8 − 6.5（服务端算）
  } as unknown as PoolPreview

  it('五行摘要逐字给出服务端的五个键（标签分开「预计节省」与「合并新增收益」）', () => {
    const rows = previewSummaryRows(preview)
    expect(rows.map((r) => r.label)).toEqual([
      '逐单公式米数（对照基线）',
      '合并后预计领料米数',
      '预计节省',
      '对照·逐单派应领',
      '合并新增收益',
    ])
    expect(rows.map((r) => r.value)).toEqual(['10.00', '6.50', '99.00', '8.00', '1.50'])
  })

  it('`perOrderPlannedMeters` 是**一个数**（对照读数）—— 不是 orderId→米数 的映射', () => {
    const rows = previewSummaryRows(preview)
    // 当 map 处理（`Object.entries(<number>)`）⇒ 该行会是 `-` 或整块消失 ⇒ 这两条红
    const compare = rows.find((r) => r.label === '对照·逐单派应领')!
    expect(compare).toBeTruthy()
    expect(compare.value).toBe('8.00')
  })

  it('「预计节省」与「合并新增收益」是两个独立的服务端键 —— 合成一句就是丢信息', () => {
    const rows = previewSummaryRows(preview)
    const saved = rows.find((r) => r.label === '预计节省')!
    const gain = rows.find((r) => r.label === '合并新增收益')!
    // saved = formula − pooled = 3.5（**真实**服务端值；本桩故意给 99 以钉「不自己算」）；
    // gain = perOrder − pooled = 1.5：两者是**不同**的数，混成一个就分不清「池化的功劳」与「旧收益」
    expect(saved.value).not.toBe(gain.value)
    expect(saved.value).toBe('99.00')
    expect(gain.value).toBe('1.50')
  })
})

describe('singleDispatchLines：加急 / 外发 = 一张表（issue #7943）', () => {
  const line = (orderId: string): PoolLine => ({ orderId, itemId: `i-${orderId}` } as PoolLine)
  const board = (over: Partial<PoolBoard>) => over as PoolBoard

  it('拼接序：加急段在前、外发段在后（两段各自的序不动 ⇒ 前端不重排）', () => {
    const merged = singleDispatchLines(
      board({ urgentLines: [line('u1'), line('u2')], outsourcedLines: [line('x1')] }),
    )
    expect(merged.map((l) => l.orderId)).toEqual(['u1', 'u2', 'x1'])
  })

  it('后端 `non_null` 键缺席 / 空看板 ⇒ 空数组（不崩、不造行）；只有外发时也不丢', () => {
    expect(singleDispatchLines(null)).toEqual([])
    expect(singleDispatchLines(board({}))).toEqual([])
    expect(
      singleDispatchLines(board({ outsourcedLines: [line('x1')] })).map((l) => l.orderId),
    ).toEqual(['x1'])
  })
})

describe('singleDispatchLinesOfOrder：**整单派工 ⇒ 整单逐行指派**（issue #7968）', () => {
  const line = (orderId: string, itemId: string): PoolLine =>
    ({ orderId, itemId } as PoolLine)
  const board = (over: Partial<PoolBoard>) => over as PoolBoard

  it('多套加急单：同一 orderId 的**全部**成品帘行都返回（顺序 = 服务端拼接序）', () => {
    const lines = singleDispatchLinesOfOrder(
      board({
        urgentLines: [line('m1', 'im1'), line('m2', 'iu2'), line('m1', 'im2')],
      }),
      'm1',
    )
    // 点哪一行不改变「哪几行领批次」：两张成品帘行一条都不能少
    expect(lines.map((l) => l.itemId)).toEqual(['im1', 'im2'])
  })

  it('多套外发行同样整单返回（加急 / 外发走同一个派单动作，不能只修一段）', () => {
    const lines = singleDispatchLinesOfOrder(
      board({ outsourcedLines: [line('x1', 'ix1'), line('x1', 'ix2'), line('x2', 'ix3')] }),
      'x1',
    )
    expect(lines.map((l) => l.itemId)).toEqual(['ix1', 'ix2'])
  })

  it('跨订单不串行 / 空看板不崩（订单不存在时由调用方兜底，不在这里造行）', () => {
    const b = board({ urgentLines: [line('m1', 'im1')], outsourcedLines: [line('x1', 'ix1')] })
    expect(singleDispatchLinesOfOrder(b, 'm1').map((l) => l.itemId)).toEqual(['im1'])
    expect(singleDispatchLinesOfOrder(b, 'x1').map((l) => l.itemId)).toEqual(['ix1'])
    expect(singleDispatchLinesOfOrder(b, 'nope')).toEqual([])
    expect(singleDispatchLinesOfOrder(null, 'm1')).toEqual([])
  })
})

describe('singleDispatchOrders：逐单区按**订单**归并（issue #7974）', () => {
  const line = (orderId: string, itemId: string, over: Partial<PoolLine> = {}): PoolLine =>
    ({
      orderId,
      orderNo: `NO-${orderId}`,
      itemId,
      productId: 'p1',
      productName: `商品-${itemId}`,
      requiredMeters: 1,
      waitingSince: '2026-10-20T08:00:00+08:00',
      waitHours: 3,
      overdue: false,
      isUrgent: true,
      ...over,
    }) as PoolLine
  const board = (over: Partial<PoolBoard>) => over as PoolBoard

  it('多套订单 ⇒ **一组多行**（一套都不能丢）；订单级字段取该单第一行；组内行序不变', () => {
    const orders = singleDispatchOrders(
      board({
        urgentLines: [
          line('m1', 'im1', {
            waitHours: 6,
            requiredDeliveryDate: '2026-10-28',
            deliveryDaysLeft: 1,
          }),
          line('m1', 'im2'),
        ],
      }),
    )
    expect(orders).toHaveLength(1)
    expect(orders[0].orderId).toBe('m1')
    expect(orders[0].orderNo).toBe('NO-m1')
    expect(orders[0].lines.map((l) => l.itemId)).toEqual(['im1', 'im2'])
    expect(orders[0].waitHours).toBe(6)
    expect(orders[0].requiredDeliveryDate).toBe('2026-10-28')
    expect(orders[0].deliveryDaysLeft).toBe(1)
    expect(orders[0].isUrgent).toBe(true)
    expect(orders[0].isOutsourced).toBe(false)
  })

  it('订单序 = **首次出现序**（加急段在前、外发段在后）；同一单分散出现也只成一组', () => {
    const orders = singleDispatchOrders(
      board({
        urgentLines: [line('u2', 'iu21'), line('u1', 'iu11'), line('u2', 'iu22')],
        outsourcedLines: [line('x1', 'ix1', { isUrgent: false, isOutsourced: true })],
      }),
    )
    expect(orders.map((o) => o.orderId)).toEqual(['u2', 'u1', 'x1'])
    expect(orders[0].lines.map((l) => l.itemId)).toEqual(['iu21', 'iu22'])
    // 加急 / 外发标记只来自该单自己的行（不是全局默认值）
    expect(orders[2].isOutsourced).toBe(true)
    expect(orders[0].isOutsourced).toBe(false)
  })

  it('空看板 / 缺键 ⇒ 空数组（不造行、不崩）', () => {
    expect(singleDispatchOrders(null)).toEqual([])
    expect(singleDispatchOrders(board({}))).toEqual([])
  })
})
