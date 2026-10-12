# case_ids: MC-032, MC-033, MC-034, MC-062
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
| C1 / C3 码列 | `menu_node_codes`（27 节点）/ `auth_menu_codes`（20 条） | `parse_menu_ts_nodes` / `parse_menus()['auth']` |
| C4 守卫码列 | `route_guard_codes`（每页 `path → gate`） | `parse_route_guard`（26 条前缀） |
| 页面面两张台账 | `multi_code_pages`（一页多码）/ `parity_residual_pages`（节点码 ≠ 页面读码） | `MULTI_READ_ENDPOINT_PAGES`（0）/ `MENU_READ_PARITY_RESIDUALS`（0） |
| 可见性 | `visibility`（按 `visibility_rule` 把 units 投影成「看得见该菜单的岗位集」） | 现值岗位集（`seed` ∪ `fallback` 的持码者） |

## 🔴 零 delta 是本阶段唯一的验收口径（违反即返工）

派生结果与现值必须**逐值相等**、**逐项点名**（不许用「数量相等」充数）。若不等 ⇒ **只报告、不修**
（那是 P4 的活，且必须由人在看过逐行 census 后点头）⇒ 故本文件的判据在「不等」时输出的是
**完整不一致清单**（每项一行），不是一个布尔量。

**特别地：多端点页与已登记残留不许被「压平」。** #5675 / #5682 已确立 `MULTI_READ_ENDPOINT_PAGES`
（多端点页必须具名 + 码集逐值冻结）与 `MENU_READ_PARITY_RESIDUALS`（节点码 ≠ 页面读码的逐条残留）；
P3 的派生**必须保留「一页多码」这一结构事实**（一页并发**两个以上**读码 ⇒ 逐项具名报出，不许压成
「一个页面一个码」）**与残留集的逐值相等**（两侧都只许缩短）。🔴 两者的**当前条数不写进散文**
（issue #6580 后都为 0）—— 写死一次就漂一次，读数现取见打印（`PROSE_READINGS` 的登记项）。
#5675 时点的具名残留是 `/dashboard`、`/production/pool`、`/production/saving-board`、
`/production/processing`、`/production/routings`、`/settings`（**已随 P4 与 issue #6580 全部销账**）。

## `visibility_rule`（逐页 `any|all`，默认 `all`）

设计 §3.4 问题 3 的结论：`/production/processing` 需要「任一 unit 可用即可见」，而 `/settings` 的语义是
「整页管理」——「允许半个页面可见」会造出新的「看得见做不了」⇒ **逐页声明 + 默认 `all`（fail-closed）**。
本判据把「现值要求」机械算出来（`all` ∩ / `any` ∪ 能否复现现值岗位集），并要求清单声明**逐页相等**：
现取 = `all` **20** 页 / `any` **0** 页 / `node-code` **1** 页（后者 = 投影复现不了现值，进
`PAGE_VISIBILITY_GAPS`，只许缩短，出口由 P4 逐条人裁定）。
⇒ 任何人把某页改成 `any`（放宽）而现值不要求它 ⇒ **红**。

## 数字纪律（issue #6771）：**写死的条数 ⇒ 要么现取、要么显式冻结**

本文件里出现的每一个「条数读数」都是**登记项**，三张表各管一类（漂了**必红**，且判红可归因）：

| 表 | 管什么 | 判据 |
|---|---|---|
| `PROSE_READINGS` | 散文 / 字符串字面量里**对当前状态的读数** | `prose_reading_problems`：逐条**现取复算**，不等 ⇒ 红（报出「写的是几 / 现取是几」）；锚被改写 / 命中不唯一 ⇒ 红；**未登记即红**（按 `READING_SHAPES` 扫全文） |
| `NARRATIVE_NUMBERS` | **沿革 / 结构叙事**里的历史数字（`X → Y` 形态） | 同上判据：锚必须仍逐字在文本里（只许缩短）——它们**不是**当前读数，故不禁写死 |
| `FROZEN_CEILINGS` | **只能写死**的那一类：冻结上界（只许缩短） | `frozen_ceiling_problems`：现取 > 上界 ⇒ 红（具名 + 读数 + 出口）；上界与侧真值不一致 ⇒ 红 |

🔴 **口径**：真实集合增长而台账没更新 ⇒ **明确判红**（不是自动接受）——每条冻结上界的 `grew_by`
逐字写明由哪个判据**具名**报出，禁止「悄悄变大」。

## 覆盖面（**覆盖不到什么**，与设计 §5.3 逐条对齐）

- 🔴 **C2（`MenuController` 的 `MENU_TREE` 码列）不由 `pages[]` 派生**：它有 5 个**动作节点**
  （新增员工 / 订单详情 / 企业基础设置（经营域）/ 加工单操作 / 入库单操作 —— 不是页面）且「经营看板」节点无码而控制器有码
  ⇒ 它的码列不属「页面 → 码」面（现值由 M1 形态面 `menu-tree` 登记）。登记在 `NON_DERIVED_FACES`。
- **岗位全集 = 种子 ∪ 回退**（7 个）。租户自建的岗位（`roles` 表里新建的角色）**读不到** ⇒ 可见性投影
  对它们**未取证** —— 设计 §3.4 问题 3 第 1 行登记的 `/dashboard` delta 正落在这里（零权限的自定义岗位
  今天因「无码不过滤」看得见该菜单，投影后会看不见）。登记在 `UNCOVERED_FACES`。
- **只派生码列**：`pages[].units` 的 `label`（tab 中文名）/ icon / 关键词 / 组序**不搬进清单**
  （散文与展示属性；要它们时由 P4 的 `partial_visibility_ack` 带理由引入）。
- **只覆盖 `frontend/admin-web` 的页面**：bmini / worker-h5 的页面不在本面内（`frontend/worker-h5` 另有裁定 13）。
- **不判「现值对不对」**：投影再准也只证明**零 delta**，不证明现值**对**（设计 §5.3 的 M3 边界同款）；
  gap 台账与残留台账的存废是**授权裁定**，归 P4。
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
#: **本文件自己** —— 散文读数的扫描面（`prose_reading_problems` 读它，不是读工作树里的别的东西）。
THIS_FILE = Path(__file__).resolve()

#: **冻结下界**（与 `FROZEN_CEILINGS` 相对的那一类）：**只防清空**、**不防**「删掉任意一项」。
#: `dashboard_page_routes()` 扫 `app/(dashboard)/**/page.tsx`；这个下界防的是「判据在扫空气」
#: （路径漂移 / 目录改名会让它扫到**零条**而**恒真通过**）。落地时现取 = 42，下界留出余量 = 30。
#: 🔴 它**不**随数据漂，也**不**被 `FROZEN_CEILINGS` 管（那是「只许缩短」的上界，语义不同）；
#: 另一半（「页面缺文件」= 删掉任意一项）由**现取**的 ⊆ 判据 `dashboard_route_coverage_problems`
#: 逐条具名负责。
DASHBOARD_PAGE_ROUTES_FLOOR = 30
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
#: 各条**都没有单一对应页面**（路由常量 ≠ 页面）：入口在别的页面里（`/categories`）/
#: 已并入别的页面（`/processing-orders`）/ 会话页无节点（`/chat`）/ **子树父前缀**（`/agent-workspace`，
#: issue #5977）；`/processing` 走的是另一张表（**同一页的第二前缀**，该页 `path` 是 `/production/processing`）。
ROUTE_PREFIX_ALIASES = {
    # 🔴 2026-10-09（issue #6580）：「加工项管理」菜单节点已移除 ⇒ 别名目标从它改钉**合并后的
    # 入口节点**「企业基础设置」（`/settings`，gate = `production:view`）—— `/processing` 是
    # `/production/processing`（→ 重定向 `/settings`）的**同一页第二前缀**，两者码逐字相同。
    "/processing": "企业基础设置",
}
ROUTE_PREFIX_EXCEPTIONS = {
    "/chat": (
        "会话页没有侧边栏节点（「在线接待」的 `path` 是 `/agent-workspace/human-sessions`）"
        "⇒ 该前缀不属「页面 → 码」面（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
    # issue #5977：`/agent-workspace` 是**子树父前缀**（根 = 重定向占位页 / `sessions` = 会话监控
    # 都**没有侧边栏节点**；子树唯一在册页面是 `/agent-workspace/human-sessions`）⇒ 它本身不是
    # 任何一页的 `path`，按本台账的口径必须**具名**。
    # 🔴 **本条目让本账台上限 3 → 4（同 PR 显式、diff 里看得见）**：不是放宽门禁，而是把本次修复
    # **新引入的守卫前缀**登记进来 —— 台账的机制就是「非派生前缀必须具名」，不登记才是假绿。
    # 台账**仍只许缩短**（销掉任一条 ⇒ 红）；码与「在线接待」节点逐字同码（`ROUTE_PREFIX_ALIASES`
    # 的语义是「同一页的第二前缀」，与本条不同 ⇒ 不走别名）。
    "/agent-workspace": (
        "客服工作台子树的**父前缀**（覆盖 `/agent-workspace`、`/agent-workspace/sessions`、"
        "`/agent-workspace/human-sessions`）—— 根与会话监控都没有侧边栏节点，故不属"
        "「页面 → 码」面（同 `/chat` 的理由）；子树唯一码 = 「在线接待」节点的 `agent:session`"
    ),
    "/categories": (
        "分类管理**没有独立侧边栏节点**（入口在商品列表页内）⇒ 不属「页面 → 码」面"
        "（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
    "/processing-orders": (
        "加工单唯一入口已并入「生产看板」⇒ 本前缀只作旧链接兼容，不属「页面 → 码」面"
        "（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）"
    ),
    # 🔴 2026-10-09（issue #6580）：下面三条是**菜单项已移除、路由保留**的旧入口兼容前缀
    #（仓内口径：旧深链不 404）。它们的**新入口**分别是 `/settings`（企业基础设置）——
    # 但按本台账的口径，一条前缀只能钉「它是某一页的 `path`」（别名）或「它不属于页面→码面」
    #（例外，本条）；这三个路径**本身都不是任何在册页面的 `path`** ⇒ 逐条具名。
    # 🔴 **本三条让本账台上限 4 → 7（同 PR 显式、diff 里看得见）**：不是放宽门禁 ——
    # 台账的机制就是「非派生前缀必须具名」，不登记才是假绿（同 issue #5977 的 4 条那次）。
    # 台账**仍只许缩短**（销掉任一条 ⇒ 红）。
    "/production/processing": (
        "「加工项管理」菜单项已移除（issue #6580：功能体并入 `/settings` 企业基础设置页内的配置域）"
        "⇒ 本前缀只作旧链兼容（重定向 `/settings?domain=processing-fee`），不属「页面 → 码」面"
        "（判据 11③ 的 `ROUTE_WITHOUT_MENU_NODE` 同款理由）；守卫码 = 新入口页的 `production:view`"
    ),
    "/production/routings": (
        "「工艺配置」菜单项已移除（issue #6580：功能体并入 `/settings`）⇒ 本前缀只作旧链兼容"
        "（重定向 `/settings?domain=craft-route`），不属「页面 → 码」面；守卫码 = `production:view`"
    ),
    "/settings/params": (
        "「参数总览」一级项已撤掉（issue #6580：内容回到 `/settings` 页内的配置域）⇒ 本前缀只作旧链兼容"
        "（重定向 `/settings`），不属「页面 → 码」面；守卫码 = `production:view`"
    ),
}

#: 页面存在、但**守卫码 ≠ 该页 `gate`** 的前缀 —— 逐条具名（只许缩短；**P4 后 0 条**）。
#: 🔴 issue #5699（P4）：`/dashboard` 一处已销账 —— 节点码补成 `dashboard:view`（= 该页第一屏读码
#: = 守卫码）⇒ 三处同码。本表从此为空：任何新出现的不一致都**未登记即红**。
ROUTE_GUARD_GATE_MISMATCHES: dict[str, str] = {}

#: **不是页面**的菜单节点（C2 的「动作节点」）—— 逐条具名 + 码冻结（只许缩短；键集与现取逐值相等）。
#: 它们是「**动作**」（去某个页面里的某个动作），没有 `path` ⇒ 不属「页面 → 码」面；
#: 现值由 M1 形态面 `menu-tree` 登记。
ACTION_NODE_CODES: dict[str, dict[str, str]] = {
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
    # 🔴 2026-10-09（issue #6580）新增：`MenuController` 的 org-center 组里那个**权限码节点**
    # 「企业基础设置（经营域）」（码 = `system:manage`）—— 它**没有 `path`**、也不是菜单项。
    # **为什么它必须存在**：合并后菜单项 `/settings` 的节点码改成了 `production:view`（生产配置面
    # 的唯一入口要对真实配置者可见），而该页**经营域**（企业信息 / AI 客服 / 工人端页面 / 通知设置）
    # 的读端点仍挂 `system:manage` ⇒ 若不留这个节点，那个码会从**权限勾选树**里彻底消失
    # （页内经营域永远无法授予，只能靠 DB 手改）。
    # 它**不是**「页面 → 码」面的一员（无 path）⇒ 按本台账口径必须具名（未登记即红）。
    "企业基础设置（经营域）": {
        "code": "system:manage",
        "reason": "只为让经营域的权限码**仍可授予**而保留的权限码节点（不是菜单项、没有 path）：菜单项 `/settings` 已改挂 `production:view`，该码在本页经营域（企业信息 / AI 客服 / 工人端页面 / 通知设置）上仍是实际生效码",
        "owner": "企业基础设置页的经营域 + `MenuController` 的 org-center 组 + 本判据的动作节点台账",
    },
    # 🔴 2026-10-12（issue #6759）新增两条：**手机端写码**进权限勾选树（用户当日裁定）。
    # 两条都**没有 `path`**、不是菜单项 ⇒ 不属「页面 → 码」面（按本台账口径必须具名）。
    # 它们今天只能靠「岗位权限」页的「其它权限」区（`/api/admin/permissions` 差集）授予，
    # 而手机端「智能派单 / 入库过账」两个写面**就挂这两个码**
    #（`frontend/bmini-app/src/utils/adminPermission.ts` 的 `processing:update` / `inbound:create`）
    # ⇒ 补进员工个人权限树 = 管理员能直接给员工勾这两个写动作。
    # ⚠️ 只加**勾选项**：两条码的授权口径与 `roles.seed` **零 delta**（没有岗位因此多码）。
    "加工单操作": {
        "code": "processing:update",
        "reason": "「加工单操作」是手机端派单的**写码**（PC 侧 = `ProductionPoolController` 的成批派单 / `ProcessingOrderController` 的生成与状态更新），不是页面",
        "owner": "生产管理组菜单面（组尾动作码节点）+ 本判据的动作节点台账",
    },
    "入库单操作": {
        "code": "inbound:create",
        "reason": "「入库单操作」是手机端过账的**写码**（PC 侧 = `InboundOrderController` 的建单 / 过账 / 作废 / 期初导入），不是页面",
        "owner": "仓储与物料组菜单面（组尾动作码节点）+ 本判据的动作节点台账",
    },
}

#: **页面节点**上「码列 ≠ 该页 `gate`」的具名不一致（只许缩短；**P4 后 0 条**）。
#: 🔴 issue #5699（P4）：C2 的经营看板一处已销账（`menu.ts` 补上同一码）⇒ 本表为空。
MENU_CODE_MISMATCHES: dict[str, str] = {}

#: `visibility_rule = node-code`（**投影复现不了现值**）的**逐页理由**（只许缩短；键集与现取逐值相等）。
#: 🔴 issue #5699（P4）：4 条 **→ 1 条** —— `/production/pool`、`/production/saving-board`、
#: `/production/processing` 三页已按子菜单粒度收敛成**单码**（`visibility_rule` 变成 `all`，
#: 投影能复现现值 ⇒ 离开 gap 台账）；只剩 `/notifications`（该页**两侧都无码**，见下）。
VISIBILITY_GAP_REASONS = {
    # 🔴 2026-10-09（issue #6580）：本表原有一条 `/settings`（合并页投影复现不了现值）——
    # 随 `test_agent_permission_parity.py` 的锚点口径收窄（只收**本页自身 effect 驱动面**；
    # 经营域面板按各自码**条件挂载**）**销账**：该页现为**单码页**（`production:view`，规则 `all`）
    # ⇒ 投影能复现现值，gap 消失。⚠️ 本表只许缩短：谁若把某个域的无条件调用接回页面自身 effect，
    # 投影立刻复现不了 ⇒ 未登记即红（判据当场要求具名）。
    "/notifications": {
        "reason": (
            "该页第一屏唯一读端点 `GET /api/admin/notifications` **未被任何权限码把守**"
            "（`units` 里只有 `__unannotated__` 一组）⇒ 投影无输入，可见性仍取节点码（今天 `gate = null`"
            "⇒ 全员可见）。🔴 **issue #5699（P4）的结论：具名保留**（不是漏改）——"
            "该页**两侧都无码**（节点 `null` ∧ 端点未注解）⇒「看得见」与「调得动」由**同一个空码**决定，"
            "结构上不可能出现「菜单看得见、点进去 403」；要把它变成「有码」必须**新造一个权限点**"
            "并给全部岗位授码（= 新增一处需要维护的真值，且对现有使用者是一次收窄/放宽的授权变更）"
            "⇒ 超出 P4「按子菜单粒度收敛已有码」的范围，须人类单独裁定。"
            "出口 = 给该端点补注解（判据 8 的 `UNANNOTATED_ENDPOINTS` 台账）或明确「该页无需权限」。"
        ),
        "owner": "通知中心页 + 端点注解面（`NotificationController`）+ 本判据的 gap 台账",
    },
}

#: **不由 `pages[]` 派生**的面（**只许缩短**）：每条写清为什么它不属「页面 → 码」。
NON_DERIVED_FACES = (
    {
        "face": "C2：`backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE` 码列（24 条）",
        "reason": (
            "它有 5 个**动作节点**（新增员工 / 订单详情 / 企业基础设置（经营域）/ 加工单操作 / 入库单操作 —— 不是页面，没有 `path`）"
            "且「经营看板」节点无码而控制器给 `dashboard:view` ⇒ 它的码列是「权限目录」语义，"
            "不属「页面 → 码」面（设计 §2.4 把 C2 与 C1/C3/C4 分开列）。现值由 M1 形态面 `menu-tree` 登记。"
        ),
        "owner": "RBAC 跟踪单 #5699（P4 若裁定「动作节点也进页面表」，本项随之缩短）",
        "issue": "#5699",
    },
)

#: **未覆盖面台账**（只许缩短）：照实验登记，不假装覆盖。
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
        "face": "「可见面 == 可做面」的**产品裁定**（残留台账与 gap 台账的存废）",
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


# ══════════════════════════════════════════════════════════════════════════════
# 数字纪律（issue #6771）：**写死的条数** ⇒ 要么现取、要么显式冻结
# ══════════════════════════════════════════════════════════════════════════════
#
# 病灶（#6771）：本文件的**打印文本 / 散文 / 台账字符串**里写死了一批条数，随真实数据漂移而
# **没有任何东西会红**（issue #6768 新增两个动作节点后：`MENU_TREE` 的 26 → 24、
# `auth_menu_codes` 的 14 → 20、`PAGE_VISIBILITY_GAPS` 从 4 → 1 …… 复核者读到的「现状」全是旧的，
# 而那个包正因为信了其中一个数字先报了错读数、再发更正）。
# 处置 = 三张表 + 两条纯函数判据：
#   · 能现取的一律现取 —— `present_readings()` 是**唯一**取数口径（清单 / 派生器 / P1 守卫 / 既有解析器）；
#   · **只能写死**的（冻结上界）逐条登记：现取侧 + 上界 + 「增长时谁具名红」+ 理由；
#   · 沿革 / 结构叙事里的历史数字登记进 `NARRATIVE_NUMBERS`（不是当前读数，故不禁写死）。
# 🔴 本包**只治读数漂移**：不改任何判定逻辑与门禁通过条件（冻结上界一律沿用落地值）。

#: 「条数读数」的**写法**（扫描面 = 本文件全文；**未登记即红**）。
#: 只认读数的三种写法（加粗 / 裸写 / 括号单列），分类词 = 条 / 页 / 个 / 项 / 节点 ——
#: **不**扫叙述句里的中文数字（「三条」不在射程），**不**扫 `第 N 条`（引用文档条款号，不是读数）。
#: 🔴 **扫描面边界（如实登记，§19.1）**：分类词只有上述五个 —— `N 码` / `N 份` 形态**有意排除**
#: （它们会命中 `C3 码列`、「同一事实的第 2/3 份副本」这类**不是读数**的写法，噪声会淹掉判据），
#: 故这两个形态里的写死读数**不在机器射程**（靠人核 / 靠 `PROSE_READINGS` 主动登记）。
READING_SHAPES: tuple[re.Pattern, ...] = (
    re.compile(r"\*\*(\d+)\*\*\s*(?:条|页|个|项|节点)"),
    re.compile(r"(?<!第 )(\d+)\s*(?:条|页|个|项|节点)"),
    re.compile(r"（(\d+)）"),
)

#: **只能写死的那一类数字**（冻结快照 / 只许缩短）—— 显式台账，每条五段：
#:   · `id`      —— **可归因的名字**（判红时逐字报出它，不让接手的人再去猜是哪一个数）；
#:   · `count`   —— **现取条数**（零参函数，每次当场算；**不读缓存**，否则内存注入验不动）；
#:   · `ceiling` —— **冻结上界**（只许缩短：现取 > 上界 ⇒ 红）；
#:   · `grew_by` —— **「真实集合增长而台账没更新」时谁具名红**（口径 = **明确判红**，不是自动接受）；
#:                 写 `None` 的两条是**纯声明面**：没有独立的现取侧 ⇒ 本上界就是唯一的闸（如实登记）；
#:   · `reason`  —— **这个数字为什么只能写死**（哪来的；放宽要谁点头）。
#: 🔴 **禁止「悄悄变大」**：现取 > 上界 ⇒ 红，报出的是「哪个上界 / 现取是几 / 上界是几 / 出口」。
#: 🔴 **上界下调**（收紧）永远合法；**上调**必须在同一个 PR 里改本表并在 `reason` 里补一句为什么。
FROZEN_CEILINGS: tuple[dict, ...] = (
    {
        "id": "PAGE_VISIBILITY_GAPS",
        "count": lambda: len(visibility_gap_pages()),
        "ceiling": 4,
        # 侧真值 = P1 守卫的 `LEDGER_CEILINGS`：**两处冻结**（本表 + P1 守卫）比一处更难被悄悄放宽。
        "ceiling_from": lambda: load_manifest_guard().LEDGER_CEILINGS["PAGE_VISIBILITY_GAPS"],
        "ceiling_from_where": "P1 守卫的 `LEDGER_CEILINGS['PAGE_VISIBILITY_GAPS']`",
        "grew_by": "`visibility_problems`（『未登记即红』具名报出是哪一页；陈旧条目同样红）",
        "reason": (
            "P3 的 gap 台账：**可见性投影复现不了现值**的页面（每条的出口都是一次授权裁定，归 P4）"
            "⇒ 只许缩短。**上界落地值 = 4**（P4 后现取 = 1）。"
        ),
    },
    {
        "id": "VISIBILITY_GAP_REASONS",
        "count": lambda: len(VISIBILITY_GAP_REASONS),
        "ceiling": 4,
        "grew_by": "`visibility_problems`（同上）",
        "reason": (
            "gap 台账的**具名条目**（理由 + 谁负责）；与 `PAGE_VISIBILITY_GAPS` 同生共死"
            "（条目集与现取 gap 页集由 `visibility_problems` 双向闭合）。**上界落地值 = 4**（P4 后现取 = 1）。"
        ),
    },
    {
        "id": "ACTION_NODE_CODES",
        "count": lambda: len(ACTION_NODE_CODES),
        "ceiling": 5,
        "grew_by": "`menu_column_problems`（『动作节点必须具名登记』具名报出是哪一个节点；已销账的陈旧条目同样红）",
        "reason": (
            "C2/C3 里**不是页面**的菜单节点（没有 `path`）必须逐条具名 + 码冻结 ⇒ 条目数就是"
            "「菜单树上挂了几个动作码」。落地值 = 5（新增员工 / 订单详情 / 企业基础设置（经营域） / "
            "加工单操作 / 入库单操作；末两条 = issue #6759 的手机端写码，本次由 4 显式抬到 5）。"
        ),
    },
    {
        "id": "MENU_CODE_MISMATCHES",
        "count": lambda: len(MENU_CODE_MISMATCHES),
        "ceiling": 1,
        "grew_by": "`menu_column_problems`（『未登记即红』+『两侧已一致 ⇒ 销账』双向）",
        "reason": (
            "『页面节点上码列 ≠ 该页 `gate`』的具名不一致：P4 的目标形态是**零**，上界 = 1 是"
            "**存量余量**（不是许可额）。落地时现取 = 0 ⇒ 任何新不一致都要具名 + 理由才可能绿。"
        ),
    },
    {
        "id": "ROUTE_PREFIX_EXCEPTIONS",
        "count": lambda: len(ROUTE_PREFIX_EXCEPTIONS),
        "ceiling": 7,
        "grew_by": "`route_guard_problems`（『既不是某页 `path`、也没有别名 / 例外登记 ⇒ 新增页面守卫必须先登记』具名报出）",
        "reason": (
            "C4 面里**不以页面 `path` 出现**的前缀（入口在别的页面里 / 旧深链兼容 / 子树父前缀）："
            "逐条具名 + 理由，只许缩短。落地值 = 7。"
        ),
    },
    {
        "id": "ROUTE_PREFIX_ALIASES",
        "count": lambda: len(ROUTE_PREFIX_ALIASES),
        "ceiling": 1,
        "grew_by": "`route_guard_problems`（别名目标必须仍解析成同码；该前缀已变成某页 `path` ⇒ 销账即红）",
        "reason": (
            "「同一页的第二前缀」只许一条（`/processing` → `/production/processing`）；多一条就意味着"
            "有页面被拆成了两个入口 —— 那必须改成真的页面 / 真的例外。落地值 = 1。"
        ),
    },
    {
        "id": "ROUTE_GUARD_GATE_MISMATCHES",
        "count": lambda: len(ROUTE_GUARD_GATE_MISMATCHES),
        "ceiling": 1,
        "grew_by": "`route_guard_problems`（『未登记即红』+『两侧同码 ⇒ 删掉这条登记』双向）",
        "reason": (
            "页面存在、但守卫码 ≠ 该页 `gate` 的前缀：P4 的目标形态是**零**，上界 = 1 是存量余量。"
            "落地时现取 = 0。"
        ),
    },
    {
        "id": "NON_DERIVED_FACES",
        "count": lambda: len(NON_DERIVED_FACES),
        "ceiling": 1,
        "grew_by": None,
        "reason": (
            "**不由 `pages[]` 派生**的面（C2 的 `MENU_TREE` 码列）：**纯声明面** —— 没有独立的现取侧"
            "（面本身不在任何解析器的读数里）⇒ 本上界就是唯一的闸；要加一条必须显式改本表。落地值 = 1。"
        ),
    },
    {
        "id": "UNCOVERED_FACES",
        "count": lambda: len(UNCOVERED_FACES),
        "ceiling": 5,
        "grew_by": None,
        "reason": (
            "**未覆盖面**（照实验登记，不假装覆盖）：同上，**纯声明面**。落地值 = 5。"
        ),
    },
    {
        "id": "MULTI_READ_ENDPOINT_PAGES",
        "count": lambda: len(derived_faces()["multi_code_pages"]),
        "ceiling": 0,
        "grew_by": "`test_multi_code_pages_and_residuals_are_not_flattened`（派生 vs 现值冻结**逐值**比 + 具名报出是哪一页）",
        "reason": (
            "P4 的目标形态：**每页恰好一个码** ⇒ 多码页现取必须为 0；又长回来必须在同一个 PR 里具名登记"
            "并说明为什么这页真的多码（禁止悄悄变大）。"
        ),
    },
    {
        "id": "MENU_READ_PARITY_RESIDUALS",
        "count": lambda: len(derived_faces()["parity_residual_pages"]),
        "ceiling": 0,
        "grew_by": "`test_multi_code_pages_and_residuals_are_not_flattened`（同上，残留集逐值比）",
        "reason": (
            "同上：节点码 ≠ 页面读码的残留集现取必须为 0（issue #6580 后每个子菜单恰好一个码）。"
        ),
    },
)

#: **散文 / 字符串字面量里对「当前状态」的条数读数**：(读数 id, 锚)。
#: 锚 = **全文件唯一**的正则（**恰好一个**捕获组）；读数 id 必须能在 `present_readings()` 里取到值。
#: 🔴 **为什么不干脆把数字删掉**：复核者读的就是这句话里的数字（`migao-dev-flow` §19.1「转述即未核实」
#: 的同族，本单就是这么发现的）—— 数字留着、但**必须与现取逐值相等**，这才既让读者看到读数、
#: 又让漂移当场红（并报出「写的是几 / 现取是几」）。
PROSE_READINGS: tuple[tuple[str, str], ...] = (
    # 模块 docstring：各投影面的现取条数（P3 的三件事 / 覆盖面）
    ("anchors", r"`MENU_READ_ENDPOINT_ANCHORS` 的 (\d+) 条「页面 → 第一屏调用」"),
    ("pages", r"\*\*新进清单\*\*） \| (\d+) 页"),
    ("menu_node_codes", r"`menu_node_codes`（(\d+) 节点）"),
    ("auth_menu_codes", r"`auth_menu_codes`（(\d+) 条）"),
    ("route_guard_prefixes", r"`parse_route_guard`（(\d+) 条前缀）"),
    ("multi_code_pages", r"`MULTI_READ_ENDPOINT_PAGES`（(\d+)）"),
    ("parity_residual_pages", r"`MENU_READ_PARITY_RESIDUALS`（(\d+)）"),
    ("visibility_all", r"现取 = `all` \*\*(\d+)\*\* 页"),
    ("visibility_any", r"/ `any` \*\*(\d+)\*\* 页"),
    ("visibility_node_code", r"`node-code` \*\*(\d+)\*\* 页"),
    ("action_nodes", r"不由 `pages\[\]` 派生\*\*：它有 (\d+) 个\*\*动作节点\*\*"),
    ("role_names", r"\*\*岗位全集 = 种子 ∪ 回退\*\*（(\d+) 个）"),
    # 覆盖面台账里的读数（`NON_DERIVED_FACES` / `UNCOVERED_FACES`）
    ("menu_controller_codes", r"`MENU_TREE` 码列（(\d+) 条）"),
    ("action_nodes", r"它有 (\d+) 个\*\*动作节点\*\*（新增员工"),
    ("role_names", r"现取只有\*\*种子 ∪ 回退\*\*（(\d+) 个）"),
    # 台账注释里的「当前条数」声明
    ("menu_code_mismatches", r"具名不一致（只许缩短；\*\*P4 后 (\d+) 条\*\*）"),
    ("route_guard_gate_mismatches", r"逐条具名（只许缩短；\*\*P4 后 (\d+) 条\*\*）"),
    # 判据 docstring / C5 段的读数
    ("menu_controller_codes", r"C2 只有 \*\*(\d+)\*\* 个节点"),
    ("auth_menu_codes", r"C3 只有 \*\*(\d+)\*\* 个"),
    ("page_visibility_gaps_ceiling", r"LEDGER_CEILINGS\['PAGE_VISIBILITY_GAPS'\] == (\d+)"),
    ("gate_free_pages", r"声明该页 `gate` 为空的页（现取 (\d+) 条：`/notifications`"),
)

#: **沿革 / 结构叙事里的历史数字**（`X → Y` 形态，或对**当时**形态的引用）—— **不是**当前读数
#: ⇒ 允许写死，但**锚必须仍逐字在文本里**（只许缩短：条目对应的句子被删掉 ⇒ 红）。
NARRATIVE_NUMBERS: tuple[dict, ...] = (
    {
        "anchor": "仓里有 **4 份手写副本**",
        "reason": (
            "结构叙事：设计 §1.3 的 C 类四份副本（`menu.ts` / `MenuController` / `AuthService` / "
            "本判据锚点表）；其真实性由 M1 形态面登记（`rbac/sources.json`）承担，不由这个数字承担。"
        ),
    },
    {
        "anchor": "同 issue #5977 的 4 条那次",
        "reason": "沿革：#5977 当次新登记的前缀数（当时读数）。当前条数由 `ROUTE_PREFIX_EXCEPTIONS` 的现取复算负责。",
    },
    {
        "anchor": "4 条 **→ 1 条** ——",
        "reason": "沿革：issue #5699（P4）前后 gap 台账的形态变化；当前条数由 `VISIBILITY_GAP_REASONS` 的现取复算负责。",
    },
)


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


@functools.lru_cache(maxsize=1)
def present_readings() -> dict[str, int]:
    """本文件**所有条数读数的唯一取数口径** —— 每一次都**当场现取**（issue #6771）。

    输入 = 清单 / 派生器（`rbac/derive.py`）/ P1 守卫 / 既有解析器（**不新造第二套读数**）；
    输出 = 「读数 id → 条数」。`PROSE_READINGS` 与各判据的打印**只许**引用这里的 id
    （`prose_reading_problems` 会自证：登记的 id 都取得到值）。
    """
    manifest, derived, present = load_manifest(), derived_faces(), present_faces()
    p1, parity = load_manifest_guard(), load_parity_guard()
    derive = load_derive()
    node_gates = dict(derived["menu_node_codes"])
    action_nodes = {
        name
        for column in (present["menu_controller_codes"], present["auth_menu_codes"])
        for name in column
        if name not in node_gates
    }
    entries = dict(present["route_guard"])
    page_gates = dict(derived["route_guard_codes"])
    by_rule: dict[str, int] = {}
    for entry in derived["visibility"].values():
        by_rule[entry["rule"]] = by_rule.get(entry["rule"], 0) + 1
    leaf_counts = {face: len(leaves({face: derived[face]})) for face in RECONCILED_FACES}
    routes = dashboard_page_routes()
    readings = {
        "pages": len(manifest["pages"]),
        "menu_node_codes": len(derived["menu_node_codes"]),
        "menu_controller_codes": len(present["menu_controller_codes"]),
        "auth_menu_codes": len(present["auth_menu_codes"]),
        "action_nodes": len(action_nodes),
        "action_node_ledger": len(ACTION_NODE_CODES),
        "route_guard_prefixes": len(entries),
        "route_guard_codes": len(page_gates),
        "C4_direct": len([p for p in entries if p in page_gates]),
        "C4_alias": len(
            [p for p in entries if p not in page_gates and p in ROUTE_PREFIX_ALIASES]
        ),
        "C4_unmapped": len(
            [p for p in entries if p not in page_gates and p not in ROUTE_PREFIX_ALIASES]
        ),
        "first_screen_codes": len(derived["first_screen_codes"]),
        "units": len(derived["units"]),
        "multi_code_pages": len(derived["multi_code_pages"]),
        "parity_residual_pages": len(derived["parity_residual_pages"]),
        "visibility_pages": len(derived["visibility"]),
        "visibility_all": by_rule.get(derive.VISIBILITY_ALL, 0),
        "visibility_any": by_rule.get(derive.VISIBILITY_ANY, 0),
        "visibility_node_code": by_rule.get(derive.VISIBILITY_NODE_CODE, 0),
        "visibility_gap_reasons": len(VISIBILITY_GAP_REASONS),
        "menu_code_mismatches": len(MENU_CODE_MISMATCHES),
        "route_guard_gate_mismatches": len(ROUTE_GUARD_GATE_MISMATCHES),
        "route_prefix_exceptions": len(ROUTE_PREFIX_EXCEPTIONS),
        "route_prefix_aliases": len(ROUTE_PREFIX_ALIASES),
        "non_derived_faces": len(NON_DERIVED_FACES),
        "uncovered_faces": len(UNCOVERED_FACES),
        "role_names": len(manifest["roles"]["seed"]),
        "anchors": len(parity.MENU_READ_ENDPOINT_ANCHORS),
        "gate_free_pages": len([p for p in present["pages"] if not p["gate"]]),
        "dashboard_routes": len(routes),
        "guarded_dashboard_routes": len(
            [r for r in routes if effective_guard_code(r, guard_entries(present))]
        ),
        "page_visibility_gaps_ceiling": int(p1.LEDGER_CEILINGS["PAGE_VISIBILITY_GAPS"]),
        **{f"leaves_{face}": count for face, count in leaf_counts.items()},
        "leaves_total": sum(leaf_counts.values()),
    }
    # 自证（读数不许两边各说一套）：清单页数 == 现值页数；岗位全集 = 种子 ∪ 回退（两侧逐值同规模）
    assert readings["pages"] == len(present["pages"]), (
        f"清单 `pages[]` = {readings['pages']} / 现值 = {len(present['pages'])} ⇒ 读数自证失败（fail-closed）"
    )
    assert readings["role_names"] == len(manifest["roles"]["fallback"]), (
        "岗位全集 = 种子 ∪ 回退：两侧岗位数不等 ⇒ 读数自证失败（fail-closed）"
    )
    return readings


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

    ⚠️ **节点集不属本面**：C2 只有 **24** 个节点、C3 只有 **20** 个（登录菜单是页面的**子集**）——
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


# ══════════════════════════════════════════════════════════════════════════════
# C5 面：**菜单码 ⇒ 路由守卫覆盖**（issue #5976 / #5977 的类级元守卫）
# ══════════════════════════════════════════════════════════════════════════════
#
# 病（2026-10-02 多角色验收实测的两个同族缺陷）：`config/menu.ts` 的节点**有码**（菜单里隐藏），
# 而 `frontend/admin-web/src/app/(dashboard)/layout.tsx` 的 `ROUTE_PERMISSION_MAP` **覆盖不到它的
# 路由** ⇒ 地址栏直达**不被 403 拦截**、页面照常渲染（后端接口仍 403 ⇒ 不越权，但「看得见却做不了」）：
#   · #5976：`/inbound-orders`（菜单码 `inbound:view`，守卫表**根本没有这一项**）；
#   · #5977：`/agent-workspace/*`（守卫表只有 `/chat` → `agent:session`，覆盖不到该子树）。
#
# 🔴 **C4 抓不到这一形态**：C4 判的是**反方向**（守卫表的每个前缀 → 必须是某页的投影或具名例外）——
# 「菜单有码、守卫表里**没有这一项**」在 C4 里是**空集**（没有前缀可判）⇒ 必须补这一面才闭环。
#
# 判据两侧都**现取**、不另造解析器、不另开手写台账：
#   ① 节点码 + 节点路径 = 现取 `config/menu.ts`（经 `present_faces()['pages']`，P3 的同一份投影）；
#   ② 守卫表 = 现取 `layout.tsx` 的 `ROUTE_PERMISSION_MAP`（`parse_route_guard`，**保持源序**）。
# 豁免**派生**而非手写：某条页面路由**没有**守卫码 **iff** 单一真值源声明该页 `gate` 为空（全员可见）。


def guard_entries(present: dict) -> tuple[tuple[str, str], ...]:
    """现值守卫表（**保持源序**；`derive.page_present` 给的是 `[[prefix, code], …]`）。"""
    return tuple((str(p), str(c)) for p, c in present["route_guard"])


def effective_guard_code(route: str, guards) -> str | None:
    """`layout.tsx` 的**运行时**语义：**首个**前缀命中即短路（`find()`），**不是**最长匹配。

    逐字对齐渲染路径（`pathname.startsWith(r.prefix)` 的源序首个命中）—— 用最长匹配会与运行时
    给出不同答案，判据就失去意义（判据 11① 正是为「顺序会改变结果」而立）。
    """
    for prefix, code in guards:
        if route.startswith(prefix):
            return code
    return None


def dashboard_page_routes() -> list[str]:
    """`app/(dashboard)/**/page.tsx` → 路由路径（**动态段原样保留**：`startsWith` 语义下等价）。

    路由组名 `(dashboard)` 不进 URL ⇒ 取相对该目录的路径；该目录自身的 `page.tsx`（若有）= `/`。
    """
    root = load_parity_guard().DASHBOARD_APP
    assert root.is_dir(), f"页面目录不存在：{root}（路径漂移 ⇒ 红，不得静默扫空）"
    routes = []
    for page in sorted(root.rglob("page.tsx")):
        rel = page.parent.relative_to(root).as_posix()
        routes.append("/" if rel == "." else f"/{rel}")
    # 🔻 **下界**（防清空 / 防「扫空气」）：它是**与 `FROZEN_CEILINGS` 相对的那一类** ——
    # 写死并**写明理由**（不是放宽门禁：这个数字一字未动，见 `DASHBOARD_PAGE_ROUTES_FLOOR`）。
    # 它**只防清空**、**不防**「删掉任意一项」⇒ 由 `dashboard_route_coverage_problems`（**现取**的
    # ⊆ 判据，逐条具名）补上那一半。
    assert len(routes) >= DASHBOARD_PAGE_ROUTES_FLOOR, (
        f"只扫到 {len(routes)} 条页面路由（冻结下界 = {DASHBOARD_PAGE_ROUTES_FLOOR}）⇒ 判据在扫空气"
        "（路径漂移 / 目录改名会让它扫到零条而恒真通过）"
    )
    return routes


def dashboard_route_coverage_problems(routes: list[str]) -> list[str]:
    """**现取的 ⊆ 判据**（纯函数，可注入）：清单 `pages[]` 的每条页面都必须有对应的路由文件。

    这是下界（`DASHBOARD_PAGE_ROUTES_FLOOR`）补不上的那一半：下界只防「整片扫空」，
    本判据防「**删掉任意一项**」—— 且**逐条具名**报出缺的是哪一页。
    """
    pages = {str(page["path"]) for page in present_faces()["pages"]}
    return [
        f"在册页面 `{path}` 没有对应的路由文件 ⇒ 路由面缺页 / 清单与文件系统脱钩（fail-closed）"
        for path in sorted(pages - set(routes))
    ]


def menu_code_route_guard_problems(present: dict) -> list[str]:
    """C5①：**带 `permissionCode` 的每个菜单节点**，其 `path` 上的生效守卫码必须**逐字相等**。

    码为 `None`（守卫表没有覆盖它的前缀）或码不等 ⇒ **具名**报出 —— 这正是 #5976 / #5977 的形态。
    无码节点（如通知中心：全员可见）**不在本面**（它本就不该有守卫码）。
    """
    guards = guard_entries(present)
    out: list[str] = []
    for page in present["pages"]:
        gate = page["gate"]
        if not gate:
            continue
        code = effective_guard_code(str(page["path"]), guards)
        if code != str(gate):
            out.append(
                f"『{page['name']}』（`{page['path']}`）菜单码 = `{gate}`，而路由守卫给出的码 = "
                f"{code!r} ⇒ **菜单隐藏、地址栏直达不被拦**（`ROUTE_PERMISSION_MAP` 缺该前缀）"
            )
    return out


def unguarded_dashboard_routes(present: dict, manifest: dict) -> list[str]:
    """C5②：`app/(dashboard)/**` 的**每一条**页面路由都必须有生效守卫码。

    无守卫码时**只**接受一种情形（**派生豁免**，不另开台账）：单一真值源 `rbac/manifest.json` 的
    `pages[]` 里该 `path` 的 `gate` **显式为空**（= 该页全员可见）。其余一律具名 —— 含「清单里
    根本没有这一页」（= 新页面既没码也没守卫，静默直达，issue #5977 的 6/39 就是这么数出来的）。
    """
    guards = guard_entries(present)
    gates = {str(p["path"]): p["gate"] for p in manifest["pages"]}
    out: list[str] = []
    for route in dashboard_page_routes():
        if effective_guard_code(route, guards):
            continue
        if route in gates and not gates[route]:
            continue
        if route in gates:
            out.append(
                f"路由 `{route}` 没有任何守卫码，而单一真值源声明该页 `gate` = `{gates[route]}` "
                "⇒ 菜单按码隐藏、地址栏直达不被拦"
            )
        else:
            out.append(
                f"路由 `{route}` 既没有守卫码、也不在清单 `pages[]` 里 ⇒ 新增页面必须二选一："
                "进 `ROUTE_PERMISSION_MAP`（有码）或在清单里声明为无码页（全员可见）"
            )
    return out


def visibility_gap_pages(derived: dict | None = None, present: dict | None = None) -> list[str]:
    """**现取**的 gap 页：`visibility_rule` 的投影复现不了现值（现值要求 `node-code`）的页面。

    唯一一份口径 —— `visibility_problems` 与 `FROZEN_CEILINGS['PAGE_VISIBILITY_GAPS']` 都调它
    （否则同一个「gap 有几页」会有两份实现，正是本单要治的形态）。
    """
    derive = load_derive()
    derived = derived_faces() if derived is None else derived
    present = present_faces() if present is None else present
    return [
        path
        for path in sorted(set(derived["visibility"]) & set(present["visibility"]))
        if present["visibility"][path]["rule"] == derive.VISIBILITY_NODE_CODE
    ]


def visibility_problems(derived: dict, present: dict, manifest: dict) -> list[str]:
    """逐页可见性：**规则合法性 + 派生 == 现值要求 + gap 台账双向闭合 + 投影岗位集逐值**。"""
    derive = load_derive()
    out: list[str] = []
    derived_visibility = dict(derived["visibility"])
    present_visibility = dict(present["visibility"])
    gaps: list[str] = visibility_gap_pages(derived, present)
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


def frozen_ceiling_problems(entries: tuple[dict, ...] | None = None) -> list[str]:
    """**冻结上界台账**（`FROZEN_CEILINGS`）：现取 ≤ 上界 + 两处冻结逐值一致 + 每条把口径写清。

    纯函数（`entries` 可注入 ⇒ 红证在内存里构造坏形态、**不碰磁盘**）；**不改任何判定逻辑**：
    上界一律沿用落地值（本包只治读数漂移）。三条：
      ① **现取 > 上界 ⇒ 红**（具名 + 现取 / 上界读数 + 出口）；「真实集合增长而台账没更新」= **明确判红**；
      ② **上界与侧真值不一致 ⇒ 红**（两处冻结：谁被悄悄放宽了）；
      ③ **不许空转**：每条必须写清 `id` / `count` / `ceiling` / `grew_by` / `reason`（缺一 ⇒ 红）。
    """
    out: list[str] = []
    for entry in FROZEN_CEILINGS if entries is None else entries:
        missing = [k for k in ("id", "count", "ceiling", "grew_by", "reason") if k not in entry]
        name = entry.get("id", "<缺 id>")
        if missing:
            out.append(
                f"冻结上界条目 `{name}` 缺字段 {missing}"
                "（id / 现取 / 上界 / 增长时谁具名红 / 理由 缺一即红 —— 缺 `grew_by` 就是「悄悄变大」）"
            )
            continue
        count, ceiling = int(entry["count"]()), int(entry["ceiling"])
        if entry.get("ceiling_from") is not None:
            side = int(entry["ceiling_from"]())
            if side != ceiling:
                out.append(
                    f"冻结上界 `{name}`：侧真值 `{entry.get('ceiling_from_where', '?')}` = {side} ≠ 本表 = {ceiling}"
                    " ⇒ **上界被悄悄放宽**（两处冻结必须逐值相等；要放宽就同 PR 改两处，diff 里看得见）"
                )
        if count > ceiling:
            oracle = entry["grew_by"] or "**本上界自身**（纯声明面：没有独立的现取侧）"
            out.append(
                f"冻结上界 `{name}`：**现取 = {count} > 上界 = {ceiling}**（只许缩短）——"
                "「真实集合增长而台账没更新」在本条的口径 = **明确判红**（不是自动接受）。"
                f"谁具名报出：{oracle}。出口：① 修小（首选）；② 若增长是有意的，同 PR 改本表 `{name}` 的"
                "`ceiling`（diff 里看得见）并在 `reason` 里补一句为什么。"
                f"这个数字为什么只能写死：{entry['reason']}"
            )
    return out


def prose_reading_problems(text: str | None = None) -> list[str]:
    """**散文 / 字面量里的条数读数 vs 现取**（issue #6771 的正题）—— 纯函数（`text` 可注入）。

    四段（缺任何一段就有漏网形态）：
      ① **登记项逐条复算**：锚必须在文本里**恰好命中一次**（0 = 锚被改写 / 删除 ⇒ 红；>1 = 锚不唯一 ⇒ 红），
         命中里的数字必须 == 现取（不等 ⇒ 红，报出「写的是几 / 现取是几」+ 行号）；
      ② **未登记即红**：按 `READING_SHAPES` 扫全文，凡「条数读数写法」命中而**既没登记、也不在
         `NARRATIVE_NUMBERS`（沿革 / 结构叙事）**⇒ 红（带行号 + 逐字命中 + 三条出口）；
      ③ **沿革台账不许陈旧**：`NARRATIVE_NUMBERS` 的锚必须仍逐字在文本里（只许缩短）；
      ④ **口径自证**：登记的 `id` 必须都能在 `present_readings()` 里取到值（否则「现取」是假的）。
    """
    body = THIS_FILE.read_text(encoding="utf-8") if text is None else text
    readings = present_readings()
    lines = body.splitlines()
    out: list[str] = []
    covered: list[tuple[int, int]] = []
    for rid, pattern in PROSE_READINGS:
        if rid not in readings:
            out.append(f"散文读数 `{rid}` 不在 `present_readings()` 里 ⇒ 这条登记取不到现取值（假现取）")
            continue
        found = list(re.finditer(pattern, body))
        if len(found) != 1:
            out.append(
                f"散文读数 `{rid}` 的锚命中 {len(found)} 次（必须**恰好一次**）⇒ 锚被改写 / 删除 / 不唯一"
                f"（锚 = {pattern!r}）—— 出口：把锚改回逐字形态，或同步改 `PROSE_READINGS` 的这一行"
            )
            continue
        match = found[0]
        covered.append(match.span())
        written = int(match.group(1))
        if written != readings[rid]:
            line_no = body[: match.start()].count("\n") + 1
            out.append(
                f"散文读数 `{rid}` **漂了**：第 {line_no} 行写的是 `{written}` / **现取**是 `{readings[rid]}`"
                f"（锚 = {pattern!r}）⇒ 数字必须由现取复算得到。出口：把该处字面量改成现取值，"
                "或在打印处以现取值插值（`present_readings()` 是唯一取数口径）"
            )
    allowed = tuple(entry["anchor"] for entry in NARRATIVE_NUMBERS)
    for entry in NARRATIVE_NUMBERS:
        if not entry.get("reason"):
            out.append(f"沿革台账条目缺 `reason`：{entry['anchor']!r}（写死了就必须写清为什么）")
        if entry["anchor"] not in body:
            out.append(
                f"沿革台账 `NARRATIVE_NUMBERS` 的锚已不在文本里：{entry['anchor']!r} ⇒ 销账（只许缩短）；"
                f"原理由：{entry.get('reason', '')}"
            )
    for shape in READING_SHAPES:
        for match in shape.finditer(body):
            if any(lo <= match.start() and match.end() <= hi for lo, hi in covered):
                continue
            line_no = body[: match.start()].count("\n") + 1
            line = lines[line_no - 1].strip()
            if any(anchor in line for anchor in allowed):
                continue
            out.append(
                f"第 {line_no} 行出现**未登记的条数读数** `{match.group(0)}`（{line}）⇒ 未登记即红："
                "对**当前状态**的读数要进 `PROSE_READINGS`（判据会逐条现取复算）；沿革 / 结构叙事要进"
                "`NARRATIVE_NUMBERS`（带理由）；也可以直接删掉这个数字（改成引用打印的现取读数）"
            )
    return out


def coverage_problems() -> list[str]:
    """覆盖面与**只许缩短**的机械形态：**冻结上界台账**（现取 + 上界 + 增长时谁具名红）+ 每条写清「覆盖不到什么、谁看」。"""
    p1, derive = load_manifest_guard(), load_derive()
    manifest = load_manifest()
    out: list[str] = []
    out += frozen_ceiling_problems()
    # 清单 `ledger_counts` 的口径（P1 守卫那份：上限登记 + 清单 <= 上限）—— 与 `FROZEN_CEILINGS`
    # 的现取复算**互补**：前者判「清单里那份读数」，后者判「真值侧现取」。两者都只许缩短。
    for name in sorted(set(p1.LEDGER_CEILINGS) & {entry["id"] for entry in FROZEN_CEILINGS}):
        if manifest["ledger_counts"].get(name, 0) > p1.LEDGER_CEILINGS[name]:
            out.append(f"台账 {name} 现取条数 > 上限（只许缩短）")
    if "pages" not in p1.RECONCILED_SEGMENTS:
        out.append(
            "P1 守卫的 `RECONCILED_SEGMENTS` 里没有 `pages` ⇒ 新段逃出了「清单 == 生成物」的对账"
            "（那正是新造并行真值的形态）"
        )
    # 规则集规模：`3` 由**命名常量**现取而来（口径与原实现逐字等价，只是不再写死一个数字）
    expected_rules = {derive.VISIBILITY_ALL, derive.VISIBILITY_ANY, derive.VISIBILITY_NODE_CODE}
    if len(derive.VISIBILITY_RULES) != len(expected_rules):
        out.append(
            f"`VISIBILITY_RULES` = {derive.VISIBILITY_RULES}（逐页规则集被人改动：新规则要显式登记，"
            f"不许悄悄多出一种；现取口径 = 命名常量集 {sorted(expected_rules)}）"
        )
    if derive.DEFAULT_VISIBILITY_RULE != derive.VISIBILITY_ALL:
        out.append(
            f"默认规则 = {derive.DEFAULT_VISIBILITY_RULE!r} ≠ {derive.VISIBILITY_ALL!r}"
            " ⇒ 默认不再是 fail-closed（设计 §3.4 问题 3 末注）"
        )
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
    """**P3 主判据之二（零 delta）**：各投影面的派生结果与现值**逐值相等**，逐项点名 + 口径读数。

    🔴 打印里的每个条数都由 `present_readings()` **现取插值**（issue #6771：写死的读数会漂，
    而漂了没有东西会红）—— 本打印**不许**再出现字面量条数。
    """
    derived, present = derived_faces(), present_faces()
    counted = 0
    for face in RECONCILED_FACES:
        for key, value in leaves({face: derived[face]}):
            counted += 1
            print(f"  {key} = {value!r}")
    r = present_readings()
    assert counted == r["leaves_total"], (
        f"逐项点名的项数 {counted} ≠ 现取摊平项数 {r['leaves_total']} ⇒ 打印与判据读的不是同一份数据"
    )
    print(
        f"── P3 逐值比对项数 = {counted}（**口径**：六个投影面摊平到叶的 `(路径, 值)` 对总数 ——"
        f"C1 按「节点 → 码」逐节点一项（{r['leaves_menu_node_codes']}）、"
        f"第一屏码按「页 → 逐码」展开（{r['leaves_first_screen_codes']}）、"
        f"units 按「页 → 码 → 逐端点」展开（{r['leaves_units']}）、"
        f"多码页 {r['leaves_multi_code_pages']} 项、残留页 {r['leaves_parity_residual_pages']} 项、"
        f"可见性按「页 → 规则 + 岗位集」逐页一项（{r['leaves_visibility']}）。"
        "**另有两条不走摊平的面**：C4 按前缀逐条比"
        f"（{r['route_guard_prefixes']} = {r['C4_direct']} 直接命中 + {r['C4_alias']} 别名 + "
        f"{r['C4_unmapped']} 无页面 —— 末一族是 issue #5977 登记的 `/agent-workspace` 同款），"
        f"C2/C3 的码列逐条比（{r['menu_controller_codes']} + {r['auth_menu_codes']} = "
        f"{r['menu_controller_codes'] + r['auth_menu_codes']}，含 {r['action_nodes']} 个**动作节点**与 "
        f"{r['menu_code_mismatches']} 处具名不一致）⇒ 全部逐项点名，**不一致 = 0**）──"
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
    """**多端点页与残留页不被压平**（#5675 / #5682 的结构事实）：派生集 == 现取，逐值。

    🔴 **issue #5699（P4）**：多码页 3 → 1（`/settings`，具名保留）；残留页 6 → 1。
    🔴 **2026-10-09（issue #6580）**：`/settings` 的锚点口径收窄（只收本页自身 effect 驱动面；
    经营域面板按各自码条件挂载）⇒ 该页成为**单码页**，两侧**都清空**（P4 的目标形态：每个子菜单
    恰好一个码）。两半判据（未登记即红 / 陈旧亦红）一字未动，另由 `test_flattening_a_page_is_red`
    与 `test_residual_ledger_only_shrinks` 用**内存合成**的坏形态继续压。
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
    # 🔴 2026-10-09（issue #6580）：冻结上界 1 → **0**（P4 的目标形态达成：每个子菜单恰好一个码）。
    # 判据方向不变（**只许缩短**）：多码页 / 残留页**又长回来** ⇒ 当场红，必须在同一个 PR 里
    # 具名登记进 `MULTI_READ_ENDPOINT_PAGES` / `MENU_READ_PARITY_RESIDUALS`，并改
    # `FROZEN_CEILINGS` 的对应上界 + 说明为什么这页真的多码（**禁止悄悄变大**）。
    caps = {entry["id"]: entry for entry in FROZEN_CEILINGS}
    multi_cap = caps["MULTI_READ_ENDPOINT_PAGES"]["ceiling"]
    residual_cap = caps["MENU_READ_PARITY_RESIDUALS"]["ceiling"]
    if len(multi) != multi_cap or len(residuals) != residual_cap:
        problems.append(
            f"结构性条数漂移：多码页 {len(multi)}（冻结上界 = {multi_cap} —— issue #6580 后每页恰好一个码，"
            f"只许缩短）/ 残留页 {len(residuals)}（冻结上界 = {residual_cap}）"
            " ⇒ 谁长出来了见上面逐条报出；出口 = 修小，或同 PR 改 `FROZEN_CEILINGS` 的对应上界并说明理由"
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


def test_frozen_ceilings_are_explicit_and_load_bearing():
    """**冻结上界台账**（`FROZEN_CEILINGS`）可归因 + 会红：落地态不超界 / 三种坏形态当场判红（内存）。

    口径（issue #6771 要求写清的那一条）：**「真实集合增长而台账没更新」= 明确判红**，不是自动接受
    —— 每条上界的 `grew_by` 逐字写明由哪个判据**具名**报出是哪些条目。
    """
    problems = frozen_ceiling_problems()
    assert problems == [], "冻结上界台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)
    ids = [entry["id"] for entry in FROZEN_CEILINGS]
    assert len(ids) == len(set(ids)), f"冻结上界的 id 必须唯一（否则判红归因不到具体哪一个）：{ids}"
    pure = ("NON_DERIVED_FACES", "UNCOVERED_FACES")
    assert all(entry["grew_by"] or entry["id"] in pure for entry in FROZEN_CEILINGS), (
        "只有**纯声明面**（无独立现取侧）才允许 `grew_by = None`，且必须在 `reason` 里如实登记 —— "
        "其余每一条都要写清「增长时谁具名红」（缺了它就是「悄悄变大」）"
    )

    # ① 现取 > 上界 ⇒ **具名红**（内存合成：把某条上界压到现取之下 =「真实集合长出来了」的等价形态）
    squeezed = []
    for entry in FROZEN_CEILINGS:
        if entry["id"] != "ACTION_NODE_CODES":
            squeezed.append(entry)
            continue
        bad = {k: v for k, v in entry.items() if k != "ceiling_from"}
        bad["ceiling"] = entry["count"]() - 1
        squeezed.append(bad)
    hits = frozen_ceiling_problems(tuple(squeezed))
    assert any("ACTION_NODE_CODES" in h and "明确判红" in h for h in hits), (
        f"现取 > 上界没有被具名报出 ⇒ 冻结上界是空断言：{hits}"
    )

    # ② 上界被悄悄放宽 ⇒ 红（两处冻结：本表 vs 侧真值）
    widened = tuple(
        {**entry, "ceiling": entry["ceiling"] + 1} if entry["id"] == "PAGE_VISIBILITY_GAPS" else entry
        for entry in FROZEN_CEILINGS
    )
    hits = frozen_ceiling_problems(widened)
    assert any("悄悄放宽" in h for h in hits), f"上界被放宽而侧真值没变 ⇒ 没报出：{hits}"

    # ③ **真实集合**（内存里真的长出一位）⇒ 红 + 具名；还原 ⇒ 必绿（对照臂）
    grown_to = len(ACTION_NODE_CODES) + 1
    original = dict(ACTION_NODE_CODES)
    try:
        ACTION_NODE_CODES["合成的动作节点"] = {
            "code": "synthetic:act",
            "reason": "红证用（内存合成，不碰磁盘）",
            "owner": "本判据的冻结上界红证",
        }
        hits = frozen_ceiling_problems()
    finally:
        ACTION_NODE_CODES.clear()
        ACTION_NODE_CODES.update(original)
    assert any("ACTION_NODE_CODES" in h and f"现取 = {grown_to}" in h for h in hits), (
        f"真实集合长出一位后冻结上界没判红 ⇒「增长而台账没更新」是空断言：{hits}"
    )
    assert frozen_ceiling_problems() == [], "还原后必须绿（红证的对照臂）"


def test_prose_readings_match_present_values():
    """**散文 / 打印里的条数读数 vs 现取**（issue #6771 的正题）：落地态全绿 + 五种坏形态当场红。

    判据本身是纯函数（文本可注入）；本用例的注入**全部在内存文本**上做（不改磁盘）。
    """
    readings = present_readings()
    problems = prose_reading_problems()
    assert problems == [], (
        "散文读数与现取不一致（**这就是本单要治的形态**）：\n" + "\n".join(f"  · {p}" for p in problems)
    )
    print(
        f"── 现取读数 = {len(readings)} 项 / 登记散文读数 = {len(PROSE_READINGS)} 项 / "
        f"沿革台账 = {len(NARRATIVE_NUMBERS)} 项 ──"
    )
    for rid in sorted({rid for rid, _ in PROSE_READINGS}):
        print(f"  {rid} = {readings[rid]}")

    body = THIS_FILE.read_text(encoding="utf-8")
    rid, pattern = PROSE_READINGS[0]
    hits_before = list(re.finditer(pattern, body))
    assert len(hits_before) == 1, (
        f"登记项 `{rid}` 的锚在本文件里命中 {len(hits_before)} 次（必须恰好一次）⇒ 红证前提不成立"
    )
    anchor = hits_before[0]

    # ① 把散文里的数字**就地改错** ⇒ 必须具名红，并报出「写的是几 / 现取是几」
    wrong = (
        body[: anchor.start()]
        + anchor.group(0).replace(str(readings[rid]), str(readings[rid] + 1))
        + body[anchor.end():]
    )
    assert wrong != body, "变异注入未生效（自证失败）"
    hits = prose_reading_problems(wrong)
    assert any(rid in h and "漂了" in h for h in hits), f"改错一个读数后没报出 ⇒ 空断言：{hits}"

    # ② 锚被改写 / 删除 ⇒ 红（命中 0 次）
    erased = body[: anchor.start()] + "（这段读数被改写了，锚不再逐字命中）" + body[anchor.end():]
    hits = prose_reading_problems(erased)
    assert any("恰好一次" in h for h in hits), f"锚被改写后没报出 ⇒「锚是承载体」是空话：{hits}"

    # ③ 锚不唯一 ⇒ 红（同一句读数被复制到第二处）
    doubled = body + "\n#: 对照臂：" + anchor.group(0) + "\n"
    hits = prose_reading_problems(doubled)
    assert any(rid in h and "命中 2 次" in h for h in hits), f"锚不唯一没报出：{hits}"

    # ④ **未登记即红**：塞一句新的写死读数（数字拆开拼，免得本判据被自己扫成未登记读数）
    injected = body + "\n#: 合成的未登记读数：共 " + "99" + " 条（红证用）\n"
    hits = prose_reading_problems(injected)
    assert any("未登记的条数读数" in h and "99" in h for h in hits), (
        f"未登记的写死读数没报出 ⇒「未登记即红」是空断言：{hits}"
    )

    # ⑤ 沿革台账陈旧 ⇒ 红（锚对应的句子被删了 ⇒ 只许缩短）
    stale = body.replace(NARRATIVE_NUMBERS[0]["anchor"], "（这段沿革被删了）")
    assert stale != body, "沿革锚的删除变异未生效（自证失败）"
    hits = prose_reading_problems(stale)
    assert any("只许缩短" in h for h in hits), f"沿革锚被删后没报出：{hits}"

    # 对照读数：只改**与读数无关**的散文 ⇒ 不红（判据判的是读数，不是「文件变了没有」）
    control = body.replace("## 数字纪律", "## 数字纪律（对照臂）", 1)
    assert control != body, "对照变异未生效（自证失败）"
    assert prose_reading_problems(control) == [], "只改无关散文竟然红了 ⇒ 判据在扫错东西"


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
    """**一页多码 / 单码的派生面是现算的**（两条分支各单独判一次）。

    🔴 issue #5699（P4）：夹具曾是 `/production/processing` → `/settings`（当时唯一的多码页）。
    🔴 **2026-10-09（issue #6580）夹具再次改判**（如实登记）：锚点口径收窄后（只收**本页自身
    effect 驱动面**；经营域面板按各自码条件挂载）**真树已无多码页** ⇒ 继续拿真页当夹具会变成
    空断言。改为**内存合成**：给一个单码页塞第二个码 ⇒ 派生面必须当场把它读成多码页并报红
    （这正是本判据要保住的那条判别力：「一页多码」这个事实由现取算出，不是手写台账说了算）。
    """
    derive, manifest, present = load_derive(), load_manifest(), present_faces()
    assert face_problems(derive.derive_page_faces(manifest), present) == [], "落地态竟不绿（前提不成立）"
    assert derive.derive_page_faces(manifest)["multi_code_pages"] == {}, (
        "落地态应**没有**多码页（每页恰好一个码 = P4 的目标形态）"
    )

    widened = _mutate_page(
        manifest, "/production/piecework",
        units={
            "production:view": ["GET /api/admin/production/piecework/summary"],
            "processing:manage": ["GET /api/admin/production/pool/preview"],
        },
    )
    faces = derive.derive_page_faces(widened)
    problems = face_problems(faces, present)
    assert any("multi_code_pages" in p for p in problems), f"合成出的多码页没被报出：{problems}"
    assert "/production/piecework" in faces["multi_code_pages"], (
        "合成第二个码后该页未被读成多码页 ⇒ `multi_code_pages` 不是现算的"
    )

    renamed = _mutate_page(manifest, "/settings", gate="dashboard:view")
    route_problems = route_guard_problems(derive.derive_page_faces(renamed), present)
    assert any("/settings" in p for p in route_problems), f"改某页 gate 后 C4 没报出：{route_problems}"


def test_residual_ledger_only_shrinks():
    """残留台账**只许缩短**：修好一处而不销账 ⇒ 红；新增一处未登记 ⇒ 红。"""
    derive, present, parity = load_derive(), present_faces(), load_parity_guard()
    manifest = load_manifest()
    # 🔴 issue #5699（P4）→ **2026-10-09（issue #6580）夹具再改判**（如实登记）：锚点口径收窄后
    # 真树**已无残留页**（每个子菜单恰好一个码 = P4 的目标形态）⇒ 夹具改为两半：
    #   ① 真集必须为空，且与现值台账**逐值相等**（锁住这个结果：谁加一条都要同批解释为什么这页真的多码）；
    #   ② **内存合成**一处新的不一致 ⇒ 派生残留集必须当场长出它（证明残留集是现算的）。
    # 不合成 = 第 ② 半永远是空断言（同本文件其余红证夹具的做法）。
    residuals = derive.derive_page_faces(manifest)["parity_residual_pages"]
    assert residuals == [], f"落地态应没有残留页（每个子菜单恰好一个码）—— 实得 {residuals}"
    assert sorted(residuals) == sorted(parity.MENU_READ_PARITY_RESIDUALS), (
        "派生残留集与现值台账必须逐值相等（两侧都应为空）—— 不等 ⇒ 本判据读的不是现算的残留集"
    )
    broken = _mutate_page(manifest, "/production/remnants", gate="production:view")
    residuals2 = derive.derive_page_faces(broken)["parity_residual_pages"]
    assert "/production/remnants" in residuals2, "新增一处不一致后派生集没变 ⇒ 本判据空跑"
    assert sorted(residuals2) != sorted(parity.MENU_READ_PARITY_RESIDUALS), (
        "新增不一致后派生集仍与台账相等 ⇒ 陈旧台账分支没被验到"
    )
    # 并且必须**具名报出**（否则「未登记即红」只是集合比较，读不出是谁）
    reported = face_problems(derive.derive_page_faces(broken), present)
    assert any("parity_residual_pages" in p and "/production/remnants" in p for p in reported), (
        f"合成的新残留页没有被具名报出 ⇒ 未登记分支判别力不足：{reported}"
    )


def test_visibility_rule_relaxation_is_red():
    """把某页的规则改成 `any`（放宽）或删掉字段 ⇒ 逐页对账必红（现值要求 `all`）。"""
    derive, manifest, present = load_derive(), load_manifest(), present_faces()
    relaxed = _mutate_page(manifest, "/settings", visibility_rule="any")
    problems = visibility_problems(derive.derive_page_faces(relaxed), present, relaxed)
    assert any("visibility./settings.rule" in p for p in problems), f"放宽规则没被报出：{problems}"

    dropped = _mutate_page(manifest, "/production/piecework", visibility_rule=None)
    faces = derive.derive_page_faces(dropped)
    assert faces["visibility"]["/production/piecework"]["rule"] == derive.VISIBILITY_ALL, (
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
    mutated = _mutate_page(manifest, "/production/piecework", gate="processing:manage")
    base_faces = derive.derive_page_faces(manifest)
    mutated_faces = derive.derive_page_faces(mutated)
    assert base_faces["route_guard_codes"]["/production/piecework"] == "production:view"
    assert mutated_faces["route_guard_codes"]["/production/piecework"] == "processing:manage", (
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


# ══════════════════════════════════════════════════════════════════════════════
# C5 的两条判据（实例面 + 类级元守卫；红证 = 内存构造「把守卫摘掉」的对照臂）
# ══════════════════════════════════════════════════════════════════════════════


def test_every_menu_code_node_is_covered_by_the_route_guard():
    """🔴 **类级元守卫**：`config/menu.ts` 里**带 `permissionCode`** 的每个节点，路由守卫必须给**同一个码**。

    这是 #5976 / #5977 的**拦网**：只要「菜单有码、守卫表缺该前缀」再出现一次，本判据当场**具名**报出
    （C4 判不到这一形态 —— 见本文件 C5 面的注释）。判别力自证放在同一条用例里（内存构造，不碰仓内文件）。
    """
    present = present_faces()
    problems = menu_code_route_guard_problems(present)
    live = [p for p in present["pages"] if p["gate"]]
    print(f"── 带 permissionCode 的菜单节点 = {len(live)} 个 / 守卫码不一致 = {len(problems)} 项 ──")
    assert problems == [], (
        f"菜单码与路由守卫不一致（共 {len(problems)} 项）—— 菜单按码隐藏、地址栏直达不被拦：\n"
        + "\n".join(f"  · {p}" for p in problems)
        + "\n出口：把该页前缀补进 `frontend/admin-web/src/app/(dashboard)/layout.tsx` 的"
        " `ROUTE_PERMISSION_MAP`（码 = 菜单节点码）。"
    )

    mutated = copy.deepcopy(present)
    mutated["route_guard"] = [
        e for e in present["route_guard"] if str(e[0]) != "/inbound-orders"
    ]
    assert mutated["route_guard"] != present["route_guard"], "变异注入未生效（自证失败）"
    hits = menu_code_route_guard_problems(mutated)
    assert any("入库单" in h for h in hits), f"摘掉 `/inbound-orders` 守卫后没被判红：{hits}"


def test_every_dashboard_page_route_resolves_to_a_guard_code():
    """**实例面**：`app/(dashboard)/**` 的每条页面路由都必须有生效守卫码（issue #5977 的 6/39 判据）。

    唯一豁免 = 单一真值源 `rbac/manifest.json` 声明该页 `gate` 为空的页（现取 1 条：`/notifications`
    —— 菜单节点无码、读端点无 `@RequirePermission`，全员可见 ⇒ **不造码**、也不给它一个空守卫）。
    判别力自证：内存摘掉 `/agent-workspace` ⇒ 该子树未被覆盖的子路由必须具名报出。
    """
    present, manifest = present_faces(), load_manifest()
    problems = unguarded_dashboard_routes(present, manifest)
    routes = dashboard_page_routes()
    # **现取的 ⊆ 判据**（`DASHBOARD_PAGE_ROUTES_FLOOR` 那个下界补不上的那一半：防「删掉任意一项」）
    coverage = dashboard_route_coverage_problems(routes)
    assert coverage == [], "清单 `pages[]` 与路由文件面不一致：\n" + "\n".join(f"  · {p}" for p in coverage)
    guarded = sum(1 for r in routes if effective_guard_code(r, guard_entries(present)))
    print(
        f"── (dashboard) 页面路由 = {len(routes)} 条 / 有守卫码 = {guarded} 条 / 无守卫码 = {len(problems)} 条 ──"
    )
    assert problems == [], (
        f"`(dashboard)` 下有 {len(problems)} 条路由没有生效守卫码：\n"
        + "\n".join(f"  · {p}" for p in problems)
        + "\n出口：进 `ROUTE_PERMISSION_MAP`（有码页）或在 `rbac/manifest.json` 的 `pages[]` 里"
        "声明该页 `gate` 为空（全员可见页，须与菜单节点「无 permissionCode」一致）。"
    )

    # 判别力自证（内存）：摘掉**一条在册页面的路由** ⇒ ⊆ 判据必须具名报出是它
    victim = sorted(str(page["path"]) for page in present["pages"])[0]
    slashed = [r for r in routes if r != victim]
    assert slashed != routes, f"变异注入未生效（`{victim}` 不在扫描到的路由里 ⇒ 自证失败）"
    hits = dashboard_route_coverage_problems(slashed)
    assert any(victim in h for h in hits), f"摘掉一条在册页面的路由后没被判红：{hits}"

    mutated = copy.deepcopy(present)
    mutated["route_guard"] = [
        e for e in present["route_guard"] if str(e[0]) != "/agent-workspace"
    ]
    assert mutated["route_guard"] != present["route_guard"], "变异注入未生效（自证失败）"
    hits = unguarded_dashboard_routes(mutated, manifest)
    assert any("agent-workspace/sessions" in h for h in hits), (
        f"摘掉 `/agent-workspace` 守卫后没被判红：{hits}"
    )
