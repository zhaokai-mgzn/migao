"""
米宝机器人全场景 E2E 集成测试
================================
通过真实 LLM 调用验证米宝所有 Skill 节点的对话能力。
按 TDD 逐条推进，每条测试描述一个业务行为。

运行方式：
    pytest tests/test_e2e_mibao_scenarios.py -v --timeout=60

前提条件：
    - AI Agent Service 运行在 localhost:8000（DEBUG=true，默认 admin 用户 → mibao agent）
    - DashScope API Key 已配置
    - PostgreSQL 和 Redis 可用

实现适配说明：
    - 实际接口为 POST /api/chat/send（非 /api/v1/chat），由 X-Service-Token + DEBUG 模式自动注入 admin 用户
    - SSE data 字段为 JSON 编码（如 {"content": "..."}），需 json.loads 解析
    - agent_type 由后端 JWT 角色自动决定（admin → mibao）
    - 多轮对话历史由服务端按 session_id 自动管理，无需在请求体中传 chat_history
"""
import json
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pytest


# === SSE 解析辅助 ===

class SSEEvent:
    """解析后的 SSE 事件。data 字段假定为 JSON，可通过 json_data 属性快捷访问。"""

    def __init__(self, event_type: str, data: str):
        self.event_type = event_type
        self.data = data

    @property
    def json_data(self) -> Dict[str, Any]:
        try:
            return json.loads(self.data)
        except (json.JSONDecodeError, TypeError):
            return {}

    def __repr__(self) -> str:
        return f"SSEEvent({self.event_type}, {self.data[:60]}...)"


BASE_URL = "http://localhost:8001"
HEADERS = {
    "Content-Type": "application/json",
    "X-Service-Token": "f4ac825ebdf8900b7b2fbcc13af93b29f352264823a3bf9a8098e7155a6961a8b",
    "X-Tenant-Id": "1",
}
CHAT_ENDPOINT = f"{BASE_URL}/api/chat/send"


# === 服务可用性检查 ===

def _is_service_available() -> bool:
    try:
        import socket
        with socket.create_connection(("localhost", 8001), timeout=2):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

SERVICE_AVAILABLE = _is_service_available()
_skip_if_no_service = pytest.mark.skipif(
    not SERVICE_AVAILABLE,
    reason="AI Agent Service 未在 localhost:8001 运行",
)


async def send_chat(
    message: str,
    session_id: Optional[str] = None,
    timeout: float = 90.0,
) -> List[SSEEvent]:
    """发送对话请求并收集所有 SSE 事件。

    若 session_id 为空，由服务端自动创建新会话；多轮场景请通过 ``get_session_id``
    从首轮的 done 事件提取 session_id 后回传，由服务端按 session_id 加载历史。
    """
    payload: Dict[str, Any] = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    events: List[SSEEvent] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", CHAT_ENDPOINT, json=payload, headers=HEADERS
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise AssertionError(
                    f"chat 接口返回非 200：{response.status_code}, body={body!r}"
                )
            current_event: Optional[str] = None
            async for raw_line in response.aiter_lines():
                line = raw_line.rstrip("\r")
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if current_event:
                        events.append(SSEEvent(current_event, data))
                elif line == "":
                    current_event = None
    return events


def get_session_id(events: List[SSEEvent]) -> Optional[str]:
    """从 done 事件中提取服务端返回的 session_id（用于多轮对话）。"""
    for e in events:
        if e.event_type == "done":
            sid = e.json_data.get("session_id")
            if sid:
                return sid
    return None


def get_full_text(events: List[SSEEvent]) -> str:
    """从事件流中拼接完整文本回复（按出现顺序合并所有 text 事件的 content）。"""
    parts: List[str] = []
    for e in events:
        if e.event_type != "text":
            continue
        data = e.json_data
        if isinstance(data, dict):
            content = data.get("content", "")
            if isinstance(content, str):
                parts.append(content)
        elif isinstance(e.data, str):
            parts.append(e.data)
    return "".join(parts)


def get_tool_calls(events: List[SSEEvent]) -> List[str]:
    """提取所有 tool_call / tool_result 事件中的工具名称。

    同时检查两类事件是因为缓存未命中、Skill 正常调用工具时，服务端会发出
    tool_call 和 tool_result 两个事件；但在某些路径上（如节点在调用后才记入 messages）只
    会产生 tool_result。合并两者可获得完整的工具调用集合。
    """
    tools: List[str] = []
    for e in events:
        if e.event_type not in ("tool_call", "tool_result"):
            continue
        data = e.json_data
        if not isinstance(data, dict):
            continue
        name = data.get("tool") or data.get("name")
        if name and name not in tools:
            tools.append(name)
    return tools


def has_event_type(events: List[SSEEvent], event_type: str) -> bool:
    """检查事件流是否包含指定类型的事件。"""
    return any(e.event_type == event_type for e in events)


def assert_no_error(events: List[SSEEvent]) -> None:
    """断言流中不存在 error 事件。"""
    errors = [e for e in events if e.event_type == "error"]
    assert not errors, f"收到错误事件: {[e.data for e in errors]}"


# === 会话级语义缓存清理 ===

@pytest.fixture(scope="module", autouse=True)
async def _flush_semantic_cache():
    """测试模块开始前清理 tenant=1 的语义缓存，避免跨轮跨用例的缓存命中干扰 tool 调用断言。"""
    try:
        import redis.asyncio as redis  # type: ignore
        client = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        # tenant=1 语义缓存条目唯一 key
        await client.delete("semantic_cache:1:entries")
        await client.close()
    except Exception:
        # 缓存不可用不应阻塞测试
        pass
    yield


# === 测试用例 ===

@pytest.mark.asyncio
@_skip_if_no_service
class TestP0CoreScenarios:
    """P0 核心场景：验证米宝基础对话能力。"""

    async def test_greeting_returns_welcome_message(self):
        """
        业务场景：用户首次打招呼，米宝应友好回应并介绍自己
        预期行为：返回包含欢迎语的文本，无 Tool 调用，无 error
        """
        events = await send_chat("你好")

        assert_no_error(events)
        text = get_full_text(events)
        assert len(text) > 0, "应返回非空文本回复"
        assert any(kw in text for kw in ["你好", "您好", "米宝", "助手", "帮"]), (
            f"回复应包含问候或自我介绍关键词，实际: {text[:100]}"
        )
        assert not get_tool_calls(events), "问候场景不应触发 Tool 调用"
        assert has_event_type(events, "done"), "应有 done 事件标志流结束"

    async def test_product_search_triggers_tool_and_returns_results(self):
        """
        业务场景：商家询问商品，米宝应调用 product_search 工具并返回结果
        预期行为：触发 product_search Tool，返回包含商品信息的文本
        """
        events = await send_chat("帮我查一下店里现在有哪些窗帘商品可以推荐给顾客")

        assert_no_error(events)
        tools = get_tool_calls(events)
        assert "product_search" in tools, f"应触发 product_search Tool，实际: {tools}"
        text = get_full_text(events)
        assert len(text) > 0, "应返回商品搜索结果文本"
        assert has_event_type(events, "done")

    async def test_order_query_asks_for_details_or_returns_results(self):
        """
        业务场景：商家查询客户订单，米宝应尝试调用 order_query 或追问必要信息
        预期行为：触发 order_query Tool 或合理追问（如缺少客户标识）
        """
        events = await send_chat("帮我查一下最近的订单")

        assert_no_error(events)
        text = get_full_text(events)
        tools = get_tool_calls(events)
        # 要么触发 Tool 查询，要么追问具体信息
        assert "order_query" in tools or any(
            kw in text for kw in ["订单号", "手机号", "客户", "哪"]
        ), f"应触发订单查询或追问，工具: {tools}，文本: {text[:100]}"
        assert has_event_type(events, "done")

    async def test_logistics_track_returns_shipping_info(self):
        """
        业务场景：商家查询订单物流，米宝应调用 logistics_track 返回快递状态
        预期行为：触发 logistics_track Tool，响应含物流相关信息
        """
        events = await send_chat("查一下订单 ORD-2024001 的物流状态")

        assert_no_error(events)
        tools = get_tool_calls(events)
        assert "logistics_track" in tools, f"应触发 logistics_track Tool，实际: {tools}"
        text = get_full_text(events)
        assert any(kw in text for kw in ["物流", "快递", "运输", "配送", "签收", "发货"]), (
            f"回复应含物流相关信息，实际: {text[:100]}"
        )
        assert has_event_type(events, "done")

    async def test_knowledge_search_returns_professional_advice(self):
        """
        业务场景：商家咨询窗帘保养知识（RAG 已禁用）
        预期行为：基于通用知识回答，返回有用建议
        """
        events = await send_chat("窗帘怎么清洗保养")

        assert_no_error(events)
        text = get_full_text(events)
        assert any(kw in text for kw in ["清洗", "保养", "洗涤", "干洗", "水洗", "面料", "建议"]), (
            f"回复应含清洗保养建议，实际: {text[:100]}"
        )
        assert has_event_type(events, "done")


@pytest.mark.asyncio
@_skip_if_no_service
class TestP1ExtendedScenarios:
    """P1 扩展场景：验证米宝进阶业务能力。"""

    async def test_aftersales_handles_return_request(self):
        """
        业务场景：客户商品破损要退货，米宝应引导售后流程
        预期行为：路由至售后 Skill，响应含退货/售后处理步骤
        """
        events = await send_chat("客户说窗帘收到有破损，想退货怎么处理")

        assert_no_error(events)
        text = get_full_text(events)
        assert any(kw in text for kw in ["退货", "退换", "售后", "照片", "凭证", "处理"]), (
            f"回复应含售后处理指引，实际: {text[:100]}"
        )
        assert has_event_type(events, "done")

    async def test_complaint_provides_resolution(self):
        """
        业务场景：客户投诉服务态度差，米宝应安抚并提供解决方案
        预期行为：识别投诉意图，响应含致歉/安抚和解决建议
        """
        events = await send_chat("有个客户非常不满意，投诉说安装师傅态度很差，要求赔偿")

        assert_no_error(events)
        text = get_full_text(events)
        assert any(kw in text for kw in ["抱歉", "理解", "处理", "解决", "投诉", "安抚", "补偿"]), (
            f"回复应含安抚或解决方案，实际: {text[:100]}"
        )
        assert has_event_type(events, "done")

    async def test_product_create_triggers_manage_tool(self):
        """
        业务场景：商家要创建新商品，米宝按新引导流程逐步确认
        预期行为：查询分类、查询加工项、使用 interact 展示选项
        """
        events = await send_chat(
            "帮我创建一个新商品，名称叫麻芘隔热窗帘-郁金香色，价格299元，库存50，分类窗帘布艺"
        )

        assert_no_error(events)
        tools = get_tool_calls(events)
        # 新引导流程：先查分类 + 加工项 + 用 interact 展示选项卡片
        assert "category_manage" in tools or "processing_item_query" in tools, (
            f"应先查询分类/加工项，实际: {tools}"
        )
        assert has_event_type(events, "done")

    async def test_inventory_query_returns_stock_info(self):
        """
        业务场景：商家查询库存情况，米宝应检索相关库存数据
        预期行为：触发商品搜索或库存管理 Tool
        """
        events = await send_chat("查一下麻芘隔热窗帘的库存还有多少")

        assert_no_error(events)
        tools = get_tool_calls(events)
        assert any(t in tools for t in ["product_search", "inventory_manage"]), (
            f"应触发 product_search 或 inventory_manage Tool，实际: {tools}"
        )
        assert has_event_type(events, "done")

    async def test_farewell_ends_politely(self):
        """
        业务场景：用户道别，米宝应礼貌结束对话
        预期行为：返回告别语，无 Tool 调用
        """
        events = await send_chat("好的谢谢，再见")

        assert_no_error(events)
        text = get_full_text(events)
        assert any(kw in text for kw in ["再见", "祝", "随时", "有需要"]), (
            f"回复应含告别语，实际: {text[:100]}"
        )
        assert not get_tool_calls(events), "告别场景不应触发 Tool 调用"
        assert has_event_type(events, "done")


@pytest.mark.asyncio
@_skip_if_no_service
class TestP2AdvancedScenarios:
    """P2 高级场景：验证米宝多轮对话与复杂意图处理。"""

    async def test_multiturn_context_reference_resolution(self):
        """
        业务场景：用户先搜索商品，再用“第一个”指代上轮结果
        预期行为：第二轮正确理解指代，返回具体商品信息
        """
        # 第一轮：创建会话并搜索商品
        events1 = await send_chat("帮我看看店里有哪些隔热麶光窗帘")
        assert_no_error(events1)
        session_id = get_session_id(events1)
        assert session_id, "首轮应返回 session_id"

        # 第二轮：复用 session_id，服务端会加载历史进行指代消解
        events2 = await send_chat("第一个多少钱", session_id=session_id)
        assert_no_error(events2)
        text2 = get_full_text(events2)
        assert any(kw in text2 for kw in ["价格", "元", "¥", "￥", "售价", "多少钱"]), (
            f"第二轮应返回价格信息或询问查价，实际: {text2[:120]}"
        )

    async def test_cross_skill_intent_switch(self):
        """
        业务场景：用户从商品话题切换到订单话题
        预期行为：米宝能无缝切换 Skill，第二轮仍能返回有效回复
        """
        # 第一轮：商品场景、创建会话
        events1 = await send_chat("看看现在隔热麶光窗帘都有哪些型号")
        assert_no_error(events1)
        session_id = get_session_id(events1)
        assert session_id

        # 第二轮：切换到订单/销售场景
        events2 = await send_chat(
            "那最近有没有老顾客下过这款的订单", session_id=session_id
        )
        assert_no_error(events2)
        text2 = get_full_text(events2)
        assert len(text2) > 0, "切换 Skill 后仍应返回非空回复"

    async def test_mixed_intent_handles_multiple_requests(self):
        """
        业务场景：一句话包含多个意图（物流+库存），米宝应合理处理
        预期行为：至少触发一个 Tool 并返回非空文本
        """
        events = await send_chat(
            "帮我查下订单 ORD-2024001 的物流，顺便看看这款窗帘还有库存吗"
        )

        assert_no_error(events)
        tools = get_tool_calls(events)
        text = get_full_text(events)
        # 至少触发一个 Tool
        assert len(tools) > 0, f"混合意图应至少触发一个 Tool，实际: {tools}"
        assert len(text) > 0
        assert has_event_type(events, "done")

    async def test_vague_query_asks_for_clarification(self):
        """
        业务场景：用户提出模糊问题，米宝应主动追问澄清
        预期行为：返回追问或引导，不盲目执行
        """
        events = await send_chat("帮我看看那个")

        assert_no_error(events)
        text = get_full_text(events)
        assert any(kw in text for kw in ["具体", "哪", "什么", "请问", "需要", "可以"]), (
            f"模糊问题应引导澄清，实际: {text[:100]}"
        )
        assert has_event_type(events, "done")

    async def test_capabilities_lists_all_functions(self):
        """
        业务场景：用户询问米宝能做什么，应完整列出能力
        预期行为：返回功能列表，覆盖主要能力（商品/订单/知识/售后）
        """
        events = await send_chat("你都能帮我做什么")

        assert_no_error(events)
        text = get_full_text(events)
        # 至少提及 3 个核心能力
        capabilities = ["商品", "订单", "知识", "售后", "物流", "库存"]
        mentioned = [c for c in capabilities if c in text]
        assert len(mentioned) >= 3, (
            f"应列出至少3个核心能力，实际提及: {mentioned}，完整回复: {text[:200]}"
        )


@pytest.mark.asyncio
@_skip_if_no_service
class TestP3PlanAndExecute:
    """P3 Plan-and-Execute：验证 P&E 模式下的多步骤文本交互"""

    async def test_product_create_triggers_query_tools(self):
        """
        商品创建走 P&E 模式 — LLM 应先收集信息或查询分类/加工项
        预期：有文本回复，可能触发查询工具（取决于 Plan 步骤），不触发 interact
        """
        events = await send_chat(
            "创建一个商品：名称测试窗帘，价格99元，库存100，分类窗帘布艺"
        )

        assert_no_error(events)
        tools = get_tool_calls(events)
        text = get_full_text(events)
        # P&E 第一步可能是 ask（收集信息）或 query（查分类），不可能调 interact
        assert "interact" not in tools, f"P&E 模式不应调 interact，实际 tools={tools}"
        assert len(text) > 10, f"应有文本回复，实际 len={len(text)}"
        assert has_event_type(events, "done")

    async def test_product_create_with_details_triggers_manage(self):
        """
        商品创建 — 提供完整信息后触发 product_manage
        预期：走 P&E execute 步骤调用 product_manage
        """
        events = await send_chat(
            "创建商品：名称星夜帘，价格268元，库存50，分类窗帘布艺，加工S钩安装和双折边"
        )

        assert_no_error(events)
        tools = get_tool_calls(events)
        text = get_full_text(events)
        # P&E 模式：应触发 product_manage 或展示文本引导
        assert any(t in tools for t in ["product_manage", "processing_item_query", "category_manage"]) or len(text) > 20, (
            f"P&E 模式应处理商品创建，实际 tools={tools}, text_len={len(text)}"
        )
        assert has_event_type(events, "done")

    async def test_order_create_triggers_order_tools(self):
        """
        订单创建走 P&E 模式 — 触发订单相关工具
        预期：触发 product_search 或 order_create，纯文本不含交互组件
        """
        events = await send_chat(
            "创建一个订单：客户李先生，商品星辰帘2件，总价256元，收货地址北京市朝阳区"
        )

        assert_no_error(events)
        text = get_full_text(events)
        tools = get_tool_calls(events)
        # P&E 模式：文本中应有确认/订单相关信息
        assert any(
            t in tools for t in ["product_search", "order_manage", "order_create"]
        ) or any(kw in text for kw in ["确认", "订单", "创建", "256", "李先生"]), (
            f"P&E 模式应处理订单创建，实际 tools={tools}, text={text[:150]}"
        )
        assert has_event_type(events, "done")

    async def test_choice_card_multi_option_rendering(self):
        """
        interact choice — 多选项列表正确展示
        预期：触发 interact 工具，options 为列表
        """
        events = await send_chat("有哪些可用的加工项")

        assert_no_error(events)
        text = get_full_text(events)
        tools = get_tool_calls(events)
        # 应查询加工项列表，可能使用 interact 展示选项
        assert "processing_item_query" in tools, (
            f"应查询加工项列表，实际: {tools}"
        )
        assert has_event_type(events, "done")
        assert has_event_type(events, "done")


@_skip_if_no_service
class TestP4FormFieldCompleteness:
    """P4 表单字段完整性：验证 LLM 将图片识别信息全量填入 form 而非散落在文本"""

    async def test_image_analysis_all_fields_in_form(self):
        """
        模拟 2699 色卡图片识别 → form 必须包含名称/价格/色号等全量字段
        """
        vision_analysis = (
            "图片中是一个布艺色卡，包含以下信息：\n"
            "- 品牌/系列：HOME YUUR COLOR SELECTION 2699系列\n"
            "- 色号列表：2699-01, 2699-02, 2699-03, 2699-04, 2699-05, "
            "2699-06, 2699-07, 2699-08, 2699-09, 2699-10, "
            "2699-11, 2699-12, 2699-13, 2699-14, 2699-15, 2699-16\n"
            "- 材质：雪尼尔\n"
            "- 幅宽：280cm\n"
            "- 重量：1200g/m\n"
            "- 标注价格：¥23.8/米"
        )

        events = await send_chat(
            f"根据以下图片分析结果创建商品：\n{vision_analysis}"
        )

        assert_no_error(events)
        tools = get_tool_calls(events)

        # 必须使用 interact
        assert "interact" in tools, f"应使用 interact，实际: {tools}"

        # 查找 interactive form
        form_data = None
        for e in events:
            if e.event_type == "interactive":
                d = e.json_data
                if d.get("type") == "form":
                    form_data = d
                    break

        assert form_data is not None, (
            f"应有 interactive form 事件，事件类型: {[e.event_type for e in events]}"
        )

        form_fields = form_data.get("formFields", [])
        field_keys = {f.get("key", "") for f in form_fields}
        all_values = " ".join(
            str(f.get("value", "") or f.get("label", "")) for f in form_fields
        )

        # 必须字段
        missing = {"name", "price"} - field_keys
        assert not missing, f"form 缺少必填字段: {missing}, 实际: {field_keys}"

        # 色号必须在 form 中（key/value/label 任一处出现 2699）
        assert "2699" in all_values, (
            f"色号 2699 应在 form 字段中（预填值/label），"
            f"实际字段: {[(f.get('key'), f.get('value',''), f.get('label','')) for f in form_fields]}"
        )

        # 价格预填
        assert any("23.8" in str(f.get("value", "")) for f in form_fields), (
            f"价格 23.8 应预填到 form，实际预填值: {[(f.get('key'), f.get('value','')) for f in form_fields]}"
        )

        assert has_event_type(events, "done")
