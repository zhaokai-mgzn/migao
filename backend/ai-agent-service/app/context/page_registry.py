"""页面上下文解释与教学（issue #5371 · B 端能力地图族 4）—— route → 真值源登记表 + 默认拒绝的注入面。

## 为什么需要机械判据（病根）

B 端最贵的成本是**培训成本**（「这个字段什么意思」「这单为什么是这个价」「这个报错怎么解决」），
而知识已经在库里 —— 缺的只是「用户在哪一页」这个入口。浮动面板（`FloatingAssistant.tsx`）
与米宝同屏 ⇒ 前端**能**直接读到 route 与当前实体。

⚠️ **但它的失效模式是「让人更烦」**：**猜错页面比不猜更烦** ——
用户明明在商品页，米宝却拿订单页的口径解释，这比「我不知道你在哪一页」糟糕得多。
⇒ 本模块的三条纪律（缺一不可，逐条有判据）：

1. **注入面按角色裁剪**（上下文注入是**新的越权面**）：只传 `route` + 实体 `id`，
   **绝不传实体快照**；实体 id 还要过该页登记的**对象读码**（缺码 ⇒ 该字段根本不出现）。
   角色**只从服务端会话取**（客户端递交的 `role` 一律不读）。
   *运输形态*：`ChatSendRequest.page_context` 一个**可选结构化字段**
   （`{"route": …, "entityId": …}`）—— 不复用 `message` 前缀协议：页面上下文是**元数据**，
   不是用户说的话（`__FORM__` 的表单值本身是内容，才需要成为消息）。
2. **`route → 真值源` 显式登记**（`TRUTH_SOURCES` + `PAGE_REGISTRY`）—— **不让 LLM 挑**：
   答案必须引登记的真值源（`citation`），不是 LLM 编的解释。
3. 🔴 **未登记的 route ⇒ 不注入**（**默认拒绝，不是默认放行**）：退回普通问答 +
   如实说「我不确定你现在在哪一页」。与「**没有处置入口的推送不发**」同源：**宁可不说，也不要猜错**。

## 登记表本身受判据约束（未登记即**不生效**，不是放行）

- `PAGE_REGISTRY` 引用未登记的 `truth_source` ⇒ `build_page_context` **不注入**（fail-closed）；
- `PAGE_REGISTRY` 的权限码必须是**真存在的码**（判据对 `RegistrationService`/`PermissionService` 的
  权限目录逐值核，见 `tests/unit_ci_workflows/test_page_context_registry.py`）；
- 真值源 `path` 必须真实存在（不存在 ⇒ 判据红 ⇒ 不许把「编的解释」伪装成真值源）。

## 明确定位（不做的事）

- **不做实体内容读取**：本模块只带 `id` 引用；实体内容由服务端既有读取面（工具/端点）
  **按该角色权限**再取一次。**复用既有读取面，不新开**。
- **不做知识库构建**（`knowledge_search` 已有）、**不做跨页面/跨实体追问**（属族 5 与对话层）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, Dict, Optional, Tuple

# C 端硬闸复用既有单点口径（`app/tools/base.py`，与 ToolContext.ticket_source 同源）——
# 页面上下文是**商户员工**的面：C 端顾客不进 B 端页面上下文（不新造第二套身份判定）。
from app.tools.base import CUSTOMER_ONLY_ROLES

#: 路径字符集：**只认路径**。查询串 / 片段在 `normalize_route` 里被丢弃（防 PII 进日志）；
#: `%` / 空格 / 非 ASCII 一律**拒绝**（URL 编码夹带 PII 的形态进不来）。
_ROUTE_RE = re.compile(r"^/[A-Za-z0-9/_.\-]*$")
_ROUTE_MAX_LEN = 200

#: 实体 id 形态：**必须含数字**（把 `new` / `edit` / `routings` / `production` 这类**路由词**挡在外面
#: —— 它们不是对象 id，当成 id 注入就是「猜错页面」的同族错误）。
#: 前端 `page-context.ts` 用**同一条**形态（语料一致性守卫：两侧对同一组样本判决必须一致）。
ENTITY_ID_RE = re.compile(r"^(?=.*[0-9])[A-Za-z0-9_\-]{2,64}$")

#: 上下文字段白名单（**静态契约**：`PageContext` 不得长出第四个字面量字段 ——
#: 新增字段必须同批登记进本元组，否则判据红。这是「不含实体快照 / 敏感字段」的机械形态）。
CONTEXT_FIELDS: Tuple[str, ...] = ("route", "truth_source", "entity_id")

#: 用户可见的降级提示（**常量**：不含 route、不含 id —— 未登记页面的路径绝不进 LLM 上下文）。
PAGE_CONTEXT_UNKNOWN_NOTICE = (
    "（提示：本次没有可用的页面上下文 —— 无法确认用户当前在哪一页。"
    "若用户的问题依赖「他在哪一页」，请**如实说明你不确定**并请他说明页面名称；"
    "不要猜测页面，也不要按猜测的页面口径解释。）"
)


@dataclass(frozen=True)
class TruthSource:
    """一个**登记在册**的真值源（解释的唯一依据）。"""

    #: 用户可见的中文来源名（上屏用；不含仓库路径等技术字面量）
    label: str
    #: 用户可见的来源标注（回复里必须写出它 ⇒ 解释可**追溯**到登记的源）
    citation: str
    #: 仓库相对路径（机器可核的追溯锚点；判据逐条核它**真实存在**）
    path: str


#: 真值源登记表。**未登记的真值源 id ⇒ 那条 route 不生效**（fail-closed，见 `build_page_context`）。
TRUTH_SOURCES: Dict[str, TruthSource] = {
    "curtain-fabric-quote-rules": TruthSource(
        label="窗帘布料算料与计价口径",
        citation="依据：本店算料与计价口径说明",
        path="docs/curtain-fabric-quote-rules.md",
    ),
    "craft-calc-glossary": TruthSource(
        label="算料口径与术语说明（工艺配置页·算料配置）",
        citation="依据：算料口径与术语说明",
        path="frontend/admin-web/src/lib/craft-calc-glossary.ts",
    ),
    "curtain-production-process-standard": TruthSource(
        label="窗帘加工工序与工艺路线标准",
        citation="依据：本店加工工序与工艺路线标准",
        path="docs/curtain-production-process-standard.md",
    ),
}


@dataclass(frozen=True)
class PageEntry:
    """一条**显式登记**的 route → 真值源（登记表的条目形态）。"""

    #: 路由（`/orders/new` 精确；`/orders/*` 前缀通配）
    route: str
    #: 真值源 id（必须 ∈ `TRUTH_SOURCES`，否则本条目**不生效**）
    truth_source: str
    #: **页面级**读码：缺 ⇒ 整块不注入（页面都看不到，凭什么给它页面口径）
    page_permissions: Tuple[str, ...]
    #: **对象级**读码：缺 ⇒ `entity_id` 字段**不出现**（其余仍在）——「注入面按角色裁剪」的落点
    entity_permissions: Tuple[str, ...]


#: route → 真值源登记表（**未登记即不注入**；本表是「哪一页能注入」的唯一真值）。
PAGE_REGISTRY: Tuple[PageEntry, ...] = (
    PageEntry(
        route="/orders/new",
        truth_source="curtain-fabric-quote-rules",
        page_permissions=("order:create",),
        entity_permissions=("order:detail",),
    ),
    PageEntry(
        route="/orders/*",
        truth_source="curtain-fabric-quote-rules",
        page_permissions=("order:list",),
        entity_permissions=("order:detail",),
    ),
    PageEntry(
        route="/products/*",
        truth_source="craft-calc-glossary",
        page_permissions=("product:list",),
        entity_permissions=("product:list",),
    ),
    PageEntry(
        route="/production/routings",
        truth_source="craft-calc-glossary",
        page_permissions=("processing:manage",),
        entity_permissions=("processing:manage",),
    ),
    PageEntry(
        route="/production/processing",
        truth_source="craft-calc-glossary",
        page_permissions=("processing:manage",),
        entity_permissions=("processing:manage",),
    ),
    PageEntry(
        route="/production/pool",
        truth_source="curtain-production-process-standard",
        page_permissions=("processing:manage",),
        entity_permissions=("processing:manage",),
    ),
)


@dataclass(frozen=True)
class PageContext:
    """注入面本身 = 三个字面量字段（**结构上装不下实体快照**）。

    `entity_id` 为 `None` = 该字段**被角色裁剪掉**（不是空串、不是占位符）。
    """

    route: str
    truth_source: str
    entity_id: Optional[str] = None

    def to_payload(self) -> Dict[str, str]:
        """序列化为**白名单键**的载荷（`None` 字段不出现 —— 裁剪 = 键缺席）。"""
        out: Dict[str, str] = {"route": self.route, "truthSource": self.truth_source}
        if self.entity_id is not None:
            out["entityId"] = self.entity_id
        return out


def normalize_route(raw: Any) -> str:
    """规范化 route：**只保留路径** —— 查询串 / 片段一律丢弃（防 PII 进日志）。

    非法形态（不以 `/` 开头 / 含 `%`、空格、非 ASCII / 过长 / 路径穿越）⇒ 返回 `""`
    ⇒ 调用方按「未登记」处理（**默认拒绝**，不是把脏数据放行）。
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


def normalize_entity_id(raw: Any) -> Optional[str]:
    """实体 id 形态校验：不合形态 ⇒ `None`（**宁可少传，也不传一个不是 id 的东西**）。"""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    return s if ENTITY_ID_RE.match(s) else None


def resolve_truth_source(truth_source_id: Any) -> Optional[TruthSource]:
    """真值源 id → 登记项；**未登记 ⇒ None**（调用方据此不注入）。"""
    if not isinstance(truth_source_id, str):
        return None
    return TRUTH_SOURCES.get(truth_source_id)


def resolve_page_entry(route: Any) -> Optional[PageEntry]:
    """route → 登记项：**先精确、后最长前缀通配**；未登记 ⇒ `None`（默认拒绝）。"""
    normalized = normalize_route(route)
    if not normalized:
        return None
    for entry in PAGE_REGISTRY:
        if entry.route == normalized:
            return entry
    best: Optional[PageEntry] = None
    for entry in PAGE_REGISTRY:
        if not entry.route.endswith("/*"):
            continue
        prefix = entry.route[:-1]  # `/orders/*` → `/orders/`
        if normalized.startswith(prefix) and (best is None or len(entry.route) > len(best.route)):
            best = entry
    return best


def has_permissions(required: Tuple[str, ...], permissions: Any) -> bool:
    """权限判定 —— 与既有口径逐字同源（`menu-nav.hasPermission` / `BaseTool.check_permission`）：

    `*` = 通配全权限；无声明码 = 不设限。
    """
    if not required:
        return True
    granted = permissions or []
    if not isinstance(granted, (list, tuple, set, frozenset)):
        return False
    if "*" in granted:
        return True
    return all(code in granted for code in required)


def build_page_context(
    raw_route: Any,
    raw_entity_id: Any = None,
    *,
    role: str = "",
    permissions: Any = None,
) -> Optional[PageContext]:
    """构造本轮注入的页面上下文；**任何一步不成立都返回 `None`（默认拒绝）**。

    判据顺序（每一步都是 fail-closed）：
    1. route 规范化失败（脏形态 / 查询串夹带）⇒ `None`；
    2. **未登记的 route ⇒ `None`**（族 4 最重要的安全默认）；
    3. 真值源**未登记 ⇒ `None`**（登记表未登记即**不生效**，不是放行）；
    4. C 端角色（`CUSTOMER_ONLY_ROLES`，复用既有单点口径）⇒ `None`；
    5. 缺**页面级**读码 ⇒ `None`；
    6. 缺**对象级**读码 ⇒ `entity_id` 键**不出现**（其余字段仍在，页面口径仍可解释）。
    """
    route = normalize_route(raw_route)
    if not route:
        return None
    entry = resolve_page_entry(route)
    if entry is None:
        return None
    if resolve_truth_source(entry.truth_source) is None:
        return None
    if role in CUSTOMER_ONLY_ROLES:
        return None
    if not has_permissions(entry.page_permissions, permissions):
        return None
    entity_id = normalize_entity_id(raw_entity_id)
    if entity_id is not None and not has_permissions(entry.entity_permissions, permissions):
        entity_id = None
    return PageContext(route=route, truth_source=entry.truth_source, entity_id=entity_id)


def render_page_context(question: str, context: Optional[PageContext]) -> str:
    """把上下文渲染成本轮注入文本（LLM 无感协议，与 `__FORM__` 同族）。

    - 有上下文 ⇒ 页面 + **真值源登记信息**（`label` / `path` / 必须写出的 `citation`）；
    - 无上下文（含未登记 route）⇒ **常量降级提示**（route / id **一个字都不进**）。
    """
    if context is None:
        return PAGE_CONTEXT_UNKNOWN_NOTICE + question
    source = resolve_truth_source(context.truth_source)
    if source is None:  # pragma: no cover - 与 build_page_context 同步的纵深防御
        return PAGE_CONTEXT_UNKNOWN_NOTICE + question
    lines = [
        f"（米宝正在用户当前页面上：{context.route}",
        f"本页的口径说明以《{source.label}》为唯一真值源（{source.path}）；"
        f"解释本页字段/口径/价格时必须基于该真值源，并在答案里写明「{source.citation}」；"
        f"真值源没写到的内容不要替它编。",
        "仅当用户的问题与当前页面或本页口径有关时才使用本提示；否则照常回答。",
    ]
    if context.entity_id is not None:
        lines.append(f"用户当前正在看的对象 id：{context.entity_id}。")
    lines.append("）")
    return "".join(lines) + question


def context_field_names() -> Tuple[str, ...]:
    """`PageContext` 的字段名（供判据核「上下文装不下第四样东西」）。"""
    return tuple(f.name for f in fields(PageContext))