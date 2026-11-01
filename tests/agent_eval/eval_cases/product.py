# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: product（源: cases/product.yml，133 条）

from ._schema import Difficulty, EvalCase, Skill

# ── PR-001 [SMOKE] 商品搜索 - 关键词模糊匹配（源: cases/product.yml）──
_CASE_PR_001 = EvalCase(
    id='PR-001',
    legacy_id='P001',
    title='商品搜索 - 关键词模糊匹配',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.SMOKE,
    user_inputs=['搜索遮光窗帘'],
    expectations=['product_search(keyword=遮光窗帘)'],
    data_checks=['搜索必须真的返回商品（机器断言见 output_verify：products 非空）—— 原 `data.products.length > 0` 不计分，已弃用'],
    skip_reason='',
    tags=['search', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    output_verify=[{'tool': 'product_search', 'expect': {'products': '__nonempty__'}}],
)

# ── PR-002 [NORMAL] 商品搜索 - 按库存状态筛选（源: cases/product.yml）──
_CASE_PR_002 = EvalCase(
    id='PR-002',
    legacy_id='2.2',
    title='商品搜索 - 按库存状态筛选',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['有哪些缺货的商品'],
    expectations=['product_search(stock_status=out_of_stock)'],
    data_checks=['「缺货商品」查询必须真的按库存过滤（机器断言见 output_verify：total == 0，= 种子无库存≤0 商品的可判定事实；过滤被忽略 ⇒ total>0 ⇒ 判红）—— 原 `data.products.length >= 0` 恒真且不计分，已弃用'],
    skip_reason='',
    tags=['search', 'filter'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    output_verify=[{'tool': 'product_search', 'expect': {'total': 0}}],
)

# ── PR-003 [SMOKE] 商品详情 - 通过名称查询（ID 解析）（源: cases/product.yml）──
_CASE_PR_003 = EvalCase(
    id='PR-003',
    legacy_id='P002',
    title='商品详情 - 通过名称查询（ID 解析）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.SMOKE,
    user_inputs=['查看遮光窗帘的详细信息'],
    expectations=['product_detail(product_id=遮光窗帘)'],
    data_checks=['data.name.length > 0', 'data.skus.length > 0', '前置（precondition）：名字含「遮光窗帘」的商品恰好 1 件（`pre_clean[product_dedupe]` 先于基线捕获执行；计数口径与 `_probe_product_count` 共用 `_list_products_matching` = 服务端 keyword 模糊匹配 + 客户端精确子串，§18 单一真相源）—— R1 按**名字**定位商品，唯一性是它真正依赖且**只读**的前置；名字 >1 件时 agent 合理地反问「要查看哪一件」（choice 卡），期望 `product_detail(product_id=遮光窗帘)` 必然落空 ⇒ 判红会伪装成「agent 不会查商品详情」（**归因全错**）。前置不成立时报告落 `precondition[product_count_for_keyword]`（**不可归因于 agent**），不落行为失败。'],
    skip_reason='',
    tags=['detail', 'id_resolve', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-004 [NORMAL] 查库存（源: cases/product.yml）──
_CASE_PR_004 = EvalCase(
    id='PR-004',
    legacy_id='2.4',
    title='查库存',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['遮光窗帘还有多少库存'],
    expectations=['inventory_manage(action=query)'],
    data_checks=['库存数量 = SUM(SKU 库存)'],
    skip_reason='',
    tags=['inventory', 'query'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-005 [NORMAL] 查库存台账与入库批次（只读；原「调整库存-出库」随 #5247 写能力下线改判）（源: cases/product.yml）──
_CASE_PR_005 = EvalCase(
    id='PR-005',
    legacy_id='2.5',
    title='查库存台账与入库批次（只读；原「调整库存-出库」随 #5247 写能力下线改判）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查一下遮光窗帘最近的库存流水（出入库记录）', '再看看这批货是哪几张入库单入的库'],
    expectations=['stock_ledger_query', 'inbound_order_query(action=batches)'],
    data_checks=['只读：回复里不得出现任何「已调整库存/已出库/已入库」的表述（B 端无写能力，#5247）', '库存流水/入库批次逐值来自服务端（`stock_ledger_query` / `inbound_order_query`），不得自行编造数量或批次号'],
    skip_reason='',
    tags=['inventory', 'write'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-006 [NORMAL] 低库存预警（源: cases/product.yml）──
_CASE_PR_006 = EvalCase(
    id='PR-006',
    legacy_id='2.6',
    title='低库存预警',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看看哪些商品库存不足'],
    expectations=['inventory_manage(action=low_stock_alert) or product_search(stock_status=low_stock)'],
    data_checks=['报告的低库存商品数 = 该路径工具返回的条数（product_search: data.products/total；inventory_manage: data.count）—— 数值必须有据，不得凭空给数（本 run 实测 4=4）', '阈值口径必须与所用工具一致：product_search 分支 = ≤100（库存≤100，与后台低库存口径一致）；inventory_manage 分支 = threshold（默认 100 —— 与 product_search 同一单点来源 app/tools/stock_semantics.py，见 #3783）', '给出的数字必须能指回该工具返回的明细（不得只给个总数而不列商品）'],
    skip_reason='',
    tags=['inventory', 'alert'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'inventory_manage or product_search'}],
)

# ── PR-007 [NORMAL] 商品上架（状态流转）（源: cases/product.yml）──
_CASE_PR_007 = EvalCase(
    id='PR-007',
    legacy_id='2.7',
    title='商品上架（状态流转）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘下架', {'auto_respond': {'fallback': '确认'}}, '再把它上架', {'auto_respond': {'fallback': '确认'}}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['direct_reply'],
    data_checks=['success=true'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「商品上架/下架状态流转」（product_manage(action=toggle_status)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['status', 'write'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    post_clean=[{'type': 'product_status_restore', 'product_keyword': '遮光窗帘'}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-008 [NORMAL] 创建商品 - 完整流程（源: cases/product.yml）──
_CASE_PR_008 = EvalCase(
    id='PR-008',
    legacy_id='P003',
    title='创建商品 - 完整流程',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['创建一个窗帘，名称测试窗帘A，价格168，分类选窗帘', '窗帘布艺', '颜色选白色和灰色', '货号用 TEST-CURTAIN-A', {'auto_respond': {'fallback': '确认创建测试窗帘A'}}],
    expectations=['direct_reply'],
    data_checks=['只读 + 如实说明：回复不得谎称已创建商品，须说明 B 端黄金策不做创建并引导去后台「商品管理」页面操作（原「商品真的被创建」断言随写能力下线改判）'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「创建商品完整流程」（product_manage(action=create)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['create', 'full_flow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_remove', 'product_keyword': '测试窗帘A'}],
    namespaces=['product_name:测试窗帘A'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '测试窗帘A', 'expect': 0, 'max_growth': 1}],
)

# ── PR-009 [ADVERSARIAL] 商品更新 - 名称解析 ID（源: cases/product.yml）──
_CASE_PR_009 = EvalCase(
    id='PR-009',
    legacy_id='P007',
    title='商品更新 - 名称解析 ID',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.ADVERSARIAL,
    user_inputs=['把遮光窗帘的价格改成 199', {'repeat_until': {'tool_called': 'product_update', 'max': 3}, 'fallback': '确认'}],
    expectations=['product_update(product_id=遮光窗帘, price=199)'],
    data_checks=['success=true', '改价前必须先发 confirm 卡展示「改前 → 改后」（机器断言见 order_before[...]；改前价真值取自 product_detail 返回，不得凭记忆编造）'],
    skip_reason='',
    tags=['id_resolve', 'update'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['interact[confirm] before product_update'],
    required_args=[{'tool': 'product_update', 'fields': ['product_id', 'price', 'before_price']}],
    must_succeed=[{'tool': 'product_update'}],
    post_clean=[{'type': 'product_price_restore', 'product_keyword': '遮光窗帘', 'price': 168}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-010 [NORMAL] 商品多轮链路 - 搜索→查看详情→改价→复核（原「改价验证」；#5247 只读化期间改判为查询链路，#5303 按 A 档裁定补回）（源: cases/product.yml）──
_CASE_PR_010 = EvalCase(
    id='PR-010',
    legacy_id='M001',
    title='商品多轮链路 - 搜索→查看详情→改价→复核（原「改价验证」；#5247 只读化期间改判为查询链路，#5303 按 A 档裁定补回）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['搜索遮光窗帘', '看看遮光窗帘的详情', '把价格改成 198', {'repeat_until': {'tool_called': 'product_update', 'max': 3}, 'fallback': '确认'}, '再看看这个商品的详情确认一下'],
    expectations=['product_search', 'product_detail(product_id=复用上轮 UUID)', 'product_update(price=198)', 'product_detail(product_id=复用上轮 UUID)'],
    data_checks=['第3轮 product_id 来自第2轮（详情）结果 —— 改价复用同一 UUID、不重新解析商品', '全程未重新 product_search 查同一个商品', '改价前必须先发 confirm 卡展示「改前 → 改后」（机器断言见 order_before[...]），改完的复核轮读到的是新价'],
    skip_reason='',
    tags=['multi_turn', 'single_skill', 'full_lifecycle', 'id_reuse', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['interact[confirm] before product_update'],
    required_args=[{'tool': 'product_update', 'fields': ['product_id', 'price', 'before_price']}],
    must_succeed=[{'tool': 'product_update'}],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    post_clean=[{'type': 'product_price_restore', 'product_keyword': '遮光窗帘', 'price': 168}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-011 [NORMAL] 创建商品完整引导流程 - AI 主导收集信息（源: cases/product.yml）──
_CASE_PR_011 = EvalCase(
    id='PR-011',
    legacy_id='M002',
    title='创建商品完整引导流程 - AI 主导收集信息',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我要创建一个新商品', '名称叫E2E引导建品样品帘，价格 168', '分类选窗帘', {'auto_select': True}, '颜色有米白和浅灰', '货号用 SUMMER-BREEZE', '确认创建，没问题', '确认'],
    expectations=['direct_reply'],
    data_checks=['创建的加工项数量 = 0（#4371 解耦：建品不再关联加工项）', '全程 AI 主动引导，不等待用户逐项输入'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「创建商品完整引导流程 - AI 主导收集信息」（product_manage(action=create)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['multi_turn', 'guided_flow', 'full_create', 'processing_item'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_remove', 'product_keyword': 'E2E引导建品样品帘'}],
    namespaces=['product_name:E2E引导建品样品帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': 'E2E引导建品样品帘', 'expect': 0, 'max_growth': 1}],
)

# ── PR-012 [NORMAL] 商品创建中途修改 - 用户纠偏（源: cases/product.yml）──
_CASE_PR_012 = EvalCase(
    id='PR-012',
    legacy_id='M003',
    title='商品创建中途修改 - 用户纠偏',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['创建商品，名称测试窗帘，价格 100', '分类选窗帘', '窗帘布艺', '等等，价格改成 200', '颜色白色，货号 TEST-001', '确认创建'],
    expectations=['direct_reply'],
    data_checks=['只读 + 如实说明：回复不得谎称已创建/已改价，须说明 B 端黄金策不做创建并引导去后台「商品管理」页面操作'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「商品创建中途修改 - 用户纠偏」（product_manage(action=create)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['multi_turn', 'correction', 'mid_flow_change'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    namespaces=['product_name:测试窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '测试窗帘', 'expect': 0, 'max_growth': 1}],
)

# ── PR-013 [NORMAL] 窗帘算料报价 - 褶皱倍数与用布量计算（源: cases/product.yml）──
_CASE_PR_013 = EvalCase(
    id='PR-013',
    legacy_id='',
    title='窗帘算料报价 - 褶皱倍数与用布量计算',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['3米宽 2.5米高 2倍褶皱 打孔帘 用98元一米的遮光布 帮我算多少钱'],
    expectations=['curtain_calc(window_width=3, window_height=2.5)'],
    data_checks=['data.fabric_meters > 0', 'data.total > 0'],
    skip_reason='',
    tags=['quote', 'fabric_calc', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-017 [NORMAL] 商品创建/更新/详情透传「退货回补库存」开关（allow_return_restock）（源: cases/product.yml）──
_CASE_PR_017 = EvalCase(
    id='PR-017',
    legacy_id='',
    title='商品创建/更新/详情透传「退货回补库存」开关（allow_return_restock）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘设置成退货后可以回补库存', {'auto_respond': {'fallback': '确认'}}],
    expectations=['product_detail'],
    data_checks=['如实说明：退货回补库存开关（allowReturnRestock）的修改须在后台「商品管理」页面操作 —— B 端黄金策只读、不代改；开关当前值可经商品详情读出（只读核对）'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「退货回补库存开关（allow_return_restock）的写能力」（product_update / product_manage）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 商品详情只读核对 + 如实说明 + 引导去后台页面。本用例不再进 agent-eval 冒烟（写能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['inventory', 'write', 'cross_skill'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-018 [NORMAL] B端黄金策 product_list 卡片引用对齐 — 只渲染回复文本中实际引用的商品（源: cases/product.yml）──
_CASE_PR_018 = EvalCase(
    id='PR-018',
    legacy_id='',
    title='B端黄金策 product_list 卡片引用对齐 — 只渲染回复文本中实际引用的商品',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查一下低库存商品的具体清单'],
    expectations=['inventory_manage(action=low_stock_alert) or product_search(stock_status=low_stock)'],
    data_checks=['黄金策（agent_type=mibao）回复中：product_list 卡片仅包含文本实际引用的商品（按商品名/ID 匹配），未被引用的商品不渲染', '文本未引用任何商品时不下发 product_list 卡片（宁可无卡，不误导）', '元元（agent_type=xiaobu）保持现状：product_search 结果全量渲染卡片（货架浏览体验不回退）'],
    skip_reason='',
    tags=['card', 'reference_alignment', 'mibao'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'inventory_manage or product_search'}],
)

# ── PR-019 [NORMAL] 建品规格落库 — 推理属性经 specifications 落库（加工项部分已随 #4371 解耦删除）（源: cases/product.yml）──
_CASE_PR_019 = EvalCase(
    id='PR-019',
    legacy_id='',
    title='建品规格落库 — 推理属性经 specifications 落库（加工项部分已随 #4371 解耦删除）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[{'text': '根据这张图片录入商品（色卡图，可识别材质/克重）', 'images': ['https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com/images/2026/09/04/e5a68d1a02f844c6a45846784765a737.jpg']}, {'auto_respond': {'fallback': '商品名称: E2E色卡建品样品面料\n单价(元/米): 23.8\n颜色: 2699-01本白\n门幅: 2.8米\n售卖方式: 散剪\n货号: XNE2699', 'form_values': {'name': 'E2E色卡建品样品面料', 'price': '23.8', 'colors': '2699-01本白', 'door_widths': '2.8米', 'selling_methods': '散剪', 'sku_code': 'XNE2699'}}}, {'auto_respond': {'fallback': '商品名称: E2E色卡建品样品面料；单价(元/米): 23.8；颜色: 2699-01本白；门幅: 2.8米；售卖方式: 散剪；货号: XNE2699；确认创建'}}],
    expectations=['direct_reply'],
    data_checks=['只读 + 如实说明：不得谎称已创建/已落库规格，须说明 B 端黄金策不做创建并引导去后台「商品管理」页面操作（机器断言见 forbidden_tools）'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「色卡图建品的规格落库」（product_manage(action=create)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['product_create', 'specifications', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['尚未真正创建', '未创建成功'],
    forbidden_tools=[{'tool': 'product_manage', 'action': 'create'}],
    pre_clean=[{'type': 'product_remove', 'product_keyword': 'E2E色卡建品样品面料'}],
    namespaces=['product_name:E2E色卡建品样品面料'],
    precondition=[{'type': 'product_count_for_keyword', 'source': 'E2E色卡建品样品面料', 'expect': 0, 'max_growth': 1}],
    auto_fill={'name': 'E2E色卡建品样品面料', 'price': '23.8', 'colors': '2699-01本白', 'door_widths': '2.8米', 'selling_methods': '散剪', 'sku_code': 'XNE2699'},
)

# ── PR-021 [NORMAL] 单独 SKU 调价 - 修改某规格价格（#5247 只读化期间改判为只读核对，#5303 按 A 档裁定补回）（源: cases/product.yml）──
_CASE_PR_021 = EvalCase(
    id='PR-021',
    legacy_id='',
    title='单独 SKU 调价 - 修改某规格价格（#5247 只读化期间改判为只读核对，#5303 按 A 档裁定补回）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘的米白色散剪规格改成 150 元', {'auto_select': True}, {'repeat_until': {'tool_called': 'sku_update', 'max': 3}, 'fallback': '确认'}],
    expectations=['product_detail', 'sku_update'],
    data_checks=['sku_update 真成功且价格为 150 元（= 用户明确给出/确认的价）：机器断言见 must_succeed（写成功）+ output_verify（new_price==150）；裸断言「调用过」不算覆盖（#3544 假绿升级）', '改价前必须先发 confirm 卡展示「改前 → 改后」（机器断言见 order_before[...]；改前价取自 product_detail 的 skus[].price 真值）'],
    skip_reason='',
    tags=['sku', 'write', 'pricing'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['interact[confirm] before sku_update'],
    required_args=[{'tool': 'sku_update', 'fields': ['product_id', 'price', 'before_price']}],
    must_succeed=[{'tool': 'sku_update'}],
    output_verify=[{'tool': 'sku_update', 'expect': {'new_price': 150}}],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    post_clean=[{'type': 'sku_price_restore', 'product_keyword': '遮光窗帘', 'color_name': '米白', 'selling_method': 'bulk_cut', 'door_width': '2.8', 'price': 168}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-024 [NORMAL] 元元算料上限 - 定宽布买高 + 对花损耗（窗高超定高上限，必须走定宽分支并告警）（源: cases/product.yml）──
_CASE_PR_024 = EvalCase(
    id='PR-024',
    legacy_id='',
    title='元元算料上限 - 定宽布买高 + 对花损耗（窗高超定高上限，必须走定宽分支并告警）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['帮我算一下：窗宽 3 米、窗高 2.7 米，2 倍褶皱，门幅 2.8 米，需要对花（花距 40 厘米），用 98 元一米的布，要多少布、多少钱？'],
    expectations=['curtain_calc(window_width=3, window_height=2.7)'],
    data_checks=['窗高 2.7m + 卷边 0.3m > 门幅 2.8m → 必须走定宽布（买高）分支，不得套定高公式', '对花损耗按每幅 +1 个花距：3 幅 × 0.4m = 1.2m，用布 10.2m（非 9.0m）', '报价总额 = 面料费 + 加工费 + 辅料费 + 安装费（fabric-calc.quote-total），不得凭记忆报价'],
    skip_reason='',
    tags=['quote', 'fabric_calc', 'ceiling', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    output_verify=[{'tool': 'curtain_calc', 'expect': {'fabric_meters': 10.2, 'formula_used': 'fixed_width', 'warning': '__nonempty__', 'fullness': 2}}],
)

# ── PR-025 [NORMAL] B端写操作必须先出确认卡再执行（缺卡不发写）（源: cases/product.yml）──
_CASE_PR_025 = EvalCase(
    id='PR-025',
    legacy_id='',
    title='B端写操作必须先出确认卡再执行（缺卡不发写）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘下架', {'auto_respond': {'fallback': '确认'}}, '把它重新上架', {'auto_respond': {'fallback': '确认'}}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['direct_reply'],
    data_checks=['写能力已下线（#5247）⇒ 不再有写确认卡：须如实说明「黄金策只做数据查询与分析，不做上下架/创建类操作」并引导去后台「商品管理」页面操作，不得谎称已执行'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「B 端写操作必须先出确认卡再执行」（product_manage(action=toggle_status)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（写能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['write', 'confirm'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    post_clean=[{'type': 'product_status_restore', 'product_keyword': '遮光窗帘'}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-026 [NORMAL] 设置商品主图 - product_manage(action=update, images) 成功路径（源: cases/product.yml）──
_CASE_PR_026 = EvalCase(
    id='PR-026',
    legacy_id='',
    title='设置商品主图 - product_manage(action=update, images) 成功路径',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[{'text': '把遮光窗帘的主图设成这张色卡图', 'images': ['https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com/images/2026/09/04/e5a68d1a02f844c6a45846784765a737.jpg']}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['direct_reply'],
    data_checks=['只读 + 如实说明：不得谎称已设置主图/已更新图片，须说明 B 端黄金策不做主图写入并引导去后台「商品管理」页面操作'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「设置商品主图成功路径」（product_manage(action=update, images)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）。本用例不再进 agent-eval 冒烟（写能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['image', 'write'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-027 [NORMAL] 设主图能力不误宣 - 回复不得出现「不包含图片上传/拿不到地址」类能力否定（源: cases/product.yml）──
_CASE_PR_027 = EvalCase(
    id='PR-027',
    legacy_id='',
    title='设主图能力不误宣 - 回复不得出现「不包含图片上传/拿不到地址」类能力否定',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[{'text': '把遮光窗帘的主图设成这张色卡图', 'images': ['https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com/images/2026/09/04/e5a68d1a02f844c6a45846784765a737.jpg']}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['direct_reply'],
    data_checks=['如实说明：B 端黄金策不写主图（能力已随 #5247 下线），须引导去后台「商品管理」页面操作；且不得出现「已为您设置主图/主图已更新/设置成功」类谎称已执行的措辞（机器断言见 forbidden_text）'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「设主图能力不误宣」（product_manage(action=update, images)）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为 如实说明 + 引导去后台页面（direct_reply）+ 禁止谎称已执行（forbidden_text 改判）。本用例不再进 agent-eval 冒烟（写能力已下线、无对象）：B 端只读化是**源码静态事实**（工具声明 / skill 绑定 / 能力文案），由零依赖静态判据承担 —— tests/unit_ci_workflows/test_mibao_b_end_readonly.py（随 #5247 落地的 MC-021）。',
    tags=['image', 'write', 'capability_denial'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['已为您设置主图', '已设置主图', '主图已更新', '设置成功'],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    namespaces=['product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── PR-029 [NORMAL] 入库单建单：草稿态**不动库存**（不生成批次号、不落台账、不加库存）（源: cases/product.yml）──
_CASE_PR_029 = EvalCase(
    id='PR-029',
    legacy_id='',
    title='入库单建单：草稿态**不动库存**（不生成批次号、不落台账、不加库存）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['建单只写单据+明细（含货号/颜色/门幅快照），状态 draft；receiveStock / stock_ledger 写入 / 批次台账**均不得**被调用'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-030 [NORMAL] 入库单过账：自动生成批次号 + 自动加库存 + 落台账 + 落批次台账（含缸号）（源: cases/product.yml）──
_CASE_PR_030 = EvalCase(
    id='PR-030',
    legacy_id='',
    title='入库单过账：自动生成批次号 + 自动加库存 + 落台账 + 落批次台账（含缸号）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['过账一次性完成四件事：批次号 PC-yyyyMMdd-NNNN 回写明细行、receiveStock 加库存、stock_ledger_entries 记 reason=inbound 且 before/after 与成本快照齐备、stock_batches 记批次（带 dye_lot）；状态转 posted 并留痕操作人'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-031 [NORMAL] 入库单过账幂等闸与作废边界：已过账不得重复过账、不得作废（源: cases/product.yml）──
_CASE_PR_031 = EvalCase(
    id='PR-031',
    legacy_id='',
    title='入库单过账幂等闸与作废边界：已过账不得重复过账、不得作废',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['draft→posted 只允许一次（重复过账被拒且不二次加库存）；posted 的单作废被拒（库存已进台账，冲销须另开单据）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-032 [NORMAL] 入库单建单校验：数量**大于 0 米**且**最多 1 位小数**、单价 >0、SKU 必须属于该商品（源: cases/product.yml）──
_CASE_PR_032 = EvalCase(
    id='PR-032',
    legacy_id='',
    title='入库单建单校验：数量**大于 0 米**且**最多 1 位小数**、单价 >0、SKU 必须属于该商品',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['数量 0 / 负数被拒（下限 = **大于 0 米**：issue #5153 起由「≥1 米」放宽，0.5 米的实物尾料可如实登记 —— 见 PR-061/PR-062）；**超过 1 位小数**（如 2.755）被**显式拒绝**且文案说明 0.1 米粒度（V115/#5063 起入库量支持 1 位小数，**不静默取整**成 2.8；放宽下限**不连带**放宽精度）；单价 ≤0 被拒（不记单价请留空）；SKU 与商品不匹配被拒（否则库存会加到别的货号上）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-033 [NORMAL] 移动加权平均成本：有库存按加权、首次入库取进价、未记单价保持原值、未知不猜 0（源: cases/product.yml）──
_CASE_PR_033 = EvalCase(
    id='PR-033',
    legacy_id='',
    title='移动加权平均成本：有库存按加权、首次入库取进价、未记单价保持原值、未知不猜 0',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['(5×10+30×12.5)/35 = 11.4286；before_qty=0 或 before_avg 未知 ⇒ 均价 = 本次进价；unitCost=null ⇒ 均价保持原值；全程无成本信息 ⇒ NULL（不得变成 0）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-034 [NORMAL] 入库单动作端点只认 post / cancel（未知 action 拒绝且不调服务）（源: cases/product.yml）──
_CASE_PR_034 = EvalCase(
    id='PR-034',
    legacy_id='',
    title='入库单动作端点只认 post / cancel（未知 action 拒绝且不调服务）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['PATCH /api/admin/inbound-orders/{id} 的 action 白名单 = {post, cancel}；未知动作抛校验错误（fail-closed：静默什么都不做会让调用方以为过账成功）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-035 [NORMAL] 入库单列表/建单透传当前租户（跨租户读 = 数据泄漏）（源: cases/product.yml）──
_CASE_PR_035 = EvalCase(
    id='PR-035',
    legacy_id='',
    title='入库单列表/建单透传当前租户（跨租户读 = 数据泄漏）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['list 与 create 均以 TenantContext 的 tenantId 调服务；无认证上下文时操作人退化为 system（不写 null、不抛异常）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-036 [NORMAL] V111 迁移契约：幂等 + 存量成本留 NULL + reason 放行 inbound + schema.sql 同步（源: cases/product.yml）──
_CASE_PR_036 = EvalCase(
    id='PR-036',
    legacy_id='',
    title='V111 迁移契约：幂等 + 存量成本留 NULL + reason 放行 inbound + schema.sql 同步',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['迁移显式 BEGIN/COMMIT、DDL 全带 IF NOT EXISTS / pg_constraint 守卫；**不得**给 avg_cost/cost_amount 回填 0（0 是假真值）；reason CHECK 必须放行 inbound；docs/sql/schema.sql 同步终态（三张新表 + 成本列 + 两个唯一索引）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-037 [NORMAL] 入库单页面：列表/建单/过账动线可达（建单 = 独立整页 /inbound-orders/new），数量越界（0）与超精度提交前即被挡住（源: cases/product.yml）──
_CASE_PR_037 = EvalCase(
    id='PR-037',
    legacy_id='',
    title='入库单页面：列表/建单/过账动线可达（建单 = 独立整页 /inbound-orders/new），数量越界（0）与超精度提交前即被挡住',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['页面渲染列表（单号/状态/行数·总数量/**批次号列**）；建单入口**导航到独立整页** `/inbound-orders/new`（issue #5844：不再是弹窗），整页按「一行 = 一个批次」提交明细（含数量/单价/缸号/卷长），明细有「批次号」列且草稿态为「过账后生成」（草稿不发号）；数量 **0** 与超 1 位小数在**提交前**被挡（不调建单接口）—— 下限自 issue #5153 起为「大于 0 米」，**0.5 米可通过**（见 PR-062）；列表批次号列：已过账显示真值、草稿「过账后生成」、作废「-」、多批次「首个 等 N 个」；详情草稿显示「过账后生成」且有过账按钮，过账后显示批次号且过账/作废入口消失；详情明细有「卷长(米)」列（1 卷 = 多少米，原值直读 —— `58.55` 就是 `58.55`，**不得**套用库存米数的 0.1 米粒度格式化器渲染成 `58.6`；未填 ⇒ `-`，不写 0）；🔴 **2026-10-01 追加（issue #5904）**：建单明细里的 `skuId` 是**雪花号字符串**（实测 `2097126615461462018` ≈ 2.1e18 > JS 的 2^53）⇒ 提交体里必须**逐字原样**，**不得**被 `Number()` 截断（截断后服务端查不到该 SKU，建单恒失败：「商品明细第 1 项的 SKU 不属于该商品」）；判据 = `frontend/admin-web/tests/unit/pages/inbound-orders-new.test.tsx` 的「#5904 靶心」用例（用真实量级 id）+ 源码面元守卫 `frontend/admin-web/tests/unit/lib/snowflake-id-not-number.test.ts`（`Number()/parseInt()/parseFloat()` 作用在 `.id` 上即红，未登记即红）', '🔴 **2026-10-24 追加（issue #7644，用户报障）**：建单明细新增「卷数」一格 ⇒ 卷数 + 卷长（每卷米数）两者齐备时，**数量（米）自动 = 卷数 × 卷长**且该格只读（换算式 `1 卷 × 70 米` 显示在格下），提交的仍是**米数**（服务端契约与 #5034「卷长仅记录」一字不动）；卷数留空 = 按米手填（散剪 / 尾料，payload 与改前逐字相同）；卷数必须是**正整数**（0.5 ⇒ 显式拒绝）；卷数 × 卷长不是 0.1 米粒度（1 × 67.25）⇒ 显式拒绝、**不静默取整**。判据 = `frontend/admin-web/tests/unit/pages/inbound-orders-new.test.tsx` 的「按卷录入：卷数 × 卷长 ⇒ 数量（米）自动换算（issue #7644）」5 条（含负控：卷数留空 payload 逐字不变）', '🔴 **2026-10-25 追加（issue #7709，用户报障 + 裁定「不要按入库单的数量来算库存，得按实际米数」）**：换算的**权威改到服务端** —— 建单 payload 带 `rollCount`（卷数原样提交，格下那行米数只是**预览**、不进库存），服务端按 **卷数 × 卷长** 算 `inbound_order_items.quantity`（恒为米数、0.1 米粒度 fail-closed；**有卷数时随行的 quantity 一律不采信**）。入库单明细由单列「卷长(米)」改为 **卷数 / 卷长(米/卷) / 入库米数(米)** 三列（入库米数 = 服务端算好的 `meters`，前端不自己乘一遍）；库存流水的列名标明单位「米」。红证（改前必红，两次注入实测）：把服务端换算换回「数量即米数」⇒ `InboundOrderServiceTest.purchaseRollsBecomeMeters` 报 `expected: 70` 失败（实得 1）、`forcedPhotoOrderStoresRollCountAndMeters` 报 `expected: 67.2` 失败；把前端 payload 里的 `rollCount` 摘掉 ⇒ `inbound-orders-new.test.tsx` 的「卷数 1 + 卷长 70 ⇒ payload 带 rollCount=1」失败。判据 = `backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderServiceTest.java` 的 `RollMetersSemantics` 8 条（换算 / 0.1 米粒度拒绝 / 历史拍照行读面兼容 / 建单 / 过账的批次·库存·台账都为 70 / 卷数非法拒绝 / 不可伪造 photo / 工人单卷数映射）+ `frontend/admin-web/tests/unit/pages/inbound-orders.test.tsx`（三列逐格，含「历史行 quantity=1 必须显示 70」）+ `inbound-orders-new.test.tsx`（payload 带 rollCount、负控 rollCount=null）+ `stock-ledger.test.tsx`（列名带「米」）。边界（如实登记）：**历史数据一律不动**（用户 2026-10-25 裁定「历史一律不动，只修以后」）⇒ 已按 1 米过账的批次 / 流水 / 库存保持原值，由用户在「批次盘点」里按实盘修正（`manual` + 「库存盘点：」口径）；历史工人拍照单的明细行「数量」仍存的是卷数，读面由服务端 `storedMeters` 还原成米数、**不回填**'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-038 [NORMAL] 入库单菜单三处同构：config/menu.ts、MenuController、AuthService 同路径同权限码同图标（源: cases/product.yml）──
_CASE_PR_038 = EvalCase(
    id='PR-038',
    legacy_id='',
    title='入库单菜单三处同构：config/menu.ts、MenuController、AuthService 同路径同权限码同图标',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在后台建入库单、过账、查批次与库存台账（非 LLM 行为，由 Java 单测/前端组件测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['三份源文件都含入库单节点，path=/inbound-orders、permissionCode=inbound:view、icon=PackageOpen；MenuController 的节点真的挂进菜单树；权限码不得挪用 processing:manage —— 🔴 **2026-09-23 补判据（issue #5271 拆组）**：该节点必须落在 **`inventory-center`「仓储与物料」组**内（组名逐字、组 key 与组顺序三源一致），**不在** `production-center`「生产管理」组内（#5271 前它挂在生产管理组 ⇒ 旧散文与 `List.of(...)` 里指向 `production` 组的组断言**已作废**）；同组另两项 = 余料台账 `/production/remnants`、省料看板 `/production/saving-board`（均 `processing:manage`）。红证：把入库单节点挪回生产管理组 / 组 key 只改一处 ⇒ `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`（#5271 起比对**全树**：组 key + 组名 + 组顺序 + 导航型节点名）与 `MenuControllerTest`（仓储与物料组 = 入库单 / 余料台账 / 省料看板 三项，codes = `inbound:view` / `processing:manage` / `processing:manage`）判红；`inbound-menu-isomorphic.test.ts` 的组断言（② 的 `List.of(...)` 所在组）**须为** `inventory-center` —— 仍指 `production` 即红'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与 admin-web 组件测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-039 [NORMAL] 入库单实体/Mapper 三源收敛：Java 实体 ↔ V111 迁移 ↔ docs/sql/schema.sql（源: cases/product.yml）──
_CASE_PR_039 = EvalCase(
    id='PR-039',
    legacy_id='',
    title='入库单实体/Mapper 三源收敛：Java 实体 ↔ V111 迁移 ↔ docs/sql/schema.sql',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单的实体/Mapper/SQL 契约（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['inbound_orders / inbound_order_items / stock_batches 三张表的表名映射、字段清单、id 生成策略（ASSIGN_UUID vs IDENTITY AUTO）、软删 @TableLogic 全部与 V111 迁移列一一对齐；批次号与缸号必须是**两列**（合并会逼系统编缸号 = 假真值）；批次号租户内唯一索引必须在'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-040 [NORMAL] 入库单列表聚合读面 SQL 契约：租户隔离 + 软删过滤 + 聚合口径 + 别名对齐（源: cases/product.yml）──
_CASE_PR_040 = EvalCase(
    id='PR-040',
    legacy_id='',
    title='入库单列表聚合读面 SQL 契约：租户隔离 + 软删过滤 + 聚合口径 + 别名对齐',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单的实体/Mapper/SQL 契约（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['手写 SQL 必须有 o.tenant_id = #{tenantId} 与 o.deleted = 0；行数/总量聚合子查询也必须限定 deleted = 0（否则软删明细虚增「行数/总数量」）；必须有 LIMIT；列别名与 InboundOrderLine 属性名逐一对齐（别名写错时 MyBatis 不报错、字段静默为 null）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-041 [NORMAL] ProductSkuMapper 入库扩展契约：按 id 定位 + 均价单源 + 成本未知留 NULL（源: cases/product.yml）──
_CASE_PR_041 = EvalCase(
    id='PR-041',
    legacy_id='',
    title='ProductSkuMapper 入库扩展契约：按 id 定位 + 均价单源 + 成本未知留 NULL',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单的实体/Mapper/SQL 契约（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['receiveStock 只按 id 定位（不得用颜色/门幅组合条件更新）；加库存+写均价+记批次号一条 SQL 完成；SQL 里**不得**出现加权平均公式（公式只有 InboundOrderService.movingAverage 一处实现，两份实现必然漂移）；成本未知时 cost_amount 留 NULL（不用 0 冒充「成本为零」）；既有 deductStock/restoreStock 未被改坏'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-042 [NORMAL] SKU 组合只有 颜色 × 门幅 —— 售卖方式不是 SKU 维度（DB 唯一键 + 三端读写面）（源: cases/product.yml）──
_CASE_PR_042 = EvalCase(
    id='PR-042',
    legacy_id='',
    title='SKU 组合只有 颜色 × 门幅 —— 售卖方式不是 SKU 维度（DB 唯一键 + 三端读写面）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**唯一键只有两维**：`product_skus` 的组合约束逐字为 `UNIQUE (product_id, color_id, door_width)`；`product_skus.selling_method` 列**已不存在**（`information_schema.columns` 查不到 ⇒ 迁移 V108 的终态对账会抛）。注入：把 `selling_method` 加回唯一键 ⇒ 断言红。', '判据 2·**建品只按颜色×门幅生成**：`ProductService.saveColorsAndSkus` 的笛卡尔积是 `colors × doorWidths`（原 `colors × sellingMethods × doorWidths`）——注入：把 sellingMethods 放回积 ⇒ 生成行数 = 颜色×售卖方式×门幅 ≠ 颜色×门幅 ⇒ 断言红。', '判据 3·**SKU 定位键族不含售卖方式**：`OrderService.matchSkuId` 的 `colorId+doorWidth` / `colorName+doorWidth` 两族即可唯一定位（原 `+sellingMethod` 那一维已删）；`order_items.processing_info` 里历史单残留的 `sellingMethod` 键**不得**再参与 SKU 定位（注入：把它加回 where 条件 ⇒ 同色同门幅的历史单定位不到 SKU ⇒ 断言红）。', '判据 4·**存量去重可复算**：同 `(product_id,color_id,door_width)` 的旧多行（散剪一行/整卷一行）收敛为**价格最低**那一行，同价取 `id` 最小 —— 两遍执行保留同一行（幂等可断言）。', '判据 5·**迁移必须能在真库上真的跑起来**（回填不得引用不存在的列）：`product_skus` **没有** `deleted` 列（删除走 `deleteById` = 物理删除）⇒ 回填写 `AND deleted = 0` 会让真库抛「字段 deleted 不存在」、整份迁移回滚，而 `MigrationRunner` 对非连接类失败是**跳过并继续** ⇒ 部署 success、三列永不建（#4402 同族）。**本单第一版正是这个缺陷，且测试夹具自己给该表补了 `deleted` ⇒ 夹具把真缺陷挡掉了**（独立对抗式复核实测抓到）。⇒ 真库判据的 `_DDL` 必须与真 schema **逐列一致**，并有静态断言钉住「回填里不得出现 `deleted`」。'],
    skip_reason='[backend-contract] 商品模型改造的后端契约（迁移 + Java 单测，无 LLM 环节，不进 agent-eval 冒烟）：断言由 tests/unit_ci_workflows/test_product_roll_length_migration.py、backend/admin-api/src/test/java/com/migao/admin/service/ProductServiceTest.java 与 OrderStockSkuKeyFamilyTest.java 执行',
    tags=['product', 'sku_matrix', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-043 [NORMAL] 售卖方式 = 商品级基础属性（products.selling_methods），非 SKU 组合维度（源: cases/product.yml）──
_CASE_PR_043 = EvalCase(
    id='PR-043',
    legacy_id='',
    title='售卖方式 = 商品级基础属性（products.selling_methods），非 SKU 组合维度',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**落商品列**：`products.selling_methods`（JSONB 数组，取值 `bulk_cut` / `full_roll`）是售卖方式的**唯一**载体；`product_skus` 不得有该列。注入：把该列建到 `product_skus` ⇒ PR-042 判据 1 红。', '判据 2·**回填取旧数据真值**：迁移把该货号 SKU 里真实出现过的售卖方式去重回填（不是无脑默认）；一个 SKU 都没有的货号回填 `["bulk_cut","full_roll"]`（最宽口径，不误禁商家已有售卖方式）。', '判据 3·**读面契约**：商品详情响应 `sellingMethods` 取自商品列（不再是「从 SKU 派生」）——注入：把读面改回从 SKU 派生 ⇒ 该字段恒空 ⇒ 断言红。', '判据 4·**订单侧校验锚点**：订单行 `selling_method` 必须属于该货号 `products.selling_methods`（越界 ⇒ 显式拒绝，不静默落库）。'],
    skip_reason='[backend-contract] 商品基础属性契约（迁移 + Java 单测，无 LLM 环节，不进 agent-eval 冒烟）：断言由 tests/unit_ci_workflows/test_product_roll_length_migration.py 与 backend/admin-api/src/test/java/com/migao/admin/service/ProductServiceTest.java 执行',
    tags=['product', 'selling_method', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-044 [NORMAL] 商品「1 卷 = 多少米」= 货号级基础参数（roll_length_m），未配置禁止推算（源: cases/product.yml）──
_CASE_PR_044 = EvalCase(
    id='PR-044',
    legacy_id='',
    title='商品「1 卷 = 多少米」= 货号级基础参数（roll_length_m），未配置禁止推算',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**货号级一列**：`products.roll_length_m NUMERIC(8,2)`（可空、**不设默认值**）。注入：给它加 `DEFAULT 60` ⇒ 「未配置」这一档从库里消失 ⇒ 断言红。', '判据 2·**NULL = 未知，禁止推算**：`ProductRollAllocation.allocate(qty, null)` / `(qty, <=0)` 一律返回未分配（`rollCount == null`，三字段全 null）——不得用任何兜底常量算出一个看似合理的分配（行业卷长是区间值，见 docs/curtain-selling-method-industry-research.md §5）。', '判据 3·**读面契约**：商品详情/编辑表单读得到 `rollLengthM`（product_detail / 商品编辑页回显），写入走 `rollLengthM`。🔴 2026-10-01（issue #5919）：**只改展示文案**（标称口径，见判据 5）—— 字段名 / 提交载荷 / 存储与派生方式**一字未动**。', '判据 4·**边界语义**：`quantity < rollLength` ⇒ `rollCount = 0` 且余量 = 全部数量（「0 整卷 + 全部散剪」是**真实结论**，与「未分配 null」不是一回事）；恰好整卷倍数 ⇒ 余量 `0`（不是 null）。', '判据 5·**两处展示文案同源 + 标称口径**（issue #5919；2026-10-01 用户裁定「只改文案，不动数据模型」）：字段标签在商品表单（frontend/admin-web/src/components/products/ProductForm.tsx 的 `FieldRow`）与商品详情页（frontend/admin-web/src/app/(dashboard)/products/[id]/ProductDetail.tsx 的 `dt`，仍是**只读**展示）**逐字一致**且含「标称」；副说明（仅作建单时的默认值与整卷换算、**实际卷长以入库单 / 订单行为准**）在**两处都渲染**。**同源 = 单点定义**：两份文案都来自 frontend/admin-web/src/lib/product-roll-length.ts 的 `ROLL_LENGTH_LABEL` / `ROLL_LENGTH_HINT`，任何一处各写一份字面量即判红。类级元守卫 = frontend/admin-web/tests/unit/roll-length-copy-single-source.test.ts（关键串只许出现在单点定义处 / 两个展示面都必须引用同一份常量 / 措辞不许被稀释 / 含判别力自证）；实例判据 = frontend/admin-web/tests/unit/components/ProductForm.test.tsx（PR-042 条）与 frontend/admin-web/tests/unit/pages/product-detail.test.tsx 的判据 5 条。🔴 **改前实测**（同一批 5 个测试文件）：`9 failed / 43 passed` —— 其中本判据相关 **5** 条判红（文案护栏 3 条 + 详情页 1 条 + 商品表单 1 条）。**不做**：不改字段名 / 提交载荷 `rollLengthM`，不把商品级参数改成从入库单动态派生（批次级实际卷长属商品详情的批次面板）。'],
    skip_reason='[backend-contract] 商品基础参数契约（迁移 + Java 单测，无 LLM 环节，不进 agent-eval 冒烟）：断言由 tests/unit_ci_workflows/test_product_roll_length_migration.py 与 backend/admin-api/src/test/java/com/migao/admin/service/ProductRollAllocationTest.java 执行',
    tags=['product', 'roll_length', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-045 [NORMAL] 多行入库单过账：批次号**逐行生成**（一个 SKU 行 = 一个批次），不得整单共用一个号（源: cases/product.yml）──
_CASE_PR_045 = EvalCase(
    id='PR-045',
    legacy_id='',
    title='多行入库单过账：批次号**逐行生成**（一个 SKU 行 = 一个批次），不得整单共用一个号',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单过账的批次粒度（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**逐行生成**：N 行明细过账 ⇒ `stock_batches` 落 **N 行**、`batch_no` **两两不同**。判据源 = `uk_stock_batches_no` 是 `UNIQUE (tenant_id, batch_no)` ⇒ 整单共用一个号时第 2 行撞唯一索引、**整个事务回滚**（≥2 行的入库单必然过账失败）。注入：把 `nextFreeBatchNo(tenantId)` 移回明细行循环之外 ⇒ 2 行夹具下取到两个相同批次号 ⇒ 断言红（红证实测：`Found duplicate(s): ["PC-…-0001"] in: ["PC-…-0001", "PC-…-0001"]`）。', '判据 2·**行上回写各自的号**：`inbound_order_items.batch_no` 必须等于**该行自己**那条 `stock_batches.batch_no`（不是整单共用的首个号）——逐行 `updateById` 的批次号与逐行批次行的批次号按序一一对应。', '判据 3·**加库存带各自的号**：`product_skus.latest_batch_no` 由每行各自的 `receiveStock` 写入（N 行 ⇒ 调 N 次、批次号两两不同）——整单共用号会让「最近批次」在多行同 SKU 时静默丢掉区分度。', '判据 4·**粒度 = 行而非 SKU**：同一 SKU 的两行（不同缸号）各一个批次、`dye_lot` 各归各行 —— 按 SKU 合并批次会丢掉缸号区分度、追溯断链。', "判据 5·**单行过账逐值不变**：仍是 `PC-yyyyMMdd-NNNN`、仍恰好 1 条批次行 / 1 条 `reason='inbound'` 台账 / `ref_no` = 入库单号；均价与台账成本快照口径不变。"],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-046 [NORMAL] 库存米数支持 1 位小数（入库 60.5 米被接受，不再拒绝「非整数米」）（源: cases/product.yml）──
_CASE_PR_046 = EvalCase(
    id='PR-046',
    legacy_id='',
    title='库存米数支持 1 位小数（入库 60.5 米被接受，不再拒绝「非整数米」）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**1 位小数入库落库**：入库单行 `quantity = 60.5` ⇒ 过账后 `product_skus.stock` 增加 **60.5**（不是 60、不是 61），批次行 `stock_batches.quantity = 60.5`，台账 `delta = 60.5`。注入红证：把 `InboundOrderService.validateRequest` 的数量判据改回「必须是整数」⇒ 建单当场拒（改前形态）。', '判据 2·**前端同判据**：admin-web 入库单提交前校验接受 `60.5` 并**原值**提交（不被 `Number.isInteger` 拦下）。注入红证：判据回退成 `Number.isInteger` ⇒ 变红。'],
    skip_reason='[backend-contract] 迁移 + Java 单测 + admin-web vitest（无 LLM 环节，不进 agent-eval 冒烟）：断言由 backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderServiceTest.java、frontend/admin-web/tests/unit/pages/inbound-orders-decimal.test.tsx 与 frontend/admin-web/tests/unit/lib/stock-quantity.test.ts 执行',
    tags=['product', 'stock', 'inbound', 'decimal', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-047 [NORMAL] 库存调整接受 1 位小数，且 SKU 间分摊不丢量、整数场景分配逐值不变（源: cases/product.yml）──
_CASE_PR_047 = EvalCase(
    id='PR-047',
    legacy_id='',
    title='库存调整接受 1 位小数，且 SKU 间分摊不丢量、整数场景分配逐值不变',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**AI 工具 schema 放宽**：`inventory_manage` 的 `adjustment` 参数 `type == "number"`（改前 `"integer"`）；工具层对该参数的整数判定不再把 `60.5` / `-2.7` 判成类型错误。注入红证：把 schema 改回 `integer` ⇒ 变红。', '判据 2·**分摊总量恒等**：`adjustStockForAgent(+2.7)` 在 2 个 SKU 上分摊后，各 SKU 库存之和**恰好** +2.7（不丢 0.1 的余数）。注入红证：把分摊改回 `int base = adjustment / n` ⇒ 得 2（丢 0.7）⇒ 变红。', '判据 3·**整数场景逐值不变**：`+3` 在 `[30,20]` 上仍是 `[32,21]`（不是「各 +1.5」）、`-25` 仍是 `[5,20]`。注入红证：把分摊一步改成 `tenths / n` ⇒ 变红。', '判据 4·**展示无浮点毛刺**：AI 工具回给 LLM/用户的库存数字不出现 `2.7000000001` 这类毛刺（`stock_semantics.product_stock_summary` 的求和不得 `int()` 截断）。注入红证：保留 `int()` ⇒ `60.5 + 1.5` 得 61 ⇒ 变红。'],
    skip_reason='[backend-contract] Java 单测 + ai-agent pytest（无 LLM 环节，不进 agent-eval 冒烟）：断言由 backend/admin-api/src/test/java/com/migao/admin/service/AgentProductServiceTest.java、backend/ai-agent-service/tests/test_tools_inventory_decimal.py 执行',
    tags=['product', 'stock', 'decimal', 'allocation', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-048 [NORMAL] 库存类输入超过 1 位小数 ⇒ 显式拒绝（fail-closed，不静默取整）（源: cases/product.yml）──
_CASE_PR_048 = EvalCase(
    id='PR-048',
    legacy_id='',
    title='库存类输入超过 1 位小数 ⇒ 显式拒绝（fail-closed，不静默取整）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**入库量 3 位小数被拒**：`quantity = 2.755` ⇒ 业务异常，文案含「1 位小数」且可行动（说明库存按 0.1 米粒度记、请改为 1 位小数后重试）；**不得**落库成 2.8（静默取整）。注入红证：去掉精度判据 ⇒ 2.755 被静默存下 ⇒ 变红。', '判据 2·**库存调整量 3 位小数被拒**：`adjustStockForAgent(2.755)` / `AgentProductController` 的 `adjustment = 2.755` ⇒ 显式拒绝（`StockQuantity.requireOneDecimal`）。', '判据 3·**AI 工具层先拒**：`inventory_manage(action=adjust, adjustment=2.755)` ⇒ `success=False`、文案含「1 位小数」，且**不发出**任何写请求（零 API 调用）。注入红证：去掉拒绝分支 ⇒ PATCH 被调用 ⇒ 变红。', '判据 4·**前端同判据**：admin-web 入库单 `2.755` / `1.05` ⇒ 提交前拒绝并提示「1 位小数」，且不调建单接口。注入红证：删掉位数判据 ⇒ 变红。', '判据 5·**建品/改品的 stock 同判据**：`ProductCreateRequest.stock = 2.755` ⇒ 显式拒绝（不得静默存成 2.8）。'],
    skip_reason='[backend-contract] 三层各自的确定性判据（Java 单测 + ai-agent pytest + admin-web vitest），无 LLM 环节：断言由 backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderServiceTest.java、ProductServiceTest.java、backend/ai-agent-service/tests/test_tools_inventory_decimal.py、frontend/admin-web/tests/unit/lib/stock-quantity.test.ts 执行',
    tags=['product', 'stock', 'decimal', 'fail_closed', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-049 [NORMAL] 订单扣减/回补按真实米数落库存与台账（买 2.7 米 ⇒ delta = -2.7）（源: cases/product.yml）──
_CASE_PR_049 = EvalCase(
    id='PR-049',
    legacy_id='',
    title='订单扣减/回补按真实米数落库存与台账（买 2.7 米 ⇒ delta = -2.7）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**扣减不再取整**：`order_items.quantity = 2.7`、SKU 库存 30 ⇒ 确认支付后 `product_skus.stock = 27.3`（不是 28）、台账 `delta = -2.7`、`after_qty = 27.3`、`before_qty = 30`。注入红证：把 `deductSkuStock` 改回 `item.getQuantity().intValue()` ⇒ 库存 28、delta = -2（0.7 米凭空消失）⇒ 变红。', '判据 2·**回补同口径**：取消订单回补后库存回到 30（扣 2.7 就补 2.7），台账第二行 `before_qty == 第一行 after_qty`（首尾相接）。注入红证：回补侧改回 `intValue()` ⇒ 30.3 ≠ 30 ⇒ 变红。', '判据 3·**超过 1 位小数的顾客数量按 §8 显式向上进位**（`docs/curtain-fabric-quote-rules.md` §8「用料米数一律向上进位到 0.1」）：`2.75` ⇒ 落库 2.8（与裁床实际用料同向同粒度），**不是**截断成 2；扣减与回补用同一函数 ⇒ 净变化为 0。这里**不拒绝**（顾客已下单，拒绝 = 损失客户）。'],
    skip_reason='[backend-contract] 订单腿契约（Java 单测，无 LLM 环节，不进 agent-eval 冒烟）：断言由 backend/admin-api/src/test/java/com/migao/admin/service/OrderStockLedgerTest.java 执行',
    tags=['product', 'order', 'stock', 'ledger', 'decimal', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-050 [NORMAL] 整数场景逐值不变（库存小数化的回归护栏）（源: cases/product.yml）──
_CASE_PR_050 = EvalCase(
    id='PR-050',
    legacy_id='',
    title='整数场景逐值不变（库存小数化的回归护栏）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**入库 30 米逐值不变**：`quantity = 30` ⇒ `stock` 由 5 变 35、批次与台账与改前同值（改动只许作用于小数场景）。', '判据 2·**订单 2 米逐值不变**：`quantity = 2` ⇒ 库存 30 → 28、台账 `delta = -2`（`BigDecimal.equals` 也比 scale ⇒ 「逐值不变」包含 JSON 字面量不出现多余的 `.0`）。', '判据 3·**调整 +3 / -25 的分配逐值不变**：`[30,20]` +3 ⇒ `[32,21]`；-25 ⇒ `[5,20]`。', '判据 4·**「未传」不变成 0**：`ProductUpdateRequest.stock == null` 仍表示「这一项不改」（`requireOneDecimalOrNull` 保 null），不得把库存清零。'],
    skip_reason='[backend-contract] 回归护栏（Java 单测，无 LLM 环节）：断言由 backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderServiceTest.java、OrderStockLedgerTest.java、AgentProductServiceTest.java 执行',
    tags=['product', 'stock', 'regression', 'decimal', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-051 [NORMAL] 三层数量列 INT → NUMERIC(12,1) 迁移（V115，幂等 + 终态对账 + bootstrap 同步）（源: cases/product.yml）──
_CASE_PR_051 = EvalCase(
    id='PR-051',
    legacy_id='',
    title='三层数量列 INT → NUMERIC(12,1) 迁移（V115，幂等 + 终态对账 + bootstrap 同步）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**真库两遍幂等**：临时 PG 集群上真跑 V115 两遍 —— 第二遍 0 次 `ALTER`（已是终态则跳过）、终态列类型与精度不变、存量整数值逐字节不变（`60 :: numeric(12,1)` = `60.0`，无损）。', '判据 2·**终态对账真跑得过**：文末 `DO` 块逐列核对 `data_type = numeric AND numeric_precision = 12 AND numeric_scale = 1`，九列任一不符 ⇒ `RAISE EXCEPTION` 整份回滚。注入红证：把某一列的 `ALTER` 去掉 ⇒ 终态对账抛 ⇒ 变红。', '判据 3·**前置 fail-closed**：五张目标表任一不存在 ⇒ 迁移立即失败并停下（不兜底建表）。注入红证：DROP 一张表后重跑 ⇒ 必须失败。', '判据 4·**bootstrap 终态同步**：`docs/sql/schema.sql` 的九列同为 `NUMERIC(12,1)`（新建库路径不跑迁移链）。注入红证：把 schema.sql 的某一列改回 INT ⇒ 变红。', '判据 5·**已发布迁移逐字节冻结**：V115 必须登记进 `tests/unit_ci_workflows/migration_fingerprints.json`（#4235），且 V111/V113 等旧文件一字未改。'],
    skip_reason='[backend-contract] 迁移契约（真库 + 静态判据，无 LLM 环节）：断言由 tests/unit_ci_workflows/test_stock_quantity_decimal_migration.py 执行',
    tags=['product', 'migration', 'decimal', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-052 [NORMAL] AI 工具建品/改品的商品级 stock_quantity 放宽为 1 位小数（60.5 原值下发；2.755 显式拒绝且零 API 调用）（源: cases/product.yml）──
_CASE_PR_052 = EvalCase(
    id='PR-052',
    legacy_id='',
    title='AI 工具建品/改品的商品级 stock_quantity 放宽为 1 位小数（60.5 原值下发；2.755 显式拒绝且零 API 调用）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**1 位小数原值下发**：`product_manage(action=create|update, stock_quantity=60.5)` ⇒ 下发给 admin-api 的 `stock` 字面量 == **60.5**（不是旧实现 `int()` 截出来的 60），且 LLM 可见 schema 声明为 `number`（改前 `integer` 会让 LLM 把 60.5 说成 60）。注入红证：把归一改回 `int(stock_quantity)` ⇒ 60 ≠ 60.5 ⇒ 变红。', '判据 2·**超过 1 位小数显式拒绝 + 零 API 调用**：`stock_quantity=2.755` ⇒ `success=False`，文案含「1 位小数」「0.1 米粒度」「系统不会自动四舍五入或截断」并带越界原值；POST / PATCH **调用次数必须为 0**（不得先打后端再报错）。注入红证：删掉精度拒绝分支 ⇒ 2.755 被静默下发 ⇒ 变红。', '判据 3·**整数场景逐值不变**：`30` 下发的仍是 `int` 30（不是 `30.0`）。注入红证：把 Decimal 归一换成 `float(...)` ⇒ 变红。', '判据 4·**前置闸门同步放宽**：`validate_input(product_manage/create, stock_quantity=60.5)` 必须通过（改前规则声明 `int` ⇒ 60.5 在闸门被判「类型错误」、数字根本到不了工具层）；负数仍被 `min=0` 拦下（放宽类型不得连带放宽既有护栏）。', '判据 5·**复用而非新造**：`product_manage` 的小数位判定 / Decimal 归一 / 0.1 米粒度**就是** #5063 落在 `inventory_manage` 的同一对象（`_one_decimal_or_none` / `_stock_number` / `STOCK_QUANTUM`），不新造第二套判据或常量。注入红证：把助手复制一份进 `product_manage` ⇒ 同一对象断言变红。'],
    skip_reason='[backend-contract] ai-agent pytest（无 LLM 环节，不进 agent-eval 冒烟）：断言由 backend/ai-agent-service/tests/test_tools_product_stock_decimal.py 执行',
    tags=['product', 'stock', 'decimal', 'fail_closed', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-055 [NORMAL] 批次消耗台账：余量派生 / 剩余量分布四档 / 路线 A 对账恒等式 / 派工候选建议值（V116，#5145 阶段 1）（源: cases/product.yml）──
_CASE_PR_055 = EvalCase(
    id='PR-055',
    legacy_id='',
    title='批次消耗台账：余量派生 / 剩余量分布四档 / 路线 A 对账恒等式 / 派工候选建议值（V116，#5145 阶段 1）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**余量是派生值**：`remaining = stock_batches.quantity + Σ(stock_batch_consumptions.delta)` —— 夹具 60 米批次已派工 2.7 ⇒ 余量 57.3（小数逐值可比）；`onlyAvailable` 只回余量 > 0 的批次。红证：把余量改成直接读 `stock_batches.quantity` ⇒ 57.3 变 60，必红。', '判据 2·**剩余量分布四档逐值可比**：夹具 6 个批次余量 `0.2 / 0.1 / −0.5 / 0.5 / 1 / 1.1` ⇒ 四档批次数恰为 `3 / 1 / 1 / 1`、占比 `0.5 / 0.1667 / 0.1667 / 0.1667`（负余量 = 超扣落入 ≤0.2 档，不藏起来）；空仓 ⇒ 四档恒在且全 0。红证：把边界改成左闭（`< 0.2`）⇒ 0.2 掉档，必红。', '判据 3·**对账可读且可解释**（路线 A 的交换条件）：批次入 60 米、销售已扣 2.7、**未派工** ⇒ `diff = 60 − 57.3 = 2.7` = 已售未派，且恒等式 `diff == (soldDeducted − dispatched − otherLedgerDelta) − unbatched` 成立（`reconciled = true`）；派工之后差额归零；退货回补（aftersales）造成的差额如实反映为 −2.7；**不平的夹具 ⇒ `reconciled = false` 且 `unreconciledCount` 报数**。红证：把 `reconciled` 恒置 true ⇒ 不平夹具那条必红。', '判据 4·**派工候选建议值 = 朴素先进先出**（`suggestionRule = FIFO_RECEIVED_DATE`）：入库早但余量不够的批次 `enough=false` 且不被建议，建议落在第一个**够用**的批次；口径随响应显式回传，免得被读成 best-fit（**缺省**口径不变；best-fit 自 issue #5167 起可**显式**切换，见 PR-066/PR-067）。', '判据 5·**工人端指派读面取净额**：同一明细行既有扣减又有回补 ⇒ 取净额；净额归零的行**不出现**在结果里（工人不该被指去裁一个已经不扣账的批次）。', '判据 6·**批次余量分页读面（issue #7604）**：`GET /api/admin/batch-stock/batches/page` 回 `PageResponse<BatchRemaining>`（items/total/page/size 四字段，`total` = 服务端总数而非本页行数）；**服务端分页** —— 只对当页批次走 `selectPage`（不是 `selectList` 拉全量再内存切片），且余量三值走 `remaining()` 同一个派生点（入库 67 / 消耗 20.5 ⇒ 46.5，不是 47）；浏览序 = 收货日期倒序、id 倒序；`keyword` 是服务端 LIKE（批号 / 旧系统批号 / 缸号 / 入库单号 / 货号）。红证：把分页实现换成 `selectList` + 内存切片、或让页面自己算余量 ⇒ 本判据红。执行点 = StockBatchConsumptionServiceTest 的「分页读面」用例 + StockBatchControllerTest 的 `GET /batches/page` 用例。'],
    skip_reason='[backend-contract] 批次账服务与只读端点契约（真值断言在 Java 单测，非 LLM 行为）：由 StockBatchConsumptionServiceTest + StockBatchControllerTest 执行（Mockito 假 Mapper，无真实 DB）',
    tags=['product', 'stock', 'batch', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-056 [NORMAL] 批次消耗台账表契约（V116）：幂等闸唯一索引 / reason 约束 / 三查询索引 / 明细行 id 同宽 / bootstrap 同步（源: cases/product.yml）──
_CASE_PR_056 = EvalCase(
    id='PR-056',
    legacy_id='',
    title='批次消耗台账表契约（V116）：幂等闸唯一索引 / reason 约束 / 三查询索引 / 明细行 id 同宽 / bootstrap 同步',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**幂等闸必须在**：`uk_batch_consumption_line (tenant_id, processing_order_no, batch_id, order_item_id, reason) WHERE deleted = 0` —— 漏了它「重复生成加工单不会二次扣减」就只剩上游一条网，而重复扣减会让余量与分布静默偏小。红证：删掉该唯一索引 ⇒ 迁移终态对账抛 + 本断言红。', '判据 2·**reason 约束同时放行扣减与回补**（`ck_batch_consumption_reason` 含 `processing_order` 与 `processing_order_cancelled`，且两者是**同一个** CHECK 的成员）。红证：把回补取值从 CHECK 里去掉 ⇒ 作废回补当场 23514，迁移终态对账先红。', '判据 3·**`order_item_id` 宽度与 `order_items.id` 一致（VARCHAR(36)）**：它是 ASSIGN_UUID 主键、**不是** BIGINT —— 写成 BIGINT 会在真库插入失败（单测全绿、生产全挂的那一类）。红证：改回 `order_item_id BIGINT` ⇒ 本断言红。', '判据 4·**三条查询索引**（按批次 / 加工单 / 订单查回来）+ **显式 BEGIN/COMMIT** + 前置表 fail-closed + 文末终态对账 DO 块。', '判据 5·**bootstrap 终态同步**：`docs/sql/schema.sql`（新建库路径不跑迁移链）也建了该表并带同一个幂等闸索引；V116 已登记进 `tests/unit_ci_workflows/migration_fingerprints.json`（#4235 不可变护栏）。红证：把 schema.sql 的该表段删掉 ⇒ 本断言红。', '判据 6·**精度与既有列逐字一致**：`delta / before_qty / after_qty NUMERIC(12,1)`（V115/#5063 的 0.1 米粒度；整数场景逐值不变）。'],
    skip_reason='[backend-contract] 表/迁移契约（静态断言 + 真值源对齐，无 LLM 环节）：由 StockBatchConsumptionMapperTest 执行',
    tags=['product', 'migration', 'batch', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-057 [NORMAL] 后台派工批次指派对话框 + 批次账读面（余量/四档分布/对账）：不指派 ⇒ 请求体不带 batches（源: cases/product.yml）──
_CASE_PR_057 = EvalCase(
    id='PR-057',
    legacy_id='',
    title='后台派工批次指派对话框 + 批次账读面（余量/四档分布/对账）：不指派 ⇒ 请求体不带 batches',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**不指派 ⇒ 行为与今天逐字相同**：一行都不可指派（无候选批次 / 候选查询失败）⇒ **不弹对话框**、`generate(orderIds)` **单参调用**（请求层断言：不指派时请求体里**没有** `batches` 键，不是空数组）。红证：让 `submitGenerate` 恒传第二参 ⇒ 本断言红。', '判据 2·**人工最终选择被如实记录**：对话框里逐行选批次 ⇒ 请求体 `batches` 逐条为 `{orderId, itemId, batchNo}`（`batchNo` = 文员改后的值，空选择的行**不**进 batches）；无可用批次的行**不给下拉**（不能选）。红证：去掉空选择过滤 / 给无候选行也渲染下拉 ⇒ 必红。', '判据 3·**系统给建议值且默认选中**：每行默认选中后端 `suggestedBatchNo`（可改）；余量不足的候选 disabled。红证：`defaultPickOf` 恒返回空串 ⇒ 必红。', '判据 4·**缺料可行动**：生成返回 `success=false` ⇒ 原样展示 `message` + `suggestion`（不得吞掉、不得改写）。红证：把 `suggestion` 换成空串 ⇒ 必红。', '判据 5·**读面口径说清**：余量表含「余量」列且文案写明「派生余量 = 入库量 − 已派工消耗」；分布**恒四档**（0 档也渲染）；对账表展示 `diff` 与分解腿，并写明「差额 = 已售未派 + 台账外存量，**不是异常**」；`reconciled=false` 显式告警 + `unreconciledCount` 报数。红证：四档 `filter(batchCount > 0)` / 文案改成「差额异常」/ 去掉告警块 ⇒ 各自必红。', '判据 6·**只读、不动钱**：读面板只调 `GET /api/admin/batch-stock/*`（无写端点）；对客金额/售价/成品尺寸一字未改。'],
    skip_reason='[backend-contract] 纯前端单元测试（admin-web vitest：ProcessingOrderBlock / BatchStockPanel / batch-stock 请求层），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['product', 'ui', 'stock', 'batch', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-058 [NORMAL] 入库单幂等与并发：并发过账只加一次库存；进程重启后当天仍能建单；同一 import_run_id 重跑不建第二张（源: cases/product.yml）──
_CASE_PR_058 = EvalCase(
    id='PR-058',
    legacy_id='',
    title='入库单幂等与并发：并发过账只加一次库存；进程重启后当天仍能建单；同一 import_run_id 重跑不建第二张',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单的并发过账 / 重跑导入 / 服务重启后建单（非 LLM 行为，由 Java 单测 + 真 PG 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**并发过账闸**：两个并发过账 ⇒ **恰好一个成功**、库存**只加一次**、台账**只落一条**。判据源 = 条件更新 CAS（`UPDATE inbound_orders SET status='posted', posted_at, posted_by … WHERE id AND tenant_id AND status='draft' AND deleted=0`，按**影响行数**判是否抢到过账权；PG 行锁持有到事务结束），SQL 从 `backend/admin-api/src/main/java/com/migao/admin/mapper/InboundOrderMapper.java` 的真源码取；真 PG 两会话并发实测读数：`claimed=1` / `claimed=0`、库存 5 → 35、台账 1 条、单据 posted。**注入红证** = 换回改前形态（先 `SELECT status` 判 draft 再干活）⇒ 两会话**都**读到 draft ⇒ 库存 5 → 65、台账 2 条（证明「只加一次」不是恒真）。", '判据 2·**重启/多副本当天首个建单必须成功**：进程内计数器归零后取号会再次走到 `RK-<今天>-0001`（当天已被占）⇒ 改前直接撞唯一索引、建单失败；改后取号前查库内占用并**重试**（上限 20 次，同批次号 `nextFreeBatchNo` 范式）⇒ 建单成功且换用未占用的号（真 PG 兜底 = `uk_inbound_orders_no (tenant_id, inbound_no) WHERE deleted = 0`）。', '判据 3·**建单幂等（GAP-02）**：同一 `(tenant_id, import_run_id)` 重跑建单 ⇒ **返回同一张单**（不建第二张；两张都过账 = 库存加两次）。真 PG 实测：第二张被 `uk_inbound_orders_tenant_import_run (tenant_id, import_run_id) WHERE import_run_id IS NOT NULL AND deleted = 0` 挡下、同键单据数 = 1；**注入红证** = DROP 该索引 ⇒ 同键 2 张。**不误伤**：不带运行标识的普通建单可并存、另一租户同键允许。', '判据 4·**口径一致**：单号唯一索引范围 = **租户内**（与 V111 建表注释逐字写的「租户内唯一」一致；改前是全局唯一索引 ⇒ 注释与索引矛盾，且另一租户同号会把本租户的建单挡下）；`source ∈ {purchase, opening}` 有 CHECK 取值约束（写 `gift` 当场拒绝），缺省 `purchase`。', '判据 5·**不损失客户**：既有单行/多行过账行为、移动加权均价、台账 `ref_no` = 入库单号、成本快照逐值不变；不带 `import_run_id` 的建单行为与改前逐字一致。'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + 真 PG 判据覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-059 [NORMAL] 商品 + SKU 批量导入：幂等键 = 租户 + 货号 / 逐行校验报告不静默跳过 / 库存 1 位小数 / 只增改不删（源: cases/product.yml）──
_CASE_PR_059 = EvalCase(
    id='PR-059',
    legacy_id='',
    title='商品 + SKU 批量导入：幂等键 = 租户 + 货号 / 逐行校验报告不静默跳过 / 库存 1 位小数 / 只增改不删',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**URL|HTTP 入口**：`POST /api/admin/products/import`（multipart，字段名 file）返回 200 + `data`（total/successCount/failCount/blankRows/createdProducts/updatedProducts/errors[]）；导入 3 行 ⇒ 1 个商品 + 3 个 SKU，逐字段（名称/货号/基础价/描述/颜色/门幅/SKU 编码/库存/租户/状态）可比对。红证：改前 `ProductController` 只有 `@GetMapping("/export")` ⇒ 该端点在 standalone MockMvc 上实测得 **405**，而 `GET /import-template` 落到「商品详情」路由返回 **JSON**（不是 xlsx）。', '判据 2·**同文件重跑 = 幂等**：幂等键 = `(tenant_id, 货号)`；第二次导入 `createdProducts=0 / updatedProducts=1`、`productMapper.insert` 只被调用 1 次、SKU 行数与**主键不变**（原地更新）。红证：把幂等键查询改成恒 null（每次都新建）⇒ 该断言红（实测）。', '判据 3·**逐行校验报告，不静默跳过**（机械判据）：`total == successCount + failCount + blankRows` 恒成立，失败行带**行号 + 货号 + 可行动原因**。红证：把逐行 `addError` 换成静默 `continue` ⇒ 恒等式与 `failCount` 同时红（实测）。', '判据 4·**库存 1 位小数**：`60.5` 原样落库；`2.755` 显式拒绝且**该行零落库副作用**（商品/颜色/SKU 一张都没写）；`2.70`（书写 2 位、有效 1 位）合法 —— 判据单点在 `StockQuantity`，导入不另写一套。红证：把准入换成静默取整 ⇒ 该断言红（实测）。', '判据 5·**不损失客户**：导入只增改不删（文件里没有的既有 SKU 不被物理删除，否则批次挂着的 SKU 断链）；对客价 = 文件原值、不经任何折算；无 SKU 维度时商品级库存取文件值，库存列留空 = 「未填 = 不改」（不是清零）。', '判据 6·**一进一出同构**：导入表头 ∩ 导出表头 = **逐字同名**的那 5 列（商品名称/货号/价格/库存/描述）；SKU 维度只有 颜色 + 门幅（**不含售卖方式**，V113）；表头按**名字**定位（列序无关、容忍模板 `*` 号、允许多余列与缺可列）；**数字单元格按十进制原样读**（门幅敲成数字 `2.8` 不得变 `2`、货号 `12345` 不得变科学计数法）；模板下载下来能**原样导回去**（表头与解析共用同一常量）。', '判据 7·**租户隔离**：查重按 `(tenant_id, 货号)`；租户取自 `TenantContext`（**不接受**客户端传入）；同货号在不同租户各建一个商品。'],
    skip_reason='[backend-contract] 服务/端点契约（静态断言 + 内存库真存真取，无 LLM 环节）：由 ProductBulkImportServiceTest / ProductImportControllerTest 执行',
    tags=['product', 'import', 'backend_contract', 'idempotent', 'decimal'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-060 [NORMAL] 商品批量导入的后台可见面：导入入口 + 模板下载 + 三桶口径逐行报告（源: cases/product.yml）──
_CASE_PR_060 = EvalCase(
    id='PR-060',
    legacy_id='',
    title='商品批量导入的后台可见面：导入入口 + 模板下载 + 三桶口径逐行报告',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**入口存在且与导出对偶**：商品管理页工具栏同时有「批量导出」「下载导入模板」「导入商品」；选中 xlsx ⇒ 请求层收到**原文件对象**；模板下载文件名 = 商品导入模板.xlsx。红证：改前 `frontend/admin-web/src` 里「导入」零命中（0 处 UI）⇒ 本文件 7 条全红（实测）。', '判据 3·**三桶口径同时可见**：报告弹窗必须同时展示「成功 N 行 / 失败 N 行 / 空白行 N 行」与「新建 N 个商品 / 更新 N 个商品」；失败明细逐行展示「第 N 行 / 货号 / 原因」且原因**原文不改写**（服务端说 1 位小数，页面不得改说格式错误）；失败为 0 时显式说「无失败行」，不留空让人猜。', '判据 1·**失败不冒充成功**：接口报错 ⇒ 不弹报告弹窗（不拿空报告当成功）；导入成功后刷新列表（商家立刻看得到落库结果）。'],
    skip_reason='[backend-contract] 纯前端单元测试（admin-web vitest：products 页导入入口 + 报告展示 + 请求层），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['product', 'ui', 'import', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-061 [NORMAL] 批次建账（期初入库单）：0.5 米尾料可登记、旧系统批次号独立落点、同 import_run_id 重跑不建第二张、余量=登记值（真库）（源: cases/product.yml）──
_CASE_PR_061 = EvalCase(
    id='PR-061',
    legacy_id='',
    title='批次建账（期初入库单）：0.5 米尾料可登记、旧系统批次号独立落点、同 import_run_id 重跑不建第二张、余量=登记值（真库）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库把现有在库批次按实物登记进 MIGAO（非 LLM 行为，由 Java 单测 + 真 PG 判据 + 源码禁令判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**0.5 米能登记（GAP-12）**：登记一个 **0.5 米**的批次 ⇒ 成功，批次行 `stock_batches.quantity` 读数就是 **0.5**（既没被下限挡下，也没被任何归一改写成 1）。红证：改前 `InboundOrderService.validateRequest` 判 `quantity.compareTo(BigDecimal.ONE) < 0` ⇒ 当场抛「商品明细第 1 项的数量必须 ≥1 米（按米入库）」（Java 单测复现文案）——用户痛点「剩余了大量的 0.5 米左右的批次布料」正是被这条挡在门外。', '判据 2·**不虚增（禁令①）**：登记 3 个批次（0.5 / 2.7 / 60.5，含缸号与旧系统批次号）⇒ `stock_batches` 落 **3 行**、`legacy_batch_no` 与 `dye_lot` 如实保存、**余量 = 登记值**（不是进位后的值）。归一**不得**复用订单侧的 `toStockScaleByCeiling`（向上进位、模拟裁床用料）—— 用它每条最多虚增 +0.099m = 系统性虚增资产；**注入式红证**：同一真列取 `2.71` 走进位方向得 `2.8`、走四舍五入方向得 `2.7` ⇒ 虚增 **0.1 米/条**（证明「余量 = 登记值」不是恒真）。源码判据（去注释后）：`InboundOrderService` / `OpeningRegisterImportService` 里不得出现 `toStockScaleByCeiling`。', '判据 3·**精度闸门不放宽**：放宽下限**不连带**放宽精度 —— `2.755` 仍**显式拒绝**（Java 判据 + 前端 `checkStockQuantity` 同判据）；真库侧同时钉住前提：`NUMERIC(12,1)` 对 `2.75` **静默落成 2.8 且不报错**（退出码 0）⇒ 「DB 会拦下 2 位小数」是假的，fail-closed 只能在应用层。', '判据 4·**幂等（复用 V117 既有件，不新造键）**：同一 `(tenant_id, import_run_id)` 重跑期初建账 ⇒ 命中既有那张单、第二张被 `uk_inbound_orders_tenant_import_run` 挡下（23505、同键单据数 = 1）；批量导入端点把 `importRunId` 声明成**必填**（缺键即拒，不建单）⇒ 重跑不会双倍加库存；**注入式红证** = DROP 该索引 ⇒ 同键 2 张。不误伤：无运行标识的普通建单可并存、另一租户同键允许。', '判据 5·**正常采购路径不回归**：原有的 `0` / 负数 / 超 1 位小数 / 非正单价 / 串 SKU 拒绝逐条仍成立；不带 `import_run_id` 的建单行为与改前逐字一致；`legacy_batch_no` 只在 `source=opening` 时可填（采购单填了被拒 —— 旧号与系统批次号**不得互相冒充**，也不得塞进 `batch_no`/`dye_lot`）。', "判据 6·**分布可复算**：给定 `source='opening'` 的批次集合 ⇒ 逐值 `quantity + Σ(delta)` 可复算（真库读数 `0.2 / 2.7 / 59.3`）、两遍读数逐字相同 ⇒「余量派生 ⇒ 分布永久可复算，**不需要**物化快照表」；采购批次不进这一集合。基线冻结点 = `posted_at` + `source='opening'`。", '判据 7·**导入必须走服务层（禁令②）**：导入器不得自己归一（去注释后的源码里不得出现 `setScale` / `RoundingMode` / `intValue()` / `(long)` / `(int)`），数值单元格按十进制定点读（`BigDecimal.valueOf`），且必须调 `inboundOrderService.create` + `.post`；**全或无**：任一行为红 ⇒ 一行都不写（不建单、不调 create）。', '判据 8·**不损失客户**：对客金额 / 售价 / 成品口径一字未动（本单只加库存侧的登记能力 + 一处下限值）。', '判据 9·**缺口列与 bootstrap 镜像**：`legacy_batch_no VARCHAR(64)` 落在 `stock_batches` 与 `inbound_order_items` 两处（明细行也要一列 —— 建单与过账是两次请求，不落明细行则过账时丢号），列注释写明「旧系统」来路；V118 已登记 `migration_fingerprints.json`、显式 `BEGIN/COMMIT`、前置 fail-closed 在写语句之前、两遍真跑幂等；`docs/sql/schema.sql` 已同步终态。'],
    skip_reason='[backend-contract] 入库/建账是后台仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + 真 PG 判据 + 源码禁令判据覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'opening-register', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-062 [NORMAL] 建账入口（admin-web）：单条录入在独立整页 /inbound-orders/new（来源=期初建账 + 旧系统批次号）+ Excel 批量（模板/逐行报告/可重跑）+ 0.5 米可提交（源: cases/product.yml）──
_CASE_PR_062 = EvalCase(
    id='PR-062',
    legacy_id='',
    title='建账入口（admin-web）：单条录入在独立整页 /inbound-orders/new（来源=期初建账 + 旧系统批次号）+ Excel 批量（模板/逐行报告/可重跑）+ 0.5 米可提交',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/仓库在商品入库页做批次建账（非 LLM 行为，由 admin-web vitest 覆盖）'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**单条录入动线**：建单页（独立整页 `/inbound-orders/new`；issue #5844 起不再是弹窗）的「单据来源」缺省 = 采购收货（此时**没有**旧系统批次号列）；切到「期初建账」⇒ 明细表出现「旧系统批次号」列，提交的 payload 为 `source: 'opening'` + `items[].legacyBatchNo`（采购收货则提交 `source: 'purchase'` + `legacyBatchNo: null` —— 填了后端会拒）。红证：改前 `InboundOrderCreateParams` 无 `source` 字段、页面无来源选择器 ⇒ 本判据红。", '判据 2·**0.5 米的实物尾料能提交**（GAP-12 的前端一半）：数量 `0.5` 通过提交前校验并按**原值** 0.5 提交（改前 `checkStockQuantity` 判 `n < 1` ⇒ 提交前就被挡、根本不调建单接口 —— 那正是「尾料进不来」的前端形态）；同时 `0` / 负数 / `2.755`（超 1 位小数）仍被挡（**放宽下限不等于取消下限，也不等于放宽精度**）。', '判据 3·**Excel 批量入口**：页头「期初建账导入」⇒ 弹窗里「下载模板」调 `openingTemplate`（blob 下载）；选文件 + 幂等键（导入标识在打开弹窗时生成、页面提示「重跑同一份文件不要改它」）⇒ 请求层收到**原文件对象**与**同一个标识**；没选文件就点导入 ⇒ 拦住且不调接口。', '判据 4·**逐行校验报告**：报告逐行渲染「行号 / 货号 / 剩余米数 / 缸号 / 旧系统批次号 / 结果」；通过行显示「通过」，不通过行显示**服务端原文原因**（含行号与位数，如「第 3 行剩余米数 最多支持 1 位小数…」）；`failCount > 0` ⇒ 提示「未建账」且**不刷新列表**（一行都没写）；`created=false 且无失败行`（幂等命中）⇒ 提示「已经建过账」而**不是**失败 —— 三种结局（建了 / 没建 / 早已建过）在界面上分得开。'],
    skip_reason='[backend-contract] 纯前端单元测试（admin-web vitest：inbound-orders 页建账入口 + 逐行报告 + stock-quantity 纯函数），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'opening-register', 'ui', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-065 [NORMAL] 排料接线：并排的两扇矮窗领料合计 3 米（不是 6 米）；省下的米数留在批次余量上；不可并排逐值不倒退；同一加工单不二次扣（源: cases/product.yml）──
_CASE_PR_065 = EvalCase(
    id='PR-065',
    legacy_id='',
    title='排料接线：并排的两扇矮窗领料合计 3 米（不是 6 米）；省下的米数留在批次余量上；不可并排逐值不倒退；同一加工单不二次扣',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['生成加工单时的领料米数口径（非 LLM 行为，由 Java 单测 + 真 PG 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**并排成立 ⇒ 真省**：门幅 2.8 米、窗高各 1.1 米（+ 上下卷边 0.3 ⇒ 各占门幅 1.4）、各需 3 米的两扇矮窗指派到**同一批次** ⇒ 排料后 1 行 / 行长 3 米 ⇒ **批次扣减 = 3 米**（不是 6 米，逐行分摊 1.5 + 1.5）。真 PG 实测读数：`Σ(−delta) = 3`、`formula_meters = 6`、`planned_meters = 3`、批次余量 60 → 57。**注入红证** = 同参数但去掉定尺入参（= 改前形态）⇒ `Σ(−delta) = 6`（同一测试内 A/B 对照打印）。', '判据 2·**不倒退**：不可并排（窗高 2.7 + 卷边 0.3 > 门幅 2.8）⇒ 逐行 `planned == formula` **逐值相同**、`saved_meters = 0`（宁可为 0，不许估）。真 PG 读数：两行各 2.7 ⇒ 合计 5.4、`SUM(formula_meters - planned_meters) = 0`。', '判据 3·**不虚报**：跨批次（不同卷）即使门幅相同也**不得**成组 —— 两块料各自都要单独占一段卷长 ⇒ 两行各扣 3 米。工艺未知 / 缺窗高 / 缺幅数（引擎 `panels` 缺席，不自己算 `ceil(M/G)`）/ 门幅没记 / 取不到上下卷边 / 排料器报错 ⇒ **逐值退回公式口径**（saved = 0），且绝不因排料失败让加工单生成失败。', '判据 4·**幂等**：同一加工单重复落账 ⇒ 被 `uk_batch_consumption_line` 挡下（真 PG 实测 SQLSTATE **23505**）、台账行数不变、批次余量不变（不得静默二次扣减）。', '判据 5·**不损失客户**：对客金额 / 售价 / 成品口径逐值不变（排料只改**批次实物账**的扣减米数，`product_skus.stock` 与 `stock_ledger_entries` 一字不动）。'],
    skip_reason='[backend-contract] 加工单/批次账的后端口径（无黄金策工具面）⇒ 由 Java 单测 + 真 PG 判据覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'production', 'cutting-plan', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-063 [NORMAL] 两个米数落库：formula/planned/当时均价三列可逐单审计；换价后历史单 saved_amount 不变；对账差额拆成「已售未派」+「排料节省」两项且仍平（源: cases/product.yml）──
_CASE_PR_063 = EvalCase(
    id='PR-063',
    legacy_id='',
    title='两个米数落库：formula/planned/当时均价三列可逐单审计；换价后历史单 saved_amount 不变；对账差额拆成「已售未派」+「排料节省」两项且仍平',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「到底省了多少料」的逐单读数与对账口径（非 LLM 行为，由 Java 单测 + 真 PG 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**两个米数 + 当时均价三列真落库**（V119）：`formula_meters` / `planned_meters` / `unit_cost` 随扣减行写入，`saved_meters = formula − planned`、`saved_amount = saved_meters × unit_cost` 在**读面派生**（不落第三个数）。真 PG 读数：两行各 1.5 米 ⇒ `saved_meters = 3`、`saved_amount = 37.50`（均价 12.5）。回补行逐值对称（两个米数取相反数、均价原样搬运）⇒ 作废后整单净额归零、不冒功。', '判据 2·**单价口径不变量**：把 `stock_batches.unit_cost` 改成 99 之后，**历史单**的 `saved_amount` 仍为 37.50（用的是行内**当时**均价快照，不是查询时 join 批次价）。历史行（V119 之前）`formula = planned = −delta`、均价 NULL = 未知（不回填、不猜）。', '判据 3·**汇总一致**：按加工单聚合与按批次聚合的 `Σ saved_meters` 逐值相等（同一批行、同一个列族，不许两套口径）；对账读面另给 `totalFormulaMeters` / `totalPlannedMeters` / `totalSavedMeters`。', '判据 4·**对账可拆且不放宽**：`soldUnbatchedMeters`（已售未派）与 `planSavedMeters`（排料节省）**分别可读**，两项之和**逐值等于**拆之前的总解释项 ⇒ `reconciled` 判据仍是 `diff == explainedDiff`（改前判 true 的账改后仍判 true；不许一项冒充另一项）。夹具：批次入 60 / 卖 6 / 排料后只扣 3 ⇒ 差 3 全部读作排料节省、已售未派 0；另一组「已售未派 2 + 排料节省 3 = 差 5」两项并存。'],
    skip_reason='[backend-contract] 台账列与对账读面的口径（无黄金策工具面）⇒ 由 Java 单测 + 真 PG 判据覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'reconciliation', 'cutting-plan', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-064 [NORMAL] 迁移 V119：批次消耗台账追加 formula_meters / planned_meters / unit_cost（历史行回填、只多不少约束、显式事务、bootstrap 终态同步）（源: cases/product.yml）──
_CASE_PR_064 = EvalCase(
    id='PR-064',
    legacy_id='',
    title='迁移 V119：批次消耗台账追加 formula_meters / planned_meters / unit_cost（历史行回填、只多不少约束、显式事务、bootstrap 终态同步）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['迁移形态与终态口径（非 LLM 行为，由 Python 真 PG 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**三列存在且两个米数 NOT NULL**：真 PG 跑 V119 后 `information_schema.columns` 逐列可查；NULL 会让「答不出省了多少」的账静默落库。', '判据 2·**历史行回填**：V119 之前写入的行 `formula_meters = planned_meters = −delta`（⇒ saved = 0，与「本单之前节省恒为 0」的事实一致）；均价**不回填**（NULL = 未知，不拿今天的批次价冒充当时价）。', '判据 3·**「只多不少」约束**：`ck_batch_consumption_plan_meters` = `planned_meters <= formula_meters AND formula_meters * planned_meters >= 0` —— 违反者当场 23514（前半句禁「排料比公式多领」，后半句禁「两列符号打架」）。⚠️ **本句只描述 V119 当时的形态**：前半句在回补行（两列都负）上方向翻转，**V121（issue #5182）已订正为** `abs(planned_meters) <= abs(formula_meters)`（对扣减行逐字等价）；本用例判据跑的是 V119 单跑，故仍按原文断言。', '判据 4·**幂等/显式事务/停止条件**：`BEGIN; … COMMIT;`；两遍真跑幂等（`ADD COLUMN IF NOT EXISTS` + `WHERE … IS NULL` 回填 + 覆盖式注释）；前置表/列缺失 ⇒ `RAISE EXCEPTION` 停下；文末终态对账两遍都成立；已登记 `migration_fingerprints.json`（旧条目零改动）；`docs/sql/schema.sql`（bootstrap 终态）已同步。'],
    skip_reason='[backend-contract] 迁移形态判据（真 PG + 源码），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['inventory', 'migration', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-066 [NORMAL] 批次指派策略可切换：默认仍是 FIFO（逐值不变）；best_fit 挑余量最接近需求者（让批次用尽）；非法规则值显式拒绝（不静默回落）（源: cases/product.yml）──
_CASE_PR_066 = EvalCase(
    id='PR-066',
    legacy_id='',
    title='批次指派策略可切换：默认仍是 FIFO（逐值不变）；best_fit 挑余量最接近需求者（让批次用尽）；非法规则值显式拒绝（不静默回落）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['生成加工单时系统建议用哪个批次（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**默认不变（本单最重要的一条）**：不传规则 / 传空白 / 显式传 `fifo` 三种调用**逐值相同**（候选顺序、建议值、`enough`/`suggested` 标记、需求米数、`suggestionRule`）。红证：把 `StockBatchConsumptionService.normalizeAssignmentRule` 的缺省返回值改成 `best_fit` ⇒ 该判据当场变红（缺省建议值 PC-LATE ≠ PC-EARLY）。', '判据 2·**best-fit 生效且可判别**：判别性夹具 = 先入库余量 30.0（PC-EARLY）/ 后入库余量 3.0（PC-LATE）、需求 3.0 ⇒ FIFO 建议 = PC-EARLY、best_fit 建议 = **PC-LATE**（余量最接近需求者）；两条建议用 `isNotEqualTo` 断言（结论若相同则本判据不可判别）。`suggestionRule` 分别 = `FIFO_RECEIVED_DATE` / `BEST_FIT_REMAINING`；候选集合与顺序两策略**逐值相同**（规则只改建议值、不改候选 ⇒ 「不漏候选」是结构性的）。', '判据 3·**不倒退**：需求 100 米（两个批次都满足不了）⇒ 两策略**同**结论：`suggestedBatchNo == null` + 候选列表完整（两行都在、`enough=false`、`suggested=false`）。红证：去掉 best-fit 的「够不够」过滤 ⇒ 它会挑「余量最小的那个」当建议 ⇒ 判据红。', '判据 4·**非法规则值显式拒绝**：`bestfit` / `best fit` / `fifo,best_fit` / `1` / `自动` ⇒ 400 + `ASSIGNMENT_RULE_UNKNOWN` + 可选值清单，**绝不静默回落 fifo**；合法取值面 = 缺省(空)/`fifo`/`FIFO`/`best_fit`/`best-fit`。红证：把 `default -> throw` 改成 `default -> fifo` ⇒ 判据红。', '平局裁决：两批余量**逐值相同**且都够用 ⇒ 取先入库者（复用 FIFO 序，不引入第二个排序键）。', '自检：候选/建议值的挑法只有**一处实现**（`suggest`）—— 读面与生成侧自动指派共用它，两处各写一份必然漂移。'],
    skip_reason='[backend-contract] 批次指派策略的后端口径（无黄金策工具面）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'batch-assignment', 'best-fit', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-067 [NORMAL] 真库判据：best-fit 建议 → 落账扣的就是那一批且**用尽**（余量 3.0→0.0、≤0.2 米档 +1）；默认 FIFO 路径逐值不变（尾料留在账上）（源: cases/product.yml）──
_CASE_PR_067 = EvalCase(
    id='PR-067',
    legacy_id='',
    title='真库判据：best-fit 建议 → 落账扣的就是那一批且**用尽**（余量 3.0→0.0、≤0.2 米档 +1）；默认 FIFO 路径逐值不变（尾料留在账上）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['指派驱动扣减落账的真库读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 2·**best-fit 建议驱动落账**：真库夹具（先入库 30.0 / 后入库 3.0、需求 3.0）下 FIFO 建议 = `PC-5167-BF-EARLY`、best_fit 建议 = `PC-5167-BF-LATE`；把建议当指派用 ⇒ 真库读数 `batch_no = PC-5167-BF-LATE`、`Σ(−delta) = 3`、该批余量 **3.0 → 0.0**（NUMERIC(12,1) 逐值归零）、分布读面「≤0.2 米」= **1** 批，没被挑中的批次一动不动（30.0）。', '判据 1·**默认 FIFO 路径逐值不变**：不传规则 == 显式 `fifo` 逐值相同；落账走 `PC-5167-DF-EARLY`（余量 30 → 27），3.0 的那批**原封不动留在账上**、分布读面「≤0.2 米」= **0** 批 —— 这就是用户痛点「剩了 3 米尾料」在真库里的形态（对照读数，与上一条同夹具不同结论 ⇒ 判据可判别）。', '判据 6·**不损失客户 / 不回退 #5158 口径**：best-fit 选出的批次上两扇可并排的矮窗仍按**排料结果**领料（真库 `Σ(formula_meters) = 6`、`−Σ(delta) = 3`，逐行 3/1.5；对照「改前形态」= 不给定尺入参 ⇒ 合计 6 米）；best-fit + 并排 ⇒ 恰好用尽 3.0（不多领、不为负）；`product_skus.stock` 与 `stock_ledger_entries` 指纹**一字不动**（批次账与销售账不串）。', '判据 5·**幂等**：同一加工单重复落账 ⇒ 被 `uk_batch_consumption_line` 挡下（SQLSTATE **23505**）、台账行数不变、批次余量不变。**注入式红证**：拆掉该唯一索引（DDL 原文取自 `docs/sql/schema.sql`）⇒ 第二遍**真的进账**（行数 2、余量 −3）⇒ 证明拦下它的确实是这个闸；复原后索引仍在。', '夹具隔离：每个用例一个独立商品 ⇒ 分布读面（按商品统计 ≤0.2 米档）的读数与用例执行顺序无关。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['inventory', 'batch-assignment', 'best-fit', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-068 [NORMAL] 生成加工单可传 assignmentRule：只在**显式传了**规则时才把建议值升级为直接采用（缺省一字不改）；显式指定永远优先；无候选/非法值一律显式拒绝（源: cases/product.yml）──
_CASE_PR_068 = EvalCase(
    id='PR-068',
    legacy_id='',
    title='生成加工单可传 assignmentRule：只在**显式传了**规则时才把建议值升级为直接采用（缺省一字不改）；显式指定永远优先；无候选/非法值一律显式拒绝',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['生成加工单时按规则自动补位批次（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**缺省不自动指派**：不传 `assignmentRule` 且某行没给 `batchNo` ⇒ **逐字**沿用原错误「批次指派缺少 batchNo（行 item-1）」、**绝不**去查建议值（`verify(never())`）、不落加工单、不落台账。红证：去掉 `assignmentRule == null` 守卫 ⇒ 该行会被「静默指派」（或换成另一条错误文案）⇒ 判据红。', '判据 2·**显式传规则才补位**：`best_fit` ⇒ 未指定批次的行补成 `suggestedBatchNo(...)` 的结果，且**真的进计划**（`plan` 收到的指派行 `batchNo = PC-LATE`）与加工单快照 `batchNo`；补位用的需求 = 该行**公式口径**米数 2.7（实际扣减仍由 plan 按排料结果定）。', '显式 `fifo` 同样开启补位（缺省「不补位」≠ 规则值 `fifo`）；行里已有 `batchNo` ⇒ 人工最终选择优先，不查建议值。', '判据 3·**无候选 ⇒ 显式拒绝该行**：`suggestedBatchNo` 回 null ⇒ 逐单失败（🔴 2026-10-17 issue #7077 改判：旧文案把**内部规则码**（`best_fit` / `fifo`）与**明细行 id**（UUID）端给商家 ⇒ 现为「`「布艺遮光帘A」这行需要 2.7 米，库存里没有能裁出它的批次（按「先到先用」也补不上）—— 请先把这批布入库，或核对库存里对应门幅与颜色的余量后重试`」；判据 = `ProcessingOrderServiceTest#noCandidateUnderTheRuleFailsClosed` 的**成对断言**：新文案必须在 ∧ `best_fit` / `item-1` / 「指派规则」三个内部串必须**不在** ⇒ 任一句写回即红）、不落半成品（不插加工单、不扣批次）—— 不静默跳过 = 不静默少扣。', '判据 4·**非法规则值 ⇒ 整批拒绝**（**即使本次所有行都显式指定了批次**）：`bestfit` ⇒ 400 + `ASSIGNMENT_RULE_UNKNOWN`，且在**碰任何 Mapper 之前**判完。两个入口都判：`POST /processing-orders/generate`（body 字段）与 `GET /batch-stock/candidates`（query 参数，非法值 ⇒ 400）。'],
    skip_reason='[backend-contract] 生成加工单侧的规则装配与失败面（无黄金策工具面）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'batch-assignment', 'processing-order', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-069 [NORMAL] 待派池可按物料查看、等待时长可读、超上限**带着单号**告警（不静默压单）；滞留上限可配且非法值显式拒绝（源: cases/product.yml）──
_CASE_PR_069 = EvalCase(
    id='PR-069',
    legacy_id='',
    title='待派池可按物料查看、等待时长可读、超上限**带着单号**告警（不静默压单）；滞留上限可配且非法值显式拒绝',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看板读取待派池（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=["判据 5·**池的定义**：池 = 已确认支付（`orders.status='confirmed'`）**且无活跃加工单**的订单 —— 有活跃加工单的那张（`selectActiveOrderIds` 回它）**不进池**（真装配下 `orderCount` 只数 3 张），口径与 `uk_processing_orders_active` 逐字相同（少一个口径就会出现「池里看得见、派的时候被唯一键拒掉」）。", '判据 5·**按物料分组**：分组键 = `productId|skuCode`（`skuCode` = `processing_info.sku`，在本系统里就是「颜色 × 门幅」）⇒ 同商品同 SKU 的两张单落在**同一组**（`orderCount=2`、`requiredMeters=6`），不同 SKU 各成一组；`materialKey` 机器可判。', '判据 5·**等待时长可读 + 上限可配**：`waitHours = now − orders.created_at`（系统无 `paid_at/confirmed_at` 列 ⇒ 用下单时刻作**上界**口径，只会算得更久、不假装刚进池），`maxWaitHours` 回口径；缺省 24 小时 ⇒ 30 小时的那张超上限、2 小时的不超；调成 1 小时 ⇒ 2 小时与 30 小时的两张超上限，而**恰好 1.0 小时**的那张不算（判据是严格大于）⇒ 阈值确实生效。', '判据 5·**不得静默压单**：超上限必须有**带对象名字**的告警（`orderNo` + `waitHours` + 上限 + 「请成批派单或单独派单」），不是数不清对象的计数；红证：把 `overdue` 恒置 false ⇒ 告警数与超限数都变 0 ⇒ 判据红。', '**非法上限 fail-closed**：`maxWaitHours <= 0` ⇒ 400（`maxWaitHours 必须为正数`），**不静默回落**缺省值 —— 静默回落会让看板以为在按自己设的阈值告警。'],
    skip_reason='[backend-contract] 池读面的分组/等待/兜底判定（无黄金策工具面）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'processing-order', 'dispatch-pool', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-070 [NORMAL] 池化开关**缺省关**（不传 ⇒ 逐单派、plan 每单各调一次）；显式 pooled=true 才把 plan 改成**池级一次**求解（入参含池内多张单）（源: cases/product.yml）──
_CASE_PR_070 = EvalCase(
    id='PR-070',
    legacy_id='',
    title='池化开关**缺省关**（不传 ⇒ 逐单派、plan 每单各调一次）；显式 pooled=true 才把 plan 改成**池级一次**求解（入参含池内多张单）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['成批派单时是否跨订单成组（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**缺省关（逐值不变）**：5 参 `generate` 调用（调用方根本没提池化）⇒ `plan` 被调 **2 次**（每张单各一次），第一次的入参只有第一张单的行、第二次只有第二张单的行 ⇒ **跨订单成组不发生**；结果顺序 = `orderIds` 顺序。红证：把 `POOLED_DEFAULT_ENABLED` 改成 true ⇒ `plan` 变成一次调用、入参含两单 ⇒ 该断言当场红。', '判据 2·**池级一次求解（本单的存在理由在服务层的形态）**：`pooled=true` ⇒ `plan` **恰好调 1 次**，入参 = 池内**两张单**的行（`containsExactly(item-1, item-2)`）；两单的行因此可以并排成同一行 ⇒ 两单各分摊 1.5 米、**合计 3 米**（对照逐单派各 3 米合计 6 米）。', '**一单一加工单的约束不变**：池化派单产出 N 张**各自独立**的加工单（`insert` 两次），`apply` 也按单各调一次（各带本单那一笔）；每张单的快照**只有本单自己的行**被盖上 `batchNo`/`plannedMeters`（不是池级合计、也不是别单的行）。', '判据 4·**预览不说谎**：`preview` 的「预计节省」= `formulaMeters − pooledPlannedMeters`，与实际交给台账的 `Σ(formula − planned)` **逐值相等**（3 == 3）；同时 `perOrderPlannedMeters`（对照读数，逐单派口径）与 `poolingGainMeters`（池化**新增**收益）分开报 —— 不把 #5158 已有的单订单内并排算成池化的功劳。红证：把 `savedMeters` 改用逐单派口径 ⇒ 预览给 0、实际落账是 3 ⇒ 判据红。预览本身**只读**（不 `insert`、不 `apply`）。', '判据 3·**不倒退**（不可成组 ⇒ 与逐单派逐值相同）：`commit` 对「池化开了没有」无感，扣减行由调用方按 `orderItemId` 切分 ⇒ 不可成组时逐单派与池级派落的行**逐值相同**（真库读数见 PR-071）。'],
    skip_reason='[backend-contract] 池化的装配与顺序（plan 调几次、入参有哪些行）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'processing-order', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-071 [NORMAL] 🔴 跨订单成组的**真库**读数：池内两张单各一扇可并排矮窗 ⇒ 合计 1 行 3 米（不是 2 行 6 米）+ 幂等闸 + 不损失客户（源: cases/product.yml）──
_CASE_PR_071 = EvalCase(
    id='PR-071',
    legacy_id='',
    title='🔴 跨订单成组的**真库**读数：池内两张单各一扇可并排矮窗 ⇒ 合计 1 行 3 米（不是 2 行 6 米）+ 幂等闸 + 不损失客户',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['跨订单成组派单的真库落账读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 2·**跨订单并排 ⇒ 3 米而不是 6 米**：真库夹具（门幅 2.8、窗高各 1.1、各需 3 米、同批次同加工类型的两张单）下，池级一次求解 ⇒ 排料器**1 行**（行长度 = 最大值 3 米）、`Σ(formula)=6`、`Σ(−delta)=3`、批次余量 60 → **57**；**同参数对照**逐单派 ⇒ **2 行**、合计 **6 米**（同一测试内对照打印 ⇒ 「3 而不是 6」不是自说自话）。', '判据 2·**落账仍按各自的加工单**：3 米拆成 2 行、两行分属 `JG-5169-A` 与 `JG-5169-B`（`COUNT(DISTINCT processing_order_no)=2`）—— 一单一加工单的约束不变，池化只改「排料与批次分配在池级求解」。', '判据 4·**预览 == 落账**：预览算式 `Σ(formula − planned)` == 真库 `Σ(formula_meters − planned_meters)` == 实体派生的 `Σ saved_meters`（三腿同值 = 3）；对照逐单派口径算出的是 0 ⇒ 该断言有判别力。', '判据 3·**不倒退（跨批次不得成组）**：两张单分属不同批次 ⇒ 每一行 `planned == formula`、合计 6 米，且池级求解与逐单派**逐值相同**（成组键含批次是 #5158 口径，本单不动）；红证：把成组键去掉批次 ⇒ 跨批次也成组 ⇒ 判据红。', '判据 6·**幂等**：重复落同一张单 ⇒ 被 `uk_batch_consumption_line` 挡下（SQLSTATE **23505**）、台账行数不变、批次余量不变。**注入式红证**：`DROP INDEX uk_batch_consumption_line`（DDL 取自 `docs/sql/schema.sql` 原文）⇒ 第二遍**真的进账**（行数 2、余量 60−3−3=54）⇒ 证明拦下它的确实是这个闸；复原后索引仍在。', '判据 7·**不损失客户**：`product_skus.stock` 与 `stock_ledger_entries` 指纹**一字不动**（池化只动批次实物账）；公式口径 `Σ formula_meters` 在池化派与逐单派下**逐值相同**（对客口径不由排料方式决定）。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-072 [NORMAL] 池化三个 HTTP 端点的装配：`/pool` 上限可配、`/preview` 只读、`/dispatch` **不传 pooled ⇒ 下传 null**（缺省关的入口守卫）（源: cases/product.yml）──
_CASE_PR_072 = EvalCase(
    id='PR-072',
    legacy_id='',
    title='池化三个 HTTP 端点的装配：`/pool` 上限可配、`/preview` 只读、`/dispatch` **不传 pooled ⇒ 下传 null**（缺省关的入口守卫）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看板/文员调用池化端点（非 LLM 行为，由 MockMvc 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**缺省关的 HTTP 入口守卫**：`POST /api/admin/production/pool/dispatch` 不传 `pooled` ⇒ 控制器下传 **null**（服务侧的 `POOLED_DEFAULT_ENABLED` 是**唯一**的缺省值来源）；这一层若写死 true（或在 DTO 上再写一个缺省值），池化就会对所有既有调用方默认生效 ⇒ 记录期基线被污染。`pooled=true` ⇒ 原样下传（池化必须**显式**开启）。', '判据 5·`GET /api/admin/production/pool` 不传 `maxWaitHours` ⇒ 下传 null（服务侧用缺省 24 小时，**不在控制器里编造**）；传 `6` ⇒ 原样下传（上限可配）；响应回 `maxWaitHours` / `poolingEnabled=false` / `overdueCount`（池**看得见** ≠ 池化**已开启**）。', '判据 4·`POST /api/admin/production/pool/preview` 把 `orderIds`/`batches`/`assignmentRule` 原样下传，响应回 `formulaMeters`（6）/`savedMeters`（3）/`assignmentRule` 口径 —— 预览是只读端点（不建加工单、不落台账）。'],
    skip_reason='[backend-contract] 端点装配与缺省下传（无黄金策工具面）⇒ 由 MockMvc 单测覆盖，不进入 agent-eval 冒烟',
    tags=['dispatch-pool', 'processing-order', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-076 [NORMAL] 🔴 真库：同货号、错颜色/门幅的批次 ⇒ `BATCH_SKU_MISMATCH` 400 + **零落账**（红证：改前读侧恒 null ⇒ 同一夹具**静默扣账**）（源: cases/product.yml）──
_CASE_PR_076 = EvalCase(
    id='PR-076',
    legacy_id='',
    title='🔴 真库：同货号、错颜色/门幅的批次 ⇒ `BATCH_SKU_MISMATCH` 400 + **零落账**（红证：改前读侧恒 null ⇒ 同一夹具**静默扣账**）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['跨 SKU 批次护栏的真库读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**跨 SKU ⇒ 显式拒绝**：`plan` 对「同一个货号、错颜色/门幅」的批次抛 `BATCH_SKU_MISMATCH`（HTTP 400）；文案点名对象（批次号 + 批次所属 SKU + 订单行要的 SKU），`suggestion` 给可行动处置（按该行的颜色/门幅重选）。跨商品那一道判据独立成立（本来就生效）⇒ 本单补的正是「同货号、跨 SKU」这一格。', '🔴 判据 1·**零落账**：拒绝发生在 `plan`（只读段，写面在 `apply`）⇒ 被拒批次在真库台账里 **0 行**、批次余量一字不动（60 仍是 60），不留下「有加工单、扣了半截」的半成品。', '🔴 **红证（改前形态 = 静默落账，实测不是推断）**：同一夹具把 SKU 码换成改前读侧必然产出的 `null`（既有路径读的是快照里**不存在**的 `skuCode` 键 ⇒ 恒 null；护栏第一个条件 `hasText(d.skuCode())` 因此恒假 ⇒ 整条判据 no-op）⇒ 真库读数 = 台账 **1 行**、扣 **3 米**、批次余量 60 → **57**，三个数在同测试内打印并与上面那条对照。', '判据 1·**可被触达的路径**：`generate` 允许逐行显式传 `batches`（文员手选批次号）⇒ 手选一个同货号但错颜色/门幅的批次，改前就是上述静默扣账。'],
    skip_reason='[backend-contract] 批次账的真库读数（无黄金策工具面）⇒ 由真 PG（initdb+pg_ctl）Java 判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-sku-guard', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-077 [NORMAL] 🔴 读侧取键（装配）：逐单派工行拿到的 SKU 码 = 快照**实际写入**的 `sku` 键（改前读 `skuCode` ⇒ 恒 null ⇒ 护栏与建议值过滤整条 no-op）（源: cases/product.yml）──
_CASE_PR_077 = EvalCase(
    id='PR-077',
    legacy_id='',
    title='🔴 读侧取键（装配）：逐单派工行拿到的 SKU 码 = 快照**实际写入**的 `sku` 键（改前读 `skuCode` ⇒ 恒 null ⇒ 护栏与建议值过滤整条 no-op）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['生成加工单时的派工入参装配（非 LLM 行为，由 Mockito 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1 的**读侧一半**：不启用池化（逐单派）时，`plan` 收到的 `Designation.skuCode` **非 null** 且逐值等于快照里的 SKU 码（快照由 `buildSnapshot` 写入：`processing_info.sku` 与 `processing_info.skuCode` **都落 `sku` 这一个键**，快照里没有 `skuCode` 键）。红证 = 改前该值为 `[null]`；它的真库后果（静默扣账）见 PR-076 的对照读数。', '判据 3 的**读侧一半**：按规则自动补位时 `suggestedBatchNo` 收到的过滤入参 = **同一个** SKU 码（改前收 `null` ⇒ 过滤条件整条 no-op ⇒ 同货号错颜色/门幅的批次也能被补位；真库读数见 PR-078）。补位挑出的批次进 `plan` 时带着同一个 SKU 码（两处口径同源，不另立第二份）。', '判据 2·**合法路径逐值不变**：正确 SKU ⇒ 加工单照旧生成成功；派工需求 `meters` 仍是公式口径米数（向上进位到 0.1，与销售账同函数）、排料定尺三项（加工类型 / 窗高 / 分幅数）仍**逐值来自快照**（#5158 口径本单不碰）。'],
    skip_reason='[backend-contract] 派工入参装配（无黄金策工具面）⇒ 由 Mockito 单测覆盖，不进入 agent-eval 冒烟',
    tags=['dispatch-sku-guard', 'batch-ledger', 'processing-order', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-078 [NORMAL] 🔴 真库：同 SKU 的批次落账**逐值不变**（含 #5158 排料口径）+ 建议值按 SKU 过滤 + 反向护栏（批次侧无色号不擅自收紧）+ 幂等（源: cases/product.yml）──
_CASE_PR_078 = EvalCase(
    id='PR-078',
    legacy_id='',
    title='🔴 真库：同 SKU 的批次落账**逐值不变**（含 #5158 排料口径）+ 建议值按 SKU 过滤 + 反向护栏（批次侧无色号不擅自收紧）+ 幂等',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['同 SKU 批次的真库落账读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 2·**合法路径逐值不变**：正确 SKU 的批次 ⇒ 落账两行，`formula_meters` = 3 / `planned_meters` = **1.5**（两扇「窗高 1.1 + 卷边 0.3」的矮窗在门幅 2.8 上并排 ⇒ #5158 排料口径**仍生效**，不是退化成「一律按公式扣」）、`Σ(formula − planned)` = 3、`unit_cost` = 12.5、`before_qty`/`after_qty` = 60 → 58.5 → 57 逐值可读、批次余量 60 → **57**。', '🔴 判据 3·**建议值过滤生效**：同货号、错门幅但**入库更早**的批次在改前形态（读侧传 `null`）下**会被建议**（FIFO 首选 —— 判别性来自夹具顺序）；带上正确 SKU 码 ⇒ 建议值换成同 SKU 的那个批次，`fifo` 与 `best_fit` 同源同一份候选（缺省仍是 `fifo`，本单不改指派策略默认值）。', '🔴 判据 2 的**反向护栏**（防「修成一律拒绝」）：批次侧 `sku_code` 为 **NULL**（导入批次未带色号 —— 如实登记的边界）⇒ **不擅自收紧**、仍按 `productId` 那道判据放行并正常落账；谁把 `hasText(batch.getSkuCode())` 去掉，这条立刻变红。', '判据 5·**幂等不变**：同一加工单重复落账被 `uk_batch_consumption_line` 挡下（SQLSTATE 23505），台账行数与批次余量都不再变化（沿用 #5145 闸）。', '判据 4·**不损失客户**：`product_skus.stock` / `price` 与 `stock_ledger_entries` 行数指纹一字不动（批次护栏不碰销售账）。'],
    skip_reason='[backend-contract] 同 SKU 落账与建议值的真库读数（无黄金策工具面）⇒ 由真 PG（initdb+pg_ctl）Java 判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-sku-guard', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-079 [NORMAL] 🔴 订单级加急/到货日字段（V120）：**零联动**（⇎ 售后 priority）+ **缺省不变** + 改单三态 + 订单页 UI 录入位（源: cases/product.yml）──
_CASE_PR_079 = EvalCase(
    id='PR-079',
    legacy_id='',
    title='🔴 订单级加急/到货日字段（V120）：**零联动**（⇎ 售后 priority）+ **缺省不变** + 改单三态 + 订单页 UI 录入位',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在订单上直接标加急 / 填客户要求到货日（非 LLM 行为，由 Java 单测 + 真 PG 判据 + 前端 vitest 覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**零联动（双向，真库）**：`orders` 与 `after_sales_tickets` 各有一行真夹具 ⇒ 改订单 `is_urgent` 后 `after_sales_tickets.priority` **逐值不变**（且工单行数不变 —— 防「改了另一行」的假通过）；反向改工单 priority ⇒ 订单 `is_urgent` 逐值不变。用户裁定逐字「加急不能跟售后工单绑定，得在订单上直接做」。**红证** = 把两者接到同一来源（或让 `updateUrgency` 顺手同步 priority）⇒ 真库断言与源码级断言同时红（源码级：`updateUrgency` 方法体不得出现 ticket/priority/after_sales 字样；`Order` 实体不得有 `priority` 字段）。', '🔴 判据 1·**只写两列**：`updateUrgency` 的 SET 子句白名单 = `is_urgent` / `required_delivery_date` / `updated_at`；**不得**出现 `total_amount` / `actual_amount` / `discount_amount` / `refund_amount` / `status` / `priority`（红证 = 顺手多写一列即红）。', '🔴 判据 2·**缺省不变（真库）**：建单 INSERT **不传**两列 ⇒ `is_urgent` 落 `false`、`required_delivery_date` 落 `NULL`（= 未指定，不回填不猜）。DTO 侧两字段必须是**可空包装类型**（`Boolean` / `LocalDate`）⇒ 未传不进 INSERT ⇒ 落列默认；缺省不得变成「总是加急」。', '判据 7·**改单三态**：`isUrgent=null` = 不改（只改加急时到货日**不进 SET**，不被顺手抹掉）；`requiredDeliveryDate=""` = **清空**（必须真的写这一列 —— MyBatis-Plus 默认 NOT_NULL 策略会跳过 null 字段，走 `updateById` 永远清不掉）；`YYYY-MM-DD` = 设值。**fail-closed**：`2026/10/01` / `"  "`（全空白）/ `2026-13-45` / 两字段都不传 ⇒ 显式拒绝，且**一次 update 都不发**（红证 = 静默回落成「清空」⇒ 拒绝断言红且「零写入」断言红）。', '🔴 **wire 契约**：JSON 键名必须是 `isUrgent`（不是 `urgent`）—— 红证 = 把 DTO 字段从 `Boolean` 改成原生 `boolean` ⇒ Lombok getter 变 `isUrgent()` ⇒ Jackson 属性名变 `urgent` ⇒ 前端读不到加急标记。到货日出线格式 `YYYY-MM-DD`，其前提（`application.yml` 的 `write-dates-as-timestamps: false`）**读真值源**断言，不是在测试里自选格式。', '判据 6·**不损失客户（真库双向）**：标加急/填到货日、以及取消加急/清空到货日 ⇒ `total_amount` / `actual_amount` / `discount_amount` **逐值不变**。', '**订单页 UI（§15.1 断言结果可见）**：订单新建页与详情页的加急开关 + 到货日选择器写进请求体；**不勾/不填 ⇒ 请求体里不出现这两个键**（不得默认勾上加急）；列表页加急角标随值出现/消失（红证 = 把缺省改成「总是加急」⇒ 角标断言红）。**版式（issue #5915，用户 2026-10-01 逐字「要求到货日能否和日期选择控件放一行？」）**：新建页那一格的 label 与原生日期控件在**同一个 flex 行容器**里（label 不再是 `block + mb-1.5` 独占一行、控件不再 `w-full`），label 的 `htmlFor` ↔ 控件 `id` 关联保持；下方提示仍另起一行、**文案一字未改**。红证 = 把 label 改回 `block`、或给控件加回 `w-full` ⇒ frontend/admin-web/tests/unit/pages/orders-urgency.test.tsx 的行容器/宽度断言红。'],
    skip_reason='[backend-contract] 订单字段与迁移的真库读数（无黄金策工具面）⇒ 由真 PG（initdb+pg_ctl）Java 判据 + 前端 vitest 覆盖，不进入 agent-eval 冒烟',
    tags=['order-urgency', 'pool-board', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-080 [NORMAL] 🔴 加急插队：加急单**不进池**、立刻单派（`pooled=false`）；混进成批批次 ⇒ **整批显式拒绝**（不静默少派）（源: cases/product.yml）──
_CASE_PR_080 = EvalCase(
    id='PR-080',
    legacy_id='',
    title='🔴 加急插队：加急单**不进池**、立刻单派（`pooled=false`）；混进成批批次 ⇒ **整批显式拒绝**（不静默少派）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在看板上对加急单点一下派工（非 LLM 行为，由 Java 单测 + 前端 vitest 覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 3·**加急不进池**：`is_urgent=true` 的订单**不出现在任何** `groups[].lines`（不是成批候选），只出现在 `urgentLines`（插队区），并带 `isUrgent=true` / `requiredDeliveryDate` / `deliveryDaysLeft`；`orderCount`+`lineCount` 是**池内（非加急）**口径，`urgentCount` 单独计数。**一张单都不丢**：池内 + 插队区的订单集合 = 全部订单（红证 = 让加急单照旧进池 ⇒ 该断言红）。', '🔴 判据 3·**成批批内拒绝（fail-closed）**：`/dispatch` 与 `/preview` 带 `pooled=true` 且批次里含加急单 ⇒ **整批显式拒绝**（消息点名**订单号** + 可行动处置：单独派 = 插队，或先取消加急），且**一行都不写**。**红证（实测单点变异）** = 摘掉 `assertNoUrgentInPooledBatch` 在成批路径上的调用 ⇒ 拒绝断言当场红。判别力：拒绝文案**不得**是逐单路径的既有文案（`不允许生成加工单`）—— 两个不同失败面必须能机器分辨。', '判据 3·**加急不侵入单派**：同一个加急单走 `pooled=false` ⇒ 抛的仍是**既有**失败文案（用「状态非 confirmed」的夹具），消息里**不含**「加急」⇒ 加急只改「是否入池/派单时机」，不改单订单路径的任何一格（判据 2 的「单订单路径错误文案」）。', '**看板上的一个动作**：插队区每行一个「加急插队派单」按钮 ⇒ 调同一个 `/dispatch` 端点 + `pooled=false` + 单订单；成功后在**看板上可见地**出现该加工单号（§15.1：断言结果可见，不停留在「API 被调用」）。', '🔴 **整单派工 ⇒ 整单逐行指派（issue #7968）**：一张**多套成品帘**的加急 / 外发单，点任意一行「立即派单」⇒ `/dispatch` 的 `batches` 必须带**该单在逐单派表里的全部行**（`orderIds` 去重为 1 条、`itemId` 一条不少）。只带被点的那一行 = 整单派出而其余各套在加工单快照里没有 `batchNo`、也不落批次台账（用户 2026-10-28 现场）。**红证** = 把 `dispatchSingle` 退回 `buildPoolRequest([line], …)` ⇒ `production-pool-urgent.test.tsx` 的多套用例当场红（实际只回被点的那一套）；`singleDispatchLinesOfOrder` 的单项判据在 `pool-board.test.ts`（加急段 / 外发段各一例）。**边界**：整单某行无可用批次 ⇒ 整单派单显式失败（与成批派单同口径，fail-closed）。', '🔴 **逐单立即派区 = 订单级展示 / 订单级动作（issue #7974）**：一张多套成品帘的加急 / 外发单在表里**恰好一行**、**恰好一个**「立即派单」按钮，行内列出该单全部套的物料与米数（信息不丢）。**红证（实测 old page）** = 退回按 `singleDispatchLines` 逐套渲染 ⇒ `production-pool-urgent.test.tsx` 的「恰好一行 / 恰好一个按钮」断言当场红（读数：`expected [...] to have a length of 1 but got 2`）；`singleDispatchOrders` 归并判据在 `pool-board.test.ts`（订单序 = 首次出现序 / 组内行序不变 / 空看板）。'],
    skip_reason='[backend-contract] 加急插队的判定与拒绝（无黄金策工具面）⇒ 由 Java 单测 + 前端 vitest 覆盖，不进入 agent-eval 冒烟',
    tags=['order-urgency', 'queue-jump', 'pool-board', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-081 [NORMAL] 🔴 智能派单可用化：**排序是字段的真实消费者**（加急优先 / 到货日临期优先，`null` 排最后）+ 成批预览**逐值不说谎** + 一键成批派单（源: cases/product.yml）──
_CASE_PR_081 = EvalCase(
    id='PR-081',
    legacy_id='',
    title='🔴 智能派单可用化：**排序是字段的真实消费者**（加急优先 / 到货日临期优先，`null` 排最后）+ 成批预览**逐值不说谎** + 一键成批派单',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在智能派单上看积压、勾单、看预计节省、一键成批派单（非 LLM 行为，由 Java 单测 + 真 PG 判据 + 前端 vitest 覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 5·**排序是真实消费者（服务端唯一口径）**：键序 = 到货日升序（`null` 排**最后**）→ 等待时长降序 → 进池时刻升序 → 单号升序。夹具**刻意让「单号序 ≠ 期望序」「输入序 ≠ 期望序」**⇒ 断言有判别力。**红证（实测单点变异）** = 把排序键退化成**单号序** ⇒ 该断言当场红；`null` 被当成最紧急同样红（未指定不得插队）。加急 / 外发同属「不进池、逐单立即派」（issue #7943）⇒ 两段合并成**一张表**、排在成批区**之后**（用户 2026-10-27 裁定：成批合并是页面主操作 ⇒ 置顶）；成批候选（`groups[].lines`）里**没有**加急 / 外发行，行序 = 两个服务端有序数组的拼接序（加急 → 外发），前端不重排。', '🔴 判据 5·**缺省不变**：没有加急单、没有到货日 ⇒ 第一把键恒相等、第二把（等待时长降序）与 `createdAt` 升序**同序** ⇒ 行序与今天**逐值相同**（既有 `#5169` 池用例的等待时长读数在同夹具下改前改后同值；本单顺手修正了该夹具「反序喂 mock」的失真 —— 真实查询是 `orderByAsc(createdAt)`）。', '🔴 判据 4·**预览不说谎**：看板的「预计节省」`savedMeters = formulaMeters − pooledPlannedMeters` 与落账 `Σ saved_meters`（= `Σ(formula_meters − planned_meters)`）**逐值相等**（真库 SQL 读数 == 实体派生读数 == 预览算式，三腿同值）；另分开回 `perOrderPlannedMeters` / `poolingGainMeters`，**不把 #5158 已有的单订单内并排算成池化的功劳**。前端**不重算**这两个数（渲染服务端值 —— 两套口径正是「预览说谎」的成因）。', '**池视图字段齐**：单号 / 物料（商品 × 颜色 × 门幅）/ 需求米数 / 等待时长 / 加急标记 / 到货日 + `maxWaitHours` / `poolingEnabled`（缺省关必须看得见）/ `overdueCount` 与**带对象名字**的 `warnings`（含加急单 —— 加急更不该被压住）。', '**一键成批派单（§15.1）**：勾选 ⇒ 调 `/preview` 展示 预计领料 vs 逐单公式米数 = 预计节省；点「一键成批派单」⇒ 调 `/dispatch`（`pooled=true`）且**逐单结果可见**（成功显示加工单号、失败显示 message），看板刷新。', '🔴 存量行不炸读面（issue #5550）：`order_items.processing_info` 为 **NULL** 的明细行（真库实证：待派 29 行里 15 行如此）**不得**让 `GET /api/admin/production/pool` NPE 500 —— 该行按「既无加工项也无 `saleForm`」的**既有**语义跳过（不成派单候选、不产出行；整单没有快照时不进池），而**同池的正常行一行不丢**（同夹具里正常单照旧成组、计数逐值不变）。**红证** = 摘掉 `buildSnapshot` 的 `pi == null` 判定 ⇒ `PoolBoardUrgencyTest#poolReadFaceSurvivesLegacyItemWithoutProcessingInfo` 当场 NPE 红。**类级元守卫** = `ProcessingInfoNullSafetyMetaGuardTest#everyNormalizationCallSiteHandlesNull`（归一化入口的每一处结果解引用都必须先判 null；无判定的新调用点即红，报告给文件:行与出口）。', '**全选（issue #6520）**：成批区标题栏一个「全选 N 单」按钮 —— 候选口径 = `batchGroups` 的**跨料组并集**（**加急单在 `urgentLines`、不在候选内**，全选勾不到它，否则整批必被 422 拒绝）；全选中时按钮变「取消全选」并清空；无候选时禁用。红证 = `production-pool-batch.test.tsx` 的「全选」用例：断言的是**每一行真的被勾上**且 `/preview` 的 `batches` 逐行带指派（不是只改计数文案），并断言加急行**没有**勾选框。', '**超时未派告警不占屏（issue #6521）**：旧形态「每单一行红字」的常驻大红块（10 单 = 整屏）改为**一行摘要常驻 + 逐单明细按需展开** —— 摘要 = 条数 + 最长等待阈值 + 最久已等（数字全部来自服务端 `overdueCount` / `warnings[].waitHours` / `maxWaitHours`，前端只格式化）；逐单明细默认**不渲染**（折叠 ≠ CSS 隐藏）⇒「不占屏」是可断言的机器读数；展开后高度封顶 + 内部滚动，页面高度不随超时单数增长；`overdueCount = 0` ⇒ 整块不存在。', '🔴 **展示名与标识分离（issue #6523）**：料组分组的 `materialKey`（= `productId|skuCode`，`productId` 是 UUID）**不再上屏** —— 它是**机器键**（前端 React `key` / 分组判据 / 其它消费者），**逐字不变**；看板标题渲染服务端新增的 `materialLabel`（人话：`商品名 × 颜色/门幅`，由服务端组装 —— 前端拼字符串就是第二份会漂的口径）。真机实测（2026-10-08，`/production/pool`）：旧形态标题渲染成 `a61daac33e1a49974577d3ca81c4500b|SD07演示-2.8-8141273`。判据 = `backend/admin-api/src/test/java/com/migao/admin/service/PoolBoardUrgencyTest.java::poolGroupExposesHumanLabelWhileMaterialKeyStaysTheMachineKey`（① `materialLabel` 不含 `|` / 不含 `productId` / 不含 UUID 形态串 ② **负控**：`materialKey` 仍逐字等于 `productId|skuCode`）+ `frontend/admin-web/tests/unit/pages/production-pool-batch.test.tsx` 的组标题用例（夹具刻意用真机形态的 `materialKey`，标题断言 `materialLabel`、断言 DOM 里**没有** `|` 与 UUID）。**红证（实测）** = 把页面标题退回 `{group.materialKey}` ⇒ 该用例当场红，失败读数里逐字出现 `a61daac33e1a49974577d3ca81c4500b|米白/2.8m`。`data-testid`（`pool-group-<i>`）一律不变。', '🔴 **超时告警文案只陈述「阈值 + 该做什么」（issue #6524）**：`PoolWarning.message` 由 `已超过最长等待 <阈值> 小时，请合并派单或单独派单` 构成 —— **阈值**取自本次生效的 `maxWaitHours`（真值渲染，**不许写死** 24）；**不念同屏已有的列**（单号在明细表已有独立列、实际等待时长也有独立列 ⇒ 文案里不重复），**去掉**口语责备尾巴「（不要一直压着不派）」。**既有口径不放松**：`PoolWarning` 的字段（`orderId` / `orderNo` / `waitHours` / `message`）与前端 `data-testid`（`pool-warning-<orderId>`）一律不动 —— 「不得静默压单 / 告警必须带对象」由 `orderNo` 字段 + 明细表独立列承载（前端逐行渲染，现状即如此）。判据 = `PoolBoardUrgencyTest.java::overdueWarningCopyStatesThresholdAndActionWithoutRepeatingColumns`（正控：含「请合并派单或单独派单」与阈值 `6`；负控：不含 `24`（缺省值不得落文案）/不含单号/不含等待时长/不含责备尾巴；另断言三个字段仍在）+ `ProcessingOrderServiceTest.java::poolGroupsByMaterialAndWarnsOverdueOrders` 的同口径断言。**红证（实测）** = 把服务端文案注入回旧形态 ⇒ `PoolBoardUrgencyTest` 当场红（失败读数逐字给出旧串）；把前端夹具的 `message` 换回旧形态 ⇒ vitest 该用例红。', '**跨模块契约（issue #6523）**：`ProductionPoolViews.PoolGroup` 新增 `materialLabel` 字段 ⇒ 前端 `frontend/admin-web/src/types/index.ts` 的 `PoolGroup` 同步为**必填**（`materialLabel: string`）—— 依赖 `tsc --noEmit` 做**机器级**全覆盖：任何漏了该字段的看板夹具都会编译红（本包实测：`production-pool-urgent.test.tsx` 的夹具就是这样被点出来补齐的）。'],
    skip_reason='[backend-contract] 排序/预览/成批派单（无黄金策工具面）⇒ 由 Java 单测 + 真 PG 判据 + 前端 vitest 覆盖，不进入 agent-eval 冒烟',
    tags=['pool-board', 'order-urgency', 'dispatch-pool', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-082 [NORMAL] 🔴 V120 迁移质量（**两遍幂等** + 列类型/默认/NOT NULL 终态对账 + schema.sql 同步）+ 加急/到货日**透传进加工单快照**（源: cases/product.yml）──
_CASE_PR_082 = EvalCase(
    id='PR-082',
    legacy_id='',
    title='🔴 V120 迁移质量（**两遍幂等** + 列类型/默认/NOT NULL 终态对账 + schema.sql 同步）+ 加急/到货日**透传进加工单快照**',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['迁移与快照的真库读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 7·**V120 同一库上连续执行两遍都成功**（`ADD COLUMN IF NOT EXISTS` 容忍 bootstrap 路径已建的列；`SET NOT NULL` / `SET DEFAULT` / 注释 / 文末终态对账 `DO` 块**第二遍仍全部成立**）⇒ 幂等可重复执行 + 前置 fail-closed（缺 `orders` 表即抛且不兜底建表）。', "🔴 判据 7·**列形态逐字对账（读 `information_schema`，不靠 Java 类型推断）**：`is_urgent` = `boolean` ∧ `is_nullable='NO'` ∧ 列默认含 `false`（⇒ **无第三态**：「未标加急」与「明确不加急」同值）；`required_delivery_date` = **`date`**（不是 `timestamp` —— 只有日期精度的事实带时刻会在别的时区把「10 月 1 日」读成 9 月 30 日）∧ 可空（「未指定」有独立真值）。`docs/sql/schema.sql`（bootstrap 路径不跑迁移链）已同步终态。", '🔴 **透传进快照（真库 JSONB 往返）**：订单级 `isUrgent` / `requiredDeliveryDate` 随加工单生成写进 `items_snapshot` **每一行**（订单级事实只能逐行固化），经真库 JSONB 编解码往返后仍是**布尔 `true`**（不是字符串 `"true"`）与 `YYYY-MM-DD` 字符串，且能被 `ProcessingOrderResponse.ProcessingOrderItemBrief` 解析出 `items`（**不为 null**）。⚠️ 这是本仓一处**静默退化**点：快照里出现 DTO 未声明的键 ⇒ `convertValue` 抛错被 catch ⇒ `items` 整段变 null 而接口照样 200 ⇒ 本用例另带一条**红证对照**（多一个未声明键 ⇒ 解析必抛）证明上一条不是碰巧通过。', '**缺值口径**：`isUrgent` **恒落键**（`false` 是**真值** —— 显式「否」不得当成「未填」丢弃）；`requiredDeliveryDate` **缺值不落键**（写空串/占位会把「未指定」读成一个日期）⇒ 既有单的快照在缺省下与该键族引入前**逐字相同**（零污染）。', '**迁移指纹账本只追加**：`tests/unit_ci_workflows/migration_fingerprints.json` 只新增 V120 一条，旧条目零改动（判据本体 = `test_migration_immutability.py`，挂 MC-012）。'],
    skip_reason='[backend-contract] 迁移与快照的真库读数（无黄金策工具面）⇒ 由真 PG（initdb+pg_ctl）Java 判据覆盖，不进入 agent-eval 冒烟',
    tags=['order-urgency', 'migration', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-083 [NORMAL] 渲染腿**转义解码**：生成物取值与真值（`yaml.safe_load`）逐值相等（修前 33 处不同 / 163 个多余转义）（源: cases/product.yml）──
_CASE_PR_083 = EvalCase(
    id='PR-083',
    legacy_id='',
    title='渲染腿**转义解码**：生成物取值与真值（`yaml.safe_load`）逐值相等（修前 33 处不同 / 163 个多余转义）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['改 `.github/cases/*.yml` 后重渲染生成物（非 LLM 行为，由 tests/unit_ci_workflows 单测验证）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**逐值相等（本单的靶心）**：真用例库 25 文件 ⇒ 产物（`tests/agent_eval/eval_cases.py` 的 `EvalCase(...)` **字面量**，用 `ast.literal_eval` 取、**不 exec**）与真值（`yaml.safe_load`）逐 `(文件, 用例 id, 字段)` 相等。判据本体 = `tests/unit_ci_workflows/test_render_leg_escape_decode.py` 的 `test_artifact_values_are_value_identical_to_truth`；比较器 = `tests/unit_ci_workflows/render_leg_compare.py`（**唯一实现**，别处不许再写第二份）。**红证（修前实测）**：33 处不同，逐处清单口径 = `(文件, 用例, 字段)` —— 代表三处：`AS-003.data_checks`（真值 `^AS-\\d{8}-\\d{4}$` / 修前 `^AS-\\\\d{8}-\\\\d{4}$`）、`CH-009.user_inputs`（真值 `__FORM__|{"customer_name":"张三"…}` / 修前每个引号前多一个反斜杠）、`PG-055.data_checks`（真值 `"applicable"` / 修前 `\\"applicable\\"`）。', '🔴 判据 2·**转义序列零外溢**：产物侧不得比真值多出任何转义序列（`\\"` / `\\\\` / `\\/` / `\\n` / `\\t` / `\\r`）。**修前实测 163 个**（`\\"` 148 + `\\\\` 9 + `\\/` 1 + `\\n` 5）；判据本体 = 同文件 `test_artifact_has_no_escape_overflow`（与判据 1 分开写：这条**只在「转义未解码」这一族**上红，诊断信息直接点名是哪个转义序列）。**单点变异红证** = 回滚 `.github/yaml_light.py` 的双引号解码（`_parse_scalar` 里 `_unescape_double(inner) if \'\\\\\' in inner else inner` 退回 `inner`）⇒ 该判据单独变红，且诊断信息给出外溢计数。', '🔴 判据 3·**「生成物新鲜度」抓不到这条（所以必须单列判据）**：那条检查比的是「能否由当前源重渲染出**已提交的**产物」，**不是**「产物是否等于真值」⇒ 一份**稳定地错**的产物永远绿。实证：修前那两个生成物在 main 上**长期"新鲜"**，而 33 处取值与真值不同（连带交给 LLM 的判据文本与真值不同；任何按值检索/比对的工具都会漏）。', '判据 4·**零 diff 自证（稳定点）**：同参数再跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases --out-md docs/testing/mibao-verification-cases.md` ⇒ 两个生成物**逐字节相同**，且与已提交版本**逐字节一致**；判据本体 = 同文件 `test_render_is_a_stable_fixpoint_and_matches_committed`（渲染两次 + 对齐已提交）。⚠️ 本单**预期生成物会变**（那正是修复本身）⇒ 生成物由 `render_cases.py` 重生成，**一个字面量都不许手改**。'],
    skip_reason='[backend-contract] 渲染腿取值保真（CI 机具面，无黄金策工具面）⇒ 由 tests/unit_ci_workflows 单测验证，不进入 agent-eval 冒烟',
    tags=['ci', 'case-library', 'render-leg', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-084 [NORMAL] 渲染腿比较器**落库**（唯一实现）+ **「0 条」必须判红**（比较器坏了 ≠ 没有差异）（源: cases/product.yml）──
_CASE_PR_084 = EvalCase(
    id='PR-084',
    legacy_id='',
    title='渲染腿比较器**落库**（唯一实现）+ **「0 条」必须判红**（比较器坏了 ≠ 没有差异）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['复核「生成物是否等于真值」（非 LLM 行为，由 tests/unit_ci_workflows 单测验证）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**口径显式化**：比较器 `tests/unit_ci_workflows/render_leg_compare.py` 是**唯一实现**（真值 = `yaml.safe_load`；产物 = 生成物里的**字面量**，`ast.literal_eval` 取、**不 exec**）。"多少处"必须同时说口径，三个读数分开取：`sites` = 取值不同的 `(文件, 用例 id, 字段)` 三元组数、`leaf_diffs` = 不同的叶子字符串数、`escape_overflow` = 产物侧多出的转义序列逐类计数（非重叠）。**红证 = 只手写一个数而不说口径即无法复算** —— 本单的由来正是这个：#5179 原文写「36 处」（31 处 `\\"` + 5 处 `\\\\`/`\\/`），而那个脚本是 heredoc、**未入库**，且当时用例数是 424（现 428）⇒ **口径不可复算**；可复算读数是 **33 / 45 / 163**。落地时**不把 33 写成 36**。', '🔴 判据 2·**「0 条」是「比较器坏了」，不是「没有差异」**：`Report.assert_sane()` 在任一侧条数为 0、或两侧 id 序列不是逐位相同时**抛错**。为什么必须有这条：#5179 的复核方**两次**独立测量都"量不出来"，成因正是真值侧解析出 **0 条** —— 而 0 条与"完全一致"在读数上**长得一模一样**（一次假绿就此诞生）。**红证（两侧都要红，只红一侧等于只守了一半）** = 产物侧换成没有 `EvalCase(...)` 的文件 ⇒ `test_comparator_reds_when_a_side_is_empty` 必红；`--cases` 指到空目录 ⇒ 同一判据的另一半必红。', '🔴 判据 3·**判别力自证（不会红的断言 = 空断言）**：修完之后"零差异"是常态 ⇒ 判据 1 永远是绿的，读者无从知道它"到底是守住了，还是根本不会红"。⇒ `test_value_diff_guard_can_actually_go_red` 把当前产物按**改前形态**重新转义（`\\` → `\\\\` 先做、`"` → `\\"` 后做）喂给同一条判据 ⇒ 必须报出差异且 `escape_overflow` 非空。**边界照实登记**：该自证覆盖 `\\"` / `\\\\` 两族（33 处里的 32 处），`\\/` 那 1 处需要**源码侧**信息（源写 `\\/` 而真值是 `/`）⇒ 由 #5179 的 PR body 里 `git show origin/main:` 的逐处对照承担，**不把"没覆盖"伪装成"已覆盖"**。'],
    skip_reason='[backend-contract] 用例库比较器与其健康断言（CI 机具面，无黄金策工具面）⇒ 由 tests/unit_ci_workflows 单测验证，不进入 agent-eval 冒烟',
    tags=['ci', 'case-library', 'render-leg', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-085 [NORMAL] 渲染腿保真度的**边界登记与死亡条件**（修好的形态必须移出登记表；未覆盖的不许说成已覆盖）（源: cases/product.yml）──
_CASE_PR_085 = EvalCase(
    id='PR-085',
    legacy_id='',
    title='渲染腿保真度的**边界登记与死亡条件**（修好的形态必须移出登记表；未覆盖的不许说成已覆盖）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['复核「还有哪些形态不保真、补上了会不会被发现」（非 LLM 行为，由 tests/unit_ci_workflows 单测验证）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**死亡条件按设计触发**：`tests/unit_ci_workflows/test_yaml_light_scalar_fidelity.py` 的 `STILL_UNFAITHFUL` 逐条断言"现在**仍然**不保真"。`escaped_*` 一族（`\\"` / `\\\\` / `\\/` / `\\n`）修好后，该表 4 条登记**当场变红**（`test_registered_gaps_are_still_gaps`）⇒ 已按红了的修法**移出登记表并加进 `CORPUS`**（改前它们是"有意不修"的绿）。**红证 = 把已修好的形态留在登记表里 ⇒ 该判据必红**（这正是发现登记表过期的方式，不许靠人记得）。', '🔴 判据 2·**仍不保真的形态逐条在册**（不把"没覆盖"伪装成"已覆盖"）：现存三种 —— ① **跨行 flow 集合**（`k: [a,` + 续行 `b]` ⇒ 取 `\'[a,\'`）；② **跨行裸标量**（`k: 第一行` + 缩进续行 ⇒ 续行不在值里）；③ **被引号包起来的 key**（`"a\\"b": 1` ⇒ 键不过 `_parse_scalar`、不解码）。三条真用例库各 **0 处**；每条都在 `.github/yaml_light.py` 模块头与登记表两处同步。', '🔴 判据 3·**未定义转义的两侧行为都被钉住**：`k: "a\\d"` ⇒ **PyYAML 拒绝**（`ScannerError`，那是标准 YAML 的语法错误）而宽松腿**原样保留** `a\\d`（不抛异常打断整份用例加载）；这类文件由渲染腿的严格判定（`.github/cases_yaml.py` 的 `require_strict`）拦下。判据本体 = `tests/unit_ci_workflows/test_render_leg_escape_decode.py` 的 `test_boundary_undefined_escape_is_not_taken_over`（**两侧都断言**：PyYAML 必须拒绝，否则"边界"名不副实）。', '判据 4·**真库零容忍（口径收紧，不是放宽）**：`test_real_library_values_are_py_yaml_identical` 现取真库与 PyYAML 的**每一处**取值差异 ⇒ 块标量 / 跨行标量 / 转义解码任一族再破都逐处点名。#5179 之前的放行口径是"差异都能由 `STILL_UNFAITHFUL` 解释"（修前实测 33 处全是 `escaped_*`）⇒ 修好后那条容忍口径**整条退场**。', '**越界声明（本单不做，防被读成已做）**：不改用例库**内容语义**；不动 `scripts/drift_audit_baseline.json` 与那 9 条豁免；**不动严格腿** `.github/cases_yaml.py`（严格判定唯一实现，一字未改）；不碰产品代码。'],
    skip_reason='[backend-contract] 解析器保真度的边界登记与死亡条件（CI 机具面，无黄金策工具面）⇒ 由 tests/unit_ci_workflows 单测验证，不进入 agent-eval 冒烟',
    tags=['ci', 'case-library', 'render-leg', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-086 [NORMAL] 自动成批派单：默认关（零读零写）+ 事件驱动（无计时器、AFTER_COMMIT）+ 三个挂载点只在既有业务之后且 fail-soft（通知抛异常不影响主流程）（源: cases/product.yml）──
_CASE_PR_086 = EvalCase(
    id='PR-086',
    legacy_id='',
    title='自动成批派单：默认关（零读零写）+ 事件驱动（无计时器、AFTER_COMMIT）+ 三个挂载点只在既有业务之后且 fail-soft（通知抛异常不影响主流程）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['自动成批的缺省（#6588 翻为**开**）与事件挂载点纪律（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=[],
    data_checks=['🔴 判据 1a·**缺省即开**（issue #6588，用户裁定「记录期已结束，可以翻默认」）：`AUTO_BATCH_DEFAULT_ENABLED=true` ⇒ **不传策略**的 2 参入口真的评估（池被读、`outcome.enabled()=true`），而不是走早返回。**红证 = 把缺省改回 `false`** ⇒ 本判据当场红（机具：`scripts/auto-batch-red-proof.py --only default_on`）。', '🔴 判据 1b·**显式关 ⇒ 零读零写**（不变式，翻缺省不放松）：开关为假（部署属性 `migao.production.auto-batch.enabled=false` / 显式策略）⇒ `autoBatchDispatch` **一个 mapper 都不碰**、一次 `generate` 都不调、连池都不查。**红证 = 摘掉 `!policy.enabled()` 那行关闸** ⇒ 本判据当场红（机具：同文件 `--only off_gate`）。', '判据 2·**事件驱动、不是计时器**：① 结构性 —— 触发链（`PoolChangeNotifier` / `AutoBatchDispatchListener` / `ProcessingOrderService`）**没有任何 `@Scheduled`**，且监听器是 `@TransactionalEventListener(phase = AFTER_COMMIT)`（提交前评估会读到「还没入池」的单 ⇒ 相位是正确性的一部分）；② 行为性 —— **没有到期的单**（进池 1~3 小时、到货日 30 天后）在条件满足时**当次事件内**即成批。**红证 = 把主触发改成「只在兜底扫描里」**（条件判定恒不成立）⇒ ②当场红。', '判据 1/10·**挂载点纪律**（四个挂载点：确认支付 / 入库过账 / 改单 / 取消）：① `InOrder` 断言「状态流转 → 库存副作用 → 通知」的**顺序**（挂到业务前面 = 用一次评估阻塞主流程）；② 🔴 **通知点抛异常 ⇒ 主流程仍成功且副作用照旧**（确认支付照常返回、`increaseSales` 仍被调到；过账仍 `receiveStock`）；③ 通知点未装配 ⇒ 跳过且不影响主流程；④ 触发原因是四类之一。**红证 = 去掉 `notifySafely` 的 `catch`** ⇒ ②红；**把 `confirmPayment` 里那行通知删掉** ⇒ ①红。', '判据 10·**失败可查**：通知点失败/未装配 ⇒ `INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED` 出现在日志里（grep 得到，不静默）。'],
    skip_reason='[backend-contract] 自动成批的开关缺省与事件挂载点纪律（无黄金策工具面）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-087 [NORMAL] 成批条件（任一即成批 / 都不满足则不派）+ 加急永不入池且自动立即派 + 兜底算式 + 幂等 + 失败留痕（源: cases/product.yml）──
_CASE_PR_087 = EvalCase(
    id='PR-087',
    legacy_id='',
    title='成批条件（任一即成批 / 都不满足则不派）+ 加急永不入池且自动立即派 + 兜底算式 + 幂等 + 失败留痕',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['自动成批的条件判定与兜底算式（非 LLM 行为，由 Java 单测覆盖）'],
    expectations=[],
    data_checks=['判据 3·**成批条件生效**：①②③ 各一条**只满足它**的夹具 ⇒ 成批（`reasons` 里是命中的那条规则）；三条都不满足（需求 3 米 / 批次 90 米 / 最小批量 30）⇒ **一次 `generate` 都不调**。**红证 = 条件恒真** ⇒ 第三条红。', '判据 5·**加急**：加急单**永不入池**且被**逐单立即派**（`pooled=false`，复用 #5177 的手动插队路径），且它**不出现在**成批那一批里。**红证 = 让加急单参与池化**（`urgent=false`）⇒ 该判据红。', '判据 4 算式面·**兜底的最晚派单日**：有到货日 ⇒ `到货日 − 标准生产周期`；无 ⇒ `进池日 + 标准生产周期`（进池日 = `orders.created_at`，与等待时长同一载体）；两个依据都缺 / 周期非正 ⇒ `null`（**不编一个日子**）。**到日必派**：条件都不满足但最晚派单日已过 ⇒ 仍派。', '判据 7·**幂等**：派过的单有了活跃加工单 ⇒ `pool()` 按同一口径（与 `uk_processing_orders_active` 逐字相同）把它排除 ⇒ 第二次触发**不重复派**（一次 `generate` 都不调）。**红证 = 池不再排除已派单** ⇒ 该判据红。', '判据 10·**失败可查**：三级降级（整批池级 → 逐单 + 规则 → 逐单不带规则）都失败 ⇒ `failures` 非空 + 监听器打出 `INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED`。**红证 = 把失败改成静默**（删掉那行 `log.error`）⇒ 该判据红。', '**「不能损失客户」的降级链**：⓵ 池级失败（累计余量不足 = 池化新出现的失败面）⇒ 逐单 + 规则重试（逐单看各自多半够）；⓶ 仍失败（该 SKU 根本没有可用批次）⇒ 逐单**不带规则**（#5145 之前的缺省形态：不碰批次账）⇒ **绝不因为优化不可用把订单压住**；重试不会重复派（`selectActiveByOrderId` + 唯一索引 fail-closed）。'],
    skip_reason='[backend-contract] 自动成批的条件/加急/兜底/幂等（无黄金策工具面）⇒ 由 Java 单测覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-088 [NORMAL] 真库：事件触发的自动成批**落账**（跨订单成组 3 米而非 6 米）+ generated_by 可审计痕迹 + 预览口径一致 + 幂等 + 对称回补 + 不损失客户（源: cases/product.yml）──
_CASE_PR_088 = EvalCase(
    id='PR-088',
    legacy_id='',
    title='真库：事件触发的自动成批**落账**（跨订单成组 3 米而非 6 米）+ generated_by 可审计痕迹 + 预览口径一致 + 幂等 + 对称回补 + 不损失客户',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['自动成批派单的真库落账读数（非 LLM 行为，由真 PG（initdb+pg_ctl）Java 判据覆盖）'],
    expectations=[],
    data_checks=['判据 2/6·**事件触发的自动成批真的落库**：事件到达（`order_confirmed`）⇒ `processing_orders` 两张（一单一加工单不变）；`Σ(−delta)` = **3 米**（不是 6 —— 池级一次求解让两张单的行并排）；3 米拆成两条台账、`COUNT(DISTINCT processing_order_no) = 2`；批次余量 60 → **57**。', '🔴 **可审计（范围 6）**：两张加工单的 `processing_orders.generated_by` = `auto:order_confirmed:fifo` —— **谁触发的**（哪类业务事件）与**按哪条规则**落在**持久列**上（不是只写在日志里）。', '判据 6·**口径一致**：真库 `Σ(formula_meters − planned_meters)` 与**独立复算的预览口径**（同一 `plan` 求解器、同一份入参）**逐值相等** = 3，且判别力自证（逐单派口径下这张单的节省 = 0 ⇒ 两套口径会给出不同的数）。', '判据 7·**幂等**：重复触发（换一个触发原因）⇒ 派过的单已有活跃加工单 ⇒ **不重复派**，`processing_orders` 行数与台账行数不变、余量不变。', '判据 8·**可撤销**：作废 ⇒ 回补**逐值对称**（余量精确回到 60、`Σ(−delta)` 净额归零）。⚠️ 这条在修前**必然失败**：V119 的 `ck_batch_consumption_plan_meters` 在回补行（两列都负）上方向翻转 ⇒ 「省过料的行的回补行」违反 CHECK（23514）。**V121（本单）** 把前半句改成绝对值口径（对扣减行逐字等价）。真库**注入式红证**：把约束换回 V119 原文 ⇒ 同一笔回补当场 23514、余量停在 57；换回修正版 ⇒ 同一笔回补照常落账。', '判据 9·**不损失客户**：`product_skus.stock` 与 `stock_ledger_entries` 行数**一字不动**（自动派单只动批次实物账）。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-089 [NORMAL] 🔴 真库：不压单可证明 —— 永远凑不满的池仍在**业务约束内**被派出去（红证：去掉兜底 ⇒ 该单永远不派）（源: cases/product.yml）──
_CASE_PR_089 = EvalCase(
    id='PR-089',
    legacy_id='',
    title='🔴 真库：不压单可证明 —— 永远凑不满的池仍在**业务约束内**被派出去（红证：去掉兜底 ⇒ 该单永远不派）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['凑不满的池是否会被压住（非 LLM 行为，由真 PG Java 判据覆盖）'],
    expectations=[],
    data_checks=['🔴 判据 4·**不压单可证明**：夹具是**永远凑不满**的池（需求 3 米 / 批次入库 90 米 ⇒ 填满率 3.3% < 80%、余量 90−3 = 87 > 0.2、需求 3 < 最小批量 30 ⇒ **三条成批条件一条都不成立**，`reasons` 为空）；无客户到货日 ⇒ 兜底链走「进池日 + **可配的**标准生产周期」。周期 7 天而进池已 30 天 ⇒ **最晚派单日已过 ⇒ 必派**（真库 `processing_orders` = 1、`generated_by` 含 `:due`、批次账落在 87）。', '🔴 **同夹具红证（去掉兜底 ⇒ 该单永远不派）**：同一个池、同一批条件、**只把标准生产周期换成 3650 天**（这张单不再到期）⇒ 一次都不派、`reasons` 为空。⇒ 「它被派出去」的原因就是业务兜底，不是别的什么。', '**边界（如实登记）**：到货日分支（`到货日 − 周期`）的算式由 PR-087 的单测逐值钉住；本判据覆盖的是「无到货日 ⇒ 标准生产周期兜底」这一支 —— 也正是「凑不满的池靠什么不无限期压住」的答案。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-090 [NORMAL] 🔴 真库：到点自愈 —— **一个业务事件都不发生**时，已过最晚派单日的单由到期扫描腿在真库被派出（痕迹 auto:due_scan:fifo）（源: cases/product.yml）──
_CASE_PR_090 = EvalCase(
    id='PR-090',
    legacy_id='',
    title='🔴 真库：到点自愈 —— **一个业务事件都不发生**时，已过最晚派单日的单由到期扫描腿在真库被派出（痕迹 auto:due_scan:fifo）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['周末 / 假期 / 淡季里没有新单、没有入库、也没人改单，已经过了最晚派单日的单会不会一直被压着（非 LLM 行为，由真 PG Java 判据覆盖）'],
    expectations=[],
    data_checks=['🔴 判据 1·**到点自愈**：夹具里**没有发布任何业务事件**（订单不被确认支付 / 没有入库过账 / 没有改单取消），只调一次到期扫描腿 ⇒ 客户要求到货日 = **今天**的那张单（最晚派单日 = 今天 − 标准生产周期 = 今天 − 7 天 ⇒ **已过**）在真库被派出：`processing_orders.deleted = 0` 的行数 = **1**、`generated_by` = `auto:due_scan:fifo`（**来源可区分**：与事件腿的 `auto:<事件原因>:<规则>` 同形态、不同触发原因）、批次台账 `Σ(−delta)` = 3、余量 90 → **87**。', '🔴 判据 1·**扫描腿不制造业务事件**：订单侧指纹（`status` / `is_urgent` / `required_delivery_date` / `created_at` 逐值拼接）在扫描前后**逐字相同** ⇒ 「它被派出去」不是靠偷偷改单或补发事件。', '🔴 **同夹具红证（停掉兜底 ⇒ 同一池一张都不派）**：同一个批次、同一张到期单 + 另加一张到货日在 **3650 天后**的单 —— ①把标准生产周期设成 **0**（`latestDispatchDate` 返回 `null` = 无从判定 ⇒ 没有兜底可言）⇒ **一张都不派**、`reasons` 为空；②兜底开着时**只有到期的那张**被派（`order_no` = `ORD-5184-A`，远到货日那张不派）、批次只扣一张单的量 ⇒ 派单的原因就是**业务约束**，不是别的什么。', '判据 6·**不损失客户**：`product_skus.stock` 与 `stock_ledger_entries` 行数**一字不动**（派单只动批次实物账）；真库读数与断言同源（不手抄列清单，schema 取 `docs/sql/schema.sql`）。', '**与 PR-089 的分工（如实登记）**：PR-089 覆盖「无到货日 ⇒ 进池日 + 标准生产周期」那一支；本判据覆盖「**有客户到货日 ⇒ 到货日 − 周期**」这一支；本判据的判别力另有注入式红证（`scripts/auto-batch-due-scan-red-proof.py` 的 `realdb_no_business_due`：去掉兜底判据 ⇒ 本判据红）。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'due-scan', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-091 [NORMAL] 🔴 真库/单测：扫描腿与事件触发**并发** ⇒ 不重复派、不重复扣（沿用三道闸）+ 逐租户隔离与上下文还原（源: cases/product.yml）──
_CASE_PR_091 = EvalCase(
    id='PR-091',
    legacy_id='',
    title='🔴 真库/单测：扫描腿与事件触发**并发** ⇒ 不重复派、不重复扣（沿用三道闸）+ 逐租户隔离与上下文还原',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['定时兜底与事件触发同时抢同一张单会不会重复派、重复扣（非 LLM 行为，由真 PG Java 判据覆盖）'],
    expectations=[],
    data_checks=['🔴 判据 3·**并发不重复**：定时腿（`AutoBatchDueScanService`，**自带一条连接**）与事件腿（`autoBatchDispatch(order_confirmed)`）用两个线程 + 同一道发令闸同时触发同一张到期单 ⇒ 真库不变量在**任意交错**下成立：`processing_orders`（`deleted = 0`）= **1**（`uk_processing_orders_active` 挡住第二张）、`stock_batch_consumptions` = **1** 行（`uk_batch_consumption_line`）、`Σ(−delta)` = **3**（只扣一次）、余量只减一次（87）；胜者的 `generated_by` 只可能是两条腿之一（`auto:due_scan:fifo…` / `auto:order_confirmed:fifo…`，三级降级会追加 `:single`/`:plain`）⇒ 不出现「第三张单」或「同一单两张加工单」。', '🔴 判据 3·**幂等（重复触发不重复派/不重复扣）**：并发之后**再扫一轮** ⇒ 派过的单已有活跃加工单 ⇒ 池里看不见它 ⇒ `dispatchedOrderNos` 为空，加工单行数、台账行数、余量与并发的结论**逐值相同**；对客口径同样不变。', '判据 3·**逐租户隔离（单测面）**：候选租户里一个租户的扫描抛异常 ⇒ **不影响**其余租户（fail-soft，留 `INCIDENT_PRODUCTION_AUTO_BATCH_DUE_SCAN_FAILED`），且失败也落在心跳的 `last_error` 上；每个租户的**池读都发生在该租户的上下文里**（#3957 的生产事故形态：漏了这一步则每轮调度整体夭折），且**退出时还原**调度线程进来的上下文（线程复用，不许漏给下一个任务）。', '**边界（如实登记）**：并发用例的**线程交错不可强制**（两条腿各自读池 → 各自尝试派单），断言写的是**不变量** ⇒ 即使某次跑成串行，它仍是「与事件腿并发/重复触发都不重复派」的有效观测；本判据**没有**注入式红证（拆库层闸门的变异是非确定的：`selectActiveByOrderId` 会在插入前就把第二路短掉）—— 该边界已登记在 `scripts/auto-batch-due-scan-red-proof.py` 的文件头。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配）+ Java 单测，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'dispatch-pool', 'auto-dispatch', 'due-scan', 'idempotency', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-092 [NORMAL] 🔴 扫描腿**只查业务约束**（无池化窗口参数）+ **默认关零动作** + 心跳可见 + 载体独立于事件链（源: cases/product.yml）──
_CASE_PR_092 = EvalCase(
    id='PR-092',
    legacy_id='',
    title='🔴 扫描腿**只查业务约束**（无池化窗口参数）+ **默认关零动作** + 心跳可见 + 载体独立于事件链',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['定时腿会不会变成「窗口到点就派」，以及它被显式关掉时会不会偷偷动数据（非 LLM 行为，由 Java 判据覆盖）'],
    expectations=[],
    data_checks=['🔴 判据 2·**只查业务约束（不得引入池化窗口参数）**：① 池内等了 **30 小时**（超过看板 24 小时上限 ⇒ 智能派单会告警）但客户到货日在 30 天后（**未到期**）⇒ 扫描腿**不派**（红证：把等待上限当死线的变异 `window_as_deadline` ⇒ 本判据红）；② 进池才 **1 小时**（远未到上限）但已过最晚派单日 ⇒ **照派**；③ 把等待上限调成 `0.001h` / `9999h` ⇒ 派单结果与 `reasons` 文案**逐值相同**（派不派与该参数无关）；④ 结构性：策略记录 `AutoBatchPolicy` 的入参集合**逐个钉死**（只有既有的看板告警上限 `maxWaitHours`，**没有任何**新增的窗口/超时参数）。', '🔴 判据 2·**定时腿是兜底、不是第二条主触发**：满足成批条件③（需求 ≥ 最小批量）但**未到期**的单 ⇒ 扫描腿一张都不派；**同一份池**走事件腿（`order_confirmed`）⇒ 当场按条件③成批 ⇒ 「什么时候成批」仍由业务事件决定，扫描腿只判业务约束。', '🔴 判据 4a·**缺省即开**（issue #6588）：缺省（属性缺失 ⇒ 开）⇒ 扫描腿**真的逐租户扫**：`orderMapper.selectConfirmedTenantIds()` 被调到、心跳 `rounds` +1。**红证 = 把缺省改回 `false`** ⇒ 本判据当场红（机具：`scripts/auto-batch-due-scan-red-proof.py --only default_on`）。', '🔴 判据 4b·**显式关 ⇒ 零读零写**（不变式）：开关为假（部署属性 `migao.production.auto-batch.enabled=false`）⇒ 扫描腿**零读零写**：连「有哪些租户」都不查（`orderMapper` / `itemMapper` / `processingOrderMapper` 零交互）、**零日志**、**零轮数**。**红证 = 摘掉扫描腿那行 `!autoBatchPolicy().enabled()` 闸** ⇒ 本判据当场红（机具：同文件 `--only off_gate`）。', '🔴 判据 5·**心跳可见**：`/actuator/health` 的 `autoBatchDueScanHealth` details 给出 `enabled` / `rounds` / `last_success_at` / `last_failure_at` / `last_scanned_tenants` / `last_dispatched` / `last_error`（跑过一轮后轮数与最近成功时刻必须变；未跑过时为 `null` = 「没跑」长得像「没跑」），状态**恒 UP**（同 `MigrationHealthIndicator`：让扫描腿把整环境打成 DOWN 比原问题更糟）⇒ 停摆有可观测面（红证：`heartbeat_not_exposed` ⇒ 本判据红）。', '**载体结构性（+ 边界）**：`@Scheduled` 只出现在**独立**的薄壳 `AutoBatchDueScanScheduler` 上（cron 可配 `migao.production.auto-batch.due-scan-cron`，缺省 `0 */5 * * * *` = 约定窗口 = 一个扫描周期 + 单轮耗时），事件链三类（监听器 / 通知点 / `ProcessingOrderService`）**仍无任何计时器**（#5182 判据 2 继续成立）；触发原因 `due_scan` **不是**事件四类之一。**约定窗口与多实例**：扫描周期只决定「多久看一眼」，到期判定是**日粒度** ⇒ 周期远小于一天即可；多实例部署时每个实例都会各自扫（本单**不做分布式锁**），安全由库层三道闸承担（见 PR-091）。'],
    skip_reason='[backend-contract] Java 判据（Mockito 真链路装配 + 反射/记录组件结构性断言），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['dispatch-pool', 'auto-dispatch', 'due-scan', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-093 [NORMAL] 🔴 真库+页面：看板汇总 == Σ 逐单 saved_*（逐值相等，不许两套口径）+ 单价口径（换价后历史读数不变）（源: cases/product.yml）──
_CASE_PR_093 = EvalCase(
    id='PR-093',
    legacy_id='',
    title='🔴 真库+页面：看板汇总 == Σ 逐单 saved_*（逐值相等，不许两套口径）+ 单价口径（换价后历史读数不变）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['省了多少料（L2 批次分档聚合 / L3 单位产出消耗）—— 非 LLM 行为，由真 PG Java 判据与前端组件判据覆盖'],
    expectations=[],
    data_checks=['判据 1·**汇总一致**：`saving-board` 的合计与分组腿 == 逐单读面 `Σ saved_meters` / `Σ saved_amount`，**逐值相等**。判别性做法：夹具里放两行 `0.1 米 × 12.345 元` ⇒「逐行先取整再求和」= 2.46、「整段求和再取整」= 2.47，两个读数在同一测试里对照打印 ⇒ 这条判据不是自说自话。**红证 = 把金额腿改成 `ROUND(SUM(...), 2)`** ⇒ 当场红（实测 103.76 → 103.77）。', '判据 5·**单价口径**：`UPDATE stock_batches SET unit_cost = 99` 之后重读看板 ⇒ 省料金额**一字不变**（用的是行内快照 `stock_batch_consumptions.unit_cost`）。**红证 = 把金额腿改成读批次现价 `b.unit_cost`** ⇒ 当场红（实测 103.76 → 1227.6）。⚠️ 复读前必须 `session.clearCache()`（MyBatis 一级缓存按 SqlSession；不清缓存会读回改前值 ⇒ **断言恒真 = 空断言**，本单实测踩到并已修）。', '判据 3·**粒度 fail-closed**：未知粒度 ⇒ 400 显式拒绝（**不静默回落 month**）；`week` 走 ISO 周（`YYYY-Www`）且响应的 `timezone` 显式为 `Asia/Shanghai`。**红证 = 把 default 改成回落 month** ⇒ 当场红。', '判据 6·**批次结构趋势（issue #6459）**：`Board.batchTrend` 按**批次收货期间**给出「几乎用完（剩余最小档）的批数 / 该期批数 / 占比」，**只含 `purchase`**（存量导入与来源未知**不进序列**）。真库读数（同夹具）：采购在 2026-09（2 批 / 0 批几乎用完 / 0.0000）、存量在 2026-08 ⇒ 序列**只有 2026-09 一行**；**红证 = 把存量并进来** ⇒ 多出 2026-08 一行、合计由 2 变 4。定点判据 = `SavingMetricsBatchTrendTest`（同期多行相加 / 期间升序 / 未记收货日期不猜 / 1÷3 ⇒ 0.3333）。复用**已加载的行**内存聚合（**零新增 SQL**）；`Board` 既有 component 的顺序与名字一字未动（**只在末尾追加** `batchTrend`）。'],
    skip_reason='[backend-contract] 省料度量的汇总读面与看板（无黄金策工具面）⇒ 由 Java 真库判据 / 前端组件判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'saving-metrics', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-094 [NORMAL] 🔴 真库+页面：存量导入批次（source='opening'）独立成组，不混入「切换后」的分子分母（源: cases/product.yml）──
_CASE_PR_094 = EvalCase(
    id='PR-094',
    legacy_id='',
    title="🔴 真库+页面：存量导入批次（source='opening'）独立成组，不混入「切换后」的分子分母",
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['省了多少料（L2 批次分档聚合 / L3 单位产出消耗）—— 非 LLM 行为，由真 PG Java 判据与前端组件判据覆盖'],
    expectations=[],
    data_checks=['判据 2·**存量单列**：`cohorts` 三组恒在（含 `opening`）；切换后 `batchCount` = 2（**不含**存量批次）、存量组 `batchCount` = 2；存量组自证 `opening=true`；两组各有自己的 `le0_2Share`。**红证 = 把 `opening` 并进 `purchase`** ⇒ 当场红（实测存量批次读数 2 → 0）。', '判别性对照读数（同夹具）：切换后占比 = **0/2 = 0.0000**、存量占比 = **1/2 = 0.5000**、**若把存量混进切换后 = 1/4 = 0.2500** —— 三个数在同一测试里都在 ⇒「不混入」这句话可证伪。', '分组腿同样单列：`batchGroups` 里存量批次落在 `cohort=opening` 的**独立组**（时间维度 = 收货月），且**不存在**「存量 + 切换后」混在一起的组。', '页面面（`SavingBoard.test.tsx`）：🔴 **2026-10-07 改判（issue #6459）** —— 旧写的「存量导入独立成卡并带「存量导入·单列」徽标」**已作废**（来源组对照表连同它的三个内部标签被用户裁定从页面删除）。**口径一字不放宽、呈现改说人话**：存量批次仍**不进**趋势的分子分母（服务端 `batchTrend` 只含采购腿；真库读数 = 存量所在的 2026-08 **整期缺席**），页面上这件事只用商家的话在折叠区说一次（「趋势只统计系统里采购入库的批次：开业时导入的老库存不算」）。**红证 = 让趋势序列吃全量来源** ⇒ 行数由 1 变 2、合计由 2 变 4 ⇒ 当场红。新增的**类级元守卫** = `user-copy-jargon-guard` 的形态③（`切换后` / `存量导入` / `来源未知` 三个服务端标签进用户可见文案即红）。'],
    skip_reason='[backend-contract] 省料度量的汇总读面与看板（无黄金策工具面）⇒ 由 Java 真库判据 / 前端组件判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'saving-metrics', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-095 [NORMAL] 🔴 真库+页面：空数据不冒充 0 —— 占比/合计/比率/单位产出在无数据时是「无数据」，真 0 与无数据可区分（源: cases/product.yml）──
_CASE_PR_095 = EvalCase(
    id='PR-095',
    legacy_id='',
    title='🔴 真库+页面：空数据不冒充 0 —— 占比/合计/比率/单位产出在无数据时是「无数据」，真 0 与无数据可区分',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['省了多少料（L2 批次分档聚合 / L3 单位产出消耗）—— 非 LLM 行为，由真 PG Java 判据与前端组件判据覆盖'],
    expectations=[],
    data_checks=['判据 4·**空租户**（无批次/无入库/无消耗）：每组 `batchCount=0` 但 `le0_2Share` / `savedMeters` / `savedAmount` / `remainingMeters` / 四档 `share` **一律 `null`**（**不是 0**）；`batchGroups` / `savedGroups` 为空、`trend.points` 为空且三个合计为 `null`。', '判据 4·**真 0 与无数据可区分**（同夹具对照）：非空租户里「分母 2、分子 0」必须是 `0.0000`（真 0），而空租户同名字段是 `null`。**红证 = 让分母为 0 时回落 `BigDecimal.ZERO`** ⇒ 当场红（实测 expected null but was 0）。', '判据 4·**分母 0 ⇒ 比率 null**：有消耗但明细行没有面积（`order_item_id` 不存在于 `order_items`）⇒ `outputAreaM2 = 0` 而 `metersPerM2` 必须 `null`（不得回落成 0 —— 会读成「一点布都没用」）。另：同一明细行有两行扣减 ⇒ 面积**按 `order_item_id` 去重**（否则分母虚高、效率被说好）。', "页面面（🔴 **2026-10-07 改判，issue #6459**）：旧写的「无数据时两张指标卡渲染「无数据」」**已作废**（那两张卡被用户裁定删除）；现口径 = 首屏两个大数字（`saving-metric-saved-meters` / `saving-metric-saved-amount`）在无数据时渲染「无数据」且**不得出现 `0 米` / `0 元`**；趋势表与明细表空数据渲染「无数据」而不是空表或 0。**红证 = 让 `formatMetric(null)` 回 `'0'`** ⇒ 前端判据当场红（红证机具第 1 条变异：`Tests 3 failed | 25 passed`）。", '§22 基线纪律①（文案不写死数字）：档位文案（如「≤0.2 米」）**必须**来自服务端 `buckets[].label`（现用于趋势表标题 `batchTrendTitle`）。**红证 = 在助手/页面里硬编码「≤0.2 米」** ⇒ 当场红（红证机具第 5 条变异：`Tests 1 failed | 27 passed`）。'],
    skip_reason='[backend-contract] 省料度量的汇总读面与看板（无黄金策工具面）⇒ 由 Java 真库判据 / 前端组件判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'saving-metrics', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-096 [NORMAL] 🔴 省料看板「两条指标并用」**已按用户裁定从页面删除**（issue #6459 改判）+ 前端零算术 + 不损失客户（源: cases/product.yml）──
_CASE_PR_096 = EvalCase(
    id='PR-096',
    legacy_id='',
    title='🔴 省料看板「两条指标并用」**已按用户裁定从页面删除**（issue #6459 改判）+ 前端零算术 + 不损失客户',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['省了多少料（L2 批次分档聚合 / L3 单位产出消耗）—— 非 LLM 行为，由真 PG Java 判据与前端组件判据覆盖'],
    expectations=[],
    data_checks=['🔴 **2026-10-07 整条改判（issue #6459，用户逐字「这个功能只需要用数据和规则说清楚我们是如何省下多少布料，节省了多少成本即可」+「这么多废话文字留在页面上只会干扰用户」）**：旧的两条判据 ——「页面恒渲染两张卡（`saving-metric-le-0-2` / `saving-metric-purchased`）」与「说明条含『两条指标必须并用 / 排料 / 误导 / 剩得更多 / 显示成变差』五要素」—— **随两张卡与那条说明一起作废**（它们正是用户点名删掉的东西）。新形态 = 首屏**两张省料结论卡**（`saving-metric-saved-meters` / `saving-metric-saved-amount`，值原样取服务端 `comparison`，读不出退回服务端 `total`）+ **一张「几乎用完的布 · 批数」趋势表**（服务端 `batchTrend`，只含采购腿）+ 默认收起的省料明细与口径区。新判据落点 = UI-092。**红证（注入式，实测）**：把旧区块写回页面 ⇒ `SavingBoardStory.test.tsx` 的「旧形态结构性退场」当场红；把内部口径词搬到首屏 ⇒ `Tests 1 failed | 27 passed`（§6459 红证机具第 6 条变异）。', '⚠️ **删的是呈现，不是口径**（判据一条不放宽）：① 指标①的实质（布有没有被用干净）以「几乎用完的布 · 批数」趋势继续在页面上；② 旧指标②（采购总米数）退出首屏，但**历史导入不进计量腿**这条服务端口径一字未改（PR-094）；③ 前端仍**零算术、零好坏判定**（下一条）。', '判据 1（页面面）·**米数/金额原样渲染服务端值**：桩数据**故意不自洽**（本期 55 米 / 逐单分组腿 77 米 / 合计 99 米，三个数互不相等）⇒ 前端任何「顺手求和/求差」都会让断言红（红证机具第 2、3 条变异分别打首屏大数字与合计行，实测 `3 failed / 25 passed` 与 `1 failed / 27 passed`）。', '判据 6·**不损失客户**：两次读面调用之后 `product_skus.stock` / `orders.total_amount` / `stock_ledger_entries` 行数**逐值不变**（读面不写任何东西）。未记均价的行数以「另有 N 行未记批次均价，金额不含这些行」显式渲染（否则「读不出」会被读成「只省了这么点」）。', "🔴 **2026-10-08 追加（issue #6535）：展示名与标识分家（省料看板「物料」列）**—— 病：该列原样渲染 `materialKey` = `productId|skuCode`（`productId` 是 UUID）⇒ 商家看到的是一长串十六进制 + 竖线 + SKU（与 #6523 同族、换了一个 DTO）。修法口径与 #6523 **同源**：① 服务端 `SavedGroup.materialLabel`（= `商品名 × 颜色/门幅`，组装入口**唯一**一份 `com.migao.admin.dto.MaterialLabels`，前端**不拼串**）；② `materialKey` **一字不改**；③ 前端只把展示文本换掉。**取值方式**：按去重后的 `productId` **一次批量查**商品名（**不是** N+1；读面同事务内完成），拿不到名字退回「未命名商品 × 颜色/门幅」而**绝不**退回机器键（展示依赖 fail-soft）。**判据（会红）**：`SavingMetricsBoardRealDbTest#savedGroupCarriesHumanReadableMaterialLabel`（真库：`materialLabel` 含商品名与 SKU、**不含** `|`、**不等于** `materialKey`；负控 = `materialKey` 仍逐字等于 `productId|skuCode`、米数/金额读数逐值不变）+ `SavingBoard.test.tsx`「#6535」用例（行文本含展示名、不含竖线/UUID 形态；`data-testid` 逐字仍是 `saving-saved-group-2026-09-p1|SKU-A`；逐格文本逐一相等）。**红证（实现前实测）**：前端 `1 failed | 9 passed`，读数 = `expected '2026-09p1|SKU-A10 米4.6 米77 米88.88 元' to contain '遮光帘A × 2.8米'`。"],
    skip_reason='[backend-contract] 省料度量的汇总读面与看板（无黄金策工具面）⇒ 由 Java 真库判据 / 前端组件判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'saving-metrics', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-097 [NORMAL] 🔴 真库 + 静态：余料台账**不算资产** —— Σ库存金额逐值不变，且余料两表不出现在任何库存/资产读面里（红证：动一下库存金额 ⇒ 读数必变）（源: cases/product.yml）──
_CASE_PR_097 = EvalCase(
    id='PR-097',
    legacy_id='',
    title='🔴 真库 + 静态：余料台账**不算资产** —— Σ库存金额逐值不变，且余料两表不出现在任何库存/资产读面里（红证：动一下库存金额 ⇒ 读数必变）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['裁剪产生的余料是否会被计成企业资产（非 LLM 行为，由真 PG Java 判据 + 静态守卫覆盖）'],
    expectations=[],
    data_checks=['🔴 判据·**不算资产**：派工/排料结果**自动**登记余料（不需要人手工登记）前后，`Σ product_skus.cost_amount` 与 `Σ product_skus.stock` **逐值不变**（真库直读 SQL；夹具的库存金额取**非零**真值 —— 全 0 上的「逐值不变」是空断言）。', '🔴 **同判据红证**：手动 `UPDATE product_skus SET cost_amount = cost_amount + 1` ⇒ 同一个读数**必须变**（证明上面那条不是恒真）。', '🔴 **结构性判据**（真库覆盖不到的另一半）：生产代码里出现 `fabric_remnants` / `remnant_small_item_specs` 这两个**表名**的地方，只允许是余料功能自己的取数面（两张实体 + 两个 mapper）—— 反面形态是「某天有人给库存读面加一条 join」（读面而已，金额不会变 ⇒ 真库判据照绿）。扫描面非空且真看得见两个 mapper（否则「零违规」可能只是扫描失灵），并带注入式红证（把余料表 join 进库存 mapper ⇒ 必须判红）。', '**边界（如实登记）**：本判据判的是「余料**不参与**库存金额」，不判「余料有没有被浪费」—— 后者是报废率/回收率读数（PR-098），不是资产口径。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配）+ 源码静态扫描，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['remnant', 'non-asset', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-098 [NORMAL] 🔴 真库 + 渲染：小件优先匹配真的省料（同缸号优先、批次数不变、回收额 = 米数 × 当时均价）+ **未配置不静默** + 不凭空推荐（源: cases/product.yml）──
_CASE_PR_098 = EvalCase(
    id='PR-098',
    legacy_id='',
    title='🔴 真库 + 渲染：小件优先匹配真的省料（同缸号优先、批次数不变、回收额 = 米数 × 当时均价）+ **未配置不静默** + 不凭空推荐',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['余料能不能拿来做绑带/帘头/抱枕、以及未配置尺寸时会不会静默（非 LLM 行为，由真 PG Java 判据 + 前端渲染守卫覆盖）'],
    expectations=[],
    data_checks=['🔴 判据·**优先匹配真的省料**：三块余料里**故意**让「异缸号的那块最小」⇒ 命中同缸号那块（`sameDyeLot=true`、来源批次 = 同缸号批次）—— 「同缸号优先」**优先于**「先用小块」。用掉之后 `stock_batch_consumptions` 的**行数与 Σdelta 逐值不变**（判据原话「该小件不产生新的批次消耗（批次数不变）」），`product_skus.stock` 同样不碰。', '判据·**回收额口径**：`recovered_amount = 用掉米数 × 该批次当时均价`（真库逐值），`recovered_unit_cost` 是**回收那一刻**的快照；**改价后历史读数一字不变**；来源批次没记均价 ⇒ **拒绝回收**（宁可为失败，不许估）。', '🔴 判据·**未配置不静默**：清空尺寸表 ⇒ 匹配 `configured=false`、**推荐为空**、`notice` **非空**（含「未配置」）；配置读面同样显式说明「未启用」。**红证**：配一行 ⇒ `configured=true` 且 `notice` 消失、**真的开始匹配**（同一份夹具 ⇒ 差别只在配置）。渲染面同判据：未配置 ⇒ 面板显式徽标「未配置（正在用默认值：空 ⇒ 未启用）」+ 服务端说明**原样**上屏；已配置 ⇒ 两个「未配置」信号都不许出现。', '判据·**不凭空推荐**：余料宽 / 长任一不足 ⇒ **无推荐**且给出可读原因；同夹具把需求改小 ⇒ 必须命中（正向对照，证明「空」是因为尺寸而不是别的原因）。', '🔴 存量行特殊选项读面（issue #5550）：`processing_info` 为 **NULL** 的明细行 ⇒ `specialOptionsOf` 必须返回**空列表**（缺值就是这一行没带特殊选项，不猜），而**不是** NPE —— 原写法 `normalize(...).get(...)` 是直连解引用，余料回收（`orderTakesRemnantsAway` / `match`）对同样的存量行随时 500。**红证** = 还原直连解引用 ⇒ `RemnantServiceTest#specialOptionsOfLegacyItemWithoutProcessingInfo` 当场 NPE 红；类级元守卫同上（`ProcessingInfoNullSafetyMetaGuardTest`）。', '判据·**配置面合规**（`migao-dev-flow` §22）：小件尺寸表挂在**既有企业参数中心**的「余料**尺寸**」域**页内**（不新造第二个配置入口；域 label 真值源 = `frontend/admin-web/src/lib/config-center-domains.ts` 的 `remnant-sizes`，issue #6827 起不再写作「余料回收」）、三件套齐全且**文案里不出现数字**、术语**就地**可查（独立锚点命名空间，与算料域不抢 id）、`impact` 明确写出「不改对客价 / 不改加工费 / 不改成品尺寸」（用户裁定「不能损失客户」）。'],
    skip_reason='[backend-contract] 真 PG 判据 + admin-web vitest 渲染/静态守卫，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['remnant', 'small-item-match', 'configurable-param', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-099 [NORMAL] 🔴 真库：客户带走的余料不入可用池 + 报废留痕 + 账实一致由 DB 约束钉住（红证：混入可用池 ⇒ 立刻命中；抹掉原因 ⇒ 23514）（源: cases/product.yml）──
_CASE_PR_099 = EvalCase(
    id='PR-099',
    legacy_id='',
    title='🔴 真库：客户带走的余料不入可用池 + 报废留痕 + 账实一致由 DB 约束钉住（红证：混入可用池 ⇒ 立刻命中；抹掉原因 ⇒ 23514）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户带走的余料会不会被拿来匹配、报废有没有留痕（非 LLM 行为，由真 PG Java 判据覆盖）'],
    expectations=[],
    data_checks=['🔴 判据·**客户带走不入可用池**：订单勾了 `余料带回-布` ⇒ 余料**仍然登记**（账要平）但状态 = `customer_taken`、`available` 计数为 **0**；匹配**不命中**、回收与报废都被**显式拒绝**。**红证**：手动把它改成 `available` ⇒ 匹配**立刻命中**（证明「不参与匹配」的原因就是那个状态）。', '判据·**报废留痕**：报废后状态 / 原因 / 操作人 / 时刻都可读（真库逐列），按 `scrapped` 状态查得回来；重复报废被拒（否则报废率失真）；报废件不得带回收额。', '🔴 判据·**账实一致不是靠读面自觉**：绕过服务层直接注销报废原因 / 写错回收额 ⇒ V122 的生命周期与算术约束**当场拒绝**（SQLSTATE 23514）—— 证明约束真的钉住了，而不是只写在注释里。', '**边界（如实登记）**：余料尺寸取自排料块清单 ⇒ 排不出料的订单行**不产生**余料（那些行的布没有排料结果可依据）；同缸号匹配在缸号为空时只按同色判定（空缸号既不算相同也不算不同）。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['remnant', 'customer-taken', 'scrap-trace', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-100 [NORMAL] 黄金策查批次余量 / 「快用尽」批次（按物料 / 批次号 / 缸号）（源: cases/product.yml）──
_CASE_PR_100 = EvalCase(
    id='PR-100',
    legacy_id='',
    title='黄金策查批次余量 / 「快用尽」批次（按物料 / 批次号 / 缸号）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['哪些批次快用尽了？还剩多少米'],
    expectations=['batch_stock_query'],
    data_checks=['商家问「哪些批次快用尽了」→ batch_stock_query(action=batches, nearly_used_up=true) 被调用且**成功**返回（must_succeed 断言 success=true，不是「工具名出现过」）', '口径同源·档位：「快用尽」= 服务端剩余量分布**第一档**（`le_0_2`），工具不得自定阈值；**负余量（超扣）也在该档内**，不得用 `onlyAvailable` 把它剔掉（剔掉就是第二份口径）。同夹具判据：工具回的行集 == `distribution` 第一档的 `batchCount`', '读数一律取 `/api/admin/batch-stock/batches` 读面（余量是服务端派生值 = 入库量 + Σ消耗）；agent 侧不得自己算「入库 − 消耗」', '空结果如实回「**无数据**」（不得回 0、不得编造批次号）；缺 `product:list` 时如实说明「这是权限限制、不要重试」并指向管理后台授权路径'],
    skip_reason='',
    tags=['mibao', 'batch-ledger', 'saving-metrics', 'agent-tool'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'batch_stock_query'}],
)

# ── PR-101 [NORMAL] 黄金策查剩余量四档分布（档位文案取服务端 label，不自写数字）（源: cases/product.yml）──
_CASE_PR_101 = EvalCase(
    id='PR-101',
    legacy_id='',
    title='黄金策查剩余量四档分布（档位文案取服务端 label，不自写数字）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['现在剩料是什么分布？有多少批次快用完了'],
    expectations=['batch_stock_query'],
    data_checks=['商家问剩料分布 → batch_stock_query(action=distribution) 被调用且**成功**返回（`must_succeed`）', '四档（`le_0_2` / `b0_2_0_5` / `b0_5_1` / `gt_1`）的 key / label / batchCount / share **全部原样透传**服务端 `GET /api/admin/batch-stock/distribution`（工具只做选择性透传，不重新分档）', '档位文案**取自服务端 `buckets[].label`**（§22 基线纪律①：文案里不出现数字，数值由真值渲染）；工具与前端都不得硬编码「≤0.2 米」这类档位文字', '空数据（`totalBatches = 0`）⇒ 文案回「**无数据**」；计数 0 是事实可保留，但**不得**把读不出的比率说成 0'],
    skip_reason='',
    tags=['mibao', 'batch-ledger', 'saving-metrics', 'agent-tool'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'batch_stock_query'}],
)

# ── PR-102 [NORMAL] 黄金策答「这个月省了多少料 / 省了多少钱」—— 🔴 与省料看板读面逐值相等（不另算一份）（源: cases/product.yml）──
_CASE_PR_102 = EvalCase(
    id='PR-102',
    legacy_id='',
    title='黄金策答「这个月省了多少料 / 省了多少钱」—— 🔴 与省料看板读面逐值相等（不另算一份）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我这个月省了多少料？省了多少钱'],
    expectations=['batch_stock_query'],
    data_checks=['商家问省料 → batch_stock_query(action=saving_board) 被调用且**成功**返回（`must_succeed`）', '🔴 判据 2·**口径同源（逐值相等）**：工具回的 `savedMeters` / `savedAmount` / `formulaMeters` / `plannedMeters` / `le0_2Share` / `remainingMeters` 与 `GET /api/admin/batch-stock/saving-board` 的读数**逐值相等**（逐来源组 + 逐分组 + total 三处都比）。**红证 = 在 agent 侧重算**：夹具刻意取「逐行取整再求和 ≠ 整段求和再取整」的账（读面 24.68，朴素重算 24.67）⇒ 重算实现当场红', '存量导入**单列**：`opening` 组的省料/余量与「切换后（采购入库）」**并列而不相加**（工具沿用服务端 `cohortLabel`，不自造分组文案）', '判据 5·**空数据不冒充 0**：`lineCount = 0` 的组与空租户 ⇒ `savedMeters` / `savedAmount` / `le0_2Share` 一律 `null`，文案回「**无数据**」、**不得出现 `0%` / `0 米`**（0 会被读成「没有浪费」）；未记均价的行数以「另有 N 行没有均价」显式说明', '判据 4·**只读无副作用**：工具源码里没有任何写调用（无 `post/put/patch/delete`），运行期四个 action 各跑一次后写方法**零调用**；不改任何对客金额/售价/成品口径（判据 6）'],
    skip_reason='',
    tags=['mibao', 'batch-ledger', 'saving-metrics', 'agent-tool'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'batch_stock_query'}],
)

# ── PR-103 [NORMAL] CI 上缺 PG 二进制 ⇒ 真库判据判 **FAIL**（不是 skip）：本机开发友好 + CI fail-closed（源: cases/product.yml）──
_CASE_PR_103 = EvalCase(
    id='PR-103',
    legacy_id='',
    title='CI 上缺 PG 二进制 ⇒ 真库判据判 **FAIL**（不是 skip）：本机开发友好 + CI fail-closed',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['（非 LLM 面）runner 镜像换代 / 换 runner / 自建 runner ⇒ admin-api-test 上找不到 PG 二进制（initdb/pg_ctl）时，真库判据的结果必须与「通过」可区分'],
    expectations=['direct_reply'],
    data_checks=['收口点唯一：缺 PG 的处置**只许**在 `backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java` 的 `startOrAbort()` 里有一份 —— 未设 `MIGAO_REQUIRE_REALDB` ⇒ `Assumptions.abort`（本机 `mvnw test` 不因没装 PG 变红）；设了 ⇒ `Assertions.fail`（**红**）。全仓真库测试类**零** `Assumptions.*` 副本', 'CI 侧两道锁同时在位：`pr-check.yml` 的 `admin-api-test` job 有「PG 二进制前置断言（缺失 ⇒ 独立一行 `exit 1`）」+「`mvnw test` 那步注入 `MIGAO_REQUIRE_REALDB`（值非空且非 0/false）」，且注入键名与 `PgCluster.REQUIRE_REALDB_ENV` 常量**逐字一致**', '红证 A（真跑，2026-09-23 本机，判据 = `mvnw -o test -Dtest=OrderUrgencyRealDbTest -Dmigao.pg.bin.dirs=<空目录>`）：**带** `MIGAO_REQUIRE_REALDB=1` ⇒ `AssertionFailedError: 缺 PG 二进制…本判据判 FAIL（不是 skip）` / `BUILD FAILURE` / EXIT=1；**不带** ⇒ `Tests run: 0 … Skipped: 0` / `BUILD SUCCESS` / EXIT=0（= 静默绿的形态，两者真的不同）', '对照组（无覆盖孔、无标记）：`Tests run: 7, Failures: 0, Skipped: 0` —— 本机真库判据**真跑**（不是靠 skip 冒充）'],
    skip_reason='[backend-contract] CI workflow 结构 + Java 真库装配由 pytest 单测验证（tests/unit_ci_workflows/test_realdb_failclosed.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['realdb', 'ci', 'fail-closed', 'evidence-strength'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-104 [NORMAL] 真库判据的类集合冻结 + 单一收口点（删掉/改名一份判据即红）（源: cases/product.yml）──
_CASE_PR_104 = EvalCase(
    id='PR-104',
    legacy_id='',
    title='真库判据的类集合冻结 + 单一收口点（删掉/改名一份判据即红）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['（非 LLM 面）有人删掉 / 改名一份真库判据，或新写一份绕过收口方法的真库判据 ⇒ 门禁必须当场变红'],
    expectations=['direct_reply'],
    data_checks=['判据① 冻结常量：测试树里「需要真 PG」的类集合 == `test_realdb_failclosed.py` 登记的 `REALDB_FILES` + 夹具 `RemnantTestDb`（按「谁真去连真 PG」定义，**不靠 `*RealDbTest` 通配** —— `ProductionPartCodeRealMappingTest` 这类不含 `RealDb` 的判据同样在集合里）', '判据② 单一收口：每个真库测试类要么直接调 `PgCluster.startOrAbort()`、要么经共用夹具 `RemnantTestDb`（夹具内部收口，三个余料消费类是本表**显式登记**的例外）；`Assumptions.abort(` 在 admin-api 测试树里**只许有一处**（PgCluster 的本机分支）', '判据④ 顺序即语义：`PgCluster` 里 `Assertions.fail(` 必须**排在** `Assumptions.abort(` 之前（挪到后面 = 永不执行，而「代码里有 fail」这种弱断言照样绿）。所有 Java 侧断言先剥注释与字符串字面量 ⇒ 注释里提一句喂不绿', '红证 B（真跑，2026-09-23 本机，7 个单点变异各**单独**变红后复原并核 sha256）：① 改名 `SkuBatchGuardRealDbTest.java` ⇒ 判据① 红；② 裸 `PgCluster.start()` / ③ 重写 `Assumptions.abort` 副本 ⇒ 判据② 红；④ 去掉前置断言那句 `exit 1` / ⑤ 删掉标记注入 / ⑥ 值改 `0` / ⑦ 键改名 ⇒ 判据③ 红；⑧ 删掉 `Assertions.fail` / ⑨ 把它挪到 abort 之后 ⇒ 判据④ 红'],
    skip_reason='[backend-contract] 静态守卫由 pytest 单测验证（tests/unit_ci_workflows/test_realdb_failclosed.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['realdb', 'ci', 'guard', 'evidence-strength'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-105 [NORMAL] 🔴 商家可见文案里的 markdown 强调不得漏出字面标记：**保留标记 + 渲染层解析**（`**x**` ⇒ 加粗、反引号 ⇒ 等宽）—— DOM 级判据（渲染后无裸标记 ∧ 强调真的以元素呈现）+ 源码面登记/接线守卫（承 issue #5033；2026-09-23 由「去掉标记」改判为「渲染」）（源: cases/product.yml）──
_CASE_PR_105 = EvalCase(
    id='PR-105',
    legacy_id='',
    title='🔴 商家可见文案里的 markdown 强调不得漏出字面标记：**保留标记 + 渲染层解析**（`**x**` ⇒ 加粗、反引号 ⇒ 等宽）—— DOM 级判据（渲染后无裸标记 ∧ 强调真的以元素呈现）+ 源码面登记/接线守卫（承 issue #5033；2026-09-23 由「去掉标记」改判为「渲染」）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['打开「企业基础设置 → 算料口径」/「企业基础设置 → 余料尺寸」：术语与参数说明里的重点词是**加粗**、配置键是等宽代码，屏幕上不该出现字面 `**` 或反引号（issue #6827 起因改准指针：#6580 已撤掉「工艺配置」/「参数总览」两个入口，配置面收口进 `/settings` 页内的配置域）'],
    expectations=[],
    data_checks=['判据 1·**改判与理由**（用户 2026-09-23 裁定）：同日合并的 #5206 走的是「把 71 处文案里的 `**` 删掉」；用户裁定「要**渲染**」⇒ 保留标记，新增渲染器 `frontend/admin-web/src/lib/inline-markdown.tsx`（只认 `**x**` 与反引号两种行内标记，其余逐字原样），并把「算料 / 余料回收 / 参数总览 / 余料台账」这几处的文案与渲染点接上。理由：删标记能让星号消失，但**强调本身也没了**，而这几处文案正是「哪几个字是重点」最需要被看见的地方。#5206 的其余部分（菜单 / 余料台账入口）**不回退**。', '判据 2·**DOM 级（红证实测）**：① `CraftCalcGlossary.test.tsx`：整块 `textContent` 不含 `**` 与反引号，且 `<strong>` 含「净窗高」「不改用料米数、也不改加工类型」、`<code>` 含 `oversize_height_threshold` / `HEM_MARGIN`；② `CalcCaliberPanel.test.tsx`：算料域摘要渲染出 `<strong>每一项都直接改米数 = 改钱</strong>` 与 `<code>HEM_MARGIN</code>`，余料域渲染出 `<strong>能再用</strong>`；③ `production-routings.test.tsx`：算料面板同上（`getAllByText(…, { selector })`）。**改前实测三条全红**（渲染层纯文本插值 ⇒ 字面星号原样上屏）。', '判据 3·**反恒真（两条必须同时成立）**：只判「不含 `**`」是**空判据** —— 把标记删掉同样绿（那正是被改判的方案）⇒ DOM 判据里同时有**正控**「`<strong>` / `<code>` 真的存在」。', '判据 4·**负控（渲染器不吞字）**：`tests/unit/lib/inline-markdown.test.tsx` 逐条判 ① 标记↔元素映射；② 去掉标记后可见文本与原文**逐字相等**；③ 单星号 / 未闭合 `**` / 手机号掩码 / 正则片段**不得**被当强调；④ `<img onerror=…>` 按文本呈现（无注入面：只建元素，不用 `dangerouslySetInnerHTML`）。不复用已装的 `react-markdown` 的理由：它把单星号当斜体、且默认输出块级 `<p>`（嵌在 `<p>`/`<span>`/`<td>` 里非法嵌套）。', '判据 5·**源码面登记/接线（发现面）**：`copy-no-markdown-emphasis.test.ts` ① 正控（检测器对成对/未闭合 `**` 必须报出，含 AST 种类与行号）；② 负控（掩码 / 注释 / JSX 注释不判违规 —— 面是 AST 非全文 grep）；③ **未登记即红**（带 `**` 的文件必须都在 `REGISTERED_MARKER_FILES` 里，本单 8 个）；④ **登记陈旧即红**；⑤ **接线即红**（6 个渲染点必须 import `@/lib/inline-markdown`，按 import 语句判定，不用注释文本）；⑥ 掩码登记表陈旧即红。', '判据 6·**不损失客户**：只改「标记 → 元素」的呈现并新增一个渲染器；不动任何数值 / 口径 / 端点 / 权限（对客金额、售价、成品口径逐值不变）。', '**边界（如实登记）**：① 服务端下发的字符串（余料 `notice`、后端错误 message）不在扫描面内（issue #5194 的穷举面 = `frontend/`）；② `frontend/mini-app` 有意不在面内 —— C 端助手消息经 `frontend/mini-app/src/utils/richText.ts` 的 `parseRichText` 真的解析强调；③ **未实装**：不做「文案 source → 消费方」静态映射（易腐），端到端上屏由判据 2 的三处 DOM 判据覆盖；④ 本单覆盖「算料 / 余料回收 / 参数总览 / 余料台账」；`inbound-orders` / `orders/new` / `processing-orders` / `worker-h5` 的同类标记已由 #5206 去掉（保持纯文本）—— 日后要加回强调，按登记表 ③ 走。'],
    skip_reason='[backend-contract] 前端文案 / 静态源码守卫（admin-web + worker-h5），由 vitest 单测（AST 静态守卫 + 组件渲染断言）执行，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui-copy', 'admin_web', 'inline-markdown', 'static-guard', 'config-ux'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-106 [NORMAL] 余料台账进侧边栏 —— **仓储与物料**（`inventory-center`）组新增「余料台账」(/production/remnants)：三处菜单源同构 + 权限码与页面门禁同码（用户裁定「补菜单」而非登记为域内下钻页；#5271 拆组后本项归「仓储与物料」，原写「生产管理组」）（源: cases/product.yml）──
_CASE_PR_106 = EvalCase(
    id='PR-106',
    legacy_id='',
    title='余料台账进侧边栏 —— **仓储与物料**（`inventory-center`）组新增「余料台账」(/production/remnants)：三处菜单源同构 + 权限码与页面门禁同码（用户裁定「补菜单」而非登记为域内下钻页；#5271 拆组后本项归「仓储与物料」，原写「生产管理组」）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['登录后打开侧边栏：生产管理组里能看到「余料台账」，点进去到 /production/remnants（与智能派单 / 省料看板口径一致）（⚠️ 本句记的是 **#5271 前**的 IA —— #5271 起「余料台账」在**「仓储与物料」（`inventory-center`）**组，与入库单/省料看板同组；组归属以本用例 `data_checks` 为准，本句只作历史留痕）'],
    expectations=[],
    data_checks=['判据 1·**三处同构**（漏任一处 = 「岗位权限页勾得动、侧边栏看不到」或反之）：`frontend/admin-web/src/config/menu.ts`（真实侧边栏单一来源）/ `MenuController.MENU_TREE`（`GET /api/admin/menus`，岗位权限页消费）/ `AuthService.buildMenusByPermissions`（登录下发）的**「仓储与物料」组（`inventory-center`；#5271 拆组前本项挂在「生产管理」组 —— 该表述已作废）**都含「余料台账」，节点名 / 路径 / 图标逐字一致且**顺序一致**（组内三项顺序 = 入库单 `/inbound-orders`（`inbound:view`）、余料台账 `/production/remnants`、省料看板 `/production/saving-board`（后两项 `processing:manage`），组名逐字「仓储与物料」、组 key 三源一致）。红证 A（实测）：只改 `menu.ts` 一处 ⇒ `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 判红（#5271 起比对**全树**：组 key + 组名 + 组顺序 + 导航型节点名）；红证 B：删掉 `menu.ts` 里该节点 ⇒ `remnants-menu-isomorphic.test.tsx` 判据 ① 与 PG-038 的面包屑覆盖同时判红。', '判据 2·**权限不放宽**（issue #5191 明写的判据）：菜单权限码 == `RemnantController` 类级 `@RequirePermission(「processing:manage」)` 的码**逐字相同**，且该节点确实落在 `permissions.contains(「processing:manage」)` 的 if 块内（测试取「该 add 之前最近的权限判定」，与注释长度无关 ⇒ 不假红）。**负控**：权限集只有 `order:list` 时渲染真实 `<Sidebar />` ⇒ 「余料台账」**不出现**（开菜单没有顺手把门禁放宽成「人人可见」）。', '判据 3·**真的点得到**（不是只断言常量表里有这行）：以 `processing:manage` 权限渲染**真实** `<Sidebar />` ⇒ 出现名为「余料台账」的 link 且 `href == /production/remnants`。', '判据 4·**面包屑（§15.2）**：`Header.tsx` 的 `/production/remnants` 条目 label == 菜单名「余料台账」，首项 == **「仓储与物料」**（#5271 拆组 —— 该组是面包屑首项的真值源，改前写「生产管理」），且该条**排在** `/production` 之前（本表 `find` 取首个命中，否则面包屑退化成「作业看板」）；对**每一个**菜单项的通用判据由既有的 PG-038（`menu-breadcrumb-coverage.test.tsx`）自动覆盖新增项。', '判据 5·**图标注册不是静默的**：`Sidebar.tsx` 的 `iconMap` 注册 `Recycle`（漏注册只会静默回落 `BarChart3`，不会有任何东西变红）；测试替身 `tests/setup.ts` 的 lucide 清单同步登记（漏登记则任何渲染 Sidebar 的用例当场抛错）。', '判据 6·**不损失客户**：纯入口变更 —— 不改任何端点、权限语义与金额/口径（对客金额、售价、成品口径逐值不变）。', '**边界（如实登记）**：① 未新增真实浏览器点击 E2E（本单以「渲染真实 Sidebar 组件 + 三源静态守卫 + Java 节点表断言」覆盖；e2e 旅程未加）；② 原先「企业参数中心 → 余料回收」域的下钻入口**保留**（两处入口并存，不删下钻）；③ 后端 Java 侧的 `MenuControllerTest` / `AuthServiceTest` 的节点表已同步（否则实现与测试漂移）。'],
    skip_reason='[backend-contract] 菜单 IA / 前端入口（admin-web + 服务端菜单树），由 vitest 单测（三源同构 + 真实 Sidebar 渲染 + 面包屑覆盖）+ Java 单测（MenuControllerTest / AuthServiceTest 节点表）执行，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['menu', 'ia', 'admin_web', 'remnant', 'static-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-107 [NORMAL] Python 侧真库判据不再静默 skip：兜底搜索路径与 Java 侧同源 + CI fail-closed（缺 PG 判红）+ skip 逐条可见（源: cases/product.yml）──
_CASE_PR_107 = EvalCase(
    id='PR-107',
    legacy_id='',
    title='Python 侧真库判据不再静默 skip：兜底搜索路径与 Java 侧同源 + CI fail-closed（缺 PG 判红）+ skip 逐条可见',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['（非 LLM 面）runner 的 PG 二进制在 /usr/lib/postgresql/16/bin（**不在 PATH**）时，Python 侧 13 个真库模块必须**真的执行**，不得静默 skip 成绿'],
    expectations=[],
    data_checks=['收口唯一：PG 二进制发现（候选目录 = PATH + /usr/lib/postgresql/{16,15,14}/bin，与 `backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java` 的 `BIN_DIRS` **同源**）与「缺 PG」处置只许在 `tests/unit_ci_workflows/pg_cluster.py` 有一份；13+1 个真库模块**零** `pytest.skip`、**零** `shutil.which`，一律经收口夹具 `realdb_binaries`，且 argv 用**绝对路径**（按名调用在 runner 上必然 `FileNotFoundError` —— 只修探测不修调用等于没修）', '冻结登记表：依赖真 PG 的测试模块集合 == `pg_cluster.REALDB_TEST_MODULES`（14 个 = 13 个真库模块 + v81），删 / 改名 / 新增未登记 ⇒ 红。**判据建在 AST 上**（只在注释 / 文档串里提 `initdb` 的 7 个 `docker-entrypoint-initdb.d` 一族**不算**真库判据）—— 防裸子串判据被文案喂绿 / 误红', 'CI 两道锁同时在位：`pr-check.yml` 的 `ci-workflow-tests` job 有「PG 二进制前置断言（initdb/pg_ctl/psql，缺失 ⇒ **独立一行** `exit 1`）」+「pytest 那步注入 `MIGAO_REQUIRE_REALDB`（真值 = 非空且非 0/false，键名与 `pg_cluster.ENV_REQUIRE_REALDB` 逐字一致）」；两处判定都先**剥注释**（注释与 `echo` 文案喂不绿）', '红证 A（真跑，2026-09-23 本机，覆盖孔 `MIGAO_PG_BIN_DIRS` 指向空目录）：**带**标记 ⇒ EXIT=1、`缺 PG 二进制 … ⇒ 本判据判 FAIL（不是 skip）`（88 条判据红）；**不带**标记（对照组）⇒ EXIT=0、88 skipped 且**逐条 nodeid + 原因**上屏 —— 两者真的不同（改前两者都是静默绿）', '红证 B / C（真跑，注入后复原并核 sha256 逐字节相同）：① 改名 `test_v93_route_rules_backfill.py` ⇒ 判据⑤（冻结常量）红；② 把 PG 相关的 `pytest.skip` 塞回夹具本体 ⇒ 判据⑥（单一收口）红', '正证（CI，`ci workflow helper unit tests`）：终端摘要的 `[realdb-summary]` 显示真库(PG)族「**执行 = N / skip = 0**」，且全部 skip 只剩本仓正当项（本分支尚未提交基线 / V83 尚未落地 / 浅检出无 origin/main 等）'],
    skip_reason='[backend-contract] CI workflow 结构 + Python 真库装配由 pytest 单测验证（tests/unit_ci_workflows/test_realdb_failclosed.py 的判据⑤~⑧，含对收口件的按路径加载断言），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['realdb', 'ci', 'fail-closed', 'evidence-strength'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-108 [NORMAL] 批量改价 - 两段确认（多选勾选集合 → 逐条「改前 → 改后」）→ 执行 → 撤销（源: cases/product.yml）──
_CASE_PR_108 = EvalCase(
    id='PR-108',
    legacy_id='',
    title='批量改价 - 两段确认（多选勾选集合 → 逐条「改前 → 改后」）→ 执行 → 撤销',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘和北欧风窗帘的价格都改成 155', '已选商品：遮光窗帘、北欧风窗帘', {'auto_respond': {'fallback': '确认'}}, '撤销刚才那个批量改价', {'auto_respond': {'fallback': '确认'}}],
    expectations=['interact(component=choice, multiSelect=true) or interact(component=confirm)', 'product_batch_update(action=preview, batch_type=product_price)', 'interact(component=confirm)', 'product_batch_update(action=execute)'],
    data_checks=['success=true', '两段确认缺一不可（机器断言）：第一段 = `interact(choice, multiSelect=true)`（集合可勾选时）或 `interact(confirm)`（集合已由商家给全时把逐条明细摆给他看）；第二段 = `interact(confirm)` + 执行必须带 preview 的 `batch_id` ⇒「没给商家看过逐条预览就执行」在**结构上不可达**', '逐条「改前 → 改后」由 `product_batch_update(preview)` 返回的 fields 派生（字段投影单一源 = backend/ai-agent-service/app/tools/confirm_value.py），断言见 backend/ai-agent-service/tests/test_product_batch_update.py', '撤销逐条还原为改前值 `old_value`（required_args[revert.batch_id] + 单测断言 `/revert` 端点与「还原」话术）', '部分失败逐条报告、不做整体回滚（单测断言：执行路径**不得**顺带调用 revert）', '阈值 N>50 拒绝并提示分批（本用例 N=2；边界判据见 PR-109）'],
    skip_reason='',
    tags=['batch', 'multi_turn', 'write', 'undo', 'two_stage_confirm'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    required_args=[{'tool': 'product_batch_update', 'action': 'preview', 'fields': ['batch_type', 'items']}, {'tool': 'product_batch_update', 'action': 'execute', 'fields': ['batch_id']}, {'tool': 'product_batch_update', 'action': 'revert', 'fields': ['batch_id']}],
    must_succeed=[{'tool': 'product_batch_update'}],
    post_clean=[{'type': 'product_price_restore', 'product_keyword': '遮光窗帘', 'price': 168}, {'type': 'product_price_restore', 'product_keyword': '北欧风窗帘', 'price': 128}],
    namespaces=['product_name:遮光窗帘', 'product_name:北欧风窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}, {'type': 'product_count_for_keyword', 'source': '北欧风窗帘', 'expect': 1}],
)

# ── PR-109 [NORMAL] 批量更新 - 阈值 N>50 拒绝分批 + batchType 白名单只有两个 + 两段确认结构锁 + 撤销逐条还原（确定性判据，非 LLM 面）（源: cases/product.yml）──
_CASE_PR_109 = EvalCase(
    id='PR-109',
    legacy_id='',
    title='批量更新 - 阈值 N>50 拒绝分批 + batchType 白名单只有两个 + 两段确认结构锁 + 撤销逐条还原（确定性判据，非 LLM 面）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['（非 LLM 面）一次提交 51 条批量改价 ⇒ 必须拒绝并提示分批；batch_type 传 product_name ⇒ 必须拒绝；execute/revert 不带 batch_id ⇒ 必须拒绝；preview 必须逐条给出「改前 → 改后」'],
    expectations=[],
    data_checks=['判据① 阈值（边界双侧）：N=51 ⇒ `success=False` / `error=batch_too_large` / suggestion 含「分批」且**不发请求**；N=50 ⇒ 放行（判据是 `> 50`，不是 `>= 50`）', '判据② batchType 白名单**只有两个**：`product_price`（field=basePrice）/ `inventory_stock`（field=stock，单位米）；传 `product_name` / `product_status` ⇒ `batch_type_unsupported` 且建议里点名两个合法值（通用批量有意不做；上下架按 2026-10-16 裁定单件/批量都 ❌，#7334 裁定 A 移除）', '判据③ 两段确认的**结构锁**：`execute` / `revert` 不带 `batch_id` ⇒ `batch_preview_required` 且不发请求；`batch_id` 只能来自 `preview` ⇒「跳过预览直接执行」在结构上不可达（不是靠 prompt 自律）', '判据④ 逐条 before → after：preview 返回 `preview[].fields` 逐条（商品ID / 改前价 / 改后价），且**逐字等于** `confirm_value.confirm_card_fields` 的产出（字段投影单一源，不新立第二份投影）', '判据⑤ 撤销逐条还原：`revert` 打到 `/api/admin/agent/batches/{batchId}/revert`、话术含「还原」；部分失败逐条报告且执行路径**不得**顺带调用 revert（不做整体回滚）；可撤销性以服务端真值字段 `revertible` 为准（`false` ⇒ 话术不得承诺可撤销）', '判据⑥ 权限码与逐条写**同码**：`required_permissions == ["product:create"]`（= `product_update` 的写码；契约正文本写的 `product:update` 在权限目录里**零命中**，用了会永久 403）', "判据⑦ 写面接线：注册表 + 门面导出（`from app.tools import ProductBatchUpdateTool`）+ `product` skill 绑定 + 写标注显式表态（`read_only=False` / `requires_confirmation=True` / `idempotent=True` / `read_only_actions={'preview'}` —— preview 免确认门禁否则两段确认在第一段之后死锁）", '红证（可执行）：以上每一条都由 backend/ai-agent-service/tests/test_product_batch_update.py 的对应用例**独立变红**（边界双侧 / 白名单 / 结构锁 / 单一源 / 端点归属 / 权限码 / 接线），不是一起红'],
    skip_reason='[backend-contract] 工具契约 / 阈值 / 两段确认结构锁 / 撤销端点归属 —— 全部由 pytest 单测（零 LLM、零网络，HTTP 客户端全程替身）执行，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['batch', 'threshold', 'static-guard', 'evidence-strength'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-014 [NORMAL] 批量库存调整 - 两段确认（多选勾选集合 → 逐条「改前库存 → 改后库存」）→ 执行 → 撤销（源: cases/product.yml）──
_CASE_PR_014 = EvalCase(
    id='PR-014',
    legacy_id='',
    title='批量库存调整 - 两段确认（多选勾选集合 → 逐条「改前库存 → 改后库存」）→ 执行 → 撤销',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把遮光窗帘和北欧风窗帘每个规格的库存都调到 1200 米', '已选商品：遮光窗帘、北欧风窗帘', {'auto_respond': {'fallback': '确认'}}, '撤销刚才那个批量调库存', {'auto_respond': {'fallback': '确认'}}],
    expectations=['interact(component=choice, multiSelect=true) or interact(component=confirm)', 'product_batch_update(action=preview, batch_type=inventory_stock)', 'interact(component=confirm)', 'product_batch_update(action=execute)'],
    data_checks=['success=true', '两段确认缺一不可（机器断言）：第一段 = `interact(choice, multiSelect=true)`（集合可勾选时）或 `interact(confirm)`（集合已由商家给全时把逐条明细摆给他看）；第二段 = `interact(confirm)` + 执行必须带 preview 的 `batch_id` ⇒「没给商家看过逐条预览就执行」在**结构上不可达**', '字段配对（机器断言）：`batch_type=inventory_stock` ⇒ 每条 `field` 必须是 `stock`（服务端 `AgentBatchService.TYPE_FIELD` 不配对直接 422），改前值 `oldValue` 必填（撤销的唯一依据）；判据见 backend/ai-agent-service/tests/test_product_batch_update.py 的 `TestInventoryStockBatch`', '阈值 N>50 拒绝并提示分批（本用例 N=2；边界判据见 PR-109）', '撤销逐条还原为改前值 `old_value`（服务端 `revert` → 状态 `reverted`；`revertible` 如实反映，false ⇒ 话术不得承诺可撤销）', '部分失败逐条报告、不做整体回滚（单测断言：执行路径**不得**顺带调用 revert）'],
    skip_reason='',
    tags=['batch', 'multi_turn', 'write', 'undo', 'two_stage_confirm', 'stock'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    required_args=[{'tool': 'product_batch_update', 'action': 'preview', 'fields': ['batch_type', 'items']}, {'tool': 'product_batch_update', 'action': 'execute', 'fields': ['batch_id']}, {'tool': 'product_batch_update', 'action': 'revert', 'fields': ['batch_id']}],
    must_succeed=[{'tool': 'product_batch_update'}],
    post_clean=[{'type': 'product_stock_restore', 'product_keyword': '遮光窗帘', 'stock': 500}, {'type': 'product_stock_restore', 'product_keyword': '北欧风窗帘', 'stock': 500}],
    namespaces=['product_name:遮光窗帘', 'product_name:北欧风窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}, {'type': 'product_count_for_keyword', 'source': '北欧风窗帘', 'expect': 1}],
)

# ── PR-110 [NORMAL] 工人可达的入库端点：零商家权限码 + 请求体**结构上**不可表达「任意调整」（源: cases/product.yml）──
_CASE_PR_110 = EvalCase(
    id='PR-110',
    legacy_id='',
    title='工人可达的入库端点：零商家权限码 + 请求体**结构上**不可表达「任意调整」',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人在车间用手机拍上游标签入库（非 LLM 行为，由 admin-api 单测与结构守卫覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 = **DTO 声明字段集**（不是运行时校验）：`WorkerInboundRecognizeRequest` = {images, barcode}、`WorkerInboundDraftRequest` = {productId, skuId, quantity, unitCost, dyeLot, supplier, supplierDocNo, warehouse, rollLengthM, remark}、`WorkerInboundPostRequest` = {confirmed} —— 三个集**恰好相等**（多一个键就红）；`adjustment` / `delta` / `setStock` / `stock` / `reason` / `operator` / `tenantId` / `targetType` / `source` / `importRunId` 一个都不在集里', '🔴 零商家权限码（源码判据）：控制器与服务源码里**没有** `@RequirePermission` / `PermissionInterceptor` / `requirePermission`，也不出现任何商家码字面量（`inbound:view` / `inbound:create` / `product:create` / `order:create`）', '🔴 不复用商家识别端点：源码不引用 `ImageRecognitionController` / `TARGET_PERMISSIONS` / `/api/admin/image-recognition`（复用的是能力 `ImageRecognitionClient`，不是那个人机接口）', '🔴 不新造库存增减：源码里没有 `receiveStock` / `deductStock` / `restoreStock` / `stock_ledger_entries` / `StockLedgerService`；过账本体必须落到 `inboundOrderService.create(` / `inboundOrderService.post(`', '路径面：控制器 `@RequestMapping` == `/api/worker/inbound`（不以 `/api/admin` 开头），且本包**只有** `/recognize`、`/drafts`、`/drafts/{id}/post` 三个 POST（标签位图 / 打印计数属 P2，不得顺手落进来）', '🔴 工人在 `/api/admin/**` 仍被拒：`SecurityConfig.ADMIN_API_REJECTED_ROLES` 含 `WorkerSessionService.WORKER_ROLE`（= `worker`），且该集合不含 `operator`/`admin`/`service`（反向护栏：门禁不是「把所有人都拒了」）'],
    skip_reason='[backend-contract] 工人入库面是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测与结构守卫覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-111 [NORMAL] 工人入库识别：解码优先（0 次 LLM）/ 降级不预填 / 零命中 SKU 不自动建品（源: cases/product.yml）──
_CASE_PR_111 = EvalCase(
    id='PR-111',
    legacy_id='',
    title='工人入库识别：解码优先（0 次 LLM）/ 降级不预填 / 零命中 SKU 不自动建品',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍上游标签 → 系统回候选（品名 / 色号 / 米数 / 条码原文），不落库、不动库存（非 LLM 行为，由 admin-api 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 成本守卫：请求带前端解码得到的条码原文 ⇒ 走解码路径且 `ImageRecognitionClient.recognize` **零调用**（`verify(..., never())`）；条码按货号精确匹配既有 SKU，零命中 ⇒ 空匹配 + 提示人工录入', 'vision 兜底：无条码时才调用，且 target 由服务端固定为 `inbound`（`verify(..., times(1)).recognize(eq("inbound"), any())`）—— 客户端结构上选不了 target', '🔴 不确定 ⇒ 不预填：vision 返回 `degraded=true` ⇒ 品名 / 色号 / 米数三格全 `null`、`skuMatches` 空、`requiresManualEntry=true`，只给人工录入提示（**不编造**）', '🔴 零命中不建品：品名 + 色号在 `product_skus` 零命中 ⇒ `skuMatches` 为空数组，且 `productMapper` / `productSkuMapper` 的 `insert` **零调用**、`receiveStock` 零调用（防 AI 幻觉造出假 SKU 还带库存流水）', '张数准入：0 张 / 4 张 ⇒ 400，且一次远端调用都不发生（上限 3 张沿用现状）', 'ai-agent 侧 schema 同源：`inbound` target 的字段键（issue #7759 起 5 个：model_no / product_name / color_name / quantity_meters / barcode）与 product / order 两个 target **零交集**，阈值取严档 0.85，低置信度（0.40）的米数**留空 + 给理由**且理由含「入库侧」'],
    skip_reason='[backend-contract] 入库识别是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + ai-agent vision 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'vision', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-112 [NORMAL] 工人入库过账：复用 #5045 过账 + Idempotency-Key 只加一次库存 + 未确认 / 跨租户拒绝（源: cases/product.yml）──
_CASE_PR_112 = EvalCase(
    id='PR-112',
    legacy_id='',
    title='工人入库过账：复用 #5045 过账 + Idempotency-Key 只加一次库存 + 未确认 / 跨租户拒绝',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人确认后提交过账（非 LLM 行为，由 admin-api 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['建草稿**不动库存**：`receiveStock` / `stockLedgerService.record` / `stockBatchMapper.insert` 全部零调用；响应 `status=draft`、`source=purchase`（工人面结构上传不出第二个来源值）、行上 `batchNo=null`', '🔴 数量准入（#5063 判据）：负数 / 0 / 超 1 位小数 ⇒ **400** 且一行都不落库；`0.5` 米的尾料可如实登记；`skuId` 不存在 ⇒ 400 且不自动建品', "🔴 过账才动库存：每次过账在 `stock_ledger_entries` 落一行 `reason='inbound'`，`before_qty` = SKU 当时库存、`after_qty − before_qty == 入库量`（`receiveStock` 恰好一次）", '🔴 幂等：同 `Idempotency-Key` 重复提交 ⇒ `claim` 第二次返回 false、回放首次结果（`replayed=true`），`receiveStock` 与 `record` 仍各只有一次、`markPosted` 只有一次；换新幂等键再提交 ⇒ 409（#5045 的条件更新闸），库存仍只加一次', '🔴 未确认不落库：`confirmed` 缺失 / false / null / 整个 body 缺失 ⇒ **409**，且 `receiveStock` / `record` / `markPosted` 零调用', '🔴 跨租户 / 非本人草稿 ⇒ **404**（不是 403，避免存在性泄露），且不写任何库存', '身份只来自 `X-Worker-Session-Id`：body 里塞 `operator` / `tenantId` 不被读取（`markPosted` 收到的 operator = session 解出的工人 id，tenant = 上下文租户）'],
    skip_reason='[backend-contract] 入库单是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'idempotency', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-113 [NORMAL] 入库标签短码与公开入口 /i/{短码}：两个码空间互斥（照 /s/ 范式、不复用其表）（源: cases/product.yml）──
_CASE_PR_113 = EvalCase(
    id='PR-113',
    legacy_id='',
    title='入库标签短码与公开入口 /i/{短码}：两个码空间互斥（照 /s/ 范式、不复用其表）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人过账后拿到 8 位短码、标签上印 https://app.migaozn.com/i/<短码>；任何持码人扫码 ⇒ 服务端 302 到落地页（非 LLM 行为，由 admin-api 单测与结构守卫覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 码形态：短码 = 8 位且每个字符都在 Crockford 字母表 `0123456789ABCDEFGHJKMNPQRSTVWXYZ` 内（生成面**从不产出** `I/L/O/U`）；手抄形态（小写 / `O` / `I` / `L`）归一化到同一短码（`O→0`、`I,L→1`）；形态不合法（长度不对 / 字符集外）⇒ 一次库都不查', '🔴 唯一与碰撞：分配器查重同时看**活码与留档码**（已撤销的码永不复发，DB 侧由 `uk_inbound_labels_code` 建在有效码 `COALESCE(short_code, revoked_code)` 上兜底）；连续 8 次碰撞 ⇒ 显式 `IllegalStateException`（**拒绝静默造重码**），不落任何标签行', '🔴 两个码空间互斥：`/i/` 面的源码不出现 `ProcessingSetPartToken` / `processing_set_part_tokens` / `REPORT_PAGE_PATH` / `"/b/?t="`（2026-10-27 起报工落地面由 `/w/` 改指 `/b/`，issue #7879；`/w/` 兼容期旧落点同样禁）；`/s/` 面的源码不出现 `InboundLabel` / `inbound_labels` / `"/i/"`；迁移 V134 的 **SQL**（剥注释后）不出现 `processing_set_part_tokens`；字母表字面量在 admin-api 主源码里**恰好一份**（`WorkerShortLinkService.java`）', '🔴 公开入口：`GET /i/{短码}` 未认证可达（`permitAll`）—— 未知短码 ⇒ **404**（不是 401）、已撤销 ⇒ **410 Gone**、有效 ⇒ **302** 且 `Location` 为**相对路径**（默认 `/b/?code=<短码>&tenant_id=<id>`）；响应体为空，`Location` 里没有品名 / 米数 / 供应商 / 单号等任何业务字段', '🔴 落地页地址走单一配置：改 `migao.inbound-label.landing-path` 即改 302 目标；解析文件里不出现硬编码域名（`migaozn.com`）', '🔴 未登记即红（类级）：控制器里出现的单字母短码前缀集合必须恰好等于登记表 `CODE_SPACES`（`/s/` + `/i/`）；每个前缀都必须在 `SecurityConfig` 的 permitAll 名单里', '🔴 撤销 = 短码置 NULL + 原码留档（`CHECK ((short_code IS NULL) <> (revoked_code IS NULL))`）⇒ 撤销后扫码仍是 410 而**不是 404**；DB 层码形状正则与 Java 侧字母表**机械等价**（逐字符集合相等）'],
    skip_reason='[backend-contract] 入库标签是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + 静态守卫 + 迁移契约覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'label', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-114 [NORMAL] 入库标签打印留痕：print_count 原子自增（并发不丢）+ 每次一行 audit_logs（第几次）（源: cases/product.yml）──
_CASE_PR_114 = EvalCase(
    id='PR-114',
    legacy_id='',
    title='入库标签打印留痕：print_count 原子自增（并发不丢）+ 每次一行 audit_logs（第几次）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人（设备侧）在打印一张入库标签**之前**调用服务端 /print 端点（非 LLM 行为，由 admin-api 单测与源码守卫覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 原子自增：计数走 SQL 内 `COALESCE(print_count, 0) + 1`（不是读出 +1 再写回）；一次 `/print` 调用恰好一次自增，**重打同样计数**（3 → 4 → 5）', '🔴 并发不丢（**真库**，两层都判）：① mapper 层 24 个连接并发自增 ⇒ 计数 == 24；② **服务调用链**层 24 并发 `recordPrint` ⇒ 计数 == 24（只测 ① 时「服务改成读改写、mapper 仍原子」这种退化不会变红 —— 该洞由红证实测发现并补上）', '🔴 每次打印一行审计：`audit_logs` 落 `action=print` / `resource_type=inbound_label` / `resource_id`=标签 id / `resource_name`=短码，details 带 `shortCode` 与 `printCount`（第几次）与 `itemId`；审计携带的 operator / IP / UA 来自请求（谁 / 何时）', '🔴 打印必留痕（结构判据）：`COALESCE(print_count…)` 只在 `InboundLabelMapper`；`inboundLabelMapper.incrementPrintCount(` 只被 `InboundLabelService` 调用；`inboundLabelService.recordPrint(` 只被 `/print` 端点调用 ⇒ **结构上不存在**第二条写计数的路径；计数与审计在**同一次调用**里', '🔴 本包**不做服务端位图**（`/bitmap` 端点零命中；§7.2 已改判为设备侧 canvas 渲染）⇒ 详情读面只回字段、不回任何可直打的渲染产物（没有「拿到图就本地直打」的旁路）', '拒绝口径：未登录 ⇒ **401**（一次业务调用都不发生）；跨租户 / 不存在 ⇒ **404**；已撤销 ⇒ **410** 且**不计不审**；自增影响 0 行（并发撤销 / 软删）⇒ 404，绝不回一个没落库的计数'],
    skip_reason='[backend-contract] 入库标签是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + 源码守卫覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'label', 'audit', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-115 [NORMAL] 入库标签详情读面：按短码回 50×30mm 渲染所需全部字段；跨租户 404 / 已撤销 410（源: cases/product.yml）──
_CASE_PR_115 = EvalCase(
    id='PR-115',
    legacy_id='',
    title='入库标签详情读面：按短码回 50×30mm 渲染所需全部字段；跨租户 404 / 已撤销 410',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人扫到 / 拍到一张已打印的观星台标签 ⇒ 打开单据详情核对后重打一张（功能② 的硬依赖；非 LLM 行为，由 admin-api 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['字段面够渲染一张 50×30mm 标签：短码原文 / 入库单号 / 明细行 id / 货号 / **品名**（实读 `products.name`，商品已删 ⇒ null 不编造）/ 色号 / 门幅 / **米数** / 缸号 / 批次号 / **供应商** / 送货单号 / 仓库 / **入库日期** / 标签生成时间 / 已打印次数', '🔴 跨租户 / 不存在 ⇒ **404**（不是 403：403 等于确认「这码存在，只是不归你」），且在**碰任何单据数据之前**就拒（不拿「单据查不到」冒充租户判据）', '🔴 跨租户去戳一个**已撤销**的码 ⇒ 仍是 404（先判租户、后判撤销 ⇒ 不泄露「这个码存在过」）', '🔴 已撤销（本租户）⇒ **410 Gone** + 错误码 `LABEL_REVOKED` + 可行动建议（补打一张，不静默回落到别的标签）', '零商家权限码：详情面源码里没有 `@RequirePermission` / `PermissionInterceptor` / 任何商家码字面量；准入判据只有有效工人 session（无 / 无效 ⇒ 401）'],
    skip_reason='[backend-contract] 入库标签是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'label', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-116 [NORMAL] 工人可达的照片上传：零商家权限码；非图片 / 超张数 / 超尺寸 ⇒ 400（源: cases/product.yml）──
_CASE_PR_116 = EvalCase(
    id='PR-116',
    legacy_id='',
    title='工人可达的照片上传：零商家权限码；非图片 / 超张数 / 超尺寸 ⇒ 400',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人在车间用手机拍上游标签 / 布卷包装并上传（拿 URL 后喂给识别端点；非 LLM 行为，由 admin-api 单测覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 补的是 P1 留下的真缺口：P1 的 `recognize` 收「已上传好的 URL」，而现有一切上传端点都在 `/api/admin/**` 且带商家权限码 ⇒ 工人够不着；本端点是工人**唯一**可达的照片上传面', '🔴 零商家权限码：源码里没有 `@RequirePermission` / `PermissionInterceptor`；**工人持 session 即可上传**（不是「有码就放行」，而是这条路径根本不查商家码）；无 / 无效 session ⇒ **401** 且一张都不落存储', '🔴 只收真图片：MIME 不是 `image/*` ⇒ 400；MIME 是 `image/png` 但**读不出图像头**（改名 + 伪造类型的文本）⇒ 400（按**内容**判，不按文件名 / Content-Type 判）；空文件 ⇒ 400', '张数：1~3 张（上限 = `WorkerInboundService.MAX_IMAGES`，与识别端点**同一常量**）；0 张 / 4 张 ⇒ 400；单张 >5MB ⇒ 400；单边 >8000px ⇒ 400', '存储**复用**既有 `FileStorageService`（目录 `inbound`），不新造存储 / 不新建桶约定；三张合法照片 ⇒ 200 + 三个 URL（可直接喂 `recognize` 的 `images`）'],
    skip_reason='[backend-contract] 入库上传是后台/仓储单据流（无黄金策工具面，AI 侧未接）⇒ 由 admin-api 单测 + 结构守卫覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'worker', 'upload', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-117 [NORMAL] 入库标签的码在边缘可用：app.migaozn.com 的 /i/<短码> 走 admin-api（不是 SPA fallback）+ 限流预算真的计账（源: cases/product.yml）──
_CASE_PR_117 = EvalCase(
    id='PR-117',
    legacy_id='',
    title='入库标签的码在边缘可用：app.migaozn.com 的 /i/<短码> 走 admin-api（不是 SPA fallback）+ 限流预算真的计账',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人把标签贴到布卷 / 塑料袋上；任何人用手机扫 https://app.migaozn.com/i/<短码> ⇒ 服务端 302 到落地页（非 LLM 行为，由 nginx 结构判据 + 线上落地面探针覆盖）'],
    expectations=['direct_reply'],
    data_checks=['🔴 补的是 P2 留下的**静默串端**缺口：端点（InboundLabelShortLinkController）与 permitAll 都已落好，但 `deploy/swas/nginx.conf` 里 `location /i/` 命中数 = 0 ⇒ 扫码落到 `location /` 的 SPA fallback，**HTTP 200 + C 端元元首页**。线上实测（2026-09-27）：`GET /i/<任意形态>` 的 body 与 `GET /` 逐字节同哈希，而同刻 `/s/<任意>` = 404（到了 admin-api）', '🔴 边缘归属（离线判据，tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py 的 F1~F3）：登记表 PUBLIC_PREFIX_FACES 覆盖 `/s/`、`/i/`（代理到 admin-api:8080）、`/b/`（静态 + 自己的命名空间 fallback）、`/w/`（由 `location /` 的 root 承载，风险已登记）；三个发现面（控制器短码前缀 / nginx 公开前缀 location / 发布腿 H5_SUBDIR）**未登记即红**', '🔴 `proxy_pass` **不带 URI 后缀**：语义模拟断言 `/i/<任意形态>` 的转发路径原样（写成 `…:8080/i;` ⇒ 变成 `/i7K3M9QP2`，控制器收不到自己的路径 ⇒ 判据红）', '🔴 端到端链路（离线语义模拟）：`/i/<短码>` 代理到 admin-api ⇒ 302 → 落地页 `/b/?code=…` → nginx `location /b/` → bmini 的 index.html；探针覆盖 `/i/`、`/i/<任意形态>`、`/s/`、`/b/`、`/b/<子路由>`、`/w/`、`/`（零回归：根仍是 C 端、`/b/` 不串端）', '🔴 线上活体断言（deploy/scripts/bmini-h5-verify-served.sh ⑤，由 bmini-h5-publish.yml 在 nginx.conf 变更时重跑）：`GET /i/<不可能存在的短码>` 必须到 admin-api（未知短码 404 / 已撤销 410），**不得**返回根页；判定刻意**不用**「状态码是 302」（未知短码本来就 404），而是「body 是否与 `GET /` 同哈希」+ 5xx 判定', '🔴 限流预算（tests/unit_ci_workflows/test_swas_nginx_rate_limit.py 判据 4/6/8）：`/i/` 与 `/s/` **同族同档**（worker_entry：per-IP 50 r/s + burst 1000；正常用量 = 一次扫码 1 个请求 ⇒ 余量 ≥ 10×），**不**套内部管理面的宽预算；且 `$worker_entry_key` 的 map 必须覆盖 `/i/` —— 否则 key 为空、nginx「空 key 不计账」⇒ 限流是空断言（判据 8 = map 语义求值 + 注入式红证）', '零回归：`/`（C 端元元）、`/b/` 与 `/b/<子路由>`（bmini）、`/w/`（worker-h5，逐字节）、`/s/`（admin-api 代理）四段既有语义一字未改（判据 = 同一套语义模拟 + 既有 worker-h5 / bmini 身份断言）'],
    skip_reason='[backend-contract] 边缘接线与限流预算是**确定性**判据（nginx 语义模拟 + 结构守卫 + 线上落地面探针），由 pytest 单测与发布腿覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['inventory', 'inbound', 'label', 'nginx', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-119 [NORMAL] 按批次库存盘点（最小录入式）：实盘录入 + 差异落批次分录 + SKU 库存同事务对齐（issue #5865）（源: cases/product.yml）──
_CASE_PR_119 = EvalCase(
    id='PR-119',
    legacy_id='',
    title='按批次库存盘点（最小录入式）：实盘录入 + 差异落批次分录 + SKU 库存同事务对齐（issue #5865）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单的单批次剩余库存米数是否有设计这个字段？要支持用户按批次做库存盘点（用户 2026-10-01 会话逐字；档位裁定 = A 最小录入式，盘盈盘亏口径裁定 = 实盘为准、差异写台账调整）'],
    expectations=['direct_reply'],
    data_checks=["🔴 红线①**不原地改** `stock_batches.quantity`：盘点的差异落 `stock_batch_consumptions` 的一条 `reason='stocktake'` 分录，派生余量自动跟上。判据 = `backend/admin-api/src/test/java/com/migao/admin/service/BatchStocktakeRealDbTest.java` 的 `journalKeepsQuantityAndRealignsBothLedgers`（**全表** `quantity` 原串快照盘前盘后逐值相同，不是只看这一行）+ `BatchStocktakeServiceTest.java` 的 `neverTouchesBatchRow`（`StockBatchMapper` 零写调用）", '🔴 红线②**批次分录与 SKU 库存同一事务**：`BatchStocktakeService#stocktake` 是本单唯一写入口，`@Transactional(rollbackFor = Exception.class)`；判据 = `BatchStocktakeRealDbTest#secondBatchFailureLeavesNothingBehind` —— 用 BEFORE INSERT 触发器让**第 2 个批次写入途中**失败 ⇒ 第 1 个也不落、`product_skus.stock` 一字不动；**并带无事务对照读数**（同一注入在无事务边界时残留 1 行 ⇒ 证明注入真的生效，回滚才是它没留下的原因）', "🔴 红线③**来源可与「加工单扣料」区分**：盘点行 `reason='stocktake'` + `stocktake_run_id`，三个扣料专属列（`processing_order_no` / `order_no` / `order_item_id`）一律留空；DB 约束 `ck_batch_consumption_source_shape` 把两族列形状钉成互斥（盘点行带加工单号 ⇒ 23514；扣料行缺加工单号 ⇒ 同样 23514）。判据 = `BatchStocktakeRealDbTest#sourceShapeAndIdempotencyAreEnforcedByTheDatabase`（含**注入式红证**：回滚事务里摘掉约束 / 索引 ⇒ 同一行坏数据当场能落库，SQLSTATE 00000/00000 ⇒ 拦住它的确实是这两个 DB 对象）+ 类级守卫 `tests/unit_ci_workflows/test_batch_stocktake_write_point.py`", '🔴 红线④**禁止负余量**：实盘米数 `-1` ⇒ 400（`ERR_STOCKTAKE_NEGATIVE`，文案给可行动出口）；盘亏会让 `product_skus.stock` 变负 ⇒ 422 `INSUFFICIENT_STOCK`。两条都发生在**任何写入之前**（预校验 + 先算后写）。判据 = `BatchStocktakeServiceTest#rejectsNegativeAndOverPrecisionAndWritesNothing` / `#refusesWhenSkuStockWouldGoNegative`', '🔴 红线⑤**幂等**：`delta = 0`（实盘 == 当刻余量）⇒ **零写入**（分录 / 台账 / SKU 库存三处都不动）；同一 `runId` 重放 ⇒ 该批次跳过（读半边 `stocktakeRecordedBatchIds` + 写半边部分唯一索引），跨请求不双记。判据 = `BatchStocktakeRealDbTest#zeroDeltaWritesNothing` / `#replayWithSameRunIdDoesNotDoubleBook`（三张表行数与 SKU 库存逐值不变）+ `BatchStocktakeServiceTest#zeroDeltaWritesNothing` / `#replayWithSameRunIdWritesNothing`', '🔴 红线⑥**不静默取整**：实盘米数沿用 `StockQuantity.requireOneDecimal` —— `2.755` ⇒ 400（文案「最多支持 1 位小数…服务端不做静默取整」），且零写入。判据 = `BatchStocktakeServiceTest#rejectsNegativeAndOverPrecisionAndWritesNothing` + `BatchStocktakeRealDbTest#invalidAmountIsRejectedWithoutAnyWrite`', '🔴 红线⑦**盘点后 `/reconcile` 的批次部分不得增大**：`diff = Σ批次余量 − product_skus.stock` 由两条腿各自聚合（批次分录腿与销售台账腿），盘点让两边按**同一个 Σdelta** 变 ⇒ 差额恒等。真库判据用「盘前差额 −40（批次 60 / SKU 100）」做夹具（判别力：只动一条腿的实现会得到 −41.5）。判据 = `BatchStocktakeRealDbTest#journalKeepsQuantityAndRealignsBothLedgers` 的 `[#5865 红线⑦] 盘前 diff = -40，盘后 diff = -40` 读数', '**端到端可见**（判据 9）= `UI-077`：商品详情批次面板按货号列出批次与当前余量 + 实盘输入 + **差异预览（± 与合计）** + 提交后列表刷新为新余量', '**类级元守卫**（判据 8）= `MC-053` / `tests/unit_ci_workflows/test_batch_stocktake_write_point.py`：批次台账写入点唯一（未登记即红）；余量派生（Σdelta 读口）只许在台账服务与其 mapper 里', "🔴 判据 D-2（独立复核后收口）：**盘点行进不了「生产消耗」的三条计量腿** —— `sumDeltaBySku`（对账的派工扣减净额腿）/ `sumSavingByPeriodCohortMaterial`（省料看板）/ `sumOutputAreaByPeriod`（产出面积）三处汇总一律按 `reason IN ('processing_order','processing_order_cancelled')` **显式包含**（新来源默认不进计量腿，要进必须显式登记）。改前真库实测（零派工零订单、只插一条盘点行）：三条腿读出 `delta=-1.5/formula=1.5`、省料看板多一张「unknown 来源」组卡（line_count=1）、产出面积多一行 —— 一次盘亏被读成「这个月消耗了 1.5 米布」（本仓自认最大的失败模式：**归因错**）。判据 = `BatchStocktakeRealDbTest#stocktakeRowsStayOutOfConsumptionMetrics`（加盘点行前后三条腿读数**逐值相同**，并反向断言余量派生**必须**含盘点差异）；**红证（实测）**：摘掉三处过滤 ⇒ 读数由 `sku:-2.0/2.0|saving:2.0/2.0/1|area:0/1` 变成 `sku:-3.0/3.0|saving:3.0/3.0/2|area:0/2` ⇒ 判据红。`reconcile` 的 `diff` 不受影响（两腿同增同减）故不改。", '🔴 判据 D-1（独立复核后收口）：**V143 的回滚段必须真能跑** —— 迁移文件里每一条 `-- -- ` 开头的行 = 一句真 SQL（共 8 句），判据逐句实跑。改前实测：第 ④ 句 42710（缺前置 `DROP CONSTRAINT IF EXISTS`）、两句 `SET NOT NULL` **根本没写** ⇒ 按净效果回滚后原先被形状约束挡住的非法行能落库（`00000`）⇒ 「两族可区分」这条合约被永久拆掉。判据 = `BatchStocktakeRealDbTest#rollbackPathIsExecutableAndRestoresTheContract`（8 句全 rc=0；回滚后非法行重新被拒 `23502` —— 形状约束没了由 NOT NULL 顶上；**负对照**：跳过两句 `SET NOT NULL` ⇒ 同一行 `00000`）；两条读数都在测试输出里。'],
    skip_reason='[backend-contract] 盘点写面是确定性的账务判据（真库 + mock + 结构守卫三层，无 LLM 环节、无黄金策工具面）由 admin-api 单测与 pytest 结构守卫覆盖，不进入 agent-eval 冒烟',
    tags=['inventory', 'batch', 'stocktake', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 账务面用例：前置（租户 / 商品 / SKU 库存 / 批次行）由判据自建 —— `BatchStocktakeRealDbTest` 在 `@BeforeAll` 起一次性真 PG 集群并跑真 `schema.sql` 建终态后插入夹具；`BatchStocktakeServiceTest` 用桩 mapper 造「入库量 60 + Σdelta」的派生余量。前置不成立时判据直接红（真库缺 PG 由 `PgCluster` fail-closed，不走 skip）；agent-eval 栈不跑它',
)

# ── PR-120 [NORMAL] 商品页版式：「拍照 / 上传识别」进「新增商品」标题卡片内的标题行右侧（识别在重置前），不再悬在卡片外（源: cases/product.yml）──
_CASE_PR_120 = EvalCase(
    id='PR-120',
    legacy_id='',
    title='商品页版式：「拍照 / 上传识别」进「新增商品」标题卡片内的标题行右侧（识别在重置前），不再悬在卡片外',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-01 走查截图 + 提问：「放到新增商品标题右侧合适位置是否更好」⇒ 裁定：是，且建单页同步对齐'],
    expectations=[],
    data_checks=['判据 1·**落点在标题卡片内**（issue #5918）：`image-recognize-button` 是标题卡片 `pf-title-card` 的后代，且与「重置」同处 `pf-title-actions` 这一行、**识别在前**（DOM 顺序）；全页只有**一个**识别入口（不再有游离于卡片外的第二处）。执行点 = frontend/admin-web/tests/unit/pages/products-new-recognize-entry.test.tsx 判据 1。红证：改前页面把它渲染在表单卡片**之外**的独立容器里（页面底色上），且 `pf-title-card` / `pf-title-actions` 都不存在 ⇒ 该文件 3 条判红（实测同一批 9 failed / 43 passed 中的 3 条）。', '判据 2·**功能一条不减 + 识别结果不落库**：选图 → 上传（`uploadApi.uploadImage`）→ 识别（`imageRecognizeApi.recognize`，target 逐字 `product` + 上传得到的地址）→ 字段回填（含来源徽标 `recognized-marker-name` 与结果区 `image-recognize-result`），全程**零** `productApi.createProduct`（识别结果只填表，提交永远是人的动作）。执行点同上，判据 2 / 2b。', '判据 3·**建单页不退化**（跨页口径）：/orders/new 的同一入口仍在「商品信息」卡标题行（frontend/admin-web/tests/unit/pages/orders-new-layout.test.tsx 判据 2：按钮在商品信息卡内、**不在**收货信息卡内）。两页的按钮文案 / 组件 / 回调语义不变。', '**类级元守卫**（判据 4）= frontend/admin-web/tests/unit/recognize-entry-placement-guard.test.ts：凡 frontend/admin-web/src 下渲染 `<ImageRecognizeButton` 的文件都必须**登记落点**（未登记即红、台账双向相等、豁免台账只许缩短），且每条登记必须同时给出①容器文件 + 逐字容器锚 ②断言「按钮在卡片里」的**运行期证据**（测试文件 + 用例标题逐字可查 —— 台账不许空口声称有人守着）；含四种坏形态（未登记 / 死条目 / 容器锚缺失 / 证据缺失）的判别力自证。', '**改 web 页面 ⇒ 多模态验收**（migao-dev-flow §15.7）：真实登录 + 全页截图 + 读图逐条判定；证据目录、被测 commit 与逐条判定写在承接 PR 的 body 里。'],
    skip_reason='[backend-contract] 管理端商品页版面与识别入口落点的**确定性 DOM 判据**（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：计分通道 = `traces.tests`（vitest），与库内同类条目共用这个历史遗留的窄标记',
    tags=['product', 'admin-web', 'layout', 'image-recognize', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-121 [NORMAL] 入库 receiveStock：null 均价（新 SKU 首次入库「不记单价」）必须能过真 PG —— PG 参数类型推断（源: cases/product.yml）──
_CASE_PR_121 = EvalCase(
    id='PR-121',
    legacy_id='',
    title='入库 receiveStock：null 均价（新 SKU 首次入库「不记单价」）必须能过真 PG —— PG 参数类型推断',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['入库单过账（含页面明示允许的「新 SKU 首次入库 + 明细不记单价」这条路径）'],
    expectations=['direct_reply'],
    data_checks=['**病（真库实测，2026-10-02）**：新 SKU（avg_cost 为 NULL）+ 明细留空单价 ⇒ movingAverage 返回 NULL ⇒ receiveStock(..., newAvgCost=null, ...) ⇒ PG 抛 `ERROR: could not determine data type of parameter $3`（`receiveStock-Inline`）⇒ BadSqlGrammarException ⇒ 接口 500（issue #5975 的服务端栈逐字如此）。根因 = `CASE WHEN #{newAvgCost} IS NULL` 里的绑定**没有类型锚点**（左边没有列/cast/函数签名），实参为 NULL 时 PG 拿到 unspecified 类型参数、推断不出。判据 = backend/admin-api/src/test/java/com/migao/admin/service/ProductSkuReceiveStockNullCostRealDbTest.java（真 PG，4 条）。**红证（修前实测读数）**：`Tests run: 4, Failures: 1, Errors: 2` —— 两条 NULL 实参判据抛 PSQLException、一条判据失败；**带单价的对照条通过**（证明判据认的是「null 参数」而不是「SQL 变了没有」）。', '**判据 1（过账成功 + 落库三件套）**：全新 SKU + 不记单价首次过账**不得抛异常**，且 `stock` 0→3、`latest_batch_no` 落批次号；`avg_cost` / `cost_amount` 留 **NULL**（不用 0 冒充「成本为零」）。执行点 = 同文件 `newSkuFirstPostWithoutUnitCostSucceeds` / `costUnknownStaysNullNotZeroAfterCostlessPost`。', '**判据 2（跨次语义）**：先不记单价过账（avg_cost 仍 NULL）→ 再带单价过账 ⇒ 均价取带价那次、`cost_amount` = 总库存 × 均价（3 + 3 = 6，单价 10 ⇒ 60）。执行点 = 同文件 `costlessFirstPostThenCostedSecondPostAccumulates`。', '**判据 3（SQL 形态钉在类型上）**：`newAvgCost` 的**每个**绑定都必须显式 `jdbcType=NUMERIC`，裸 `#{newAvgCost}` 一处都不许留 —— 丢掉 jdbcType 就是回退到 500。执行点 = backend/admin-api/src/test/java/com/migao/admin/mapper/ProductSkuMapperTest.java 的 `receiveStockBindsCostWithExplicitNumericJdbcType`（反射读 @Update 注解 SQL，定位串与 `avg_cost = #{newAvgCost,jdbcType=NUMERIC}` / `CASE WHEN #{newAvgCost,jdbcType=NUMERIC} IS NULL` 对齐）。'],
    skip_reason='[backend-contract] 入库过账的**真库**判据 + Mapper SQL 形态契约（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：admin-api 单测面（真 PG 一次性集群，走 PgCluster.startOrAbort() 收口）',
    tags=['inventory', 'inbound', 'backend-contract', 'realdb', 'null-param'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-122 [NORMAL] 商品/SKU 超长文本入参（货号 >30 等）⇒ 422 可行动文案（不是 500）—— DTO/库列长度准入 + 类级元守卫（源: cases/product.yml）──
_CASE_PR_122 = EvalCase(
    id='PR-122',
    legacy_id='',
    title='商品/SKU 超长文本入参（货号 >30 等）⇒ 422 可行动文案（不是 500）—— DTO/库列长度准入 + 类级元守卫',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['建品 / 改品 / Excel 导入时填了超过库列上限的货号（如 31 个字符）'],
    expectations=['direct_reply'],
    data_checks=['**病（实测，2026-10-04）**：`POST /api/admin/products` 传 31 字符 `skuCode`（库列 `products.sku_code` = `varchar(30)`）⇒ PG 报 `ERROR: value too long for type character varying(30)` @ `ProductMapper.insert` ⇒ HTTP 500 `INTERNAL_ERROR`「服务器内部错误」——用户无法自救（不知道哪一列、该改多长）。修前 DTO **零长度准入**（`ProductCreateRequest.skuCode` 无任何注解），Service 层也未见校验。', '**判据 1（表单路径 4xx + 可行动文案 + 零写入）**：`POST /api/admin/products` 传 31 字符货号 ⇒ **422**、`$.error.code = VALIDATION_ERROR`、文案含「最长 30 个字符」「当前 31 个字符」「请缩短」，且 `productMapper.insert` **一次都没被调用**。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/ProductSkuCodeLengthAdmissionTest.java 的 `overlongProductSkuCodeIsRejectedWithActionableMessage`。', '**判据 2（边界）**：长度 = 列上限是**合法**输入（30 字符 ⇒ 放行到写面；`PUT` 路径 30 字符 ⇒ 落到「商品不存在」= 闸门之后的下一步，而不是被长度准入拦下）—— 准入不得挡掉合法边界值。执行点 = 同文件 `productSkuCodeAtColumnLimitPassesTheLengthGate` / `updateProductUsesTheSameGate`。', '**判据 3（同族写面同源拒绝）**：SKU 级 `skus[].skuCode` > 50、`skus[].doorWidth` > 20、`colors[].colorName` > 30 各自被同一收口拒绝（SKU / 颜色表零写入）。执行点 = 同文件 `skuFaceOverlongFieldsAreRejectedFromOneGate`。', '**判据 4（家族覆盖：不走 Bean Validation 的路径）**：agent 路径手工 `new ProductCreateRequest` + 直调 `ProductService#createProduct`（即 `createProductForAgent` 的形态）同样 422 + 可行动文案 —— 只给 DTO 加 `@Size` 会漏掉它；Excel 导入行（`upsertImportedProduct` → `saveColorsAndSkus`）走同一收口。执行点 = 同文件 `agentPathIsGatedTooEvenThoughItSkipsBeanValidation`。', '**判据 5（类级元守卫 = 真值现取 + 未登记即红）**：写面收口的**上限字面量**必须等于**现取** `information_schema.columns.character_maximum_length`（真 PG 跑 `schema.sql` 终态）；四个商品入参 DTO 的每个 String 字段必须登记；未登记 / 台账空转 / 有界列被登记成无界 / 无收口 / 上限漂移 / 豁免增长 / 扫描面为空 ⇒ 各自判红；豁免台账冻结上限 = **0**、条数现取。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/ProductTextColumnAdmissionMetaGuardTest.java。', '**判据 6（真库边界读数）**：现取 `products.sku_code` = `varchar(30)`；真库直插 30 字符**成功**、31 字符报 SQLState `22001`（string_data_right_truncation = `value too long for type character varying(30)`）。执行点 = 同文件 `realDbBoundaryReadingMatchesLiveColumn`。'],
    skip_reason='[backend-contract] 入参健壮性 + DTO↔库列长度对账（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：admin-api 单测面（元守卫走一次性真 PG，PgCluster.startOrAbort() 收口）',
    tags=['product', 'backend-contract', 'input-robustness', 'realdb', 'text-length'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-123 [NORMAL] 并发过账同一 SKU 的入库单：台账 before/after 必须来自同一条原子语句（RETURNING）⇒ 链式相接、禁止同基（issue #6300）（源: cases/product.yml）──
_CASE_PR_123 = EvalCase(
    id='PR-123',
    legacy_id='',
    title='并发过账同一 SKU 的入库单：台账 before/after 必须来自同一条原子语句（RETURNING）⇒ 链式相接、禁止同基（issue #6300）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['两张**同一 SKU** 的草稿入库单（10 米 / 15 米）**同时**过账（同一 microtask 门控同时 PATCH /api/admin/inbound-orders/{id} {action:post}）'],
    expectations=['direct_reply'],
    data_checks=['**病（真库并发实测读数）**：两行台账出现**同一个 before**（同基）、before/after 链断裂；净增量仍对 ⇒ **只看库存查不出来**。生产读数 = acceptance/2026-10-04/race-sweep/out/probe-write-raw.json::cases.W3（两行 [{delta=10, before=65.0, after=75.0}, {delta=15, before=65.0, after=80.0}]、chainBad=[{at:2246, prevAfter=75.0, curBefore=65.0}]、sameBaseConcurrentRead=true）与 W7（100.0→115.0 / 100.0→110.0）；顺序对照 = probe-redproof-raw.json::RP3（台账 1 行、链正常）。根因 = backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java 的 `post` 里 `beforeQty = sku.getStock()` **快照读** → `receiveStock` 原子自增 → `record(beforeQty, afterQty)` 用的是陈旧值。', '**判据 1（净增量，正对照）**：真库并发判据 = backend/admin-api/src/test/java/com/migao/admin/service/InboundPostLedgerChainRaceRealDbTest.java 的 `concurrentPostKeepsLedgerChainConnected`（3 轮）：两单都过账成功、库存净增量 == 两单数量之和（25）。**这条在修前也是绿的** —— 证明装置有判别力（链断裂不是「什么都判不出来」）。', '**判据 2（链式相接）**：本 SKU 的 inbound 行按 id 升序，每行 before == 上一行 after，首行 before == 初始库存，末行 after == 当前库存，行数 == 2。**红证（修前实测）**：`#2{before=50.0, after=65.0}` 与 `#3{before=50.0, after=60.0}`（两行同基）⇒ 当场红。修后：`#2{before=50.0, after=65.0}` / `#3{before=65.0, after=75.0}`。', '**判据 3（行内自洽）**：每行 `delta == after - before`。', '**正对照（护栏不误杀）**：同文件 `serialPostStillSucceeds` —— 单张草稿单串行过账仍成功、台账 1 行、链成立。', '**类级元守卫（铁律 8）**：backend/admin-api/src/test/java/com/migao/admin/service/StockDeductionAndLedgerAtomicityMetaGuardTest.java 的 `ledgerBeforeAfterComeFromAtomicStatement` —— 现取 OrderService / InboundOrderService 里落台账的库存变更方法：每次 `record(…)` 的实参不得读自快照（`.getStock()`），且所在方法体必须有原子取值锚（`RETURNING` 或逐字 `atomic-ledger: true`）。'],
    skip_reason='[backend-contract] 入库过账台账链的**真库并发**判据 + Mapper SQL 形态契约（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：admin-api 单测面（真 PG 一次性集群，走 PgCluster.startOrAbort() 收口）',
    tags=['inventory', 'inbound', 'ledger', 'concurrency', 'backend-contract', 'realdb'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-015 [NORMAL] 雪花号 id 不许经过 Number()：源码面元守卫射程 = admin-web + bmini-app（两个语料根）（源: cases/product.yml）──
_CASE_PR_015 = EvalCase(
    id='PR-015',
    legacy_id='',
    title='雪花号 id 不许经过 Number()：源码面元守卫射程 = admin-web + bmini-app（两个语料根）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家/工人在任何前端面提交带雪花 id 的表单（商品 SKU 选择、入库建单、派工候选）：id 必须逐字原样透传，不得在端侧转成 double'],
    expectations=['direct_reply'],
    data_checks=['判据 1·正控：检测器对 `Number(sku.id)` / `parseInt(o.productId)` / `parseFloat(x.skuId)` 必须报出（没有这条，「零命中」可能只是检测器瞎了）', '判据 2·负控：`Number(item.quantity)`（非 id）/ `String(sku.id)`（没转 double）/ `sku.id`（没调用）/ `String(chosenSku?.skuId)`（#6340 修好后的形态）/ 注释里的写法 —— 都不得判违规', '判据 3·🔴 未登记即红：**两个语料根**（frontend/admin-web/src/** + frontend/bmini-app/src/**）真实语料命中且不在登记表 ⇒ 红并具名打印 `文件:行 → 代码`；登记表当前为空 = 一处都不许', '判据 4·登记陈旧即红（登记过却已无命中 ⇒ 红，留着会让守卫悄悄放宽）', '判据 5·反空跑（**逐根**）：每个根的语料文件数必须 > 50（根写错 / 目录改名 ⇒ 红，而不是「那个根 0 命中」的假绿）', '判据 6·射程自证：射程声明必须恰好是 admin-web + bmini-app 两个根，且 bmini 的入库页确实被扫到'],
    skip_reason='[backend-contract] 确定性源码面守卫（vitest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['snowflake-id', 'precision', 'meta-guard', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-016 [NORMAL] 建品/改品 status 枚举准入：非法值 4xx 且列出合法枚举；状态机死行（active/on_shelf）可改回 off_sale/draft 自救（源: cases/product.yml）──
_CASE_PR_016 = EvalCase(
    id='PR-016',
    legacy_id='',
    title='建品/改品 status 枚举准入：非法值 4xx 且列出合法枚举；状态机死行（active/on_shelf）可改回 off_sale/draft 自救',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['（非 LLM 行为：状态准入由 admin-api 服务层单测 + 仓内语料元守卫覆盖，不进 agent-eval 冒烟）'],
    expectations=['direct_reply'],
    data_checks=['🔴 建品/改品传非法 status（active / on_shelf / in_warehouse / ON_SALE / 含空格 …）⇒ **422 VALIDATION_ERROR**，且文案**列出合法枚举**（draft(草稿)/under_review(审核中)/on_sale(出售中)/off_sale(已下架)）——不是「请检查字段格式是否正确」这种无出路的话', '🔴 合法集合**单一真值源** = backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java 的 STATUS_TRANSITIONS 键集（PRODUCT_STATUSES 必须是它的派生）；admin-api 主源码里别处不得再定义 ≥3 个状态 token 的集合字面量；createProduct / updateProduct 两个入口都必须走 requireValidStatusOrNull', '🔴 状态机死行（当前状态不在状态机内，如 active / on_shelf / in_warehouse）⇒ 报错**必须给可执行出路**（改回 off_sale(已下架) 或 draft(草稿) 修正回状态机），**禁止**再出现「允许的目标状态: 无」；且该出路真的走得通（PUT /api/admin/products/{id}/status body={"status":"off_sale"} 成功），但**不允许**从死行直接跳到 on_sale（来历不明的行不得被直接上架）', "🔴 仓内语料（含 acceptance/** 的 harness）里商品 status 字面量必须全部落在合法集合内：引信 = acceptance/2026-10-04/worker-miniapp-sweep/harness/bootstrap-chain.mjs 原先建品写 status:'active'（另有 19 个 harness 文件、共 20 处写 status:'on_shelf'）", '🔴 写入方**未登记即红**：tests/unit_ci_workflows/product_status_write_sites.json ⇄ 现取检出集双向相等（新写入方未登记 ⇒ 红；陈旧条目 ⇒ 红，台账只许缩短）', "判别力自证：注入真语料（把 bootstrap-chain.mjs 的 status:'on_sale' 改回 'active'）⇒ 判据当场红；不改 ⇒ 不报（反向对照）"],
    skip_reason='[backend-contract] 商品状态准入是服务层枚举校验（无黄金策工具面）⇒ 由 admin-api 单测（ProductStatusAdmissionTest）+ 仓内语料元守卫（tests/unit_ci_workflows/test_product_status_single_source.py）覆盖，不进入 agent-eval 冒烟',
    tags=['product', 'status', 'validation', 'backend-contract', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-020 [NORMAL] 图片识别色号清单拆行：一张色卡的 16 个色号 ⇒ 16 行颜色（改前塞成一格、被 30 字符输入框削断）（issue #6354）（源: cases/product.yml）──
_CASE_PR_020 = EvalCase(
    id='PR-020',
    legacy_id='',
    title='图片识别色号清单拆行：一张色卡的 16 个色号 ⇒ 16 行颜色（改前塞成一格、被 30 字符输入框削断）（issue #6354）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['建品页「拍照 / 上传识别」喂一张色卡图（识别报告逐字给出 `2699-01、2699-02、…、2699-16`，共 127 字符）'],
    expectations=['direct_reply'],
    data_checks=['**病（用户 2026-10-05 实测读数）**：识别报告面板显示 16 个色号，落到表单「颜色分类」只剩 `2699-01、2699-02、2699-03、` —— 恰好 30 字符（颜色行名称框 maxLength = COLOR_NAME_MAX = 30）⇒ 第 4 个色号被静默削断、SKU 矩阵只出 1 行。根因 = frontend/admin-web/src/lib/image-recognize.ts 的 `buildProductPrefill` 把整串当一个 `colors[0].colorName`。', "**判据 1（实例，改前必红）**：`buildProductPrefill` 收 16 色号 + 门幅 `3.2` ⇒ `colors` 恰 16 行、`skus` 恰 16 行且逐行 colorName 与色号顺序一致；`recognizedFields` 里 `color` 只出现 1 次。红证（修前实测，5 failed）：`expected [ Array(1) ] to deeply equal [ '2699-01', '2699-02', …(14) ]`、`expected [ { id: '-4', …(1) } ] to have a length of 200 but got 1`。", '**判据 2（类级元守卫，铁律 8）**：`buildProductPrefill` 产出的**每一个**颜色名长度必须 ≤ `COLOR_NAME_MAX`（超限即红并具名打印哪个颜色名 / 多长）—— 防「拆了但仍超限」与「上限改小却不同步」。改前红证：`以下颜色名超过表单上限 30，会被输入框静默截断: expected [ Array(1) ] to deeply equal []`。', '**判据 3（口径单一）**：分隔符口径与 `SkuMatrix.tsx::BatchColorInput`（人工「批量输入颜色」）同一套（换行 / 中英文逗号 / 顿号），且上限常量只有一处定义（`lib/product-limits.ts`）—— 组件里再写死一份 ⇒ 红。', "**判据 4（封顶与去重）**：超过 `MAX_COLORS` 的输入 ⇒ 截到 200；逐字重复的名字去重、但**不猜、不改写**颜色名（`2699-01、2699-01、 2699-02 、2699-02` ⇒ `['2699-01','2699-02']`）。", '**边界（如实登记）**：**单个**颜色名本身超过 30 字符时本层不裁剪（那是颜色名不该这么长的表单侧问题）⇒ 由判据 2 具名报出，交给表单校验，不在预填侧猜改；`MAX_SKUS`（600）不在本层裁剪（预填恒 1 个门幅 ⇒ 颜色数即 SKU 数）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 vitest（frontend/admin-web/tests/unit/lib/image-recognize-color-split.test.ts、frontend/admin-web/tests/unit/lib/product-limits.test.ts、frontend/admin-web/tests/unit/components/ImageRecognizePrefill.test.tsx）验证，非 LLM 行为，不进入 agent-eval 冒烟 —— 断言的「拆行 + 上限 + 口径单一」全部可在单测里逐值钉住',
    tags=['image-recognize', 'color', 'frontend', 'prefill', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-022 [NORMAL] 图片识别门幅清单拆行 + 识别卡片描述转可读纯文本：一键填入后「规格尺寸」不再 (0)、卡片不再裸显示 <p>（issue #6403）（源: cases/product.yml）──
_CASE_PR_022 = EvalCase(
    id='PR-022',
    legacy_id='',
    title='图片识别门幅清单拆行 + 识别卡片描述转可读纯文本：一键填入后「规格尺寸」不再 (0)、卡片不再裸显示 <p>（issue #6403）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['建品页「拍照 / 上传识别」喂一张面料图（识别报告给出颜色一串 + 门幅逐字 `2.8米和3.2米`）'],
    expectations=['direct_reply'],
    data_checks=['**病（用户 2026-10-06 实测，4 张截图）**：① 同一张图「颜色进得来、门幅一个都进不来」—— 一键填入后页面「规格尺寸 (0)」；② 识别卡片「商品描述」逐字显示 `<p>…</p><p>…</p>`。根因 = frontend/admin-web/src/lib/image-recognize.ts 的 `buildProductPrefill` 把 `door_width` 当**标量**（多值串归一后 `Number(...)` 为 `NaN` ⇒ 整串被丢），而 `color` 走的是清单口径（issue #6354）；以及 frontend/admin-web/src/components/image-recognize/FormInterpretCard.tsx 的 `{field.label}：{field.value}` 纯文本渲染。', "**判据 1（实例，改前必红）**：`buildProductPrefill` 收 `door_width='2.8米和3.2米'` ⇒ `doorWidths = ['2.8','3.2']`；顿号 / 斜杠 /「与」/ 中英文逗号同效；`'2.8米'` ⇒ `['2.8']`（**旧行为不许变**）；`'深灰色'` ⇒ 该键不出现（非数仍必须丢）；`2.8` / `2.8米` / `门幅2.8` 按 `sameDoorWidth` 去重；SKU 行数 = 颜色数 × 门幅数。执行点 = frontend/admin-web/tests/unit/lib/image-recognize-door-width-split.test.ts。", '**判据 2（页面级，改前必红）**：多值门幅串一键填入 ⇒ 真 SkuMatrix 渲染 **2 行**「规格尺寸」（改前「规格尺寸 (0)」）。执行点 = frontend/admin-web/tests/unit/components/ImageRecognizePrefill.test.tsx「判据 2」（真 ProductForm + 真 SkuMatrix）+ frontend/admin-web/tests/unit/pages/products-new-recognize-entry.test.tsx「判据 2c」（`/products/new` 的一键填入链路；该文件里 `SkuMatrix` 是替身 ⇒ 断言它收到的 `doorWidths`）。', "**判据 3（展示层纯函数，改前必红）**：`htmlToPlainText('<p>a</p><p>b</p>')` ⇒ 两段可读文本且**不含 `<` `>`**；`&amp;` ⇒ `&`（数字实体同样解码）；纯文本入参**原样**；连续空行收敛。执行点 = frontend/admin-web/tests/unit/lib/rich-text-plain.test.ts。", '**判据 4（卡片，改前必红）**：`form-interpret-field-description` 的文本**不含 `<p>`** 且两段内容都在。执行点 = frontend/admin-web/tests/unit/components/FormInterpretCard.test.tsx「判据 4c」。', '**判据 5（反向守卫，落值口径未变）**：`buildProductPrefill` 落给表单的 `description` 仍是**原始 HTML**；卡片回传 `onFill` 的 `value` 也是原始 HTML —— 展示层不改落值（富文本区 / 入库需要 HTML）。执行点 = frontend/admin-web/tests/unit/lib/rich-text-plain.test.ts 的「反向守卫」+ FormInterpretCard.test.tsx「判据 4d」。', '**判据 6（类级元守卫，铁律 8）**：`LIST_SEMANTIC_FIELD_KEYS` 登记表 ⇄ 探针表**双向相等**，且每一个登记为清单语义的识别字段都必须能把多值串拆开落进表单（新增同类字段却按标量处理 ⇒ 红）；并扫描源码断言门幅拆分复用**唯一**那份分隔符表（再声明第二个 `*SEPARATORS` 常量 / 在 `doorWidthsOf` 里自写 `.split(` ⇒ 红）。', '**边界（如实登记）**：本守卫只裁「识别字段 → 预填落点」这一族的清单语义（现登记 `color` / `door_width`）；**未登记**的清单字段不在此射程内。`SkuMatrix.tsx::BatchColorInput`（人工「批量输入颜色」）的分隔符口径与行为**本单未改**（`COLOR_LIST_SEPARATORS` 值逐字不变，判据 3 的「同一套表」仍绿）。展示层改的是纯文本化，**未**渲染富文本（HTML 注入面另行裁定）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 vitest（frontend/admin-web/tests/unit/lib/image-recognize-door-width-split.test.ts、frontend/admin-web/tests/unit/lib/rich-text-plain.test.ts、frontend/admin-web/tests/unit/components/FormInterpretCard.test.tsx、frontend/admin-web/tests/unit/components/ImageRecognizePrefill.test.tsx、frontend/admin-web/tests/unit/pages/products-new-recognize-entry.test.tsx）验证，非 LLM 行为，不进入 agent-eval 冒烟 —— 拆行 / 丢非数 / 去重 / 纯文本转换都能逐值钉住',
    tags=['image-recognize', 'door-width', 'frontend', 'prefill', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-131 [NORMAL] 图片建品「补充一句」的字面事实落表单：货号 2659 / 门幅 2.8+3.2 / 颜色按「货号-序号+颜色名」/ SKU 4 行（issue #7528）（源: cases/product.yml）──
_CASE_PR_131 = EvalCase(
    id='PR-131',
    legacy_id='',
    title='图片建品「补充一句」的字面事实落表单：货号 2659 / 门幅 2.8+3.2 / 颜色按「货号-序号+颜色名」/ SKU 4 行（issue #7528）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['建品页「拍照 / 上传识别」的补充一句里逐字写：「这个商品的货号是2659，颜色格式是2659-序号+颜色名，门幅是2.8和3.2」，再上传一张色卡图'],
    expectations=['direct_reply'],
    data_checks=['**病（用户 2026-10-23 实测，五项同时缺失）**：货号空缺 / 商品属性全空 / 门幅未选中 / 颜色不按格式 / SKU 0 行。根因四条：① 货号**不在** backend/ai-agent-service/app/vision/targets.py 的 `TARGET_FIELDS["product"]`；② 门幅的**推理值**被冻结契约拦掉（关联 #6356 的裁定）；③ 那句话只当推理上下文（提示词逐字「不得改变输出格式与铁律」）；④ SKU = 颜色 × 门幅，门幅空 ⇒ 0 行。', "**判据 1**：解析用户原句 ⇒ 货号 `2659`、门幅 `['2.8','3.2']`、命名规则 `{code:'2659'}`。执行点 = frontend/admin-web/tests/unit/lib/declared-facts.test.ts。", '**判据 2（负例，防「见数字就抓」）**：`这款有2659个颜色` 不产货号/门幅；`颜色格式按序号+颜色名`（无货号）不产规则；门幅超区间（26）不认；超过 3 根门幅不认。', '**判据 3**：`01米白、02雾霾蓝` ⇒ `2659-1米白、2659-2雾霾蓝`（序号 1 起、不补零、丢图上原序号）；幂等；改名后超 30 字 ⇒ 整体不改（输入框会静默削断，半截名字更糟）。', '**判据 4**：规格属性命中内置选项即选中；否定前缀（`不要提花` / `无需遮光`）与单字选项（`棉` / `麻`）不参与。', "**判据 5（类级守卫 + 注入式反证）**：解析产出的键必须落在 `sku_code` / `door_width` / `SPEC_EN_TO_CN` 全键里；手造 `{key:'price'}` 事实 ⇒ 被过滤（涉钱面不许被一句话带进表单）。", "**判据 6（页面级，改前必红）**：真 `/products/new` 页 —— 填那句话 + 上传 ⇒ 一键填入后 `ProductAttributes.skuCode='2659'`、`SkuMatrix` 收到 `doorWidths=['2.8','3.2']`、颜色两行改名、SKU **4 行**，且仍零 create/update。执行点 = frontend/admin-web/tests/unit/pages/products-new-recognize-entry.test.tsx「判据 2d」。", '**判据 7（不覆盖 / 可覆盖）**：`[图片识别]` 已有值的格不被覆盖；`[米宝解读]` 的推断值可被商家明说的字面事实覆盖。执行点 = frontend/admin-web/tests/unit/components/FormInterpretCard.test.tsx「判据 6~9」。', '**边界（如实登记）**：只认三类显式说法（货号/款号/商品编号、门幅/幅宽/门宽、颜色格式/命名）；那句话里枚举颜色名**本单不做**（颜色内容仍必须来自图）；后端契约与 `INTERPRETABLE_KEYS` 白名单**零改动**（判据：backend/ai-agent-service/tests/test_vision/test_interpret.py 全绿）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 vitest（declared-facts / FormInterpretCard / products-new-recognize-entry / image-recognize）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['image-recognize', 'declared-facts', 'prefill', 'frontend', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-023 [NORMAL] 余料「回收 / 报废」的状态迁移走 DB 原子条件更新（CAS）⇒ 并发双 recover 恰一次回收额入账、回收×报废恰一个赢家（issue #6960）（源: cases/product.yml）──
_CASE_PR_023 = EvalCase(
    id='PR-023',
    legacy_id='',
    title='余料「回收 / 报废」的状态迁移走 DB 原子条件更新（CAS）⇒ 并发双 recover 恰一次回收额入账、回收×报废恰一个赢家（issue #6960）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['并发两个 recover 打同一块**可用**余料（非 LLM 行为，由真 PG Java 判据 + 静态元守卫覆盖）'],
    expectations=[],
    data_checks=['🔴 **判据 1（真库并发 + 窗口注入，改前必红）**：并发双 `recover` ⇒ 成功数 **== 1**、落败方 **409 CONFLICT**、终态 `used`、`recovered_amount` **逐值等于**「余料米数 × 批次均价」（夹具常量独立复算，不读被测读面）。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/RemnantRecoverRaceRealDbTest.java。**窗口探针** = `RemnantService#setRecoverProbePauseMillisForTest`（生产恒为 0；只让第一个到达者停顿 ⇒ 对手走完「读-判 → CAS 0 行 → 409」全长）。', '🔴 **判据 2（回收 × 报废交叉，改前必红）**：同一行的同一个 `available` 只能被消耗一次 ⇒ 恰一个赢家，终态 ∈ {used, scrapped} 且与赢家自洽（回收赢 ⇒ 报废留痕列全 NULL；报废赢 ⇒ 回收列全 NULL）。两者争**同一份**状态迁移权，一个写面有 CAS、另一个没有就**不互斥**（修前实测两个都 200 / 唯一约束异常）。', '**判据 3（串行正对照，护栏不误杀）**：无并发时 `recover` / `scrap` 各成功一次（谓词非空 ⇒ 正常请求不被 409 误杀）。', "🔴 **判据 4（类级元守卫，铁律 8）**：`FabricRemnantMapper` 里写 `status` 的手写 SQL 必须带完整谓词（`status='<当前态>'` + `tenant_id` + `deleted = 0` —— 本表**有**软删列，逐字核对 schema.sql）；`RemnantService` 里每条状态写路径必须登记进 backend/admin-api/src/test/resources/remnant-status-cas-ledger.json（**未登记即红** / 幽灵条目即红 / 豁免只许缩短且条数现取）；且 CAS 调用后必须有 `== 0` 的行数判定（只留调用不判 0 行 / 把判定塞进 `if (false && …)` 都判红）。执行点 = RemnantStatusCasMetaGuardTest.java（含八种坏形态的合成语料判别力自证）。", '**红证（注入式 · 双向，实测）**：探针开（800ms）+ 退回修前的无谓词 `updateById` ⇒ 1 failed，逐字读数 `状态码=[200, 200] 成功数=2 409数=0`；恢复修后 ⇒ 3 passed，读数 `状态码=[409, 200] 成功数=1 终态=used 回收额=50.000000`。探针关（0ms）⇒ 并发档按设计判红（`探针未在 10000ms 内进入窗口` —— 无探针的并发判据会退化成 flake，故探针是**硬前提**）。元守卫侧：抽掉 mapper 谓词里的 `deleted = 0` ⇒ `everyStatusWriteCarriesTheFullPredicate` 判红并具名 `[markRecovered 缺 [deleted=0 谓词], markScrapped 缺 …]`。', '**边界（如实登记）**：① 跑的是**服务层真库并发**而非 HTTP 栈（controller 只是薄转发）；② **回收额算法一字未动**（只钉「并发恰一次」）；③ 探针对象全部自建（tenant 6960），随一次性临时 PG 集群销毁，不碰存量数据；④ 元守卫是**纯文本形态判据**（无 AST），真实防线是该条真库判据，两者缺一不可。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配 + 窗口注入）+ 源码静态元守卫，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['remnant', 'concurrency', 'cas', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-028 [NORMAL] Agent 批次「执行 / 撤销」的准入走 DB 原子条件更新（CAS）⇒ 并发 execute/revert 恰一轮 apply、商品终态可复算（issue #6960）（源: cases/product.yml）──
_CASE_PR_028 = EvalCase(
    id='PR-028',
    legacy_id='',
    title='Agent 批次「执行 / 撤销」的准入走 DB 原子条件更新（CAS）⇒ 并发 execute/revert 恰一轮 apply、商品终态可复算（issue #6960）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['并发两个 execute（或两个 revert）打同一批次（非 LLM 行为，由真 PG Java 判据 + 静态元守卫覆盖）'],
    expectations=[],
    data_checks=['🔴 **判据 1（真库并发 + 窗口注入，改前必红）**：并发双 `execute` ⇒ 成功数 **== 1**、落败方 **409**、**真的落到商品上的 apply 恰一轮**（1 条明细 ⇒ 恰 1 次调用；计数器由 `CountingProductService`（真 ProductService 的有界子类，真库真写）现取）、批次终态 `done`、商品 `status` **逐字等于 newValue**。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/AgentBatchStatusRaceRealDbTest.java。**窗口探针** = `AgentBatchService#setBatchProbePauseMillisForTest`（生产恒为 0）。', '🔴 **判据 2（并发 revert，改前必红）**：成功数 == 1、apply 计数恰 1、批次终态 `reverted`、商品被还原成持久化的 `oldValue`。', '**判据 3（无探针并发对照 + 串行正对照）**：无窗口注入、`CyclicBarrier` 同时起跑 ⇒ 仍恰一个赢家 + 恰一轮 apply（CAS 不依赖注入）；串行 `execute` + `revert` 各成功一次、状态来回（谓词非空 ⇒ 不误杀正常请求）。', "🔴 **判据 4（类级元守卫，铁律 8）**：`AgentBatchMapper` 里写 `status` 的手写 SQL 必须带谓词 —— `status='<来源态>'`（或 `status IN (…)`，值由服务层传参）+ `tenant_id`；⚠️ **本表没有 `deleted` 列**（逐字核对 schema.sql）⇒ 谓词里出现 `deleted = 0` 反而**判红**（本仓出过「模板写了 `deleted=0` 但该表没有这一列」）。每条状态写路径必须登记进 backend/admin-api/src/test/resources/agent-batch-status-cas-ledger.json（未登记即红 / 幽灵即红 / 豁免只许缩短），且 CAS 调用后必须有 `== 0` 判定。执行点 = AgentBatchStatusCasMetaGuardTest.java。（**⛔ 本包不动** MC-100 `InboundOrderStatusCasMetaGuardTest` 与 PG-075 `ProductionOperationDeleteCasMetaGuardTest` —— 它们归 #6956。）", '**红证（注入式 · 双向，实测）**：探针开 + 退回修前（CAS 结果不判）⇒ 1 failed，逐字读数 `状态码=[200, 200] 成功数=2 409数=0 apply次数=2 批次终态=partial`；恢复修后 ⇒ 4 passed，读数 `状态码=[409, 200] 成功数=1 409数=1 apply次数=1 批次终态=done 商品终态=on_sale`。元守卫侧：把 `if (batchMapper.markExecuting(…) == 0)` 改成不判行数（`if (false && …)`）⇒ `noStatusWritePathUsesUnconditionalUpdateById` 判红并具名 `[CAS 调用没判影响行数（execute 的 markExecuting 后 300 字符内没有 == 0)）]`。', '**边界（如实登记）**：① 跑的是**服务层真库并发**而非 HTTP 栈；② **有意不加方法级 `@Transactional`**（类注释取舍 ②③：逐条独立提交 = 部分失败的载体）⇒ 本单主张的是「准入闸 = 单条语句的 CAS」，**不**主张事务边界；③ revert 的 claim 中间态复用既有 `executing` 取值（**不**扩 DB 的 `ck_agent_batch_status` 约束）；④ 元守卫是纯文本形态判据，真实防线是该条真库判据。'],
    skip_reason='[backend-contract] 真 PG 判据（initdb+pg_ctl 临时集群 + Java 真装配 + 窗口注入）+ 源码静态元守卫，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['agent-batch', 'concurrency', 'cas', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-124 [NORMAL] 米宝解读可落值的商品字段放开为 name/material/craft/color；door_width 与 price 只写 note 建议、值不落地（issue #6361）（源: cases/product.yml）──
_CASE_PR_124 = EvalCase(
    id='PR-124',
    legacy_id='',
    title='米宝解读可落值的商品字段放开为 name/material/craft/color；door_width 与 price 只写 note 建议、值不落地（issue #6361）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把一张面料图发给黄金策并要求「按这张图建商品」⇒ 黄金策调 image_recognize 时带 interpretations（含 name/material/craft/color 的贴近结论）'],
    expectations=['direct_reply'],
    data_checks=['**口径（用户 2026-10-05 逐字裁定）**：「不可信没关系，先推理一份贴近的结论」⇒ 商品侧可落值的键 = `name` / `material` / `craft` / `color`（来源一律 `[米宝解读]`）。', '**判据 1（逐字钉住，会红）**：`backend/ai-agent-service/app/vision/deep_channel.py::INTERPRETABLE_KEYS["product"]` 恰为 `("name","material","craft","color","description")`（#6362 追加描述格）；`["order"]` 保持 `()`。判据 = tests/test_vision/test_deep_channel.py。', '**判据 2（涉钱两格不落值，注入式红证）**：`interpretations={"price": {"value": "199", "note": "建议 199 元"}}` ⇒ 该格 `value` **仍为空**、`note` / `note_source` 存在；`door_width` 同。判据 = tests/test_vision/test_deep_channel.py 的注入式用例（把 `_empty_cell` 的 `value=None` 改成写回 ⇒ 当场红）。', '**判据 3（不覆盖）**：内核 `[图片识别]` 已给值的格、以及目录歧义格（有 candidates）**一律不被解读覆盖** —— 既有注入式红证保持绿。', '**判据 4（来源可分辨）**：落值格 `source == "[米宝解读]"` 且 `note_source` 同名；与 `[图片识别]` 不同（商家据此判断该信哪一格）。', '**边界**：内核 `recognizer` 的「只抄写明的内容」铁律**一字未动**（transcription 与 inference 是两层）；本端点**不落库**（TestNoWriteBoundary 保持）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 pytest（backend/ai-agent-service/tests/test_vision/test_deep_channel.py、tests/test_tools_image_recognize.py）验证，非 LLM 行为，不进入 agent-eval 冒烟 —— 可落值集合与「不落值」两半都能逐值钉住',
    tags=['image-recognize', 'interpretation', 'backend-contract', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'product_manage', 'action': 'create'}],
)

# ── PR-125 [NORMAL] 米宝解读额外生成商品描述文案 ⇒ 预填建品页「图文描述」富文本区（来源 [米宝解读]、有值才写键、不覆盖商家内容）（issue #6362）（源: cases/product.yml）──
_CASE_PR_125 = EvalCase(
    id='PR-125',
    legacy_id='',
    title='米宝解读额外生成商品描述文案 ⇒ 预填建品页「图文描述」富文本区（来源 [米宝解读]、有值才写键、不覆盖商家内容）（issue #6362）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-05 逐字「然后把商品描述的文案也要生成一份」⇒ 黄金策的 interpretations 里带 description（HTML 片段）'],
    expectations=['direct_reply'],
    data_checks=["**判据 1（落值）**：前端 `frontend/admin-web/src/lib/image-recognize.ts::buildProductPrefill` 收到 `{key:'description', value:'<p>…</p>', source:'[米宝解读]'}` ⇒ `initialData.description` **逐字**等于该值、`recognizedFields` 含 `description`。判据 = tests/unit/components/ImageRecognizePrefill.test.tsx。", "**判据 2（空值不写键，会红）**：`value` 为空 / 键缺失 ⇒ `'description' in initialData === false`（**绝不写空串** —— 那会覆盖商家自己写的描述；表单是 `{...prev, ...initialData}` 合并语义）。", '**判据 3（徽标各认各的键）**：描述格在**解读清单**里 ⇒ 渲染 `interpreted-marker-description`（`[米宝解读]`），且**不得**出现 `recognized-marker-description`（`[图片识别]`）。红证：预填了描述却一枚徽标都没有 ⇒ 该断言红。', '**判据 4（字段表登记）**：`backend/ai-agent-service/app/vision/targets.py` 的 product 字段表含 `description`（类级元守卫：前端读的键必须在内核字段表里 —— 不登记即红）。', '**边界（如实登记）**：描述**文案质量**（是否编造、是否贴图）判据红不了，只由字段表 hint 的口径约束（「不得编造图上没有的硬事实」）；徽标的**端到端**可见性只有组件级判据（Playwright 页面验收未落）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 vitest（frontend/admin-web/tests/unit/components/ImageRecognizePrefill.test.tsx、tests/unit/lib/image-recognize.test.ts）+ pytest（tests/test_vision/test_targets.py、test_recognizer.py、test_deep_channel.py）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['image-recognize', 'description', 'frontend', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'product_manage', 'action': 'create'}],
)

# ── PR-126 [NORMAL] 识别 vs 推理的分工按字段定死：生成类字段（商品名/商品描述）只由 [米宝解读] 给值，识别路径永不许直填（issue #6386）（源: cases/product.yml）──
_CASE_PR_126 = EvalCase(
    id='PR-126',
    legacy_id='',
    title='识别 vs 推理的分工按字段定死：生成类字段（商品名/商品描述）只由 [米宝解读] 给值，识别路径永不许直填（issue #6386）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户提供真实色卡图，要求「可以实际测试跑这个功能」⇒ 用真模型（deepseek-flash / V4.1-Flash）跑，不给 hint、带 hint 各一次'],
    expectations=['direct_reply'],
    data_checks=['**真跑现场（修前，可复算）**：`name` = 「常青藤系列窗帘面料色卡」、`description` = 一段完整文案，两格都被标成 `[图片识别]`（=抄的），而图上根本没有这两段内容 —— 同图同提示词只改 hint，两次 `description` 文案**不同** ⇒ 是**生成**的。来源标记把「猜的」标成「抄的」= 比留空更危险。', '**判据 1（字段表）**：`targets.TARGET_FIELDS["product"]` 里 `name` / `description` 的 `recognizable=False`；`color` / `material` / `craft` / `door_width` / `price` 仍为 `True`。', '**判据 2（不给模型这一格）**：`recognizer._schema_for("product")` 不含 `name` / `description`；而 `deep_channel._schema_for` 仍含它们（页面上要有这两格，否则表单少格）。', '**判据 3（类级元守卫，会红）**：**凡 `recognizable=False` 的字段，`[图片识别]` 直填路径永不产出它的值** —— 把全量字段都摆成「已识别且有值」跑 `build_page_fill`，这些格不得带 `SOURCE_RECOGNIZED`。将来新增同类字段自动受约束。', '**判据 4（自否证的值必须丢）**：模型给值 + `reason` 逐字「图片未给出该字段」⇒ 值丢弃（修前亲见这个自相矛盾组合；`_SELF_DENY_RE` 只认明确缺席表述，`图上第二行` 这类正常依据不受影响）。', '**判据 5（空格理由不自相矛盾）**：这两格的 `reason` 不得是「图片未给出该字段」，而是指向米宝解读。', '**判据 6（真跑复验，读数）**：修后同图同模型 ⇒ `name` = 「常青藤系列 全遮光雪尼尔提花窗帘 卧室客厅定制」（`[米宝解读]`）、`description` = 生成的 HTML 文案（`[米宝解读]`）、`color` 仍 `[图片识别]`（16 个色号未截断）、`price` 值空仅有建议。', '**不变式（未被本单放松）**：`price` / `door_width` 值永不落地（涉钱面）；识别已给值的格不被解读覆盖；零命中仍降级不推理。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 pytest（backend/ai-agent-service/tests/test_vision/test_copy_vs_infer.py 等）验证，非 LLM 行为，不进入 agent-eval 冒烟 —— 「哪一格允许由生成类字段填值」是**逐键白名单**，能逐值钉住；真实 LLM 的那一次真跑按 #4262 由用户显式要求、不自动派发',
    tags=['image-recognize', 'source-marker', 'backend-contract', 'regression'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-127 [NORMAL] 🔴 真库+定点：省料看板与趋势的「相邻两期对比」（环比）—— 期间不回填、verdict 由服务端定、占比恒不给好坏（issue #6430）（源: cases/product.yml）──
_CASE_PR_127 = EvalCase(
    id='PR-127',
    legacy_id='',
    title='🔴 真库+定点：省料看板与趋势的「相邻两期对比」（环比）—— 期间不回填、verdict 由服务端定、占比恒不给好坏（issue #6430）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-06 逐字「省料看板看不明白这里是什么意思」「把这个省料的故事讲清楚明白」—— 重设计要求把「在变好还是变坏」讲清楚，环比口径归服务端'],
    expectations=[],
    data_checks=['判据 1·**期间选择不回填**：`MetricDelta` 的「上一期」= 该指标自己时间轴上**相邻的两个有数据期间**（值非 null 的期间按字典序取最后两个）⇒ 没数据的月份**不生成 0**、也不参与选择（否则「没采购」会被读成「采购下降」，与本模块「无数据不冒充 0」同源）。红证（定点）：把 null 期间当 0 参与 ⇒ `SavingMetricsComparisonTest` 用例红；现取命令（在 `backend/admin-api` 下执行）= `./mvnw -q test -Dtest=SavingMetricsComparisonTest`。', '判据 2·**verdict 四态 + 两种「不表态」可区分**：`better`/`worse`/`same`/`unknown`；`same` 一律 `compareTo` 判等（判别性对照：`1.5` 与 `1.50` ⇒ same，而 `equals` 为 false）；`le0_2Share.verdict` **判得了时恒 `null`**（有意不给好坏，见 #5144）且与 `"unknown"`（判不了）**可区分**（断言 `isNotEqualTo("unknown")`）。', '判据 3·**较好方向唯一定义处**：省料米数/金额 ↑ better、采购米数 ↓ better、米每㎡ ↓ better —— 集中在 `StockBatchConsumptionService` 的 `DIR_UP_BETTER` / `DIR_DOWN_BETTER` / `DIR_NO_VERDICT` 与单点 `verdict(...)`；口径正文在 `SavingMetricViews.MetricDelta` 的 javadoc（**不许写第二份**）。', '判据 4·**真库自洽**：`SavingMetricsBoardRealDbTest` 在真 PG 夹具上断言 `comparison` 的期间/数值与既有分组行**逐值自洽**（本期值 == `points` / 分组腿同期的值），并有反向对照「上期 ≠ 本期」。实测读数（2026-10-06）：`savedMeters 5.6 → 1 / savedAmount 69.96 → 5 / le0_2Share 0.5 → 0 (verdict=null) / purchased 15 (unknown) / metersPerM2 0.4583 → 0.8276 (worse)`。', '判据 6·**本期还没过完 ⇒ 不给方向（`partial`，2026-10-06 页面多模态验收反哺）**：`period` == 当前所在期间（业务时区；月 = `YYYY-MM`、周 = `ISO 周历年` 的 `IYYY-"W"IW`）⇒ `verdict = "partial"`，**只覆盖 better/worse/same**，**不覆盖** `unknown`（判不了更具体）与 `null`（有意不给）。病根 = 拿「才过 6 天的月份」与整月比大小 ⇒ 把「这个月还没进货」读成「买得更克制」（实测读数：上期 13236.5 米 → 本期 220.5 米 → 「变好了」）。定点判据用**注入的当前期间**（与「今天几号」解耦，不会下个月自己变红）；真库判据相应放宽为 `isIn("worse", "partial")`（**仍禁止 better**）。', '判据 6c·**行级序列按期间汇总**：环比原始行是（期间 × 来源组 × 物料）粒度 ⇒ 用前必须按期间相加成一期一行，否则「相邻两期」会取到**同一个月的两行**（实测红证：页面打出「上期 **2026-10**：1.3 米 → 本期 **2026-10**：10.3 米」）。判据 = 定点 `aggregateByPeriod`（同期两行相加、全 null 期间整条不进序列 + 汇总后两期必不相同） + 真库「`previousPeriod != period`」。', '判据 5·**零新增 SQL、只加不改**：对比全部由 `savingBoard` / `savingTrend` **已加载的行**内存聚合（未加查询、未碰 mapper/XML、无迁移）；`Board` / `Trend` 既有 component 的顺序与名字一字未动（只在末尾追加 `comparison`）⇒ 既有消费方（ai-agent 的 `batch_stock_query` 按 key 取值）不受影响。 ｜ 2026-10-07（issue #6459）：同批在 `Board` 末尾**再追加**一个 component `batchTrend`（只含采购腿、由已加载的 `batchGroups` 内存聚合，**零新增 SQL**）；既有 component 的顺序与名字**仍**一字未动 ⇒ 本判据继续成立。'],
    skip_reason='[backend-contract] 读面契约与口径（无 LLM 环节）⇒ 由 Java 定点判据 + 真 PG 判据覆盖，不进入 agent-eval 冒烟',
    tags=['batch-ledger', 'saving-metrics', 'real-db', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-128 [NORMAL] 商品创建服务端幂等（issue #6209）：同一 X-Client-Request-Id 并发 N 次 ⇒ 恰 1 条商品 + client_request_keys 恰 1 行；不同键各建一份（负向对照）（源: cases/product.yml）──
_CASE_PR_128 = EvalCase(
    id='PR-128',
    legacy_id='',
    title='商品创建服务端幂等（issue #6209）：同一 X-Client-Request-Id 并发 N 次 ⇒ 恰 1 条商品 + client_request_keys 恰 1 行；不同键各建一份（负向对照）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['现场证据 acceptance/2026-10-03/batch-writeface-sweep/out/E1-duplicate-submit.json：同 X-Client-Request-Id 串行 1 次 ⇒ 商品 1 条，随后同键并发 5 次 ⇒ 5 个请求全 200 各返回一个新 id、落地商品 6 条、client_request_keys 0 行'],
    expectations=[],
    data_checks=['**判据 1·同键并发 ⇒ 恰 1 条业务对象**（真 PG，N=4 × 3 轮）：`ProductCreateIdempotencyRealDbTest#concurrentSameKeyCreatesExactlyOneProduct` 断言 products 该货号恰 1 行、所有成功结果的 id 同一个、至少 1 个 replayed=true、赢家的 SKU 恰 1 行。改后逐字读数 `[READING #6209 同键并发 r=0/1/2] 请求=4 成功=4 回放=3 不同id=1 商品行=1 幂等键行=1 SKU行=1`。', '**判据 2·幂等留痕**：`client_request_keys` 该 (tenant_id, client_request_id) 恰 1 行（endpoint = ProductService.ENDPOINT_CREATE_PRODUCT）。改前现场读数是 **0 行**（写面从未接幂等）。', '**判据 3·负向对照（防「一律只建一条」的假修）**：`ProductCreateIdempotencyRealDbTest#concurrentDistinctKeysEachCreateTheirOwnProduct` —— N=4 **不同**键并发 ⇒ 4 条独立商品 + 4 行幂等键，逐字读数 `[READING #6209 不同键并发] 成功=4 不同id=4 商品行=4 幂等键行=4`。', '**判据 4·服务方法三态接线**：`ProductCreateIdempotencyTest`（claim 判非首次 ⇒ replay 且零 insert；首次 ⇒ insert 1 次 + complete；无键 ⇒ 零幂等交互；失败 ⇒ discard 不 complete）。', '**判据 5·端点接线 + 回放标记冒到 HTTP 层**：`ProductCreateIdempotencyEndpointTest`（真 MockMvc，3 条）—— 带 X-Client-Request-Id ⇒ 头值逐字传到 ProductService#createProduct；回放响应 ⇒ `$.data.replayed == true`（服务端标记必须能冒到 HTTP 层）；不带头 ⇒ 传 null 且 `$.data.replayed` **不存在**（`@JsonInclude(NON_NULL)`，老客户端路径逐字不变）。服务级判据看不见这一层（现场读数与「从没接幂等」逐字相同）。', '**判据 6·回放标记与线上时间格式都保住**：ProductResponse 加 `replayed`（回放=true 才出现，与订单/售后同族）；三个 DTO 的 `@JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")` **一字未改**（线上时间格式不变），回放路径用 `LenientOffsetDateTimeDeserializer` 反序列化该展示格式。', "🔴 **红证（并发类修复必填：注入方式 + 修前逐字读数）**：① **修前红（契约点不存在）** `cd backend/admin-api && ./mvnw -o test -Dtest='ProductCreateIdempotencyTest,ProductCreateIdempotencyEndpointTest,ProductCreateIdempotencyRealDbTest'` ⇒ `COMPILATION ERROR … 找不到符号 变量 ENDPOINT_CREATE_PRODUCT` / `无法将类 ProductService 中的方法 createProduct 应用到给定类型`；② **注入式红证（接上后把去重闸摘掉）** 把 ProductService 的 `if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_CREATE_PRODUCT)) {` 改成 `if (false && …) {` ⇒ `MIGAO_REQUIRE_REALDB=1 ./mvnw -o test -Dtest=ProductCreateIdempotencyRealDbTest` = `Tests run: 2, Failures: 2`，逐字读数 `[READING #6209 同键并发 r=0] 请求=4 成功=4 回放=0 不同id=4 商品行=4 幂等键行=0 SKU行=1`（= 现场 5 并发建 6 条的同族形态）+ `expected: 1L but was: 4L` / `expected: 4L but was: 0L`；撤回注入 ⇒ 复绿。", '**改后绿读数（逐字）**：`Tests run: 10, Failures: 0, Errors: 0, Skipped: 0` + `BUILD SUCCESS`（单元 5 / 端点 3 / 真库并发 2）。', '🔴 **本次如实登记**：口径是**同一 X-Client-Request-Id 并发 N 次**（现场探针形态），本判据逐字取之；「大得多的并发（如 N=20）」与「真实网络下的前端重试」未取证。'],
    skip_reason='[backend-contract] 幂等接线 + 真 PG 并发落库事实（无 LLM 环节）⇒ 由 Java 定点判据与真库并发判据验证，不进入 agent-eval 冒烟',
    tags=['backend-contract', 'idempotency', 'concurrency', 'real-db', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-129 [NORMAL] 商品状态迁移改 DB 原子条件更新（CAS）：并发 on/off_sale 恰一个赢家，落败方 409 + 实际当前态（源: cases/product.yml）──
_CASE_PR_129 = EvalCase(
    id='PR-129',
    legacy_id='',
    title='商品状态迁移改 DB 原子条件更新（CAS）：并发 on/off_sale 恰一个赢家，落败方 409 + 实际当前态',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在商品管理页点「上架」，另一个管理员（或另一个标签页）同一时刻点「下架」——两个请求都回 200，谁后写谁的终态'],
    expectations=[],
    data_checks=['**核验结论 = 真**：修前 `ProductService#updateProductStatus` / `#updateProductForAgent` / `#batchOnShelf` / `#batchOffShelf` 四条状态迁移都是「先 `selectById` 读旧 status 过状态机（`STATUS_TRANSITIONS`）→ `updateById`（WHERE 仅主键 ⇒ **无谓词**）」⇒ 校验在**读**之后、写无谓词：并发 on/off_sale **两个请求都 200**、终态由后写者决定，另一个请求的 200 是谎话。', '**主判据（已落码）**：真库并发（N=2 同刻起跑 × 3 轮，各自独立连接 + 独立事务）on_sale × off_sale ⇒ 成功数 **恰 == 1**、落败方必须 **409 CONFLICT**、终态 == 赢家的目标态，且「谁回 200，终态就必须是它声称的那个态」。断言 = backend/admin-api/src/test/java/com/migao/admin/service/ProductStatusCasRaceRealDbTest.java 的 `concurrentOnAndOffShelfHasExactlyOneWinner`。', '**谓词完整性**：CAS = `WHERE id=? AND tenant_id=? AND deleted=0 AND ((#{fromStatus} IS NULL AND status IS NULL) OR status = #{fromStatus})` —— 谓词逐条自证（列存在性对 `db/init/schema.sql` 的 `products` DDL 核过：`status`/`tenant_id`/`deleted` 三列都在）；`status` 可空 ⇒ 单列一支 `IS NULL`（PG 里 `status = NULL` 永假）。断言 = 同文件判据 1 的落库终态 + ProductStatusCasMetaGuardTest 的谓词判据。', '**正对照（不误杀）**：串行 `off_sale → on_sale → off_sale` 各成功一次；`off_sale → under_review`（不在状态机里）照旧是既有校验错误（非 200 / 非 409）。断言 = 同文件 `serialTransitionsStillSucceed`。', '🔴 **红证（并发类修复必填：注入方式 + 修前逐字读数）**：见同批 PR body「红证」节（探针开 ⇒ 必红；探针关 ⇒ 绿，成对读数；注入 = 把 CAS 退回 `productMapper.updateById(product)`）。', '**改品不得回滚状态（T2b，本单另一半）**：真库并发「`updateProduct`（改名，带窗口探针）× 状态迁移 off_sale → on_sale」⇒ 终态必须仍是 `on_sale`（修前：整实体回写 + `setStatus(originalStatus)` ⇒ 静默写回 `off_sale`），且改名**真的生效**（判据不是「什么都没发生」）。断言 = 同文件 `updateProductDoesNotRollBackConcurrentStatusMigration`。', '**边界（如实登记）**：① 跑的是服务层真库并发而非 HTTP 栈（`PUT /api/admin/products/{id}/status` 与 agent 端点只是薄转发）；② 探针对象全部自建（tenant 6961 / 商品 id 前缀 `p-6961-`），随一次性临时集群销毁，不碰存量数据；③ 判据 1 只用 `updateProductStatus` 一条入口代表四条（四条都走同一个 `applyStatusTransition` → 同一条 CAS；另外三条的**登记**由 MC-115 逐条钉住）；④ `batchOnShelf`/`batchOffShelf` 的落败文案走 `BatchOperationResult.failed`（分部分成功语义）而不是 409，本判据未逐条断言它的影响行数分支。'],
    skip_reason='[backend-contract] 真 PG 并发落库判据（initdb+pg_ctl 临时集群 + 真 ProductService 装配）：CAS 的行锁 / 条件重估与「改了哪几列」在 mock 面结构上不可见，无 LLM 环节 ⇒ 不进 agent-eval 冒烟。',
    tags=['backend-contract', 'concurrency', 'real-db', 'red-proof', 'product-status'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MC-115 [EDGE] 类级元守卫（#6961）：商品状态迁移写路径必须落到 SQL 谓词（CAS）+ 未登记即红 + 豁免只许缩短（源: cases/product.yml）──
_CASE_MC_115 = EvalCase(
    id='MC-115',
    legacy_id='',
    title='类级元守卫（#6961）：商品状态迁移写路径必须落到 SQL 谓词（CAS）+ 未登记即红 + 豁免只许缩短',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.EDGE,
    user_inputs=['（元守卫，无用户轮次）下一个人在商品族新加一条状态迁移写路径，或把 CAS 退回无谓词 `updateById` / 把改品退回整实体回写'],
    expectations=[],
    data_checks=['**为什么是类级**（铁律 8）：只修一个入口 = 没修 —— 下一个人在同族文件新加一条状态迁移写路径、或把 CAS 退回 `updateById`，不会有任何东西变红。守卫把「mapper 状态写谓词完整性 + service 状态写路径登记 + 改品不写状态列的否定锚」钉成机械判据。断言 = backend/admin-api/src/test/java/com/migao/admin/service/ProductStatusCasMetaGuardTest.java。', '**判据 1（扫描器非空跑自证）**：现取「写 `products.status` 的 mapper 手写 SQL」必须含 `updateStatusIfFrom`；现取「service 里出现状态写锚的方法」必须含 `updateProductStatus` / `updateProductForAgent` / `batchOnShelf` / `batchOffShelf` / `updateProduct` / `applyStatusTransition`（少一个核心对象 = 判据失明要当场暴露，不是静默通过）。', '**判据 2（谓词完整性）**：凡 SET 侧写 `status` 的手写 `@Update` SQL，必须同时含 `tenant_id` 参数 + WHERE 侧 status 谓词 + `deleted = 0` —— 少任何一条 ⇒ 红。', '**判据 3（无谓词写即红 + T2b 否定锚）**：现取的每个状态写路径方法体里**不得**出现 `productMapper.updateById(`；改品宿主 `updateProduct` 必须逐字含 `product.setStatus(null)`（退回 `setStatus(originalStatus)` 的整实体回写 ⇒ 红）。', '**判据 4（未登记即红 + 登记必须兑现 + 豁免只许缩短 + 不许空转）**：现取写路径与台账 backend/admin-api/src/test/resources/product-status-cas-ledger.json 的 `service_write_paths` **双向对账**（未登记 ⇒ 红 / 幽灵条目 ⇒ 红）；每条 `evidence` = `<仓库相对全路径>::<可检索文本>` 必须逐字兑现；`entries` 不许为空；`unverified` ≤ `unverified_baseline`（**0**，条数现取打印）。', '**判据 5（判别力自证）**：合成语料上七种坏形态各自判红 —— ① 无谓词状态写；② 缺 `deleted = 0`；③ 缺 tenant 谓词；④ **去谓词定向注入**（缺 WHERE 侧 status 谓词）；⑤ 未登记的新写路径；⑥ **去行数判定定向注入**（锚串留着 `if (false && …updateStatusIfFrom(…)`，真正落库换成无谓词 `updateById`）；⑦ 台账未兑现（CAS 调用被摘掉）；合规语料（与真源码同形）判绿；只改注释不红。另带两条**扫描器鲁棒性**自证（跨行签名必须仍被扫到 + 注释里的孤立 `{` 不得让花括号深度错位）。', '**边界（如实登记）**：见台账 `coverage_boundary` —— 形态判据不做 AST（换措辞可绕过，真实防线仍是 PR-129 的实例判据）；射程只到 `ProductMapper` + `ProductService` 两条文件；判不了「拿 `updateById` / wrapper 改**非状态**列」；不跑被它引用的真库判据；不改任何门禁的通过条件、不新增豁免；**与 MC-100 / PG-075 / MC-102 / MC-104 / #6220 的售后守卫有意不重叠**（各自守自己那张表，一字未动它们）。'],
    skip_reason='[backend-contract] 类级形态守卫（读源码文本、零 DB 零网络）⇒ 不进 agent-eval 冒烟：由 admin-api 单测 ProductStatusCasMetaGuardTest 执行。',
    tags=['backend_contract', 'meta_guard', 'concurrency', 'product-status', 'static-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PG-084 [EDGE] 🔴 真库并发（#6961）：商品状态迁移 = CAS（恰一个赢家 + 落败 409）+ 改品不得静默回滚并发状态迁移（源: cases/product.yml）──
_CASE_PG_084 = EvalCase(
    id='PG-084',
    legacy_id='',
    title='🔴 真库并发（#6961）：商品状态迁移 = CAS（恰一个赢家 + 落败 409）+ 改品不得静默回滚并发状态迁移',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.EDGE,
    user_inputs=['两个管理员同时对同一件商品操作：一个点「上架」、一个点「下架」（或一个在改商品名、另一个在上下架）'],
    expectations=[],
    data_checks=['**核验结论 = 真（两条主张都在当前代码上成立）**：① 四条状态迁移入口（`updateProductStatus` / `updateProductForAgent` / `batchOnShelf` / `batchOffShelf`）是「读旧 status 过状态机 → `updateById`（WHERE 仅主键）」⇒ 并发 on/off_sale **两个请求都 200**、终态由后写者决定；② `updateProduct` 是整实体回写 + `setStatus(originalStatus)` ⇒ 改品会把读到的旧 status 写回，**静默回滚**并发的状态迁移（T2b 的类级根因）。', '**判据 1·恰一个赢家（真库并发 + 窗口探针，3 轮）**：同一件商品并发 `on_sale` × `off_sale`（同刻起跑、各自独立连接 + 独立事务）⇒ 成功数 **恰 == 1**、落败方必须 **409 CONFLICT**、终态 == 赢家的目标态，且「谁回 200，终态就必须是它声称的那个态」。断言 = backend/admin-api/src/test/java/com/migao/admin/service/ProductStatusCasRaceRealDbTest.java 的 `concurrentOnAndOffShelfHasExactlyOneWinner`。', '**判据 2·改品不得回滚状态（T2b）**：真库并发「`updateProduct`（改名）× 状态迁移 off_sale → on_sale」⇒ 终态必须仍是 `on_sale`，且改名**真的生效**（判据不是「什么都没发生」）。修前：迁移 200 + status 落 on_sale，随后改品的整实体回写把它写回 `off_sale` ⇒ 当场红。断言 = 同文件 `updateProductDoesNotRollBackConcurrentStatusMigration`。', '**判据 3·正对照（护栏不误杀）**：串行 `off_sale → on_sale → off_sale` 各成功一次；`off_sale → under_review`（不在状态机里）照旧是既有校验错误（非 200 / 非 409）。断言 = 同文件 `serialTransitionsStillSucceed`。', '**为什么必须真库 + 窗口探针**：CAS 的效力来自只有真 PG 才有的**行锁 + 条件重估**（后到者阻塞到前者提交后按新版本行重估谓词 ⇒ 影响行数 0）；mock 面结构上不可见（mock 恒返回 1）⇒ 修前形态在 mock 面**恒绿**（假绿）。窗口只有微秒级 ⇒ 用 `ProductService#setStatusMigrationProbePauseMillisForTest`（生产恒 0）放大，判据才是确定性的而不是 flake。', '🔴 **红证（探针开 ⇒ 必红 / 探针关 ⇒ 全绿，成对逐字读数见同批 PR body）**：注入 = 把四条写退回无谓词 `updateById` + 把 `updateProduct` 退回整实体回写 + `setStatus(originalStatus)`。', '**边界（如实登记）**：① 服务层真库并发，不覆盖 HTTP 薄转发层；② 探针对象全部自建（tenant 6961 / id 前缀 `p-6961-`），随一次性临时集群销毁，不碰存量数据；③ 判据 1 用 `updateProductStatus` 一条入口代表四条（同一个 `applyStatusTransition` → 同一条 CAS；另外三条的登记由 MC-115 钉住）；④ `batchOnShelf` / `batchOffShelf` 的落败走 `BatchOperationResult.failed`（分部分成功语义）而不是 409，本判据未逐条断言它的影响行数分支（已登记在台账 `coverage_boundary`）。'],
    skip_reason='[backend-contract] 真 PG 并发落库判据（initdb+pg_ctl 临时集群 + 真 ProductService 装配），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['product', 'concurrency', 'real-db', 'backend-contract', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-130 [NORMAL] 报价问法真跑：问「2699 雪尼尔做 3 米宽一幅窗帘多少钱」→ 报商品真价 + 说清加工费口径，不得凭空给总价（源: cases/product.yml）──
_CASE_PR_130 = EvalCase(
    id='PR-130',
    legacy_id='',
    title='报价问法真跑：问「2699 雪尼尔做 3 米宽一幅窗帘多少钱」→ 报商品真价 + 说清加工费口径，不得凭空给总价',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2699系列雪尼尔窗帘面料，2.8 米门幅，做 3 米宽的一幅窗帘，大概多少钱？'],
    expectations=['product_detail or product_search'],
    data_checks=['必须落到**商品真价 23.80 元/米**（夹具 prod_eval_2699 的 base_price；回复里出现 23.8 / 23.80 任一形态）', '必须说清**加工费/用料另有口径**（店铺加工项目录 15 项、按加工费组合计价）—— 不得把布料单价直接当总价，也不得凭空编一个总价数字', '不得出现「免费 / 一共 0 元」这类**未算就给结论**的形态'],
    skip_reason='',
    tags=['product', 'pricing', 'journey'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'product_detail'}],
)

# ── PR-053 [NORMAL] 营销海报 - 商品事实 + 商家确认文案生成海报卡（缺文案 fail-closed；PC 下载 / 手机保存相册）（源: cases/product.yml）──
_CASE_PR_053 = EvalCase(
    id='PR-053',
    legacy_id='',
    title='营销海报 - 商品事实 + 商家确认文案生成海报卡（缺文案 fail-closed；PC 下载 / 手机保存相册）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 0·**机器可判**：缺文案 / 越界时工具必须失败（`must_fail[marketing_poster]`；工具错误码为 `COPY_REQUIRED` / `COPY_INVALID`，属工具结果级、不是轮级 SSE 错误）；成功时 `success=true` 且 `data.product.name` 逐字等于 admin-api 返回的商品名。', '判据 1·🔴 **文案必须由操作员提供**（issue #7351；用户逐字「不要无脑的直接生成」）：`marketing_poster` 缺 `promo_title` / 缺 `selling_points` / 卖点 >3 条 ⇒ `success=False`（`COPY_REQUIRED` / `COPY_INVALID`），且**零 admin-api 调用**、`_should_send_card` 为 False（前端不会画「空头海报」）。注入红证：允许空标题发卡 ⇒ 变红。', '判据 2·**商品事实只来自 admin-api**：主图 / 名称 / 价格（缺 price 回退 basePrice）/ 单位 / 规格逐字段来自 `GET /api/admin/products/{id}`；商品描述里的营销词**不得**被搬进 `copy`。注入红证：把 description 拼进卖点 ⇒ 变红。', '判据 3·**租户隔离 + 权限码**：响应 tenantId ≠ 会话租户 ⇒ 按「商品不存在」拒绝；无 `product:list` 的 C 端上下文 ⇒ 权限拒绝（`c_end_reachable=False`）。注入红证：删掉 tenant 校验 ⇒ 变红。', "判据 4·**卡型跨端契约**：`_detect_card_type('marketing_poster')` → `marketing_poster`；该工具只绑黄金策 product/general ⇒ B 端桌面 `ToolResultCard` 与 B 端移动 `MessageBubble` 都必须有渲染分支（`test_card_type_cross_end_contract.py` 现算，缺一端即红）。", '判据 5·**PC 下载**：`MarketingPosterCard` 点「下载海报」触发带 `download="营销海报-<商品名>.png"` 与 `data:image/png` href 的锚点；版面纯函数固定 750×1000、标题 ≤2 行、卖点 ≤3 行、缺价显示「价格面议」（不伪装 ¥0.00）。注入红证：把 download 改成新窗口打开 ⇒ 变红。', '判据 6·**手机保存到相册**：`PosterCard` 在微信内置浏览器弹「长按图片保存」提示（JS 无法直接写相册，不谎报已保存）；其它浏览器触发 `<a download>` + toast；商品图跨域失败 ⇒ 降级为无图海报并明说。注入红证：微信分支改成 toast「已保存」⇒ 变红。', '判据 7·**快捷入口**：`GET /api/chat/quick-actions` 的 `actions` 仍恰好 6 条（2×3 契约不变），新增 `tools` 字段含「营销海报」；两端按工具行独立渲染并发送服务端 prompt（前端不写死入口内容）。注入红证：把海报塞进 actions 变第 7 格 ⇒ 六格判据红。'],
    skip_reason='[backend-contract] 工具 + 两端渲染契约（无 LLM 环节）：断言由 backend/ai-agent-service/tests/test_marketing_poster.py、test_chat.py::TestQuickActions、test_card_type_cross_end_contract.py 与两端前端单测执行',
    tags=['product', 'poster', 'marketing', 'tool', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_fail=[{'tool': 'marketing_poster'}],
)

# ── PR-054 [NORMAL] 营销海报旅程 - 先问商家要文案，拿到「开门红 + 卖点」后才调海报工具（不得自行编文案）（源: cases/product.yml）──
_CASE_PR_054 = EvalCase(
    id='PR-054',
    legacy_id='',
    title='营销海报旅程 - 先问商家要文案，拿到「开门红 + 卖点」后才调海报工具（不得自行编文案）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['帮我给「2699系列雪尼尔窗帘面料」做一张营销海报', '主标题写「开门红」，卖点写「高遮光、免烫易打理」'],
    expectations=['product_search', 'marketing_poster(promo_title=开门红)'],
    data_checks=['第一轮：**不得直接生成海报**（商家还没给文案）—— 必须先问「主标题 + 2~3 条卖点」，不得用商品描述自动拼卖点、不得编造折扣/赠品/材质。', '第二轮：商家逐字给出「开门红」+「高遮光」「免烫易打理」后才调用 `marketing_poster`；工具入参 `promo_title` 必须逐字等于「开门红」（模型自己换词 = 红）。', '回复出现营销海报卡（商品主图 + 名称 + 价格 + 单位 + 文案），并提示商家可在 PC 下载 / 手机长按保存到相册。'],
    skip_reason='',
    tags=['product', 'poster', 'journey', 'marketing'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition=[{'type': 'product_count_for_keyword', 'source': '2699'}],
)

# ── PR-073 [NORMAL] 营销海报 - 商家让 AI 写文案：先按营销三板斧给 2~3 组候选，确认前不得调海报工具（源: cases/product.yml）──
_CASE_PR_073 = EvalCase(
    id='PR-073',
    legacy_id='',
    title='营销海报 - 商家让 AI 写文案：先按营销三板斧给 2~3 组候选，确认前不得调海报工具',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我要给 2699 系列雪尼尔窗帘面料做张海报，文案你帮我写吧，随便写'],
    expectations=[],
    data_checks=['`marketing_poster` 在本轮**未被调用**（计分锚点；真实机器判据 = forbidden_tools，调用即违规）。', '必须给出 2~3 组**候选文案**（每组含主标题 + 2~3 条卖点），并明确请商家选一组或改写；候选必须基于商品事实（名称 / 规格 / 价格）。', '**不得**在商家确认前调用 `marketing_poster`（机器断言 = forbidden_tools，调用即违规）；不得把候选当最终结果直接发卡。', '候选不得编造折扣 / 赠品 / 材质 / 销量 / 「第一 / 最好 / 100%」等无依据表述；活动价、库存等不知道的事实先问商家。'],
    skip_reason='',
    tags=['product', 'poster', 'journey', 'marketing', 'fail_closed'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'marketing_poster'}],
    precondition=[{'type': 'product_count_for_keyword', 'source': '2699'}],
)

# ── PR-074 [NORMAL] 商品图生成 - 对已选商品生成商品图（先定位再生成；成功发卡：PC 下载 / 手机保存相册；缺主图/不可用都可行动拒绝）（源: cases/product.yml）──
_CASE_PR_074 = EvalCase(
    id='PR-074',
    legacy_id='',
    title='商品图生成 - 对已选商品生成商品图（先定位再生成；成功发卡：PC 下载 / 手机保存相册；缺主图/不可用都可行动拒绝）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['搜索遮光窗帘，然后给第一个商品生成一张主图'],
    expectations=['product_search', 'product_image_generate(kind=main)'],
    data_checks=['判据 0·**机器可判**：缺 `product_id` / `kind` 不在白名单 / 商品没有可用主图 ⇒ `success=False`（`missing_params` 或工具错误码 `IMAGE_SOURCE_MISSING`）；成功时 `success=true`、`data.image_url` 非空、`data.product.name` 逐字等于 admin-api 返回的商品名（判据源 = `backend/ai-agent-service/tests/test_product_image_generate.py`）。', '判据 1·**入口 = 已选商品**（issue #7541；用户 2026-10-23 裁定）：`product_id` 必填，模型先 `product_search` / `product_detail` 定位；缺参 / `kind` 越界 ⇒ 立刻失败且**零 admin-api 调用、零生图调用**。注入红证：缺参放行到取商品 ⇒ 变红。', '判据 2·**样图只来自该商品主图**：样图取 `GET /api/admin/products/{id}` 的 `mainImage`（缺失回退 `images[0]`）；两者都没有、或不是 http(s) 完整地址 ⇒ `IMAGE_SOURCE_MISSING` + **零生图调用**，不拿别的商品凑、不编造。注入红证：缺主图时改传空串给内核 ⇒ 变红。', '判据 3·**不写表单、不落库**：全程只有一次 `GET /api/admin/products/{id}`，`post` / `put` / `patch` / `delete` 一个都不调；生成图只作为卡载荷回给对话（转存与「用不用」都在商家后台）。注入红证：成功后顺手 PATCH 商品主图 ⇒ 变红。', '判据 4·🔴 **失败语义如实**：`ImageGenerationUnavailable`（含模型不接这类图生图请求）⇒ `IMAGE_GEN_UNAVAILABLE`；`ImageGenerationQuotaExceeded` ⇒ `IMAGE_GEN_QUOTA_EXCEEDED`；其它供应商失败 ⇒ `IMAGE_GEN_FAILED`。三者**互不冒充**，`IMAGE_GEN_UNAVAILABLE` 的用户话术里**不得**出现「额度」。注入红证：把前两者合成一个码 ⇒ 变红。', "判据 5·**卡发射条件**：`_detect_card_type('product_image_generate')` → `generated_image`；`_should_send_card` 只在 `success=true` **且** `data.image_url` 非空时为真（失败 / 空图不发卡，避免前端画空图框）。注入红证：去掉 image_url 判据 ⇒ 变红。", '判据 6·**跨端契约**：该工具只绑黄金策 `product` / `general` ⇒ B 端桌面 `ToolResultCard` 与 B 端移动 `MessageBubble` 都必须有 `generated_image` 渲染分支，C 端（元元）不可达（判据 = `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py` 现算）。注入红证：删掉任一端的分支 ⇒ 变红。', '判据 7·**PC 下载 / 手机保存到相册**：桌面卡点「下载图片」走「取文件再按 `商品图-<商品名>.png` 存盘」，取不到时打开原图并明说可「图片另存为」（不谎报已下载）；移动卡在微信内置浏览器弹「长按图片保存」（JS 无法直接写相册，不谎报已保存）。注入红证：微信分支改成提示「已保存」⇒ 变红。', '判据 8·**行为面：先定位再生成**（2026-10-25 首次成功出图后补，issue #7541 的重启条件）：本轮必须先 `product_search` / `product_detail` 拿到商品，再调 `product_image_generate`；`args.product_id` 来自上一步结果（**值级相等**），不得凭空编 UUID、也不得跳过定位直接生成。', '判据 9·**行为面：成功与不可用都说真话**：生成成功 ⇒ `success=true` 且 `data.image_url` 以 `http(s)` 开头（值级）；生成不可用 ⇒ `error.code` **逐字**为 `IMAGE_GEN_UNAVAILABLE`，**不得**是 `IMAGE_GEN_QUOTA_EXCEEDED`（判据 4 在行为面的镜像）。', '判据 10·**行为面：不谎报落库/保存**：回复文本不得出现「已写入商品档案 / 已保存到相册 / 已上传」——图只在卡里（PC 下载 / 手机长按保存是人工动作）。'],
    skip_reason='',
    tags=['product', 'image_generation', 'tool', 'backend_contract', 'fail_closed', 'behavior'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-132 [NORMAL] 商品档案不再设置库存：表单 / 建品接口 / Excel 导入三面下线，存量按真实单据净额重算（V190）（源: cases/product.yml）──
_CASE_PR_132 = EvalCase(
    id='PR-132',
    legacy_id='',
    title='商品档案不再设置库存：表单 / 建品接口 / Excel 导入三面下线，存量按真实单据净额重算（V190）',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我们现在商品中设置了库存数值，这个要移除了，要根据真实库存数据来'],
    expectations=[],
    data_checks=["判据 1·**商品表单无库存录入口**（改前必红）：SKU 矩阵表头不含「库存」列、每行只有价格一个输入框、批量填写区没有「数量」框；源码（剥注释后）不再出现 `STOCK_UNIT` / `'stock'` / `batchStock` / 「库存（」任何一个。注入红证：把 `<th>库存（米）</th>` 与库存 `NumberInput` 加回去 ⇒ 判据红。判据本体 = frontend/admin-web/tests/unit/components/SkuMatrixStockRemoved.test.tsx（4 条行为 + 1 条静态扫描）；连带 = SkuMatrixNumbers.test.tsx 只剩价格逐键与编辑既有值，ProductForm.test.tsx 的「总库存」断言改成只读说明。", '判据 2·**建品接口忽略库存**（改前必红）：`ProductCreateRequest.stock=500` + `skus[].stock=300` ⇒ 落库 `products.stock=0`、`product_skus.stock=0`，且**不落**「新 SKU 初始库存（基线行）」台账行；`colors × doorWidths` 自动生成的 SKU 同样为 0（改前默认 100）。注入红证：把 `input.getStock()` 透传 / 恢复默认 100 ⇒ ProductCreateStockIgnoredTest 两条各红。', '判据 3·**Excel 导入不再建立库存**（改前必红）：`IMPORT_HEADERS` 不含「库存」（模板与解析同源）；旧文件仍带「库存」列时按未知列忽略 —— 行照常落库、库存 0，且不再因 2.755 被拒。注入红证：把库存加回 `IMPORT_HEADERS` 并恢复精度准入 ⇒ 判据红。判据本体 = ProductBulkImportServiceTest 的 legacyStockColumnIsIgnored / importHeaderFaceIsIsomorphicToExport / templateCanBeImportedBackAsIs。', "判据 4·**存量按真实单据净额重算**（V190，真库执行）：SKU 库存 = `reason IN (inbound, order, aftersales) OR (reason='manual' AND note LIKE '库存盘点：%')` 的台账净额，clamp ≥ 0；手工基线 / 表单改库存 / 手工调整**不计**。6 种形态实测：纯手工 30 ⇒ 0；入库 100 + 订单 -10 ⇒ 90；入库 50 + 手工调整 -20 ⇒ 50；入库 20 + 批次盘点 +5 ⇒ 25；净额 -7 ⇒ 0 且不落 0 变更行；无 SKU 商品 ⇒ 0。有变化的 SKU 各落一条 `manual` 补偿行（before=改前 / after=重算值），第二遍执行 0 行新增（幂等），且所有补偿行 `after_qty == product_skus.stock`。可重放证据 = acceptance/2026-10-24-7597-product-stock-from-documents/verify_v190_migration.py（真起临时 PG + schema.sql）；静态守卫 = tests/unit_ci_workflows/test_migration_immutability.py / test_migration_idempotency.py / test_migration_references_exist_in_schema.py。", '判据 5·**读面仍是只读余额、写面边界不清算**：商品列表 / 详情继续返回 `stock`（= SKU 汇总）且表单「总库存」为只读说明；**保留**改品 stock 分支（批量库存调整 / Agent 调整）作为唯一还在的绝对库存写面，其落账链条与幂等由 ProductStockLedgerRealDbTest 判据 1b/2/3 在真库上钉住（首行 before=0、逐次首尾相接、同值重放不增行）；订单侧库存校验**未改**（库存 0 ⇒ 拒绝下单，这是「只认真实入库」的有意后果）。'],
    skip_reason='[backend-contract] 商品档案口径 + 破坏性数据迁移（前端组件 + Java 单测 + 真库迁移脚本，无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/SkuMatrixStockRemoved.test.tsx、backend/admin-api/src/test/java/com/migao/admin/service/ProductCreateStockIgnoredTest.java、ProductBulkImportServiceTest.java、ProductStockLedgerRealDbTest.java、ProductUpdatePruneScopeRealDbTest.java 与 tests/unit_ci_workflows/test_migration_*.py 执行；V190 的真库执行证据见 acceptance/2026-10-24-7597-product-stock-from-documents/（CI 的迁移判据是静态的，不执行 SQL）',
    tags=['product', 'stock', 'product_contract', 'data_migration'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── PR-133 [SMOKE] 冒烟 · 改价闭环：一句「把 2699系列雪尼尔窗帘面料 的价格改成 25.8 元」→ 改前→改后确认卡 → 点卡后真写（源: cases/product.yml）──
_CASE_PR_133 = EvalCase(
    id='PR-133',
    legacy_id='',
    title='冒烟 · 改价闭环：一句「把 2699系列雪尼尔窗帘面料 的价格改成 25.8 元」→ 改前→改后确认卡 → 点卡后真写',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.SMOKE,
    user_inputs=['把 2699系列雪尼尔窗帘面料 的价格改成 25.8 元', {'repeat_until': {'tool_called': 'product_update', 'max': 3}, 'fallback': '确认'}],
    expectations=['product_update(product_id=2699系列雪尼尔窗帘面料, price=25.8)'],
    data_checks=['改前价必须取自 product_detail 的返回（before_price 必填，漏传即 price_preview_required 拦截：tests/test_price_preview_guard.py）', '先发「改前 → 改后」确认卡，点卡之后才允许改（order_before 机器断言）', '改的是商品级 base_price：23.8 → 25.8，跑完由 post_clean 复位的回读自证（种子真值见 tests/agent_eval/fixtures/mibao_eval_seed.sql 的 prod_eval_2699）'],
    skip_reason='',
    tags=['write', 'price', 'write_path', 'smoke'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    order_before=['interact[confirm] before product_update'],
    required_args=[{'tool': 'product_update', 'fields': ['product_id', 'price', 'before_price']}],
    must_succeed=[{'tool': 'product_update'}],
    post_clean=[{'type': 'product_price_restore', 'product_keyword': '2699系列雪尼尔窗帘面料', 'price': 23.8}],
    namespaces=['product_name:2699系列雪尼尔窗帘面料'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '2699系列雪尼尔窗帘面料', 'expect': 1}],
)

CASES = (
    _CASE_PR_001,
    _CASE_PR_002,
    _CASE_PR_003,
    _CASE_PR_004,
    _CASE_PR_005,
    _CASE_PR_006,
    _CASE_PR_007,
    _CASE_PR_008,
    _CASE_PR_009,
    _CASE_PR_010,
    _CASE_PR_011,
    _CASE_PR_012,
    _CASE_PR_013,
    _CASE_PR_017,
    _CASE_PR_018,
    _CASE_PR_019,
    _CASE_PR_021,
    _CASE_PR_024,
    _CASE_PR_025,
    _CASE_PR_026,
    _CASE_PR_027,
    _CASE_PR_029,
    _CASE_PR_030,
    _CASE_PR_031,
    _CASE_PR_032,
    _CASE_PR_033,
    _CASE_PR_034,
    _CASE_PR_035,
    _CASE_PR_036,
    _CASE_PR_037,
    _CASE_PR_038,
    _CASE_PR_039,
    _CASE_PR_040,
    _CASE_PR_041,
    _CASE_PR_042,
    _CASE_PR_043,
    _CASE_PR_044,
    _CASE_PR_045,
    _CASE_PR_046,
    _CASE_PR_047,
    _CASE_PR_048,
    _CASE_PR_049,
    _CASE_PR_050,
    _CASE_PR_051,
    _CASE_PR_052,
    _CASE_PR_055,
    _CASE_PR_056,
    _CASE_PR_057,
    _CASE_PR_058,
    _CASE_PR_059,
    _CASE_PR_060,
    _CASE_PR_061,
    _CASE_PR_062,
    _CASE_PR_065,
    _CASE_PR_063,
    _CASE_PR_064,
    _CASE_PR_066,
    _CASE_PR_067,
    _CASE_PR_068,
    _CASE_PR_069,
    _CASE_PR_070,
    _CASE_PR_071,
    _CASE_PR_072,
    _CASE_PR_076,
    _CASE_PR_077,
    _CASE_PR_078,
    _CASE_PR_079,
    _CASE_PR_080,
    _CASE_PR_081,
    _CASE_PR_082,
    _CASE_PR_083,
    _CASE_PR_084,
    _CASE_PR_085,
    _CASE_PR_086,
    _CASE_PR_087,
    _CASE_PR_088,
    _CASE_PR_089,
    _CASE_PR_090,
    _CASE_PR_091,
    _CASE_PR_092,
    _CASE_PR_093,
    _CASE_PR_094,
    _CASE_PR_095,
    _CASE_PR_096,
    _CASE_PR_097,
    _CASE_PR_098,
    _CASE_PR_099,
    _CASE_PR_100,
    _CASE_PR_101,
    _CASE_PR_102,
    _CASE_PR_103,
    _CASE_PR_104,
    _CASE_PR_105,
    _CASE_PR_106,
    _CASE_PR_107,
    _CASE_PR_108,
    _CASE_PR_109,
    _CASE_PR_014,
    _CASE_PR_110,
    _CASE_PR_111,
    _CASE_PR_112,
    _CASE_PR_113,
    _CASE_PR_114,
    _CASE_PR_115,
    _CASE_PR_116,
    _CASE_PR_117,
    _CASE_PR_119,
    _CASE_PR_120,
    _CASE_PR_121,
    _CASE_PR_122,
    _CASE_PR_123,
    _CASE_PR_015,
    _CASE_PR_016,
    _CASE_PR_020,
    _CASE_PR_022,
    _CASE_PR_131,
    _CASE_PR_023,
    _CASE_PR_028,
    _CASE_PR_124,
    _CASE_PR_125,
    _CASE_PR_126,
    _CASE_PR_127,
    _CASE_PR_128,
    _CASE_PR_129,
    _CASE_MC_115,
    _CASE_PG_084,
    _CASE_PR_130,
    _CASE_PR_053,
    _CASE_PR_054,
    _CASE_PR_073,
    _CASE_PR_074,
    _CASE_PR_132,
    _CASE_PR_133,
)
