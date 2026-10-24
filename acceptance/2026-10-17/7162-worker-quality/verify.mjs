// 工人端质检真页面验收（issue #7162）——
// 真浏览器（Playwright chromium）+ **真 H5 页面**（`frontend/worker-h5` 静态直出，与线上同源形态）
// + route 注入 `/api/worker/**` 夹具（本机 admin-api 是 #7162 之前的构建，无
//   `/api/worker/quality/**` ⇒ 真后端只能在 CI 覆盖；读取面形状由 WorkerQualityControllerTest 钉住）。
//
// 视口 390×844（手机）。判据：
//   ① 扫水洗唛（URL `?t=`）落地报工页 ⇒ 出现「质检」区块，初始「未检」（不是「合格」）；
//   ② 点「录入质检判定」⇒ 三态 + 原因 +「提交质检单」；
//   ③ 选「返工」+ 填原因 + 提交 ⇒「质检单已生成」+ 状态「返工」+ 原因上屏；
//   ④ 提交的 body **只**含 `order_item_id/result/reason`（不带 worker_id / inspector_id）；
//   ⑤ 全程无 console.error。
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { mkdirSync, writeFileSync, readFileSync, existsSync, statSync } from 'node:fs'
import { extname, join, normalize } from 'node:path'

const REPO_ROOT = '/Users/guangzhen.zk/ai native/migao'
const H5_ROOT = `${REPO_ROOT}/frontend/worker-h5`
const OUT = `${REPO_ROOT}/acceptance/2026-10-17/7162-worker-quality`
const { chromium } = createRequire(`${REPO_ROOT}/tests/package.json`)('playwright')

mkdirSync(OUT, { recursive: true })
const RESULT = { ok: false, viewport: '390x844', checks: {}, consoleErrors: [], posts: [] }

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
}

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  let path = url.pathname === '/' ? '/index.html' : url.pathname
  const file = normalize(join(H5_ROOT, path))
  if (!file.startsWith(H5_ROOT) || !existsSync(file) || !statSync(file).isFile()) {
    res.writeHead(404)
    res.end('not found')
    return
  }
  res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' })
  res.end(readFileSync(file))
})
await new Promise((resolve) => server.listen(8123, '127.0.0.1', resolve))

const VIEW = {
  granularity: 'set_position',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '裁剪', unit: '米', qty: 11.0 },
  alternatives: [],
  needs_selection: [],
  completed: false,
}

let latest = null

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
page.on('console', (msg) => {
  if (msg.type() === 'error') RESULT.consoleErrors.push(msg.text())
})

await page.addInitScript(() => {
  localStorage.setItem('migao:worker-h5:session', JSON.stringify({
    sessionId: 'ws-accept-7162', workerId: 'w1', workerNo: 'W-001', workerName: '张师傅', idleMinutes: 43200,
  }))
})

const json = (body) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ data: body }) })

await page.route('**/api/worker/**', async (route) => {
  const req = route.request()
  const path = new URL(req.url()).pathname
  if (path.endsWith('/production/current-worker')) {
    return route.fulfill(json({ worker_id: 'w1', worker_no: 'W-001', worker_name: '张师傅' }))
  }
  if (path.endsWith('/api/worker/me')) {
    // 逐人开了「质检」页（服务端准入在 WorkerQualityController；这里只验页面用得上它）
    return route.fulfill(json({ worker_id: 'w1', worker_name: '张师傅', pages: ['report', 'inspect'] }))
  }
  if (path.endsWith('/production/scan')) {
    return route.fulfill(json(VIEW))
  }
  if (path.endsWith('/quality/latest')) {
    return route.fulfill(json({ order_item_id: 'item-1', latest }))
  }
  if (path.endsWith('/quality/inspections') && req.method() === 'POST') {
    const body = JSON.parse(req.postData() ?? '{}')
    RESULT.posts.push(body)
    latest = {
      id: 'qi-accept-1',
      order_item_id: body.order_item_id,
      result: body.result,
      result_label: body.result === 'rework' ? '返工' : '合格',
      reason: body.reason ?? null,
      inspector_name: '张师傅',
      inspector_kind: 'worker',
      inspector_id: 'w1',
      inspected_at: '2026-10-17T13:10:00+08:00',
    }
    return route.fulfill(json(latest))
  }
  return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'NOT_FOUND', message: path } }) })
})

try {
  await page.goto('http://127.0.0.1:8123/index.html?t=WASH-7162', { waitUntil: 'networkidle' })
  const block = page.locator('#wh5-quality')
  await block.waitFor({ state: 'visible', timeout: 10_000 })
  RESULT.checks.blockVisible = true
  RESULT.checks.initialState = (await page.locator('#wh5-quality-state').innerText()).trim()
  if (RESULT.checks.initialState !== '未检') throw new Error(`初始态应为「未检」，实际：${RESULT.checks.initialState}`)
  await page.screenshot({ path: `${OUT}/质检-未检.png`, fullPage: true })

  await page.locator('#wh5-quality-open').click()
  await page.locator('#wh5-quality-form').waitFor({ state: 'visible' })
  RESULT.checks.formVisible = true
  RESULT.checks.resultOptions = await page.locator('[data-quality-result]').count()
  if (RESULT.checks.resultOptions !== 3) throw new Error(`三态应为 3 个选项，实际：${RESULT.checks.resultOptions}`)

  await page.locator('[data-quality-result="rework"]').click()
  await page.locator('#wh5-quality-reason').fill('缝线开裂')
  await page.locator('#wh5-quality-submit').click()

  await page.getByText('质检单已生成').waitFor({ state: 'visible', timeout: 10_000 })
  RESULT.checks.generatedNotice = true
  RESULT.checks.stateAfter = (await page.locator('#wh5-quality-state').innerText()).trim()
  if (RESULT.checks.stateAfter !== '返工') throw new Error(`提交后应为「返工」，实际：${RESULT.checks.stateAfter}`)
  RESULT.checks.reasonShown = (await page.locator('#wh5-quality-reason-latest').innerText()).includes('缝线开裂')
  if (!RESULT.checks.reasonShown) throw new Error('提交后原因未上屏')
  await page.screenshot({ path: `${OUT}/质检单已生成.png`, fullPage: true })

  const body = RESULT.posts[0] ?? {}
  RESULT.checks.postBody = body
  const keys = Object.keys(body).sort()
  if (JSON.stringify(keys) !== JSON.stringify(['order_item_id', 'reason', 'result'])) {
    throw new Error(`提交 body 不得带身份字段（实际键：${keys.join(',')}）`)
  }
  if (body.order_item_id !== 'item-1' || body.result !== 'rework' || body.reason !== '缝线开裂') {
    throw new Error(`提交内容不对：${JSON.stringify(body)}`)
  }
  if (RESULT.consoleErrors.length > 0) throw new Error(`console.error：${RESULT.consoleErrors.join(' | ')}`)
  RESULT.ok = true
} catch (e) {
  RESULT.error = String(e?.message ?? e)
}

writeFileSync(`${OUT}/result.json`, JSON.stringify(RESULT, null, 2))
await browser.close()
server.close()
console.log(JSON.stringify(RESULT, null, 2))
process.exit(RESULT.ok ? 0 : 1)
