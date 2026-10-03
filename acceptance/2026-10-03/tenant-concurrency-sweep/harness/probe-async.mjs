// 判据组 A：@Async / 线程边界（admin-api 唯一的异步面 = AuditLogService.recordLogAsync）
// 关键：@Async 线程没有 TenantContext（ThreadLocal 不跨线程）；MyBatis-Plus 的
// TenantLineInnerInterceptor 在 tenantId==null 时**抛异常**（守门人能红）。
// 判据：① 异步审计不得静默丢行；② 并发下不得把行写错租户。
import { api, loginApi, Recorder, psql, log, OUT } from './lib.mjs'
import { A, B } from './resources.mjs'
import { readFileSync, writeFileSync, statSync, openSync, readSync, closeSync } from 'node:fs'
import { join } from 'node:path'

const args = Object.fromEntries(process.argv.slice(2).map((x) => { const [k, v] = x.replace(/^--/, '').split('='); return [k, v ?? true] }))
const FLIP = !!args.flip
const R = new Recorder(`probe-async${FLIP ? '-flip' : ''}.json`)
const ok = (bad) => (FLIP ? bad > 0 : bad === 0)
const LOG = process.env.API_LOG || '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/out/main-live-1233b8a42-api.log'

const a = await loginApi(A.phone), b = await loginApi(B.phone)
const rowCount = (t) => psql(`select count(*)::int as c from audit_logs where tenant_id=${t} and action='update' and resource_type='briefing_config'`)[0].c

// 前置：保持 enabled=false（不得因本探针触发任何简报生成 / LLM）
const curA = await api('GET', '/api/admin/briefing/config', { token: a.token })
const curB = await api('GET', '/api/admin/briefing/config', { token: b.token })
log(`前置读数 briefing/config：A(20)=${curA.text.slice(0, 160)}；B(21)=${curB.text.slice(0, 160)}`)

const before = { 20: rowCount(20), 21: rowCount(21) }
const logSizeBefore = (() => { try { return statSync(LOG).size } catch { return -1 } })()

// 并发触发异步审计落库（三个租户各 4 次，同一 worker 线程池）
const reqs = []
for (let i = 0; i < 12; i++) {
  const t = i % 2 === 0 ? 20 : 21
  const tok = t === 20 ? a.token : b.token
  const body = { enabled: false, generateTime: i % 2 === 0 ? '09:00' : '08:30' }
  reqs.push({ i, t, p: api('PUT', '/api/admin/briefing/config', { token: tok, body }) })
}
const out = await Promise.all(reqs.map((x) => x.p))
const statuses = out.map((r) => r.status)
const okStatus = statuses.filter((s) => s === 200).length
const ev = [{ case: 'A0-触发', statuses, head: out[0].text.slice(0, 180) }]

// 等异步落库完成（轮询 DB，不 sleep 猜测；最多 8s）
let after = { 20: rowCount(20), 21: rowCount(21) }
for (let k = 0; k < 16; k++) {
  if (after[20] + after[21] > before[20] + before[21]) break
  await new Promise((r) => setTimeout(r, 500))
  after = { 20: rowCount(20), 21: rowCount(21) }
}
const delta = { 20: after[20] - before[20], 21: after[21] - before[21] }
ev.push({ case: 'A1-审计行增量', before, after, delta, expected: 6 })

// 读服务日志里本窗口的新增行（找异步落库失败的根因读数）
let newLog = ''
try {
  if (logSizeBefore >= 0) {
    const size = statSync(LOG).size
    const len = Math.min(size - logSizeBefore, 512 * 1024)
    if (len > 0) {
      const fd = openSync(LOG, 'r'); const buf = Buffer.alloc(len)
      readSync(fd, buf, 0, len, size - len); closeSync(fd)
      newLog = buf.toString('utf8')
    }
  }
} catch (e) { newLog = `LOGREAD_ERR:${e.message}` }
const interesting = newLog.split('\n').filter((l) => /异步记录审计日志失败|Tenant context not initialized|briefing_config|更新简报配置/.test(l))
writeFileSync(join(OUT, `probe-async${FLIP ? '-flip' : ''}-log-slice.txt`), interesting.join('\n'))
ev.push({ case: 'A2-日志窗口', lines: interesting.slice(0, 12) })

// ── 判据 A1：12 次 200 的请求平台，异步审计行必须 ≥ 1（不得静默丢行）──
const totalDelta = delta[20] + delta[21]
const dropped = totalDelta === 0
const det1 = `12 次 PUT briefing/config 全 ${okStatus}/12 → 200；audit_logs(action=update,resource_type=briefing_config) 增量 A=${delta[20]} B=${delta[21]}（合计 ${totalDelta}）`
writeFileSync(join(OUT, `probe-async${FLIP ? '-flip' : ''}-counts.json`), JSON.stringify({ before, after, delta, statuses, logTail: interesting.slice(0, 20) }, null, 2))
ok(dropped ? 1 : 0)
  ? R.pass('A1-异步审计不丢行', '@Async 审计落库：请求 200 后表里必须有行', det1, ev)
  : R.fail('A1-异步审计不丢行', '@Async 审计落库：请求 200 后表里必须有行', `🔴 ${det1} ⇒ 异步落库静默丢行`, ev)

// ── 判据 A2：并发下不得把行写到别的租户（串号）──
const misattr = []
if (totalDelta > 0) {
  const rows = psql(`select tenant_id, resource_id, created_at from audit_logs where action='update' and resource_type='briefing_config' and created_at > now() - interval '10 minutes' order by created_at desc limit 30`)
  for (const r of rows) {
    // resource_id = String.valueOf(tenantId)（BriefingController 的调用点）；自述与列值必须一致且 ∈ {20,21}
    if (!['20', '21'].includes(String(r.resource_id)) || Number(r.tenant_id) !== Number(r.resource_id)) misattr.push(r)
  }
  ev.push({ case: 'A2-近 10 分钟行', rows: rows.slice(0, 10), misattr })
}
ok(misattr.length)
  ? R.pass('A2-异步审计不串号', '@Async 并发下审计行的 tenant_id 与调用租户一致', `近 10 分钟 briefing_config 审计行 ${misattr.length ? misattr.length + ' 条错租户' : '无错租户（resource_id 自述与 tenant_id 列一致）'}`, ev.slice(-1))
  : R.fail('A2-异步审计不串号', '@Async 并发下审计行的 tenant_id 与调用租户一致', `🔴 ${misattr.length} 条错租户：${JSON.stringify(misattr.slice(0, 3))}`, ev.slice(-1))

// ── 线程边界表（代码级读数，落盘供报告引用）──
writeFileSync(join(OUT, `thread-boundary${FLIP ? '-flip' : ''}.json`), JSON.stringify({
  setPoints: [
    { file: 'security/JwtAuthenticationFilter.java:112', what: 'TenantContext.setTenantId(claims.tenantId)（仅当 tenantId!=null 且 !=-1）' },
    { file: 'security/ServiceTokenFilter.java:104', what: 'TenantContext.setTenantId(X-Tenant-Id)（合法 service token ∧ SecurityContext 空）' },
    { file: 'service/AuthService.java:196,449,524,739', what: '登录链路内显式 setTenantId' },
    { file: 'controller/WorkerAuthController.java:60-71,92-101', what: '保存 previous 后 setTenantId，finally 还原/清理' },
    { file: 'worker/WorkerSessionService.java:318-331', what: '同上（保存 previous → set → finally 还原/清理）' },
    { file: 'service/DailyBriefingService.java:345-353,1424-1442', what: '调度线程显式 setTenantId（previous 还原/清理）' },
    { file: 'service/RegistrationService.java:414-440', what: '入驻链路显式 setTenantId（previous 还原/清理）' },
    { file: 'service/AutoBatchDueScanService.java:110-166', what: '调度线程显式 setTenantId（previous 还原/清理）' },
  ],
  clearPoints: [
    { file: 'security/JwtAuthenticationFilter.java:165-168', what: 'doFilterInternal finally → TenantContext.clear()（无条件）' },
    { file: 'security/JwtAuthenticationFilter.java:171-178', what: 'doFilterNestedErrorDispatch finally → clear()（ERROR 派发）' },
    { file: 'security/ServiceTokenFilter.java:174-181', what: 'filterChain 之后 finally → clear()（仅当本过滤器设置过）' },
    { file: 'security/WorkerSessionFilter.java:76,85,129', what: '工人会话路径 clear()' },
  ],
  readPoints: [{ file: 'config/MybatisPlusConfig.java:69-87', what: 'getTenantId()：tenantId==null ⇒ 若主体是 super_admin 跳过过滤，否则抛 "Tenant context not initialized"' }],
  threadBoundaries: [
    { boundary: 'Tomcat 请求线程池 (server.tomcat.threads.max=200, accept-count=100)', contextPropagation: '无（每请求 finally clear ⇒ 复用安全）', evidence: 'probe.mjs P1/P3/P5 并发读数 + application.yml' },
    { boundary: '@Async SessionDistillListener.onSessionEnded (listener/SessionDistillListener.java:27)', contextPropagation: '不传播（@EnableAsync 无 AsyncConfigurer/TaskDecorator；Spring Boot 默认 ApplicationTaskExecutor）', note: '回调内 distillSession(event.tenantId(), …) 显式传参，不依赖 TenantContext；需真实结束会话才能触发 ⇒ 本轮未行使' },
    { boundary: '@Async AuditLogService.recordLogAsync (service/AuditLogService.java:72)', contextPropagation: '不传播', note: '异步线程内 auditLogMapper.insert(tenantId=显式参数)；TenantLineInnerInterceptor 会为 audit_logs 追加 tenant_id = TenantContext.getTenantId() ⇒ 异步线程为 null ⇒ 抛 "Tenant context not initialized"（被 catch 吞掉，仅 ERROR 日志）', evidence: 'probe-async.mjs A1/A2 读数 + 日志窗口切片' },
    { boundary: 'Servlet ERROR 派发', contextPropagation: '同一请求线程（doFilterNestedErrorDispatch 已补 clear）', evidence: 'security/JwtAuthenticationFilter.java:171-178' },
  ],
}, null, 2))

const sum = R.summary()
log(`=== probe-async 读数（flip=${FLIP}）：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, `probe-async${FLIP ? '-flip' : ''}-summary.json`), JSON.stringify({ flip: FLIP, ...sum }, null, 2))
