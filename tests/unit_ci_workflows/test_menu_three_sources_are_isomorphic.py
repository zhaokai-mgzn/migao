# case_ids: PG-021, MC-019, UI-028
"""菜单**三处来源全树同构**守卫（issue #4440 起源；**#5271 升级为全树**）—— 治「改一处不红」。

## 病根（issue #4357 关闭评论搬出的如实登记 ②，原文零追踪单）

菜单号称「三处同构」，但**三份各自维护**：

| 来源 | 角色 |
|---|---|
| `frontend/admin-web/src/config/menu.ts` | **真实侧边栏**（`Sidebar.tsx` 只读它） |
| `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE` | `GET /api/admin/menus` 的读面（**前端员工管理页**消费，渲染权限勾选树） |
| `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions` | 登录后下发的菜单（侧边栏数据源之一） |

⇒ 任何一份都可以**静默腐烂**：服务端改了前端不跟（前端只读 `menu.ts`），前端改了服务端不跟
（没有东西比对）⇒ **没有任何东西会变红**（`migao-dev-flow` §19 的「不会红的判据」形态）。

## 🔴 #5271 的升级：原守卫**只比对「生产管理」一个组**

旧实现的判据是「**生产管理组**的节点名列表在三处逐值相等」—— 于是**另外六组与组 key 全部无人校验**，
实测已长出两处**没人发现**的漂移（#5271 一并收口）：

| 漂移 | 前端 | 服务端 |
|---|---|---|
| **组 key 不一致** | `production` | `AuthService` = `production-center` |
| **智能客服组项数不一致** | 2 项（在线接待 / 知识库） | `AuthService` **3 项**（多一个 `chat`「米宝 · 在线对话」/chat，而它在 #3094 已从侧边栏移除） |

本守卫现在比对**全树**，判据见下。

## 判据

1. **组层**（三源逐值相等，含顺序）：`[(组 key, 组名)]` —— 前端 / `MenuController` / `AuthService` 三者一致；
2. **导航节点层**（前端 ↔ `AuthService` 逐值相等，含顺序与组归属）：两处都是**导航**语义，无豁免；
3. **前端 ↔ `MenuController`**：`MenuController` 是**权限目录**（除菜单项外还带**动作码**节点，
   如「新增商品」`product:create`）⇒ 判据取两段：
   - `menu.ts` 的项名必须是该组节点的**前缀子序列**（顺序也一致）；
   - 多出来的节点必须**逐条**命中下方 `ACTION_NODES` 白名单（白名单是**显式枚举**的，
     新增一个动作码节点会被判红 ⇒ 逼人来这里登记理由，而不是静默漂移）。

## 红证（注入式，见文件末尾 `test_each_isomorphism_assertion_can_go_red`）

对三份源码分别做**单点变异**后重跑判据，断言它**变红**（不是「一起红」）：
改前端组名 / 删服务端一组 / 打乱 `AuthService` 项序 / 让任一源解析为空 / 往 `MenuController` 塞一个未登记动作节点。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MENU_TS = REPO_ROOT / "frontend/admin-web/src/config/menu.ts"
MENU_CONTROLLER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java"
AUTH_SERVICE = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java"

#: `MenuController` 里**合法不参与导航**的动作码节点（按组 key 归集）。
#: 每一条都要能说清「它为什么不是菜单项」—— 否则它就该出现在侧边栏里，或该被删掉。
ACTION_NODES: dict[str, set[str]] = {
    # 商品域的动作码（新增/分类在页面内以按钮/内嵌入口承载，非侧边栏项）
    "product-center": {"新增商品", "商品分类管理"},
    # 订单详情是**行内下钻**，不占侧边栏位（列表页点行进详情）
    "trade-center": {"订单详情"},
    # 新增员工是员工管理页的按钮动作
    "org-center": {"新增员工"},
}


def _read(path: Path) -> str:
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf8")


# ══════════════════════════ 三源解析（失配一律 fail-closed） ══════════════════════════


def _parse_frontend(src: str) -> list[tuple[str, str, list[str]]]:
    """`menu.ts` → `[(组 key, 组名, [菜单项名…])]`（保持出现顺序）。

    解析策略（**不依赖缩进/换行形态**，只依赖两件事）：
      · 每个分组以 `children: [` 为锚 —— 组 key / 组名取该锚**之前**最后一次出现的 `key:` / `name:`；
      · 组内项 = `{ key: '…', name: '…', icon: '…', path: '…' }` 形态的单条对象。
    另加**自证**：解析出的项数必须等于该组 body 里 `path:` 的出现次数（否则说明格式漂移把项漏掉了 ⇒ 红）。
    """
    marks = [m.start() for m in re.finditer(r"children:\s*\[", src)]
    assert marks, "`menu.ts` 里找不到任何 `children: [`（解析失配 ⇒ 红，不得静默空跑）"
    # 末组 body 必须止于 `standaloneItems`（否则独立项会被算进最后一个组）
    tail_marks = [m.start() for m in re.finditer(r"export const standaloneItems", src)]
    hard_end = tail_marks[0] if tail_marks else len(src)

    groups: list[tuple[str, str, list[str]]] = []
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else hard_end
        head = src[:start]
        keys = re.findall(r"key:\s*'([^']+)'", head)
        names = re.findall(r"name:\s*'([^']+)'", head)
        assert keys and names, "`menu.ts` 分组锚点前取不到 `key:` / `name:`（解析失配 ⇒ 红）"
        body = src[start:end]
        items = re.findall(
            r"\{\s*key:\s*'([^']+)',\s*name:\s*'([^']+)',\s*icon:\s*'([^']+)',\s*path:\s*'([^']+)'",
            body,
        )
        n_paths = len(re.findall(r"\bpath:\s*'", body))
        assert len(items) == n_paths, (
            f"`menu.ts` 第 {i + 1} 组解析出 {len(items)} 项，但该组 body 里有 {n_paths} 个 `path:` "
            f"⇒ 解析失配（格式漂移会把项静默漏掉）⇒ 红，请同步本解析器")
        groups.append((keys[-1], names[-1], [name for _, name, _, _ in items]))

    assert groups, "`menu.ts` 解析出 0 个分组 ⇒ 判据会空跑（fail-closed）"
    if tail_marks:
        standalone = re.findall(
            r"\{\s*key:\s*'([^']+)',\s*name:\s*'([^']+)',\s*icon:\s*'[^']+',\s*path:\s*'[^']+'",
            src[hard_end:],
        )
        assert standalone, "`standaloneItems` 解析出 0 项（解析失配 ⇒ 红，独立项也是导航的一部分）"
    return groups


def _parse_controller(src: str) -> list[tuple[str, str, list[str]]]:
    """`MenuController.MENU_TREE` → `[(组 key, 组名, [节点 label…])]`（按组内 `List.of(...)` 的变量顺序）。"""
    decls = dict(re.findall(r'MenuNode\s+(\w+)\s*=\s*new MenuNode\("[^"]+",\s*"([^"]+)"\)', src))
    assert decls, "`MenuController` 解析出 0 个 MenuNode 声明（解析失配 ⇒ 红，不得静默空跑）"
    groups: list[tuple[str, str, list[str]]] = []
    for gkey, gname, vars_blob in re.findall(
        r'new MenuNode\("([^"]+)",\s*"([^"]+)",\s*List\.of\(([^)]*)\)\)', src
    ):
        names: list[str] = []
        for var in [v.strip() for v in vars_blob.split(",") if v.strip()]:
            assert var in decls, f"组 `{gkey}` 内的变量 `{var}` 找不到对应 MenuNode 声明（解析失配 ⇒ 红）"
            names.append(decls[var])
        assert names, f"`{gname}` 组解析出 0 个节点 ⇒ 判据会空跑（fail-closed）"
        groups.append((gkey, gname, names))
    assert groups, "`MenuController` 解析出 0 个分组 ⇒ 判据会空跑（fail-closed）"
    return groups


def _parse_auth(src: str) -> list[tuple[str, str, list[str]]]:
    """`AuthService.buildMenusByPermissions` → `[(组 key, 组名, [菜单项名…])]`。

    组锚 = `menuGroup("<key>", "<name>", <childrenVar>)`（**出现顺序即下发顺序**）；
    组内项 = 该 `childrenVar` 上按出现顺序的 `menuItem("<key>", "<name>", "<path>")`。
    """
    group_refs = re.findall(r'menuGroup\("([^"]+)",\s*"([^"]+)",\s*(\w+)\)', src)
    assert group_refs, "`AuthService` 里找不到任何 `menuGroup(...)`（解析失配 ⇒ 红，不得静默空跑）"
    groups: list[tuple[str, str, list[str]]] = []
    for gkey, gname, var in group_refs:
        names = re.findall(rf'{re.escape(var)}\.add\(menuItem\("[^"]+",\s*"([^"]+)",\s*"[^"]+"\)\)', src)
        assert names, (
            f"`AuthService` 的组 `{gkey}`（children 变量 `{var}`）解析出 0 项 ⇒ 判据会空跑（fail-closed）")
        groups.append((gkey, gname, names))
    return groups


# ══════════════════════════ 判据本体（纯函数 ⇒ 可对文本注入验证判别力） ══════════════════════════


def _isomorphism_problems(front_src: str, ctrl_src: str, auth_src: str) -> list[str]:
    """三源全树同构判据。返回问题清单（空 = 通过）。**纯函数**，便于注入式红证。"""
    problems: list[str] = []
    try:
        front = _parse_frontend(front_src)
        ctrl = _parse_controller(ctrl_src)
        auth = _parse_auth(auth_src)
    except AssertionError as exc:
        return [f"解析失配（判据无法空跑通过）：{exc}"]

    front_layer = [(k, n) for k, n, _ in front]
    ctrl_layer = [(k, n) for k, n, _ in ctrl]
    auth_layer = [(k, n) for k, n, _ in auth]

    if front_layer != ctrl_layer:
        problems.append(
            f"**组层**不一致：前端 `menu.ts` 与 `MenuController.MENU_TREE`（`GET /api/admin/menus`，"
            f"员工管理页渲染权限树）的「组 key + 组名 + 顺序」必须逐值相等\n"
            f"  前端 = {front_layer}\n  服务端 = {ctrl_layer}")
    if front_layer != auth_layer:
        problems.append(
            f"**组层**不一致：前端 `menu.ts` 与 `AuthService.buildMenusByPermissions`（登录下发）"
            f"的「组 key + 组名 + 顺序」必须逐值相等\n"
            f"  前端 = {front_layer}\n  服务端 = {auth_layer}")

    # ── 导航节点层：前端 ↔ AuthService（两处都是导航语义，无豁免）──
    if front_layer == auth_layer:
        for (fk, fn, fitems), (_, _, aitems) in zip(front, auth):
            if fitems != aitems:
                problems.append(
                    f"组「{fn}」(`{fk}`) 的**菜单项**在前端与 `AuthService` 不一致（含顺序）：\n"
                    f"  前端 = {fitems}\n  服务端 = {aitems}\n"
                    f"⇒ 登录下发的菜单与真实侧边栏对不上")

    # ── 前端 ↔ MenuController：导航项是前缀子序列，多出的必须是已登记动作节点 ──
    if front_layer == ctrl_layer:
        for (fk, fn, fitems), (_, _, citems) in zip(front, ctrl):
            allowed = ACTION_NODES.get(fk, set())
            head = citems[: len(fitems)]
            if head != fitems:
                problems.append(
                    f"组「{fn}」(`{fk}`) 的**导航节点**在 `MenuController` 里不是前端菜单项的前缀子序列"
                    f"（顺序也必须一致）：\n  前端 = {fitems}\n  服务端前 {len(fitems)} 项 = {head}")
            extra = [x for x in citems[len(fitems):] if x not in allowed]
            if extra:
                problems.append(
                    f"组「{fn}」(`{fk}`) 的 `MenuController` 多出**未登记**的动作码节点 {extra} —— "
                    f"要么它其实是菜单项（那就补进 `menu.ts`），要么来本文件 `ACTION_NODES` 登记"
                    f"「它为什么不是菜单项」（当前已登记 = {sorted(allowed)}）")
            missing = [x for x in allowed if x not in citems]
            if missing:
                problems.append(
                    f"组「{fn}」(`{fk}`) 的 `ACTION_NODES` 登记了 {missing}，但 `MenuController` 里"
                    f"没有这些节点 ⇒ 白名单过期（要么补节点、要么删登记，不许挂着）")
    return problems


def test_menu_is_isomorphic_across_three_sources() -> None:
    """三源（前端 / `MenuController` / `AuthService`）**全树**同构。"""
    problems = _isomorphism_problems(_read(MENU_TS), _read(MENU_CONTROLLER), _read(AUTH_SERVICE))
    assert problems == [], "菜单三源不同构（改一处不红 = 允许静默腐烂）：\n  - " + "\n  - ".join(problems)


#: 注入点 —— 每个对应上面一条判据的一种破坏形态（各有一条能**单独**变红的红证）
def _inject_front_group_rename(src: str) -> str:
    return src.replace("name: '交易管理',", "name: '订单管理',", 1)


def _inject_controller_drop_group(src: str) -> str:
    """删掉 `inventory-center` 那一个顶层组的**挂载**（声明保留 ⇒ 只动组层）。"""
    m = re.search(r'\n\s*new MenuNode\("inventory-center".*?\)\)\,', src, re.S)
    assert m, "注入锚点失配：`MenuController` 里找不到 inventory-center 组挂载"
    return src[: m.start()] + src[m.end():]


def _inject_auth_swap_items(src: str) -> str:
    """打乱 `AuthService` 交易组的项序（订单列表 ↔ 售后工单 的 add 顺序）。"""
    a = 'tradeChildren.add(menuItem("orders", "订单列表", "/orders"));'
    b = 'tradeChildren.add(menuItem("after-sales", "售后工单", "/after-sales"));'
    assert a in src and b in src, "注入锚点失配：`AuthService` 交易组的两个 add 语句找不到"
    return src.replace(a, "@@TMP@@", 1).replace(b, a, 1).replace("@@TMP@@", b, 1)


def _inject_controller_extra_node(src: str) -> str:
    """往 `MenuController` 生产管理组塞一个**未登记**的动作节点。"""
    m = re.search(r'new MenuNode\("production-center", "生产管理", List\.of\(([^)]*)\)\)', src)
    assert m, "注入锚点失配：`MenuController` 里找不到 production-center 组"
    return src.replace(
        m.group(0),
        'new MenuNode("production-center", "生产管理", List.of(pr1, pr1, ' + m.group(1) + "))",
        1,
    )


def _inject_empty_source(src: str) -> str:
    return "// 什么都不剩\n"


_INJECTIONS: dict[str, tuple[str, object]] = {
    "① 前端改一个组名（组层漂移）": ("front", _inject_front_group_rename),
    "② MenuController 少一个组（组层漂移）": ("ctrl", _inject_controller_drop_group),
    "③ AuthService 打乱组内项序（导航节点层漂移）": ("auth", _inject_auth_swap_items),
    "④ MenuController 多一个未登记动作节点": ("ctrl", _inject_controller_extra_node),
    "⑤ 任一源解析为空（判据空跑）": ("front", _inject_empty_source),
}


def test_each_isomorphism_assertion_can_go_red() -> None:
    """注入式红证：**每一条**判据都要有能**单独**变红的负向夹具（否则它只是空断言）。"""
    base = {
        "front": _read(MENU_TS),
        "ctrl": _read(MENU_CONTROLLER),
        "auth": _read(AUTH_SERVICE),
    }
    assert _isomorphism_problems(*base.values()) == [], "对照组：未注入时判据必须全绿（否则红证无从归因）"
    for label, (which, mutate) in _INJECTIONS.items():
        parts = dict(base)
        parts[which] = mutate(parts[which])  # type: ignore[operator]
        assert parts[which] != base[which], f"{label}：注入没生效（锚点失配）—— 同步本判据"
        assert _isomorphism_problems(*parts.values()), f"{label}：判据没有变红 ⇒ 它是空断言"


# ══════════════ 图标维度：**不参与同构**（issue #5217 裁决 = 方案 2「图标是前端专属」） ══════════════
#
# 裁决依据（**实测**，复算命令见 PR body；不是推断）：
#   · `MenuNode.java`（`GET /api/admin/menus` 的节点 DTO）只有 `code/label/children`
#     —— 服务端权限树**结构上就没有**图标这一维 ⇒ 方案 1「三源图标逐字一致」需先**新增**该字段；
#   · 前端对「登录下发菜单」的读取点**只有** `frontend/admin-web/src/types/index.ts` 的
#     `User.menus` 类型声明与 `frontend/admin-web/src/store/auth.ts` 的透传赋值
#     —— **没有任何生产读取点**读 `menus[].icon`（真实侧边栏
#     `frontend/admin-web/src/components/layout/Sidebar.tsx` 的图标取自 `@/config/menu` +
#     `@/config/menu-icons`，见 #5271 的注册表抽离）；
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
        "sidebar", lambda s: s.replace("import { menuGroups, standaloneItems, type MenuItem } "
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