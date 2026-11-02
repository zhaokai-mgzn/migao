// 2026-10-06 省料看板「能不能看到真实省下的成本」验证
//
// 用户追问：「省料看板上能看到真实省下的成本吗？」
// 判据（每条会红）：
//   A1 台账真的落了省料（Σsaved > 0）
//   A2 看板 total.savedMeters == 台账逐行 Σsaved（**逐值相等**，不是两套口径）
//   A3 看板 total.savedAmount == Σ round(saved × unit_cost, 2)
//   A4 total.unknownCostLines == 0（成本可知 ⇒ 金额不是「无数据」）
//   A5 savedGroups 里能定位到本物料组，其米数/金额 == 台账 Σ
//   A6 页面 /production/saving-board 渲染出同一组数字（真浏览器 + DOM 文本 + 截图）
//   A7 负对照：**界面路径**（不带批次指派）的 4 单在看板上不产生任何省料（=0）
//   A8 前后对照：清理后同一查询不再出现该物料组（证明读数确实来自本轮数据）
import { api, psql, chromium, loginUi, OUT, PROBE } from './lib.mjs'
import { login, setupProbe, createOrder, assign, consumptions, cleanup, T } from './steps.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'

const stamp = String(Date.now()).slice(-6)
const t0 = Date.now()
const R = { at: new Date().toISOString(), stamp, prefix: PROBE, checks: [] }
const ck = (id, ok, detail) => { R.checks.push({ id, ok: !!ok, detail }); console.log(`${ok ? '✅' : '❌'} ${id} — ${detail}`) }
const err = (r) => (r?.json?.error?.message || r?.json?.message || r?.text || '').slice(0, 200)

const token = await login()
R.probe = await setupProbe(token, { stamp, meters: 600, unitCost: 40 })

const orders = []
for (let i = 0; i < 8; i++) orders.push(await createOrder(token, { ...R.probe, seq: `${stamp}-${i}`, idx: 900 + i }))
const uiArm = orders.slice(0, 4), apiArm = orders.slice(4)

// ── 派单：UI 体（界面真实路径） vs 带指派（能省料的路径）──
const dUi = await api('POST', '/api/admin/production/pool/dispatch', { token, body: { orderIds: uiArm.map((o) => o.orderId), batches: [], assignmentRule: null, pooled: true } })
const dApi = await api('POST', '/api/admin/production/pool/dispatch', { token, body: { orderIds: apiArm.map((o) => o.orderId), ...assign(apiArm, 'fifo'), pooled: true } })
R.dispatch = { ui: dUi.json?.data, api: dApi.json?.data }

// ── 台账逐行（真值）──
const rows = consumptions(`order_item_id in (select oi.id::text from order_items oi join orders o on o.id=oi.order_id where o.tenant_id=${T} and o.customer_name like '${PROBE}%')`)
const sum = (f) => Number(rows.reduce((a, r) => a + Number(f(r)), 0).toFixed(2))
R.ledger = { rows: rows.length, formula: sum((r) => r.formula), planned: sum((r) => r.planned), saved: sum((r) => r.saved), amount: sum((r) => Number(r.saved) * Number(r.unit_cost)) }
ck('A1-台账真的落了省料', R.ledger.saved > 0, `行数=${R.ledger.rows} Σformula=${R.ledger.formula} Σplanned=${R.ledger.planned} Σsaved=${R.ledger.saved} 米`)

// ── 看板（服务端聚合）──
const boardRes = await api('GET', '/api/admin/batch-stock/saving-board?granularity=month', { token })
const board = boardRes.json?.data
R.board = { status: boardRes.status, total: board?.total, savedGroups: (board?.savedGroups || []).map((g) => ({ period: g.period, cohort: g.cohort, skuCode: g.skuCode, savedMeters: g.savedMeters, savedAmount: g.savedAmount, lineCount: g.lineCount, unknownCostLines: g.unknownCostLines })), cohorts: (board?.cohorts || []).map((c) => ({ cohort: c.cohort, savedMeters: c.savedMeters, savedAmount: c.savedAmount, batchCount: c.batchCount })) }
if (!board) { ck('A0-看板端点可用', false, `HTTP ${boardRes.status} ${err(boardRes)}`); writeFileSync(`${OUT}/evidence/saving-board.json`, JSON.stringify(R, null, 2)); process.exit(1) }
const mine = (board.savedGroups || []).filter((g) => String(g.skuCode || '').startsWith(PROBE))
const rowsSum = (k) => Number(mine.reduce((a, g) => a + Number(g[k] ?? 0), 0).toFixed(2))
R.boardMine = { groups: mine.length, savedMeters: rowsSum('savedMeters'), savedAmount: rowsSum('savedAmount') }

ck('A2-看板米数 == 台账逐行 Σsaved', Math.abs(Number(board.total.savedMeters) - R.ledger.saved) < 0.005, `看板 total.savedMeters=${board.total.savedMeters} vs 台账 ${R.ledger.saved}`)
ck('A3-看板金额 == Σ(省料 × 当时批次均价)', Math.abs(Number(board.total.savedAmount) - R.ledger.amount) < 0.02, `看板 total.savedAmount=${board.total.savedAmount} vs 台账 ${R.ledger.amount}`)
ck('A4-成本可知（金额不是「无数据」）', Number(board.total.unknownCostLines) === 0, `unknownCostLines=${board.total.unknownCostLines}、lineCount=${board.total.lineCount}`)
ck('A5-能定位到本物料的省料组', mine.length === 1 && Math.abs(rowsSum('savedMeters') - R.ledger.saved) < 0.005, `组数=${mine.length} ${JSON.stringify(R.board.savedGroups)}`)
ck('A7-负对照·界面路径的 4 单不产生省料', R.ledger.rows === apiArm.length, `台账行数=${R.ledger.rows}（应=带指派臂的 ${apiArm.length} 单；界面臂 4 单 0 行）`)

// ── 页面（真浏览器）──
mkdirSync(`${OUT}/screenshots`, { recursive: true })
let uiText = ''
try {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  await loginUi(page, { mode: 'admin', phone: process.env.ADMIN_PHONE || '13800138000' })
  await page.goto(`${process.env.BASE_URL}/production/saving-board`, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.waitForSelector('[data-testid="saving-saved-groups"]', { timeout: 30000 })
  await page.waitForTimeout(1500)
  uiText = await page.locator('[data-testid="saving-saved-groups"]').innerText()
  R.uiText = uiText
  await page.screenshot({ path: `${OUT}/screenshots/saving-board-${stamp}.png`, fullPage: true })
  R.screenshot = `out/screenshots/saving-board-${stamp}.png`
  await browser.close()
} catch (e) { R.uiError = String(e).slice(0, 300) }
// 页面按 `formatMeters/formatMetric` 渲染 ⇒ 末位 0 会被去掉（112 元，不是 112.00 元）。
// 判据必须按**页面自己的展示口径**归一后再比 —— 拿 2 位小数比是**假红**（实测踩过：页面写「112 元」）。
const fmt = (v) => String(Number(Number(v).toFixed(2)))
const uiHasMeters = uiText.includes(fmt(R.boardMine.savedMeters))
const uiHasAmount = uiText.includes(fmt(R.boardMine.savedAmount))
ck('A6-页面渲染出看板数字（真浏览器）', !!uiText && (uiHasMeters || uiHasAmount), R.uiText ? `页面「逐单省料汇总」文本=${JSON.stringify(uiText.replace(/\s+/g, ' ').slice(0, 400))}｜含米数=${uiHasMeters} 含金额=${uiHasAmount}` : `页面读取失败：${R.uiError}`)
ck('A6b-页面确实带上省料金额（元）', uiHasAmount, `期望金额 ${fmt(R.boardMine.savedAmount)} 元（页面按 formatMetric 展示，末位 0 不补）`)

// ── 前后对照：清理后看板不再有该物料组 ──
cleanup(PROBE)
const after = (await api('GET', '/api/admin/batch-stock/saving-board?granularity=month', { token })).json?.data
const afterMine = (after?.savedGroups || []).filter((g) => String(g.skuCode || '').startsWith(PROBE))
R.after = { mineGroups: afterMine.length, totalSavedMeters: after?.total?.savedMeters, totalSavedAmount: after?.total?.savedAmount }
ck('A8-清理后看板不再出现该物料（证明读数来自本轮数据）', afterMine.length === 0, `清理后本物料组=${afterMine.length}，全租户 Σsaved=${after?.total?.savedMeters} 米 / ${after?.total?.savedAmount} 元`)
R.residue = psql(`select (select count(*) from orders where tenant_id=${T} and customer_name like '${PROBE}%') orders,
  (select count(*) from stock_batch_consumptions where tenant_id=${T}) cons,
  (select count(*) from products where tenant_id=${T} and name like '${PROBE}%') products,
  (select count(*) from stock_batches where tenant_id=${T} and sku_code like '${PROBE}%') batches`)[0]

mkdirSync(`${OUT}/evidence`, { recursive: true })
writeFileSync(`${OUT}/evidence/saving-board.json`, JSON.stringify(R, null, 2))
const failed = R.checks.filter((c) => !c.ok)
console.log(`\n== ${R.checks.length - failed.length}/${R.checks.length} pass（${((Date.now() - t0) / 1000).toFixed(0)}s）；残留 ${JSON.stringify(R.residue)} ==`)
process.exit(failed.length ? 1 : 0)
