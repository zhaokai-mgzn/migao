// ─────────────────────────────────────────────────────────────────────────────
// 跨租户验收工装 · **唯一**注入口（issue #6937）
//
// 为什么存在：2026-10-14 环境重建轮，`tenant-isolation-sweep` 与
// `tenant-concurrency-sweep` 的主体矩阵与手机号是**写死**的（租户 A=20 / B=21 / C=1 +
// 3 个手机号）⇒ 环境里那些租户已不存在 ⇒ 登录 401 ⇒ **整 sweep 一条判据都没跑出**
// （被判「未覆盖」，而不是「跑过且绿」）。本模块把主体 / 短信码 / 端点收成一处：
//   · 缺注入口 ⇒ **大声失败**（exit 2 + 打印怎么给），**严禁**回退到任何写死的租户；
//   · `MISSING_B` 只有**显式** `TENANT_B_ALLOW_MISSING=1` 才成立，且此时 B 侧判据一律
//     **具名 skip**（印出来，**不折算 pass**）——静默打空租户 = 空转断言，是本 issue 的病根；
//   · 模块导入时跑一次**写死主体守卫**（见文件末尾）：任何人把注入口写死回去 ⇒ 立即判红。
//
// 缺省给法（逐字可复制）：
//   export TENANT_A=<A 侧租户 id>  PHONE_A=<A 侧管理员手机号>
//   export TENANT_B=<B 侧租户 id>  PHONE_B=<B 侧管理员手机号>    # 对照租户
//   export SMS_CODE=<短信万能码>                                  # 本机 dev 通常 123456
// 可选：TENANT_C/PHONE_C（第三租户，「无关集」反向对照）、TENANT_P/PHONE_P（平台超管）、
//       API_BASE（默认 http://localhost:8080）、AGENT_BASE（默认 http://localhost:8001）、
//       FIXTURE_PHONE（写面载荷里的假手机号）、OUT_DIR、API_LOG、LABEL_A/LABEL_B/LABEL_C
// 一侧租户时的显式出口：export TENANT_B_ALLOW_MISSING=1
// ─────────────────────────────────────────────────────────────────────────────
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))              // acceptance/2026-10-03/lib
export const BASE_20261003 = join(HERE, '..')

export const HINT = [
  '跨租户 sweep 的主体**必须**由环境变量注入（issue #6937）；本工装不会回退到任何写死的租户。',
  '  export TENANT_A=<A 侧租户 id>  PHONE_A=<A 侧管理员手机号>',
  '  export TENANT_B=<B 侧租户 id>  PHONE_B=<B 侧管理员手机号>   # 对照租户（负例来源）',
  '  export SMS_CODE=<短信万能码>                                 # 本机 dev 通常 123456',
  '  # 可选：TENANT_C/PHONE_C（第三租户）、TENANT_P/PHONE_P（平台超管）、API_BASE/AGENT_BASE、',
  '  #       FIXTURE_PHONE、OUT_DIR、API_LOG、LABEL_A/LABEL_B',
  '  # 只有一侧真租户时（显式）：export TENANT_B_ALLOW_MISSING=1 ⇒ B 侧判据**具名 skip**，不折算 pass',
  '示例：',
  '  TENANT_A=32 PHONE_A=13800138000 TENANT_B=<对照租户 id> PHONE_B=<对照租户管理员手机号> \\',
  '    SMS_CODE=123456 node acceptance/2026-10-03/tenant-isolation-sweep/harness/sweep.mjs',
].join('\n')

function loudFail(problems) {
  const bar = '='.repeat(78)
  console.error(`\n${bar}\n🔴 [ENV-GUARD #6937] 跨租户 sweep 注入口缺失 —— **大声失败，不静默回退**\n${bar}`)
  for (const p of problems) console.error(`  · ${p}`)
  console.error(`\n${HINT}\n${bar}\n`)
  process.exit(2)
}

const env = (k) => (process.env[k] ?? '').trim()
const pairs = { A: ['TENANT_A', 'PHONE_A'], B: ['TENANT_B', 'PHONE_B'], C: ['TENANT_C', 'PHONE_C'], P: ['TENANT_P', 'PHONE_P'] }
const problems = []
const missing = {}

for (const [key, [tk, pk]] of Object.entries(pairs)) {
  const t = env(tk), p = env(pk)
  if (!t && !p) { missing[key] = 'both'; continue }
  if (!t || !p) { problems.push(`${key} 侧注入口**成对**给：${tk} 与 ${pk}（现在只有一个）`); missing[key] = 'partial'; continue }
  if (!/^-?\d+$/.test(t)) { problems.push(`${tk}='${t}' 不是整数租户 id`); missing[key] = 'partial'; continue }
  if (!/^\d{6,}$/.test(p)) { problems.push(`${pk}='${p}' 不是手机号形态`); missing[key] = 'partial'; continue }
  missing[key] = false
}
// A 侧是**不可缺**的被测主体；B 侧是本轮判据的负例来源，缺了要显式声明
if (missing.A) problems.push('A 侧（TENANT_A/PHONE_A）不可缺 —— 没有 A 就没有任何可判对象')
if (missing.B && env('TENANT_B_ALLOW_MISSING') !== '1') {
  problems.push('B 侧（TENANT_B/PHONE_B）缺 —— 隔离/并发面的**负例**全靠它；')
  problems.push('  确实只有一侧真租户时请**显式**声明：export TENANT_B_ALLOW_MISSING=1（B 侧判据将具名 skip）')
}
if (!env('SMS_CODE')) problems.push('SMS_CODE 缺 —— 短信码也是注入口（本机 dev 通常 123456）')
if (problems.length) loudFail(problems)

const SMS = env('SMS_CODE')
const MISSING_B = missing.B === 'both'
const subject = (key, labelFallback) => (missing[key] === false
  ? { tenant: Number(env(pairs[key][0])), phone: env(pairs[key][1]), label: env(`LABEL_${key}`) || labelFallback }
  : null)
const S = { A: subject('A', 'A 侧'), B: subject('B', 'B 侧对照'), C: subject('C', 'C 侧'), P: subject('P', '平台超管') }
S.P = S.P ? { ...S.P, tenant: -1 } : null    // 平台超管租户 = 产品常量 -1（不是环境夹具）

// 隔离面的前提：主体之间必须是**不同**的真租户，否则「跨租户」无意义（自相矛盾即大声失败）
const distinct = [['A', 'B'], ['A', 'C'], ['B', 'C']].filter(([x, y]) => S[x] && S[y])
for (const [x, y] of distinct) {
  if (S[x].tenant === S[y].tenant) loudFail([`TENANT_${x} === TENANT_${y} === ${S[x].tenant} ⇒ 跨租户隔离面无判别力（两个主体是同一个租户）`])
}
if (S.P && [S.A, S.B, S.C].some((s) => s && s.tenant === -1)) loudFail(['TENANT_P 与某个商户侧租户同 id（-1）'])

export const T = { A: S.A.tenant, B: S.B?.tenant ?? null, C: S.C?.tenant ?? null, P: S.P?.tenant ?? -1 }
export const PH = { A: S.A.phone, B: S.B?.phone ?? null, C: S.C?.phone ?? null, P: S.P?.phone ?? null }
export { S, SMS, MISSING_B }
export const SMS_CODE = SMS
export const API_BASE = env('API_BASE') || 'http://localhost:8080'
export const AGENT_BASE = env('AGENT_BASE') || 'http://localhost:8001'
/** 写面**载荷**里的假手机号（不是主体身份；与主体注入解耦） */
export const FIXTURE_PHONE = env('FIXTURE_PHONE') || PH.A
export const B_SKIP = MISSING_B
  ? '对照租户 B 未注入（TENANT_B/PHONE_B 缺，已显式 TENANT_B_ALLOW_MISSING=1）⇒ 本判据**具名跳过**，**不折算 pass**；给法见 acceptance/2026-10-03/lib/subjects.mjs 的 HINT'
  : null
export const SUBJECTS_LINE = `A=${S.A.tenant}/${S.A.phone}`
  + (S.B ? ` B=${S.B.tenant}/${S.B.phone}` : ' B=**未注入**')
  + (S.C ? ` C=${S.C.tenant}/${S.C.phone}` : ' C=—')
  + (S.P ? ` P=${S.P.tenant}/${S.P.phone}` : ' P=—')

/** 启动横幅：把「到底注入了什么」逐字印出来（读数可复核，不是靠记忆） */
export function announce(log = console.log) {
  log(`[env] ${SUBJECTS_LINE} sms=${SMS ? '已注入' : '缺'} api=${API_BASE} agent=${AGENT_BASE}${MISSING_B ? ' TENANT_B_ALLOW_MISSING=1' : ''}`)
}

// ─────────────────────────────────────────────────────────────────────────────
// 写死主体守卫：**回归时会红**
// 有人把注入口写死回去（手机号字面量 / tenant 字面量 / dbIds 里的数字租户）⇒ 直接判红。
// 台账 LEDGER **只许缩短**（现取为空）；命中即列出 file:line + 该写成什么。
// ─────────────────────────────────────────────────────────────────────────────
const GUARD_DIRS = ['tenant-isolation-sweep/harness', 'tenant-concurrency-sweep/harness']
const LEDGER = []   // 只许缩短：{ file, rule, reason }
const RULES = [
  { rule: 'phone-literal', re: /\b1[3-9]\d{9}\b/, fix: '手机号走 PHONE_A/PHONE_B/PHONE_C/PHONE_P 或 FIXTURE_PHONE' },
  { rule: 'tenant-field-literal', re: /\btenant(?:Id|_id)?\s*[:=]\s*-?(?!1\b)\d+/, fix: '租户 id 走 TENANT_A/TENANT_B/TENANT_C（平台常量 -1 除外）' },
  { rule: 'tenant-sql-literal', re: /tenant_id\s*(?:=|in\s*\()\s*-?\s*(?!1\b)\d/, fix: `SQL 里写 \\${T.A} / \\${T.B}，不写数字租户` },
  { rule: 'dbids-literal', re: /dbIds\([^,)]+,\s*-?(?!1\b)\d+/, fix: 'dbIds(表, T.A | T.B | T.C)' },
  { rule: 'x-tenant-id-literal', re: /X-Tenant-Id['"]?\s*:\s*['"]?-?\d/, fix: 'String(T.B)' },
  { rule: 'subj-index-literal', re: /subj\[\s*-?\d+\s*\]/, fix: '按租户 id 建索引（subj[T.A]），不按下标' },
]
// 注入口自身也必须 fail-closed：`process.env.X || <数字>` 形态 = 静默默认，判红
const SELF_RULES = [{ rule: 'env-default-fallback', re: /process\.env\.(?:TENANT|PHONE|SMS)\w*\s*\|\|\s*-?\d/, fix: '缺注入口要 loudFail（exit 2），不要给默认值' }]

function scanFile(file, rules) {
  const hits = []
  const lines = readFileSync(file, 'utf8').split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (/guard-allow/.test(line)) continue
    for (const r of rules) {
      if (!r.re.test(line)) continue
      if (LEDGER.some((e) => e.file.endsWith(file.split('/').pop()) && e.rule === r.rule)) continue
      hits.push({ file, line: i + 1, rule: r.rule, text: line.trim().slice(0, 120), fix: r.fix })
    }
  }
  return hits
}

/** 扫描两条 sweep 的 harness + 本注入口自身；有命中即 exit 3（红）。 */
export function guardSubjects({ quiet = false } = {}) {
  const hits = []
  for (const d of GUARD_DIRS) {
    const dir = join(BASE_20261003, d)
    for (const f of readdirSync(dir)) {
      if (!f.endsWith('.mjs')) continue
      hits.push(...scanFile(join(dir, f), RULES))
    }
  }
  hits.push(...scanFile(fileURLToPath(import.meta.url), SELF_RULES))
  if (hits.length) {
    console.error(`\n🔴 [ENV-GUARD #6937] 写死主体 / 静默默认 命中 ${hits.length} 处（台账只许缩短，现取为空）：`)
    for (const h of hits) console.error(`  · ${h.file.split('/acceptance/')[1]} :: ${h.rule} → ${h.text}\n      改法：${h.fix}`)
    console.error('  若确需保留，必须写进 acceptance/2026-10-03/lib/subjects.mjs 的 LEDGER（附理由）。\n')
    process.exit(3)
  }
  if (!quiet) console.log(`[env-guard] 写死主体扫描：${GUARD_DIRS.join(' + ')} 命中 0 处（台账现取 0 条）`)
  return hits
}
guardSubjects()
