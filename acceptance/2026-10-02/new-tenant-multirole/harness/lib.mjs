// 新企业入驻 + 多岗位 RBAC 验收 —— 共享库
//
// 用途：把「页面 / DB / 服务器日志」三路证据统一成同一套记录格式，供 s1~s5 各阶段脚本复用。
// 证据纪律（migao-acceptance）：每条记录必须带可复核的证据引用（截图路径 / SQL 原文 /
// 日志行号），禁止只写「正常/符合预期」。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const { chromium } = createRequire(join(REPO_ROOT, 'tests', 'package.json'))('playwright')
export const WEB = process.env.BASE_URL || 'http://localhost:3001'
export const API = process.env.API_BASE || 'http://localhost:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const API_LOG = process.env.API_LOG || '/tmp/acc-admin-api.log'
export const AGENT_LOG = process.env.AGENT_LOG || '/tmp/acc-ai-agent.log'
export const WEB_LOG = process.env.WEB_LOG || '/tmp/acc-admin-web.log'

mkdirSync(join(OUT, 'screenshots'), { recursive: true })
mkdirSync(join(OUT, 'evidence'), { recursive: true })

export function log(msg) {
  const line = `${new Date().toISOString()} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 证据记录 ──────────────────────────
export class Recorder {
  constructor(file) {
    this.file = file
    this.records = []
  }
  add(id, name, status, detail, evidence = []) {
    const rec = { id, name, status, detail, evidence, at: new Date().toISOString() }
    this.records.push(rec)
    const icon = status === 'pass' ? '✅' : status === 'fail' ? '❌' : '⏭️'
    log(`${icon} [${id}] ${name} — ${detail}`)
    this.dump()
    return rec
  }
  pass(id, name, detail, ev) { return this.add(id, name, 'pass', detail, ev) }
  fail(id, name, detail, ev) { return this.add(id, name, 'fail', detail, ev) }
  skip(id, name, detail) { return this.add(id, name, 'skip', detail, []) }
  dump() { writeFileSync(join(OUT, this.file), JSON.stringify(this.records, null, 2)) }
  summary() {
    const c = (s) => this.records.filter((r) => r.status === s).length
    return { pass: c('pass'), fail: c('fail'), skip: c('skip'), total: this.records.length }
  }
}

// ────────────────────────── HTTP（node 侧直连 admin-api）──────────────────────────
// 为什么不在页面内 fetch：access_token 是 HttpOnly cookie，浏览器在 http 跨端口下不发它
// （与 scripts/ui-smoke-merchant/spec.mjs 同因）。node 侧显式带 Cookie 头 = 与 UI 同一用户/租户。
export async function api(method, path, { token, body, headers = {} } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers }
  if (token) {
    h.Cookie = `access_token=${token}`
    h.Authorization = `Bearer ${token}`
  }
  const res = await fetch(API + path, {
    method,
    headers: h,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON（如 502 HTML） */ }
  return { status: res.status, json, text, ok: res.ok }
}

/** 短信登录（万能码；SmsService.verifyCode 的 bypass 分支）。 */
export async function loginApi(phone, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, refreshToken: d.refreshToken, raw: d }
}

export async function me(token) {
  const r = await api('GET', '/api/auth/me', { token })
  return r.json?.data
}

// ────────────────────────── DB（psql 直连云 dev 库）──────────────────────────
let _pgConf = null
function pgConf() {
  if (_pgConf) return _pgConf
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pgConf = {
    host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'),
    db: get('RDS_DB'), password: get('RDS_PASSWORD'),
  }
  return _pgConf
}

/** 执行只读 SQL，返回行对象数组。包成 json_agg 一行输出 ⇒ 不用解析表格宽度。 */
export function psql(sql) {
  const c = pgConf()
  const out = execFileSync(
    'psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
     '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 },
  )
  return JSON.parse(out.trim() || '[]')
}

/** 写 SQL（验收脚本自己造的数据清理用），返回 psql 文本输出。 */
export function psqlWrite(sql) {
  const c = pgConf()
  try {
    return execFileSync(
      'psql',
      ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-c', sql],
      { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' },
    )
  } catch (e) {
    return String(e.stderr || e.message)
  }
}

// ────────────────────────── 服务器日志 ──────────────────────────
/** 在 admin-api 日志里检索（返回匹配行 + 行号），用于「日志侧证据」。 */
export function grepApiLog(pattern, { limit = 20, file = API_LOG } = {}) {
  if (!existsSync(file)) return []
  const lines = readFileSync(file, 'utf8').split('\n')
  const re = new RegExp(pattern)
  const hits = []
  for (let i = 0; i < lines.length; i++) {
    if (re.test(lines[i])) hits.push({ line: i + 1, text: lines[i].slice(0, 400) })
  }
  return hits.slice(-limit)
}

// ────────────────────────── 浏览器 ──────────────────────────
export async function newContext(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  page.on('pageerror', () => {})
  return { ctx, page }
}

export async function shot(page, name) {
  const p = join(OUT, 'screenshots', `${name}.png`)
  try { await page.screenshot({ path: p, fullPage: false }) } catch { /* 忽略截图失败 */ }
  return p
}

/**
 * 员工登录（issue #5485 的正式入口）：`用户名@企业编码` + 密码。
 * 与 UI 的「员工登录」页签同一端点。
 */
export async function employeeLoginApi(identifier, password) {
  const r = await api('POST', '/api/auth/employee/login', { body: { identifier, password } })
  if (!r.json?.success) throw new Error(`员工登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  return { token: r.json.data.accessToken, raw: r.json.data }
}

/**
 * UI 登录。登录页有两个页签（issue #5485）：默认「员工登录」（账号密码），
 * 「管理员登录」才是手机验证码 —— 不切页签直接找 #phone 会超时。
 * @param {{mode?: 'admin'|'employee', phone?: string, identifier?: string, password?: string}} opts
 */
export async function loginUi(page, opts = {}) {
  const mode = opts.mode || (opts.phone ? 'admin' : 'employee')
  await page.goto(WEB + '/login', { waitUntil: 'domcontentloaded', timeout: 45000 })
  if (mode === 'admin') {
    await page.getByRole('tab', { name: /管理员登录/ }).click()
    await page.waitForSelector('#phone', { timeout: 45000 })
    await page.fill('#phone', opts.phone)
    await page.fill('#code', SMS_CODE)
  } else {
    await page.waitForSelector('#identifier', { timeout: 45000 })
    await page.fill('#identifier', opts.identifier)
    await page.fill('#password', opts.password)
  }
  await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
  await page.waitForURL('**/dashboard**', { timeout: 45000 })
}

export function saveCtx(obj) {
  const cur = loadCtx()
  writeFileSync(join(OUT, 'context.json'), JSON.stringify({ ...cur, ...obj }, null, 2))
}
export function loadCtx() {
  try { return JSON.parse(readFileSync(join(OUT, 'context.json'), 'utf8')) } catch { return {} }
}

export async function waitService(ms = 60000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try {
      const r = await fetch(API + '/actuator/health')
      if (r.ok) return true
    } catch { /* 未就绪 */ }
    await new Promise((r) => setTimeout(r, 2000))
  }
  return false
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
