// setup.mjs —— 夹具前置：探针工人（本包自建）+ 登录（商家 JWT / 工人 session）
import { api, loginApi, workerLogin, PROBE_WORKER, TENANT_ID, log, nowCST, buildPoint, cleanupProbe } from './lib.mjs'

/** 建/复用本包探针工人（幂等：已存在则 200/409 都算就绪）。 */
export async function ensureWorker(token) {
  const list = await api('GET', `/api/admin/workers?page=1&size=50&keyword=${encodeURIComponent(PROBE_WORKER.workerNo)}`, { token })
  const found = (list.data?.items || []).some((w) => w.workerNo === PROBE_WORKER.workerNo)
  if (found) return { workerNo: PROBE_WORKER.workerNo, created: false }
  const r = await api('POST', '/api/admin/workers', {
    token,
    body: { workerNo: PROBE_WORKER.workerNo, name: PROBE_WORKER.name, pin: PROBE_WORKER.pin },
  })
  if (!r.json?.success) {
    // 409 = 并发建号/已存在 ⇒ 视为就绪
    if (r.status === 409) return { workerNo: PROBE_WORKER.workerNo, created: false, note: r.text.slice(0, 160) }
    throw new Error(`建探针工人失败 ${r.status}: ${r.text.slice(0, 300)}`)
  }
  return { workerNo: PROBE_WORKER.workerNo, created: true }
}

export async function setup({ clean = false } = {}) {
  const bp = buildPoint()
  if (clean) cleanupProbe()
  const { token, raw } = await loginApi()
  const wi = await ensureWorker(token)
  const session = await workerLogin()
  const ctx = { token, session, worker: wi, tenantId: TENANT_ID, buildPoint: bp, at: nowCST() }
  log(`[setup] 构建点 sha=${bp.sha} subject=${bp.subject}`)
  log(`[setup] 商家 JWT ok (role=${raw.role ?? raw.user?.role}) tenant=${TENANT_ID}；探针工人 ${wi.workerNo} created=${wi.created}`)
  return ctx
}
