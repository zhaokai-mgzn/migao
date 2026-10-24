// 工人端裁剪报工确认批次 —— 真浏览器截图（issue #7647 的多模态验收载体）
// 纯前端：静态服务 + 路由打桩（不碰真库），只为让「批次区块 / 禁用态 / 候选 / 回执」上屏。
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { createRequire } from 'node:module'
import { existsSync } from 'node:fs'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 路径一律从**本文件**推（换机器 / 换 worktree 都能复跑；不写死任何绝对路径）。
// 🔴 必须用 fileURLToPath 而不是 `URL.pathname`：本仓路径含空格（`ai native`）⇒ pathname 是 `%20` 编码，
//    直接拼路径会 ENOENT（实测）。
const REPO = fileURLToPath(new URL('../../../', import.meta.url))   // <repo>/
const ROOT = join(REPO, 'frontend/worker-h5')
const OUT = fileURLToPath(new URL('./', import.meta.url))           // 本目录（ui-evidence/）
const PORT = 5197
// playwright 挂在仓库 `tests/` 目录（与本仓 ui-smoke 的取法一致）。**worktree 里 tests/node_modules 未安装**
// （实测：linked worktree 只有源码）⇒ 依次尝试：环境变量 → 本仓 → 兄弟主仓库（worktree 形态）。
const PW_BASES = [
  process.env.PLAYWRIGHT_REQUIRE_BASE,
  join(REPO, 'tests/package.json'),
  // worktree 形态：主仓库与 worktree 同父（`migao-wt/<分支>`）或 upper 一级（`<parent>/migao`）各试一次
  join(REPO, '..', '..', 'migao', 'tests/package.json'),
  join(REPO, '..', 'migao', 'tests/package.json'),
].filter(Boolean)
const PW_BASE = PW_BASES.find((p) => existsSync(join(dirname(p), 'node_modules', 'playwright')))
if (!PW_BASE) {
  throw new Error('找不到 playwright：装到 <repo>/tests/node_modules，或用 PLAYWRIGHT_REQUIRE_BASE 指向含它的 package.json')
}
const { chromium } = createRequire(PW_BASE)('playwright')

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
    if (url.pathname.endsWith('/production/scan/complete')) return json({ operation_id: 'op-1', done_qty: 10, status: 'done', order_completed: false, set_no: '1', position: '布帘', set_progress: { done: 1, total: 2 }, set_completed: false, next_operation: { logical_name: '打包' }, batch_no: assigned ? 'PC-20261020-0007' : 'PC-20261018-0002', batch_remaining: -1.5, batch_shortage_meters: 4.5, next_batch_required: false, next_batch_no: null, next_batch_candidates: [] })
    return json({})
  })
  await page.goto(`http://127.0.0.1:${PORT}/index.html?t=scan-visual-token`)
  await page.waitForSelector('#wh5-report', { timeout: 20000 })
  if (act) await act(page)
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  // 回执屏上按钮已消失（报工成功换屏）⇒ isDisabled 会等不到元素，这里只做诊断、不阻断
  const report = page.locator('#wh5-report')
  const disabled = (await report.count()) === 0 ? 'n/a（已换屏）' : await report.isDisabled()
  console.log(name, 'errors=', errors, 'batchBlock=', await page.locator('#wh5-batch').count(), 'reportDisabled=', disabled)
  await ctx.close()
}

await shoot({ assigned: true, name: '01-assigned-prefilled', viewport: { width: 390, height: 844 } })
await shoot({ assigned: false, name: '02-unassigned-empty-disabled', viewport: { width: 390, height: 844 } })
await shoot({ assigned: false, name: '03-typed-enabled', viewport: { width: 390, height: 844 }, act: async (p) => {
  await p.fill('#wh5-batch-input', 'PC-20261018-0002')
  await p.click('#wh5-batch-candidates button')
} })
await shoot({ assigned: true, name: '04-receipt-after-report', viewport: { width: 390, height: 844 }, act: async (p) => {
  await p.click('#wh5-report')
  await p.waitForSelector('.wh5-notice', { timeout: 15000 }).catch(() => {})
  await p.waitForTimeout(300)
} })

await browser.close()
server.close()
