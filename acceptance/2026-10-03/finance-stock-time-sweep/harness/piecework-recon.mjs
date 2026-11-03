// 线③ 家族 A —— 计件报表的「逐人金额」与「无署名归集」判定（**纯函数**：零 IO / 零网络 / 零 DB）。
//
// 病（issue #7030，工装假红；实测误导过一次，并据此开出过一张错的「钱面缺陷」单 #7028）：
//   旧 A0b 拿独立 SQL 的 `worker_name` 分组（无署名那组是 NULL）去和接口 `per_worker` 的键**逐字**比对。
//   而接口会把无署名的那笔钱归进一个**服务端下发的展示文案**（本仓今天叫「未分配」；同一概念的
//   另一个读面 ProductionService.UNSIGNED_WORKER 叫「未署名」，见 issue #4309）⇒
//   「名不同、钱相同」⇒ 判据必然报「1 人不一致」，而失败文案（`{"worker_name":null,...}`）
//   天然指向「接口漏了这笔钱」—— 一条红不在真问题上的判据，会消耗掉别人一整轮排查并产出错误结论。
//
// 本模块的三条不变量（改动前先读；判据在 `piecework-recon.test.mjs`）：
//   ① **类的身份是结构，不是文案**：无署名 = 独立 SQL 里 `worker_name` 无文本的那一组；
//      接口侧对应的那一行由**结构**匹配得到（不属于任何真实工人的**残余行**，至多 1 行）——
//      文案只进证据。⇒ 服务端改文案**不会**让判据变红，也不存在第二份会漂的文案常量。
//   ② **无署名不许消失**：它不进逐人比（A0b），但必须被 A0c **单独**判：残余行 ≤ 1 行、
//      其金额 = 独立 SQL 的无名组金额，且 `总额 − 逐人合计 = 无署名金额`（差额可解释）。
//   ③ **判别力不降**：真实工人金额错 1 分 / 接口漏一组 / 两行无法归因 ⇒ **都必红**。
import { money2, fmt, S2 } from './lib.mjs'

/** 「无署名归集」这一**类**的显式标识（**不是**工人；判定从不拿它和任何工人名做字符串比较）。 */
export const UNASSIGNED = Symbol('piecework.unassigned')

/** 有文本即真实工人姓名（null / 空串 / 纯空白 ⇒ 无署名）。 */
const hasText = (v) => v != null && String(v).trim() !== ''

/**
 * 「这一行属于无署名归集吗」的**唯一**判定点。
 *
 * 🔴 红证注入点（issue #7030 判据 ④）：把函数体改成 `return false`（= 删掉「无署名」特殊处理）
 * ⇒ 无署名那组会被当成一个**名字为空的工人**去逐人比 ⇒ 夹具判据 ① 当场判红。
 * 复算 = tests/unit_ci_workflows/test_piecework_unnamed_recon_guard.py 的注入式红证。
 */
export function isUnassignedWorker(workerName) {
  return !hasText(workerName)
}

/** 金额 → 分（BigInt；缺值 ⇒ null，非法读数抛错 —— **不猜**）。 */
const cents = (v) => (v == null || v === '' ? null : money2(String(v)))
const addOrZero = (acc, v) => (v == null ? acc : acc == null ? v : acc + v)

/**
 * 把两侧读数分成三类：**真实工人**（逐人比）/ **无署名归集**（勾稽）/ **无法归因的残余行**。
 *
 * @param {{ expectRows?: object[], perWorker?: object[] }} input
 *   `expectRows` = 独立 SQL（group by worker_name，无署名组为 NULL）；
 *   `perWorker` = 接口 `per_worker` 原样（键名/文案取服务端实际下发值）。
 * @returns {{
 *   assigned: Array<{ name: string, expect: bigint|null, actual: bigint|null }>,
 *   unassigned: { kind: symbol, expect: bigint, actual: bigint|null, label: string|null, apiRow: object|null },
 *   residual: object[],
 * }}
 */
export function classifyPerWorker({ expectRows = [], perWorker = [] } = {}) {
  const expected = new Map()
  let unassignedExpect = 0n
  for (const row of expectRows || []) {
    const amount = cents(row?.amount)
    if (isUnassignedWorker(row?.worker_name)) {
      unassignedExpect = addOrZero(unassignedExpect, amount)
      continue
    }
    expected.set(String(row.worker_name), amount)
  }

  const apiRows = Array.isArray(perWorker) ? perWorker : []
  const apiByName = new Map()
  for (const row of apiRows) {
    const name = row?.worker_name == null ? null : String(row.worker_name)
    apiByName.set(name, addOrZero(apiByName.get(name) ?? null, cents(row?.amount)))
  }

  const assigned = [...expected.entries()].map(([name, expect]) => ({
    name,
    expect,
    actual: apiByName.has(name) ? apiByName.get(name) : null,
  }))
  const residual = apiRows.filter(
    (row) => !expected.has(row?.worker_name == null ? null : String(row.worker_name)),
  )
  // 残余行至多 1 行才是「无署名归集」；多于 1 行 ⇒ 无法归因（**不猜**哪一行才是归集）。
  const bucket = residual.length === 1 ? residual[0] : null

  return {
    assigned,
    unassigned: {
      kind: UNASSIGNED,
      expect: unassignedExpect,
      apiRow: bucket,
      label: bucket && bucket.worker_name != null ? String(bucket.worker_name) : null,
      actual: residual.length > 1 ? null : bucket ? cents(bucket.amount) : 0n,
    },
    residual,
  }
}

const money = (v) => (v == null ? 'null' : fmt(v, S2))

/**
 * 产出 A0b / A0c 两条判据（形状与 `lib.mjs` 的 `judge()` 入参一致，调用方直接 `judge(R, v)`）。
 *
 * @param {{ expectRows?: object[], perWorker?: object[], total?: string|number|null }} input
 *   `total` = 接口总额（A0a 已单独比过；这里只用它做**勾稽**，不当逐人的期望）。
 * @returns {object[]} `[a0b, a0c]`
 */
export function judgePiecework({ expectRows = [], perWorker = [], total } = {}) {
  const { assigned, unassigned, residual } = classifyPerWorker({ expectRows, perWorker })
  const isArray = Array.isArray(perWorker)
  const totalC = cents(total)

  // ── A0b：真实工人逐人金额（无署名归集**不进**这里）────────────────────
  const diffs = assigned
    .filter((x) => x.actual === null || x.actual !== x.expect)
    .map((x) => ({
      worker_name: x.name,
      expect: money(x.expect),
      actual: x.actual === null ? null : money(x.actual),
      kind: x.actual === null ? 'missing-in-api' : 'amount-mismatch',
    }))
  const a0b = {
    id: 'A0b',
    name: '计件工资逐人金额 = 独立 SQL 重算（**已剔除无署名归集**；归集由 A0c 单独勾稽）',
    expect: `逐人一致（${assigned.length} 人）`,
    actual: diffs.length === 0 ? `逐人一致（${assigned.length} 人）` : `${diffs.length} 人不一致`,
    pass: isArray && diffs.length === 0,
    expectSource:
      '独立 SQL：SUM(round(qualified_qty*unit_price,2)) group by worker_name，**只取有姓名的组**；'
      + '无署名组（worker_name 无文本）不进逐人比 —— 它的钱由 A0c 的勾稽判。期望不含接口任何读数，也不含服务端文案。',
    evidence: [
      `逐人差异（名不同 vs 钱不同，一眼可分）: ${JSON.stringify(diffs)}`,
      `独立 SQL 逐人: ${JSON.stringify(expectRows)}`,
      `接口 per_worker: ${JSON.stringify(perWorker)}`,
      `无署名归集（不进逐人比）: 独立 SQL ${money(unassigned.expect)} / 接口 ${money(unassigned.actual)}`
        + `（服务端文案「${unassigned.label ?? '（无该行）'}」）`,
    ],
  }

  // ── A0c：无署名归集 ⊆ 总额，且差额可解释 ────────────────────────────
  const problems = []
  const apiSum = isArray
    ? (perWorker || []).reduce((acc, row) => addOrZero(acc, cents(row?.amount)), 0n)
    : null
  const assignedActualSum = assigned.reduce((acc, x) => addOrZero(acc, x.actual), 0n)

  if (!isArray) problems.push('接口未返回 per_worker 数组 ⇒ 无法勾稽')
  if (totalC === null) problems.push('接口未返回 total ⇒ 无法勾稽')
  else if (totalC < 0n) problems.push(`接口总额为负（${money(totalC)}）⇒ 勾稽前提不成立`)
  if (residual.length > 1) {
    problems.push(
      `接口有 ${residual.length} 行不属于任何真实工人（只允许 1 行无署名归集，多行 ⇒ 无法归因）: `
      + JSON.stringify(residual.map((r) => r?.worker_name ?? null)),
    )
  }
  if (apiSum !== null && totalC !== null && apiSum !== totalC) {
    problems.push(`接口内部不自洽：Σ per_worker=${money(apiSum)} ≠ total=${money(totalC)}（差 ${money(apiSum - totalC)}）`)
  }
  if (unassigned.actual !== null && unassigned.actual !== unassigned.expect) {
    problems.push(
      `无署名归集对不上独立 SQL 的无名组：接口 ${money(unassigned.actual)}`
      + `（行文案「${unassigned.label ?? '（无该行）'}」） vs 独立 SQL ${money(unassigned.expect)}`,
    )
  }
  if (totalC !== null && unassigned.actual !== null && totalC - assignedActualSum !== unassigned.actual) {
    problems.push(
      `差额无法解释：total − 逐人合计 = ${money(totalC - assignedActualSum)}，`
      + `但无署名归集只有 ${money(unassigned.actual)}`,
    )
  }
  const a0c = {
    id: 'A0c',
    name: '无署名归集金额 ⊆ 总额且差额可解释（总额 − 逐人 = 无署名；归集 = 独立 SQL 的无名组）',
    expect: `Σ per_worker = ${money(totalC)}；总额 − 逐人 = 无署名 ${money(unassigned.expect)}`,
    actual: problems.length === 0
      ? `勾稽成立：逐人合计 ${money(assignedActualSum)} + 无署名 ${money(unassigned.actual)} = ${money(totalC)}`
      : `${problems.length} 项不成立：${problems.join('；')}`,
    pass: problems.length === 0,
    expectSource:
      '期望 = 独立 SQL 的无署名组金额（worker_name 无文本）+ 接口 total 的**恒等式**；'
      + '服务端下发的归集文案只作证据，**不作为期望键**。',
    evidence: [
      `接口 Σ per_worker: ${money(apiSum)} / total: ${money(totalC)}（两者必须相等）`,
      `逐人合计（真实工人，接口侧）: ${money(assignedActualSum)}`,
      `无署名归集: 独立 SQL ${money(unassigned.expect)} / 接口 ${money(unassigned.actual)}`
        + `（服务端文案「${unassigned.label ?? '（无该行）'}」；文案变了不影响本判据）`,
      `不属于任何真实工人的残余行: ${JSON.stringify(residual.map((r) => r?.worker_name ?? null))}`,
      `逐人差异: ${JSON.stringify(diffs)}`,
    ],
  }
  return [a0b, a0c]
}
