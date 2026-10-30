# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: api（源: cases/api.yml，21 条）

from ._schema import Difficulty, EvalCase, Skill

# ── API-001 [NORMAL] chat 会话生命周期 - 租户隔离 + 用户所有权 + 幂等/重开（源: cases/api.yml）──
_CASE_API_001 = EvalCase(
    id='API-001',
    legacy_id='',
    title='chat 会话生命周期 - 租户隔离 + 用户所有权 + 幂等/重开',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 处理会话 create/list/close/reopen/delete/history 端点'],
    expectations=['direct_reply'],
    data_checks=['close/reopen/delete/history 对不存在会话返回 404 SESSION_NOT_FOUND', '跨租户或非所有者访问返回 403 PERMISSION_DENIED', 'close 幂等（已 closed 仍 success 且不调 close_session）；reopen 仅 closed→active'],
    skip_reason='[backend-contract] 会话端点由 pytest 单测验证（tests/test_chat.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'session_lifecycle', 'tenant_isolation'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-002 [NORMAL] chat 卡片判定 + 历史转换（think 剥离 / 多模态 metadata）（源: cases/api.yml）──
_CASE_API_002 = EvalCase(
    id='API-002',
    legacy_id='',
    title='chat 卡片判定 + 历史转换（think 剥离 / 多模态 metadata）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 判定工具结果是否发卡片，并转换多模态对话历史'],
    expectations=['direct_reply'],
    data_checks=['_should_send_card 仅 success 且对应字段非空（products/product/tracking_number/order/orders/items）才 True', '_detect_card_type 映射 product_search→product_list 等四类', '_convert_history_to_agent_format 剥离 assistant <think>、透传 content_type、metadata 含 images 时过滤非法 URL'],
    skip_reason='[backend-contract] 纯函数由 pytest 单测验证（tests/test_chat.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'card', 'history', 'multimodal'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-003 [NORMAL] chat __PAGE__ 分页协议 - 白名单直调 + 格式/工具守卫（源: cases/api.yml）──
_CASE_API_003 = EvalCase(
    id='API-003',
    legacy_id='',
    title='chat __PAGE__ 分页协议 - 白名单直调 + 格式/工具守卫',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 处理 __PAGE__|tool|params_json 翻页消息'],
    expectations=['direct_reply'],
    data_checks=['白名单工具（order_query 等）直接执行并返回 tool_call/tool_result', "非白名单工具 → SSE error '不支持该操作的分页查询'", "split/json 解析失败 → SSE error '翻页请求格式错误'"],
    skip_reason='[backend-contract] 分页协议由 pytest 单测验证（tests/test_chat.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'page_protocol', 'guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-004 [NORMAL] chat 图片校验 + 多模态消息构造（源: cases/api.yml）──
_CASE_API_004 = EvalCase(
    id='API-004',
    legacy_id='',
    title='chat 图片校验 + 多模态消息构造',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 校验 send 消息携带的图片 URL 列表'],
    expectations=['direct_reply'],
    data_checks=['>3 张 → SSE error；URL 非 https:// 或 /api/files 开头 → SSE error', 'images 存在时 content_type=mixed 并逐图构造 image_url（_rewrite_image_url CDN→OSS）'],
    skip_reason='[backend-contract] 图片校验由 pytest 单测验证（tests/test_chat.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'image_guard', 'multimodal'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-005 [NORMAL] chat Agent 流→SSE 序列 + 意图/昵称助手（源: cases/api.yml）──
_CASE_API_005 = EvalCase(
    id='API-005',
    legacy_id='',
    title='chat Agent 流→SSE 序列 + 意图/昵称助手',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 将 Agent 流式输出转换为 SSE，并处理用户昵称'],
    expectations=['direct_reply'],
    data_checks=['loading→text/tool_call/tool_result/card/interactive→done 序列；空文本降级兜底文案', "suggestion-feedback 返回 {ok:true}；_infer_intent_from_text 关键词按具体词优先匹配，空/无匹配返回 ''/general", '_get_user_nickname Redis 命中直返、未命中查 DB、异常静默返回 None'],
    skip_reason='[backend-contract] SSE 流/助手函数由 pytest 单测验证（tests/test_chat.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'sse_stream', 'suggestion'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-006 [NORMAL] sse.SSEEvent 帧格式 + SSEStreamBuilder 链式/迭代（源: cases/api.yml）──
_CASE_API_006 = EvalCase(
    id='API-006',
    legacy_id='',
    title='sse.SSEEvent 帧格式 + SSEStreamBuilder 链式/迭代',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 构建 SSE 事件帧'],
    expectations=['direct_reply'],
    data_checks=["10 种事件统一 'event: <type>\\ndata: <json>\\n\\n'，heartbeat 为 ': heartbeat\\n\\n'", 'error 无 code 时 data 仅含 message；interactive payload 含 type + 展开 data', 'SSEStreamBuilder 链式 add_*、build() 拼接、__iter__ 迭代'],
    skip_reason='[backend-contract] SSE 帧格式由 pytest 单测验证（tests/test_sse.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'sse_format'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-007 [NORMAL] internal.execute_tool 守卫 - 只读白名单 + 错误码（源: cases/api.yml）──
_CASE_API_007 = EvalCase(
    id='API-007',
    legacy_id='',
    title='internal.execute_tool 守卫 - 只读白名单 + 错误码',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['admin-api 经 Service Token 调用内部 /tools/execute'],
    expectations=['direct_reply'],
    data_checks=['工具不存在 404 TOOL_NOT_FOUND；非 read_only 工具 403 WRITE_TOOL_FORBIDDEN', '只读工具成功返回 {success,data,error,message}；执行异常 500 INTERNAL_ERROR'],
    skip_reason='[backend-contract] 内部接口守卫由 pytest 单测验证（tests/test_internal.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'internal', 'tool_guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-009 [NORMAL] upload.upload_chat_image 校验 + 嗅探 + 代理转发（源: cases/api.yml）──
_CASE_API_009 = EvalCase(
    id='API-009',
    legacy_id='',
    title='upload.upload_chat_image 校验 + 嗅探 + 代理转发',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 上传聊天图片并代理转发到 admin-api'],
    expectations=['direct_reply'],
    data_checks=['>3 张 400 TOO_MANY_FILES、空文件 400 NO_FILE；MIME/扩展名白名单拒绝；>5MB 400 FILE_TOO_LARGE', 'magic number 嗅探与声明类型不符 400 FILE_CONTENT_MISMATCH', '按 tenant_id 隔离目录 chat/{tenant_id} 转发；HTTPStatusError→502 UPLOAD_PROXY_ERROR、RequestError→502 UPLOAD_SERVICE_UNAVAILABLE'],
    skip_reason='[backend-contract] 上传校验/代理由 pytest 单测验证（tests/test_upload.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'upload', 'file_guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-010 [NORMAL] 微信小程序 mock 登录链路（无 appid 时自动 mock）（源: cases/api.yml）──
_CASE_API_010 = EvalCase(
    id='API-010',
    legacy_id='',
    title='微信小程序 mock 登录链路（无 appid 时自动 mock）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/auth/mini/login 在 wechat.mini.appid 未配置时走 mock 模式', '同 code 二次登录返回同一用户（账号稳定）'],
    expectations=['direct_reply'],
    data_checks=['mock 登录成功返回 accessToken + user', '登录参数 tenantId(camelCase) 与后端一致'],
    skip_reason='[backend-contract] 判据在 `frontend/mini-app/tests/auth.test.ts`（mock 登录返回 accessToken+user / tenantId 口径），**非 LLM 行为**；本用例的 `expectations: direct_reply` 只是占位，agent 面对「接口实现细节」这类问题合法地可能去查设置（基线 run 40895378323：模型调了 settings_manage(get_settings/login_logs) 但给了正确解释 ⇒ 按行为计分是**假红**）⇒ 不进 agent-eval（同 `api.yml` 其余 20 条的契约标记口径）',
    tags=['login', 'mock'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 的**接口契约**用例（不进 agent-eval 冒烟）：前置 = 部署的 `wechat.mini.appid` **未配置** ⇒ `POST /api/auth/mini/login` 走 **mock 模式**（两轮 `user_inputs` 是对**同一个接口**的两条断言，不是两次会话）。该前置由 `frontend/mini-app/tests/auth.test.ts` 在 mock 下直接构造并断言 ⇒ 前置不成立（appid 被配上、mock 分支被摘掉）时单测直接红，不会表现为「agent 不干活」',
)

# ── API-013 [NORMAL] 知识知识卡片数据模型 - knowledge_cards 表/实体/Mapper（LLM WIKI 板块 #3051）（源: cases/api.yml）──
_CASE_API_013 = EvalCase(
    id='API-013',
    legacy_id='',
    title='知识知识卡片数据模型 - knowledge_cards 表/实体/Mapper（LLM WIKI 板块 #3051）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['知识卡片（问题+标准回答+分类+关键词+来源+状态）可持久化存储与检索'],
    expectations=[],
    data_checks=['V35 迁移创建 knowledge_cards：tenant_id/title/category/industry/source_type/source_ref/question/answer/keywords/apply_products/variables/status(draft|pending_review|published|archived)/version/review_note/created_by/reviewed_by/reviewed_at 全字段', 'KnowledgeCard 实体字段与列名一一映射（MyBatis-Plus），Mapper 继承 BaseMapper（租户隔离由拦截器注入）', 'docs/sql/schema.sql 全量 schema 同步包含 knowledge_cards（防文档-代码漂移 P0-3）'],
    skip_reason='[backend-contract] 数据模型由 Mapper/迁移契约测试验证（KnowledgeCardMapperTest/KnowledgeWikiMigrationTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'data-model'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-014 [NORMAL] 提炼候选数据模型 - knowledge_candidates 表/实体/Mapper（LLM WIKI 板块 #3051）（源: cases/api.yml）──
_CASE_API_014 = EvalCase(
    id='API-014',
    legacy_id='',
    title='提炼候选数据模型 - knowledge_candidates 表/实体/Mapper（LLM WIKI 板块 #3051）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AI 提炼的候选知识卡片（建议标题/答案/置信度/依据/状态）可进入待采纳队列'],
    expectations=[],
    data_checks=['V35 迁移创建 knowledge_candidates：tenant_id/source_type(conversation|document|product|config)/source_ref/suggested_title/suggested_answer/suggested_category/suggested_keywords/confidence/evidence/status(pending|adopted|edited|rejected)/status_note/reviewed_by/reviewed_at 全字段', 'KnowledgeCandidate 实体字段与列名一一映射（MyBatis-Plus），Mapper 继承 BaseMapper', 'docs/sql/schema.sql 全量 schema 同步包含 knowledge_candidates（防文档-代码漂移 P0-3）'],
    skip_reason='[backend-contract] 数据模型由 Mapper/迁移契约测试验证（KnowledgeCandidateMapperTest/KnowledgeWikiMigrationTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'data-model'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-015 [NORMAL] 知识知识卡片 CRUD + 状态机 - 创建/编辑/发布/归档/删除（LLM WIKI 板块 #3051）（源: cases/api.yml）──
_CASE_API_015 = EvalCase(
    id='API-015',
    legacy_id='',
    title='知识知识卡片 CRUD + 状态机 - 创建/编辑/发布/归档/删除（LLM WIKI 板块 #3051）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家创建/编辑知识卡片（问题+标准回答+分类+关键词）并发布/归档'],
    expectations=[],
    data_checks=['POST /api/admin/knowledge/entries 创建知识卡片：title/answer 必填（缺则 400 中文 detail），sourceType=manual，version=1，status 缺省 draft（可显式 published）', 'PUT /api/admin/knowledge/entries/{id} 编辑：version+1；跨租户 404', 'POST /{id}/publish：draft/pending_review → published（记录 reviewedAt）；archived 可重新发布回 published（归档非终点，#3108）', 'POST /{id}/archive：published → archived；DELETE /{id} 逻辑删除；全部按 tenant 隔离', 'GET /api/admin/knowledge/entries 分页：keyword/category/sourceType/status 筛选，updated_at 倒序'],
    skip_reason='[backend-contract] 知识卡片 CRUD/状态机由 MockMvc + Service 单测验证（KnowledgeCardControllerTest/KnowledgeCardServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'entries'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-016 [NORMAL] 知识知识卡片检索 - 仅 published + 租户隔离 + 关键词命中（LLM WIKI 板块 #3051）（源: cases/api.yml）──
_CASE_API_016 = EvalCase(
    id='API-016',
    legacy_id='',
    title='知识知识卡片检索 - 仅 published + 租户隔离 + 关键词命中（LLM WIKI 板块 #3051）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AI 客服/商家检索知识卡片：发布知识卡片可查、草稿/归档不可查、跨租户不可见'],
    expectations=[],
    data_checks=['GET /api/admin/knowledge/entries/search?query=&productId=&category= 仅返回本租户 status=published 知识卡片（draft/pending_review/archived 不返回）', '关键词命中 title/keywords/question/answer（租户内 LIKE，.or() 必须嵌套在 eq 内防跨租户泄露——审计 07 P1-6）', '跨租户知识卡片在任何查询下不可见（显式 eq tenant_id，复测 P1-6 回归）'],
    skip_reason='[backend-contract] 知识卡片检索由 MockMvc + Service 单测验证（KnowledgeCardControllerTest/KnowledgeCardServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'search'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-017 [NORMAL] 行业模板 - 目录 + 一键套用（去重 + source=template）（LLM WIKI 板块 #3051 P3）（源: cases/api.yml）──
_CASE_API_017 = EvalCase(
    id='API-017',
    legacy_id='',
    title='行业模板 - 目录 + 一键套用（去重 + source=template）（LLM WIKI 板块 #3051 P3）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家一键套用行业模板后自动获得预置知识卡片，无需逐条手写'],
    expectations=[],
    data_checks=['GET /api/admin/knowledge/templates 返回平台预置模板目录（templateId/industry/name/version/description/entryCount），布艺模板 entryCount≥25（商品级词条已移除，仅行业通用知识 26 条，#3095）', 'POST /api/admin/knowledge/templates/{templateId}/apply 将模板知识卡片复制到本租户：sourceType=template、sourceRef=templateId、status=published', '按 (tenant_id, title) 去重：重复标题跳过不重复插入，返回 {created, skipped} 统计', '套用跨租户无影响：仅当前租户可见（租户隔离拦截器）'],
    skip_reason='[backend-contract] 模板套用由 MockMvc + Service 单测验证（KnowledgeTemplateControllerTest/KnowledgeTemplateServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'template'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-019 [NORMAL] 待确认队列闭环 - 候选读+写路径齐全，采纳转卡片、拒绝记原因（LLM WIKI 板块 #3051 P5）（源: cases/api.yml）──
_CASE_API_019 = EvalCase(
    id='API-019',
    legacy_id='',
    title='待确认队列闭环 - 候选读+写路径齐全，采纳转卡片、拒绝记原因（LLM WIKI 板块 #3051 P5）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AI 提炼的候选知识卡片进入待确认队列，商家采纳（或编辑后采纳）后生效，拒绝则不生效'],
    expectations=[],
    data_checks=['GET /api/admin/knowledge/candidates 分页返回候选（缺省 status=pending，created_at 倒序，租户隔离）；GET /candidates/pending-count 返回待确认数', 'POST /{id}/adopt 采纳：候选 → 知识卡片（status=published，sourceType/sourceRef 继承候选来源），候选置 adopted；立即可被检索', 'POST /{id}/adopt-edited 编辑后采纳：人工修订标题/回答覆盖（标题回答必填），候选置 edited', 'POST /{id}/reject 拒绝：候选置 rejected + status_note 记录原因，不产生卡片；跨租户一律 404'],
    skip_reason='[backend-contract] 队列读写路径由 MockMvc + Service 单测验证（KnowledgeCandidateControllerTest/KnowledgeCandidateServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'candidates'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-020 [NORMAL] 会话提炼闭环 - 人工客服会话结束自动提炼 → 待确认队列（LLM WIKI 板块 #3051 P5b + #3090 自动触发）（源: cases/api.yml）──
_CASE_API_020 = EvalCase(
    id='API-020',
    legacy_id='',
    title='会话提炼闭环 - 人工客服会话结束自动提炼 → 待确认队列（LLM WIKI 板块 #3051 P5b + #3090 自动触发）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['人工客服会话结束后系统自动提炼候选知识卡片进入待确认队列（无需手动触发）；纯 AI 接待会话不提炼；商家采纳后生效'],
    expectations=[],
    data_checks=['提炼源 = 已结束**人工**会话（agent_sessions status=ended 且 employeeId 非空，转人工标记）：纯 AI 会话（employeeId 为空）不提炼（AI 回答是知识卡片消费输出，提炼=自循环且兜底话术污染知识库，#3090）', '自动触发：会话结束（endSession，status→ended）事务提交后发布 SessionEndedEvent，@Async @TransactionalEventListener(AFTER_COMMIT) 异步调 distillSession（不阻塞结束接口）', '防重复提炼：distillSession 先查该会话是否已有 conversation 候选（sourceRef=会话ID），已有 → 跳过，不重复调 LLM', 'POST /api/admin/knowledge/distill/conversations?hours=24 保留（管理端对账入口，语义同自动触发：仅人工会话），返回 {sessions, candidates, created, skipped}', 'ai-agent 内部 POST /internal/knowledge/distill（Service Token）：会话文本 → LLM 提炼 JSON 候选数组（title/answer/category/keywords/confidence/evidence），解析失败/异常降级返回空候选（不阻断）', '候选写入 knowledge_candidates：sourceType=conversation、sourceRef=会话ID、status=pending；同名知识卡片或同名待确认候选已存在 → 跳过（去重）；单会话上限 5 条、单条 200 字截断'],
    skip_reason='[backend-contract] 提炼逻辑由 ai-agent 单测（test_knowledge_distill.py）+ admin-api Service 测试（KnowledgeDistillServiceTest/KnowledgeDistillControllerTest）验证，LLM 行为 mock，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'distill'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-021 [NORMAL] 文档提炼闭环 - 文档文本 → AI 提炼候选 → 待确认队列（LLM WIKI 板块 #3051 P6）（源: cases/api.yml）──
_CASE_API_021 = EvalCase(
    id='API-021',
    legacy_id='',
    title='文档提炼闭环 - 文档文本 → AI 提炼候选 → 待确认队列（LLM WIKI 板块 #3051 P6）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家上传文档后，系统提炼候选知识卡片进入待确认队列（文档→知识卡片提炼，非文档→切块检索）'],
    expectations=[],
    data_checks=['POST /api/admin/knowledge/distill/documents（body: {title, content}）→ 文档文本提炼为候选，返回 {candidates, created, skipped}', '候选写入 knowledge_candidates：sourceType=document、sourceRef=文档标题、status=pending；同名卡片/待确认候选已存在 → 跳过', '文档内容 <50 字 → 422 中文提示；超长内容截断至 8000 字；提炼失败降级空候选', '原文仅作 evidence 保留，不参与运行时检索（文档→提炼，非文档→切块检索）'],
    skip_reason='[backend-contract] 文档提炼复用 KnowledgeDistillService/Controller 单测（已扩展文档用例），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'distill', 'document'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-022 [NORMAL] Agent 知识卡片检索 - 词条优先、命中标注来源、未命中通用兜底（LLM WIKI 板块 #3051 P7）（源: cases/api.yml）──
_CASE_API_022 = EvalCase(
    id='API-022',
    legacy_id='',
    title='Agent 知识卡片检索 - 词条优先、命中标注来源、未命中通用兜底（LLM WIKI 板块 #3051 P7）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AI 客服回答知识类问题时优先采用本店知识卡片内容，未命中才用通用知识兜底'],
    expectations=['knowledge_search'],
    data_checks=['customer_knowledge 技能启用 knowledge_search（tool_names 含之，System Prompt 词条优先：命中注明「📖 来自本店知识库」、未命中注明「💡 通用行业建议」）', 'knowledge_search 调 GET /api/admin/knowledge/cards/search（query/category），命中返回 ≤3 条卡片（title/answer≤500 字/category/sourceType），hit=true', '未命中 hit=false → LLM 通用知识兜底 + 通用建议免责；检索接口不可用 → 降级同兜底（不阻断回答）', 'query 必填（空拒绝）；权限不足拒绝；租户隔离由 admin-api 强制（工具侧无跨租户入口）'],
    skip_reason='[backend-contract] 工具行为由 ai-agent 单测验证（test_tools_knowledge_search.py + test_customer_knowledge_simplified.py），LLM 行为 mock，不进入 agent-eval 冒烟',
    tags=['api', 'knowledge', 'wiki', 'tool', 'agent'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-012 [NORMAL] 语音转写接口容错 - 空/极小/静音音频返回友好 4xx/5xx，不裸 500（#2984）（源: cases/api.yml）──
_CASE_API_012 = EvalCase(
    id='API-012',
    legacy_id='',
    title='语音转写接口容错 - 空/极小/静音音频返回友好 4xx/5xx，不裸 500（#2984）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['语音转写接口异常输入容错'],
    expectations=[],
    data_checks=['空文件 → 400 中文 detail「音频文件为空，未检测到声音」', '极小文件（<1KB）→ 400「未检测到有效音频内容，录音可能过短或麦克风未开启」，不裸 500', '超 10MB / 估算超 60s → 400 中文 detail（音频文件过大 / 音频时长超过上限）', 'DashScope 未识别到语音内容（静音）→ 400「未识别到语音内容，请靠近麦克风重新录音」', 'ASR 上游不可用 → 503「语音识别服务暂时不可用，请稍后重试」', '正常音频 → 200：text/language/duration_ms 齐全'],
    skip_reason='[backend-contract] 函数级容错由 ai-agent 单测（test_asr.py TestTranscribeAudioFriendlyErrors）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['asr', 'voice', 'error-handling'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-008 [NORMAL] 缺必填 @RequestParam / 参数类型不符 ⇒ 400 + 字段名（不是 500），且处理器分支台账双向一致（#5982）（源: cases/api.yml）──
_CASE_API_008 = EvalCase(
    id='API-008',
    legacy_id='',
    title='缺必填 @RequestParam / 参数类型不符 ⇒ 400 + 字段名（不是 500），且处理器分支台账双向一致（#5982）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['B 端调后端接口漏传必填参数（或把参数类型写错）时，返回 400 并点名该字段，而不是 500「服务器内部错误」'],
    expectations=[],
    data_checks=["实例（真端点 + 真 @RestControllerAdvice）：POST /api/admin/inbound-orders/opening-import 只带 file、缺 importRunId ⇒ 400 code=BAD_REQUEST、error.details[0].field=importRunId、响应全文含 importRunId；修前实测 500 INTERNAL_ERROR「服务器内部错误」（日志 Required request parameter 'importRunId' ... is not present）；闸门在调 service 之前（verifyNoInteractions）", '类级守卫（反射双向）：GlobalExceptionHandler 的 @ExceptionHandler 目标类型集合 ⇄ 台账 BRANCH_LEDGER 相等 —— 台账有而处理器缺 = 红（即 #5982 形态）、处理器有而台账缺 = 红（新增分支未登记）；兜底 Exception.class 必须仍在（削掉 = 未知异常漏原始堆栈）', '请求绑定失败族（MissingServletRequestParameterException / MethodArgumentTypeMismatchException / HttpMessageNotReadableException / MissingRequestHeaderException / MissingPathVariableException / ServletRequestBindingException）每个成员要么有具名分支、要么在豁免台账里登记理由（裸露成员判红）', '豁免台账只许缩短：现取豁免 ⊆ 冻结基线；理由非空；已被处理的「陈旧豁免」判红；MissingRequestHeaderException 的豁免附带**可判前置** = main 源码必填 @RequestHeader 数 = 0（出现即该豁免失效并判红）', '行为双向对照（探针控制器经真 Spring 分发链）：缺必填参数 / 参数类型不符 ⇒ 400；无具名分支的裸 RuntimeException ⇒ 仍 500 INTERNAL_ERROR（证明不是「什么都返 400」；反向对照**不能**用 IllegalStateException —— 它自己有具名分支、返 400）', '判别力自证：四类坏形态（删分支 / 增未登记分支 / 豁免超基线 / 出现必填请求头）在内存里各自判红，合法输入不判红'],
    skip_reason='[backend-contract] 由 admin-api 单测（GlobalExceptionHandlerCoverageTest / InboundOrderOpeningImportRequiredParamTest）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'error-handling', 'exception-handler'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── API-023 [NORMAL] 建号缺岗位/角色 ⇒ 422 + 未落库（不再按 operator 兜底），且「缺省角色字面量」台账双向一致（#5987）（源: cases/api.yml）──
_CASE_API_023 = EvalCase(
    id='API-023',
    legacy_id='',
    title='建号缺岗位/角色 ⇒ 422 + 未落库（不再按 operator 兜底），且「缺省角色字面量」台账双向一致（#5987）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['API 直连创建员工时没传岗位（也没传 role/roleIds）：账号不得拿到运营级权限，应明确报错要求选岗位'],
    expectations=[],
    data_checks=['实例（真端点 + 真 @RestControllerAdvice）：POST /api/admin/users 只带 phone/name/username/password（或缺 position 且 role/roleIds 皆无）⇒ 422 VALIDATION_ERROR（BusinessException.validationError 的既有码位）+ 响应全文含「岗位」（可行动文案）；闸门在调 userService.createUser 之前（verifyNoInteractions = 未落库的行为等价读数）；修前实测 200 + role=operator + 岗位名=operator（运营级 26 码含 order:create/inbound:create/finance:create/order:refund）', '正向对照（证明不是「什么都返 400」）：带 position（岗位=角色体系 #2969）⇒ 200 且 role 按岗位解析下发；只带 role 不传 position ⇒ 200 且 position 回退为角色名（既有契约 employee-role.position-fallback 不回归）', '服务侧实例：UserService.createUser 的 role 为空/空白 ⇒ 422 BusinessException（VALIDATION_ERROR），且 userMapper.insert 一次都没发生（「返回了错误」≠「没写进去」）；显式 role ⇒ 成功落库且写入行 role/position 逐字等于调用方声明', '类级元守卫：「缺省角色字面量」赋值点（.role("<字面量>") / .role(x != null ? x : "<字面量>")）扫描结果 ⇄ 台账双向相等（台账有而扫描无 = 陈旧 ⇒ 红；扫描有而台账无 = 新增缺省/授权字面量 ⇒ 红）；台账只许缩短（条数现取比较）', '类级语义判据：两个建号入口里含 .position(...) 的语句不得出现写权限角色字面量（admin/super_admin/operator/product_manager/finance/sales/manager）', '判别力自证：旧形态 .role(x != null ? x : "operator") 判 FALLBACK、.role("super_admin") 判 LITERAL、.role(user.getRole()) 与 .role(anyToString(map.get("role"))) 不命中；并反射读一次台账常量与扫描实现（防空跑绿）'],
    skip_reason='[backend-contract] 由 admin-api 单测（AdminUserControllerPostMissingPositionTest / EmployeeGrantDefaultRoleMetaGuardTest）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['api', 'fail-closed', 'permission'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_API_001,
    _CASE_API_002,
    _CASE_API_003,
    _CASE_API_004,
    _CASE_API_005,
    _CASE_API_006,
    _CASE_API_007,
    _CASE_API_009,
    _CASE_API_010,
    _CASE_API_013,
    _CASE_API_014,
    _CASE_API_015,
    _CASE_API_016,
    _CASE_API_017,
    _CASE_API_019,
    _CASE_API_020,
    _CASE_API_021,
    _CASE_API_022,
    _CASE_API_012,
    _CASE_API_008,
    _CASE_API_023,
)
