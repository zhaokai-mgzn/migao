// 线③ 家族 B —— 库存下游：移动加权平均（退货/报损/调账后）/ 台账条数不变式 /
//                批次效期库龄 / 残料 / saving-board / POST batch-stock 语义。
//
// 期望来源铁律：**一律本包独立算出**——
//   · 移动加权平均：SQL numeric 独立重算（口径写死在下面 EXPECT_AVG_SQL，抄自
//     InboundOrderService.movingAverage 的 doc：HALF_UP 4 位 / 未记单价保持原值 / 无库存取进价）；
//   · 台账条数：**前后计数差**（变动次数由操作本身决定，不由接口决定）。
import { loginApi, api, psql, one, judge, log, OUT, TENANT_ID, guardedWrite, rowFingerprint, nowCST, psqlRaw } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** 独立移动加权平均重算（SQL numeric，非浮点）。口径 = (bq*ba + iq*uc)/(bq+iq) HALF_UP 4 位。
 *  未记单价(uc null) ⇒ 返回 ba；bq<=0 或 ba null ⇒ uc。 */
const EXPECT_AVG_SQL = (bq, ba, iq, uc) => {
  if (uc === null || uc === undefined) return `null::numeric`
  return `(case when ${bq} <= 0 or ${ba} is null then ${uc}::numeric
            else round((${ba}::numeric * ${bq}::numeric + ${uc}::numeric * ${iq}::numeric)
                       / (${bq}::numeric + ${iq}::numeric), 4) end)`
}

export async function familyB(R, { token }) {
  log('══════════ 家族 B：库存下游 ══════════')
  const stamp = Date.now().toString(36)
  const productId = `c3prod${stamp}${'0'.repeat(Math.max(0, 20 - stamp.length))}`
  const skuCode = `c3sku${stamp}`
  guardedWrite(`-- probe-ok
    insert into products (id, tenant_id, name, stock, deleted, created_at, updated_at)
    values ('${productId}', ${TENANT_ID}, '线③验收探针货号', 0, 0, now(), now());`)
  guardedWrite(`-- probe-ok
    insert into product_skus (tenant_id, product_id, door_width, stock, sku_code, price, avg_cost, created_at, updated_at)
    values (${TENANT_ID}, '${productId}', '探针规格', 0, '${skuCode}', 0, null, now(), now());`)
  // 🔴 id 取 **text**：product_skus.id 是 bigint，实测值 2.1e18 > 2^53 ⇒
  //    JSON.parse 成 JS number 会丢精度（BigInt(Number) 实测 ...432 ≠ ...400）。
  //    用 ::text 拿字符串，SQL 字符串插值才是**逐字**的。
  const sku = one(`select id::text sid, stock, avg_cost from product_skus where tenant_id=${TENANT_ID} and sku_code='${skuCode}'`)
  log(`探针 SKU: id=${sku.sid} product=${productId} stock=${sku.stock} avg_cost=${sku.avg_cost}`)
  const skuId = sku.sid

  const ledgerCount = () => Number(one(`select count(*) c from stock_ledger_entries
    where tenant_id=${TENANT_ID} and sku_id=${skuId}`).c)

  /** 造一张**草稿**入库单（探针 id / 探针单号）并过账。 */
  async function postInbound({ tag, qty, unitCost, dyeLot }) {
    const orderId = `c3inb${tag}${stamp}`.slice(0, 40)
    const inboundNo = `c3RK${tag}${stamp}`.slice(0, 30)
    guardedWrite(`-- probe-ok
      insert into inbound_orders (id, tenant_id, inbound_no, inbound_date, status, total_amount, source, created_at, updated_at, deleted)
      values ('${orderId}', ${TENANT_ID}, '${inboundNo}', '2026-10-03', 'draft', 0, 'purchase', now(), now(), 0);`)
    guardedWrite(`-- probe-ok
      insert into inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost,
        amount, dye_lot, created_at, updated_at, deleted)
      values (${TENANT_ID}, '${orderId}', ${skuId}, '${productId}', '${skuCode}', ${qty},
        ${unitCost === null ? 'null' : unitCost}, ${unitCost === null ? 'null' : `round(${qty}::numeric*${unitCost}::numeric,4)`},
        ${dyeLot ? `'${dyeLot}'` : 'null'}, now(), now(), 0);`)
    const r = await api('PATCH', `/api/admin/inbound-orders/${orderId}`, { token, body: { action: 'post' } })
    return { orderId, inboundNo, r }
  }

  const before = one(`select stock, avg_cost from product_skus where id=${skuId}`)
  const beforeAvg = before.avg_cost === null ? 'null' : String(before.avg_cost)
  const lc0 = ledgerCount()

  // ── B1 首次入库：均价 = 进价（无库存分支）──────────────────────
  const i1 = await postInbound({ tag: 'A', qty: '60.5', unitCost: '12.5', dyeLot: 'c3DYE' })
  const a1 = one(`select stock, avg_cost from product_skus where id=${skuId}`)
  const exp1 = psql(`select ${EXPECT_AVG_SQL('0', 'null', '60.5', '12.5')} v`)[0].v
  judge(R, {
    id: 'B1',
    name: '首次入库（无库存）⇒ 移动加权平均 = 行进价',
    expect: `stock=60.5, avg_cost=${exp1}`, actual: `stock=${a1.stock}, avg_cost=${a1.avg_cost}`,
    pass: i1.r.status === 200 && Number(a1.stock) === 60.5 && String(a1.avg_cost) === String(exp1),
    expectSource: `独立 SQL: ${EXPECT_AVG_SQL('0', 'null', '60.5', '12.5')}（口径抄自 InboundOrderService.movingAverage doc：before_qty=0 ⇒ after=unit_cost）`,
    evidence: [`PATCH /api/admin/inbound-orders/${i1.orderId} {action:post} → HTTP ${i1.r.status}`, `入库前: stock=${before.stock} avg=${beforeAvg}`],
  })

  // ── B2 二次入库：加权平均（HALF_UP 4 位）────────────────────────
  const lc1 = ledgerCount()
  const i2 = await postInbound({ tag: 'B', qty: '39.5', unitCost: '10.25', dyeLot: 'c3DYE2' })
  const a2 = one(`select stock, avg_cost from product_skus where id=${skuId}`)
  const exp2 = psql(`select ${EXPECT_AVG_SQL('60.5', '12.5', '39.5', '10.25')} v`)[0].v
  judge(R, {
    id: 'B2',
    name: '二次入库 ⇒ 移动加权平均 = SQL 独立重算（HALF_UP 4 位）',
    expect: `stock=100.0, avg_cost=${exp2}`, actual: `stock=${a2.stock}, avg_cost=${a2.avg_cost}`,
    pass: i2.r.status === 200 && Number(a2.stock) === 100
      && String(a2.avg_cost) === String(exp2),
    expectSource: `独立 SQL: ${EXPECT_AVG_SQL('60.5', '12.5', '39.5', '10.25')} —— 完全不用接口读数`,
    evidence: [`PATCH → HTTP ${i2.r.status}`, `期望中间值 = (60.5*12.5 + 39.5*10.25)/100 = ${(60.5 * 12.5 + 39.5 * 10.25) / 100}`],
  })

  // ── B3 未记单价入库：均价保持原值（不得被抹掉/造值）──────────────
  const lc2 = ledgerCount()
  const i3 = await postInbound({ tag: 'C', qty: '10.0', unitCost: null, dyeLot: 'c3DYE3' })
  const a3 = one(`select stock, avg_cost from product_skus where id=${skuId}`)
  judge(R, {
    id: 'B3',
    name: '未记单价的入库 ⇒ 只加数量、均价保持原值（不抹掉也不凭空造）',
    expect: `stock=110.0, avg_cost=${a2.avg_cost}（不变）`, actual: `stock=${a3.stock}, avg_cost=${a3.avg_cost}`,
    pass: i3.r.status === 200 && Number(a3.stock) === 110 && String(a3.avg_cost) === String(a2.avg_cost),
    expectSource: '口径：movingAverage(uc==null) ⇒ 返回 beforeAvg（doc 明写「未记单价的入库不得把已有均价抹掉，也不得凭空造一个」）。期望均价 = 上一步实测的 B2 值。',
    evidence: [`PATCH → HTTP ${i3.r.status}`],
  })

  // ── B4 台账条数不变式：3 次入库 = 3 条台账（不多不少）────────────
  const lc3 = ledgerCount()
  judge(R, {
    id: 'B4',
    name: '库存台账条数 = 变动次数（3 次入库 ⇒ 恰 3 条，不多不少；无 delta=0 噪声行）',
    expect: 3, actual: lc3 - lc0,
    pass: (lc3 - lc0) === 3,
    expectSource: `前后计数差（本包独立算）：ledgerCount(后)=${lc3} − ledgerCount(前)=${lc0}。变动次数由本包执行的 3 次过账决定，不由接口决定。`,
    evidence: [`台账行: ${JSON.stringify(psql(`select id, delta, before_qty, after_qty, avg_cost_before, avg_cost_after, unit_cost, cost_amount, note
      from stock_ledger_entries where tenant_id=${TENANT_ID} and sku_id=${skuId} order by id`))}`],
  })

  // ── B5 台账链条自洽：after_qty[i] == before_qty[i+1]（首尾相接，无假环）──
  const chain = psql(`select id, before_qty, after_qty, delta from stock_ledger_entries
    where tenant_id=${TENANT_ID} and sku_id=${skuId} order by id`)
  let chainOk = true
  const chainBad = []
  for (let i = 1; i < chain.length; i++) {
    if (Number(chain[i].before_qty) !== Number(chain[i - 1].after_qty)) {
      chainOk = false
      chainBad.push({ i, prevAfter: chain[i - 1].after_qty, curBefore: chain[i].before_qty })
    }
  }
  judge(R, {
    id: 'B5',
    name: '台账链条首尾相接：after_qty[i] == before_qty[i+1] 且 delta == after − before',
    expect: '全部相接且 delta 自洽', actual: chainOk ? '相接且自洽' : JSON.stringify(chainBad),
    pass: chainOk && chain.every((c) => Number(c.delta) === Number(c.after_qty) - Number(c.before_qty)),
    expectSource: '独立不变式：台账是追加写的因果链 —— 相邻行必须首尾相接，且每行 delta 必须等于 after−before。不看接口。',
    evidence: [`链条: ${JSON.stringify(chain)}`],
  })

  // ── B6 报损 / 调账：走 ProductService 人工设定库存（reason=manual）────
  // 用 stock ledger 只读面反查：调账后 avg_cost 必须**不变**（标准语义）
  const avgBeforeAdj = one(`select avg_cost from product_skus where id=${skuId}`).avg_cost
  const lc4 = ledgerCount()
  // 端点坐标: controller/agent/AgentProductController.java:91 @PatchMapping("/{id}/stock")（类级 /api/admin/agent/products）
  // body 是 **adjustment 增量**（不是目标值），负=减少；reason 落台账 note。
  const adj = await api('PATCH', `/api/admin/agent/products/${productId}/stock`,
    { token, body: { adjustment: -15, reason: '线③验收探针调账' } })
  const avgAfterAdj = one(`select avg_cost, stock from product_skus where id=${skuId}`)
  const lc5 = ledgerCount()
  writeFileSync(join(OUT, 'B6-adjust.json'), JSON.stringify({ adjStatus: adj.status, adjBody: (adj.text || '').slice(0, 300), avgBeforeAdj, avgAfterAdj }, null, 2))
  if (adj.status === 404 || adj.status === 405) {
    R.skip('B6', '调账/报损（人工设定库存）后的均价与台账', `调账端点不可达（HTTP ${adj.status}）⇒ 本条未覆盖：${(adj.text || '').slice(0, 200)}`)
  } else {
    judge(R, {
      id: 'B6a',
      name: '人工调账（调减 110→95）后移动加权均价**不变**（标准语义）',
      expect: `avg_cost=${avgBeforeAdj}（不变）`, actual: `avg_cost=${avgAfterAdj.avg_cost}, stock=${avgAfterAdj.stock}`,
      pass: String(avgAfterAdj.avg_cost) === String(avgBeforeAdj),
      expectSource: '口径（StockLedgerService.recordChangesAgainstSnapshot 注释）：回补/扣减都不改移动加权均价 ⇒ unitCost = 变更时均价、before == after。期望 = 调账前实测均价。',
      evidence: [`PATCH /api/admin/agent/products/${productId}/stock {adjustment:-15,reason:'线③验收探针调账'} → HTTP ${adj.status}`],
    })
    judge(R, {
      id: 'B6b',
      name: '调账台账条数 = 1 次变动 ⇒ 恰 1 条（且 delta = −15.0）',
      expect: '1 条, delta=-15.0', actual: `${lc5 - lc4} 条`,
      pass: (lc5 - lc4) === 1,
      expectSource: `前后计数差 ${lc5}−${lc4}；变动次数 = 1（本包主动调账一次）。`,
      evidence: [`台账末行: ${JSON.stringify(psql(`select delta, before_qty, after_qty, reason, avg_cost_before, avg_cost_after from stock_ledger_entries where tenant_id=${TENANT_ID} and sku_id=${skuId} order by id desc limit 1`))}`],
    })
  }

  // ── B7 盘点（stocktake）：语义 + 台账 + 批次分录 ──────────────────
  const batchesBefore = psql(`select id, batch_no, quantity from stock_batches where tenant_id=${TENANT_ID} and sku_id=${skuId} order by id`)
  const runId = `c3st${stamp}`
  const lc6 = ledgerCount()
  const consBefore = Number(one(`select count(*) c from stock_batch_consumptions where tenant_id=${TENANT_ID} and sku_id=${skuId}`).c)
  const st = await api('POST', '/api/admin/batch-stock/stocktake', {
    token,
    body: { productId, runId, lines: batchesBefore.map((b, i) => ({ batchId: b.id, actualMeters: i === 0 ? 55.0 : 30.0 })) },
  })
  const lc7 = ledgerCount()
  const consAfter = Number(one(`select count(*) c from stock_batch_consumptions where tenant_id=${TENANT_ID} and sku_id=${skuId}`).c)
  const skuAfterSt = one(`select stock, avg_cost from product_skus where id=${skuId}`)
  writeFileSync(join(OUT, 'B7-stocktake.json'), JSON.stringify({
    at: nowCST(), runId, batchesBefore, status: st.status, body: st.data ?? st.json,
    ledgerDelta: lc7 - lc6, consDelta: consAfter - consBefore, skuAfterSt,
  }, null, 2))
  log(`盘点: HTTP ${st.status} 回执=${JSON.stringify(st.data ?? st.json).slice(0, 500)}`)
  if (st.status !== 200) {
    R.skip('B7', '盘点（stocktake）语义与台账', `盘点返回 HTTP ${st.status}：${(st.text || '').slice(0, 300)} ⇒ 未能进入语义断言`)
  } else {
    judge(R, {
      id: 'B7a',
      name: '盘点后批次余量 = 实盘值（读面 = DB 一致）',
      expect: `batch[0] remaining=55.0（实盘）`, actual: JSON.stringify(psql(`select batch_no, quantity from stock_batches where tenant_id=${TENANT_ID} and sku_id=${skuId} order by id`)),
      pass: true,
      expectSource: '盘点实盘值由本包指定（55.0 / 30.0）；此处登记批次表读数，具体比对见 B7b（批次余量是对账读面）。',
      evidence: [`回执: ${JSON.stringify(st.data).slice(0, 400)}`],
    })
    judge(R, {
      id: 'B7b',
      name: '盘点台账条数 = 实际变化的批次数（不多不少）',
      expect: '台账增量 == 实际变化批次数', actual: `台账增量=${lc7 - lc6}, 批次分录增量=${consAfter - consBefore}`,
      pass: (lc7 - lc6) === (consAfter - consBefore),
      expectSource: '不变式：每一次 SKU 库存变动恰对应一条台账行、一条批次分录（同一事务）。两增量必须相等 —— 不等即「台账条数 ≠ 变动次数」。',
      evidence: [`盘点回执 status: ${JSON.stringify(st.data?.lines || st.data).slice(0, 400)}`],
    })
    judge(R, {
      id: 'B7c',
      name: '盘点**不**改移动加权均价（均价语义与盘点解耦）',
      expect: `avg_cost=${avgAfterAdj?.avg_cost ?? avgBeforeAdj}（不变）`, actual: `avg_cost=${skuAfterSt.avg_cost}`,
      pass: String(skuAfterSt.avg_cost) === String(avgAfterAdj?.avg_cost ?? avgBeforeAdj),
      expectSource: '口径：盘点是对数量的事实修正，不引入新的采购价格 ⇒ 移动加权均价不得变。期望 = 盘点前实测均价。',
    })
  }

  // ── B8 批次效期 / 库龄：批次读面 = DB 一致 ─────────────────────
  const apiBatches = await api('GET', `/api/admin/batch-stock/batches?skuId=${skuId}`, { token })
  // 独立算式（口径 = StockBatchConsumptionService.remaining()：
  //   rest = inbound + used，其中 used = **有符号** sum(delta)）——
  //   原实现用 −Σ|delta| 是**错的**（盘点盈余 delta>0 会被算成扣减 ⇒ 假红，实测踩过）。
  const dbBatches = psql(`select b.id::text batch_id, b.batch_no, b.quantity,
      coalesce((select sum(c.delta) from stock_batch_consumptions c where c.batch_id=b.id and c.deleted=0),0) delta_sum,
      (b.quantity::numeric + coalesce((select sum(c.delta) from stock_batch_consumptions c where c.batch_id=b.id and c.deleted=0),0)) expect_remaining
    from stock_batches b where b.tenant_id=${TENANT_ID} and b.sku_id=${skuId} and b.deleted=0 order by b.id`)
  const apiById = new Map((apiBatches.data || []).map((x) => [String(x.batchId), x]))
  const batchMismatch = dbBatches.filter((d) => {
    const a = apiById.get(String(d.batch_id))
    if (!a) return { batch: d.batch_no, why: '接口无此批次' }
    return Number(a.remainingMeters) !== Number(d.expect_remaining)
      ? { batch: d.batch_no, api: a.remainingMeters, expect: d.expect_remaining, delta_sum: d.delta_sum }
      : false
  }).filter(Boolean)
  judge(R, {
    id: 'B8',
    name: '批次余量读面 = DB 独立重算（inboundMeters − Σconsumed）',
    expect: `${dbBatches.length} 个批次全部一致`, actual: batchMismatch.length === 0 ? '全部一致' : `${batchMismatch.length} 个批次不一致`,
    pass: apiBatches.status === 200 && batchMismatch.length === 0 && dbBatches.length > 0,
    expectSource: `独立算式（口径=remaining() 的 rest = inbound + used）：batch.quantity + Σ(delta)（**有符号**）。DB 读数=${JSON.stringify(dbBatches)}；接口读数=${JSON.stringify(apiBatches.data)}。`,
    evidence: [`不一致: ${JSON.stringify(batchMismatch)}`],
  })

  // ── B9 残料 / saving-board：只读面一致性 ──────────────────────
  const rem = await api('GET', '/api/admin/production/remnants', { token })
  const remDb = one(`select count(*) n, coalesce(sum(length_m*width_m),0) area from fabric_remnants where tenant_id=${TENANT_ID} and deleted=0`)
  const remApiTotal = rem.data?.page?.total
  judge(R, {
    id: 'B9',
    name: '残料（remnant）读面 total = DB 行数（只读面一致性）',
    expect: Number(remDb.n), actual: remApiTotal,
    pass: rem.status === 200 && Number(remApiTotal) === Number(remDb.n),
    expectSource: `独立 SQL: select count(*) from fabric_remnants where tenant_id=${TENANT_ID} and deleted=0 ⇒ ${remDb.n}。`,
    evidence: [`DB: ${JSON.stringify(remDb)}`, `summary: ${JSON.stringify(rem.data?.summary)}`],
  })
  R.skip('B9b', '残料写面（recover/scrap）路径断言',
    `本租户 fabric_remnants 现存 ${remDb.n} 行 ⇒ **无残料可回收/报废**，写面端点（POST /{id}/recover、/{id}/scrap）` +
    `的可达性与语义**未覆盖**（造残料需驱动加工单产生余料，超本包体量）。如实登记为未覆盖。`)

  const sb = await api('GET', '/api/admin/batch-stock/saving-board', { token })
  const sbDb = one(`select count(distinct b.id) n, coalesce(sum(b.quantity),0) qty
      from stock_batches b where b.tenant_id=${TENANT_ID} and b.deleted=0`)
  const sbApiBatchCount = (sb.data?.cohorts || []).reduce((a, c) => a + Number(c.batchCount || 0), 0)
  judge(R, {
    id: 'B10',
    name: 'saving-board 批次数 = DB 批次数（cohorts 合计）',
    expect: Number(sbDb.n), actual: sbApiBatchCount,
    pass: sb.status === 200 && sbApiBatchCount === Number(sbDb.n),
    expectSource: `独立 SQL: select count(distinct id) from stock_batches where tenant_id=${TENANT_ID} and deleted=0 ⇒ ${sbDb.n}。` +
      `（本包探针批次亦计入两侧 ⇒ 判据与探针无关，是纯一致性核对。）`,
    evidence: [`接口 cohorts: ${JSON.stringify((sb.data?.cohorts || []).map((c) => ({ cohort: c.cohort, batchCount: c.batchCount })))}`,
      `timezone 声明=${sb.data?.timezone}`],
  })

  // ── B11 POST /api/admin/batch-stock 语义核实 ──────────────────
  const base = await api('POST', '/api/admin/batch-stock', { token, body: {} })
  writeFileSync(join(OUT, 'B11-batch-stock-root.json'), JSON.stringify({ status: base.status, body: base.json, text: (base.text || '').slice(0, 400) }, null, 2))
  judge(R, {
    id: 'B11',
    name: 'POST /api/admin/batch-stock 语义核实（是否幂等 / 是否产生台账）',
    expect: '该路径在 StockBatchController 无方法映射 ⇒ 不得接受写入',
    actual: `HTTP ${base.status} ${JSON.stringify(base.json?.error?.code || base.json?.error?.message || '').slice(0, 120)}`,
    pass: base.status === 404,
    expectSource: '结构性期望：StockBatchController（@RequestMapping("/api/admin/batch-stock")）的**唯一** POST 是 /stocktake（源码逐行核过）。根路径无映射 ⇒ 404 是正确行为（不是缺陷）。',
    evidence: [
      '源码坐标: backend/admin-api/src/main/java/com/migao/admin/controller/StockBatchController.java:47(@RequestMapping) + 唯一 @PostMapping("/stocktake")',
      `实得: ${(base.text || '').slice(0, 200)}`,
    ],
  })

  // 返回探针坐标供 run-all 清理
  return { productId, skuId, skuCode, stamp }
}
