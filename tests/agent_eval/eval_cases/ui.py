# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: ui（源: cases/ui.yml，145 条）

from ._schema import Difficulty, EvalCase, Skill

# ── UI-001 [NORMAL] 织物质感设计 token - primary/accent/neutral 三阶与默认蓝清理（源: cases/ui.yml）──
_CASE_UI_001 = EvalCase(
    id='UI-001',
    legacy_id='',
    title='织物质感设计 token - primary/accent/neutral 三阶与默认蓝清理',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['经营看板织物质感重设计子任务 A：建立设计 token 体系'],
    expectations=['direct_reply'],
    data_checks=["tailwind.config.ts theme.extend.colors.primary[500] = '#48618f'", "tailwind.config.ts theme.extend.colors.accent[500] = '#c06a3e'", "tailwind.config.ts theme.extend.colors.neutral[50] = '#faf7f2'", "frontend/admin-web/src/**/*.{ts,tsx} 扫描 '#3b82f6'（大小写不敏感）计数 = 0"],
    skip_reason='[backend-contract] 纯前端设计 token 由 vitest 单测验证（tests/unit/tailwind.config.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'token', 'tailwind'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-002 [NORMAL] 订单/售后状态语义色 chips + 数据空态「暂无数据」治理（源: cases/ui.yml）──
_CASE_UI_002 = EvalCase(
    id='UI-002',
    legacy_id='',
    title='订单/售后状态语义色 chips + 数据空态「暂无数据」治理',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['订单/售后状态用语义色 chips 表达，数据空态显示暂无数据'],
    expectations=['direct_reply'],
    data_checks=['OrderStatusBadge shipped 含 bg-primary-50 且不含 bg-indigo-50', 'OrderStatusBadge closed 含 bg-neutral-100 且不含 bg-gray-50', '🔴 OrderTable「采购商品」列**逐条**渲染全部明细（2026-09-25 补判据，issue #4908 的修复证据入用例库，配套 #4916 判据 1）：1 个订单 **3 条** `items` ⇒ 该单元格里渲染出 **3 组「名称 + 货号」**（3 行 `货号 X`，且三条商品名与末一条货号都落在**同一个** `td` 内），顺序与 `items` 相同；改前只取 `items[0]` ⇒ 只出 1 组、该断言当场红（红证实测：`expected [ <div …(1)></div> ] to have a length of 3 but got 1`）。**反向护栏**：`items` 为空仍渲染「暂无数据」且无裸 `-` 占位（见下一条）。证据：frontend/admin-web/tests/unit/components/OrderTable.test.tsx 的「多商品订单：采购商品列逐条渲染全部商品（名称 + 货号），不是只渲染第一条」', 'OrderTable 采购明细列与采购商品列在 `items` 为空时渲染「暂无数据」，且全表无裸 `-` 占位（**2026-09-25 事实订正**：本条原文写「采购商品列无 `firstItem`」—— `firstItem` 是实现期局部变量，已随 issue #4908 的修复删除（改后按 `items?.length` 判空）⇒ 判据文字不再引用已不存在的实现标识符，判据强度一格未降）'],
    skip_reason='[backend-contract] 纯前端 UI chips/空态由 vitest 单测验证（status-chip/OrderStatusBadge/OrderTable/RecentOrders/after-sales），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'status-chip', 'empty-state'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-003 [NORMAL] 黄金策「今日经营速览」洞察条 - 一句话经营解读（源: cases/ui.yml）──
_CASE_UI_003 = EvalCase(
    id='UI-003',
    legacy_id='',
    title='黄金策「今日经营速览」洞察条 - 一句话经营解读',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['经营看板织物质感重设计子任务 C：黄金策「今日经营速览」洞察条置于页面顶部'],
    expectations=['direct_reply'],
    data_checks=['frontend/admin-web/src/components/dashboard/TodayOverviewBar.tsx 以「一句话经营解读」串联今日订单/销售额/环比/提醒', '含加工占比 = processingCount / pendingCount，pendingCount<=0 时渲染 0% 而非 NaN/Infinity/undefined', '一句话中的数值全部来自 props（由页面 API 返回值派生），组件内无硬编码固定数值', '洞察条置于经营看板顶部（先于待处理区块渲染）'],
    skip_reason='[backend-contract] 纯前端组件由 vitest 单测验证（TodayOverviewBar.test.tsx + dashboard.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'dashboard', 'insight', 'token'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-004 [NORMAL] 经营看板密度治理 - 商品销量排行表头不截断 + 订单趋势 x 轴降采样（源: cases/ui.yml）──
_CASE_UI_004 = EvalCase(
    id='UI-004',
    legacy_id='',
    title='经营看板密度治理 - 商品销量排行表头不截断 + 订单趋势 x 轴降采样',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['经营看板织物质感重设计子任务 B：dashboard 密度修复（表格/图表多视口）'],
    expectations=['direct_reply'],
    data_checks=['商品销量排行表头「环比」列渲染 whitespace-nowrap，1440×900 与 1280×800 两视口无截断（#2984：原列名「日涨」误导，改「环比」并标注周期口径）', '商品销量排行「环比」列有可见口径说明（不依赖 hover title）：表头 title 写明「本期(近7天) vs 上一统计周期(前7天)」，表下渲染「环比 = 本期销量（近7天）对比上一期（前7天）的涨跌幅」（#3000：大部分用户不理解环比概念，需讲明比较周期）', '订单趋势图 x 轴刻度按 sampleTickIndices 降采样，1280 宽度下标签数 ≤ 7 且不密集重叠', 'dashboard 页面在 1440×900 与 1280×800 两视口无水平/垂直截断或溢出'],
    skip_reason='[backend-contract] 纯前端密度/布局治理由 vitest 单测验证（axis-sampling.test.ts + dashboard.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'dashboard', 'density', 'axis-sampling'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-005 [NORMAL] 侧边栏「智能客服」大类——在线接待图标修复 + 机器人设置改名归组（#3081 起 AI 客服配置已合并进企业基础信息）（源: cases/ui.yml）──
_CASE_UI_005 = EvalCase(
    id='UI-005',
    legacy_id='',
    title='侧边栏「智能客服」大类——在线接待图标修复 + 机器人设置改名归组（#3081 起 AI 客服配置已合并进企业基础信息）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['侧边栏新增「智能客服」一级大类：在线接待耳机图标修复 + 机器人设置改名归组'],
    expectations=['direct_reply'],
    data_checks=['Sidebar.tsx 渲染一级大类「智能客服」，DOM 顺序位于「工作台」之后、「商品管理」之前；「在线接待」从「工作台」分组移除', '「智能客服」下子菜单顺序：在线接待 在前、知识库 次之（#3094 起黄金策·在线对话 菜单入口已移除，智能体对话经右下角 FAB 进入；#3081 起 AI 客服配置菜单已移除）', '「在线接待」渲染 Headphones 图标（iconMap 已注册，非 BarChart3 回退），与「经营看板」BarChart3 图标明确区分；「智能客服」大类渲染 MessageSquare 图标', '原「机器人设置」更名为「AI 客服配置」后（2026-08）又随 #3081 合并进企业基础信息：侧边栏不再出现「AI 客服配置」菜单项，/chat/config 页面删除，机器人名称+欢迎语并入 /settings 页「AI 客服设置」区块；不再出现「机器人设置」残留', '链接路径：在线接待 href=/agent-workspace/human-sessions（#3081 起无 /chat/config 链接）', '权限过滤不回归：无 agent:session → 隐藏「在线接待」；无 knowledge:manage → 隐藏「知识库」；均无 → 「智能客服」整组隐藏', '「在线接待」菜单项不再出现旧名「人工客服」（#3109 菜单改名，页面标题/Header 面包屑/权限分配弹窗同步为新名；C 端顾客侧『人工客服』来源标识与转人工文案不变）'],
    skip_reason='[backend-contract] 纯前端侧边栏菜单/图标/文案由 vitest 单测验证（sidebar/settings/Header.test），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'sidebar', 'menu', 'icon'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-006 [NORMAL] 会话管理工作台 - 单列表（无筛选控件）+ 已结束会话续聊 banner（源: cases/ui.yml）──
_CASE_UI_006 = EvalCase(
    id='UI-006',
    legacy_id='',
    title='会话管理工作台 - 单列表（无筛选控件）+ 已结束会话续聊 banner',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['会话管理工作台：去掉「活跃/已关闭」硬 tab 与筛选控件，始终单列表展示全部会话（活跃在前、同组 updated_at 倒序），已结束会话灰化；查看已结束会话显示续聊 banner 可一键重新打开'],
    expectations=['direct_reply'],
    data_checks=['SessionList 单列表渲染：全部会话按「活跃在前 + updated_at 倒序」排序；无「活跃/已关闭」双 tab，也无「全部/活跃/已结束」筛选 chips/tab', '已结束会话行保留灰化 + 「已结束」徽标 + 重新打开按钮；活跃会话行保留「结束会话」菜单；空态统一「暂无会话」，搜索空态「没有匹配的会话」', '查看已结束会话时聊天区顶部显示「会话已结束」banner + 「继续此会话」按钮；点击调用 reopenSession 并聚焦输入框，banner 消失', '会话管理工作台统计条文案统一为「活跃/已结束/共」（无「已关闭」残留）'],
    skip_reason='[backend-contract] 纯前端会话列表/续聊交互由 vitest 单测 + E2E 点击链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'session-list', 'reopen'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-007 [NORMAL] 元元 C 端输入条 - 单容器语音优先（textarea 常驻 + 带文字标签的宽胶囊「按住 说话」松开发送）（源: cases/ui.yml）──
_CASE_UI_007 = EvalCase(
    id='UI-007',
    legacy_id='',
    title='元元 C 端输入条 - 单容器语音优先（textarea 常驻 + 带文字标签的宽胶囊「按住 说话」松开发送）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['元元 C 端（小程序/H5 同源）输入条为单容器语音优先布局：textarea 常驻（语音优先 placeholder「按住说话，也可以打字」），空草稿时右侧主键是带文字标签的宽胶囊「按住 说话」，有草稿时该键位变为发送；上滑取消录音；首访给一条一次性可关闭的语音引导'],
    expectations=['direct_reply'],
    data_checks=['mini-app MessageInput 单容器：textarea 常驻渲染（无键盘/语音模式切换键，已退役的 hold-btn/mode-btn/btn 类名不得复用），语音可用时 placeholder 为「按住说话，也可以打字」，语音不可用（H5）时回落纯键盘措辞且不显示语音入口', '语音优先形态：空草稿主键是带可见文字标签「按住 说话」的宽胶囊（图标 + 文字 + 按钮底齐备，触控区仍为 88px/44pt），有草稿变为发送圆键、流式中变为停止键；单行时加图键/输入框/主键同行垂直居中（真实几何由模拟器探针取证）', '一次性语音引导：首访展示即落已读标记（storage key voice_hint_seen）故只出现一次，可点关闭键立即消失，语音不可用时不展示；不因用户打字而提示改用语音', '按住语音键（touchStart）调用 startRecording，松开（touchEnd）调用 stopAndTranscribe → 转写文本直接 onSend（行为保持不变）；上滑超过阈值取消不发送', '空口/误触录音（<0.8s 或 <4KB）不发转写请求，toast「未检测到声音，已取消转写」；转写失败仍 toast「未听清，请重试」不发送（对齐 B 端 #2984 voice-guard 语义）', '添图入口统一：选图进草稿（预览可删），无按住模式下直接发图旁路；空文本有图点发送 → 纯图消息（UI-013 协议不变）', '自适应动作键：草稿为空显示语音键，有草稿变为发送，流式中变为停止；流式/无会话时禁止录音；转写失败 toast「未听清，请重试」不发送'],
    skip_reason='[backend-contract] 纯前端 C 端输入交互由 mini-app jest 单测验证（message-input.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟；xiaobu H5 E2E 基建在 WIP 分支（main 未落）',
    tags=['mini-app', 'voice-input', 'hold-to-talk'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-008 [NORMAL] 观星台会话列表折叠/展开窄 rail（参考 DSH sidebar 折叠交互）（源: cases/ui.yml）──
_CASE_UI_008 = EvalCase(
    id='UI-008',
    legacy_id='',
    title='观星台会话列表折叠/展开窄 rail（参考 DSH sidebar 折叠交互）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['会话列表支持折叠为窄 rail（图标态），展开恢复完整列表，折叠偏好持久化到 localStorage'],
    expectations=['direct_reply'],
    data_checks=['SessionList 折叠按钮 aria-label「折叠会话列表」且展开态 aria-expanded=true；点击折叠 → 窄 rail 仅保留「新建对话」图标按钮 + 展开 toggle（aria-label「展开会话列表」、aria-expanded=false），列表项/搜索隐藏', '再点展开 → 完整 w-64 列表恢复（新建对话/搜索/右键菜单功能全部保留）', '折叠偏好写入 localStorage（key chat.session-list.collapsed），刷新/重挂后恢复折叠态', '折叠动画为 Tailwind width transition + overflow-hidden（参考 DSH slide+crossfade 的简洁等价）'],
    skip_reason='[backend-contract] 纯前端会话列表折叠交互由 vitest 单测 + E2E 点击链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'session-list', 'collapse', 'rail'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-009 [NORMAL] 黄金策聊天输入框 - 拖拽图片作为附件上传（源: cases/ui.yml）──
_CASE_UI_009 = EvalCase(
    id='UI-009',
    legacy_id='',
    title='黄金策聊天输入框 - 拖拽图片作为附件上传',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策聊天输入框支持把图片文件直接拖拽到输入区作为附件上传，与点击「添加图片」按钮共用同一套校验与上传链路（最多 3 张、5MB、jpeg/png/gif/webp）'],
    expectations=['direct_reply'],
    data_checks=['输入区（aria-label「消息输入区」）绑定 onDragOver/onDragLeave/onDrop；拖拽悬停时显示「松开上传图片」高亮提示', 'drop 图片文件 → 调用 chatApi.uploadChatImages 并出现预览缩略图；拖拽非图片文件 toast「不支持的文件类型」、超 5MB toast「超过 5MB 限制」、超过 3 张 toast「最多上传 3 张图片」', '会话已关闭/流式中/上传中拖拽不生效；拖拽上传与点击上传共用 handleFiles 校验逻辑'],
    skip_reason='[backend-contract] 纯前端聊天输入拖拽交互由 vitest 单测 + E2E 点击链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'chat-input', 'drag-drop', 'image-upload'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-010 [NORMAL] 元元聊天主页快捷入口改版 - 转人工→查物流、退换货→售后咨询（源: cases/ui.yml）──
_CASE_UI_010 = EvalCase(
    id='UI-010',
    legacy_id='',
    title='元元聊天主页快捷入口改版 - 转人工→查物流、退换货→售后咨询',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['元元聊天主页四个快捷对话入口：查订单/找产品/售后咨询/查物流'],
    expectations=['direct_reply'],
    data_checks=['QuickActions 渲染 4 个入口：查订单/找产品/售后咨询/查物流（无「退换货」「转人工」文案残留）', '点击「查物流」发送物流查询 prompt（如「帮我查一下物流」），进入 C 端仅查本人已发货订单物流的链路', '点击「售后咨询」发送售后 prompt（如「我想咨询售后问题」），进入售后工单快捷对话', '「转人工」入口移除 + 转人工能力退场（2026-09-19 用户裁定）后，输入「转人工」关键词不再导向任何转人工能力：AI 如实告知系统无人工转接通道并继续服务（机器断言见 CH-015 的 forbidden_text）'],
    skip_reason='[backend-contract] 纯前端入口改版由 mini-app jest 单测 + xiaobu E2E 验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'quick-actions', 'chat-entry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-011 [NORMAL] 侧边栏移除「黄金策 · 在线对话」/chat 菜单入口 —— 智能体对话入口统一收敛到右下角浮动按钮（#3094）（源: cases/ui.yml）──
_CASE_UI_011 = EvalCase(
    id='UI-011',
    legacy_id='',
    title='侧边栏移除「黄金策 · 在线对话」/chat 菜单入口 —— 智能体对话入口统一收敛到右下角浮动按钮（#3094）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['隐藏侧边栏「智能客服」组「黄金策 · 在线对话」菜单入口：智能体对话统一经右下角浮动按钮（FAB）进入（issue #3094）'],
    expectations=['direct_reply'],
    data_checks=['Sidebar「智能客服」组子菜单：在线接待(/agent-workspace/human-sessions) 在前、知识库(/knowledge) 次之，共 2 项（#3094 黄金策·在线对话 入口已移除；#3081 起无 AI 客服配置菜单）', '「黄金策 · 在线对话」不再作为侧边栏菜单项渲染（mibao-chat 菜单配置与 MessageCircle 图标注册删除）；/chat 页面路由保留（ActiveSessions「查看全部」/深链/Header 面包屑不回归）', '权限过滤：agent:session 控制「在线接待」可见；无 agent:session → 隐藏「在线接待」，仅保留知识库（knowledge:manage）', '「智能客服」组子菜单均不可见时整组隐藏（不回归 UI-005 行为）'],
    skip_reason='[backend-contract] 纯前端侧边栏菜单由 vitest 单测验证（sidebar.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'sidebar', 'mibao', 'chat-entry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-012 [NORMAL] 销售订单页「刷新」按钮 — 保持当前筛选条件重新拉取（演示实时可见新订单）（源: cases/ui.yml）──
_CASE_UI_012 = EvalCase(
    id='UI-012',
    legacy_id='',
    title='销售订单页「刷新」按钮 — 保持当前筛选条件重新拉取（演示实时可见新订单）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['老板在销售订单页，顾客刚下单 → 点「刷新」按钮，新订单出现在列表（无需 F5/切 tab）'],
    expectations=['direct_reply'],
    data_checks=['订单列表查询按钮旁渲染「刷新」按钮（RefreshCw 图标，aria-label=刷新，title=刷新订单列表）', '点击「刷新」保持当前搜索条件/分页重新调用列表接口（GET /api/admin/orders），列表数据更新', '列表加载中（loading=true）时刷新按钮禁用（disabled），避免并发请求', '刷新失败 toast「加载订单失败」，页面不崩溃'],
    skip_reason='[backend-contract] 纯前端交互由 E2E 验证（tests/e2e/specs/orders/order-list.spec.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'orders', 'list', 'refresh'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-013 [NORMAL] 元元 C 端支持纯图消息发送（拍照识别：无文本仅图片 → 后端 vision 理解）（源: cases/ui.yml）──
_CASE_UI_013 = EvalCase(
    id='UI-013',
    legacy_id='',
    title='元元 C 端支持纯图消息发送（拍照识别：无文本仅图片 → 后端 vision 理解）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['顾客拍一张窗帘照片直接发送（不带文字），元元应能收到并走视觉理解推荐相似商品'],
    expectations=['direct_reply'],
    data_checks=['chatStore.sendMessage 允许 content 为空但 images 非空的消息：不再被 `!content.trim()` 守卫静默拦截（发送后 SSE POST /api/chat/send 带 images、message 为空串）', 'MessageBubble 对纯图消息（content 空 + images 有）不渲染空文本区，仅渲染图片缩略图', '空文本且无图片仍被拦截（不发送），行为不回归', '转人工态（handedOff+agentSessionId）纯图消息静默忽略（人工会话仅文本通道，不向客服发空文本）'],
    skip_reason='[backend-contract] 纯前端发送层由 mini-app jest 单测验证（store-chat.test.ts / message-bubble.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'chat-input', 'image', 'vision'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-014 [NORMAL] 元元聊天主页快捷入口六格化 - 算料报价与推荐热门商品并列（取消全宽）（源: cases/ui.yml）──
_CASE_UI_014 = EvalCase(
    id='UI-014',
    legacy_id='',
    title='元元聊天主页快捷入口六格化 - 算料报价与推荐热门商品并列（取消全宽）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['顾客打开元元聊天主页，快捷入口区六个入口等权排列：算料报价/推荐热门商品/查订单/找产品/售后咨询/查物流'],
    expectations=['direct_reply'],
    data_checks=['QuickActions 渲染 6 个入口：算料报价/推荐热门商品/查订单/找产品/售后咨询/查物流（无「退换货」「转人工」文案残留）', '「算料报价」为首项但不带 wide 全宽样式（与其余入口等权，2 列网格 3 行）；标题为「您可以试试以下问题」', '**不得**残留两栏分组结构（`.quick-actions__group` / `__group-head` / `__row` / `__row-arrow` 计数 0，无「下单小助手」「专属推荐师」「你可以这样对我说：」文案）—— issue #4236 回退后，`#4199` 的分组卡任何痕迹都不该留下（防半回退 / 死代码）', '点击「算料报价」发送算料 prompt（含 quote 路由关键词：用料/报价），直达 curtain_calc 算料报价链路', '点击「推荐热门商品」发送推荐 prompt，进入商品推荐问答', '其余入口行为不回归（查订单/找产品/售后咨询/查物流 prompt 不变）'],
    skip_reason='[backend-contract] 纯前端入口由 mini-app jest 单测验证（quick-actions.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'quick-actions', 'quote'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-044 [NORMAL] 元元聊天主页空态移除商品推荐卡（NewArrivals），推荐改由文字胶囊/快捷对话入口承载（源: cases/ui.yml）──
_CASE_UI_044 = EvalCase(
    id='UI-044',
    legacy_id='',
    title='元元聊天主页空态移除商品推荐卡（NewArrivals），推荐改由文字胶囊/快捷对话入口承载',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['顾客打开元元聊天主页空态：顶部三条居中的推荐胶囊（如「📐 按窗尺寸测算用布量与报价」），不再展示热销商品图片与名称'],
    expectations=['direct_reply'],
    data_checks=['空态（MessageList 无消息时）不再渲染 NewArrivals 商品卡片（无商品图/名横滑区；结构性判据 = `.new-arrivals*` 计数 0、无 img、无「¥」价格）', '空态渲染 RecommendChips 横滑区：5 条**纯前端静态策划文案**胶囊（图标+文案），点任一胶囊发送对应 prompt 进对话（与快捷入口同语义）', '胶囊**不请求商品接口**（不恢复 getNewArrivals）—— 与「空态不铺商品图/名」的裁定一致，推荐一律以对话形式承载；也不放真实价格/热卖数据（用户 2026-09-18 复选「保持静态」）', '文案定稿 = **专业服务句**（issue #4236 用户三轮裁定）：①「每条指向不同能力」→ ②「不要太口语化，我们得专业」（去「我/你/一问便知/搭最省的」这类聊天语气，改用行业术语 + 服务项）→ ③「最多 3 条最有价值」⇒ 保留 **3 条**：📐按窗尺寸测算用布量与报价（curtain_calc；术语：用布量/测算/报价）｜☀️遮光率等级与适用场景（遮光率等级/场景适配）｜🚚查询订单物流轨迹（customer_logistics_track）；覆盖**买前→买中→买后**三段，各指向不同能力、文案互不重复。**保留 emoji 图标**（视觉锚点，用户圈定保留的设计）', '布局 = **3 条 × 3 行、左对齐、与六格同宽同基线**（左右 24px，同 `.quick-actions` 的 padding）：每条胶囊保持自然宽度（非通栏），左边缘与六格左列**逐像素对齐**；**横滑实现已撤下**（`.recommend-chips__scroll` / `__row` 计数 0）—— 横滑必然左对齐 + 右端截断，3 条时只会把第 3 条切掉。**左对齐而非居中**的依据：三条宽度不同（201/175/149px），居中 ⇒ 左边缘参差（ragged left），而竖排列表的扫视锚点是左边缘', '空态保留品牌头 + 欢迎语 + 推荐胶囊 + 六格等权快捷入口（UI-014）', '推荐能力由「推荐热门商品」快捷入口与推荐胶囊以**对话形式**承载，商品推荐问答不回归'],
    skip_reason='[backend-contract] 纯前端空态由 mini-app jest 单测验证（recommend-chips.test.tsx / quick-actions.test.tsx）+ H5 视觉回归（xiaobu-h5.spec.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'chat-entry', 'empty-state'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-015 [NORMAL] 我的页移除「账号信息」占位入口（功能开发中占位不进 POC 演示）（源: cases/ui.yml）──
_CASE_UI_015 = EvalCase(
    id='UI-015',
    legacy_id='',
    title='我的页移除「账号信息」占位入口（功能开发中占位不进 POC 演示）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['顾客打开「我的」页，设置列表不应出现点了只提示「功能开发中」的占位入口'],
    expectations=['direct_reply'],
    data_checks=['设置列表无「账号信息」占位入口（页面顶部已有用户信息，占位菜单冗余）', '「关于我们」「隐私协议」「退出登录」等真实入口保留，不回归'],
    skip_reason='[backend-contract] 纯前端 UI 由 mini-app jest 单测验证（profile-page.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'profile'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-016 [NORMAL] C 端品牌名去硬编码 — 导航副标题企业名取自企业设置租户名（tenantName）（源: cases/ui.yml）──
_CASE_UI_016 = EvalCase(
    id='UI-016',
    legacy_id='',
    title='C 端品牌名去硬编码 — 导航副标题企业名取自企业设置租户名（tenantName）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['多租户场景下，C 端聊天页导航副标题应显示当前企业（租户）设置里的公司名，而不是写死的「观星台窗帘」'],
    expectations=['direct_reply'],
    data_checks=['导航副标题由 buildBrandSubtitle(user.tenantName) 生成：有租户名 → 「{企业名} · 智能购物助手」', '租户名为空/未登录 → 仅「智能购物助手」，不硬编码默认企业名', 'User 类型含 tenantName（camelCase，对齐 admin-api mini/login 返回）'],
    skip_reason='[backend-contract] 纯前端文案由 mini-app jest 单测验证（brand.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['mini-app', 'brand'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-017 [NORMAL] C 端隐藏工具执行指示器 — 工具调用过程不对客户展示（源: cases/ui.yml）──
_CASE_UI_017 = EvalCase(
    id='UI-017',
    legacy_id='',
    title='C 端隐藏工具执行指示器 — 工具调用过程不对客户展示',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户在聊天页不应看到「正在搜索商品...」「商品搜索完成」等工具执行过程指示器'],
    expectations=['direct_reply'],
    data_checks=['MessageBubble 不渲染 tool_calls/toolCall 指示器（数据仍保留供转人工等逻辑判定）', '未知卡片类型占位不暴露内部 type（显示「消息内容暂不支持预览」）'],
    skip_reason='[backend-contract] 纯前端渲染由 mini-app jest 单测验证（message-bubble.test.tsx），非 LLM 行为',
    tags=['mini-app', 'chat'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-018 [NORMAL] C 端智能客服名称取 botName 配置 — 思考中/空态/导航名去硬编码（默认元元）（源: cases/ui.yml）──
_CASE_UI_018 = EvalCase(
    id='UI-018',
    legacy_id='',
    title='C 端智能客服名称取 botName 配置 — 思考中/空态/导航名去硬编码（默认元元）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['C 端「正在思考...」/空态/导航名应使用企业设置里的智能客服名称（TenantAiConfig.botName），未配置默认「元元」'],
    expectations=['direct_reply'],
    data_checks=['admin-api mini/login 与 /api/admin/user/info 返回 botName（camelCase，对齐 User 类型）', '思考中文案 = 「{botName}正在思考...」；空态 = 「你好，我是{botName}」；导航名 = buildBotName(botName)', 'botName 为空/未登录 → 兜底「元元」（buildBotName 默认值）'],
    skip_reason='[backend-contract] 纯前端文案由 mini-app jest 单测验证（brand.test.ts + message-list），非 LLM 行为',
    tags=['mini-app', 'brand'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-020 [NORMAL] 销售订单采购明细 — 含加工项订单展示加工项计费（加工费合计 + 加工项明细行）（源: cases/ui.yml）──
_CASE_UI_020 = EvalCase(
    id='UI-020',
    legacy_id='',
    title='销售订单采购明细 — 含加工项订单展示加工项计费（加工费合计 + 加工项明细行）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['订单包含加工项（如打孔、韩式打褶定型）时，销售订单「采购明细」列应展示该项加工费与加工项明细，与详情页口径一致'],
    expectations=['direct_reply'],
    data_checks=['OrderTable 采购明细列的加工费与订单详情「费用构成」读**同一份权威落库值**（`processingInfo.processingFeeDetail.amount`，唯一实现点 = frontend/admin-web/src/lib/order-fee-display.ts::processingFeeOf），商品行后展示「+ 加工费{金额}元」', 'processingInfo 里的客户端副本（`processingFee`）**不采信**：副本 15 元 / 权威 0 元（fee_source=unpriced）时不得渲染「+ 加工费15元」（issue #7138 实证的不一致）', '存量单（#4406 接线前生成、无 processingFeeDetail）才回落：先取顶层 processingFee，再按 processingInfo.processingItems 的 amount/subtotal 求和兜底展示', '权威值 > 0 时「+ 加工费{金额}元」与详情逐分一致；权威未定价 ⇒ 列表不出现加工费字样（不写「+ 加工费0元」）', '空数据态下表头不被压成竖排：「采购明细」表头与数据格共用同一宽度契约（whitespace-nowrap + min-w-[280px]），tbody 只有 colSpan 空态行时也不塌'],
    skip_reason='[backend-contract] 纯前端列表展示由 vitest 单测验证（OrderTable.test.tsx / order-fee-source-guard.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'orders', 'list', 'processing-fee'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-019 [NORMAL] 黄金策工作台「洞察」重构为「会话简报」 — 工具台账转业务简报（结论/待办/办理结果/建议，/chat 工作台默认右侧展开可缩回）（源: cases/ui.yml）──
_CASE_UI_019 = EvalCase(
    id='UI-019',
    legacy_id='',
    title='黄金策工作台「洞察」重构为「会话简报」 — 工具台账转业务简报（结论/待办/办理结果/建议，/chat 工作台默认右侧展开可缩回）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策会话页顶部「洞察」抽屉展示的是工具调用台账（查询订单/参数校验/请求确认），商家用户不理解也不关心 agent 调用了哪些工具', '应改为「会话简报」：业务语言回答三个问题 — ①刚办了什么事（会话结论）②哪些事还需要确认/跟进（需要你处理）③涉及的业务对象什么状态、接下来可以问什么（办理结果 + 建议）', '从侧边栏「黄金策 · 在线对话」进入 /chat 工作台页右侧完全空白：会话简报应默认在右侧展开（docked 常驻列、无遮罩），可像抽屉一样向右缩回；右下角 FAB 浮窗入口保持现有设计（overlay 覆盖式抽屉、默认收起、带遮罩）'],
    expectations=['direct_reply'],
    data_checks=['frontend/admin-web/src/components/chat/SessionInsight.tsx 渲染四区块：会话结论 / 需要你处理 / 办理结果 / 接下来可以问，标题与顶部按钮文案为「会话简报」；variant prop 支持 overlay（覆盖式+遮罩，FAB 用）与 docked（右侧常驻列、无遮罩）两种布局', 'chat/page.tsx 传 <ChatArea insightDefaultOpen insightVariant="docked" />：/chat 工作台进入即右侧展开会话简报（不再右侧空白），点击顶部按钮可向右缩回、再点可再次展开；docked 变体无遮罩', 'FloatingAssistant.tsx 不传 insightDefaultOpen/insightVariant：FAB 浮窗保持现有设计 — overlay 覆盖式抽屉默认收起、点击展开、遮罩点击关闭', '会话结论 = buildSessionBrief 确定性推导：查询类按域聚合（如「查询了 2 笔订单」）、写操作完成（如「已创建售后工单」）、失败（含业务化原因）、待确认，全部业务语言，不含工具原始名/参数校验等机器语言', '办理结果 = extractLedgerRows：订单行带状态/金额/客户，有 orderId 时点击跳订单详情，其余点击发送追问；跨来源去重', '接下来可以问 = collectSuggestions 取最近 assistant 消息的 suggestions，点击即发送', '删除：处理进度工具时间线、业务域 ×N 计数、裸编号便签；会话标识弱化保留（调试用）'],
    skip_reason='[backend-contract] 纯前端重构由 vitest 单测（session-insight.test.ts + SessionInsight.test.tsx）+ e2e 抽屉链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'chat', 'insight'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端渲染用例：前置（会话消息流 + suggestions + 订单/售后台账行 + docked/overlay 两种布局入口）由单测自建（frontend/admin-web/tests/unit/lib/session-insight.test.ts、tests/unit/components/SessionInsight.test.tsx、tests/unit/components/ChatArea.test.tsx 直接构造 message/会话对象；e2e tests/e2e/specs/chat/chat.spec.ts 走 fixture 模式），不依赖共享夹具 ⇒ 前置不成立时单测直接红；agent-eval 栈不跑它',
)

# ── UI-021 [NORMAL] 黄金策展开大面板缩放手柄加大 + 缩放上限放开到视口 100%（拖到最大不留白）（源: cases/ui.yml）──
_CASE_UI_021 = EvalCase(
    id='UI-021',
    legacy_id='',
    title='黄金策展开大面板缩放手柄加大 + 缩放上限放开到视口 100%（拖到最大不留白）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策 AI 对话浮框（点开机器人后的默认大弹框）的顶部/底部/右侧缩放手柄只有 8px 太大难抓取；高度/宽度最多只能缩放到视口 90%，上下左右总会留空白拖不满屏'],
    expectations=['direct_reply'],
    data_checks=['MibaoChatPanel 顶部/底部手柄高度 h-2→h-3.5、右侧手柄宽度 w-2→w-3.5（抓取区域加大）', 'MAX_HEIGHT_RATIO / MAX_WIDTH_RATIO = 1：缩放手柄可把面板拖到视口 100%（innerHeight/innerWidth），不留边距空白', '保留原有最小尺寸边界（MIN_HEIGHT=300 / MIN_WIDTH=480）与 localStorage 持久化'],
    skip_reason='[backend-contract] 纯前端 React 组件/单测验证（MibaoChatPanel.test.tsx + useResizableHeight/Width.test.ts），非 LLM 行为',
    tags=['ui', 'admin-web', 'floating-assistant', 'resize'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-022 [NORMAL] 黄金策展开大面板新增右下角斜向缩放把手（同时调整宽度与高度）（源: cases/ui.yml）──
_CASE_UI_022 = EvalCase(
    id='UI-022',
    legacy_id='',
    title='黄金策展开大面板新增右下角斜向缩放把手（同时调整宽度与高度）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策大弹框只能横向（右侧把手）/上下（顶部/底部把手）分别缩放，没有斜向缩放能力；希望加一个右下角把手，按住后沿对角线拖动可同时调整宽度与高度'],
    expectations=['direct_reply'],
    data_checks=['MibaoChatPanel 渲染右下角把手 testid=chat-panel-resize-handle-corner，光标 nwse-resize，aria-label「拖拽调整大小（斜向缩放）」', '斜向拖拽时宽度=起始宽度+dx、高度=起始高度+dy 同步更新（useResizableHeight.setHeight / useResizableWidth.setWidth 新 API，夹在 min/max 内）', '松开后宽/高持久化到 mibao_chat_panel_height / mibao_chat_panel_width'],
    skip_reason='[backend-contract] 纯前端 React 组件/单测验证（MibaoChatPanel.test.tsx），非 LLM 行为',
    tags=['ui', 'admin-web', 'floating-assistant', 'resize'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-023 [NORMAL] 黄金策最小化浮窗 — 默认高度按视口自适应（≥600 上限 760）+ 底部/右下角把手调大小 + 位置与尺寸越界自动钳制（源: cases/ui.yml）──
_CASE_UI_023 = EvalCase(
    id='UI-023',
    legacy_id='',
    title='黄金策最小化浮窗 — 默认高度按视口自适应（≥600 上限 760）+ 底部/右下角把手调大小 + 位置与尺寸越界自动钳制',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策收起后的最小化小浮窗固定 400×600，高度不够、聊天布局拥挤；且换屏/改窗口后存储的浮窗位置会落到视口外看不见'],
    expectations=['direct_reply'],
    data_checks=['默认高度按视口自适应：min(760, max(600, innerHeight*0.8))，小屏不超过视口高度（贴边不留白）', '默认位置贴右下角：右侧 16px 边距、底部贴齐视口（top = innerHeight - 高，无底部预留空间 #3106）', '底部把手（testid=float-minimized-resize-bottom）拖拽调整高度、右下角把手（float-minimized-resize-corner，nwse-resize）斜向同时调整宽高；尺寸持久化 mibao_minimized_size', '移动拖拽按当前浮窗尺寸钳制（0 ≤ x ≤ iw-w、0 ≤ y ≤ ih-h）；读取存储位置/尺寸时越界自动钳回视口'],
    skip_reason='[backend-contract] 纯前端 React 组件/单测验证（floating-assistant.test.tsx），非 LLM 行为',
    tags=['ui', 'admin-web', 'floating-assistant', 'minimized-window'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-024 [NORMAL] 请求错误提示去重 — 拦截器已展示后端具体错误，页面不再叠加通用错误 toast（源: cases/ui.yml）──
_CASE_UI_024 = EvalCase(
    id='UI-024',
    legacy_id='',
    title='请求错误提示去重 — 拦截器已展示后端具体错误，页面不再叠加通用错误 toast',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['订单详情页点「确认付款」失败（如商品库存不足）：只看到 1 条具体错误提示（含「库存不足」详情），不再同时叠加「确认付款失败」通用提示'],
    expectations=['direct_reply'],
    data_checks=['request.ts 响应拦截器 toast 后端具体错误（success:false 业务错误 / HTTP 错误 / 网络错误 / 登录已过期）后，给错误对象打已提示标记（api-error.ts 的 markErrorToastShown / isErrorToastShown，Symbol.for 稳定键，frozen 对象不抛错）', '页面 catch 统一走 toastRequestError(e, fallback, {id?})：拦截器已提示 → 不再重复弹 fallback；传入 loading toast id 且已提示时先 dismiss（销售订单页「操作中…」不滞留）；未标记错误（客户端校验等本地错误）→ 弹 fallback', '订单域页面（订单详情/销售订单/发货/新建订单）请求失败 catch 不再重复 toast 通用错误；客户端校验类提示（如「请输入快递单号」「请完善订单信息」）保留不变，不回归'],
    skip_reason='[backend-contract] 纯前端错误提示行为由 vitest 单测验证（api-error/request/order-detail 三套），toast 链路由 request 拦截器单测覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'toast', 'error-handling'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-025 [NORMAL] 黄金策输入条统一重设计 — ArrowUp/Square 同形图标、录音状态条替代 placeholder 文案、预览缩略图内嵌容器（源: cases/ui.yml）──
_CASE_UI_025 = EvalCase(
    id='UI-025',
    legacy_id='',
    title='黄金策输入条统一重设计 — ArrowUp/Square 同形图标、录音状态条替代 placeholder 文案、预览缩略图内嵌容器',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策聊天输入条图标与状态呈现和元元同形：发送键 ↑（ArrowUp）、停止键 ■（Square）、语音键音波线稿（AudioLines 弃用 Mic），录音状态在容器内状态条展示而不占用 placeholder，图片预览缩略图收进输入容器内'],
    expectations=['direct_reply'],
    data_checks=['发送键图标 lucide ArrowUp（lucide-arrow-up）、流式中停止键 lucide Square（lucide-square）、语音键 lucide AudioLines（lucide-audio-lines，弃用 Mic）；title/aria 语义（发送/停止生成/语音输入）不变', '录音中：placeholder 保持「输入消息…」短句不被录音文案占用；容器内显示录音状态条「正在录音 {m:ss} · 点击停止，Esc 取消」（红点脉冲）；转写中提示「转写中...」不变；Esc 取消 / 右键取消行为不变（B 端转写追加进输入框，D1 既定差异不改）', '图片预览缩略图渲染在「消息输入区」容器内顶部；删除角标常显且带 aria-label「删除图片」；上传中添图键置灰（disabled）但不换图标（仍 ImagePlus），上传进度提示在预览块', '#2984 语音容错：空口语/误触录音（<0.8s 或 <4KB）停止不发转写请求，提示「未检测到声音，已取消转写」；转写失败文案友好化（网络失败/裸 500 转中文提示，不透出 Failed to fetch）'],
    skip_reason='[backend-contract] 纯前端输入条视觉/图标/状态呈现由 vitest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'chat-input', 'admin-web', 'design-system'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-028 [NORMAL] 岗位权限页（原角色权限）改名 + 侧边栏菜单七大组重构 + 员工选岗位自动带默认权限（#2969）（源: cases/ui.yml）──
_CASE_UI_028 = EvalCase(
    id='UI-028',
    legacy_id='',
    title='岗位权限页（原角色权限）改名 + 侧边栏菜单七大组重构 + 员工选岗位自动带默认权限（#2969）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['把「角色权限」改成「岗位权限」：每个岗位默认设置权限；创建员工选岗位自动带出该岗位默认权限，仍可自定义；侧边栏按七大组重构'],
    expectations=['direct_reply'],
    data_checks=['「角色权限」页整站改名「岗位权限」（页面标题/新增按钮/编辑弹窗/删除确认/空态，侧边栏入口与 Header 面包屑同步），URL /roles 不变', '侧边栏七大组（#5271 按业务动线重排）：工作台(经营看板+每日简报) / 智能客服(在线接待+知识库) / 商品与加工项(商品列表+加工项管理) / 交易管理(订单列表+售后工单+客户列表+财务对账) / 生产管理(作业看板+智能派单+工艺配置+计件工资) / 仓储与物料(入库单+余料台账+省料看板) / 组织管理(员工管理+岗位权限+企业基础信息) / 通知中心（独立）；**菜单项一项不少不减（21 项）**，只改分组归属与组名（原「客户管理」组并入交易管理组、原生产管理组的物料三项拆入新组「仓储与物料」）；权限过滤不回归（组内无可见子项则整组隐藏）', '侧边栏交互（#5271）：分组默认**只展开当前路由所在组**（组标题显示项数徽标，收起不等于丢项）；路由变化 ⇒ 自动展开新所在组；折叠态仍按组渲染锚点（组图标 + title=组名，分组信息不丢）；小屏为抽屉式浮层（遮罩点击关闭、内容区不占宽度），桌面端常驻可折叠', '🔴 **2026-09-29 改判（issue #5778，用户逐条裁定）**：上面的七组清单**已作废**，现为 **6 组 + 2 一级项**：工作台(经营看板+每日简报) / **客户服务**(在线接待+客户列表+知识库+售后工单) / 交易管理(订单列表+财务对账) / 生产管理(作业看板+智能派单+**加工项管理**+工艺配置+计件工资) / 仓储与物料(入库单+余料台账+省料看板) / 组织管理(员工管理+岗位权限+企业基础信息)；**一级项** = 分组之前的「商品管理」(`/products`，原「商品与加工项」组撤销后升为一级项) 与分组之后的「通知中心」。仍 **22 项一项不少不减**（🔴 2026-10-02 issue #5939 起 +「发货单」：仓储与物料组内、与「入库单」对称，权限码取**既有** `order:list` ⇒ 零授权 delta）；权限码 / 路径 / 门控一字未动（合并只改分组归属）。新增「常用（收藏）」= 用户自钉 4~6 项 pin 在侧边栏最顶部（权限被收回则该项自动消失）。 🔴 **2026-10-09 再改判（issue #6580，用户逐字「移除加工项管理和工艺配置这两个菜单」「企业基础信息改成企业基础设置，这个菜单和通知中心是一个类型的放到通知中心的上面，并且和通知中心一起沉底」）**：生产管理组**由 5 项收拢为 3 项**（作业看板 → 智能派单 → 计件工资）——「加工项管理」「工艺配置」两个菜单项从**四处载体**（`config/menu.ts` / `MenuController.MENU_TREE` / `AuthService.buildMenusByPermissions` / `menu_navigator.py` 的 `MENU_TREE`）同批移除，功能体并入 `/settings`「企业基础设置」页内的配置域；两个旧路径 `/production/processing`、`/production/routings` 保留为**重定向薄壳**（不 404）；组织管理组的「企业基础信息」改名「企业基础设置」并**升为尾部一级项**（与「通知中心」同为沉底项、紧排在它之前）。整树 **24 项 → 21 项**（6 组 18 组内项 + 2 一级项 + 1 尾部独立项）。**本改判不削弱任何既有断言**：更新后的判据与红证在 UI-066 / UI-067，旧 IA 的反向钉子（「客户管理」组与 `customer-center` 不得长回来）逐条保留并新增 `product-center` / `smart-customer-service` 两条。', '菜单搜索 / 命令面板（#5271）：⌘K（Ctrl+K）打开、侧边栏顶部入口亦可打开；空查询列出**当前用户有权访问**的全部菜单项；命中面 = 菜单名 ∪ 组名 ∪ 拼音首字母别名（如 ddlb→销售订单）；↑/↓ 选择、Enter 跳转、Esc/点遮罩关闭；无权限的项**不得**出现在结果里（搜索不是绕过权限的口子）', '创建/编辑员工：岗位改为下拉选择（岗位=角色体系，来自 /api/admin/roles/all），选岗位自动把该岗位默认权限（role_permissions codes）预填进权限树；仍可手动增删；编辑切岗位则重置为新岗位默认', '员工权限快照式（#2969）：提交时携带 position+permissions（permissions=最终勾选），不携带 role 字段（#2907 契约），后端按岗位名解析角色', '岗位权限弹窗「权限分配」按真实侧边栏菜单同构渲染（#3002；🔴 2026-10-01 改判，#5895）：权限树必须覆盖 `frontend/admin-web/src/config/menu.ts` 的**全部三个梯队** —— ① 一级项 `standaloneTopItems`（「商品管理」= `product:list`，渲染在**所有分组之前**、不在任何分组里，专属容器 `perm-standalone-top`）② 分组 `menuGroups` 的组名与组内菜单名（工作台：经营看板/每日简报；客户服务：在线接待/客户列表/知识库/售后工单；交易管理：销售订单/财务对账；生产管理：作业看板/智能派单/计件工资（🔴 #6580 起收拢为 3 项，加工项管理/工艺配置已移除）；仓储与物料：入库单/库存明细/发货单/余料台账/省料看板；组织管理：员工管理/岗位权限）③ 一级项（`standaloneTopItems`：「商品管理」+「企业基础设置」）+ 尾部项 `standaloneItems`（通知中心，全员可见**无码** ⇒ 不可授予、不进树）；勾选即授予对应权限码（roles 保存权限 ID，前端做码→ID 映射）；非菜单操作权限（仪表板查看/新增商品/商品分类/订单详情/新增员工等）单独一节「操作权限」；旧口径不再出现（英文 resourceType 组头 / 会话监控 / 快捷回复 / AI 客服配置 等旧名；组名「智能客服」「商品与加工项」随 #5778 作废）；保存契约不变（permissionIds = 权限 ID）。🔴 **#5895 的缺陷形态（本条原判据漏网）**：#5778 把「商品列表」升为一级项时只跟了侧边栏与 ⌘K，弹窗仍只遍历 `menuGroups` ⇒ 该菜单**整项不可勾选**（且因「省料看板」同持 `product:list`，它连「操作权限」兜底节也被过滤掉，一个入口都没有）；判据 = `frontend/admin-web/tests/unit/pages/roles.test.tsx` 的类级元守卫「`config/menu` 的菜单梯队全部已并入权限树」+「三梯队里每个带码菜单节点都能在权限树里勾到」+ 实例判据两条；红证（临时摘掉修复）= 3 failed / 1 passed，恢复后 14/14 绿'],
    skip_reason='[backend-contract] 岗位权限/菜单重构/选岗位带权限均由 vitest 单测 + E2E 点击链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'sidebar', 'menu', 'role', 'position', 'employee'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-029 [NORMAL] 黄金策面板缩放防冻结与恢复默认 —— 双击手柄复位 + 残留尺寸视口钳制 + 角把手误触防护（#3021）（源: cases/ui.yml）──
_CASE_UI_029 = EvalCase(
    id='UI-029',
    legacy_id='',
    title='黄金策面板缩放防冻结与恢复默认 —— 双击手柄复位 + 残留尺寸视口钳制 + 角把手误触防护（#3021）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策对话面板被拖拽/误触缩放后宽度被冻成固定 px：窗口尺寸变化后面板不重新适配，右侧露出大片白色卡片底（观感『页面坏了』），且界面上没有任何恢复默认大小的入口'],
    expectations=['direct_reply'],
    data_checks=['双击任意缩放手柄（底部/顶部/右侧/右下角）恢复默认尺寸（宽 100% / 高 85vh）并清除 localStorage（mibao_chat_panel_width/height）', '四个缩放手柄 title 含「双击恢复默认」，用户可发现自救入口', 'useResizableWidth/useResizableHeight 挂载时把超过视口的残留 px 钳制到视口上限，窗口 resize 持续钳制；视口变大不放大刻意缩小的浮窗（保留浮窗能力）', '右下角斜向把手未发生拖动的 mouseup 不持久化（单击误触不再把 100% 流式宽度冻结成 px）', '既有拖拽缩放/持久化行为不回退（UI-021/UI-022）'],
    skip_reason='[backend-contract] 纯前端 React 组件/hook 行为，由 vitest 单测（MibaoChatPanel.test.tsx + useResizableWidth/Height.test.ts）+ E2E 双击复位与角把手防误触链路验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'chat', 'resize'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-030 [NORMAL] 黄金策交互组件渲染三态固化 —— interactive（等待用户）/ readonly（已答只读）/ hidden（流式中），渲染决策收敛为纯函数 resolveInteractiveState，FAB 浮窗与 /chat 工作台共用同一 MessageList 链路（源: cases/ui.yml）──
_CASE_UI_030 = EvalCase(
    id='UI-030',
    legacy_id='',
    title='黄金策交互组件渲染三态固化 —— interactive（等待用户）/ readonly（已答只读）/ hidden（流式中），渲染决策收敛为纯函数 resolveInteractiveState，FAB 浮窗与 /chat 工作台共用同一 MessageList 链路',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策（admin-web）interact 交互组件（choice/confirm/form）渲染不确定：已回复的卡片锁是组件本地 useState(submitted)，FAB 关闭重开/会话切换后组件重挂载 → 锁重置 → 已经确认的卡片重新可点 → 可重复提交（重复建单/下单）', '企业级要求渲染逻辑与效果固定：同一消息任何时候渲染结果一致，不能一会渲染可交互控件、一会渲染只读/消失控件'],
    expectations=['direct_reply'],
    data_checks=['前置（precondition）：`frontend/admin-web/src/lib/interactive-render.ts` 导出纯函数 `resolveInteractiveState`，且 `MessageList.tsx` 的交互组件渲染确实经它决策（不是各调用点各判一次 `message.isStreaming`）—— 这是下面全部判据与 traces 里两个 vitest 文件的接地对象（success=true）；前置不成立时单测只能报「找不到该导出 / 行为不符」，判红会伪装成「渲染决策写错」', "frontend/admin-web/src/lib/interactive-render.ts（或等价位置）导出纯函数 resolveInteractiveState(msg) → 'interactive' | 'readonly' | 'hidden'：有 interactive 且非流式且未答 → interactive；有 interactive 且 interactiveAnswered → readonly；流式中或无 interactive → hidden", 'MessageList.tsx 渲染交互组件时经 resolveInteractiveState 决策，不再直接用 message.isStreaming 作为 disabled：流式中隐藏（hidden），已答（interactiveAnswered=true）渲染同构只读变体（disabled=true，按钮置灰不可点），未答复渲染可交互（disabled=false）', 'InteractiveMessage ChoiceCard/ConfirmCard/FormCard 在 disabled=true 时不可点击且视觉置灰（opacity/disabled 属性），点击不触发 sendMessage', '锁的单一事实源为消息级 interactiveAnswered（来自 store 透传/历史回放），非组件本地 useState：FAB 关闭重开（ChatArea 卸载重挂载）后已答卡片仍保持只读不可点', 'FAB 浮窗（FloatingAssistant）与 /chat 工作台共用 MessageList/InteractiveMessage 链路，两入口渲染决策一致'],
    skip_reason='[backend-contract] 纯前端渲染决策由 vitest 单测（components-chat.test.tsx + interactive-render 单测）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'chat', 'interactive', 'render-freeze'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-031 [NORMAL] 黄金策交互组件历史回放透传 —— interactive 载荷落库 + history 返回，刷新/切会话后已答卡片以只读变体呈现而非消失（源: cases/ui.yml）──
_CASE_UI_031 = EvalCase(
    id='UI-031',
    legacy_id='',
    title='黄金策交互组件历史回放透传 —— interactive 载荷落库 + history 返回，刷新/切会话后已答卡片以只读变体呈现而非消失',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['黄金策交互组件（choice/confirm/form）只存在于前端内存态：后端 save_message 只存 content+tool_calls，interactive 载荷从不落库，get_history 不返回；前端 selectSession 历史映射同样丢弃 interactive → 刷新/切会话后确认卡片整体消失只剩纯文本，待确认状态（session-insight detectPendingInteraction）失效'],
    expectations=['direct_reply'],
    data_checks=['ai-agent-service 保存 assistant 消息时把 interactive 载荷写入 metadata（interactive JSON 字段），get_history 返回 interactive 字段；历史消息的 interactive 状态（interactive_answered）随消息返回', 'admin-web store selectSession 历史映射透传 interactive 与 interactiveAnswered（不再丢弃），历史回放后交互组件按 UI-030 三态渲染（已答 → 只读变体，未答 → 仍可交互）', 'detectPendingInteraction 在历史回放后仍能检测未答交互（interactive 随历史返回）', '卡片信息（fields/options/formFields）不回退：历史回放的只读变体仍展示完整字段内容'],
    skip_reason='[backend-contract] 前后端契约由 vitest（interactive-contract.test.ts / components-chat.test.tsx）+ ai-agent 单测（get_history 返回 interactive）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'chat', 'interactive', 'history', 'persistence'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-032 [NORMAL] LLM 幻觉 <interact> XML 伪代码块剥离/解析 —— 后端识别文本流中的 <interact>…</interact> 并转换为 SSE interactive 事件，前后端兜底剥离防止原始 XML 泄漏到气泡（源: cases/ui.yml）──
_CASE_UI_032 = EvalCase(
    id='UI-032',
    legacy_id='',
    title='LLM 幻觉 <interact> XML 伪代码块剥离/解析 —— 后端识别文本流中的 <interact>…</interact> 并转换为 SSE interactive 事件，前后端兜底剥离防止原始 XML 泄漏到气泡',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['LLM（如 Vision 建品流程）把 <interact> <component>form</component> … </interact> XML 伪代码块直接输出到文本流，前端只剥离 ```tool_call 伪代码块不剥 XML → 卡片未渲染为 FormCard，用户看到原始 XML 文本（渲染不确定）'],
    expectations=['direct_reply'],
    data_checks=['ai-agent-service 在文本输出流中识别 <interact>…</interact> XML 块：解析 component/title/options/formFields/fields 等字段并转换为 SSE interactive 事件（与 interact 工具同协议，前端无需新分支）；同时从文本中剥离该 XML 块，不再进入 message.content', '解析失败或字段缺失时兜底剥离 XML 块（不展示原始 XML），SSE 不再下发残缺 payload', 'admin-web AIMessageContent.cleanContent 增加 <interact>…</interact> 剥离正则（与 ```tool_call 剥离同处），历史消息若有残留 XML 也不展示', '正常 interact 工具路径（SSE interactive 事件）不回退：choice/confirm/form 仍渲染为对应交互组件'],
    skip_reason='[backend-contract] 后端 XML 解析/剥离由 ai-agent 单测（test_chat.py XML 用例）验证，前端兜底由 vitest（components-chat.test.tsx cleanContent）验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'chat', 'interactive', 'xml', 'sanitize'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-033 [NORMAL] 知识库页 UI 修复：面包屑对齐菜单名 + 页面样式统一 + 分页不被黄金策浮动按钮遮挡 + 模板套用/候选采纳后结果立即可见可编辑（#3070）（源: cases/ui.yml）──
_CASE_UI_033 = EvalCase(
    id='UI-033',
    legacy_id='',
    title='知识库页 UI 修复：面包屑对齐菜单名 + 页面样式统一 + 分页不被黄金策浮动按钮遮挡 + 模板套用/候选采纳后结果立即可见可编辑（#3070）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['知识库页面包屑应与侧边栏菜单一致叫「知识库」（非「知识库管理」）；页面样式与全局产品样式一致；右下角分页不被黄金策浮动按钮遮挡；行业模板一键套用后套用出的卡片立即可见可编辑；待确认候选采纳后结果立即可见可编辑'],
    expectations=['direct_reply'],
    data_checks=['Header 面包屑 /knowledge → 智能客服 / 知识库（与侧边栏菜单名一致，不再出现「知识库管理」）', '知识库页内容区 p-6 内边距、页面标题 text-xl text-neutral-900 + 副标题、Tab 高亮用 primary-600（非蓝色 border-blue-500）、筛选/表单控件带标准 focus 态（focus:border-primary-500 focus:ring-2）', 'dashboard 布局底部预留黄金策浮动按钮（FAB）空间（main pb-24 + 内容卡片 min-h 联动），内容不足一屏时底部锚定元素（分页等）不被右下角浮动按钮遮挡、可正常点击', '行业模板一键套用后：跳转「知识卡片」Tab、重置筛选并刷新列表，套用出的卡片（published）立即可见且可编辑（打开编辑弹窗回填标题）', '待确认候选「采纳」后：跳转「知识卡片」Tab 并刷新列表，已发布卡片立即可见可编辑'],
    skip_reason='[backend-contract] 纯前端样式/交互由 vitest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'knowledge', 'breadcrumb', 'pagination', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-034 [NORMAL] 知识库「采纳/一键套用」成果去向提示与定位 — toast 带去向 + 采纳新卡高亮 + 套用确认弹窗 + 来源筛选定位（#3080）（源: cases/ui.yml）──
_CASE_UI_034 = EvalCase(
    id='UI-034',
    legacy_id='',
    title='知识库「采纳/一键套用」成果去向提示与定位 — toast 带去向 + 采纳新卡高亮 + 套用确认弹窗 + 来源筛选定位（#3080）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['知识库待确认候选「采纳」后用户不知道卡片去哪了；行业模板「一键套用」后不知道套出的卡片在哪。需要写操作反馈闭环：做了什么 → 去哪了 → 怎么找回来（toast 去向文案 + 落地高亮 + 前置确认弹窗 + 来源筛选自动定位）'],
    expectations=['direct_reply'],
    data_checks=['待确认候选「采纳」后：toast 文案包含去向（跳转知识卡片列表）；落地「知识卡片」Tab 后新卡行高亮定位（Table 的 highlightRowKey 匹配新卡 id，bg-primary-50），高亮 4s 自动消退', '行业模板「一键套用」：先弹确认弹窗（说明将新增 N 条并立即发布、已存在自动跳过），未确认不得调用 applyTemplate；确认后 toast 文案包含去向与定位方式（筛选「来源=模板」）', '套用确认后：跳转「知识卡片」Tab 并自动按来源=模板筛选（getCards 带 sourceType=template），列表仅显示模板来源卡片（批量成果可核对可编辑）', '「知识卡片」Tab 筛选区常驻「来源」下拉（全部来源/模板/会话提炼/文档提炼/人工——商品派生/加工项派生能力已移除且存量数据已清理（#3083/#3085/#3087），来源定义「一眼看懂」），用户可随时按来源定位卡片', '待确认/行业模板两处 Tab 副文案补充去向说明，与 toast 口径一致'],
    skip_reason='[backend-contract] 纯前端交互由 vitest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'knowledge', 'feedback-loop', 'locate', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-035 [NORMAL] 知识库来源定义「一眼看懂」+ 商品/加工项派生能力移除（issue #3083/#3085）（源: cases/ui.yml）──
_CASE_UI_035 = EvalCase(
    id='UI-035',
    legacy_id='',
    title='知识库来源定义「一眼看懂」+ 商品/加工项派生能力移除（issue #3083/#3085）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['知识库来源定义需用户一眼看懂；商品派生（#3083）与加工项派生（#3085）能力移除后，来源筛选仅剩活跃来源（模板/会话提炼/文档提炼/人工）'],
    expectations=['direct_reply'],
    data_checks=['来源筛选下拉选项 = 全部来源/模板/会话提炼/文档提炼/人工（SOURCE_FILTER_OPTIONS 排除 product/config 两个已移除的派生来源）', '来源徽标（列表列）：仅 模板/会话提炼/文档提炼/人工 四种；product/config 已从类型枚举与渲染中移除（存量数据已清理，无归档卡）', '来源定义全部自解释：模板/会话提炼/文档提炼/人工，无模糊词与已移除的派生来源'],
    skip_reason='[backend-contract] 纯前端文案/交互由 vitest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'knowledge', 'source-clarity', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-036 [NORMAL] 快捷回复功能下线 + AI 客服配置合并进企业基础信息「AI 客服设置」（#3081）（源: cases/ui.yml）──
_CASE_UI_036 = EvalCase(
    id='UI-036',
    legacy_id='',
    title='快捷回复功能下线 + AI 客服配置合并进企业基础信息「AI 客服设置」（#3081）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['快捷回复已被知识卡片（知识库）替代，功能全栈下线；AI 客服配置不再单独立菜单，合并进企业基础信息，区块命名「AI 客服设置」并说明作用'],
    expectations=['direct_reply'],
    data_checks=['侧边栏「智能客服」组不再有「AI 客服配置」菜单项（#3094 起 在线接待/知识库 共 2 项，黄金策·在线对话 入口已移除）；/chat/config 页面与 /agent-workspace/quick-replies 占位页删除，Header 面包屑无对应残留', '「企业基础信息」页（/settings）新增「AI 客服设置」tab（#3098 恢复 #3006 之前的左侧 tab 导航布局）：tab 栏 = 基本设置（公司名称+Logo）/ AI 客服设置 / 通知设置；AI 客服设置 tab 副文案说明作用「配置顾客在对话中看到的 AI 客服助手（元元）的名称与欢迎语」，含 AI 客服名称（必填）+ 欢迎语；🔴 **2026-10-01 改判（issue #5899）**：本 tab **不再有「保存」按钮** —— 两个字段**失焦即保存**（调用 /api/admin/tenant/ai-config；名称为空不提交并报错回退；值没变不发请求），成功提示「AI 客服名称已保存」/「欢迎语已保存，顾客侧将按新配置生效」', '企业基础信息页 tab 行为：默认激活「基本设置」tab；点击左侧 tab 切换内容区（AI 客服设置/通知设置内容不默认展示）；URL ?tab=ai 直达 AI 客服设置 tab（旧链接兼容，不再重定向 /chat/config）；修改密码/登录日志 tab 保持 #3006 隐藏；🔴 **2026-10-01 整格改判（issue #5899）** —— 用户逐字：「保存按钮放置的太底端了，用户容易忽略，我建议是如果有办法移除保存按钮就直接移除，通过更优秀的设计来满足配置变更保存的结果」⇒ **基本设置 / AI 客服设置两个 tab 的「保存」按钮整体移除**，改为**变更即保存**（口径与 #3119 通知开关、#3468 简报开关与生成时刻同源）：① 公司名称 / 企业编码 / AI 客服名称 / 欢迎语 —— **失焦即落库**（有改动才发请求）；② Logo —— **上传成功即落库、移除即落库**（改前要再点一次「保存」才生效）；③ 卡片标题下写明「修改后自动保存，无需手动提交」（把「没有保存按钮」这件事说出来，否则商家会去找按钮）；④ 失败沿用既有回退：企业编码 422 展示**服务端** message 并把输入框拉回已落库值，`#3099` 的「保存后刷新用户信息（侧边栏/右上角即时同步）」行为不变。判据 = `frontend/admin-web/tests/unit/pages/settings.test.tsx` 的实例判据 5 条 + **类级元守卫**「基本设置 / AI 客服设置 里每个可编辑字段都变更即保存（漏接线即红，枚举当前 tab 的每个文本框/文本域）」', '通知设置 tab（#3103/#3119）：仅系统通知总开关（启用系统通知，控制订单/客服等重要事件自动站内信；关闭后不再产生新站内信、历史保留）；开关点击即时保存（乐观更新+失败回滚，调用 /api/admin/settings），无独立保存按钮（开关类配置即时生效）；已移除通知邮箱输入框——notification_email 为僵尸字段（站内信无需邮箱、后端无邮件消费逻辑），SystemSettings 类型同步移除该字段', '快捷回复 UI 全部移除：quickReplyApi 与 QuickReply 类型删除，页面不再出现「快捷回复」tab/新建回复/模板列表', '权限联动（岗位权限页由 menuGroups 单源渲染）：权限分配弹窗与操作权限节均不再出现「AI 客服配置」「快捷回复」；agent:quickreply 权限码从后端权限目录与岗位默认权限移除；后端 /api/admin/quick-replies 接口与 quick_reply_manage 工具随功能下线'],
    skip_reason='[backend-contract] 纯前端页面/菜单/权限联动由 vitest 单测验证（settings/Sidebar/Header/roles.test），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'sidebar', 'settings', 'admin-web', 'permission'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-037 [NORMAL] 右上角用户信息卡片 — 点击展开 + 默认展示登录用户姓名 + 手机号/岗位/所属企业 + 企业名/Logo 侧边栏即时同步（#3099）（源: cases/ui.yml）──
_CASE_UI_037 = EvalCase(
    id='UI-037',
    legacy_id='',
    title='右上角用户信息卡片 — 点击展开 + 默认展示登录用户姓名 + 手机号/岗位/所属企业 + 企业名/Logo 侧边栏即时同步（#3099）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['点击右上角用户信息，默认展示当前登录用户名称；丰富该区域卡片信息（手机号/岗位/所属企业）；修改企业名称与 Logo 后应在商家后端（侧边栏）即时体现'],
    expectations=['direct_reply'],
    data_checks=['Header 右上角用户按钮默认展示当前登录用户名称（name→nickname→username→管理员 兜底链），点击展开下拉卡片（非 hover 悬停触发），再次点击/点击卡片外收起；🔴 2026-10-05（issue #6339）：「点击卡片外收起」的承载实现已由 header 内的 `fixed inset-0` 透明遮罩改为**文档级 mousedown 监听 + 容器 ref**（同 NotificationBell 范式）—— 原遮罩落在带 `backdrop-blur-sm` 的 header 内，其包含块是顶栏 56px、内容区点击落不到它上面（用户实测收不回去）', '用户卡片包含：头像（有 avatar 用图片，否则姓名首字）、姓名、账号（email 或 username）、手机号（username=手机号）、岗位（position）、所属企业（tenantName）、退出登录', 'fetchUserInfo 解包 /api/auth/me 的 { user, roles, permissions, menus } 包装结构：顶层 nickname/username/position/tenantName/tenantLogo 可读，roles/permissions/menus 保留（侧边栏过滤依赖）——修复右上角恒显「管理员」与侧边栏企业名/Logo 静默失效的根因', '「企业基础信息」保存成功后立即 fetchUserInfo 刷新，侧边栏企业名/Logo 即时同步（无需刷新页面）；toast「侧边栏将同步展示」与实际行为一致', '后端 /api/auth/me 与 /api/admin/user/info 的 user 内层返回 position（岗位，User 实体字段）'],
    skip_reason='[backend-contract] 纯前端交互 + 后端 DTO 由 vitest 单测与 MockMvc 集成测试验证（Header/auth store/settings/AuthIntegrationTest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'header', 'user-card', 'admin-web', 'settings'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-038 [NORMAL] 新增订单表单支持选择已有客户 — 自动回填收货信息（姓名/手机号/省市区），保留手动兜底（#3102）（源: cases/ui.yml）──
_CASE_UI_038 = EvalCase(
    id='UI-038',
    legacy_id='',
    title='新增订单表单支持选择已有客户 — 自动回填收货信息（姓名/手机号/省市区），保留手动兜底（#3102）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['新增订单表单不支持选择客户，收货信息需纯手动输入；增加「选择客户」能力：从客户列表搜索选中后自动回填，提升下单效率与体验'],
    expectations=['direct_reply'],
    data_checks=['新增订单页「收货信息」卡提供「选择客户」入口，点击打开客户选择弹窗（标题「选择客户」），加载客户列表（customerApi.getCustomers）', '弹窗支持按 姓名/手机号 关键词搜索（Enter/搜索按钮触发 getCustomers 携带 keyword）；客户行展示 姓名（wechatNickname 优先）+ 手机号 + 省市区 + 来源渠道', '选中客户后自动回填：收货人姓名/手机号/收货地址——**优先**取客户档案的默认收货地址（defaultReceiverName/defaultReceiverPhone/defaultReceiverAddress，客户管理「收货信息」卡片维护，issue #4419），档案未录时才回退旧口径（姓名=昵称、地址=省市区拼接 regionProvince regionCity regionDistrict）；仍可手动修改', '客户档案有常用物流时**按档案带出两个可编辑控件**（⚠️ **2026-09-21 改判，issue #4874**：原文的**只读提示**「常用物流：<方式> · <公司>」已被用户需求推翻并**整体删除** —— 用户原话「新增订单时收货信息中缺少用户的常用物流/快递以及常用公司，选择客户后要默认带出」⇒ 现在是 `order-logistics-type`（快递/物流专线，空值 = 「未指定」）+ `order-logistics-company`（datalist 候选 + 允许自定义）**两个可编辑控件**，档案没录时置空而**不编造「快递」**；发货页按同一档案带出方式/公司（UI-047）', "两控的值**随建单提交**为顶层 `logisticsType` / `logisticsCompany`（**缺值不写**）⇒ 后端落 `orders.logistics_type` / `orders.logistics_company`（V100）。⚠️ 该列**不设默认**（未传 ⇒ NULL）：若给 `DEFAULT 'express'`，「商家没选」与「选了快递」在库里不可区分，发货页的「订单值优先」会被幽灵 `express` 永久遮蔽客户档案（independent review #4878 修正）", '保留手动兜底：未命中客户/关闭弹窗后可直接手填收货信息提交订单；订单提交契约不变（OrderCreateRequest 无 customerId，不引入跨端契约改动）'],
    skip_reason='[backend-contract] 纯前端页面交互由 vitest 单测验证（orders-new.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'orders', 'customer', 'order-create', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-039 [NORMAL] 知识卡片：已归档卡片可「重新发布」+ 新增只读「查看」+ 副标题文案通俗化（#3108）（源: cases/ui.yml）──
_CASE_UI_039 = EvalCase(
    id='UI-039',
    legacy_id='',
    title='知识卡片：已归档卡片可「重新发布」+ 新增只读「查看」+ 副标题文案通俗化（#3108）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['知识卡片归档后没有恢复入口（归档成终点）；操作列没有不动数据的「查看」；副标题「LLM WIKI 知识卡片管理」对商家太技术化。需要：已归档卡片一键重新发布、只读查看弹窗、通俗副标题'],
    expectations=['direct_reply'],
    data_checks=['已归档卡片操作列显示「重新发布」（图标 RotateCcw），点击调用 publishCard（POST /{id}/publish，后端已放开 archived → published，#3108），成功后列表刷新为已发布状态（操作区出现「归档」，重新发布按钮消失）', '「重新发布」成功 toast 文案为「知识卡片已重新发布」（区别于普通发布的「知识卡片已发布」）', '操作列新增「查看」按钮（所有状态卡片可见）：点击打开只读详情弹窗「知识卡片详情」，展示 标题/分类/常见问法/标准回答/关键词 + 来源/状态/版本/更新时间 元信息；无「保存」按钮、字段不可编辑（与「编辑」弹窗分离，看内容不动数据）', '知识库页副标题不再出现「LLM WIKI」字样，改为通俗文案（如「AI 客服知识库 — 发布后的知识卡片将优先用于 AI 客服回答顾客问题」）'],
    skip_reason='[backend-contract] 纯前端交互 + 状态机 UI 由 vitest 单测验证（knowledge.test.tsx），后端状态机放开由 KnowledgeCardServiceTest 验证（API-015），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'knowledge', 'status-machine', 'read-only-view', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-040 [NORMAL] 发货单：发货人落库（预填当前登录人可改）+ 可打印纸质单据（发货前打 / 发货后补打）（#3768）（源: cases/ui.yml）──
_CASE_UI_040 = EvalCase(
    id='UI-040',
    legacy_id='',
    title='发货单：发货人落库（预填当前登录人可改）+ 可打印纸质单据（发货前打 / 发货后补打）（#3768）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['发货时要拿着一张单据照单拣货/打包，纸面还要留经手人（发货人）；但系统里发货只填了承运商+运单号，既没有可打印的发货单，也没有任何发货人留痕'],
    expectations=['direct_reply'],
    data_checks=['发货页新增「发货人」输入：默认预填当前登录人姓名（name→nickname→username 兜底链，但**不**退化为「管理员」这类角色名），允许改成实际经手人；清空则拒绝提交（toast「请输入发货人」）', '确认发货 payload 携带 shipperName（trim 后非空才下发）；后端 PUT /api/admin/orders/{id}/logistics 落库 order_logistics.shipper_name，传空时用 SecurityUser.userId 查 users.nickname 兜底（agent order_manage(update_logistics) 路径同口径——order_manage 透传 X-User-Id）', '更新已有物流时**仅**在显式传入非空才覆盖发货人：改运单号/纠错不等于换经手人；存量订单（shipper_name 为 NULL）不为历史数据猜经手人', 'order_logistics.shipper_name 必须 nullable：存量已发货订单历史上无此数据，纸面「发货人」栏显示「-」（#3818 裁定，不得留白、不得 undefined/null），不得回填假值（否则迁移失败或纸面出现伪造经手人）', '新增可打印「发货单」（ShipmentDoc）：A4（@page size: A4）+ body visibility 隔离；纸面含 订单号/下单时间/收货人/电话/地址/商品明细（品名·货号·颜色·规格·数量·单价·金额）/合计（总数量+总金额）/加工费合计（`ShipmentDoc.tsx` 的纸面标签真值）/备注/发货人（存量空值显示「-」）/物流公司·运单号（发货前留空供手写，发货后带出）', '入口两处：发货页（发货前打印，发货人取当前输入值，未保存也印）+ 订单详情页页面级「打印」入口里选**发货单**（补打——发货页有状态守卫，shipped 后进不去）。🔴 issue #7544 改判：详情页不再有独立的「打印发货单」按钮，也不再按状态显隐（待付款等未发货状态同样能补打，只是纸面物流 / 发货人栏为空）', '⛔ **发货单自 issue #7902 整体退场**（用户 2026-10-27 逐字「移除发货单打印」「统一到销售单上打印」）：纸、组件、发货页「打印发货单」、发货记录页「补打」一并撤下；上方纸面/入口类断言只作为**历史口径留档**，现行判据 = `frontend/admin-web/tests/unit/pages/ship-order.test.tsx` / `shipments.test.tsx` 的「零打印入口」与订单详情打印层里取不到 `print-preview-doc-shipment`', '发货单渲染在页面级，**不得**放进 Modal（Modal 为 max-h-full + 内部 overflow-y-auto，打印只会打出可视一屏、多页明细被裁）；每页只挂一份（.shipment-print-area 为全局选择器，挂两份会打印出两套单据）', '不向 C 端顾客泄漏发货人：customer_logistics_track 按白名单字段构造返回（order_id/order_no/tracking_number/company/status/status_text/latest/traces），响应中不含 shipperName', '加工项区（issue #7275 → #7605 → **#7891**）：**加工项绑商品行** —— 每个商品行下方跟一条子行（`shipment-item-processing-N`，单格 `colSpan` = 全表列数），文案 = 水洗唛式单行 `加工项：定型、韩褶 各 6.3 · 特殊选项：拼2次-布`（**加工费合计**仍在明细表之后单独一行右对齐，口径不变 = Σ 行级 `processingFee`）；「不绑商品」的表外一行（旧区头 `加工项（数量：米）`、锚点 `shipment-processing-items`）**退场**。行文案由 `frontend/admin-web/src/lib/processing-item-text.ts` 的 `processingItemsText()` / `processingPaperLine()` **单一构建器**产出（三份纸共用）、按**数据二态**：数量全等 ⇒ `定型、韩褶 各 6`（数字只说一遍）；数量不等 ⇒ `定型 6 + 韩褶 2`；单项 ⇒ `定型 6`（不写「各」）；缺数量 ⇒ 该项显式印 `—`（`打孔 —`）。🔴 **不得**用 `（A+B）×6`（用户 2026-10-24 裁定）：纯文本有运算优先级歧义（`定型 + 韩褶×6`），且与「加工费合计」并排会诱导客户拿它去乘出加工费（真值 = 组合价 元/米 × 加工费米数）；各加工项 quantity 可以不等、可以缺 ⇒ 无条件提公因子 = 把不等的数压成一个 = 报错数。执行点 = `frontend/admin-web/tests/unit/components/SalesDoc.test.tsx` 与 `QuotationDoc.test.tsx`（同一条不变量；发货单已于 issue #7902 退场）+ `frontend/admin-web/tests/unit/lib/processing-item-text.test.ts`；类级判据 = `tests/unit_ci_workflows/test_print_media_matrix_guard.py::test_c9_shipment_processing_items_bind_to_the_product_row`（子行锚点缺失 / 退回旧表外锚点 / 没 import 单一构建器 / 构建器缺全等形态 / 构建器里出现 `×` / 删掉加工费合计 均判红，含注入式红证）'],
    skip_reason='[backend-contract] 纯前端 UI + 后端字段落库，由 vitest 单测（ShipmentDoc/ship-order/order-detail/data-adapter）与 MockMvc/Service 单测（OrderControllerTest/AgentOrderServiceTest/UserServiceTest）验证；非 LLM 行为（agent 工具参数未变，发货人由后端按 X-User-Id 兜底），不进入 agent-eval 冒烟',
    tags=['ui', 'order', 'shipment', 'print', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-041 [NORMAL] 设置页开关几何完整性 — flex 行内开关按钮 shrink-0（轨道不压缩、圆钮不溢出，issue #3924）（源: cases/ui.yml）──
_CASE_UI_041 = EvalCase(
    id='UI-041',
    legacy_id='',
    title='设置页开关几何完整性 — flex 行内开关按钮 shrink-0（轨道不压缩、圆钮不溢出，issue #3924）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['企业基础信息 → 基本设置里「启用智能每日经营简报」开关样式异常：白色圆钮溢出蓝色轨道右缘（说明文字长的行里更明显）'],
    expectations=['direct_reply'],
    data_checks=['settings/page.tsx 两个开关按钮（启用智能每日经营简报开关 / 启用系统通知开关）类名含 shrink-0：作为 flex justify-between 行子项时不被长说明文字压缩，w-11 轨道保持 44px', 'E2E 几何断言（boundingBox）：开启态圆钮四边完整落在轨道内（右缘 ≤ 轨道右缘 + 0.5px），轨道宽 ≥ 43.5px —— 修复前实测轨道被压至 37.9px、圆钮溢出右缘', '点击简报开关 → PUT /api/admin/briefing/config 携带 enabled 翻转，toast 与真实结果一致（交互链路不回归）'],
    skip_reason='[backend-contract] 纯前端布局几何由 Playwright E2E 验证（tests/e2e/specs/settings/toggle-geometry.spec.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'settings', 'toggle', 'layout'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-043 [NORMAL] 元元选择卡片回传人话 — 点击选项发 label 而非内部编码（proc_item_* 用户看不懂）（源: cases/ui.yml）──
_CASE_UI_043 = EvalCase(
    id='UI-043',
    legacy_id='',
    title='元元选择卡片回传人话 — 点击选项发 label 而非内部编码（proc_item_* 用户看不懂）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['点加工项选择卡片里的「LG工艺 ¥50/件」后，聊天里用户气泡直接发出 proc_item_craft_lg 这种内部编码，顾客看不懂发的是什么'],
    expectations=['direct_reply'],
    data_checks=['ChoiceCard 点击选项回传 opt.label || opt.value（人话，如「LG工艺 ¥50/件」），不得回传内部编码 proc_item_craft_lg —— 与 admin-web InteractiveMessage.tsx 单一事实源及 AI 侧 nodes.py _card_accepts_answer（label/value 均接受）对齐', '选项缺 label 时回退 value（label || value 协议兜底不回归）', '提交锁（CH-030）不回归：点选后锁卡，后续点击不再触发 onAction', '多选卡（issue #3947）：卡声明 multiSelect=true 时点选项只本地勾选积累（零 onAction）、再点可取消，点「完成选择（N）」才一次性回传 `${multiSelectSubmitPrefix}${已选名称、拼接}`（默认「已选加工项：A、B」）；未勾选不渲染提交按钮；提交后锁卡。判据 = frontend/mini-app/tests/choice-card.test.tsx 与 frontend/bmini-app/tests/choice-card.test.tsx 的行为用例，接线普查 = tests/unit_ci_workflows/test_frontend_choice_multiselect_protocol.py', '多选字段不得被 store 白名单吞掉（issue #3947 的真实病根）：frontend/mini-app/src/store/chatStore.ts 的 onInteractive 原样透传 multiSelect/multiSelectSubmitPrefix/multiSelectSubmitLabel/multiSelectSkipLabel，判据 = frontend/mini-app/tests/store-chat.test.ts', '单选卡（无 multiSelect）点第一项仍立即提交，且不渲染「完成选择」按钮（防多选逻辑污染单选体验）'],
    skip_reason='[backend-contract] 纯前端组件行为由 jest 组件测试验证（frontend/mini-app/tests/choice-card.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'mini-app', 'choice-card', 'protocol'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-042 [NORMAL] C 端助手消息富文本渲染 — markdown 粗体/列表渲染为样式而非裸符号（真机实测反馈）（源: cases/ui.yml）──
_CASE_UI_042 = EvalCase(
    id='UI-042',
    legacy_id='',
    title='C 端助手消息富文本渲染 — markdown 粗体/列表渲染为样式而非裸符号（真机实测反馈）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['真机预览实测：元元回复含 **9231 遮光窗帘**、**几米** 等 markdown 加粗符与 - 列表，气泡里原样显示星号与短横线'],
    expectations=['direct_reply'],
    data_checks=['src/utils/richText.ts parseRichText：成对 **x** 解析为 bold 段，未闭合 ** 原样保留（流式安全），单个 * 不误吞；- 开头行解析为 bullet 行', 'MessageBubble 气泡文本区按行渲染：bullet 行带圆点缩进，bold 段走加粗样式类，空行保留段落间距'],
    skip_reason='[backend-contract] 纯前端渲染由工具单测验证（frontend/mini-app/tests/rich-text.test.ts），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'chat', 'rich-text'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-045 [NORMAL] 顾客端生产进度卡 — 进度%/当前工序/待完工序数/预计交付（不泄露内部信息，issue #3997）（源: cases/ui.yml）──
_CASE_UI_045 = EvalCase(
    id='UI-045',
    legacy_id='',
    title='顾客端生产进度卡 — 进度%/当前工序/待完工序数/预计交付（不泄露内部信息，issue #3997）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['顾客在元元对话里收到生产进度卡：显示加工单做到哪一步了（进度百分比）、当前在做哪道工序、还剩几道工序、预计什么时候交付'],
    expectations=['direct_reply'],
    data_checks=['进度百分比取 progress.percent；progress 缺省时按 已完/总数 推导，空态（无工序）显示「暂无生产进度」（不显示假进度、不空白）', '当前工序 = 第一个 status!=done 的工序；待完工序数 = status!=done 的工序数；交期字段缺省时不渲染交期行', '兼容两种载荷（M4-G-2 实装字段）：工序树 {positions[].operations[], progress:{total,done,percent}, expected_delivery_at} 与黄金策精简进度 {progress_percent, current_operation, pending_operations[], total_operations, done_operations, expected_delivery_date}', '不泄露内部信息：工人姓名 / 计件单价 / 成本 / qr_token 不出现在卡片文案（内部计件与对外加工费两套账分离）', "MessageBubble 的 cardData.type='production_progress' 渲染该卡（未知卡片占位分支不被命中）"],
    skip_reason='[backend-contract] 纯前端组件渲染由 jest 单测验证（frontend/mini-app/tests/production-progress-card.test.tsx），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'mini-app', 'production-progress', 'card'],
    persona='xiaobu',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-046 [NORMAL] admin-web 构建契约 - route 文件导出越界 / 预渲染期错误必须被 CI 的 next build 拦下（issue #4412）（源: cases/ui.yml）──
_CASE_UI_046 = EvalCase(
    id='UI-046',
    legacy_id='',
    title='admin-web 构建契约 - route 文件导出越界 / 预渲染期错误必须被 CI 的 next build 拦下（issue #4412）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['前端 PR：route 文件（page/layout/template/route）只导出框架认识的字段；预渲染期不得抛错'],
    expectations=['direct_reply'],
    data_checks=['pr-check 的 admin-web-test job 在 tsc/lint 之后执行 npm run build（Next-only 校验）', '该步有 job 内路径门控：无 frontend/admin-web/** 变更时**未跑**（「没跑」不得读成「通过」）', 'checkout 为 fetch-depth: 0（否则三点 diff 取不到 merge-base，门控恒判无变更）'],
    skip_reason='[backend-contract] CI workflow 结构由 pytest 单测验证（tests/unit_ci_workflows/test_admin_web_next_build_gate.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ci', 'next-build', 'build-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-047 [NORMAL] 发货页带出客户常用物流方式/公司 + 写入 order_logistics.logistics_type（issue #4419）（源: cases/ui.yml）──
_CASE_UI_047 = EvalCase(
    id='UI-047',
    legacy_id='',
    title='发货页带出客户常用物流方式/公司 + 写入 order_logistics.logistics_type（issue #4419）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['发货时要按客户常用的物流方式（快递/物流专线）和常用承运商预填，不用每次重选；物流类型要真的记到这一单上'],
    expectations=['direct_reply'],
    data_checks=['打开发货页时按订单 customerPhone 调 customerApi.getCustomers(keyword=phone)，**精确匹配 phone** 后才带出 defaultLogisticsType/defaultLogisticsCompany（关键词是模糊匹配，命中的其他客户不得采用）', '带出的常用公司在预置候选之外时，下拉补出该选项（否则 select 显示不出已存值）；用户已手动改过物流字段则不再覆盖（与发货人预填同口径）；查询失败不阻断发货', '**订单值优先**（⚠️ **2026-09-21 新增优先级，issue #4874**）：订单自带 `logisticsType` / `logisticsCompany`（建单时录的「常用物流/快递 + 常用物流公司」，落 `orders` 两列）时**优先用订单值**；订单没记的那一半才回落本用例的客户档案反查（既有兜底**不删、不改门禁**）。双向断言 + 注入式红证：把优先级调反 ⇒ 红', '确认发货 payload 携带 logisticsType（express/logistics），经 buildLogisticsPayload 透传；未选时不写（由后端按列默认 express 兜底，不写假值）⚠️ **2026-09-21 订正**：`order_logistics.logistics_type` 的列默认**未变**（仍是 `express`，V47 既有行为）；本批新增的是 **`orders`**（订单级「下单时约定的收货方式」）两列，那一对**有意不设默认**——两者不是同一张表，别混用'],
    skip_reason='[backend-contract] 纯前端交互 + payload 透传，由 vitest 单测（ship-order.test.tsx / data-adapter.test.ts / logistics.test.ts）覆盖；agent 工具参数未变，不进入 agent-eval 冒烟',
    tags=['ui', 'order', 'logistics', 'admin-web', 'customer'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-048 [NORMAL] 工艺配置页：规则 / 工序删除的二次确认改**弹框**（与「删除工艺路线」同一形态；弹框写清删的是哪一条 + 删除中禁用 + 失败理由逐条）（源: cases/ui.yml）──
_CASE_UI_048 = EvalCase(
    id='UI-048',
    legacy_id='',
    title='工艺配置页：规则 / 工序删除的二次确认改**弹框**（与「删除工艺路线」同一形态；弹框写清删的是哪一条 + 删除中禁用 + 失败理由逐条）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**规则删除 = 弹框**（不再就地展开）：点行的「删除」⇒ 弹框出现（`route-rule-delete-modal`），弹框**写清这条规则是什么**（触发类型 + 触发值 + 动作 + 目标工序，如「工艺 韩褶 → 在『三边』之后插入『韩褶』」）+ 影响（删除后不再增删这道工序；软删、历史加工单一字不变）；危险按钮用既有 danger 形态、取消为 secondary。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx「⑲-①」（**红证**：改前无弹框 ⇒ `Unable to find an element by: [data-testid="route-rule-delete-modal"]`，实测）', '判据 2·**取消 ⇒ 不发请求**，弹框关闭。证据：production-routings.test.tsx「⑲-②」', '判据 3·**删除中按钮禁用**（防重复提交）：确认按钮 loading 态禁用、取消按钮同时禁用；重复点击不会再发第二次请求。证据：production-routings.test.tsx「⑲-③」（`toBeDisabled()` + 二次点击后调用次数仍为 1）', '判据 4·**失败理由逐条在弹框里就地展示**（**不许**吞成一句「删除失败」）：后端 422 的 `error.details[].message` 逐条渲染（`route-rule-delete-reasons`），失败后弹框仍在（理由要看得见）。证据：production-routings.test.tsx「⑲-④」', '判据 5·**工序删除同一套弹框**（同一页面不留两套形态；#4947 起入口**只剩**抽屉 footer 那一处）：点抽屉 footer 的「删除」⇒ `operations-manage-delete-modal`，写清删的是**哪一道工序**（逻辑工序名 —— 变体名不上界面，issue #4622/#4886）；取消不发请求。证据：production-routings.test.tsx「⑲-⑤」（#4617 当时的**红证**：改前无弹框 ⇒ `Unable to find an element by: [data-testid="variant-delete-modal"]`，实测；#4947 把逐行那一套弹框去重退场后该 testid 已不存在，判据随之落在 footer 路径上）', '判据 6·**不动删除的后端语义与护栏**（#4608 刚修好：显式写列 + `updated_at` 推进 + 护栏一字不动）：`DELETE /route-rules/{id}` 与 `DELETE /operations/{id}` 的端点、请求体、响应形态、护栏判据**逐字未动**（本单只改二次确认的**形态**）。既有删除断言（逐条理由）一条未放宽：工序删除那条的**现状**渲染点是 `operations-manage-delete-reasons`（#4947 前是逐行弹框里的 `variant-delete-reasons`，该弹框已去重退场），规则删除那条仍是 `route-rule-delete-reasons`。证据：ProductionRoutingReadControllerTest「DELETE /route-rules/{id} ⇒ 200 软删 {id,deleted:true}；不存在/已软删 ⇒ 404」未改 + production-routings.test.tsx 的既有 ⑰-⑬/⑰-⑯/⑰-⑰ 用例保留', '**边界（如实登记）**：本单**不动** `routings/page.tsx` 里 #4613（条件工序规则常驻展开）/ #4615（页头「新增工序」入口）涉及的外壳与按钮 —— 那两处由已合入的 #4618 落地，本单只在其之上改删除确认形态。'],
    skip_reason='[backend-contract] 纯前端交互（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-routings.test.tsx 执行',
    tags=['ui', 'production-routing', 'route-rules', 'confirm-modal', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-049 [NORMAL] 工艺项页·**一张表装全部工序**（用户裁定 2026-09-21：删【打包发货】独立区块 ⇒ 两层分区退场；按车间分组可折叠；**不再有部位列**）（源: cases/ui.yml）──
_CASE_UI_049 = EvalCase(
    id='UI-049',
    legacy_id='',
    title='工艺项页·**一张表装全部工序**（用户裁定 2026-09-21：删【打包发货】独立区块 ⇒ 两层分区退场；按车间分组可折叠；**不再有部位列**）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=["判据 1·🔴 **一屏只有一张表，且装**全部**工序**（2026-09-21 改判，配套 #4886 / #4913）：容器 `operation-price-matrix`、表 `operation-workshop-table`；行来自价目读面（`GET /operation-positions`），`scope='position'` 与 `scope='set'` **同表**，一道逻辑工序一行（读面由 `ProductionOperationQueryService#collapseToLogical` 收敛，前端另按 `logical_name ?? operation` 去重兜住前后端各自上线的过渡期）。🔴 **改判要点（用户裁定 ⇒ 判据面缩小，不是放宽）**：改前这条守的是「**两层**：`scope='set'` 的成员落【打包发货】独立区块（`delivery-section`）、**不得**出现在工序层的行里」—— 用户 2026-09-21 裁定「这里的表单也直接删，不需要了」⇒ 该区块**整块删除**，那 5 道 `scope='set'` 工序（`打包` / `外帘打卷` / `外帘装袋` / `外帘发货` / `裁剪-布`）**并回这唯一一张表**（它们本来就在 `matrixRows` 里、有 `id`、可改价，独立区块只是同一批工序的**第二个视图**）⇒「按既有 `scope` 分区」这条判据**失去对象**（不再有两个载体可分区，如实登记为判据面缩小）；**补位的反向护栏不放宽**：`queryAllByTestId(/^delivery-/)` 必须为空（同一概念不得留下第二个载体）。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx 的「B1 一张表装**全部**工序（用户裁定 2026-09-21：删【打包发货】独立区块 + 两个 tab 合并）」+「B2 「工序」区按车间分组可折叠」", '判据 2·**按车间分组 + 可折叠**：组标题逐字为「<车间> · N 道」，点标题折叠/展开只影响该组（`matrix-workshop-<组>` / `matrix-workshop-toggle-<组>`）。证据：同文件 B3（**红证**：改前无分组 ⇒ `Unable to find an element by: [data-testid="matrix-workshop-toggle-裁剪"]`，实测）', "判据 3·**没有部位列**（2026-09-21 改判，issue #4886 去部位化）：工序层列头**逐字** = `['工序','单价','分组 · 单位 · 操作']`（🔴 **2026-09-21 改判（issue #4961）**：原第 3 列逐字是 `分组 · 单位 · 必完 · 操作` —— 「必完」随「完工 = 全部工序实例报满」**整条退场**（前端勾选框/徽标/chip/列头/预检全部退场），`matrix-must-finish-*` 一族 testid 一律为空；**不是**把列头文案改短，而是该维度不再存在） —— 部位列（`布帘` / `纱帘` / `帘头` / **`布料`**）**一律不再存在**；单价格 `operation-price-<逻辑工序名>`，`data-state` ∈ `priced` / `unpriced`（**两态**；🔴 **2026-09-21 改判（issue #4939，配套 #4951 去部位化彻底版）**：第三态 `na`（「不做」）**已退场** —— 存活价目行的 `applicable` 恒 `TRUE`（V102/V104）、`applicable` 也已从读面类型退场 ⇒ 该态**永不可达**，判据由「三态可区分」收敛为「恰两态 + 『不做』不得出现在任何单价格里」）。**反向护栏（判据升级，不是放宽）**：改前这条守的是「`布料` 不得当第 4 个部位列、但读面那一格仍在（`variant_operation_id` 的载体 + V88 保命格）」—— 现在**列与格都没有了**，所以守的变成：`queryByTestId(/^matrix-cell-/)` / `queryByTestId(/^matrix-applicable-/)` / `queryByTestId(/^matrix-price-input-/)` **三者都必须为空**；而 `variant_operation_id` **仍必须由读面给出**（收敛**只选行、不回落** —— 收敛后那一行上的 `variant_operation_id` 是孤儿判据 #4614 与实例化的载体）⇒ 孤儿仍按**数据**判、不按**列**判，`裁剪` **不得**被点名成孤儿。证据：同文件 B4（改判后）+「同一逻辑名的多行**收敛为一行**：30 行（不是 120 行），列头只有「一个单价」」（**红证**：注入「读面删掉 `布料` 行」⇒ 收敛结果变化、`operation-price-*` 的态断言红）", '**边界（如实登记）**：本用例只判 `jsdom` 可见结构；真实浏览器的 HTML 合法性与 CSS 布局由 UI-052 的**结构合法性断言**兜底，完整浏览器渲染仍**未采集**（见 issue #4721 的 P2-4 登记）。'],
    skip_reason='[backend-contract] 纯前端渲染（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-routings.test.tsx 执行',
    tags=['ui', 'production-routing', 'operation-price-matrix', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-050 [NORMAL] 工艺项页·**【打包发货】独立区块已删除**（用户裁定 2026-09-21）+ 工艺路线并入该位置**同屏** + 两个 tab（工序管理 / 算料配置）+ **行为变更如实登记**（零价目行的工序**进表**：`data-state=no_row` + 行尾 `管理▸` 可停用/删除，issue #5875）（源: cases/ui.yml）──
_CASE_UI_050 = EvalCase(
    id='UI-050',
    legacy_id='',
    title='工艺项页·**【打包发货】独立区块已删除**（用户裁定 2026-09-21）+ 工艺路线并入该位置**同屏** + 两个 tab（工序管理 / 算料配置）+ **行为变更如实登记**（零价目行的工序**进表**：`data-state=no_row` + 行尾 `管理▸` 可停用/删除，issue #5875）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=["判据 1·🔴 **独立区块整块退场 + 交付工序并回唯一那张表**（2026-09-21 改判，配套 #4913）：用户裁定逐字「这里的表单也直接删，不需要了，然后把工艺路线的功能放置到这块区域，两个tab合并成一个」⇒【打包发货】层（原 `delivery-section`）与它那一族 testid（`delivery-row-*` / `delivery-price-*` / `delivery-manage-*` / `delivery-must-finish-*` / `delivery-empty`）**一律不得存在**（`queryAllByTestId(/^delivery-/)` 必须为空）；那 5 道 `scope='set'` 工序（`打包` / `外帘打卷` / `外帘装袋` / `外帘发货` / `裁剪-布`）改由唯一那张表承载 —— 行 `matrix-row-<工序>`、价 `operation-price-<工序>`（`data-state` ∈ `priced` / `unpriced` —— **两态**，🔴 2026-09-21 #4939 改判：第三态 `na` 随 #4951 退场、恒不可达）、抽屉入口 `matrix-manage-<工序>`（🔴 **2026-09-21 改判（issue #4961）**：原列的「行尾 `matrix-must-finish-<工序>`」随「必完」**整条退场** ⇒ 该族 testid **一律不得存在**、`matrix-meta-<工序>` 的文本也不得含「必完」；列头逐字 = `分组 · 单位 · 操作`）。**判据面缩小如实登记**：原「一列价 + 不得按部位渲染 `matrix-cell-*`」那一格**失去对象**（列与格已随 #4886 去部位化退场），其结构纪律仍由「整页不得出现 `matrix-cell-*` / `matrix-applicable-*` / `matrix-price-input-*`」这条反向护栏承担。证据：同文件「B1 一张表装**全部**工序（用户裁定 2026-09-21：删【打包发货】独立区块 + 两个 tab 合并）」+「B3 这张表 = **一道工序一个价**（列头恰三列 + 行尾单位逐字取后端）」（#4961 起该测试标题里的「必完」已同步去掉）", '判据 2·**价与态逐字取价目读面，且不再有第二个来源**（2026-09-21 改判，配套 #4913）：唯一那张表的价态**逐字**由 `GET /operation-positions` 那一行算出（`cellState`，顶层函数、主表与单价格共用一份）：🔴 **2026-09-21 改判（issue #4939，配套 #4951 去部位化彻底版）**：原第一支 `applicable === false` ⇒ `na`（渲染逐字「不做」，`title` = 「「<工序>」当前配置为不做这道工序」）**已退场** —— 存活价目行的 `applicable` 恒 `TRUE`（V102/V104）且该字段已从读面类型退场（写面收到它即 **422**）⇒ 第三态**永不可达**；现在的判据只有两支：`unit_price == null` ⇒ `unpriced`（「未定价」，**绝不**回落工序库单价 —— 库行价是 `NOT NULL DEFAULT 0`，回落会把「未定价」变成真 ¥0.00）；否则 `priced` 显示 `¥x.xx`（**真 0 元照显示** `¥0.00`）。🔴 **事实订正（判据面缩小，纪律不放宽）**：改前这条守的是「行的 `price_state` / `price` 逐字用 `GET /operation-layers` 的 `delivery` 段聚合值、前端不重算」—— 独立区块删除后该端点在本页**零消费者**（随之退场：`deliveryAgg` / `layersError` 两个 state、`operationsRows` 的 `scope` 过滤、`deliveryOps` / `deliveryRows` 两块派生、以及那次请求），**端点本身未删**（仍是后端读面，见处理面用例 PG-039 / PG-054）。⇒ 「服务端聚合 vs 前端重算」这条漂移面就此消失；「逐字取读面、不前端重算」这条纪律**一字不放宽**，只是观测面从聚合段换成价目行。证据：同文件「B3 这张表 = **一道工序一个价**…」+「⑰-④ 三态可区分：`¥0.00` 是真价（≠「未定价」）、`未定价`、`不做`；未定价计数 = 待办数」', '判据 3·🔴 **改判（issue #5875，2026-10-01 用户裁定）**：**零价目行的工序进表** —— 表的行 = 价目行 ∪ **无价目行的库行**（`operationsRows = matrixRows ∪ orphanRows`，同逻辑名只出一行、已有价目行的逻辑名不补行）⇒ 这类工序有行、单价格 `data-state=no_row` + 文案「无价目行」、行尾 `管理▸` 可停用/删除。历史（改前形态）：表的行**只来自价目读面**（`operationsRows = matrixRows`）⇒ 「一格价目行都没有」的工序**不再有行**（改前由【打包发货】那道「**行不依赖矩阵格**」（issue #4729 / PG-054）兜底给行 —— 那条约束随区块一并退场）。**不静默**：`matrix-orphan-hint` **随本次改判整体退场**（信息进表 —— 同一概念不留第二个载体）；改判后由**行本身**承载（`data-state=no_row`），**不得**摆死路按钮（「接入部位价目」弹窗已随去部位化退场）。历史**边界（如实登记，不粉饰）**：改前前端测试只锁该提示的**缺失**态（同文件「㉕-② 反向护栏：已被矩阵格指向的工序**不算**孤儿（不提示）」断言 `matrix-orphan-hint` 为 null），**在场（报数）态无前端断言** ⇒ 这一格的证据只到「渲染分支存在 + 文案逐字取自源码（frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx 的 `matrix-orphan-hint` 分支）」，**运行期报数未采集**。', '判据 4·**两态语义不变**（反向护栏；🔴 2026-09-21 改判，issue #4939 配套 #4951 去部位化彻底版）：**有价**（`¥x.xx`，真 0 元**照显示** `¥0.00`）/ **未定价**（`unit_price=null`，**不得**显示成 `¥0.00`）两态可区分。**改判要点（判据面缩小、不放宽）**：原第三态「`不做`」（`applicable=false`）随 #4951 **退场** —— 存活价目行的 `applicable` 恒 `TRUE`（V102/V104）且该字段已从读面类型退场 ⇒ `na` **永不可达**，`data-state` 收敛为 `priced` / `unpriced`；判据由「三态可区分」改为「**恰两态** + 『不做』不得出现在任何单价格里」（补了反向断言），载体仍是 `operation-price-<工序>` 的 `data-state`。**「未定价 ≠ ¥0.00」与「真 0 元照显示」两条一字不放宽。** 证据：同文件「反向护栏 B5：两态语义**不变** —— `未定价` ≠ `¥0.00`；`applicable` 退场后**恰两态**（`na` 不可达）」+「⑰-④ 两态可区分：`¥0.00` 是真价（≠「未定价」）、`未定价`；第三态「不做」已随 #4951 退场（反向护栏）」。', '判据 5·🔴 **两个 tab（不是三个）+ 同屏**（2026-09-21 新增判据，配套 #4913；🔴 **同日收口（issue #4939，配套 #4935 的标签定名）**：第一个 tab 的标签逐字 = `工序管理`（**不是** `工序与路线`）—— 这一格是**已登记的短期不一致**，本次按运行期真值与测试标题收口）：`process-config-tabs` 里 `role=tab` 恰 **2** 个 —— `process-config-tab-process`（标签逐字 `工序管理`，默认 `data-state=active`）与 `process-config-tab-calc`（标签逐字 `算料配置`）；`process-config-tab-operations` / `process-config-tab-routes` **一律不得存在**。合并后的判据是**同屏**：工序表（`operation-price-matrix`）与路线列表（`routings-total`）在**同一 tab 里同时在场**（不再是「切换互斥」），且工艺路线**就在原【打包发货】的位置**（文档序在工序表**之后**，`compareDocumentPosition` 可判）；切到「算料配置」才是真互斥（两者都不在）。⚠️ **登记口径**：这一格此前**任何用例都没承载**（工艺配置页的 tab 结构只活在前端测试里）⇒ 按「不新增用例」的口径落在本条（同一用户裁定、同一页面形态），**不是**新增用例、也不放宽带宽。证据：同文件「**两个 tab**（工序管理 / 算料配置）且默认落前者；工序表与路线列表**同屏**（用户裁定合并后的形态）」+「切 tab **不丢状态**」。'],
    skip_reason='[backend-contract] 纯前端渲染（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-routings.test.tsx 执行',
    tags=['ui', 'production-routing', 'operation-price-matrix', 'orphan-visibility', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-051 [NORMAL] 工艺项页·🔴 **一口价写面**（`operation-price-<工序>` 就地改价，寻址 = 收敛后那一行的 `id`）+ 旧【布料单】定价区/两格写面**已随去部位化退场**（源: cases/ui.yml）──
_CASE_UI_051 = EvalCase(
    id='UI-051',
    legacy_id='',
    title='工艺项页·🔴 **一口价写面**（`operation-price-<工序>` 就地改价，寻址 = 收敛后那一行的 `id`）+ 旧【布料单】定价区/两格写面**已随去部位化退场**',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**写面入口 = 工序单价表上的单价格**（2026-09-21 改判，issue #4886 去部位化）：在 `operation-workshop-table` 的某一行点 `operation-price-edit-<逻辑工序>` → 填 `operation-price-input-<逻辑工序>` → `operation-price-save-<逻辑工序>` ⇒ 发 `PUT /api/admin/production/operation-positions/{id}`，body **只带** `{unit_price}`（不夹带 `applicable` 等）。改前这一格写的是【布料单】小区里 `裁剪` / `打包` 两行（`fabric-sheet-section` / `fabric-sheet-row-*`）—— 该区已整区退场，判据**改判到主表**、不放宽（仍要求「明确、可见的位置 + 就地改价 + body 恰好一个键」）。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx「收敛规则：优先 `applicable=true`…」（**红证**：把编辑入口改成 `disabled` ⇒ `Unable to find an element by: [data-testid="operation-price-edit-工序1"]`）', "判据 2·**改价寻址 = 收敛后那一行的 `id`**（2026-09-21 改判，issue #4886）：读面**可能仍返回同一逻辑名的多行**（前后端各自上线的过渡期）⇒ 前端按 `logical_name ?? operation` 收敛，并**保留收敛后那一行的 `id`**；断言 = 改 `工序1` 的价时发的是**那一行**的 id（夹具里 `mp-工序1-布帘`，不是 `mp-工序1-帘头` / `-布料`）—— 选错行 = 改了另一个价。证据：同文件「收敛规则」用例的 `toHaveBeenCalledWith('mp-工序1-布帘', { unit_price: 3.5 })`", '判据 3·🔴 **旧两格写面已不存在**（2026-09-21 改判，issue #4886 去部位化）：`fabric-sheet-section` 与 `fabric-sheet-*` 整区退场（用户裁定：一道工序一个价后它与主表重复）；`matrix-price-input-打包-布料` / `matrix-price-input-裁剪-布料`（原 `id` = `lc-8` / `lc-12`）**一律不得存在**。**反向护栏**（这是本条改判后真正承重的一格）：`queryByTestId(/^fabric-sheet-/)` 与 `queryByTestId(/^matrix-price-input-/)` 都必须为空 —— 「布料单」这条**专用定价旁路**不得以任何形态复活（复活 = 同一个价有两个写面）。证据：同文件「同一逻辑名的多行收敛为一行」的 testid 反向断言组', '判据 4·**旧「格缺失给出路」整格退场**（2026-09-21 改判，issue #4886）：改前「`× 布料` 这一格缺失 ⇒ 两道工序各给出「接入部位」+「补套行业模板」两个可点动作」（`fabric-sheet-attach-*` / `fabric-sheet-seed-*`）—— 部位维度退场后**不再有「某一格缺失」这个状态**，该区的两个动作随之消失。**保留不放宽的判据**：① 存量孤儿仍**如实可见** —— 🔴 **2026-10-01 改判（issue #5875）**：不再靠 `matrix-orphan-hint`（该提示已退场），而是**在表里成行**（`data-state=no_row` + 行尾 `管理▸` 可停用 / 删除）；② 页面**不得**摆死路（无出路的可点按钮）—— 「接入部位价目」弹窗已退场，故不得留下指向它的残留入口。证据：同文件的 `matrix-orphan-hint` 在场/缺失两态', '判据 5·**结构合法（issue #4721 P2-1）—— 改判为「结构性不可达」**（2026-09-21，issue #4886）：改前那条守的是「【布料单】小区那一格不得渲染成 `<td>` 且其父元素不得是 `<td>`」（`<td>` 嵌 `<td>` 是非法 DOM）；现在该小区**整区退场** ⇒ 非法嵌套**结构性不再可能**（不再有嵌套小区可断言），故本条判据改为：**该区与它的结构断言随能力一并退场**，且页面不得以任何其它形态把「单价格」渲染成嵌套 `<td>`。⚠️ 照实登记：这是一条**判据面缩小**（能力被用户裁定删除 ⇒ 判据失去对象），**不是**放宽——同一份结构纪律仍由工序层的表结构（`operation-workshop-table` 三列）承担。', "判据 6·🔴 **工序「停用」写面发出的 `status` 必须落在后端受理词表内**（2026-10-03 新增，issue #6103；与判据 1 同一写面族 —— 都是本页把值发给后端的那些面）：工序管理页的行尾 `管理▸` 抽屉 → 「停用」⇒ 发 `PUT /api/admin/production/operations/{id}`，body 恰为 `{status}` 且取值 ∈ `active|disabled`；**不得**是 `inactive`。病根（实测：租户 20 真实浏览器 + 真实接口）：前端逐字发 `{status:'inactive'}` —— 那是「**加工项**」域 `ProcessingItemStatus` 的词表，**抄错了域** ⇒ 后端 **422**「status 仅支持 active/disabled」⇒ 按钮 **100% 失效**（toast + 抽屉红字都是这句，库里 `status` 一直是 `active`）。**修的是 UI 侧取值，后端词表一字不动**（后端 `ProductionOperationCommandService.STATUSES` 与路线域一致）。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx「#6103 抽屉「停用」发出的 payload.status 落在**后端受理词表**内（断言 payload，不断言文案）」—— 断言的是**实际发出的 payload**（不是 toast、不是红字文案）；**红证（实测）**：`expect(sent).toBe('disabled')` 与 `expect(BACKEND_ACCEPTED).toContain(sent)` 两条都报 `expected 'inactive' to be 'disabled'`。类型面同时收窄：`ProductionOperationStatus = 'active' | 'disabled'`（`ProductionOperationUpdateParams.status` 不再是裸 `string`）⇒ 同类错值在 `tsc` 当场红（红证：`tsc` 报 **TS2820**（旧值不可赋给 `ProductionOperationStatus`））。**类级元守卫**（让同类进不来）：tests/unit_ci_workflows/test_operation_status_vocab_parity.py 机械判红三态 —— ① 前端联合类型 ⇄ 后端 `STATUSES` 逐值相等；② 写面纵深（本页每一处 `status` 字面量都在词表内）；③ 成员逐项冻结（两边一起改也红）。**红证（实测）**：把本页写面值改回旧值 ⇒ 「工序管理页发出的 status 取值不在后端受理词表内：['inactive']（后端受理 ['active', 'disabled']）」；把后端 `STATUSES` 加一个前端没登记的值（`deleted`）⇒ 「后端有、前端没有：['deleted']」。**边界（如实登记）**：射程 = 上述两个源文件 + 本页这一处写面；`ProductionRoutingCommandService.STATUSES`（路线域）不在面内。"],
    skip_reason='[backend-contract] 纯前端交互（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-routings.test.tsx 执行',
    tags=['ui', 'production-routing', 'operation-price', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-052 [NORMAL] 工艺项页·**种子自愈**：就绪度按「两条基础路线是否齐」判 + **补套入口已整体退场**（issue #5874；开租自动套用保留）（源: cases/ui.yml）──
_CASE_UI_052 = EvalCase(
    id='UI-052',
    legacy_id='',
    title='工艺项页·**种子自愈**：就绪度按「两条基础路线是否齐」判 + **补套入口已整体退场**（issue #5874；开租自动套用保留）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=['判据 1·**就绪度②判据换源**：不再「数路线条数」（改前 `工艺路线 2 条` 就显示「已完成」），而是**两条基础路线是否齐**（`窗帘工序路线（默认）` + `布料工序路线`）并**点名**缺哪条。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx 的 §6-②（**红证**：改前 `data-state` 仍是 `done`，实测）', '判据 2·🔴 **改判（issue #5874，2026-10-01 用户裁定「移除这个功能」）**：**补套行业模板入口已整体退场** —— `seed-templates` / `seed-template-<id>` / `seed-template-apply-*` 一族 testid **一律不得存在**（前端不再有 `getSeedTemplates` / `applySeedTemplate`，后端 `GET /seed-templates` 与 `POST /{id}/apply` 两个端点**同批删除**，见 PG 侧同批改判），**开租时的自动套用保留**（`RegistrationService` → `ProductionSeedTemplateService.applyTemplate`）。历史（改前形态）：工序库**非空**但缺 `布料工序路线` ⇒ 补套入口（`seed-templates`）**仍可见**（改前判据是 `!operationsReady` ⇒ 工序库非空时被隐藏）；🔴 **2026-10-01 事实订正（issue #5858）**：「可补齐的缺失项」由**两类**扩到**三类** —— 缺基础路线 / 缺基线工序（工序库为空）/ **有工序没有价目行（孤儿）** ⇒ 判据订正为「**存在可补齐的缺失项 ⇒ 显示；三类都不缺 ⇒ 不显示**」（与设计 `docs/design/public-operations-and-craft-ui.md` §6 修法 A 的原文一致；改前孤儿那一类没接线 ⇒ 页面提示会指向一张**根本没渲染**的卡）。证据：同文件 §6-① 与 §6-① 反向护栏 + ⑨c-⑦（红证：把渲染条件改回两类 ⇒ ⑨c-⑦ 红，实测）', "判据 3·🔴 **改判（issue #5874）**：`applySeedTemplate` 与「一键套用」按钮**都已退场** ⇒ 本条判据**失去被测对象**（保留在册、不再有断言）；改判后的判据 = 「**入口不存在**」（`queryByTestId('seed-templates')` 为 null、api 客户端无这两个方法）。**边界（如实登记）**：开租自动套用仍由 Java `RegistrationServiceTest` 覆盖，本文件不再有前端半边。", '判据 4·🔴 **2026-10-01 改判（issue #5858；用户逐字「这个页面的向导式已经和实际功能不匹配了，重构这个向导」）：就绪度向导由四步改判为**五步** —— ① 工序与单价 → ② 工艺路线 → ③ 默认路线 → ④ 算料配置 → ⑤ **裁高配置**（`readiness-step-cut-config`）。改前四步向导**不知道裁高存在**（tab `process-config-tab-cut` 已随 #5161/#5777 上线）。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx 的 ⑨c-③ / ⑨c-④（红证：删掉第 ⑤ 步 ⇒ `getByTestId` 抛错）', '判据 5·**每一步的计数与它所指的区块同源**（第 ① 步 = 表头 `operation-price-matrix-total` 的**同一份** `operationsRows`；改前用工序库行数 ⇒ 同屏两个数字打架：截图实证「工序库 40 道 · 已完成」与表头「29 道工序」+「有 11 道工序还没有价目行」并存）；第 ① 步的完成判据 = 表里有工序 ∧ **无未定价** ∧ **无孤儿工序**（`未定价 ≠ ¥0.00`、报工白干；孤儿 = 库里有工序却没有任何价目行）。证据：同文件 ⑨c-① / ⑨c-②（红证：label 改回 `工序库 ${total} 道` ⇒ ⑨c-① 红；判据去掉未定价/孤儿 ⇒ ⑨c-② 与 ⑨c-⑦ 红，实测）', '判据 6·**每一步一个可点的去处**（`readiness-goto-<key>`）：点算料 / 裁高 / 工艺路线各自的按钮 ⇒ **目标区块真的可见**（切 tab + 滚到锚点），不再只写「下方…」「切到…tab」——那类文案在别的 tab 上就是**假指路**。证据：同文件 ⑨c-⑤（断言落在**可见面**：目标 panel 的 testid + 目标 tab 的 `data-state=active`）', '判据 7·**首屏即真值**（issue #5858 用户裁定「首屏就读取算料 + 裁高」）：算料与裁高两个读面都在**首屏**就发（不必先点 tab 才知道配没配）；读失败 ⇒ 如实 `unknown` + 状态词「读取失败」，**不谎报「已配」**。证据：同文件 ⑨c-⑥（红证：把算料读面改回懒加载 ⇒ 红，实测）'],
    skip_reason='[backend-contract] 纯前端渲染 + 既有端点透传（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-routings.test.tsx 执行',
    tags=['ui', 'production-routing', 'seed-template', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-053 [NORMAL] 订单详情页「打印报价单」A4 — 按商品行成套 + 组件/货号/颜色/门幅/尺寸/数量/单价/小计 + 金额汇总 + 扫码支付（issue #4965 / #7527）（源: cases/ui.yml）──
_CASE_UI_053 = EvalCase(
    id='UI-053',
    legacy_id='',
    title='订单详情页「打印报价单」A4 — 按商品行成套 + 组件/货号/颜色/门幅/尺寸/数量/单价/小计 + 金额汇总 + 扫码支付（issue #4965 / #7527）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['这是从订单上打印的报价单，用来发给客户的，也可用于生产，这是A4大小，这个用来参考设计我们的打印制式', '把订单的打印功能改成这样的报价单'],
    expectations=['direct_reply'],
    data_checks=['订单详情页点页面级唯一「打印」入口 → 在打印层里选**报价单**标签，先看纸面预览再出纸（`window.print()` 仍只在 `usePrintDoc` 一处；issue #7544 起入口与订单状态无关，任何状态都能补打）—— 改前是 shipped/completed 操作区的「打印报价单」按钮（issue #4965 的形态，2026-10-23 改判）；`QuotationDoc` 在**页面级**挂载一份（不进 Modal、每页只挂一份）', '纸面四段齐全（A4，`@page { size: A4 }`）：① 表头 = 报价单 / 单号 `orderNo` / 货运（`logisticsType` + `logisticsCompany`，两者都缺 ⇒ 该栏不印）/ 客户·电话·地址 / 备注；② 正文 = **每个商品行自成一套**（用户裁定：不做樘窗分组），段头 `第N套/共M套` + `本套金额`，每段一张 8 列表 `组件 | 货号 | 颜色 | 门幅 | 尺寸 | 数量(米) | 单价(元/米) | 小计`（🔴 issue #7527：**品名列与工艺行不印** —— 用户 2026-10-23 逐字「报价单不要品名列和工艺行」）；③ 汇总 = 本单总金额 / 优惠金额 / 本单应收；④ 页脚 = 温馨提示常量 + 扫码支付码', '逐列映射（issue #7527 后 8 列）：组件 = 面料行 `processingInfo.componentRole`（缺省即主布）/ 加工费行「加工费」；货号 = `skuCode`（经 `lib/order-item-sku.ts::orderItemSku()` 唯一取值口；原读的 `productCode` 不在响应里 ⇒ 纸面恒空，issue #6869）；颜色 = `processingInfo.colorName`；门幅 = `processingInfo.doorWidth`（同一取值口格式化为 `2.8米`）；尺寸 = `width`×`height`（米，任一缺 ⇒ 不印）；数量 / 单价 / 小计 = 面料行 `quantity`（米）/`unitPrice`/`amount`（= 单价×数量，经 `lib/order-amount.ts::fabricSubtotal()` 取 —— 🔴 **不许直读 `subtotal`**：它的语义二义，「新增订单」页落的 subtotal 已含加工费，再单列加工费行 = 双算，issue #7724）、加工费行 `processingFeeDetail.meters`（加工费米数，缺 ⇒ 回落 `quantity`）/`processingFeeDetail.unit_price`（组合价 元/米，缺 ⇒ `—`）/`processingFee`（整笔，仍并进「本套金额」）。🔴 **加工费行的单价格不得取 `processingFee`**（issue #7716，用户 2026-10-25 截图：「这里加工费的单价没有取对数据」—— 修前单价 = 小计 = 51.10，而真单价 = 51.10 ÷ 7.3 = 7.00 元/米）；边界：`processingFee` 含按套选项 / 拼色加价时 `单价 × 数量 ≠ 小计`，纸面**不摊平均价**。**品名与工艺文案都不上纸**（issue #7527）：品名在面料行 / 加工费行连印两遍（产品设计原则 P2「信息不重复」），工艺（部位 / 加工类型 / 用料公式 / 算料）属生产侧信息，留在订单详情页与 `ProcessingDoc`', '加工费**单独成行**（`processingFee > 0` 才出）：与参照物的一处**有意差异** —— 参照物把加工费并进面料单价，而我们 `unitPrice` 与 `processingFee` 是两笔真实金额，必须分别列示，否则商家对不上账', '金额口径单一真值：行小计（本套金额）= `lib/order-amount.ts` 的 `paperLineSubtotal(item)` = `fabricSubtotal(item) + processingFee`（`fabricSubtotal` = 服务端 `amount`（单价×数量）优先、`subtotal` 仅兜底），与 `OrderItemList` 的明细行小计**同一份**实现（不各算一套，issue #4965）；🔴 issue #7724（用户 2026-10-25 同一张截图）：同一张纸出现过「本套金额 327.04」而「本单应收 275.94」——加工费被算两遍（`subtotal` 已含费 + 又加 `processingFee`）⇒ 面料金额一律走 `fabricSubtotal`；汇总三个数字只读订单字段 `totalAmount` / `discountAmount` / `actualAmount`，**不自己求和**', '缺值不渲染（用户裁定 ①）：上期余额 / 预存抵扣 / 账户余额 / 交付日期 / 制单人一律不印；键缺席 / null / 空串 / 空数组 ⇒ 该行不出现；纸面绝不出现 `undefined` / `null` / `NaN`（含整单缺值扫描）', '页脚扫码支付码 = `TenantPaymentQrcode`（`GET /api/admin/settings/payment-qrcodes`，`settingsApi.getPaymentQrcodes`）：有码 ⇒ 印图片 + 收款方；**没有码 / 缺 `imageUrl` / 拉取失败 ⇒ 整块不出现、不画假码**；常驻组件**不在挂载时**拉码（`beforeprint` 时才拉，避免每次打开订单详情页都发请求）', "收款码标签逐字 `微信支付`（issue #7605，用户 2026-10-24 逐字「这里把微信改成微信支付是否更好？」）：白纸上「二维码 + 微信」在中文语境里默认指「加微信好友」，而这里印的是收款码 ⇒ caption = `微信支付`、`alt` = `微信支付收款码`；对侧仍是 `支付宝`（**不加**「支付」——本词自带支付语义，不是漏改）。执行点 = frontend/admin-web/tests/unit/components/QuotationDoc.test.tsx 的「预览层（inline）挂载即出码」；红证：标签改回 `微信` ⇒ `toContain('微信支付')` 与 caption 逐字断言同时红（旧写法 `toContain('微信')` 对新旧两种文案都绿 = 零判别力）", '打印隔离沿用 `components/orders/ShipmentDoc.tsx` 的范式 6 条：portal 到 `document.body` 直接子级 + 容器自身 class `quotation-print-area` + `display:none` 与 `@media print` 显形 + `body > *:not(.quotation-print-area){display:none!important}` + visibility 防御 + 不进 Modal + 每页只挂一份'],
    skip_reason='[backend-contract] 纯前端打印纸面 + 既有端点只读（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/QuotationDoc.test.tsx、tests/unit/pages/order-detail.test.tsx、tests/unit/lib/logistics.test.ts 执行',
    tags=['ui', 'order', 'quotation', 'print', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端纸面用例：前置（订单对象含明细/物流/备注、收款码 map）由单测自建（frontend/admin-web/tests/unit/components/QuotationDoc.test.tsx 直接构造 Order/OrderItem 并注入 paymentQrcodes；tests/unit/pages/order-detail.test.tsx mock `orderApi.getOrder`；`settingsApi.getPaymentQrcodes` 打桩），不依赖共享夹具 ⇒ 前置不成立时单测直接红；agent-eval 栈不跑它',
)

# ── UI-054 [NORMAL] 企业基础设置页「算料口径」域 - 按域分组 + 每参数三件套 + 默认值可见 + 行式配置只给入口（源: cases/ui.yml）──
_CASE_UI_054 = EvalCase(
    id='UI-054',
    legacy_id='',
    title='企业基础设置页「算料口径」域 - 按域分组 + 每参数三件套 + 默认值可见 + 行式配置只给入口',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['issue #5131：商家可配参数散在 6 个页面 / 7 张表 ⇒ 收进「企业基础设置」页的配置域，按域分组一处列出（**当前指针**）', 'issue #6573（用户 2026-10-08 裁定方案 C）曾把「参数总览」升为一级菜单项 `/settings/params` —— 🔴 **该一级项已由 #6580 撤掉**（用户逐字「参数总揽不要单独搞个菜单，这些信息都直接做到企业基础信息中」「我的目的是要能移除加工项管理和工艺配置这两个菜单」）⇒ **当前**：配置面在「企业基础设置」页内的配置域，旧深链 `/settings/params` 只作重定向（不 404）'],
    expectations=['direct_reply'],
    data_checks=['「参数总览」的**一级菜单项席位已撤掉**（issue #6580：内容并入 `/settings`「企业基础设置」页内的配置域，席位改由「企业基础设置」占用）；旧深链 `/settings/params` 与 `settings?tab=params` 仍**不 404**（重定向到 `/settings`）。#6573 那一轮的形态（独立一级项 `/settings/params`，节点码 = 路由守卫码 = 该页第一屏读码 `production:view`）**已退场**，保留为历史口径', '**配置主线**（issue #6573）：常驻面只有**一行摘要**（完成数 + 缺口 + 下一步）；逐项明细按需展开且**折叠态下逐项 DOM 不渲染**（§31 P1）；每步三态 = 已配置 / 待配置 / **读不到**（读失败 ⇒ unknown，绝不画成「待配置」）', '**域级权限**（issue #6573）：算料域需 `production:view`、AI 客服域需 `system:manage`、余料**尺寸**域需 `processing:manage`；不持该码的域**不渲染也不请求**（域 label 真值源 = `frontend/admin-web/src/lib/config-center-domains.ts` 的 `remnant-sizes`；issue #6827 起因旧文案仍写「余料回收」域 ⇒ 判据行同批改准）', '域清单按 PARAM_DOMAINS 渲染（算料 / AI 客服 / 加工费 / 工艺）；每个标量参数渲染 label + hint + impact 三件套', '算料域当读面 source 不等于 stored ⇒ **域级**说明「下表全部为引擎默认值」（横幅 + 标题下口径徽标）；**逐键不再渲染任何默认态徽标**（issue #6857 改判，用户逐字「不要每行都写个默认，太丑了」⇒ §31 P2 信息不重复）', '「高级」默认收起：初始不渲染其中参数，点开后渲染', '参数文案里不出现数字字符（扫描 tenant-params.ts 全部文案）；算料域 common 并 advanced 与 CALC_SCALAR_KEYS 双向相等', '算料口径读面失败（权限拒绝等）⇒ 渲染可行动话术（含「请联系管理员」），不静默空白', '行式配置（加工费组合 / 特殊选项价 / 工序库 / 工序管理 / 计件）只给入口链接与「钱在哪」说明，不在本页做列表编辑', '阈值试算（§22 P4）：双列对照「按当前口径」与「按你改的阈值」；判定依据逐字来自服务端 auto-features（config 透传，不本地判、不本地拼文案）；改阈值 ⇒ 用新值重发试算；服务端不可用 ⇒ 可行动话术（**不得**显示成「不判任何特征」）；本块**不发任何 PUT**', '**数字框精度与 0 值**（issue #7548，用户 2026-10-23 裁定「算料口径的输入框都允许设置3位小数」「另外还要都允许设置为0」）：算料口径所有数字框（10 标量 + 档位褶倍 + 拼色配布 + 阈值试算 4 格）失焦按 **3 位小数**归一（`0.125` 原样留住、`0.1234` ⇒ `0.123`；改前按 2 位 ⇒ 被改成 `0.13`）；单/多开余量、上下卷边、超宽/超高阈值、褶倍下限、用料进位步长**允许设 0**（0 = 不留边 / 全部按超额 / 关闭护栏 / 不进位），单色每折用料与档位褶倍仍须 > 0（0 米 = 0 元报价）', '**算料口径域 = 算料配置的唯一写面**（issue #6825）：域内就地可改 **10 标量**（含**拼色单开 / 拼色多开余量**两项独立参数）+ 档位表（显示名 + 满度逐行可改）+ 拼色配布长度表 + `default_formula` select，**只有一个**保存按钮；保存 `PUT` 带**全量 13 键**（缺键 ⇒ 后端静默回默认值）；422 ⇒ `details[].message` 逐条上屏、**草稿不回滚**、不谎报「已保存」；数字格清空 ⇒ 空框（不得出现字面量 `NaN`）', '**板子退役**（issue #6825）：`/production/routings` 的 tab 收敛为「工序管理 / 裁高配置」两个（`process-config-tab-calc` 与全部 `craft-calc-config-*` DOM 不得存在）；就绪度第 ④ 步「去处理」是**跨页链接** `/settings?domain=calc`（不是页内切 tab、不是死按钮）；旧深链 `?tab=calc` ⇒ `router.replace` 到 `/settings?domain=calc` **恰好一次**、不 404 不落空白', '**类级守卫：每个配置域都有写面**（issue #6825 判据 6）：遍历 `CONFIG_DOMAINS`（含 `mainlineSteps`）断言 `config-domain-panel-*` 内有可交互控件，且该域有 `[data-write-exit]` 写出口（两者成对 ⇒ **只留试算框**那种「有输入框、没保存」的形态必红）；台账未登记即抛错（fail-closed）', '**行式紧凑版式**（issue #6857，用户裁定方案 B）：算料域的数值输入**与名称同一行**（输入框紧邻的前一个兄弟 = 名称元素）、定宽 `w-28` + 数字右对齐（`tabular-nums`）、**不得** `w-full`；行间细分割线、**不再用卡片**；档位表 显示名 `w-40` / 褶倍 `w-28`、拼色表 `w-28`、备用公式 `select` `w-64`', "**行内不标默认态**（issue #6857，用户裁定方案 C）：`param-unset-*` / `param-is-default-*` / `param-changed-*` **一个都不在**；替代 = 域级信号（横幅 + 口径徽标）+ 「恢复为默认值」按钮（把**整份**草稿写回 `defaults`；`defaults_source !== 'engine'` ⇒ 禁用；**不自动保存**）", '**类级守护：配置页数值输入必须定宽**（issue #6857 判据 5）：本域每个 `calc-caliber-*` 输入/下拉都带定宽 token（`w-28`/`w-40`/`w-64`）且**不得** `w-full`；`boundedInputCls` 的替换必须真的生效（`inputCls` 丢了 `w-full` ⇒ 自证红，防静默退化成整列宽）', '🔴 **2026-10-17 用户裁定（两条）**：① 「把算料口径里面的这行字都拿掉吧」—— 参数行内**整行**「改它会怎样：… 说明」退场（含行尾 `param-doc-*` 锚点），影响说明的唯一载体是同屏术语区块的「参数当前值」表；承载体 = `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx`（逐条断言页面上取不到 `改它会怎样`、`param-doc-*` 为 `null`，并反向自证 `glossary-param-*` 目标行仍在）。② 「两个参数一行排列的布局是否更美观」⇒ 常用 / 高级参数容器改为 `grid grid-cols-1 gap-x-8 xl:grid-cols-2`（窄屏单列），判据 = 同文件的「两列排布（xl+）」用例（把 `divide-y` 单列写回 ⇒ 红）。三件套口径（人话名 / 口径提示 / 就地可改）一条不放宽。'],
    skip_reason='[backend-contract] 纯前端页面与只读展示（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx（算料口径域面板；它承接的是 #6826 删掉的那个死代码组件的面）、frontend/admin-web/tests/unit/pages/settings-params.test.tsx（新页面 + 配置主线）、frontend/admin-web/tests/unit/lib/config-readiness.test.ts（三态判据）、frontend/admin-web/tests/unit/lib/tenant-params.test.ts 执行',
    tags=['ui', 'settings'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端用例：前置（算料配置读面与 AI 配置读面）由单测 mock `@/lib/api` 自建（#6573 起算料域读面由**页面**发起、以 props 注入面板），不依赖共享夹具 ⇒ 前置不成立时单测直接红；agent-eval 栈不跑它',
)

# ── UI-055 [NORMAL] 数字输入框统一治理：0 打不进去 / 小数点吞键 / 中间态丢失 —— 共享 NumberInput（type=text + inputMode=decimal + 字符串草稿），站点级落地 SkuMatrix 价格库存 / 算料配置参数 / 工人端报工数量（issue #5198）（源: cases/ui.yml）──
_CASE_UI_055 = EvalCase(
    id='UI-055',
    legacy_id='',
    title='数字输入框统一治理：0 打不进去 / 小数点吞键 / 中间态丢失 —— 共享 NumberInput（type=text + inputMode=decimal + 字符串草稿），站点级落地 SkuMatrix 价格库存 / 算料配置参数 / 工人端报工数量（issue #5198）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['migao 整个页面系统的数字输入框有不少问题，我碰到过 1 个是不能直接输入 0，所以导致无法输入 0.？这样的需求，还有其他问题，你统一把代码审查一遍。'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**控件形态**：共享组件 `frontend/admin-web/src/components/ui/NumberInput.tsx` 用 `type="text"` + `inputMode="decimal"`（**不用** `type="number"`：浏览器对 `0.` / `.` / `-` 这类中间态按非法浮点数处理，受控回写即吞键），内部持有**字符串草稿**，`onChange(v: number | null)` 在草稿可解析成有限数时回调该数、**0 原样回调**（不得出现 `value={n || \'\'}` / `Number(raw) || 0` 这类把 0 与空混为一谈的归一化）；`forwardRef` 透传真实 input；默认 className 与仓库既有输入框逐字一致（UI 回退检测比对 neutral token）。证据：frontend/admin-web/tests/unit/components/NumberInput.test.tsx 的「控件用 type="text" + inputMode="decimal"」「默认 className …逐字一致」「forwardRef 拿到真实 input 元素」（**红证**：把组件换回 `type="number"` + `value={n || \'\'}` 形态 ⇒ 判据 1/2 全红，实测 `AssertionError: expected \'\' to be \'0\'`）', '判据 2·**中间态逐键不丢**（用户原始 bug 的正身）：输入序列 `0` ⇒ **DOM 值仍为 "0"**、回调 `0`；续输 `0.` ⇒ DOM `"0."`、回调 `null`（不谎报成 0）；再输 `0.5` ⇒ 回调 `0.5`；清空 ⇒ DOM `""`、回调 `null`；负号中间态 `-` ⇒ DOM `"-"` 不被吞；`abc` 等非法字符 ⇒ 草稿与 DOM 都不变（不静默变 0）。证据：NumberInput.test.tsx 的 ①②③⑥ 与「非法字符被忽略」。**红证（真实浏览器 + 真实 React 19，Chrome for Testing 实测）**：旧形态 `value={n || \'\'}` + `onChange(Number(raw))` 在 `0 → . → 5` 序列上 `dom=""` / `state=0`（输入框敲下 "0" 当刻被清空 ⇒ 永远打不出 0.x）；本组件同序列 `dom="0"/"0."/"0.5"`', '判据 3·**失焦归一化与边界**：`decimals`（默认 2）截断 —— `0.567` 失焦 ⇒ DOM `0.57`、回调 `0.57`；尾随小数点 `2.` ⇒ `2`；`min` / `max` 夹紧（`1.2` + min=5 ⇒ 5；`99` + max=10 ⇒ 10）；空草稿失焦 ⇒ `null`（`allowEmpty` 默认 true），`allowEmpty={false}` ⇒ 回上一个有效值（不落 null、不落 0）；外部 `value` 变化同步草稿（1 ⇒ 2 时 DOM 变 `"2"`），但**用户正在输入的中间态优先**（外部 value 未变时输入 `"2."` 不被洗回 `"2"`）。证据：NumberInput.test.tsx 的 ④⑤a⑤b⑤c 与 blur 组。**红证（issue #5218 #7 订正）**：承重的守卫**只有一条** —— `NumberInput.tsx` 的 `if (editingRef.current && value === lastEmittedRef.current) return`；删掉它 ⇒ ⑤c「外部回传「空」不得吞掉正在输入的中间态」必红（单点变异实测）。⚠️ 原声明「去掉「草稿解析值等于外部值则不覆盖」这条守卫 ⇒ ④ 必红」**是假的**（独立复核两次实测：删任一条守卫 19/19 仍全绿）⇒ 那条守卫已按最少代码阶梯**删除**，声明同步订正（假红证比没有红证更坏）', '判据 4·**站点落地（改前必红的存量站点）**：① `components/products/SkuMatrix.tsx` 价格单元格（旧 `value={sku?.price || \'\'}` + `parseFloat(raw) || 0`）⇒ 输入 `0` 后 DOM 仍为 `0`、可连续打出 `0.5`（🔴 库存格已随 issue #7597（用户裁定 2026-10-24「商品中设置了库存数值，这个要移除了，要根据真实库存数据来」）从商品表单移除：商品档案不再设置库存，新 SKU 从 0 起算；库存只由真实单据产生。移除判据 = frontend/admin-web/tests/unit/components/SkuMatrixStockRemoved.test.tsx）；**缺行**（矩阵未重建）显示占位符 `0.00`/`0`，**已存在的行 `price=0`** 显示 `0`（「0 = 未填写」由校验表达，输入框不再替商家藏起来，issue #5218 #1 的可见面变化如实登记）；`onChange` 载荷形状（`{colors,doorWidths,skus}` 且带 colorId/colorName/doorWidth 定位）与 #2908 的 `border-red-400` + `aria-invalid` 标红行为**不变**。证据：frontend/admin-web/tests/unit/components/SkuMatrixNumbers.test.tsx（**红证**：改前实测 `AssertionError: expected \'\' to be \'0\'`，三条全红）③ **编辑既有值方向**（issue #5218 判据 1/2，同一文件单开一组）：价格已是 `12.5` ⇒ 全选输入 `0` ⇒ DOM 仍为 `"0"`；既有值 ⇒ 逐键 `0 → . → 5` 打出 `0.5`（库存格已随 issue #7597 移除 ⇒ 原「库存已是 30 ⇒ 输入 0」那条随格一起退场，不是放宽）。**红证（单点变异实测）**：把接线改回 `value={sku?.price ? sku.price : null}` ⇒ 这 3 条必红（0 是 falsy ⇒ 外部值变 null ⇒ 草稿被洗成 `\'\'`）② `app/(dashboard)/production/routings/page.tsx` 算料配置三处（标量参数 / 档位 fullness / 拼次数，旧 `value={String(v ?? \'\')}` + 清空落 `NaN` 哨兵 ⇒ 输入框渲染出**字面量 `NaN`** 且清不掉）⇒ 清空即空框、`0.5` 可逐键录入、面板内任何输入框都不以 `NaN` 为值。证据：frontend/admin-web/tests/unit/pages/production-routings.test.tsx「清空算料参数 ⇒ 空框（不许变成字面量 `NaN`），且 0.x 小数能正常录入」（**红证**：还原旧代码后该条实测红 —— `toHaveValue(\'0.5\')` 收到空值；`NaN` 兜底断言同因）', '判据 5·**同一病灶在 bmini 侧**（2026-10-14 更新：原承载页已删 ⇒ 实例改为商家面 FormCard）：原承载页 `frontend/bmini-app/src/pages/production/index/index.tsx`（报工数量输入框 `digit`，**已于 2026-10-14 随 issue #6868 实现包 D1 整页删除**）（微信小程序 `number` 键盘**没有小数点键**，而报工数量按米常有小数如 60.5 ⇒ 改前小数点根本打不出来）；数量仍走既有「默认 = 应做数量 / 上限 = 应做数量」校验，请求体字段与幂等键一字未变。证据：frontend/bmini-app/tests/form-card.test.tsx「数字字段（数量(米)）键盘用 digit」（原实例随报工页退场后，商家面 FormCard 是同一判据的现役承载体）（**红证**：还原旧代码后实测 `Expected: "digit" / Received: "number"`）。② **同一机制的第二处（2026-09-29 补漏）**：`frontend/mini-app/src/components/cards/FormCard.tsx` 与 `frontend/bmini-app/src/components/cards/FormCard.tsx` 的数字字段键盘 = `digit`（改前是 `const inputType = isNumber ? \'number\' : \'text\'` ⇒ 黄金策在小程序里收集的尺寸 / 数量 / 金额**在真机上打不出小数点**，用户 2026-09-29 报障「商家后台输入框无法输入小数点」；字段面 = `NUMBER_KEYS` = quantity / price / amount / stock / width / height / meter / …，手机号字段不受影响）；本地校验（必填 / 手机号 / 数字 > 0）与 `__FORM__|json` 序列化一字未改。证据：`frontend/mini-app/tests/form-card.test.tsx` 与 `frontend/bmini-app/tests/form-card.test.tsx` 的「数字字段（数量(米)）键盘用 digit ⇒ 小数点打得出来，且 0.5 原样进值 / 原样提交」（**红证**：改前实测 `Expected: digit / Received: number`）；**类级判据** = `frontend/mini-app/tests/numeric-input-keyboard-guard.test.ts`（全仓扫 Taro `Input` 上 `type=number`，豁免**纯数字字段**：字段名 phone / mobile / tel / pin / captcha 或中文标签 验证码 / 手机号 / 短信 / 密码 / PIN / 工号 / 账号；红证样本 ①~③ + 真仓零命中 ⑥；**判别力实测**：修复前的直写形态被扫出、修复后零命中）。**已知不覆盖（钉成可执行断言 ④⑤）**：`type={x}` 间接形态（本仓 FormCard 恰是这种 ⇒ 由实例判据承担）/ `Textarea` 与原生 input / admin-web 桌面侧（浏览器 `type=number` 不挡小数点键，挡的是中间态，另有判据 1/6）', '判据 6·**防新形态复发（静态扫描；判据是「语义」而非某一种写法）**：命中 = **表达式在 `x` 为假值时会产出一个「空」值**（`0` 被当空 = 病根本体）—— 这正是 #5198 漏网的形态（它只机械扫了 `value={x || \'\'}` **一种写法**）。两种**等价**形态都纳入判定：① **三元** `x ? x : <空>` —— 条件与真分支**规范化后同一表达式**（`?.` 与 `.` 视为同一形态），且假分支是空值；② **短路或** `x || <空>`（≡ `x ? x : <空>`）；`<空>` = `null` / `undefined` / `\'\'` / `""`。**两个分支都纳入判定**：真分支必须与条件同一表达式（`x ? x : …` 才是「拿 x 自己当 x 的真值判据」），假分支必须是空值。**分档作用域（#5228 实测数据逼出来的，不是随手选的）**：三元形态在**全仓** `src/**`（admin-web / mini-app / bmini-app，剥掉注释后）判红 —— 实测 `x ? x : null` / `: undefined` / `: \'\'` 三种写法**各 0 处** ⇒ 全仓扫描零假红，沿用既有严格度；短路或形态**只在「数值输入接线」面**判红（`value=` / `defaultValue=` 落在带数值标记的控件上：`type="number"` / `inputMode="decimal"` / `step=` / `min=` / `NumberInput`）—— **分档理由是实测的**：裸 `||` 兜底全仓 **223 处**（`|| \'\'` 166 / `|| undefined` 45 / `|| null` 12），几乎全是**合法**的字符串 / nullable 兜底（`data.content || \'\'`、`res.data.session || null`）⇒ 全仓判红就是**假红机器**（假红 = 假证据，比漏报更坏：它会逼后人去改合法代码）。**已知不覆盖（判据边界，与判据本体一起登记）**：以下三条**都不是留白** —— 实现侧已把它们各自钉成**可执行断言** ⑨（防后人把「没扫到」读成「没违规」）：① 非「数值输入接线」面的裸 `||` 兜底**有意不判红**（= 上面那 223 处合法兜底，这是判据的**边界**不是漏）；② 经中间变量 / 解构 / `{...props}` 展开传递的**间接接线**（静态文本扫描**不追数据流**）；③ issue #5228 表里字面写的「跨行 `x &&` 接 `x : null`」**不是合法 JS**（`&&` 后不能直接接 `:`）⇒ 无法作判据样本；其可判的等价形态（跨行的 `?:`）**已覆盖且有红证**。扫描器自身可红：四个变体（`x ? x : null` / `x ? x : undefined` / `x ? x : \'\'` / 数值接线上的 `x || null`）**各一条红证样本**必须被扫出、`typeof m === \'string\' && m ? m : null`（字符串守卫）与注释里的旧形态不判红、全仓真扫零命中。证据：frontend/admin-web/tests/unit/components/NumberInputWiring.test.ts（**红证**：把 `findFalsyWiring` 换成 `() => []` ⇒ ①~⑤ 必红）', '判据 7·**下单页工艺字段同一病灶**（issue #5218 #2/#3）：① 花距（占位符写着「米，如 0.6」）逐键 `0 → . → 6` ⇒ DOM 依次 `"0"` / `"0."` / `"0.6"`，且 `0` 是合法值（旧 `numberOrNull` 的 `parsed > 0 ? parsed : null` 把它判成空 ⇒ 框当场清空）；② 配布边米数输入 `0` ⇒ **不落 0**（`null` = 跟随主布，算料口径不变）但**显式告知**（`craft-edge-meters-zero-rejected`：按主布米数 N 米计算 + 留空即跟随主布），不再无声跳回；③ 配布边单价 `0` 不落库但框里保留输入。证据：frontend/admin-web/tests/unit/components/OrderCraftFields.test.tsx 的「判据 3」「判据 4」与配布边单价一条（**红证（单点变异实测）**：花距改回 `type="number"` + `> 0` 强转 ⇒ 判据 3 必红；删掉显式告知块 ⇒ 判据 4 必红）', '判据 8·**其余三处漏网站点迁移**（issue #5218 #4/#5/#6）：① `components/products/ProductForm.tsx`「1 卷 = 多少米」与 ② `components/settings/OversizeThresholdPreview.tsx` 四个框（试算窗宽/高、超宽/超高阈值）迁 `NumberInput` ⇒ 逐键 `0 → . → 5` / `3 → . → 5` 时 DOM 保留中间态；③ `app/(dashboard)/production/routings/page.tsx` 规则单价行内编辑改用**逐字保留原文**的 `type=text + inputMode=decimal`（等效实现，issue 明确允许）—— 该格的本地预检要**拒绝**三位小数，而 `NumberInput` 失焦按 `decimals` 归一化会把 `6.005` 静默改成 `6.01`（实测：换成 NumberInput 后「三位小数 ⇒ 不发请求」那条既有判据直接红）。证据：ProductForm.test.tsx 与 OversizeThresholdPreview.test.tsx 的「逐键」两条 + production-routings.test.tsx「规则区单价：逐键 `0 → . → 5` 打出 0.5，三位小数中间态不丢」（**红证（单点变异实测）**：三格分别改回 `type=number` ⇒ 各自对应条必红）', '判据 9·**发现 #9 的复核结论（不降级）**：独立复核称 `orders-new-plan.test.tsx` 的 `meters-manual-stale` 在删掉算料 effect 的 `continue` 守卫后**仍绿** —— 本包实测**不成立**：删掉 `orders/new/page.tsx` 的 `if (line.metersSource !== METERS_SOURCE_FORMULA) continue` ⇒ 该条**红**（`Tests 1 failed | 23 passed`，失败者即该条），同批「自动态下改宽 ⇒ 用料自动跟着变」保持绿 ⇒ 原「（红证）」标注属实。实测留痕已写进测试文件内注释，下次复核不必重跑。证据：tests/unit/pages/orders-new-plan.test.tsx 的「根因 2（红证）：人工指定后改宽/高…」'],
    skip_reason='[backend-contract] 纯前端输入控件 + 既有端点透传（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/NumberInput.test.tsx、tests/unit/components/SkuMatrixNumbers.test.tsx、tests/unit/pages/production-routings.test.tsx、frontend/bmini-app/tests/form-card.test.tsx 执行',
    tags=['ui', 'number-input', 'decimal', 'admin-web', 'bmini'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端控件用例：前置（受控夹具的 value/onChange、SKU 矩阵的 colors×doorWidths 组合、算料配置 GET 的引擎默认值、工人端工序夹具）全部由单测自建或打桩（`mockGetCraftCalcConfig` 等），不依赖共享夹具与真实服务 ⇒ 前置不成立时单测直接红；agent-eval 栈不跑它',
)

# ── UI-056 [NORMAL] 入库单页按钮几何完整性 — 按钮标签不换行（`whitespace-nowrap` 进 Button 基类）+ 类级元守卫（issue #5558；同族 UI-041）（源: cases/ui.yml）──
_CASE_UI_056 = EvalCase(
    id='UI-056',
    legacy_id='',
    title='入库单页按钮几何完整性 — 按钮标签不换行（`whitespace-nowrap` 进 Button 基类）+ 类级元守卫（issue #5558；同族 UI-041）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['仓储与物料 → 入库单：页头与筛选行的按钮文字被压成竖排（期初建账导入 / 新建入库单 / 查询 / 重置）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**效果层几何（Playwright boundingBox + 内容溢出）**：1100×800 与 1280×800 两视口下，四个按钮的 `scrollHeight − clientHeight ≤ 1`（标签没换行）且宽度 ≥ 自然宽度下限（期初建账导入 130 / 新建入库单 118 / 查询 78 / 重置 76）。**修复前实测**：期初建账导入溢出 **13px**（1100 视口）/ 3px（1280）、查询溢出 3px，宽度被压到 101 / 90 / 70 / 68（自然宽度 140 / 124 / 84 / 82）⇒ 标签在固定 `h-9` 盒子里换行。**红证** = 去掉基类 `whitespace-nowrap` ⇒ 该 spec 当场红（含 Playwright 失败截图）。仅「元素存在/不存在」不算覆盖（`frontend-fix.layout`）。', '🔴 判据·**类级元守卫**（每次 PR 就拦，不等 nightly E2E）：`frontend/admin-web/tests/unit/ui-primitive-nowrap-guard.test.ts` 扫 `src/components/ui/**`，凡是 `inline-flex` 基类的原语都必须带 `whitespace-nowrap`；发现规则是机械的（不是人工台账），新原语漏了即红，并带非空跑自证（普查面为空 / 已知原语改名 ⇒ 先红）。**红证** = 去掉 Button 的那一条 ⇒ 元守卫指名 `Button.tsx` 变红。', '**类级口径（为什么不是只钉这一页）**：`Badge` / `StatusBadge` 早就有 `whitespace-nowrap`，只有 `Button` 漏了 —— 它是三个 `inline-flex` 原语里的异类；同族先例 UI-041（设置页开关缺 `shrink-0` ⇒ 轨道被压扁、圆钮溢出）说明「flex 行里的原语缺几何保护」是一**类**。本单只改共享基类，**不动任何页面结构**。', '**不回归**：无 API/契约变更（`frontend-fix.no-api-change`）；页面列表渲染/建单/过账等既有前端判据（PR-037）逐条不变。'],
    skip_reason='[backend-contract] 纯前端布局几何由 Playwright E2E（tests/e2e/specs/warehouse/inbound-orders-button-geometry.spec.ts）+ admin-web vitest 覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'layout', 'button', 'geometry'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-057 [NORMAL] 省料看板文案去内部代号（L2/L3 → 说人话）+ 类级元守卫：内部代号不得进用户可见文案（issue #5565）（源: cases/ui.yml）──
_CASE_UI_057 = EvalCase(
    id='UI-057',
    legacy_id='',
    title='省料看板文案去内部代号（L2/L3 → 说人话）+ 类级元守卫：内部代号不得进用户可见文案（issue #5565）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['生产管理 → 省料看板：页头与两个区块标题写着 L2 / L3（用户逐字「L2和L3是什么概念，用户不懂，我也不懂」）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**渲染文本零代号**：省料看板整页渲染文本里不出现 `L1/L2/L3`（严格 `/L[123]/`）。修复前实测：页头副标题「批次余量分档（L2）＋ 单位产出的面料消耗（L3）」+ 区块标题「L2 批次余量分档…」「L3 单位产出的面料消耗…」三处命中。断言口径 = **整页 textContent**（本页「批次余量分档」在副标题与区块标题各出现一次，`findByText` 会因多命中重试到 5s 超时 —— 已记在测试文件注释里）。', '判据·**说人话且不丢口径**：🔴 **2026-10-07 改判（issue #6459）** —— 旧写的「副标题渲染出『每批布用剩多少』『每平方米成品用掉多少米布』」**已作废**（那两个概念连同「单位产出的面料消耗」表一起被用户裁定删除）；现口径 = 页头**一句规则**（`saving-rule`：「省下的布 = 按公式该领的米数 − 排料实际领走的米数；省下的钱 = 省下的布 × 那批布当时的进价」）+ 区块标题点明「这个数是什么」（`几乎用完的布` / `省料明细` / `口径与边界`）。**判据一条不减**：整页仍零内部代号，且**新增**零服务端分组标签（`user-copy-jargon-guard` 形态③）。', '🔴 判据·**类级元守卫**：`src/app` / `src/components` / `src/lib` 三处扫「用户可见形态」的内部代号 —— `（L2）`（括号包裹）与 `L2 中文`（标题式）；注释行与 SVG `d="…"` 不算（它们不上屏，实测 `orders/page.tsx` 图标路径含 `L3` 会假红）。未登记即红，豁免台账为空。修复前实测具名三行（saving-board/page.tsx 的副标题与两个 h2）。', '**不回归**：口径/接口/数值一律未动（`frontend-fix.no-api-change`）；省料看板既有纯函数判据（PR-095：空数据不冒充 0、档位文案来自服务端）逐条不变。'],
    skip_reason='[backend-contract] 纯前端文案 + 静态守卫，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'copy', 'saving-board', 'jargon'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-058 [NORMAL] 菜单改名「池看板」→「智能派单」+ 页内去内部隐喻（池化开关/进池/池内/成批区/加急插队）+ 三源同构 + 「只改文案」负控（issue #5576）（源: cases/ui.yml）──
_CASE_UI_058 = EvalCase(
    id='UI-058',
    legacy_id='',
    title='菜单改名「池看板」→「智能派单」+ 页内去内部隐喻（池化开关/进池/池内/成批区/加急插队）+ 三源同构 + 「只改文案」负控（issue #5576）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家看不懂「池看板」这个名字（用户逐字：「池看板 这个命名用户不太懂，能否改成通俗易懂，并且尽量贴合行业叫法」）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**三源同构**：`config/menu.ts` 的 `production-pool` 节点、`MenuController.MENU_TREE` 的 `new MenuNode("processing:manage", "智能派单")`、`AuthService.buildMenusByPermissions` 的 `menuItem("production-pool", "智能派单", "/production/pool")`、`Header.tsx` 面包屑 —— 四处逐字一致（任一处漏改就会出现「侧边栏看到的名字」与「后端下发的名字」不一致，`#4203` 同族坑）。', '🔴 判据·**页面零隐喻 + 人话读数**：整页渲染文本不出现 `/池/`，也不出现旧词（成批区 / 加急插队 / 一键成批派单 / 池化开关 / **合并派单开关**）；同时**必须有**替换后的人话（待派订单 / 加急订单（不参与合并，立即派）/ 可合并的待派订单（按料分组）/ 一键合并派单）—— 「删掉就算过」不算通过。🔴 #6588 追加：原「合并派单开关 已开启/未开启」徽标**必须不存在**（`data-testid="pool-status-pooling"` 取不到）—— 它是**只读**的服务端缺省值（字段 `poolingEnabled`），不可点、没有出口、恒为「未开启」，实测引来用户逐字提问「在哪开启？」；合并是页面上的**动作**（勾选 → 一键合并派单），不是要商家拨的开关。', '🔴 判据·**只改文案（负控）**：路由 `/production/pool`、菜单 key `production-pool`、权限码 `processing:manage`、三个接口路径（含 `pooled` / `poolingEnabled` 字段）逐字未动（先例 = UI-028「角色权限」→「岗位权限」时 URL 与接口不变）。', '🔴 类级元守卫：`user-copy-jargon-guard.test.ts` 新增「机制隐喻」形态 —— `src/app` / `src/components` / `src/lib` 的**用户可见**行里出现 CJK「池」即红（注释与 SVG path 不算；ASCII 的 `pool` / `pooled` / `poolingEnabled` 是契约与实现，不在射程）。修复前实测具名 2 行预览标签（`src/lib/pool-board.ts` 的 `previewSummaryRows`（第一行「合并后预计领料米数」与第五行「合并新增收益」两处标签））。🔴 #6588 追加**第二形态**：**只读状态不得做成「开关」徽标** —— 状态副词（已开启 / 未开启 / 已关闭 / 已启用 / 已停用）不得单独作为 `Badge` 的子节点（`src/app` / `src/components` 源码扫描；判别力自证：坏的孤立状态徽标判红、动作结果徽标「已派单」与真实 toggle 不红；`aria-label` 里的「开关」是真实控件的可访问名，不在射程）。', '**命名裁定留档**：菜单名曾考虑「智能下料」（用户先提），因本仓「下料」已被裁定为**车间裁剪工序**（工序库「裁剪组」；黄金策触发词「这单下料做到哪了」走 `production_worklog_query`）会撞名 ⇒ 用户改选「智能派单」；「智能」保留用户本意（系统按料分组、算好合并省多少），动作落回商家的词「派单」。'],
    skip_reason='[backend-contract] 纯前端文案/菜单名 + 静态守卫（无 LLM 行为面），不进入 agent-eval 冒烟',
    tags=['ui', 'copy', 'naming', 'pool-board'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-059 [NORMAL] 左侧菜单图标两两不同 —— 4 组同图各自换唯一图标 + 数据层/渲染面双判据（issue #5582）（源: cases/ui.yml）──
_CASE_UI_059 = EvalCase(
    id='UI-059',
    legacy_id='',
    title='左侧菜单图标两两不同 —— 4 组同图各自换唯一图标 + 数据层/渲染面双判据（issue #5582）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户逐字：「左侧菜单栏有部分子菜单的图标完全一样，能否做到每个菜单不同图标」'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**数据层两两不同**（`menu-icons.test.ts` 判据④）：28 个节点（7 组头 + 20 组内项 + 1 独立项）的图标名去重后数量 == 节点数；面非空自证（节点数 == 28 且点名 8 个已知节点）。修复前实测 4 组同图：`BarChart3` 经营看板/省料看板、`ShieldCheck` 售后工单/岗位权限、`Calculator` 财务对账/计件工资、`Building2` 组织管理/企业基础信息。', '🔴 判据·**渲染面两两不同**（`Sidebar.test.tsx`）：展开全部组后，22 项（21 组内项 + 通知中心）的**渲染结果**里图标互不重复（从 tests/setup.ts 的 lucide 夹具 `data-testid="icon-<kebab>"` 反读，不是读配置）—— §15.1「结果可见」。⚠️ 本判据需先 `mockBriefingEnabled = true` + `waitFor` 等「每日简报」到位（它是异步拉配置决定可见性的，实测踩过一次）。', '🔴 红证（单点变异）：把「省料看板」的图标改回 `BarChart3` ⇒ **数据层与渲染面两条判据同时具名变红**（`BarChart3 → 经营看板、省料看板`），还原 sha256 逐字节一致。', '**三处同批**（漏一处即红/即抛）：`config/menu.ts` 的 icon 名 + `config/menu-icons.ts` 的 import 与 `menuIconMap` + `tests/setup.ts` 的 lucide 白名单（未登记的新图标会让任何渲染 Sidebar 的用例当场抛 `No "X" export is defined on the "lucide-react" mock`）。既有三条注册表判据（正向不漏 / 反向无死映射 / 注入式红证）逐条不回归。', '**只换图标**：路由 / 菜单 key / 权限码 / 菜单名一律未动（`frontend-fix.no-api-change`）；图标仍是**前端专属**（MC-019 裁决：服务端不下发 icon）。'],
    skip_reason='[backend-contract] 纯前端菜单图标 + 静态/渲染判据（无 LLM 行为面），不进入 agent-eval 冒烟',
    tags=['ui', 'menu', 'icon', 'layout'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-060 [NORMAL] 官网首页未登录不跳登录页 —— 根路径进公开路由白名单（`isPublicRoute('/')` = true / `shouldRedirectToLogin('/')` = false），受保护业务页跳转一条不放宽（issue #4903 的行为修复补录用例，关联 #4906）（源: cases/ui.yml）──
_CASE_UI_060 = EvalCase(
    id='UI-060',
    legacy_id='',
    title="官网首页未登录不跳登录页 —— 根路径进公开路由白名单（`isPublicRoute('/')` = true / `shouldRedirectToLogin('/')` = false），受保护业务页跳转一条不放宽（issue #4903 的行为修复补录用例，关联 #4906）",
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['未登录直接打开 migaozn.com 官网首页（根路径 /）：首页必须正常常开，不得被强制跳转到登录页'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**根路径是公开路由**：`isPublicRoute('/')` === true；带 query/hash 的落地页同样 true（`isPublicRoute('/?utm_source=wechat')` === true、`isPublicRoute('/#hero')` === true）。执行点 = frontend/admin-web/tests/unit/lib/auth-redirect.test.ts 的「官网首页（根路径）是公开路由 —— migaozn.com 首页不得把未登录访客挡在门外（issue #4903）」（逐条 `expect(...).toBe(true)`）。", "判据 2·**根路径 401 不跳登录页**：`shouldRedirectToLogin('/')` === false —— AuthProvider 不再对首页执行会话恢复、axios 拦截器不再强制 `window.location.href='/login'`（生产实测形态：首页先渲染再被跳走）。执行点 = 同文件的「官网首页 401 不跳转 —— 只有用户主动点「商家登录」才去登录页（issue #4903）」（`expect(shouldRedirectToLogin('/')).toBe(false)`）。", "判据 3·**受保护业务页跳转一条不放宽**（反向护栏 —— 防「放宽首页」被顺手扩大成放宽业务面）：`shouldRedirectToLogin` 对 '/dashboard' / '/orders' / '/customers' 全 === true，且 `isPublicRoute` 对 '/dashboard' / '/orders' / '/products' / '/employees' / '/agent-workspace' 全 === false。执行点 = 「受保护业务页非公开路由」+「在受保护页面 401 时应跳转登录」+「不含任何受保护业务页（放宽首页不得连带放宽业务面）」。", "判据 4·**公开面单一源**：`PUBLIC_ROUTES` 排序后逐字等于 ['/', '/about', '/contact', '/login', '/register', '/services']（六项；根路径必须在内、受保护业务页不得混入）。执行点 = 「恰好是「首页 + 认证页 + 官网公开页」六项」+「公开路由的子路径也算公开（兼容 query 前缀）」。", "🔴 红证（单点变异实测 2026-09-26，node 直跑真源码 + 变异副本，非纸面推断）：把 `PUBLIC_ROUTES` 里的 '/' 删掉 ⇒ 7 条探针 **4 条判红**（`isPublicRoute('/')`、`isPublicRoute('/?utm_source=wechat')`、`shouldRedirectToLogin('/')`、`PUBLIC_ROUTES` 六项断言），判据 1/2/4 三条**同时失效**；还原后 7/7 绿。⚠️ 判据 3 在该变异下**仍绿** —— 它是反向护栏（本缺陷的红证不在它身上），如实登记以免被读成它的红证。"],
    skip_reason='[backend-contract] 纯前端路由守卫（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/lib/auth-redirect.test.ts 执行',
    tags=['ui', 'auth', 'redirect', 'public-route', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-061 [NORMAL] A4 加工单打印：表头九栏（订单日期/客户/电话/地址/备注/制单人/单号/交付日期/货运）；按套分块，每块 6 列 货号|颜色|门幅|数量|批号|备注（🔴 纸面不印工序清单；纸面标题按作业单两型「加工单 / 面料单」；🔴 两型同版式 —— 品名/帘种/尺寸三列与工艺行都不上纸，issue #7901 → #7909；左上角印扫码报工码）；@page A4 + 分页不裁切 + 表头重复（issue #5651 / #6901 / #7274 / #7891 / #7901 / #7909）（源: cases/ui.yml）──
_CASE_UI_061 = EvalCase(
    id='UI-061',
    legacy_id='',
    title='A4 加工单打印：表头九栏（订单日期/客户/电话/地址/备注/制单人/单号/交付日期/货运）；按套分块，每块 6 列 货号|颜色|门幅|数量|批号|备注（🔴 纸面不印工序清单；纸面标题按作业单两型「加工单 / 面料单」；🔴 两型同版式 —— 品名/帘种/尺寸三列与工艺行都不上纸，issue #7901 → #7909；左上角印扫码报工码）；@page A4 + 分页不裁切 + 表头重复（issue #5651 / #6901 / #7274 / #7891 / #7901 / #7909）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户现行四张单据里的 A4 加工单（2026-09-26 用户提供实物照，去 PII 后登记在 issue #5651 的实证表 #3）；用户逐字裁定「要做，新增 A4 加工单打印」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**表头九栏逐条命中实证 #3**：订单日期 / 客户 / 电话 / 地址 / 备注 / 制单人 / 单号 / 交付日期 / 货运 九栏全部渲染，取值取服务端字段（订单日期 = order.createdAt；单号 = 加工单号、缺则回落订单号；交付日期 = 加工单交期、缺则回落订单「要求到货日」；货运 = logisticsType · logisticsCompany）。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的「① 表头九栏逐条命中实证 #3 的制式」+「① 交付日期回落链」+「① 加工单缺失 ⇒ 单号回落订单号」。', "判据 2·**按套分块**：N 个商品行 ⇒ N 块，每块段头 `第N套/共M套`，块内一张 **6 列表**，列序逐字等于 PROCESSING_DOC_COLUMNS = ['货号','颜色','门幅','数量','批号','备注']。🔴 2026-10-14 同批纠正一处**散文漂移**（非本批引入）：本条此前写的是「8 列表 = ['部位','部位信息','尺寸','组件','货号','用料','批号','备注']」，与真值（代码常量 + CI 守卫 C5 的钉住元组）**早已不符** —— 该判据执行点断言的本来就是当前版式，故不构成假绿，但散文必须与真值对齐。🔴 2026-10-27 再改判（issue #7901 面料单 → #7909 加工单）：品名 / 帘种 / 尺寸三列退场 ⇒ 9 列变 6 列，**两型同一套列**（真值同步进 CI 守卫 C5 的钉住元组）。执行点 = 同文件「② 按套分块：3 个商品行 ⇒ 3 块」+「纸面列收敛：两型同版式」。", "判据 3·**A4 版面与分页不裁切**：样式里 `@page { size: A4; margin: 0; }`（由 `lib/print-media.ts` 的 printPageRule('a4') 生成，本组件不自写纸型；🔴 issue #7309：边距 0 = 浏览器页眉页脚无处可画，版面内缩 12mm 由容器 padding + `box-decoration-break: clone` 承担）；`.processing-set { break-inside: avoid }` + `.processing-doc-table thead { display: table-header-group }`（长单跨页时表头重复）。执行点 = 同文件「③ 版面：@page A4（由介质矩阵生成）+ 分页不裁切 + 表头重复」。", '判据 4·**缺值不许静默留空**：客户名 / 电话 / 地址缺失 ⇒ 单元格为显式占位 `—`（不是空串）；本系统**未采集**的字段（制单人 / 批号）标「未采集」并出脚注 —— 二者必须可区分。执行点 = 同文件「🔴 ④ 缺字段可见」+「🔴 ④ 本系统未采集的字段必须显式标注」。', '判据 5·🔴 **左上角「作业单扫码报工」码**（issue #7891，2026-10-27 由销售单迁入；取代 #7219 的「纸面不印 QR」口径）：有 `scan_url` ⇒ 码块 `processing-doc-qr` 在纸面**左上角**（与抬头并排、文档顺序在纸面标题之前），码值逐字 = 服务端下发的 `scan_url`（qrcode.react 把 value 写进 `svg > title`），码旁只留**竖排**「扫码报工」(`writing-mode: vertical-rl`）；`short_code` 的取值不出现在纸面文本里（类级 C12）。无 `scan_url`（含 `processingOrder=null`）⇒ **三种形态都不出现**（码 / 占位框 / 可读短码行）。执行点 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的 #7891 码用例组。', '判据 6·**加工单不印金额**（实证 #3 无金额列）⇒ 天然没有第二份金额真值：纸面文本不含「本单应收 / 单价 / 金额 / 小计」。执行点 = 同文件「⑥ 加工单不印金额」。', '判据 7·🔴 **纸面不印工序清单**（issue #7274，用户 2026-10-18 逐字「工序细节不用在打印单上，移除掉工序相关的表格信息」）：加工单纸面**零**工序节点 —— 即使按旧调用方形态（issue #6901 的 `operations` prop）传入工序实例，也不得出现 `processing-doc-operations` / `processing-doc-operation`，纸面文本不含「工序 / 精裁 / 应做 / 待做」。工序信息改在**屏幕**加工单块（`frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx`）与工人扫码面呈现（读面 / 显示名口径不变）。执行点 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的「ProcessingDoc 纸面不印工序（issue #7274）」；类级判据 = `tests/unit_ci_workflows/test_print_media_matrix_guard.py::test_c8_paper_must_not_carry_the_operation_list`。红证（实跑）：把 `ProcessingDoc.tsx` **与** `ShipmentDoc.tsx` 一起换回 origin/main 版（测试留本分支版本）⇒ 组件用例 **2 failed / 49 passed**（两个文件各挂 1 条）、C8/C9 守卫 **2 failed / 7 passed', '判据 8·**数量列名按本行单位**：快照行 `unit` 有 ⇒ `数量(套)`；**没采集到单位 ⇒ 只写「数量」**（不编「米」）；列名与值**同出** `frontend/admin-web/src/lib/order-item-sku.ts::orderItemQuantity()`。红证 = 把 CI 守卫 C5 的元组改回 `数量(米)` ⇒ **1 failed / 6 passed**（实跑读数）', '判据 9·🔴 **两型同版式：6 列、无工艺行**（issue #7901 面料单 → issue #7909 加工单，用户 2026-10-27 逐字「面料单移除红框的行列」+「加工单也要移除」）：正文表**恰 6 列**（`货号 | 颜色 | 门幅 | 数量 | 批号 | 备注`），品名 / 帘种 / 尺寸**取不到节点**（不是样式藏起来），「工艺」行整行不渲染；`order_kind` 为 `processing` / `outbound` / 缺键（存量单）三种形态**列清单一致**（不随作业单类型分叉）；每行 `Σ(colSpan)` = 6（补位行 `colSpan` 随列数变，不写死）；6 列宽度 Σ = 100% 且 `批号` ≥16%。执行点 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的「纸面列收敛：两型同版式（issue #7901 / #7909）」六条 + 「🔴 帘种不上纸」+「🔴 纸面不印「工艺」行」。🔴 有意接受的信息收敛（已登记 issue #7909）：加工单纸面从此没有帘种 / 尺寸 / 工艺规格，车间看水洗唛或屏幕。', "🔴 红证（注入式，随测试文件常驻）：把 `.processing-set` 的 break-inside 与 thead 的 table-header-group 抹掉 ⇒ 判据 3 必须红（同文件「③ 分页判据可红」）；把占位换回 `value || ''` 的静默留空 ⇒ 判据 4 必须红（同文件「④ 缺字段判据可红」）；把工序块接回纸面 ⇒ 判据 7 必须红（同文件「ProcessingDoc 纸面不印工序」）。⚠️ 取不到真机读数（针打/三联纸）的部分不在本用例的判据里，如实登记在 docs/design/print-media-matrix.md 的待实测清单。", '🔴 **加工费组合行（issue #7833，用户 2026-10-26 逐字「JG-20261026-8172 这个加工单有超高倒幅，但是在加工单的各个环节都没有体现出来」）**：A4 加工单每套块内、紧跟「工艺」行之后单列一行「加工费组合」，值 = 加工单**快照**行的 `processingItems[].name` 用顿号连接（如 `韩褶、超高、倒幅、定型`；取值口 `lib/processing-combo.ts`，不另写推导）；缺该键（存量单）⇒ 整行不渲染（不印空壳行）；整行仍占满 9 列（1 + colSpan 8，Σ(colSpan) 不变量由类级判据钉住）；长值走 `DocTd` 的 `break-words` 折行印全文（不裁切）。判据 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx`。'],
    skip_reason='[backend-contract] 纯前端打印版式（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 执行',
    tags=['ui', 'order', 'print', 'processing-doc', 'a4'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-062 [NORMAL] 销售单打印（三联纸 241mm × 140mm 两等分）：@page 241mm 140mm + 只渲染一页（复写由压感纸承担）+ 明细 序号|货号|颜色|门幅|数量|单位|单价|金额（「品名」列自 issue #7530 退场）+ 金额一律取服务端字段 + 缺口金额栏不编数 + 长文本折行印全文不缩略（issue #5651 / #7715）（源: cases/ui.yml）──
_CASE_UI_062 = EvalCase(
    id='UI-062',
    legacy_id='',
    title='销售单打印（三联纸 241mm × 140mm 两等分）：@page 241mm 140mm + 只渲染一页（复写由压感纸承担）+ 明细 序号|货号|颜色|门幅|数量|单位|单价|金额（「品名」列自 issue #7530 退场）+ 金额一律取服务端字段 + 缺口金额栏不编数 + 长文本折行印全文不缩略（issue #5651 / #7715）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客户现行四张单据里的销售单（2026-09-26 用户提供实物照，去 PII 后登记在 issue #5651 的实证表 #4）；用户逐字裁定「要，而且挂在发货链上」并以「241mm × 140mm（两等分）」定连续纸规格'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**三联纸纸型**：样式里 `@page { size: 241mm 140mm; margin: 6mm 12mm; }`（由 printPageRule('continuous-241x140') 生成），容器带 data-print-media='continuous-241x140'。执行点 = frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 的「① 介质：@page 241mm × 140mm（两等分）」。", "判据 2·🔴 **只渲染一页**（复写是纸的特性，不是软件的事）：DOM 里 `.sales-sheet` **恰好一份**；容器高度 = printUsableHeightMm('continuous-241x140') = 128mm（页长 140 − 上下边距 12）且 overflow: hidden ⇒ 浏览器不会再分页（跨联 = 纸面与账目对不上）。执行点 = 同文件「① 介质」+「① 红证：改坏只渲染一页 ⇒ 必红」。", "判据 3·**介质是参数不是副本**：`media` 是 prop，切到 'a4' 后 @page 变 A4，而**逐格取值（序号/货号/颜色/门幅/数量/单位/单价/金额）、表头、金额汇总、扫码报工码值逐字不变** —— 复制一份字段映射给 A4 版本 ⇒ 必红。执行点 = 同文件「② 介质是参数不是副本：切 A4 后 @page 变、而逐格取值逐字不变」+「② 列清单 = SALES_DOC_COLUMNS」。", '判据 4·🔴 **金额一律取服务端字段**（前端现算 = 第二份真值）：构造的服务端值与前端求和**故意不同**（行 unitPrice×quantity = 30 而服务端 amount = 500；行金额之和 = 500 而 actualAmount = 888.88）⇒ 纸面必须印 500.00 / 888.88 / 999.99 / 111.11。执行点 = 同文件「🔴 ③ 金额取服务端字段」+「🔴 ③ 红证：让前端现算 ⇒ 必红」。', '判据 5·🔴 **缺口金额栏不编数**：上期余额 / 预存抵扣 / 账户余额 服务端无字段（Order DTO 与 SystemSettings 均无余额面）⇒ 纸面标「未采集」，**不含任何数字**（印 0.00 = 把「没有这个数」画成「余额为零」）。执行点 = 同文件「🔴 ④ 缺口金额栏标未采集且不含数字」+「🔴 ④ 红证：编成 0.00 ⇒ 必红」。', '判据 6·**缺值可见 / 长名完整可见**：客户 / 电话 / 地址缺失 ⇒ 显式占位 `—`（不是空串）；长客户名 / 长色名**折行印全文** —— 全文在 DOM、不做字符串截断、也**不上省略号**（issue #7715：用户 2026-10-25 逐字「这里打印预览的文字要打印全，不能缩略」）。执行点 = 同文件「🔴 ⑤ 缺值可见」+「⑤ 长名完整可见」+「⑤ 颜色列折行印全」+两条对应的红证用例；类级守卫 = tests/unit_ci_workflows/test_print_paper_full_text_guard.py（四张纸面单据同尺判定：省略号 / `truncate` / `line-clamp` 一律红）。', '判据 7·🔴 **纸面不印收款码**（issue #7589）：销售单页脚只留温馨提示 —— 纸面 `img` 数 = 0、无 `sales-qr-*` 节点、正文不含「微信 / 支付宝」，且组件**不再订阅**收款码读取口（`usePaymentQrcodes` 零调用 ⇒ 打印销售单不多发一次 `payment-qrcodes` 请求）。执行点 = frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 的「⑥ 销售单纸面**不印收款码**」+「⑥ 销售单**不读**收款码」；类级守卫 = tests/unit_ci_workflows/test_print_doc_convention_guard.py 的 C6（收款码只属于报价单）。', '🔴 红证（注入式，随测试文件常驻）：渲三份 .sales-sheet ⇒ 判据 2 红；前端现算行金额/汇总 ⇒ 判据 4 红；缺口栏印 0.00 ⇒ 判据 5 红；长名 slice(0,8) 或把省略号裁切写回来 ⇒ 判据 6 红。⚠️ **未完成项如实登记**：销售单「挂发货链」（数量与实发同源）的真值载体 order_shipment_items（issue #5648 / PR #5664）**已合入 main**，但它今天**只有工人读面**（GET /api/worker/shipment/orders/{id}，工人 session 准入），**admin 端没有读面** ⇒ 跑在 admin-web 的销售单拿不到实发数量，接线需新增 admin 端读面（后端改动）。⇒ 本版数量取订单行 order.items[].quantity（与报价单/发货单**同一份**投影，**不**自造发货明细表、不照工人读面猜 DTO），消费入口由该表 owner 指定 = OrderShipmentService.readShipment。', '🔴 **「打印全」的射程扩到洗水唛（issue #7833）**：类级守卫 C4 —— 洗水唛三份源码同尺判定（CSS 渲染器未去注释的代码面不得出现省略号 / `truncate` / `line-clamp-*`；纸面内容模块不得带行数预算 `maxLines`；位图渲染器不得按 `row.maxLines` 裁），并附注入式红证与「注释里提及不算」负控；CSS 渲染器必须声明折行（`break-words` / `break-all`）。判据 = `tests/unit_ci_workflows/test_print_paper_full_text_guard.py::test_c4_wash_label_prints_full_text` / `::test_c4_injection_turns_red`。'],
    skip_reason='[backend-contract] 纯前端打印版式与金额取值（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 执行',
    tags=['ui', 'order', 'print', 'sales-doc', 'continuous-paper', 'dot-matrix'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-063 [NORMAL] 打印介质矩阵分层：A4 / 标签 50×60 / 三联纸 241×140 三介质显式在册；可打印单据必须声明介质（未声明即红）+ @page 与矩阵同源 + 三联纸待实测登记 + 同一单据只许一份字段映射（issue #5651）（源: cases/ui.yml）──
_CASE_UI_063 = EvalCase(
    id='UI-063',
    legacy_id='',
    title='打印介质矩阵分层：A4 / 标签 50×60 / 三联纸 241×140 三介质显式在册；可打印单据必须声明介质（未声明即红）+ @page 与矩阵同源 + 三联纸待实测登记 + 同一单据只许一份字段映射（issue #5651）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-26 裁定销售单介质（三联纸 241mm × 140mm 两等分）；issue #5651 要求把「打印介质矩阵」显式建立为后续所有单据打印的分层依据（新单据先回答「介质是哪一种」）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**三介质在册且技术口径正确**：介质矩阵（frontend/admin-web/src/lib/print-media.json）登记 a4（激光/喷墨，size A4，不复写）/ label-50x60（热敏，size 50mm 60mm，几何为 #5646 实测）/ continuous-241x140（针式点阵 + 连续纸 + 压感复写，size 241mm 140mm，carbonCopies=3）；TS 侧 id 字面量清单与 JSON 的 id 集逐字一致。执行点 = frontend/admin-web/tests/unit/lib/print-media.test.ts 的「① id 字面量清单与 JSON 的 id 集逐字一致」+「② 三种介质都在册」。', '判据 2·**介质是参数不是副本**：每张单据的列清单在 src 下**恰好命中一个文件**；把销售单的列清单复制一份（模拟「再写一个 A4 版」）⇒ 判据必红。执行点 = tests/unit_ci_workflows/test_print_media_matrix_guard.py 的 test_c5_each_doc_has_exactly_one_field_projection + test_c6_injected_regressions_are_red 的注入 D。', '判据 3·**可打印单据必须声明介质（未声明即红）**：扫描 src 下所有门户式单据（createPortal + -print-area），逐个必须在 PRINT_DOCS 登记介质；新增一个不登记的打印组件 ⇒ 必红。执行点 = 同文件 test_c3_new_portaled_print_docs_must_declare_a_media（含反空跑下界：扫描面 ≥4 份单据）。', "判据 4·**@page 与矩阵同源**：受管单据的 @page 要么由 printPageRule('<介质>') 生成、要么自写字面量与矩阵逐字一致；把矩阵里的 A4 纸型改成 A3、或让单据不再声明纸型 ⇒ 该单据判红。执行点 = 同文件 test_c2_every_print_doc_page_rule_matches_the_media_matrix + test_c6 的注入 A/B。", '判据 5·🚧 **三联纸真机参数显式登记为待实测**（不是编造的精确值）：continuous-241x140 的 measurement = pending-field-measurement 且 pendingMeasurements ≥3 条（走纸长度 / 边距 / 行高 / 最小字号）；删掉登记 ⇒ 必红。执行点 = 同文件 test_c4_pending_field_measurements_must_be_registered + test_c6 的注入 C，以及 frontend/admin-web/tests/unit/lib/print-media.test.ts 的「🔴 ③ 三联纸的待实测登记必须存在」。', '判据 6·**三种介质互不串页**（#4983 既有约定扩展到新增的两份单据）：新增的 ProcessingDoc / SalesDoc 与既有三份一样带共享标记类 print-doc、隔离选择器恰好 `body > *:not(.print-doc)`、visibility 防御限定自己的 data-print-target。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 与 SalesDoc.test.tsx 的「⑦ 打印隔离」用例 + tests/unit_ci_workflows/test_print_doc_convention_guard.py（受管清单已含新增两份，C1/C2 判红）。', '🔴 红证（注入式实跑，随守卫常驻）：test_c6_injected_regressions_are_red 逐条做「注入 → 断言必红」，并用 **sha256 内容指纹**自证注入生效（禁 mtime/size）—— 注入 A 改纸型、B 删纸型声明、C 删待实测登记、D 复制一份字段映射，任一不红即判「守卫是空判据」。'],
    skip_reason='[backend-contract] 纯前端打印介质分层 + 源码级元守卫（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/lib/print-media.test.ts 与 tests/unit_ci_workflows/test_print_media_matrix_guard.py 执行',
    tags=['ui', 'print', 'media-matrix', 'guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-027 [NORMAL] 打印链路「一次只放一份单据上纸」：window.print() 收敛到唯一入口且在目标提交后调用（首次打印不再是空白纸）+ @page 只在本次目标时发表（纸型不被兄弟单据顶掉）+ 打印前纸面自检预览 + 截图复制（issue #5914）（源: cases/ui.yml）──
_CASE_UI_027 = EvalCase(
    id='UI-027',
    legacy_id='',
    title='打印链路「一次只放一份单据上纸」：window.print() 收敛到唯一入口且在目标提交后调用（首次打印不再是空白纸）+ @page 只在本次目标时发表（纸型不被兄弟单据顶掉）+ 打印前纸面自检预览 + 截图复制（issue #5914）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-01 逐字：「打印功能是否应该先预览然后再打印，你觉得是否有必要，不过截图有必要，点击截图后把单据模板信息直接截图下来并复制」；同轮裁定范围 = 修 P1（首次打印空白 / 四单纸型互串）+ 预览 + 截图复制一起做，加工单「制单人 / 批号」按印真值修'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **print 被调用时目标已在 DOM**（旧写法同 tick `setState` + `window.print()` ⇒ 首次打印空白纸）：真实浏览器在 `beforeprint` 抓 `[data-print-target]`，点「打印销售单」后必须恰好是 `sales`（旧实现实测 = NONE）。执行点 = tests/e2e/specs/orders/print-preview.spec.ts 的「① 点『打印』时目标已置位」+ frontend/admin-web/tests/unit/lib/print-doc.test.tsx 的「① print 被调用时目标已在 DOM」。', '判据 2·**唯一入口**：`window.print()` 在 `frontend/admin-web/src/**` 里**恰好**出现在 lib/print-doc.ts（第二处裸调用 ⇒ 必红）。执行点 = tests/unit_ci_workflows/test_print_single_doc_on_paper.py 的 test_c1_window_print_has_exactly_one_entry（红证 = test_c5 的注入 A）。', '判据 3·🔴 **同页四份单据只放一份上纸**：文档里 `@page` 规则**恰好一条**且等于本次目标那张纸（销售单 ⇒ 241mm 140mm）；非目标单据在打印媒体下 `display: none`（不占版面 ⇒ 不出空白页）。执行点 = tests/e2e/specs/orders/print-preview.spec.ts 的「② 同页四份单据只放一份上纸」+ tests/unit_ci_workflows/test_print_single_doc_on_paper.py 的 test_c2_c3（红证 = 注入 B/B2）。', '判据 4·**纸面自检可见**（销售单单联 128mm）：明细 8 行（实测内容 ≈136.5mm）⇒ 预览必须报「超出」并给可行动出口；5 行 ⇒ 报「装得下」（判据不是恒报警）。执行点 = 同 spec 的「③ 纸面自检：装得下 / 装不下」+ frontend/admin-web/tests/unit/components/PrintDocPreview.test.tsx 的 measureSheets 三条几何用例。', '判据 5·🔴 **截图复制产出真尺寸 PNG**：点「复制截图」⇒ 剪贴板拿到 image/png，尺寸 ≈ 纸型 × 3 倍（241mm ≈ 911px ⇒ ≈2733px，宽高比 1.72±0.15）；剪贴板不可用 ⇒ 下载 PNG + 明示提示（不许静默失败）。执行点 = 同 spec 的「④ 复制截图」（真实 Chrome + clipboard 权限 + createImageBitmap 读尺寸）。', '判据 6·🔴 **纸面读的字段必须真的下发**（本单修的正是这一类）：订单详情面四份单据里每个 `order.<字段>` 都要在 backend/admin-api/src/main/java/com/migao/admin/dto/OrderDetailResponse.java 里有声明；删掉 `createdByName` ⇒ 必红。执行点 = tests/unit_ci_workflows/test_print_single_doc_on_paper.py 的 test_c4（红证 = test_c5 的注入 C，豁免台账为空且只许缩短）。', '判据 7·**加工单纸面印真值**：制单人 = `order.createdByName`、批号 = 快照行 `batchNo`（按 `itemId` 对齐）；缺值印 `—`，**纸面不再出现「未采集」**（那是「系统没有这个字段」的说法）。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的「🔴 ④ 制单人 / 批号 印服务端真值」+「🔴 ④ 红证：批号挂不到订单行 ⇒ 不猜」。', '判据 8·🔴 **表头企业名不得对无 system:manage 的岗位发请求**（issue #7285）：四张纸面在订单详情页**常驻挂载** ⇒ 企业名读口若无条件回落 `GET /api/admin/settings`（该端点要 `system:manage`），客服/销售/财务**一进详情页就吃一次 403**、屏上弹「没有权限执行此操作」而数据照常渲染。口径 = 登录态 `user.tenantName` 有值 ⇒ **一次请求都不发**（`try/catch` 吞不掉 `request.ts` 的 403 toast ⇒ 唯一干净修法是不发）。执行点 = frontend/admin-web/tests/unit/lib/use-company-name.test.ts 的判据 ④（登录态有值 ⇒ `getSettings` 零调用）+ 判据 ⑤ 对照（登录态为空 ⇒ 仍回落，防「永远不发」作弊）。'],
    skip_reason='[backend-contract] 纯前端打印链路 + 一条 DTO 字段透出（无 LLM 环节，不进 agent-eval 冒烟）：断言由 tests/e2e/specs/orders/print-preview.spec.ts、frontend/admin-web/tests/unit/{lib/print-doc,components/PrintDocPreview,components/ProcessingDoc}.test.tsx 与 tests/unit_ci_workflows/test_print_single_doc_on_paper.py 执行',
    tags=['ui', 'print', 'single-doc', 'guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-064 [NORMAL] 商家后台「手机端入口」二维码 —— 顶栏唯一入口（设置页不再有入口块）；地址单一配置、内容逐字等于该值、未配置不画假码（issue #5668 / #7198 / #7212）（源: cases/ui.yml）──
_CASE_UI_064 = EvalCase(
    id='UI-064',
    legacy_id='',
    title='商家后台「手机端入口」二维码 —— 顶栏唯一入口（设置页不再有入口块）；地址单一配置、内容逐字等于该值、未配置不画假码（issue #5668 / #7198 / #7212）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户逐字：「你在商家后端合适的位置搞个二维码，方便用户扫码使用」＋同日裁定「二维码放『系统设置 / 企业设置』页」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**有值 ⇒ 内容逐字等于配置值**：`NEXT_PUBLIC_BMINI_H5_URL` = `https://bmini-entry.invalid/b/`（哨兵值，与线上域名不同）时，二维码 svg 的 `<title>` 与可复制链接都逐字等于该值。红证：把 `QRCodeSVG` 的 value/title 改成硬编码线上地址 ⇒ 本格判红（实测：夹具用线上域名时该变异**判不出来** ⇒ 那是空断言方向，故改用哨兵值）。执行点 = frontend/admin-web/tests/unit/components/MobileEntry.test.tsx 的「点击 ⇒ 展开弹层，二维码的标题与可复制地址逐字等于配置值（哨兵值 ⇒ 硬编码必红）」+「点「复制链接」⇒ 复制的是**配置值**（不是硬编码地址）+ 成功提示」。', "判据 2·**无值 ⇒ 明确「未配置」且不画码**：配置为空/纯空白时渲染 `data-testid=bmini-h5-unconfigured`（文案含「尚未开通手机版」），且面板内 `querySelector('svg') === null`（不是「没找到 testid」，是确实没画）。红证：把渲染条件改成恒真 ⇒ 本格判红（实测）。执行点 = frontend/admin-web/tests/unit/components/MobileEntry.test.tsx 的「未配置 ⇒ 不画假码：零 svg + 逐字说明「未配置」」。", '判据 3·**唯一读取点**：`process.env.NEXT_PUBLIC_BMINI_H5_URL` 在全前端只允许出现在 frontend/admin-web/src/lib/bmini-h5-url.ts；组件经 `getBminiH5Url()` 取。红证：在第二个文件里再读一次 ⇒ 判红。执行点 = tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py。', '判据 4·**前端源码零硬编码域名**：`frontend/admin-web/src/**` 与 `frontend/bmini-app/{src,config}/**` 的**代码**（注释不算 —— 否则判据会被自己的文档喂红）里不得出现 app.migaozn.com；豁免台账为空、未登记即红。执行点 = 同文件（含「注释剥离但字符串保留」的状态机，防 `https://` 被当注释切掉的假绿）。', '判据 5·**发布链三环在案**：Dockerfile 的 `ARG`+`ENV`、deploy-frontend.yml 的 `--build-arg`、.env.example 的说明 —— 任一环缺失 ⇒ 镜像里没有这个值 ⇒ 顶栏永远显示「未配置」而没人会发现。红证：删任一环 ⇒ 判红（实测）。执行点 = 同文件。', '判据 6·**既有页零回归**：设置页既有域（企业信息 / AI 客服 / 通知设置）全在、既有 vitest 全绿（本单只换入口形态，不动域目录与保存逻辑）。⚠️ 2026-10-08（issue #6573）改判：原口径里的「参数总览」已**搬出本页**成为一级菜单项 ⇒ 本判据不再含它。', '判据 7·**落位（issue #7198 / #7212）**：① 顶栏右上角挂「手机端入口」按钮（`aria-label`，`< lg` 隐藏），点击才画码、点击外部收起；② 设置页**不再有**手机端入口（issue #7212 整块移除 —— 用户 2026-10-18 逐字「这块直接移除吧，已经迁移到右上角了」）：`data-testid=bmini-h5-entry` / `MobileEntryInline` / `QRCodeSVG` / `qrcode.react` / `getBminiH5Url` 任一在设置页代码里出现即红；③ 二维码只由 `MobileEntry.tsx` 的 `MobileEntryPanel` 渲染一处。红证：从 Header 摘掉 `<MobileEntryHeader />` ⇒ 单源守卫判红（实测）；把入口块塞回设置页 ⇒ 单源守卫判红（实测）。执行点 = frontend/admin-web/tests/unit/components/MobileEntry.test.tsx + frontend/admin-web/tests/unit/components/Header.test.tsx 的「顶栏带「手机端入口」按钮」+ frontend/admin-web/tests/unit/pages/settings.test.tsx 的「企业信息域**不再**渲染入口块」+ tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py 的 test_qr_entry_is_in_the_header_only_and_keeps_existing_tabs。'],
    skip_reason='[backend-contract] 纯前端渲染 + 接线判据（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest（frontend/admin-web/tests/unit/components/MobileEntry.test.tsx、frontend/admin-web/tests/unit/pages/settings.test.tsx）与 pytest（tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py）执行',
    tags=['ui', 'settings', 'qrcode', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-065 [NORMAL] 销售单数量列消费**实发**（order_shipment_items，经 admin 读面）：已发货/部分发货/未发货/读面未取到四态各自可判 + 永不印 0 + 缺口显式（issue #5651 收口）（源: cases/ui.yml）──
_CASE_UI_065 = EvalCase(
    id='UI-065',
    legacy_id='',
    title='销售单数量列消费**实发**（order_shipment_items，经 admin 读面）：已发货/部分发货/未发货/读面未取到四态各自可判 + 永不印 0 + 缺口显式（issue #5651 收口）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-26 逐字裁定销售单要「挂在发货链上」= 随货给客户的那张、数量与**实发**同源；issue #5651 正文把「admin 端没有读面 ⇒ admin-web 拿不到实发数量」登记为未完成项，2026-09-27 由 OR-051 补上后端读面后本用例接线'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**已发货 ⇒ 数量列印实发**（不是下单数量）：夹具给实发 7 而下单数量 3 ⇒ 纸面必须印 7。执行点 = frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 的「⑧ 已发货 ⇒ 数量列印实发」+「⑧ 红证：退回订单行投影 ⇒ 必红」。', '判据 2·🔴 **部分发货 ⇒ 未发行显式标「未发」**（不是 0、不是空白）：两行订单行、只有一行有实发 ⇒ 该行印实发、另一行印「未发」且**不含任何数字**（印 0 = 把「没有这个数」画成「实发为零」）。执行点 = 同文件「⑨ 部分发货」+「⑨ 红证：写成 0 / 静默留空 ⇒ 必红」。', '判据 3·**未发货 ⇒ 数量列 = 订单数量，且纸面标明基准**（不静默沿用：「未发货：数量列 = 订单数量（尚无可核的实发）」）。执行点 = 同文件「⑩ 未发货」。', '判据 4·🔴 **读面没取到（null）与「未发货」必须分开**：取不到读数 ⇒ 纸面标「发货明细未取到」，不得显示成「未发货」（把取数故障读成业务事实 = 用缺数据冒充业务状态）。执行点 = 同文件「⑪ 读面没取到」+「⑪ 红证：四态合并成一种显示 ⇒ 必红」（四句口径文案两两不同 + 四个业务情形判出四个态）。', '判据 5·**挂不到订单行的实发行显式提示行数**（不静默丢）：一枚实发行 order_item_id 为空 ⇒ 纸面提示「另有 1 行实发明细未挂到订单行（不猜归属，故不在本表）」。执行点 = 同文件「⑫」。', '判据 6·**口径判定是纯函数且有独立判据**：resolveSalesQuantity 的四态/累加/缺值边界由 frontend/admin-web/tests/unit/lib/sales-shipment.test.ts（11 格）钉住 —— 含「补发（第二张发货单）实发累加」与「订单行数量缺失 ⇒ null 而不是 0」。', '判据 7·🔴 **无第二份字段映射**：tests/unit_ci_workflows/test_print_media_matrix_guard.py 的 C5（销售单列清单在 src 下**恰好命中一个文件**）零回归。红证（实测 rc=1）：把列清单复制一份到 SalesDocA4.tsx ⇒ C5 判红。', '判据 8·🔴 **金额仍全部取服务端字段**（前端现算 = 第二份真值）：既有判据（SalesDoc.test.tsx 的 ③ 与其红证）零回归。红证（实测 rc=1）：把行金额改成 unitPrice×quantity ⇒ 该判据红。', '判据 9·**类级元守卫**：tests/unit_ci_workflows/test_shipment_read_surface_guard.py 把「同一真值两个读面只落一面」与「缺值被显示成 0」固化 —— 消费方接错面（改调 /api/worker/shipment）/ 数量列写 `?? 0` / 管理面自拼字段 ⇒ 各自判红。'],
    skip_reason='[backend-contract] 纯前端渲染 + 接线判据（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest（frontend/admin-web/tests/unit/components/SalesDoc.test.tsx、frontend/admin-web/tests/unit/lib/sales-shipment.test.ts）与 pytest（tests/unit_ci_workflows/test_shipment_read_surface_guard.py）执行',
    tags=['ui', 'order', 'print', 'sales-doc', 'shipment', 'actual-quantity'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-066 [NORMAL] 商家后台大菜单信息架构：**5 组 + 三个一级项**（**最前席位「经营看板」** / 尾席位「商品管理」「企业基础设置」）+ 尾部「通知中心」= **20 项**（🔴 2026-10-17 issue #7087 用户裁定「经营看板直接作为一级菜单，移除工作台」⇒「工作台」组撤销、「每日简报」菜单项删除；沿革：#5939 +「发货单」、#6573 +「参数总览」、#6580 收拢生产组并撤「参数总览」⇒ 24→21）（源: cases/ui.yml）──
_CASE_UI_066 = EvalCase(
    id='UI-066',
    legacy_id='',
    title='商家后台大菜单信息架构：**5 组 + 三个一级项**（**最前席位「经营看板」** / 尾席位「商品管理」「企业基础设置」）+ 尾部「通知中心」= **20 项**（🔴 2026-10-17 issue #7087 用户裁定「经营看板直接作为一级菜单，移除工作台」⇒「工作台」组撤销、「每日简报」菜单项删除；沿革：#5939 +「发货单」、#6573 +「参数总览」、#6580 收拢生产组并撤「参数总览」⇒ 24→21）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户裁定汇总（**同一份声明的两条日期**，不是两轮对话）：2026-09-29「加工项应该属于生产管理」「客户管理也不属于交易管理」「（售后）和客户管理应该属于一类？都属于服务客户的功能」「智能客服和客户管理是否应该合并到一个大菜单下？你考量下」「商品列表改成商品管理，直接作为一级菜单使用」；2026-10-01（issue #5877）「商品管理的菜单不应该作为第一行」（位置=「工作台」组之后，仍保留为一级项）「商品管理页面本体也要改」「列表中的商品ID移除，不要展示在列表」「搜索区的商品ID筛选也一并移除」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**三源同构（组层）**：`frontend/admin-web/src/config/menu.ts` 的 `menuGroups` / `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE` / `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions` 的「组 key + 组名 + 顺序」逐值相等，且为 **5 组**：`customer-service 客户服务 / trade-center 交易管理 / production-center 生产管理 / inventory-center 仓储与物料 / org-center 组织管理`。🔴 **2026-10-17（issue #7087）**：原第 1 组 `workspace 工作台` 已**整组撤销**（不再是组、也不是空组）⇒ 6 组 → 5 组。执行点 = tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py 的 test_menu_is_isomorphic_across_three_sources（#5778 起含「席位项层 / 独立项层」两段判据；**#5877 起再含「顶层布局序列」**——**位置**也参与三源比对；**#7087 起该序列的前端侧含三个席位**，注入式红证第 ⑥~⑭ 条）。', '判据 1b·🔴 **最前席位「经营看板」（issue #7087）**：`menu.ts` 的 `standaloneHeadItems` 第 1 项 = 「经营看板」(`/dashboard`，节点码 `dashboard:view` **一字不动** ⇒ 零授权 delta)，渲染在**所有分组之前**；三源同批表达同一位置（`MenuController.MENU_TREE` 顶层**首个**节点 / `AuthService.buildMenusByPermissions` **首个**顶层 `menus.add` / 前端 `standaloneHeadItems`）。**为什么必须最前**：`lib/menu-nav.ts` 的 `landingPath()` = **第一个可见菜单项**（issue #6758）⇒ 放尾席位会让登录落点变成「在线接待」，与用户逐字要的「一进来就很直观的看到经营看板」正好相反。执行点 = tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（顶层布局序列 + 注入 ⑪~⑭）+ backend/ai-agent-service/app/context/menu_navigator.py 的 `MENU_TREE` 首节点（镜像判据 tests/unit_ci_workflows/test_menu_navigator.py）。', '判据 1c·🔴 **「每日简报」菜单项已删除（issue #7087）**：`briefingToggle` 这一菜单级过滤机制**一并撤掉**（`MenuItem` 接口不再有该字段）；`/briefing` 保留为**重定向薄壳** → `/dashboard`（旧深链不 404），守卫前缀 `/briefing` 仍在 `ROUTE_PERMISSION_MAP`（= `dashboard:view`）但**不再有菜单节点**（登记在 test_agent_permission_parity.py 的 `ROUTE_WITHOUT_MENU_NODE` 与 test_rbac_derived_pages.py 的 `ROUTE_PREFIX_EXCEPTIONS`）。企业开关 `GET/PUT /api/admin/briefing/config` **继续存在**，只驱动**经营看板上的结论卡**（`BriefingCard enabled=…`）：开关关 = 看板无结论文字；开关开 = 有结论文字。执行点 = 同上两条守卫 + UI-085 判据 3。', '判据 2·**加工项管理归生产管理组**（用户第 1 条）：`production-center` 组内顺序 = 作业看板 → 智能派单 → 计件工资（3 项；🔴 #6580 起「加工项管理」「工艺配置」两个菜单项已移除），且 `product-center` 组**不再存在**。执行点 = frontend/admin-web/tests/unit/pages/processing-merged.test.tsx（「加工项管理由生产管理组承载」）+ tests/unit/pages/processing-fees.test.tsx + backend/admin-api/src/test/java/com/migao/admin/controller/MenuControllerTest.java 的 productionCenterGroupMirrorsMenuTs / productCenterGroupIsGone。', '判据 3·**客户侧独立成「客户服务」组**（用户第 2/3 条）：该组成员与顺序 = 在线接待 → 知识库 → 售后工单 → 客户列表；`trade-center` = 销售订单 → 财务对账。执行点 = frontend/admin-web/tests/unit/components/Sidebar.test.tsx（「客户服务」组内顺序）+ backend/admin-api/src/test/java/com/migao/admin/service/AuthServiceTest.java 的 currentUserMenusDropRemovedChatEntry / currentUserMenusAbsorbCustomerCenterIntoTrade。', '判据 4·🔴 **尾席位一级项「商品管理」与「企业基础设置」**（用户 2026-09-29「直接作为一级菜单使用」）：两项**保留为一级菜单**（不折叠、一屏直达）、不属于任何组（服务端 = `MenuController` 顶层节点 + `AuthService` 顶层 `menuItem`），渲染在 **`STANDALONE_TOP_AFTER_GROUP_KEY`（现取最后一个组 `org-center`）之后**、尾部「通知中心」之前。⚠️ 不要把「最前席位」（经营看板）与它混为一谈：**两个席位的位置语义不同**，见 `menu.ts` 文件头「三个席位」节。**席位组不可见时的回落**：`org-center` 被整组权限过滤掉 ⇒ 尾席位项**回落到当前可见分组的末尾**（绝不跟着消失）；**最前席位**不依赖任何常量、恒在**所有分组之前**。执行点 = 三源同构守卫的「顶层布局序列」判据（注入 ⑦ MenuController 挪位 / ⑧ 前端尾席位常量改判 / ⑨⑩ AuthService 挪首尾与组之间 / ⑪~⑭ 最前席位）+ frontend/admin-web/tests/unit/lib/menu-nav.test.ts 的 `splitGroupsAtTopItemSlot` 专条用例 + frontend/admin-web/tests/unit/components/Sidebar.test.tsx 的 DOM 顺序用例 + MenuControllerTest 的 topLevelStandaloneItemMirrorsFrontend。', '判据 9·🔴 **「参数总览」一级项已撤（issue #6580）**：`standaloneTopItems` 不再含 `/settings/params`（内容回到 `/settings` 页内的配置域）；旧路径 `/settings/params` 保留为重定向。当前一级项 = **3 项**（最前席位：经营看板；尾席位：商品管理 / 企业基础设置）。执行点 = tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（席位项层 / 顶层布局序列）+ test_agent_permission_parity.py（`ROUTE_MENU_ANCHORS` / `MENU_READ_ENDPOINT_ANCHORS` 成对登记）。', '判据 5·**面包屑与侧边栏一致（§15.2）**：`/` 与 `/dashboard` ⇒ **单级**「经营看板」（issue #7087；旧口径是「工作台 > 经营看板」，组名「工作台」自此**不再出现在任何商家可见面**）；未知路径兜底 ⇒ 单级「经营看板」（可回首页）。`/products`、`/settings` ⇒ **单级**（一级项**没有父组**，与「通知中心」同口径）；`/customers`、`/after-sales`、`/knowledge`、`/agent-workspace*`、`/chat` ⇒ 首项「客户服务」。执行点 = frontend/admin-web/tests/unit/components/Header.test.tsx + frontend/admin-web/tests/unit/lib/menu-breadcrumb-coverage.test.tsx（PG-038 按菜单项 path 穷举，末项 == 菜单名）。', '判据 6·**RBAC 单一真值源同批对齐**：`rbac/manifest.json` 的 `menu_nodes`（25 条，**首条 = 经营看板**） / `menus.{frontend,controller,auth}`（分别 25 / 23 / 19 条） / `pages[]`（20 页，「每日简报」条已销账）与本 IA 逐值相等，产物 `rbac/readings.json` 新鲜（`python3 rbac/generate_readings.py --check`）。执行点 = tests/unit_ci_workflows/test_rbac_single_source_manifest.py + test_rbac_derived_pages.py（`ACTION_NODE_CODES` / `ROUTE_PREFIX_EXCEPTIONS` 只许缩短）。', '判据 7·**权限码 / 路径 / 门控一字不动（零可见性 delta）**：纯信息架构调整，不改任何端点的码（`dashboard:view` 一字未动）；后端 `AuthServiceTest` 的角色可见性用例（负控 / inbound 独立门控 / 客户侧）+ frontend/admin-web/tests/unit/lib/menu-nav.test.ts 的权限过滤表逐条精确断言。', '判据 8·**一级项不进「常用」**（#5877）：一级项**不再渲染星标按钮**，可收藏面 = 组内项 ∪ 尾部独立项；用户 localStorage 里残留的 `products` key **静默丢弃**（不出现第二条一模一样的入口），而一级项本身照旧渲染一次。🔴 #7087 新增的**最前席位**同样遵守本条（它是一级项的一种，不进「常用」）。执行点 = frontend/admin-web/tests/unit/lib/menu-pinned.test.ts + frontend/admin-web/tests/unit/components/Sidebar.test.tsx 的「无星标 / 不进常用 / 板块入口规格」用例。'],
    skip_reason='[backend-contract] 纯前端信息架构 + 三处菜单源同构（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest（前端）与 pytest（tests/unit_ci_workflows 的三源同构守卫）执行',
    tags=['ui', 'menu', 'ia', 'navigation', 'rbac'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-067 [NORMAL] 侧边栏「常用（收藏）」：用户自选钉 4~6 项 pin 在顶部（权限优先于偏好 / 无效 key 静默丢弃 / 满额拒绝 / 本机持久化）（源: cases/ui.yml）──
_CASE_UI_067 = EvalCase(
    id='UI-067',
    legacy_id='',
    title='侧边栏「常用（收藏）」：用户自选钉 4~6 项 pin 在顶部（权限优先于偏好 / 无效 key 静默丢弃 / 满额拒绝 / 本机持久化）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29 裁定：「只做常用（收藏）—— 用户自己钉 4~6 项，pin 在侧边栏顶部」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **权限优先于偏好**（本用例的安全判据）：钉过的项若当前无权（或企业开关关了「每日简报」）⇒ **必须**从「常用」消失。红证 = 只持 order:list 时 `resolvePinnedItems` 只回 `orders`（反向自证：全权时三项都在）。执行点 = frontend/admin-web/tests/unit/lib/menu-pinned.test.ts 的「钉过但当前无权的项 ⇒ 从「常用」消失」+「企业开关关掉「每日简报」⇒ 即使钉过也不出现」。', '判据 2·**不做死引用**：菜单项被删/改名（key 不再存在）或清单为空 / 钉住项一项都不可见 ⇒ 静默丢弃，且「常用」区**整区不渲染**（返回 null，不留空标题）。执行点 = 同文件的「菜单项被删/改名 ⇒ 静默丢弃」+「钉住的项一项都不可见 ⇒ 返回 null」。', '判据 3·**上限 6 且满额拒绝**（不静默顶掉别人的位置）：`togglePinned` 满额时原样返回；渲染面星标不翻转、计数停在 `6/6`、localStorage 不含第 7 项。执行点 = 同文件的「togglePinned 三态」+ frontend/admin-web/tests/unit/components/Sidebar.test.tsx 的「钉满 6 项后再钉第 7 项 ⇒ 被拒」。', '判据 4·**脏数据清洗 + 静默降级**：非 JSON / 非数组 / 元素非字符串 / 空串 / 重复 / 超长 ⇒ 逐个注入后读回合法子集（不抛错）；`localStorage` 读写抛错（隐私模式 / 配额满）⇒ 读回空表、写静默失败，侧边栏不白屏。执行点 = 同文件的三条持久化用例。', '判据 5·**保留用户的钉序**（不是菜单自身顺序）：先钉 finance 再钉 orders ⇒ 常用区就是 finance 在前；反例自证 = 菜单自身顺序 orders 在前。执行点 = 同文件的「保留用户钉的顺序」。', '判据 6·**渲染面**：未钉任何项时整区不渲染；点星标 ⇒ 该项出现在 `data-group-key="pinned"` 的「常用」区（DOM 最顶部）、计数 `1/6`、落盘 localStorage；再点即取消（区消失、落盘空表）；刷新后从 localStorage 恢复。执行点 = frontend/admin-web/tests/unit/components/Sidebar.test.tsx 的「常用（收藏）」5 条。', '判据 7·**合成 key 不撞车**：`PINNED_GROUP_KEY`（`pinned`）不得是任何真实菜单组的 key（否则 `data-group-key` 撞车）。执行点 = frontend/admin-web/tests/unit/lib/menu-nav.test.ts 的 IA 事实用例 + menu-pinned.test.ts 的「返回的合成组」。'],
    skip_reason='[backend-contract] 纯前端个性化偏好（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest 执行',
    tags=['ui', 'menu', 'favorites', 'preference'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-068 [NORMAL] 经营看板可插拔指标卡：`capabilities.aiService` 决定「AI 接待占比」卡**在不在**（未启用 ⇒ 不渲染，不是渲染成 0）（源: cases/ui.yml）──
_CASE_UI_068 = EvalCase(
    id='UI-068',
    legacy_id='',
    title='经营看板可插拔指标卡：`capabilities.aiService` 决定「AI 接待占比」卡**在不在**（未启用 ⇒ 不渲染，不是渲染成 0）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29 追加要求原话：「AI 接待占比这个需要设计成可插拔的，未来有部分企业可能未购买智能客服」；同日裁定判定口径 = 方案 B（按租户派生），并指明「未来是跟着租户购买模块决定的」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**注册表化**：依赖企业能力的卡片必须在 `frontend/admin-web/src/lib/dashboard-cards.ts` 的注册表里声明 `requires`，组件内不得散落 `if`。执行点 = frontend/admin-web/tests/unit/lib/dashboard-cards.test.ts 的「注册表里『AI 接待占比』依赖 `aiService` 能力位」。', '判据 2·🔴 **缺省 = 不渲染**（保守口径，与 `false` 同待遇）：能力位未下发（老后端 / 请求失败 / 字段拼错）时**不知道**企业有没有买 ⇒ 不显示，而不是显示来源不明的数字。执行点 = 同文件的表驱动五态（undefined / {} / false / true / 另一位为假）。', "判据 3·**未购买 ⇒ 卡片不渲染**，**不是**渲染成 0、**不是**空白占位（0 会被读成业务事实）。执行点 = frontend/admin-web/tests/unit/pages/dashboard.test.tsx 的「`aiService` 未启用/未下发 ⇒ 卡片不渲染」，含反向自证（`queryByText('AI 接待占比')` 为 null）。", '判据 4·**启用 ⇒ 数字来自服务端**：`aiSessionRate` / `activeSessions` 取自 `/api/admin/dashboard/stats`（前端不硬编码 0）。执行点 = 同文件「`aiService = true` ⇒ 渲染卡片，数字取服务端 `aiSessionRate`」。', '判据 5·**单点判定 + 未来可替换**：租户级判定收敛在 `AdminGate.tenantUsesAiService`（当前 = 租户有任一岗位持 `agent:session`；用户指明未来改为「跟着租户购买模块决定」）⇒ 届时**只改该函数体**，能力位契约与端侧判据不动。执行点 = backend/admin-api/src/test/java/com/migao/admin/security/AdminGateTest.java 的 `tenantUsesAiServiceFollowsSessionReadCode` + `AuthServiceTest::capabilitiesExposeAiServiceByTenant`（含查询失败 ⇒ 保守 false 的第三态）。', '判据 6·**类级元守卫**：注册表里每个 `requires` 都必须是**已知能力位**（类型被放宽时仍能挡运行期拼错）。执行点 = dashboard-cards.test.ts 的「类级元守卫」。'],
    skip_reason='[backend-contract] 纯前端显隐判定 + 后端能力位单测（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest 与 Java 单测执行',
    tags=['ui', 'dashboard', 'pluggable', 'capability'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-069 [NORMAL] 经营看板接上「订单状态分布」图：读 `/dashboard/order-status`、显示合计；单独失败只点名自己（源: cases/ui.yml）──
_CASE_UI_069 = EvalCase(
    id='UI-069',
    legacy_id='',
    title='经营看板接上「订单状态分布」图：读 `/dashboard/order-status`、显示合计；单独失败只点名自己',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29：「经营看板需要重构一下，当前的功能不满足当前整体产品功能需要了」→ 盘点（PR #5788）查出「`/dashboard/order-status` 端点与 `OrderStatusChart` 组件都已写好、**从未被任何页面引用**」；本单把死代码接进页面'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**接线为真**：页面必须真调 `dashboardApi.getOrderStatusDistribution()`，并把返回条目的 `count` 合计渲染成「共 N 单」（证明数据流到组件，而不是渲染空态）。执行点 = frontend/admin-web/tests/unit/pages/dashboard.test.tsx 的「订单状态分布图接线」。', '判据 2·🔴 **单独失败只点名自己**：该端点失败 ⇒ 失败告警里出现「订单状态分布」，且**不得**连坐点名其他块（趋势图/近期订单/商品销量排行）。执行点 = 同文件的第二条。', '判据 3·**被接线的组件必须能在 jsdom 里渲染**：`OrderStatusChart` 用 recharts `ResponsiveContainer`（需 `ResizeObserver`，jsdom 不提供）—— 它此前是死代码所以这个不兼容一直没暴露；`frontend/admin-web/tests/setup.ts` 提供最小 stub。执行点 = 上述两条（无 stub 则整页 44+ 条一起红，实测 `ResizeObserver is not defined`）。', '判据 4·**注入式红证**（已实跑）：把 `allSettled` 里的端点调用换成 `Promise.resolve({data:{data:[]}})`（= 未接线形态）⇒ 上述两条 **2 failed**（`toHaveBeenCalled` 与合计断言）；还原后 48 passed。'],
    skip_reason='[backend-contract] 纯前端接线与显隐判定（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest 执行',
    tags=['ui', 'dashboard', 'dead-code', 'wiring'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-070 [NORMAL] 经营看板「待支付订单」卡：计数来自服务端聚合 FILTER，下钻用端点枚举值 `pending_payment`（源: cases/ui.yml）──
_CASE_UI_070 = EvalCase(
    id='UI-070',
    legacy_id='',
    title='经营看板「待支付订单」卡：计数来自服务端聚合 FILTER，下钻用端点枚举值 `pending_payment`',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29：「经营看板需要重构一下，当前的功能不满足当前整体产品功能需要了」→ 盘点结论之一：看板缺「钱还没到」的风险面'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**计数来自真聚合**：`OrderMapper.selectDashboardOrderStats` 必须含 `COUNT(*) FILTER (WHERE status = 'pending') AS pending_payment_orders`。执行点 = backend/admin-api/src/test/java/com/migao/admin/mapper/OrderMapperTest.java 的 `dashboardStatsAggregateShape`。", '判据 2·🔴 **不得用 `/dashboard/pending-tasks` 当计数**：那是**任务列表**且每类上限 5 条（`LIMIT 5`）⇒ 拿它当「待支付订单数」会把「≤5」误报成总数。执行点 = 同一条判据（钉住真值来源是聚合 FILTER）。', '判据 3·**下钻可用**：卡片链接必须是 `/orders?status=pending_payment`（`resolveStatusParam` 直接匹配枚举值 ⇒ 不依赖中文标签词表）。执行点 = frontend/admin-web/tests/unit/pages/dashboard.test.tsx 的「待支付订单卡」。', '判据 4·**注入式红证**（已实跑）：把卡片数字写死成 `count={0}` ⇒ 该条 **1 failed**（断言数字来自服务端字段）；还原后 49 passed。'],
    skip_reason='[backend-contract] 前端卡片 + 后端 SQL 形态判据（无 LLM 环节，不进 agent-eval 冒烟）',
    tags=['ui', 'dashboard', 'metrics'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-071 [NORMAL] 看板口径整改：今日/昨日销售额只算四态（与本月同口径）+ 上期为 0 ⇒ 环比为 null 且显示「—」中性态（源: cases/ui.yml）──
_CASE_UI_071 = EvalCase(
    id='UI-071',
    legacy_id='',
    title='看板口径整改：今日/昨日销售额只算四态（与本月同口径）+ 上期为 0 ⇒ 环比为 null 且显示「—」中性态',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29：「经营看板需要重构一下，当前的功能不满足当前整体产品功能需要了」→ 盘点查出同页 6 处口径硬伤，本单整改其中两处'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**今日/昨日销售额与本月营收同口径**（只算 `confirmed/producing/shipped/completed`）：`OrderMapper.selectDashboardOrderStats` 的 `today_sales` / `yesterday_sales` 两条 FILTER 都必须带状态过滤。执行点 = backend/admin-api/src/test/java/com/migao/admin/mapper/OrderMapperTest.java 的 `dashboardStatsAggregateShape`。改前无状态过滤 ⇒ 未付款/已取消的单也算「今日销售额」，而同页「本月销售额」不含 ⇒ 两个「销售额」两套口径。', '判据 2·🔴 **上期为 0 ⇒ 环比为 `null`**（不是 0）：三个环比字段（`todayOrdersChange`/`todaySalesChange`/`monthRevenueChange`）在分母为 0 时必须序列化为 `null`。执行点 = backend/admin-api/src/test/java/com/migao/admin/controller/DashboardControllerTest.java 的 `changeIsNullWhenBaselineIsZero`。`0%` 的语义是「与上期持平」，与「没有可比基数」是两件事 ⇒ 折叠成 0 会被读成「没有变化」。', '判据 3·**前端「—」中性态**：环比为 `null` ⇒ 徽章文案「较昨日 —」、底色**中性灰**、**不画方向箭头**（没有可比基数时任何方向箭头都是编造），并带悬停说明「无上期可比」。执行点 = frontend/admin-web/tests/unit/pages/dashboard.test.tsx 的「上期为 0 ⇒ 徽章显示『较昨日 —』」。', '判据 4·**概览句同口径**：`formatOrderChange(null)` ⇒ 「—」，而 `0` 仍为「0%」（有基线且真持平）。执行点 = frontend/admin-web/tests/unit/components/TodayOverviewBar.test.tsx。', '判据 5·**注入式红证**（均已实跑）：把 `null` 折叠成 0 ⇒ 前端该条 **1 failed**；去掉今日销售额的状态过滤 ⇒ `OrderMapperTest` **FAILURE**。'],
    skip_reason='[backend-contract] 口径与语义整改（SQL 形态 + DTO 序列化 + 前端渲染），由 Java 单测与 vitest 执行；不涉 LLM，不进 agent-eval',
    tags=['ui', 'dashboard', 'metrics', 'semantics'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-072 [NORMAL] 超时工单：口径收敛一处（简报/看板/列表筛选同源）+ 看板卡下钻 `?overdue=1` 在列表页**真的筛**且可撤销（源: cases/ui.yml）──
_CASE_UI_072 = EvalCase(
    id='UI-072',
    legacy_id='',
    title='超时工单：口径收敛一处（简报/看板/列表筛选同源）+ 看板卡下钻 `?overdue=1` 在列表页**真的筛**且可撤销',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29：「经营看板需要重构一下」→ 盘点查出「最该被老板看见的是有几单快超期了」；用户同日要求「AI 接待占比做成可插拔」「未来跟着租户购买模块决定」，本单沿用同一纪律：**同一数字只算一份**'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **口径只有一处**：`AfterSalesTicketMapper.applyOverdue` = `status ∈ (pending,processing)` ∧ `deadline` 非空 ∧ `deadline` 已过；三个读面（简报快照 `overdue_tickets` / 看板卡 / 列表筛选）都调它，不得各写一份 wrapper。执行点 = backend/admin-api/src/test/java/com/migao/admin/mapper/AfterSalesTicketMapperTest.java 的 `applyOverdueShape`（三条缺一即红）。', '判据 2·**列表筛选同源**：`GET /api/admin/after-sales?overdue=true` 走同一 `applyOverdue`。执行点 = 同文件的形态判据 + `AfterSalesControllerTest`。', '判据 3·🔴 **下钻真的筛**：看板「超时工单」卡链接 `/after-sales?overdue=1`，列表页必须**把 `overdue: true` 发给服务端**（不是前端假装筛），并显示**可清除**的筛选指示。执行点 = frontend/admin-web/tests/unit/pages/after-sales.test.tsx 的两条（带 `?overdue=1` ⇒ 请求带 `overdue:true` 且指示可见；点掉指示 ⇒ 请求不再带 `overdue`）。', '判据 4·**卡片数字与服务端一致**：卡片数字取 `stats.overdueTickets`、`href` 逐字等于 `/after-sales?overdue=1`。执行点 = frontend/admin-web/tests/unit/pages/dashboard.test.tsx 的「超时工单卡」。', '判据 5·**注入式红证**（均已实跑）：前端去掉「把 overdue 发给服务端」⇒ 该条 **1 failed**；后端去掉 `deadline IS NOT NULL` 条件 ⇒ `applyOverdueShape` **FAILURE**。'],
    skip_reason='[backend-contract] 口径单源 + 前端筛选接线（无 LLM 环节，不进 agent-eval）',
    tags=['ui', 'dashboard', 'metrics', 'single-source'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-073 [NORMAL] 销售订单状态筛选支持逗号分隔多值：前端「待发货」= `confirmed,producing`（与看板卡计数取齐）（源: cases/ui.yml）──
_CASE_UI_073 = EvalCase(
    id='UI-073',
    legacy_id='',
    title='销售订单状态筛选支持逗号分隔多值：前端「待发货」= `confirmed,producing`（与看板卡计数取齐）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-09-29：「经营看板需要重构一下」→ 盘点查出「待发货卡计数含 producing、而链接只筛待发货」= 计数与下钻不一致；用户同日要求同一数字只能有一份口径'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **映射层修，而不是改卡片**：前端类型里的注释一直写着「`pending_shipment: 'confirmed'` // confirmed 和 producing 都算待发货」，而实际只下发单值 ⇒ 列表比计数少。修在 `toBackendStatusParam()`：`pending_shipment` ⇒ `'confirmed,producing'`，其余仍单值（**不放宽其他筛选的语义**）。执行点 = frontend/admin-web/tests/unit/pages/orders-status-drilldown.test.tsx 的「纯映射」条。", "判据 2·**端到端下钻链**：看板卡跳 `/orders?status=待发货`（中文标签）⇒ 列表页请求带 `status='confirmed,producing'`。执行点 = 同文件的「端到端」条（该文件**不 mock `@/types`**，跑真映射；`orders.test.tsx` 把 `@/types` 整体 mock 成后端状态键，该判据在那里不可测，故独立成文件并写明原因）。", '判据 3·**后端支持多值**：`OrderService.applyStatusFilter` 单值用 `=`、多值用 `IN`、空白不动 wrapper。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/OrderServiceTest.java 的 `statusFilterSupportsMultiValue`。', '判据 4·**注入式红证**（均已实跑）：前端恢复单值 ⇒ 2 failed；后端只取第一个状态 ⇒ `statusFilterSupportsMultiValue` **FAILURE**。'],
    skip_reason='[backend-contract] 口径/筛选参数与前端下钻映射（无 LLM 环节，不进 agent-eval）',
    tags=['ui', 'orders', 'caliber', 'multi-value'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-074 [NORMAL] 新增入库单从弹窗改为独立整页（版式对齐新增订单/新增商品）+ 入库单批次号可见化（issue #5844）（源: cases/ui.yml）──
_CASE_UI_074 = EvalCase(
    id='UI-074',
    legacy_id='',
    title='新增入库单从弹窗改为独立整页（版式对齐新增订单/新增商品）+ 入库单批次号可见化（issue #5844）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['仓储与物料 → 入库单：「新增入库单的布局很怪异，应该和订单，商品设计风格对齐」（2026-10-01，附建单弹窗截图）', '「并且缺乏入库批次号？批次号要根据统一规则自动生成」⇒ 用户二选一裁定：只做「看得见」，**不改生成时机**'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**建单是一等页面，不是弹窗**：`/inbound-orders/new` 独立路由存在；列表页「新建入库单」是 `router.push('/inbound-orders/new')` 导航，且点击后页面里**没有** `role=dialog`、**没有**「保存为草稿」按钮（改前是一个 960px `Modal`，商品结果被页脚截断、搜索框双边框、入库日期独占半行）。执行点 = frontend/admin-web/tests/unit/pages/inbound-orders.test.tsx 与 inbound-orders-new.test.tsx。", "判据 2·**版式件与商品/订单同族**：整页 = 页头（返回 + h1 + 一句口径）+ 两张分区卡片（h2「单据信息」「入库明细」）+ 吸底汇总条 `data-testid=inbound-create-summary-bar`（`sticky bottom-0`，同 /orders/new 的 fee-summary-bar）；控件一律用共享 `Input/Select`（h-9 / rounded-lg / 同一 focus ring），不再有裸 `border-neutral-300` 手写输入框。**栅格不拉伸控件**（issue #5912 改判，取代 #5871「日期跨 2 列」的口径 —— 跨列正是输入框被撑到整行宽的成因）：`入库日期` 占半列 + **标准尺寸**的原生 date 控件（宽度加在 `Input` 的 className 上、由 twMerge 顶掉它默认的 `w-full`）、**默认当天**（**本地日**）；**栅格内跨列字段数为 0**；`备注` 是**多行文本域**（textarea / rows≥3 / 整行宽，label 与控件真关联）。⚠️ 2 列 + 5 个字段 ⇒ 末行右半为空是**计数事实**，本口径的选择是让空白挨着「本来就窄」的日期控件，而不是把输入框拉长去填满它。红证 = ① 把建单搬回 `Modal` ⇒ 判据 1 的 `queryByRole('dialog')` 当场红；② 给日期字段加回 `md:col-span-2` ⇒ 跨列数断言红、删掉控件的宽度 class ⇒ 宽度断言红；③ 把 `localToday()` 换回 `new Date().toISOString().slice(0, 10)` ⇒ 默认当天那条红（该用例把进程时区钉成 UTC+8 并取 UTC 缺陷窗口正中的时刻）；④ 备注改回单行 `Input` ⇒ `getByLabelText('备注')` 取不到 / `tagName` 断言红。几何以 §15.7 的真实截图读图复核。", '判据 3·🔴 **建单契约一字未改**（版式改动不得顺手改契约）：提交 payload 逐字段与改造前相同（`source` / `items[]` 的 productId,skuId,quantity,unitCost,dyeLot,legacyBatchNo,rollLengthM），数量仍是「大于 0 且最多 1 位小数」。红证 = payload 少一个键 / 多一层包装 ⇒ 逐字段断言红。', '判据 4·**批次号「看得见」而生成时机不变**：建单明细表有「批次号」列且草稿态恒为「过账后生成」（**不得**出现 `PC-yyyyMMdd-NNNN` 这类前端编造的号段）；列表页有「批次号」列 —— 已过账显示服务端真值、草稿「过账后生成」、**作废显示「-」**（作废单永远不会过账，不谎报成「过账后生成」）、多批次聚合成「首个 等 N 个」。执行点 = inbound-orders-new.test.tsx + inbound-orders.test.tsx（`data-testid=inbound-batch-nos`）。', "判据 5·**列表批次号来自服务端聚合，不是前端拼的**：`InboundOrderQueryMapper.selectOrderLines` 用 `string_agg(batch_no, ',' ORDER BY batch_no)` 聚合明细批次号（一行 = 一个批次 ⇒ 列表只能聚合），草稿/作废为 `null`。", '判据 6·**新路由不破坏导航高亮**：`/inbound-orders/new` 必须仍解析到「入库单」菜单项（侧边栏 + 面包屑共用 resolveActivePath）。执行点 = frontend/admin-web/tests/unit/lib/menu-nav.test.ts。'],
    skip_reason='[backend-contract] 纯前端版式 + 一个聚合列（Java 侧只加 `batchNos` 读字段，无 LLM 环节，不进 agent-eval 冒烟）',
    tags=['ui', 'layout', 'inbound', 'batch'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端页面/版式用例：前置（入库单列表行、商品搜索结果、SKU 明细行）全部由单测自建或打桩（frontend/admin-web/tests/unit/pages/inbound-orders-new.test.tsx 与 frontend/admin-web/tests/unit/pages/inbound-orders.test.tsx mock `@/lib/api`）；后端那一条聚合判据由真 PG 判据自建 schema + 租户 + 单据（backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderListBatchNosRealDbTest.java）—— 不依赖共享夹具与真实服务 ⇒ 前置不成立时判据直接红；agent-eval 栈不跑它',
)

# ── UI-075 [NORMAL] 销售订单查询区在窄屏既不横向溢出（issue #5841）也不把筛选框压到不可读（issue #5850）：行必须可换行（flex-wrap）、每个字段格必须有 min-w-[…]；同行控件不得 flex-1 + 固定 min-w（源: cases/ui.yml）──
_CASE_UI_075 = EvalCase(
    id='UI-075',
    legacy_id='',
    title='销售订单查询区在窄屏既不横向溢出（issue #5841）也不把筛选框压到不可读（issue #5850）：行必须可换行（flex-wrap）、每个字段格必须有 min-w-[…]；同行控件不得 flex-1 + 固定 min-w',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-01 报障（附截图）：「是否加工」下拉贴到卡片右边界，同行的「查询 / 重置」按钮被挤出卡片外；同日同会话的第二形态（issue #5850）：溢出修完后**筛选框被压到不可读** —— 集成侧按 main 上的类名与盒模型给出读数（1440 下文本框约 74px、日期框约 80px，只显示得出「2026」），用户当场选定「现在就修」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **轨道必须可收缩**：查询区任何 `grid-cols-…` 的 `fr` 轨道都要写成 `minmax(0, …)`。CSS 里 `1fr` = `minmax(auto,1fr)` ⇒ 轨道最小尺寸 = 该格内容的 min-content、**不可收缩**。实测归因（真实 Chrome + 真实 Tailwind 编译产物）：改前第二行 `md:grid-cols-[repeat(4,1fr)_auto]` 各格 min-content = 下单时间 380 / 商品货号 251 / 商品标题 251 / 是否加工 141 + 按钮列 228 + 间隙 96 = **1347px**，而 1440 窗口下卡片内容宽只有 1060 ⇒ 溢出 287px。⚠️ 实测这四条 `1fr` 轨道**并非等宽**（380/251/251/141，各自等于本格 min-content）—— 「四条轨道全被撑到同宽」只是各格最小尺寸恰好相同时的特例，不是本缺陷的机制。执行点 = frontend/admin-web/tests/unit/pages/orders-query-area-overflow.test.tsx 的判据 ①。', '判据 2·**同行控件也要能缩**：查询区表单控件不得同时带 `flex-1` 与固定长度 `min-w-[<N>px|rem|em]`（改前两个日期输入是 `min-w-[130px]`）—— 轨道可缩而控件不可缩时，控件会顶穿所在格、同样溢到卡片外。执行点 = 同文件判据 ②。', '判据 3·**fail-closed**：查询区的**行**（≥2）/**字段格**（≥6）/表单控件（≥8 个）必须存在，删光即红 —— 否则各条判据会在空集上假绿。执行点 = 同文件判据 ⑤。', '判据 6·🔴 **行必须可换行**（issue #5850 的核心形态判据）：查询区每一**行**容器必须带 `flex-wrap`，且**不得**再用 `grid-cols-…` 单行布局 —— grid 的单行轨道只会把格压小、**不会换行**，这正是「溢出修完改成压扁」的病根。执行点 = 同文件判据 ①。红证（已实跑）：把第二行改回 `grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]` ⇒ 判据 ① 红并打印该类名。', '判据 7·**每个字段格必须有 `min-w-[…]`**：`flex-1` 的格若没有固定最小宽，窄屏会被压到 0（改前 1440 下文本框 74px 就是这么来的）。执行点 = 同文件判据 ②。红证（已实跑）：去掉商品货号格的 `min-w-[240px]` ⇒ 判据 ② 红并打印该格。', '判据 8·**防 A 类回潮**：查询区若**又出现** `grid-cols-…` 行，其 `fr` 轨道仍必须写成 `minmax(0,…)`（issue #5841 那条判据保留为第二道闸）。执行点 = 同文件判据 ④。', '判据 9·**像素读数（#5850 改后；真 Chrome 153 + 仓库 tailwind CLI 编译的真 CSS）**：1280/1366/1440/1512/1536/1920 六档 —— 日期框 50.4/66.5/80.4/93.9/98.4/170.4 → **114.5/141.5/157.4/110.9/118.1/145.8**；商品货号/标题框 41.1/59/74.4/89.4/94.4/174.4 → **169/185/206.1/169/169/190.8**；六档**横向溢出均为 0**。复算入口 = 最小夹具（真实 tailwind 产物 + Playwright 量 `getBoundingClientRect`）。', '判据 4·**像素读数**（真实浏览器复核，读数表见 PR body）：改前在 375/414/768/900/1024/1200/1279/1280/1366/1440/1512 窗口下页面横向溢出 +48/+9/+649/+517/+633/+457/+378/+377/+291/+217/+145px，「查询/重置/刷新」右边界最多出卡片 **719px**；改后 12 个宽度（375~1920）**溢出 0 / 按钮出界 0**。', '判据 5·**注入式红证**（均已实跑）：把第二行改回 `md:grid-cols-[repeat(4,1fr)_auto]` ⇒ 判据 ① 红并打印类名；把第一行改回 `md:grid-cols-[1fr_1fr_1.5fr]` ⇒ 判据 ① 红（同类缺陷的第二处实例：实测 768~1100 窗口下第一行自身溢出 41~173px）；给日期输入加回 `min-w-[130px]` ⇒ 判据 ② 红。'],
    skip_reason='[backend-contract] 纯前端布局（无 LLM 环节，不进 agent-eval）；jsdom 无布局引擎（`getBoundingClientRect` 恒 0）⇒ 单测钉类名形态，像素读数走真实浏览器',
    tags=['ui', 'orders', 'layout', 'overflow'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-076 [NORMAL] 订单详情页费用构成可见：商品合计 + 加工费 + 其它构成 = 订单金额（issue #5843）（源: cases/ui.yml）──
_CASE_UI_076 = EvalCase(
    id='UI-076',
    legacy_id='',
    title='订单详情页费用构成可见：商品合计 + 加工费 + 其它构成 = 订单金额（issue #5843）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「商品合计 ¥245.14 与订单金额 ¥368.74 之间那笔 ¥123.60 加工费在页面上任何位置都不出现」（2026-10-01 报障截图），并问「是否要和新增订单页对齐」⇒ 集成侧裁定：对齐**展示口径**、不复制实现（详情页 = 落库快照，新增订单页 = 试算预览）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **那笔钱必须在页面上出现**：含加工费的订单渲染「加工费」行，其值 = 落库 Σ `items[].processingFee`（报障单 = 245.14 商品 + **123.60** 加工 = 368.74 订单金额）。改前实测读数（本判据的红证）：整页金额读数 = ["¥368.74","¥23.80","¥245.14","¥245.14","¥368.74","¥0.00","¥368.74"] —— **¥123.60 一个渲染点都没有**。执行点 = frontend/admin-web/tests/unit/pages/order-detail.test.tsx::「复现读数：这笔 ¥123.60 必须在页面上出现」。', '判据 2·**等式在页面上看得见**：`data-testid=fee-breakdown-equation` 的文本同时含 商品合计 / 加工费 / 订单金额 三个数（`¥245.14（商品合计） + ¥123.60（加工费） = ¥368.74（订单金额）`），且页面上读到的 `商品合计 + 加工费 = 订单金额` 逐值闭合（差额非 0 ⇒ `data-testid=fee-breakdown-other` 的「其它构成」解释行把它报出来）。红证 = 去掉接线 ⇒ `fee-breakdown-goods` 找不到。', '判据 3·**只展示落库快照、不重算**：`unit_price` 9.99 与米数 10.3（重算 = 102.90）而落库 `processingFee` = 123.60 时，页面显示 123.60 且**不出现** `¥102.90`（详情页是落库快照面，试算口径只属于新增订单页；`fee_source=manual` 另标「人工改价」）。', "判据 4·**未定价不渲染 `¥0.00`**：`fee_source=unpriced` 的行显式标「未定价」并**点名组合**（口径 = `unpricedCombinationLabel`：`items.join(' + ')` → composition → 「没有可匹配的组合（缺选配信息）」），未定价区文本**不含** `¥0.00`，也不渲染「加工费 ¥0.00」行（那与「本来就不收」长得一样 = 静默改钱的外观）。", '判据 5·**布料单不出现空行 / `¥0.00` 行**：无加工费、无未定价、无差额的订单整块不渲染（`data-testid=order-fee-breakdown` 不存在）—— 没有加工是正常，不是缺失。', '判据 6·**类级元守卫（单源）**：`frontend/admin-web/tests/unit/order-fee-composition-guard.test.ts` 扫全 `src/**` 的「逐行累加加工费」形态：命中而不在**只许缩短**的 `ALLOWED_SITES`（4 条冻结快照：共享层 / 明细行合计区 / 纸质发货单 / 新增订单页试算面）里 ⇒ 红；白名单里每一条必须仍是**真在累加**的活文件（豁免不许比代码活得久）；订单详情页**不得出现**加工费字段名（必须走 `frontend/admin-web/src/lib/order-fee-display.ts`）。'],
    skip_reason='[backend-contract] 纯前端展示（后端字段与契约一字未改：`processingFee` / `processingFeeDetail` 早已由 `OrderDetailResponse.OrderItemResponse` 下发；无 LLM 环节，不进 agent-eval 冒烟）',
    tags=['ui', 'order', 'fee', 'display'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端展示用例：前置（订单行 + 落库的 processingFee / processingFeeDetail）全部由单测自建 —— frontend/admin-web/tests/unit/pages/order-detail.test.tsx mock `@/lib/api` 的 `orderApi.getOrder`（mock 数据即用户报障那一单的落库形状），frontend/admin-web/tests/unit/lib/order-fee-display.test.ts 直接构造行数据 —— 不依赖共享夹具与真实服务 ⇒ 前置不成立时判据直接红；agent-eval 栈不跑它',
)

# ── UI-077 [NORMAL] 商品详情批次面板「按批次盘点」：按货号列批次与余量 + 实盘录入 + 差异预览（± 与合计）+ 提交后列表刷新为新余量（issue #5865）（源: cases/ui.yml）──
_CASE_UI_077 = EvalCase(
    id='UI-077',
    legacy_id='',
    title='商品详情批次面板「按批次盘点」：按货号列批次与余量 + 实盘录入 + 差异预览（± 与合计）+ 提交后列表刷新为新余量（issue #5865）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['要支持用户按批次做库存盘点（用户 2026-10-01 会话逐字；档位裁定 A 最小录入式：按货号列出批次与当前余量 → 填实盘米数 → 差异预览（±）→ 提交）', '盘点是仓储日常动作：录完要能当场看见差异，提交完要能看见新余量'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**差异预览就是账号面**：逐行显示 `差异 = 实盘 − 余量`（正 = 盘盈带 `+`、负 = 盘亏）与页脚**合计差异**（余量 60 → 实盘 58.5 ⇒ 行内 `-1.5`、合计 `-1.5`；实盘 62 ⇒ `+2`）。执行点 = frontend/admin-web/tests/unit/components/BatchStocktakeForm.test.tsx 的「UI-077 差异预览」', '判据 2·**不静默取整**：`2.755` / `-1` ⇒ 行内说明（「只能填 ≥0 且最多 1 位小数（0.1 米粒度，服务端不取整）」）+ **提交按钮禁用** + **零请求**（前端不许把非法值四舍五入后发出去，也不许发一笔注定 400 的请求）。执行点 = 同文件「UI-077 不静默取整」', '判据 3·**零差异零请求**：实盘 == 余量 ⇒ 差异 `0`、按钮禁用、不发请求（后端另有「零写入」判据，前端不许先发一笔空请求）。执行点 = 同文件「UI-077 零差异零请求」', '判据 4·**提交载荷**：`{productId, runId, lines:[{batchId, actualMeters}]}`，只带**真的变了差异**的行（余量 60 的两行里只填一行 ⇒ `lines` 恰 1 条）；`runId` 形态 `PD-…`。执行点 = 同文件「UI-077 提交载荷」', '判据 5·**幂等键语义**：提交**成功** ⇒ 换新 `runId`（下一笔 = 新的一次盘点）；提交**失败** ⇒ 复用同一个 `runId`（网络重试不双记）且后端 4xx 原文照实显示。执行点 = 同文件「UI-077 幂等键语义」', '🔴 判据 6·**结果可见**（`migao-dev-flow` §15.1：禁止停在「函数被调用」）：提交成功后宿主的批次余量表**重新取数并渲染新余量**（60 → 58.5），不是「提交成功但列表还是旧值」。执行点 = 同文件「UI-077 结果可见」', '🔴 红证（改前实测）：本单落地前 `frontend/admin-web/tests/unit/components/BatchStocktakeForm.test.tsx` 整个文件不存在（`data-testid="batch-stocktake"` / `stocktake-input-*` / `stocktake-diff-*` / `stocktake-total` / `stocktake-submit` 在页面上一个都没有）；把「提交成功后 `runIdRef` 换新」删掉 ⇒ 判据 5 红；把 `onApplied` 回调删掉 ⇒ 判据 6 红（列表停在旧余量 60）'],
    skip_reason='[backend-contract] 纯前端录入与预览（写面口径由 PR-119 的真库判据守；本用例只判「看得见、拦得住、提交后刷新」）由 vitest（jsdom）执行，不进入 agent-eval 冒烟',
    tags=['ui', 'product', 'batch', 'stocktake', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="本用例是 [backend-contract] 纯前端用例：前置（`batchStockApi` 的 batches/distribution/reconcile/stocktake 四个响应）由单测自建 —— frontend/admin-web/tests/unit/components/BatchStocktakeForm.test.tsx 直接 `vi.mock('@/lib/api')` 注入批次夹具（余量 60、货号 SKU-11）并逐条桩掉响应；前置不成立时单测直接红（找不到 `data-testid`），不依赖共享夹具；agent-eval 栈不跑它",
)

# ── UI-026 [NORMAL] 跨权限域跳转入口按目标域守卫码显隐（作业看板「订单详情」+ 售后工单「订单号」）（源: cases/ui.yml）──
_CASE_UI_026 = EvalCase(
    id='UI-026',
    legacy_id='',
    title='跨权限域跳转入口按目标域守卫码显隐（作业看板「订单详情」+ 售后工单「订单号」）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['作业看板里点「查看」跳转到订单详情，这设计合理吗（用户 2026-10-01 走查；裁定改法 A：正名 + 按权限显隐 + 提示上移）'],
    expectations=[],
    data_checks=['判据 1·**入口文案有确定宾语**：作业看板行内入口 = 「订单详情」（「查看」在本行没有确定宾语 —— 与同行的「生产明细」互换也不违和，即命名失败的直接判据）；点击仍跳 `/orders/{orderId}`。执行点 = frontend/admin-web/tests/unit/pages/production-board.test.tsx 的「合并能力⑥订单详情」', "判据 2·**可见却 403 的红线（双向对照）**：持 `order:list` ⇒ 渲染该入口；**不持** ⇒ **不渲染**（默认岗位 product_manager 即持 production:view、不持 order:list 的形态）。⚠️ 反向用例必须同时清空 `roles` —— `usePermission()` 把 `roles:['admin']` 判为全权限（isAdmin），只改 permissions 会让红线**恒真**。执行点 = 同文件「无 order:list ⇒ 不渲染」+「持 order:list ⇒ 照常渲染」", '判据 3·**引导文案是页面级的**：「状态流转请在订单详情操作」全页**恰 1 条**且**不在 `<table>` 内**（改前 = 每行一份，挤在 8 列中最挤的「操作」格里）；无 `order:list` 时同一句标明「需订单查看权限」（不把人指向去不了的地方）。执行点 = 同文件「引导文案是页面级的」+「无 order:list 时引导文案标明需订单查看权限」', "判据 4·**类级元守卫（未登记即红）**：`src/app` 下 `(dashboard)` 路由组内的**跨权限域**字面量 `router.push/replace`，源文件必须出现目标守卫码（`has('<码>')`）；守卫码表**现取** `layout.tsx` 的 ROUTE_PERMISSION_MAP（不硬编码）。豁免台账当前为空且只许缩短。执行点 = frontend/admin-web/tests/unit/cross-domain-nav-permission-guard.test.ts 的「每个跨权限域跳转入口都按目标域守卫码显隐」", '同族第二处（**链内修**，铁律 12(b) ①）：售后工单详情页（守卫 `after_sales:view`）的「订单号」入口跳 `/orders/{id}`（`order:list`）—— 默认岗位里两者总同时持有（客服/运营），但岗位权限页可以只给前者 ⇒ 同一形态；改为无 `order:list` 时**订单号照显、不再是入口**。执行点 = frontend/admin-web/tests/unit/pages/after-sales-detail.test.tsx 的两条用例', '🔴 红证（改前实测，本机 vitest：2 文件 **6 failed / 25 passed**）：① 类级守卫具名抓到 `(dashboard)/production/page.tsx · /production → /orders/（目标守卫码 order:list，源页 production:view）`；②「合并能力⑥订单详情」找不到名为「订单详情」的按钮；③ 引导文案用例得**每行一条**（≠1）；④ 同族第二处 `(dashboard)/after-sales/[id]/AfterSalesDetail.tsx · /after-sales/[id] → /orders/` 由**类级守卫自己**抓出（不是人找的）。复算方式：进入 frontend/admin-web 目录后以 vitest 跑下面两个文件（全路径见 traces.tests）—— frontend/admin-web/tests/unit/cross-domain-nav-permission-guard.test.ts 与 frontend/admin-web/tests/unit/pages/production-board.test.tsx'],
    skip_reason='[backend-contract] 纯前端入口显隐与文案（admin-web），由 vitest 单测执行（含对源码的静态扫描），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'rbac', 'admin_web', 'navigation'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-078 [NORMAL] 「发货单」进大菜单（仓储与物料组，与「入库单」对称）：/shipments 列表页（全量发货单 + 关键词筛选 + 补打走纸面自检层）+ 三源同构 + **单据入口台账**类级守卫（未登记即红）（源: cases/ui.yml）──
_CASE_UI_078 = EvalCase(
    id='UI-078',
    legacy_id='',
    title='「发货单」进大菜单（仓储与物料组，与「入库单」对称）：/shipments 列表页（全量发货单 + 关键词筛选 + 补打走纸面自检层）+ 三源同构 + **单据入口台账**类级守卫（未登记即红）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-02 原话：「我让你开发过发货单的，但是在大菜单上没见到这个单据」；同日逐条裁定：形态 = **A（新建「发货单」列表页 + 菜单项）**、归属 = **仓储与物料组（与「入库单」对称）**'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **节点三源同构且落在「仓储与物料」组**：`frontend/admin-web/src/config/menu.ts`（`path: '/shipments'` / `permissionCode: 'order:list'` / `icon: 'Truck'`）/ `MenuController.MENU_TREE`（`new MenuNode(「order:list」, 「发货单」)` 且挂在 inventory-center 组）/ `AuthService.buildMenusByPermissions`（`menuItem(「shipments」, 「发货单」, 「/shipments」)` 且落在 `order:list` 自己的 if 里）三处逐字一致。执行点 = frontend/admin-web/tests/unit/lib/shipments-menu-isomorphic.test.ts（4 条，含「不得挂进交易管理组」的负控）+ tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py（全树 + 顶层布局序列）。红证：三处任删一处 ⇒ 各自判红且具名（本地实测：节点归属判定曾把节点自己的 `key` 当成组名 ⇒ 该判据当场红，已修）。", "判据 2·**权限码复用既有 `order:list`（零授权 delta）**：节点码 = 页面守卫码（`(dashboard)/layout.tsx` 的 ROUTE_PERMISSION_MAP）= 该页第一屏读端点码（`GET /api/admin/shipments`）。执行点 = tests/unit_ci_workflows/test_agent_permission_parity.py 判据 12（锚点 `MENU_READ_ENDPOINT_ANCHORS['/shipments']` ⇒ garments 页面源码里的 `shipmentApi.list`）+ 判据 11（`ROUTE_MENU_ANCHORS['/shipments']`）。红证：新造一个 `shipment:view` ⇒ 页面码与节点码脱钩、判据红（且该码今天没有岗位持有 ⇒ 菜单对所有人不可见 = #4203 同族坑）。", '判据 3·**面包屑与侧边栏一致（§15.2）**：`/shipments` ⇒ `仓储与物料 > 发货单`（末项逐字 == 菜单名）。执行点 = frontend/admin-web/tests/unit/lib/menu-breadcrumb-coverage.test.tsx（PG-038 按菜单项 path 穷举）。红证：删掉 Header 的该条目 ⇒ 该用例红。', '判据 4·**列表页看得见、缺值显式**：发货单号 / 订单号 / 客户 / 来源 / 发货人 / 发货时间 / 实发七列；未发货 ⇒「未发货」（不填当前时间）、发货人未采集 ⇒「-」、无明细 ⇒「无实发明细」（不是 0、不是空白）；`roll_count = 0` **不显示**（0 = 这一维不适用）。执行点 = frontend/admin-web/tests/unit/pages/shipments.test.tsx 的 ①②③。红证：把缺值渲染成 0 / 空串 ⇒ 对应断言红。', '判据 5·**补打走唯一打印入口**：点「补打」⇒ 取订单 → 打开**纸面自检层**（`PrintDocPreview`，真尺寸 A4 发货单，aria-label「发货单打印预览」）；取不到订单 ⇒ 不打开预览层（不弹一张缺数据的纸）。执行点 = 同文件 ⑥；`window.print()` 全仓唯一入口由 tests/unit_ci_workflows/test_print_single_doc_on_paper.py 把守（本页不新增第二处）。红证：绕开 usePrintDoc 直接 window.print() ⇒ 该守卫红。', '判据 6·🔴 **类级元守卫：单据入口台账（未登记即红）**：真值源 = `frontend/admin-web/src/lib/print-doc.ts` 的 `PRINT_TARGETS`（全仓唯一可打印单据清单），每个单据必须在 `tests/unit_ci_workflows/document_entry_ledger.json` 里**显式声明入口形态**（`menu:<菜单路径>` / `embedded:<承载页的菜单路径>`），且声明必须真实可达；台账清空**不能**消红。执行点 = tests/unit_ci_workflows/test_document_entry_ledger.py（12 条，含七种坏形态的注入式红证 + 「只加注释不红」的对照读数）。红证（本缺陷的原始形态）：把 menu.ts 的 `/shipments` 路径摘掉而台账仍声明 `menu:/shipments` ⇒ `test_removing_the_menu_item_goes_red` 当场红。', '判据 7·**既有菜单判据零放宽**：21 项 → **22 项**的计数改判落在既有用例/用例库（Sidebar / SidebarRedesign / CommandPalette / menu-nav / menu-icons / UI-066 / UI-021），只改计数与新增 key，**不删任何断言**。执行点 = frontend/admin-web/tests/unit/lib/menu-nav.test.ts 等（本地实测：改前 19 条红、改后全绿）。'],
    skip_reason='[backend-contract] 纯前端 IA + 页面行为（无 LLM 环节，不进 agent-eval 冒烟）：由 vitest（前端三份）+ pytest（tests/unit_ci_workflows 的台账/同构/权限判据）执行',
    tags=['ui', 'menu', 'ia', 'navigation', 'shipment', 'rbac'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-079 [NORMAL] 黄金策对话「客户端打字机」：服务端整段下发 ⇒ 客户端按节奏揭示（真实事件序下逐字 / 单调不回退 / 收口替换不卡 / 有界收敛 / 历史·中断·减少动画立刻全文）；PC 与**手机端（bmini）**同口径（issue #7235）（源: cases/ui.yml）──
_CASE_UI_079 = EvalCase(
    id='UI-079',
    legacy_id='',
    title='黄金策对话「客户端打字机」：服务端整段下发 ⇒ 客户端按节奏揭示（真实事件序下逐字 / 单调不回退 / 收口替换不卡 / 有界收敛 / 历史·中断·减少动画立刻全文）；PC 与**手机端（bmini）**同口径（issue #7235）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-02 原话（流式体验）：问「米宝走 SSE 但不是逐字输出，是否要改成逐字」⇒ 裁定 =「选 2（客户端打字机）」', '同一裁定附带的结构性理由（不做服务端真逐字）：backend/ai-agent-service/app/agents/customer_service_agent.py 的 astream_chat 用 graph.astream(initial_state, stream_mode="updates") = 节点级更新；backend/ai-agent-service/app/graph/skills/execution/finalize_turn.py 有后置收口（追加确认卡 XML / 用工具返回 message 替换回复）；C 端出站还有 backend/ai-agent-service/app/api/chat.py 的 _mask_for_customer 跨片脱敏 ⇒ 服务端逐字会与「收口后才是最终文本」冲突'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**真的在逐字**：注入一段文本后，t 时刻可见字符数 **< 全文长度**，且可见文本恒为全文**前缀**；最终 == 全长。执行点 = frontend/admin-web/tests/unit/hooks/use-typewriter.test.tsx「UI-079-1」+ frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx「UI-079 流式回复（真实打字机）」', '判据 2·**收口替换不卡**：先注入短文本、随后注入收口后的长文本（模拟 finalize_turn 替换）⇒ 全程采样「已揭示字符数」**只增不减**（不出现「先短后长再回退」），最终显示**必须是收口版**；反向（收口版更短）⇒ 立刻夹到收口版，不出现越界可见文本。执行点 = 同 hook 文件「UI-079-2」两条', '判据 3·**立刻收敛只对非直播面**：历史回放 / 切会话重挂载（挂载即完整）、用户中断（wasAborted）、减少动画（prefers-reduced-motion: reduce）⇒ 可见文本**立刻**等于全文（不许卡在半截）。🔴 **「流式结束」不在此列**（2026-10-17 / issue #7086 改判）：正文整段到达 + 紧随 done 只有几十~两百毫秒窗口，把「isStreaming=false ⇒ 立刻全文」当不变量会让揭示窗口 ≈ 0（本机实测：结束瞬间已是 37/37 全文 ⇒ 用户看到「一次性刷出」）。执行点 = hook 文件「UI-079-3 历史回放 / 已结束会话」「UI-079-3 用户主动中断（instant）」「UI-079-3 用户偏好减少动画」+ 组件文件「UI-079 中断（wasAborted=true）」「UI-079 历史回放（非流式）」「UI-079 切会话/重挂载」', '🔴 判据 4·**服务端不被改动（本单边界）**：本用例只判展示面 —— `git diff origin/main...HEAD -- backend/` 为空。执行点 = PR 的改动清单（本包零后端改动）', '🔴 判据 5·**真实事件序下必须逐字（issue #7086）**：正文以**一个** `text` 事件整段到达、紧随 `done`（store 同批把 `isStreaming` 置假并落库）⇒ 结束之后**仍在逐字**（t 时刻可见字符数**严格少于**全长、且恒为全文前缀），最终 == 全长；且整段揭示**有界**（≤ TYPEWRITER_MAX_REVEAL_MS，长文自动加速、不无限拖尾）。执行点 = frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx「🔴 UI-079 真实事件序」+ frontend/admin-web/tests/unit/hooks/use-typewriter.test.tsx「🔴 UI-079-1 真实事件序」「UI-079-3 有界收敛」。类级元守卫 = tests/unit_ci_workflows/test_typewriter_reveal_not_lifecycle_bound.py（揭示层再读外部生命周期开关 / 真实事件序判据被摘掉 ⇒ 判红）', '🔴 红证（改前实测）：本单落地前全仓 `grep -rn "typewriter\\|useTypewriter" frontend/admin-web/src` = 0 命中 ⇒ 组件测试 import 即失败；把 hook 换成直返全文（等效「无打字机」）⇒ 判据 1/2/3 的「中途可见 < 全长」「维持替换过程单调」「流式结束立刻等于全文」三条当场红（本机实测 3 failed / 6 passed）；把组件的 `data-revealed` 接入摘掉 ⇒ 组件侧两条红', '🔴 判据 6·**手机端（bmini）同口径执行点**（issue #7235）：同一组不变量在 frontend/bmini-app 上成立 —— 直播消息从 0 起逐字（t 时刻 `data-revealed` < 全长且恒为全文前缀）、结束之后仍逐字、历史回放 / 中断（`wasAborted`）/ 减少动画立刻全文、长文按上界有界收敛。执行点 = frontend/bmini-app/tests/chat-typewriter.test.tsx「UI-079 手机端打字机」6 条 + frontend/bmini-app/tests/store-chat.test.ts「stopStreaming 给被中断的消息打 wasAborted」（负控：已结束消息不打标记）', '🔴 红证（#7086，2026-10-17 实测）：把实现回退到 origin/main（旧 hook 的 `instant = !streaming || …` + 组件传 `streaming: !!message.isStreaming`）⇒ 本用例 19 条里 **5 条红**，其中「真实事件序」的读数是 `expected 37 to be less than 37`（= done 之后第一次读数已是全长，一帧未播，与用户现场一致）；改后 19 条全绿。复算：`git stash push -- frontend/admin-web/src/hooks/use-typewriter.ts frontend/admin-web/src/components/chat/MessageList.tsx` ⇒ `cd frontend/admin-web && npx vitest run --dir tests/unit use-typewriter.test.tsx MessageList-typewriter.test.tsx` ⇒ `git stash pop`（回退后 5 红、恢复后 19 绿，本机 2026-10-17 复算）'],
    skip_reason='[backend-contract] 纯前端揭示层（服务端一字未改：仍整段下发）由 vitest（jsdom）执行，不进入 agent-eval 冒烟；LLM 行为面不变，故无 agent 用例',
    tags=['ui', 'chat', 'streaming', 'typewriter', 'admin-web', 'bmini'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="本用例是 [backend-contract] 纯前端用例：前置由单测自建 —— frontend/admin-web/tests/unit/hooks/use-typewriter.test.tsx 用 `vi.useFakeTimers()` 直接驱动 hook 的揭示时钟；frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx `vi.mock('@/store/chat')` 注入带 `isStreaming/tool_calls` 的消息夹具。前置不成立时单测直接红（找不到 `data-revealed` / 找不到文案），不依赖共享夹具；agent-eval 栈不跑它",
)

# ── UI-080 [NORMAL] 黄金策对话不向用户暴露 tool：带 tool_calls 的消息只渲染人性化进度文案，工具名/入参/结果/原始 JSON 一律不进 DOM（对齐 C 端先例 issue #2857）（源: cases/ui.yml）──
_CASE_UI_080 = EvalCase(
    id='UI-080',
    legacy_id='',
    title='黄金策对话不向用户暴露 tool：带 tool_calls 的消息只渲染人性化进度文案，工具名/入参/结果/原始 JSON 一律不进 DOM（对齐 C 端先例 issue #2857）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-02 原话（同一次裁定）：「不要把 tool 暴露给用户，用户只关注 agent 回复了什么以及用户要交互什么」'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**工具执行中仍有可感知进度**：无正文 + `tool_calls[{status:'running'}]` ⇒ 渲染「正在处理您的请求...」（用户裁定的是「不暴露 tool」，不是「让界面长时间无反馈」）。执行点 = frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx「UI-080 工具执行中（无正文）」", '🔴 判据 2·**具名不暴露断言**（不是 `not None` 这类弱断言）：渲染结果里不得出现工具名 `order_query`、入参值 `SO-2026-001`、结果值 `RESULT_SECRET_2026`，也不得出现 `tool_calls` / `tool_name` / `"input"` / `"args"` / `工具调用` / `{"order_no"` 这些技术形态。执行点 = 同文件四个 UI-080 用例共用的 `expectNoToolDetails()`（有正文 / 仅 tool_calls 的历史消息 / status=error 各覆盖一次）', '判据 3·**正文本体不回归**：工具在场时正文照常显示（不得因「藏 tool」把回复内容一起藏掉）；仅 tool_calls、无正文的历史消息仍显示「（已处理）」兜底文案。执行点 = 同文件「有正文 + 工具同时在场」「仅 tool_calls、无正文的历史消息」', '判据 4·**C 端先例零回归（复算读数）**：frontend/mini-app/src/components/chat/MessageBubble.tsx 的「工具调用过程对客户隐藏（issue #2857）」行为不动，既有判据 frontend/mini-app/tests/message-bubble.test.tsx「UI-017: 工具执行过程对客户隐藏（不渲染 tool_calls 指示器）」仍绿（本包**未改** C 端任何文件）', '🔴 红证（改前实测）：把 `AIMessageContent` 的 tool_calls 分支改回「渲染工具名 + JSON.stringify(input)」⇒ 判据 2 当场红（本机实测：`data-injected-tool-exposure` 注入 ⇒ 3 条红 1 条绿，其中两条正是「工具名/入参进了 DOM」）'],
    skip_reason='[backend-contract] 纯前端展示面（后端是否下发 tool 信息是另一条边界，本用例不管）由 vitest（jsdom）执行，不进入 agent-eval 冒烟',
    tags=['ui', 'chat', 'tool-call', 'privacy', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="本用例是 [backend-contract] 纯前端用例：前置由单测自建 —— frontend/admin-web/tests/unit/components/MessageList-typewriter.test.tsx `vi.mock('@/store/chat')` 注入带 `tool_calls`（工具名 order_query / 入参 {order_no: SO-2026-001} / 结果含 RESULT_SECRET_2026）的消息夹具；前置不成立时单测直接红，不依赖共享夹具；agent-eval 栈不跑它",
)

# ── UI-081 [NORMAL] 列表页写按钮随权限显隐（issue #5983）：无写码岗位在 /orders、/products、/inbound-orders、/finance 看不到建单/建品/登记按钮，有码照旧（源: cases/ui.yml）──
_CASE_UI_081 = EvalCase(
    id='UI-081',
    legacy_id='',
    title='列表页写按钮随权限显隐（issue #5983）：无写码岗位在 /orders、/products、/inbound-orders、/finance 看不到建单/建品/登记按钮，有码照旧',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['客服/销售/财务登录后进 /orders、/products、/inbound-orders、/finance：页面能进（守卫是读码），但笔下的写按钮不该出现'],
    expectations=['direct_reply'],
    data_checks=['判据 1：客服（有 order:list、无 order:create）在 /orders **看不到**「新增订单」；运营（有 order:create）**看得到**。执行点 = frontend/admin-web/tests/unit/pages/list-write-button-permission.test.tsx「判据 1」', '判据 2：销售（有 product:list、无 product:create）在 /products 看不到「新增商品」；运营看得到。执行点 = 同文件「判据 2」', '判据 3：财务（有 inbound:view、无 inbound:create）在 /inbound-orders 看不到「新建入库单」；运营看得到。执行点 = 同文件「判据 3」', '判据 4（对照，防「一刀切隐藏」）：只持 order:create 时只有订单页按钮在场，另两页按钮不在。执行点 = 同文件「判据 4」', '判据 5（第 4 页 · 链内同修）：有 `finance:view` 但无 `finance:create` 时 /finance 看不到「登记收支」；财务（有码）看得到。执行点 = 同文件「判据 5」', '判据 6（第 5 页 · 链内同修 · issue #6392）：有 `knowledge:view` 但无 `knowledge:manage` 时 /knowledge 看不到「新建知识卡片」**与**「文档提炼」（两个写入口同码）；知识编辑（有码）两个都看得到。执行点 = 同文件「判据 6」', '🔴 红证 1（改前实测，2026-10-02）：`git stash push` 临时摘掉三页修复后跑本判据 ⇒ **4 failed / 4**（报错形态逐字为 `expected document not to contain element, found <button …>新增商品</button>`）；恢复修复后 **4 passed**。复算命令（在 `frontend/admin-web` 目录下执行）= `npx vitest run frontend/admin-web/tests/unit/pages/list-write-button-permission.test.tsx`', '🔴 红证 2（第 4 页加入时实测，2026-10-02）：先落判据 5、`/finance` 尚未接码时跑 ⇒ **1 failed / 4 passed**（`expected document not to contain element, found <button …>登记收支</button>`）；接码后 **5 passed**', '🔴 红证 3（第 5 页加入时实测，2026-10-06）：把 `frontend/admin-web/src/app/(dashboard)/knowledge/page.tsx` 回退到 HEAD（未接码）跑本文件 ⇒ **1 failed / 5 passed**（报错逐字 `expected document not to contain element, found <button`）；恢复后 **6 passed**。复算命令（在 `frontend/admin-web` 目录下执行）= `npx vitest run --dir tests/unit/pages list-write-button-permission`', '🔴 红证 4（类级守卫侧的同一处，2026-10-06）：同上回退后跑 `python3 -m pytest tests/unit_ci_workflows/test_list_page_write_button_gate.py -q` ⇒ **2 failed / 3 passed**（具名 `…/knowledge/page.tsx 未接写码 knowledge:manage（实取 []）` 与「未登记的写按钮」）；恢复后 **5 passed**'],
    skip_reason='[backend-contract] 纯前端展示面（按钮是否渲染）由 vitest（jsdom）执行；「提交时后端 403」属 admin-api 权限链（另有用例），本用例不管，不进入 agent-eval 冒烟',
    tags=['ui', 'rbac', 'button-gate', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-082 [NORMAL] 官网企业站整体重构（issue #6291）：四页文案按系统真实能力重写 + 织物质感视觉 + 清退占位联系方式；文案口吻改为能力陈述型书面语（issue #6326）（源: cases/ui.yml）──
_CASE_UI_082 = EvalCase(
    id='UI-082',
    legacy_id='',
    title='官网企业站整体重构（issue #6291）：四页文案按系统真实能力重写 + 织物质感视觉 + 清退占位联系方式；文案口吻改为能力陈述型书面语（issue #6326）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['官网四个页面（首页 / 产品与服务 / 关于我们 / 联系我们）加导航 / 页脚，按当前系统真实能力重写文案与视觉（用户 2026-10-04 逐字：「根据我们当前米高整体系统的能力，重构下我们的主页整体设计，每个页面每个文案都重新做整体设计，要体现出我们的产品优势和亮点」）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·文案=真实能力：首页渲染六个能力域与真实菜单名（经营看板 / 每日简报 / 智能派单 / 计件工资 / 余料台账 / 省料看板 / 岗位权限 / 商品管理 / 通知中心），菜单名与 frontend/admin-web/src/config/menu.ts 同源（共用 frontend/admin-web/src/components/corporate/capability-map.ts）。执行点 = frontend/admin-web/tests/unit/pages/corporate-home.test.tsx「renders 能力地图」', '判据 2·旧口径不复活：首页与产品服务页不得出现已清退的夸大表述（自动学习 / 越用越懂 / 越用越精准）与未落地术语（拼版 / 质检 / 毫秒级 / 批量操作库存 / 智能工单流转）。执行点 = corporate-home.test.tsx「宣传真实性：不夸大能力」与 services.test.tsx「能力边界」两条', '判据 3·占位假值清退（本单新增）：四页与页脚均不得出现 400-888-8888 / contact@migao-ai.com / 文一西路000号 / 地铁5号线。执行点 = corporate-home.test.tsx、corporate-contact.test.tsx、CorporateFooter.test.tsx 三条同名判据', '判据 4·合规宣称不变（OB-005 口径字面保留）：首页仍渲染 GB/T 47746-2026 区块（标准号 + 4 能力点 + 免责小字），且不含「已通过…认证 / 无缝接管」。执行点 = corporate-home.test.tsx「renders GB/T 47746-2026 遵循国家标准区块」', '判据 5·视觉口径：四页渲染结果的 innerHTML 不含 from-blue-600 / to-indigo-800（旧的通用蓝色渐变模板）。执行点 = 四个页面测试文件各自的「视觉口径」用例', '判据 6·文案口吻（issue #6326 新增）：四页渲染文本不得出现 AI 口语词表（打理 / 管住 / 接住 / 折腾 / 摊开 / 跑完 / 直说 / 兜底 / 一句话 / 问一句 / 谁都不会 / 把时间还给 / 说了算 / 答一遍 / 先说说）。词表单一源 = frontend/admin-web/tests/unit/pages/copy-voice-banlist.ts。执行点 = 四个页面测试文件各自的「文案口吻」用例 + corporate-home.test.tsx 的「判别力自证」（词表必须命中已知口语样本，防空断言）', '判据 7·品牌称呼反回流（issue #6525，**类级元守卫**）：四个前端包**生产源码的代码面**不得出现旧称呼（米宝 / 小布 / 米高；`米高` 的计量义「2.7 米高窗」豁免、服务端协议标签 `[米宝解读]` 豁免），且新称呼（观星台 / 黄金策 / 元元）在关键落点**正向存在**；守卫自带判别力自证（字符串命中判红 / 计量义不假红 / 注释面不假红）。执行点 = tests/unit_ci_workflows/test_positioning_copy_terms.py 的 `test_old_agent_names_do_not_come_back_in_code_face` / `test_new_agent_names_are_present_at_key_surfaces` / `test_agent_name_guard_discriminating_power`', '🔴 红证（改前实测，2026-10-04）：把这 6 个源文件（四页 + 导航 + 页脚）替换回 origin/main 版本后跑本用例的 5 个测试文件 ⇒ **28 failed / 58**；恢复后 **58 passed**。复算命令（在 `frontend/admin-web` 目录下执行）= `npx vitest run --dir tests/unit/pages corporate-home.test services.test corporate-about.test corporate-contact.test` + `npx vitest run --dir tests/unit/components CorporateFooter`（两条合计 52 + 6 = 58；写法用 `--dir` + 文件名过滤，避免在文档里留下包内相对路径字面量 —— M4 只认仓库根相对路径，包内路径会被判成失效路径）'],
    skip_reason='[backend-contract] 纯前端公开页面（无 LLM 行为）：由 vitest 验证；页面级视觉另有 Playwright 截图 + 多模态读图一轮（migao-dev-flow §15.7 口径），不进入 agent-eval 冒烟',
    tags=['ui', 'homepage', 'corporate', 'copy-truthfulness', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端页面用例：前置 = `(corporate)` 四页源码与 5 个 vitest 文件同时存在、且被 vitest 正常收集；前置由测试自身持有（页面文件缺失 / 改名 / 选择器被摘即直接红，不表现成「agent 不干活」），不依赖共享夹具 ⇒ agent-eval 栈不跑它',
)

# ── UI-083 [NORMAL] 右上角用户卡片「点击外部收起」回归修复（issue #6339）：fixed 遮罩落在 backdrop-blur 祖先内 ⇒ 只盖住顶栏 56px；改文档级 mousedown + 类级不变式「fixed 不得落在生成包含块的祖先内」（源: cases/ui.yml）──
_CASE_UI_083 = EvalCase(
    id='UI-083',
    legacy_id='',
    title='右上角用户卡片「点击外部收起」回归修复（issue #6339）：fixed 遮罩落在 backdrop-blur 祖先内 ⇒ 只盖住顶栏 56px；改文档级 mousedown + 类级不变式「fixed 不得落在生成包含块的祖先内」',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['右上角用户信息展开后，点击其他任意区域要能收回去，现在是不行，优化下（用户 2026-10-05 逐字）'],
    expectations=['direct_reply'],
    data_checks=['展开用户卡片后，`mousedown` 落在卡片容器之外（页面任意区域）⇒ 卡片收起；落在卡片内部 ⇒ **不**收起。执行点 = `frontend/admin-web/tests/unit/components/Header.test.tsx` 的两条 #6339 用例（判别力：修复前跑该文件 ⇒ `expected document not to contain element, found <button` 失败，卡片仍在文档里）', '类级不变式（本单新增）：`fixed` 元素不得出现在带**生成包含块**类的 JSX 祖先内（`backdrop-blur*` / `filter` / `transform` / `translate-*` / `scale-*` / `rotate-*` / `will-change-*` / `perspective-*` / `contain-*`）—— 此时 `fixed` 的 `inset-0` 相对的是**祖先盒子**、不是视口。执行点 = `frontend/admin-web/tests/unit/lib/fixed-containing-block.test.ts`（6 条：检出面非空 + 真语料零违规 + 4 条判别力自证/对照）', '🔴 红证（改前实测，2026-10-05，**注入式**）：把 `frontend/admin-web/src/components/layout/Header.tsx` 换回 `origin/main` 版本（注入自证 = 该文件 `fixed inset-0` 遮罩 1 处、`addEventListener` 0 处）⇒ 两个测试文件 **2 failed / 55 passed**；具名读数 = 实例判据 `expected document not to contain element, found <button` + 类级判据 `["frontend/admin-web/src/components/layout/Header.tsx 的遮罩行 ← 祖先 backdrop-blur-sm"] to deeply equal []`；恢复后 **57 passed**（注入方式与复算命令见 PR body）。复算命令（在 `frontend/admin-web` 目录执行；写法用 `--dir` + 文件名过滤，**避免在用例库里留下包内相对路径字面量** —— 机器判据 `tests/unit_ci_workflows/test_recomputable_command_paths.py` 只认仓库根相对路径）= `npx vitest run --dir tests/unit/components Header.test` + `npx vitest run --dir tests/unit/lib fixed-containing-block.test`'],
    skip_reason='[backend-contract] 纯前端交互 + 静态不变式：由 vitest 验证；jsdom 不做布局（命中测试类缺陷的机器判据是**静态 AST**）⇒ 真实浏览器另按 migao-dev-flow §15.7 跑一轮 Playwright 截图 + AI 读图，不进入 agent-eval 冒烟',
    tags=['ui', 'header', 'user-card', 'outside-click', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端用例：前置 = `frontend/admin-web/src/components/layout/Header.tsx` 与两个 vitest 文件同时存在、且被 vitest 正常收集；前置由测试自身持有（文件缺失 / 改名即直接红，不表现成「agent 不干活」），不依赖共享夹具 ⇒ agent-eval 栈不跑它',
)

# ── UI-084 [NORMAL] B 端黄金策回复富文本渲染 — admin-web 软换行不折段 + bmini 粗体/列表不裸符号（用户实测截图，C 端 UI-042 的同族补课）（源: cases/ui.yml）──
_CASE_UI_084 = EvalCase(
    id='UI-084',
    legacy_id='',
    title='B 端黄金策回复富文本渲染 — admin-web 软换行不折段 + bmini 粗体/列表不裸符号（用户实测截图，C 端 UI-042 的同族补课）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-05 实测截图 + 逐字：「这个回复是不是没排版」—— 黄金策 capabilities 能力清单（每行一条、末尾单个换行）在 admin-web 聊天气泡里被折成一整段无分段长文；同句文案在小程序端则是 `**` 与 `- ` 裸符号'],
    expectations=['direct_reply'],
    data_checks=['判据 1·admin-web 软换行：frontend/admin-web/src/components/chat/MessageList.tsx 的 ReactMarkdown 挂 remark-breaks —— 段落内 3 个换行 ⇒ 3 个 <br>（改前实测 0 个）、空行分段 ⇒ 2 个 <p>、**强调** 仍走 <strong>、行内单个 * 不被当强调吞掉。执行点 = frontend/admin-web/tests/unit/components/chat-soft-breaks.test.tsx', '判据 2·bmini 富文本：frontend/bmini-app/src/utils/richText.ts 的 parseRichText（成对 **x** ⇒ bold 段、未闭合 ** 原样保留 = 流式安全、单个 * 不误吞、- 与 • 开头 ⇒ bullet、空行保留）+ frontend/bmini-app/src/components/chat/MessageBubble.tsx 按行渲染（.message-bubble__line / --bullet / --empty / __text-strong；DOM 文本零字面 **）。执行点 = frontend/bmini-app/tests/chat-rich-text.test.ts 与 frontend/bmini-app/tests/chat-rich-text-render.test.tsx', '🔴 红证（改前实测，migao-dev-flow §28.1 出口① 临时反转）：把两端渲染文件换回 origin/main 版本再跑 ⇒ admin-web 4 条里 1 条红（<br> 实测计数 0 / 期望 3）；bmini 13 条里 3 条红（.message-bubble__line 零命中 / 期望 4）。复算 = 在 frontend/admin-web 跑 npx vitest run tests/unit/components/chat-soft-breaks.test.tsx、在 frontend/bmini-app 跑 npx jest tests/chat-rich-text-render.test.tsx（覆盖前先取 origin/main 版本：git show origin/main:<仓库相对路径>）'],
    skip_reason='[backend-contract] 纯前端渲染由 vitest / jest 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'chat', 'rich-text'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-126 [NORMAL] 手机端（B 端黄金策 / C 端元元）助手消息的 **GFM 表格**渲染 —— 表格成组件（窄屏可横滑 / 表头-数据行逐格 / 列数按分隔行）+ PC 端同族回归判据（用户 2026-10-18 手机端实测：一排 `|---|`）（源: cases/ui.yml）──
_CASE_UI_126 = EvalCase(
    id='UI-126',
    legacy_id='',
    title='手机端（B 端黄金策 / C 端元元）助手消息的 **GFM 表格**渲染 —— 表格成组件（窄屏可横滑 / 表头-数据行逐格 / 列数按分隔行）+ PC 端同族回归判据（用户 2026-10-18 手机端实测：一排 `|---|`）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-18 逐字：「手机端的黄金策返回的表格样式没有正常渲染，还是原声markdown」（原声 = 原生 / raw）；同一句里要求「顺便把pc端的也一起检查下」', '同一轮的 DB 证据（session_messages，session sess_742201cbf83f4f58）：assistant 正文逐字含 `| 工单号 | 关联订单 | 客户 | 类型 | 状态 | 优先级 | 创建时间 |` 与 `|---|---|---|---|` —— 黄金策的清单类回复大量使用 GFM 表格，手机端把这排竖线原样上屏'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**解析口径（B/C 两端同口径）**：表头行 + 分隔行（列数一致）⇒ 一个 table 块（header / align / rows 逐值）；列数按分隔行定（数据行缺格补空、多格截断）；单元格内 `**粗体**` 仍解析；空行结束表格；首尾竖线可省略。执行点 = frontend/bmini-app/tests/chat-rich-text-table.test.ts（9 条）与 frontend/mini-app/tests/message-bubble-table.test.tsx', '判据 2·**流式安全负控**：只有表头、分隔行还没到 ⇒ 仍是普通文本（不闪半张表）；普通句子里的 `a | b` 不判成表格；**揭示期（打字机逐字中）尾部未成表的行先不画** —— 表头到了、分隔行没到 ⇒ DOM 里没有裸 `|`（旧形态会闪一两百毫秒裸管道符）。执行点 = 同上两个文件 + frontend/bmini-app/tests/chat-typewriter.test.tsx 判据 ⑦', '判据 3·**渲染**：`.message-bubble__table` 在场、DOM 文本零字面 `|` / `---`；表头 3 格 + 数据行 N 行且列数不错位；包在 `scrollX` 容器里（窄屏可横滑）；有表格的气泡放宽到 94%。执行点 = frontend/bmini-app/tests/chat-table-render.test.tsx（6 条）+ frontend/mini-app/tests/message-bubble-table.test.tsx', '判据 4·**PC 同族核查**（用户要求「顺便检查 PC」）：admin-web 走 react-markdown + remark-gfm ⇒ 同一段表格渲染出 `<table>` / `<th>` / `<td>`，且 remark-breaks 在场时仍成表（不折成 `<br>` 裸文本）、对齐标记不错位。执行点 = frontend/admin-web/tests/unit/components/chat-markdown-table.test.tsx（5 条）', '判据 5·**类级元守卫（两端同口径）**：同一组语料（含单列表格）喂给两端解析器，输出必须**逐值相等**（`toEqual`），且语料自证「lines 与 table 两种块都出现」（防两边都空 ⇒ 相等假绿）。判据 = frontend/mini-app/tests/chat-rich-text-parity.test.ts（3 条；放在 C 端腿里跑 —— 避免 bmini 腿跨目录依赖 C 端源码而污染本地门禁矩阵的触发面）。判别力自证：只改 C 端一处口径（单列表格判定加 `header.length > 1`）⇒ 该条当场红（`1 failed / 2 passed`）；还原 ⇒ 3 passed。这条防的正是本缺陷的**类**：两份本地实现「一端修、一端漏」（UI-042 漏 B 端 → #6346；#7235 若只修 B 端则 C 端继续裸奔）。另有**接线普查**类级守卫 tests/unit_ci_workflows/test_chat_richtext_surface_guard.py 判据 2：每个小程序气泡包必须引用 `parseRichContent` 且渲染 `message-bubble__table`（摘掉表格组件 ⇒ 红）', '🔴 红证（改前实测，migao-dev-flow §28.1 出口① 临时反转）：把两端实现退回 origin/main（`git stash push -- src/utils/richText.ts src/components/chat/MessageBubble.tsx`，在 frontend/bmini-app 下）⇒ 表格两条执行点 **2 suites failed / 5 failed / 1 passed**（`chat-rich-text-table` 因 `parseRichContent` 不存在整 suite 失败；`chat-table-render` 的 ①③⑤⑥ 红、负控 ④ 仍绿）；恢复后两文件 **15/15 全绿**。PC 侧判别力自证：摘掉 `remarkGfm` ⇒ 判据 4 的 `<table>` 零命中当场红'],
    skip_reason='[backend-contract] 纯前端渲染（vitest / jest jsdom），不进 agent-eval 冒烟；服务端一字未改（表格是既有 LLM 输出形态，只改展示层）',
    tags=['ui', 'chat', 'rich-text', 'table', 'bmini'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="两端 jest 夹具自建消息对象（role='assistant' + 带表格的 content），PC 侧 vi.mock('@/store/chat') 注入消息、**不 mock** react-markdown（判据打在真实渲染管线上）",
)

# ── UI-085 [NORMAL] 岗位 × 侧边栏菜单：种子权限集 × menu.ts 三条件 ⇒ 可见项逐值相等（岗位矩阵）（源: cases/ui.yml）──
_CASE_UI_085 = EvalCase(
    id='UI-085',
    legacy_id='',
    title='岗位 × 侧边栏菜单：种子权限集 × menu.ts 三条件 ⇒ 可见项逐值相等（岗位矩阵）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-06 用户裁定「做全量」：把「岗位 × 页面」这一维跑完（此前只做过单一人设 admin 的 UI 冒烟与 403 页面守卫）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·岗位矩阵：6 个岗位的种子权限集（逐字写死于用例内）各自渲染出的可见项 key（**顺序敏感**）逐值相等 —— 客服 **10** / 销售 **10** / 财务 **8** / 知识编辑 **6** / 商品管理员 **10** / 运营 **19** 项。执行点 = frontend/admin-web/tests/unit/lib/menu-nav.test.ts 的 describe「岗位矩阵：role_permissions（种子）× menu.ts **两条件**」。🔴 **2026-10-17（issue #7087）计数改判的现取口径**：过滤条件由**三条降为两条**（`adminOnly` ∧ `permissionCode`；`briefingToggle` 机制连同「每日简报」菜单项已删）⇒ 与旧读数相比：客服 10→10（少「每日简报」1 项、但「经营看板」在，且它现在是清单**第 1 项**）、销售 9→**10**、财务 8→8、知识编辑 5→**6**、商品管理员 10→10、运营 19→19。**读数出处（两处独立同源）**：① 本人按 `parse_role_defaults(RegistrationService) ∪ parse_role_fallback(RoleService)` ∩ `parse_menu_ts_nodes(menu.ts)` 复算；② 与 `frontend/admin-web/tests/unit/lib/menu-nav.test.ts` 的 `ROLES[].expected` **逐项相等**（该文件的期望值是**独立写死**的，不由本用例反推）。', '判据 2·**两条件**组合：`adminOnly` ∧ `permissionCode` 的组合表驱动（真实菜单无人用 adminOnly ⇒ 用合成项取证；同文件既有 describe）。🔴 2026-10-17（issue #7087）：原「三条件」里的 `briefingToggle` **已随「每日简报」菜单项整维撤销**（`Menu item` 接口不再有该字段、`isItemVisible` 不再读它）⇒ 本判据的组合表**同批收窄为两条件**（撤销一维是**实现面的事实**，不是放宽门禁：任何仍在读 `briefingToggle` 的代码路径都会因字段不存在而当场红）。', '判据 3·🔴 **企业简报开关不再作用于侧边栏**（issue #7087 口径改判）：`briefingEnabled` 开关**只驱动经营看板上的结论卡**（`BriefingCard enabled=…`），**不再有任何菜单项受它影响** ⇒ 原「`briefingEnabled=false` 时「每日简报」不出现 / `true` 才出现」这条**已随菜单项撤销**，改为钉新形态：菜单元数据里不存在 `briefingToggle` 字段、`/briefing` 不是任何岗位可见项清单的成员（该 path 已无菜单节点）。', '判据 4·判别力自证：摘掉**非菜单码**（knowledge:manage）可见项不变；摘掉**菜单码**（product:list）必少「商品管理」「省料看板」两项', '🔴 红证（2026-10-24 本包实测，§28.1 出口① 临时反转）：把页面换回改前形态（`git show origin/main:frontend/admin-web/src/app/(dashboard)/stock-ledger/page.tsx`，md5 `e9d04bddbe5cce1c36e4748c1fc48b60` ≠ 新版 `7e1dcfa57d062e003b8337d08b2c9cb1`）⇒ 本包新增的 ⑨⑩⑪⑫⑬⑭ 六条**全红**（`Unable to find an element by: [data-testid="batch-row"]`），而流水 ①~⑧ **全绿** ⇒ 红只归因于本包判据；恢复新版（md5 一致）⇒ 14 条全绿。后端判据红证：把 `remainingPage` 的 `selectPage` 换成 `selectList` + 内存切片 ⇒ `StockBatchConsumptionServiceTest` 唯一红 = `remainingPageIsServerSidePagedAndSharesDerivation`（Tests run: 42, Failures: 1）；还原（md5 `84a263f1d2a7188493ff8b54c08e016c` 一致）⇒ 绿。复算（仓库根）：`npx --prefix frontend/admin-web vitest run frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx`；`cd backend/admin-api && ./mvnw -Dtest=StockBatchConsumptionServiceTest test`。'],
    skip_reason='[backend-contract] 纯前端纯函数（菜单过滤）由 vitest 验证；不依赖 LLM / 网络 / DB ⇒ 不进入 agent-eval 冒烟',
    tags=['ui', 'rbac', 'menu', 'permission-matrix', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置由测试自身持有：frontend/admin-web/src/config/menu.ts 与 src/lib/menu-nav.ts 同时存在且被 vitest 正常收集（缺文件 / 改名 ⇒ 直接红，不表现成「agent 不干活」）。🔴 2026-10-17（issue #7087）：`menu.ts` 的三个独立项数组（`standaloneHeadItems` / `standaloneTopItems` / `standaloneItems`）都必须被 `flattenMenu` 纳入过滤面 —— 最前席位（经营看板）漏进过滤面会让**所有**岗位的矩阵行当场红。',
)

# ── UI-086 [NORMAL] 入库单列表：表格列与状态药丸不得被压成竖排（th 全 nowrap + 横向逃逸口 + 复用 Badge 原语）（源: cases/ui.yml）──
_CASE_UI_086 = EvalCase(
    id='UI-086',
    legacy_id='',
    title='入库单列表：表格列与状态药丸不得被压成竖排（th 全 nowrap + 横向逃逸口 + 复用 Badge 原语）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-06 用户实测（附两张截图）：「入库单列表的状态样式展示不对，列的样式也有问题，要平铺开」—— 状态药丸「已过账」折成两行（已过 / 账）、表头「行数 / 总数量」折行'],
    expectations=['direct_reply'],
    data_checks=['判据 1·表头单行：入库单列表 9 个表头（含「行数 / 总数量」）各自的内容行盒数 = 1。执行点 = tests/e2e/specs/warehouse/inbound-orders-table-geometry.spec.ts「表头全部单行」', '判据 2·状态药丸单行：已过账 / 已作废 / 草稿三种状态的药丸内容行盒数 = 1（改前「已过账」= 2 行，药丸被压成 ~1 个汉字宽）。执行点 = 同文件「状态药丸单行」', '判据 3·**逐单元格**单行：两行数据 × 9 个单元格（含供应商 / 仓库 / 单号 / 日期 / 金额 / `1 / 90`（**三文本节点**单元格）/ 聚合批次号「PC-… 等 2 个」/ 状态 / 操作）行盒数 = 1。执行点 = 同文件「每一列的内容都单行」', '判据 4·几何护栏：表格祖先里存在 `overflow-x: auto|scroll` 逃逸口（只有 nowrap 没有逃逸口 ⇒ 表格被外层 `overflow-hidden` **裁切** = 看不见的假绿），且最近一个 `overflow-x: hidden` 祖先的 `scrollWidth-clientWidth` ≤ 1px（右侧列没被裁掉）。执行点 = 同文件「横向逃逸口存在 + 卡片不裁切表格」', '判据 8·**逃逸口真的可滚 + 最右两列可达**（窄视口 1280）：容器的 `scrollWidth > clientWidth`（只断言「祖先里有个 overflow 容器」不够 —— 被 `overflow-hidden` 裁掉时同样有祖先），滚到底后状态药丸与「详情」按钮 `toBeInViewport()`（⚠️ `toBeVisible()` **不判视口相交**，滚动容器外的元素照样 visible）。执行点 = 同文件「窄视口（1280）：逃逸口真的可滚…」', '判据 5·宽视口同形态：1440×900 下表头与药丸同样单行。执行点 = 同文件「宽视口（1440×900）同样」', '判据 6·类级元守卫（每一次 PR 都能拦）：`src/app/**` 与 `src/components/**`（`src/components/ui/**` 除外 —— 共享原语面由 UI-056 守）里，凡**有 `<th>` 的表格**必须「每个 th 带 `whitespace-nowrap`」且「表格落在横向逃逸口里」（`overflow-x-auto` 或 `overflow-auto`），凡**手写药丸**（`inline-flex` ∧ `rounded-full` ∧ `border`）必须带 `whitespace-nowrap`；未登记即红、台账与现取缺陷集合**双向相等**（修好必须删死条目并下调基线）。**边界（有意，且被自证钉住）**：静态规则**只裁表头**，单元格（td）由判据 3/8 在效果层守 —— 「单元格能不能折行」取决于数据与列语义（`src/components/ui/Table.tsx` 的原语也只给表头 nowrap），静态判不了。执行点 = frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts', '判据 7·判别力自证：内存注入八种形态（无 nowrap 无逃逸口 ⇒ 红 / 只加逃逸口 ⇒ 仍红 / 两条都齐 ⇒ 绿 / `<td>` 当表头的单据表格 ⇒ 不在面内 / 手写药丸缺 nowrap ⇒ 红 / 补上 ⇒ 绿 / **th 全 nowrap 而 td 未 nowrap ⇒ 不红（有意边界，被这条断言钉住）** / `overflow-auto` 也算逃逸口）各自判定正确。执行点 = 同文件「判别力自证」', '🔴 红证（改前实测，2026-10-06，1280×800）：表头「行数 / 总数量」= **2 行**、状态药丸「已过账」= **2 行**、单元格「1 / 90」与聚合批次号折行、`overflow-x-auto` 逃逸口**不存在**（最近祖先 overflow-x = hidden）⇒ 判据 1/2/3/4 同时红（**5 failed / 1 passed**，那 1 条是 auth-setup）。复算命令（在 `tests` 目录下执行）= `npx playwright test --project=web inbound-orders-table-geometry --reporter=list`', '🔴 红证（类级守卫侧，改前实测）：改前基线 26 张表格 / 6 个手写药丸（含入库单列表那一处）；修复后若不同步删条目 ⇒ 守卫由「台账不得腐坏」判红并**具名**报出死条目。复算命令（在 `frontend/admin-web` 目录下执行）= `npx vitest run --dir tests/unit list-table-nowrap-guard`'],
    skip_reason='[backend-contract] 纯前端布局几何由 Playwright E2E（tests/e2e/specs/warehouse/inbound-orders-table-geometry.spec.ts）+ admin-web vitest（tests/unit/list-table-nowrap-guard.test.ts）覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'layout', 'geometry', 'nowrap', 'table', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置由判据自身持有：列表数据由 spec 自己 mock `**/api/admin/inbound-orders**`（非空 4 行，覆盖 posted/cancelled/draft），登录由 E2E_MOCK_AUTH 夹具持有；页面渲染不出第一行时判据直接红（不表现成「agent 不干活」）',
)

# ── UI-087 [NORMAL] 库存明细页（/stock-ledger）：流水可见 + 成本 NULL≠0 + 不重算（见证行）+ 商品两步筛选（源: cases/ui.yml）──
_CASE_UI_087 = EvalCase(
    id='UI-087',
    legacy_id='',
    title='库存明细页（/stock-ledger）：流水可见 + 成本 NULL≠0 + 不重算（见证行）+ 商品两步筛选',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-06 用户提问「我在哪里查批次的剩余布料？我们是不是缺了库存明细这个功能」，追问后裁定「直接做这个页面」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·流水可见：时间 / 货号·SKU / 变动 / 变动前 / 变动后 / 原因 / 单据号 / 操作人 / 成本金额九列逐值渲染（入库过账行：+50 / 0 / 50 / 入库过账 / RK-20261001-0001 / zhangsan / ¥1240.00）。执行点 = frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx', '判据 2·成本 NULL ⇒「未知」（**不得**回落成 ¥0.00 / 0 —— 真值源 backend/admin-api/src/main/java/com/migao/admin/entity/StockLedger.java 的 javadoc 逐字：「NULL = 该次变更发生时成本未知（存量行全部为 NULL，不伪造）」）；数量 NULL ⇒「-」（与「成本未知」区分：一个读不出、一个没有数）。执行点同上', "🔴 判据 3·不重算（**见证行**）：服务端下发 delta '-2.0' / costAmount '74.40'，而 afterQty−beforeQty = -6.0、|delta|×unitCost = 3.00 ⇒ 页面必须渲染服务端的 -2 / ¥74.40（页面若自算 ⇒ 本判据红）。执行点同上", '判据 4·未知 reason **原样显示**（不吞成空白 —— 读不出 ≠ 没有原因）；并含**类级**判据 ⑥：`StockLedger` 的每个 `REASON_*` 常量都必须有中文标签（服务端新增 reason 而前端未跟 ⇒ 具名红；反向陈旧也红）。执行点 = frontend/admin-web/tests/unit/lib/stock-ledger.test.ts 与 pages/stock-ledger.test.tsx', '判据 5·商品**两步筛选**：先 productApi.getProducts({keyword}) 拿 productId，再按 productId 查流水；**绝不把关键词发给 /api/admin/stock-ledger**（该端点没有关键词参数，传了会被服务端静默丢弃 = 拿全量冒充过滤结果）。执行点 = frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx 与 frontend/admin-web/tests/unit/lib/stock-ledger-api.test.ts', '判据 6·单据号筛选 / 重置 / 空态「暂无库存流水」/ 读面失败给出可行动话术（含「权限」）。执行点 = frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx', '🔴 红证（改前实测，2026-10-06，migao-dev-flow §28.1 出口① 临时反转）：三个测试文件在**实现落码之前**跑 ⇒ 3 failed（页面模块不存在 ⇒ 动态导入失败；菜单节点/面包屑/图标均未登记）。复算 = 在 frontend/admin-web 跑 npx vitest run tests/unit/lib/stock-ledger-api.test.ts tests/unit/lib/stock-ledger-menu-isomorphic.test.ts tests/unit/pages/stock-ledger.test.tsx（覆盖前先取 origin/main 版本：git show origin/main:frontend/admin-web/src/app/(dashboard)/stock-ledger/page.tsx 应为「不存在」）'],
    skip_reason='[backend-contract] 纯前端页面与纯函数由 vitest 验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'stock', 'ledger', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置由测试自身持有：frontend/admin-web/src/app/(dashboard)/stock-ledger/page.tsx 与 frontend/admin-web/src/lib/stock-ledger.ts 同时存在且被 vitest 正常收集（缺文件 / 改名 ⇒ 直接红，不表现成「agent 不干活」）',
)

# ── UI-088 [NORMAL] 库存明细菜单三处同构 + 权限同码 + 图标注册 + 面包屑（/stock-ledger）（源: cases/ui.yml）──
_CASE_UI_088 = EvalCase(
    id='UI-088',
    legacy_id='',
    title='库存明细菜单三处同构 + 权限同码 + 图标注册 + 面包屑（/stock-ledger）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-06 用户裁定「直接做这个页面」—— 新页面必须有侧边栏入口，否则用户最初那句「我在哪里查」没有被回答'],
    expectations=['direct_reply'],
    data_checks=['判据 1·三源同构：frontend/admin-web/src/config/menu.ts 的 stock-ledger 节点、backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java 的 prLedger（必须挂进 inventory-center 组、不得留在 production-center）、backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java 的 menuItem("stock-ledger", "库存明细", "/stock-ledger")（必须落在 inventoryChildren 装配区间）三处逐字一致。执行点 = frontend/admin-web/tests/unit/lib/stock-ledger-menu-isomorphic.test.ts', '判据 2·权限不放宽：菜单码 == backend/admin-api/src/main/java/com/migao/admin/controller/StockLedgerController.java 的 @RequirePermission ⇒ 逐字 product:list（不新造码：新码今天没有任何岗位持有 ⇒ 节点对所有人不可见，#4203 同族坑）。执行点同上', '判据 3·图标注册：ClipboardList 既被 import 又登记进 menuIconMap（漏注册**不报错**，只会静默回落 BarChart3）。执行点同上', '判据 4·面包屑：frontend/admin-web/src/components/layout/Header.tsx 的 /stock-ledger 条目 =「仓储与物料 / 库存明细」（末项 == 侧边栏菜单名，§15.2 / 判据 PG-038）。执行点同上', '🔴 红证（改前实测，2026-10-06，§28.1 出口① 临时反转）：实现落码前该文件 4 条全红（三源均无该节点 ⇒ 断言 undefined/false；面包屑条目 undefined）；落码后 4 passed。复算 = 在 frontend/admin-web 跑 npx vitest run tests/unit/lib/stock-ledger-menu-isomorphic.test.ts'],
    skip_reason='[backend-contract] 纯静态文本守卫（不启动 Spring，因而不会被「后端没跑起来」掩盖）由 vitest 验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'rbac', 'menu', 'permission-matrix', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置由测试自身持有：三份菜单源与 frontend/admin-web/src/components/layout/Header.tsx 同时存在（缺文件 ⇒ readFileSync 直接抛错，不表现成「agent 不干活」）',
)

# ── UI-089 [NORMAL] 库存明细页的「批次余量」视图（/stock-ledger）：每卷剩余米数可见 + 不重算（见证批次）+ **默认分页列表**（不必先选商品）+ 两本账不串（源: cases/ui.yml）──
_CASE_UI_089 = EvalCase(
    id='UI-089',
    legacy_id='',
    title='库存明细页的「批次余量」视图（/stock-ledger）：每卷剩余米数可见 + 不重算（见证批次）+ **默认分页列表**（不必先选商品）+ 两本账不串',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-06 用户逐字：「库存明细还是缺乏单批次的剩余量，比如1卷=67米，经过加工裁剪后应该有个剩余米数」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·批次余量可见：视图② 一行 = 一个批次，八列逐值渲染（批次号 / 货号·SKU / 缸号 / 入库单 / 入库米数 / 已消耗 / **剩余米数** / 收货日期）；缺值不空白（缸号 null ⇒ 「—」）；余量 0 的批次**照样列出**（用尽本身是要看的信息）。执行点 = frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx 的「⑨ 每卷一行…」', "🔴 判据 2·**不重算**（见证批次）：服务端下发 inboundMeters '67.0' / consumedMeters '20.0' / remainingMeters '46.5'，而 67−20 = **47** ⇒ 页面必须渲染服务端的 46.5，渲染里**不得出现 47**（页面若自己减一遍 ⇒ 本判据红）。余量是**派生值**，单一真值在服务端。执行点 = 同文件「⑩ 不重算…」", '判据 3·**默认分页列表**（issue #7604，用户 2026-10-24 逐字「这里是不是应该默认给个分页查询展示当前批次库存」）：切到批次视图 ⇒ **不选商品就查第 1 页**（`batchStockApi.batchesPage` 收到 `page=1` / `size=20`），首屏直接是可读的表 + 「共 N 条」+「第 1 / y 页」；🔴 旧全量端点 `batchStockApi.batches` **一次都不调用**（那才是一次拉全量）。红证：把页面改回「必须先选商品」⇒ 本判据红（零请求 / 无批次行）。执行点 = 同文件「⑨ 默认就展示…」「⑪ 只发分页读面…」', '判据 3b·**翻页与关键字**：点「下一页」⇒ 请求带 `page=2`；批次关键字（批次号 / 缸号 / 入库单号 / 货号）交给**服务端**（`keyword=` 下传、页码重置 1、前端不自己过滤）；商品是**可选**收窄（选中后同一分页读面带 `productId`）。执行点 = 同文件「⑫ 翻页与关键字…」「⑬ 商品是可选收窄…」', '判据 4·两本账**不串** + 失败可行动：批次视图下不渲染 SKU 流水行（`stock-ledger-row` 数 = 0）、不渲染只对流水有意义的「业务单据号」筛选；批次读面失败 ⇒ `batch-error` 话术含「权限」且无批次行、计数印「共 — 条」（读不到 ≠ 共 0 条）。执行点 = 同文件「⑭ 两个读面不串…」', '判据 5·**类级**（由 #6398 的元守卫自动覆盖，无需本包另写）：本包新增的批次表必须「每个 th 带 `whitespace-nowrap`」且「表格在横向逃逸口里」—— 违反即具名红。执行点 = frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts（每次 PR 的 admin-web 单测面真跑）', '判据 6·**效果层**（真实浏览器 + 真实布局，jsdom 判不了的那一半）：每卷一行可见（46.5 / 0 / 120 三条读数）+ 表头八列**全部单行**（列不许被压成竖排，同 #6398 那一族）+ 卡片不裁切 + 1280 下 8 列直接装得下（最右「剩余米数」列无需横滚即在视口内）+ 1024 下装不下则**滚到底必达**（实测读数：表 813px / 容器 684px / overflow-x=auto）+ **不选商品就发分页请求**（`page=1&size=20` 真下传、旧 `/batches` 零调用、首屏有表与「共 N 条」）。执行点 = tests/e2e/specs/warehouse/stock-ledger-batch-view.spec.ts', '🔴 红证（改前实测，2026-10-06，migao-dev-flow §28.1 出口① 临时反转）：把`批次余量`视图整段从页面移除（= 改前形态，用 `git show origin/main:<path>` 换入并自证 md5 不同）⇒ 单测 ⑨⑩⑪⑫ 四条**全红**（`Unable to find an element by: [data-testid="view-batch"]`），而原有 ⑧ 条**全绿** ⇒ 红只归因于本包新增判据；恢复 ⇒ 12 条全绿。复算（在 frontend/admin-web 目录下执行）= `npx vitest run --dir tests/unit/pages stock-ledger`；效果层复算（在 tests 目录下执行）= `npx playwright test --project=web --no-deps warehouse/stock-ledger-batch-view --reporter=list`'],
    skip_reason='[backend-contract] 纯前端页面与纯函数由 vitest 验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'stock', 'batch', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置由测试自身持有：frontend/admin-web/src/app/(dashboard)/stock-ledger/page.tsx 含 `批次余量` 视图（`data-testid=view-batch` / `batch-row` / `batch-remaining` / `batch-total` / `batch-page-info`）且测试 mock 了 `batchStockApi.batchesPage`（视图被删 / 改名 / mock 缺失 ⇒ 直接红，不表现成「agent 不干活」）',
)

# ── UI-090 [NORMAL] 订单详情打印收口成**单一入口**：任何状态（含已关闭 / 退款中）都只有一个「打印」，点开后选单据（销售单/加工单/报价单/发货单）先预览再打印（issue #6434 → #7544 改判）（源: cases/ui.yml）──
_CASE_UI_090 = EvalCase(
    id='UI-090',
    legacy_id='',
    title='订单详情打印收口成**单一入口**：任何状态（含已关闭 / 退款中）都只有一个「打印」，点开后选单据（销售单/加工单/报价单/发货单）先预览再打印（issue #6434 → #7544 改判）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「这几个打印按钮不要跟状态挂钩，允许任何状态都能进行打印这些单据，另外把按钮收拢到一个打印统一入口中？作业单区域也有两个按钮，应该都统一收口到打印中，点击打印后可以选择不同的单据预览再进行打印」（2026-10-23 用户逐字，附两张截图：状态卡右侧四个打印按钮、作业单区块右侧「复制全部 | 打印」）'],
    expectations=['direct_reply'],
    data_checks=['改判说明（写清为什么反向）：issue #6434 曾把四个打印按钮收敛成「状态 × 可打单据」矩阵并给 待付款/待发货/生产中 补入口；2026-10-23 用户裁定**打印不该跟状态挂钩**、且要**收拢成一个入口**。旧矩阵的两个可见病灶：① `closed` / `refund` 状态**一张单据都打不出来**；② 四个按钮常驻把状态卡操作行铺满。⇒ 新形态 = 页面级唯一「打印」入口（与状态无关）+ 打印层内单据标签选择。', '判据 1·🔴 **任何状态都有且只有一个入口**（表驱动 7 条）：待付款 / 待发货 / 生产中 / 已发货 / 已完成 / 已关闭 / 退款中 —— 每个状态断言「以『打印』开头的按钮**恰好 1 个**」（改前：前五个状态分别 1/3/3/4/4 个，后两个 0 个）。执行点 = frontend/admin-web/tests/unit/pages/order-detail.test.tsx::「打印不跟订单状态挂钩（issue #7544）…」。', '判据 2·🔴 **入口 → 预览 → 选单据 → 打印**（接线）：点「打印」打开打印层（此时**不出纸**）⇒ 四份单据各一签（文案取 `PRINT_TARGET_SPECS`）、默认选中销售单（纸型读数 241mm × 140mm）⇒ 点「加工单」标签后纸型变 210mm × 297mm 且**仍未出纸** ⇒ 点「打印」才 `window.print()` 一次。另有一条「已关闭订单也能打开打印层」（旧矩阵下这是死路）。执行点 = 同文件::「点「打印」→ 在预览层里换单据 → 打印…」/「已关闭订单也能打开打印层」。', '判据 3·**选择器本体**（组件级）：frontend/admin-web/tests/unit/components/PrintDocPreview.test.tsx::「打印层的单据选择器（issue #7544）」三条 —— 一单一签且纸型读介质矩阵、点标签只回调 `onSelect` 不触发打印、不传 `docs` 时没有选择器（发货页 / 加工单生产页形态不变）；frontend/admin-web/tests/unit/lib/print-doc.test.tsx::「`selectPreview` 只换预览、不动打印目标」。', '判据 4·**类级元守卫**（让「再加一个打印入口」进不来）：页面不得有状态矩阵、入口恰好一处且不在 `StatusSection`、不手写单据名、选择器接线齐全且清单每项都是真实 target、作业单区块不得再有打印入口。判据 = tests/unit_ci_workflows/test_order_print_entry_matrix.py（5 条真语料 + 7 条注入式判别力自证，含「只加注释 ⇒ 不红」的对照读数），用例 MC-085。', '判据 5·**真浏览器**：tests/e2e/specs/orders/print-preview.spec.ts 的「已关闭的单子照样能打开打印层、能选单据、能出纸」—— 抓 `beforeprint` 那一刻的 `data-print-target`，断言换到加工单后出纸的正是 `processing`（纸型/目标不是默认那份）。', '🔴 **覆盖边界（照实登记）**：① 单测只判「入口唯一 / 可打开 / 选中的单据与纸型对」，**不判**真机点击与真纸输出（由 Playwright 那条 + 现场承接）；② 单据的**展示顺序**（销售单 → 加工单 → 报价单 → 发货单，用得最多的在前）是产品口径，判据只钉「四份都在」；③ 作业单区块的「复制全部」**有意保留**（文本通道：作业单文本发加工方 / 贴 Excel；塞进打印层会把一键复制变成三步）—— 本用例只收口**打印**通道。'],
    skip_reason='[backend-contract] 纯前端入口面（零 LLM、零网络、零后端契约改动：入口只是前端可见面的收口，打印仍走 #5914 的共享入口 usePrintDoc；端点 / 权限 / 纸型矩阵一字未动），不进入 agent-eval 冒烟',
    tags=['ui', 'order', 'print', 'single-entry', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端入口面：前置由单测自建 —— frontend/admin-web/tests/unit/pages/order-detail.test.tsx mock 了 `@/lib/api` 的 `orderApi.getOrder`（逐状态给 status）与组件桶；页面的 `ORDER_PRINT_DOCS` 清单与唯一入口锚点 `data-testid="order-print-entry"` 是判据的抓手。文件缺失 / 清单被删 / 锚点漂移 ⇒ 判据当场 fail-closed 判红（不会表现成「agent 不干活」）；agent-eval 栈不跑它',
)

# ── UI-091 [NORMAL] 订单详情打印入口 × 订单状态矩阵：待付款出报价单；待发货/生产中出报价单+加工单+销售单；已发货/已完成四单齐全；已关闭零入口（issue #6434）（源: cases/ui.yml）──
_CASE_UI_091 = EvalCase(
    id='UI-091',
    legacy_id='',
    title='订单详情打印入口 × 订单状态矩阵：待付款出报价单；待发货/生产中出报价单+加工单+销售单；已发货/已完成四单齐全；已关闭零入口（issue #6434）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「之前让你设计过打印销售单，报价单等功能，我在订单详情中没有看到打印功能」（2026-10-06 用户报障；追问确认场景 = 待发货订单 / merchant.migaozn.com）；用户同时裁定要覆盖的状态 = 待付款（报价单先行）+ 待发货 + 生产中（车间要加工单、随货要销售单）'],
    expectations=['direct_reply'],
    data_checks=['病根读数（现取 `origin/main`）：订单详情页的四个打印入口只在 `status === \'shipped\'` 与 `status === \'completed\'` 两个分支里渲染；`pending_payment` / `pending_shipment`（含 `producing`）分支里**一个打印按钮都没有**，而 `CHANGELOG` 的 #5651 条目声称的是「在「待发货」与「已完成」两个状态区」⇒ **声称与实现不符**（`git log -S 打印销售单` 只有一个提交 = 引入提交 #5669）。复算 = `git show origin/main:frontend/admin-web/src/app/\\(dashboard\\)/orders/\\[id\\]/OrderDetail.tsx | grep -n "打印销售单\\|pending_shipment"`。', '判据 1·🔴 **状态 × 入口矩阵**（表驱动）：待付款 ⇒ 只有「打印报价单」（且不得出现发货单/加工单/销售单）；待发货 ⇒ 报价单 + 加工单 + 销售单（**不得**出现发货单：未发货谈不上补打）；生产中（`producing`）⇒ 同待发货；已发货 / 已完成 ⇒ 四单齐全；已关闭 ⇒ 零入口。执行点 = frontend/admin-web/tests/unit/pages/order-detail.test.tsx::「打印入口矩阵：…」六条（`it.each`）。', '判据 2·🔴 **红证（改前实测，`migao-dev-flow` §28.1 出口①）**：判据 1 先在 `origin/main` 上跑 ⇒ **3 红 3 绿**（红 = 待付款/待发货/生产中；绿 = 已发货/已完成/已关闭）—— 红只归因于本包缺口，同时证明矩阵**不是空断言**；落实现后 ⇒ 该文件 46/46 全绿。复算（在 frontend/admin-web 目录下执行）= `npx vitest run --dir tests/unit/pages order-detail -t 打印入口矩阵`。', '判据 3·**类级元守卫（唯一声明处）**：① 矩阵覆盖 `OrderStatus` 全部取值（新增状态忘登记 ⇒ 红）② 四个「有单据可出」的状态非空（清空 ⇒ 红）③ 页面代码里不得再出现手写的 `打印发货单/报价单/加工单/销售单` 字面量（再抄一份 ⇒ 红）④ `<PrintActions>` 接线 ≥4 且定义只有一份。判据 = tests/unit_ci_workflows/test_order_print_entry_matrix.py（5 条真语料 + 5 条判别力自证，含「只加注释 ⇒ 不红」的对照读数）。', '判据 4·**文案单一真值**：按钮文案 = `打印${PRINT_TARGET_SPECS[target].title}`（与纸面自检层标题**同一份**），页面不手写字面量 ⇒ 改文案 / 新增单据只改 frontend/admin-web/src/lib/print-doc.ts 一处。'],
    skip_reason='[backend-contract] 纯前端入口面（零 LLM、零网络、零后端契约改动：矩阵只决定按钮渲染，打印仍走 #5914 的共享入口 usePrintDoc），不进入 agent-eval 冒烟',
    tags=['ui', 'order', 'print', 'entry-matrix', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端入口面：前置由单测自建 —— frontend/admin-web/tests/unit/pages/order-detail.test.tsx mock 了 `@/lib/api` 的 `orderApi.getOrder`（逐状态给 status）与组件桶；页面里的 `PRINT_TARGETS_BY_STATUS` 矩阵是判据的唯一真值源。文件缺失 / 矩阵被删 / 状态键漂移 ⇒ 判据当场红（不会表现成「agent 不干活」）；agent-eval 栈不跑它',
)

# ── UI-092 [NORMAL] 省料看板首屏重做：只讲「省了多少布 / 多少钱」（结论数字 + 几乎用完的批数趋势 + 省料明细）+ 内部口径词零上屏（issue #6430 原单；**2026-10-07 issue #6459 用户裁定整条改判**）（源: cases/ui.yml）──
_CASE_UI_092 = EvalCase(
    id='UI-092',
    legacy_id='',
    title='省料看板首屏重做：只讲「省了多少布 / 多少钱」（结论数字 + 几乎用完的批数趋势 + 省料明细）+ 内部口径词零上屏（issue #6430 原单；**2026-10-07 issue #6459 用户裁定整条改判**）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-06 逐字：「省料看板看不明白这里是什么意思，如果是新用户这么解释这些概念」「你需要重新设计整个页面布局，如何把这个省料的故事讲清楚明白，让用户能看懂逻辑和门道」「不单单是页面布局，还有核心功能如何表达出省料看板」'],
    expectations=['direct_reply'],
    data_checks=['🔴 **2026-10-07 整条改判（issue #6459，用户三张截图逐字）**：「省料看板为什么一定要加上切换后（采购入库）这种概念，让新用户如何理解，图中这种数据和概念毫无意义，这个功能只需要用数据和规则说清楚我们是如何省下多少布料，节省了多少成本即可」+「这么多废话文字留在页面上只会干扰用户」+「我们有个剩余0.2布料在仓库的数量趋势是不是就能说明问题了」。**整页形态 = 结论数字 + 趋势 + 明细**：① 首屏**两张省料结论卡**（`saving-metric-saved-meters` → 本期省下多少布；`saving-metric-saved-amount` → 本期省下多少钱；大数字取服务端 `comparison.*.current`、副行「累计」取服务端 `total`，后端未部署则大数字退回 `total`）；② **一张「几乎用完的布（剩余 ≤0.2 米）· 批数」趋势表**（服务端 `batchTrend`，列 = 几乎用完的批数 / 当期收进的批数 / 占比）；③ **默认收起的省料明细**（逐行 = 服务端值，合计行 = 服务端 `total`）；④ 默认收起的「口径与边界」。**更新形态的一条不减**：结论大数字与合计行仍是服务端原值（桩数据 55 / 77 / 99 三个数互不相等）。', '🔴 **2026-10-07 作废的旧判据（如实登记，不粉饰）**：`saving-headline` 结论条、门道卡因果链（`saving-causal-chain`）、术语词典（`saving-terms`）、`saving-metric-le-0-2` / `saving-metric-purchased` 两张指标卡、「两条指标必须并用」说明条、`saving-cohorts` 来源组对照表、`saving-batch-groups`（含异常优先排序与渐进披露）、`saving-trend` 单位产出表、`saving-period-axis-note` / `saving-trend-caveat` / 两腿同参 —— **全部随本次裁定退场**。它们**不是被藏起来**：`SavingBoardStory.test.tsx` 逐条断言这十个 testid 在整页里**一个都找不到**（把任一块写回页面 ⇒ 当场红）。', '🔴 **内部口径词零上屏（本单的核心新判据）**：`切换后` / `存量导入` / `来源未知`（= 服务端 `SavingMetricViews.cohortLabel` 的三个取值）**一个都不许出现**在整页渲染文本里 —— 夹具**故意**把 `cohortLabel` 设成内部口径（页面拿得到、但不许渲染），红证 = 把来源组对照表写回去 ⇒ 当场红；类级元守卫 = `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts` 形态③（扫 `src/app` / `src/components` / `src/lib`，豁免台账为空）。同批按类级固化修掉另一处同族形态 = `src/components/chat/BatchStockCard.tsx` 的「存量导入入库（单列）」（改说「开业时导入的老库存（单列）」）。', '🔴 **少废话（可判据化的那一半）**：首屏常驻文案 = 页头一句规则（`savedRule`）+ 趋势表一句（`batchTrendNote`），两者合计 **≤ 120 字**；折叠区条目 **≤ 7 条**。两条都是 `saving-board.test.ts` 的定点断言 —— 把门道卡那类散文加回来 ⇒ 当场红（红证机具另有一条把服务端分组标签搬回首屏的注入，实测 `1 failed / 27 passed`）。', '🔴 **口径不放宽的对照读数**：趋势**只含采购腿**（服务端 `batchTrend` 由 `batchGroups` 的 `purchase` 腿聚合）—— 真库夹具里存量在 2026-08 ⇒ 该期**整期缺席**（红证：并进全量来源 ⇒ 多一行、合计由 2 变 4）；页面**只调一条读面**（`board`；`trend` 调用次数恒 0）⇒ 旧「两腿不同参」漂移面结构性消失。', '🔴 判据·**门道可视**：门道卡含因果链（`saving-causal-chain`：排料省 ⇒ 剩得更多 ⇒ 只盯一个数会看反）与术语词典（`saving-terms`：公式米数 / 排料米数 / 省料米数 / 省料金额 / 来源组 / 批次余量 + 「占比按**批数**算」）；既有「两条指标必须并用」的措辞一条不放宽。', '🔴 判据·**环比词只来自服务端 verdict**：同一份夹具把 `verdict` 由 `worse` 改成 `better` ⇒ 文案必须跟着改口（写死「变好了」的前端过不了这条）；`le0_2Share.verdict = null` ⇒ 该行**只给两期数值、不给好坏词**（有意不给，#5144）。', '🔴 判据·**本期还没过完 ⇒ 不给方向**：`verdict = "partial"` ⇒ 文案写「本期还没过完，环比先不算」，且**不得**出现「变好/变差」（红证来源 = 2026-10-06 页面多模态验收实测：趋势区把「才过 6 天的 10 月」与整月 9 月比，打出「上期 13236.5 米 → 本期 220.5 米 · 变好了」）。', '🔴 判据·**异常优先 + 渐进披露**：「布剩在哪」按余量降序（**纯排序**），12 行默认只渲染 8 行且**余量最大的排第一**（不排序时它会被切掉 ⇒ 红）；点 `saving-batch-groups-toggle` 后最小余量的那行出现。', '🔴 判据·**合计行 = 服务端 total**：逐单省料表新增 `saving-saved-groups-total`，渲染 99 米 / 999 元（服务端合计腿），**不是**逐行求和 77 米 / 88.88 元 —— 判据 1（逐值相等、前端零算术）由此再加一道锁。', '🔴 判据·**新用户 5 问**：整页文本面必须答得出 ①省了多少 ②布还剩在哪、剩多少 ③比上期好还是坏 ④为什么两个指标要一起看 ⑤存量导入为什么单列（缺任一条即红）。', '判据·**两张表的时间轴说明 + 趋势分母警示**：`saving-period-axis-note`（收货月 vs 消耗月不是一回事）、`saving-trend-caveat`（产出面积跨品类不可比、只跟自己的历史比）；`saving-footnotes` 折叠区含「无数据 ≠ 0 / 金额是下界 / 存量导入单列」。', '🔴 判据·**两腿同参（防口径漂移）**：`board` 与 `trend` 收到的 params 必须深相等 —— 只给一条腿加筛选（例如只加 `productId`）会让结论卡①（单商品）与②（全店）分属两个域，而账面上看不出来。', '判据·**向后兼容**：后端未部署（响应无 `comparison` 键）⇒ 页面不崩、且不渲染任何环比块（滚动发布安全）。', '判据·**既有口径一条不放宽**（🔴 2026-10-07 改判后重述）：PR-093 的逐值相等（前端零算术）、PR-094 的「历史导入不进计量腿」、PR-095 的「无数据 ≠ 0 / 档位文案来自服务端」、PR-096 的「不损失客户」与 UI-057 的零内部代号**全部继续绿**；**新增**的是「零服务端分组标签」与「旧形态结构性退场」。⚠️ 一处**定位串**改判（如实登记）：省料明细行 testid 由 `saving-saved-group-<cohort>-<period>` 改为 `saving-saved-group-<period>-<materialKey>` —— 来源组维度已不上屏，行内不再有 cohort 列；**断言强度不变**（仍是「逐行原样渲染服务端值」）。'],
    skip_reason='[backend-contract] 纯前端页面 / 文案 / 纯函数，由 vitest 单测覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'saving-board', 'copy'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-093 [NORMAL] 商家后台用户可见文案去「研发腔」：全量扫描器 + 六条机械规则 + 副标题四条判据 + 类级守卫（issue #6488）（源: cases/ui.yml）──
_CASE_UI_093 = EvalCase(
    id='UI-093',
    legacy_id='',
    title='商家后台用户可见文案去「研发腔」：全量扫描器 + 六条机械规则 + 副标题四条判据 + 类级守卫（issue #6488）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户逐字：「我们系统中暴露了大量的这种研发过程产生的文字，适当的文档可以引导和教育用户如何使用我们的产品，但是这类文案明显不是一个好的引导文案」「最好是扫描下全部商家后台页面，目标是提高文案的真实价值和作用，去除这类看不懂的文字」 —— 现场病灶（截图逐字）：库存明细「端点没有关键词参数」「批次读面没有分页参数……本页宁可不查，也不做「一次拉全量」的假方便」；工艺配置「未定价 = 还没定价（≠ ¥0.00…）（issue #4886）」「判定：净窗高 > 超高阈值（oversize_height_threshold）」「判据是客户口径（企业参数，可配），非 ERP 实证」（注：以上为 **#6580 之前的界面截图逐字转录**，作为当时病灶的证据**保留原样、不改写**；旧坐标「工艺配置」「参数总览」已由 #6580 撤掉 —— **当前**该面板 = 企业基础设置 → 工序与部位单价）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**页面副标题标准**（用户 2026-10-08 定）：副标题要说清「这个功能是干什么的」（正例「管理客户信息、标签和互动记录」；「待派订单按料（商品 × 颜色 × 门幅）合并 —— 同料合并领料，减少接头损耗；**加急单不参与合并，立即单独派单**」也行），**关键规则加粗**；不写机制链路（⇒/→）、表达式（`每行 = 一次…`）、本企业数值口径（`0.5 米级` / `0.1 米粒度`）、占位符字母与模式代号（`X 变成 Y` / `A 模式`）。判据 = `SUBTITLE_RULES` S1~S4 + `findSubtitleOffenses`，扫商家后台 `src/app/(dashboard)/**` 的 `h1` 兄弟 `<p>`（官网不在射程）。', '🔴 判据·**全量扫描器 + 判据单一源**：`frontend/admin-web/scripts/user-copy-scan.mjs` 用 TypeScript AST 抽「会上屏」的三类候选（JSX 文本 / 白名单 JSX 属性 / 含中文的字符串与模板串**字面块**，注释与 CSS 模板串天然不在内），并把五条机械规则与「什么算上屏」的口径做成**唯一一份**（守卫 `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts` 与命令行共用，不写第二份正则）。复算：`node frontend/admin-web/scripts/user-copy-scan.mjs`（在仓库根跑；退出码 ≠ 0 = 仍有命中）。', '🔴 判据·**五族研发腔零上屏**（修复前实测 78 处 / 25 个文件，逐条具名 file:line）：R1 接口与参数细节（端点/入参/分页参数/拉全量/读面/写面/幂等/落库/数据库/服务端/内核）、R2 内部机制名（组合键/派生值/真值源/单一源/快照/状态机/兜底/插值/落账/静默）、R3 研发过程编号与判据语（`issue #NNNN`/`#NNNN`/`PR #NNNN`/`V1xx`/判据/待查明）、R4 代码标识符上屏（`oversize_height_threshold`/`scan_url`/`PC-yyyyMMdd-NNNN`）、R5 行内代码片里塞标识符（`` `HEM_MARGIN` ``）。**判据面 = 用户可见文案**，不是「源码里有没有这个词」。', '🔴 判据·**类级元守卫不退化（判别力自证）**：坏的九个取样形态各自判红（五族各一 + 既有 L2/池/分组标签三族），好的三条（行业术语 + 商家动作）一条都不红；**只改注释不红**（对照读数：守卫不得被自己的文案喂红）；**真声明面自证**（内存里注入的坏文案确实被抽出来，否则「全绿」是假绿）。', '🔴 判据·**豁免台账只许缩短 + 不空转**：`EXEMPT` 每条必须**仍然**命中某条规则，失效当场判红（逼着删干净）。当前唯一一条 = 岗位编码输入框的 placeholder（`admin、customer_service` 是编码**内容本身**，不是散文里的研发腔）。', '判据·**三条既有规则原样迁入**（不削弱）：R6 `L1/L2/L3` 代号（UI-057）、R7 「池」隐喻（UI-058）、R8 服务端分组标签（UI-092）由行扫描改为同一份 AST 口径后**仍逐条判红**，且各自保留原出口话术。', '判据·**假红清理有实测**：`value="pending_review"` / `fieldKey="door_width"` / `stopColor="#6366f1"` 三个 JSX 属性值曾被误判成文案/issue 号 ⇒ 改为**属性白名单**（只认 label/title/hint/placeholder/…）+ 十六进制颜色排除，命中 91 → 78。', '**不回归**：口径/接口/字段名/权限/算料行为一字未动（`frontend-fix.no-api-change`）；被改写的文案所承载的承诺与边界**逐条保留**（未定价 ≠ ¥0.00、「拼接/接高要手选，系统不推算」+「不会多排一道工序」、算例数字仍由真值渲染）。'],
    skip_reason='[backend-contract] 纯前端文案 + 静态守卫，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'copy', 'jargon', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-094 [NORMAL] 服务端机器键不得当展示文本上屏（JSX 文本位跨页面元守卫 · #6523/#6535 同族）（源: cases/ui.yml）──
_CASE_UI_094 = EvalCase(
    id='UI-094',
    legacy_id='',
    title='服务端机器键不得当展示文本上屏（JSX 文本位跨页面元守卫 · #6523/#6535 同族）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-08 用户在两处真机截图上撞见同族缺陷：#6523 智能派单「可合并的待派订单（按料分组）」的料组标题渲染成 `a61daac33e1a49974577d3ca81c4500b|SD07演示-2.8-8141273`（= 服务端 `PoolGroup.materialKey` = `productId|skuCode`，productId 是 UUID）；#6535 省料看板「省下多少」表的「物料」列渲染同一个键（换了个 DTO）。用户同轮逐字：「我们的产品是一个智能专业的优雅绅士，所有的设计风格都应该如此」。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据·**JSX 文本位的服务端机器键零上屏**（跨页面类级元守卫，issue #6552）：扫 `frontend/admin-web/src/**/*.tsx` 的 **JSX 文本位**（元素子节点位置的 `{expr}`，同行 / 独占一行 / 跨行都在面内 —— 用 TypeScript AST 取，**不看行首**）里渲染的**纯成员链**（`x` / `a.b` / `a?.b`），末端标识符以**小写驼峰**命中 `*Key` / `*Uuid` / `*Hash` / `*Token`（或正好叫 `hash` / `token` / `uuid`）⇒ 未登记即红。执行点 = `frontend/admin-web/tests/unit/jsx-machine-key-guard.test.ts`。现取为**空集**（#6523/#6535 已修）。', '🔴 判据·**空集必须显式断言 + 扫描面自证活着**（防「扫到 0 条就绿」的假绿）：同一判据内断言扫描面文件数 ≥ 100、JSX 文本位表达式数 ≥ 1500，且两个现场页面（`production/pool/page.tsx`、`production/saving-board/page.tsx`）必须在场、**仍在用** `materialKey`（只应出现在属性位）；扫描面为空时门禁口径 `guardViolations` 报「判据在扫空气」（真去扫一个空目录取读数，并有真语料对照证明该断言不是恒真）。', '🔴 判据·**属性位是合法承载面**（边界，不许放宽）：`key={…materialKey}` / `data-testid={…materialKey}` / `href` / `value` / `title` **一律不判** —— #6523/#6535 的修复正是把 `materialKey` 留在这些位置、只换展示文本。', '🔴 判据·**人话不误伤**（只收服务端机器键这一族，不是「什么变量都不能渲染」）：`row.productName` / `row.orderNo` / `row.code` / `row.id` / `{key}` / `p.key` / `OTHER_KEY` / `t(`materialKey`)` / `{`materialKey`}`（源码里是 ASCII 双引号，这里转写成反引号） 一律不红；`composition_key`（snake_case）与 `itemKey`（= **工序名**，内容本身）进 `HUMAN_KEY_WHITELIST` 显式登记（**只许缩短**：条目必须仍出现在语料里，死条目即红）。', '🔴 判据·**判别力自证（注入式，两条都要有实跑读数）**：① 把 #6523 / #6535 的**历史形态逐字**写进 `src/` 再扫 ⇒ 必红（两条各自具名 `group.materialKey` / `g.materialKey`），删掉 ⇒ 回到空集；② 把扫描面（语料为空）/ 规则（射程为空的规则表）弄坏 ⇒ 门禁口径必红。另有内存对照：同行形态（`<span …>{group.materialKey}</span>`）与独占一行形态都必红，且**按行首锚定**的坏正则对同行形态给出的是假绿（issue 里逐字的假绿教训，钉成断言）。', '**不回归**：本包只新增判据与用例，`src/**` 一字未改（`frontend-fix.no-api-change`）；`materialKey` 的承载面（React key / `data-testid` / 分组判据）与两处修复的展示口径均不变。'],
    skip_reason='[backend-contract] 纯前端静态元守卫（vitest），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'copy', 'machine-key', 'admin-web', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-095 [NORMAL] 打印单据表格列数不变量：每行 Σ(colSpan) 必须等于表头列数 —— 实例判据（加工单「备注」列数据行缺格 ⇒ 整列无边框）+ 五份单据测试的类级元守卫（issue #6595）（源: cases/ui.yml）──
_CASE_UI_095 = EvalCase(
    id='UI-095',
    legacy_id='',
    title='打印单据表格列数不变量：每行 Σ(colSpan) 必须等于表头列数 —— 实例判据（加工单「备注」列数据行缺格 ⇒ 整列无边框）+ 五份单据测试的类级元守卫（issue #6595）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-09 用户真机截图指出：加工单打印预览里「备注」列**数据行没有边框**（红框圈出）。上一轮我先按「列没对齐」查错了方向（表头/数据行边界逐像素相同），用户逐字纠正：「我是说备注那列的样式缺失了边框」。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**加工单主体行必须占满 8 列**：任一套表格的每一行 Σ(colSpan) 等于 `PROCESSING_DOC_COLUMNS.length`（= 8）；品名规格为空（没有整行补位）时也必须如此 —— 这正是「备注列在数据行没有单元格 ⇒ 整列没有边框」的判据。执行点 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的「表格列数不变量：正文明细表逐行 Σ(colSpan) = 表头列数」+ `frontend/admin-web/tests/unit/components/doc-table-integrity-guard.test.tsx` 的「加工单 · 表格列数不变量」三条。', '🔴 判据 2·**类级元守卫：五份单据都挂同一条不变量**（加工单 / 报价单 / 销售单 / 发货单 / 任务卡）：每份单据的测试必须在本文件里出现「不变量调用 + 单据标识」同一行（`collectTableIntegrity` + `单据：<label>`），未登记即红并逐份具名。执行点 = `doc-table-integrity-guard.test.tsx` 的「类级元守卫 · 每份打印单据都挂同一条表格不变量」三条（含语料下限 ≥ 5 与判别力自证）。', '🔴 判据 3·**判别力自证（注入式，实跑读数）**：① 内存对照 —— 表头 8 列 / 数据行 7 格 ⇒ 抛 `占 7 列，表头是 8 列`；补第 8 格 ⇒ 转绿且读数 ={ columns: 8, rows: [8, 8] }；一格 `colSpan=8` 的行同样自洽（`colSpan` 计入）；容器里 0 张表 ⇒ 抛错（空集不许被读成通过）。② **真浏览器红证**（Chromium 1400×1100 @2x，把修好的第 8 格从渲染出的 DOM 摘掉 = 修前形态）：数据行 `lastCellRight` 由 747.8 退到 649.5，而表头仍是 747.8 ⇒ 备注列（649.5..747.8）在数据行没有格子；补回第 8 格 ⇒ 两者同为 747.8。③ 元守卫内存对照：无标识的调用不认。', '🔴 判据 4·**抬头信息表不被误判（边界，不许放宽）**：`ProcessingDoc` 的抬头表是 `tbody`-only 且行**本来就不等列**（`地址`/`货运` 两行是 `label + colspan=3`，实测 4+4+6+4+6）⇒ 不变量只取带 `<thead>` 的正文明细表（`dataTables()`）；抬头表进面 = 假红。执行点 = `doc-table-integrity-guard.test.tsx` 的「抬头信息表（tbody-only、行内不等列）不被误判」。', "**不回归**：只加一格（`<DocTd>{''}</DocTd>`）—— 列宽分配、纸面文案、接口与字段名一字未动（`frontend-fix.no-api-change`）；备注补位行的触发条件（`item.specification` 非空）与整行形态不变。"],
    skip_reason='[backend-contract] 纯前端打印版式 + 静态/运行时判据（无 LLM 环节），不进 agent-eval 冒烟',
    tags=['ui', 'print', 'table-integrity', 'admin-web', 'meta-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-096 [NORMAL] 加工单列宽按内容预算：批号列 ≥16%（17 位批号两行放得下）+ 列序与 100% 合计不变（issue #6600）（源: cases/ui.yml）──
_CASE_UI_096 = EvalCase(
    id='UI-096',
    legacy_id='',
    title='加工单列宽按内容预算：批号列 ≥16%（17 位批号两行放得下）+ 列序与 100% 合计不变（issue #6600）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['2026-10-09 用户看过加工单真机截图后逐字：> 派（同意把批号列加宽；原口径 =「从货号借 4 个百分点给批号」）'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**批号列的声明宽度 ≥ 16%**：批号是固定 17 字符 `PC-yyyyMMdd-####`（单行约 40mm），9pt/`table-layout: fixed` 下 10%（18.6mm）必然折三行、把数据行撑到 63px；16% ≈ 29.7mm 让 `PC-` / `20261006-0009` **两行放得下**（真浏览器实测 3 行 → 2 行、行高 63 → 45px）。执行点 = `frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx` 的「⑦ 列宽按内容预算」。', '🔴 判据 2·**列序不变 + 合计仍 100% + 8 列都在**：表头标签逐字等于 `PROCESSING_DOC_COLUMNS`（宽度改动不许顺手挪列）；8 个 `w-[N%]` 之和 = 100（改宽必须从别列让出等量，不许悄悄撑破纸面）。执行点 = 同一条测试的后三条断言。', '🔴 判据 3·**判别力自证（在真值源上取证）**：测试从 `src/components/orders/ProcessingDoc.tsx` 的声明里解析出每列 `w-[N%]`（`<DocTh … w-[16%]>…PROCESSING_DOC_COLUMNS[6]`），断言批号那一条就是渲染出来的 16；把该值换成修前的 10 ⇒ 下限判红（`10 < 16`）⇒ 判据不恒真。⚠️ 真跑读数：修前（批号 10%）本测试报 `expected 10 to be greater than or equal to 16`（1 failed / 15 passed），改宽后 16 passed。', '**不回归**：只改 8 个百分比（8/26/11/9/14/8/10/14 → 8/22/11/9/14/8/16/12）—— 列清单、字段取值、纸型、字号、补位行触发条件一字未动（`frontend-fix.no-api-change`）；`部位信息` / `货号` 在样例下仍各 2 行，纸面内容总高 81.8 → 77.0mm（A4 可用 273mm）。'],
    skip_reason='[backend-contract] 纯前端打印版面调整 + vitest 判据（无 LLM 环节），不进 agent-eval 冒烟',
    tags=['ui', 'print', 'processing-doc', 'column-width', 'admin-web'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-097 [NORMAL] 块级元素落在 <p> 里的 hydration 缺陷：售后详情页实例判据（SSR→hydrate 见证）+ 两条类级元守卫（字面嵌套扫描 / 运行期组合台账）（issue #6799）（源: cases/ui.yml）──
_CASE_UI_097 = EvalCase(
    id='UI-097',
    legacy_id='',
    title='块级元素落在 <p> 里的 hydration 缺陷：售后详情页实例判据（SSR→hydrate 见证）+ 两条类级元守卫（字面嵌套扫描 / 运行期组合台账）（issue #6799）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['售后详情页整页 hydration 失败（console 打 `In HTML, <div> cannot be a descendant of <p>`）—— 我要的是**这一族再也进不来**，不是修好这一处：同一形态（组件把块级渲染进 <p>）在别的页面同样是整页 hydration 失败。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**实例**（会红）：`frontend/admin-web/tests/unit/pages/after-sales-detail-hydration.test.tsx` 用 `renderToString` → 浏览器式解析 → `hydrateRoot` 走一轮，断言 ① 服务端 HTML 里没有 `<p …>` 直接包块级标签；② hydrate 的 `console.error` 里没有 `cannot be a descendant of` / `cannot contain a nested` / `Hydration failed`（React 的 `validateDOMNesting`）。修前实测：该文件红（React 逐字打印上述两条，客户端渲染面 `expected [ …(2) ] to deeply equal []`）；修后 3 passed。', '🔴 判据 2·**类级（字面嵌套，零浏览器）**：`scripts/jsx-p-tag-nesting-scan.mjs` 扫 `src/**` 的 `.tsx`，块级/未知 HTML 元素直接落在 `<p>` 里即判红；判别力自证 = 扫描器 `--self-test` 的 10 条**内存注入**形态（坏必红 / 好不报），由 `frontend/admin-web/tests/unit/p-tag-block-nesting-guard.test.ts` 现跑并另做一次真语料变异注入（临时目录，不写工作树）。实测：硬命中 0 / 软命中（组件落在 `<p>` 里）6 类。', '🔴 判据 3·**类级（运行期组合，双向对齐）**：`frontend/admin-web/tests/unit/p-tag-inline-components-guard.test.tsx` 现取「谁被放进 `<p>` 里」的清单（同源跑扫描器），与 `tests/unit/p-tag-inline-components-ledger.json` 逐条对账：**新组件未登记即红**、**台账里有而语料无即红**（只许缩短）；台账 `runtime: instantiated` 的条目**逐个真渲染**在 `<p>` 里，断言 DOM 无块级后代。实测 5 passed（含判别力自证：`<p><div/></p>` 报 div、`<p><span/></p>` 不报）。', '**不回归**：只把 `frontend/admin-web/src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx` 的两处 `<p>` 容器换成 `<div>`（`DateTimeCell` 的两行布局依赖块级子元素，改内联会动版式）；其余 `<p>`（含同类文案 `售后类型` / `退款金额`）一字未动，样式类名逐字保留（`text-sm font-medium text-neutral-900`）。'],
    skip_reason='[backend-contract] 纯前端 DOM 形状 + SSR/hydrate 判据（vitest，零 LLM 环节），不进 agent-eval 冒烟',
    tags=['ui', 'hydration', 'dom-nesting', 'ssr', 'class-level-guard', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-098 [NORMAL] 黄金策对话的中文标点旁强调必须渲染成 <strong>：CommonMark flanking 在「汉字紧邻中文标点」时判 `**` 不能开/不能闭（原样上屏），归一化后星号消失、加粗成立、代码面逐字不动（源: cases/ui.yml）──
_CASE_UI_098 = EvalCase(
    id='UI-098',
    legacy_id='',
    title='黄金策对话的中文标点旁强调必须渲染成 <strong>：CommonMark flanking 在「汉字紧邻中文标点」时判 `**` 不能开/不能闭（原样上屏），归一化后星号消失、加粗成立、代码面逐字不动',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-14 实测截图（黄金策对话）：「黄金策对话回复的Markdown格式还是未完全正确渲染」—— 回复里 `下单入口：后台的**「订单列表」页**，页面里的「新建订单」入口。` 的 `**` 原样上屏，而同一条回复里 `**下单（新建订单）不在我这边办理——…**`、`**我能帮上忙的部分**` 加粗正常。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**实例（会红，真解析管线）**：`frontend/admin-web/tests/unit/components/MessageList-cjk-emphasis.test.tsx` **不 mock `react-markdown`/`remark-gfm`/`remark-breaks`**（既有 MessageList 测试都把 react-markdown 换成 span ⇒ 替身永远看不见真解析结果），断言两条**同时**成立：① markdown 容器（`div.prose`）的 `textContent` 与 `innerHTML` 都不含 `**`；② `<strong>` 真的在（截图原句 = 1 个、截图全文 = 3 个且逐个点名）。只判 ① 的话「把标记删掉」也能绿 = 空判据。修前实测：本文件 4 条红（`**` 进了 textContent、`<strong>` 数为 0）。', '🔴 判据 2·**零可见变化 + 负控（不许误伤）**：`frontend/admin-web/tests/unit/lib/cjk-emphasis.test.ts` —— ① 正控：该插 ZWSP 的边界逐个钉死（开侧 `的**「` / 闭侧 `」**文` / 两侧同时）；② 负控：本来能配对的形态与「不是强调」的星号**逐字不动且一个 ZWSP 都不许插**（`**A**：**B**`、`**A**，**B**`、`snake_case_name`、`2*3*4`、掩码 `138****8888`、单星列表、未闭合 `**`、纯 ASCII `abc**"x"**def`、`def f(**kwargs)`）；③ 代码面：行内代码与围栏代码块里的 `**` 逐字保留（既不配对也不插 ZWSP），代码面之外的正文照常修。其中 `**A**：**B**` 是**改了配对策略就会红**的那条（把作 closer 的标记也改成能开 ⇒ 后面的 `**B**` 落单）。', "🔴 判据 3·**类级元守卫（新渲染点漏接即红）**：同文件判据 ④ 扫 `src/**`，凡 `from 'react-markdown'` 的组件都必须调用 `normalizeCjkEmphasis(`，且扫描面非空自证（面消失 ⇒ 判据在空集上恒真 = 失效）。当下渲染点 = `frontend/admin-web/src/components/chat/MessageList.tsx` 一处。", '**回归面清点（本单边界）**：`frontend/bmini-app/src/utils/richText.ts` 与 `frontend/mini-app/src/utils/richText.ts` 用自写正则 `\\*\\*([^*]+)\\*\\*` 解析强调、`frontend/admin-web/src/lib/inline-markdown.tsx` 同样自写 ⇒ **不受 CommonMark flanking 约束**，本单未改它们（黄金策 web 面是唯一用 CommonMark 渲染商家可见正文的地方）。', '**有意收窄（如实登记）**：① 只在 CJK 区动手 —— 纯 ASCII 的同类失效（`abc**"x"**`）不修（否则 `(**kwargs)` 这类代码随笔会被插入 ZWSP），重启用条件 = 真出现非中文语种的商家可见缺陷；② `_` 的词内斜体（`中文_斜体_中文`）不修（那是 CommonMark 对 `_` 的独立规则，修它会连坐 `snake_case`）；③ 跨行内代码的配对（`**中文 <code>…</code> 中文**`）不修（配对按代码面切分后各自独立 ⇒ 不配对 = 保持原样）。'],
    skip_reason='[backend-contract] 纯前端渲染层（服务端一个字未改：LLM 输出的 markdown 原样下发，缺陷在解析/展示面）由 vitest（jsdom）执行，不进入 agent-eval 冒烟',
    tags=['ui', 'chat', 'markdown', 'cjk', 'admin-web', 'class-level-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition="本用例是 [backend-contract] 纯前端用例：前置由单测自建 —— `frontend/admin-web/tests/unit/components/MessageList-cjk-emphasis.test.tsx` `vi.mock('@/store/chat')` 注入消息夹具（截图全文逐字复用），另把 `@/hooks/use-typewriter` 替身成直返全文（真实定时器会饿死 waitFor 轮询）。前置不成立时单测直接红（找不到 `div.prose` / 找不到 `<strong>`），不依赖共享夹具；agent-eval 栈不跑它",
)

# ── UI-099 [NORMAL] measure 区间守卫：谓词按浏览器实测取（负时间戳，不是负时长）+ 必须真装进客户端（issue #6946）（源: cases/ui.yml）──
_CASE_UI_099 = EvalCase(
    id='UI-099',
    legacy_id='',
    title='measure 区间守卫：谓词按浏览器实测取（负时间戳，不是负时长）+ 必须真装进客户端（issue #6946）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=["验收冒烟偶发 `[pageerror] TypeError: Failed to execute 'measure' on 'Performance': 'ProcessingRedirectPage' cannot have a negative time stamp.` —— #6799 ② 说修过了却还复发；我要的是**这一族再也进不来**，不是再修一次。"],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**实例（会红）**：`frontend/admin-web/tests/unit/lib/user-timing-guard.test.ts` —— 桩按**浏览器实测**实现（**任一时间戳为负 ⇒ 抛** `cannot have a negative time stamp`），覆盖 `{start:-1,end:10}` / `{start:5,end:-1}` / `{start:-5,end:-1}`；判别力对照：**负时长**（`100 → 90`，两个时间戳都非负）必须**照旧透传**（旧守卫会误丢它 ⇒ 拿丢埋点换不报错）。修前实测（旧实现 + 新判据）= **7 failed**；修后 = **2 files / 12 passed**。', "🔴 判据 2·**类级接线元守卫**：`frontend/admin-web/tests/unit/user-timing-guard-wiring.test.ts` 钉三件事 —— ① 装它的模块必须是 `'use client'` 模块；② `layout.tsx` 必须**渲染**该客户端组件（只 import 不算）；③ 守卫模块顶层自装。**回归时会怎么红**：改回「Server Component 里副作用 import」/ 删 `'use client'` / 删 `<UserTimingGuard />` ⇒ 具名报红。", '🔴 判据 3·**接线时机**：`frontend/admin-web/tests/unit/components/UserTimingGuard.test.ts` —— import 即装（模块顶层，早于 React 首次 commit 埋点）、重复 import 只装一次、组件渲染 null、且调用位置必须在 `export default` **之前**（挪进组件体即判红，附负控）。', '🔴 真栈复探（人工一条命令，非 CI 腿）：`node acceptance/2026-10-14/tools/probe-timing-guard.mjs` ⇒ 修后逐字 `installed=true patched=true negativeTimestampThrows=false legitPassedThrough=true pageerrors=0`（修前 `installed=false patched=false`）。⚠️ 探针自己踩过假阴性：标记打在 `window.performance` 上，不是 `performance.measure` 上。'],
    skip_reason='[backend-contract] 纯前端研发态观测面（User Timing 只喂 DevTools；服务端一字未改），由 vitest（jsdom）+ 一条 Playwright 探针执行，不进 agent-eval 冒烟',
    tags=['ui', 'dev-mode', 'performance-timing', 'client-wiring', 'class-level-guard', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-100 [NORMAL] 商家后台版式统一（页头/页内容器/筛选卡片共享件）+ 零 Tailwind 默认调色板（issue #7007）（源: cases/ui.yml）──
_CASE_UI_100 = EvalCase(
    id='UI-100',
    legacy_id='',
    title='商家后台版式统一（页头/页内容器/筛选卡片共享件）+ 零 Tailwind 默认调色板（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=["🔴 判据 1·**零中性灰族（会红）**：`frontend/admin-web/tests/unit/warm-token-palette-guard.test.ts` 扫 `frontend/admin-web/src/app/**` + `frontend/admin-web/src/components/**`（`.tsx`，去注释后），不得出现 `bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke` × `gray|slate|zinc|stone` × 色阶的工具类。**修前实测 = 8 个文件 / 104 处**（`SessionInsight` 38 · `Pagination` 22 · `RefundOrderModal` 17 · `FileUpload` 17 · `EmptyState` 4 · `TreeCheckbox` 3 · `MibaoAccessGate` 2 · `Loading` 1）；**修后 = 0**。复算命令：`grep -rEn '(bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(gray|slate|zinc|stone)-[0-9]' frontend/admin-web/src/`（注释里的引用会命中，判据侧先去注释 ⇒ 以测试为准）。", '🔴 判据 2·**冷彩族台账双向相等（会红）**：同一文件的判据 4 —— 台账 `frontend/admin-web/tests/unit/palette-drift-ledger.json`（20 个文件 / 74 处，`blue`/`indigo`/`sky`/`violet`/`purple`/`cyan` 族）与**现取命中**必须逐文件逐计数相等。**三态都会红**：① 台账有、现取无 ⇒ **死条目**（修好必须删条，留着即松弛量）；② 现取有、台账无 ⇒ **新写的漂移当场红**；③ 计数不一致 ⇒ 报「台账 N vs 现取 M」。判据 5 另判台账不得为空（清空「消红」⇒ 红）。**本判据不为存量背书**，只保证「不再增长 + 修一处少一处」。', '🔴 判据 3·**判别力自证（4 条，在内存里各自判红/放行）**：① 坏形态 `bg-gray-50 text-gray-500 border-gray-200` 命中三条；② 暖色 token（`neutral-*`/`primary-*`）与语义色（`emerald`/`red`/`amber`）**放行且不误伤**；③ **注释里的旧写法不算违规**（否则守卫被自己的说明喂红 —— 本仓已多次踩）；④ 官网子树 `frontend/admin-web/src/app/(corporate)/**` 确在射程之外。', '🔴 判据 4·**共享件存在且用词来自 token**：`frontend/admin-web/src/components/ui/PageHeader.tsx`（标题 `text-2xl` = `TYPE_SCALE` 的 h1 档，见 `frontend/admin-web/src/lib/design-tokens.ts`；此前 26 处 `h1` 全写 `text-xl` ⇒ 页面标题与区块标题同档、层级读不出来）、`PageCard.tsx`（`bg-white rounded-lg border border-neutral-200 shadow-card` + `p-5`）、`SearchPanel.tsx`（标签左置 + 单一响应式 grid + 按钮独占一行，抽自订单页 issue #5880 那一版）三件经 `frontend/admin-web/src/components/ui/index.ts` 导出；`SearchBar.tsx` 底色由 `bg-gray-50` 改 `bg-neutral-50`、**调用方契约（`onSearch(values)` 形状 / `data-testid` = `search-area`）零变更**。', '🔴 判据 5·**既有设计基线一条不放宽**：`design-baseline-token-contract` / `-geometry`（桌面主控件高度 ≥36px，见 `GEOMETRY_LIMITS.minControlHeight`）/ `-page-state-contract`（四态齐备、失败 ≠ 空）/ `-expression-fallback` / `-server-strings` 五个文件**全部继续绿**（本包实测 `137 passed`），且 `tests/unit/components/**` 全量 **1694 passed**。'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数 / 加工费组合键**逐值不变**，由 vitest（jsdom）+ §15.7 真机多模态验收执行，不进 agent-eval 冒烟',
    tags=['ui', 'design-baseline', 'class-level-guard', 'warm-token', 'shared-primitive', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-101 [NORMAL] 算料口径的术语与说明文案收口：展示名改叫法 + 去内部腔 + 逐条术语压到 2~4 行（issue #7007）（源: cases/ui.yml）──
_CASE_UI_101 = EvalCase(
    id='UI-101',
    legacy_id='',
    title='算料口径的术语与说明文案收口：展示名改叫法 + 去内部腔 + 逐条术语压到 2~4 行（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['算料口径里面的术语也重构一下，现在给人一种乱七八糟的感觉，文案也是非常乱，应该精简美化，算料口径也顺带重构一遍最好'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**只改展示名，口径零变更（会红）**：`frontend/admin-web/tests/unit/lib/craft-calc-glossary.test.ts` 的键集同源判据（`CALC_SCALAR_KEYS` 逐值等于引擎 `DEFAULT_CRAFT_CALC_CONFIG` 的标量键）+ `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx` 的「保存发**全量键**（11 键）」判据 —— 改展示名若顺手动了键名 / 公式 / 数值，这两条当场红。**实测修后 `183 passed`**（P3 射程 11 个文件）。', '🔴 判据 2·**展示名逐字为改后值（会红）**：`frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx` 断言 `单色每折用料（米）` 在位（改前为 `单色每折吃布（米）`）。同批把 `CalcCaliberPanel.tsx` 里拼次输入框的 `aria-label` 由「拼N次 每折吃布」改为「拼N次 每折用料」—— 无障碍名与可见名**同一套词**，避免屏幕阅读器读到另一个说法。', '🔴 判据 3·**逐条术语压到 2~4 行（会红）**：`frontend/admin-web/tests/unit/components/CraftCalcGlossary.test.tsx` 的渲染面（`glossary-term-<名>` 锚点在、算例带真实数字、`拼接` 含「不会多排一道工序」、`接高` 含「系统不推算」；2026-10-17 #7147 起另加**类级口语词表守卫** —— 口语 / 说不准 / 替你猜 / 看着像 / 真值 / 名义 / 系数档 任一上屏 ⇒ 红）+ `frontend/admin-web/tests/unit/lib/copy-no-markdown-emphasis.test.ts`（带 `**` 的文件必须登记且接线渲染器）。结构改法 = 术语名与一句话定义**同一段**（此前名 / 定义 / 判定 / 影响各占一段 ⇒ 一条最多 5 行小字、六组三四十行）。', '🔴 判据 4·**用户裁定的边界照实登记（有意不做）**：① **不改** `每折吃布` 这个算料术语本身 —— 它同时是引擎响应字段名（`per_fold`）与下单页用料公式说明（`frontend/admin-web/src/lib/meters-formula-legend.ts`）里的用词，只改配置页展示名会让配置页与公式说明对不上；重启条件 = 公式说明的词一并统一时（属另一包）。② **保留** `倒幅`/`正幅`/`定型`/`拼N次`/`接高`/`双眼皮接高` 业务词（与 ERP、工序目录、工人端同源，改名会让三方分叉）。两条都写在 `frontend/admin-web/src/lib/craft-calc-glossary.ts` 的模块头注释里。'],
    skip_reason='[backend-contract] 纯前端展示名与说明文案（服务端一字未改）：配置键 / 公式 / 米数 / 加工费组合键逐值不变，由 vitest（jsdom）+ §15.7 真机多模态验收执行，不进 agent-eval 冒烟',
    tags=['ui', 'copy', 'craft-calc', 'user-facing-copy', 'display-name-only', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-107 [NORMAL] PageHeader 共享原语：页面标题必须是 h1 档（text-2xl）而非区块标题档（text-xl）—— 26 处手写页头收敛为一个原语（issue #7007）（源: cases/ui.yml）──
_CASE_UI_107 = EvalCase(
    id='UI-107',
    legacy_id='',
    title='PageHeader 共享原语：页面标题必须是 h1 档（text-2xl）而非区块标题档（text-xl）—— 26 处手写页头收敛为一个原语（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**标题渲染成 `<h1>` 且是 TYPE_SCALE 的 h1 档**：`frontend/admin-web/src/lib/design-tokens.ts` 规定 h1 = `text-2xl`（24px）、h2 = `text-xl`（20px）；改前全仓 **26 处手写 `h1` 全部写 `text-xl`** ⇒ 页面标题与页内区块标题**同档**、层级读不出来。执行点 = `frontend/admin-web/tests/unit/components/PageHeader.test.ts` 的「标题渲染成 `<h1>` 且是 TYPE_SCALE 的 h1 档」。**红证（实跑）**：`text-2xl` → `text-xl` ⇒ 该条当场判红（1 failed | 6 passed）。', '🔴 判据 2·**字重只有一支**：改前两种字重混用（`font-bold` 分类页 vs `font-semibold` 其余 25 处）⇒ 同层级标题字重不同。执行点 = 同文件的「整仓不许再出现 font-bold 的页头」', '🔴 判据 3·**语义与视觉同时到位**：`<h1>` 而不是 `text-2xl` 的 `<div>` —— 读屏器靠 h1 建立大纲。**红证**：把 `<h1>` 换成 `<div>` ⇒ 该条红', '🔴 判据 4·**副标题与动作区都是可选的、且不传时不留空壳**：`subtitle` 不传 ⇒ DOM 里零个 `<p>`；`actions` 不传 ⇒ 只有一个外层 div（红证：去掉 `subtitle &&` / `actions &&` 的条件 ⇒ 留下空 `<p>` / 空 flex 容器，把标题可用宽度挤掉）', '🔴 判据 5·**动作区纵向对齐用 `items-start`**：`items-center` 会让「有副标题」时按钮下沉、「无副标题」时上跳 ⇒ 同批页面里按钮位置不一致。⚠️ 本条**只钉类名**；真实几何由 `migao-dev-flow` §15.7 真浏览器读图覆盖', '🔴 判据 6·**原语不吃权限码**：`canWrite ? <Button/> : null` 留在调用方，原语结构上没有回显权限码的入口（与 `AccessDenied` 同族口径）'],
    skip_reason='[backend-contract] 纯前端版式原语（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'design-baseline', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-108 [NORMAL] PageCard 共享原语：页内一级容器必须自带 shadow-card（否则与整页卡片同为「边框套边框」）+ testId 必须透传（14 页迁移的支点）（issue #7007）（源: cases/ui.yml）──
_CASE_UI_108 = EvalCase(
    id='UI-108',
    legacy_id='',
    title='PageCard 共享原语：页内一级容器必须自带 shadow-card（否则与整页卡片同为「边框套边框」）+ testId 必须透传（14 页迁移的支点）（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**自带 `shadow-card`**：改前全仓 **15 处内层容器只有 `border`、无阴影** ⇒ 与 `app/(dashboard)/layout.tsx` 的整页卡片（`rounded-2xl border shadow-card`）视觉权重相同 ⇒ 「边框套边框」、层级分不开。执行点 = `frontend/admin-web/tests/unit/components/PageCard.test.ts` 的同名条目。**红证（实跑）**：去掉 `shadow-card` ⇒ 该条当场判红（连带 3 条形态判据同时红，成对读数已在 PR body）', '🔴 判据 2·**形态值只来自 token**：`bg-white` / `border-neutral-200`（**不得** `border-gray-*` —— `gray` 在本仓没有 token）/ `rounded-lg`（不得 `rounded-xl` —— 改前圆角三种写法混用 ⇒ 同屏区块起点参差）', '🔴 判据 3·**`testId` 必须透传到 DOM 的 `data-testid`** —— 本包 14 页迁移的**支点**：页面级判据大量以 `data-testid` = `search-area` / `<x>-empty` 定位容器，原语不透传就只能退回手写 div，迁移前提不成立。**红证（实跑）**：删掉 `data-testid={testId}` ⇒ 该条当场判红', '🔴 判据 4·**不传 `testId` 时 DOM 上不出现 `data-testid`**（原语要能替换原有手写 div 而**不引入**新属性，否则既有选择器会漂）', '🔴 判据 5·**`padded={false}` 只关内边距档、不关分层**：整宽表格 + 分页脚的页面保留 `shadow-card` / `border` / `rounded`，但不被多套一层 `p-5`（红证：让 `padded=false` 仍加 `p-5` ⇒ 红）', '🔴 判据 6·**不碰布局语义**：children 原样渲染、原语不加栅格 / 不包额外 div（红证：给 children 套一层 grid ⇒ 元素计数判据红）。这是架构边界，与 `SearchPanel` 的「不持有筛选 state」同族'],
    skip_reason='[backend-contract] 纯前端版式原语（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'design-baseline', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-102 [NORMAL] CustomerPanel 状态色收口：订单六态语义色由冷色族（blue/purple/indigo）改为暖色 token（primary/accent）+ 收起/展开两态（issue #7007）（源: cases/ui.yml）──
_CASE_UI_102 = EvalCase(
    id='UI-102',
    legacy_id='',
    title='CustomerPanel 状态色收口：订单六态语义色由冷色族（blue/purple/indigo）改为暖色 token（primary/accent）+ 收起/展开两态（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**冷色收口（实例判据）**：`confirmed` 由 `blue-*` 改 `primary-*`；`producing` 由 `purple-*` 改 `accent-*`；`shipped` 由 `indigo-*` 改 `accent-*`。**未改判的三态**：`pending` 保持 `amber-*`、`completed` 保持 `green-*`、`cancelled` 保持 `neutral-*`。红证：把任一态改回 `blue-50` ⇒ 该条红；由 `warm-token-palette-guard.test.ts` 的硬禁做类级兜底', '🔴 判据 2·**两条渲染分支**：无 `currentSessionId` 时`return null`（不留空壳侧栏）；`collapsed` 时只渲染折叠条，点它回到展开态'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-103 [NORMAL] SearchPanel 共享原语：筛选区版式不变量（单一响应式 grid + label 左置定宽 + 按钮行独占）+ 三个动作按钮的「没传就不渲染」（issue #7007）（源: cases/ui.yml）──
_CASE_UI_103 = EvalCase(
    id='UI-103',
    legacy_id='',
    title='SearchPanel 共享原语：筛选区版式不变量（单一响应式 grid + label 左置定宽 + 按钮行独占）+ 三个动作按钮的「没传就不渲染」（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**版式不变量**：容器 `grid-cols-1 md:grid-cols-2 2xl:grid-cols-4`（单一响应式 grid ⇒ 行与行天然对齐，取代 `flex-wrap` 的漂移换行点）；字段格 `min-w-0`；label `w-[4.5em]` + `text-right` + `shrink-0`（各行 label 起点对齐）；按钮行 `col-span-full` + `justify-end`。红证：改回 `flex flex-wrap` / 去掉 `w-[4.5em]` ⇒ 对应条红', '🔴 判据 2·**动作分层的取舍**：「查询」恒在并调 `onSearch`；「重置」/「刷新」**没传就不渲染**（`onRefresh` 那支外面套 `border-l` 的 span —— 刷新是列表动作、与筛选动作分层）；`loading` 时三个按钮都 `disabled`。红证：把 `onReset &&` 去掉 ⇒ 「没传就不渲染」当场红', '🔴 判据 3·**原语不持有筛选 state**（架构边界）：`fields[].control` 由调用方渲染、被原样透传（改原语不该改变任何页面的信息结构）；红证：原语内部改成受控 state ⇒ 透传判据红', '🔴 判据 4·**`SEARCH_CONTROL_CLASS` 值与暖色收口**：含 `h-9`（36px，`design-baseline-geometry-probe.mjs` 的 `GEOMETRY_LIMITS.minControlHeight`）/ `w-full` / `border-neutral-300` / `focus:ring-primary-500/15`，且**不含** `gray-`/`blue-`/`indigo-`/`purple-`'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-104 [NORMAL] EmptyState：新增 testId 透传（默认不改变既有 DOM）+ 四个图标映射 + 暖中性色收口（issue #7007）（源: cases/ui.yml）──
_CASE_UI_104 = EvalCase(
    id='UI-104',
    legacy_id='',
    title='EmptyState：新增 testId 透传（默认不改变既有 DOM）+ 四个图标映射 + 暖中性色收口（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**`testId` 透传成 `data-testid`**；**不传时 DOM 上不出现该属性**（原语要能替换手写空态而不引入新属性）。红证：不透传 ⇒ 红', '🔴 判据 2·**四个 `icon` 值映射到 `Package`/`Search`/`FileX`/`Inbox`**；默认 `title`/`description` 逐字；`action` 给了才渲染', '🔴 判据 3·**暖中性色收口**：`bg-neutral-100`/`text-neutral-400`/`text-neutral-900`/`text-neutral-500`，**不得**出现 Tailwind 默认冷灰 `gray-*`（改前那些是 `gray-*`；类级硬禁见 `warm-token-palette-guard.test.ts`）'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-105 [NORMAL] FileUpload：上传/删除/超限拦截的交互契约 + 进度条与暖色收口（blue-* → primary-*）（issue #7007）（源: cases/ui.yml）──
_CASE_UI_105 = EvalCase(
    id='UI-105',
    legacy_id='',
    title='FileUpload：上传/删除/超限拦截的交互契约 + 进度条与暖色收口（blue-* → primary-*）（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**暖色收口**：上传中那块由 `blue-*` 改 `primary-*`（`border-primary-200` / `bg-primary-50/50` / 进度条 `bg-primary-500` / 桶底 `bg-primary-100`）；失败态进度条保持 `bg-red-500`。红证：改回 `blue-200` ⇒ 红', '🔴 判据 2·**`effectiveMax` 语义**（`multiple ? maxFiles : 1`）：`value.length >= effectiveMax` 时**不再渲染上传入口**（满了不给入口）；多选时 `multiple` 才透传', '🔴 判据 3·**超限文件拦截**：`file.size > maxSize*1024*1024` ⇒ 调 `toast.error` **且不调上传接口**（真实反例保护）', '🔴 判据 4·**`formatSize` 三档边界**：`<1024` ⇒ `N B`；`<1MB` ⇒ `X.X KB`；否则 `X.X MB`（一位小数）', '🔴 判据 5·**`label` / `hint` 给了才渲染**；已传文件列表渲染文件名 + 人类可读体积 + 删除按钮'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-106 [NORMAL] Loading：三档 size 的类名逐值 + 默认 md + 文案给了才渲染 + 主色由 blue 收口到 primary（issue #7007）（源: cases/ui.yml）──
_CASE_UI_106 = EvalCase(
    id='UI-106',
    legacy_id='',
    title='Loading：三档 size 的类名逐值 + 默认 md + 文案给了才渲染 + 主色由 blue 收口到 primary（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=['🔴 判据 1·**暖色收口**：`Loader2` 由 `text-blue-600` 一类改为 `text-primary-600`（实例判据；类级硬禁见 `warm-token-palette-guard.test.ts`）', '🔴 判据 2·**三档 `sizeMap` 逐值**：`sm`=`w-4 h-4` / `md`=`w-6 h-6` / `lg`=`w-10 h-10`，且**默认档是 `md`**（不传 size 时取 md）', '🔴 判据 3·**`text` 给了才渲染**（`text-neutral-500 text-sm`）；`className` 透传'],
    skip_reason='[backend-contract] 纯前端版式与配色收口（服务端一字未改）：配置键 / 公式 / 米数口径 / 接口与字段名均未动，不进入 agent-eval 冒烟',
    tags=['ui', 'shared-primitive', 'warm-token', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-109 [NORMAL] lucide-react mock 的闭集类级元守卫：替身必须摊开真值（ ...actual / Proxy(actual)），不得用固定图标名单（issue #7007）（源: cases/ui.yml）──
_CASE_UI_109 = EvalCase(
    id='UI-109',
    legacy_id='',
    title='lucide-react mock 的闭集类级元守卫：替身必须摊开真值（ ...actual / Proxy(actual)），不得用固定图标名单（issue #7007）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['能否再保留我们当前项目原UI风格设计的前提下，提高整体的精美程度？我看到当前页面整体只有订单管理的设计是非常精美的，其他的页面没有这样的感觉。'],
    expectations=['direct_reply'],
    data_checks=["🔴 判据 1·**类级元守卫：凡替身 `lucide-react` 的 mock 都不得是闭合集合**：扫 `tests/**` 全部 TS/TSX，凡出现 `vi.mock('lucide-react', …)` —— 要么走本仓 helper `tests/unit/helpers/lucide-mock.ts`（它自己 `...actual`），要么工厂必须是 `async (importOriginal)` 且返回值里出现 `...actual`，要么是 `new Proxy(actual, …)`（未知键透真值）。违者**具名列出文件**。执行点 = `frontend/admin-web/tests/unit/lucide-mock-closure-guard.test.ts` 的「凡替身 lucide-react 的 mock，都必须是「摊开真值 + 显式桩」而不是闭合集合」。**红证（实跑）**：删掉 `setup.ts` 或 `after-sales.test.tsx` 的 `...actual` ⇒ 该条当场判红并指名那个文件", '🔴 判据 2·**全局兜底桩 `tests/setup.ts` 单独再钉一次**：它是所有测试文件的兜底，漏一个图标就是**全仓红**（实测 `File` / `KeyRound` / `MailOpen` 三个就不在它那张 163 个的固定名单里）。红证：删掉它的 `...actual` ⇒ 当场红', '🔴 判据 3·**判别力自证（防空转绿）**：① 语料下限 —— 真扫到 > 200 个测试文件（把扫描根指错 ⇒ 红）；② 被检 mock 处数 ≥ 10（把扫描面改窄 ⇒ 红）。没有这两条，「零违规」可能与「什么都没扫」无法区分', '📌 **为什么立成类级**（同一族缺陷本轮咬了两次，单点修复只是把病灶挪到下一层）：第 1 次 `@/components/ui` **桶**的 mock 是闭集 ⇒ 页面一用上当时不存在的原语就报 `No "PageHeader" export`；第 2 次把桶改成 `...actual` 后，**真的**加载了 `EmptyState` ⇒ 而测试文件自己的 lucide mock 只列了 7 个图标 ⇒ 7 个套件同时报 `No "Package" export is defined on the "lucide-react" mock`。⇒ 病根是「**用闭合集合去替身一个会继续增长的模块**」，必须靠扫形状的元守卫拦，不能靠逐处补图标', '📌 **为什么本地没抓到（判据读数口径）**：上一轮用 `vitest run --reporter=json --outputFile=…` 取读数，报「4743/4744 通过、失败文件 0」—— 但**套件加载失败时那一整个文件的用例不计入 JSON 的 assertionResults** ⇒ 「7 个文件全灭」表现为「失败文件 0」。改用 CI 同款裸命令 + **看 exit code / `Test Files` 行**后当场复现 7 个 FAIL。⇒ 判据读数必须取**会红的那个量**，不能取一个漂亮的分母'],
    skip_reason='[backend-contract] 纯前端测试基建（服务端一字未改）：不进入 agent-eval 冒烟',
    tags=['ui', 'test-infra', 'meta-guard', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-110 [NORMAL] **「商家后台页面头只有一个来源」的类级元守卫**：射程内凡手写 `<h1>` 且未用共享原语 `PageHeader` 的文件，必须恰好等于「冻结快照 ∪ 逐条给出理由的有意不迁」；快照只许缩短、有意不迁不许悄悄涨价（issue #7065）（源: cases/ui.yml）──
_CASE_UI_110 = EvalCase(
    id='UI-110',
    legacy_id='',
    title='**「商家后台页面头只有一个来源」的类级元守卫**：射程内凡手写 `<h1>` 且未用共享原语 `PageHeader` 的文件，必须恰好等于「冻结快照 ∪ 逐条给出理由的有意不迁」；快照只许缩短、有意不迁不许悄悄涨价（issue #7065）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['为什么只有订单页看起来精致，其它页面没有这种感觉？'],
    expectations=['direct_reply'],
    data_checks=['🔴 **判据 1（完备性，会红）**：射程（`src/app/(dashboard)/**` 下每个 `page.tsx` + 动态路由段下的页面组件，现取 48 个文件）内，凡**手写 `<h1>` 且未用 `PageHeader`** 的文件，必须**恰好**等于「冻结快照 ∪ 逐条给出理由的有意不迁」⇒ **两边都不许漏项**（既不能偷偷手写，也不能把文件挪进清单了事）。执行点 = frontend/admin-web/tests/unit/page-header-single-source-guard.test.ts。**红证（实跑，逐字节还原）**：把 `products/page.tsx` 的 `<PageHeader>` 换回手写 `<h1 className="text-xl …">` ⇒ 判据 1 红；把快照里一项删掉但不迁移 ⇒ 判据 1 红。', '🔴 **判据 2（只许缩短）**：快照**销账是必须动作** —— 已迁完却还留在快照里 ⇒ 红（陈旧条目）；快照项必须去重、必须真实存在且仍在射程内。', '🔴 **判据 3（有意不迁不许悄悄涨价）**：`PARKED_WITH_REASON` 每条**理由非空且 ≥15 字** + 路径必须在射程内 + 条目数有**独立冻结上界**（现取 8，只许缩短）—— 快照清零后不能让它顺带变成「有意不迁可以无限长」。', "🔴 **判别力自证 + fail-closed**：坏形态（手写 `<h1>`）判红、好形态（`<PageHeader>`）放行；**关键反例**：`import { PageHeader } from '@/components/ui'` 只剩 import（用点被换回手写 h1 但忘了删 import）⇒ **不算用过**；射程目录取不到 ⇒ 抛（不许把「没东西可判」读成绿）；射程 > 20 个文件的反空跑下限。", '📌 **为什么必须静态拦**：P0/P1/P2（PR #7012）只做了**逐页迁移**，**没有任何东西**阻止新页面再手写一个 `<h1 className="text-xl font-semibold">` 回去 —— 而 `design-tokens.ts` 的 `TYPE_SCALE` 规定 h1 = `text-2xl`、h2 = `text-xl` ⇒ 手写 `text-xl` 的页头与**页内区块标题同档**，视觉层级读不出来（用户 2026-10-16「只有订单管理精美」的三条根因之一）。`production/remnants` 那页更差：`text-lg`，**低于** h2 档。', '📌 **本单交付**：16 项存量**全部处置** —— **8 项**迁原语（production 族 5 + knowledge/settings/orders/orders-new 5，去重后 8 个真实文件），**8 项**进「有意不迁」并逐条写明理由。快照现为 **0 项**。', '📌 **有意不迁的 8 项为什么是「适配问题」而不是遗漏**：`agent-workspace` 两页是**固定高度工具条**（`h-14` + `border-b`，嵌在 `h-[calc(100vh-180px)]` 全高工作区里，标题 `text-base`）—— 套 `PageHeader`（`text-2xl` + 自带外边距 + 两行结构）会**撑破版式**；其余 6 项（`orders/[id]` / `orders/[id]/ship` / `processing-orders/[id]/production` / `after-sales/[id]` / `products/[id]`）是**标题与返回按钮 / 内联状态徽标 / 标题行内图标 / 单据号咬合**的详情页头。⇒ 重启条件已写进清单注释（真要做这些页面的版式统一时，先给它们定「紧凑型页头」的形态）。', '📌 **迁移过程的机械护栏（值得复用）**：批量替换 JSX 极易漏收尾标签 —— 本单**第一版 5 个文件全部漏了**外层 `</div>`，`tsc` 报 19 个语法错。重做时给迁移脚本加了**替换前自证**：被替换片段与替换片段的 **JSX 栈深度**与**花括号配平**必须逐项相等。它**真的抓到了两次**（`saving-board` 只截半个块；`orders/page.tsx` 同样）⇒ 脚本拒绝写入，补上收尾标签后才写。'],
    skip_reason='[backend-contract] 前端静态判据（扫 TSX 源码 + 冻结快照对账），零网络、零时钟、非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'design-consistency', 'page-header', 'class-guard', 'snapshot-burndown', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置 = 两样都在仓里可读：① 共享原语 frontend/admin-web/src/components/ui/PageHeader.tsx（h1 = `text-2xl font-semibold text-neutral-900`，即 `design-tokens.ts` 的 `TYPE_SCALE` h1 档）；② 守卫本体 frontend/admin-web/tests/unit/page-header-single-source-guard.test.ts。**前置不成立时不许读成通过**：射程目录取不到 ⇒ `walk()` 抛（fail-closed）；射程文件数 < 20 ⇒ 反空跑判红。',
)

# ── UI-111 [NORMAL] **「内层白卡必须有 shadow-card」的类级元守卫**：射程内凡「白底 + 圆角 + 中性边框」的内层白卡容器，必须带 `shadow-card`，否则「一圈边框套一圈边框」（issue #7069，承接 #7007 根因②）（源: cases/ui.yml）──
_CASE_UI_111 = EvalCase(
    id='UI-111',
    legacy_id='',
    title='**「内层白卡必须有 shadow-card」的类级元守卫**：射程内凡「白底 + 圆角 + 中性边框」的内层白卡容器，必须带 `shadow-card`，否则「一圈边框套一圈边框」（issue #7069，承接 #7007 根因②）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['为什么只有订单页看起来精致，其它页面没有这种感觉？'],
    expectations=['direct_reply'],
    data_checks=['🔴 **判据 1（会红）**：射程（`src/app/(dashboard)/**` + `src/components/**` 的 `.tsx`，现取 400+ 文件）内，凡形态为「白底 + 圆角 + 中性边框」（`bg-white rounded-{lg,xl,2xl} border border-neutral-200`）的**内层白卡容器**，**必须**带 `shadow-card`；缺即**点名 `文件:行号`** 判红（判红文案直接给出复算命令与出口）。**红证（实跑、逐字节还原）**：摘掉「作业看板」页查询区容器的 `shadow-card`（定位 = 该页 `bg-white rounded-lg border border-neutral-200 shadow-card p-5` 那个 div）⇒ 判据 1 红并点名该处所在的 `文件:行号`。', '🔴 **判据 2（反空转）**：射程内白卡容器**实存 ≥ 15 处**（现取 **22**）⇒ 防「把 className 改写成别的形态」绕过判据 1。', '🔴 **判据 3**：`shadow-card` 这个 token **真的被定义**（`tailwind.config.ts` 的 `boxShadow.card`）⇒ 防「写了个不存在的类」（本仓曾出现「声明存在 ≠ 可达」的形态，铁律 11）。', '🔴 **判据 4（判别力自证）**：坏形态判红、好形态放行；且**不该命中的形态不被命中**（`divide-y divide-neutral-200` 分隔线 / `input` 的 `border-neutral-300` 边框 / Tab 下划线都**不是**白卡容器）。', '📌 **为什么这是「精美度」的结构问题**：`app/(dashboard)/layout.tsx` 已把每页包进 `rounded-2xl border shadow-card`（外壳统一），差距全在**卡片内部**。订单页的清透感来自「**整页卡片(阴影) → 内层卡片(边框)**」这套层级；内层容器缺 `shadow-card` 时与外壳**视觉权重相同** ⇒ 退化成「**一圈边框套一圈边框**」（#7007 正文逐字诊断，用户原话「只有订单管理精美」）。', '📌 **本单交付**：22 处命中里 **9 处缺 `shadow-card`** 全部补齐（production / knowledge / orders×2 / finance / roles + components 的 WorkerProfilesPanel / ProductForm / ProductTable）；修后缺 = **0**。**只补 token，不动 padding / 布局 / 文案 / 交互**。', '📌 **一处易误读**：`frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx` 有 **5 处**命中该 grep，但它们**本来就有** `shadow-card`（`bg-white rounded-xl border border-neutral-200 shadow-card p-5`）⇒ 「命中 grep」≠「缺阴影」；**必须在同一行**再查 `shadow-card` 才能定性（我第一版用 `grep -c "shadow-card"` 统计时就被这个绊了一次）。', '📌 **顺带修真的一处漂移**：`roles/page.tsx` 原写 `hover:shadow-md`（Tailwind **内置**阴影）⇒ 改为仓里已有的 `hover:shadow-card-hover`（暖色阴影 token，与 `shadow-card` 同一套体系）。', '📌 **边界（照实登记）**：本判据**只钉住「白卡容器不得缺 shadow-card」这一侧**，**不判**「阴影是不是太多了」——反过来层层堆阴影同样破坏层级，那属**评审面**（§15.7 读图 + §31 产品设计原则）；也**不判**「该用 `PageCard` 原语还是手写 div」（两种写法都合规，只看层级 token）。'],
    skip_reason='[backend-contract] 前端静态判据（扫 TSX 源码的 className 形态 + 冻结下界对账），零网络、零时钟、非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'design-consistency', 'card-layering', 'shadow-card', 'class-guard', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置 = 三样都在仓里可读：① 阴影 token `frontend/admin-web/tailwind.config.ts` 的 `boxShadow.card`（`0 1px 2px rgba(36,31,24,.04), 0 4px 16px rgba(36,31,24,.06)`）；② 页内一级容器原语 `frontend/admin-web/src/components/ui/PageCard.tsx`（自带 `shadow-card`）；③ 守卫本体 `frontend/admin-web/tests/unit/inner-card-layer-guard.test.ts`。**前置不成立时不许读成通过**：射程目录取不到 ⇒ `walk()` 抛（fail-closed）；射程文件数 ≤ 40 ⇒ 反空跑判红；白卡容器 < 15 处 ⇒ 判据 2 红。',
)

# ── UI-112 [NORMAL] 失败原因 = 业务文案：传输层读数不得上屏（智能派单报 422 显示 Request failed with status code 422；2026-10-17 用户裁定）（源: cases/ui.yml）──
_CASE_UI_112 = EvalCase(
    id='UI-112',
    legacy_id='',
    title='失败原因 = 业务文案：传输层读数不得上屏（智能派单报 422 显示 Request failed with status code 422；2026-10-17 用户裁定）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 逐字：「点击一键合并派单后页面报错了，你看下服务器上的日志，这个错误提示非常低级，用户完全看不懂，得把报错原因用业务文案写清楚，而不是技术语言」（截图 = 智能派单页 `合并预览失败：Request failed with status code 422`）'],
    expectations=['direct_reply'],
    data_checks=['🔴 **两层归因**：① 调用面 `frontend/admin-web/src/app/(dashboard)/production/pool/page.tsx` 的 `dispatchErrorText` 取的是 `e.message`，而 axios 错误的 `.message` **就是**传输层读数（`Request failed with status code 422`）；服务端业务原因在 `error.response.data.error.message`（`GlobalExceptionHandler` 的 `ApiResponse.error(code, message, details)`）里、被那一行丢掉。② 共享原语 `frontend/admin-web/src/lib/api-error.ts` 的 `extractApiErrorMessage` 兜底链里也留着 `err.message` 一格 ⇒ 服务端文案缺失时照样端出技术语言。', '🔴 **判据（行为面）**：服务端文案优先（业务原因逐字透出）；**传输层原文绝不外传**（缺服务端文案 ⇒ 落到业务兜底话术）；反向自证 —— 非传输层的本地错误（客户端校验等）仍用自己的 `message`（不是把 `message` 一律禁掉）。承载体 = `frontend/admin-web/tests/unit/lib/server-error-copy.test.ts`。', '🔴 **判据（形态面，类级）**：`src/app` + `src/components` 全域扫描，禁止「`instanceof Error ? <x>.message`」这种把错误对象 message 当展示文案的写法（改前 9 处：智能派单 1 / 知识库 8 / 省料看板 1）—— 注入任一形态 ⇒ 具名报出该文件。', '⚠️ **本次未固化的那一半（照实登记）**：服务端 2026-10-17 那次 422 的**具体业务原因**要在真实环境复现才能定名（本机两个 admin-api 实例的日志里都没有该请求：:8080 的实例自 03:53 起连不上云 dev RDS、:8180 的实例 07:15~07:22 只有定时任务的 SQL）⇒ 本条只保证「服务端给了什么文案，商家就看到什么」；改后同一次失败会把服务端原文打在卡片上（报错原因具备可见性）。'],
    skip_reason='[backend-contract] 纯前端错误文案 / 纯函数，由 vitest 单测覆盖，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'copy', 'error-message'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-116 [NORMAL] 作业单两型可见面：作业看板 / 订单详情统一「作业单」+ 中文类型标签；`outbound` 型不显示加工方与交期；机器键不上屏（源: cases/ui.yml）──
_CASE_UI_116 = EvalCase(
    id='UI-116',
    legacy_id='',
    title='作业单两型可见面：作业看板 / 订单详情统一「作业单」+ 中文类型标签；`outbound` 型不显示加工方与交期；机器键不上屏',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 逐字：「……原设计是想规定好成品帘加工路线和单布料售卖的路线……但是单布料售卖是不应该生成加工单的，现在仍然是个功能缺口」（附「工艺路线」页截图）'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **类型必须在界面上看得见，且是中文**：`order_kind='outbound'` 的作业单在作业看板/订单详情渲染**「出库作业单」**，`processing` 渲染**「加工单」**。红证：把标签渲染去掉 ⇒ 该行取不到该文案（`queryByText` 为 null）。", '判据 2·🔴 **机器键绝不上屏**：页面上**不得**出现 `processing` / `outbound` / `order_kind` 这些标识（本仓既有「JSX 文本位机器键」跨页面元守卫会上红）。红证：把 `{po.order_kind}` 直接渲染进 JSX ⇒ 具名报出。', '判据 3·**`outbound` 型不渲染加工方 / 交期**：卖布单没有加工方与交期这两个概念 ⇒ 相关字段与写面（含「发加工」动作）在 `outbound` 型上不出现；`processing` 型**照旧全渲染**（反向护栏：不许把成品帘面砍掉）。', '判据 4·**缺键 = 存量单，按加工单处理**：读面 `order_kind` 缺席（存量单）时按 `processing` 渲染，**不得**渲染成空白或未知态。', '判据 5·**工艺路线页口径同步**：「布料工序路线」的说明文案改成「卖布单的**出库作业**（裁剪 / 打包）」这一口径（改前写「这两条是窗帘单与布料单各自的主线」）。', '**未覆盖面（照实登记，不粉饰）**：工人端 `frontend/worker-h5/**` 与 `frontend/bmini-app/**` 里「加工单」措辞的同族收敛**不在本条** —— 那条面（洗水码/扫码页/离线报工）本轮未改，重启条件 = 工人端做一次同族文案巡检时一并收口。'],
    skip_reason='[backend-contract] 纯前端渲染与文案（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'production', 'processing-order', 'copy', 'order-kind'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-114 [NORMAL] demo path spec 的占位符选择器活性：`tests/e2e/**` 里每个 `getByPlaceholder(...)` 字面量必须在 admin-web 源码里逐字活着（源: cases/ui.yml）──
_CASE_UI_114 = EvalCase(
    id='UI-114',
    legacy_id='',
    title='demo path spec 的占位符选择器活性：`tests/e2e/**` 里每个 `getByPlaceholder(...)` 字面量必须在 admin-web 源码里逐字活着',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=[],
    expectations=[],
    data_checks=["判据 L1·🔴 **射程内每个占位符字面量必须在被驱动面里活着**：`tests/e2e/**/*.ts` 的 `getByPlaceholder('X')` / `getByPlaceholderText('X')` 的 `X`，必须在 `frontend/admin-web/src/**` 的 `.ts`/`.tsx` 里**逐字**出现。证据 = tests/unit_ci_workflows/test_e2e_placeholder_liveness.py::test_every_e2e_placeholder_literal_is_alive_in_admin_web。**红证（真回归实跑，2026-10-17）**：四包集成树里（源码已改、e2e 未修）该判据红，具名逐字为 `tests/e2e/specs/orders/processing-orders.spec.ts 的 getByPlaceholder('请输入加工单号或订单号') 在 frontend/admin-web/src/** 里取不到逐字文案`（该文件两处 fill 同因）—— 与 CI 那条腿点的**同一个文件**。", '判据 L2·**反空跑（fail-closed）**：射程（`getByPlaceholder` 字面量）为空 ⇒ 红 —— spec 被改名/搬走、或调用换成了变量时，不许把「没有可比对的东西」读成通过。', '判据 L3·**判别力自证（反恒真）**：好形态（字面量在源码里）不报；坏形态具名报出（含本次真实漏网的那个字面量）；且 `getByPlaceholder` / `getByPlaceholderText`、单双引号两种拼写都认。', '**边界（照实登记）**：① 射程只到**占位符**这一档 —— `getByText` / `getByRole(name)` / `getByLabel` 的同族字面量**不在本条**（现取 397 / 330 / 14 处，多数是运行期数据，静态判据会假红）；② 判据是「字面量在不在源码里」，**不是**「Playwright 真能定位到它」—— 运行期真实定位由 CI 的 `Demo path specs (admin-web, fixture mode)` 腿承担，本条的绿**不能**替代它；③ 不含 `scripts/ui-smoke-merchant/spec.mjs`（那是 test_ui_smoke_selector_liveness.py 的射程，两处不互为副本）。'],
    skip_reason='[backend-contract] 纯静态源码判据（读 `tests/e2e/**` 与 `frontend/admin-web/src/**` 的字面量对账），零网络、非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'e2e', 'selector-liveness', 'copy-drift', 'class-level-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-115 [NORMAL] **卖布单在订单详情的「生成作业单」出口**：发货前是否需要作业由读面给出（`needs_work` / `work_order_kind`），详情空态/生成按钮、发货页守卫、详情发货入口三处都用它（issue #7079 第 5 包）（源: cases/ui.yml）──
_CASE_UI_115 = EvalCase(
    id='UI-115',
    legacy_id='',
    title='**卖布单在订单详情的「生成作业单」出口**：发货前是否需要作业由读面给出（`needs_work` / `work_order_kind`），详情空态/生成按钮、发货页守卫、详情发货入口三处都用它（issue #7079 第 5 包）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['卖布单（按米卖布）在订单详情里为什么没有生成作业单的按钮？空态还写着「无加工项订单无需加工环节」，可它明明要先裁剪打包报工。'],
    expectations=['direct_reply'],
    data_checks=['🔴 **判据 1（会红，前端可见面）**：卖布单（`work_order_kind = outbound`、`processingItems` 为空）且无作业单 ⇒ 订单详情「作业单」区块必须出现**「去智能派单」**入口 + 按型说明（业务名取 `ORDER_KIND_LABELS`，不新造词），且屏上**不出现**机器键 `outbound` / `work_order_kind`。🔴 issue #7634 起生成入口**一律**收走（不再按型/按加急给「生成…」按钮）⇒ 判据看的是「按型说明 + 派单页入口」，不是「生成按钮」。执行点 = `frontend/admin-web/tests/unit/components/ProcessingOrderBlock.test.tsx`（`UI-115 判据 1`）。**红证**：把按型说明换回无型文案（丢掉 `ORDER_KIND_LABELS`）⇒ 红。', '🔴 **判据 2（会红，不实文案）**：空态文案**不得**再出现「无加工项订单无需加工环节」——它对卖布单**不实**（卖布单正需要裁剪/打包作业）。需要作业但当前状态还不能派单 ⇒ 显示按型的**可行动**说明（「该订单需要作业单（出库作业单），当前状态还不能派单」+ 下一步是什么）；无需要报工的作业 ⇒ 「该订单无需作业单（没有加工项，也不是卖布单）」。执行点 = 同文件 `UI-115 判据 3/4`。**红证**：把空态改回那句旧文案 ⇒ 判据 3 红。', '🔴 **判据 3（会红，发货页前置守卫）**：卖布单在 `/orders/{id}/ship` 必须被**前置阻断**（不渲染发货表单「确认发货 / 确认物流」）+ 可行动出口（「返回订单详情」）+ 按型引导句（「该订单是卖布单：先完成出库作业单的裁剪与打包报工，再发货」）；作业单已完成 ⇒ 放行；**无作业**的普通单（`work_order_kind` 缺键）⇒ 不查作业单、直接渲染表单（不许误拦）。执行点 = `frontend/admin-web/tests/unit/components/ShipOrderGuard.test.tsx`（`UI-115 判据 1~4`）。**红证**：把守卫退回 `order.processingItems?.length > 0` ⇒ 卖布单那 3 条红。', '🔴 **判据 4（会红，详情页发货入口）**：订单详情的发货入口对卖布单同样有前置提示（按型引导句），作业单已完成才出可点的「发货」。执行点 = `frontend/admin-web/tests/unit/components/OrderDetailShipGuard.test.tsx`（`UI-115 判据 5~7`）。**红证**：退回 `processingItems` 单侧判据 ⇒ 卖布单直接渲染「发货」按钮 ⇒ 红。', '🔴 **判据 5（会红，读面同源）**：`OrderShipGuard.requiredOrderKind` 与 `needsWork` **必须同源**（有型 ⇔ 需要作业），且逐值：全卖布行 ⇒ `outbound` / 含加工项或混合 ⇒ `processing` / 无作业 ⇒ `null`；卖布行以 JSON **字符串** 形态出现时仍判出库。执行点 = `backend/admin-api/src/test/java/com/migao/admin/service/OrderShipGuardTest.java`（`requiredOrderKind*` 6 条）。**红证**：让 `hasFabricSaleLine` 恒假 / 按 `processingItems` 单侧判 ⇒ 红。', '🔴 **判据 6（会红，读面接线）**：`OrderService.convertToDetailResponse` 必须真的调用 `OrderShipGuard.requiredOrderKind` 并把结果落到响应（`setNeedsWork` / `setWorkOrderKind`），DTO 上两个键必须是显式 `@JsonProperty`（snake_case 冻结键）。执行点 = `backend/admin-api/src/test/java/com/migao/admin/service/OrderDetailWorkSignalReadFaceTest.java`（含判别力自证：判据本体不接线 / 结果不落响应 / 摘掉 `@JsonProperty` / 方法体取不到，四种坏形态各自判红；只往注释里加字面量 ⇒ 一条都不红）。**红证**：把 `requiredOrderKind(` 换成 `hasProcessingItems(` ⇒ 红。', '📌 **为什么这是缺陷不是新需求**：卖布单生成作业单的**能力早就有**（`ProcessingOrderService.prepare` 的门是 `snapshot.isEmpty()`，而 `buildSnapshot` 对 `saleForm=布料` 的行使**保留**），派单池与 AI 工具两条出口都通；断的只是**读面没把「要不要作业」交给前端** ⇒ 商家在订单详情看不到出口，而刚被发货守卫拦下时收到的却正是「须先完成出库作业单的裁剪与打包报工」——两个面互相矛盾。', '📌 **边界（照实登记）**：本用例**不判**「作业单该由谁生成」（派单池 / AI 工具 / 详情按钮三条路都合法）；也**不判**「卖布单该不该走作业」（那是 issue #7079 ②/③ 的产品裁定，已定）；`order_kind` 的三源词表（后端常量 / V159 的 CHECK / 前端联合类型）本包**未动**。'],
    skip_reason='[backend-contract] 前端可见面判据（vitest 渲染断言）+ 后端行为/接线判据（JUnit）；零网络、零时钟、非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'processing-order', 'fabric-sale', 'read-face-signal', 'ship-guard', 'dead-end-exit', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置 = 四样都在仓里可读：① 判据本体 `backend/admin-api/src/main/java/com/migao/admin/service/OrderShipGuard.java`（`needsWork` = 含加工项 **或** 有卖布行；`requiredOrderKind` = 该判据的读面形态）；② 读面键 `backend/admin-api/src/main/java/com/migao/admin/dto/OrderDetailResponse.java` 的 `@JsonProperty("needs_work")` / `@JsonProperty("work_order_kind")`；③ 前端唯一读点 `frontend/admin-web/src/lib/processing-order.ts` 的 `workOrderKindOf`；④ 三处消费面组件（`ProcessingOrderBlock` / `ship/ShipOrder` / `OrderDetail`）。**前置不成立时不许读成通过**：接线判据取不到 `convertToDetailResponse` 方法体 ⇒ fail-closed 判红（不许读成「没有违规」）。',
)

# ── UI-113 [NORMAL] **「页面声明的筛选区必须由原语承载」的类级元守卫**：凡页面自报 `search-area` 的筛选区，承载标签必须是 `SearchPanel` / `SearchBar` / `PageCard`，不得是裸 `div`（issue #7116，承接 #7007 根因③）（源: cases/ui.yml）──
_CASE_UI_113 = EvalCase(
    id='UI-113',
    legacy_id='',
    title='**「页面声明的筛选区必须由原语承载」的类级元守卫**：凡页面自报 `search-area` 的筛选区，承载标签必须是 `SearchPanel` / `SearchBar` / `PageCard`，不得是裸 `div`（issue #7116，承接 #7007 根因③）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['为什么只有订单页看起来精致，其它页面没有这种感觉？'],
    expectations=['direct_reply'],
    data_checks=['🔴 **判据 1（会红）**：射程 = `frontend/admin-web/src/app/(dashboard)/**` 下**每个页面**。凡页面上**自己声明**了筛选区（`data-testid="search-area"` 或 `PageCard` 的 `testId="search-area"`），其**承载标签必须是原语**（`SearchPanel` / `SearchBar` / `PageCard`）——**不得是裸 `<div>`/`<section>`**，否则判红并点名「文件 + 承载标签」。**红证（实跑、逐字节还原）**：迁移前实测 `orders/page.tsx` 与 `after-sales/page.tsx` 各自以裸 `<div>` 承载 ⇒ 判据 1 红并点名两页；迁完两个原语后转绿。', '🔴 **判据 2（反空转）**：射程内「显式声明」**加**「用了 `SearchPanel` 的页面」合计 **≥ 5**（现取：显式 2 + 用原语 3）⇒ 防「把声明或原语都删掉」让判据 1 空转；另断言三个原语文件真实存在。', '🔴 **判据 3（判别力自证）**：坏形态（`<div … data-testid="search-area">`）判红、好形态（`<SearchPanel … testId=` / `<PageCard testId=`）放行；**没有声明 ⇒ 不产生任何判定**（不猜 —— 见下条）。', '📌 **为什么只认「页面自己声明的」**（射程**有意收窄**）：本仓标记「筛选区」的方式不统一，靠「这页有没有查询按钮 / 搜索框」去猜**会把新建单据表单误判成筛选区** —— 实测 `orders/new/page.tsx` 有搜索框 + 查询 + 重置，但它是**下单表单**、不是筛选区。⇒ 判据只承认页面自报的意图，不猜。', '📌 **病灶（#7007 根因③）**：用户原话「只有订单管理精美」。`#7012` 抽出了 `SearchPanel` 原语，但**落地只有 1 页**（`customers`），而 `PageCard` 被 9 页拿去做筛选外壳 —— 共享件造出来没落地。', '📌 **本单交付**：`orders` / `after-sales` / `employees` 三页迁到 `SearchPanel`（无状态原语，页面自持筛选 state），迁移后 `SearchPanel` 落地从 **1 页 → 4 页**。`orders` 那页正是「单一响应式 grid / 标签左置 / 按钮独占一行」这一版的**母版**（`#5880` 打磨出来的就是它）—— 迁回去等于把母版接回原语，而不是发明新形态。', '📌 **`products` 有意未迁（照实登记）**：它用的是**两行独立栅格**（`md:grid-cols-2` + `md:grid-cols-[1fr_1fr_auto]`）+ 防抖 URL 同步，与 `SearchPanel` 的单一 grid 版式不同；且它**已经用 `PageCard` 承载**（判据 1 认可的合法形态）⇒ 不属本判据的违规面。重启条件：真要做「筛选区版式全统一」时，先给 `SearchPanel` 定「多行栅格」形态。', "📌 **迁移过程中的一处真实性修正（值得记）**：`employees` 迁移后有 1 条断言翻红，我一度误判为「迁移引入行为变化」。实测请求序列迁移前后**逐字相同**（`[{page,size}, {page,size,keyword:'张'}]`），真因是**交互与挂载请求的竞争**：断言 `waitFor(toHaveBeenCalled())` 被**挂载那次**满足 ⇒ 读到的是挂载入参（不带 keyword）。修法 = 交互前**先等挂载请求落地**（不是放宽断言、不是改产品代码）。\n  ⚠️ 过程中我一度把「测试超时」误读成「通过」（`vitest` 对 `-t` 过滤时把未选中用例显示为 skipped），差点据此得出错误结论 —— **判读测试结果必须看 `Tests N passed/failed` 汇总行，不能只看有没有 ×**。"],
    skip_reason='[backend-contract] 前端静态判据（扫 TSX 源码判承载标签 + 冻结下界对账），零网络、零时钟、非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'design-consistency', 'filter-area', 'shared-primitive', 'class-guard', 'red-proof'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='前置 = 三样都在仓里可读：① 无状态筛选原语 `frontend/admin-web/src/components/ui/SearchPanel.tsx`（`fields[].control` 由页面渲染、单一响应式 grid、`testId` 默认 `search-area`）；② 有状态轻量筛选条 `frontend/admin-web/src/components/ui/SearchBar.tsx`；③ 守卫本体 `frontend/admin-web/tests/unit/filter-area-primitive-guard.test.ts`。**前置不成立时不许读成通过**：射程目录取不到 ⇒ `walk()` 抛（fail-closed）；页面数 ≤ 40、或「声明 + 原语」合计 < 5 ⇒ 反空跑判红。',
)

# ── UI-117 [NORMAL] 岗位权限页默认菜单 = 后台 + 手机端（一份权限码两面投影）+ 只读工人卡；岗位描述只留职责（issue #7146）（源: cases/ui.yml）──
_CASE_UI_117 = EvalCase(
    id='UI-117',
    legacy_id='',
    title='岗位权限页默认菜单 = 后台 + 手机端（一份权限码两面投影）+ 只读工人卡；岗位描述只留职责（issue #7146）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['手机端可见面要不要作为「默认岗位默认菜单」的一部分，当然需要，把 PC 和手机端当一个整体'],
    expectations=['direct_reply'],
    data_checks=['岗位权限页每张岗位卡：同一处同时给「后台 N 项」与「手机端 M 个入口」（默认收起 = §31 P1；展开看两份清单）；后台名逐字取 config/menu（与侧边栏同源），手机端面名逐字取服务端 GET /api/admin/menus 的 mobileTitles（夹具改名 ⇒ 页面跟着改，证明前端无第二张表）；没有手机端码的岗位显示 0（不是「全给」、不是报错）', '岗位描述 roles.description 只承载「职责：…」散文：不得再出现「默认可用模块：」（模块清单必须派生，否则是第二份会漂的真值）；判据 = tests/unit_ci_workflows/test_role_descriptions.py 判据 A（注入「默认可用模块：」⇒ 具名红）', '只读「工人」卡：工人端默认 5 页（页键 + 人话名取 GET /api/admin/worker-pages），卡内**没有**编辑/删除按钮、给出「员工管理 → 工人档案」链接；目录读失败 ⇒ 显式失败态 + 重试（不画成「没有页面」）', '零授权 delta：本单不改 role_permissions / users.permissions；手机端写码仍由商家在权限树逐人勾（#6759）', '存量租户：V162 只改「仍是 V161 默认文案」的行（商家自定义描述不动），终态对账 fail-closed；V161 渲染输入冻结（活清单前进不动它）'],
    skip_reason='[backend-contract] 前端派生/只读卡由 vitest 验证；岗位描述职责-only 由 pytest 常驻判据验证；均零网络、零 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'position', 'role', 'menu', 'mobile', 'worker'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-118 [NORMAL] 质检记录页（`/quality-inspections`）：质检指标 + 质检流水（判定入口只在手机端；PC 待检清单/录入判定已于 2026-10-27 移除）（源: cases/ui.yml）──
_CASE_UI_118 = EvalCase(
    id='UI-118',
    legacy_id='',
    title='质检记录页（`/quality-inspections`）：质检指标 + 质检流水（判定入口只在手机端；PC 待检清单/录入判定已于 2026-10-27 移除）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 逐字：「之前让你做过质检流程，我看在观星台上没有任何地方体现出来了」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·🔴 **PC 不再读待检清单 / 不再录入判定（2026-10-27 改判）**：页面零调用 `qualityInspectionApi.targets`，无 `quality-targets-card`、无「录入判定 / 复检」按钮、无「未检 N 件」摘要行。红证：把 targets 读回页面 ⇒ ① 用例当场红。证据：frontend/admin-web/tests/unit/pages/quality-inspections.test.tsx（①）', '判据 2·**指标面板照旧**：默认「本月」拉一次；首检合格率与样本量同屏（服务端算率，前端只格式化）。证据：同文件（②）', '判据 3·🔴 **读失败 ≠ 没有数据**：流水读失败 ⇒ 失败锚（role=alert）常驻、不画空态；空态只在真的 0 条时出现。证据：同文件（③ ④）', '判据 4·**流水客户端分页**：25 条 ⇒ 第 1 页 10 条、翻页看第 2 页（读面无服务端分页）。证据：同文件（⑤）', '判据 5·**入口只在手机端**：页面如实说明质检员在手机端扫码录入（改判的可见面）。证据：同文件（⑥）', '**边界（照实登记，2026-10-27）**：PC 关掉录入是为了避免「同一件判定两个录入口」；`GET /api/admin/quality-inspections/targets` 服务端保留（供手机端队列演进），PC 不消费。作业单内嵌质检区（UI-119）不在本次改动内，另单评估。', '**边界（照实登记）**：流水读面（`GET /api/admin/quality-inspections`）没有分页 ⇒ 本页**截断展示最近 20 条**并在标题上写明（不假装是全部）；重启条件 = 该读面加分页。不做时间范围筛选（读面无该入参，前端过滤 = 第二份口径）。'],
    skip_reason='[backend-contract] 纯前端渲染与交互（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'production', 'quality-inspection', 'read-failure', 'copy'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-119 [NORMAL] 作业单生产明细内嵌**质检区**：逐件成品帘最新判定（未检 = 未检）+ 录入/复检入口；读失败不画成「没有质检」（issue #7140）（源: cases/ui.yml）──
_CASE_UI_119 = EvalCase(
    id='UI-119',
    legacy_id='',
    title='作业单生产明细内嵌**质检区**：逐件成品帘最新判定（未检 = 未检）+ 录入/复检入口；读失败不画成「没有质检」（issue #7140）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 裁定①：落位 = 生产管理组新增菜单 **+** 作业单生产明细内嵌质检区'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**逐件成品帘显示最新判定**：有记录 ⇒ 渲染服务端判定（含原因 / 检验人 / 检验时刻）；无记录 ⇒ **「未检」**（不是空白、不是「合格」）。证据：frontend/admin-web/tests/unit/components/QualityCheckPanel.test.tsx', '判据 2·🔴 **最新一条胜出**：同一件多条记录时取读面给的**第一条**（服务端已按时间倒序）—— 见证行故意让第二条的时间更晚，组件仍取第一条 ⇒ 证明前端**没有**第二份排序口径。证据：同文件（② 用例）', '判据 3·**录入口在单上**：未检 ⇒「录入判定」、已判 ⇒「复检」，点开同一表单；提交体带上**这一件成品帘**的 id。证据：同文件（③ 用例）', '判据 4·🔴 **读失败不画成「本单没有质检」**：失败锚常驻，空态**不出现**、逐件行不渲染。证据：同文件（④ 用例）', '**权限面（不在本用例的断言里，登记在此）**：质检区只在持 `production:inspect` 时渲染（权限门在**调用方** `processing-orders/[id]/production/page.tsx`，组件自己不再判一次 —— 避免两处口径）；读权限**零放宽**（用户裁定③）。'],
    skip_reason='[backend-contract] 纯前端渲染与交互（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'production', 'quality-inspection', 'read-failure'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-120 [NORMAL] 工序进度表**三态数量列**（合格 / 返工 / 报废）：返工报废不进进度、与「已完成数量」分列、缺报工渲染 0（issue #7140）（源: cases/ui.yml）──
_CASE_UI_120 = EvalCase(
    id='UI-120',
    legacy_id='',
    title='工序进度表**三态数量列**（合格 / 返工 / 报废）：返工报废不进进度、与「已完成数量」分列、缺报工渲染 0（issue #7140）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 裁定②：范围 = 一起补 —— 生产明细显示「合格/返工/报废」三列'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**三列表头都在**（合格 / 返工 / 报废）—— 此前 `rework_qty` / `scrap_qty` 在 admin-web **零消费者**（只有米宝读面能看到）。证据：frontend/admin-web/tests/unit/components/ProductionProgressTable-worktype.test.tsx', '判据 2·**逐工序渲染服务端下发的三态数量（含单位）**；缺报工 ⇒ 服务端给 0 ⇒ 渲染 `0`（不是空白、不是 `undefined`）。证据：同文件（② 用例）', '判据 3·🔴 **合格与「已完成数量」是两列**（见证行：`done_qty=10` / `qualified_qty=7` 故意不等）—— 返工 / 报废**既不推进进度也不计件**（既有口径），本表**不为它们做合计**（避免被读成「已完成 = 合格 + 返工 + 报废」）。三天不做合计这件事**不在**本用例的机器断言里（它是「没有写」的事实）⇒ 靠本条的方案注释 + 代码评审承担。'],
    skip_reason='[backend-contract] 纯前端渲染（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'production', 'quality-inspection', 'worklog'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-121 [NORMAL] 工人档案：质检页逐人开（新建弹窗「单独开放」一栏 + 列表行「开/关质检」）；默认页面不含质检、未收窄显示「默认页面」（源: cases/ui.yml）──
_CASE_UI_121 = EvalCase(
    id='UI-121',
    legacy_id='',
    title='工人档案：质检页逐人开（新建弹窗「单独开放」一栏 + 列表行「开/关质检」）；默认页面不含质检、未收窄显示「默认页面」',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-17 裁定：「工人档案逐人开质检页，服务端同时当写准入」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**质检不在默认菜单里**：新建弹窗的默认页勾选栏（`worker-page-option-*`）不含 `inspect`；它出现在「单独开放」一栏（`worker-page-optional-inspect`），默认未勾。红证：把 inspect 加进默认集合 ⇒ 判据当场红。证据：frontend/admin-web/tests/unit/components/WorkerProfilesPanel.test.tsx（⑨）', '判据 2·**勾上 ⇒ 建号请求带它**：默认四页 + 单独勾质检 ⇒ `workerPages = [report, order, cut_calc, shipment, inspect]`（收窄列表，不是 null）。证据：同文件（⑨）', '判据 3·**已有工人可开/关**：列表行「开质检」⇒ `PUT /api/admin/workers/{id}/pages` 带默认页 + inspect；「关质检」⇒ 去掉 inspect（回到收窄集）。证据：同文件（⑨ 第二条）', '判据 4·**口径显示**：未收窄（null / 空数组）⇒「默认页面」（不再是「全部页面」—— 全部能力还包含逐人开的质检）。证据：同文件（⑧）', '**上游形状**：`GET /api/admin/worker-pages` 回 `{pages, default_pages, optional_pages, labels}`（服务端唯一真值）；`inspect` 在 pages、不在 default_pages、在 optional_pages。证据：backend/admin-api/src/test/java/com/migao/admin/controller/WorkerPageCatalogControllerTest.java', '**边界（照实登记）**：本页只决定「开不开放」；真正的写准入在 `/api/worker/quality/**`（服务端 403），不是前端隐藏按钮。'],
    skip_reason='[backend-contract] 纯前端配置面（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['worker-profile', 'quality-inspection', 'permission', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-122 [NORMAL] 配置面的字段只有一种写法：区块 = 浅底面板 + 标题 + 说明，字段 = 标签在上 + 控件满列 + 单位入框（共享原语 + 类级守卫）（源: cases/ui.yml）──
_CASE_UI_122 = EvalCase(
    id='UI-122',
    legacy_id='',
    title='配置面的字段只有一种写法：区块 = 浅底面板 + 标题 + 说明，字段 = 标签在上 + 控件满列 + 单位入框（共享原语 + 类级守卫）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-18 裁定：「第二张图（阈值试算）可以作为一个标准来参考，后续都要形成固定的设计风格和组件，我们一个产品不要出现多种设计和风格样式」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**区块形态**：配置面的区块 = `FormPanel`（`rounded-lg border border-neutral-200 bg-neutral-50/50 p-4` + `h4.text-sm.font-semibold` + 可选一句 `text-xs` 说明）。证据：frontend/admin-web/src/components/ui/FormPanel.tsx', '判据 2·**字段形态**：标签在上（`label.text-xs`）、控件满列（`FIELD_CONTROL` 带 `w-full h-9 rounded-lg border border-neutral-300` + 主色聚焦环）、单位做**框内后缀**（带单位时 `pr-9`）。证据：同文件 + frontend/admin-web/src/components/settings/OversizeThresholdPreview.tsx（基准面，by construction 不改像素）', '判据 3·**受管面必须继续用原语**：算料口径全域（标量 / 档位与拼色 / 备用用料公式）、阈值试算、裁剪高度「预演（只读）」都从 `components/ui/FormPanel` 取字段版式（改回手拼 ⇒ 红）。证据：frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx、frontend/admin-web/tests/unit/design-system-form-fields.test.tsx', '判据 4·**「档位与拼色」不再是贴内容的小表**：两张 `w-fit` 小表在内容宽 764 时右侧空出 79px（读数）；改成两个并排 `FormPanel` 后 blank = 0，且每档 = 两个字段（显示名 / 褶倍）、拼 N 次 = 一个字段（单位入框）。证据：前端单测的 `calc-caliber-group-tiers` / `calc-caliber-group-mixed` 锚点 + PR 截图', '判据 5·**类级守卫**：业务面自己拼控件铬（`h-9 ... rounded-lg ... border-neutral-300` 字符串）⇒ 红；「标签顺排在控件左边」（`ml-1 inline-block`）⇒ 红；两处存量按台账**双向相等 + 只许缩短**。红证：守卫内有内存注入自证（造一份第二铬 / 一段旧形态源码 ⇒ 当场红并具名）。证据：frontend/admin-web/tests/unit/design-system-form-fields.test.tsx', '**边界**：本单不改字段、默认值、保存语义、422 逐条理由与算料口径（纯版式）；美化本身仍由 §15.7 读图 + 人裁定。'],
    skip_reason='[backend-contract] 纯前端配置面（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['design-system', 'settings', 'form-field', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-125 [NORMAL] 算料口径改「变更即保存」：删掉保存 / 恢复默认两个按钮，防抖 0.6 秒自动 PUT（422 逐条理由、草稿不回滚）（源: cases/ui.yml）──
_CASE_UI_125 = EvalCase(
    id='UI-125',
    legacy_id='',
    title='算料口径改「变更即保存」：删掉保存 / 恢复默认两个按钮，防抖 0.6 秒自动 PUT（422 逐条理由、草稿不回滚）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-18 裁定：「这里的两个按钮应该移除，一是不需要恢复默认功能，而是应该让用户在输入框变更后即保存，这样增加界面简洁程度提高了用户体验」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**全域零保存 / 恢复默认按钮与吸底条**（`calc-caliber-save` / `calc-caliber-restore-defaults` / `calc-caliber-save-dock` 取不到），且「没有保存按钮」这件事被写出来（「修改后自动保存（约 0.6 秒），无需手动提交」）。证据：frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx（判据 9·a）', '判据 2·**变更即保存 600ms**：改一个标量 ⇒ 599ms 时 0 次、600ms 后 `onCalcSave` 恰好 1 次；期间输入框**不**禁用。证据：同文件（判据 9·b）', '判据 3·**防抖合并**：窗口内连改两处 ⇒ 只发 1 次，正文带两处新值。证据：同文件（判据 9·c）', '判据 4·**首屏 / 读面刷新不写库**（基线 = 读面给的整份配置）：挂载后 5s 内 0 次；换一份新配置对象（页面读面落地同步草稿）后仍 0 次。证据：同文件（判据 9·d）', '判据 5·**在飞闸**：第 1 次未回来前再改两次 ⇒ 仍只有 1 次；回来后按最新草稿补发 1 次（不排队）。证据：同文件（判据 9·e）', '判据 6·**422 语义不变**：`details[].message` 逐条上屏、草稿不回滚（输入值仍在）、保存态「保存失败 · N 条理由」；改对后再改一次自动重试。证据：同文件（判据 9·f / f2）', '判据 7·**只读退化零请求**：不给保存回调（只给草稿回调）⇒ 5s 内 0 写请求、无保存态与自动保存说明。证据：同文件（判据 9·g）', '判据 8·**页面这一跳也是全量键**：`PUT` 正文逐键齐全（11 键），改的键是新值 —— 触发方式改为防抖自动保存。证据：frontend/admin-web/tests/unit/pages/settings.test.tsx（算料口径域保存）', '判据 9·**类级写面守卫口径不变**：域写面出口标记从保存按钮迁到保存态（`data-write-exit` 仍带 `calc`），逐域 traversal 与「写出口成对」判据仍绿。证据：frontend/admin-web/tests/unit/lib/domain-write-surface.test.tsx（判据 4 / 写出口成对）', '**边界**：不碰后端、不改 422 理由结构；「恢复为默认值」**不给替代入口**（用户明确不要），引擎默认值仍由 `source` 徽标与「本企业尚未保存过算料口径」横幅承担；面板卸载（切域）时待发的那一次仍会发出。证据：同文件（判据 9·h）'],
    skip_reason='[backend-contract] 纯前端配置面（vitest 单测覆盖），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['settings', 'craft-calc', 'autosave', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-123 [NORMAL] 旧「工艺配置」页已下架：/production/routings 重定向到唯一写面，且全仓不再有写死的旧链接（源: cases/ui.yml）──
_CASE_UI_123 = EvalCase(
    id='UI-123',
    legacy_id='',
    title='旧「工艺配置」页已下架：/production/routings 重定向到唯一写面，且全仓不再有写死的旧链接',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-18 报障：「原工艺配置页面怎么未下架，从计件工资提示链接可以跳转到原页面，这里应该跳转到新页面了」'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**旧路由重定向**：渲染 `/production/routings` ⇒ `router.replace('/settings?domain=operation-prices')`，且不渲染任何内容（不 404、不落空白）。证据：frontend/admin-web/tests/unit/pages/production-routings-legacy.test.tsx", '判据 2·**旧链接不再存在**：`src/` 里没有写死的 `href` / `redirect(` / `router.push|replace(` 指向 `/production/routings`（注释里的历史说明、`page-context` 的路由映射、`layout.tsx` 的权限前缀不算链接）。证据：同测试文件的 `linksToRetiredRoute()`', '判据 3·**定价入口与文案同源**：计件工资「去定价」的落点常量 = `/settings?domain=operation-prices`（文案写的是「企业基础设置 → 工序与部位单价」）。证据：frontend/admin-web/tests/unit/components/UnpricedNotice.test.tsx、ProductionProgressTable.test.tsx、PieceworkTable.test.tsx', '判据 4·**功能体仍有覆盖**：原借旧页当壳的两个测试改为直接渲染 `ProcessConfigBoard`（覆盖不随页面下架一起消失）。证据：OperationsScopeColumn.test.tsx、OperationsProvenance.test.tsx'],
    skip_reason='[backend-contract] 本用例判的是 admin-web 的**旧路由下架 + 链接面**（/production/routings → 重定向 /settings?domain=operation-prices、全仓无写死旧链接），**没有 Agent 面可跑**：user_inputs 是用户 2026-10-18 的报障原文，expectations 的 direct_reply 只是占位。承载体 = traces.tests 里的 6 个前端单测。2026-10-19 mibao 基线实测它被当成 LLM 用例跑（agent 调 nav_guide / craft_calc_config_query 等 ⇒ 误判红灯，issue #7027）。',
    tags=['navigation', 'settings', 'route-retirement', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-124 [NORMAL] 按钮只有一种形态：icon slot 统一间距、loading 时 spinner 顶替图标（不并排）、裸 button 不得自拼主色 chrome（源: cases/ui.yml）──
_CASE_UI_124 = EvalCase(
    id='UI-124',
    legacy_id='',
    title='按钮只有一种形态：icon slot 统一间距、loading 时 spinner 顶替图标（不并排）、裸 button 不得自拼主色 chrome',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-18 裁定：「还是老问题，按钮样式未统一 …… 制定一个统一规范并执行落地」「这个规范包含观星台所有功能，PC&手机端」'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**icon slot**：前置图标走 `Button` 的 `icon` prop（slot 给 `mr-1.5 shrink-0` 且 `aria-hidden`），调用方不再手写 `mr-*`。证据：frontend/admin-web/tests/unit/design-system-buttons.test.tsx', '判据 2·**loading 顶替**：`loading` 时只渲染 spinner，页面自带图标不出现（并排 = 双图标，真机读成「图标重叠」）；`aria-busy` 随 loading。证据：同文件', '判据 3·**尺寸 token**：sm=h-8 / md=h-9 / lg=h-10，圆角 rounded-lg（改映射 ⇒ 红）。证据：同文件', '判据 4·**类级**：裸 `<button>` 不得自带主色 chrome（`bg-primary-600`）；存量 10 处按冻结台账只许缩短，新增文件/同文件变多 ⇒ 红并具名。证据：同文件 `NAKED_PRIMARY_LEDGER`', '迁移面：工艺配置（刷新/新增工序/新建路线）、加工项与分类（加工分类/新增加工项）、加工费组合（新建组合）、工序与部位单价（刷新/新增工序）—— 全部改走 `icon` slot。证据：frontend/admin-web/src/components/production-config/*.tsx'],
    skip_reason='[backend-contract] 本用例判的是 admin-web 的**设计系统按钮形态**（icon slot / loading 顶替 / 尺寸 token / 裸 button 冻结台账），**没有 Agent 面可跑**：user_inputs 是用户 2026-10-18 的裁定原文，expectations 的 direct_reply 只是占位。承载体 = traces.tests 里的前端单测。2026-10-19 mibao 基线里它同样被当成 LLM 用例跑（issue #7027）。',
    tags=['design-system', 'button', 'ui'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-127 [NORMAL] 订单详情权限（order:detail）真正生效：详情/发货两读面收码 + 页面拒绝态 + 无权限的加工单块不发起请求（issue #7276）（源: cases/ui.yml）──
_CASE_UI_127 = EvalCase(
    id='UI-127',
    legacy_id='',
    title='订单详情权限（order:detail）真正生效：详情/发货两读面收码 + 页面拒绝态 + 无权限的加工单块不发起请求（issue #7276）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「虽然页面上提示我没权限操作，但是我仍然能访问，RBAC权限没控制住？」（用户 2026-10-18）→ 裁定：让「订单详情」这个码真正生效'],
    expectations=['direct_reply'],
    data_checks=['判据 1·前端（会红）：frontend/admin-web/tests/unit/pages/order-detail-permission-gate.test.tsx —— 无 order:detail ⇒ 渲染拒绝态且零读请求；有 order:detail 无 production:view ⇒ 页可看、加工单块不渲染；两码都在 ⇒ 加工单块渲染（对照组）。修前实测 3 failed。证据：该文件三条用例', '判据 2·后端（会红）：AdminOrderShipmentReadTest#adminReadFaceCarriesTheSameReadCodeAsTheOrderDetailPage —— GET /api/admin/orders/{id} 与 .../shipments 的生效码都必须是 order:detail（改回 order:list ⇒ 红）。', '判据 3·台账：tests/unit_ci_workflows/test_agent_permission_parity.py 的 census —— order:detail.endpoints 非空、order:list 同步移除两条；工具 logistics_track 的 required_permissions ≡ 端点生效码（order:list + order:detail）。', '判据 4·类级元守卫（新增，目录级）：tests/unit_ci_workflows/test_rbac_derived_pages.py::test_every_grantable_code_has_a_server_side_enforcement_point —— 目录里**每个可授予的码**（含动作节点码）都必须在服务端强制面（admin-api 的 @RequirePermission，行首锚定）至少命中一次，否则具名判红；豁免台账 CODE_WITHOUT_ENFORCEMENT 只许缩短（现取 0：最后一条 product:manage 已按用户裁定删除），已接线或陈旧登记同样红；**手写门**（不在注解体系里的判定点，如 AdminGate 承载的 agent:chat）走 EXPLICIT_GATES 登记 + **活体校验**（门删了登记还在 ⇒ 红）—— 这是上一轮普查的真实盲区。UI 面（路由守卫/页面 has/菜单节点）**不算**强制点 —— 直接调 API 就绕过。'],
    skip_reason='[backend-contract] 权限/门控面（前端拒绝态 + Java 注解 + 静态台账）由 vitest 与 Java 单测验证，非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['rbac', 'permission', 'order-detail', 'class-level-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-128 [NORMAL] 纸面不带浏览器页眉页脚：全矩阵 @page 上下边距写 0（浏览器无可画之处）+ 版面内缩走 contentInset 与单据容器 padding、box-decoration-break: clone 逐页重复（issue #7309 → 2026-10-25 全矩阵收口）（源: cases/ui.yml）──
_CASE_UI_128 = EvalCase(
    id='UI-128',
    legacy_id='',
    title='纸面不带浏览器页眉页脚：全矩阵 @page 上下边距写 0（浏览器无可画之处）+ 版面内缩走 contentInset 与单据容器 padding、box-decoration-break: clone 逐页重复（issue #7309 → 2026-10-25 全矩阵收口）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「我建议拿掉打印的页头和页脚」（用户 2026-10-19，附 A4 报价单打印成品截图）', '「刚才发现打印预览的所有单子，水洗唛都带了打印页头和页脚，你把所有打印的功能都检查一遍，移除掉」（用户 2026-10-25）', '「可能默认勾着，我希望做到即使勾着也不要打印出页眉和页脚」（用户 2026-10-25）'],
    expectations=['direct_reply'],
    data_checks=["判据 1·**结构性去页眉页脚（全矩阵）**（会红）：介质矩阵 frontend/admin-web/src/lib/print-media.json 里**每一份浏览器打印的介质**上下 `pageMargin` 都必须是 0 —— a4 ⇒ contentInset=12mm、**continuous-241x140（三联纸）⇒ contentInset=6mm 12mm**（2026-10-25 由 `pageMargin: 6mm 12mm` 改 0，属于「靠 6mm < 实测下限 8.7mm 侥幸不画」的形态）；`printPageRule('a4') === '@page { size: A4; margin: 0; }'`、`printPageRule('continuous-241x140') === '@page { size: 241mm 140mm; margin: 0; }'`、可用版面逐值不变（a4 = 186 × 273mm、三联纸 = 217 × 128mm）。执行点 = frontend/admin-web/tests/unit/lib/print-media.test.ts 的「⑤ 纸面不带浏览器页眉页脚」+「③ @page 规则由 printPageRule 唯一生成」。", '判据 2·**类级元守卫**（会红）：tests/unit_ci_workflows/test_print_media_matrix_guard.py::test_c10_browser_chrome_stays_off_the_paper 与 frontend/admin-web/src/lib/print-media.ts::browserChromeMarginProblems —— 浏览器打印介质的上下 @page 边距**只要不是 0 就判红**（2026-10-25 由「≥ 8.7mm 才红」收紧：8.7mm 是实测下限、**不是容忍度**，判别力自证里专设一条「三联纸写回 6mm 12mm ⇒ 必红」）；边距 0 必须登记 contentInset；contentInset 存在 ⇒ 边距必须为 0；且受管单据的打印 CSS 必须带 printContentInsetCss( + box-decoration-break: clone（缺一即红，四张 A4/三联纸单据 + 洗水唛都在册）。', '判据 3·**逐页内缩**（会红）：四份单据（发货单 / 报价单 / 加工单 / 销售单）的 @media print 容器规则里 padding 取介质内缩、并带 box-decoration-break: clone。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的「③ 版面：@page A4（由介质矩阵生成）+ 分页不裁切 + 表头重复」、frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 的「② 介质是**参数**不是副本：切 A4 后 @page 变、而逐格取值**逐字不变**」。', '🔴 红证（实跑）：① 把 a4 的 pageMargin 改回 12mm ⇒ 判据 1/2 必红（本机读数：vitest 4 failed / 5 passed）；② 抹掉容器的 printContentInsetCss( 与 box-decoration-break: clone ⇒ C10 的单据侧必红（内存变异逐条常驻，见该测试的「判别力自证」）。', '真机读数（Chromium 1243 = Chrome 14x；displayHeaderFooter: true + preferCSSPageSize: true；A4；两页样张）：改前 @page margin 12mm ⇒ 纸面出现 `10/19/26, 11:08 AM 观星台 - AI经营管理平台` + `about:blank 1/2`（= 用户截图同款四行）；改后 margin 0 + 容器内缩 12mm + clone ⇒ 零浏览器页眉页脚，且第 1 / 第 2 页首行 y 坐标**相同**（798.42pt）= 逐页内缩成立、版面未变。**2026-10-25 复测（同一台机器上装的正式版 Google Chrome，channel=chrome；printToPDF + displayHeaderFooter: true + 强制 10mm 页边距参数）**：`@page { size: 50mm 70mm; margin: 0 }` ⇒ 纸面**零**页眉页脚；把 `margin: 0` 去掉（只有 `size`）⇒ 纸面立刻多出 `2026/10/25 15:34 观…` + `about:bl… 1/1` 四行（**与用户 2026-10-25 截图里的形态逐字同款**：zh-CN 24 小时日期 + 标题 + URL + 页码）。⇒ 结论收敛成一句可判据的话：**边距只要不是 0，浏览器就有画它的路；边距是 0，Chrome 无画可画**。'],
    skip_reason='[backend-contract] 纯前端打印版式（无 LLM 环节）：断言由 vitest 与 tests/unit_ci_workflows/test_print_media_matrix_guard.py 执行',
    tags=['print', 'a4', 'browser-chrome', 'class-level-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端纸面 / 源码级守卫用例：**没有运行期前置**（不连真实打印机、不依赖共享夹具与数据库）—— 判据全部由 frontend/admin-web 的 vitest 与 tests/unit_ci_workflows/ 的静态守卫执行，两者都在 PR CI 的 admin-web 腿与 pr-check 腿里常驻；纸面「观感」仍由真机验收覆盖（无人值守环境拿不到打印机），因此本用例判的是**结构性口径**（边距是否 0 / 内缩是否由容器承担 / clone 是否在），不是「打出来好不好看」',
)

# ── UI-129 [NORMAL] 建品页 AI 生成商品图：样图 → 百炼图生图 → 一键出整套（主图 3 + 详情图 5，边生成边追加，只追加不覆盖；issue #7335 / #7533 / #7773 / #7782）（源: cases/ui.yml）──
_CASE_UI_129 = EvalCase(
    id='UI-129',
    legacy_id='',
    title='建品页 AI 生成商品图：样图 → 百炼图生图 → 一键出整套（主图 3 + 详情图 5，边生成边追加，只追加不覆盖；issue #7335 / #7533 / #7773 / #7782）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「当前缺乏商品的主图和明细图，你能否根据用户提供的样本图通过大模型来补充一份接近商品的样品图」（用户 2026-10-19）', '「如果效果可以的话，我希望做成商品创建中的功能的一部分」（用户 2026-10-19）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·后端不落库（会红）：POST /api/admin/products/ai-images 只回 {url, model}（data 恰好两个键）；控制器依赖面恰好 ProductImageGenerationService（无 ProductService / Mapper）。执行点 = ProductImageControllerTest + ProductImageGenerationServiceTest。', '判据 2·链路收口（会红）：临时 URL 只允许从 *.aliyuncs.com 下载并转存 OSS（非百炼域名 ⇒ 422 且不下载）；样图必须 https；用途白名单 **main/white/texture/craft/scene** 之外 ⇒ 422 且不发起生成请求；主图构图变体 `variant` 越界（>2）⇒ 422 且不发起生成请求，缺省 = 0（老客户端不受影响）。执行点 = ProductImageGenerationServiceTest + ProductImageControllerTest。', '判据 3·ai-agent 模型轮换（会红）：配额类错误（429 / AllocationQuota）与「模型接不了该请求」（HTTP 400 InvalidParameter）自动切下一个模型；审核类 400（DataInspectionFailed）不切模型；**默认链 = qwen-image-3.0-pro、端点 = 阿里云 MaaS token-plan 的原生多模态路径（用户 2026-10-24 裁定，issue #7661）**，旧百炼模型与旧 host 不得回流（类级守卫 = tests/unit_ci_workflows/test_maas_audio_image_single_source.py 的 G1/G3）；全链不可用时报「模型不接这类请求（非配额原因）」而不是「额度用尽」；全部用尽 ⇒ 503；未配置 Key ⇒ 503 且不发外部请求（**不回落 PRIMARY 的 DeepSeek key**）。**503 响应体必须带稳定机器可读 code（四类互不相同：IMAGE_GEN_MODEL_UNSUPPORTED / IMAGE_GEN_QUOTA_EXCEEDED / IMAGE_GEN_DISABLED / IMAGE_GEN_NO_KEY，issue #7552），detail 并存、状态码语义不变（其它供应商失败仍 502）；凭证失效（401/403，issue #7680）复用 IMAGE_GEN_NO_KEY（同属平台侧凭证问题、商家的下一个动作一致，不新增第五码）**。执行点 = backend/ai-agent-service/tests/test_generator.py。', '判据 4·前端（会红，issue #7533 / #7773 / #7782 改判）：无样图 ⇒ 按钮 disabled + 先上传提示；默认用第 1 张、多图可切换样图（生成携带所选样图 URL + kind + variant）；**生成成功即自动追加到图片位**（主图·白底图 ⇒ onApplyMain 追加主图末尾；细节·工艺·场景 ⇒ onApplyDetail 追加 detailImages 末尾），**不存在「用这张」按钮**（回归守卫）；**只追加不覆盖**：再生成一张 / 换用途再生成 **都不摘掉上一张**（不再有 replaceUrl；先详情后主图 ⇒ 详情那张仍在）；**一键生成整套**（用户 21:09 改判）⇒ 一次点出 8 张：`main:0 / main:1 / white:0 / texture:0 / texture:1 / craft:0 / scene:0 / scene:1`，并发 3，边生成边落位，结束时报「已生成 8/8」；个别失败 ⇒ 其余照常落位并在错误行点名未成功的用途（可单独补）；单张补生成时主图连点 ⇒ 构图 `variant` 按 0→1→2→0 轮换，面板写明「本次构图：正面棚拍/半垂坠/悬挂近景」；白底图 ⇒ kind=white 且进主图列表、面板写明「可直接放第 5 张」；列表满（主图 5 / 详情图 9）⇒ 提示先删一张、**不静默丢图**；生成中 loading；失败**不落位**且错误可见可行动。**失败话术按 admin-api 错误码分叉（issue #7552）：模型不支持 / 额度用尽 / 真·瞬时三类不同，「稍后重试」只出现在真·瞬时那一条；页面不出现服务名与内部地址（§31 P3）**。执行点 = frontend/admin-web/tests/unit/components/ProductImageAI.test.tsx。', '判据 5·落位闭环（会红，issue #7533 / #7773）：渲染真实 `ProductForm` ⇒ 生成成功**无需任何额外点击**主图位即变为 [原图, 生成图]（**追加末位**，不再抢封面）；点「提交并上架」⇒ `onSubmit` 载荷 `images` 带上该 URL（= 用户逐字「保存后也没有」的判据）；**再生成 ⇒ 追加不替换**（不摘掉上一张）；细节用途 ⇒ `detailImages` 末位**且提交载荷 `detailImages` 带上它**（= 用户逐字「生图不能保存到详情图」的判据）；**先出详情图、再出主图 ⇒ 详情图那张不得被摘掉**（改前红）；主图已满 5 张 ⇒ 提示先删一张、盘里 5 张一张不少；**生成期间（1~2min）商家改过图片列表 ⇒ 落位基于最新列表**（删掉的图不复活、新图不丢，靠函数式更新）。执行点 = frontend/admin-web/tests/unit/components/ProductFormAIImage.test.tsx + ProductFormAIImageEditPage.test.tsx（编辑页父组件再渲染不得冲掉落位）；编辑态样图候选去重 = ProductForm.test.tsx。', '判据 7·生成侧「岗位」口径（会红，issue #7782）：ai-agent 提示词按用途分叉 —— 主图三套构图（正面棚拍 / 半垂坠 / 悬挂近景）**互不相同**且都带商品名、`variant` 越界取模；`white` 白底图提示词包含平台硬要求（纯白背景 + RGB 255,255,255 + 居中 + 无水印/无 logo/无边框），且 `variant` 对它无影响；材质提示词不变。取数理由：用户 2026-10-25「主图图片生成的都一样」+ 淘宝/天猫 5 张主图岗位分工（第 5 位白底图是合规位与免费流量位）。执行点 = backend/ai-agent-service/tests/test_generator.py。', '判据 6·失败口径分叉（会红，issue #7552）：ai-agent 503 的四种 code 在 admin-api 产出**互不相同**的错误码与 suggestion（表驱动）；「稍后重试」只用于真·瞬时不可用（模型不支持 ⇒ 「该能力暂不可用，已反馈平台」+ 手工传图出路；额度 ⇒ 「今日额度已用完」）；对外 message / suggestion **不含**服务名与 URL（§31 P3）。执行点 = backend/admin-api/src/test/java/com/migao/admin/service/ProductImageClientTest.java。'],
    skip_reason='[backend-contract] 纯页面 AI 辅助入口（不经过 LLM 对话/工具），由 admin-api 单测 + ai-agent pytest + 前端 vitest 执行，不进入 agent-eval 冒烟',
    tags=['ai-image', 'product-create', 'image-generation'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端/接口契约用例：前置（已上传样图、admin-api 端点、ai-agent 内部端点）由三端单测自建或 mock（admin-web mock `@/lib/api`；admin-api mock ProductImageClient/FileStorageService；ai-agent mock httpx），不依赖共享夹具与真实服务 ⇒ 前置不成立时对应单测直接红；agent-eval 栈不跑它',
)

# ── UI-130 [NORMAL] 销售订单列表查询区默认折叠：常驻一行摘要 + 展开才渲染筛选项（issue #7388）（源: cases/ui.yml）──
_CASE_UI_130 = EvalCase(
    id='UI-130',
    legacy_id='',
    title='销售订单列表查询区默认折叠：常驻一行摘要 + 展开才渲染筛选项（issue #7388）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「这里的查询区域默认折叠起来」（用户 2026-10-20，销售订单页截图）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·原语 opt-in（会红）：不传 `collapsible` 的 `SearchPanel` 字段常驻且无折叠开关（客户 / 售后 / 品检 / 员工四页行为零变化）。执行点 = frontend/admin-web/tests/unit/components/SearchPanel.test.ts（describe「collapsible（issue #7388）」）。', '判据 2·折叠态 DOM 在场性（会红）：`collapsible` 默认收起时 `fields[].control` 与「查询/重置/刷新」三个按钮 `queryBy*` 为 null，`search-panel-toggle` 的 `aria-expanded=false` 且 `search-panel-summary` 在。执行点同上。', '判据 3·两态往返（会红）：点「展开筛选」⇒ 字段与三个按钮逐个回来、`aria-expanded=true`、摘要不再渲染；再点 ⇒ 字段又消失。执行点同上 + frontend/admin-web/tests/unit/pages/orders.test.tsx。', '判据 4·订单页默认收起且摘要说清时间范围（会红）：首屏取不到「请输入订单ID」与「查询」按钮，`search-panel-summary` 含「近一个月」；展开后 5 个文本框 + 2 个日期框 + 查询/重置/刷新全在。执行点 = orders.test.tsx。', '判据 5·版式判据不被折叠绕过（会红）：`orders-query-area-overflow.test.tsx` 的单一 grid / 无溢出 / label 定宽 / 字段格可缩在**展开态**逐条仍成立（不是靠容器里没有 grid 而假绿）。', '判据 6·收起态要**引导**用户去查询（会红，用户 2026-10-20 追加「折叠状态需要引导用户可以打开区域查询」）：收起时入口必须是**按钮形态**（`search-panel-toggle-label` 带 `border` + `rounded-lg`）且文案「展开筛选」、`title` 含「展开筛选区」；展开后同一位置降级成弱文字「收起」（无描边，不与「查询」抢 primary）。执行点 = SearchPanel.test.ts（判据 2/3）+ orders.test.tsx。'],
    skip_reason='[backend-contract] 纯前端版式与交互契约（不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['search-panel', 'collapse', 'orders-list'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端版式/交互契约用例：页面渲染时 mock `@/lib/api` 与 `@/components/orders`，不依赖共享夹具与真实服务 ⇒ 前置不成立时对应单测直接红；agent-eval 栈不跑它',
)

# ── UI-131 [NORMAL] 全站下拉框只有一种形态（共享 SELECT_CONTROL / 自绘箭尖）+ 筛选条字段参与伸缩（issue #7397）（源: cases/ui.yml）──
_CASE_UI_131 = EvalCase(
    id='UI-131',
    legacy_id='',
    title='全站下拉框只有一种形态（共享 SELECT_CONTROL / 自绘箭尖）+ 筛选条字段参与伸缩（issue #7397）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['「输入框长度不够，文字被遮住了」（用户 2026-10-20，知识库关键词输入框截图红框）', '「我们所有页面的下拉框都看着很别扭，不协调」（用户 2026-10-20，作业看板状态筛选截图红框）', '「都是这种不协调的问题」（用户 2026-10-20，第三张下拉截图）'],
    expectations=['direct_reply'],
    data_checks=['判据 1·业务面下拉必须引用共享铬（会红）：`src/**`（除 `src/components/ui/**`）里每个真实 `<select>` 开标签必须含 `SELECT_CONTROL`；只借箭尖（`SELECT_CHEVRON`）的面必须登记在冻结台账且台账只许缩短。执行点 = frontend/admin-web/tests/unit/select-control-unification.test.tsx（describe「判据 1」）。', '判据 2·共享铬不许被削弱（会红）：`SELECT_CONTROL` 仍带 `appearance-none` / `h-9` / `border-neutral-300` / `pr-9` / `rounded` / 自绘箭尖背景 / 焦点环 / disabled 态；表单面 `SELECT_CONTROL_FIELD` = 同一套 + `rounded-lg`。执行点同上（判据 2）。', '判据 3·单一份箭尖图形（会红）：`Select` 原语不再 import `ChevronDown`、不再叠第二个箭头，改用 `SELECT_CONTROL_FIELD`。执行点同上（判据 3）。', '判据 4·筛选条字段参与伸缩（会红）：`SearchBar` 字段容器带 `flex-1` + `basis-[22rem]`、不再有定宽 `min-w-[200px]`；输入框 `w-full` 吃满容器 ⇒ 长占位文案（「搜索标题 / 关键词 / 常见问法 / 回答内容」）不再被截断。执行点同上（判据 4）。', '判据 5·判别力自证（会红）：注入「自己拼铬」「台账外的 SELECT_CHEVRON」「注释里的 <select> 字样」三种形态，纯函数必须在内存里分别判红 / 判红 / 放行（不制造假红）。执行点同上（describe「判别力自证」）。'],
    skip_reason='[backend-contract] 纯前端版式契约（不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['design-system', 'select', 'search-bar', 'control-chrome'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端版式契约用例：源码扫描 + jsdom 渲染，不依赖共享夹具与真实服务 ⇒ 前置不成立时对应单测直接红；agent-eval 栈不跑它',
)

# ── UI-132 [NORMAL] 黄金策悬浮助手「全屏（最大化）」必须铺满视口 —— 历史拖拽 px 尺寸不得覆盖全屏布局，全屏不渲染缩放手柄（issue #7508）（源: cases/ui.yml）──
_CASE_UI_132 = EvalCase(
    id='UI-132',
    legacy_id='',
    title='黄金策悬浮助手「全屏（最大化）」必须铺满视口 —— 历史拖拽 px 尺寸不得覆盖全屏布局，全屏不渲染缩放手柄（issue #7508）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['这里最大化之后显示的有问题，没有呈现最大化的状态', '我看只有我电脑是这样的，我换一台电脑就正常了'],
    expectations=['direct_reply'],
    data_checks=['判据 1·全屏铺满（会红）：localStorage 残留 `mibao_chat_panel_width/height`（620×480）时点「全屏」⇒ 面板根 `chat-panel-resize-container` 的 style 必须是 `width:100%` / `height:100%`（修前实测 `620px` / `480px`，即左上角小窗 + 右上露出底层页面）。执行点 = frontend/admin-web/tests/unit/floating-assistant.test.tsx（describe「全屏」）', '判据 2·全屏无缩放手柄（会红）：全屏态四个手柄（`chat-panel-resize-handle` / `-top` / `-horizontal` / `-corner`）全部不渲染；退出全屏后全部恢复（最大化窗口不可再被拖成小窗，也阻断在最大化态把 px 写回 localStorage）。执行点同上', '判据 3·退出全屏可逆（会红）：退出全屏后遮罩 `float-assistant-overlay` 回来、面板回到历史 px（620/480）；无历史 px 时全屏同样 100%（对照：不是靠清缓存才正常）。执行点同上', '判据 4·模式外观契约矩阵（类级，未登记即红）：closed / centered / fullscreen / minimized 四模式 × {面板根 / 模态遮罩 / 悬浮球 / 最小化浮窗 / 缩放手柄} 逐格断言 —— 新增或改动任一模式必须在该表加行。执行点 = 同文件 describe「模式外观契约」的 it.each', '既有判据零放宽：UI-021 / UI-022 / UI-023 / UI-029 的拖拽缩放、持久化、双击复位、最小化浮窗行为全绿（MibaoChatPanel.test.tsx / floating-assistant.test.tsx 一条断言都没改弱）'],
    skip_reason='[backend-contract] 纯前端 React 组件/布局契约，由 admin-web vitest 执行（jsdom + 真机截图取证），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'floating-assistant', 'fullscreen', 'resize'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端布局契约用例（jsdom 渲染 + 源码行为），不依赖真实服务与共享夹具；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-133 [NORMAL] 客户详情「标签」：没有标签可加时点「+」必须给出可见反馈 + 去处（系统无标签 / 客户已打满两种空态）（源: cases/ui.yml）──
_CASE_UI_133 = EvalCase(
    id='UI-133',
    legacy_id='',
    title='客户详情「标签」：没有标签可加时点「+」必须给出可见反馈 + 去处（系统无标签 / 客户已打满两种空态）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['当系统没有标签时，点击+号无反应，应该引导客户去添加标签'],
    expectations=['direct_reply'],
    data_checks=['判据 1·系统无标签时点「+」有反馈（会红）：`getCustomerTags` 返回空数组时点触发器 ⇒ 面板 `customer-tag-empty` 在场、文案说明「系统还没有标签」、入口「去添加标签」把路由推到 `/customers?manageTags=1`。修前形态 = 面板被 `availableTags.length > 0` 门控 ⇒ 点「+」零反馈（触发器可点、DOM 无任何变化）。执行点 = frontend/admin-web/tests/unit/pages/customer-detail-tags-empty.test.tsx', '判据 2·两种空态不混（会红）：标签存在但该客户已全部关联 ⇒ 文案是「全部标签」、不得说成「系统还没有标签」，入口换为「管理标签」且同样推到 `/customers?manageTags=1`。执行点同上', '判据 3·负控（会红）：未点击时无空态面板且 `aria-expanded=false`；有可加标签时不出空态、选择器照常列出可加的那一条（空态不得掩盖正常选择器）。执行点同上', '判据 4·深链一步到位（会红）：`/customers?manageTags=1` ⇒ 客户列表页直接打开「标签管理」模态（「新建标签」表单 / 「已有标签」块在场）；不带参数 ⇒ 不自动打开（进客户列表不该被弹窗打断）。执行点 = frontend/admin-web/tests/unit/pages/customers-tag-deeplink.test.tsx', '判据 5·类级元守卫（会红）：`frontend/admin-web/src/**` 里 0 处「state 开合的浮层被 `列表.length > 0` 门控」的形态（`{showXxx && 某处.length > 0 && (`）—— 修前恰 1 处 = 本单病灶；判别力自证 = 修前那一行原样注入必须命中、良性写法（只由 state 门控 / 只判列表非空 / 整行注释里的反例）必须放行；扫描面非空（文件数 > 100）防「空集比空集」的假绿。执行点 = frontend/admin-web/tests/unit/popover-empty-gate-guard.test.ts'],
    skip_reason='[backend-contract] 纯前端交互 + 源码形态契约（不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['ui', 'admin-web', 'customer-tag', 'empty-state', 'inert-trigger'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端交互契约用例（jsdom 渲染 + 源码形态扫描），不依赖真实服务与共享夹具；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-134 [NORMAL] 加工单左上角「作业单扫码报工」二维码：码值逐字取服务端 processingOrder.scan_url（前端不拼域名/路径）+ 纸面只留**竖排**「扫码报工」（短码不上产品面，issue #7608）+ 缺码不画假码（不回落作业单号），工人扫码进报工页（issue #7530；2026-10-27 由销售单迁到加工单，issue #7891）（源: cases/ui.yml）──
_CASE_UI_134 = EvalCase(
    id='UI-134',
    legacy_id='',
    title='加工单左上角「作业单扫码报工」二维码：码值逐字取服务端 processingOrder.scan_url（前端不拼域名/路径）+ 纸面只留**竖排**「扫码报工」（短码不上产品面，issue #7608）+ 缺码不画假码（不回落作业单号），工人扫码进报工页（issue #7530；2026-10-27 由销售单迁到加工单，issue #7891）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['销售单不要品名，并且把作业出库单手机端链接对应的二维码信息放置在左上角，工人可以通过扫码进入报工页面', '把销售单左上角的扫码报工二维码迁移到加工单打印上，这样设计才是合理的'],
    expectations=['direct_reply'],
    data_checks=['判据 1·码值只认服务端下发（会红）：纸面二维码的内容逐字 = `processingOrder.scan_url`（示例域刻意不用 app.migaozn.com）⇒ 前端自己拼 `{base}/o/{短码}` 会印出另一个地址 ⇒ 必红。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的「扫码报工码」用例组（有码 ⇒ 码值逐字 = 服务端 scan_url / 无码 ⇒ 三种形态都不出现）', '判据 2·位置在**加工单**纸面左上角（会红，issue #7891）：二维码块与加工单抬头并排（文档顺序在纸面标题之前），取 `processing-doc-qr` 能取到；同时**销售单**纸面取不到任何扫码码（`sales-work-order-qr` 为 null，销售单不再承载车间入口）。执行点 = ProcessingDoc.test.tsx 的码用例 + frontend/admin-web/tests/unit/components/SalesDoc.test.tsx 的反向断言', '判据 3·纸面只留**竖排**「扫码报工」、短码不上产品面（会红，issue #7608）：标签 `processing-doc-qr-label` 带 `writing-mode: vertical-rl`（改成横排 ⇒ 红），且纸面文本里不出现 `short_code` 的取值（把短码行加回去 ⇒ 红；类级判据 = C12）。兜底不靠这张纸：工人报工页有「输码（短码 / 加工单号 / 订单号）」输入框，短码仍印在任务卡上（`TaskCardPrint` 的 `part_short_code`），加工单纸面本来就印「单号」。', '判据 4·缺码不画假码（会红）：无 `scan_url`（存量单未实例化短码 / 没有作业单 / 读面没取到）⇒ 零二维码、零占位框，纸面既不出现作业单号也不出现裸短码（扫出来只有一串文本、打不开任何页面 = issue #6867 治过的病）。执行点 = ProcessingDoc.test.tsx 的「无 scan_url ⇒ 整块不出现」', '判据 5·**类级元守卫**（让同类进不来）：受管打印单据里不得出现扫码短链路径段（`/o/` 作业单级 · `/s/` 部位级）—— 谁再在纸面拼域名 / 路径段 ⇒ 红（含内存注入自证：拼路径段的样本判红、逐字取 `scan_url` 的样本判绿，防「空判据」）。执行点 = tests/unit_ci_workflows/test_print_media_matrix_guard.py 的 C11（test_c11_print_docs_never_assemble_scan_short_links）；另一条类级判据 = 同文件 C12（test_c12_customer_visible_docs_never_print_internal_short_code）：客户可见纸面（销售单 / 报价单 / 发货单 / 加工单）不得读取或渲染 `short_code` —— 把短码行加回纸面即红'],
    skip_reason='[backend-contract] 纯前端打印版式与扫码入口取值（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 与 SalesDoc.test.tsx 执行',
    tags=['ui', 'order', 'print', 'processing-doc', 'work-order-qr'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端打印版式契约（jsdom 渲染），不依赖真实服务与共享夹具；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-135 [NORMAL] 纸面收款码：预览层与真打印都出码（打印前等异步取码）+ 上传图自动裁白边 + 缺码不画假码（issue #7536）（源: cases/ui.yml）──
_CASE_UI_135 = EvalCase(
    id='UI-135',
    legacy_id='',
    title='纸面收款码：预览层与真打印都出码（打印前等异步取码）+ 上传图自动裁白边 + 缺码不画假码（issue #7536）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['我上传了微信二维码，为什么报价单上没有展示收款码', '我上传的二维码周围有白色区域，在报价单上不要展示白色区域，只把二维码展示上去'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**取码时点**（会红）：预览层（`inline`）或「本次打印目标就是本单据」⇒ **立刻**取码；常驻挂载的屏幕态**零请求**（该读端点要 `order:list`，在无该码的页面上会变成「一进页面弹一条 403」，与 use-company-name 的 #7285 同族）。执行点 = frontend/admin-web/tests/unit/lib/use-payment-qrcodes.test.ts 的「② 未注入 + 未要出纸 ⇒ 零请求」「③ 🔴 红证：active（预览层 / 本次打印目标）⇒ 挂载即取」', '判据 2·🔴 **打印前等码**（会红）：`usePrintDoc` 在 `window.print()` 之前 await 同一份取码 Promise（上限 `PRINT_ASSET_WAIT_MS` = 2.5s，超时也出纸），并让出一帧等 React 提交；**没有码在飞**时走同步路径（发货单 / 洗水唛的既有读数一字未变）。执行点 = frontend/admin-web/tests/unit/lib/print-doc.test.tsx 的「⑤ 🔴 红证（issue #7536）：收款码在飞 ⇒ print 等它 resolve 之后才调用」', '判据 3·🔴 **裁白边发生在上传时**（会红，用户 2026-10-23 追加裁定「直接改成上传时裁」）：`settings/page.tsx` 的收款码上传先过 `trimWhiteMarginFile(file)` —— canvas 亮度扫描（阈值 `QR_CONTENT_LUMINANCE` = 245，亮度 ≥ 阈值为背景）取内容外接框后重绘成 PNG；四边留白不对称也裁对；无白边（整帧即内容）⇒ 原文件不重编码；**任何失败（无 canvas / 解码超时或失败 / 编码失败 / 全白）一律退回原文件**（上传宁可有白边，不许传不上去）。执行点 = frontend/admin-web/tests/unit/lib/qr-image.test.ts（①~⑫）+ tests/unit/pages/settings.test.tsx 的「🔴 收款码上传前先裁白边」「裁边失败 ⇒ 照常上传」', '判据 4·**缺码不画假码 / 注入优先仍然成立**：调用方注入 map ⇒ 一次请求都不发、连裁边都不做；拉取失败或空响应 ⇒ 整块不渲染。执行点 = use-payment-qrcodes.test.ts 的「① 注入」「⑥ 失败 ⇒ 空 map」+ QuotationDoc.test.tsx 的「收款码缺 imageUrl ⇒ 不画假码」', '🔴 红证（真实 Chromium 实测读数，修前）：预览纸框内 img = 0、收款码请求 0 次；模拟 `beforeprint` 当帧 img = 0，1.5s 后才是 1（纸面快照早已完成）⇒ 预览永远无码、第一次打印纸上无码。修后：预览纸框内出码、`window.print()` 在取码 resolve 之后才调用。', '边界（照实登记）：① 裁边只作用于**新上传**的图 —— **存量带白边的图不会自动变干净**，需在「企业基础设置 → 收款码」重新上传一次（界面文案已提示）；② 不做服务端重编码（无新依赖）；③ 渲染口不碰像素（不依赖 OSS 的 CORS，口径对所有人一致）。'],
    skip_reason='[backend-contract] 纯前端取数时点 + 图片裁边（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/lib/use-payment-qrcodes.test.ts、tests/unit/lib/qr-image.test.ts、tests/unit/lib/print-doc.test.tsx、tests/unit/components/QuotationDoc.test.tsx 执行',
    tags=['ui', 'admin-web', 'print', 'quotation', 'sales-doc', 'payment-qrcode'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端取数/图片处理契约用例：收款码 map 由单测自建并注入 settingsApi 打桩（不碰真库、不依赖共享夹具）；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-136 [NORMAL] 作业看板：父订单已删（列表 orderNo 缺失）的行不再发 operations/piecework（404 toast 风暴），订单号列写「订单已删除」（issue #7633）（源: cases/ui.yml）──
_CASE_UI_136 = EvalCase(
    id='UI-136',
    legacy_id='',
    title='作业看板：父订单已删（列表 orderNo 缺失）的行不再发 operations/piecework（404 toast 风暴），订单号列写「订单已删除」（issue #7633）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-24 PC 端截图：打开作业看板就弹 toast「请求的资源不存在」（可叠多层），列表里出现订单号 / 客户都是「—」的作业单行；点「刷新」仍复现'],
    expectations=['direct_reply'],
    data_checks=["判据 1·🔴 **父订单缺失的行零请求**（会红）：判定口径 = 列表响应里 `!po.orderNo`（`processing_orders.order_id` 是 NOT NULL 外键、列表与明细同租户 ⇒ `orderNo == null` 当且仅当父订单已软删 / 不可解析），这类行**不进**懒加载 `pending` ⇒ 对 `/production/orders/{orderId}/operations` 与 `/production/orders/{orderId}/piecework` 各 **0 次**调用。执行点 = frontend/admin-web/tests/unit/pages/production-board.test.tsx 的「#7633 父订单已删的行：不扇出 operations/piecework，订单号列显示「订单已删除」」（红证：改前实测 `expected 1 to be +0`，即该行确实发了一次 `getOrderOperations('order-uuid-gone')`）", '判据 2·**同一用例内的负控**：正常行（`orderNo` 有值）**照常**请求两个端点 —— 否则「一个都不发」也能让判据 1 变绿（空跑式假绿）。', '判据 3·**可见文案是业务话**：该行订单号单元格渲染「订单已删除」（不是「—」、不是内部键）；客户列保持「—」（不编造客户）；**不新增**常驻告警条 / 红块、**不给**这类行「重试」入口（§31 P1/P3）。', '边界（照实登记）：① 「父订单缺失」的判定依赖 `orderNo` 缺失去推断，**不是**显式契约字段（若后续要 `orderMissing: true` 这类显式位，另立单改契约）；② 这些行仍在列表里（本 PR 不删数据 —— 存量孤儿子行的软删由 #7633 主会话在数据侧完成，物理清理涉钱需人工裁定）；③ 进度 / 计件两列对这类行仍显示 `0%（0/0）` / `¥0.00`（既有「详情缺失」形态，未改）。'],
    skip_reason='[backend-contract] 纯前端取数 + 渲染契约（无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/admin-web/tests/unit/pages/production-board.test.tsx 执行',
    tags=['ui', 'admin-web', 'production-board', 'orphan', 'backend-contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端取数/渲染契约用例：列表与两个详情端点都由单测打桩（不碰真库、不依赖共享夹具）；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-137 [NORMAL] 工人端裁剪报工确认批次：派工批次预填可改 / 未指派空着必须手输 / 回执带批次与余量（issue #7647）（源: cases/ui.yml）──
_CASE_UI_137 = EvalCase(
    id='UI-137',
    legacy_id='',
    title='工人端裁剪报工确认批次：派工批次预填可改 / 未指派空着必须手输 / 回执带批次与余量（issue #7647）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['裁剪报工的时候需要工人裁剪的哪个批次，如果通过智能派单的就默认展示指定批次，允许工人改，如果没指定批次就需要工人手输才能完成报工'],
    expectations=[],
    data_checks=['**判据 1·区块只在需要批次时出现（会红）**：`batch_required === true` ⇒ 报工主屏出「批次（这次从哪一批裁）」输入框 `#wh5-batch-input`；缺键 / false ⇒ 批次区块**一个字节都不渲染**、报工按钮与请求体与改前逐字一致（老响应零回归）。执行点 = frontend/worker-h5/tests/worker-h5-cutting-batch.test.mjs 的用例 ①②④。**红证**：把 `isBatchRequired` 改成恒 true ⇒ ④ 红；区块恒不渲染 ⇒ ①②③ 等 7 条红。', '**判据 2·派工批次预填且可改（会红）**：有派工批次 ⇒ 输入框 `value` = 该批次，工人可改成别的批次并原样进入请求体；没有 ⇒ 输入框为空。执行点 = 同文件用例 ①②③。**红证**：`currentBatchNo` 忽略工人输入（恒用预填）⇒ ③⑥⑦⑧-b 红。', '**判据 3·没填不让报工（会红）**：`batch_required` 且输入 trim 后为空 ⇒ 报工按钮 `disabled` + 一句可行动提示；硬点（模拟绕过 disabled）也**一个写请求都不发**。执行点 = 同文件用例 ②③-b。**红证**：去掉 render 侧的 `batchBlocked` 分支 ⇒ ②⑧ 红；去掉 app 侧闸 ⇒ ③-b 红（发出了请求）。', '**判据 4·请求体带工人确认的批次（会红）**：点报工时请求体含 `batch_no`（= 输入框/候选点选后的值，trim 过）；非裁剪工序**不带**该键（白名单构造）。执行点 = 同文件用例 ③④ + frontend/worker-h5/src/api.mjs 的 `completeByScan`。**红证**：api 侧不写 `body.batch_no` ⇒ ③ 红。', "**判据 5·候选批次可点选（会红）**：`batch_candidates[]` 渲染成 chip（批次号 + 余量 + 余量不足标记），点一下填入输入框；候选为空 ⇒ 整块候选区不渲染。执行点 = 同文件用例 ⑤。**红证**：不接线候选点击 ⇒ ⑤ 红；候选为空仍渲染空壳 ⇒ ⑤'' 红。", '**判据 6·回执显示批次与余量、缺键不印假数据（会红）**：报工成功回执句追加「批次 X · 余量 Y 米」；`batch_shortage_meters > 0` 追加缺口说明；三键缺键 / null ⇒ 整句不渲染（屏上不出现 `undefined` / `NaN` / `null`）。执行点 = 同文件用例 ⑥⑦。**红证**：把回执尾部改成 naive 插值 ⇒ ⑦ 红；不追加批次尾 ⇒ ⑥⑦ 红。', '**判据 7·下一屏只认服务端重解析（会红）**：报工成功后的下一屏按回执的 `next_batch_required` / `next_batch_no` / `next_batch_candidates` 渲染 —— 下一道不要批次（车位/打包）⇒ 批次区块**不出现**且按钮可点；仍要批次（报废不推进 ⇒ 仍是裁剪）⇒ 输入框空 + 按钮禁用 + 候选来自服务端；服务端给了预填值 ⇒ 预填。工人手输的值**不带到下一屏**（`state.batchNo` 清回 null）。执行点 = 同文件用例 ⑧ / ⑧′ / ⑧″ / ⑧-b。**红证**：沿用上一屏的 `batch_required` ⇒ ⑧ 红（打包屏多出输入框、按钮被禁死）；清空成 false ⇒ ⑧′ 红（裁剪屏填不了批次）；`resolved` 不清 `batchNo` ⇒ ⑧-b 红。', '**判据 8·一体机不被新规则卡死（会红）**：机台页（`machine.mjs` / `machine-app.mjs`）对裁剪工序：有派工批次 ⇒ 报工请求自动带 `batch_no`（屏面一字不变）；没有 ⇒ **零请求** + 大字「本单未指派批次：请到报工页填写批次后再报工」+ 去报工页入口；非裁剪 ⇒ 请求体不带该键。执行点 = frontend/worker-h5/tests/worker-h5-machine.test.mjs 的 ⑦ / ⑦′ / ⑦″。**红证**：机台不带 `batch_no` ⇒ ⑦ 红；去掉机台批次闸 ⇒ ⑦′ 红（发了请求）；恒显阻断提示 ⇒ ⑦″ 红。'],
    skip_reason='[backend-contract] 纯前端（假 DOM + fetch 替身驱动真实装配层；无 LLM 环节，不进 agent-eval 冒烟）：断言由 frontend/worker-h5/tests/worker-h5-cutting-batch.test.mjs 与 worker-h5-machine.test.mjs 执行',
    tags=['ui', 'worker-h5', 'production', 'scan-report', 'batch-stock'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端契约用例：服务端解析响应（`batch_required` / `batch_no` / `batch_candidates`）与报工回执由单测自建并打桩（假 DOM + fetch 替身，不碰真库），前置不成立时单测直接红；agent-eval 栈不跑它',
)

# ── UI-141 [NORMAL] 数值输入框的小数录入口径：<input> 的 onChange 不许 Number/parseFloat(target.value) 往返（类级判据 + 裁高取值框三位小数；单测覆盖，非 LLM 行为）（源: cases/ui.yml）──
_CASE_UI_141 = EvalCase(
    id='UI-141',
    legacy_id='',
    title='数值输入框的小数录入口径：<input> 的 onChange 不许 Number/parseFloat(target.value) 往返（类级判据 + 裁高取值框三位小数；单测覆盖，非 LLM 行为）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['这里的输入框不允许输入小数点，这里应该要支持3位小数，后续要注意，已经发现几次新增的输入框都不支持输入小数点，这个默认开发规则是不符合实际业务需要的'],
    expectations=[],
    data_checks=['**判据 1·类级（会红）**：三个前端包 `src/**` 里每个 `<input …>` 开标签，若 `onChange` 内出现 `Number(...target.value)` / `parseFloat(...)` / `parseInt(...)`（含 `currentTarget` / 跨行）⇒ 红；真语料**零容忍**（落地时全仓唯一一处 = 裁高配置的取值框，已改 `NumberInput`）。红证 = 把该框改回手写往返 ⇒ 当场红。执行点 = frontend/admin-web/tests/unit/numeric-input-draft-guard.test.ts 的 ①②③④。', "**判据 2·实例（会红）**：裁高配置「取值（米）」敲 `0.`（中间态）后输入框仍是 `0.`（旧实现 `Number('0.')===0` ⇒ 上屏 `0`，小数点打不出来），再敲成 `0.145` 后保存报文里 `value === 0.145`。执行点 = frontend/admin-web/tests/unit/components/CuttingHeightConfigPanel.test.tsx 的 ⑩。"],
    skip_reason='[frontend-contract] 只登记「数值输入的草稿口径」这一层**确定性**判据（静态扫描 + jsdom 输入事件），由单元测试全量覆盖 ⇒ 不进 agent-eval 冒烟（同 UI-131 / UI-138 家族惯例）。',
    tags=['ui', 'frontend', 'numeric-input', 'class-level-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='纯前端契约用例：静态扫描 + jsdom 输入事件，不碰真库、不起服务栈；`NumberInput` 的草稿口径由 frontend/admin-web/src/components/ui/NumberInput.tsx 提供（issue #5198/#5210）',
)

# ── UI-138 [NORMAL] 纸面加工项绑商品：销售单 / 报价单 / 发货单在商品行下印水洗唛式「加工项 + 特殊选项」，发货单底部独立加工项区退场（issue #7891）（源: cases/ui.yml）──
_CASE_UI_138 = EvalCase(
    id='UI-138',
    legacy_id='',
    title='纸面加工项绑商品：销售单 / 报价单 / 发货单在商品行下印水洗唛式「加工项 + 特殊选项」，发货单底部独立加工项区退场（issue #7891）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['销售单和报价单都缺了加工项', '发货单的加工项需要和商品绑定，比如如果是成品帘，一览展示商品，商品下面是加工项，展示内容参考水洗唛的那种格式，还有特殊选项也要放上去，都放在加工项那一栏里面', '发货单的打印格式也需要改一下'],
    expectations=['direct_reply'],
    data_checks=['判据 1·三份纸都有加工项（会红）：销售单 / 报价单 / 发货单的商品行下方都能取到加工项子行（`sales-item-processing-N` / `quotation-set-processing-N` / `shipment-item-processing-N`），文案含加工项名称与数量；把子行删掉 ⇒ 对应测试红。执行点 = frontend/admin-web/tests/unit/components/ 下 SalesDoc.test.tsx / QuotationDoc.test.tsx 的加工项用例（发货单已于 issue #7902 退场）', '判据 2·**绑到商品行**（会红）：商品 A 的加工项只出现在 A 的子行、B 行下不出现（两行各带不同加工项 + `within(row)` 断言）；把子行挂到表尾（改回不绑商品）⇒ 红。执行点 = 三份测试的绑定用例', '判据 3·水洗唛式两栏 + 特殊选项同栏（会红）：子行文案 = `加工项：… · 特殊选项：…`（特殊选项取 craftSpecRows 的同一份格式化）；特殊选项被丢 ⇒ 红。执行点 = 同文件「特殊选项也上纸」用例', '判据 4·数量三态与缺值占位（会红）：全等 ⇒ `定型、韩褶 各 6.3`；不等 ⇒ `定型 6.3 + 韩褶 2`；缺数量 ⇒ `打孔 —`（不印 0、不吞项、不出现 `×`）。执行点 = 同文件三态用例 + 类级守卫 tests/unit_ci_workflows/test_print_media_matrix_guard.py 的 C9（构建器形态 + `×` 判红）', '判据 5·布料行不出子行（会红）：商品行没有 `processingInfo`（面料/布料单）⇒ 该行下零加工项节点。执行点 = 三份测试的布料行用例', '判据 6b·⛔ **发货单整张退场**（issue #7902）：`shipment-item-processing-*` / `shipment-processing-fee-total` 随纸一起消失；同一条「加工项绑商品行」不变量由**销售单**承接（`sales-item-processing-*`），类级判据 C9 已改挂 SalesDoc', '判据 6·发货单底部独立区退场、加工费合计仍在（会红）：纸面取不到「加工项（数量：米）」与 `shipment-processing-items`；`shipment-processing-fee-total` 仍印且数值 = Σ 行级 `processingFee`（为 0 时不渲染该行）。执行点 = SalesDoc.test.tsx 的加工费合计用例（发货单底区已随整张纸退场，issue #7902）'],
    skip_reason='[backend-contract] 纯前端打印版式契约（无 LLM 环节，不进 agent-eval 冒烟）：断言由三份单据组件测试执行',
    tags=['ui', 'order', 'print', 'processing-items', 'sales-doc', 'quotation', 'shipment'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端打印版式契约（jsdom 渲染，夹具自建）；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-139 [NORMAL] 作业单纸面按两型命名（成品帘=加工单 / 面料单=面料单），且面料单不提供水洗唛打印入口（issue #7891）（源: cases/ui.yml）──
_CASE_UI_139 = EvalCase(
    id='UI-139',
    legacy_id='',
    title='作业单纸面按两型命名（成品帘=加工单 / 面料单=面料单），且面料单不提供水洗唛打印入口（issue #7891）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['面料单不能打印水洗唛，应该打印加工单，但是面料单不设计加工，只需要裁剪，那加工单打印名称如何统一命名呢，又能体现成品帘加工，又要体现面料单的简单裁剪工序', '选择A，面料单就叫面料单，不要叫裁剪单'],
    expectations=['direct_reply'],
    data_checks=["判据 1·纸面标题按作业单两型（会红）：`order_kind='processing'` ⇒ 纸面标题「加工单」；`order_kind='outbound'` ⇒「面料单」；缺键（存量单）⇒「加工单」。把标题写回恒定的「加工单」或改成「裁剪单」⇒ 红。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的标题用例", '判据 2·取值口单一（会红）：标题取自 frontend/admin-web/src/lib/processing-order.ts 的 WORK_ORDER_DOC_TITLES / workOrderDocTitleOf()（与 orderKindOf 的存量单口径一致），组件里不另写一份两型映射。执行点 = ProcessingDoc.test.tsx + 预览层标题（OrderDetail 的 printTargetTitle）', "判据 3·面料单隐藏水洗唛入口（会红）：加工单生产页在 `order_kind='outbound'` 时取不到「打印任务卡」入口与水洗唛纸面（TaskCardPrint / labels 预览）；`processing` 时照旧存在（负控）。把入口对所有型都藏或都对开 ⇒ 红。执行点 = frontend/admin-web/tests/unit/pages/processing-orders-production.test.tsx 的 #7891 用例"],
    skip_reason='[backend-contract] 纯前端命名与入口显隐契约（无 LLM 环节，不进 agent-eval 冒烟）：断言由 ProcessingDoc 与加工单生产页测试执行',
    tags=['ui', 'print', 'processing-doc', 'work-order-kind', 'wash-label'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端命名与入口显隐契约（jsdom 渲染 + 页面级测试，夹具自建）；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-140 [NORMAL] 加工单纸面的「工艺」按水洗唛形态分行：加工方式一行（工艺-加工类型-打开方式-定型）+ 特殊选项独立一行，其余工艺规格各自成行（issue #7891）（源: cases/ui.yml）──
_CASE_UI_140 = EvalCase(
    id='UI-140',
    legacy_id='',
    title='加工单纸面的「工艺」按水洗唛形态分行：加工方式一行（工艺-加工类型-打开方式-定型）+ 特殊选项独立一行，其余工艺规格各自成行（issue #7891）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['加工单打印的工艺也参考水洗唛上的加工和特殊选项的展示方式'],
    expectations=['direct_reply'],
    data_checks=['判据 1·加工方式一行、与 水洗唛同一取值口（会红）：纸面「加工方式：…」逐字 = frontend/admin-web/src/lib/wash-label-content.ts 的 washLabelCraftMode(src)（工艺-加工类型-打开方式-定型，`-` 连接），不再拆成「工艺 / 加工类型 / 打开方式 / 是否定型」四段；改回整串长句 ⇒ 红。执行点 = frontend/admin-web/tests/unit/components/ProcessingDoc.test.tsx 的工艺行用例', '判据 2·特殊选项独立成行（会红）：有特殊选项 ⇒ 纸面出现「特殊选项：…」并逐字 = washLabelSpecialOptions(src)；没有 ⇒ 该行不渲染（不印空值、不印「特殊选项：—」）。执行点 = 同文件两条用例', '判据 3·其余工艺规格各自成行、顺序沿用 craftSpecRows（会红）：款式 / 用料公式 / 档位 / 总褶数 / 褶数（每片）/ 理论褶倍 / 实际褶倍 / 面料米数 / 加工费米数 / 算料公式 / 是否对花 仍逐条在纸面（未被新形态吞掉），顺序与 frontend/admin-web/src/lib/craft-display.ts 的 CRAFT_SPEC_FIELDS 一致。执行点 = 同文件逐行断言', '判据 4·取值口单一（会红）：`src` 优先加工单快照行、缺快照时回落 `item.processingInfo`（两者键名同源），纸面不出现自造的推导；组件里不另写一份「定型 / 不定型」映射（应取 wash-label 的格式化）。执行点 = 同文件「缺快照时仍从 processingInfo 取值」用例'],
    skip_reason='[backend-contract] 纯前端打印版式契约（无 LLM 环节，不进 agent-eval 冒烟）：断言由 ProcessingDoc.test.tsx 执行',
    tags=['ui', 'print', 'processing-doc', 'wash-label'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端打印版式契约（jsdom 渲染，夹具自建）；前置不成立时对应单测直接红，agent-eval 栈不跑它',
)

# ── UI-142 [NORMAL] 销售订单列表：4 个同级文字链收敛为「1 主行动 + ⋯ 菜单」，非加急行不再印「不加急」，订单号可复制（issue #8011）（源: cases/ui.yml）──
_CASE_UI_142 = EvalCase(
    id='UI-142',
    legacy_id='',
    title='销售订单列表：4 个同级文字链收敛为「1 主行动 + ⋯ 菜单」，非加急行不再印「不加急」，订单号可复制（issue #8011）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-28 评审：B 端先打磨，C 端暂不做'],
    expectations=['direct_reply'],
    data_checks=["判据 1·「不加急」零出现（会红）：非加急行的「加急」单元格 `textContent === ''`（不是灰字、不是 CSS 隐藏）。执行点 = frontend/admin-web/tests/unit/pages/orders-list-row-actions.test.tsx。", '判据 2·行内可点元素 ≤ 2（会红）：每行 1 个主行动 + 1 个「⋯」触发器；旧的「查看/备注/发货/处理退款」四文字链同屏形态不再出现。执行点同上。', '判据 3·主行动按状态派生（会红）：待付款 → 收款 / 待发货 → 发货 / 已发货 → 确认收货 / 其它 → 无。执行点同上 + frontend/admin-web/tests/unit/pages/orders-confirm-modal.test.tsx。', '判据 4·菜单可达性（会红）：`aria-haspopup=menu` / `aria-expanded` / `role=menu` / `role=menuitem`，Escape 与点外部收起，**收起态菜单项不进 DOM**。执行点同上。', '判据 5·订单号复制（会红）：单元格内有 `aria-label` 为「复制订单号」 的按钮，点击写剪贴板并给 toast。执行点同上。'],
    skip_reason='[backend-contract] 纯前端交互契约（不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['orders-list', 'row-actions', 'noise'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端交互契约：页面渲染时 mock `@/lib/api` 与 `@/components/orders`，不依赖共享夹具与真实服务',
)

# ── UI-143 [NORMAL] 经营看板首屏：待处理前置 + 顶部两块 AI 内容合并成一卡（四态齐全）+ 骨架 + 环比改倍数（issue #8012 / #8105 / #8114）（源: cases/ui.yml）──
_CASE_UI_143 = EvalCase(
    id='UI-143',
    legacy_id='',
    title='经营看板首屏：待处理前置 + 顶部两块 AI 内容合并成一卡（四态齐全）+ 骨架 + 环比改倍数（issue #8012 / #8105 / #8114）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-28 评审：首屏第一眼要能看到要做的事'],
    expectations=['direct_reply'],
    data_checks=['判据 1·顶部只有一张 AI 卡（issue #8114，会红）：`daily-business-card` 在场，旧速览条 `today-overview-bar` 与旧简报块 `dashboard-briefing-section` 均取不到；卡头有 `briefing-toggle`（`aria-expanded`）与 AI 标记；收起态只有一句话（`today-overview-sentence` 同款文案），简报正文不在 DOM。执行点 = frontend/admin-web/tests/unit/pages/dashboard-first-screen.test.tsx。', '判据 2·加载出骨架（会红）：待处理卡与经营数据格在加载中渲染骨架块，卡上不出现 `…`。执行点同上。', '判据 4·首屏顺序（issue #8105 / #8114，会红）：`daily-business-card` 在 `dashboard-pending-section`（待处理）之前，待处理在「经营数据」之前；1440×900 真机下待处理 5 卡底边 ≤ 900（#8105 实测 1563→303 / 卡底 435；#8114 合并后卡底仍 435）。真机读数见 acceptance/2026-10-29/8105-dashboard/ 与 acceptance/2026-10-29/8114-merged-ai/。', '判据 5·合并卡四态（issue #8114，会红）：①开启且有数据 ⇒ 展开出完整简报（摘要 / 主动检查 / 昨日回顾 / 今日必办）；②开启但未生成 ⇒ 沿用 `briefing-collapsed-hint` + 查看设置入口；③**未开启** ⇒ 合并卡**仍在**（页面不再按开关整块隐藏），展开显示「每日经营简报未开启」+ 开启入口，且速览那句话照常（`getToday` 不发请求）；④开关未回 / 加载中 ⇒ 展开出 `briefing-skeleton`，收起态不等简报。负控：`stats=null` ⇒ 「经营数据没读到」而非「今日 0 单」；计数 null ⇒ `—` 不显示 0。执行点同上。', '判据 3·环比大基数保护（会红）：`|change| ≥ 500%` 改倍数（+23× / -8×）并带「基数较小」说明；阈值以下仍是百分比；上期为 0 仍是 `—`（#5792 裁定不回退）；页面上不再出现 `2300%`。执行点同上 + dashboard.test.tsx。'],
    skip_reason='[backend-contract] 纯前端契约（不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['dashboard', 'first-screen', 'skeleton'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    precondition='本用例是 [backend-contract] 纯前端契约：mock `@/lib/api`，不依赖真实服务',
)

# ── UI-144 [NORMAL] 官网下载页（/download，issue #8195）：从终端发布清单展示版本 / SHA-256 / 大小 / 发布时间 / 说明与两个下载按钮；清单缺失或格式坏 ⇒ 明确「暂未发布」且不编造版本号；伪协议不渲成链接；首屏正文进初始 HTML（源: cases/ui.yml）──
_CASE_UI_144 = EvalCase(
    id='UI-144',
    legacy_id='',
    title='官网下载页（/download，issue #8195）：从终端发布清单展示版本 / SHA-256 / 大小 / 发布时间 / 说明与两个下载按钮；清单缺失或格式坏 ⇒ 明确「暂未发布」且不编造版本号；伪协议不渲成链接；首屏正文进初始 HTML',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家要在官网下载车间一体机（Windows）与手持机（Android）的安装包，并核对版本与校验值；没有正式版时必须明确说「暂未发布」，不能显示一个不存在的版本'],
    expectations=['direct_reply'],
    data_checks=['**清单正常 ⇒ 逐项展示（会红）**：Windows 卡显示版本 / SHA-256 / 大小（`321.0 KB`）/ 发布时间 / notes 与「下载 Windows 安装包」链接（href 逐字等于清单的 `download_url`）；Android 卡显示 `versionName（versionCode N）` 与「下载 Android 安装包」链接。两个请求分别打到 `/terminal/latest.json` 与 `/terminal/android/latest.json`。执行点 = frontend/admin-web/tests/unit/pages/corporate-download.test.tsx。', "**缺失 / 坏 / 网络失败 ⇒ 「暂未发布」（会红）**：两个清单都 404 / 返回坏 JSON / 字段类型不对（`versionCode: 'seven'`、`sha256: 'not-a-hash'`）/ fetch reject ⇒ 两处「暂未发布」、**没有**下载按钮、页面不出现任何版本号；只有一端发布时另一端单独显示「暂未发布」（互不牵连）。", '**安全（会红）**：清单是外部输入，`download_url` 为 `javascript:` ⇒ 该端按「暂未发布」处理、不渲染 href。', '**首屏（会红）**：页面是服务端组件（正文进初始 HTML）——渲染出 h1「下载观星台终端」、三段安装说明（未知来源 / SmartScreen / 检查更新）与 SHA-256 校验方法，且不含「加载中...」骨架。', '**结构（会红）**：`next.config.mjs` 有 `/terminal/:path*` → `app.migaozn.com` 的同源转发（浏览器直连会被 CORS 挡）；`src/proxy.ts` 的官网白名单含 `/download`；`CorporateNav` / `CorporateFooter` 都有 `/download` 入口；sitemap 含 `/download/`。'],
    skip_reason='[backend-contract] 纯前端契约（mock fetch，不经过 LLM 对话/工具），由 admin-web vitest 执行，不进入 agent-eval 冒烟',
    tags=['corporate', 'download', 'terminal', 'no-fabrication', 'first-screen'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UI-147 [NORMAL] 商家后台读失败出口（issue #8200 · P1-06）：凡渲染共享空态原语 <EmptyState> 的文件必须带常驻读失败出口；/categories 读失败 ⇒ 失败面 + 重试，空态与「还没有商品分类」断言都不上屏（DQ-1）（源: cases/ui.yml）──
_CASE_UI_147 = EvalCase(
    id='UI-147',
    legacy_id='',
    title='商家后台读失败出口（issue #8200 · P1-06）：凡渲染共享空态原语 <EmptyState> 的文件必须带常驻读失败出口；/categories 读失败 ⇒ 失败面 + 重试，空态与「还没有商品分类」断言都不上屏（DQ-1）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['商家打开商品分类页时接口挂了：屏幕上不能写「还没有商品分类」「先建一个分类」（那是把没读到说成本来就没有），要明确说没读到并给重试'],
    expectations=['direct_reply'],
    data_checks=['**读失败 ⇒ 常驻失败面（会红）**：mock `categoryApi.getCategories` reject ⇒ 屏上有 `categories-load-error`（`role="alert"`）与 `categories-load-error-retry`。改前该页只有空 `catch` + `<EmptyState title="还没有商品分类">`，两个锚都不存在（红证读数见 PR body）。执行点 = frontend/admin-web/tests/unit/pages/categories.test.tsx。', '**不冒充空态（会红）**：同一失败态下 `categories-empty` 锚不在、「还没有商品分类」文案不在，且整屏经 `findEmptyDataAssertions`（单一源口径）无「没有数据」断言。', '**重试真的重发（会红）**：点 `categories-load-error-retry` ⇒ `getCategories` 调用次数增加，且成功回包后分类树渲染、失败面退场（不是只把失败面藏起来）。', '**对照读数（不许把真 0 判红）**：读成功且真的 0 条 ⇒ `categories-empty` 照旧在、失败面不在。', '**类级（会红）**：`frontend/admin-web/scripts/read-failure-empty-state-scan.mjs::componentEmptyStateOffenders` 在面内（`(dashboard)` + `src/components`）对「渲染 `<EmptyState>` 且无失败锚」的文件判红；台账 `COMPONENT_EMPTY_LEDGER` 现取 0 条、只许缩短；判别力自证 = `frontend/admin-web/tests/unit/read-failure-component-empty-state-guard.test.ts`。', '**审计读数纠偏**：审计 P1-06 用「有没有引用 `ListLoadError`」当代理指标 ⇒ 得出「37 页缺失」。逐页复核：`/products`（`products-load-failed`）/`/dashboard`（`dashboard-load-failed` + 分块重试）/`/production`（`production-board-error` + 重试，失败时不渲染 `production-board-empty`）/`/orders/[id]`（`order-detail-load-error` + 重试）**早已可区分读失败与真空态**；真实缺口只有 `/categories` 一处。'],
    skip_reason='[backend-contract] 纯前端渲染契约（vitest + mock 读接口），不经过 LLM 对话/工具，不进入 agent-eval 冒烟',
    tags=['read-failure', 'empty-state', 'categories', 'class-guard'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_UI_001,
    _CASE_UI_002,
    _CASE_UI_003,
    _CASE_UI_004,
    _CASE_UI_005,
    _CASE_UI_006,
    _CASE_UI_007,
    _CASE_UI_008,
    _CASE_UI_009,
    _CASE_UI_010,
    _CASE_UI_011,
    _CASE_UI_012,
    _CASE_UI_013,
    _CASE_UI_014,
    _CASE_UI_044,
    _CASE_UI_015,
    _CASE_UI_016,
    _CASE_UI_017,
    _CASE_UI_018,
    _CASE_UI_020,
    _CASE_UI_019,
    _CASE_UI_021,
    _CASE_UI_022,
    _CASE_UI_023,
    _CASE_UI_024,
    _CASE_UI_025,
    _CASE_UI_028,
    _CASE_UI_029,
    _CASE_UI_030,
    _CASE_UI_031,
    _CASE_UI_032,
    _CASE_UI_033,
    _CASE_UI_034,
    _CASE_UI_035,
    _CASE_UI_036,
    _CASE_UI_037,
    _CASE_UI_038,
    _CASE_UI_039,
    _CASE_UI_040,
    _CASE_UI_041,
    _CASE_UI_043,
    _CASE_UI_042,
    _CASE_UI_045,
    _CASE_UI_046,
    _CASE_UI_047,
    _CASE_UI_048,
    _CASE_UI_049,
    _CASE_UI_050,
    _CASE_UI_051,
    _CASE_UI_052,
    _CASE_UI_053,
    _CASE_UI_054,
    _CASE_UI_055,
    _CASE_UI_056,
    _CASE_UI_057,
    _CASE_UI_058,
    _CASE_UI_059,
    _CASE_UI_060,
    _CASE_UI_061,
    _CASE_UI_062,
    _CASE_UI_063,
    _CASE_UI_027,
    _CASE_UI_064,
    _CASE_UI_065,
    _CASE_UI_066,
    _CASE_UI_067,
    _CASE_UI_068,
    _CASE_UI_069,
    _CASE_UI_070,
    _CASE_UI_071,
    _CASE_UI_072,
    _CASE_UI_073,
    _CASE_UI_074,
    _CASE_UI_075,
    _CASE_UI_076,
    _CASE_UI_077,
    _CASE_UI_026,
    _CASE_UI_078,
    _CASE_UI_079,
    _CASE_UI_080,
    _CASE_UI_081,
    _CASE_UI_082,
    _CASE_UI_083,
    _CASE_UI_084,
    _CASE_UI_126,
    _CASE_UI_085,
    _CASE_UI_086,
    _CASE_UI_087,
    _CASE_UI_088,
    _CASE_UI_089,
    _CASE_UI_090,
    _CASE_UI_091,
    _CASE_UI_092,
    _CASE_UI_093,
    _CASE_UI_094,
    _CASE_UI_095,
    _CASE_UI_096,
    _CASE_UI_097,
    _CASE_UI_098,
    _CASE_UI_099,
    _CASE_UI_100,
    _CASE_UI_101,
    _CASE_UI_107,
    _CASE_UI_108,
    _CASE_UI_102,
    _CASE_UI_103,
    _CASE_UI_104,
    _CASE_UI_105,
    _CASE_UI_106,
    _CASE_UI_109,
    _CASE_UI_110,
    _CASE_UI_111,
    _CASE_UI_112,
    _CASE_UI_116,
    _CASE_UI_114,
    _CASE_UI_115,
    _CASE_UI_113,
    _CASE_UI_117,
    _CASE_UI_118,
    _CASE_UI_119,
    _CASE_UI_120,
    _CASE_UI_121,
    _CASE_UI_122,
    _CASE_UI_125,
    _CASE_UI_123,
    _CASE_UI_124,
    _CASE_UI_127,
    _CASE_UI_128,
    _CASE_UI_129,
    _CASE_UI_130,
    _CASE_UI_131,
    _CASE_UI_132,
    _CASE_UI_133,
    _CASE_UI_134,
    _CASE_UI_135,
    _CASE_UI_136,
    _CASE_UI_137,
    _CASE_UI_141,
    _CASE_UI_138,
    _CASE_UI_139,
    _CASE_UI_140,
    _CASE_UI_142,
    _CASE_UI_143,
    _CASE_UI_144,
    _CASE_UI_147,
)
