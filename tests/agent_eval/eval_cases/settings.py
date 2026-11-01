# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: settings（源: cases/settings.yml，11 条）

from ._schema import Difficulty, EvalCase, Skill

# ── ST-001 [NORMAL] 系统设置 - 读取（源: cases/settings.yml）──
_CASE_ST_001 = EvalCase(
    id='ST-001',
    legacy_id='6.1',
    title='系统设置 - 读取',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查看系统设置'],
    expectations=['settings_manage(action=get_settings)'],
    data_checks=['返回商户名/行业', '响应不含 accessKeyId/accessKeySecret/apiKey/secret'],
    skip_reason='',
    tags=['query'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-002 [NORMAL] AI 配置 - 读取（源: cases/settings.yml）──
_CASE_ST_002 = EvalCase(
    id='ST-002',
    legacy_id='6.2',
    title='AI 配置 - 读取',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['AI客服配置是什么'],
    expectations=['settings_manage(action=get_ai_config)'],
    data_checks=['data.botName 非空'],
    skip_reason='',
    tags=['query', 'ai_config'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-003 [NORMAL] 修改密码 —— 能力已下线（settings 域只读）：如实告知 + 引导管理员，不假承诺（源: cases/settings.yml）──
_CASE_ST_003 = EvalCase(
    id='ST-003',
    legacy_id='6.3',
    title='修改密码 —— 能力已下线（settings 域只读）：如实告知 + 引导管理员，不假承诺',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['改密码，旧密码xxx 新密码newpass123'],
    expectations=['direct_reply'],
    data_checks=['如实告知：黄金策不改密码（本域只读），且后台暂无自助改密入口 ⇒ 引导用户联系管理员处理', '整场不得出现假承诺话术（机器断言见 forbidden_text）', '不得索取/复述密码明文，也不得改用其它工具假装完成（如改配置/发通知）', 'settings_manage 只暴露 get_settings/get_ai_config/login_logs（结构性判据：backend/ai-agent-service/tests/test_settings_domain_readonly.py）'],
    skip_reason='',
    tags=['query', 'password'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['已修改成功', '密码已修改', '已为您修改密码', '已帮您修改', '修改成功'],
)

# ── ST-004 [NORMAL] 通知列表（源: cases/settings.yml）──
_CASE_ST_004 = EvalCase(
    id='ST-004',
    legacy_id='6.4',
    title='通知列表',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看看通知'],
    expectations=['notification_manage(action=list)'],
    data_checks=['返回列表/未读数'],
    skip_reason='',
    tags=['query'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-005 [NORMAL] 通知标记已读 —— 变更已接回（#7040）：标记已读要真做（走确认门禁），不得谎称已读（源: cases/settings.yml）──
_CASE_ST_005 = EvalCase(
    id='ST-005',
    legacy_id='6.5',
    title='通知标记已读 —— 变更已接回（#7040）：标记已读要真做（走确认门禁），不得谎称已读',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把新订单通知标为已读', '确认'],
    expectations=['notification_manage(action=mark_read) or interact'],
    data_checks=['真值 = 变更（标记已读）已在能力面内，且该调用必须走写确认门禁（非只读 action）', '整场不得出现假承诺话术（机器断言见 forbidden_text）', '标记已读的落库真值由 admin-api 侧承担：PUT /api/admin/notifications/{id}/read（单条）/ PUT /api/admin/notifications/read-all（全部）'],
    skip_reason='',
    tags=['write', 'notification'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=[{'round': 1, 'text': '已标记为已读'}, {'round': 1, 'text': '已标为已读'}, {'round': 1, 'text': '已全部标记'}, {'round': 1, 'text': '已经帮您标记'}, {'round': 1, 'text': '已为您标记'}],
    must_succeed=[{'tool': 'notification_manage', 'only_if_called': True}],
    pre_clean=[{'type': 'notification_unread_restore', 'notification_id': 'ntf_eval_new_order_0001', 'recipient_id': 'dev_user'}],
    namespaces=['account_password:notifications_mark_read'],
)

# ── ST-008 [NORMAL] 机器人设置生效 - 自动转人工关键词命中后如实告知（无人工通道）+ 非营业时间降级（确定性层）（源: cases/settings.yml）──
_CASE_ST_008 = EvalCase(
    id='ST-008',
    legacy_id='',
    title='机器人设置生效 - 自动转人工关键词命中后如实告知（无人工通道）+ 非营业时间降级（确定性层）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=["商家配置 autoHandoffKeywords=[找老板,我要投诉] 后，用户消息'我要找老板'应命中 complaint 路由（不再有可用的转人工工具）", '商家配置 afterHoursMode=auto_reply 且非营业时间时，转人工降级返回 afterHoursMessage（确定性层）'],
    expectations=['direct_reply'],
    data_checks=["（确定性层）is_auto_handoff_trigger('我要找老板', config) == true", '（确定性层）is_after_hours(config, 非营业时间) == true', '（确定性层）非营业时间降级不创建工单、返回 afterHoursMessage（实现在工具类内，随退场改为工具直测覆盖）'],
    skip_reason='[backend-contract] 纯配置函数行为由 pytest 单测（tests/test_tenant_config.py）验证：is_auto_handoff_trigger / is_after_hours 是纯函数，其入参 config（TenantAiConfig）无法经 agent-eval 设置，非 LLM 行为，不进入 C 端评测（issue #3270 断言层归因：原 user_inputs 是断言描述而非顾客对话）；2026-09-19 追加：转人工工具退场 ⇒ 原 human_handoff 断言不再有意义，降级分支改由工具直测覆盖',
    tags=['ai_config', 'handoff'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='租户 AI 配置就位：autoHandoffKeywords=[找老板,我要投诉]、afterHoursMode=auto_reply 且当前为非营业时间（TenantAiConfig；agent-eval 栈无法设置 ⇒ 本用例 skip，行为由 tests/test_tenant_config.py 的 is_auto_handoff_trigger / is_after_hours 纯函数单测 + tests/test_tools_human_handoff.py 的降级分支覆盖）',
)

# ── ST-009 [NORMAL] 系统通知总开关 - 租户关闭后自动站内信停止发送（#3003）（源: cases/settings.yml）──
_CASE_ST_009 = EvalCase(
    id='ST-009',
    legacy_id='',
    title='系统通知总开关 - 租户关闭后自动站内信停止发送（#3003）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['企业基础设置里关闭「启用系统通知」后，新订单/新售后/状态变更等自动站内信还发吗？'],
    expectations=['direct_reply'],
    data_checks=['tenants.notification_enabled=false 的租户：triggerByEvent（order_created / after_sales_created / order_status_changed / after_sales_status_changed）与 triggerForTenantAdmins 直接跳过，不再产生新的自动站内信；历史通知保留', '开关字段为 null（存量租户）默认视为开启，行为不变；triggerByEvent 命中规则仍正常落库', '前端企业基础设置「启用系统通知」描述与实际一致：控制订单、客服等重要事件站内通知的发送；关闭后不再产生新的站内通知（历史通知保留），不再写「当前为站内通知开关」含糊文案'],
    skip_reason='[backend-contract] 开关接线为 Java 单测验证（NotificationServiceTest）+ 前端文案 vitest，非 LLM 工具行为，不进入 agent-eval 冒烟',
    tags=['notification', 'switch', 'setting'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-010 [NORMAL] 企业基础信息页 - 隐藏「登录日志」（无记录）与「修改密码」（未来短信码登录）（#3006）（源: cases/settings.yml）──
_CASE_ST_010 = EvalCase(
    id='ST-010',
    legacy_id='',
    title='企业基础信息页 - 隐藏「登录日志」（无记录）与「修改密码」（未来短信码登录）（#3006）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['企业基础信息页还有「登录日志」和「修改密码」入口吗？'],
    expectations=['direct_reply'],
    data_checks=['企业基础信息页仅展示基本设置（品牌设置 + 通知设置），移除 tab 切换栏；「修改密码」「登录日志」tab 及区块不再渲染（登录日志无记录、修改密码未来由短信验证码登录取代；后端/Agent 接口保留，待短信码登录落地后再评估移除）', '页面副标题不再提「账号安全与登录审计」'],
    skip_reason='[backend-contract] 纯前端 UI 隐藏由 vitest 验证（settings.test.tsx ST-010），非 LLM 工具行为，不进入 agent-eval 冒烟',
    tags=['setting', 'ui', 'tab'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-011 [NORMAL] 企业收款二维码（微信/支付宝）C 端支付页展示与平台不经手资金（二清规避）（源: cases/settings.yml）──
_CASE_ST_011 = EvalCase(
    id='ST-011',
    legacy_id='',
    title='企业收款二维码（微信/支付宝）C 端支付页展示与平台不经手资金（二清规避）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我支付这笔订单，怎么付款'],
    expectations=['direct_reply or order_query or knowledge_search'],
    data_checks=['C 端收款码卡（卡型 `payment`）的**发射点**：C 端只读工具 `payment_qrcode_query`（无参，按租户取商家自己的收款码）返回的 data 即卡载荷 —— 含 `payment_qrcodes` 键（wechat/alipay 子对象含精简字段 image_url/payee_name），卡片渲染微信/支付宝切换与收款方（#4085 第 1 项）', '「应付金额」**只在载荷带 amount 时**展示（对话内收款码查询无订单上下文 ⇒ 不带 amount，卡片不显示金额行）；金额行由组件测试 frontend/mini-app/tests/payment-card.test.tsx 覆盖', '页面注明「款项直接支付给商家」（平台不经手资金，二清规避）', '商家设置端 PUT /api/admin/settings/payment-qrcodes/{type} upsert（wechat/alipay 各一张，非法类型拒绝）—— 由 SettingsControllerTest MockMvc 覆盖', '无收款码时展示降级提示（PaymentCard 空态「商家暂未设置收款码，请联系客服获取收款方式」）—— 触发条件 = 工具 success=true 且 `payment_qrcodes` 为空对象（空是合法答案，不是失败）', '答付款问题前先定位订单（order_query / C 端 customer_order_query）属合格路径；direct_reply 直答亦合格（OR 形态）'],
    skip_reason='',
    tags=['settings', 'payment'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── ST-012 [NORMAL] 元元答顾客问付款/收款码 —— 收款二维码工具可达 + 支付卡发射点（issue #4085 第 1 项）（源: cases/settings.yml）──
_CASE_ST_012 = EvalCase(
    id='ST-012',
    legacy_id='',
    title='元元答顾客问付款/收款码 —— 收款二维码工具可达 + 支付卡发射点（issue #4085 第 1 项）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我想付款，收款码在哪里？'],
    expectations=['payment_qrcode_query'],
    data_checks=['顾客问付款/收款码 → C 端只读工具 `payment_qrcode_query` 被调用且 success=true（must_succeed 机器断言；只要求「工具名出现过」不算）', '工具 data 即支付卡载荷：含 `payment_qrcodes` 键（子对象字段 image_url / payee_name / payment_type）—— 载荷形状合法即可，**不要求内容非空**', '⚠️ 可满足性真值（本用例刻意不要求非空内容）：评测栈种子 tests/agent_eval/fixtures/xiaobu_eval_seed.sql、mibao_eval_seed.sql 与 docs/deployment/demo-seed.sql 里 `tenant_payment_qrcodes` **零行**（按表名检索实测）⇒ 该租户未配收款码，工具返回 success=true + 空 `payment_qrcodes` 是**合法答案**；要求非空即造恒红。非空内容/空态提示由后端单测 tests/test_payment_qrcode_query.py（工具面：字段归一/缺图跳过/无码空态）与 tests/test_payment_card_emission.py（发射链与可达性）、前端 frontend/mini-app/tests/payment-card.test.tsx 覆盖', '工具失败（admin-api 异常/权限不足）时必须带 suggestion 并如实告知，禁止编造收款码或收款方名称', '卡片发射：工具 success=true 且 data 非空 ⇒ chat.py `_detect_card_type` 下发卡型 `payment`（同一轮 SSE card 事件），前端渲染 PaymentCard（有码→收款码；无码→空态提示）'],
    skip_reason='',
    tags=['xiaobu', 'payment', 'settings'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'payment_qrcode_query'}],
)

# ── ST-013 [SMOKE] 冒烟 · 通知标记已读：说一句「把新订单通知标为已读」→ 确认门禁 → 点卡后真做（不得先声张）（源: cases/settings.yml）──
_CASE_ST_013 = EvalCase(
    id='ST-013',
    legacy_id='',
    title='冒烟 · 通知标记已读：说一句「把新订单通知标为已读」→ 确认门禁 → 点卡后真做（不得先声张）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.SMOKE,
    user_inputs=['把新订单通知标为已读', '确认'],
    expectations=['notification_manage(action=mark_read)'],
    data_checks=['写确认门禁：R1 只能提出 + 发确认卡（或先确认再改），**不得**在 R1 就声称已完成（forbidden_text 收窄到 R1）', '真做：mark_read 必须 success=true（工具调用失败不算做过）', '前置由 pre_clean 复位成未读（首跑消费掉唯一夹具行后，重跑前置等价，#7048 P10 同款）'],
    skip_reason='',
    tags=['write', 'notification', 'write_path', 'smoke'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=[{'round': 1, 'text': '已标记为已读'}],
    must_succeed=[{'tool': 'notification_manage'}],
    pre_clean=[{'type': 'notification_unread_restore', 'notification_id': 'ntf_eval_new_order_0001', 'recipient_id': 'dev_user'}],
    precondition='前置 = 本店通知中心存在未读通知 `ntf_eval_new_order_0001`（由 pre_clean 复位成未读；夹具行缺失时 agent **合理地**答「这条已是已读」，此时的红是数据层、不是行为层）',
)

CASES = (
    _CASE_ST_001,
    _CASE_ST_002,
    _CASE_ST_003,
    _CASE_ST_004,
    _CASE_ST_005,
    _CASE_ST_008,
    _CASE_ST_009,
    _CASE_ST_010,
    _CASE_ST_011,
    _CASE_ST_012,
    _CASE_ST_013,
)
