# case_ids: MC-032, MC-033, MC-034
"""RBAC 单一真值源 **P3**：由清单 `pages[]` **派生「页面 → 码」**（跟踪单 issue #5699）。

设计真值源 = `docs/design/rbac-single-source.md` 的 **§4 的 P3 行**（「由清单 `pages[]` 生成
C1 / C2 / C3 / C4 的**码列**（**不动**分组/顺序/icon/keywords）」+ 验收「节点码 == `pages[].gate`
（或 `visibility_rule` 的投影）逐值」）、**§2.4** 的逐消费面投影表、**§2.5**（可见性 = units 的组合）
与 **§3.4 问题 3 末注**（`pages[]` 必须支持**逐页** `any|all`、且**默认 `all`（fail-closed）**）。

## 这一条判据要治什么

「某页面要什么码」这个事实在仓里有 **4 份手写副本**（设计 §1.3 的 C 类）：`menu.ts` 的节点码、
`MenuController` 的 `MENU_TREE`、`AuthService` 的登录菜单、以及**判据自己的锚点表**
（`MENU_READ_ENDPOINT_ANCHORS` 的 21 条「页面 → 第一屏调用」+ 两张页面面台账）。P1/P2 把「角色 → 码」
与「码目录」搬进了清单，**「页面 → 码」当时一处都没进清单** ⇒ 「谁新写一张页面 → 码 的表」不会有东西变红。

P3 做三件事，**都不改行为**（零 delta）：

| 面 | 派生（本文件的被测对象） | 现值（对照） |
|---|---|---|
| `pages[]`（**新进清单**） | 21 页：`gate` 菜单可见码 + `units` 第一屏读码 → 端点 + 逐页 `visibility_rule` | 四跳现取（菜单节点 → 页面锚点 → `lib/api.ts` → Java 生效码） |
| C1 / C3 码列 | `menu_node_codes`（28 节点）/ `auth_menu_codes`（14 条） | `parse_menu_ts_nodes` / `parse_menus()['auth']` |
| C4 守卫码列 | `route_guard_codes`（每页 `path → gate`） | `parse_route_guard`（19 条前缀） |
| 页面面两张台账 | `multi_code_pages`（一页多码）/ `parity_residual_pages`（节点码 ≠ 页面读码） | `MULTI_READ_ENDPOINT_PAGES`（3）/ `MENU_READ_PARITY_RESIDUALS`（6） |
| 可见性 | `visibility`（按 `visibility_rule` 把 units 投影成「看得见该菜单的岗位集」） | 现值岗位集（`seed` ∪ `fallback` 的持码者） |

## 🔴 零 delta 是本阶段唯一的验收口径（违反即返工）

派生结果与现值必须**逐值相等**、**逐项点名**（不许用「数量相等」充数）。若不等 ⇒ **只报告、不修**
（那是 P4 的活，且必须由人在看过逐行 census 后点头）⇒ 故本文件的判据在「不等」时输出的是
**完整不一致清单**（每项一行），不是一个布尔量。

**特别地：多端点页与已登记残留不许被「压平」。** #5675 / #5682 已确立 `MULTI_READ_ENDPOINT_PAGES`
（多端点页必须具名 + 码集逐值冻结）与 6 条菜单残留；P3 的派生**必须保留「一页多码」**（3 页：
`/production/processing` 3 码、`/production/routings` 2 码、`/settings` 2 码）**与 6 条具名残留**
（`/dashboard`、`/production/pool`、`/production/saving-board`、`/production/processing`、
`/production/routings`、`/settings`）—— 把它们压成「一个页面一个码」是本判据要抓的第一坏形态。

## `visibility_rule`（逐页 `any|all`，默认 `all`）

设计 §3.4 问题 3 的结论：`/production/processing` 需要「任一 unit 可用即可见」，而 `/settings` 的语义是
「整页管理」——「允许半个页面可见」会造出新的「看得见做不了」⇒ **逐页声明 + 默认 `all`（fail-closed）**。
本判据把「现值要求」机械算出来（`all` ∩ / `any` ∪ 能否复现现值岗位集），并要求清单声明**逐页相等**：
现取 = `all` **18** 页 / `any` **0** 页 / `node-code` **4** 页（后者 = 投影复现不了现值，进
`PAGE_VISIBILITY_GAPS`，只许缩短，出口由 P4 逐条人裁定）。
⇒ 任何人把某页改成 `any`（放宽）而现值不要求它 ⇒ **红**。

## 覆盖面（**覆盖不到什么**，与设计 §5.3 逐条对齐）

- 🔴 **C2（`MenuController` 的 `MENU_TREE` 码列）不由 `pages[]` 派生**：它有 4 个**动作节点**
  （新增商品 / 商品分类管理 / 新增员工 / 订单详情 —— 不是页面）且「经营看板」节点无码而控制器有码
  ⇒ 它的码列不属「页面 → 码」面（现值由 M1 形态面 `menu-tree` 登记）。登记在 `NON_DERIVED_FACES`。
- **岗位全集 = 种子 ∪ 回退**（7 个）。租户自建的岗位（`roles` 表里新建的角色）**读不到** ⇒ 可见性投影
  对它们**未取证** —— 设计 §3.4 问题 3 第 1 行登记的 `/dashboard` delta 正落在这里（零权限的自定义岗位
  今天因「无码不过滤」看得见该菜单，投影后会看不见）。登记在 `UNCOVERED_FACES`。
- **只派生码列**：`pages[].units` 的 `label`（tab 中文名）/ icon / 关键词 / 组序**不搬进清单**
  （散文与展示属性；要它们时由 P4 的 `partial_visibility_ack` 带理由引入）。
- **只覆盖 `frontend/admin-web` 的页面**：bmini / worker-h5 的页面不在本面内（`frontend/worker-h5` 另有裁定 13）。
- **不判「现值对不对」**：投影再准也只证明**零 delta**，不证明现值**对**（设计 §5.3 的 M3 边界同款）；
  4 条 gap 与 6 条残留的存废是**授权裁定**，归 P4。
- **运行时未取证**：真实租户的 `role_permissions` 与自定义岗位读不到（本机无库/无环境），本判据只覆盖
  仓内可读的两个岗位来源。

## 红证的机具纪律（本仓已固化）

判据一律是**纯函数**（输入 = 清单 / 现值读数 / 语料文本，输出 = 问题清单），注入式红证**当场在内存里
构造坏形态**并把变异体**直接作为判据入参**；涉及**改磁盘文件**的变异还要额外证明**变异真的被读到**
（本文件的 `test_manifest_mutation_is_really_read` 就是干这个的：断言变异体与原文**逐叶不同**）。
「P3 新增形态面的锚唯一 + 删掉必红」由 `test_p3_copy_face_anchors_are_load_bearing` 在**内存语料**上自证。
"""
from __future__ import annotations

import copy
import functools
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
DERIVE_PATH = RBAC_DIR / "derive.py"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
#: P1 守卫：**逐项点名的摊平与对账口径在它里面**（`_walk` / `reconcile` / `LEDGER_CEILINGS`）——
#: 本文件复用，不另写第二套（否则同一个「零 delta」会有两种口径）。
MANIFEST_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_rbac_single_source_manifest.py"

#: P3 新增的形态面（P1 守卫 `COPY_FACES` 里的 id）—— 本文件自证它们的锚**唯一**且**删掉必红**。
P3_COPY_FACES = ("page-first-screen-anchors", "page-parity-residual-ledger", "route-node-anchor-ledger")


#: C4 面里**不以页面 `path` 出现**的前缀 —— 逐条具名 + 理由（只许缩短）。
#: 前三条**没有对应页面**（路由常量 ≠ 页面：入口在别的页面里 / 已并入别的页面）；
#: `/processing` 是**同一页的第二前缀**（该页 `path` 是 `/production/processing`）。
ROUTE_PREFIX_ALIASES = {
    "/processing": "加工项管理",
}
ROUTE_PREFIX_EXCEPTIONS = {
    "/chat": (
        "会话页没有侧边栏节点（「在线接待」的 `path` 是 `/agent-workspace/human-sessions`）"
        "⇒ 该前缀不属「页面 → 码」面（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
    "/categories": (
        "分类管理**没有独立侧边栏节点**（入口在商品列表页内）⇒ 不属「页面 → 码」面"
        "（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
    "/processing-orders": (
        "加工单唯一入口已并入「生产看板」⇒ 本前缀只作旧链接兼容，不属「页面 → 码」面"
        "（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
}

#: 页面存在、但**守卫码 ≠ 该页 `gate`** 的前缀 —— 逐条具名（只许缩短；今天 1 条）。
#: 这些不是「例外」而是**已知的不一致**：两侧各自的理由都在判据 11③ / 判据 12 的台账里。
ROUTE_GUARD_GATE_MISMATCHES = {
    "/dashboard": (
        "「经营看板」节点**有意无码**（`gate = null` ⇒ 全员可见），而页面守卫要 `dashboard:view` "
        "⇒ 两侧取值不同。本判据**不裁定哪一侧为真值**：谁改都能让本项消失，而改错方向会同时让"
        "判据 11③（`ROUTE_WITHOUT_MENU_NODE`）与判据 12（`MENU_READ_PARITY_RESIDUALS`）判红。"
    ),
}

#: **不是页面**的菜单节点（C2 的「动作节点」）—— 逐条具名 + 码冻结（只许缩短；键集与现取逐值相等）。
#: 它们是「**动作**」（去某个页面里的某个动作），没有 `path` ⇒ 不属「页面 → 码」面；
#: 现值由 M1 形态面 `menu-tree` 登记。
ACTION_NODE_CODES: dict[str, dict[str, str]] = {
    "商品分类管理": {
        "code": "product:category",
        "reason": "分类管理的入口在商品列表页内，**没有独立页面**（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE['/categories']` 登记的是同一件事）",
        "owner": "商品域菜单面（`menu.ts` 的 product-center 组）+ 本判据的动作节点台账",
    },
    "新增商品": {
        "code": "product:create",
        "reason": "「新增商品」是商品列表页内的动作（`ProductController` 的写码），不是页面",
        "owner": "商品域菜单面 + 本判据的动作节点台账",
    },
    "新增员工": {
        "code": "employee:create",
        "reason": "「新增员工」是员工管理页内的动作（`UserController` 的写码），不是页面",
        "owner": "组织管理组菜单面 + 本判据的动作节点台账",
    },
    "订单详情": {
        "code": "order:detail",
        "reason": "「订单详情」是订单列表页内的动作（`order:detail` 的 census 端点数现取 = 0 —— 它是页面内路由，不是首屏）",
        "owner": "交易管理组菜单面 + 本判据的动作节点台账",
    },
}

#: **页面节点**上「码列 ≠ 该页 `gate`」的具名不一致（只许缩短；今天 1 条 = C2 的经营看板）。
#: 与 `ROUTE_GUARD_GATE_MISMATCHES` 是**同一处不一致的两条出路**（C2 的码列 / 路由守卫），
#: 两处都具名 ⇒ 谁单方面改一侧都会被拦住。
MENU_CODE_MISMATCHES = {
    "经营看板": "「经营看板」节点在 `menu.ts` 里**有意无码**（`gate = null` ⇒ 全员可见），而 `MenuController` 的权限目录给它 `dashboard:view`（路由守卫同码）⇒ 两侧取值不同。本判据**不裁定哪一侧为真值**：改任一侧都要同时改判据 11③ 与判据 12 的登记。",
}

#: `visibility_rule = node-code`（**投影复现不了现值**）的**逐页理由**（只许缩短；键集与现取逐值相等）。
#: 前三条是「节点码 ≠ 页面读码」的三页（终端 403 面），`/notifications` 是「第一屏端点全未注解」。
VISIBILITY_GAP_REASONS = {
    "/notifications": {
        "reason": (
            "该页第一屏唯一读端点 `GET /api/admin/notifications` **未被任何权限码把守**"
            "（`units` 里只有 `__unannotated__` 一组）⇒ 投影无输入，可见性仍取节点码（今天 `gate = null`"
            "⇒ 全员可见）。出口 = 给该端点补注解（判据 8 的 `UNANNOTATED_ENDPOINTS` 台账）或明确"
            "「该页无需权限」—— 两者都是裁定，P3 只登记。"
        ),
        "owner": "通知中心页 + 端点注解面（`NotificationController`）+ 本判据的 gap 台账",
    },
    "/production/pool": {
        "reason": (
            "节点码 `processing:manage`，而该页第一屏读端点要 `processing:view` ⇒ 两种投影（∩ 与 ∪）"
            "都复现不了现值：把节点可见性交给读码 ⇒ 客服 / 销售 / 财务（持 `processing:view`）"
            "**凭空看见**该菜单；交给管理码 ⇒ 投影与现值一致但**不表达**「页面第一屏要什么码」"
            "（那正是本面存在的意义）。两个方向都要人裁定（判据 12 的残留台账逐字记着）。"
        ),
        "owner": "生产域菜单/权限面（`menu.ts` 的 production-center 组 + `ProductionPoolController`）+ 本判据的 gap 台账",
    },
    "/production/saving-board": {
        "reason": (
            "节点码 `processing:manage`，而该页第一屏两个端点在 `StockBatchController` 上各带**方法级**"
            "`product:list`（#5145 立的口径）⇒ 两种投影都复现不了现值（∩ 或 ∪ 都会改某个岗位集合的可见性）。"
            "出口是授权裁定，归 P4。"
        ),
        "owner": "仓储与物料组菜单/权限面（`menu.ts` 的 inventory-center 组 + `StockBatchController`）+ 本判据的 gap 台账",
    },
    "/production/processing": {
        "reason": (
            "第一屏**跨三个码**（3 个 unit：`production:view` / `order:list` / `processing:manage`）"
            "⇒ `∩` 比现值窄（丢掉只持节点码的 `product_manager@fallback`）、`∪` 比现值宽"
            "（客服 / 销售 / 财务凭空看见）。这一页正是设计 §2.5 / §3.4 问题 1 的标本："
            "「整页可见但某个 tab 403」需要 `partial_visibility_ack` 或收窄端点码，两者都归 P4。"
        ),
        "owner": "生产域读码收口面（#5291 未走完的端点族）+ 本判据的 gap 台账",
    },
}

#: **不由 `pages[]` 派生**的面（**只许缩短**）：每条写清为什么它不属「页面 → 码」。
NON_DERIVED_FACES = (
    {
        "face": "C2：`backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE` 码列（24 条）",
        "reason": (
            "它有 4 个**动作节点**（新增商品 / 商品分类管理 / 新增员工 / 订单详情 —— 不是页面，没有 `path`）"
            "且「经营看板」节点无码而控制器给 `dashboard:view` ⇒ 它的码列是「权限目录」语义，"
            "不属「页面 → 码」面（设计 §2.4 把 C2 与 C1/C3/C4 分开列）。现值由 M1 形态面 `menu-tree` 登记。"
        ),
        "owner": "RBAC 跟踪单 #5699（P4 若裁定「动作节点也进页面表」，本项随之缩短）",
        "issue": "#5699",
    },
)
NON_DERIVED_FACE_CAP = 1

#: P3 的**未覆盖面台账**（只许缩短）：照实验登记，不假装覆盖。
UNCOVERED_FACES: tuple[dict[str, str], ...] = (
    {
        "face": "租户**自建岗位**（`roles` 表里新建的角色）的可见性",
        "reason": (
            "岗位全集现取只有**种子 ∪ 回退**（7 个）；自建岗位在库里，仓内读不到 ⇒ 投影对它们未取证。"
            "设计 §3.4 问题 3 第 1 行登记的 `/dashboard` delta（零权限的自定义岗位今天因「无码不过滤」"
            "看得见该菜单）正落在这里 —— 归 P4 的裁定"
        ),
        "owner": "RBAC 跟踪单 #5699 的 P4（重启条件：接上真库后按租户复算岗位 → 可见性）",
        "issue": "#5699",
    },
    {
        "face": "`frontend/bmini-app` / `frontend/worker-h5` 的页面 → 码",
        "reason": (
            "本面的四跳现取只覆盖 `frontend/admin-web/src/app/(dashboard)` 的页面；"
            "worker-h5 另有裁定 13（不重写），bmini 的页面面由 `frontend/bmini-app/tests/` 的既有判据管"
        ),
        "owner": "裁定 13 + bmini 面既有判据",
        "issue": "#5699",
    },
    {
        "face": "`pages[].units` 的 `label`（tab 中文名）/ icon / 关键词 / 组序",
        "reason": (
            "散文与展示属性：判据读不到就只能靠人核；P3 有意只搬**码列**（设计 §4 的 P3 行逐字："
            "「**不动**分组/顺序/icon/keywords」）⇒ 要它们时由 P4 的 `partial_visibility_ack` 带理由引入"
        ),
        "owner": "RBAC 跟踪单 #5699 的 P4",
        "issue": "#5699",
    },
    {
        "face": "「可见面 == 可做面」的**产品裁定**（6 条残留与 4 条 gap 的存废）",
        "reason": (
            "P1–P3 全部是「让结构对，但不让人察觉」；每一条残留的出口都是一次**授权变更**（放宽或收窄），"
            "必须由人在看过 §3.3(c) 的逐行 census 后点头 ⇒ P3 只登记、不消解"
        ),
        "owner": "人类裁定（设计 §4.1 的 D1~D4 硬前置）",
        "issue": "#5699",
    },
    {
        "face": "运行时可见性（真租户 / 真库上「这个岗位看不看得见这个菜单」）",
        "reason": (
            "本机没有可跑的 `admin-api` / 真库环境 ⇒ 只能取证**静态**的两个岗位来源；"
            "与 P1/P2 的同款边界（设计 §6 第 1 条）"
        ),
        "owner": "RBAC 跟踪单 #5699 的重启条件（接上真环境后复算）",
        "issue": "#5699",
    },
)
UNCOVERED_FACE_CAP = 5


# ══════════════════════════════════════════════════════════════════════════════
# 一、读盘（清单 / 派生器 / 既有判据）—— 缺任一 ⇒ fail-closed，不静默当空
# ══════════════════════════════════════════════════════════════════════════════


def _load_module(name: str, path: Path):
    """按路径加载模块（`sys.modules` 先注册：`@dataclass` 解析 `cls.__module__` 的前提）。"""
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_manifest() -> dict:
    assert MANIFEST_PATH.is_file(), f"声明真值源不存在：{MANIFEST_PATH}（fail-closed）"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "清单必须是**非空对象**（空 ⇒ 判据在空集上恒真）"
    return data


def load_derive():
    """P3 派生器（`rbac/derive.py`）—— 生成器与判据取的是**同一份**投影实现。"""
    return _load_module("migao_rbac_derive", DERIVE_PATH)


def load_parity_guard():
    """既有解析器的唯一家（P1/P2 沿用同一套机具；本文件不另造第二套）。"""
    return _load_module("migao_rbac_parity_guard", PARITY_GUARD)


def load_manifest_guard():
    """P1 守卫 —— 只为复用它的 `_walk` / `reconcile` / `LEDGER_CEILINGS` / `RECONCILED_SEGMENTS`。"""
    return _load_module("migao_rbac_p1_guard", MANIFEST_GUARD)


@functools.lru_cache(maxsize=1)
def present_faces() -> dict:
    """「页面 → 码」的**现值**（缓存：多条判据共用同一次现取 —— 四跳现取不便宜）。"""
    return load_derive().page_present(load_parity_guard())


@functools.lru_cache(maxsize=1)
def derived_faces() -> dict:
    """由**清单**派生的各投影面（缓存：清单是只读输入）。"""
    return load_derive().derive_page_faces(load_manifest())


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数：输入注入，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════

#: 逐值对账的**面**（`route_guard_codes` 单独走 `route_guard_problems`：两边的键空间不同；
#: C2 / C3 两列码走 `menu_column_problems`：**节点集**不属「页面 → 码」面，只有**码列**属）。
RECONCILED_FACES = (
    "menu_node_codes",
    "first_screen_codes",
    "units",
    "multi_code_pages",
    "parity_residual_pages",
    "visibility",
)


def leaves(value: object) -> list[tuple[str, object]]:
    """摊平成 `(路径, 值)` 清单（复用 P1 守卫的 `_walk`：同一个「逐项点名」口径）。"""
    return load_manifest_guard()._walk(value)


def face_problems(derived: dict, present: dict) -> list[str]:
    """**零 delta 逐项点名**：每个面的派生值 vs 现值，逐叶比对 ⇒ 完整不一致清单。

    面的**全集**也要相等（派生多一面 / 少一面 ⇒ 具名报出），否则「漏了一面」会静默通过。
    """
    out: list[str] = []
    for face in RECONCILED_FACES:
        if face not in derived:
            out.append(f"[派生缺面] {face}（派生器没有产出这一面）")
            continue
        if face not in present:
            out.append(f"[现值缺面] {face}（现值侧没有这一面）")
            continue
        want = dict(leaves({face: derived[face]}))
        got = dict(leaves({face: present[face]}))
        for key in sorted(set(want) | set(got)):
            if key not in got:
                out.append(f"[派生多出] {key} = {want[key]!r}（现值里没有这一项）")
            elif key not in want:
                out.append(f"[现值多出] {key} = {got[key]!r}（派生里没有这一项）")
            elif want[key] != got[key]:
                out.append(f"[值不等] {key}: 派生={want[key]!r} / 现值={got[key]!r}")
    return out


def page_problems(manifest: dict, present: dict) -> list[str]:
    """清单 `pages[]` vs 现值页面表：**逐值对账**（复用 P1 守卫的 `reconcile`，口径唯一）。"""
    return load_manifest_guard().reconcile(
        {"pages": manifest["pages"]}, {"pages": present["pages"]}
    )


def menu_column_problems(derived: dict, present: dict) -> list[str]:
    """C2 / C3 的**码列**必须与该页 `gate` 逐条相等；不是页面的节点必须具名登记。

    判据 11③ / 判据 12 管的是「菜单节点 ≡ 页面第一屏」，**没有一条**管「`MenuController` / `AuthService`
    的码列 ≡ 页面的 `gate`」—— 而这两列正是「同一事实的第 2/3 份副本」。三段（缺任何一段就有漏网形态）：

      ① **页面节点**：码列里凡在 `menu_nodes` 里出现的名字 ⇒ 码必须 == 该页 `gate`（或具名在
         `MENU_CODE_MISMATCHES`）；
      ② **非页面节点**（动作节点）：名字不在 `menu_nodes` 里 ⇒ 必须具名在 `ACTION_NODE_CODES`
         （理由 + 谁的负责 + 码**冻结**：涨跌都要同 PR 更新）；
      ③ **只许缩短**：两张台账里登记了却已对不上 / 已不在码列里 ⇒ 红。

    ⚠️ **节点集不属本面**：C2 只有 24 个节点、C3 只有 14 个（登录菜单是页面的**子集**）——
    「哪些节点进哪一列」是菜单结构的事实，不由 `pages[]` 决定；本函数只判**码**（逐条点名）。
    """
    node_gates = dict(derived["menu_node_codes"])
    columns = {
        "C2(MenuController)": present["menu_controller_codes"],
        "C3(AuthService)": present["auth_menu_codes"],
    }
    out: list[str] = []
    live_mismatch: set[str] = set()
    live_action: dict[str, str] = {}
    for label, column in sorted(columns.items()):
        for name, code in sorted(column.items()):
            if name in node_gates:
                if code == node_gates[name]:
                    continue
                live_mismatch.add(name)
                if name not in MENU_CODE_MISMATCHES:
                    out.append(
                        f"{label} 的『{name}』码 = `{code}` ≠ 该页 `gate` = {node_gates[name]!r}"
                        " ⇒ 要么对齐两侧、要么在 `MENU_CODE_MISMATCHES` 里具名（只许缩短）"
                    )
                continue
            live_action[name] = str(code)
            entry = ACTION_NODE_CODES.get(name)
            if entry is None:
                out.append(
                    f"{label} 的『{name}』（码 `{code}`）不是任何页面的节点 ⇒ **动作节点必须具名登记**"
                    "（`ACTION_NODE_CODES`：码 + 理由 + 谁负责；未登记即红）"
                )
            elif entry["code"] != code:
                out.append(
                    f"`ACTION_NODE_CODES['{name}']['code']` = {entry['code']!r} ≠ 现取 `{code}`"
                    "（涨跌都要在同 PR 更新）"
                )
    for name in sorted(set(MENU_CODE_MISMATCHES) - live_mismatch):
        out.append(
            f"`MENU_CODE_MISMATCHES['{name}']` 已不再不一致（或该节点已不在任何码列里）⇒ 销账（只许缩短）"
        )
    for name in sorted(set(ACTION_NODE_CODES) - set(live_action)):
        out.append(
            f"`ACTION_NODE_CODES['{name}']` 已不在任何码列里 ⇒ 销账（只许缩短；陈旧条目会把下一次真回归"
            "读成「已登记」）"
        )
    for name, entry in sorted(ACTION_NODE_CODES.items()):
        empty = [k for k in ("code", "reason", "owner") if not entry.get(k)]
        if empty:
            out.append(f"`ACTION_NODE_CODES['{name}']` 缺字段 {empty}（码/理由/谁负责缺一即红）")
    return out


def route_guard_problems(derived: dict, present: dict) -> list[str]:
    """C4：`ROUTE_PERMISSION_MAP` 的每个前缀都必须是「某页 `path` → 该页 `gate`」的投影，或具名例外。

    三段（缺任何一段这条对账就有漏网形态）：
      ① **可派生前缀**（页面 `path` 命中 / 登记的别名）⇒ 守卫码必须逐值 == 该页 `gate`；
      ② **未命中任何页面**的前缀 ⇒ 必须具名（未登记即红）—— 新增页面守卫时不许静默漂移；
      ③ **例外台账只许缩短**：登记了却已一致 / 已不在路由表里 ⇒ 红（陈旧条目会把下一次真回归读成「已登记」）。
    """
    entries = {prefix: code for prefix, code in present["route_guard"]}
    page_gates = dict(derived["route_guard_codes"])
    node_gates = dict(derived["menu_node_codes"])
    out: list[str] = []
    for prefix, code in sorted(entries.items()):
        if prefix in page_gates:
            if code == page_gates[prefix]:
                continue
            if prefix in ROUTE_GUARD_GATE_MISMATCHES:
                continue
            out.append(
                f"路由 `{prefix}` 的守卫码 = `{code}` ≠ 该页 `gate` = {page_gates[prefix]!r}"
                " ⇒ 要么对齐两侧、要么在 `ROUTE_GUARD_GATE_MISMATCHES` 里逐条具名（只许缩短）"
            )
            continue
        if prefix in ROUTE_PREFIX_ALIASES:
            node = ROUTE_PREFIX_ALIASES[prefix]
            gate = node_gates.get(node)
            if gate != code:
                out.append(
                    f"别名路由 `{prefix}`（→『{node}』）的守卫码 = `{code}` ≠ 该节点 `gate` = {gate!r}"
                    " ⇒ 同页两处取值不同"
                )
            continue
        if prefix in ROUTE_PREFIX_EXCEPTIONS:
            continue
        out.append(
            f"路由 `{prefix}` 既不是某页的 `path`、也没有别名 / 例外登记 ⇒ **新增页面守卫必须先登记**"
            "（否则它改了码不会有东西变红）"
        )
    registered = set(ROUTE_PREFIX_ALIASES) | set(ROUTE_PREFIX_EXCEPTIONS) | set(ROUTE_GUARD_GATE_MISMATCHES)
    for prefix in sorted(registered - set(entries)):
        out.append(f"登记的 `{prefix}` 已不在 `ROUTE_PERMISSION_MAP` 里 ⇒ 销账（只许缩短）")
    for prefix in sorted(set(ROUTE_GUARD_GATE_MISMATCHES) & set(page_gates)):
        if page_gates[prefix] == entries.get(prefix):
            out.append(
                f"`ROUTE_GUARD_GATE_MISMATCHES['{prefix}']` 已不再不一致（两侧同码）⇒ 删掉这条登记"
                "（只许缩短；陈旧条目会把下一次真回归读成「已登记」）"
            )
    for prefix in sorted(set(ROUTE_PREFIX_ALIASES) & set(page_gates)):
        out.append(
            f"`ROUTE_PREFIX_ALIASES['{prefix}']` 已经是某页的 `path` ⇒ 别名登记陈旧，删掉它"
        )
    return out


def visibility_problems(derived: dict, present: dict, manifest: dict) -> list[str]:
    """逐页可见性：**规则合法性 + 派生 == 现值要求 + gap 台账双向闭合 + 投影岗位集逐值**。"""
    derive = load_derive()
    out: list[str] = []
    derived_visibility = dict(derived["visibility"])
    present_visibility = dict(present["visibility"])
    gaps: list[str] = []
    for path in sorted(set(derived_visibility) | set(present_visibility)):
        if path not in present_visibility:
            out.append(f"[派生多出] 可见性面多出一页 `{path}`（现值页面表里没有）")
            continue
        if path not in derived_visibility:
            out.append(f"[现值多出] 可见性面缺页 `{path}`（清单 `pages[]` 里没有这一页）")
            continue
        want, got = derived_visibility[path], present_visibility[path]
        if want["rule"] not in derive.VISIBILITY_RULES:
            out.append(f"`{path}` 的 `visibility_rule` = {want['rule']!r} 不在 {derive.VISIBILITY_RULES} 里")
        if want["rule"] != got["rule"]:
            out.append(
                f"[值不等] visibility.{path}.rule: 清单={want['rule']!r} / 现值要求={got['rule']!r}"
                "（清单声明的投影规则必须能复现现值；放宽或收窄都要在人看过 diff 后改）"
            )
        if want["roles"] != got["roles"]:
            out.append(
                f"[值不等] visibility.{path}.roles: 派生={want['roles']!r} / 现值={got['roles']!r}"
            )
        if got["rule"] == derive.VISIBILITY_NODE_CODE:
            gaps.append(path)
    ledger = set(VISIBILITY_GAP_REASONS)
    for path in sorted(set(gaps) - ledger):
        out.append(
            f"`{path}` 的可见性**投影复现不了现值** ⇒ 必须在 `VISIBILITY_GAP_REASONS` 里具名"
            "（理由 + 谁负责）；未登记即红"
        )
    for path in sorted(ledger - set(gaps)):
        out.append(
            f"`VISIBILITY_GAP_REASONS['{path}']` 已不再是一条 gap（投影能复现现值或该页已不在）"
            " ⇒ 销账（只许缩短）"
        )
    counted = manifest["ledger_counts"].get("PAGE_VISIBILITY_GAPS")
    if counted != len(gaps):
        out.append(
            f"清单 `ledger_counts.PAGE_VISIBILITY_GAPS` = {counted!r}，而现取 = {len(gaps)}"
            "（涨跌都要在同 PR 更新：清单 + 本台账 + P1 守卫的上限）"
        )
    for path, entry in sorted(VISIBILITY_GAP_REASONS.items()):
        empty = [k for k in ("reason", "owner") if not entry.get(k, "").strip()]
        if empty:
            out.append(f"`VISIBILITY_GAP_REASONS['{path}']` 缺字段 {empty}（理由/谁负责缺一即红）")
    return out


def coverage_problems() -> list[str]:
    """覆盖面与**只许缩短**的机械形态：台账条数上限 + 每条写清「覆盖不到什么、谁看」。"""
    p1, derive = load_manifest_guard(), load_derive()
    manifest = load_manifest()
    out: list[str] = []
    for name, cap in (("PAGE_VISIBILITY_GAPS", 4),):
        if p1.LEDGER_CEILINGS.get(name) != cap:
            out.append(
                f"P1 守卫的 `LEDGER_CEILINGS['{name}']` = {p1.LEDGER_CEILINGS.get(name)!r} ≠ {cap}"
                " ⇒ 台账的增长无人管或上限被悄悄放宽"
            )
        if manifest["ledger_counts"].get(name, 0) > p1.LEDGER_CEILINGS.get(name, 0):
            out.append(f"台账 {name} 现取条数 > 上限（只许缩短）")
    if "pages" not in p1.RECONCILED_SEGMENTS:
        out.append(
            "P1 守卫的 `RECONCILED_SEGMENTS` 里没有 `pages` ⇒ 新段逃出了「清单 == 生成物」的对账"
            "（那正是新造并行真值的形态）"
        )
    if len(derive.VISIBILITY_RULES) != 3:
        out.append(f"`VISIBILITY_RULES` = {derive.VISIBILITY_RULES}（逐页规则集被人改动）")
    if derive.DEFAULT_VISIBILITY_RULE != derive.VISIBILITY_ALL:
        out.append(
            f"默认规则 = {derive.DEFAULT_VISIBILITY_RULE!r} ≠ {derive.VISIBILITY_ALL!r}"
            " ⇒ 默认不再是 fail-closed（设计 §3.4 问题 3 末注）"
        )
    if len(VISIBILITY_GAP_REASONS) > 4:
        out.append(f"gap 台账 {len(VISIBILITY_GAP_REASONS)} 条 > 上限 4（只许缩短）")
    if len(ACTION_NODE_CODES) > 4:
        out.append(f"动作节点台账 {len(ACTION_NODE_CODES)} 条 > 上限 4（只许缩短）")
    if len(MENU_CODE_MISMATCHES) > 1:
        out.append(f"码列不一致台账 {len(MENU_CODE_MISMATCHES)} 条 > 上限 1（只许缩短）")
    if len(ROUTE_PREFIX_EXCEPTIONS) > 3:
        out.append(f"无页面前缀台账 {len(ROUTE_PREFIX_EXCEPTIONS)} 条 > 上限 3（只许缩短）")
    if len(ROUTE_PREFIX_ALIASES) > 1:
        out.append(f"前缀别名台账 {len(ROUTE_PREFIX_ALIASES)} 条 > 上限 1（只许缩短）")
    if len(ROUTE_GUARD_GATE_MISMATCHES) > 1:
        out.append(f"守卫码不一致台账 {len(ROUTE_GUARD_GATE_MISMATCHES)} 条 > 上限 1（只许缩短）")
    if len(NON_DERIVED_FACES) > NON_DERIVED_FACE_CAP:
        out.append(f"非派生面 {len(NON_DERIVED_FACES)} 条 > 上限 {NON_DERIVED_FACE_CAP}（只许缩短）")
    if len(UNCOVERED_FACES) > UNCOVERED_FACE_CAP:
        out.append(f"未覆盖面 {len(UNCOVERED_FACES)} 条 > 上限 {UNCOVERED_FACE_CAP}（只许缩短）")
    for face in NON_DERIVED_FACES:
        for key in ("face", "reason", "owner", "issue"):
            if not face.get(key):
                out.append(f"非派生面条目缺 {key!r}（必须写清「谁看」）：{face}")
    for face in UNCOVERED_FACES:
        for key in ("face", "reason", "owner", "issue"):
            if not face.get(key):
                out.append(f"未覆盖面条目缺 {key!r}（必须写清「谁看」）：{face}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（每条配注入式红证 + 对照读数）
# ══════════════════════════════════════════════════════════════════════════════


def test_manifest_pages_match_present_values():
    """**P3 主判据之一（零 delta）**：清单 `pages[]` 与现值页面表**逐值相等**，逐项点名。

    不等时输出**完整不一致清单**（「发现 delta」是正常交付，**不改**、只报告 —— 设计 §4 的 P3 口径）。
    """
    manifest, present = load_manifest(), present_faces()
    problems = page_problems(manifest, present)
    print(f"── 清单 pages[] = {len(manifest['pages'])} 页 / 现值 = {len(present['pages'])} 页 ──")
    assert problems == [], (
        f"清单 `pages[]` 与现值**不一致**（共 {len(problems)} 项）—— 🔴 本阶段只报告、不修"
        "（P4 的活，且须人点头）：\n" + "\n".join(f"  · {p}" for p in problems)
    )


def test_derived_page_faces_match_present_values():
    """**P3 主判据之二（零 delta）**：各投影面的派生结果与现值**逐值相等**，逐项点名 + 口径读数。"""
    derived, present = derived_faces(), present_faces()
    counted = 0
    for face in RECONCILED_FACES:
        for key, value in leaves({face: derived[face]}):
            counted += 1
            print(f"  {key} = {value!r}")
    print(
        f"── P3 逐值比对项数 = {counted}（**口径**：六个投影面摊平到叶的 `(路径, 值)` 对总数 ——"
        "C1 按「节点 → 码」逐节点一项（28）、第一屏码按「页 → 逐码」展开（24）、"
        "units 按「页 → 码 → 逐端点」展开（27）、多码页 3 项、残留页 6 项、可见性按「页 → 规则 + 岗位集」"
        "逐页一项（21）。**另有两条不走摊平的面**：C4 按前缀逐条比（19 条 = 15 直接命中 + 1 别名 +"
        " 3 无页面），C2/C3 的码列逐条比（24 + 14 = 38 条，含 4 个**动作节点**与 1 处具名不一致）"
        "⇒ 全部逐项点名，**不一致 = 0**）──"
    )
    problems = (
        face_problems(derived, present)
        + route_guard_problems(derived, present)
        + menu_column_problems(derived, present)
    )
    assert problems == [], (
        f"派生结果与现值**不一致**（共 {len(problems)} 项）—— 🔴 本阶段只报告、不修"
        "（P4/P5 的活，且须人点头）：\n" + "\n".join(f"  · {p}" for p in problems)
    )


def test_multi_code_pages_and_residuals_are_not_flattened():
    """**多端点页与 6 条残留不被压平**（#5675 / #5682 的结构事实）：派生集 == 现取，逐值。

    多码页：3 页，**码集逐值冻结**（`/production/processing` 3 码、`/production/routings` 2 码、
    `/settings` 2 码）；残留页：6 页，键集与现取逐值相等。两侧都**只许缩短**（未登记即红 / 陈旧亦红）。
    """
    derived, present, parity = derived_faces(), present_faces(), load_parity_guard()
    multi = {path: sorted(codes) for path, codes in derived["multi_code_pages"].items()}
    frozen = {
        path: sorted(entry.codes) for path, entry in parity.MULTI_READ_ENDPOINT_PAGES.items()
    }
    residuals = sorted(derived["parity_residual_pages"])
    ledger = sorted(parity.MENU_READ_PARITY_RESIDUALS)
    print(f"多码页（派生）={multi}")
    print(f"多码页（现值冻结）={frozen}")
    print(f"残留页（派生）={residuals}")
    print(f"残留页（现值台账）={ledger}")
    problems: list[str] = []
    for path in sorted(set(multi) | set(frozen)):
        if path not in frozen:
            problems.append(f"`{path}` 派生为多码页（{multi.get(path)}）但现值未冻结 ⇒ 未登记即红")
        elif path not in multi:
            problems.append(
                f"`{path}` 现值冻结为多码页（{frozen[path]}）但派生只给 {multi.get(path)}"
                " ⇒ **被压平**（判据 12 的「那一个码」前提被悄悄恢复）"
            )
        elif multi[path] != frozen[path]:
            problems.append(f"`{path}` 码集不等：派生={multi[path]} / 现值={frozen[path]}")
    if residuals != ledger:
        problems.append(
            f"残留页集不等：派生={residuals} / 现值台账={ledger}"
            "（两侧都只许缩短：不一致消失而条目还在 ⇒ 红；新增不一致未登记 ⇒ 红）"
        )
    if len(multi) != 3 or len(residuals) != 6:
        problems.append(
            f"结构性条数漂移：多码页 {len(multi)}（期望 3）/ 残留页 {len(residuals)}（期望 6）"
        )
    assert problems == [], "多端点页 / 残留台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_visibility_rule_is_fail_closed_and_registered():
    """逐页 `visibility_rule`：派生 == 现值要求 + gap 台账双向闭合 + 默认 fail-closed。"""
    derived, present, manifest = derived_faces(), present_faces(), load_manifest()
    problems = visibility_problems(derived, present, manifest)
    print(f"逐页规则（清单）= { {p: e['rule'] for p, e in sorted(derived['visibility'].items())} }")
    assert problems == [], "逐页可见性不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_visibility_rule_default_is_all_not_any():
    """`visibility_rule` 的默认值 = **`all`（fail-closed）**；未登记的规则名 ⇒ fail-closed 抛错。

    两半都要钉：① 字段缺失 / 为空 ⇒ 按 `all` 算（**不是** `any`、也不是「当空」）；
    ② 显式 `any` 不被默认值吞掉（否则「支持逐页 any|all」是空话）；
    ③ 未登记的规则名不许静默当默认（fail-closed 抛错）。
    """
    derive = load_derive()
    base = {"path": "/x", "units": {"a:b": ["GET /x"]}, "visibility_rule": None}
    assert derive.effective_visibility_rule(base) == derive.VISIBILITY_ALL
    assert derive.effective_visibility_rule({**base, "visibility_rule": "any"}) == derive.VISIBILITY_ANY
    assert derive.effective_visibility_rule({**base, "visibility_rule": "all"}) == derive.VISIBILITY_ALL
    with pytest.raises(AssertionError):
        derive.effective_visibility_rule({**base, "visibility_rule": "or"})


def test_any_and_all_projections_really_differ():
    """**机制存活读数**：`any`（∪）与 `all`（∩）在同一组 unit 码上真的给出不同岗位集。

    否则「支持逐页 any|all」就是一句空话（两个分支等价 ⇒ 规则字段无判别力）。
    现取例：一页并发 `processing:manage`（admin · operator · product_manager）与 `order:list`
    （admin · 客服 · 财务 · operator · sales）⇒ `all` 比 `any` 窄。
    """
    derive, manifest = load_derive(), load_manifest()
    tables = derive.role_tables(manifest)
    codes = ["processing:manage", "order:list"]
    every = derive.project_visibility(derive.VISIBILITY_ALL, codes, tables)
    any_ = derive.project_visibility(derive.VISIBILITY_ANY, codes, tables)
    print(f"∩(all) = {every} / ∪(any) = {any_}")
    assert every != any_, "两个投影等价 ⇒ `visibility_rule` 字段没有判别力（本判据是空断言）"
    assert set(every) < set(any_), f"`all` 必须是更严的那一侧：{every} ⊄ {any_}"


def test_p3_coverage_expansion_is_load_bearing():
    """**M1/M2 覆盖面按 P3 更新**的四条红证 + 一条对照读数（全部在内存里构造坏形态）。

    ① 未登记副本 ⇒ 具名红（注入一个假命中）；
    ② 陈旧登记 ⇒ 红（登记了一个已不命中的面 / 文件）；
    ③ 登记的 `hits` 与现取不符（涨或跌）⇒ 红；
    ④ 上限登记存在且只许缩短（`P1 守卫的 LEDGER_CEILINGS['PAGE_VISIBILITY_GAPS'] == 4`）。
    对照读数：**只改注释**（在真文件文本里插一句注释）⇒ 命中数**不变**（剥注释是单一实现）。
    """
    p1 = load_manifest_guard()
    registry = p1.load_json(p1.SOURCES_PATH)
    hits = list(p1.repo_copy_face_hits())
    registered = {(e["face"], e["file"]): e["hits"] for e in registry["sources"]}
    p3_hits = {h["face"]: h for h in hits if h["face"] in P3_COPY_FACES}
    problems: list[str] = []
    for face in P3_COPY_FACES:
        if face not in p3_hits:
            problems.append(f"P3 形态面 `{face}` 现取 0 命中 ⇒ 它已失效（判据空跑）")
    problems += coverage_problems()

    injected = hits + [{"face": "page-first-screen-anchors", "file": "frontend/admin-web/src/config/page-codes.ts", "count": 1}]
    if not any("page-codes.ts" in x for x in p1.unregistered_copies(injected, registry)):
        problems.append("注入一个未登记副本后 `unregistered_copies` 没报出 ⇒ 「未登记即红」是空断言")

    ghost = copy.deepcopy(registry)
    ghost["sources"] = ghost["sources"] + [{"face": "page-first-screen-anchors", "file": "ghost.ts", "hits": 1}]
    if not any("ghost.ts" in x for x in p1.stale_registrations(hits, ghost)):
        problems.append("登记的副本已不命中却没报出 ⇒ 「陈旧登记亦红」是空断言")

    drifted = copy.deepcopy(registry)
    for entry in drifted["sources"]:
        if entry["face"] in P3_COPY_FACES:
            entry["hits"] = entry["hits"] + 1
            break
    else:
        problems.append("找不到 P3 形态面的登记条目 ⇒ 本红证没验到东西")
    if not any("登记命中数漂移" in x for x in p1.copy_hit_count_drift(hits, drifted)):
        problems.append("`hits` 被改后 `copy_hit_count_drift` 没报出 ⇒ 「hits == 现取」是空断言")

    # 对照读数：把「锚的写法」放进**注释**里追加到语料末尾 ⇒ 命中数**不得**变化（注释被剥掉）。
    # ⚠️ 形态字面量在这里**拆开拼**（`"MenuReadAnchor" + "("`）：本判据自己也要被 M1 扫，
    # 而写进 docstring / 字符串里的「举例」会被当真命中（P1 的 `Case Trust` 规则 G 同族教训）——
    # 本文件第一版就因为在 docstring 里举了一个构造调用的例子，被自己的形态面抓成未登记副本。
    target = next(e["file"] for e in registry["sources"] if e["face"] == "page-first-screen-anchors")
    text = (REPO_ROOT / target).read_text(encoding="utf-8")
    shape_literal = "MenuReadAnchor" + "("
    control = text + "\n# " + shape_literal + " 只是一句注释：注释里的写法不算命中\n"
    before = p1.copy_face_hits({target: text})
    after = p1.copy_face_hits({target: control})
    if before != after:
        problems.append(f"把锚的写法放进注释后命中数变了（{before} → {after}）⇒ 剥注释口径被绕过")
    assert problems == [], "覆盖面红证不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def _neutralize(spec: dict, text: str) -> str:
    """把形态面的锚**就地改名**（内存里、保持语法有效）—— 用来证明「删掉锚 ⇒ 必红」。

    ⚠️ **不是**「删掉匹配的那些行」：匹配行常常是**多行表达式的首行**（`"/x": <锚的构造调用>(…, (`），
    逐行删除会让括号失衡 ⇒ 剥注释器 fail-closed 抛错（实测踩过：`EOF in multi-line statement`）。
    改成给标识符加后缀：括号/引号配平不变，而 `shape` **不再命中** —— 这才是「那个锚没了」的最小变异。
    """
    rx = re.compile(spec["shape"], re.M)

    def repl(match: re.Match) -> str:
        matched = match.group(0)
        if ":" in matched:
            return matched.replace(":", "_X:", 1)
        if "=" in matched:
            return matched.replace("=", "_X=", 1)
        return matched[:-1] + "_" + matched[-1]

    return rx.sub(repl, text)


def test_p3_copy_face_anchors_are_load_bearing():
    """P3 新增形态面的锚**条数冻结、且删掉必红** —— 全部在**内存语料**上自证（不改磁盘）。

    每个形态面的 `shape` 在目标文件里的**出现次数必须等于登记的 `hits`**（所以「加一条锚点而不同步
    登记表」= 现取 ≠ 登记 ⇒ 红）；把锚**就地改名**（内存变异，语法仍有效） ⇒ 该面命中消失 ⇒
    `stale_registrations` 具名报出 ⇒ 那条「删掉会红」是**可复算的断言**，不是空话。
    """
    p1 = load_manifest_guard()
    registry = p1.load_json(p1.SOURCES_PATH)
    by_face = {e["face"]: e for e in registry["sources"] if e["face"] in P3_COPY_FACES}
    assert len(by_face) == len(P3_COPY_FACES), f"P3 形态面登记不全：{sorted(by_face)}"
    problems: list[str] = []
    for face in P3_COPY_FACES:
        spec = next(f for f in p1.COPY_FACES if f["id"] == face)
        entry = by_face[face]
        text = (REPO_ROOT / entry["file"]).read_text(encoding="utf-8")
        rx = re.compile(spec["shape"], re.M)
        found = rx.findall(p1.strip_for(Path(entry["file"]).suffix, text))
        if len(found) != entry["hits"]:
            problems.append(
                f"`{face}` 的锚在 {entry['file']} 里出现 {len(found)} 次，而登记 `hits` = {entry['hits']}"
                "（锚必须条数冻结：加一条锚点就要同 PR 更新登记表）"
            )
        mutated = _neutralize(spec, text)
        if mutated == text:
            problems.append(f"`{face}` 的锚改名变异未生效 ⇒ 「删掉必红」是空断言")
            continue
        if any(h["face"] == face for h in p1.copy_face_hits({entry["file"]: mutated})):
            problems.append(f"把 `{face}` 的锚改名后该面仍命中 ⇒ 锚不是那个锚（红证打偏）")
        remaining = [h for h in p1.repo_copy_face_hits() if h["face"] != face]
        if not any(face in x for x in p1.stale_registrations(remaining, registry)):
            problems.append(f"拔掉 `{face}` 的锚后没有报出陈旧登记 ⇒ 那条断言是空话")
    assert problems == [], "P3 形态面锚自证不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_non_derived_and_uncovered_faces_are_registered():
    """覆盖面登记：非派生面与未覆盖面**逐条写清**「覆盖不到什么、谁看」，且**只许缩短**。"""
    problems = coverage_problems()
    print(f"非派生面 {len(NON_DERIVED_FACES)} 条 / 未覆盖面 {len(UNCOVERED_FACES)} 条 / "
          f"gap 台账 {len(VISIBILITY_GAP_REASONS)} 条")
    assert problems == [], "覆盖面台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（**当场在内存里构造坏形态**，变异体直接作为判据入参）
# ══════════════════════════════════════════════════════════════════════════════


def _mutate_page(manifest: dict, path: str, **changes) -> dict:
    """把某一页改坏（内存构造）—— 并**自证变异真的被读到**（变异体与原文逐叶不同）。"""
    mutated = copy.deepcopy(manifest)
    for page in mutated["pages"]:
        if page["path"] == path:
            page.update(changes)
            break
    else:
        raise AssertionError(f"变异目标 {path} 不在清单 pages[] 里（红证打偏 ⇒ 视为失败）")
    assert leaves(mutated["pages"]) != leaves(manifest["pages"]), (
        "变异注入未生效（变异体与原文逐叶相同）⇒ 该红证是空断言"
    )
    return mutated


def test_flattening_a_page_is_red():
    """**把某页压成一个码**（多码页被压平）⇒ 必红；三条分支各单独判一次。"""
    derive, manifest, present = load_derive(), load_manifest(), present_faces()
    assert face_problems(derive.derive_page_faces(manifest), present) == [], "落地态竟不绿（前提不成立）"

    flattened = _mutate_page(
        manifest, "/production/processing", units={"production:view": ["GET /api/admin/processing-items"]}
    )
    faces = derive.derive_page_faces(flattened)
    problems = face_problems(faces, present)
    assert any("multi_code_pages" in p for p in problems), f"压平多码页没被报出：{problems}"
    assert faces["multi_code_pages"] == {"/production/routings": ["processing:manage", "production:view"],
                                         "/settings": ["dashboard:view", "system:manage"]}, (
        "压平后多码页集应只剩 2 页（证明 multi_code_pages 是现算的，不是抄来的）"
    )
    assert any("parity_residual_pages" in p for p in problems), "压平后残留页集变化没被报出"

    renamed = _mutate_page(manifest, "/settings", gate="dashboard:view")
    route_problems = route_guard_problems(derive.derive_page_faces(renamed), present)
    assert any("/settings" in p for p in route_problems), f"改某页 gate 后 C4 没报出：{route_problems}"


def test_residual_ledger_only_shrinks():
    """残留台账**只许缩短**：修好一处而不销账 ⇒ 红；新增一处未登记 ⇒ 红。"""
    derive, present, parity = load_derive(), present_faces(), load_parity_guard()
    manifest = load_manifest()
    fixed = _mutate_page(manifest, "/production/pool", gate="processing:view")
    residuals = derive.derive_page_faces(fixed)["parity_residual_pages"]
    assert "/production/pool" not in residuals, "对齐两侧后该页应离开残留集（证明派生是现算的）"
    assert sorted(residuals) != sorted(parity.MENU_READ_PARITY_RESIDUALS), (
        "修好一处后派生集仍与现值台账相等 ⇒ 本判据读的不是派生的残留集（空断言）"
    )
    broken = _mutate_page(manifest, "/production/remnants", gate="production:view")
    residuals2 = derive.derive_page_faces(broken)["parity_residual_pages"]
    assert "/production/remnants" in residuals2, "新增一处不一致后派生集没变 ⇒ 本判据空跑"
    assert sorted(residuals2) != sorted(parity.MENU_READ_PARITY_RESIDUALS), (
        "新增不一致后派生集仍与台账相等 ⇒ 陈旧台账分支没被验到"
    )


def test_visibility_rule_relaxation_is_red():
    """把某页的规则改成 `any`（放宽）或删掉字段 ⇒ 逐页对账必红（现值要求 `all`）。"""
    derive, manifest, present = load_derive(), load_manifest(), present_faces()
    relaxed = _mutate_page(manifest, "/settings", visibility_rule="any")
    problems = visibility_problems(derive.derive_page_faces(relaxed), present, relaxed)
    assert any("visibility./settings.rule" in p for p in problems), f"放宽规则没被报出：{problems}"

    dropped = _mutate_page(manifest, "/production/routings", visibility_rule=None)
    faces = derive.derive_page_faces(dropped)
    assert faces["visibility"]["/production/routings"]["rule"] == derive.VISIBILITY_ALL, (
        "缺字段后应落到 fail-closed 的 `all`（本项原本就是 `all` ⇒ 该页仍绿，见下一条对照）"
    )
    dropped2 = _mutate_page(manifest, "/notifications", visibility_rule=None)
    problems2 = visibility_problems(derive.derive_page_faces(dropped2), present, dropped2)
    assert any("notifications" in p for p in problems2), (
        f"gap 页被抹掉规则后没被报出：{problems2}"
    )


def test_manifest_mutation_is_really_read():
    """**「变异真的被读到」自证**：内存变异体喂进判据后读数**必须跟着变**（不是空断言）。"""
    derive, manifest, present = load_derive(), load_manifest(), present_faces()
    mutated = _mutate_page(manifest, "/production/routings", gate="processing:manage")
    base_faces = derive.derive_page_faces(manifest)
    mutated_faces = derive.derive_page_faces(mutated)
    assert base_faces["route_guard_codes"]["/production/routings"] == "production:view"
    assert mutated_faces["route_guard_codes"]["/production/routings"] == "processing:manage", (
        "变异体没被派生器读到 ⇒ 这批红证全是空断言"
    )
    assert leaves(mutated["pages"]) != leaves(manifest["pages"]), "变异体与原文逐叶相同（自证失败）"
    assert page_problems(mutated, present) != [], "变异体喂进 pages 对账后竟然不报 ⇒ 对账没读它"


def test_comment_only_change_is_not_red():
    """**对照读数**：只改清单的**散文**（`_note` / `_boundary`）⇒ 派生与对账**都不变**（应当不红）。

    这不是「判据失效」的证据，而是它的**判别力边界**：判据判的是语义（声明的事实），
    不是「文件变了没有」。同一形态的另一半（改源码**注释**）在 `test_p3_coverage_expansion_is_load_bearing`
    的对照读数里验（形态面命中数不变）。
    """
    derive, present = load_derive(), present_faces()
    manifest = load_manifest()
    prose = copy.deepcopy(manifest)
    prose["_note"] = prose["_note"] + "（只改散文的一句）"
    prose["_boundary"] = prose["_boundary"] + "（只改散文的一句）"
    assert prose != manifest, "散文变异注入未生效（自证失败）"
    assert face_problems(derive.derive_page_faces(prose), present) == []
    assert page_problems(prose, present) == []
    assert route_guard_problems(derive.derive_page_faces(prose), present) == []
    assert menu_column_problems(derive.derive_page_faces(prose), present) == []


def test_unreconciled_segment_is_red():
    """把 `pages` 从 P1 守卫的对账段里拿掉 ⇒ 覆盖面判据必红（新段逃出对账 = 新的并行真值）。"""
    p1 = load_manifest_guard()
    original = p1.RECONCILED_SEGMENTS
    try:
        p1.RECONCILED_SEGMENTS = tuple(s for s in original if s != "pages")
        problems = coverage_problems()
    finally:
        p1.RECONCILED_SEGMENTS = original
    assert any("RECONCILED_SEGMENTS" in p for p in problems), f"段被移出对账后没报出：{problems}"
