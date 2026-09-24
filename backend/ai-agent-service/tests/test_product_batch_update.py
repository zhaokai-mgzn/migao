# case_ids: PR-108, PR-109
"""`product_batch_update` 批量更新的 Agent 能力 — 契约 / 两段确认 / 阈值 / 撤销（issue #5314）

被测对象 = issue #5314 冻结契约（评论「批量更新能力 —— 设计 + 冻结契约（2026-09-24）」）
的 **Agent 侧一半**（服务端 `/api/admin/agent/batches` 由另一个包实现，本文件按契约编码，
**不依赖服务端存在**：HTTP 客户端全程替身）。

本文件锁的不变式（每条都能单独变红）：

1. **契约面**：preview → `POST /api/admin/agent/batches`，body `{batchType, items:[{resourceId,
   field, oldValue, newValue}]}`（camelCase，逐字对齐契约表）；execute/revert →
   `POST /api/admin/agent/batches/{batchId}/{execute,revert}`。
2. **两段确认不可跳过**（本单核心交互）：
   · 第一段 = `interact(multiSelect=true)` 让商家勾选集合（**改哪些**）；
   · 第二段 = `interact(confirm)` 逐条「改前 → 改后」预览（**改成什么**）；
   · 机器判据：`action=execute/revert` **必须**带 `batch_id`，而它只能由 `action=preview`
     产生 ⇒ 「没预览就执行」在结构上不可达（不是靠 prompt 自律）。
3. **逐条 before → after 的字段投影只此一处**：预览行由 `app/tools/confirm_value.py`
   派生（`confirm_card_fields`），**不新立第二份字段投影**（#5303 的同一套单一源）。
4. **阈值**：`N > 50` ⇒ 拒绝并提示分批（不做后台任务）；`N == 50` 放行（边界双侧）。
5. **batchType 白名单只有两个**：`product_price` / `product_status`（通用批量不做）。
6. **撤销入口可用**：`revert` 逐条还原 `old_value`，且执行成功的话术里就告诉用户「可以撤销」。
7. **部分失败逐条报告，不做整体回滚**（回滚会掩盖真问题）。
8. 权限码与逐条写**同码**（`product:create`，= `product_update` 的写码）。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools import confirm_value
from app.tools.base import ToolContext
from app.tools.product_batch_update import (
    BATCH_TYPE_PRICE,
    BATCH_TYPE_STATUS,
    BATCH_TYPES,
    MAX_BATCH_ITEMS,
    VALID_ACTIONS,
    ProductBatchUpdateTool,
)

PRICE_ITEMS = [
    {"resourceId": "prod_eval_blackout", "field": "price", "oldValue": 168, "newValue": 155},
    {"resourceId": "prod_eval_dark_green", "field": "price", "oldValue": 128, "newValue": 155},
]
STATUS_ITEMS = [
    {"resourceId": "prod_eval_blackout", "field": "status", "oldValue": "on_sale", "newValue": "off_sale"},
    {"resourceId": "prod_eval_dark_green", "field": "status", "oldValue": "on_sale", "newValue": "off_sale"},
]


def _ctx(permissions=("*",), role="admin") -> ToolContext:
    """商户上下文：权限码按 JWT `permissions` claim 判定（#4106 F3）。"""
    return ToolContext(tenant_id=1, user_id="u1", role=role,
                       permissions=list(permissions), session_id="s1")


def _client(post_return):
    """替身 admin-api 客户端（`post` 是唯一被本工具使用的动词）。"""
    client = MagicMock()
    client.post = AsyncMock(return_value=post_return)
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
    async def test_status_batch_shows_before_and_after_status(self, tool):
        """`product_status` 的预览同样成对（改前状态 → 改后状态），口径来自同一模块。"""
        client = _client(_ok({"batchId": "b2", "itemCount": 2, "status": "preview"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_STATUS, items=STATUS_ITEMS)
        fields = result.data["preview"][0]["fields"]
        assert [f["label"] for f in fields] == ["商品ID", "改前状态", "改后状态"]
        assert [f["value"] for f in fields] == ["prod_eval_blackout", "on_sale", "off_sale"]

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
# 二、阈值：N > 50 拒绝并提示分批（边界双侧；不做后台任务）
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
# 三、batchType 白名单（只有两个）+ 入参 fail-closed
# ══════════════════════════════════════════════════════════════════════════════


class TestWhitelistAndInputGuards:
    def test_only_two_batch_types_are_declared(self, tool):
        """白名单只有 `product_price` / `product_status`（通用批量有意不做）。"""
        declared = set(tool.parameters["properties"]["batch_type"]["enum"])
        assert declared == {BATCH_TYPE_PRICE, BATCH_TYPE_STATUS}

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
        assert props["batch_type"]["enum"] == ["product_price", "product_status"]
        assert set(props["batch_type"]["enum"]) == set(BATCH_TYPES)

    @pytest.mark.asyncio
    async def test_unknown_batch_type_is_rejected(self, tool):
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview", batch_type="product_name",
                                        items=PRICE_ITEMS)
        assert result.success is False
        assert result.error == "batch_type_unsupported"
        assert BATCH_TYPE_PRICE in result.suggestion and BATCH_TYPE_STATUS in result.suggestion
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
    async def test_status_item_without_old_value_is_rejected(self, tool):
        """`product_status` 同样必须带改前状态（撤销依据与预览的另一半，不是价格专属）。"""
        client = _client(_ok({"batchId": "b1"}))
        items = [{"resourceId": "p1", "field": "status", "newValue": "off_sale"}]
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview",
                                        batch_type=BATCH_TYPE_STATUS, items=items)
        assert result.success is False and result.error == "batch_preview_required"
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
        client = _client(_ok({"batchId": "b1"}))
        with patch("app.tools.product_batch_update.get_admin_api_client", return_value=client):
            result = await tool.execute(_ctx(), action="preview", batch_type=BATCH_TYPE_PRICE,
                                        items=STATUS_ITEMS)
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
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b1/execute"
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
        assert called_paths == ["/api/admin/agent/batches/b1/execute"]   # 不得顺手撤销

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
        assert client.post.call_args.args[0] == "/api/admin/agent/batches/b1/revert"
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
        商品写入 ⇒ 必须留在门禁内（用户点卡才放行）。
        """
        from app.graph.skills.base_skill import _requires_confirmation
        assert set(tool.read_only_actions) == {"preview"}
        assert set(tool.read_only_actions) <= set(VALID_ACTIONS)
        # 第一段勾选卡回传的文本不是「明确确认」⇒ preview 必须免门禁，否则死锁
        selection_msg = "已选商品：遮光窗帘、北欧风窗帘"
        assert _requires_confirmation(tool, {"action": "preview"}, selection_msg) is False
        assert _requires_confirmation(tool, {"action": "execute"}, selection_msg) is True
        assert _requires_confirmation(tool, {"action": "revert"}, selection_msg) is True
        # 用户点了确认卡（confirmValue 前缀确认词）⇒ 执行放行
        assert _requires_confirmation(tool, {"action": "execute"}, "确认批量改价 2 条") is False

    def test_description_answers_the_three_questions(self, tool):
        """设计范式（docs/wiki/agent-design-standard.md）：何时用 / 前置 / 与相似工具的区别。"""
        d = tool.description
        assert "【触发】" in d and "【前置" in d and "【反例】" in d
        # 与相似工具的区别**必须点名** product_update（单条）与 interact（两段确认的载体）
        assert "product_update" in d
        assert "interact" in d and "multiSelect" in d
        assert "50" in d
        assert "撤销" in d


class TestWiring:
    def test_registered_and_exported(self):
        from app.tools import ProductBatchUpdateTool as Exported
        from app.tools.registry import get_tool_registry
        assert Exported is ProductBatchUpdateTool
        assert "product_batch_update" in get_tool_registry()

    def test_bound_to_product_skill_with_two_stage_prompt(self):
        """绑定 B 端商品 skill，且 prompt 讲清两段确认 / 阈值 / 撤销 / 白名单。"""
        from app.graph.skills.product_skill import PRODUCT_SKILL_CONFIG, PRODUCT_SYSTEM_PROMPT
        assert "product_batch_update" in PRODUCT_SKILL_CONFIG.tool_names
        assert "product_batch_update" in PRODUCT_SYSTEM_PROMPT
        assert "multiSelect" in PRODUCT_SYSTEM_PROMPT
        assert "product_price" in PRODUCT_SYSTEM_PROMPT
        assert "product_status" in PRODUCT_SYSTEM_PROMPT
        assert "撤销" in PRODUCT_SYSTEM_PROMPT
        assert "50" in PRODUCT_SYSTEM_PROMPT