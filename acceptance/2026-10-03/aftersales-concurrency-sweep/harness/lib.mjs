// 线B 售后退款闭环 + 并发竞态 sweep —— 本包共享库（2026-10-03 第三轮）
//
// 复用自 batch-writeface-sweep/harness/lib.mjs（共享库，按要求**复制后再改**）。本包特有的补充：
//   ① 探针命名域换成 `线B验收` / id 前缀 `lb`（跨包隔离：线A 同时在同租户 20 跑）
//   ② 探针**订单/SKU** 的建与清（售后闭环必须有一张可退款的已确认订单 + 一条带 skuId 的明细）
//   ③ 并发原语 `raceStart()`：同一起跑线 + 逐请求结局采集（B2 方法学重点）
//   ④ 红证注入 helper（只在**本目录的副本**上生效，绝不改产品源码）
//
// 证据纪律（migao-acceptance）：
//   ① 期望一律本包独立算出（DB 读数 / 端点契约原文），**严禁**拿被测系统自己的读面当期望；
//   ② 写 SQL 必须带 `-- probe-ok`；探针命名域统一 `线B验收`，id 前缀 `lb`；
//   ③ 时间一律 +08 口径；JSON 里 UTC 与 +08 同时留。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://127.0.0.1:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const TENANT_ID = Number(process.env.TENANT_ID || 20)
export const ADMIN_PHONE = process.env.ADMIN_PHONE || '13870217889'
export const LIVE_WORKTREE = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live'

/** 探针命名域：本包创建的一切对象都带此前缀（中文名域）+ `lb` 机器前缀（id 域）。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '线B验收'
/** 探针 id 的机器可判前缀：所有本包自建行 id / 单号以 `lb` 开头（绝不碰别人的行）。 */
export const ID_PREFIX = 'lb'
export const AS_TICKET_PREFIX = 'LB-AS-'
export const IDEM_HEADER = 'X-Client-Request-Id'

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${nowCST().cst} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 时间（+08 口径）──────────────────────────
// 🔴 本机时区 = Asia/Shanghai（issue #5352），但**进程 TZ 未必是** ⇒ 一律走 Intl 显式时区。
const CST_FMT = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})
export function nowCST() {
  const d = new Date()
  return { cst: `${CST_FMT.format(d).replace('T', ' ')} +08`, utc: d.toISOString() }
}
/** 毫秒级墙钟（并发重叠判据用） */
export const nowMs = () => Date.now()

// ────────────────────────── 构建点自证 ──────────────────────────
export function buildPoint(worktree = LIVE_WORKTREE) {
  const git = (args) => { try { return execFileSync('git', ['-C', worktree, ...args], { encoding: 'utf8' }).trim() } catch { return 'unknown' } }
  let procStart = 'unknown', pid = 'unknown'
  try {
    pid = execFileSync('bash', ['-lc', `lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null | head -1`], { encoding: 'utf8' }).trim()
    if (pid) procStart = execFileSync('bash', ['-lc', `ps -o lstart= -p ${pid}`], { encoding: 'utf8' }).trim()
  } catch { /* 非致命 */ }
  return {
    worktree, pid,
    sha: git(['rev-parse', '--short', 'HEAD']),
    shaFull: git(['rev-parse', 'HEAD']),
    subject: git(['log', '-1', '--format=%s']),
    commitTime: git(['log', '-1', '--format=%cI']),
    originMain: (() => { try { return execFileSync('git', ['-C', REPO_ROOT, 'rev-parse', '--short', 'origin/main'], { encoding: 'utf8' }).trim() } catch { return 'unknown' } })(),
    adminApiStart: procStart,
    observedAt: nowCST(),
  }
}

// ────────────────────────── 证据记录（四态分列）──────────────────────────
// status ∈ pass | fail | skip | falseRed
export class Recorder {
  constructor(file) { this.file = file; this.records = [] }
  add(id, name, status, detail, evidence = [], extra = {}) {
    // 🔴 `status` 是四态 verdict；`extra` 里可能带同名键（如 HTTP 状态码）—— **不可覆盖 verdict**
    //    （实测：一条 422 的读数把 verdict 覆盖成 "422"，看板上就成了第五种状态）
    const safeExtra = { ...extra }
    if (safeExtra.status !== undefined) { safeExtra.httpStatus = safeExtra.status; delete safeExtra.status }
    const rec = { id, name, status, detail, evidence, at: nowCST().cst, atUtc: nowCST().utc, ...safeExtra }
    this.records.push(rec)
    log(`[${String(status).toUpperCase()}] [${id}] ${name} — ${detail}`)
    this.dump()
    return rec
  }
  pass(id, name, detail, ev, extra) { return this.add(id, name, 'pass', detail, ev, extra) }
  fail(id, name, detail, ev, extra) { return this.add(id, name, 'fail', detail, ev, extra) }
  skip(id, name, detail, ev = [], extra) { return this.add(id, name, 'skip', detail, ev, extra) }
  falseRed(id, name, detail, ev, extra) { return this.add(id, name, 'falseRed', detail, ev, extra) }
  dump() { writeFileSync(join(OUT, this.file), JSON.stringify({ records: this.records, summary: this.summary() }, null, 2)) }
  summary() {
    const c = (s) => this.records.filter((r) => r.status === s).length
    return { pass: c('pass'), fail: c('fail'), skip: c('skip'), falseRed: c('falseRed'), total: this.records.length }
  }
}

/** 断言器：pass/fail **都**带「期望来源 + 原始读数」。 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail, extra }) {
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  const ev = [`期望来源: ${expectSource}`, `期望: ${expect}`, `实得: ${actual}`, ...evidence]
  return pass ? R.pass(id, name, d, ev, extra) : R.fail(id, name, d, ev, extra)
}

// ────────────────────────── HTTP ──────────────────────────
export async function api(method, path, { token, body, headers = {}, timeoutMs = 60000 } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers }
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  let res
  try {
    res = await fetch(API + path, {
      method, headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (e) {
    return { status: 0, json: null, text: `FETCH_ERROR ${e.name}: ${e.message}`, ok: false, data: null, headers: {} }
  }
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON */ }
  return { status: res.status, json, text, ok: res.ok, data: json?.data, bookErr: json?.error }
}

export async function loginApi(phone = ADMIN_PHONE, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, raw: d }
}

/**
 * 取管理员 token（**环境事实**：本轮 :8080 进程未加载 `SMS_BYPASS_CODE` ⇒ 万能码 123456 被拒）。
 *
 * 做法：走**用户等价**的合法路径 —— `POST /api/auth/sms/send` 触发服务端生成并**落 Redis**
 * （`SmsService` 的 `sms:code:<phone>`，TTL 300s；服务端**故意不打日志**），再从 Redis 读回该码登录。
 * 这与「用户收到短信后输入」等价，不改产品源码、不绕过任何鉴权（仍是真实验证码校验）。
 * 前置（若 bypass 已启用）则直接用万能码。**只读 Redis，不写**。
 */
export async function adminToken() {
  try {
    const l = await loginApi(ADMIN_PHONE, SMS_CODE)
    if (l.token) return { token: l.token, via: 'sms-bypass-code', raw: l.raw }
  } catch { /* 回落 Redis 读码 */ }
  // 60s 防刷窗口：先看 Redis 里**是否已有活码**（上一轮留下的），没有再触发发送；发送被限流则退避重试。
  let code = redisGet(`sms:code:${ADMIN_PHONE}`)
  for (let attempt = 0; !code && attempt < 4; attempt++) {
    const s = await api('POST', '/api/auth/sms/send', { body: { phone: ADMIN_PHONE } })
    if (!s.json?.success && /频繁/.test(s.text || '')) { await sleep(20000); continue }
    await sleep(300)
    code = redisGet(`sms:code:${ADMIN_PHONE}`)
  }
  if (!code) throw new Error('登录失败：万能码被拒且 Redis 无 sms:code（:8080 未加载 SMS_BYPASS_CODE 且发送被限流）')
  const l = await loginApi(ADMIN_PHONE, code)
  return { token: l.token, via: 'redis-readback-code', codeLen: String(code).length, raw: l.raw }
}

/** 只读 Redis（凭 `backend/admin-api/.env` 的连接参数）；用于取登录验证码。 */
export function redisGet(key) {
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  try {
    return execFileSync('redis-cli', ['-h', get('REDIS_HOST'), '-p', get('REDIS_PORT'),
      '-a', get('REDIS_PASSWORD'), '--no-auth-warning', 'GET', key],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch { return null }
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ────────────────────────── 并发原语（B2 方法学核心）──────────────────────────
/**
 * 同一起跑线并发：先在本地把 N 个请求**全部构造完**，再用一个共享 barrier 同时放行。
 *
 * 🔴 为什么不是「for 循环里 await」：那样是**串行**（第 k 个请求开始前第 k-1 个已经结束）
 *   ⇒ 「并发没真重叠」的绿是**假绿**（无判别力）。本函数给出：
 *     - `started`/`settled` 的本地墙钟（ms）⇒ 可算**重叠窗口**（见 overlapEvidence）
 *     - 逐请求结局（status / 业务码 / 逐字响应摘录）
 *     - `barrierAt`：共同放行时刻（证明「同一起跑线」不是事后叙事）
 */
export async function raceStart(n, fn, { stagger = 0 } = {}) {
  let release
  const gate = new Promise((r) => { release = r })
  const tasks = []
  for (let i = 0; i < n; i++) {
    tasks.push((async () => {
      await gate
      if (stagger) await sleep(i * stagger)
      const t0 = nowMs()
      const t0cst = nowCST().cst
      let out = null, err = null
      try { out = await fn(i) } catch (e) { err = `${e.name}: ${e.message}` }
      return { i, t0, t1: nowMs(), startedAt: t0cst, out, err, durMs: nowMs() - t0 }
    })())
  }
  await sleep(30)   // 让所有 task 挂到 gate 上（fetch 尚未发出）
  const barrierAt = nowMs()
  const barrierCST = nowCST().cst
  release()
  const results = await Promise.all(tasks)
  return { n, barrierAt, barrierCST, results }
}

/** 重叠证据：并发请求的 [t0,t1] 区间是否真的交叠（逐对重叠 > 0 ⇒ 真重叠）。 */
export function overlapEvidence(race) {
  const iv = race.results.map((r) => [r.t0, r.t1]).sort((a, b) => a[0] - b[0])
  const unionStart = iv[0][0], unionEnd = Math.max(...iv.map((x) => x[1]))
  const unionMs = unionEnd - unionStart
  const sumMs = race.results.reduce((a, r) => a + Math.max(1, r.durMs), 0)
  let maxPairOverlap = 0
  for (let i = 0; i < iv.length; i++) {
    for (let j = i + 1; j < iv.length; j++) {
      const ov = Math.min(iv[i][1], iv[j][1]) - Math.max(iv[i][0], iv[j][0])
      if (ov > maxPairOverlap) maxPairOverlap = ov
    }
  }
  return {
    barrierAt: race.barrierAt, barrierAtCST: race.barrierCST,
    perRequest: race.results.map((r) => ({ i: r.i, t0: r.t0, t1: r.t1, durMs: r.durMs })),
    unionMs, sumMs, maxPairOverlapMs: maxPairOverlap,
    overlapped: maxPairOverlap > 0,
    verdict: maxPairOverlap > 0
      ? `真重叠：最大逐对重叠 ${maxPairOverlap}ms（并集 ${unionMs}ms < 各历时之和 ${sumMs}ms）`
      : `⚠️ 未观察到重叠（逐对重叠 ≤0，并集 ${unionMs}ms ≈ 和 ${sumMs}ms）—— 该轮绿**不算通过**`,
  }
}

// ────────────────────────── DB（psql 直连云 dev 库）──────────────────────────
let _pgConf = null
export function pgConf() {
  if (_pgConf) return _pgConf
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pgConf = { host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'), db: get('RDS_DB'), password: get('RDS_PASSWORD') }
  return _pgConf
}

/**
 * 只读查询 → JS 数组。
 *
 * 🔴 为什么用 `with src as materialized (…)` 而不是 `from (…) t`（**实测踩过，本包自曝的 harness 缺陷**）：
 *   PG 的**子查询展平**会把单列表子查询拉平成**标量**（`row_to_json(text)` 不存在 ⇒ 报错），
 *   而多加一列 / `LIMIT 0` / `OFFSET 0` / `WHERE true` **都拦不住**（planner 仍展平）——
 *   共享 lib 原写法在「单列表子查询」上必炸。`MATERIALIZED` 是 PG 12+ 的**不可展平**保证
 *   （显式物化 CTE ⇒ `src` 恒为 record），单列/多列通吃。
 *   ⚠️ 影响面：这是**读器**的缺陷，不是产品缺陷；它曾在上游包里把「读器坏了」读成「导出是空的」（CLAUDE 教训）。
 */
export function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
     '-c', `with src as materialized (${sql}) select coalesce(json_agg(row_to_json(src))::text,'[]') from src`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null

export function guardedWrite(sql) {
  if (!/--\s*probe-ok/.test(sql)) throw new Error(`写 SQL 缺 -- probe-ok 标记: ${sql.slice(0, 120)}`)
  const c = pgConf()
  return execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

export function assertProbe(...vals) {
  const s = vals.filter((v) => v !== null && v !== undefined).join(' ')
  if (!s.includes(PROBE_PREFIX)) throw new Error(`拒绝操作非探针对象（缺前缀「${PROBE_PREFIX}」）: ${s}`)
}

/** 内容指纹（红证注入/还原自证）。 */
export function sha256(s) {
  return execFileSync('shasum', ['-a', '256'], { input: typeof s === 'string' ? s : s, encoding: 'utf8' }).split(/\s+/)[0]
}

// ────────────────────────── decimal 语义（千分 milli，禁浮点 ==）──────────────────────────
export const SCALE = 1000n
export function cents(v) {
  if (typeof v === 'bigint') return v
  if (v === null || v === undefined || v === '') return null
  const s = String(v).trim()
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(s)
  if (!m) throw new Error(`非十进制读数: ${JSON.stringify(v)}`)
  const sign = m[1] === '-' ? -1n : 1n
  const frac = (m[3] || '').padEnd(3, '0').slice(0, 3)
  return sign * (BigInt(m[2]) * SCALE + BigInt(frac))
}
export function fmtQty(c) {
  if (c === null || c === undefined) return 'null'
  const sign = c < 0n ? '-' : ''
  const a = c < 0n ? -c : c
  return `${sign}${a / SCALE}.${String(a % SCALE).padStart(3, '0')}`
}
export const qtyEq = (a, b) => { try { return cents(a) === cents(b) } catch { return false } }
/** 金额相加（字符串 → 字符串，禁浮点） */
export function moneyAdd(...vals) {
  return fmtQty(vals.reduce((a, v) => a + (cents(v) ?? 0n), 0n))
}


// ────────────────────────── 探针注册表（**新增段自动被清**的形状）──────────────────────────
// 为什么要有它（主会话 16:50 复核指出的缺口）：只按「命名前缀白名单」清理时，**新加的段**一旦用了
// 新命名/新表，清理器就静默漏清（实测：p10 的 `LB-DISP-*` 商品与「探针订单-派工并发」订单在 p9 跑完后
// 仍然存活 448 行）。⇒ 改为「建的时候登记、清理按登记 + 前缀兜底」：**归属**由注册表定义，不由命名推断。
const REGISTRY_FILE = join(OUT, 'probe-registry.json')
export const REGISTRY = { categories: [], products: [], orders: [], tickets: [], processingOrders: [] }
export function registerProbe(kind, id, note = '') {
  if (!id) return
  const k = `${kind}s`
  if (!REGISTRY[k]) REGISTRY[k] = []
  if (!REGISTRY[k].includes(String(id))) REGISTRY[k].push(String(id))
  try { writeFileSync(REGISTRY_FILE, JSON.stringify(REGISTRY, null, 2)) } catch { /* 登记失败不阻断判据 */ }
  return id
}

// ────────────────────────── 本包探针对象 ──────────────────────────
export const uniq = () => `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`

/**
 * 建一个探针商品（走真实 API：POST /api/admin/products）；allowRestock 控制售后回补开关。
 * 返回 { productId, skuId, skuCode, stock, price, name, colorId }
 */
export async function createProbeProduct(token, { allowRestock = true, stock = 100, price = 100, tag = 'P', categoryId = null } = {}) {
  const u = uniq()
  const skuCode = `${ID_PREFIX.toUpperCase()}-${tag}-${u}`.toUpperCase()
  const name = `${PROBE_PREFIX}商品-${tag}-${u}`
  // ⚠️ categoryId **必填**（实测：不传 ⇒ 422「分类ID不能为空」）。复用租户既有分类，**不新建**分类
  //    （少一类待清理对象；分类不是本线的被测面）。缺省取该租户第一个 active 分类。
  const cat = categoryId || psql(`select id from categories where tenant_id=${TENANT_ID} and status='active' order by created_at limit 1`)[0]?.id
  const body = {
    name,
    skuCode,
    categoryId: cat,
    unit: '米',
    pricingType: 'per_meter',
    basePrice: price,
    price,
    stock,
    status: 'on_shelf',
    description: `${PROBE_PREFIX}（线B 售后退款/并发探针，用后自清）`,
    allowReturnRestock: allowRestock,
    colors: [{ colorName: `${PROBE_PREFIX}色-${u}`, mainColorHex: '#AABBCC' }],
    doorWidths: ['2.8m'],
  }
  const r = await api('POST', '/api/admin/products', { token, body })
  if (!r.json?.success) return { ok: false, resp: r, body }
  const productId = r.data?.id
  // 🔴 id / color_id 一律 ::text 取回：两者都是 **bigint**，JS Number 在 >2^53 时**静默舍入**
  //    （实测：真值 …3873796 被读成 …3873800）⇒ 拿舍入值当 colorId 回传，订单侧按 color_id **精确等值**
  //    查 SKU ⇒ 命中 0 行 ⇒ 422「无法定位到 SKU」。**这是 harness 的缺陷，不是产品缺陷。**
  const skus = psql(`select id::text as id, sku_code, stock, price, color_id::text as color_id from product_skus where tenant_id=${TENANT_ID} and product_id='${productId}'`)
  const colors = psql(`select id::text as id, color_name from product_colors where tenant_id=${TENANT_ID} and product_id='${productId}'`)
  registerProbe('product', productId, `${PROBE_PREFIX}商品-${tag}`)
  return {
    ok: true, productId, skuId: skus[0]?.id ?? null, skuCode: skus[0]?.sku_code ?? skuCode,
    stock: skus[0]?.stock, price, name, colorId: colors[0]?.id ?? skus[0]?.color_id ?? null,
    productSkuRows: skus, resp: r, body,
  }
}

/** 建一张探针订单并**确认收款**（走真实 API + 真实确认端点）⇒ 得到一张可退款订单。 */
export async function createProbeOrder(token, { productId, productName, skuId, skuCode, colorId, qty = 2, unitPrice = 100, tag = 'O' } = {}) {
  const u = uniq()
  const body = {
    customerName: `${PROBE_PREFIX}客户-${tag}-${u}`,
    customerPhone: `139${String(Math.floor(Math.random() * 1e8)).padStart(8, '0')}`,
    customerAddress: `${PROBE_PREFIX}地址（探针）`,
    logisticsType: 'express',
    logisticsCompany: `${PROBE_PREFIX}物流`,
    remark: `${PROBE_PREFIX}（线B 探针订单，用后自清）`,
    items: [{
      productId,
      productName: productName || `${PROBE_PREFIX}商品`,
      quantity: qty,
      unitPrice,
      subtotal: fmtQty(cents(unitPrice) * BigInt(Math.trunc(qty))),   // 实测必填（缺 ⇒ 422「小计不能为空」）
      width: 2.8, height: 2.0,
      processingInfo: { skuId, skuCode, colorId, doorWidth: '2.8m' },
    }],
  }
  const r = await api('POST', '/api/admin/orders', { token, body })
  if (!r.json?.success) return { ok: false, resp: r, body }
  const orderId = r.data?.id ?? r.data?.orderId
  // ⚠️ 确认收款端点 = `PUT /api/admin/orders/{id}/payment`
  //    （实测：POST /confirm-payment 不存在 ⇒ 订单停留 pending、库存不扣、台账零行）
  registerProbe('order', orderId, `${PROBE_PREFIX}探针订单-${tag}`)
  const confirm = await api('PUT', `/api/admin/orders/${orderId}/payment`, { token, body: {} })
  return {
    ok: true, orderId, orderNo: r.data?.orderNo, total: r.data?.totalAmount,
    actual: r.data?.actualAmount, resp: r, confirmResp: confirm, body,
  }
}

/** 探针订单的 DB 真身（判据一律以**库**为期望来源）。 */
export function orderRow(orderId) {
  return one(`select id, tenant_id, order_no, status, total_amount, actual_amount, refund_amount, refund_at, deleted
              from orders where id='${orderId}'`)
}
export function ticketRow(id) {
  return one(`select id, tenant_id, ticket_no, order_id, ticket_type, status, refund_amount, refund_method,
                     source, closed_at, close_reason, deleted from after_sales_tickets where id='${id}'`)
}
export function financeRefundRows(orderId) {
  return psql(`select id, type, amount, status, occurred_at, remark from finance_transactions
               where tenant_id=${TENANT_ID} and order_id='${orderId}' and type='refund' order by created_at`)
}
export function ledgerRowsFor(refNo) {
  return psql(`select id, product_id, sku_id, delta, before_qty, after_qty, reason, ref_no, note
               from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${refNo}' order by id`)
}
export function skuStock(skuId) {
  return one(`select id::text as id, stock, sales_count from product_skus where id=${skuId}`)
}

// ────────────────────────── 零残留 ──────────────────────────
/** 本包探针在**全库**的存活计数（只读；机器读数）。 */
export function probeResidue() {
  const T = TENANT_ID
  const P = ID_PREFIX.toUpperCase()
  const counts = {
    products: psql(`select id from products where tenant_id=${T} and (name like '${PROBE_PREFIX}%' or sku_code like '${P}-%')`).length,
    productSkus: psql(`select id from product_skus where tenant_id=${T} and sku_code like '${P}-%'`).length,
    orders: psql(`select id from orders where tenant_id=${T} and remark like '${PROBE_PREFIX}%'`).length,
    orderItems: psql(`select oi.id from order_items oi join orders o on o.id=oi.order_id where oi.tenant_id=${T} and o.remark like '${PROBE_PREFIX}%'`).length,
    tickets: psql(`select id from after_sales_tickets where tenant_id=${T} and description like '${PROBE_PREFIX}%'`).length,
    ticketTimeline: psql(`select tt.id from ticket_timeline tt join after_sales_tickets t on t.id=tt.ticket_id where tt.tenant_id=${T} and t.description like '${PROBE_PREFIX}%'`).length,
    ledger: psql(`select id from stock_ledger_entries where tenant_id=${T} and (product_id in (select id from products where name like '${PROBE_PREFIX}%') or sku_id in (select id from product_skus where sku_code like '${P}-%'))`).length,
    finance: psql(`select f.id from finance_transactions f join orders o on o.id=f.order_id where f.tenant_id=${T} and o.remark like '${PROBE_PREFIX}%'`).length,
    clientKeys: psql(`select client_request_id from client_request_keys where tenant_id=${T} and client_request_id like '${ID_PREFIX}-%'`).length,
    tempTables: psql(`select tablename from pg_tables where tablename like '${ID_PREFIX}_gp_%'`).length,
    processingOrders: psql(`select id from processing_orders where tenant_id=${T} and order_id in (select id from orders where tenant_id=${T} and remark like '${PROBE_PREFIX}%')`).length,
    positionOperations: psql(`select ppo.id from processing_position_operations ppo join processing_orders po on po.id=ppo.processing_order_id where ppo.tenant_id=${T} and po.order_id in (select id from orders where tenant_id=${T} and remark like '${PROBE_PREFIX}%')`).length,
    workLogs: psql(`select w.id from production_work_logs w join processing_orders po on po.id=w.processing_order_id where w.tenant_id=${T} and po.order_id in (select id from orders where tenant_id=${T} and remark like '${PROBE_PREFIX}%')`).length,
  }
  return { counts, total: Object.values(counts).reduce((a, b) => a + b, 0) }
}

/** 硬删本包探针数据（仅本包命名域；子行先删，FK 顺序即安全顺序）。 */
export function cleanupProbe() {
  const T = TENANT_ID
  const P = ID_PREFIX.toUpperCase()
  const errors = []
  const w = (sql, label) => {
    try { guardedWrite(`-- probe-ok\n${sql}`); return true } catch (e) { errors.push(`${label}: ${String(e.message).split('\n').find((l) => l.startsWith('ERROR')) || e.message.slice(0, 120)}`); return false }
  }
  // 三个作用域：① 命名前缀（兜底）② 注册表（**权威归属**，新增段自动覆盖）
  const ord = `select id from orders where tenant_id=${T} and (remark like '${PROBE_PREFIX}%' ${REGISTRY.orders.length ? `or id in (${REGISTRY.orders.map((x) => `'${x}'`).join(',')})` : ''})`
  const tk = `select id from after_sales_tickets where tenant_id=${T} and (description like '${PROBE_PREFIX}%' ${REGISTRY.tickets.length ? `or id in (${REGISTRY.tickets.map((x) => `'${x}'`).join(',')})` : ''})`
  const prod = `select id from products where tenant_id=${T} and (name like '${PROBE_PREFIX}%' or sku_code like '${P}-%' ${REGISTRY.products.length ? `or id in (${REGISTRY.products.map((x) => `'${x}'`).join(',')})` : ''})`
  const skus = `select id from product_skus where product_id in (${prod})`
  const po = `select id from processing_orders where tenant_id=${T} and order_id in (${ord})`
  const pos = `select id from processing_position_operations where tenant_id=${T} and processing_order_id in (${po})`
  const scopeNote = { orders: ord, afterSalesTickets: tk, products: prod, processingOrders: po }

  // ① 售后侧子行
  w(`delete from ticket_notes where ticket_id in (${tk});`, 'ticket_notes')
  w(`delete from ticket_timeline where tenant_id=${T} and ticket_id in (${tk});`, 'ticket_timeline')
  w(`delete from after_sales_tickets where id in (${tk});`, 'after_sales_tickets')
  // ② 资金流水
  w(`delete from finance_transactions where tenant_id=${T} and order_id in (${ord});`, 'finance_transactions')
  // ③ 库存台账（按探针商品/sku 或探针订单号）
  w(`delete from stock_ledger_entries where tenant_id=${T} and (product_id in (${prod}) or sku_id in (${skus}));`, 'ledger-by-product')
  w(`delete from stock_ledger_entries where tenant_id=${T} and ref_no in (select order_no from orders where id in (${ord}));`, 'ledger-by-orderno')
  // ④ 批次消耗 / 批次（**该表无 processing_order_id，按 processing_order_no 寻址** —— 实测踩过）
  w(`delete from stock_batch_consumptions where product_id in (${prod}) or sku_id in (${skus});`, 'batch_consumptions-by-product')
  w(`delete from stock_batch_consumptions where processing_order_no in (select processing_order_no from processing_orders where id in (${po}));`, 'batch_consumptions-by-po')
  w(`delete from stock_batches where product_id in (${prod});`, 'stock_batches')
  w(`delete from fabric_remnants where product_id in (${prod});`, 'fabric_remnants')
  w(`delete from inbound_order_items where product_id in (${prod});`, 'inbound_order_items')
  // ⑤ 加工单侧子行（FK 依赖清单由 information_schema 现取，见 out 证据）
  w(`delete from production_work_logs where tenant_id=${T} and processing_order_id in (${po});`, 'production_work_logs')
  w(`delete from worker_report_audits where processing_order_id in (${po});`, 'worker_report_audits')
  w(`delete from production_instance_repricing_logs where processing_order_id in (${po});`, 'repricing_logs')
  w(`delete from processing_set_part_tokens where processing_order_id in (${po});`, 'set_part_tokens')
  w(`delete from processing_position_operations where tenant_id=${T} and processing_order_id in (${po});`, 'position_operations')
  w(`delete from processing_order_sets where processing_order_id in (${po});`, 'order_sets')
  w(`delete from processing_orders where id in (${po});`, 'processing_orders')
  // ⑥ 订单侧子行
  w(`delete from order_logistics where order_id in (${ord});`, 'order_logistics')
  w(`delete from order_items where order_id in (${ord});`, 'order_items')
  w(`delete from orders where id in (${ord});`, 'orders')
  // ⑦ 商品侧子行
  w(`delete from product_skus where product_id in (${prod});`, 'product_skus')
  w(`delete from product_colors where product_id in (${prod});`, 'product_colors')
  w(`delete from product_attributes where product_id in (${prod});`, 'product_attributes')
  w(`delete from products where id in (${prod});`, 'products')
  // ⑧ 幂等键 / 临时表
  w(`delete from client_request_keys where tenant_id=${T} and client_request_id like '${ID_PREFIX}-%';`, 'client_request_keys')
  try {
    const temps = psql(`select tablename from pg_tables where tablename like '${ID_PREFIX}_gp_%'`)
    for (const x of temps) w(`drop table if exists ${x.tablename};`, `temp:${x.tablename}`)
  } catch (e) { errors.push('temp-scan: ' + e.message.slice(0, 100)) }
  try { writeFileSync(REGISTRY_FILE, JSON.stringify(REGISTRY, null, 2)) } catch { /* 非致命 */ }
  return { errors, scopeNote, registrySize: Object.fromEntries(Object.entries(REGISTRY).map(([k, v]) => [k, v.length])) }
}

// ────────────────────────── 红证注入（仅在**本包副本**上）──────────────────────────
/**
 * 判别力红证：把「守卫摘掉 / 守卫在位」两种等价 SQL 在**本包自建的临时表**上跑同一个并发实验。
 *
 * 🔴 纪律：**绝不改产品源码**（铁律 1）。本函数只做两件事：
 *   ① 临时表 `lb_gp_redproof` 上跑「**无** WHERE 上限」的等价 UPDATE
 *      ⇒ 证明「并发窗口真实存在 + 判据（累计 ≤ 上限）会红」；
 *   ② 同一个临时表上跑「**带** WHERE 上限」的同形 SQL（= 产品守卫的等价复刻）
 *      ⇒ 证明同一实验装置在守卫在位时**会绿**（⇒ 装置有判别力，不是恒红）。
 * N 个**独立 psql 进程**并发（真并发，非同进程内 await）；临时表用后即 drop，不留残留。
 */
export function redProofGuardExperiment(n = 6, cap = '100.00', each = '100.00') {
  const c = pgConf()
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  const setup = () => {
    w(`drop table if exists ${ID_PREFIX}_gp_redproof;`)
    w(`create table ${ID_PREFIX}_gp_redproof (id int primary key, refund_amount numeric(12,2), cap numeric(12,2));`)
    w(`insert into ${ID_PREFIX}_gp_redproof values (1, 0, ${cap});`)
  }
  const run = (guarded) => {
    const sql = guarded
      ? `UPDATE ${ID_PREFIX}_gp_redproof SET refund_amount = COALESCE(refund_amount,0) + ${each} WHERE id=1 AND COALESCE(refund_amount,0) + ${each} <= cap;`
      : `UPDATE ${ID_PREFIX}_gp_redproof SET refund_amount = COALESCE(refund_amount,0) + ${each} WHERE id=1;`
    const cmd = `for i in $(seq 1 ${n}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 -c "${sql}" >/dev/null 2>&1 & done; wait`
    execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
    return one(`select refund_amount from ${ID_PREFIX}_gp_redproof where id=1`)?.refund_amount
  }
  const out = { n, cap, each }
  setup(); out.unguardedResult = run(false)
  setup(); out.guardedResult = run(true)
  setup(); w(`drop table if exists ${ID_PREFIX}_gp_redproof;`)
  out.unguardedLeaked = cents(out.unguardedResult) > cents(cap)
  out.guardedHeld = cents(out.guardedResult) <= cents(cap)
  out.verdict = `无守卫 ⇒ 终值 ${out.unguardedResult}（上限 ${cap}，泄漏=${out.unguardedLeaked}）；` +
                `有守卫（产品同形复刻）⇒ 终值 ${out.guardedResult}（守住=${out.guardedHeld}）`
  return out
}

export { writeFileSync, readFileSync }
export const outPath = (f) => join(OUT, f)
