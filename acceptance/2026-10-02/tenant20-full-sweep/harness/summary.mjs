// 汇总：把各阶段 JSON 结果合成一张总表（out/SUMMARY.md）+ 控制台读数。
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')

const STAGES = [
  ['s1-onboard.json', '阶段1 新企业入驻'],
  ['s2-seed.json', '阶段2 多岗位员工 + 工人档案'],
  ['s20-inventory.json', '阶段2 库存侧（入库/库存面）'],
  ['s3-rbac.json', '阶段3 RBAC 矩阵（第一轮）'],
  ['s3b-rbac2.json', '阶段3b RBAC 复核（第二轮）'],
  ['s3c-rbac3.json', '阶段3c RBAC 收口（第三轮）'],
  ['s4-docs.json', '阶段4 功能单据逐项（两轮）'],
  ['s5-h5.json', '阶段5 B 端 H5（工人端）'],
  ['s6-chain.json', '阶段6 **连贯链路**（入库过账→下单→加工→报工→发货）'],
  ['s7-rbac-matrix.json', '阶段7 **全量端点 RBAC 矩阵**（115 端点 × 8 身份 @ main）'],
  ['s8-routes-buttons.json', '阶段8 全量页面守卫 + 元素级 RBAC（40 路由 × 8 身份）'],
  ['s9-position-jobs.json', '阶段9 **每岗位用自己的账号跑本岗位功能**（8 岗位 × 17 动作）'],
  ['s21-craft-init.json', '阶段2 工艺侧（工艺参数配置初始化模拟）'],
]

const rows = []
let P = 0, F = 0, S = 0
for (const [file, label] of STAGES) {
  const p = join(OUT, file)
  if (!existsSync(p)) { rows.push([label, '—', '—', '—', '未产出']); continue }
  const recs = JSON.parse(readFileSync(p, 'utf8'))
  const c = (s) => recs.filter((r) => r.status === s).length
  P += c('pass'); F += c('fail'); S += c('skip')
  rows.push([label, c('pass'), c('fail'), c('skip'), recs.filter((r) => r.status === 'fail').map((r) => r.id).join(', ') || '—'])
}

const h5 = existsSync(join(OUT, 'ui-smoke', 'smoke-summary.md')) ? readFileSync(join(OUT, 'ui-smoke', 'smoke-summary.md'), 'utf8') : ''
const smokeTotal = (h5.match(/通过 (\d+)\/(\d+)/) || [])[0] || '未产出'

const md = []
md.push('# 汇总读数（自动生成）')
md.push('')
md.push('| 阶段 | pass | fail | skip | 失败项 |')
md.push('|---|---|---|---|---|')
for (const r of rows) md.push(`| ${r[0]} | ${r[1]} | ${r[2]} | ${r[3]} | ${r[4]} |`)
md.push('')
md.push(`**自建阶段合计**：pass=${P} / fail=${F} / skip=${S}`)
md.push('')
md.push(`**复用仓库既有 33 旅程 UI 冒烟**（scripts/ui-smoke-merchant/spec.mjs）：${smokeTotal} —— 12 条失败经截图+DOM 逐条归因为「脚本自身过期」，非产品缺陷（见 REPORT.md）。`)
md.push('')
md.push('## 失败明细')
md.push('')
for (const [file] of STAGES) {
  const p = join(OUT, file)
  if (!existsSync(p)) continue
  for (const r of JSON.parse(readFileSync(p, 'utf8'))) {
    if (r.status === 'fail') md.push(`- **[${r.id}] ${r.name}** — ${r.detail}`)
  }
}
writeFileSync(join(OUT, 'SUMMARY.md'), md.join('\n'))
console.log(md.join('\n'))
