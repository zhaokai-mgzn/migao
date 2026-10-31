# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: ontology（源: cases/ontology.yml，4 条）

from ._schema import Difficulty, EvalCase, Skill

# ── ON-001 [NORMAL] 本体 schema 加载与状态枚举校验（核心四对象 + 扩展三对象）（源: cases/ontology.yml）──
_CASE_ON_001 = EvalCase(
    id='ON-001',
    legacy_id='',
    title='本体 schema 加载与状态枚举校验（核心四对象 + 扩展三对象）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['加载默认本体 schema，校验七对象（订单/商品SKU/售后单/客户 + 员工/加工项/分类）定义、状态枚举、关系目标与 source 挂载点（issue #5245）'],
    expectations=['direct_reply'],
    data_checks=['默认 schema.yaml 存在且可加载，返回 Ontology 七对象：order/product_sku/aftersales/customer + employee/processing_item/category（knowledge_document 已随旧 RAG 知识库退场，issue #3051）', '每个对象具备属性/关系/规则三要素（动作段已出库，issue #8172）——能力/确认闸/白名单的真值只认 tools registry；schema.yaml 再出现动作键 ⇒ backend/ai-agent-service/tests/test_ontology_schema.py::TestActionsSectionStaysOut 判红（含注入式红证 + 「只改注释不红」的对照读数）', '订单状态枚举 == [pending, confirmed, producing, shipped, completed, cancelled]（与 CONTRACT-LEDGER 的 OrderService.java 状态机一致，生产中是 producing 非 processing）', '售后工单状态枚举 == [pending, processing, rejected, resolved, closed]；商品状态枚举 == [draft, on_sale, off_sale, under_review]（载体是商品级 Product.status，SKU 表无状态列）', '扩展对象状态枚举与代码真值一致：员工 == [online, offline, busy]（AgentEmployeeService 错误消息）、加工项/分类 == [active, inactive]（DTO 注释）', '词表 STATUS_LEXICON 与 schema 的 status 枚举键集**双向一致**（无死条目、无漏挂：knowledge_document.status 已随对象删除清出词表）；非法状态值（如 processing 混入订单枚举）加载校验必须拒绝并给出明确错误', '关系目标 fail-closed（issue #5245 B6）：relations[].target 必须 ∈ objects ∪ external_targets（order_item/product/processing_category/agent_session/tenant 显式登记为外部概念）；未登记目标 ⇒ 加载拒绝', 'source 挂载点与真实载体一致（issue #5245 B1~B3，逐个 Java 实体/迁移取证）：product_sku.status → Product.status、product_sku 无 attributes、aftersales.ticket_type → AfterSalesTicket.ticketType、customer 的 wechat_nickname/wechat_openid/default_receiver_address → CustomerProfile 同名列'],
    skip_reason='[backend-contract] 本体模块为纯数据结构契约，由 pytest 单测验证（backend/ai-agent-service/tests/test_ontology_schema.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ontology', 'schema', 'enum_alignment'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ON-002 [NORMAL] vision 分析候选实体写入上下文实体槽（G10 修复）（源: cases/ontology.yml）──
_CASE_ON_002 = EvalCase(
    id='ON-002',
    legacy_id='',
    title='vision 分析候选实体写入上下文实体槽（G10 修复）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户发图，vision 分析识别出候选商品/订单/客户 → 候选实体写入 context_manager 实体槽 → 后续轮次 build_context 注入'],
    expectations=['direct_reply'],
    data_checks=['record_vision_candidates 写入后 get_entities 返回包含 source=vision 的候选实体', 'build_context 注入的上下文包含 vision 候选实体（图片关联对象有召回保障）', '重复写入同一候选去重；非法 entity_type 拒绝', '实体槽与 _extract_entities 的工具结果提取共存（vision 与工具结果互不覆盖）'],
    skip_reason='[backend-contract] 上下文记忆为纯数据结构契约，由 pytest 单测验证（backend/ai-agent-service/tests/test_ontology_vision_grounding.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ontology', 'vision', 'context_memory', 'grounding'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ON-003 [NORMAL] intent 归属表全量登记 + 双端能力视图契约校验（v2 按 agent 核对）（源: cases/ontology.yml）──
_CASE_ON_003 = EvalCase(
    id='ON-003',
    legacy_id='',
    title='intent 归属表全量登记 + 双端能力视图契约校验（v2 按 agent 核对）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['schema 全量登记 30 个业务 intent（双端 22 + 仅 mibao 5（finance + 加工单域 3 + 定时提醒 1）+ 仅 xiaobu 2（knowledge_manage/quote）——knowledge_faq 已双端可达，issue #3059）；契约校验与双端真实映射按 agent 分别对比，活映射侧另有一条端到端判据'],
    expectations=['direct_reply'],
    data_checks=['schema.intent_ownership 全量登记 30 个业务 intent（排除 general 兜底；mibao 已启用 knowledge_faq 知识卡片检索，issue #3059；knowledge_manage 管理意图不可达 agent——管理走 admin-web；定时提醒 scheduled_task_manage 仅 mibao（issue #6486 包 2 引入、#6514 补登记 schema））', '契约校验 v2：schema 声明某 agent 可达的 intent 必须在该 agent 映射中存在（防假声明）；mibao route_key 严格一致（B 端是约定事实源，xiaobu 兜底覆盖不计漂移）；任一 agent 映射有但 schema 未登记 → 违规；声明可达的 route_key 必须在该 agent 真实可达集合中', 'xiaobu 专属 intent（quote/knowledge_manage）在 mibao 映射缺失是正常的，不得误报（knowledge_faq 现为双端可达）', '缺失/漂移返回违规清单（不抛异常，由调用方决定阻断）', '**活映射侧**（issue #6514）：backend/ai-agent-service/tests/test_ontology_contract.py 的 TestLiveRegistryMatchesSchema::test_live_registry_matches_schema_no_violations 直接跑 scripts/check_ontology_contract.py（= contract-check.sh 第 6 项同一入口）并断言 exit 0 —— 在装了全依赖的 job（ai-agent-tests.yml 的 ai-agent-service unit tests）里执行且**无 skip 分支**；测试文件里的夹具快照漂移不构成「有人守着」'],
    skip_reason='[backend-contract] 契约校验为纯数据结构逻辑，由 pytest 单测验证（backend/ai-agent-service/tests/test_ontology_contract.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ontology', 'intent_ownership', 'contract', 'dual_agent'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ON-004 [NORMAL] vision 分析文本落上下文槽 + base_skill 接线（行为闭环收口）（源: cases/ontology.yml）──
_CASE_ON_004 = EvalCase(
    id='ON-004',
    legacy_id='',
    title='vision 分析文本落上下文槽 + base_skill 接线（行为闭环收口）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['vision 分析完成后，分析文本写入 context_manager 上下文槽（record_vision_analysis）→ build_context 跨 skill 注入，澄清候选 grounded 有召回保障；base_skill 接线调用'],
    expectations=['direct_reply'],
    data_checks=['record_vision_analysis 写入后 build_context 注入包含 vision 分析文本（截断 800 字符）', '重复写入覆盖旧文本（最新图片分析优先）；空文本/无 session 不落槽', 'base_skill vision 分支分析成功后调用 record_vision_analysis（与 set_vision_analysis 并列，异常降级不破坏主流程）'],
    skip_reason='[backend-contract] 上下文记忆为纯数据结构契约，由 pytest 单测验证（backend/ai-agent-service/tests/test_ontology_vision_grounding.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ontology', 'vision', 'context_memory', 'grounding', 'base_skill'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_ON_001,
    _CASE_ON_002,
    _CASE_ON_003,
    _CASE_ON_004,
)
