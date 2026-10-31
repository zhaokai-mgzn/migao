# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: hr（源: cases/hr.yml，13 条）

from ._schema import Difficulty, EvalCase, Skill

# ── HR-001 [SMOKE] 员工列表（源: cases/hr.yml）──
_CASE_HR_001 = EvalCase(
    id='HR-001',
    legacy_id='5.1',
    title='员工列表',
    skill=Skill.GENERAL,
    difficulty=Difficulty.SMOKE,
    user_inputs=['有哪些员工'],
    expectations=['employee_manage(action=list)'],
    data_checks=['返回姓名/角色/状态', 'position 为空时回退 role 值'],
    skip_reason='',
    tags=['query', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-002 [NORMAL] 创建员工 - 开账号（源: cases/hr.yml）──
_CASE_HR_002 = EvalCase(
    id='HR-002',
    legacy_id='5.2',
    title='创建员工 - 开账号',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['新客服王五 13812345678，密码 Abc123456，开账号', '确认'],
    expectations=['employee_manage(action=list)'],
    data_checks=['收集确认后创建成功 —— 机器断言见 must_succeed[employee_manage(action=create)]（工具真的返回 success）｜ ⚠️ 2026-09-24（issue #5247，B 端只读化）：该 `must_succeed` 已随写 action `create` 下线而整格移除（悬空声明），本条作为**历史判据说明**保留；本用例已退役（见 `skip_reason`），能力下线由工具层单测与绑定判据承担'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「创建员工/开账号」（employee_manage / action=create）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 employee_manage(action=list)（只读查询员工列表）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['create'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'employee_remove', 'employee_name': '王五', 'employee_phone': '13812345678'}],
    namespaces=['employee_name:王五', 'employee_phone:13812345678'],
    precondition=[{'type': 'employee_count_for_phone', 'source': '13812345678', 'expect': 0, 'max_growth': 1}],
)

# ── HR-003 [NORMAL] 禁用员工账号（源: cases/hr.yml）──
_CASE_HR_003 = EvalCase(
    id='HR-003',
    legacy_id='5.3',
    title='禁用员工账号',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['手机号 13700137000 的那位员工（王五）离职了，停用账号', '确认停用'],
    expectations=['employee_manage(action=list)'],
    data_checks=['二次确认后停用', '目标是手机号 13700137000 的种子员工（debug_employee_wangwu），不是任何同名账号'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「停用员工账号」（employee_manage / action=toggle_status）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 employee_manage(action=list)（只读查询员工列表）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['status', 'destructive'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'employee_reactivate', 'employee_name': '王五', 'employee_phone': '13700137000'}],
    namespaces=['employee_name:王五', 'employee_phone:13700137000'],
    precondition=[{'type': 'employee_count_for_phone', 'source': '13700137000'}],
)

# ── HR-004 [SMOKE] 角色列表（源: cases/hr.yml）──
_CASE_HR_004 = EvalCase(
    id='HR-004',
    legacy_id='5.4',
    title='角色列表',
    skill=Skill.GENERAL,
    difficulty=Difficulty.SMOKE,
    user_inputs=['系统有哪些角色'],
    expectations=['role_manage(action=list)'],
    data_checks=['返回角色列表'],
    skip_reason='',
    tags=['query', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-005 [NORMAL] 查角色与权限（只读；原「创建角色」随 #5247 写能力下线改判）（源: cases/hr.yml）──
_CASE_HR_005 = EvalCase(
    id='HR-005',
    legacy_id='5.5',
    title='查角色与权限（只读；原「创建角色」随 #5247 写能力下线改判）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['现在有哪些角色？', '第一个角色有哪些权限？'],
    expectations=['role_manage(action=list)', 'role_manage(action=all)'],
    data_checks=['角色/权限清单逐条来自服务端（role_manage list / list_permissions），不得编造；只读，不得声称已创建或已分配权限'],
    skip_reason='',
    tags=['create', 'permission'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    namespaces=['role_code:stock_keeper'],
)

# ── HR-006 [NORMAL] 岗位权限体系 - 注册新租户初始化五岗默认权限 + 员工权限快照式解析（#2969）（源: cases/hr.yml）──
_CASE_HR_006 = EvalCase(
    id='HR-006',
    legacy_id='',
    title='岗位权限体系 - 注册新租户初始化五岗默认权限 + 员工权限快照式解析（#2969）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['新租户注册后有哪些默认岗位？每个岗位的默认权限是什么？员工权限与岗位默认权限什么关系？'],
    expectations=['direct_reply'],
    data_checks=['审批通过创建租户时初始化五岗种子：管理员(admin)/客服(customer_service)/运营(operator)/销售(sales)/财务(finance)，每岗 status=active', '非 admin 岗位预置默认权限（role_permissions 落库）：客服=看板/订单查看/客户/会话；运营=看板/订单/商品/加工/客户/财务/会话/员工列表；销售=看板/商品/订单查看/客户；财务=看板/订单查看/财务', 'getUserPermissions 快照式：admin 恒 ["*"]；有 users.permissions 快照（员工管理保存勾选）直接返回快照不合并岗位角色；无快照（历史数据/ai-agent 创建）回退 role_permissions/硬编码', 'V29 迁移为存量租户补齐 sales/finance 岗位与五岗 role_permissions（幂等）'],
    skip_reason='注册种子的五岗/默认权限/快照解析为 Java 单测验证（RegistrationServiceTest/RoleServiceTest），非 LLM 工具行为，不进入 agent-eval 冒烟',
    tags=['position', 'permission', 'seed'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-007 [NORMAL] 员工管理列表排除 C 端消费者账号（role=customer，issue #3004）（源: cases/hr.yml）──
_CASE_HR_007 = EvalCase(
    id='HR-007',
    legacy_id='',
    title='员工管理列表排除 C 端消费者账号（role=customer，issue #3004）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['有哪些员工？查一下员工列表里为什么有微信用户'],
    expectations=['employee_manage(action=list)'],
    data_checks=['GET /api/admin/users 员工分页查询默认排除 role=customer（C 端小程序登录自动建号的消费者账号，见 AuthService.findOrCreateMiniProgramUser）', '不传角色筛选时列表只含员工角色（admin/operator/自定义岗位等），nickname=微信用户、无手机号的消费者账号不出现', '显式传 role=customer 筛选时同样不返回消费者（员工管理范畴定义：customer 不属于员工）'],
    skip_reason='查询条件由 Java 单测验证（UserServiceTest.getUserPage_ExcludesCustomerRole 断言 wrapper 含 role <> customer），非 LLM 工具行为差异，不进入 agent-eval 冒烟',
    tags=['employee', 'list', 'scoping'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-008 [NORMAL] 更新员工手机号 - 写入真的落库（update 写路径首次覆盖，issue #3593）（源: cases/hr.yml）──
_CASE_HR_008 = EvalCase(
    id='HR-008',
    legacy_id='',
    title='更新员工手机号 - 写入真的落库（update 写路径首次覆盖，issue #3593）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['手机号 13700137000 的这位员工（王五）换号了，帮我把他的手机号改成 13900139111', {'auto_respond': {'fallback': '确认'}}, {'auto_respond': {'fallback': '确认'}}],
    expectations=['employee_manage(action=detail)'],
    data_checks=['PUT /api/admin/users/debug_employee_wangwu 落库后 users.phone = 13900139111，而不是 200 假成功（库里仍是 13700137000）', '同租户内手机号唯一：13900139111 不与既有用户（13700137000 / 13800138000 / 13900139000）冲突，写入不被唯一校验拒绝'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「更新员工资料」（employee_manage / action=update）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 employee_manage(action=detail)（只读查询员工详情）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['update', 'write', 'confirm'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    namespaces=['employee_phone:13700137000', 'employee_phone:13900139111'],
    precondition=[{'type': 'employee_count_for_phone', 'source': '13700137000', 'expect': 1, 'max_growth': 0}],
)

# ── HR-009 [NORMAL] 黄金策无创建员工能力——须如实说明并给后台开通路径（不得自旋重试 / 不得谎称已开）（源: cases/hr.yml）──
_CASE_HR_009 = EvalCase(
    id='HR-009',
    legacy_id='',
    title='黄金策无创建员工能力——须如实说明并给后台开通路径（不得自旋重试 / 不得谎称已开）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['帮我开个客服账号，姓名李四，手机号 13800009999，密码 Test123456', '那我要怎么才能给员工开账号？'],
    expectations=['direct_reply or nav_guide'],
    data_checks=['同一失败的调用不得跨轮重复（自旋）：本仓库 runner 目前**没有**跨轮重复调用断言，故该条只能靠 LLM 层人工/盲审读报告 —— 如实登记，不假装已机器判定', '如实说明黄金策不提供创建员工/开账号能力（B 端只读化 #5247：写能力与对应 tools 已从 B 端整体移除），并给出后台「员工管理」页面开通路径（正向判据 want_text 要求全程出现「后台」）', '不得出现「请稍后重试」/「系统不支持」这类编造或敷衍话术（如实说明「黄金策做不到、请去后台」是**正确**回答，不在禁词内）'],
    skip_reason='',
    tags=['permission', 'denial', 'auth', 'regression'],
    persona='mibao',
    debug_user='',
    debug_permissions='employee:list',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=[{'any_of': ['系统不支持', '请稍后重试']}],
    forbidden_tools=['order_manage', 'product_manage'],
    want_text=[{'any_of': ['开通', '后台', '入口', '管理员']}],
    db_verify=[{'fetch': 'employee_absent', 'name': '李四', 'phone': '13800009999'}],
    pre_clean=[{'type': 'employee_remove', 'employee_name': '李四', 'employee_phone': '13800009999'}],
    namespaces=['employee_name:李四', 'employee_phone:13800009999'],
    precondition=[{'type': 'debug_permissions_effective', 'source': 'employee:list'}],
)

# ── HR-010 [NORMAL] 有能力时不得误拒（正向对照）- 持 employee:create 时同一请求必须真的执行（源: cases/hr.yml）──
_CASE_HR_010 = EvalCase(
    id='HR-010',
    legacy_id='',
    title='有能力时不得误拒（正向对照）- 持 employee:create 时同一请求必须真的执行',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['帮我开个客服账号，姓名李四，手机号 13800009999，密码 Test123456', '确认'],
    expectations=['role_manage(action=list)'],
    data_checks=['持 employee:create 的员工请求同一动作时，agent 必须走完创建（不得以权限为由拒绝）', '创建结果须回执给用户（账号已开/密码等），不得只展示查询结果就停（HR-003/PP-006/PR-005 同族）'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「创建员工」（employee_manage / action=create）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 role_manage(action=list)。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。｜ 退役登记纪律（守卫 tests/unit_ci_workflows/test_eval_debug_permissions_precondition.py 的 TestThePairIsIsolatedAndRegistered 要求「skip_reason 非空时必须点名产品侧归属 + 摘除判据」）：**产品侧归属 = #4147**（注入面「可用能力（仅限以下，超出即无权）…不要调用工具尝试」收窄为「先发起调用，由系统给出权威结论；真被拒时不再重试」，PR #4164；实现见 backend/ai-agent-service/app/graph/skills/base_skill.py 的 _inject_permission_scope）—— 本用例与 HR-009 正是该产品侧改动的**允许半 / 拒绝半对照**，#5247 下线写能力后对照前提消失故退役。**un-skip 判据（怎么才算修好、可摘掉本 skip_reason）**：当 B 端重新获得「创建员工」能力（employee_manage 的 action=create 回到源码且重新绑定 B 端，即 #5247 的只读裁定被撤销或改写）时 —— 把 expectations 改回 employee_manage(action=create) 或 role_manage 的 OR 串、恢复 must_succeed[employee_manage(action=create)] 与 db_verify[employee]（李四落库），并摘掉本 skip_reason。',
    tags=['permission', 'create', 'positive-control'],
    persona='mibao',
    debug_user='',
    debug_permissions='employee:create',
    form_prefill=[],
    forbidden_card_text=[],
    db_verify=[{'fetch': 'employee', 'name': '李四', 'expect_fields': {'phone': '13800009999'}}],
    pre_clean=[{'type': 'employee_remove', 'employee_name': '李四', 'employee_phone': '13800009999'}],
    namespaces=['employee_name:李四', 'employee_phone:13800009999'],
    precondition=[{'type': 'debug_permissions_effective', 'source': 'employee:create'}],
)

# ── HR-011 [NORMAL] 回退路径岗位默认权限与种子矩阵对齐（含客服/销售/财务三岗从空表补齐）+ 立「回退 ⊆ 种子 / 差异具名登记」常驻判据（issue #5683）（源: cases/hr.yml）──
_CASE_HR_011 = EvalCase(
    id='HR-011',
    legacy_id='',
    title='回退路径岗位默认权限与种子矩阵对齐（含客服/销售/财务三岗从空表补齐）+ 立「回退 ⊆ 种子 / 差异具名登记」常驻判据（issue #5683）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['历史账号（无 user_roles 行 / 无 users.permissions 快照）以 operator / customer_service / sales / finance 岗位登录后打开侧边栏'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **回退不得比种子更宽**（逐角色码穷举）：`回退 − 种子` 非空 ⇒ 无条件红，且**不提供登记出口**（绕过岗位权限页的真放宽）。执行点 = tests/unit_ci_workflows/test_agent_permission_parity.py 的 problems_role_default_parity ① 段。红证（实测）：往回退里加一个种子没有的码 ⇒ 具名红。', '判据 2·🔴 **「整角色没有 case」形态**（`∅ ⊆ 种子` 恒真 ⇒ 只看 ⊆ 会全绿）：种子里出现的每个角色码在回退里都必须有显式 case；没有的必须具名登记（理由 + 显形条件 + owner），台账只许缩短。执行点 = 同 ① 段（`missing` 一半 + ROLE_FALLBACK_DIVERGENCES 台账，issue #5683 收口后**整表销账、上限 0**）。红证（实测）：`_drop_fallback_case` 删掉整段 case ⇒ **指名**红（报「回退 switch 里根本没有 case … ⇒ 空表 ⇒ 该角色在回退路径上零权限」）；登记了却已补齐 ⇒ 陈旧红；含对照组。', '判据 3·🔴 **零 403 受害者**：持某菜单节点码的岗位必须同时持该页第一屏的每个读端点码 ⇒ 「菜单看得见、点进去 403」不成立。执行点 = 同文件的 problems_menu_read_parity 第 ④ 段（逐岗位复算，种子 ∪ 回退）。红证（实测）：把补上的 processing:view 从回退收回 + 把该路径的 victims_ack 置空 ⇒ 零 403 受害者段具名报出 operator@fallback / product_manager@fallback。', '判据 4·**回退路径的行为面可判**（不靠读代码推断）：直接调真实服务的 getEffectivePermissionCodesForRoleCode(role, null)（= 纯回退路径）与 getUserPermissions（无 user_roles 的历史账号路径），逐码点名。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/RoleServiceTest.java（operator / 客服 / 销售 / 财务各 containsExactlyInAnyOrder；另有「五个种子岗位码在回退里都非空」一条）。', '判据 5·🔴 **授权变更 census**：本次新增的每个权限码必须逐条列出「哪些端点 / 菜单节点 / Agent 工具因此变为可达」，且登记与代码逐值相符（census 少列一个新增码 ⇒ 红；列的端点生效码不是本码 ⇒ 红）。本次共 15 个码（含 operator / product_manager 的 4 个 + 客服/销售/财务三岗的 11 个新增键）。执行点 = 判据 14 ② 段 + AUTHORIZATION_CENSUS。红证（实测）：删掉 census 里任一条 ⇒ 具名红。', '判据 6·**工具层镜像同批同步且口径零变化**：backend/ai-agent-service/tests/test_tool_permission_codes.py 的 ROLE_PERMISSIONS 对五个种子岗位取 seed 口径、对两个历史角色取回退口径；补码后 seeded_role_gaps(...) == [] 与 fallback_role_gaps(...) == [] 同时成立。', '判据 7·**不动任何已存授予行**：修复方向只动「计算」出来的回退表（回退路径不落 role_permissions）⇒ 不新增迁移、不改 role_permissions、不改种子矩阵、不改任何 V 迁移。'],
    skip_reason='[backend-contract] 岗位默认权限的静态契约 + 行为契约（admin-api 单测 backend/admin-api/src/test/java/com/migao/admin/service/RoleServiceTest.java + CI 工作流静态守卫 tests/unit_ci_workflows/test_agent_permission_parity.py 的判据 14 + 工具层镜像判据 backend/ai-agent-service/tests/test_tool_permission_codes.py），无 LLM 环节，不进入 agent-eval 冒烟',
    tags=['role', 'permission', 'fallback', 'rbac'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-012 [NORMAL] 岗位默认权限补本职码：客服+order:refund / 销售+order:create / 财务+customer:view / 知识编辑+knowledge:view+knowledge:manage（四处真值源逐值一致 + 存量回填 V145）（issue #5979 / #5988）（源: cases/hr.yml）──
_CASE_HR_012 = EvalCase(
    id='HR-012',
    legacy_id='',
    title='岗位默认权限补本职码：客服+order:refund / 销售+order:create / 财务+customer:view / 知识编辑+knowledge:view+knowledge:manage（四处真值源逐值一致 + 存量回填 V145）（issue #5979 / #5988）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['新租户管理员在「岗位权限」页查看 客服 / 销售 / 财务 / 知识编辑 四个岗位的默认权限（存量租户由 V145 同批回填）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **四个岗位的默认权限含各自的本职码**（人类 2026-10-02 逐条裁定「应允许」）：客服 `order:refund`（处理售后工单）/ 销售 `order:create`（下单）/ 财务 `customer:view`（读客户列表）/ 知识编辑 `knowledge:view` + `knowledge:manage`（维护知识库）。缺任一码 ⇒ 该岗位**做不了本职**（#5979 的原始形态 = 知识编辑一个 knowledge 码都没有 ⇒ 打开「知识库」被守卫拦下「当前账号缺少权限 knowledge:view」、调 `/api/admin/knowledge/cards` 得 403）。执行点 = tests/unit_ci_workflows/test_position_default_permissions.py 的 problems_裁定面（**逐码穷举四处真值源**，不是集合相等 —— 相等会把整份岗位矩阵抄成第二份真值）。', '判据 2·🔴 **四处真值源逐值一致**：① `RoleService.getPermissionCodesForRole` 的回退 switch / ② `rbac/manifest.json` 的 `roles.seed` / ③ `RegistrationService.attachDefaultPermissions` 的注册种子 —— 三者对同一岗位**逐值相等**（穷举，不抽样）；④ 迁移 `V145__backfill_position_permissions.sql` 只承担**增量** ⇒ 判据是「不得授 ①②③ 之外的码」（子集，防真放宽），**不是**逐值相等。执行点 = 同文件的 problems_四处逐值一致。红证（实测）：从回退删一个码 ⇒ 具名红；从 V145 删/多一个码 ⇒ 具名红；往回退加一个别处没有的码 ⇒ 具名红；只改注释 ⇒ **不红**（对照）。', "判据 3·🔴 **存量租户一起回填（口径必须写进 PR body）**：`V145` **无租户过滤** —— 语句以 `r.code = '<码>'` 为谓词、`JOIN permissions p ON p.tenant_id = r.tenant_id` 取该租户自己的码行 ⇒ 对**每一个**存在该岗位的租户生效。幂等 = `ON CONFLICT (role_id, permission_id) DO NOTHING`（与 V124 / V125 / V137 同款）⇒ 第二遍 0 行；**有意不清空后重加**（那会把租户在岗位权限页的手工增减静默复位）。边界（照实登记）：① 不回填 `users.permissions` 员工级快照（设计 §2.9）；② 不改 `roles` 行 ⇒ 没有该岗位行的租户不被波及；③ 目录缺该码的租户会被**终态对账** `RAISE EXCEPTION` 回滚（不静默放过）。", '判据 4·🔴 **P5 收敛不变量仍成立**：声明面（`roles.seed`）前进后，整条迁移链（含 V136 / V137 的**重新渲染**与 V145）推演出的每个岗位累计码 **== 清单声明** ⇒ 「新租户（Java seed）与存量租户（迁移链）逐值相等」这条口径常驻可判。本轮三个岗位各补 1 码 ⇒ P5 固定读数由「全 ∅」变为 `customer_service: (order:refund,) / finance: (customer:view,) / sales: (order:create,)`（`knowledge_editor` 不在 P5 射程），**同批重锚是本判据的必须动作**。执行点 = tests/unit_ci_workflows/test_rbac_migration_convergence.py 的 convergence_problems + census_problems。', '判据 5·🔴 **授权变更 census 逐条交代「打开了哪几扇门」**：本轮新增的码在判据 14 的 `AUTHORIZATION_CENSUS` 里必须逐条给出「哪些端点 / 菜单节点 / Agent 工具因此变为可达」：`order:refund` = 4 个写端点、无菜单节点、**无** Agent 工具（`after_sales_manage` 已于 #5247 收窄为只读）；`order:create` = 2 个端点 + 工具 `order_create`；`knowledge:manage` = 11 个端点、无菜单节点、无工具；`customer:view` / `knowledge:view` 已有条目只改 `roles` 集。台账条数 16 → 19（**显式放宽**，diff 里看得见）。', '判据 6·**工具层镜像同批同步且口径零变化**：backend/ai-agent-service/tests/test_tool_permission_codes.py 的 `ROLE_PERMISSIONS` 对 `knowledge_editor` 同批补两码 ⇒ `seeded_role_gaps(...) == []` 与 `fallback_role_gaps(...) == []` 同时成立（镜像 ≡ 种子 ≡ 回退）。', '判据 7·**RBAC 单一真值源的派生面同批更新**：清单改了 ⇒ `python3 rbac/generate_readings.py` 的 `rbac/readings.json` 必须重生成（新鲜度逐字节判）、`python3 rbac/generate_migration.py` 渲染的 V136 / V137 必须重渲染（`test_generated_migrations_are_fresh` 判红）、`rbac/sources.json` 的副本登记命中数必须同批重锚（涨跌都红）。'],
    skip_reason='[backend-contract] 岗位默认权限的静态契约 + 行为契约（tests/unit_ci_workflows/test_position_default_permissions.py 的四真值源逐码判据 + test_agent_permission_parity.py 判据 14 + test_rbac_migration_convergence.py 的 P5 不变量 + backend/ai-agent-service/tests/test_tool_permission_codes.py 的镜像判据），无 LLM 环节，不进入 agent-eval 冒烟',
    tags=['role', 'permission', 'seed', 'fallback', 'migration', 'rbac'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── HR-013 [NORMAL] 岗位权限树同码多节点：TreeCheckbox key 唯一不触发 React duplicate-key + 权限徽标 label 首见优先不被同码节点覆盖（issue #6083）（源: cases/hr.yml）──
_CASE_HR_013 = EvalCase(
    id='HR-013',
    legacy_id='',
    title='岗位权限树同码多节点：TreeCheckbox key 唯一不触发 React duplicate-key + 权限徽标 label 首见优先不被同码节点覆盖（issue #6083）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['管理员打开员工管理页：菜单树按设计含同码多节点（workspace 组两个 dashboard:view 叶子「经营看板/每日简报」、production-center 组四个 production:view 叶子），员工权限徽标应显示权限中文名'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **同码多节点渲染零 duplicate-key**：树组件对同码多节点渲染时 console.error 不得出现「Encountered two children with the same key」——key 不得只用 node.code（同码 = #5699/#5291 的有意设计面），必须由 code+label 派生唯一 key。执行点 = frontend/admin-web/tests/unit/components/TreeCheckbox.test.tsx（#6083 describe 判据 1）。红证（实测）：还原 key={node.code} ⇒ 具名红。', '判据 2·🔴 **同码节点全部渲染且 key 派生幂等**：同码多叶子的 6 个 label 全部渲染（一个不少）；treeNodeKey 对同码不同 label 派生不同 key 且幂等（同码同 label 的极端形态仍会撞 key —— 已知接受的边界，登记不修）。执行点 = 同文件判据 2。', "判据 3·🔴 **类级守卫·同码勾选语义不回退**：同码 = 同权限 —— 勾选其一上抛共享 code，同码各节点一起高亮（selected=['dashboard:view'] ⇒ 经营看板与每日简报同时勾选）。该语义是正确设计，禁因修 key 而改坏。执行点 = 同文件判据 3。", '判据 4·🔴 **权限徽标 label 首见优先**：员工权限徽标按菜单树**首见** label 展示（dashboard:view → 经营看板），不被同码后到节点（每日简报）后写覆盖。执行点 = frontend/admin-web/tests/unit/pages/employees.test.tsx（#6083 行为判据）。红证（实测）：还原 map[c.code]=c.label ⇒ 徽标变「每日简报」⇒ 具名红。'],
    skip_reason='[backend-contract] 纯前端渲染契约（React key 唯一性 + 徽标 label 映射），vitest 单测验证，无 LLM 环节，不进入 agent-eval 冒烟',
    tags=['permission', 'menu', 'same-code', 'react-key', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_HR_001,
    _CASE_HR_002,
    _CASE_HR_003,
    _CASE_HR_004,
    _CASE_HR_005,
    _CASE_HR_006,
    _CASE_HR_007,
    _CASE_HR_008,
    _CASE_HR_009,
    _CASE_HR_010,
    _CASE_HR_011,
    _CASE_HR_012,
    _CASE_HR_013,
)
