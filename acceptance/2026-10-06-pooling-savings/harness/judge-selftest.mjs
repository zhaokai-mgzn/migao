// 判据离线自检（用 out/main.json 里 300 张单的真实工序签名 + 现取配置）：
// 先在**已落盘的真实读数**上把「工序 × 工艺路线」判据跑通，再去跑 300 单的主实验（避免第二次假红）。
import { readFileSync } from 'node:fs'
import { psql } from './lib.mjs'

const j = JSON.parse(readFileSync(new URL('../out/main.json', import.meta.url), 'utf8'))
const T = 25
const rules = psql(`select trigger_kind, trigger_value, coalesce(position,'') as position, action, operation, priority
  from production_route_rules where tenant_id=${T} and deleted=0 and status='active' order by priority, id`)
const tpl = j.templates.find((t) => t.is_default)
const mainline = JSON.parse(tpl.mainline)
const logical = (n) => n.replace(/^(布帘|布|纱)/, '').replace(/-(布|纱)$/, '')
const sigs = j.seqSignatureSet
const actual = sigs[0].split('>').map((s) => s.split(':')[1])
const actualLogical = actual.map(logical)
const matched = rules.filter((r) => r.trigger_kind === 'craft' && r.trigger_value === '韩褶')
const ins = matched.filter((r) => r.action === 'insert').map((r) => r.operation)
const rem = matched.filter((r) => r.action === 'remove').map((r) => r.operation)
const expect = mainline.filter((m) => !rem.includes(m)).concat(ins)
console.log(JSON.stringify({
  signatures: sigs.length,
  mainline, matchedRules: matched, inserted: ins, removed: rem,
  expect, actual, actualLogical,
  missing: expect.filter((m) => !actualLogical.includes(m)),
  extra: actualLogical.filter((n) => !expect.includes(n)),
  orderExact: JSON.stringify(expect) === JSON.stringify(actualLogical),
  templateFull: JSON.parse(tpl.mainline),
}, null, 1))
