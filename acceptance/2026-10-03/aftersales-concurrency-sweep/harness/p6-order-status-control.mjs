// p6-order-status-control —— **正对照**：订单侧并发改状态（CAS 守卫在位）vs 售后工单侧（无守卫）
// 用法：API_BASE=http://127.0.0.1:8080 node p6-order-status-control.mjs
//
// 为什么必须有这条：C2/C21/C23 判的是售后工单侧「并发写入重复生效」。只有同族里给出**会绿的对照**，
// 才能证明「并发到得了、判据会红也 loosens 会绿」——即读数不是恒红，也不是装置故障。
// 订单侧的实现（`OrderService.transitionStatusAtomic`：WHERE status = <旧值> 的条件更新 + rows==0 ⇒ 422）
// 与售后侧（`AfterSalesTicketService.updateTicketStatus`：updateById，WHERE 仅 id）**同一仓、同一形态**，
// 但一个有谓词、一个没有 ⇒ 天然对照。
import { writeFileSync } from 'node:fs'
import {
  api, adminToken, psql, outPath, log, nowCST, Recorder, raceStart, overlapEvidence,
  orderRow, qtyEq, TENANT_ID,
} from './lib.mjs'

const R = new Recorder('B6-order-status-control.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)
const setOrderStatus = (id, status) => api('PUT', `/api/admin/orders/${id}/status`, { token, body: { status } })
const brief = (r) => ({ status: r?.status, code: r?.bookErr?.code, msg: r?.bookErr?.message || (r?.json?.success ? 'ok' : undefined) })
const runtime = (await import('./lib.mjs'))
const mkProduct = (tag, opts = {}) => runtime.createProbeProduct(token, { tag, ...opts })
const mkOrder = (p, tag, pay = true, qty = 1, unitPrice = 100) =>
  runtime.createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty, unitPrice, tag })

const N = 4
const rounds = []
for (let rd = 1; rd <= 3; rd++) {
  const p = await mkProduct(`OC${rd}`, { allowRestock: false, stock: 100, price: 100 })
  const o = await mkOrder(p, `OC${rd}`, true, 1, 100)   // confirmed
  await Promise.all([1, 2, 3].map(() => api('GET', `/api/admin/orders/${o.orderId}`)))
  const race = await raceStart(N, () => setOrderStatus(o.orderId, 'producing'))
  const ov = overlapEvidence(race)
  const ok = race.results.filter((r) => r.out?.status === 200).length
  const row = orderRow(o.orderId)
  rounds.push({
    round: rd, N, okCount: ok, statuses: race.results.map((r) => r.out?.status),
    msgs: race.results.map((r) => brief(r.out).msg), dbStatus: row?.status,
    perRequest: race.results.map((r, i) => ({ i, ...brief(r.out), durMs: r.durMs })),
    expectation: 'N 路并发 confirmed→producing ⇒ 恰 1 次 200（其余 422「订单状态已并发变更，请刷新后重试」）；DB 终态 producing',
    pass: ov.overlapped && ok === 1 && row?.status === 'producing',
    overlapEvidence: ov,
  })
}
const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
const allPass = rounds.every((r) => r.pass)
R.add('LB-CTRL-ORDER-STATUS-CAS',
  `正对照：订单侧并发改状态（confirmed→producing）N=${N}×3 轮 ⇒ 恰 1 个赢家（DB 谓词守卫在位）`,
  allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
  `三轮成功数=${JSON.stringify(rounds.map((r) => r.okCount))}；逐轮状态码=${JSON.stringify(rounds.map((r) => r.statuses))}；DB 终态=${JSON.stringify(rounds.map((r) => r.dbStatus))}`,
  [`期望来源: 本包独立算式 + 源码 —— backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java 的 updateOrderStatus ⇒ transitionStatusAtomic(id, currentStatus, status, null)，其 wrapper = eq(id).eq(status, expectedStatus).set(status, newStatus)；rows==0 ⇒ 「订单状态已并发变更，请刷新后重试」`,
   `为什么它是**对照**: 售后工单侧（AfterSalesTicketService.updateTicketStatus）在**同一时刻、同一装置**下读到 4/4 全 200（见 LB-C2/LB-C21/LB-C23）`,
   `   ⇒ 两者差别只在「落库语句有没有状态谓词」，不是「并发到不了」或「装置坏了」`,
   `重叠证据: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
   `逐请求结局: ${JSON.stringify(rounds.map((r) => r.perRequest.map((x) => [x.status, x.msg])))}`],
  { extra: { N, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })

// 同时给出「无谓词」的同形 SQL 在自建临时表上的读数（把对照量化到 SQL 层）
{
  const { guardedWrite, pgConf } = await import('./lib.mjs')
  const { execFileSync } = await import('node:child_process')
  const c = pgConf()
  const run = (withPredicate) => {
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_orderstatus;`)
    guardedWrite(`-- probe-ok\ncreate table lb_gp_orderstatus (id int primary key, status text);`)
    guardedWrite(`-- probe-ok\ninsert into lb_gp_orderstatus values (1,'confirmed');`)
    const sql = withPredicate
      ? `UPDATE lb_gp_orderstatus SET status='producing' WHERE id=1 AND status='confirmed';`
      : `UPDATE lb_gp_orderstatus SET status='producing' WHERE id=1;`
    const cmd = `for i in $(seq 1 ${N}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 -c "${sql}" >/dev/null 2>&1 & done; wait`
    execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
    const st = psql(`select status from lb_gp_orderstatus where id=1`)[0]?.status
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_orderstatus;`)
    return st
  }
  // 计数型读数：⚠️ 关键修法（**本包自曝的判据缺陷**）—— 谓词列必须**同时被本次 UPDATE 改写**，
  // 否则谓词恒真（PG 的 READ COMMITTED 会在等锁后重算谓词，但 status 一直没变 ⇒ 每次都通过）。
  // 实测（第一版）：`SET w = w+1 WHERE id=1 AND status='confirmed'` 在 N=4 并发下终值 = 4（守护"失效"），
  // 那是**我的 SQL 没改 status**，不是产品守卫无效 —— 产品那条是 SET status=<新值>（谓词列被改写）。
  const countRows = (withPredicate) => {
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_orderstatus;`)
    guardedWrite(`-- probe-ok\ncreate table lb_gp_orderstatus (id int primary key, status text, w int);`)
    guardedWrite(`-- probe-ok\ninsert into lb_gp_orderstatus values (1,'confirmed',0);`)
    const sql = withPredicate
      ? `UPDATE lb_gp_orderstatus SET w = w + 1, status = 'producing' WHERE id=1 AND status='confirmed';`
      : `UPDATE lb_gp_orderstatus SET w = w + 1, status = 'producing' WHERE id=1;`
    const cmd = `for i in $(seq 1 ${N}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 -c "${sql}" >/dev/null 2>&1 & done; wait`
    execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
    const row = psql(`select w, status from lb_gp_orderstatus where id=1`)[0]
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_orderstatus;`)
    return row
  }
  const withPred = countRows(true)
  const withoutPred = countRows(false)
  writeFileSync(outPath('B6-cas-sql.json'), JSON.stringify({ at: nowCST(), N, withPredicate: withPred, withoutPredicate: withoutPred }, null, 2))
  R.add('LB-CTRL-CAS-SQL', '正对照的 SQL 层量化：同一并发下「有状态谓词且谓词列被改写」写 1 次、「无谓词」写 N 次',
    (withPred?.w === 1 && withoutPred?.w === N) ? 'pass' : 'fail',
    `N=${N} 并发：有谓词 ⇒ w=${withPred?.w} status=${withPred?.status}（期望 w=1）；无谓词 ⇒ w=${withoutPred?.w} status=${withoutPred?.status}（期望 w=${N}）`,
    [`注入方式: **不改产品源码** —— 自建临时表 lb_gp_orderstatus 上跑 ${N} 个**独立 psql 进程**，`,
     `  ① 有谓词: UPDATE … SET w=w+1 WHERE id=1 AND status='confirmed'（= OrderService.transitionStatusAtomic 同形）`,
     `  ② 无谓词: UPDATE … SET w=w+1 WHERE id=1（= AfterSalesTicketService.updateById 同形：WHERE 仅主键）`,
     `该读数把「重复生效」量化为一次计数（不依赖任何响应时序），是 C2/C21/C23 泄漏的机制层证据`,
     `读数: 有谓词 w=${withPred?.w} / 无谓词 w=${withoutPred?.w}`,
     `⚠️ 自曝（第一版判据缺陷）: 谓词列若**不被本次 UPDATE 改写**，N=4 并发下终值同样是 4 ⇒ 该写法**无判别力**（会假红）。`,
     `   这是**本包自己的 SQL 写错**，不是产品守卫无效 —— 修法是让 SET 同时改写谓词列（与产品 set(status,newStatus) 同形）。`],
    { extra: { N, withPred, withoutPred } })
}

log(`p6 完成：${JSON.stringify(R.summary())}`)
