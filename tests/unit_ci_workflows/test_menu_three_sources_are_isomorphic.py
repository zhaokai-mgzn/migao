# case_ids: PG-021, MC-019
"""菜单**三处来源同构**守卫（issue #4440）—— 治「改一处不红」。

## 病根（issue #4357 关闭评论搬出的如实登记 ②，原文零追踪单）

菜单号称「三处同构」，但**三份各自维护**：

| 来源 | 角色 |
|---|---|
| `frontend/admin-web/src/config/menu.ts` | **真实侧边栏**（`Sidebar.tsx` 只读它） |
| `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE` | `GET /api/admin/menus` 的读面 |
| `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions` | 登录后下发的菜单（侧边栏数据源之一） |

⇒ 任何一份都可以**静默腐烂**：服务端改了前端不跟（前端只读 `menu.ts`），前端改了服务端不跟
（没有东西比对）⇒ **没有任何东西会变红**（`migao-dev-flow` §19 的「不会红的判据」形态）。

🔴 **本守卫的实例（issue #4440 落地时实测）**：`frontend/admin-web/src/config/menu.ts` 已在
**issue #4416** 把「工序库」+「工艺路线」**合并为单入口「工艺配置」**（工序库半边 = 该页左栏；
旧路径 `/production/operations` 保留为重定向），而**服务端两处仍是合并前的两个节点**
⇒ 前端「岗位权限」页（`frontend/admin-web/src/app/(dashboard)/employees/page.tsx` 消费
`GET /api/admin/menus`）显示的菜单项与**真实侧边栏对不上**（商家勾得动、侧边栏看不到 / 反之）。

## 判据

**生产管理组**的**节点名列表**在**三处逐值相等**（顺序也一致）：

- 红证：只改 `menu.ts` 加一项 ⇒ 红；只改 `MenuController` ⇒ 红；只改 `AuthService` ⇒ 红；
- 反恒真：三处任一解析为空 ⇒ **红**（不得静默空跑通过）。

## 图标维度：**不参与同构**（issue #5217 裁决 = 方案 2，见文件末尾 `test_icon_is_frontend_only`）

上面那条判据只比**名字 / 路径 / 顺序**，**不比图标** —— 于是图标维度**纸面同构、实际可静默漂移**
（实测：`production-piecework` 前端 `Calculator` / 服务端 `Coins`）。issue #5217 给了二选一，
本仓按**实测证据**选**方案 2：图标是前端专属**（服务端不下发图标）——
而不是选方案 1（把图标纳入同构）：**`MenuController.MENU_TREE` 的节点 DTO 结构上就没有图标这一维**
（`code/label/children`），走方案 1 得先**新增**一个服务端图标字段（+30 余个节点逐一手填），
而该字段同样**无人消费** ⇒ 只是把雷做大。裁决依据与机械判据见文件末尾。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MENU_TS = REPO_ROOT / "frontend/admin-web/src/config/menu.ts"
MENU_CONTROLLER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java"
AUTH_SERVICE = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java"

GROUP_KEY = "production"
GROUP_LABEL = "生产管理"


def _read(path: Path) -> str:
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf8")


def _frontend_names() -> list[str]:
    """`menu.ts` 的生产管理组的 `children[].name`（按出现顺序）。"""
    src = _read(MENU_TS)
    # 组起点 = `key: 'production'`；终点 = 组内 `children: [` 的配对 `]`
    m = re.search(r"key:\s*'production'.*?children:\s*\[", src, re.S)
    assert m, "`menu.ts` 里找不到 `key: 'production'` 组（解析失配 ⇒ 红，不得静默空跑）"
    tail = src[m.end():]
    depth, i = 0, 0
    while i < len(tail):
        if tail[i] == "[":
            depth += 1
        elif tail[i] == "]":
            if depth == 0:
                break
            depth -= 1
        i += 1
    body = tail[:i]
    names = re.findall(r"\bname:\s*'([^']+)'", body)
    assert names, "生产管理组解析出 0 个菜单名 ⇒ 判据会空跑（fail-closed）"
    return names


def _menu_controller_names() -> list[str]:
    """`MENU_TREE` 的生产管理组的节点 label（按组内 `List.of(...)` 的变量顺序）。"""
    src = _read(MENU_CONTROLLER)
    grp = re.search(
        rf'new MenuNode\("{GROUP_KEY}",\s*"{GROUP_LABEL}",\s*List\.of\(([^)]*)\)\)', src
    )
    assert grp, f"`MenuController` 里找不到 {GROUP_LABEL} 组（解析失配 ⇒ 红）"
    decls = dict(re.findall(r"MenuNode\s+(\w+)\s*=\s*new MenuNode\(\"[^\"]+\",\s*\"([^\"]+)\"\)", src))
    names: list[str] = []
    for var in [v.strip() for v in grp.group(1).split(",") if v.strip()]:
        assert var in decls, f"组内变量 `{var}` 在文件里找不到对应的 MenuNode 声明（解析失配 ⇒ 红）"
        names.append(decls[var])
    assert names, f"{GROUP_LABEL}组解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
    return names


def _auth_service_names() -> list[str]:
    """`AuthService.buildMenusByPermissions` 的生产管理组 `menuItem(...)` 的第 2 个实参（名称）。"""
    src = _read(AUTH_SERVICE)
    assert "productionChildren" in src, "`AuthService` 里找不到 `productionChildren`（解析失配 ⇒ 红）"
    names = re.findall(r'productionChildren\.add\(menuItem\("[^"]+",\s*"([^"]+)"', src)
    assert names, "`AuthService` 的生产管理组解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
    return names


def test_production_menu_is_isomorphic_across_three_sources() -> None:
    """三处来源的**生产管理组**节点名**逐值相等**（顺序一致）。"""
    frontend, controller, auth = _frontend_names(), _menu_controller_names(), _auth_service_names()
    assert frontend == controller, (
        "前端 `config/menu.ts`（真实侧边栏）与 `MenuController.MENU_TREE`（`GET /api/admin/menus`，"
        f"被「岗位权限」页消费）的生产管理组**不同构**：\n  前端 = {frontend}\n  服务端 = {controller}\n"
        "⇒ 商家在岗位权限页勾的菜单项与真实侧边栏对不上（改一处不红 = 允许静默腐烂）"
    )
    assert frontend == auth, (
        "前端 `config/menu.ts` 与 `AuthService.buildMenusByPermissions`（登录下发的菜单）的生产管理组"
        f"**不同构**：\n  前端 = {frontend}\n  服务端 = {auth}"
    )


# ══════════════ 图标维度：**不参与同构**（issue #5217 裁决 = 方案 2「图标是前端专属」） ══════════════
#
# 裁决依据（**实测**，复算命令见 PR body；不是推断）：
#   · `MenuNode.java`（`GET /api/admin/menus` 的节点 DTO）只有 `code/label/children`
#     —— 服务端权限树**结构上就没有**图标这一维 ⇒ 方案 1「三源图标逐字一致」需先**新增**该字段；
#   · 前端对「登录下发菜单」的读取点**只有** `frontend/admin-web/src/types/index.ts` 的
#     `User.menus` 类型声明与 `frontend/admin-web/src/store/auth.ts` 的透传赋值
#     —— **没有任何生产读取点**读 `menus[].icon`（真实侧边栏
#     `frontend/admin-web/src/components/layout/Sidebar.tsx` 的 `iconMap[...]` 取自 `@/config/menu`）；
#   · 实证漂移：`production-piecework` 前端 `Calculator` / 服务端 `Coins`（无人消费 ⇒ 无人发现）。
# ⇒ 服务端那份 `icon` 是**无人消费、只会与前端漂移**的雷 ⇒ 删掉它（方案 2），
#   而**不是**把它抄成前端值（那只是把漂移盖住、判据仍然不比这一维）。

MENU_NODE = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/MenuNode.java"
USER_INFO_RESPONSE = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/dto/UserInfoResponse.java")
WIRE_TYPES = REPO_ROOT / "frontend/admin-web/src/types/index.ts"
SIDEBAR = REPO_ROOT / "frontend/admin-web/src/components/layout/Sidebar.tsx"


def _menu_item_fields(src: str) -> list[str]:
    """`UserInfoResponse.MenuItem` 的字段名（按声明顺序）—— 服务端菜单下发面的结构真相。"""
    m = re.search(r"public static class MenuItem \{(.*?)\n    \}", src, re.S)
    assert m, "`UserInfoResponse` 里找不到 `MenuItem` 内部类（解析失配 ⇒ 红，不得静默空跑）"
    fields = re.findall(r"private\s+[\w<>,.\s]+?\s(\w+);", m.group(1))
    assert fields, "`MenuItem` 解析出 0 个字段 ⇒ 判据会空跑（fail-closed）"
    return fields


def _wire_menu_item_fields(src: str) -> list[str]:
    """前端 wire 类型 `types/index.ts` 的 `MenuItem` 字段名。"""
    m = re.search(r"// 菜单项类型\nexport interface MenuItem \{(.*?)\n\}", src, re.S)
    assert m, "`types/index.ts` 里找不到菜单项类型 `MenuItem`（解析失配 ⇒ 红）"
    fields = re.findall(r"^\s*(\w+)\??:", m.group(1), re.M)
    assert fields, "前端 `MenuItem` 解析出 0 个字段 ⇒ 判据会空跑（fail-closed）"
    return fields


def _icon_ruling_problems(server_src: str, wire_src: str, node_src: str, sidebar_src: str) -> list[str]:
    """图标裁决判据（**纯函数** ⇒ 可对文本注入验证判别力，见 `test_*_is_caught`）。

    锁的是「**服务端不再持有该字段**」+「前端不留读取点」，而不是「服务端图标 == 前端图标」。
    """
    problems: list[str] = []
    try:
        server = _menu_item_fields(server_src)
    except AssertionError as exc:
        return [f"服务端 `UserInfoResponse.MenuItem` 解析失配：{exc}"]
    if "icon" in server:
        problems.append(
            f"`UserInfoResponse.MenuItem` 仍持有 `icon`（服务端图标字段）—— issue #5217 已裁决"
            f"「图标是前端专属、服务端不下发」（实测无任何生产读取点）。实得字段 = {server}")
    try:
        wire = _wire_menu_item_fields(wire_src)
    except AssertionError as exc:
        return problems + [f"前端 wire `MenuItem` 解析失配：{exc}"]
    if "icon" in wire:
        problems.append(f"前端 wire 类型 `MenuItem` 仍声明 `icon`（服务端已不下发）—— 实得 = {wire}")
    if "icon" in node_src:
        problems.append("`MenuNode`（`GET /api/admin/menus` 的节点）不得有图标字段 —— 权限树本就没有这一维")
    if "from '@/config/menu'" not in sidebar_src:
        problems.append("`Sidebar.tsx` 不再从前端 `@/config/menu` 取菜单（图标真值源）—— 结构变了就同步本判据")
    if ".menus" in sidebar_src:
        problems.append(
            "`Sidebar.tsx` 出现了对「登录下发菜单」的读取点（`.menus`）⇒ 图标维度**不再是**前端专属，"
            "必须改回方案 1（把图标纳入同构判据）")
    return problems


def test_icon_is_frontend_only() -> None:
    """图标**是前端专属**：服务端（DTO / 权限树）不再持有图标字段，前端也不留读取点。"""
    problems = _icon_ruling_problems(
        _read(USER_INFO_RESPONSE), _read(WIRE_TYPES), _read(MENU_NODE), _read(SIDEBAR))
    assert problems == [], "issue #5217 的图标裁决被破坏：\n  - " + "\n  - ".join(problems)


def _inject_wire_icon(src: str) -> str:
    """②：往 `types/index.ts` 的**菜单项类型**里长回 `icon`（锚点必须落在 `MenuItem` 内 ——
    本文件里有别的 `name: string`，按裸 `name: string` 替换会打在别处、注入不生效）。"""
    m = re.search(r"(// 菜单项类型\nexport interface MenuItem \{\n  key: string\n  name: string\n)", src)
    assert m, "`types/index.ts` 的 `MenuItem` 锚点失配 ⇒ 注入无从进行（同步本判据）"
    return src[: m.end()] + "  icon: string\n" + src[m.end():]


#: 五个注入点 —— 每个对应上面一条判据的一种破坏形态（各有一条能单独变红的红证）。
_ICON_INJECTIONS = {
    "① 服务端 DTO 长回 icon 字段": (
        "server", lambda s: s.replace("        private String name;",
                                      "        private String name;\n\n"
                                      "        /** 图标 */\n        private String icon;", 1)),
    "② 前端 wire 类型长回 icon 字段": ("wire", _inject_wire_icon),
    "③ 权限树节点长回 icon 字段": (
        "node", lambda s: s.replace("    private String label;",
                                    "    private String label;\n    private String icon;", 1)),
    "④ 真实侧边栏改从登录下发菜单读（图标不再前端专属）": (
        "sidebar", lambda s: s.replace("import { menuGroups, standaloneItems, type MenuItem, type MenuGroup } "
                                       "from '@/config/menu'", "  const menus = useAuthStore(s => s.user?.menus)",
                                       1)),
    "⑤ 侧边栏不再从前端 config 取菜单": (
        "sidebar", lambda s: s.replace("from '@/config/menu'", "from '@/config/menu-legacy'", 1)),
}


def test_each_icon_ruling_assertion_can_go_red() -> None:
    """注入式红证：**每一条**判据都要有能**单独**变红的负向夹具（否则它只是空断言）。"""
    base = {
        "server": _read(USER_INFO_RESPONSE),
        "wire": _read(WIRE_TYPES),
        "node": _read(MENU_NODE),
        "sidebar": _read(SIDEBAR),
    }
    assert _icon_ruling_problems(*base.values()) == [], (
        "对照组：未注入时裁决判据必须全绿（否则红证无从归因）")
    for label, (which, mutate) in _ICON_INJECTIONS.items():
        parts = dict(base)
        parts[which] = mutate(parts[which])
        assert parts[which] != base[which], f"{label}：注入没生效（锚点失配）—— 同步本判据"
        assert _icon_ruling_problems(*parts.values()), f"{label}：判据没有变红 ⇒ 它是空断言"
