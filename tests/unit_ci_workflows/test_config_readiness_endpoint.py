# case_ids: MC-189
"""「配置就绪度端点」的**跨仓一致性**守卫（issue #6579）。

## 病根（这个端点的三个"第二份会很贵"的地方）

`GET /api/admin/config-readiness` 是**聚合器**：它把七个既有读面的事实收成一份响应，
前端据此画出配置主线。这种「一个端点 + 一份事实 + 七个来源」的形状有三个天然漂移点，
每一处都**不会有任何东西变红**：

1. **权限码**：端点的码必须 = 该页第一屏读码 = 菜单节点码 = 路由守卫码（#6573 已定「不新造码」）。
   若它悄悄变成别的码（或退回类级声明），「菜单看得见、点进去 403」就有了显形条件。
2. **跨码步骤的码**：`remnant-sizes` 是否出现，取决于调用方**是否持余料尺寸读面的那个码**。
   这个码在三处出现（本服务常量 / `RemnantController` 的类级声明 / 前端域目录的 `requiredCode`）
   —— 任何一处单独改动，「不持码就给数」或「持码反而不给数」都**不会红**。
3. **两条基础路线名 + 七步的 href**：服务端把它们当"事实"给出去，前端 `MAINLINE_STEPS` 也各有一份。
   两处改一处就是「同一屏两套口径」，而且照样绿。

## 判据（每条都带注入式红证）

| # | 判据 | 红证（本文件内**真的跑一遍**） |
|---|---|---|
| 1 | 端点方法级 `@RequirePermission("production:view")`，**类级不许有** | 改成类级 / 换码 / 删注解 ⇒ 必须报出 |
| 2 | 服务是**聚合器**：零 Mapper、零 SQL、零三态字面量，且八处既有读面的委派一个不少 | 注入 `Mapper` / 删一处委派 / 注入 `"done"` ⇒ 必须报出 |
| 3 | 跨码步骤的码三处同值 | 改其中一处 ⇒ 必须报出并**点名是哪一处** |
| 4 | 两条基础路线名 Java / TS / 引擎三处同值 | 改一处 ⇒ 必须报出 |
| 5 | 七步的 `href` 与前端主线逐值相等 | 改一个 href / 少一步 ⇒ 必须报出 |
| 6 | 前端**只发这一个请求**画主线：页面调聚合端点、且不再调那五个旧读面；三态翻译走 `statesFromFacts` | 把任一旧读面调回页面 / 删掉聚合调用 ⇒ 必须报出 |

## 边界（如实登记，§19.1）

- 它判**接线与同值**，不判口径正确性（孤儿工序怎么数在
  `ConfigReadinessServiceTest` 的夹具里判，三态怎么判在 `config-readiness.test.ts` 里判）。
- 「页面真的只发一个请求」这一半由 `settings.test.tsx` 的运行时判据承重（本文件只判源码面
  有没有**多出来的调用**，run-time 的请求计数不在这里）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JAVA_MAIN = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
CONTROLLER = JAVA_MAIN / "controller" / "ConfigReadinessController.java"
SERVICE = JAVA_MAIN / "service" / "ConfigReadinessService.java"
REMNANT_CONTROLLER = JAVA_MAIN / "controller" / "RemnantController.java"

WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
READINESS_TS = WEB_SRC / "lib" / "config-readiness.ts"
DOMAINS_TS = WEB_SRC / "lib" / "config-center-domains.ts"
API_MODULE_TS = WEB_SRC / "lib" / "api-config-readiness.ts"
TYPES_TS = WEB_SRC / "types" / "config-readiness.ts"
SETTINGS_PAGE = WEB_SRC / "app" / "(dashboard)" / "settings" / "page.tsx"

#: 算料引擎里的两条基础路线名（**第三处**真值源：Java 无法 import Python ⇒ 逐字解析文本）。
ROUTING_PY = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "production" / "routing.py"

#: 端点必须挂的码（= 该页第一屏读码 = 菜单节点码 = 路由守卫码，issue #6573 已定）。
ENDPOINT_CODE = "production:view"

#: 服务端**必须**委派的既有读面（少一处 ⇒ 那一步的事实没了来源，会静默变成 `unknown`）。
REQUIRED_DELEGATIONS: tuple[str, ...] = (
    "productionRoutingReadService.operationPositions(",
    "productionOperationQueryService.catalog(",
    "productionOperationQueryService.routings(",
    "processingFeeQueryService.combinations(",
    "processingFeeQueryService.feeGaps(",
    "processingItemService.getProcessingItems(",
    "craftCalcConfigService.get(",
    "remnantService.specs(",
)

#: 旧的主线五读面（issue #6579 之后**不该**再出现在 `/settings` 页面的 effect 驱动面上）。
RETIRED_PAGE_CALLS: tuple[str, ...] = (
    "productionApi.getOperationPositions",
    "productionApi.getRoutings",
    "productionApi.getFeeCombinations",
    "productionApi.getFeeGaps",
)

#: 服务端**不许**出现的形态（正则，按**标识符**判，不按散文判）：
#: 直接摸库（`XxxMapper` 类型 / `mapper` 包的 import）、手写查询（`@Select` / `SELECT …`）、
#: 以及三态字面量（第二份判定口径）。
_FORBIDDEN_SERVICE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b\w+Mapper\b", "直连持久层类型（XxxMapper）"),
    (r"import\s+com\.migao\.admin\.mapper\.", "直连持久层包（mapper import）"),
    (r"@Select\b", "手写查询注解（@Select）"),
    (r"\bSELECT\s+\w", "手写查询语句（SELECT …）"),
    (r"JdbcTemplate", "直连 JDBC 模板"),
    (r'"done"', "三态字面量 done"),
    (r'"todo"', "三态字面量 todo"),
    (r'"unknown"', "三态字面量 unknown"),
    (r'"state"', "三态键 state"),
)


def _class_level_annotation(text: str) -> str | None:
    """类级 `@RequirePermission("…")`（在 `public class` 之前出现的那个）。"""
    head = text.partition("public class ")[0]
    match = re.search(r'@RequirePermission\(\s*"([^"]+)"\s*\)', head)
    return match.group(1) if match else None


def _method_annotation(text: str, method: str) -> str | None:
    """`method()` 声明**紧邻**上方的 `@RequirePermission("…")`（方法级）。"""
    match = re.search(rf"public [^;{{]*\b{re.escape(method)}\(", text)
    if match is None:
        return None
    window = text[max(0, match.start() - 400): match.start()]
    found = re.findall(r'@RequirePermission\(\s*"([^"]+)"\s*\)', window)
    return found[-1] if found else None


def problems_endpoint_permission(controller_text: str) -> list[str]:
    """判据 1：方法级 {@link ENDPOINT_CODE}，且**不许**有类级声明。"""
    out: list[str] = []
    if '@GetMapping("/config-readiness")' not in controller_text:
        out.append("控制器里找不到 `@GetMapping(\"/config-readiness\")` ⇒ 端点路径漂移（前端会 404）")
    method_code = _method_annotation(controller_text, "readiness")
    if method_code is None:
        out.append("`readiness()` 没有**方法级** `@RequirePermission` ⇒ 该端点没有任何码把守")
    elif method_code != ENDPOINT_CODE:
        out.append(f"`readiness()` 的方法级码是 `{method_code}`，应为 `{ENDPOINT_CODE}`")
    class_code = _class_level_annotation(controller_text)
    if class_code is not None:
        out.append(
            f"控制器出现了**类级** `@RequirePermission(\"{class_code}\")` ⇒ 该端点的码不再是它自己那一行"
            "（口径要求方法级；类级会让判据拿不到「这个端点用哪个码」的源码证据）"
        )
    return out


def problems_service_is_aggregator(service_text: str) -> list[str]:
    """判据 2：聚合器 —— 零直连库、零 SQL、零三态；八处既有读面委派一个不少。"""
    out: list[str] = []
    for pattern, what in _FORBIDDEN_SERVICE_PATTERNS:
        match = re.search(pattern, service_text)
        if match:
            out.append(
                f"就绪度服务里出现 `{match.group(0)}`（{what}）⇒ 它不再是聚合器"
                "（直连库 / 手写查询 = 第二份数据源；三态字面量 = 第二份判定口径）"
            )
    missing = [call for call in REQUIRED_DELEGATIONS if call not in service_text]
    if missing:
        out.append(
            "就绪度服务少了这些**既有读面**的委派 ⇒ 那几步的事实会静默变成 unknown：" + "、".join(missing)
        )
    return out


def _java_constant(text: str, name: str) -> str | None:
    match = re.search(rf'{re.escape(name)}\s*=\s*"([^"]*)"', text)
    return match.group(1) if match else None


def _domain_required_code(domains_text: str, domain_key: str) -> str | None:
    """域目录里某个域的 `requiredCode`（从该域对象起，到下一个域对象为止的窗口里找）。"""
    start = domains_text.find(f"key: '{domain_key}'")
    if start < 0:
        return None
    nxt = domains_text.find("  {\n    key: '", start)
    window = domains_text[start: nxt if nxt > 0 else len(domains_text)]
    match = re.search(r"requiredCode:\s*'([^']+)'", window)
    return match.group(1) if match else None


def problems_cross_code_single_source(
    service_text: str,
    remnant_controller_text: str,
    domains_text: str,
) -> list[str]:
    """判据 3：「余料尺寸读面码」三处同值（服务常量 / 控制器类级声明 / 前端域目录）。"""
    out: list[str] = []
    service_code = _java_constant(service_text, "REMNANT_SIZES_READ_CODE")
    remnant_code = _class_level_annotation(remnant_controller_text)
    domain_code = _domain_required_code(domains_text, "remnant-sizes")
    if service_code is None:
        out.append("就绪度服务里找不到 `REMNANT_SIZES_READ_CODE` 常量 ⇒ 跨码步骤失去了说明「哪个码」的唯一出处")
    if remnant_code is None:
        out.append("`RemnantController` 上没有类级 `@RequirePermission` ⇒ 余料尺寸读面的码无从现取（fail-closed）")
    if domain_code is None:
        out.append("域目录里找不到 `remnant-sizes` 域或其 `requiredCode` ⇒ 前端域门控的码无从现取")
    present = {"就绪度服务": service_code, "余料尺寸控制器": remnant_code, "前端域目录": domain_code}
    values = {value for value in present.values() if value is not None}
    if len(values) > 1:
        detail = "、".join(f"{where}=`{code}`" for where, code in present.items() if code is not None)
        out.append(f"「余料尺寸读面码」三处不同值（{detail}）⇒ 不持码的人会拿到数、或持码的人拿不到")
    return out


def _java_list(text: str, name: str) -> list[str]:
    match = re.search(rf"{re.escape(name)}\s*=\s*List\.of\(([^)]*)\)", text)
    if match is None:
        return []
    return re.findall(r'"([^"]*)"', match.group(1))


def _ts_string_array(text: str, name: str) -> list[str]:
    match = re.search(rf"{re.escape(name)}\s*=\s*\[([^\]]*)\]", text)
    if match is None:
        return []
    return re.findall(r"'([^']*)'", match.group(1))


def problems_base_route_names(service_text: str, readiness_ts: str, routing_py: str) -> list[str]:
    """判据 4：两条基础路线名 Java / TS / 引擎三处**逐值**同值。"""
    out: list[str] = []
    java_names = _java_list(service_text, "BASE_ROUTE_NAMES")
    ts_names = _ts_string_array(readiness_ts, "BASE_ROUTE_NAMES")
    py_names = [
        _java_constant(routing_py, "ROUTE_TEMPLATE_NAME_DEFAULT"),
        _java_constant(routing_py, "FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT"),
    ]
    py_names = [name for name in py_names if name is not None]
    if not java_names:
        out.append("就绪度服务里找不到 `BASE_ROUTE_NAMES` ⇒ `missing_base_routes` 会退化成「一条都不缺」")
    if not ts_names:
        out.append("前端判据模块里找不到 `BASE_ROUTE_NAMES` ⇒ 页面内五步判据失去真值源")
    if len(py_names) != 2:
        out.append("算料引擎 `routing.py` 里找不到两条基础路线名的常量（路径或改名 ⇒ fail-closed）")
    for label, names in (("就绪度服务", java_names), ("前端判据模块", ts_names), ("算料引擎", py_names)):
        if names and sorted(names) != sorted(java_names or names):
            out.append(f"{label} 的基础路线名 {names} 与就绪度服务的 {java_names} 不同 ⇒ 同一件事两套口径")
    return out


def _java_step_hrefs(service_text: str) -> dict[str, str]:
    """`STEP_*` 常量 → `hrefs.put(STEP_*, "...")` 的键值对（服务端七步的去处）。"""
    constants = {
        name: value
        for name, value in re.findall(r'(STEP_[A-Z_]+)\s*=\s*"([^"]*)"', service_text)
    }
    hrefs: dict[str, str] = {}
    for step_constant, href in re.findall(r'hrefs\.put\(\s*(STEP_[A-Z_]+)\s*,\s*"([^"]*)"\s*\)', service_text):
        key = constants.get(step_constant)
        if key is not None:
            hrefs[key] = href
    return hrefs


def _ts_mainline_hrefs(readiness_ts: str) -> dict[str, str]:
    """前端 `MAINLINE_STEPS` 的 `key → href`（同一条目内的配对）。"""
    start = readiness_ts.find("export const MAINLINE_STEPS")
    if start < 0:
        return {}
    end = readiness_ts.find("\n]", start)
    block = readiness_ts[start: end if end > 0 else len(readiness_ts)]
    hrefs: dict[str, str] = {}
    for entry in re.finditer(r"\{\s*key:\s*'([^']+)'(.*?)\n  \}", block, re.S):
        href = re.search(r"href:\s*'([^']+)'", entry.group(2))
        if href:
            hrefs[entry.group(1)] = href.group(1)
    return hrefs


def problems_step_hrefs(service_text: str, readiness_ts: str) -> list[str]:
    """判据 5：七步的 `href` 服务端 ≡ 前端主线（改一处 ⇒ 死链，且没有东西会红）。"""
    out: list[str] = []
    server = _java_step_hrefs(service_text)
    frontend = _ts_mainline_hrefs(readiness_ts)
    if not server:
        out.append("就绪度服务里解析不出任何 `hrefs.put(STEP_*, \"…\")` ⇒ 响应里的 href 无从现取")
    if not frontend:
        out.append("前端 `MAINLINE_STEPS` 里解析不出任何 `href` ⇒ 判据会空跑（fail-closed）")
    for key, href in server.items():
        if key not in frontend:
            out.append(f"服务端给了 `{key}` 一步，前端主线里没有这个 key ⇒ 那一步的文案与去处对不上")
        elif frontend[key] != href:
            out.append(
                f"`{key}` 的去处两处不同（服务端 `{href}` / 前端 `{frontend[key]}`）⇒ 必有一条是死链"
            )
    for key in frontend:
        if key not in server:
            out.append(f"前端主线有 `{key}` 一步，服务端没给它的 href ⇒ 响应契约缺项")
    return out


def problems_frontend_single_request(page_text: str, api_text: str) -> list[str]:
    """判据 6：页面调聚合端点、不再调那五个旧读面、三态翻译走单一真值模块。"""
    out: list[str] = []
    if not re.search(r"['\"]/api/admin/config-readiness['\"]", api_text):
        out.append("前端 api 模块没有请求 `/api/admin/config-readiness` ⇒ 页面无从只发一个请求")
    if "configReadinessApi.get(" not in page_text:
        out.append("`/settings` 页面没有调用 `configReadinessApi.get(` ⇒ 主线读数没有来源")
    if "statesFromFacts(" not in page_text:
        out.append("`/settings` 页面没有用 `statesFromFacts(` 翻译事实 ⇒ 三态判定又回到页面里了（第二份口径）")
    still_there = [call for call in RETIRED_PAGE_CALLS if call in page_text]
    if still_there:
        out.append(
            "`/settings` 页面仍在直调旧的主线读面（" + "、".join(still_there) + "）⇒ "
            "「只发一个请求」不成立（这五个读面已由聚合端点收口）"
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（读真文件）
# ══════════════════════════════════════════════════════════════════════════════


def _read(path: Path) -> str:
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf-8")


def test_endpoint_declares_method_level_production_view() -> None:
    problems = problems_endpoint_permission(_read(CONTROLLER))
    assert problems == [], "就绪度端点的权限声明不合口径：\n" + "\n".join(f"  · {p}" for p in problems)


def test_service_is_an_aggregator_of_existing_read_surfaces() -> None:
    problems = problems_service_is_aggregator(_read(SERVICE))
    assert problems == [], "就绪度服务不再是聚合器：\n" + "\n".join(f"  · {p}" for p in problems)


def test_cross_code_step_code_is_isomorphic_in_three_places() -> None:
    problems = problems_cross_code_single_source(
        _read(SERVICE), _read(REMNANT_CONTROLLER), _read(DOMAINS_TS)
    )
    assert problems == [], "跨码步骤的读面码三源不同构：\n" + "\n".join(f"  · {p}" for p in problems)


def test_base_route_names_match_across_java_ts_and_engine() -> None:
    problems = problems_base_route_names(_read(SERVICE), _read(READINESS_TS), _read(ROUTING_PY))
    assert problems == [], "基础路线名三源不同构：\n" + "\n".join(f"  · {p}" for p in problems)


def test_step_hrefs_match_the_frontend_mainline() -> None:
    problems = problems_step_hrefs(_read(SERVICE), _read(READINESS_TS))
    assert problems == [], "七步的 href 两处不同值：\n" + "\n".join(f"  · {p}" for p in problems)


def test_settings_page_draws_the_mainline_with_one_request() -> None:
    problems = problems_frontend_single_request(_read(SETTINGS_PAGE), _read(API_MODULE_TS))
    assert problems == [], "前端没有做到「只发一个请求画主线」：\n" + "\n".join(
        f"  · {p}" for p in problems
    )


def test_new_modules_exist_and_carry_no_tri_state() -> None:
    """类型模块只声明**事实**形状（不许出现三态字段）—— 出现即第二份判定口径。"""
    types_text = _read(TYPES_TS)
    assert "steps" in types_text, "类型模块里没有 `steps` ⇒ 响应形状无从表达"
    for literal in ('"done"', "'done'", '"todo"', "'todo'", "state:"):
        assert literal not in types_text, f"就绪度类型里出现 `{literal}` ⇒ 事实与三态被混在一个形状里"


# ══════════════════════════════════════════════════════════════════════════════
# 红证（注入式；**真的跑一遍**，证明上面每条判据都有牙）
# ══════════════════════════════════════════════════════════════════════════════


def test_endpoint_permission_guard_can_go_red() -> None:
    good = _read(CONTROLLER)
    assert problems_endpoint_permission(good) == []

    class_level = good.replace(
        "public class ConfigReadinessController",
        '@RequirePermission("processing:manage")\npublic class ConfigReadinessController',
        1,
    )
    assert problems_endpoint_permission(class_level), "类级声明竟没被判出 ⇒ 判据 1 是空断言"

    wrong_code = good.replace('@RequirePermission("production:view")',
                              '@RequirePermission("processing:manage")', 1)
    assert problems_endpoint_permission(wrong_code), "换码（方法级）竟没被判出 ⇒ 判据 1 是空断言"

    no_annotation = good.replace('    @RequirePermission("production:view")\n', "", 1)
    assert problems_endpoint_permission(no_annotation) != problems_endpoint_permission(good)


def test_aggregator_guard_can_go_red() -> None:
    good = _read(SERVICE)
    assert problems_service_is_aggregator(good) == []

    with_mapper = good + "\n// injected\nprivate final ProductionOperationMapper injected;\n"
    assert problems_service_is_aggregator(with_mapper), "直连 Mapper 竟没被判出 ⇒ 判据 2 是空断言"

    dropped = good.replace("processingFeeQueryService.feeGaps(tenantId)", "Map.of()", 1)
    assert problems_service_is_aggregator(dropped), "少一处委派竟没被判出 ⇒ 判据 2 是空断言"

    with_state = good + '\n// injected\nstatic final String X = "todo";\n'
    assert problems_service_is_aggregator(with_state), "服务端出现三态字面量竟没被判出 ⇒ 判据 2 是空断言"


def test_cross_code_guard_can_go_red_and_names_the_place() -> None:
    service = _read(SERVICE)
    remnant = _read(REMNANT_CONTROLLER)
    domains = _read(DOMAINS_TS)
    assert problems_cross_code_single_source(service, remnant, domains) == []

    mutated_service = service.replace('REMNANT_SIZES_READ_CODE = "processing:manage"',
                                      'REMNANT_SIZES_READ_CODE = "production:view"', 1)
    hits = problems_cross_code_single_source(mutated_service, remnant, domains)
    assert hits, "服务常量改掉竟没被判出 ⇒ 判据 3 是空断言"
    assert any("就绪度服务" in hit for hit in hits), f"没点名是哪一处不同：{hits}"

    mutated_domains = domains.replace(
        "requiredCode: 'processing:manage'", "requiredCode: 'production:view'", 1
    )
    assert problems_cross_code_single_source(service, remnant, mutated_domains), (
        "前端域目录的码改掉竟没被判出 ⇒ 判据 3 对前端那一处没有牙"
    )


def test_base_route_guard_can_go_red() -> None:
    service = _read(SERVICE)
    readiness = _read(READINESS_TS)
    routing = _read(ROUTING_PY)
    assert problems_base_route_names(service, readiness, routing) == []

    mutated_py = routing.replace(
        'ROUTE_TEMPLATE_NAME_DEFAULT = "窗帘工序路线（默认）"',
        'ROUTE_TEMPLATE_NAME_DEFAULT = "窗帘路线"',
        1,
    )
    assert problems_base_route_names(service, readiness, mutated_py), (
        "引擎侧改名竟没被判出 ⇒ 判据 4 是空断言"
    )

    mutated_ts = readiness.replace("'布料工序路线'", "'布帘工序路线'", 1)
    assert problems_base_route_names(service, mutated_ts, routing), (
        "前端改名竟没被判出 ⇒ 判据 4 对前端那一处没有牙"
    )


def test_step_href_guard_can_go_red() -> None:
    service = _read(SERVICE)
    readiness = _read(READINESS_TS)
    assert problems_step_hrefs(service, readiness) == []

    mutated_service = service.replace(
        'hrefs.put(STEP_CALC, "/settings/params")',
        'hrefs.put(STEP_CALC, "/settings?domain=calc")',
        1,
    )
    assert problems_step_hrefs(mutated_service, readiness), "服务端 href 改掉竟没被判出 ⇒ 判据 5 是空断言"

    mutated_ts = readiness.replace("href: '/production/processing-fees'",
                                   "href: '/production/processing-fees?tab=1'", 1)
    assert problems_step_hrefs(service, mutated_ts), "前端 href 改掉竟没被判出 ⇒ 判据 5 对前端没有牙"


def test_single_request_guard_can_go_red() -> None:
    page = _read(SETTINGS_PAGE)
    api_module = _read(API_MODULE_TS)
    assert problems_frontend_single_request(page, api_module) == []

    restored = page.replace(
        "try {\n", "try {\n      void productionApi.getOperationPositions()\n", 1
    )
    if restored == page:  # 锚点漂移的保护：换一个稳定锚再注入
        restored = page.replace("      configReadinessApi.get(),", "      configReadinessApi.get(),\n      productionApi.getRoutings(),", 1)
    assert problems_frontend_single_request(restored, api_module), (
        "把旧读面调回页面竟没被判出 ⇒ 判据 6 是空断言"
    )

    # 全部替换（不止第一处）：第一处落在散文里，只改它会留下真正的请求字面量不动
    mutated_api = api_module.replace("/api/admin/config-readiness", "/api/admin/config-readiness-v2")
    assert problems_frontend_single_request(page, mutated_api), (
        "api 模块换了路径竟没被判出 ⇒ 判据 6 对请求路径没有牙"
    )
