// 2026-10-06 智能派单省料验证 · **结论判定器（会红）**
//
// 独立复核（2026-10-06 11:05 +08）指出：J1~J4 的判定原先只活在 REPORT.md 的散文里、且
// `judge-selftest.mjs` 只有 console.log（**空断言**）、用的还是与主判据不同的期望函数。
// 本文件把这些判定收敛成**机器可核、会红**的断言：任一条不成立 ⇒ 非零退出。
//
//   node verify.mjs            # 判定（读 out/main.json + 现取配置表）
//   node verify.mjs --inject   # 判别力自证：注入式改坏期望 ⇒ 必须红（退出码非零）
import { readFileSync } from 'node:fs'
import { psql } from './lib.mjs'
import { expectedRoute, logicalOperation, T } from './steps.mjs'

const INJECT = process.argv.includes('--inject')
const R = JSON.parse(readFileSync(new URL('../out/main.json', import.meta.url), 'utf8'))
const results = []
const check = (id, ok, detail) => { results.push({ id, ok: !!ok, detail }); }

// ── 配置真值（现取，不落盘快照）──
const rules = psql(`select trigger_kind, trigger_value, coalesce(position,'') as position, action, operation,
  coalesce(after_operation,'') as after_operation, priority
  from production_route_rules where tenant_id=${T} and deleted=0 and status='active' order by priority, id`)
const tpl = psql(`select name, mainline::text as mainline from production_route_templates
  where tenant_id=${T} and is_default=true and status='active' and deleted=0`)[0]
const catalog = psql(`select name from production_operations where tenant_id=${T} and status='active' and deleted=0`).map((r) => r.name)
const mainline = JSON.parse(tpl.mainline)

// ── J1~J4：省料判定（读数来自 out/main.json 的落账聚合）──
const A = R.arms.A.ledger, B = R.arms.B.ledger, C = R.arms.C.ledger, D = R.arms.D.ledger
check('J1-池化省料真实存在', B.saved > 0 && B.saved > C.saved && B.saved > D.saved,
  `B.saved=${B.saved} > C.saved=${C.saved} / D.saved=${D.saved}`)
check('J1b-省料来自跨订单而非订单内', B.planned < B.formula && C.planned === C.formula,
  `B ${B.formula}→${B.planned}；C ${C.formula}→${C.planned}`)
check('J2-界面路径零扣减', A.rows === 0 && R.arms.A.ok === 75 && R.poPerArm.A === 75 && R.previewUI.savedMeters === 0,
  `A 消耗行=${A.rows}、派单成功=${R.arms.A.ok}/75、加工单=${R.poPerArm.A}、预览 saved=${R.previewUI.savedMeters}`)
check('J3-省料不虚报', R.rowInvariants.plannedLEformula && R.rowInvariants.plannedPositive,
  `planned≤formula=${R.rowInvariants.plannedLEformula}、planned>0=${R.rowInvariants.plannedPositive}、行数=${R.rowInvariants.rows}`)
check('J4-预览==落账', Math.abs(Number(R.previewFilled.savedMeters) - Number(B.saved)) < 0.005,
  `preview=${R.previewFilled.savedMeters} vs 落账 ${B.saved}`)

// ── R1~R7：工序 × 配置路线（期望由配置表展开，**不读实得行**）──
const expect = expectedRoute(INJECT ? mainline.filter((m) => m !== '打包') : mainline, rules, { craft: '韩褶', position: '布帘' })
check('R7-300 张单工序签名唯一', R.seqSignatureSet.length === 1, `签名数=${R.seqSignatureSet.length}`)
const actualNames = R.seqSignatureSet[0].split('>').map((s) => s.split(':')[1])
const actualLogical = actualNames.map(logicalOperation)
check('R5-工序序列 == 配置路线展开（归一后全序）', JSON.stringify(actualLogical) === JSON.stringify(expect),
  `期望 [${expect.join('>')}] 实得 [${actualLogical.join('>')}]`)
check('R3/R4-工序行数齐备', R.poOpsTotal === R.poCount * actualNames.length,
  `工序行 ${R.poOpsTotal} == ${R.poCount} 单 × ${actualNames.length} 道`)
check('R6-route_key/source 唯一且合法', R.routeKeySet.length === 1 && R.routeKeySet[0] === tpl.name
  && R.routeSourceSet.every((s) => ['direct', 'derived', 'partial', 'default', 'missing_route'].includes(s)),
  `route_key=${JSON.stringify(R.routeKeySet)}（配置模板名=${tpl.name}）route_source=${JSON.stringify(R.routeSourceSet)}`)
// 材料面（补 F1 的假绿通道）：本单是**布帘**单，实得工序行里不得出现纱系变体
const yarnLeak = actualNames.filter((n) => n.includes('纱'))
check('R8-布帘单不得出现纱系变体（防布/纱错料被归一掩盖）', yarnLeak.length === 0, `纱系=${JSON.stringify(yarnLeak)}`)

// ── 判据自身的诚实披露（复核 F1：归一函数**非单射**，会掩盖布/纱错料）──
const byLogical = new Map()
for (const n of catalog) { const k = logicalOperation(n); byLogical.set(k, [...(byLogical.get(k) || []), n]) }
const collisions = [...byLogical.entries()].filter(([, v]) => v.length > 1).map(([k, v]) => `${k}←{${v.join(',')}}`)

// ── 红证（判别力自证）：注入「缺一道」⇒ 期望必须与实得不同 ──
check('RED-注入式红证（摘掉主线的「打包」⇒ 判据必须报红）',
  INJECT ? JSON.stringify(actualLogical) !== JSON.stringify(expect) : true,
  INJECT ? `注入后期望 [${expect.join('>')}] 与实得不同 ⇒ 判据会红` : '未注入（正常判定）')

const failed = results.filter((r) => !r.ok)
console.log(JSON.stringify({ mode: INJECT ? 'inject' : 'judge', pass: results.length - failed.length, fail: failed.length, results, judgeCaveat: { normalizationCollisions: collisions.length, examples: collisions.slice(0, 6) } }, null, 1))
process.exit(failed.length === 0 ? 0 : 1)
