# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: customer（源: cases/customer.yml，13 条）

from ._schema import Difficulty, EvalCase, Skill

# ── CU-001 [SMOKE] 客户列表（源: cases/customer.yml）──
_CASE_CU_001 = EvalCase(
    id='CU-001',
    legacy_id='4.1',
    title='客户列表',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.SMOKE,
    user_inputs=['查客户列表'],
    expectations=['customer_manage(action=list)'],
    data_checks=['返回客户列表（手机号脱敏：前3位+****+后4位）'],
    skip_reason='',
    tags=['query', 'smoke'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-002 [NORMAL] 客户详情 - 档案统计（源: cases/customer.yml）──
_CASE_CU_002 = EvalCase(
    id='CU-002',
    legacy_id='4.2',
    title='客户详情 - 档案统计',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看张三的客户档案'],
    expectations=['customer_manage(action=detail)'],
    data_checks=['profile.totalOrders / totalConsumption 为**数值或 null**：这两个字段属「无真值」声明面（issue #5362）⇒ 修后一律 null（未知），不得把 DB 列默认值 0 / 30 或建档种子常量当成真值', 'orders.length <= 10 AND sessions.length <= 10', '档案里「有真值」的字段（vipLevel / customerStatus / sourceChannel / phone / wechatNickname / tags / craftMode / defaultReceiver* 等）照常返回、**不得被遮蔽**（同一张表有真值/无真值并存，不是整表一刀切）', '字段级声明与源码写入点的一致性由确定性判据强制（零 LLM）：CustomerProfileFieldTruthGateTest 断言「声明有真值 ⇒ 源码里存在真值级写入点」与「声明无真值 ⇒ 必在读面遮蔽清单里」（改判任一字段即红，且带注入式红证）；CustomerProfileTruthExposureTest 断言四条读路径（列表 / 详情 / PUT / 分群成员）与序列化后的响应体里无真值字段为 null；FieldTruthMetaGuardTest 对同域表逐条对账（未登记即红、台账只许缩短）'],
    skip_reason='',
    tags=['query', 'detail'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-003 [NORMAL] 查客户标签（只读；原「打标签」随 #5247 写能力下线改判）（源: cases/customer.yml）──
_CASE_CU_003 = EvalCase(
    id='CU-003',
    legacy_id='4.3',
    title='查客户标签（只读；原「打标签」随 #5247 写能力下线改判）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['张三（手机号 13800138000）都有哪些标签？'],
    expectations=['customer_manage(action=list_tags)'],
    data_checks=['标签清单逐条来自服务端（customer_manage list_tags），不得编造；只读，不得声称已加标签（原「add_tag 真实落库（customer_profiles.tags JSONB 写入），重复标签幂等跳过」是写路径断言，已随 #5247 写能力下线改判）'],
    skip_reason='',
    tags=['tag', 'write'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'customer_tag_remove', 'customer_keyword': '13800138000', 'tag_name': 'VIP2'}],
    namespaces=['customer_phone:13800138000'],
    precondition=[{'type': 'order_count_for_phone', 'source': '13800138000'}],
)

# ── CU-004 [NORMAL] 更新客户资料（部分更新）（源: cases/customer.yml）──
_CASE_CU_004 = EvalCase(
    id='CU-004',
    legacy_id='4.4',
    title='更新客户资料（部分更新）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['张三（手机号 13800138000）的手机号改成 13900001111', {'auto_respond': {'fallback': '确认'}}],
    expectations=['customer_manage(action=detail)'],
    data_checks=['仅 phone 被更新，未传字段保持原值'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「更新客户资料」（customer_manage / action=update）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 customer_manage(action=detail)（只读查询客户详情）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['update'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'customer_profile_restore', 'customer_keyword': '13800138000', 'phone': '13800138000'}],
    post_clean=[{'type': 'customer_profile_restore', 'customer_keyword': '13900001111', 'phone': '13800138000'}],
    precondition=[{'type': 'order_count_for_phone', 'source': '13800138000'}],
)

# ── CU-005 [ADVERSARIAL] 对抗性 - 模糊名称渐进澄清（老王→王五→订单→发货）（源: cases/customer.yml）──
_CASE_CU_005 = EvalCase(
    id='CU-005',
    legacy_id='M011',
    title='对抗性 - 模糊名称渐进澄清（老王→王五→订单→发货）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.ADVERSARIAL,
    user_inputs=['帮我处理下老王的订单', '就是王五', '他那个窗帘订单', '对，发货吧', '顺丰，运单号 SF1234567890'],
    expectations=['customer_manage(action=list)', 'order_query(action=list)'],
    data_checks=['customer_id 从 customer_manage 查询获得', 'order_id 从 order_query 获得', '如实说明黄金策不做发货/改物流（order_manage 的 update_logistics 已随 #5247 从 B 端解绑），引导后台订单页面；不得声称已发货（原第 3 条「发货操作使用正确的 order_id」是写路径断言，已随写能力下线改判）'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「发货/改物流」（order_manage / action=update_logistics）已从 B 端下线（该工具已从 B 端全部解绑；工具类仍在、C 端绑定未动）。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 customer_manage(action=list) + order_query(action=list)，「已发货」类断言改判为**如实说明黄金策不做发货/改物流 + 引导后台订单页面**。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['fuzzy_input', 'progressive_clarification', 'adversarial'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    pre_clean=[{'type': 'order_status_restore', 'order_no': 'EVAL-MB-ORD-0006', 'status': 'confirmed'}],
    post_clean=[{'type': 'order_status_restore', 'order_no': 'EVAL-MB-ORD-0006', 'status': 'confirmed'}],
    precondition=[{'type': 'order_count_for_phone', 'source': '13700137000'}],
)

# ── CU-006 [NORMAL] C 端租户域名路由 - 微信用户经企业域名自动关联租户并落 CRM 客户档案（#3011）（源: cases/customer.yml）──
_CASE_CU_006 = EvalCase(
    id='CU-006',
    legacy_id='',
    title='C 端租户域名路由 - 微信用户经企业域名自动关联租户并落 CRM 客户档案（#3011）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['C 端微信用户从企业小程序登录后，客户列表里能看到他吗？租户是怎么挂上的？'],
    expectations=['customer_manage(action=list)'],
    data_checks=['POST /api/auth/mini/login：X-Tenant-Id（nginx 按 <tenantId>.app.migaozn.com 注入）/ Host 子域解析为租户权威来源；body tenantId 仅兼容期兜底；均无 → 400', '登录（新 openid 自动建号 / 已有 openid）后调用 CustomerService.createFromSession(tenantId, openid, nickname, wechat_mini) 幂等上写 customer_profiles', '客户列表（CRM）可见 C 端消费者；员工管理列表仍排除 role=customer（#3007 语义不变）'],
    skip_reason='域名解析/建档为 Java 单测验证（TenantDomainResolverTest/AuthServiceTest/AuthIntegrationTest），非 LLM 工具行为差异，不进入 agent-eval 冒烟',
    tags=['c-end', 'tenant', 'domain', 'customer_profile'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-007 [NORMAL] C 端商品搜索只展示已上架商品（下架商品不得出现）（源: cases/customer.yml）──
_CASE_CU_007 = EvalCase(
    id='CU-007',
    legacy_id='',
    title='C 端商品搜索只展示已上架商品（下架商品不得出现）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['店里有什么窗帘？'],
    expectations=['product_search(keyword=窗帘)'],
    data_checks=['product_search 返回的 products[].status 全部 == "on_sale"（任一非 on_sale 即违规；工具层按 context.role == "customer" 过滤）', '回复/卡片不得出现『已下架』『off_sale』等状态披露（forbidden_text 机器断言）', 'product_detail 对非 on_sale 商品按『不存在』处理（不泄露商品名/ID）'],
    skip_reason='',
    tags=['c-end', 'product', 'visibility'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    forbidden_text=['已下架', 'off_sale'],
)

# ── CU-008 [NORMAL] 客户工艺画像与常用物流查询（黄金策 customer_manage 读路径，M2-D）（源: cases/customer.yml）──
_CASE_CU_008 = EvalCase(
    id='CU-008',
    legacy_id='',
    title='客户工艺画像与常用物流查询（黄金策 customer_manage 读路径，M2-D）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['帮我看看客户张三的工艺偏好和常用物流设置是什么'],
    expectations=['customer_manage(action=detail)'],
    data_checks=['客户工艺偏好/常用物流是**读**场景 → customer_manage(action=detail) 被调用且成功（must_succeed 断言 success=true）；detail 返回 CustomerProfile 的 craftMode/craftProfile/defaultLogisticsType/defaultLogisticsCompany', '写路径（customer_manage(action=update) 写 craftMode / craftProfile / defaultLogisticsType / defaultLogisticsCompany，CustomerProfile 新列 V47 迁移）**由单测契约覆盖**：test_tool_field_name_contract.py（case_ids 含 CU-008）+ 后端列契约，不在本行为用例重复断言', '物流类型区分 express（快递）与 logistics（物流/专线，如四季安）——POC 客户更多选物流', '工艺画像与常用物流在客户详情（GET /api/admin/customers/{id}）中返回，供报价协商（M3-F）读取'],
    skip_reason='',
    tags=['customer', 'mibao', 'craft-profile', 'logistics'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'customer_manage'}],
)

# ── CU-009 [NORMAL] 客户默认收货信息与常用物流档案（客户管理「收货信息」卡片 + 落库契约，issue #4419）（源: cases/customer.yml）──
_CASE_CU_009 = EvalCase(
    id='CU-009',
    legacy_id='',
    title='客户默认收货信息与常用物流档案（客户管理「收货信息」卡片 + 落库契约，issue #4419）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户管理里要能记录客户的收货地址、常用物流/快递方式和常用物流/快递公司；新增订单选客户时自动带出'],
    expectations=['direct_reply'],
    data_checks=['customer_profiles 新增 default_receiver_name VARCHAR(100) / default_receiver_phone VARCHAR(20) / default_receiver_address TEXT（V70 迁移，列注释与 schema.sql bootstrap 终态同步）；PUT /api/admin/customers/{id} 非空拷贝落库，客户详情 GET /api/admin/customers/{id} 返回', '客户详情页「收货信息」卡片可查看/编辑：收货人姓名、收货人电话、收货地址、常用物流方式（express 快递 / logistics 物流专线）、常用物流公司（预置候选 datalist + 允许自定义）', '落库是**效果层**断言：CustomerReceiverAddressPersistTest 断言交给 Mapper 的实体内容（删掉 setXxx 即红）；前端由 customer-detail.test.tsx 断言 updateCustomer payload 五键齐全（空白不覆盖既有值）', '黄金策写路径 customer_manage(update) 的 3 个新列与 CustomerService.updateCustomer 非空拷贝白名单**同集合**（test_tool_field_name_contract.py 的 java-service-null-copy 判据）——防 #4115 同款「工具可写 + 服务层静默丢弃」', '空白/缺省字段不覆盖既有收货信息（清空语义未定义 ⇒ 一律不覆盖），避免客户管理页把已录地址误抹掉'],
    skip_reason='[backend-contract] 字段落库与前端表单交互由确定性单测覆盖（CustomerReceiverAddressPersistTest + customer-detail.test.tsx + test_tool_field_name_contract.py）；读路径已由 CU-002/CU-008 覆盖，非 LLM 行为新增面，不进入 agent-eval 冒烟',
    tags=['customer', 'ui', 'logistics', 'receiver-address', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-010 [NORMAL] 客户画像视图：逐字段三态 +「未知」≠「0」（具名跨域视图 customer_profile 的按需消费，issue #5456 族 3 · 包 3）（源: cases/customer.yml）──
_CASE_CU_010 = EvalCase(
    id='CU-010',
    legacy_id='',
    title='客户画像视图：逐字段三态 +「未知」≠「0」（具名跨域视图 customer_profile 的按需消费，issue #5456 族 3 · 包 3）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户画像视图语义自检'],
    expectations=[],
    data_checks=['快照契约（GET /api/admin/customers/profile-view?limit=N，权限码 customer:view）：返回跨域视图内核**同一形状**的确定性快照 —— row_fields（自描述，customer_profiles 的字段集 ≡ #5362 声明的字段集）＋ row_meta（limit / count / truncated）＋ field_truth（真值声明的**运输**，由 FieldTruthRegistry.customerProfile() **现取** —— 装配与消费两侧都不持有第二份真值判断）＋ customer_profiles 行数组（显式租户过滤 + createdAt 倒序，行键集 ≡ 声明字段集、含**线上 JSON 形态**）。⚠️ 行键集 ≡ 声明字段集这条**实测红过一次**（把实体直接交给 Jackson 时 getRScore 这类 getter 被折叠成 rscore ⇒ 键集对不上）', '🔴「未知」≠「0」（本视图的核心口径）：「无真值」在行的值域里**只可能是 null**（不得回填 0 / DB 列默认值 0.00 / 30 / 建档种子常量），「有真值」的字段**照实返回**（值就是 0 / 空照原样保留 —— 那是真结论）；两侧**逐字段区分**，既不许给默认值、也不许把有真值的字段抹成 null（**不得整表一刀切**）。注入式红证：把取值处换成「无真值当 0」⇒ 同一断言必红；换成「整表一刀切置 null」⇒ 保真断言必红', '逐字段三态（视图侧）：每个被声明字段输出 status ∈ wired / not_wired / incomplete，不变式 reason is None ⟺ status == wired；声明「无真值」⇒ not_wired + 证据化原因（来自 #5362 的登记）；装配层未接线（快照无行数组 / 该字段不在行里）⇒ not_wired + 点名缺什么；行数被上限截断或有行**整行缺键** ⇒ incomplete + 原因（**有界不许变成静默少报**）', '口径同源（真值判断只有一份）：视图模块内**不出现任何被声明字段的名字**（自带字段清单 = 第二份真值判断）；把运输来的 field_truth 声明改掉，视图的逐字段分类必须跟着变。类级元守卫覆盖 app/briefing/** 全部模块：自带字段台账 ⇒ 未登记即红，台账**只许缩短**', 'fail-closed（没带声明就不猜）：快照未携带 field_truth.customer_profiles ⇒ 视图**一个字段都不产出**（declaration.status=not_wired + 原因），且不得退化成「都当有真值」（会把 DB 默认值当真值下发）或「都当无真值」（会把真值抹成 null）；声明块另带 fields_total / has_truth_count / no_truth_count', '有界 + 租户 + 确定性：Agent 侧请求恒为 limit=50（MAX_VIEW_ROWS），装配层上限收敛到 SNAPSHOT_ROW_LIMIT；视图输出被截断 ⇒ 每个「有真值」字段落 incomplete（带可归因读数：上限多少行 / 给出多少行 / 共多少行）；租户由调用方传入并**原样回显**（不由行数据反推 —— 隔离关口在装配层，每条查询显式带 tenantId）；同一快照 ⇒ 逐字相同输出（纯函数、不联网、不读挂钟），行序 = 装配层 SQL 口径（视图不改行序）', '字段级声明与源码写入点的一致性（零 LLM，判据 = traces.tests 点名的四条确定性测试）：声明「有真值」⇒ 源码里存在真值级写入点；声明「无真值」⇒ 必在读面遮蔽清单里；四条读路径（列表 / 详情 / PUT / 分群成员）与序列化后的响应体里无真值字段为 null；同域表逐条对账（未登记即红、台账只许缩短）'],
    skip_reason='[backend-contract] 视图语义由 ai-agent 单测验证（backend/ai-agent-service/tests/test_briefing_customer_profile.py 的三态 / 未知≠0 / 口径同源 / 五条注入式红证），装配腿由 admin-api 单测验证（CustomerProfileViewSnapshotTest 的装配契约、CustomerProfileTruthExposureTest 的读面遮蔽、CustomerProfileFieldTruthGateTest 的声明对账），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['query', 'briefing', 'view', 'field-truth'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-011 [NORMAL] 客户画像 action：customer_manage(profile_view) 的按需消费与披露纪律（issue #5456）（源: cases/customer.yml）──
_CASE_CU_011 = EvalCase(
    id='CU-011',
    legacy_id='',
    title='客户画像 action：customer_manage(profile_view) 的按需消费与披露纪律（issue #5456）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看一下客户画像'],
    expectations=['customer_manage(action=profile_view)'],
    data_checks=['只读且免确认：profile_view 在 VALID_ACTIONS 与 read_only_actions 里（与 list / detail / list_tags 同列），工具 read_only=True ⇒ 不弹确认卡（_requires_confirmation 为 False）', '端点与参数：GET /api/admin/customers/profile-view 的字面量留在**调用点**（静态归属机具只认调用点的字符串字面量；常量与调用点字面量的一致性由单测机械钉住），参数恒为 limit=MAX_VIEW_ROWS（50）并带 tenant_id / user_id；该端点与客户列表/详情**同权限码** customer:view（不并入 dashboard:view 的简报表快照 —— 客户档案含 PII，Agent 能力 ≡ 页面权限）', '🔴「未知」≠「0」的披露：快照里声明「无真值」的字段**逐条点名**，并说清它们一律为「未知」—— **不是 0、不是「从未发生」、不是默认值**（消息是模型的唯一输入源，不写这句模型会把 null 讲成「消费 0 元」）', '三类「没有数据」**各自点名、不合并**：① 声明「无真值」（系统没有这项能力）；② 声明「有真值」但**本次未接线**的字段单独点名（+ 请勿理解为均为 0）；③ **本次不完整**的字段点名 + 原因（不许读成「没问题」）；全部 wired 时不得出现未接线措辞（披露不能因为总是出现而失去信息量）', '有界不静默：输出被上限截断时消息点出「视图只列前 N 位，共 M 位」；data 就是**视图本体**（有界 ≤ MAX_VIEW_ROWS 行），不再包一层、也不回灌原始快照', '失败可归因：admin-api 返回 success=false 时走 admin_api_failure（带 error + message + 可行动 suggestion 指向 customer_manage 的 list），不是空壳失败；快照未携带真值声明时把 declaration.reason 说出来（fail-closed 的说明面）'],
    skip_reason='[backend-contract] action 的披露与端点契约由 pytest 单测验证（backend/ai-agent-service/tests/test_customer_manage.py 的 profile_view 三条：未知≠0 披露 / 缺声明披露 / 失败可归因），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['query', 'tool', 'disclosure', 'field-truth'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CU-012 [NORMAL] 客户价值分层 / 流失预警视图：customer_manage(value_view) 的跨域取数面与披露纪律（issue #6217）（源: cases/customer.yml）──
_CASE_CU_012 = EvalCase(
    id='CU-012',
    legacy_id='',
    title='客户价值分层 / 流失预警视图：customer_manage(value_view) 的跨域取数面与披露纪律（issue #6217）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['哪些老客户最近不下单了', '谁最值得维护'],
    expectations=['customer_manage(action=value_view)'],
    data_checks=['只读且免确认：value_view 在 VALID_ACTIONS 与 read_only_actions 里（与 list / detail / list_tags / profile_view 同列），工具 read_only=True ⇒ 不弹确认卡（_requires_confirmation 为 False）', '取数面 = **三条既有只读端点**（不新开端点、不扩 /api/admin/briefing/snapshot）：GET /api/admin/customers、GET /api/admin/orders、GET /api/admin/after-sales —— 端点字面量在 client.get 的**调用点**（静态归属机具只认调用点字面量），参数恒为 page=1&size=200 并带 tenant_id / user_id；三条并发取数，**任一条失败即 fail-closed**（不拿半份数据出结论）且点名失败面 + 所需权限码（customer:view / order:list / after_sales:view，与控制器 @RequirePermission 逐字对齐）', '🔴「未知」≠「0」（本视图的核心口径）：窗口内**没有订单行**的客户 ⇒ order_count / days_since_last_order / total_consumption / avg_order_amount / return_rate 一律 **null** + 行内 *_basis=no_orders（**不是 0 单、不是 0 天、不是 0 元** —— 0 天会把从未下单的客户排成最活跃）；窗口外有行而窗口内 0 行 ⇒ order_count **真 0**（那是一个真结论）；退货率**无分母** ⇒ null（不是「0% 退货」）。注入式红证：把 _row 的未知格填成 0 ⇒ 同一断言必红', '🔴 分层未知 ≠ 活跃、也 ≠ 已流失：没有任何订单行的客户落 risk_band=unknown（unknown 分层），消息里**明说**「分层未知 = 不知道」，不得被读成「活跃」或「已流失」；行序 = 流失风险降序（lost → at_risk → active → unknown）再按距上次下单天数倒序（本视图的用途就是「谁最值得维护」，不改序等于把问题丢给模型；口径写在 basis.row_order 里可复算）', '归并主键 = 手机号（既有订单读面不含客户 id —— OrderListResponse 只有 customerName / customerPhone，这是唯一可用联接键）：客户档案里**被打码**的手机号（含 * ）不参与归并（打码号经数字提炼会变成一个看似合法的数字串 ⇒ 不拦就是把「读不出」当「读到了」）；订单行手机号缺失 ⇒ 该行落不可归属并计数（unattributed_orders），受影响的指标字段落 incomplete（**不得静默偏低**）', '🔴 具名披露「未接线」：声明**无真值**的字段（outstanding_amount 欠款 / avg_ticket_amount 客单价 / recent_days 最近活跃天数）逐条点名并说清一律「未知」，附**逐条原因**（既有只读端点里没有这个列：订单列表无已收/未收金额、售后**列表**无金额列、客户档案无「最近活跃」列）—— 消息是模型的唯一输入源，不写这句模型会把 null 讲成「欠款 0 元」', '逐字段三态（视图侧）：每个声明字段输出 status ∈ wired / not_wired / incomplete，不变式 reason is None ⟺ status == wired；声明无真值 ⇒ not_wired + 证据化原因；装配层未接线（快照缺数组 / 该字段不在行里）⇒ not_wired + 点名缺什么；行数被上限截断或有行整行缺键 ⇒ incomplete + 原因（**有界不许变成静默少报**）；口径同源：行里读的每个键都必须在 FIELD_SOURCES 里声明过（AST 机械判据）', '确定性 + 有界 + 租户：同一快照 ⇒ 逐字相同输出（纯函数、不联网；as_of 由调用方传入 —— 视图模块内不出现 date.today / datetime.now，注入式判据扫描源码）；默认上限 50 行、工具侧每面取数上限 200 行（截断由 row_meta.truncated 显式声明）；租户由调用方传入并原样回显（不由行数据反推）'],
    skip_reason='[backend-contract] 视图语义由 ai-agent 单测验证（backend/ai-agent-service/tests/test_briefing_customer_value.py 的逐字段三态 / 未知≠0 / 口径同源 / 五条注入式红证），工具面由 backend/ai-agent-service/tests/test_customer_manage.py 的 TestCustomerValueAction 验证（action 白名单 / 三条端点字面量三处同源 / 任一面失败 fail-closed / 披露纪律），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['query', 'tool', 'cross-domain', 'disclosure', 'churn'],
    persona='mibao',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 的**视图契约**用例（不进 agent-eval 冒烟）：两条 user_inputs 是**同一能力**的两种问法（「哪些老客户最近不下单了」/「谁最值得维护」），不是两次会话。前置 = 三条既有只读端点可用且当前账号同持 customer:view + order:list + after_sales:view（缺任一面 ⇒ 工具 fail-closed 并点名缺哪个码）。该前置由 backend/ai-agent-service/tests/test_customer_manage.py 的 TestCustomerValueAction 逐面构造并断言（三面各失败一次都必须 cross_domain_fetch_failed + 点名权限码）⇒ 前置不成立（端点 / 权限码改名）时单测直接红，不会表现为「agent 不干活」',
)

# ── CU-013 [NORMAL] 客户授信额度与账期：超限拒单（服务端闸门）/ 未启用不拦（零回归）/「额度 0」≠「未启用」（issue #7370，P0-2 段 1）（源: cases/customer.yml）──
_CASE_CU_013 = EvalCase(
    id='CU-013',
    legacy_id='',
    title='客户授信额度与账期：超限拒单（服务端闸门）/ 未启用不拦（零回归）/「额度 0」≠「未启用」（issue #7370，P0-2 段 1）',
    skill=Skill.CUSTOMER,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户（2026-10-20，逐字）：「p0 p1 逐步推进落地」—— 要求把中型企业能力缺口按 P0→P1 逐项做成可合并的最小闭环，P0-2 = 授信/账期/应收。'],
    expectations=[],
    data_checks=['**口径（本单裁定，两处同源）**：`credit_limit` **NULL = 未启用授信**（存量客户默认 ⇒ 一律放行，零回归）；**0 = 启用但零额度**（拒一切赊销）；正数 = 额度（闭区间，恰好等于可用额度放行）；负额度 = 配置错误 ⇒ 抛（不许静默当 0 或不限）。落地 = `backend/admin-api/src/main/java/com/migao/admin/service/CreditPolicy.java`。', '**判据 1（纯函数逐格）**：`backend/admin-api/src/test/java/com/migao/admin/service/CreditPolicyTest.java`（7 条：NULL 放行 / 额度内可用=额度-已欠 / 超额给 excess / 闭区间边界 / 零额度拒 0.01 / null 金额视为 0 / 负额度抛）。红证 = TDD 第一步实测 `./mvnw -o -Dtest=CreditPolicyTest test` ⇒ `找不到符号: CreditPolicy`（编译级红）。', '**判据 2（下单闸门挂在唯一入口）**：`OrderService.createOrder` 在算出 `totalAmount` 之后、**任何写之前**调 `customerService.assertWithinCredit(...)` —— 该方法是表单 / Agent（`createOrderForAgent` 手工 new 请求）/ 程序化三条路径的共用入口，故闸门无死角。', "**判据 3（已欠口径可复算）**：`OrderMapper.selectOutstandingTotal` = `SUM(total_amount)` where `paid_at IS NULL AND status <> 'cancelled'`；未建档客户（按手机号匹配不到）⇒ 不校验（不猜）。⚠️ 部分收款仍按全额计入（偏保守），逐笔核销属 P0-2 段 3。", '**判据 4（前端不发假读数）**：`frontend/admin-web/tests/unit/pages/customer-detail.test.tsx`（4 条：显示服务端额度/账期/已欠/可用；保存发**数字**；清空发 **null** 而非 0；负额度前端拦下且不发请求）。', '**边界（照实登记）**：① 只拦「赊销超限」，不拦现结订单（订单尚未区分付款方式，P0-2 段 3 承接）；② 审批出口（谁可批超额）归 P1-2；③ 账龄分档（0-30/31-60/…）与收款核销未在本段落地（issue #7370 段 2/3）。'],
    skip_reason='[backend-contract] 服务端授权/金额闸门 + 页面读数契约，由 Java 单测与 vitest 页面判据验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['backend-contract', 'credit', 'credit-limit', 'payment-terms', 'receivable', 'admin-api', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract]：前置 = `customer_profiles` 有 `credit_limit` / `payment_terms_days` 两列（V169 迁移 + 建库脚本终态）；客户详情页与 `GET/PUT /api/admin/customers/{id}/credit` 在场。零网络、零 LLM。',
)

CASES = (
    _CASE_CU_001,
    _CASE_CU_002,
    _CASE_CU_003,
    _CASE_CU_004,
    _CASE_CU_005,
    _CASE_CU_006,
    _CASE_CU_007,
    _CASE_CU_008,
    _CASE_CU_009,
    _CASE_CU_010,
    _CASE_CU_011,
    _CASE_CU_012,
    _CASE_CU_013,
)
