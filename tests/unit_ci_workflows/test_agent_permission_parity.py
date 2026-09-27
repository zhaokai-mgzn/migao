# case_ids: MC-012, HR-011
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
| **S3 菜单** | **三处**菜单源（`frontend/admin-web/src/config/menu.ts`、`MenuController.MENU_TREE`、`AuthService.buildMenusByPermissions`）—— 第四处（`UserController.generateMenus`）已于 issue #5236 整段删除，本守卫**双向**钉住它不得长回来 | 同一节点多源各写各的码（`售后工单` = `order:refund`，而客服岗位没有该码）；被删的第四处当时是**5 节点遗留树**（`product:manage` 粗码），没有任何守卫覆盖 |
| **S4 岗位** | 内置岗位默认权限（`RegistrationService.initializeDefaultRolesAndPermissions` 的 `attachDefaultPermissions` + `RoleService.getPermissionCodesForRole` 硬编码回退） | 岗位持 `processing:view` 却**没有**对应菜单节点 ⇒ 经 Agent 能查到页面里看不到的生产数据；issue #5291 起：岗位的**读**码与菜单节点码由判据 10 逐面钉住 |

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
   `PAGE_WRITE_CODES`），且**菜单源在交集上同构**（同一节点名不得两处不同码），
   并**双向**钉住第四处菜单源已删（issue #5236）：被删符号不得长回来，且它缺席时解析器不得静默恒绿。
4. **零权限泄露**：对每个内置岗位 R 与每个已编码工具 T —— `R 可调 T ⇒ R 看得见 T 的菜单节点`
   （用户逐字要求）。
5. **读写码不错配**：`read_only=True` 的工具不得只要求写码；写工具不得只要求读码。
   冲突项走**具名例外** `READ_WRITE_EXCEPTIONS`（每条带理由 + 建议修法，不允许沉默跳过），
   且该表**只许缩短**：条数**现取**、上限登记在 `READ_WRITE_EXCEPTIONS_CEILING`
   （issue #5291 起 = **0**：三个域的读码补齐后，一条例外都不该再挂着）。
6. **角色白名单卫生**：声明了权限码的工具不得再声明 `allowed_roles`（第二份不生效的假门禁）；
   `allowed_roles` 里不得出现 C 端角色（`customer`/`agent`）与幽灵角色（`tenant_admin`/`worker`，
   admin-api 里没有角色行/权限映射）—— 除非该工具**确实**是 C 端可达的（`c_end_reachable`）。
7. **`c_end_reachable` 不得手写**：必须逐字等于「该工具是否被**小布（C 端）**的 skill 绑定」
   （从 `app/agents/agents/xiaobu.py` 的 `skill_names` + `app/graph/skills/*.py` 的 `*_TOOLS` 推导）。
8. **未注解端点 = 显式登记的决定**（不是沉默）：每个生效码为 `None` 的端点必须命中
   `UNANNOTATED_ENDPOINTS` 的某条已登记口径；登记项不得陈旧。同理 `REGISTERED_RESIDUALS`
   逐条登记**已知但本单不修**的残留（带理由 + 去向）。
9. **解析器自检（防恒绿空跑）**：注解条数守恒 / 两处权限目录逐值相等 / 回退里的角色必须是种子岗位
   或已登记的历史角色 / 菜单码 ∈ 权限目录 / 各集合非空。⚠️ **岗位默认权限的「值级不变量」已迁到
   判据 14**（issue #5683）：早先这里持一张**手工维护的 5 个读码白名单**（`SEED_PARITY_READ_CODES`），
   而它漏掉的那 4 个码正是当时已经分叉的那 4 个 ⇒ 清单式判据本身就是缺陷形态，故删除、改为
   逐角色码**穷举**对照。
10. **三个域的读码「四面锚定」**（issue #5291 收口）：新增的读码在**目录 / 承载工具 / 菜单节点 /
    端点 / 岗位**五处逐面登记（`READ_CODE_ANCHORS`），任一面掉码都红 —— 含「把读码从菜单源删掉」
    与「只读工具退回管理码」两种回归形态。**例外表缩小≠判据失去判别力**：该条与判据 5 的台账
    一起，把「删条目」这件事变成**可红**的动作（见 `test_exception_ledger_only_shrinks`）。
11. **前端页面守卫（`ROUTE_PERMISSION_MAP`）前缀序 + 码锚定**（issue #5291 收口）：#5291 改了它
    **5 个前缀**，而它此前**全仓零判据**（PR #5516 自己登记为「未固化项」）⇒ 改错不会有东西变红。
    三段：① 更宽的前缀不得排在更具体的子路径之前（`find()` 先命中即短路 ⇒ `/production` 排到
    `/production/pool|remnants|saving-board` 之前会让三个管理码页面按读码判定）；② 码必须在
    权限目录里（否则该路由对所有角色恒 403）；③ 登记的前缀必须解析到 `config/menu.ts` 的节点、
    且码逐字相等，**未登记的前缀不登记即红**（台账 `ROUTE_MENU_ANCHORS` / `ROUTE_WITHOUT_MENU_NODE`）。
12. **菜单节点码 ≡ 该页第一屏读端点码**（issue #5675 新增；#5675 收口包补第 ⑤ 段）：侧边栏
    **可见性**只由节点码决定，而点进去成不成由端点码决定 ⇒ 两侧不同就是「可见面与可做面脱钩」
    （持节点码而不持端点码的人「菜单看得见、点进去 403」）。五段：① 每个带 `path` 的节点必须登记
    锚点；② 四跳**现取**（页面 → `useEffect` 驱动的调用 → `lib/api.ts` 的 URL → Java 生效码，
    任一跳解析不出来即红，**不静默跳过**）；③ 节点码必须等于该页第一屏**每个**非 None 端点码，
    否则具名登记进 `MENU_READ_PARITY_RESIDUALS`（**只许缩短**：不一致消失而条目还在也红）；
    ④ **零 403 受害者** —— 持节点码的岗位（种子 ∪ 回退）必须同时持该页第一屏的每个端点码
    （确有受害者 ⇒ 必须在该路径的 `victims_ack` 里逐条认领）；⑤ **多端点页的适用面前提**：
    ③ 的命题只在「第一屏**恰好一个**读端点码」的页面上适定 —— 第一屏并发 ≥2 个不同码的页面
    必须具名登记在 `MULTI_READ_ENDPOINT_PAGES` 且码集**逐值冻结**（未登记 / 与现取不符 /
    已不再多码 ⇒ 都红）。该表登记的是**结构事实**、**不是豁免**：多端点页的不一致照样要进 ③ 的
    残留台账、受害者照样要 ④ 的认领。
    锚点表 = `MENU_READ_ENDPOINT_ANCHORS`（`path` → 页面 + 逐页读出来的第一屏调用）。
13. **注释里的「计数 / 点名」声明 ≡ 代码现值**（#5675 收口包新增）：说明文字先写对、代码后来变了，
    而**没有任何东西会红** —— 本单实测两例（生产域读码目录的「8 个只读工具」已漂成 9；
    `StockBatchController` 类 javadoc 的「四个读面」实为 7 个 GET 端点）。
    机制 = 策展表 `COMMENT_CLAIMS`（逐条登记：源码键 + 逐字锚 + 复核口径），
    漂移 / 锚被改写 / 该处出现写死条数 ⇒ 红。⚠️ **边界（如实登记）**：只覆盖**已登记**的声明
    （全仓按「N 个……」扫会命中大量叙述句与**引用的历史文本** ⇒ 噪声淹掉判据），未登记的计数声明
    **不在射程**。与判据面「注释不是代码」（#5272）**方向相反、不冲突**：那条禁止把注释当声明**读**，
    本条的对象**就是注释文本**、真值在代码那一侧（读注释是为了**证伪**注释）。

## 明确的边界（**不要**把本守卫读成覆盖面更大）

- **C 端不在本守卫射程内**：C 端 JWT 没有权限码（`UserIdentity.permissions` 默认空），且
  `ServiceTokenFilter` 对 `X-User-Id ∈ {customer, agent}`（或无 `X-User-Id`）回退成 `service` 权威，
  `PermissionInterceptor.hasBypassRole` 直通 ⇒ **admin-api 侧对 C 端没有权限码校验**，
  C 端的隔离靠业务层的 `X-User-Id` 过滤（`/api/customer/**` 与 `/api/admin/agent/**` 各自过滤）。
  见 `backend/admin-api/src/main/java/com/migao/admin/security/ServiceTokenFilter.java` 与
  `.../security/PermissionInterceptor.java`。本守卫只判「商户员工」这条线。
- **菜单源不做全树同构**（那是 #5236 的产品裁定）：本守卫只比**交集**（同名节点不得两处不同码），
  并把未覆盖部分登记进 `REGISTERED_RESIDUALS`（见 `problems_registered_decisions`）。
- **第四处菜单源已删（issue #5236）**：`UserController.generateMenus` 整段删除 ⇒ `menu:user` 允许解析出
  **空表**；但放行**有条件**（剥注释后的代码面必须一个被删符号都没有），且符号一长回来判据 3 立刻红 ——
  「对象没了 ⇒ 把断言删掉」是本守卫明确拒绝的形态（见 `problems_menu_parity` ④ 与 `parse_menus`）。
- **该对象的三条判据仍有漏网形态（如实登记，不粉饰）**：一个**换名 + 换 DTO + 从未接回响应**的私有菜单表
  （纯死代码）符号面 / 解析面 / 结构面都看不见 —— 它与「任意死代码」静态不可区分，登记为残留
  （见 `REGISTERED_RESIDUALS` 的「第四处菜单源（已于 #5236 删除）」）。
- **解析口径（issue #5272）：注释不是代码** —— `parse_agent_skills` 用标准库 `tokenize` 按**真字符串
  token** 取 skill 名：注释里的带引号 skill 名、文档字符串里的举例都**不算绑定**。修前它按双引号
  字面量扫**原文** ⇒ `mibao.py` 解绑说明注释里的 `"settings"` 被读成「仍绑定」，得到**与事实相反**的
  假红（判据 1 报 2 条），当时只能靠「本注释不得给 skill 名加双引号」的规避说明绕过。
- **判据 12 的两条适用面限制（#5675 收口：如实登记，不粉饰 —— 不登记的限制就是未来的空断言）**：
  ① **只对「第一屏恰好一个读端点码」的页面适定**。第一屏**并发**多个码时，「节点码 ≡ 该页第一屏
     读端点码」这个命题本身**不适定**（不存在「那一个」码）⇒ 这类页面必须具名登记在
     `MULTI_READ_ENDPOINT_PAGES`（码集逐值冻结），而不是被硬凑一个码糊过去。附带一层：
     「`useEffect` 一定在**挂载时**跑」也没有机械证明（依赖形态多样）—— 停靠点是逐页读过的锚点 +
     「该调用由某个 effect 驱动、不是纯交互路径」。
  ② **受害者复算的岗位来源只有两处**（`RegistrationService` 种子 ∪ `RoleService` 硬编码回退，
     外加 V129 ②-b 谓词的前提自证）。`users.permissions` 的**员工级权限快照**（员工管理勾选即最终
     权限，按设计**与岗位脱钩**）与租户**自建岗位**的 `role_permissions` 都**读不到** ⇒ 一个在
     「岗位权限 / 员工管理」页里**手工只勾了读码、没勾管理码**的岗位，今天就是多码页面上的真受害者，
     而 ④ 看不见它。本条是**已知缺口**（`0 受害者` 的读数只在上述两处来源上成立），不是「已覆盖」。
- 本守卫**只读源码文本**（零依赖：只用标准库 + 共用的静态归属机具
  `backend/ai-agent-service/tests/tool_http_attribution.py`），不连库、不跑 LLM。
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
import sys
import tokenize
from dataclasses import dataclass, field, replace
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
#: 前端**页面守卫**（`ROUTE_PERMISSION_MAP`，issue #5291 改了 5 个前缀而此前无任何判据 —— 判据 11）。
ROUTE_LAYOUT = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)" / "layout.tsx"
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

# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323 第 1 条：Java 剥注释的唯一实现）
    java_code,
    java_literals,
)


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
        ("route:layout.tsx", ROUTE_LAYOUT),
    ):
        assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
        srcs[key] = path.read_text(encoding="utf8")
    for p in sorted(SKILLS_DIR.glob("*.py")):
        srcs[f"skill:{p.name}"] = p.read_text(encoding="utf8")
    for name in ("mibao", "xiaobu"):
        p = AGENTS_DIR / f"{name}.py"
        srcs[f"agent:{name}"] = p.read_text(encoding="utf8")
    # 判据 12（issue #5675）：页面源码 + 前端 api 客户端。**必须进源码表**（而不是现读磁盘）——
    # 否则「改页面第一屏调用」这类注入不会改变判据输入 ⇒ 判据永远不变红（空断言）。
    assert API_TS.is_file(), f"被判据引用的文件不存在：{API_TS}（路径漂移 ⇒ 红，不得静默跳过）"
    srcs["frontend:api.ts"] = API_TS.read_text(encoding="utf8")
    assert V129_SQL.is_file(), f"被判据引用的文件不存在：{V129_SQL}（路径漂移 ⇒ 红，不得静默跳过）"
    srcs["sql:V129"] = V129_SQL.read_text(encoding="utf8")
    for path, anchor in MENU_READ_ENDPOINT_ANCHORS.items():
        page = DASHBOARD_APP / anchor.page
        assert page.is_file(), (
            f"判据 12 的锚点指向的页面不存在：{page}（`MENU_READ_ENDPOINT_ANCHORS['{path}']` "
            "陈旧/路径漂移 ⇒ 红，不得静默跳过）"
        )
        srcs[f"page:{path}"] = page.read_text(encoding="utf8")
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
    """S1×S2：每个工具文件的 HTTP 调用点 → 目标端点的**生效**权限码（含**在飞端点**登记）。"""
    out: dict[str, list[tuple[str, str, str | None]]] = {}
    for call in ATTR.tool_calls():
        eps = index.lookup(call.method, call.endpoint)
        for ep in eps:
            out.setdefault(call.file, []).append((call.method, ep.path, ep.permission))
        if not eps:
            # 契约先行（issue #5314）：Agent 侧按冻结契约先编码、服务端由另一个包并行实现
            # ⇒ 端点暂时在 admin-api 里查不到。**必须**显式登记后才按契约码参与对账
            # （否则本工具会被判据 1 读成「纯本地工具」、判据 2 拿空集比 codes ⇒ 两条红，
            #   而它们与真漂移长得一模一样）；未登记 ⇒ 一律照旧红（判据 1/2 不静默放行）。
            pending = PENDING_ENDPOINTS.get(f"{call.file}|{call.method} {call.endpoint}")
            if pending:
                out.setdefault(call.file, []).append(
                    (call.method, call.endpoint, pending.get("code"))
                )
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


# ── 2.3 菜单来源（三处现役 + 第四处已删的登记） ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MenuTsNode:
    """`config/menu.ts` 的一个节点（判据 3 只用 `name`/`code`；判据 12 还要 `path`）。"""

    key: str
    name: str
    path: str | None
    code: str | None


def parse_menu_ts_nodes(text: str) -> tuple[MenuTsNode, ...]:
    """`frontend/admin-web/src/config/menu.ts` 的**节点表** —— 本文件里 menu.ts 的**唯一**解析。

    🔴 issue #5675：判据 12 要按 `path` 锚「该页第一屏读端点」⇒ 把旧的 `_iter_menu_ts`
    （只产出 `name → code`）就地扩成结构化节点表，`_iter_menu_ts` 改为它的**投影**。
    **不另起第二个 menu.ts 解析器**（同一份文件被多处各解析一遍是 issue #3570 的教训）。

    切分口径与旧版**逐字一致**（以 `key:` 为分隔，chunk 内取 `name` / `path` / `permissionCode`）
    ⇒ 组头（无 `path`）照旧解析出来、`parse_menus` 的读数一字不变。
    """
    keys = list(re.finditer(r"key:\s*'([^']+)'", text))
    out: list[MenuTsNode] = []
    for i, m in enumerate(keys):
        end = keys[i + 1].start() if i + 1 < len(keys) else len(text)
        chunk = text[m.end():end]
        nm = re.search(r"name:\s*'([^']+)'", chunk)
        if not nm:
            continue
        pm = re.search(r"path:\s*'([^']+)'", chunk)
        cm = re.search(r"permissionCode:\s*'([^']+)'", chunk)
        out.append(
            MenuTsNode(
                key=m.group(1),
                name=nm.group(1),
                path=pm.group(1) if pm else None,
                code=cm.group(1) if cm else None,
            )
        )
    return tuple(out)


def _iter_menu_ts(text: str):
    """`frontend/admin-web/src/config/menu.ts`：`key` → 其后的 `name` / `permissionCode`。

    （判据 3 的投影 —— 与判据 12 共用 `parse_menu_ts_nodes`，**不是**第二份解析。）
    """
    for node in parse_menu_ts_nodes(text):
        yield node.name, node.code


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
    """`UserController.generateMenus`（**第四处**，5 节点遗留树）：`.key(...)` + `.name(...)`。

    ⚠️ 该对象已于 issue #5236 **整段删除** ⇒ 本迭代器在**方法不存在**时返回空（而非抛错），
    但空表**不是**无条件放行：前提由 `fourth_menu_source_symbols` 判（代码面确实无被删符号），
    见 `parse_menus`。对象回来时它必须仍能解析出节点 —— 否则「空表」会把回归读成缺席。
    """
    pattern = re.compile(
        r'permissions\.contains\("([^"]+)"\)\)\s*\{\s*\n\s*menus\.add\([^;]*?\.key\("([^"]+)"\)\s*\n\s*\.name\("([^"]+)"\)',
        re.S,
    )
    for m in pattern.finditer(text):
        yield m.group(3), m.group(1)


#: 第四处菜单源的**被删符号**（issue #5236 整段删除后，只允许出现在**注释**里 ——
#: 删除落码时写入的决策记录 javadoc 必然点名它们）。口径与
#: `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的
#: 「不得再长出第四处独立菜单表」一致（`\bgenerateMenus\b` + `MenuItem`）：那边判它不得长回来，
#: 这边还要判「它不在时解析器不许瞎」。
_FOURTH_MENU_SOURCE_RE = re.compile(r"\bgenerateMenus\b|MenuItem")


def fourth_menu_source_symbols(text: str) -> list[str]:
    """`UserController` **代码面**（剥注释后）残留的被删符号；空表 = 第四处菜单源确实不在。

    🔴 必须剥注释（`ATTR._strip_java_comments`）：扫原文会把判据**永久喂红** —— migao-dev-flow
    §17.3「判据被自己的文案喂红」，同族实证见
    `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的 `_strip_java_comments`。
    """
    return sorted(set(_FOURTH_MENU_SOURCE_RE.findall(ATTR._strip_java_comments(text))))


MENU_SOURCES = {
    "frontend": ("menu:frontend", _iter_menu_ts),
    "controller": ("menu:controller", _iter_menu_controller),
    "auth": ("menu:auth", _iter_menu_auth),
    "user": ("menu:user", _iter_menu_user),
}


def parse_menus(sources: dict[str, str]) -> dict[str, dict[str, str | None]]:
    """S3：菜单源的 `节点名 → 权限码`（无码节点值为 None）。

    ⚠️ 第四处（`menu:user`）自 issue #5236 起**已删除** ⇒ 允许解析出**空表**；另三源照旧
    fail-closed（解析出 0 个节点 = 判据空跑 ⇒ 红）。空表放行**只有一个前提**：剥注释后的代码面
    一个被删符号都没有（`fourth_menu_source_symbols`）。符号在、节点却解析出 0 个 ⇒ 照旧抛错
    —— 这就是「对象缺席不得让解析器静默恒绿」的机械形态（换名长回会被它抓住）。
    """
    out: dict[str, dict[str, str | None]] = {}
    for label, (key, it) in MENU_SOURCES.items():
        text = sources[key]
        nodes = dict(it(text))
        if not nodes:
            absent = label == "user" and not fourth_menu_source_symbols(text)
            assert absent, (
                f"菜单源 `{label}`（{key}）解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
                + (
                    f"：第四处菜单源虽已按 issue #5236 删除，但代码面仍有被删符号 "
                    f"{fourth_menu_source_symbols(text)} ⇒ 「对象在、解析器却没解析出来」不许静默"
                    if label == "user"
                    else ""
                )
            )
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


def _java_string_arg(body: str, callee: str) -> str:
    """Java 片段里 `callee("字面量")` 的**字面量值**（按**词法**定位；取不到 ⇒ `""`）。

    `#5323` 第 1 条：旧口径 `re.search(r'code\\("([^"]+)"\\)', body)` 在**原文**上搜 ⇒
    注释里写一行 `// .code("ghost")` 就被读成该岗位的角色码（首命中即取）。现口径 = 剥注释
    （`java_code`）+ 词法取字面量（`java_literals`）并按**前缀**归属到 `callee`。
    """
    for pos, value in java_literals(body):
        if body[:pos].rstrip().endswith(callee):
            return value
    return ""


def parse_role_defaults(reg_text: str) -> dict[str, frozenset[str]]:
    """S4：内置岗位默认权限（`Role.builder()...code("x")` 变量 + `attachDefaultPermissions` 列表）。

    `#5323` 第 1 条（required 判据）：三处取值**一律先剥 Java 注释**（共享实现
    `_source_parsing.java_code`，**引号感知** ⇒ 字符串里的 `//`（`"http://x"`）不会被截断），
    再按**词法**取字面量（`java_literals`）—— 注释里写一个 `code("x")` 或 `"x"` 不再被读成声明。
    旧口径在**原文**上跑 `re.findall(r'"([^"]+)"', …)`：注释里的码被当成「真的挂了这个码」
    （假绿：漏检「该挂没挂」；兼假红：判禁用码 / 多余码时）。
    """
    code = java_code(reg_text)
    var_to_code: dict[str, str] = {}
    for var, body in dict(
        re.findall(r'Role\s+(\w+)\s*=\s*Role\.builder\(\)(.*?)\.build\(\);', code, re.S)
    ).items():
        role_code = _java_string_arg(body, "code(")
        if role_code:
            var_to_code[var] = role_code
    out: dict[str, frozenset[str]] = {}
    for m in re.finditer(
        r"attachDefaultPermissions\(tenantId,\s*(\w+),\s*(List\.of\(([^)]*)\)|permissionByCode\.keySet\(\))",
        code,
        re.S,
    ):
        var, arg, codes = m.group(1), m.group(2), m.group(3)
        role = var_to_code.get(var)
        assert role, f"`attachDefaultPermissions` 的变量 `{var}` 找不到对应角色码（解析失配 ⇒ 红）"
        if arg.startswith("permissionByCode"):
            out[role] = frozenset({"*"})       # admin 恒为全部权限
        else:
            out[role] = frozenset(value for _pos, value in java_literals(codes or ""))
    assert len(out) >= 5, f"内置岗位解析出 {len(out)} 个 ⇒ 判据会空跑（fail-closed）：{sorted(out)}"
    return out


def parse_role_fallback(role_text: str) -> dict[str, frozenset[str]]:
    """S4（回退口径）：`RoleService.getPermissionCodesForRole` 的硬编码 `case "x" -> List.of(...)`。

    口径同 `parse_role_defaults`（`#5323` 第 1 条）：先剥注释再按**词法**取字面量 ——
    注释里的 `case "x" -> List.of("y");` 不算回退分支。方法找不到 ⇒ 红（fail-closed；
    旧版这里 `find()` 返回 -1 时静默切片，会让回退表**空表恒绿**）。
    """
    code = java_code(role_text)
    start = code.find("getPermissionCodesForRole(String roleCode)")
    assert start != -1, "`RoleService.getPermissionCodesForRole` 找不到（解析失配 ⇒ 红）"
    body = code[start:]
    return {
        m.group(1): frozenset(value for _pos, value in java_literals(m.group(2)))
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


#: tokenize 里「不是代码」的 token：注释是独立的 `COMMENT`；文档字符串只是**别处**的 `STRING`。
_PY_TRIVIA = frozenset(
    {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER, tokenize.COMMENT}
)


def _py_tokens(text: str, where: str) -> list[tokenize.TokenInfo]:
    """Python 源码的 token 流（**不可 tokenize ⇒ 红**：fail-closed，不许静默恒绿）。"""
    try:
        return list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise AssertionError(f"{where} 无法 tokenize（{exc}）⇒ 解析失配 ⇒ 红（同步本判据）") from exc


def _py_string_token(tok: tokenize.TokenInfo, where: str) -> str:
    """一个 `STRING` token 的字面量值（f-string / bytes 等取不出 ⇒ 红，不静默丢）。"""
    try:
        value = ast.literal_eval(tok.string)
    except (ValueError, SyntaxError) as exc:
        raise AssertionError(f"{where} 里 `{tok.string}` 不是字符串字面量（{exc}）⇒ 解析失配 ⇒ 红") from exc
    assert isinstance(value, str), f"{where} 里 `{tok.string}` 解析出 {type(value).__name__} ⇒ 解析失配 ⇒ 红"
    return value


def _py_assigned_strings(text: str, key: str, where: str) -> list[str]:
    """Python 源码里 `key="…"` / `key=[…]` 的**真字符串字面量**（注释与文档字符串都不算）。

    issue #5272 的病灶 → 修法：旧口径在**原文**上跑 `m.group(1)` + `re.findall(r'"([^"]+)"', …)`
    ⇒ `skill_names` 附近**注释**里带双引号的 skill 名被读成「仍绑定」（与事实相反的假红：实测把
    `settings` 的工具悄悄拉进 B 端工具集 ⇒ 判据 1 报 2 条；`mibao.py` 作者只能写注释规避）。
    现口径 = 标准库 `tokenize` 按 **token** 取值：注释是独立的 `COMMENT`、文档字符串是**别处的**
    `STRING`，两者都不落在 `key` 的值里 ⇒ 「注释不是代码」由词法保证，且 `#` 出现在字符串 /
    三引号内部也不会被误切。
    ⚠️ **不要**退回 `re.sub(r"#.*", "", text)` 这类朴素剥法：字符串里的 `#` 会被一起切掉 ⇒ 新的错判。
    """
    toks = [t for t in _py_tokens(text, where) if t.type not in _PY_TRIVIA]
    for i, tok in enumerate(toks):
        if tok.type != tokenize.NAME or tok.string != key:
            continue
        tail = toks[i + 1:]
        if not tail or tail[0].string != "=":
            continue
        value = tail[1:]
        if not value:
            continue
        if value[0].type == tokenize.STRING:
            return [_py_string_token(value[0], where)]
        if value[0].string != "[":
            continue
        depth, out = 0, []
        for item in value:
            if item.type == tokenize.OP and item.string in "([{":
                depth += 1
            elif item.type == tokenize.OP and item.string in ")]}":
                depth -= 1
                if depth <= 0:
                    return out
            elif depth == 1 and item.type == tokenize.STRING:
                out.append(_py_string_token(item, where))
        return out                       # 值未闭合 ⇒ 交出已收集到的，由调用方 fail-closed
    return []


def parse_agent_skills(sources: dict[str, str], agent: str) -> tuple[frozenset[str], str | None]:
    """某人格的 `skill_names` + `fallback_skill`（**读真字符串 token**；注释/文档字符串不算绑定）。"""
    where = f"agent:{agent}"
    text = sources[where]
    names = _py_assigned_strings(text, "skill_names", where)
    assert names, f"`{agent}` 的 `skill_names` 解析失配 ⇒ 红"
    fb = _py_assigned_strings(text, "fallback_skill", where)
    return frozenset(names), (fb[0] if fb else None)


# ══════════════════════════════════════════════════════════════════════════════
# 三、核定表（**判据的唯一来源**；新增/改动必须显式落在这里 —— diff 里看得见）
# ══════════════════════════════════════════════════════════════════════════════

#: 工具 → 其对应菜单节点（**节点名逐字取自现役三处菜单源**）。
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
    # issue #5314：批量改价 / 批量上下架（`product:create` = 商品列表页的写码）
    "product_batch_update": "商品列表",
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
    # ── B 端只读模块覆盖（issue #5247）：新增只读工具 → 逐个登记「它的码属于哪个菜单节点」──
    "stock_ledger_query": "商品列表",            # product:list
    "inbound_order_query": "入库单",             # inbound:view
    "operation_catalog_query": "工艺配置",       # 端点方法级 processing:manage（#5247 新增，收窄）
    "briefing_query": "每日简报",                # dashboard:view
    "craft_calc_config_query": "工艺配置",       # processing:manage（生产域无专属读码）
    "processing_order_set_query": "生产看板",    # processing:manage（套件读面 = 加工单读面同码，#5246 收尾）
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
    # issue #5291：生产域新增**读**码 `production:view` ⇒ 本键由 `processing:manage` 改名而来
    #（节点的读码变了，页内写码不变）：该页发起的写动作仍用 `processing:manage`（加工项 CRUD）
    # 与 `processing:update`（生成/改加工单）。
    "production:view": frozenset({"processing:manage", "processing:update"}),
    "employee:list": frozenset({"employee:create"}),
    "knowledge:view": frozenset({"knowledge:manage"}),
    "inbound:view": frozenset({"inbound:create"}),
}

#: 页内**读**码（判据 3/4 的第三个落点，issue #5291）：某个**只读子面**没有独立侧边栏节点
#: （它挂在某页之内，例如「商品分类」没有自己的菜单项、其管理入口在商品列表页里），
#: 但仍需要一个可授予的**读**码 —— 于是登记为「该页读码 → 页内读码」。
#: 与 `PAGE_WRITE_CODES` 对称：两者合起来 = 「这一页**名下**的全部码」。
#: 判据：该码必须有人用（判据 3 ②）、持它的岗位必须看得见**这一页**（判据 4）、
#: 且它必须在 `READ_CODE_ANCHORS` 里登记（判据 10）。
PAGE_READ_CODES: dict[str, frozenset[str]] = {
    # 商品分类读码：`CategoryController.getCategoryTree` + 只读工具 `category_manage`
    # （分类管理没有独立侧边栏入口 ⇒ 归属「商品列表」页）。
    "product:list": frozenset({"product:category:view"}),
}

#: 纯本地工具（**无任何 admin-api HTTP 调用点** ⇒ 没有可对账的端点码）。
#: 与「实际解析出的无调用点工具集」必须**双向相等**（陈旧条目也红）。
LOCAL_ONLY_TOOLS: dict[str, str] = {
    # issue #5247：`validate_input` **退出本表** —— 它是写操作的前置校验，B 端只读化后
    # 已从全部 8 个 skill 解绑（绑着它就会把「skill 校验自己执行不了的写工具」重新引入，
    # 正是 A5 账本要治的形态）⇒ 它不再是「B 端可达且无调用点」的工具（C 端仍绑，见
    # `tests/test_skill_tool_reachability.py` 的 A5 域闸门）。
    "interact": "纯本地交互卡构造（confirm/choice/form 的载荷生成）：无 admin-api 调用点",
    # issue #5368 包 2（Agent 深通道）：`image_recognize` 是**纯本地**能力 ——
    # 调一次 vision 模型 + 跑 `app/vision/**` 的纯函数（识别 / 消歧 / 解读），
    # 产出「同页填充计划」交给 `chat.py` 的瞬时 SSE 事件；**没有任何 admin-api HTTP 调用点**
    # ⇒ 没有可对账的端点码（与 `interact` 同一豁免口径）。可达性只由 B 端两个 skill 的
    # 工具集决定（`product` / `order`；小布不绑 ⇒ C 端零改动）。
    "image_recognize": "纯本地图片识别 + 同页填充计划构造（只调 vision 模型与 app/vision 纯函数）：无 admin-api 调用点",
}

#: 读码后缀（判据 5 的机械口径）：`模块:动作` 的动作 ∈ 这些 ⇒ 读码，其余 ⇒ 写/管理码。
READ_CODE_ACTIONS = frozenset({"view", "list", "detail", "session"})

#: 读写码冲突的**具名例外**（判据 5）：每条必须带理由 + 建议修法；条目陈旧（不再冲突）也红。
#:
#: 🔴 issue #5291（用户 2026-09-25 裁定「方案①：新增读码」）：本表**已清空** —— 原 10 条**同源**
#: （分类 / 权限目录 / 生产域三个域**没有读码** ⇒ 只读工具只能持管理码）已由「三个域各新增一个读码」
#: 根治（`product:category:view` / `system:view` / `production:view`，四处同批：三处菜单源 + 岗位矩阵，
#: 读端点与只读工具同批迁移）。逐条处置见 issue #5291 与本次 PR body。
#:
#: **只许缩短的靶子** = 下面那个上限（条数**现取** ⇒ 表一变长就红，抬高上限必须在 diff 里显式改这一行）。
READ_WRITE_EXCEPTIONS: dict[str, str] = {}

#: `READ_WRITE_EXCEPTIONS` 的**条数上限**（判据 5 的台账面）：issue #5291 清空后为 **0**。
#: 设计口径（migao-dev-flow §23 G1「豁免台账只许缩短、条数现取、命中数涨跌都红」）：
#: 例外表是**燃尽靶子**而不是垃圾场 —— 新增一条必须在同一 diff 里抬高本上限并写明理由（评审可见）。
READ_WRITE_EXCEPTIONS_CEILING = 0

#: **在飞端点**的显式登记（判据 1/2 的补集；issue #5314）。
#:
#: 病根：`endpoints_by_tool` 只收录**能在 admin-api 源码里查到**的端点。契约先行
#: （Agent 侧按冻结契约先编码、服务端由另一个包并行实现）时工具会暂时「一个端点都查不到」
#: ⇒ 判据 1 把它读成**纯本地工具**（`LOCAL_ONLY_TOOLS` 双向核对 ⇒ 红）、判据 2 拿空集比
#: `required_permissions`（⇒ 红）。这两条红**不是漂移**，是"服务端还没合入"——
#: 但它与真漂移长得一模一样，故必须**显式登记**（未登记 ⇒ 一律照旧红，不静默放行）。
#:
#: 纪律（与 `backend/ai-agent-service/tests/test_tool_payload_backend_contract.py` 的
#: `ENDPOINT_ALLOWLIST` 同族，逐条带 reason + owner + issue）：
#: **端点一旦在 admin-api 里落地 ⇒ 本条目变陈旧 ⇒ 判据 8 红**，逼承接包删掉它
#: （白名单即工作清单，不允许变成垃圾场）。
PENDING_ENDPOINTS: dict[str, dict[str, str]] = {
    # 当前为空：issue #5314 的两侧都已在 main 上（服务端端点由 #5339 合入
    # `AgentBatchController`，类级 `@RequirePermission("product:create")`）⇒ 三条在飞登记
    # 按本表纪律**已删除**（陈旧条目会被判据 8 判红），判据回到「拿真实端点的生效码对账」。
    # 留档（#5314，2026-09-24）：曾临时登记 `POST /api/admin/agent/batches` 与
    # `.../{}/execute`、`.../{}/revert` 三条（契约先行期，Agent 侧先编码、服务端未合入）。
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
    "POST /api/admin/image-recognition": "图片识别（issue #5321 包 1）—— ⚠️ **本条不是「有意放行」**："
                                        "权限**有**，只是取不到静态注解上。语义 = 一个入口覆盖两个模块、"
                                        "两种写码（建品页 `product:create` / 建单页 `order:create`），"
                                        "`@RequirePermission` 只能声明**端点级静态码**，表达不了这种分叉 "
                                        "⇒ 控制器内用 `PermissionInterceptor.requirePermission(...)` "
                                        "**命令式断言**动态校验（issue #4148 的既有机制，与 AOP 拦截走**同一份**判定："
                                        "未认证拒绝 / 旁路角色 / `*` 通配 / 细粒度查询）；**未知 target ⇒ 400 且不发起远端调用**"
                                        "（fail-closed，没有可用码就不放行）。"
                                        "⚠️ **本守卫看不到动态调用**（它只读注解）⇒ 登记项与被登记端点之间的"
                                        "「动态校验真的存在」由 `backend/admin-api/src/test/java/com/migao/admin/"
                                        "controller/ImageRecognitionControllerTest.java` 机械兜住："
                                        "逐 target 断言 `requirePermission(\"product:create\")` / "
                                        "`requirePermission(\"order:create\")`，并断言未知 target 时"
                                        "`never()` 调客户端与权限判定。同族形态见 `AgentOrderController` "
                                        "的退款 action 复检（类级读码 + 命令式 `order:refund`）。",
    "GET /api/customer/*": "C 端人工会话面：不走 `/api/admin/**` 门禁，隔离靠业务层 `X-User-Id` 过滤",
    "POST /api/customer/*": "同上",
    "GET /api/worker/*": "工人端身份（#4716 设计 C11 预留）：`ADMIN_API_REJECTED_ROLES` 已把 worker 挡在 `/api/admin/**` 之外",
    "POST /api/worker/*": "同上",
    "GET /s/{}": "短链跳转（`permitAll`，无租户数据）",
    "GET /i/{}": "入库标签公开入口（issue #5052 P2，`permitAll`）：标签贴在布卷 / 塑料袋上，"
                 "纸上的码对**任何持码人等价** ⇒ 服务端 302 到落地页；**只回跳转、不泄露业务字段**"
                 "（响应体为空，`Location` 里只有落地页 + 短码 + 租户 id）。它与 `/s/{}` 是"
                 "**两个码空间**（入库标签 vs 报工短链），混用会把「扫标签」变成「进报工页」"
                 "⇒ 互斥判据见 tests/unit_ci_workflows/test_public_code_spaces_are_disjoint.py",
}

#: `RoleService.getPermissionCodesForRole` 里**有意保留**的历史角色（admin-api 无角色行/无种子）：
#: 它们是存量库里的岗位码，回退表保住兼容；新增任何角色都必须先落进种子矩阵，否则判据 9 红。
#: ⚠️ **`SEED_PARITY_READ_CODES` 已删**（issue #5683）：它是一张**手工维护的 5 个码**的白名单，
#: 而它漏掉的那 4 个码（`processing:view` / `processing:update` / `inbound:view` / `inbound:create`）
#: **正是当时已经分叉**的那 4 个 —— 清单式判据本身就是这个缺陷的形态（人会忘记往清单里加码）。
#: 值级不变量改由**判据 14**（`problems_role_default_parity`）承担：逐角色码**穷举**对照两处，
#: 差异必须具名登记在只许缩短的 `ROLE_FALLBACK_DIVERGENCES` 里 —— 严格强于那张清单，且无需人维护。

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
    # 「生产域缺读码」**已于 issue #5291 消项**（用户 2026-09-25 裁定「方案①：新增读码」）：
    # 生产域读码 `production:view` 连同分类 / 权限目录两个读码一起落地（三处菜单源 + 岗位矩阵 +
    # 读端点 + 8 个只读工具同批迁移）⇒ 该条不再是残留，按「登记表只许缩短」从本表**删除**。
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
    "第四处菜单源（已于 #5236 删除）": {
        "what": "`UserController.generateMenus` 曾是**第四处**菜单源（5 节点遗留树：经营看板/商品管理/加工项管理/"
                "知识库管理/系统设置，粗码 `product:manage`），issue #5236 已**整段删除**（含唯一调用点与 "
                "`.menus(menus)` 构建行；端点 `GET /api/admin/user/info` 本体与 `UserInfoResponse.menus` 字段 **未动**）",
        "why": "删除取证（实测）：该表只有本类一个调用点；端点前端零调用（`frontend/admin-web/src/lib/api.ts` "
               "只调 `/api/auth/me`）；`docs/wiki/CONTRACT-LEDGER.md` 无本端点条目；测试只断言该端点状态码、"
               "0 处断言其 `menus` 内容。⇒ 「全树同构」的残留问题因此收窄为**三源之间**",
        "where": "本守卫不再把它当「登记残留」而是**双向钉住不得长回来**（判据 3 ④：符号面 + 解析面 + "
                 "结构面 `.menus(...)`）；全树同构仍不做（产品裁定）。"
                 "**残留（如实登记，不粉饰）**：三条判据看不见「换名 + 换 DTO + 且从未接回响应」的私有菜单表"
                 "（= 与任意死代码静态不可区分）—— 与 `test_menu_three_sources_are_isomorphic.py` 同口径，"
                 "登记为残留而不是假装覆盖。去向：#5236",
    },
    "MenuController 省略的节点": {
        "what": "**只剩「通知中心」**：它不在 `MenuController.MENU_TREE`（该树每个节点都必须有权限码，"
                "而通知中心是全员可见项）—— 但它在 `AuthService` 的下发面里。"
                "issue #5271 起服务端两处已镜像侧边栏全部 7 组（含 在线接待/知识库/岗位权限/"
                "企业基础信息/每日简报），本条残留原先列的其它节点**均已消除**",
        "why": "通知中心无权限码 ⇒ 结构上不进权限树（不是漏改）；三处菜单源（前端 / `MenuController` / "
               "`AuthService`）现已是**全树同构**，判据见 `test_menu_three_sources_are_isomorphic.py`"
               "（#5271 升级）；第四处源已于 issue #5236 **整段删除**（本单，不再是待统一的残留）",
        "where": "交集覆盖度由 `problems_menu_parity` 的 `CROSS_CHECKED_FLOOR` 自检；去向：#5236",
    },
    "权限码零消费": {
        "what": "`order:detail` / `product:manage` 在目录里且被岗位授予/菜单使用，但没有任何 "
                "`@RequirePermission` 消费它们（`product:manage` 原只出现在第四处菜单源，"
                "该源已于 issue #5236 删除 ⇒ 它现在只剩目录 / 岗位面）",
        "why": "删码/改码会动岗位矩阵（产品裁定）；本单不动",
        "where": "去向：#5236",
    },
    "行为评测用例未补": {
        "what": "本单未新增/修改 `.github/cases/**` 的行为用例（如「客服经米宝查售后不再 403」的正向对照）",
        "why": "B 端 skill 工具绑定与提示词属 #5247（在其上 rebase），行为面用例应与绑定同批落地",
        "where": "去向：#5247（input 已写进 PR 说明）",
    },
}

#: 菜单源**交集**的覆盖度下限（自检：低于它说明解析面缩小了 ⇒ 红）。
#: 实测值见 `problems_menu_parity` 的报错文案（**不写死读数**：它会随菜单重排漂移）；不写死到刚好相等，
#: 留余量 —— 但**只许上调**：改小它等于把「不检查」伪装成「检查过」。
#: （#5271 全树重排后实测 = 19：`frontend ∩ controller` 19 / `frontend ∩ auth` 13 / `menu:user` 已空）
CROSS_CHECKED_FLOOR = 8


@dataclass(frozen=True)
class World:
    """判据的全部输入（注入式红证 = 用改过的文本重建它）。"""

    tools: tuple[ToolDecl, ...]
    endpoints: dict[str, tuple[tuple[str, str, str | None], ...]]
    all_eps: dict[tuple[str, str], tuple]
    menus: dict[str, dict[str, str | None]]
    route_guard: tuple[tuple[str, str], ...]
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
        route_guard=parse_route_guard(sources["route:layout.tsx"]),
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
# 四、判据（纯函数：输入 `World`，输出问题清单 —— 空 = 绿）
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
    """判据 3：工具码 ≡ 菜单节点码（写工具可持页内写码/跨页读码）+ 三处菜单源在交集上同构
    + 第四处菜单源（issue #5236 已删）不得长回来（两种口径都钉）。"""
    out: list[str] = []
    by_name = _by_name(w)
    front = w.menus["frontend"]
    node_codes = {c for c in front.values() if c}
    write_codes = {c for fam in PAGE_WRITE_CODES.values() for c in fam}
    read_codes = {c for fam in PAGE_READ_CODES.values() for c in fam}
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
            if code not in node_codes and code not in write_codes and code not in read_codes:
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
        anchor = (
            {node_code}
            | set(PAGE_WRITE_CODES.get(node_code, frozenset()))
            | set(PAGE_READ_CODES.get(node_code, frozenset()))
        )
        if not (codes & anchor):
            out.append(
                f"{name}：required_permissions={sorted(codes)} 与节点『{node_name}』"
                f"（本页码域 {sorted(anchor)}）无任何交集 ⇒ 工具做的事与它登记的页面不是同一件事"
            )
    # ③ 现役三处菜单源：**交集**上同名节点不得两处不同码
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
            f"菜单源的**交集**只剩 {len(checked)} 个节点（下限 {CROSS_CHECKED_FLOOR}）"
            f"：{sorted(checked)} —— 解析面缩小 = 「没检查」被读成「检查过」"
        )
    # ④ 第四处菜单源（issue #5236 已整段删除）：**双向**钉住 —— 不是「对象没了就把断言删掉」。
    #    正向（符号面）：`UserController` 的**代码面**不得再出现被删符号（原名长回、换名构造
    #    `MenuItem` 都拦得住）—— 判据改挂在「不得再长出第四处」这件事上，与
    #    `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的
    #    `test_no_fourth_menu_source` 同口径（只读剥注释后的代码，不吃自己的说明文字）；
    #    反向（解析面）：符号不在却解析出节点 ⇒ 解析器认错了对象（空表只对「真的不在」成立）。
    #    ⚠️ 两条**缺一不可**：只留正向 ⇒ 换名长回时解析器空表、判据以为「没长回来」照样绿；
    #    只留反向 ⇒ 对象整段消失就没人管了（判据随对象一起被删除 = 丢覆盖）。
    user_text = w.sources.get("menu:user", "")
    user_symbols = fourth_menu_source_symbols(user_text)
    if user_symbols:
        out.append(
            f"第四处菜单源又长回来了：`UserController` 的代码面出现 {user_symbols} —— issue #5236 "
            "已把它整段删除（它与另三源都不一致、且实测无任何消费方）；新增菜单必须走三源之一"
            "（`frontend/admin-web/src/config/menu.ts` / `MenuController.MENU_TREE` / "
            "`AuthService.buildMenusByPermissions`），否则它又是判据射程之外的第 N 处"
        )
    elif w.menus.get("user"):
        out.append(
            f"`UserController` 代码面已无被删符号，却仍解析出 {len(w.menus['user'])} 个菜单节点 —— "
            "解析器认错了对象（空表只对「第四处确实不在」成立 ⇒ 同步本判据）"
        )
    elif ".menus(" in ATTR._strip_java_comments(user_text):  # noqa: SLF001
        out.append(
            "`UserController` 的响应构建又挂上了 `.menus(...)`（issue #5236 已把 "
            "`GET /api/admin/user/info` 收窄为**不下发菜单**）—— 这条判据**不看名字**："
            "无论那份菜单表叫什么、用什么 DTO，只要它重新接到响应上，就又是三源之外的第 N 处"
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
    for page_code, reads in PAGE_READ_CODES.items():
        pages = owners.get(page_code, set())
        for code in reads:
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
                    w.menus["frontend"].get(p) or "", set()) or code in PAGE_READ_CODES.get(
                    w.menus["frontend"].get(p) or "", set()) for p in pages):
                out.append(f"权限泄露：码 `{code}` 的归属节点解析失败（{sorted(pages)}）—— 同步本判据")
                continue
            visible = [
                p for p in pages
                if code in PAGE_WRITE_CODES.get(w.menus["frontend"].get(p) or "", set())
                or code in PAGE_READ_CODES.get(w.menus["frontend"].get(p) or "", set())
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
    # 台账面（issue #5291）：例外表**只许缩短** —— 条数**现取**，超过登记上限即红。
    # 形态：把某个只读工具的码改回管理码、并把它登记进例外表（正是例外表存在的理由）
    # ⇒ 「具名例外」的老检查会放行，**只有**这一条能拦（红证见 `test_exception_ledger_only_shrinks`）。
    if len(READ_WRITE_EXCEPTIONS) > READ_WRITE_EXCEPTIONS_CEILING:
        out.append(
            f"读写例外表**又长回来了**：{len(READ_WRITE_EXCEPTIONS)} 条 > 上限 "
            f"{READ_WRITE_EXCEPTIONS_CEILING}（issue #5291 已为分类 / 权限目录 / 生产域补齐读码 "
            "`product:category:view` / `system:view` / `production:view` ⇒ 只读工具不得再靠具名例外持"
            "管理码）。登记表是**燃尽靶子**：确需新增，必须在同一 diff 里显式抬高 "
            "`READ_WRITE_EXCEPTIONS_CEILING` 并写明理由"
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
    # 在飞端点登记（#5314）：条目必须**真的还在飞** —— 端点已在 admin-api 落地 ⇒ 删除它，
    # 让判据 1/2 回到「拿真实端点的生效码对账」（否则登记会静默盖住真实端点的码漂移）。
    for key, entry in sorted(PENDING_ENDPOINTS.items()):
        for field_name in ("code", "reason", "owner", "issue"):
            if not str(entry.get(field_name, "")).strip():
                out.append(f"在飞端点登记 `{key}` 缺 `{field_name}`（必须写清契约码与归属）")
        call_file, _, call_key = key.partition("|")
        verb, _, path = call_key.partition(" ")
        if (verb, path) in w.all_eps:
            out.append(
                f"在飞端点登记 `{key}` 的端点**已在 admin-api 落地**"
                f"（{call_file} 的 {verb} {path} 现在查得到）⇒ 陈旧登记必须删除，"
                "改由真实端点的生效码对账"
            )
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
    # ③ 回退里的角色必须是种子岗位或已登记的历史角色。
    #    🔴 **值级不变量不在这里**（issue #5683）：岗位默认权限「两处逐值相等」由判据 14
    #    （`problems_role_default_parity`）**穷举**承担 —— 本段此前各持一份 5 码白名单，
    #    而它漏掉的 4 个码正是当时已经分叉的那 4 个；两套真值源必然分叉，故只留一处。
    for role in sorted(w.role_fallback):
        if role in w.roles:
            continue
        if role not in LEGACY_ROLES_IN_FALLBACK:
            out.append(
                f"`RoleService` 回退里的角色 `{role}` 既不在种子岗位矩阵、也没登记为历史角色"
                f"（岗位码漂移）—— 登记进 LEGACY_ROLES_IN_FALLBACK 或补种子"
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


# ══════════════════════════════════════════════════════════════════════════════════════
# issue #5291：三个域新增读码的**锚定台账**（判据 10 的唯一来源）
# ══════════════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ReadCodeAnchor:
    """一个**新增读码**的五处落点（判据 10 逐面复核；任一面掉码 ⇒ 红）。"""

    domain: str                                  # 业务域（红证文案用）
    tool: str                                    # 承载它的**只读**工具（判据 5 的载体）
    node_sources: tuple[tuple[str, str], ...]    # (菜单源标签, 节点名) —— 该源里该节点必须 == 本码
    legacy_code: str                             # 迁移前的管理/写码（读码回退 ⇒ 判据 5/10 红）
    page_code: str | None                        # 无独立菜单节点时：挂在哪个页读码下
    endpoints: tuple[str, ...]                   # 该码必须生效的关键读端点（`verb 路径`）
    role_holders: tuple[str, ...]                # 原持 legacy_code、必须同批持有本码的内置岗位


#: 三个域读码的锚定登记表（issue #5291：用户 2026-09-25 裁定「新增读码」）。
#:
#: ⚠️ **如实登记的两条边界**（不粉饰）：
#:   ① `auth` 源只登记**解析器看得见**的节点（`_iter_menu_auth` 只取 `permissions.contains(...)` 块内
#:      **首个** `menuItem`，而生产组那三个节点的 `if` 块以注释开头 ⇒ 解析面看不见它们）。
#:      `AuthService` 侧的同码由 `AuthServiceTest` 的**渲染面**断言兜住（按 `production:view` 拿菜单，
#:      断言「生产看板/工艺配置/计件工资」可见、按 `processing:manage` 拿只剩池看板）—— 那是行为级判据，
#:      不是文本级判据。本表**不**用「源码里出现过这个字符串」来假装覆盖。
#:   ② `system:view` 的 `role_holders` 为空是**有意**：内置岗位里只有 admin 持 `system:manage`（恒 `*`），
#:      其余岗位**一个都不给** —— 给 operator 就是让运营看见「岗位权限」页并读到权限目录（放宽，禁止）。
READ_CODE_ANCHORS: dict[str, ReadCodeAnchor] = {
    "product:category:view": ReadCodeAnchor(
        domain="商品分类",
        tool="category_manage",
        # 分类管理**没有独立侧边栏节点**（入口在商品列表页内）⇒ 走 `PAGE_READ_CODES` 挂页。
        node_sources=(),
        legacy_code="product:category",
        page_code="product:list",
        endpoints=("GET /api/admin/categories/tree", "GET /api/admin/categories"),
        role_holders=("operator",),
    ),
    "system:view": ReadCodeAnchor(
        domain="岗位权限 / 权限目录",
        tool="role_manage",
        node_sources=(("frontend", "岗位权限"), ("controller", "岗位权限"), ("auth", "岗位权限")),
        legacy_code="system:manage",
        page_code=None,
        endpoints=("GET /api/admin/permissions",),
        role_holders=(),
    ),
    "production:view": ReadCodeAnchor(
        domain="生产域",
        tool="processing_order_query",
        node_sources=(
            ("frontend", "加工项管理"), ("controller", "加工项管理"),
            ("frontend", "生产看板"), ("controller", "生产看板"),
            ("frontend", "工艺配置"), ("controller", "工艺配置"),
            ("frontend", "计件工资"), ("controller", "计件工资"),
        ),
        legacy_code="processing:manage",
        page_code=None,
        endpoints=(
            "GET /api/admin/processing-orders",
            "GET /api/admin/processing-items",
            "GET /api/admin/processing-order-sets",
            "GET /api/admin/production/operations-catalog",
            "GET /api/admin/production/routings",
            "GET /api/admin/production/craft-calc-config",
            "GET /api/admin/agent/production/progress",
            "GET /api/admin/agent/production/worklog",
            "GET /api/admin/agent/production/piecework",
        ),
        role_holders=("operator",),
    ),
}


def problems_read_code_anchoring(w: World) -> list[str]:
    """判据 10：三个域读码的**五面锚定**（issue #5291）—— 任一面掉码 ⇒ 红。

    为什么必须有**这一条**（既有判据 2/3/4 各自都有漏网形态 ⇒ 「删读码」这件事没人看得见）：
      ① 判据 3 的锚定对「节点**无码**」是**跳过**（`node_code is None ⇒ continue`：全员可见节点）；
      ② 菜单源的**交会同构**只比「两处都有码」的节点 —— 一方掉成无码 ⇒ 它退出交集 ⇒ 不报；
      ③ 判据 4 只在**真有岗位持该码**时才看得见「码没有节点」；岗位一旦没回填，它连看都不看。
    ⇒ 「把读码从某处删掉 / 退回管理码」必须有一条**能红**的判据，否则删码 = 授权语义悄悄消失
    （这正是 issue #5246/#5247 那批「代码收窄了、语义没落地」的同族形态）。
    """
    out: list[str] = []
    by_name = _by_name(w)
    for code, a in sorted(READ_CODE_ANCHORS.items()):
        # ① 权限目录：两处**集合相等**由判据 9② 判；这里判该码**在**目录里（否则岗位权限页勾不到）
        if code not in set(w.catalog):
            out.append(f"读码 `{code}`（{a.domain}）不在权限目录里 ⇒ 「岗位权限」页勾不到它")
        # ② 承载工具：必须**仍声明**本码、且仍是只读（退回管理码 = 本单要治的病复发）
        t = by_name.get(a.tool)
        if t is None:
            out.append(f"读码 `{code}` 登记的承载工具 `{a.tool}` 不存在（陈旧登记）")
        else:
            if code not in t.required_permissions:
                out.append(
                    f"{a.tool} 未声明读码 `{code}`（现声明 {list(t.required_permissions)}）"
                    "⇒ 只读工具退回管理码"
                )
            if not t.read_only:
                out.append(f"{a.tool} 已不是只读工具（read_only=False）⇒ 读码的「只读」语义无从成立")
        # ③ 菜单源：登记的每个 (源, 节点) 都必须**在**该源里、且码**逐字等于**本码
        for src, node in a.node_sources:
            nodes = w.menus.get(src, {})
            if node not in nodes:
                out.append(
                    f"菜单源 `{src}` 里没有节点『{node}』⇒ 读码 `{code}` 的锚点缺席"
                    "（菜单被改 / 解析面变了）"
                )
            elif nodes[node] != code:
                out.append(
                    f"菜单源 `{src}` 的节点『{node}』码 = `{nodes[node]}` ≠ 读码 `{code}` "
                    "⇒ 改/删一处菜单源即可悄悄回退"
                )
        # ④ 无独立节点的读码必须挂在某页读码之下，否则「码没有出处」（判据 3 ② 也会报）
        if a.page_code is not None and code not in PAGE_READ_CODES.get(a.page_code, frozenset()):
            out.append(
                f"读码 `{code}` 未登记在页 `{a.page_code}` 的 `PAGE_READ_CODES` 里 ⇒ 码没有出处"
            )
        # ⑤ 端点：登记的关键读端点必须**确实**挂本码（判据 2 管「工具码 ≡ 端点码」，这里管「哪几个端点」）
        for key in a.endpoints:
            verb, _, path = key.partition(" ")
            eps = w.all_eps.get((verb, path))
            if not eps:
                out.append(f"读码 `{code}` 登记的端点 `{key}` 在 admin-api 里查不到（陈旧登记 / 路径漂移）")
            elif not any(ep.permission == code for ep in eps):
                out.append(
                    f"端点 `{key}` 未挂读码 `{code}`"
                    f"（生效码 {sorted({ep.permission for ep in eps}, key=str)}）"
                )
        # ⑥ 岗位：原持 legacy 管理码的内置岗位必须**同批**持有本码（拆码不许变成收权）
        for role in a.role_holders:
            perms = w.roles.get(role)
            if perms is None:
                out.append(f"读码 `{code}` 登记的岗位 `{role}` 不在种子岗位矩阵里（陈旧登记）")
            elif "*" not in perms and code not in perms:
                out.append(
                    f"岗位 `{role}` 原持 `{a.legacy_code}`，却没有同批拿到读码 `{code}` ⇒ "
                    "拆码把它的菜单/Agent 面**收权**了（只收窄不放宽的反面）"
                )
    return out


# ── 判据 11：前端**页面守卫**（`ROUTE_PERMISSION_MAP`，issue #5291 的收口面）─────────────────
#
# 为什么必须有这一条：#5291 改了它 **5 个前缀**，而它此前**全仓零判据**（PR #5516 自己把它登记进
# 「未固化项」）⇒ 改错不会有东西变红。而它带着一个真实的权限面风险：`find()` 是**首个前缀命中**，
# 所以「更宽的前缀排在更具体的子路径之前」会把子路径整个遮蔽 —— `layout.tsx` 的 `/production`
#（读码）若排到 `/production/pool|remnants|saving-board`（管理码）之前，访问池看板就会按
# `production:view` 判定 ⇒ **两个方向的错都有**（持 `processing:manage` 者被 403、
# 持 `production:view` 者反而通行）。


def _strip_ts_line_comments(text: str) -> str:
    """剥掉 TS **行注释**（只在字符串**外**截断）——「注释不是代码」的口径，见 issue #5272/#5323。"""
    out_lines: list[str] = []
    for line in text.splitlines():
        quoted: str | None = None
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if quoted is not None:
                if ch == quoted:
                    quoted = None
            elif ch in "'\"`":
                quoted = ch
            elif ch == "/" and line[i : i + 2] == "//":
                cut = i
                break
            i += 1
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


_ROUTE_ENTRY_RE = re.compile(r"\{\s*prefix:\s*'([^']*)'\s*,\s*code:\s*'([^']*)'\s*\}")


def parse_route_guard(text: str) -> tuple[tuple[str, str], ...]:
    """解析 `layout.tsx` 的 `ROUTE_PERMISSION_MAP`（条目 = `(prefix, code)`，**保持源序**）。

    保持源序是前提：遮蔽只在「顺序」上有意义。注释一律剥掉（注释里贴的样例条目不算条目）。
    """
    entries = tuple(_ROUTE_ENTRY_RE.findall(_strip_ts_line_comments(text)))
    assert entries, (
        "`ROUTE_PERMISSION_MAP` 解析为空 ⇒ 判据 11 会空跑（fail-closed）。"
        "锚点漂移时先修解析器，**不得**让它静默通过。"
    )
    return entries


#: 路由前缀 → `config/menu.ts` 的**节点名**（判据 11 ③ 的锚点台账）。
#: 真值在**菜单源**一侧（复用同一份 `parse_menus`，不造第二个解析器）：本表只登记
#: 「这个页面在侧边栏里是哪个节点」，**不复写码** —— 码由菜单源现取比对。
ROUTE_MENU_ANCHORS: dict[str, str] = {
    "/after-sales": "售后工单",
    "/orders": "订单列表",
    "/products": "商品列表",
    "/processing": "加工项管理",
    "/production/pool": "智能派单",
    "/production/remnants": "余料台账",
    "/production/saving-board": "省料看板",
    "/production": "生产看板",
    "/customers": "客户列表",
    "/finance": "财务对账",
    "/employees": "员工管理",
    "/settings": "企业基础信息",
    "/knowledge": "知识库",
    "/roles": "岗位权限",
    "/briefing": "每日简报",
}

#: 没有可钉菜单节点的路由前缀（逐条带理由；**新增路由不登记即红** —— 见判据 11 ③ 末段）。
ROUTE_WITHOUT_MENU_NODE: dict[str, str] = {
    "/chat": "会话页没有侧边栏节点（「在线接待」的路径是 `/agent-workspace/human-sessions`）⇒ 守卫码 `agent:session` 无节点可钉",
    "/categories": "分类管理**没有独立侧边栏节点**（入口在商品列表页内，同 `READ_CODE_ANCHORS`）⇒ 该码由判据 10 的 `PAGE_READ_CODES['product:list']` 承担",
    "/processing-orders": "加工单唯一入口已并入「生产看板」（issue #4357）⇒ 本前缀只作旧链接兼容，节点归「生产看板」",
    "/dashboard": "菜单节点『经营看板』的码是 `None`（menu.ts 该行无 `permissionCode`），而页面守卫要 `dashboard:view` —— 两侧取值**不同**；本判据不假定哪一侧为真值（谁改都对不上时仍由②保证码在目录里），登记为残留",
}


def problems_route_guard(w: World) -> list[str]:
    """判据 11：`ROUTE_PERMISSION_MAP` 的**前缀序**与**码锚定**（issue #5291 收口）。

    三段（缺任何一段这条判据就有漏网形态）：
      ① **前缀序不得遮蔽**：任何条目的前缀都不得是**更早**条目的真前缀（`find()` 先命中即短路）；
      ② **码必须在权限目录里**：否则该路由**对所有角色恒 403**（码名打错 / 码已删）；
      ③ **前缀 ↔ 菜单节点**：登记的前缀必须解析到 `config/menu.ts` 的节点、且码逐字相等
         （侧边栏看得见而页面 403，或反之）；**未登记的前缀不登记即红**，台账陈旧也红。
    """
    out: list[str] = []
    entries = w.route_guard
    prefixes = [p for p, _ in entries]

    for p in sorted({q for q in prefixes if prefixes.count(q) > 1}):
        out.append(f"路由前缀 `{p}` 重复登记 ⇒ `find()` 只命中第一条，后一条是**死条目**")
    for p in prefixes:
        if not p.startswith("/"):
            out.append(f"路由前缀 `{p}` 不以 `/` 开头 ⇒ `pathname.startsWith` 永不命中（守卫失效）")

    # ① 遮蔽：更宽的前缀排在更具体的子路径之前 ⇒ 子路径永远命中不到
    for i, (p, _) in enumerate(entries):
        for q in prefixes[:i]:
            if p != q and p.startswith(q):
                out.append(
                    f"路由 `{q}` 排在更具体的 `{p}` 之前 ⇒ `{p}` 被短路成死条目："
                    "持更宽那侧码的人通吃、持该页自己的码的人被 403（两个方向的错都有）"
                )

    # ② 码必须在权限目录里
    catalog = set(w.catalog)
    for c in sorted({c for _, c in entries} - catalog):
        out.append(f"路由守卫要求码 `{c}`，它不在权限目录里 ⇒ 该路由**对所有角色恒 403**")

    # ③ 前缀 ↔ 菜单节点（真值 = 菜单源）
    known = set(prefixes)
    nodes = w.menus.get("frontend", {})
    for p, node in sorted(ROUTE_MENU_ANCHORS.items()):
        if p not in known:
            out.append(f"`ROUTE_MENU_ANCHORS` 登记的前缀 `{p}` 已不在 `ROUTE_PERMISSION_MAP` 里（陈旧登记）")
            continue
        if node not in nodes:
            out.append(f"`ROUTE_MENU_ANCHORS['{p}']` 指的节点『{node}』在 `config/menu.ts` 里不存在（陈旧登记）")
            continue
        guard_code = next(c for pp, c in entries if pp == p)
        if nodes[node] != guard_code:
            out.append(
                f"路由 `{p}` 的守卫码 = `{guard_code}` ≠ 菜单节点『{node}』的码 = `{nodes[node]}` "
                "⇒ 侧边栏与页面守卫各说各话（一方改了、另一方没跟上）"
            )

    for p in sorted(set(ROUTE_WITHOUT_MENU_NODE) - known):
        out.append(f"`ROUTE_WITHOUT_MENU_NODE` 登记的 `{p}` 已不在 `ROUTE_PERMISSION_MAP` 里（陈旧登记）")
    for p in sorted(known - set(ROUTE_MENU_ANCHORS) - set(ROUTE_WITHOUT_MENU_NODE)):
        out.append(
            f"路由 `{p}` 既没有菜单节点锚点、也没有「无节点」理由 ⇒ **新增页面守卫必须先登记**"
            "（否则它改了码不会有东西变红）"
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据 12 的专属面：菜单节点码 ≡ 该页**第一屏读端点**的生效码（issue #5675）
# ══════════════════════════════════════════════════════════════════════════════

#: 前端页面目录（Next.js 路由组；`MENU_READ_ENDPOINT_ANCHORS` 的 `page` 相对它拼）。
DASHBOARD_APP = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)"
#: 前端 api 客户端（判据 12 的**第二跳**：`xxxApi.fn` → HTTP 端点）。
API_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "api.ts"
#: 存量回填迁移（**第三个**岗位来源：读码回填谓词，与种子同谓词）。
V129_SQL = (
    REPO_ROOT / "backend/admin-api/src/main/resources/db/migration"
    / "V129__backfill_domain_read_permissions.sql"
)


@dataclass(frozen=True)
class MenuReadAnchor:
    """一条「节点 → 页面」的锚（判据 12 里**唯一**手写的东西）。

    `page` 是相对 `frontend/admin-web/src/app/(dashboard)/` 的页面文件；**端点与码一律现取**：
      ① `parse_menu_ts_nodes` 给出该节点的 `path` / `permissionCode`；
      ② 页面源码里**由 `useEffect` 驱动**的 api 调用（第一屏，不是点击才跑）；
      ③ `lib/api.ts` 把 api 函数解析成 URL；
      ④ `JavaEndpointIndex` 给出该 URL 的**生效码**（方法级优先）。
    四跳都是读源码，**没有一处靠推断**（issue #5675 范围①的要求）。
    """

    node: str
    page: str
    calls: tuple[str, ...]


#: `menu.ts` 节点 `path` → 页面文件 + **该页第一屏真实调用的 api 函数**（逐页读源码得出，不是推断）：
#: 只收「挂载即跑」那条链上的调用 —— 勾选/翻页/tab 切换才跑的调用（如 `/production/pool` 的
#: `preview`、`/knowledge` 的候选/模板、`/production/routings` 的算料配置）**不收**，
#: 否则会把交互面的码算成第一屏的码（实测踩过：入库单页的「建单表单」商品下拉会让
#: `product:list` 混进来，凭空造出并不存在的 403 受害者）。
#: **每个带 `path` 的节点都必须在这里**（未登记即红）。
MENU_READ_ENDPOINT_ANCHORS: dict[str, MenuReadAnchor] = {
    "/dashboard": MenuReadAnchor("经营看板", "dashboard/page.tsx", (
        "dashboardApi.getStats", "dashboardApi.getOrderTrend",
        "dashboardApi.getProductRanking", "dashboardApi.getRecentOrders",
        "briefingApi.getConfig")),
    "/briefing": MenuReadAnchor("每日简报", "briefing/page.tsx", ("briefingApi.getConfig",)),
    "/agent-workspace/human-sessions": MenuReadAnchor(
        "在线接待", "agent-workspace/human-sessions/page.tsx",
        ("agentSessionApi.getSessions", "agentSessionApi.getSession")),
    "/knowledge": MenuReadAnchor("知识库", "knowledge/page.tsx", ("knowledgeApi.getCards",)),
    "/products": MenuReadAnchor("商品列表", "products/page.tsx", ("productApi.getProducts",)),
    "/production/processing": MenuReadAnchor("加工项管理", "production/processing/page.tsx", (
        "processingItemApi.getProcessingItems", "productionApi.getFeeCombinations",
        "productionApi.getFeeGaps", "processingCategoryApi.getProcessingCategories")),
    "/orders": MenuReadAnchor("订单列表", "orders/page.tsx", ("orderApi.getOrders",)),
    "/after-sales": MenuReadAnchor("售后工单", "after-sales/page.tsx", ("afterSalesApi.getTickets",)),
    "/customers": MenuReadAnchor("客户列表", "customers/page.tsx", (
        "customerApi.getCustomers", "customerApi.getCustomerTags")),
    "/finance": MenuReadAnchor("财务对账", "finance/page.tsx", (
        "financeApi.getSummary", "financeApi.getTransactions", "financeApi.getReconciliation")),
    "/production": MenuReadAnchor("生产看板", "production/page.tsx", ("processingOrderApi.list",)),
    "/production/pool": MenuReadAnchor("智能派单", "production/pool/page.tsx",
                                       ("poolBoardApi.getBoard",)),
    "/production/routings": MenuReadAnchor("工艺配置", "production/routings/page.tsx", (
        "productionApi.getRoutings", "productionApi.getOperationsCatalog",
        "productionApi.getRouteRules", "productionApi.getRouteRuleOptions",
        "productionApi.getOperationPositions", "productionApi.getSeedTemplates")),
    "/production/piecework": MenuReadAnchor("计件工资", "production/piecework/page.tsx",
                                            ("productionApi.getPieceworkSummary",)),
    "/inbound-orders": MenuReadAnchor("入库单", "inbound-orders/page.tsx", ("inboundOrderApi.list",)),
    "/production/remnants": MenuReadAnchor("余料台账", "production/remnants/page.tsx",
                                           ("remnantApi.ledger",)),
    "/production/saving-board": MenuReadAnchor("省料看板", "production/saving-board/page.tsx",
                                               ("savingBoardApi.board", "savingBoardApi.trend")),
    "/employees": MenuReadAnchor("员工管理", "employees/page.tsx", (
        "employeeApi.getEmployees", "employeeApi.loadPositions")),
    "/roles": MenuReadAnchor("岗位权限", "roles/page.tsx", (
        "roleApi.getRoles", "permissionApi.getPermissions")),
    "/settings": MenuReadAnchor("企业基础信息", "settings/page.tsx", (
        "settingsApi.getSettings", "settingsApi.getAiConfig", "briefingApi.getConfig")),
    "/notifications": MenuReadAnchor("通知中心", "notifications/page.tsx",
                                     ("notificationApi.getNotifications",)),
}


@dataclass(frozen=True)
class MenuReadResidual:
    """残留登记的四件套：**理由 + 显形条件 + 谁负责**，外加（有 403 受害者时必需的）**认领**。"""

    reason: str
    surfaces_when: str
    owner: str
    #: 该路径**确有** 403 受害者时，逐条认领（谁、缺什么码、为什么本单不改）——空 ⇒ 受害者段判红；
    #: 反过来，若无受害者却写了认领 ⇒ 陈旧认领，也判红（它在替未来的真受害者放行）。
    victims_ack: str = ""


#: 🔴 **只许缩短的残留台账**（issue #5675）：`节点码 ≠ 该页第一屏读端点码` 且本单**有意不修**的项。
#: 两条机械约束（都在 `problems_menu_read_parity` 里判）：
#:   ① 台账里**每一条**都必须仍然真的不一致 —— 不一致消失而条目还在 ⇒ **红**（逼人删掉它）；
#:   ② 判据发现的**每一个**不一致都必须在这里具名 —— 未登记 ⇒ **红**。
#: 于是「新增一处不一致」与「修好了却不销账」都是可红的动作，台账只会变短。
#:
#: ⚠️ 与 `MULTI_READ_ENDPOINT_PAGES` 的分工（#5675 收口包）：**本台账装「不一致性」**（设计上要被
#: 销掉的债 ⇒ 只许缩短）；**那张表装「结构性事实」**（一页第一屏并发哪几个码，冻结、不承诺缩短）。
#: 分工不是修辞：把结构事实塞进本台账，「只许缩短」的压力会变成「硬凑一个码」的动机 —— 而硬凑
#: 一个码就得改某侧注解 ⇒ 改某个岗位集合的可见性或可做性（本台账三条多端点项的 `reason` 逐条记着
#: 为什么两个方向都不能走）。
MENU_READ_PARITY_RESIDUALS: dict[str, MenuReadResidual] = {
    "/dashboard": MenuReadResidual(
        reason=(
            "「经营看板」节点**有意无码**（`frontend/admin-web/src/config/menu.ts` 该行没有 permissionCode"
            " ⇒ 全员可见），而页面守卫与第一屏读端点都取 `dashboard:view` ⇒ 两侧取值不同。"
            "本判据**不假定哪一侧为真值**（谁改都能让本项消失，改错方向会判红）——"
            "判据 11 的 `ROUTE_WITHOUT_MENU_NODE['/dashboard']` 登记的是同一件事。"
        ),
        surfaces_when="给该节点补上 `dashboard:view`（两侧同码）⇒ 本项应删除。",
        owner="菜单面（`frontend/admin-web/src/config/menu.ts` 的 workspace 组）+ 本守卫的残留台账",
    ),
    "/production/pool": MenuReadResidual(
        reason=(
            "「智能派单」节点挂 `processing:manage`、读端点要 `processing:view` —— issue #5291 的**有意**"
            "决定（`menu.ts` 的 #5291 注记逐字登记），issue #5675 逐岗位复算后**维持原判**："
            "两个方向的「对齐」都会改变某个岗位集合 —— ① 节点码改读码 ⇒ 客服/销售/财务（三个来源都持"
            " `processing:view`）**凭空看见**该菜单，而前端路由守卫 "
            "（`frontend/admin-web/src/app/(dashboard)/layout.tsx` 的 `/production/pool`）仍是管理码 ⇒ "
            "正好造出本判据要治的「菜单看得见、点进去 403」；② 端点码改管理码 ⇒ 这三个岗位的 API "
            "可做性被收窄，且手机端入口（`frontend/bmini-app/src/utils/adminPermission.ts` 按端点码判可见）"
            "一并消失。两侧**都要有人明确裁定**才动。"
        ),
        surfaces_when=(
            "节点码与 `layout.tsx` 的该前缀**同批**改挂读码（且已确认「只持旧读码的岗位」的可见性变化"
            "是被裁定的）⇒ 本项删除；单独改一侧 ⇒ 判据 11/12 立刻红。"
        ),
        owner="生产域菜单/权限面（下一位改生产组菜单或 ProductionPoolController 读端点的人）+ 本守卫的残留台账",
    ),
    "/production/saving-board": MenuReadResidual(
        reason=(
            "「省料看板」节点挂 `processing:manage`，而该页第一屏两个端点"
            "（`GET /api/admin/batch-stock/saving-board`、`.../saving-trend`）在 `StockBatchController` 上"
            "各带**方法级** `@RequirePermission(\"product:list\")`（⚠️ **不是**类级 —— 该控制器**没有**"
            "类级注解；它的类 javadoc 里那句「权限复用商品域 product:list」是**注释**不是注解，"
            "把注释读成注解正是本守卫要治的「读到的文本与它声称的对象不是同一个」；#5675 收口包已更正"
            "此前残留登记里的「类级」措辞）。该组注记写「与各自页面的类级码同码」—— 对余料台账成立"
            "（`RemnantController` 确为**类级** `processing:manage`）、对省料看板**不成立**。"
            "**为什么不是笔误而是历史包袱**：`StockBatchController` 的类 javadoc 逐字登记了本次复用"
            "决定 ——「权限复用商品域 `product:list`（批次/库存属于商品管理的读权限，不新造权限点 ——"
            " 新权限点需要配角色/种子数据，本 issue 不含权限模型变更）」（V116 / issue #5145 立的口径），"
            "省料看板两个端点是 issue #5159 后来**长进同一个控制器**的，自然沿用该族码；而节点码来自"
            "另一条线（#5271 放进「仓储与物料」组、沿用该组的管理码）⇒ 两侧各自有据，没有哪一侧是打错的字。"
            "**今天零受害**：持节点码的岗位（种子 ∪ 回退）= admin / operator / product_manager@fallback，"
            "三个都持 `product:list`（V129 回填与节点码无关，见 ② 段的谓词前提）。"
        ),
        surfaces_when=(
            "① 节点码改 `product:list` ⇒ 销售（种子）与 knowledge_editor / product_manager（回退）"
            "**凭空看见**该菜单（它们持 `product:list` 而无管理码）—— 而前端路由守卫"
            "（`frontend/admin-web/src/app/(dashboard)/layout.tsx` 的 `/production/saving-board`）仍是管理码"
            "⇒ 正好造出本判据要治的「菜单看得见、点进去 403」；"
            "② 端点码改 `processing:manage` ⇒ 只持 `product:list` 者失去该页可读性，且手机端"
            "（`frontend/bmini-app/src/utils/adminPermission.ts` 按**端点码**判可见）一并变。"
            "两侧**都要有人明确裁定**才动。"
        ),
        owner="仓储与物料组菜单/权限面（menu.ts 的 inventory-center 组 + StockBatchController）+ 本守卫的残留台账",
    ),
    "/production/processing": MenuReadResidual(
        reason=(
            "「加工项管理」页第一屏**跨三个码**（`MULTI_READ_ENDPOINT_PAGES['/production/processing']` "
            "逐值冻结）：加工项 = `production:view`（`ProcessingItemController` 的**方法级**覆盖，与节点同码 ✓）、"
            "加工费组合/缺口 = `ProductionController` 的**类级** `order:list`（这两个 GET 没有方法级覆盖）、"
            "加工分类 = `ProcessingCategoryController` 的**类级** `processing:manage`（#5291 的读码迁移"
            "没走到这两个端点族）。**为什么不能对齐**（两个方向都会改某个岗位集合，复算见 ② 段）："
            "① 节点码改 `order:list` ⇒ 客服 / 销售 / 财务（三来源都持 `order:list`）凭空看见该菜单；"
            "② 端点码全改 `production:view` ⇒ 持 `order:list` 而不持读码的客服 / 销售 / 财务（种子）"
            "**失去**加工费组合 / 缺口的可读性。"
        ),
        surfaces_when=(
            "出现「持 `production:view` 而不持 `order:list`/`processing:manage`」的岗位 ⇒ 该页对应 tab 的"
            "第一屏 403 —— 届时判据 12 的**零 403 受害者**段会先判红（不必依赖本条登记）。"
        ),
        owner="生产域读码收口面（#5291 未走完的端点族）+ 本守卫的残留台账",
        victims_ack=(
            "回退路径仍有受害者：`product_manager@fallback` 持 `production:view` 而不持 `order:list` "
            "⇒ 该页「加工费组合」tab 的第一屏 403。**#5683 未修**：给历史遗留岗位补 `order:list` 是"
            "**又一次**授权放宽，且它**不在** #5683 已批准的范围里（批的是 `processing:view`）——"
            "同一个历史岗位的第二处分叉，必须由人类**单独裁定**才不会把「已批准的 2 例」悄悄扩大。"
            "去向：与「该页端点族到底挂 `order:list` 还是 `production:view`」同批裁定。"
        ),
    ),
    "/production/routings": MenuReadResidual(
        reason=(
            "「工艺配置」节点与两个只读端点（`/routings`、`/operations-catalog`）同码 `production:view` ✓，"
            "但该页第一屏**并发六个读端点、跨两个码**（`MULTI_READ_ENDPOINT_PAGES['/production/routings']` "
            "逐值冻结）：路线规则族（`route-rules` / `route-rule-options` / `operation-positions` / "
            "`seed-templates`）都是 `processing:manage`。"
            "⚠️ **收口包独立复核的更正**：这一族**不是**「#5291 漏改」（那是 #5675 修计件工资时的形态），"
            "而是**有断言记录的族级决定** —— `ProductionRoutingReadControllerTest#endpointsDeclareManagePermission` "
            "逐字断言 `operationPositions` / `routeRules` 两个读端点必须声明 `processing:manage`（理由逐字："
            "「价目与规则是生产配置面」），`ProductionSeedTemplateControllerTest` 的 `endpointsInheritClassPermission` "
            "逐字断言该控制器不得有更宽松的方法级覆盖（套用会真的批量落库）。"
            "**「改漏」这个假设的来源已定位**：`RegistrationService` 的生产域读码目录注释写「四个页面的读端点」"
            "同批改挂本码，而 `ProductionController` 的类注记逐字只写「**两个**只读端点（`/operations-catalog`、"
            "`/routings`）改挂读码」⇒ 两处措辞不一致（前者过宽）。以 **Java 断言**为准：族级码是裁定过的，"
            "不是漏的。今天零受害（持读码的岗位都同持管理码，复算见 ② 段）。"
        ),
        surfaces_when=(
            "出现只持 `production:view` 的岗位（例如租户在「岗位权限」页只勾读码）⇒ 工艺配置页第一屏的"
            "规则族四处 403 —— 同上的**零 403 受害者**段会先判红。**若人类裁定该族改挂读码**，"
            "必须同批改那两条 Java 断言（它们钉的就是相反的决定）并重跑本判据。"
        ),
        owner="生产域配置族权限面（ProductionController / ProductionSeedTemplateController + 上述两条 Java 断言）+ 本守卫的残留台账",
    ),
    "/settings": MenuReadResidual(
        reason=(
            "「企业基础信息」节点 = `system:manage`，而该页第一屏**并发三个读端点、跨两个码**"
            "（`MULTI_READ_ENDPOINT_PAGES['/settings']` 逐值冻结）：企业设置 + AI 配置 = `system:manage` ✓，"
            "每日简报开关（`GET /api/admin/briefing/config`）= `dashboard:view`。今天零受害："
            "`system:manage` 的持有者（三来源里只有 admin）恒为 `*`；而把简报端点改挂 `system:manage` "
            "会让只持 `dashboard:view` 的六个岗位失去 /briefing 页与看板的简报开关（两个方向都不能走）。"
        ),
        surfaces_when=(
            "把 `system:manage` 授给非 `*` 的岗位 ⇒ 该页简报开关读数 403 —— 同上的"
            "**零 403 受害者**段会先判红。"
        ),
        owner="组织管理组菜单/权限面（menu.ts 的 org-center 组 + BriefingController）+ 本守卫的残留台账",
    ),
}


@dataclass(frozen=True)
class MultiReadEndpointPage:
    """一页第一屏**并发多个不同码**的读端点时的**结构性**登记（#5675 收口包新增）。"""

    node: str
    #: 该页第一屏**现取**到的全部非 None 端点码（判据逐值比对 ⇒ 多一个 / 少一个都红）。
    codes: frozenset[str]
    reason: str
    owner: str


#: 🔴 多端点页登记表（#5675 收口包）：判据 12 的命题「节点码 ≡ 该页**第一屏读端点码**」只在
#: 「第一屏**恰好一个**读端点码」的页面上适定。#5675 正是按这个前提修的「计件工资」页 ——
#: 它的 PR body 逐字写着「两页第一屏都**只调一个读端点**（无聚合旁路），故不存在『硬凑一对』的情形」。
#: 而下面这些页面在同一时刻**并发** ≥2 个不同码的第一屏读端点 ⇒ 不存在「那一个」码可对齐；
#: 硬凑一个码 = 改某个岗位集合的可见性或可做性（每条的 `reason` 记着两个方向各会改谁）。
#:
#: 三条机械约束（都在 `problems_menu_read_parity` 里判）：
#:   ① **覆盖**：第一屏现取到 ≥2 个不同码的页面**必须**在此具名（未登记 ⇒ 红）—— 判据 12 的
#:      「单端点」前提被打破时必须有东西提醒，否则它会在无人察觉时退化成空断言；
#:   ② **冻结**：登记的码集必须与**现取**逐值相等（多一个 / 少一个 ⇒ 红）—— 给某页新增或改挂一个
#:      第一屏端点码，不会被「这页已经登记过了」吞掉；
#:   ③ **陈旧**：已不再并发多码的页面（或 path 已不在 `menu.ts`）必须删掉本条（⇒ 红）——
#:      结构性登记与残留台账同口径，**只许缩短**。
#: 🔴 **本表不是豁免**：它**不解释任何不一致**。节点码只命中其中一个码 ⇒ 该页**同时**进
#: `MENU_READ_PARITY_RESIDUALS`（判据 12 第 ③ 段）；持节点码却缺其余码的岗位 ⇒ 照旧走第 ④ 段
#: 的零 403 受害者与 `victims_ack` 认领。表里三条今天**都**在残留台账里。
MULTI_READ_ENDPOINT_PAGES: dict[str, MultiReadEndpointPage] = {
    "/production/processing": MultiReadEndpointPage(
        node="加工项管理",
        codes=frozenset({"production:view", "order:list", "processing:manage"}),
        reason=(
            "第一屏由**一个** `useEffect` 并发四跳（`loadItems` / `loadCombinations` / `loadGaps`，"
            "页面源码里三条 `Promise.allSettled` 分支各给可读降级提示），落三个不同码："
            "加工项 = `production:view`（`ProcessingItemController` 的方法级覆盖，与节点同码）；"
            "加工费组合 / 缺口 = `order:list`（`ProductionController` 的**类级**码，这两个 GET 无方法级覆盖）；"
            "加工分类 = `processing:manage`（`ProcessingCategoryController` 的**类级**码）。"
            "**两个方向都不能对齐**：① 节点码改 `order:list` ⇒ 客服 / 销售 / 财务凭空看见该菜单"
            "（三来源都持 `order:list`）；② 端点码全改 `production:view` ⇒ 持 `order:list` 而不持读码的"
            "客服 / 销售 / 财务（种子）失去加工费组合 / 缺口的可读性。"
        ),
        owner="生产域读码收口面（#5291 未走完的端点族）+ 本守卫的多端点登记表",
    ),
    "/production/routings": MultiReadEndpointPage(
        node="工艺配置",
        codes=frozenset({"production:view", "processing:manage"}),
        reason=(
            "第一屏由**一个** `useEffect`（`load()`）并发六跳（六条 `Promise.allSettled`），落两个码："
            "工艺路线 + 工序库 = `production:view`（`ProductionController` 的方法级覆盖，与节点同码）；"
            "配置族读面（`route-rules` / `route-rule-options` / `operation-positions` / `seed-templates`）"
            "= `processing:manage`。**这一族是有裁定记录的族级决定，不是 #5291 漏改**："
            "`ProductionRoutingReadControllerTest#endpointsDeclareManagePermission` 逐字断言 "
            "`operationPositions` / `routeRules` 两个读端点必须声明 `processing:manage`（理由逐字"
            "「价目与规则是生产配置面」），`ProductionSeedTemplateControllerTest` 的 "
            "`endpointsInheritClassPermission` 逐字断言该控制器不得有更宽松的方法级覆盖。"
            "⇒ 对齐这一族 = 改掉那三条 Java 断言的裁定（需人类裁定，本单射程外）。"
        ),
        owner="生产域配置族权限面（ProductionController / ProductionSeedTemplateController + 两条 Java 断言）+ 本守卫的多端点登记表",
    ),
    "/settings": MultiReadEndpointPage(
        node="企业基础信息",
        codes=frozenset({"dashboard:view", "system:manage"}),
        reason=(
            "第一屏并发三跳，落两个码：企业设置 + AI 配置 = `system:manage`（与节点同码）；"
            "每日简报开关 = `dashboard:view`（`BriefingController` 的读码 —— /briefing 页与经营看板也读它）。"
            "**两个方向都不能对齐**：① 简报端点改 `system:manage` ⇒ 只持 `dashboard:view` 的六个岗位"
            "（客服 / 运营 / 销售 / 财务 / `product_manager`@回退 / `knowledge_editor`@回退）"
            "失去 /briefing 页与看板的简报开关可读性；② 节点码改 `dashboard:view` ⇒ 全员看见「企业基础信息」。"
        ),
        owner="组织管理组菜单/权限面（menu.ts 的 org-center 组 + BriefingController）+ 本守卫的多端点登记表",
    ),
}


def _js_block(text: str, open_brace: int) -> str:
    """从 `{` 起做括号配平取块（TS/JS 源码的粗粒度切分，够用即止）。

    ⚠️ 如实登记：字符串/注释里的裸花括号会干扰配平。失配的后果是**块偏大或偏小**，
    偏大 ⇒ 多收调用（更容易红），偏小 ⇒ 可能漏判 —— 故有两道补偿：`/notifications` 这类
    极简页也照样解析出调用（解析出 0 个调用 ⇒ 红），且注入式红证覆盖两个方向。
    """
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    return text[open_brace:]


def page_first_screen_text(page_text: str) -> str:
    """页面源码里**由 `useEffect` 驱动**的可执行面（= 判「第一屏读端点」的语料）。

    = 每个 `useEffect(() => { … }, […])` 的块体 ∪ 这些块体里**被调用**的本地函数定义体
    （一跳：`useEffect(() => { load() }, [load])` 是仓里最常见的形态）。
    「点击才跑」的处理函数**不在**这个面里 ⇒ 把第一屏调用挪进按钮不会静默通过。

    ⚠️ 边界（如实登记）：`useEffect` 的依赖形态多样（`[]` / `[loader]` / `[tab]`），本判据**不**逐一
    证明「该 effect 一定在挂载时跑」；它证明的是「这些调用由某个 effect 驱动、不是纯交互路径」。
    真正的锚是台账里逐条读过的页面（`MENU_READ_ENDPOINT_ANCHORS`）+ 下面四跳现取的端点码。
    """
    parts: list[str] = []
    driven: set[str] = set()
    for m in re.finditer(r"useEffect\(\s*\(\)\s*=>\s*\{", page_text):
        body = _js_block(page_text, m.end() - 1)
        parts.append(body)
        driven |= set(re.findall(r"\b(\w+)\s*\(", body))
    for name in sorted(driven):
        for pat in (rf"const\s+{name}\s*=\s*useCallback\(", rf"function\s+{name}\s*\("):
            for m in re.finditer(pat, page_text):
                brace = page_text.find("{", m.end())
                if brace != -1:
                    parts.append(_js_block(page_text, brace))
    return "\n".join(parts)


def parse_frontend_api_calls(text: str) -> dict[tuple[str, str], tuple[str, str]]:
    """`frontend/admin-web/src/lib/api.ts`：`(api 对象名, 方法名) → (verb, url)`。

    🔴 键**必须带对象名**：方法名跨对象大量重名（`list` / `preview` / `detail` …）——
    只按方法名解析会把 `processingOrderApi.list` 读成 `inboundOrderApi.list` 的 URL
    （issue #5675 实测踩过：拿错端点 ⇒ 判据拿别人的码去比）。
    """
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for m in re.finditer(r"export const (\w+)\s*=\s*\{", text):
        obj = m.group(1)
        segment = _js_block(text, m.end() - 1)
        for call in re.finditer(
            r"request\.(get|post|put|patch|delete)\s*(?:<[^()]*>)?\s*\(\s*[`'\"]([^`'\"]+)",
            segment,
            re.S,
        ):
            decls = re.findall(r"\n\s*(\w+)\s*:\s*(?:async\s*)?\(", segment[:call.start()])
            if decls:
                out.setdefault((obj, decls[-1]), (call.group(1).upper(), call.group(2)))
    assert len(out) >= 100, f"api.ts 只解析出 {len(out)} 个调用 ⇒ 判据会空跑（fail-closed）"
    return out


def _norm_endpoint_url(url: str) -> str:
    """`/api/admin/agent-sessions/${id}` → `…/{}`（与 `JavaEndpointIndex` 的模板口径对齐）。"""
    return re.sub(r"\$\{[^}]*\}", "{}", url)


def _effective_codes(w: World, verb: str, url: str) -> tuple[str | None, ...] | None:
    """端点的**生效码**（精确命中优先，其次 `{}` 模板正则回退）；端点查不到 ⇒ None。"""
    path = _norm_endpoint_url(url)
    exact = w.all_eps.get((verb, path))
    if exact:
        return tuple(sorted((ep.permission for ep in exact), key=str))
    hits: list[str | None] = []
    for (v, tpl), eps in w.all_eps.items():
        if v != verb:
            continue
        rx = re.compile("^" + re.escape(tpl).replace(re.escape("{}"), "[^/]+") + "$")
        if rx.match(path):
            hits.extend(ep.permission for ep in eps)
    return tuple(sorted(set(hits), key=str)) if hits else None


def _holder_roles(w: World, code: str | None) -> tuple[str, ...]:
    """三处岗位来源（种子 / 硬编码回退）里持该码的岗位（`*` 通配恒真）。"""
    if code is None:
        return ()
    out: set[str] = set()
    for label, table in (("seed", w.roles), ("fallback", w.role_fallback)):
        for role, codes in table.items():
            if "*" in codes or code in codes:
                out.add(f"{role}@{label}")
    return tuple(sorted(out))


def problems_menu_read_parity(w: World) -> list[str]:
    """判据 12：`menu.ts` 每个节点的码 ≡ 它 `path` 对应页面**第一屏读端点**的生效码（issue #5675）。

    病根：菜单**可见性**只由节点码决定，而点进去成不成由端点码决定 ⇒ 两侧不同就是「可见面与可做面
    脱钩」：持节点码而不持端点码的人「菜单看得见、点进去 403」（潜伏；受害人群今天为空，但可显形）。
    五段（缺任何一段这条判据就有漏网形态）：
      ① **覆盖**：每个带 `path` 的节点必须登记锚点（未登记 ⇒ 红）；锚点也不得陈旧/错人；
      ② **四跳现取**：页面 → `useEffect` 驱动的调用 → `lib/api.ts` 的 URL → Java 生效码
         （任一跳解析不出来 ⇒ 红，**不静默跳过**）；
      ③ **一致性**：节点码必须等于该页第一屏**每个**非 None 端点码，否则必须具名登记在
         `MENU_READ_PARITY_RESIDUALS`（台账**只许缩短**：不一致消失而条目还在 ⇒ 红）；
      ④ **零 403 受害者（逐岗位复算）**：任何持节点码的岗位，必须同时持该页第一屏的每个端点码
         —— 这是「菜单看得见 ⇒ 点进去一定打得开」的机械形态（种子 + 回退两处来源）；
      ⑤ **多端点页的适用面前提**：第一屏现取到 ≥2 个不同码的页面必须具名在
         `MULTI_READ_ENDPOINT_PAGES` 且码集逐值冻结（未登记 / 与现取不符 / 已不再多码 ⇒ 红）。
         ⚠️ ⑤ **不替代** ③④：本表**不是豁免**（多端点页的不一致照样要进残留台账、受害者照样要认领）；
         它保证的是「③ 的『那一个码』前提在哪些页面上不成立」这件事**一直被记着**。
    """
    out: list[str] = []
    nodes = [n for n in parse_menu_ts_nodes(w.sources["menu:frontend"]) if n.path]
    by_path = {n.path: n for n in nodes}
    api_calls = parse_frontend_api_calls(w.sources["frontend:api.ts"])

    # ⓪ 复算的**前提自证**（issue #5675）：存量租户那一路（V129）必须仍是「读码 ← 只授给
    #    原本持管理码的岗位」。它是「可见性零变化」复算的第三个来源 —— 谓词被改成「授给所有人」
    #    或「授给只持旧读码的岗位」时，本判据的种子/回退复算**看不出来**，故必须单独钉住。
    v129 = w.sources.get("sql:V129", "")
    branch = v129[v129.find("-- ②-b"): v129.find("-- ②-c")] if "-- ②-b" in v129 else ""
    for literal, why in (
        ("'production:view'", "生产域读码本身"),
        ("'processing:manage'", "回填谓词（只授给原本持管理码的岗位）"),
    ):
        if literal not in branch:
            out.append(
                f"`V129__backfill_domain_read_permissions.sql` 的 ②-b 段（生产域读码回填）里找不到 "
                f"{literal} —— {why}变了 ⇒ 「持读码的岗位集合 = 持管理码的岗位集合」这条"
                "可见性零变化复算的前提不再成立（本单的复算以它为前提）"
            )

    # ① 覆盖 + 锚点卫生（陈旧锚点 / 锚错人都不许静默）
    for path in sorted(set(MENU_READ_ENDPOINT_ANCHORS) - set(by_path)):
        out.append(f"`MENU_READ_ENDPOINT_ANCHORS['{path}']` 在 `config/menu.ts` 里找不到该 path（陈旧登记）")
    for path in sorted(set(by_path) - set(MENU_READ_ENDPOINT_ANCHORS)):
        out.append(
            f"菜单节点『{by_path[path].name}』（`{path}`）没有登记「第一屏读端点」锚点 ⇒ "
            "**新增菜单节点必须先登记**（否则它的节点码与页面读码脱钩时不会有东西变红）"
        )

    mismatching: list[str] = []
    endpoint_codes_by_path: dict[str, set[str]] = {}
    for path, node in sorted(by_path.items()):
        anchor = MENU_READ_ENDPOINT_ANCHORS.get(path)
        if anchor is None:
            continue
        if anchor.node != node.name:
            out.append(
                f"锚点 `{path}` 指的是『{anchor.node}』，而 `config/menu.ts` 该 path 现在是『{node.name}』"
                "（路径↔节点漂移 ⇒ 锚错人）"
            )
            continue
        page_rel = f"frontend/admin-web/src/app/(dashboard)/{anchor.page}"
        page_text = w.sources.get(f"page:{path}")
        if page_text is None:
            out.append(f"锚点 `{path}` 的页面源码没进源码表（{page_rel}）—— 路径漂移 ⇒ 红")
            continue
        # ②-a **声明面自证**：台账声明的每个调用必须仍在该页的「effect 驱动面」上 ——
        #     挪进纯交互路径（点击/勾选才跑）就不再是第一屏调用 ⇒ 声明陈旧，必须同步台账。
        corpus = page_first_screen_text(page_text)
        for call in anchor.calls:
            if call not in corpus:
                out.append(
                    f"锚点 `{path}` 声明的 `{call}` 不在『{node.name}』（`{page_rel}`）的"
                    " **effect 驱动面**上 ⇒ 它已被挪到纯交互路径（第一屏不再调它）或声明陈旧"
                    " ⇒ 同步 `MENU_READ_ENDPOINT_ANCHORS`"
                )
        codes: list[str | None] = []
        for call in anchor.calls:
            obj, fn = call.split(".", 1)
            target = api_calls.get((obj, fn))
            if target is None:
                out.append(
                    f"『{node.name}』第一屏调了 `{call}`，但 `frontend/admin-web/src/lib/api.ts` 里"
                    "解析不出它的 URL ⇒ 判据不静默跳过（端点未知即红）"
                )
                continue
            verb, url = target
            eps = _effective_codes(w, verb, url)
            if eps is None:
                out.append(
                    f"『{node.name}』第一屏的 `{call}` → `{verb} {url}` 在 admin-api 的端点表里查不到"
                    "（端点未落地/路径漂移 ⇒ 红）"
                )
                continue
            codes.extend(eps)
        real_codes = sorted({c for c in codes if c is not None})
        endpoint_codes_by_path[path] = set(real_codes)
        if not real_codes:
            # 第一屏全部落在**未注解端点**上（判据 8 已逐条登记那些端点）⇒ 本判据无数可对。
            continue
        for code in real_codes:
            if code == node.code:
                continue
            mismatching.append(path)
            if path not in MENU_READ_PARITY_RESIDUALS:
                out.append(
                    f"『{node.name}』（`{path}`）的节点码 = `{node.code}`，而该页第一屏读端点要 "
                    f"`{code}`（{page_rel}）⇒ 可见面与可做面脱钩。"
                    "**要么对齐两处码，要么在 `MENU_READ_PARITY_RESIDUALS` 里具名登记"
                    "（理由 + 显形条件 + 谁负责）**"
                )

    # ③ 台账只许缩短（不一致消失而条目还在 ⇒ 红）
    for path in sorted(set(MENU_READ_PARITY_RESIDUALS) - set(mismatching)):
        out.append(
            f"`MENU_READ_PARITY_RESIDUALS['{path}']` 已不再不一致（两侧现同码或该节点已不在）"
            " ⇒ **删掉这条登记**（台账只许缩短；陈旧条目会把下一次真回归读成「已登记」）"
        )
    for path, residual in sorted(MENU_READ_PARITY_RESIDUALS.items()):
        empty = [
            name for name, value in (("reason", residual.reason),
                                     ("surfaces_when", residual.surfaces_when),
                                     ("owner", residual.owner))
            if not value.strip()
        ]
        if empty:
            out.append(f"`MENU_READ_PARITY_RESIDUALS['{path}']` 缺字段 {empty}（理由/显形条件/谁负责缺一即红）")

    # ④ 零 403 受害者：持节点码 ⇒ 必持该页第一屏的每个端点码（逐岗位复算：种子 ∪ 硬编码回退）。
    #    🔴 **面外不是安全区**（migao-dev-flow §23 G4）：只算种子会漏掉「无 role_permissions 记录的
    #    历史账号」（回退路径），而那正是「菜单看得见、点进去 403」最容易存活的地方。
    #    已有具名登记的路径 ⇒ 必须由该条登记的 `victims_ack` **逐条认领**（不认领照样红）。
    victims_by_path: dict[str, list[str]] = {}
    for path, node in sorted(by_path.items()):
        endpoint_codes = endpoint_codes_by_path.get(path, set())
        if not endpoint_codes or not node.code:
            continue
        for role in _holder_roles(w, node.code):
            missing = sorted(c for c in endpoint_codes if role not in _holder_roles(w, c))
            if not missing:
                continue
            victims_by_path.setdefault(path, []).append(f"{role} 缺 {missing}")
            residual = MENU_READ_PARITY_RESIDUALS.get(path)
            if residual is not None and residual.victims_ack.strip():
                continue  # 已具名认领（见 `victims_ack`）
            out.append(
                f"🔴 403 受害者：岗位 `{role}` 持节点码 `{node.code}`（看得见『{node.name}』）"
                f"却不持该页第一屏读端点码 {missing} ⇒ 「菜单看得见、点进去 403」"
                "（零受害者段：新增岗位/改码都会在这里变红；确有裁定 ⇒ 在该路径的登记里写 `victims_ack`）"
            )
    for path, residual in sorted(MENU_READ_PARITY_RESIDUALS.items()):
        if residual.victims_ack.strip() and path not in victims_by_path:
            out.append(
                f"`MENU_READ_PARITY_RESIDUALS['{path}'].victims_ack` 声称认领了 403 受害者，"
                "但逐岗位复算**一个都没有** ⇒ 陈旧认领，删掉它（否则它会替未来的真受害者放行）"
            )

    # ⑤ 多端点页的**结构性**登记（#5675 收口包）：判据 12 的命题只在「第一屏恰好一个读端点码」的
    #    页面上适定。并发多码的页面必须具名，且码集**逐值冻结** —— 这一段的判别力形态是
    #    「某页悄悄多/少一个第一屏码」（节点码恰好命中新码时 ③ 一声不响 ⇒ 只有这里看得见）。
    #    🔴 本段**不是豁免**：它放行的每一条都仍受 ③（不一致即登记）与 ④（受害者认领）管辖。
    live_multi = {p: set(c) for p, c in endpoint_codes_by_path.items() if len(c) >= 2}
    for path in sorted(set(live_multi) - set(MULTI_READ_ENDPOINT_PAGES)):
        out.append(
            f"`{path}` 的第一屏现取到 {sorted(live_multi[path])} —— **多个不同码**，但没登记在 "
            "`MULTI_READ_ENDPOINT_PAGES` ⇒ 多端点页必须具名（判据 12 的「节点码 ≡ 那**一个**读端点码」"
            "命题对多端点页不适定；本表登记**结构事实**、不是豁免，不一致仍须进 "
            "`MENU_READ_PARITY_RESIDUALS`）"
        )
    for path in sorted(set(MULTI_READ_ENDPOINT_PAGES) - set(live_multi)):
        if path not in by_path:
            out.append(
                f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 的 path 已不在 `config/menu.ts` ⇒ 删掉本条"
                "（结构性登记也**只许缩短**）"
            )
        elif path in endpoint_codes_by_path:
            out.append(
                f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 已**不再并发多码**（该页第一屏现取 "
                f"{sorted(endpoint_codes_by_path[path])}）⇒ **删掉这条登记**"
                "（陈旧的结构性登记会把下一次真漂移读成「已登记」）"
            )
        # path 在菜单里、却没有现取码（锚点段已红）⇒ 本段不重复报，避免给出错误读数。
    for path, entry in sorted(MULTI_READ_ENDPOINT_PAGES.items()):
        node = by_path.get(path)
        if node is not None and node.name != entry.node:
            out.append(
                f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 指的是『{entry.node}』，而 `config/menu.ts` "
                f"该 path 现在是『{node.name}』（路径↔节点漂移 ⇒ 锚错人）"
            )
        live = live_multi.get(path)
        if live is not None and live != set(entry.codes):
            out.append(
                f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 登记的码集 {sorted(entry.codes)} 与**现取** "
                f"{sorted(live)} 不符 ⇒ 同步登记（多一个 / 少一个都必须有人看一眼：这页的"
                "「第一屏读端点码集」变了）"
            )
        empty = [name for name, value in (("reason", entry.reason), ("owner", entry.owner))
                 if not value.strip()]
        if empty:
            out.append(f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 缺字段 {empty}（理由/谁负责缺一即红）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据 13 的专属面：**注释里的「计数 / 点名」声明 ≡ 代码现值**（#5675 收口包）
# ══════════════════════════════════════════════════════════════════════════════
#
# 病根（本单实测两例，形态完全相同）：说明文字**先写对**、代码**后来变了**，而**没有任何东西会红**——
#   ① `RegistrationService` 的生产域读码目录写「四个侧边栏节点、四个页面的读端点、以及 8 个只读工具」：
#      端点那一半**从来就不成立**（#5291 只搬了两个），工具那一半 **8 → 9** 也漂了（且没有判据守着它）；
#   ② `StockBatchController` 的类 javadoc 写「四个读面……另有一个消耗台账分页端点」：
#      该控制器今天有 **7 个** GET 端点（#5159 的两个省料端点根本没被写进去）。
# 两句都是**给后来人读的**，而后来人（#5675 的包）正是照第 ① 句把归因写成了「#5291 漏改」——
# **一次漂移的注释 = 下一次误判的输入**。
#
# 🔴 与 #5272「注释不是代码」**不冲突**（方向相反）：那条禁止把注释当权限声明**读**；
# 本条的对象**就是注释文本本身**，真值在**代码**那一侧 —— 读注释是为了**证伪**注释，不是拿它当证据。
#
# ⚠️ 覆盖面（如实登记，不粉饰）：**只覆盖已登记的声明** —— 本表是**策展**清单，不是全仓扫描。
# 全仓按「N 个……」扫会命中大量叙述句与**引用的历史文本**（例如本单同时改准的那段「本段曾写……」），
# 噪声会把判据淹掉；**未登记的计数声明不在射程**（这就是本判据的边界）。


@dataclass(frozen=True)
class CommentClaim:
    """一条注释声明的登记：`anchor` 是它在源码里的**逐字锚**，`kind` + `arg` 决定**现取**怎么复核它。"""

    source: str
    anchor: str
    kind: str
    arg: object
    why: str


#: 本单（#5675 收口包）**逐条复核过**、并从此**钉住**的注释声明。
#: 新增条目 = 声明「这段文字的条数/点名必须与代码一致」；改动被钉的代码 ⇒ 这里立刻红。
COMMENT_CLAIMS: tuple[CommentClaim, ...] = (
    CommentClaim(
        source="java:service/RegistrationService.java",
        anchor="① **四个侧边栏节点**",
        kind="menu-node-count",
        arg=("production:view", 4),
        why="生产域读码的四个侧边栏节点（生产看板 / 加工项管理 / 工艺配置 / 计件工资）",
    ),
    CommentClaim(
        source="java:service/RegistrationService.java",
        anchor="**两个**只读端点：`/operations-catalog`、`/routings`",
        kind="endpoint-code",
        arg=(("GET", "/api/admin/production/operations-catalog"),
             ("GET", "/api/admin/production/routings"), "production:view"),
        why="#5291 声称只搬了这两个只读端点 —— 点名的端点必须真的存在、且真的挂该读码",
    ),
    CommentClaim(
        source="java:service/RegistrationService.java",
        anchor="**不写死条数**",
        kind="no-hardcoded-count",
        arg=(r"[0-9]+ ?个只读工具",),
        why="承载该码的只读工具条数会随工具增删变化（实测 8→9）⇒ 这段刻意不写数字；写回来即红",
    ),
    CommentClaim(
        source="java:controller/ProductionController.java",
        anchor="两个**只读**端点（{@code /operations-catalog}、{@code /routings}）",
        kind="endpoint-code",
        arg=(("GET", "/api/admin/production/operations-catalog"),
             ("GET", "/api/admin/production/routings"), "production:view"),
        why="同一份声明在 `ProductionController` 的类注记里也有一份（两处都得能被现取复核）",
    ),
    CommentClaim(
        source="java:controller/ProductionController.java",
        anchor="授了 4 个岗位",
        kind="seed-role-count",
        arg=("order:list", 4),
        why="「打印计数沿用类级 order:list」的理由里那个岗位数（非 admin 的内置岗位）",
    ),
    CommentClaim(
        source="java:controller/StockBatchController.java",
        anchor="**7 个 GET 端点**",
        kind="get-endpoint-count",
        arg=("/api/admin/batch-stock/", 7),
        why="该控制器的读面条数（本单改准：原写「四个读面……另有一个」而实测 7 个）",
    ),
)


def problems_comment_claims(w: World) -> list[str]:
    """判据 13：注释里的声明必须能被**现取**复核（漂移 / 锚被改写 / 违规数字 ⇒ 红）。

    四类出口（都只读源码文本 ⇒ 与判据 12 同款、零依赖）：
      · `menu-node-count`：声明「N 个节点」⇒ 与 `menu.ts` 现取的同码节点数比；
      · `get-endpoint-count` / `seed-role-count`：与端点表 / 种子矩阵的现取计数比；
      · `endpoint-code`：注释**点名**的端点必须存在，且生效码逐值等于声明值；
      · `no-hardcoded-count`：该处**刻意不写死**的条数，若被写回来（匹配 `arg` 的正则）即红。
    锚找不到 ⇒ 也是红（声明被改写/删除却没同步登记 —— 否则本表会静默过期）。
    """
    out: list[str] = []
    menu_nodes = parse_menu_ts_nodes(w.sources["menu:frontend"])
    for claim in COMMENT_CLAIMS:
        text = w.sources.get(claim.source)
        if text is None:
            out.append(f"判据 13 的登记指向的源不在源码表里：`{claim.source}`（路径漂移 ⇒ 红）")
            continue
        idx = text.find(claim.anchor)
        if idx == -1:
            out.append(
                f"判据 13：「{claim.anchor}」这条声明在 `{claim.source}` 里已找不到**逐字锚** "
                f"⇒ 它被改写/删除却没有同步登记（{claim.why}）"
            )
            continue
        if claim.kind == "menu-node-count":
            code, expected = claim.arg
            live = sum(1 for n in menu_nodes if n.code == code)
            if live != expected:
                out.append(
                    f"判据 13：`{claim.source}` 声明「{claim.anchor}」= {expected} 个，而 `menu.ts` 里 "
                    f"code == `{code}` 的节点**现值 {live} 个** ⇒ 注释与代码不符（{claim.why}）"
                )
        elif claim.kind == "endpoint-code":
            *eps, code = claim.arg
            for verb, path in eps:
                got = w.all_eps.get((verb, path))
                codes = sorted({e.permission for e in got}) if got else None
                if codes is None:
                    out.append(f"判据 13：注释点名的 `{verb} {path}` 在 admin-api 里**查不到** ⇒ 点名失实（{claim.why}）")
                elif code not in codes:
                    out.append(
                        f"判据 13：注释点名 `{verb} {path}` 声称挂 `{code}`，**现值 {codes}** "
                        f"⇒ 声明与代码不符（{claim.why}）"
                    )
        elif claim.kind == "no-hardcoded-count":
            (pattern,) = claim.arg
            # 扫**该声明的本行与上一行**（不含其后）：后面常是**引用的历史文本**
            # （本单实测：留档那句「本段曾写……8 个只读工具……」会把本判据**喂红** ——
            #   §17.3「判据被自己的文案喂红」的同款，故射程刻意收在声明本行 + 上一行）。
            line_start = text.rfind("\n", 0, idx) + 1
            prev_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
            line_end = text.find("\n", idx)
            span = text[prev_start: line_end if line_end != -1 else len(text)]
            if re.search(pattern, span):
                out.append(
                    f"判据 13：`{claim.source}` 的「{claim.anchor}」所在两行里出现了**写死的条数**"
                    f"（匹配 `{pattern}`）⇒ 它没有判据守着、只会腐烂（{claim.why}）"
                )
        elif claim.kind == "get-endpoint-count":
            prefix, expected = claim.arg
            live = sum(1 for (verb, path) in w.all_eps if verb == "GET" and path.startswith(prefix))
            if live != expected:
                out.append(
                    f"判据 13：`{claim.source}` 声明「{claim.anchor}」= {expected} 个，而 `{prefix}` 前缀下"
                    f"的 GET 端点**现值 {live} 个** ⇒ 注释与代码不符（{claim.why}）"
                )
        elif claim.kind == "seed-role-count":
            code, expected = claim.arg
            live = len([r for r, codes in w.roles.items() if r != "admin" and code in codes])
            if live != expected:
                out.append(
                    f"判据 13：`{claim.source}` 声明「{claim.anchor}」= {expected} 个内置岗位持 `{code}`，"
                    f"**现取 {live} 个** ⇒ 注释与代码不符（{claim.why}）"
                )
        else:
            out.append(f"判据 13：登记里的 kind `{claim.kind}` 未知（登记写错 ⇒ 本判据对它是空跑）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据 14 的专属面：**同一岗位默认权限写在两处** ⇒ 逐值不变量 + 授权变更 census（issue #5683）
# ══════════════════════════════════════════════════════════════════════════════
#
# 病根（**类级**，不是一个实例）：同一个岗位的默认权限被写在**两处** ——
#   ① 种子矩阵 `RegistrationService.initializeDefaultRolesAndPermissions`（新租户建租户时写
#      `role_permissions`）；
#   ② 回退 switch `RoleService.getPermissionCodesForRole`（无 `role_permissions` 记录的历史账号走它）。
# 两处**靠注释维持同步**，而注释不会被任何判据读 ⇒ 历史上已分叉**两轮**（issue #5246、#5291），
# 到 issue #5683 实测 `operator` 在回退里**少 4 个码**（`processing:view` / `processing:update` /
# `inbound:view` / `inbound:create`），显形形态是**真实 403** 与**菜单凭空消失**。
# ⚠️ 分叉当时，那处注释逐字写着「与种子矩阵逐值同步」—— 这正是本仓反复出现的缺陷类：
# **判据读到的文本与它声称的对象不是同一个**（把注释当声明读）。
# ⇒ 本判据把那句话变成**机器可读的不变量**：两处对同一角色码**逐值相等**，未登记差异即红。
#
# 🔴 **明确的边界（不要把本判据读成覆盖面更大）** —— 不登记的限制就是未来的空断言：
#   ① **只覆盖「两处都有定义」的角色码**。历史遗留岗位（`LEGACY_ROLES_IN_FALLBACK` 里的
#      `product_manager` / `knowledge_editor`）**不在种子矩阵里** ⇒ 「两处逐值相等」这个命题对它们
#      **不适定**（没有第二处可比）⇒ ① 段对它们的取值**一声不响**；它们的可达面变化由 ② 段的
#      **授权变更 census** 承担（`FALLBACK_BASELINE_BEFORE_5683` 把 `product_manager` 也冻在里面）。
#   ② **只解析源码文本**：种子面靠 `parse_role_defaults` 读 `attachDefaultPermissions(…List.of(…))`
#      与 `permissionByCode.keySet()`，回退面靠 `parse_role_fallback` 读 `case "x" -> List.of(…)`。
#      换形态（把种子挪进 SQL/YAML、把 switch 改成 Map、用常量变量拼列表）⇒ 解析面**读不到** ——
#      届时由各自的 fail-closed 断言兜（`len(out) >= 5`、方法找不到即红），不是静默通过。
#   ③ **不判「值本身对不对」**：两处一起把某个码写错（都多 / 都少）本判据**看不出来** ——
#      那一半由判据 2/3/4/10 承担（工具码 ≡ 端点码 ≡ 菜单节点码 / 零权限泄露 / 读码四面锚定）。
#   ④ **运行时快照面不在射程**：`users.permissions`（员工级快照，按设计**与岗位脱钩**）与租户
#      **自建岗位**的 `role_permissions` 都不是本判据的来源 —— 只判「内置岗位的两处默认定义」。


@dataclass(frozen=True)
class RoleFallbackDivergence:
    """一个角色码上「种子矩阵 ↔ 硬编码回退」的逐值差异（issue #5683 的**只许缩短**台账条目）。"""

    #: 种子有、回退无 —— 回退路径上的账号**少拿到** ⇒ 「菜单看得见、点进去 403」的形态。
    missing: frozenset[str]
    #: 回退有、种子无 —— **真放宽**（回退绕过岗位权限页）。🔴 本判据**不给它登记出口**：
    #: 字段在这里只为「逐值冻结」的比对形态完整，非空即红。
    extra: frozenset[str]
    reason: str
    owner: str
    issue: str


#: 🔴 **只许缩短的差异台账**（issue #5683）：种子矩阵 ↔ 硬编码回退逐值对照后**仍存**的差异。
#: 三条机械约束（都在 `problems_role_default_parity` 里判）：
#:   ① **未登记即红**：现取到的任何差异（多授 / 少授）必须在此具名；
#:   ② **逐值冻结**：登记项的 `missing` / `extra` 必须与**现取**逐值相同 —— 多一个、少一个都红
#:      （「差异悄悄变大」与「差异悄悄变小却不销账」都不许静默）；`extra` 非空则**无条件红**；
#:   ③ **陈旧即红**：差异已消失而条目还在 ⇒ 红（逼人删掉它 ⇒ 台账只会变短，**销账是必须动作**）。
#: 条数上限 `ROLE_FALLBACK_DIVERGENCE_CEILING` **现取**（只许缩短）。
#:
#: 今天在册的三条 = 客服 / 销售 / 财务「种子有码、回退**没有 case**（落 `default` ⇒ 空表）」。
#: 它们是**超出 #5683 已批准范围**的更大一处授权变更（补码 = 让这三个岗位的历史账号从**零权限**
#: 变成有权限），#5683 **只量化、只提请裁定**，故**有意留在台账里**，由人类裁定后另行销账。
ROLE_FALLBACK_DIVERGENCES: dict[str, RoleFallbackDivergence] = {
    "customer_service": RoleFallbackDivergence(
        missing=frozenset({
            "after_sales:view", "agent:session", "agent:session:manage", "customer:view",
            "dashboard:view", "inbound:view", "knowledge:view", "order:detail", "order:list",
            "processing:view",
        }),
        extra=frozenset(),
        reason=(
            "回退 switch**没有** `case \"customer_service\"` ⇒ 落 `default` ⇒ **空表**：持该角色码且"
            "无 `role_permissions` 记录 / 无权限快照的历史账号**零权限**（连「经营看板」都看不见），"
            "而种子给同一岗位授了 10 个码。补它 = 把这批历史账号从零权限放到有权限 = **改授权**，"
            "**超出 #5683 用户已批准的范围**（#5683 只批了 operator / product_manager）⇒ 只量化、"
            "提请人类裁定，本单**不改**。"
        ),
        owner="岗位权限面（RoleService 回退 switch 的 default 分支）+ 待人类裁定（#5683 ④）",
        issue="#5683",
    ),
    "sales": RoleFallbackDivergence(
        missing=frozenset({
            "customer:view", "dashboard:view", "inbound:view", "order:detail", "order:list",
            "processing:view", "product:list",
        }),
        extra=frozenset(),
        reason=(
            "同客服：回退 switch 没有 `case \"sales\"` ⇒ 空表，历史账号零权限；种子授了 7 个码。"
            "补它同属**超出已批准范围**的授权放宽 ⇒ 只量化、提请裁定，本单**不改**。"
        ),
        owner="岗位权限面（RoleService 回退 switch 的 default 分支）+ 待人类裁定（#5683 ④）",
        issue="#5683",
    ),
    "finance": RoleFallbackDivergence(
        missing=frozenset({
            "dashboard:view", "finance:create", "finance:view", "inbound:view", "order:detail",
            "order:list", "processing:view",
        }),
        extra=frozenset(),
        reason=(
            "同客服：回退 switch 没有 `case \"finance\"` ⇒ 空表，历史账号零权限；种子授了 7 个码。"
            "补它同属**超出已批准范围**的授权放宽 ⇒ 只量化、提请裁定，本单**不改**。"
        ),
        owner="岗位权限面（RoleService 回退 switch 的 default 分支）+ 待人类裁定（#5683 ④）",
        issue="#5683",
    ),
}

#: 差异台账的**现取**条数上限（只许缩短）：今天 = 3（客服 / 销售 / 财务）。
ROLE_FALLBACK_DIVERGENCE_CEILING = 3

#: issue #5683 **生效前**的回退集合逐值冻结（`git show origin/main:<path>` 的读数，2026-09-27）——
#: 「本单新增了哪些码」= 现取 − 本基线：不许靠提交信息或人的记忆去记（那是不可复算的）。
#: 🔴 本基线是**历史事实**，任何后续改动都**不得**改它（要记新变更就另开一段基线）。
FALLBACK_BASELINE_BEFORE_5683: dict[str, frozenset[str]] = {
    "operator": frozenset({
        "after_sales:view", "agent:session", "agent:session:manage", "customer:create",
        "customer:view", "dashboard:view", "employee:list", "finance:create", "finance:view",
        "knowledge:view", "order:create", "order:detail", "order:list", "order:refund",
        "order:update", "processing:manage", "product:category", "product:category:view",
        "product:create", "product:list", "production:view",
    }),
    "product_manager": frozenset({
        "dashboard:view", "processing:manage", "product:category", "product:category:view",
        "product:create", "product:list", "production:view",
    }),
}


@dataclass(frozen=True)
class AuthorizationCensusEntry:
    """一个**被新增**到回退集合的权限码 → 它使哪些面变为可达（#5683 硬约束 2：给不出就不许合并）。"""

    #: 哪些岗位码的回退集合里新增了它（逐值比对现取 —— 多写 / 少写都红）。
    roles: tuple[str, ...]
    #: 生效码 == 本码的 admin-api 端点（`VERB 路径`，路径用 `{}` 表模板）。必须非空。
    endpoints: tuple[str, ...]
    #: 挂本码的菜单节点（`<菜单源>:<节点名>`）。无节点 ⇒ 空（本码不决定任何菜单可见性）。
    menu_nodes: tuple[str, ...]
    #: 声明本码的 B 端 Agent 工具。无 ⇒ 空（Agent 面不因本码变宽）。
    tools: tuple[str, ...]
    #: 为什么「现在可达」（给人读的理由；机械判据**不依赖**它，故它写错不会假绿）。
    reachable: str


#: 🔴 **授权变更 census**（issue #5683 硬约束 2）：回退集合**新增**的每个码逐条列出「哪些端点 /
#: 菜单节点 / Agent 工具因此变为可达」。机械判据（`problems_role_default_parity` ② 段）：
#:   · 新增了码却没登记 ⇒ **红**；登记了并没真新增的码 ⇒ **红**（陈旧）；
#:   · 登记的岗位集必须 == 现取；列的端点必须真存在**且生效码就是本码**；菜单节点同理；工具同理。
#: 于是「补码」这件事不可能悄悄发生 —— 每一个码都必须同时交代它打开了哪几扇门。
AUTHORIZATION_CENSUS: dict[str, AuthorizationCensusEntry] = {
    "processing:view": AuthorizationCensusEntry(
        roles=("operator", "product_manager"),
        endpoints=("GET /api/admin/production/pool", "POST /api/admin/production/pool/preview"),
        menu_nodes=(),
        tools=(),
        reachable=(
            "「智能派单」页（`/production/pool`）的第一屏读端点 `GET /api/admin/production/pool` 要本码，"
            "而**节点码是 `processing:manage`** ⇒ 补本码前：回退账号（持管理码）**菜单看得见、点进去 403**；"
            "补本码后该页可读。本码**不挂任何菜单节点**（`menu.ts` 里无节点用它）⇒ 补它**不改变任何菜单的"
            "可见性**，只把已有节点背后的 API 打通 —— 这正是「补读码」方向不需要连带改节点码的原因。"
        ),
    ),
    "processing:update": AuthorizationCensusEntry(
        roles=("operator",),
        endpoints=(
            "PATCH /api/admin/processing-orders/{}",
            "POST /api/admin/processing-orders/generate",
            "POST /api/admin/production/pool/dispatch",
        ),
        menu_nodes=(),
        tools=("processing_order_generate", "processing_order_update"),
        reachable=(
            "加工单更新 / 生成、派单执行三个写端点改用本码判定 ⇒ 补码前回退账号在「加工项管理」"
            "与「智能派单」上**改不了单**（种子路径的新账号能改）；另有两个 B 端 Agent 工具"
            "（`processing_order_update` / `processing_order_generate`）声明本码 ⇒ Agent 面对回退账号"
            "由「拿不到权限」变为「可写」。"
        ),
    ),
    "inbound:view": AuthorizationCensusEntry(
        roles=("operator",),
        endpoints=(
            "GET /api/admin/inbound-orders",
            "GET /api/admin/inbound-orders/batches",
            "GET /api/admin/inbound-orders/{}",
        ),
        menu_nodes=("frontend:入库单", "controller:入库单", "auth:入库单"),
        tools=("inbound_order_query",),
        reachable=(
            "「入库单」菜单节点的**节点码就是本码**（三处菜单源一致）⇒ 补码前回退账号**根本看不见该节点**"
            "（issue #5271 新增的页面 = 菜单凭空消失）；补码后节点出现且三个读端点同时可读。"
            "Agent 侧 `inbound_order_query`（只读）同批对回退账号开放。"
        ),
    ),
    "inbound:create": AuthorizationCensusEntry(
        roles=("operator",),
        endpoints=(
            "GET /api/admin/inbound-orders/opening-template",
            "PATCH /api/admin/inbound-orders/{}",
            "POST /api/admin/inbound-orders",
            "POST /api/admin/inbound-orders/opening-import",
        ),
        menu_nodes=(),
        tools=(),
        reachable=(
            "建单 / 改单 / 期初导入三个写端点（外加期初模板读端点，注解口径如实照录）改用本码 ⇒ "
            "补码前回退账号进得去「入库单」页（若已持 `inbound:view`）却**建不了单**；"
            "补码后与种子路径的运营同权。本码不挂菜单节点、无 Agent 工具声明它。"
        ),
    ),
}


def problems_role_default_parity(w: World) -> list[str]:
    """判据 14：**同一岗位默认权限写在两处** ⇒ 逐值不变量 + 授权变更 census（issue #5683）。

    两段（缺任何一段这条判据都有一个漏网形态）：
      ① **不变量**：对**每一个**种子角色码，`种子[role]` 与 `回退[role]` 逐值相等；不等必须具名
         登记在 `ROLE_FALLBACK_DIVERGENCES`（台账只许缩短：多一个 / 少一个 / 差异消失而条目还在
         ⇒ 都红；`extra` 非空 ⇒ **无条件红**，不提供登记出口）。
      ② **授权变更 census**：本单**新增**的每个码必须逐条给出「哪些端点 / 菜单节点 / Agent 工具
         因此变为可达」，且登记与代码**逐值相符**（少列一个新增码 ⇒ 红；列了没真加上去的码 ⇒ 红；
         列的端点生效码不是本码 ⇒ 红）。
    """
    out: list[str] = []
    # ── ① 不变量：**穷举**逐一对照（不抽样） ──
    # 回退面「没有 case」不等于「没有差异」：运行时会落 `default -> List.of()` ⇒ 口径是**空表**。
    live: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for role in sorted(set(w.roles) | set(w.role_fallback)):
        seeded = w.roles.get(role)
        if seeded is None:
            continue                      # 只有回退一份定义（历史遗留岗位）⇒ 命题不适定，见 docstring ①
        if "*" in seeded:
            continue                      # admin：`*` 是通配（恒为全部权限），集合不可逐值比较
        fallback = frozenset(w.role_fallback.get(role, frozenset()))
        live[role] = (frozenset(seeded - fallback), frozenset(fallback - seeded))

    for role, (missing, extra) in sorted(live.items()):
        if extra:
            out.append(
                f"🔴 岗位 `{role}` 的**硬编码回退多出**种子矩阵没有的码 {sorted(extra)} ⇒ **真放宽**"
                "（回退路径绕过岗位权限页）。本判据**不给这条登记出口**：回退集合里不得出现种子"
                "（= 权限目录）没有的码"
            )
        entry = ROLE_FALLBACK_DIVERGENCES.get(role)
        if not missing and not extra:
            if entry is not None:
                out.append(
                    f"`ROLE_FALLBACK_DIVERGENCES['{role}']` 已**不再有差异**（两处现逐值相等）"
                    "⇒ **删掉这条登记**（台账只许缩短；陈旧条目会把下一次真分叉读成「已登记」）"
                )
            continue
        if entry is None:
            out.append(
                f"岗位 `{role}` 的默认权限在**两处已经分叉**且未登记：少授（种有回退无）{sorted(missing)} / "
                f"多授（回退有种子无）{sorted(extra)} ⇒ 同一岗位「有权限快照的账号」与「无快照的历史账号」"
                "行为不同（真实 403 / 菜单凭空消失）。**要么补齐两处，要么在 "
                "`ROLE_FALLBACK_DIVERGENCES` 里具名登记（差异集 + 理由 + 谁负责 + 单号）**"
            )
        elif entry.missing != missing or entry.extra != extra:
            out.append(
                f"`ROLE_FALLBACK_DIVERGENCES['{role}']` 登记的差异与**现取**不符："
                f"missing 登记 {sorted(entry.missing)} / 现取 {sorted(missing)}；"
                f"extra 登记 {sorted(entry.extra)} / 现取 {sorted(extra)} ⇒ 同步登记"
                "（差异集**逐值冻结**：多一个 / 少一个都必须有人看一眼）"
            )
    for role in sorted(set(ROLE_FALLBACK_DIVERGENCES) - set(live)):
        out.append(
            f"`ROLE_FALLBACK_DIVERGENCES['{role}']` 已**不再有差异**（两处现逐值相等，或该角色码"
            "已不在比对面内）⇒ **删掉这条登记**（台账只许缩短；陈旧条目会把下一次真分叉读成「已登记」）"
        )
    for role, entry in sorted(ROLE_FALLBACK_DIVERGENCES.items()):
        empty = [n for n, v in (("reason", entry.reason), ("owner", entry.owner), ("issue", entry.issue))
                 if not v.strip()]
        if empty:
            out.append(f"`ROLE_FALLBACK_DIVERGENCES['{role}']` 缺字段 {empty}（理由 / 谁负责 / 单号缺一即红）")
    if len(ROLE_FALLBACK_DIVERGENCES) > ROLE_FALLBACK_DIVERGENCE_CEILING:
        out.append(
            f"差异台账**又长回来了**：现有 {len(ROLE_FALLBACK_DIVERGENCES)} 条 > 上限 "
            f"{ROLE_FALLBACK_DIVERGENCE_CEILING} ⇒ 台账**只许缩短**（新增一条差异不是「登记一下」"
            "就能过关的，得先有人裁定这次授权变更）"
        )

    # ── ② 授权变更 census：新增的码逐条给出「打开了哪几扇门」 ──
    added: dict[str, set[str]] = {}
    for role, before in FALLBACK_BASELINE_BEFORE_5683.items():
        now = frozenset(w.role_fallback.get(role, frozenset()))
        for code in sorted(now - before):
            added.setdefault(code, set()).add(role)
    for code in sorted(set(added) - set(AUTHORIZATION_CENSUS)):
        out.append(
            f"回退集合里**新增了**码 `{code}`（岗位 {sorted(added[code])}），但没有登记在 "
            "`AUTHORIZATION_CENSUS` ⇒ 授权变更必须逐条给出「哪些端点 / 菜单节点 / Agent 工具因此变为"
            "可达」（#5683 硬约束 2：给不出 census 就不许合并）"
        )
    by_name = _by_name(w)
    for code, entry in sorted(AUTHORIZATION_CENSUS.items()):
        roles_now = added.get(code)
        if roles_now is None:
            out.append(
                f"`AUTHORIZATION_CENSUS['{code}']` 的码**并没有**被新增到任何回退集合里 ⇒ 陈旧登记，"
                "删掉它（否则 census 会替一次不存在的授权变更背书）"
            )
            continue
        if set(entry.roles) != roles_now:
            out.append(
                f"`AUTHORIZATION_CENSUS['{code}']` 登记的岗位 {sorted(entry.roles)} 与**现取** "
                f"{sorted(roles_now)} 不符 ⇒ 同步登记（census 说的「谁被放宽了」必须与代码一致）"
            )
        if not entry.reachable.strip():
            out.append(f"`AUTHORIZATION_CENSUS['{code}']` 缺 `reachable`（为什么现在可达 —— 人读的理由）")
        if not entry.endpoints:
            out.append(
                f"`AUTHORIZATION_CENSUS['{code}']` 一个端点都没列 ⇒ census 的核心就是「因此变为可达的面」，"
                "空 census = 给不出 census"
            )
        for key in entry.endpoints:
            verb, _, path = key.partition(" ")
            eps = w.all_eps.get((verb, path))
            if eps is None:
                out.append(
                    f"`AUTHORIZATION_CENSUS['{code}']` 列的端点 `{key}` 在 admin-api 端点表里查不到"
                    "（路径漂移 / 该端点不存在 ⇒ 红）"
                )
                continue
            codes = sorted({str(ep.permission) for ep in eps})
            if codes != [code]:
                out.append(
                    f"`AUTHORIZATION_CENSUS['{code}']` 列的端点 `{key}` 生效码实为 {codes} ≠ `{code}` ⇒ "
                    "census 与代码不一致（census 必须逐条是**这个码**打开的面）"
                )
        for key in entry.menu_nodes:
            src, _, node = key.partition(":")
            if w.menus.get(src, {}).get(node) != code:
                out.append(
                    f"`AUTHORIZATION_CENSUS['{code}']` 列的菜单节点 `{key}` 实挂 "
                    f"`{w.menus.get(src, {}).get(node)}` ≠ `{code}`（或该节点已不在该菜单源里）"
                )
        for name in entry.tools:
            tool = by_name.get(name)
            if tool is None:
                out.append(f"`AUTHORIZATION_CENSUS['{code}']` 列的工具 `{name}` 不存在（改名 / 删除 ⇒ 红）")
            elif code not in (tool.required_permissions or ()):
                out.append(
                    f"`AUTHORIZATION_CENSUS['{code}']` 列的工具 `{name}` 并未声明本码 "
                    f"（现声明 {sorted(tool.required_permissions or ())}）"
                )
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
    "10 · 三个域读码的锚定（issue #5291）": problems_read_code_anchoring,
    "11 · 页面守卫前缀序 + 码锚定（issue #5291）": problems_route_guard,
    "12 · 菜单节点码 ≡ 页面第一屏读端点码（issue #5675）": problems_menu_read_parity,
    "13 · 注释里的计数/点名声明 ≡ 代码现值（#5675 收口）": problems_comment_claims,
    "14 · 岗位默认权限两处定义的不变量 + 授权变更 census（issue #5683）": problems_role_default_parity,
}


# ══════════════════════════════════════════════════════════════════════════════
# 五、断言（每条判据一条；全部绿 = 本单的四集合互相对账成立）
# ══════════════════════════════════════════════════════════════════════════════


def test_every_judgement_is_green() -> None:
    """全部判据在**当前仓库**上全绿（红 = 权限面已经漂移，逐条问题见断言文案）。"""
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


def _shadow_production_subpaths(text: str) -> str:
    """判据 11 ① 的注入：把 `/production`（**更宽**）挪到 `/production/pool` 之前。

    这是 #5291 的**顺序回归形态**（不是改一个字的假变异）：`find()` 先命中 `/production`
    ⇒ `/production/pool|remnants|saving-board` 三个**管理码**页面全部按读码判定。
    """
    wide = "  { prefix: '/production', code: 'production:view' },\n"
    assert wide in text, "注入锚点失配：找不到 `/production` 那一行（同步本判据）"
    pool = "  { prefix: '/production/pool', code: 'processing:manage' },\n"
    assert pool in text, "注入锚点失配：找不到 `/production/pool` 那一行（同步本判据）"
    return text.replace(wide, "", 1).replace(pool, wide + pool, 1)


def _swap(text: str, old: str, new: str) -> str:
    """判据 12 的注入：**整段换/删**（`old` 出现次数 ≠ 1 ⇒ 注入锚点失配，必须同步本判据）。"""
    assert text.count(old) == 1, f"注入锚点失配（出现 {text.count(old)} 次）：{old!r}"
    return text.replace(old, new, 1)


def _fallback_case_span(text: str, role: str) -> tuple[int, int]:
    """`RoleService` 回退 switch 里 `case "<role>" -> List.of(` … `);` 的区间（判据 14 的注入锚点）。"""
    anchor = f'case "{role}" -> List.of('
    idx = text.find(anchor)
    assert idx != -1, f"注入锚点失配：找不到 `{anchor}`（同步本夹具）"
    end = text.find(");", idx)
    assert end != -1, "注入锚点失配：找不到该 case 的 `List.of(...)` 结尾"
    return idx, end


def _drop_fallback_code(text: str, role: str, code: str) -> str:
    """从 `RoleService` 的某个回退 `case` 里删掉一个码（判据 14 的注入面）。

    只删**非注释行**里的码（`#5323`：注释里的码不是声明）—— 否则注入会打在注释上，
    「注入没生效」与「判据不红」将无法区分（那正是空断言的形态）。
    """
    idx, end = _fallback_case_span(text, role)
    head, block, tail = text[:idx], text[idx:end], text[end:]
    lines, removed = [], 0
    for line in block.split("\n"):
        if removed == 0 and not line.lstrip().startswith("//") and f'"{code}"' in line:
            line = re.sub(rf'"{re.escape(code)}"\s*,?\s*', "", line, count=1)
            removed += 1
        lines.append(line)
    assert removed == 1, f'注入锚点失配：`case "{role}"` 的代码行里没有 `{code}`（同步本夹具）'
    return head + "\n".join(lines) + tail


def _add_fallback_code(text: str, role: str, code: str) -> str:
    """往 `RoleService` 的某个回退 `case` 的列表**开头**加一个码（判据 14 的注入面）。"""
    idx, _end = _fallback_case_span(text, role)
    at = text.find("List.of(", idx)
    assert at != -1, "注入锚点失配：该 case 里找不到 `List.of(`"
    at += len("List.of(")
    return text[:at] + f'\n                    "{code}",' + text[at:]


def _injections() -> dict[str, tuple[str, "callable", "callable"]]:
    """`label` → (被判据读取的源键, 文本变异, 目标判据)。"""
    return {
        # ── 判据 14（issue #5683）：同一岗位默认权限写在两处 ⇒ 逐值不变量 ──
        # 三条注入分别打在不变量段与不变量的两个方向（少授 / 多授）上：
        "⑭a 从**回退**里删掉一个码（operator − processing:view）⇒ 判据 14 红": (
            "java:service/RoleService.java",
            lambda s: _drop_fallback_code(s, "operator", "processing:view"),
            problems_role_default_parity,
        ),
        "⑭b 从**种子**里删掉一个码（operator − processing:view）⇒ 判据 14 红": (
            "java:service/RegistrationService.java",
            lambda s: _drop_role_code(s, "operatorRole", "processing:view"),
            problems_role_default_parity,
        ),
        "⑭c 往回退里加一个**种子没有的**码（operator += ghost:code）⇒ 判据 14 红": (
            "java:service/RoleService.java",
            lambda s: _add_fallback_code(s, "operator", "ghost:code"),
            problems_role_default_parity,
        ),
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
        "③ 岗位拿到页内读码却没有该页读码（finance += product:category:view）⇒ 判据 4 红": (
            # 锚点口径（issue #5247 改判）：注入的码**必须是「某个 B 端可达工具仍声明的码」**
            # —— 判据 4 只看 `declared`（B 端工具声明的码）∩ 岗位权限。
            # 原锚 `employee:create` 在 #5247 收窄 `employee_manage` 后**不再被任何 B 端工具声明**
            # ⇒ 判据 4 恒不报（红证空转，由 `test_every_judgement_can_go_red` 抓到，故改锚）。
            # 现锚（issue #5291 改判）：`product:category:view` —— 由只读工具 `category_manage` 声明，
            # 且经 `PAGE_READ_CODES` 归属「商品列表」页 ⇒ 财务岗没有 `product:list`（该页读码）
            # ⇒ 「Agent 拿得到、页面里看不见」成立。原锚 `product:category` 随读码拆分**退出声明面**
            #（工具不再声明它）⇒ 那时本注入会变成空断言，故同批改锚。
            "java:service/RegistrationService.java",
            lambda s: _add_role_code(s, "financeRole", "product:category:view"),
            problems_leakage,
        ),
        "③b 码没有任何菜单节点（改掉『售后工单』节点码）⇒ 判据 4 红": (
            # 锚点口径（issue #5247 改判）：**被改的节点码必须是「某个 B 端可达工具仍声明的码」**，
            # 否则判据 4 连这个码都不看（原锚改成的 `order:refund` 随 `after_sales_manage`
            # 收窄而退出 B 端声明面 ⇒ 注入变空断言）。现锚改成的 `order:list` 仍是 B 端声明码
            # （`order_query`/`logistics_track`），且改完后 `after_sales:view` 在四处菜单源里
            # **一个节点都没有** ⇒ 「Agent 查得到、页面里看不到」成立。
            "menu:frontend",
            lambda s: s.replace("permissionCode: 'after_sales:view'", "permissionCode: 'order:list'", 1),
            problems_leakage,
        ),
        "④ 只改一处菜单源的节点码 ⇒ 判据 3 红": (
            "menu:controller",
            _diverge_shared_node,
            problems_menu_parity,
        ),
        "④b 第四处菜单源长回来（还原原名 + 真树 + 调用点）⇒ 判据 3 红": (
            # issue #5236 的**真实回归形态**（不是改一个字的假变异）：同时压住两条 ——
            # 符号面（判据 3 ④ 红）与解析面（还原后的树必须仍能被 `_iter_menu_user` 解析出来，
            # 否则「空表」会把「长回来了」读成「缺席」）。
            "menu:user",
            _restore_fourth_menu_source,
            problems_menu_parity,
        ),
        "④c 第四处菜单源**换名**长回并接回响应（无 generateMenus / MenuItem 字面量）⇒ 判据 3 红": (
            # 名-based 判据的漏网形态：只有结构面（`.menus(...)`）看得见 ⇒ 它自己的判别力证明。
            "menu:user",
            _regrow_fourth_source_renamed,
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
        "⑩ 读端点被改挂写码（after_sales:view → order:refund）⇒ 判据 2 红": (
            # 唯一口径（issue #5247 改判）：**必须挑「某个 B 端可达工具真调用的端点」** ——
            # 判据 2 只对 `_coded_b_end`（B 端 skill 并集里的已编码工具）生效，挑一个
            # **没有任何 B 端 skill 绑定**的工具的端点 ⇒ 判据 2 依然绿 = 红证空转。
            # 实测踩过（同一处注入、两次失效）：
            #   ① 改 `OrderController`（人工表单端点）⇒ 不是任何工具的端点；
            #   ② 改 `AgentOrderController.PATCH /{id}`（issue #5246 的原锚，当时 `order_manage`
            #      还在 B 端）⇒ **#5247 把 `order_manage` 从 B 端解绑后本注入随即变成空断言**
            #      （`test_every_judgement_can_go_red` 立刻抓到，故本次改锚）。
            # 现锚 = `AfterSalesController` 的**读**端点 `GET /api/admin/after-sales`
            # （`after_sales_manage` 仍绑 B 端且仍调它）；把它的码改成写码后
            # 「工具码 ≡ 端点生效码」立刻不等 —— 形态 = 读面被挂写码（持读码者被假拒绝）。
            "java:controller/AfterSalesController.java",
            lambda s: s.replace('@RequirePermission("after_sales:view")',
                                '@RequirePermission("order:refund")', 1),
            problems_endpoint_parity,
        ),
        "⑪ 目录删掉新写码（customer:create）⇒ 两处目录不同步 ⇒ 判据 9 红": (
            "java:service/PermissionService.java",
            lambda s: s.replace('"customer:create"', '"customer:create-typo"', 1),
            problems_self_checks,
        ),
        "⑫ 岗位只拿到页内写码、没有该页读码（operator 去掉 product:list）⇒ 判据 4 红": (
            # 锚点口径（issue #5247 改判）：被删的**读**码必须与一个**仍在 B 端声明面里**的
            # 页内写码同页 —— 原锚删 `customer:view` 靠的是 `customer:create`（随
            # `customer_manage` 收窄退出声明面 ⇒ 注入变空断言）。
            # 现锚：operator 同时持 `product:list`（读）与 `product:category`（页内写码）
            # ⇒ 删掉读码后它仍能用 `category_manage` 查分类，但「商品列表」页要的
            # `product:list` 它没有 = 「Agent 做得到、页面里看不到」。
            "java:service/RegistrationService.java",
            lambda s: _drop_role_code(s, "operatorRole", "product:list"),
            problems_leakage,
        ),
        "⑬ 把生产读码从**前端菜单源**删掉（生产看板 → 无码）⇒ 判据 10 红": (
            # issue #5291 的**真实回归形态**：节点仍在、只是 `permissionCode` 没了 ⇒
            # 判据 3 的锚定会**跳过**它（无码节点被读成「全员可见」）、交会同构也不再比它
            # ⇒ 只有判据 10 能拦（这正是「删读码必须有一条能红的判据」的理由）。
            "menu:frontend",
            # 锚点 = **生产看板**那一行（`path: '/production'`）—— 与注入名逐字对应；
            # 用「第一个 production:view」当锚会让失败文案点名另一个节点（读数与结论不符）。
            lambda s: s.replace(
                "path: '/production', permissionCode: 'production:view', ", "path: '/production', ", 1),
            problems_read_code_anchoring,
        ),
        "⑭ 生产读码只在**一处菜单源**回退成管理码（MenuController 生产看板）⇒ 判据 10 红": (
            "menu:controller",
            lambda s: s.replace(
                'new MenuNode("production:view", "生产看板")',
                'new MenuNode("processing:manage", "生产看板")', 1),
            problems_read_code_anchoring,
        ),
        "⑮ 承载工具退回管理码（processing_order_query → processing:manage）⇒ 判据 10 红": (
            # 与 ⑤ 成对（**但锚点必须是登记表里的「承载工具」**，否则本注入是空断言 ——
            # `READ_CODE_ANCHORS` 的 ② 只复核登记的那一个工具）：⑤ 证明判据 5 仍有判别力
            #（例外表清空后照样红），本注入证明**读码锚定**那条也拦得住「工具悄悄退回管理码」。
            "tool:processing_order_query.py",
            lambda s: _set_codes(s, "processing_order_query.py", '["processing:manage"]'),
            problems_read_code_anchoring,
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
        "⑯ 把 `/production`（更宽）挪到 `/production/pool` 之前 ⇒ 子路径被短路 ⇒ 判据 11 红": (
            # 判据 11 ①（前缀序）：`find()` 先命中 ⇒ 三个管理码页面全部按读码判定。
            "route:layout.tsx",
            _shadow_production_subpaths,
            problems_route_guard,
        ),
        "⑰ 页面守卫码打错（`/categories` → `product:category:veiw`）⇒ 判据 11 红": (
            # 判据 11 ②（码必须在目录里）：码名不存在 ⇒ 该路由**对所有角色恒 403**（整页打不开）。
            # 锚点选 `/categories` 是**有意**：它不在 `ROUTE_MENU_ANCHORS` 里 ⇒ 只触发 ②，
            # 失败文案能干净归因（若选 `/knowledge` 会同时触发 ③，读数与结论对不上）。
            "route:layout.tsx",
            lambda s: s.replace(
                "{ prefix: '/categories', code: 'product:category:view' }",
                "{ prefix: '/categories', code: 'product:category:veiw' }",
                1,
            ),
            problems_route_guard,
        ),
        "⑱ 岗位权限页面守卫退回管理码（`/roles` → `system:manage`）⇒ 判据 11 红": (
            # 判据 11 ③（前缀 ↔ 菜单节点）：#5291 的**读码回退形态** —— 与 ⑬⑭⑮ 同族，
            # 但那一族只覆盖菜单源 / 工具，**页面守卫此前没有任何判据**。
            # 形态 = 侧边栏按 `system:view` 过滤、页面却要 `system:manage`
            # ⇒ 只持读码的岗位「看得见菜单、点进去 403」。
            "route:layout.tsx",
            lambda s: s.replace(
                "{ prefix: '/roles', code: 'system:view' }",
                "{ prefix: '/roles', code: 'system:manage' }",
                1,
            ),
            problems_route_guard,
        ),
        # ── 判据 12（issue #5675）：四类注入（改节点码 / 删节点码 / 改端点码 / 新增未登记的不一致）
        #    + 两类面内注入（台账陈旧、页面第一屏调用被换掉）──────────────────────────────
        "⑲ 改节点码（余料台账 `processing:manage` → `order:list`）⇒ 判据 12 红": (
            # 形态 = **新增一处未登记的不一致**：节点码与读端点码脱钩而台账里没有它。
            "menu:frontend",
            lambda s: _swap(
                s,
                "path: '/production/remnants', permissionCode: 'processing:manage'",
                "path: '/production/remnants', permissionCode: 'order:list'",
            ),
            problems_menu_read_parity,
        ),
        "⑳ 删节点码（余料台账的 permissionCode 整段删掉 ⇒ 码变 None）⇒ 判据 12 红": (
            "menu:frontend",
            lambda s: _swap(
                s,
                "path: '/production/remnants', permissionCode: 'processing:manage', ",
                "path: '/production/remnants', ",
            ),
            problems_menu_read_parity,
        ),
        "㉑ 改端点码（**本单修复的回退形态**：计件报表退回 `processing:manage`）⇒ 判据 12 红": (
            # 这是本单改动的**真实回归形态**（不是假变异）：谁把码改回去，判据立刻红
            # —— 且要变绿必须显式往台账里加一条登记（评审可见）。
            "java:controller/ProductionController.java",
            lambda s: _swap(
                s,
                '@GetMapping("/piecework/summary")\n    @RequirePermission("production:view")',
                '@GetMapping("/piecework/summary")\n    @RequirePermission("processing:manage")',
            ),
            problems_menu_read_parity,
        ),
        "㉒ 新增未登记的菜单节点 ⇒ 判据 12 红": (
            "menu:frontend",
            lambda s: _swap(
                s,
                "{ key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications',",
                "{ key: 'ghost-surface', name: '幽灵页', icon: 'Bell', path: '/ghost-surface', "
                "permissionCode: 'order:list', keywords: [] },\n"
                "  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications',",
            ),
            problems_menu_read_parity,
        ),
        "㉓ 台账陈旧（智能派单节点码改挂读端点码 ⇒ 那处不一致已消失）⇒ 判据 12 红": (
            # 只许缩短的**另一半**：不一致修好了却不销账 ⇒ 红（否则陈旧条目会把下一次真回归
            # 读成「已登记」）。注入的码 = 该页读端点码 `processing:view`（不是 `production:view`
            # —— 那仍是「不一致」，测的是 ⑲ 那一类）。
            "menu:frontend",
            lambda s: _swap(
                s,
                "path: '/production/pool', permissionCode: 'processing:manage'",
                "path: '/production/pool', permissionCode: 'processing:view'",
            ),
            problems_menu_read_parity,
        ),
        "㉔ 页面第一屏调用被换成别的端点（计件页改调 per-order 计件）⇒ 判据 12 红": (
            # 页面侧那一跳的判别力：声明的调用从「effect 驱动面」上消失 ⇒ 声明陈旧 ⇒ 红
            # （逼人同步台账，而不是让台账继续描述一个已经不存在的第一屏）。
            "page:/production/piecework",
            lambda s: _swap(
                s, "productionApi.getPieceworkSummary", "productionApi.getPiecework"),
            problems_menu_read_parity,
        ),
        # ── 判据 12 的**多端点页适用面**（#5675 收口包）：结构事实未登记 / 登记与现取不符 ────────
        "㉕ 单端点页变多端点页（省料看板的 saving-trend 改挂 `processing:manage`）⇒ 多端点页未登记 ⇒ 判据 12 红": (
            # 形态 = 判据 12 的「第一屏恰好一个读端点码」**前提被打破**：该页节点码恰好命中新码
            # ⇒ 一致性段（③）一声不响（原来的 `product:list` 那条不一致仍有登记）⇒
            # **只有**多端点登记表拦得住。本注入就是这张表自己的判别力证明。
            "java:controller/StockBatchController.java",
            lambda s: _swap(
                s,
                '    @RequirePermission("product:list")\n    @GetMapping("/saving-trend")',
                '    @RequirePermission("processing:manage")\n    @GetMapping("/saving-trend")',
            ),
            problems_menu_read_parity,
        ),
        "㉖ 多端点页码集漂移（工艺配置的 `route-rules` 读端点改挂 `product:list`）⇒ 登记与现取不符 ⇒ 判据 12 红": (
            # 形态 = 某页的「第一屏读端点码集」变了而登记没跟：③ 只看到 route-rules 那个码仍 ≠ 节点码
            # （该页本来就在残留台账里）⇒ 同样只有「逐值冻结」这一段看得见。
            "java:controller/ProductionController.java",
            lambda s: _swap(
                s,
                '    @GetMapping("/route-rules")\n    @RequirePermission("processing:manage")',
                '    @GetMapping("/route-rules")\n    @RequirePermission("product:list")',
            ),
            problems_menu_read_parity,
        ),
        # ── 判据 13（#5675 收口包）：注释里的计数 / 点名声明必须与代码现值一致 ────────────────
        #    🔴 **每一个 kind 都要有自己的红证**（否则那一支就是空断言）：计数类的红证必须改**代码**
        #    （改注释只会命中「锚失配」那一支），点名类的红证改**端点注解**，另有「锚被改写」一支。
        "㉗ 代码漂了而注释没跟（余料台账节点改挂 `production:view` ⇒ `menu.ts` 里该码节点 4→5）⇒ 判据 13 红（menu-node-count）": (
            "menu:frontend",
            lambda s: _swap(s, "path: '/production/remnants', permissionCode: 'processing:manage'",
                            "path: '/production/remnants', permissionCode: 'production:view'"),
            problems_comment_claims,
        ),
        "㉘ 注释里的声明被改写（`**两个**只读端点：…` 去掉加粗标记）⇒ 逐字锚失配 ⇒ 判据 13 红（锚卫生）": (
            "java:service/RegistrationService.java",
            lambda s: _swap(s, "**两个**只读端点：`/operations-catalog`、`/routings`",
                            "两处只读端点：`/operations-catalog`、`/routings`"),
            problems_comment_claims,
        ),
        "㉙ 点名的端点掉了码（`/operations-catalog` 改回 `processing:manage`）⇒ 判据 13 红（endpoint-code）": (
            "java:controller/ProductionController.java",
            lambda s: _swap(s, '    @GetMapping("/operations-catalog")\n    @RequirePermission("production:view")',
                            '    @GetMapping("/operations-catalog")\n    @RequirePermission("processing:manage")'),
            problems_comment_claims,
        ),
        "㉚ 把刻意不写死的条数写回来（该行加「今天 9 个只读工具」）⇒ 判据 13 红（no-hardcoded-count）": (
            "java:service/RegistrationService.java",
            lambda s: _swap(s, "**不写死条数**：工具会增删", "**不写死条数**（今天 9 个只读工具）：工具会增删"),
            problems_comment_claims,
        ),
        "㉛ 新增端点而注释没跟（该控制器加一个 GET ⇒ 7→8）⇒ 判据 13 红（get-endpoint-count）": (
            # 真实回归形态 = #5159 当年就是「加了端点没改类 javadoc」；本注入把它复现成一次改动。
            "java:controller/StockBatchController.java",
            lambda s: _swap(
                s,
                '    @RequirePermission("product:list")\n    @GetMapping("/saving-trend")',
                '    @RequirePermission("product:list")\n    @GetMapping("/ghost-read-face")\n'
                '    public ApiResponse<String> ghostReadFace() {\n        return ApiResponse.success("x");\n    }\n\n'
                '    @RequirePermission("product:list")\n    @GetMapping("/saving-trend")',
            ),
            problems_comment_claims,
        ),
        "㉜ 岗位权限变了而注释没跟（finance 去掉 `order:list` ⇒ 该码内置岗位 4→3）⇒ 判据 13 红（seed-role-count）": (
            "java:service/RegistrationService.java",
            lambda s: _drop_role_code(s, "financeRole", "order:list"),
            problems_comment_claims,
        ),
    }


def _restore_fourth_menu_source(text: str) -> str:
    """把第四处菜单源**长回来**（issue #5236 的回归形态：原名 + 调用点 + 真树）。

    注入的是当初被删的那棵表的**结构**（`permissions.contains(...)` + `menus.add(MenuItem.builder()
    .key(...).name(...))`），不是「改一个字的假变异」⇒ 它让 `_iter_menu_user` 真的解析出节点
    （没有这一条，注入后仍是空表 ⇒ 判据 3 ④ 的「解析面」那一半永远测不到）。
    """
    assert not fourth_menu_source_symbols(text), "注入前提：`UserController` 代码面已有该符号（同步本判据）"
    method = (
        "\n    // issue #5236 回归注入：第四处菜单源长回来\n"
        "    private List<UserInfoResponse.MenuItem> generateMenus(List<String> permissions, List<String> roles) {\n"
        "        List<UserInfoResponse.MenuItem> menus = new ArrayList<>();\n"
        "        boolean isAdmin = roles.contains(\"admin\") || permissions.contains(\"*\");\n"
        "        if (isAdmin || permissions.contains(\"dashboard:view\")) {\n"
        "            menus.add(UserInfoResponse.MenuItem.builder()\n"
        "                    .key(\"dashboard\")\n"
        "                    .name(\"经营看板\")\n"
        "                    .build());\n"
        "        }\n"
        "        if (isAdmin || permissions.contains(\"knowledge:view\")) {\n"
        "            menus.add(UserInfoResponse.MenuItem.builder()\n"
        "                    .key(\"knowledge\")\n"
        "                    .name(\"知识库管理\")\n"
        "                    .build());\n"
        "        }\n"
        "        return menus;\n"
        "    }\n"
    )
    idx = text.rstrip().rfind("\n}")
    assert idx != -1, "注入锚点失配：`UserController` 的类体收尾 `}` 找不到（同步本判据）"
    return text[:idx] + method + text[idx:]


def _regrow_fourth_source_renamed(text: str) -> str:
    """**换名**长回第四处菜单源（既无 `generateMenus`、也无 `MenuItem` 字面量）+ 重新接到响应上。

    这是「按名字钉」的漏网形态：`_FOURTH_MENU_SOURCE_RE` 看不见它，`_iter_menu_user` 也解析不出节点
    ⇒ 只剩**结构面**（响应构建里的 `.menus(...)`）兜得住。

    ⚠️ 夹具只做**文本变异**、不编译（本判据零依赖、只读源码文本，与 ⑨「删注解」同族）；
    它压的是**结构事实**（有没有菜单表接到响应上），不是 Java 类型正确性。
    """
    assert not fourth_menu_source_symbols(text), "注入前提：`UserController` 代码面已有该符号（同步本判据）"
    injected = text.replace(
        "        // 构建响应\n        UserInfoResponse response = UserInfoResponse.builder()",
        "        // 构建响应（issue #5236 回归注入：第四处菜单源**换名**长回）\n"
        "        List<LegacyMenuNode> legacyMenus = buildLegacyMenuTable(permissions);\n"
        "        UserInfoResponse response = UserInfoResponse.builder()",
        1,
    )
    assert injected != text, "注入锚点失配：响应构建处找不到（同步本判据）"
    relinked = injected.replace(
        "                .permissions(permissions)\n",
        "                .permissions(permissions)\n                .menus(legacyMenus)\n",
        1,
    )
    assert relinked != injected, "注入锚点失配：`.permissions(permissions)` 构建行找不到（同步本判据）"
    return relinked.rstrip() + (
        "\n\n    private List<LegacyMenuNode> buildLegacyMenuTable(List<String> permissions) {\n"
        "        return List.of(new LegacyMenuNode(\"dashboard\", \"经营看板\"));\n"
        "    }\n"
    )


def _diverge_shared_node(text: str) -> str:
    """把 `MenuController` 的『生产看板』节点码改成**与其它菜单源不同**的值。

    选『生产看板』而不是『售后工单』：前者在三处菜单源里**同名**（才落在交集判据的射程内），
    后者在 `MenuController` 里叫「退换货」—— 名字都不同的节点本就不参与同构比对
    （这正是 `REGISTERED_RESIDUALS` 所登记「菜单源不做全树同构」的含义）。
    """
    m = re.search(r'new MenuNode\("([^"]+)", "生产看板"\)', text)
    assert m, "注入锚点失配：`MenuController` 里找不到『生产看板』节点（同步本判据）"
    other = "order:list" if m.group(1) != "order:list" else "processing:manage"
    return text.replace(m.group(0), f'new MenuNode("{other}", "生产看板")', 1)


def test_fourth_source_comment_mention_stays_green() -> None:
    """**负控**：被删符号只出现在**注释**里 ⇒ 判据 3 必须保持绿（判据读的是剥注释后的代码）。

    为什么必须有这条：`UserController` 的决策记录 javadoc **必然**点名 `generateMenus`
    （issue #5236 落码时就写了一段 ⚠️ 说明）⇒ 若判据扫原文，它会被自己的说明文字**永久喂红**
    （migao-dev-flow §17.3「判据被自己的文案喂红」）。

    与上面 ④b 注入**成对**才有判别力：**只有**「注入注释必须绿」+「注入代码必须红」同时成立，
    符号判据才是「读代码」而不是「读文本」—— 单看任何一边都可以是一条恒绿 / 恒红的空断言。
    """
    base = _source_map()
    text = base["menu:user"]
    assert not fourth_menu_source_symbols(text), "前提：现存 `UserController` 代码面已无被删符号"
    injected = text.replace(
        "public class UserController {",
        "public class UserController {\n"
        "    // 这里曾经有 generateMenus（第四处菜单源，issue #5236 已整段删除）\n"
        "    /* MenuItem 同理：只在注释里提到 ≠ 长回来 */",
        1,
    )
    assert injected != text, "注入锚点失配：`public class UserController {` 找不到（同步本判据）"
    assert fourth_menu_source_symbols(injected) == [], "剥注释失效：注释里的提及被当成了代码"
    sources = dict(base)
    sources["menu:user"] = injected
    assert not problems_menu_parity(build_world(sources)), (
        "负控失败：只在注释里提及被删符号 ⇒ 判据被自己的说明文字喂红了"
    )


# ── issue #5272：`skill_names` 的**解析口径**（注释不是代码）─────────────────────────


def _legacy_quote_scan(text: str, agent: str) -> frozenset[str]:
    """**旧口径逐字复刻**（issue #5272 的病灶）：在**原文**上按双引号扫 `skill_names=[...]`。

    ⚠️ 它**不是**被测解析器（被测的是 `parse_agent_skills`）—— 它只用来断言下面两条负红证的夹具
    是**真陷阱**：注入的注释 / 文档字符串在旧口径下**确实**会被读成绑定。没有这条前提断言，
    「注入后仍绿」可能只是因为注入点没落进射程（= 恒绿的空断言，`migao-acceptance` 明令禁止）。
    """
    m = re.search(r"skill_names=\[(.*?)\]", text, re.S)
    assert m, f"旧口径复刻：`{agent}` 的 `skill_names=[...]` 锚点失配（同步本夹具）"
    return frozenset(re.findall(r'"([^"]+)"', m.group(1)))


def _mibao_with_comment_near_skill_names(text: str) -> str:
    """往 `skill_names=[` 之后插一行**带双引号 skill 名**的注释（**代码零改动**）。"""
    anchor = "    skill_names=[\n"
    assert anchor in text, "注入锚点失配：`mibao.py` 的 `skill_names=[` 找不到（同步本夹具）"
    at = text.index(anchor) + len(anchor)
    injected = text[:at] + (
        '        # 解绑说明（自然写法）：这里曾绑 "settings"（issue #5247 用户裁定；#5272 负控）\n'
    ) + text[at:]
    assert injected != text, "注入没生效（锚点失配）"
    return injected


def _mibao_with_docstring_example(text: str) -> str:
    """往 `MIBAO_CONFIG` 之前插一段**文档字符串**举例（**代码零改动**）。"""
    anchor = "MIBAO_CONFIG = AgentConfig("
    assert anchor in text, "注入锚点失配：`MIBAO_CONFIG = AgentConfig(` 找不到（同步本夹具）"
    doc = (
        '"""文档举例（issue #5272 负控）：下面这一行只是说明文字 ——\n'
        'skill_names=["settings"] 不是绑定。\n'
        '"""\n'
    )
    at = text.index(anchor)
    injected = text[:at] + doc + text[at:]
    assert injected != text, "注入没生效（锚点失配）"
    return injected


def _mibao_with_real_binding(text: str) -> str:
    """往 `skill_names` 列表里**真**插一个 skill 名（**代码**，不是注释）。"""
    anchor = '        "staff",\n'
    assert anchor in text, '注入锚点失配：`mibao.py` 找不到 `"staff",` 行（同步本夹具）'
    injected = text.replace(anchor, anchor + '        "settings",\n', 1)
    assert injected != text, "注入没生效（锚点失配）"
    return injected


def _assert_inert(base: dict[str, str], mutate, what: str) -> None:
    """**口径纯判据**：`mutate` 只加注释 / 文档字符串 ⇒ **任何读数都不得变化**（差分必须为零）。

    🔴 为什么**不能**写成「读数 == 某个期望值」（`leaked == []` / `not problems_missing_codes(w)`）：
    `settings` 绑不绑是**产品裁定**（#5247 今天解绑，明天可以再绑）⇒ 那种写法把夹具的绿
    与产品当前状态**耦合**：产品真绑回去时，报出来的话会是「**注释**里的 `settings` 被读成了绑定」，
    而**真因是代码绑定** —— 读数与病因不一致（本单一路在治的形态）。
    差分口径只谈夹具要钉的东西：**注入注释 / 文档字符串不得改变任何读数**。
    状态无关性由 `test_negative_fixtures_are_state_blind` 钉住（先真绑一个 skill 再跑同一对夹具）。
    """
    text = base["agent:mibao"]
    injected = mutate(text)
    assert "settings" in _legacy_quote_scan(injected, "mibao"), (
        f"注入前提：旧口径必须真会把{what}读成绑定（否则本夹具是恒绿的空断言）"
    )
    sources = dict(base)
    sources["agent:mibao"] = injected
    assert parse_agent_skills(sources, "mibao") == parse_agent_skills(base, "mibao"), (
        f"{what}改变了 `skill_names` / `fallback_skill` 的读数："
        f"{sorted(parse_agent_skills(sources, 'mibao')[0])} vs {sorted(parse_agent_skills(base, 'mibao')[0])}"
    )
    w_base = build_world(base)
    w_mut = build_world(sources)
    assert w_mut.b_end_tools == w_base.b_end_tools, f"{what}改变了 B 端工具集"
    assert w_mut.c_end_tools == w_base.c_end_tools, f"{what}改变了 C 端工具集"
    drifted = sorted(label for label, fn in JUDGEMENTS.items() if fn(w_mut) != fn(w_base))
    assert not drifted, f"{what}改变了判据读数（差分不为零）：{drifted}"


def test_skill_name_in_a_comment_is_not_a_binding() -> None:
    """**负红证**（issue #5272）：`skill_names` 附近**注释**里带双引号的 skill 名 ⇒ 不算绑定。

    形态 = **差分必须为零**（口径纯，**不依赖产品当前绑没绑** —— 理由见 `_assert_inert` 的 🔴 段）。
    修前必红（现场实证：作者为绕过它写了「本注释不得给 skill 名加双引号」的规避说明）：
    旧口径把注释里的 `"settings"` 读成仍绑定 ⇒ 读数与 base 不同 ⇒ 本夹具立刻红。
    **成对**的正红证见 `test_real_skill_binding_is_still_a_binding` ——
    只有两边同时成立，解析口径才是「读代码」而不是「读文本」（单看任一边都是空断言）。
    """
    _assert_inert(_source_map(), _mibao_with_comment_near_skill_names, "注释里的带引号 skill 名")


def test_skill_name_in_a_docstring_is_not_a_binding() -> None:
    """**文档字符串负例**（issue #5272 要求 3）：文档里举例写 `skill_names=["settings"]` ⇒ 不算绑定。

    `tokenize` 下整段是**一个 `STRING` token**（不是 `NAME skill_names` + `=` + 列表）⇒
    `_py_assigned_strings` 看不见它；但同一段文本在旧口径里是**首个** `skill_names=[...]` 命中
    ⇒ 会被读成绑定（这正是判据 3 要治的形态）。判据同样走**差分**（`skill_names` 与 `fallback_skill` 一起比）。
    """
    _assert_inert(_source_map(), _mibao_with_docstring_example, "文档字符串里的举例")


def test_negative_fixtures_are_state_blind() -> None:
    """**口径纯的红证**（issue #5272）：产品**真**绑了一个 skill 时，上面两条负例夹具必须**仍绿**。

    做法：先造一份「真绑定」的 base（= 真实源码 + **代码**里加回 `"settings",`），再在同一 base 上
    跑那两条夹具 —— 它们只谈「注释 / 文档字符串不算绑定」，**不该**因为产品绑没绑而变红。

    判别力（本条自己会红）：夹具若退回「读数 == 期望值」的耦合形式（`leaked == []` /
    `not problems_missing_codes(w)`），在**真绑定**的 base 上必然红 —— 那正是「读数与病因不一致」
    的形态（报出来的是「注释被读成绑定」，真因却是代码绑定）。逐字变异证据见 PR body。

    ⚠️ 判别力前提**不靠产品状态**：除「真绑定」外再叠一处**判据必红**的注入（⑥ 清空 `role_manage`
    的权限码）⇒ 无论产品今天绑不绑 `settings`，耦合形式的夹具都会红（本条不会因产品裁定而假绿/假红）。
    """
    base = _source_map()
    bound = dict(base)
    bound["agent:mibao"] = _mibao_with_real_binding(base["agent:mibao"])
    bound["tool:role_manage.py"] = _set_codes(base["tool:role_manage.py"], "role_manage.py", "[]")
    assert "settings" in parse_agent_skills(bound, "mibao")[0], "注入没生效：真绑定没进对照 base"
    assert problems_missing_codes(build_world(bound)), (
        "注入前提：对照 base 上判据 1 必须是红的 —— 否则「耦合形式的夹具会红」无从证明"
    )
    _assert_inert(bound, _mibao_with_comment_near_skill_names, "注释里的带引号 skill 名（真绑定对照 base）")
    _assert_inert(bound, _mibao_with_docstring_example, "文档字符串里的举例（真绑定对照 base）")


def test_real_skill_binding_is_still_a_binding() -> None:
    """**正红证**（issue #5272 要求 2）：真往 `skill_names` 里插一个名字（**代码**，非注释）⇒ 判据照旧红。

    与负红证**同一注入点、同一 skill 名**（只差「代码 vs 注释」）⇒ 两者成对才证明
    「注释被忽略」没有把真绑定也一起忽略（判据强度未降，B 端不得绑写工具的判据一字未放宽）。
    ⚠️ 本夹具**有意**与产品状态相关（它钉的就是「真绑定 ⇒ 判据红」）⇒ 故**显式登记前提**：
    `settings` 当前必须**未**绑定 —— 产品若真绑回去，它会以**准确的前提失效**报出，
    而不是报成「判据被削弱了」（读数与病因一致）。
    """
    base = _source_map()
    assert "settings" not in parse_agent_skills(base, "mibao")[0], (
        "注入前提失效：产品**现在**真绑了 settings（本夹具的注入会退化成重复项，测不到东西）⇒ "
        "换一个未绑定的 skill 名并同步本夹具"
    )
    sources = dict(base)
    sources["agent:mibao"] = _mibao_with_real_binding(base["agent:mibao"])
    names, _fb = parse_agent_skills(sources, "mibao")
    assert "settings" in names, f"真绑定没被解析出来（漏判比假红更糟）：{sorted(names)}"
    w = build_world(sources)
    assert {"settings_manage", "notification_manage"} <= w.b_end_tools, "真绑定的工具没进 B 端工具集"
    assert problems_missing_codes(w), "真插入 skill 名后判据 1 没变红 ⇒ 判据被削弱了"


def test_pending_endpoint_registry_is_self_clearing(monkeypatch) -> None:
    """**在飞端点登记的自清判据**（#5314）：端点一落地，登记项必须被报成「陈旧」⇒ 逼人删除。

    为什么单独成例（而不是源文本注入）：登记表**当前为空**（服务端 #5339 已把
    `/api/admin/agent/batches*` 合入 `AgentBatchController`）—— 源注入的注入点已不存在，
    而「陈旧即红」这条判据仍必须**有能单独变红的证据**（否则它是空断言）。
    故用 monkeypatch 合成登记表：**正控** = 合成一条**端点真实存在**的登记 ⇒ 必须报；
    **负控** = 合成一条端点不存在的登记 ⇒ 不得报（否则任何人加条目都恒红）。
    """
    import sys as _sys
    mod = _sys.modules[__name__]
    w = world()
    real_key = "app/tools/product_batch_update.py|POST /api/admin/agent/batches"
    assert ("POST", "/api/admin/agent/batches") in w.all_eps, (
        "前提失效：该端点已不在 admin-api 源码里（本判据的正控就没有对象了）—— 同步本判据")
    entry = {"code": "product:create", "reason": "红证夹具（端点已落地）",
             "owner": "本判据", "issue": "#5314"}

    monkeypatch.setattr(mod, "PENDING_ENDPOINTS", {real_key: dict(entry)})
    hits = problems_registered_decisions(w)
    assert any("陈旧登记必须删除" in h for h in hits), (
        f"端点已落地却未报「陈旧登记」⇒ 自清判据失效（hits={hits}）")

    ghost_key = "app/tools/product_batch_update.py|POST /api/admin/agent/ghost-endpoint"
    monkeypatch.setattr(mod, "PENDING_ENDPOINTS", {ghost_key: dict(entry)})
    hits = problems_registered_decisions(w)
    assert not any("陈旧登记必须删除" in h for h in hits), (
        f"端点**不存在**的登记被判陈旧 ⇒ 负控失败（恒红，无法登记任何在飞端点）：hits={hits}")

    monkeypatch.setattr(mod, "PENDING_ENDPOINTS", {real_key: {"code": "product:create"}})
    hits = problems_registered_decisions(w)
    assert any("缺 `reason`" in h or "缺 `owner`" in h or "缺 `issue`" in h for h in hits), (
        f"登记项缺必填字段却未报 ⇒ 登记表会退化成垃圾场（hits={hits}）")


def test_multi_endpoint_registry_is_self_clearing(monkeypatch) -> None:
    """多端点页登记表（判据 12 ⑤）的**三态**都能单独变红：未登记 / 现取不符 / 已不再多码（#5675 收口包）。

    为什么单独成例：「未登记」那一态的**真实回归形态**由注入 ㉕㉖ 走（改注解 ⇒ 某页码集变化）；
    本例外加的三态是**登记表自身**的卫生 —— ②「现取不符」的两侧（多一个 / 少一个码）与 ③「陈旧」
    今天在真实源码里**没有**对应坏形态，只能靠合成登记来压（同 `test_pending_endpoint_registry_is_self_clearing`
    的做法：不合成 = 这三态永远是空断言）。
    """
    import sys as _sys
    mod = _sys.modules[__name__]
    w = world()
    assert not problems_menu_read_parity(w), "前提：当前树判据 12 全绿（否则本条的读数无从归因）"
    # ⚠️ 先留一份**未被 monkeypatch 过的**原表：下面每一态都替换模块级名字，裸名读到的已是被换掉那份。
    pristine = dict(MULTI_READ_ENDPOINT_PAGES)

    # ① 未登记：把登记表清空 ⇒ 三个多端点页**每一个**都必须被点名（登记表不是装饰）。
    monkeypatch.setattr(mod, "MULTI_READ_ENDPOINT_PAGES", {})
    hits = problems_menu_read_parity(w)
    for path in ("/production/processing", "/production/routings", "/settings"):
        assert any(path in h and "多个不同码" in h for h in hits), (
            f"清空登记表后 `{path}` 未被判「多端点页未登记」⇒ ⑤ 的覆盖段失效（hits={hits}）")

    # ② 现取不符：把真登记里某一页的码集**改宽一个**（多一个码）⇒ 必须报「与现取不符」。
    widened = dict(pristine)
    widened["/production/routings"] = replace(
        widened["/production/routings"], codes=widened["/production/routings"].codes | {"order:list"})
    monkeypatch.setattr(mod, "MULTI_READ_ENDPOINT_PAGES", widened)
    hits = problems_menu_read_parity(w)
    assert any("与**现取**" in h and "order:list" in h for h in hits), (
        f"登记的码集比现取多一个码却未报 ⇒ ⑤ 的冻结段失效（hits={hits}）")

    # ③ 陈旧：把一个**单端点**页登记成多端点页 ⇒ 必须报「已不再并发多码 ⇒ 删掉这条登记」。
    monkeypatch.setattr(mod, "MULTI_READ_ENDPOINT_PAGES", {
        "/production/saving-board": MultiReadEndpointPage(
            node="省料看板", codes=frozenset({"product:list"}),
            reason="红证夹具（单端点页）", owner="本判据"),
    })
    hits = problems_menu_read_parity(w)
    assert any("已**不再并发多码**" in h for h in hits), (
        f"单端点页被登记成多端点页却未报「陈旧」⇒ ⑤ 的只许缩短段失效（hits={hits}）")

    # ④ path 已不在菜单里 ⇒ 同一段的另一个出口（删除而不是留着）。
    monkeypatch.setattr(mod, "MULTI_READ_ENDPOINT_PAGES", {
        "/ghost-surface": MultiReadEndpointPage(
            node="幽灵页", codes=frozenset({"order:list"}),
            reason="红证夹具（path 不存在）", owner="本判据"),
    })
    hits = problems_menu_read_parity(w)
    assert any("已不在 `config/menu.ts`" in h for h in hits), (
        f"登记了一个不在菜单里的 path 却未报 ⇒ 陈旧登记会永久留存（hits={hits}）")


def test_read_parity_victims_ack_is_load_bearing(monkeypatch) -> None:
    """`victims_ack` 是**承载字段**（判据 12 ④，#5675 收口包）：清空它 ⇒ 受害者必须立刻报出来。

    四段（缺任何一段这条「认领」就只是注释）：
      ① 现状：确有受害者的路径都写了认领 ⇒ 判据 12 全绿、且**不**报受害者（基线）；
      ② 清空那条真认领 ⇒ 逐岗位复算立刻报出（`product_manager@fallback` 缺 `order:list`）——
         即「菜单看得见、点进去 403」的机械形态，而不是靠人记得；
      ③ 反向：给一条**没有**受害者的路径写认领 ⇒ 判「陈旧认领」（否则它会替未来的真受害者放行）；
      ④ 🔴 **销账 ≠ 把认领删掉**（issue #5683）：`/production/pool` 今天**既无受害者、也没写认领**
         —— 若有人把补上的权限**收回去**而认领仍空着 ⇒ 必须**立刻红**。这一条把「真销账」
         （权限补上了）与「假装销账」（只是把那段文字删了）区分开：后者在这里爆。
    """
    import sys as _sys
    mod = _sys.modules[__name__]
    w = world()
    baseline = problems_menu_read_parity(w)
    assert not baseline, "前提：当前树判据 12 全绿"
    assert not [h for h in baseline if "403 受害者" in h], "基线不得已有受害者读数"

    # ② 清空那条真认领 ⇒ 受害者必须逐条报出。
    cleared = dict(MENU_READ_PARITY_RESIDUALS)
    for path in ("/production/processing",):
        assert MENU_READ_PARITY_RESIDUALS[path].victims_ack.strip(), (
            f"前提失效：`{path}` 今天没有 `victims_ack` ⇒ 本夹具测不到「认领是承载字段」")
        cleared[path] = replace(MENU_READ_PARITY_RESIDUALS[path], victims_ack="")
    monkeypatch.setattr(mod, "MENU_READ_PARITY_RESIDUALS", cleared)
    hits = problems_menu_read_parity(w)
    assert any("403 受害者" in h and "product_manager@fallback" in h for h in hits), (
        "清空 `victims_ack` 后 `product_manager@fallback` 的 403 受害者未被报出 ⇒ "
        f"认领字段不是承载字段（hits={hits}）")
    assert any("403 受害者" in h and "order:list" in h for h in hits), (
        f"`product_manager@fallback` 缺 `order:list` 的那一条未被报出（hits={hits}）")

    # ③ 反向：给无受害者的路径写认领 ⇒ 陈旧认领必红。
    stale = dict(MENU_READ_PARITY_RESIDUALS)
    stale["/production/routings"] = replace(
        MENU_READ_PARITY_RESIDUALS["/production/routings"], victims_ack="红证夹具：本路径无受害者")
    monkeypatch.setattr(mod, "MENU_READ_PARITY_RESIDUALS", stale)
    hits = problems_menu_read_parity(w)
    assert any("陈旧认领" in h for h in hits), (
        f"无受害者却写了认领、判据没红 ⇒ 陈旧认领会替未来的真受害者放行（hits={hits}）")
    monkeypatch.setattr(mod, "MENU_READ_PARITY_RESIDUALS", MENU_READ_PARITY_RESIDUALS)

    # ④ 销账的判据形态（issue #5683）：`/production/pool` 无受害者、认领也已清空；
    #    把补上的 `processing:view` **从回退里收回去** ⇒ 「清空但权限没补」必须立刻红。
    assert not MENU_READ_PARITY_RESIDUALS["/production/pool"].victims_ack.strip(), (
        "前提失效：`/production/pool` 今天应写**空**认领（issue #5683 已销账）；"
        "若它又有认领，说明这次销账被回退了")
    reverted = _source_map()
    role_key = "java:service/RoleService.java"
    reverted[role_key] = _drop_fallback_code(reverted[role_key], "operator", "processing:view")
    reverted[role_key] = _drop_fallback_code(reverted[role_key], "product_manager", "processing:view")
    assert reverted[role_key] != _source_map()[role_key], "注入没生效（锚点失配）—— 同步本夹具"
    hits = problems_menu_read_parity(build_world(reverted))
    for victim in ("operator@fallback", "product_manager@fallback"):
        assert any("403 受害者" in h and victim in h for h in hits), (
            f"把 `processing:view` 收回后 `{victim}` 未被判为 403 受害者 ⇒ 「销账」可以只是"
            f"把那段文字删掉（清空但权限没补必须红）（hits={hits}）")


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
        "对照组：未注入时全部判据必须全绿（否则红证无从归因）：\n"
        + "\n".join(f"  【{k}】{v[:2]}" for k, v in green.items() if v)
    )
    for label, (key, mutate, judgement) in _injections().items():
        sources = dict(base_sources)
        sources[key] = mutate(sources[key])
        assert sources[key] != base_sources[key], f"{label}：注入没生效（锚点失配）—— 同步本判据"
        mutated = build_world(sources)
        assert judgement(mutated), f"{label}：判据没有变红 ⇒ 它是空断言"


def test_exception_ledger_only_shrinks(monkeypatch) -> None:
    """例外表**只许缩短**（issue #5291 的收口面）：`READ_WRITE_EXCEPTIONS` 一旦变长即红。

    三段式（缺任何一段这条判据就是空断言）：
      ① **对照组**：当前树（表已清空）下判据 5 全绿；
      ② **删条目 ≠ 失去判别力**：把某个只读工具的码改回管理码 ⇒ 判据 5 **照样红**
         （例外表清空没有把这条能力一起删掉，与注入 ⑤ 同向互证）；
      ③ **台账能拦「加回一条例外」**：把该工具登记进例外表（这正是例外表当初存在的理由）
         ⇒ 「具名例外」的老检查放行，**只有**条数台账能拦 ⇒ 它必须红。

    为什么第 ③ 段必须有：只看 ①②，「例外表只许缩短」就只是**注释里的纪律** ——
    新增一条例外的 PR 会一路绿到 main（#5246/#5247 两批把它从 7 条喂到 10 条，无人被拦）。
    """
    base = _source_map()
    assert not problems_read_write(build_world(base)), "前提：当前树判据 5 全绿（例外表为空）"

    mutated = dict(base)
    key = "tool:processing_order_query.py"
    mutated[key] = _set_codes(mutated[key], "processing_order_query.py", '["processing:manage"]')
    hits = problems_read_write(build_world(mutated))
    assert any("`read_only=True`（只读）却要求写/管理码" in h for h in hits), (
        f"② 失败：只读工具改持管理码后判据 5 没红 ⇒ 删例外条目把判别力一起删掉了（hits={hits}）"
    )

    monkeypatch.setitem(
        READ_WRITE_EXCEPTIONS,
        "processing_order_query",
        "红证注入：假装这是本轮新欠的粒度债（具名例外必须带理由 + 建议修法）",
    )
    hits = problems_read_write(build_world(mutated))
    assert any("读写例外表**又长回来了**" in h for h in hits), (
        f"③ 失败：例外表加回一条后条数台账没红 ⇒ 「只许缩短」是空断言（hits={hits}）"
    )
    assert len(READ_WRITE_EXCEPTIONS) > READ_WRITE_EXCEPTIONS_CEILING


# ── issue #5323 第 1 条：岗位默认权限 / 角色码的**取值口径**（注释不是代码）───────────────


def _comment_only_attach_code(text: str, role_fragment: str, code: str) -> str:
    """在 `attachDefaultPermissions(...List.of(` 的**参数区里**插一行注释（**代码零改动**）。

    注入的码只出现在注释里 ⇒ 任何读数都不得变化（旧口径会把它读成「该岗位挂了这个码」）。
    """
    anchor = f"attachDefaultPermissions(tenantId, {role_fragment}, List.of("
    idx = text.find(anchor)
    assert idx != -1, f"注入锚点失配：找不到 `{anchor}`（同步本夹具）"
    end = text.find("permissionByCode)", idx)
    assert end != -1, "注入锚点失配：找不到该岗位列表的结尾"
    block = text[idx:end]
    injected = block.replace(
        "List.of(",
        f'List.of(\n                // 留档注释（代码零改动）："{code}" 已随 issue #5247 解绑，曾在此列表里\n                ',
        1,
    )
    assert injected != block, "注入没生效（锚点失配）"
    return text[:idx] + injected + text[end:]


def _comment_only_role_code(text: str, role_fragment: str, code: str) -> str:
    """在 `Role.builder()` 身体里插一行注释，其中写着 `code("…")`（**代码零改动**）。"""
    anchor = f"Role {role_fragment} = Role.builder()\n"
    idx = text.find(anchor)
    assert idx != -1, f"注入锚点失配：找不到 `{anchor}`（同步本夹具）"
    at = idx + len(anchor)
    return text[:at] + f'                // 留档注释（代码零改动）：曾写 code("{code}")\n' + text[at:]


def _comment_only_fallback_case(text: str, code: str) -> str:
    """在 `RoleService` 的 switch 里插一行注释，写着 `case "…" -> List.of("…");` 形态。"""
    anchor = 'case "admin" -> List.of("*");'
    idx = text.find(anchor)
    assert idx != -1, '注入锚点失配：找不到 `case "admin" -> List.of("*");`（同步本夹具）'
    line_start = text.rfind("\n", 0, idx) + 1
    inject = f'// 留档注释（代码零改动）：case "{code}" -> List.of("ghost:code");\n            '
    return text[:line_start] + inject + text[line_start:]


class TestRolePermissionParsingIsCommentAware:
    """`#5323` 第 1 条成对红证：权限码 / 角色码只认**代码**里的声明（required 判据）。"""

    def test_comment_only_injections_do_not_move_any_reading(self):
        """负例：三处各注入一行**注释**（代码零改动）⇒ 读数**逐值不变**（差分为零）。"""
        base = _source_map()
        reg = base["java:service/RegistrationService.java"]
        role_text = base["java:service/RoleService.java"]
        baseline_roles = parse_role_defaults(reg)
        baseline_fallback = parse_role_fallback(role_text)
        assert baseline_fallback, "前提：回退表解析非空（否则下面的负控是空跑）"

        injected = _comment_only_attach_code(reg, "financeRole", "ghost:code")
        assert injected != reg, "注入没生效（锚点失配）"
        assert parse_role_defaults(injected) == baseline_roles, (
            "`List.of(...)` 参数区里的**注释**被读成了「该岗位挂了这个码」")

        with_comment_code = _comment_only_role_code(reg, "financeRole", "ghost_role")
        assert with_comment_code != reg, "注入没生效（锚点失配）"
        assert parse_role_defaults(with_comment_code) == baseline_roles, (
            "`Role.builder()` 身体里注释中的 `code(\"…\")` 被读成了角色码")

        injected_role = _comment_only_fallback_case(role_text, "ghost")
        assert injected_role != role_text, "注入没生效（锚点失配）"
        assert parse_role_fallback(injected_role) == baseline_fallback, (
            "注释里的 `case \"…\" -> List.of(…)` 被读成了回退分支")

    def test_real_code_injection_does_move_the_reading(self):
        """正例（防修过头）：把码**真**写进 `List.of(...)` ⇒ 读数跟着变（判据照旧被行使）。"""
        reg = _source_map()["java:service/RegistrationService.java"]
        baseline = parse_role_defaults(reg)
        mutated = parse_role_defaults(_add_role_code(reg, "financeRole", "product:category"))
        assert mutated["finance"] == baseline["finance"] | {"product:category"}, sorted(mutated["finance"])

    def test_synthetic_comment_payloads_read_nothing(self):
        """负例（合成载荷）：三处都**只**在注释里声明 ⇒ 一个都不被读到；真写则读到。"""
        assert _java_string_arg('// .code("ghost_role")\n.code("finance")\n', "code(") == "finance"
        assert _java_string_arg('// .code("ghost_role")\n', "code(") == ""
        role_text = (
            "class S {\n"
            "    private List<String> getPermissionCodesForRole(String roleCode) {\n"
            "        return switch (roleCode) {\n"
            '            // case "ghost" -> List.of("ghost:code");\n'
            '            case "operator" -> List.of("order:list");\n'
            "        };\n"
            "    }\n"
            "}\n"
        )
        assert parse_role_fallback(role_text) == {"operator": frozenset({"order:list"})}
        real = role_text.replace('// case "ghost"', 'case "ghost"')
        assert parse_role_fallback(real) == {
            "ghost": frozenset({"ghost:code"}), "operator": frozenset({"order:list"})}, (
            "真写进 switch 的分支没被读到 ⇒ 判据恒绿（空断言）"
        )