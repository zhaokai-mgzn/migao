// 假绿自查补强：① 平台上不存在 id ⇒ 404（自证平台确有条目）；② 超管端点带合法数字 id ⇒ 权限闸是否生效
// 主体由 env 注入（issue #6937）；本案要求 A/B/P 三方齐（缺一即具名 skip —— 少一方就没有对照）。
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log } from '../../config-writeface-sweep/harness/lib.mjs'
import { PH, SMS_CODE, SUBJECTS_LINE } from '../../lib/subjects.mjs'
const OUT = process.env.OUT_DIR ? process.env.OUT_DIR.replace(/\/?$/, '/') : fileURLToPath(new URL('../out/', import.meta.url))
const tok = {}
for (const [k, p] of Object.entries({ A: PH.A, B: PH.B, P: PH.P })) { if (p) tok[k] = (await loginApi(p, SMS_CODE)).token }
log(`[env] ${SUBJECTS_LINE}；已登录=${Object.keys(tok).join('/') || '无'}`)
const recs = []; const rec = (o) => { recs.push(o); log(`${o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'} [${o.id}] ${o.name} — ${o.detail}`) }
const cut = (s, n = 260) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)
for (const p of ['/api/super-admin/registrations/999999999999', '/api/super-admin/registrations/1']) {
  const id = 'ROLE-plat-numeric' + p.slice(-12)
  if (!tok.P || !tok.B) { rec({ id, name: '角色越权·超管端点（合法数字 id）', verdict: 'skip', detail: `需 A/B/P 三方齐（当前已注入=${Object.keys(tok).join('/') || '无'}）⇒ 具名跳过，不折算 pass`, evidence: [] }); continue }
  const a = await api('GET', p, { token: tok.A }), b = await api('GET', p, { token: tok.B }), pp = await api('GET', p, { token: tok.P })
  const ok = a.status === 403 && b.status === 403 && [404].includes(pp.status)
  rec({ id, name: '角色越权·超管端点（合法数字 id）', verdict: ok ? 'pass' : 'fail',
    detail: ok ? `商家 admin 被权限闸拦住（A=${a.status} B=${b.status}），超管正对照到业务层 404（id 不存在）` : `A=${a.status} B=${b.status} P=${pp.status} —— 需归因（若商家得到 404 而非 403 ⇒ 权限闸未生效，超管端点暴露给商家 token）`,
    evidence: [`A → ${a.status} ${cut(a.text, 180)}`, `B → ${b.status} ${cut(b.text, 180)}`, `P → ${pp.status} ${cut(pp.text, 180)}`] })
}
writeFileSync(OUT + 'sweep4-probe.json', JSON.stringify(recs, null, 1))
