"""
AI 智能客服系统 - 客户管理 Tool

管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。
"""

import asyncio
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.briefing.customer_profile import HAS_TRUTH, MAX_VIEW_ROWS, customer_profile
from app.briefing.customer_value import (
    FIELD_LABELS as VALUE_LABELS,
    NO_TRUTH_REASONS as VALUE_NO_TRUTH_REASONS,
    customer_value,
)
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED
from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client


# 操作类型
VALID_ACTIONS = {"list", "detail", "list_tags", "profile_view", "value_view"}

#: 具名跨域视图 `customer_profile`（族 3 · 包 3，issue #5456，**按需**消费）的端点。
#: 与 `CustomerController` 的 `@GetMapping("/api/admin/customers/profile-view")` 逐字相同，
#: 权限码同为 `customer:view`（与客户列表/详情同码）—— 一致性由单测机械钉住，不许凭语义推测。
PROFILE_VIEW_ENDPOINT = "/api/admin/customers/profile-view"

#: 具名跨域视图 `customer_value`（族 3 · 包 4 / V1，issue #6217）的**取数面**：三条**既有**只读端点。
#: 端点字面量按本仓风格留在**调用点**（静态归属机具只认调用点的字符串字面量）；常量与调用点
#: 字面量的一致性由单测机械钉住。权限码逐条对齐（`CustomerController` / `OrderController` /
#: `AfterSalesController` 的 `@RequirePermission`）：
#: 客户 `customer:view`、订单 `order:list`、售后 `after_sales:view`。
VALUE_VIEW_CUSTOMERS_ENDPOINT = "/api/admin/customers"
VALUE_VIEW_ORDERS_ENDPOINT = "/api/admin/orders"
VALUE_VIEW_AFTER_SALES_ENDPOINT = "/api/admin/after-sales"

#: 跨域取数的每面行数上限（有界是硬前提；截断由 `row_meta.truncated` **显式**声明）
VALUE_VIEW_FETCH_LIMIT = 200
#: 复购 / 让利 / 退货率的观察窗口（天）—— 与 `customer_value.RECENT_WINDOW_DAYS` 同口径
VALUE_VIEW_WINDOW_DAYS = 90

# 客户档案可写字段（单一事实源 = admin-api CustomerProfile 列 ∩ CustomerService.updateCustomer
# 的非空拷贝白名单）。写路径只允许下发这些 key，其余一律显式报错——禁止原样透传后由 admin-api
# 静默丢弃（Spring 默认 FAIL_ON_UNKNOWN_PROPERTIES=false → HTTP 200 但数据不落库 = 假成功，issue #3551）。
# 跨端字段契约由 tests/test_tool_field_name_contract.py 强制：既解析 CustomerProfile.java 的列，
# 也解析 CustomerService.updateCustomer 的非空拷贝白名单 —— 即上面「交集」这条口径现在是**被判据强制的**
# （issue #4115 之前只校验前者：4 个新列两边都「对得上」，却照样静默丢弃 + 谎报成功）。
WRITABLE_FIELDS = frozenset({
    "wechatNickname", "phone", "gender",
    "regionProvince", "regionCity", "regionDistrict",
    "vipLevel", "customerStatus", "agentNotes", "tags", "customFields",
    # 工艺画像与常用物流（issue #3984，V47，M2-D）
    "craftMode", "craftProfile", "defaultLogisticsType", "defaultLogisticsCompany",
    # 默认收货信息（issue #4419，V70）：收货人姓名/电话/详细地址。
    # 与 admin-api CustomerService.updateCustomer 的非空拷贝白名单**必须同集合**
    # （跨端契约由 tests/test_tool_field_name_contract.py 强制）。
    "defaultReceiverName", "defaultReceiverPhone", "defaultReceiverAddress",
})

# 姓名别名 → canonical 列名：客户实体无 name/nickname/realName 列，姓名存 wechatNickname
# （读路径 _list_customers/_detail_customer 已按同序回退，写路径必须对齐，否则静默丢弃 = 谎报成功）。
NAME_ALIAS_TO_CANONICAL = {"name": "wechatNickname", "nickname": "wechatNickname", "realName": "wechatNickname"}

# craftMode 允许值（单一事实源 = V47 迁移的列注释 / CustomerProfile#craftMode javadoc；
# admin-api CustomerService.requireValidCraftMode 是同口径的服务端兜底，非法值 400 + suggestion）。
# 本层提前拦下：省一轮注定失败的写请求，并给出比「更新失败」更可行动的提示（issue #4115）。
CRAFT_MODES = frozenset({"standard", "economy", "self_quoted"})


def normalize_update_data(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """把 update 的 data 归一化为 CustomerProfile 真实列名 payload。

    返回 (payload, rejected)；rejected 非空时调用方必须显式报错且**不得发起写请求**
    （既不静默忽略、也不部分写入——两者都会让用户看到假成功）。
    """
    payload: Dict[str, Any] = {}
    rejected: List[str] = []
    for key, value in data.items():
        canonical = NAME_ALIAS_TO_CANONICAL.get(key, key)
        if canonical not in WRITABLE_FIELDS:
            rejected.append(key)
            continue
        # 显式 wechatNickname 优先于姓名别名（两者同时出现时以 canonical 为准）
        if canonical == "wechatNickname" and key != "wechatNickname" and "wechatNickname" in payload:
            continue
        payload[canonical] = value
    return payload, sorted(rejected)


class CustomerManageTool(BaseTool):
    """客户管理 Tool

    管理客户档案，支持查询客户列表、客户详情、更新档案、管理客户标签。

    使用场景：
    - 查询客户列表（按关键词、来源渠道、VIP等级筛选）
    - 查看客户详细档案
    - 更新客户信息
    - 给客户打标签或移除标签
    - 管理标签库（创建、更新、删除标签）
    """

    name = "customer_manage"
    description = (
        "【触发】用户问'客户''顾客''VIP''客户档案''客户标签''给XX打标签''查XX电话'时调用。"
        "【参数】action 必填：**只有 list / detail / list_tags / profile_view / value_view 五个只读 action**（B 端已只读化，issue #5247）。"
        "list 可按 keyword(名称/手机号) 搜索；detail 需 customer_id（32 位 UUID，先 list 查出真实 UUID，"
        "禁止传手机号）；list_tags 列出全店客户标签；"
        "profile_view = 客户画像视图（逐字段告诉你**哪些字段有真值、哪些没有** —— 没有真值的字段一律「未知」，"
        "不得读成 0 元/从未发生；问「客户画像 / 这个客户消费多少 / 复购率 / RFM 评分」时用它）。"
        "value_view = 客户价值分层 / **流失预警**视图（跨客户排序：距上次下单天数 + 窗口内复购单数 + "
        "消费额 + 让利率 + 退货率 + 标签；问「哪些老客户最近不下单了 / 谁最值得维护 / 客户流失 / "
        "该回访谁」时用它 —— 它按流失风险分层排序，**不是**单个客户的画像）。"
        "【反例】查客户的历史订单用 order_query(keyword=XX)，不要用本工具；"
        "员工账号用 employee_manage，角色权限用 role_manage。"
        "【反例】改客户资料/打标签/删标签**不在本工具能力内**——引导用户到后台「客户列表」页面自行操作。"
        "【口径】value_view 依赖**三条既有只读端点**（客户 / 订单 / 售后）⇒ 需要同时持有 "
        "customer:view、order:list、after_sales:view 三个权限码；缺哪个会**点名**说清。"
        "该视图里「未接线」的字段（欠款 / 客单价 / 最近活跃天数）在既有端点里**根本没有来源**"
        "⇒ 一律为「未知」，**不是 0 元、不是「从未发生」**。"
        "【标注】READONLY — 纯查询，不含任何写 action"
    )
    # 权限码（admin-api 目录）：issue #5246 起 `CustomerController` 的读面 `customer:view`、
    # 写面（改/删客户、标签增删）`customer:create`（此前整类挂在读码上，只读持有者能删客户）。
    required_permissions = ["customer:view"]  # B 端只读化（#5247）：写码 customer:create 已随写 action 一并移除

    read_only = True
    read_only_actions = {"list", "detail", "list_tags", "profile_view", "value_view"}  # 只读 action 免确认拦截
    idempotent = False   # 创建/删除非幂等

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：list（客户列表）/ detail（客户详情）/ list_tags（标签列表）/ profile_view（客户画像视图，逐字段标注真值来源）/ value_view（客户价值分层 / 流失预警视图，跨客户按流失风险排序）—— 均为只读",
                "enum": ["list", "detail", "list_tags", "profile_view", "value_view"],
            },
            "customer_id": {
                "type": "string",
                "description": "客户 32 位 UUID。detail/update/add_tag/remove_tag 时必填。必须先通过 customer_manage(list) 查出真实 UUID，禁止传手机号或姓名",
            },
            "page": {
                "type": "integer",
                "description": "页码，默认 1（list 时可选）",
                "default": 1,
            },
            "size": {
                "type": "integer",
                "description": "每页数量，默认 10（list 时可选）",
                "default": 10,
            },
            "keyword": {
                "type": "string",
                "description": "搜索关键词，支持客户名称、手机号（list 时可选）",
            },
            "source_channel": {
                "type": "string",
                "description": "来源渠道筛选（list 时可选）",
            },
            "vip_level": {
                "type": "string",
                "description": "VIP等级筛选（list 时可选）",
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        context: ToolContext,
        action: str,
        customer_id: Optional[str] = None,
        page: int = 1,
        size: int = 10,
        keyword: Optional[str] = None,
        source_channel: Optional[str] = None,
        vip_level: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        tag_id: Optional[str] = None,
        name: Optional[str] = None,
        color: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行客户管理操作"""
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限执行客户管理操作",
                suggestion="请联系管理员获取执行客户管理操作权限",
            )

        # 参数校验
        if action not in VALID_ACTIONS:
            return ToolResult(
                success=False,
                error=f"无效的操作类型: {action}",
                message=f"不支持的操作类型，可选：{', '.join(sorted(VALID_ACTIONS))}",
                suggestion="请从工具说明里的可选操作类型中选一个后重试，不要自行改用其它 action",
            )

        try:
            if action == "list":
                return await self._list_customers(context, page, size, keyword, source_channel, vip_level)
            elif action == "detail":
                return await self._detail_customer(context, customer_id)
            elif action == "list_tags":
                return await self._list_tags(context)
            elif action == "profile_view":
                return await self._profile_view(context)
            elif action == "value_view":
                return await self._value_view(context)
            else:
                return ToolResult(
                    success=False,
                    error=f"未知操作: {action}",
                    message="不支持的操作类型",
                    suggestion="请选择支持的操作类型，查看工具说明了解可用操作",
                )

        except Exception as e:
            logger.error(f"[customer-manage] Error: action={action}, error={type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                message="客户管理操作失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

    async def _list_customers(
        self,
        context: ToolContext,
        page: int,
        size: int,
        keyword: Optional[str],
        source_channel: Optional[str],
        vip_level: Optional[str],
    ) -> ToolResult:
        """查询客户列表"""
        page = int(page) if page else 1
        size = int(size) if size else 10

        params: Dict[str, Any] = {"page": page, "size": size}
        if keyword:
            params["keyword"] = keyword
        if source_channel:
            params["sourceChannel"] = source_channel
        if vip_level:
            params["vipLevel"] = vip_level

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/customers",
            params=params,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="客户列表查询失败，请稍后重试",
                suggestion="请稍后重试，如持续失败请联系技术支持",
            )

        data = response.get("data", {})
        records = data.get("items", [])
        total = data.get("total", 0)

        customers = []
        for record in records:
            raw_phone = record.get("phone") or ""
            # 脱敏：列表接口对手机号中间4位打码，防止批量泄露
            masked_phone = (raw_phone[:3] + "****" + raw_phone[7:]) if len(raw_phone) >= 11 else raw_phone
            customers.append({
                "id": record.get("id"),
                # 生产回归修复：admin-api 客户数据无 name 字段（存 wechatNickname/nickname），
                # 旧实现只读 name → 黄金策显示"姓名字段都为空"。逐级回退。
                "name": record.get("name")
                        or record.get("wechatNickname")
                        or record.get("nickname")
                        or record.get("realName")
                        or "",
                "phone": masked_phone,
                "source_channel": record.get("sourceChannel"),
                "vip_level": record.get("vipLevel"),
                "tags": record.get("tags", []),
                "created_at": record.get("createdAt"),
            })

        logger.info(f"[customer-manage] Listed {len(customers)} customers, total={total} | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={
                "customers": customers,
                "total": total,
                "page": page,
                "size": size,
            },
            message=f"找到 {total} 个客户" if total > 0 else "未找到符合条件的客户",
        )

    async def _detail_customer(
        self,
        context: ToolContext,
        customer_id: Optional[str],
    ) -> ToolResult:
        """查询客户详情"""
        if not customer_id:
            return ToolResult(
                success=False,
                error="缺少客户 ID",
                message="查询客户详情时必须提供客户 ID（customer_id）",
                suggestion="缺少 customer_id，请先用 customer_manage 的 list 操作按姓名或手机号搜到客户后重试",
            )

        client = get_admin_api_client()
        response = await client.get(
            f"/api/admin/customers/{customer_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="客户详情查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", {})
        logger.info(f"[customer-manage] Detail customer_id={customer_id} | tenant={context.tenant_id}")

        # 姓名展示回退（生产回归：admin-api 详情同样无 name 字段）
        display_name = (data.get("name") or data.get("wechatNickname")
                        or data.get("nickname") or data.get("realName") or "")
        return ToolResult(
            success=True,
            data=data,
            message=f"客户【{display_name}】的详细信息",
        )
    async def _profile_view(self, context: ToolContext) -> ToolResult:
        """客户画像视图（具名跨域视图 `customer_profile` 的**按需**消费，issue #5456）。

        披露纪律与族 3 包 2（`briefing_query` 的 `product_health`）同一份 —— 消息是模型的**唯一**
        输入源，消息里没有的兜底模型编不出来：

        1. 🔴 **「未知」≠「0」**：声明无真值的字段**逐条点名**，并说清它们一律是「未知」（不是 0、
           不是「从未发生」、不是默认值）—— 不说这句，模型会把 `null` 讲成「消费 0 元」；
        2. **未接线 / 本次不完整**各自点名 + 原因（本次没检查 / 不完整 ⇒ 不许读成「没问题」）；
        3. **有界不静默**：输出被上限截断时点出「只列前 N 位，共 M 位」。
        """
        client = get_admin_api_client()
        response = await client.get(
            # 🔴 端点字面量必须留在**调用点**：静态归属机具只认调用点的字符串字面量（写成模块常量会让
            # 本工具被判成「无 admin-api 调用点」⇒ 权限对账两条判据一起红）；常量与调用点字面量的一致性
            # 由单测机械钉住（`tests/test_customer_manage.py`）。
            "/api/admin/customers/profile-view",
            params={"limit": MAX_VIEW_ROWS},
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(
                response,
                error=error_msg,
                message="客户画像查询失败",
                suggestion="请稍后重试；若持续失败，可先用 customer_manage 的 list 操作查看客户列表",
            )

        snapshot = response.get("data") or {}
        result = customer_profile(snapshot, tenant_id=context.tenant_id)
        fields = result["fields"]
        no_truth = result["no_truth_fields"]
        # 「声明无真值」（系统没有这项能力）与「本次未接线」（装配层没给数据）是**两回事** ⇒ 分开点名
        unwired = [name for name, entry in fields.items()
                   if entry["status"] == NOT_WIRED and entry["truth"] == HAS_TRUTH]
        incomplete = [(name, entry["reason"]) for name, entry in fields.items()
                      if entry["status"] == INCOMPLETE]
        logger.info(
            "[customer-manage] profile_view rows={} total={} no_truth={} not_wired={} incomplete={}",
            result["count"], result["rows_total"], len(no_truth), len(unwired), len(incomplete))

        message = f"客户画像视图：{result['count']} 位客户"
        if result["truncated"]:
            message += f"（视图只列前 {result['count']} 位，共 {result['rows_total']} 位）"
        if no_truth:
            # 关键口径：无真值**不是** 0 元 / 从未发生 —— 不许让模型把「读不到」讲成「就是 0」
            message += (
                f"。⚠️ 其中 {len(no_truth)} 个字段**没有真值来源**（系统没有采集/计算逻辑）"
                f"⇒ 这些字段一律为「未知」，**不是 0、不是「从未发生」、不是默认值**："
                f"{'、'.join(no_truth)}"
            )
        if result["declaration"]["status"] != WIRED:
            message += f"。⚠️ {result['declaration']['reason']}"
        if unwired:
            message += (f"。⚠️ 以下字段本次未接线：{'、'.join(unwired)}"
                        " —— 这些方面本次没有数据，请勿理解为均为 0")
        if incomplete:
            detail = "；".join(f"{name}：{reason}" for name, reason in incomplete if reason)
            message += (f"。⚠️ 以下字段本次数据不完整，其结论不可当作「没问题」："
                        f"{'、'.join(name for name, _ in incomplete)} —— {detail}")
        # data 就是**视图本体**（有界：≤ MAX_VIEW_ROWS 行）—— 不再包一层，也不回灌原始快照
        return ToolResult(success=True, data=dict(result), message=message)

    # ── 具名跨域视图 `customer_value`（族 3 · 包 4 / V1，issue #6217）────────────────

    async def _fetch_rows(self, context: ToolContext, endpoint: str, page: int,
                          size: int) -> Tuple[Optional[List[Dict[str, Any]]], str]:
        """取一条**既有只读端点**的行数组 ⇒ `(rows | None, 失败原因)`。

        容错取列表（`PageResponse` 的 `items` / `records` / `list` / `rows` 与裸列表都收）；
        **失败一律返回 `None` + 原因**（不返回 `[]` —— 空列表会被读成「这个租户没有订单」，
        而事实是「没读到」）。

        🔴 三条端点的路径在 `client.get(...)` 的实参位置**逐条写成字面量**：静态归属门禁
        （`tests/test_tool_payload_backend_contract.py::test_payload_calls_are_attributable_to_an_endpoint`）
        只认调用点的字面量 —— 用变量拼路径会让这个调用点**静默脱离**门禁射程（比判红更糟）。
        这里刻意**不用循环**：循环会把路径变回变量，正是要避开的形态。同理 `params` 在调用点写成
        **字面量 dict**（键集静态可读）—— 传形参会让这些调用点落进「动态登记站点」名单。
        """
        client = get_admin_api_client()
        try:
            if endpoint == VALUE_VIEW_CUSTOMERS_ENDPOINT:
                response = await client.get("/api/admin/customers",
                                            params={"page": page, "size": size},
                                            tenant_id=context.tenant_id,
                                            user_id=context.user_id)
            elif endpoint == VALUE_VIEW_ORDERS_ENDPOINT:
                response = await client.get("/api/admin/orders",
                                            params={"page": page, "size": size},
                                            tenant_id=context.tenant_id,
                                            user_id=context.user_id)
            elif endpoint == VALUE_VIEW_AFTER_SALES_ENDPOINT:
                response = await client.get("/api/admin/after-sales",
                                            params={"page": page, "size": size},
                                            tenant_id=context.tenant_id,
                                            user_id=context.user_id)
            else:  # fail-closed：不认识的端点**不猜路径**（否则会去请求一个不存在的地址）
                return None, f"未登记的端点（不在本视图的三条取数面内）：{endpoint}"
        except Exception as exc:  # 网络 / 超时 / 熔断：**归因到这一面**，不炸掉其它两面
            logger.error("[customer-manage] value_view 端点异常 endpoint={}: {}: {}",
                         endpoint, type(exc).__name__, exc)
            return None, f"{type(exc).__name__}: {exc}"

        if not response.get("success"):
            error = response.get("error")
            message = error.get("message", "查询失败") if isinstance(error, dict) else str(error or "查询失败")
            return None, message
        data = response.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)], ""
        if isinstance(data, dict):
            for key in ("items", "records", "list", "rows"):
                value = data.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)], ""
            return [], ""
        return None, "响应形态不可识别（data 既不是列表也不是对象）"

    @staticmethod
    def _assemble(customers: List[Dict[str, Any]], orders: List[Dict[str, Any]],
                  tickets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """把三条端点的行**归一化**成视图消费的快照（列名归一化是**装配层**的口径）。

        🔴 归一化只改键名、不改语义：`customer_id` ← 客户 `id`；`customer_phone` ← 订单
        `customerPhone`（**归并主键**，既有订单读面不含客户 id ⇒ 这是唯一可用联接键）；
        金额列直取端点原值（`null` 保持 `null` —— **不折 0**）。
        """
        def bounded(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
            return rows[:VALUE_VIEW_FETCH_LIMIT], len(rows) > VALUE_VIEW_FETCH_LIMIT

        customer_rows, customers_truncated = bounded(customers)
        order_rows, orders_truncated = bounded(orders)
        ticket_rows, tickets_truncated = bounded(tickets)

        def meta(rows: List[Dict[str, Any]], truncated: bool) -> Dict[str, Any]:
            return {"limit": VALUE_VIEW_FETCH_LIMIT, "count": len(rows), "truncated": truncated}

        customers_out = [{
            "customer_id": row.get("id"),
            "name": (row.get("name") or row.get("wechatNickname") or row.get("nickname")
                     or row.get("realName")),
            "phone": row.get("phone"),
            "vip_level": row.get("vipLevel"),
            "source_channel": row.get("sourceChannel"),
            "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
        } for row in customer_rows]
        orders_out = [{
            "order_no": row.get("orderNo"),
            "customer_phone": row.get("customerPhone"),
            "created_at": row.get("createdAt"),
            "total_amount": row.get("totalAmount"),
            "actual_amount": row.get("actualAmount"),
        } for row in order_rows]
        tickets_out = [{
            "ticket_id": row.get("id"),
            "customer_id": row.get("customerId"),
            "ticket_type": row.get("ticketType"),
            "created_at": row.get("createdAt"),
        } for row in ticket_rows]

        return {
            "row_fields": {
                # 键 = 视图模块的契约键（`customer_value.PROFILE_ARRAY`）—— 装配与消费两侧同名，
                # 改名时两侧一起红（`test_endpoint_literals_are_pinned_three_ways` 同族的机械判据）
                "profile": ["customer_id", "name", "phone", "vip_level", "source_channel", "tags"],
                "orders": ["order_no", "customer_phone", "created_at", "total_amount",
                           "actual_amount"],
                "tickets": ["ticket_id", "customer_id", "ticket_type", "created_at"],
            },
            "row_meta": {
                "profile": meta(customers_out, customers_truncated),
                "orders": meta(orders_out, orders_truncated),
                "tickets": meta(tickets_out, tickets_truncated),
            },
            "window_days": VALUE_VIEW_WINDOW_DAYS,
            "profile": customers_out,
            "orders": orders_out,
            "tickets": tickets_out,
        }

    async def _value_view(self, context: ToolContext) -> ToolResult:
        """客户价值分层 / 流失预警视图（具名跨域视图 `customer_value` 的按需消费，issue #6217）。

        取数面 = **三条既有只读端点**（客户 / 订单 / 售后），并发取；任一条失败 ⇒ **fail-closed**
        （不拿半份数据出结论），并把失败的那一面与所需权限码**点名**（可归因）。

        披露纪律与 `profile_view` 同一份 —— 消息是模型的**唯一**输入源：

        1. 🔴 **「未知」≠「0」**：声明无真值的字段**逐条点名**并说清一律「未知」（不是 0 元、
           不是「从未发生」）；行级的 `*_basis` 说清「这一格为什么是 null」；
        2. **未接线 / 本次不完整**各自点名 + 原因（不完整 ⇒ 不许读成「没问题」）；
        3. **有界不静默**：输出被上限截断时点出「只列前 N 位，共 M 位」。
        """
        # 🔴 三条既有端点各自以**字面量**出现在调用点（静态归属机具只认调用点的字符串字面量；
        # 写成模块常量会让本工具被判成「无 admin-api 调用点」⇒ 权限对账判据一起红）。
        endpoints = (
            ("customers", VALUE_VIEW_CUSTOMERS_ENDPOINT, "customer:view"),
            ("orders", VALUE_VIEW_ORDERS_ENDPOINT, "order:list"),
            ("after_sales", VALUE_VIEW_AFTER_SALES_ENDPOINT, "after_sales:view"),
        )
        fetched = await asyncio.gather(
            self._fetch_rows(context, VALUE_VIEW_CUSTOMERS_ENDPOINT, 1, VALUE_VIEW_FETCH_LIMIT),
            self._fetch_rows(context, VALUE_VIEW_ORDERS_ENDPOINT, 1, VALUE_VIEW_FETCH_LIMIT),
            self._fetch_rows(context, VALUE_VIEW_AFTER_SALES_ENDPOINT, 1, VALUE_VIEW_FETCH_LIMIT),
        )

        failures = [(name, permission, reason)
                    for (name, _endpoint, permission), (rows, reason)
                    in zip(endpoints, fetched)
                    if rows is None]
        if failures:
            detail = "；".join(f"{name}（{permission}）：{reason}"
                              for name, permission, reason in failures)
            logger.warning("[customer-manage] value_view 取数失败：{}", detail)
            return ToolResult(
                success=False,
                error="cross_domain_fetch_failed",
                message=("客户价值视图取数失败 —— 该视图跨三条只读端点，缺任一面都无法出结论"
                         f"（fail-closed）：{detail}"),
                suggestion=("请确认当前账号同时具备 customer:view / order:list / after_sales:view "
                            "三个权限码；若只是临时故障请稍后重试，也可先用 customer_manage 的 list "
                            "查看客户列表"),
            )

        snapshot = self._assemble(*(rows or [] for rows, _reason in fetched))
        result = customer_value(snapshot, tenant_id=context.tenant_id, as_of=_dt.date.today())
        fields = result["fields"]
        no_truth = result["no_truth_fields"]
        # 「声明无真值」（系统没有这项能力）与「本次未接线」（装配层没给数据）是**两回事** ⇒ 分开点名
        unwired = [name for name, entry in fields.items()
                   if entry["status"] == NOT_WIRED and entry["truth"] == HAS_TRUTH]
        incomplete = [(name, entry["reason"]) for name, entry in fields.items()
                      if entry["status"] == INCOMPLETE]
        bands = result["band_counts"]
        logger.info(
            "[customer-manage] value_view rows={} total={} lost={} at_risk={} no_truth={} "
            "not_wired={} incomplete={}",
            result["count"], result["rows_total"], bands.get("lost"), bands.get("at_risk"),
            len(no_truth), len(unwired), len(incomplete))

        message = (f"客户价值分层 / 流失预警视图（截至 {result['as_of']}，窗口 "
                   f"{snapshot['window_days']} 天）：{result['count']} 位客户 —— "
                   f"已流失 {bands.get('lost', 0)} / 流失预警 {bands.get('at_risk', 0)} / "
                   f"活跃 {bands.get('active', 0)} / 分层未知 {bands.get('unknown', 0)}"
                   "（分层未知 = 该客户在订单端点里**没有订单行**，即「不知道」，"
                   "**不是**「活跃」也**不是**「已流失」）")
        if result["truncated"]:
            message += (f"。⚠️ 视图只列前 {result['count']} 位，共 {result['rows_total']} 位"
                        "（按流失风险排序取前段）")
        if no_truth:
            message += (f"。⚠️ 其中 {len(no_truth)} 个字段**没有真值来源**（既有只读端点里没有这个列）"
                        f"⇒ 这些字段一律为「未知」，**不是 0、不是「从未发生」、不是默认值**："
                        + "、".join(f"{VALUE_LABELS.get(name, name)}（{name}）" for name in no_truth)
                        + "。逐条原因："
                        + "；".join(f"{name}：{VALUE_NO_TRUTH_REASONS[name]}"
                                    for name in no_truth if name in VALUE_NO_TRUTH_REASONS))
        if unwired:
            message += (f"。⚠️ 以下字段本次未接线：{'、'.join(unwired)}"
                        " —— 这些方面本次没有数据，请勿理解为均为 0")
        if incomplete:
            detail = "；".join(f"{VALUE_LABELS.get(name, name)}：{reason}"
                               for name, reason in incomplete if reason)
            message += (f"。⚠️ 以下字段本次数据不完整，其结论不可当作「没问题」："
                        f"{'、'.join(VALUE_LABELS.get(name, name) for name, _ in incomplete)}"
                        f" —— {detail}")
        # data 就是**视图本体**（有界：≤ VALUE_MAX_VIEW_ROWS 行）—— 不再包一层，也不回灌原始快照
        return ToolResult(success=True, data=dict(result), message=message)

    async def _list_tags(self, context: ToolContext) -> ToolResult:
        """查询所有客户标签"""

        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/customer-tags",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )

        if not response.get("success"):
            error_msg = response.get("error", {}).get("message", "查询失败")
            return admin_api_failure(response,
                error=error_msg,
                message="标签列表查询失败",
                suggestion="请检查输入参数是否正确，或稍后重试",
            )

        data = response.get("data", [])
        logger.info(f"[customer-manage] Listed {len(data)} tags | tenant={context.tenant_id}")

        return ToolResult(
            success=True,
            data={"tags": data, "count": len(data)},
            message=f"共 {len(data)} 个客户标签",
        )