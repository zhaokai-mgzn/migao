// p9：按独立复核（GLM）的 objection 逐条订正**产物**（不许改报告去迁就产物，也不许改产物去迁就报告）
//
// 处置的 objection：
//   · A-OBJ-1 / C-OBJ-08：`P2-NEG:admin` 零探针仍记 pass = **空断言**（恒真）⇒ 改记 skip（未覆盖），并重算 A 面计数。
//   · B-OBJ-4：buttonMatrix 的 18 个「无读码」格逐字引用「见 p2 负向」，但逐格配对后仅 6/18 真有被拦记录
//     （12 格悬空，含 /employees×5 从未被任何负向探针测过）⇒ 改理由为「本格未覆盖」，并把悬空清单落盘。
//   · B-OBJ-1 / C-OBJ-04：`p8-reclassify.json` 的 changed 被后一次运行覆写（p4/p4d 记为 []）⇒ 从**行内** rawState/reclassReason **重建**台账（可复算）。
//   · C-OBJ-12：`out/shots/*_briefing.png` ×6 是 v1 轮陈留（与「7 岗位均不显示简报」矛盾）⇒ 移出主证据目录。
import { readFileSync, writeFileSync, mkdirSync, renameSync, existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, log } from './lib.mjs'

const read = (f) => JSON.parse(readFileSync(join(OUT, f), 'utf8'))
const write = (f, o) => writeFileSync(join(OUT, f), JSON.stringify(o, null, 2))
const recount = (j) => { j.counts = j.rows.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {}); return j }
const fixes = { at: new Date().toISOString(), items: [] }

// ── 1. P2-NEG:admin：零探针的空断言 → skip ──
{
  const j = read('p2-roles-ui.json')
  for (const r of j.rows) {
    if (r.id === 'P2-NEG:admin' && r.state === 'pass' && /探测 0 条/.test(r.detail)) {
      r.rawState = 'pass'
      r.state = 'skip'
      r.reclassReason = '全码岗位无负向项 ⇒ 该判据对 admin **恒真**（空断言）⇒ 未覆盖，不折算 pass（独立复核 A-OBJ-1/C-OBJ-08）'
      fixes.items.push({ id: r.id, from: 'pass', to: 'skip', why: r.reclassReason })
    }
  }
  recount(j)
  write('p2-roles-ui.json', j)
  log(`p2-roles-ui.json → ${JSON.stringify(j.counts)}`)
}

// ── 2. buttonMatrix 的悬空引用 → 明确「本格未覆盖」+ 落盘悬空清单 ──
{
  const j = read('p4-writes.json')
  const p2 = read('p2-roles-ui.json')
  const deniedByRole = Object.fromEntries(p2.roles.map((r) => [r.roleCode, new Set((r.deniedProbes || []).filter((d) => d.denied).map((d) => d.path))]))
  const dangling = []
  let n = 0
  for (const m of j.buttonMatrix || []) {
    for (const row of m.rows) {
      if (!row.skipped) continue
      n++
      const hit = deniedByRole[m.roleCode]?.has(row.path)
      if (!hit) dangling.push({ role: m.roleCode, path: row.path })
      row.skipped = hit
        ? '无读码（该页已被 p2 负向实测拦下）'
        : '无读码（**本格未做负向探测** ⇒ 未覆盖，不得据此说「已被拦」）'
    }
  }
  j.skippedCellCitation = { total: n, backedByP2: n - dangling.length, dangling }
  write('p4-writes.json', j)
  fixes.items.push({ id: 'buttonMatrix.skipCitations', detail: `共 ${n} 格，其中 ${dangling.length} 格原引用悬空，已改为「未覆盖」并落盘 dangling 清单（独立复核 B-OBJ-4）` })
  log(`buttonMatrix 跳过格 ${n}，悬空 ${dangling.length}：${JSON.stringify(dangling.slice(0, 6))}`)
}

// ── 3. 重建订正台账（从行内 rawState 派生，可复算）──
{
  const files = ['p2-roles-ui.json', 'p4-writes.json', 'p4d-writes2.json', 'p5-perm-api.json']
  const ledger = { at: new Date().toISOString(), derivedFrom: 'rows[].rawState + rows[].reclassReason（可复算：重跑本脚本即得同一台账）', files: [] }
  for (const f of files) {
    const j = read(f)
    const changed = j.rows.filter((r) => r.rawState).map((r) => ({ id: r.id, from: r.rawState, to: r.state, reason: r.reclassReason || '(无 reason)' }))
    ledger.files.push({ file: f, counts: j.counts, changed })
  }
  write('p8-reclassify.json', ledger)
  log(`p8-reclassify.json 重建：${ledger.files.map((x) => `${x.file}:${x.changed.length}`).join(' ')}`)
}

// ── 4. v1 轮陈留截图移出主证据目录 ──
{
  const src = join(OUT, 'shots')
  const dst = join(OUT, 'shots-v1-superseded')
  mkdirSync(dst, { recursive: true })
  const moved = []
  for (const f of readdirSync(src)) {
    if (/_briefing\.png$/.test(f)) { renameSync(join(src, f), join(dst, f)); moved.push(f) }
  }
  fixes.items.push({ id: 'staleShots', detail: `${moved.length} 张 v1 轮 *_briefing.png 移至 out/shots-v1-superseded/（独立复核 C-OBJ-12）`, moved })
  log(`陈留截图移出 ${moved.length} 张：${JSON.stringify(moved)}`)
}

write('p9-fixes.json', fixes)
log('== p9 完成')
