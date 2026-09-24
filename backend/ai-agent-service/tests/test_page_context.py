# case_ids: CH-009, CH-004, DF-007, DF-013, CH-003
"""页面上下文（issue #5371 · B 端能力地图族 4）—— 注入面按角色裁剪 + route→真值源登记 + **默认拒绝**。

## 本文件判什么（逐条对应 issue 的 5 条验收判据，全部可执行）

| # | 判据 | 判据函数 | 红证（注入式） |
|---|---|---|---|
| 1 | **注入面按角色裁剪**：越权角色 ⇒ 该字段**不出现在上下文里** | `problems_role_trim` | `has_permissions` 恒真 ⇒ 红 |
| 2 | **上下文不含实体快照 / 敏感字段**（静态契约 + 断言） | `problems_injection_surface` | `PageContext` 长字段 / 载荷混入敏感键 ⇒ 红 |
| 3 | 🔴 **未登记 route ⇒ 不注入**（**默认拒绝**） | `problems_default_deny` | 登记表加一条 `/*` 兜底 ⇒ 红 |
| 4 | **答案引真值源**：解释可追溯到**登记的**源 | `problems_truth_source_registered` | 摘掉一条真值源（未被登记）⇒ 红 |
| 5 | **route 不带查询串**（防 PII 进日志） | `problems_route_no_query` | 把 `normalize_route` 换成放行版 ⇒ 红 |

外加两条**类级元守卫**（§23 G1/G2/G5）：

- `problems_permission_codes`：登记表里的权限码必须是**真存在的码** —— 复用既有对账守卫
  `tests/unit_ci_workflows/test_agent_permission_parity.py` 的权限目录解析器（**不造第二套解析器**，
  §17.3 ⑤「契约里的技术字面量凭语义推测」的病根：`product:update` 曾在全仓零命中）。
- `problems_cross_language_form`：**同一形态两处投影 ⇒ 机械钉等价**（§17.3 ③）——
  实体 id 形态（`ENTITY_ID_FORM` ↔ `ENTITY_ID_RE`）与路径字符集（`ROUTE_FORM` ↔ `_ROUTE_RE`）
  在 TS / Python 两侧**对同一语料逐条判决必须相同**。

## 明确边界（照实登记，不粉饰）

- **纯数字段无法与「恰好出现在路径里的一串数字」区分**：`13800138000` 形态**会被当成 id**
  （见 `ENTITY_ID_CORPUS` 的 `KNOWN_RESIDUALS`）。缓解：① 前端只从**路径段**取、且查询串在
  两端各丢一次；② 服务端日志侧走 `LogSanitizer.mask_text` 脱敏、**不留痕 route 原文与 id**；
  ③ 该值只出现在 `entityId` 一个字段里（`PageContext` 结构上装不下别的）。
- 本文件**不判 LLM 是否真的引用了真值源**（那是行为面，按 `migao-dev-flow` §13.2 映射到
  `.github/cases/` 的 CH-004/CH-003 走评测；本文件判的是**注入面**：真值源与必写标注
  **确实进了本轮上下文**，即「可追溯」的必要条件）。
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.schemas import ChatSendRequest
from app.context import page_registry as PR
from app.utils.auth import UserIdentity
from tests.test_chat import _memory, _session

REPO_ROOT = Path(__file__).resolve().parents[3]
TS_PAGE_CONTEXT = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "page-context.ts"
TS_PAGE_CONTEXT_TEST = REPO_ROOT / "frontend" / "admin-web" / "tests" / "unit" / "lib" / "page-context.test.ts"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"

UUID = "8f3c1a2e-4b5d-4f6a-9c7e-1d2b3a4c5d6e"

#: 实体 id 形态语料（**与前端 `tests/unit/lib/page-context.test.ts` 同语料**）。
ENTITY_ID_CORPUS: tuple[tuple[str, bool], ...] = (
    (UUID, True),
    ("12345", True),
    ("test-order-123", True),
    ("item1", True),
    # 路由词**不是**对象 id（`use-route-id.ts` 在 `/orders/new` 会解析出 `orders`，本模块必须拒）
    ("new", False),
    ("edit", False),
    ("create", False),
    ("ship", False),
    ("production", False),
    ("routings", False),
    ("pool", False),
    ("processing", False),
    ("orders", False),
    ("products", False),
    ("张三", False),
    ("郑 州", False),
    ("<script>", False),
    ("", False),
)

#: **残留（如实登记）**：纯数字串形态上无法与「路径里的一串数字」区分 ⇒ 会被当作 id。
KNOWN_RESIDUALS = frozenset({"13800138000"})

#: 路径规范化语料（**与前端同语料**；`""` = 非法形态 ⇒ 不递交 / 不注入）。
ROUTE_CORPUS: tuple[tuple[str, str], ...] = (
    ("/orders/123", "/orders/123"),
    ("/orders/123?phone=13800138000", "/orders/123"),
    ("/orders/123?phone=13800138000#top", "/orders/123"),
    ("/products/abc/", "/products/abc"),
    ("/production/routings", "/production/routings"),
    ("/", "/"),
    ("orders/123", ""),
    ("", ""),
    ("/orders/%E5%BC%A0%E4%B8%89", ""),
    ("/orders/张 三", ""),
    ("/orders/../etc/passwd", ""),
    ("/orders//123", ""),
)

#: 路径字符集语料（跨语言形态一致性用；只含**路径**，不含查询串）。
PATH_FORM_CORPUS: tuple[str, ...] = ("/orders/123", "/", "/production/routings", "/a_b-c.d", "/x y", "/x%20y", "x/y")

#: **未登记**的 route 语料（默认拒绝的靶子）。至少一条是**真实存在的页面**（不是瞎编的路径）。
UNREGISTERED_ROUTES: tuple[str, ...] = (
    "/knowledge",          # 真实页面（知识库），**本单未登记** ⇒ 不注入
    "/dashboard",          # 真实页面（经营看板），未登记
    "/customers/12345",    # 真实页面（客户详情），未登记
    "/settings",           # 真实页面（企业基础信息），未登记
    "/production/piecework",
    "/not-a-real-page",
)

#: 商户员工身份（真实权限码取自 admin-api 权限目录）
MERCHANT_PERMISSIONS = ("order:list", "order:detail", "product:list", "processing:manage")

_INJECTION_KEYS = ("role", "permissions", "entitySnapshot", "snapshot", "data", "customerName", "phone")
_QUESTION = "这单为什么是这个价？"

#: C 端角色语料（**冻结在判据文件里**，值域与 `app/tools/base.py` 的 `CUSTOMER_ONLY_ROLES` 相同；
#: 判据逐条断言两侧集合相等 ⇒ 实现增删角色而不改本语料 = 红）。
C_END_ROLES: tuple[str, ...] = ("customer", "agent")


def _merchant(role: str = "product_manager", permissions=MERCHANT_PERMISSIONS) -> UserIdentity:
    return UserIdentity(
        user_id="user_1", tenant_id=1, identity_type="account",
        role=role, permissions=list(permissions),
    )


def _customer() -> UserIdentity:
    return UserIdentity(user_id="c_1", tenant_id=1, identity_type="wechat_mini", role="customer")


def _payload(route: Optional[str], entity_id: Optional[str] = None, **extra) -> dict:
    """递交载荷（服务端**只读** `route` / `entityId`，其余键一律忽略 —— 测试据此注入越权字段）。"""
    body: dict = {"route": route}
    if entity_id is not None:
        body["entityId"] = entity_id
    body.update(extra)
    return body


# ══════════════════════════════════════════════════════════════════════════════
# 一、判据函数（纯函数，读**现取**的模块状态 —— 注入式红证就是替换这里的输入）
# ══════════════════════════════════════════════════════════════════════════════


def problems_default_deny() -> list[str]:
    """③ 未登记的 route ⇒ **不注入**，且 route / id 一个字都不进注入文本。"""
    bad: list[str] = []
    for route in UNREGISTERED_ROUTES:
        ctx = PR.build_page_context(route, "12345", role="admin", permissions=["*"])
        if ctx is not None:
            bad.append(f"未登记 route 被注入了：{route} → {ctx.to_payload()}")
        rendered = PR.render_page_context(_QUESTION, ctx)
        if rendered != PR.PAGE_CONTEXT_UNKNOWN_NOTICE + _QUESTION:
            bad.append(f"未登记 route 的注入文本不是常量降级提示：{route}")
        if route in rendered:
            bad.append(f"未登记 route 的路径进了上下文：{route}")
    return bad


def problems_role_trim() -> list[str]:
    """① 注入面按角色裁剪：越权角色 ⇒ 该字段**不出现在**上下文里。"""
    bad: list[str] = []
    order_route = f"/orders/{UUID}"
    full = PR.build_page_context(order_route, UUID, role="admin", permissions=["*"])
    if full is None or full.entity_id != UUID:
        bad.append("全权限角色没能拿到实体 id（判据会空转 ⇒ fail-closed）")
    else:
        payload = full.to_payload()
        if payload.get("entityId") != UUID:
            bad.append("全权限角色的载荷里没有 entityId")
        if set(payload) != {"route", "entityId", "truthSource"}:
            bad.append(f"全权限角色载荷键集不对：{sorted(payload)}")

    # 有页面读码、无对象读码 ⇒ 上下文仍在，但 entityId **键缺席**
    trimmed = PR.build_page_context(order_route, UUID, role="customer_service", permissions=["order:list"])
    if trimmed is None:
        bad.append("有页面读码却被整块拒了（页面口径应当仍可解释）")
    else:
        payload = trimmed.to_payload()
        if "entityId" in payload:
            bad.append(f"缺对象读码却仍带实体 id：{payload}")
        if set(payload) != {"route", "truthSource"}:
            bad.append(f"裁剪后载荷键集不对：{sorted(payload)}")

    # 无页面读码 ⇒ 整块不注入
    if PR.build_page_context(order_route, UUID, role="warehouse", permissions=["product:list"]) is not None:
        bad.append("缺页面读码却被注入了")

    # C 端（复用既有 CUSTOMER_ONLY_ROLES 硬闸）⇒ 整块不注入
    for role in sorted(PR.CUSTOMER_ONLY_ROLES):
        if PR.build_page_context(order_route, UUID, role=role, permissions=[]) is not None:
            bad.append(f"C 端角色被注入了 B 端页面上下文：{role}")

    # 通配 `*` 与逐码声明同口径
    if PR.build_page_context(order_route, UUID, role="admin", permissions=[]) is not None:
        bad.append("空权限被注入了（`*` 之外不该放行）")
    return bad


def problems_injection_surface() -> list[str]:
    """② 上下文**结构上**装不下实体快照 / 敏感字段（静态契约 + 载荷断言）。"""
    bad: list[str] = []
    names = PR.context_field_names()
    if names != PR.CONTEXT_FIELDS:
        bad.append(f"PageContext 字段白名单漂移：{names} != {PR.CONTEXT_FIELDS}")
    ctx = PR.build_page_context(f"/orders/{UUID}", UUID, role="admin", permissions=["*"])
    if ctx is None:
        bad.append("登记 route 拿不到上下文（判据会空转）")
        return bad
    payload = ctx.to_payload()
    extra = set(payload) - {"route", "entityId", "truthSource"}
    if extra:
        bad.append(f"载荷出现白名单外的键：{sorted(extra)}")
    blob = json.dumps(payload, ensure_ascii=False)
    for token in _INJECTION_KEYS:
        if token in blob:
            bad.append(f"载荷里出现疑似快照/敏感键：{token}")
    return bad


def problems_truth_source_registered() -> list[str]:
    """④ 登记表自证：真值源**已登记**且 `path` **真实存在**（未登记即不生效）。"""
    bad: list[str] = []
    if not PR.PAGE_REGISTRY:
        bad.append("登记表为空 ⇒ 判据会空跑")
    for entry in PR.PAGE_REGISTRY:
        source = PR.resolve_truth_source(entry.truth_source)
        if source is None:
            bad.append(f"`{entry.route}` 引用了未登记的真值源：{entry.truth_source}（未登记即不生效）")
            continue
        if not (REPO_ROOT / source.path).is_file():
            bad.append(f"真值源 `{entry.truth_source}` 的 path 不存在：{source.path}")
        if not source.citation.strip() or not source.label.strip():
            bad.append(f"真值源 `{entry.truth_source}` 缺 label / citation（回复无法追溯）")
    # 真值源 id ↔ 用户可见标注必须**一一对应**（否则「可追溯」是假的）
    citations = [s.citation for s in PR.TRUTH_SOURCES.values()]
    if len(set(citations)) != len(citations):
        bad.append("真值源的 citation 有重号 ⇒ 回复里的来源标注无法反查到唯一真值源")
    return bad


def problems_route_no_query() -> list[str]:
    """⑤ route **不带查询串**（防 PII 进日志），且非法形态一律拒绝。"""
    bad: list[str] = []
    for raw, expected in ROUTE_CORPUS:
        got = PR.normalize_route(raw)
        if got != expected:
            bad.append(f"规范化不符：{raw!r} → {got!r}（期望 {expected!r}）")
    # 任何一次真实注入里都不得出现 `?` / `#` / PII 片段
    for route, entity_id in (("/orders/123?phone=13800138000", "123"), ("/products/abc#top", None)):
        ctx = PR.build_page_context(route, entity_id, role="admin", permissions=["*"])
        if ctx is None:
            bad.append(f"带查询串的合法路径被整块拒了（应当丢查询串后注入）：{route}")
            continue
        rendered = PR.render_page_context(_QUESTION, ctx)
        for token in ("?", "#", "phone", "13800138000"):
            if token in rendered:
                bad.append(f"注入文本里出现 `{token}`：{route}")
    return bad


def problems_c_end_gate() -> list[str]:
    """类级：**每一条**登记 route 在 C 端角色下都必须拿不到上下文（逐条穷举，一个洞都不许有）。

    为什么这是**类级**判据：登记表是 agent 侧唯一按**前端路由**登记知识的模块，而既有 L0 约束
    （`tests/test_card_type_cross_end_contract.py::TestAgentSideCarriesNoRoutes`，射程 = `chat.py`）
    给出的理由正是「路由必须由各端自己拼，否则 **C 端会拿到 B 端路径**」。那张守卫**不覆盖**本模块
    —— 于是「本模块也不能对 C 端生效」这个理由必须在这里被机械钉住（§23 G5：面外不是安全区）。
    """
    bad: list[str] = []
    if not PR.PAGE_REGISTRY:
        return ["登记表为空 ⇒ 判据会空跑（fail-closed）"]
    # 🔴 语料**冻结在本文件**，不取 `PR.CUSTOMER_ONLY_ROLES`（§23.8 B1：判据语料不得取自被测对象
    # —— 否则「硬闸被摘掉」会让语料同时变空，判据**空跑成绿**，红证当场失效）。
    if set(C_END_ROLES) != set(PR.CUSTOMER_ONLY_ROLES):
        bad.append(
            f"C 端角色语料与实现不同源（增删 C 端角色必须同批改本语料）："
            f"语料={sorted(C_END_ROLES)} 实现={sorted(PR.CUSTOMER_ONLY_ROLES)}"
        )
    for entry in PR.PAGE_REGISTRY:
        sample = entry.route[:-1] + "12345" if entry.route.endswith("/*") else entry.route
        for role in C_END_ROLES:
            context = PR.build_page_context(sample, "12345", role=role, permissions=["*"])
            if context is not None:
                bad.append(f"C 端角色 `{role}` 拿到了 B 端页面上下文：{sample} → {context.to_payload()}")
    return bad


def _permission_catalog() -> frozenset[str]:
    """权限目录（**复用既有守卫的解析器**，不造第二套）。"""
    import sys
    spec = importlib.util.spec_from_file_location("_parity_guard_for_page_ctx", PARITY_GUARD)
    module = importlib.util.module_from_spec(spec)
    # 必须先入 `sys.modules`：该模块用 `from __future__ import annotations` + `@dataclass`，
    # 而 dataclasses 解析字符串注解时要按 `cls.__module__` 查 `sys.modules`（缺了会 TypeError）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    sources = module._source_map()
    reg_codes, perm_codes = module.parse_catalog(
        sources["java:service/RegistrationService.java"],
        sources["java:service/PermissionService.java"],
    )
    return frozenset(reg_codes) | frozenset(perm_codes)


def problems_permission_codes() -> list[str]:
    """类级元守卫：登记表里的权限码必须是**真存在的码**（零命中的想象码 ⇒ 红）。"""
    bad: list[str] = []
    catalog = _permission_catalog()
    if not catalog:
        bad.append("权限目录解析出 0 条 ⇒ 判据会空跑（fail-closed）")
        return bad
    declared = {code for entry in PR.PAGE_REGISTRY for code in entry.page_permissions + entry.entity_permissions}
    if not declared:
        bad.append("登记表没有声明任何权限码 ⇒ 判据会空跑")
    for code in sorted(declared):
        if code not in catalog:
            bad.append(f"权限码 `{code}` 不在 admin-api 权限目录里（零命中的想象码）")
    return bad


def _ts_regex_source(text: str, const_name: str) -> str:
    """取 TS 模块里 `const <name> = /…/` 的正则**源文本**（找不到 ⇒ `""` ⇒ 判据红）。"""
    m = re.search(rf"const {const_name} = /(.+?)/\n", text)
    return m.group(1) if m else ""


def problems_cross_language_form(ts_text: Optional[str] = None) -> list[str]:
    """类级元守卫：**同一形态两处投影 ⇒ 机械钉等价**（TS ↔ Python 逐条同判决）。"""
    bad: list[str] = []
    text = TS_PAGE_CONTEXT.read_text(encoding="utf-8") if ts_text is None else ts_text
    ts_id = _ts_regex_source(text, "ENTITY_ID_FORM")
    ts_route = _ts_regex_source(text, "ROUTE_FORM")
    if not ts_id or not ts_route:
        bad.append("TS 侧形态字面量取不到（`ENTITY_ID_FORM` / `ROUTE_FORM`）—— 形态被换写法即判红")
        return bad

    for token, expected in ENTITY_ID_CORPUS:
        py_ok = PR.normalize_entity_id(token) is not None
        ts_ok = re.fullmatch(ts_id, token) is not None
        if py_ok != ts_ok:
            bad.append(f"实体 id 形态两侧不同源：{token!r} TS={ts_ok} Py={py_ok}")
        if py_ok != expected and token not in KNOWN_RESIDUALS:
            bad.append(f"实体 id 判决与语料不符：{token!r} → {py_ok}（期望 {expected}）")

    for token in PATH_FORM_CORPUS:
        py_ok = PR._ROUTE_RE.match(token) is not None
        ts_ok = re.fullmatch(ts_route, token) is not None
        if py_ok != ts_ok:
            bad.append(f"路径字符集两侧不同源：{token!r} TS={ts_ok} Py={py_ok}")
    return bad


PROBLEM_SETS: dict[str, Callable[[], list[str]]] = {
    "default_deny": problems_default_deny,
    "role_trim": problems_role_trim,
    "injection_surface": problems_injection_surface,
    "truth_source_registered": problems_truth_source_registered,
    "route_no_query": problems_route_no_query,
    "permission_codes": problems_permission_codes,
    "cross_language_form": problems_cross_language_form,
    "c_end_gate": problems_c_end_gate,
}


# ══════════════════════════════════════════════════════════════════════════════
# 二、实例判据（全绿）
# ══════════════════════════════════════════════════════════════════════════════


def test_all_judgements_are_green(capsys) -> None:
    """七条判据全绿 —— 并**打印现取读数**（绿得没有计数 = 未跑）。"""
    for name, fn in PROBLEM_SETS.items():
        problems = fn()
        assert not problems, f"判据 `{name}` 判红：\n" + "\n".join(f"  {p}" for p in problems)
    with capsys.disabled():
        print(
            f"[页面上下文] 登记 route={len(PR.PAGE_REGISTRY)} 条 / 真值源={len(PR.TRUTH_SOURCES)} 条 / "
            f"未登记语料={len(UNREGISTERED_ROUTES)} 条 / id 语料={len(ENTITY_ID_CORPUS)} 条 / "
            f"路径语料={len(ROUTE_CORPUS)} 条 / 权限目录现取={len(_permission_catalog())} 码"
        )


@pytest.mark.parametrize("route,expected", ROUTE_CORPUS)
def test_route_corpus(route: str, expected: str) -> None:
    assert PR.normalize_route(route) == expected


@pytest.mark.parametrize("token,expected", ENTITY_ID_CORPUS)
def test_entity_id_corpus(token: str, expected: bool) -> None:
    assert (PR.normalize_entity_id(token) is not None) is expected


def test_registry_routes_match_real_pages() -> None:
    """登记表里的 route **必须对应真实存在的页面**（登记一条不存在的页面 = 猜错页面）。"""
    dashboard = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)"
    missing = []
    for entry in PR.PAGE_REGISTRY:
        head = entry.route.rstrip("*").rstrip("/").lstrip("/")
        if not (dashboard / head).exists():
            missing.append(entry.route)
    assert missing == [], f"登记了不存在的页面：{missing}（判据：登记表只许登记真实路由）"


def test_unregistered_truth_source_does_not_inject(monkeypatch) -> None:
    """🔴 登记表未登记即**不生效**（fail-closed）—— 摘掉真值源 ⇒ 那条 route 不再注入。"""
    baseline = PR.build_page_context("/orders/123", "12345", role="admin", permissions=["*"])
    assert baseline == PR.PageContext(
        route="/orders/123", truth_source="curtain-fabric-quote-rules", entity_id="12345",
    ), "前提自证：未注入前该 route 是登记的且带实体 id"
    monkeypatch.setattr(
        PR, "TRUTH_SOURCES",
        {k: v for k, v in PR.TRUTH_SOURCES.items() if k != "curtain-fabric-quote-rules"},
    )
    assert PR.build_page_context("/orders/123", "12345", role="admin", permissions=["*"]) is None


def test_unregistered_route_renders_constant_notice() -> None:
    """降级文本是**常量**：任意 route / id 输入 ⇒ 输出逐字相同（结构上没有泄漏通道）。"""
    for route in UNREGISTERED_ROUTES:
        assert PR.render_page_context(_QUESTION, None) == PR.PAGE_CONTEXT_UNKNOWN_NOTICE + _QUESTION
    assert "?" not in PR.PAGE_CONTEXT_UNKNOWN_NOTICE
    assert "/" not in PR.PAGE_CONTEXT_UNKNOWN_NOTICE


def test_truth_source_reaches_context_with_citation() -> None:
    """④ 可追溯：本轮上下文里**确实**带上了登记的真值源与必写标注。"""
    ctx = PR.build_page_context(f"/products/{UUID}", UUID, role="admin", permissions=["*"])
    assert ctx == PR.PageContext(
        route=f"/products/{UUID}", truth_source="craft-calc-glossary", entity_id=UUID,
    )
    source = PR.TRUTH_SOURCES[ctx.truth_source]
    rendered = PR.render_page_context(_QUESTION, ctx)
    assert source.citation in rendered
    assert source.path in rendered
    assert f"/products/{UUID}" in rendered
    assert rendered.endswith(_QUESTION)


# ══════════════════════════════════════════════════════════════════════════════
# 三、注入式红证（§23 G7：每条**先自证注入生效**，再判它真会红）
# ══════════════════════════════════════════════════════════════════════════════


def _mutant_default_allow(monkeypatch) -> Callable[[], list[str]]:
    """把默认改成「放行」：加一条 `/*` 兜底登记。"""
    baseline = PR.PAGE_REGISTRY
    monkeypatch.setattr(
        PR, "PAGE_REGISTRY",
        baseline + (PR.PageEntry(route="/*", truth_source="craft-calc-glossary",
                                 page_permissions=(), entity_permissions=()),),
    )
    assert PR.PAGE_REGISTRY != baseline, "注入未生效（自证）：登记表没变"
    assert PR.resolve_page_entry("/not-a-real-page") is not None, "注入未生效（自证）：兜底条目没兜住"
    return problems_default_deny


def _mutant_ignore_permissions(monkeypatch) -> Callable[[], list[str]]:
    baseline = PR.has_permissions
    monkeypatch.setattr(PR, "has_permissions", lambda required, permissions: True)
    assert PR.has_permissions is not baseline, "注入未生效（自证）"
    assert PR.build_page_context(f"/orders/{UUID}", UUID, role="admin", permissions=[]) is not None, \
        "注入未生效（自证）：空权限仍被拦"
    return problems_role_trim


def _mutant_drop_truth_source(monkeypatch) -> Callable[[], list[str]]:
    baseline = dict(PR.TRUTH_SOURCES)
    monkeypatch.setattr(PR, "TRUTH_SOURCES", {k: v for k, v in baseline.items() if k == "craft-calc-glossary"})
    assert PR.TRUTH_SOURCES != baseline, "注入未生效（自证）"
    return problems_truth_source_registered


def _mutant_keep_query(monkeypatch) -> Callable[[], list[str]]:
    baseline = PR.normalize_route

    def lax(raw):
        return raw.strip() if isinstance(raw, str) and raw.startswith("/") else ""

    monkeypatch.setattr(PR, "normalize_route", lax)
    assert PR.normalize_route is not baseline, "注入未生效（自证）"
    assert "?" in PR.normalize_route("/orders/123?phone=1"), "注入未生效（自证）：查询串没被留下"
    return problems_route_no_query


def _mutant_ghost_permission_code(monkeypatch) -> Callable[[], list[str]]:
    baseline = PR.PAGE_REGISTRY
    monkeypatch.setattr(
        PR, "PAGE_REGISTRY",
        baseline + (PR.PageEntry(route="/ghost", truth_source="craft-calc-glossary",
                                 page_permissions=("ghost:code",), entity_permissions=()),),
    )
    assert PR.PAGE_REGISTRY != baseline, "注入未生效（自证）"
    return problems_permission_codes


def _mutant_widen_context_fields(monkeypatch) -> Callable[[], list[str]]:
    baseline = PR.CONTEXT_FIELDS
    monkeypatch.setattr(PR, "CONTEXT_FIELDS", baseline + ("entity_snapshot",))
    assert PR.CONTEXT_FIELDS != baseline, "注入未生效（自证）"
    return problems_injection_surface


def _mutant_drop_c_end_gate(monkeypatch) -> Callable[[], list[str]]:
    """把 C 端硬闸摘掉（`CUSTOMER_ONLY_ROLES` 清空）⇒ 逐条穷举判据必须变红。"""
    baseline = PR.CUSTOMER_ONLY_ROLES
    monkeypatch.setattr(PR, "CUSTOMER_ONLY_ROLES", frozenset())
    assert PR.CUSTOMER_ONLY_ROLES != baseline, "注入未生效（自证）"
    assert PR.build_page_context("/orders/123", "12345", role="customer", permissions=["*"]) is not None, \
        "注入未生效（自证）：C 端仍被拦住"
    return problems_c_end_gate


@pytest.mark.parametrize("mutate", [
    _mutant_default_allow,
    _mutant_ignore_permissions,
    _mutant_drop_truth_source,
    _mutant_keep_query,
    _mutant_ghost_permission_code,
    _mutant_widen_context_fields,
    _mutant_drop_c_end_gate,
])
def test_every_judgement_can_go_red(monkeypatch, mutate) -> None:
    problems_fn = mutate(monkeypatch)
    assert problems_fn(), f"注入 `{mutate.__name__}` 后判据仍判绿 ⇒ 该判据没有判别力"


def test_cross_language_form_drift_can_go_red() -> None:
    """跨语言形态守护的红证：把 TS 侧的数字前瞻拿掉 ⇒ 判决分叉 ⇒ 必红。"""
    text = TS_PAGE_CONTEXT.read_text(encoding="utf-8")
    baseline = problems_cross_language_form(text)
    assert baseline == [], f"前提自证：原始 TS 与 Python 同源，却判红 {baseline}"
    mutated = text.replace("const ENTITY_ID_FORM = /^(?=.*[0-9])", "const ENTITY_ID_FORM = /^(?:)")
    assert mutated != text, "注入未生效（自证）：TS 形态字面量没被替换"
    assert problems_cross_language_form(mutated), "TS 侧形态漂移却没红 ⇒ 跨语言守护是空断言"


def test_ts_test_corpus_is_shared() -> None:
    """两侧语料**同源**：前端判据文件里必须出现同一批 id 语料（漂移即红）。"""
    text = TS_PAGE_CONTEXT_TEST.read_text(encoding="utf-8")
    missing = [token for token, _ in ENTITY_ID_CORPUS if token and token not in text]
    assert missing == [], f"前端语料里缺这些样本：{missing}（跨语言语料漂移）"


# ══════════════════════════════════════════════════════════════════════════════
# 四、字段入口（`ChatSendRequest.page_context`）—— 客户端说了不算
# ══════════════════════════════════════════════════════════════════════════════


async def _run_handler(req: ChatSendRequest, user: UserIdentity):
    """调 `_handle_page_ctx_request`，返回它交给下游 `send_message` 的那条消息。"""
    from app.api.chat import _handle_page_ctx_request

    with patch("app.api.chat.send_message", new=AsyncMock(return_value=MagicMock())) as mock_send, \
            patch("app.api.chat.SessionMemory",
                  return_value=_memory(get_session=_session(id="sess_1", customer_id=user.user_id))):
        await _handle_page_ctx_request(req, tenant_id=1, user_id=user.user_id, current_user=user)
    return mock_send.call_args.args[0].message


def _req(route: Optional[str], entity_id: Optional[str] = None, **extra) -> ChatSendRequest:
    return ChatSendRequest(
        session_id="sess_1",
        message=_QUESTION,
        page_context=_payload(route, entity_id, **extra),
    )


class TestPageContextField:
    """字段入口：登记 ⇒ 注入真值源；未登记 ⇒ 什么都不注入；客户端越权字段一律忽略。"""

    @patch("app.api.chat._handle_page_ctx_request")
    @pytest.mark.asyncio
    async def test_send_message_delegates(self, mock_handler) -> None:
        """入口分派：带 `page_context` 的请求委托 `_handle_page_ctx_request`。"""
        from app.api.chat import send_message
        mock_handler.return_value = MagicMock()
        await send_message(_req("/orders/123", "12345"), current_user=_merchant())
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registered_route_injects_truth_source(self) -> None:
        message = await _run_handler(_req("/orders/123", "12345"), _merchant())
        source = PR.TRUTH_SOURCES["curtain-fabric-quote-rules"]
        assert source.citation in message
        assert source.path in message
        assert "/orders/123" in message
        assert "12345" in message
        assert message.endswith(_QUESTION)

    @pytest.mark.asyncio
    async def test_unregistered_route_injects_nothing(self) -> None:
        """🔴 未登记 ⇒ 注入文本里**没有** route（默认拒绝的入口级红证）。"""
        message = await _run_handler(_req("/knowledge"), _merchant())
        assert message == PR.PAGE_CONTEXT_UNKNOWN_NOTICE + _QUESTION
        assert "/knowledge" not in message
        assert "knowledge" not in message

    @pytest.mark.asyncio
    async def test_absent_page_context_does_not_delegate(self) -> None:
        """**不递交页面上下文 ⇒ 入口不分派、不注入任何提示**（非浏览器调用方零影响）。

        判据取「正常链路照旧走」：未带 `page_context` 的请求走普通路径（这里用 closed 会话
        把普通路径停在 409），且 `_handle_page_ctx_request` **一次都没被调**。
        """
        from app.api.chat import send_message
        with patch("app.api.chat._handle_page_ctx_request") as mock_handler, \
                patch("app.api.chat.SessionMemory",
                      return_value=_memory(get_session=_session(status="closed"))):
            with pytest.raises(HTTPException) as e:
                await send_message(
                    ChatSendRequest(session_id="sess_1", message=_QUESTION), current_user=_merchant(),
                )
        assert e.value.status_code == 409
        assert e.value.detail["error"]["code"] == "SESSION_CLOSED"
        mock_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_client_supplied_role_and_snapshot_are_ignored(self) -> None:
        """越权面：payload 里的 role / permissions / 实体快照**一律不读**（角色只从会话取）。"""
        message = await _run_handler(
            _req(
                f"/orders/{UUID}", UUID, role="admin", permissions=["*"],
                entitySnapshot={"customerName": "张三", "phone": "13800138000"},
            ),
            _merchant(permissions=("order:list",)),  # 有页面读码、**无** order:detail
        )
        assert "customerName" not in message
        assert "13800138000" not in message
        assert "entitySnapshot" not in message
        # ⚠️ 不能用 `UUID not in message` 断言裁剪 —— UUID 同时是**路径**的一段。
        # 判「实体 id 字段被裁剪」只能认注入文本里的**对象行**：
        assert "对象 id：" not in message, "缺对象读码却把实体 id 注入了（客户端自称的 admin 被采信）"
        assert f"/orders/{UUID}" in message, "页面级上下文应当仍在（有 order:list）"

    @pytest.mark.asyncio
    async def test_c_end_caller_gets_no_context(self) -> None:
        message = await _run_handler(_req("/orders/123", "12345", role="admin"), _customer())
        assert message == PR.PAGE_CONTEXT_UNKNOWN_NOTICE + _QUESTION
        assert "/orders/123" not in message

    @pytest.mark.asyncio
    async def test_malformed_payload_degrades_to_notice(self) -> None:
        """畸形 payload（非字符串 route / 带查询串 / 路径穿越）⇒ 一律按「未登记」处理。"""
        for payload in (
            {"route": 123},
            {"route": None},
            {"route": "/orders/%E5%BC%A0%E4%B8%89"},
            {"route": "/orders/../etc/passwd"},
            {"route": "orders/123"},
            {},
        ):
            req = ChatSendRequest(session_id="sess_1", message=_QUESTION, page_context=payload)
            message = await _run_handler(req, _merchant())
            assert message == PR.PAGE_CONTEXT_UNKNOWN_NOTICE + _QUESTION, f"畸形 payload 被注入了：{payload}"

    @pytest.mark.asyncio
    async def test_closed_session_blocked(self) -> None:
        from app.api.chat import _handle_page_ctx_request
        with patch("app.api.chat.send_message", new=AsyncMock()) as mock_send, \
                patch("app.api.chat.SessionMemory",
                      return_value=_memory(get_session=_session(status="closed"))):
            with pytest.raises(HTTPException) as e:
                await _handle_page_ctx_request(
                    _req("/orders/123", "12345"),
                    tenant_id=1, user_id="user_1", current_user=_merchant(),
                )
        assert e.value.status_code == 409
        assert e.value.detail["error"]["code"] == "SESSION_CLOSED"
        mock_send.assert_not_awaited()