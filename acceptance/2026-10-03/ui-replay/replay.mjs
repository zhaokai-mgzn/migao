// UI 级重放（2026-10-03）：把两条前端修复放到**真机 UI + 真 API**上验，而不是 jsdom 夹具。
//
// 为什么值得单开这一轮（证据面降级）：
//   ① #6128 的读面标记要**按逻辑工序名 join 两张读面**（qty_rule_missing 只在工序库读面
//      `operations-catalog`，而工艺项表的行来自价目读面）⇒ jsdom 里字段是夹具直接给的，
//      **join 失配永远照不到**；
//   ② #6103 修前是字典域取错（UI 发 inactive、后端只认 active|disabled）⇒ 单测只能证明
//      "请求体里是 disabled"，真机才能证明"点下去 422 消失、状态真的变了"。
//
// 判据（每条都得能红；负对照防"永远绿"）：
//   U1 前置：登录后进入工艺配置页
//   U2 新建**目录外**工序 ⇒ 写面提示条 qty-rule-hint 出现（且不阻断创建）
//   U3 刷新后该行出现「数量按 1 计」徽标 matrix-qty-fallback-<名>   ← join 判据（单测照不到）
//   U4 【负对照·界面】目录内工序**不得**出现该徽标
//   U5 抽屉里出现「按 1 计」解释行 operations-manage-qty-fallback
//   U6 【#6103】经「管理▸」点停用 ⇒ **无 4xx**（网络面取证）且 **读面 status 真的变 disabled**
//   U7 【负对照·读面】目录内工序的 qty_rule_missing 必须为 falsy（判据不是"一律标记"）
//   U8 零残留：探针工序已软删（**按 operations-catalog 真读面判定**，不再用坏查询假绿）
//
// 用法：node replay.mjs   （API :8080 / WEB :3001，二者都必须是 origin/main 的构建点）

import { chromium } from '../../../tests/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = join(HERE, 'out')
mkdirSync(OUT, { recursive: true })

const API = process.env.API_URL || 'http://localhost:8080'
const WEB = process.env.WEB_URL || 'http://localhost:3001'
const REST = `${API}/api/admin`
const PHONE = '13800138000', CODE = '123456'
const STAMP = String(Date.now()).slice(-6)
const PROBE = `UI重放工序${STAMP}`   // 目录外：引擎算料目录里不可能有它
const INTERNAL = '韩褶'               // 目录内：负对照

const R = []
const rec = (id, name, ok, detail) => { R.push({ id, name, ok, detail }); console.log(`${ok ? '✅' : '❌'} [${id}] ${name} — ${detail}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function j(method, path, { token, body } = {}) {
  const res = await fetch(`${REST}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const text = await res.text()
  let parsed = null
  try { parsed = text ? JSON.parse(text) : null } catch { parsed = { raw: text.slice(0, 300) } }
  return { status: res.status, body: parsed }
}

/** 读面真值：GET /production/operations-catalog ⇒ 拍平 groups[].operations[] */
async function catalog(token) {
  const r = await j('GET', '/production/operations-catalog', { token })
  const data = r.body?.data ?? r.body
  const groups = data?.groups ?? []
  const flat = groups.flatMap((g) => (g.operations ?? []).map((o) => ({ ...o, group: o.group ?? g.group })))
  return { http: r.status, total: data?.total, flat }
}

// ── 直连 DB（只读）：读面**不暴露** status（CatalogOperation 无该键）⇒ 「停用是否真生效」
//    只能用 DB 作权威证据；这也正是 UI 判据容易假绿的地方（界面没报错 ≠ 状态变了）。
const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..')
let _pg = null
function pgConf() {
  if (_pg) return _pg
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pg = { host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'), db: get('RDS_DB'), password: get('RDS_PASSWORD') }
  return _pg
}
function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
      '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}

async function login() {
  const tried = []
  for (const path of ['/api/auth/sms/login', '/api/admin/auth/sms/login']) {
    const res = await fetch(`${API}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone: PHONE, code: CODE }),
    })
    const text = await res.text()
    tried.push(`${path}=${res.status}`)
    if (res.ok) { const json = JSON.parse(text); return { path, data: json.data ?? json } }
  }
  throw new Error(`登录失败：${tried.join(' / ')}`)
}

const main = async () => {
  const health = await fetch(`${API}/actuator/health`).then((r) => r.json()).catch(() => null)
  console.log(`构建点自证：API health=${health?.status} / WEB=${WEB}`)

  const { path, data } = await login()
  const token = data.accessToken
  console.log(`登录成功（${path}）token=${String(token).slice(0, 12)}…`)

  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: { width: 1512, height: 950 } })
  await ctx.addCookies([{ name: 'access_token', value: token, url: WEB }])
  await ctx.addInitScript(([t, u]) => {
    localStorage.setItem('auth-storage', JSON.stringify({
      state: { accessToken: t, refreshToken: t, user: u, isAuthenticated: true, rememberMe: false }, version: 0,
    }))
  }, [token, data.user ?? null])
  const page = await ctx.newPage()

  // 网络面取证：所有 4xx/5xx 的写请求都记下来（#6103 的关键是"别再 422"）
  const bad = []
  page.on('response', (res) => {
    const u = res.url()
    if (u.includes('/api/') && res.status() >= 400) bad.push(`${res.request().method()} ${u.replace(API, '')} ⇒ ${res.status()}`)
  })

  const shot = async (n) => { await page.screenshot({ path: join(OUT, `${n}.png`), fullPage: true }); return `${n}.png` }
  const created = []
  try {
    await page.goto(`${WEB}/production/routings`, { waitUntil: 'domcontentloaded' })
    await sleep(3000)
    const s1 = await shot('u1-routings-page')
    rec('U1', '登录后进入工艺配置页', (await page.getByTestId('operation-price-matrix').count()) > 0, `截图=${s1}`)

    // ── U2 新建目录外工序 ⇒ 写面提示条 ────────────────────────────
    await page.getByTestId('routings-new-operation').click()
    await sleep(1200)
    await shot('u2a-create-dialog')
    await page.getByTestId('routings-create-op-name').fill(PROBE)
    await page.getByTestId('routings-create-op-unit_price').fill('0.9')
    await page.getByTestId('routings-create-operation-submit').click()
    await sleep(3000)
    const s2 = await shot('u2b-after-create')
    const hintN = await page.getByTestId('qty-rule-hint').count()
    const hintTxt = hintN ? (await page.getByTestId('qty-rule-hint').innerText()).replace(/\s+/g, ' ').slice(0, 120) : '(无)'
    rec('U2', '新建目录外工序 ⇒ 写面提示条出现（不阻断创建）', hintN > 0, `条数=${hintN}；文案=「${hintTxt}」；截图=${s2}`)

    const c1 = await catalog(token)
    const mine = c1.flat.find((o) => o.name === PROBE)
    if (mine) created.push(mine.id)
    const probeId = mine?.id ?? null
    console.log(`  读面确认：catalog http=${c1.http} total=${c1.total} 条数=${c1.flat.length}；探针=${mine ? `id=${mine.id} status=${mine.status} qty_rule_missing=${mine.qty_rule_missing}` : '未找到'}`)

    // ── U3 刷新后行内徽标（join 判据）────────────────────────────
    await page.reload({ waitUntil: 'domcontentloaded' })
    await sleep(3000)
    const s3 = await shot('u3-after-reload')
    const badge = page.getByTestId(`matrix-qty-fallback-${PROBE}`)
    const bN = await badge.count()
    rec('U3', `读面徽标 matrix-qty-fallback-${PROBE} 可见（按逻辑工序名 join 两张读面）`,
      bN > 0 && (await badge.first().isVisible()), `命中=${bN}；截图=${s3}`)

    // ── U4 负对照·界面 ──────────────────────────────────────────
    const iN = await page.getByTestId(`matrix-qty-fallback-${INTERNAL}`).count()
    rec('U4', `负对照（界面）：目录内「${INTERNAL}」不得有徽标`, iN === 0, `命中=${iN}（期望 0）`)

    // ── U5 抽屉解释行 ───────────────────────────────────────────
    let drawer = false, drawerTxt = ''
    try {
      const row = page.getByTestId(`matrix-row-${PROBE}`)
      await row.getByTitle(/管理/).first().click({ timeout: 8000 })
      await sleep(1500)
      const line = page.getByTestId('operations-manage-qty-fallback')
      drawer = (await line.count()) > 0
      drawerTxt = drawer ? (await line.first().innerText()).replace(/\s+/g, ' ').slice(0, 120) : '未找到该行'
    } catch (e) { drawerTxt = `打开抽屉失败：${String(e).slice(0, 100)}` }
    const s4 = await shot('u5-drawer')
    rec('U5', '抽屉里的「按 1 计」解释行在场', drawer, `${drawerTxt}；截图=${s4}`)

    // ── U6 #6103 停用：无 4xx + 读面真变 disabled ────────────────
    const badBefore = bad.length
    try {
      const btn = page.getByTestId('operations-manage-disable')
      if (await btn.count()) { await btn.first().click({ timeout: 8000 }); await sleep(1500) }
      const ok = page.getByTestId('routing-confirm-confirm')
      if (await ok.count()) { await ok.first().click({ timeout: 8000 }) }
      await sleep(3000)
    } catch (e) { console.log(`  （停用交互异常：${String(e).slice(0, 120)}）`) }
    const s5 = await shot('u6-after-disable')
    const newBad = bad.slice(badBefore)
    let dbRow = null
    try { dbRow = psql(`select status, deleted from production_operations where id = '${probeId}'`)[0] ?? null } catch (e) { console.log(`  （DB 直连失败：${String(e).slice(0, 100)}）`) }
    rec('U6', '#6103 停用按钮：无 4xx 且 **DB** status 真的变 disabled',
      newBad.length === 0 && dbRow?.status === 'disabled',
      `新增 4xx=${JSON.stringify(newBad)}；DB status=${dbRow?.status}（deleted=${dbRow?.deleted}）；截图=${s5}`)

    // ── U7 负对照·读面 ─────────────────────────────────────────
    const c2 = await catalog(token)
    const internal = c2.flat.find((o) => o.name === INTERNAL)
    rec('U7', `负对照（读面）：目录内「${INTERNAL}」的 qty_rule_missing 必须为 falsy`,
      !!internal && !internal.qty_rule_missing, `qty_rule_missing=${internal?.qty_rule_missing}（期望 falsy）`)
  } finally {
    // 清理：有挂格的工序必须走 detach-and-delete（普通 DELETE 正是那条 422 护栏）；
    // 另外把**历史遗留**的探针（前缀 `UI重放工序`）一并收掉，保证"零残留"是真读数。
    // 🔴 用 **DB** 找残留，不用读面：**停用后的工序在读面里已经看不见**（本轮实测）——
    //    按读面清场会漏掉"被停用过的探针"，那正是"零残留"最容易假绿的地方。
    let leftovers = []
    try { leftovers = psql(`select id::text as id, name from production_operations where name like 'UI重放工序%' and deleted = 0`) } catch { leftovers = [] }
    for (const o of leftovers) {
      const del = await j('DELETE', `/production/operations/${o.id}/detach-and-delete`, { token })
      console.log(`  清理探针 ${o.id}（${o.name}）⇒ HTTP ${del.status}`)
    }
    for (const id of created) {
      if (leftovers.some((o) => String(o.id) === String(id))) continue
      const del = await j('DELETE', `/production/operations/${id}/detach-and-delete`, { token })
      console.log(`  清理探针 ${id} ⇒ HTTP ${del.status}`)
    }
    const c3 = await catalog(token)
    const alive = c3.flat.filter((o) => String(o.name || '').startsWith('UI重放工序'))
    let dbAlive = null
    try { dbAlive = psql(`select count(*)::int as n from production_operations where name like 'UI重放工序%' and deleted = 0`)[0]?.n ?? null } catch { /* 已在读数里体现 */ }
    rec('U8', '零残留：探针工序不存活（读面 operations-catalog + **DB** 双证）',
      c3.http === 200 && alive.length === 0 && dbAlive === 0,
      `catalog http=${c3.http} 存活探针=${alive.length}；DB 存活=${dbAlive}；本轮清理=${leftovers.length + created.length} 个`)
    await browser.close()
  }

  const pass = R.filter((r) => r.ok).length
  writeFileSync(join(OUT, 'ui-replay.json'), JSON.stringify(
    { at: new Date().toISOString(), api: API, web: WEB, probe: PROBE, pass, fail: R.length - pass, total: R.length, results: R }, null, 2))
  console.log(`\nsummary=${JSON.stringify({ pass, fail: R.length - pass, total: R.length })}`)
}

main().catch((e) => { console.error('💥 重放异常：', e); process.exitCode = 1 })
