# case_ids: MC-269
"""`app/api/chat.py` 切片 characterization（issue #8725 第三档）。

## 这份判据回答什么

切片（把聊天入口里的**纯装配/纯整形**函数整块搬到同包单元）是**搬运**，不是重写 ——
但"搬运不改行为"这句话本身没有判别力：挪一个闭包、换一次 import 的求值时机、
改一处默认参数，都能让点状断言（`test_chat.py` / `test_api_chat_helpers.py` 那一族）
**全绿通过**，而某个键名、某条日志、某个 fail-open 分支已经悄悄变了。

所以本文件冻的是**同一批输入 ⇒ 输出逐字节相同**：

| 层 | 抓什么 |
|---|---|
| `outbound` | 卡型判定 / 发卡门槛 / 订单卡归一 / 客户面脱敏 / 卡片脱敏 / 卡片声称判定与改写 |
| `interact` | `<interact>` XML → 交互载荷（choice / confirm / form / 残块）、剥离、商品引用过滤 |
| `history`  | 历史 → agent 形态（多模态 / `<think>` / 页面信封 / 存量主动提示）、会话守卫、落库失败审计行 |
| `profiles` | 昵称 / 企业名（Redis→DB 两跳）、会话标题生成、记忆累积 |

golden `tests/golden/chat_slice_golden.json` **录制于未切片代码**（`_meta.recorded_from` 记了
录制时的 `chat.py` 行数）。切片后**不带** `CHAT_SLICE_GOLDEN_UPDATE=1` 复跑必须逐字节相同。

## 为什么允许 mock LLM / DB / Redis

本文件验的是**装配与分支不变**（哪条路走哪个口、失败走哪个降级），不是"LLM 说了什么"、
也不是"数据库里存了什么"。凡是跨进程的边界（模型、数据库、Redis、时间）一律替身；
替身返回**固定**值 ⇒ 输出可逐字节比较。日志用 loguru sink 抓**未格式化的 message**
（`record["message"]`），避免行号/时间戳把比较弄脏 —— 审计行本身（含 `incident=` 短码）
是要冻的行为，它不是时间戳。

## 三态

- 默认：与 golden 逐字节比对；
- `CHAT_SLICE_GOLDEN_UPDATE=1`：**重录**（只该在未切片代码上或行为变更的同一 commit 里用；
  CI 从不用它 —— 用了就等于把判据改成"记录现状"）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger

from app.api import chat as chat_api
from app.context.menu_navigator import LEGACY_PROACTIVE_TIP_MARK
from app.context.page_registry import (
    PAGE_CONTEXT_ENVELOPE_OPEN,
    PAGE_CONTEXT_ENVELOPE_TAIL,
    PAGE_CONTEXT_UNKNOWN_NOTICE,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "chat_slice_golden.json"
UPDATE_FLAG = "CHAT_SLICE_GOLDEN_UPDATE"


# ══════════════════════════════════════════════════════════════════════════════
# golden 读写 / 比较（唯一实现，四个面共用）
# ══════════════════════════════════════════════════════════════════════════════

def _canon(payload) -> str:
    """稳定序列化：同一 payload 恒得同一串字节（键序 = 构造序，不排序）。"""
    return json.dumps(payload, ensure_ascii=False, indent=1)


#: 每次调用都变的**请求号**（`make_response` 现生成 `req_<hex>`）：它**该变**，
#: 把它冻进 golden 只会让判据随机变红。归一成占位符 —— 保留「这个键在、且是 req_ 形态」
#: 这两条事实（形态变了照样红），只丢随机尾巴。
_RANDOM_KEYS = {"requestId", "timestamp"}


def _normalize(obj):
    if isinstance(obj, dict):
        return {
            k: (
                "req_<normalized>" if k == "requestId" and isinstance(v, str) and v.startswith("req_")
                else "<timestamp>" if k == "timestamp" and isinstance(v, (int, float))
                else _normalize(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def _load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _check(section: str, observed) -> None:
    """逐字节比对；重录模式只写盘 + 断言写进去的确实是本次观测。"""
    golden = _load_golden()
    observed = _normalize(observed)
    produced = _canon(observed)
    if os.environ.get(UPDATE_FLAG) == "1":
        golden[section] = observed
        golden.setdefault("_meta", {})["updated_by"] = "CHAT_SLICE_GOLDEN_UPDATE=1"
        GOLDEN_PATH.write_text(_canon(golden) + "\n", encoding="utf-8")
        assert _canon(_load_golden()[section]) == produced, (
            f"{section}：重录后回读不一致（写盘链路坏了，判据会变成空跑）")
        return
    assert section in golden, (
        f"golden 缺 `{section}` 面 —— 录制不完整（判据不能只冻半边）")
    expected = _canon(golden[section])
    if produced != expected:
        # 逐行 diff 便于具名归因（不打印整块：那块可能几千行）
        got_lines, want_lines = produced.splitlines(), expected.splitlines()
        head = next(
            (f"行{i}: got={got_lines[i]!r} want={want_lines[i]!r}"
             for i in range(min(len(got_lines), len(want_lines)))
             if got_lines[i] != want_lines[i]),
            f"长度不同 got={len(got_lines)} want={len(want_lines)}",
        )
        raise AssertionError(
            f"[{section}] 切片后行为漂移（逐字节不相同）：{head}\n"
            f"若这是**有意的行为变更**：改代码的同一个 commit 里带 "
            f"`{UPDATE_FLAG}=1` 重录并说明理由；若只是搬运，说明搬错了。")


class _Ctx:
    """最小上下文替身：只带 `role`（本文件全部脱敏分支的唯一判据维度）。"""

    def __init__(self, role=None):
        if role is not None:
            self.role = role


class _BadCtx:
    """没有 `role` 属性的上下文（`getattr(..., 'role', '')` 的兜底分支）。"""

    def __getattr__(self, name):  # pragma: no cover - 只在缺属性时被调用
        raise AttributeError(name)


def _capture_logs(fn, *args, **kwargs):
    """跑一段代码并抓 loguru 的 message（不含时间戳/行号），返回 (结果, 日志列表)。"""
    records: list[str] = []
    sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
    try:
        result = fn(*args, **kwargs)
    finally:
        logger.remove(sink)
    return result, records


async def _capture_logs_async(fn, *args, **kwargs):
    records: list[str] = []
    sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
    try:
        result = await fn(*args, **kwargs)
    finally:
        logger.remove(sink)
    return result, records


def _raised(fn, *args, **kwargs):
    """把"抛出来的 HTTPException"冻成可比较的形态（类型 / 状态码 / detail）。"""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 判据要连异常形态一起冻
        return {
            "type": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
            "detail": getattr(exc, "detail", None),
        }
    return None


async def _raised_async(fn, *args, **kwargs):
    try:
        await fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {
            "type": type(exc).__name__,
            "status_code": getattr(exc, "status_code", None),
            "detail": getattr(exc, "detail", None),
        }
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 一、出站整形（卡决策 / 归一 / 脱敏 / 声称改写）
# ══════════════════════════════════════════════════════════════════════════════

#: 覆盖 `_detect_card_type` 的全部卡型分支 + 四个"空态也发卡"契约 + 负例。
CARD_CASES: list[tuple[str, dict]] = [
    ("product_search", {"success": True, "data": {"products": [{"id": "p1", "name": "棉麻窗帘"}]}}),
    ("product_search", {"success": True, "data": {"products": []}}),
    ("product_search", {"success": False, "data": {"products": [{"id": "p1", "name": "棉麻窗帘"}]}}),
    ("product_detail", {"success": True, "data": {"product": {"id": "p1", "name": "棉麻窗帘"}}}),
    ("product_detail", {"success": True, "data": {"product": None}}),
    ("marketing_poster", {"success": True, "data": {
        "product": {"id": "p1"}, "copy": {"title": "夏日特惠", "selling_points": ["遮光"]}}}),
    ("marketing_poster", {"success": True, "data": {
        "product": {"id": "p1"}, "copy": {"title": "   ", "selling_points": ["遮光"]}}}),
    ("marketing_poster", {"success": True, "data": {
        "product": {"id": "p1"}, "copy": {"title": "夏日特惠", "selling_points": []}}}),
    ("marketing_poster", {"success": True, "data": {"product": {"id": "p1"}, "copy": "文案"}}),
    ("product_image_generate", {"success": True, "data": {"image_url": "https://cdn.example.com/a.png"}}),
    ("product_image_generate", {"success": True, "data": {"image_url": "   "}}),
    ("product_image_generate", {"success": True, "data": "oops"}),
    ("logistics_track", {"success": True, "data": {"tracking_number": "SF1001"}}),
    ("logistics_track", {"success": True, "data": {"tracking_number": None}}),
    ("customer_logistics_track", {"success": True, "data": {"logistics_list": [{"no": "SF1001"}]}}),
    ("customer_logistics_track", {"success": True, "data": {"logistics_list": []}}),
    ("order_query", {"success": True, "data": {"order": {"orderNo": "SO1"}}}),
    ("order_query", {"success": True, "data": {"orders": [{"orderNo": "SO1"}, {"orderNo": "SO2"}]}}),
    ("order_query", {"success": True, "data": {"orders": [{"orderNo": "SO1"}]}}),
    ("order_query", {"success": True, "data": {"items": [{"orderNo": "SO1"}]}}),
    ("order_query", {"success": True, "data": {"orders": [], "items": []}}),
    ("order_query", {"success": True, "data": {"orders": "not-a-list"}}),
    ("customer_order_query", {"success": True, "data": {"order": {"orderNo": "SO9"}}}),
    ("curtain_calc", {"success": True, "data": {"total": 1395.56}}),
    ("curtain_calc", {"success": True, "data": {}}),
    ("production_progress_query", {"success": True, "data": {"progress_percent": 0}}),
    ("production_progress_query", {"success": True, "data": {}}),
    ("payment_qrcode_query", {"success": True, "data": {"payment_qrcodes": {}}}),
    ("payment_qrcode_query", {"success": True, "data": {}}),
    ("batch_stock_query", {"success": True, "data": {"action": "batches", "batches": []}}),
    ("batch_stock_query", {"success": True, "data": {"action": ""}}),
    ("unknown_tool", {"success": True, "data": {"x": 1}}),
]

#: 出站文本：手机号 / 座机 / 内部前端路由 / markdown 路由 / 业务斜杠 / 代码围栏 / 空串。
MASK_TEXTS: list[str] = [
    "您的订单请联系 13800138000 或 0571-88886666。",
    "发货需要在后台「销售订单」页（/orders）找到该订单。",
    "请查看 [销售订单](/orders) 页面，或电话 13900139000。",
    "定高买宽/定宽买高，¥29/米，请联系 13700137000。",
    "```\n/orders\n``` 是代码，不要动。",
    "无敏感信息的一句普通回复。",
    "",
]

#: 出站卡片：formFields[].value 与 options[].value / confirmValue 是**协议值**，绝不许脱敏。
MASK_CARD: dict = {
    "component": "form",
    "title": "联系方式 13800138000",
    "fields": [{"label": "电话", "value": "13800138000"}],
    "formFields": [
        {"key": "customer_phone", "label": "手机号 13800138000", "value": "13800138000"},
        {"key": "note", "label": "备注", "value": 3},
    ],
    "options": [{"label": "尾号 8000", "value": "13800138000"}],
    "confirmValue": "13800138000",
}

#: 收尾守卫的文本判据（`_has_card_claim` × `_rewrite_card_claims`）：四面各取正负例。
CLAIM_TEXTS: list[str] = [
    "请点击下方确认卡片完成提交。",
    "开单表单已发出，请查看。",
    "请 点 击 上 方 卡 片",
    "请选择卡其色的窗帘。",
    "请选择色卡上的米白色。",
    "请查看上方结果卡片。",
    "请您选择需要的加工项。",
    "点击确认收货即可。",
    "规格回复『确认』已发出。",
    "确认卡未显示（请刷新页面后重新进入对话）。",
    "物流已发出，单号 SF1001。",
    "",
]


def _observed_outbound() -> dict:
    cards = []
    for tool_name, result in CARD_CASES:
        cards.append({
            "tool": tool_name,
            "result": result,
            "detect": chat_api._detect_card_type(tool_name, result),
            "send": chat_api._should_send_card(tool_name, result),
            "payload": list(chat_api._card_payload(tool_name, result)),
        })

    texts = []
    for text in MASK_TEXTS:
        texts.append({
            "text": text,
            "mask_customer": chat_api._mask_for_customer(text, _Ctx("customer")),
            "mask_merchant": chat_api._mask_for_customer(text, _Ctx("merchant")),
            "mask_no_role": chat_api._mask_for_customer(text, _BadCtx()),
            "sanitize_customer": chat_api._sanitize_outbound_text(text, _Ctx("customer")),
            "sanitize_merchant": chat_api._sanitize_outbound_text(text, _Ctx("merchant")),
        })

    claims = []
    for text in CLAIM_TEXTS:
        claims.append({
            "text": text,
            "has_claim": chat_api._has_card_claim(text),
            "rewritten": chat_api._rewrite_card_claims(text),
            "rewrite_idempotent": chat_api._rewrite_card_claims(
                chat_api._rewrite_card_claims(text)),
        })

    return {
        "cards": cards,
        "normalize": [
            chat_api._normalize_order_card_data({"order": {"orderNo": "SO1"}}),
            chat_api._normalize_order_card_data({"orders": [{"orderNo": "SO1"}]}),
            chat_api._normalize_order_card_data({"orders": [{"orderNo": "SO1"}, {"orderNo": "SO2"}]}),
            chat_api._normalize_order_card_data({"items": [{"orderNo": "SO1"}, {"orderNo": "SO2"}]}),
            chat_api._normalize_order_card_data({"orders": []}),
            chat_api._normalize_order_card_data({"orders": "not-a-list"}),
            chat_api._normalize_order_card_data("oops"),
        ],
        "texts": texts,
        "card_mask_customer": chat_api._mask_card_for_customer(MASK_CARD, _Ctx("customer")),
        "card_mask_merchant": chat_api._mask_card_for_customer(MASK_CARD, _Ctx("merchant")),
        "card_mask_no_role": chat_api._mask_card_for_customer(MASK_CARD, _BadCtx()),
        "card_mask_not_dict": chat_api._mask_card_for_customer("oops", _Ctx("customer")),
        "claims": claims,
    }


def test_outbound_shaping_is_byte_identical_after_slice():
    _check("outbound", _observed_outbound())


# ══════════════════════════════════════════════════════════════════════════════
# 二、<interact> XML 协议解析
# ══════════════════════════════════════════════════════════════════════════════

XML_CHOICE = """<interact>
  <component>choice</component>
  <title>请选择加工项</title>
  <options>
    <option><label>打孔</label><value>punch</value><description>含罗马圈</description></option>
    <option><label>挂钩</label><value>hook</value></option>
  </options>
</interact>"""

XML_CONFIRM = """<interact><component>confirm</component>
<fields>
  <field><label>收货人</label><value>张三</value></field>
  <field><label>手机号</label><value>13800138000</value></field>
  <field><label>缺value</label></field>
</fields>
<confirmLabel>确认下单</confirmLabel><cancelLabel>再改改</cancelLabel>
<confirmValue>yes</confirmValue></interact>"""

XML_FORM = """<interact><component>form</component><title>补全收货信息</title>
<formFields>
  <field><key>receiver</key><label>收货人</label><value>张三</value><required>true</required></field>
  <field><key>phone</key><label>手机号</label><placeholder>请输入手机号</placeholder></field>
  <field><label>缺 key</label></field>
</formFields>
<submitLabel>提交</submitLabel></interact>"""

XML_BROKEN = """<interact><component>choice</component><title>请选择</title>
<options><option><value>only-value</value></option></options></interact>"""

XML_UNKNOWN_COMPONENT = "<interact><component>carousel</component><title>x</title></interact>"

#: choice 的 `value` 缺省时回落到 `label`（协议口径；红证 D 抓出来的覆盖缺口：
#: 早先两个 option 都显式带 value ⇒ 把 `or label` 改成 `or ""` 判据不红 = 空断言）
XML_CHOICE_VALUE_FALLBACK = (
    "<interact><component>choice</component><title>请选择</title><options>"
    "<option><label>米白色</label></option>"
    "<option><label>有 value</label><value>has</value></option>"
    "</options></interact>"
)
XML_NO_COMPONENT = "<interact><title>无组件</title></interact>"

XML_BLOCKS: list[str] = [
    XML_CHOICE, XML_CONFIRM, XML_FORM, XML_BROKEN,
    XML_UNKNOWN_COMPONENT, XML_NO_COMPONENT, XML_CHOICE_VALUE_FALLBACK,
    "", "<interact></interact>",
]

FILTER_PRODUCTS: list[dict] = [
    {"id": "p1", "name": "棉麻窗帘"},
    {"id": "p2", "name": "遮光布"},
    {"id": "p3", "name": "纱帘"},
    "not-a-dict",
]


def _observed_interact() -> dict:
    parsed = []
    for block in XML_BLOCKS:
        parsed.append({
            "block": block,
            "payload": chat_api._parse_interact_xml(block),
            "stripped": chat_api._strip_interact_xml(block),
        })

    reports = []
    samples = [
        ("普通文本，没有块", "sess-1"),
        (f"好的，我先看下。{XML_CHOICE}", "sess-1"),
        (f"残块：{XML_BROKEN}", "sess-2"),
    ]
    for text, sid in samples:
        payload, logs = _capture_logs(chat_api._parse_interact_block_or_report, text, sid)
        reports.append({"text": text, "session_id": sid,
                        "payload": payload, "logs": logs})

    return {
        "parsed": parsed,
        "tag_values": [
            chat_api._extract_tag_value(XML_CHOICE, "title"),
            chat_api._extract_tag_value(XML_CHOICE, "missing"),
            chat_api._extract_tag_value(XML_CHOICE, "label"),
        ],
        "tag_lists": [
            chat_api._extract_tags(XML_CHOICE, "option"),
            chat_api._extract_tags(XML_CHOICE, "nope"),
        ],
        "reports": reports,
        "filter_products": [
            chat_api._filter_products_by_reference("第 1 件 棉麻窗帘 与第 3 件 纱帘", FILTER_PRODUCTS),
            chat_api._filter_products_by_reference("只有 p2 提到", {"products": FILTER_PRODUCTS}),
            chat_api._filter_products_by_reference("什么都没提到", FILTER_PRODUCTS),
            chat_api._filter_products_by_reference("", FILTER_PRODUCTS),
            chat_api._filter_products_by_reference("棉麻窗帘", "not-a-list"),
        ],
    }


def test_interact_protocol_is_byte_identical_after_slice():
    _check("interact", _observed_interact())


# ══════════════════════════════════════════════════════════════════════════════
# 三、历史 / 会话守卫 / 落库失败审计
# ══════════════════════════════════════════════════════════════════════════════

ENVELOPED = (
    f"{PAGE_CONTEXT_ENVELOPE_OPEN}销售订单列表；路径登记：/orders；"
    f"{PAGE_CONTEXT_ENVELOPE_TAIL}我想问下这单到哪了"
)

HISTORY_MESSAGES: list[dict] = [
    {"role": "user", "content": ENVELOPED},
    {"role": "user", "content": PAGE_CONTEXT_UNKNOWN_NOTICE + "你好"},
    {"role": "user", "content": "没有信封的一句用户话"},
    {"role": "assistant", "content": "<think>内部推理</think>给您的答复是 ¥1,395.56。"},
    {"role": "assistant", "content": "请查看上方结果卡片。"},
    {"role": "assistant", "content": f"{LEGACY_PROACTIVE_TIP_MARK}去「销售订单」页）"},
    {"role": "user", "content": "有图的用户消息", "content_type": "image",
     "metadata": {"images": ["https://cdn.example.com/a.jpg", "not-a-url"]}},
    {"role": "assistant", "content": "JSON 字符串 metadata",
     "metadata": json.dumps({"images": ["https://cdn.example.com/b.png"]})},
    {"role": "assistant", "content": "坏 JSON metadata", "metadata": "{not json"},
    {"role": "user", "content": [{"type": "text", "text": "多模态数组"}]},
]

DATETIME_CASES: list = [
    datetime(2026, 11, 6, 11, 42, 0),
    datetime(2026, 11, 6, 11, 42, 0, tzinfo=timezone.utc),
    datetime(2026, 11, 6, 19, 42, 0, tzinfo=timezone(timedelta(hours=8))),
    "2026-11-06T11:42:00+00:00Z",
    "2026-11-06T11:42:00+00:00",
    "2026-11-06T11:42:00",
    12345,
]


def _fake_session_memory(session):
    memory = MagicMock()
    memory.get_session = AsyncMock(return_value=session)
    memory.save_message = AsyncMock(return_value="msg-1")
    return memory


def _observed_history() -> dict:
    memory_cases = [
        ({"tenant_id": 1, "customer_id": "u1"}, {"tenant_id": 1, "user_id": "u1"}),
        (None, {"tenant_id": 1, "user_id": "u1"}),
        ({"tenant_id": 2, "customer_id": "u1"}, {"tenant_id": 1, "user_id": "u1"}),
        ({"tenant_id": 1, "customer_id": "u9"}, {"tenant_id": 1, "user_id": "u1"}),
    ]
    guards = []
    for session, kwargs in memory_cases:
        result, logs = _capture_logs(
            lambda s=session, k=kwargs: _raised(
                lambda: __import__("asyncio").run(
                    chat_api._guard_session(_fake_session_memory(s), "sess-1",
                                            action="查看", **k))),
        )
        guards.append({"session": session, "kwargs": kwargs,
                       "outcome": result, "logs": logs})

    async def _run_save(side_effect, fail_open):
        """落库单一策略点：连"抛不抛 / 抛什么"一起冻（fail_open 的两个分支都是行为）。"""
        memory = MagicMock()
        memory.save_message = (
            AsyncMock(side_effect=side_effect) if side_effect
            else AsyncMock(return_value="msg-1"))
        records: list[str] = []
        sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
        raised = None
        result = None
        try:
            result = await chat_api._save_message_or_report(
                memory, source="chat.assistant", fail_open=fail_open,
                session_id="sess-1", role="assistant", content="hi")
        except Exception as exc:  # noqa: BLE001 - fail-closed 分支的"上抛"本身是被冻的行为
            raised = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            logger.remove(sink)
        return {"result": result, "raised": raised, "logs": records}

    return {
        "history_user_text": [
            chat_api._history_user_text("user", ENVELOPED),
            chat_api._history_user_text("user", "普通用户话"),
            chat_api._history_user_text("assistant", ENVELOPED),
            chat_api._history_user_text("user", ["多模态"]),
        ],
        "legacy_tip_rows": [
            chat_api._is_legacy_proactive_tip_row({"role": "assistant", "content": f"x{LEGACY_PROACTIVE_TIP_MARK}y"}),
            chat_api._is_legacy_proactive_tip_row({"role": "user", "content": f"x{LEGACY_PROACTIVE_TIP_MARK}y"}),
            chat_api._is_legacy_proactive_tip_row({"role": "assistant", "content": "普通回复"}),
        ],
        "format_datetime": [chat_api._format_datetime(dt) for dt in DATETIME_CASES],
        "convert_history": chat_api._convert_history_to_agent_format(HISTORY_MESSAGES),
        "guard_session": guards,
        "raise_session_error": [
            _raised(chat_api._raise_session_error, "SESSION_NOT_FOUND", "会话不存在"),
            _raised(chat_api._raise_session_error, "PERMISSION_DENIED", "无权访问该会话"),
            _raised(chat_api._raise_session_error, "SESSION_CLOSED", "会话已关闭"),
            _raised(chat_api._raise_session_error, "SOMETHING_ELSE", "未知"),
        ],
        "report_persist_failure": [
            _capture_logs(
                chat_api._report_persist_failure,
                exc=TypeError("unexpected keyword argument 'tool_results'"),
                op="save_message", source="chat.assistant",
                session_id="sess-1", role="assistant", tenant_id=1,
            ),
            _capture_logs(
                chat_api._report_persist_failure,
                exc=ConnectionError("db down"),
                op="save_message", source="page.user", session_id="sess-2",
            ),
        ],
        "save_message_ok": _run_save(None, True),
        "save_message_typeerror_fail_open": _run_save(TypeError("drift"), True),
        "save_message_valueerror_fail_open": _run_save(ValueError("boom"), True),
        "save_message_valueerror_fail_closed": _run_save(ValueError("boom"), False),
    }


def test_history_and_persistence_is_byte_identical_after_slice():
    import asyncio

    observed = _observed_history()
    # asyncio.run 不能嵌套在事件循环里；pytest-asyncio auto 下本用例是同步函数 ⇒ 安全。
    for key in ("save_message_ok", "save_message_typeerror_fail_open",
                "save_message_valueerror_fail_open",
                "save_message_valueerror_fail_closed"):
        observed[key] = asyncio.run(observed[key])
    _check("history", observed)


# ══════════════════════════════════════════════════════════════════════════════
# 四、会话周边档案（昵称 / 企业名 / 标题 / 记忆）
# ══════════════════════════════════════════════════════════════════════════════

class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDB:
    """最小 DB 替身：只实现 `async with` + `execute(...).fetchone()`。"""

    def __init__(self, row=None, boom=None):
        self.row = row
        self.boom = boom
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, sql, params):
        self.calls.append({"sql": str(sql), "params": params})
        if self.boom:
            raise self.boom
        return _FakeResult(self.row)


class _FakeRedis:
    """最小 Redis 替身：`Redis(connection_pool=...)` → get / setex。"""

    def __init__(self, connection_pool=None):
        self.connection_pool = connection_pool

    async def get(self, key):
        return None

    async def setex(self, key, ttl, value):
        return True


def _observed_profiles() -> dict:
    import asyncio

    out: dict = {}

    async def _nick(row=None, boom=None, redis_pool=None):
        db = _FakeDB(row=row, boom=boom)
        with patch("app.utils.database.AsyncSessionLocal", return_value=db), \
                patch("app.utils.redis_client.redis_pool", redis_pool), \
                patch("redis.asyncio.Redis", _FakeRedis):
            value, logs = await _capture_logs_async(
                chat_api._get_user_nickname, 1, "u1")
        return {"value": value, "logs": logs,
                "sql": [c["sql"] for c in db.calls]}

    async def _tenant(row=None, boom=None):
        db = _FakeDB(row=row, boom=boom)
        with patch("app.utils.database.AsyncSessionLocal", return_value=db), \
                patch("app.utils.redis_client.redis_pool", None), \
                patch("redis.asyncio.Redis", _FakeRedis):
            value, logs = await _capture_logs_async(
                chat_api._get_tenant_name, 7)
        return {"value": value, "logs": logs,
                "sql": [c["sql"] for c in db.calls]}

    out["nickname"] = [
        asyncio.run(_nick(row=("张老板",))),
        asyncio.run(_nick(row=(None,))),
        asyncio.run(_nick(boom=RuntimeError("db down"))),
        asyncio.run(_nick(row=("张老板",), redis_pool=object())),
    ]
    out["tenant_name"] = [
        asyncio.run(_tenant(row=("词元通达",))),
        asyncio.run(_tenant(row=None)),
        asyncio.run(_tenant(boom=RuntimeError("db down"))),
    ]

    def _title_case(session, llm_content=None, llm_boom=None):
        memory = MagicMock()
        memory.get_session = AsyncMock(return_value=session)
        memory.update_session_title = AsyncMock(return_value=True)

        class _LLM:
            async def ainvoke(self, prompt):
                if llm_boom:
                    raise llm_boom
                self.prompt = prompt
                return SimpleNamespace(content=llm_content)

        llm = _LLM()

        class _Factory:
            @staticmethod
            def create_summary_llm():
                return llm

        class _Memory:
            def __new__(cls):
                return memory

        async def _go():
            return await _capture_logs_async(
                chat_api._generate_title_async, "sess-1", "用户问价", "报价 1395.56")

        with patch("app.memory.session_memory.SessionMemory", _Memory), \
                patch("app.llm.factory.LLMFactory", _Factory):
            _, logs = asyncio.run(_go())
        return {
            "session": session,
            "llm_content": llm_content,
            "llm_error": None if not llm_boom else type(llm_boom).__name__,
            "updated": memory.update_session_title.await_args_list,
            "logs": logs,
        }

    out["title"] = [
        _title_case({"metadata": {"title": "会话 20261106-1142"}}, llm_content='  "窗帘报价"  '),
        _title_case({"metadata": {"title": "会话 20261106-1142"}}, llm_content="  "),
        _title_case({"metadata": {"title": "手动标题"}}, llm_content="不该用到"),
        _title_case(None, llm_content="不该用到"),
        _title_case({"metadata": {"title": "会话 20261106-1142"}}, llm_boom=RuntimeError("llm down")),
    ]

    def _memories(count=3, boom=None):
        calls: list[dict] = []

        class _Extractor:
            @staticmethod
            async def extract_and_accumulate(**kwargs):
                calls.append(kwargs)
                if boom:
                    raise boom
                return count

        async def _go():
            return await _capture_logs_async(
                chat_api._extract_memories_async,
                1, "u1", "用户问价", "报价 1395.56", "sess-1")

        with patch("app.memory.extractor.extract_and_accumulate",
                   _Extractor.extract_and_accumulate):
            _, logs = asyncio.run(_go())
        return {"count": count, "error": None if not boom else type(boom).__name__,
                "calls": calls, "logs": logs}

    out["memories"] = [
        _memories(count=3),
        _memories(count=0),
        _memories(boom=RuntimeError("extract down")),
    ]
    return out


def test_profiles_is_byte_identical_after_slice():
    _check("profiles", _observed_profiles())


# ══════════════════════════════════════════════════════════════════════════════
# 五、golden 自身的完整性（防止"只冻半边"）
# ══════════════════════════════════════════════════════════════════════════════

def test_golden_declares_its_provenance_and_all_four_faces():
    golden = _load_golden()
    assert set(golden) == {"_meta", "outbound", "interact", "history", "profiles"}, (
        f"golden 的面集合变了：{sorted(golden)}")
    meta = golden["_meta"]
    assert meta["recorded_from"] == "backend/ai-agent-service/app/api/chat.py", (
        "golden 必须记明录制来源（行为判据的可追溯性）")
    assert isinstance(meta["recorded_chat_lines"], int) and meta["recorded_chat_lines"] > 2000, (
        f"录制行数不合理：{meta['recorded_chat_lines']!r}")
    # 每一面都必须真的装了样本（空面 = 空断言）
    assert len(golden["outbound"]["cards"]) == len(CARD_CASES)
    assert len(golden["interact"]["parsed"]) == len(XML_BLOCKS)
    assert len(golden["history"]["convert_history"]) == len(HISTORY_MESSAGES) - 1, (
        "存量主动导航提示必须被读侧跳过（喂 10 条、进模型 9 条 —— 差 1 才是对的）")
    assert len(golden["profiles"]["title"]) == 5
