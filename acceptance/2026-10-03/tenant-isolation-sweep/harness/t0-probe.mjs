// 探针：登录注入的主体 + 摸清列表返回体形态（零写入）
// 主体全部由 env 注入（issue #6937；注入口 = acceptance/2026-10-03/lib/subjects.mjs）
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log, Recorder, sha, psql } from '../../config-writeface-sweep/harness/lib.mjs'
import { PH, SMS_CODE, SUBJECTS_LINE } from '../../lib/subjects.mjs'
const OUT = process.env.OUT_DIR ? process.env.OUT_DIR.replace(/\/?$/, '/') : fileURLToPath(new URL('../out/', import.meta.url))
const rec = new Recorder('t0-probe.json')
const PHONES = Object.fromEntries(Object.entries({ A: PH.A, B: PH.B, P: PH.P }).filter(([, p]) => p))
log(`[env] ${SUBJECTS_LINE}（未注入的主体不登录）`)
const out = {}
for (const [k, phone] of Object.entries(PHONES)) {
  try { const r = await loginApi(phone, SMS_CODE); out[k] = { phone, token: r.token, raw: r.raw }
    log(`login ${k} ${phone} OK token=${r.token.slice(0,16)}… raw=${JSON.stringify(r.raw).slice(0,300)}`)
  } catch (e) { out[k] = { phone, error: String(e).slice(0,300) }; log(`login ${k} ${phone} FAIL ${String(e).slice(0,200)}`) }
}
const T = out.A?.token
const LISTS = ['/api/admin/products?page=1&size=3','/api/admin/customers?page=1&size=3','/api/admin/users?page=1&size=3',
 '/api/admin/customer-tags','/api/admin/categories','/api/admin/production/routings','/api/admin/production/route-rules',
 '/api/admin/production/processing-fee-combinations','/api/admin/processing-items?query=','/api/admin/processing-categories',
 '/api/admin/orders?page=1&size=3','/api/admin/processing-orders','/api/admin/inbound-orders','/api/admin/agent-sessions?page=1&size=3',
 '/api/admin/notification-templates?page=1&size=3','/api/admin/notification-rules?page=1&size=3','/api/admin/knowledge/cards?page=1&size=3',
 '/api/admin/roles?page=1&size=3','/api/admin/after-sales?page=1&size=3','/api/admin/shipments','/api/admin/workers?page=1&size=3',
 '/api/admin/production/operations-catalog','/api/admin/production/operation-positions','/api/admin/stock-ledger','/api/admin/permissions',
 '/api/admin/production/remnants','/api/admin/processing-order-sets','/api/admin/finance/transactions?page=1&size=3','/api/admin/menus','/api/admin/user/info']
for (const p of LISTS) {
  const r = await api('GET', p, { token: T })
  const shape = r.json?.data == null ? `json=${JSON.stringify(r.json)?.slice(0,120)}`
    : Array.isArray(r.json.data) ? `data[${r.json.data.length}]`
    : r.json.data.records ? `records[${r.json.data.records.length}] total=${r.json.data.total}`
    : `data.keys=${Object.keys(r.json.data).join(',')}`
  log(`LIST ${r.status} ${p} → ${shape}`)
  out['list:' + p] = { status: r.status, shape, sample: JSON.stringify(r.json).slice(0, 900) }
}
writeFileSync(OUT + 't0-subjects.json', JSON.stringify(out, null, 1))
log(`sha=${sha()} tenants=${JSON.stringify(psql('select id, name from tenants order by id'))}`)
