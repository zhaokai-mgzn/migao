# case_ids: DF-017, DF-007
"""工具访问由 **admin-api 权限码**（JWT `permissions` claim）驱动 — 常驻 L0/L2 守卫（issue #4106 F3/F4）。

## 病灶形状（`[ai-chat.permission-layers]` 契约与实现不符）

`.github/templates/ai-chat.yml` 的 `[ai-chat.permission-layers]` 写的是
「权限两层：角色检查（allowed_roles）+ 细粒度权限（required_permissions）」，
`app/agents/agent_router.py` 的注释与 issue #2773 的收口说明更进一步：
「米宝工具级权限仍由 permissions claim 强控（required_permissions）」。

**但实现不是这样**：`BaseTool.check_permission` 只在 `required_permissions` **非空**时
才看 `context.permissions`，而 38 个工具类里只有 1 个（`employee_manage`）声明了它 ——
其余 37 个**纯靠手写的 `allowed_roles` 角色码白名单**授权（F3：细粒度层是空护栏）。

白名单随后**必然漂移**（F4）：`category_manage` / `product_update` / `sku_update` /
`processing_item_manage` / `role_manage` /
`settings_manage` 等把 `allowed_roles` 写死成 `["admin", "tenant_admin"]`，
而 admin-api 的角色目录里 `operator` / `product_manager` 明明持有对应权限码
（真值源 `RegistrationService.initializeDefaultRolesAndPermissions` 的 18 码目录 +
`RoleService.getPermissionCodesForRole`）⇒ **持有权限码的员工被工具判「权限不足」**
（假拒绝），模型随后无法向用户解释任何东西。

## 本文件锁的不变式（每条都有反例输入）

1. `TestDeclaredCodesMatchReviewedMapping` —— 每个声明了权限码的工具，其
   `required_permissions` 必须**逐字**等于下表（映射按 admin-api 的
   `@RequirePermission` 标注 + 资源 CRUD 语义核定，表在下）；
2. `TestPermissionCodeIsTheGate` —— **表驱动**：对每个 B 端工具 × 每个商户角色，
   `check_permission` 的结果必须**恰好**等于「该角色的目录里有没有这个码」
   （`admin` 的 `*` 通配除外）——既有正向（持有码 ⇒ 放行）也有负向（无码 ⇒ 拒绝）；
3. `TestRoleListIsNotTheGate` —— 反向证据：**同时声明码与角色白名单**的替身上，判定必须
   跟着**权限码**走（`tenant_admin` 列进白名单、目录无码 ⇒ 拒；`operator` 持码、不在白名单
   ⇒ 放行）。**不再拿真工具的 `allowed_roles` 当前提** —— 已声明码的工具按 ④ 不得声明白名单，
   那时读到的是 `BaseTool` 默认值，对任何工具都成立 ⇒ 空前提（#4149 G9 实测）；
4. `TestCodedToolsCarryNoRoleList` —— 静态锁：声明了权限码的工具**不得**再声明
   `allowed_roles`（否则是第二份会漂移的、且实际不生效的假门禁）；
5. 判据自身**可红 + 不恒真**（`TestGuardsAreNotVacuous`：注入式夹具必报、合法输入必不报）。

## 权限码映射的核定口径（不猜）

- 目录 18 码：`RegistrationService.java` 第 548-567 行（`initializeDefaultRolesAndPermissions`）。
- 角色默认码：该方法第 587-601 行的 `attachDefaultPermissions`（DB 口径，
  `V29`/`V32`/`V43` 对存量租户补齐）+ `RoleService.getPermissionCodesForRole` 第 289-314 行
  （无 `role_permissions` 记录时的硬编码回退）。`admin` 恒为 `["*"]`
  （`RoleService.getUserPermissions` 第 210-211 行）。
- 端点→码：各 `controller/*.java` 的 `@RequirePermission`（类级 + 方法级）。
- **写操作一律取「写码」**：`/api/admin/agent/**` 的若干写端点只挂了类级读码
  （如 `AgentProductController` 类级 `product:list` 覆盖 `PATCH /{id}` 改商品），
  按读码放行会让**只读持有者拿到写权限** ⇒ 写工具一律取该资源 CRUD 控制器的写码
  （商品写 → `product:create`，加工单写 → `processing:update`）。这是**收窄**，不是放宽。

## 明确不在本映射内的工具（对照，不是遗漏）

- **C 端也在用的双端工具**（`allowed_roles` 含 `customer`，如 `product_search` /
  `order_query` / `product_detail` / `order_create` / `curtain_calc`
  / `interact` / `validate_input` / `knowledge_search` 等）：C 端 JWT 没有权限码
  （`UserIdentity.permissions` 默认空、`customer`/`agent` 不是 `roles` 表角色）
  ⇒ 加码会让 C 端全量失效。**保持角色层**，本次不动。
  🔴 **issue #5247 改判**：`inventory_manage` 从本清单**移除** —— 它收窄为只读后不再是
  双端工具（严格执行 `product:list`，C 端恒拒；判据见
  `test_customer_without_codes_is_denied_on_every_coded_tool` 的 `c_end_reachable` 清单）。
  「双端」的机械口径自 #5246 起是工具自述的 `c_end_reachable`，**不是** `allowed_roles` 里
  有没有 `customer`（后者是 `BaseTool` 默认值，对每个未覆写 `allowed_roles` 的工具都成立）。
- `notification_manage`：`NotificationController` 的两个**读**端点（`GET /notifications` /
  `GET /notifications/unread-count`）**都没有** `@RequirePermission`（读面是自助语义）
  ⇒ 目录里没有对应码，角色层是**真正需要**的（工具层唯一保留角色白名单的 B 端工具）。
  🔴 **issue #5302 改判（settings 域收口）**：该工具**重新回到**角色层 ——
  它原来取的 `["system:manage", "employee:list"]` 全是**写路径的码**（前者 = `POST` 建通知，
  后者 = `create` 解析收件人用的 `GET /api/admin/users`）⇒ 写 action 删除后两个码都失去
  调用点（留着 = `employee:list` 把「通知中心」这个后台全员可见页收窄成"只有持码岗位可用"）。
  ⇒ `required_permissions = []` + 类体显式 `allowed_roles`（不含 C 端/幽灵角色），
  并登记进 `ROLE_GATED_B_SIDE_TOOLS`。
- `role_manage` / `settings_manage` 的码是 `system:manage`；对 `settings_manage` 而言
  该码是**读码**（三个读端点都是它）⇒ #5302 收窄为只读后**码不变**（无写码可去，
  该域读写同码的粒度债见 `tests/unit_ci_workflows/test_agent_permission_parity.py`
  的 `REGISTERED_RESIDUALS`「settings 域写面未注解」）。
- 🔴 **issue #5247 改判（B 端米宝只读化，用户裁定 2026-09-23）**：下列 8 把工具的写 action
  被删除 ⇒ 它们各自只保留**读码**（`after_sales_manage` / `category_manage` /
  `customer_manage` / `employee_manage` / `finance_api` / `inventory_manage` /
  `role_manage` / `session_manage`），另进场 6 把新只读工具
  （`briefing_query` / `craft_calc_config_query` / `inbound_order_query` /
  `operation_catalog_query` / `processing_order_set_query` / `stock_ledger_query`）。**表是唯一真值**：任何码的进出都必须
  在本表与 `EXPECTED_ALLOWED_ROLES` 里显式改判（判据见本文件 ①/②）。
  被删除的写 action 留下的**规则/映射**不在这里治理 —— 见
  `tests/test_tools_validate_input.py` 的 #5247 退役台账（单一台账，不抄第二份）。
- `tenant_admin`：admin-api 里**不存在**该角色（无 seed、无权限映射，
  `UserService.java` 第 49 行注释「历史遗留管理角色」）。它在 ai-agent 的 27 个工具里
  被放行、在 admin-api 侧所有 `@RequirePermission` 接口 403 ⇒ 修掉这个**跨服务口径断裂**
  属于本单预期结果（不是回归）。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.tools.base import CUSTOMER_ONLY_ROLES, BaseTool, ToolContext, ToolResult
from app.tools.registry import create_default_registry

# ──────────────────────────────────────────────────────────────────────────────
# 真值表（判据的唯一来源 —— 测试与红证夹具共用这一处，不写第二份）
# ──────────────────────────────────────────────────────────────────────────────

#: admin-api 权限目录（22 码，`RegistrationService` 的 defaultPermissions 逐条对齐；
#: 该判据按**集合**比对 ⇒ 新增码必须同批落在这里，否则「镜像腐烂 ⇒ 工具层按错码授权」判红）
PERMISSION_CATALOG = frozenset({
    "dashboard:view",
    "product:manage",
    "product:list",
    "product:create",
    "product:category",
    "processing:manage",
    "processing:view",
    "processing:update",
    # 入库单（V111，issue #5034）：与 V111 迁移的存量租户权限补齐**同源同码**
    "inbound:view",
    "inbound:create",
    "knowledge:manage",
    # 知识库**读**码（issue #5246）：读（卡片列表/搜索）与写（增删改/发布/归档）此前同用
    # `knowledge:manage` ⇒ 只想看看卡片的客服/运营必须被授予写权才进得去；本次按读写拆开。
    "knowledge:view",
    "order:list",
    "order:detail",
    "order:refund",
    # 售后工单**读**码（issue #5246）：此前列表/详情与建单/改状态同用 `order:refund`
    # （**处理退款**的写语义）⇒ 客服岗位默认权限不含它 ⇒ 客服经米宝查售后必 403。
    "after_sales:view",
    "customer:view",
    "finance:view",
    "agent:session",
    "employee:list",
    "employee:create",
    "system:manage",
    # issue #5246 第二批（用户裁定本轮一并收口）：订单/客户/财务/会话四域**拆出真写码** ——
    # 此前写动作挂在读码上（只读持有者因此拿到写能力，端点层也拦不住）。
    "order:update",
    "order:create",
    "customer:create",
    "finance:create",
    "agent:session:manage",
})

#: 商户角色的默认权限码（DB seed 口径；`admin` 运行时恒为 `*`）
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "operator": frozenset({
        "after_sales:view", "agent:session", "agent:session:manage",
        "customer:create", "customer:view", "dashboard:view",
        "employee:list", "finance:create", "finance:view",
        "inbound:create", "inbound:view", "knowledge:view",
        "order:create", "order:detail", "order:list", "order:refund", "order:update",
        "processing:manage", "processing:update", "processing:view",
        "product:category", "product:create", "product:list",
    }),
    "customer_service": frozenset({
        "after_sales:view", "agent:session", "agent:session:manage", "customer:view",
        "dashboard:view", "inbound:view", "knowledge:view",
        "order:detail", "order:list", "processing:view",
    }),
    "sales": frozenset({
        "customer:view", "dashboard:view", "inbound:view", "order:detail", "order:list",
        "processing:view", "product:list",
    }),
    "finance": frozenset({
        "dashboard:view", "finance:create", "finance:view", "inbound:view",
        "order:detail", "order:list", "processing:view",
    }),
    "product_manager": frozenset({
        "dashboard:view", "processing:manage", "product:category",
        "product:create", "product:list",
    }),
    "knowledge_editor": frozenset({"dashboard:view", "product:list"}),
    # 以下角色在 admin-api 权限目录里没有任何码（C 端角色 / 幽灵角色）
    "customer": frozenset(),
    "agent": frozenset(),
    "tenant_admin": frozenset(),
}

#: 工具 → 应声明的权限码（下表的「工具 × 角色」放行集由它推导，不手写第二遍）
TOOL_PERMISSION_CODES: dict[str, tuple[str, ...]] = {
    # issue #5246：读（list/detail）取新增的售后读码 `after_sales:view`。
    # 🔴 **issue #5247 改判（B 端米宝只读化，用户裁定 2026-09-23）**：写 action
    # （create/update_status）已从工具删除 ⇒ 写码 `order:refund` 随之退场 —— 这是**收窄**，
    # 不是放宽：工具自身再没有需要该码的调用面（残留的规则/映射由
    # `tests/test_tools_validate_input.py` 的 #5247 退役台账治理）。
    "after_sales_manage": ("after_sales:view",),
    # 批次账 / 省料读面（issue #5188）：码与 `StockBatchController` 各端点的
    # `@RequirePermission("product:list")` **逐字一致**（判据见
    # `tests/test_batch_stock_query.py::TestPermissionAlignment`）。
    "batch_stock_query": ("product:list",),
    # issue #5247 进场：简报卡（读面）取 `dashboard:view` —— 与
    # `DashboardController` 的 `@RequirePermission` 同码。
    "briefing_query": ("dashboard:view",),
    # issue #5247：码**未变**（`product:category`），变的只是工具本身收窄为只读（`tree`）。
    "category_manage": ("product:category",),
    # issue #5247 进场：算料配置读面 —— 配置读写同用 `processing:manage`
    # （`CraftCalcConfigController` 的 `@RequirePermission`），本工具只读、不写配置。
    "craft_calc_config_query": ("processing:manage",),
    # issue #5247 改判：写 action（create/update/打标签族）已删除 ⇒ 写码 `customer:create` 退场。
    "customer_manage": ("customer:view",),
    "dashboard_stats": ("dashboard:view",),
    # issue #5247 改判：写 action（create/update/delete/reset_password/toggle_status）已删除
    # ⇒ 写码 `employee:create` 退场（`idempotent = False` 也随之移除，见
    # `tests/test_tool_idempotent_retry_guard.py` 的抽样改判）。
    "employee_manage": ("employee:list",),
    # issue #5247 改判：写 action（create_transaction）已删除 ⇒ 写码 `finance:create` 退场。
    "finance_api": ("finance:view",),
    # issue #5247 进场：入库单读面（V111，issue #5034 的 `inbound:view`）—— 与
    # `InboundOrderController` 各端点的 `@RequirePermission` 同码。
    "inbound_order_query": ("inbound:view",),
    # issue #5246：库存读（query/low_stock_alert）= product:list。
    # 🔴 issue #5247 改判：写 action（adjust）已删除 ⇒ 写码 `product:create` 退场。
    "inventory_manage": ("product:list",),
    # issue #5246：知识卡片**读**码 knowledge:view（写/发布/归档仍 knowledge:manage）。
    "knowledge_search": ("knowledge:view",),
    "logistics_track": ("order:list",),
    # 🔴 issue #5302 改判：`notification_manage` 从本表**移出**（settings 域收口）——
    # 它的两个读端点都没有生效码 ⇒ 工具不持码、回到角色层（见 `ROLE_GATED_B_SIDE_TOOLS`
    # 与文件头 `notification_manage` 段）。原码 `["system:manage", "employee:list"]`
    # 全是写路径的码（create 端点 + create 的收件人解析）。
    "order_create": ("order:create", "product:list"),
    "order_manage": ("order:update",),
    "order_query": ("order:list",),
    # issue #5247 进场：加工项目录（店铺级）读面 —— 与 `ProcessingCatalogController` 同码
    # （与 `category_manage` 的 `product:category` 无关：那是**商品分类**，不是加工项）。
    "operation_catalog_query": ("processing:manage",),
    # issue #5246 改判：计件/报工/加工单读面取**加工面读码** processing:manage
    # （ProductionController 的方法级注解；原 order:list / processing:view 与端点生效码不符）。
    "piecework_query": ("processing:manage",),
    "processing_item_manage": ("processing:manage",),
    "processing_item_query": ("processing:manage",),
    "processing_order_generate": ("processing:update",),
    "processing_order_query": ("processing:manage",),
    # issue #5247 进场（加工套件 / 扫码循环，`ProcessingOrderSetController`）：三个端点均是
    # 方法级 `@RequirePermission("processing:manage")` ⇒ 与加工面读码同源（生产域暂无专属读码）。
    "processing_order_set_query": ("processing:manage",),
    "processing_order_update": ("processing:update",),
    # issue #5314：批量改价 / 批量上下架的端点码与**逐条写同码**（契约 §三「不新开权限面」；
    # 契约正文括注的 `product:update` 在权限目录里不存在 ⇒ 取「同码」这条更硬的判据）。
    "product_batch_update": ("product:create",),
    "product_detail": ("product:list",),
    "product_manage": ("product:create",),
    "product_search": ("product:list",),
    "product_update": ("product:create",),
    "production_progress_query": ("processing:manage",),
    "production_worklog_query": ("processing:manage",),
    # issue #5247：码**未变**（`system:manage` = admin 专属越权守卫，本表不放松），
    # 变的只是工具收窄为只读（list/all/detail/list_permissions）。
    "role_manage": ("system:manage",),
    # issue #5247 改判：写 action（assign/end）已删除 ⇒ 写码 `agent:session:manage` 退场
    # （读码 `agent:session` 不变）。
    "session_manage": ("agent:session",),
    "settings_manage": ("system:manage",),
    "sku_update": ("product:create",),
    # issue #5247 进场：库存台账（读面）取 `product:list` —— 与 `/api/admin/stock-ledger`
    # 端点的生效码同源（存量余额/流水是可被商品读码持有者看到的口径）。
    "stock_ledger_query": ("product:list",),
}

#: 每个工具**必须**放行的商户角色（除恒放行的 admin 外）—— 显式写死，
#: 映射一变本表就得跟着改，diff 里看得见「谁新拿到/谁被收回」。
EXPECTED_ALLOWED_ROLES: dict[str, frozenset[str]] = {
    # issue #5246：售后**读**码 `after_sales:view` 已授予客服/运营 ⇒ 客服经米宝查售后不再 403。
    "after_sales_manage": frozenset({"customer_service", "operator"}),
    # 批次/省料读面（issue #5188）：`product:list` 的持有角色（目录推导，不手抄）
    "batch_stock_query": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
    # issue #5247 进场：`dashboard:view` 的持有角色（目录推导，不手抄 —— 与 dashboard_stats 同集）。
    "briefing_query": frozenset({
        "customer_service", "finance", "knowledge_editor", "operator", "product_manager", "sales",
    }),
    "category_manage": frozenset({"operator", "product_manager"}),
    # issue #5247 进场：`processing:manage` 的持有角色（目录推导）。
    "craft_calc_config_query": frozenset({"operator", "product_manager"}),
    "customer_manage": frozenset({"customer_service", "operator", "sales"}),
    "dashboard_stats": frozenset({
        "customer_service", "finance", "knowledge_editor", "operator", "product_manager", "sales",
    }),
    "employee_manage": frozenset({"operator"}),
    "finance_api": frozenset({"finance", "operator"}),
    # issue #5247 进场：`inbound:view` 的持有角色（目录推导）。
    "inbound_order_query": frozenset({"customer_service", "finance", "operator", "sales"}),
    # issue #5246：库存读 = `product:list` ⇒ 持有该码者放行（目录推导）。
    # 🔴 issue #5247 改判：写码 `product:create` 随 `adjust` 退场 ⇒ 放行集**不变**
    # （`product:create` 的持有者恰好都持 `product:list`，diff 里看得见"没有谁被收回"）。
    "inventory_manage": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
    # issue #5246：知识库**读**码下发给客服 + 运营（本次新授予的两个岗位）。
    "knowledge_search": frozenset({"customer_service", "operator"}),
    "logistics_track": frozenset({"customer_service", "finance", "operator", "sales"}),
    # 🔴 issue #5302 改判：`notification_manage` 从本表**移出**（无码 ⇒ 回到角色层，
    # 放行集由类体 `allowed_roles` 决定，不再由权限码目录推导）。
    "order_create": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
    "order_manage": frozenset({"operator"}),
    "order_query": frozenset({"customer_service", "finance", "operator", "sales"}),
    # issue #5247 进场：`processing:manage` 的持有角色（目录推导）。
    "operation_catalog_query": frozenset({"operator", "product_manager"}),
    # issue #5246 改判：计件/报工/加工单读面 = `processing:manage` ⇒ 运营 + 商品主管。
    "piecework_query": frozenset({"operator", "product_manager"}),
    "processing_item_manage": frozenset({"operator", "product_manager"}),
    "processing_item_query": frozenset({"operator", "product_manager"}),
    "processing_order_generate": frozenset({"operator"}),
    "processing_order_query": frozenset({"operator", "product_manager"}),
    # issue #5247 进场：`processing:manage` 的持有角色（目录推导）。
    "processing_order_set_query": frozenset({"operator", "product_manager"}),
    "processing_order_update": frozenset({"operator"}),
    # issue #5314：与 `product_update` 同码 ⇒ 放行集**逐字相同**（目录推导，不额外授予）
    "product_batch_update": frozenset({"operator", "product_manager"}),
    "product_detail": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
    "product_manage": frozenset({"operator", "product_manager"}),
    "product_search": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
    "product_update": frozenset({"operator", "product_manager"}),
    "production_progress_query": frozenset({"operator", "product_manager"}),
    "production_worklog_query": frozenset({"operator", "product_manager"}),
    "role_manage": frozenset(),
    "session_manage": frozenset({"customer_service", "operator"}),
    "settings_manage": frozenset(),
    "sku_update": frozenset({"operator", "product_manager"}),
    # issue #5247 进场：`product:list` 的持有角色（目录推导）。
    "stock_ledger_query": frozenset({"knowledge_editor", "operator", "product_manager", "sales"}),
}

#: 仍由角色层把关的 B 端工具（目录里没有对应权限码）—— 任何新增都必须显式登记在此。
#: 🔴 **issue #5302 改判**：`notification_manage` **回归本表**（settings 域只读化收口）——
#: 它剩下的两个 action（list / unread_count）对应的端点在 `NotificationController` 里
#: **没有** `@RequirePermission` ⇒ 目录里没有对应码，角色层是**真正需要**的；
#: 类体必须显式声明 `allowed_roles`（判据 `test_role_gated_tools_still_declare_their_role_list`）。
ROLE_GATED_B_SIDE_TOOLS = frozenset({"notification_manage"})

#: **未注册但类仍在**的工具（issue #3917：加工单工具暂不接入，类文件保留并直测）。
#: 类里的 `allowed_roles` 同样是 F4 病灶 —— 恢复注册时不得把假拒绝一起带回来。
UNREGISTERED_CODED_TOOLS = {
    "processing_order_generate": "app.tools.processing_order_generate:ProcessingOrderGenerateTool",
    "processing_order_query": "app.tools.processing_order_query:ProcessingOrderQueryTool",
    "processing_order_update": "app.tools.processing_order_update:ProcessingOrderUpdateTool",
}


# ──────────────────────────────────────────────────────────────────────────────
# 判据本体（纯函数 —— 测试与红证夹具共用）
# ──────────────────────────────────────────────────────────────────────────────

def _load_dotted(target: str) -> BaseTool:
    module_name, _, attr = target.partition(":")
    module = __import__(module_name, fromlist=[attr])
    return getattr(module, attr)()


def all_checked_tools() -> dict[str, BaseTool]:
    """判据覆盖的工具全集：注册表工具 + 未注册但类仍在的加工单工具。"""
    tools = {t.name: t for t in create_default_registry().get_all_tools()}
    for name, target in UNREGISTERED_CODED_TOOLS.items():
        tools.setdefault(name, _load_dotted(target))
    return tools


def registry_tools() -> dict[str, BaseTool]:
    """注册表里的工具（按 name 索引）。"""
    return {t.name: t for t in create_default_registry().get_all_tools()}


def role_allowed(tool: BaseTool, role: str) -> bool:
    """某角色能否通过该工具的两层权限检查（角色只用于提供 permissions 集合）。"""
    ctx = ToolContext(
        tenant_id=1, user_id="u-perm-test", session_id="s-perm-test",
        role=role, permissions=sorted(ROLE_PERMISSIONS[role]),
    )
    return tool.check_permission(ctx)


def expected_roles_for(codes: tuple[str, ...]) -> frozenset[str]:
    """按目录推导「哪些商户角色持有这些码中的**至少一个**」（`admin` 的 `*` 单独恒真）。"""
    return frozenset(
        role for role, perms in ROLE_PERMISSIONS.items()
        if role != "admin" and (perms & set(codes))
    )


def declares_allowed_roles(tool: BaseTool) -> bool:
    """工具是否在**自己的类体**里声明了 `allowed_roles`（不吃 `BaseTool` 默认值）。

    沿 MRO 找第一个声明者：只要在 `BaseTool` 之前有类声明过就算显式
    （与 `tests/test_tool_idempotent_retry_guard.py` 的 `_declares_idempotency_explicitly` 同款）。
    """
    for klass in type(tool).__mro__:
        if klass is BaseTool:
            return False
        if "allowed_roles" in klass.__dict__:
            return True
    return False


def coded_tools_carrying_a_role_list(tools) -> list[str]:
    """**既声明权限码、又声明角色白名单**的工具名（后者已不生效 ⇒ 假门禁，必须为空）。"""
    return sorted(
        t.name for t in tools
        if t.required_permissions and declares_allowed_roles(t)
    )


def code_mismatches(tools) -> list[str]:
    """`required_permissions` 与核定映射不一致的工具名（含缺声明 / 多声明 / 码写错）。"""
    bad: list[str] = []
    for t in tools:
        expected = list(TOOL_PERMISSION_CODES.get(t.name, ()))
        if list(t.required_permissions) != expected:
            bad.append(t.name)
    return sorted(bad)


# ──────────────────────────────────────────────────────────────────────────────
# ① 声明必须等于核定映射
# ──────────────────────────────────────────────────────────────────────────────

class TestDeclaredCodesMatchReviewedMapping:
    """每个工具的 `required_permissions` 必须逐字等于核定映射（防悄悄漂移）。"""

    def test_every_tool_declares_the_reviewed_codes(self):
        bad = code_mismatches(all_checked_tools().values())
        assert bad == [], (
            "以下工具的 required_permissions 与核定映射不一致："
            f"{bad}\n  " + "\n  ".join(
                f"{n}: 实际={list(all_checked_tools()[n].required_permissions)} "
                f"期望={list(TOOL_PERMISSION_CODES.get(n, ()))}"
                for n in bad
            )
        )

    def test_reviewed_mapping_and_expected_roles_agree(self):
        """表自身的自洽性：`EXPECTED_ALLOWED_ROLES` 必须与按目录推导的结果一致。"""
        for name, codes in TOOL_PERMISSION_CODES.items():
            assert EXPECTED_ALLOWED_ROLES[name] == expected_roles_for(codes), (
                f"{name}: 手写放行集与目录推导不一致（表已漂移）"
            )

    def test_every_declared_code_exists_in_the_catalog(self):
        unknown = sorted(
            f"{name}:{code}"
            for name, codes in TOOL_PERMISSION_CODES.items()
            for code in codes
            if code not in PERMISSION_CATALOG
        )
        assert unknown == [], f"以下权限码不在 admin-api 目录里（臆造码）：{unknown}"

    def test_b_side_tools_without_a_catalog_code_are_registered(self):
        """无目录码的 B 端工具必须显式登记（新增即红，防「忘了加码」静默退回角色白名单）。"""
        # `"*"` = 角色层不适用（双端都能用，issue #4147 G1b）⇒ 不是「B 端-only 工具」。
        # 这一类由 tests/test_tool_denial_semantics.py 单独锁（只允许纯本地校验类工具声明，
        # 当前唯一 = validate_input），登记的严格性没有丢。
        unregistered = sorted(
            t.name for t in registry_tools().values()
            if t.name not in TOOL_PERMISSION_CODES
            and "customer" not in t.allowed_roles
            and "*" not in t.allowed_roles
            and t.name not in ROLE_GATED_B_SIDE_TOOLS
        )
        assert unregistered == [], (
            f"以下 B 端工具既没有权限码、也不在登记表里：{unregistered}。"
            "请补 required_permissions；确实没有对应目录码时登记进 ROLE_GATED_B_SIDE_TOOLS 并写明出处"
        )


# ──────────────────────────────────────────────────────────────────────────────
# ② 表驱动：权限码就是门禁（正向 + 负向）
# ──────────────────────────────────────────────────────────────────────────────

class TestPermissionCodeIsTheGate:
    """逐「工具 × 商户角色」断言：结果 == 「该角色持有该工具的码」（`admin` 通配除外）。"""

    def test_exactly_the_roles_holding_the_code_are_allowed(self):
        tools = all_checked_tools()
        failures: list[str] = []
        for name in TOOL_PERMISSION_CODES:
            tool = tools[name]
            if role_allowed(tool, "admin") is not True:
                failures.append(f"{name} × admin: 通配 `*` 必须放行")
            for role in EXPECTED_ALLOWED_ROLES[name]:
                if role_allowed(tool, role) is not True:
                    failures.append(f"{name} × {role}: 持有权限码却被拒（假拒绝）")
            for role in ROLE_PERMISSIONS:
                if role == "admin" or role in EXPECTED_ALLOWED_ROLES[name]:
                    continue
                # C 端**双端工具**（issue #5246）：声明了 `c_end_reachable` 的工具，权限码层对
                # C 端**不可判**（C 端 JWT 没有 permissions claim）⇒ 按 `base.py` 的既定语义落到
                # 角色层，与「该工具还没有权限码时」逐字一致（零回归）。这一支在
                # `test_customer_without_codes_is_denied_on_every_coded_tool` 里单独钉住
                # （两方向都断言：非双端工具必须拒、双端工具必须放行）。
                if role in CUSTOMER_ONLY_ROLES and tool.c_end_reachable:
                    continue
                if role_allowed(tool, role) is not False:
                    failures.append(f"{name} × {role}: 无权限码却被放行（越权）")
        assert failures == [], "权限码门禁与目录不符：\n  " + "\n  ".join(failures)

    def test_operator_is_no_longer_falsely_denied_on_named_tools(self):
        """F4 点名的 7 个 `["admin","tenant_admin"]` 工具：持码的 operator 必须能过。"""
        tools = all_checked_tools()
        for name in (
            "category_manage", "product_update", "sku_update",
            "processing_item_manage", "role_manage", "settings_manage",
        ):
            assert name in EXPECTED_ALLOWED_ROLES, f"{name} 不在核定映射里"
        for name in (
            "category_manage", "product_update", "sku_update",
            "processing_item_manage",
        ):
            assert role_allowed(tools[name], "operator") is True, (
                f"{name}: operator 持有对应权限码，不得再判「权限不足」"
            )
        # role_manage / settings_manage 的码是 system:manage —— 目录里只有 admin 有
        # （`RoleService` 第 301 行「不含 system:manage —— 归 admin 专属（越权守卫）」）
        # ⇒ 它们仍然只放行 admin；**没有放宽**，只是不再靠角色名硬编码。
        for name in ("role_manage", "settings_manage"):
            assert role_allowed(tools[name], "operator") is False, (
                f"{name}: operator 在 admin-api 目录里没有 system:manage，不得放行"
            )

    def test_custom_role_with_the_code_is_allowed(self):
        """F3 的核心：admin-api「角色管理」创建的**任意自定义角色码**只按码授权。"""
        tool = all_checked_tools()["category_manage"]
        ctx = ToolContext(
            tenant_id=1, user_id="u-custom", session_id="s-custom",
            role="poc_operator_custom", permissions=["product:category"],
        )
        assert tool.check_permission(ctx) is True, "持码的自定义角色必须放行（角色名不在任何白名单里）"

    def test_customer_without_codes_is_denied_on_every_coded_tool(self):
        """C 端顾客 JWT 没有权限码 ⇒ 非双端的管理类工具一律拒绝（不因改码而开口子）。

        issue #5246：声明了 `c_end_reachable` 的**双端工具**（被小布 skill 绑定）是**唯一**例外 ——
        权限码层对 C 端不可判，按 `base.py` 的既定语义落到角色层（= 加码前的行为，零回归）。
        例外集合在这里**逐字**钉住（它的取值由 `tests/unit_ci_workflows/test_agent_permission_parity.py`
        从 `app/graph/skills/*.py` 机械推导），两个方向都要成立：非双端工具拒 + 双端工具放行。
        """
        tools = all_checked_tools()
        leaked = sorted(
            name for name in TOOL_PERMISSION_CODES
            if not tools[name].c_end_reachable
            and role_allowed(tools[name], "customer") is not False
        )
        assert leaked == [], f"以下工具对 C 端顾客放行（越权）：{leaked}"

        c_end = sorted(n for n in TOOL_PERMISSION_CODES if tools[n].c_end_reachable)
        assert c_end == [
            "knowledge_search", "order_create", "processing_item_query",
            "product_detail", "product_search", "production_progress_query",
        ], f"双端工具集合变了（须与 skills 推导逐字同步）：{c_end}"
        for name in c_end:
            assert role_allowed(tools[name], "customer") is True, (
                f"{name}: 双端工具对 C 端顾客必须放行（按角色层）"
            )


# ──────────────────────────────────────────────────────────────────────────────
# ③ 反向证据：角色白名单不再是授权来源
# ──────────────────────────────────────────────────────────────────────────────

class TestRoleListIsNotTheGate:
    """`required_permissions` 在场时，`allowed_roles` **不参与**判定（#4149 G9 修正判别性）。

    ⚠️ **判别性从哪来**（旧版在这里是空判据）：已声明权限码的工具按不变式 ④**不得**再声明
    `allowed_roles` ⇒ `category_manage` 的 `allowed_roles` 只是 `BaseTool` 的**默认值**
    （`["customer","admin","agent","tenant_admin"]`），对任何未覆写的工具都成立 ⇒
    拿 `"tenant_admin" in tool.allowed_roles` 当前提**没有任何判别力**（实测：`declares_allowed_roles`
    为 False）。真正的判别性只能来自**同时声明两者**的替身 `_FakeCodedWithRoleList`：
    结果必须跟着**权限码**走，两个方向各钉一条 ——
      ① 列进角色白名单、目录里却没有该码的角色（`tenant_admin`）⇒ **拒绝**；
      ② **没**列进角色白名单、却持有该码的角色（`operator`）⇒ **放行**。
    两条必须同时成立：任何「按角色白名单判」的实现都会在其中一条上翻转
    （红证：`TestGuardsAreNotVacuous::test_role_list_as_gate_implementation_is_caught`）。
    """

    def test_ghost_role_in_the_role_list_is_denied_because_it_has_no_code(self):
        tool = _FakeCodedWithRoleList()
        assert declares_allowed_roles(tool) is True, "前提自断言：替身必须真的声明了角色白名单"
        assert "tenant_admin" in tool.allowed_roles, "前提：tenant_admin 在替身的角色白名单里"
        assert ROLE_PERMISSIONS["tenant_admin"] == frozenset(), (
            "前提：admin-api 目录里 tenant_admin 没有任何码（否则本负例失去判别力）"
        )
        assert role_allowed(tool, "tenant_admin") is False, (
            "tenant_admin 在 admin-api 权限目录里没有任何码 ⇒ 工具层必须拒绝"
            "（它在 admin-api 侧所有 @RequirePermission 接口都是 403，放行才是口径断裂）"
        )

    def test_role_holding_the_code_is_allowed_even_without_the_role_list(self):
        """反方向：**不在**角色白名单里但持有权限码 ⇒ 必须放行（码是门禁，白名单不是）。"""
        tool = _FakeCodedWithRoleList()
        assert "operator" not in tool.allowed_roles, (
            "前提：operator 不在替身的角色白名单里（否则本判据无判别力）"
        )
        assert "product:category" in ROLE_PERMISSIONS["operator"], "前提：operator 持有该码"
        assert role_allowed(tool, "operator") is True, (
            "持码但不在角色白名单 ⇒ 必须放行；否则又回到按角色名硬编码的假拒绝（F4 病根）"
        )


# ──────────────────────────────────────────────────────────────────────────────
# ④ 静态锁：声明了码的工具不得再声明角色白名单（防假门禁回归）
# ──────────────────────────────────────────────────────────────────────────────

class TestCodedToolsCarryNoRoleList:
    """`required_permissions` 与 `allowed_roles` 并存 = 第二份不生效的假门禁。"""

    def test_no_coded_tool_declares_allowed_roles(self):
        offenders = coded_tools_carrying_a_role_list(all_checked_tools().values())
        assert offenders == [], (
            f"以下工具同时声明了 required_permissions 与 allowed_roles：{offenders}。"
            "权限码为权威层时角色白名单**不生效** —— 留着只会让下一个人以为它在把关（#4106 F3/F4 的病根）"
        )

    def test_role_gated_tools_still_declare_their_role_list(self):
        """反面：真正靠角色层把关的工具（无目录码）必须保留白名单，别被顺手删掉。"""
        tools = all_checked_tools()
        for name in ROLE_GATED_B_SIDE_TOOLS:
            assert declares_allowed_roles(tools[name]) is True, (
                f"{name} 没有目录权限码，只能靠角色层把关 —— allowed_roles 不得删除"
            )


# ──────────────────────────────────────────────────────────────────────────────
# ⑤ 判据自身可红 + 不恒真（防「恒绿假锁」）
# ──────────────────────────────────────────────────────────────────────────────

class _FakeWrongCodeTool(BaseTool):
    """夹具：声明的码与核定映射不符（判据必须报出）。"""

    name = "fake_wrong_code"
    description = "红证夹具"
    required_permissions = ["product:list"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:  # pragma: no cover
        return ToolResult(success=True)


class _FakeCodedWithRoleList(BaseTool):
    """夹具：既声明码、又声明角色白名单（静态锁必须报出）。"""

    name = "fake_coded_with_role_list"
    description = "红证夹具"
    required_permissions = ["product:category"]
    allowed_roles = ["admin", "tenant_admin"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:  # pragma: no cover
        return ToolResult(success=True)


class _FakeRoleGatedOnly(BaseTool):
    """阴性夹具：只有角色白名单、没有码（合法形态，静态锁不得误伤）。"""

    name = "fake_role_gated_only"
    description = "阴性夹具"
    allowed_roles = ["admin", "operator"]

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:  # pragma: no cover
        return ToolResult(success=True)


class _RoleListAsGateFixture(_FakeCodedWithRoleList):
    """**红证替身**：把角色白名单当门禁（= #4106 F3/F4 的病灶实现）。

    用途单一：证明 `TestRoleListIsNotTheGate` 的两条判据**确实有判别力**
    （病灶实现下一条翻转成放行、另一条翻转成假拒绝），而不是恒绿的空判据（#4149 G9）。
    """

    name = "fake_role_list_as_gate"

    def check_permission(self, context: ToolContext) -> bool:  # pragma: no cover - 替身
        return context.role in self.allowed_roles


class TestGuardsAreNotVacuous:
    """**:red_circle: 红证** + **阴性负例**：判据必须能报出，也必须能不报。"""

    def test_mapping_lock_reports_a_wrong_code(self):
        assert code_mismatches([_FakeWrongCodeTool()]) == ["fake_wrong_code"], (
            "映射判据是空的：码写错的工具没被报出"
        )

    def test_role_list_as_gate_implementation_is_caught(self):
        """**:red_circle: 红证（#4149 G9）** —— 换上「按角色白名单判」的实现，判据必须翻转。

        翻转即判别力：`tenant_admin`（列进白名单、无码）被放行 + `operator`（持码、不在白名单）
        被假拒绝 —— 与真实现逐条对照**两个方向都不同**，证明那两条断言不是恒绿的。
        """
        planted = _RoleListAsGateFixture()
        real = _FakeCodedWithRoleList()
        assert role_allowed(planted, "tenant_admin") is True, "病灶实现下 tenant_admin 会被放行"
        assert role_allowed(planted, "operator") is False, "病灶实现下持码 operator 会被假拒绝"
        assert [role_allowed(planted, r) for r in ("tenant_admin", "operator")] != [
            role_allowed(real, r) for r in ("tenant_admin", "operator")
        ], "病灶实现与真实现的判定完全相同 ⇒ 那两条判据没有判别力（空判据）"

    def test_role_list_lock_reports_a_coded_tool_with_a_role_list(self):
        assert coded_tools_carrying_a_role_list([_FakeCodedWithRoleList()]) == [
            "fake_coded_with_role_list"
        ], "静态锁是空的：同时声明码与角色白名单的工具没被报出"

    def test_role_list_lock_does_not_flag_a_role_gated_tool(self):
        """阴性负例：无码工具的角色白名单是合法形态，不得误伤。"""
        assert coded_tools_carrying_a_role_list([_FakeRoleGatedOnly()]) == []

    def test_registry_actually_carries_the_coded_tools(self):
        """守卫不得空转：注册表必须真的取出足量带码工具（fail-closed）。"""
        tools = all_checked_tools()
        coded = [n for n in TOOL_PERMISSION_CODES if n in tools]
        assert len(coded) == len(TOOL_PERMISSION_CODES), (
            f"映射表里有 {len(TOOL_PERMISSION_CODES)} 个工具，只解析出 {len(coded)} 个 —— 表与真值脱节"
        )
        assert len(coded) >= 15, (
            f"注册表只解析出 {len(coded)} 个带码工具（期望 ≥15）—— 判据会空转通过，请核对工具是否被改名/移除"
        )
        assert "category_manage" in tools, "`category_manage` 不见了（fail-closed）"

# ──────────────────────────────────────────────────────────────────────────────
# ⑥ 单一真相源：镜像表必须对 **admin-api 源码**交叉核对（#4149 G8）
# ──────────────────────────────────────────────────────────────────────────────
#
# `PERMISSION_CATALOG` / `ROLE_PERMISSIONS` 是 admin-api 源码的**手抄件**：没有源级核对时，
# admin-api 改了某岗默认权限，本文件全绿而镜像腐烂 —— 而工具层正是按镜像推导放行集
# ⇒ 腐烂即「持码被假拒绝 / 无码被放行」，且没有任何东西会红。
# 先例（同款做法）：`test_permission_scope_injection.py` 的 `PERMISSION_LABELS` 源级核对。

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRATION_SERVICE = (
    _REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java"
)
_ROLE_SERVICE = (
    _REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java"
)

#: Java 权限目录行：`{"仪表板查看", "dashboard:view", "dashboard", "view", "查看数据概览"},`
_JAVA_CATALOG_ROW_RE = re.compile(r'\{"[^"]+",\s*"([a-z][a-z_]*(?::[a-z_]+)+)"')
# ⚠️ 段数：权限码允许 **≥2 段**（`agent:session:manage` 是 issue #5246 引入的第一个三段码）；
# 旧正则 `[a-z_]+:[a-z_]+` 只认两段 ⇒ 三段码被静默漏掉（「镜像多码」假红，实测踩过）。
#: `Role <var> = Role.builder() … .code("<role_code>") … .build();`
_JAVA_ROLE_BUILDER_RE = re.compile(r'Role\s+(\w+)\s*=\s*Role\.builder\(\)(.*?)\.build\(\);', re.S)
_JAVA_ROLE_CODE_RE = re.compile(r'\.code\("([a-z_]+)"\)')
#: `attachDefaultPermissions(tenantId, <var>, List.of(…)|<x>.keySet(), permissionByCode);`
_JAVA_ATTACH_RE = re.compile(
    r"attachDefaultPermissions\(\s*tenantId\s*,\s*(\w+)\s*,\s*"
    r"(List\.of\((?P<list>[^)]*)\)|(?P<all>[\w.]+\.keySet\(\)))\s*,",
    re.S,
)
#: `case "<role>" -> List.of(…);`（RoleService 的硬编码回退）
_JAVA_FALLBACK_RE = re.compile(r'case\s+"(\w+)"\s*->\s*List\.of\(([^)]*)\)', re.S)
_JAVA_STRING_RE = re.compile(r'"([^"]+)"')

#: 镜像里**刻意**登记为空集的角色（C 端角色 / admin-api 里不存在的幽灵角色）
KNOWN_CODELESS_ROLES = ["agent", "customer", "tenant_admin"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def java_catalog_codes(text: str) -> frozenset:
    """`RegistrationService` 的权限目录（`String[][] defaultPermissions = {…}`）里的码。"""
    return frozenset(_JAVA_CATALOG_ROW_RE.findall(text))


def java_seeded_role_permissions(text: str) -> dict:
    """`attachDefaultPermissions(...)` 逐岗预置的默认码（**DB seed 口径**，新租户真值）。"""
    var_to_code = {
        m.group(1): code.group(1)
        for m in _JAVA_ROLE_BUILDER_RE.finditer(text)
        if (code := _JAVA_ROLE_CODE_RE.search(m.group(2)))
    }
    catalog = java_catalog_codes(text)
    seeded: dict = {}
    for m in _JAVA_ATTACH_RE.finditer(text):
        role = var_to_code.get(m.group(1))
        if role is None:
            continue
        seeded[role] = catalog if m.group("all") else frozenset(
            _JAVA_STRING_RE.findall(m.group("list") or "")
        )
    return seeded


def java_fallback_role_permissions(text: str) -> dict:
    """`RoleService.getPermissionCodesForRole` 的硬编码回退（无 `role_permissions` 记录时）。"""
    return {
        m.group(1): frozenset(_JAVA_STRING_RE.findall(m.group(2)))
        for m in _JAVA_FALLBACK_RE.finditer(text)
    }


def catalog_gaps(java_codes, mirror) -> list:
    """目录 ↔ 镜像的差集（改名会同时表现为「镜像缺码」+「镜像多码」）。抽成纯函数以便喂夹具。"""
    return sorted(
        [f"镜像缺码:{c}" for c in java_codes if c not in mirror]
        + [f"镜像多码:{c}" for c in mirror if c not in java_codes]
    )


def seeded_role_gaps(seeded: dict, mirror: dict) -> list:
    """逐岗默认码 ↔ 镜像的差集（缺/多逐条列出）。`admin` 的通配语义由调用方单独核对。"""
    gaps: list = []
    for role, codes in seeded.items():
        if role == "admin":
            continue
        have = mirror.get(role, frozenset())
        gaps += [f"{role}:镜像缺码:{c}" for c in sorted(codes - have)]
        gaps += [f"{role}:镜像多码:{c}" for c in sorted(have - codes)]
    return sorted(gaps)


def fallback_role_gaps(fallback: dict, mirror: dict) -> list:
    """回退路径 ↔ 镜像：**回退里有、镜像里没有** = 工具层会对合法调用报「权限不足」（假拒绝）。"""
    return sorted(
        f"{role}:镜像缺码:{c}"
        for role, codes in fallback.items() if role != "admin"
        for c in sorted(codes - mirror.get(role, frozenset()))
    )


class TestRoleMirrorMatchesTheAdminApiSource:
    """镜像表逐条对 admin-api 源码交叉核对（缺 / 多 / 改名都必须报出）。"""

    def test_both_java_sources_are_parsed(self):
        """fail-closed：抽不到内容 ⇒ 判据空跑，宁可红。"""
        for path in (_REGISTRATION_SERVICE, _ROLE_SERVICE):
            assert path.exists(), f"{path} 不见了 —— 真相源消失（fail-closed）"
        registration, role_service = _read(_REGISTRATION_SERVICE), _read(_ROLE_SERVICE)
        assert java_catalog_codes(registration), "`defaultPermissions` 一行都没抽到（正则或被扫目标变了）"
        assert java_seeded_role_permissions(registration), "抽不到逐岗默认权限（fail-closed）"
        assert java_fallback_role_permissions(role_service), "抽不到硬编码回退（fail-closed）"

    def test_the_catalog_is_exactly_the_java_directory(self):
        """18 码目录逐字一致：改名 ⇒ 「缺 + 多」同时出现。"""
        gaps = catalog_gaps(java_catalog_codes(_read(_REGISTRATION_SERVICE)), PERMISSION_CATALOG)
        assert gaps == [], (
            f"`PERMISSION_CATALOG` 与 `RegistrationService.defaultPermissions` 不符：{gaps}"
            "（镜像腐烂 ⇒ 工具层按错码授权）"
        )

    def test_seeded_role_defaults_match_the_mirror(self):
        """五岗 seed 与镜像逐岗相等；`admin` 的 seed = 全量目录、镜像 = `*`（运行时通配）。"""
        seeded = java_seeded_role_permissions(_read(_REGISTRATION_SERVICE))
        assert set(seeded) == {"admin", "customer_service", "operator", "sales", "finance"}, (
            f"admin-api 默认岗位集合变了：{sorted(seeded)} —— 镜像必须同步评审"
        )
        assert seeded["admin"] == java_catalog_codes(_read(_REGISTRATION_SERVICE)), (
            "admin 岗位的 seed 必须预置全量目录（运行时 `getUserPermissions` 再折叠成 `*`）"
        )
        assert ROLE_PERMISSIONS["admin"] == frozenset({"*"}), (
            "镜像里 admin 必须是运行时口径 `*`（`RoleService.getUserPermissions` 特判）"
        )
        gaps = seeded_role_gaps(seeded, ROLE_PERMISSIONS)
        assert gaps == [], f"逐岗默认权限与镜像不符：{gaps}"

    def test_the_hardcoded_fallback_is_covered_by_the_mirror(self):
        """回退路径只能授予镜像认为该角色拥有的码（否则工具层假拒绝合法调用）。"""
        fallback = java_fallback_role_permissions(_read(_ROLE_SERVICE))
        gaps = fallback_role_gaps(fallback, ROLE_PERMISSIONS)
        assert gaps == [], (
            f"`RoleService.getPermissionCodesForRole` 的码不在镜像里：{gaps}"
            "—— 这些角色在工具层会被判「权限不足」（F4 假拒绝形态）"
        )

    def test_no_mirrored_role_is_unknown_to_the_admin_api_source(self):
        """反方向：镜像里持有码的角色必须来自两处源码之一；空集角色必须显式登记。"""
        registration, role_service = _read(_REGISTRATION_SERVICE), _read(_ROLE_SERVICE)
        known = set(java_seeded_role_permissions(registration)) | set(
            java_fallback_role_permissions(role_service))
        extra = sorted(r for r, codes in ROLE_PERMISSIONS.items() if codes and r not in known)
        assert extra == [], (
            f"镜像里这些角色持有权限码，但 admin-api 源码里根本没有它们：{extra}"
            "（臆造角色 / 源码已删而镜像残留）"
        )
        codeless = sorted(r for r, codes in ROLE_PERMISSIONS.items() if not codes)
        assert codeless == KNOWN_CODELESS_ROLES, (
            f"无码角色集合变了：{codeless} —— C 端角色与幽灵角色必须逐个显式登记后才可加入"
        )

    def test_every_mirrored_role_code_exists_in_the_catalogue(self):
        """镜像里不允许出现目录外的码（`*` 是运行时通配，不在目录里）。"""
        unknown = sorted(
            f"{role}:{code}" for role, codes in ROLE_PERMISSIONS.items()
            for code in codes if code != "*" and code not in PERMISSION_CATALOG
        )
        assert unknown == [], f"镜像里出现了目录外的码：{unknown}"


class TestRoleMirrorGuardIsNotVacuous:
    """**:red_circle: 红证**（处方码夹具）+ **阴性负例**：源级核对必须能报出，也必须能不报。"""

    #: 处方夹具：admin-api 把 operator 的默认码改了（含一个目录外的自造码），镜像没跟上
    _PLANTED_TEXTS = {
        "renamed_role_default": (
            "String[][] defaultPermissions = {\n"
            '        {"商品列表", "product:list", "product", "list", "x"}\n'
            "};\n"
            "Role operatorRole = Role.builder()\n"
            '        .code("operator")\n'
            "        .build();\n"
            "attachDefaultPermissions(tenantId, operatorRole, "
            'List.of("product:list", "wallet:payout"), permissionByCode);\n'
        ),
        "invented_catalog_code": (
            "String[][] defaultPermissions = {\n"
            '        {"钱包提现", "wallet:payout", "wallet", "payout", "x"}\n'
            "};\n"
        ),
        "fallback_grants_a_code_the_mirror_lacks": (
            "private List<String> getPermissionCodesForRole(String roleCode) {\n"
            "    return switch (roleCode) {\n"
            '        case "operator" -> List.of("wallet:payout");\n'
            "        default -> List.of();\n"
            "    };\n"
            "}\n"
        ),
    }

    def test_planted_java_true_source_is_parsed(self):
        """夹具自证：处方源码必须先被解析出来（否则下面的红证是空跑）。"""
        seeded = java_seeded_role_permissions(self._PLANTED_TEXTS["renamed_role_default"])
        assert seeded == {"operator": frozenset({"product:list", "wallet:payout"})}, (
            f"处方夹具没被解析出来：{seeded}"
        )
        assert java_catalog_codes(self._PLANTED_TEXTS["invented_catalog_code"]) == {"wallet:payout"}
        assert java_fallback_role_permissions(
            self._PLANTED_TEXTS["fallback_grants_a_code_the_mirror_lacks"]
        ) == {"operator": frozenset({"wallet:payout"})}

    def test_guard_reports_a_renamed_role_default(self):
        """**:red_circle:** admin-api 改了某岗默认码而镜像没跟上 ⇒ 必须报出缺 + 多。"""
        gaps = seeded_role_gaps(
            java_seeded_role_permissions(self._PLANTED_TEXTS["renamed_role_default"]),
            ROLE_PERMISSIONS,
        )
        assert "operator:镜像缺码:wallet:payout" in gaps, f"新码没被报出：{gaps}"
        assert any(g.startswith("operator:镜像多码:") for g in gaps), (
            f"被撤掉的码没被报出（只报新增 = 半个判据）：{gaps}"
        )

    def test_guard_reports_a_catalog_code_the_mirror_lacks(self):
        """**:red_circle:** 目录里新增/改名一个码 ⇒ 必须报出「镜像缺码 + 镜像多码」。"""
        gaps = catalog_gaps({"dashboard:view", "wallet:payout"}, PERMISSION_CATALOG)
        assert "镜像缺码:wallet:payout" in gaps
        assert any(g.startswith("镜像多码:") for g in gaps), (
            "只报新增不报多余 ⇒ 改名会被当成两条无关变更（半个判据）"
        )

    def test_guard_reports_a_fallback_grant_the_mirror_lacks(self):
        """**:red_circle:** 回退路径授予了镜像没有的码 ⇒ 必须报出（否则工具层假拒绝）。"""
        gaps = fallback_role_gaps(
            java_fallback_role_permissions(
                self._PLANTED_TEXTS["fallback_grants_a_code_the_mirror_lacks"]),
            ROLE_PERMISSIONS,
        )
        assert gaps == ["operator:镜像缺码:wallet:payout"], f"假拒绝形态未被报出：{gaps}"

    def test_guard_reports_a_rotted_mirror_against_the_real_source(self):
        """**:red_circle: 反向红证**：真源码不动、**镜像**被手改坏 ⇒ 同一条判据必须报出。

        与处方 Java 夹具互补：那个证明「admin-api 改了能抓到」，这个证明「镜像被改坏了也能抓到」。
        """
        rotted = dict(
            ROLE_PERMISSIONS,
            operator=ROLE_PERMISSIONS["operator"] - {"processing:update"},
            sales=ROLE_PERMISSIONS["sales"] | {"system:manage"},
        )
        gaps = seeded_role_gaps(
            java_seeded_role_permissions(_read(_REGISTRATION_SERVICE)), rotted)
        assert "operator:镜像缺码:processing:update" in gaps, f"镜像被删码没报出：{gaps}"
        assert "sales:镜像多码:system:manage" in gaps, f"镜像被加码没报出：{gaps}"

    def test_guard_does_not_flag_the_real_sources(self):
        """**阴性负例**：当下真源码必须不报（防恒红 —— 镜像一旦腐烂才该红）。"""
        registration, role_service = _read(_REGISTRATION_SERVICE), _read(_ROLE_SERVICE)
        assert seeded_role_gaps(
            java_seeded_role_permissions(registration), ROLE_PERMISSIONS) == []
        assert fallback_role_gaps(
            java_fallback_role_permissions(role_service), ROLE_PERMISSIONS) == []

    def test_operator_seed_is_a_superset_of_the_hardcoded_fallback(self):
        """登记的现实差异：seed（14 码）⊃ 回退（12 码，缺加工单查看/操作）。

        镜像取 **seed 口径**（新租户真值，`V29`/`V32`/`V43` 对存量租户补齐）⇒
        回退是它的子集；本断言把这条关系钉住，防「回退悄悄比 seed 更宽」被当成等价。
        """
        seeded = java_seeded_role_permissions(_read(_REGISTRATION_SERVICE))["operator"]
        fallback = java_fallback_role_permissions(_read(_ROLE_SERVICE))["operator"]
        assert fallback < seeded, (
            f"回退不再是 seed 的真子集（seed={sorted(seeded)} / fallback={sorted(fallback)}）"
            "—— 这两个口径的差异必须重新评审后再改镜像"
        )
