// 线③ 独立复现（**本线自建工装**，不改任何既有 harness）：入库单「过账 × 作废」严格同时起跑的交叉竞态。
// 目标：给出**独立于 race-sweep harness** 的时间线 + 库侧读数，用来把 W2 的归因强度钉住
//   （谁先提交、200 回执对应什么库侧事实、台账是否留下来）。
// 纪律：写操作只碰本脚本自建的探针入库单（remark 前缀 lb3-race）；只读其它表。
import { api, loginApi, psql, nowCST, log } from '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-04/aftersales-refund-sweep/harness/lib.mjs'

const TENANT = Number(process.env.TENANT_ID || 32)
const PHONE = process.env.ADMIN_PHONE || '13800138000'
const SKU_ID = process.env.SKU_ID   // 探针 SKU（race-sweep-A1）
const OUT = []

const cst = () => new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }) + ' +08'
const ms = () => Date.now()

const l = await loginApi(PHONE, process.env.SMS_CODE || '123456')
const TOK = l.token
log(`[独立复现] 登录 tenant=${l.raw?.user?.tenantId}（期望 ${TENANT}）`)

const skuBefore = psql(`select stock from product_skus where id=${SKU_ID}`)[0]
const stockBefore = Number(skuBefore.stock)
log(`[独立复现] SKU ${SKU_ID} 起始库存 = ${stockBefore}`)

// ① 建草稿入库单（探针对象）
const cr = await api('POST', '/api/admin/inbound-orders', { token: TOK, body: {
  supplier: 'lb3-race-supplier', warehouse: 'lb3-race-wh', source: 'purchase',
  remark: `lb3-race-${ms()}`,
  items: [{ productId: process.env.PRODUCT_ID, skuId: String(SKU_ID), quantity: '5.0', unitCost: 5.0, dyeLot: 'lb3-race-lot' }],
} })
if (cr.status !== 200) { console.error('建单失败', cr.status, cr.text.slice(0, 400)); process.exit(1) }
const id = cr.json.data.id
const inboundNo = cr.json.data.inbound_no ?? cr.json.data.inboundNo
log(`[独立复现] 草稿单 id=${id} no=${inboundNo}`)

// ② 严格同时起跑：post 与 cancel 同一个 microtask 门控放行
let release
const gate = new Promise((r) => { release = r })
const fire = (i) => (async () => {
  await gate
  const t0 = ms()
  const action = i === 0 ? 'post' : 'cancel'
  const r = await api('PATCH', `/api/admin/inbound-orders/${id}`, { token: TOK, body: { action, reason: 'lb3-race' } })
  const t1 = ms()
  OUT.push({ i, action, t0, t1, durMs: t1 - t0, status: r.status, body: r.text.slice(0, 240) })
})()
const tasks = [fire(0), fire(1)]
await new Promise((r) => setTimeout(r, 40))
const barrierAt = ms()
release()
await Promise.all(tasks)

// ③ 库侧现取
const row = psql(`select status, posted_at, cancelled_at, cancelled_reason, updated_at from inbound_orders where id='${id}'`)[0]
const led = psql(`select id, delta, before_qty, after_qty, reason, ref_no, created_at from stock_ledger_entries where tenant_id=${TENANT} and ref_no='${inboundNo}'`)
const stockAfter = Number(psql(`select stock from product_skus where id=${SKU_ID}`)[0].stock)

const spans = OUT.map((o) => [o.t0, o.t1])
const union = [Math.min(...spans.map((s) => s[0])), Math.max(...spans.map((s) => s[1]))]
const sumDur = OUT.reduce((a, o) => a + o.durMs, 0)
const overlap = union[1] - union[0]
const report = {
  at: cst(), tenant: TENANT, inboundId: id, inboundNo,
  barrierAtCst: new Date(barrierAt).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }),
  requests: OUT.sort((a, b) => a.i - b.i),
  overlapEvidence: {
    真实重叠: overlap < sumDur, unionMs: overlap, sumDurMs: sumDur,
    说明: '并集墙钟 < 各历时之和 ⇒ 两个请求的时间窗真有交集（非串行叙事）',
  },
  db: { status: row.status, postedAt: row.posted_at, cancelledAt: row.cancelled_at, cancelledReason: row.cancelled_reason, updatedAt: row.updated_at },
  ledgerForRef: led,
  ledgerRows: led.length,
  stockBefore, stockAfter, stockDelta: stockAfter - stockBefore,
  expectedByIndependentMath: {
    若作废胜出: { dbStatus: 'cancelled', stockDelta: 0, ledgerRows: 0 },
    若过账胜出: { dbStatus: 'posted', stockDelta: 5, ledgerRows: 1 },
    '两者都成 ⇒ 不可能一致': 'dbStatus=cancelled 且 stockDelta≠0 或 ledgerRows≠0',
  },
}
const inconsistent = []
if (OUT[0].status === 200 && row.status !== 'posted') inconsistent.push({ rule: 'post 返回 200 但库侧状态不是 posted', dbStatus: row.status })
if (OUT[1].status === 200 && row.status !== 'cancelled') inconsistent.push({ rule: 'cancel 返回 200 但库侧状态不是 cancelled', dbStatus: row.status })
if (row.status === 'cancelled' && (stockAfter - stockBefore) !== 0) inconsistent.push({ rule: '已作废的单却改了库存', delta: stockAfter - stockBefore })
if (row.status === 'cancelled' && led.length !== 0) inconsistent.push({ rule: '已作废的单却留下了入库台账行', rows: led.length })
report.inconsistent = inconsistent
report.verdict = inconsistent.length ? 'fail(产品)' : 'pass'
report.selfCheck = '本判据会红：把 cancel 换成先串行 post 再 cancel（无重叠）⇒ 应得 409 + 无台账（对照 RP3 的形态）'
console.log(JSON.stringify(report, null, 2))
