# case_ids: MC-035, MC-036, MC-037
"""RBAC 单一真值源 **P4：子菜单粒度**（跟踪单 issue #5699；设计真值源 `docs/design/rbac-single-source.md`）。

## 它判什么（三条不变量 + 两张台账）

用户的裁定（2026-09-27，逐字）：「**直接按目标改，权限粒度到子菜单即可，不需要细化到页面内功能**」
⇒ 权限单位 = **子菜单（侧边栏节点）**；页内功能 / 页签**不是**权限边界。本守卫把那句话变成三条
机器判据（P4 之前它们**都不存在**，是「靠人记得」）：

1. **每个子菜单 ↔ 恰好一个可见性码**：`pages[].gate` 非空，且该页第一屏的码集**恰好** = `{gate}`；
   「第一屏无任何码」的页（节点无码 ∧ 端点未注解）必须具名登记在 `FAIL_OPEN_PAGES`
   （两侧同一个**空码** ⇒ 结构上不可能「菜单看得见、点进去 403」）。第一屏**真的**并发多码的页
   必须具名在**既有**台账 `MENU_READ_PARITY_RESIDUALS`（判据 12 ③ 的只许缩短台账，本守卫**读它**
   而不另立一份 —— 同一事实两处登记 = 又一处并行真值）。
2. **看得见 ⇒ 打得开**（零 403 的角色集形态）：持 `gate` 的岗位必须同时持该页**每一个** unit 的码；
   多码页额外要求 `可见面投影 == 持 gate 者`（可见性仍由**那一个**码决定）。
3. **四个菜单/守卫面同码**：C1 前端侧边栏 / C2 权限目录树 / C3 登录下发菜单 / C4 路由守卫，逐页
   与 `pages[].gate` 逐值相等（跨面映射复用判据 11 的 `ROUTE_MENU_ANCHORS`，本守卫**不新建映射**）。

两张台账（都落在本文件里，各自「未登记即红 + 只许缩短 + 陈旧亦红」）：

- `P4_AUTHORIZATION_CENSUS`（设计 §4.1 的 **D1/D3**）：本次**变动的每一页**逐页记「改前的码 / 改后的码 /
  方向 / 理由」，外加**逐个变动端点**的 `(改前码, 改后码)`。判据拿它与**现值**对账，并**当场复算**
  「谁因此看得见 / 谁因此多出或少了可做面」（岗位来源 = 种子 ∪ 回退，与判据 12 ④ 同口径）。
  ⇒ 手写汇总（「25 个端点」写成「6」那种，见设计 §1.4 实例 5）在这里不可能存活。
- `WRITE_UNDER_READ_CODE`（设计 §3.4 问题 2 / #5699 的发现 ①，**不变量 I4**）：**端点层**的
  「写动作只由读码把守」逐条具名。判据 5 的射程只有**工具层** ⇒ 这一族今天**没有任何判据看得见**
  （现取问题数 0、例外台账 0 条）。I4 只**具名报出**，不改任何行为（改它是授权变更，须人类裁定）。

## 它复用什么（**不造第二套解析器**）

现值一律由既有解析器现取：`rbac/derive.py` 的 `load_manifest` / `derive_page_faces` /
`page_present` / `role_tables` / `code_holders` / `page_unit_codes` / `project_visibility` /
`effective_visibility_rule`；而 `derive.py` 自己只调
`tests/unit_ci_workflows/test_agent_permission_parity.py` 的既有函数。本文件**一行源码解析都没有**
（#3570 的教训：第二套解析器 = 第二个真值源）。

## 🔴 「子菜单粒度」管的是**读侧可见性**，**写动作仍由写码把守**（把这句话写清，防止被读成「读码可写」）

用户裁定的原文是「权限粒度到子菜单即可，**不需要细化到页面内功能**」—— 它消掉的是
**「同一个子菜单的读面被拆成多个码」**（页签 / 第一屏各读端点各挂一个码），
**不是**「页面内的写动作不再需要写码」。两者的区别是**可做面**与**可见面**：

- **可见面**：侧边栏节点码 = 该页第一屏读码（本守卫的三条不变量管的就是它）；
- **可做面**：写动作仍由**写码**把守（`POST /pool/dispatch` = `processing:update`、
  `PUT /operation-positions/{id}` = `processing:manage`、`POST /production/seed-templates/{id}/apply` 继承类级
  `processing:manage` …）。**P4 一个写端点的码都没改**（见下条的自证读数）。

⇒ 推论（**必须知道，否则会误判**）：一个岗位**可以**「看得见页面、读得到数据、点写按钮 403」——
这在 P4 之后**仍然存在**，且**不是** P4 引入的（`product_manager`@回退 的「智能派单 → 派单按钮」今天就是这样）。
要消掉它只有两条路，两条都**不在**本阶段射程：① 把写动作对齐到页面读码（= **放宽写面**，须人类裁定）；
② 在前端按写码隐藏/禁用写按钮（那是**页内 UI 动作**，不是权限边界 —— 裁定说页内功能不作边界，
但也不要求把写权限并进读码）。登记在 `UNCOVERED_FACES` 的「页内写动作的边界」一条。

**自证读数（两个方向的对照，实跑）**：把 `origin/main` 与 P4 分支各自解析一遍端点表 ⇒
**写端点（非 GET）165 → 165，码变化 0 条**；同一把尺子量读端点 ⇒ **恰好 7 条**生效码变化
（逐条 = 本 PR 的 `units_changed`）。**前者为 0 之所以可信，正是因为后者非 0**（阴性结果必须有阳性对照）。

## 明确的边界（**不要把本守卫读成覆盖面更大**，照实登记）

① **岗位全集只有 种子 ∪ 回退**（同判据 12 ④ / P3 的 `UNCOVERED_FACES`）：租户在「岗位权限」页
   **自建**的岗位、以及 `users.permissions` 的**员工级快照**，本守卫都读不到 ⇒ 一个「只勾了管理码、
   没勾读码」的自建岗位在这里看不见。
② **只覆盖能被既有解析器读到的形态**：`Map.of(...)` / YAML / `@ConfigurationProperties` 注入的
   码表**扫不到**（与设计 §5.3 的 M1 边界同源；这里说的是边界，不是覆盖面）。
③ **`WRITE_UNDER_READ_CODE` 只认「动词 + 码的动作段」这一形态**：`POST` 而语义只读的端点
   （计算 / 预览）与 `GET` 而语义写库的端点都不在射程；「这个码名算不算读码」由
   `READ_CODE_ACTIONS`（`list` / `view` / `detail` / `session`）决定，**那是一份策展表**，不是语义理解
   ⇒ 它判的是「命名形态」，不是「这个动作到底写不写库」。
④ **不判现值对不对**：三条不变量只保证「自洽」（同码 / 不 403 / 四面一致）。某个码**该不该**授给
   某个岗位是授权决定（P4 已按裁定收敛方向，逐页理由见 `P4_AUTHORIZATION_CENSUS`）。
⑤ **不动任何行为**：本文件是判据 + 台账；P4 的行为改动在 Java 注解 / 四个菜单源里，两者同 PR。
⑥ **失败态（gap）不在本守卫的实现里**：`FAIL_OPEN_PAGES` 的出口（给 `/notifications` 造一个权限点）
   是授权变更，须人类裁定 —— 本守卫只保证「它被具名登记着，不会悄悄长出新的一页」。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
DERIVE_PATH = RBAC_DIR / "derive.py"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
#: P3 守卫：**跨面映射的别名表**（`ROUTE_PREFIX_ALIASES` 等）在它里面 —— 本守卫复用，不另立一份。
P3_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_rbac_derived_pages.py"

_DERIVE_MODULE = "migao_rbac_derive_p4"
_PARITY_MODULE = "migao_rbac_parity_p4"
_P3_MODULE = "migao_rbac_derived_pages_p4"


def _load(mod_name: str, path: Path):
    """按路径加载模块（`sys.modules` 先注册是 `@dataclass` 解析 `cls.__module__` 的前提）。"""
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    assert path.is_file(), f"被复用的模块不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_derive():
    return _load(_DERIVE_MODULE, DERIVE_PATH)


def load_parity_guard():
    return _load(_PARITY_MODULE, PARITY_GUARD)


def load_p3_guard():
    return _load(_P3_MODULE, P3_GUARD)


def load_manifest() -> dict:
    return load_derive().load_manifest(MANIFEST_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# 台账一：两侧都无码的页面（fail-open 对）—— 未登记即红 / 只许缩短
# ══════════════════════════════════════════════════════════════════════════════

FAIL_OPEN_PAGES: dict[str, dict[str, str]] = {
    "/notifications": {
        "evidence": (
            "节点 `gate = null` ∧ 第一屏唯一端点 `GET /api/admin/notifications` 未被任何码把守"
            "（`units` 里只有 `__unannotated__` 一组，判据 8 的 `UNANNOTATED_ENDPOINTS` 已逐条登记）"
        ),
        "why_it_is_not_a_403": "两侧由**同一个空码**决定 ⇒ 可见面恒等于可做面，不存在「看得见打不开」",
        "exit": "给该端点补注解 + 给节点补码（= 新造一个权限点并对全部岗位授码）或明确「该页无需权限」—— 两者都是授权裁定",
        "owner": "通知中心页 + 端点注解面（`backend/admin-api/src/main/java/com/migao/admin/controller/NotificationController.java`）+ 本台账",
    },
}

#: `FAIL_OPEN_PAGES` 的条数上限（**只许缩短**；新增一页两侧无码 ⇒ 未登记即红）。
FAIL_OPEN_PAGE_CAP = 1


# ══════════════════════════════════════════════════════════════════════════════
# 台账二：I4 —— 端点层「写动作只由读码把守」的具名 census（设计 §3.4 问题 2）
# ══════════════════════════════════════════════════════════════════════════════
#
# 每条的键 = `"<VERB> <归一化路径>"`（与判据 12 的端点点名同形态）；值 = (归类, 理由 + owner)。
# 判据逐条对现取：条目必须**仍然存在且生效码不变**（陈旧 ⇒ 红）；现取里出现未登记的新形态 ⇒ 红。
# ⚠️ 本台账**不豁免任何东西**：它只是把「判据 5 看不见的那一族」变成可点名、可审的清单 ——
# 「写动作挂读码」是否要改，是授权裁定（#5699 的发现 ① 归 P4 具名报出、处置另裁）。

WRITE_UNDER_READ_CODE: dict[str, tuple[str, str]] = {
    # ── 真写动作（会改库 / 改状态；这四条就是 #5699 发现 ① 点名的四个端点）──────────────
    "POST /api/admin/production/orders/{}/instantiate": (
        "真写",
        "建加工单（`ProductionController` 类级读码 `order:list`，无方法级覆盖）—— #5699 发现 ① 的四条之一；"
        "owner = 生产域写面权限（`ProductionController`）+ 本台账",
    ),
    "POST /api/admin/production/orders/{}/operations/{}/report": (
        "真写",
        "扫码报工（同上，类级 `order:list`）—— #5699 发现 ① 的四条之一；"
        "owner = 生产域写面权限（`ProductionController`）+ 本台账",
    ),
    "POST /api/admin/production/orders/{}/print": (
        "真写",
        "打印计数（同上；`ProductionControllerTest` 逐字记录「故意沿用类级 `order:list`」的理由："
        "打印按钮对客服/销售/财务可见）—— #5699 发现 ① 的四条之一；owner = 生产域写面权限 + 本台账",
    ),
    "POST /api/admin/production/orders/{}/ship": (
        "真写",
        "发货（同上，类级 `order:list`）—— #5699 发现 ① 的四条之一；"
        "owner = 生产域写面权限（`ProductionController`）+ 本台账",
    ),
    "POST /api/admin/agent-sessions": (
        "真写",
        "开会话（`AgentSessionController`；`session` 是身份面动作名、落在 `READ_CODE_ACTIONS` 里）"
        "⇒ 形态上命中本判据，需要人判「它是不是读码」；owner = 智能客服面权限 + 本台账",
    ),
    "POST /api/admin/files/upload": (
        "真写（文件面）",
        "上传文件（`UploadController` 挂 `dashboard:view` —— 文件面**没有**自己的码）⇒ 形态上命中；"
        "owner = 文件/上传面权限（`UploadController`）+ 本台账",
    ),
    "POST /api/admin/files/upload-batch": (
        "真写（文件面）", "批量上传（同上）；owner = 文件/上传面权限 + 本台账",
    ),
    "POST /api/admin/upload/image": (
        "真写（文件面）", "上传图片（同上）；owner = 文件/上传面权限 + 本台账",
    ),
    "POST /api/admin/upload/images": (
        "真写（文件面）", "批量上传图片（同上）；owner = 文件/上传面权限 + 本台账",
    ),
    "DELETE /api/admin/files/{}": (
        "真写（文件面）", "删文件（同上）；owner = 文件/上传面权限 + 本台账",
    ),
    "DELETE /api/admin/upload/image": (
        "真写（文件面）", "删图片（同上）；owner = 文件/上传面权限 + 本台账",
    ),
    # ── 计算 / 预览（POST 但**不写库**）⇒ 挂读码是**合理**形态，登记是为了把两类分开 ─────────
    "POST /api/admin/orders/auto-features": (
        "计算/预览", "按订单特征推导可选加工项（不写库）；owner = 交易域读面 + 本台账",
    ),
    "POST /api/admin/orders/craft-calc": (
        "计算/预览", "算料预览（不写库）；owner = 交易域读面 + 本台账",
    ),
    "POST /api/admin/orders/door-width-plan": (
        "计算/预览", "门幅方案预览（不写库）；owner = 交易域读面 + 本台账",
    ),
    "POST /api/admin/orders/fee-preview": (
        "计算/预览", "加工费预览（不写库）；owner = 交易域读面 + 本台账",
    ),
    "POST /api/admin/production/pool/preview": (
        "计算/预览", "派单预览（不写库；`ProductionPoolController` 方法级 `processing:view`）；owner = 生产域读面 + 本台账",
    ),
}

#: `WRITE_UNDER_READ_CODE` 的条数上限（**只许缩短**；现取出现未登记形态 ⇒ 红）。
WRITE_UNDER_READ_CODE_CAP = 16


# ══════════════════════════════════════════════════════════════════════════════
# 台账三：D1 / D3 的授权变更 census（逐页 + 逐端点，**由判据当场复算岗位差量**）
# ══════════════════════════════════════════════════════════════════════════════

P4_AUTHORIZATION_CENSUS: dict[str, dict[str, object]] = {
    "/dashboard": {
        "gate_before": None,
        "gate_after": "dashboard:view",
        "direction": "收窄（可见面）",
        "reason": (
            "节点此前**无码**（全员可见），而该页 5 个读端点与前端路由守卫都是 `dashboard:view` "
            "⇒ 判据 12 的残留 + 「零权限的自建岗位看得见、点进去 403」。P4 按子菜单粒度补码。"
            "**D2 逐条算 M 与 N**：理由（让该页可见面 = 它的可读面）支撑 **5** 个端点（该页全部第一屏读码，"
            "同一个码），实际**新增**可达面 **0 个端点 / 0 个菜单节点给老岗位**，收窄的是「不持该码」的岗位的**菜单项**。"
        ),
        "units_changed": (),
        "menu_nodes": ("frontend:经营看板", "auth:经营看板", "controller:经营看板"),
    },
    "/production/pool": {
        "gate_before": "processing:manage",
        "gate_after": "processing:view",
        "direction": "放宽（可见面）",
        "reason": (
            "节点码此前**严于**页面读码：端点 `GET /api/admin/production/pool` 是 `processing:view`，"
            "而节点/路由守卫挂 `processing:manage` ⇒ 持读码者能调 API 却看不见入口（静默的能力浪费）。"
            "P4 取「能力真值」（端点码）为页面码。**D2**：理由支撑 **1** 个端点（该页唯一 unit），"
            "实际放开的可达面 = **1 个端点 + 1 个菜单节点**，且这 1 个端点**本来就是这些岗位可读的** "
            "⇒ M == N，不存在「理由 2 个端点、实际放开 25 个」那种不匹配。"
            "**新看见该菜单的岗位**（判据当场复算）：`customer_service`（客服）、`sales`（销售）、"
            "`finance`（财务）—— 三个在种子与回退两来源里都持 `processing:view`；"
            "`operator` / `product_manager` / `admin` 两码都持 ⇒ 无变化。**失去者：无**。"
        ),
        "units_changed": (),
        "menu_nodes": ("frontend:智能派单", "auth:智能派单", "controller:智能派单"),
    },
    "/production/saving-board": {
        "gate_before": "processing:manage",
        "gate_after": "product:list",
        "direction": "放宽（可见面）",
        "reason": (
            "同 `/production/pool`：该页第一屏两个端点在 `StockBatchController` 上是方法级 `product:list`，"
            "节点/守卫却挂 `processing:manage`。**D2**：理由支撑 **2** 个端点（该页全部第一屏读端点），"
            "实际放开 = **2 个端点 + 1 个菜单节点**，且这两个端点本就是新可见岗位可读的 ⇒ M == N。"
            "**新看见该菜单的岗位**（判据当场复算）：`sales`（销售）、`knowledge_editor`（回退）；"
            "`operator` / `product_manager` / `admin` 两码都持 ⇒ 无变化。**失去者：无**。"
        ),
        "units_changed": (),
        "menu_nodes": ("frontend:省料看板", "auth:省料看板", "controller:省料看板"),
    },
    "/production/processing": {
        "gate_before": "production:view",
        "gate_after": "production:view",
        "direction": "收窄 + 放宽（端点侧；可见面不变）",
        "reason": (
            "该页第一屏跨三个码（`order:list` ×2 / `processing:manage` ×1 / `production:view` ×1）"
            "⇒ 「整页可见但某个 tab 403」（`product_manager@fallback` 的「加工费组合」tab）。"
            "P4 把三个 unit 全部收敛到页面码 `production:view`。**D2**：理由 = 让**一个子菜单只有一个码**，"
            "它支撑该页的 **4** 个第一屏读端点（= 全部），实际变动的是**其中 3 个端点的生效码**"
            "（2 个从 `order:list`、1 个从 `processing:manage`）⇒ M（3）= N（3），且**没有**任何岗位"
            "因此看见新菜单（可见面零变化：`production:view` 的持有者集合未变）。"
            "🔴 **收窄（逐条点名，判据当场复算）**：`GET /api/admin/production/processing-fee-combinations` 与 "
            "`.../processing-fee-gaps` 从 `order:list` 改挂 `production:view` ⇒ `customer_service`（客服）、"
            "`sales`（销售）、`finance`（财务）**失去这两个端点的 API 可读性**（它们在 UI 上看不见该菜单，"
            "只可能在手机端/直达调用里用到）；`product_manager`（回退）**获得**这两个端点 —— "
            "它此前看得见「加工项管理」却在「加工费组合」tab 上 403（#5699 登记的半碎页面）。"
            "`GET /api/admin/processing-categories` 从 `processing:manage` 改挂 `production:view`："
            "两个码的持有者集合逐值相同 ⇒ **零 delta**。"
        ),
        "units_changed": (
            ("GET /api/admin/production/processing-fee-combinations", "order:list", "production:view"),
            ("GET /api/admin/production/processing-fee-gaps", "order:list", "production:view"),
            ("GET /api/admin/processing-categories", "processing:manage", "production:view"),
        ),
        "menu_nodes": (),
    },
    "/production/routings": {
        "gate_before": "production:view",
        "gate_after": "production:view",
        "direction": "零 delta（同义码统一）",
        "reason": (
            "该页第一屏 6 个读端点跨两个码（配置族 4 个 `processing:manage` / 2 个 `production:view`）。"
            "P4 把配置族收敛到页面码 `production:view`。**D2**：理由支撑该页 **6** 个端点，"
            "实际变动 **4** 个端点的生效码 ⇒ M == N。**零 delta**：两个码的持有岗位集合在种子 / 回退两来源里"
            "逐值相同（判据当场复算 `who_gains` / `who_loses` 必须都为空）。"
        ),
        "units_changed": (
            ("GET /api/admin/production/operation-positions", "processing:manage", "production:view"),
            ("GET /api/admin/production/route-rules", "processing:manage", "production:view"),
            ("GET /api/admin/production/route-rule-options", "processing:manage", "production:view"),
            ("GET /api/admin/production/seed-templates", "processing:manage", "production:view"),
        ),
        "menu_nodes": (),
    },
    "/settings": {
        "gate_before": "system:manage",
        "gate_after": "system:manage",
        "direction": "零 delta（具名保留一页多码）",
        "reason": (
            "🔴 **具名保留 + 硬理由**（两条出口都会造出新的 403，第三条出口是产品/信息架构裁定）："
            "① 简报端点改挂 `system:manage` ⇒ 只持 `dashboard:view` 的六个岗位失去 `/briefing` 页与看板的"
            "简报开关；② 节点码改 `dashboard:view` ⇒ 全员看见「企业基础信息」而该页两个管理端点 403；"
            "③ 把「每日简报开关」搬到 `/briefing` 页 ⇒ 超出权限模型阶段的射程（须人类裁定）。"
            "**零 delta 且零 403**：`system:manage` 的持有者只有 admin（恒 `*`）⇒ "
            "`可见面投影 == 持码者`（判据当场复算）。"
        ),
        "units_changed": (),
        "menu_nodes": (),
    },
    "/notifications": {
        "gate_before": None,
        "gate_after": None,
        "direction": "零 delta（具名保留 fail-open 对）",
        "reason": (
            "两侧都无码（见 `FAIL_OPEN_PAGES`）⇒ 「恰好一个码」这条不变量的**登记例外**："
            "它由一个**空码**决定，可见面恒等于可做面。要变「有码」必须新造权限点（授权变更）。"
        ),
        "units_changed": (),
        "menu_nodes": (),
    },
}

#: 覆盖面边界（**只许缩短**：条数现取、上限登记在这里；每条必须有 reason / owner）。
UNCOVERED_FACES: tuple[dict[str, str], ...] = (
    {
        "face": "租户自建岗位 + 员工级权限快照",
        "reason": "岗位全集只有 种子 ∪ 回退（仓内可读的两处）；自建岗位与 `users.permissions` 快照读不到 ⇒ 它们的可见面/可做面本判据看不见",
        "owner": "RBAC 面（租户侧数据）+ 本判据",
    },
    {
        "face": "非约定形态的码表",
        "reason": "`Map.of(...)` / YAML / `@ConfigurationProperties` 注入的码表不在既有解析器射程（设计 §5.3 的 M1 边界）",
        "owner": "RBAC 面 + 本判据",
    },
    {
        "face": "I4 的语义判定",
        "reason": "`WRITE_UNDER_READ_CODE` 只认「动词 + 码的动作段」形态；「这个动作到底写不写库」仍是人的判断（台账每条带归类，可按类审）",
        "owner": "端点写面权限 + 本判据",
    },
    {
        "face": "页内写动作的边界",
        "reason": (
            "子菜单粒度**不覆盖写动作**：页面内的写按钮仍按各自**写码**拦截（「智能派单」页的派单按钮 = "
            "`processing:update`）⇒ 持页面读码但无写码的岗位会「看得见页、读得到池、点派单 403」。"
            "这不是 P4 引入的形态（`product_manager`@回退 今天即如此），P4 让客服/销售/财务**也**落到这个形态。"
            "两条出口（写动作对齐读码 = 放宽写面须人裁 / 前端按写码隐藏按钮 = 页内 UI 动作）都不在本阶段射程。"
        ),
        "owner": "生产域写面权限（`ProductionPoolController` 等）+ 本判据",
    },
    {
        "face": "「省料看板」的域归属",
        "reason": (
            "该页第一屏两个读端点（`StockBatchController` 的 `saving-board` / `saving-trend`）是**方法级** "
            "`product:list`（V116/#5145 的口径：批次/库存属商品域读权限、不新造权限点），而它挂在"
            "「仓储与物料」组下 —— P4 按子菜单粒度把节点码收敛到该读码（**语义跨度最大**的一条）。"
            "第三条候选（为它**新造一个专属读码**）不在射程：新造权限点 = 新增一处真值 + 给全部岗位授码（授权变更）。"
        ),
        "owner": "仓储与物料组菜单/权限面 + 商品/库存域读码面 + 本判据",
    },
    {
        "face": "运行时可见性（真租户 / 真库）",
        "reason": "本机没有 admin-api 运行环境与真库 ⇒ 三条不变量算的是**声明面**（注解 / 菜单表 / 角色表），不是运行时实际授权",
        "owner": "验收面（接真环境后复算）+ 本判据",
    },
)
UNCOVERED_FACE_CAP = 6


# ══════════════════════════════════════════════════════════════════════════════
# 判据（纯函数：喂清单 / 现值 / 既有台账，返回问题清单 ⇒ 注入式红证就是喂改过的输入）
# ══════════════════════════════════════════════════════════════════════════════


def present_faces() -> dict[str, object]:
    """现值（既有解析器现取；与 P3 判据同一口径、同一入口）。"""
    derive, parity = load_derive(), load_parity_guard()
    return derive.page_present(parity, parity._source_map())


def submenu_problems(manifest: dict, present: dict, parity) -> list[str]:
    """三条不变量（子菜单粒度 / 零 403 / 多码页必须具名）。"""
    derive = load_derive()
    out: list[str] = []
    tables = derive.role_tables(manifest)
    registered_multi = set(parity.MULTI_READ_ENDPOINT_PAGES)
    present_pages = {str(p["path"]): p for p in present["pages"]}
    for page in manifest["pages"]:
        path = str(page["path"])
        gate = page["gate"]
        codes = derive.page_unit_codes(page)
        seers = set(derive.code_holders(str(gate), *tables)) if gate else set()
        if path not in present_pages:
            out.append(f"`{path}` 在清单 `pages[]` 里、却不在现值页面表里 ⇒ 锚错人（fail-closed）")
            continue
        if not codes:
            if path not in FAIL_OPEN_PAGES:
                out.append(
                    f"`{path}` 第一屏**一个码都没有**（节点码 {gate!r}）却未登记 ⇒ "
                    "「两侧都无码」必须具名（未登记即红：它是「恰好一个码」这条不变量的唯一登记例外）"
                )
            if gate is not None:
                out.append(f"`{path}` 登记为「两侧无码」却带着节点码 {gate!r} ⇒ 台账与现取不符")
            continue
        if gate is None:
            out.append(
                f"`{path}` 第一屏有码 {codes} 而节点码为 `None` ⇒ 该子菜单**没有可见性码**"
                "（「菜单看得见、点进去 403」的温床）"
            )
            continue
        if codes != [str(gate)] and path not in registered_multi:
            out.append(
                f"`{path}` 第一屏码集 {codes} ≠ 节点码 `{gate}` ⇒ 一页多码未登记"
                "（登记进 `MENU_READ_PARITY_RESIDUALS`/`MULTI_READ_ENDPOINT_PAGES`，或按子菜单粒度收敛）"
            )
        for code in codes:
            missing = seers - set(derive.code_holders(code, *tables))
            if missing:
                out.append(
                    f"`{path}`：持可见性码 `{gate}` 却**不持** `{code}` 的岗位 {sorted(missing)} ⇒ "
                    "菜单看得见、点进去 403（这正是本单要拦的形态）"
                )
        if path in registered_multi:
            rule = derive.effective_visibility_rule(page)
            projected = derive.project_visibility(rule, codes, tables)
            if projected is None or set(projected) != seers:
                out.append(
                    f"`{path}`（已登记的多码页）按 `{rule}` 投影出的可见面 {projected} ≠ 持 `{gate}` 者 "
                    f"{sorted(seers)} ⇒ 可见性不再由**那一个**码决定（例外台账失去意义）"
                )
    for path in sorted(set(FAIL_OPEN_PAGES) - {str(p["path"]) for p in manifest["pages"]}):
        out.append(f"`FAIL_OPEN_PAGES['{path}']` 已不在清单 `pages[]` 里 ⇒ 陈旧登记（只许缩短）")
    for path in sorted(registered_multi - {str(p["path"]) for p in manifest["pages"]}):
        out.append(f"`MULTI_READ_ENDPOINT_PAGES['{path}']` 已不在清单 `pages[]` 里 ⇒ 陈旧登记")
    return out


def menu_source_problems(manifest: dict, present: dict, parity) -> list[str]:
    """四个菜单/守卫面（C1/C2/C3/C4）与 `pages[].gate` 逐页同码。"""
    out: list[str] = []
    by_name = {str(n["name"]): n for n in manifest["menu_nodes"]}
    pages = {str(p["path"]): p for p in manifest["pages"]}
    guard_by_prefix = {str(prefix): code for prefix, code in present["route_guard"]}
    for path, page in sorted(pages.items()):
        gate = page["gate"]
        node = by_name.get(str(page["name"]))
        if node is None:
            out.append(f"`{path}` 的页面名『{page['name']}』不在 `menu_nodes` 里 ⇒ 四面对不上人")
            continue
        if str(node["path"] or "") != path:
            out.append(f"『{page['name']}』的节点 path = {node['path']!r} ≠ 清单页 `{path}` ⇒ 锚漂移")
        c1 = present["menu_node_codes"].get(str(page["name"]), "<缺失>")
        if c1 != gate:
            out.append(f"C1（`menu.ts` 侧边栏）『{page['name']}』码 = {c1!r} ≠ 页面码 {gate!r}")
        c2 = present["menu_controller_codes"].get(str(page["name"]))
        if c2 is not None and c2 != gate:
            out.append(f"C2（权限目录树）『{page['name']}』码 = {c2!r} ≠ 页面码 {gate!r}")
        c3 = present["auth_menu_codes"].get(str(page["name"]))
        if c3 is not None and c3 != gate:
            out.append(f"C3（登录下发菜单）『{page['name']}』码 = {c3!r} ≠ 页面码 {gate!r}")
        p3 = load_p3_guard()
        prefixes = [p for p, name in parity.ROUTE_MENU_ANCHORS.items() if name == page["name"]]
        prefixes += [p for p, name in p3.ROUTE_PREFIX_ALIASES.items() if name == page["name"]]
        for prefix in prefixes:
            code = guard_by_prefix.get(prefix)
            if code is not None and code != gate:
                out.append(f"C4（路由守卫 `{prefix}`）码 = {code!r} ≠ 页面码 {gate!r}")
    return out


def write_under_read_code(parity, manifest: dict | None = None) -> list[str]:
    """I4 的**现取**：动词非 GET、且生效码的动作段 ∈ `READ_CODE_ACTIONS` 的端点（升序、端点点名）。"""
    del manifest  # 保留形参：注入式红证按同一签名喂输入
    w = parity.build_world(parity._source_map())
    read_actions = set(parity.READ_CODE_ACTIONS)
    out: set[str] = set()
    for (verb, path), eps in w.all_eps.items():
        if verb == "GET":
            continue
        for ep in eps:
            code = ep.permission
            if code and code.split(":")[-1] in read_actions:
                out.add(f"{verb} {path}")
    return sorted(out)


def ledger_problems(parity, manifest: dict | None = None) -> list[str]:
    """两张台账的机械卫生：未登记即红 / 陈旧亦红 / 只许缩短。"""
    out: list[str] = []
    live = set(write_under_read_code(parity, manifest))
    for key in sorted(live - set(WRITE_UNDER_READ_CODE)):
        out.append(
            f"端点 `{key}` 的动词是写、生效码却是**读**码，且未登记在 `WRITE_UNDER_READ_CODE` ⇒ "
            "未登记即红（判据 5 的射程只有工具层 ⇒ 这一族没有第二条判据看得见）"
        )
    for key in sorted(set(WRITE_UNDER_READ_CODE) - live):
        out.append(f"`WRITE_UNDER_READ_CODE['{key}']` 已不再命中（端点不在 / 码已改 / 已注解写码）⇒ 陈旧登记，删掉它")
    if len(WRITE_UNDER_READ_CODE) > WRITE_UNDER_READ_CODE_CAP:
        out.append(
            f"I4 台账**又长回来了**：{len(WRITE_UNDER_READ_CODE)} 条 > 上限 {WRITE_UNDER_READ_CODE_CAP}"
            "（只许缩短；要新增先裁掉一条或改掉那个端点）"
        )
    if len(FAIL_OPEN_PAGES) > FAIL_OPEN_PAGE_CAP:
        out.append(
            f"「两侧无码」的页面**又长出来了**：{len(FAIL_OPEN_PAGES)} 页 > 上限 {FAIL_OPEN_PAGE_CAP}"
        )
    for path, entry in sorted(FAIL_OPEN_PAGES.items()):
        for field in ("evidence", "why_it_is_not_a_403", "exit", "owner"):
            if not entry.get(field, "").strip():
                out.append(f"`FAIL_OPEN_PAGES['{path}']` 缺字段 `{field}`（理由/出口/谁负责缺一即红）")
    for key, (kind, why) in sorted(WRITE_UNDER_READ_CODE.items()):
        if kind not in ("真写", "真写（文件面）", "计算/预览"):
            out.append(f"`WRITE_UNDER_READ_CODE['{key}']` 的归类 {kind!r} 不在登记集里（不许自由发挥）")
        if len(why.strip()) < 20:
            out.append(f"`WRITE_UNDER_READ_CODE['{key}']` 的理由过短（≈空字段）")
    return out


def census_problems(manifest: dict, present: dict, parity) -> list[str]:
    """D1/D3：逐页 census 与现值对账 + **当场复算**岗位差量（得 / 失）。"""
    derive = load_derive()
    out: list[str] = []
    tables = derive.role_tables(manifest)
    known = derive.all_role_names(*tables)
    pages = {str(p["path"]): p for p in manifest["pages"]}
    guard_by_prefix = {str(prefix): code for prefix, code in present["route_guard"]}
    for path, entry in sorted(P4_AUTHORIZATION_CENSUS.items()):
        page = pages.get(path)
        if page is None:
            out.append(f"`P4_AUTHORIZATION_CENSUS['{path}']` 不在清单 `pages[]` 里 ⇒ 陈旧登记")
            continue
        if str(entry["gate_after"]) != str(page["gate"]):
            out.append(
                f"census `{path}` 的改后码 {entry['gate_after']!r} ≠ 清单现值 {page['gate']!r} ⇒ 同步登记"
            )
        for field in ("direction", "reason"):
            if not str(entry[field]).strip():
                out.append(f"`P4_AUTHORIZATION_CENSUS['{path}']` 缺 `{field}`（D1 的表不许留空行）")
        before = entry["gate_before"]
        after = entry["gate_after"]
        seen_before = set(derive.code_holders(str(before), *tables)) if before else set(known)
        seen_after = set(derive.code_holders(str(after), *tables)) if after else set(known)
        for role in sorted(seen_after - seen_before):
            if role not in str(entry["reason"]):
                out.append(
                    f"census `{path}`：复算显示 `{role}` 因此**新看见**该菜单，而理由里没有点名它 ⇒ "
                    "「谁被放宽了」必须写进 D1 的表（D2 的 M/N 也要能对上）"
                )
        for role in sorted(seen_before - seen_after):
            if role not in str(entry["reason"]):
                out.append(
                    f"census `{path}`：复算显示 `{role}` 因此**失去**该菜单的可见性，而理由里没有点名它 ⇒ "
                    "收窄必须逐条写明（PR body 另有单列一节）"
                )
        # 逐端点：改后码必须等于**现值**生效码；改前 ≠ 改后；并复算「谁多出/少了这个端点」
        for endpoint, code_before, code_after in entry["units_changed"]:
            verb, _, url = str(endpoint).partition(" ")
            eps = parity._effective_codes(parity.build_world(parity._source_map()), verb, url)
            now = sorted(c for c in (eps or ()) if c)
            if now != [code_after]:
                out.append(
                    f"census `{path}`：`{endpoint}` 的现值生效码 {now} ≠ 登记的改后码 {code_after!r} ⇒ 同步登记"
                )
            if code_before == code_after:
                out.append(f"census `{path}`：`{endpoint}` 的改前码 == 改后码 ⇒ 空变动（不许凑数）")
            had = set(derive.code_holders(str(code_before), *tables))
            has = set(derive.code_holders(str(code_after), *tables))
            for role in sorted(had - has):
                if role not in str(entry["reason"]):
                    out.append(
                        f"census `{path}`：复算显示 `{role}` 因 `{endpoint}` 改码而**失去**可做面，"
                        "理由里没有点名它 ⇒ 收窄必须逐条写明"
                    )
        for node in entry["menu_nodes"]:
            source, _, name = str(node).partition(":")
            table = {
                "frontend": present["menu_node_codes"],
                "auth": present["auth_menu_codes"],
                "controller": present["menu_controller_codes"],
            }[source]
            if table.get(name) != after:
                out.append(f"census `{path}`：登记的菜单节点 `{node}` 现值码 {table.get(name)!r} ≠ {after!r}")
    del guard_by_prefix
    return out


def uncovered_face_problems() -> list[str]:
    """覆盖面台账：未登记即红（反向那条：本判据声明的面必须逐条登记）。"""
    out: list[str] = []
    if len(UNCOVERED_FACES) > UNCOVERED_FACE_CAP:
        out.append(f"未覆盖面台账**又长回来了**：{len(UNCOVERED_FACES)} 条 > 上限 {UNCOVERED_FACE_CAP}")
    seen: set[str] = set()
    for entry in UNCOVERED_FACES:
        face = entry.get("face", "")
        if not face or face in seen:
            out.append(f"覆盖面条目 `{face!r}` 为空或重复（未登记即红 / 重复 = 两处登记同一件事）")
        seen.add(face)
        for field in ("reason", "owner"):
            if not entry.get(field, "").strip():
                out.append(f"覆盖面 `{face}` 缺 `{field}`（必须写清「覆盖不到什么」）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据入参（每次现取；红证 = 喂**内存构造**的清单 / 现值，绝不改磁盘）
# ══════════════════════════════════════════════════════════════════════════════


def all_problems(manifest: dict, present: dict, parity) -> list[str]:
    return (
        submenu_problems(manifest, present, parity)
        + menu_source_problems(manifest, present, parity)
        + census_problems(manifest, present, parity)
        + ledger_problems(parity, manifest)
        + uncovered_face_problems()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据（每条都必须能变红；红证全部是**内存构造** + 「只改散文」的对照读数）
# ══════════════════════════════════════════════════════════════════════════════


def _mutate_page(manifest: dict, path: str, **fields):
    import copy

    mutated = copy.deepcopy(manifest)
    for page in mutated["pages"]:
        if str(page["path"]) == path:
            page.update(fields)
            return mutated
    raise AssertionError(f"夹具目标页不存在：{path}")


def _page(manifest: dict, path: str) -> dict:
    return next(p for p in manifest["pages"] if str(p["path"]) == path)


def test_p4_invariants_are_green_on_the_current_tree():
    """对照组：三条不变量 + 四个面 + 两张台账在**当前树**上全绿（否则红证无从归因）。"""
    manifest, present, parity = load_manifest(), present_faces(), load_parity_guard()
    problems = all_problems(manifest, present, parity)
    assert problems == [], "P4 判据在落地态不绿：\n" + "\n".join(f"  · {p}" for p in problems)


def test_every_submenu_has_one_code_and_opens_for_whoever_sees_it():
    """不变量 1 + 2 的**判别力自证**（内存构造）：三种坏形态各自必须判红。

    - ① 把某页某个端点**改回独立码**（判据 12 的多码页形态）⇒ 必须红；
    - ② 给某页的 `units` 塞一个**更宽**的码（持该码者多于持节点码者）⇒ 零 403 段必须红；
    - ③ 把某页的 `gate` 抹成 `None`（子菜单没有可见性码）⇒ 必须红。
    """
    derive, manifest, present, parity = load_derive(), load_manifest(), present_faces(), load_parity_guard()
    assert submenu_problems(manifest, present, parity) == [], "前提：当前树这一面全绿"

    # ① 端点改回独立码（`/production/processing` 的一个端点改回 `processing:manage`）
    back = _mutate_page(
        manifest, "/production/processing",
        units={
            "production:view": [
                "GET /api/admin/processing-items",
                "GET /api/admin/production/processing-fee-combinations",
                "GET /api/admin/production/processing-fee-gaps",
            ],
            "processing:manage": ["GET /api/admin/processing-categories"],
        },
    )
    hits = submenu_problems(back, present, parity)
    assert any("一页多码未登记" in h for h in hits), f"端点改回独立码没被判红：{hits}"
    assert derive.derive_page_faces(back)["multi_code_pages"] == {
        "/production/processing": ["processing:manage", "production:view"],
        "/settings": ["dashboard:view", "system:manage"],
    }, "变异体没被派生器读到 ⇒ 本条是空断言"

    # ② 更宽的码进 units（`order:list` 的持有者多于 `/production/processing` 的节点码持有者）
    wider = _mutate_page(
        manifest, "/production/processing",
        units={
            "production:view": ["GET /api/admin/processing-items"],
            "order:list": ["GET /api/admin/production/processing-fee-combinations"],
        },
    )
    hits = submenu_problems(wider, present, parity)
    assert any("菜单看得见、点进去 403" in h for h in hits), f"零 403 段没拦住更宽的码：{hits}"

    # ③ 子菜单没有可见性码
    gateless = _mutate_page(manifest, "/production/pool", gate=None)
    hits = submenu_problems(gateless, present, parity)
    assert any("没有可见性码" in h for h in hits), f"抹掉节点码后没被判红：{hits}"


def test_menu_sources_and_route_guard_must_agree_with_the_page_code():
    """不变量 3 的判别力自证：**内存构造**一个「C1 与页面码不同」的现值 ⇒ 必须红。"""
    manifest, present, parity = load_manifest(), present_faces(), load_parity_guard()
    assert menu_source_problems(manifest, present, parity) == [], "前提：当前树四面一致"
    mutated = dict(present)
    mutated["menu_node_codes"] = dict(present["menu_node_codes"])
    mutated["menu_node_codes"]["智能派单"] = "production:view"
    hits = menu_source_problems(manifest, mutated, parity)
    assert any("C1" in h and "智能派单" in h for h in hits), f"C1 与页面码不同没被判红：{hits}"

    mutated2 = dict(present)
    mutated2["route_guard"] = [
        [prefix, ("production:view" if prefix == "/production/pool" else code)]
        for prefix, code in present["route_guard"]
    ]
    hits2 = menu_source_problems(manifest, mutated2, parity)
    assert any("C4" in h and "/production/pool" in h for h in hits2), f"C4 与页面码不同没被判红：{hits2}"


def test_write_under_read_code_is_named_and_load_bearing():
    """I4 台账是**承载字段**：清空它 ⇒ 必须逐条报出（未登记即红那一半）。"""
    parity = load_parity_guard()
    live = write_under_read_code(parity)
    assert len(live) == WRITE_UNDER_READ_CODE_CAP, (
        f"现取 {len(live)} 条 / 登记 {WRITE_UNDER_READ_CODE_CAP} 条 ⇒ 两边必须逐值同步（未登记即红）"
    )
    for key in live:
        if key.startswith(("POST /api/admin/production/orders/{}/", "POST /api/admin/agent-sessions")):
            assert key in WRITE_UNDER_READ_CODE, f"`{key}` 是 #5699 发现 ① 点名的形态，必须具名登记"
    saved = dict(WRITE_UNDER_READ_CODE)
    try:
        WRITE_UNDER_READ_CODE.clear()
        problems = ledger_problems(parity)
        missing = [p for p in problems if "未登记即红" in p]
        assert len(missing) == len(live), (
            f"清空台账后应逐条报出 {len(live)} 条未登记，实际 {len(missing)} 条 ⇒ 覆盖段失效"
        )
    finally:
        WRITE_UNDER_READ_CODE.update(saved)


def test_p4_census_only_touches_read_endpoints():
    """🔴 **写侧零变化**的门禁形态：`units_changed` 里**只许出现读端点（GET）**。

    为什么需要它：用户裁定「页内功能不作为权限边界」极易被读成「读码可写」。
    写动作的码若被对齐到页面读码，就是一次**放宽写面**（持读码者可写）—— 那是必须人类裁定的授权变更。
    本判据把「P4 只改读端点」钉成机械事实：任何把写端点写进 census 的改动 ⇒ 红。
    """
    for path, entry in sorted(P4_AUTHORIZATION_CENSUS.items()):
        for endpoint, code_before, code_after in entry["units_changed"]:
            verb, _, url = str(endpoint).partition(" ")
            assert verb == "GET", (
                f"`P4_AUTHORIZATION_CENSUS['{path}']` 把**写端点** `{endpoint}` 记成了 P4 的变动项 —— "
                "子菜单粒度只管**读侧可见性**；写动作的码不在本阶段射程（I4 台账只具名报出、不处置）"
            )
            assert url.startswith("/"), f"端点 `{endpoint}` 的形态不对（应为 `<VERB> <path>`）"
    # 写侧的第二个读数：I4 台账（端点层「写动词 + 读码」）是**存量**形态，P4 不动它 ⇒ 条数必须仍是 16。
    live = write_under_read_code(load_parity_guard())
    assert len(live) == WRITE_UNDER_READ_CODE_CAP == 16, (
        f"写侧台账条数漂移（现取 {len(live)} / 上限 {WRITE_UNDER_READ_CODE_CAP}）⇒ "
        "要么有人改了写端点的码（本阶段射程外、须人裁），要么漏登记"
    )
    # 读侧：P4 记录在案的变动**恰好 7 条**（6 个方法级覆盖 + 1 个类级码改挂的列表读端点）。
    # 这个数是本阶段 D1 表的机器影子：多一条（把写端点记进来）或少一条（漏记读端点）都红。
    changed = sum(len(entry["units_changed"]) for entry in P4_AUTHORIZATION_CENSUS.values())
    assert changed == 7, (
        f"P4 的读端点变动应为 7 条，实际 {changed} ⇒ 同步 census（本数与 §一 D1 表逐条对应）"
    )


def test_census_recomputes_who_gains_and_who_loses():
    """D1/D3：census 的「谁得 / 谁失」是**当场复算**的（不是手写汇总）。

    判别力自证：把 `/production/pool` 的改前码改成与改后码**同一个**（声称零 delta），
    再将改后码换成 `processing:manage`（= 收窄形态，`customer_service` 等会失去菜单）⇒ 必须报出。
    """
    manifest, present, parity = load_manifest(), present_faces(), load_parity_guard()
    assert census_problems(manifest, present, parity) == [], "前提：census 与现值一致"
    entry = P4_AUTHORIZATION_CENSUS["/production/pool"]
    saved = dict(entry)
    try:
        entry["gate_after"] = "processing:manage"
        problems = census_problems(manifest, present, parity)
        assert any("≠ 清单现值" in p for p in problems), f"改后码与现值不符没被判红：{problems}"
        entry["gate_after"] = saved["gate_after"]
        entry["units_changed"] = (
            ("GET /api/admin/production/pool", "processing:view", "processing:manage"),
        )
        # 理由换成一句**不点名任何人**的散文 ⇒ 「谁失去」必须由判据**自己复算**并指名报出
        # （这一半是「手写汇总会与代码分叉」的机械防线，见设计 §1.4 实例 5）。
        entry["reason"] = "夹具：本行故意不点名任何岗位"
        problems = census_problems(manifest, present, parity)
        assert any("≠ 登记的改后码" in p and "processing:manage" in p for p in problems), (
            f"端点改码没被对账到现值：{problems}"
        )
        assert any("失去" in p and "customer_service" in p for p in problems), (
            f"收窄（谁失去可做面）没被复算并指名：{problems}"
        )
    finally:
        entry.clear()
        entry.update(saved)


def test_uncovered_faces_are_registered_and_only_shrink():
    """覆盖面台账：未登记即红 / 重复即红 / 只许缩短（每条必须有 reason + owner）。"""
    assert uncovered_face_problems() == [], uncovered_face_problems()
    saved = UNCOVERED_FACES
    try:
        globals()["UNCOVERED_FACES"] = saved + ({"face": "重复面", "reason": "x", "owner": "y"},
                                                {"face": "重复面", "reason": "x", "owner": "y"})
        problems = uncovered_face_problems()
        assert any("重复" in p for p in problems), f"重复条目没被判红：{problems}"
        globals()["UNCOVERED_FACES"] = saved + tuple(
            {"face": f"面{i}", "reason": "x", "owner": "y"} for i in range(UNCOVERED_FACE_CAP + 1)
        )
        assert any("又长回来了" in p for p in uncovered_face_problems()), "上限被突破没被判红"
    finally:
        globals()["UNCOVERED_FACES"] = saved


def test_comment_only_change_is_not_red():
    """**对照读数**：只改清单的散文（`_note` / `_boundary`）⇒ 判据**不红**（判的是语义，不是文件变没变）。"""
    import copy

    manifest, present, parity = load_manifest(), present_faces(), load_parity_guard()
    prose = copy.deepcopy(manifest)
    prose["_note"] = str(prose["_note"]) + "（只改散文的一句）"
    assert prose != manifest, "散文变异注入未生效（自证失败）"
    assert all_problems(prose, present, parity) == [], "只改散文竟判红 ⇒ 判据在读文本而不是在读语义"
