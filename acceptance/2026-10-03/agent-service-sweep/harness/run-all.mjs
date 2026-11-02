// 线① —— 全量复跑入口（可复跑工装）
//
// 用法（在 harness/ 目录）：
//   node run-all.mjs            # 跑 A(false) + B..F + R + Z（需要 :8001 以 DEBUG=false 运行）
//   node run-all.mjs --with-debug-pair   # 额外提示如何跑 DEBUG=true 对照批（需重启服务）
//
// 前置（本线自起服务的方式，逐字）：
//   WT=/Users/guangzhen.zk/migao-wt/line1-agent     # 干净 origin/main 检出
//   git -C "$WT" rev-parse HEAD                     # 自证构建点
//   cd "$WT/backend/ai-agent-service" && DEBUG=false nohup .venv/bin/python -m uvicorn app.main:app --port 8001 \
//     > ../../acceptance/2026-10-03/agent-service-sweep/out/ai-agent-service.running.log 2>&1 &
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { OUT, log, nowCST, buildPoint, probeResidue, AGENT_WORKTREE } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const run = (file, env = {}) => {
  log(`----- 运行 ${file} -----`)
  try {
    const out = execFileSync('node', [join(HERE, file)], { encoding: 'utf8', env: { ...process.env, ...env }, maxBuffer: 64 * 1024 * 1024 })
    const tail = out.trim().split('\n').slice(-1)[0]
    log(`${file} 完成：${tail}`)
    return { file, ok: true, last: tail }
  } catch (e) {
    log(`${file} 失败：${String(e.message).slice(0, 300)}`)
    return { file, ok: false, error: String(e.message).slice(0, 500) }
  }
}

const results = []
results.push(run('p0-service-auth.mjs', { MODE: 'debugfalse' }))
results.push(run('p1-tenant-isolation.mjs'))
results.push(run('p2-knowledge-cards.mjs'))
results.push(run('p3-knowledge-candidates.mjs'))
results.push(run('p4-knowledge-templates.mjs'))
results.push(run('p5-agent-sessions.mjs'))
results.push(run('p6-redproof.mjs'))
// 清理：tag 由调用方传入（PROBE_TAGS），与本次各组的 tag 对应；缺省不删
results.push(run('p7-residue.mjs', { PROBE_TAGS: process.env.PROBE_TAGS || '' }))

const summary = {
  ranAt: nowCST(),
  buildPoints: { aiAgent: buildPoint(AGENT_WORKTREE, 8001), adminApi: buildPoint('/Users/guangzhen.zk/migao-wt/main-live', 8080) },
  runs: results,
  residueAfter: probeResidue(),
  note: 'DEBUG=true 对照批需另起服务：DEBUG=true nohup … uvicorn … --port 8001，然后 MODE=debugtrue node p0-service-auth.mjs',
}
writeFileSync(join(OUT, 'SUMMARY.json'), JSON.stringify(summary, null, 2))
log(`SUMMARY 写入 out/SUMMARY.json；残留 = ${JSON.stringify(summary.residueAfter)}`)
console.log(JSON.stringify(summary, null, 2))
