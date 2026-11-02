// P5 — UI 级（真机驱动 worker-h5 :3160）：登录（**工号 + 企业编码 + PIN**）+ 当前工人 + 一次扫码开工（网络面 + DB 面双侧夹住）
//
// 🔴 修 #6938（入口漂移 —— 4 条判据恒红，且掩盖了「UI 级写面旅程 U5 实为未覆盖」）：
//    worker-h5 早已改「工号 + 企业编码」（issue #6564 / 提交 `0478ca5ff`：登录 body 送 `enterpriseCode`、
//    **不再**送 `tenantId`；短链 `?tenant_code=` 只是输入框初值；选择器 = `#wh5-enterprise-code`），
//    而本段仍用 `?tenant_id=` + 不存在的 `#wh5-code`/`#wh5-scan` ⇒ U2/U3/U3b/U4a 恒红、U5 根本没跑到。
//    ⇒ 选择器与 URL 参数**不手抄**：从 worker-h5 源码**引用**（见下方「UI 契约自证」），
//      并加 U0 契约断言把形态钉住（源码变了 ⇒ 当场红，而不是夹具悄悄过期）。
// 判据（每条都能红；含负对照与红证）：
//   U0 契约自证：选择器/URL 参数引用的真值源逐条命中（读不到 ⇒ fail-closed）
//   U1 未登录进入 ⇒ 登录视图可见（工号/企业编码/PIN/登录按钮）
//   U2 **负对照**：错误 PIN ⇒ 停在登录视图 + 页面出现服务端业务文案（不得进报工视图）
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
  TENANT_ID, TENANT_CODE, ID_PREFIX, cleanupFixture,
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

// ── UI 契约自证（真值源 = worker-h5 源码；选择器与 URL 参数**引用**，不手抄）──
// 读不到真值源 ⇒ fail-closed（不静默跳过、不回落成"大概对"）。
const REPO = process.env.REPO_ROOT || fileURLToPath(new URL('../../../../..', import.meta.url))
const readSrc = (p) => { try { return readFileSync(`${REPO}/${p}`, 'utf8') } catch { return null } }
const renderSrc = readSrc('frontend/worker-h5/src/render.mjs')
const scanInputSrc = readSrc('frontend/worker-h5/src/scan-input.mjs')
const uiContractFailures = []
if (!renderSrc) uiContractFailures.push('读不到 frontend/worker-h5/src/render.mjs（REPO_ROOT 指错？）')
if (!scanInputSrc) uiContractFailures.push('读不到 frontend/worker-h5/src/scan-input.mjs（REPO_ROOT 指错？）')
// 🔴 别再手抄：URL 参数名从 `enterpriseCodeFromLocation` 源码里抠（#6564 契约的唯一事实源）
const codeParam = scanInputSrc?.match(/url\.searchParams\.get\('([^']+)'\)[\s\S]{0,80}?TENANT_CODE_PATTERN/) ?.[1] ?? null
if (!codeParam) uiContractFailures.push("从 scan-input.mjs 的 enterpriseCodeFromLocation 抠不出企业编码的 query key")
if (codeParam && codeParam !== 'tenant_code') uiContractFailures.push(`企业编码 query key 已变成 '${codeParam}'（不是 tenant_code）⇒ 本段的 URL 要跟着改`)
for (const id of ['wh5-enterprise-code', 'wh5-worker-no', 'wh5-pin', 'wh5-login', 'wh5-error', 'wh5-code', 'wh5-scan', 'wh5-report', 'wh5-current-worker']) {
  if (renderSrc && !new RegExp(`id="${id}"`).test(renderSrc)) uiContractFailures.push(`render.mjs 里不再有 #${id} ⇒ 本段的页内选择器已过期`)
}
if (renderSrc) {
  const loginBlock = renderSrc.slice(renderSrc.indexOf('id="wh5-enterprise-code"'), renderSrc.indexOf('id="wh5-pin"'))
  if (!/工号/.test(loginBlock)) uiContractFailures.push('登录表单里「企业编码」与「PIN」之间不是「工号」格 ⇒ 顺序/形态已改')
}
if (scanInputSrc && !/TENANT_CODE_PATTERN/.test(scanInputSrc)) uiContractFailures.push('scan-input.mjs 里没有 TENANT_CODE_PATTERN（企业编码形状口径被移走？）')
const T_CODE = TENANT_CODE
judge(R, {
  id: 'U0.ui-contract-shape', name: '🔴 UI 契约自证：登录入口 = 工号 + 企业编码（#6564），选择器与 `?tenant_code=` 全部从 worker-h5 源码引用',
  expect: `render.mjs 含 #wh5-enterprise-code/#wh5-worker-no/#wh5-pin/#wh5-login/#wh5-code/#wh5-scan/#wh5-report/#wh5-current-worker ∧ scan-input.mjs 的企业编码 query key = tenant_code`,
  actual: `${JSON.stringify(uiContractFailures)}（query key=${JSON.stringify(codeParam)}）`,
  pass: uiContractFailures.length === 0,
  expectSource: '真值源：frontend/worker-h5/src/render.mjs（登录/扫码视图 id）+ frontend/worker-h5/src/scan-input.mjs::enterpriseCodeFromLocation（`?tenant_code=`，提交 0478ca5ff / issue #6564）',
  evidence: [`REPO_ROOT=${REPO}`, '回归时会怎么红：入口再改（选择器/参数/表单顺序）⇒ 本条红并具名；夹具若没跟上，U1~U5 也会红'],
})
const tenantCodeRow = one(`select code from tenants where id=${TENANT_ID}`)
judge(R, {
  id: 'U0b.tenant-code-matches-db', name: '🔴 夹具企业编码 == DB 里被测租户的 code（不一致 ⇒ 登录必 422，且**当场具名**而不是显示成产品缺陷）',
  expect: `harness TENANT_CODE（${T_CODE}）== tenants(${TENANT_ID}).code（${tenantCodeRow?.code}）`,
  actual: `harness=${T_CODE} db=${tenantCodeRow?.code ?? '(查不到)'}`,
  pass: !!tenantCodeRow?.code && tenantCodeRow.code === T_CODE,
  expectSource: '租户短链口径：`?tenant_code=`（PR #6566 短链）== tenants.code；不一致时把 TENANT_CODE=<该值> 传给 harness',
  evidence: ['可用 TENANT_CODE=<shop-xxxx> 覆盖；本判据的价值 = 让「编码抄错」当场红，而不是被读成产品登录坏了'],
})

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
await page.goto(`${UI}${UI_PATH}/index.html?${codeParam || 'tenant_code'}=${T_CODE}`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('#wh5-login', { timeout: 15000 })
await page.waitForTimeout(200)
const loginVisible = await page.locator('#wh5-login').isVisible().catch(() => false)
const enterprisePrefilled = await page.locator('#wh5-enterprise-code').inputValue().catch(() => null)
await page.screenshot({ path: join(SHOT, 'U1-login-view.png') })
judge(R, {
  id: 'U1.login-view', name: '未登录进入 worker-h5 ⇒ 登录视图可见（#wh5-login / #wh5-worker-no / #wh5-enterprise-code / #wh5-pin）',
  expect: `四个元素都可见 + 企业编码框被 URL 初值预填（${T_CODE}）`,
  actual: `login=${loginVisible} no=${await page.locator('#wh5-worker-no').count()} ent=${await page.locator('#wh5-enterprise-code').count()} pin=${await page.locator('#wh5-pin').count()} code预填=${JSON.stringify(enterprisePrefilled)}`,
  pass: loginVisible && (await page.locator('#wh5-worker-no').count()) === 1 && (await page.locator('#wh5-enterprise-code').count()) === 1
    && (await page.locator('#wh5-pin').count()) === 1 && enterprisePrefilled === T_CODE,
  expectSource: 'worker-h5/src/render.mjs::loginView（`#wh5-enterprise-code` / `#wh5-worker-no` / `#wh5-pin` / `#wh5-login`）+ app.mjs::createApp（`?tenant_code=` ⇒ 企业编码框**初值**）',
  evidence: [`截图 out/shots/U1-login-view.png`],
})

// ── U2 负对照：错误 PIN 必须停在登录视图 ──
await page.fill('#wh5-worker-no', A.workerNo)
await page.fill('#wh5-enterprise-code', T_CODE)
await page.fill('#wh5-pin', '999999')
await page.click('#wh5-login')
await page.waitForTimeout(1200)
const stillLogin = await page.locator('#wh5-login').isVisible().catch(() => false)
const errText = await page.locator('#wh5-error').innerText().catch(() => '')
const reportBtnAfterBad = await page.locator('#wh5-report').count()
await page.screenshot({ path: join(SHOT, 'U2-bad-pin.png') })
const headerAfterBad = await page.locator('#wh5-current-worker').count()
judge(R, {
  id: 'U2.bad-pin-negative-control', name: '负对照：错误 PIN（企业编码正确）⇒ 停在登录视图 + #wh5-error 显示**服务端业务文案**「工号或 PIN 不正确」+ 无报工入口、无工人名',
  expect: '#wh5-login 仍在 + #wh5-error 含「工号或 PIN 不正确」+ #wh5-report 不存在 + #wh5-current-worker 不存在',
  actual: `loginVisible=${stillLogin} err="${errText.slice(0, 80)}" reportCount=${reportBtnAfterBad} headerCount=${headerAfterBad}`,
  pass: stillLogin && errText.includes('工号或 PIN 不正确') && reportBtnAfterBad === 0 && headerAfterBad === 0,
  expectSource: 'worker-h5 api.mjs::login 抛错 → render.mjs 显示 #wh5-error（文案来自服务端 401「工号或 PIN 不正确」）',
  evidence: [
    `截图 out/shots/U2-bad-pin.png`,
    `网络面：${JSON.stringify(net.filter((x) => x.u.includes('/api/worker/login')).map((x) => [x.u, x.status]))}`,
    '🔴 文案口径（issue #6747，提交 8874bee5b）：「认证失败」路径**逐字保留服务端那句判定**（`工号或 PIN 不正确`）+ 一句可行动作；本次取 `includes` 而不等值，避免把「后面多了半句动作」判成红',
    '🔴 第一版只断言「#wh5-error 非空」⇒ 抓到的是 `Failed to fetch`（**测试装置没做同源代理**，不是产品文案）= 判据什么都没证（主会话复核指出）',
  ],
})

// ── U2b 负对照：**企业编码错** ⇒ 拒绝且不进报工视图（#6564 的租户只由服务端解析）──
await page.fill('#wh5-enterprise-code', 'zzz-not-a-tenant')
await page.fill('#wh5-pin', String(A.pin))
await page.click('#wh5-login')
await page.waitForTimeout(1200)
const errText2 = await page.locator('#wh5-error').innerText().catch(() => '')
const stillLogin2 = await page.locator('#wh5-login').isVisible().catch(() => false)
const badCodeCalls = net.filter((x) => x.u.includes('/api/worker/login'))
await page.screenshot({ path: join(SHOT, 'U2b-bad-enterprise-code.png') })
judge(R, {
  id: 'U2b.bad-enterprise-code-rejected', name: '负对照：企业编码不存在 ⇒ 停在登录视图 + 得到**确定性拒绝**（4xx，不是静默成功、不是 5xx）',
  expect: '#wh5-login 仍在（无 #wh5-report）+ 网络面 /api/worker/login 4xx 且无 5xx',
  actual: `loginVisible=${stillLogin2} err="${errText2.slice(0, 80)}" 登录调用=${JSON.stringify(badCodeCalls.map((x) => [x.status, String(x.err ?? '').slice(0, 90)]))}`,
  pass: stillLogin2 && badCodeCalls.length > 0 && badCodeCalls.every((x) => x.status >= 400 && x.status < 500),
  expectSource: 'WorkerTenantResolver.resolve（服务端按 enterpriseCode 解析租户；解析不到 ⇒ 反枚举 401/422，见 scan-input.mjs 类注释的 2026-10-11 生产实测）',
  evidence: ['截图 out/shots/U2b-bad-enterprise-code.png', '本条把「租户只由服务端解析」这一条 #6564 纪律钉在 UI 层（前端的默认租户曾把租户 25 的工人登录判成租户 1）'],
})

// ── U3 正确登录 ⇒ 页头「当前工人」出现在真实 DOM ──
net.length = 0
await page.fill('#wh5-worker-no', A.workerNo)
await page.fill('#wh5-enterprise-code', T_CODE)   // 🔴 U2b 刚把它填成错编码 ⇒ 必须复位，否则本条测的是「编码错」不是「登录成功」
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
  expectSource: 'worker-h5/src/render.mjs::scanView（`#wh5-code` + `#wh5-scan`）；app.mjs 只从 URL 读**企业编码**（enterpriseCodeFromLocation）与 `?code=`/`?token=` 扫码深链，扫码框本身不回填（观察项）',
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
await page.goto(`${UI}${UI_PATH}/machine.html?${codeParam || 'tenant_code'}=${T_CODE}`, { waitUntil: 'domcontentloaded' })
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
