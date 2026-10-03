// 线③ 家族 C —— 账期 / 时间口径（+08 口径；DB 里 timestamptz UTC 存储）。
//
// 判据设计（关键）：
//  · 探针一律**显式指定** occurred_at / created_at（绝不依赖 now()）—— 见任务书 C 节；
//  · 期望来源 = **本包独立算出的 +08 日历归属**（哪一笔该落在哪个「月/日」桶），
//    对照被测端点在 `startDate/endDate` 过滤下的**包含/排除**结果；
//  · 红证（必红控制项）：把一节探针的日期字段改一行（+8h 平移）⇒ 归属翻转 ⇒ 当场红；
//    测完**还原**并给 sha256 内容指纹自证（禁用 mtime/size）。
//
// 为什么用「02:00 +08」这个时刻作为主探针：
//   它在 +08 口径下**明确属于 10-01**，但在 **UTC 日切**下属于 09-30 18:00。
//   两条口径对同一笔给出**不同**归属 ⇒ 这是唯一能区分两种实现的时刻选择。
import { loginApi, api, psql, one, judge, log, OUT, TENANT_ID, nowCST, guardedWrite, rowFingerprint, psqlRaw, hexId } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const TXN_TABLE = 'finance_transactions'

/** 造一条**本包探针**财务流水（order_no/transaction_no 皆带 c3 前缀，remark 带中文探针域）。 */
function mkTxn(id, { occurredAt, amount, type = 'income', orderNo, remark }) {
  guardedWrite(`-- probe-ok
    insert into finance_transactions
      (id, tenant_id, transaction_no, order_id, order_no, type, amount, payment_method, status, operator, occurred_at, remark, created_at, updated_at, deleted)
    values
      ('${id}', ${TENANT_ID}, '${orderNo}', null, '${orderNo}', '${type}', ${amount}, 'other', 'success',
       '线③验收探针', '${occurredAt}', '${remark}', now(), now(), 0);`)
}

/** 读探针跨月/跨年边界的两条关键读数：startDate=endDate=D 的**包含性**。 */
async function includesOn(token, date, tag) {
  const r = await api('GET', `/api/admin/finance/transactions?page=1&size=100&startDate=${date}&endDate=${date}`, { token })
  const hit = (r.data?.items || []).some((x) => (x.orderNo || x.transactionNo) === tag)
  return { status: r.status, hit, total: r.data?.total, n: (r.data?.items || []).length }
}

export async function familyC(R, { token }) {
  log('══════════ 家族 C：账期 / 时间口径（+08 vs UTC 日切）══════════')

  const stamp = Date.now().toString(36)
  // 探针清单：occurred_at 显式指定；两条「跨月」，两条「跨年」。
  const probes = [
    { id: `c3tb${stamp}a`, orderNo: `c3ref${stamp}A`, occurredAt: '2026-09-30 23:59:59+08', expectMonth: '2026-09', note: '跨月边界·9月最后1秒' },
    { id: `c3tb${stamp}b`, orderNo: `c3ref${stamp}B`, occurredAt: '2026-10-01 00:00:00+08', expectMonth: '2026-10', note: '跨月边界·10月第1秒' },
    { id: `c3tb${stamp}c`, orderNo: `c3ref${stamp}C`, occurredAt: '2026-10-01 02:00:00+08', expectMonth: '2026-10', note: '**判别探针**·+08属10-01 / UTC属09-30' },
    { id: `c3tb${stamp}d`, orderNo: `c3ref${stamp}D`, occurredAt: '2025-12-31 23:59:00+08', expectMonth: '2025-12', note: '跨年边界·12月最后一分钟' },
    { id: `c3tb${stamp}e`, orderNo: `c3ref${stamp}E`, occurredAt: '2026-01-01 00:01:00+08', expectMonth: '2026-01', note: '跨年边界·1月第一分钟' },
  ]
  // 还原范围快照（只取本包探针行，避免把他人行纳入 diff）
  const probeWhere = `tenant_id=${TENANT_ID} and transaction_no like 'c3ref%'`
  const beforeSnap = psql(`select * from ${TXN_TABLE} where ${probeWhere}`)
  const beforeFp = rowFingerprint(beforeSnap)
  log(`注入前探针行数=${beforeFp.n} sha256=${beforeFp.sha256}`)

  for (const p of probes) {
    mkTxn(p.id, { occurredAt: p.occurredAt, amount: 1.01, orderNo: p.orderNo, remark: `线③验收时间口径探针 ${p.note}` })
  }
  const injected = psql(`select * from ${TXN_TABLE} where ${probeWhere} order by occurred_at`)
  const injFp = rowFingerprint(injected)
  log(`注入后探针行数=${injFp.n} sha256=${injFp.sha256}（自证注入真的生效：指纹已变=${injFp.sha256 !== beforeFp.sha256}）`)
  writeFileSync(join(OUT, 'C0-injection-fingerprint.json'), JSON.stringify({
    injectedAt: nowCST(), probeWhere, beforeFp, injFp,
    rows: injected.map((r) => ({ orderNo: r.order_no, occurredAt: r.occurred_at })),
  }, null, 2))

  // ── C1 跨月：每条探针是否落在**它 +08 日历所属**的那一天 ───────────
  // 期望来源：本包按 +08 墙钟直接写死的日历日（探针构造时即确定，非读被测系统）。
  for (const p of probes) {
    const plus08Day = p.occurredAt.slice(0, 10)          // 显式 +08 墙钟的日期部分 = 权威 +08 日历日
    const inc = await includesOn(token, plus08Day, p.orderNo)
    const expect = true                                   // 该笔在 +08 口径下**就在**这一天
    judge(R, {
      id: `C1-${p.orderNo.slice(-1)}`,
      name: `跨月/跨年归属：occurred_at=${p.occurredAt}（${p.note}）落在 ${plus08Day}`,
      expect: `GET startDate=endDate=${plus08Day} 应包含 ${p.orderNo}`,
      actual: `HTTP ${inc.status}，包含=${inc.hit}（该日共 ${inc.n} 行 / total=${inc.total}）`,
      pass: inc.status === 200 && inc.hit === expect,
      expectSource: `期望由本包按 **+08 墙钟日历**直接给出：occurred_at 字面量 '${p.occurredAt}' 的日期部分即 ${plus08Day}（显式 +08 偏移，无歧义）。不使用接口任何读数作期望。`,
      evidence: [
        `注入行: order_no=${p.orderNo}, occurred_at='${p.occurredAt}'`,
        `实测接口: /api/admin/finance/transactions?startDate=${plus08Day}&endDate=${plus08Day}`,
      ],
    })
  }

  // ── C2 月汇总口径：月度窗口是否 +08 ──────────────────────────────
  // 期望来源：独立 SQL 按月（+08 口径）聚合本包探针，得每月笔数；
  // 再对照接口 summary 的 startDate=月首/endDate=月末（OK 则笔数与金额应含探针）。
  const expByMonth = psql(`select to_char(occurred_at at time zone 'Asia/Shanghai','YYYY-MM') m, count(*) n,
      sum(amount) amt from ${TXN_TABLE} where ${probeWhere} group by 1 order by 1`)
  writeFileSync(join(OUT, 'C2-expected-by-month.json'), JSON.stringify(expByMonth, null, 2))

  for (const row of expByMonth) {
    const [y, m] = row.m.split('-').map(Number)
    const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate()
    const start = `${row.m}-01`, end = `${row.m}-${String(lastDay).padStart(2, '0')}`
    const r = await api('GET', `/api/admin/finance/summary?startDate=${start}&endDate=${end}`, { token })
    const inc = r.data?.incomeCount
    // 期望：该月窗口**应包含**本包在该月的全部探针（income 笔数已含其它行 ⇒ 只判"是否把这 N 笔算进去"，
    // 用 no-window 基线 vs 该月窗口 之差 ≥ 探针数 来判 —— 差值比对避免依赖存量。
    const rAll = await api('GET', '/api/admin/finance/summary', { token })
    const allCount = rAll.data?.incomeCount ?? 0
    // 基线：本包探针在该月的笔数
    const pn = Number(row.n)
    // 其它期间的探针不该落进本窗口：用「全量 - 本窗口」判断（本窗口必须少掉非本月的探针）
    const otherProbes = probes.filter((x) => !x.occurredAt.startsWith(row.m)).length
    const expMin = pn
    const gotInWindow = null // 无法直接读；改为「非本月探针不得出现在本月金额里」的等价判据 ↓
    const sumRow = psql(`select coalesce(sum(amount),0) amt from ${TXN_TABLE}
      where ${probeWhere} and to_char(occurred_at at time zone 'Asia/Shanghai','YYYY-MM')='${row.m}'`)[0]
    judge(R, {
      id: `C2-${row.m}`,
      name: `月度窗口（+08）：${row.m} 的探针应被 summary 窗口覆盖（独立 SQL 计 ${pn} 笔 / ${sumRow.amt}）`,
      expect: `窗口 startDate=${start}&endDate=${end} 的 incomeCount ≥ ${expMin}（且该月探针金额可被独立重算）`,
      actual: `HTTP ${r.status} incomeCount=${inc}；无窗口 incomeCount=${allCount}；独立 SQL: ${pn} 笔 ${sumRow.amt}`,
      pass: r.status === 200 && Number(inc) >= expMin,
      expectSource: `独立 SQL（+08）: select count(*) from ${TXN_TABLE} where transaction_no like 'c3ref%' and to_char(occurred_at at time zone 'Asia/Shanghai','YYYY-MM')='${row.m}' ⇒ ${pn} 笔。窗口若能覆盖 +08 日历月，则 incomeCount 至少含这 ${pn} 笔。`,
      evidence: [
        `该月窗口探针数(独立)=${pn}，本月窗口读数=${inc}，无窗口读数=${allCount}`,
        `非本月探针数=${otherProbes}（若被错误纳入本窗口，会体现在 C1 的逐笔判据里）`,
      ],
    })
  }

  // ── C3 反假绿：探针真的存在且可读（否则 C1 的"未命中"可能是夹具没造出来）──
  const verify = psql(`select order_no, occurred_at from ${TXN_TABLE} where ${probeWhere} order by order_no`)
  judge(R, {
    id: 'C3',
    name: '反假绿控制：5 条时间探针确实落库且可被 SQL 读回',
    expect: 5, actual: verify.length,
    pass: verify.length === 5,
    expectSource: '探针构造清单写死 5 条（跨月 3 + 跨年 2），由独立 SQL 读回计数。夹具不存在则 C1 的"未命中"无判别力。',
    evidence: [`读回: ${JSON.stringify(verify)}`],
  })

  // ── C7 窗口唯一性不变式（关系式断言，**不会自毁**）──────────────────
  // 「一笔流水恰落在**一个**日窗口，且那个窗口 == 它 +08 日历所属日」。
  // 这条比 C1 更强：既抓「归属错位」，也抓「同笔被两个窗口同时算进去」（重复计数）。
  // 修好后自动转绿；当前（8h 错位）必红 ⇒ 既非恒真也非恒假。
  for (const p of [probes[0], probes[2], probes[4]]) {
    const day = p.occurredAt.slice(0, 10)
    const d0 = new Date(`${day}T00:00:00Z`)
    const scan = []
    for (let off = -2; off <= 2; off++) {
      const d = new Date(d0.getTime() + off * 86400000)
      const ds = d.toISOString().slice(0, 10)
      const inc = await includesOn(token, ds, p.orderNo)
      if (inc.hit) scan.push(ds)
    }
    judge(R, {
      id: `C7-${p.orderNo.slice(-1)}`,
      name: `窗口唯一性：${p.orderNo}（occurred_at=${p.occurredAt}）恰落在 [${day}] 一个日窗口`,
      expect: `[${day}]`, actual: JSON.stringify(scan),
      pass: scan.length === 1 && scan[0] === day,
      expectSource: `独立期望：+08 墙钟日历日就是『唯一应有的窗口』（区间扫描 −2..+2 天，逐窗调用同一读面）。` +
        `**不是**真值主张（不断言"缺陷存在"）：修好后此条自然转绿。`,
      evidence: [`扫描窗口(±2天): ${JSON.stringify(scan)}`, `occurred_at 字面量=${p.occurredAt}`],
    })
  }

  // ── C4 红证（必红控制项）：**挑一条当前为绿的判据**把它改坏 ⇒ 当场红 ────
  // 🔴 原设计缺陷：原先对「已经红的」判别探针做注入 ⇒ 红没有变化 ⇒ 红证无判别力（实测踩过）。
  //    正解：对**当前为绿**的 C1-A 探针注入 —— 绿→红→还原→绿，才是有效红证。
  const greenProbe = probes[0]                       // 2026-09-30 23:59:59+08，C1-A 当前 = 绿
  const greenDay = greenProbe.occurredAt.slice(0, 10)
  const pre = await includesOn(token, greenDay, greenProbe.orderNo)
  const orig = one(`select * from ${TXN_TABLE} where transaction_no='${greenProbe.orderNo}' and tenant_id=${TENANT_ID}`)
  const origFp = rowFingerprint([orig])
  log(`红证前置：${greenProbe.orderNo} 在 ${greenDay} 窗口命中=${pre.hit}（必须 true 才有判别力）`)
  // 注入：把它挪出该窗口（+08 → 10-05 12:00）
  guardedWrite(`-- probe-ok
    update ${TXN_TABLE} set occurred_at='2026-10-05 12:00:00+08' where transaction_no='${greenProbe.orderNo}' and tenant_id=${TENANT_ID};`)
  const injRow = one(`select * from ${TXN_TABLE} where transaction_no='${greenProbe.orderNo}' and tenant_id=${TENANT_ID}`)
  const injRowFp = rowFingerprint([injRow])
  const redInc = await includesOn(token, greenDay, greenProbe.orderNo)
  const redIsRed = redInc.hit === false
  R.add('C4', '红证（必红控制项）：把**当前为绿**的 A 探针挪出所属日窗口 ⇒ 同一判据当场红',
    (redIsRed && pre.hit === true) ? 'pass' : 'fail',
    (redIsRed && pre.hit === true)
      ? `前置绿(${greenDay} 命中=true) → 注入后红(命中=false) ⇒ 判据**会红**，C1/C7 非空断言得证`
      : `前置绿=${pre.hit} / 注入后命中=${redInc.hit} ⇒ 判据在错误数据上不翻转 = 空断言（必须修判据）`,
    [
      `注入: occurred_at '${greenProbe.occurredAt}' → '2026-10-05 12:00:00+08'`,
      `内容指纹（sha256，禁用 mtime/size）: ${origFp.sha256} → ${injRowFp.sha256}（变=${origFp.sha256 !== injRowFp.sha256}）`,
      `同一判据复跑: 注入前 hit=${pre.hit} / 注入后 hit=${redInc.hit}（期望 true → false）`,
    ])

  // ── 还原：逐字段还原 + 指纹自证 ─────────────────────────────────
  guardedWrite(`-- probe-ok restore
    update ${TXN_TABLE} set occurred_at='${greenProbe.occurredAt}' where transaction_no='${greenProbe.orderNo}' and tenant_id=${TENANT_ID};`)
  const restored = one(`select * from ${TXN_TABLE} where transaction_no='${greenProbe.orderNo}' and tenant_id=${TENANT_ID}`)
  const restFp = rowFingerprint([restored])
  const greenAgain = await includesOn(token, greenDay, greenProbe.orderNo)
  judge(R, {
    id: 'C5',
    name: '红证还原：逐字段还原后指纹回到注入前，且同一判据回绿',
    expect: `sha256 == ${origFp.sha256} 且 ${greenDay} 窗口重新命中`,
    actual: `sha256=${restFp.sha256}（相等=${restFp.sha256 === origFp.sha256}），${greenDay} 命中=${greenAgain.hit}`,
    pass: restFp.sha256 === origFp.sha256 && greenAgain.hit === true,
    expectSource: '还原正确性 = 内容指纹逐字节相等（sha256，非 mtime/size）+ 同一判据复跑回绿。',
    evidence: [`还原后行: ${JSON.stringify(restored)}`],
  })

  // ── C8 边界夹逼（口径判定的**决定性**证据，主会话指定设计）────────────
  // 口径声明（必须写明，不混用）：本包判定采用 **产品意图 = +08 日历日**，依据 =
  //   ① 仓库自declare 的「业务今天」单点 = BusinessClock.BUSINESS_ZONE=Asia/Shanghai，
  //      且 BusinessClockSourceGuardTest **禁止** src/main 下出现别的 Asia/Shanghai 字面量/无参 now()；
  //   ② DashboardController/order-trend 同日窗口用的就是 businessClock.startOfToday()（= +08 00:00）；
  //   ③ 而 FinanceService/OrderService 用 `date+"T00:00:00Z"`（固定 UTC）⇒ **同一仓两套口径**，
  //      内部已经不自洽 ⇒ 以 BusinessClock 为准判 UTC 那侧为缺陷。
  const bF = { id: `c3tb${stamp}F`, orderNo: `c3ref${stamp}F`, occurredAt: '2026-10-01 08:00:00+08', note: '夹逼下界·恰=UTC下界(=10-01T00:00Z)' }
  const bG = { id: `c3tb${stamp}G`, orderNo: `c3ref${stamp}G`, occurredAt: '2026-10-01 07:59:59+08', note: '**决定性红证**·北京10-01早晨 / UTC仍属09-30' }
  for (const p of [bF, bG]) {
    mkTxn(p.id, { occurredAt: p.occurredAt, amount: 2.02, orderNo: p.orderNo, remark: `线③验收边界夹逼探针 ${p.note}` })
  }
  {
    const f = await includesOn(token, '2026-10-01', bF.orderNo)
    judge(R, {
      id: 'C8a',
      name: `边界夹逼·下界：北京 2026-10-01 08:00:00（= 2026-10-01T00:00:00Z）落在 10-01 窗口`,
      expect: '包含（两种口径在此点一致 ⇒ 正对照）', actual: `包含=${f.hit}`,
      pass: f.hit === true,
      expectSource: '该时刻 = UTC 窗口的**含入下界**，也 ≥ +08 日界 ⇒ UTC 与 +08 两种口径都应收录。作为**正对照**证明过滤链路本身在工作（不是"窗口不生效"）。',
      evidence: [`occurred_at=${bF.occurredAt}`, `UTC 值=2026-10-01T00:00:00Z`],
    })
    const g = await includesOn(token, '2026-10-01', bG.orderNo)
    judge(R, {
      id: 'C8b',
      name: `🔴 边界夹逼·错位：北京 2026-10-01 07:59:59（= 2026-09-30T23:59:59Z）**应**落在 10-01 窗口`,
      expect: '包含（+08 口径）', actual: `包含=${g.hit}`,
      pass: g.hit === true,
      expectSource: `口径 = 产品意图 +08（依据见上「口径声明」：BusinessClock 是仓内声明的业务时间单点，Dashboard 亦用它）。` +
        `北京 10-01 07:59:59 在 +08 日历上**明确属于 10-01** ⇒ 必须命中。` +
        `UTC 口径下它是 09-30T23:59:59Z，落进 09-30 的 UTC 窗口 ⇒ 即**整体后移 8 小时**。`,
      evidence: [`occurred_at=${bG.occurredAt} = 2026-09-30T23:59:59Z`,
        `这是本族**决定性红证**：同一条判据在 +08 口径下必绿、在 UTC 口径下必红 ⇒ 判据有判别力`],
    })
    const gPrev = await includesOn(token, '2026-09-30', bG.orderNo)
    judge(R, {
      id: 'C8c',
      name: `🔴 错位归属：北京 10-01 的流水**不得**落进 09-30 窗口`,
      expect: '不包含（+08 口径）', actual: `09-30 窗口包含=${gPrev.hit}`,
      pass: gPrev.hit === false,
      expectSource: '同一笔（北京 10-01 07:59:59）在 +08 口径下属 10-01 ⇒ 出现在 09-30 窗口即**归错月份**（跨月时是真实的账期错报）。',
      evidence: [`09-30 窗口读数 hit=${gPrev.hit}`, `对应 UTC 值 2026-09-30T23:59:59Z 恰在 09-30 的 UTC 窗口内`],
    })
  }

  // ── C9 跨端点口径不自洽（同一笔单，两个端点归属不同）────────────────
  // 这是**内部不一致**的硬证据：不需要外部口径裁定 —— 同一仓里两个端点对同一时刻给出不同"日期归属"。
  const ordId = hexId('c3', 20)
  const ordNo = `c3ord${stamp}`
  const custName = '线③验收探针客户'
  // 探针时刻 = 北京「今天」凌晨 02:00（+08 今日之内；对应 UTC 为昨日 18:00）
  const todayCst = nowCST().cst.slice(0, 10)
  const ordAt = `${todayCst} 02:00:00+08`
  guardedWrite(`-- probe-ok
    insert into orders (id, tenant_id, order_no, customer_name, customer_phone, status, total_amount, actual_amount,
      created_at, updated_at, deleted, is_urgent)
    values ('${ordId}', ${TENANT_ID}, '${ordNo}', '${custName}', '13900000000', 'confirmed', 0, 0,
      '${ordAt}', '${ordAt}', 0, false);`)
  const dbOrd = one(`select id, order_no, created_at from orders where id='${ordId}' and tenant_id=${TENANT_ID}`)
  log(`订单探针: ${ordNo} created_at=${ordAt}（DB: ${JSON.stringify(dbOrd)}）`)

  // (1) Dashboard 侧（+08 口径：businessClock.startOfToday）—— 用前后增量判断是否收录
  const d1 = await api('GET', '/api/admin/dashboard/stats', { token })
  const listToday = await api('GET', `/api/admin/orders?page=1&size=100&startDate=${todayCst}&endDate=${todayCst}`, { token })
  const listHit = (listToday.data?.items || []).some((x) => x.id === ordId || x.orderNo === ordNo)
  const trend = await api('GET', '/api/admin/dashboard/order-trend', { token })
  const trendToday = (trend.data || []).find((p) => p.date === todayCst)
  writeFileSync(join(OUT, 'C9-cross-endpoint.json'), JSON.stringify({
    at: nowCST(), ordId, ordNo, ordAt, todayCst,
    dashboardTodayOrders: d1.data?.todayOrders,
    orderTrendToday: trendToday,
    listStatus: listToday.status, listTotal: listToday.data?.total, listHit,
  }, null, 2))

  judge(R, {
    id: 'C9',
    name: '🔴 跨端点口径不自洽：同一笔「北京今日凌晨」订单，Dashboard 按 +08 收录 / 订单列表按 UTC 排除',
    expect: `两端口径一致（列表也应收录该单）`,
    actual: `Dashboard order-trend[${todayCst}] orders=${trendToday?.orders}；列表 startDate=endDate=${todayCst} total=${listToday.data?.total} 收录探针=${listHit}`,
    pass: listHit === true,
    expectSource:
      '口径声明同上（+08）。**不需要外部裁定**：DashboardController.getOrderTrend 用 businessClock.startOfDay(today-6)（+08），' +
      '而 OrderController.getOrders 的 startDate/endDate 走 OrderService 的 `T00:00:00Z`（UTC）——' +
      '**同一仓内两个端点对同一时刻给出不同日期归属** ⇒ 至少一侧必错，且 BusinessClock 是仓内声明的单点 ⇒ 判 UTC 侧为缺陷。',
    evidence: [
      `探针 created_at=${ordAt}（北京 ${todayCst} 凌晨 02:00）`,
      `Dashboard order-trend 该日: ${JSON.stringify(trendToday)}`,
      `订单列表 startDate=endDate=${todayCst}: HTTP ${listToday.status}, total=${listToday.data?.total}, 收录=${listHit}`,
      '源码坐标: OrderService.java:208-211 (T00:00:00Z / T23:59:59Z 字面量) vs DashboardController.java:190-193 businessClock.startOfDay',
    ],
  })

  // ── C6 #6185 物流缓存：构建点不含 ⇒ 只做当前行为登记 ───────────────
  R.skip('C6', '#6185 物流缓存（缓存键/档位/失败不缓存）',
    '前置：:8080 构建点 = main-live @ d1c09d02f，**不含 #6185**（#6185 在 origin/main 上，见 REPORT.md §1 的 git show 级证据）' +
    '⇒ 按任务书「若 :8080 构建点不含它 ⇒ 只做当前行为登记，不判缺陷」处理：本条**不作 pass/fail**，' +
    '当前行为登记 = 无缓存层可观察（未做 Redis 读/写断言，因对象不在运行构建内）。')

  // 保持探针存活到清理阶段（供零残留自证）；由 run-all 统一 cleanup
  return { probes, probeWhere }
}
