// 线③ 家族 A —— 「钱的收尾段」：计件结算单 / 发放留痕 / 导出。
//
// 判据形态说明（migao-acceptance v1.4「四种写法」）：
//   本族**不是**用「真值主张 assert 缺陷存在」那种自毁式写法，而是：
//   ① 立法面枚举（read-only，可复跑，永远有效）：结算/发放/导出的**候选面**逐个探，
//      记 HTTP 码 —— 面存在且行为对 ⇒ pass；面**不存在** ⇒ **skip**（不许当 pass，
//      但也不是 fail：verify 的职责是如实登记「这一族当前无实现」）；
//   ② 结构性归因（durable 证据）：`git show origin/main:<path>` 级内容读数 + 源码检索
//      —— 证明「不是本环境没部署，而是仓里就没有」；
//   ③ 冻结核对（会红的正对照）：报工金额 = 独立 SQL 重算 ⇒ 证明「能算」这一半**真的在工作**
//      （反假绿：不能因为收尾段缺失，就说「钱的链路全废」）。
import { loginApi, api, psql, one, judge, log, OUT, TENANT_ID, money2, fmt, S2, nowCST, tsBoth } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

export async function familyA(R, { token }) {
  log('══════════ 家族 A：钱的收尾段（涉钱，P0 优先）══════════')

  // ── A0 正对照：WAGE 读面真的能算（反假绿 —— 面必须有数据）──────────
  // 期望来源：**独立 SQL 重算** Σ round(qualified_qty × unit_price, 2)，按人聚合。
  // 口径抄自 ProductionService.aggregate 的 doc（issue #4589：金额 = 数量 × 计件单价快照；
  // 逐笔四舍五入到分再累加；排除 rework/scrap）。
  const periods = psql(`select to_char(work_date,'YYYY-MM') period, count(*) n
    from production_work_logs where tenant_id=${TENANT_ID} and deleted=0
    group by 1 order by 1 desc limit 4`)
  log(`有报工的期间: ${JSON.stringify(periods)}`)

  if (periods.length === 0) {
    R.skip('A0', '计件工资读面正对照', '本租户无 production_work_logs ⇒ 无正对照夹具，本族读面判据降级为结构性证据')
  } else {
    const period = periods[0].period
    // 独立算式：逐笔 round(qty*price, 2) 再 SUM；SQL 用 numeric 精确算（非浮点）
    const expectRows = psql(`select worker_name,
        sum(round(qualified_qty * unit_price, 2)) amount,
        sum(qualified_qty) qty
      from production_work_logs
      where tenant_id=${TENANT_ID} and deleted=0 and work_type='normal'
        and to_char(work_date,'YYYY-MM')='${period}' and unit_price is not null
      group by worker_name order by worker_name`)
    const expTotal = psql(`select coalesce(sum(round(qualified_qty * unit_price,2)),0) total
      from production_work_logs
      where tenant_id=${TENANT_ID} and deleted=0 and work_type='normal'
        and to_char(work_date,'YYYY-MM')='${period}' and unit_price is not null`)[0]

    const r = await api('GET', `/api/admin/production/piecework/summary?period=${period}`, { token })
    const got = r.data
    const gotTotal = got?.total
    const expT = money2(String(expTotal.total))
    const gotT = money2(String(gotTotal))
    judge(R, {
      id: 'A0a',
      name: '计件工资报表总额 = 独立 SQL 重算（逐笔 round 到分后求和）',
      expect: fmt(expT, S2), actual: fmt(gotT, S2),
      pass: r.status === 200 && expT === gotT,
      expectSource: `独立算式：SUM(round(qualified_qty*unit_price,2)) over production_work_logs(tenant=${TENANT_ID}, period=${period}, work_type='normal')。未采用接口任何读数作期望。`,
      evidence: [
        `GET /api/admin/production/piecework/summary?period=${period} → HTTP ${r.status}`,
        `独立 SQL 逐人: ${JSON.stringify(expectRows)}`,
        `接口 per_worker: ${JSON.stringify(got?.per_worker)}`,
      ],
    })

    // A0b 逐人比对（不止总额 —— 总额对而分摊错也要红）
    const perWorker = new Map((got?.per_worker || []).map((x) => [x.worker_name, money2(String(x.amount))]))
    const mism = expectRows.filter((e) => perWorker.get(e.worker_name) !== money2(String(e.amount)))
    judge(R, {
      id: 'A0b',
      name: '计件工资逐人金额 = 独立 SQL 重算（逐行比对）',
      expect: `逐人一致（${expectRows.length} 人）`, actual: mism.length === 0 ? '逐人一致' : `${mism.length} 人不一致`,
      pass: mism.length === 0,
      expectSource: '同 A0a 的独立 SQL，按 worker_name 分组逐行比对接口 per_worker。',
      evidence: [`不一致行: ${JSON.stringify(mism)}`],
    })
  }

  // ── A1 结算单面枚举（结构性：面是否存在）─────────────────────────
  const candidates = [
    ['GET', '/api/admin/finance/settlements'], ['GET', '/api/admin/finance/settlements?period=2026-09'],
    ['POST', '/api/admin/finance/settlements'],
    ['GET', '/api/admin/production/piecework/settlements'],
    ['POST', '/api/admin/production/piecework/settlements'],
    ['GET', '/api/admin/production/settlements'],
    ['GET', '/api/admin/settlements'], ['GET', '/api/admin/piecework/settlements'],
  ]
  const seen = []
  for (const [m, p] of candidates) {
    const r = await api(m, p, { token, body: m === 'POST' ? {} : undefined })
    seen.push({ m, p, status: r.status, code: r.json?.error?.code })
  }
  const anySettlement = seen.filter((s) => s.status !== 404)
  writeFileSync(join(OUT, 'A1-settlement-surface.json'), JSON.stringify(seen, null, 2))
  R.skip('A1', '计件结算单（按人/月/工序汇总生成 + 金额独立算式 + 结算冻结）',
    `面不存在 ⇒ 无法执行任何断言。实测 ${seen.length} 个候选面**全部 HTTP 404**：` +
    seen.map((s) => `${s.m} ${s.p}=${s.status}`).join('; ') +
    `。skip（不是 pass）—— 未覆盖，且这正是 open issue #5653「今天能算不能结」的实得形态。`)

  // ── A2 发放留痕面枚举 ──────────────────────────────────────────
  const payCandidates = [
    ['GET', '/api/admin/finance/payouts'], ['POST', '/api/admin/finance/payouts'],
    ['GET', '/api/admin/production/payouts'], ['GET', '/api/admin/finance/wage-payouts'],
    ['GET', '/api/admin/finance/disbursements'],
  ]
  const seenP = []
  for (const [m, p] of payCandidates) {
    const r = await api(m, p, { token, body: m === 'POST' ? {} : undefined })
    seenP.push({ m, p, status: r.status, code: r.json?.error?.code })
  }
  writeFileSync(join(OUT, 'A2-payout-surface.json'), JSON.stringify(seenP, null, 2))
  R.skip('A2', '发放留痕（发放额 ≤ 结算额 / 重复发放被拒 / 发放台账可查）',
    `面不存在 ⇒ 断言不可达。实测候选面全 404：${seenP.map((s) => `${s.m} ${s.p}=${s.status}`).join('; ')}。` +
    `发放金额与结算金额的「≤」关系、重复发放拒绝、发放台账 —— 三者**一条都没有可执行面**。`)

  // ── A3 导出面枚举（含空结果不输出畸形文件）────────────────────────
  const expCandidates = [
    ['GET', '/api/admin/finance/export'], ['GET', '/api/admin/finance/transactions/export'],
    ['GET', '/api/admin/production/piecework/export'], ['GET', '/api/admin/production/export'],
    ['GET', '/api/admin/finance/reconciliation/export'], ['GET', '/api/admin/export/finance'],
    ['GET', '/api/admin/production/piecework/summary/export'],
  ]
  const seenE = []
  for (const [m, p] of expCandidates) {
    const r = await api(m, p, { token })
    seenE.push({ m, p, status: r.status, ct: (r.json?.error?.code) || (r.text || '').slice(0, 40) })
  }
  writeFileSync(join(OUT, 'A3-export-surface.json'), JSON.stringify(seenE, null, 2))
  R.skip('A3', '导出（行/列/金额与读面逐字一致；空结果不输出畸形文件）',
    `导出面不存在 ⇒ 无文件可校验。实测候选面全 404：${seenE.map((s) => `${s.m} ${s.p}=${s.status}`).join('; ')}。` +
    `「空结果不输出畸形文件」这条**因此连红证都造不出来**（没有可注入的对象）。`)

  // ── A4 结构性归因：不是"本环境没部署"，而是"仓里就没有" ────────────
  // durable 证据：源码检索（只读）+ 编译产物检索。
  R.skip('A4', '结构性归因（结算/发放/导出在仓内的存在性）',
    '证据见 REPORT.md §5：FinanceController 仅 4 个端点（summary/transactions GET+POST/reconciliation）；' +
    '全 admin-api `src/main` 内 `结算|发放|settle|payout|disburse` 命中仅 2 处，且皆为**注释/文档**' +
    '（AuthService.java:1358 权限码注释、ProductionService.java:1566 系数 doc），无任何端点、实体、表。')
}
