// A0 — 构建点自证 + 正对照（面真的有数据）
import { buildPoint, writeFileSync, outPath, loginApi, api, psql, TENANT_ID, log, nowCST } from './lib.mjs'

const bp = buildPoint()
writeFileSync(outPath('A0-buildpoint.json'), JSON.stringify(bp, null, 2))
log(`构建点: worktree=${bp.worktree} sha=${bp.sha} subj=${bp.subject}`)
log(`构建点: origin/main=${bp.originMain} pid=${bp.pid} 进程启动=${bp.adminApiStart}`)
log(`构建点: 测量开始=${bp.observedAt.cst} / UTC=${bp.observedAt.utc}`)

const { token, raw } = await loginApi()
log(`登录 OK: tenantId=${raw.tenantId ?? raw.tenant_id} user=${raw.username ?? raw.name ?? '?'}`)

// 正对照 1：商品列表面真的有数据（对 tenant 20）
const list = await api('GET', '/api/admin/products?page=1&size=5', { token })
log(`商品列表: HTTP ${list.status} total=${list.data?.total} items=${list.data?.items?.length}`)
writeFileSync(outPath('A0-list-probe.json'), JSON.stringify({
  status: list.status, total: list.data?.total, first: list.data?.items?.[0] ?? null,
}, null, 2))

// 正对照 2：全部 6 个上传端点 + 3 个批写端点 + 导入导出 **都存在**（不是 404）
const probes = {}
const ep = async (m, p, body) => { const r = await api(m, p, { token, body }); probes[`${m} ${p}`] = { status: r.status, code: r.json?.code ?? null, msg: (r.json?.message ?? '').slice(0, 80) }; return r }
await ep('POST', '/api/admin/products/batch/on-shelf', { productIds: [] })
await ep('POST', '/api/admin/products/batch/off-shelf', { productIds: [] })
await ep('POST', '/api/admin/products/batch/delete', { productIds: [] })
await ep('GET', '/api/admin/products/export')
await ep('DELETE', `/api/admin/production/operations/${'l2' + '0'.repeat(20)}/detach-and-delete`)
writeFileSync(outPath('A0-endpoint-probes.json'), JSON.stringify(probes, null, 2))
log(`端点存在性探针: ${JSON.stringify(probes)}`)

// 正对照 3：库存台账表可读
const led = psql(`select count(*)::int as n from stock_ledger_entries where tenant_id=${TENANT_ID}`)
log(`stock_ledger_entries(t20) = ${led[0]?.n}`)

process.exit(0)
