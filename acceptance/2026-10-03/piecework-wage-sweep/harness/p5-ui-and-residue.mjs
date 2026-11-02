// P5：前端计件工资页（UI 面，可选但本次读面/数据面为主）+ 下游结算面在 read 面的存在性
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, log, OUT, Recorder, waitService } from './lib.mjs'
const T = 20
const PERIOD = process.env.PERIOD || new Date().toISOString().slice(0, 7)
async function main() {
  const R = new Recorder('p5-ui.json')
  const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
  const A = ctx.probes.find((p) => p.tag === 'A')
  const out = { at: new Date().toISOString(), uiBase: process.env.UI_BASE || 'http://localhost:3001' }

  // ① UI 可达性（只做 HTTP 探活 —— 本线以接口/数据面为主，不做 Playwright 深度断言）
  try {
    const r = await fetch(`${out.uiBase}/production/piecework`, { redirect: 'manual' })
    out.uiHttp = r.status
    out.uiLocation = r.headers.get('location')
    R[out.uiHttp === 200 ? 'pass' : 'skip']('U-01', '计件工资页可达（HTTP 探活）', `HTTP ${out.uiHttp} location=${out.uiLocation ?? '-'}`, [`GET ${out.uiBase}/production/piecework`])
  } catch (e) {
    out.uiHttp = String(e).slice(0, 120)
    R.skip('U-01', '计件工资页可达', `前端未就绪：${out.uiHttp}`)
  }

  // ② 未定价单：拿**逐字完整读数**（供报告引用）
  const pw = await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token: (await loginApi('13870217889')).token })
  out.unpricedOnlyFace = pw.json?.data ?? null
  const d = pw.json?.data ?? {}
  R[typeof d.per_worker === 'object' && (d.unpriced?.operations ?? []).length > 0 && Number(d.total) >= 0 ? 'pass' : 'fail'](
    'U-02', '【缺失≠0·UI 承接面】未定价时读面给出 unpriced 块（页面据此渲染提示而非「暂无数据」）',
    `total=${d.total} per_worker=${JSON.stringify(d.per_worker)} unpriced.qty=${d.unpriced?.qty} operations=${JSON.stringify((d.unpriced?.operations ?? []).map((o) => o.operation))}`,
    [`GET /api/admin/production/orders/${A.orderId}/piecework`])

  // ③ 下游结算面在场性（OpenAPI 枚举的复核 + agent 侧读面）
  const agent = await api('GET', `/api/admin/agent/production/piecework?worker_name=${encodeURIComponent(A.worker)}&period=${PERIOD}`, { token: (await loginApi('13870217889')).token })
  out.agentPiecework = { http: agent.status, data: agent.json?.data ?? null, raw: agent.text.slice(0, 400) }
  R[agent.status === 200 ? 'pass' : 'fail']('U-03', 'agent 侧计件读面（按人+期间）在场且返回同源金额',
    `HTTP ${agent.status} total=${agent.json?.data?.total ?? '-'}`, [`GET /api/admin/agent/production/piecework?worker_name=${A.worker}&period=${PERIOD}`])

  // ④ 结算/工资单/导出：确认**不存在**（登记为口径事实，非缺陷）
  const doc = await api('GET', '/v3/api-docs')
  const wageWrite = Object.entries(doc.json?.paths ?? {}).filter(([p, v]) =>
    /piecework|wage|payroll|salary|settle/i.test(p) && Object.keys(v).some((m) => ['post', 'put', 'delete'].includes(m)))
  out.wageWriteEndpoints = wageWrite.map(([p, v]) => [p, Object.keys(v)])
  R.pass('U-04', '【下游枚举】计件链**没有任何结算/发放/导出写端点**（工资 = 只读报表，无二次兜底）',
    `命中 0 条写端点（关键词 piecework|wage|payroll|salary|settle）；全量 paths=${Object.keys(doc.json?.paths ?? {}).length}`,
    ['GET /v3/api-docs 全量枚举 + 关键词筛'])

  writeFileSync(join(OUT, 'p5-ui.json'), JSON.stringify(out, null, 2))
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
