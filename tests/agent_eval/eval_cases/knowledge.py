# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: knowledge（源: cases/knowledge.yml，9 条）

from ._schema import Difficulty, EvalCase, Skill

# ── KN-001 [SMOKE] 元元知识问答 - 面料问题先检索本店知识卡片（query 必填）（源: cases/knowledge.yml）──
_CASE_KN_001 = EvalCase(
    id='KN-001',
    legacy_id='',
    title='元元知识问答 - 面料问题先检索本店知识卡片（query 必填）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.SMOKE,
    user_inputs=['雪尼尔面料会不会起球'],
    expectations=['knowledge_search(query=雪尼尔)'],
    data_checks=['knowledge_search 返回后会话正常结束（无报错）；命中则基于卡片回答并注明「来自本店知识库」，未命中用通用行业建议兜底，不得编造本店事实'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'smoke', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-002 [NORMAL] 元元知识问答 - 清洗保养类问题走知识卡片检索（源: cases/knowledge.yml）──
_CASE_KN_002 = EvalCase(
    id='KN-002',
    legacy_id='',
    title='元元知识问答 - 清洗保养类问题走知识卡片检索',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['窗帘多久洗一次？'],
    expectations=['knowledge_search(query=清洗)', 'success=true'],
    data_checks=['知识卡片命中时回答基于卡片内容并注明来源；未命中时如实告知知识库暂无收录，用通用行业建议谨慎回答'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-003 [SMOKE] 黄金策知识问答 - 本店售后政策先检索知识卡片（B 端接线回归，issue #3059）（源: cases/knowledge.yml）──
_CASE_KN_003 = EvalCase(
    id='KN-003',
    legacy_id='',
    title='黄金策知识问答 - 本店售后政策先检索知识卡片（B 端接线回归，issue #3059）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.SMOKE,
    user_inputs=['我们店的退换货政策是什么？'],
    expectations=['knowledge_search(query=退换货)'],
    data_checks=['黄金策知识问答走知识卡片检索（B 端 skill 接线不可回退）；命中基于卡片回答，未命中通用兜底不编造本店事实'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'smoke', 'mibao'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-006 [NORMAL] 文档提炼 - 有效售后文本必须产出候选进待确认队列（P1-1 回归，issue #3063）（源: cases/knowledge.yml）──
_CASE_KN_006 = EvalCase(
    id='KN-006',
    legacy_id='',
    title='文档提炼 - 有效售后文本必须产出候选进待确认队列（P1-1 回归，issue #3063）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家上传售后政策文本后，系统提炼候选知识卡片进入待确认队列'],
    expectations=['direct_reply'],
    data_checks=['success=true'],
    skip_reason='提炼链路由 admin-api/ai-agent 单测 + 生产验收重放验证；LLM 行为 mock。验收实测：部署前后均 candidates:0（P1-1，issue #3063）——修复后重放必须 candidates>0',
    tags=['knowledge', 'wiki', 'distill'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-007 [NORMAL] 售后政策类问题走知识卡片检索（双端，P1-2 回归，issue #3064）（源: cases/knowledge.yml）──
_CASE_KN_007 = EvalCase(
    id='KN-007',
    legacy_id='',
    title='售后政策类问题走知识卡片检索（双端，P1-2 回归，issue #3064）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['你们退换货政策是怎样的？'],
    expectations=['knowledge_search(query=退换货)'],
    data_checks=['售后政策/质保类咨询为知识问题：双端应调 knowledge_search 命中本店退换货卡片并标注来源，而非通用售后流程话术；操作类（我要退货/申请退款）仍走售后工单（不回归）'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'xiaobu', 'mibao'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-004 [NORMAL] 黄金策知识问答 - 加工计价规则走 processing_item_query 工具（加工项派生卡片已移除）（源: cases/knowledge.yml）──
_CASE_KN_004 = EvalCase(
    id='KN-004',
    legacy_id='',
    title='黄金策知识问答 - 加工计价规则走 processing_item_query 工具（加工项派生卡片已移除）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我们店打孔加工怎么计价？'],
    expectations=['processing_item_query(keyword=打孔)', 'success=true'],
    data_checks=['加工计价规则类问题：knowledge_search 未命中（加工项派生卡片已移除，#3085）→ 用 processing_item_query 查店铺加工项目录（返回计价方式/单价/单位），以工具结果回答计价规则'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'mibao'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-008 [NORMAL] 知识来源标注边界 - 自补常识不得混入「📖 来自本店知识库」标注（P2-4，issue #3076）（源: cases/knowledge.yml）──
_CASE_KN_008 = EvalCase(
    id='KN-008',
    legacy_id='',
    title='知识来源标注边界 - 自补常识不得混入「📖 来自本店知识库」标注（P2-4，issue #3076）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['雪尼尔面料会起球吗'],
    expectations=['knowledge_search(query=雪尼尔)'],
    data_checks=['命中知识卡片时回复含「📖 来自本店知识库」来源标注（不回归）；标注仅覆盖卡片原文，自补常识与标注分离并注明通用参考'],
    skip_reason='',
    tags=['knowledge', 'wiki', 'source-annotation', 'xiaobu'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── KN-009 [NORMAL] C 端知识问答**活栈**冒烟（元元）：多轮上下文 + 复合 Tool 的 SSE 事件 + 异常输入 + 快捷操作菜单（源: cases/knowledge.yml）──
_CASE_KN_009 = EvalCase(
    id='KN-009',
    legacy_id='',
    title='C 端知识问答**活栈**冒烟（元元）：多轮上下文 + 复合 Tool 的 SSE 事件 + 异常输入 + 快捷操作菜单',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['对**已部署**的 C 端客服（元元）跑知识库与高级 AI 对话冒烟：多轮上下文关联 / 复合 Tool 调用的 SSE 事件 / 空消息·超长消息·并发会话 / 快捷操作菜单'],
    expectations=['direct_reply'],
    data_checks=['判据 1·活栈链路（HTTP / SSE 契约）：多轮对话上下文关联、复合 Tool 调用能产出 SSE 事件、快捷操作菜单接口返回非空列表。执行点 = tests/smoke/test_11_knowledge_ai_advanced.py', '判据 2·异常输入不炸链路：空消息 / 超长消息 / 并发会话下返回结构化错误或降级，**不得 5xx 裸崩**。执行点 = 同文件的三组 `Test...SSE...`', '⚠️ 真值缺口（照实登记）：活栈冒烟依赖部署环境与卡片是否已发布 ⇒ `truths_ref: []`（同 KN-001~003 的既有口径，只告警不阻塞）'],
    skip_reason='[backend-contract] **活栈冒烟**（pytest 直连已部署环境，nightly-verification 腿）：判定在 HTTP / SSE 契约与工具链路层 —— 它**不是** agent-eval 的可重放用例（评测栈无法重放活环境），故不进 agent-eval 冒烟',
    tags=['knowledge', 'smoke', 'live-stack'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置 = 目标环境可达（`tests/smoke/config.py` 的 base url + 租户凭据）且该环境 C 端渠道可用；不可达时 pytest fixture 直接报错（不会伪装成「知识问答不会答」）',
)

# ── KN-010 [EDGE] 知识候选并发双采纳各自插卡 ⇒ 产出两张卡；改写为「先抢发布权（CAS）再插卡」后恰一次成功、恰一张卡（issue #6962）（源: cases/knowledge.yml）──
_CASE_KN_010 = EvalCase(
    id='KN-010',
    legacy_id='',
    title='知识候选并发双采纳各自插卡 ⇒ 产出两张卡；改写为「先抢发布权（CAS）再插卡」后恰一次成功、恰一张卡（issue #6962）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.EDGE,
    user_inputs=['同一条待确认候选被严格同时采纳两次（并发 adopt）', '同一条待确认候选被并发「采纳 × 拒绝」各一次'],
    expectations=[],
    data_checks=["**病（真实缺陷形态）**：修前 `KnowledgeCandidateService#adoptInternal` / `#reject` 都是「`getOwned` 读出 `status='pending'` → 应用层判 → 整实体 `knowledgeCandidateMapper.updateById(candidate)`（WHERE 仅主键 ⇒ **无谓词**）」，且采纳路径是**先 `knowledgeCardMapper.insert(card)` 再置态** ⇒ 并发双采纳**各插一张卡**（实测 2 张）；「采纳 × 拒绝」并发则两个都过读判、都成功，终态由后写者决定。", '**判据 1（恰一次成功、恰一张卡）**：backend/admin-api/src/test/java/com/migao/admin/service/ConcurrentQuotaAdoptDeleteCas6962RealDbTest.java：并发双 `adopt` ⇒ 成功数 **恰 == 1**、落败方 **409**，且 `SELECT COUNT(*) FROM knowledge_cards WHERE tenant_id=? AND source_ref=<候选 id>` **恰 == 1**（修前为 2 ⇒ 判红）；候选终态 = `adopted`。', "**判据 2（同族 `reject` 同口径）**：`reject` 与 `adopt` 走**同一条**条件更新 `KnowledgeCandidateMapper#markReviewedIfPending`（谓词 `id + tenant_id + status='pending'`）⇒ 并发「采纳 × 拒绝」只有一方赢；`status_note` 只在 `note != null` 时写（采纳路径不动拒绝原因）。", '**判据 3（写序不可反转）**：类级元守卫 backend/admin-api/src/test/java/com/migao/admin/service/ConcurrencyCasBatch6962MetaGuardTest.java 断言 `adoptInternal` 里 `knowledgeCardMapper.insert(` **出现在** `markReviewedIfPending(` 及其 `== 0` 冲突检查**之后** —— 把插卡挪回 CAS 之前 ⇒ 判红（那正是「两张卡」的成因）。', '**列存在性自证（本批两例踩坑的正面登记）**：谓词里的列**逐个对 `db/init/schema.sql` 现取核对** —— `knowledge_candidates` **没有** `deleted` 列（本表谓词**不得**写 `deleted = 0`，写了就是列不存在 ⇒ SQL 报错）；而 `agent_sessions` / `agent_employees` / `production_route_templates` / `production_route_rules` **有** `deleted` 列。', '**边界（照实登记）**：判据跑服务层真库并发而非 HTTP 栈；候选与卡片的归属键用 `source_ref`（采纳时逐字继承候选的 `source_ref`），不新增审计列。'],
    skip_reason='[backend-contract] 纯后端真库并发判据（真 PG 一次性集群，走 `PgCluster.startOrAbort()` 收口）+ 类级元守卫：admin-api 单测面，不进 agent-eval 冒烟',
    tags=['concurrency', 'cas', 'idempotency', 'backend-contract', 'realdb'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="前置 = 一条 `status='pending'` 的知识提炼候选（`knowledge_candidates` 无 `deleted` 列，软删语义由 `status` 承担）。前置由判据自建（一次性真 PG 集群 + 自建 tenant / 候选行），**不成立时 fail-closed 硬失败**，不会伪装成「agent 不干活」。",
)

CASES = (
    _CASE_KN_001,
    _CASE_KN_002,
    _CASE_KN_003,
    _CASE_KN_006,
    _CASE_KN_007,
    _CASE_KN_004,
    _CASE_KN_008,
    _CASE_KN_009,
    _CASE_KN_010,
)
