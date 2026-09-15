"""商品图片域的能力误宣守卫（issue #3931）— 语义归一判据（锚点 × 否定 × 自我主体）。

生产实证（sess_2efa2071bb1747d8，2026-09-15）：用户「先把这张色卡图设为主图」，
agent 拒绝：「我这个商品管理入口只能改价格、名称、描述、状态、回补库存开关这些字段，
不包含图片上传……您上传的这张色卡图我这边拿不到可写入的地址，所以没法代劳」——
但同一回合 tool_calls 里就有 product_update(images=[色卡URL])，且 19:49 用户坚持后
改用 product_manage(action=update, images=[2 个 URL]) 成功 —— 图片更新能力真实存在。

守卫要求（与下单域 #3389/#3477 同构）：**AI 自己否定一个它实际拥有的能力**（图片更新）
→ 必须命中并纠正；「顾客没发图片」「主图还是空的建议上传」「我没权限删除商品」等
非能力误宣（中性说明 / 真实越权）→ 不得命中（防误伤，判别性测试）。
"""
# case_ids: PR-017, PR-026, PR-027

import json

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.skills.base_skill import (
    _product_image_capability_available,
    _product_image_denial_hit,
    _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE,
    capability_denial_text_hit,
    execute_skill,
)


class TestProductImageDenialHit:
    """19:46:32 拒绝文本必须命中（能力误宣），中性/越权文本不得命中。"""

    def test_production_denial_texts_hit(self):
        for t in [
            # 19:46:32 拒绝原文（一）：显式否定「不包含图片上传」
            "我这个商品管理入口只能改价格、名称、描述、状态、回补库存开关这些字段，不包含图片上传",
            # 19:46:32 拒绝原文（二）：「拿不到可写入的地址」+「没法代劳」
            "您上传的这张色卡图我这边拿不到可写入的地址，所以没法代劳",
            # 同族变体：明确的主图能力否定
            "抱歉，这个入口不能设置主图，图片上传功能不在我的能力范围内",
            "抱歉，我这边没法设置主图，只能请您去后台操作",
        ]:
            assert capability_denial_text_hit(t), f"能力误宣未命中: {t!r}"
            assert _product_image_denial_hit(t), f"图片域判据未命中: {t!r}"

    def test_neutral_statements_not_hit(self):
        """防误伤：中性说明 / 真实越权不得被当成能力误宣纠正。"""
        for t in [
            # 顾客没发图（事实说明，非自我能力否定）
            "顾客没发图片给我，我这边看不到任何色卡图",
            # 中性建议（主图是空的 → 建议上传）
            "主图目前还是空的，建议您先上传一张主图",
            # 真实越权（删除商品确实无此能力/权限）
            "我没权限删除商品，这个操作需要管理员账号",
            # 中性描述（商品没设主图，帮忙查详情）
            "该商品没有设置主图，我帮您查一下详情",
            # 与图片无关的既有边界（回归：下单域越权拒绝不得因图片判据误报）
            "小布没有权限查看其他租户的数据，只能看您自己的订单",
            "库存不足无法创建订单",
        ]:
            assert capability_denial_text_hit(t) == "", f"中性/越权文本误命中: {t!r}"
            assert _product_image_denial_hit(t) == "", f"图片域判据误命中: {t!r}"

    def test_order_denial_phrasing_unaffected(self):
        """下单域既有判据不因图片域扩展而回归（锚点不相交）。"""
        for t in ["没有权限帮您下单", "非常抱歉，小布这边没有办法帮您直接下单哦",
                  "抱歉，下单功能暂时不可用"]:
            assert capability_denial_text_hit(t), f"下单域判据回归: {t!r}"


class TestProductImageCapabilityFactDriven:
    """能力可达性问**工具注册表**（product_manage 有没有 images 参数），不硬编码。"""

    def test_available_when_registry_has_product_manage_with_images(self):
        tool = MagicMock()
        tool.parameters = {"type": "object",
                           "properties": {"images": {}, "detail_images": {}}}
        registry = MagicMock()
        registry.get_tool.side_effect = lambda n: tool if n == "product_manage" else None
        assert _product_image_capability_available(registry) is True

    def test_unavailable_when_tool_missing(self):
        registry = MagicMock()
        registry.get_tool.side_effect = lambda n: None
        assert _product_image_capability_available(registry) is False

    def test_unavailable_when_no_image_params(self):
        tool = MagicMock()
        tool.parameters = {"type": "object", "properties": {"price": {}}}
        registry = MagicMock()
        registry.get_tool.side_effect = lambda n: tool if n == "product_manage" else None
        assert _product_image_capability_available(registry) is False


class TestProductImageDenialMorphology:
    """形态优先（issue #3936）：V+不了/V+不到 编译形态，而非 #3934 的枚举词表。

    判别性：**新措辞**（非生产原文）也必须命中 —— 证明判据是「形态 × 锚点 × 自我主体」
    的结构匹配，不是对着 sess_2efa2071bb1747d8 的拒绝原文过拟合。
    """

    def test_new_phrasing_denials_hit(self):
        for t in [
            # V+不了 形态（新动词，未逐词登记过）
            "图片这个我这边做不了，您去后台改吧",
            "上传图片这个功能我这边弄不了，只能请您自己操作",
            # V+不到 形态
            "我这边换不到可用的图片地址",
            # 既有语义词干（没有…能力/权限）覆盖的新措辞
            "图片这个我这边没有对应的上传能力",
            "我的工具列表里没有图片写入这个功能",
            # 不包含 + 主图锚点
            "主图这个功能不包含在我的能力里",
        ]:
            assert capability_denial_text_hit(t), f"能力误宣未命中（新措辞）: {t!r}"
            assert _product_image_denial_hit(t), f"图片域判据未命中（新措辞）: {t!r}"

    def test_neutral_new_phrasings_not_hit(self):
        """新措辞的防误伤：中性说明 / 非自我否定不得命中。"""
        for t in [
            # 客观事实（顾客没发图，非能力否定）
            "顾客没发图片给我，我这边没有收到任何图片",
            # 中性建议（不是拒绝）
            "建议您先上传一张主图，我再帮您设置",
            # 非自我主体（商品缺图是客观状态）
            "这个商品没有主图，我帮您查一下详情",
            # 权限真实受限（删除商品确实无能力）
            "我没权限删除商品，需要管理员账号操作",
        ]:
            assert capability_denial_text_hit(t) == "", f"中性文本误命中: {t!r}"
            assert _product_image_denial_hit(t) == "", f"图片域判据误命中: {t!r}"


class TestProductImageDenialCrossClause:
    """迭代2（issue #3938，PR-026/027 评测复现 run 34976473654）：跨小句否定 + 新形态。

    中文话题-评论结构把「图片锚点」与「能力否定」拆到两个小句（「改商品图片属于
    商品编辑操作，我这边没有这个能力」）——旧判据要求同小句共现即漏。判别性文本
    直接取自评测真实 LLM 输出（重放证据）。
    """

    def test_eval_transcript_denials_hit(self):
        for t in [
            # 评测 R1 原文：锚点「主图」句1 + 否定「没有…工具」句2（跨小句 + 工具形态）
            "更换商品主图属于商品管理模块的写操作，我这边没有对应的执行工具，没法直接帮您",
            # 评测 R1 原文：同小句但「执行不了」（执行不在旧 V+不了 动词前缀表）
            "设置主图这个操作我这边执行不了",
            # 评测 R1 原文：锚点「图片」句1 + 否定「没有这个能力」句2（跨小句）
            "改商品图片属于商品编辑操作，我这边没有这个能力",
            # 评测 R2 原文变体：跨小句 + 「操作不了」
            "更换主图这个操作我这边操作不了，只能请您去后台改",
            # 跨小句 + 「没有…通道」
            "改图这块属于商品编辑，我这边没有图片上传的通道",
        ]:
            assert capability_denial_text_hit(t), f"能力误宣未命中（评测原文）: {t!r}"
            assert _product_image_denial_hit(t), f"图片域判据未命中（评测原文）: {t!r}"

    def test_cross_clause_false_positives_not_hit(self):
        """跨小句放宽的假阳性守卫：通用权限否定 + 他处有图片词 → 不得命中。"""
        for t in [
            # 图片词在句1，句2是**通用权限**否定（与图片能力无关）→ 不得误报
            "顾客问主图怎么换，我这边没有权限查看其他租户的数据",
            # 顾客没发图（事实，非能力否定）
            "顾客没发图片给我，我这边没有收到任何图片",
            # 中性建议
            "主图目前还是空的，建议您先上传一张主图",
            # 非自我主体
            "这个商品没有主图，我帮您查一下详情",
        ]:
            assert capability_denial_text_hit(t) == "", f"中性/越权文本误命中: {t!r}"
            assert _product_image_denial_hit(t) == "", f"图片域判据误命中: {t!r}"


def _make_state(**overrides):
    state = {
        "messages": [HumanMessage(content="测试消息")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_denial_gate",
        "role": "admin",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


class TestProductImageDenialToolCallGate:
    """迭代3（issue #3940）：拒绝文本与查询工具调用**同回合**时必须触发纠正重答。

    红证（改前）：`execute_skill` 的图片域误宣检查位于 `if not response.tool_calls:`
    分支内 —— flash 常把拒绝文本与 product_detail 等查询调用同一条消息生成
    （PR-026/027 复现 run 34978506935 transcript 实证），守卫从未看到拒绝文本。
    本测试 mock LLM 首回合 = 拒绝文本 + product_detail 调用，断言纠正话术被注入
    第二次调用、且流程继续（interact 确认卡被执行）。
    """
    import asyncio as _asyncio

    def _drive(self, with_capability: bool):
        from app.tools.base import ToolResult
        from app.tools.product_manage import ProductManageTool
        from app.tools.product_detail import ProductDetailTool

        executed: list = []
        injected: list = []

        async def fake_execute(tool, args, ctx, state):
            executed.append(tool.name)
            if tool.name == "interact":
                _data = {"component": "confirm", "title": args.get("title"),
                         "fields": args.get("fields") or [],
                         "confirmValue": "确认设置主图"}
                return (json.dumps({"success": True, "data": _data}),
                        {"success": True, "data": _data})
            return (json.dumps({"success": True, "data": {}}),
                    {"success": True, "data": {}})

        class _Store:
            def __init__(self):
                self._d = {}
            async def load(self, sid):
                return dict(self._d)
            async def commit(self, sid, full):
                self._d.clear(); self._d.update(full or {}); return True
            async def clear(self, sid):
                return True

        store = _Store()
        history = [HumanMessage(content="把遮光窗帘的主图设成这张色卡图")]

        # R1：拒绝文本 + 查询工具调用**同回合**（复现 run 34978506935 transcript 形态）
        r1 = MagicMock(spec=AIMessage)
        r1.content = "我理解您想换主图，但这里得再跟您明确一次：**换主图这个动作我这边做不了**，当前模块只提供查询类能力。"
        r1.tool_calls = [{"name": "product_detail",
                          "args": {"product_id": "prod_eval_blackout"}, "id": "t1"}]
        # R2：被纠正后发确认卡
        r2 = MagicMock(spec=AIMessage)
        r2.content = ""
        r2.tool_calls = [{"name": "interact",
                          "args": {"component": "confirm", "title": "确认设置主图",
                                   "fields": [{"label": "商品", "value": "遮光窗帘"}]},
                          "id": "t2"}]
        r3 = MagicMock(spec=AIMessage)
        r3.content = "好的，已为您发出确认卡片，请点击确认后我立即设置主图。"
        r3.tool_calls = []
        side = [r1, r2, r3]

        with patch("app.memory.session_memory.SessionMemory") as mem_cls, \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: store), \
             patch("app.graph.skills.base_skill.get_breaker") as get_breaker, \
             patch("app.graph.skills.base_skill.get_skill_llm") as get_llm, \
             patch("app.graph.skills.base_skill.create_skill_registry") as create_reg, \
             patch("app.graph.skills.base_skill.set_tool_context"), \
             patch("app.graph.skills.base_skill._execute_tool_safe", fake_execute):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []

            def _get_tool(n):
                if n == "interact":
                    from app.tools.interact import InteractTool
                    return InteractTool()
                if n == "product_detail":
                    return ProductDetailTool()
                if n == "product_manage" and with_capability:
                    return ProductManageTool()
                return None

            registry.get_tool.side_effect = _get_tool
            create_reg.return_value = registry
            breaker = MagicMock()
            breaker.call = lambda fn: fn()
            get_breaker.return_value = breaker
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=side)
            get_llm.return_value = llm
            mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)

            def _capture_injections(fn):
                async def wrapper(*a, **k):
                    r = await fn(*a, **k)
                    for m in (a[0] if a and isinstance(a[0], list) else []):
                        if getattr(m, "content", None) == _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE:
                            injected.append(True)
                    return r
                return wrapper

            # 包装 ainvoke 以便在第二次调用前捕获注入的纠正话术
            _orig = llm.ainvoke
            async def _wrapped(*a, **k):
                await _orig(*a, **k)
                msgs = a[0] if a and isinstance(a[0], list) else []
                if any(getattr(m, "content", None) == _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE
                       for m in msgs):
                    injected.append(True)
            llm.ainvoke = _wrapped
            # 但 side_effect 已绑定 _orig；直接用 await_args 检查
            llm.ainvoke = AsyncMock(side_effect=side)
            get_llm.return_value = llm

            out = self._asyncio.run(execute_skill(
                state=_make_state(messages=history),
                skill_name="product",
                tool_names=["product_detail", "product_manage", "interact"],
                system_prompt="你是米宝（B 端商品助手）。",
            ))
        # 重新取 ainvoke 的调用输入检查纠正话术
        call_inputs = [c.args[0] for c in llm.ainvoke.await_args_list]
        return out, executed, call_inputs

    def test_denial_text_with_tool_call_triggers_correction(self):
        """能力可达（product_manage 带 images）：拒绝文本+查询调用同回合 → 纠正注入。"""
        out, executed, call_inputs = self._drive(with_capability=True)
        # 纠正话术必须出现在某次 LLM 调用的输入里
        assert any(
            any(getattr(m, "content", "") == _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE
                for m in msgs)
            for msgs in call_inputs
        ), "纠正话术未被注入（守卫未触发 text+tool_calls 同回合的拒绝）"
        # 流程继续：interact 确认卡被真实执行
        assert "interact" in executed, f"纠正后流程未推进，executed={executed}"

    def test_no_correction_when_capability_unavailable(self):
        """能力不可达（注册表无 product_manage）：同文本不得触发纠正（事实门）。"""
        out, executed, call_inputs = self._drive(with_capability=False)
        assert not any(
            any(getattr(m, "content", "") == _TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE
                for m in msgs)
            for msgs in call_inputs
        ), "能力不可达时不应注入纠正话术"
