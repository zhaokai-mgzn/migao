# case_ids: OR-033, PG-048, PG-023
"""#4390「Agent 侧缺口台账」本包射程内的两条缺口的确定性判据（零 LLM / 零真实网络）。

台账原文（issue #4390 缺口表）：① `order_create` 不写 `craftLineId`；② 不写 `specialOptions`；
③ 加工费不得由 Agent 声明；④ `curtain_checklist` 采集的 6 个工艺字段要落到订单。

## 核实结论（逐条带证据；本文件锁的是「已实现」的那两条）

### 缺口 ① `craftLineId`：schema 声明了、`processing_info` 也**整体透传** ⇒ 缺的是**绑组形态**
`order_create.py` 的 `items_payload` 构造段把 `processing_info` 原样作为 `processingInfo`
发给服务端（服务端 `OrderCreateRequest.OrderItemRequest.processingInfo` 是 `Object`）
⇒ **不是透传丢失**。真正的缺陷在**形态**：服务端读侧 `ProcessingOrderService.craftGroupKey`
的组键 = 本行 `craftLineId`，**缺省回落本行 `itemId`**（两个不同行的 itemId 天然不等）。
而工具描述原先教的是「配布边行带 `craftLineId=主布行的行标识`」—— 行 id 要**落库后**才有，
下单前拿不到 ⇒ 主布行的组键是它自己的 `itemId`，配布边行写什么都对不上 ⇒
**结构上永远绑不上组**，且后果**静默**：配布边行不被吸收 ⇒ 一扇窗被算成两扇
（褶数/开数/工序/计件全部翻倍；`ProcessingFeeCalculator.windowKey` 的樘窗级去重同时失效
⇒ 同樘窗同名 `specialOptions` 会被收两次）。

**权威写侧口径**（不是我自造的）：`frontend/admin-web/src/lib/order-craft-fields.ts` 的
`resolveWindowCraftLineIds` —— ① `group.length < 2 ⇒ continue`（**单行樘窗不写 `craftLineId`**，
消费端回落本行 itemId）；② `for (const line of group) craftLineIds[line.id] = representative.id`
（**组内每一行都写同一个值**）。页面拿得到行 id ⇒ 可写代表行 id；**agent 下单前拿不到**
⇒ 只能用自命名的稳定标识（如 w1）。本包的修法 = 描述改写 + 跨行闸门
`_reject_ungrouped_craft_lines`（配布边行缺组键 / 组键只绑住一行 ⇒ fail-closed），
两条判据与上面两条口径**逐条对齐**。

### 缺口 ② `specialOptions`：声明 + 透传都在 ⇒ 缺的是**形态闸门**
服务端唯一消费点 `ProcessingOrderService.specialOptions()`：`!(raw instanceof List)
⇒ List.of()` —— **非数组形态整份静默丢弃** ⇒ 车间拿不到勾选、工人拿不到那笔计件
（台账原文的受害面）。而 `BaseTool.validate_args` **显式不校验嵌套明细项**
（docstring：「嵌套明细项（`items[].xxx`，由各工具自己的精确失败面负责」）⇒ 写面此前零校验。
修法 = `_reject_invalid_special_options`（必须是非空字符串数组、无重复项）。

### 缺口 ③ 加工费：**本包未落地**（如实登记，见 `order_create.py` 的 `_entry_processing_fee` 注释）
权威口径 = `POST /api/admin/orders/fee-preview`（`FeePreviewController` → 与建单**同一个**
`ProcessingFeeCalculator.feesFor`）。**消费它 = 每个带加工费域的单多一次 HTTP POST**
⇒ 实测**红 6 个既有用例**：`tests/test_order_create_quantity_bounds.py` 的
`TestOrderCreateProcessingFeeAndItemBounds::test_legal_processing_values_still_pass`（5 个参数化）
+ `TestOrderCreateEnumGuards::test_legacy_pricing_method_no_longer_gated`，断言均为
`mock_client.post.await_count == 1`（该文件共 5 处该断言，另 3 处用例不含加工费域）——
那些文件**不在本包白名单**（只许新建测试文件）⇒ 按「不得削弱既有校验 / 缺前提就停下报告」
登记为需授权项，不在此硬做。**本文件不为它写任何断言**（缺口不许被固化成期望）。

### 缺口 ④ 6 个工艺字段：4 个在、1 个已退役、1 个**不在本包射程**
`curtain_checklist.CHECKLIST_TO_CRAFT_SPEC` 已映射 帘型/工艺/打开方式/定型（+ 用料公式/对花）
⇒ `order_create` 在全部校验前调 `to_craft_spec` 归一 ⇒ 可落库（本文件末段钉住）；
**褶距**已随 issue #4873 退役（写面显式丢弃，本文件钉反向断言）；
**房间（`room`）零映射** —— 修它要改 `curtain_checklist.py`（不在白名单）⇒ 停下报告。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.base import ToolContext
from app.tools.order_create import OrderCreateTool

# ══════════════════════════════════════════════════════════════════════════════
# 夹具：mock admin-api（商品库 + 建单），并记录**建单端点被打了几次**
# ══════════════════════════════════════════════════════════════════════════════

_LIB_PRICE = 168.0


def _rejected(result, what):
    """断言闸门**确实拒绝**并返回它（不用 `is not None` —— 弱断言门禁禁那个形态）。

    闸门返回 None 或 success=True 都算「没拦住」，两种都给可归因的失败信息。
    """
    if result is None:
        raise AssertionError(f"闸门**未拒绝**（静默放行）：{what}")
    assert result.success is False, f"闸门返回了成功结果（未拒绝）：{what} → {result}"
    return result


def _search_response():
    return {"success": True, "data": {
        "items": [{"id": "prod_eval_blackout", "name": "遮光窗帘", "basePrice": _LIB_PRICE}],
        "total": 1}}


def _detail_response():
    return {"success": True, "data": {
        "id": "prod_eval_blackout", "name": "遮光窗帘",
        "price": _LIB_PRICE, "basePrice": _LIB_PRICE,
        "skus": [{"id": "s1", "skuCode": "BLK-28", "colorName": "米白",
                  "sellingMethod": "bulk_cut", "doorWidth": "2.8",
                  "price": _LIB_PRICE, "stock": 500}],
        "status": "on_sale"}}


def _run_execute(items, *, role="agent"):
    """执行 `OrderCreateTool.execute`。

    Returns:
        (result, order_calls, sent) —— order_calls = 打到建单端点的次数；
        sent 是**建单请求体记录**（键 `payload` 只在真的发过 POST 时才出现）。
    """
    client = MagicMock()
    calls = {"orders": 0}
    sent = {}

    async def fake_get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return _search_response()
        return _detail_response()

    async def fake_post(path, json_data=None, **kwargs):
        calls["orders"] += 1
        sent["payload"] = json_data
        return {"success": True, "data": {"id": "o1", "orderNo": "ORD-2026-0001"}}

    client.get = AsyncMock(side_effect=fake_get)
    client.post = AsyncMock(side_effect=fake_post)

    with patch("app.tools.order_create.get_admin_api_client", return_value=client):
        tool = OrderCreateTool()
        result = asyncio.run(tool.execute(
            context=ToolContext(tenant_id=1, user_id="u1", session_id="s1", role=role),
            customer_name="张三", customer_phone="13800138000", items=items,
            sms_code=None,
        ))
    return result, calls["orders"], sent


def _line(quantity=3, unit_price=_LIB_PRICE, **pinfo):
    """一行明细：`processing_info` 由 **pinfo 关键字**组装（camelCase 工艺规格键）。"""
    return {"product_name": "遮光窗帘", "quantity": quantity, "unit_price": unit_price,
            "subtotal": round(unit_price * quantity, 2),
            "processing_info": {"sellingMethod": "bulk_cut", **pinfo}}


def _pi_props():
    return OrderCreateTool.parameters["properties"]["items"]["items"][
        "properties"]["processing_info"]["properties"]


# ══════════════════════════════════════════════════════════════════════════════
# ① 樘窗绑组（craftLineId）—— issue #4387 语义扩展 / #4390 缺口①
# ══════════════════════════════════════════════════════════════════════════════

class TestWindowCraftLineGrouping:
    """组键 = `craftLineId`（缺省回落本行 `itemId`）⇒ **同樘窗每一行都要写同一个值**。"""

    def test_edge_row_without_craft_line_id_is_rejected_before_http(self):
        """配布边行缺 `craftLineId` ⇒ 拦下（改前：静默直发建单 ⇒ 一扇窗算两扇）。

        ⚠️ 这一条正是工具描述**原来教的形态**（「配布边行带 craftLineId=主布行的行标识」）
        漏掉的那半：主布行不写组键 ⇒ 它的组键是它自己的 `itemId` ⇒ 配布边行写什么都对不上。
        """
        items = [
            _line(componentRole="主布", craftLineId="w1"),
            _line(componentRole="配布边", metersSource="跟随主布"),
        ]
        result, order_calls, sent = _run_execute(items)

        assert result.success is False, "配布边行缺组键必须被拦下"
        assert order_calls == 0, "拦截必须发生在调用建单端点**之前**"
        assert "payload" not in sent, "不得触达服务端（建单请求体不存在）"
        assert "配布边" in (result.message or ""), f"必须点名是哪个角色: {result.message}"
        assert "两扇" in (result.message or "") or "翻倍" in (result.message or ""), \
            f"必须写明**真实后果**（静默翻倍）: {result.message}"
        assert "craftLineId" in (result.suggestion or ""), \
            f"suggestion 必须指向要改的字段: {result.suggestion}"

    def test_craft_line_id_binding_only_one_row_is_rejected(self):
        """组键只绑住**一行** ⇒ 拦下 —— 与权威写侧口径逐条对齐。

        权威 = `resolveWindowCraftLineIds`（`frontend/admin-web/src/lib/order-craft-fields.ts`）：
        `group.length < 2 ⇒ continue`（**单行樘窗不写 `craftLineId`**，消费端回落本行 itemId）。
        """
        result, order_calls, sent = _run_execute([_line(componentRole="主布", craftLineId="w1")])

        assert result.success is False, "只绑住一行的组键必须被拦下"
        assert order_calls == 0 and "payload" not in sent, "不得触达服务端"
        assert "w1" in (result.message or ""), f"必须点名是哪个组键: {result.message}"
        assert "两行" in (result.message or "") or "至少" in (result.message or ""), \
            f"必须说明组键的成立条件: {result.message}"

    def test_shared_craft_line_id_reaches_payload_for_cloth_and_sheer(self):
        """布行 + 纱行同樘窗（#4387 R-a）⇒ **两行都落同一个 `craftLineId`**，各成一个部位。"""
        items = [
            _line(componentRole="主布", craftLineId="w1", curtainType="布帘"),
            _line(componentRole="纱", craftLineId="w1", curtainType="纱帘"),
        ]
        result, order_calls, sent = _run_execute(items)

        assert result.success is True, f"合法绑组不得被误拦: {result.error} {result.message}"
        assert order_calls == 1
        infos = [it["processingInfo"] for it in sent["payload"]["items"]]
        assert [i.get("craftLineId") for i in infos] == ["w1", "w1"], \
            f"两行必须落**逐字相同**的组键（服务端靠值相等判同组）: {infos}"
        assert [i.get("componentRole") for i in infos] == ["主布", "纱"], \
            "布/纱两行各成一个部位（纱不得被当成配布边吸收掉）"

    def test_non_string_craft_line_id_is_rejected(self):
        """非字符串组键 ⇒ 拦下（服务端按字面取值绑组，数字/对象形态是幻觉源）。"""
        result, order_calls, _sent = _run_execute([
            _line(componentRole="主布", craftLineId=7),
            _line(componentRole="纱", craftLineId=7),
        ])
        assert result.success is False and order_calls == 0
        assert "craftLineId" in (result.message or "")

    def test_description_no_longer_teaches_the_unbindable_form(self):
        """描述与 schema 的**教学口径**必须已换成「同樘窗每行写同一个值」。

        红证（注入式）：把描述改回修前原文（「配布边行带 `craftLineId=主布行的行标识`」）
        ⇒ 本断言红 —— 旧形态**结构上绑不上组**（下单前不存在行 id）。
        """
        desc = _pi_props()["craftLineId"]["description"]
        tool_desc = OrderCreateTool.description

        assert "同一个值" in desc, f"schema 必须教「同一个值」才算可执行: {desc}"
        assert "不是订单行 id" in desc or "不要写订单行" in desc, \
            f"必须显式排掉「写行 id」这条不可达路径: {desc}"
        assert "主布行的行标识" not in desc, \
            "旧口径（组键 = 主布行的行标识）必须已被替换 —— 下单前拿不到行 id"
        assert "只生成一个部位" not in desc, \
            "旧口径对**纱行**是错的（纱是独立部位，只有配布边被吸收）—— 留着会把纱行也吓跑"
        assert "樘窗" in tool_desc and "同一个 craftLineId" in tool_desc, \
            f"工具描述必须教「同樘窗每一行写同一个 craftLineId」: {tool_desc[:200]}…"

    def test_description_requires_distinct_values_per_window(self):
        """**反方向**的静默涉钱面：不同樘窗必须用**互不相同**的值。

        同一根因的另一半：描述若只说「同一樘窗的每一行写同一个值」，模型极易把 `w1` 当成
        「那个组」的名字 ⇒ 一张**两个窗户**的单 4 行都写 `w1` ⇒ 服务端 `craftGroupKey` 按值
        **逐字相等**判同组 ⇒ **两扇窗并成一扇**，套数/工序/计件**算少**（与「只绑一行 ⇒ 算多」
        同一个静默面，方向相反）。

        **闸门判不出这一条**（见 `_reject_ungrouped_craft_lines` 的判据边界：判它需要
        「这张单有几个窗户」，而该事实不由任何输入给出，`curtainType`/`componentRole` 的组合
        也不足以判定）⇒ 该方向由**描述约束**守住；本断言是它的哨兵 —— 有人精简描述时这条约束
        会**静默消失**，本断言让它变红。
        """
        desc = _pi_props()["craftLineId"]["description"]
        tool_desc = OrderCreateTool.description

        for where, text in (("schema", desc), ("工具描述", tool_desc)):
            assert "不同樘窗" in text, (
                f"{where}必须写明「不同樘窗」这条约束（否则两个窗户会被并成一扇）: {text[:200]}…")
            assert "互不相同" in text, (
                f"{where}必须写明「互不相同」（复用同一个值 ⇒ 两扇并一扇、算少）: {text[:200]}…")


# ══════════════════════════════════════════════════════════════════════════════
# ② specialOptions 形态闸门 —— issue #4230 v1a / #4390 缺口②
# ══════════════════════════════════════════════════════════════════════════════

class TestSpecialOptionsShapeGate:
    """服务端只认 `string[]`（非数组 ⇒ `List.of()` 整份丢弃）⇒ 写面必须拦脏形态。"""

    def test_string_form_is_rejected_with_server_side_consequence(self):
        """`specialOptions` 写成字符串 ⇒ 拒（改前：透传 ⇒ 服务端静默丢弃）。"""
        result = _rejected(
            OrderCreateTool._validate_processing_info(0, {"specialOptions": "加铅块"}),
            "字符串形态（服务端会整份丢弃）")
        assert "specialOptions" in (result.message or ""), \
            f"必须点名是哪个字段: {result.message}"
        assert "数组" in (result.suggestion or ""), \
            f"suggestion 必须给出正确形态: {result.suggestion}"

    def test_non_string_element_is_rejected(self):
        """数组里混非字符串 ⇒ 拒（脏元素会变成取不到价的选项名）。"""
        result = _rejected(
            OrderCreateTool._validate_processing_info(0, {"specialOptions": ["加铅块", 123]}),
            "数组里混非字符串元素")
        assert "123" in (result.message or ""), f"必须点名脏元素: {result.message}"

    def test_blank_element_is_rejected(self):
        """空白项 ⇒ 拒（空名字不构成选项，落库后无人能核对）。"""
        _rejected(
            OrderCreateTool._validate_processing_info(0, {"specialOptions": ["  "]}),
            "空白选项名")

    def test_duplicate_option_is_rejected(self):
        """重复项 ⇒ 拒（同樘窗同名选项只收一次，写两遍说明模型以为是两笔钱）。"""
        result = _rejected(
            OrderCreateTool._validate_processing_info(0, {"specialOptions": ["加铅块", "加铅块"]}),
            "重复选项")
        assert "重复" in (result.message or ""), f"必须说清是重复: {result.message}"

    def test_empty_array_is_treated_as_absent(self):
        """空数组 ⇒ 放行（等价于没选，服务端同样归一成空）。"""
        assert OrderCreateTool._validate_processing_info(0, {"specialOptions": []}) is None

    def test_valid_options_reach_payload(self):
        """合法数组 ⇒ 原样落进 `processingInfo`（不透传丢失；#4390 缺口②的「0 命中」形态）。"""
        result, order_calls, sent = _run_execute([_line(specialOptions=["拼2次", "加铅块"])])

        assert result.success is True, f"合法选项不得被误拦: {result.error} {result.message}"
        assert order_calls == 1
        info = sent["payload"]["items"][0]["processingInfo"]
        assert info["specialOptions"] == ["拼2次", "加铅块"], \
            f"specialOptions 必须原样进 payload: {info}"


# ══════════════════════════════════════════════════════════════════════════════
# ④ 澄清清单字段落库（缺口④：核到哪一步）—— 6 字段里 4 个在、1 个已退役、1 个缺
# ══════════════════════════════════════════════════════════════════════════════

class TestChecklistFieldsReachOrder:
    """`curtain_checklist` 清单 id（snake_case）经 `to_craft_spec` 归一为下单行要素键。"""

    def test_collected_checklist_fields_land_in_payload(self):
        """帘型/打开方式/工艺/定型（+ 用料公式/对花/窗型）⇒ 全部以 canonical 键落进 payload。"""
        items = [{
            "product_name": "遮光窗帘", "quantity": 3, "unit_price": _LIB_PRICE, "subtotal": 504.0,
            "processing_info": {
                "sellingMethod": "bulk_cut",
                # 清单 id（`curtain_checklist.CHECKLIST` 的词汇，snake_case）
                "curtain_type": "纱帘", "craft": "打孔", "open_count": 3,
                "is_shaped": False, "formula": "fullness",
                "has_pattern": True, "window_type": "飘窗",
                # 已退役键（issue #4873）：写面必须显式丢弃，否则「净删」只落在文档层
                "pleatSpacing": 0.15,
            },
        }]
        result, order_calls, sent = _run_execute(items)

        assert result.success is True, f"清单字段不得把合法单拦掉: {result.error} {result.message}"
        assert order_calls == 1
        info = sent["payload"]["items"][0]["processingInfo"]
        assert (info.get("curtainType"), info.get("craft"), info.get("openCount")) == \
            ("纱帘", "打孔", 3), f"帘型/工艺/打开方式必须落 canonical 键: {info}"
        assert info.get("isShaped") is False, f"定型必须落库（False 也要落，不是「缺」）: {info}"
        assert info.get("corner") == "飘窗", f"窗型必须落 corner（转角影响开数与片数）: {info}"
        assert info.get("formula") == "fullness" and info.get("hasPattern") is True, \
            f"用料公式/对花必须落库: {info}"
        assert "pleatSpacing" not in info, "退役的褶距键不得落库（#4873 写面净删）"
