// 跨租户隔离 + 权限横切 —— 差分对照验证主程序
//
// 主体：**全部由 env 注入**（issue #6937；唯一注入口 = acceptance/2026-10-03/lib/subjects.mjs）
//   A = TENANT_A/PHONE_A（被测主体）  B = TENANT_B/PHONE_B（对照租户 = 负例来源）
//   C = TENANT_C/PHONE_C（可选，第三租户）  P = TENANT_P/PHONE_P（可选，平台超管，租户恒 -1）
// 缺注入口 ⇒ **大声失败**（exit 2 + 打印怎么给），**不静默回退**；只有一侧真租户时须显式
// TENANT_B_ALLOW_MISSING=1 ⇒ B 侧判据一律**具名 skip**（印出来，不折算 pass）。
// 纪律（migao-acceptance 铁律 2/3）：每条判据必须**可红**（--flip 反向注入会把它变红），
//   每条结论必须带**逐字读数**（状态码 + 返回体片段 + DB 前后快照）。
// 零写入原则：只做读取 + 必须被拒绝的写尝试（跨租户写）。同租户正对照一律用**幂等 PUT**（值 = 现值）。
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log, psql, psqlWrite, one } from '../../config-writeface-sweep/harness/lib.mjs'
import { RESOURCES, dbIds, rowSnapshot, realCols } from './registry.mjs'
import { S, T, PH, SMS_CODE, MISSING_B, B_SKIP, SUBJECTS_LINE } from '../../lib/subjects.mjs'

const OUT = process.env.OUT_DIR ? process.env.OUT_DIR.replace(/\/?$/, '/') : fileURLToPath(new URL('../out/', import.meta.url))
const FLIP = process.argv.includes('--flip')
const recs = []
const rec = (o) => { recs.push(o); const i = o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'
  log(`${i} [${o.id}] ${o.name} — ${o.detail}`); return o }
const pass = (o) => rec({ ...o, verdict: 'pass' })
const fail = (o) => rec({ ...o, verdict: 'fail' })
const skip = (o) => rec({ ...o, verdict: 'skip' })
const cut = (s, n = 400) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)
const RAND = () => 'zz-nonexist-' + Math.random().toString(36).slice(2, 10)

log(`[env] 主体 ${SUBJECTS_LINE}（issue #6937：A=被测 / B=对照 / C=第三租户 / P=超管）`)
const BTAG = S.B ? `租户 ${T.B}（B）` : '对照租户 B（**未注入**）'

// ────────────────── 前置：登录 + 主体自洽性（注入的 TENANT_* 必须与登录自述一致）
const SUBJ = { A: PH.A, B: PH.B, C: PH.C, P: PH.P }
const tok = {}
const claims = {}
for (const [k, phone] of Object.entries(SUBJ)) {
  if (!phone) { log(`[subject] ${k} 未注入 ⇒ 不登录`); continue }
  const r = await loginApi(phone, SMS_CODE)
  tok[k] = r.token; claims[k] = r.raw.user
  log(`[subject] ${k} phone=${phone} tenantId=${r.raw.user.tenantId} tenantName=${r.raw.user.tenantName} role=${r.raw.user.role} user.id=${r.raw.user.id}`)
}
const mismatch = Object.entries(claims).filter(([k, u]) => Number(u.tenantId) !== T[k])
rec({ id: 'PRE-1', name: '主体自洽性（注入租户 = 登录自述租户）',
  verdict: tok.A && mismatch.length === 0 ? 'pass' : (tok.A ? 'fail' : 'fail'),
  detail: tok.A
    ? (mismatch.length === 0
      ? `${SUBJECTS_LINE} 与登录自述逐一对齐（不一致会让「DB 侧 id」与「token 所属租户」错位 ⇒ 全表判据失真）`
      : `🔴 注入租户与登录自述不一致：${mismatch.map(([k, u]) => `${k}: 注入 ${T[k]} vs 登录 ${u.tenantId}`).join('；')}`)
    : `🔴 A 侧登录失败 ⇒ 本 sweep 无法产出任何判据（注入口：${SUBJECTS_LINE}）`,
  evidence: Object.entries(claims).map(([k, u]) => `${k} 注入=${T[k]} 登录自述=${u.tenantId} name=${u.tenantName}`) })
if (MISSING_B) rec({ id: 'PRE-2', name: '对照租户注入口', verdict: 'skip', detail: B_SKIP, evidence: [SUBJECTS_LINE] })

// ────────────────── 0. 正对照可达性（非红证②：证明探针真能到达端点、token 有效、id 形态正确）
rec({ id: 'PC-0', name: '主体登录', verdict: tok.A ? 'pass' : 'fail',
  detail: `已登录主体：${Object.keys(tok).join('/') || '无'}（${SUBJECTS_LINE}）`,
  evidence: Object.entries(tok).map(([k, v]) => `${k}: token.len=${v.length}`) })

// ────────────────── 资源面：跨租户读（A 的 token 打 B 的 id）
const inv = []
for (const R of RESOURCES) {
  const aIds = dbIds(R.table, T.A)
  const bIds = dbIds(R.table, T.B)
  inv.push({ key: R.key, label: R.label, table: R.table, list: R.list, read: R.read ? R.read(':id') : null,
    write: R.write ?? null, A_ids: aIds.length, B_ids: bIds.length, B_sample: bIds.slice(0, 2) })
}
writeFileSync(OUT + 'inventory.json', JSON.stringify(inv, null, 1))
rec({ id: 'INV', name: '资源面枚举', verdict: 'pass',
  detail: `枚举 ${RESOURCES.length} 个有 tenant 维度的资源（A=${T.A} 有数据 ${inv.filter((x) => x.A_ids > 0).length}，${BTAG} 有数据 ${inv.filter((x) => x.B_ids > 0).length}）`,
  evidence: inv.map((x) => `${x.key}(${x.table}) A=${x.A_ids} B=${x.B_ids} read=${x.read ?? '—'} write=${x.write ?? '—'}`) })

const EXPECT_DENY = [401, 403, 404]
const denied = (st) => EXPECT_DENY.includes(st)
const leakIn = (text, ids) => (ids ?? []).filter((id) => text.includes(String(id)))

for (const R of RESOURCES) {
  const aIds = dbIds(R.table, T.A)
  const bIds = dbIds(R.table, T.B)
  const base = { res: R.key, label: R.label, table: R.table }
  if (!R.read) { skip({ id: `R-${R.key}`, name: `跨租户读·${R.label}`, detail: `该资源无「按 id 读」端点（OpenAPI 无 GET /…/{id}）⇒ 读面不可测，改由写面（W-${R.key}）+ 列表越界（L-${R.key}）覆盖`, ...base }); continue }
  if (bIds.length === 0) { skip({ id: `R-${R.key}`, name: `跨租户读·${R.label}`, detail: `${BTAG} 该表无存活行 ⇒ 无 B 侧 id 可打；仅做随机 id 段${MISSING_B ? `（真因：${B_SKIP}）` : ''}`, ...base }) }
  // 正对照：A 打 A 自己（必须 200）
  const pcId = aIds[0]
  const pc = pcId ? await api('GET', R.read(pcId), { token: tok.A }) : null
  const pcOk = pc?.status === 200
  if (!pcOk) {
    skip({ id: `R-${R.key}`, name: `跨租户读·${R.label}`, detail: `🔶探针失效跳过：正对照（A 打自己 id=${pcId ?? '无'}）未返回 200，实测 ${pc?.status} ⇒ 本资源读面**不可判**（不记为通过）`, ...base,
      evidence: [`GET ${pcId ? R.read(pcId) : '—'} → ${pc?.status} ${cut(pc?.text, 200)}`] })
    continue
  }
  const cases = []
  for (const bid of bIds.slice(0, 2)) {
    const r = await api('GET', R.read(bid), { token: tok.A })
    cases.push({ kind: 'B_id', id: bid, status: r.status, text: r.text, leak: leakIn(r.text, bIds) })
  }
  const rid = RAND()
  const rr = await api('GET', R.read(rid), { token: tok.A })
  cases.push({ kind: 'random', id: rid, status: rr.status, text: rr.text, leak: [] })
  const expectDeny = FLIP ? [200] : EXPECT_DENY
  const bad = cases.filter((c) => !expectDeny.includes(c.status) || c.leak.length > 0)
  const ev = [
    `正对照 A→A id=${pcId} → 200（reachable=true）`,
    ...cases.map((c) => `${c.kind} id=${c.id} → ${c.status} leak=${JSON.stringify(c.leak)} body=${cut(c.text, 180)}`),
  ]
  if (bad.length === 0) pass({ id: `R-${R.key}`, name: `跨租户读·${R.label}`, detail: `${cases.length} 例全部拒绝（${cases.map((c) => c.status).join('/')}），无 B 数据泄漏；正对照 200`, ...base, evidence: ev })
  else fail({ id: `R-${R.key}`, name: `跨租户读·${R.label}`, detail: `🔴 ${bad.length}/${cases.length} 例未拒绝或含 B 数据：${bad.map((c) => `${c.kind}:${c.status}${c.leak.length ? '(泄漏' + c.leak + ')' : ''}`).join(' ')}`, ...base, evidence: ev })
}

// ────────────────── 列表越界：A 的列表 id 集合 ∩ B 的全量 id 集合 == ∅
for (const R of RESOURCES) {
  const bIds = new Set(dbIds(R.table, T.B))
  const r = await api('GET', R.list, { token: tok.A })
  if (r.status !== 200) { skip({ id: `L-${R.key}`, name: `列表越界·${R.label}`, detail: `列表端点 ${R.list} 对 A 返回 ${r.status} ⇒ 不可判`, evidence: [`GET ${R.list} → ${r.status} ${cut(r.text, 200)}`] }); continue }
  let ids = []
  try { ids = (R.extract(r.json?.data) ?? []).map(String) } catch (e) { ids = [] }
  const inter = ids.filter((i) => bIds.has(i))
  const ev = [`GET ${R.list} → 200，A 侧返回 id 数=${ids.length}`, `${BTAG} 全量 id 数=${bIds.size}`, `交集=${JSON.stringify(inter.slice(0, 10))}`]
  const flipOk = FLIP ? inter.length > 0 : inter.length === 0
  if (flipOk) pass({ id: `L-${R.key}`, name: `列表越界·${R.label}`, detail: `A 列表 ∩ B 全量 = ∅（A 侧 ${ids.length} 条 vs B 侧 ${bIds.size} 条）${ids.length === 0 ? ' ⚠️A 侧为空，正对照弱' : ''}${bIds.size === 0 ? ' ⚠️B 侧为空 ⇒ 判别力弱' : ''}`, evidence: ev })
  else fail({ id: `L-${R.key}`, name: `列表越界·${R.label}`, detail: `🔴 A 的列表出现 B 的 id：${JSON.stringify(inter.slice(0, 10))}`, evidence: ev })
}

// ────────────────── 跨租户写：A 的 token 对 B 的 id 发 PUT/DELETE ⇒ 必须拒绝且不改库
const WRES = RESOURCES.filter((R) => R.write)
for (const R of WRES) {
  const bIds = dbIds(R.table, T.B)
  const aIds = dbIds(R.table, T.A)
  if (bIds.length === 0) { skip({ id: `WT-${R.key}`, name: `跨租户写·${R.label}`, detail: `${BTAG} 无存活行 ⇒ 无对象可打${MISSING_B ? `（真因：${B_SKIP}）` : ''}` }); continue }
  const bid = bIds[0]
  R.snap = realCols(R.table, R.snap ?? [])
  const before = rowSnapshot(R.table, bid, R.snap ?? [])
  const body = R.write === 'DELETE' ? undefined : (R.writeBody ? R.writeBody() : undefined)
  const w = await api(R.write, pathFor(R, bid), { token: tok.A, body })
  const after = rowSnapshot(R.table, bid, R.snap ?? [])
  const unchanged = JSON.stringify(before) === JSON.stringify(after)
  // 同租户正对照：证明该写端点对 A **可达**（不是一律 401/403）。
  // ⚠️ 实测（2026-10-14，#6937）：`{}` 空 body **不是幂等** —— 部分端点返回 200 并改写行。
  // ⇒ 写完立即**逐字段还原**并把还原读数写进证据（保证「零残留」不是空话）。
  let pc = null, pcRestored = null
  if (aIds.length > 0 && R.write !== 'DELETE') {
    const aid = aIds[0]
    const pcCols = R.snap ?? []
    const pcBefore = rowSnapshot(R.table, aid, pcCols)
    pc = await api(R.write, pathFor(R, aid), { token: tok.A, body: R.writeBody ? R.writeBody() : undefined })
    const pcAfter = rowSnapshot(R.table, aid, pcCols)
    if (JSON.stringify(pcBefore) !== JSON.stringify(pcAfter)) {
      restoreRow(R.table, aid, pcBefore)
      pcRestored = JSON.stringify(rowSnapshot(R.table, aid, pcCols)) === JSON.stringify(pcBefore)
    }
  }
  const expectDeny = FLIP ? [200] : EXPECT_DENY
  const good = expectDeny.includes(w.status) && unchanged
  const ev = [
    `跨租户写 A→B：${R.write} ${pathFor(R, bid)} body=${cut(body ?? '', 160)} → ${w.status} ${cut(w.text, 220)}`,
    `DB 前后快照（表 ${R.table} id=${bid}）：before=${cut(before, 300)} after=${cut(after, 300)} unchanged=${unchanged}`,
    pc ? `正对照 A→A 写：${R.write} ${pathFor(R, aIds[0])} → ${pc.status} ${cut(pc.text, 160)}${pcRestored === null ? '（探针未改库）' : `（⚠️空 body 非幂等 ⇒ 探针写脏了 A ⇒ 逐字段还原：${pcRestored ? '已回到基线' : '🔴 还原失败'}）`}` : '正对照：无 A 侧对象或 DELETE（不做同租户删除）',
  ]
  if (good) pass({ id: `WT-${R.key}`, name: `跨租户写·${R.label}`, detail: `拒绝 ${w.status}，且库行逐字段未变（unchanged=true）`, evidence: ev })
  else fail({ id: `WT-${R.key}`, name: `跨租户写·${R.label}`, detail: `🔴 ${R.write} 打 B 的 id 得到 ${w.status}；库变动=${!unchanged}${!unchanged ? ' ⇒ 需还原！' : ''}`, evidence: ev })
  if (!unchanged) {
    rec({ id: `WT-${R.key}-RESTORE`, name: `🔴跨租户写生效·还原`, verdict: 'fail',
      detail: `跨租户写**真的改了 ${BTAG} 的数据** ⇒ 需按 evidence 的 before 逐字段还原`, evidence: [cut(before, 300), cut(after, 300)] })
  }
}

/** 用 JSON 预映像把一行**逐字段**还原。
 *  走 jsonb_populate_record ⇒ 类型安全（jsonb / 时间戳 / 数组都不需要手写引号；实测 `positions` 是 jsonb，
 *  手写 `'布料'` 会 `invalid input syntax for type json`）。 */
function restoreRow(table, id, before) {
  const cols = Object.keys(before).filter((c) => c !== 'id')
  const json = JSON.stringify(before).replace(/'/g, "''")
  psqlWrite(`update ${table} t set (${cols.join(', ')}) = `
    + `(select ${cols.join(', ')} from jsonb_populate_record(null::${table}, '${json}'::jsonb)) `
    + `where t.id = '${String(id).replace(/'/g, "''")}'`)
}

function pathFor(R, id) {
  if (R.key === 'orders') return `/api/admin/orders/${id}/content`
  if (R.read) return R.read(id)
  const map = { operations: `/api/admin/production/operations/${id}`, routings: `/api/admin/production/routings/${id}`,
    route_rules: `/api/admin/production/route-rules/${id}`, fee_combos: `/api/admin/production/processing-fee-combinations/${id}`,
    customer_tags: `/api/admin/customer-tags/${id}`, categories: `/api/admin/categories/${id}`,
    op_positions: `/api/admin/production/operation-positions/${id}`, notif_templates: `/api/admin/notification-templates/${id}`,
    notif_rules: `/api/admin/notification-rules/${id}`, knowledge_cards: `/api/admin/knowledge/cards/${id}` }
  return map[R.key] ?? `/api/admin/${R.key}/${id}`
}
writeFileSync(OUT + `sweep-${FLIP ? 'flip' : 'main'}.json`, JSON.stringify(recs, null, 1))
const c = (v) => recs.filter((r) => r.verdict === v).length
log(`=== 阶段读数（${FLIP ? 'FLIP 反向注入' : '主跑'}）：pass=${c('pass')} fail=${c('fail')} skip=${c('skip')} total=${recs.length}`)
if (c('fail') > 0) process.exitCode = 1
