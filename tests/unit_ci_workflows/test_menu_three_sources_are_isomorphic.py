# case_ids: PG-021
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
