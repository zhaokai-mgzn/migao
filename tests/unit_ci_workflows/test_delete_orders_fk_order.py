# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：脚本/CI 结构类 L0 不变式统一挂 MC-012 ——
#   `.github/cases/misc.yml` 的 MC-012 已登记「CI/工具链结构由 tests/unit_ci_workflows/ 单测验证，
#   skip_reason = [backend-contract]，不进 agent-eval 冒烟」。本文件同属该形态：零真实 DB。）
"""L0 红证：`scripts/delete_orders.py` 的删除拓扑必须覆盖 schema 真值的**全部**外键依赖层。

## 病灶（issue #4242，2026-09-18 走查实测）

V49 给 `processing_position_operations`（工序实例）与 `production_work_logs`（报工明细）
加了指向 `processing_orders` 的外键，而删除脚本只知道 V43 时代的
`processing_orders → order_items → orders` 三层 ⇒ 任何生成过加工单的订单都删不掉：

    ForeignKeyViolationError: update or delete on table "processing_orders" violates
    foreign key constraint "processing_position_operations_processing_order_id_fkey"

## 本文件怎么拿到「红证」（不连任何真实 DB）

用**假 asyncpg 连接**驱动脚本真实代码路径（`asyncio.run(run(...))`），把它**按顺序执行的
SQL** 记下来，再与**从 `docs/sql/schema.sql` 现场抽出的外键边**对照 —— 表名清单**不写死**，
schema 加了新外键就自动要求删除计划跟上（这是防"下次再加一层依赖又漏"的护栏）。

RED 钩子：`DELETE_ORDERS_SCRIPT=/tmp/orig/delete_orders.py` 可把被测脚本换成改动前版本
（复现「改前红 / 改后绿」两次输出）；CI 不设该变量，恒测仓库内真身。
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "docs" / "sql" / "schema.sql"
MIGRATIONS = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration"

# issue #4242 判据 1 的显式序列（前两级经加工单定位），末尾 `order_logistics` 是
# schema 真值补出的第三层漏项（见报告「外键链核对表」）。
EXPECTED_DELETE_ORDER = (
    "production_work_logs",
    "processing_position_operations",
    "processing_orders",
    "order_items",
    "order_logistics",
    "orders",
)

ORDER_NO = "20260918392560001"
ORDER_ID = "a1b2c3d4-e5f6-4a7b-8c9d-000000000042"
PO_ID = "f47a332fadea30d7114993ad92ab87df"
PO_NO = "JG20260918001"
OP_IDS = tuple(f"op{i:064d}" for i in range(1, 12))  # 11 道工序实例

ORDER_ROWS = [{
    "id": ORDER_ID, "order_no": ORDER_NO, "status": "producing",
    "customer_name": "走查测试客户", "remark": None,
}]
PO_ROWS = [{
    "id": PO_ID, "order_id": ORDER_ID, "processing_order_no": PO_NO, "status": "in_processing",
}]
# dry-run 应报出的行数（= 实际将被删除的行数；由计划派生的 COUNT 查询取回）
COUNTS = {
    "production_work_logs": 1,
    "processing_position_operations": 11,
    "processing_orders": 1,
    "order_items": 2,
    "order_logistics": 1,
    "orders": 1,
}


# ─────────────────────────── schema 真值（现场抽取，不写死） ───────────────────────────

_CREATE_RE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.I)
_ALTER_RE = re.compile(r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I)
_REF_RE = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.I)


def _fk_edges_in(path: Path) -> set:
    """抽出单文件里的 (子表 → 父表) 外键边；同时支持 CREATE TABLE 块与 ALTER TABLE ... ADD COLUMN。"""
    edges = set()
    current, in_create = None, False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("--", 1)[0]
        if not line.strip():
            continue
        m = _CREATE_RE.match(line)
        if m:
            current, in_create = m.group(1), True
            continue
        m = _ALTER_RE.match(line)
        if m:
            current, in_create = m.group(1), False
        if current is None:
            continue
        for parent in _REF_RE.findall(line):
            edges.add((current, parent))
        if in_create and line.strip().startswith(")"):
            current = None
        elif not in_create and ";" in line:
            current = None
    return edges


def schema_fk_edges() -> set:
    """外键边真值 = `docs/sql/schema.sql`（合并后的完整建库脚本）+ 迁移链里的显式加列外键。

    ⚠️ 不含 `docs/sql/schema_full.sql` —— 该文件头部自述「已废弃（DEPRECATED）、两个方向都已失真」，
    是 2026-05-30 的快照（连 processing_orders 都没有）；拿它当真相 = 读落后副本。
    """
    edges = _fk_edges_in(SCHEMA_SQL)
    for f in sorted(MIGRATIONS.glob("*.sql")):
        edges |= _fk_edges_in(f)
    return edges


def required_deletion_tables() -> set:
    """必须早于 `orders` 被删的表闭包：凡（直接或经加工单间接）引用 orders 的表都算。"""
    edges = schema_fk_edges()
    needed = {"orders"}
    changed = True
    while changed:
        changed = False
        for child, parent in edges:
            if parent in needed and child not in needed:
                needed.add(child)
                changed = True
    return needed


# ─────────────────────────── 假 asyncpg：零真实 DB 驱动真身代码路径 ───────────────────────────

_TABLE_RE = re.compile(r"(?:DELETE\s+FROM|FROM)\s+(\w+)", re.I)


def _table_of(sql: str) -> str:
    m = _TABLE_RE.search(sql)
    assert m, f"无法从 SQL 解析表名: {sql}"
    return m.group(1)


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    """记录脚本**按顺序**执行的 SQL；`fetchval` 按表名回预置行数。"""

    def __init__(self, orders, processing_orders, counts):
        self._orders = orders
        self._po = processing_orders
        self._counts = counts
        self.sql_log = []   # [(kind, table, sql, args)]

    async def fetch(self, sql, *args):
        table = _table_of(sql)
        self.sql_log.append(("fetch", table, sql, args))
        if table == "orders":
            return self._orders
        if table == "processing_orders":
            return self._po
        raise AssertionError(f"未预期的 fetch：{sql}")

    async def fetchval(self, sql, *args):
        table = _table_of(sql)
        self.sql_log.append(("fetchval", table, sql, args))
        return self._counts.get(table, 0)

    async def execute(self, sql, *args):
        table = _table_of(sql)
        self.sql_log.append(("execute", table, sql, args))
        return "DELETE 1"

    def transaction(self):
        return _FakeTx()

    async def close(self):
        return None

    # ── 断言用取景器 ──
    @property
    def deleted_tables(self) -> list:
        return [t for kind, t, _, _ in self.sql_log if kind == "execute"]

    def deletes(self) -> list:
        return [(t, sql, args) for kind, t, sql, args in self.sql_log if kind == "execute"]

    def selects(self) -> list:
        return [(t, sql, args) for kind, t, sql, args in self.sql_log if kind != "execute"]


def load_script():
    """被测脚本（`DELETE_ORDERS_SCRIPT` 仅用于红证时指向改动前版本；CI 不设）。"""
    path = Path(os.environ.get("DELETE_ORDERS_SCRIPT", REPO_ROOT / "scripts" / "delete_orders.py"))
    assert path.is_file(), f"被测脚本不存在: {path}"
    spec = importlib.util.spec_from_file_location("_delete_orders_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(conn, order_nos, env_file, apply=False):
    """注入假 asyncpg 后跑脚本真身（脚本在 run() 内 `import asyncpg`，故只需替 sys.modules）。"""
    mod = load_script()
    fake = types.ModuleType("asyncpg")

    async def _connect(**kwargs):
        conn.connect_kwargs = kwargs
        return conn

    fake.connect = _connect
    saved = sys.modules.get("asyncpg")
    sys.modules["asyncpg"] = fake
    try:
        return asyncio.run(mod.run(list(order_nos), env_file, apply))
    finally:
        if saved is None:
            sys.modules.pop("asyncpg", None)
        else:
            sys.modules["asyncpg"] = saved


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / "rds.env"
    p.write_text("RDS_HOST=127.0.0.1\nRDS_PORT=55432\nRDS_USER=tester\nRDS_PASSWORD=pw\nRDS_DB=ai_customer_service\n",
                 encoding="utf-8")
    return p


@pytest.fixture
def full_conn():
    return FakeConn(list(ORDER_ROWS), list(PO_ROWS), dict(COUNTS))


# ─────────────────────────── 判据：删除计划 = schema 真值的依赖闭包 + 拓扑序 ───────────────────────────

def test_plan_covers_every_table_referencing_orders(full_conn, env_file):
    """凡引用 orders / processing_orders 的表，都必须出现在删除计划里（漏一层 ⇒ 删到父表时 FK 报错）。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    done = set(full_conn.deleted_tables)
    missing = required_deletion_tables() - done
    assert not missing, (
        f"删除计划漏掉了 schema 真值里引用 orders/processing_orders 的表：{sorted(missing)}；"
        f"实际只删了 {full_conn.deleted_tables}"
    )


def test_delete_order_is_topological(full_conn, env_file):
    """被引用表必须先于引用表被删（否则父表 DELETE 被外键拦下）。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    order = full_conn.deleted_tables
    pos = {t: i for i, t in enumerate(order)}
    constrained = [(c, p) for c, p in schema_fk_edges() if c in pos and p in pos]
    # 禁空跑：被删表之间若没有任何外键约束对，这条拓扑断言就是空断言（假绿）
    assert constrained, f"被删表之间没有任何外键约束对 ⇒ 拓扑断言空跑：{order}"
    violations = [(c, p) for c, p in constrained if pos[c] > pos[p]]
    assert not violations, f"删除顺序违反外键拓扑（子表必须先删）: {violations}；实际顺序 = {order}"


def test_delete_order_matches_issue_4242_spec(full_conn, env_file):
    """issue #4242 判据 1 的显式序列（含 schema 真值补出的 order_logistics）。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    assert tuple(full_conn.deleted_tables) == EXPECTED_DELETE_ORDER


def test_new_levels_located_through_processing_orders(full_conn, env_file):
    """前两级（报工 / 工序实例）必须经**该订单的加工单 id** 定位，而不是直接按 order_id 猜。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    by_table = {t: (sql, args) for t, sql, args in full_conn.deletes()}
    for table in ("production_work_logs", "processing_position_operations"):
        sql, args = by_table[table]
        assert "processing_order_id = ANY($1::text[])" in sql, sql
        assert list(args[0]) == [PO_ID], f"{table} 应以加工单 id 定位，实际参数 = {args}"
    assert "order_id = ANY($1::text[])" in by_table["processing_orders"][0]
    assert "id = ANY($1::text[])" in by_table["orders"][0]


def test_dry_run_reports_every_level(full_conn, env_file, capsys):
    """判据 3：dry-run 汇总必须报出工序实例与报工行数（否则低报删除量）+ 不执行任何 DELETE。"""
    rc = run_script(full_conn, [ORDER_NO], env_file)
    out = capsys.readouterr().out
    assert rc == 0
    assert full_conn.deletes() == [], f"dry-run 不应执行删除，实际执行了 {full_conn.deletes()}"
    for label, n in (("报工", "1"), ("工序实例", "11"), ("加工单", "1"),
                     ("订单明细", "2"), ("物流", "1"), ("订单", "1")):
        assert f"{label} {n} 行" in out, f"dry-run 汇总缺「{label} {n} 行」：\n{out}"


def test_apply_prints_every_level(full_conn, env_file, capsys):
    """--apply 的结果行同样逐级报数（与删除计划同源）。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    out = capsys.readouterr().out
    assert "✅ 已删除" in out
    for label in ("报工", "工序实例", "加工单", "订单明细", "物流", "订单"):
        assert label in out.split("✅ 已删除", 1)[1], f"--apply 结果行缺「{label}」：\n{out}"


# ─────────────────────────── 不回归：安全设计（精确匹配 / apply 闸门 / V43 形态） ───────────────────────────

def test_only_explicit_order_no_exact_match(full_conn, env_file):
    """安全设计保留：仅按显式 order_no 精确匹配，无通配/模糊/条件/批量删除。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    table, sql, args = full_conn.selects()[0]
    assert table == "orders", sql
    assert "order_no = ANY($1::text[])" in sql, sql
    assert "LIKE" not in sql.upper() and "%" not in sql, f"订单定位退化为模糊匹配：{sql}"
    assert list(args[0]) == [ORDER_NO], f"参数必须是显式订单号原样：{args}"
    for _, del_sql, _ in full_conn.deletes():
        upper = del_sql.upper()
        assert "LIKE" not in upper and " OR " not in upper and "NOT IN" not in upper, del_sql


def test_v43_only_order_still_deletes(env_file):
    """判据 4 不回归：无生产数据（V43 形态）的订单仍能正常删除。"""
    conn = FakeConn(list(ORDER_ROWS), [], {"orders": 1, "order_items": 2})
    rc = run_script(conn, [ORDER_NO], env_file, apply=True)
    assert rc == 0
    assert tuple(conn.deleted_tables) == EXPECTED_DELETE_ORDER


def test_soft_deleted_children_are_still_located(env_file, capsys):
    """软删的加工单同属被删对象 ⇒ 其工序实例/报工也须被定位（否则删父表时 FK 报错）。"""
    conn = FakeConn(list(ORDER_ROWS), list(PO_ROWS), dict(COUNTS))
    run_script(conn, [ORDER_NO], env_file)
    po_sql = [sql for t, sql, _ in conn.selects() if t == "processing_orders"]
    assert po_sql, "必须查询加工单"
    assert "deleted = 0" not in po_sql[0], (
        f"加工单查询带 deleted=0，会漏掉软删加工单的子行 ⇒ 删父表时 FK 报错：{po_sql[0]}"
    )


def test_empty_order_nos_is_rejected(monkeypatch, capsys):
    """`--order-nos` 为空必须拒绝（退出码 2），绝不退化成"删空条件"式批量删除。"""
    mod = load_script()
    monkeypatch.setattr(sys, "argv", ["delete_orders.py", "--order-nos", " , "])
    assert mod.main() == 2
    assert "为空" in capsys.readouterr().err
