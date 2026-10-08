// 假绿自查补强：① 平台上不存在 id ⇒ 404（自证平台确有条目）；② 超管端点带合法数字 id ⇒ 权限闸是否生效
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log } from '../../config-writeface-sweep/harness/lib.mjs'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const tok = {}
for (const [k, p] of Object.entries({ A: '13870217889', B: '13797101248', P: '13456800919' })) tok[k] = (await loginApi(p)).token
const recs = []; const rec = (o) => { recs.push(o); log(`${o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'} [${o.id}] ${o.name} — ${o.detail}`) }
const cut = (s, n = 260) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)
for (const p of ['/api/super-admin/registrations/999999999999', '/api/super-admin/registrations/1']) {
  const a = await api('GET', p, { token: tok.A }), b = await api('GET', p, { token: tok.B }), pp = await api('GET', p, { token: tok.P })
  const ok = a.status === 403 && b.status === 403 && [404].includes(pp.status)
  rec({ id: 'ROLE-plat-numeric' + p.slice(-12), name: '角色越权·超管端点（合法数字 id）', verdict: ok ? 'pass' : 'fail',
    detail: ok ? `商家 admin 被权限闸拦住（A=${a.status} B=${b.status}），超管正对照到业务层 404（id 不存在）` : `A=${a.status} B=${b.status} P=${pp.status} —— 需归因（若商家得到 404 而非 403 ⇒ 权限闸未生效，超管端点暴露给商家 token）`,
    evidence: [`A → ${a.status} ${cut(a.text, 180)}`, `B → ${b.status} ${cut(b.text, 180)}`, `P → ${pp.status} ${cut(pp.text, 180)}`] })
}
writeFileSync(OUT + 'sweep4-probe.json', JSON.stringify(recs, null, 1))
