# case_ids: MC-012, AS-004, PG-015, CH-040
"""「声明与实际不符」的三处静态守卫（issue #4259）。

病根同族：**声明与实际不符，且没有任何东西会因此变红**。

| # | 声明处 | 实际 | 本文件的判据 |
|---|---|---|---|
| ① | `tests/agent_eval/fixtures/mibao_eval_seed.sql` Phase 3 的注释「用独立订单 EVAL-MB-ORD-0003（同客户张三）」 | Phase 3 那行的 id 与 Phase 2 撞车 ⇒ 被 `ON CONFLICT (id) DO NOTHING` **静默丢弃**；库里生效的是 Phase 2 的 `李四/13900139000` | 逐条核「每个 `EVAL-MB-ORD-*` 的声明行真的会生效」+ 注释里的客户与实际生效行一致 + 工单挂的订单与工单客户同族 |
| ② | `ProductionOperationQueryService` 类注释「30 道工序 + 6 条 部位×工艺 路线」 | 实测 `OPERATION_CATALOG` **35** 道 / `ROUTINGS` **9** 条（V56 #4234、V58 #4246 之后）—— 数字漂了注释不会跟着变（§19.2 ③） | 该注释里不得出现「N 道工序 / N 条…路线」形态 |
| ③ | `tests/unit_ci_workflows/test_production_catalog_seed.py` docstring 指向一个仓内**不存在**的测试类名（实测 `grep "class TestGuardSelfProof"` 零命中）⇒ 读者会去找它 | 已改指文件尾真实存在的注入式自证测试 | docstring 里反引号引用的测试标识符必须可在仓内解析 |

危害为什么值得一条守卫：评测种子是「用例前置真值」的来源（`.github/cases/*.yml` 的
`pre_clean` / `data_checks` 都按它写）。种子**静默少插一行** + 注释误导 ⇒ 后续写用例的人
会按**错的客户/电话**写断言，而**本地跑种子不报错、CI 也不红**。

## 判据形态：纯静态 + 注入式自证

判据全部读**文本**（种子 SQL / Java 注释 / docstring），零 DB、零 LLM、秒级。
每个判据都有**注入式自证**（本文件 `test_*_detector_*`）：在**构造的**缺陷载荷上必须报错，
否则主测试的绿只是空跑（`migao-acceptance`「不会红的断言 = 空断言」）。

## 边界（照实登记，别把「登记了」读成「治住了」）

* ① 覆盖 `orders` 表**跨 `INSERT` 语句**的 id 撞车（`ON CONFLICT (id) DO NOTHING` 的冲突键）；
  同一语句内的重复由「id 全局唯一」判据一并拦下；其它表的种子真值由既有守卫
  （`test_eval_case_asset_truth.py` / `test_eval_preclean_seed_parity.py`）覆盖。
* ③ 的扫描范围**只有** `GUARDED_DOCSTRING_FILES`（本包修复的那两个文件）—— 仓内**还有**
  同类悬空引用，属其它包的所有权，未纳入本守卫（已在 issue #4259 报告里列出，不冒充已覆盖）。
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED_SQL = REPO / "tests" / "agent_eval" / "fixtures" / "mibao_eval_seed.sql"
JAVA_SERVICE = (REPO / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
                / "admin" / "service" / "ProductionOperationQueryService.java")
# ③ 的扫描范围：本包修复的文件（不做全仓扫描 —— 存量同类悬空引用不属本包所有权）
GUARDED_DOCSTRING_FILES = (
    REPO / "tests" / "unit_ci_workflows" / "test_production_catalog_seed.py",
    Path(__file__).resolve(),
)

_EVAL_ORDER_NO_RE = re.compile(r"^EVAL-MB-ORD-\d+$")


# ── SQL 解析（纯函数；口径与 test_production_catalog_seed.py 的 parse_seed 一致）──

def _split_rows(values_block: str) -> list[str]:
    """把 `VALUES (...), (...)` 拆成行（尊重单引号内的逗号与括号）。"""
    rows, depth, current, in_quote = [], 0, "", False
    for ch in values_block:
        if ch == "'":
            in_quote = not in_quote
        if not in_quote:
            if ch == "(":
                depth += 1
                if depth == 1:
                    current = ""
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    rows.append(current)
                    current = ""
                    continue
        if depth >= 1:
            current += ch
    return [r for r in (row.strip() for row in rows) if r]


def _split_fields(row: str) -> list[str]:
    """按顶层逗号切字段（尊重单引号与 `[...]::jsonb` 内的逗号）。"""
    fields, current, in_quote, depth = [], "", False, 0
    for ch in row:
        if ch == "'":
            in_quote = not in_quote
        if not in_quote:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "," and depth == 0:
                fields.append(current.strip())
                current = ""
                continue
        current += ch
    fields.append(current.strip())
    return fields


def _literal(raw: str | None):
    """SQL 字面量 → Python 值（只处理本判据用得到的形态）。"""
    text = (raw or "").strip()
    if text.upper() == "NULL":
        return None
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def _table_rows(sql: str, table: str) -> list[dict]:
    """该表**全部** `INSERT INTO … VALUES` 段聚合为行字典。

    跨语句聚合是本判据的关键：同族缺陷的形态正是「两条 INSERT 各写一行、id 相同」——
    只看单条语句永远看不出撞车（issue #4259 ①）。
    """
    rows: list[dict] = []
    pattern = (r"INSERT\s+INTO\s+" + table
               + r"\b\s*\(([^)]*)\)\s*VALUES(.*?)(?:ON\s+CONFLICT|;)")
    for match in re.finditer(pattern, sql, re.S | re.I):
        columns = [c.strip() for c in match.group(1).split(",")]
        for raw in _split_rows(match.group(2)):
            fields = _split_fields(raw)
            assert len(fields) == len(columns), (
                f"{table} 种子行字段数 {len(fields)} ≠ 列数 {len(columns)}"
                f"（列序漂移即解析错位）: {raw[:120]}")
            rows.append(dict(zip(columns, fields)))
    return rows


def _effective_order_rows(sql: str) -> dict[str, dict]:
    """**真的会插进库里**的 `order_no` → 行。

    `ON CONFLICT (id) DO NOTHING` ⇒ **先到者胜、后到者整行被丢弃**（不报错、不警告）。
    故这里按 id 首次出现取行 —— 与数据库的实际行为同口径。
    """
    effective: dict[str, dict] = {}
    seen_ids: set = set()
    for row in _table_rows(sql, "orders"):
        order_id = _literal(row.get("id"))
        if order_id in seen_ids:
            continue
        seen_ids.add(order_id)
        effective[_literal(row.get("order_no"))] = row
    return effective


# ── ① 判据 ──────────────────────────────────────────────────────────────────

def _shadowed_order_declarations(sql: str) -> list[str]:
    """声明了却**不会生效**的 `EVAL-MB-ORD-*` 订单（id / order_no 撞车 ⇒ 静默丢弃）。"""
    rows = _table_rows(sql, "orders")
    id_counts = Counter(_literal(r.get("id")) for r in rows)
    no_counts = Counter(_literal(r.get("order_no")) for r in rows)
    problems: list[str] = []
    seen_ids: set = set()
    for row in rows:
        order_id = _literal(row.get("id"))
        order_no = _literal(row.get("order_no"))
        if not _EVAL_ORDER_NO_RE.match(order_no or ""):
            seen_ids.add(order_id)
            continue
        if id_counts[order_id] > 1 and order_id in seen_ids:
            problems.append(
                f"{order_no}（id={order_id}）不会生效：该 id 已被前一条 INSERT 占用 ⇒ "
                f"本行被 `ON CONFLICT (id) DO NOTHING` **静默丢弃**，"
                f"这个 order_no 在库里从未存在")
        seen_ids.add(order_id)
    for order_no, count in no_counts.items():
        if count > 1 and _EVAL_ORDER_NO_RE.match(order_no or ""):
            problems.append(f"{order_no} 被声明了 {count} 次（order_no 重复 ⇒ 落点不确定）")
    return problems


_DECLARED_CUSTOMER_RE = re.compile(
    r"EVAL-MB-ORD-(\d+)[^()（）\n]{0,24}[（(]\s*同客户\s*([\u4e00-\u9fa5]{2,4})\s*[）)]")


def _declared_customer_mismatches(sql: str) -> list[str]:
    """注释里「`EVAL-MB-ORD-N`（同客户X）」的声明与**实际生效**行的客户不一致。"""
    effective = _effective_order_rows(sql)
    problems: list[str] = []
    for suffix, declared_name in _DECLARED_CUSTOMER_RE.findall(sql):
        order_no = f"EVAL-MB-ORD-{suffix}"
        row = effective.get(order_no)
        if row is None:
            problems.append(
                f"注释声明 {order_no} 是「同客户{declared_name}」，但没有任何一行真的插入了它")
            continue
        actual_name = _literal(row.get("customer_name"))
        actual_phone = _literal(row.get("customer_phone"))
        if actual_name != declared_name:
            problems.append(
                f"注释声明 {order_no} 是「同客户{declared_name}」，而**实际生效**的行是 "
                f"{actual_name}/{actual_phone} ⇒ 注释描述的是一个从未被插入的状态")
    return problems


def _ticket_customer_mismatches(sql: str) -> list[str]:
    """售后工单挂的订单必须与**工单客户**同族（种子自洽不变式，非生产规则）。"""
    orders_by_id: dict = {}
    seen_ids: set = set()
    for row in _table_rows(sql, "orders"):
        order_id = _literal(row.get("id"))
        if order_id in seen_ids:
            continue
        seen_ids.add(order_id)
        orders_by_id[order_id] = row
    profiles = {_literal(r.get("id")): r for r in _table_rows(sql, "customer_profiles")}
    problems: list[str] = []
    for ticket in _table_rows(sql, "after_sales_tickets"):
        ticket_no = _literal(ticket.get("ticket_no"))
        order = orders_by_id.get(_literal(ticket.get("order_id")))
        customer = profiles.get(_literal(ticket.get("customer_id")))
        if order is None or customer is None:
            problems.append(
                f"工单 {ticket_no} 的 order_id={_literal(ticket.get('order_id'))} / "
                f"customer_id={_literal(ticket.get('customer_id'))} 在种子内解析不到")
            continue
        if _literal(order.get("customer_phone")) != _literal(customer.get("phone")):
            problems.append(
                f"工单 {ticket_no} 挂的订单 {_literal(order.get('order_no'))}"
                f"（{_literal(order.get('customer_name'))}/{_literal(order.get('customer_phone'))}）"
                f"与工单客户 {_literal(ticket.get('customer_id'))}"
                f"（{_literal(customer.get('wechat_nickname'))}/{_literal(customer.get('phone'))}）"
                f"不是同一个客户 ⇒ 工单挂错了对象")
    return problems


def test_every_eval_order_is_really_inserted():
    """① 每个 `EVAL-MB-ORD-*` 都必须有一行**真的会生效**（不是被 `ON CONFLICT` 丢掉）。"""
    sql = SEED_SQL.read_text(encoding="utf-8")
    declared = sorted({_literal(r.get("order_no")) for r in _table_rows(sql, "orders")
                       if _EVAL_ORDER_NO_RE.match(_literal(r.get("order_no")) or "")})
    assert declared, "解析不出任何 EVAL-MB-ORD-* 订单（本守卫会静默空跑）"
    effective = _effective_order_rows(sql)
    missing = [no for no in declared if no not in effective]
    assert missing == [], f"这些订单在库里根本不存在（整行被丢弃）：{missing}"
    problems = _shadowed_order_declarations(sql)
    assert problems == [], "种子声明了这些订单但**不会真的插入**：\n  - " + "\n  - ".join(problems)


def test_comment_declared_customer_matches_the_inserted_row():
    """① 注释里声明的客户/电话必须与该 order_no **实际生效**的行一致。"""
    sql = SEED_SQL.read_text(encoding="utf-8")
    declared = _DECLARED_CUSTOMER_RE.findall(sql)
    assert declared, ("种子注释里没有可判定的「EVAL-MB-ORD-N（同客户X）」声明"
                      "（本守卫会静默空跑）")
    problems = _declared_customer_mismatches(sql)
    assert problems == [], "注释与实际生效值不符：\n  - " + "\n  - ".join(problems)


def test_aftersales_ticket_hangs_on_an_order_of_the_same_customer():
    """① 工单挂的订单必须与工单客户同族（否则工单承载的订单与客户是两个世界）。"""
    sql = SEED_SQL.read_text(encoding="utf-8")
    tickets = _table_rows(sql, "after_sales_tickets")
    assert tickets, "解析不出任何售后工单种子（本守卫会静默空跑）"
    problems = _ticket_customer_mismatches(sql)
    assert problems == [], "工单与所挂订单不同族：\n  - " + "\n  - ".join(problems)


# ── ② 判据 ──────────────────────────────────────────────────────────────────

# 「不写死易变数字」（§19.2 ③）的形态判据：工序数 / 路线数会随迁移漂移
_VOLATILE_CATALOG_COUNT_RE = re.compile(r"\d+\s*道工序|\d+\s*条[^。；\n]{0,12}?路线")


def _hardcoded_catalog_counts(text: str) -> list[str]:
    return [f"第 {no} 行：{line.strip()}"
            for no, line in enumerate(text.splitlines(), 1)
            if _VOLATILE_CATALOG_COUNT_RE.search(line)]


def test_java_service_javadoc_does_not_hardcode_catalog_counts():
    """② 注释里不得写死工序数 / 路线数（数字会漂，注释不会跟着变）。"""
    hits = _hardcoded_catalog_counts(JAVA_SERVICE.read_text(encoding="utf-8"))
    assert hits == [], (
        "注释写死了易变的工序数/路线数 → 数字漂了就变成假声明（issue #4259 ②）。"
        "改成「工序库目录 + 工艺路线模板」这类不随迁移漂移的表述：\n  - "
        + "\n  - ".join(hits))


# ── ③ 判据 ──────────────────────────────────────────────────────────────────

_REFERENCED_TEST_RE = re.compile(r"`(Test[A-Z]\w*|test_[a-z0-9_]+)`")
_PY_SCAN_ROOTS = (REPO / "tests", REPO / "backend")
_PRUNED_PARTS = {"node_modules", ".venv", "venv", ".git", "target", "build", "dist",
                 "__pycache__", ".next"}
_DEFINED_TEST_RE = re.compile(
    r"^\s*(?:class|def)\s+(Test[A-Za-z0-9_]*|test_[a-z0-9_]+)\s*[(:]", re.M)


def _defined_test_names() -> set[str]:
    """仓内（`tests/` ∪ `backend/`）真实存在的测试类 / 测试函数名。"""
    names: set[str] = set()
    for root in _PY_SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if _PRUNED_PARTS & set(path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            names.update(_DEFINED_TEST_RE.findall(text))
    return names


def _unresolvable_test_refs(docstring: str, defined: set[str]) -> set[str]:
    return {ref for ref in _REFERENCED_TEST_RE.findall(docstring) if ref not in defined}


def test_guarded_docstrings_only_reference_existing_tests():
    """③ docstring 里反引号引用的测试标识符必须在仓内可解析（防「过期引用」）。"""
    defined = _defined_test_names()
    referenced: dict[str, set[str]] = {}
    for path in GUARDED_DOCSTRING_FILES:
        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        for ref in _REFERENCED_TEST_RE.findall(docstring):
            referenced.setdefault(ref, set()).add(path.name)
    assert referenced, "被守卫的 docstring 里零个测试名引用（本守卫会静默空跑）"
    missing = {ref: sorted(files) for ref, files in referenced.items() if ref not in defined}
    assert missing == {}, (
        f"docstring 引用了仓内**不存在**的测试标识符 {missing} ⇒ 读者会去找它（issue #4259 ③）")


# ── 注入式自证（每个判据都必须能红，否则上面全绿 = 空跑）─────────────────────

_SEED_HEADER = "INSERT INTO orders (id, order_no, customer_name, customer_phone) VALUES\n"


def test_shadowed_order_detector_reddens_on_injected_duplicate_id():
    good = (_SEED_HEADER
            + "  ('id-a', 'EVAL-MB-ORD-0001', '张三', '13800138000')\n"
              "ON CONFLICT (id) DO NOTHING;\n")
    bad = (good
           + _SEED_HEADER
           + "  ('id-a', 'EVAL-MB-ORD-0009', '李四', '13900139000')\n"
             "ON CONFLICT (id) DO NOTHING;\n")
    assert _shadowed_order_declarations(good) == [], "合法载荷不应报问题（判据不得恒真）"
    injected = _shadowed_order_declarations(bad)
    assert len(injected) == 1, f"注入 id 撞车后判据没红 ⇒ 主测试是空断言：{injected}"
    assert "EVAL-MB-ORD-0009" in injected[0]
    # 「真的会生效」的那份映射也要能照出差别（否则 missing 断言是空断言）
    assert "EVAL-MB-ORD-0009" not in _effective_order_rows(bad)


def test_declared_customer_detector_reddens_on_injected_mismatch():
    good = ("-- 用独立订单 EVAL-MB-ORD-0003（同客户李四）承载本次工单\n"
            + _SEED_HEADER
            + "  ('id-a', 'EVAL-MB-ORD-0003', '李四', '13900139000')\n"
              "ON CONFLICT (id) DO NOTHING;\n")
    bad = good.replace("（同客户李四）", "（同客户张三）")
    assert bad != good, "注入没生效（替换未命中）⇒ 下面的红证不成立"
    assert _declared_customer_mismatches(good) == [], "合法载荷不应报问题（判据不得恒真）"
    injected = _declared_customer_mismatches(bad)
    assert len(injected) == 1, f"注入「注释说张三、实际李四」后判据没红 ⇒ 空断言：{injected}"
    assert "李四" in injected[0]


def test_ticket_customer_detector_reddens_on_injected_mismatch():
    good = (
        "INSERT INTO customer_profiles (id, phone, wechat_nickname) VALUES\n"
        "  ('cust_zhangsan', '13800138000', '张三')\n"
        "ON CONFLICT (id) DO NOTHING;\n"
        + _SEED_HEADER
        + "  ('id-a', 'EVAL-MB-ORD-0003', '张三', '13800138000')\n"
          "ON CONFLICT (id) DO NOTHING;\n"
          "INSERT INTO after_sales_tickets (id, ticket_no, order_id, customer_id) VALUES\n"
          "  ('tkt-1', 'AS-20260914-9001', 'id-a', 'cust_zhangsan')\n"
          "ON CONFLICT (id) DO NOTHING;\n")
    bad = good.replace("('id-a', 'EVAL-MB-ORD-0003', '张三', '13800138000')",
                       "('id-a', 'EVAL-MB-ORD-0003', '李四', '13900139000')")
    assert bad != good, "注入没生效（替换未命中）⇒ 下面的红证不成立"
    assert _ticket_customer_mismatches(good) == [], "合法载荷不应报问题（判据不得恒真）"
    injected = _ticket_customer_mismatches(bad)
    assert len(injected) == 1, f"注入「工单客户与订单客户不同族」后判据没红 ⇒ 空断言：{injected}"
    assert "李四" in injected[0]


def test_volatile_count_detector_reddens_on_injected_counts():
    stale = (" * 本类补上「可查询/可展示」这一半：读 V54 种子（`app/production/routing.py` 的 30 道工序\n"
             " * + 6 条 部位×工艺 路线）并按展示口径整形。</p>\n")
    stable = (" * 本类补上「可查询/可展示」这一半：读工序库目录 + 工艺路线模板并按展示口径整形。</p>\n")
    assert _hardcoded_catalog_counts(stable) == [], "不写数字的表述不应报问题（判据不得恒真）"
    hits = _hardcoded_catalog_counts(stale)
    assert len(hits) == 2, f"注入写死的工序数/路线数后判据没红 ⇒ 空断言：{hits}"


def test_stale_reference_detector_reddens_on_injected_dangling_name():
    defined = {"test_real_guard"}
    assert _unresolvable_test_refs("红证见文件尾 `test_real_guard`", defined) == set()
    dangling = _unresolvable_test_refs("红证见文件尾 `TestGuardSelfProof`", defined)
    assert dangling == {"TestGuardSelfProof"}, (
        f"注入悬空引用后判据没红 ⇒ 空断言：{dangling}")
