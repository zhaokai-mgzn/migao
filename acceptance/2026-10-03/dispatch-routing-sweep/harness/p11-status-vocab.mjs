// P11：**真库收口** —— 「停用工序」写面在真实后端上的受理词表（给 P2/#6105 补真对象读数）
//  ① UI 现在发的值 `disabled` ⇒ 必须 200 且库内真的变 disabled
//  ② 旧错值 `inactive` ⇒ 必须 422（这就是 F1 的病根）
//  ③ 还原 `active`
import { api, loginApi, psql, one, log, waitService, Recorder } from './lib.mjs'
const T = Number(process.env.TENANT_ID || 20)
const R = new Recorder('p11-status-vocab.json')
await waitService()
const { token } = await loginApi(process.env.ADMIN_PHONE || '13870217889')
const op = one(`select id, name, status from production_operations where tenant_id=${T} and name='质检' and coalesce(deleted,0)=0`)
const st = async () => one(`select status from production_operations where id='${op.id}'`)?.status
const before = await st()
const ok = await api('PUT', `/api/admin/production/operations/${op.id}`, { token, body: { status: 'disabled' } })
const afterOk = await st()
const bad = await api('PUT', `/api/admin/production/operations/${op.id}`, { token, body: { status: 'inactive' } })
const afterBad = await st()
const restore = await api('PUT', `/api/admin/production/operations/${op.id}`, { token, body: { status: before } })
const afterRestore = await st()
ok.status === 200 && afterOk === 'disabled'
  ? R.pass('P11-01', "UI 现在发的 `status:'disabled'` 在真库上被受理且状态真的翻转（P2/#6105 的对象侧）",
      `PUT {status:'disabled'} → HTTP ${ok.status}；库内 ${before} → ${afterOk}`, [`PUT /api/admin/production/operations/${op.id} {status:'disabled'}`])
  : R.fail('P11-01', 'disabled 受理', `HTTP ${ok.status}；库内 ${before} → ${afterOk}`)
bad.status === 422
  ? R.pass('P11-02', "旧错值 `status:'inactive'` 在真库上仍被拒（= F1 病根，修的是 UI 侧）",
      `PUT {status:'inactive'} → HTTP ${bad.status}：${(bad.json?.error?.message || bad.text).slice(0, 80)}；库内仍 ${afterBad}`)
  : R.fail('P11-02', 'inactive 应被拒', `HTTP ${bad.status}；库内 ${afterBad}`)
restore.status === 200 && afterRestore === before
  ? R.pass('P11-03', '还原到原状态', `PUT {status:'${before}'} → HTTP ${restore.status}；库内 ${afterRestore}`)
  : R.fail('P11-03', '还原', `HTTP ${restore.status}；库内 ${afterRestore}（期望 ${before}）`)
log(`summary=${JSON.stringify(R.summary())}；质检 status ${before} → disabled → (inactive 被拒) → ${afterRestore}`)
