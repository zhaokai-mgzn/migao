# case_ids: MC-012
"""**Agent 功能权限 ≡ 页面权限** 的机械对账（issue #5246）。

## 用户裁定（本守卫的唯一理由，2026-09-23）

> 「admin-api 与 tools 按项目最新要求重新设计……**Agent 的功能权限必须与页面权限保持一致，
> 不得造成权限泄露**」

## 为什么必须有机械判据（病根）

权限面有**四个各自维护的集合**，任何一处改动都**不会有东西变红**：

| 集合 | 载体 | 漂移形态（实测） |
|---|---|---|
| **S1 工具** | `backend/ai-agent-service/app/tools/*.py` 的 `required_permissions` / `read_only` / `allowed_roles` | 44 个工具里只有 21 个声明权限码，其余靠**手写角色白名单**（#4106 F3/F4 说的漂移病根）；`inventory_manage.allowed_roles` 里还留着 C 端角色 `customer` |
| **S2 端点** | `backend/admin-api/src/main/java/com/migao/admin/controller/**` 的 `@RequirePermission`（**方法级优先于类级**，同 `PermissionInterceptor.resolveRequirePermission`） | 类级读码盖住写端点（`AgentProductController` 的 `product:list` 盖住 4 个 PATCH/POST）；11 个 controller 完全没有注解 |
| **S3 菜单** | 四处菜单源（`frontend/admin-web/src/config/menu.ts`、`MenuController.MENU_TREE`、`AuthService.buildMenusByPermissions`、`UserController.generateMenus`） | 同一节点四处各写各的码（`售后工单` = `order:refund`，而客服岗位没有该码）；第四处是**5 节点遗留树**（`product:manage` 粗码），没有任何守卫覆盖 |
| **S4 岗位** | 内置岗位默认权限（`RegistrationService.initializeDefaultRolesAndPermissions` 的 `attachDefaultPermissions` + `RoleService.getPermissionCodesForRole` 硬编码回退） | 岗位持 `processing:view` 却**没有**对应菜单节点 ⇒ 经 Agent 能查到页面里看不到的生产数据 |

## 三条授权面（对账必须同时覆盖）

1. **工具层** `BaseTool.check_permission`（Python，友好错误 + 纵深防御）；
2. **端点层** `@RequirePermission` + `PermissionInterceptor`（**权威闸**：`ServiceTokenFilter` 在
   `X-User-Id` 命中本租户商户员工时挂**真实角色**，故工具调用同样受端点细粒度校验）；
3. **菜单层** 前端侧边栏 `/api/auth/me` 的 `permissions`/`menus` 过滤。

## 判据（每条都有**注入式红证**，见文件末尾 `test_every_judgement_can_go_red`）

1. **B 端可达的工具一律声明权限码** —— 白名单**不是手写清单**：唯一豁免口径 = 「该工具在本仓
   **没有任何 admin-api HTTP 调用点**」（纯本地），且逐条登记在 `LOCAL_ONLY_TOOLS` 并**双向相等**
   （陈旧条目也红）。
2. **工具码 ≡ 它调用的每个已注解端点的生效码**（集合相等；未注解端点必须登记在
   `UNANNOTATED_ENDPOINTS` 里 —— 沉默放行正是本单要治的失效模式）。
3. **工具码 ≡ 其对应菜单节点的码**（读工具必须持节点码；写工具允许持该页的写码，登记在
   `PAGE_WRITE_CODES`），且**四处菜单源在交集上同构**（同一节点名不得两处不同码）。
4. **零权限泄露**：对每个内置岗位 R 与每个已编码工具 T —— `R 可调 T ⇒ R 看得见 T 的菜单节点`
   （用户逐字要求）。
5. **读写码不错配**：`read_only=True` 的工具不得只要求写码；写工具不得只要求读码
   （冲突项走**具名例外** `READ_WRITE_EXCEPTIONS`，每条带理由 + 建议修法，不允许沉默跳过）。
6. **角色白名单卫生**：声明了权限码的工具不得再声明 `allowed_roles`（第二份不生效的假门禁）；
   `allowed_roles` 里不得出现 C 端角色（`customer`/`agent`）与幽灵角色（`tenant_admin`/`worker`，
   admin-api 里没有角色行/权限映射）—— 除非该工具**确实**是 C 端可达的（`c_end_reachable`）。
7. **`c_end_reachable` 不得手写**：必须逐字等于「该工具是否被**小布（C 端）**的 skill 绑定」
   （从 `app/agents/agents/xiaobu.py` 的 `skill_names` + `app/graph/skills/*.py` 的 `*_TOOLS` 推导）。
8. **未注解端点 = 显式登记的决定**（不是沉默）：每个生效码为 `None` 的端点必须命中
   `UNANNOTATED_ENDPOINTS` 的某条已登记口径；登记项不得陈旧。同理 `REGISTERED_RESIDUALS`
   逐条登记**已知但本单不修**的残留（带理由 + 去向）。
9. **解析器自检（防恒绿空跑）**：注解条数守恒 / 两处权限目录逐值相等 / 岗位硬编码回退 ⊆ 种子矩阵 /
   菜单码 ∈ 权限目录 / 各集合非空。

## 明确的边界（**不要**把本守卫读成覆盖面更大）

- **C 端不在本守卫射程内**：C 端 JWT 没有权限码（`UserIdentity.permissions` 默认空），且
  `ServiceTokenFilter` 对 `X-User-Id ∈ {customer, agent}`（或无 `X-User-Id`）回退成 `service` 权威，
  `PermissionInterceptor.hasBypassRole` 直通 ⇒ **admin-api 侧对 C 端没有权限码校验**，
  C 端的隔离靠业务层的 `X-User-Id` 过滤（`/api/customer/**` 与 `/api/admin/agent/**` 各自过滤）。
  见 `backend/admin-api/src/main/java/com/migao/admin/security/ServiceTokenFilter.java` 与
  `.../security/PermissionInterceptor.java`。本守卫只判「商户员工」这条线。
- **四处菜单源不做全树同构**（那是 #5236 的产品裁定）：本守卫只比**交集**（同名节点不得两处不同码），
  并把未覆盖部分登记进 `REGISTERED_RESIDUALS`（见 `problems_registered_decisions`）。
- 本守卫**只读源码文本**（零依赖：只用标准库 + 共用的静态归属机具
  `backend/ai-agent-service/tests/tool_http_attribution.py`），不连库、不跑 LLM。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE = REPO_ROOT / "backend" / "ai-agent-service"
TOOLS_DIR = AI_SERVICE / "app" / "tools"
SKILLS_DIR = AI_SERVICE / "app" / "graph" / "skills"
AGENTS_DIR = AI_SERVICE / "app" / "agents" / "agents"
JAVA_MAIN = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
CONTROLLER_DIR = JAVA_MAIN / "com" / "migao" / "admin" / "controller"
SERVICE_DIR = JAVA_MAIN / "com" / "migao" / "admin" / "service"
MENU_TS = REPO_ROOT / "frontend/admin-web/src/config/menu.ts"
MENU_CONTROLLER = CONTROLLER_DIR / "MenuController.java"
AUTH_SERVICE = SERVICE_DIR / "AuthService.java"
USER_CONTROLLER = CONTROLLER_DIR / "UserController.java"
REGISTRATION_SERVICE = SERVICE_DIR / "RegistrationService.java"
PERMISSION_SERVICE = SERVICE_DIR / "PermissionService.java"
ROLE_SERVICE = SERVICE_DIR / "RoleService.java"
ATTRIBUTION_PATH = AI_SERVICE / "tests" / "tool_http_attribution.py"

# ══════════════════════════════════════════════════════════════════════════════
# 一、共用的静态归属机具（**不造第二套解析器**：issue #3570 的教训）
# ══════════════════════════════════════════════════════════════════════════════


def _load_attribution():
    """按路径加载 `tool_http_attribution`（零依赖；与 payload 契约门禁**同一份**机具）。"""
    name = "migao_tool_http_attribution"
    if name in sys.modules:
        return sys.modules[name]
    assert ATTRIBUTION_PATH.is_file(), f"共用归属机具不存在：{ATTRIBUTION_PATH}（路径漂移 ⇒ 红）"
    spec = importlib.util.spec_from_file_location(name, ATTRIBUTION_PATH)
    mod = importlib.util.module_from_spec(spec)
    # `from __future__ import annotations` + `@dataclass` 需要模块已在 sys.modules 里
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ATTR = _load_attribution()


# ══════════════════════════════════════════════════════════════════════════════
# 二、读源（**全部走源码文本**，便于注入式红证：改一处文本 ⇒ 判据必红）
# ══════════════════════════════════════════════════════════════════════════════


def _tool_sources() -> dict[str, str]:
    return {
        f"tool:{p.name}": p.read_text(encoding="utf8")
        for p in sorted(TOOLS_DIR.glob("*.py"))
        if p.name not in ("__init__.py", "base.py", "registry.py", "langchain_adapter.py")
    }


def _java_controller_sources() -> dict[str, str]:
    return {
        f"java:controller/{p.relative_to(CONTROLLER_DIR).as_posix()}": p.read_text(encoding="utf8")
        for p in sorted(CONTROLLER_DIR.rglob("*.java"))
    }


def _source_map() -> dict[str, str]:
    """判据的全部输入（注入式红证就是替换这里的某一项文本）。"""
    srcs = dict(_tool_sources())
    srcs.update(_java_controller_sources())
    for key, path in (
        ("java:service/RegistrationService.java", REGISTRATION_SERVICE),
        ("java:service/PermissionService.java", PERMISSION_SERVICE),
        ("java:service/RoleService.java", ROLE_SERVICE),
        ("java:service/AuthService.java", AUTH_SERVICE),
        ("menu:frontend", MENU_TS),
        ("menu:controller", MENU_CONTROLLER),
        ("menu:auth", AUTH_SERVICE),
        ("menu:user", USER_CONTROLLER),
    ):
        assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
        srcs[key] = path.read_text(encoding="utf8")
    for p in sorted(SKILLS_DIR.glob("*.py")):
        srcs[f"skill:{p.name}"] = p.read_text(encoding="utf8")
    for name in ("mibao", "xiaobu"):
        p = AGENTS_DIR / f"{name}.py"
        srcs[f"agent:{name}"] = p.read_text(encoding="utf8")
    return srcs


# ── 2.1 工具声明 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolDecl:
    file: str                      # `app/tools/xxx.py`
    name: str
    read_only: bool
    required_permissions: tuple[str, ...]
    c_end_reachable: bool
    declared_allowed_roles: tuple[str, ...] | None   # None = 类体未声明（吃 BaseTool 默认值）
    destructive: bool
    description: str
    endpoints: tuple[tuple[str, str, str | None], ...] = ()   # (verb, 归一化路径, 生效码)


def _class_literal(node: ast.ClassDef, attr: str):
    """类体里 `attr = <literal>` 的值（未声明 ⇒ None；非字面量 ⇒ None 并由自检报出）。"""
    for st in node.body:
        if (
            isinstance(st, ast.Assign)
            and len(st.targets) == 1
            and isinstance(st.targets[0], ast.Name)
            and st.targets[0].id == attr
        ):
            try:
                return ast.literal_eval(st.value)
            except ValueError:
                return None
    return None


def _declares(node: ast.ClassDef, attr: str) -> bool:
    return any(
        isinstance(st, ast.Assign)
        and len(st.targets) == 1
        and isinstance(st.targets[0], ast.Name)
        and st.targets[0].id == attr
        for st in node.body
    )


def parse_tools(sources: dict[str, str]) -> tuple[ToolDecl, ...]:
    """S1：`app/tools/*.py` 里每个 `name = "..."` 的工具类声明。"""
    out: list[ToolDecl] = []
    for key, text in sorted(sources.items()):
        if not key.startswith("tool:"):
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = _class_literal(node, "name")
            if not isinstance(name, str):
                continue
            ro = _class_literal(node, "read_only")
            rp = _class_literal(node, "required_permissions")
            ar = _class_literal(node, "allowed_roles")
            out.append(
                ToolDecl(
                    file=f"app/tools/{key.split(':', 1)[1]}",
                    name=name,
                    read_only=True if ro is None else bool(ro),
                    required_permissions=tuple(rp or ()),
                    c_end_reachable=bool(_class_literal(node, "c_end_reachable") or False),
                    declared_allowed_roles=None if ar is None else tuple(ar),
                    destructive=bool(_class_literal(node, "destructive") or False),
                    description=str(_class_literal(node, "description") or ""),
                )
            )
    assert out, "工具解析出 0 个声明 ⇒ 判据会空跑（fail-closed）"
    return tuple(out)


# ── 2.2 端点生效码（复用共用归属机具）─────────────────────────────────────────


def _java_sources_from(sources: dict[str, str]) -> dict[str, str]:
    """把守卫的源码表投影成共用机具要的 {相对 java 根: 源码} 形态。

    为什么必须这样做（而不是让机具读磁盘）：注入式红证改的是**内存里的源码文本**，
    若端点解析仍读磁盘 ⇒ Java 侧的任何注入都不会改变判据输入 ⇒ 判据永远不变红（空断言）。
    实测踩过：`⑨ 删掉一个 @RequirePermission` 注入后判据 8 纹丝不动。
    """
    out: dict[str, str] = {}
    for key, text in sources.items():
        if key.startswith("java:controller/"):
            out[f"com/migao/admin/controller/{key.split('/', 1)[1]}"] = text
        elif key.startswith("java:service/"):
            out[f"com/migao/admin/service/{key.split('/', 1)[1]}"] = text
    return out


def _endpoint_index(sources: dict[str, str]):
    return ATTR.JavaEndpointIndex(java_sources=_java_sources_from(sources))


def endpoints_by_tool(index) -> dict[str, tuple[tuple[str, str, str | None], ...]]:
    """S1×S2：每个工具文件的 HTTP 调用点 → 目标端点的**生效**权限码。"""
    out: dict[str, list[tuple[str, str, str | None]]] = {}
    for call in ATTR.tool_calls():
        eps = index.lookup(call.method, call.endpoint)
        for ep in eps:
            out.setdefault(call.file, []).append((call.method, ep.path, ep.permission))
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


# ── 2.3 菜单四处来源 ──────────────────────────────────────────────────────────


def _iter_menu_ts(text: str):
    """`frontend/admin-web/src/config/menu.ts`：`key` → 其后的 `name` / `permissionCode`。"""
    keys = list(re.finditer(r"key:\s*'([^']+)'", text))
    for i, m in enumerate(keys):
        end = keys[i + 1].start() if i + 1 < len(keys) else len(text)
        chunk = text[m.end():end]
        nm = re.search(r"name:\s*'([^']+)'", chunk)
        cm = re.search(r"permissionCode:\s*'([^']+)'", chunk)
        if nm:
            yield nm.group(1), (cm.group(1) if cm else None)


def _iter_menu_controller(text: str):
    """`MenuController.MENU_TREE`：`MenuNode("<code>", "<label>")` 声明 → 变量表。"""
    decls = re.findall(r'MenuNode\s+(\w+)\s*=\s*new MenuNode\("([^"]*)",\s*"([^"]*)"\)', text)
    for _var, code, label in decls:
        yield label, (code or None)


def _iter_menu_auth(text: str):
    """`AuthService.buildMenusByPermissions`：`permissions.contains("code")` + `menuItem(key, name, path)`。"""
    pattern = re.compile(
        r'permissions\.contains\("([^"]+)"\)\)\s*\{\s*\n\s*\w+\.add\(\s*menuItem\("([^"]+)",\s*"([^"]+)"'
    )
    for m in pattern.finditer(text):
        yield m.group(3), m.group(1)


def _iter_menu_user(text: str):
    """`UserController.generateMenus`（**第四处**，5 节点遗留树）：`.key(...)` + `.name(...)`。"""
    pattern = re.compile(
        r'permissions\.contains\("([^"]+)"\)\)\s*\{\s*\n\s*menus\.add\([^;]*?\.key\("([^"]+)"\)\s*\n\s*\.name\("([^"]+)"\)',
        re.S,
    )
    for m in pattern.finditer(text):
        yield m.group(3), m.group(1)


MENU_SOURCES = {
    "frontend": ("menu:frontend", _iter_menu_ts),
    "controller": ("menu:controller", _iter_menu_controller),
    "auth": ("menu:auth", _iter_menu_auth),
    "user": ("menu:user", _iter_menu_user),
}


def parse_menus(sources: dict[str, str]) -> dict[str, dict[str, str | None]]:
    """S3：四处菜单源的 `节点名 → 权限码`（无码节点值为 None）。"""
    out: dict[str, dict[str, str | None]] = {}
    for label, (key, it) in MENU_SOURCES.items():
        nodes = dict(it(sources[key]))
        assert nodes, f"菜单源 `{label}`（{key}）解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
        out[label] = nodes
    return out


# ── 2.4 权限目录与岗位矩阵 ────────────────────────────────────────────────────

_CATALOG_ROW_RE = re.compile(
    r'\{\s*"[^"]*",\s*"([^"]+)",\s*"[^"]*",\s*"[^"]*",\s*"[^"]*"\s*\}'
)


def parse_catalog(reg_text: str, perm_text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """权限目录两处：`RegistrationService.defaultPermissions` 与 `PermissionService` 的懒补种目录。"""
    reg = tuple(_CATALOG_ROW_RE.findall(reg_text))
    perm = tuple(_CATALOG_ROW_RE.findall(perm_text))
    assert reg and perm, "权限目录解析出 0 条 ⇒ 判据会空跑（fail-closed）"
    return reg, perm


def parse_role_defaults(reg_text: str) -> dict[str, frozenset[str]]:
    """S4：内置岗位默认权限（`Role.builder()...code("x")` 变量 + `attachDefaultPermissions` 列表）。"""
    var_to_code = dict(re.findall(r'Role\s+(\w+)\s*=\s*Role\.builder\(\)(.*?)\.build\(\);', reg_text, re.S))
    var_to_code = {v: re.search(r'code\("([^"]+)"\)', body).group(1) for v, body in var_to_code.items()
                   if re.search(r'code\("([^"]+)"\)', body)}
    out: dict[str, frozenset[str]] = {}
    for m in re.finditer(
        r"attachDefaultPermissions\(tenantId,\s*(\w+),\s*(List\.of\(([^)]*)\)|permissionByCode\.keySet\(\))",
        reg_text,
        re.S,
    ):
        var, arg, codes = m.group(1), m.group(2), m.group(3)
        role = var_to_code.get(var)
        assert role, f"`attachDefaultPermissions` 的变量 `{var}` 找不到对应角色码（解析失配 ⇒ 红）"
        if arg.startswith("permissionByCode"):
            out[role] = frozenset({"*"})       # admin 恒为全部权限
        else:
            out[role] = frozenset(re.findall(r'"([^"]+)"', codes or ""))
    assert len(out) >= 5, f"内置岗位解析出 {len(out)} 个 ⇒ 判据会空跑（fail-closed）：{sorted(out)}"
    return out


def parse_role_fallback(role_text: str) -> dict[str, frozenset[str]]:
    """S4（回退口径）：`RoleService.getPermissionCodesForRole` 的硬编码 `case "x" -> List.of(...)`。"""
    body = role_text[role_text.find("getPermissionCodesForRole(String roleCode)"):]
    assert body, "`RoleService.getPermissionCodesForRole` 找不到（解析失配 ⇒ 红）"
    return {
        m.group(1): frozenset(re.findall(r'"([^"]+)"', m.group(2)))
        for m in re.finditer(r'case\s+"([^"]+)"\s*->\s*List\.of\(([^;]*?)\);', body, re.S)
    }


# ── 2.5 skill 绑定（B 端 / C 端可达性的**唯一**真值源）────────────────────────


def _literal_list_at(text: str, open_idx: int) -> tuple[list[str], int] | None:
    """从 `[` 起做括号配平，返回 (字面量值, `]` 下标)。

    不能用 `\\[.*?\\n\\]` 这类正则：本仓既有**单行**列表（`SETTINGS_TOOLS = ["a", "b"]`）也有
    **多行且 `]` 不另起一行**的列表（`DATA_TOOLS = [... "interact"]`）⇒ 正则只认得其中一种，
    另一种被静默丢掉（实测：15 个 skill 只解析出 9 个 —— 少掉的正是 C 端商品/算料/知识三支）。
    """
    depth = 0
    i = open_idx
    in_str: str | None = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == in_str and text[i - 1] != "\\":
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    value = ast.literal_eval(text[open_idx: i + 1])
                except (ValueError, SyntaxError):
                    return None
                return list(value), i
        i += 1
    return None


def parse_skill_bindings(sources: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """skill 名 → 工具清单（`SkillConfig(name="x")` + 同模块的 `*_TOOLS`）。"""
    out: dict[str, tuple[str, ...]] = {}
    for key, text in sources.items():
        if not key.startswith("skill:"):
            continue
        nm = re.search(r'(?:SkillConfig|create_skill_config)\(\s*\n?\s*name="([^"]+)"', text)
        tools: tuple[str, ...] = ()
        for m in re.finditer(r"^([A-Z_]+_TOOLS)\s*(?::[^=]+)?=\s*\[", text, re.M):
            parsed = _literal_list_at(text, m.end() - 1)
            if parsed and all(isinstance(x, str) for x in parsed[0]):
                tools = tuple(parsed[0])
                break
        if nm and tools:
            out[nm.group(1)] = tools
    assert len(out) >= 12, f"skill 绑定解析出 {len(out)} 个 ⇒ 判据会空跑（fail-closed）：{sorted(out)}"
    return out


def parse_agent_skills(sources: dict[str, str], agent: str) -> tuple[frozenset[str], str | None]:
    """某人格的 `skill_names` + `fallback_skill`。"""
    text = sources[f"agent:{agent}"]
    m = re.search(r"skill_names=\[(.*?)\]", text, re.S)
    assert m, f"`{agent}` 的 `skill_names` 解析失配 ⇒ 红"
    names = frozenset(re.findall(r'"([^"]+)"', m.group(1)))
    fb = re.search(r'fallback_skill="([^"]+)"', text)
    return names, (fb.group(1) if fb else None)


# ══════════════════════════════════════════════════════════════════════════════
# 三、核定表（**判据的唯一来源**；新增/改动必须显式落在这里 —— diff 里看得见）
# ══════════════════════════════════════════════════════════════════════════════

#: 工具 → 其对应菜单节点（**节点名逐字取自四处菜单源**）。
#: 取值口径（issue #5246 的裁定）：**节点的码就是该工具应当持有的码**；
#: 节点无码（全员可见）⇒ 该工具只受端点层约束。
TOOL_MENU_NODE: dict[str, str] = {
    "order_query": "订单列表",
    "order_manage": "订单列表",
    "logistics_track": "订单列表",
    "order_create": "订单列表",
    "after_sales_manage": "售后工单",
    "customer_manage": "客户列表",
    "dashboard_stats": "经营看板",
    "finance_api": "财务对账",
    "session_manage": "在线接待",
    "employee_manage": "员工管理",
    "role_manage": "岗位权限",
    "settings_manage": "企业基础信息",
    "notification_manage": "通知中心",
    "product_search": "商品列表",
    "product_detail": "商品列表",
    "product_manage": "商品列表",
    "product_update": "商品列表",
    "sku_update": "商品列表",
    "inventory_manage": "商品列表",
    "batch_stock_query": "商品列表",
    "category_manage": "商品列表",
    "processing_item_query": "加工项管理",
    "processing_item_manage": "加工项管理",
    "processing_order_query": "生产看板",
    "processing_order_generate": "生产看板",
    "processing_order_update": "生产看板",
    "production_progress_query": "生产看板",
    "production_worklog_query": "生产看板",
    "piecework_query": "计件工资",
    "knowledge_search": "知识库",
}

#: 该菜单**页**允许的写码（判据 3 的「写工具可持页内写码」口径）：
#: 页面读码 → 从该页发起的写动作所用的码。
PAGE_WRITE_CODES: dict[str, frozenset[str]] = {
    "product:list": frozenset({"product:create", "product:category", "product:manage"}),
    # issue #5246 第二批（用户裁定本轮一并收口）：订单/客户/财务/会话四域**拆出真写码** ——
    # 此前写动作挂在读码上（只读持有者因此拿到写能力）。写码**没有菜单节点**（按钮级），
    # 故在此登记「它属于哪个页」；判据 4 会按所属页的读码反查岗位可见性。
    "order:list": frozenset({"order:refund", "order:detail", "order:update", "order:create"}),
    "after_sales:view": frozenset({"order:refund"}),
    "customer:view": frozenset({"customer:create"}),
    "finance:view": frozenset({"finance:create"}),
    "agent:session": frozenset({"agent:session:manage"}),
    "processing:manage": frozenset({"processing:update"}),
    "employee:list": frozenset({"employee:create"}),
    "knowledge:view": frozenset({"knowledge:manage"}),
    "inbound:view": frozenset({"inbound:create"}),
}

#: 纯本地工具（**无任何 admin-api HTTP 调用点** ⇒ 没有可对账的端点码）。
#: 与「实际解析出的无调用点工具集」必须**双向相等**（陈旧条目也红）。
LOCAL_ONLY_TOOLS: dict[str, str] = {
    "validate_input": "纯本地入参校验：不读库不写库；双端都要用（#4147 G1b 的 `allowed_roles=[\"*\"]`）",
    "interact": "纯本地交互卡构造（confirm/choice/form 的载荷生成）：无 admin-api 调用点",
}

#: 读码后缀（判据 5 的机械口径）：`模块:动作` 的动作 ∈ 这些 ⇒ 读码，其余 ⇒ 写/管理码。
READ_CODE_ACTIONS = frozenset({"view", "list", "detail", "session"})

#: 读写码冲突的**具名例外**（判据 5）：每条必须带理由 + 建议修法；条目陈旧（不再冲突）也红。
READ_WRITE_EXCEPTIONS: dict[str, str] = {
    # ⚠️ 只读工具却持**管理码**的**唯一**残留：生产域**没有可用的读码** ——
    # `processing:view` 在任一处菜单源里都没有节点（「生产看板/计件工资/工艺配置」的节点码
    # 都是 `processing:manage`）⇒ 若让工具持 `processing:view`，就等于允许"页面里看不到、
    # Agent 却查得到"（用户裁定禁止）。用户裁定：**不得改节点码、不得给岗位新增权限**
    # ⇒ 唯一可行方向是工具码对齐节点码（收窄），读写粒度债如实登记。
    # 建议（未实装）：为生产域引入真正的读码（如 `production:view`）并把节点与端点同批迁过去。
    "processing_item_query": "节点『加工项管理』= `processing:manage`（该域无读节点）⇒ 只读工具不得不持管理码。"
                             "建议：新开生产域读码并把节点/端点/工具同批迁移",
    "processing_order_query": "节点『生产看板』= `processing:manage`（加工单列表已并入该页），端点同批收窄为同码。"
                              "建议：同上",
    "production_progress_query": "同『生产看板』节点码。建议：同上",
    "production_worklog_query": "同『生产看板』节点码。建议：同上",
    "piecework_query": "节点『计件工资』= `processing:manage`。建议：同上",
}

#: 未注解端点的**显式登记**（判据 8；键 = `verb 归一化路径` 或 `verb /前缀*`）。
#: 口径 = `docs/wiki/RBAC.md` 的「权限注解面审计（issue #4727）」逐条结论：该放行的**登记为有意放行**。
UNANNOTATED_ENDPOINTS: dict[str, str] = {
    "GET /api/auth/*": "公开登录/OAuth/refresh（`permitAll`）+ 自助 me（#4727 第 8 行：加码 = 线上故障）",
    "POST /api/auth/*": "同上（登录/短信/绑定手机号/注册）",
    "GET /api/super-admin/*": "超管面不在 `/api/admin/**`，已由 `checkSuperAdminPermission()` 显式校验 `super_admin`",
    "PUT /api/super-admin/*": "同上",
    "GET /api/admin/menus": "静态权限目录常量；「员工管理」页的勾选树依赖它（#4727 第 6 行）",
    "GET /api/admin/user/info": "自助首屏：只返回当前用户自己的角色/权限/菜单（#4727 第 7 行）",
    "GET /api/admin/roles": "「员工管理」页岗位下拉的数据源（写面已是 `system:manage`；#4727 部分覆盖表）",
    "GET /api/admin/roles/all": "同上",
    "GET /api/admin/roles/{}": "同上",
    "PUT /api/admin/settings/password": "自助改密：只改当前认证用户自己的密码（#4727 部分覆盖表）",
    "GET /api/admin/notifications*": "自助通知中心：收件人一律取 `SecurityContext` 当前用户（#4727 第 4 行）",
    "PUT /api/admin/notifications*": "同上（标记已读）",
    "DELETE /api/admin/notifications*": "同上（删除自己的通知）",
    "POST /api/admin/agent/audit-logs": "内部服务**取证上报**面：加码会让受限岗位的写操作审计被 403（#4727 第 11 行，"
                                        "取证缺口不可接受 —— 这是审计明说该放行的一条）",
    "GET /api/customer/*": "C 端人工会话面：不走 `/api/admin/**` 门禁，隔离靠业务层 `X-User-Id` 过滤",
    "POST /api/customer/*": "同上",
    "GET /api/worker/*": "工人端身份（#4716 设计 C11 预留）：`ADMIN_API_REJECTED_ROLES` 已把 worker 挡在 `/api/admin/**` 之外",
    "POST /api/worker/*": "同上",
    "GET /s/{}": "短链跳转（`permitAll`，无租户数据）",
}

#: `RoleService.getPermissionCodesForRole` 里**有意保留**的历史角色（admin-api 无角色行/无种子）：
#: 它们是存量库里的岗位码，回退表保住兼容；新增任何角色都必须先落进种子矩阵，否则判据 9 红。
LEGACY_ROLES_IN_FALLBACK: dict[str, str] = {
    "product_manager": "POC 期的历史岗位码（`mibao.py` 的 `allowed_roles` 仍在用）：无 roles 行，只有回退表口径",
    "knowledge_editor": "同上（知识库编辑岗）",
}

#: **已知但不修**的残留（判据 8）：带理由 + 去向，禁止沉默。
REGISTERED_RESIDUALS: dict[str, dict[str, str]] = {
    "settings 域写面未注解": {
        "what": "`SettingsController` 的 `PUT /api/admin/settings` / 收款码写面 / 登录日志读面没有权限码",
        "why": "该域只有 `system:manage` 一个码（企业基础信息页），而设置读写是**全岗位自助**语义；"
               "加码会砍掉非管理员的基础设置能力 —— 属产品裁定，不在本单授权范围",
        "where": "本守卫 `UNANNOTATED_ENDPOINTS` 已逐条登记；去向：#5236 菜单/权限统一",
    },
    "通知模块无权限码": {
        "what": "`NotificationController` 六个端点里五个无码（仅 `POST` 补了 `system:manage`）",
        "why": "通知域在 admin-api 权限目录里**没有任何码**；读面是自助语义（收件人取当前用户）",
        "where": "去向：#5247（B 端通知能力下线）+ #5236；本守卫按『未覆盖模块』登记，不臆造码",
    },
    "生产域缺读码": {
        "what": "生产域读面（生产看板/计件工资/工艺配置）的菜单码与端点码都是 `processing:manage`，"
                "而只读工具（`processing_item_query`/`piecework_query`/`production_*_query`）不得不持管理码",
        "why": "节点码早已是 `processing:manage`；按用户裁定「不得改变节点码、不得给岗位新增权限」，"
               "唯一可行方向是把**工具码对齐节点码**（收窄），读写粒度残留如实登记",
        "where": "见 `READ_WRITE_EXCEPTIONS` 逐条；去向：为生产域设计真正的读码（产品裁定）",
    },
    "订单/客户/财务/会话缺写码": {
        "what": "`order_manage` / `customer_manage` / `finance_api` / `session_manage` 是写工具，"
                "但目录里对应资源只有读码（或唯一码即 `order:list` / `customer:view` / `finance:view` / `agent:session`）",
        "why": "新增写码 = 产品裁定（谁拿到该码就是一次授权变更）；本单授权范围只含两个**读**码"
               "（`after_sales:view` / `knowledge:view`）",
        "where": "见 `READ_WRITE_EXCEPTIONS` 逐条（含建议码名）；去向：#5236",
    },
    "生产池读端点仍是 processing:view（节点是 processing:manage）": {
        "what": "`ProductionPoolController` 的两个读端点（`GET /api/admin/production/pool`、`/pool/preview` 的读面）"
                "仍挂 `processing:view`，而『池看板』菜单节点是 `processing:manage`",
        "why": "与 `ProcessingOrderController` 同类（读码没有对应菜单节点）；但**没有任何 Agent 工具**"
               "调用这两个端点 ⇒ 不在本守卫判据 2/3/4 的射程内（工具侧已全部对账），"
               "改它只是端点收窄，属本单授权范围外的产品动作",
        "where": "实测（`tool_http_attribution.JavaEndpointIndex`）逐端点生效码可复算；去向：#5236",
    },
    "端点层写挂读码（非 Agent 可达）": {
        "what": "`ProductionController`（类级 `order:list` 下仍混着 `POST /orders/{}/ship`、"
                "`/instantiate`、`/operations/{}/report`、`/print` 等写端点）与 `UploadController` 的 "
                "`DELETE /files/{}`、`DELETE /upload/image`（挂 `dashboard:view`）",
        "why": "这些端点**没有任何 Agent 工具调用**（工具侧已全部对账）；订单/客户/财务/会话四域已在 "
               "issue #5246 追加单里拆出真写码（`order:update`/`order:create`/`customer:create`/"
               "`finance:create`/`agent:session:manage`），剩下这两处要么新增生产域写码/上传域码"
               "（产品裁定），要么改前端调用口径 —— 超出本单授权",
        "where": "`UNANNOTATED_ENDPOINTS` 只管「无码」；本项是「有码但码粒度错」，逐条记在这里；去向：#5236",
    },
    "第四处菜单源（遗留树）": {
        "what": "`UserController.generateMenus` 是 **5 节点遗留树**（经营看板/商品管理/加工项管理/知识库管理/系统设置），"
                "用粗码 `product:manage`，且不含售后工单/生产看板/订单列表等节点",
        "why": "四处菜单源全树同构是 #5236 的产品裁定（前端 7 组 vs 服务端 9 节点 vs 遗留 5 节点，"
               "节点集本就不同）；本守卫只比**交集**（同名节点不得两处不同码）",
        "where": "交集覆盖度由 `problems_menu_parity` 的 `CROSS_CHECKED_FLOOR` 自检；去向：#5236",
    },
    "MenuController 省略的节点": {
        "what": "**只剩「通知中心」**：它不在 `MenuController.MENU_TREE`（该树每个节点都必须有权限码，"
                "而通知中心是全员可见项）—— 但它在 `AuthService` 的下发面里。"
                "issue #5271 起服务端两处已镜像侧边栏全部 7 组（含 在线接待/知识库/岗位权限/"
                "企业基础信息/每日简报），本条残留原先列的其它节点**均已消除**",
        "why": "通知中心无权限码 ⇒ 结构上不进权限树（不是漏改）；三处菜单源（前端 / `MenuController` / "
               "`AuthService`）现已是**全树同构**，判据见 `test_menu_three_sources_are_isomorphic.py`"
               "（#5271 升级）；第四处源的全树统一是 #5236 的产品裁定",
        "where": "交集覆盖度由 `problems_menu_parity` 的 `CROSS_CHECKED_FLOOR` 自检；去向：#5236（第四处源）",
    },
    "权限码零消费": {
        "what": "`order:detail` / `product:manage` 在目录里且被岗位授予/菜单使用，但没有任何 "
                "`@RequirePermission` 消费它们（`product:manage` 只出现在第四处菜单源）",
        "why": "删码/改码会动岗位矩阵（产品裁定）；本单不动",
        "where": "去向：#5236",
    },
    "行为评测用例未补": {
        "what": "本单未新增/修改 `.github/cases/**` 的行为用例（如「客服经米宝查售后不再 403」的正向对照）",
        "why": "B 端 skill 工具绑定与提示词属 #5247（在其上 rebase），行为面用例应与绑定同批落地",
        "where": "去向：#5247（input 已写进 PR 说明）",
    },
}

#: 四处菜单源**交集**的覆盖度下限（自检：低于它说明解析面缩小了 ⇒ 红）。
#: 实测值（含 after-sales/知识库改动后）见 `problems_menu_parity` 的报错文案；不写死到刚好相等，
#: 留 2 个余量 —— 但**只许上调**：改小它等于把「不检查」伪装成「检查过」。
CROSS_CHECKED_FLOOR = 8


@dataclass(frozen=True)
class World:
    """判据的全部输入（注入式红证 = 用改过的文本重建它）。"""

    tools: tuple[ToolDecl, ...]
    endpoints: dict[str, tuple[tuple[str, str, str | None], ...]]
    all_eps: dict[tuple[str, str], tuple]
    menus: dict[str, dict[str, str | None]]
    catalog: tuple[str, ...]
    catalog_perm_service: tuple[str, ...]
    roles: dict[str, frozenset[str]]
    role_fallback: dict[str, frozenset[str]]
    skills: dict[str, tuple[str, ...]]
    b_end_tools: frozenset[str]
    c_end_tools: frozenset[str]
    sources: dict[str, str] = field(default_factory=dict)


def build_world(sources: dict[str, str]) -> World:
    tools = parse_tools(sources)
    index = _endpoint_index(sources)
    eps = endpoints_by_tool(index)
    skills = parse_skill_bindings(sources)
    c_skill_names, c_fallback = parse_agent_skills(sources, "xiaobu")
    b_skill_names, b_fallback = parse_agent_skills(sources, "mibao")
    c_skills = set(c_skill_names) | ({c_fallback} if c_fallback else set())
    b_skills = set(b_skill_names) | ({b_fallback} if b_fallback else set())
    c_tools = {t for s in c_skills for t in skills.get(s, ())}
    b_tools = {t for s in b_skills for t in skills.get(s, ())}
    assert c_tools, "C 端工具集解析为空 ⇒ 判据会空跑（fail-closed）"
    assert b_tools, "B 端工具集解析为空 ⇒ 判据会空跑（fail-closed）"
    tools = tuple(
        ToolDecl(**{**t.__dict__, "endpoints": eps.get(t.file, ())}) for t in tools
    )
    reg_cat, perm_cat = parse_catalog(
        sources["java:service/RegistrationService.java"], sources["java:service/PermissionService.java"]
    )
    return World(
        tools=tools,
        endpoints=eps,
        all_eps=index.endpoints(),
        menus=parse_menus(sources),
        catalog=reg_cat,
        catalog_perm_service=perm_cat,
        roles=parse_role_defaults(sources["java:service/RegistrationService.java"]),
        role_fallback=parse_role_fallback(sources["java:service/RoleService.java"]),
        skills=skills,
        b_end_tools=frozenset(b_tools),
        c_end_tools=frozenset(c_tools),
        sources=sources,
    )


def world() -> World:
    return build_world(_source_map())


def _by_name(w: World) -> dict[str, ToolDecl]:
    return {t.name: t for t in w.tools}


def _c_end_reachable(w: World) -> frozenset[str]:
    """C 端可达工具集（**推导**：小布的 skill_names + fallback → 各自 `*_TOOLS`）。"""
    return w.c_end_tools


def _coded_b_end(w: World) -> list[ToolDecl]:
    return [t for t in w.tools if t.name in w.b_end_tools and t.required_permissions]


def _node_code(w: World, node_name: str) -> str | None:
    """节点码（以**前端侧边栏** `config/menu.ts` 为真值源；节点不存在 ⇒ KeyError 由判据报出）。"""
    return w.menus["frontend"][node_name]


def _is_read_code(code: str) -> bool:
    return code.split(":")[-1] in READ_CODE_ACTIONS


def _endpoint_patterns() -> dict[str, str]:
    return UNANNOTATED_ENDPOINTS


# ══════════════════════════════════════════════════════════════════════════════
# 四、九条判据（纯函数：输入 `World`，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_missing_codes(w: World) -> list[str]:
    """判据 1：B 端可达的工具必须声明权限码；白名单 = 「无 admin-api 调用点」且双向相等。"""
    out: list[str] = []
    derived = {
        t.name for t in w.tools if t.name in w.b_end_tools and not t.endpoints
    }
    if derived != set(LOCAL_ONLY_TOOLS):
        out.append(
            "纯本地工具登记表与实际不符（陈旧条目 = 白名单在偷偷变长）：\n"
            f"    实际无 admin-api 调用点的 B 端工具 = {sorted(derived)}\n"
            f"    登记表 = {sorted(LOCAL_ONLY_TOOLS)}"
        )
    for t in w.tools:
        if t.name not in w.b_end_tools or t.required_permissions:
            continue
        if t.name in LOCAL_ONLY_TOOLS:
            continue
        out.append(
            f"{t.name}（{t.file}）：B 端可达、又**有** admin-api 调用点"
            f"（{[f'{v} {p}' for v, p, _ in t.endpoints][:3]}…），却未声明 required_permissions —— "
            "加码前它靠手写角色白名单把关，必然与目录漂移（#4106 F3/F4）"
        )
    return out


def problems_endpoint_parity(w: World) -> list[str]:
    """判据 2：工具码 ≡ 它调用的每个端点生效码；未注解端点必须显式登记。"""
    out: list[str] = []
    for t in _coded_b_end(w):
        codes = set(t.required_permissions)
        effective = {p for _, _, p in t.endpoints if p}
        if codes != effective:
            out.append(
                f"{t.name}（{t.file}）：required_permissions={sorted(codes)} ≠ "
                f"其端点生效码 {sorted(effective)}"
                f"（端点：{sorted({f'{v} {p} → {c}' for v, p, c in t.endpoints})}）"
            )
        for verb, path, perm in t.endpoints:
            if perm is not None:
                continue
            key = f"{verb} {path}"
            if not _matches_registered(key, UNANNOTATED_ENDPOINTS):
                out.append(
                    f"{t.name} 调用了**未登记**的未注解端点 `{key}` —— "
                    "沉默放行正是本单要治的失效模式（登记进 UNANNOTATED_ENDPOINTS 并写明理由）"
                )
    return out


def _matches_registered(key: str, table: dict[str, str]) -> bool:
    verb, _, path = key.partition(" ")
    for pattern in table:
        p_verb, _, p_path = pattern.partition(" ")
        if p_verb and p_verb != verb:
            continue
        if p_path.endswith("*"):
            if path.startswith(p_path[:-1]):
                return True
        elif p_path == path:
            return True
    return False


def problems_menu_parity(w: World) -> list[str]:
    """判据 3：工具码 ≡ 菜单节点码（写工具可持页内写码/跨页读码）+ 四处菜单源在交集上同构。"""
    out: list[str] = []
    by_name = _by_name(w)
    front = w.menus["frontend"]
    node_codes = {c for c in front.values() if c}
    write_codes = {c for fam in PAGE_WRITE_CODES.values() for c in fam}
    # ① 每个已编码的 B 端工具都必须有节点登记（否则「没登记」会被读成「没问题」）
    for t in _coded_b_end(w):
        if t.name not in TOOL_MENU_NODE:
            out.append(f"{t.name}：已声明权限码但未登记对应菜单节点（TOOL_MENU_NODE）⇒ 判据 3/4 会跳过它")
    for name in TOOL_MENU_NODE:
        if name not in by_name:
            out.append(f"TOOL_MENU_NODE 里的 `{name}` 不是现存工具（陈旧登记）")
    # ② 每个码都必须有出处：某个菜单节点的码，或已登记的页内写码
    for name, node_name in sorted(TOOL_MENU_NODE.items()):
        t = by_name.get(name)
        if t is None or not t.required_permissions:
            continue
        for code in t.required_permissions:
            if code not in node_codes and code not in write_codes:
                out.append(
                    f"{name}：声明的码 `{code}` 既不是任何菜单节点的码、也不在 PAGE_WRITE_CODES 里"
                    "（= 没有页面对应的能力 / 新码没登记）"
                )
        if node_name not in front:
            out.append(
                f"{name} 的菜单节点『{node_name}』在 `config/menu.ts` 里不存在 "
                "（节点名漂移 ⇒ 先改本登记表再改代码）"
            )
            continue
        node_code = front[node_name]
        if node_code is None:
            continue          # 全员可见节点：无码可对
        codes = set(t.required_permissions)
        # 锚定口径：工具必须**至少持有一个「本页的码」**（节点码，或从本页发起的写码）——
        # 至于它另外还读别的页（如 `order_create` 在建单流程里读商品 `product:list`），
        # 那部分由判据 ②（码必须有出处）与判据 4（跨页可见性）分别把关。
        anchor = {node_code} | set(PAGE_WRITE_CODES.get(node_code, frozenset()))
        if not (codes & anchor):
            out.append(
                f"{name}：required_permissions={sorted(codes)} 与节点『{node_name}』"
                f"（本页码域 {sorted(anchor)}）无任何交集 ⇒ 工具做的事与它登记的页面不是同一件事"
            )
    # ③ 四处菜单源：**交集**上同名节点不得两处不同码
    checked: set[str] = set()
    base = {k: v for k, v in front.items() if v}
    for other, nodes in w.menus.items():
        if other == "frontend":
            continue
        common = {k for k in base if k in nodes and nodes[k]}
        checked |= common
        for node in sorted(common):
            if base[node] != nodes[node]:
                out.append(
                    f"菜单源不同构：节点『{node}』在 `frontend`={base[node]} / "
                    f"`{other}`={nodes[node]}（同名节点两处不同码 ⇒ 改一处不红）"
                )
    if len(checked) < CROSS_CHECKED_FLOOR:
        out.append(
            f"四处菜单源的**交集**只剩 {len(checked)} 个节点（下限 {CROSS_CHECKED_FLOOR}）"
            f"：{sorted(checked)} —— 解析面缩小 = 「没检查」被读成「检查过」"
        )
    return out


def _code_owner_pages(w: World) -> dict[str, set[str]]:
    """码 → 拥有它的菜单节点名集合（节点码直接命中；写码按 `PAGE_WRITE_CODES` 反查所属页）。"""
    owners: dict[str, set[str]] = {}
    for node, code in w.menus["frontend"].items():
        if code:
            owners.setdefault(code, set()).add(node)
    for page_code, writes in PAGE_WRITE_CODES.items():
        pages = owners.get(page_code, set())
        for code in writes:
            owners.setdefault(code, set()).update(pages)
    return owners


def problems_leakage(w: World) -> list[str]:
    """判据 4（**用户逐字要求**）：R 持有工具声明的码 ⇒ R 在菜单里看得见对应的页面节点。

    为什么对**每个码**做（而不是只对该工具的「主节点」）：工具的码可能跨页
    （`order_create` 同时持 `order:list` 与 `product:list`，因为它在建单流程里读商品），
    只查主节点会漏掉「R 能经 Agent 读商品、却看不到商品列表」这一半。
    写码没有节点（它是按钮级），按 `PAGE_WRITE_CODES` 反查**所属页**的节点。
    """
    out: list[str] = []
    owners = _code_owner_pages(w)
    declared: set[str] = set()
    for t in _coded_b_end(w):
        declared |= set(t.required_permissions)
    for role, perms in sorted(w.roles.items()):
        if "*" in perms:
            continue
        for code in sorted(declared & perms):
            pages = owners.get(code)
            if not pages:
                out.append(
                    f"权限泄露：码 `{code}`（岗位 `{role}` 持有、且被某个 Agent 工具声明）"
                    "**在任何菜单源里都没有节点** ⇒ 「Agent 做得到、页面里看不到」"
                )
                continue
            if not any(w.menus["frontend"].get(p) == code or code in PAGE_WRITE_CODES.get(
                    w.menus["frontend"].get(p) or "", set()) for p in pages):
                out.append(f"权限泄露：码 `{code}` 的归属节点解析失败（{sorted(pages)}）—— 同步本判据")
                continue
            visible = [
                p for p in pages
                if code in PAGE_WRITE_CODES.get(w.menus["frontend"].get(p) or "", set())
                or w.menus["frontend"].get(p) == code
            ]
            if not any((w.menus["frontend"].get(p) or "") in perms or w.menus["frontend"].get(p) is None
                       for p in visible):
                out.append(
                    f"权限泄露：岗位 `{role}` 持 `{code}` ⇒ 可经 Agent 用该能力，"
                    f"但菜单节点 {sorted(visible)} 需要的码"
                    f"（{[w.menus['frontend'].get(p) for p in visible]}）该岗位没有 ⇒ "
                    "「页面里看不到、Agent 却做得到」（用户裁定禁止）"
                )
    return out


def problems_read_write(w: World) -> list[str]:
    """判据 5：只读工具不得持写码；写工具不得只持读码（冲突走具名例外）。"""
    out: list[str] = []
    excused: set[str] = set()
    for t in _coded_b_end(w):
        codes = list(t.required_permissions)
        reads = [c for c in codes if _is_read_code(c)]
        writes = [c for c in codes if not _is_read_code(c)]
        conflict = (t.read_only and writes) or (not t.read_only and not writes and reads)
        if not conflict:
            continue
        if t.name in READ_WRITE_EXCEPTIONS:
            excused.add(t.name)
            continue
        if t.read_only and writes:
            out.append(
                f"{t.name}：`read_only=True`（只读）却要求写/管理码 {writes} ⇒ "
                "持读码的员工会被假拒绝，或（反向）读工具实际要求了写授权"
            )
        else:
            out.append(
                f"{t.name}：`read_only=False`（会写数据）却只要求读码 {reads} ⇒ "
                "只读持有者拿到写能力（端点层若同为读码，则**没有任何一层**拦它）"
            )
    for name, reason in READ_WRITE_EXCEPTIONS.items():
        if name not in excused:
            out.append(f"读写例外 `{name}` 已不冲突（或工具不存在）⇒ 陈旧例外必须删除：{reason[:40]}…")
        if not reason.strip():
            out.append(f"读写例外 `{name}` 缺理由（具名例外必须带理由 + 建议修法）")
    return out


C_END_ROLES = frozenset({"customer", "agent"})
GHOST_ROLES = frozenset({"tenant_admin", "worker"})


def problems_role_list_hygiene(w: World) -> list[str]:
    """判据 6：角色白名单卫生（假门禁 / C 端角色 / 幽灵角色）。

    口径：C 端角色写进 `allowed_roles` **只在两种情况下合法** ——
    ① 该工具**确实**被 C 端 skill 绑定（`derived_c_end`，如 `interact` / `validate_input`；
       C 端没有权限码，角色层就是它唯一的门禁）；② 工具**没有任何 admin-api 调用点**
       （纯本地：角色层管不到跨服务能力，幽灵角色也无从 403）。
    其余情况 = 「B 端独占能力对 C 端/幽灵角色开口子」（issue #5246 点名的 latent leak 形态）。
    """
    out: list[str] = []
    derived_c_end = _c_end_reachable(w)
    for t in w.tools:
        if t.name not in w.b_end_tools or t.declared_allowed_roles is None:
            continue
        declared = set(t.declared_allowed_roles)
        if t.required_permissions:
            out.append(
                f"{t.name}：同时声明 `required_permissions` 与 `allowed_roles` —— "
                "权限码在场时角色白名单**不生效**，留着只是第二份会漂移的假门禁"
            )
            continue
        if not t.endpoints:
            continue          # 纯本地工具：角色层不构成跨服务能力
        bad_c = declared & C_END_ROLES
        if bad_c and t.name not in derived_c_end:
            out.append(
                f"{t.name}：`allowed_roles` 含 C 端角色 {sorted(bad_c)}，而该工具**没有**被任何 "
                "C 端 skill 绑定（B 端独占）⇒ 横向越权隐患"
            )
        bad_g = declared & GHOST_ROLES
        if bad_g:
            out.append(
                f"{t.name}：`allowed_roles` 含幽灵角色 {sorted(bad_g)} —— "
                "admin-api 里没有该角色的行/权限映射，放行只会在端点层 403（跨服务口径断裂）"
            )
    return out


def problems_c_end_flag(w: World) -> list[str]:
    """判据 7：`c_end_reachable` ≡ 「被小布（C 端）的 skill 绑定」（不得手写）。"""
    out: list[str] = []
    derived = _c_end_reachable(w)
    for t in w.tools:
        if not t.required_permissions:
            continue
        should = t.name in derived
        if bool(t.c_end_reachable) != should:
            out.append(
                f"{t.name}：`c_end_reachable={t.c_end_reachable}` 但按 skill 绑定推导应为 {should} —— "
                "C 端 JWT 没有权限码，标错会让 C 端全量失效，或让 B 端独占工具对 C 端开口子"
            )
    return out


def problems_registered_decisions(w: World) -> list[str]:
    """判据 8：未注解端点 = 显式登记的决定（登记不得陈旧）；残留必须带理由与去向。"""
    out: list[str] = []
    hit: set[str] = set()
    for (verb, path), eps in sorted(w.all_eps.items()):
        for ep in eps:
            if ep.permission is not None:
                continue
            key = f"{verb} {path}"
            matched = [p for p in UNANNOTATED_ENDPOINTS if _matches_registered(key, {p: ""})]
            if not matched:
                out.append(f"未注解端点 `{key}` 未登记（沉默放行 = 本单要治的失效模式）")
            hit |= set(matched)
    for pattern in UNANNOTATED_ENDPOINTS:
        if pattern not in hit:
            out.append(f"未注解端点登记项 `{pattern}` 已无对应端点（陈旧登记必须删除）")
    for name, entry in REGISTERED_RESIDUALS.items():
        for field_name in ("what", "why", "where"):
            if not entry.get(field_name, "").strip():
                out.append(f"残留登记 `{name}` 缺 `{field_name}`（必须写清理由与去向）")
    return out


def problems_self_checks(w: World) -> list[str]:
    """判据 9：解析器自检（防恒绿空跑 + 两处目录同源 + 回退矩阵一致）。

    每条都是「解析器自己失效」的形态：注解漏解析、目录两处不同步、岗位矩阵与硬编码回退漂移。
    """
    out: list[str] = []
    # ① 注解条数守恒：源文件里的 `@RequirePermission` 条数 == 解析出的注解位点数
    sites: dict[str, set] = {}
    for (verb, path), eps in w.all_eps.items():
        for ep in eps:
            if ep.method_permission:
                sites.setdefault(ep.controller, set()).add((ep.method_permission, ep.line))
            if ep.class_permission:
                sites.setdefault(ep.controller, set()).add((ep.class_permission, -1))
    for rel, src in w.sources.items():
        if not rel.startswith("java:controller/"):
            continue
        stripped = ATTR._strip_java_comments(src)  # noqa: SLF001
        total = len(ATTR._REQUIRE_PERMISSION_RE.findall(stripped))  # noqa: SLF001
        parsed = len(sites.get(f"com/migao/admin/controller/{rel.split('/', 1)[1]}", set()))
        if total != parsed:
            out.append(
                f"{rel}：`@RequirePermission` 条数守恒失败（源里 {total} 条 / 解析到 {parsed} 处）"
                " —— 有注解没被解析（写法变了）或解析器把非注解当成了注解"
            )
    # ② 两处权限目录逐值相等
    if set(w.catalog) != set(w.catalog_perm_service):
        out.append(
            "权限目录两处不同步：RegistrationService 与 PermissionService "
            f"（差集 {sorted(set(w.catalog) ^ set(w.catalog_perm_service))}）—— "
            "存量租户的岗位权限页会缺码/多码"
        )
    # ③ 岗位硬编码回退 ⊆ 种子矩阵；两个新读码的持有岗位两边一致
    for role, fallback in sorted(w.role_fallback.items()):
        seeded = w.roles.get(role)
        if seeded is None:
            if role not in LEGACY_ROLES_IN_FALLBACK:
                out.append(
                    f"`RoleService` 回退里的角色 `{role}` 既不在种子岗位矩阵、也没登记为历史角色"
                    f"（岗位码漂移）—— 登记进 LEGACY_ROLES_IN_FALLBACK 或补种子"
                )
            continue
        if "*" in seeded:
            continue
        extra = sorted(fallback - seeded)
        if extra:
            out.append(f"岗位 `{role}` 的硬编码回退多出种子矩阵没有的码 {extra}（回退会绕过岗位权限页）")
        for code in ("after_sales:view", "knowledge:view"):
            if (code in seeded) != (code in fallback):
                out.append(
                    f"岗位 `{role}` 的 `{code}` 在种子矩阵与硬编码回退里不一致"
                    f"（种子={code in seeded} / 回退={code in fallback}）"
                )
    # ④ 菜单码必须都在权限目录里（打错一个字母就查不到）
    known = set(w.catalog)
    for source, nodes in sorted(w.menus.items()):
        for node, code in sorted(nodes.items()):
            if code and code not in known:
                out.append(f"菜单源 `{source}` 的节点『{node}』用了目录里没有的码 `{code}`")
    # ⑤ 各集合非空（fail-closed）
    for label, value in (
        ("工具", len(w.tools)),
        ("端点", sum(len(v) for v in w.all_eps.values())),
        ("岗位", len(w.roles)),
        ("skill", len(w.skills)),
        ("B 端工具", len(w.b_end_tools)),
        ("C 端工具", len(w.c_end_tools)),
    ):
        if value < 5:
            out.append(f"{label}解析出 {value} 个 —— 解析面塌了（判据会空跑）")
    return out


JUDGEMENTS = {
    "1 · B 端工具必须声明权限码": problems_missing_codes,
    "2 · 工具码 ≡ 端点生效码": problems_endpoint_parity,
    "3 · 工具码 ≡ 菜单节点码 + 四源同构": problems_menu_parity,
    "4 · 零权限泄露": problems_leakage,
    "5 · 读写码不错配": problems_read_write,
    "6 · 角色白名单卫生": problems_role_list_hygiene,
    "7 · c_end_reachable 不得手写": problems_c_end_flag,
    "8 · 未注解端点/残留已登记": problems_registered_decisions,
    "9 · 解析器自检": problems_self_checks,
}


# ══════════════════════════════════════════════════════════════════════════════
# 五、断言（每条判据一条；全部绿 = 本单的四集合互相对账成立）
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """九条判据在**当前仓库**上全绿（红 = 权限面已经漂移，逐条问题见断言文案）。"""
    w = world()
    problems = {label: fn(w) for label, fn in JUDGEMENTS.items()}
    bad = {label: p for label, p in problems.items() if p}
    assert bad == {}, "权限对账判据未通过：\n" + "\n".join(
        f"  【{label}】\n    - " + "\n    - ".join(items[:12]) for label, items in bad.items()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 六、注入式红证：**每一条**判据都要有能单独变红的负向夹具（否则它只是空断言）
# ══════════════════════════════════════════════════════════════════════════════


def _set_codes(text: str, filename: str, codes: str) -> str:
    """把 `app/tools/<filename>` 里第一个 `required_permissions = [...]` 换成 `codes`。"""
    new, n = re.subn(
        r"required_permissions\s*=\s*\[[^\]]*\]",
        f"required_permissions = {codes}",
        text,
        count=1,
    )
    assert n == 1, f"注入锚点失配：{filename} 里没有 `required_permissions = [...]`（同步本判据）"
    return new


def _add_allowed_roles(text: str, roles: str) -> str:
    """往工具类体里插一行 `allowed_roles = [...]`（锚 = 第一个 `read_only =`）。"""
    new, n = re.subn(r"(\n(\s+)read_only\s*=\s*\w+\n)", rf"\1\2allowed_roles = {roles}\n", text, count=1)
    assert n == 1, "注入锚点失配：工具类里没有 `read_only = ...` 行（同步本判据）"
    return new


def _add_role_code(text: str, role_fragment: str, code: str) -> str:
    """给 `RegistrationService` 的某个岗位默认列表**加**一个码（判据 4 的注入面）。

    注意注入方向：**不能**用「从岗位删码」来造泄露 —— 删码会同时删掉「R 持有该码」这个**前提**，
    判据随即变成空跑（这正是「不会红的断言」的形态）。泄露的正确形态是
    「岗位拿到了写码、却没有该页的读码」⇒ 给 `finance` 加 `employee:create`（它没有 `employee:list`）。
    """
    anchor = f"attachDefaultPermissions(tenantId, {role_fragment}, List.of("
    idx = text.find(anchor)
    assert idx != -1, f"注入锚点失配：找不到 `{anchor}`（锚必须落在 attach 调用上）"
    end = text.find("permissionByCode)", idx)
    assert end != -1, "注入锚点失配：找不到该岗位列表的结尾"
    block = text[idx:end]
    assert f'"{code}"' not in block, f"注入前提：该岗位已经有 `{code}`（换一个码）"
    return text[:idx] + block.replace("List.of(", f'List.of("{code}", ', 1) + text[end:]


def _drop_role_code(text: str, role_fragment: str, code: str) -> str:
    """在 RegistrationService 的某个岗位默认列表里删掉一个码。"""
    anchor = f"attachDefaultPermissions(tenantId, {role_fragment}, List.of("
    idx = text.find(anchor)
    assert idx != -1, f"注入锚点失配：找不到 `{anchor}`"
    end = text.find("permissionByCode)", idx)
    assert end != -1, "注入锚点失配：找不到该岗位列表的结尾"
    block = text[idx:end]
    new_block = block.replace(f'"{code}", ', "", 1)
    assert new_block != block, f"注入锚点失配：该岗位列表里没有 `{code}`"
    return text[:idx] + new_block + text[end:]


def _injections() -> dict[str, tuple[str, "callable", "callable"]]:
    """`label` → (被判据读取的源键, 文本变异, 目标判据)。"""
    return {
        "① 工具码与目标端点不一致 ⇒ 判据 2 红": (
            "tool:order_query.py",
            lambda s: _set_codes(s, "order_query.py", '["dashboard:view"]'),
            problems_endpoint_parity,
        ),
        "② 往 B 端工具注入 C 端角色 ⇒ 判据 6 红": (
            "tool:role_manage.py",
            lambda s: _add_allowed_roles(s, '["admin", "customer"]'),
            problems_role_list_hygiene,
        ),
        "③ 岗位拿到写码却没有该页读码（finance += employee:create）⇒ 判据 4 红": (
            "java:service/RegistrationService.java",
            lambda s: _add_role_code(s, "financeRole", "employee:create"),
            problems_leakage,
        ),
        "③b 码没有任何菜单节点（改掉『售后工单』节点码）⇒ 判据 4 红": (
            "menu:frontend",
            lambda s: s.replace("permissionCode: 'after_sales:view'", "permissionCode: 'order:refund'", 1),
            problems_leakage,
        ),
        "④ 只改一处菜单源的节点码 ⇒ 判据 3 红": (
            "menu:controller",
            _diverge_shared_node,
            problems_menu_parity,
        ),
        "⑤ 只读工具要求写码 ⇒ 判据 5 红": (
            "tool:order_query.py",
            lambda s: _set_codes(s, "order_query.py", '["product:create"]'),
            problems_read_write,
        ),
        "⑥ B 端工具清空权限码 ⇒ 判据 1 红": (
            "tool:role_manage.py",
            lambda s: _set_codes(s, "role_manage.py", "[]"),
            problems_missing_codes,
        ),
        "⑦ 手写 c_end_reachable ⇒ 判据 7 红": (
            "tool:knowledge_search.py",
            lambda s: s.replace("c_end_reachable = True", "c_end_reachable = False", 1),
            problems_c_end_flag,
        ),
        "⑧ 目录两处不同步 ⇒ 判据 9 红": (
            "java:service/PermissionService.java",
            lambda s: s.replace('"knowledge:view"', '"knowledge:view-typo"', 1),
            problems_self_checks,
        ),
        "⑩ 写端点退回读码（order:update → order:list）⇒ 判据 2 红": (
            # issue #5246 第二批的回归形态：把拆出来的写码改回读码 ⇒ 工具码与端点码立刻不等
            # 必须挑**工具真调用的那个端点**：`order_manage` 只调 `AgentOrderController.PATCH /{id}`
            # （改 `OrderController` 的注解不会碰到任何工具的端点 ⇒ 判据 2 依然绿 = 红证空转）。
            "java:controller/agent/AgentOrderController.java",
            lambda s: s.replace('@RequirePermission("order:update")',
                                '@RequirePermission("order:list")', 1),
            problems_endpoint_parity,
        ),
        "⑪ 目录删掉新写码（customer:create）⇒ 两处目录不同步 ⇒ 判据 9 红": (
            "java:service/PermissionService.java",
            lambda s: s.replace('"customer:create"', '"customer:create-typo"', 1),
            problems_self_checks,
        ),
        "⑫ 岗位只拿到写码、没有该页读码（operator 去掉 customer:view）⇒ 判据 4 红": (
            "java:service/RegistrationService.java",
            lambda s: _drop_role_code(s, "operatorRole", "customer:view"),
            problems_leakage,
        ),
        "⑨ 有人删掉一个 @RequirePermission ⇒ 端点变成未登记的无码端点 ⇒ 判据 8 红": (
            # 为什么不用「改路径名」来造这个红：`UNANNOTATED_ENDPOINTS` 里有 `GET /api/admin/notifications*`
            # 这类前缀口径 ⇒ 改个后缀仍会被前缀命中（实测：那样注入**不会**变红）。
            # 用「删注解」既是真实回归形态，也必然落到前缀之外。
            "java:controller/StockBatchController.java",
            lambda s: s.replace(
                '    @RequirePermission("product:list")\n    @GetMapping("/batches")',
                '    @GetMapping("/batches")', 1),
            problems_registered_decisions,
        ),
    }


def _diverge_shared_node(text: str) -> str:
    """把 `MenuController` 的『生产看板』节点码改成**与其它菜单源不同**的值。

    选『生产看板』而不是『售后工单』：前者在三处菜单源里**同名**（才落在交集判据的射程内），
    后者在 `MenuController` 里叫「退换货」—— 名字都不同的节点本就不参与同构比对
    （这正是 `REGISTERED_RESIDUALS` 登记「四处菜单源不做全树同构」的含义）。
    """
    m = re.search(r'new MenuNode\("([^"]+)", "生产看板"\)', text)
    assert m, "注入锚点失配：`MenuController` 里找不到『生产看板』节点（同步本判据）"
    other = "order:list" if m.group(1) != "order:list" else "processing:manage"
    return text.replace(m.group(0), f'new MenuNode("{other}", "生产看板")', 1)


def test_every_judgement_can_go_red() -> None:
    """**每条**判据都要有能单独变红的注入（改坏必红、还原必绿）。"""
    # 判据表 ↔ 注入表**一一对应**（防「新增判据忘了补注入」⇒ 该判据永远不会红 = 空断言；
    # 反向也防：注入指向已删判据 ⇒ 红证无从归因）。放在循环**之前**：这是纯表校验，
    # 失败时只报表差集，不与"哪条判据红了"混在一起。
    _covered = {fn for _key, _mutate, fn in _injections().values()}
    _missing = sorted(label for label, fn in JUDGEMENTS.items() if fn not in _covered)
    _orphan = sorted(label for label, (key, _m, fn) in _injections().items() if fn not in JUDGEMENTS.values())
    assert not _missing and not _orphan, (
        "判据表与注入表必须**互相覆盖**：缺注入 ⇒ 该判据永远不会红（空断言）；"
        "注入指向已删判据 ⇒ 红证无从归因。"
        f"\n  仅有判据、无注入：{_missing}"
        f"\n  注入指向未登记的判据：{_orphan}"
        "\n  （一条判据允许多个注入 —— 但每条判据至少要有一个。）"
    )
    base_sources = _source_map()
    base_world = build_world(base_sources)
    green = {label: fn(base_world) for label, fn in JUDGEMENTS.items()}
    assert all(not v for v in green.values()), (
        "对照组：未注入时九条判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )
    for label, (key, mutate, judgement) in _injections().items():
        sources = dict(base_sources)
        sources[key] = mutate(sources[key])
        assert sources[key] != base_sources[key], f"{label}：注入没生效（锚点失配）—— 同步本判据"
        mutated = build_world(sources)
        assert judgement(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"