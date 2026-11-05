# case_ids: MC-012
"""活 seed 的**数据面**判据（SDQS D1/D2/D3；issue #7583 缺陷 1 / 2 / 3 / 7）。

> **case 声明口径**：与 `tests/unit_ci_workflows/test_smoke_data_quality.py` 同族 ——
> `.github/cases/` 没有「冒烟/种子数据质量」域的真实用例，本文件沿用 **MC-012**
> （研发工具/基建判据的登记号）；将来该域立真实用例时由用例库所有权包改写本行。

## 病灶（issue #7583 的 durable 证据）

| # | 缺口 | 现取证据 |
|---|---|---|
| 1 | `demo-seed.sql` 的商品状态落在应用枚举外（`active`） | 规范 §4 审计表的「demo-seed 商品状态」条；枚举真值源 = `ProductService.STATUS_TRANSITIONS` |
| 2 | SKU 矩阵残缺（`p-zg-002` 三颜色 0 SKU；`p-zg-001` / `p-sl-001` 各仅 1 行） | `docs/deployment/demo-seed.sql` 的 `product_skus` 段 |
| 3 | 金额链不闭合（订单总额 ≠ Σ 明细；有单无明细；明细单价 ≠ SKU 价） | 同文件的 `orders` / `order_items` 段 |
| 7 | 评测栈种子只数 `products`；SKU / 用户 / 金额段静默 0 行也绿 | `scripts/eval_stack_seed.sh` 的「数据核对」段 |

## 判据（每条都单独变红；`3` 类「判不了」一律 fail-closed，不得当通过）

| 判据 | 回归时会怎么红 |
|---|---|
| ① 商品状态 ∈ 应用枚举 | seed 写回 `active` ⇒ 红（枚举从 `ProductService` **现取**，不抄第二份） |
| ② 每个颜色都有 SKU | 删掉某商品某色的 SKU 行 / 新增颜色不补矩阵 ⇒ 红（具名「商品 × 颜色」） |
| ③ SKU 矩阵字段有效 | 色名空 / 门幅非 canonical / `price <= 0` / `stock < 0` ⇒ 红 |
| ④ SKU 插入语句的关联条件与行值一致 | `WHERE c.color_name = …` 打错一字 ⇒ 真库插 0 行而 ② 仍绿（缺陷 2 的复发通道）⇒ 红并具名「商品 × 颜色」 |
| ⑤ 金额链闭合 | 总额 ≠ Σ 明细小计 / 明细单价不在该商品 SKU 价集 / 有单无明细 / 已收 > 总额 ⇒ 各自具名红 |
| ⑥ 评测栈五类计数 | `eval_stack_seed.sh` 少断言一类，或任一类 0 行仍绿 ⇒ 红（**stub `docker` 跑真脚本**，不是读源码猜） |

**红证怎么取**（回退实现 ⇒ 本文件必红；恢复 ⇒ 绿）：见 PR body 的读数表；
`_seed_sql.py` 的解析是纯函数，判据吃的是**磁盘上的真 seed**，注入即红。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unit_ci_workflows._seed_sql import (  # noqa: E402
    literal,
    parse_seed,
    read as read_seed,
    rows as seed_rows,
)

DEMO_SEED = REPO / "docs" / "deployment" / "demo-seed.sql"
EVAL_SEED_SH = REPO / "scripts" / "eval_stack_seed.sh"
PRODUCT_SERVICE = (
    REPO / "backend" / "admin-api" / "src" / "main" / "java"
    / "com" / "migao" / "admin" / "service" / "ProductService.java"
)

#: 计数桩：`eval_stack_seed.sh` 与 DB 的唯一交互是 `docker compose … psql` ⇒ 换掉 `docker`
#: 就能在**零网络零 DB** 下行使真脚本（判据不是「读源码猜它会不会判」，而是「真跑一遍」）。
DOCKER_STUB = """#!/usr/bin/env bash
# 判据桩（tests/unit_ci_workflows/test_seed_data_quality.py）：原样吐出 STUB_COUNTS。
# 用 `-`（不是 `:-`）：空串必须保持空 —— 那一条判据要的正是「读不到」。
printf '%s\\n' "${STUB_COUNTS-1|1|1|1|1|1}"
"""


def _demo() -> str:
    return read_seed(DEMO_SEED)


def _app_product_statuses() -> set[str]:
    """商品状态合法集合 —— **现取** `ProductService.STATUS_TRANSITIONS` 的键集（不抄第二份）。"""
    source = PRODUCT_SERVICE.read_text(encoding="utf-8")
    keys = set(re.findall(r'STATUS_TRANSITIONS\.put\(\s*"([a-z_]+)"', source))
    assert keys, "fail-closed：读不到 ProductService.STATUS_TRANSITIONS 的键集 —— 枚举真值源解析失败"
    return keys


def _sku_prices_by_product(sql: str) -> dict[str, set[Decimal]]:
    prices: dict[str, set[Decimal]] = defaultdict(set)
    for row in seed_rows(sql, "product_skus"):
        prices[str(literal(row["product_id"]))].add(literal(row["price"]))
    return prices


# ── ① 商品状态 ∈ 应用枚举（issue #7583 缺陷 1）─────────────────────────────
def test_demo_seed_product_status_is_within_app_enum():
    products = seed_rows(_demo(), "products")
    assert len(products) == 3, f"demo-seed 商品行数应为 3，实得 {len(products)} —— 判据覆盖面变了"
    allowed = _app_product_statuses()
    bad = {str(literal(r["id"])): str(literal(r["status"]))
           for r in products if literal(r["status"]) not in allowed}
    assert not bad, (
        f"demo-seed 的商品状态落在应用枚举外（合法 = {sorted(allowed)}）：{bad} —— "
        "演示租户的商品在按状态过滤的列表 / 库存预警里查不到，状态变更只能走 recovery 分支"
        "（issue #7583 缺陷 1；枚举真值源 = ProductService.STATUS_TRANSITIONS）")


# ── ② 每个颜色都有 SKU（缺陷 2）─────────────────────────────────────────
def test_demo_seed_every_color_has_sku():
    sql = _demo()
    colors = {(str(literal(c["product_id"])), str(literal(c["color_name"])))
              for c in seed_rows(sql, "product_colors")}
    skus = {(str(literal(s["product_id"])), str(literal(s["color_name"])))
            for s in seed_rows(sql, "product_skus")}
    assert colors, "fail-closed：demo-seed 解析不到 product_colors 行 —— 判不了，不得当通过"
    missing = sorted(colors - skus)
    assert not missing, (
        f"以下「商品 × 颜色」没有任何 SKU 行：{missing} —— 演示环境「颜色 × 门幅」选不全"
        "（issue #7583 缺陷 2）")


# ── ③ SKU 矩阵字段有效（同缺陷 2 的「不是空壳」一半）──────────────────────
def test_demo_seed_sku_matrix_fields_are_valid():
    skus = seed_rows(_demo(), "product_skus")
    assert skus, "fail-closed：demo-seed 解析不到 product_skus 行 —— 判不了，不得当通过"
    bad = []
    for row in skus:
        color = str(literal(row["color_name"])).strip()
        width = str(literal(row["door_width"])).strip()
        price, stock = literal(row["price"]), literal(row["stock"])
        if (not color or not re.fullmatch(r"\d+(?:\.\d+)?", width)
                or not isinstance(price, Decimal) or price <= 0
                or not isinstance(stock, Decimal) or stock < 0):
            bad.append({k: literal(v) for k, v in row.items() if k in
                        ("product_id", "color_name", "door_width", "price", "stock")})
    assert not bad, (
        "SKU 矩阵字段不合格（色名 / 门幅 canonical / price>0 / stock>=0；SDQS Q2）："
        f"{bad[:3]}")


# ── ④ SKU 插入语句的关联条件与行值一致（缺陷 2 的假绿出口）──────────────────
def _relation_literal(statement: str, column: str) -> str | None:
    """从 `… WHERE … AND c.<column> = '<值>' …` 取那个字面量（**纯字符串操作**）。

    刻意不写正则：`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 把
    「带引号的捕获组」判成高危口径（注释 / docstring 里的假字面量会被当成真站点）。
    取不到 ⇒ `None`，调用方 **fail-closed**（判不了 ≠ 通过）。
    """
    if "WHERE" not in statement:
        return None
    for segment in statement.split("WHERE", 1)[1].split(" AND "):
        text = segment.strip()
        prefix = f"c.{column}"
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix):].lstrip()
        if not rest.startswith("="):
            continue
        value = rest[1:].strip()
        if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
        return None
    return None


def test_demo_seed_sku_insert_relations_match_row_values():
    """SKU 行走 `FROM product_colors c` 的相关子查询 ⇒ **插 0 行也是静默的**。

    缺陷 2 的复发通道：只把 `WHERE c.color_name = '<色名>'`（或 `c.product_id`）打错一个字，
    真库里这一行**根本插不进去**（子查询无行，INSERT … SELECT 静默插 0 行），而 ② 仍从
    SELECT 列表读到「该颜色有 SKU」⇒ 判据绿、演示库空。本判据把**三处**对齐：
    SELECT 列表的行值 ⇄ WHERE 的关联条件 ⇄ `product_colors` 里真实声明的颜色。
    """
    sql = _demo()
    declared = {(str(literal(c["product_id"])), str(literal(c["color_name"])))
                for c in seed_rows(sql, "product_colors")}
    assert declared, "fail-closed：demo-seed 解析不到 product_colors 行 —— 判不了，不得当通过"
    blocks = [b for b in parse_seed(sql) if b["table"] == "product_skus"]
    assert blocks, "fail-closed：demo-seed 解析不到 product_skus 语句 —— 判不了，不得当通过"
    bad: list[str] = []
    for block in blocks:
        if block["literals"] is None:
            bad.append("product_skus 出现未经本判据核对的写入形态（元组 VALUES）："
                       f"{block['sql'][:90]}…")
            continue
        row = dict(zip(block["columns"], block["literals"]))
        selected = (str(literal(row["product_id"])), str(literal(row["color_name"])))
        who = f"商品 {selected[0]} / 颜色 {selected[1]}"
        related = tuple(_relation_literal(block["sql"], column)
                        for column in ("product_id", "color_name"))
        if None in related:
            bad.append(f"{who}：语句里没有 `c.product_id` / `c.color_name = '<字面量>'` "
                       "关联条件 —— 判不了（fail-closed）")
        elif related not in declared:
            bad.append(f"{who}：WHERE 按「商品 {related[0]} × 颜色 {related[1]}」关联，"
                       "但 product_colors 里没有这个颜色 ⇒ 真库插 0 行")
        elif related != selected:
            bad.append(f"{who}：SELECT 写「商品 {selected[0]} × 颜色 {selected[1]}」，"
                       f"WHERE 却按「商品 {related[0]} × 颜色 {related[1]}」关联 ⇒ 真库插 0 行")
    assert not bad, (
        "SKU 插入语句的关联条件与行值不一致：静态判据仍读到「该颜色有 SKU」，真库里却是空的"
        "（缺陷 2 的复发通道；issue #7583）：\n" + "\n".join(bad))


# ── ⑤ 金额链闭合（缺陷 3）─────────────────────────────────────────────
def test_demo_seed_every_order_has_items():
    sql = _demo()
    orders = {str(literal(o["id"])) for o in seed_rows(sql, "orders")}
    with_items = {str(literal(i["order_id"])) for i in seed_rows(sql, "order_items")}
    assert orders, "fail-closed：demo-seed 解析不到 orders 行 —— 判不了，不得当通过"
    assert not (orders - with_items), (
        f"以下订单**一条明细都没有**（有单无明细 ⇒ 对账/报表读数是错的）：{sorted(orders - with_items)}"
        "（issue #7583 缺陷 3）")


def test_demo_seed_order_total_equals_sum_of_items():
    sql = _demo()
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for item in seed_rows(sql, "order_items"):
        sums[str(literal(item["order_id"]))] += literal(item["subtotal"])
    bad = []
    for order in seed_rows(sql, "orders"):
        oid = str(literal(order["id"]))
        total = literal(order["total_amount"])
        if total != sums[oid]:
            bad.append(f"{oid}: total_amount={total} ≠ Σ subtotal={sums[oid]}")
    assert not bad, (
        "订单总额与明细合计不闭合（issue #7583 缺陷 3）：" + "；".join(bad))


def test_demo_seed_order_item_price_is_a_sku_price():
    sql = _demo()
    prices = _sku_prices_by_product(sql)
    bad = []
    for item in seed_rows(sql, "order_items"):
        pid = str(literal(item["product_id"]))
        unit = literal(item["unit_price"])
        if unit not in prices.get(pid, set()):
            bad.append(f"{literal(item['id'])}: product={pid} unit_price={unit} "
                       f"∉ SKU 价集 {sorted(prices.get(pid, set()))}")
    assert not bad, (
        "明细单价不是该商品任何 SKU 的价格（issue #7583 缺陷 3）：" + "；".join(bad))


def test_demo_seed_order_row_is_arithmetically_closed():
    """明细自身也要闭合（数量 × 单价 = 小计），且已收金额不得超过总额。"""
    sql = _demo()
    bad = []
    for item in seed_rows(sql, "order_items"):
        qty, unit, subtotal = (literal(item["quantity"]), literal(item["unit_price"]),
                              literal(item["subtotal"]))
        if qty * unit != subtotal:
            bad.append(f"{literal(item['id'])}: {qty} × {unit} ≠ {subtotal}")
    for order in seed_rows(sql, "orders"):
        total, actual = literal(order["total_amount"]), literal(order["actual_amount"])
        if actual > total:
            bad.append(f"{literal(order['id'])}: actual_amount={actual} > total_amount={total}")
    assert not bad, "明细 / 订单金额算术不闭合：" + "；".join(bad)


# ── ⑥ 评测栈种子的五类计数（缺陷 7）:真脚本 + 桩 docker ─────────────────
def _run_eval_seed(tmp_path: Path, counts: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB, encoding="utf-8")
    stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "STUB_COUNTS": counts,
    }
    return subprocess.run(
        ["bash", str(EVAL_SEED_SH), "--persona", "xiaobu"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
    )


GOOD_COUNTS = "5|8|14|4|6|1234.80"


def test_eval_seed_reports_five_entity_counts(tmp_path):
    done = _run_eval_seed(tmp_path, GOOD_COUNTS)
    assert done.returncode == 0, f"计数合格仍非零退出（{done.returncode}）：{done.stderr[-500:]}"
    for token in ("products=5", "colors=8", "skus=14", "users=4",
                  "order_items=6", "order_amount=1234.80"):
        assert token in done.stdout, (
            f"数据核对没有打印 `{token}` —— 五类计数（商品/颜色/SKU/用户/金额）缺一类，"
            f"缺数据的种子就会静默通过（issue #7583 缺陷 7）。stdout 尾部：{done.stdout[-400:]}")


@pytest.mark.parametrize("index, token", [
    (0, "products"),
    (1, "colors"),
    (2, "skus"),
    (3, "users"),
    (4, "order_items"),
])
def test_eval_seed_turns_red_when_any_face_is_empty(tmp_path, index, token):
    parts = GOOD_COUNTS.split("|")
    parts[index] = "0"
    done = _run_eval_seed(tmp_path, "|".join(parts))
    assert done.returncode != 0, (
        f"`{token}` 计数为 0 仍绿（exit={done.returncode}）—— 夹具缺数据会被读成「种子注入成功」"
        "（issue #7583 缺陷 7）")
    assert token in done.stderr, (
        f"判红没有点名 `{token}`（stderr={done.stderr[-400:]}）—— 归因不可读")


def test_eval_seed_turns_red_when_money_is_empty(tmp_path):
    done = _run_eval_seed(tmp_path, "5|8|14|4|6|0.00")
    assert done.returncode != 0, "订单金额合计为 0 仍绿 —— 金额链没有数据却读成「种子完成」"
    assert "order_amount" in done.stderr, f"判红没有点名 order_amount（stderr={done.stderr[-400:]})"


def test_eval_seed_fails_closed_when_counts_unreadable(tmp_path):
    """读不到 ≠ 通过：DB 不通 / 查询被改坏 ⇒ 非零退出，不许静默跳过核对。"""
    done = _run_eval_seed(tmp_path, "")
    assert done.returncode != 0, "计数查询没有输出仍绿（读不到 ≠ 通过）"
