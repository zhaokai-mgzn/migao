# case_ids: CH-021, PR-008, OR-008
"""识别内核测试（issue #5321 包 1 · 页面快通道）

判据（issue #5321「验收判据」，逐条对应）：

1. **识别内核可被页面路径独立调用**（不依赖对话会话）——
   `test_recognize_runs_without_a_conversation_session` + 静态面（不 import 对话路径 / 记忆层）。
2. **管道确定性**：用固定夹具钉住 vision 输出后，「字段 → 表单」这一段可写**死断言** ——
   `TestExtractFieldsProduct` / `TestExtractFieldsOrder` 逐字段比对整张表（不是"包含"）。
3. **每个预填字段带 `[图片识别]` 标注** —— `TestMarker`：值非空 ⇒ `source == "[图片识别]"`；
   留空 ⇒ 无标注但必有 reason。
4. **提交动作不发生在端点 / Agent 侧** —— `TestNoWriteBoundary`：静态扫描 `app/vision/**`
   的写入缝 + **扫描器判别力红证**（注入一个写调用必须能被扫出来）+ 端点返回体恰好三个键。
5. **不确定的字段宁可不填**（错填比留空贵得多）—— 空值 / 置信度不足 / 订单侧手机号形状不合
   ⇒ **不填**并给 reason；且**订单侧阈值严于商品侧**（同一个 0.70 的置信度：商品留、订单弃）。

⚠️ 本文件**不落库**：识别结果只描述「填哪几格」，提交永远是人的动作（包 2 的同页填充通道不在本包）。
"""
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.vision.recognizer import (
    FIELD_MARKER,
    build_messages,
    extract_fields,
    recognize,
)

VISION_DIR = Path(__file__).resolve().parents[2] / "app" / "vision"

# ── 固定夹具：钉住 vision 输出（真实模型只负责产出这段 JSON，其余全是确定性代码）──
PRODUCT_VISION_FIXTURE = """识别结果如下：
```json
{
  "fields": {
    "name":       {"value": "雪尼尔遮光窗帘", "confidence": 0.95},
    "color":      {"value": "3610-28 奶茶色", "confidence": 0.90},
    "material":   {"value": "雪尼尔", "confidence": 0.80},
    "craft":      {"value": "遮光", "confidence": 0.70},
    "door_width": {"value": null, "reason": "图片未标注门幅"},
    "price":      {"value": "128", "confidence": 0.92}
  }
}
```"""

ORDER_VISION_FIXTURE = """```json
{
  "fields": {
    "customer_name":    {"value": "王秀英", "confidence": 0.95},
    "customer_phone":   {"value": "138 0013 8000", "confidence": 0.90},
    "customer_address": {"value": "杭州市余杭区某小区", "confidence": 0.55},
    "items":            {"value": "雪尼尔遮光窗帘、纱帘", "confidence": 0.90},
    "quantity":         {"value": "3 套", "confidence": 0.88},
    "curtain_width":    {"value": "窗宽 2.8 米", "confidence": 0.92},
    "curtain_height":   {"value": "2.40 米", "confidence": 0.90}
  }
}
```"""


class VisionStub:
    """把 vision 调用钉在夹具上，并留下**实际发出的消息**供断言（内核其余部分全是真代码）。"""

    def __init__(self, payload: str = "", error: Exception = None):
        self.payload = payload
        self.error = error
        self.calls = []

    def install(self):
        llm = MagicMock()

        async def _ainvoke(messages):
            self.calls.append(messages)
            if self.error is not None:
                raise self.error
            return AIMessage(content=self.payload)

        llm.ainvoke = _ainvoke
        factory = MagicMock()
        factory.create_vision_llm = MagicMock(return_value=llm)
        return patch("app.vision.recognizer.LLMFactory", factory)

    def sent_content(self):
        return self.calls[0][0].content


# ══════════════════════════════════════════════════════════════════════════════
# 2. 管道确定性：「字段 → 表单」段的死断言
# ══════════════════════════════════════════════════════════════════════════════
class TestExtractFieldsProduct:
    def test_product_fixture_maps_to_an_exact_field_table(self):
        fields = extract_fields("product", PRODUCT_VISION_FIXTURE)
        assert [(f["key"], f["label"], f["value"], f["source"]) for f in fields] == [
            ("name", "商品名称", "雪尼尔遮光窗帘", FIELD_MARKER),
            ("color", "颜色", "3610-28 奶茶色", FIELD_MARKER),
            ("material", "材质", "雪尼尔", FIELD_MARKER),
            ("craft", "工艺", "遮光", FIELD_MARKER),
            ("door_width", "门幅", None, None),
            ("price", "售价", "128", FIELD_MARKER),
        ]

    def test_uncertain_field_is_left_empty_with_a_reason(self):
        door_width = next(
            f for f in extract_fields("product", PRODUCT_VISION_FIXTURE)
            if f["key"] == "door_width"
        )
        assert door_width["value"] is None
        assert door_width["reason"] == "图片未标注门幅"
        assert door_width["source"] is None

    def test_field_order_is_the_schema_order_not_the_model_order(self):
        # 模型把 price 写在最前面，返回顺序仍必须是 schema 顺序（页面按它逐格填）
        shuffled = ('{"fields": {"price": {"value": "9", "confidence": 0.9}, '
                    '"name": {"value": "帘", "confidence": 0.9}}}')
        assert [f["key"] for f in extract_fields("product", shuffled)] == [
            "name", "color", "material", "craft", "door_width", "price",
        ]


class TestExtractFieldsOrder:
    def test_order_fixture_maps_to_an_exact_field_table(self):
        fields = extract_fields("order", ORDER_VISION_FIXTURE)
        assert [(f["key"], f["label"], f["value"], f["source"]) for f in fields] == [
            ("customer_name", "客户名", "王秀英", FIELD_MARKER),
            ("customer_phone", "电话", "13800138000", FIELD_MARKER),
            ("customer_address", "地址", None, None),
            ("items", "商品明细", "雪尼尔遮光窗帘、纱帘", FIELD_MARKER),
            ("quantity", "数量", "3 套", FIELD_MARKER),
            ("curtain_width", "帘宽", "2.8", FIELD_MARKER),
            ("curtain_height", "帘高", "2.4", FIELD_MARKER),
        ]

    def test_order_side_is_stricter_than_product_side_on_the_same_confidence(self):
        """用户裁定：订单侧「不确定的宁可不填」比商品侧更严格（客户信息错 ⇒ 货发错人）。"""
        payload = '{"fields": {"%s": {"value": "王秀英", "confidence": 0.70}}}'
        product = extract_fields("product", payload % "name")
        order = extract_fields("order", payload % "customer_name")
        assert product[0]["value"] == "王秀英"
        assert order[0]["value"] is None
        assert "置信度" in order[0]["reason"]

    def test_low_confidence_field_is_dropped_with_the_threshold_in_the_reason(self):
        address = next(
            f for f in extract_fields("order", ORDER_VISION_FIXTURE)
            if f["key"] == "customer_address"
        )
        assert address["value"] is None
        assert address["reason"] == "置信度 0.55 低于订单侧阈值 0.85，宁可不填"

    def test_malformed_phone_is_never_filled(self):
        """手写单手机号一位看不清 ⇒ 宁可不填（错填 = 货发错人）。"""
        payload = '{"fields": {"customer_phone": {"value": "138 0013 800", "confidence": 0.95}}}'
        phone = extract_fields("order", payload)[1]
        assert phone["key"] == "customer_phone"
        assert phone["value"] is None
        assert phone["reason"] == "手机号「138 0013 800」不是 11 位有效号码，宁可不填"

    def test_phone_is_normalised_by_stripping_separators(self):
        payload = ('{"fields": {"customer_phone": '
                   '{"value": "+86 138-0013-8000", "confidence": 0.95}}}')
        assert extract_fields("order", payload)[1]["value"] == "13800138000"

    @pytest.mark.parametrize("raw", ["", "参", "货到付款", "138001380001"])
    def test_non_phone_garbage_never_becomes_a_phone(self, raw):
        payload = '{"fields": {"customer_phone": {"value": "%s", "confidence": 0.99}}}' % raw
        assert extract_fields("order", payload)[1]["value"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. 逐字段 `[图片识别]` 标注
# ══════════════════════════════════════════════════════════════════════════════
class TestExtractFieldsOrderSize:
    """订单侧尺寸字段（issue #5349）：**推导链的原始输入**必须结构化到「页面能直接用」。

    判据（issue #5349 判据 3 + 「不确定的宁可不填」）：

    1. 🔴 手写单常见的 `2.8×2.4` **没写明哪个是宽哪个是高**，而约定**不统一**
       ⇒ **两个尺寸格都留空 + 给理由**，**不猜顺序**（猜错 = 成品尺寸反了 ⇒ 米数错 ⇒ 钱错）；
    2. 值必须是**规范十进制串**（`2.80 米` → `2.8`）—— 前端数字框吃的是 `Number(value)`，
       原文带中文单位 ⇒ `NaN` ⇒ 推导链 fail-closed（页面看着"填了"、实际不推）；
    3. 读不出唯一一个数 / 超出合理量程 ⇒ 留空。

    **注入式红证**（逐条可单独变红）：把 `recognizer.py` 的 `_normalise_size` 摘掉（或让
    `_resolve` 不再调用它）⇒ 本类第 1 条的 `2.8×2.4` 会被原样填进「帘宽」⇒ 当场红；
    把归一那步改成 `return value, None` ⇒ 第 2 条的长度 / `float()` 断言红。
    """

    @staticmethod
    def _field(key: str, value, confidence: float = 0.95) -> dict:
        payload = json.dumps(
            {"fields": {key: {"value": value, "confidence": confidence}}}, ensure_ascii=False
        )
        return next(f for f in extract_fields("order", payload) if f["key"] == key)

    @pytest.mark.parametrize("raw", ["2.8×2.4", "2.8*2.4", "2.8 x 2.4", "宽高 2.8/2.4"])
    def test_undirected_pair_is_never_guessed_into_one_axis(self, raw):
        """`2.8×2.4` ⇒ 两个尺寸格都留空（**不猜顺序**），理由必须说清是方向问题。"""
        for key in ("curtain_width", "curtain_height"):
            field = self._field(key, raw)
            assert field["value"] is None
            assert field["source"] is None
            assert field["reason"] == (
                f"「{raw}」没写明哪一个是宽、哪一个是高（手写单的宽高顺序约定不统一）"
                "⇒ 宁可不填，请手工填「帘宽」「帘高」"
            )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2.8", "2.8"),
            ("2.80 米", "2.8"),
            ("窗宽 2.8 米", "2.8"),
            ("2.8m", "2.8"),
            ("2.4 M", "2.4"),
            ("约 2.5 米左右", "2.5"),
            ("3", "3"),
        ],
    )
    def test_size_is_normalised_to_a_plain_decimal_the_page_can_read(self, raw, expected):
        field = self._field("curtain_width", raw)
        assert field["value"] == expected
        # 判据的牙齿：前端 `Number(value)` 必须吃下它（`2.8米` 会得到 NaN ⇒ 推导链静默不跑）
        assert float(field["value"]) == float(expected)

    @pytest.mark.parametrize("raw", ["看不清", "深灰色", "货到付款"])
    def test_values_without_a_size_number_are_left_empty(self, raw):
        field = self._field("curtain_height", raw)
        assert field["value"] is None
        assert field["reason"] == f"「{raw}」里读不出尺寸数字 ⇒ 宁可不填"

    @pytest.mark.parametrize("raw", ["28", "0.05", "13800138000"])
    def test_implausible_sizes_never_become_a_curtain_dimension(self, raw):
        """`28` 米不是窗帘（漏了小数点）、`13800138000` 更不是尺寸。"""
        field = self._field("curtain_width", raw)
        assert field["value"] is None
        assert field["reason"] == f"「{raw}」不在帘宽 / 帘高的合理量程（0.2~20.0 米）内 ⇒ 宁可不填"

    def test_size_shape_gate_runs_before_the_confidence_gate(self):
        """**很自信地**抄成对写法也要拦（与手机号闸同一个位置：置信度闸之前）。

        理由：形状错 ⇒ 下游一定错（尺寸错 ⇒ 米数错 ⇒ 钱错），置信度高只说明"抄得清楚"。
        """
        field = self._field("curtain_width", "2.8×2.4", confidence=0.99)
        assert field["value"] is None
        assert "置信度" not in field["reason"]

    def test_product_side_is_untouched_by_the_order_side_size_guard(self):
        """商品侧的 `door_width` 不套这条闸（它的门幅是**商品属性**，不是窗帘成品尺寸）。"""
        payload = '{"fields": {"door_width": {"value": "门幅2.8米", "confidence": 0.9}}}'
        assert extract_fields("product", payload)[4]["value"] == "门幅2.8米"


class TestMarker:
    def test_every_filled_field_carries_the_marker(self):
        for target_type, fixture in (("product", PRODUCT_VISION_FIXTURE),
                                     ("order", ORDER_VISION_FIXTURE)):
            fields = extract_fields(target_type, fixture)
            filled = [f for f in fields if f["value"]]
            empty = [f for f in fields if not f["value"]]
            assert filled, f"{target_type}: 夹具应至少预填一格"
            assert empty, f"{target_type}: 夹具应至少留空一格"
            assert {f["source"] for f in filled} == {FIELD_MARKER}
            # 留空的格子**没有**标注（标注 = 「这格是识别出来的」，空值不得冒充）
            assert {f["source"] for f in empty} == {None}
            assert all(f["reason"] for f in empty)

    def test_marker_is_the_contract_string(self):
        assert FIELD_MARKER == "[图片识别]"


# ══════════════════════════════════════════════════════════════════════════════
# 1. 内核可被页面路径独立调用
# ══════════════════════════════════════════════════════════════════════════════
class TestRecognizeKernel:
    @pytest.mark.asyncio
    async def test_recognize_runs_without_a_conversation_session(self):
        """页面路径的唯一入口：签名里**没有** session_id / 会话对象。"""
        assert "session_id" not in inspect.signature(recognize).parameters

        stub = VisionStub(PRODUCT_VISION_FIXTURE)
        with stub.install():
            result = await recognize("product", ["https://oss.example.com/a.jpg"], tenant_id=7)
        assert result == {
            "target_type": "product",
            "fields": extract_fields("product", PRODUCT_VISION_FIXTURE),
            "degraded": False,
        }

    @pytest.mark.asyncio
    async def test_recognize_normalises_urls_before_calling_vision(self):
        """CDN 重写发生在**发给 vision 之前**（与对话路径同一份规则、同一份实现）。"""
        stub = VisionStub(PRODUCT_VISION_FIXTURE)
        with patch("app.vision.pipeline.settings") as s, stub.install():
            s.IMAGE_URL_REWRITE_FROM = "https://cdn.a.com"
            s.IMAGE_URL_REWRITE_TO = "https://oss.a.com"
            await recognize("product", [
                "https://cdn.a.com/a.jpg",
                "http://bad.example.com/skip.jpg",
            ], tenant_id=7)
        content = stub.sent_content()
        assert [c["image_url"]["url"] for c in content if c["type"] == "image_url"] == [
            "https://oss.a.com/a.jpg",
        ]

    @pytest.mark.asyncio
    async def test_unknown_target_type_is_rejected(self):
        with pytest.raises(ValueError) as ei:
            await recognize("invoice", ["https://oss.example.com/a.jpg"])
        assert "invoice" in str(ei.value)

    @pytest.mark.asyncio
    async def test_no_usable_image_is_rejected(self):
        with pytest.raises(ValueError) as ei:
            await recognize("product", ["http://bad.example.com/a.jpg", ""])
        assert "图片" in str(ei.value)


class TestNoWriteBoundary:
    """**任务 6 / 验收判据 4**：识别结果只填表，提交永远是人的动作。"""

    WRITE_SEAMS = (
        "app.api.chat",
        "app.memory",
        "SessionMemory",
        "session_memory",
        "get_admin_api_client",
        "commit(",
        "db.add(",
        "INSERT INTO",
    )

    @classmethod
    def scan(cls, source: str):
        return [seam for seam in cls.WRITE_SEAMS if seam in source]

    def test_vision_package_touches_no_write_seam(self):
        hits = {}
        for path in sorted(VISION_DIR.glob("*.py")):
            found = self.scan(path.read_text(encoding="utf-8"))
            if found:
                hits[path.name] = found
        assert hits == {}

    def test_scanner_has_discriminative_power(self):
        """**注入式红证**：把一个写调用塞进内核源码，上面的断言必须变红。

        逐条证明扫描器认得出每一种写缝形态（若换掉 `WRITE_SEAMS` 或把扫描写成恒真，
        本用例先红）—— 不是"一起红"的装饰。
        """
        assert self.scan("    await SessionMemory().save_message(sid, text)\n") == ["SessionMemory"]
        assert self.scan("    await db.commit()\n") == ["commit("]
        assert self.scan("    client = get_admin_api_client()\n") == ["get_admin_api_client"]
        assert self.scan("    cur.execute('INSERT INTO products VALUES (1)')\n") == ["INSERT INTO"]
        assert self.scan("    return fields\n") == []

    @pytest.mark.asyncio
    async def test_endpoint_returns_fields_only_and_never_persists(self):
        """端点返回体**恰好**只有三个键 —— 没有 id / saved / created 之类的落库痕迹。"""
        import app.api.internal as internal_mod
        from app.api.internal import VisionRecognizeRequest, vision_recognize

        stub = VisionStub(PRODUCT_VISION_FIXTURE)
        with stub.install():
            resp = await vision_recognize(
                VisionRecognizeRequest(
                    tenant_id=7,
                    target_type="product",
                    images=["https://oss.example.com/a.jpg"],
                ),
                authorized=True,
            )
        assert resp["success"] is True
        assert set(resp["data"].keys()) == {"target_type", "fields", "degraded"}
        assert resp["data"]["degraded"] is False
        assert resp["data"]["fields"] == extract_fields("product", PRODUCT_VISION_FIXTURE)
        # 端点 handler 源码里不得出现任何写入缝
        assert self.scan(inspect.getsource(vision_recognize)) == []

    @pytest.mark.asyncio
    async def test_vision_failure_degrades_to_empty_fields_never_fabricates(self):
        stub = VisionStub(error=RuntimeError("vision down"))
        with stub.install():
            result = await recognize("order", ["https://oss.example.com/a.jpg"], tenant_id=7)
        assert result["degraded"] is True
        assert result["fields"] == []

    @pytest.mark.asyncio
    async def test_unparseable_vision_output_degrades_to_empty_fields(self):
        stub = VisionStub("抱歉，我看不清这张图片。")
        with stub.install():
            result = await recognize("order", ["https://oss.example.com/a.jpg"], tenant_id=7)
        assert result["degraded"] is True
        assert result["fields"] == []


class TestBuildMessages:
    def test_messages_carry_one_image_block_per_url_and_the_target_schema(self):
        msgs = build_messages("order", ["https://oss.example.com/a.jpg",
                                        "https://oss.example.com/b.jpg"])
        assert len(msgs) == 1
        content = msgs[0].content
        assert isinstance(content, list)
        assert [c["type"] for c in content] == ["text", "image_url", "image_url"]
        assert [c["image_url"]["url"] for c in content if c["type"] == "image_url"] == [
            "https://oss.example.com/a.jpg",
            "https://oss.example.com/b.jpg",
        ]
        prompt = content[0]["text"]
        # 订单侧字段 schema 与商品侧**不同**（不得做成「一套字段两个页面填」）
        assert "customer_phone" in prompt
        assert "door_width" not in prompt