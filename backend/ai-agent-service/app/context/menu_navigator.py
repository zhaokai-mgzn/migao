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
- **不做自由匹配 / 同义词推断 / 拼音纠错**：说法必须**接地**（与所属菜单名 / 本功能 `label`
  有包含关系）且**不被别的功能更长说法遮蔽**，判据逐条核（`problems_aliases_grounded` /
  `problems_shadowed_aliases`）—— 这一条把「说法表退化成同义词词典」的漂移堵在门外；
- **不查实体、不调 admin-api**：纯本地只读（无 HTTP 调用点 ⇒ 登记进 `LOCAL_ONLY_TOOLS`）。

## 类级判据（issue #6062：让「同类覆盖缺口」进不来）

| # | 判据 | 红 |
|---|---|---|
| ① | **每个菜单节点至少一条可命中的说法** | 某节点没有任何说法能命中 ⇒ 红（那个页面用户永远问不到） |
| ② | **没有空登记（死条目）** | 某条说法永远解不出它自己的功能 ⇒ 红（登记了但不生效） |
| ③ | **说法 ⇄ `menu.ts` 同步** | 说法与镜像漂移 ⇒ 红（页面增删/改名必须同批改登记表） |

判据的独立实现（**不 import 本模块**，纯静态）在
`tests/unit_ci_workflows/test_menu_navigator.py`；行为面在
`backend/ai-agent-service/tests/test_nav_guide.py`。
"""

from __future__ import annotations

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
    #: **登记**的意图台词（可搜索键）—— 每条必须**接地**（见 `NAV_FEATURES` 上方的硬约束）：
    #: 与所属节点菜单名 / 本功能 `label`（含括注）有包含关系，且**不被别的功能更长说法遮蔽**
    aliases: Tuple[str, ...]


#: 意图 → 功能登记表（**第一批：只做导航类**；未登记 ⇒ 默认拒绝）。
#: 🔴 新增条目 = 显式改本表（语义判断必须人做），**不许**改成「模糊匹配 menu.ts 的菜单名」。
#:
#: ## 每个节点登记**两个可搜索键**（issue #6062：修「问不到」与「空登记」两类病）
#:
#: ① **菜单名**（逐字等于 `menu.ts` 的 `name`，**必须**登记）—— 用户问「XX 在哪」时
#:    `resolve_feature` 按最长命中拿到它；缺了它 ⇒ 那个页面**用户永远问不到**（判据
#:    `problems_nodes_without_hit_alias`）；
#: ② **常见说法 / 括注**（同义词表超集：口语、简称、行业叫法）—— 从 `menu.ts` 既有
#:    `keywords`、`.github/cases/**` 的 `user_inputs` 语料与真实评测失败样例里摘，
#:    **不是凭空造词**。没有合适说法的节点只登记菜单名（如「知识库」）。
#:
#: ## 括注承载两件事（**同一个字段，不新增第五列**）
#:
#: · **菜单名与口语的落差**（如「发货单（出库）」「企业基础信息（系统设置）」）；
#: · 🔴 **「无独立导航目标」的操作**：某功能**在菜单里确实没有可指的页面**（例：给员工开账号
#:   只在「员工管理」页内以按钮形式存在）⇒ **不许编一个不存在的菜单路径**，而是把它登记成
#:   **该页的括注**（「员工管理（员工开账号）」），指向**最近的可指页面**。实测来源：
#:   2026-10-02 B 端真实评测 `normal` 档 `nav_guide!nav_not_registered ×1`，用户输入
#:   「怎么给员工开账号」；同一说法也出现在本仓既有用例 `HR-009` 的 `user_inputs`。
#:
#: ## 硬约束（自检 + 判据双闸）
#:
#: 🔴 **接地**：每条说法必须与它所属节点的菜单名有包含关系，**或**与它所属功能的
#: `label`（含括注）有包含关系 —— 这一条把「说法表退化成同义词词典」的漂移堵在门外，
#: 同时给①/②留下落点（判据 `problems_aliases_grounded`）。
#: 🔴 **非空登记**：每条说法都必须**能自己赢**（作为整句问句解出自己）——被更长的说法遮蔽
#: 的短说法**永远不可能**命中（`resolve_feature` 取最长命中）⇒ 那是死条目（判据
#: `problems_shadowed_aliases`）。推论：同一功能**不得**登记 `("发货单", "发货单列表")`
#: 这种「短说法是长说法子串」的形态（旧的 `…页` / `…列表` **装饰性变体**即属此列，已清掉）。
NAV_FEATURES: Tuple[NavFeature, ...] = (
    NavFeature("dashboard", "经营看板（经营数据）", (("workspace", "经营看板"),), ("经营看板", "经营数据")),
    NavFeature("briefing", "每日简报（日报）", (("workspace", "每日简报"),), ("每日简报", "日报")),
    NavFeature("human-sessions", "在线接待（人工接待）", (("customer-service", "在线接待"),), ("在线接待", "人工接待")),
    NavFeature("customers", "客户列表（客户）", (("customer-service", "客户列表"),), ("客户列表", "客户")),
    NavFeature("knowledge", "知识库", (("customer-service", "知识库"),), ("知识库",)),
    NavFeature("after-sales", "售后工单（退换货）", (("customer-service", "售后工单"),), ("售后工单", "退换货")),
    NavFeature("orders", "订单列表（订单）", (("trade-center", "订单列表"),), ("订单列表", "订单")),
    NavFeature("finance", "财务对账（对账）", (("trade-center", "财务对账"),), ("财务对账", "对账")),
    NavFeature("production-board", "生产看板（加工单）", (("production-center", "生产看板"),), ("生产看板", "加工单")),
    NavFeature("production-pool", "智能派单（派单）", (("production-center", "智能派单"),), ("智能派单", "派单")),
    NavFeature("processing-items", "加工项管理（加工项）", (("production-center", "加工项管理"),), ("加工项管理", "加工项")),
    NavFeature("production-process", "工艺配置（工艺）", (("production-center", "工艺配置"),), ("工艺配置", "工艺")),
    NavFeature("piecework", "计件工资（计件）", (("production-center", "计件工资"),), ("计件工资", "计件")),
    NavFeature("inbound-orders", "入库单（入库）", (("inventory-center", "入库单"),), ("入库单", "入库")),
    NavFeature("shipments", "发货单（出库）", (("inventory-center", "发货单"),), ("发货单", "出库")),
    NavFeature("remnants", "余料台账（余料）", (("inventory-center", "余料台账"),), ("余料台账", "余料")),
    NavFeature("saving-board", "省料看板（省料）", (("inventory-center", "省料看板"),), ("省料看板", "省料")),
    NavFeature("employees", "员工管理（员工开账号）", (("org-center", "员工管理"),), ("员工管理", "员工开账号")),
    NavFeature("roles", "岗位权限（角色权限）", (("org-center", "岗位权限"),), ("岗位权限", "角色权限")),
    NavFeature("settings", "企业基础信息（系统设置）", (("org-center", "企业基础信息"),), ("企业基础信息", "系统设置")),
    NavFeature("products", "商品管理（商品）", ((STANDALONE_GROUP, "商品管理"),), ("商品管理", "商品")),
    NavFeature("notifications", "通知中心（消息）", ((STANDALONE_GROUP, "通知中心"),), ("通知中心", "消息")),
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
            if not any(
                alias in label or label in alias for label in labels | {feature.label}
            ):
                raise MenuNavigatorError(
                    f"{feature.feature_id}：说法 {alias!r} 与登记菜单名 {sorted(labels)} /"
                    f" 功能名 {feature.label!r} 都无包含关系"
                    " ⇒ 说法表正在退化成同义词词典（禁止自由匹配）"
                )
    # ── 类级两条（issue #6062）：① 每个节点至少一条可命中的说法 ② 没有空登记（死条目）──
    declaring = {
        _NODES[k].label
        for feature in NAV_FEATURES
        for k in feature.node_keys
        if any(alias in _NODES[k].label for alias in feature.aliases)
    }
    no_alias = [node.label for node in MENU_TREE if node.label not in declaring]
    if no_alias:
        raise MenuNavigatorError(
            f"这些菜单节点**没有任何说法能命中**（用户永远问不到）：{no_alias}"
            " ⇒ 给它的登记项补一条**逐字等于菜单名**的说法（menu.ts 改了菜单名也要同批改）"
        )
    aliases = [(feature.feature_id, alias) for feature in NAV_FEATURES for alias in feature.aliases]
    # 有资格进 `has_prefix` 分支的 = 不在**同一功能**里被别的更长说法盖住的（见「可达性」推导）。
    maximal = [
        (owner, alias)
        for owner, alias in aliases
        if not any(
            other_owner == owner and alias in other_alias and alias != other_alias
            for other_owner, other_alias in aliases
        )
    ]
    for owner, alias in maximal:
        # 去掉这一条后，其功能还有没有别的说法能同样长度命中 `alias` 这句问句？
        siblings = [
            a for o, a in maximal if o == owner and a != alias
        ]
        if not any(a in alias for a in siblings) and any(
            other_owner != owner and other_alias in alias
            for other_owner, other_alias in maximal
        ):
            raise MenuNavigatorError(
                f"{owner} 的说法 {alias!r} 命不中自己：问「{alias}」时它会被"
                f"别的功能的更长说法抢先命中 ⇒ 这条说法永远解不出它自己的功能（属空登记）"
                " ⇒ 换一个不与别家成子串的说法，或删掉它"
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

    匹配口径（**确定性、可复算**）：在**登记说法的并集**上取**最长命中**；同长度命中多条
    ⇒ `None`（歧义**不猜**，与 `base_skill` 的「歧义即 fail-closed 不并」同族）。
    说法必须**接地**（与所属节点菜单名 / 本功能 `label` 有包含关系，导入期自检），
    且**不被别的功能更长说法遮蔽**（否则 `has_prefix` 分支永远收不到它）⇒ 不存在「自由匹配」。
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
