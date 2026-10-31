# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: aftersales（源: cases/aftersales.yml，16 条）

from ._schema import Difficulty, EvalCase, Skill

# ── AS-001 [SMOKE] 售后工单列表（源: cases/aftersales.yml）──
_CASE_AS_001 = EvalCase(
    id='AS-001',
    legacy_id='3.1',
    title='售后工单列表',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.SMOKE,
    user_inputs=['看看售后工单'],
    expectations=['after_sales_manage(action=list)'],
    data_checks=['工单列表含 ticketNo/状态'],
    skip_reason='',
    tags=['query', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-002 [NORMAL] 售后工单详情（源: cases/aftersales.yml）──
_CASE_AS_002 = EvalCase(
    id='AS-002',
    legacy_id='3.2',
    title='售后工单详情',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看一下 AS-20260914-9001 工单详情'],
    expectations=['after_sales_manage(action=detail)'],
    data_checks=['statusHistory 按时间正序，首条 status=pending'],
    skip_reason='',
    tags=['query', 'detail'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-003 [NORMAL] 查订单 → 创建退款工单（跨域复用 order_id）（源: cases/aftersales.yml）──
_CASE_AS_003 = EvalCase(
    id='AS-003',
    legacy_id='C002',
    title='查订单 → 创建退款工单（跨域复用 order_id）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查一下客户手机号 13800138000 最近的订单', '就刚才那笔订单，客户手机号 13800138000，要退货，创建售后工单', '确认创建', '确认', {'auto_respond': {'fallback': '确认创建'}}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['order_query', 'after_sales_manage'],
    data_checks=['success=true', '工单号匹配 ^AS-\\d{8}-\\d{4}$'],
    skip_reason='',
    tags=['cross_skill', 'context_share', 'create'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'aftersale_create', 'only_if_called': True}, {'tool': 'aftersale_create', 'source': 'metadata', 'only_if_called': True}],
    namespaces=['customer_phone:13800138000'],
    precondition=[{'type': 'order_count_for_phone', 'source': '13800138000'}],
)

# ── AS-004 [NORMAL] 查看售后工单（只读；原「更新工单状态-关闭」随 #5247 写能力下线改判）（源: cases/aftersales.yml）──
_CASE_AS_004 = EvalCase(
    id='AS-004',
    legacy_id='3.4',
    title='查看售后工单（只读；原「更新工单状态-关闭」随 #5247 写能力下线改判）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查看最近的售后工单'],
    expectations=['after_sales_manage(action=list)'],
    data_checks=['success=true', '如实说明工单状态变更（关闭）须在后台「售后」页面操作，并引导顾客去那里处理；**不得声称已关闭**（原「工单已关闭 / 状态已更新」的机器断言 db_verify[after_sales_ticket] 已随 #5247 写能力下线退役，理由见上方注释）'],
    skip_reason='',
    tags=['update', 'status'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'aftersales_ticket_prepare'}],
    precondition=[{'type': 'aftersales_ticket_count_for_ticket_no', 'source': 'AS-20260914-9001', 'expect': 1}],
)

# ── AS-005 [NORMAL] 售后处理全流程 - 查单→确认问题→建工单→跟踪（源: cases/aftersales.yml）──
_CASE_AS_005 = EvalCase(
    id='AS-005',
    legacy_id='M008',
    title='售后处理全流程 - 查单→确认问题→建工单→跟踪',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户张三说窗帘颜色不对，帮我查下他的订单', '最近那个订单，客户手机号 13800138000', '客户要退货，创建售后工单', '原因：颜色与图片不符，退款', '这工单现在什么状态了'],
    expectations=['order_query', 'after_sales_manage'],
    data_checks=['aftersale_create 的 order_id 来自第2步查询结果', '售后工单包含正确的退款原因'],
    skip_reason='',
    tags=['multi_turn', 'cross_skill', 'real_scenario'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'aftersale_create', 'only_if_called': True}],
    namespaces=['customer_phone:13800138000'],
    precondition=[{'type': 'order_count_for_phone', 'source': '13800138000'}],
)

# ── AS-006 [NORMAL] 售后工单退款/退货完结 - 按商品「退货回补库存」开关决定是否回补库存（源: cases/aftersales.yml）──
_CASE_AS_006 = EvalCase(
    id='AS-006',
    legacy_id='',
    title='售后工单退款/退货完结 - 按商品「退货回补库存」开关决定是否回补库存',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AS-20260701-0002 退款工单已处理完，完成'],
    expectations=['after_sales_manage(action=detail)'],
    data_checks=['refund/return 工单 resolved 时：订单全部商品 allow_return_restock=true 才恢复 SKU 库存；任一商品为 false 则整单不回补（窗帘定制退货不可再售）', 'allow_return_restock 默认 false；黄金策不得在售后完成后默认引导恢复库存/重新上架'],
    skip_reason='依赖生产不存在的固定测试工单 AS-20260701-0002（评测数据脱节）——回补库存逻辑已由 admin-api 单测覆盖（AfterSalesTicketServiceTest），LLM 行为待重构为自包含（先建工单再完结） ｜ 2026-09-24（issue #5247，用户裁定 2026-09-23 B 端只读化）：after_sales_manage 收窄为只读（写 action update_status / create 已删除）⇒ 写声明改判为 detail；must_succeed（指向写能力）删除；本用例保持退役。',
    tags=['update', 'status', 'cross_skill'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'aftersales_ticket_prepare'}],
    precondition=[{'type': 'aftersales_ticket_count_for_ticket_no', 'source': 'AS-20260701-0002', 'expect': 1}],
)

# ── AS-007 [NORMAL] 换货选目标商品后必须确认加工项（before 生成换货工单确认卡）（源: cases/aftersales.yml）──
_CASE_AS_007 = EvalCase(
    id='AS-007',
    legacy_id='',
    title='换货选目标商品后必须确认加工项（before 生成换货工单确认卡）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['面料有瑕疵，帮我换货', {'repeat_until': {'tool_called': 'order_query', 'max': 2}, 'fallback': '换成2699系列雪尼尔窗帘面料'}, '换成2699系列雪尼尔窗帘面料', {'repeat_until': {'tool_called': 'after_sales_manage', 'max': 5}, 'fallback': '好的'}],
    expectations=['order_query', 'product_detail'],
    data_checks=['换货目标商品的**店铺加工项目录**（processing_item_query，与商品无关：#4371 解耦后 product_detail 不再返回 processing_items）非空时，confirm 卡之前必须主动询问加工项（interact(choice, multiSelect=true)，透传 pageMeta 支持翻页；文本询问亦可，语义由 order_before 保证）', '用户选择加工项后，所选名称与计价写入换货方案汇总与工单 description；用户说『不需要加工项』才跳过', '店铺加工项目录为空时才如实告知『暂无可用加工项』后继续，不强求', '换货工单 order_id 来自本轮 order_query 定位结果（不得编造订单号）'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「换货（after_sales_manage 写面）」（after_sales_manage action=create）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为「查订单 + 查商品详情（order_query / product_detail）+ 如实说明换货须在后台「售后」页面操作」。',
    tags=['exchange', 'processing_item', 'guided_flow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['order_query before after_sales_manage', 'processing_ask before after_sales_manage', 'processing_ask before interact[confirm]'],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '2699系列雪尼尔窗帘面料', 'price': 23.8}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '2699系列雪尼尔窗帘面料', 'expect': 1}],
)

# ── AS-008 [NORMAL] C 端售后进度查询 - 仅限本人工单 + 拒绝跨用户/快递单号式越权查询（源: cases/aftersales.yml）──
_CASE_AS_008 = EvalCase(
    id='AS-008',
    legacy_id='',
    title='C 端售后进度查询 - 仅限本人工单 + 拒绝跨用户/快递单号式越权查询',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我上次申请的售后处理得怎么样了'],
    expectations=['aftersale_query'],
    data_checks=['aftersale_query 无用户/租户参数，后端强制按当前登录顾客过滤（/api/admin/agent/after-sales/mine 同构）——顾客无法通过任何参数读取他人工单', 'list 返回当前顾客工单（含 status 标签与 timeline）；无工单时如实告知『暂无售后记录』，不编造工单号/状态', 'status 可筛选（pending/processing/resolved/rejected/closed），非法值不静默当成全部', '与 B 端 after_sales_manage 物理隔离：元元无 after_sales_manage 工具，不得出现管理端动作（改状态/退款/回补库存）'],
    skip_reason='',
    tags=['query', 'aftersale', 'data_safety', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_args=[{'tool': 'aftersale_query', 'fields': ['user_id', 'customer_id', 'customer_phone']}],
)

# ── AS-009 [NORMAL] C 端售后进度正向查询 - 工具可达 + 能力不否定（权限类禁词）（源: cases/aftersales.yml）──
_CASE_AS_009 = EvalCase(
    id='AS-009',
    legacy_id='',
    title='C 端售后进度正向查询 - 工具可达 + 能力不否定（权限类禁词）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我上次申请的那个换货单现在处理到哪一步了'],
    expectations=['aftersale_query'],
    data_checks=['正向可达性：aftersale_query 被调用（expectation 机器断言）；回复不得出现『没有权限/无权限』（forbidden_text 机器断言，防 #3477 类能力自我否定在售后域的对应）', '状态 grounded 到本人真实工单，无工单时如实说明（不禁『暂无』——诚实正确行为）'],
    skip_reason='',
    tags=['query', 'aftersale'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['没有权限', '无权限'],
)

# ── AS-010 [EDGE] 同会话同键重试建工单 —— 第二次是幂等回放（replayed=true），落库工单恰好一张（源: cases/aftersales.yml）──
_CASE_AS_010 = EvalCase(
    id='AS-010',
    legacy_id='',
    title='同会话同键重试建工单 —— 第二次是幂等回放（replayed=true），落库工单恰好一张',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['订单 EVAL-ORD-0001 的窗帘颜色和图片不符，我要退货，帮我建个售后工单', {'auto_respond': {'fallback': '确认创建'}}, {'auto_respond': {'fallback': '确认'}}, {'retry_same_session': {'tool': 'aftersale_create', 'calls': 2, 'max': 3}, 'fallback': '我这边页面提示『提交失败，请重试』，你帮我把刚才那个售后工单再提交一次，内容不用改'}],
    expectations=['aftersale_create'],
    data_checks=['**同键只落一张工单**（机器断言 db_verify[after_sales_by_client_request_id]，expect_rows=1 + expect_replayed=true）：判据 = 同一会话 + 至少一次 `replayed=true`（服务端 `ClientRequestIdService.replay` 只在同键命中时置位）+ 全部成功调用指向**同一张工单**。', '**回放可见**（机器断言 output_verify[aftersale_create, last]）：第二次调用返回 replayed=true，顾客看到的仍是**同一个工单号**，不得播报成「又建了一张」。', '**可达性（红证方向）**：模型只口头声称已重发、实际没有第二次成功的 aftersale_create ⇒ must_succeed[min_successes=2] 判红（不是绿）。', '⚠️ 与 dup-guard 的区别（别把两件事混成一件）：`aftersales-flow.dup-guard` 治的是「同订单同类型已有活跃工单 ⇒ 422」这条**业务规则**；本用例治的是**同一次逻辑写请求被重发**时的**同键回放**（在 claim 层就被挡下、`replayed=true`，不会走到 dup-guard 的 422）。两者都要在，缺任何一条都会让另一条看起来像坏了。', '⚠️ 形态边界（如实登记）：与 OR-049 同 —— 「服务端已落库但 HTTP 客户端超时」需要故障注入（当前无此能力），本用例用「顾客转述页面提示提交失败、要求原样再提交」这一行为层可复现的重试形态作代理，不是等价物。'],
    skip_reason='',
    tags=['aftersale_create', 'idempotency', 'retry'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['interact[confirm] before aftersale_create'],
    must_succeed=[{'tool': 'aftersale_create', 'min_successes': 2}],
    db_verify=[{'fetch': 'after_sales_by_client_request_id', 'source': 'aftersale_create', 'expect_rows': 1, 'expect_replayed': True}],
    output_verify=[{'tool': 'aftersale_create', 'last': True, 'expect': {'replayed': True}}],
    namespaces=['customer_phone:13800138000'],
    precondition=[{'type': 'order_count_for_phone', 'source': '13800138000'}],
)

# ── AS-011 [EDGE] 售后工单并发完结（N=4 同一 processing 工单）—— 恰一个赢家、库存只回补一次、台账恰 1 行（issue #6220）（源: cases/aftersales.yml）──
_CASE_AS_011 = EvalCase(
    id='AS-011',
    legacy_id='',
    title='售后工单并发完结（N=4 同一 processing 工单）—— 恰一个赢家、库存只回补一次、台账恰 1 行（issue #6220）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['两个管理员同时点了「完结」（或一个人在慢网络下双击）：把 AS-6220-R1 这张退货工单完结掉'],
    expectations=['after_sales_manage(action=detail)'],
    data_checks=['**并发完结恰一个赢家**（机器断言 = admin-api 真库并发单测 AfterSalesConcurrentResolveRealDbTest，CI job `admin-api-test`）：N=4 并发同一 processing 工单 → 成功数 1，其余 3 个返回 409「工单状态已被他人变更」；重复 3 轮三轮都必须成立（缺陷时序敏感，单轮会因调度侥幸变绿）。', '**副作用只执行一次**（同一判据的另外三条读数）：`product_skus.stock` 增量 == 单次回补量（订单明细数量，独立算式，不得用被测读面当期望）；`stock_ledger_entries` 该 ref_no 恰 1 行；`ticket_timeline` 的 status_change 恰 2 行（pending→processing + processing→resolved）。修前读数 = 成功数 4 / 库存 98→106 / 台账 4 行 / 时间线 5 行。', '**正对照（护栏不误杀）**：单个请求串行完结必须成功（199 谓词里的 tenant_id 非空、正常流转不被 409 误杀）；同一事务里的退款联动（linkRefundToOrderAndFinance）修前修后都 == 单次金额 300（证明判据有判别力，不是什么都判不出来）。', '**行为契约不回退**：pending→{processing,rejected,closed}、processing→{resolved,closed}、终态不可变、pending→closed（#3541）、closed/rejected 记 closed_at、internal_notes 追加不覆盖、中文业务文案 —— 由 AfterSalesTicketServiceTest 同批守住。'],
    skip_reason='[backend-contract] 本用例判的是 **admin-api 服务层的并发写面**（B 端 HTTP 直连 PUT /api/admin/after-sales/{id}/status，不经黄金策 Agent）；而 after_sales_manage 的写 action 已于 #5247（用户裁定 2026-09-23 B 端只读化）从源码删除 ⇒ **Agent 面没有可跑的写路径**，评测栈里无法复现「两个管理员同时完结」。机器判据改由 admin-api 真库并发单测承载（traces.tests，CI job `admin-api-test`，重复 3 轮）：见 AfterSalesConcurrentResolveRealDbTest（case_ids: AS-011）。**这不是「没有判据」** —— 该单测先跑出修前红（成功数 4 / 库存 98→106 / 台账 4 行 / 时间线 5 行）再跑出修后绿（成功数 1 / +2 / 1 行 / 2 行），成对读数见 PR body。',
    tags=['update', 'status', 'concurrency'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-012 [EDGE] 类级元守卫：同一事务里「状态写 + 多个副作用」的方法必须逐个登记并发保护（未登记即红）（源: cases/aftersales.yml）──
_CASE_AS_012 = EvalCase(
    id='AS-012',
    legacy_id='',
    title='类级元守卫：同一事务里「状态写 + 多个副作用」的方法必须逐个登记并发保护（未登记即红）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['（无 Agent 面输入 —— 本用例是研发侧类级守卫，防「同一事务里只保护了其中一个副作用」的形态再进来）'],
    expectations=['after_sales_manage(action=detail)'],
    data_checks=['**未登记即红**（机器断言 = AfterSalesSideEffectConcurrencyMetaGuardTest，CI job `admin-api-test`）：`src/main/java/com/migao/admin/service/*.java` 里满足「@Transactional ∧ 体内 setStatus( ∧ ≥2 处 mapper/service 副作用调用」的方法（现取 10 个）必须逐个出现在台账 `entries`（已保护 + 兑现锚）或 `unverified`（豁免 + 理由 + 重启条件）里。', '**豁免台账只许缩短 + 条数现取**：`unverified` 必须是冻结基线 `unverified_baseline` 的子集（新增豁免 ⇒ 红）；条数不写死在测试代码里（读数打印在守卫输出上：现取候选=10 / 已保护=1 / 豁免=9 / 豁免基线=9）。', '**登记必须兑现**：`entries[].evidence` = `<仓库相对全路径>::<文本锚>`，锚必须在该文件里逐字存在 ⇒ 把条件更新退回无条件 updateById 时本判据与 AS-011 同时红（不许留假章）。', '**判别力自证**：合成语料上「未登记 / 未兑现 / 新增豁免 / 豁免缺理由 / 扫描器失明」五种坏形态各自判红、合规语料判绿（防「判据恒绿」与「判据有效」在输出上分不开）。'],
    skip_reason='[backend-contract] 研发侧类级守卫（源码形态扫描 + 台账判定），**没有 Agent 面可跑**（不吃 user_inputs、也不产生对话行为）；承载体 = admin-api 单测 AfterSalesSideEffectConcurrencyMetaGuardTest（case_ids: AS-012，CI job `admin-api-test`）。形态判据不做 AST 解析（换措辞可绕过）⇒ 真实防线仍是 AS-011 的行为面，本守卫只保证「同类形态进来时当场撞红」。',
    tags=['status', 'concurrency', 'meta_guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-013 [EDGE] 涉钱入口退款金额超 2 位小数 ⇒ 4xx 显式拒绝（不静默取整）：订单与资金流水零写入、refund_at 不写（源: cases/aftersales.yml）──
_CASE_AS_013 = EvalCase(
    id='AS-013',
    legacy_id='',
    title='涉钱入口退款金额超 2 位小数 ⇒ 4xx 显式拒绝（不静默取整）：订单与资金流水零写入、refund_at 不写',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['PUT /api/admin/orders/{id}/refund body {refund_amount:0.001}（子分级金额）'],
    expectations=[],
    data_checks=['**0.001 ⇒ 4xx 显式拒绝**（机器断言 = `backend/admin-api/src/test/java/com/migao/admin/service/OrderRefundMoneyPrecisionTest.java` 的 refundOrder_threeDecimals_isRejectedWithNoWrites / refundEndpoint_threeDecimals_is4xx）：HTTP 422 + 文案含「最多支持 2 位小数」。修前实测 = 200 且库内被 PG 舍成 0。', '**零写入**（同上两条断言）：拒绝时 `orders` 不落 refund_amount / refund_at、`finance_transactions` 零新增 —— 修前是「订单与流水两处同时静默归零、refund_at 却已写入」。', '**正对照 0.01 不退化**（断言 = refundOrder_oneCent_succeedsWithBothSidesLiterallyEqual）：200 且订单侧写库字面量与流水侧金额**逐字相等**（`0.01` 就是 `0.01`）。', '**既有两个守卫未回退**（断言 = refundOrder_accumulatedCapUnchanged / refundOrder_statusWhitelistUnchanged）：累计退款封顶实收、状态白名单（confirmed/producing/shipped/completed）一字未动。', '**舍入方向登记（不作缺陷判据）**：PG `numeric(·,2)` 是半进位，修前实测 0.004⇒0 / 0.005⇒0.01 / 0.009⇒0.01（issue #6221 逐字读数）；这三个值修后一律被拒（断言 = MoneyScaleTest.registeredRoundingDirection_isPgHalfUp_andSubCentValuesAreNowRejected）。'],
    skip_reason='[backend-contract] 涉钱金额小数位准入由 Java 单测验证（MoneyScaleTest / OrderRefundMoneyPrecisionTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['refund', 'money-precision', 'fail-closed', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-014 [EDGE] 类级：全仓金额入口小数位准入台账（金额写面未登记即红、豁免台账只许缩短）（源: cases/aftersales.yml）──
_CASE_AS_014 = EvalCase(
    id='AS-014',
    legacy_id='',
    title='类级：全仓金额入口小数位准入台账（金额写面未登记即红、豁免台账只许缩短）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['在未登记的文件里新增一处写入 NUMERIC(·,2) 金额列的写面（或新增一个金额列）'],
    expectations=[],
    data_checks=['**未登记即红**（机器断言 = `backend/admin-api/src/test/java/com/migao/admin/service/MoneyEntryPrecisionMetaGuardTest.java` 的 everyMoneyEntryIsRegisteredAndBacked）：发现规则（实体 BigDecimal 金额字段的 setter 调用点 + 金额实体 builder 调用点）扫出的每一处写面都必须在入口台账里 ⇒ 新写面未登记即具名红。', '**台账不许空转**（断言 = redproof_staleLedgerEntry）：登记的写面被删/改名 ⇒ 红（防「台账留着好看、写面早没了」）。', '**登记未被兑现即红**（断言 = redproof_gatedClaimWithoutGateText）：登记为已过准入但文件里没有 MoneyScale 调用文本 ⇒ 红。', '**豁免只许缩短**（断言 = redproof_debtGrowth / liveDebtCountDoesNotExceedFrozenBaseline）：无准入的写面登记为债务且必须带跟进 issue 号，条数现取 ≤ 冻结上限；新增缺口只能落准入、不能塞进台账。', '**判别力自证 + 反向对照**（断言 = redproof_* 七条 + cleanFixture_hasNoViolation）：六种坏形态各自在内存里判红；同一夹具不注入 ⇒ 零违规（证明红由注入引起）。', '**扫描面非空**（断言 = scanSurfaceIsNotEmpty / redproof_emptyScanFailsClosed）：发现规则失效（扫不到任何金额写面）⇒ fail-closed 红，不许「空跑成绿」。'],
    skip_reason='[backend-contract] 类级元守卫是纯源码扫描 + 内存注入判据，由 Java 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['money-precision', 'meta-guard', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-015 [EDGE] 售后工单详情/列表响应不再携带恒空的 refundMethod 键（三个 Java 载体上字段/getter/setter 全无；键不存在而非值为 null）（源: cases/aftersales.yml）──
_CASE_AS_015 = EvalCase(
    id='AS-015',
    legacy_id='',
    title='售后工单详情/列表响应不再携带恒空的 refundMethod 键（三个 Java 载体上字段/getter/setter 全无；键不存在而非值为 null）',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.EDGE,
    user_inputs=['GET /api/admin/after-sales（列表）与 GET /api/admin/after-sales/{id}（详情）—— 响应体里不得出现 refundMethod 键'],
    expectations=[],
    data_checks=['**形状判据（加回去即红）**（机器断言 = backend/admin-api/src/test/java/com/migao/admin/controller/AfterSalesRefundMethodRetiredTest.java 的 refundMethodIsGoneFromEveryJavaCarrier）：实体 AfterSalesTicket + 列表/详情两个响应 DTO 上不得再有 refundMethod 字段，也不得有 getRefundMethod / setRefundMethod。反射判据与 Jackson 的 null 策略无关 ⇒ 把字段加回去 ⇒ 当场红。', '**线上响应判据（键不存在，不是值为 null）**（断言 = listResponseCarriesNoRefundMethodKey / detailResponseCarriesNoRefundMethodKey）：真走一次列表与详情（MockMvc + mock 服务）⇒ 响应体里不得出现 refundMethod 键；同时给正对照（同一份响应里 ticketNo / refundAmount 在），证明读到的是那份真响应而不是空壳。', '**修后实测读数**：本包落库时该测试类 Tests run: 3, Failures: 0, Errors: 0；修前红用注入式红证取（把 refundMethod 加回 types + 三个 Java 载体 ⇒ 形状判据与元守卫同时具名红）。', '**类级元守卫（铁律 8）**：本字段所属的「前端 types 声明、后端零生产者」族由 backend/admin-api/src/test/java/com/migao/admin/contract/FrontendUnionFieldProducerMetaGuardTest.java 承担（未登记即红 / 台账只许缩短 / 扫描面为空 fail-closed）。', '**射程边界（照实登记）**：MockMvc 走 standaloneSetup ⇒ 默认 Jackson 会序列化 null，比线上（spring.jackson.default-property-inclusion: non_null）更严；本判据不断言 DB 列被删（列无写者无读者即无害，删列是破坏性迁移，不在本包内）。'],
    skip_reason='[backend-contract] 售后响应契约下线由 Java 单测验证（AfterSalesRefundMethodRetiredTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['refund', 'dead-field', 'response-contract', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── AS-016 [NORMAL] 售后如实引导：客户说窗帘收到时有破洞 → 先查那单 + 说清后台怎么走，不承诺代办（源: cases/aftersales.yml）──
_CASE_AS_016 = EvalCase(
    id='AS-016',
    legacy_id='',
    title='售后如实引导：客户说窗帘收到时有破洞 → 先查那单 + 说清后台怎么走，不承诺代办',
    skill=Skill.AFTERSALES,
    difficulty=Difficulty.NORMAL,
    user_inputs=['张三那单收到的窗帘布边上有个破洞，这怎么处理？'],
    expectations=['order_query or customer_manage'],
    data_checks=['前置（precondition）：订单夹具 `EVAL-MB-ORD-0001` 在库且客户名为「张三」（success=true；真值 = tests/agent_eval/fixtures/mibao_eval_seed.sql 的订单 INSERT 块）', '必须先**真的查**（order_query 按客户名/订单号定位张三的单，或 customer_manage 查档案），不得凭空说「已为您登记」', '售后**写面**已随 #5247 只读化下线 ⇒ 回复必须引导后台「售后」页面自行处理，且不得承诺代办（机器断言 = forbidden_text）'],
    skip_reason='',
    tags=['aftersales', 'journey', 'capability-boundary'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['已为您提交售后', '已帮您申请售后', '已登记售后'],
    precondition='前置 = 客户「张三」名下有夹具订单（`EVAL-MB-ORD-0001/0002`，customer_name=张三 / 13800138000，见 mibao_eval_seed.sql 的订单夹具块）；前置不成立 ⇒ agent 查不到单、判红会伪装成「不会处理售后」',
)

CASES = (
    _CASE_AS_001,
    _CASE_AS_002,
    _CASE_AS_003,
    _CASE_AS_004,
    _CASE_AS_005,
    _CASE_AS_006,
    _CASE_AS_007,
    _CASE_AS_008,
    _CASE_AS_009,
    _CASE_AS_010,
    _CASE_AS_011,
    _CASE_AS_012,
    _CASE_AS_013,
    _CASE_AS_014,
    _CASE_AS_015,
    _CASE_AS_016,
)
