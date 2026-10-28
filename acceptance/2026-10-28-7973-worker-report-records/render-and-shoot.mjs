// case_ids: PG-098, PG-099
//
// 扫码报工屏「返工 / 质检记录」视觉证据的**可复跑**载体（issue #7973）。
//
// 口径（照实写清楚，别把夹具截图读成真实登录截图）：
//   ① 页面 HTML 由**真** `render.mjs#renderPage` 产出（不手写夹具 —— 手写就是第二份口径）；
//   ② 样式用**真** `styles.css`；
//   ③ 视口 = CDP `Emulation.setDeviceMetricsOverride({width:390,height:844,mobile:true})`（手机宽，
//      与真机同一条 viewport meta）；截图 `captureBeyondViewport` 取整页；
//   ④ 数据 = 夹具（不是真库、不是真实登录）—— 真栈读写由后端测试钉住，这里只判**页面长相**。
//
// 用法（在仓根）：
//   node acceptance/2026-10-28-7973-worker-report-records/render-and-shoot.mjs
//   CHROME_PATH=/path/to/Chrome node acceptance/.../render-and-shoot.mjs
// 产物：同目录 01-scan-report-records.png + 终端打印 innerWidth / scrollWidth / 卡片宽。
//
// 退出码：0 = 截图已生成且无横向溢出；1 = 有横向溢出（真缺陷）；3 = 环境不具备（无 Chrome）。

import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '../..')
const H5 = join(ROOT, 'frontend/worker-h5')
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PORT = Number(process.env.CDP_PORT ?? 9332)
const OUT = join(HERE, '01-scan-report-records.png')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const { renderPage, initialState, reduce } = await import(join(H5, 'src/render.mjs'))

// 一件「有未完结返工单 + 质检待复检」的最坏排版：两块的记录/动作/提示全在屏上。
const VIEW = {
  set_no: 'JG-20261027-5878-001',
  position: {
    order_item_id: 'item-1',
    position_name: '奶油风纯色遮光窗帘 桂月白露系列 2659-01 桂月白露',
  },
  operation: { operation_id: 'op-1', logical_name: '布带', qty: 2, unit: '套', unit_price: 1.5, determined_by: 'worker' },
  completed: false,
  rework_records: [
    { rework_no: 'RG202610280002', logical_name: '布带', operation_name: '布带-布', qty: 2, reason: '布面污渍', status: 'draft', worker_name: '张师傅', created_at: '2026-10-28T09:15:00+08:00' },
    { rework_no: 'RG202610270001', logical_name: '布带', operation_name: '布带-布', qty: 2, reason: '色差', status: 'done', worker_name: '张师傅', created_at: '2026-10-27T16:40:00+08:00' },
  ],
  set_overview: { positions: [{ order_item_id: 'item-1', position_name: '布帘', operations: [
    { operation_id: 'op-1', logical_name: '布带', qty: 2, unit: '套', unit_price: 1.5, status: 'done', done_qty: 2 },
    { operation_id: 'op-2', logical_name: '车缝', qty: 2, unit: '套', unit_price: 2, status: 'pending', done_qty: 0 },
  ] }] },
}
const REWORK = { result: 'rework', result_label: '返工', reason: '缝线开裂', inspector_name: '张师傅', inspected_at: '2026-10-28T09:20:00+08:00' }
const PASS = { result: 'pass', result_label: '合格', inspector_name: '李质检', inspected_at: '2026-10-27T10:00:00+08:00' }

let state = reduce(initialState(), { type: 'worker', worker: { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 } })
state = reduce(state, { type: 'pages', pages: ['report', 'inspect'] })
state = reduce(state, { type: 'resolved', view: VIEW })
state = reduce(state, { type: 'qualityLoaded', latest: REWORK, records: [REWORK, PASS] })

const css = readFileSync(join(H5, 'src/styles.css'), 'utf8')
const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<style>${css}</style></head><body><main id="worker-h5-root" class="wh5-root">${renderPage(state)}</main></body></html>`
const pageFile = join(mkdtempSync(join(tmpdir(), 'wh5-7973-')), 'page.html')
writeFileSync(pageFile, html)

const profile = mkdtempSync(join(tmpdir(), 'wh5-7973-profile-'))
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu', 'about:blank'], { stdio: 'ignore' })

async function waitForDevtools() {
  for (let i = 0; i < 80; i += 1) {
    try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) return true } catch { /* 还没起来 */ }
    await sleep(200)
  }
  return false
}

let code = 0
try {
  if (!(await waitForDevtools())) { console.error('无法判定（3）：Chrome DevTools 没起来'); process.exit(3) }
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true })
    ws.addEventListener('error', () => rej(new Error('WebSocket 连接失败')), { once: true })
  })
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data)
    const p = pending.get(msg.id)
    if (!p) return
    pending.delete(msg.id)
    msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result)
  })
  const cdp = (method, params = {}) => new Promise((resolve2, reject) => {
    const myId = (id += 1)
    pending.set(myId, { resolve: resolve2, reject })
    ws.send(JSON.stringify({ id: myId, method, params }))
    setTimeout(() => { if (pending.delete(myId)) reject(new Error(`CDP 超时：${method}`)) }, 20000)
  })

  await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true })
  await cdp('Page.navigate', { url: `file://${pageFile}` })
  await sleep(600)
  const measured = await cdp('Runtime.evaluate', {
    expression: `JSON.stringify({ inner: innerWidth, scrollW: document.documentElement.scrollWidth,
      cardW: document.querySelector('.wh5-card')?.getBoundingClientRect().width,
      entriesW: document.getElementById('wh5-worker-entries')?.getBoundingClientRect().width })`,
    returnByValue: true,
  })
  console.log('读数', measured.result.value)
  const shot = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  writeFileSync(OUT, Buffer.from(shot.data, 'base64'))
  const m = JSON.parse(measured.result.value)
  if (m.scrollW > m.inner) {
    console.error(`❌ 横向溢出：scrollWidth ${m.scrollW} > innerWidth ${m.inner}`)
    code = 1
  } else {
    console.log(`✅ 无横向溢出（${m.scrollW}/${m.inner}）⇒ ${OUT}`)
  }
  ws.close()
} finally {
  try { chrome.kill('SIGKILL') } catch { /* 已经退了 */ }
  try { rmSync(profile, { recursive: true, force: true }) } catch { /* 尽力而为 */ }
}
process.exit(code)
