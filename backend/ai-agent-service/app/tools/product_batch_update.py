"""商品批量更新 Tool —— 批量改价 / 批量上下架 + 撤销（issue #5314 的 Agent 侧）。

**契约**（`gh issue view 5314` 的评论「批量更新能力 —— 设计 + 冻结契约（2026-09-24）」，
服务端由另一个包按同一份契约实现，双方只靠契约对齐）：

    POST /api/admin/agent/batches                创建批次（= 预演）
        req  {batchType, items:[{resourceId, field, oldValue, newValue}]}
        resp {batchId, itemCount, status:"preview"}
    POST /api/admin/agent/batches/{batchId}/execute   执行 → {batchId, status, results:[{resourceId, success, error?}]}
    POST /api/admin/agent/batches/{batchId}/revert    撤销 → 同上形态

为什么不复用 `product_update`（有意分开，契约 §四 明写）：单条路径已交付并带自己的
「改前 → 改后」护栏；批量是**另一类风险**（一键确认 N 条 = 商家实际没看 = 盲签），
它的准入前置是**撤销**（`docs/wiki/agent-write-boundary.md` §五 裁定 1）。两份实现各自可读、
文件所有权也更干净。

## 三条机器判据（不靠 prompt 自律）

1. **两段确认不可跳过**：`execute` / `revert` **必须**带 `batch_id`，而它只能来自
   `preview` ⇒ 「没给商家看过逐条预览就执行」在**结构上不可达**（fail-closed，
   与 `product_update` 的 `price_preview_required` 同族）。
   第一段（`interact(multiSelect=true)` 勾选集合）的载体是 `interact` 工具，见 description。
2. **`old_value` 必须在预览阶段采集**（契约 §三：它是撤销的唯一依据，必须持久化）
   ⇒ 任一条目缺改前值一律拒；改价类型的判据复用 `confirm_value.price_preview_missing`
   （#5303 的同一套单一源，不另立第二份）。
3. **阈值**：`N > MAX_BATCH_ITEMS(50)` ⇒ 拒绝并提示分批（本单不做后台异步任务）。

字段投影同样**只此一处**：预览行由 `app.tools.confirm_value.confirm_card_fields` 派生。
"""

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.tools import confirm_value
from app.tools.base import (
    BaseTool,
    ToolContext,
    ToolResult,
    admin_api_failure,
    permission_denied,
)
from app.utils.http_client import get_admin_api_client

#: batchType 白名单 —— **只有这两个**（契约 §三）。通用批量有意不做：
#: 具名批量的可逆性与预览形态是确定的，通用批量不是。
BATCH_TYPE_PRICE = "product_price"
BATCH_TYPE_STATUS = "product_status"
BATCH_TYPES: Tuple[str, ...] = (BATCH_TYPE_PRICE, BATCH_TYPE_STATUS)

#: 每个 batchType 对应的唯一字段（类别与字段错配 ⇒ 拒绝，不让服务端去猜）。
#: 每个 batchType 对应的 wire 字段名（**服务端实测真值**，不是猜的）：
#: `product_price` → `basePrice`（= admin-api `products.base_price` 的 wire 名，与逐条写
#: `product_update` 的 `basePrice` **同名字段**）；`product_status` → `status`
#: （取值只认 `on_sale` / `off_sale`）。
_FIELD_OF_BATCH_TYPE = {BATCH_TYPE_PRICE: "basePrice", BATCH_TYPE_STATUS: "status"}

#: 字段别名（模型很容易把改价字段写成 `price`，而 wire 字段是 `basePrice`）：
#: 收下别名并**归一成 wire 名**再下发 —— 让 LLM 的用词习惯不至于变成一次无谓失败。
_FIELD_ALIASES = {BATCH_TYPE_PRICE: {"basePrice", "price"}, BATCH_TYPE_STATUS: {"status"}}

#: 单批上限（契约 §四）：N > 50 ⇒ 拒绝并提示分批（本单不做后台任务，最小实现）。
MAX_BATCH_ITEMS = 50

#: 本工具的 action 全集（模块级常量 = `read_only_actions ⊆ VALID_ACTIONS` 契约的校验面）。
VALID_ACTIONS = {"preview", "execute", "revert"}

_ACTIONS = ("preview", "execute", "revert")


def _present(value: Any) -> bool:
    """非空取值：`None` / 空串 / 纯空白一律视为「没给」。"""
    return value is not None and str(value).strip() != ""


def _missing_before_value_reason(batch_type: str, item: Dict[str, Any]) -> str:
    """改前值缺席的判据（合规返回 ""）。

    改价类型复用 `confirm_value.price_preview_missing`（#5303 的单一源）；
    改状态类型是同一口径的镜像 —— `old_value` 是撤销的唯一依据，两类都必须在预览阶段采集。
    """
    if batch_type == BATCH_TYPE_PRICE:
        return confirm_value.price_preview_missing(
            {"price": item.get("newValue"), "before_price": item.get("oldValue")})
    if not _present(item.get("oldValue")):
        return "本次批量改状态没有带改前值 oldValue（改前 → 改后的另一半，也是撤销的唯一依据）"
    return ""


def _preview_row(batch_type: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """单条的「改前 → 改后」字段行 —— 投影**只此一处**（`confirm_value`）。

    键的插入顺序决定卡片行序（`confirm_card_fields` 的通用分支按 `args.items()` 遍历）
    ⇒ 商品 → 改前 → 改后，与 #5303 单条改价确认卡同一读法。
    """
    resource_id = str(item.get("resourceId"))
    if batch_type == BATCH_TYPE_PRICE:
        args = {"product_id": resource_id,
                "before_price": item.get("oldValue"), "price": item.get("newValue")}
    else:
        args = {"product_id": resource_id,
                "before_status": item.get("oldValue"), "status": item.get("newValue")}
    return {"resourceId": resource_id, "fields": confirm_value.confirm_card_fields(args)}


class ProductBatchUpdateTool(BaseTool):
    """商品批量更新 —— 批量改价 / 批量上下架（先预览后执行，可撤销）"""

    name = "product_batch_update"
    description = (
        "【触发】商家要**一次改多条**商品时用：'把这几款都改成…'、'这批全部下架'、'统一改价'、"
        "'批量调整价格/上下架'，或商家已用多选卡勾选完一批商品后。"
        "【前置】必须走完**两段确认**才允许执行（本工具强制，不是建议）："
        "① 第一段（改哪些）：先用 product_search / product_detail 拿真实候选与**改前值真值**，"
        "再发 `interact(component=choice, multiSelect=true, …)` 让商家**勾选集合** —— "
        "multiSelect 必须显式传 true（漏传会变单选，商家选不了多条）；"
        "② 第二段（改成什么）：调本工具 action=preview 生成**逐条「改前 → 改后」**预览，"
        "把返回的 fields 交给 `interact(component=confirm, fields=…)` 展示给商家并等其点卡；"
        "③ 商家点卡后，再调 action=execute 并带上 preview 返回的 batch_id。"
        "**禁止跳过任一段直接执行**：不带 batch_id 调 execute/revert 一律被拒（batch_preview_required）。"
        "【参数】action=preview / execute / revert；preview 必填 batch_type + items（batch_id 由它产生）；"
        "execute / revert 只需 batch_id。items 每项 {resourceId, field, oldValue, newValue}："
        "resourceId 用 product_search / product_detail 返回的真实商品标识（禁止自造）；"
        "oldValue 必须取自 product_detail 的**当前值**真值（不得凭记忆或推算）—— 它是撤销的唯一依据，"
        "缺席一律被拒；newValue 是商家明确给出的值（不得自行推算幅度）。"
        "【批量类型·只有两个】batch_type=product_price（商品级统一定价批量改价，field=basePrice）"
        "/ product_status（批量上/下架，field=status，取值 on_sale / off_sale）。"
        "其它类型（改名 / 改图 / 改库存 / 自由字段）**不支持** —— 如实说明并引导到商品列表页 /products。"
        "【阈值】单批最多 50 条：N>50 一律拒绝并提示**分批**（本工具不做后台异步任务）。"
        "【撤销】执行成功后**必须告诉商家可以撤销**：action=revert + batch_id 会逐条还原为改前值 "
        "old_value；部分失败**逐条报告、不做整体回滚**（回滚会掩盖真问题）—— 把失败条目与原因如实转述。"
        "【反例】单条改价/改名用 product_update；单规格调价用 sku_update；"
        "查数据用 product_search / product_detail；本工具不查数据、不猜值，也不做批量**创建**/导入。"
        "【标注】WRITE|NON_IDEMPOTENT — 写操作：先 preview（两段确认齐了）再 execute；"
        "禁止只预览就宣称已改，也禁止把 preview 的结果当成已执行。"
    )
    # 权限码（契约 §三）：与**逐条写同码**，不新开权限面。
    # 逐条写的码 = `product_update.required_permissions` = admin-api `ProductController`
    # 的写码 `product:create`（「新增/编辑/上下架商品」，`RegistrationService` 权限目录；
    # 契约正文括注的 `product:update` 在目录里**不存在** ⇒ 取「同码」这一条更硬的判据）。
    required_permissions = ["product:create"]
    read_only = False
    requires_confirmation = True   # #3594：高风险非 destructive 写操作必须显式表态（走确认门禁）
    destructive = False            # 可撤销（revert 逐条还原），不是不可逆破坏
    idempotent = True              # 写的是**绝对目标值**（价格 155 / 下架）⇒ 重放收敛到同一状态
                                   # （与 `product_update` 同口径）；批次状态由服务端状态机把关
    # `preview` = **预演**（契约原话「创建批次（= 预演）」）：只落一条 preview 批次，
    # **不改变任何商品数据** ⇒ 免确认拦截（`_requires_confirmation` 的既有豁免口）。
    # ⚠️ 这一格是**必需**的，不是顺手加的：第二段确认卡的材料（逐条「改前 → 改后」字段）
    # 只能由 preview 产出 —— 若 preview 也要「用户先明确确认」，两段确认在第一段
    # （multiSelect 勾选卡回传「已选商品：…」）之后立刻死锁：模型拿不到预览就发不出第二张卡。
    # `execute` / `revert` **不在**本集合里 ⇒ 仍必须经用户点确认卡（或在同会话已确认过本工具）。
    read_only_actions = frozenset({"preview"})

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "preview=生成批次并返回逐条「改前 → 改后」预览（先给商家确认）；"
                               "execute=执行该批次（须带 preview 返回的 batch_id）；"
                               "revert=撤销该批次（逐条还原为改前值 old_value）",
            },
            "batch_type": {
                "type": "string",
                "enum": list(BATCH_TYPES),
                "description": "批量类型（action=preview 必填）：product_price=商品级统一定价批量改价；"
                               "product_status=批量上/下架。只有这两个",
            },
            "items": {
                "type": "array",
                "description": "要改的条目（action=preview 必填，最多 50 条）。每项一条："
                               "resourceId=商品标识；field=字段（product_price→basePrice / product_status→status）；"
                               "oldValue=改前值（product_detail 的真值，撤销依据）；newValue=改后值（商家给定）",
                "items": {
                    "type": "object",
                    "properties": {
                        "resourceId": {"type": "string",
                                       "description": "商品标识（product_search / product_detail 返回的真值，禁止自造）"},
                        "field": {"type": "string", "enum": ["basePrice", "status"],
                                  "description": "要改的字段：改价传 basePrice（写 price 也收，会归一成 basePrice）"
                                                 "/ 上下架传 status"},
                        "oldValue": {"type": "string",
                                     "description": "改前值（元 / on_sale|off_sale），取自 product_detail 的当前值真值；必填（撤销依据）"},
                        "newValue": {"type": "string",
                                     "description": "改后值（元 / on_sale|off_sale），必须是商家明确给出的值"},
                    },
                    "required": ["resourceId", "field", "oldValue", "newValue"],
                },
            },
            "batch_id": {
                "type": "string",
                "description": "批次号（action=execute / revert 必填）—— 只能来自 action=preview 的返回；"
                               "没有它说明还没给商家看过逐条预览",
            },
        },
        "required": ["action"],
    }

    async def execute(  # type: ignore[override]
        self,
        context: ToolContext,
        action: str = "",
        batch_type: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        batch_id: Optional[str] = None,
    ) -> ToolResult:
        if not self.check_permission(context):
            return permission_denied(
                error="权限不足",
                message="您没有权限批量修改商品",
                suggestion=("批量改价 / 上下架与逐条写**同码**（product:create）：请如实告知商家当前账号"
                            "缺少该权限，并指引其联系管理员在管理后台（「员工管理 → 编辑员工 → 权限」"
                            "或「角色管理 → 岗位权限」）开通后重试 —— 这是权限限制，不是参数问题。"),
            )

        if action == "preview":
            return await self._preview(context, batch_type, items)
        if action == "execute":
            return await self._execute_batch(context, batch_id)
        if action == "revert":
            return await self._revert_batch(context, batch_id)

        return ToolResult(
            success=False,
            error="unsupported_batch_action",
            message=f"不支持的批量动作：{action or '（未提供）'}",
            suggestion=("action 只接受 preview / execute / revert —— 请先调 action=preview 生成批次"
                        "（返回 batch_id 与逐条「改前 → 改后」预览），商家在确认卡上点确认后再调 "
                        "action=execute, batch_id=…"),
        )

    # ── action=preview：创建批次（= 预演），产出第二段确认卡的材料 ──────────────
    async def _preview(self, context: ToolContext, batch_type: Optional[str],
                       items: Optional[List[Dict[str, Any]]]) -> ToolResult:
        if batch_type not in BATCH_TYPES:
            return ToolResult(
                success=False,
                error="batch_type_unsupported",
                message=f"不支持的批量类型：{batch_type or '（未提供）'}",
                suggestion=(f"batch_type 只支持 {BATCH_TYPE_PRICE}（商品级批量改价）/ "
                            f"{BATCH_TYPE_STATUS}（批量上/下架）—— 请从这两个里选一个。"
                            "改名 / 改图 / 改库存 / 自由字段的批量**不在**本工具范围，"
                            "请如实告知商家并引导到商品列表页 /products 操作。"),
            )
        if not isinstance(items, list) or not items:
            return ToolResult(
                success=False,
                error="batch_items_required",
                message="批量预览至少需要一条商品",
                suggestion=("items 不能为空：先用 product_search / product_detail 拿到候选商品与**改前值**真值，"
                            "再发 interact(component=choice, multiSelect=true, …) 让商家勾选要改的商品后重试。"),
            )
        if len(items) > MAX_BATCH_ITEMS:
            return ToolResult(
                success=False,
                error="batch_too_large",
                message=f"一次最多处理 {MAX_BATCH_ITEMS} 条，本次 {len(items)} 条",
                suggestion=(f"本次 {len(items)} 条超过单批上限 {MAX_BATCH_ITEMS} 条 —— 请提示商家**分批**处理"
                            f"（每批 ≤ {MAX_BATCH_ITEMS} 条，逐批走两段确认）；本工具不做后台异步任务，"
                            "不要承诺「稍后一次性完成」。"),
            )

        expected_field = _FIELD_OF_BATCH_TYPE[batch_type]
        normalized: List[Dict[str, Any]] = []
        for raw in items:
            item = raw if isinstance(raw, dict) else {}
            if not _present(item.get("resourceId")) or not _present(item.get("field")):
                return ToolResult(
                    success=False,
                    error="batch_item_incomplete",
                    message="批量条目缺少 resourceId 或 field",
                    suggestion=("items 每项都必须带 resourceId / field / oldValue / newValue —— 请补齐缺失字段后重试"
                                "（resourceId 取 product_search / product_detail 返回的真值，禁止自造）"),
                )
            if item.get("field") not in _FIELD_ALIASES[batch_type]:
                return ToolResult(
                    success=False,
                    error="batch_field_mismatch",
                    message=f"条目字段 {item.get('field')} 与批量类型 {batch_type} 不匹配",
                    suggestion=(f"batch_type={batch_type} 的每项 field 必须是 {expected_field} —— "
                                "改价与上下架不能混在同一批里，请拆成两次批量（各自走两段确认）。"),
                )
            if not _present(item.get("newValue")):
                return ToolResult(
                    success=False,
                    error="batch_item_incomplete",
                    message="批量条目缺少 newValue（改后值）",
                    suggestion=("items 每项都必须带 newValue（改后值）—— 它是商家明确给出的目标值，"
                                "不得由你推算（如「统一上调 5%」需先向商家确认具体数值）后重试。"),
                )
            missing = _missing_before_value_reason(batch_type, item)
            if missing:
                return ToolResult(
                    success=False,
                    error="batch_preview_required",
                    message=f"批量预览被拒（缺改前值）：{missing}",
                    suggestion=("先用 product_detail 取每个商品**当前值**（= oldValue，改前真值），"
                                "再带上它重试 preview —— 改前值是「改前 → 改后」预览的另一半，"
                                "也是撤销（revert）的唯一依据，禁止凭记忆或推算。"),
                )
            normalized.append({
                "resourceId": str(item.get("resourceId")),
                # 归一成 wire 字段名（别名 `price` → `basePrice`）
                "field": expected_field,
                "oldValue": item.get("oldValue"),
                "newValue": item.get("newValue"),
            })

        client = get_admin_api_client()
        # 端点路径**以字面量写在调用点**（常量会让调用点脱离静态归属门禁的射程 ——
        # 见 `app/tools/registry.py` 的同款注释与 `tests/tool_http_attribution.py` 的
        # `_path_template`：非字面量表达式返回 None ⇒ 该调用点被整条跳过）。
        response = await client.post(
            "/api/admin/agent/batches",
            json_data={"batchType": batch_type, "items": normalized},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "批量预览失败") if isinstance(err, dict) else str(err)
            return admin_api_failure(
                response, error=msg, message=f"批量预览失败: {msg}",
                suggestion="批量预览失败：请核对商品标识与改前值（先用 product_search / product_detail 取真值）后重试",
            )

        data: Dict[str, Any] = dict(response.get("data") or {})
        rows = [_preview_row(batch_type, it) for it in normalized]
        data["batchType"] = batch_type
        data["preview"] = rows
        # 扁平字段：LLM 直接把它交给 interact(component=confirm, fields=…)（逐条 商品/改前/改后）
        data["fields"] = [f for row in rows for f in row["fields"]]
        logger.info(f"[product_batch_update] preview {batch_type} N={len(normalized)} "
                    f"batch_id={data.get('batchId')} tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message=(f"已生成批量预演（{len(normalized)} 条，batch_id={data.get('batchId')}）："
                     "请把返回的 fields 用 interact(component=confirm, fields=…) 展示**逐条「改前 → 改后」**"
                     "给商家确认，商家点卡后再调本工具 action=execute, batch_id=… 执行；"
                     "执行后如发现改错，可用 action=revert 撤销（逐条还原为改前值）。"),
            summary=f"批量预览 {len(normalized)} 条（{batch_type}），等待商家确认",
        )

    # ── action=execute：执行批次（必须带 preview 产生的 batch_id）─────────────
    async def _execute_batch(self, context: ToolContext, batch_id: Optional[str]) -> ToolResult:
        if not _present(batch_id):
            return ToolResult(
                success=False,
                error="batch_preview_required",
                message="批量执行被拒：没有批次号（batch_id）",
                suggestion=("禁止跳过预览直接执行：先调 action=preview 生成批次（返回 batch_id 与逐条"
                            "「改前 → 改后」），把预览用 interact(component=confirm, fields=…) 给商家看过、"
                            "商家点卡之后，再带 batch_id 调 action=execute。"),
            )
        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/agent/batches/{batch_id}/execute",
            json_data={},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "批量执行失败") if isinstance(err, dict) else str(err)
            return admin_api_failure(
                response, error=msg, message=f"批量执行失败: {msg}",
                suggestion=("批量执行失败：请按返回的 error.code 处理（批次不存在/状态不允许执行等），"
                            "不要把失败说成已完成；必要时引导商家在商品列表页 /products 核对"),
            )

        data: Dict[str, Any] = dict(response.get("data") or {})
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        ok = sum(1 for r in results if r.get("success"))
        failed = [r for r in results if not r.get("success")]
        logger.info(f"[product_batch_update] execute batch_id={batch_id} ok={ok} fail={len(failed)} "
                    f"tenant={context.tenant_id}")
        # 部分失败**逐条报告、不做整体回滚**（契约 §五 判据 3）：回滚会掩盖真问题。
        # 服务端的失败项 `error` 已是「资源ID: 原因」文案 ⇒ 不重复拼 resourceId
        detail = "；".join(str(r.get("error") or "失败") for r in failed[:5])
        # `revertible` 是服务端的**可撤销性真值**（true ⇔ status ∈ done/partial，实测字段名）：
        # 只有它为真时才承诺撤销 —— 否则就是"说了做不到"（#5303 改价预览同族的口径纪律）。
        revert_line = (
            f"如发现改错，可调本工具 action=revert, batch_id={batch_id} **撤销**（逐条还原为改前值）。"
            if data.get("revertible") is not False else
            f"本批次当前**不可撤销**（revertible=false，status={data.get('status')}）—— 请如实告知商家，"
            "不要在商品列表页之外另做补偿性改动。"
        )
        return ToolResult(
            success=True,
            data=data,
            message=(f"批量执行完成（batch_id={batch_id}）：成功 {ok} 条 / 失败 {len(failed)} 条 —— "
                     "逐条结果见 results，**不做整体回滚**（部分失败逐条报告）。"
                     + (f"失败条目：{detail}。" if failed else "")
                     + revert_line),
            summary=f"批量执行 {len(results)} 条：成功 {ok} / 失败 {len(failed)}",
        )

    # ── action=revert：撤销批次（逐条还原 old_value）─────────────────────────
    async def _revert_batch(self, context: ToolContext, batch_id: Optional[str]) -> ToolResult:
        if not _present(batch_id):
            return ToolResult(
                success=False,
                error="batch_preview_required",
                message="批量撤销被拒：没有批次号（batch_id）",
                suggestion=("撤销必须点名批次：先调 action=preview 生成批次拿到 batch_id"
                            "（或从本会话此前执行成功的批次里取），再调 action=revert, batch_id=…；"
                            "不要凭空编造批次号。"),
            )
        client = get_admin_api_client()
        response = await client.post(
            f"/api/admin/agent/batches/{batch_id}/revert",
            json_data={},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
        if not response.get("success"):
            err = response.get("error", {})
            msg = err.get("message", "撤销失败") if isinstance(err, dict) else str(err)
            return admin_api_failure(
                response, error=msg, message=f"撤销失败: {msg}",
                suggestion="撤销失败：请先只读查询该批次状态后再决定（不可撤销 = 状态非 done/partial 或已撤销）",
            )

        data: Dict[str, Any] = dict(response.get("data") or {})
        results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
        ok = sum(1 for r in results if r.get("success"))
        failed = [r for r in results if not r.get("success")]
        # `skipped` = 执行时本就失败的条目（撤销时报 skipped + success=true，服务端口径）
        # ⇒ 单独计数，别把它混进"还原成功 N 条"（那是一句会误导商家的话）。
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        logger.info(f"[product_batch_update] revert batch_id={batch_id} ok={ok} fail={len(failed)} "
                    f"tenant={context.tenant_id}")
        return ToolResult(
            success=True,
            data=data,
            message=(f"已撤销批次 {batch_id}：逐条**还原**为改前值（old_value）—— "
                     f"成功 {ok} 条 / 失败 {len(failed)} 条"
                     + (f"（其中 {skipped} 条是执行时本来就失败的条目，撤销时跳过）。" if skipped else "。")
                     + "逐条结果见 results。"),
            summary=f"批量撤销 {len(results)} 条：成功 {ok} / 失败 {len(failed)}",
        )