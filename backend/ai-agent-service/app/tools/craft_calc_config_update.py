"""
AI 智能客服系统 - 算料配置变更 Tool（issue #7514：黄金策支持算料配置的创建与变更）

语义（用户 2026-10-23 裁定，会话 sess_5742c5b5c43a48b1）：**改单键 / 多键 + 逐键前后对照**
—— 不做整份编辑、不做重置默认。

## 端点与权限（admin-api 侧**已存在**，本单不新增任何接口）

| 方法 | 路径 | 生效权限码 |
|---|---|---|
| `GET` | `/api/admin/production/craft-calc-config` | `production:view`（方法级，issue #5291） |
| `PUT` | `/api/admin/production/craft-calc-config` | `processing:manage`（类级，写面） |

`PUT` 是 **upsert + 全量替换**（`CraftCalcConfigService.put`）⇒ 本工具必须
「先 `GET` 取当前配置 → 只覆盖点名的键 → 整体 `PUT` 回去」——
否则**没点名的键会被清空**（这正是「改一个键、别的全恢复默认」的事故形态）。
非法值 ⇒ `422 + error.details:[{field,message}]`，逐条转述给商家（不得吞成「更新失败」）。

## `before` 为什么是**必填参数**（不是可选项）

1. **确认卡**要逐键呈现「改前 → 改后」：商家点卡前必须看见自己那几个键**原来是多少**；
2. **服务端侧核对**：`before` 必须与服务端**当前真值**逐键相符，否则说明确认卡上的
   「改前」已经过期（他人改过 / 会话里的值被回忆出来的）⇒ `craft_calc_config_stale`，
   **零写入**（fail-closed，绝不把「没说清的旧值」当成写前状态）。

## 边界（有意不做，如实登记）

- **不做整份编辑**：只覆盖 `changes` 点名的键，其余原样保留；
- **不支持重置默认**：`PUT` 是全量替换、没有「删掉一个键」的语义 ——
  要恢复默认请引导商家到后台「企业基础设置 → 工艺与路线 → 算料口径」页；
- 未知键 fail-closed（`unknown_config_key`）：键名清单**不摆给商家**当操作指引。

## 门禁

`read_only=False` + `requires_confirmation=True` ⇒ 未点卡调用由
`app/graph/skills/base_skill.py` 的确认门禁拦下（A 档可逆写，
台账 = `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的 `A_TIER_REVERSIBLE_WRITES`）。
"""

import json
from typing import Any, Dict, List

from loguru import logger

from app.tools.base import BaseTool, ToolContext, ToolResult, admin_api_failure
from app.tools.confirm_value import CRAFT_CALC_CONFIG_FIELD_LABELS, config_key_label
from app.utils.http_client import get_admin_api_client

#: 端点**不抽成模块常量**（有意，同 `notification_manage.py` 的口径）：
#: `tests/tool_http_attribution.py` 的静态归属机具只在**函数体内**解析命名常量 ⇒
#: 模块级常量会让调用点脱离跨模块契约门禁的射程（「无法归属到端点」即红）。
#: 读写是**同一路径**（`CraftCalcConfigController` 的 `@RequestMapping`），
#: 两个调用点各自写字面量 `/api/admin/production/craft-calc-config`。

#: 允许变更的键 = admin-api `CraftCalcConfig.toConfigMap()` 的键集（**11 个，逐字同名**）。
#: 跨源漂移（引擎配置键 / 迁移列 / 本表）由
#: `tests/unit_ci_workflows/test_craft_calc_config_contract.py` 逐键对账兜住。
ALLOWED_CONFIG_KEYS: tuple = (
    "per_fold_single",
    "per_fold_mixed_times",
    "margin_single",
    "margin_multi",
    "margin_mixed_single",
    "margin_mixed_multi",
    "min_fullness",
    "tiers",
    "default_formula",
    "hem_margin",
    "meters_rounding_step",
    "oversize_width_threshold",
    "oversize_height_threshold",
)

#: 商家说法 → 内部键名（issue #8300 实测：模型把「上下卷边」自造成 `hem_allowance`，
#: 服务端只认内部键 ⇒ `unknown_config_key`）。键名翻译放在**确定性代码**里，不靠模型猜。
#: 单一真值源 = `confirm_value.CRAFT_CALC_CONFIG_FIELD_LABELS`（卡面同款人话名），这里只做反查，
#: 避免第二份「中文 → 键」表漂移。
KEY_ALIASES: dict = {label: key for key, label in CRAFT_CALC_CONFIG_FIELD_LABELS.items()}
#: 商家口语会把「合计」省掉（实测原话就是「上下卷边」）⇒ 补一条同义写法。
KEY_ALIASES["上下卷边"] = "hem_margin"


def _canonical_key(key: Any) -> str:
    """键名归一：商家说法 → 内部键；已是合法内部键 ⇒ 原样返回（未知键仍交给 fail-closed）。"""
    raw = str(key or "").strip()
    if raw in ALLOWED_CONFIG_KEYS:
        return raw
    return KEY_ALIASES.get(raw, raw)


#: 数值比较容差：JSON 里 `0.25` / `0.250000` 是同一个值，浮点解析也留一丝误差。
_NUMERIC_TOLERANCE = 1e-9


def _as_number(value: Any):
    """数值化（bool 不算数字）；非数值返回 `None`（**不抛**，交回字符串口径）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _normalized(value: Any) -> str:
    """结构化值（`tiers` / `per_fold_mixed_times`）的规范化形态：**键序无关**。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def same_config_value(declared: Any, current: Any) -> bool:
    """「商家点卡时看到的改前值」是否 == 「服务端当前真值」（issue #7514 的第 4 步）。

    口径（唯一实现，消费方 = `execute` 的逐键核对）：
      · 任一侧缺失 ⇒ `False`（fail-closed：绝不为「没法比对」放行）；
      · 任一侧是 dict / list（`tiers` / `per_fold_mixed_times`）⇒ JSON 规范化后比较（键序无关）；
      · 两侧都能当数字 ⇒ `abs(a-b) <= 1e-9`；
      · 其余 ⇒ 字符串逐字比较（`default_formula` 这类枚举）。
    """
    if declared is None or current is None:
        return False
    if isinstance(declared, (dict, list)) or isinstance(current, (dict, list)):
        return _normalized(declared) == _normalized(current)
    left, right = _as_number(declared), _as_number(current)
    if left is not None and right is not None:
        return abs(left - right) <= _NUMERIC_TOLERANCE
    return str(declared).strip() == str(current).strip()


def _invalid_details(response: Dict[str, Any]) -> List[Dict[str, str]]:
    """admin-api `422` 的逐条理由（`error.details:[{field,message}]`）—— 空 = 不是校验失败。"""
    error = response.get("error") if isinstance(response, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list):
        return []
    out: List[Dict[str, str]] = []
    for item in details:
        if isinstance(item, dict) and str(item.get("message") or "").strip():
            out.append({
                "field": str(item.get("field") or ""),
                "message": str(item.get("message") or "").strip(),
            })
    return out


class CraftCalcConfigUpdateTool(BaseTool):
    """算料配置变更 Tool（A 档可逆写：改单键 / 改多键，其余原样保留）"""

    name = "craft_calc_config_update"
    description = (
        "【触发】商家明确要求**改**本店算料参数时调用，如「上下卷边改成 0.25」「搭接损耗调 0.1」"
        "「单开余量调到 0.25」「褶倍下限改成 1.6」。"
        "【前置，缺一不可】① 先调 craft_calc_config_query 取本店**当前真值**；"
        "② 再发 interact(component=confirm) 确认卡，**逐键**展示「改前 → 改后」；"
        "③ 商家**点卡之后**才调用本工具（未点卡调用会被确认门禁拦下）。"
        "【参数】changes = 要改的键 → 新值（**只放点名的键**）；before = 同一批键 → **改前值**"
        "（必须取自 craft_calc_config_query 的返回，服务端逐键核对，不符即拒绝且**零写入**）。"
        "【边界】只覆盖 changes 点名的键，其余配置**原样保留**；**不支持重置默认**"
        "（要恢复默认请到后台「企业基础设置 → 工艺与路线 → 算料口径」页操作）；"
        "算具体一单的用布量/报价请引导商家到后台算料页填尺寸计算。"
        "【纪律】不要把内部键名 / 内部标识摆给商家：确认卡与人话一律用中文字段名。"
        "【标注】WRITE|IDEMPOTENT — 变更类写操作（同一 changes/before 重放结果一致），必须先确认再执行"
        "｜【键名】" + "、".join(f"{alias}→{key}" for alias, key in KEY_ALIASES.items())
        + "；用商家说法当键也接受，**禁止自造英文键名**"
    )

    #: 写面权限码 = `CraftCalcConfigController` 的类级 `processing:manage`
    #: （与工序库 / 工艺路线写面同码；读面另见 `craft_calc_config_query` 的 `production:view`）。
    required_permissions = ["processing:manage"]
    read_only = False
    destructive = False
    #: A 档可逆写：必须由用户确认（确认卡逐键「改前 → 改后」）后才执行。
    requires_confirmation = True
    idempotent = True

    parameters = {
        "type": "object",
        "properties": {
            "changes": {
                "type": "object",
                "description": (
                    "要改的算料配置键 → 新值（只放商家点名的那几个键；"
                    "键名与 fill 值都必须来自 craft_calc_config_query 的返回）"
                ),
            },
            "before": {
                "type": "object",
                "description": (
                    "与 changes **同一批键** → 改前值（逐字取自 craft_calc_config_query 的返回；"
                    "服务端会逐键核对，不符即拒绝且不做任何修改）"
                ),
            },
        },
        "required": ["changes", "before"],
    }

    async def execute(
        self,
        context: ToolContext,
        changes: Dict[str, Any] = None,
        before: Dict[str, Any] = None,
        **kwargs,
    ) -> ToolResult:
        # ① 权限门禁（工具层）：失败给中文提示 + 可行动的办理路径
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限修改算料配置",
                suggestion=(
                    "请联系管理员为您开通「企业基础设置 → 工艺与路线」管理权限"
                    "（权限码 processing:manage）后重试"
                ),
            )

        changes_map = {_canonical_key(k): v for k, v in (changes or {}).items() if v is not None}
        before_map = {_canonical_key(k): v for k, v in (before or {}).items()}

        # ② 参数面校验（**本地 fail-closed：一个请求都不发**）
        if not changes_map:
            return ToolResult(
                success=False,
                error="changes_required",
                message="不清楚要改哪几个算料参数，所以没有做任何修改",
                suggestion=(
                    "先调 craft_calc_config_query 取当前配置，再用 interact(component=confirm) "
                    "发确认卡让商家确认要改的值（改前 → 改后）"
                ),
            )

        unknown = sorted(str(k) for k in changes_map if k not in ALLOWED_CONFIG_KEYS)
        if unknown:
            return ToolResult(
                success=False,
                error="unknown_config_key",
                message=(
                    "这几个参数不在可改范围内：" + "、".join(f"「{k}」" for k in unknown)
                    + "（本次没有做任何修改）"
                ),
                suggestion=(
                    "不要向商家罗列内部键名清单。改用商家能对上的参数名复述他要改什么"
                    "（如上下卷边 / 单开余量 / 褶倍下限），必要时先调 craft_calc_config_query "
                    "取当前配置再问一次；确实不在可改范围内的，引导商家到后台"
                    "「企业基础设置 → 工艺与路线 → 算料口径」页操作"
                ),
            )

        missing_before = sorted(str(k) for k in changes_map if k not in before_map)
        if missing_before:
            return ToolResult(
                success=False,
                error="before_required",
                message=(
                    "少了改前的值，没法给商家看「改前 → 改后」，所以没有做任何修改："
                    + "、".join(f"「{config_key_label(k)}」" for k in missing_before)
                ),
                suggestion=(
                    "先调 craft_calc_config_query 取本店当前配置，把每个要改的键的**改前值**"
                    "填进 before，并重发确认卡让商家逐键确认后再调用"
                ),
            )

        # ③ 取当前真值（before 的核对基准 = 服务端，不是会话记忆）
        try:
            client = get_admin_api_client()
            response = await client.get(
                "/api/admin/production/craft-calc-config",
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Craft calc config read-before-write error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="读取本店当前算料配置失败，**本次没有做任何修改**",
                suggestion="请稍后重试；若持续失败请联系技术支持（不要凭记忆直接写配置）",
            )

        if not response.get("success"):
            error_info = response.get("error", {})
            error_msg = (
                error_info.get("message", "查询失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                response,
                error=error_msg,
                message=f"读取本店当前算料配置失败，本次没有做任何修改：{error_msg}",
                suggestion=(
                    "请稍后重试；若持续失败，请引导商家到后台"
                    "「企业基础设置 → 工艺与路线 → 算料口径」页查看与修改"
                ),
            )

        payload: Dict[str, Any] = response.get("data") or {}
        source = str(payload.get("source") or "")
        current_config = payload.get("config")
        if not isinstance(current_config, dict) or not current_config:
            return ToolResult(
                success=False,
                error="craft_calc_config_unavailable",
                message="暂时读不到本店当前的算料配置，**本次没有做任何修改**",
                suggestion=(
                    "先调 craft_calc_config_query 确认能取到配置再谈修改；"
                    "取不到时如实告知商家，不要用默认值/行业常识顶替"
                ),
            )

        # ④ 逐键核对 before ↔ 服务端当前真值（不符 ⇒ 零 PUT）
        stale = [
            str(key) for key in changes_map
            if not same_config_value(before_map.get(key), current_config.get(key))
        ]
        if stale:
            logger.warning(f"[craft_calc_config_update] stale before keys={stale}")
            return ToolResult(
                success=False,
                error="craft_calc_config_stale",
                data={
                    "stale_keys": stale,
                    "current": {key: current_config.get(key) for key in stale},
                    "before": {key: before_map.get(key) for key in stale},
                    "source": source,
                },
                message=(
                    f"有 {len(stale)} 项配置在商家确认之后已经变了（改前值和当前值对不上），"
                    "**本次没有做任何修改**"
                ),
                suggestion=(
                    "重新调 craft_calc_config_query 取一次当前配置，把新的「改前 → 改后」"
                    "**再发确认卡**让商家重新确认；确认后再调用本工具。"
                    "不要把内部键名摆给商家 —— 用中文字段名说「XX 已经从 A 变成 B，"
                    "要按新值再改一次吗」"
                ),
            )

        # ⑤ 只覆盖点名的键，其余原样保留（`PUT` 是全量替换 ⇒ 必须带上完整配置）
        merged = {**current_config, **changes_map}
        try:
            written = await client.put(
                "/api/admin/production/craft-calc-config",
                json_data=merged,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except Exception as e:
            logger.error(f"Craft calc config write error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="算料配置提交失败，请稍后重试",
                suggestion="请稍后重试；若持续失败请联系技术支持，并请商家到后台「企业基础设置 → 工艺与路线 → 算料口径」页核对当前配置",
            )

        if not written.get("success"):
            details = _invalid_details(written)
            if details:
                # ⑥ 422：逐条转述（中文、可行动），**不得**吞成「更新失败」
                lines = "；".join(
                    f"{idx}. {config_key_label(d['field'])}：{d['message']}"
                    for idx, d in enumerate(details, 1)
                )
                # 必须经唯一映射点（`admin_api_failure`）：绕过它 = 授权类失败会被降级成套话
                # （判据 `tests/test_admin_api_failure_mapping.py` 的「零绕过」）。
                return admin_api_failure(
                    written,
                    error="craft_calc_config_invalid",
                    message=f"这几个值没通过校验，**本次修改没有生效**：{lines}",
                    suggestion=(
                        "按上面每一条的说法把值改到合法范围后，**重新发确认卡**（改前 → 改后）"
                        "让商家再点一次；不要原样重试同一组值"
                    ),
                    data={"details": details},
                )
            error_info = written.get("error", {})
            error_msg = (
                error_info.get("message", "提交失败")
                if isinstance(error_info, dict)
                else str(error_info)
            )
            return admin_api_failure(
                written,
                error=error_msg,
                message=f"算料配置提交失败：{error_msg}",
                suggestion=(
                    "请稍后重试；若持续失败，请引导商家到后台"
                    "「企业基础设置 → 工艺与路线 → 算料口径」页修改"
                ),
            )

        written_data: Dict[str, Any] = written.get("data") or {}
        after_config = written_data.get("config")
        after_config = after_config if isinstance(after_config, dict) else {}
        keys = sorted(changes_map)
        before_facts = {key: before_map.get(key) for key in keys}
        after_facts = {
            key: after_config.get(key, changes_map[key]) for key in keys
        }
        pairs = "；".join(
            f"{config_key_label(key)} {before_facts[key]} → {after_facts[key]}"
            for key in keys
        )
        logger.info(f"[craft_calc_config_update] done keys={keys}")
        return ToolResult(
            success=True,
            data={
                "before": before_facts,
                "after": after_facts,
                "keys": keys,
                "source_before": source,
            },
            message=f"已修改 {len(keys)} 项算料配置：{pairs}（其余配置未改动）",
            summary=(
                f"算料配置已更新 {len(keys)} 项：" + pairs
                + "。如实转述给商家（用中文字段名，不要提内部键名）；"
                "说明只改了这几项、其余未动，且随时可以再调回来"
            ),
        )
