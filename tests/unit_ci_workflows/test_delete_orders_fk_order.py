# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：脚本/CI 结构类 L0 不变式统一挂 MC-012 ——
#   `.github/cases/misc.yml` 的 MC-012 已登记「CI/工具链结构由 tests/unit_ci_workflows/ 单测验证，
#   skip_reason = [backend-contract]，不进 agent-eval 冒烟」。本文件同属该形态：零真实 DB。）
"""L0 红证：`scripts/delete_orders.py` 的删除拓扑必须覆盖 schema 真值的**全部**依赖层。

## 病灶（issue #4242 / #7633，走查实测）

- **#4242**：V49 给 `processing_position_operations`（工序实例）与 `production_work_logs`（报工明细）
  加了指向 `processing_orders` 的外键，而删除脚本只知道 V43 时代的
  `processing_orders → order_items → orders` 三层 ⇒ 任何生成过加工单的订单都删不掉：

      ForeignKeyViolationError: update or delete on table "processing_orders" violates
      foreign key constraint "processing_position_operations_processing_order_id_fkey"

- **#7633**（2026-10-24）：计划缺「售后 / 发货 / 收款」三族（`after_sales_tickets` /
  `ticket_timeline` / `ticket_notes` / `rework_orders` / `order_shipments` / `order_shipment_items` /
  `finance_transactions`）以及 `receipt_allocations` 的 `transaction_id` 一侧 ⇒ 带收款 / 售后 / 发货的
  订单删不掉，最后只能手写 SQL（实测 `finance_transactions` 55 行、`ticket_timeline` 23 行…）。

## 本文件怎么拿到「红证」（不连任何真实 DB）

用**假 asyncpg 连接**驱动脚本真实代码路径（`asyncio.run(run(...))`），把它**按顺序执行的
SQL** 记下来，再与**从 `backend/admin-api/src/main/resources/db/init/schema.sql` + 迁移链现场抽出的
依赖真值**对照 —— 表名清单**不写死**，schema 加了新依赖就自动要求删除计划跟上
（这是防"下次再加一层依赖又漏"的护栏）。依赖真值有**两类**：

1. **真外键边**（`REFERENCES`）—— 删父表会被数据库直接拦下；
2. **`order_id` 列**（issue #7633）—— `after_sales_tickets` / `order_shipments` / `finance_transactions`
   的 `order_id` **没有**外键约束（应用层维护），但数据同样属于这张订单 ⇒ 不进计划就留孤儿。

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
SCHEMA_SQL = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from unit_ci_workflows._migration_paths import migration_files  # noqa: E402

# issue #4242 判据 1 的显式序列（前两级经加工单定位），末尾 `order_logistics` 是
# schema 真值补出的第三层漏项（见报告「外键链核对表」）。
# ⚠️ **本序列必须随依赖真值一起长**（本文件的 `test_plan_covers_every_table_referencing_orders`
# 就是从 schema 反推闭包来守它的）：
# issue #4698 切片 ⓪ 的 V92 新增两层 —— `processing_set_part_tokens`（码行，引用套行）必须排在
# `processing_order_sets` **之前**，两者都在 `processing_orders` 之前。
# issue #7370 段 3 的 V176 又加一层：`receipt_allocations`（收款核销明细）引用 `orders` ⇒ 早于 `orders`。
EXPECTED_DELETE_ORDER = (
    # V94（issue #4709）新增：补价动作账引用 **processing_orders** 与 **processing_position_operations**
    # 两张父表 ⇒ 必须最先删（`test_plan_covers_every_table_referencing_orders` 会自动要求它出现；
    # 本元组是 issue #4242 判据 1 的**显式序列**，故新增一层时同步在这里显式化）。
    # V98（issue #4733）新增：报工身份旁路账引用 **processing_orders** 与 **production_work_logs**
    # 的语义父行 ⇒ 与 production_work_logs 同层最先删（`test_plan_covers_every_table_referencing_orders`
    # 会自动要求它出现；本元组是 issue #4242 判据 1 的**显式序列**，故新增一层时同步显式化）。
    # V157（issue #5652）新增：质检记录（成品帘级）同时引用 processing_orders 与 order_items
    # ⇒ 必须最先删（`test_plan_covers_every_table_referencing_orders` 会自动要求它出现）。
    "quality_inspections",
    "worker_report_audits",
    "production_instance_repricing_logs",
    # #7633 新增（售后族）：工单时间线 / 工单备注 / 返工单都引用 `after_sales_tickets(id)`（真外键）
    # ⇒ 必须早于售后工单；返工单还带 `order_id`（语义引用），故排在加工单之前。
    "ticket_timeline",
    "ticket_notes",
    "rework_orders",
    "production_work_logs",
    "processing_position_operations",
    "processing_set_part_tokens",
    "processing_order_sets",
    "processing_orders",
    # #7633 新增（发货族）：`order_shipment_items.shipment_id` 是真外键 ⇒ 早于发货单；
    # 明细也带 `order_id` / `order_item_id`（语义引用）⇒ 早于订单明细。
    "order_shipment_items",
    "order_shipments",
    "order_items",
    "order_logistics",
    # V201（issue #7902）新增：打印流水的是**语义**引用（无外键，但属该订单的审计行）
    # ⇒ 与物流同层、早于 orders 删（否则删单后留下孤儿「已打印」读数）。
    "print_logs",
    # #7633 新增（售后工单本体）：`after_sales_tickets.order_id` 无外键但语义属该订单 ⇒ 早于 orders。
    "after_sales_tickets",
    # V176（issue #7370 段 3）新增：收款核销明细引用 **orders**（order_id 是真外键）⇒ 必须早于 orders 删；
    # #7633 补上它的 **transaction_id 一侧**（引用 finance_transactions 的真外键）⇒ 必须早于收款流水。
    "receipt_allocations",
    # #7633 新增（收款族）：`finance_transactions.order_id` 无外键但语义属该订单 ⇒ 早于 orders。
    "finance_transactions",
    # V196（issue #7750）新增：成品在库 / 出库单 / 出库明细 / 入库明细都带 `order_id`
    # （成品在库、出库单、入库明细是真外键；出库明细的 outbound_order_id 是外键）⇒ 全部早于 orders。
    "outbound_order_items",
    "outbound_orders",
    "inbound_order_items",
    "finished_goods_stock",
    "orders",
)

ORDER_NO = "20260918392560001"
ORDER_ID = "a1b2c3d4-e5f6-4a7b-8c9d-000000000042"
PO_ID = "f47a332fadea30d7114993ad92ab87df"
PO_NO = "JG20260918001"
TICKET_ID = "d7c1e2f3-a4b5-4c6d-8e9f-000000007633"
SHIPMENT_ID = "b8e2f4a6-c1d3-4e5f-9a7b-000000007633"
TXN_ID = "c9f3a5b7-d2e4-4f60-8b1c-000000007633"
OP_IDS = tuple(f"op{i:064d}" for i in range(1, 12))  # 11 道工序实例

ORDER_ROWS = [{
    "id": ORDER_ID, "order_no": ORDER_NO, "status": "producing",
    "customer_name": "走查测试客户", "remark": None, "deleted": 0,
}]
PO_ROWS = [{
    "id": PO_ID, "order_id": ORDER_ID, "processing_order_no": PO_NO, "status": "in_processing",
}]
# 子表父 id 的预取结果（脚本先查父 id、再按父 id 定位子行）
TICKET_ROWS = [{"id": TICKET_ID}]
SHIPMENT_ROWS = [{"id": SHIPMENT_ID}]
TXN_ROWS = [{"id": TXN_ID}]
# dry-run 应报出的行数（= 实际将被删除的行数；由计划派生的 COUNT 查询取回）
COUNTS = {
    "worker_report_audits": 0,                 # V98（issue #4733）：本夹具未走过工人报工
    "production_instance_repricing_logs": 0,   # V94（issue #4709）：本夹具的订单未做过补价
    "ticket_timeline": 2,                      # #7633：售后工单时间线
    "ticket_notes": 1,                         # #7633：售后工单备注
    "rework_orders": 1,                        # #7633：返工单
    "production_work_logs": 1,
    "processing_position_operations": 11,
    "processing_orders": 1,
    "order_shipment_items": 3,                 # #7633：发货明细
    "order_shipments": 1,                      # #7633：发货单
    "order_items": 2,
    "order_logistics": 1,
    "after_sales_tickets": 1,                  # #7633：售后工单
    "receipt_allocations": 1,                  # #7633：收款核销明细（两侧合成一次 COUNT/DELETE）
    "finance_transactions": 1,                 # #7633：收款流水
    "orders": 1,
}


# ─────────────────────────── 依赖真值（现场抽取，不写死） ───────────────────────────

_CREATE_RE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.I)
_ALTER_RE = re.compile(r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I)
_REF_RE = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.I)
_COLUMN_RE = re.compile(r"^\s*(?:ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?)?(\w+)\s+", re.I)


def _scan_schema(path: Path) -> tuple:
    """一次扫出单文件里的 (外键边, 带 `order_id` 列的表)。

    同时支持 `CREATE TABLE` 块与 `ALTER TABLE ... ADD COLUMN / ADD CONSTRAINT`。
    """
    edges, order_id_tables = set(), set()
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
        column = _COLUMN_RE.match(line)
        if column and column.group(1).lower() == "order_id":
            order_id_tables.add(current)
        if in_create and line.strip().startswith(")"):
            current = None
        elif not in_create and ";" in line:
            current = None
    return edges, order_id_tables


def _scan_truth() -> tuple:
    """依赖真值 = `backend/admin-api/src/main/resources/db/init/schema.sql`（建库脚本）+ 迁移链。

    ⚠️ 不含 `docs/sql/archive/schema_full.sql` —— 该文件头部自述「已废弃（DEPRECATED）、两个方向都已失真」，
    是 2026-05-30 的快照（连 processing_orders 都没有）；拿它当真相 = 读落后副本。
    """
    edges, order_id_tables = set(), set()
    for f in [SCHEMA_SQL] + migration_files():   # 基线 + 归档 ∪ 活目录（issue #5243）
        e, o = _scan_schema(f)
        edges |= e
        order_id_tables |= o
    return edges, order_id_tables


def schema_fk_edges() -> set:
    """真外键边 (子表 → 父表)。"""
    return _scan_truth()[0]


def schema_order_id_tables() -> set:
    """schema 里带 `order_id` 列的表（指向订单的**语义**引用，外键未必存在 —— issue #7633）。

    这是一层**独立**的依赖真值：`after_sales_tickets` / `order_shipments` / `finance_transactions` 等的
    `order_id` 没有 `REFERENCES orders`，删 `orders` 时数据库**不会**报错 ⇒ 只靠外键闭包看不见它们，
    但它们的数据仍然属于这张订单（2026-10-24 实测：55 张单软删后这些行全部残留）。
    """
    return _scan_truth()[1]


def required_deletion_tables() -> set:
    """必须进删除计划的表闭包。

    根 = `orders` **∪ schema 里带 `order_id` 列的表**（issue #7633）；再沿外键**反向**取闭包 ——
    引用这些表的行（如 `ticket_timeline` / `rework_orders` / `order_shipment_items`）同样必须先删，
    否则删父表时会被外键拦下。
    """
    edges = schema_fk_edges()
    needed = {"orders"} | schema_order_id_tables()
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
    """记录脚本**按顺序**执行的 SQL；`fetchval` 按表名回预置行数。

    `orders` 那条查询**照真库语义**求值（`order_no = ANY($1) AND (deleted = 0 OR $2)`）——
    `$2` = `--include-soft-deleted` 开关。本文件只跑「未软删」夹具（墓碑单语义见
    `tests/unit_ci_workflows/test_delete_orders_soft_deleted.py`）。
    """

    def __init__(self, orders, processing_orders, counts, tickets=(), shipments=(), transactions=()):
        self._orders = orders
        self._po = processing_orders
        self._counts = counts
        self._children = {
            "after_sales_tickets": list(tickets),
            "order_shipments": list(shipments),
            "finance_transactions": list(transactions),
        }
        self.sql_log = []   # [(kind, table, sql, args)]

    async def fetch(self, sql, *args):
        table = _table_of(sql)
        self.sql_log.append(("fetch", table, sql, args))
        if table == "orders":
            # `$2` = 「是否包含墓碑单」（默认 False）；真的有没有把开关接进 SQL，由
            # test_delete_orders_soft_deleted.py 的 TombstoneConn 严格钉住。
            order_nos = args[0]
            include_soft_deleted = args[1] if len(args) > 1 else False
            return [r for r in self._orders
                    if r["order_no"] in order_nos and (r.get("deleted", 0) == 0 or include_soft_deleted)]
        if table == "processing_orders":
            return self._po
        if table in self._children:
            return self._children[table]
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
    return FakeConn(list(ORDER_ROWS), list(PO_ROWS), dict(COUNTS),
                    list(TICKET_ROWS), list(SHIPMENT_ROWS), list(TXN_ROWS))


# ─────────────────────────── 判据：删除计划 = 依赖真值的闭包 + 拓扑序 ───────────────────────────

def test_plan_covers_every_table_referencing_orders(full_conn, env_file):
    """凡引用 orders / processing_orders（外键）或带 `order_id` 列（语义引用）的表，都必须进计划。

    漏一层 ⇒ 要么删父表时 FK 报错，要么留下孤儿行（issue #7633 实测：残留
    `finance_transactions` 55 / `ticket_timeline` 23 / `after_sales_tickets` 10 …）。
    """
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    done = set(full_conn.deleted_tables)
    missing = required_deletion_tables() - done
    assert not missing, (
        f"删除计划漏掉了依赖真值里引用该订单的表：{sorted(missing)}；"
        f"实际只删了 {full_conn.deleted_tables}。"
        f"补法 = 在 scripts/delete_orders.py 的 DELETE_PLAN 里按依赖顺序加一级（中文名补进 TABLE_LABELS）；"
        f"带 order_id 语义引用的表还要补进 locators() 的键空间。"
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


def test_order_id_tables_deleted_before_orders(full_conn, env_file):
    """带 `order_id` 列的表（语义引用，外键未必存在）必须先于 `orders` 删。

    与 `test_delete_order_is_topological` 互补：那条只看**真外键**，这条管 `order_id` 这类没建外键的
    语义引用 —— 2026-10-24 的残留（`after_sales_tickets` / `order_shipments` / `finance_transactions`）
    正好落在后者上：删完订单，它们就成了永远指不到父行的孤儿。
    """
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    order = full_conn.deleted_tables
    pos = {t: i for i, t in enumerate(order)}
    roots = sorted(schema_order_id_tables())
    checked = [t for t in roots if t in pos]
    late = [(t, pos[t], pos["orders"]) for t in checked if pos[t] > pos["orders"]]
    assert not late, (
        f"这些带 order_id 的表排在 orders 之后（删完订单它们就成了孤儿）：{late}；实际顺序 = {order}。"
        f"补法 = 在 DELETE_PLAN 里把它们移到 orders 之前。"
    )
    # 禁空跑：至少要有三层语义引用真的被检查到
    must = {"after_sales_tickets", "order_shipments", "finance_transactions"}
    assert must <= set(checked), (
        f"语义引用面没被检查到：{sorted(must - set(checked))}（schema 侧 order_id 表 = {roots}；"
        f"删除顺序 = {order}）"
    )


def test_delete_order_matches_issue_4242_spec(full_conn, env_file):
    """issue #4242 判据 1 的显式序列（含 schema 真值补出的 order_logistics 与 #7633 的三族）。"""
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


def test_new_levels_located_through_prefetched_parent_ids(full_conn, env_file):
    """#7633 的三族必须经**预取的父 id** 定位（先查父 id、再定位子行），不得靠 order_id 猜。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    by_table = {t: (sql, args) for t, sql, args in full_conn.deletes()}
    for table, arg in (("ticket_timeline", TICKET_ID), ("ticket_notes", TICKET_ID),
                       ("order_shipment_items", SHIPMENT_ID), ("finance_transactions", ORDER_ID)):
        sql, args = by_table[table]
        assert list(args[0]) == [arg], f"{table} 的定位参数取错了键空间：{sql} / {args}"
    # 交易侧必须早于 finance_transactions 删（那是删流水的 FK 前置）
    pos = {t: i for i, t in enumerate(full_conn.deleted_tables)}
    assert pos["receipt_allocations"] < pos["finance_transactions"], (
        f"收款核销明细（交易侧）必须早于收款流水：{full_conn.deleted_tables}")
    tx_sql, tx_args = by_table["receipt_allocations"]
    assert "transaction_id = ANY($1::text[])" in tx_sql, tx_sql
    assert list(tx_args[0]) == [TXN_ID], f"交易侧参数必须是交易 id：{tx_args}"


def test_dry_run_reports_every_level(full_conn, env_file, capsys):
    """判据 3：dry-run 汇总必须报出每一级的行数（否则低报删除量）+ 不执行任何 DELETE。"""
    rc = run_script(full_conn, [ORDER_NO], env_file)
    out = capsys.readouterr().out
    assert rc == 0
    assert full_conn.deletes() == [], f"dry-run 不应执行删除，实际执行了 {full_conn.deletes()}"
    for label, n in (("报工", "1"), ("工序实例", "11"), ("加工单", "1"),
                     ("订单明细", "2"), ("物流", "1"), ("订单", "1"),
                     # #7633 三族：汇总必须报出来，否则用户看不到将删多少行
                     ("工单时间线", "2"), ("工单备注", "1"), ("返工单", "1"), ("售后工单", "1"),
                     ("发货明细", "3"), ("发货单", "1"), ("收款核销明细", "1"), ("收款流水", "1")):
        assert f"{label} {n} 行" in out, f"dry-run 汇总缺「{label} {n} 行」：\n{out}"
    # 多侧定位的表只应汇总**一次**（两侧合成同一条 DELETE，否则行数会被重复报）
    assert out.count("收款核销明细") == 1, f"多侧定位的表被重复汇总：\n{out}"


def test_apply_prints_every_level(full_conn, env_file, capsys):
    """--apply 的结果行同样逐级报数（与删除计划同源）。"""
    run_script(full_conn, [ORDER_NO], env_file, apply=True)
    out = capsys.readouterr().out
    assert "✅ 已删除" in out
    for label in ("报工", "工序实例", "加工单", "订单明细", "物流", "订单",
                  "工单时间线", "工单备注", "返工单", "售后工单",
                  "发货明细", "发货单", "收款核销明细", "收款流水"):
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
    # 多侧定位（`rework_orders` 工单侧+订单侧 / `order_shipment_items` 发货单侧+订单侧 /
    # `receipt_allocations` 交易侧+订单侧）会用 `OR` 连接 —— 语义仍是「只按主键等值命中」，
    # 故这里钉**条件形态**（每一侧都必须是 `<列> = ANY($n::text[])`），而不是「不许出现 OR」。
    conjunct = re.compile(r"^\w+ = ANY\(\$\d+::text\[\]\)$")
    for _, del_sql, _ in full_conn.deletes():
        upper = del_sql.upper()
        assert "LIKE" not in upper and "%" not in del_sql and "NOT IN" not in upper, del_sql
        for part in del_sql.split(" WHERE ", 1)[1].split(" OR "):
            assert conjunct.match(part), f"删除条件退化成非主键等值形态：{del_sql}"


def test_v43_only_order_still_deletes(env_file):
    """判据 4 不回归：无生产数据（V43 形态）的订单仍能正常删除。"""
    conn = FakeConn(list(ORDER_ROWS), [], {"orders": 1, "order_items": 2})
    rc = run_script(conn, [ORDER_NO], env_file, apply=True)
    assert rc == 0
    assert tuple(conn.deleted_tables) == EXPECTED_DELETE_ORDER


def test_soft_deleted_children_are_still_located(env_file, capsys):
    """软删的**子行**同属被删对象 ⇒ 定位它们时不得带 `deleted = 0`（否则漏掉子行、删父表时 FK 报错）。

    覆盖加工单（#4242 起）与 #7633 新增的三族（售后工单 / 发货单 / 收款流水）。
    """
    conn = FakeConn(list(ORDER_ROWS), list(PO_ROWS), dict(COUNTS),
                    list(TICKET_ROWS), list(SHIPMENT_ROWS), list(TXN_ROWS))
    run_script(conn, [ORDER_NO], env_file)
    for table in ("processing_orders", "after_sales_tickets", "order_shipments", "finance_transactions"):
        sql_list = [sql for t, sql, _ in conn.selects() if t == table]
        assert sql_list, f"必须先查 {table} 的 id（它是子表外键的父行）"
        assert "deleted = 0" not in sql_list[0], (
            f"{table} 查询带 deleted=0，会漏掉已软删行的子行 ⇒ 删父表时 FK 报错：{sql_list[0]}")


def test_empty_order_nos_is_rejected(monkeypatch, capsys):
    """`--order-nos` 为空必须拒绝（退出码 2），绝不退化成"删空条件"式批量删除。"""
    mod = load_script()
    monkeypatch.setattr(sys, "argv", ["delete_orders.py", "--order-nos", " , "])
    assert mod.main() == 2
    assert "为空" in capsys.readouterr().err
