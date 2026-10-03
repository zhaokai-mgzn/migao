// P5 — UI 级（真机驱动 worker-h5 :3100）：登录 + 当前工人 + 一次扫码开工（网络面 + DB 面双侧夹住）
//
// 工具：Playwright（`tests/node_modules/playwright`，**不新装依赖**，与 ui-replay/replay.mjs 同一引入方式）。
// 判据（每条都能红；含负对照与红证）：
//   U1 未登录进入 ⇒ 登录视图可见（工号/PIN/登录按钮）
//   U2 **负对照**：错误 PIN ⇒ 停在登录视图 + 页面出现错误文案（不得进报工视图）
//   U3 正确登录 ⇒ 页头「当前工人：<探针工人>」出现在**真实 DOM**（不是接口回执）
//   U4 带 token 进入扫码页 ⇒ 扫码输入框 + 「开 工」按钮渲染（`wh5-code` / `wh5-report`）
//   U5 点「开 工」⇒ **网络面**：POST /api/worker/production/scan/complete 200；**DB 面**：落 1 行 production_work_logs
//   U6 红证：把期望改坏（断言扫的是**不存在**的 token）⇒ 判据必红（证明它真的在看读数）
import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs'
import {
  Recorder, judge, log, nowCST, outPath, psql, one, guardedWrite,
  buildFixture, fixtureOps, workLogs, ensureWorkerSession, storePath, saveStore,
  TENANT_ID, ID_PREFIX, cleanupFixture,
} from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const SHOT = join(HERE, '..', 'out', 'shots')
mkdirSync(SHOT, { recursive: true })
const R = new Recorder('P5-ui.json')
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')

// 🔴 端口说明（**环境缺陷登记**）：`:3100` 的静态根 = `main-live/frontend/worker-h5`，
// 而 `render.mjs` / `machine.mjs` 里 `import '../../shared/operation-display.mjs'`（= `/shared/...`）
// 会被解析到 **:`3100`/shared/** ⇒ 本机 404 ⇒ 页面**整页白屏**（实测：body 仅 423 字节、0 个 #wh5-login）。
// ⇒ 本段改用 :3160（同一份静态文件的只读静态服务，根目录 = `frontend/`，不重启任何既有服务）。
const UI = process.env.WORKER_UI || 'http://127.0.0.1:3160'
const UI_PATH = process.env.WORKER_UI_PATH || '/worker-h5'
const API_ORIGIN = process.env.API_ORIGIN || 'http://127.0.0.1:8080'
const browser = await chromium.launch()
const net = []
const page = await browser.newPage({ viewport: { width: 480, height: 900 } })
// 同源假设（页面与 /api 同域，部署形态 = nginx 同源）在本机不成立 ⇒ **测试装置级**代理：
// Playwright 路由把 :3160 的 /api/** 转发到 :8080（**不改产品代码**；报告里如实标注）。
// 🔴 为什么必须用 `route.fulfill`（Node 侧代理）而不是 `route.continue({url})`：
//    continue 只改请求去向，浏览器仍按**跨源**处理响应 ⇒ 要过 CORS，而 admin-api 的
//    `CORS_ALLOWED_ORIGINS` 只放行 localhost:3000/3001（预检 OPTIONS 实测 403）
//    ⇒ 登录响应被浏览器拦掉（#wh5-error 显示 `Failed to fetch`）。fulfill 让浏览器看到的是
//    **同源响应**（部署形态本来就是 nginx 同源）⇒ 这是测试装置的代理，不是产品放宽。
await page.route('**/api/**', async (route) => {
  const req = route.request()
  const url = req.url().replace(UI, API_ORIGIN)
  try {
    const headers = { ...req.headers() }
    delete headers.origin; delete headers.referer; delete headers.host   // 去掉跨源痕迹（否则后端可能按 Origin 拒）
    const resp = await fetch(url, { method: req.method(), headers, body: req.postData() ?? undefined })
    const body = await resp.text()
    log(`  [proxy] ${req.method()} ${url.replace(API_ORIGIN, '')} ⇒ ${resp.status}${resp.status >= 400 ? ' body=' + body.slice(0, 200) : ''}`)
    await route.fulfill({ status: resp.status, contentType: resp.headers.get('content-type') ?? 'application/json', body })
  } catch (e) {
    await route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'PROXY_ERROR', message: String(e).slice(0, 120) } }) })
  }
})
page.on('request', (r) => { if (r.url().includes('/api/')) net.push({ m: r.method(), u: r.url().replace(UI, ''), body: r.postData()?.slice(0, 200) }) })
page.on('response', async (r) => {
  if (!r.url().includes('/api/')) return
  const u = r.url().replace(UI, '')
  const i = net.findIndex((x) => x.u === u && !x.status)
  const body = r.status() >= 400 ? (await r.text().catch(() => '')).slice(0, 240) : undefined
  if (i >= 0) { net[i].status = r.status(); net[i].err = body } else net.push({ m: r.request().method(), u, status: r.status(), err: body })
})

// ── U1 未登录视图 ──
await page.goto(`${UI}${UI_PATH}/index.html?tenant_id=${TENANT_ID}`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('#wh5-login', { timeout: 15000 })
await page.waitForTimeout(200)
const loginVisible = await page.locator('#wh5-login').isVisible().catch(() => false)
await page.screenshot({ path: join(SHOT, 'U1-login-view.png') })
judge(R, {
  id: 'U1.login-view', name: '未登录进入 worker-h5 ⇒ 登录视图可见（#wh5-login / #wh5-worker-no / #wh5-pin）',
  expect: '三个元素都可见', actual: `login=${loginVisible} no=${await page.locator('#wh5-worker-no').count()} pin=${await page.locator('#wh5-pin').count()}`,
  pass: loginVisible && (await page.locator('#wh5-worker-no').count()) === 1 && (await page.locator('#wh5-pin').count()) === 1,
  expectSource: 'worker-h5/src/render.mjs::renderLogin（`#wh5-worker-no` / `#wh5-pin` / `#wh5-login`）',
  evidence: [`截图 out/shots/U1-login-view.png`],
})

// ── U2 负对照：错误 PIN 必须停在登录视图 ──
await page.fill('#wh5-worker-no', A.workerNo)
await page.fill('#wh5-pin', '999999')
await page.click('#wh5-login')
await page.waitForTimeout(1200)
const stillLogin = await page.locator('#wh5-login').isVisible().catch(() => false)
const errText = await page.locator('#wh5-error').innerText().catch(() => '')
const reportBtnAfterBad = await page.locator('#wh5-report').count()
await page.screenshot({ path: join(SHOT, 'U2-bad-pin.png') })
const headerAfterBad = await page.locator('#wh5-current-worker').count()
judge(R, {
  id: 'U2.bad-pin-negative-control', name: '负对照（内容级）：错误 PIN ⇒ 停在登录视图 + #wh5-error 显示**业务文案**「工号或 PIN 不正确」+ 无报工入口、无工人名',
  expect: '#wh5-login 仍在 + #wh5-error 含「工号或 PIN 不正确」+ #wh5-report 不存在 + #wh5-current-worker 不存在',
  actual: `loginVisible=${stillLogin} err="${errText.slice(0, 60)}" reportCount=${reportBtnAfterBad} headerCount=${headerAfterBad}`,
  pass: stillLogin && errText.includes('工号或 PIN 不正确') && reportBtnAfterBad === 0 && headerAfterBad === 0,
  expectSource: 'worker-h5 api.mjs::login 抛错 → render.mjs 显示 #wh5-error（文案来自服务端 401 "工号或 PIN 不正确"）',
  evidence: [
    `截图 out/shots/U2-bad-pin.png`,
    `网络面：${JSON.stringify(net.filter((x) => x.u.includes('/api/worker/login')).map((x) => [x.u, x.status]))}`,
    '🔴 第一版只断言「#wh5-error 非空」⇒ 抓到的是 `Failed to fetch`（**测试装置没做同源代理**，不是产品文案）= 判据什么都没证（主会话复核指出）',
  ],
})

// ── U3 正确登录 ⇒ 页头「当前工人」出现在真实 DOM ──
net.length = 0
await page.fill('#wh5-worker-no', A.workerNo)
await page.fill('#wh5-pin', String(A.pin))
await page.dispatchEvent('#wh5-worker-no', 'input')
await page.dispatchEvent('#wh5-pin', 'input')
const loginResp = page.waitForResponse((r) => r.url().includes('/api/worker/login'), { timeout: 20000 }).catch(() => null)
await page.click('#wh5-login')
const lr = await loginResp
log(`UI 登录响应: ${lr?.status() ?? '(未捕获)'}`)
await page.waitForSelector('#wh5-current-worker', { timeout: 12000 }).catch(() => {})
const errAfterLogin = await page.locator('#wh5-error').innerText().catch(() => '')
const headerText = await page.locator('#wh5-current-worker').innerText().catch(() => '')
await page.screenshot({ path: join(SHOT, 'U3-logged-in.png') })
judge(R, {
  id: 'U3.current-worker-in-dom', name: '正确登录 ⇒ 页头「当前工人：<探针工人>」出现在**真实 DOM**',
  expect: `#wh5-current-worker 含「${A.workerName}」`,
  actual: `header="${headerText}" err="${errAfterLogin.slice(0, 60)}" 登录响应=${JSON.stringify(net.filter((x) => x.u.includes('/api/worker/login')).map((x) => [x.u, x.status, x.err]))}`,
  pass: headerText.includes(A.workerName ?? '@@'),
  expectSource: 'WorkerProfileController/current-worker（服务端解身份）+ render.mjs 页头渲染',
  evidence: [`截图 out/shots/U3-logged-in.png`],
})
judge(R, {
  id: 'U3b.me-called', name: '登录后 UI 真的拉了服务端读面（GET /api/worker/production/current-worker 或 /me 出现在网络面）',
  expect: '网络面出现 worker 读面请求', actual: JSON.stringify(net.map((x) => [x.u.split('?')[0], x.status])),
  pass: net.some((x) => x.u.includes('/api/worker/production/current-worker') || x.u.includes('/api/worker/me')),
  expectSource: 'worker-h5 app.mjs 登录后 refreshPages/currentWorker（网络面取证，不靠接口独立调用）',
})

// ── U4/U5 扫码 + 一次开工（**页面自己的链路**：填码 → 点 wh5-scan → 点 wh5-report）──
const F = buildFixture({ tag: 'P5UI', qty: '2.00' })
store.fixtures = store.fixtures || {}; store.fixtures.P5UI = F; saveStore(store)
net.length = 0
// 扫码前的形态（判据拆两段，避免把「扫码后」的 id 集当成「扫码前」的）
const preIds = await page.evaluate(() => Array.from(document.querySelectorAll('[id^=wh5-]')).map((e) => e.id))
const codeBefore = await page.locator('#wh5-code').inputValue().catch(() => null)
judge(R, {
  id: 'U4a.scan-input-empty', name: '扫码前：手输框 `#wh5-code` 存在且**默认为空**、`#wh5-scan` 存在（页面**不**从 URL 读 token 回填 ⇒ 无深链，观察项）',
  expect: '#wh5-code 存在且值 == ""；#wh5-scan 存在',
  actual: `codeBefore=${JSON.stringify(codeBefore)} ids=${JSON.stringify(preIds)}`,
  pass: codeBefore === '' && preIds.includes('wh5-scan'),
  expectSource: 'app.mjs: 只从 URL 读 tenantId（tenantIdFromLocation）；token 只能手输/扫码（无深链能力，登记为观察项）',
})
await page.fill('#wh5-code', F.token)
await page.click('#wh5-scan')
const resolved = await page.waitForSelector('#wh5-report', { timeout: 20000 }).then(() => true).catch(() => false)
const codeAfterScan = await page.locator('#wh5-code').inputValue().catch(() => null)
const pageIds = await page.evaluate(() => Array.from(document.querySelectorAll('[id^=wh5-]')).map((e) => e.id))
await page.screenshot({ path: join(SHOT, 'U4-scan-view.png') })
judge(R, {
  id: 'U4.scan-resolves-in-ui', name: '页面内「扫码」链路：填码点 #wh5-scan ⇒ 服务端解析成功并渲染「开 工」按钮（#wh5-report）',
  expect: '#wh5-report 出现（= 服务端推断出唯一工序）',
  actual: `扫码后 code=${JSON.stringify(codeAfterScan)} 出现开工按钮=${resolved} 页面 id 集=${JSON.stringify(pageIds)}`,
  pass: resolved,
  expectSource: 'app.mjs::on("wh5-scan") → api.resolveScan（服务端推断工序）→ render 渲染 wh5-report',
  evidence: [`截图 out/shots/U4-scan-view.png`],
})
const before = { logs: workLogs(F).length, ops: fixtureOps(F) }
let clickErr = null
try { await page.click('#wh5-report') } catch (e) { clickErr = e.message }
await page.waitForTimeout(2500)
await page.screenshot({ path: join(SHOT, 'U5-after-report.png') })
const after = { logs: workLogs(F).length, ops: fixtureOps(F) }
const completeCalls = net.filter((x) => x.u.includes('/api/worker/production/scan/complete'))
judge(R, {
  id: 'U5.ui-report-writes', name: '🔴 UI 点「开 工」⇒ 网络面 POST scan/complete 200 + DB 落 1 行 production_work_logs（双侧夹住）',
  expect: '网络面 1 次 scan/complete 且 status=200；work_logs 0→1；工序 done_qty 0→2.00',
  actual: `net=${JSON.stringify(completeCalls.map((x) => [x.u, x.status]))} logs=${before.logs}→${after.logs} done_qty=${after.ops[0]?.done_qty}`,
  pass: completeCalls.some((x) => x.status === 200) && after.logs === before.logs + 1 && after.ops[0]?.done_qty === '2.00',
  expectSource: 'worker-h5 app.mjs::completeByScan（唯一写入口）+ ProductionScanCompleteService（服务端记账）',
  evidence: [`截图 out/shots/U5-after-report.png`, `点击异常=${clickErr ?? '无'}`, `页面文本片段=${(await page.content()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 220)}`],
})
judge(R, {
  id: 'U5b.receipt-rendered', name: '回执渲染：页面显示「已领活/下一道/本套完成」类文案（不是只有网络 200）',
  expect: '页面正文含回执语义文案', actual: (await page.content()).match(/已领活|下一道|本套|没有再待做|开工/)?.[0] ?? '(未匹配)',
  pass: /已领活|下一道|本套|没有再待做|开工/.test(await page.content()),
  expectSource: 'worker-h5 render.mjs::renderReceipt（回执文案由服务端 result 给）',
})

// ── U7 一体机屏（machine.html）：把 #6219 在 **UI 层**复现（用户可见面）──
const FM = buildFixture({ tag: 'P5M', qty: '3.00' })
store.fixtures.P5M = FM; saveStore(store)
guardedWrite(`-- probe-ok\nupdate order_items set product_id=null where tenant_id=${TENANT_ID} and id='${FM.itemId}';`)
await page.goto(`${UI}${UI_PATH}/machine.html?tenant_id=${TENANT_ID}`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('#machine-root', { timeout: 15000 }).catch(() => {})
let machineText = ''
try {
  // machine.html 的输入是**全页键盘事件**（machine-app.mjs::doc.addEventListener('keydown')），
  // 不是 <input> ⇒ 必须用 keyboard.type（实测 locator.fill 超时 ⇒ 那是我的装置错，不是页面错）。
  await page.locator('#machine-root').click({ timeout: 5000 }).catch(() => {})
  await page.keyboard.type(FM.token, { delay: 12 })
  await page.keyboard.press('Enter')
  await page.waitForTimeout(3000)
} catch (e) { machineText = `交互失败: ${e.message.slice(0, 120)}` }
const machineContent = (await page.content()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
machineText = machineText || machineContent.slice(0, 300)
await page.screenshot({ path: join(SHOT, 'U7-machine-null-product.png') })
const chCalls = net.filter((x) => x.u.includes('cutting-height'))
judge(R, {
  id: 'U7.machine-null-product-500', name: '🔴 #6219 的 **UI 层**复现：一体机屏扫「订单行 product_id 为空」的码 ⇒ 裁高读面 500，页面显示失败大字（用户可见面）',
  expect: '网络面 GET /api/worker/production/cutting-height ⇒ 500；页面**显式报错**（不是假装成功/空值静默）',
  actual: `cutting-height 请求=${JSON.stringify(chCalls.map((x) => [x.u.split('?')[0], x.status]))}；页面文本=${machineText.slice(0, 200)}`,
  pass: chCalls.some((x) => x.status === 500) && /失败|错误|internal/i.test(machineText),
  expectSource: 'machine-app.mjs::onScan → api.readCuttingHeight（WorkerCuttingHeightService.positionRow:149 NPE ⇒ 500）',
  evidence: ['截图 out/shots/U7-machine-null-product.png', '与 API 层复现（P2b/N1、P2/C23）互为**两侧证据**：接口 500 + 车间屏可见失败'],
})

// ── U6 红证：把期望改坏 ⇒ 判据必红（证明 U4 判据真的在看读数）──
// 红证取「扫码**前**」的读数（那时输入框是空的）⇒ 期望它 == 一个不存在的 token，必然不成立。
const brokenExpectation = F.token + '-BROKEN'
const brokenPass = codeBefore === brokenExpectation
judge(R, {
  id: 'U6.redproof', name: '🔴 红证：把 U4 的期望改成「输入框 == 不存在的 token」⇒ 该判据**必红**（证明它不是空断言）',
  expect: `codeBefore == ${brokenExpectation}（**故意错的期望**）`, actual: `codeBefore=${JSON.stringify(codeBefore)}`,
  pass: brokenPass,
  expectSource: '红证夹具：期望值故意改坏；若这里 pass ⇒ U4 的判据没在真读 DOM（空断言）',
  evidence: ['本条按设计**必须 fail**（fail 桶中的失效控制项，不计产品缺陷）'],
})

await browser.close()
writeFileSync(outPath('P5-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary(), shots: ['U1-login-view.png', 'U2-bad-pin.png', 'U3-logged-in.png', 'U4-scan-view.png', 'U5-after-report.png'] }, null, 2))
log(`P5 汇总: ${JSON.stringify(R.summary())}（U6 是**故意的失效控制项**）`)
process.exit(0)
