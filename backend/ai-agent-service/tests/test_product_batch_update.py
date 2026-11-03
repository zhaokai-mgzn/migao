# case_ids: PR-108, PR-109
"""`product_batch_update` 批量更新的 Agent 能力 — 契约 / 两段确认 / 阈值 / 撤销（issue #5314）

被测对象 = issue #5314 冻结契约（评论「批量更新能力 —— 设计 + 冻结契约（2026-09-24）」）
的 **Agent 侧一半**（服务端 `/api/admin/agent/batches` 由另一个包实现，本文件按契约编码，
**不依赖服务端存在**：HTTP 客户端全程替身）。

本文件锁的不变式（每条都能单独变红）：

1. **契约面**：preview → `POST /api/admin/agent/batches`，body `{batchType, items:[{resourceId,
   field, oldValue, newValue}]}`（camelCase，逐字对齐契约表）；execute/revert →
   `POST /api/admin/agent/batches/{batchId}/{execute-async,revert-async}`，随后
   `GET /api/admin/agent/batches/{batchId}` 轮询到终态（issue #8283）。
2. **两段确认不可跳过**（本单核心交互）：
   · 第一段 = `interact(multiSelect=true)` 让商家勾选集合（**改哪些**）；
   · 第二段 = `interact(confirm)` 逐条「改前 → 改后」预览（**改成什么**）；
   · 机器判据：`action=execute/revert` **必须**带 `batch_id`，而它只能由 `action=preview`
     产生 ⇒ 「没预览就执行」在结构上不可达（不是靠 prompt 自律）。
3. **逐条 before → after 的字段投影只此一处**：预览行由 `app/tools/confirm_value.py`
   派生（`confirm_card_fields`），**不新立第二份字段投影**（#5303 的同一套单一源）。
4. **阈值 + 后台 job**：`N > 50` ⇒ 拒绝并提示分批；`N == 50` 放行（边界双侧）；
   执行/撤销提交后台 job 后轮询，超时只报「尚未完成」。
5. **batchType 白名单只有两个**：`product_price` / `inventory_stock`（通用批量不做；
   上下架按 2026-10-16 裁定单件/批量都 ❌，#7334 裁定 A 移除 `product_status`）。
6. **撤销入口可用**：`revert` 逐条还原 `old_value`，且执行成功的话术里就告诉用户「可以撤销」。
7. **部分失败逐条报告，不做整体回滚**（回滚会掩盖真问题）。
8. 权限码与逐条写**同码**（`product:create`，= `product_update` 的写码）。
"""
import ast
import inspect
import textwrap
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools import confirm_value, product_batch_update
from app.tools.base import ToolContext
from app.tools.product_batch_update import (
    BATCH_TYPE_PRICE,
    BATCH_TYPE_STOCK,
    BATCH_TYPES,
    MAX_BATCH_ITEMS,
    VALID_ACTIONS,
    ProductBatchUpdateTool,
)

PRICE_ITEMS = [
    {"resourceId": "prod_eval_blackout", "field": "price", "oldValue": 168, "newValue": 155},
    {"resourceId": "prod_eval_dark_green", "field": "price", "oldValue": 128, "newValue": 155},
]
#: 第三个具名批量（issue #5950）：库存调整 —— field 是 `stock`（与逐条写同一个字段词）。
STOCK_ITEMS = [
    {"resourceId": "prod_eval_blackout", "field": "stock", "oldValue": 1000, "newValue": 1200},
    {"resourceId": "prod_eval_dark_green", "field": "stock", "oldValue": 800, "newValue": 1200},
]


def _ctx(permissions=("*",), role="admin") -> ToolContext:
    """商户上下文：权限码按 JWT `permissions` claim 判定（#4106 F3）。"""
    return ToolContext(tenant_id=1, user_id="u1", role=role,
                       permissions=list(permissions), session_id="s1")


def _client(post_return, get_return=None):
    """替身 admin-api 客户端：`post` 提交 job，`get` 查进度（issue #8283）。"""
    client = MagicMock()
    client.post = AsyncMock(return_value=post_return)
    client.get = AsyncMock(return_value=get_return if get_return is not None else _ok({}))
    return client


def _ok(data):
    return {"success": True, "data": data}


@pytest.fixture
def tool():
    return ProductBatchUpdateTool()


# ══════════════════════════════════════════════════════════════════════════════
# 一、preview：契约 payload + 逐条 before → after（第二段确认的材料）
# ══════════════════════════════════════════════════════════════════════════════


class TestPreview:
    @pytest.mark.asyncio
    async def test_preview_posts_frozen_contract_payload(self, tool):
        """preview == 创建批次（= 预演）：路径与 body 键逐字对齐冻结契约表。"""
        client = _client(_ok({"batchId": "b1", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=PRICE_ITEMS)
        assert result.success, result.message
        path, kwargs = client.post.call_args.args[0], client.post.call_args.kwargs
        assert path == "/api/admin/agent/batches"
        assert set(kwargs["json_data"]) == {"batchType", "items"}
        assert kwargs["json_data"]["batchType"] == "product_price"
        # ⚠️ wire 字段名 = **服务端实测真值**：改价批次的 field 是 `basePrice`
        # （= admin-api `products.base_price` 的 wire 名，与逐条写同名字段），不是 `price`。
        assert kwargs["json_data"]["items"] == [
            {"resourceId": "prod_eval_blackout", "field": "basePrice", "oldValue": 168, "newValue": 155},
            {"resourceId": "prod_eval_dark_green", "field": "basePrice", "oldValue": 128, "newValue": 155},
        ]
        # 租户 / 用户上下文必须随请求下发（多租户隔离，与其余工具同款）
        assert kwargs["tenant_id"] == 1 and kwargs["user_id"] == "u1"
        assert result.data["batchId"] == "b1"

    @pytest.mark.asyncio
    async def test_price_field_alias_is_normalized_to_wire_name(self, tool):
        """模型把改价字段写成 `price` 时**收下并归一成 `basePrice`**（别名 ≠ 放行错字段）。"""
        client = _client(_ok({"batchId": "b1", "itemCount": 1, "status": "preview"}))
        items = [{"resourceId": "p1", "field": "price", "oldValue": 168, "newValue": 155}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=items)
        assert result.success, result.message
        assert client.post.call_args.kwargs["json_data"]["items"][0]["field"] == "basePrice"

    @pytest.mark.asyncio
    async def test_preview_returns_per_item_before_after_rows(self, tool):
        """逐条「改前 → 改后」必须**逐条**可判（验收判据 1）：每条一个字段行组 + 扁平卡字段。"""
        client = _client(_ok({"batchId": "b1", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=PRICE_ITEMS)
        rows = result.data["preview"]
        assert [r["resourceId"] for r in rows] == ["prod_eval_blackout", "prod_eval_dark_green"]
        for row, item in zip(rows, PRICE_ITEMS):
            assert [f["label"] for f in row["fields"]] == ["商品ID", "改前价", "改后价"]
            assert row["fields"][1]["value"] == str(item["oldValue"])
            assert row["fields"][2]["value"] == str(item["newValue"])
        # 扁平字段 = 逐条字段的拼接（LLM 直接把它交给 interact(component=confirm, fields=…)）
        assert result.data["fields"] == [f for r in rows for f in r["fields"]]

    @pytest.mark.asyncio
    async def test_preview_rows_come_from_confirm_value_single_source(self, tool):
        """字段投影**只此一处**：预览行必须逐字等于 `confirm_value.confirm_card_fields` 的产出。"""
        client = _client(_ok({"batchId": "b1", "itemCount": 1, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=PRICE_ITEMS[:1])
        expected = confirm_value.confirm_card_fields(
            {"product_id": "prod_eval_blackout", "before_price": 168, "price": 155})
        assert result.data["preview"][0]["fields"] == expected

    @pytest.mark.asyncio
    async def test_status_batch_type_is_rejected(self, tool):
        """上下架按裁定 A 不做：`product_status` 必须被判 `batch_type_unsupported` 且不发请求。"""
        client = _client(_ok({"batchId": "b2"}))
        items = [{"resourceId": "p1", "field": "status",
                  "oldValue": "on_sale", "newValue": "off_sale"}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type="product_status", items=items)
        assert result.success is False
        assert result.error == "batch_type_unsupported"
        assert "product_status" not in (result.suggestion or "")
        assert "上下架" in (result.suggestion or "") or "上下架" in (result.message or "")
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_message_asks_for_confirm_card(self, tool):
        """话术必须把「下一步发确认卡」讲清楚（否则模型拿到 batchId 直接 execute）。"""
        client = _client(_ok({"batchId": "b1", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=PRICE_ITEMS)
        assert "确认" in (result.message or "")
        assert "改前" in (result.message or "") and "改后" in (result.message or "")
        assert result.summary and "批量" in result.summary


# ══════════════════════════════════════════════════════════════════════════════
# 一点五、第三个具名批量 `inventory_stock`（issue #5950 库存调整）
# ══════════════════════════════════════════════════════════════════════════════
# 为什么复用同一工具而不是新造第二个批量工具：服务端是**同一个批次资源**
# （`/api/admin/agent/batches` 的四端点 + 同一状态机 + 同一 `revertible`），批量语义由
# `batchType` 声明 ⇒ 新造工具 = 把同一份两段确认 / 阈值 / 撤销逻辑抄第二份（必然漂移）。
# 红证 = 本类「字段配对 / 改前值 / before → after 投影」三条 + `test_only_three_batch_types_are_declared`。


class TestInventoryStockBatch:
    @pytest.mark.asyncio
    async def test_preview_posts_inventory_stock_batch_type(self, tool):
        """库存批量与改价批量**走同一端点、同一契约**（payload 的 field 归一成 `stock`）。"""
        client = _client(_ok({"batchId": "b-stock", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_STOCK, items=STOCK_ITEMS)
        assert result.success is True
        args, kwargs = client.post.await_args.args, client.post.await_args.kwargs
        assert args[0] == "/api/admin/agent/batches"
        body = kwargs["json_data"]
        assert body["batchType"] == "inventory_stock"
        assert [it["field"] for it in body["items"]] == ["stock", "stock"]
        assert [it["oldValue"] for it in body["items"]] == [1000, 800]

    def test_field_of_the_stock_batch_type_is_stock(self, tool):
        """字段配对（`_FIELD_OF_BATCH_TYPE`）：库存在场时 field 必须是 `stock`。

        为什么单列一条：字段词与 `batchType` 必须配对是服务端的硬前提
        （`AgentBatchService.TYPE_FIELD` 不配对直接 422）；工具侧漏了这一格 ⇒
        每次 preview 都白烧一轮。
        """
        from app.tools.product_batch_update import _FIELD_OF_BATCH_TYPE
        assert _FIELD_OF_BATCH_TYPE[BATCH_TYPE_STOCK] == "stock"

    @pytest.mark.asyncio
    async def test_stock_item_without_old_value_is_rejected(self, tool):
        """改前库存缺席 ⇒ `batch_preview_required` 且**不发请求**（撤销的唯一依据不许缺）。"""
        client = _client(_ok({"batchId": "b1"}))
        items = [{"resourceId": "prod_eval_blackout", "field": "stock", "newValue": 1200}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_STOCK, items=items)
        assert result.success is False
        assert result.error == "batch_preview_required"
        assert "改前" in result.message
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stock_field_cannot_be_mixed_into_a_price_batch(self, tool):
        """`stock` 条目混进改价批量 ⇒ `batch_field_mismatch`（不许服务端去猜）。"""
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=STOCK_ITEMS)
        assert result.success is False
        assert result.error == "batch_field_mismatch"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stock_preview_rows_are_before_after_via_single_projection(self, tool):
        """逐条「改前库存 → 改后库存」由 `confirm_value.confirm_card_fields` 派生（投影单一源）。"""
        client = _client(_ok({"batchId": "b-stock", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_STOCK, items=STOCK_ITEMS)
        row = result.data["preview"][0]
        expect = confirm_value.confirm_card_fields(
            {"product_id": "prod_eval_blackout", "before_stock": 1000, "stock": 1200})
        assert row["fields"] == expect
        labels = [f["label"] for f in row["fields"]]
        assert "改前库存" in labels and "库存" in labels


# ══════════════════════════════════════════════════════════════════════════════
# 二、阈值：N > 50 拒绝并提示分批（边界双侧；执行/撤销转后台 job 不改变上限）
# ══════════════════════════════════════════════════════════════════════════════


def _n_items(n: int) -> list:
    return [{"resourceId": f"p{i}", "field": "price", "oldValue": 1, "newValue": 2}
            for i in range(n)]


class TestThreshold:
    @pytest.mark.asyncio
    async def test_over_threshold_is_rejected_with_batching_hint(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE,
                                        items=_n_items(MAX_BATCH_ITEMS + 1))
        assert result.success is False
        assert result.error == "batch_too_large"
        assert "分批" in (result.suggestion or "")
        client.post.assert_not_awaited()   # 拒绝就必须**不发请求**（不是发出去再让服务端拒）

    @pytest.mark.asyncio
    async def test_threshold_boundary_is_inclusive(self, tool):
        """边界：恰好 50 条放行（判据是 `> 50`，不是 `>= 50`）。"""
        client = _client(_ok({"batchId": "b1", "itemCount": MAX_BATCH_ITEMS, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE,
                                        items=_n_items(MAX_BATCH_ITEMS))
        assert result.success is True
        assert len(client.post.call_args.kwargs["json_data"]["items"]) == MAX_BATCH_ITEMS


# ══════════════════════════════════════════════════════════════════════════════
# 三、batchType 白名单（两个）+ 入参 fail-closed
# ══════════════════════════════════════════════════════════════════════════════


class TestWhitelistAndInputGuards:
    def test_only_two_batch_types_are_declared(self, tool):
        """白名单只有 `product_price` / `inventory_stock`（通用批量有意不做）。

        （#5950 扩面后曾三条；#7334 裁定 A 移除 `product_status` ⇒ 两条。
        判据形状不变：**闭集**相等，多一个 / 少一个都红。）
        """
        declared = set(tool.parameters["properties"]["batch_type"]["enum"])
        assert declared == {BATCH_TYPE_PRICE, BATCH_TYPE_STOCK}

    def test_enums_are_literals_for_the_static_action_catalog(self, tool):
        """🔴 action / batch_type 的 enum 必须与常量一致**且是字面量列表**。

        为什么专门判：`scripts/case_coverage.py::tool_declared_actions` 的真值源 = 工具源码文本里
        `parameters.properties.action.enum` 的**字面量**（正则取花括号配对后的 `enum`）。
        写成表达式（如 `list(_ACTIONS)`）⇒ 它读到「该工具没有 action 维度」⇒ **用例里任何
        action 声明都被判 `action_dangling`（假红阻塞 CI）** —— 实测踩过。
        """
        props = tool.parameters["properties"]
        assert props["action"]["enum"] == ["preview", "execute", "revert"]
        assert set(props["action"]["enum"]) == set(VALID_ACTIONS)
        assert props["batch_type"]["enum"] == ["product_price", "inventory_stock"]
        assert set(props["batch_type"]["enum"]) == set(BATCH_TYPES)

    @pytest.mark.asyncio
    async def test_unknown_batch_type_is_rejected(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview", batch_type="product_name",
                                        items=PRICE_ITEMS)
        assert result.success is False
        assert result.error == "batch_type_unsupported"
        assert BATCH_TYPE_PRICE in result.suggestion and BATCH_TYPE_STOCK in result.suggestion
        assert "product_status" not in result.suggestion
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_without_items_is_rejected(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=[])
        assert result.success is False and result.error == "batch_items_required"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_price_item_without_old_value_is_rejected(self, tool):
        """`old_value` 是撤销的唯一依据（契约 §三）⇒ 预览阶段就必须采集，缺席一律 fail-closed。"""
        client = _client(_ok({"batchId": "b1"}))
        items = [{"resourceId": "p1", "field": "price", "newValue": 155}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=items)
        assert result.success is False
        assert result.error == "batch_preview_required"
        assert "product_detail" in (result.suggestion or "")
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_item_missing_new_value_is_rejected(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        items = [{"resourceId": "p1", "field": "price", "oldValue": 168}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=items)
        assert result.success is False and result.error == "batch_item_incomplete"
        assert "newValue" in (result.suggestion or "")
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_item_field_must_match_batch_type(self, tool):
        """改价批次里塞 status 字段 = 类别与字段错配 ⇒ 拒绝（不让服务端去猜）。"""
        status_items = [{"resourceId": "p1", "field": "status",
                         "oldValue": "on_sale", "newValue": "off_sale"}]
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview", batch_type=BATCH_TYPE_PRICE,
                                        items=status_items)
        assert result.success is False and result.error == "batch_field_mismatch"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_item_resource_id_is_required(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        items = [{"field": "price", "oldValue": 1, "newValue": 2}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_PRICE, items=items)
        assert result.success is False and result.error == "batch_item_incomplete"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_action_is_rejected(self, tool):
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="do_everything")
        assert result.success is False and result.error == "unsupported_batch_action"
        assert "preview" in (result.suggestion or "")
        client.post.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# 四、两段确认不可跳过：execute / revert 必须带 preview 产生的 batch_id
# ══════════════════════════════════════════════════════════════════════════════


class TestExecuteRequiresPreview:
    @pytest.mark.asyncio
    async def test_execute_without_batch_id_is_rejected(self, tool):
        """🔴 本单核心：没有 preview 的 batchId ⇒ 执行在结构上不可达（禁止跳过预览直接执行）。"""
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute",
                                        batch_type=BATCH_TYPE_PRICE, items=PRICE_ITEMS)
        assert result.success is False
        assert result.error == "batch_preview_required"
        assert "preview" in (result.suggestion or "")
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revert_without_batch_id_is_rejected(self, tool):
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert")
        assert result.success is False and result.error == "batch_preview_required"
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_hits_frozen_endpoint(self, tool):
        client = _client(_ok({"batchId": "b1", "status": "done",
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")
        assert result.success
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b1/execute-async"
        assert result.data["status"] == "done"

    @pytest.mark.asyncio
    async def test_execute_reports_partial_failures_without_rollback(self, tool):
        """验收判据 3：部分失败**逐条报告**，不做整体回滚（回滚会掩盖真问题）。"""
        results = [{"resourceId": "p1", "success": True},
                   {"resourceId": "p2", "success": False, "error": "商品不存在"}]
        client = _client(_ok({"batchId": "b1", "status": "partial", "results": results}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")
        assert result.success
        assert result.data["results"] == results
        # 逐条报告：失败条数进话术（不是笼统的「已完成」）
        assert "失败 1" in (result.message or "") and "成功 1" in (result.message or "")
        assert "不做整体回滚" in (result.message or "")
        called_paths = [c.args[0] for c in client.post.call_args_list]
        assert called_paths == ["/api/admin/agent/batches/b1/execute-async"]   # 不得顺手撤销

    @pytest.mark.asyncio
    async def test_execute_tells_user_it_can_be_reverted(self, tool):
        """撤销入口必须**在话术里可达**（用户不知道能撤销 = 没有撤销）。"""
        client = _client(_ok({"batchId": "b1", "status": "done", "results": []}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")
        assert "撤销" in (result.message or "")
        assert "b1" in (result.message or "")

    @pytest.mark.asyncio
    async def test_execute_does_not_promise_revert_when_server_says_not_revertible(self, tool):
        """`revertible=false` ⇒ 话术**不得**承诺可撤销（服务端真值优先，说了要能做到）。"""
        client = _client(_ok({"batchId": "b1", "status": "failed", "revertible": False,
                              "results": [{"resourceId": "p1", "success": False, "error": "p1: 商品不存在"}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")
        assert "不可撤销" in (result.message or "")
        assert "action=revert" not in (result.message or "")


class TestAsyncPolling:
    """issue #8283：execute/revert 提交后台 job → GET 轮询 → 终态/超时/查询失败三态。"""

    @pytest.mark.asyncio
    async def test_execute_polls_until_done_and_maps_items(self, tool, monkeypatch):
        import app.tools.product_batch_update as pbu
        monkeypatch.setattr(pbu, "POLL_TIMEOUT_SECONDS", 1.0)
        monkeypatch.setattr(pbu, "POLL_INTERVAL_SECONDS", 0)
        get_return = _ok({
            "batchId": "b1", "status": "done", "successCount": 1, "failCount": 0,
            "revertible": True,
            "items": [{"resourceId": "p1", "field": "basePrice",
                       "oldValue": "10.00", "newValue": "12.00", "status": "success"}],
        })
        client = _client(_ok({"batchId": "b1", "status": "executing"}), get_return)
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")

        assert result.success
        assert client.get.call_args.args[0] == "/api/admin/agent/batches/b1"
        assert result.data["status"] == "done"
        assert result.data["results"][0]["success"] is True
        assert "成功 1" in (result.message or "") and "失败 0" in (result.message or "")

    @pytest.mark.asyncio
    async def test_execute_timeout_reports_unfinished_not_completed(self, tool, monkeypatch):
        import app.tools.product_batch_update as pbu
        monkeypatch.setattr(pbu, "POLL_TIMEOUT_SECONDS", 0)
        client = _client(_ok({"batchId": "b1", "status": "executing"}),
                         _ok({"batchId": "b1", "status": "executing", "items": []}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")

        assert result.success is True
        assert "尚未完成" in (result.message or "")
        assert "批量执行完成" not in (result.message or "")
        assert result.data["status"] == "executing"

    @pytest.mark.asyncio
    async def test_execute_status_query_failure_is_not_reported_as_submit_failure(self, tool, monkeypatch):
        import app.tools.product_batch_update as pbu
        monkeypatch.setattr(pbu, "POLL_TIMEOUT_SECONDS", 0)
        client = _client(_ok({"batchId": "b1", "status": "executing"}),
                         {"success": False, "error": {"message": "progress unavailable"}})
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")

        assert result.success is True
        assert "查询进度失败" in (result.message or "")
        assert "批量执行提交失败" not in (result.message or "")
        assert result.data["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_revert_polls_until_reverted(self, tool, monkeypatch):
        import app.tools.product_batch_update as pbu
        monkeypatch.setattr(pbu, "POLL_TIMEOUT_SECONDS", 1.0)
        monkeypatch.setattr(pbu, "POLL_INTERVAL_SECONDS", 0)
        get_return = _ok({
            "batchId": "b1", "status": "reverted", "revertible": False,
            "items": [{"resourceId": "p1", "status": "reverted"}],
        })
        client = _client(_ok({"batchId": "b1", "status": "executing"}), get_return)
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id="b1")

        assert result.success
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b1/revert-async"
        assert client.get.call_args.args[0] == "/api/admin/agent/batches/b1"
        assert result.data["status"] == "reverted"
        assert "还原" in (result.message or "")


# ══════════════════════════════════════════════════════════════════════════════
# 五、撤销：逐条还原 old_value
# ══════════════════════════════════════════════════════════════════════════════


class TestRevert:
    @pytest.mark.asyncio
    async def test_revert_hits_frozen_endpoint(self, tool):
        client = _client(_ok({"batchId": "b1", "status": "reverted",
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id="b1")
        assert result.success
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b1/revert-async"
        assert result.data["status"] == "reverted"

    @pytest.mark.asyncio
    async def test_revert_message_says_values_are_restored(self, tool):
        client = _client(_ok({"batchId": "b1", "status": "reverted",
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id="b1")
        assert "还原" in (result.message or "")

    @pytest.mark.asyncio
    async def test_revert_separates_skipped_from_restored(self, tool):
        """执行时本就失败的条目在撤销时报 `skipped` ⇒ 不得混进「还原成功 N 条」。"""
        results = [{"resourceId": "p1", "success": True, "status": "reverted"},
                   {"resourceId": "p2", "success": True, "status": "skipped"}]
        client = _client(_ok({"batchId": "b1", "status": "reverted", "revertible": False,
                              "results": results}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id="b1")
        assert "成功 2 条" in (result.message or "")
        assert "1 条是执行时本来就失败的条目" in (result.message or "")

    @pytest.mark.asyncio
    async def test_revert_failure_is_not_silent(self, tool):
        """不可撤销 / 状态不允许 ⇒ 失败必须带可执行建议（不许静默成功）。"""
        client = _client({"success": False, "error": {"code": "BATCH_NOT_REVERTABLE",
                                                     "message": "该批次不可撤销"},
                          "suggestion": "只读查询该批次状态后再决定"})
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id="b1")
        assert result.success is False
        assert result.error_code == "BATCH_NOT_REVERTABLE"
        assert "只读查询该批次状态" in (result.suggestion or "")


# ══════════════════════════════════════════════════════════════════════════════
# 六、权限 / 标注 / description 契约 / 接线
# ══════════════════════════════════════════════════════════════════════════════


class TestPermissionAndAnnotations:
    @pytest.mark.asyncio
    async def test_without_product_write_code_is_denied_and_not_retryable(self, tool):
        """权限码与逐条写**同码**（`product:create`）：无码者一律拒，且码 ∈ 不可重试集合。"""
        from app.tools.base import NON_RETRYABLE_ERROR_CODES
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(permissions=["product:list"]),
                                        action="preview", batch_type=BATCH_TYPE_PRICE,
                                        items=PRICE_ITEMS)
        assert result.success is False
        assert result.error_code in NON_RETRYABLE_ERROR_CODES
        client.post.assert_not_awaited()

    def test_permission_code_matches_single_item_write(self, tool):
        """契约 §三：与逐条写同码，**不新开权限面**。"""
        from app.tools.product_update import ProductUpdateTool
        assert tool.required_permissions == ProductUpdateTool().required_permissions == ["product:create"]
        assert not tool.allowed_roles or tool.allowed_roles == ["customer", "admin", "agent", "tenant_admin"]

    def test_write_annotations_are_explicit(self, tool):
        """写工具必须显式表态（#3594 确认门禁 + #3564 幂等性静态锁 + A 档入册判据）。"""
        assert tool.read_only is False
        assert tool.requires_confirmation is True
        assert tool.destructive is False
        # 绝对目标值 ⇒ 重放收敛（与 product_update 同口径）；A 档入册判据要求 `WRITE|IDEMPOTENT`
        assert tool.idempotent is True

    def test_only_preview_is_exempt_from_the_confirm_gate(self, tool):
        """🔴 两段确认的门禁分布：preview 免确认（否则第一段之后死锁），execute/revert 仍须确认。

        判据本体在 `base_skill._requires_confirmation`：`read_only_actions` 是**唯一**豁免口，
        而第二段确认卡的材料只能由 preview 产出 ⇒ preview 必须豁免；execute/revert 是真正的
        商品写入 ⇒ 必须留在门禁内，且（issue #5317，涉钱面）**只认卡值** —— 文本确认不放行。
        """
        from app.graph.skills.base_skill import _requires_confirmation
        assert set(tool.read_only_actions) == {"preview"}
        assert set(tool.read_only_actions) <= set(VALID_ACTIONS)
        # 第一段勾选卡回传的文本不是「明确确认」⇒ preview 必须免门禁，否则死锁
        selection_msg = "已选商品：遮光窗帘、北欧风窗帘"
        assert _requires_confirmation(tool, {"action": "preview"}, selection_msg) is False
        assert _requires_confirmation(tool, {"action": "execute"}, selection_msg) is True
        assert _requires_confirmation(tool, {"action": "revert"}, selection_msg) is True
        # 涉钱面（issue #5317 裁定）：execute/revert **只认卡值** —— 文本「确认」不再放行，
        # 放行链只剩 `_is_card_confirm_value`（用户消息逐字等于系统自产的卡值 = 真的点了卡）。
        # 判据本体见 tests/test_price_card_only_confirm.py。
        assert _requires_confirmation(tool, {"action": "execute"}, "确认批量改价 2 条") is True
        assert _requires_confirmation(tool, {"action": "revert"}, "确认") is True

    def test_description_answers_the_three_questions(self, tool):
        """设计范式（docs/wiki/agent-design-standard.md）：何时用 / 前置 / 与相似工具的区别。"""
        d = tool.description
        assert "【触发】" in d and "【前置" in d and "【反例】" in d
        # 与相似工具的区别**必须点名** product_update（单条）与 interact（两段确认的载体）
        assert "product_update" in d
        assert "interact" in d and "multiSelect" in d
        assert "50" in d
        assert "撤销" in d

    def test_description_does_not_advertise_status(self, tool):
        """裁定 A：描述不得再把「批量下架」当触发词 / 不得出现状态取值（工具面也不接受）。"""
        d = tool.description
        assert "这批全部下架" not in d
        assert "product_status" not in d
        assert "on_sale" not in d and "off_sale" not in d
        assert "上下架" in d  # 只允许作为「不在能力内」的显式拒绝出现


class TestWiring:
    def test_registered_and_exported(self):
        from app.tools import ProductBatchUpdateTool as Exported
        from app.tools.registry import get_tool_registry
        assert Exported is ProductBatchUpdateTool
        assert "product_batch_update" in get_tool_registry()

    def test_inventory_stock_channel_is_reachable_and_documented(self):
        """第三个具名批量对模型**可达且被讲清**（issue #5950）。

        两半缺一不可：① 工具 schema 的 `batch_type` enum（模型唯一能看到的取值面）；
        ② `product` skill 的提示词（模型据此知道该走两段确认 + 可撤销）。
        只改一半 ⇒ 能力存在但模型不会用（= 交付了等于没交付）。
        """
        from app.graph.skills.product_skill import PRODUCT_SKILL_CONFIG, PRODUCT_SYSTEM_PROMPT
        from app.tools.product_batch_update import ProductBatchUpdateTool as Tool
        assert "inventory_stock" in Tool.parameters["properties"]["batch_type"]["enum"]
        assert "inventory_stock" in PRODUCT_SYSTEM_PROMPT
        assert "stock" in PRODUCT_SYSTEM_PROMPT
        # 前置条件必须被讲清（否则模型会把服务端拒绝当"再来一次"，白烧轮次）
        desc = ProductBatchUpdateTool.description
        assert "各规格库存一致" in desc and "各规格库存一致" in PRODUCT_SYSTEM_PROMPT
        assert "product_batch_update" in PRODUCT_SKILL_CONFIG.tool_names

    def test_bound_to_product_skill_with_two_stage_prompt(self):
        """绑定 B 端商品 skill，且 prompt 讲清两段确认 / 阈值 / 撤销 / 白名单。"""
        from app.graph.skills.product_skill import PRODUCT_SKILL_CONFIG, PRODUCT_SYSTEM_PROMPT
        assert "product_batch_update" in PRODUCT_SKILL_CONFIG.tool_names
        assert "product_batch_update" in PRODUCT_SYSTEM_PROMPT
        assert "multiSelect" in PRODUCT_SYSTEM_PROMPT
        assert "product_price" in PRODUCT_SYSTEM_PROMPT
        assert "product_status" not in PRODUCT_SYSTEM_PROMPT
        assert "上下架" in PRODUCT_SYSTEM_PROMPT
        assert "撤销" in PRODUCT_SYSTEM_PROMPT
        assert "50" in PRODUCT_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# 六、issue #6998：撤销段的 `batch_id` 兜底 —— execute / revert **同一个**解析函数
# ══════════════════════════════════════════════════════════════════════════════
# 病（真 LLM 重放 `PR-108`）：R3 执行成功、批次号就在上下文里，R5 撤销却**丢了**
# `batch_id`（`product_batch_update{"action":"revert"}`）；修前那一次则**编造**批次号
# （`batch_20260923_155` ⇒ 服务端 NOT_FOUND）。两条路都通向「撤销要么永不成功、
# 要么打到错的批次」。修法 = 把「这一批是哪个」抽成**一处**解析：
#   ① 显式给了 ⇒ 原样用；② 没给 ⇒ 只认本会话台账里**恰好一个**候选；③ 否则 fail-closed。

#: `app/tools/` 目录（类级登记册的扫描面 —— 现取，不写死清单）。
TOOLS_DIR = Path(product_batch_update.__file__).resolve().parent

#: 类级登记册：`app/tools/**` 里 `parameters` 字面量声明了 `batch_id` 的工具文件 →
#: 它的 `batch_id` 解析入口。**未登记即红**（第三条批量路径不许各写一份解析）。
BATCH_ID_SCHEMA_OWNERS = {
    "product_batch_update.py": "ProductBatchUpdateTool.resolve_batch_id",
}

#: 共享解析器的**全仓唯一**锚（新增批量路径只能复用这一处）。
SHARED_BATCH_ID_RESOLVER = "ProductBatchUpdateTool.resolve_batch_id"


def _ledger_state(*batch_ids, kind="executed"):
    """会话状态替身：批次台账里有这几条记录（最近写入在前 = 参数顺序）。"""
    return {product_batch_update.BATCH_LEDGER_KEY:
            [{"batch_id": b, "kind": kind} for b in batch_ids]}


@pytest.fixture(autouse=True)
def _session_state_store(monkeypatch):
    """单测**不连库**：把会话工作状态（PG `session_states`）的**存储层**换成替身。

    为什么替的是存储层、而不是本模块那两个包装函数（issue #6998）：包装函数必须被**真的**
    执行，否则「台账确实落在会话工作状态里」这条**接线判据**就测不到（§28.2：判据本体绿 ≠ 接线在）。
    为什么 autouse：`revert` 的缺省批次号来自会话台账 ⇒ 本文件**全部**用例在「执行成功」这条
    路径上都会经过一次台账写入；真连库既慢又会把单测绑到云 dev 库。
    """
    store = MagicMock()
    store.load = AsyncMock(return_value=None)
    store.commit = AsyncMock(return_value=True)
    monkeypatch.setattr("app.memory.session_state_store.SessionStateStore",
                        lambda *a, **k: store)
    return store


class TestRevertBatchIdFallback:
    """issue #6998 的实例判据：撤销**不许猜批次**。"""

    @pytest.mark.asyncio
    async def test_revert_without_batch_id_is_governed_by_the_context_candidate(
            self, tool, _session_state_store):
        """① 缺 `batch_id` 时**只由上下文候选决定**：取不到 ⇒ 拒绝 + 可行动提示；唯一 ⇒ 采用那一批。

        两半必须在**同一个用例**里（本单的红证口径）：把兜底整段摘掉 ⇒ 下半段必红；
        把「唯一」放宽成「取第一个」⇒ ③ 必红 —— 只留任何一半都证明不了这条口径。
        """
        # ── 上半：上下文里什么都没有 ⇒ fail-closed 拒绝，且**不发任何请求** ──
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            denied = await tool.execute(_ctx(), action="revert")
        assert denied.success is False
        # 沿用既有契约码（`.github/cases` 判据③ 的同一读数），语义收窄成「也没有可用的唯一批次」
        assert denied.error == "batch_preview_required"
        assert denied.missing_params == ["batch_id"]        # 结构化缺参（#4080 T3）
        assert "本会话" in (denied.message or "") and "唯一" in (denied.message or "")
        suggestion = denied.suggestion or ""
        assert "batch_id" in suggestion                     # 说出「缺什么」
        assert "不要凭空编造" in suggestion                   # 明确禁止猜
        assert "确认" in suggestion                          # 取不到时的真出口 = 问商家
        client.post.assert_not_awaited()

        # ── 下半：本会话**恰好一个**执行成功的批次 ⇒ 撤销它（`PR-108` R5 无参 revert 的正解）──
        _session_state_store.load.return_value = _ledger_state("b-real")
        client = _client(_ok({"batchId": "b-real", "status": "reverted",
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert")
        assert result.success, result.message
        # 撤回的是**真实执行过的那一批**，不是模型自报的号
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b-real/revert-async"
        assert result.data["batchId"] == "b-real"
        # 话术要点明批次号**来自本会话上下文**（下一轮模型就知道该带什么）
        assert "上下文" in (result.message or "")

    @pytest.mark.asyncio
    async def test_revert_refuses_to_pick_among_multiple_candidates(self, tool, _session_state_store):
        """③ 有**多个**候选批次 ⇒ 拒绝，而不是挑「最近的那一个」（本单最容易写错的地方）。"""
        _session_state_store.load.return_value = _ledger_state("b-late", "b-earlier")
        # 终止态替身：万一将来退化成"挑一个"，本用例要**立刻**红，而不是等轮询超时（60s）
        client = _client(_ok({"status": "reverted"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert")
        assert result.success is False
        assert result.error == "batch_id_ambiguous"
        assert "b-late" in (result.message or "") and "b-earlier" in (result.message or "")
        assert "2" in (result.message or "")            # 候选条数要报出来
        assert result.missing_params == ["batch_id"]
        assert "不要替商家挑" in (result.suggestion or "")
        client.post.assert_not_awaited()                 # 🔴 一个请求都不发

    @pytest.mark.asyncio
    async def test_revert_with_explicit_batch_id_wins_over_context(self, tool, _session_state_store):
        """② 负控：显式 `batch_id` **原样**使用（上下文里有别的候选也不改写、不拒绝）。"""
        _session_state_store.load.return_value = _ledger_state("b-other")
        client = _client(_ok({"batchId": "b-explicit", "status": "reverted",
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="revert", batch_id=" b-explicit ")
        assert result.success, result.message
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b-explicit/revert-async"
        # 显式值不触发兜底 ⇒ 话术里不出现「取自上下文」的说明
        assert "上下文" not in (result.message or "")
        _session_state_store.load.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_still_requires_an_explicit_batch_id(self, tool, _session_state_store):
        """执行**不吃**上下文兜底：`batch_id` 只能来自 preview（两段确认的结构锁不变）。"""
        _session_state_store.load.return_value = _ledger_state("b-executed")
        client = _client(_ok({}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute")
        assert result.success is False and result.error == "batch_preview_required"
        assert "preview" in (result.suggestion or "")
        client.post.assert_not_awaited()
        _session_state_store.load.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_records_the_batch_for_the_later_revert(self, tool, _session_state_store):
        """写侧：执行成功后**记下真实批次号**（撤销兜底的唯一来源）。"""
        client = _client(_ok({"batchId": "b1", "status": "done", "revertible": True,
                              "results": [{"resourceId": "p1", "success": True}]}))
        # 会话里**已有**别的字段：台账写入必须是**增量**，不许把状态覆盖成只剩台账
        _session_state_store.load.return_value = {"last_confirm_value": "确认批量改价"}
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="execute", batch_id="b1")
        assert result.success, result.message
        # 接线判据：真的写进**会话工作状态**（`session_states`）—— 会话键正确、别的字段原样保留
        session_id, state = _session_state_store.commit.await_args.args
        assert session_id == "s1"
        assert state[product_batch_update.BATCH_LEDGER_KEY] == [
            {"batch_id": "b1", "kind": "executed"}]
        assert state["last_confirm_value"] == "确认批量改价"

    @pytest.mark.asyncio
    async def test_execute_does_not_record_a_batch_the_server_says_is_not_revertible(
            self, tool, _session_state_store):
        """`revertible=false` 的批次**不进**撤销候选（否则「撤销」会去打一个撤不了的批次）。"""
        client = _client(_ok({"batchId": "b1", "status": "done", "revertible": False,
                              "results": [{"resourceId": "p1", "success": True}]}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            await tool.execute(_ctx(), action="execute", batch_id="b1")
        _session_state_store.commit.assert_not_awaited()


class TestSharedBatchIdResolver:
    """④ 类级固化：`execute` 与 `revert` 必须调**同一个**解析函数，且第三条路进不来。"""

    def test_execute_and_revert_call_the_same_resolver(self):
        for method in ("_execute_batch", "_revert_batch"):
            assert "resolve_batch_id" in _called_attribute_names(ProductBatchUpdateTool, method), (
                f"{method} 没有走共享的 batch_id 解析器（各写一份 = 下一个撤销路径又会漏）")
        # 全模块只许有**一处**定义（第二份实现 ⇒ 红）
        source = (TOOLS_DIR / "product_batch_update.py").read_text(encoding="utf-8")
        assert source.count("async def resolve_batch_id(") == 1

    def test_resolver_is_the_declared_single_anchor(self):
        assert SHARED_BATCH_ID_RESOLVER == "ProductBatchUpdateTool.resolve_batch_id"
        assert inspect.iscoroutinefunction(ProductBatchUpdateTool.resolve_batch_id)
        # 兜底只许发生在 `revert` 一侧：`execute` 的结构锁不许被兜底打穿
        assert set(product_batch_update.CONTEXT_FALLBACK_ACTIONS) == {"revert"}

    def test_every_tool_declaring_batch_id_is_registered(self):
        """**未登记即红**：新工具把 `batch_id` 写进 `parameters` 而没登记 ⇒ 第三条路又漏了。"""
        scanned = _tools_declaring_batch_id()
        unregistered = sorted(set(scanned) - set(BATCH_ID_SCHEMA_OWNERS))
        assert not unregistered, (
            f"这些工具声明了 `batch_id` 但没登记到 BATCH_ID_SCHEMA_OWNERS：{unregistered}"
            " —— 请复用 `ProductBatchUpdateTool.resolve_batch_id`（同一套口径）后再登记")
        for filename, resolver in BATCH_ID_SCHEMA_OWNERS.items():
            assert resolver == SHARED_BATCH_ID_RESOLVER
            assert "resolve_batch_id" in (TOOLS_DIR / filename).read_text(encoding="utf-8")


def _called_attribute_names(cls, method):
    """某方法体里**实际调用**过的属性名集合（AST 判据 —— 不是"文本里出现过"）。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(cls, method))))
    return {node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}


def _tools_declaring_batch_id():
    """现取：`app/tools/*.py` 里 `parameters` 字面量含 `batch_id` 的 `{文件名: 类名}`。"""
    found = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:      # 语法坏掉的模块由别的判据负责，这里不重复报
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                if not any(isinstance(t, ast.Name) and t.id == "parameters" for t in item.targets):
                    continue
                if "batch_id" in (ast.get_source_segment(source, item.value) or ""):
                    found[path.name] = node.name
    return found