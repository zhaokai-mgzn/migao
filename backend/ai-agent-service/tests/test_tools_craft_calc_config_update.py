# case_ids: PP-015
"""算料配置变更 Tool 的契约判据（issue #7514，用户 2026-10-23 裁定）。

语义（用户裁定原文口径）：**改单键 / 多键 + 逐键前后对照** —— 不做整份编辑、不做重置默认。

覆盖（每条都能红 = 把被测行为改回旧形态即失败）：

① **只改一个键 ⇒ 其余 10 个键逐值不变**：admin-api 的 `PUT` 是 upsert + **全量替换**
   ⇒ 少带一个键就等于把它清空（「改一个键、别的全恢复默认」的静默事故形态）；
② **`before` 与服务端当前值不符 ⇒ `craft_calc_config_stale` + 零 `PUT`**（fail-closed：
   确认卡上的「改前」已经过期时绝不写）；
③ **无 `processing:manage` ⇒ 拒且零 admin-api 调用**（工具层门禁，不靠服务端兜底）；
④ **类属性契约**：`read_only=False` / `requires_confirmation=True` / `destructive=False` /
   `idempotent=True` / `required_permissions == ["processing:manage"]`；
⑤ **`422 + error.details:[{field,message}]` 逐条透传**（中文、可行动，不得吞成「更新失败」）。

全部走 mock（`unittest.mock.patch` 的 `get_admin_api_client`）—— 不连真库、不连真 admin-api。
"""
import copy
from unittest.mock import AsyncMock, patch

from app.tools.base import ToolContext
from app.tools.craft_calc_config_update import (
    ALLOWED_CONFIG_KEYS,
    CraftCalcConfigUpdateTool,
    same_config_value,
)

ENDPOINT = "/api/admin/production/craft-calc-config"
PERMISSION = "processing:manage"

ALLOWED = ToolContext(tenant_id=46, user_id="u-1", session_id="s-1", role="operator",
                      permissions=[PERMISSION])
DENIED = ToolContext(tenant_id=46, user_id="u-1", session_id="s-1", role="operator",
                     permissions=["production:view"])

#: 本店当前配置（= `GET` 的 `data.config`，11 个键全在）
CURRENT_CONFIG = {
    "per_fold_single": 0.25,
    "per_fold_mixed_times": {"2": 0.3, "3": 0.35},
    "margin_single": 0.2,
    "margin_multi": 0.3,
    "margin_mixed_single": 0.15,
    "margin_mixed_multi": 0.2,
    "min_fullness": 1.5,
    "tiers": {
        "标准": {"fullness": 2.0, "label": "2.0 倍"},
        "满褶": {"fullness": 2.4, "label": "2.4 倍"},
    },
    "default_formula": "pleat",
    "hem_margin": 0.3,
    "meters_rounding_step": 0.1,
    "oversize_width_threshold": 6,
    "oversize_height_threshold": 4,
}


def _client(current=None, write_response=None):
    """GET 返回本店当前配置（可注入成任意形态）；PUT 返回成功（或注入失败响应）。"""
    client = AsyncMock()
    client.get = AsyncMock(return_value={
        "success": True,
        "data": {"source": "stored", "config": copy.deepcopy(current or CURRENT_CONFIG)},
    })
    client.put = AsyncMock(return_value=write_response or {"success": True, "data": {}})
    return client


class TestDeclaration:
    """④ 类属性契约（A 档可逆写：写面码 + 确认门禁 + 幂等）"""

    def test_write_flags_are_declared(self):
        tool = CraftCalcConfigUpdateTool()
        assert tool.read_only is False
        assert tool.requires_confirmation is True
        assert tool.destructive is False
        assert tool.idempotent is True

    def test_required_permission_is_the_endpoint_write_code(self):
        assert CraftCalcConfigUpdateTool.required_permissions == [PERMISSION]

    def test_name_is_stable(self):
        assert CraftCalcConfigUpdateTool().name == "craft_calc_config_update"

    def test_changes_and_before_are_both_required(self):
        params = CraftCalcConfigUpdateTool().parameters
        assert set(params["required"]) == {"changes", "before"}
        assert params["properties"]["changes"]["type"] == "object"
        assert params["properties"]["before"]["type"] == "object"

    def test_allowed_keys_match_the_admin_api_config_map(self):
        """13 个键与 `CraftCalcConfig.toConfigMap()` 逐字同名且**同序**（跨源对账见根仓契约守卫）。"""
        assert list(ALLOWED_CONFIG_KEYS) == list(CURRENT_CONFIG)


class TestPermissionGate:
    """③ 无权限 ⇒ 拒且零 admin-api 调用"""

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_denied_without_manage_code_and_no_request_sent(self, mock_get_client):
        result = await CraftCalcConfigUpdateTool().execute(
            context=DENIED,
            changes={"hem_margin": 0.25},
            before={"hem_margin": 0.3},
        )
        assert result.success is False
        assert "权限" in (result.message or "")
        assert "工艺与路线" in (result.suggestion or "")
        mock_get_client.assert_not_called()


class TestOnlyNamedKeysAreChanged:
    """① 只改点名的键，其余原样保留（`PUT` 全量替换语义）"""

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_other_twelve_keys_are_written_back_verbatim(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"hem_margin": 0.25},
            before={"hem_margin": 0.3},
        )

        assert result.success is True
        assert client.put.call_args.args[0] == ENDPOINT
        body = client.put.call_args.kwargs["json_data"]
        assert set(body) == set(ALLOWED_CONFIG_KEYS)
        assert body["hem_margin"] == 0.25
        untouched = [key for key in CURRENT_CONFIG if key != "hem_margin"]
        assert len(untouched) == 12   # 13 键 − 改掉的那 1 个
        for key in untouched:
            assert body[key] == CURRENT_CONFIG[key], f"{key} 被写坏了（{PUT_HINT}）"

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_multiple_keys_are_paired_in_the_result(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"hem_margin": 0.25, "margin_single": 0.25},
            before={"hem_margin": 0.3, "margin_single": 0.2},
        )

        assert result.success is True
        assert result.data["keys"] == ["hem_margin", "margin_single"]
        assert result.data["before"] == {"hem_margin": 0.3, "margin_single": 0.2}
        assert result.data["after"] == {"hem_margin": 0.25, "margin_single": 0.25}
        assert result.data["source_before"] == "stored"
        # 确认卡口径：人话字段名 + 成对「改前 → 改后」，内部键名不上屏
        assert "上下卷边合计 0.3 → 0.25" in (result.message or "")
        assert "hem_margin" not in (result.message or "")


class TestStaleBeforeIsFailClosed:
    """② `before` 不符 ⇒ 零写入"""

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_mismatched_before_writes_nothing(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"margin_single": 0.25},
            before={"margin_single": 0.15},
        )

        assert result.success is False
        assert result.error == "craft_calc_config_stale"
        assert result.data["stale_keys"] == ["margin_single"]
        assert result.data["current"] == {"margin_single": 0.2}
        assert "没有做任何修改" in (result.message or "")
        client.put.assert_not_called()

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_structured_value_change_also_blocks_the_write(self, mock_get_client):
        client = _client()
        mock_get_client.return_value = client
        before_tiers = {
            "标准": {"fullness": 2.0, "label": "2.0 倍"},
            "满褶": {"fullness": 2.2, "label": "2.2 倍"},  # 与服务端当前的 2.4 不同
        }

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"tiers": {**before_tiers, "满褶": {"fullness": 2.6, "label": "2.6 倍"}}},
            before={"tiers": before_tiers},
        )

        assert result.error == "craft_calc_config_stale"
        assert result.data["stale_keys"] == ["tiers"]
        client.put.assert_not_called()

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_unreadable_current_config_writes_nothing(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(return_value={"success": False, "error": {"message": "配置缺失"}})
        mock_get_client.return_value = client

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"hem_margin": 0.25},
            before={"hem_margin": 0.3},
        )

        assert result.success is False
        assert "配置缺失" in (result.message or "")
        client.put.assert_not_called()


class TestSameConfigValue:
    """逐键核对的口径（数值容差 / 结构化键序无关 / 缺失 fail-closed）"""

    def test_numeric_tolerance(self):
        assert same_config_value(0.3, 0.3) is True
        assert same_config_value("0.30", 0.3) is True
        assert same_config_value(0.3, 0.25) is False

    def test_structured_values_are_key_order_agnostic(self):
        reversed_tiers = {
            "满褶": CURRENT_CONFIG["tiers"]["满褶"],
            "标准": CURRENT_CONFIG["tiers"]["标准"],
        }
        assert same_config_value(reversed_tiers, CURRENT_CONFIG["tiers"]) is True
        assert same_config_value({"2": 0.3}, {"2": 0.31}) is False

    def test_missing_side_is_never_treated_as_equal(self):
        assert same_config_value(None, 0.3) is False
        assert same_config_value(0.3, None) is False

    def test_enum_text_is_compared_literally(self):
        assert same_config_value("pleat", "pleat") is True
        assert same_config_value("pleat", "fullness") is False


class TestParameterValidation:
    """参数面 fail-closed：一个请求都不发"""

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_empty_changes_sends_nothing(self, mock_get_client):
        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED, changes={}, before={})
        assert result.success is False
        assert result.error == "changes_required"
        mock_get_client.assert_not_called()

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_unknown_key_fails_closed_without_dumping_the_whitelist(self, mock_get_client):
        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"tax_rate": 0.13},
            before={"tax_rate": 0.1},
        )
        assert result.success is False
        assert result.error == "unknown_config_key"
        assert "tax_rate" in (result.message or "")
        # 键名清单**不得**当操作指引抛给商家
        for internal_key in ("per_fold_single", "oversize_width_threshold", "meters_rounding_step"):
            assert internal_key not in (result.message or "")
        mock_get_client.assert_not_called()

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_missing_before_fails_closed(self, mock_get_client):
        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"margin_single": 0.25},
            before={},
        )
        assert result.success is False
        assert result.error == "before_required"
        assert "单开余量" in (result.message or "")
        mock_get_client.assert_not_called()


class TestValidationErrorsAreRelayed:
    """⑤ `422` 的逐条理由必须原样回给商家（不得吞成「更新失败」）"""

    @patch("app.tools.craft_calc_config_update.get_admin_api_client")
    async def test_details_are_relayed_one_by_one(self, mock_get_client):
        details = [
            {"field": "min_fullness", "message": "不能小于行业红线 1.5"},
            {"field": "margin_single", "message": "必须大于 0"},
        ]
        client = _client(write_response={
            "success": False,
            "error": {"code": "VALIDATION_ERROR", "message": "参数校验失败", "details": details},
        })
        mock_get_client.return_value = client

        result = await CraftCalcConfigUpdateTool().execute(
            context=ALLOWED,
            changes={"margin_single": -1, "min_fullness": 1.2},
            before={"margin_single": 0.2, "min_fullness": 1.5},
        )

        assert result.success is False
        assert result.error == "craft_calc_config_invalid"
        assert result.data["details"] == details
        assert "褶倍下限：不能小于行业红线 1.5" in (result.message or "")
        assert "单开余量：必须大于 0" in (result.message or "")
        assert "更新失败" not in (result.message or "")
        assert "重新发确认卡" in (result.suggestion or "")


PUT_HINT = "PUT 是全量替换：只改一个键时其余 10 个键必须原样写回"
