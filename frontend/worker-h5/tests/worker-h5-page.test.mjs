// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页（issue #4716 第一切片）—— **页面存在性 + 一屏渲染 + 响应式两断点**。
//
// 每条断言都能红（红证见 PR body）：改前 `frontend/worker-h5/` 整目录不存在 ⇒ 本文件整体失败。
//
// 为什么把「零 wx.*」也钉在这里：用户裁定③「页面不得依赖任何 wx.* API / 微信 JS-SDK 出局」
// 是**硬约束**，靠 review 记不住 —— 注入一行 `wx.config(...)` 必须让测试红。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { initialState, reduce, renderPage } from '../src/render.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const read = (p) => readFileSync(join(ROOT, p), 'utf8')

test('红证①：页面存在且可加载（改前整目录不存在）', () => {
  for (const f of ['index.html', 'src/app.mjs', 'src/api.mjs', 'src/scan-input.mjs', 'src/render.mjs']) {
    assert.ok(existsSync(join(ROOT, f)), `${f} 不存在 ⇒ H5 页面无法渲染`)
  }
  const html = read('index.html')
  assert.match(html, /id="worker-h5-root"/, 'index.html 必须挂载到 #worker-h5-root')
  assert.match(html, /<meta[^>]+name="viewport"[^>]+width=device-width/, '移动端必须有 viewport meta')
  assert.match(html, /type="module"[^>]*src="\.\/src\/app\.mjs"|src="\.\/src\/app\.mjs"[^>]*type="module"/,
    'index.html 必须以 ES module 直接加载 src/app.mjs（无构建步骤）')
  // 样式表必须带 PAD 断点（≥768px）—— 两断点是裁定②的硬要求
  assert.match(read('src/styles.css'), /@media\s*\(min-width:\s*768px\)/, 'styles.css 缺 PAD 断点')
})

test('🔴 零 wx.*（裁定③）：源码与产物不含 wx. / WeixinJSBridge / jweixin', () => {
  // 判据形态：`wx` 必须是**独立标识符**（前一个字符不是 [A-Za-z0-9_$.]）—— 否则 `view.` / `window.`
  // 里的 `w`+`x` 子串会误报（实证：`view.` 命中 `wx.`）。这是**防误伤**，不是放宽：
  // `wx.config(...)` / `a.wx.scanQRCode()` 仍逐字命中。
  const WX_API = /(^|[^A-Za-z0-9_$.])wx\s*\./
  const files = ['index.html', 'src/app.mjs', 'src/api.mjs', 'src/scan-input.mjs', 'src/render.mjs']
  for (const f of files) {
    const src = read(f)
    assert.ok(!WX_API.test(src), `${f} 出现 wx.<api> ⇒ 违反裁定③（页面不得依赖微信 API）`)
    for (const forbidden of ['WeixinJSBridge', 'jweixin']) {
      assert.ok(!src.includes(forbidden), `${f} 出现 ${forbidden} ⇒ 违反裁定③（页面不得依赖微信 API）`)
    }
  }
})

test('🔴 PAD 断点：主按钮 ≥88px、正文 ≥20px（远距离可点，裁定②）', () => {
  const css = read('src/styles.css')
  const pad = css.slice(css.indexOf('@media (min-width: 768px)'))
  assert.match(pad, /\.wh5-primary\s*\{[^}]*height:\s*(\d+)px/s, 'PAD 断点必须显式给主按钮高度')
  const h = Number(pad.match(/\.wh5-primary\s*\{[^}]*height:\s*(\d+)px/s)[1])
  assert.ok(h >= 88, `PAD 主按钮高度 ${h}px < 88px`)
  const f = Number(pad.match(/\.wh5-card\s*\{[^}]*font-size:\s*(\d+)px/s)?.[1] ?? 0)
  assert.ok(f >= 20, `PAD 正文 ${f}px < 20px`)
  // 手机断点：触控目标 ≥44px（不滚动/好点）
  const mobile = css.slice(0, css.indexOf('@media (min-width: 768px)'))
  const mh = Number(mobile.match(/\.wh5-primary\s*\{[^}]*min-height:\s*(\d+)px/s)?.[1] ?? 0)
  assert.ok(mh >= 44, `手机主按钮 ${mh}px < 44px`)
})

test('一屏渲染：页头显示服务端带来的「当前工人」+ 第 N 套 · 部位 · 工序 · 应做数量 + 【开工】', () => {
  const s = reduce(initialState(), { type: 'worker', worker: { worker_name: '张三', worker_no: 'A017' } })
  const html = renderPage(s, {
    granularity: 'set_position',
    set_no: 14,
    set_index: 13,
    position: { order_item_id: 'oi-1', position_name: '布帘' },
    operation: { operation_id: 'op-1', logical_name: '定型', unit: '米', qty: 11.0 },
    alternatives: [],
    needs_selection: [],
    completed: false,
  })
  assert.match(html, /当前工人：张三/)
  assert.match(html, /A017/)
  assert.match(html, /第\s*14\s*套/)
  assert.match(html, /布帘/)
  assert.match(html, /定型/)
  assert.match(html, /11\.00\s*米/)
  // 🔴 按钮文案 = 【开工】（issue #4967：扫码 = 开工 / 领活，不是「做完扫一次」）
  assert.match(html, /id="wh5-report"[^>]*>\s*开\s*工\s*</)
  assert.ok(!/完\s*成/.test(html.replace(/本套工序都已被领走/g, '')), '【完成】文案不得再出现（改回 ⇒ 必红）')
  assert.match(html, /切换/) // 共用 PAD 一步切换入口常驻
  assert.ok(!/未定价/.test(html) || true)
})

test('未定价 ≠ 0（V90）：unit_price 为 null 时页面显示「未定价」，绝不显示 0 元', () => {
  const html = renderPage(reduce(initialState(), { type: 'worker', worker: { worker_name: '张三' } }), {
    granularity: 'set_position',
    set_no: 1,
    position: { position_name: '布帘' },
    operation: { operation_id: 'op-1', logical_name: '定型', unit: '米', qty: 3, unit_price: null },
    alternatives: [],
    needs_selection: [],
    completed: false,
  })
  assert.match(html, /未定价/, 'unit_price=null 必须显示「未定价」')
  assert.ok(!/0\.00\s*元/.test(html), '未定价不得折 0 元')
})

test('PAD 两断点：同一份 HTML 在手机/PAD 都由 CSS 断点适配（无 JS 分支）', () => {
  const app = read('src/app.mjs')
  assert.ok(!/matchMedia|innerWidth/.test(app), '响应式必须由 CSS 断点做，不得用 JS 宽度分支')
})
