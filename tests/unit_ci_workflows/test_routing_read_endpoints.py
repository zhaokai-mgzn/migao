# case_ids: PG-018, PG-035
"""两个只读端点（issue #4500 = 母单 #4423 的 **P2c**，P3 前端 #4433 的数据面前置）的静态承重判据。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的 `extract_case_ids()`
只扫前 50 行），故它放在 docstring 之前。

## 被测对象（issue #4500 冻结的两个形状）

| 端点 | 形状 | 顺序口径 |
|---|---|---|
| `GET /api/admin/production/operation-positions` | `[{id, operation, position, unit_price, applicable, variant_operation_id, unit, group, scope, is_must_finish}]`（物理表 30 逻辑工序 × 4 部位 = 120 行；**去部位化后端点收敛为「一道逻辑工序一行」= 30 行**，issue #4883；`id` + 变体元数据 = issue #4587 追加；**`variant_name` 已按 issue #4622 去掉**） | **先收敛**（`collapseToLogical`）**再按逻辑工序名** |
| `GET /api/admin/production/route-rules` | `[{id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status, customer_unit_price}]`（**26 条**；末键 = issue #4567 追加的**元/套**价，`null` = 未定价 ≠ 0 元） | `(priority, id)` |

## 为什么需要本文件（三条**结构性**失效形态，各自不会自己变红）

① **第二份口径漂移**：真值源是 `app/production/routing.py` 的 `OPERATION_POSITION_PRICES` /
   `ROUTE_RULES`，落库快照是 V71 的 84 + 26 行。**端点把哪一份呈现给前端**决定了商家看到的价目与
   规则 —— 两份额外的可能（端点自行过滤/改名/换源）**没有任何既有判据**会红。
   （值层面的三源收敛已由 `test_production_catalog_seed.py` 守；本文件守的是
   「**端点能不能看见全部 84/26 行**」这一层 —— 两者是不同的失效面。）
② **读已软删的旧规则表**：`production_option_routings` / `production_option_factors` 是**已退场**
   的旧真值源（P2b 软删）。端点若读旧表 ⇒ 商家改一条规则、车间按另一条干（工序顺序错 = 少发工资）。
③ **顺序不确定**：矩阵/规则区的顺序由服务端派生；不排序 ⇒ 每次刷新顺序都变（同 P2b 的
   `(priority, id)` 口径）。

## 判据与红证（每条都独立可红，互不掩盖）

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | 两个端点存在 + `processing:manage` + `TenantContext.getTenantId()` 隔离 + 信封形状/键集逐字 | 今天端点不存在 ⇒ 红；改键名/加键 ⇒ 红 |
| 2 | 数据源**只**是新两表（旧表 entity/mapper 零命中） | 把服务改成 `ProductionOptionRoutingMapper` ⇒ 红 |
| 3 | 顺序口径落码：**收敛**（适用优先 → 布帘列 → `position` → `id`）**+ 按逻辑工序名排序** / `(priority, id)` | 去掉收敛或排序 ⇒ 红 |
| 4 | **无行丢弃过滤**：`eq` 目标集恰为 `{TenantId, Deleted, Status}`（规则表另加 `action IN (insert, remove)`） | 加 `.eq(...getApplicable, true)` ⇒ 红（120 格变少） |
| 5 | 端点可见性 = 真值源**全集**：V71 的 84/26 行逐值等于 `routing.py` 且每行对端点可见 | 改一格价目（0.4 → 0.45）⇒ 红；把一行种成 `status='disabled'` ⇒ 红 |

红证原文（本文件对当前树的运行结果）见 PR body —— 本单按 TDD 先落本文件、确认**红**，再实现。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTROLLER = REPO / "backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java"
SERVICE = REPO / "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java"
#: 收敛实现的**唯一**出处（issue #4883 去部位化）：读面 / 实例化 / 补价三处共用它。
QUERY_SERVICE = REPO / ("backend/admin-api/src/main/java/com/migao/admin/service/"
                        "ProductionOperationQueryService.java")
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
ROUTING_PY_DIR = REPO / "backend/ai-agent-service"

POSITION_TABLE = "production_operation_positions"
RULE_TABLE = "production_route_rules"
#: 已退场的旧规则表（P2b / issue #4459 软删；**端点绝不许读**）。
RETIRED_TYPES = ("ProductionOptionRouting", "ProductionOptionFactor")

#: 端点声明的形状（issue #4500 冻结，逐字；多一个键/少一个键/改名都红）。
#: `customer_unit_price` 是 issue #4567 追加的第 10 键（**元/套**；`null` = 未定价 ≠ 0 元）。
#: 部位价目 = **10 键**：前 4 键（issue #4500 冻结）+ `id`（前端 `PUT /operation-positions/{id}`
#: 的寻址键）+ 5 键变体元数据（issue #4587 ①，母单 #4586 的「中间那座桥」）。
#: ⚠️ **`variant_name` 已按 issue #4622 去掉**（goal「web 面工序命名统一」阶段 3）：它是**当前**
#: 工序库的旧名（`布三边` / `精裁-布`），而 web 面只用**一套工序名** = 逻辑工序名 + 部位
#: ⇒ 键留在响应里就仍是 web 可见的旧口径。改判为 10 键是**契约同步**，**不是**放宽判据
#: —— 本常量仍是**冻结判据**（不是「至少包含」）：加/删/改名照旧红。
POSITION_KEYS = ("id", "operation", "position", "unit_price", "applicable",
                 "variant_operation_id", "unit", "group", "scope", "is_must_finish")
RULE_KEYS = ("id", "trigger_kind", "trigger_value", "position", "action", "operation",
             "after_operation", "priority", "status", "customer_unit_price")

#: 两层分区端点（issue #4676）的 `delivery` 段键集（逐字；9 键）。
#: `price_state` 是**三态 + 一个退化态**的显式判据：`priced` / `unpriced`（**≠ ¥0.00**）/
#: `multiple_prices`（+ `different_price_count`）/ `no_applicable_position`。
#: `applicable_positions` = 参与取值的部位（前端渲染「各部位不同价（N 处）」）。
DELIVERY_KEYS = ("operation", "scope", "unit", "group", "is_must_finish",
                 "price", "price_state", "different_price_count", "applicable_positions")

#: 本端点呈现的规则动作 = 路线编排（`insert`/`remove`）。`action='factor'`（V72 从旧
#: `production_option_factors` 搬来的**计件系数档**）**不在本端点**：它没有 `after_operation` 语义、
#: 也不属 P3「统一规则区」（#4433 §三 只描述插入/移除）—— 见服务类 javadoc 的口径说明。
ROUTE_ACTIONS = ("insert", "remove")

#: 端点可见性过滤（服务层 SQL 条件）—— 84/26 行**每一行**都必须满足，否则真值源里有行前端看不见。
VISIBLE_STATUS = "active"

_POSITION_ROW_RE = re.compile(
    r"\(\s*'(?P<id>[^']*)'\s*,\s*(?P<tenant>\d+)\s*,\s*'(?P<logical>[^']*)'\s*,\s*'(?P<position>[^']*)'\s*,"
    r"\s*(?P<price>NULL|[\d.]+)\s*,\s*(?P<applicable>TRUE|FALSE)\s*,\s*'(?P<status>[^']*)'\s*\)",
    re.I)
_RULE_ROW_RE = re.compile(
    r"\(\s*'(?P<id>[^']*)'\s*,\s*(?P<tenant>\d+)\s*,\s*'(?P<kind>[^']*)'\s*,\s*'(?P<trigger>[^']*)'\s*,"
    r"\s*(?P<position>NULL|'[^']*')\s*,\s*'(?P<action>[^']*)'\s*,\s*'(?P<operation>[^']*)'\s*,"
    r"\s*(?P<after>NULL|'[^']*')\s*,\s*(?P<priority>\d+)\s*,\s*'(?P<status>[^']*)'\s*\)",
    re.I)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _java_code(path: Path) -> str:
    """Java 源码的**可执行**部分（去掉 `/* … */` 与 `// …` 注释）。

    守卫必须看代码、不能把注释里的字面量当成实现（同 `test_routing_model_p2_consumers.py` 的
    `_strip_comments` 口径）：本单的服务类 javadoc **正当地**提到旧表名（解释「为什么只读新表」），
    不剥注释就会把「解释」判成「读取点」= 假红。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", _read(path))
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.split("\n"))


def _literal_values_sources(table: str) -> list:
    """**按内容**发现该表的字面量种子迁移（`INSERT INTO <table> … VALUES …`）。

    判据 1（按内容发现源）同 `test_production_catalog_seed.py`：将来的增量迁移无需改本文件。
    ⚠️ `VALUES` 之前**不得出现 `SELECT`** —— P2（V72）的按租户回填是
    `INSERT INTO <table> … SELECT … FROM tenants t JOIN (VALUES …)`，那个 `VALUES` 是
    **派生**语句的 JOIN 源、不是字面量种子行（把它算进来会造出第二份「种子」口径）。
    """
    found = []
    for path in sorted(MIGRATION_DIR.glob("V*.sql")):
        sql = _read(path)
        for m in re.finditer(r"INSERT\s+INTO\s+" + table + r"\b(?P<mid>[\s\S]{0,600}?)\bVALUES\b", sql, re.I):
            if "select" not in m.group("mid").lower():
                found.append(path)
                break
    return found


def _rows(table: str, row_re: re.Pattern) -> list:
    """全部字面量种子行（`INSERT` 语句文本内逐个 tuple 解析）→ `[match, …]`。"""
    rows = []
    for path in _literal_values_sources(table):
        sql = _read(path)
        for stmt in re.findall(r"INSERT\s+INTO\s+" + table + r"\b[\s\S]*?;", sql, re.I):
            if "select" in stmt[:stmt.lower().find("values")].lower():
                continue
            rows.extend(row_re.finditer(stmt))
    return rows


def _position_seed_rows() -> dict:
    """`{(逻辑工序, 部位): (单价|None, applicable, status)}`（V71 ∪ V79 的 **120 行字面量**）。

    ⚠️ 键含部位维（**历史 120 行态的入口**）：issue #4937 之后**终态**是一道逻辑工序一行，
    所以本函数只用于「字面量种子逐行可见性」这类仍需部位维的判据（见
    `test_position_seed_is_visible_and_matches_truth_source`）。
    """
    out = {}
    for m in _rows(POSITION_TABLE, _POSITION_ROW_RE):
        price = None if m.group("price").upper() == "NULL" else float(m.group("price"))
        out[(m.group("logical"), m.group("position"))] = (
            price, m.group("applicable").upper() == "TRUE", m.group("status"))
    return out


def _rule_seed_rows() -> dict:
    """`{(trigger_kind, trigger_value, position|None, action, operation, after|None): (priority, status)}`。"""
    def text_or_none(raw: str):
        return None if raw.upper() == "NULL" else raw.strip("'")

    out = {}
    for m in _rows(RULE_TABLE, _RULE_ROW_RE):
        out[(m.group("kind"), m.group("trigger"), text_or_none(m.group("position")),
             m.group("action"), m.group("operation"), text_or_none(m.group("after")))] = (
            int(m.group("priority")), m.group("status"))
    return out


def _truth_positions() -> dict:
    """`routing.py::OPERATION_POSITION_PRICES` → `{逻辑工序: (单价|None, applicable)}`（**终态单键**）。

    🔴 issue #4937：真值源的价目表**只按逻辑工序**建索引（30 行）⇒ 本函数随之收敛为单键。
    """
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import OPERATION_POSITION_PRICES
        return {logical: (None if cell["unit_price"] is None else float(cell["unit_price"]),
                          bool(cell["applicable"]))
                for logical, cell in OPERATION_POSITION_PRICES.items()}
    finally:
        sys.path.pop(0)


def _collapse_seed_rows() -> dict:
    """按**四档选行**把 120 行种子收敛为 `{逻辑工序: (价, 适用, status)}`（终态口径）。

    档序 = ① `applicable` 优先 ② `布帘` 列优先 ③ `position` 字典序 ④ `id` 升序
    （与 `ProductionOperationQueryService#collapseToLogical` / `V104` 同序）。
    """
    grouped: dict = {}
    for key, value in _position_seed_rows().items():
        grouped.setdefault(key[0], []).append((key[1], value))

    def rank(item):
        position, (price, applicable, status) = item
        return (0 if applicable else 1, 0 if position == "布帘" else 1, position)

    return {logical: sorted(items, key=rank)[0][1] for logical, items in grouped.items()}


def _truth_rules() -> dict:
    """`routing.py::ROUTE_RULES` → 与 `_rule_seed_rows` 同形的键（**含** `position`）。

    🔴 **issue #4962 改判**（此前 #4937 / O2 期间比对键去掉过这一维）：规则级部位限定
    **加回** ⇒ 真值源里恰好一条带 `position`（`韩褶 → insert 上车布` = `'布帘'`），
    SQL 字面量侧同值（`V71` 的 `rr-v70-02`；迁移链终态由
    `V108__restore_route_rule_positions.sql` 写回、净效果 = 恒等）⇒ 比对键**必须含**该维。
    """
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import ROUTE_RULES
        limited = [r for r in ROUTE_RULES if r.get("position")]
        assert len(limited) == 1 and limited[0]["position"] == "布帘", (
            f"`routing.py::ROUTE_RULES` 的部位限定集漂移（期望恰好一条 `布帘`）：{limited}")
        return {(r["trigger_kind"], r["trigger_value"], r.get("position"),
                 r["action"], r["operation"], r["after_operation"]):
                int(r["priority"]) for r in ROUTE_RULES}
    finally:
        sys.path.pop(0)


def _endpoint_body(path: str) -> str:
    """控制器里该端点的**方法体**（`@GetMapping("<path>")` 到方法结束的 `    }`）。"""
    src = _java_code(CONTROLLER)
    m = re.search(r'@GetMapping\("' + re.escape(path) + r'"\)[\s\S]*?\n    \}', src)
    assert m, (
        f"找不到 `GET {path}` 端点 —— issue #4500 的两个只读端点是 P3（#4433）的数据面前置；"
        f"缺了它前端「部位价目矩阵」/「统一规则区」无数据可渲染"
    )
    return m.group(0)


def _view_keys(method: str) -> tuple:
    """服务层展示形态方法里的键**顺序**（`view.put("…", …)` 逐行）。"""
    src = _java_code(SERVICE)
    m = re.search(r"private\s+Map<String,\s*Object>\s+" + method + r"\s*\([\s\S]*?\n    \}", src)
    assert m, f"服务层找不到 {method} —— 展示形态必须收敛到**一处**（列表项与端点共用同一份）"
    return tuple(re.findall(r'view\.put\("([a-z_]+)"', m.group(0)))


def _eq_targets(entity: str) -> set:
    """服务层对该实体的 `eq(...)` 目标字段集合（**行丢弃过滤**的机械判据）。"""
    return set(re.findall(r"\.eq\(\s*" + entity + r"::get(\w+)", _java_code(SERVICE)))


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1：两个端点存在 + 权限 + 租户隔离 + 形状逐字
# ══════════════════════════════════════════════════════════════════════════════════

def test_operation_positions_endpoint_declares_manage_permission_and_tenant():
    """判据 1a：`GET /operation-positions` 存在、权限 `processing:manage`、按 TenantContext 隔离。"""
    body = _endpoint_body("/operation-positions")
    assert '@RequirePermission("processing:manage")' in body, (
        "端点缺方法级 `@RequirePermission(\"processing:manage\")` —— 类级是 `order:list`"
        "（客服/销售/财务都有）⇒ 不覆盖 = 价目矩阵与规则区对所有岗位可见（issue #4500 硬要求 4）"
    )
    assert "TenantContext.getTenantId()" in body, (
        "端点没有把 `TenantContext.getTenantId()` 传给服务层 —— 跨租户读价目/规则"
        "（商家会看到别人的价与规则 = 少发/多发工资）"
    )


def test_route_rules_endpoint_declares_manage_permission_and_tenant():
    """判据 1b：`GET /route-rules` 同上。"""
    body = _endpoint_body("/route-rules")
    assert '@RequirePermission("processing:manage")' in body, "端点缺方法级 `processing:manage`"
    assert "TenantContext.getTenantId()" in body, "端点没有按 `TenantContext.getTenantId()` 隔离租户"


def test_position_view_keys_are_frozen_contract():
    """判据 1c：部位价目项的键集/键序 = 10 键（逐字；issue #4587 起 = 原 4 键 + `id` + 5 键变体元数据，
    issue #4622 起去掉 `variant_name`）。"""
    assert _view_keys("positionView") == POSITION_KEYS, (
        f"部位价目项键集漂移（issue #4500 冻结 4 键 + #4587 追加 id/变体元数据 − #4622 去掉变体名："
        f"{POSITION_KEYS}）"
        f"—— 前端矩阵按这 10 个键渲染，且 `id` 是格内改价 `PUT /operation-positions/{{id}}` 的寻址键；"
        f"缺 `id` ⇒ 改价无法落地，缺变体键 ⇒ 单位/单价/必完一律显示不出来；"
        f"多回 `variant_name` ⇒ 变体名又变成 web 可见的旧口径（issue #4622 的硬判据）"
    )


def test_rule_view_keys_are_frozen_contract():
    """判据 1d：规则项的键集/键序 = 10 个键（逐字；末键 = issue #4567 的 `customer_unit_price`）。

    ⚠️ issue #4643 把 `operation` / `after_operation` 改成**读时归一后的逻辑名**（读面兜住存量变体名行），
    但**键集一字不动**（归一不新增也不删键）—— 本常量仍是**冻结判据**，加/删/改名照旧红。
    """
    assert _view_keys("ruleView") == RULE_KEYS, (
        f"规则项键集漂移（issue #4500 冻结 + #4567 追加 `customer_unit_price`：{RULE_KEYS}）"
        f"—— 前端 #4433 的统一规则区按这些键渲染"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 2：只读新两表（旧规则表已退场，绝不读）
# ══════════════════════════════════════════════════════════════════════════════════

def _method_body(method: str) -> str:
    """服务层某方法的**方法体**（含签名行，到方法结束的 `    }`）。"""
    src = _java_code(SERVICE)
    m = re.search(r"(private|public)[\s\S]{0,80}?\b" + method + r"\s*\([\s\S]*?\n    \}", src)
    assert m, f"服务层找不到 {method} —— 两层分区/一列价必须收敛到**一处**实现"
    return m.group(0)


def test_operation_layers_endpoint_declares_manage_permission_and_tenant():
    """判据 1e：`GET /operation-layers` 存在、权限 `processing:manage`、按 TenantContext 隔离。"""
    body = _endpoint_body("/operation-layers")
    assert '@RequirePermission("processing:manage")' in body, (
        "两层分区端点缺方法级 `processing:manage` —— 类级是 `order:list`"
        "（客服/销售/财务都有）⇒ 不覆盖 = 工序/交付分区与价目对所有岗位可见"
    )
    assert "TenantContext.getTenantId()" in body, "端点没有按 `TenantContext.getTenantId()` 隔离租户"


def test_operation_layers_partitions_by_existing_scope():
    """判据 1f：分区判据 = **既有** `scope`（`set` ⇒ delivery；其余含 `null` ⇒ operations）。

    为什么守：判据换成「有没有矩阵格」⇒ 一道交付工序在某部位没有格时**整行消失**
    （#4674 形态：表格里有、抽屉里空、无处可删）；换成新字段 ⇒ 引入第二套分区口径。

    ⚠️ **本判据的形态在 issue #4729 随实现改钉**（不是放宽）：行来源已从「矩阵行」改为
    「工序库行」（见判据 1f′），故被比较的对象由 `row.get("scope")` 变为
    `entry.getValue().get("scope")` —— 判据本体仍是「**`SCOPE_SET` 常量**在 `operationLayers`
    里对 `scope` 键做相等判定」，且**仍在 `operationLayers` 内**（没被挪走/没换新概念）。
    """
    src = _java_code(SERVICE)
    assert re.search(r'SCOPE_SET\s*=\s*"set"', src), (
        "服务层没有 `SCOPE_SET = \"set\"` 常量 —— 分区判据必须是库里带出的既有 `scope`"
    )
    body = _method_body("operationLayers")
    assert re.search(r'SCOPE_SET\.equals\([\s\S]{0,60}?get\("scope"\)\s*\)', body), (
        "分区没有按 `scope == 'set'` 判定（`scope` 缺省 ⇒ `operations` = 安全方向）"
    )
    assert "delivery" in body and "operations" in body, "分区没有产出 `operations` / `delivery` 两段"
    assert not re.search(r'row\.get\("position"\)\s*==\s*null', body), (
        "分区不得按「有没有矩阵格/部位」判定（那会让交付工序整行消失）"
    )


def test_delivery_rows_come_from_operation_library_not_matrix_cells():
    """判据 1f′ 🔴：`delivery` 段的**行来源 = 工序库**的 `scope='set'` 行（issue #4729）。

    为什么守（独立验收 #4677 的 P1-2，实测 `PROBE delivery operations = [打包]`）：
    原实现遍历 `operationPositions()`（**只读矩阵表**）⇒ **零矩阵格**的套级工序在 `delivery` 段
    **一行都没有** ⇒ 该形态下【打包发货】层无行、无 `管理▸`、抽屉打不开。设计要求
    （#4675 §7 第 7 条 / #4677 四条约束）是「**第二层的行不依赖矩阵格**」。

    红证：把行来源改回「只遍历矩阵行」（删掉 `operationsByName` 这一路）⇒ 本条红。
    """
    body = _method_body("operationLayers")
    assert "operationsByName" in body, (
        "`delivery` 段没有从**工序库**取行 —— 零矩阵格的套级工序会整行消失"
        "（#4674 形态：表格里有、抽屉里空、无处可删）"
    )
    assert re.search(r'cellsByOperation\s*\.\s*getOrDefault\s*\(', body), (
        "`delivery` 段没有「零格 ⇒ 空格列表」的显式路径 ⇒ 零格工序仍会消失"
    )
    assert re.search(r'SCOPE_SET\.equals\(\s*entry\.getValue\(\)\.get\("scope"\)\s*\)', body), (
        "行来源没有按工序库行的 `scope == 'set'` 判定（判据必须是既有 `scope`，不新造概念）"
    )


def test_delivery_price_rule_reads_only_matrix_cells():
    """判据 1g 🔴：一列价**只**读矩阵格价，**不**回落工序库行价（设计 F1/F4 红线）。

    · F1：「格不存在 ⇒ 静默滤掉」不是兜底 ⇒ 一列价绝不能用「删格」实现（读面不得写 `deleted`）；
    · F4：`production_operations.unit_price` 是 `NOT NULL DEFAULT 0` ⇒ 一旦回落，
      「未定价」会变成「真 0 元」（工人白干）⇒ 读面必须把两态分开。
    """
    body = _method_body("deliveryView")
    assert re.search(r'cell\.get\("unit_price"\)', body), "一列价没有读矩阵格的 `unit_price`"
    for forbidden in ("productionOperationMapper", "operationsByName", "production_operations"):
        assert forbidden not in body, (
            f"一列价读了 `{forbidden}` —— 工序库行价是 `NOT NULL DEFAULT 0`，"
            f"回落会把「未定价」变成「真 ¥0.00」（设计 F4）"
        )
    assert '"unpriced"' in body, "一列价没有「未定价」态 ⇒ 未定价与 ¥0.00 不可区分"
    assert '"multiple_prices"' in body, "一列价在各部位不同价时没有显式态（会静默取第一个）"
    assert "different_price_count" in body, "一列价没有给出「不同价个数」（前端要渲染 N 处）"
    assert "applicable" in body, "一列价没有按 `applicable=TRUE` 过滤（明确不做 ≠ 未定价）"
    src = _java_code(SERVICE)
    assert not re.search(r"\.delete\(|\.setDeleted\(", src), (
        "只读服务里出现写操作 —— 一列价绝不能用「删格」实现（删格 ⇒ 该部位单静默少一道）"
    )


def test_delivery_view_keys_are_frozen_contract():
    """判据 1h：`delivery` 段键集/键序 = 9 键（逐字）。"""
    assert _view_keys("deliveryView") == DELIVERY_KEYS, (
        f"`delivery` 段键集漂移：{DELIVERY_KEYS} —— 前端 #4677 的「打包发货」区按这些键渲染"
        f"（`price_state` 是「未定价 ≠ ¥0.00」的机械判据，不得省略）"
    )


class TestInjectedDriftLayers:
    """两层分区 / 一列价的注入式红证（**不会红的断言 = 空断言**）。"""

    def test_partition_judgment_is_scope_not_cells(self):
        """注入：把分区判据换成「有格即交付」⇒ 判据 1f 的正则读不出来（红）。"""
        fake = ('private Map<String, Object> operationLayers(Long tenantId) {\n'
                '        if (row.get("position") == null) { return null; }\n'
                '        view.put("operations", null);\n'
                '    }')
        assert not re.search(r'SCOPE_SET\.equals\(\s*row\.get\("scope"\)\s*\)', fake), \
            "换成按格分区后判据仍命中 ⇒ 判据 1f 是空断言"
        assert re.search(r'row\.get\("position"\)\s*==\s*null', fake), \
            "注入形态读不出来 ⇒ 判据 1f 的否定分支是空断言"

    def test_price_fallback_is_detected(self):
        """注入：一列价回落工序库行价 ⇒ 判据 1g 的禁用清单会命中（红）。"""
        fake = ('private Map<String, Object> deliveryView(String op, List<Map<String, Object>> cells) {\n'
                '        Object price = cell.get("unit_price");\n'
                '        if (price == null) { price = productionOperationMapper.selectById(op); }\n'
                '    }')
        assert "productionOperationMapper" in fake, "注入形态读不出来 ⇒ 判据 1g 是空断言"

    def test_delivery_rows_drift_is_detected(self):
        """注入：把行来源改回「只遍历矩阵行」⇒ 判据 1f′ 命中（红）。"""
        fake = ('public Map<String, Object> operationLayers(Long tenantId) {\n'
                '        List<Map<String, Object>> rows = operationPositions(tenantId);\n'
                '        for (Map<String, Object> row : rows) {\n'
                '            if (SCOPE_SET.equals(row.get("scope"))) { view.put("delivery", row); }\n'
                '        }\n'
                '    }')
        assert "operationsByName" not in fake, "注入形态读不出来 ⇒ 判据 1f′ 是空断言"
        assert not re.search(r'cellsByOperation\s*\.\s*getOrDefault\s*\(', fake), \
            "注入形态读不出来 ⇒ 判据 1f′ 的「零格显式路径」分支是空断言"

    def test_delivery_keys_drift_is_detected(self):
        """注入：删掉 `price_state` 键 ⇒ 键集判据红。"""
        assert tuple(k for k in DELIVERY_KEYS if k != "price_state") != DELIVERY_KEYS, \
            "键集常量不含 `price_state` ⇒ 判据 1h 是空断言"


def test_reads_the_new_tables():
    """判据 2a：读面经**新两表**的 entity/mapper（不是「把旧读取点删掉了事」）。"""
    src = _java_code(SERVICE)
    missing = [t for t in ("ProductionOperationPositionMapper", "ProductionRouteRuleMapper")
               if t not in src]
    assert not missing, (
        f"服务层没有经这些类型读新表：{missing} —— 部位价目与规则的真值源是 V71/V72 的新两表"
        f"（{POSITION_TABLE} / {RULE_TABLE}）"
    )


def test_never_reads_retired_rule_tables():
    """判据 2b：旧规则表（P2b 已软删）**零**读取点。

    读取点的机械判据 = 源码里出现旧表的 entity/mapper 类型（读表必然经它们）。
    """
    offenders = {}
    for path in (SERVICE, CONTROLLER):
        hits = sorted(set(re.findall("|".join(RETIRED_TYPES), _java_code(path))))
        if hits:
            offenders[path.name] = hits
    assert not offenders, (
        f"这些文件仍在读**已退场**的旧规则表：{offenders} —— 旧两表的活跃行已由 P2b（#4459）软删，"
        f"读它们 ⇒ 商家改一条规则、车间按另一条干（工序顺序错 = 少发工人钱）"
    )
    src = _java_code(SERVICE)
    for table in ("production_option_routings", "production_option_factors"):
        assert table not in src, f"服务层出现了旧表名 `{table}`（只读新表）"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 3：顺序口径落码（派生必须确定性）
# ══════════════════════════════════════════════════════════════════════════════════

def test_position_order_is_logical_name_after_collapse():
    """判据 3a（**改判**，issue #4883 去部位化）：先**收敛**，再按**逻辑工序名**稳定排序。

    改前口径 = `(operation, position)` —— 它的前提是「同一逻辑工序在多个部位各有一行」。
    去部位化后读面必须把同一逻辑工序的多行**收敛成一行**（否则界面上同一道工序重复出现，
    且「改价改的是哪一行」取决于 DB 返回序 ⇒ 同一道工序两次刷新取到不同的价）。
    收敛顺序**完全确定**（不依赖 DB 返回序）= `applicable = TRUE` 优先 → 其中**布帘列**优先
    （用户裁定「取布帘价」）→ `position` 字典序 → `id` 升序。
    """
    src = _java_code(SERVICE)
    assert "ProductionOperationQueryService.collapseToLogical" in src, (
        "读面没有走 `collapseToLogical` 收敛 —— 矩阵物理行仍是 (逻辑工序, 部位) 多行，"
        "端点会把同一道工序按部位重复返回（一道工序一个价的前提不成立）"
    )
    assert not re.search(r"thenComparing\(ProductionOperationPosition::getPosition\)", src), (
        "读面仍在按 `(operation, position)` 排序 —— 那是去部位化**之前**的口径"
    )
    collapsed = _java_code(QUERY_SERVICE)
    assert re.search(r"names\.sort\(String::compareTo\)", collapsed), (
        "收敛结果没有按逻辑工序名排序 ⇒ 每次刷新顺序都变（issue #4500 硬要求 2）"
    )
    assert re.search(r"Boolean\.compare\(\s*Boolean\.TRUE\.equals\(candidate\.getApplicable\(\)\)",
                     collapsed), (
        "收敛没有「适用行优先」这一档 —— 少了它，`帘头制作` 这类「布帘格 applicable=FALSE 且价 NULL」"
        "的工序会被收敛成**未定价**（而它有价：帘头格 ¥2.00）"
    )
    assert re.search(r"COLLAPSE_PRICE_SOURCE_POSITION\.equals\(candidate\.getPosition\(\)\)",
                     collapsed), (
        "收敛没有「布帘列优先」这一档 —— 用户裁定「取布帘价」，少了它取哪一行不确定"
    )


def test_rule_order_is_priority_then_id():
    """判据 3b：规则按 `(priority, id)` 稳定排序（与 P2b 的实例化口径一致）。"""
    src = _java_code(SERVICE)
    assert re.search(r"comparing\(ProductionRouteRule::getPriority\)[\s\S]{0,120}?"
                     r"thenComparing\(ProductionRouteRule::getId\)", src), (
        "规则没有按 `(priority, id)` 排序（缺 `comparing(getPriority)` + `thenComparing(getId)`）"
        "—— priority 撞档时「谁先」由内部 id 决定，不钉 id ⇒ 同 priority 两行的顺序不可预测"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 4：无行丢弃过滤（端点看得见真值源的**全部**行）
# ══════════════════════════════════════════════════════════════════════════════════

def test_position_query_has_no_row_dropping_filter():
    """判据 4a：部位价目的过滤条件**恰为** `{TenantId, Deleted, Status}`。

    任何额外的值过滤（如 `.eq(getApplicable, true)` = 只返回「做」的部位、
    `.isNotNull(getUnitPrice)` = 只返回有价的）都会让矩阵**少格** —— 而「不做」与「没定价」
    在界面上必须可区分（#4433 判据 2）⇒ 全表必须整份取回（**过滤可以没有，收敛必须有** ——
    收敛在 Java 侧由 `collapseToLogical` 承担，不是靠 `.eq(...)` 把行丢掉）。
    """
    assert _eq_targets("ProductionOperationPosition") == {"TenantId", "Deleted", "Status"}, (
        f"部位价目的过滤条件漂移：{sorted(_eq_targets('ProductionOperationPosition'))} —— "
        f"只允许租户隔离 + 软删 + 停用三个条件；额外的值过滤会让矩阵少格（120 格必须整份呈现）"
    )


def test_rule_query_has_no_row_dropping_filter():
    """判据 4b：规则的过滤条件 = 上三者 + `action IN ('insert','remove')`（路线编排档）。"""
    assert _eq_targets("ProductionRouteRule") == {"TenantId", "Deleted", "Status"}, (
        f"规则的过滤条件漂移：{sorted(_eq_targets('ProductionRouteRule'))} —— "
        f"只允许租户隔离 + 软删 + 停用三个 eq；额外的值过滤会让规则区少条"
    )
    src = _java_code(SERVICE)
    assert re.search(r"\.in\(\s*ProductionRouteRule::getAction\s*,\s*ROUTE_ACTIONS\s*\)", src), (
        "规则查询没有按 `action IN ROUTE_ACTIONS`（insert/remove）过滤 —— "
        "不过滤会把 V72 搬进来的 `action='factor'` 计件系数档也返回（形状与 26 条口径都对不上）"
    )
    assert tuple(ROUTE_ACTIONS) == ("insert", "remove"), "ROUTE_ACTIONS 常量被改动"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 5：端点可见性 = 真值源全集（120 格 / 26 条，逐值）
# ══════════════════════════════════════════════════════════════════════════════════

def test_position_seed_is_visible_and_matches_truth_source():
    """判据 5a：V71 ∪ V79 的 **120 行**逐值等于 `OPERATION_POSITION_PRICES`，且每行对端点可见。

    两个半边合起来才是「端点输出 = 真值源」：① 值不漂移（改一格价目即红）；
    ② 没有任何一行被可见性过滤挡在端点之外（种成 `status='disabled'` 即红）。
    """
    raw_seed = _position_seed_rows()
    assert len(raw_seed) == 120, (
        f"部位价目**字面量**种子行数 = {len(raw_seed)}，期望 120（30 逻辑工序 × 4 部位）—— "
        f"行数不对时下面的逐值比对会退化成「比较两个残缺集合」"
    )
    # 🔴 issue #4937：终态 = 一道逻辑工序一行（四档选行收敛）⇒ 与真值源按**单键**逐值比对
    seed = _collapse_seed_rows()
    truth = _truth_positions()
    assert len(seed) == 30, f"收敛后的价目行数 = {len(seed)}，期望 30（一道逻辑工序一行）"
    assert len(truth) == 30, f"真值源 OPERATION_POSITION_PRICES 的行数 = {len(truth)}，期望 30"
    drifted = {key: (seed.get(key), truth.get(key)) for key in set(seed) | set(truth)
               if seed.get(key, (None, None, None))[:2] != truth.get(key)}
    assert not drifted, (
        f"这些格与真值源 `routing.py::OPERATION_POSITION_PRICES` 不一致（键 → (种子, 真值源)）：{drifted} "
        f"—— 两份口径漂移 ⇒ 商家看到的价目与实例化算的价不是同一个（改价直接变成工人工资）"
    )
    invisible = {key: row[2] for key, row in raw_seed.items() if row[2] != VISIBLE_STATUS}
    assert not invisible, (
        f"这些种子行对端点**不可见**（status ≠ {VISIBLE_STATUS}）：{invisible} —— "
        f"真值源里有、前端看不见 = 静默少一格/少一条规则"
    )


def test_rule_seed_is_visible_and_matches_truth_source():
    """判据 5b：V71 的 26 条规则**逐值**等于 `ROUTE_RULES`，且每行都落在端点的 `action` 过滤内。"""
    seed = _rule_seed_rows()
    assert len(seed) == 26, (
        f"规则种子行数 = {len(seed)}，期望 26（工艺变体 10 + 特殊选项 16，母单 #4423 冻结数字）"
    )
    # 🔴 issue #4962 改判：比对键**含** `position`（#4937 期间曾去掉该维；现在真值源里恰好一条
    # `韩褶 → insert 上车布 = '布帘'`，与 V71 字面量同值 ⇒ 不再投影掉它）。
    truth = _truth_rules()
    assert len(truth) == 26, f"真值源 ROUTE_RULES 条数 = {len(truth)}，期望 26"
    drifted = {key: (seed.get(key), truth.get(key)) for key in set(seed) | set(truth)
               if (seed.get(key) or (None, None))[0] != truth.get(key)}
    assert not drifted, (
        f"这些规则与真值源 `routing.py::ROUTE_RULES` 不一致（键 → (种子, 真值源)）：{drifted} —— "
        f"漂移 ⇒ 商家在规则区看到的顺序/锚点与实际实例化不同（工序顺序错 = 车间按错顺序干）"
    )
    hidden = {key: row for key, row in seed.items()
              if row[1] != VISIBLE_STATUS or key[3] not in ROUTE_ACTIONS}
    assert not hidden, (
        f"这些规则行对端点**不可见**（status ≠ {VISIBLE_STATUS} 或 action 不在 {ROUTE_ACTIONS}）："
        f"{hidden} —— 真值源里有、规则区看不见 = 静默少一条"
    )
