// P3 — 小程序（bmini-app）**入库写面**：/api/worker/inbound/**（草稿 → 过账 → 标签短码 → 打印留痕）
//
// 判据来源（源码符号）：
//   POST /api/worker/inbound/recognize        → WorkerInboundService.recognize（解码优先，零 LLM）
//   POST /api/worker/inbound/drafts           → WorkerInboundService.createDraft（草稿不动库存）
//   POST /api/worker/inbound/drafts/{id}/post → WorkerInboundService.postDraft（过账才动库存；confirmed 必填）
//   GET/POST /api/worker/inbound/labels/{code}[/print] → InboundLabelService.detail/recordPrint
// 期望独立算出：库存/台账/标签行从 DB 复读，不拿 API 读面当期望。
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import {
  Recorder, judge, apiWorker, api, log, nowCST, psql, one,
  ensureWorkerSession, storePath, saveStore, idemKey, loginApi, rawWorker, guardedWrite,
  TENANT_ID, PROBE_PREFIX, ID_PREFIX, IDEMPOTENCY_HEADER, fmtQty, cents,
} from './lib.mjs'

// 前置清理（幂等）：本包 `la` 前缀域的入库单/标签/明细（含本轮 bisect 期间的探针单）
{
  const w = (sql) => { try { guardedWrite(`-- probe-ok\n${sql}`) } catch (e) { log(`前置清理跳过: ${e.message.slice(0, 80)}`) } }
  const sc = `select id from inbound_orders where tenant_id=${20} and id like 'la%'`
  w(`delete from inbound_labels where inbound_order_id in (${sc});`)
  w(`delete from inbound_order_items where inbound_order_id in (${sc});`)
  w(`delete from inbound_orders where id in (${sc});`)
}

const R = new Recorder('P3-inbound.json')
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const B = await ensureWorkerSession(store, 'B')

// ── 选一个真实商品 + SKU 作为入库对象（**不新建商品**：探针域只在 id 前缀，商品不动）──
// 🔴 `product_skus.id` 是 bigint 且 > 2^53 ⇒ **禁止** 走 Number()/JSON.parse 取值（精度丢失会让
//    skuId 变另一个数 ⇒ 服务端 400「SKU 不属于该商品」）。用 psql 的 `::text` + 原文拼进请求体。
const skuRaw = psql(`select s.id::text as sku_id, s.sku_code, s.color_name, s.stock::text, p.id as product_id, p.name
                   from product_skus s join products p on p.id=s.product_id
                  where s.tenant_id=${TENANT_ID} and p.deleted=0 order by s.id limit 1`)[0]
const sku = { ...skuRaw, sku_id_json: skuRaw.sku_id }
log(`入库对象: product=${sku.product_id} (${sku.name}) sku=${sku.sku_id} 现库存=${sku.stock}`)
const stockOf = (skuId) => one(`select stock::text from product_skus where tenant_id=${TENANT_ID} and id='${skuId}'`)?.stock
const lastLedger = () => psql(`select id, delta::text, before_qty::text, after_qty::text, reason, ref_no, operator, (created_at at time zone 'Asia/Shanghai')::text as cst
                                  from stock_ledger_entries where tenant_id=${TENANT_ID} and sku_id='${sku.sku_id}'
                                 order by created_at desc limit 1`)[0]

// ── ① 识别（**不触发真实 LLM**：只走不调用模型的路径）──
// 🔴 重要契约发现：源码 `WorkerInboundService.recognize` 注释声称「前端已解码 ⇒ 走 PATH_BARCODE，
//    零 LLM 调用；解不出 ⇒ 不传这个键」。但**实测**：只给 `barcode` 不给图片 ⇒ 400
//    `INBOUND_RECOGNIZE_NO_IMAGE`（图片校验在解码分支**之前**）⇒ 前端那条「解码优先」的省流路径
//    在当前端点上**不可达**（必须同时带图，才会走到 path=barcode_decode）。本节按实测登记。
const rec1 = await apiWorker('POST', '/api/worker/inbound/recognize', { sessionId: A.sessionId, body: { barcode: sku.sku_code } })
judge(R, {
  id: 'D1.recognize-barcode-only-rejected', name: '入库识别：**只给条码不给图片** ⇒ 400 INBOUND_RECOGNIZE_NO_IMAGE（源码注释里「解码优先、零 LLM」那条路径从本端点**不可达**）',
  expect: '实测 HTTP 400（与源码类注释「barcode 非空 ⇒ PATH_BARCODE，一次 LLM 都不调」不一致：图片校验在解码分支之前）',
  actual: `HTTP ${rec1.status} code=${rec1.json?.error?.code} msg=${String(rec1.json?.error?.message).slice(0, 80)}`,
  pass: rec1.status === 400 && rec1.json?.error?.code === 'INBOUND_RECOGNIZE_NO_IMAGE',
  expectSource: 'WorkerInboundService.recognize: `validImages(req)` 在 `if (barcode != null)` **之前** 执行（源码顺序）',
  evidence: ['契约影响：H5/小程序若按注释只传 barcode 想省一次 vision，会直接 400 —— 该路径需同时带图才可达'],
})
// D2：0 次 LLM 的负例 —— 无效 URL 由 ai-agent 侧归一化过滤 ⇒ 走 vision 但**不产生命中**；
//     本条只断言「零命中不建品」，不断言具体 HTTP（避免把 agent-service 行为误记为本线判据）。
// 🔴 跨包隔离（铁律 6）：线B 同时在租户 20 建商品（实测 16:32:16~20 连建 3 个「线B验收商品-C2xR3」）
// ⇒ 全表计数会被外来行污染。判据收敛到**本包命名域**，并归因逐行内容。
const probeProducts = () => psql(`select id, name, created_at from products where tenant_id=${TENANT_ID} and deleted=0 and name like '${PROBE_PREFIX}%'`)
const productsBefore = probeProducts().length
const rec2 = await apiWorker('POST', '/api/worker/inbound/recognize', { sessionId: A.sessionId, body: { images: ['not-a-url://x'], barcode: `${ID_PREFIX}-NOPE-000` } })
const productsAfter = probeProducts().length
judge(R, {
  id: 'D2.recognize-no-match-no-create', name: '识别零命中 ⇒ **不自动建品/SKU**（商品数前后相同；响应不得回凭空构造的 SKU）',
  expect: `本包探针域商品数不变（${productsBefore}）+ 响应不含构造的 skuMatches`,
  actual: `HTTP ${rec2.status} matches=${JSON.stringify(rec2.json?.data?.skuMatches ?? null)} 探针域商品=${productsBefore}→${productsAfter}`,
  pass: productsBefore === productsAfter && (rec2.status >= 500 ? false : true) && (rec2.json?.data?.skuMatches?.length ?? 0) === 0,
  expectSource: 'WorkerInboundService：零命中不建品（MSG_MANUAL_NO_SKU_MATCH「系统不会替你猜」）',
  evidence: [`resp=${JSON.stringify(rec2.json?.error ?? rec2.json?.data ?? {}).slice(0, 240)}`],
})
// ── ② 建草稿：**不动库存** ──
const stockBeforeDraft = stockOf(sku.sku_id)
const draftKey = idemKey('p3draft')
const draftBody = { productId: sku.product_id, skuId: sku.sku_id, quantity: '7.5', unitCost: '12.5', supplier: `${PROBE_PREFIX}供应商`, dyeLot: `${ID_PREFIX}-LOT` }
const draftBodyJson = JSON.stringify(draftBody)
// 🔴 载荷取向（主会话独立复核 + 本包实测，两方一致）：`productId`=字符串(products.id)、
//    `skuId`=**数字**(product_skus.id, bigint)。倒置或传字符串 id ⇒ Jackson 解不出 Long ⇒
//    400 BAD_REQUEST「请求体格式错误或缺失」（**不是**业务校验，别误记成缺陷）。
const d1 = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: A.sessionId, headers: { [IDEMPOTENCY_HEADER]: draftKey }, body: draftBody,
})
const draftId = d1.json?.data?.draftId ?? null
const stockAfterDraft = stockOf(sku.sku_id)
const draftRow = draftId ? one(`select id, inbound_no, status, source, created_by, total_amount::text from inbound_orders where tenant_id=${TENANT_ID} and id='${draftId}'`) : null
judge(R, {
  id: 'D5.draft-created', name: 'POST /api/worker/inbound/drafts ⇒ 建单成功（status=draft, source=purchase）',
  expect: 'HTTP 200 + DB inbound_orders 行 status=draft + source=purchase + created_by=探针工人 id',
  actual: `HTTP ${d1.status} draftId=${draftId} row=${JSON.stringify(draftRow)}`,
  pass: d1.status === 200 && draftRow?.status === 'draft' && draftRow?.source === 'purchase' && draftRow?.created_by === A.workerId,
  expectSource: 'WorkerInboundService.createDraft → InboundOrderService.create（source 服务端固定 purchase；DTO 无 source 键）',
  evidence: [`resp=${String(JSON.stringify(d1.status >= 300 ? (d1.json?.error ?? d1.text ?? '') : (d1.json?.data ?? ''))).slice(0, 300)}`, `req=${draftBodyJson}`],
})
judge(R, {
  id: 'D6.draft-does-not-move-stock', name: '🔴 草稿态**完全不动库存**（SKU stock 前后逐字相同）',
  expect: `${stockBeforeDraft} == ${stockAfterDraft}`, actual: `before=${stockBeforeDraft} after=${stockAfterDraft}`,
  pass: cents(stockBeforeDraft) === cents(stockAfterDraft),
  expectSource: 'WorkerInboundService.createDraft 类注释：「草稿态完全不动库存」（设计 §5.3 硬约束 1）',
})
const d1dup = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: A.sessionId, headers: { [IDEMPOTENCY_HEADER]: draftKey }, body: draftBody,
})
const dupOrders = psql(`select id, inbound_no from inbound_orders where tenant_id=${TENANT_ID} and id='${draftId}'`).length
judge(R, {
  id: 'D7.draft-idempotent', name: '同 Idempotency-Key 重复建草稿 ⇒ 不建第二张（回放首次结果）',
  expect: 'HTTP 200 + 同 draftId + 无第二张单',
  actual: `HTTP ${d1dup.status} draftId=${d1dup.json?.data?.draftId}（首次 ${draftId}）行数=${dupOrders}`,
  pass: d1dup.status === 200 && d1dup.json?.data?.draftId === draftId,
  expectSource: 'ClientRequestIdService（ENDPOINT_DRAFTS=worker/inbound/drafts）+ 同键回放',
})

// ── ③ 过账：确认标记 + 幂等 + 动库存 + 发标签 ──
const postKey = idemKey('p3post')
const noConfirm = await apiWorker('POST', `/api/worker/inbound/drafts/${draftId}/post`, { sessionId: A.sessionId, body: {} })
const stockAfterNoConfirm = stockOf(sku.sku_id)
judge(R, {
  id: 'D8.post-needs-confirm', name: '过账缺 confirmed=true ⇒ 409 且**一行库存都不动**',
  expect: 'HTTP 409 + stock 不变', actual: `HTTP ${noConfirm.status} code=${noConfirm.json?.error?.code} stock=${stockAfterNoConfirm}`,
  pass: noConfirm.status === 409 && cents(stockAfterNoConfirm) === cents(stockBeforeDraft),
  expectSource: 'WorkerInboundService.postDraft：req.confirmed != TRUE ⇒ conflict(409)（设计 §6.5 未确认不落库）',
})
const post1 = await apiWorker('POST', `/api/worker/inbound/drafts/${draftId}/post`, {
  sessionId: A.sessionId, headers: { [IDEMPOTENCY_HEADER]: postKey }, body: { confirmed: true },
})
const stockAfterPost = stockOf(sku.sku_id)
const postRow = one(`select id, status, posted_at is not null as posted, posted_by from inbound_orders where tenant_id=${TENANT_ID} and id='${draftId}'`)
const ledger = lastLedger()
const expectStock = fmtQty(BigInt(cents(stockBeforeDraft)) + BigInt(cents('7.5')))
judge(R, {
  id: 'D9.post-moves-stock', name: '过账 ⇒ status=posted + SKU 库存 +7.500（期望本包独立算出） + 台账一行',
  expect: `stock ${stockBeforeDraft} + 7.500 = ${expectStock}；inbound_orders.status=posted`,
  actual: `HTTP ${post1.status} stock=${stockAfterPost} row=${JSON.stringify(postRow)} ledger=${JSON.stringify(ledger)}`,
  pass: post1.status === 200 && cents(stockAfterPost) === cents(expectStock) && postRow?.status === 'posted',
  expectSource: 'InboundOrderService.post（过账才动库存）+ stock_ledger_entries 独立复读',
  evidence: [`expectedStock=${expectStock}`, `ledger delta=${ledger?.delta} ${ledger?.before_qty}→${ledger?.after_qty} reason=${ledger?.reason}`],
})
const labels = psql(`select l.id, l.short_code, l.print_count, l.inbound_order_id from inbound_labels l where l.tenant_id=${TENANT_ID} and l.inbound_order_id='${draftId}' and l.deleted=0`)
judge(R, {
  id: 'D10.labels-issued', name: '过账后**同一事务**为每行发短码（8 位 Crockford Base32），草稿态没有',
  expect: 'inbound_labels 1 行 + short_code 匹配 ^[0-9A-HJKMNP-TV-Z]{8}$ + print_count=0',
  actual: JSON.stringify(labels),
  pass: labels.length === 1 && /^[0-9A-HJKMNP-TV-Z]{8}$/.test(labels[0]?.short_code ?? '') && labels[0]?.print_count === 0,
  expectSource: 'WorkerInboundService.postDraft → InboundLabelService.ensureLabels（§7.1 缺码不画假码）',
})
const post2 = await apiWorker('POST', `/api/worker/inbound/drafts/${draftId}/post`, {
  sessionId: A.sessionId, headers: { [IDEMPOTENCY_HEADER]: postKey }, body: { confirmed: true },
})
const stockAfterPost2 = stockOf(sku.sku_id)
judge(R, {
  id: 'D11.post-idempotent', name: '同 Idempotency-Key 重复过账 ⇒ 回放、**库存只加一次**',
  expect: `stock 仍 ${expectStock}`, actual: `HTTP ${post2.status} stock=${stockAfterPost2}`,
  pass: post2.status === 200 && cents(stockAfterPost2) === cents(expectStock),
  expectSource: 'ClientRequestIdService（ENDPOINT_POST）+ 条件更新 CAS 双保险',
})
// 无幂等键重复过账 ⇒ 409（CAS 挡）
const post3 = await apiWorker('POST', `/api/worker/inbound/drafts/${draftId}/post`, { sessionId: A.sessionId, body: { confirmed: true } })
const stockAfterPost3 = stockOf(sku.sku_id)
judge(R, {
  id: 'D12.post-repeat-cas', name: '同一草稿重复过账（**不带**幂等键）⇒ 409 且库存仍只加一次（CAS）',
  expect: 'HTTP 409 + stock 不变', actual: `HTTP ${post3.status} code=${post3.json?.error?.code} stock=${stockAfterPost3}`,
  pass: post3.status === 409 && cents(stockAfterPost3) === cents(expectStock),
  expectSource: 'InboundOrderService.post 的条件更新（CAS）—— WorkerInboundService 类注释逐字「第二次会得到 409 而不是回放结果」',
})

// ── ④ 建单/过账负例：数量与归属 ──
const badQty = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: A.sessionId, body: `{"productId":${JSON.stringify(sku.product_id)},"skuId":"${sku.sku_id}","quantity":"0"}`, raw: true, headers: { 'Content-Type': 'application/json' },
})
const manyDecimals = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: A.sessionId, body: `{"productId":${JSON.stringify(sku.product_id)},"skuId":"${sku.sku_id}","quantity":"1.23"}`, raw: true, headers: { 'Content-Type': 'application/json' },
})
judge(R, {
  id: 'D13.qty-validation', name: '数量准入：0 与两位小数 ⇒ 422 VALIDATION_ERROR（平台统一 422；口径唯一在 requireItemNumbers）',
  expect: 'both 422 VALIDATION_ERROR', actual: `zero=${badQty.status}/${badQty.json?.error?.code} 1.23=${manyDecimals.status}/${manyDecimals.json?.error?.code}`,
  pass: badQty.status === 422 && manyDecimals.status === 422,
  expectSource: 'InboundOrderService.requireItemNumbers（>0 且最多 1 位小数，显式拒绝不静默取整）—— 期望「400」是第一版判据过窄（假红），已按实测收敛',
  evidence: [`zero body=${JSON.stringify(badQty.json?.error ?? {}).slice(0, 200)}`, `1.23 body=${JSON.stringify(manyDecimals.json?.error ?? {}).slice(0, 200)}`],
})
const wrongSku = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: A.sessionId, body: `{"productId":${JSON.stringify(sku.product_id)},"skuId":${BigInt(sku.sku_id) + 77n},"quantity":"1"}`,
})
judge(R, {
  id: 'D14.sku-not-exist', name: 'skuId 不存在 ⇒ 4xx（400/404/409，不得 500、不得静默建品）',
  expect: 'HTTP 4xx', actual: `HTTP ${wrongSku.status} code=${wrongSku.json?.error?.code}`,
  pass: wrongSku.status >= 400 && wrongSku.status < 500,
  expectSource: 'WorkerInboundService → InboundOrderService 的 SKU 校验（设计 §5.2 逐字：不存在 ⇒ 400/409）',
})
const noSku = await apiWorker('POST', '/api/worker/inbound/drafts', { sessionId: A.sessionId, body: { productId: sku.product_id, quantity: '1' } })
judge(R, {
  id: 'D15.draft-needs-sku', name: '缺 skuId ⇒ 422 VALIDATION_ERROR（结构上只能提交既有 skuId ⇒ 不存在「服务端顺手建一个」的路径）',
  expect: 'HTTP 422', actual: `HTTP ${noSku.status} code=${noSku.json?.error?.code}`,
  pass: noSku.status === 422,
  expectSource: 'WorkerInboundService.createDraft：req.skuId==null ⇒ validationError（工人面改写成 400）',
})

// ── ⑤ 归属：**自己的草稿才能过账**（非本人 ⇒ 404，不泄露存在性）──
const draftBKey = idemKey('p3draftB')
const dB = await apiWorker('POST', '/api/worker/inbound/drafts', {
  sessionId: B.sessionId, headers: { [IDEMPOTENCY_HEADER]: draftBKey },
  body: `{"productId":${JSON.stringify(sku.product_id)},"skuId":"${sku.sku_id}","quantity":"1.0"}`, raw: true, headers: { 'Content-Type': 'application/json' },
})
const draftB = dB.json?.data?.draftId ?? null
const crossPost = draftB ? await apiWorker('POST', `/api/worker/inbound/drafts/${draftB}/post`, { sessionId: A.sessionId, body: { confirmed: true } }) : null
judge(R, {
  id: 'D16.only-owner-can-post', name: '🔴 别人建的草稿由 A 过账 ⇒ **404**（不是 403：不泄露存在性）且库存不动',
  expect: 'HTTP 404', actual: `B 建单=${dB.status}/${draftB} A 过账=${crossPost?.status}/${crossPost?.json?.error?.code}`,
  pass: !!draftB && crossPost?.status === 404,
  expectSource: 'WorkerInboundService.requireOwnDraft：created_by != operator ⇒ notFound(404)（设计 §5.2 逐字）',
})

// ── ⑥ 标签读面 + 打印留痕 ──
const shortCode = labels[0]?.short_code
const labelDetail = shortCode ? await apiWorker('GET', `/api/worker/inbound/labels/${shortCode}`, { sessionId: A.sessionId }) : null
judge(R, {
  id: 'D17.label-detail', name: 'GET /api/worker/inbound/labels/{短码} ⇒ 回单据业务详情（品名/色号/米数/供应商）',
  expect: 'HTTP 200 + 键集含 sku/quantity 类字段', actual: `HTTP ${labelDetail?.status} keys=${JSON.stringify(Object.keys(labelDetail?.json?.data ?? {}))}`,
  pass: labelDetail?.status === 200 && Object.keys(labelDetail.json?.data ?? {}).length > 0,
  expectSource: 'InboundLabelService.detail（短码 ⇒ 单据详情）',
})
const print1 = shortCode ? await apiWorker('POST', `/api/worker/inbound/labels/${shortCode}/print`, { sessionId: A.sessionId }) : null
const print2 = shortCode ? await apiWorker('POST', `/api/worker/inbound/labels/${shortCode}/print`, { sessionId: A.sessionId }) : null
const labelRow = shortCode ? one(`select short_code, print_count from inbound_labels where tenant_id=${TENANT_ID} and short_code='${shortCode}'`) : null
judge(R, {
  id: 'D18.print-count', name: 'POST labels/{短码}/print 两次 ⇒ print_count 原子自增到 2（打印必留痕）',
  expect: 'DB print_count=2', actual: `print1=${print1?.status} print2=${print2?.status} row=${JSON.stringify(labelRow)}`,
  pass: print1?.status === 200 && print2?.status === 200 && labelRow?.print_count === 2,
  expectSource: 'InboundLabelService.recordPrint（COALESCE(print_count,0)+1 原子自增；重打同样计数）',
})
const badLabel = await apiWorker('GET', '/api/worker/inbound/labels/ZZZZZZZZ', { sessionId: A.sessionId })
judge(R, {
  id: 'D19.label-unknown-404', name: '未知短码 ⇒ 404（不得 500、不得回落别的标签）',
  expect: 'HTTP 404', actual: `HTTP ${badLabel.status} code=${badLabel.json?.error?.code}`, pass: badLabel.status === 404,
  expectSource: 'WorkerInboundLabelController 类注释：跨租户/不存在 ⇒ 404（不是 403）',
})
const noAuthPrint = await apiWorker('POST', `/api/worker/inbound/labels/${shortCode}/print`, { sessionId: null })
judge(R, {
  id: 'D20.label-print-needs-session', name: '打印留痕无工人 session ⇒ 401（不记无名之痕）',
  expect: 'HTTP 401', actual: `HTTP ${noAuthPrint.status}`, pass: noAuthPrint.status === 401,
  expectSource: 'SecurityConfig `/api/worker/**` authenticated() + 控制器 requireWorker',
})

// ── ⑦ 跨租户：租户 20 的标签短码在**租户 21** 的请求上下文里必须摸不到 ──
//    注：短码全局唯一、`selectByShortCode` 绕过多租户拦截器 ⇒ 这条正是「靠服务端判」的判据点
const t21Label = one(`select l.short_code from inbound_labels l where l.tenant_id=21 and l.deleted=0 and l.short_code is not null limit 1`)
if (!t21Label) {
  R.skip('D21.cross-tenant-label', '跨租户标签读面（租户21 短码）', '租户 21 无标签短码夹具 ⇒ 未覆盖（不冒充已验）')
} else {
  const crossLabel = await apiWorker('GET', `/api/worker/inbound/labels/${t21Label.short_code}`, { sessionId: A.sessionId })
  judge(R, {
    id: 'D21.cross-tenant-label', name: '租户 20 的工人读**租户 21** 的标签短码 ⇒ 404（不得返回别家单据）',
    expect: 'HTTP 404', actual: `HTTP ${crossLabel.status} code=${crossLabel.json?.error?.code}`,
    pass: crossLabel.status === 404,
    expectSource: 'InboundLabelService.detail：按 tenant_id 查（短码全局唯一不代表可跨租户读）',
  })
}

writeFileSync(outPath('P3-inbound-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary(), probe: { skuId: sku.sku_id, productId: sku.product_id, draftId, draftB, shortCode } }, null, 2))
log(`P3 汇总: ${JSON.stringify(R.summary())}`)
process.exit(0)
