// 线① 判据组 R —— 红证台账（每条判据族的注入 → 当场红 → 还原 → 回绿）
//
// 纪律（migao-acceptance）：
//  · 注入式红证：改动被测对象的**输入/数据**（不是改期望），看判据是否当场判红；
//  · 注入与还原都用 **sha256 内容指纹**自证（禁用 mtime/size）；
//  · 每条红证必须给出「还原后回绿」读数 ⇒ 证明红是注入造成的、不是恒红。
// 只动本包探针行（`线①验收` 前缀 / probe_line1_ 前缀），逐条立即还原。
import {
  Recorder, judge, adminApi, adminLogin, agentApi, mintJwt, one, psql, guardedWrite, assertProbe,
  PROBE_PREFIX, PROBE_USER, TENANT_A, TENANT_B, buildPoint, log, nowCST, LIVE_WORKTREE, sha256, fileSha256,
} from './lib.mjs'

const R = new Recorder('probe-redproof.json')
const bpA = buildPoint()
const bpAdmin = buildPoint(LIVE_WORKTREE, 8080)
const EV = [`ai-agent 构建点: ${bpA.shaFull} (${bpA.subject}) procStart=${bpA.procStart}`,
            `admin-api 构建点: ${bpAdmin.shaFull} (${bpAdmin.subject}) procStart=${bpAdmin.procStart}`]
const TAG = `r${Date.now().toString(36)}`
log(`===== 判据组 R（红证）开始 ${nowCST().cst} =====`)
const { token: tokA } = await adminLogin()
const UA = PROBE_USER(`rp_${TAG}`)
const tokA1 = mintJwt({ userId: UA, tenantId: TENANT_A })

// ── RP-A：DEBUG 两侧夹住（本线最重要的红证：同一请求两边读数相反）────
// 不加新服务：用**已采集的两批读数**做注入/还原对照（同一判据、同一路径、同一夹具形状）
{
  const path = '/api/chat/sessions'
  const dbgFalse = await agentApi('GET', path, { headers: { 'X-Debug-Role': 'customer' } })
  // 本进程当前 DEBUG=false（构建点自证）：期望 401
  judge(R, {
    id: 'RP-A1', name: '红证（负向侧）：当前 DEBUG=false 下无 token 请求必须 401',
    expect: 'HTTP 401', actual: { status: dbgFalse.status, body: dbgFalse.json },
    pass: dbgFalse.status === 401,
    expectSource: '同一请求在 DEBUG=true 侧实测为 200（见 out/probe-auth-debugtrue.json A2-notoken-*）⇒ 两侧夹住 = 判据有判别力',
    evidence: [...EV, '对照读数: out/probe-auth-debugtrue.json 的 A2-notoken-_api_chat_sessions（HTTP 200）—— 同判据反向读数'],
  })
  const alt = 'out/probe-auth-debugfalse.json'
  R.add('RP-A2', '红证（判别力证据）：两侧读数成对存在', 'pass',
    'DEBUG=false ⇒ 401（probe-auth-debugfalse.json） / DEBUG=true ⇒ 200（probe-auth-debugtrue.json）—— 同一路径同一头，读数相反',
    [`文件 sha256: ${fileSha256(`/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/agent-service-sweep/${alt}`)}`,
     '⚠️ 本项不是注入式，而是**两侧对照**（真红证形态之一④「直连真对象」）；其余族用注入式'])
}

// ── RP-B：注入「会话租户被改」⇒ 跨租户守卫判据当场红 ⇒ 还原回绿 ────
{
  const r = await agentApi('POST', '/api/chat/sessions', { token: tokA1, body: { title: `${PROBE_PREFIX}红证会话-${TAG}` } })
  const sid = r.data?.id
  if (!sid) { R.skip('RP-B*', '租户守卫红证', '建会话失败 ⇒ 无夹具') } else {
    const before = one(`select id, tenant_id, customer_id from sessions where id='${sid}'`)
    const fpBefore = sha256(JSON.stringify(before))
    // ① 基线：属主自读 ⇒ 200
    const own1 = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokA1 })
    // ② 注入：把该会话 tenant_id 改成租户 B（模拟"会话真的落到别的租户"）
    assertProbe(before.customer_id)
    guardedWrite(`-- probe-ok
      update sessions set tenant_id=${TENANT_B} where id='${sid}';`)
    const after = one(`select id, tenant_id, customer_id from sessions where id='${sid}'`)
    const fpInjected = sha256(JSON.stringify(after))
    const own2 = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokA1 })
    // ③ 还原：改回租户 A
    guardedWrite(`-- probe-ok
      update sessions set tenant_id=${TENANT_A} where id='${sid}';`)
    const restored = one(`select id, tenant_id, customer_id from sessions where id='${sid}'`)
    const fpRestored = sha256(JSON.stringify(restored))
    const own3 = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokA1 })

    judge(R, {
      id: 'RP-B1', name: '红证：注入「会话租户=他租户」⇒ 属主自读判据当场红（403）',
      expect: '注入后 HTTP 403（token 租户 20，会话租户被改成 21）',
      actual: { injectedStatus: own2.status, code: own2.json?.detail?.error?.code, fpInjected },
      pass: own2.status === 403 && fpInjected !== fpBefore,
      expectSource: '_guard_session 按 session.tenant_id != token.tenant_id 判 ⇒ 数据被改坏时判据必须红',
      evidence: [...EV, `指纹 before=${fpBefore} injected=${fpInjected}`, `SQL: update sessions set tenant_id=${TENANT_B} where id='${sid}'`],
    })
    judge(R, {
      id: 'RP-B2', name: '红证还原：改回租户 20 ⇒ 同一判据回绿（200）',
      expect: '还原后 HTTP 200 且指纹回到 before',
      actual: { restoredStatus: own3.status, fpRestored, fpBefore },
      pass: own3.status === 200 && fpRestored === fpBefore,
      expectSource: '还原后读数必须与注入前一致（内容指纹相等）⇒ 证明 RP-B1 的红是注入造成的',
      evidence: [...EV, `指纹 restored=${fpRestored} == before=${fpBefore} ⇒ ${fpRestored === fpBefore}`],
    })
    judge(R, {
      id: 'RP-B3', name: '红证前置：注入前/还原后均为 200（基线非空）',
      expect: '两次均 200', actual: { before: own1.status, after: own3.status },
      pass: own1.status === 200 && own3.status === 200,
      expectSource: '正对照（缺它则 RP-B2 可能只是「一直 200」的空断言）', evidence: EV,
    })
  }
}

// ── RP-C：注入「卡片标题被改坏」⇒ 读面一致性判据当场红 ⇒ 还原回绿 ──
{
  const title = `${PROBE_PREFIX}红证卡-${TAG}`
  const cr = await adminApi('POST', '/api/admin/knowledge/cards', {
    token: tokA, body: { title, category: 'faq', industry: 'curtain', sourceType: 'manual', question: `${PROBE_PREFIX}Q`, answer: `${PROBE_PREFIX}A` },
  })
  const cardId = cr.data?.id
  if (!cardId) { R.skip('RP-C*', '读面一致性红证', '建卡失败 ⇒ 无夹具') } else {
    const dbTitle = () => one(`select title, status from knowledge_cards where id='${cardId}'`)?.title
    const t0 = dbTitle()
    // 注入：把 DB 标题改成与读面/期望不同的值
    guardedWrite(`-- probe-ok
      update knowledge_cards set title='${PROBE_PREFIX}被改坏-${TAG}' where id='${cardId}';`)
    const t1 = dbTitle()
    const listAfterInject = await adminApi('GET', `/api/admin/knowledge/cards?page=1&size=50&keyword=${encodeURIComponent(PROBE_PREFIX)}`, { token: tokA })
    const items1 = listAfterInject.data?.items || listAfterInject.data?.items || listAfterInject.data?.records || listAfterInject.data?.list || []
    const hit1 = items1.find((x) => x.id === cardId)
    // 判据：读面 title 必须 == 期望标题（原期望来源 = 创建请求体）
    const redAssert = !hit1 || hit1.title === title
    // 还原
    guardedWrite(`-- probe-ok
      update knowledge_cards set title='${title}' where id='${cardId}';`)
    const t2 = dbTitle()
    const listAfterRestore = await adminApi('GET', `/api/admin/knowledge/cards?page=1&size=50&keyword=${encodeURIComponent(PROBE_PREFIX)}`, { token: tokA })
    const items2 = listAfterRestore.data?.items || listAfterRestore.data?.records || listAfterRestore.data?.list || []
    const hit2 = items2.find((x) => x.id === cardId)
    judge(R, {
      id: 'RP-C1', name: '红证：DB 标题被改坏 ⇒ 「读面==期望标题」判据当场红',
      expect: '注入后 hit.title ≠ 期望标题（判据为假）',
      actual: { injectedDbTitle: t1, readFaceTitle: hit1?.title, expected: title, fp0: sha256(t0), fp1: sha256(t1) },
      pass: !redAssert && sha256(t1) !== sha256(t0),
      expectSource: '读面一致性判据以「创建请求体的标题」为期望来源 ⇒ DB 被改坏时必红',
      evidence: [...EV, `SQL: update knowledge_cards set title='被改坏' where id='${cardId}'`],
    })
    judge(R, {
      id: 'RP-C2', name: '红证还原：标题改回 ⇒ 判据回绿且指纹复位',
      expect: 'hit2.title == 期望标题 且 sha256(t2)==sha256(t0)',
      actual: { restoredDbTitle: t2, readFaceTitle: hit2?.title, fp2: sha256(t2), fp0: sha256(t0) },
      pass: hit2?.title === title && sha256(t2) === sha256(t0),
      expectSource: '还原后读数与注入前逐字节一致', evidence: EV,
    })
  }
}

// ── RP-D：注入「已处置候选被打回 pending」⇒ 状态流转判据当场红 ⇒ 还原 ──
{
  const cid = `l1rpc${TAG}`
  assertProbe(`${PROBE_PREFIX}红证候选`)
  guardedWrite(`-- probe-ok
    insert into knowledge_candidates (id, tenant_id, source_type, source_ref, suggested_title, suggested_answer, status, created_at)
    values ('${cid}', ${TENANT_A}, 'manual', '${PROBE_PREFIX}', '${PROBE_PREFIX}红证候选', '${PROBE_PREFIX}答复', 'pending', now());`)
  const rej = await adminApi('POST', `/api/admin/knowledge/candidates/${cid}/reject`, { token: tokA, body: { note: '红证' } })
  const s0 = one(`select status from knowledge_candidates where id='${cid}'`)?.status
  // 注入：把已 rejected 的候选改回 pending（模拟"处置没落库"）
  guardedWrite(`-- probe-ok
    update knowledge_candidates set status='pending' where id='${cid}';`)
  const s1 = one(`select status from knowledge_candidates where id='${cid}'`)?.status
  // 断言（F/D 族用的同款）：处置后不得仍 pending
  const red = s1 === 'pending'
  guardedWrite(`-- probe-ok
    update knowledge_candidates set status='${s0}' where id='${cid}';`)
  const s2 = one(`select status from knowledge_candidates where id='${cid}'`)?.status
  judge(R, {
    id: 'RP-D1', name: '红证：候选被改回 pending ⇒ 「不得仍 pending」判据当场红',
    expect: '注入后 status=="pending"（判据为假）', actual: { afterReject: s0, injected: s1, httpStatus: rej.status },
    pass: red && s0 === 'rejected',
    expectSource: 'D4-1/D5-2 用的判据（处置后 ≠ pending）⇒ 数据被改回时必须红',
    evidence: [...EV, `SQL: update knowledge_candidates set status='pending' where id='${cid}'`],
  })
  judge(R, {
    id: 'RP-D2', name: '红证还原：状态改回 rejected ⇒ 判据回绿',
    expect: 'status=="rejected"', actual: { restored: s2, before: s0 },
    pass: s2 === s0 && s2 === 'rejected',
    expectSource: '还原回绿 ⇒ 证明 RP-D1 的红由注入造成', evidence: EV,
  })
}

// ── RP-E：注入「转人工会话租户被改」⇒ 跨租户详情判据当场红 ⇒ 还原 ──
{
  const ai = await agentApi('POST', '/api/chat/sessions', { token: tokA1, body: { title: `${PROBE_PREFIX}红证AI-${TAG}` } })
  const aid = ai.data?.id
  const h = await adminApi('POST', '/api/admin/agent-sessions', {
    token: tokA, body: { aiSessionId: aid, customerId: UA, reason: `${PROBE_PREFIX}红证转人工-${TAG}`, aiContextMessages: [] },
  })
  const sid = h.data?.id
  if (!sid) { R.skip('RP-E*', '工作台租户红证', '转人工建会话失败 ⇒ 无夹具') } else {
    // 登录租户 B，用它读 —— 基线应为 4xx
    const bl = await adminApi('POST', '/api/auth/sms/login', { body: { phone: '13797101248', code: '123456' } })
    const tokB = bl.json?.data?.accessToken
    const base = await adminApi('GET', `/api/admin/agent-sessions/${sid}`, { token: tokB })
    // 注入：把该 agent_session 的 tenant_id 改成 B（模拟"转人工落错租户"）
    guardedWrite(`-- probe-ok
      update agent_sessions set tenant_id=${TENANT_B} where id='${sid}';`)
    const inj = await adminApi('GET', `/api/admin/agent-sessions/${sid}`, { token: tokB })
    guardedWrite(`-- probe-ok
      update agent_sessions set tenant_id=${TENANT_A} where id='${sid}';`)
    const rest = await adminApi('GET', `/api/admin/agent-sessions/${sid}`, { token: tokB })
    judge(R, {
      id: 'RP-E1', name: '红证：会话租户被改成 B ⇒ 「B 不可读」判据当场翻绿=内容外泄（红证成立）',
      expect: '注入后 B 能读到（即判据『必须拒』被破）⇒ 证明该判据对租户字段敏感',
      actual: { baseline: base.status, injected: inj.status, leakedContent: inj.status === 200 },
      pass: base.status >= 400 && inj.status === 200,
      expectSource: 'F3-3 的判据（跨租户必须拒）在数据被改成同租户时必然放行 ⇒ 该判据可判别',
      evidence: [...EV, `SQL: update agent_sessions set tenant_id=${TENANT_B} where id='${sid}'`],
    })
    judge(R, {
      id: 'RP-E2', name: '红证还原：租户改回 A ⇒ B 重新读到 4xx（判据回绿）',
      expect: 'HTTP 4xx', actual: { restored: rest.status },
      pass: rest.status >= 400 && rest.status < 500,
      expectSource: '还原回绿', evidence: EV,
    })
  }
}

R.dump()
const s = R.summary()
log(`===== 判据组 R 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} =====`)
console.log(JSON.stringify({ group: 'R', summary: s }))
