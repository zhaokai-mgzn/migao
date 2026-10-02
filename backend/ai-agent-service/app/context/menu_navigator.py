"""米宝「导航类」指引的真值源（issue #5989 · P1）—— `功能 ⇄ 菜单路径 ⇄ 权限码 ⇄ 该角色可见性` + **默认拒绝**。

## 用户裁定（2026-10-02，逐字口径）

| 问题 | 裁定 |
|---|---|
| 真值源 | **C · 混合**：**结构性事实**（有哪些功能 / 在哪一页 / 你这角色能不能看）走**登记表**；**步骤/图文**留给知识卡片（**本包不做**） |
| 第一批范围 | **只做「导航类」**：只回答「**这个功能在哪一页 / 你这角色有没有权限**」；**不写操作步骤** |
| 问「怎么做」 | 给导航答案 + **如实说「我没有步骤级指引」**；**禁止 LLM 编步骤** |

## 病根（为什么必须有机械判据）

今天**没有任何**「功能 ↔ 页面 ↔ 角色可见性」的真值源：

- `app/context/page_registry.py`（族 4）只管「**你现在这一页**的数字/字段从哪来」，
  docstring 明写**不做知识库构建**、**不给操作步骤**；
- `knowledge_search` 的知识卡片是**面向顾客**的店务知识（faq/product/measure/aftersale/config），
  **不是**系统使用指引；
- 既有收口 #5454/#5457 只保证**话术里提到的菜单名是真的**（名字对），
  **不保证**「该功能在哪一页」「这个角色看不看得到」。

⇒ 没有真值源时，模型对「XX 在哪一页」只能**编**，而编出来的页面/权限无法被任何判据抓住。

## 三条纪律（缺一不可，逐条有判据）

1. **两层真值（混合口径的落点）**
   - **结构层**：`MENU_TREE` 是 `frontend/admin-web/src/config/menu.ts` 的**镜像**（节点 key /
     菜单名 / 路径 / 权限码），由判据**逐节点、逐字段、逐序**核（`ORDER_LOCKED`）；
     `menu.ts` 是菜单**单一源**，本文件**不解释**它、只镜像它。
   - **语义层（意图 → 功能）**：只能**显式登记**在 `NAV_FEATURES` 里。
     🔴 **不让 LLM 挑、不做自由匹配、不做近似匹配** —— 匹配是**确定性最长前缀**（`resolve_feature`），
     命中不了就 `None`。
2. **未登记 ⇒ 默认拒绝**（fail-closed）：`resolve_feature` 未命中 ⇒ 工具不返回任何路径/权限码，
   只说「我没有这条指引」。**不猜「可能在哪」**。
3. **角色裁剪**：可见性**只按服务端会话的 `permissions`** 判（`ToolContext.permissions`），
   **不读任何客户端递交的 role / roleName**（与 `page_registry.py` 同纪律）；
   无权 ⇒ **不把路径与权限码说出去**，但仍然 **citation 可溯**（引登记项 → 菜单节点）。

## 派生的机器可核部分（**不手抄第二份**）

- **路径 / 权限码 / 菜单名**：全部来自 `MENU_TREE`（= `menu.ts` 的镜像），
  `NAV_FEATURES` **只登记节点 key**，路径与码**派生** ⇒ 登记项引用不存在的节点即红；
- **权限码目录**：判据逐值核 `RegistrationService` / `PermissionService` 的权限目录
  （复用 `tests/unit_ci_workflows/test_agent_permission_parity.py` 的解析器，**不造第二套**）。

## 为 P2（主动新手引导）预留的接口

`visible_nodes(permissions)` / `nodes_for_feature()` / `resolve_feature()` 已经同时回答
「**这一页有什么**（节点 key + 菜单名 + 路径 + 码）」与「**哪些角色能看**（按会话权限现算）」——
P2 的推送面直接复用本模块，**不要另造第二份真值**（本包只提供接口，不做推送）。

## 明确不做（照实登记）

- **不做步骤/图文**：知识卡片的面（业务方维护），本模块结构上不含 steps 字段；
- **不做自由匹配 / 同义词推断 / 拼音纠错**：别名必须**是菜单名的一部分**（或含菜单名），
  判据逐条核（`_alias_is_grounded`）—— 这一条把「别名表退化成同义词词典」的漂移堵在门外；
- **不查实体、不调 admin-api**：纯本地只读（无 HTTP 调用点 ⇒ 登记进 `LOCAL_ONLY_TOOLS`）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Optional, Sequence, Tuple

#: 菜单组（`menu.ts` 的 `menuGroups`）—— key 与组名逐字同源，顺序即渲染顺序。
MENU_GROUPS: Tuple[Tuple[str, str], ...] = (
    ("workspace", "工作台"),
    ("customer-service", "客户服务"),
    ("trade-center", "交易管理"),
    ("production-center", "生产管理"),
    ("inventory-center", "仓储与物料"),
    ("org-center", "组织管理"),
)

#: 一级独立菜单项（`menu.ts` 的 `standaloneTopItems` / `standaloneItems`）的组归属哨兵。
#: 它们**不在任何组里** —— 用字面量而不是空串，避免「漏填」与「真的没有组」长得一样。
STANDALONE_GROUP = "(一级独立项)"


@dataclass(frozen=True)
class MenuNode:
    """`menu.ts` 的一个**导航型**节点（有 `path` 才有它）。

    **派生关系**：`group` / `label` / `path` / `permission_code` 四列全部来自 `menu.ts`，
    本文件不新增第五列（`MENU_TREE_ORDER_LOCKED` 逐节点逐字段核）。
    """

    group: str
    label: str
    path: str
    permission_code: str


#: `menu.ts` 的**全量导航节点**（issue #5989 现取：6 组 19 项 + 2 个一级独立项 = 21）。
#: 顺序 = `menu.ts` 的渲染顺序；判据按 `MENU_TREE_ORDER_LOCKED` 比对（**顺序也锁**，
#: 因为「一级项插在哪个组之后」在 `menu.ts` 里是一门被用户裁定过的信息架构）。
MENU_TREE: Tuple[MenuNode, ...] = (
    # 工作台
    MenuNode("workspace", "经营看板", "/dashboard", "dashboard:view"),
    MenuNode("workspace", "每日简报", "/briefing", "dashboard:view"),
    # 客户服务
    MenuNode("customer-service", "在线接待", "/agent-workspace/human-sessions", "agent:session"),
    MenuNode("customer-service", "客户列表", "/customers", "customer:view"),
    MenuNode("customer-service", "知识库", "/knowledge", "knowledge:view"),
    MenuNode("customer-service", "售后工单", "/after-sales", "after_sales:view"),
    # 交易管理
    MenuNode("trade-center", "订单列表", "/orders", "order:list"),
    MenuNode("trade-center", "财务对账", "/finance", "finance:view"),
    # 生产管理
    MenuNode("production-center", "生产看板", "/production", "production:view"),
    MenuNode("production-center", "智能派单", "/production/pool", "processing:view"),
    MenuNode("production-center", "加工项管理", "/production/processing", "production:view"),
    MenuNode("production-center", "工艺配置", "/production/routings", "production:view"),
    MenuNode("production-center", "计件工资", "/production/piecework", "production:view"),
    # 仓储与物料
    MenuNode("inventory-center", "入库单", "/inbound-orders", "inbound:view"),
    MenuNode("inventory-center", "发货单", "/shipments", "order:list"),
    MenuNode("inventory-center", "余料台账", "/production/remnants", "processing:manage"),
    MenuNode("inventory-center", "省料看板", "/production/saving-board", "product:list"),
    # 组织管理
    MenuNode("org-center", "员工管理", "/employees", "employee:list"),
    MenuNode("org-center", "岗位权限", "/roles", "system:view"),
    MenuNode("org-center", "企业基础信息", "/settings", "system:manage"),
    # 一级独立项（`standaloneTopItems` 的「商品管理」+ `standaloneItems` 的「通知中心」）
    MenuNode(STANDALONE_GROUP, "商品管理", "/products", "product:list"),
    MenuNode(STANDALONE_GROUP, "通知中心", "/notifications", ""),
)

#: 判据的**核对锚**（issue #5989）：与 `MENU_TREE` 逐节点逐字段比对的**有序**四元组序列。
#: 为什么另立一份而不是「直接读 MENU_TREE」：**注入式红证要能改一处而别的读法不变**
#: —— 判据读的是本锚，`MENU_TREE` 是被测对象；两者不一致 ⇒ 红（含顺序、含空码节点）。
MENU_TREE_ORDER_LOCKED: Tuple[Tuple[str, str, str, str], ...] = tuple(
    (n.group, n.label, n.path, n.permission_code) for n in MENU_TREE
)


@dataclass(frozen=True)
class NavFeature:
    """一条**显式登记**的「意图 → 功能 → 菜单节点」（语义层，**只能人登记**）。

    `node_keys` 里放的是 `MENU_TREE` 的 `(group, label)` —— **不是**路径、**不是**权限码：
    路径与码一律从 `MENU_TREE` 派生（这样 `menu.ts` 改了路径/码，本表不需要跟改，
    但会**当场判红**直到本表与镜像对齐）。
    """

    #: 登记项 id（citation 的可追溯锚：`登记项 #<id>`）
    feature_id: str
    #: 功能名（上屏用；建议逐字等于主菜单名）
    label: str
    #: 该功能落在哪些菜单节点（多节点 = 同一功能分布在多页，各自独立裁剪）
    node_keys: Tuple[Tuple[str, str], ...]
    #: **登记**的意图台词（枢纽词）—— 必须**是某个被登记菜单名的一部分**（或包含它）
    aliases: Tuple[str, ...]


#: 意图 → 功能登记表（**第一批：只做导航类**；未登记 ⇒ 默认拒绝）。
#: 🔴 新增条目 = 显式改本表（语义判断必须人做），**不许**改成「模糊匹配 menu.ts 的菜单名」。
#: 🔴 **别名的硬约束**：每个别名**必须**是它所属节点菜单名的一部分（或含菜单名）——
#: 导入期自检 + 判据 `problems_aliases_grounded` 双重拦截「别名表退化成同义词词典」。
#: ⇒ 表里只会出现**菜单名的子串**（如「订单管理」之于「订单列表」不行、「订单列表」之于
#: 「订单列表」才行）—— 想要新说法，就把它做成菜单名的一部分，别在别名里偷偷扩同义词。
NAV_FEATURES: Tuple[NavFeature, ...] = (
    NavFeature("dashboard", "经营看板", (("workspace", "经营看板"),), ("经营看板", "经营看板数据")),
    NavFeature("briefing", "每日简报", (("workspace", "每日简报"),), ("每日简报", "每日简报页")),
    NavFeature(
        "human-sessions",
        "在线接待",
        (("customer-service", "在线接待"),),
        ("在线接待", "在线接待会话"),
    ),
    NavFeature("customers", "客户列表", (("customer-service", "客户列表"),), ("客户列表", "客户列表管理")),
    NavFeature("knowledge", "知识库", (("customer-service", "知识库"),), ("知识库", "知识库管理")),
    NavFeature(
        "after-sales",
        "售后工单",
        (("customer-service", "售后工单"),),
        ("售后工单", "售后工单管理"),
    ),
    NavFeature("orders", "订单列表", (("trade-center", "订单列表"),), ("订单列表", "订单列表页")),
    NavFeature("finance", "财务对账", (("trade-center", "财务对账"),), ("财务对账", "财务对账页")),
    NavFeature(
        "production-board",
        "生产看板",
        (("production-center", "生产看板"),),
        ("生产看板", "生产看板页"),
    ),
    NavFeature(
        "production-pool",
        "智能派单",
        (("production-center", "智能派单"),),
        ("智能派单", "智能派单池"),
    ),
    NavFeature(
        "processing-items",
        "加工项管理",
        (("production-center", "加工项管理"),),
        ("加工项管理", "加工项管理页"),
    ),
    NavFeature(
        "production-process",
        "工艺配置",
        (("production-center", "工艺配置"),),
        ("工艺配置", "工艺配置页"),
    ),
    NavFeature(
        "piecework",
        "计件工资",
        (("production-center", "计件工资"),),
        ("计件工资", "计件工资表"),
    ),
    NavFeature(
        "inbound-orders",
        "入库单",
        (("inventory-center", "入库单"),),
        ("入库单", "入库单列表"),
    ),
    NavFeature("shipments", "发货单", (("inventory-center", "发货单"),), ("发货单", "发货单列表")),
    NavFeature(
        "remnants",
        "余料台账",
        (("inventory-center", "余料台账"),),
        ("余料台账", "余料台账页"),
    ),
    NavFeature(
        "saving-board",
        "省料看板",
        (("inventory-center", "省料看板"),),
        ("省料看板", "省料看板页"),
    ),
    NavFeature("employees", "员工管理", (("org-center", "员工管理"),), ("员工管理", "员工管理页")),
    NavFeature("roles", "岗位权限", (("org-center", "岗位权限"),), ("岗位权限", "岗位权限页")),
    NavFeature(
        "settings",
        "企业基础信息",
        (("org-center", "企业基础信息"),),
        ("企业基础信息", "企业基础信息页"),
    ),
    NavFeature("products", "商品管理", ((STANDALONE_GROUP, "商品管理"),), ("商品管理", "商品管理页")),
    NavFeature(
        "notifications",
        "通知中心",
        ((STANDALONE_GROUP, "通知中心"),),
        ("通知中心", "通知中心页"),
    ),
)

#: 所有节点都**不需要**权限码时的哨兵（`通知中心` 是全员可见项）。
NO_PERMISSION_CODE = ""

#: 未登记 / 未命中时的**如实告知**（**常量**，不含任何路径、权限码或猜测）。
NAV_NOT_REGISTERED_NOTICE = (
    "⚠️ 这条问题没有命中登记在册的「功能 → 页面 → 权限」登记项 —— 我**不确定**它在哪一页，"
    "**没有**这条指引。请**如实**告知用户你不确定，"
    "并请他把功能名说清楚（或去「帮助 / 反馈」提一下）；"
    "**不要**猜测页面，**不要**按猜测的页面口径作答。"
)

#: 任何回答都必须带上的**步骤禁令**（用户裁定：禁止 LLM 编步骤）。
NO_STEPS_NOTICE = (
    "🔴 本轮只有**导航类**信息（功能在哪个页面 + 你这角色有没有权限）："
    "**不得**把它扩写成逐步指引、图文说明或操作顺序；"
    "用户问「怎么做」时，给导航答案 + **如实说「我没有步骤级指引」**。"
)


class MenuNavigatorError(ValueError):
    """登记表自检失败（导入期即抛 ⇒ 未登记/写错的条目**不生效**，不是被放行）。"""


# ── 登记表自检（导入期 fail-closed；判据另有独立实现，见 tests/test_menu_navigator.py）──


def _node_index() -> Dict[Tuple[str, str], MenuNode]:
    index: Dict[Tuple[str, str], MenuNode] = {}
    for node in MENU_TREE:
        key = (node.group, node.label)
        if key in index:
            raise MenuNavigatorError(f"MENU_TREE 里节点 key 重复：{key}")
        if not node.path.startswith("/"):
            raise MenuNavigatorError(f"MENU_TREE 节点 {key} 的 path 不是绝对路径：{node.path!r}")
        index[key] = node
    if not index:
        raise MenuNavigatorError("MENU_TREE 为空 ⇒ 一切查询都会退化成「未登记」（fail-closed 的空转）")
    return index


_NODES: Dict[Tuple[str, str], MenuNode] = _node_index()


def _self_check() -> None:
    """导入期自检：**结构层与语义层必须自洽**，不自洽 ⇒ 直接抛（不静默降级）。"""
    if tuple((n.group, n.label, n.path, n.permission_code) for n in MENU_TREE) != (
        MENU_TREE_ORDER_LOCKED
    ):
        raise MenuNavigatorError("MENU_TREE 与 MENU_TREE_ORDER_LOCKED 不一致（镜像漂移）")
    seen: set[str] = set()
    for feature in NAV_FEATURES:
        if feature.feature_id in seen:
            raise MenuNavigatorError(f"NAV_FEATURES 里 feature_id 重复：{feature.feature_id}")
        seen.add(feature.feature_id)
        if not feature.node_keys:
            raise MenuNavigatorError(f"{feature.feature_id}：node_keys 为空 ⇒ 无从回答「在哪一页」")
        for key in feature.node_keys:
            if key not in _NODES:
                raise MenuNavigatorError(
                    f"{feature.feature_id}：引用了 MENU_TREE 里不存在的节点 {key}（未登记即不生效）"
                )
        if not feature.aliases:
            raise MenuNavigatorError(f"{feature.feature_id}：aliases 为空 ⇒ 这条登记永远匹配不到")
        labels = {_NODES[k].label for k in feature.node_keys}
        for alias in feature.aliases:
            if not any(alias in label or label in alias for label in labels):
                raise MenuNavigatorError(
                    f"{feature.feature_id}：别名 {alias!r} 不是任何被登记菜单名的一部分"
                    f"（{sorted(labels)}）⇒ 别名表正在退化成同义词词典（禁止自由匹配）"
                )


_self_check()


def menu_node(group: str, label: str) -> Optional[MenuNode]:
    """节点查询；未登记 ⇒ `None`（默认拒绝）。"""
    return _NODES.get((group, label))


def nodes_for_feature(feature_id: str) -> Tuple[MenuNode, ...]:
    """功能 id → 其登记的菜单节点；**未登记 ⇒ 空元组**（不猜）。"""
    for feature in NAV_FEATURES:
        if feature.feature_id == feature_id:
            return tuple(_NODES[k] for k in feature.node_keys)
    return ()


def has_permissions(required: Sequence[str], permissions: Any) -> bool:
    """权限判定 —— 与既有口径逐字同源（`menu-nav.hasPermission` / `base_tool.check_permission` /
    `page_registry.has_permissions`）：`*` = 通配全权限；无声明码 = 不设限。
    """
    codes = [c for c in required if c]
    if not codes:
        return True
    if not isinstance(permissions, (list, tuple, set, frozenset)):
        return False
    if "*" in permissions:
        return True
    return all(code in permissions for code in codes)


def visible_nodes(permissions: Any) -> Tuple[MenuNode, ...]:
    """**P2 预留接口**：这一份权限**能看见**的全部菜单节点（按 `MENU_TREE` 顺序）。

    `menu.ts` 的可见性口径 = 「无码节点全员可见 ∧ 有码节点需持该码」—— 与
    `frontend/admin-web/src/lib/menu-nav.ts` / `Sidebar.tsx` 的过滤口径同源。
    """
    return tuple(n for n in MENU_TREE if has_permissions((n.permission_code,), permissions))


def _match_length(text: str, feature: NavFeature) -> int:
    """该功能在 `text` 里按**登记别名**命中的**最长长度**；未命中 ⇒ 0。"""
    best = 0
    for alias in feature.aliases:
        if alias and alias in text:
            best = max(best, len(alias))
    return best


def resolve_feature(query: str) -> Optional[NavFeature]:
    """用户问题 → 登记的**功能**；**未登记 ⇒ `None`**（默认拒绝，不猜、不近似匹配）。

    匹配口径（**确定性、可复算**）：在**登记别名的并集**上取**最长命中**；同长度命中多条
    ⇒ `None`（歧义**不猜**，与 `base_skill` 的「歧义即 fail-closed 不并」同族）。
    别名必须**是菜单名的一部分**（导入期自检），故这里不存在「自由匹配」。
    """
    if not isinstance(query, str):
        return None
    text = query.strip()
    if not text:
        return None
    hits: list[Tuple[int, NavFeature]] = []
    for feature in NAV_FEATURES:
        length = _match_length(text, feature)
        if length:
            hits.append((length, feature))
    if not hits:
        return None
    longest = max(length for length, _ in hits)
    winners = [feature for length, feature in hits if length == longest]
    if len(winners) != 1:
        return None
    return winners[0]


@dataclass(frozen=True)
class NavigationAnswer:
    """一条导航答案（**结构上不含 steps**：只有页面 + 权限 + citation）。"""

    #: 登记项 id（citation 左端）
    feature_id: str
    #: 功能名
    label: str
    #: 该角色**能看**的节点（路径 + 需要的码）
    granted: Tuple[MenuNode, ...]
    #: 该功能登记、但该角色**看不到**的节点（**只出菜单名，不出路径/码**）
    denied: Tuple[MenuNode, ...]
    #: 未命中任何登记项 ⇒ `feature_id` 为空、`granted`/`denied` 皆空
    registered: bool = True

    @property
    def citation(self) -> str:
        """citation —— **登记项 → 菜单节点**（可追溯；未登记时如实说明未登记）。"""
        if not self.registered:
            return "登记项：（无）—— 未命中「功能 → 页面 → 权限」登记表"
        nodes = "、".join(
            f"{'菜单组' if n.group != STANDALONE_GROUP else '一级项'}「{n.label}」"
            for n in (*self.granted, *self.denied)
        )
        return f"登记项 #{self.feature_id} → 菜单节点 {nodes}"

    def to_data(self) -> Dict[str, Any]:
        """给模型的**结构化载荷**（键白名单：**没有** steps / 操作说明 / 图文）。"""
        return {
            "registered": self.registered,
            "featureId": self.feature_id,
            "label": self.label,
            "pages": [
                {
                    "menuGroup": n.group,
                    "menuName": n.label,
                    "path": n.path,
                    "requiredPermission": n.permission_code,
                }
                for n in self.granted
            ],
            # 无权节点：**只出菜单名**（连菜单名都不出的话用户没法去申请权限；
            # 但路径与码属于「看不到这一页的人不该拿到的结构事实」）
            "deniedMenuNames": [n.label for n in self.denied],
            "citation": self.citation,
        }

    def render(self) -> str:
        """给模型的**导航描述**（`message`）。**只描述页面与权限**，不含任何操作步骤。"""
        if not self.registered:
            return NAV_NOT_REGISTERED_NOTICE
        if not self.granted:
            names = "、".join(n.label for n in self.denied)
            return (
                f"「{self.label}」在菜单节点「{names}」下（{self.citation}）；"
                f"但你**这个角色没有权限**进入该页面 —— 请如实告知用户「你看不到这个页面」，"
                f"并提示他联系管理员开通对应权限。**不要**给出页面路径。"
            )
        parts = [
            f"「{n.label}」（菜单路径 `{n.path}`，需要的权限码 `{n.permission_code or '（无需权限码）'}`）"
            for n in self.granted
        ]
        lines = [f"「{self.label}」在：" + "；".join(parts) + f"。{self.citation}"]
        if self.denied:
            lines.append(
                "另有登记节点「" + "、".join(n.label for n in self.denied)
                + "」你这个角色看不到（**不要**给出其路径）。"
            )
        lines.append("（以上仅为导航信息；用户若要操作步骤，如实说没有步骤级指引。）")
        return "".join(lines)


def build_navigation_answer(query: str, permissions: Any) -> NavigationAnswer:
    """问题 + **服务端会话权限** → 导航答案（**任何一步不成立都 fail-closed**）。

    判据顺序：
    1. 未命中登记项 ⇒ `NavigationAnswer(registered=False)`（**不带任何路径/码**）；
    2. 逐节点按会话权限裁剪（`permissions` 只能来自 `ToolContext`，服务端会话）；
    3. 全部节点都无权 ⇒ `granted` 为空（调用方不得把路径说出去）。

    ⚠️ 本函数**不读 role**：角色→权限的映射是服务端的既有能力（`agent:session` claim），
    这里只看**已经取到的权限码**（与 `page_registry.build_page_context` 同纪律）。
    """
    feature = resolve_feature(query)
    if feature is None:
        return NavigationAnswer("", "", (), (), registered=False)
    granted: list[MenuNode] = []
    denied: list[MenuNode] = []
    for key in feature.node_keys:
        node = _NODES[key]
        (granted if has_permissions((node.permission_code,), permissions) else denied).append(node)
    return NavigationAnswer(
        feature_id=feature.feature_id,
        label=feature.label,
        granted=tuple(granted),
        denied=tuple(denied),
    )


def registered_feature_ids() -> FrozenSet[str]:
    """已登记的功能 id 集（判据与 P2 用；现算，不手抄）。"""
    return frozenset(f.feature_id for f in NAV_FEATURES)


def registered_aliases() -> Iterable[str]:
    """已登记的全部别名（判据用：核「别名不撞车」）。"""
    for feature in NAV_FEATURES:
        yield from feature.aliases

# ══════════════════════════════════════════════════════════════════════════════
# P2（主动新手引导，issue #5989 下半场）—— 推送面：**只推导航，不推步骤**
# ══════════════════════════════════════════════════════════════════════════════
#
# 用户裁定（2026-10-02）：**A** 形态 —— 「用户**首次进入某个已登记页面**时，米宝在**对话区**
# 主动发一条**导航提示**」（每页每会话最多 1 次 · 只推该角色可见的 · 未登记页面不推 · 只给导航不给步骤）。
#
# 本段**不建任何推送基础设施**（无 SSE 主动推 / 无定时 / 无队列）：运输形态 = **客户端首次进页时
# 带 `page_context` 发一轮**（族 4 既有运输形态），服务端**只做判定**（发不发 / 发什么）。
# ⇒ 判定是**纯函数**（登记表 + 会话权限 + 已推集，三样都是入参或仓内真值）。

#: 推送判定的**不发**理由（枚举即契约；判据逐值核「四种都存在」，且**不推时理由必命中闭集**）。
PUSH_REASON_UNREGISTERED = "unregistered"        # 未登记页面 ⇒ 不推（默认拒绝）
PUSH_REASON_NOT_VISIBLE = "not_visible"          # 该角色看不到这一页 ⇒ 不推（越权面）
PUSH_REASON_ALREADY_PUSHED = "already_pushed"    # 本会话已推过这一页 ⇒ 不推（骚扰面）
PUSH_REASON_AMBIGUOUS_ROUTE = "ambiguous_route"  # route ↔ 功能不是一一对应 ⇒ 不推（不猜）

#: 不发理由的**闭集**（新增理由必须同批登记进本元组）。
PUSH_REASONS: Tuple[str, ...] = (
    PUSH_REASON_UNREGISTERED,
    PUSH_REASON_NOT_VISIBLE,
    PUSH_REASON_ALREADY_PUSHED,
    PUSH_REASON_AMBIGUOUS_ROUTE,
)

#: 主动推送的**步骤禁令**（常量；结构上推不出步骤 ⇒ 本句只是「文案里也别写成步骤」的机械落点）。
PROACTIVE_STEPS_NOTICE = "（只给导航：在哪一页 / 这页有什么。操作步骤不在本轮。）"

#: 「这一页能做什么」的自述前缀（**可行动性判据的结构锚**：说不出它 ⇒ 这条推送不该发）。
PROACTIVE_CAPABILITY_PREFIX = "这页能做："


@dataclass(frozen=True)
class ProactivePush:
    """一条**已判定可发**的主动导航提示（结构上**不含** steps / 图文 / 操作顺序）。"""

    #: 登记项 id（citation 左端）
    feature_id: str
    #: 功能名（= 菜单名）
    label: str
    #: 当前页（**可行动性的那一半**：告诉用户「你在哪一页」）
    route: str
    #: 页面所属菜单组（`STANDALONE_GROUP` = 一级独立项）
    group: str
    #: 「这页能做什么」的自述（导航级：能看到什么、入口在哪 —— **不含**操作顺序）
    capabilities: Tuple[str, ...]

    @property
    def citation(self) -> str:
        where = "一级项" if self.group == STANDALONE_GROUP else f"菜单组「{self.group}」"
        return f"登记项 #{self.feature_id} → {where}「{self.label}」"

    def to_data(self) -> Dict[str, Any]:
        """给模型的**结构化载荷**（键白名单：**没有** steps / 操作说明 / 图文）。"""
        return {
            "proactive": True,
            "featureId": self.feature_id,
            "label": self.label,
            "route": self.route,
            "capabilities": list(self.capabilities),
            "citation": self.citation,
        }

    def render(self) -> str:
        """上屏文案 —— 「你在【X】，这页能做 A、B」+ citation。**只给导航，不给步骤。**"""
        caps = "、".join(self.capabilities)
        return (
            f"你在【{self.label}】（{self.route}）。{PROACTIVE_CAPABILITY_PREFIX}{caps}。"
            f"（{self.citation}）{PROACTIVE_STEPS_NOTICE}"
        )


@dataclass(frozen=True)
class ProactiveVerdict:
    """推送判定结果。`push is None` ⇔ **不发**（此时 `reason` 必命中 `PUSH_REASONS`）。"""

    reason: str
    push: Optional[ProactivePush] = None

    @property
    def should_push(self) -> bool:
        """可行动性判据的入口：`True` ⇒ 一定带得出「在哪一页 + 这页能做什么」。"""
        return self.push is not None


def page_capabilities(node: MenuNode) -> Tuple[str, ...]:
    """「这页能做什么」——**导航级**自述（能看到什么 / 从哪进）。

    🔴 **不是操作步骤**：不写点击顺序、不写字段名、不写「第一步」。文案由**结构**生成
    （菜单组 + 菜单名），判据核「文案里不含受控步骤词」。
    """
    where = "菜单" if node.group == STANDALONE_GROUP else f"菜单组「{node.group}」"
    return (f"查看「{node.label}」", f"从{where}进入这一页")


def _route_feature_ids() -> Dict[str, Tuple[str, ...]]:
    """菜单路径 → 登记它的功能 id（**从 `MENU_TREE` / `NAV_FEATURES` 现算**，不手抄第二份）。

    多个功能登记同一路径 ⇒ 记成**多元组** ⇒ 调用方按 `ambiguous_route` 不推（不猜）。
    """
    index: Dict[str, list] = {}
    for feature in NAV_FEATURES:
        for key in feature.node_keys:
            index.setdefault(_NODES[key].path, []).append(feature.feature_id)
    return {path: tuple(ids) for path, ids in index.items()}


_ROUTE_FEATURES: Dict[str, Tuple[str, ...]] = _route_feature_ids()


#: 路由形态：**只认路径**（与 `app/context/page_registry.py` 的 `_ROUTE_RE` / 前端
#: `frontend/admin-web/src/lib/page-context.ts` 的 `ROUTE_FORM` **逐字同源**）。
#: 为什么本模块**不 import** `page_registry.normalize_route`：那样会把 `app.tools.base`
#: （pydantic + 环境变量）拉进**只跑标准库**的静态判据环境 —— 实测 `tests/unit_ci_workflows/**`
#: 的解释器里直接 `ModuleNotFoundError: pydantic`，而 CI 只装 `pytest pyyaml`（见
#: `docs/wiki/Change-Blast-Radius.md` 陷阱 1）。⇒ 语料一致性由判据核（两侧同语料判决必须一致），
#: **不是靠共享 import**。
_ROUTE_RE = re.compile(r"^/[A-Za-z0-9/_.\-]*$")
_ROUTE_MAX_LEN = 200


def normalize_route(raw: Any) -> str:
    """规范化 route：**只保留路径**（丢查询串/片段）；非法形态 ⇒ `""`（调用方按未登记处理）。

    与 `app/context/page_registry.py::normalize_route` **逐条同语义**（长度上限 / 只认路径字符集 /
    拒 `%` 与空格与非 ASCII / 拒路径穿越与 `//` / 去尾斜杠）。
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s or len(s) > _ROUTE_MAX_LEN:
        return ""
    for sep in ("?", "#"):
        s = s.split(sep, 1)[0]
    if not s.startswith("/") or not _ROUTE_RE.match(s):
        return ""
    if ".." in s or "//" in s:
        return ""
    if len(s) > 1:
        s = s.rstrip("/") or "/"
    return s


def _feature_ids_for_route(route: Any) -> Optional[Tuple[str, ...]]:
    """路由 → 功能 id 元组。`None` = route 形态不合法/未登记；`()` = 歧义（被多条登记项覆盖）。"""
    normalized = normalize_route(route)
    if not normalized:
        return None
    return _ROUTE_FEATURES.get(normalized)


def feature_for_route(route: Any) -> Optional[str]:
    """路由 → 功能 id；**未登记 / 歧义 / 脏形态 ⇒ `None`**（默认拒绝，不猜）。"""
    ids = _feature_ids_for_route(route)
    if not ids or len(ids) != 1:
        return None
    return ids[0]


def route_feature_coverage_problems() -> Tuple[str, ...]:
    """自检：`MENU_TREE` 的每个导航节点必须**恰好**被一条登记项覆盖（现算，供判据与元守备用）。

    病根同 P1：新增菜单节点却没人登记功能 ⇒ 那一页**永远不推**，而没有任何东西会红。
    """
    problems: list = []
    for node in MENU_TREE:
        ids = _ROUTE_FEATURES.get(node.path, ())
        if not ids:
            problems.append(f"菜单节点「{node.label}」（{node.path}）没有被任何 NAV_FEATURES 登记")
        elif len(ids) > 1:
            problems.append(f"菜单路径 {node.path} 被多条登记项覆盖 {sorted(ids)} ⇒ 功能不唯一")
    return tuple(problems)


def build_proactive_push(
    raw_route: Any,
    permissions: Any,
    *,
    already_pushed: Iterable[str] = (),
) -> ProactiveVerdict:
    """**主动新手引导的判定本体**（纯函数：登记表 + 会话权限 + 已推集，全部是入参）。

    判定顺序（**每一步 fail-closed**，逐条对应 issue #5989 的必做判据）：

    1. route ↔ 功能**唯一**对应 —— 没登记 ⇒ `unregistered`；被多条覆盖 ⇒ `ambiguous_route`；
    2. 该节点在**当前会话权限**下可见 —— 看不到 ⇒ `not_visible`
       （推了就是让用户去看他看不到的页面，既越权又不可行动）；
    3. 本会话还没推过这一页（`already_pushed`）—— 推过 ⇒ `already_pushed`（每页每会话 ≤ 1 次）；
    4. 🔴 **可行动性**：文案必须能说出「**在哪一页**（label + route）+ **这页能做什么**」
       —— 任一为空 ⇒ **不发**（`unregistered`，宁可静默）。

    ⚠️ `permissions` **只能来自服务端会话**（`ToolContext.permissions` / `UserIdentity.permissions`）；
    本函数签名里**没有 role** ⇒ 客户端递交的 role 结构上读不到（与 `build_navigation_answer` 同纪律）。
    """
    ids = _feature_ids_for_route(raw_route)
    if ids is None:
        return ProactiveVerdict(PUSH_REASON_UNREGISTERED)   # 未登记 / 脏形态
    if len(ids) != 1:
        return ProactiveVerdict(PUSH_REASON_AMBIGUOUS_ROUTE)  # 歧义 ⇒ 不猜
    feature_id = ids[0]
    node = _NODES[next(f for f in NAV_FEATURES if f.feature_id == feature_id).node_keys[0]]
    # 角色裁剪：**只按服务端会话权限**判（无权 ⇒ 不推：越权面 + 无处置入口）
    if not has_permissions((node.permission_code,), permissions):
        return ProactiveVerdict(PUSH_REASON_NOT_VISIBLE)
    if feature_id in set(already_pushed or ()):
        return ProactiveVerdict(PUSH_REASON_ALREADY_PUSHED)
    # 可行动性：说不出「在哪一页」或「这页能做什么」⇒ 不发（宁可静默）
    capabilities = page_capabilities(node)
    if not node.path or not node.label or not capabilities:
        return ProactiveVerdict(PUSH_REASON_UNREGISTERED)
    return ProactiveVerdict(
        "",
        ProactivePush(
            feature_id=feature_id,
            label=node.label,
            route=node.path,
            group=node.group,
            capabilities=capabilities,
        ),
    )
