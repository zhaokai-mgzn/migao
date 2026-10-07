// 2026-10-07 · issue #6408 修复的**真环境 UI 重放**（定点，不是 300 单全量）
//
// 要证的一条（界面路径，不是直调）：
//   智能派单页「一键合并派单」现在**真的带指派** ⇒ 服务端 `buildDesignations` 非空
//   ⇒ 池级排料求解器真的跑 ⇒ 落 `stock_batch_consumptions` 行
//   ⇒ 且界面上的「预计节省」== 台账 Σ(saved_meters)。
//
// 为什么必须真环境：前端改动（`buildPoolRequest` 的**请求体形状**）在单测里只能钉住请求体本身；
// 「服务端拿到这个体之后真的扣料、且数与界面显示一致」只能在真库真链路上读（migao-acceptance 的 L2/UA 面）。
//
// 复用：`acceptance/2026-10-06-pooling-savings/harness/{lib,steps}.mjs`（**不复制**实现，避免第二份判定）。
// 探针：本次专用前缀（缺省 `SD07UI`），收尾 `cleanup()` 删干净。
import { chromium, api, shot, loginUi, OUT, WEB } from '../2026-10-06-pooling-savings/harness/lib.mjs'
import { login, setupProbe, createOrder, assign, consumptions, cleanup, ordersByNoPrefix, T } from '../2026-10-06-pooling-savings/harness/steps.mjs'
import { mkdirSync, writeFileSync } from 'node:fs'

const stamp = String(Date.now()).slice(-6)
const PREFIX = process.env.PROBE_PREFIX || 'SD07UI'
const out = { at: new Date().toISOString(), stamp, prefix: PREFIX, web: WEB, steps: [], asserts: [] }
const rec = (k, v) => { out.steps.push({ k, v }); console.log('▶', k, JSON.stringify(v)?.slice(0, 700)) }
const A = (name, ok, detail) => { out.asserts.push({ name, ok, detail: detail ?? null }); console.log(ok ? '✅' : '❌', name, detail ?? ''); return ok }
const until = async (fn, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (fn()) return true; await new Promise((r) => setTimeout(r, 300)) } return false }
const jbody = (s) => { try { return JSON.parse(s || '{}') } catch { return {} } }

const probeSql = `order_item_id in (select oi.id::text from order_items oi join orders o on o.id=oi.order_id where o.tenant_id=${T} and o.customer_name like '${PREFIX}%')`

let browser
let failed = []
try {
  const token = await login()
  const probe = await setupProbe(token, { stamp, meters: 4000, unitCost: 40 })
  rec('probe', probe)

  // 4 张几何相同的窄窗单（同商品/SKU ⇒ 同一池组）
  const orders = []
  for (let i = 0; i < 4; i++) orders.push(await createOrder(token, { ...probe, seq: `${stamp}${i}` }))
  rec('orders', orders)
  if (orders.some((o) => !o.orderNo)) throw new Error('造单未拿到 orderNo，无法在界面上定位')

  browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  const reqs = []
  const resps = []
  page.on('request', (r) => { if (r.url().includes('/api/admin/production/pool/')) reqs.push({ url: r.url(), body: r.postData() }) })
  page.on('response', async (r) => {
    if (!r.url().includes('/api/admin/production/pool/')) return
    let json = null
    try { json = await r.json() } catch { /* 非 JSON 就留 null */ }
    resps.push({ url: r.url(), status: r.status(), json })
  })

  await loginUi(page, { phone: process.env.ADMIN_PHONE || '13800138000' })
  await page.goto(WEB + '/production/pool', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('[data-testid="pool-status-line-count"]', { timeout: 60000 })
  await shot(page, 'pool-before-select')

  // 勾选这 4 单 ⇒ 页面自发调 /preview（判据：请求体形状）
  for (const o of orders) await page.getByLabel(`选择订单 ${o.orderNo}`).check()
  const gotPreview = await until(() => reqs.some((r) => r.url.includes('/preview') && (jbody(r.body).orderIds || []).length === orders.length))
  const pvReq = [...reqs].reverse().find((r) => r.url.includes('/preview') && (jbody(r.body).orderIds || []).length === orders.length)
  const pvBody = jbody(pvReq?.body)
  rec('ui_preview_body', pvBody)

  failed.push(...[
    A('① 界面 /preview 请求体逐行带指派', !!pvReq && pvBody.batches?.length === orders.length
      && pvBody.batches.every((b) => b.orderId && b.itemId) && pvBody.assignmentRule === 'fifo' && pvBody.pooled === true,
      JSON.stringify(pvBody)),
    A('①b 界面 /preview 不再是空指派（#6408 的缺陷形态）', (pvBody.batches || []).length > 0, `batches=${(pvBody.batches || []).length}`),
  ].filter((x) => !x))

  // 多模态证据：**派单前**把「预计节省」那一屏截下来（铁律 2 的 Playwright 页面多模态验收）
  // ⚠️ 必须等预览**渲染完**再截：早一轮实测截到了「正在预览…」，图里根本没有数字（假证据）。
  await page.waitForFunction(
    () => (document.querySelector('[data-testid="pool-preview"]')?.textContent || '').includes('预计节省'),
    { timeout: 60000 },
  ).catch(() => {})
  const panelText = (await page.locator('[data-testid="pool-preview"]').innerText().catch(() => '')).replace(/\s+/g, ' ')
  rec('preview_panel_text', panelText.slice(0, 500))
  await shot(page, 'pool-preview-with-savings')

  await page.click('[data-testid="pool-dispatch-batch"]')
  const gotDispatch = await until(() => reqs.some((r) => r.url.includes('/dispatch')))
  const dReq = [...reqs].reverse().find((r) => r.url.includes('/dispatch'))
  const dBody = jbody(dReq?.body)
  rec('ui_dispatch_body', dBody)
  failed.push(...[
    A('② 界面 /dispatch 请求体逐行带指派 + fifo + pooled', !!dReq && dBody.batches?.length === orders.length
      && dBody.batches.every((b) => b.orderId && b.itemId) && dBody.assignmentRule === 'fifo' && dBody.pooled === true,
      JSON.stringify(dBody)),
  ].filter((x) => !x))

  await page.waitForSelector('[data-testid="pool-dispatch-results"]', { timeout: 60000 }).catch(() => {})
  await shot(page, 'pool-after-dispatch')

  // 真库读数：扣料行 + Σsaved
  const cons = consumptions(probeSql)
  const sumSaved = cons.reduce((a, c) => a + Number(c.saved), 0)
  rec('consumptions', cons)
  failed.push(...[
    A('③ 真库产生扣料行（>0）', cons.length > 0, `rows=${cons.length}`),
    A('③b Σ(saved_meters) > 0（真的省了料）', sumSaved > 0, `${sumSaved} 米`),
  ].filter((x) => !x))

  // 界面「预计节省」== 台账 Σ(saved)
  const pvResp = [...resps].reverse().find((r) => r.url.includes('/preview') && r.json?.data)
  const savedShown = Number(pvResp?.json?.data?.savedMeters)
  rec('preview_response_savedMeters', savedShown)
  const savedOnScreen = Number((panelText.match(/预计节省[^0-9-]*(-?[0-9.]+)/) || [])[1])
  failed.push(...[
    A('④ 服务端 preview.savedMeters == 台账 Σ(saved_meters)', Number.isFinite(savedShown) && Math.abs(savedShown - sumSaved) < 0.005,
      `preview=${savedShown} / db=${sumSaved}`),
    // §15.1：断言**用户可见结果**（屏幕上那个数），而不是只断言「API 被调过」
    A('⑥ 屏幕上「预计节省」显示值 == 台账 Σ(saved_meters)', Number.isFinite(savedOnScreen) && Math.abs(savedOnScreen - sumSaved) < 0.005,
      `屏上=${savedOnScreen} / db=${sumSaved}`),
  ].filter((x) => !x))

  // 同轮红绿对照（单变量 = 请求体）：另造 2 单，只做 /preview，不派单
  const pair = []
  for (let i = 4; i < 6; i++) pair.push(await createOrder(token, { ...probe, seq: `${stamp}${i}` }))
  const ids = pair.map((o) => o.orderId)
  const pvOld = await api('POST', '/api/admin/production/pool/preview', { token, body: { orderIds: ids, batches: [], assignmentRule: null, pooled: true } })
  const pvNew = await api('POST', '/api/admin/production/pool/preview', { token, body: { orderIds: ids, ...assign(pair, 'fifo'), pooled: true } })
  const oldSaved = Number(pvOld.json?.data?.savedMeters)
  const newSaved = Number(pvNew.json?.data?.savedMeters)
  rec('contrast', { old_body_savedMeters: oldSaved, new_body_savedMeters: newSaved })
  failed.push(...[
    A('⑤ 对照·旧体（batches:[]）⇒ savedMeters == 0', oldSaved === 0, `${oldSaved}`),
    A('⑤b 对照·新体（逐行指派+fifo）⇒ savedMeters > 0', newSaved > 0, `${newSaved}`),
  ].filter((x) => !x))
} catch (e) {
  rec('FATAL', String(e?.stack || e).slice(0, 1200))
  failed.push({ name: '运行时异常', ok: false, detail: String(e?.message || e) })
} finally {
  try {
    if (browser) await browser.close()
  } catch { /* 关不掉也不掩盖真读数 */ }
  try {
    const left = ordersByNoPrefix(PREFIX).length
    const cleaned = String(cleanup(PREFIX)).slice(0, 200)
    rec('cleanup', { cleaned, left })
    out.cleanup = { left, cleaned }
  } catch (e) { rec('cleanup_error', String(e)) }
  mkdirSync(`${OUT}/evidence`, { recursive: true })
  out.ok = failed.length === 0
  writeFileSync(`${OUT}/ui-replay.json`, JSON.stringify(out, null, 2))
  console.log('\n== 汇总 ==')
  for (const a of out.asserts) console.log(a.ok ? '✅' : '❌', a.name, a.detail ?? '')
  console.log(out.ok ? '\n全部判据通过' : `\n失败 ${failed.length} 条`)
  process.exit(out.ok ? 0 : 1)
}
