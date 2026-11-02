#!/usr/bin/env python3
# 线②（2026-10-04）—— 把「四态 counts / 更正后的 buildpoint / findings」写回 out/SUMMARY.json。
#
# 为什么需要它：`run-all.mjs` 每次收尾都会用各段 JSON **重新生成** SUMMARY.json（这是底座行为，
# 我们不改底座）；集成侧后来更正了被测构建点坐标（台账声称 ff655a06c，**行为实测 de614623d**，见 #6294），
# 而 findings（4 条现象 → 8 条 fail 的收敛）也不是底座脚本能生成的 ⇒ 用本脚本在收尾后**合并写回**。
# 用法：python3 harness/apply-summary.py out/SUMMARY.json
import json
import sys

f = sys.argv[1]
j = json.load(open(f))
items = {it["id"]: it for it in j["items"]}

findings = [
    {"id": "F1", "severity": "P1-candidate",
     "title": "售后工单并发完结 ⇒ 审计重复 + 退货回补库存重复生效（时间线 5 行/台账 4 行/库存 98→106）",
     "judges": [{"id": "LB-C2-CONCURRENT-RESOLVE", "verdict": "fail"},
                {"id": "LB-C21-CONCURRENT-SAME-TARGET", "verdict": "fail"},
                {"id": "LB-C22-CONCURRENT-CONFLICT", "verdict": "fail"},
                {"id": "LB-C23-CONCURRENT-RESOLVE-TIMELINE", "verdict": "fail"}],
     "minRepro": "SEGMENTS=p0,p1,p3,p4 API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 node acceptance/2026-10-04/aftersales-refund-sweep/harness/run-all.mjs —— 建探针商品(allow_return_restock=true,stock=100)+建单qty=2并PUT /orders/{id}/payment(实收300) → POST /after-sales{ticketType:return,refundAmount:300} → 工单转 processing → N=4 并发同时 PUT /after-sales/{tid}/status{status:resolved}",
     "willRed": "stock_ledger_entries(ref_no=工单号,reason=aftersales) 行数必须=1（实测4）；SKU 终值必须=回补前+明细数量（实测98→106）；ticket_timeline 中 to=resolved 行数必须=1（实测4）；并发同目标成功响应必须恰1（实测4/4全200）",
     "rootCauseSymbols": [
         "backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::updateTicketStatus（状态机校验读 selectById 内存旧值；落库 afterSalesTicketMapper.updateById(ticket)，WHERE 仅主键 id，无状态谓词）",
         "backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::maybeRestockOnReturn ⇒ OrderService.restoreStockForReturn ⇒ backend/admin-api/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java::restoreStock（UPDATE product_skus SET stock=COALESCE(stock,0)+#{quantity} WHERE id=#{skuId}，无幂等谓词）",
         "正对照 1（同一次完结的另一副作用有护栏）：AfterSalesTicketService::linkRefundToOrderAndFinance 的 setSql+WHERE COALESCE(refund_amount,0)+applied<=actual（实测退款未翻倍 300.00、流水1行）",
         "正对照 2（同仓更近范式）：OrderService::transitionStatusAtomic（带状态谓词条件更新 + rows==0⇒422；实测订单侧并发改状态恰1个赢家）"],
     "attribution5L": "现象层=并发完结致库存虚增6米+审计4行；接口层=PUT /api/admin/after-sales/{id}/status 对同工单无并发互斥（4/4全200）；实现层=updateById 缺状态谓词⇒校验基于陈旧内存值；类级层=同一服务内已有正确范式（退款封顶谓词）与订单CAS未复用；机制层=回补副作用无幂等键，未落到SQL",
     "evidence": [
         'out/B2-concurrency.json::records[LB-C2-CONCURRENT-RESOLVE].extra.rounds[0].dbFinal = {"ticketStatus":"resolved","refund_amount":300,"actual":300,"skuBefore":98,"skuAfter":106,"ledgerRows":4,"timelineRows":5,"financeRows":1}（三轮逐字相同）',
         "out/B2-concurrency.json::records[LB-C2-CONCURRENT-RESOLVE].extra.rounds[0].overlapEvidence.verdict=真重叠：最大逐对重叠 365ms（并集 459ms < 各历时之和 1336ms）",
         "out/B4-probe-batch.json::records[LB-C21-CONCURRENT-SAME-TARGET].detail=成功数=[4,4,4]；时间线读数=[4,4,4]",
         "out/B4-probe-batch.json::records[LB-C23-CONCURRENT-RESOLVE-TIMELINE].detail=成功数=[4,4,4]；时间线读数=[4,4,4]",
         'out/B4-probe-batch.json::records[LB-C22-CONCURRENT-CONFLICT].detail=成功数=[2,2,2]；DB 终态=["processing","closed","closed"]'],
     "postDeploy": {"status": "已随部署消失", "replayVerdict": "pass", "note": "升级 6838a0533 后同 harness 重放：C2/C21/C22/C23 全转 pass（B2-并发竞态 5/0、补强探针 11/0）"}, "buildScope": "老构建 de614623d 上实测存在；升级 6838a0533 后重放已消失（2026-10-04 09:30:44 +08 起）"},

    {"id": "F2", "severity": "P2-candidate",
     "title": "涉钱精度静默归零：refund_amount=0.001 ⇒ HTTP 200 但 orders.refund_amount=0 且仍写 refund_at",
     "judges": [{"id": "LB-PREC-02", "verdict": "fail"}, {"id": "LB-REF-B03", "verdict": "fail"}],
     "minRepro": "curl -X PUT https://api.migaozn.com/api/admin/orders/<探针已确认订单>/refund -H 'Content-Type: application/json' -b \"access_token=$TOKEN\" -d '{\"refund_reason\":\"精度探针\",\"refund_amount\":\"0.001\"}' ⇒ 200 {\"success\":true}；库内 refund_amount=0.00 且 refund_at 非空、流水1行 amount=0.00",
     "willRed": "0<x<0.01 的退款额必须 4xx 显式拒绝，且不得写 refund_at、不得写资金流水；不变式=orders.refund_amount 与 finance_transactions.amount 逐字相等",
     "rootCauseSymbols": [
         "backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java::refundOrder（只做 new BigDecimal(amount.toString().trim())，无精度准入）",
         "列类型：orders.refund_amount=numeric(12,2) / finance_transactions.amount=numeric(12,2) ⇒ 库内隐式舍入",
         "同系统既有「显式拒绝」范式：backend/admin-api/src/main/java/com/migao/admin/service/StockQuantity.java::requireOneDecimal、InboundOrderService::requireItemNumbers"],
     "attribution5L": "现象层=退0.001显示已退款而金额为0；接口层=非法精度未准入；实现层=金额侧无校验（数量侧有）；类级层=StockQuantity范式未在金额面复用；机制层=精度责任交给DB隐式舍入",
     "evidence": [
         "out/B5-refund-precision.json::LB-PREC-01 pass 0.01⇒订单0.01/流水0.01",
         "out/B5-refund-precision.json::LB-PREC-02 fail 200；orders.refund_amount=0；流水 1 行 amount=0；refund_at=set",
         "out/B5-refund-precision.json::LB-PREC-03 舍入方向登记 0.004⇒0/0；0.005⇒0.01/0.01；0.009⇒0.01/0.01",
         "out/B4-probe-batch.json::LB-REF-B03（独立复现）"],
     "postDeploy": {"status": "已随部署消失", "replayVerdict": "pass", "note": "升级后 B1-涉钱精度 3/0（PREC-02 / REF-B03 均转 pass）"}, "buildScope": "老构建 de614623d 上实测存在；升级 6838a0533 后重放已消失"},

    {"id": "F3", "severity": "P3-candidate",
     "title": "读面自相矛盾：列表端点 size<0 ⇒ HTTP 200 但 total=0 而返回整页（三端点均命中）",
     "judges": [{"id": "LB-C4-NEGATIVE-SIZE", "verdict": "fail"}],
     "minRepro": "curl -b \"access_token=$TOKEN\" \"https://api.migaozn.com/api/admin/orders?page=1&size=-5\" ⇒ 200 / total=0 / size=500 / items 非空",
     "willRed": "任意 200 的分页响应必须 items.length<=total；size<0 应 4xx 或归一化（回退默认20）且 total 保持真实",
     "rootCauseSymbols": [
         'backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java::getOrders（@RequestParam(defaultValue="1") long size，无下限校验）',
         "backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java::PaginationInnerInterceptor(setMaxLimit(500)) 只设上限"],
     "attribution5L": "现象层=按 total 驱动分页器/空态的调用方把有数据的页面当0条；接口层=参数无下限校验；实现层=非法入参下 total 与列表路径分叉；类级层=分页插件只设上限",
     "evidence": [
         "out/B4-probe-batch.json::LB-C4-NEGATIVE-SIZE.detail=[{label:orders,total:0,size:500,rows:44},{label:stock-ledger,total:0,size:500,rows:148},{label:after-sales,total:0,size:500,rows:20}]；不自洽点数=3"],
     "postDeploy": {"status": "已随部署消失", "replayVerdict": "pass", "note": "升级后补强探针 fail 0（C4-NEGATIVE-SIZE 转 pass）"}, "buildScope": "老构建 de614623d 上实测存在；升级 6838a0533 后重放已消失"},

    {"id": "F4", "severity": "P2-candidate",
     "title": "空租户「商品→订单→售后」链缺前置：本线命名域初始 0 个商品分类 ⇒ POST /api/admin/products（categoryId 必填）422 不可达",
     "judges": [{"id": "LB1-SETUP-category-gap", "verdict": "fail"}],
     "minRepro": "curl -X POST https://api.migaozn.com/api/admin/products -H 'Content-Type: application/json' -b \"access_token=$TOKEN\" -d '{\"name\":\"x\",\"unit\":\"米\",\"pricingType\":\"per_meter\",\"basePrice\":100,\"price\":100,\"stock\":100,\"status\":\"on_shelf\",\"colors\":[{\"colorName\":\"c\",\"mainColorHex\":\"#AABBCC\"}],\"doorWidths\":[\"2.8m\"]}' ⇒ 422 VALIDATION_ERROR「分类ID不能为空」",
     "willRed": "新租户（本线命名域内 categories 0 行）在不手工造分类的前提下，POST /api/admin/products 不得因缺服务端默认分类而 422；或入驻时种一个默认分类 / 422 文案给出可行动出口",
     "rootCauseSymbols": [
         "backend/admin-api/src/main/java/com/migao/admin/dto/ProductCreateRequest.java::categoryId（必填，服务端 createProduct 依赖）",
         "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java（入驻只种默认角色/权限/岗位，不种商品分类）"],
     "attribution5L": "现象层=空租户走API建不出首个商品；接口层=422文案只指「分类ID不能为空」不给出口；实现层=入驻无分类种子；类级层=「新租户可用性」缺端到端判据（本轮以空租户首跑才暴露）。⚠️ 归因强度限制：只断言「本租户本线命名域初始零分类⇒走API建商品缺前置」；能否由前端商品管理页自助建分类兜住不在本线射程（未做UI级验证）⇒ 不写更强归因",
     "evidence": [
         "out/B1-setup.json::LB1-SETUP-category-gap.detail=本线命名域（前缀「线B验收」）初始 active 分类数=0；经真实API补建后=1",
         "out/B1-fixtures.json::fixtures[*].resp 原始 422「分类ID不能为空」",
         "out/B1-category-gap.json::catsBefore=[] / catsForeign=线A验收链分类-*（别线，本线不触碰）"],
     "selfDisclosedHarnessDefect": "首版该判据查「全租户 active 分类」，当时租户内已有别线 4 条 线A验收链分类-* ⇒ 判据无判别力地变绿（本线自曝的假绿）；已改为只查本线前缀并重跑",
     "postDeploy": {"status": "仍开放", "replayVerdict": "fail", "note": "升级 6838a0533 后仍 fail（重放读数：本线命名域（前缀「ZR」）初始 active 分类数=0；经真实 API 补建探针分类后=1（HTTP 200））；与 #6295（main 上仍开放）一致 ⇒ 不是老构建伪影"}, "buildScope": "两条构建点（de614623d 与 main 6838a0533）上都成立 ⇒ 可上升到 main 现状层"},
]

counts = {k: j["counts"][k] for k in ("pass", "fail", "skip", "falseRed")}
counts["total"] = j["counts"]["total"]

j["line"] = "②售后退款"
j["counts"] = counts
j["buildpoint"] = {
    "behaviorMeasured": "de614623d",
    "behaviorMeasuredNote": "集成侧独立复现同一工单并发状态流转=[200,200,200,200]+副作用×4，而被测台账 SHA 的源码里 #6220 的原子条件更新本应给出 [200,409,409,409]；部署步远端输出逐字 PREV_GOOD_TAG=sha-de61462 且「❌ 磁盘可用 3998MB < 门槛 4096MB ⇒ 中止构建」⇒ 行为实测构建点 = de614623d（2026-10-02 10:22:50 UTC，落后 origin/main 152 个提交）",
    "deployLegClaimed": "ff655a06c",
    "deployLegNote": "部署台账声称 ff655a06c（deploy-admin-api.yml 最近一个 success 的 headSha，2026-10-03T21:47:10Z），但部署腿自 2026-10-03 起从未成功：近 80 条 deploy run 里 deploy=success 一条都没有，两条 success 出自 reconcile 的「跳过部署」路径（skip 不判绿 ⇒ 假绿）；已开单 #6294（P0·部署）",
    "readingSource": "https://api.migaozn.com（已部署面）",
    "localWorktree": {"path": "/Users/guangzhen.zk/migao-wt/main-live",
                      "shaFull": "43ca703221a714e143c468ff0b29c4a46e67a88f",
                      "note": "本地旧构建点，**读数不取自它**"},
    "scopeOfConclusions": "本线全部 fail 只能定性为「老构建 de614623d 上实测存在的缺陷」；不得归因为「main 上的缺陷」—— 对 origin/main 的结论需环境修复（#6294）后重跑。引用的源码符号属**台账声称构建点** ff655a06c，实际运行构建点早于它 ⇒ 同名符号不保证逐字一致，需复验",
}
j["findings"] = findings

# ── 升级后重放（集成侧原样重放本线 harness；证据 = replay-postdeploy/aftersales/SUMMARY.json + 20-aftersales-full.log）──
j["postDeployReplay"] = {
    "at": "2026-10-04 09:30:44 +08 起（环境切到 sha-6838a05 = main HEAD 6838a0533，#6294 已修）",
    "by": "集成侧（主会话）用本线 harness 原样重放；本线只做对照转录",
    "evidence": ["acceptance/2026-10-04/replay-postdeploy/aftersales/SUMMARY.json",
                 "acceptance/2026-10-04/replay-postdeploy/20-aftersales-full.log"],
    "before": {"buildpoint": "de614623d", "counts": {"pass": 51, "fail": 8, "skip": 3, "falseRed": 0, "total": 62}},
    "after": {"buildpoint": "6838a0533", "counts": {"pass": 57, "fail": 2, "skip": 3, "falseRed": 0, "total": 62}},
    "residualFails": [
        {"id": "LB0-01", "kind": "判据侧伪影（期望值过期，非产品缺陷）",
         "readout": "远端声明=(ADMIN_API_DEPLOYED_SHA 未设)；最后一个 success 部署=6838a0533 @ 2026-10-04T01:20:10Z（UTC）",
         "note": "本线 p0-env.mjs 写死 EXPECTED=ff655a06c（BRIEF 口径）⇒ 台账一变即红；**未**改判据去凑绿"},
        {"id": "LB1-SETUP-category-gap", "kind": "真读数（仍开放）",
         "readout": "本线命名域（前缀「ZR」）初始 active 分类数=0；经真实 API 补建探针分类后=1（HTTP 200）",
         "note": "与 #6295（main 上仍开放）一致 ⇒ F4 不是老构建伪影"}],
    "scopeNote": "重放支持「F1/F2/F3 是老构建上的缺陷、main 上已消失」（本线当初**未**将其归因给 main）；F4 两条构建点都成立 ⇒ 可上升到 main 现状层。本线仍不下「验收通过」结论",
    "segmentsFieldNote": "本 SUMMARY 的 segments 字段为 {}（收尾用 SKIP_RUN=1 重生成过一次，该档不跑段）；段级真相见 out/run-all.log 的 11 对 ▶/◀（均 ok，09:15:19–09:17:10 +08）",
}
notes = list(j.get("notes") or [])
notes += [
    "⚠️ 坐标更正（集成侧，2026-10-04 09:1x +08）：行为实测构建点 = de614623d（落后 main 152 提交）；台账声称 ff655a06c 但部署腿从未成功（#6294）⇒ 本线全部 fail 只定性为「老构建上实测存在的缺陷」",
    "凡 evidence 里引用的源码符号属**台账声称构建点** ff655a06c 的路径；不保证与实际运行构建点 de614623d 的同名符号逐字一致 ⇒ 需在环境升到 main 后复验",
    "收尾凭据：out/.token（临时管理员 token）由 run-all 收尾删除，打印 token 凭据已删=true",
]
j["notes"] = notes

json.dump(j, open(f, "w"), ensure_ascii=False, indent=2)
print("SUMMARY 合并写回：counts=%s | findings=%d | buildpoint=%s | postDeployReplay=%s" % (counts, len(findings), j["buildpoint"]["behaviorMeasured"], j["postDeployReplay"]["after"]))
