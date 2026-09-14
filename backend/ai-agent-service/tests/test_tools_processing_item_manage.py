"""ProcessingItemManageTool 单元测试 — 加工项/加工分类 CRUD + 价格计算。"""
# case_ids: PP-002, PP-003, PP-004, PP-006
import ast
import inspect
import re
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import ToolContext
from app.tools.processing_item_manage import VALID_ACTIONS, ProcessingItemManageTool


@pytest.fixture
def tool():
    return ProcessingItemManageTool()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client


# ========== issue #3584：update_item 全量替换契约 ==========
# admin-api `ProcessingItemUpdateRequest` 为**全量替换语义**（name/categoryId/pricingMethod
# @NotBlank + unitPrice @NotNull），PUT 缺任一必填字段 → Bean Validation → 422。
# 因此工具必须先 GET 详情 → merge → PUT 全量；「只改一个字段」不能把其它字段清空。
ITEM_DETAIL = {
    "id": "pi-1",
    "name": "打孔",
    "categoryId": "c1",
    "categoryName": "打孔加工",
    "pricingMethod": "per_meter",
    "unitPrice": 5.0,
    "unit": "米",
    "minQuantity": 1,
    "maxQuantity": 100,
    "description": "旧描述",
    "options": [{"name": "孔径", "values": ["10mm"]}],
    "applicableProductCategories": ["cat-1"],
    "processingDays": 2,
    "aiRecommended": False,
    "status": "active",
}
# DTO 上的四个必填字段（缺一即 422）
REQUIRED_DTO_FIELDS = ("name", "categoryId", "pricingMethod", "unitPrice")


def _detail_response(data: dict = None):
    return {"success": True, "data": dict(ITEM_DETAIL if data is None else data)}


@pytest.fixture
def item_client():
    """GET 详情可用（返回存量加工项）的 admin-api mock 客户端。"""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_detail_response())
    client.post = AsyncMock()
    client.put = AsyncMock(return_value={"success": True, "data": dict(ITEM_DETAIL)})
    client.delete = AsyncMock()
    return client


def _put_body(client) -> Dict[str, object]:
    return client.put.call_args[1]["json_data"]


# ========== schema ↔ 运行时一致性（issue #3584） ==========

def _dispatch_branches() -> Dict[str, str]:
    """AST 解析 execute() 的 action 分发表：{action 字面量: self._handler 名}

    只取 `if action == "xxx":` 分支**直接 body** 里的 handler，不递归 elif 链，
    避免把其它分支的 handler 误判给当前 action。
    """
    source = inspect.getsource(ProcessingItemManageTool.execute)
    tree = ast.parse(inspect.cleandoc(source))
    branches: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == "action"):
            continue
        for comparator in test.comparators:
            if not (isinstance(comparator, ast.Constant) and isinstance(comparator.value, str)):
                continue
            for sub in ast.walk(ast.Module(body=list(node.body), type_ignores=[])):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                        and sub.value.id == "self"):
                    branches[comparator.value] = sub.attr
                    break
    return branches


_TOOL_SOURCE = Path(inspect.getfile(ProcessingItemManageTool))
# <repo>/backend/ai-agent-service/app/tools/x.py → parents[4] = <repo>
_ADMIN_API_CONTROLLERS = (_TOOL_SOURCE.resolve().parents[4]
                          / "backend" / "admin-api" / "src" / "main"
                          / "java" / "com" / "migao" / "admin" / "controller")


def _normalize_endpoint(path: str) -> str:
    """`/api/admin/processing-items/{item_id}` → `/api/admin/processing-items/{}`"""
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/"))


def _admin_api_endpoints() -> set:
    """扫描 admin-api Controller，返回 {(HTTP 方法, 归一化路径)}。"""
    endpoints = set()
    for java_file in sorted(_ADMIN_API_CONTROLLERS.glob("*.java")):
        source = java_file.read_text(encoding="utf-8")
        base_match = re.search(r'@RequestMapping\(\s*(?:value\s*=\s*)?"([^"]*)"', source)
        base = base_match.group(1) if base_match else ""
        for match in re.finditer(r'@(Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?"([^"]*)"', source):
            endpoints.add((match.group(1).upper(), _normalize_endpoint(base + match.group(2))))
        for match in re.finditer(r'@(Get|Post|Put|Patch|Delete)Mapping\b(?!\s*\()', source):
            endpoints.add((match.group(1).upper(), _normalize_endpoint(base)))
    return endpoints


def _tool_http_calls() -> set:
    """扫描工具源码，返回本工具真实调用的 {(HTTP 方法, 归一化路径)}。"""
    source = _TOOL_SOURCE.read_text(encoding="utf-8")
    return {
        (match.group(1).upper(), _normalize_endpoint(match.group(2)))
        for match in re.finditer(r'client\.(get|post|put|patch|delete)\(\s*f?"([^"]+)"', source)
    }


@pytest.fixture
def agent_tool_context():
    return ToolContext(tenant_id=1, user_id="agent_001", session_id="sess", role="agent")


class TestProcessingPermission:
    async def test_customer_denied(self, tool, sample_tool_context):
        result = await tool.execute(context=sample_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_agent_denied(self, tool, agent_tool_context):
        result = await tool.execute(context=agent_tool_context, action="list_categories")
        assert result.success is False
        assert "权限" in result.error

    async def test_invalid_action(self, tool, admin_tool_context):
        result = await tool.execute(context=admin_tool_context, action="remove_item")
        assert result.success is False
        assert "无效的操作类型" in result.error


class TestProcessingItemCreate:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            category_id="c1", price=5.0, pricing_method="per_meter")
        assert r1.success is False and "缺少加工项名称" in r1.error
        r2 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", price=5.0, pricing_method="per_meter")
        assert r2.success is False and "缺少分类 ID" in r2.error
        r3 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", category_id="c1", pricing_method="per_meter")
        assert r3.success is False and "缺少价格" in r3.error
        # issue #3543：pricing_method 是 admin-api @NotBlank 必填项，缺失必须本地拦下
        r4 = await tool.execute(
            context=admin_tool_context, action="create_processing_item",
            name="打孔", category_id="c1", price=5.0)
        assert r4.success is False and "缺少计价方式" in r4.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        """PP-006 / issue #3543：请求体必须含 pricingMethod + unitPrice，且显式映射 price→unitPrice。

        admin-api `ProcessingItemCreateRequest` 契约（Java DTO 为准）：
        `@NotBlank pricingMethod` + `@NotNull BigDecimal unitPrice` + `@NotBlank categoryId`。
        旧实现只 POST `{name, categoryId, price}` → Bean Validation 422「参数校验失败」
        → B 端「新增加工项」完全不可用（acceptance/2026-09-14/replay-triage §2.3）。
        """
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="测试加工",
            price=8.0, category_id="c1", pricing_method="per_meter")
        assert result.success is True
        assert result.data["id"] == "pi-new"
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items"
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["categoryId"] == "c1"
        assert json_data["name"] == "测试加工"
        assert json_data["pricingMethod"] == "per_meter"
        # 值正确：单价以 unitPrice（非 price）落请求体——显式映射，禁止依赖同名
        assert json_data["unitPrice"] == 8.0
        assert "price" not in json_data

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_rejects_unsupported_pricing_method(self, mock_get_client, tool, admin_tool_context, mock_client):
        """计价方式 canonical 枚举（issue #3543 / #3005）：per_piece（按个）非法必须拒绝并说明。"""
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="测试加工",
            category_id="c1", price=8.0, pricing_method="per_piece")
        assert result.success is False
        assert "计价方式" in result.error
        # 「并说明」：错误信息须给出可选枚举，且点明 per_piece 不支持
        assert "per_meter" in result.message and "per_area" in result.message
        assert "per_piece" in result.message
        mock_client.post.assert_not_called()

    def test_pricing_method_schema_declares_canonical_enum(self, tool):
        """schema 必须声明 pricing_method（与 description 铁律所列参数一致），枚举无 per_piece。"""
        props = tool.parameters["properties"]
        assert "pricing_method" in props, "description 要求 LLM 传 pricing_method，schema 必须声明"
        assert set(props["pricing_method"]["enum"]) == {"per_meter", "per_set", "fixed", "per_area"}
        assert "per_piece" not in props["pricing_method"]["enum"]

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_without_density_field(self, mock_get_client, tool, admin_tool_context, mock_client):
        """PP-006（issue #3005 回滚）：create_item 不再支持 per_meter_quantity 透传"""
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pi-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="create_processing_item", name="打孔", price=8.0,
            category_id="c1", pricing_method="per_meter")
        assert result.success is True
        json_data = mock_client.post.call_args[1]["json_data"]
        assert json_data["unitPrice"] == 8.0
        assert "perMeterQuantity" not in json_data


class TestProcessingItemUpdate:
    """issue #3584：PUT 是全量替换（admin-api ProcessingItemUpdateRequest），
    缺 name/categoryId/pricingMethod/unitPrice 任一 → 422「参数校验失败」。"""

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", name="打孔")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.get.assert_not_called()
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_no_content(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="update_item", item_id="pi-1")
        assert result.success is False
        assert "缺少更新内容" in result.error
        mock_client.get.assert_not_called()
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_sends_all_required_fields_with_canonical_names(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """红→绿核心断言：PUT body 必须含 DTO **全部**必填字段，且单价字段名是 unitPrice（非 price）。"""
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1",
            name="打孔(更新)", price=6.0)

        assert result.success is True, result.message
        # 先 GET 详情（merge 语义的必要证据），再 PUT 同一资源
        assert item_client.get.call_args[0][0] == "/api/admin/processing-items/pi-1"
        assert item_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1"

        body = _put_body(item_client)
        for field in REQUIRED_DTO_FIELDS:
            assert field in body, f"PUT body 缺 DTO 必填字段 {field} → admin-api 必 422"
        assert body["name"] == "打孔(更新)"          # 用户显式传入 → 覆盖
        assert body["categoryId"] == "c1"            # 未传 → 保留原值（否则 @NotBlank 422）
        assert body["pricingMethod"] == "per_meter"  # 未传 → 保留原值（否则 @NotBlank 422）
        assert body["unitPrice"] == 6.0              # price → unitPrice 显式映射
        assert "price" not in body, "DTO 无 price 字段，单价必须叫 unitPrice"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_single_field_keeps_untouched_fields(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """只改一个字段时未传字段不被清空（GET merge 的必要性证据）。

        PUT 是全量替换：若不先读回原值，缺字段会被 Bean Validation 拦（422）；
        即便绕过校验，也会把未提交的可选字段写成 null。
        """
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1", price=9.5)

        assert result.success is True, result.message
        body = _put_body(item_client)
        assert body["unitPrice"] == 9.5
        assert body["name"] == ITEM_DETAIL["name"]
        assert body["categoryId"] == ITEM_DETAIL["categoryId"]
        assert body["pricingMethod"] == ITEM_DETAIL["pricingMethod"]
        assert body["unit"] == ITEM_DETAIL["unit"]
        assert body["minQuantity"] == ITEM_DETAIL["minQuantity"]
        assert body["maxQuantity"] == ITEM_DETAIL["maxQuantity"]
        assert body["description"] == ITEM_DETAIL["description"]
        assert body["options"] == ITEM_DETAIL["options"]
        assert body["applicableProductCategories"] == ITEM_DETAIL["applicableProductCategories"]
        assert body["processingDays"] == ITEM_DETAIL["processingDays"]
        assert body["aiRecommended"] is False
        assert body["status"] == ITEM_DETAIL["status"]

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_can_change_pricing_method(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """pricing_method → pricingMethod（canonical 驼峰）透传。"""
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1",
            pricing_method="per_set")

        assert result.success is True, result.message
        assert _put_body(item_client)["pricingMethod"] == "per_set"
        assert "pricing_method" not in _put_body(item_client)

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_rejects_illegal_pricing_method_locally(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """非法枚举在本地（调 admin-api 之前）拒绝 + 列合法值（与 create_item 同口径）。"""
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1",
            pricing_method="per_piece")

        assert result.success is False
        assert "计价方式" in result.error
        assert "per_meter" in result.message and "per_area" in result.message
        assert "per_piece" in result.message
        item_client.get.assert_not_called()
        item_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_rejects_price_out_of_dto_range_locally(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """DTO @DecimalMin(0.10)/@DecimalMax(999.99) → 本地先拒，不发必 422 的请求。"""
        mock_get_client.return_value = item_client

        for bad_price in (0.05, 1000.0):
            result = await tool.execute(
                context=admin_tool_context, action="update_item", item_id="pi-1", price=bad_price)
            assert result.success is False, f"price={bad_price} 应本地拒绝"
            assert "单价" in result.error
            assert "0.10" in result.message and "999.99" in result.message

        item_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_rejects_when_detail_lacks_required_field(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """存量数据缺必填（脏数据）→ 本地拒绝并指出缺哪个，而不是发出去吃 422。"""
        item_client.get = AsyncMock(return_value=_detail_response(
            {"id": "pi-1", "name": "打孔", "unitPrice": 5.0}))  # 缺 categoryId/pricingMethod
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-1", price=6.0)

        assert result.success is False
        assert "必填字段" in result.error
        assert "categoryId" in result.message and "pricingMethod" in result.message
        item_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_detail_not_found_does_not_put(
            self, mock_get_client, tool, admin_tool_context, item_client):
        """详情查询失败（不存在/无权限）→ 直接失败，不发 PUT。"""
        item_client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "加工项不存在"}, "data": None})
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="update_item", item_id="pi-404", price=6.0)

        assert result.success is False
        assert "加工项不存在" in result.message
        item_client.put.assert_not_called()


class TestProcessingItemDelete:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_item")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_item", item_id="pi-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-items/pi-1"


class TestProcessingToggleStatus:
    """issue #3584：`PUT /api/admin/processing-items/{id}/status` 在 admin-api **不存在**，
    旧实现必 404；status 是 ProcessingItemUpdateRequest 的合法可选字段 →
    改走真实存在的 `PUT /{id}`（同样是 GET 详情 → merge → 全量 PUT）。"""

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="toggle_item_status", status="active")
        assert result.success is False
        assert "缺少加工项 ID" in result.error
        mock_client.get.assert_not_called()
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_invalid_status(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="archived")
        assert result.success is False
        assert "无效的状态值" in result.error
        mock_client.get.assert_not_called()
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_active(self, mock_get_client, tool, admin_tool_context, item_client):
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="active")

        assert result.success is True
        assert "已启用" in result.message
        # 真实端点：PUT /{id}（不是 /{id}/status —— 后者 admin-api 无此映射，必 404）
        assert item_client.put.call_args[0][0] == "/api/admin/processing-items/pi-1"
        body = _put_body(item_client)
        assert body["status"] == "active"
        for field in REQUIRED_DTO_FIELDS:
            assert field in body, f"全量替换 PUT 缺必填字段 {field}"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_toggle_inactive(self, mock_get_client, tool, admin_tool_context, item_client):
        mock_get_client.return_value = item_client

        result = await tool.execute(
            context=admin_tool_context, action="toggle_item_status", item_id="pi-1", status="inactive")

        assert result.success is True
        assert "已停用" in result.message
        body = _put_body(item_client)
        assert body["status"] == "inactive"
        assert body["name"] == ITEM_DETAIL["name"]  # 其余字段原样保留


class TestSchemaRuntimeInvariants:
    """schema 暴露的能力必须运行时可达（issue #3584：死 action / 死端点防复发）。"""

    def test_action_enum_matches_valid_actions_and_dispatch(self, tool):
        """action enum == VALID_ACTIONS == execute() 分发分支集合（三者不得漂移）。"""
        schema_actions = set(tool.parameters["properties"]["action"]["enum"])
        assert schema_actions == VALID_ACTIONS
        assert schema_actions == set(_dispatch_branches())

    @pytest.mark.parametrize("action", sorted(VALID_ACTIONS))
    def test_every_action_has_reachable_handler(self, tool, action):
        """schema 里每个 action 都必须有真实分发分支（防「拆完忘改 schema」的死 action）。"""
        branches = _dispatch_branches()
        assert action in branches, f"action {action} 在 schema 里但 execute() 无分发分支"
        assert callable(getattr(tool, branches[action]))

    def test_tool_http_calls_exist_in_admin_api_controllers(self):
        """本工具调用的每个 (method, path) 都必须在 admin-api Controller 里真实存在。

        红→绿证据（缺陷 2）：修复前工具调 `PUT /api/admin/processing-items/{id}/status`，
        该映射不存在 → 本断言失败；修复后与 Controller 映射集合一致。
        """
        if not _ADMIN_API_CONTROLLERS.is_dir():
            pytest.skip(f"admin-api Controller 目录不存在（独立检出场景）：{_ADMIN_API_CONTROLLERS}")

        declared = _admin_api_endpoints()
        missing = sorted(call for call in _tool_http_calls() if call not in declared)
        assert not missing, (
            "工具调用了 admin-api 不存在的端点（恒 404/405）：\n"
            + "\n".join(f"  {method} {path}" for method, path in missing)
            + f"\nadmin-api 已声明：{sorted(declared)}"
        )

    def test_update_path_uses_full_put_not_status_subresource(self):
        """回归护栏：加工项状态更新不得再指向不存在的 /{id}/status 子资源。"""
        assert ("PUT", "/api/admin/processing-items/{}/status") not in _tool_http_calls()


class TestProcessingCategories:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_list_categories(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.get = AsyncMock(return_value={"success": True, "data": [{"id": "pc-1"}]})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="list_categories")
        assert result.success is True
        assert result.data["categories"] == [{"id": "pc-1"}]
        assert mock_client.get.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_missing_name(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="create_category")
        assert result.success is False
        assert "缺少分类名称" in result.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_create_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"id": "pc-new"}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="create_category", name="高级加工")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-categories"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="update_category", name="新名")
        assert r1.success is False and "缺少分类 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="update_category", category_id="pc-1")
        assert r2.success is False and "缺少分类名称" in r2.error
        mock_client.put.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_update_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.put = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="update_category", category_id="pc-1", name="新名")
        assert result.success is True
        assert mock_client.put.call_args[0][0] == "/api/admin/processing-categories/pc-1"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_missing_id(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        result = await tool.execute(context=admin_tool_context, action="delete_category")
        assert result.success is False
        assert "缺少分类 ID" in result.error
        mock_client.delete.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_delete_category_success(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.delete = AsyncMock(return_value={"success": True})
        mock_get_client.return_value = mock_client

        result = await tool.execute(context=admin_tool_context, action="delete_category", category_id="pc-1")
        assert result.success is True
        assert mock_client.delete.call_args[0][0] == "/api/admin/processing-categories/pc-1"


class TestProcessingCalculatePrice:
    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_missing_fields(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_get_client.return_value = mock_client
        r1 = await tool.execute(context=admin_tool_context, action="calculate_price", quantity=2)
        assert r1.success is False and "缺少加工项 ID" in r1.error
        r2 = await tool.execute(context=admin_tool_context, action="calculate_price", processing_item_id="pi-1")
        assert r2.success is False and "缺少数量" in r2.error
        mock_client.post.assert_not_called()

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_priority(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={
            "success": True, "data": {"totalPrice": 100, "total_price": 90},
        })
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "100" in result.message
        assert mock_client.post.call_args[0][0] == "/api/admin/processing-items/calculate"

    @patch("app.tools.processing_item_manage.get_admin_api_client")
    async def test_calculate_total_price_fallback(self, mock_get_client, tool, admin_tool_context, mock_client):
        mock_client.post = AsyncMock(return_value={"success": True, "data": {"total_price": 90}})
        mock_get_client.return_value = mock_client

        result = await tool.execute(
            context=admin_tool_context, action="calculate_price", processing_item_id="pi-1", quantity=2)
        assert result.success is True
        assert "90" in result.message
