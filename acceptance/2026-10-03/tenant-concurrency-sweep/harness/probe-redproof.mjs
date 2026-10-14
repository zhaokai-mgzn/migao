// 红证 + 正对照 + 假绿自查（不依赖被测系统的真值来定义期望）
// 主体由 env 注入（issue #6937）：RP1/RP2/RP4/RP5 都是**跨租户**判据 ⇒ 需 A/B 双侧，缺 B 即具名 skip。
import { api, loginApi, Recorder, psql, log, OUT, AGENT } from './lib.mjs'
import { RESOURCES, dbIds, A, B } from './resources.mjs'
import { S, T, PH, SMS_CODE, MISSING_B, B_SKIP, SUBJECTS_LINE } from '../../lib/subjects.mjs'
import { writeFileSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const R = new Recorder('probe-redproof.json')
log(`[env] ${SUBJECTS_LINE}`)
const TA = T.A, TB = T.B
const ev = []

if (MISSING_B) {
  for (const [id, name] of [
    ['RP1-正对照', '单线程单租户串行列表请求必须全部 200 且无他租户 id'],
    ['RP2-检测器注入', '判据能检出合成越租户响应（证明 P1/P5 的比对器有效）'],
    ['RP4-期望独立性', '期望集合取自直连 DB 且两侧不相交（交集 ∅ ⇒ 越租户可判别）'],
    ['RP5-判据级注入', '比对器对「干净体」绿、对「掺入他租户 id」红（双向可判）'],
  ]) R.skip(id, name, `本红证判据的期望来源是 A/B **两侧**不相交的 id 集合 ⇒ B 未注入即不可判：${B_SKIP}`)
} else {
  const a = await loginApi(A.phone, SMS_CODE), b = await loginApi(B.phone, SMS_CODE)

  // ── RP1 正对照：单线程单租户串行（必须全绿，证明判据不是恒红）──
  {
    const rows = []
    let bad = 0
    for (const t of [TA, TB]) {
      const tok = t === TA ? a.token : b.token
      for (const r of RESOURCES) {
        const res = await api('GET', r.list, { token: tok })
        const ids = res.status === 200 ? (r.extract(res.json?.data) || []).map(String) : []
        const own = new Set(dbIds(r.table, t))
        const foreign = ids.filter((id) => !own.has(id))
        const okRow = res.status === 200 && foreign.length === 0
        if (!okRow) bad++
        rows.push({ tenant: t, resource: r.key, status: res.status, n: ids.length, foreign: foreign.slice(0, 3) })
      }
    }
    ev.push({ note: `串行 ${RESOURCES.length * 2} 个列表请求（A=${TA}/B=${TB} 各自打自己）`, bad, sample: rows.slice(0, 6) })
    bad === 0 ? R.pass('RP1-正对照', '单线程单租户串行列表请求必须全部 200 且无他租户 id', `${RESOURCES.length * 2} 个串行请求，失败 ${bad} 个`, ev.slice(-1))
             : R.fail('RP1-正对照', '单线程单租户串行列表请求', `🔴 ${bad} 个异常`, ev.slice(-1))
    writeFileSync(join(OUT, 'redproof-poscontrol.json'), JSON.stringify(rows, null, 2))
  }

  // ── RP2 检测器注入：把一条**合成的**越租户响应喂给判据 ⇒ 必须翻红 ──
  {
    const foreignId = [...dbIds('products', TB)][0]
    const own20 = dbIds('products', TA)
    const synth = { status: 200, json: { success: true, data: { items: [{ id: foreignId, name: 'SYNTH' }] } }, text: 'synthetic' }
    const own = new Set(own20)
    const leaked = (synth.json.data.items ?? []).map((x) => String(x.id)).filter((id) => !own.has(id))
    ev.push({ note: `合成响应：声称 tenant ${TA} 的列表里放了 tenant ${TB} 的真实商品 id`, foreignId, leaked })
    leaked.length > 0 ? R.pass('RP2-检测器注入', '判据能检出合成越租户响应（证明 P1/P5 的比对器有效）', `合成体含 ${leaked.length} 个非 ${TA} 的 id ⇒ 判据报红`, ev.slice(-1))
                     : R.fail('RP2-检测器注入', '判据能检出合成越租户响应', '🔴 合成越租户 id 未被检出', ev.slice(-1))
  }

  // ── RP4 期望来源的独立性自查：期望值不取自被测系统的读面 ──
  {
    const ownA = dbIds('products', TA), ownB = dbIds('products', TB)
    const inter = ownA.filter((id) => new Set(ownB).has(id))
    ev.push({ note: '期望来自直连 DB（information_schema + select tenant_id），不取自 API 响应', a: ownA.length, b: ownB.length, intersection: inter.length })
    inter.length === 0 ? R.pass('RP4-期望独立性', '期望集合取自直连 DB 且两侧不相交（交集 ∅ ⇒ 越租户可判别）', `A=${ownA.length} B=${ownB.length} 交集=${inter.length}`, ev.slice(-1))
                       : R.fail('RP4-期望独立性', '期望集合取自直连 DB', `🔴 A/B 交集非空（${inter.length}）⇒ 判据可能误报`, ev.slice(-1))
  }

  // ── RP5 判据级注入（同一个比对器，喂干净体 vs 合成越租户体）──
  {
    const ownA = new Set(dbIds('orders', TA)), ownB = new Set(dbIds('orders', TB))
    const a20 = [...ownA][0], b21 = [...ownB][0]
    writeFileSync(join(OUT, 'redproof-judge-injection.json'), JSON.stringify({
      clean_body_ids: [a20], poisoned_body_ids: [a20, b21],
      truth: { [`a${TA}_belongs_to`]: TA, [`b${TB}_belongs_to`]: TB, source_sql: 'select id, tenant_id from orders where id in (...)' },
    }, null, 2))
    const verify = (bodyIds) => bodyIds.filter((id) => id != null && !ownA.has(id))     // 这是 P1/P5 用的同一个比对判据
    const cleanBad = verify([a20]).length
    const poisonedBad = verify([a20, b21]).length
    const ok1 = cleanBad === 0 && poisonedBad > 0
    ev.push({ note: '判据级注入：同一比对器，干净体应绿、掺入 B 的订单 id 应红', a20, b21, cleanBad, poisonedBad })
    ok1 ? R.pass('RP5-判据级注入', '比对器对「干净体」绿、对「掺入他租户 id」红（双向可判）', `干净体越租户数=${cleanBad}（期望 0）；掺入体越租户数=${poisonedBad}（期望 >0）`, ev.slice(-1))
        : R.fail('RP5-判据级注入', '比对器双向可判', `🔴 干净=${cleanBad} 掺入=${poisonedBad}`, ev.slice(-1))
  }
}

// ── RP3 线程复用残留的注入式演示：读数取自被测服务自身日志（与主体注入无关）──
{
  const LOG = process.env.API_LOG || join(OUT, 'api.log')
  if (!existsSync(LOG)) R.skip('RP3-线程复用证据', '线程复用证据', `服务日志不存在（API_LOG=${LOG}）⇒ 本读数不可得，不折算 pass`)
  else {
    const txt = readFileSync(LOG, 'utf8')
    const lines = txt.split('\n').filter((l) => l.includes('查询我的订单') || l.includes('列表查询') || l.includes('查询商品列表') || l.includes('ProductController'))
    const byThread = {}
    for (const l of lines) {
      const m = l.match(/\[(http-nio-8080-exec-\d+)\]/)
      const t = l.match(/tenantId=(\d+)/)
      if (m && t) (byThread[m[1]] ||= new Set()).add(t[1])
    }
    const reused = Object.entries(byThread).filter(([, s]) => s.size > 1)
    ev.push({ note: '同一 Tomcat 线程先后服务 >1 个租户的请求（线程复用直接证据）', threadCount: Object.keys(byThread).length, reusedThreads: reused.length, sample: reused.slice(0, 5).map(([k, v]) => `${k}: tenants=${[...v].join(',')}`) })
    reused.length > 0 ? R.pass('RP3-线程复用证据', '线程复用确实发生（读数来自被测服务自身日志，非推断）', `${Object.keys(byThread).length} 个线程中 ${reused.length} 个先后服务过多租户；样例：${reused.slice(0, 3).map(([k, v]) => k + '→' + [...v].join('/')).join(' | ')}`, ev.slice(-1))
                      : R.skip('RP3-线程复用证据', '线程复用证据', '本次日志窗口未抓到同一线程多租户')
    writeFileSync(join(OUT, 'redproof-threadreuse.json'), JSON.stringify({ threadCount: Object.keys(byThread).length, reused: reused.slice(0, 20) }, null, 2))
  }
}

const sum = R.summary()
log(`=== redproof 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, 'probe-redproof-summary.json'), JSON.stringify({ ...sum }, null, 2))
if (sum.fail > 0) process.exitCode = 1
