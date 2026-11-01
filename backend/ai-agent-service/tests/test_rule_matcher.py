# case_ids: MC-010, MC-011, AS-003, AS-004, AS-005, HR-002, DA-004, PR-013, DA-003, PP-002, OR-014, CH-010, PG-017, PG-064, CU-008, CU-001, CU-002, ST-002, ST-001, HR-009
"""规则匹配器单元测试（app/router/rule_matcher.py）

覆盖：_extract_text / RuleMatcher.match 关键词优先级 / 正则规则 / 未命中。
"""
from app.router.rule_matcher import REGEX_RULES, RuleMatcher, _extract_text
from app.router.intent_config import IntentType


class TestExtractText:
    def test_none_returns_empty(self):
        assert _extract_text(None) == ""

    def test_str_returns_same(self):
        assert _extract_text("查订单") == "查订单"

    def test_list_joins_text_blocks(self):
        content = [
            {"type": "text", "text": "你好"},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            {"type": "text", "text": "查订单"},
        ]
        assert _extract_text(content) == "你好 查订单"

    def test_other_type_stringified(self):
        assert _extract_text(42) == "42"


class TestMatch:
    def _match(self, message):
        return RuleMatcher().match(message)

    def test_empty_text_returns_none(self):
        assert self._match("") is None

    def test_none_returns_none(self):
        assert self._match(None) is None

    def test_whitespace_returns_none(self):
        assert self._match("   ") is None

    def test_capabilities_priority(self):
        result = self._match("你能做什么")
        assert result.intent == IntentType.CAPABILITIES
        assert result.confidence == 1.0
        assert result.source == "rule"

    def test_farewell_priority(self):
        result = self._match("再见")
        assert result.intent == IntentType.FAREWELL
        assert result.confidence == 1.0

    def test_order_statistics_priority_over_statistics(self):
        # "订单统计" 同时含"订单"和"统计"，必须优先 order_query 而非 statistics
        result = self._match("订单统计")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.95
        assert result.matched_keywords == ["订单统计"]

    def test_recent_orders_matches_dashboard(self):
        # DA-003 回归："最近5条订单"是看板语义（dashboard_stats recent_orders），
        # 此前「订单」关键词把它抢到 order_query，agent 用 order_query(list) 而非
        # dashboard_stats(recent_orders)——工具说明明确「最近X条订单优先用本工具」。
        result = self._match("最近5条订单")
        assert result is not None
        assert result.intent == IntentType.DASHBOARD

    def test_recent_orders_with_digits_matches_dashboard(self):
        result = self._match("最近3笔订单")
        assert result is not None
        assert result.intent == IntentType.DASHBOARD

    def test_recent_orders_no_digits_stays_order_query(self):
        # OR-001 回归（#3142 修正）："查看最近的订单"（无数字量词）是查订单列表，
        # 不是看板 recent_orders——#3124 的「最近+订单→DASHBOARD」规则过宽把它误路由，
        # smoke 档 OR-001 回归（7/8，唯一失败）。收紧：仅「最近+数字量词+订单」走看板。
        result = self._match("查看最近的订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_notification_mark_read_matches_notification(self):
        # ST-005 回归：KEYWORD_MAP 缺 NOTIFICATION 关键词，「把新订单通知标为已读」被
        # 「订单」抢到 ORDER_QUERY → agent 按 order 工具集误宣「无法改通知状态」（能力误宣）。
        result = self._match("把新订单通知标为已读")
        assert result is not None
        assert result.intent == IntentType.NOTIFICATION

    def test_notification_query_matches_notification(self):
        result = self._match("有没有未读通知")
        assert result is not None
        assert result.intent == IntentType.NOTIFICATION

    def test_return_restock_setting_matches_product(self):
        # PR-017 回归：「把遮光窗帘设置成退货回补库存」是商品设置（product_update 的
        # allow_return_restock），但「退货」关键词把它抢到 after_sales → agent 按售后
        # 工具集误宣「没有商品设置入口」（能力误宣，ST-005 同类）。
        result = self._match("把遮光窗帘设置成退货后可以回补库存")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    def test_regular_keyword_confidence(self):
        result = self._match("我要投诉")
        assert result.intent == IntentType.COMPLAINT
        assert result.confidence == 0.95
        assert result.source == "rule"
        assert result.matched_keywords == ["投诉"]

    def test_greeting_short_high_confidence(self):
        result = self._match("你好")
        assert result.intent == IntentType.GREETING
        assert result.confidence == 1.0

    def test_long_greeting_skipped(self):
        # 长消息含问候词，不识别为 greeting（无其他关键词 → None）
        assert self._match("你好呀，今天天气不错，很高兴见到你") is None

    def test_regex_order_number(self):
        result = self._match("ORD1234567890123")
        assert result.intent == IntentType.ORDER_QUERY
        assert result.confidence == 0.9
        assert result.matched_keywords[0].startswith("regex:")

    # ── 人事域路由（HR-002：创建员工/添加员工必须路由到 staff，不得被商品正则劫持）──
    def test_create_employee_account_routes_to_staff(self):
        result = self._match("创建一个员工账号，姓名张三，手机号13800000000")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    def test_add_employee_routes_to_staff(self):
        result = self._match("添加员工 李四 运营人员")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    def test_new_employee_routes_to_staff(self):
        result = self._match("新建一个员工账号")
        assert result.intent == IntentType.EMPLOYEE_MANAGE

    # ── 会话管理触发（看看当前有哪些会话 → session_manage）──
    def test_session_listing_routes_to_session_manage(self):
        result = self._match("看看当前有哪些会话")
        assert result.intent == IntentType.SESSION_MANAGE

    def test_customer_service_sessions_routes_to_session_manage(self):
        result = self._match("看看当前有哪些活跃的客服会话")
        assert result.intent == IntentType.SESSION_MANAGE

    def test_regex_product_creation(self):
        result = self._match("新建一个窗帘")
        assert result.intent == IntentType.PRODUCT_INQUIRY
        assert result.confidence == 0.9
        assert result.matched_keywords[0].startswith("regex:")

    def test_create_order_not_product_inquiry(self):
        # "创建订单" 含"订单"，不应被商品创建正则抢占
        result = self._match("创建订单")
        assert result.intent == IntentType.ORDER_CREATE

    def test_bare_confirm_create_not_product_inquiry(self):
        # issue #3731：商品创建规则的注释要求「+ 任意商品描述」，但尾组 `(?:商品|产品|…)?`
        # 是**可选**、且 `.{0,10}` 允许零字符 ⇒ 裸「确认创建」（答卡文案，AS-003 的 R3 输入）
        # 也命中 ⇒ 被判 PRODUCT_INQUIRY，并参与 L1 高置信域切换（#3625），把订单/售后域拉去商品域。
        result = self._match("确认创建")
        assert result is None or result.intent != IntentType.PRODUCT_INQUIRY

    def test_create_with_product_description_still_product_inquiry(self):
        # 同一条规则的射程守门（防「把规则改死」）：带商品描述时仍必须判商品域。
        # 末项专挑上一条规则覆盖不到的形态（动词与商品名之间有修饰语）—— 证明该规则不冗余。
        for message in ("创建遮光窗帘", "新建色卡", "新建个浅灰色的色卡"):
            result = self._match(message)
            assert getattr(result, "intent", None) == IntentType.PRODUCT_INQUIRY, message

    def test_no_product_regex_matches_without_product_noun(self):
        # 类级固化（issue #3731）：射程守门**遍历全部** PRODUCT_INQUIRY 正则（不只盯被修的那一条）
        # —— 将来再加一条「尾组可选」的商品规则，这里就会红。语料 = 有创建动词/数量词、无商品名词。
        bare = ("确认创建", "创建", "新建", "添加", "创建一个", "新建个", "帮我新建")
        product_patterns = [p for p, intent in REGEX_RULES if intent == IntentType.PRODUCT_INQUIRY]
        for pattern in product_patterns:
            for message in bare:
                assert pattern.search(message) is None, f"{message} 被 {pattern.pattern} 命中"

    def test_no_match_returns_none(self):
        assert self._match("随便说点什么") is None

    def test_ambiguous_order_and_aftersales_returns_none(self):
        # 跨域消息：订单实体 + 售后动作 → 多意图冲突，L1 不硬猜，交给 L2 带上下文分类
        # （修复生产回归：售后工单创建被"订单"关键词抢占路由）
        assert self._match("给订单20260826708690102创建退款售后工单") is None

    def test_ambiguous_product_and_aftersales_returns_none(self):
        # 售后补信息消息含"商品"实体 + "退款"动作 → 同样不硬猜
        assert self._match("客户手机号13800138000，要退款，商品有瑕疵") is None

    def test_ambiguous_order_entity_and_return_action_returns_none(self):
        # 指代上下文："这个订单…退货…建售后工单"
        assert self._match("这个订单的客户要退货，帮他建个售后工单") is None

    def test_single_aftersales_keyword_still_matches(self):
        # 纯售后意图（单意图）仍走 L1 快速通道
        result = self._match("看看售后工单")
        assert result is not None
        assert result.intent == IntentType.AFTER_SALES

    def test_single_order_keyword_still_matches(self):
        result = self._match("查一下订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_single_intent_multi_keywords_same_intent_still_matches(self):
        # 同意图多关键词（订单 + 待发货）不算冲突
        result = self._match("查一下待发货订单")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_mixed_regex_and_keyword_prefers_keyword_intent(self):
        # regex 命中不计长度：ORD 单号 + "退款" → 售后意图胜出（售后 skill 持有 order_query）
        result = self._match("ORD1234567890123 要退款")
        assert result is not None
        assert result.intent == IntentType.AFTER_SALES

    def test_quote_keyword_routes_to_quote(self):
        # 算料/报价关键词 → quote 意图
        result = self._match("帮我算一下窗帘要用多少布")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    def test_quote_dimension_regex_routes_to_quote(self):
        # 尺寸数字 + 褶皱 → quote 意图（正则规则）
        result = self._match("3米窗 2倍褶皱 多少钱")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    def test_quote_punch_hole_keyword(self):
        # 打孔帘关键词 → quote 意图
        result = self._match("打孔帘 2.7米高 报价")
        assert result is not None
        assert result.intent == IntentType.QUOTE

    # ── 售后政策类知识咨询（issue #3064 验收 P1-2：双端「退换货政策」未走知识卡片）──
    def test_return_policy_inquiry_routes_to_knowledge_faq(self):
        # 验收实测失败场景：元元/黄金策问退换货政策 → 规则判 after_sales → 未调 knowledge_search
        result = self._match("你们退换货政策是怎样的？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_store_return_policy_inquiry_routes_to_knowledge_faq(self):
        result = self._match("我们店的退换货政策是什么")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_aftersales_policy_inquiry_routes_to_knowledge_faq(self):
        result = self._match("售后政策是什么？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_warranty_inquiry_routes_to_knowledge_faq(self):
        result = self._match("窗帘质保多久？")
        assert result is not None
        assert result.intent == IntentType.KNOWLEDGE_FAQ

    def test_aftersales_operation_still_routes_to_after_sales(self):
        # 操作类不回归：无政策咨询词 → 仍售后工单
        for msg in ["我要退货", "帮我退款", "看看售后工单", "申请换货"]:
            result = self._match(msg)
            assert result is not None, f"{msg} 应命中"
            assert result.intent == IntentType.AFTER_SALES, f"{msg} 应判售后操作而非知识咨询"


class TestFinanceRouting:
    """FN-004 回归：收支/收入退款必须路由 FINANCE（此前「退款」被 AFTER_SALES 抢走）"""

    def _match(self, message):
        return RuleMatcher().match(message)

    def test_income_refund_routes_finance(self):
        """「本期收入退款是多少」→ FINANCE（收支汇总），不是 AFTER_SALES。"""
        result = self._match("本期收入退款是多少")
        assert result.intent == IntentType.FINANCE

    def test_income_routes_finance(self):
        result = self._match("这个月收入多少")
        assert result.intent == IntentType.FINANCE

    def test_refund_alone_stays_aftersales(self):
        """单纯「退款」仍走售后（不误伤）。"""
        result = self._match("我要退款")
        assert result.intent == IntentType.AFTER_SALES


class TestProcessingManageRouting:
    """PP-006 回归：「新增加工项」必须路由 PROCESSING_MANAGE（此前「加工项」
    被 PRODUCT_INQUIRY 抢 → agent 误宣「不在商品管理能力范围」）"""

    def _match(self, message):
        return RuleMatcher().match(message)

    def test_create_item_routes_processing(self):
        result = self._match("新增加工项，计价方式选按个")
        assert result.intent == IntentType.PROCESSING_MANAGE

    def test_processing_inquiry_stays_product(self):
        """「查加工项」仍走商品查询（不误伤）。"""
        result = self._match("查一下这个商品的加工项")
        assert result.intent == IntentType.PRODUCT_INQUIRY


class TestProcessingOrderRouting:
    """PG-017（issue #3921）：「加工单」必须确定性路由到订单域（ORDER_QUERY）。

    根因：L1 关键词表只有「加工项/加工项目/加工费」（→ PRODUCT_INQUIRY），**没有
    「加工单」**——「查看加工单数据」不命中任何规则 → 降级 L2 LLM 分类 → 被归到
    商品域（加工项）→ agent 调 processing_item_query 返回加工项目录（证据会话
    sess_f3c0ee0d2cc342a0 + PG-017 首跑 0 分）。修法：加工单/JG-xxx → ORDER_QUERY
    （订单域），由 order_skill 的概念区分 prompt 引导（agent 暂不接入加工单工具）。
    """

    def _match(self, message):
        return RuleMatcher().match(message)

    def test_processing_order_query_routes_order(self):
        """「查看加工单数据」→ ORDER_QUERY（不再落 L2 被归到商品域）。"""
        result = self._match("查看加工单数据")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_processing_order_status_routes_order(self):
        result = self._match("这个订单的加工单什么状态")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_processing_order_no_routes_order(self):
        result = self._match("加工单号 JG-20260915-0001 查一下")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_jg_serial_alone_routes_order(self):
        """JG-xxx 加工单号 → ORDER_QUERY（正则兜底，消息不带「加工单」三字时）。"""
        result = self._match("JG-20260915-0001 现在什么状态")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_processing_item_inquiry_unchanged(self):
        """回归：加工项查询仍走商品域（不误伤，issue #3921 不得破坏 #3917 的加工项目录查询）。"""
        result = self._match("查一下有哪些加工项")
        assert result is not None
        assert result.intent == IntentType.PRODUCT_INQUIRY

    # ── 加工**套件**（issue #8300，PG-064 实测）──────────────────────────────
    # 病灶：L1 只有「加工单」没有「加工套件」⇒ 降级 L2 被判 `product_inquiry`
    # （2026-11-01 run 41258535162 系列实测：`Routing to 'product_inquiry'` → 执行 `[product]`）。
    # 后果叠加读面裁剪后更硬：`processing_order_set_query` 不在 product 的声明面 ⇒ 工人问
    # 「店里的加工套件有哪些」得到的是「加工项目录」（`processing_item_query` 顶替）。
    def test_processing_order_set_routes_order(self):
        """「加工套件」→ ORDER_QUERY（套件工具绑在订单域）。"""
        result = self._match("我们店里的加工套件现在有哪些？")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_processing_order_set_scan_progress_routes_order(self):
        """「套件扫码进度」同样落订单域（套件工具的 scan_progress action）。"""
        result = self._match("加工套件 JG-20261101-0001 的扫码进度到哪了")
        assert result is not None
        assert result.intent == IntentType.ORDER_QUERY

    def test_processing_item_manage_unchanged(self):
        """回归：加工项管理仍走 PROCESSING_MANAGE（PP-006）。"""
        result = self._match("新增加工项，计价方式选按个")
        assert result.intent == IntentType.PROCESSING_MANAGE


class TestOrderVerbBeatsQuote:
    """显式交易动词优先于"尺寸+算料"（issue #3365，OR-014 根因之二）。

    实证：OR-014 的「帮我下单，遮光窗帘 3 米，要打孔加工」同时命中算料模式
    （`\d+米?.{0,10}(打孔…)`）→ 被路由到 **customer_quote**，而该 skill **没有 order_create**
    → 模型无法下单，只能在收货表单/转人工之间空转（同一用例不同跑表现漂移）。
    语义：顾客说了"下单/买/订"，交易动作比算料权威 —— 算料只是手段。
    """

    def _intent(self, msg):
        r = RuleMatcher().match(msg)
        return r.intent if r else None

    def test_order_verb_wins_over_quote_dimension(self):
        assert self._intent("帮我下单，遮光窗帘 3 米，要打孔加工") == IntentType.ORDER_CREATE

    def test_quote_still_wins_without_order_verb(self):
        """回归：纯算料诉求（无交易动词）仍走报价"""
        assert self._intent("3米窗 2倍褶皱 多少钱") == IntentType.QUOTE

    def test_other_order_verbs(self):
        for msg in ("我要买遮光窗帘 3 米", "帮我买 2 米面料", "创建订单"):
            assert self._intent(msg) == IntentType.ORDER_CREATE, msg


class TestCustomerProfileRouting:
    """客户画像/工艺偏好/常用物流 → CUSTOMER_QUERY（issue #4198，CU-008 恒红真因）。

    机制（域切分 + 单关键词抢路由）：KEYWORD_MAP 里**没有**任何客户域关键词，
    CU-008 原文只命中「物流」→ `logistics_track`（conf 0.95）→ 域 = order
    （`_SKILL_DOMAIN_KEYWORDS` 与 INTENT_DOMAINS 均归 order）→ **order 域工具集不含
    `customer_manage`** ⇒ 模型物理不可达，`must_succeed: customer_manage` 必然红
    （run 35295494688 @d5bca241 及此前 6 个 run，实测命令见 PR body）。

    为什么**不**加进 KEYWORD_MAP：该表是**多意图收集**，命中 ≥2 个意图即返回 None 降级 L2
    （非确定性）；本用例同时含「工艺偏好」+「物流」两族词 ⇒ 加表会让它变 L2。
    ⇒ 走本文件既有的**前置改判**范式（同 订单统计→order_query / 回补库存→product /
    交易动词→order_create / 售后政策→knowledge_faq）：位置在「显式交易动词优先」之后、
    「尺寸+算料→quote」之前（依据本文件既有原则"交易动作比手段权威"）。
    """

    def _intent(self, message):
        """返回意图值（None = 无命中/降级 L2）。"""
        result = RuleMatcher().match(message)
        return result.intent.value if result else None

    def test_cu008_utterance_routes_to_customer_query(self):
        """红证：CU-008 原文改前 = logistics_track（域 order，customer_manage 不可达）。"""
        assert self._intent("帮我看看客户张三的工艺偏好和常用物流设置是什么") == "customer_query"

    def test_customer_phrase_beats_logistics_keyword_without_l2_degrade(self):
        """关键不变式：客户短语 + 「物流」同现 ⇒ 必须 CUSTOMER_QUERY，**不得降级 L2（None）**。

        这是本单的存在理由 —— KEYWORD_MAP 路线会让复合句变 L2（多意图平局），
        确定性路由随之丢失；前置改判必须给出唯一确定的意图。
        """
        for msg in ("帮我看看客户张三的工艺偏好和常用物流设置是什么",
                    "客户张三的常用物流设置是什么"):
            assert self._intent(msg) == "customer_query", msg

    def test_other_customer_profile_phrasings(self):
        """其余客户档案类短语同样确定性命中（改前均为 None → 落 L2）。"""
        for msg in ("查客户列表", "看张三的客户档案", "客户张三的客户画像是什么",
                    "客户张三的消费偏好是什么", "看看客户信息"):
            assert self._intent(msg) == "customer_query", msg

    def test_no_hijack_of_order_and_aftersales_utterances(self):
        """负例（零劫持）：含「客户」的订单/售后话语**逐条保持改前意图**（#4198 电池复算抽样）。

        断言的是**精确意图**（含 `None` = 改前就未命中、落 L2），不是 `!= customer_query`
        ——「没被劫持到客户域」也可能是被劫持到**别的**域，等值断言才排得掉。
        期望值与改前实测逐条一致（本文件在改前跑此用例**全绿**，见 PR body 红证对照）：
          · CH-019「帮客户…下一单」     = quote        （改前 quote）
          · CR-003「就这个，帮我下单…」  = order_create （改前 order_create）
          · OR-006「客户确认收货了…」    = None         （改前 None → 落 L2）
          · AS-003「查一下客户手机号…订单」= order_query  （改前 order_query）

        只用具体短语（禁裸「客户」）的理由就在这些负例里：「帮客户…下一单」若被裸词劫持，
        下单/查询/售后全被改判到客户域 ⇒ order_create 不可达（把本单的病灶反向复制一遍）。
        """
        for msg, want in (
            ("帮客户张三（手机号 13800138000）下一单：遮光窗帘 3 米，要打孔加工", "quote"),
            ("就这个，帮我下单，客户张三 13800138000，2件", "order_create"),
            ("客户确认收货了，标记完成", None),
            ("查一下客户手机号 13800138000 最近的订单", "order_query"),
        ):
            got = self._intent(msg)
            assert got == want, f"劫持：{msg!r} 期望 {want}，实得 {got}"

    def test_customer_query_declared_tool_is_reachable_in_its_domain(self):
        """可达性判据：`customer_query` → 路由 key → 该 skill 工具集必须含 `customer_manage`。

        这是 CU-008 那一类的**常驻守卫**：把「用例声明的工具必须在该域可达」钉死，
        防同类复发（改前 CU-008 的组合 `logistics_track` → order skill，其工具集不含
        `customer_manage` ⇒ 模型物理不可达）。
        """
        from app.graph.skills.skill_registry import get_skill_registry

        registry = get_skill_registry()
        route_key = registry.get_intent_to_route_map("mibao").get(IntentType.CUSTOMER_QUERY.value)
        assert route_key, "intent customer_query 无路由 key（声明面缺失）"
        tools = list(getattr(registry.get(route_key), "tool_names", None) or [])
        assert "customer_manage" in tools, f"route_key={route_key} tools={tools}"

    def test_cu008_declared_tool_reachable_from_the_utterance(self):
        """端到端可达性：CU-008 原文 → 意图 → 该域工具集 ⊇ 用例声明的工具。

        改前必红：`logistics_track` → order skill 的 9 个工具里没有 `customer_manage`。
        """
        from app.graph.skills.skill_registry import get_skill_registry

        intent = self._intent("帮我看看客户张三的工艺偏好和常用物流设置是什么")
        registry = get_skill_registry()
        route_key = registry.get_intent_to_route_map("mibao").get(intent)
        tools = list(getattr(registry.get(route_key), "tool_names", None) or [])
        assert "customer_manage" in tools, f"intent={intent} route_key={route_key} tools={tools}"


class TestCustomerProductBrowsePhrasing:
    """C 端口语型商品浏览 → product_inquiry（issue #3364，E2E 实测红）。"""

    def _intent(self, msg):
        r = RuleMatcher().match(msg)
        return r.intent if r else None

    def test_colloquial_browse(self):
        for msg in ("有什么遮光窗帘推荐", "看看这款面料", "有没有雪尼尔面料"):
            assert self._intent(msg) == IntentType.PRODUCT_INQUIRY, msg

    def test_order_instruction_with_product_noun_not_browse(self):
        """反向：下单指令含商品名词但无浏览句式 → 必须走 ORDER_CREATE（不是商品咨询）。"""
        assert self._intent("帮我下单，遮光窗帘 3 米，要打孔加工") == IntentType.ORDER_CREATE


class TestSettingsRouting:
    """设置类查询的 L1 确定性路由（ST-002 实测红）。

    病灶：`SYSTEM_SETTINGS` / `AI_CONFIG` 两个意图**都在** `IntentType` 且都映射到 `settings_manage`，
    但 `KEYWORD_MAP` 里**没有它们的 L1 关键词** ⇒ 设置类查询一律降级 L2 分类器。
    实测后果（本次真实 LLM 评测，persona=mibao）：`ST-001`「查看系统设置」蒙对；
    `ST-002`「AI客服配置是什么」被判成 `capabilities` ⇒ agent 回自我介绍（`rounds=1 tools=[]`），
    `settings_manage(action=get_ai_config)` **不可达** ⇒ 该用例确定性红（日志标 `🔬复现型回归`）。
    """

    def _intent(self, msg):
        r = RuleMatcher().match(msg)
        return r.intent if r else None

    def test_ai_config_phrase(self):
        """ST-002 输入原文：必须落 AI_CONFIG（→ settings_manage），即"查询类必须支持"。"""
        assert self._intent("AI客服配置是什么") == IntentType.AI_CONFIG

    def test_system_settings_phrase(self):
        """ST-001 输入原文（回归保护）：系统设置 → SYSTEM_SETTINGS。"""
        assert self._intent("查看系统设置") == IntentType.SYSTEM_SETTINGS

    def test_not_capabilities(self):
        """反向：同一句话**不得**被判成 capabilities —— 那正是本次实测的错误落点。"""
        assert self._intent("AI客服配置是什么") != IntentType.CAPABILITIES

    def test_compound_not_hijacked(self):
        """负控（CU-008 家族）：含「物流设置」的复合句不得被设置域抢走（那是客户域/物流域的事）。"""
        msg = "帮我看看客户张三的常用物流设置是什么"
        assert self._intent(msg) not in (IntentType.SYSTEM_SETTINGS, IntentType.AI_CONFIG)


class TestEveryIntentHasL1OrRegisteredExemption:
    """类级元守卫（铁律 8：修一个缺陷只修这一处 = 没修）。

    判据：**每个 `IntentType` 要么在 `KEYWORD_MAP` 里有 L1 关键词，要么在 `L2_ONLY_EXEMPT` 里
    且写明"为什么它可以只走 L2"**。未登记即红。
    形态来源（ST-002 实测）：意图**存在**、工具映射**也在**，唯独**没有 L1 关键词** ⇒ 查询只能降级 L2
    ⇒ 一次判错就整句走 `direct_reply`、工具**不可达**。这类"沉默的不可达"没有任何东西会报。
    豁免表**只许缩短**：新增豁免必须在同一条里写清理由（`L2_ONLY_EXEMPT` 的值就是理由）。
    """

    # 显式豁免：允许只走 L2 的意图（每条都带理由）。**只许缩短**。
    # 口径：本仓的路由设计是「**L2 分类器为主 + L1 规则为已知误路由打的补丁**」⇒ "没有 L1 关键词"
    # 本身不等于缺陷；本表的作用是让这个集合**可见、被有意持有**，并逼新增意图/新发现的误路由
    # 走一次显式登记（要么补 L1 + 红证 = ST-002 的修法，要么在这里写清为什么可以只走 L2）。
    L2_ONLY_EXEMPT: dict[IntentType, str] = {
        # 兜底意图本身就是 L2 的落点，不该有 L1 关键词
        IntentType.GENERAL: "L2 兜底落点本身",
        # ── 以下各条的"已立证"口径（2026-10-16，证据与复算命令见 issue #7038 的评论）──
        #   「已立证无用例面」= 全库用例里**没有**任何一条的 expectations/must_succeed 落到该意图的工具；
        #   「已立证」= 它在评测用例里有覆盖，且其覆盖用例在 2026-10-16 那次基线里**全部通过**
        #     （唯一落在这些覆盖里且失败的是 `HR-005`，其红因是 **action 过度指定**，与 L2 路由无关）。
        #   ⚠️ 「已立证」不等于"任何措辞都不会失败"——它只说明**已有的用例面**没暴露该意图的 L2 路由问题。
        IntentType.CUSTOMER_MANAGE: "L2 主路径；无已立证的确定性误路由（出现即按 ST-002 模式补 L1 + 红证）· **已立证**（覆盖 10 条用例全过）",
        IntentType.CUSTOMER_QUERY: "同上（客户域查询；CU-008 的复合句劫持由「客户域前置改判」承担）· **已立证**（覆盖 10 条用例全过）",
        IntentType.CATEGORY_MANAGE: "同上（分类树读取；无已立证的确定性误路由）· **已立证**（覆盖 2 条用例全过）",
        IntentType.PERMISSION_MANAGE: "同上（角色权限）· **已立证**（覆盖 3 条用例；唯一红条 `HR-005` 的红因是 action 过度指定 ≠ L2 路由）",
        IntentType.DATA_REPORT: "同上（报表/分析；与 STATISTICS/DASHBOARD 的边界由 L2 判）· **已立证**（覆盖 5 条用例全过）",
        IntentType.KNOWLEDGE_MANAGE: "同上（知识库管理；C 端 KNOWLEDGE_FAQ 另有 L1）· **已立证无用例面**（全库 0 条覆盖）",
        IntentType.AFTER_SALES_CREATE: "同上（售后工单**创建**；B 端按裁定不支持创建单据 ⇒ 主要面在 C 端）· **已立证**（覆盖 8 条用例全过）",
        IntentType.PROCESSING_ORDER_GENERATE: "同上（加工单**生成**；同上，B 端不支持创建单据）· **已立证无用例面**（全库 0 条覆盖）",
        IntentType.PROCESSING_ORDER_QUERY: "同上（加工单查询；「加工单」关键词已在 ORDER_QUERY 上）· **已立证**（覆盖 4 条用例全过）",
        IntentType.PROCESSING_ORDER_UPDATE: "同上（加工单变更）· **已立证无用例面**（全库 0 条覆盖）",
    }

    # ⚠️ 口径（issue #7038 立证时**实测**取到，勿凭印象改）：
    #   · `KEYWORD_MAP` 键数 = 22；`REGEX_RULES` **只产出 3 个意图** —— `order_query`/`product_inquiry`/`quote`。
    #   · 因此「声明式规则层可达」= 这 25 项；下表里那些**不在这 25 项内**的意图，就是"只靠 L2 或靠
    #     `match()` 内的命令式特判"的那一批（例如 `customer_query` 由 `match()` 的「客户域前置改判」可达，
    #     不由本表的声明式两层可达 —— 见它自己那条理由）。
    #   · 本表**不是**"这些意图只走 L2"的同义语，而是"它们没有声明式 L1 关键词，被有意持有"。
    @staticmethod
    def _rule_reachable() -> set:
        """**声明式**规则层可达的意图 = `KEYWORD_MAP` 的键 ∪ `REGEX_RULES` 能产出的意图。

        注意它只是可达性的**下界**：`RuleMatcher.match()` 里还有命令式特判（长短语优先、
        客户域前置改判、算料 re-route 等），那些不在这两层里 ⇒ 本判据不声称"不在集合内 ⇒ 不可达"。
        """
        from app.router.rule_matcher import KEYWORD_MAP, REGEX_RULES

        return set(KEYWORD_MAP) | {intent for _, intent in REGEX_RULES}

    @staticmethod
    def _unreachable(intents, reachable, exempt):
        return [(i.value if hasattr(i, "value") else str(i))
                for i in intents if i not in reachable and i not in exempt]

    def test_no_unregistered_l2_only_intent(self):
        missing = self._unreachable(list(IntentType), self._rule_reachable(), self.L2_ONLY_EXEMPT)
        assert missing == [], (
            f"这些意图在**声明式规则层（KEYWORD_MAP ∪ REGEX_RULES）**不产出、也没登记豁免：{missing}\n"
            "首选：给它们补 L1 关键词（ST-002 的修法）；次选：加进 L2_ONLY_EXEMPT 并写清理由。"
        )

    def test_exempt_table_has_no_rule_reachable_intent(self):
        """豁免表必须**最小**：声明式规则层已可达的意图**不许**躺在豁免表里（「只许缩短」的机器化）。

        落地时本判据**是绿的**（表里没有声明式可达项）—— 它的价值是拦住**将来**把已可达意图塞进表里
        （那会让"豁免"变成垃圾桶，并掩盖真正的缺词）。这条**不会**因为 `match()` 的命令式特判而误报。
        """
        overlap = sorted(i.value for i in self.L2_ONLY_EXEMPT if i in self._rule_reachable())
        assert overlap == [], (
            f"豁免表里有**声明式规则层已可达**的意图：{overlap}\n"
            "⇒ 它们不需要豁免，请从 L2_ONLY_EXEMPT 里删掉（豁免表只许缩短）。"
        )

    def test_guard_has_teeth(self):
        """判别力自证：把 ST-002 的修复**摘掉**（= 意图存在但声明式两层都不产出）⇒ 守卫必须具名报出它。"""
        stripped = {i for i in self._rule_reachable() if i != IntentType.AI_CONFIG}
        missing = self._unreachable(list(IntentType), stripped, self.L2_ONLY_EXEMPT)
        assert "ai_config" in missing, "摘掉 AI_CONFIG 的关键词后守卫没有报 ⇒ 守卫退化成空断言"


class TestScheduledTaskRouting:
    """定时提醒的 L1 确定性路由（issue #7038 的唯一真缺口，2026-10-19）。

    背景：`scheduled_task_manage` 只绑 reminder skill（兜底 general 也没有它）⇒
    L2 判错一次就整句 direct_reply、工具不可达。本类钉住「该命中的命中、不该抢的不抢」。
    红证：删掉 `KEYWORD_MAP[SCHEDULED_TASK_MANAGE]` ⇒ `test_relative_followup` 红。
    """

    def test_relative_followup(self):
        r = RuleMatcher().match("3 天后提醒我跟进张先生")
        assert r is not None and r.intent == IntentType.SCHEDULED_TASK_MANAGE

    def test_explicit_reminder(self):
        r = RuleMatcher().match("帮我设一个定时提醒，明天下午三点")
        assert r is not None and r.intent == IntentType.SCHEDULED_TASK_MANAGE

    def test_notification_not_hijacked(self):
        r = RuleMatcher().match("把新订单通知标为已读")
        assert r is not None and r.intent == IntentType.NOTIFICATION

    def test_bare_reminder_word_is_not_routed(self):
        """裸「提醒」刻意不收：订单/通知类复合句不得被抢。"""
        r = RuleMatcher().match("提醒我一下这个订单到哪了")
        assert r is None or r.intent != IntentType.SCHEDULED_TASK_MANAGE


class TestStaffAccountRouting:
    """HR-009：「帮我开个客服账号…」在 L1 一个词都不命中。

    词表里有「开个账号 / 开通账号 / 员工账号」，但输入是「开个**客服**账号」—— **子串不含「开个账号」**
    ⇒ 该句落 L2 兜底。本次真实 LLM 评测（`persona=mibao`）该用例确定性红：实况 agent 调了
    `employee_manage` + `role_manage`×3 + `nav_guide`，而用例期望写的是 `direct_reply`。
    按 2026-10-16 边界裁定（#5247 评论）：「**开客服账号**」= 创建**非单据对象** ⇒ **必须支持** ⇒
    正确意图 = `STAFF_MANAGE`（映射 `["employee_manage", "role_manage"]` —— **正是实测调用的那两个工具**）。
    ⇒ 本组判据把"L2 蒙对"变成"L1 确定"，也让 #7035 第二相重锚该用例期望时**有确定的目标意图**。
    """

    def _intent(self, msg):
        r = RuleMatcher().match(msg)
        return r.intent if r else None

    def test_staff_account_phrase(self):
        """HR-009 输入原文：必须落 STAFF_MANAGE（= 真去开账号，而不是回一句"我不能"）。"""
        msg = "帮我开个客服账号，姓名李四，手机号 13800009999，密码 Test123456"
        assert self._intent(msg) == IntentType.STAFF_MANAGE

    def test_short_form(self):
        """去掉姓名/手机号等修饰后仍必须命中（防"只有长句才过"）。"""
        assert self._intent("帮我开个客服账号") == IntentType.STAFF_MANAGE

    def test_negative_control_session(self):
        """负控：「客服会话」不得被账号域抢走（会话管理另有意图，SE-001 家族）。"""
        assert self._intent("看看当前有哪些客服会话") == IntentType.SESSION_MANAGE
