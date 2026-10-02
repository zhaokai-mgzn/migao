#!/usr/bin/env node
/**
 * Playwright 页面多模态验收 · **证据采集器**（`migao-dev-flow` §15.7 的承载体）
 *
 * 为什么有它：改 web 页面时，「断言绿 + 构建绿」**看不见**用户看到的东西（文案读不读得懂、
 * 控件挤不挤、有没有裸露的 markdown、吸底条挡不挡内容）。§15.7 要求**每轮改 web 页面都跑一轮
 * 真实浏览器的多模态验收** —— 本脚本负责**确定性地**产出那一轮的证据（截图 + DOM 逐字文本 +
 * testid 清单），判定由 AI **读图**完成（读图能力缺失时按 §15.5 用视觉模型开子代理）。
 *
 * 用法（在仓库根执行；`@playwright/test` 从 `<repo>/tests/node_modules` 解析 ——
 * 从别的工作树跑时设 `MIGAO_REPO_ROOT=<仓根>`）：
 *
 *   node .agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
 *     --site http://localhost:3001 --path /orders/new --shot fee-summary-bar --open-details --out /tmp/ui-acceptance
 *
 *   # 只探登录页形态（不登录、不截图、不需要账号/后端）—— 改过登录页、或工具莫名超时时**第一条命令**：
 *   node .agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
 *     --login-shape-check --site http://localhost:3001
 *
 * 参数：
 *   --site <url>        站点（默认 https://merchant.migaozn.com；**本机唯一入口 = http://localhost:3001**，见 §15.7）
 *   --path <path>       目标路径（`--login-shape-check` 模式不需要）
 *   --phone/--code      登录（默认 13800138000 / 123456 = 本机 `backend/admin-api/.env` 的 `SMS_BYPASS_CODE`）
 *   --out <dir>         证据目录（默认 /tmp/ui-acceptance-<时间戳>）
 *   --width/--height    视口（默认 1440×980）
 *   --shot <testid>     额外截该元素（可重复；也接受 CSS 选择器）
 *   --fill <ph>=<val>   按 placeholder 子串填值（可重复）
 *   --click <text>      点击文本（可重复，用于展开折叠块等）
 *   --open-details      打开页面上所有 <details>
 *   --allow-login-page  允许停在登录页（**默认禁止** —— 见下）
 *   --login-shape-check 只做登录页形态自检（不登录 / 不截图 / 不需要 `--path`）
 *
 * 产出：`01-full.png`（全页）+ `<testid>.png` + `page-text.txt`（body 逐字）+ `testids.txt` + `summary.json`。
 *
 * 🔴 **登录页形态指纹（issue #6009）**：登录页是**客户端渲染**的（`useSearchParams` ⇒ SSR 出来的是空壳，
 *   连「手机验证码」这四个字都不在 HTML 里）。因此「domcontentloaded 后凭手速点击」的写法在**慢首帧**下
 *   必然静默失败：点了一个还不存在的元素（异常被 `.catch` 吞掉）⇒ 页面仍停在「员工登录」tab ⇒
 *   后面等手机号输入框 30s ⇒ `TimeoutError`（#5976+#5977 / #5983 两包实测撞的就是这一形态）。
 *   本脚本三条硬约束：① **先等表单真渲染出来**（可见的 `input`）；② 核对 `LOGIN_SHAPE` 指纹
 *   （两页签名 + 副标题、手机号/验证码占位、`获取验证码` / `登 录` 按钮）——**不匹配即红**并逐条报出缺失项；
 *   ③ 只在指纹通过后按**语义锚**（`role=tab` / `getByLabel`）操作，每一步失败都**具名报出**、绝不静默。
 *
 * 🔴 **fail-closed（防假绿）**：登录未生效（仍停在 `/login`）或页面零 `data-testid` ⇒ **非零退出**。
 * 「截了一张登录页/空白页」不是验收证据 —— 它比不跑更危险（看起来做过）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const argv = process.argv.slice(2)
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : dflt
}
const argAll = (name) => argv.flatMap((a, i) => (a === `--${name}` && argv[i + 1] && !argv[i + 1].startsWith('--') ? [argv[i + 1]] : []))
const has = (name) => argv.includes(`--${name}`)

const SCRIPT_REL = '.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs'
const die = (msg) => { console.error(`❌ ${msg}`); process.exit(1) }

/**
 * 登录页形态指纹（真源 = `frontend/admin-web/src/app/login/page.tsx`，issue #5485 起的两页签形态）。
 *
 * 页面改版 ⇒ 改这里**一处**（并升 `migao-dev-flow` 的 version + 更新 §15.7）；
 * 忘了改 ⇒ 运行时**当场红**（`--login-shape-check` 就能验），不用等下一个人撞 `TimeoutError`。
 */
const LOGIN_SHAPE = {
  id: 'login-tabs-v5485',
  tabs: [
    { label: '员工登录', hint: '账号密码' },
    { label: '管理员登录', hint: '手机验证码' },
  ],
  phonePlaceholderIncludes: '手机号',
  codePlaceholderIncludes: '验证码',
  sendCodeText: '获取验证码',
  submitTextRe: /登\s*录/,
}

const site = arg('site', 'https://merchant.migaozn.com').replace(/\/$/, '')
const shapeCheckOnly = has('login-shape-check')
const target = arg('path')
if (!target && !shapeCheckOnly) die('缺 `--path`（例：--path /orders/new）；只想验登录页形态请用 `--login-shape-check`')
const phone = arg('phone', '13800138000')
const code = arg('code', '123456')
const width = Number(arg('width', 1440))
const height = Number(arg('height', 980))
const outDir = arg('out', `/tmp/ui-acceptance-${new Date().toISOString().replace(/[:.]/g, '-')}`)
const shots = argAll('shot')
const fills = argAll('fill')
const clicks = argAll('click')

const repoRoot = process.env.MIGAO_REPO_ROOT || process.cwd()
const require = createRequire(path.join(repoRoot, 'tests', 'package.json'))
let chromium
try {
  ;({ chromium } = require('@playwright/test'))
} catch (e) {
  die(`解析不到 @playwright/test（试过 ${path.join(repoRoot, 'tests', 'package.json')}）：先跑 \`npm --prefix tests install\`，或设 MIGAO_REPO_ROOT=<仓根>`)
}

const oneLine = (e) => String(e).split('\n')[0].slice(0, 240)

/**
 * 「页面形态已变」的统一出口（fail-closed）。**不许**把选择器超时（`TimeoutError`）当通过 ——
 * 那种形态既不给归因、也不给出口，是「看起来跑了、其实没跑」的典型（§15.7 假绿清单）。
 */
function dieShape(what, details = []) {
  console.error('')
  console.error('❌ 页面形态已变 —— 登录页与工具失配（fail-closed：拒绝把超时 / 空白当通过）')
  console.error(`   站点：${site}`)
  console.error(`   期望：${LOGIN_SHAPE.id} —— 「${LOGIN_SHAPE.tabs.map((t) => `${t.label}/${t.hint}`).join('」+「')}」两页签 + 占位含「${LOGIN_SHAPE.phonePlaceholderIncludes}」/「${LOGIN_SHAPE.codePlaceholderIncludes}」的输入框 + 「${LOGIN_SHAPE.sendCodeText}」「登 录」按钮`)
  console.error(`   实测：${what}`)
  for (const d of details) console.error(`     · ${d}`)
  console.error('   ⇒ 处置（缺一不算修好）：')
  console.error('     ① 打开 frontend/admin-web/src/app/login/page.tsx 核对页签 / 副标题 / 占位 / 按钮文案，更新本脚本顶部 LOGIN_SHAPE 与登录步锚点；')
  console.error('     ② 同步升 .agent-presets/migao/skills/migao-dev-flow 的 version（单调递增）并更新 §15.7 的用法说明。')
  console.error(`   自检（不需要账号 / 后端）：node ${SCRIPT_REL} --login-shape-check --site ${site}`)
  process.exit(1)
}

/** 读登录页的「形态指纹」：页签（逐字文本 + 选中态）、输入框占位、按钮文案。 */
async function probeLoginShape(page) {
  return page.evaluate(() => ({
    title: document.title,
    // 页签文本**压平空白**再比对（真实页面的页签是 flex-col ⇒ innerText 有换行；夹具 / 改版后可能是行内
    // ⇒ 按「换行」切 label/hint 会假红。这里只要求「同一个页签里同时出现 名 + 副标题」）。
    tabs: Array.from(document.querySelectorAll('[role="tab"]')).map((t) => ({
      text: (t.innerText || '').replace(/\s+/g, ''),
      selected: t.getAttribute('aria-selected') === 'true',
    })),
    placeholders: Array.from(document.querySelectorAll('input')).map((i) => i.getAttribute('placeholder') || ''),
    buttons: Array.from(document.querySelectorAll('button')).map((b) => (b.innerText || '').trim()).filter(Boolean),
  }))
}

/**
 * 指纹判定**阶段一（页签层）**：页签名 + 副标题 + 提交按钮。返回缺失项清单（空 = 匹配）。
 *
 * ⚠️ 指纹必须分两阶段：登录页**只渲染当前页签的表单** ⇒ 手机号/验证码输入框在切到
 * 「管理员登录」之前**根本不在 DOM 里**（把两阶段混成一次判定 ⇒ 工具自己永远判红）。
 */
function judgeLoginTabs(probe) {
  const missing = []
  for (const want of LOGIN_SHAPE.tabs) {
    const hits = probe.tabs.filter((t) => t.text.includes(want.label))
    if (!hits.length) missing.push(`缺少页签「${want.label}」（现有页签：${probe.tabs.map((t) => `「${t.text}」`).join(' ') || '无'}）`)
    else if (!hits.some((t) => t.text.includes(want.hint))) missing.push(`页签「${want.label}」里找不到副标题「${want.hint}」（实测「${hits.map((t) => t.text).join('」/「')}」）`)
  }
  if (!probe.buttons.some((b) => LOGIN_SHAPE.submitTextRe.test(b))) missing.push('找不到「登 录」提交按钮')
  return missing
}

/** 指纹判定**阶段二（管理员表单层）**：手机号 / 验证码占位 + 「获取验证码」按钮。 */
function judgeAdminForm(probe) {
  const missing = []
  if (!probe.placeholders.some((p) => p.includes(LOGIN_SHAPE.phonePlaceholderIncludes))) missing.push(`没有任何输入框的 placeholder 含「${LOGIN_SHAPE.phonePlaceholderIncludes}」（实测：${probe.placeholders.map((p) => `「${p}」`).join(' ') || '无输入框'}）`)
  if (!probe.placeholders.some((p) => p.includes(LOGIN_SHAPE.codePlaceholderIncludes))) missing.push(`没有任何输入框的 placeholder 含「${LOGIN_SHAPE.codePlaceholderIncludes}」（实测：${probe.placeholders.map((p) => `「${p}」`).join(' ') || '无输入框'}）`)
  if (!probe.buttons.some((b) => b.includes(LOGIN_SHAPE.sendCodeText))) missing.push(`找不到「${LOGIN_SHAPE.sendCodeText}」按钮（实测按钮：${probe.buttons.map((b) => `「${b.replace(/\s+/g, ' ')}」`).join(' ') || '无'}）`)
  return missing
}

const describeProbe = (probe) => [
  `页签 = ${probe.tabs.length ? probe.tabs.map((t) => `「${t.text}」${t.selected ? '(选中)' : ''}`).join(' , ') : '(无)'}`,
  `输入框占位 = ${probe.placeholders.length ? probe.placeholders.map((p) => `「${p}」`).join(' , ') : '(无)'}`,
  `按钮 = ${probe.buttons.map((b) => `「${b.replace(/\s+/g, ' ')}」`).join(' , ') || '(无)'}`,
]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, locale: 'zh-CN' })
const page = await ctx.newPage()
const http5xx = []
page.on('response', (r) => { if (r.status() >= 500) http5xx.push(`${r.status()} ${r.url()}`) })

// ── ① 打开登录页：先等**真的渲染出来**（客户端渲染页面的 SSR 是空壳，抢跑必静默失败）─────
try {
  await page.goto(`${site}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
} catch (e) {
  die(`登录页打不开（${site}/login）：${oneLine(e)}\n   ⇒ 先确认站点入口可用（本机唯一入口见 §15.7「唯一入口」：admin-web :3001 + admin-api :8080）。`)
}
try {
  await page.locator('input').first().waitFor({ state: 'visible', timeout: 25000 })
} catch {
  const probe = await probeLoginShape(page)
  dieShape(`25s 内登录表单没有渲染出任何可见 input（页面 title=「${probe.title}」）`, describeProbe(probe))
}

// ── ② 形态指纹 · 阶段一（页签层；不匹配即红：页面改版 ⇒ 工具失配**下次自己爆**）──────
const probe0 = await probeLoginShape(page)
const missingTabs = judgeLoginTabs(probe0)
if (missingTabs.length) dieShape(`指纹（页签层）不匹配（${probe0.tabs.length} 个页签 / ${probe0.buttons.length} 个按钮）`, [...missingTabs, ...describeProbe(probe0)])

// ── ③ 切「管理员登录」：语义锚（role=tab）优先，文本兜底；失败具名报出 ──────────────
const adminLabel = LOGIN_SHAPE.tabs[1].label
const adminTab = page.getByRole('tab', { name: new RegExp(adminLabel) })
if (await adminTab.count()) {
  try {
    await adminTab.first().click({ timeout: 10000 })
  } catch (e) {
    dieShape(`「${adminLabel}」页签点不动：${oneLine(e)}`, describeProbe(await probeLoginShape(page)))
  }
} else {
  const tabText = page.getByText(adminLabel, { exact: false }).first()
  if (!(await tabText.count())) dieShape(`找不到「${adminLabel}」入口（页签与文本都没有）`, describeProbe(await probeLoginShape(page)))
  try {
    await tabText.click({ timeout: 10000 })
  } catch (e) {
    dieShape(`「${adminLabel}」文本入口点不动：${oneLine(e)}`, describeProbe(await probeLoginShape(page)))
  }
}

const phoneInput = page.getByLabel('手机号', { exact: false })
try {
  await phoneInput.first().waitFor({ state: 'visible', timeout: 15000 })
} catch {
  dieShape(`切了「${adminLabel}」但 15s 内没出现管理员表单（手机号输入框）；可能是页面形态变了，也可能是页面尚未水合 / 网络慢`, describeProbe(await probeLoginShape(page)))
}

// ── ③b 形态指纹 · 阶段二（管理员表单层：占位 / 按钮）────────────────────────────
const probe1 = await probeLoginShape(page)
const missingAdmin = judgeAdminForm(probe1)
if (missingAdmin.length) dieShape(`指纹（管理员表单层）不匹配（${probe1.placeholders.length} 个输入框 / ${probe1.buttons.length} 个按钮）`, [...missingAdmin, ...describeProbe(probe1)])

if (shapeCheckOnly) {
  console.log(`✅ 登录页形态自检通过：${site}/login 命中指纹 ${LOGIN_SHAPE.id}（页签层 + 管理员表单层两阶段都过）`)
  console.log(`   阶段一 页签层：${describeProbe(probe0)[0]}`)
  console.log(`   阶段二 表单层：${describeProbe(probe1).slice(1).join(' ; ')}`)
  await browser.close()
  process.exit(0)
}
fs.mkdirSync(outDir, { recursive: true })

// ── ④ 真实用户路径登录（手机验证码）─────────────────────────────────────────
const step = (msg) => console.log(`   · ${msg}`)
step(`形态指纹 ${LOGIN_SHAPE.id} ✓ → 已切「${adminLabel}」`)

await phoneInput.first().fill(phone)
const sendCodeBtn = page.getByText(LOGIN_SHAPE.sendCodeText, { exact: false }).first()
if (!(await sendCodeBtn.count())) dieShape(`找不到「${LOGIN_SHAPE.sendCodeText}」按钮（管理员表单在，但按钮缺失）`, describeProbe(await probeLoginShape(page)))
try {
  await sendCodeBtn.click({ timeout: 10000 })
} catch (e) {
  dieShape(`「${LOGIN_SHAPE.sendCodeText}」点不动：${oneLine(e)}`, describeProbe(await probeLoginShape(page)))
}
step(`已请求验证码（手机号 ${phone}）`)
await page.waitForTimeout(1500)

const codeInput = page.getByLabel('验证码', { exact: false })
if (!(await codeInput.count())) dieShape('管理员表单里找不到「验证码」输入框', describeProbe(await probeLoginShape(page)))
await codeInput.first().fill(code)

const submitBtn = page.getByRole('button', { name: LOGIN_SHAPE.submitTextRe })
if (!(await submitBtn.count())) dieShape('找不到「登 录」提交按钮', describeProbe(await probeLoginShape(page)))
await submitBtn.first().click()

let landed = true
try {
  await page.waitForURL((u) => !/^\/login\b/.test(u.pathname), { timeout: 25000 })
} catch {
  landed = false
}
if (!landed) {
  const banner = await page.locator('p.text-red-600, p.text-red-500').first().innerText().catch(() => '')
  try { await page.screenshot({ path: path.join(outDir, 'login-failed.png') }) } catch { /* 截图失败不掩盖主因 */ }
  die(`登录未生效（仍停在 ${page.url()}）—— 页面提示：「${banner.replace(/\s+/g, ' ').trim() || '(无可见错误文案)'}」\n   ⇒ 属**凭据 / 服务端面**的失败（不是页面形态）：核对 --phone/--code 与 backend/admin-api/.env 的 SMS_BYPASS_CODE；诊断截图 ${path.join(outDir, 'login-failed.png')}`)
}
step(`登录成功 → ${page.url()}`)

const afterLogin = page.url()
const loginOk = !/\/login\b/.test(new URL(afterLogin).pathname)

// ── ⑤ 目标页证据 ────────────────────────────────────────────────────────────
await page.goto(`${site}${target}`, { waitUntil: 'networkidle', timeout: 90000 })
await page.waitForTimeout(2500)

for (const spec of fills) {
  const [ph, value] = spec.split('=')
  const input = page.locator(`input[placeholder*="${ph}"]`).first()
  if ((await input.count()) === 0) { console.error(`⚠️ 未找到 placeholder 含「${ph}」的输入框（跳过）`); continue }
  await input.click(); await input.fill(''); await input.type(value, { delay: 60 })
  await page.waitForTimeout(400)
}
for (const text of clicks) {
  await page.getByText(text, { exact: false }).first().click({ timeout: 5000 }).catch(() => console.error(`⚠️ 点不到「${text}」（跳过）`))
  await page.waitForTimeout(800)
}
if (has('open-details')) {
  await page.evaluate(() => { document.querySelectorAll('details:not([open])').forEach((d) => d.setAttribute('open', '')) })
  await page.waitForTimeout(800)
}

const url = page.url()
const testids = await page.evaluate(() => Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid')))
const text = await page.evaluate(() => document.body.innerText)
await page.screenshot({ path: path.join(outDir, '01-full.png'), fullPage: true })
fs.writeFileSync(path.join(outDir, 'page-text.txt'), text)
fs.writeFileSync(path.join(outDir, 'testids.txt'), testids.join('\n'))

const shotFiles = []
for (const sel of shots) {
  const locator = sel.startsWith('[') || sel.startsWith('.') || sel.startsWith('#') ? page.locator(sel).first() : page.locator(`[data-testid="${sel}"]`).first()
  const name = sel.replace(/[^A-Za-z0-9_-]/g, '_')
  if ((await locator.count()) === 0) { console.error(`⚠️ MISSING ${sel}（元素不在 DOM ⇒ 记入 summary.missing）`); continue }
  try {
    await locator.scrollIntoViewIfNeeded(); await page.waitForTimeout(300)
    await locator.screenshot({ path: path.join(outDir, `${name}.png`) })
    shotFiles.push(`${name}.png`)
  } catch (e) { console.error(`⚠️ 截图失败 ${sel}: ${String(e).slice(0, 120)}`) }
}

const summary = {
  site,
  target,
  url,
  loginOk,
  afterLogin,
  loginShape: { id: LOGIN_SHAPE.id, ok: true, tabs: probe0.tabs.map((t) => t.text) },
  testids: testids.length,
  http5xx,
  files: ['01-full.png', ...shotFiles, 'page-text.txt', 'testids.txt'],
  missingShots: shots.filter((s) => !shotFiles.includes(s.replace(/[^A-Za-z0-9_-]/g, '_'))),
}
fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2))
await browser.close()

console.log(`\n证据目录: ${outDir}`)
console.log(`URL: ${url} ｜ testid: ${testids.length} ｜ 5xx: ${http5xx.length}`)
console.log(`截图: ${summary.files.filter((f) => f.endsWith('.png')).join(', ')}`)
if (!loginOk && !has('allow-login-page')) die(`登录未生效（停在 ${afterLogin}）—— **拒绝把登录页当验收证据**（§15.7 假绿形态①）`)
if (testids.length === 0 && !has('allow-login-page')) die('页面零 data-testid —— 疑似未渲染/被重定向，**不作为验收证据**')
console.log('✅ 证据采集完成 —— 下一步：AI **读图**逐条判定（读图能力缺失时按 §15.5 用视觉模型开子代理）')
