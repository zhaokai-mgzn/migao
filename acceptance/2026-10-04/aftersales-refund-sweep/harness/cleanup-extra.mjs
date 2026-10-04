// cleanup-extra —— 本线**新增探针域**的清理（底座 lib.mjs 的 cleanupProbe 未覆盖「探针分类」）
// 纪律：只删**本线注册表 / 命名前缀**命中的行；绝不动非探针对象。写 SQL 必带 `-- probe-ok`。
import { psql, guardedWrite, log, nowCST, PROBE_PREFIX, TENANT_ID, outPath, writeFileSync } from './lib.mjs'
import { readFileSync, existsSync } from 'node:fs'

const REG = existsSync(outPath('probe-registry.json')) ? JSON.parse(readFileSync(outPath('probe-registry.json'), 'utf8')) : {}
const ids = (REG.categories || []).filter((x) => /^[0-9a-f]{32}$/.test(String(x)))
const errors = []
const w = (sql, label) => { try { guardedWrite(`-- probe-ok\n${sql}`); return true } catch (e) { errors.push(`${label}: ${String(e.message).split('\n').find((l) => l.startsWith('ERROR')) || e.message.slice(0, 120)}`); return false } }
let deletedByName = 0, deletedById = 0
if (ids.length) { w(`delete from categories where id in (${ids.map((x) => `'${x}'`).join(',')});`, 'categories-by-registry'); deletedById = ids.length }
const pre = psql(`select id, name from categories where tenant_id=${TENANT_ID} and name like '${PROBE_PREFIX}%'`)
if (pre.length) { w(`delete from categories where tenant_id=${TENANT_ID} and name like '${PROBE_PREFIX}%';`, 'categories-by-prefix'); deletedByName = pre.length }
const after = psql(`select id, name from categories where tenant_id=${TENANT_ID} and (name like '${PROBE_PREFIX}%' ${ids.length ? `or id in (${ids.map((x) => `'${x}'`).join(',')})` : ''})`)
writeFileSync(outPath('Z-cleanup-extra.json'), JSON.stringify({ at: nowCST(), tenant: TENANT_ID, registryCategoryIds: ids, preByPrefix: pre, deletedByName, deletedById, remaining: after, errors }, null, 2))
log(`cleanup-extra：探针分类 前缀命中 ${pre.length} / 注册表 ${ids.length} ⇒ 删除后剩余 ${after.length}；errors=${errors.length}`)
if (after.length) { log(`⚠️ 探针分类仍残留：${JSON.stringify(after)}`); process.exit(1) }
