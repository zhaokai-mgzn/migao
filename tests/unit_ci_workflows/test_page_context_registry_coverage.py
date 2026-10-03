# case_ids: MC-075
"""B 端米宝页面上下文（族 4）的**登记收敛元守卫**（issue #6215）—— `menu.ts` 的 route 集合
⇄ `PAGE_REGISTRY ∪ 豁免台账` **双向相等**，且登记项自证（真值源在册 / 路径存在 / 权限码真实）。

## 病（本单要治的形态）

族 4 的登记表在 #5371 起有 **6** 条 route，而 `frontend/admin-web/src/config/menu.ts` 有 **22** 个菜单页
⇒ 用户在其余 **16** 个页面上问「这一页是干什么的 / 这个数怎么算的」时，`build_page_context` 走
**默认拒绝**（这是**有意**的安全默认）⇒ 米宝只能回「我不确定你在哪一页」。
病根不是「默认拒绝错了」，而是 **`route → 真值源` 的覆盖没有任何东西在管**：

- 登记表少一条 = 用户得不到解释，而**没有任何判据会红**（漏登记的形态是**沉默**）；
- 反方向也判不了：登记一条**不存在**的 route / 引用一份**不存在**的真值源（#5371 的
  `tests/unit_ci_workflows/test_page_context_registry.py` 只核登记表**自证**，不核**覆盖面**）；
- 「暂不覆盖」**只活在代码里没有的东西**（登记表里少一条）⇒ 看不出是有意为之、也看不出欠了什么。

## 判据（每条都能单独变红；判别力自证见 `test_discriminating_power_*`）

| # | 判据 | 语义 / 变红的形态 |
|---|---|---|
| 0 | **静态前置**：`menu.ts` 解析出非空 route 集、`page_registry.py` 由 AST 取到字面量、台账 `exemptions` 非空 | 任一为空 ⇒ 红（**fail-closed**：「没东西可判」不是通过） |
| 1 | 🔴 **漏登记即红**（本单的牙齿） | 菜单有、登记表与台账**都没有** ⇒ 红（具名报出该 route） |
| 2 | 🔴 **多登记 / 悬挂即红** | 登记表或台账里有、**挂不到任何菜单项**的 route ⇒ 红（登记了不存在的页面 = 猜错页面） |
| 3 | **登记 ⇄ 台账互斥** | 同一条 route 既在 `PAGE_REGISTRY` 又在豁免台账 ⇒ 红（豁免台账只许缩短） |
| 4 | 🔴 **只许缩短**（两处冻结） | 台账 `exempt_routes_frozen` ⇄ `exemptions` 的 route 集**逐项相等**；条数 ≤ `EXEMPT_COUNT_MAX` 且 == `baseline_frozen` ⇒ 想「把新页塞进豁免」必须同时改三处 |
| 5 | **真值源在册** | 登记项的 `truth_source` ∉ `TRUTH_SOURCES` ⇒ 红（未登记即不生效） |
| 6 | **真值源 `path` 真实存在** | 路径不在仓里 ⇒ 红（不许把「编的解释」伪装成真值源） |
| 7 | **权限码真实存在** | 页面级 / 对象级码不在 admin-api 权限目录 ⇒ 红（复用既有对账守卫的解析器，**不造第二套**） |
| 8 | **台账每条写清为什么 + 重启条件** | `reason` / `restart_condition` 缺或为空 ⇒ 红（缺口不许匿名存在） |
| 9 | 🔴 **判别力自证**（注入式红证，内存里对各判据本体变异） | 摘一条登记 route / 加一条豁免 / 造悬挂 route / 造幽灵真值源 / 造幽灵权限码 / 只加注释 ⇒ **各自判红与否如预期** |

## 为什么判据长这样（三条硬约束，逐条都踩过）

- 🔴 **纯静态、零 ai-agent 依赖**：CI 的 `ci workflow helper unit tests` 这个 job **只装 `pytest` + `pyyaml`**
  ⇒ 本文件**不得** `import app.*`（`app.context.page_registry` 会经 `app.tools.base` 拉 pydantic + 环境变量，
  实测会让该 job 直接红，见 `tests/unit_ci_workflows/test_proactive_onboarding.py` 的同款注记）。
  ⇒ `page_registry.py` 的登记表用 **`ast` 取模块级字面量**（判据 0 自证取到了），
  `menu.ts` / 权限目录**复用** `tests/unit_ci_workflows/test_agent_permission_parity.py` 的解析器
  （**不造第二个解析器**）。
- 🔴 **判据本体是纯函数**（输入 = 现取语料），注入式红证直接在**内存**里换输入 ⇒ 不动仓内文件、
  判据与红证同批跑（`migao-dev-flow` §23 G7 的前提自证）。
- 🔴 **不写死任何条数**：条数一律**现取**（`len(...)`），只与**冻结快照**比 ——
  「现取多少个页面」是读数，不是常量（写死会在下一次菜单变更时变成假红）。

## 明确不在本文件射程（照实登记）

- **行为面**（真跑 `build_page_context` / 真注入 / 真拒绝）：`backend/ai-agent-service/tests/test_page_context.py`；
- **LLM 是否按真值源解释**：`.github/cases/chat.yml` 的 CH 用例（本轮**不跑**真实 LLM 评测，
  按 issue #4262 的用户裁定：手动集中跑一次）；
- **「这份文档真的是这一页的口径」**：那是**判断**（锚点逐条写在 PR body），
  本判据只核「登记项自证 + 覆盖面双向相等」；覆盖面边界逐条登记在台账 `coverage_boundary`。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / ".github" / "cases").is_dir()
)
MENU_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "config" / "menu.ts"
PAGE_REGISTRY_PY = (
    REPO_ROOT / "backend" / "ai-agent-service" / "app" / "context" / "page_registry.py"
)
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
LEDGER_PATH = Path(__file__).with_name("page_context_exemptions_ledger.json")
REGISTRATION_SERVICE = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
    / "admin" / "service" / "RegistrationService.java"
)
PERMISSION_SERVICE = (
    REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
    / "admin" / "service" / "PermissionService.java"
)

#: 豁免条数上限（**只许缩短**）：与台账 `baseline_frozen` **两处一致**才放行。
#: ⚠️ 这不是「页面数」——它是**豁免**条数（菜单页总数永远现取）。
EXEMPT_COUNT_MAX = 13
#: 覆盖面（`coverage_boundary`）条数上限（同上：只许缩短；与台账 `coverage_boundary_frozen` 两处一致）。
COVERAGE_BOUNDARY_COUNT_MAX = 4

#: 台账每条豁免必须带的键（缺一 ⇒ 红：「缺口不许匿名存在」）。
EXEMPTION_KEYS = ("route", "reason", "restart_condition")
#: 覆盖面登记每条必须带的键（与 `schedule_scope_ledger.json` 同口径）。
BOUNDARY_KEYS = ("face", "reason", "recompute")

#: 断言模式名（判别力自证的靶子）——`problems_*` 是可注入的纯函数。
ProblemFn = Callable[..., List[str]]


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取（唯一来源 = 真文件；判据吃的是**现取对象 + 可注入的台账/登记表**）
# ══════════════════════════════════════════════════════════════════════════════


def _load_parity_module() -> Any:
    """按路径加载对账守卫模块（`menu.ts` / 权限目录解析器的**同一个**实现）。"""
    name = "migao_parity_for_page_ctx_coverage"
    if name in sys.modules:
        return sys.modules[name]
    assert PARITY_GUARD.is_file(), f"被判据复用的解析器不存在：{PARITY_GUARD}（路径漂移 ⇒ 红）"
    sys.path.append(str(REPO_ROOT / "tests"))
    spec = importlib.util.spec_from_file_location(name, PARITY_GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def menu_routes() -> List[str]:
    """`menu.ts` 的**导航 route 集**（组头无 `path` ⇒ 不产出；复用既有解析器）。"""
    parity = _load_parity_module()
    assert MENU_TS.is_file(), f"菜单单一源不存在：{MENU_TS}（路径漂移 ⇒ 红，不得静默跳过）"
    nodes = parity.parse_menu_ts_nodes(MENU_TS.read_text(encoding="utf8"))
    routes = [n.path for n in nodes if n.path]
    assert routes, "menu.ts 解析出 0 个 route ⇒ 判据会空跑（fail-closed）"
    return routes


def permission_catalog() -> Set[str]:
    """admin-api 权限目录（两处）—— **复用既有对账守卫的解析器**，不造第二套。"""
    parity = _load_parity_module()
    for path in (REGISTRATION_SERVICE, PERMISSION_SERVICE):
        assert path.is_file(), f"权限目录文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    reg, perm = parity.parse_catalog(
        REGISTRATION_SERVICE.read_text(encoding="utf8"),
        PERMISSION_SERVICE.read_text(encoding="utf8"),
    )
    catalog = set(reg) | set(perm)
    assert catalog, "权限目录解析出 0 条 ⇒ 判据会空跑（fail-closed）"
    return catalog


def _module_assignment(tree: ast.Module, var_name: str) -> Optional[ast.AST]:
    """模块级 `var_name = <表达式>` 的**值节点**（取不到 ⇒ `None` ⇒ 调用方 fail-closed）。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        else:
            continue
        if var_name in targets:
            return node.value
    return None


def _literal_kwargs(call: ast.AST) -> Optional[Dict[str, Any]]:
    """`SomeDataclass(route="…", …)` 的**字面量关键字参数**（有一个非字面量 ⇒ `None`）。"""
    if not isinstance(call, ast.Call):
        return None
    if call.args:  # 位置参数 ⇒ 形态漂移（登记项一律用关键字）⇒ fail-closed
        return None
    out: Dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            return None
        try:
            out[kw.arg] = ast.literal_eval(kw.value)
        except ValueError:
            return None
    return out


def parse_registry() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """静态解析 `page_registry.py` ⇒ `(PAGE_REGISTRY 条目, {真值源 id: path})`。

    ⚠️ 这是**静态**解析（AST 取 `PageEntry(...)` / `TruthSource(...)` 的**字面量关键字实参**），
    不是 import 运行时模块（理由见模块 docstring：CI 的 helper job 装不了 pydantic）。
    登记表被改写成非字面量形态（循环构造 / 变量拼接 / 位置参数）⇒ 这里取不到 ⇒
    判据 0 **fail-closed 判红**（不是静默放过）。
    """
    assert PAGE_REGISTRY_PY.is_file(), f"登记表文件不存在：{PAGE_REGISTRY_PY}（路径漂移 ⇒ 红）"
    tree = ast.parse(PAGE_REGISTRY_PY.read_text(encoding="utf8"))

    entries: List[Dict[str, Any]] = []
    raw_entries = _module_assignment(tree, "PAGE_REGISTRY")
    if isinstance(raw_entries, (ast.Tuple, ast.List)):
        for item in raw_entries.elts:
            kwargs = _literal_kwargs(item)
            if kwargs is not None:
                entries.append(kwargs)

    sources: Dict[str, str] = {}
    raw_sources = _module_assignment(tree, "TRUTH_SOURCES")
    if isinstance(raw_sources, ast.Dict):
        for key_node, value_node in zip(raw_sources.keys, raw_sources.values):
            try:
                key = ast.literal_eval(key_node)
            except ValueError:
                continue
            kwargs = _literal_kwargs(value_node)
            if isinstance(key, str) and kwargs and isinstance(kwargs.get("path"), str):
                sources[key] = kwargs["path"]
    return entries, sources


def load_ledger() -> Dict[str, Any]:
    assert LEDGER_PATH.is_file(), f"豁免台账不存在：{LEDGER_PATH}（路径漂移 ⇒ 红）"
    return json.loads(LEDGER_PATH.read_text(encoding="utf8"))


def _routes_of(entries: Sequence[Dict[str, Any]]) -> List[str]:
    return [str(e.get("route", "")) for e in entries]


def registered_routes(entries: Sequence[Dict[str, Any]]) -> List[str]:
    return _routes_of(entries)


def exempt_routes(ledger: Dict[str, Any]) -> List[str]:
    return _routes_of(ledger.get("exemptions") or [])


def covers(registry_route: str, menu_path: str) -> bool:
    """登记条目 ⇄ 菜单项：**精确相等** / **通配整族**（`/orders/*` ↔ `/orders`）/ **子路由**。

    - 精确：`/dashboard` ⇄ `/dashboard`；
    - 通配：`/orders/*` 登记的是「`/orders` 这一族」（含列表页本身；与既有的 `/products/*` 同式）；
    - 子路由：`/orders/new` / `/production/routings` 挂在菜单项 `/orders` / `/production` 之下
      （它们在运行时确实会被 `resolve_page_entry` 命中，只是**不是**独立菜单项）。
    """
    if registry_route == menu_path:
        return True
    if registry_route.endswith("/*"):
        return registry_route[:-2] == menu_path
    return registry_route.startswith(menu_path + "/")


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（**纯函数**：真语料与注入语料走同一份判据 —— §28.2「判据绿 ≠ 接线在」）
# ══════════════════════════════════════════════════════════════════════════════


def problems_corpus_is_nonempty(
    menu: Sequence[str],
    entries: Sequence[Dict[str, Any]],
    sources: Dict[str, str],
    ledger: Dict[str, Any],
    catalog: Set[str],
) -> List[str]:
    """判据 0：语料非空（fail-closed：「没东西可判」不是通过）。"""
    out: List[str] = []
    if not menu:
        out.append("menu.ts 的 route 集为空 ⇒ 判据会空跑")
    if not entries:
        out.append("PAGE_REGISTRY 静默为空（AST 取不到字面量？）⇒ 判据会空跑")
    if not sources:
        out.append("TRUTH_SOURCES 静默为空（AST 取不到字面量？）⇒ 判据会空跑")
    if not exempt_routes(ledger):
        out.append("豁免台账 `exemptions` 为空 ⇒ 判据会空跑（且与「只许缩短」的口径不符）")
    if not catalog:
        out.append("权限目录为空 ⇒ 判据会空跑")
    return out


def problems_coverage(
    menu: Sequence[str],
    entries: Sequence[Dict[str, Any]],
    ledger: Dict[str, Any],
    **_: Any,
) -> List[str]:
    """判据 1/2：`menu.ts` ⇄ `PAGE_REGISTRY ∪ 豁免台账` 的**双向相等**。

    - 菜单有、两边都没有 ⇒ **漏登记**（红）；
    - 登记表 / 台账里有、挂不到任何菜单项 ⇒ **多登记 / 悬挂**（红）。
    """
    out: List[str] = []
    reg = registered_routes(entries)
    exc = exempt_routes(ledger)
    for path in menu:
        if any(covers(r, path) for r in reg):
            continue
        if path in exc:
            continue
        out.append(
            f"菜单页 `{path}` **既没登记也没豁免** —— 米宝在这一页拿不到任何页面上下文"
            "（漏登记的形态是沉默：要么登记真值源，要么进 `tests/unit_ci_workflows/"
            "page_context_exemptions_ledger.json` 具名豁免）"
        )
    for route in reg + exc:
        if not any(covers(route, path) for path in menu):
            out.append(
                f"`{route}` 在{'登记表' if route in reg else '豁免台账'}里，但**挂不到任何菜单项**"
                " —— 登记一条不存在的页面 = 猜错页面（悬挂登记必须删掉）"
            )
    return out


def problems_registry_and_ledger_are_disjoint(
    entries: Sequence[Dict[str, Any]], ledger: Dict[str, Any], **_: Any
) -> List[str]:
    """判据 3：同一条 route 不许既登记又豁免（豁免台账只许缩短）。"""
    both = sorted(set(registered_routes(entries)) & set(exempt_routes(ledger)))
    if both:
        return [f"`{r}` 同时在 PAGE_REGISTRY 与豁免台账里 ⇒ 删掉豁免那条（豁免只许缩短）" for r in both]
    return []


def problems_ledger_shrinks_only(
    ledger: Dict[str, Any], entries: Sequence[Dict[str, Any]] | None = None, **_: Any
) -> List[str]:
    """判据 4：豁免台账**只许缩短**（冻结快照 ⇄ 现取条数/集合，两处一致）。"""
    out: List[str] = []
    frozen = ledger.get("exempt_routes_frozen")
    baseline = ledger.get("baseline_frozen")
    current = exempt_routes(ledger)
    if not isinstance(frozen, list) or not isinstance(baseline, int):
        return ["豁免台账缺 `exempt_routes_frozen` / `baseline_frozen` ⇒ 冻结面读不到（fail-closed）"]
    if sorted(current) != sorted(str(x) for x in frozen):
        only_frozen = sorted(set(map(str, frozen)) - set(current))
        only_current = sorted(set(current) - set(map(str, frozen)))
        out.append(
            "豁免台账的冻结快照与现取条目不一致（**只许缩短**：只删不改名；"
            f"新增必须同批改三处）—— 只在快照={only_frozen}；只在现取={only_current}"
        )
    if len(current) > EXEMPT_COUNT_MAX or len(current) != baseline:
        out.append(
            f"豁免条数现取 {len(current)} ≠ 台账 `baseline_frozen` {baseline}"
            f"（判据侧上限 {EXEMPT_COUNT_MAX}）—— 条数**只许缩短**：删一条豁免时三处一起改小"
        )
    return out


def problems_truth_sources_are_registered(
    entries: Sequence[Dict[str, Any]], sources: Dict[str, str], **_: Any
) -> List[str]:
    """判据 5/6：登记项的 `truth_source` 必须在册，且它的 `path` **真实存在**。

    外加**反向**一条（同族：`test_menu_navigator.py` 的「没有空登记（死条目）」）：
    `TRUTH_SOURCES` 里**没有任何登记项引用**的条目 ⇒ 红（死条目：表里躺着一份谁也不用的口径，
    下一个人会以为它是活的）。
    """
    out: List[str] = []
    used: Set[str] = set()
    for entry in entries:
        route = entry.get("route")
        ts = entry.get("truth_source")
        if ts not in sources:
            out.append(
                f"`{route}` 引用了未登记的真值源 `{ts}` ⇒ 该条目**不生效**（fail-closed，"
                "米宝仍拿不到这一页的口径）"
            )
            continue
        used.add(str(ts))
        path = sources[str(ts)]
        if not (REPO_ROOT / path).is_file():
            out.append(f"真值源 `{ts}` 的 path 不存在：`{path}`（不许把「编的解释」伪装成真值源）")
    for ts in sorted(set(sources) - used):
        out.append(f"真值源 `{ts}` **没有任何登记项引用**（死条目）—— 留着它只会让人以为它是活的")
    return out


def problems_permission_codes_are_real(
    entries: Sequence[Dict[str, Any]], catalog: Set[str], **_: Any
) -> List[str]:
    """判据 7：登记表的页面级 / 对象级权限码必须是**真存在**的码（逐值核）。"""
    out: List[str] = []
    declared = 0
    for entry in entries:
        route = entry.get("route")
        for key in ("page_permissions", "entity_permissions"):
            for code in entry.get(key) or ():
                declared += 1
                if code not in catalog:
                    out.append(
                        f"`{route}` 的 {key} 里的 `{code}` 不在 admin-api 权限目录里"
                        "（零命中的想象码 ⇒ 这条 route 对所有人恒不可见）"
                    )
    if not declared:
        out.append("登记表没有声明任何权限码 ⇒ 判据 7 会空跑（fail-closed）")
    return out


def problems_ledger_entries_documented(ledger: Dict[str, Any], **_: Any) -> List[str]:
    """判据 8：台账每条豁免必须写清 `reason`（为什么不登记）与 `restart_condition`（重启条件）。"""
    out: List[str] = []
    for entry in ledger.get("exemptions") or []:
        if not isinstance(entry, dict):
            out.append(f"豁免条目不是对象：{entry!r}")
            continue
        route = entry.get("route", "<缺 route>")
        for key in EXEMPTION_KEYS:
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                out.append(f"豁免 `{route}` 缺 `{key}`（或为空）—— 缺口不许匿名存在")
    # 只多不少：多余键不判红（台账允许补充元数据），但**不许少键**。
    return out


def problems_coverage_boundary_documented(ledger: Dict[str, Any], **_: Any) -> List[str]:
    """判据 9：覆盖面缺口必须逐条登记（`face` / `reason` / `recompute`），且**条数冻结**。

    条数冻结的理由：只判「每条非空」的话，**删掉一整条覆盖面登记不会红**（本判据的红证曾经
    空跑过一次，实测读数见 PR body）⇒ 与 `schedule_scope_ledger.json` 的 `coverage_boundary`
    同口径：条数**现取**，只与台账自己的 `coverage_boundary_frozen` 比（**只许缩短**）。
    """
    out: List[str] = []
    boundary = ledger.get("coverage_boundary")
    if not isinstance(boundary, list) or not boundary:
        return ["豁免台账缺 `coverage_boundary`（覆盖面缺口不许匿名存在）"]
    for item in boundary:
        if not isinstance(item, dict):
            out.append(f"`coverage_boundary` 条目不是对象：{item!r}")
            continue
        missing = [k for k in BOUNDARY_KEYS if not str(item.get(k) or "").strip()]
        if missing:
            out.append(f"`coverage_boundary` 条目缺键 {missing}：{item.get('face', '<无 face>')}")
    frozen = ledger.get("coverage_boundary_frozen")
    if not isinstance(frozen, int):
        out.append("台账缺 `coverage_boundary_frozen` ⇒ 覆盖面条数判不了（fail-closed）")
    elif len(boundary) != frozen:
        out.append(
            f"覆盖面登记条数现取 {len(boundary)} ≠ `coverage_boundary_frozen` {frozen}"
            " —— 只许缩短（删一条时两个数一起改小；不许**默默删掉**一条缺口登记）"
        )
    if len(boundary) > COVERAGE_BOUNDARY_COUNT_MAX:
        out.append(f"覆盖面登记条数 {len(boundary)} > 判据侧上限 {COVERAGE_BOUNDARY_COUNT_MAX}")
    return out


PROBLEM_SETS: Dict[str, ProblemFn] = {
    "corpus_is_nonempty": problems_corpus_is_nonempty,
    "coverage": problems_coverage,
    "registry_and_ledger_are_disjoint": problems_registry_and_ledger_are_disjoint,
    "ledger_shrinks_only": problems_ledger_shrinks_only,
    "truth_sources_are_registered": problems_truth_sources_are_registered,
    "permission_codes_are_real": problems_permission_codes_are_real,
    "ledger_entries_documented": problems_ledger_entries_documented,
    "coverage_boundary_documented": problems_coverage_boundary_documented,
}


#: 现取语料（模块级：判据与对照读数用**同一份**）。
MENU_ROUTES: Tuple[str, ...] = tuple(menu_routes())
PAGE_ENTRIES, TRUTH_PATHS = parse_registry()
LEDGER = load_ledger()
CATALOG: Set[str] = permission_catalog()


def _run_all(
    menu: Sequence[str] | None = None,
    entries: Optional[Sequence[Dict[str, Any]]] = None,
    sources: Optional[Dict[str, str]] = None,
    ledger: Optional[Dict[str, Any]] = None,
    catalog: Optional[Set[str]] = None,
) -> Dict[str, List[str]]:
    """跑全部判据（缺省 = 现取语料；注入式红证只换其中一项）。"""
    kw: Dict[str, Any] = {
        "menu": MENU_ROUTES if menu is None else menu,
        "entries": PAGE_ENTRIES if entries is None else entries,
        "sources": TRUTH_PATHS if sources is None else sources,
        "ledger": LEDGER if ledger is None else ledger,
        "catalog": CATALOG if catalog is None else catalog,
    }
    return {name: fn(**kw) for name, fn in PROBLEM_SETS.items()}


# ══════════════════════════════════════════════════════════════════════════════
# 三、实例判据（全绿 + 现取读数）
# ══════════════════════════════════════════════════════════════════════════════


def test_all_judgements_are_green(capsys) -> None:
    """八条判据全绿 —— 并**打印现取读数**（绿得没有计数 = 未跑）。"""
    results = _run_all()
    for name, problems in results.items():
        assert not problems, f"判据 `{name}` 判红：\n" + "\n".join(f"  {p}" for p in problems)
    reg = registered_routes(PAGE_ENTRIES)
    covered = [p for p in MENU_ROUTES if any(covers(r, p) for r in reg)]
    with capsys.disabled():
        print(
            f"[页面上下文覆盖] 菜单页={len(MENU_ROUTES)} 条 / PAGE_REGISTRY={len(reg)} 条"
            f"（覆盖菜单页 {len(covered)} 条）/ 豁免台账={len(exempt_routes(LEDGER))} 条"
            f"（上限 {EXEMPT_COUNT_MAX}）/ 真值源={len(TRUTH_PATHS)} 条 / 权限目录现取={len(CATALOG)} 码"
        )


def test_static_ast_actually_reads_the_registry() -> None:
    """判据 0 的**接线自证**：AST 静态解析真的取到了字面量（否则判据是空跑）。"""
    assert PAGE_ENTRIES, "AST 取不到 PAGE_REGISTRY 字面量 ⇒ 判据 1/2/5/6/7 全是空跑"
    assert TRUTH_PATHS, "AST 取不到 TRUTH_SOURCES 字面量 ⇒ 判据 5/6 是空跑"
    assert all(isinstance(e.get("route"), str) and e["route"] for e in PAGE_ENTRIES)
    assert all(isinstance(e.get("truth_source"), str) for e in PAGE_ENTRIES)


def test_menu_route_corpus_is_not_hardcoded() -> None:
    """现取自证：菜单 route 集来自 `menu.ts`（**不是**本文件写死的清单）。"""
    assert len(MENU_ROUTES) == len(set(MENU_ROUTES)), f"menu.ts 出现重复 route：{MENU_ROUTES}"
    source = MENU_TS.read_text(encoding="utf8")
    missing = [r for r in MENU_ROUTES if f"path: '{r}'" not in source]
    assert not missing, f"这些 route 不是从 menu.ts 的 `path:` 现取来的：{missing}"


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（§23 G7：每条**先自证注入生效**，再判它真会红）
# ══════════════════════════════════════════════════════════════════════════════


def test_red_proof_dropping_a_registered_route_reports_it() -> None:
    """🔴 **实例红证**：把某条已登记 route 从 `PAGE_REGISTRY` 摘掉 ⇒ 判红并**具名**报出该 route。"""
    victim = "/production/piecework"
    assert victim in registered_routes(PAGE_ENTRIES), "前提自证：该 route 本来在登记表里"
    injected = [e for e in PAGE_ENTRIES if e.get("route") != victim]
    assert len(injected) == len(PAGE_ENTRIES) - 1, "注入未生效（自证）：登记表没变短"
    problems = _run_all(entries=injected)["coverage"]
    assert problems, f"摘掉 `{victim}` 后仍然判绿 ⇒ 漏登记这条判据没有判别力"
    assert any(victim in p for p in problems), f"判红但**没有具名**报出 `{victim}`：{problems}"


def test_red_proof_adding_an_exemption_goes_red() -> None:
    """🔴 **台账红证**：往豁免台账加一条 ⇒ 判红（只许缩短）。"""
    extra = {"route": "/not-a-real-page", "reason": "临时注入", "restart_condition": "临时注入"}
    injected = dict(LEDGER)
    injected["exemptions"] = list(LEDGER["exemptions"]) + [extra]
    assert len(injected["exemptions"]) == len(LEDGER["exemptions"]) + 1, "注入未生效（自证）"
    results = _run_all(ledger=injected)
    assert results["ledger_shrinks_only"], "加了豁免却仍然判绿 ⇒ 「只许缩短」没有判别力"
    assert results["coverage"], "加了悬挂豁免却仍然判绿 ⇒ 判据 2 没有判别力"
    assert any("/not-a-real-page" in p for p in results["coverage"]), "判红但没有具名报出该 route"


def test_red_proof_dangling_registry_route_goes_red() -> None:
    """判据 2 红证：登记一条**菜单里没有**的 route ⇒ 判红（多登记 / 悬挂）。"""
    injected = list(PAGE_ENTRIES) + [
        {"route": "/ghost-page", "truth_source": "order-amount",
         "page_permissions": [], "entity_permissions": []}
    ]
    assert len(injected) == len(PAGE_ENTRIES) + 1, "注入未生效（自证）"
    problems = _run_all(entries=injected)["coverage"]
    assert problems and any("/ghost-page" in p for p in problems), \
        f"悬挂登记没被判红（或没具名）：{problems}"


def test_red_proof_ghost_truth_source_goes_red() -> None:
    """判据 5/6 红证：未登记的真值源 id / 不存在的真值源 path ⇒ 判红。"""
    ghost_id = list(PAGE_ENTRIES)
    ghost_id[0] = dict(ghost_id[0], truth_source="ghost-source")
    r5 = _run_all(entries=ghost_id)["truth_sources_are_registered"]
    assert r5 and any("ghost-source" in p for p in r5), f"幽灵真值源没判红：{r5}"

    ghost_path = dict(TRUTH_PATHS)
    # 必须挑一条**真的被某个登记项引用**的真值源（否则判据 5 先命中 `continue`，判据 6 根本跑不到）
    used = sorted({str(e["truth_source"]) for e in PAGE_ENTRIES})
    assert used, "前提自证：登记表引用了真值源"
    ghost_path[used[0]] = "docs/does-not-exist-6215.md"
    assert ghost_path != TRUTH_PATHS, "注入未生效（自证）"
    r6 = _run_all(sources=ghost_path)["truth_sources_are_registered"]
    assert r6 and any("does-not-exist-6215" in p for p in r6), f"幽灵 path 没判红：{r6}"

    # 反向：表里多一条**没人引用**的真值源 ⇒ 红（死条目）
    dead = dict(TRUTH_PATHS, dead_source="docs/curtain-production-rules.md")
    assert dead != TRUTH_PATHS, "注入未生效（自证）"
    r7 = _run_all(sources=dead)["truth_sources_are_registered"]
    assert r7 and any("dead_source" in p for p in r7), f"死条目真值源没判红：{r7}"


def test_red_proof_ghost_permission_code_goes_red() -> None:
    """判据 7 红证：登记一个**权限目录里没有**的码 ⇒ 判红。"""
    injected = list(PAGE_ENTRIES)
    injected[0] = dict(injected[0], page_permissions=("ghost:code",))
    problems = _run_all(entries=injected)["permission_codes_are_real"]
    assert problems and any("ghost:code" in p for p in problems), f"幽灵权限码没判红：{problems}"


def test_red_proof_undocumented_exemption_goes_red() -> None:
    """判据 8 红证：豁免条目缺 `reason` / `restart_condition` ⇒ 判红。"""
    injected = dict(LEDGER)
    entries = [dict(e) for e in LEDGER["exemptions"]]
    entries[0]["reason"] = "   "
    del entries[1]["restart_condition"]
    injected["exemptions"] = entries
    problems = _run_all(ledger=injected)["ledger_entries_documented"]
    assert len(problems) >= 2, f"缺 reason / restart_condition 没逐条判红：{problems}"


def test_red_proof_deleting_boundary_entry_goes_red() -> None:
    """判据 9 红证：删掉任意一条覆盖面登记 ⇒ 判红（缺口不许匿名存在）。"""
    injected = dict(LEDGER)
    injected["coverage_boundary"] = list(LEDGER["coverage_boundary"])[:-1]
    assert len(injected["coverage_boundary"]) == len(LEDGER["coverage_boundary"]) - 1, \
        "注入未生效（自证）"
    problems = _run_all(ledger=injected)["coverage_boundary_documented"]
    assert problems, "删掉覆盖面登记仍判绿 ⇒ 该判据没有判别力"


def test_control_comment_only_change_is_green() -> None:
    """🔴 **对照读数**：只往 `page_registry.py` / 台账**加注释与键** ⇒ **不红**。

    为什么必须有这条：判别力自证不能靠「注入什么都红」——那样判据可能只是被自己的文案喂红
    （`migao-dev-flow` §17.3）。本用例在**内存里**给登记项加一个无关元数据键、给台账加一个说明键，
    判据必须**全绿**。
    """
    injected_entries = [dict(e, __note__="只加一个无关元数据键（不改 route / 真值源 / 权限码）")
                        for e in PAGE_ENTRIES]
    injected_ledger = dict(LEDGER, ledger_note="只加一句说明，不动 exemptions")
    assert injected_entries != list(PAGE_ENTRIES), "注入未生效（自证）"
    results = _run_all(entries=injected_entries, ledger=injected_ledger)
    for name, problems in results.items():
        assert not problems, f"只加了注释/元数据，判据 `{name}` 却判红：{problems}"


def test_this_judgement_is_pure_static_and_never_skips() -> None:
    """纯静态自证：不 import `app.*` / 不用 skip 类针脚（CI 的 helper job 只装 pytest + pyyaml）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf8"))
    imported: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [m for m in imported if m.split(".")[0] == "app"], \
        f"本判据 import 了 ai-agent 运行时依赖：{sorted(imported)}"
    src = Path(__file__).read_text(encoding="utf8")
    # ⚠️ 针脚必须**拼出来**：直接写整串会让本判据扫到自己 ⇒ 永远红（同款踩过的先例见本仓既有守卫）
    for needle in ("pytest" + "." + "skip", "importor" + "skip"):
        assert needle not in src, f"判据里出现 `{needle}`（会让它在 CI 里空跑成绿）"
