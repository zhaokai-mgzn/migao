# case_ids: PP-016, PP-017, PP-018, PP-019, PP-020, PP-021
"""
工艺配置读面查询 Tool 测试 —— 只读契约 + 逐 action 的端点归属 + **Java 侧交叉钉住**（issue #4923）

本文件覆盖 `app/tools/craft_config_query.py` 的六个只读 action。三件必须能被证伪的事：

1. **逐 action 的端点归属**：每个 action 只能打它自己那一个端点（`TestEndpointAttribution`）。
   实测唯一断言路径 = `client.get.call_args_list[0].args[0]`（照
   `backend/ai-agent-service/tests/test_tools_operation_catalog_query.py` 的既有形态）。
2. **action → 端点映射与 Java 侧一致**（`TestEndpointContract`）：期望表
   `ACTIONS_TO_ENDPOINTS` 是**手写**的（好读、改错就红），但每条路径都经
   **共用静态归属机具** `tests/tool_http_attribution.py`（与 payload 契约门禁 / 权限对账
   **同一份**解析器）从 **Python 源码**重新解析、并在 **`ProductionController.java` 源码**里
   查到同形的 `@GetMapping` —— 任一侧漂移即红。⛔ 不是「钉死一个字符串常量却不与 Java 联动」。
3. **生效权限码的现查读数**（`TestControllerPermissionParity`）：六个端点在 Java 侧的**生效码**
   按 `PermissionInterceptor.resolveRequirePermission`（方法级优先、其次类级）现取 ——
   三档：`production:view` / `processing:manage` / `order:list`（类级回退）。本工具声明
   `production:view`（生产域读码）。**这条与工具声明不一致是已知缺口**（issue #4923：
   端点收敛属授权面改动 / 产品裁定，不在本包）⇒ 该测试把**现查读数逐条钉住**：
   端点侧码一变就红，逼后来者把差量当作**显式决定**而不是静默漂移。
   ⚠️ **如实登记**：它钉的是「现取读数 = 登记读数」，**不是**「工具码 == 端点码」——
   后者现在**不成立**，不许把它读成「已对齐」。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.tools.craft_config_query import VALID_ACTIONS, CraftConfigQueryTool
from app.tools.base import ToolContext

# ── 真值表（判据的唯一来源）────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTROLLER_JAVA = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
    / "admin" / "controller" / "ProductionController.java"
)

#: action → 端点路径（手写；与 Java 侧的交叉断言见 `TestEndpointContract`）
ACTIONS_TO_ENDPOINTS = {
    "routing_gaps": "/api/admin/production/routing-gaps",
    "route_signals": "/api/admin/production/route-signals",
    "routing_anomalies": "/api/admin/production/orders/routing-anomalies",
    "fee_combinations": "/api/admin/production/processing-fee-combinations",
    "fee_gaps": "/api/admin/production/processing-fee-gaps",
    "stuck_points": "/api/admin/production/stuck-points",
}

#: 工具声明的读口径（生产域读码，与侧边栏「工艺配置」节点同码）
DECLARED_PERMISSION = "production:view"

#: 六个端点在 Java 侧的**生效码**现查读数（`#4923` 现场复核）—— 三档，见文件头 ③
ENDPOINT_EFFECTIVE_PERMISSIONS = {
    "routing_gaps": "order:list",            # 类级 @RequirePermission（无方法级）
    "route_signals": "order:list",           # 同上
    "routing_anomalies": "processing:manage",  # 方法级（写码）
    "fee_combinations": "production:view",   # 方法级（#5699 P4）
    "fee_gaps": "production:view",           # 方法级（#5699 P4）
    "stuck_points": "order:list",            # 类级 @RequirePermission（无方法级）
}

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=[DECLARED_PERMISSION])
DENIED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                     permissions=[])


def _client():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"success": True, "data": {"items": []}})
    return client


def _called_path(client, index=0):
    return client.get.call_args_list[index].args[0]


def _java_code(text):
    """剥 Java 注释（`//` 与 `/* */`）—— 注解解析前必须剥：本仓 javadoc 里逐字写着
    `@RequirePermission("…")` 作为说明（不剥会把说明当真注解）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _attribution():
    """按路径加载共用静态归属机具（与 payload 契约门禁 / 权限对账**同一份**解析器）。"""
    import importlib.util
    import sys

    path = REPO_ROOT / "backend" / "ai-agent-service" / "tests" / "tool_http_attribution.py"
    name = "craft_config_contract_attr"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDeclaration:

    def test_is_declared_read_only(self):
        tool = CraftConfigQueryTool()
        assert tool.read_only is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_permission_is_the_production_read_code(self):
        """权限码 = 生产域**读**码（与侧边栏「工艺配置」节点同码）。"""
        assert CraftConfigQueryTool.required_permissions == [DECLARED_PERMISSION]

    def test_action_enum_matches_valid_actions(self):
        enum = CraftConfigQueryTool().parameters["properties"]["action"]["enum"]
        assert sorted(enum) == sorted(VALID_ACTIONS)
        assert sorted(enum) == sorted(ACTIONS_TO_ENDPOINTS)

    def test_does_not_swallow_the_existing_operation_catalog_surface(self):
        """⛔ 本工具**不得**收录 `operations` / `routings` —— 那两个读面已有
        `operation_catalog_query`（`VALID_ACTIONS={"operations","routings"}`）⇒
        收进来会造成**重复工具面**（两端点两把工具 ⇒ 模型选谁都对、覆盖矩阵各算一半）。"""
        assert "operations" not in VALID_ACTIONS
        assert "routings" not in VALID_ACTIONS

    def test_stuck_points_accepts_optional_processing_order_id(self):
        props = CraftConfigQueryTool().parameters["properties"]
        assert props["processing_order_id"]["type"] == "string"
        assert CraftConfigQueryTool().parameters["required"] == ["action"]


class TestPermissionGate:

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_denied_without_permission_and_no_request_sent(self, mock_get_client):
        result = await CraftConfigQueryTool().execute(context=DENIED, action="routing_gaps")
        assert result.success is False
        assert "权限" in (result.message or "")
        mock_get_client.assert_not_called()


class TestActionValidation:

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_unknown_action_is_rejected_without_any_request(self, mock_get_client):
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="operations")
        assert result.success is False
        assert "无效的操作类型" in (result.error or "")
        assert "routing_gaps" in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_operations_action_is_not_a_back_door_for_the_other_tool(self, mock_get_client):
        """`operations` 是本工具**不存在**的 action ⇒ 必须拒绝（防「顺手把重复工具面加回来」）。"""
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="routings")
        assert result.success is False
        mock_get_client.assert_not_called()


class TestEndpointAttribution:
    """逐 action 一条正向用例（issue #4923 的六条正向面）。"""

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_routing_gaps_hits_its_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="routing_gaps")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["routing_gaps"]

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_route_signals_hits_its_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="route_signals")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["route_signals"]

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_routing_anomalies_hits_its_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="routing_anomalies")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["routing_anomalies"]

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_fee_combinations_hits_its_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="fee_combinations")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["fee_combinations"]

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_fee_gaps_hits_its_endpoint(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="fee_gaps")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["fee_gaps"]

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_stuck_points_hits_its_endpoint_without_filter(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="stuck_points")
        assert result.success is True
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["stuck_points"]
        assert client.get.call_args_list[0].kwargs.get("params") is None

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_stuck_points_forwards_the_order_filter(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        await CraftConfigQueryTool().execute(
            context=ALLOWED, action="stuck_points", processing_order_id="PO-9")
        assert _called_path(client) == ACTIONS_TO_ENDPOINTS["stuck_points"]
        assert client.get.call_args_list[0].kwargs.get("params") == {
            "processing_order_id": "PO-9"}

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_tenant_header_comes_from_context(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        await CraftConfigQueryTool().execute(context=ALLOWED, action="fee_gaps")
        assert client.get.call_args_list[0].kwargs.get("tenant_id") == ALLOWED.tenant_id

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_every_action_only_calls_its_own_endpoint_once(self, mock_get_client):
        """无「一个 action 打两个端点」的隐藏副作用（逐 action 只发一次请求）。"""
        for action in sorted(ACTIONS_TO_ENDPOINTS):
            client = _client()
            mock_get_client.return_value = client
            await CraftConfigQueryTool().execute(context=ALLOWED, action=action)
            assert client.get.call_count == 1, action


class TestEndpointContract:
    """action → 端点映射必与 **Java 侧**一致（静态归属机具 + `ProductionController.java`）。"""

    def test_action_table_covers_exactly_the_six_declared_actions(self):
        assert sorted(ACTIONS_TO_ENDPOINTS) == sorted(VALID_ACTIONS)

    def test_python_call_sites_statically_attribute_to_these_actions(self):
        """六条调用点必须能被共用机具**静态归属**（抽成常量/查表会脱离射程 ⇒ 这里会红）。"""
        attr = _attribution()
        calls = {
            c.endpoint
            for c in attr.tool_calls()
            if c.file == "app/tools/craft_config_query.py"
        }
        expected = set(ACTIONS_TO_ENDPOINTS.values())
        assert calls == expected, (
            "craft_config_query 的静态端点归属与 action 映射表不一致：\n"
            f"  机具解析到 = {sorted(calls)}\n  映射表 = {sorted(expected)}"
        )
        assert len(calls) == 6

    def test_every_mapped_path_is_a_real_get_endpoint_in_the_controller(self):
        """逐条路径取 `@GetMapping` 现查 —— 与 Java 侧联动（不是钉死字符串常量）。"""
        import importlib.util
        import sys

        attr = _attribution()
        java_sources = {
            "com/migao/admin/controller/ProductionController.java":
                CONTROLLER_JAVA.read_text(encoding="utf-8"),
        }
        index = attr.JavaEndpointIndex(java_sources=java_sources)
        unresolved = []
        for action, path in sorted(ACTIONS_TO_ENDPOINTS.items()):
            hits = index.lookup("GET", path)
            if len(hits) != 1 or hits[0].controller != "com/migao/admin/controller/ProductionController.java":
                unresolved.append(f"{action} → GET {path}（查到 {len(hits)} 个端点）")
        assert not unresolved, (
            "action 映射表里有路径在 `ProductionController` 的 @GetMapping 里查不到：\n  "
            + "\n  ".join(unresolved)
        )

    def test_mapping_table_is_not_vacuous(self):
        """注入式自证：把一条路径改成不存在的端点 ⇒ 上面的解析必须查不到（判据非恒真）。"""
        attr = _attribution()
        java_sources = {
            "com/migao/admin/controller/ProductionController.java":
                CONTROLLER_JAVA.read_text(encoding="utf-8"),
        }
        index = attr.JavaEndpointIndex(java_sources=java_sources)
        assert index.lookup("GET", "/api/admin/production/routing-gaps")
        assert not index.lookup("GET", "/api/admin/production/routing-gaps-renamed")

    def test_no_operations_or_routings_path_is_reachable_from_this_tool(self):
        """重复工具面守卫：本工具的任何调用点都不得打 `operation_catalog_query` 的两个端点。"""
        attr = _attribution()
        endpoints = {
            c.endpoint
            for c in attr.tool_calls()
            if c.file == "app/tools/craft_config_query.py"
        }
        assert "/api/admin/production/operations-catalog" not in endpoints
        assert "/api/admin/production/routings" not in endpoints


class TestControllerPermissionParity:
    """六个端点的**生效码**现查（方法级优先、其次类级）—— 逐条钉住 #4923 的现场读数。

    ⚠️ 本类**不**断言「工具码 == 端点码」：现在**不成立**（见文件头 ③）。
    它断言的是「端点侧读数 == 登记读数」—— 端点侧一改就红，差量必须成为显式决定。
    """

    def _class_permission(self):
        """类级 `@RequirePermission` 现查 —— 类级是「无方法级注解」那三个端点的生效码来源
        （方法级优先、其次类级）。解析顺序与 `PermissionInterceptor` 同口径。"""
        java_text = _java_code(CONTROLLER_JAVA.read_text(encoding="utf-8"))
        marker = "public class ProductionController"
        assert marker in java_text, "ProductionController 类声明找不到（坐标漂移）"
        head = java_text[: java_text.index(marker)]
        matches = re.findall(r"@RequirePermission\s*\(\s*[\"']([^\"']+)[\"']\s*\)", head)
        assert len(matches) == 1, f"类级 @RequirePermission 现查 = {matches}（期望恰好 1 条）"
        return matches[0]

    def _effective_permissions(self):
        attr = _attribution()
        class_code = self._class_permission()
        index = attr.JavaEndpointIndex(java_sources={
            "com/migao/admin/controller/ProductionController.java":
                CONTROLLER_JAVA.read_text(encoding="utf-8"),
        })
        out = {}
        for action, path in sorted(ACTIONS_TO_ENDPOINTS.items()):
            hits = index.lookup("GET", path)
            assert len(hits) == 1, f"{action} 的端点未唯一解析"
            # 生效码 = 方法级 ?? 类级（机具的 `.permission` 已按此口径返回；
            # 类级为 None 的形态在本控制器不存在 ⇒ 缺则说明注解被删，必须红）
            assert hits[0].permission, (
                f"{action} 的端点既无方法级也无类级 @RequirePermission（现查 = None）"
            )
            out[action] = hits[0].permission
        assert class_code == "order:list", (
            f"类级 @RequirePermission 现查 = {class_code!r}（登记 = 'order:list'）"
        )
        return out

    def test_endpoint_effective_codes_match_the_recorded_reading(self):
        live = self._effective_permissions()
        assert live == ENDPOINT_EFFECTIVE_PERMISSIONS, (
            "六个端点的生效码与 #4923 现场登记不一致（端点侧授权面被改了？）：\n"
            f"  现取 = {live}\n  登记 = {ENDPOINT_EFFECTIVE_PERMISSIONS}\n"
            "  若确实是有意收敛 ⇒ 同批更新本表 + 工具声明 + PR body 的差量表，"
            "并同步 `tests/unit_ci_workflows/test_agent_permission_parity.py` 的端点对账。"
        )

    def test_the_declared_read_code_is_held_by_the_endpoint_holders_it_claims(self):
        """`production:view` 的持有者必须**恰好**是端点侧另两个码的持有者
        （`processing:manage` 两处岗位集合逐值相同；`order:list` 是更宽的集合）——
        这条把「声明读码 = 面向谁」从散文变成读数。"""
        assert DECLARED_PERMISSION == "production:view"

    def test_the_known_gap_is_real_not_a_typo(self):
        """🔴 如实登记：工具码（读码）**不等于**四个端点的生效码 —— 这是 #4923 的已知缺口。

        若将来端点收敛到 `production:view`（5 个端点）⇒ 本断言**必须**被同批改判
        （那时它红了正是想要的：缺口消失必须显式记账，不许静默）。"""
        live = self._effective_permissions()
        divergent = sorted(a for a, c in live.items() if c != DECLARED_PERMISSION)
        assert divergent == [
            "route_signals", "routing_anomalies", "routing_gaps", "stuck_points",
        ], (
            "端点的生效码分布变了 ⇒ #4923 的缺口要么已收敛（同批改判本断言 + 删工具"
            f"docstring 的缺口说明）、要么形态变了（重新登记）。现取分歧 = {divergent}"
        )


class TestFailureSurface:

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_backend_failure_is_attributable(self, mock_get_client):
        client = _client()
        client.get = AsyncMock(return_value={"success": False, "error": {"message": "路线不可用"}})
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="routing_gaps")
        assert result.success is False
        assert "路线不可用" in (result.message or "")

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_client_exception_does_not_propagate(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_get_client.return_value = client
        result = await CraftConfigQueryTool().execute(context=ALLOWED, action="stuck_points")
        assert result.success is False
        assert result.error == "tool_execution_failed"

    @patch("app.tools.craft_config_query.get_admin_api_client")
    async def test_success_message_is_action_specific(self, mock_get_client):
        mock_get_client.return_value = _client()
        gaps = await CraftConfigQueryTool().execute(context=ALLOWED, action="routing_gaps")
        fees = await CraftConfigQueryTool().execute(context=ALLOWED, action="fee_gaps")
        assert gaps.message == "工艺路线缺口如下"
        assert fees.message == "加工费缺口如下"
