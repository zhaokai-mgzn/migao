// p6：H5 跨端一致性（部署面）—— 工人端 /w/ + 一体机 /w/machine.html
//
// 为什么单列：2026-10-04 的 P1 #6306（工人端整页白屏 ≈13 天）**只有真浏览器**能发现
// —— 「MIME 正确」是手段，「页面能渲染」才是目的（那是 curl 读数的假绿）。
// 判据：DOM 真值（#wh5-* 元素）+ 负对照（错 PIN 必须报错、且不得出现已登录态）+ 截图。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, PROBE, SUBJECT_SHA, api, loginApi, psql, scrub } from './lib.mjs'
import { launch, newPage, shot, stableText } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const APP = 'https://app.migaozn.com'
const stamp = String(Date.now()).slice(-6)
const WORKER_NO = `A06W${stamp}`
const WORKER_PIN = '246810'
const WORKER_NAME = `${PROBE}工人${stamp}`

const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })

async function createWorker() {
  const { token } = await loginApi('13800138000')
  const res = await api('POST', '/api/admin/workers', { token, body: { workerNo: WORKER_NO, name: WORKER_NAME, pin: WORKER_PIN } })
  const row = psql(`select id, worker_no, nickname, status from users where tenant_id=${TENANT_ID} and worker_no='${WORKER_NO}'`)[0]
  return { http: res.status, ok: res.status === 200 && !!row, row, text: res.text.slice(0, 200) }
}

async function workerH5(browser) {
  const { ctx, page } = await newPage(browser)
  const out = { url: null, loginView: false, badPinError: null, loginOk: false, currentWorker: null, shots: [] }
  try {
    // 🔴 入口必须带**租户上下文**（v1 用裸 `https://app.migaozn.com/w/` ⇒ 页面报
    //    「无法识别租户：请通过 <租户ID>.app.migaozn.com 域名访问或提供 tenantId」，
    //    于是 W2 的「负对照」是**因为租户都没解析**而绿 —— 那是判据侧假绿）。逐个试到解析成功为止。
    const entries = [
      `${APP}/w/?tenant_id=${TENANT_ID}`,
      `https://${TENANT_ID}.app.migaozn.com/w/`,
      `${APP}/w/`,
    ]
    // 独立复核 C-OBJ-09：v1 只记了「首个可用入口」，裸入口的报错**没有留证** ⇒ 现在**逐个都探**、逐条落盘
    const probes = []
    let entry = null
    // 每条入口用**独立 page**探（同一 page 上一次失败导航会打断下一次 —— 实测 chrome-error 打断）
    for (const url of entries) {
      const { ctx: c2, page: p2 } = await newPage(browser)
      let navErr = null
      try { await p2.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }) } catch (e) { navErr = String(e).slice(0, 100) }
      if (navErr) { probes.push({ url, navErr }); await c2.close().catch(() => {}); continue }
      await p2.waitForTimeout(4000)
      const t = (await stableText(p2)).text
      const tenantErr = /无法识别租户/.test(t)
      probes.push({ url, tenantErr, bodyLen: t.length, errText: (t.match(/[^\n]*无法识别租户[^\n]*/) || [''])[0].slice(0, 120) })
      if (!entry && !tenantErr && /工号|PIN/.test(t)) entry = url
      await c2.close().catch(() => {})
    }
    out.entry = entry
    // 独立复核 C-OBJ-09 的收口：**裸入口登录**到底报什么（v1 的「无法识别租户」当时无留证，现在实测落盘）
    try {
      const { ctx: c3, page: p3 } = await newPage(browser)
      await p3.goto(`${APP}/w/`, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await p3.waitForTimeout(4000)
      await p3.fill('#wh5-worker-no', WORKER_NO).catch(() => {})
      await p3.fill('#wh5-pin', WORKER_PIN).catch(() => {})
      await p3.click('#wh5-login').catch(() => {})
      await p3.waitForTimeout(5000)
      out.bareLoginProbe = {
        url: `${APP}/w/`,
        err: (await p3.locator('#wh5-error').innerText().catch(() => '')).slice(0, 120),
        currentWorker: await p3.locator('#wh5-current-worker').count(),
      }
      await shot(p3, 'h5-w-bare-login')
      await c3.close().catch(() => {})
    } catch (e) { out.bareLoginProbe = { error: String(e).slice(0, 150) } }
    if (entry) await page.goto(entry, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    else { rec('fail', 'P6-W1', '工人端入口不可用', `三个入口都不可用：${JSON.stringify(probes)}`); }
    out.entryProbes = probes
    out.url = page.url()
    const hasLogin = await page.locator('#wh5-login').count()
    const hasNo = await page.locator('#wh5-worker-no').count()
    const hasPin = await page.locator('#wh5-pin').count()
    const { text: t0 } = await stableText(page)
    out.loginView = !!(hasLogin && hasNo && hasPin)
    out.bodyLen = t0.length
    out.shots.push(await shot(page, 'h5-w-login'))
    rec(out.loginView ? 'pass' : 'fail', 'P6-W1', '工人端 /w/ 首屏渲染（带租户上下文；#6306 修复后复探）',
      `入口=${out.entry || '(全部失败)'} 探测=${JSON.stringify(probes)} url=${out.url} #wh5-login=${hasLogin} #wh5-worker-no=${hasNo} #wh5-pin=${hasPin} bodyLen=${t0.length}；正文头=${JSON.stringify(t0.slice(0, 120))}`,
      ['out/shots/h5-w-login.png', 'DOM #wh5-login/#wh5-worker-no/#wh5-pin'])

    if (out.loginView) {
      // 负对照：错 PIN ⇒ 必须留在登录态 + 显示错误；不得出现已登录元素
      await page.fill('#wh5-worker-no', WORKER_NO)
      await page.fill('#wh5-pin', '000000')
      await page.click('#wh5-login')
      await page.waitForTimeout(4000)
      const stillLogin = await page.locator('#wh5-login').isVisible().catch(() => false)
      const err = await page.locator('#wh5-error').innerText().catch(() => '')
      const loggedIn = await page.locator('#wh5-current-worker').count()
      out.badPinError = err
      out.shots.push(await shot(page, 'h5-w-badpin'))
      rec(stillLogin && !!err && loggedIn === 0 ? 'pass' : 'fail', 'P6-W2', '工人端错 PIN 负对照',
        `仍在登录态=${stillLogin} 错误文案=${JSON.stringify(err.slice(0, 80))} 已登录元素数=${loggedIn}`,
        ['out/shots/h5-w-badpin.png'])

      // 正路：真工号 + 真 PIN
      await page.fill('#wh5-worker-no', WORKER_NO)
      await page.fill('#wh5-pin', WORKER_PIN)
      await page.click('#wh5-login')
      await page.waitForTimeout(5000)
      const cur = await page.locator('#wh5-current-worker').innerText().catch(() => '')
      out.currentWorker = cur
      out.loginOk = !!cur && cur.includes('A06')
      out.shots.push(await shot(page, 'h5-w-logged'))
      rec(out.loginOk ? 'pass' : 'fail', 'P6-W3', '工人端真实登录（工号+PIN）并进入报工页',
        `#wh5-current-worker=${JSON.stringify(cur)}；期望含工号/姓名 ${WORKER_NO}`,
        ['out/shots/h5-w-logged.png'])
      const ids = await page.evaluate(() => Array.from(document.querySelectorAll('[id^=wh5-]')).map((e) => e.id))
      out.domIds = ids
      rec(ids.length > 3 ? 'pass' : 'fail', 'P6-W4', '登录后报工页 DOM 就位',
        `#wh5-* 元素 ${ids.length} 个：${JSON.stringify(ids.slice(0, 20))}`, ['DOM 快照'])
    }
  } catch (e) {
    rec('fail', 'P6-W0', '工人端旅程异常', String(e).slice(0, 300))
  } finally { await ctx.close().catch(() => {}) }
  return out
}

async function machineH5(browser) {
  const { ctx, page } = await newPage(browser)
  try {
    await page.goto(`${APP}/w/machine.html`, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(4000)
    const { text } = await stableText(page)
    const ids = await page.evaluate(() => Array.from(document.querySelectorAll('[id^=wh5-]')).map((e) => e.id))
    const shotPath = await shot(page, 'h5-machine')
    rec(text.length > 20 || ids.length > 0 ? 'pass' : 'fail', 'P6-M1', '一体机页 /w/machine.html 非空白',
      `正文 ${text.length} 字符；#wh5-* 元素 ${ids.length} 个；正文头=${JSON.stringify(text.slice(0, 140))}`,
      [shotPath])
  } catch (e) {
    rec('fail', 'P6-M0', '一体机页异常', String(e).slice(0, 300))
  } finally { await ctx.close().catch(() => {}) }
}

async function main() {
  const w = await createWorker()
  rec(w.ok ? 'pass' : 'fail', 'P6-W0a', '建测工人档案（工号+PIN）',
    `POST /api/admin/workers HTTP ${w.http}；DB users#${w.row?.id} worker_no=${w.row?.worker_no} status=${w.row?.status} ${w.ok ? '' : w.text}`,
    ['POST /api/admin/workers'])
  const browser = await launch()
  const h5 = await workerH5(browser)
  await machineH5(browser)
  await browser.close()
  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  writeFileSync(join(OUT, 'p6-h5.json'), JSON.stringify(scrub({
    at: new Date().toISOString(), subjectSha: SUBJECT_SHA, app: APP, worker: { no: WORKER_NO, name: WORKER_NAME }, workerCreate: w, h5, counts, rows: R,
  }), null, 2))
  console.log('== p6 counts:', JSON.stringify(counts))
  for (const x of R) console.log(`  [${x.state}] ${x.id} ${x.name} — ${x.detail.slice(0, 260)}`)
}

main().catch((e) => { console.error('p6 失败:', e); process.exit(1) })
