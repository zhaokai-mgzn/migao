# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: token-refresh（源: cases/token-refresh.yml，4 条）

from ._schema import Difficulty, EvalCase, Skill

# ── TR-001 [NORMAL] refresh-success — 401 自动刷新并重放原请求（源: cases/token-refresh.yml）──
_CASE_TR_001 = EvalCase(
    id='TR-001',
    legacy_id='',
    title='refresh-success — 401 自动刷新并重放原请求',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['admin-web 业务请求收到 401，TokenRefreshManager 自动刷新并重放'],
    expectations=['direct_reply'],
    data_checks=['refreshAccessToken() 被调用一次；原请求 headers.Authorization 更新为 Bearer <newToken>', '原请求 _retry=true；通过注入的 axiosInstance 重放原请求并返回其结果'],
    skip_reason='[backend-contract] 依赖注入 mock 的单元测试验证（frontend/admin-web/tests/unit/lib/token-refresh-manager.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['token_refresh', 'auth', 'retry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── TR-002 [NORMAL] single-flight — 并发 401 仅触发一次刷新并共享结果（源: cases/token-refresh.yml）──
_CASE_TR_002 = EvalCase(
    id='TR-002',
    legacy_id='',
    title='single-flight — 并发 401 仅触发一次刷新并共享结果',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['多个请求同时收到 401，TokenRefreshManager 单飞刷新'],
    expectations=['direct_reply'],
    data_checks=['refreshAccessToken() 仅调用一次；刷新中后续请求入 failedQueue 挂起', '刷新成功后队列请求以同一新 token resolve，且刷新结束后 isRefreshing=false、queueLength=0'],
    skip_reason='[backend-contract] 依赖注入 mock 的单元测试验证（frontend/admin-web/tests/unit/lib/token-refresh-manager.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['token_refresh', 'concurrency', 'single_flight'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── TR-003 [NORMAL] refresh-failed — 刷新失败清除凭证并跳登录页（源: cases/token-refresh.yml）──
_CASE_TR_003 = EvalCase(
    id='TR-003',
    legacy_id='',
    title='refresh-failed — 刷新失败清除凭证并跳登录页',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['刷新接口失败或返回 null，TokenRefreshManager 登出'],
    expectations=['direct_reply'],
    data_checks=['refreshAccessToken 返回 null 或抛异常 → 全部挂起请求 reject、clearAuth() 被调用', "window.location.href 置为 /login；原请求 Promise.reject（null 分支带 'Token refresh failed'，异常分支透传原错误）"],
    skip_reason='[backend-contract] 依赖注入 mock 的单元测试验证（frontend/admin-web/tests/unit/lib/token-refresh-manager.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['token_refresh', 'auth', 'logout'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── TR-004 [NORMAL] no-loop — 刷新/登录请求自身 401 不触发刷新（防死循环）（源: cases/token-refresh.yml）──
_CASE_TR_004 = EvalCase(
    id='TR-004',
    legacy_id='',
    title='no-loop — 刷新/登录请求自身 401 不触发刷新（防死循环）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['刷新或登录请求自身收到 401，TokenRefreshManager 直接拒绝'],
    expectations=['direct_reply'],
    data_checks=["URL 含 /api/auth/refresh 或 /api/auth/admin/login → reject('Authentication failed')", 'refreshAccessToken 不被调用；clearAuth() 被调用、window.location.href 置为 /login'],
    skip_reason='[backend-contract] 依赖注入 mock 的单元测试验证（frontend/admin-web/tests/unit/lib/token-refresh-manager.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['token_refresh', 'auth', 'no_loop'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_TR_001,
    _CASE_TR_002,
    _CASE_TR_003,
    _CASE_TR_004,
)
