# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: migration（源: cases/migration.yml，10 条）

from ._schema import Difficulty, EvalCase, Skill

# ── MIG-001 [NORMAL] 客户 Excel 任意表头：AI 映射建议（非固定模板）（源: cases/migration.yml）──
_CASE_MIG_001 = EvalCase(
    id='MIG-001',
    legacy_id='',
    title='客户 Excel 任意表头：AI 映射建议（非固定模板）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=["POST /api/internal/migration/customer-mapping {headers:['购货单位','联系方式','送货地点'], ...}"],
    expectations=[],
    data_checks=['AI 返回 mappings：source_index 指向正确列，target_field ∈ 请求 fields[].key；未知 target / 越界 index / 重复 target 被过滤（承载体 = tests/test_customer_mapping.py）', '合法映射 confidence ∈ [0,1]；degraded=false 只在 LLM 输出可解析时出现'],
    skip_reason='[backend-contract] 内部 AI 映射端点的 JSON 契约由 pytest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ai-mapping', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-002 [EDGE] 客户 Excel 任意表头：AI 输入样本脱敏（源: cases/migration.yml）──
_CASE_MIG_002 = EvalCase(
    id='MIG-002',
    legacy_id='',
    title='客户 Excel 任意表头：AI 输入样本脱敏',
    skill=Skill.GENERAL,
    difficulty=Difficulty.EDGE,
    user_inputs=['样本含手机号 13800138000 / 邮箱 a@b.com 时调用映射端点'],
    expectations=[],
    data_checks=['送给 LLM 的 prompt 不含原始手机号/邮箱；手机号与邮箱已打码（承载体 = tests/test_customer_mapping.py::test_masks_pii_before_prompt）', '日志不含样本原文；端点只返回映射建议，不回传客户样本之外的完整行'],
    skip_reason='[backend-contract] 脱敏判据由 pytest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ai-mapping', 'pii', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-003 [EDGE] AI 映射不可用/输出非法 ⇒ 降级但不阻断迁移（源: cases/migration.yml）──
_CASE_MIG_003 = EvalCase(
    id='MIG-003',
    legacy_id='',
    title='AI 映射不可用/输出非法 ⇒ 降级但不阻断迁移',
    skill=Skill.GENERAL,
    difficulty=Difficulty.EDGE,
    user_inputs=['LLM 抛异常或返回非 JSON 时调用映射端点'],
    expectations=[],
    data_checks=['端点仍返回 success=true + degraded=true + mappings=[]，不抛 500（承载体 = tests/test_customer_mapping.py）', 'admin-api analyze 在 AI 不可用时用确定性表头别名兜底，aiDegraded=true，页面可手工映射'],
    skip_reason='[backend-contract] 降级契约由 pytest + Java 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ai-mapping', 'degraded', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-004 [NORMAL] 客户 Excel 解析 + 列映射分析：任意表头、空表头、行数上限（源: cases/migration.yml）──
_CASE_MIG_004 = EvalCase(
    id='MIG-004',
    legacy_id='',
    title='客户 Excel 解析 + 列映射分析：任意表头、空表头、行数上限',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/admin/customers/import/analyze multipart file'],
    expectations=[],
    data_checks=['任意表头（购货单位/联系方式/送货地点）能解析出 headers + 样本 + 确定性映射建议；不写库', '空表头补「列N」；超过 2000 行 / 5MB 显式 422，不静默截断（承载体 = CustomerImportParserTest）'],
    skip_reason='[backend-contract] Excel 解析/边界由 admin-api 单测验证，非 Agent 行为，不进入 agent-eval 冒烟',
    tags=['excel', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-005 [NORMAL] 试运行绝不写库；缺 externalId / 重复 externalId / 手机号冲突 ⇒ 行错误（源: cases/migration.yml）──
_CASE_MIG_005 = EvalCase(
    id='MIG-005',
    legacy_id='',
    title='试运行绝不写库；缺 externalId / 重复 externalId / 手机号冲突 ⇒ 行错误',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/admin/customers/import/preview multipart file + mapping'],
    expectations=[],
    data_checks=['preview 期间 mapper 的 insert/update 零调用，客户行数不变（承载体 = CustomerImportServiceTest）', '缺 externalId / displayName、文件内 externalId 重复、手机号撞他人 ⇒ action=ERROR，不写该行'],
    skip_reason='[backend-contract] 试运行只读判据由 admin-api 单测验证，非 Agent 行为，不进入 agent-eval 冒烟',
    tags=['preview', 'fail-closed', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-006 [NORMAL] 正式导入按 externalId 幂等：重跑不重复建、updateExisting 可控更新（源: cases/migration.yml）──
_CASE_MIG_006 = EvalCase(
    id='MIG-006',
    legacy_id='',
    title='正式导入按 externalId 幂等：重跑不重复建、updateExisting 可控更新',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/admin/customers/import/commit（同一文件重跑；updateExisting=false/true）'],
    expectations=[],
    data_checks=['首次创建写 external_id + wechat_nickname + phone + default_receiver_address；同一 (tenant, external_id) 仍 1 行（承载体 = CustomerImportServiceTest）', '重跑 updateExisting=false ⇒ SKIPPED；true ⇒ 调 updateCustomer 且不新建；created/updated/skipped/failed 计数与行一致'],
    skip_reason='[backend-contract] 幂等/重跑由 admin-api 单测验证，非 Agent 行为，不进入 agent-eval 冒烟',
    tags=['idempotency', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-007 [NORMAL] 客户导入 HTTP 端点：analyze/preview/commit + customer:create 权限（源: cases/migration.yml）──
_CASE_MIG_007 = EvalCase(
    id='MIG-007',
    legacy_id='',
    title='客户导入 HTTP 端点：analyze/preview/commit + customer:create 权限',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/admin/customers/import/{analyze,preview,commit}'],
    expectations=[],
    data_checks=['三个端点均返回 ApiResponse.success + 对应 data；mapping/updateExisting 参数透传（承载体 = CustomerImportControllerTest）', '三端点均标注 @RequirePermission("customer:create")，不给只读角色接触客户 PII'],
    skip_reason='[backend-contract] HTTP 契约由 admin-api 单测验证，非 Agent 行为，不进入 agent-eval 冒烟',
    tags=['api', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-008 [EDGE] AI 映射客户端失败语义：超时/非 2xx/坏 JSON ⇒ null，由确定性兜底（源: cases/migration.yml）──
_CASE_MIG_008 = EvalCase(
    id='MIG-008',
    legacy_id='',
    title='AI 映射客户端失败语义：超时/非 2xx/坏 JSON ⇒ null，由确定性兜底',
    skill=Skill.GENERAL,
    difficulty=Difficulty.EDGE,
    user_inputs=['ai-agent-service 不可达或返回 success=false 时调用 analyze'],
    expectations=[],
    data_checks=['CustomerImportAiClient.suggest 返回 null，不抛异常；analyze 的 aiDegraded=true 且仍有确定性建议（承载体 = CustomerImportAiClientTest）', '只有 data.mappings 的合法结构才映射为内部 DTO；source_index/target_field 逐字段取，不按位置猜'],
    skip_reason='[backend-contract] 客户端失败语义由 admin-api 单测验证，非 Agent 行为，不进入 agent-eval 冒烟',
    tags=['ai-mapping', 'degraded', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-009 [NORMAL] 客户迁移工作台：上传 → AI 映射建议 → 人工确认（源: cases/migration.yml）──
_CASE_MIG_009 = EvalCase(
    id='MIG-009',
    legacy_id='',
    title='客户迁移工作台：上传 → AI 映射建议 → 人工确认',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['打开 /customers/import，上传任意表头客户 Excel'],
    expectations=[],
    data_checks=['analyze 返回 success=true 后页面渲染每个源列 + 样本 + 目标字段下拉；AI 建议预选；必填 externalId/displayName 有标记（承载体 = page.test.tsx）', 'AI 降级时显示提示，仍可手工映射并试运行'],
    skip_reason='[frontend-contract] 页面行为由 admin-web Vitest/RTL 验证；真实登录/截图的 Playwright 多模态验收在集成阶段单独跑',
    tags=['ui', 'ai-mapping'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── MIG-010 [NORMAL] 客户迁移工作台：试运行 → 正式导入 → 逐行结果（源: cases/migration.yml）──
_CASE_MIG_010 = EvalCase(
    id='MIG-010',
    legacy_id='',
    title='客户迁移工作台：试运行 → 正式导入 → 逐行结果',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['在 /customers/import 点试运行，再点正式导入'],
    expectations=[],
    data_checks=['未试运行前正式导入接口未被调用（not called）；试运行后展示 new/update/skip/error 汇总；commit 返回 success=true 后展示 created/updated/skipped/failed（承载体 = page.test.tsx）', 'updateExisting 勾选透传到 preview/commit'],
    skip_reason='[frontend-contract] 页面行为由 admin-web Vitest/RTL 验证；真实登录/截图的 Playwright 多模态验收在集成阶段单独跑',
    tags=['ui', 'preview'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_MIG_001,
    _CASE_MIG_002,
    _CASE_MIG_003,
    _CASE_MIG_004,
    _CASE_MIG_005,
    _CASE_MIG_006,
    _CASE_MIG_007,
    _CASE_MIG_008,
    _CASE_MIG_009,
    _CASE_MIG_010,
)
