"""InteractTool 单元测试 — 生成交互组件，无 API 调用"""
# case_ids: PR-010, CH-019, UI-043
import pytest
import json
from app.tools.interact import InteractTool


@pytest.fixture
def tool():
    return InteractTool()


class TestConfirmValueDeterministic:
    """confirm 卡的 `confirmValue` 必须由**实质内容**决定（issue #3401 根因）。

    实证（run 34756290189 工具健康度）：`order_create!confirmation_required × 4` ——
    确认门禁要求"用户消息**精确等于**最近一次确认卡的 confirmValue"，而该值由**模型**书写
    （工具描述还要求它"包含上下文"）→ 模型每次重发确认卡换一种措辞，值就变了 →
    顾客点的是上一张卡的值 → 门禁判"没确认" → 模型再发卡 → **确认死循环、订单落不了库**
    （OR-019/OR-023/OR-024 三条用例的失败形态）。

    修法：值只由**字段（顾客要确认的事实）**决定 —— 同样的事实 ⇒ 同样的值（点击必中）；
    事实变了（数量 3→4、总价变）⇒ 值变（顾客必须重新确认，语义不被削弱）。
    """

    def _value(self, tool, fields, model_value, ctx):
        import asyncio
        res = asyncio.run(tool.execute(
            context=ctx, component="confirm", title="请确认订单信息",
            fields=fields, confirmValue=model_value))
        assert res.success, res.error
        return res.data["confirmValue"]

    def _fields(self, qty=3, total="528"):
        return [{"label": "商品", "value": f"遮光窗帘 米白 {qty}米"},
                {"label": "总价", "value": f"¥{total}"}]

    def test_same_facts_same_value_regardless_of_wording(self, tool, sample_tool_context):
        a = self._value(tool, self._fields(), "确认下单：遮光窗帘 米白 3米 合计528元", sample_tool_context)
        b = self._value(tool, self._fields(), "请核对后确认创建订单（遮光窗帘 3 米）", sample_tool_context)
        assert a == b, (
            f"同一张卡的两种措辞必须得到同一个 confirmValue（否则顾客点击不中）: {a!r} vs {b!r}")

    def test_changed_facts_change_value(self, tool, sample_tool_context):
        a = self._value(tool, self._fields(qty=3, total="528"), "确认下单", sample_tool_context)
        b = self._value(tool, self._fields(qty=4, total="704"), "确认下单", sample_tool_context)
        assert a != b, "数量/金额变了必须换值（顾客要重新确认新明细）"

    def test_field_order_does_not_matter(self, tool, sample_tool_context):
        """同一批事实换个**字段顺序**（模型自由发挥）也必须同值。"""
        a = self._value(tool, self._fields(), "确认", sample_tool_context)
        rev = list(reversed(self._fields()))
        b = self._value(tool, rev, "确认", sample_tool_context)
        assert a == b, f"字段顺序变了值就变 → 点击仍可能不中: {a!r} vs {b!r}"

    def test_value_still_reads_as_confirmation(self, tool, sample_tool_context):
        """值仍需以确认词开头（门禁的 `_is_explicit_confirmation` 短词判定依赖它）。"""
        v = self._value(tool, self._fields(), "确认下单", sample_tool_context)
        assert v.startswith("确认"), v


class TestInteractChoice:
    async def test_choice_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "打孔", "value": "hole"},
                {"label": "韩褶", "value": "pleat"},
            ],
        )
        assert result.success is True
        assert result.data["component"] == "choice"
        assert len(result.data["options"]) == 2

    async def test_choice_options_json_string(self, tool, sample_tool_context):
        """options 为 JSON 字符串时自动解析"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="选择色号",
            options=json.dumps([{"label": "深灰", "value": "dark_gray"}]),
        )
        assert result.success is True
        assert result.data["options"][0]["label"] == "深灰"

    async def test_choice_with_pagemeta(self, tool, sample_tool_context):
        """choice 组件接收 pageMeta 并透传（加工项列表分页展示）。

        生产回归（sess_fba38395ed094a9d）：processing_item_query 返回的 pageMeta
        提示 LLM「调用 interact(choice) 时直接透传」，但 execute 签名无该参数
        导致 TypeError → 整个 agent 流崩溃、assistant 消息不落库。
        """
        page_meta = {
            "current": 1,
            "total": 4,
            "totalCount": 32,
            "tool": "processing_item_query",
            "params": json.dumps({"keyword": "", "page": 1, "size": 10}, ensure_ascii=False),
        }
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "1. 罗马杆环安装", "value": "proc_item_hook_roman"},
                {"label": "2. 高温定型", "value": "proc_item_shape_high"},
            ],
            pageMeta=page_meta,
        )
        assert result.success is True
        assert result.data["component"] == "choice"
        assert result.data["pageMeta"] == page_meta

    async def test_choice_multi_select_passthrough(self, tool, sample_tool_context):
        """choice 组件 multiSelect=True 时透传到 data（B 端加工项多选）。

        回归（issue #2894）：加工项选择需支持多次点击选择（每个选项分别发送），
        multiSelect 标记须透传，前端 ChoiceCard 据此不锁死卡片并保留翻页控件。
        """
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "打孔加工", "value": "pi_hole"},
                {"label": "韩式折边", "value": "pi_pleat"},
            ],
            pageMeta={
                "current": 1,
                "total": 3,
                "totalCount": 22,
                "tool": "processing_item_query",
                "params": json.dumps({"keyword": "", "page": 1, "size": 10}, ensure_ascii=False),
            },
            multiSelect=True,
        )
        assert result.success is True
        assert result.data["multiSelect"] is True

    async def test_choice_multi_select_default_false(self, tool, sample_tool_context):
        """未显式传 multiSelect 时默认为单选（不输出 multiSelect 字段）。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择分类",
            options=[{"label": "窗帘", "value": "curtain"}],
        )
        assert result.success is True
        assert "multiSelect" not in result.data

class TestInteractConfirm:
    async def test_confirm_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="确认创建商品？",
            fields=[
                {"label": "商品名称", "value": "遮光窗帘"},
                {"label": "价格", "value": "299元"},
            ],
            confirmLabel="确认创建商品",
        )
        assert result.success is True
        assert result.data["component"] == "confirm"
        assert len(result.data["fields"]) == 2


class TestInteractForm:
    async def test_form_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="form",
            title="创建商品",
            formFields=[
                {"key": "name", "label": "商品名称", "type": "text", "required": True},
                {"key": "price", "label": "价格", "type": "number", "required": True},
            ],
        )
        assert result.success is True
        assert result.data["component"] == "form"


class TestInteractError:
    async def test_invalid_component_type(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="invalid_type",
            title="test",
        )
        assert result.success is False

    async def test_choice_missing_options(self, tool, sample_tool_context):
        """choice 组件缺少 options 时报错"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="选择",
        )
        assert result.success is False


class TestChoiceConfirmItemShapeGuard:
    """choice 的 options / confirm 的 fields 必须**逐项归一**（issue #3962）。

    根因：`form` 分支有逐项校验（每个 formField 必须有 key 和 label，否则 fail-closed），
    choice/confirm 只查了 `len(...) == 0` —— 模型把 options 传成**字符串数组**
    （实测 `["LG工艺 ¥50/件","打孔加工"]`）时工具返回 `success=True` 并原样下发。
    前端 C 端 `ChoiceCard.tsx` 渲染 `{opt.label}`、B 端 `InteractiveMessage.tsx` 用
    `opt.label || opt.value` → `undefined` ⇒ **选项行没有文字（一张没有按钮的卡）**，
    点击还把 `undefined` 当答复回传，流程直接坏掉。

    归一规则（逐项）：
      · 字符串项 → `{"label": s, "value": s}`（label 即人话，回传人话）；
      · 缺 label 用 value 补、缺 value 用 label 补（value 是回传标识，缺了就发 undefined）；
      · label/value 都没有（含纯空白字符串、非 str/dict） → **丢弃**；
      · 归一后为空 ⇒ 复用**现有**错误返回 fail-closed、**不发卡**。
    """

    async def test_choice_string_options_normalized(self, tool, sample_tool_context):
        """issue #3962 复现形态：`options` 是字符串数组 → 必须归一为 label/value 对象。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=["LG工艺 ¥50/件", "打孔加工"],
        )
        assert result.success is True, result.error
        assert result.data["options"] == [
            {"label": "LG工艺 ¥50/件", "value": "LG工艺 ¥50/件"},
            {"label": "打孔加工", "value": "打孔加工"},
        ]

    async def test_choice_json_string_options_normalized(self, tool, sample_tool_context):
        """字符串数组经 JSON 字符串传入（模型真实形态）同样归一。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=json.dumps(["LG工艺 ¥50/件", "打孔加工"], ensure_ascii=False),
        )
        assert result.success is True, result.error
        assert result.data["options"] == [
            {"label": "LG工艺 ¥50/件", "value": "LG工艺 ¥50/件"},
            {"label": "打孔加工", "value": "打孔加工"},
        ]

    async def test_choice_partial_keys_normalized(self, tool, sample_tool_context):
        """只给一半键：缺 label 用 value 补，缺 value 用 label 补。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[{"label": "打孔", "value": "pi_hole"}, {"label": "韩褶"}],
        )
        assert result.success is True, result.error
        assert result.data["options"] == [
            {"label": "打孔", "value": "pi_hole"},
            {"label": "韩褶", "value": "韩褶"},
        ]

    async def test_choice_items_without_label_and_value_dropped(self, tool, sample_tool_context):
        """无 label 无 value 的项必须丢弃；有效项的**其余键**（如 description）保留。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"description": "只有说明，没有 label/value"},
                "",
                "   ",
                123,
                None,
                {"label": "打孔", "value": "pi_hole", "description": "免费"},
            ],
        )
        assert result.success is True, result.error
        assert result.data["options"] == [
            {"label": "打孔", "value": "pi_hole", "description": "免费"},
        ]

    async def test_choice_all_items_invalid_fail_closed(self, tool, sample_tool_context):
        """全部项无效 ⇒ 沿用现有错误返回、**不发卡**（不得发出空白按钮卡）。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[{"description": "只有说明"}, 123, None],
        )
        assert result.success is False
        assert result.error == "choice 组件需要至少一个 option"
        assert result.data is None, "归一后为空必须 fail-closed，不发卡"

    async def test_confirm_fields_partial_keys_normalized(self, tool, sample_tool_context):
        """confirm 的 fields 同规则：缺 label 用 value 补、缺 value 用 label 补。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认订单信息",
            fields=[{"label": "商品名称"}, {"value": "遮光窗帘 3米"}],
        )
        assert result.success is True, result.error
        assert result.data["fields"] == [
            {"label": "商品名称", "value": "商品名称"},
            {"label": "遮光窗帘 3米", "value": "遮光窗帘 3米"},
        ]

    async def test_confirm_string_fields_normalized(self, tool, sample_tool_context):
        """confirm 的 fields 传字符串数组同样归一（与 choice 同规则）。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认订单信息",
            fields=["商品名称：遮光窗帘"],
        )
        assert result.success is True, result.error
        assert result.data["fields"] == [
            {"label": "商品名称：遮光窗帘", "value": "商品名称：遮光窗帘"},
        ]

    async def test_confirm_value_built_from_normalized_facts(self, tool, sample_tool_context):
        """`confirmValue` 必须基于**归一后**的字段（否则值里带 None → 顾客点击不中）。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认订单信息",
            fields=[{"value": "遮光窗帘 3米"}, {"label": "总价"}],
            confirmValue="确认下单",
        )
        assert result.success is True, result.error
        assert result.data["confirmValue"] == "确认：" + "；".join(sorted([
            "总价=总价",
            "遮光窗帘 3米=遮光窗帘 3米",
        ]))

    async def test_confirm_all_fields_invalid_fail_closed(self, tool, sample_tool_context):
        """confirm 全部字段无效 ⇒ 沿用现有错误返回、**不发卡**。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认订单信息",
            fields=[{"description": "只有说明"}],
        )
        assert result.success is False
        assert result.error == "confirm 组件需要至少一个 field"
        assert result.data is None, "归一后为空必须 fail-closed，不发卡"


class TestInteractFormRegression:
    """form 分支行为**不得**被本次归一改动波及（回归保护）。"""

    async def test_form_missing_label_still_fail_closed(self, tool, sample_tool_context):
        formFields = [{"key": "name"}]
        result = await tool.execute(
            context=sample_tool_context,
            component="form",
            title="创建商品",
            formFields=formFields,
        )
        assert result.success is False
        assert result.error == "每个 formField 必须有 key 和 label"
        assert result.data is None

    async def test_form_fields_not_reshaped(self, tool, sample_tool_context):
        """form 分支不做归一：字段原样透传（不会被注入 value 等键）。"""
        formFields = [{"key": "name", "label": "商品名称", "type": "text", "required": True}]
        result = await tool.execute(
            context=sample_tool_context,
            component="form",
            title="创建商品",
            formFields=formFields,
        )
        assert result.success is True, result.error
        assert result.data["formFields"] == formFields


class TestCardPiiNotMaskedAtToolLayer:
    """工具层**不脱敏**（issue #3379 边界修正，实测回归）。

    首版把卡片脱敏做在 `interact` 工具里 → 工具返回值同时进入**模型上下文**与
    `confirmValue`（顾客回传后要精确匹配）→ 实测把流程搞坏（run 34736385849：
    卡片显示"待补充完整手机号"，模型反过来问顾客要号码；验收 2 条违规）。
    脱敏移到**出站序列化**（`chat.py` 的 SSE 层）后，顾客看到的仍是脱敏值。
    本测试锁住这个边界：工具层必须保持原值。
    """

    async def test_tool_keeps_raw_values(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认收货信息",
            fields=[{"label": "手机号", "value": "13800138000"}],
            confirmValue="确认提交：13800138000",
        )
        payload = json.dumps(result.data, ensure_ascii=False)
        assert "13800138000" in payload, "工具层不得脱敏（会污染模型上下文与 confirmValue）"
