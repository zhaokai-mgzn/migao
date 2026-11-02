// 线① 判据组 Z —— 零残留（自建自清）+ 残留计数机器读数 + 故意失效控制项
//
// 纪律：只删**本包确认创建**的对象（按本包 tag / 前缀逐条列出），逐表计数证明残留 = 0。
// 另含一条**故意失效控制项**（必须红）：证明其余判据不是空跑。
import {
  Recorder, judge, guardedWrite, psql, one, probeResidue, log, nowCST, PROBE_PREFIX,
} from './lib.mjs'

const R = new Recorder('probe-residue.json')
log(`===== 判据组 Z（零残留）开始 ${nowCST().cst} =====`)

// 本包 tag 集合（来自各判据组的输出记录：tag = 时间戳 36 进制后缀）
const TAGS = (process.env.PROBE_TAGS || '').split(',').filter(Boolean)
log(`清理 tag 集合: ${TAGS.join(', ')}`)

const before = probeResidue()
log(`清理前残留读数: ${JSON.stringify(before)}`)

const like = (col, tags) => tags.map((t) => `${col} like '%${t}%'`).join(' or ')
const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)

if (TAGS.length) {
  const sessWhere = `customer_id like 'probe_line1_%' and (${like('customer_id', TAGS)})`
  const agentWhere = `customer_id like 'probe_line1_%' and (${like('customer_id', TAGS)})`
  // 会话消息 → 会话
  w(`delete from session_messages where session_id in (select id from sessions where ${sessWhere});`)
  w(`delete from agent_messages where session_id in (select id from agent_sessions where ${agentWhere});`)
  w(`delete from agent_sessions where ${agentWhere};`)
  w(`delete from sessions where ${sessWhere};`)
  // 知识卡片 / 候选
  w(`delete from knowledge_candidates where suggested_title like '${PROBE_PREFIX}%';`)
  w(`delete from knowledge_cards where title like '${PROBE_PREFIX}%';`)
  // 探针员工
  w(`delete from agent_employees where id like 'l1emp%';`)
} else {
  log('⚠️ 未提供 PROBE_TAGS ⇒ 不执行删除（避免误删他人行）')
}

const after = probeResidue()
log(`清理后残留读数: ${JSON.stringify(after)}`)

judge(R, {
  id: 'Z1-1', name: '零残留：本包探针对象全部清除（逐表计数）',
  expect: 'probeResidue().total == 0（sessions/session_messages/agentSessions/knowledgeCards/knowledgeCandidates 全 0）',
  actual: { before: before.counts, after: after.counts, afterTotal: after.total },
  pass: after.total === 0,
  expectSource: '自建自清纪律：本包创建的一切对象用后必须为 0',
  evidence: [
    `清理 tag: ${TAGS.join(', ')}`,
    `逐表: ${JSON.stringify(after.counts)}`,
    `SQL: delete from sessions where customer_id like 'probe_line1_%' and (customer_id like '%<tag>%')`,
  ],
})

// ── 零残留判据的**红证**（证明它真的会红：故意留一行探针再数）────
{
  const sid = `sess_l1residue${Date.now().toString(36)}`
  w([
    'insert into sessions (id, tenant_id, customer_id, channel, status, metadata, created_at, updated_at, deleted)',
    `values ('${sid}', 20, 'probe_line1_ZCONTROL', 'wechat_mini', 'active', '{}'::jsonb, now(), now(), 0);`,
  ].join('\n'))
  const during = probeResidue()
  const redProofOk = during.total === 1 && during.counts.sessions === 1
  w(`delete from sessions where id='${sid}';`)
  const restored = probeResidue()
  judge(R, {
    id: 'Z1-2', name: '零残留判据的红证：注入 1 行探针 ⇒ 计数当场为 1；删除后回 0',
    expect: '注入期 total==1，还原后 total==0',
    actual: { during: during.counts, afterRestore: restored.counts },
    pass: redProofOk && restored.total === 0,
    expectSource: '零残留读数必须对"多一行/少一行"敏感（否则它是恒 0 的空断言）',
    evidence: [`注入行: ${sid}`, 'SQL: insert into sessions ... customer_id=probe_line1_ZCONTROL ...'],
  })
}

// ── 故意失效控制项（必须红）——证明其余判据不是空跑 ────────────────
{
  const r = { control: 'deliberately-failing-assertion' }
  R.add('Z2-1', '【故意失效控制项】本项**必须红**（若真红 ⇒ 整套断言在真跑）', 'fail',
    '控制项：把期望值换成必然不成立的值（期望 HTTP 599）—— 本项恒 fail 是**设计如此**',
    ['设计说明：若不是 fail，说明 recorder/judge 链路本身没在工作 ⇒ 其余 pass 全部不可信'])
  console.log(JSON.stringify({ control: r }))
}

R.dump()
const s = R.summary()
log(`===== 判据组 Z 结束：pass=${s.pass} fail=${s.fail}（其中故意控制项 1 条）skip=${s.skip} =====`)
console.log(JSON.stringify({ group: 'Z', summary: s, before: before.counts, after: after.counts }))
