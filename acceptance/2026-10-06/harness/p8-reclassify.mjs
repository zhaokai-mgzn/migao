// p8：判据侧分类订正（**不许**把"驱动没走完表单"记成"产品缺陷"）
//
// 依据（全部是本轮实测读数，逐条可复核）：
//   · W3 订单：页面给出「还差 1 项 —— 有 1 行加工费未定价（组合那半按 0 计）⇒ 请先定价再下单：拼接」
//     ⇒ 这是**产品有意的业务闸门**（未定价的加工组合禁止下单），我的驱动没有去定价 ⇒ 该趟**未覆盖**。
//   · W4 工单：关联订单为必填；UI 驱动未能把订单解析进表单（对话框仍开着）⇒ 未覆盖。
//   · W5 商品：页面给出「还有 6 处必填未完成」（分类/主图/计价单位/售卖方式…）⇒ 驱动未填齐 ⇒ 未覆盖。
// 订正方式：state 改 `skip`，原值留在 `rawState`，并把**实测证据原文**写进 `reclassReason`（可复算）。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, log } from './lib.mjs'

const RULES = {
  'P4-W3': '页面校验清单逐字：「还差 1 项 … 有 1 行加工费未定价（组合那半按 0 计）⇒ 请先定价再下单：拼接」= 产品有意的业务闸门；驱动未去定价',
  'P4-W4': '前置不成立（本租户当轮无订单）⇒ 已由驱动自记 skip',
  'P4D-2': '关联订单为必填，UI 驱动未把订单解析进表单（提交后对话框仍在，库内无新行）',
  'P5-positive': 'API 正对照载荷未对上契约（HTTP 422：缺 title/必填）；正对照已由 **UI 侧 W2**（知识编辑真建卡片、库内 0→1→2）承担 ⇒ 本行不构成产品判定',
  'P4D-3': '页面校验逐字：「表单校验未通过：还有 6 处必填内容未完成」（商品分类/商品主图/计价单位/售卖方式…）；此后两次补齐仍未通过',
}

const out = { at: new Date().toISOString(), files: [] }
for (const f of ['p4-writes.json', 'p4d-writes2.json', 'p5-perm-api.json']) {
  const p = join(OUT, f)
  const j = JSON.parse(readFileSync(p, 'utf8'))
  const changed = []
  for (const r of j.rows) {
    const reason = RULES[r.id]
    if (reason && r.state === 'fail') {
      changed.push({ id: r.id, from: r.state, to: 'skip', reason })
      r.rawState = r.state
      r.state = 'skip'
      r.reclassReason = reason
    }
  }
  j.counts = j.rows.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  j.reclassified = changed
  writeFileSync(p, JSON.stringify(j, null, 2))
  out.files.push({ file: f, counts: j.counts, changed })
  log(`${f}: ${JSON.stringify(j.counts)} 订正 ${changed.length} 条`)
  for (const c of changed) log(`   ${c.id}: ${c.from} → ${c.to}（${c.reason.slice(0, 90)}）`)
}
writeFileSync(join(OUT, 'p8-reclassify.json'), JSON.stringify(out, null, 2))
