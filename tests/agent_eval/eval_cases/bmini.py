# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: bmini（源: cases/bmini.yml，54 条）

from ._schema import Difficulty, EvalCase, Skill

# ── BM-001 [NORMAL] B 端员工小程序登录 - 账号密码（用户名@企业编码）登录，不再走微信手机号匹配（源: cases/bmini.yml）──
_CASE_BM_001 = EvalCase(
    id='BM-001',
    legacy_id='',
    title='B 端员工小程序登录 - 账号密码（用户名@企业编码）登录，不再走微信手机号匹配',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['员工在 bmini-app 登录页填 `用户名@企业编码` + 密码 → POST /api/auth/employee/login → 服务端按编码解析租户、按 (tenant_id, username) 定位员工 → 签发含 permissions 的员工 JWT（issue #5485 收口：员工只留用户名+密码）'],
    expectations=['direct_reply'],
    data_checks=['登录成功返回 accessToken + user；租户 = 标识里的企业编码解析所得（不由前端传 tenantId）', '**不再**写入 user_identities / 不再需要 phoneCode / 不再有 openid 免密路径（原「微信授权手机号匹配员工 + 绑定 openid」整体退场）', '签发的 JWT 含 roles + permissions（与 loginBySms 同源，工具级鉴权可用）'],
    skip_reason='[backend-contract] 纯后端单测契约（AuthService.bminiLogin 的废弃语义 + AuthService.loginByEmployee），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'employee'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-002 [NORMAL] B 端员工小程序登录 - bmini 专用入口已废弃（明确拒绝，不静默失联）（源: cases/bmini.yml）──
_CASE_BM_002 = EvalCase(
    id='BM-002',
    legacy_id='',
    title='B 端员工小程序登录 - bmini 专用入口已废弃（明确拒绝，不静默失联）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['任何客户端仍调用 POST /api/auth/bmini/login（旧版小程序在升级窗口内）→ 服务端明确拒绝并引导到 /api/auth/employee/login'],
    expectations=['direct_reply'],
    data_checks=['拒绝语义：抛 AUTH_FAILED + 引导文案（沿用 #375「密码登录已禁用」范式），**不是** 404/静默失联', '**不存在**「openid 已绑定即免密登录」这条路径（本次整条删除）—— 员工每次都要用账号密码登录'],
    skip_reason='[backend-contract] 纯后端单测契约（BminiLoginServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'deprecated'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-003 [NORMAL] B 端登录拒绝语义保留 - 匹配不到员工绝不自动建号，且失败不泄露账号是否存在（源: cases/bmini.yml）──
_CASE_BM_003 = EvalCase(
    id='BM-003',
    legacy_id='',
    title='B 端登录拒绝语义保留 - 匹配不到员工绝不自动建号，且失败不泄露账号是否存在',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['POST /api/auth/employee/login 用户名在企业下不存在（或密码错、或该账号被禁用）→ 拒绝登录，不自动创建用户（与 C 端 findOrCreate 语义相反）'],
    expectations=['direct_reply'],
    data_checks=['失败统一为 401 AUTH_FAILED「账号或密码错误」（**反枚举**：用户名不存在/密码错/账号禁用/编码不存在 四者同码同文案）', '不向 users / user_identities 写入任何新记录、不返回 token', 'C 端 consumer 账号不会被员工登录入口认领（员工凭据由管理员设置，与 C 端自动建号语义相反）'],
    skip_reason='[backend-contract] 纯后端单测契约（EmployeeLoginServiceTest / BminiLoginServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'defense'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-004 [NORMAL] B 端小程序请求层基建 - Token 注入/401 清理/重试（源: cases/bmini.yml）──
_CASE_BM_004 = EvalCase(
    id='BM-004',
    legacy_id='',
    title='B 端小程序请求层基建 - Token 注入/401 清理/重试',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['bmini-app 复用 C 端 request.ts：请求自动带 Authorization Bearer；401 清 Token 跳登录页；网络错误指数退避重试'],
    expectations=['direct_reply'],
    data_checks=['非 skipAuth 请求头含 Authorization: Bearer <token>', '401 响应清除本地 Token 并跳转登录页', 'timeout/fail 类错误按指数退避重试（MAX_RETRIES 次）'],
    skip_reason='[backend-contract] 纯前端单元测试（bmini-app tests/request.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'request'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-005 [NORMAL] B 端认证 store - 登录状态流转/持久化/登出清理（源: cases/bmini.yml）──
_CASE_BM_005 = EvalCase(
    id='BM-005',
    legacy_id='',
    title='B 端认证 store - 登录状态流转/持久化/登出清理',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['bmini-app authStore（Zustand+persist）：login 成功写入 token/user；logout 清空；initialize 从本地恢复；token 过期自动登出'],
    expectations=['direct_reply'],
    data_checks=['bminiLoginAction 成功 → isLoggedIn=true + token/user 落 storage', 'logout 清空 token/user/isLoggedIn（含 storage 持久化清理）', 'initialize 有效 token 恢复登录态；过期 token 自动 logout'],
    skip_reason='[backend-contract] 纯前端单元测试（bmini-app tests/store-auth.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'store', 'auth'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-006 [NORMAL] 工人扫码开工/领活 - 扫码/手输单号 → 本单工序 → 开工（领活）→ 本套工序明细（源: cases/bmini.yml）──
_CASE_BM_006 = EvalCase(
    id='BM-006',
    legacy_id='',
    title='工人扫码开工/领活 - 扫码/手输单号 → 本单工序 → 开工（领活）→ 本套工序明细',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人扫加工单二维码（或手输单号）→ 老师傅看到本单工序：按部位分组展示「工序名 · 应做数量+单位 · 单价」→ 点「完成报工」→ 工序列推进 → 必完工序全绿显示「✅ 订单生产完成」；🔴 2026-09-21 改判（issue #4967）：工人**扫新码（套 × 部位）** ⇒ A 模式一屏显示「套号 · 部位 + 系统推断的这一道 + 应做数量」+ 一个大按钮**【报工】** + **本套工序明细**（本套 → 部位 → 工序：逻辑名 / 应做数量+单位 / 单价 / 状态 / 已报数量）⇒ 点【报工】= 报工（先报工再生产，完工不扫）'],
    expectations=['direct_reply'],
    data_checks=['🔴 **本用例的承载体已改钉到工人端 H5 `/w/`**（2026-10-14，issue #6868 实现包 D1；逐字口径见 merge_log）：工人报工的唯一实现是 frontend/worker-h5（零构建原生 ESM 静态页）；小程序侧那**第二份实现**（frontend/bmini-app/src/pages/production/index/**）按用户裁定（「没有用处的页面就直接删了」）整页删除 ⇒ 本用例原挂在它上面的页面级断言随之改钉到 H5 面。**退休登记本身也有判据**（不留「描述了不存在的页面」的用例）：该页已不在 frontend/bmini-app/src/app.config.ts 的 pages 里、工人工作台也不再发射指向它的入口 —— 证据 frontend/bmini-app/tests/page-entry-reachability.test.ts（L0/L2 入口台账）+ frontend/bmini-app/tests/worker-home-page.test.tsx（「扫码报工」主按钮不渲染的反向断言）', '码的容错解析（H5 侧）：`/w/?t=<码>`（**2026-10-27 起 `/s/<短码>` 的 302 落点改成 `/b/?t=<token>`**，见 BM-053 issue #7879；`/w/` 转兼容期，解析面照旧认这种旧形态，判据 = frontend/worker-h5/tests/worker-h5-6866-scan-landing.test.mjs）在**装载时解析一次**并直接渲染解析结果 —— 已登录工人扫部位码不再停在「输码」空态（issue #6866）；旧码降级（`granularity=order`）⇒ 显式提示必须选部位、**不**出【开工】按钮（绝不默认取第 1 套）；解析失败 ⇒ 上屏服务端点名的原因。证据：frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs + frontend/worker-h5/tests/worker-h5-legacy-code.test.mjs + frontend/worker-h5/tests/worker-h5-6866-scan-landing.test.mjs', '🔴 **扫码 = 开工 / 领活**（issue #4967，2026-09-21 用户逐字裁定①「工人都是先扫码报工后再真实进行生产」）：H5 一屏的大按钮文案 = **【报工】**（`id=wh5-report`；2026-10-14 用户逐字裁定②「工人屏全部统一到『报』」把工人可见面统一到「报」⇒ 由【开工】改钉为【报工】；**id 与动作一字未改**；改回【完成】或改回【开工】⇒ 必红）；点它只调一次 `POST /api/worker/production/scan/complete`（数量/身份都不传：数量缺省由服务端取剩余应做、身份由服务端从工人 session 解）；报工在飞期间按钮禁用 + 说「提交中」（issue #6667 第 4 条，涉计件正确性）；未确定工序（operation=null）⇒ 屏上**没有**【开工】按钮。记账口径（`started_at` / `done_at` / 一次事务）一字不动（见 PG-018）。证据：frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs + frontend/worker-h5/tests/worker-h5-page.test.mjs', '🔴 **按套展示工序细节**（issue #4967 交付物 2）：扫码后（除「当前这道 + 按钮」外）列出**本套各部位的工序明细**（逻辑名 / 应做数量+单位 / 单价 / 状态 / 已报数量）。数据**只**来自服务端解析响应的 `set_overview`（聚合只有一份，见 PG-058）—— 页面**不**自己聚合、也**不**另拉 `GET /api/worker/production/orders/{orderId}/operations` 再按套重排（第二份口径）。🔴 **缺值不渲染**：`set_overview` 缺失 / `positions` 为空 ⇒ 明细块一个字节都不出现（不渲染 undefined 米 / ¥NaN）；`unit_price` 为 `null` = **未定价**（≠ 0 元，issue #4696）显式写「未定价」。证据：frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs（⑨ / ⑨-b / ⑨-c / ⑩）', '🔴 **工序选择器**（issue #6635，2026-10-10 用户裁定 = 选项 A）：扫一次码后，解析响应的 `operation`（系统推断的那道）+ `alternatives`（其它待领工序）一起渲染成**正常的工序选择器**（稳定 id `wh5-op-picker`，标签「选工序（点哪道就领哪道）」，当前那道带 `is-on` + `aria-pressed=true`）；点别的候选 ⇒ 走既有**一键改**（`GET /scan?operation_id=…`，归属由服务端校验 = 防呆④）；点当前已选中那道 ⇒ **一个请求都不发**（no-op）。证据：frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs（② / ②-b）+ frontend/worker-h5/tests/worker-h5-operation-display.test.mjs', '报工失败（success=false）⇒ 上屏服务端 message 且**不清空**工序列表（工人可继续）；弱网（传输层失败）⇒ 进本机补传队列并**复用同一幂等键**（补传不重复计件）。幂等键的服务端侧与网络层侧判据见 PG-018。证据：frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs + frontend/worker-h5/tests/worker-h5-api.test.mjs + frontend/bmini-app/tests/production-report-idempotency.test.ts', '**本包删除的另两格（如实登记，不粉饰；判据没有被静默放宽）**：① 原「报工数量键盘 = 小数键位（`digit`）」是**小程序 `<Input>`** 的键盘面（h5 的 `type=digit` 无意义）⇒ 随页面退场；同一病灶在**商家面**的现役判据 = `.github/cases/ui.yml` 的 UI-055（frontend/bmini-app/tests/form-card.test.tsx + 类级键盘守卫）。② 原「非微信浏览器的扫码降级 = 拍照识别」是**页内扫一扫**的降级面；H5 `/w/` **没有页内扫码**（工人用微信 / 系统扫一扫打开页面）⇒ 该降级面在小程序侧只剩 frontend/bmini-app/src/utils/platform.ts 的常量与 frontend/bmini-app/tests/h5-platform-runtime.test.ts 的平台判据（`scanCode` 的 h5 台账条目随唯一用法一起删除，判据 = h5-platform-api-guard.test.ts 的「台账条目必须仍然活着」）。'],
    skip_reason='[backend-contract] 纯前端单元测试（frontend/worker-h5/tests/*.mjs + frontend/bmini-app/tests/production-qr.test.ts / production-report-idempotency.test.ts / worker-home-page.test.tsx / page-entry-reachability.test.ts / h5-platform-runtime.test.ts / h5-platform-api-guard.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'production', 'qr-report'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-008 [NORMAL] 黄金策唤出授权门（按权限码）- 管理员默认可唤；未授权员工明确「需要管理员授权」+ 可行动引导（源: cases/bmini.yml）──
_CASE_BM_008 = EvalCase(
    id='BM-008',
    legacy_id='',
    title='黄金策唤出授权门（按权限码）- 管理员默认可唤；未授权员工明确「需要管理员授权」+ 可行动引导',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['企业管理员唤出黄金策对话（持该组权限码 ⇒ 默认可唤）；未获授权的员工进入黄金策页 ⇒ 看到「需要管理员授权」以及去哪开通的引导'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**唯一判定**：管理员权限码集合在服务端**只有一处字面量**（`backend/admin-api/src/main/java/com/migao/admin/security/AdminGate.java` 的 `ADMIN_PERMISSION_CODES`），全仓**代码面**语料里该集合三码的**字面量相邻出现**次数 == 1。红证：在第二个文件里再抄一遍三码数组 ⇒ 计数变 2 ⇒ 红。证据：tests/unit_ci_workflows/test_mibao_chat_gate.py 判据 ①。', '判据 2·**前端零副本**：`frontend/bmini-app/src/**` 与 `frontend/admin-web/src/**` 的任一文件里，该集合的**不同成员数 ≤ 1** —— 两端都只消费服务端下发的 `capabilities.mibaoChat` 布尔位，不自己判码。红证：在前端写两个成员参与判定 ⇒ 红。证据：tests/unit_ci_workflows/test_mibao_chat_gate.py 判据 ②。', '判据 3·**码必须真在目录里**：集合每个成员 ∈ `RegistrationService.defaultPermissions` 的码集 ∧ ∈ `PermissionService.ensureFullPermissionCatalog` 的码集（两处目录逐值相等，与既有判据 9 同源复用）；**本单新增的那个成员**还必须由一条迁移落库（否则**存量租户永远拿不到它**）。红证：写一个目录里没有的码 ⇒ 红（**本包开工前的现状正是这一形态**：该码全仓 0 命中）。证据：tests/unit_ci_workflows/test_mibao_chat_gate.py 判据 ③。', "判据 4·**只回填 `admin`**（用户 2026-09-26 裁定⑧「严格收窄」）：迁移 `backend/admin-api/src/main/resources/db/migration/V132__add_agent_chat_permission.sql` 的岗位授权谓词恒为 `r.code = 'admin'`，且带终态对账 `DO` 块（多授一个非 admin 岗位 ⇒ `RAISE EXCEPTION` 回滚）；迁移幂等（`WHERE NOT EXISTS` + `ON CONFLICT DO NOTHING`）且头部登记回滚 SQL。红证：把谓词放宽到客服岗位 ⇒ 红。证据：tests/unit_ci_workflows/test_mibao_chat_gate.py 判据 ④。**口径澄清（issue #6525）**：「落库」= 该迁移含 `INSERT INTO`；只改展示名的 `UPDATE`（如品牌改名迁移 V150 对 `agent:chat` 的 `name`/`description` 回填）**不计入**迁移计数 —— 否则「防重复授权」会退化成「迁移里不许出现这个码」。判别力自证 = 同文件 `test_rename_only_migration_is_not_counted_as_landing`（探针让「提到即算」多 1 条、落库计数不变，④ 仍绿）。", '判据 5·**既有行为零回归**：`role=\'admin\'` 的账号仍能唤黄金策 —— 走的是 `AdminGate` 的 `"*"` **通配判真**分支（`RoleService` 四处分支恒为 `["*"]`），**不是**为 admin 写的特例分支。红证：把判定改成读 `role` 字段 ⇒ 红（引入第二套身份口径）。证据：backend/admin-api/src/test/java/com/migao/admin/security/AdminGateTest.java 的「"*" 通配直接判真」与「三码全持为真、缺一为假」两条。', '判据 6·**未授权 ⇒ 入口可见 + 逐字「需要管理员授权」+ 可行动引导**（issue 范围 3 逐字「不是静默隐藏，也不是 403 白屏」）：端侧拒绝态**渲染得出来**（稳定锚点 `mibao-gate-denied`）、文案常量逐字等于「需要管理员授权」、引导含「员工管理」（去哪授权）。红证：文案退回泛化「无权限」/ 去掉引导 ⇒ 红。证据：frontend/bmini-app/tests/mibao-access-gate.test.tsx + frontend/admin-web/tests/unit/components/MibaoAccessGate.test.tsx。', '判据 7·**两端同源**：小程序端（`frontend/bmini-app`，**一端双编译** ⇒ weapp 与 h5 产物同一份门）与 admin-web 端都从 `GET /api/auth/me` 的 `capabilities.mibaoChat` 取值、都挂上同一形态的门；未授权时**不创建会话、不拉会话列表**（避免「页面看起来正常、一发消息什么都没有」的静默形态）。红证：只在其中一端加门 ⇒ 红。证据：frontend/admin-web/tests/unit/pages/chat-page.test.tsx 的授权门两格。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 pytest（tests/unit_ci_workflows/test_mibao_chat_gate.py）+ JUnit（backend/admin-api/src/test/java/com/migao/admin/security/AdminGateTest.java）+ jest/vitest（frontend/bmini-app/tests/mibao-access-gate.test.tsx、frontend/admin-web/tests/unit/components/MibaoAccessGate.test.tsx、frontend/admin-web/tests/unit/pages/chat-page.test.tsx）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'auth', 'permission', 'mibao-gate', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-009 [NORMAL] 管理面手机端 4 项（智能派单 / 入库过账 / 售后处理 / 计件工资报表）- h5 可用 + 权限双面 + 写动作护栏 + 与 PC 同源（源: cases/bmini.yml）──
_CASE_BM_009 = EvalCase(
    id='BM-009',
    legacy_id='',
    title='管理面手机端 4 项（智能派单 / 入库过账 / 售后处理 / 计件工资报表）- h5 可用 + 权限双面 + 写动作护栏 + 与 PC 同源',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['管理员用手机浏览器（h5）打开「我的」→ 智能派单 / 入库过账 / 售后处理 / 计件工资报表：排产派单可勾选并预览成批方案后一键派单；入库单可看详情并对草稿单过账；售后工单可看详情并按状态机推进；计件报表按人/按工序出数'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**4 项端到端可用**（每项至少一条）：① 智能派单——池+加急插区上屏 → 勾选 → 预览（服务端五个米数原样渲染）→ 二次确认 → `POST /api/admin/production/pool/dispatch`（成批 `pooled:true`；**加急单 = 单订单 + `pooled:false`**）；② 入库过账——列表 → 点卡拉详情 → 草稿单出「过账」→ 二次确认 → `PATCH /api/admin/inbound-orders/{id}` `{action:'post'}` → 刷新；③ 售后处理——列表 → 详情（含状态历史）→ **只出状态机允许的下一步** → 二次确认 → `PUT /api/admin/after-sales/{id}/status`；④ 计件工资——`GET /api/admin/production/piecework/summary?period=YYYY-MM` 四块渲染 + 期间切换。证据：frontend/bmini-app/tests/admin-pool-dispatch.test.tsx / admin-inbound-post.test.tsx / admin-after-sales.test.tsx / admin-piecework.test.tsx", '判据 2·**权限拒绝有文案（双面）**：无对应码 ⇒ ①「我的」页入口**不可见**；🔴 **2026-10-08 改判（issue #6570，用户裁定「走 B」）**：菜单可见性改由**服务端按岗位投影**（`GET /api/auth/me` 的 `mobileSurfaces`，服务端 `MobileSurfaces.visibleFor`），端侧不再自己判码；**菜单拉不到 ⇒ 显式「菜单没加载出来，点这里重试」+ 一个面都不渲染**（旧口径「集合未知 ⇒ 照显（fail-open）」已废 —— 它的实际形态是员工点进去逐项 403，线上读数见 issue #6570）；② 端点 403 ⇒ 页面逐字「无「XX」…权限（需要权限码 …）」（如「无「入库过账」过账权限（需要权限码 inbound:create）」），**不许空白/转圈**。红证：去掉 forbidden 分支 ⇒ admin-pool-dispatch.test.tsx 的 403 用例当场红（实测退出码 1）。证据：frontend/bmini-app/tests/admin-surfaces-permission.test.tsx + admin-surfaces-service.test.ts', '判据 3·**权限码真值在后端注解**：端侧台账（`ADMIN_SURFACES[].readPermission/writePermission`）与 4 个 Controller 的 `@RequirePermission` **逐值相等**（读：processing:view / inbound:view / after_sales:view / production:view（issue #5675 起 —— 该端点是「计件工资」页第一屏读端点，台账随后端注解同步）；写：processing:update / inbound:create / order:refund）。红证：改台账任一码 ⇒ 守卫判据 5 红。证据：frontend/bmini-app/tests/admin-surfaces-guard.test.ts', '判据 4·**h5 下不调 `Taro.login`**（#5650 既有判据）：h5 编译目标下渲染 4 个管理面，`Taro.login` 一次都不被调；未登录 ⇒ 明说「浏览器环境不支持微信登录，请用「用户名@企业编码 + 密码」登录」并给「去登录」。红证：在池页渲染路径注入 `Taro.login()` ⇒ 运行时判据 + 类级守卫**同时**红（实测退出码 1）。证据：frontend/bmini-app/tests/admin-surfaces-permission.test.tsx + admin-surfaces-guard.test.ts', '判据 5·**平台能力缺口显式**（类级）：射程内实测的 Taro API 集必须**逐值等于**声明集（当前 = `redirectTo` / `showModal`，均 h5 可用），命中 #5650 的两张清单（h5 未实现 / 只走微信 JS-SDK）⇒ 必须在缺口台账登记文案**且由真的调用它的文件接线**。红证：注入 `Taro.login` 不同步声明 ⇒ 判据 2 红；补声明+登记文案但不接线 ⇒ 判据 3 红（两条实测退出码均为 1）。证据：frontend/bmini-app/tests/admin-surfaces-guard.test.ts', '判据 6·**计件报表与 PC 端同源（不重算）**：手机端与 `/production/piecework` 读**同一个端点、同一份服务端聚合**；页面渲染服务端 `total`。判据夹具刻意让 `per_worker` 之和（1200）≠ `total`（1234.56）⇒ 显示 1234.56 才说明没本地求和。红证：把 `data.total` 换成 Σ`per_worker` ⇒ 显示 1200.00 ⇒ 当场红。证据：frontend/bmini-app/tests/admin-piecework.test.tsx', '判据 7·**写面护栏**：派单 / 过账 / 工单流转三个不可逆动作都有二次确认 —— 弹窗取消 ⇒ **一次都不调**写端点（红证：去掉确认分支 ⇒ admin-inbound-post 用例红）；失败**显式上屏**（派单逐单 `success:false` / 过账 422 / 状态机拒绝的中文文案都逐字透出，不静默）。证据：同判据 1 的四个测试文件', '判据 8·**不新增后端逻辑**：本单 diff **零** `backend/**` 改动（4 项端点全部既有）；登记**既有分歧**（本单不改后端、不改 admin-web）：admin-web 菜单节点码与端点码不一致（智能派单节点 `processing:manage` vs 读端 `processing:view`）⇒ 手机端一律以**端点码**为可见性判据（宁可不出死页）。🔴 **2026-09-27 改判（issue #5675）**：原登记的第二处「计件节点 `production:view` vs 端 `processing:manage`」**已收口**（该端点是「计件工资」页第一屏读端点，形态 = 菜单节点码 ≠ 该页第一屏读端点码 ⇒ 端点码改挂 `production:view`，本台账镜像同步）⇒ 本格的既有分歧**由两处缩到一处**，只剩智能派单那条（#5675 复算后判为**有意保留**：两个方向的对齐都会改变某个岗位集合的可见性或可做性，已具名登记在 `tests/unit_ci_workflows/test_agent_permission_parity.py` 判据 12 的残留台账）。'],
    skip_reason='[backend-contract] 确定性契约/机械判据，由 jest（frontend/bmini-app/tests/admin-surfaces-guard.test.ts / admin-surfaces-service.test.ts / admin-surfaces-permission.test.tsx / admin-pool-dispatch.test.tsx / admin-inbound-post.test.tsx / admin-after-sales.test.tsx / admin-piecework.test.tsx）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'admin-surface', 'permission', 'h5', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-010 [NORMAL] 入库标签 50×80mm 像素口径 - 单一真值（400/384/640/8 dots/mm），别处出现第二份字面量即红（源: cases/bmini.yml）──
_CASE_BM_010 = EvalCase(
    id='BM-010',
    legacy_id='',
    title='入库标签 50×80mm 像素口径 - 单一真值（400/384/640/8 dots/mm），别处出现第二份字面量即红',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍照入库出标签时，设备侧（客户端 canvas）按 **50×80mm 竖版**（2026-10-26 用户裁定改尺寸）的**点阵口径**出图：203dpi = 8 dots/mm、纸宽 50mm ⇒ 400px、纸高 80mm ⇒ 640px；**有效打宽 = 打印头宽 384px**（50mm 纸宽于 48mm 头 ⇒ 右侧约 2mm 打不到），1:1 不缩放不裁切'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**逐值正确 + 派生自洽**：`dotGeometry` 的 dpi=203、dotsPerMm=8，且 `widthPx == dotsPerMm×50`、`heightPx == dotsPerMm×80`、`headWidthPx == dotsPerMm×48`、`effectiveWidthPx == min(纸宽, 打印头宽)`（孤立的数不算数；红证：把 headWidthPx 记成纸宽、或 dotsPerMm 改成 8.47、或 heightPx 按 70mm 画 ⇒ 各自判红）。证据：frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts', '判据 2·**单一真值**：全仓 `384`（打印头宽）**只出现在** `frontend/admin-web/src/lib/print-media.json`（#5651 的介质矩阵）；240 / 320 与无关业务重号 ⇒ 改按**出图链路**逐字面量判（「只写一个数」也算，这正是旧口径漏掉的形态）。bmini 侧由 `frontend/bmini-app/src/utils/inbound/truth.ts` **跨工程直接 import 同一份文件**，不复制、不做构建期拷贝（红证：在渲染器里复制一份 384 ⇒ 实测判红）。', '判据 3·**渲染模块零像素字面量**：labelLayout.ts / labelCanvas.ts / truth.ts 去注释后不出现 240/320/384（只能从真值源取）。', '判据 4·**待实测显式登记**：`label-50x80` 介质 `measurement = pending-field-measurement` 且 `pendingMeasurements ≥ 3`（**DP235S** 的打印头 dpi / 有效打印宽度、间隙定位、原点偏移与出纸方向等真机参数**未核实** ⇒ 按安全侧设计，不把推定值写成实测值）。', '判据 5·**判据自身排除在语料外**（B1）：守卫文件自己会写 384/240，必须显式排除，否则判据永远红或永远抓不到真违规。'],
    skip_reason='[backend-contract] 确定性契约判据（jest: frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'label', 'single-source'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-011 [NORMAL] 入库标签短码口径 - 与 WorkerShortLinkService / WorkerInbound 控制器逐值一致（端点/头名/字母表）（源: cases/bmini.yml）──
_CASE_BM_011 = EvalCase(
    id='BM-011',
    legacy_id='',
    title='入库标签短码口径 - 与 WorkerShortLinkService / WorkerInbound 控制器逐值一致（端点/头名/字母表）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人端消费 `/api/worker/inbound/**`：上传 / 识别 / 建草稿 / 过账 / 按短码读详情 / 打印留痕；请求头幂等键名为 `Idempotency-Key`（逐字等于后端常量），短码 = 8 位、字母表 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`（生成面不产出 I/L/O/U）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**端点字面量逐值来自后端 Java 源**（不是按语义推测）：端侧 6 个端点路径 ⊆ 三个控制器的 `@RequestMapping` + 方法映射，且**反向覆盖**（后端有而端侧漏 ⇒ 红）。红证：把 `drafts` 写成 `draft` ⇒ 判据红（实测退出码 1）。证据：frontend/bmini-app/tests/inbound-api-contract.test.ts', '判据 2·**HTTP 方法一致**（GET 详情读面写成 POST ⇒ 405）：从 service 源码就近取每个端点常量实际用的方法，与后端注解比对。', '判据 3·**幂等头名逐字**：`INBOUND_IDEMPOTENCY_HEADER` == `WorkerInboundController.IDEMPOTENCY_HEADER`（写成报工链的 `X-Client-Request-Id` ⇒ 幂等**静默失效**，重复提交真的入两次库而两次都 200）。', '判据 4·**短码字母表 / 长度逐值**：`SHORT_CODE_ALPHABET` / `SHORT_CODE_LENGTH` == `WorkerShortLinkService.ALPHABET` / `CODE_LENGTH`，且不含 I/L/O/U（客户端只校验、不生成）。', '判据 5·**回执形状两侧一致**（issue #6864，线上 P0）：上传端点的 `ApiResponse<T>` 的 `T` 是**容器**（`List<UploadedFileInfo>`，后端用例逐字断言 `$.data[0].url`）⇒ 端侧必须做容器归一化；同族其余 5 个端点为**对象**。红证：端侧按对象读 `data.url`（修复前形态）= 每一次上传都报「照片上传失败，请重试」而服务端其实成功落 OSS（2026-10-14 线上实测）；把 `upload` 的返回类型改成对象而端侧没跟上亦 ⇒ 红。证据：frontend/bmini-app/tests/inbound-api-contract.test.ts（判据 C6）+ frontend/bmini-app/tests/worker-inbound-upload-receipt.test.ts'],
    skip_reason='[backend-contract] 确定性契约判据（jest: frontend/bmini-app/tests/inbound-api-contract.test.ts 解析后端 Java 源逐值比对），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-012 [NORMAL] 入库标签版面（50×80 竖版）- 去顶部品名 / 印入库日期 / 色号不遮挡 / 二维码在底部居中 / 缺码不画假码 / 1:1 不缩放（源: cases/bmini.yml）──
_CASE_BM_012 = EvalCase(
    id='BM-012',
    legacy_id='',
    title='入库标签版面（50×80 竖版）- 去顶部品名 / 印入库日期 / 色号不遮挡 / 二维码在底部居中 / 缺码不画假码 / 1:1 不缩放',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['标签纸面渲染（**50×80mm 竖版**，2026-10-26 用户裁定）：自上而下 = 货号 → 色号/门幅（全宽、两行内放下）→ 米数 → 批次/单号/入库日期/缸号/送单 → 分隔线 → 二维码（居中）→ 短码；**顶部不印品名**；短码缺失或脏码（长度不对 / 含 I L O U）时**不画二维码**、留空位并印可见标注；其余超宽文本**截断 + 省略号**'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**缺码不画假码**：`shortCode` 为空 / 非法 ⇒ `qr === null`、纸面出现可见标注「短码缺失·未出码」、warnings 含「未绘制二维码」；paint 计划里**没有任何二维码方块**（红证：改成画占位二维码 ⇒ 实测判红）。证据：frontend/bmini-app/tests/inbound-label-layout.test.ts', '判据 2·**色号不遮挡 + 超宽才可见截断**：色号/门幅走**全宽**，两行内放下（先缩字号 26→23→20），放得下就**一字不截**、不出省略号；只有实在放不下才 ⇒ 省略号 + `truncated=true` + warnings（红证：按旧的「半版心」宽度排 ⇒ 色号必截断，实测判红）。证据：frontend/bmini-app/tests/inbound-label-layout.test.ts（C2）', '判据 3·**1:1 不缩放不裁切**：画布尺寸 = 版心 384×640（从真值源取），所有绘制 op 落在版心内、文本不越界；渲染出的位图宽高 == 计划宽高。', '判据 4·**二维码整数倍点阵**：`sizePx == moduleCount × cellPx`（cellPx 为整数、≥1），点阵非空（防「画了个空方框」）。', '判据 5·**缺字段不编造 + 顶部无品名**：没有的字段整行不画（批次 / 单号 / 入库日期都适用）；**顶部不再印商品名**（用户逐字「移除顶部的商品名」），纸面第一行是货号。证据：frontend/bmini-app/tests/inbound-label-layout.test.ts（C6）', '判据 6·**增加入库日期**：`inboundDate`（服务端 `InboundLabelView.inboundDate`，= 收货日期）原样印成「入库 YYYY-MM-DD」；该字段为空 ⇒ 整行不画（不编造）。证据：frontend/bmini-app/tests/inbound-label-layout.test.ts（C7）', '判据 7·**二维码在底部且水平居中**：`qr.y > 纸高 × 0.5`、左右留白差 ≤ 2px、所有文字行都在二维码上方、短码在二维码下方（用户逐字「可以把二维码放到底部」）。证据：frontend/bmini-app/tests/inbound-label-layout.test.ts（C8）'],
    skip_reason='[backend-contract] 确定性版面判据（jest: frontend/bmini-app/tests/inbound-label-layout.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'label'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-013 [NORMAL] 识别成本守卫 - 照片含可解条码时 0 次 LLM 调用（先本机解码，只上传 1 张并带上条码原文）（源: cases/bmini.yml）──
_CASE_BM_013 = EvalCase(
    id='BM-013',
    legacy_id='',
    title='识别成本守卫 - 照片含可解条码时 0 次 LLM 调用（先本机解码，只上传 1 张并带上条码原文）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍上游标签 → 设备侧先解码（jsQR）：解出条码 ⇒ 只把**解出码的那一张**上传并带 `barcode` 调 `/api/worker/inbound/recognize`（服务端走 `barcode_decode` 路径，零 LLM）；解不出 ⇒ 全量上传（≤3 张）不带条码，服务端 vision 兜底'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**解码命中 ⇒ llmCalls == 0**（假服务端复刻服务端语义：`barcode` 非空才不调模型）、上传恰好 1 张、请求里 `barcode` 非空。红证：把识别排到解码之前 ⇒ 假服务端计数 = 1 ⇒ 判据红（实测退出码 1）。证据：frontend/bmini-app/tests/inbound-decode-first.test.ts', '判据 2·**解码失败 ⇒ 全量上传（≤3）+ 不带 barcode**（服务端 vision 兜底，1 次 LLM），且超过 3 张时端侧先截断（不让工人白等一次 400）。', '判据 3·**解码库真能解出码**：真跑 encode（qrcode-generator）→ decode（jsQR）往返，解出原文；纯白图必须解不出（防「永远返回第一个参数」式假实现）。', '判据 4·**过程不静默，但不摆过程**（issue #7818，用户 2026-10-26 逐字「为什么会出现，移除掉」）：解码没命中而服务端 vision 认回来了 = **正常路径** ⇒ 本链**不回传任何上屏文案**（`RecognizeFlowResult` 没有 `notices`）；「要不要人工核对」由**确认卡**说清（服务端 `message` 原样上屏）。红证：把两条 notices 的 push 加回 `recognizeFlow` ⇒ 本单两处判据**同时红**（实测 2 failed / 21 passed）。证据：frontend/bmini-app/tests/inbound-decode-first.test.ts（C4）+ frontend/bmini-app/tests/worker-inbound-page.test.tsx（C13）', '⚠️ weapp 侧本机解码需 `Taro.createOffscreenCanvas`，**本机无小程序运行时 ⇒ 未实测**；取不到像素 ⇒ 返回 null ⇒ 回落服务端 vision（失败方向安全），文案已在 `H5_API_OUTLET_LEDGER` + 本页缺口台账登记并被调用点引用。'],
    skip_reason='[backend-contract] 确定性成本守卫判据（jest: frontend/bmini-app/tests/inbound-decode-first.test.ts，含 qrcode→jsQR 真往返），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'cost-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-014 [NORMAL] 打印必留痕 - 送打印的唯一入口先调服务端 /print；留痕失败不打印；前端不自行计数（源: cases/bmini.yml）──
_CASE_BM_014 = EvalCase(
    id='BM-014',
    legacy_id='',
    title='打印必留痕 - 送打印的唯一入口先调服务端 /print；留痕失败不打印；前端不自行计数',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人点「打印标签」：先调 `POST /api/worker/inbound/labels/{短码}/print`（计数原子自增 + audit_logs），服务端回执成功**才**把位图送给打印机；纸上/屏上的「第几次」一律取服务端回执'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**顺序硬约束**：调用序 = render → **recordPrint** → transport（红证：交换成先送数据再留痕 ⇒ 判据红，实测退出码 1）。证据：frontend/bmini-app/tests/inbound-print-channel.test.ts', '判据 2·**留痕失败 ⇒ 一次都不送数据**（不产生无痕打印）；回执里 `printRecorded:false` 说清。', '判据 3·**前端不自行计数**：两次不同服务端读数（7 / 12）原样转发，不做本地 +1；源码面判据：入库模块里不存在对 `printCount` 的算术（红证：本地 +1 ⇒ 行为判据与源码面判据同时红）。', '判据 4·**渲染失败 ⇒ 中止且未留痕**（画不出来就不该占一次计数）。', '判据 5·**送数据失败要说清「留痕已发生」**（重打会再记一次，不骗工人）。'],
    skip_reason='[backend-contract] 确定性留痕判据（jest: frontend/bmini-app/tests/inbound-print-channel.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'print', 'audit'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-015 [NORMAL] 打印能力缺口 - 每种失败各有可行动文案，且动手前上屏（iOS / 非 HTTPS / 无蓝牙 / 非 h5 / SDK 缺失 / 取消 / 连不上 / 机型不支持）（源: cases/bmini.yml）──
_CASE_BM_015 = EvalCase(
    id='BM-015',
    legacy_id='',
    title='打印能力缺口 - 每种失败各有可行动文案，且动手前上屏（iOS / 非 HTTPS / 无蓝牙 / 非 h5 / SDK 缺失 / 取消 / 连不上 / 机型不支持）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人用手机打开入库页：iOS 任何浏览器 / 非 HTTPS 地址 / 浏览器无 Web Bluetooth / 小程序端 / 打印组件加载失败 / 用户取消选择 / 连不上 / 机型不支持 —— 每一种都要说清「为什么」与「现在能做什么」，并在**动手前**（拍照之前）就把本机能不能打印说清楚'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**逐种文案两两不同、非空、可行动**（红证：合并成一条通用文案 ⇒ 判据红，实测退出码 1）：iOS ⇒ 点名 iPhone/iPad 并给「换安卓或电脑端补打」；非 HTTPS ⇒ 点名 https 入口；无 API ⇒ 点名 Android/桌面 Chrome；非 h5 ⇒ 点名小程序链路搁置 + 换 Chrome；SDK 缺失 ⇒ 保持联网刷新；取消 ⇒ 说明计数已记一次；连不上 ⇒ 开机/3 米内/别被占用；机型不支持 ⇒ 选 DP 开头；打印失败 ⇒ 查纸仓；渲染失败 ⇒ 不会打空白标签。证据：frontend/bmini-app/tests/inbound-print-channel.test.ts', '判据 2·**探测顺序**：iOS 判在「无 Web Bluetooth」**之前**（iPhone 上换任何浏览器都不行 ⇒ 先判无 API 会把人引向走不通的动作）；`isSecureContext` 缺失按**不安全**处理（fail-closed）。', '判据 3·**动手前上屏**：页面在拍照步之前就渲染能力探测结论（`data-testid=inbound-print-capability` 出现在 step 分支之外）；iOS 环境下一进页面（**零操作**）就能看到该文案，且此时未调用任何服务端端点（红证：把横幅挪进「打完失败后」⇒ 判据红）。证据：frontend/bmini-app/tests/worker-inbound-page.test.tsx + tests/inbound-page-platform-gaps.test.ts（判据 G5 按源码位置断言）', '⚠️ 真机（DP30S）打印**未验证**（本机无该机型 / 无 Android 蓝牙环境）⇒ 传输层做成可注入接口，判据全部跑在替身上；重启条件见 PR 正文。'],
    skip_reason='[backend-contract] 确定性能力缺口判据（jest: frontend/bmini-app/tests/inbound-print-channel.test.ts + worker-inbound-page.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'print', 'platform-gap'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-016 [NORMAL] 拍照入库页类级守卫 - 声明==实测 / 平台缺口登记且接线 / h5 不调 Taro.login / 路由登记（源: cases/bmini.yml）──
_CASE_BM_016 = EvalCase(
    id='BM-016',
    legacy_id='',
    title='拍照入库页类级守卫 - 声明==实测 / 平台缺口登记且接线 / h5 不调 Taro.login / 路由登记',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['拍照入库页（`/pages/worker/inbound/index`）的平台能力面：射程内用到的 Taro API 必须逐值等于声明集；命中 #5650 两张清单（h5 未实现 / 只走微信 JS-SDK）的 API 必须在台账登记出路**且被调用点真的引用**；h5 下不得调 `Taro.login`'],
    expectations=['direct_reply'],
    data_checks=['判据 G0·**路由登记**：`INBOUND_PAGE_ROUTE` 逐字出现在 `src/app.config.ts` 的 pages 里（没登记 = 死链），页面 / 页面配置 / 工人登录页都在。', '判据 G1·**声明 == 实测（双向）**：射程内实测 `Taro.*` 集 == `INBOUND_PAGE_TARO_APIS`（红证：页面加一处未声明的 `Taro.showToast` ⇒ 红，实测退出码 1）。', '判据 G2·**缺口必须接线**：本页命中清单的 `createOffscreenCanvas` 在 `H5_API_OUTLET_LEDGER`（#5650 全局台账）与 `INBOUND_PAGE_PLATFORM_GAP_HINTS`（本页台账）**两处**都登记，且文案出现在**射程内真的会渲染它的文件**里（只登记不接线 ⇒ 红）。', '判据 G3/G4·**台账只许缩短且条目活着**（射程里已不存在的 API 不得留在台账）、文案非占位（≥10 字）。', '判据 G5·**打印能力探测在动手前上屏**（源码位置判据）+ 每条失败原因都点名了引用它的文件。', '判据 G6·**h5 不调 `Taro.login`**、页面不碰 `/api/admin/**`（去注释后判定：注释里的解释不算违规）。证据：frontend/bmini-app/tests/inbound-page-platform-gaps.test.ts'],
    skip_reason='[backend-contract] 类级元守卫（jest: frontend/bmini-app/tests/inbound-page-platform-gaps.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-017 [NORMAL] SKU 匹配门禁与预填口径 - 零命中拒绝入库不建品 / 不确定不预填 / 多命中工人消歧 / 数量口径唯一真值在服务端（源: cases/bmini.yml）──
_CASE_BM_017 = EvalCase(
    id='BM-017',
    legacy_id='',
    title='SKU 匹配门禁与预填口径 - 零命中拒绝入库不建品 / 不确定不预填 / 多命中工人消歧 / 数量口径唯一真值在服务端',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['识别回执到达页面后：命中既有 `product_skus` ⇒ 预填并请工人核对；零命中 ⇒ 拒绝入库、不自动建品；多命中 ⇒ 工人自己选；vision 降级 / requiresManualEntry ⇒ 三格全空、提示手输'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**零命中 ⇒ none**（文案含「不会自动建品」）+ 提交闸拒绝（没有 skuId 就不放行，只有 productId 也不放行）。红证：允许无 sku 提交 ⇒ 红（实测退出码 1）。证据：frontend/bmini-app/tests/inbound-sku-gate.test.ts', '判据 2·**不确定不预填**：`degraded` / `requiresManualEntry` / 零命中 ⇒ `prefillUsed=false` 且品名/色号/米数三格全空 + 可行动提示（红证：让降级分支也预填 ⇒ 判定函数判红）。', '判据 3·**多命中由工人消歧**：返回 `ambiguous` 且不自动取第一条；唯一命中才预选（仍要核对）。', '判据 4·**端侧只拦结构上不可能成功的**（缺 SKU / 缺米数 / 未勾选「我确认」）；数值口径**唯一真值在服务端**（`> 0` 且最多 1 位小数，超 1 位显式拒绝），端侧不重写第二份（源码面：recognizeGate.ts 无 Number(/parseFloat/toFixed/小数位正则），400 文案原样上屏）。', '判据 5·**「不自动建品」是结构事实**：入库射程内不存在任何建商品 / 建 SKU / 改库存的调用（红证：加一个 `POST /api/admin/products` ⇒ 红）；建草稿请求体结构上无 `adjustment`/`delta`/`setStock`/`operator`/`tenantId`。'],
    skip_reason='[backend-contract] 确定性门禁判据（jest: frontend/bmini-app/tests/inbound-sku-gate.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'sku-gate'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-018 [NORMAL] 拍照入库页链路 - 工人身份分流（无 session 明说去登录）+ 过账二次确认（取消即不建单）（源: cases/bmini.yml）──
_CASE_BM_018 = EvalCase(
    id='BM-018',
    legacy_id='',
    title='拍照入库页链路 - 工人身份分流（无 session 明说去登录）+ 过账二次确认（取消即不建单）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人（有工号 + PIN 的 worker session）在手机浏览器打开入库页：拍照/选图 → 识别 → 核对并勾选「我确认」→ 点「提交过账」→ 二次确认 → 建单并过账 → 出标签 → 送打印；没有工人 session 时页面明说去登录工人身份'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**身份分流**：无工人 session ⇒ 渲染「请先用工号 + PIN 登录工人身份」引导且**不渲染拍照入口**；点引导 ⇒ `Taro.navigateTo` 到工人登录页（不静默跳走、不静默失败）。证据：frontend/bmini-app/tests/worker-inbound-page.test.tsx', '判据 2·**过账二次确认（不可逆动作护栏）**：弹窗取消 ⇒ `createInboundDraft` / `postInboundDraft` **一次都不被调**；确认 ⇒ 各恰好一次，且建单请求体只含入库语义（dyeLot/productId/quantity/remark/skuId/supplier/supplierDocNo —— 无 adjustment/operator/tenantId）。红证：去掉确认分支 ⇒ 取消用例红（实测退出码 1）。', '判据 3·**服务端 400 的文案原样上屏**（数量口径真值在服务端）：建单被拒 ⇒ 屏上逐字出现服务端 message，且**不继续过账**（不产生半张单）。', '判据 4·**h5 下不调 `Taro.login`**（工人身份走工号 + PIN）。', '判据 5·过账后短码上屏（工人可抄），标签步渲染 50×30mm 版心（= 有效打宽 × 纸高）。'],
    skip_reason='[backend-contract] 确定性页面链路判据（jest: frontend/bmini-app/tests/worker-inbound-page.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'page-flow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-019 [NORMAL] 工号+PIN 登录页在 h5 可用 - 拍照入库的登录前置在浏览器下走得出（不依赖微信换码）（源: cases/bmini.yml）──
_CASE_BM_019 = EvalCase(
    id='BM-019',
    legacy_id='',
    title='工号+PIN 登录页在 h5 可用 - 拍照入库的登录前置在浏览器下走得出（不依赖微信换码）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人首次在手机浏览器打开拍照入库页（无 worker session）→ 页面引导去工人登录页 → 用「工号 + PIN」登录成功后回到入库页'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**登录前置在 h5 走得通**：工人登录页的提交路径不调用 `Taro.login`（`H5_API_OUTLET_LEDGER` 的 `login` 条目：h5 不走微信换码，直接拒绝并指向账号密码登录）⇒ 浏览器下能拿到 worker session，才谈得上入库。证据：frontend/bmini-app/tests/worker-inbound-page.test.tsx（判据 4）+ tests/h5-platform-api-guard.test.ts', '判据 2·**未登录不静默**：入库页在没有 worker session 时给出可行动文案与入口（不空白页、不转圈、不静默跳转）。', '⚠️ 关联阻塞（照实登记，不在本单）：工人档案创建（#4869）未闭环前，真实部署里第一个工人建不出来 ⇒ 本链在 POC 阶段需要开发手段直插一条工人档案。'],
    skip_reason='[backend-contract] 确定性平台/前置判据（jest: frontend/bmini-app/tests/worker-inbound-page.test.tsx + tests/h5-platform-api-guard.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'login', 'platform'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-020 [NORMAL] 拍照补打标签·第一跳 - 解码优先（0 次 LLM 调用）且只有入库码才去查单据详情（源: cases/bmini.yml）──
_CASE_BM_020 = EvalCase(
    id='BM-020',
    legacy_id='',
    title='拍照补打标签·第一跳 - 解码优先（0 次 LLM 调用）且只有入库码才去查单据详情',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人登录 B 端（H5 / 小程序）后打开「拍照补打标签」→ 拍一张观星台入库标签 → 本机解码优先（jsQR，**0 次 LLM**）→ 解出短码后按短码读单据详情'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**解码优先、0 次 LLM**：`runReprintResolve` 的 `expectedLlmCalls === 0`，且假服务端的 `llmCalls` / `recognizeCalls` 均为 0；补打链的依赖里**没有**上传/识别回调（结构事实：解不出码的正确答案是「重拍 / 手输」，不是「让模型猜单」）。红证（对照实跑）：复刻「先问模型」⇒ 同一个假服务端立刻记 1 次 LLM 调用。证据：frontend/bmini-app/tests/inbound-reprint-flow.test.ts', '判据 2·**是真解码**：qrcode-generator 编码 → jsQR 解码真往返，解出 `https://app.migaozn.com/i/<短码>`（不是替身对替身）。', '判据 3·🔴 **只有入库码才查详情**：`/s/` 洗水码与陌生二维码 ⇒ `lookup` **一次都不调用**（`detailCalls === []`），状态是 `blocked` 而不是 404。红证（变异注入实跑退出码 1）：把 `loadReprintDetail` 的码空间门禁改掉 ⇒ 判据红。', "判据 4·**解码失败不猜单**：`route === 'manual-required'`、短码为 null、屏上给重拍要点 + 手输入口（不预填任何单据字段）。"],
    skip_reason='[backend-contract] 确定性成本守卫与门禁判据（jest: frontend/bmini-app/tests/inbound-reprint-flow.test.ts + tests/inbound-reprint-code-space.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'reprint', 'cost-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-021 [NORMAL] 码空间分清 - /s/ 洗水码绝不当入库标签查（给报工入口）；非观星台二维码明确告知（源: cases/bmini.yml）──
_CASE_BM_021 = EvalCase(
    id='BM-021',
    legacy_id='',
    title='码空间分清 - /s/ 洗水码绝不当入库标签查（给报工入口）；非观星台二维码明确告知',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍到的码有两种可能：入库标签 `https://app.migaozn.com/i/<短码>`（承载入库单）与洗水码 / 报工短链 `https://app.migaozn.com/s/<短码>`（302 → 报工页，承载加工部位）。两者的短码规格**故意同款**（8 位 Crockford Base32）—— 同款是为了人可读可抄，不是为了可以互相串。另有一种：根本不是观星台的二维码'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **`/s/` ⇒ 洗水码空间**：判定为 `wash-code`、文案点明「水洗唛上的报工码」并给出**报工页入口**（路由已登记进 `src/app.config.ts`），且**不查入库详情**（页面判据：`getInboundLabel` 0 次调用）。红证（变异注入实跑退出码 1）：不看码空间、拿 URL 末段直接查 ⇒ 判据红。证据：frontend/bmini-app/tests/inbound-reprint-code-space.test.ts + tests/worker-reprint-page.test.tsx', '判据 2·**非观星台二维码明确告知**：别的域名的 `/i/<码>`、纯文本二维码 ⇒ `foreign` + 「这不是观星台的标签」+ 引导手输；**绝不**拿去查入库接口（红证：变异注入「认路径不认主机」⇒ 判据红，退出码 1）。', "判据 3·**前缀单一来源**：`/s/` 在端侧只出现一处（`src/utils/inbound/codeSpace.ts`），且与后端控制器 `@GetMapping('/s/{shortCode}')`、`@GetMapping('/i/{shortCode}')` **逐值一致**（红证：客户端另抄一份前缀 / 后端换前缀 ⇒ 判据红）。", '判据 4·**类级元守卫（两套码空间被当成一套用）**：「谁可以查入库详情」有台账（`LABEL_DETAIL_CALLERS`）—— 未登记即红、条目必须活着、受门禁的调用点必须引用码空间判定。证据同上（同文件的 G1/G2）。'],
    skip_reason='[backend-contract] 确定性码空间判据（jest: frontend/bmini-app/tests/inbound-reprint-code-space.test.ts 等），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'reprint', 'code-space'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-022 [NORMAL] 手输短码兜底 - 标签磨花时手输 8 位短码，抄错形态（O/I/L）原样交给服务端归一化（源: cases/bmini.yml）──
_CASE_BM_022 = EvalCase(
    id='BM-022',
    legacy_id='',
    title='手输短码兜底 - 标签磨花时手输 8 位短码，抄错形态（O/I/L）原样交给服务端归一化',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['标签磨花 / 破损 ⇒ 二维码根本解不出来（这就是补打的主场景）⇒ 工人照抄纸面上的 8 位短码并手输；抄写必然出错：`0` 抄成 `O`、`1` 抄成 `I/L`'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **抄错形态必须能解析**：`classifyManualCode('ABCDO234')` ⇒ `inbound-label` 且短码**原样**（客户端不做别名映射）；服务端 `WorkerShortLinkService.normalize`（`O→0`、`I/L→1`）归一化后仍能查到单据（假服务端逐字复刻该映射，断言拿到的 `shortCode` 是服务端归一化后的那一个）。红证（变异注入实跑退出码 1）：把客户端闸改成只认严格字母表（`isValidShortCode` 那种）⇒ 判据红，且页面判据同时红（**这个码永远送不到服务端**）。证据：frontend/bmini-app/tests/inbound-reprint-code-space.test.ts + tests/inbound-reprint-flow.test.ts + tests/worker-reprint-page.test.tsx", '判据 2·**客户端不归一化、不生成**：新文件里不存在 `O→0` / `I/L→1` 的映射，也不存在短码生成（生成面唯一写方 = 服务端 `allocateUniqueCode()`）。', '判据 3·**抄写分隔符容忍**：`ABCD 2345` / `abcd-2345` / 整条 `/i/` URL 粘进来 ⇒ 都能取到候选短码（大小写与别名一律留给服务端）。', '判据 4·**形态不合法 ⇒ 一次请求都不发**：非 8 位字母数字 ⇒ `invalid-input` + 「8 位」的可行动文案，`lookup` 0 次（红证：变异注入「去掉长度闸」⇒ 判据红，退出码 1）。'],
    skip_reason='[backend-contract] 确定性手输/归一化口径判据（jest: frontend/bmini-app/tests/inbound-reprint-code-space.test.ts 等），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'reprint', 'manual-entry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-023 [NORMAL] 补打详情与打印 - 404/410 分开呈现（查无此码 vs 已撤销）+ 打印必留痕且前端不自行计数（源: cases/bmini.yml）──
_CASE_BM_023 = EvalCase(
    id='BM-023',
    legacy_id='',
    title='补打详情与打印 - 404/410 分开呈现（查无此码 vs 已撤销）+ 打印必留痕且前端不自行计数',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍到 / 手输一张入库标签短码 → 页面展示服务端给的**单据详情**（品名 / 色号 / 门幅 / 米数 / 货号 / 缸号 / 批次 / 单号 / 供应商 / 已打印次数）→ 点「打印新标签」补打；短码不存在与已撤销会分别出现'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **404 / 410 分开**：跨租户 / 不存在 ⇒ `not-found`（「查无此码…核对纸面短码」）；已撤销 ⇒ `revoked`（「该标签已撤销…请文员按单据重新补打」）。两者是**两种状态、两句不同的话**，页面上是两个不同的块（`reprint-not-found` / `reprint-revoked`，实测两句文本不相等）；服务端建议（`ApiResponse.suggestion`）原样上屏。红证（变异注入实跑退出码 1）：把 410 也报成 404 ⇒ 判据红。证据：frontend/bmini-app/tests/inbound-reprint-flow.test.ts + tests/worker-reprint-page.test.tsx', '判据 2·**200 但无 data 不算 ready**（不返回空详情、不画假标签）⇒ `error` 态。', '判据 3·🔴 **打印必留痕**：补打的详情走**同一个** `printInboundLabel`（P3/P4 的唯一送打印入口），调用序 `render → recordPrint → transport`；留痕失败 ⇒ **一次都不送数据**；能力不可用 ⇒ 既不调留痕也不连蓝牙。红证（变异注入实跑退出码 1）：把 `recordPrint` 换成「自己造一个计数」 ⇒ 判据与 P3 的 D1 同时红。', '判据 4·**前端不自行计数**：两次不同服务端读数（3 / 9）原样转发，屏上显示服务端那次；源码面判据扫新增文件与页面（`printCount` 算术 ⇒ 红）。红证（变异注入实跑退出码 1）：页面写 `printCount + 1` ⇒ 行为判据与源码面判据同时红。', '判据 5·**字段真值只从服务端来**：屏上字段全部取自 `GET /api/worker/inbound/labels/{短码}` 的响应（端侧不拼第二份），短码以服务端归一化后的值为准。', '判据 6·**零后端改动**：本单只消费已合并的 P1/P2 端点（`INBOUND_ENDPOINTS` 与后端控制器逐值一致由既有守卫钉住），未新增任何端点。'],
    skip_reason='[backend-contract] 确定性详情/留痕判据（jest: frontend/bmini-app/tests/inbound-reprint-flow.test.ts + tests/worker-reprint-page.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'reprint', 'print', 'audit'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-024 [NORMAL] 同族页面不分叉 - 补打页复用 P3 的版面/渲染/打印件（类级元守卫）且 h5 不调 Taro.login（源: cases/bmini.yml）──
_CASE_BM_024 = EvalCase(
    id='BM-024',
    legacy_id='',
    title='同族页面不分叉 - 补打页复用 P3 的版面/渲染/打印件（类级元守卫）且 h5 不调 Taro.login',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['补打页（`pages/worker/reprint/index`）与入库页（`pages/worker/inbound/index`）是同族页面：都要把服务端详情渲染成 50×30mm 位图并送打印。判据要能拦住「复制一份而不复用」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **同族页面必须复用**：射程内渲染标签的页面（现为入库页 + 补打页）必须 ① 引用唯一送打印入口 `printInboundLabel`；② 不得自带第二份二维码版面（`qrcode(`）、不得直连传输层（`printImageData`）、不得手写端点字面量、不得自带像素/纸型字面量（纸型走 `inboundLabelPageSize()`）、不得对 `printCount` 做本地算术；③ 必须用共用画布工厂。红证（变异注入实跑退出码 1，逐条）：删掉 `printInboundLabel` 引用 / 页面自带第二份画布工厂 / 手写 `/api/worker/...` ⇒ 判据点名判红。证据：frontend/bmini-app/tests/inbound-reprint-code-space.test.ts（G3）+ tests/inbound-page-platform-gaps.test.ts', '判据 2·**画布工厂唯一定义处** = `src/utils/inbound/labelPageKit.ts`（全仓扫描）；入库页已改为引用同一份共用件（不再自带第二份）。', '判据 3·**版面/渲染/打印三件零改动**：`labelLayout.ts` / `labelCanvas.ts` / `labelPrint.ts` 在本分支**未被修改**（补打只换数据源：入参从「过账回执 + 详情」换成「扫到的短码 → GET …/labels/{短码}」）⇒ 「缺码不画假码」「长名截断可见」「1:1 送打印」由复用直接继承；若为补打改这三件，即证明该层抽取有误（本单未改）。', '判据 4·**页面的平台能力台账只有一份**：补打页与入库页共用 `INBOUND_PAGE_SCOPE_FILES` / 声明集（新增一处 `Taro.*` 而未声明 ⇒ 红）；两页路由都在 `src/app.config.ts` 登记（没登记 = 死链）。', '判据 5·**h5 不调 `Taro.login`**（#5650 判据）：页面与实测 Taro 集都不含 `login`。红证（变异注入实跑退出码 1）：页面加一处 `Taro.login` ⇒ 页面判据与平台守卫同时红。', '判据 6·**两平台都要能编译**：`npm run build:h5` 与 `npm run build:weapp` 均退出 0（CI 的 `bmini-app build (h5 + weapp)` 腿）。'],
    skip_reason='[backend-contract] 确定性复用/平台判据（jest: frontend/bmini-app/tests/inbound-reprint-code-space.test.ts + tests/inbound-page-platform-gaps.test.ts + 两平台构建腿），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'reprint', 'reuse-guard', 'platform'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-025 [NORMAL] 工人面两页的入口可达性 - 入口台账（未登记即红 / 登记了没人指向也红）（源: cases/bmini.yml）──
_CASE_BM_025 = EvalCase(
    id='BM-025',
    legacy_id='',
    title='工人面两页的入口可达性 - 入口台账（未登记即红 / 登记了没人指向也红）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人要拍照入库 / 补打标签时，他必须有一条真的能走到的入口（2026-10-10 起由**工人工作台**承载，`/w/` 报工页不再发射）；而「路由常量被声明、被 app.config 比对过、却没有任何跳转用它」必须被判红'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **未登记即红**：`src/app.config.ts` 里每个**非 tabBar** 页面都必须在 `src/utils/pageEntries.ts` 的 `PAGE_ENTRY_LEDGER` 具名（tabBar 页面按 `tabBar.list` 机械豁免，且不许登记 —— 登记它 = 台账里躺着一条假入口）。红证：给 app.config 加一个页面而不登记 ⇒ 判红（证据：frontend/bmini-app/tests/page-entry-reachability.test.ts 的 L2）', '判据 2·🔴 **登记了没人指向也红**：每条登记都必须在 `from` 里找到真导航形态（`Taro.navigateTo/redirectTo/switchTab/reLaunch` 或跨应用 `href`）**且**跳转里带着目标记号。红证（变异注入实跑）：把入口换回「只声明」（`from` 指向只写着路由常量的 `src/utils/inbound/gaps.ts`）⇒ 判红点名「声明存在 ≠ 可达」；删掉 `/w/` 上的 `<a href>` ⇒ 判红。这是本单要治的形态本身：两条路由常量被声明、被 `tests/inbound-page-platform-gaps.test.ts` 的 G0 比对过 `app.config.ts`，却没有任何跳转用它们（证据：同文件 L3）', '判据 3·**台账只许缩短**：条目对应的页面从 `app.config.ts` 消失 ⇒ 判红（条目必须活着）；`via` 为动态记号时 `viaBinding` 必须钉住「记号 ⇒ 路由」的绑定。红证：从 app.config 删掉补打页 / 把 viaBinding 指向无关文件 ⇒ 各自判红（证据：同文件 L0 / L4）', '判据 4·**跨应用入口已收敛**（2026-10-10 用户逐字「移除拍照入库和补打入库标签」，issue #6635）：`/w/` 报工页**不再**承载入库两页的 `<a>`（反向钉住：本页再出现 `/b/#/pages/worker/inbound|reprint` ⇒ 红）—— 可达性**没有丢**：那两页由**工人工作台** `src/pages/worker/home/index.tsx` 承载（台账 `from` 逐值核 + `nav` 形态 + L3b「写了 ≠ 会被执行」），且台账里**不再有** `nav: \'href\'` 条目。渲染面判据在 frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs（`renderPage` 的渲染结果；本页只留「裁高计算（一体机）」「返工记录」两条入口）+ 反向面在 frontend/bmini-app/tests/page-entry-reachability.test.ts 的 L5。🔴 **2026-10-27 再收窄（issue #7934）**：用户逐字「我的计件和发货…为什么做到报工详情页面？应该都作为工人菜单页面上的菜单」⇒ 本页连「我的计件」「发货」两条也撤除（反向钉住 `./piecework.html` / `./shipment.html` 出现即红，即使 `piecework` / `to_ship` 页面键开着）；两张静态页本身**保留可直连**（判据同文件 ④：文件 + 装配模块都在）。红证（实跑）：把 `<a href="./piecework.html">` 加回 `workerEntriesBar` ⇒ 4 failed（worker-h5-worker-entries 的 ② 与 worker-h5-pages 的 ①′ 各自具名）。', '判据 5·**平台缺口必须有登记且被真的接线**：`/b/?code=` 是 h5 专有形态（小程序没有 URL query），登记在 `src/utils/inbound/gaps.ts` 的 `WORKER_SURFACE_PLATFORM_GAPS`，`wiredBy` 的文件**代码**里必须真的出现 `wiredToken`（只登记不接线 ⇒ 红）', '判据 6·**两平台都要能编译**：`npm run build:h5` 与 `npm run build:weapp` 均退出 0（CI 的 `bmini-app build (h5 + weapp)` 腿）'],
    skip_reason='[backend-contract] 确定性入口/台账判据（jest: frontend/bmini-app/tests/page-entry-reachability.test.ts + node --test: frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs + 两平台构建腿），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'entry-reachability', 'meta-guard', 'worker-surface'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-027 [NORMAL] 商家 H5 登录可用：同源 API 面（同源 POST 不被 CORS 误判）+ 两入口（员工 / 管理员短信）+ 可读字号与触控目标（源: cases/bmini.yml）──
_CASE_BM_027 = EvalCase(
    id='BM-027',
    legacy_id='',
    title='商家 H5 登录可用：同源 API 面（同源 POST 不被 CORS 误判）+ 两入口（员工 / 管理员短信）+ 可读字号与触控目标',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家员工/管理员在手机浏览器打开 `https://app.migaozn.com/b/`：员工填「用户名@企业编码 + 密码」；管理员切到「管理员登录」填「手机号 + 验证码」。两条路都能登进去，且字号/触控目标随屏幕宽度合理缩放'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **同源请求不被判成跨域**（修复前线上 403 `Invalid CORS request`、前端只显示 `Load failed`、服务端零日志）：带 `Origin: https://app.migaozn.com` 的同源 POST 必须与不带 Origin 的同一请求同结果。实现 = backend/admin-api/src/main/java/com/migao/admin/security/SameOriginOriginHeaderFilter.java（按浏览器口径逐项比 scheme+host+port，代理不在场时退回本地视角 ⇒ 本地开发的真跨域不受影响）。红证：把 `isSameOrigin` 恒 false ⇒ SameOriginOriginHeaderFilterTest 8 条里 3 条红（实跑过）；还原即复绿', '判据 2·🔴 **H5 产物的 API/AI 基址与落地面同源**（跨域既要多一次预检、又要求白名单里有它；AI 面未配置时会 baked 成 `http://localhost:8001`）：判据 = tests/unit_ci_workflows/test_bmini_h5_delivery_contract.py 的 test_h5_api_base_is_same_origin_as_landing_surface（落地面取自发布后断言 step，不写死常量）。红证：改回 `https://api.migaozn.com` / 删掉 `TARO_APP_AI_API_URL` ⇒ 红（实跑过）', '判据 3·**「字号太小」这一类进不来**：h5 模板必须带响应式 root font-size（Taro rem 方案缺的另一半；修复前 root 从未设置 ⇒ 全端按设计值 40% 渲染、标签实测 5.2 CSS px），且 750 设计尺度字号下限 24px、台账**只许缩短**（现取 **0** —— issue #5769 收口后全库清零）。判据 = tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py + test_bmini_h5_delivery_contract.py；红证：写回 `font-size: 13px` / 删掉根字号脚本 / 下调 `MIN_FONT_SIZE` ⇒ 红（实跑过）', '判据 4·**触控目标与输入字号**：登录页交互件 ≥ 88 设计 px（≈45.8 CSS px，手指最小命中区 44 CSS px）、输入与按钮字号 ≥ 32（≈16.6 CSS px —— 输入框小于 16 CSS px 时 iOS 聚焦会放大整页）。实测 5 个视口（320/360/390/430/1024）全达标', "判据 6·🔴 **前端实际发的自定义头 ⊆ 两个后端的 CORS 逐项白名单**（issue #6479：两个 H5 端**每个**请求都带 `X-Client-Type`，而 admin-api `setAllowedHeaders` 与 ai-agent `allow_headers` 都没有它 ⇒ 预检不放行该头 ⇒ **真实请求根本不发出去**，前端只看到 `net::ERR_FAILED` / CORS 报错、**服务端零日志**；同一形态当年已在 `X-Worker-Session-Id` 上发生过，但**没有判据对账**，换个头名又来一次）。判据 = tests/unit_ci_workflows/test_cors_custom_headers_contract.py（扫 `frontend/*/src/**` **代码里**的 `X-*` 头字面量 ⊆ admin-api 清单 ∧ ⊆ ai-agent 清单，含反空跑金丝雀）。真栈复探：`curl -i -X OPTIONS http://127.0.0.1:8080/api/auth/me -H 'Origin: http://localhost:3000' -H 'Access-Control-Request-Method: GET' -H 'Access-Control-Request-Headers: authorization,x-client-type,content-type'` ⇒ 修前 `Access-Control-Allow-Headers: authorization, content-type`、修后含 `x-client-type`（实测）。红证：把 `X-Client-Type` 从任一侧白名单摘掉 ⇒ 具名报红（实跑过）", '判据 5·**两个入口各自可登、失败方向正确**：管理员短信入口走 `POST /api/auth/sms/send` + `POST /api/auth/sms/login`（角色门禁在服务端，非管理员 401 + 引导文案，端侧不自行判角色）；员工入口失败展示服务端反枚举文案（`账号或密码错误`），**不是** `Load failed` 这类网络层文案'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/login-page.test.tsx；JUnit: SameOriginOriginHeaderFilterTest；pytest: tests/unit_ci_workflows/test_bmini_h5_delivery_contract.py、test_bmini_mobile_typography_floor.py 与 test_cors_custom_headers_contract.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'admin-sms', 'same-origin', 'responsive', 'typography'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-026 [NORMAL] 入库标签落地页深链（/b/?code=<短码>）被消费且按码空间分流（源: cases/bmini.yml）──
_CASE_BM_026 = EvalCase(
    id='BM-026',
    legacy_id='',
    title='入库标签落地页深链（/b/?code=<短码>）被消费且按码空间分流',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人扫观星台入库标签上的码（`https://app.migaozn.com/i/<短码>`）→ 服务端 302 到 `/b/?code=<短码>&tenant_id=…` → h5 启动器读到该参数并按码空间分流；小程序侧走页面参数（`router.params.code`）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **参数真的被读到**（修复前全仓 `params.code`/`query.code`/`searchParams` 零命中 ⇒ 工人扫了自家标签却停在商家首页，且没有任何东西会变红）：`/b/?code=<合法入库短码>` ⇒ 启动器 `Taro.redirectTo` 到补打页并把短码**原样**带走（不归一化，归一化在服务端 `WorkerShortLinkService.normalize`）。红证：删掉 app.tsx 里那两行消费逻辑 ⇒ frontend/bmini-app/tests/inbound-landing-deeplink.test.tsx 的 D5 判红', '判据 2·🔴 **按码空间分流（复用 `codeSpace.ts`，不新造判定）**：`/s/<短码>` 洗水码 ⇒ 洗水码文案 + 报工入口，**一次都不查入库详情**（页面测：`getInboundLabel` 调用数 = 0）。红证：不看码空间直接取路径段（`treatAsInboundShortCode` 形态）⇒ 判红', "判据 3·🔴 **失败方向不静默**：别域名 / 纯文本 ⇒ 「这不是观星台的标签」；**出现但为空**（`/b/?code=`）⇒ 「8 位短码」提示（`present` 与 `raw === ''` 必须可区分）。红证：读不到就 `return`（静默当没有参数）或把两者合并 ⇒ 判红", '判据 4·**两侧都给得出路径**：h5 读 URL query（`landingCodeFromSearch`），小程序读页面参数（`landingCodeFromParams`）—— 共用同一个下游页面与同一处码空间判定；小程序侧的形态差异登记在 `WORKER_SURFACE_PLATFORM_GAPS`（h5 专有形态 ⇒ 显式登记，不留白）', '判据 5·**商家首页不抢路由**：URL 上带 `?code=` 时，商家首页不再排「未登录 ⇒ 600ms 后去商家登录页」的定时器（该定时器在页面卸载后照样触发，会把工人从他自己的落地页踢走，而**没有任何东西会变红**）。红证：删掉那道闸 ⇒ 行为面判据红（工人被送到 `/pages/auth/login/index`）'],
    skip_reason='[backend-contract] 确定性深链/分流判据（jest: frontend/bmini-app/tests/inbound-landing-deeplink.test.tsx + tests/worker-reprint-page.test.tsx 的 R1~R4），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'deeplink', 'code-space', 'landing-page'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-028 [NORMAL] B 端「问黄金策」入口＝B 端场景 + 服务端单一真值（六格等权 · 无 C 端顾客口吻 · 无商品推荐卡 · 默认「黄金策」）（源: cases/bmini.yml）──
_CASE_BM_028 = EvalCase(
    id='BM-028',
    legacy_id='',
    title='B 端「问黄金策」入口＝B 端场景 + 服务端单一真值（六格等权 · 无 C 端顾客口吻 · 无商品推荐卡 · 默认「黄金策」）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器打开 `https://app.migaozn.com/b/` 停在「问黄金策」空态：六个等权快捷入口的内容与 PC 端智能助手**同一份**（今日经营 / 交付风险 / 库存告急 / 商品健康度 / 售后待办 / 客户回访），点一格就发出对应的 B 端问句（如「哪些订单快到交期还卡着工序？」）；**看不到**任何商品推荐卡、价格符号、顾客端 agent 名「元元」，也看不到 C 端顾客口吻的旧入口（算料报价 / 找产品 / 售后咨询 / 查物流）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 空态**不得**出现 C 端商品推荐卡（修复前渲染 `.new-arrivals` 商品卡并提示「点一下问问元元」= 把顾客端入口与顾客端 agent 名搬进商家端）：结构性判据 = 空态无 `.new-arrivals` / `.new-arrivals__card` / `.new-arrivals__img`、无「新品推荐」文本、无 `¥`。红证：把该组件挂回 frontend/bmini-app/src/components/chat/MessageList.tsx 的空态 ⇒ frontend/bmini-app/tests/chat-empty-state.test.tsx 判红（实跑过）', '判据 2·🔴 **快捷入口 = 六格等权（2 列 × 3 行）**：`.quick-actions__item` 恰好 6 个（#7358 起按当前用户权限投影：6 = 管理员满额，其他岗位可能更少；布局契约 = 等权网格，格子数 = 服务端下发数）、每个都不带 `quick-actions__item--wide`、无 `.quick-actions__group` / `__row` 残留；六条 prompt 逐格可断言（渲染出的内容 = 服务端下发的那份）。红证：给任一项加回 `wide: true` ⇒ frontend/bmini-app/tests/quick-actions.test.tsx 判红（实跑过）', '判据 3·🔴 **入口内容单一真值 = 服务端**（issue #6468：此前 H5 组件里硬编码六条 **C 端顾客口吻**的入口，而服务端那份从没被消费）：服务端 `GET /api/chat/quick-actions`（backend/ai-agent-service/app/api/chat.py 的 `QUICK_ACTIONS`）是唯一内容源，H5 只渲染传入的 `actions`；组件源码不得再自带清单 / prompt / emoji 字面量；`actions` 为空 ⇒ **不渲染**（不退回一份本地兜底清单 —— 那正是病灶形态）。红证：把硬编码六条写回 frontend/bmini-app/src/components/chat/QuickActions.tsx ⇒ frontend/bmini-app/tests/quick-actions.test.tsx 的「类级元守卫」判红', '判据 4·🔴 **每条入口必须能追溯到真实能力**（机械投影，「引导了却做不到，比不引导更伤」）：backend/ai-agent-service/tests/test_chat.py::TestQuickActions::test_every_entry_maps_to_a_real_mibao_capability 要求每条的 skill 在黄金策绑定面内、且 tool 在该 skill 的 tool_names 里。红证：把任一条 skill 改成已解绑的 `settings` 或把 tool 改成顾客端专用的 `aftersale_query` ⇒ 具名判红（实跑过）', '判据 5·**agent 名用 B 端口径**：空态欢迎语不含「元元」、含「商家经营助手」；「思考中」默认文案 = 「黄金策正在思考...」（frontend/bmini-app/src/components/chat/TypingIndicator.tsx）', '判据 7·🔴 **空态那句「都可以问我」与快捷入口指向同一组业务域**（issue #6476：文案原文是「查订单、查库存、**算料报价**、售后与物流」——与六格**没有任何交集**，且「算料报价」在 B 端没有对应能力）：frontend/bmini-app/tests/chat-empty-state.test.tsx **现取**服务端 `QUICK_ACTIONS` 的 id 清单，要求空态文案逐组覆盖其业务域词（经营 / 交付 / 库存 / 商品 / 售后 / 客户），并负向断言不含「算料报价」。红证（实跑过）：把文案改回旧那句 ⇒ 具名判红；服务端新增第 7 条入口而不补映射/文案 ⇒ 同样红（服务端 id 集 != 映射表键集）', '判据 6·**类级元守卫（让同类进不来）**：B 端全量 `frontend/bmini-app/src/**` 的**代码**不得引用顾客端商品推荐端点 `new-arrivals`；聊天面（components/chat 与 pages/chat）的代码不得出现顾客端 agent 名，也不得出现 C 端顾客口吻的快捷问句（「推荐一下热门窗帘产品」「帮我查一下物流」「我想咨询售后问题」「帮我算一下窗帘用料和价格」）—— 「再抄一次顾客端页面」当场变红。边界：只扫代码（块注释与整行 `//` 注释先剔除），注释与文档不在面内', '判据 8·🔴 **快捷入口 = 当前用户权限的机械投影**（issue #7358：改前 7 条对**所有岗位**原样下发，与 8 个内置岗位默认权限比对实测 **56 格里 27 格是死的** —— inspector 1/7、finance 3/7）：服务端按 `BaseTool.check_permission`（**与工具执行同一个谓词**，不新写权限逻辑）过滤 `actions`/`tools`；按 **`permissions` 而非岗位**判（权限自 #2969 起是快照式）。判据双侧：行为 = backend/ai-agent-service/tests/test_chat.py::TestQuickActions（inspector 只剩「交付风险」；customer_service 4 条；空权限 0 条；管理员 7 条）；结构 = tests/unit_ci_workflows/test_quick_actions_permission_projection.py（能力锚 / 权限锚 / 过滤接线 / 每岗非空且无全局死项 + 注入式红证）。红证：删掉端点里的 `_quick_action_visible` 调用 ⇒ 结构判据具名判红；把 inspector 的权限喂成 `[]` ⇒ 行为判据判红（均已实跑）'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/chat-empty-state.test.tsx + frontend/bmini-app/tests/quick-actions.test.tsx；pytest: backend/ai-agent-service/tests/test_chat.py::TestQuickActions），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'chat', 'quick-actions', 'empty-state', 'c-end-isolation'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-029 [NORMAL] 「我的」页：只剩商家面入口（工人三件功能已移出到工人工作台）+ 字号按设计尺度（≥24）（源: cases/bmini.yml）──
_CASE_BM_029 = EvalCase(
    id='BM-029',
    legacy_id='',
    title='「我的」页：只剩商家面入口（工人三件功能已移出到工人工作台）+ 字号按设计尺度（≥24）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家员工在 `/b/` 的「我的」页：菜单里只有商家面入口（管理面 4 项 + 关于我们 / 隐私协议）；工人三件功能（扫码报工 / 拍照入库 / 补打入库标签）**不在**商家菜单里 —— 它们在工人用「工号 + PIN」登录后的工作台；菜单文字在手机上清晰可读，不再是挤在一起的小字'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 商家「我的」页**取不到**工人三件功能（扫码报工 / 拍照入库 / 补打入库标签）：判据 = frontend/bmini-app/tests/profile-page.test.tsx 的渲染面反向断言（`queryByText` 三条全 null）+ 源码面（去注释）断言（页面源码不得出现这三条标签与 `PRODUCTION_PAGE_ROUTE` / `INBOUND_PAGE_ROUTE` / `REPRINT_PAGE_ROUTE` / `/pages/production/index/index` 任一记号）。红证（实跑）：把一条「扫码报工」菜单项注入回 frontend/bmini-app/src/pages/profile/index/index.tsx ⇒ 两条判据各自判红（2 failed / 13 passed，随后还原）。三件功能的**存活**判据在工人工作台：frontend/bmini-app/tests/worker-home-page.test.tsx（BM-034，一格未放宽）', '判据 2·入口台账同批**收缩**：frontend/bmini-app/src/utils/pageEntries.ts 撤掉 `from = 「我的」页` 的三条登记（扫码报工 / 拍照入库 / 补打入库标签）—— 三页仍各有其它真入口（工人工作台三条 / `/w/` 报工页页头两条 / 扫标签深链一条）⇒ 守卫 frontend/bmini-app/tests/page-entry-reachability.test.ts 的「未登记即红 / 登记了没人指向也红」双向仍绿，且登记总数只减不增', '判据 3·🔴 「我的」页 sub-floor 字号**清零**（修复前 `.menu-item__text` = `font-size: 15px` ⇒ 真机 ≈7.8 CSS px @390 宽，用户反馈「菜单列表字体太小」）：判据 = tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py 的 test_profile_page_has_no_sub_floor_font_size（该页独立报红，不从台账里翻）+ 只许缩短台账全库读数 **85 → 68 → 0**（第二轮收口见 issue #5769：聊天卡片与各页共 68 处一并达标，台账已清零）。红证：把 15px 写回 ⇒ 该用例判红（实跑过）', '判据 4·同批清掉从顾客端 profile 抄来、本页零引用的整块样式（CSS 尺度小字号的来源），菜单行高按手指命中区口径取 96 设计 px（≈50 CSS px，同 BM-027 的 ≥88 口径）'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/profile-page.test.tsx + pytest: tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'profile', 'worker', 'page-entry', 'typography'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-030 [NORMAL] B 端 H5 底部 tabBar 居中：iOS 安全区只补一次 + 图标/文字在可视区垂直居中（源: cases/bmini.yml）──
_CASE_BM_030 = EvalCase(
    id='BM-030',
    legacy_id='',
    title='B 端 H5 底部 tabBar 居中：iOS 安全区只补一次 + 图标/文字在可视区垂直居中',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器打开 `https://app.migaozn.com/b/`：底部四个 tab（问黄金策 / 数据 / 坐席 / 我的）在条内垂直居中 —— 图标与文字上下留白对称；在带 home indicator 的 iPhone 上，条覆盖安全区、文字既不被顶到条外、下方也不留大块空白'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **安全区只补一次**（修复前 Taro h5 的 tabBar 把它算了**两遍**：`.taro-tabbar__tabbar-bottom{margin-bottom:env(safe-area-inset-bottom)}` 把整条抬起 + `.weui-tabbar__item{padding-bottom:env(...)}` 条内再垫一次 ⇒ 线上 390×844 实测：图标相对条顶 −12px（溢出条外）、文字下方留 51px 空白）：判据 = frontend/bmini-app/tests/tabbar-layout.test.ts 断言 frontend/bmini-app/src/styles/tabbar.scss 里条 `margin-bottom: 0` 且条高 = `calc(50PX + env(safe-area-inset-bottom))`（**CSS 尺度字面量**）。⚠️ **不许**写成 `var(--taro-tabbar-height)`：构建流水线会把这个名字改写成 `var(--50PX)` ⇒ 声明在计算值阶段失效（`unset`→`auto`）⇒ 条高塌成 26px、标签被挤出屏幕（#5755 发布后实测，同日 follow-up 修）；该形态另有一条类级判据（本仓 scss 出现它即红）。判据 1c 还会现取 Taro 实现包，核对字面量与 `--taro-tabbar-height` **逐值相等**。红证：把该文件移开（= 改前状态）⇒ 同一文件 3 条判据判红（实跑过：3 failed / 2 passed）', '判据 1b·🔴 **陷阱判据**（本次回归的拦网）：`frontend/bmini-app/src/**/*.scss` 里出现 `var(--taro-tabbar-height` ⇒ 判红（探针实测：`var(--my-thing)` / `var(--foo-height)` 原样保留，被特殊处理的**只有这个名字**）', '判据 1c·字面量 == Taro 运行时值（现取 `@tarojs/{components,router}` 的 dist 里的 `--taro-tabbar-height:<n>px`；找不到 ⇒ fail-closed 判红，不许猜一个数补上）—— Taro 升级改了它 ⇒ 判红，逼人同步这一格', '判据 2·🔴 **图标 + 文字在可视区垂直居中**（修复前 item 是 `padding:5px 0` = 上 5 下 0 ⇒ **无安全区时文字直接贴着屏幕底边**，安卓 / 桌面 / 老 iPhone 同样不居中）：`.weui-tabbar__item` 必须是 flex 纵列居中（`display:flex` + `flex-direction:column` + `align-items:center` + `justify-content:center` + `padding-top:0`），且**保留** `padding-bottom: env(safe-area-inset-bottom)` —— 与判据 1 合起来才是「只补一次」（把两处一起删掉 ⇒ 判红）', '判据 3·覆盖样式必须被 frontend/bmini-app/src/app.scss **真的引入**（写在别处但没接线 ⇒ 判红）；类级：`src/styles/*.scss` 里不许出现第二份 `taro-tabbar__` 覆盖（第二份口径会漂）', '判据 4·**几何面**：（a）🔴 **机器判据（issue #5759 起）** = tests/e2e/specs/bmini/bmini-tabbar.spec.ts（配置 tests/playwright.bmini.config.ts；CI = .github/workflows/bmini-app.yml 的 `tabbar-geometry` job）—— 判条贴底（±1px）、每格图标与文字相对本格水平居中（±1px）、**图标上方留白 == 文字下方留白（±2px）且两者都 > 0**、条高 ∈ [49,51]；Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ 这些数字**跨平台确定**。（b）**iOS 安全区那一侧仍是复测读数**（该腿环境取不到 env()）：安全区 34 ⇒ 条高 84 = 50+34、图标相对条顶 ≈+2.5px、文字底距屏幕底 ≈36.5px（= 34 安全区 + 2.5 居中留白）。⚠️ 本腿**不做像素基线**（darwin/linux 双平台基线本机生成不齐全）⇒ 颜色 / 观感类回归仍无机器判据'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/tabbar-layout.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'tabbar', 'layout', 'safe-area', 'responsive'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-031 [NORMAL] B 端 H5 tabBar：四张图标两两不同 + 新增 e2e 几何腿（底栏居中第一次有了机器判据）（源: cases/bmini.yml）──
_CASE_BM_031 = EvalCase(
    id='BM-031',
    legacy_id='',
    title='B 端 H5 tabBar：四张图标两两不同 + 新增 e2e 几何腿（底栏居中第一次有了机器判据）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器打开 `https://app.migaozn.com/b/`：底栏四个入口（问黄金策 / 数据 / 坐席 / 我的）**图标各不相同**（此前「问黄金策」与「坐席」共用同一张对话气泡图 ⇒ 两个入口长得一模一样）；底栏整体居中，不出现「文字贴屏幕底边」或「下方一大块空白」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **四个 tab 四张不同图标**（修复前「问黄金策」与「坐席」同指 frontend/bmini-app/src/assets/tabbar/chat.png，线上实测两处 `img.src` 的 base64 完全相同）：单测 = frontend/bmini-app/tests/tabbar-icons.test.ts（app.config.ts 文本里 `iconPath` / `selectedIconPath` 两两不同 + 文件存在 + 81×81 + 不留零引用图标）；e2e = tests/e2e/specs/bmini/bmini-tabbar.spec.ts 断言**渲染出来的**四个 `img.src` 两两不同。红证（实跑过）：把「坐席」改回 chat.png ⇒ 单测 3 failed / 2 passed；e2e 2 failed（Expected 4 / Received 3）', '判据 2·**素材规格与图标家族一致**：新图标（数据 = 柱状图）81×81 RGBA、单色（未选 #999999 / 选中 #2F54EB，与既有六张同色；active 与 inactive 同形换色），由判据读 PNG 头现取尺寸；换设计稿只需替换 PNG，判据只锁规格与唯一性', "判据 3·**e2e 腿在位且真的跑得起来**：tests/playwright.bmini.config.ts（复用 C 端 tests/xiaobu_dist_freshness.py 的 `--project` 做产物新鲜度前置断言，**不重写第二份实现**；`channel: 'chrome'`；webServer 只服务不构建、`reuseExistingServer: false`）+ tests/e2e/specs/bmini/bmini-tabbar.spec.ts + .github/workflows/bmini-app.yml 的 `tabbar-geometry` job（与另两条腿同一 PR/push 门控口径）", '判据 4·**几何判据**（Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ 跨平台确定）：条贴底（±1px）、每格图标与文字相对本格水平居中（±1px）、**图标上方留白 == 文字下方留白（±2px）且两者都 > 0**、条高 ∈ [49,51]（#5756 那次「条高塌成 26px」会被这一条抓住）。几何侧红证读数见 BM-030 判据 4'],
    skip_reason='[backend-contract] 确定性判据（jest: frontend/bmini-app/tests/tabbar-icons.test.ts；playwright: tests/e2e/specs/bmini/bmini-tabbar.spec.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'tabbar', 'icons', 'e2e', 'geometry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-032 [NORMAL] 工人拍照入库：雪花号 skuId 逐字原样回传（真实量级 2.1e18，> 2^53），端侧类型为 string（源: cases/bmini.yml）──
_CASE_BM_032 = EvalCase(
    id='BM-032',
    legacy_id='',
    title='工人拍照入库：雪花号 skuId 逐字原样回传（真实量级 2.1e18，> 2^53），端侧类型为 string',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人在手机浏览器（bmini H5）拍/扫面料标签 → 识别命中既有 SKU → 核对米数 → 确认过账：提交体里的 skuId 必须与识别结果逐字相同（2.1e18 的雪花号，JS 的 Number 只有 2^53 精度）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 实例（#6340 靶心）：frontend/bmini-app/tests/worker-inbound-page.test.tsx 的 C7 用例 —— 识别 mock 返回真实量级 skuId `2106900122848247810`（> 2^53 = 9007199254740991），断言 createInboundDraft 收到的 body.skuId **逐字等于**该字符串（`String(body.skuId)` 同值）；页面写回 `Number(chosenSku?.skuId)` ⇒ 红（末两位被吞成 …800）。玩具 id 测不出来 —— 那正是本洞当初溜过的原因（同 #5904）', '判据 2·端侧类型 = 字符串：frontend/bmini-app/src/utils/inbound/recognizeGate.ts 的 SkuMatch.skuId / DraftInput.skuId、frontend/bmini-app/src/services/workerInboundService.ts 的 InboundDraftRequest.skuId 均为 string（后端出参形态；类型写回 number ⇒ tsc 报错）', '判据 3·类级元守卫（同族进不来）：frontend/admin-web/tests/unit/lib/snowflake-id-not-number.test.ts 的语料根已参数化为 admin-web + bmini-app 两个根 —— `Number()/parseInt()/parseFloat()` 作用在 `.id` 形态成员上即红（未登记即红 / 登记陈旧即红 / 逐根反空跑）；单变量红证实跑：把 bmini 入库页那行改回 `Number(chosenSku?.skuId)` ⇒ 具名报出 `frontend/bmini-app/src/pages/worker/inbound/index.tsx`（命中的那一行 = 建草稿体里的 skuId 表达式）'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/worker-inbound-page.test.tsx / vitest: frontend/admin-web/tests/unit/lib/snowflake-id-not-number.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-033 [NORMAL] B 端登录页第三入口（工人）+ 路由参数直达 - 工号 + PIN 走既有 workerLogin，成功落工人首页（不 switchTab）（源: cases/bmini.yml）──
_CASE_BM_033 = EvalCase(
    id='BM-033',
    legacy_id='',
    title='B 端登录页第三入口（工人）+ 路由参数直达 - 工号 + PIN 走既有 workerLogin，成功落工人首页（不 switchTab）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人打开 B 端 H5 登录页（或从报工页 / 工人首页点「去登录工人身份」）→ 切到第三个 tab「工人登录」→ 填工号 + PIN（可选设备标签）→ POST /api/worker/login → 成功进工人工作台；输错 PIN 时屏上**原样**显示服务端文案'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**三个 tab 都在册**（员工 / 管理员 / 工人），默认停在员工入口；`/pages/auth/login/index?tab=worker` **路由参数直达**工人入口（员工/管理员字段退场）。证据：frontend/bmini-app/tests/login-page.test.tsx', '判据 2·🔴 **提交恰一次 + 成功后 `redirectTo` 工人首页且绝不 switchTab**：工人 tab 提交 ⇒ `workerLogin(工号, PIN, 设备标签, 企业编码)` 恰一次（**既有**端点 `POST /api/worker/login`，未新造端点/登录服务），成功 ⇒ `Taro.redirectTo({ url: WORKER_HOME_ROUTE })` 且 `Taro.switchTab` 一次都不调（工人没有商家会话，switchTab 会落到商家 tabBar=问黄金策，而工人零商家权限 ⇒ 落地即 403/空页）。红证（实跑）：把 `redirectTo` 改回 `switchTab` ⇒ 1 failed', '判据 3·**失败原样展示服务端 message**：服务端失败信封是 `{success:false,error:{code,message}}`（真值 = backend/admin-api/src/main/java/com/migao/admin/config/GlobalExceptionHandler.java 的 `handleBusinessException`）⇒ 端侧取值链路必须取到它，而不是 HTTP 层噪声「Request failed with status 401」。证据：frontend/bmini-app/tests/worker-service-message.test.ts'],
    skip_reason='[backend-contract] 确定性前端判据（jest: frontend/bmini-app/tests/login-page.test.tsx + frontend/bmini-app/tests/worker-service-message.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'worker'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-034 [NORMAL] 工人工作台（pages/worker/home/index）- 身份卡读服务端 + 工人功能入口按工人档案菜单显隐（拍照入库 / 补打入库标签 / 拍照发货 / 待发货单 / 返工记录 / 我的计件）+ 待处理数 + 退出工人身份；不出现任何商家面入口；扫码报工入口已移除（扫码由微信 / 手机相机承担）（源: cases/bmini.yml）──
_CASE_BM_034 = EvalCase(
    id='BM-034',
    legacy_id='',
    title='工人工作台（pages/worker/home/index）- 身份卡读服务端 + 工人功能入口按工人档案菜单显隐（拍照入库 / 补打入库标签 / 拍照发货 / 待发货单 / 返工记录 / 我的计件）+ 待处理数 + 退出工人身份；不出现任何商家面入口；扫码报工入口已移除（扫码由微信 / 手机相机承担）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人用「工号 + PIN」登录成功后落在**工人工作台**：页头显示当前工人（工号 + 姓名，来自服务端 `GET /api/worker/production/current-worker`）→ 工人功能：拍照入库 / 补打入库标签 / 拍照发货 / 待发货单 / 返工记录 / 我的计件（按工人档案的菜单勾选显隐；2026-10-27 用户裁定「把工人菜单页面的扫码报工菜单移除掉，直接用其他 app 的扫一扫功能替代」⇒ 扫码报工**不再是本页菜单**，工人用微信 / 手机相机扫纸上的码直接落到报工页）；底部「退出工人身份」→ 回登录页的工人入口'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**身份卡读服务端**：工号 + 姓名来自 `fetchCurrentWorker()`（服务端工人 session，页头显示的正是「这笔活会记到谁头上」= 计件工资凭证）；服务端读不到（session 失效）⇒ 回落成「未登录工人身份」并清本机工人态，**不**静默保留上一个人的名字。红证（实跑）：把身份卡改读 `getCachedWorker()`（不调服务端）⇒ 1 failed', '判据 2·**工人功能入口各自跳对路由 + 扫码报工入口已移除**：拍照入库 → `INBOUND_PAGE_ROUTE`、补打入库标签 → `REPRINT_PAGE_ROUTE`、拍照发货 → `SHIPMENT_PAGE_ROUTE`、待发货单 → `SHIPMENT_ORDERS_PAGE_ROUTE`、返工记录 → `REWORK_PAGE_ROUTE`、**我的计件 → `PIECEWORK_PAGE_ROUTE`**（真值全在 frontend/bmini-app/src/utils/inbound/gaps.ts，页面不写第二份字面量；我的计件这条是 issue #7934 从**报工详情页**页头搬到本页的，worker-h5 侧同步反向钉住「报工页不得再渲染它」）。🔴 2026-10-27（issue #7920，用户逐字「把工人菜单页面的扫码报工菜单移除掉，直接用其他 app 的扫一扫功能替代」）：**该入口已删除**，并**反向钉住**「本页的 `Taro.navigateTo` 里不许再出现 `/pages/worker/report/index`」（报工页只由外部扫码 302 → 启动器 `redirectTo` 到达）。红证（实跑）：把「扫码报工」卡加回去 / 或把返工记录入口摘掉 ⇒ frontend/bmini-app/tests/worker-home-page.test.tsx 对应断言 red', '判据 6·**待处理红色数字**（issue #7921）：待发货单 / 返工记录两条入口标题上显示服务端列表行数（`GET /api/worker/shipment/orders` 的 `items`、`GET /api/worker/production/rework-orders` 的 `orders`）；**只在这条入口可见时才请求**；`>0` 才显示、`0` 与读失败都**不显示**（读失败绝不回落成 0 —— 那是在替服务端断言「没有待处理的活」）。红证（实跑）：把读失败的 `null` 改成 0 ⇒ 徽标出现 ⇒ 断言 red', '判据 7·**返工记录页**（issue #7921，新页 pages/worker/rework/index）：数据 = `GET /api/worker/production/rework-orders`（与 H5 `/w/rework.html` 同一端点，端侧只渲染）；五态互斥 —— 读取中 / 读不到（可重试）/ 401（去登录）/ **403（工人档案没开「返工记录」页 ⇒ 可行动提示，不冒充「没有返工」）** / 读到了（空态或列表）。判据 = frontend/bmini-app/tests/worker-rework-page.test.tsx。红证（实跑）：把 403 归到 error / 把 `rework_count` 缺值补 0 ⇒ 对应断言 red', '判据 3·🔴 **不出现任何商家面入口**：问黄金策 / 数据 / 坐席 / 我的 四个 tabBar 文案与管理面 4 项（标签取自 frontend/bmini-app/src/utils/adminPermission.ts 的 `ADMIN_SURFACES`）一个都不渲染 —— 工人零商家权限（`/api/admin/**` 拒绝集合含 `worker`），点了只会 403/空页。红证（实跑）：往页面混入一行「问黄金策」⇒ 1 failed', '判据 4·**退出工人身份**：`workerLogout()`（服务端留 `end_reason=logout` 痕）+ `clearWorkerSession()` 清本机 ⇒ `redirectTo` 登录页的工人入口（共用 PAD 场景：下一个人接着用；只清本机会让下一个人记到上一个人头上）', '判据 5·**新页必须在册**：`WORKER_HOME_ROUTE` / `REWORK_PAGE_ROUTE` / `PIECEWORK_PAGE_ROUTE` 逐字出现在 frontend/bmini-app/src/app.config.ts 的 pages 里（没登记 = 死链），并登记进 frontend/bmini-app/src/utils/pageEntries.ts 的入口台账（「登记了没人指向也红 / 没登记即红」）。🔴 2026-10-27 台账**缩表**：报工页的发射方由两条（端内点击 + 扫码落地）降为**一条**（扫码落地，`src/app.tsx`）—— 入口台账只许缩短。证据：frontend/bmini-app/tests/page-entry-reachability.test.ts + frontend/bmini-app/tests/report-landing.test.ts（B4）'],
    skip_reason='[backend-contract] 确定性页面链路判据（jest: frontend/bmini-app/tests/worker-home-page.test.tsx + tests/page-entry-reachability.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'page-flow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-036 [NORMAL] 请求层 401 身份分流 - 工人端点 401 不再误诊成「商家会话过期」（不清商家态 / 不跳商家登录页 / 上屏服务端文案）（源: cases/bmini.yml）──
_CASE_BM_036 = EvalCase(
    id='BM-036',
    legacy_id='',
    title='请求层 401 身份分流 - 工人端点 401 不再误诊成「商家会话过期」（不清商家态 / 不跳商家登录页 / 上屏服务端文案）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['本机同时有商家登录态（管理员在共用 PAD 上开着后台）与一次**工人端点**调用：`POST /api/worker/production/scan/complete` 返回 401（报工写入口只认工号 + PIN 签发的工人身份）或 `POST /api/worker/login` 输错 PIN 返回 401 → 屏上只出现服务端文案，商家登录态**不受影响**'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **工人端点 401（`path` 以 `/api/worker/` 开头）**：① **不清**商家 `auth_token` / `auth_user`（实测旧行为把它们清掉 ⇒ 用户被踢回登录页，重登再点仍然 401）；② 只清工人 session/缓存；③ 上屏**服务端文案**（`data.error.message || data.message`，取不到才用兜底「工人身份已失效，请重新用工号 + PIN 登录」）；④ **不**做商家登录页跳转（把定时器推完也不跳；引导交给页面自身的身份分流）。红证（实跑）：把该分流条件写成 `false`（= 旧行为）⇒ 2 failed。证据：frontend/bmini-app/tests/request.test.ts', '判据 2·**商家端点 401 行为逐字不变**：清 `auth_token`/`auth_user` + 弹「登录已过期，请重新登录」+ 1.5s 后 `redirectTo` 商家登录页。证据：frontend/bmini-app/tests/request.test.ts（既有判据 + 新增一条钉死跳转）', "判据 3·**实现只取最少代码**：分流依据是 `path.startsWith('/api/worker/')`（不引入第二份端点台账）—— 与服务端 `WorkerSessionService` 的工人路径前缀同形。"],
    skip_reason='[backend-contract] 确定性网络层判据（jest: frontend/bmini-app/tests/request.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'auth', 'worker'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-037 [NORMAL] 类级元守卫：工人面写入口台账（未登记即红 / 台账只许缩短 / 身份分流与渲染条件都要命中 / 空台账 fail-closed）（源: cases/bmini.yml）──
_CASE_BM_037 = EvalCase(
    id='BM-037',
    legacy_id='',
    title='类级元守卫：工人面写入口台账（未登记即红 / 台账只许缩短 / 身份分流与渲染条件都要命中 / 空台账 fail-closed）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['任何人给 bmini 的某个页面新增一处工人写调用（`completeByScan` / `workerLogin` / `workerLogout` / `createInboundDraft` / `postInboundDraft`）—— 无论他有没有写身份分流，判据都要拦得住'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **未登记即红**：以 frontend/bmini-app/src/pages 下全部 `.tsx`（先剥注释）为射程现取 (页面, 工人写调用) 配对集，凡有配对不在 frontend/bmini-app/tests/worker-surface-ledger.json 里 ⇒ 具名判红。红证（实跑，in-test 注入）：新增一个调 `workerLogout()` 的虚拟页面 ⇒ 报出 `src/pages/worker/brand-new/index.tsx::workerLogout(`', '判据 2·**台账只许缩短**：每条登记都必须仍能被扫到（页面已不再有该调用 ⇒ 该条已死 ⇒ 红）。红证：摘掉工人首页的 `workerLogout(` 调用而不删登记 ⇒ 红', '判据 3·🔴 **声称「必须先有工人身份」的写入口必须真的有分流**：`gate_tokens` 两条记号（身份分流**声明** + **用到它的渲染条件**）都要命中。红证（真语料注入，两条各一次）：① 把 `const workerReady = hasWorkerSession()` 改成 `const workerReady = true` ⇒ 正跑判据 1 failed；② **留着声明**只把 `position.part_token && workerReady ? (` 改成 `position.part_token ? (` ⇒ 正跑判据 1 failed（这一族正是「按某个 token 在不在」判的守卫会漏的形态）', '判据 4·**引导必须可行动**：分流页面必须渲染引导文案（`guide_token`）与指向登录页工人入口的记号（`login_route_token`）；删掉任一个 ⇒ 红', '判据 5·**台账不许空转（fail-closed）**：条数为 0 ⇒ 红（「空」不等于「全部合规」）；每条登记必须声明 `case_ids`。台账条数**现取**（守卫按射程现算配对集，双向相等才算过；文档里不写死条数）'],
    skip_reason='[backend-contract] 确定性元守卫（jest: frontend/bmini-app/tests/worker-surface-ledger.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-038 [NORMAL] 类级元守卫：工人面动作**端点归属**台账（工人面动作打 /api/admin/ ⇒ 未登记即红 / 台账只许缩短 / admin 条目必须给出路 / 工人替代必须真被用上 / 空台账 fail-closed）（源: cases/bmini.yml）──
_CASE_BM_038 = EvalCase(
    id='BM-038',
    legacy_id='',
    title='类级元守卫：工人面动作**端点归属**台账（工人面动作打 /api/admin/ ⇒ 未登记即红 / 台账只许缩短 / admin 条目必须给出路 / 工人替代必须真被用上 / 空台账 fail-closed）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['任何人给 bmini 的某个**身份感知页面**（出现 `hasWorkerSession(` 的 `.tsx`）新增/改动一个工人动作，而它打的是 `/api/admin/**`（工人零商家权限，`SecurityConfig.ADMIN_API_REJECTED_ROLES` 的拒绝集合含 worker ⇒ 纯工人设备必被拒）—— 无论他有没有写身份分流，判据都要拦得住'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **未登记即红**：射程 = frontend/bmini-app/src/services/*.ts 里**顶层导出函数**中，函数体（先剥注释）含 `/api/admin/`、且所在 service 模块被某个身份感知页面（`src/pages/**/*.tsx` 里出现 `hasWorkerSession(`）import 的那一批；凡不在 frontend/bmini-app/tests/worker-action-endpoint-ledger.json 里 ⇒ 具名判红。红证（实跑，in-test 注入）：给 frontend/bmini-app/src/services/productionService.ts 注入一个调 `/api/admin/.../nope` 的新导出函数 ⇒ 报出 `src/services/productionService.ts::injectedAdminAction`', '判据 2·**台账只许缩短**：每条登记都必须仍能被现扫命中（函数已删 / 已不再被身份感知页面引用 / 端点已搬走 ⇒ 该条已死 ⇒ 红）。红证（实跑）：登记一个不存在的 `shippedLongAgo` ⇒ 判红；摘掉 `shipOrder` 的登记（函数仍在被页面引用）⇒ 判据 1 红', '判据 3·🔴 **admin 条目必须给出路**：要么 `worker_alternative` 在**同 service** 里真的顶层导出、且其函数体真的含 `/api/worker/`；要么显式写明 `reason`（有意不搬的理由）。红证（实跑）：把 `shipOrder` 的 `worker_alternative` 清空且不给 `reason` ⇒ 红；把替代函数名改成 `shipWorkerOrderGhost` ⇒ 红', '判据 4·**工人替代必须真的被用上**（`migao-dev-flow` §28.2「判据绿 ≠ 接线在」）：登记了 `worker_alternative` 就必须在调用页里找到对它的调用。红证（实跑，真语料注入）：把 frontend/bmini-app/src/pages/production/index/index.tsx 里的 `shipWorkerOrder(` 改名 ⇒ 报「接线不在」（替代只是声明，工人身份下仍走商家端点）；不注入 ⇒ 同一份判据不报（反向对照）', '判据 5·**台账不许空转（fail-closed）**：条数为 0 ⇒ 红（「空」不等于「全部合规」）；每条登记必须声明 `case_ids`；正跑还要求「登记集 ⇄ 现扫集」双向相等。台账条数**现取**（不写死），复算（**在仓根执行**，路径即仓根相对）：`node -e "const l=require(\'./frontend/bmini-app/tests/worker-action-endpoint-ledger.json\');console.log(l.entries.length)"`'],
    skip_reason='[backend-contract] 确定性元守卫（jest: frontend/bmini-app/tests/worker-action-endpoint-ledger.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-040 [NORMAL] 「数据」页三类待办落到「加工单详情」只读页 + 纯工人设备不进商家页（三身份隔离收口）（源: cases/bmini.yml）──
_CASE_BM_040 = EvalCase(
    id='BM-040',
    legacy_id='',
    title='「数据」页三类待办落到「加工单详情」只读页 + 纯工人设备不进商家页（三身份隔离收口）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在「数据」页点一张待办（待排产 / 卡在哪 / 待发货）⇒ 打开的是**只读的加工单详情**（加工单号 / 订单号 / 客户 / 交期 + 工序进度），页面上没有「扫一扫」「去登录工人身份」；工人设备（有工人 session、没有商家凭据）打开商家页 ⇒ 自动回工人工作台'],
    expectations=['direct_reply'],
    data_checks=['判据 1·三类待办的落脚页 = 加工单详情：backend/admin-api/src/main/java/com/migao/admin/service/ProductionTodoService.java 的 `processingOrderDetailPage(orderId)` 逐字产出 `/pages/production/order-detail/index?orderId=<orderId>`；页面在 frontend/bmini-app/src/app.config.ts 在册、并登记进入口台账（via=url，viaBinding=该 Java 文件）。红证：改回报工页 ⇒ frontend/bmini-app/tests/page-entry-reachability.test.ts 的 L4 绑定判红 + backend/admin-api/src/test/java/com/migao/admin/service/ProductionTodoServiceTest.java 的三类 link 断言判红', '判据 2·🔴 新页**纯只读**：frontend/bmini-app/tests/processing-order-detail-page.test.tsx 的源码级断言（去注释后不得出现「扫一扫 / 去登录工人身份 / scanResolve( / completeByScan( / getWorkerOrderOperations / hasWorkerSession / WORKER_TAB_LOGIN_ROUTE / PRODUCTION_WORKER_LOGIN_REQUIRED / workerSessionHeaders」任一记号）+ 反向自证（源码确实消费 `getProcessingOrderBrief(` / `getOrderOperations(`）。红证：往页面注入一个「扫一扫」按钮 ⇒ 该用例判红', '判据 3·页面三态分开（403 ⇒「无「作业看板」查看权限（需要权限码 production:view）」/ 这笔订单还没有加工单 / 加载失败可重试）+ 抬头缺键的行不渲染：同文件四条用例。红证：删掉 forbidden 分支 ⇒ 落到「加载失败」⇒ 红', '判据 4·🔴 商家面身份护栏：frontend/bmini-app/tests/role-guard.test.tsx —— 有工人 session、无商家凭据 ⇒ `Taro.redirectTo(WORKER_HOME_ROUTE)`；有商家凭据（哪怕同时有工人 session）**不跳**（负控：共用 PAD 的正常动线）；工人页 / 公开登录页**不许**挂护栏（负控：挂了工人会被自己的页面弹走）', '判据 5·**类级**（新增商家页不挂护栏 ⇒ 红）：商家页清单**现取** —— tabBar 四页来自 frontend/bmini-app/src/app.config.ts 的 `tabBar.list`、管理面 4 项来自 frontend/bmini-app/src/utils/adminPermission.ts 的 `ADMIN_SURFACES`、外加坐席会话详情页 —— 每页都必须挂 `useMerchantSurfaceGuard`（证据：同文件的「商家页清单」组，含反空跑断言）', '判据 6·**按部位补生产信息**（issue #6901）：frontend/bmini-app/tests/processing-order-detail-info.test.tsx 逐部位渲染商品身份（品名 / 货号 / 颜色 / 门幅 / 售卖方式 / 单位）、规格尺寸（宽 × 高，两位小数 + 米）、加工信息（走 `src/utils/craft-display.ts::craftSpecRows()` —— **不新造标签表**）、派工（批号 + 指派米数**两键都在才显示**；只有批号 = 未指派 ⇒ 不渲染）、部位备注；🔴 **键缺席 ⇒ 该行不渲染**（不补默认值、不折 0）。红证（实跑读数）：去掉 `craftSpecRows` 的「部位」过滤 ⇒ **1 failed / 7 passed**（判据 4+5）；`sizeText` 不判有限数 ⇒ **2 failed**（正文含 NaN）；`batchText` 删「两键都在」守卫 ⇒ **2 failed**', '判据 8·🔴 **落地优先：落地参数在场时护栏不得抢路由**（issue #7887，2026-10-27 现场：工人手机上扫水洗唛 ⇒ 落在工人工作台）。frontend/bmini-app/tests/report-landing.test.ts 的 B3b 组：纯工人设备 + `?t=`（报工短链）⇒ 护栏**零** `redirectTo`；纯工人设备 + `?code=`（入库标签）⇒ 同样零跳（同一类老问题）；负控：纯工人设备 + **无**落地参数 ⇒ 照旧送 `WORKER_HOME_ROUTE`（证明不是把护栏废掉）；负控：`?qr=<票据>`（PC「手机端」码）不含 t/code ⇒ 照旧送工人工作台（#7880 的行为不许被影响）；类级：`frontend/bmini-app/src/utils/roleGuard.ts` 的护栏必须**在 `redirectTo` 之前**调用 `hasLandingIntent()`。红证（实测）：删掉护栏里那句 `if (hasLandingIntent()) return` ⇒ B3b **3 failed / 1 passed**；还原 ⇒ 4 passed。', '判据 7·**类级同源（售卖方式展示名）**（issue #6901）：frontend/bmini-app/tests/selling-method-same-source.test.ts 把 bmini 的 `src/utils/selling-method.ts` 与 admin-web 单一真值 `frontend/admin-web/src/types/index.ts::SellingMethodLabels` **现取双侧逐值比对**，并判两侧都非空（防「都空 ⇒ 相等」假绿）。红证：让 `sellingMethodLabel` 直接回显内部键 ⇒ **2 failed**（`bulk_cut` 上屏 + 同源守卫判据 3）'],
    skip_reason='[backend-contract] 确定性结构 / 页面判据（jest: frontend/bmini-app/tests/processing-order-detail-page.test.tsx + role-guard.test.tsx + page-entry-reachability.test.ts + processing-order-detail-info.test.tsx + selling-method-same-source.test.ts；java: ProductionTodoServiceTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'production', 'dashboard', 'page-entry', 'role-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-041 [NORMAL] 登录页记住上次成功登录的账号名（按登录面分开存 / 进页预填 / 绝不记 PIN·密码·验证码）（源: cases/bmini.yml）──
_CASE_BM_041 = EvalCase(
    id='BM-041',
    legacy_id='',
    title='登录页记住上次成功登录的账号名（按登录面分开存 / 进页预填 / 绝不记 PIN·密码·验证码）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-07 原话「还要做个小优化，账号名存在 cookies 中，不要每次都要输入」—— 员工 / 管理员 / 工人三个登录面各自记住上次**成功登录**用过的账号名，再次进入登录页时预填'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**预填口径**：`getRememberedAccount(面)` 取该面**上次成功登录**用过的账号名并预填；从未登录过 ⇒ 空串（**不编默认值**）；三面各存各的键、互不串台。证据：frontend/bmini-app/tests/login-remember-account.test.tsx（判据 1a / 1b / 1c / 1f；1b / 1f 自 issue #7944 起同时覆盖「企业编码预填」）', '判据 2·**只记「成功过」的**：失败不写、成功才覆盖 —— 把 `rememberAccount` 提到 `if (!success)` 之前 ⇒ 判据 1d 判红。证据：frontend/bmini-app/tests/login-remember-account.test.tsx', "判据 3·🔴 **反向红线（可红）**：三个面全部填满并成功登录（密码 / 短信验证码 / PIN 各带一个哨兵值）⇒ 落盘键值里**不出现**任何哨兵；且落盘的键只有账号名三键 + 企业编码两键（企业编码的专门用例 = BM-055，issue #7944）。红证（实跑，真语料注入）：把 `rememberAccount('employee', username)` 改成 `rememberAccount('employee', password)` ⇒ 判据 2 判红。证据：frontend/bmini-app/tests/login-remember-account.test.tsx", '判据 4·**类级**：① 本仓存储键面（`STORAGE_KEYS` 的键值 + `src` 下所有 storage 调用的字面量键）不许出现凭据形态键名（`password`/`pwd`/`pin`/`*code`/`credential`…）；② 账号名三键 + 企业编码两键只有 frontend/bmini-app/src/utils/loginAccount.ts 一个读写点（第二份口径即红）。证据：frontend/bmini-app/tests/login-remember-account.test.tsx（判据 2b / 2c）', '判据 5·**退出登录不清账号名**（它只是输入便利，不是登录态）：调真实现的 `logout()` 后账号名三键 + 企业编码两键原值仍在，而 `auth_token` / `auth_user` 照旧被清（对照组）。证据：frontend/bmini-app/tests/login-remember-account.test.tsx（判据 1e）', '判据 6·**口径替换已显式登记**：用户口述要用浏览器 cookies 存账号名，落地为 **localStorage**（`Taro.setStorageSync` + `STORAGE_KEYS`，与 frontend/bmini-app/src/utils/workerSession.ts 同款）—— 不新引依赖、不用 cookie；替换理由写在本包 CHANGELOG 与 PR body（不静默改口径）。'],
    skip_reason='[backend-contract] 确定性页面判据（jest: frontend/bmini-app/tests/login-remember-account.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'auth', 'login', 'ux'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-042 [NORMAL] B 端 H5 输入框文字竖向居中（共享样式层 + 真几何 e2e：内层撑满外框 / 上下留白对称）（源: cases/bmini.yml）──
_CASE_BM_042 = EvalCase(
    id='BM-042',
    legacy_id='',
    title='B 端 H5 输入框文字竖向居中（共享样式层 + 真几何 e2e：内层撑满外框 / 上下留白对称）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-07 原话「H5 的输入框中的提示信息都不是居中的，文字偏上了」—— 生产 `https://app.migaozn.com/b/#/pages/auth/login/index`（390×844）实测：内层原生 input 26px 贴在 49.9px 外框顶部（上留白 0.5px / 下留白 23.4px）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**根因与修法**：Taro h5 的 `<Input>` 是两层 —— 外层 `taro-input-core`（拿 `className`，即用户看到的圆角框）+ 内层原生 `<input class="weui-input">`（Taro 自带 `height:1.47059em`）；外层 `display:block` 且无居中规则 ⇒ 内层行盒贴顶。修法落在**共享样式层** frontend/bmini-app/src/styles/input-center.scss（① 外框 `display:flex` + `align-items:center`；② 内层 `height:100%`），由 frontend/bmini-app/src/app.scss 引入。**只改竖向对齐**，不动任何尺寸 / 圆角 / 字号。', '判据 2·**真几何判据（不是字符串断言）**：tests/e2e/specs/bmini/bmini-input-center.spec.ts（配置 tests/playwright.bmini.config.ts；CI = .github/workflows/bmini-app.yml 的 `tabbar-geometry` job，该 job 的 run 自 issue #6478 起跑整个 `specs/bmini/` 目录）—— 对**未登录即可到达的 3 个输入面 / 15 个输入框**（登录页 9 + 工人登录页 3 + 首登强制改密页 3；2026-10-31 按 issue #8194 校正：工人登录页重写成共享组件 `WorkerLoginForm` ⇒ 选择器改 `.worker-login-form__input`、去掉「设备标签」一格，4 → 3；旧文写的 16 / 13 都是历史读数）逐个量「内层 input 高 ÷ 外框高 ≥ 0.90」「内层相对外框的上留白 == 下留白（±1 CSS px）」「上留白 > 0」。实测读数（390×844，Chromium，本地 dist 重建）：修后 登录页 47.906/49.906（上/下留白 1.0/1.0）、改密页 45.75/47.75（1.0/1.0）；修前（临时撤掉共享层引入 + 重建后同一 spec 实跑）登录页 26.0/49.906（1.0/22.91）、改密页 24.47/47.75（1.0/22.28）⇒ **3 failed** 且逐面具名报出占比与留白。⚠️ **工人登录页的新几何读数未重测**（issue #8194 重写该页；同一缺陷口径与同一全局共享层照旧判它，读数由 CI 腿的 `[input-center]` 日志打印，红了按日志逐面归因）—— 旧页的读数（45.75/47.75 修后、22.94/47.75 修前）保留在 `tests/e2e/specs/bmini/bmini-input-center.spec.ts` 的表里并标注为该页旧形态。未实测的输入面（报工页 / 坐席详情 / 工人入库 / 工人补打 / WorkerBar / FormCard）靠同一全局选择器构造性覆盖 + 台账登记（见 BM-043）。', '判据 3·**共享层必须真的接线且只许一份**：frontend/bmini-app/tests/input-center-guard.test.ts 断言共享层文件在位 + 被 frontend/bmini-app/src/app.scss 引入 + 三条居中声明都在；且 `taro-input-core` 只许出现在 frontend/bmini-app/src/styles 下的 scss（逐页打补丁 ⇒ 判红）。注入式红证（in-memory，实跑）：删 `@use` ⇒ 红；外框改回 `display:block` ⇒ 红；内层改回 `height:1.47059em` ⇒ 红；把规则抄进 frontend/bmini-app/src/pages/auth/login/index.scss ⇒ 红并具名。', '判据 4·**小程序端逐字不变**：共享层的两条选择器（`taro-input-core` / `.weui-input`）只存在于 Taro **h5** 产物 DOM；小程序编译产物里 `<Input>` 是单层原生 input，选择器一个元素都匹配不到 ⇒ 对小程序零影响。'],
    skip_reason='[backend-contract] 确定性判据（jest: frontend/bmini-app/tests/input-center-guard.test.ts；playwright: tests/e2e/specs/bmini/bmini-input-center.spec.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'layout', 'h5'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-043 [NORMAL] 类级元守卫：bmini 输入框面台账（未登记即红 / 台账只许缩短 / 空台账 fail-closed / 抽取不完全即红）（源: cases/bmini.yml）──
_CASE_BM_043 = EvalCase(
    id='BM-043',
    legacy_id='',
    title='类级元守卫：bmini 输入框面台账（未登记即红 / 台账只许缩短 / 空台账 fail-closed / 抽取不完全即红）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['任何人给 bmini 的某个页面新增一个 `<Input>`（或给已有输入框换一个 className）—— 无论他有没有确认那一面也走共享样式层，判据都要拦得住'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **未登记即红**：以 frontend/bmini-app/src 下全部 `.tsx`（先剥注释）为射程现取 `(文件, className)` 输入面配对集，凡有配对不在 frontend/bmini-app/tests/input-surface-ledger.json 里 ⇒ 具名判红。红证（实跑，in-test 注入）：造一个用 `<Input className='brand-new__input'>` 的页面 ⇒ 报出 `src/pages/brand-new/index.tsx::brand-new__input`。", '判据 2·**台账只许缩短 + 条目必须活着**：每条登记都必须仍能被扫到（面没了 ⇒ 该条已死 ⇒ 红）。红证：内存里把 frontend/bmini-app/src/pages/worker/reprint/index.tsx 的 `<Input>` 改名 ⇒ 红并报出 `src/pages/worker/reprint/index.tsx::admin-input`。', '判据 3·**抽取必须完整（fail-closed）**：`<Input>` 出现次数必须等于抽到的 className 数；把 className 挪成第二个属性（抽取口径漂移）⇒ 红，**不许**静默跳过。红证：内存变体 frontend/bmini-app/src/pages/sessions/detail/index.tsx ⇒ 红。', '判据 4·**台账不许空转**：条数为 0 ⇒ 红（「空」不等于「全部合规」）；射程一处 `<Input>` 都扫不到 ⇒ 红；每条登记必须声明 `label` 与非空 `case_ids`。红证：清空台账 / 清空射程 / 摘掉 label 与 case_ids，三条各自判红。', '判据 5·**条数现取、不写死**：守卫按射程现算配对集、与台账**双向相等**才算过；复算命令写在 frontend/bmini-app/tests/input-surface-ledger.json 的 `_recompute` 字段（文档与用例里都不写死条数）。'],
    skip_reason='[backend-contract] 确定性元守卫（jest: frontend/bmini-app/tests/input-center-guard.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-044 [NORMAL] B 端「问黄金策」输入条 H5 形态与语音可达性：placeholder 按「浏览器能不能录音」分流 + 样式必须落到内层原生控件（字体/占位符色/缩放手柄/单行行盒）（源: cases/bmini.yml）──
_CASE_BM_044 = EvalCase(
    id='BM-044',
    legacy_id='',
    title='B 端「问黄金策」输入条 H5 形态与语音可达性：placeholder 按「浏览器能不能录音」分流 + 样式必须落到内层原生控件（字体/占位符色/缩放手柄/单行行盒）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器（`app.migaozn.com/b/`）打开「问黄金策」：输入框里那行提示**不得承诺做不到的事**（浏览器真能录音时才写「按住说话」，不能录音时写键盘措辞），文字用 App 字体与设计色、右下**没有**原生缩放手柄、单行与动作行对齐'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **H5 按运行时能力分流**（2026-10-09 #6596 **改判**：H5 已把录音真做出来）：frontend/bmini-app/tests/chat-input-surface.test.tsx —— `TARO_ENV=h5` 且 `isVoiceSupported()` 为**假**（浏览器确实没有 `MediaRecorder`/`getUserMedia`）时 placeholder = 键盘措辞（`打字问黄金策，比如「今天经营怎么样？」`）且**不含**「按住说话」；能力为**真**时语音可达（**不许出现按不动的键**）。红证（实跑过）：把 placeholder 改回硬编码那一句 ⇒ 具名判红；把能力判定改回「h5 ⇒ 恒不支持」⇒ #6596 的判据集红', '判据 2·小程序（录音可用）保留「打字 or 说话」双语义 placeholder —— 一刀切成键盘措辞 ⇒ 红', '判据 3·🔴 **样式必须落到内层原生控件**：Taro H5 把 class 挂在包裹元素 `<taro-textarea-core>` 上，真正绘制文字的是内层 `<textarea class="taro-textarea">`；只写外层时实测内层跑的是**浏览器默认**（`monospace 13.33px` + 默认灰 placeholder + `resize` 手柄）。判据 = 输入态 SCSS 块含 `.taro-textarea` 内层选择器 + `font-family/font-size/line-height/color: inherit` + `resize: none` + `::placeholder` 用 `$text-secondary` + `min-height: 42px`（单行行盒，原 40px 小于行盒）；**反陷阱**断言块内不出现 `textarea` 标签选择器（H5 构建会把它改写成自定义元素 ⇒ 静默无效）。红证（各一次，实跑过）：删掉内层块 / `resize: none`→`both` / `min-height` 42→40px ⇒ 具名判红', '判据 4·真机读数（承载体，**不进 CI**）：真栈 + 真 Chromium（:8080 admin-api + :8001 ai-agent 跑被验 commit，H5 由本 worktree 构建产物供给）内层 `textarea` 读数由 `fontFamily: monospace` / `fontSize: 13.3333px` / `resize: both` / `::placeholder rgb(117,117,117)` 变为 App 字体 / `14.56px` / `none` / `rgb(90,107,124)`'],
    skip_reason='[backend-contract] 确定性前端/结构判据（jest: frontend/bmini-app/tests/chat-input-surface.test.tsx + frontend/bmini-app/tests/message-input.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'chat', 'input-bar', 'h5-surface'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-045 [NORMAL] 工人登录租户解析 - 企业编码（服务端唯一解析点）+ 兼容期 tenantId 兜底，非 1 租户不再恒 401（源: cases/bmini.yml）──
_CASE_BM_045 = EvalCase(
    id='BM-045',
    legacy_id='',
    title='工人登录租户解析 - 企业编码（服务端唯一解析点）+ 兼容期 tenantId 兜底，非 1 租户不再恒 401',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['租户 25（企业编码 migao）的工人在 B 端 H5（app.migaozn.com/b/，无租户子域、无 X-Tenant-Id 头）填 工号 + PIN + 企业编码 migao 登录 → POST /api/worker/login → 服务端按企业编码解析出租户 25、工人进自己的工作台（改前前端默认发 tenantId=1 ⇒ 恒 401）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**租户解析优先级唯一实现点**（backend/admin-api/src/main/java/com/migao/admin/worker/WorkerTenantResolver.java）：域名/网关头 → body `enterpriseCode` → `工号@企业编码` → 兼容期 body `tenantId`（打 WARN）→ 四档都没有 ⇒ 422 可行动文案「无法识别租户：请填写企业编码（向商家索取，例如 migao）」。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerAuthControllerTest.java', '判据 2·🔴 **反枚举与员工登录 #5485 同口径**：企业编码的存在性/可解析性有问题 ⇒ 与「工号不存在 / PIN 错」**同一个 401 同一文案**（`WorkerSessionService.AUTH_FAILED_MESSAGE` = 「工号或 PIN 不正确」），不得泄露企业是否存在；只有「完全没提供任何租户来源」才是 422。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerAuthControllerTest.java', '判据 3·**工号原样、企业编码规整**：切分按最后一个 `@`、右侧走 `LoginIdentifiers` 的企业编码口径、左侧**不转小写**（`CY-1001@migao` ⇒ 传给服务层的工号逐字是 `CY-1001`）—— 工号无字符集约束且服务端按大小写敏感等值匹配，故**不得**整体复用 `LoginIdentifiers.split`（它按员工用户名正则校验并小写化）。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerAuthControllerTest.java', '判据 4·**前端请求体与租户解耦**（类级守卫）：frontend/bmini-app/src 与 frontend/worker-h5/src 的工人登录/切换请求体**不含** `tenantId`、`DEFAULT_TENANT_ID` 不出现在工人登录链路的文件里、且请求体**含** `enterpriseCode`。证据：frontend/bmini-app/tests/worker-login-tenant-source-guard.test.ts + frontend/worker-h5/tests/worker-h5-login-tenant-source-guard.test.mjs', '判据 5·**印刷品红线未动**：短链 `/s/{短码}` 的路径段与短码口径一字未改，302 的 `Location` 在既有 `&tenant_id=` 之后**追加** `&tenant_code=<企业编码>`（旧包继续可用；企业编码查不到就不带该参数）。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerShortLinkControllerTest.java', '判据 6·**工人端 H5 从 URL 取企业编码**：`?tenant_code=` 形态合法则**预填**登录表单（仍是可编辑输入框），不合法/缺失 ⇒ null。证据：frontend/worker-h5/tests/worker-h5-scan-input.test.mjs'],
    skip_reason='[backend-contract] 确定性前后端判据（Java 单测 + jest + node --test 源码守卫），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'login', 'worker', 'tenant'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-046 [NORMAL] 手机端菜单 = 服务端按岗位投影（「我的」入口 + 「数据」生产待办块）；菜单拉不到 ⇒ 显式态，不照显（源: cases/bmini.yml）──
_CASE_BM_046 = EvalCase(
    id='BM-046',
    legacy_id='',
    title='手机端菜单 = 服务端按岗位投影（「我的」入口 + 「数据」生产待办块）；菜单拉不到 ⇒ 显式态，不照显',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['员工在手机端登录：什么岗位就只看到那个岗位的菜单（由服务端说了算）；菜单没加载出来时会明说并可重试，而不是给一堆点进去就报无权限的入口'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**服务端投影逐值**（真值 = backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java 的 `ALL` + `visibleFor`）：期望值**逐字取自线上真账号读数**（2026-10-08 19:58~20:09 +08，租户 25 四岗位在 `/b/` 的实拍）—— 通配 `*` ⇒ 5 项；客服（12 码，**无** `production:view`）⇒ pool/inbound/after-sales；商品管理员（8 码）⇒ pool/piecework/production-todos；财务（9 码）⇒ pool/inbound；空集合/null ⇒ 空清单（不是「全给」）。红证：把任一面的读码改一个字母 ⇒ 对应键序列对不上。证据：backend/admin-api/src/test/java/com/migao/admin/service/MobileSurfacesTest.java', '判据 2·**`/me` 字段与缺键语义**：`$.data.mobileSurfaces[0].key/title/route` 逐值；无独立页面的能力位（`production-todos`）⇒ `route` **缺键**（`doesNotExist`，不是 null、不是空串）—— 端侧据此只开页面内的块。红证：字段名改名/改蛇形 ⇒ 端侧菜单全灭（端侧读的就是这个键）+ 本判据红。证据：backend/admin-api/src/test/java/com/migao/admin/controller/AuthIntegrationTest.java', '判据 3·🔴 **端侧只渲染服务端给的面**：给 4 面 ⇒ 逐字按服务端顺序与标题渲染（端侧不自造、不排序）；只给 1 面 ⇒ 只出 1 个；给**空数组** ⇒ 一个入口都没有且**不是**错误态（服务端的明确答复 ≠ 失败）；🔴 **拉不到 ⇒ 显式「菜单没加载出来，点这里重试」+ 一个面都不渲染**（既不静默隐藏，也不照显）；点重试**真的**再拉一次 `/me`。红证：退回「未知 ⇒ 照显」⇒ 该用例红。证据：frontend/bmini-app/tests/mobile-menu-server-driven.test.tsx', '判据 4·**「数据」页生产待办块 = 同一份服务端清单开关**：清单含 `production-todos` ⇒ 渲染（每件可点即办）；🔴 **不含**（没有 `production:view` 的岗位 = 客服 / 财务实拍）⇒ **整块不渲染**（那块「无权限查看生产待办（需作业看板权限）」的噪音消失）；菜单**拉不到** ⇒ 照渲染（数据优先：不静默吞掉今天的待办）。红证：仍按权限码判 ⇒ 该用例红。证据：同判据 3 的文件', '判据 5·**类级守卫（服务端清单 ⇄ 端侧落地，双向）**：后端清单现取 5 项（反空跑）；有路由的面必须 ① 逐字在 `frontend/bmini-app/src/app.config.ts` 的 pages 在册 ② 在入口台账 `frontend/bmini-app/src/utils/pageEntries.ts` 登记过 ③ 读码与端侧台账 `ADMIN_SURFACES[].readPermission` 逐值相等；无路由的能力位必须被「数据」页**真的消费**（登记而不接线 = 台账自我复制）。红证：给 Java 清单加一条 bmini 没登记的 `new Surface(...)` ⇒ 判红。证据：frontend/bmini-app/tests/admin-surfaces-guard.test.ts（判据 8）', "判据 6·**源级：端侧不再自己判菜单码**：「我的」页源码不含 `visibleAdminSurfaces` / `useAdminPermissions` / `permissions.includes`，且确实调用 `useMobileMenu()`（反向自证，防空跑）；「数据」页的开关取 `s.key === 'production-todos'`。证据：同判据 3 的文件"],
    skip_reason='[backend-contract] 确定性判据（Java 单测 + jest + 源码守卫），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'menu', 'permission', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-047 [NORMAL] B 端 H5 底栏 4 项一律可见 + 端侧自绘 + 收起原生条（2026-10-18 裁定；旧「按权限裁剪」退场）（源: cases/bmini.yml）──
_CASE_BM_047 = EvalCase(
    id='BM-047',
    legacy_id='',
    title='B 端 H5 底栏 4 项一律可见 + 端侧自绘 + 收起原生条（2026-10-18 裁定；旧「按权限裁剪」退场）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['员工在手机端：底部 4 项（问黄金策 / 数据 / 坐席 / 我的）一律可见（用户 2026-10-18 逐字「跟问黄金策那个菜单一样都可见」），没权限的底栏页走「问黄金策」式的「需要管理员授权」；「我的」页的子菜单（智能派单 / 入库过账 / 售后处理 / 计件工资报表）仍按权限控制可见性（服务端 mobileSurfaces 投影）；数据面仍按权限拦'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**服务端投影逐值**（真值 = `MobileSurfaces.visibleTabsFor`）：商品管理员（8 码）/ 财务（9 码，均**无** `agent:session`）⇒ chat/dashboard/profile（**没有 sessions**）；客服（12 码，持 `agent:session`）⇒ 4 项齐全；一个码都没有的员工 ⇒ chat/profile（无码项）；`*` 通配 ⇒ 4 项。红证（实跑过）：把 `sessions` 的码改成 `null` ⇒ 同文件 `Tests run: 14, Failures: 4`。证据：backend/admin-api/src/test/java/com/migao/admin/service/MobileSurfacesTest.java', '判据 2·**`/me` 的 `mobileTabs` 字段与序列化**：`$.data.mobileTabs[0].key/route`、`[1].title` 逐值（字段名 = 端侧依赖：改名/改蛇形 ⇒ 端侧底栏退回「照显 4 项」+ 本判据红）。证据：backend/admin-api/src/test/java/com/migao/admin/controller/AuthIntegrationTest.java', '判据 3·🔴 **底栏 4 项一律可见**（用户 2026-10-18 裁定「跟问黄金策那个菜单一样都可见」）：服务端给 3 项（无 `sessions`）⇒ 端侧**仍画 4 格**（`merchant-tab-sessions` 照显）；标题取服务端、顺序取静态表（= 服务端 TABS 的逐值镜像）。红证（实跑过）：端侧跟着服务端删格 ⇒ jest 1 failed / 12。证据：frontend/bmini-app/tests/merchant-tabbar.test.tsx', '判据 4·**可见性不依赖那次 fetch**：拿不到菜单 / 空清单 ⇒ 同样 4 格（与判据 3 同形）—— 改前 loading 与 error 共用 fail-open 兜底，导致没有 `agent:session` 的账号「先看到坐席、点进去后那一格又消失」（用户 2026-10-18 实测）。证据：同判据 3', '判据 4b·**「我的」页子菜单无权限不可见**（同一裁定里的另一半）：`GET /api/auth/me` 的 `mobileSurfaces` 由服务端 `MobileSurfaces.visibleFor` 按生效权限过滤，端侧只渲染服务端给的面 + `error` 显式重试。证据：frontend/bmini-app/tests/profile-page.test.tsx + frontend/bmini-app/tests/mobile-menu-server-driven.test.tsx', '判据 4c·🔴 **没权限的底栏页 = 「问黄金策」同一做法**：服务端 `mobileTabs` 里没有该 tab（或接口 403）⇒ 整页「需要管理员授权」+ 可行动引导（「请联系企业管理员在「员工管理」中为你开通「X」权限」），**不白屏、不静默隐藏、不画成空态**；`loading` / `error` 一律不拦（拿不到菜单 ≠ 没权限）。呈现实现只有一份：`frontend/bmini-app/src/components/admin/SurfaceAccessGate.tsx`（`MibaoAccessGate` 复用它）。红证（实跑过）：让界面无视 `mobileTabs` ⇒ 数据页 `dashboard-gate-denied` / 坐席页 `sessions-gate-denied` 判红。证据：frontend/bmini-app/tests/dashboard-three-state.test.tsx + frontend/bmini-app/tests/sessions-page.test.tsx', '判据 5·🔴 **原生条必须被收起**（自绘底栏挂载即调 `Taro.hideTabBar({animation:false})`）：否则**两条底栏叠着**（自绘底栏上线后最容易出的形态）。红证（实跑过）：去掉该调用 ⇒ jest 1 failed / 12 + 几何腿 2 failed（`toBeHidden` Expected hidden / Received **visible**）。证据：frontend/bmini-app/tests/merchant-tabbar.test.tsx + tests/e2e/specs/bmini/bmini-tabbar.spec.ts 判据 7', '判据 6·**几何一格不放宽**（判据对象从原生条换成自绘条）：条贴底 ±1px / 条高 ∈[49,51]（页面高度算式按 Taro 的 50 留白）/ 每格图标与文字上下留白对称且都 > 0 / 水平居中 ±1px / 渲染出的四张图标 `src` 两两不同 / 当前页那一格 active。证据：tests/e2e/specs/bmini/bmini-tabbar.spec.ts + frontend/bmini-app/tests/tabbar-layout.test.ts（自绘底栏块：安全区只补一次、条不吃 `margin-bottom`、字面量 == Taro 现取的 50PX、flex 纵列居中、每格 `flex:1`）', "判据 7·**类级守卫（三处同源 + 接线 + 图标）**：服务端 `MobileSurfaces.TABS` ⇄ 端侧 `ALL_MERCHANT_TABS` ⇄ `app.config.ts` 的 `tabBar.list`（key/title/route 逐值，两处现取 4 项反空跑）；4 个 tab 页都必须接线 `<MerchantTabBar current='<自己的 key>' />`（新加 tab 页不接线 / 传错 key ⇒ 红）；8 张图标导入互不相同。红证（实跑过）：坐席页传 `current='chat'` ⇒ jest 1 failed / 12。证据：frontend/bmini-app/tests/merchant-tabbar.test.tsx"],
    skip_reason='[backend-contract] 确定性判据（Java 单测 + jest + playwright 几何腿），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'tabbar', 'permission', 'backend_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-048 [NORMAL] 「卡在哪」链路两处：数据页待办标签不折行 + 加工单详情显示这一单卡在哪（只读复用卡点面）（源: cases/bmini.yml）──
_CASE_BM_048 = EvalCase(
    id='BM-048',
    legacy_id='',
    title='「卡在哪」链路两处：数据页待办标签不折行 + 加工单详情显示这一单卡在哪（只读复用卡点面）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器（app.migaozn.com/b/）打开「数据」页：待办左侧标签显示成「卡在 / 哪」两行；点这条待办进「加工单详情」后，页里只有抬头 + 工序进度，看不到这一单到底卡在哪'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**标签不折行（形态，剔除注释后扫 scss）**：frontend/bmini-app/src/pages/dashboard/index/index.scss 的 `.task-item__tag` **不再**是固定 `width: 64px`（改宽度自适应 + 左右内边距）、`&-text` 有 `white-space: nowrap`、高度仍 40px；文案仍**全部**来自服务端 `type_label`（前端不缩字/不改字）。红证（实跑过）：样式退回 `width:64px` 且删 `nowrap` ⇒ 该文件 2 条判红；证据：frontend/bmini-app/tests/processing-order-detail-page.test.tsx', '判据 2·**宽度复算装得下 3 字**：按 scss 自己声明的 `font-size` 与左右内边距复算，`padding×2 + font-size×3 > 64`（即「卡在哪」这类服务端 3 字标签不再被 64px 挤成两行）。红证（实跑过）：把内边距改回 0 ⇒ 该条判红；证据：同上', '判据 3·🔴 **详情页真的接上了卡点面**：`GET /api/admin/production/stuck-points?processing_order_id=…` 被请求，且卡点块渲染出（工序显示名走唯一口径 `operationDisplayName` + 「等了 N 小时」+ 阈值与来源**逐字来自服务端**，前端不重算 stalled_hours/threshold）。红证（实跑过）：把卡点块渲染条件改恒 false ⇒ 4 条判红、无关判据照绿；证据：frontend/bmini-app/tests/processing-order-detail-stuck.test.tsx', '判据 4·**没有卡点 ⇒ 整块不渲染**（不摆「暂无卡点」空壳；`queryByTestId` 取不到才是机器读数，CSS 隐藏不算）；卡点面 403/失败 ⇒ 工序进度照旧渲染 + 卡点块一句可行动提示，**整页不报错**（三态不混淆）；证据：同判据 3', '判据 5·**该页仍零写请求**（issue #6567 的「纯只读」纪律不退化：只有 GET，不发任何写请求）；证据：frontend/bmini-app/tests/processing-order-detail-page.test.tsx', '判据 6·**浏览器几何/网络读数（承载体，不进 CI）**：acceptance/2026-10-09-bmini-three-fixes 的独立探针 —— 线上 BEFORE：`.task-item__tag` 宽 33.3 CSS px / `lineBoxes=2`、加工单详情 `stuckPointRequests=0` 且 `mentionsStuck=false`；修复后重放：`lineBoxes=1`、`stuckPointRequests=1`、正文出现工序名与「等了 74.6 小时」。红证 = 探针脚本同参数重跑（线上读旧产物即红）'],
    skip_reason='[backend-contract] 确定性前端判据（jest 形态 + DOM 断言）+ 独立几何探针；非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'production', 'dashboard', 'stuck-point', 'page-entry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-049 [NORMAL] 「问黄金策」输入条：单行 + 默认按住说话 + 键盘/语音切换，且底栏不再遮住输入条（H5 语音真落地）（源: cases/bmini.yml）──
_CASE_BM_049 = EvalCase(
    id='BM-049',
    legacy_id='',
    title='「问黄金策」输入条：单行 + 默认按住说话 + 键盘/语音切换，且底栏不再遮住输入条（H5 语音真落地）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家在手机浏览器（app.migaozn.com/b/）用「问黄金策」：输入条此前是两行（输入框一行、动作一行），而且被底部那条自绘栏整个压住、只剩一条缝；语音按钮点不动（H5 上没有录音实现）。改后希望：输入框/加图/语音在**一行**、有固定的宽高、默认就显示「按住说话」，并能在语音与键盘之间来回切'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**单行结构**：四个控件（键盘/语音切换键、中间区、加图、主动作键）都在同一条 `message-input__row` 内；`__row` 定高 88px（44pt）且行内 `nowrap`；证据：frontend/bmini-app/tests/chat-input-bar-layout.test.tsx', '判据 2·**默认语音模式 + 可切换**：首屏中间是「按住说话」且**没有**输入框；点键盘图标 ⇒ 中间换成输入框（placeholder 是键盘措辞）且「按住说话」消失，再点 ⇒ 变回；键盘模式下打字后主动作键变「发送」并发出输入的文字。红证（实跑过）：把默认态改回键盘 ⇒ 该文件多条判红；证据：同判据 1', '判据 3·🔴 **底栏留位（遮挡的根因之一）**：`.chat-page` 底部预留 == 底栏高（`50PX + 安全区`，且**取自同一条算式**，不是随手写的数）；`.chat-page` 是 `border-box`（状态栏 `padding-top` 不许把整页顶出视口 —— 改前它把 844 的视口顶成 864）；**安全区只补一次**（输入条自己不再补 `env(safe-area-inset-bottom)`，两处都补 ⇒ 底部留缝）；证据：同判据 1', '判据 4·🔴 **H5 语音是**真**实现的，不是空承诺**：能力探测不假绿（缺 `MediaRecorder` 或 `getUserMedia` ⇒ 判不支持）；`startRecording` 真请求麦克风并开录（不是只探测）；`stopRecording` 交回**可上传**的 blob（mime → 后端认得的扩展名，后端 `_get_audio_format` 认 webm/opus）；**麦克风被拒 ⇒ 抛出可行动的提示**（说清去哪开权限 + 还能怎么办）。红证（实跑过）：让探测只判 `MediaRecorder` 存在 ⇒ 该条判红；证据：frontend/bmini-app/tests/voice-browser-recorder.test.ts', '判据 5·**几何读数（常驻 e2e，承载体）**：真浏览器 390×844 下默认态是「按住说话」单行条，且 `coveredPx ≤ 0`、整页不高于视口；证据：tests/e2e/specs/bmini/bmini-chat-input-geometry.spec.ts', '判据 6·**独立探针读数（不进 CI）**：acceptance/2026-10-09-bmini-three-fixes/out/after-6596 —— 线上 BEFORE `coveredPx=70` / 整页 864（视口 844）；修后 `coveredPx=0` / 整页 844 / 默认 `按住说话` / 四控件纵向中心完全相等（`764.89`）。⚠️ 该目录同时记了一条坑：`index.html` 只引用固定名 chunk、不含应用代码 ⇒ 两个不同分支的构建它的 sha 竟逐字节相同，故探针另取 `app.js` 代码指纹'],
    skip_reason='[backend-contract] 确定性前端判据（jest 结构/DOM + playwright 几何），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'chat', 'message-input', 'voice', 'layout', 'safe-area'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-050 [NORMAL] 工人工作台第 4 条「拍照发货」：拍照 → 识别候选 → 工人核对（不确定的格子留空、绝不预填 0）→ 定位订单 → 生成发货单 → 实发读面说人话（源: cases/bmini.yml）──
_CASE_BM_050 = EvalCase(
    id='BM-050',
    legacy_id='',
    title='工人工作台第 4 条「拍照发货」：拍照 → 识别候选 → 工人核对（不确定的格子留空、绝不预填 0）→ 定位订单 → 生成发货单 → 实发读面说人话',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人（工号 + PIN 登录后）在工人工作台点第 4 条「拍照发货」：拍订单行 / 商品标签 → 识别出订单号等候选 → 逐格核对（没认出来的格子是**空的**，并说清要手输）→ 用单号定位订单 → 填实发数量 / 单位 / 运单号 → 生成发货单 → 看到「实发多少」（米 / 套 / 卷 + 经手人 + 照片张数）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**页面存在且可达**：新页 frontend/bmini-app/src/pages/worker/shipment/index 三件（`index.tsx` / `index.config.ts` / `index.scss`）在位、路由 `SHIPMENT_PAGE_ROUTE` 逐字出现在 frontend/bmini-app/src/app.config.ts 的 pages 里、并登记进 frontend/bmini-app/src/utils/pageEntries.ts 的入口台账（`from = src/pages/worker/home/index.tsx`，`nav = navigateTo`）。红证（实跑过）：从 PAGE_ENTRY_LEDGER 撤掉该条 ⇒ frontend/bmini-app/tests/page-entry-reachability.test.ts 判红（L2「面向用户的页面没有任何入口登记」）；把台账 `from` 指向只写着常量的 gaps.ts ⇒ 同文件 L3「声明存在 ≠ 可达」红。证据：frontend/bmini-app/tests/page-entry-reachability.test.ts', '判据 2·🔴 **不预填**（#5648 已落码的既有判据，一格未放松）：识别回执里 `value` 为 null / 空串的格子 ⇒ 输入框**留空**（**不是** 0、不是猜测值），并逐格列出「这一格要手输」（键 + 中文名 + 为什么）。红证（实跑过）：把 frontend/bmini-app/src/utils/inbound/shipment.ts 的 `prefillFromRecognition` 里 null 折成 `\'0\'` ⇒ frontend/bmini-app/tests/worker-shipment-service.test.ts 的「null / 空串 ⇒ 空串」1 failed + frontend/bmini-app/tests/worker-shipment-page.test.tsx 的判据 P3 1 failed（`Expected: "" Received: "0"`）。证据：frontend/bmini-app/tests/worker-shipment-page.test.tsx + frontend/bmini-app/tests/worker-shipment-service.test.ts', '判据 3·🔴 **请求体白名单**：`worker_id` / `worker_name` **一个字节都不进**发货 body（身份只由 `X-Worker-Session-Id` 解 —— 发货留痕是**责任凭证**）；白名单是**构造式**的（混入的额外键进不了 body）。红证（实跑过）：往 `buildShipBody` 里加一行 `worker_id: ...` ⇒ frontend/bmini-app/tests/worker-shipment-service.test.ts 的「请求体白名单」1 failed（Key 集合多出 `worker_id`）。证据：frontend/bmini-app/tests/worker-shipment-service.test.ts', '判据 4·🔴 **幂等键 `X-Client-Request-Id` 重试复用同一把**（超时重发不许重复发货）：一次发货动作生成一把、重试**不换键**（页面在 ref 里持有）。红证（实跑过）：把页面里的键改成每次提交新生成（`newShipmentRequestId()` 移进 `onSubmit` 内）⇒ frontend/bmini-app/tests/worker-shipment-page.test.tsx 的判据 P5「重试复用同一把幂等键」1 failed。证据：同判据 3 + frontend/bmini-app/tests/worker-shipment-page.test.tsx', '判据 5·**端点与字段面照后端逐字同名（零后端改动）**：`/api/worker/shipment/recognize`（body 只有 `images`，**不落库、不提交**）/ `/api/worker/shipment/orders/{orderId}/ship` / `/api/worker/shipment/orders/{orderId}`；识别字段面 = `order_no / product_name / quantity / width / height`（= 后端 `backend/ai-agent-service/app/vision/targets.py` 的 shipment target）。🔴 **定位订单不新造端点**：识别出的单号直接当 token 走既有读面 `GET /api/worker/production/scan?token=` 拿 `order_id`。证据：frontend/bmini-app/tests/worker-shipment-service.test.ts（S1）+ frontend/bmini-app/tests/worker-shipment-page.test.tsx（P4）', '判据 6·**实发读面说人话**：单位 / 套 / 卷三样来自服务端 `shipped_totals`；`set_count` / `roll_count` 为 null（这一维不适用）⇒ **不印 0**（三样都空 ⇒ 「—」）；读面没有发货单 ⇒ **不渲染空壳**面板。红证（实跑过）：把 `formatShippedTotals` 里的 null 折成 0 并照印 ⇒ frontend/bmini-app/tests/worker-shipment-service.test.ts 的「全空 ⇒ —」1 failed（收到 `0套 / 0卷`）。证据：同判据 3', '判据 7·**身份分流**：无工人 session ⇒ 只渲染引导（「请先用工号 + PIN 登录工人身份，再拍照发货」）+ 指向登录页工人入口的按钮，**一个发货写入口都不渲染**（商家设备点了只会 401）。红证（实跑过）：把页面的 `if (!workerReady)` 分支删掉 ⇒ frontend/bmini-app/tests/worker-shipment-page.test.tsx 的判据 P1 1 failed（`shipment-pick` 仍取得到）。证据：同判据 3', '判据 8·**复用既有通道，不新造第二条链**：照片上传走既有 `POST /api/worker/inbound/upload`（`uploadInboundPhoto`，multipart）；识别只走 vision 的 `shipment` target（端侧**没有** target 参数 ⇒ 工人面开不出 product / order 识别入口）。证据：frontend/bmini-app/tests/worker-shipment-page.test.tsx（P2）'],
    skip_reason='[backend-contract] 确定性前端判据（jest: frontend/bmini-app/tests/worker-shipment-page.test.tsx + frontend/bmini-app/tests/worker-shipment-service.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'shipment', 'page-flow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-051 [NORMAL] 手机端页面文案：工人 / 商家可见纯文本（零 markdown 标记、零研发术语）（源: cases/bmini.yml）──
_CASE_BM_051 = EvalCase(
    id='BM-051',
    legacy_id='',
    title='手机端页面文案：工人 / 商家可见纯文本（零 markdown 标记、零研发术语）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人 / 商家在手机上打开拍照入库 / 拍照补打入库标签 / 拍照发货 / 计件工资 / 派单 / 数据页：看到的字是能直接读懂的话（二维码拍清楚 ⇒ 手机当场就能认出来；认不出 ⇒ 换一种方式再认，会稍慢一点），屏幕上不出现 `**` 星号，也不出现「识别模型 / 服务端 / 解码 / 接口」这类研发术语'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**零 markdown 标记**：手机端页面（frontend/bmini-app/src/pages/** + src/components/**）的 JSX 文本与字面量里没有 `**` / `__` / 行内反引号 / 行首标题，**含被拆到多个 JSX 子节点的裸标记**（`<Text>{'**'}{n}{'**'}</Text>`）—— Taro `<Text>` 不渲染 markdown ⇒ 星号原样印在手机上。红证（实跑：`git checkout origin/main -- frontend/bmini-app/src` 后跑本判据）：frontend/bmini-app/tests/worker-copy-plain-text-guard.test.ts 判据 1 判红并逐条具名 **3** 处（inbound:337 / reprint:319 / shipment:182，逐字含 `**不会**` 与 `**实发**`）；修后 3 passed。证据：frontend/bmini-app/tests/worker-copy-plain-text-guard.test.ts", '判据 2·**零研发术语**（识别模型 / 大模型 / LLM / 服务端 / 后端 / 解码 / 接口 / 安全上下文 / 落库 / 幂等 / 裁定 / 判据 / 快照）：同一次红证实跑具名 **19** 处 —— 4 处商家手机端页面（计件工资 2 / 派单 1 / 数据页 1）、4 条打印失败提示、2 条打印回执（「服务端记第 N 次」）、5 条识别链文案源（recognizeFlow / barcodeDecode ×4 / recognizeGate / reprintFlow）；修后同一判据 0 命中。证据：同判据 1 + frontend/bmini-app/tests/worker-inbound-page.test.tsx（C9）+ frontend/bmini-app/tests/worker-reprint-page.test.tsx（P10）', '判据 3·**过程不静默，但不摆过程**（用户 2026-10-26 逐字「为什么会出现，移除掉」）：识别成功时页面顶部**零告警横幅** —— 旧形态两条（「这张照片里没找到二维码。」+「系统换一种方式再认了一次（会稍慢一点）…」）把一次**良性内部降级**说了两遍（§31 P2），还一路带到「入库标签」步、那步已经没有「下面的结果」（P3 摆内部标识）；「不静默」改由**确认卡**承担（`inbound-prefill-notice` + 卡标题「识别完成，请核对」/「请手工录入（识别不确定）」），服务端 `message` 原样上屏；补打的详情读失败仍是可行动的话（网络问题或系统暂时不可用 ⇒ 重试 / 报短码给文员）。红证（实跑）：`git stash push -- frontend/bmini-app/src` 后跑本判据 ⇒ frontend/bmini-app/tests/worker-inbound-page.test.tsx 的 C13 逐字收到 `inbound-notice-0` =「这张照片里没找到二维码。」⇒ 2 failed / 21 passed；恢复源码后 23 passed。证据：frontend/bmini-app/tests/worker-inbound-page.test.tsx（C13）+ frontend/bmini-app/tests/inbound-reprint-flow.test.ts（F5b）', '判据 4·**射程可复核**（防假绿 / 防假红）：判别力自证 = 抽到 > 20 条文案、三个被点名页面与每个登记文案源都在射程内（路径写错 ⇒ 当场红）；`exported` 模式只扫**顶层导出字符串常量** ⇒ 同文件里混着的研发台账字段（gaps.ts / reprintFlow.ts 的 why / audience，本来就用 markdown 写实现细节、且从不上屏）不误报。证据：同判据 1'],
    skip_reason='[backend-contract] 确定性文案守卫（jest: frontend/bmini-app/tests/worker-copy-plain-text-guard.test.ts + worker-inbound-page / worker-reprint-page / inbound-decode-first / inbound-reprint-flow / inbound-print-channel），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'copy', 'inbound'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-052 [NORMAL] 供应商侧布料标签拍照入库 - 型号 2659-4 归一后命中货号 2659-04 + 门幅没印按行业标准 2.8 + 逐格结果上屏 + 只读货号搜索（源: cases/bmini.yml）──
_CASE_BM_052 = EvalCase(
    id='BM-052',
    legacy_id='',
    title='供应商侧布料标签拍照入库 - 型号 2659-4 归一后命中货号 2659-04 + 门幅没印按行业标准 2.8 + 逐格结果上屏 + 只读货号搜索',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人拍一张供应商侧布料标签（型号：雪尼尔2659-4绵绵奶咖、52.4 米，**没有印门幅**）：页面先逐格显示系统读到的内容（型号 / 货号 / 品名 / 色号 / 门幅 / 米数，没认出来的那格明说要自己填），再说明「标签未印门幅，按行业标准 2.8 米」并预选出 2659-04-28；若标签印了门幅（3.2）则命中 2659-04-32；工人的出口除了核对还有只读的按货号 / 色名搜索'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**识别面要有「型号 / 货号」这一格**：backend/ai-agent-service/app/vision/targets.py 的 inbound 字段表含 model_no（标签写「雪尼尔2659-4绵绵奶咖」⇒ model_no=2659-4、color_name=绵绵奶咖），提示词带上该格中文名。红证（实跑过）：从 TARGET_FIELDS 的 inbound 删掉 model_no ⇒ backend/ai-agent-service/tests/test_vision/test_targets_inbound.py 的字段键元组与提示词 label 两处同时判红。证据：backend/ai-agent-service/tests/test_vision/test_targets_inbound.py', '判据 2·**匹配面归一化后命中（本条真实读数做夹具）**：品名 雪尼尔2659-4绵绵奶咖 + 色号 2659-4绵绵奶咖 + 库里 products.sku_code=2659 / product_skus 2659-04-28 与 2659-04-32（color_name=2659-04 绵绵奶咖）⇒ 命中 2 条。红证（实跑过）：去掉色号段补零，或摘掉 model_no 这一级，命中数 2 → 0（判据当场红）。证据：backend/admin-api/src/test/java/com/migao/admin/service/WorkerInboundServiceTest.java 的 SupplierLabel 组', '判据 3·**归一化是纯函数且不跨色号猜**：全角 / 分隔符（— · *）/ NO. 前缀 / 空白都归一到 2659-04；型号 2659-05 不得吃进 2659-04 的货号；型号只到 2659 时不去猜更细的 2659-04（商品侧更细 = 标签没说的信息，不补）。证据：同上（normalizationCollapsesEverySupplierSpelling / modelKeyDoesNotBleedAcrossColourNumbers）', '判据 4·**红线不动**：三个键全对不上 ⇒ 空匹配 + requiresManualEntry + products/product_skus 的 insert 零调用、库存零变更（不建品、不猜）；型号命中但色名一条不中 ⇒ 回该型号下的全部货号（交工人选），不是零命中。证据：同上（nothingMatchesStillRefusesToCreateAnything / modelHitWithoutColorHitStillReturnsTheModelCandidates）', '判据 5·**类级元守卫**：工人入库匹配面不得再出现「按商品名 / 色号精确相等匹配」（`.eq(Product::getName` / `.eq(ProductSku::getColorName`），且两条降级腿（sku_code 前缀 / color_name 包含）必须都在。红证（实跑过）：把其中任一句写回 backend/admin-api/src/main/java/com/migao/admin/service/WorkerInboundService.java ⇒ backend/admin-api/src/test/java/com/migao/admin/controller/WorkerInboundSurfaceGuardTest.java 判红。证据：同判据 5 的类', '判据 6·**零命中不再是无路可走（端侧）**：页面把服务端 fields 逐格上屏（空值那格写「没认出来（请自己填）」），并给只读的按货号 / 色名搜索入口 —— 搜到后点选即成为待入库货号，且搜索期间建单 / 过账零调用。issue #7892 起这个入口是**边输边出候选的下拉框**（满 2 字停手约 300ms 自动查，点一条即选中并收起；不足 2 字零请求 + 说明还差几个字），且旧查询的响应不得覆盖新查询的候选（先搜 26 慢、后搜 2659 快 ⇒ 面板只留 2659）。红证（实跑过）：页面不读 fields ⇒ inbound-field-* 一个都取不到；删掉搜索区 ⇒ inbound-sku-search 取不到、已选货号恒为「（未选）」；退回「输入 + 点按钮」⇒ 输入 2 字后取不到 inbound-sku-suggest（红）；去掉乱序守卫 ⇒ 慢响应把候选顶成 26 那批（红）。证据：frontend/bmini-app/tests/worker-inbound-page.test.tsx 的 C10 / C11 / C17 / C18 ＋ frontend/bmini-app/tests/inbound-sku-suggest.test.ts 的 C1~C6', '判据 7·**只读搜索端点两侧一致**：GET /api/worker/inbound/skus 在后端存在、端侧有常量且方法对得上（端侧 7 个端点全登记）。红证：端侧漏登记 ⇒ frontend/bmini-app/tests/inbound-api-contract.test.ts 的 C2 反向判红；写成 POST ⇒ C3 判红。证据：同文件', '判据 8·**门幅口径（来源：用户 2026-10-25 裁定）**：标签**没印门幅** ⇒ 取该商品 2.8 米那一档（唯一候选、预选，页面仍要工人勾「我确认」）；标签**写了 3.2** ⇒ 只取 3.2；标签写了库里**没有**的 3.5 ⇒ 零命中、**不回落** 2.8；该商品**没有 2.8 档** ⇒ 退回候选交工人选。归一：2.8 / 2.80 / 280 / 280cm 同一档。红证（实跑过）：把 selectByDoorWidth 里的默认门幅拿掉 ⇒ 默认门幅那两条用例当场红（命中数 1 → 2、doorWidthAssumed 恒 false）。证据：backend/admin-api/src/test/java/com/migao/admin/service/WorkerInboundServiceTest.java 的 DoorWidthRule 组', '判据 9·**识别面只抄不推**：backend/ai-agent-service/app/vision/targets.py 的 inbound「门幅」格在图没印时必须留空（2.8 是匹配侧的业务默认值，不是图上的事实）。红证（实跑过）：在 extract_fields 里给门幅兜一个 2.8 ⇒ backend/ai-agent-service/tests/test_vision/test_targets_inbound.py 的 TestDoorWidth 判红。证据：同文件', '判据 10·**默认值只在一处**：2.8 只出现在 WorkerInboundService.DEFAULT_DOOR_WIDTH（注释引用裁定），页面上的数字取服务端下发的 doorWidth。红证：页面写死 2.8 而服务端改值 ⇒ frontend/bmini-app/tests/worker-inbound-page.test.tsx 的 C12 断言数字对不上。证据：同文件'],
    skip_reason='[backend-contract] 确定性判据（pytest: backend/ai-agent-service/tests/test_vision/test_targets_inbound.py；maven: WorkerInboundServiceTest + WorkerInboundSurfaceGuardTest；jest: worker-inbound-page / inbound-api-contract），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'inbound', 'sku-gate', 'supplier-label'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-053 [NORMAL] 扫码报工落地面从 /w 改到 /b - 302 目标改成 /b/?t=<token>，h5 启动器把 token 交给报工页（/w 不再是任何跳转生产者）（源: cases/bmini.yml）──
_CASE_BM_053 = EvalCase(
    id='BM-053',
    legacy_id='',
    title='扫码报工落地面从 /w 改到 /b - 302 目标改成 /b/?t=<token>，h5 启动器把 token 交给报工页（/w 不再是任何跳转生产者）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人用微信扫加工单 / 水洗唛上的码（https://app.migaozn.com/s/<短码>）：服务端 302 到 /b/?t=<token> 后直接开到报工页（一屏：套号 / 部位 / 工序 / 应做 / 进度 → 报工 → 回执），不再出现 /w 路径'],
    expectations=['direct_reply'],
    data_checks=['判据 9·🔴 **302 目标必须带 hash 路由**（issue #7889，2026-10-27 现场：第一次进报工页、**关闭后再扫地址栏对而页面渲染成商家首页**）：`Location` = `/b/?t=<token>&tenant_id=…&tenant_code=…#/pages/worker/report/index`（`/i/` 补打同理 `#/pages/worker/reprint/index?code=<短码>`）。理由 = 只给 search 段时 Taro 先起默认页再由启动器 `redirectTo` 补救，那一步与路由初始化**竞态**（缓存命中时必翻车）。判据 = WorkerShortLinkControllerTest / ProcessingOrderShortLinkControllerTest / InboundLabelShortLinkControllerTest 的 Location 逐字断言 + frontend/bmini-app/tests/report-landing.test.ts 的 B3c 漂移守卫（服务端 REPORT_ROUTE/LANDING_ROUTE ⇄ gaps.ts 逐字一致）。红证：把 hash 段删掉 ⇒ 三个 Java 类立红（实测 2 failures）+ B3c 红。', '判据 10·🔴 **整站五页都在 `/b/report/` 下、且页内无绝对 `/w/` 链接**（issue #7915，2026-10-27 用户逐字「所有 /w 页面都要迁移到 /b，统一成手机端/小程序」）：`deploy/scripts/bmini-h5-verify-served.sh` 的 ③b 段**逐页**断言 `/b/report/{index,machine,piecework,shipment,rework}.html` 各自与线上 `/w/<同名页>` **逐字节一致**；`frontend/worker-h5/tests/worker-h5-pages.test.mjs` 的类级守卫断言 `src/**.mjs` 里**不得**出现绝对 `/w/` 链接（LD 形态：从 `/b/report/` 点进机台/计件/发货/返工后地址栏仍留在 `/b`）。红证：模拟器新增 `no_report_rewrite` 形态（删掉 rewrite）⇒ 落点变成 bmini 产物 ⇒ 判红并指名；把任一绝对链接改回去 ⇒ 类级守卫红。', '判据 1·**302 目标逐字 = /b/report/?t=…**（issue #7906 终态：手机端只留 `/b` 命名空间；`/b/report/` 在 nginx 里 `rewrite ^/b/report/(.*)$ /w/$1 last;` **内部落到 `/w/`**（deploy/swas/nginx.conf），即 URL 在 `/b` 下、页面本体是经多轮现场测试的 worker-h5 **一字未改**）；历史：issue #7899 曾把落点直接改回 `/w/`（用户「仍然没有合并替代 /b 页面的扫码报工页面」⇒ 才有了这条 rewrite 层）（issue #7899，2026-10-27 15:16 用户逐字「需要用 /w 的页面替代 /b 的报工页面，/w 的页面是经过多轮测试过的」）：`GET /s/{短码}` 与 `GET /o/{短码}` 的 `Location` = `/w/?t=<token>&tenant_id=<id>&tenant_code=<code>`；拼装仍只有 `WorkerShortLinkService.reportPageLocation` 一份；未知短码 ⇒ 404、已撤销 ⇒ 410 一格未变。为什么回退：`/b/` 那页是 #7812 P2a 的 MVP（能力远少于 `/w/` 的报工 + 机台 + 计件 + 发货四页），且 SPA 落点依赖启动器补救跳转（#7889 的第二次扫码故障即源于此）⇒ 现场先用经多轮测试的静态多页 `/w/`；`/b/` 报工页保留为**小程序原生面**载体，切回只需改这一条常量。红证：把 `REPORT_PAGE_PATH` 改回 `/b/` ⇒ WorkerShortLinkControllerTest / ProcessingOrderShortLinkControllerTest / WorkerShortLinkServiceTest 的 Location 逐字断言红（实测过的同款命令见 #7879 的 PR）。', '判据 01·**302 目标逐字 = /b/?t=…**：`GET /s/{短码}` 与 `GET /o/{短码}` 的 `Location` = `/b/?t=<token>&tenant_id=<id>&tenant_code=<code>`（查询串口径一字未动，只换落地面），拼装仍只有 `WorkerShortLinkService.reportPageLocation` 一份；未知短码 ⇒ 404、已撤销 ⇒ 410 一格未变。红证（实跑过）：把 `REPORT_PAGE_PATH` 改回 `/w/` ⇒ WorkerShortLinkControllerTest / ProcessingOrderShortLinkControllerTest / SecurityConfigTest / WorkerShortLinkServiceTest 的逐字断言全红（读数见 issue #7879 的实现 PR）。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerShortLinkControllerTest.java + frontend/bmini-app/tests/report-landing.test.ts', "判据 2·**h5 启动器把 token 交给报工页，且与 `?code=` 支线不串道**：`/b/?t=<token>` ⇒ `Taro.redirectTo('/pages/worker/report/index?t=<token>')`；`/b/?code=<短码>` 仍走补打页（负控）；一个参数都没有 ⇒ 不动路由；两者同时出现 ⇒ 以 `t` 为准。红证（实跑过）：删掉 src/app.tsx 的 `t` 支线 ⇒ report-landing.test.ts 的 B1 判红（页面停在 chat/index，工人扫开纸上的码什么也没发生）。证据：frontend/bmini-app/tests/report-landing.test.ts", '判据 3·**商家首页不抢路由**：URL 上带 `?t=` 时 `src/pages/chat/index/index.tsx` 不排「未登录 ⇒ 600ms 去商家登录页」的定时器（与 `?code=` 同款守卫）。红证：去掉那道闸 ⇒ B3 行为面带码落地判红（工人被踢到商家登录页，且没有任何东西会报警）。证据：frontend/bmini-app/tests/report-landing.test.ts', '判据 4·**报工页四条硬约束不因换落地面而放宽**：旧码（`granularity=order`）进选套态**绝不默认第 1 套**；`operation == null` ⇒ **不出报工按钮**；未登录 ⇒ 不出报工按钮且明说去哪登录；回执驱动下一屏（前端不猜）。红证（实跑过）：去掉「工序未确定不出现报工按钮」的判断 ⇒ worker-report-page.test.tsx 的 ② 判红。证据：frontend/bmini-app/tests/worker-report-page.test.tsx + frontend/bmini-app/tests/report-state.test.ts', '判据 5·**入口可达（两条都要在册）**：报工页在 `src/app.config.ts` 的 pages 里，且入口台账有**两条**发射方（工人首页的「扫码报工」行卡 / h5 启动器的 `?t=` 深链）；未登记即红、登记了没人指向也红。证据：frontend/bmini-app/tests/page-entry-reachability.test.ts + frontend/bmini-app/tests/report-landing.test.ts 的 B4', '判据 6·**反向钉住（/w 不再是跳转生产者）**：`WorkerShortLinkService.REPORT_PAGE_PATH` == `/b/`，且 src/app.tsx / 工人首页 / 入口台账的**代码**里不再出现 `/w/`（兼容期只允许「静态面可直连」这一条历史陈述，写在注释里）。红证：把 REPORT_PAGE_PATH 换回 `/w/` ⇒ report-landing.test.ts 的 B4 判红 + Java 四个测试类红。证据：frontend/bmini-app/tests/report-landing.test.ts'],
    skip_reason='[backend-contract] 确定性判据（maven: WorkerShortLink* / ProcessingOrderShortLink* / SecurityConfigTest；jest: report-landing / worker-report-page / report-state / page-entry-reachability），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'scan-landing'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-054 [NORMAL] 工人「我的计件」页（pages/worker/piecework/index）- 入口从报工详情页归位到工人菜单；金额只用服务端聚合（端侧不求和）、未定价显式列出且不计入合计、绝不印 0 元、只读（源: cases/bmini.yml）──
_CASE_BM_054 = EvalCase(
    id='BM-054',
    legacy_id='',
    title='工人「我的计件」页（pages/worker/piecework/index）- 入口从报工详情页归位到工人菜单；金额只用服务端聚合（端侧不求和）、未定价显式列出且不计入合计、绝不印 0 元、只读',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人从**工人菜单页**点「我的计件」：看到本月合计金额 + 件数 + 逐笔工序（本月，可切上月），只看到**自己的**计件；未定价的活显式列出「N 道未定价（未计入合计）」，不印 0 元；读不到时说「读取失败，请重试」（用户 2026-10-27 逐字「我的计件和发货…为什么做到报工详情页面？应该都作为工人菜单页面上的菜单」）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **金额只有一份聚合**：合计逐值渲染服务端 `amount_total`（`GET /api/worker/piecework?month=YYYY-MM` 的实现 = `ProductionService.workerPieceworkLedger`，只是 `ProductionService.aggregate` 之上「按当前工人 + 期间」的过滤投影，与商家端计件报表 / H5 `/b/report/piecework.html` 同一份算法）—— 端侧**不**把 `lines[].amount` 加起来。红证（实跑）：夹具给 `amount_total=2000` 而两行之和 1234.5，端侧改成求和 ⇒ frontend/bmini-app/tests/worker-piecework-page.test.tsx 的 ① red（屏上出现 ¥1,234.50）', '判据 2·🔴 **作用域只认会话**：请求只带可选 `month`（首屏一个参数都不带），**绝不**带 `worker_id` / `worker_name` —— 身份只由 `X-Worker-Session-Id` 解（涉钱面：工资归属不能由前端自称）。红证（实跑）：给 `readWorkerPiecework` 加一个 worker_id 入参 ⇒ ⑥ red（`mockRead.mock.calls[0]` 不等于 `[undefined]`）', '判据 3·🔴 **未定价显式列出且不进合计**：`unpriced` 原样渲染成「N 道未定价（未计入合计）」+ 逐条工序名，合计仍是服务端值；**一整月都是未定价**时只出未定价块（不出合计），**绝不**印 ¥0.00（未定价 ≠ 0 元，V90 / #4696）。红证（实跑）：把 `hasPriced` 改成恒真 ⇒ ③ red（`document.body.textContent` 出现 ¥0.00）', '判据 4·**空态 ≠ 读不到**：`amount_total=0` 且既无定价行也无未定价行 ⇒ 空态文案（「本月还没有计件…」）；读失败 / 形状不对（没有 `amount_total`）⇒ 「读取失败，请重试」+ 重试（再读一次），**不**冒充空态、不冒充 0 元。红证（实跑）：把 error 分支渲染成空态 ⇒ ⑤ red', '判据 5·**期间切换只按服务端给的 `can_prev` / `prev_period` / `can_next` / `next_period`**（端侧不推算月份边界）；401 ⇒ 清本机工人身份 + 引导去工人登录入口（`WORKER_TAB_LOGIN_ROUTE`）。红证（实跑）：端侧自己算上月（`new Date` 减一月）⇒ ⑦ red', '判据 6·**只读**：屏上只有 刷新 / 上月 / 下月 / 去登录 / 重试，没有任何写动作（不确认 / 不保存 / 不结算 / 不锁定 —— 用户 2026-09-19 裁定 2）。红证：加一个「确认」按钮 ⇒ ⑧ red', '判据 7·**入口归位 + 页在册**：本页在 `src/app.config.ts` 的 pages 里（`pages/worker/piecework/index`），入口 = 工人菜单页的「我的计件」行卡（静态字面锚点 `Taro.navigateTo({ url: PIECEWORK_PAGE_ROUTE })`），已登记进 `src/utils/pageEntries.ts` 的 `PAGE_ENTRY_LEDGER`（未登记即红 / 登记了没人指向也红）；**报工详情页不再发射这条入口**（反向钉住 = frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs）。红证（实跑）：把工人菜单页的行卡删掉 ⇒ frontend/bmini-app/tests/page-entry-reachability.test.ts 判红（「声明存在 ≠ 可达」并点名 route）；把 `<a href="./piecework.html">我的计件</a>` 加回报工页页头 ⇒ worker-h5 两条判据各自具名红'],
    skip_reason='[backend-contract] 确定性页面链路判据（jest: frontend/bmini-app/tests/worker-piecework-page.test.tsx + worker-home-page / worker-home-menu / page-entry-reachability；node --test: frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'piecework', 'money-surface'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-055 [NORMAL] 手机端登录记住企业编码：员工账号拆「用户名 @ 企业编码」两格（@ 固定不用输）+ 工人面预填企业编码（源: cases/bmini.yml）──
_CASE_BM_055 = EvalCase(
    id='BM-055',
    legacy_id='',
    title='手机端登录记住企业编码：员工账号拆「用户名 @ 企业编码」两格（@ 固定不用输）+ 工人面预填企业编码',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-27 原话「现在手机端登录不能默认显示企业编码，让浏览器记录下来上次登录的企业编码。员工登录也应该记录下来@企业编码，最好是只需要输入员工账号，除非是首次登录才需要输入，另外中间的@符号不需要输入，设计成两个输入框，中间固定@号，这样更好」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**两格 + 固定 @**：员工面渲染两个输入框（用户名 / 企业编码），中间的 `@` 是静态文本（不可编辑、不用输入），提交值 = 用户名@企业编码（单 `@`、各自去首尾空白）。红证（实跑）：把提交值改成只发用户名（漏 `@企业编码`）⇒ 判据 3 判红（1 failed / 10 skipped）。证据：frontend/bmini-app/tests/login-identifier-split.test.tsx（判据 1 / 3）+ frontend/bmini-app/tests/login-page.test.tsx', '判据 2·**首次登录才要输企业编码**：从未登录过 ⇒ 两格都空、缺企业编码在本地拦下不发请求；成功之后企业编码落 `login_tenant_employee` ⇒ 再次进入预填，换人登录只改用户名即可提交。证据：frontend/bmini-app/tests/login-identifier-split.test.tsx（判据 2 / 4 / 5）', '判据 3·**旧数据平滑迁移**：issue #6478 时代 `login_account_employee` 存的是整串 用户名@企业编码 ⇒ 进页按**最后一个 `@`** 拆开预填（与服务端 `LoginIdentifiers.split()` 同口径），老用户不必再「首次」一次、也不会把整串塞进用户名框。红证（实跑）：把 `splitLoginIdentifier` 的切分点改成「不切」⇒ 判据 6 判红（1 failed / 10 skipped）。证据：frontend/bmini-app/tests/login-identifier-split.test.tsx（判据 6）', '判据 4·**工人面两个入口同样记住企业编码**：登录页工人 tab 与独立工人登录页（frontend/bmini-app/src/pages/worker/login/index.tsx）都预填 `login_tenant_worker`、成功后写回；PIN 永不预填；员工面与工人面各用各的键（不互相串台）。红证（实跑）：把工人面企业编码初值改回空串（不预填）⇒ 判据 7a 判红（1 failed / 10 skipped）。证据：frontend/bmini-app/tests/login-identifier-split.test.tsx（判据 7a / 7b / 7c / 7d / 8）', '判据 5·🔴 **凭据红线不变**：企业编码可以落盘（它不是凭据 —— 没有用户名 + 密码 / 工号 + PIN 就登不进去），但密码 / PIN / 短信验证码一条都不许落盘，且落盘的是**编码本身**而不是整串标识。证据：frontend/bmini-app/tests/login-remember-account.test.tsx（判据 2 / 2b / 2c）+ frontend/bmini-app/tests/login-identifier-split.test.tsx（判据 4 的「落盘不含 @」）', '判据 6·**前端不解析租户**：两格只是拼回既有标识原样发服务端，租户仍只由服务端按企业编码解析（不传 tenantId；服务端逻辑与文案零改动）。证据：frontend/bmini-app/tests/worker-login-tenant-source-guard.test.ts + frontend/bmini-app/tests/login-page.test.tsx 的提交断言'],
    skip_reason='[backend-contract] 确定性页面判据（jest: frontend/bmini-app/tests/login-identifier-split.test.tsx / frontend/bmini-app/tests/login-remember-account.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'auth', 'login', 'ux'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-056 [NORMAL] 工人端库存修正 - 手机/APK 按批次把余量改成实盘米数（复用按批次盘点唯一写面 + 幂等 + 台账可答「谁/为什么」）（源: cases/bmini.yml）──
_CASE_BM_056 = EvalCase(
    id='BM-056',
    legacy_id='',
    title='工人端库存修正 - 手机/APK 按批次把余量改成实盘米数（复用按批次盘点唯一写面 + 幂等 + 台账可答「谁/为什么」）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['工人（工号 + PIN 登录后）在工作台点「库存修正」→ 搜批次（批次号 / 货号 / 缸号 / 入库单号任一段，空关键词 = 最近入库）→ 看到系统余量 → 选中该批 → 填实盘米数（例如系统说 45.5 米、实盘 42 米）+ 选原因（数量记错了 / 破损报废 / 报工选错批次 / 其他）→ 二次确认「系统 45.5 米 → 实盘 42 米」→ 提交 → 回执显示盘前 / 实盘 / 差异 / 盘后'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**未登录零读写**：无工人 session ⇒ 两个端点都 401，服务层零调用；页面只渲染引导 + 去登录（`WORKER_LOGIN_ROUTE`）。红证：摘掉 gate ⇒ `tests/worker-stock-page.test.tsx` ① 红；控制器侧 = `WorkerBatchStockControllerTest` ①（无 session ⇒ 401 且 `verify(never())`）', '判据 2·**复用唯一写面（不是第二套库存逻辑）**：本类不写任何表，只调 `BatchStocktakeService#stocktake`，参数逐值钉住（tenant 来自会话上下文、productId 由批次行解析、runId = `wc-<client_request_id>`、实盘行、审计来源）。红证：把 productId 改成请求体自带 ⇒ `WorkerBatchStockServiceTest` ① 的 ArgumentCaptor 断言红', '判据 3·**幂等**：同一 `client_request_id` 的重复提交 ⇒ 第二遍 `status=replayed`、库存只变一次；缺 / 超长 / 非法字符 ⇒ 422（`WORKER_STOCK_CORRECTION_REQUEST_ID`）。红证：把 runId 换成随机值 ⇒ 重放判据红（真库面 = `uk_batch_consumption_stocktake` 唯一索引）', '判据 4·**实盘为准、零差异零写入**：实盘 == 当刻余量 ⇒ `unchanged`，不落批次分录、不动 SKU 库存。红证：把 `unchanged` 也当 `applied` 回 ⇒ 回执判据红', '判据 5·**准入先于写入**：负数 ⇒ 400（`WORKER_STOCK_CORRECTION_ACTUAL_NEGATIVE`，文案说清「最小 0，报损请选破损/报废」）；超 1 位小数 / 缺实盘 / 未知原因 / 备注超 60 字 ⇒ 422；批次不属于本租户 ⇒ 404；以上全部零写入。红证：放行 `-1` ⇒ `WorkerBatchStockServiceTest` ③ 红', '判据 6·**台账答得出谁/为什么**：批次分录 `operator` = 工人姓名；`note` 以「工人库存修正：姓名（工号 X），原因 …」开头（工人 session 在 `resolveOperator()` 里是 system ⇒ 不显式给就是假账）。红证：把 audit 去掉 ⇒ `WorkerBatchStockServiceTest` ① 的 audit 断言红', '判据 7·**端侧三态分开说 + 传输白名单**：applied / unchanged / replayed 三句互不相同（「已修正 / 与系统一致未写入 / 此前已记过账」）；提交体只有 `batch_id` / `actual_meters` / `reason` / `note` / `client_request_id`，**没有** worker_id / worker_name / tenant_id。红证：把身份字段塞进 body ⇒ `tests/worker-stock.test.ts` ③ 红', '判据 8·**端侧幂等键语义**：同一份输入重试 ⇒ 复用同一个 `client_request_id`；改了米数 / 原因 / 备注 ⇒ 换新键（否则服务端按回放处理，静默不落账）。红证：每次提交都新生成 ⇒ `tests/worker-stock-page.test.tsx` ⑦ 红', '判据 9·**入口可达 + 写入口台账 + 视觉形态**：`pages/worker/stock/index` 登记进 `app.config.ts` 且工人首页有**真导航**（漏登记 = 死链 ⇒ `page-entry-reachability` 红）；`submitBatchCorrection(` 登记进工人写入口台账（未登记即红，且必须命中身份分流 + 引导登录记号）；新页 `__gate` 卡片有可见边界、页面有非白底色（`worker-card-contrast-guard`）', '判据 10·**菜单开关可设**：`WorkerPages.STOCK = stock` 进闭词表与默认集合，商家后台「设置工人端菜单」能看到「库存修正」（目录端点 `labels.stock`）；`/w/` 的闭词表镜像同批更新（`worker-h5-pages` 逐值比对）。红证：只改后端不改镜像 ⇒ `frontend/worker-h5/tests/worker-h5-pages.test.mjs` 红'],
    skip_reason='[backend-contract] 确定性判据（maven: WorkerBatchStockControllerTest / WorkerBatchStockServiceTest / WorkerPagesTest / WorkerPageCatalogControllerTest；jest: worker-stock-page / worker-stock / page-entry-reachability / worker-surface-ledger / worker-card-contrast-guard；node: worker-h5-pages），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'stock', 'batch-stocktake', 'idempotency'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── BM-057 [NORMAL] 小程序工人登录 = 终端 /w/ 同一份表单 - 扫码报工页未登录就地登录（不跳三角色登录页），工人首页入口复用同一组件（源: cases/bmini.yml）──
_CASE_BM_057 = EvalCase(
    id='BM-057',
    legacy_id='',
    title='小程序工人登录 = 终端 /w/ 同一份表单 - 扫码报工页未登录就地登录（不跳三角色登录页），工人首页入口复用同一组件',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['新手机第一次扫纸上的码（GET /s/<短码> → 302 → /b/?t=<token>）⇒ 本机没有工人 session ⇒ 扫码报工页**就地**显示登录表单：标题「工人报工」/ 副标题「工号 + PIN 登录（手机 / PAD 均可，无需微信）」/ 企业编码（向商家索取）→ 工号 → PIN / 按钮「登 录」，与终端 /w/ 逐字一致；**没有**「设备标签」一格，也**没有**「去登录工人身份」跳转按钮；登录成功留在本页继续手里的那个码（无码则回工人首页）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**跨端逐字一致**（真值 = frontend/worker-h5/src/render.mjs 的 loginView()）：标题 / 副标题 / 三个字段标签**及顺序** / 按钮文案逐字相等，且不出现「设备标签」字段；渲染面同序（标题 → 副标题 → 企业编码 → 工号 → PIN → 按钮），错误位在字段**上方**（与 /w/ 的 .wh5-error 同位）。红证（实跑，真语料注入）：改一个标签 ⇒ 4 failed / 2 passed；把两个字段换顺序 ⇒ 3 failed / 3 passed。证据：frontend/bmini-app/tests/worker-login-parity.test.ts', '判据 2·**报工页未登录就地登录**：渲染三个输入 + 「登 录」，没有「去登录工人身份」跳转按钮、不导航去三角色登录页、不出报工按钮；🔴 未登录**不渲染页头**（`/w/` 的登录屏只有一张卡片 —— 用户 2026-10-31 裁定「不一致，需要收口」：否则「扫码报工」+「工人报工」两层标题），登录成功后才出现页头（含当前工人）。红证（实跑）：摘掉就地表单渲染（只留 import）⇒ 9 failed / 5 passed（台账具名「就地渲染工人登录表单」+ 页面 find 不到表单）；未登录态把页头加回来 ⇒ 2 failed / 9 passed（两条 ① 各自具名 `worker-report-header`）。证据：frontend/bmini-app/tests/worker-report-login.test.tsx + frontend/bmini-app/tests/worker-report-page.test.tsx', '判据 3·**登录后接着报手里的码**：带码（/b/?t=<token>）⇒ 留在本页并 scanResolve 该码（不回首页、不跳走）；无码 ⇒ 回工人首页；失败 ⇒ 错误上屏、不解析码。跨登录那一步的码走 utils/reportEntry.ts 的既有一次性记录 rememberReportReturn / takeReportReturn（登录前 write、成功后 take 即清），不新造第二套「待报码」通道。证据：frontend/bmini-app/tests/worker-report-login.test.tsx', '判据 4·**工人首页入口复用同一组件**（同一份表单的**第二个入口**，不是第二份实现）：「去登录工人身份」与「退出工人身份」都落 frontend/bmini-app/src/pages/worker/login/index.tsx（WORKER_LOGIN_ROUTE）；三角色登录页（/pages/auth/login/index?tab=worker）保留为常规入口、本单不改；该页重写成共享组件的一层壳（只负责调 workerLogin 与登录后去向：有 pending code 回报工页、从入库/补打/库存 navigateTo 过来则 navigateBack、页面栈只有自己则回工人首页）。证据：frontend/bmini-app/tests/worker-home-page.test.tsx + frontend/bmini-app/tests/login-identifier-split.test.tsx + frontend/bmini-app/tests/login-remember-account.test.tsx', '判据 5·**台账同批更新（未登记即红 / 只许缩短）**：报工页新增 workerLogin( 写入口登记；其引导形态改成 login_in_place_token（认 JSX 渲染形态 <WorkerLoginForm，import 提及不算）；工人首页 login_route_token 改 WORKER_LOGIN_ROUTE；入口台账把「工人首页 → 三角色登录页」换成「工人首页 → 工人登录页」；输入面台账把 worker-login__input 换成共享组件的 worker-login-form__input。证据：frontend/bmini-app/tests/worker-surface-ledger.test.ts + frontend/bmini-app/tests/input-center-guard.test.ts + frontend/bmini-app/tests/page-entry-reachability.test.ts'],
    skip_reason='[backend-contract] 确定性跨端文案/装配判据（jest: worker-login-parity / worker-report-login / worker-report-page / worker-home-page / worker-surface-ledger / input-center-guard / page-entry-reachability），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['bmini', 'worker', 'login', 'parity', 'h5'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_BM_001,
    _CASE_BM_002,
    _CASE_BM_003,
    _CASE_BM_004,
    _CASE_BM_005,
    _CASE_BM_006,
    _CASE_BM_008,
    _CASE_BM_009,
    _CASE_BM_010,
    _CASE_BM_011,
    _CASE_BM_012,
    _CASE_BM_013,
    _CASE_BM_014,
    _CASE_BM_015,
    _CASE_BM_016,
    _CASE_BM_017,
    _CASE_BM_018,
    _CASE_BM_019,
    _CASE_BM_020,
    _CASE_BM_021,
    _CASE_BM_022,
    _CASE_BM_023,
    _CASE_BM_024,
    _CASE_BM_025,
    _CASE_BM_027,
    _CASE_BM_026,
    _CASE_BM_028,
    _CASE_BM_029,
    _CASE_BM_030,
    _CASE_BM_031,
    _CASE_BM_032,
    _CASE_BM_033,
    _CASE_BM_034,
    _CASE_BM_036,
    _CASE_BM_037,
    _CASE_BM_038,
    _CASE_BM_040,
    _CASE_BM_041,
    _CASE_BM_042,
    _CASE_BM_043,
    _CASE_BM_044,
    _CASE_BM_045,
    _CASE_BM_046,
    _CASE_BM_047,
    _CASE_BM_048,
    _CASE_BM_049,
    _CASE_BM_050,
    _CASE_BM_051,
    _CASE_BM_052,
    _CASE_BM_053,
    _CASE_BM_054,
    _CASE_BM_055,
    _CASE_BM_056,
    _CASE_BM_057,
)
