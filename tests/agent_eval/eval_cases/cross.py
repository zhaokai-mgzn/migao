# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: cross（源: cases/cross.yml，3 条）

from ._schema import Difficulty, EvalCase, Skill

# ── CR-001 [NORMAL] 查商品 → 下单（跨 Skill 复用 UUID）（源: cases/cross.yml）──
_CASE_CR_001 = EvalCase(
    id='CR-001',
    legacy_id='C001',
    title='查商品 → 下单（跨 Skill 复用 UUID）',
    skill=Skill.CROSS,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查一下遮光窗帘', '用遮光窗帘给张三创建订单，2件，手机13800138000', {'auto_select': True}, '不需要加工项', '确认下单', {'auto_respond': {'fallback': '确认下单'}}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['product_detail'],
    data_checks=['order_create items 包含遮光窗帘的 UUID（复用上轮，不重查）', 'Context 注入包含 product_ids'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「下单（跨 Skill 复用 UUID）」（order_create）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为「查商品详情（product_detail）+ 如实说明黄金策不做下单、引导去后台订单页面」。',
    tags=['cross_skill', 'context_share'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'order_create'}],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    namespaces=['customer_phone:13800138000', 'product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── CR-002 [ADVERSARIAL] 对抗性 - 3 个 Skill 连续切换（源: cases/cross.yml）──
_CASE_CR_002 = EvalCase(
    id='CR-002',
    legacy_id='C003',
    title='对抗性 - 3 个 Skill 连续切换',
    skill=Skill.CROSS,
    difficulty=Difficulty.ADVERSARIAL,
    user_inputs=['搜遮光窗帘', '查张三这个客户', '给张三下个遮光窗帘的订单'],
    expectations=['product_search', 'customer_manage(action=list)'],
    data_checks=['order_create 复用前两轮的 product_id 和 customer_id', 'success=true'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「给张三下单（3 个 Skill 连续切换的末段写面）」（order_create）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为「搜商品 + 查客户（product_search / customer_manage action=list）+ 如实说明黄金策不做下单、引导去后台订单页面」。',
    tags=['cross_skill', 'multi_round', 'adversarial'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'order_create'}],
    namespaces=['product_name:遮光窗帘', 'customer_phone:13800138000'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
)

# ── CR-003 [NORMAL] 真实场景全旅程 - 咨询→查商品→下单→查物流（源: cases/cross.yml）──
_CASE_CR_003 = EvalCase(
    id='CR-003',
    legacy_id='M007',
    title='真实场景全旅程 - 咨询→查商品→下单→查物流',
    skill=Skill.CROSS,
    difficulty=Difficulty.NORMAL,
    user_inputs=['你好，我想买窗帘', '有什么遮光好的推荐吗', '看看遮光窗帘的详情', '就这个，帮我下单，客户张三 13800138000，2件', '米白，散剪，2.8米门幅', '不需要加工项', {'auto_respond': {'fallback': '确认下单', 'form_values': {'customer_name': '张三', 'customer_phone': '13800138000', 'customer_address': '浙江省杭州市西湖区文三路 1 号 1 幢 101 室'}}}, {'auto_respond': {'fallback': '确认', 'form_values': {'customer_name': '张三', 'customer_phone': '13800138000', 'customer_address': '浙江省杭州市西湖区文三路 1 号 1 幢 101 室'}}}, {'auto_respond': {'fallback': '确认'}}, '订单怎么样了，发货了吗', '好的谢谢'],
    expectations=['product_search', 'product_detail', 'order_query'],
    data_checks=['第4步 product_id 来自第2-3步上下文', '订单创建成功并包含 SKU 信息', '第7步自动找到刚创建的订单'],
    skip_reason='[backend-contract] [#5247] B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「全旅程下单」（order_create）已从 B 端下线、不再绑定任何 B 端 skill。用例条目与退役理由保留（不删除）；断言面改判为「咨询 + 搜商品 + 查商品详情 + 查订单/物流（product_search / product_detail / order_query）+ 如实说明黄金策不做下单、引导去后台订单页面」。',
    tags=['multi_turn', 'real_scenario', 'cross_skill', 'full_journey'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_tools=[{'tool': 'order_create'}],
    want_text=['订单'],
    pre_clean=[{'type': 'product_dedupe', 'product_keyword': '遮光窗帘'}],
    namespaces=['customer_phone:13800138000', 'product_name:遮光窗帘'],
    precondition=[{'type': 'product_count_for_keyword', 'source': '遮光窗帘', 'expect': 1}],
    auto_fill={'customer_name': '张三', 'customer_phone': '13800138000', 'customer_address': '浙江省杭州市西湖区文三路 1 号 1 幢 101 室'},
)

CASES = (
    _CASE_CR_001,
    _CASE_CR_002,
    _CASE_CR_003,
)
