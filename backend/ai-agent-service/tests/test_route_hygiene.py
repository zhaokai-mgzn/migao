"""出站文本的**内部路由清洗**（issue #7236，2026-10-18 用户实测）。

故障现场（黄金策 B 端，session `sess_742201cbf83f4f58`）：assistant 正文逐字含
「发货操作在后台「订单列表」页(/orders)对应订单上点「发货」即可」—— 内部前端路由被当成
展示文案上屏，商家看不懂。两层治：
  ① 源头：工具 description / references 提示词只写中文页面名（不在本文件射程）；
  ② 出站兜底：`strip_internal_routes` 纯函数 + **接在落库/SSE/历史回放之前**（本文件射程）。

只测纯函数是假守卫 —— 把 `app/api/chat.py` 的接线摘掉，纯函数测试照样全绿。故本文件
的接线类**直接驱动真桥**（`_agent_stream_to_sse` / `get_history`），并留一条结构级断言
把「所有文本下发都走收口」这件事自身钉住。

红证（可复算）：注释掉 `app/api/chat.py` 的 `_sanitize_outbound_text` 三个调用点与落库前
那一行 `strip_internal_routes(...)` ⇒ TestOutboundWiring / TestHistoryReplayWiring /
TestWiringIsStructural 全红。
"""
# case_ids: CH-048

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.route_hygiene import strip_internal_routes

# 生产实证泄漏句（issue #7236 原文，逐字保留）
LEAKED = "发货需要在后台「订单列表」页(/orders)找到该订单，再点「发货」；我这边不能代办发货。"
CLEANED = "发货需要在后台「订单列表」页找到该订单，再点「发货」；我这边不能代办发货。"


# ═══════════════════════════════════════════════════════════════════
# 一、纯函数判据
# ═══════════════════════════════════════════════════════════════════

class TestStripInternalRoutes:
    def test_issue_verbatim_reply_is_cleaned(self):
        """生产实证句：删掉 `(/orders)` 整段，中文之间不留空格。"""
        assert strip_internal_routes(LEAKED) == CLEANED
        assert "/orders" not in strip_internal_routes(LEAKED)

    @pytest.mark.parametrize("raw,expected", [
        ("请在订单列表(/orders)操作", "请在订单列表操作"),
        ("请在订单列表（/orders）操作", "请在订单列表操作"),      # 全角括号
        ("请在订单列表( /orders )操作", "请在订单列表操作"),      # 括号内空白
        ("请在订单列表(  /orders  )操作", "请在订单列表操作"),    # 多空白
        ("页面(/products/new)操作", "页面操作"),                  # 多段路径整段删
        ("(/orders)", ""),                                        # 整段只有路由
        ("页(/orders)", "页"),
        ("(/orders)页", "页"),
    ])
    def test_paren_forms_removed(self, raw, expected):
        assert strip_internal_routes(raw) == expected

    def test_chinese_junction_drops_spaces(self):
        """删点两侧都是中文 ⇒ 直接相连（中文之间不留空格）。"""
        assert strip_internal_routes("页 (/orders)找到") == "页找到"
        assert strip_internal_routes("页(/orders) 找到") == "页找到"
        assert strip_internal_routes("）。 (/orders) 见") == "）。见"

    def test_english_junction_keeps_single_space(self):
        """删点两侧是英文/中英混排 ⇒ 保留**恰好 1 个**空格（不粘连英文单词）。"""
        assert strip_internal_routes("open page(/orders)now") == "open page now"
        assert strip_internal_routes("open page  (/orders)  now") == "open page now"
        assert strip_internal_routes("页面(/orders)open") == "页面 open"

    def test_markdown_link_keeps_label_only(self):
        """内部路由不得变成可点链接：`[订单列表](/orders)` ⇒ `订单列表`。"""
        assert strip_internal_routes("见[订单列表](/orders)页") == "见订单列表页"
        assert strip_internal_routes("[商品管理](/products)") == "商品管理"
        assert strip_internal_routes("请到[订单列表]( /orders )新建") == "请到订单列表新建"

    def test_negative_controls_untouched(self):
        """负控逐条不许动（代码/URL/业务斜杠不是「展示文案里的内部路由」）。"""
        untouched = [
            "¥29/米，按米计价",
            "定高买宽/定宽买高两种计价方式",
            "参见 http://example.com/a/b 与 https://example.com/a/b?x=1",
            "```\n内部路由 (/orders) 与 [订单列表](/orders) 都在代码块里\n```",
            "行内写 `/orders` 是内部路由（说代码，不是展示文案）",
            "[官网](https://example.com/a/b) 不是内部路由链接",
            "订单号 ORD-202610180001 与 29/米",
        ]
        for text in untouched:
            assert strip_internal_routes(text) == text, f"负控被改动: {text!r}"

    def test_protected_fence_does_not_break_outer_cleaning(self):
        """代码块两侧的展示文案照清，代码块内部一个字不动。"""
        raw = "后台(/orders)操作：\n```\ncurl /products\n```\n完成。"
        out = strip_internal_routes(raw)
        assert "后台操作" in out
        assert "```\ncurl /products\n```" in out

    def test_idempotent(self):
        """幂等：对已清洗文本再跑一次结果逐字不变。"""
        samples = [LEAKED, "页 (/orders)找到", "见[订单列表](/orders)页",
                   "open page  (/orders)  now", "```\n(/orders)\n```", "¥29/米"]
        for raw in samples:
            once = strip_internal_routes(raw)
            assert strip_internal_routes(once) == once, f"非幂等: {raw!r} -> {once!r}"

    def test_none_and_empty(self):
        assert strip_internal_routes("") == ""
        assert strip_internal_routes(None) is None


# ═══════════════════════════════════════════════════════════════════
# 二、接线判据：真驱动 SSE 桥（双端都要干净）
# ═══════════════════════════════════════════════════════════════════

class _StreamAgent:
    def __init__(self, content):
        self.content = content

    async def astream_chat(self, message, context, chat_history):
        from app.agents.customer_service_agent import AgentResponse
        yield AgentResponse(type="text", content=self.content)


class _StreamMemory:
    def __init__(self):
        self.saved = []

    async def save_message(self, **kwargs):
        self.saved.append(kwargs)
        return "msg_1"

    async def add_message(self, **kwargs):
        self.saved.append(kwargs)
        return "msg_1"

    async def save(self, *args, **kwargs):
        return None


def _drive_stream(content, role):
    """驱动真 `_agent_stream_to_sse`，返回 (SSE 全文, 落库 kwargs 列表)。"""
    from app.agents.customer_service_agent import AgentContext
    from app.api.chat import _agent_stream_to_sse

    memory = _StreamMemory()
    ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                       identity_type="customer")

    async def _collect():
        return [chunk async for chunk in _agent_stream_to_sse(
            _StreamAgent(content), "你好", ctx, [], MagicMock(), memory, "s1", 1, "u1")]

    with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
         patch("app.api.chat._generate_title_async", new=AsyncMock()):
        chunks = asyncio.run(_collect())
    return "".join(chunks), memory.saved


class TestOutboundWiring:
    def test_b_end_sse_text_has_no_internal_route(self):
        """B 端（商家）SSE 下发文本不得含 `(/orders)`（issue #7236 的现场）。"""
        outbound, _ = _drive_stream(LEAKED, role="admin")
        assert "/orders" not in outbound, f"B 端出站仍含内部路由: {outbound[:240]}"
        assert "订单列表」页找到" in outbound

    def test_b_end_saved_assistant_message_is_cleaned(self):
        """落库在**下发之前**就清洗 ⇒ 历史回放（读库）不再出现路由。"""
        _, saved = _drive_stream(LEAKED, role="admin")
        assistant = [kw for kw in saved if kw.get("role") == "assistant"]
        assert assistant, "assistant 消息没落库（判据会空跑）"
        content = assistant[-1]["content"]
        assert content == CLEANED, f"落库文本未清洗: {content!r}"

    def test_c_end_sse_text_has_no_internal_route(self):
        """C 端顾客同样不该看到内部路由（与脱敏同收口，不改变脱敏语义）。"""
        outbound, saved = _drive_stream(LEAKED, role="customer")
        assert "/orders" not in outbound
        assert any(kw.get("role") == "assistant" and kw["content"] == CLEANED
                   for kw in saved)


# ═══════════════════════════════════════════════════════════════════
# 三、接线判据：历史回放（旧行已在库，读侧也要干净）
# ═══════════════════════════════════════════════════════════════════

def _user(tenant_id=1, user_id="user_1", role="admin"):
    from app.utils.auth import UserIdentity
    return UserIdentity(user_id=user_id, tenant_id=tenant_id,
                        identity_type="wechat_mini", role=role)


def _session(tenant_id=1):
    return {"id": "sess_1", "tenant_id": tenant_id, "customer_id": "user_1",
            "title": "测试会话", "status": "active",
            "created_at": "2026-06-20T10:00:00Z",
            "updated_at": "2026-06-20T10:00:00Z"}


class TestHistoryReplayWiring:
    @patch("app.api.chat.SessionMemory")
    @pytest.mark.asyncio
    async def test_legacy_row_route_stripped_on_read(self, MockSM):
        """库里已含路由的旧行（如 sess_742201cbf83f4f58）回放时也不得上屏。"""
        from app.api.chat import get_history

        row = {"id": "m1", "session_id": "sess_1", "role": "assistant",
               "content": LEAKED, "content_type": "text",
               "created_at": "2026-06-20T10:00:00Z", "metadata": None}
        memory = AsyncMock()
        memory.get_session = AsyncMock(return_value=_session())
        memory.get_history = AsyncMock(return_value=[row])
        MockSM.return_value = memory

        result = await get_history("sess_1", current_user=_user())
        content = result["data"]["messages"][0]["content"]
        assert "/orders" not in content, f"历史回放仍含内部路由: {content!r}"
        assert content == CLEANED


# ═══════════════════════════════════════════════════════════════════
# 四、结构级守卫：文本下发/落库路径必须走收口
# ═══════════════════════════════════════════════════════════════════

class TestWiringIsStructural:
    def test_text_emission_and_persist_go_through_sanitizer(self):
        """摘掉接线即红：SSE 文本不得再直连 `_mask_for_customer`，落库前必须清一遍。"""
        import inspect
        import app.api.chat as chat

        src = inspect.getsource(chat)
        assert "def _sanitize_outbound_text(" in src, "chat.py 未定义出站收口函数"
        assert "SSEEvent.text(_mask_for_customer(" not in src, (
            "仍有 SSE 文本绕过收口（直连脱敏层）")
        assert '"content": _sanitize_outbound_text(' in src, (
            "历史回放未走收口")
        assert "assistant_content = strip_internal_routes(assistant_content)" in src, (
            "落库前未清洗（历史回放会带出路由）")
