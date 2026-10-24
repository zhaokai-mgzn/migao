# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：脚本 / CI / 工具链结构类 L0 不变式统一挂 MC-012 ——
#   `.github/cases/misc.yml` 的 MC-012 已登记「CI/工具链结构由 tests/unit_ci_workflows/ 单测验证，
#   skip_reason = [backend-contract]，不进 agent-eval 冒烟」。本文件同属该形态：零真实 DB。）
"""L0 判据：`scripts/delete_orders.py` 的两种「匹配语义」+ 删除拓扑的键空间。

## 病灶（issue #7633，2026-10-24 云 dev 库实测）

一张裸 SQL 把 55 张冒烟订单批量**软删**（`orders.deleted = 1`），子行没级联；事后想用本脚本收尾，
发现两个洞：

1. **清不了墓碑单**：订单查询只匹配 `deleted = 0` ⇒ 已被软删的订单**匹配 0 行**，
   工具对「最该清理的那批数据」恰好一条也清不掉；
2. **删不动带收款 / 售后 / 发货的单**：`DELETE_PLAN` 缺 `after_sales_tickets` / `ticket_timeline` /
   `ticket_notes` / `rework_orders` / `order_shipments` / `order_shipment_items` /
   `finance_transactions`，以及 `receipt_allocations` 的 `transaction_id` 一侧（删
   `finance_transactions` 的前置）⇒ 删父表时被外键拦下。最后只能**手写 SQL** 清干净。

⇒ 本文件钉两件事（**零数据库**：不连库，只注入假连接驱动脚本真身）：

| 判据 | 会红的形态 |
|---|---|
| `--include-soft-deleted` 的语义 | 默认也匹配墓碑单（安全默认被悄悄放宽）；或开关不生效（墓碑单永远清不掉） |
| `locators()` 的拓扑与键空间 | 子表排在父表之后（删父表被 FK 拦下）；`receipt_allocations` 的交易侧晚于 `finance_transactions`；同一张表被删两次（汇总重复报数） |

RED 钩子（与 `tests/unit_ci_workflows/test_delete_orders_fk_order.py` 同口径）：
`DELETE_ORDERS_SCRIPT=/tmp/orig/delete_orders.py` 可把被测脚本换成改动前版本，复现「改前红 / 改后绿」。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORDER_NO = "20261024392560001"
ORDER_ID = "a1b2c3d4-e5f6-4a7b-8c9d-000000007633"
# 同一 order_no、但已被**软删**的墓碑单 —— 就是 2026-10-24 云 dev 库里那 55 张单的形态
TOMBSTONE_ROW = {
    "id": ORDER_ID, "order_no": ORDER_NO, "status": "cancelled",
    "customer_name": "墓碑单客户", "remark": "冒烟残留", "deleted": 1,
}

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


class TombstoneConn:
    """最小假连接：**只对 `orders` 那条查询照真库语义求值**，其余表回空集。

    真库语义 = `WHERE order_no = ANY($1) AND (deleted = 0 OR $2)` —— `$2` 就是
    `--include-soft-deleted` 开关（默认 False）。本文件只钉「同一 order_no 的墓碑单是否被匹配」；
    子表拓扑 / 计数由 `test_delete_orders_fk_order.py` 覆盖。
    """

    def __init__(self, order_rows):
        self._orders = list(order_rows)
        self.order_queries = []   # [(sql, order_nos, include_soft_deleted)]
        self.deleted_tables = []
        self.selects = []         # [(table, sql, args)]

    async def fetch(self, sql, *args):
        table = _table_of(sql)
        self.selects.append((table, sql, args))
        if table != "orders":
            return []             # 本连接不模拟子表内容（拓扑另有判据）
        assert len(args) == 2, (
            "订单查询必须把「是否包含墓碑单」当作**参数**传入（默认 False）；"
            f"实测只收到 {len(args)} 个参数 ⇒ 默认与开关无差别：{sql}")
        order_nos, include_soft_deleted = args[0], args[1]
        self.order_queries.append((sql, order_nos, include_soft_deleted))
        return [r for r in self._orders
                if r["order_no"] in order_nos and (r["deleted"] == 0 or include_soft_deleted)]

    async def fetchval(self, sql, *args):
        return 0

    async def execute(self, sql, *args):
        self.deleted_tables.append(_table_of(sql))
        return "DELETE 0"

    def transaction(self):
        return _FakeTx()

    async def close(self):
        return None


def load_script():
    """被测脚本真身（`DELETE_ORDERS_SCRIPT` 仅红证时指向改动前版本；CI 不设）。"""
    path = Path(os.environ.get("DELETE_ORDERS_SCRIPT", REPO_ROOT / "scripts" / "delete_orders.py"))
    assert path.is_file(), f"被测脚本不存在: {path}"
    spec = importlib.util.spec_from_file_location("_delete_orders_soft_deleted_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """按 **CLI 形态**跑脚本真身（`--include-soft-deleted` 必须真的能被 argparse 接受）。"""
    env_file = tmp_path / "rds.env"
    env_file.write_text("RDS_HOST=127.0.0.1\nRDS_PORT=55432\nRDS_USER=t\nRDS_PASSWORD=p\n"
                        "RDS_DB=ai_customer_service\n", encoding="utf-8")

    def _run(conn, *extra, apply: bool = False):
        mod = load_script()
        fake = types.ModuleType("asyncpg")

        async def _connect(**kwargs):
            return conn

        fake.connect = _connect
        monkeypatch.setitem(sys.modules, "asyncpg", fake)
        argv = ["delete_orders.py", "--order-nos", ORDER_NO, "--env-file", str(env_file), *extra]
        if apply:
            argv.append("--apply")
        monkeypatch.setattr(sys, "argv", argv)
        return mod.main()

    return _run


# ─────────────────────── 判据 1：--include-soft-deleted 的语义（默认关） ───────────────────────

def test_default_does_not_match_tombstone(cli, capsys):
    """默认：**同一 order_no** 的墓碑单不匹配 ⇒ 0 行被删（安全默认绝不悄悄放宽）。"""
    conn = TombstoneConn([dict(TOMBSTONE_ROW)])
    assert cli(conn, apply=True) == 0
    out = capsys.readouterr().out
    assert "匹配订单 0/1 个" in out, f"默认不应匹配已软删的订单：\n{out}"
    assert conn.order_queries[0][2] is False, "默认的「包含墓碑单」参数必须是 False"
    assert conn.deleted_tables == [], f"默认路径不应删除任何行，实际删了 {conn.deleted_tables}"


def test_include_soft_deleted_matches_tombstone(cli, capsys):
    """开关打开：**同一 order_no** 的墓碑单被匹配 ⇒ 按拓扑执行删除（末级 = orders 自身）。"""
    conn = TombstoneConn([dict(TOMBSTONE_ROW)])
    assert cli(conn, "--include-soft-deleted", apply=True) == 0
    out = capsys.readouterr().out
    assert "匹配订单 1/1 个" in out, f"开关打开时必须匹配到墓碑单：\n{out}"
    assert conn.order_queries[0][2] is True, "开关打开时「包含墓碑单」参数必须是 True"
    assert conn.deleted_tables, "开关打开后必须真的执行删除"
    assert conn.deleted_tables[-1] == "orders", (
        f"末级必须是 orders 自身（父表最后删）：{conn.deleted_tables}")
    assert str(ORDER_ID) in str(conn.selects), "子表父 id 必须来自订单查询结果"


# ─────────────────────── 判据 2：locators() 的拓扑与键空间（纯函数） ───────────────────────

def test_locators_order_is_topological_and_has_no_duplicate_tables():
    """子表先于父表；一张表只删一次（多侧定位合成同一条 DELETE，汇总才不会重复报数）。"""
    steps = load_script().locators(["o1"], ["po1"], ["t1"], ["s1"], ["x1"])
    tables = [t for t, _, _ in steps]
    assert len(tables) == len(set(tables)), f"同一张表被删两次（汇总会重复报数）：{tables}"
    pos = {t: i for i, t in enumerate(tables)}
    for child, parent in (
        ("ticket_timeline", "after_sales_tickets"),
        ("ticket_notes", "after_sales_tickets"),
        ("rework_orders", "after_sales_tickets"),
        ("order_shipment_items", "order_shipments"),
        ("receipt_allocations", "finance_transactions"),
        ("after_sales_tickets", "orders"),
        ("order_shipments", "orders"),
        ("finance_transactions", "orders"),
        ("rework_orders", "processing_orders"),
        ("order_shipment_items", "order_items"),
    ):
        assert child in pos, f"删除计划漏了 {child}（它的父行会先被删 ⇒ 被外键拦下）"
        assert parent in pos, f"删除计划漏了 {parent}"
        assert pos[child] < pos[parent], f"{child} 必须先于 {parent} 删：{tables}"
    assert tables[-1] == "orders", f"orders 必须是最后一级：{tables}"


def test_locators_maps_each_side_to_its_own_keyspace():
    """每一侧的定位参数必须来自**自己的键空间**（取错父 id ⇒ 删错行或删不掉）。"""
    steps = {t: (where, args) for t, where, args in
             load_script().locators(["o1"], ["po1"], ["t1"], ["s1"], ["x1"])}
    where, args = steps["receipt_allocations"]
    assert "transaction_id = ANY($1::text[])" in where, f"交易侧必须是第一侧：{where}"
    assert "order_id = ANY($2::text[])" in where, where
    assert args == [["x1"], ["o1"]], f"交易侧参数必须来自 transaction 键空间：{args}"
    where, args = steps["rework_orders"]
    assert "after_sales_ticket_id = ANY($1::text[])" in where, where
    assert "order_id = ANY($2::text[])" in where, where
    assert args == [["t1"], ["o1"]], f"返工单两侧参数必须是 ticket / order：{args}"
    where, args = steps["order_shipment_items"]
    assert "shipment_id = ANY($1::text[])" in where and "order_id = ANY($2::text[])" in where, where
    assert args == [["s1"], ["o1"]], f"发货明细两侧参数必须是 shipment / order：{args}"
    assert steps["ticket_timeline"][1] == [["t1"]]
    assert steps["finance_transactions"][1] == [["o1"]]
    assert steps["orders"][0] == "id = ANY($1::text[])"


def test_every_locator_condition_is_exact_primary_key_equality():
    """所有定位条件只能是 `<列> = ANY($n::text[])`：不许通配 / 范围 / NOT IN / 子查询。

    （安全设计「仅按显式主键精确匹配」的机械面；多侧定位用 `OR` 连接，但**每一侧**都必须是等值。）
    """
    step_re = re.compile(r"^\w+ = ANY\(\$\d+::text\[\]\)(?: OR \w+ = ANY\(\$\d+::text\[\]\))*$")
    steps = load_script().locators(["o1"], ["po1"], ["t1"], ["s1"], ["x1"])
    assert steps, "删除计划为空 —— 本判据会空跑"
    for table, where, args in steps:
        assert step_re.match(where), f"{table} 的定位条件退化成非等值形态：{where}"
        assert len(args) == where.count("ANY("), f"{table} 的定位条件与参数个数不匹配：{where} / {args}"
