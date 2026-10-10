// case_ids: PG-065, BM-006
//
// 车间现场端触屏几何探针（issue #6667）—— **真实浏览器**读计算样式与盒子尺寸。
//
// 为什么必须真浏览器：`touch-action` / `:active` / 触控目标尺寸这类读数在 Node 里**没有布局引擎**，
// 静态判据（tests/worker-h5-6667-field-usability.test.mjs 的触屏两条）只能判「CSS 里写没写」——
// 那一条**不能**替代「浏览器算出来是什么」。本探针补的就是这一半。
//
// 零依赖：用**本机已装的 Chrome** + CDP（Node 24 自带 `WebSocket`）——不引 Playwright/Puppeteer
// （最少代码阶梯；也避开在 worktree 里装 node_modules，见 issue #5930）。
//
// 用法（在仓根）：
//   node scripts/probe-worker-h5-touch.mjs
//   node scripts/probe-worker-h5-touch.mjs --out acceptance/6667-field-probe.json
//   CHROME_PATH=/path/to/Chrome node scripts/probe-worker-h5-touch.mjs
// 退出码：0 = 全部探针通过；1 = 有探针不达标（打印逐条读数）；3 = 环境不具备（无 Chrome / 起不来）
//
// 🔴 本探针**只读**页面与样式，不登录、不碰真数据、不写任何库。

import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const H5 = join(ROOT, 'frontend/worker-h5')
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const CSS = readFileSync(join(H5, 'src/styles.css'), 'utf8')
const outArg = process.argv.indexOf('--out')
const OUT = outArg > -1 ? resolve(process.argv[outArg + 1]) : null
const PORT = Number(process.env.CDP_PORT ?? 9223)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 等 DevTools 端点起来（最多 ~15s）；起不来 ⇒ `null`。 */
async function waitForDevtools() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (res.ok) return await res.json()
    } catch {
      /* 还没起来 */
    }
    await sleep(250)
  }
  return null
}

/**
 * 探针页：把**真渲染输出**塞进 DOM，样式用**真 styles.css**（只换掉 `<main>` 初始内容）。
 *
 * 🔴 不手写 HTML 夹具：屏面由 `render.mjs` / `machine.mjs` 的真渲染函数产出 ——
 * 手写一份就是第二份口径（它会漂，而漂了不会变红）。
 */
function buildFixture() {
  return (html, ready) => `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8" /><style>${CSS}</style></head>
<body>
  <main id="worker-h5-root" class="wh5-root">${html}</main>
  <main id="machine-root" class="wh5-machine">${html}</main>
  <script>
    const $ = (sel) => document.querySelector(sel)
    const num = (v) => Number.parseFloat(v) || 0
    const read = (sel) => {
      const el = $(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        selector: sel,
        touchAction: cs.touchAction,
        cursor: cs.cursor,
        minHeight: num(cs.minHeight),
        height: Math.round(r.height * 10) / 10,
        width: Math.round(r.width * 10) / 10,
        background: cs.backgroundColor,
        transition: cs.transitionProperty,
      }
    }
    window.__probe = () => ({ ready: ${JSON.stringify(ready)}, items: {
      loginLink: read('#wh5-machine-login'),
      switchWorker: read('#wh5-machine-switch-worker'),
    } })
  </script>
</body></html>`
}

/** 一次 CDP 往返（id ↔ 结果），带超时。 */
function cdp(ws, state) {
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data)
    const p = pending.get(msg.id)
    if (!p) return
    pending.delete(msg.id)
    msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result)
  })
  return (method, params = {}) => {
    const myId = (id += 1)
    return new Promise((resolve, reject) => {
      pending.set(myId, { resolve, reject })
      ws.send(JSON.stringify({ id: myId, method, params }))
      setTimeout(() => { if (pending.delete(myId)) reject(new Error(`CDP 超时：${method}`)) }, 20000)
    })
  }
}

async function main() {
  // ── 造两条真屏面 ────────────────────────────────────────────────────────────
  const { renderPage, initialState } = await import(join(H5, 'src/render.mjs'))
  const { initialMachineState, renderScan } = await import(join(H5, 'src/machine.mjs'))
  const reportHtml = renderPage(
    { ...initialState(), worker: { workerName: '张师傅', workerNo: 'W-001' } },
    { set_no: 1, position: { position_name: '左窗' }, operation: { operation_id: 'op-1', logical_name: '打卷', qty: 2, unit: '片', unit_price: 3.5 }, alternatives: [], needs_selection: [] },
  )
  const reportBusy = renderPage(
    { ...initialState(), worker: { workerName: '张师傅' }, reporting: true },
    { set_no: 1, position: { position_name: '左窗' }, operation: { operation_id: 'op-1', logical_name: '打卷', qty: 2, unit: '片' }, alternatives: [], needs_selection: [] },
  )
  const machineHtml = renderScan(initialMachineState())

  const machineBusyHtml = renderScan({ ...initialMachineState(), worker: { workerName: '张师傅' } })

  const screens = [
    { name: 'report', html: reportHtml, ready: 'wh5-report' },
    { name: 'report-busy', html: reportBusy, ready: 'wh5-report' },
    { name: 'machine', html: machineHtml, ready: 'wh5-machine-login' },
    { name: 'machine-worker', html: machineBusyHtml, ready: 'wh5-machine-switch-worker' },
  ]

  // ── 起 Chrome（headless + 一次性 profile，跑完删） ────────────────────────────
  const profile = mkdtempSync(join(tmpdir(), 'wh5-probe-'))
  const chrome = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    'about:blank',
  ], { stdio: 'ignore' })

  const cleanup = () => {
    try { chrome.kill('SIGKILL') } catch { /* 已经退了 */ }
    try { rmSync(profile, { recursive: true, force: true }) } catch { /* 尽力而为 */ }
  }

  try {
    const version = await waitForDevtools()
    if (!version) {
      console.error('无法判定（3）：Chrome 的 DevTools 端点没起来 —— 环境不具备，不是判据不达标')
      return 3
    }
    const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
    const ws = new WebSocket(target.webSocketDebuggerUrl)
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true })
      ws.addEventListener('error', () => rej(new Error('WebSocket 连接失败')), { once: true })
    })
    const send = cdp(ws)
    await send('Page.enable')
    await send('Runtime.enable')

    const results = []
    for (const screen of screens) {
      const url = `data:text/html;charset=utf-8,${encodeURIComponent(buildFixture()(screen.html, screen.ready))}`
      await send('Page.navigate', { url })
      await sleep(400) // 数据 URL 的样式解析 + 一次布局
      const probe = await send('Runtime.evaluate', { expression: 'JSON.stringify(window.__probe())', returnByValue: true })
      const parsed = JSON.parse(probe.result.value)
      const items = { ...parsed.items }
      // 屏面专属：主按钮 / 幽灵按钮（报工页）· 机台【完成】与切换工人（机台页）
      const extra = screen.name === 'machine'
        ? ['#wh5-machine-login']
        : screen.name === 'machine-worker'
          ? ['#wh5-machine-switch-worker']
          : ['#wh5-report', '#wh5-rescan', '.wh5-ghost']
      for (const sel of extra) {
        const r = await send('Runtime.evaluate', {
          expression: `(() => { const el=document.querySelector(${JSON.stringify(sel)}); if(!el) return 'null';
            const cs=getComputedStyle(el), b=el.getBoundingClientRect();
            return JSON.stringify({ selector:${JSON.stringify(sel)}, touchAction:cs.touchAction, cursor:cs.cursor,
              minHeight:parseFloat(cs.minHeight)||0, height:Math.round(b.height*10)/10, width:Math.round(b.width*10)/10,
              background:cs.backgroundColor, disabled: el.disabled===true, text: (el.textContent||'').trim() }) })()`,
          returnByValue: true,
        })
        if (r.result.value !== 'null') items[sel] = JSON.parse(r.result.value)
      }
      // `:active` 是**状态**样式：用 CDP 强制伪类（没有真指针也能读）
      if (screen.name === 'report') {
        const node = await send('Runtime.evaluate', { expression: `document.querySelector('#wh5-report') ? 1 : 0`, returnByValue: true })
        if (node.result.value === 1) {
          await send('DOM.enable')
          const { root } = await send('DOM.getDocument', { depth: -1 })
          const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: '#wh5-report' })
          await send('CSS.enable')
          await send('CSS.forcePseudoState', { nodeId, forcedPseudoClasses: ['active'] })
          const active = await send('Runtime.evaluate', {
            expression: `(() => { const cs=getComputedStyle(document.querySelector('#wh5-report')); return JSON.stringify({background:cs.backgroundColor, transform:cs.transform}) })()`,
            returnByValue: true,
          })
          items['#wh5-report:active'] = { selector: '#wh5-report:active(forced)', ...JSON.parse(active.result.value) }
        }
      }
      results.push({ screen: screen.name, items })
    }
    ws.close()

    // ── 判据（每条都会红：读数不达标 ⇒ 非零退出并逐条打印） ──────────────────────
    const checks = []
    const add = (name, ok, reading) => checks.push({ name, ok, reading })
    /** 读某屏某选择器（null ⇒ undefined 也要能判）。 */
    const at = (screen, sel) => results.find((s) => s.screen === screen)?.items?.[sel] ?? null

    // ① 触屏目标：本包新加/改过的可点元素必须都不是浏览器默认（auto）行为
    for (const [screen, sel] of [
      ['report', '#wh5-report'],
      ['report', '#wh5-rescan'],
      ['report', '.wh5-ghost'],
      ['machine', '#wh5-machine-login'],
      ['machine-worker', '#wh5-machine-switch-worker'],
    ]) {
      const v = at(screen, sel)
      add(`${screen} ${sel} · 存在且 touch-action=manipulation`, Boolean(v) && v.touchAction === 'manipulation', v ? v.touchAction : '元素不存在')
    }

    // ② 触控目标尺寸 ≥44px（设计 §4.2 的两断点下限；现场戴手套）
    for (const [screen, sel] of [
      ['report', '#wh5-report'],
      ['machine', '#wh5-machine-login'],
      ['machine-worker', '#wh5-machine-switch-worker'],
    ]) {
      const v = at(screen, sel)
      add(`${screen} ${sel} · 触控目标高度 ≥44px`, (v?.height ?? 0) >= 44, v ? v.height : '元素不存在')
    }

    // ③ `:active` 真反馈（CDP 强制伪类读计算样式 —— 不是"CSS 里写了 :active"）
    const idle = at('report', '#wh5-report')
    const active = results.find((s) => s.screen === 'report')?.items?.['#wh5-report:active']
    add(
      'report #wh5-report:active · 按下有视觉变化（背景或位移）',
      Boolean(active) && (active.background !== idle?.background || active.transform !== 'none'),
      JSON.stringify(active ?? null),
    )

    // ④ 提交中：`disabled` + **视觉可分**（弱网下这是唯一反馈）
    const busy = at('report-busy', '#wh5-report')
    add(
      'report-busy #wh5-report · 提交中 disabled 且视觉可分（背景与空闲态不同）',
      busy?.disabled === true && busy.background !== idle?.background,
      JSON.stringify({ disabled: busy?.disabled, busyBg: busy?.background, idleBg: idle?.background, text: busy?.text }),
    )

    const payload = { generatedAt: new Date().toISOString(), chrome: version.Browser, screens: results, checks }
    if (OUT) writeFileSync(OUT, `${JSON.stringify(payload, null, 2)}\n`)
    for (const c of checks) console.log(`${c.ok ? '✅' : '❌'} ${c.name} → ${JSON.stringify(c.reading)}`)
    const failed = checks.filter((c) => !c.ok)
    console.log(`\n探针合计 ${checks.length} 条，不达标 ${failed.length} 条${OUT ? `；原始读数 = ${OUT}` : ''}`)
    return failed.length ? 1 : 0
  } finally {
    cleanup()
  }
}

process.exit(await main())
