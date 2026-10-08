// ui-deployed-mime.mjs — 部署面 worker-h5 **整页不可用**的最小复现 + 单变量对照
//
// 线索（ui-probe.mjs 读数，逐字）：
//   workerH5 https://app.migaozn.com/w/  HTTP 200 ∧ title="工人报工" ∧ body innerText=""
//   ∧ console error: `Failed to load module script: Expected a JavaScript-or-Wasm module script
//     but the server responded with a MIME type of "application/octet-stream".`
//   ⇒ JS 模块根本没执行（#worker-h5-root 里 0 个子节点 / 0 个 input / 0 个 button）。
//
// 本段做**单变量对照**（不猜、不编归因）：
//   ① 取 index.html 原文，抽出**它自己声明**的入口脚本 URL（不自己拼路径）；
//   ② 对该 URL 发请求，记 **Content-Type / Content-Encoding / content-length / 首字节**；
//   ③ 对照：同一 host 下**同族但 MIME 正确**的静态资源（如 index.html 自身 / bmini 的 js）
//      ⇒ 证明「不是整个 CDN 都坏」，而是**这一条路径**的 MIME 配置。
import { writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs'
import { log, nowCST, outPath, api } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const SHOT = join(HERE, '..', 'out', 'shots')
mkdirSync(SHOT, { recursive: true })
const W = process.env.WORKER_UI_URL || 'https://app.migaozn.com/w/'
const B = process.env.BMINI_UI_URL || 'https://app.migaozn.com/b/'

const out = { at: nowCST(), workerH5: W, bmini: B, steps: [] }

// ── ① index.html 原文（worker-h5）──
const html = await fetch(W, { headers: { 'user-agent': 'migao-acceptance-line1' } })
const htmlText = await html.text()
const scriptSrcs = [...htmlText.matchAll(/<script[^>]*\bsrc=["']([^"']+)["']/g)].map((m) => m[1])
const linkHrefs = [...htmlText.matchAll(/<link[^>]*\bhref=["']([^"']+)["']/g)].map((m) => m[1])
out.steps.push({
  id: 'D1.index-html', status: html.status, contentType: html.headers.get('content-type'),
  bodyLen: htmlText.length, bodyText: htmlText.slice(0, 900), scriptSrcs, linkHrefs,
})

// ── ② 逐个入口脚本：Content-Type 是判据 ──
const scriptProbes = []
for (const src of scriptSrcs) {
  const url = new URL(src, W).href
  const r = await fetch(url, { headers: { 'user-agent': 'migao-acceptance-line1' } })
  const buf = Buffer.from(await r.arrayBuffer())
  scriptProbes.push({
    src, url, status: r.status,
    contentType: r.headers.get('content-type'),
    contentEncoding: r.headers.get('content-encoding'),
    contentLength: r.headers.get('content-length'),
    first80: buf.toString('utf8', 0, 80),
  })
}
out.steps.push({ id: 'D2.entry-script-content-types', probes: scriptProbes })

// ── ③ 对照面：bmini 的入口脚本（同 host 家族；证明不是「全站坏」）──
const bHtml = await fetch(B, { headers: { 'user-agent': 'migao-acceptance-line1' } })
const bText = await bHtml.text()
const bScripts = [...bText.matchAll(/<script[^>]*\bsrc=["']([^"']+)["']/g)].map((m) => m[1])
const bProbes = []
for (const src of bScripts) {
  const url = new URL(src, B).href
  const r = await fetch(url, { headers: { 'user-agent': 'migao-acceptance-line1' } })
  bProbes.push({ src, url, status: r.status, contentType: r.headers.get('content-type'), contentLength: r.headers.get('content-length') })
}
out.steps.push({ id: 'D3.control-bmini-scripts', httpStatus: bHtml.status, scripts: bScripts, probes: bProbes })

// ── ④ 真实浏览器：模块**未执行**的 DOM 面证据 ──
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 420, height: 900 } })
const errs = []
page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
page.on('pageerror', (e) => errs.push('pageerror: ' + String(e)))
await page.goto(W, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {})
await page.waitForTimeout(2500)
const dom = await page.evaluate(() => ({
  title: document.title,
  rootChildren: document.getElementById('worker-h5-root')?.children.length ?? null,
  inputs: document.querySelectorAll('input').length,
  buttons: document.querySelectorAll('button').length,
  bodyText: document.body.innerText,
}))
await page.screenshot({ path: join(SHOT, 'D-mime-workerh5-blank.png') })
await page.close()
await browser.close()
out.steps.push({ id: 'D4.real-browser-dom', consoleErrors: errs, dom, screenshot: 'out/shots/D-mime-workerh5-blank.png' })

// ── ⑤ 交叉对照：同一份静态产物在**本机只读静态服务**上会不会也这样？──
//     这里只用 HTTP 头做对照（不启服务、不碰产品代码）：直接看部署侧响应头是否声明 JS。
out.steps.push({
  id: 'D5.judgement-inputs',
  expectation: 'HTML 用 <script type="module" src=…> 加载入口 ⇒ 该资源 Content-Type 必须是 JS MIME'
    + '（text/javascript / application/javascript / …+json 之类），否则浏览器按 HTML 规范**拒绝执行**',
  actual: scriptProbes.map((p) => `${p.src} ⇒ ${p.contentType}`),
  note: '期望来源 = HTML 规范对 module script 的 MIME 强制（浏览器 console 已逐字给出该判定），不是本包自创口径',
})

writeFileSync(outPath('P0c-ui-deployed-mime.json'), JSON.stringify(out, null, 2))
log(`部署面 MIME 判据: worker-h5 入口脚本 Content-Type=${JSON.stringify(scriptProbes.map((p) => p.contentType))}`)
log(`对照 bmini 入口脚本 Content-Type=${JSON.stringify(bProbes.map((p) => p.contentType))}`)
log(`真实浏览器 DOM: ${JSON.stringify(dom)}`)
process.exit(0)
