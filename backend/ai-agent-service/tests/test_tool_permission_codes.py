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
`processing_item_manage` / `product_processing_item_manage` / `role_manage` /
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
3. `TestRoleListIsNotTheGate` —— 反向证据：只写在 `allowed_roles` 里、目录中**没有**该码的
   角色（`tenant_admin` 幽灵角色）必须被拒 —— 证明角色白名单不再是授权来源；
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
  `order_query` / `product_detail` / `inventory_manage` / `order_create` / `curtain_calc`
  / `interact` / `validate_input` / `knowledge_search` 等）：C 端 JWT 没有权限码
  （`UserIdentity.permissions` 默认空、`customer`/`agent` 不是 `roles` 表角色）
  ⇒ 加码会让 C 端全量失效。**保持角色层**，本次不动。
- `notification_manage`：`NotificationController` 全类**无** `@RequirePermission`
  ⇒ 目录里没有对应码，角色层是**真正需要**的（工具层唯一保留角色白名单的 B 端工具）。
- `tenant_admin`：admin-api 里**不存在**该角色（无 seed、无权限映射，
  `UserService.java` 第 49 行注释「历史遗留管理角色」）。它在 ai-agent 的 27 个工具里
  被放行、在 admin-api 侧所有 `@RequirePermission` 接口 403 ⇒ 修掉这个**跨服务口径断裂**
  属于本单预期结果（不是回归）。
"""

from __future__ import annotations

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.registry import create_default_registry

# ──────────────────────────────────────────────────────────────────────────────
# 真值表（判据的唯一来源 —— 测试与红证夹具共用这一处，不写第二份）
# ──────────────────────────────────────────────────────────────────────────────

#: admin-api 权限目录（18 码，`RegistrationService` 第 548-567 行逐条对齐）
PERMISSION_CATALOG = frozenset({
    "dashboard:view",
    "product:manage",
    "product:list",
    "product:create",
    "product:category",
    "processing:manage",
    "processing:view",
    "processing:update",
    "knowledge:manage",
    "order:list",
    "order:detail",
    "order:refund",
    "customer:view",
    "finance:view",
    "agent:session",
    "employee:list",
    "employee:create",
    "system:manage",
})

#: 商户角色的默认权限码（DB seed 口径；`admin` 运行时恒为 `*`）
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "operator": frozenset({
        "agent:session", "customer:view", "dashboard:view", "employee:list",
        "finance:view", "order:detail", "order:list", "order:refund",
        "processing:manage", "processing:update", "processing:view",
        "product:category", "product:create", "product:list",
    }),
    "customer_service": frozenset({
        "agent:session", "customer:view", "dashboard:view",
        "order:detail", "order:list", "processing:view",
    }),
    "sales": frozenset({
        "customer:view", "dashboard:view", "order:detail", "order:list",
        "processing:view", "product:list",
    }),
    "finance": frozenset({
        "dashboard:view", "finance:view", "order:detail", "order:list",
        "processing:view",
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
    "after_sales_manage": ("order:refund",),
    "category_manage": ("product:category",),
    "customer_manage": ("customer:view",),
    "dashboard_stats": ("dashboard:view",),
    "employee_manage": ("employee:list", "employee:create"),
    "finance_api": ("finance:view",),
    "order_manage": ("order:list",),
    "piecework_query": ("order:list",),
    "processing_item_manage": ("processing:manage",),
    "processing_order_generate": ("processing:update",),
    "processing_order_query": ("processing:view",),
    "processing_order_update": ("processing:update",),
    "product_manage": ("product:create",),
    "product_processing_item_manage": ("processing:manage",),
    "product_update": ("product:create",),
    "role_manage": ("system:manage",),
    "session_manage": ("agent:session",),
    "settings_manage": ("system:manage",),
    "sku_update": ("product:create",),
}

#: 每个工具**必须**放行的商户角色（除恒放行的 admin 外）—— 显式写死，
#: 映射一变本表就得跟着改，diff 里看得见「谁新拿到/谁被收回」。
EXPECTED_ALLOWED_ROLES: dict[str, frozenset[str]] = {
    "after_sales_manage": frozenset({"operator"}),
    "category_manage": frozenset({"operator", "product_manager"}),
    "customer_manage": frozenset({"operator", "customer_service", "sales"}),
    "dashboard_stats": frozenset({
        "operator", "customer_service", "sales", "finance",
        "product_manager", "knowledge_editor",
    }),
    "employee_manage": frozenset({"operator"}),
    "finance_api": frozenset({"operator", "finance"}),
    "order_manage": frozenset({"operator", "customer_service", "sales", "finance"}),
    "piecework_query": frozenset({"operator", "customer_service", "sales", "finance"}),
    "processing_item_manage": frozenset({"operator", "product_manager"}),
    "processing_order_generate": frozenset({"operator"}),
    "processing_order_query": frozenset({"operator", "customer_service", "sales", "finance"}),
    "processing_order_update": frozenset({"operator"}),
    "product_manage": frozenset({"operator", "product_manager"}),
    "product_processing_item_manage": frozenset({"operator", "product_manager"}),
    "product_update": frozenset({"operator", "product_manager"}),
    "role_manage": frozenset(),
    "session_manage": frozenset({"operator", "customer_service"}),
    "settings_manage": frozenset(),
    "sku_update": frozenset({"operator", "product_manager"}),
}

#: 仍由角色层把关的 B 端工具（目录里没有对应权限码）—— 任何新增都必须显式登记在此
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
        unregistered = sorted(
            t.name for t in registry_tools().values()
            if t.name not in TOOL_PERMISSION_CODES
            and "customer" not in t.allowed_roles
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
                if role_allowed(tool, role) is not False:
                    failures.append(f"{name} × {role}: 无权限码却被放行（越权）")
        assert failures == [], "权限码门禁与目录不符：\n  " + "\n  ".join(failures)

    def test_operator_is_no_longer_falsely_denied_on_named_tools(self):
        """F4 点名的 7 个 `["admin","tenant_admin"]` 工具：持码的 operator 必须能过。"""
        tools = all_checked_tools()
        for name in (
            "category_manage", "product_update", "sku_update",
            "processing_item_manage", "product_processing_item_manage",
            "role_manage", "settings_manage",
        ):
            assert name in EXPECTED_ALLOWED_ROLES, f"{name} 不在核定映射里"
        for name in (
            "category_manage", "product_update", "sku_update",
            "processing_item_manage", "product_processing_item_manage",
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
        """C 端顾客 JWT 没有权限码 ⇒ 管理类工具一律拒绝（不因改码而开口子）。"""
        tools = all_checked_tools()
        leaked = sorted(
            name for name in TOOL_PERMISSION_CODES
            if role_allowed(tools[name], "customer") is not False
        )
        assert leaked == [], f"以下工具对 C 端顾客放行（越权）：{leaked}"


# ──────────────────────────────────────────────────────────────────────────────
# ③ 反向证据：角色白名单不再是授权来源
# ──────────────────────────────────────────────────────────────────────────────

class TestRoleListIsNotTheGate:
    """只写在 `allowed_roles`、目录里没有码的角色必须被拒 —— 角色白名单已非门禁。"""

    def test_ghost_role_listed_in_allowed_roles_is_still_denied(self):
        tools = all_checked_tools()
        tool = tools["category_manage"]
        # 前提自断言：这条负例只在「tenant_admin 确实被列进了角色白名单」时有判别力
        assert "tenant_admin" in tool.allowed_roles, (
            "前提不成立：category_manage 的 allowed_roles 已不含 tenant_admin —— 本负例失去判别力"
        )
        assert role_allowed(tool, "tenant_admin") is False, (
            "tenant_admin 在 admin-api 权限目录里没有任何码 ⇒ 工具层必须拒绝"
            "（它在 admin-api 侧所有 @RequirePermission 接口都是 403，放行才是口径断裂）"
        )

    def test_role_without_the_code_but_with_merchant_role_code_is_denied(self):
        """`finance` 是**真实商户角色**，但没有 product:category ⇒ 必须拒绝（负向样本）。"""
        tool = all_checked_tools()["category_manage"]
        assert "finance" not in tool.allowed_roles, "前提：finance 不在该工具的角色白名单里"
        assert role_allowed(tool, "finance") is False


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


class TestGuardsAreNotVacuous:
    """**:red_circle: 红证** + **阴性负例**：判据必须能报出，也必须能不报。"""

    def test_mapping_lock_reports_a_wrong_code(self):
        assert code_mismatches([_FakeWrongCodeTool()]) == ["fake_wrong_code"], (
            "映射判据是空的：码写错的工具没被报出"
        )

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