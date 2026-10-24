// 工人端裁剪报工确认批次 —— 真浏览器截图（issue #7647 的多模态验收载体）
// 纯前端：静态服务 + 路由打桩（不碰真库），只为让「批次区块 / 禁用态 / 候选 / 回执」上屏。
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { createRequire } from 'node:module'

const ROOT = '/Users/guangzhen.zk/ai native/migao-wt/7647-cutting-report-batch/frontend/worker-h5'
const OUT = '/tmp/wh5-visual/out'
const PORT = 5197
const { chromium } = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')('playwright')

const TYPES = { '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' }

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://127.0.0.1:${PORT}`)
    const rel = normalize(url.pathname === '/' ? '/index.html' : url.pathname).replace(/^([.]{2}[/\\])+/, '')
    const file = join(ROOT, rel)
    const body = await readFile(file)
    res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' })
    res.end(body)
  } catch {
    res.writeHead(404); res.end('not found')
  }
})
await new Promise((r) => server.listen(PORT, '127.0.0.1', r))

const resolvePayload = ({ assigned }) => ({
  granularity: 'set_position', order_id: 'o-1', processing_order_no: 'CSO261024-00001',
  set_no: '1', set_index: 1,
  position: { order_item_id: 'it-1', position_kind: '布帘', position_name: '布帘', remark: null },
  set_overview: {
    positions: [{
      order_item_id: 'it-1', position_kind: '布帘', position_name: '布帘',
      width: 3.2, height: 2.6, fabric_meters: 10,
      operations: [{ operation_id: 'op-1', logical_name: '裁剪', qty: 10, done_qty: 0, unit: '米', unit_price: 0.4, status: 'pending' }],
    }],
    cut_plan: [{ order_item_id: 'it-1', position_name: '布帘', component: null, panel_length_m: 3.2, panel_count: 2, fabric_meters: 10, batch_no: assigned ? 'PC-20261020-0007' : null }],
  },
  operation: { operation_id: 'op-1', logical_name: '裁剪', position: '布帘', qty: 10, done_qty: 0, unit: '米', unit_price: 0.4, status: 'pending', seq: 1, determined_by: 'inferred' },
  alternatives: [], set_progress: { done: 0, total: 2 }, stalled: { kind: null },
  completed: false, completed_at: null, needs_selection: [],
  batch_required: true,
  batch_no: assigned ? 'PC-20261020-0007' : null,
  batch_candidates: assigned
    ? [{ batch_no: 'PC-20261020-0007', remaining_meters: 42.5, enough: true },
       { batch_no: 'PC-20261018-0002', remaining_meters: 3, enough: false }]
    : [{ batch_no: 'PC-20261018-0002', remaining_meters: 3, enough: false }],
})

const browser = await chromium.launch()

async function shoot({ assigned, name, viewport, act }) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, locale: 'zh-CN' })
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.addInitScript(() => {
    localStorage.setItem('migao:worker-h5:session', JSON.stringify({
      sessionId: 'sess-visual-1', workerId: 'w-1', workerNo: 'W001', workerName: '张三',
      idleMinutes: 43200, idleExpiresAt: '2099-01-01T00:00:00Z',
    }))
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const json = (obj) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: obj }) })
    if (url.pathname.endsWith('/production/current-worker')) return json({ worker_id: 'w-1', worker_no: 'W001', worker_name: '张三' })
    if (url.pathname.endsWith('/worker/me')) return json({ worker_id: 'w-1', worker_name: '张三', pages: ['report', 'cut_calc'] })
    if (url.pathname.endsWith('/production/scan')) return json(resolvePayload({ assigned }))
    if (url.pathname.endsWith('/production/scan/complete')) return json({ operation_id: 'op-1', done_qty: 10, status: 'done', order_completed: false, set_no: '1', position: '布帘', set_progress: { done: 1, total: 2 }, set_completed: false, next_operation: { logical_name: '打包' }, batch_no: assigned ? 'PC-20261020-0007' : 'PC-20261018-0002', batch_remaining: -1.5, batch_shortage_meters: 4.5 })
    return json({})
  })
  await page.goto(`http://127.0.0.1:${PORT}/index.html?t=scan-visual-token`)
  await page.waitForSelector('#wh5-report', { timeout: 20000 })
  if (act) await act(page)
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log(name, 'errors=', errors, 'batchRequired=', await page.locator('#wh5-batch').count(), 'disabled=', await page.locator('#wh5-report').isDisabled())
  await ctx.close()
}

await shoot({ assigned: true, name: '1-assigned-prefilled', viewport: { width: 390, height: 844 } })
await shoot({ assigned: false, name: '2-unassigned-empty-disabled', viewport: { width: 390, height: 844 } })
await shoot({ assigned: false, name: '3-typed-enabled', viewport: { width: 390, height: 844 }, act: async (p) => {
  await p.fill('#wh5-batch-input', 'PC-20261018-0002')
  await p.click('#wh5-batch-candidates button')
} })
await shoot({ assigned: true, name: '4-receipt-after-report', viewport: { width: 390, height: 844 }, act: async (p) => {
  await p.click('#wh5-report')
  await p.waitForSelector('.wh5-notice', { timeout: 15000 }).catch(() => {})
  await p.waitForTimeout(300)
} })

await browser.close()
server.close()
