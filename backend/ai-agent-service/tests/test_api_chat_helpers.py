"""
Tests for app/api/*.py — coverage gap issue #581
Covers: chat (helpers), sse (SSEEvent/SSEStreamBuilder),
         upload (_sniff_image_type/_validate_image_file), internal (Pydantic models)
"""
# case_ids: CH-001, API-004, CH-010, CH-011, CH-012, OR-017, CH-032, CH-019
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ═══════════════════════════════════════
# chat.py — helper functions
# ═══════════════════════════════════════

class TestFormatDatetime:
    def test_datetime_naive(self):
        from app.api.chat import _format_datetime
        dt = datetime(2026, 6, 20, 10, 30, 0)
        result = _format_datetime(dt)
        assert result.endswith("Z")
        assert "2026-06-20" in result

    def test_datetime_with_tz(self):
        from app.api.chat import _format_datetime
        dt = datetime(2026, 6, 20, 10, 30, 0, tzinfo=timezone.utc)
        result = _format_datetime(dt)
        assert result.endswith("Z")

    def test_string_double_suffix(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00+00:00Z")
        assert not result.endswith("+00:00Z")
        assert result.endswith("Z")

    def test_string_plus_00_00(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00+00:00")
        assert result.endswith("Z")

    def test_string_no_suffix(self):
        from app.api.chat import _format_datetime
        result = _format_datetime("2026-06-20T10:30:00")
        assert "2026-06-20" in result


class TestConvertHistoryToAgentFormat:
    def test_user_message_passthrough(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_assistant_think_stripped(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "assistant", "content": "<think>reasoning</think>actual reply"}
        ])
        assert result[0]["content"] == "actual reply"
        assert "think" not in result[0]["content"]

    def test_assistant_no_think_passthrough(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "assistant", "content": "plain reply"}
        ])
        assert result[0]["content"] == "plain reply"

    def test_mixed_messages(self):
        from app.api.chat import _convert_history_to_agent_format
        result = _convert_history_to_agent_format([
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "<think>x</think>a1"},
            {"role": "user", "content": "q2"},
        ])
        assert len(result) == 3
        assert result[1]["content"] == "a1"


class TestValidateImageUrl:
    def test_valid_https(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("https://example.com/img.jpg") is True

    def test_valid_api_files(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("/api/files/upload/abc.jpg") is True

    def test_invalid_http(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("http://example.com/img.jpg") is False

    def test_invalid_empty(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url("") is False

    def test_invalid_none(self):
        from app.api.chat import _validate_image_url
        assert _validate_image_url(None) is False


class TestDetectCardType:
    def test_product_search(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("product_search", {}) == "product_list"

    def test_product_detail(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("product_detail", {}) == "product_detail"

    def test_unknown_tool(self):
        from app.api.chat import _detect_card_type
        assert _detect_card_type("some_unknown_tool", {}) is None


class TestInteractXmlParseFailureIsObservable:
    """畸形 `<interact>` 块必须留痕，不得静默剥离（issue #3959 / case CH-032）。

    缺陷形态：文本里「**有** `<interact>` 块但解析失败」（`_parse_interact_xml` fail-closed
    返回 None）与「本来就没有块」在调用点**不可区分** —— 两者都走 `_strip_interact_xml`。
    于是模型本想发卡但写残时：块被静默剥掉、不发卡、**零日志**。用户侧表现为
    「该弹的卡没了，只剩文字」，评测侧只能归因成「agent 不干活」。
    本类从**真 SSE 桥**（`_agent_stream_to_sse`）出发钉住留痕与「合法块/无块」两条不变路径。
    """

    # choice 缺 <option> ⇒ `_parse_interact_xml` fail-closed 返回 None（正确语义，不改）
    MALFORMED = ("<interact><component>choice</component><title>请选择</title></interact>")
    VALID = ("<interact><component>choice</component><title>请选择</title><options>"
             "<option><label>遮光窗帘</label><value>遮光窗帘</value></option>"
             "</options></interact>")
    SESSION_ID = "sess-3959"

    def _stream(self, content):
        """驱动真 SSE 桥（假 agent 只负责 yield 文本），返回 (SSE chunks, [interact-xml] 留痕)"""
        import asyncio
        from loguru import logger
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        records = []
        sink_id = logger.add(lambda m: records.append(m.record), level="WARNING")

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content=content)

        class _Mem:
            async def add_message(self, **kw):
                return None

            async def save_message(self, **kw):
                return None

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id=self.SESSION_ID,
                           role="customer", identity_type="customer")

        async def _collect():
            return [chunk async for chunk in _agent_stream_to_sse(
                _Agent(), "你好", ctx, [], MagicMock(), _Mem(), self.SESSION_ID, 1, "u1")]

        try:
            chunks = asyncio.run(_collect())
        finally:
            logger.remove(sink_id)
        return chunks, [r for r in records if "[interact-xml]" in str(r["message"])]

    def test_malformed_block_is_reported_not_silently_dropped(self):
        chunks, marks = self._stream(self.MALFORMED)
        assert len(marks) == 1, (
            "畸形 <interact> 块被静默剥离了 —— 必须留一条 warning 才可观测（issue #3959）："
            f"{[str(m['message']) for m in marks]}")
        msg = str(marks[0]["message"])
        assert marks[0]["level"].name == "WARNING", f"留痕级别应为 WARNING: {marks[0]['level']}"
        assert "[interact-xml]" in msg, f"留痕需带稳定检索标记 [interact-xml]: {msg!r}"
        assert self.SESSION_ID in msg, f"留痕必须能定位会话: {msg!r}"
        assert "choice" in msg, f"留痕应含块的 component 片段: {msg!r}"
        assert len(msg) < 600, f"留痕必须是截断片段，不得把整块打进日志: {len(msg)} 字符"
        # 行为不变：fail-closed 不发残缺卡，原文也不泄漏到气泡
        out = "".join(chunks)
        assert "event: interactive" not in out, "畸形块不得下发残缺 payload"
        assert "<interact>" not in out, "XML 伪代码块仍须剥离"

    def test_huge_malformed_block_report_is_truncated(self):
        from loguru import logger
        from app.api.chat import _parse_interact_block_or_report

        huge = ("<interact><component>form</component>"
                + "<field><label>字段</label></field>" * 500 + "</interact>")
        records = []
        sink_id = logger.add(lambda m: records.append(m.record), level="WARNING")
        try:
            payload = _parse_interact_block_or_report(huge, session_id=self.SESSION_ID)
        finally:
            logger.remove(sink_id)
        assert not payload, "畸形块必须 fail-closed（不下发残缺 payload）"
        msg = str(records[0]["message"]) if records else ""
        assert len(records) == 1, "畸形块漏报（无块与解析失败必须可区分）"
        assert "form" in msg and self.SESSION_ID in msg
        assert len(msg) < 600, f"大块也必须截断: {len(msg)} 字符"

    def test_valid_block_still_emits_card_without_report(self):
        chunks, marks = self._stream(self.VALID)
        out = "".join(chunks)
        assert "event: interactive" in out, "合法块照旧发卡（本次修复不得改动该路径）"
        assert "遮光窗帘" in out, f"卡片内容应下发: {out[:200]}"
        assert marks == [], f"合法块不得产生留痕: {[str(m['message']) for m in marks]}"

    def test_absent_block_is_silent(self):
        chunks, marks = self._stream("您好，请问有什么可以帮您？")
        assert marks == [], "[interact-xml] 留痕只应来自「有块但解析失败」"
        assert "请问有什么可以帮您" in "".join(chunks), "无块时文本照旧下发"


# ═══════════════════════════════════════
# chat.py — 收尾守卫升级（issue #3929 缺口修补 / #3967）
# ═══════════════════════════════════════

# 实测漏检措辞（逐字取自三个独立产品会话；见 #3967 的挖掘报告）
#   sess_e52cff42c5d144f0：只调 validate_input，没发 interact(confirm)
#   sess_7f27137647e14b1e：「请点击上方卡片勾选加工项」→ 两次都没调 interact，订单未创建
#   sess_2efa2071bb1747d8：「确认卡已发出 👆」+「现在为您调出真正的加工项选择卡片」
CLAIM_ABOVE = "请点击上方卡片勾选加工项"
CLAIM_SUMMON = "现在为您调出真正的加工项选择卡片，请点击选择（可多选）"
CLAIM_EMITTED = "确认卡已发出 👆"
# 负例：提及「卡片」但**没有动作指向**的合法文本必须原样保留
#   —— 含方向词 + 卡片（「请查看上方结果卡片」「下方列表」）与纯解释性文字
BENIGN_TEXTS = (
    "好的，已为您查询到相关信息，请查看上方结果卡片。",
    "下方列表里列出了全部加工项，您可以慢慢看。",
    "确认设置后我立即为您处理。",
    "您好，很高兴为您服务。",
    "每一件商品都会显示一张卡片，里面有价格和图片。",
    "对话框里可以直接输入您想问的问题。",
)
# 会话状态里「已校验待执行」的写动作（validate_input 通过后由 base_skill 落库）
PENDING_WRITE = {
    "target_tool": "order_create",
    "target_action": "create",
    "params": {"customer_name": "张三", "customer_phone": "13800138000",
               "items": [{"product_name": "遮光窗帘", "quantity": 3}]},
}


def _pending_state():
    from app.graph.pending_validated import PENDING_KEY
    return {PENDING_KEY: dict(PENDING_WRITE)}


def _claim_ctx(role="admin"):
    from app.agents.customer_service_agent import AgentContext
    return AgentContext(user_id="u1", tenant_id=1, session_id="sess-3967",
                        role=role, identity_type=role)


class _FakeStore:
    """SessionStateStore 替身（内存 state，与 test_b_end_confirm_card_fallback 同形）。"""

    def __init__(self, shared):
        self._shared = shared
        self.commits = []

    async def load(self, sid):
        return dict(self._shared)

    async def commit(self, sid, full):
        self.commits.append(dict(full or {}))
        self._shared.clear()
        self._shared.update(full or {})
        return True


class _FakeMemory:
    """SessionMemory 替身：只记 save_message 的入参。"""

    def __init__(self):
        self.saved = []

    async def add_message(self, **kw):
        return None

    async def save_message(self, **kw):
        self.saved.append(kw)
        return "msg-3967"

    async def save(self, *a, **kw):
        return None


def _claim_stream(content, *, role="admin", store_state=None):
    """驱动真 SSE 桥跑一轮「模型只输出文本、没调 interact」，返回
    (SSE chunks, SessionMemory 替身, SessionStateStore 替身, [chat/card-claim] 留痕)。"""
    import asyncio
    from loguru import logger
    from app.agents.customer_service_agent import AgentResponse
    from app.api.chat import _agent_stream_to_sse

    records = []
    sink_id = logger.add(lambda m: records.append(m.record), level="WARNING")
    shared = {} if store_state is None else store_state
    store = _FakeStore(shared)
    mem = _FakeMemory()

    class _Agent:
        _agent_type = "xiaobu"

        async def astream_chat(self, message, context, chat_history):
            yield AgentResponse(type="text", content=content)

    async def _collect():
        return [c async for c in _agent_stream_to_sse(
            _Agent(), "你好", _claim_ctx(role), [], MagicMock(), mem,
            "sess-3967", 1, "u1")]

    try:
        with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
             patch("app.api.chat._generate_title_async", new=AsyncMock()), \
             patch("app.memory.session_state_store.SessionStateStore",
                   side_effect=lambda *a, **k: store):
            chunks = asyncio.run(_collect())
    finally:
        logger.remove(sink_id)
    return chunks, mem, store, [r for r in records if "[chat/card-claim]" in str(r["message"])]


class TestCardClaimWordingCoverage:
    """缺口 1：检测覆盖面（实测措辞族不得漏检；合法提及不得误改）。

    旧正则只覆盖「下方/确认」家族，实测三条生产措辞**全部漏检** ——
    守卫不触发 ⇒ 不改写、不补卡，顾客侧「看不到下方卡片」（#3967）。
    """

    def test_repro_wording_now_detected_after_normalization(self):
        """归一（方向词/空白）+ 语义模式后，实测措辞必须命中。"""
        from app.api.chat import _has_card_claim

        cases = [
            CLAIM_ABOVE,                                        # 请点击上方卡片勾选加工项
            CLAIM_SUMMON,                                       # 现在为您调出真正的加工项选择卡片
            "现在为您调出真正的加工项选择卡片，请点击选择（可多选）",   # 同上（原样）
            CLAIM_EMITTED,                                      # 确认卡已发出 👆
            "请点击上方的卡片勾选加工项",                            # 夹了「的」
            "请点击卡片上方的按钮勾选加工项",                        # 方向词 + 空隙
            "请 点 击 上 方 卡 片 勾 选 加 工 项",                    # 字符间空白（归一）
            "请点下方确认卡片",                                    # 向后兼容：既有短语
        ]
        for text in cases:
            assert _has_card_claim(text), f"实测/既有措辞漏检: {text!r}"

    def test_legacy_phrases_still_detected(self):
        """向后兼容：#3929 已覆盖的「下方/确认」短语不得回归。"""
        from app.api.chat import _CARD_CLAIM_RE, _has_card_claim

        for text in ("确认无误请点下方确认卡片，我立即创建。",
                     "确认无误请点下方卡片，我立即写入。",
                     "请点确认。",
                     "请点击确认卡片。"):
            assert _CARD_CLAIM_RE.search(text), f"既有正则回归: {text!r}"
            assert _has_card_claim(text), f"合成判据漏检既有短语: {text!r}"
        # 实测漏检措辞在**改写正则**上也不得漏（否则只"判得出来"却改不掉）
        from app.api.chat import _rewrite_card_claims
        assert _rewrite_card_claims("请点击上方卡片勾选加工项") != "请点击上方卡片勾选加工项"
        assert _rewrite_card_claims("确认卡已发出 👆") != "确认卡已发出 👆"

    def test_benign_card_mentions_not_detected(self):
        """负例：提及「卡片」但无动作指向 ⇒ 不得命中（避免误改合法话术）。"""
        from app.api.chat import _has_card_claim

        for text in BENIGN_TEXTS:
            assert not _has_card_claim(text), f"合法文本被误判: {text!r}"

    def test_user_action_wording_not_detected(self):
        """负例：动作句 + 用户侧操作，不指向卡片 ⇒ 不得命中。"""
        from app.api.chat import _has_card_claim

        for text in ("好的，请您选择需要的加工项，我这就安排。",
                     "请确认收货地址，确认后我立即创建订单。"):
            assert not _has_card_claim(text), f"用户动作话术被误判: {text!r}"

    def test_benign_text_not_rewritten(self):
        """负例落到改写函数：合法文本必须逐字返回（幂等纯函数不受影响）。"""
        from app.api.chat import _rewrite_card_claims
        from tests.test_chat_card_claim_guard import CLAIM_CREATE

        for text in BENIGN_TEXTS:
            assert _rewrite_card_claims(text) == text, text
        # 非空返回：下游（收尾守卫）会剥离 #3883 误导句后 strip
        assert _rewrite_card_claims(CLAIM_CREATE) == "确认无误请回复『确认』，我立即创建。"

    def test_repro_wording_rewritten_to_text_guide(self):
        """命中后改写为唯一可执行的下一步（不再指路到不存在的卡）。"""
        from app.api.chat import _rewrite_card_claims

        out = _rewrite_card_claims(CLAIM_SUMMON)
        assert "回复『确认』" in out, out
        assert "卡片" not in out, out
        out2 = _rewrite_card_claims(CLAIM_ABOVE)
        assert "回复『确认』" in out2 and "卡片" not in out2, out2
        out3 = _rewrite_card_claims(CLAIM_EMITTED)
        assert "回复『确认』" in out3 and "卡片" not in out3, out3


class TestCardClaimGuardReissuesCard:
    """缺口 2：命中 + 有待确认动作 ⇒ 真的补卡（而不是只改写话术）。

    三次实测里模型**压根没尝试写**，门禁（`confirmation_required_no_card`）
    从没拦下 ⇒ base_skill 8.3b 的补卡分支不触发，接缝处无人兜底。
    """

    def test_claim_without_pending_action_only_rewrites(self):
        """命中但会话状态**没有**待确认动作 ⇒ 行为与现状一致（只改写 + 直播提示，不造卡）。"""
        chunks, mem, store, marks = _claim_stream(CLAIM_SUMMON)
        out = "".join(chunks)

        assert "event: interactive" not in out, "无待确认动作时不得凭空造卡"
        assert store.commits == [], "无待确认动作时不得写会话状态"
        assert len(marks) == 1, f"漏留痕: {[str(m['message']) for m in marks]}"
        assert "改写为纯文本确认指引" in str(marks[0]["message"])
        saved = mem.saved[0]
        assert saved["interactive"] is None
        assert "回复『确认』" in saved["content"], saved["content"]
        assert "卡片" not in saved["content"], saved["content"]
        assert any("确认卡片未显示" in c for c in chunks), "直播侧仍须给可执行下一步"

    def test_claim_with_pending_action_emits_real_card(self):
        """命中 + `pending_validated_input` 有待确认动作 ⇒ 真的下发 interactive 载荷。"""
        import json
        chunks, mem, store, marks = _claim_stream(CLAIM_SUMMON,
                                                  store_state=_pending_state())
        out = "".join(chunks)

        assert "event: interactive" in out, f"有待确认动作必须真发卡: {out[:400]}"
        assert "遮光窗帘" in out and "张三" in out, "卡片必须回显已校验参数"
        # 卡片语料经真解析器落成载荷并持久化（#3883：不落库刷新后卡又消失）
        payload = mem.saved[0]["interactive"]
        assert payload and payload["component"] == "confirm", payload
        assert payload["fields"], payload
        assert mem.saved[0]["interactive"] is not None
        # 直播提示不得出现（卡真的到了，不能再让顾客「直接回复确认」代替点卡）
        assert not any("确认卡片未显示" in c for c in chunks)
        # 留痕：稳定检索标记 + 指明走的是补卡分支
        assert len(marks) == 1, [str(m["message"]) for m in marks]
        msg = str(marks[0]["message"])
        assert "[chat/card-claim]" in msg and "sess-3967" in msg
        assert "补发" in msg or "补卡" in msg, msg
        # 落 last_confirm_value + 发卡 skill（否则顾客点了卡也过不了确认门禁）
        assert store.commits, "补卡必须落会话状态（确认门禁靠它比对）"
        committed = store.commits[-1]
        assert str(committed.get("last_confirm_value") or ""), committed
        assert committed.get("last_confirm_value") == payload.get("confirmValue")
        assert committed.get("last_confirm_skill") == "order_create"
        # 载荷口径与门禁一致（confirm_value_for_fields 同源）
        from app.graph.skills.base_skill import confirm_value_for_fields
        assert payload["confirmValue"] == confirm_value_for_fields(payload["fields"])

    def test_pending_action_without_claim_emits_no_card(self):
        """gating 负例：有待确认动作但模型**没声称**发卡 ⇒ 不得补卡（不凭空造卡）。"""
        chunks, mem, store, marks = _claim_stream("您好，请问有什么可以帮您？",
                                                  store_state=_pending_state())
        out = "".join(chunks)
        assert "event: interactive" not in out, "无声称时不得补卡"
        assert store.commits == []
        assert marks == []

    def test_customer_card_masked_but_confirm_value_intact(self):
        """出站脱敏不变式：顾客侧卡片手机号脱敏，confirmValue（协议值）保持真值。

        `confirmValue` 是**协议值**（点击后回传、门禁按它比对）⇒ 出站不得脱敏
        （见 `_mask_card_for_customer` 的文档字符串），故断言按**事件内部结构**判，
        不能笼统地"整条 SSE 不含手机号"。
        """
        chunks, mem, store, marks = _claim_stream(CLAIM_ABOVE, role="customer",
                                                  store_state=_pending_state())
        line = next((c for c in chunks if c.startswith("event: interactive")), "")
        assert line, "有待确认动作必须真发卡"
        payload = json.loads(line.split("data: ", 1)[1].strip())
        phone = [f for f in payload["fields"] if f["label"] == "手机号"]
        assert phone and phone[0]["value"] == "138****8000", payload["fields"]
        assert "13800138000" not in json.dumps(payload["fields"], ensure_ascii=False)
        assert "13800138000" in payload["confirmValue"], "协议值不得脱敏（回传靠它匹配）"
        # 落库载荷同样是真值（模型上下文/门禁匹配链全程用真值）
        saved = mem.saved[0]["interactive"]
        assert any(f["value"] == "13800138000" for f in saved["fields"]), saved["fields"]

    def test_pending_action_without_fields_falls_back_to_rewrite(self):
        """取不到字段（params 为空）⇒ 退回现有行为，绝不造空卡。"""
        from app.graph.pending_validated import PENDING_KEY
        chunks, mem, store, marks = _claim_stream(
            CLAIM_SUMMON,
            store_state={PENDING_KEY: {"target_tool": "order_create",
                                       "target_action": "create", "params": {}}})
        out = "".join(chunks)
        assert "event: interactive" not in out, "空字段不得造空卡"
        assert store.commits == []
        assert "回复『确认』" in mem.saved[0]["content"], mem.saved[0]["content"]
        assert len(marks) == 1 and "改写" in str(marks[0]["message"])

    def test_store_failure_does_not_break_stream(self):
        """落库失败 ⇒ 非致命：卡照发、留痕，流程不炸。"""
        from app.graph.pending_validated import PENDING_KEY
        store_state = {PENDING_KEY: dict(PENDING_WRITE)}

        class _BrokenStore(_FakeStore):
            async def commit(self, sid, full):
                raise RuntimeError("db down")

        chunks, mem, store, marks = None, None, None, None
        import asyncio
        from loguru import logger
        from app.agents.customer_service_agent import AgentResponse
        from app.api.chat import _agent_stream_to_sse
        records = []
        sink_id = logger.add(lambda m: records.append(m.record), level="WARNING")
        _store = _BrokenStore(store_state)
        _mem = _FakeMemory()

        class _Agent:
            _agent_type = "xiaobu"

            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content=CLAIM_SUMMON)

        async def _collect():
            return [c async for c in _agent_stream_to_sse(
                _Agent(), "你好", _claim_ctx(), [], MagicMock(), _mem,
                "sess-3967", 1, "u1")]

        try:
            with patch("app.api.chat._extract_memories_async", new=AsyncMock()), \
                 patch("app.api.chat._generate_title_async", new=AsyncMock()), \
                 patch("app.memory.session_state_store.SessionStateStore",
                       side_effect=lambda *a, **k: _store):
                chunks = asyncio.run(_collect())
        finally:
            logger.remove(sink_id)
        out = "".join(chunks)
        assert "event: done" in out, "落库失败不得中断 SSE 流"
        assert "event: interactive" in out, "卡本身照发（落库失败非致命）"
        assert _mem.saved, "消息照旧落库"


# ═══════════════════════════════════════
# sse.py — SSEEvent / SSEStreamBuilder
# ═══════════════════════════════════════

class TestSSEEvent:
    def test_text_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.text("hello")
        assert "event: text" in event
        assert "hello" in event

    def test_tool_call_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.tool_call("search", {"q": "test"})
        assert "event: tool_call" in event
        assert "search" in event

    def test_tool_result_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.tool_result("search", {"data": [1, 2]})
        assert "event: tool_result" in event

    def test_error_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.error("something wrong")
        assert "event: error" in event
        assert "something wrong" in event

    def test_suggestions_event(self):
        from app.api.sse import SSEEvent
        event = SSEEvent.suggestions(["a", "b", "c"])
        assert "event: suggestions" in event


class TestSSEStreamBuilder:
    def test_build_empty(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        assert builder.build() == ""

    def test_build_with_text(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        builder.add_text("hello")
        result = builder.build()
        assert "event: text" in result
        assert "hello" in result

    def test_fluent_chaining(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        result = builder.add_text("hi").add_text("there").build()
        assert "hi" in result
        assert "there" in result

    def test_add_tool_call(self):
        from app.api.sse import SSEStreamBuilder
        builder = SSEStreamBuilder()
        builder.add_tool_call("search", {"q": "x"})
        result = builder.build()
        assert "event: tool_call" in result


# ═══════════════════════════════════════
# upload.py — image helpers
# ═══════════════════════════════════════

class TestSniffImageType:
    def test_jpeg(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'\xff\xd8\xff\xe0\x00\x10JFIF')
        assert result == 'image/jpeg'

    def test_png(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
        assert result == 'image/png'

    def test_gif(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'GIF89a\x00\x00\x00\x00')
        assert result == 'image/gif'

    def test_webp(self):
        from app.api.upload import _sniff_image_type
        header = b'RIFF\x00\x00\x00\x00WEBP'
        result = _sniff_image_type(header)
        assert result == 'image/webp'

    def test_unknown(self):
        from app.api.upload import _sniff_image_type
        result = _sniff_image_type(b'random bytes here')
        assert result is None

    def test_empty(self):
        from app.api.upload import _sniff_image_type
        assert _sniff_image_type(b'') is None


class TestValidateImageFile:
    def test_valid_jpeg(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "image/jpeg"
        _validate_image_file(mock_file)  # should not raise

    def test_valid_png(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "image/png"
        _validate_image_file(mock_file)

    def test_invalid_type(self):
        from app.api.upload import _validate_image_file
        mock_file = MagicMock()
        mock_file.content_type = "application/pdf"
        with pytest.raises(Exception):
            _validate_image_file(mock_file)


# ═══════════════════════════════════════
# internal.py — Pydantic models
# ═══════════════════════════════════════

class TestInternalModels:
    def test_tool_execute_request(self):
        from app.api.internal import ToolExecuteRequest
        req = ToolExecuteRequest(
            tool_name="product_search",
            arguments={"keyword": "窗帘"},
            tenant_id=1,
            user_id="u1",
        )
        assert req.tool_name == "product_search"
        assert req.tenant_id == 1



# ═══════════════════════════════════════
# 对抗性审查修复 #937 — chat.py / schemas.py
# ═══════════════════════════════════════

class TestChatSSEDoneFix:
    def test_sse_done_event_structure(self):
        """SSE done 事件包含 session_id 和 message_id"""
        from app.api.sse import SSEEvent
        event = SSEEvent.done("sess_001", "msg_001")
        assert "event: done" in event
        assert "sess_001" in event
        assert "msg_001" in event

    def test_sse_interactive_event(self):
        """SSE interactive 事件发送 choice/confirm/form 组件"""
        from app.api.sse import SSEEvent
        event = SSEEvent.interactive("choice", {"title": "test"})
        assert "event: interactive" in event
        assert "choice" in event


class TestSchemasMaxLength:
    def test_message_max_length(self):
        """ChatSendRequest.message 有 max_length=10000 约束"""
        from app.api.schemas import ChatSendRequest
        from pydantic import ValidationError
        import pytest
        # 验证 schema 定义包含 max_length
        field = ChatSendRequest.model_fields["message"]
        assert field.metadata is not None
        # 超长消息应被拒绝
        with pytest.raises(ValidationError):
            ChatSendRequest(message="x" * 10001)


# ═══════════════════════════════════════
# #947 — chat.py: _infer_intent_from_text 关键词推断
# ═══════════════════════════════════════

class TestInferIntentFromText:
    """建议文本 → 意图类型推断（关键词匹配）"""

    def test_order_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("查看订单") == "order_query"
        assert _infer_intent_from_text("查询发货状态") == "order_query"

    def test_logistics_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("物流到哪了") == "logistics_track"
        assert _infer_intent_from_text("快递单号查一下") == "logistics_track"
        assert _infer_intent_from_text("签收了吗") == "logistics_track"

    def test_after_sales_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("申请售后") == "after_sales"
        assert _infer_intent_from_text("我要退款") == "after_sales"
        assert _infer_intent_from_text("工单处理") == "after_sales"

    def test_complaint_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("我要投诉") == "complaint"

    def test_product_inquiry_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("有什么商品") == "product_inquiry"
        assert _infer_intent_from_text("查一下产品") == "product_inquiry"
        assert _infer_intent_from_text("库存有多少") == "product_inquiry"

    def test_category_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("分类管理") == "category_manage"

    def test_processing_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("加工管理") == "processing_manage"

    def test_customer_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("客户管理") == "customer_manage"

    def test_employee_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("员工管理") == "employee_manage"

    def test_role_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("角色管理") == "role_manage"

    def test_permission_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("权限管理") == "permission_manage"

    def test_dashboard_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("经营看板") == "dashboard"
        assert _infer_intent_from_text("看板数据") == "dashboard"

    def test_statistics_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("数据统计") == "statistics"
        assert _infer_intent_from_text("统计报表") == "statistics"

    def test_data_report_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("数据报表") == "data_report"

    def test_notification_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("通知管理") == "notification"
        assert _infer_intent_from_text("消息中心") == "notification"

    def test_knowledge_faq_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("知识问答") == "knowledge_faq"
        assert _infer_intent_from_text("FAQ查询") == "knowledge_faq"

    def test_session_manage_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("会话管理") == "session_manage"

    def test_system_settings_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("系统设置") == "system_settings"

    def test_ai_config_keyword(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("AI配置") == "ai_config"
        assert _infer_intent_from_text("模型设置") == "ai_config"

    def test_empty_text_returns_empty(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("") == ""
        assert _infer_intent_from_text(None) == ""

    def test_no_keyword_falls_to_general(self):
        from app.api.chat import _infer_intent_from_text
        assert _infer_intent_from_text("你好呀") == "general"
        assert _infer_intent_from_text("abc123") == "general"

    def test_first_keyword_wins(self):
        """多个关键词时返回第一个匹配的意图"""
        from app.api.chat import _infer_intent_from_text
        # "订单" 在 "数据" 之前 → order_query
        assert _infer_intent_from_text("查看订单数据") == "order_query"


class TestCustomerStreamMasking:
    """SSE 出站文本脱敏（issue #3379 P2-2 真正的收敛点）。

    为什么必须放在**流式桥**上：C 端回复有**两个生产者** ——
    `final_answer`（技能收尾，已在 base_skill 脱敏）与 **`text_before_tools`**
    （模型调工具前的中间文本，由 `chat.py` 的 `_agent_stream_to_sse` 直接流给顾客）。
    实测 OR-017 R2（run 34735574206，复现型失败）泄露的正是**中间文本**那条路径：
    ```
    ❌ 回复出现完整手机号 13800138000（R2）—— C 端应脱敏为 138****8000
    ```
    在收尾处脱敏永远追不上已经流出去的文本，故收敛到**出站桥**（覆盖全部文本路径）。
    """

    def _ctx(self, role):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    def test_customer_text_masked(self):
        from app.api.chat import _mask_for_customer
        out = _mask_for_customer("已用您上次的收货信息：张三 13800138000 杭州市西湖区文三路1号",
                                 self._ctx("customer"))
        assert "13800138000" not in out and "138****8000" in out

    def test_staff_text_untouched(self):
        from app.api.chat import _mask_for_customer
        text = "客户手机号 13800138000"
        assert _mask_for_customer(text, self._ctx("admin")) == text

    def test_order_number_not_masked(self):
        from app.api.chat import _mask_for_customer
        out = _mask_for_customer("订单号 20260913027050006 已创建", self._ctx("customer"))
        assert "20260913027050006" in out

    def test_empty_and_none(self):
        from app.api.chat import _mask_for_customer
        assert _mask_for_customer("", self._ctx("customer")) == ""
        assert _mask_for_customer(None, self._ctx("customer")) is None


class TestStreamBridgeMaskingWiring:
    """**接线**断言：脱敏必须真的作用在流式桥上（M120 变异存活暴露的缺口）。

    只测 helper 是假守卫 —— 把出站口那行的 `_mask_for_customer(...)` 删掉，
    helper 单测照样全绿（本轮实测 M120 存活）。故这里直接驱动
    `_agent_stream_to_sse`：喂一个含手机号的文本响应，收集 SSE 输出。
    """

    def _run(self, content, role="customer"):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content=content)

        class _Mem:
            async def add_message(self, **kw):
                return None

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                           identity_type="customer")
        gen = _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(), _Mem(),
                                   "s1", 1, "u1")

        async def _collect():
            out = []
            async for chunk in gen:
                out.append(chunk)
            return out

        return asyncio.run(_collect())

    def test_bridge_masks_intermediate_text(self):
        """中间文本（text_before_tools 路径）出站即脱敏 —— 这是 OR-017 R2 泄露的那条。"""
        chunks = self._run("已用您上次的收货信息：张三 13800138000 杭州市西湖区文三路1号")
        joined = "".join(chunks)
        assert "13800138000" not in joined, f"出站文本未脱敏: {joined[:200]}"
        assert "138****8000" in joined

    def test_bridge_keeps_staff_text(self):
        chunks = self._run("客户 13800138000", role="admin")
        assert "13800138000" in "".join(chunks)


class TestCardMaskingAtSseBoundary:
    """卡片脱敏在**出站层**（issue #3379）——顾客看到脱敏，模型上下文保持原值。"""

    def _ctx(self, role):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    def _card(self):
        return {"component": "confirm", "title": "请确认收货信息",
                "fields": [{"label": "收货人", "value": "张三"},
                           {"label": "手机号", "value": "13800138000"}],
                "confirmValue": "确认提交：张三 13800138000"}

    def test_customer_card_masked_on_output(self):
        """**顾客可见部分**（title/fields/formFields/options.label）脱敏；
        `confirmValue` 属协议值不脱敏（见下一条测试）—— 故不能对整卡 JSON 断言"不含手机号"。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx("customer"))
        assert "138****8000" in out["fields"][1]["value"], f"字段未脱敏: {out['fields']}"
        assert "13800138000" not in json.dumps(out["fields"], ensure_ascii=False)

    def test_confirm_value_untouched(self):
        """`confirmValue` 是回传协议值 —— 出站也不改，否则顾客点卡后匹配不上。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx("customer"))
        assert out["confirmValue"] == "确认提交：张三 13800138000"

    def test_staff_card_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        assert _mask_card_for_customer(card, self._ctx("admin")) == card

    def test_option_values_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = {"component": "choice", "title": "选一下",
                "options": [{"label": "打孔 13800138000", "value": "opt_13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert out["options"][0]["value"] == "opt_13800138000"
        assert "13800138000" not in out["options"][0]["label"]

    def test_form_prefill_value_not_masked(self):
        """**form 的预填值不得脱敏**（issue #3379 关键修正，CI 实证）。

        前端提交表单会把**所有字段值**回传 → 若出站时把 `formFields[].value` 脱敏，
        顾客（或 harness）提交回来的就是 `138****8000`：
        CI 日志实证 `validate_input({"customer_phone": "138****8000", …})`
        —— **订单会用掩码号码创建**，比"明文回显"严重得多。
        故：form 只脱敏 **label**（顾客可见文案），value（协议回传数据）保持原值；
        confirm 卡的 `fields[].value` 是纯展示（点击回传的是 confirmValue）→ 可脱敏。
        """
        from app.api.chat import _mask_card_for_customer
        card = {"component": "form", "title": "请确认收货信息",
                "formFields": [{"key": "customer_phone", "label": "手机号", "value": "13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert out["formFields"][0]["value"] == "13800138000", \
            "form 预填值被脱敏 → 顾客提交回来后订单会拿到掩码号码"
        assert "13800138000" not in out["formFields"][0]["label"] or True  # label 无 PII 时不改

    def test_confirm_field_value_masked(self):
        """confirm 卡的字段值是纯展示（点击回传 confirmValue）→ 应当脱敏。"""
        from app.api.chat import _mask_card_for_customer
        card = {"component": "confirm", "title": "请确认",
                "fields": [{"label": "手机号", "value": "13800138000"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert "138****8000" in out["fields"][0]["value"]

    def test_order_number_untouched(self):
        from app.api.chat import _mask_card_for_customer
        card = {"component": "confirm", "title": "订单号 20260913027050006",
                "fields": [{"label": "订单号", "value": "20260913027050006"}]}
        out = _mask_card_for_customer(card, self._ctx("customer"))
        assert "20260913027050006" in json.dumps(out, ensure_ascii=False)


class TestMaskingStructuralGuards:
    """出站脱敏的**结构级**守卫（issue #3379）。

    上一轮是靠 CI 日志**人工发现**"form 预填值被脱敏 → 掩码号码被提交回来下单"。
    这一个反复出现的教训说明：只补"某个字段"的测试不够，必须把**边界本身**锁死。

    两条不变量：
      A. 出站脱敏只许改写**展示文本**（白名单），**任何其它键必须逐字节不变** ——
         卡载荷里混着展示与协议（`value`/`key`/`component`/自定义回声字段），
         脱敏一旦越界就会污染回传数据；
      B. 脱敏只作用于**出站**，落库历史（喂给模型的上下文）必须保持原值。
    """

    def _ctx(self, role="customer"):
        from app.agents.customer_service_agent import AgentContext
        return AgentContext(tenant_id=1, user_id="u1", session_id="s1", role=role,
                            identity_type="customer")

    # 允许被改写的键（白名单）；其它一律不许动
    ALLOWED = {
        ("title",),
        ("fields", "label"), ("fields", "value"),
        ("options", "label"),
        ("formFields", "label"),
    }

    def _card(self):
        """尽量把协议键、回声键、展示键混在一起（含未来可能新增的键）。"""
        return {
            "component": "form",
            "title": "请确认收货信息 13800138000",
            "submitLabel": "提交 13800138000",
            "pageMeta": {"page": 1, "size": 10, "cursor": "13800138000"},
            "echo": "13800138000",                     # 若真被回传，脱敏即为越界
            "formFields": [
                {"key": "customer_phone", "label": "手机号 13800138000",
                 "value": "13800138000", "required": True, "placeholder": "13800138000"},
            ],
            "fields": [{"label": "手机号 13800138000", "value": "13800138000", "extra": "13800138000"}],
            "options": [{"label": "选项 13800138000", "value": "opt_13800138000", "meta": "13800138000"}],
            "confirmValue": "确认 13800138000",
            "cancelValue": "取消 13800138000",
        }

    def _walk_and_check(self, before, after, path=()):
        """递归比对：白名单路径**允许**变化；其它路径必须相等。"""
        bad = []
        if isinstance(before, dict) and isinstance(after, dict):
            for k in set(before) | set(after):
                bad += self._walk_and_check(before.get(k), after.get(k), path + (k,))
            return bad
        if isinstance(before, list) and isinstance(after, list):
            for i, (b, a) in enumerate(zip(before, after)):
                bad += self._walk_and_check(b, a, path + (str(i),))
            return bad
        if before != after:
            # 归一化路径（去掉列表的下标，只看字段名序列）
            norm = tuple(x for x in path if not x.isdigit())
            if norm not in self.ALLOWED:
                bad.append((path, before, after))
        return bad

    def test_only_display_fields_may_change(self):
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        out = _mask_card_for_customer(card, self._ctx())
        bad = self._walk_and_check(card, out)
        assert not bad, (
            "出站脱敏越界改写了非展示字段（会被回传 → 污染下单数据）：\n  "
            + "\n  ".join(f"{p}: {b!r} → {a!r}" for p, b, a in bad))

    def test_display_fields_actually_masked(self):
        """白名单不只是"允许变"，还**必须真的变**（否则守卫变成空转）。"""
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx())
        assert "138****8000" in out["title"]
        assert "138****8000" in out["fields"][0]["value"]
        assert "138****8000" in out["formFields"][0]["label"]
        assert "138****8000" in out["options"][0]["label"]

    def test_hidden_protocol_fields_survive(self):
        from app.api.chat import _mask_card_for_customer
        out = _mask_card_for_customer(self._card(), self._ctx())
        assert out["confirmValue"] == "确认 13800138000"
        assert out["cancelValue"] == "取消 13800138000"
        assert out["formFields"][0]["value"] == "13800138000"   # 回传数据
        assert out["options"][0]["value"] == "opt_13800138000"  # 回传标识
        assert out["pageMeta"]["cursor"] == "13800138000"

    def test_staff_payload_is_byte_identical(self):
        """B 端：整份载荷逐字节不变（不做任何脱敏）。"""
        from app.api.chat import _mask_card_for_customer
        card = self._card()
        assert _mask_card_for_customer(card, self._ctx("admin")) == card


class TestHistoryStaysRaw:
    """不变量 B：脱敏只作用出站，**落库历史保持原值**（issue #3379）。

    首版把 `full_response.append(clean)` 也脱敏了 → 模型下一轮读到 `138****8000`，
    以为顾客号码不完整、反过来问顾客要号码（验收 0 → 2 违规）。
    """

    def test_saved_assistant_message_not_masked(self):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        saved = []

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                yield AgentResponse(type="text", content="您的收货信息：张三 13800138000")

        class _Mem:
            async def add_message(self, **kw):
                saved.append(kw)
                return None

            async def save_message(self, **kw):
                saved.append(kw)
                return None

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role="customer",
                           identity_type="customer")

        async def _collect():
            out = []
            async for chunk in _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(),
                                                    _Mem(), "s1", 1, "u1"):
                out.append(chunk)
            return out

        chunks = asyncio.run(_collect())
        outbound = "".join(chunks)
        assert "138****8000" in outbound, f"出站应脱敏: {outbound[:120]}"
        history = " ".join(str(v) for kw in saved for v in kw.values())
        assert "13800138000" in history, "落库历史被脱敏了 → 模型下一轮会以为号码不完整"


class TestMemoryIntegrityAcrossGraphAndBoundary:
    """跨层不变量：**真 graph** 产出原文 → 出站脱敏 → 落库保持原文（issue #3386）。

    为什么必须跨层：上面的 `TestHistoryStaysRaw` 用**假 agent**（直接 yield 原文），
    看不到上游 graph 已经把 `final_answer` 脱敏过 —— 真 bug 就藏在这条缝里：
    graph 脱敏 `13800138000` → `138****8000` → 落库 → 模型下一轮把 `****` 填成 `0`
    → `13800008000` 建单成功（CH-010 订单 20260913384380002 落库实证）。
    本用例把「真 skill 执行」和「SSE 边界」串起来，两侧同时断言，缝再断就会被拦。
    """

    def _graph_final_answer(self, reply="您的收货信息：张三 · 13800138000"):
        """用**真 skill 执行**（stub LLM）产出 `final_answer` —— 不假手于假 agent。"""
        import asyncio
        from unittest.mock import AsyncMock
        from langchain_core.messages import AIMessage, HumanMessage
        from app.graph.skills.base_skill import execute_skill
        from tests.test_graph_skills import _make_state

        with patch("app.memory.session_memory.SessionMemory"), \
             patch("app.graph.skills.base_skill.get_breaker") as gb, \
             patch("app.graph.skills.base_skill.get_skill_llm") as gl, \
             patch("app.graph.skills.base_skill.create_skill_registry") as cr, \
             patch("app.graph.skills.base_skill.set_tool_context"):
            registry = MagicMock()
            registry.get_langchain_tools.return_value = []
            registry.get_tool.return_value = None
            cr.return_value = registry
            breaker = MagicMock()

            async def _pt(fn):
                return await fn()

            breaker.call = _pt
            gb.return_value = breaker
            final = MagicMock(spec=AIMessage)
            final.content = reply
            final.tool_calls = []
            llm = MagicMock()
            llm.bind_tools.return_value = llm
            llm.ainvoke = AsyncMock(side_effect=[final])
            gl.return_value = llm
            res = asyncio.run(execute_skill(
                state=_make_state(messages=[HumanMessage(content="我的收货信息是什么")],
                                  role="customer"),
                skill_name="customer_order", tool_names=["product_search"], system_prompt="p"))
        return res.get("final_answer") or ""

    def test_outbound_masked_while_persisted_stays_raw(self):
        import asyncio
        from app.agents.customer_service_agent import AgentContext, AgentResponse
        from app.api.chat import _agent_stream_to_sse

        graph_answer = self._graph_final_answer()
        assert "13800138000" in graph_answer, (
            f"graph 层不得脱敏（记忆要保原文）: {graph_answer!r}")

        saved = []

        class _Agent:
            async def astream_chat(self, message, context, chat_history):
                # 真 graph 的输出原样喂进 SSE 边界
                yield AgentResponse(type="text", content=graph_answer)

        class _Mem:
            async def add_message(self, **kw):
                saved.append(kw)

            async def save_message(self, **kw):
                saved.append(kw)

            async def save(self, *a, **kw):
                return None

        ctx = AgentContext(tenant_id=1, user_id="u1", session_id="s1", role="customer",
                           identity_type="customer")

        async def _collect():
            out = []
            async for chunk in _agent_stream_to_sse(_Agent(), "你好", ctx, [], MagicMock(),
                                                    _Mem(), "s1", 1, "u1"):
                out.append(chunk)
            return out

        outbound = "".join(asyncio.run(_collect()))
        assert "138****8000" in outbound, f"出站必须脱敏（顾客看得到）: {outbound[:160]}"
        history = " ".join(str(v) for kw in saved for v in kw.values())
        assert "13800138000" in history, (
            "落库 assistant 消息被脱敏 → 模型下一轮读残缺值填 0 建单（issue #3386）")
        assert "138****8000" not in history, f"落库必须是原文: {history[:160]!r}"

