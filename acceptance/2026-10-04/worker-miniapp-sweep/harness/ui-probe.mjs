// ui-probe.mjs — 部署面 worker-h5 / bmini 页面**可达性与真实错误读数**探针（装置级，不判产品）
//
// 目的：BRIEF 要求 UI 级「可行则做，不可行如实登记 skip —— 不得用『页面能打开』冒充写面验证」。
// 本探针只做**三件可复核的事**，不做写面判定：
//   ① 真实无头浏览器打开部署页 → 记录 DOM 里**实际存在**的元素 id/文本；
//   ② 记录浏览器网络面（含被 CORS 拦掉的请求）与 console error；
//   ③ 截图留档（路径登记）。
// 判定是否「UI 写面可验」由 p5-ui-deployed.mjs 依据本探针的读数决定。
import { writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs'
import { log, nowCST, outPath } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const SHOT = join(HERE, '..', 'out', 'shots')
mkdirSync(SHOT, { recursive: true })

const TARGETS = [
  { key: 'workerH5', url: process.env.WORKER_UI_URL || 'https://app.migaozn.com/w/', viewport: { width: 420, height: 900 } },
  { key: 'bmini', url: process.env.BMINI_UI_URL || 'https://app.migaozn.com/b/', viewport: { width: 420, height: 900 } },
]

const browser = await chromium.launch()
const out = { at: nowCST(), targets: {} }

for (const t of TARGETS) {
  const page = await browser.newPage({ viewport: t.viewport })
  const net = []
  const consoleErrors = []
  const pageErrors = []
  page.on('request', (r) => { if (/\/(api|worker)\//.test(r.url())) net.push({ m: r.method(), u: r.url(), body: r.postData()?.slice(0, 200) ?? null, t: 'req' }) })
  page.on('response', async (r) => {
    if (/\/(api|worker)\//.test(r.url())) {
      let body = ''
      try { body = (await r.text()).slice(0, 300) } catch { /* opaque */ }
      net.push({ m: r.method(), u: r.url(), status: r.status(), body, t: 'res' })
    }
  })
  page.on('requestfailed', (r) => net.push({ m: r.method(), u: r.url(), failed: r.failure()?.errorText ?? null, t: 'failed' }))
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 300)) })
  page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 300)))

  let goto = null
  try {
    const resp = await page.goto(t.url, { waitUntil: 'networkidle', timeout: 45000 })
    goto = resp?.status() ?? null
  } catch (e) { goto = `GOTO_ERROR ${String(e.message).slice(0, 160)}` }
  await page.waitForTimeout(2500)

  const dom = await page.evaluate(() => {
    const ids = [...document.querySelectorAll('[id]')].map((e) => e.id).slice(0, 80)
    const inputs = [...document.querySelectorAll('input,button,select')].map((e) => ({
      tag: e.tagName.toLowerCase(), id: e.id || null, type: e.type || null,
      ph: e.getAttribute('placeholder') || null, txt: (e.innerText || '').trim().slice(0, 30),
    })).slice(0, 40)
    return { title: document.title, bodyText: (document.body?.innerText || '').slice(0, 1200), ids, inputs, html: document.body?.innerHTML?.length ?? 0 }
  }).catch((e) => ({ error: String(e).slice(0, 200) }))

  const shot = join(SHOT, `probe-${t.key}.png`)
  await page.screenshot({ path: shot, fullPage: false }).catch(() => {})
  out.targets[t.key] = { url: t.url, httpStatus: goto, dom, net, consoleErrors, pageErrors, screenshot: `out/shots/probe-${t.key}.png` }
  await page.close()
  log(`UI 探针 ${t.key}: HTTP ${goto} ids=${JSON.stringify(dom.ids?.slice(0, 20))} 网络条=${net.length} console错=${consoleErrors.length}`)
}

await browser.close()
writeFileSync(outPath('UI-probe.json'), JSON.stringify(out, null, 2))
process.exit(0)
