// 配置写面「写后等价性」横切扫描 —— 快照 / 字段级 diff / 判据 / 还原自证
//
// 核心判据（本线的灵魂）：
//   一次「只改一个字段」的保存，**允许变化的字段集必须恰好等于你发出的 payload 的键**
//   （外加显式声明的审计 / 版本 / 时间戳字段）。多一处即红。
//
// 证据纪律（migao-acceptance）：每条记录带可复核证据（HTTP 读数 + SQL 原文 + 字段级 diff 原文）。
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { psql, psqlWrite, one, log } from './lib.mjs'

export const T = Number(process.env.TENANT_ID || 20)

// ── 时间戳 / 审计列（**显式声明**）：任何写面命中它们都不算越界（但必须逐条报出）──
export const AUDIT_FIELDS = new Set(['updated_at', 'created_at'])

// 主面：必须逐字段盯住的配置表（判据主体）
export const PRIMARY_TABLES = [
  'production_operations',
  'production_operation_positions',
  'production_route_templates',
  'production_route_rules',
  'processing_fee_combinations',
  'production_route_signals',
  'craft_calc_configs',
  'cutting_height_configs',
  'production_crafts',
  'processing_items',
  'processing_categories',
]

// 审计 / 版本面（**显式声明的副账**）：允许出现「只追加、只针对本次目标实体」的行
export const AUDIT_TABLES = [
  'production_operation_price_versions',
  'production_operation_position_price_versions',
  'production_routing_versions',
  'processing_fee_combination_versions',
  'tenant_param_audit',
  'audit_logs',
]

export const ALL_TABLES = [...PRIMARY_TABLES, ...AUDIT_TABLES]

// 行标识：优先 id，否则用业务键拼接（保证跨快照可比对）
const ROW_KEYS = {
  production_operations: 'id',
  production_operation_positions: 'id',
  production_route_templates: 'id',
  production_route_rules: 'id',
  processing_fee_combinations: 'id',
  production_route_signals: 'id',
  craft_calc_configs: 'id',
  cutting_height_configs: 'id',
  production_crafts: 'id',
  processing_items: 'id',
  processing_categories: 'id',
}

/** 确定性 JSON：对象键递归排序 ⇒ 同内容必得同串（jsonb 键序不稳定，不能直接比原文）。 */
function canon(v) {
  if (v === null || typeof v !== 'object') return v
  if (Array.isArray(v)) return v.map(canon)
  const out = {}
  for (const k of Object.keys(v).sort()) out[k] = canon(v[k])
  return out
}
export const canonStr = (v) => JSON.stringify(canon(v))
const sha256 = (s) => createHash('sha256').update(s).digest('hex')

// 表元数据（存在性 / deleted 列 / tenant_id 列）—— 启动时**一次**取回（不逐表 io）
let _meta = null
export async function loadMeta() {
  if (_meta) return _meta
  const raw = psql(`select table_name, string_agg(column_name, ',') as cols
      from information_schema.columns where table_schema='public' group by table_name`)
  const m = new Map()
  for (const r of raw) {
    const cols = new Set(String(r.cols).split(','))
    m.set(r.table_name, { exists: true, hasDeleted: cols.has('deleted'), hasTenant: cols.has('tenant_id') })
  }
  _meta = m
  return m
}
const tableExists = async (t) => (await loadMeta()).get(t)?.exists === true
const hasDeleted = async (t) => (await loadMeta()).get(t)?.hasDeleted === true

/** 快照 SQL：每表一段 `select '<表>' as _t, row_to_json(x) ... where tenant_id=T order by <key>`，union all **一次**发。 */
async function snapshotSql() {
  const meta = await loadMeta()
  const parts = []
  for (const t of ALL_TABLES) {
    const md = meta.get(t)
    if (!md?.exists) { parts.push(`select '${t}'::text as _t, null::json as _r`); continue }
    const key = ROW_KEYS[t] || 'id'
    const where = md.hasTenant ? `where tenant_id=${T}` : ''
    parts.push(`(select '${t}'::text as _t, row_to_json(x) as _r from (select * from ${t} ${where} order by ${key}) x)`)
  }
  return parts.join(' union all ')
}

/**
 * 对**整个租户的配置表全集**做逐行逐字段快照（**一次** SQL 往返）。
 * - 含软删行（`deleted=1` 也快照：横切扫描要看见「孤儿行被新建」这类副作用）
 * - 行序由主键/业务键决定 ⇒ 两次快照可直接逐行比对
 */
export async function snapshot(label) {
  const rows = new Map()
  const hashes = {}
  const at = new Date().toISOString()
  const data = psql(await snapshotSql())
  for (const rec of data) {
    const t = rec._t
    if (rec._r == null) { hashes[t] = 'TABLE_MISSING'; continue }
    const r = rec._r
    const key = ROW_KEYS[t] || 'id'
    const rowKey = r[key] != null ? String(r[key]) : canonStr(r)
    rows.set(`${t}|${rowKey}`, { table: t, rowKey, fields: r })
  }
  for (const t of ALL_TABLES) {
    if (hashes[t] !== undefined) continue
    const all = [...rows.values()].filter((x) => x.table === t)
      .sort((a, b) => (a.rowKey < b.rowKey ? -1 : a.rowKey > b.rowKey ? 1 : 0))
      .map((x) => `${x.rowKey}=${canonStr(x.fields)}`)
      .join('\n')
    hashes[t] = sha256(all)
  }
  log(`[snapshot ${label}] ${at} rows=${rows.size} tables=${ALL_TABLES.length}`)
  return { at, rows, hashes }
}

/**
 * 字段级 diff：返回 [{table,rowKey,field,before,after,kind}]
 * kind ∈ added-row / removed-row / field
 */
export function diff(before, after) {
  const out = []
  for (const [k, b] of before.rows) {
    const a = after.rows.get(k)
    if (!a) { out.push({ table: b.table, rowKey: b.rowKey, field: '*', before: 'ROW_EXISTS', after: 'ROW_MISSING', kind: 'removed-row' }); continue }
    const fields = new Set([...Object.keys(b.fields), ...Object.keys(a.fields)])
    for (const f of fields) {
      const bv = b.fields[f], av = a.fields[f]
      if (canonStr(bv) !== canonStr(av)) {
        out.push({ table: b.table, rowKey: b.rowKey, field: f, before: bv, after: av, kind: 'field' })
      }
    }
  }
  for (const [k, a] of after.rows) {
    if (!before.rows.has(k)) out.push({ table: a.table, rowKey: a.rowKey, field: '*', before: 'ROW_MISSING', after: 'ROW_ADDED', kind: 'added-row' })
  }
  return out.sort((x, y) => (x.table + x.rowKey + x.field).localeCompare(y.table + y.rowKey + y.field))
}

/** 把 diff 压成「表.字段」集合（判据用的口径）。 */
export function changedKeys(d) {
  return [...new Set(d.map((x) => (x.kind === 'added-row' ? `${x.table}.*(row-added)` : x.kind === 'removed-row' ? `${x.table}.*(row-removed)` : `${x.table}.${x.field}`)))].sort()
}

/**
 * 越界判据：允许集合 = payload 键 ∪ 审计列 ∪ 显式声明的白名单。
 * 🔴 审计/版本表里**任何**变化都不算主判据越界，但**必须**单独作为 declaredAudit 报出（不许静默）。
 */
export function overreach(d, payloadKeys = [], { extraAllowed = [] } = {}) {
  const allow = new Set([...payloadKeys, ...AUDIT_FIELDS, ...extraAllowed])
  const out = []
  for (const x of d) {
    if (AUDIT_TABLES.includes(x.table)) continue // 副账：单列，不计越界
    if (x.kind !== 'field') {
      if (!allow.has(`${x.table}.*`) && !allow.has(x.table)) out.push(x)
      continue
    }
    if (!allow.has(x.field) && !allow.has(`${x.table}.${x.field}`) && !allow.has(x.table)) out.push(x)
  }
  return out
}

/** 审计/版本面里出现的变化（显式声明的副账）—— 单独报出，不当越界。 */
export const declaredAudit = (d) => d.filter((x) => AUDIT_TABLES.includes(x.table))

export const fmt = (d) => d.map((x) => `${x.table}.${x.rowKey}.${x.field}: ${canonStr(x.before)} → ${canonStr(x.after)} [${x.kind}]`)

// ────────────── 时间口径（铁律：一切时间表达用本机时区 Asia/Shanghai = UTC+8）──────────────
/** +08 口径时间戳（原始 JSON 里同时存 UTC ISO，标注换算）。 */
export function nowCST() {
  const d = new Date()
  const p = (n, w = 2) => String(n).padStart(w, '0')
  const off = -d.getTimezoneOffset()
  const sign = off >= 0 ? '+' : '-'
  const l = new Date(d.getTime() + off * 60000)
  const cst = `${l.getFullYear()}-${p(l.getMonth() + 1)}-${p(l.getDate())} ${p(l.getHours())}:${p(l.getMinutes())}:${p(l.getSeconds())} +08`
  return { cst, utc: d.toISOString(), tz: `UTC${sign}${p(Math.floor(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}` }
}

/**
 * **构建点自证**：本包全部读数必须钉在一个**明确的部署点**上。
 * 本会话实测到部署点在测量期间移动（worktree `402be478b` → `a4aaa3c24`，Java 进程重启），
 * ⇒ 每次运行都要把 (HEAD, 编译产物 mtime, Java 进程启动时刻, 是否含已知修复) 记进读数。
 */
export function buildPoint(worktree = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live') {
  const git = (args) => { try { return execFileSync('git', ['-C', worktree, ...args], { encoding: 'utf8' }).trim() } catch { return 'unknown' } }
  const sha = git(['rev-parse', '--short', 'HEAD'])
  const subject = git(['log', '-1', '--format=%s'])
  let hasFix = false
  try { execFileSync('git', ['-C', worktree, 'merge-base', '--is-ancestor', '1d1fe5e55', 'HEAD']); hasFix = true } catch { hasFix = false }
  let classMtime = 'unknown', procStart = 'unknown'
  try {
    classMtime = execFileSync('stat', ['-f', '%Sm', '-t', '%F %T',
      `${worktree}/backend/admin-api/target/classes/com/migao/admin/service/ProductionOperationCommandService.class`], { encoding: 'utf8' }).trim()
  } catch { /* ignore */ }
  try {
    const line = execFileSync('ps', ['-eo', 'lstart,command'], { encoding: 'utf8' }).split('\n').find((l) => l.includes('AdminApiApplication'))
    if (line) procStart = line.slice(0, 24).trim()
  } catch { /* ignore */ }
  return { worktree, sha, subject, hasFix, classMtime, procStart, at: nowCST().cst }
}

export async function login(phone = process.env.ADMIN_PHONE || '13870217889') {
  const { loginApi } = await import('./lib.mjs')
  return (await loginApi(phone)).token
}

/** 写一行 SQL（还原 / 注入用）。 */
export const writeSql = (sql) => psqlWrite(sql)

/** SQL 字面量（正确转义 null / 数字 / 字符串 / 布尔 / JSON）。 */
export function lit(v) {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'object') return `'${canonStr(v).replace(/'/g, "''")}'::jsonb`
  return `'${String(v).replace(/'/g, "''")}'`
}

/**
 * **探针行归属判据**：一行是不是**我这次探针的对象**？
 * 判据 = 行内容里出现我探针的标识串（如工序名 / 行 id）。
 * 🔴 为什么必须限定：**同租户另有并行包**（piecework-wage-sweep）会写同一批表；
 * 若不限定，`restoreTo` 会把**它的**改动也「还原」掉（实测：`复烫-布帘` 价被并行包改成 1.11，
 * 我的还原又把它写回 null ⇒ 我篡改了别人的写入，且「还原自证」会假红）。
 */
export function claimsFor(context) {
  const names = contextNames(context).filter((n) => n.length >= 6)
  if (names.length === 0) return () => false
  return (rowKey, fields) => {
    const blob = canonStr(fields || {})
    return names.some((n) => blob.includes(n) || String(rowKey).includes(n))
  }
}
/** 默认归属判据：任何含「写面横切」前缀的行都是我的；其余不是。 */
export const claimsPrefix = (prefix = '写面横切') => (rowKey, fields) =>
  String(rowKey).includes(prefix) || canonStr(fields || {}).includes(prefix)

/**
 * **拉到目标态**的还原（与写面机制无关 ⇒ 不依赖我猜对它的行为），两趟：
 *   ① 逐行逐字段把 `snap.rows` 里的每一行写回目标值（含 `deleted` 翻回）
 *   ② 把「目标态里没有」的**我的**行软删（`deleted=1`）—— 再取一次快照做这趟，避免漏掉两趟之间新增的行
 * `owns(rowKey, fields)` = 只碰**我自己探针的对象**（并行包的行一律不碰、也不计入残留）。
 * 每个动作都带「受影响行数」读数（0 行 = 没写进去，不许当成功）。
 */
export async function restoreTo(snap, { verbose = false, owns = claimsPrefix() } = {}) {
  const affects = []
  const keyOf = (t, f) => {
    const key = ROW_KEYS[t] || 'id'
    return `${key}=${typeof f[key] === 'number' ? f[key] : lit(f[key])}`
  }
  const affectedRows = (out) => {
    const m = String(out).match(/UPDATE\s+(\d+)/i)
    return m ? Number(m[1]) : null
  }
  // 趟 ①：字段写回
  const now1 = await snapshot('restore-pass1')
  for (const [k, tgt] of snap.rows) {
    if (!owns(k, tgt.fields)) continue
    const cur = now1.rows.get(k)
    if (!cur) { affects.push({ k, note: 'TARGET_ROW_MISSING_IN_DB', affected: null }); continue }
    const sets = []
    for (const f of Object.keys(tgt.fields)) {
      if (canonStr(cur.fields[f]) !== canonStr(tgt.fields[f])) sets.push(`${f}=${lit(tgt.fields[f])}`)
    }
    if (sets.length === 0) continue
    const sql = `update ${tgt.table} set ${sets.join(', ')} where ${keyOf(tgt.table, tgt.fields)} and tenant_id=${T}`
    const out = psqlWrite(sql)
    affects.push({ k, sets, sql, affected: affectedRows(out), out: String(out).trim().slice(0, 60) })
  }
  // 趟 ②：**我的**新行软删（重新取快照）
  const now2 = await snapshot('restore-pass2')
  for (const [k, cur] of now2.rows) {
    if (snap.rows.has(k)) continue
    if (!owns(k, cur.fields)) continue
    if (!(await hasDeleted(cur.table))) { affects.push({ k, note: 'NEW_ROW_NO_SOFTDELETE', table: cur.table, affected: null }); continue }
    const sql = `update ${cur.table} set deleted=1 where ${keyOf(cur.table, cur.fields)} and tenant_id=${T}`
    const out = psqlWrite(sql)
    affects.push({ k, note: 'SOFT_DELETED_NEW_ROW', sql, affected: affectedRows(out), out: String(out).trim().slice(0, 60) })
  }
  if (verbose) log(`[restore] 写回动作 ${affects.length} 次：${affects.map((a) => a.note || a.sets.join(',')).join(' | ')}`)
  return affects
}

/**
 * 还原自证（逐字段比对），**只比我自己的行**：
 *   ① 我的行：主面 = 0 残留；② 每个还原动作的受影响行数 > 0（不是 no-op）
 *   ③ 非我的行若有变化 ⇒ 单列「并行包改动」（不是我的残留，也**不**还原）
 */
export async function verifyClean(snap, affects = [], { owns = claimsPrefix() } = {}) {
  const now = await snapshot('verify-clean')
  // 🔴 关键口径：**本次还原动作软删掉的行**视为「已不在」（那正是还原动作本身），
  //    否则 `diff` 会把「我刚软删的行」记成 ROW_ADDED ⇒ **恒红**（实测踩过）。
  const goneKeys = new Set(affects.filter((a) => a.note === 'SOFT_DELETED_NEW_ROW').map((a) => a.k))
  const strip = (s) => {
    const rows = new Map()
    for (const [k, v] of s.rows) {
      if (goneKeys.has(k)) continue
      if (v.fields?.deleted === 1) continue // 软删行不参与「存活态」比对
      rows.set(k, v)
    }
    return { ...s, rows }
  }
  const all = diff(strip(snap), strip(now))
  const isMine = (x) => owns(`${x.table}|${x.rowKey}`, snap.rows.get(`${x.table}|${x.rowKey}`)?.fields ?? now.rows.get(`${x.table}|${x.rowKey}`)?.fields)
  const mine = all.filter(isMine)
  const foreign = all.filter((x) => !isMine(x))
  const primary = mine.filter((x) => PRIMARY_TABLES.includes(x.table))
  const audit = mine.filter((x) => AUDIT_TABLES.includes(x.table))
  const noop = affects.filter((a) => a.affected === 0)
  const unresolved = affects.filter((a) => a.note === 'TARGET_ROW_MISSING_IN_DB' || a.note === 'NEW_ROW_NO_SOFTDELETE')
  const softDeleted = goneKeys.size
  return { primary, audit, foreign, noop, unresolved, softDeleted, clean: primary.length === 0 && noop.length === 0 && unresolved.length === 0, hashes: now.hashes, total: all.length }
}

// ────────────── 读数辅助：某逻辑工序的**存活**价目行（有效价真值源）──────────────
export const alivePriceRows = (op) => psql(`select id, position, unit_price::text as p, applicable
    from production_operation_positions
    where tenant_id=${T} and logical_name='${op}' and coalesce(deleted,0)=0 order by position`)

/** 存活行的最小字段集规范化串（用于「还原后 == 还原前」的机器比对）。 */
export const priceSig = (op) => canonStr(alivePriceRows(op).map((r) => ({ position: r.position, p: r.p })).sort((a, b) => a.position.localeCompare(b.position)))

/**
 * 被测系统**自己的读面**（不是我的期望来源）：「工艺项」里该逻辑工序的有效价。
 * 未定价（键为 null）与「行缺失」是两件事，不得混同。
 */
export async function facePrice(token, op) {
  const { api } = await import('./lib.mjs')
  const r = await api('GET', '/api/admin/production/operation-positions', { token })
  const row = (r.json?.data || []).find((x) => x.operation === op)
  if (!row) return { face: '无价目行', http: r.status }
  return { face: row.unit_price == null ? 'NULL(未定价)' : String(row.unit_price), http: r.status }
}

/** 清掉该工序「非 通用」的存活价目行（= 此前写面残留的探针痕迹）——**清场**，不是本轮改动。 */
export async function clearStray(op) {
  const rows = alivePriceRows(op).filter((r) => r.position !== '通用')
  for (const r of rows) psqlWrite(`update production_operation_positions set deleted=1 where id='${r.id}'`)
  return rows
}

/**
 * 一条探针的**标准形态**（照抄执行，别自创）：
 *   快照(before) → 发**一个**写请求 → 快照(after) → 字段级 diff → 判据 → 还原 → 还原自证
 * 并发纪律：`startState` 若与快照不一致 ⇒ 判「疑似并发干扰」，重跑该条，不记缺陷。
 */
export async function probe(R, opts) {
  return probeOnce(R, opts, opts.maxRetry ?? 1)
}

/**
 * **价格副作用判据**（区分「写后等价性越界」与「越界是否伤钱」）：
 * 一次写面之后，该工序的**有效价**（读面口径）与**存活价目行集合**是否变化。
 * - 有效价变了 ⇒ **涉钱**副作用（P1）
 * - 只有行集合变了、有效价没变 ⇒ **等价性越界但不伤钱**（P3，仍是写面副作用）
 */
export async function priceEffect(token, opName, beforeFace, beforeRows) {
  const afterFace = await facePrice(token, opName)
  const afterRows = alivePriceRows(opName)
  const faceChanged = beforeFace.face !== afterFace.face
  const rowsChanged = canonStr(beforeRows) !== canonStr(afterRows)
  return {
    beforeFace: beforeFace.face, afterFace: afterFace.face, faceChanged,
    beforeRows, afterRows, rowsChanged,
    severity: faceChanged ? 'P1（涉钱：有效价被改写）' : rowsChanged ? 'P3（等价性越界，但有效价未变 ⇒ 暂不伤钱）' : '—',
  }
}

/** 取 context / ownedValues 里出现的对象标识串（用于区分「我的写面副作用」与「并行包的行」）。 */
function contextNames(c) {
  if (!c) return []
  const out = []
  const walk = (v) => {
    if (typeof v === 'string') { out.push(v); return }
    if (Array.isArray(v)) return v.forEach(walk)
    if (v && typeof v === 'object') { for (const k of Object.keys(v)) walk(v[k]) }
  }
  walk(c)
  return [...new Set(out.filter(Boolean))]
}

/**
 * 越界项的归因（用**行内容**判，不用行身份 —— 新增行在 before 里没有对应行）：
 *   ① `ownedValues` 显式声明「本次写面自己的目标对象标识」⇒ 行内容含它 = **本写面副作用**（= 发现）
 *   ② `context` 的探针对象名（前缀「写面横切」等）⇒ 同样是**我的**行
 *   ③ 其余越界项：若目标表**根本不在我的写面契约里** ⇒ 一律算**本写面副作用**（保守，宁记缺陷不放过）
 *      只有「内容的字段值匹配不上任何我的标识，且**名字列**明显属于别的对象」才算外来（并行包）
 * 说明：本线宁**多记**缺陷、不放过；`foreign` 只在证据明确时使用（记 skip 而非 pass）。
 */
function attribute(over, after, { context, ownedValues = [] } = {}) {
  const names = [...contextNames(context), ...ownedValues].filter((n) => typeof n === 'string' && n.length >= 4)
  const mine = [], foreign = []
  for (const x of over) {
    const row = after.rows.get(`${x.table}|${x.rowKey}`)
    const blob = row ? canonStr(row.fields) : ''
    if (names.some((n) => blob.includes(n))) { mine.push(x); continue }
    // 名字列（logical_name / trigger_value / composition_key / name）整体不属于我 ⇒ 外来
    const nameField = row?.fields?.logical_name ?? row?.fields?.trigger_value ?? row?.fields?.composition_key ?? row?.fields?.name
    if (row && typeof nameField === 'string' && !names.some((n) => nameField.includes(n))) { foreign.push(x); continue }
    mine.push(x)
  }
  return { mine, foreign }
}

async function probeOnce(R, { id, name, note, payloadKeys, startState, act, declareAudit = true, context, ownedValues }, retriesLeft) {
  const before = await snapshot(`${id}-before`)
  if (startState) {
    const mism = startState(before)
    if (mism && mism.length) {
      R.add(id, name, 'skip', `⏭ 前置不成立 / 疑似并发干扰：${mism.join(' | ')}；本条记 skip（不记缺陷）`)
      return { skipped: true, mism }
    }
  }
  const res = await act()
  const after = await snapshot(`${id}-after`)
  const d = diff(before, after)
  const rawOver = overreach(d, payloadKeys, note?.extraAllowed ? { extraAllowed: note.extraAllowed } : {})
  const audit = declaredAudit(d)
  const { mine: over, foreign } = attribute(rawOver, after, { context, ownedValues })

  // 只有「外来新增行」才判「疑似并发干扰」——**必须在同一写请求内没有我自己的后果时**才能重跑，
  // 否则重跑会被第一次的副作用（如「布帘」行已存在 ⇒ 幂等跳过）**掩盖**（实测踩过，属假绿）。
  const myCorroborating = rawOver.some((x) => x.kind === 'added-row' && after.rows.get(`${x.table}|${x.rowKey}`) &&
    [...contextNames(context), ...(ownedValues || [])].some((n) => typeof n === 'string' && n.length >= 4 && canonStr(after.rows.get(`${x.table}|${x.rowKey}`).fields).includes(n)))
  if (foreign.length > 0 && retriesLeft > 0 && !myCorroborating) {
    await restoreTo(before, { owns: claimsFor(context) })
    R.add(id, name, 'skip',
      `⏭ 疑似并发干扰（同租户并行包 piecework-wage-sweep）：写窗口内的变化落在**不是我探针对象**的行上` +
      `（${JSON.stringify(changedKeys(foreign))}）⇒ 已还原到 before 并重跑该条（不记缺陷）`)
    return await probeOnce(R, { id, name, note, payloadKeys, startState, act, declareAudit, context, ownedValues }, retriesLeft - 1)
  }

  const ok = over.length === 0
  const ev = [
    `${note?.request || '(request)'}`,
    `payload 键=[${payloadKeys.join(',')}]；HTTP ${res?.status}${res?.httpNote ? ' / ' + res.httpNote : ''}`,
    `判据越界字段（应为空）: ${JSON.stringify(changedKeys(over))}`,
    `全部字段级 diff: ${fmt(d).join(' | ') || '（空）'}`,
    ...(declareAudit ? [`审计/版本面（显式声明副账，不计越界）: ${fmt(audit).join(' | ') || '（无）'}`] : []),
    ...(foreign.length ? [`外来行（并行包，已尽力归因）: ${fmt(foreign).join(' | ')}`] : []),
  ]
  ok
    ? R.pass(id, name, `越界 = 0（changed_keys ⊆ payload ∪ 审计列）；changed=${JSON.stringify(changedKeys(d))}`, ev)
    : R.fail(id, name, `🔴 越界 ${over.length} 处（本写面副作用）：${JSON.stringify(changedKeys(over))}（payload 键=[${payloadKeys.join(',')}]）`, ev)

  const owns = claimsFor(context)
  const ops = await restoreTo(before, { owns })
  const clean = await verifyClean(before, ops, { owns })
  ok_restore(R, id, name, ops, clean)
  return { skipped: false, over, foreign, d, audit, clean, res, before, after }
}

/** 还原自证的四条读数（主面残留 / no-op / 无法恢复项 / 审计面）统一出口。 */
function ok_restore(R, id, name, ops, clean) {
  const detail =
    `我的行主面残留=${clean.primary.length}；还原动作=${ops.length}（其中 no-op=${clean.noop.length}，无法恢复=${clean.unresolved.length}）；` +
    `审计面变化=${clean.audit.length}（显式声明副账）；软删回收=${clean.softDeleted} 行；**非我的行**（并行包改动，未触碰）=${clean.foreign.length}`
  const ev = [
    `还原 SQL（含受影响行数）: ${ops.map((o) => `${o.note || o.sets?.join(',') || '?'}[affected=${o.affected ?? 'n/a'}]`).join(' ;; ') || '（无差异）'}`,
    `我的行残留明细: ${fmt(clean.primary).join(' | ') || '（空）'}`,
    `审计面明细: ${fmt(clean.audit).join(' | ') || '（无）'}`,
    `非我的行（并行包；一律不还原）: ${fmt(clean.foreign).join(' | ') || '（无）'}`,
  ]
  clean.clean
    ? R.pass(`${id}-restore`, `${name} · 还原自证`, `逐字段比对「还原后 == 快照前」：${detail}`, ev)
    : R.fail(`${id}-restore`, `${name} · 还原自证`, `${detail}；残留：${fmt(clean.primary).join(' | ')}；no-op=${JSON.stringify(clean.noop)}；无法恢复=${JSON.stringify(clean.unresolved)}`, ev)
}
