// run-all.mjs —— 串行跑完本包全部探针，汇总读数
// ⚠️ 重活串行纪律：本脚本不跑 gate/quick/full（任务书明令），只跑本包 HTTP/SQL 探针。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, log, nowCST, buildPoint } from './lib.mjs'
import { setup } from './setup.mjs'
import { run as p1 } from './p1-ship-protection.mjs'
import { run as p2 } from './p2-state-machine.mjs'
import { run as p3 } from './p3-independent-math.mjs'
import { run as p4 } from './p4-writeface-equivalence.mjs'
import { run as p5 } from './p5-stock-and-print.mjs'
import { run as p6 } from './p6-redproof.mjs'
import { run as p7 } from './p7-noresidue.mjs'

const only = process.argv.slice(2)
const want = (n) => only.length === 0 || only.includes(n)

const started = nowCST()
const bp = buildPoint()
log(`[run-all] 开始 ${started.cst}｜构建点 ${bp.worktree}@${bp.sha}（${bp.subject}）｜admin-api 进程启动 ${bp.adminApiStart}`)

const ctx = await setup({ clean: true })
const results = {}
const t0 = Date.now()

for (const [name, fn, args] of [
  ['p1-ship-protection', p1, { session: ctx.session }],
  ['p2-state-machine', p2, { session: ctx.session, token: ctx.token }],
  ['p3-independent-math', p3, { session: ctx.session, token: ctx.token }],
  ['p4-writeface-equivalence', p4, { session: ctx.session, token: ctx.token }],
  ['p5-stock-and-print', p5, { session: ctx.session, token: ctx.token }],
  ['p6-redproof', p6, { session: ctx.session, token: ctx.token }],
  ['p7-noresidue', p7, {}],
]) {
  if (!want(name)) continue
  try {
    results[name] = await fn(args)
  } catch (e) {
    log(`[run-all] ${name} 抛错: ${e.message}`)
    results[name] = { error: e.message, pass: 0, fail: 1, skip: 0, total: 1 }
  }
}

const total = Object.values(results).reduce(
  (a, r) => ({ pass: a.pass + (r.pass || 0), fail: a.fail + (r.fail || 0), skip: a.skip + (r.skip || 0) }),
  { pass: 0, fail: 0, skip: 0 })
const summary = {
  startedAt: started, finishedAt: nowCST(), wallMs: Date.now() - t0,
  buildPoint: bp, perScript: results,
  total: { ...total, all: total.pass + total.fail + total.skip },
}
writeFileSync(join(OUT, 'summary.json'), JSON.stringify(summary, null, 2))
log(`[run-all] 结束：pass=${total.pass} fail=${total.fail} skip=${total.skip} 墙钟=${Math.round((Date.now() - t0) / 1000)}s`)
console.log(JSON.stringify(summary.total))
