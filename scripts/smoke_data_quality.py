#!/usr/bin/env python3
# case_ids: MC-012
"""冒烟**数据质量**体检（SDQS：`docs/testing/smoke-data-quality.md`）。

## 为什么要有它（2026-10-23 现取读数）

`./scripts/ui_smoke_merchant.sh` 报 **33/33 全绿**，而人工一看数据不合格：
冒烟自造的「冒烟SKU商品…」**一条 `product_skus` 都没有**，`08-products-list` 的截图里
列表还在「加载中…」——"绿"证明的是「页面渲染出来了」，**不是**「数据能用」。
这类假绿不看源码看不出来：旅程判据是 `rows > 0` / `bodyLen > 50`，空态与渲染态都能过。

## 判据（每条都会红，红得具名）

本文件只做一件事：把**冒烟跑完后的一份数据快照**（`smoke-data.json`，由
`scripts/ui-smoke-merchant/spec.mjs` 的 `collectDataSnapshot()` 用**管理端 API 现读**产出）
按下面五组规则判红。**数据面独立于 UI 面**：UI 33/33 绿也不能把这个判据染色。

| 代号 | 判什么 | 怎么算红 |
|---|---|---|
| `DQ-1` | 被测商品面**真的有 SKU** | 跑过商品旅程，而 `products.with_skus == 0` |
| `DQ-2` | 冒烟**自造**的商品**都有 SKU** | `fixtures.products_with_skus != fixtures.products_created` |
| `DQ-3` | SKU 口径 **canonical** | `skus.door_width_noncanonical > 0`（如落库 `2.8米`） |
| `DQ-4` | 订单/客户/售后面**非空** | 对应旅程跑过，而 `total == 0`（空态冒充绿） |
| `DQ-5` | 冒烟自造商品**清理干净** | `fixtures.products_residue > 0`（残留可删对象） |
| `DQ-U` | 读不到就**不许当通过** | 任何被判定面 `collected == false` ⇒ 退出码 3（不可判定） |

## 怎么跑

```bash
# 冒烟壳脚本在 spec 之后自动调用（见 scripts/ui_smoke_merchant.sh 的「数据质量体检」段）
python3 scripts/smoke_data_quality.py --snapshot acceptance/.../out/smoke-data.json

# 自检 / 红证（离线，零网络零 DB）：
python3 -m pytest tests/unit_ci_workflows/test_smoke_data_quality.py -q
```

退出码（三态，`3` **不得**当 `0` 读）：

| 码 | 含义 |
|---|---|
| `0` | 全部规则通过（或该面本轮未跑 ⇒ 规则不适用） |
| `1` | 有具名违规（**这是数据不合格**，不是产品缺陷） |
| `3` | 读不到快照 / 快照缺面 ⇒ **不可判定**（fail-closed，不许当通过） |

## 边界（照实登记，`migao-dev-flow` §19.1）

- 它判**数据形态**，不判业务正确性：SKU 存在且价格/库存非空 ≠ 价格算对。
- 规则按 `ran_journeys` 收窄：`--group 09-` 这类局部跑只判相关面，不因「没跑订单」误红。
- `fixtures.products_residue` 只收**可删对象**（商品/草稿）；订单/发货单是业务事实，
  不要求删除，改为「冒烟标记 + 台账」（见规范 §D4），本判据**不判**它们。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1

#: 门幅 canonical 形态：裸数值（与 `frontend/admin-web/src/components/products/SkuMatrix.tsx`
#: 的写入侧 `normalizeDoorWidth` 同口径）。带单位（`2.8米`）或 `门幅2.8米` 都算**非 canonical**
#: ——服务端虽然兼容，但落库口径不一致会让「按门幅检索 / 去重」在不同数据源上结论相反。
CANONICAL_DOOR_WIDTH = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

#: 每类实体由哪些旅程「需要非空」（前缀匹配；与 spec.mjs 的旅程名同源）。
ENTITY_JOURNEYS = {
    "products": ("08-", "09-", "10-", "11-", "15-", "16-", "17-", "32-"),
    "orders": ("14-", "15-", "16-", "17-", "17b-", "32-"),
    "customers": ("20-", "21-"),
    "after_sales": ("18-", "19-"),
}

RULES = ("DQ-1", "DQ-2", "DQ-3", "DQ-4", "DQ-5")


def _ran(snapshot: dict) -> set[str]:
    return {str(j) for j in (snapshot.get("ran_journeys") or [])}


def _applicable(ran: set[str], entity: str) -> bool:
    """该实体面本轮是否真的被跑到（`ran_journeys` 为空 ⇒ 全部适用，fail-closed）。"""
    prefixes = ENTITY_JOURNEYS[entity]
    if not ran:
        return True
    return any(str(j).startswith(p) for j in ran for p in prefixes)


def _entity(snapshot: dict, name: str) -> dict:
    entities = snapshot.get("entities") or {}
    return entities.get(name) or {}


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate(snapshot: dict) -> tuple[list[dict], list[dict]]:
    """返回 `(violations, undecidable)`；两者都为空 = 通过。

    每个条目都带 `code` / `rule` / `why` / `observed`，便于在汇总里**具名**打印
    （「数据不合格」必须能追到哪一面、差多少、复算命令）。
    """
    violations: list[dict] = []
    undecidable: list[dict] = []
    ran = _ran(snapshot)
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        undecidable.append({
            "code": "DQ-U", "rule": "schema",
            "why": f"快照 schema_version={snapshot.get('schema_version')!r}，本判据只认 {SCHEMA_VERSION}",
            "observed": snapshot.get("schema_version"),
        })
        return violations, undecidable

    products = _entity(snapshot, "products")
    skus = _entity(snapshot, "skus")
    fixtures = snapshot.get("fixtures") or {}
    collect_issues = snapshot.get("collection_errors") or []

    # ── DQ-U：读不到的面 ⇒ 不可判定（不许当通过）──
    for name, payload in (("products", products), ("skus", skus)):
        if payload.get("collected") is False:
            undecidable.append({
                "code": "DQ-U", "rule": name,
                "why": payload.get("why") or "采集失败（无原因登记）",
                "observed": payload.get("why"),
            })
    for name, payload in (("orders", _entity(snapshot, "orders")),
                          ("customers", _entity(snapshot, "customers")),
                          ("after_sales", _entity(snapshot, "after_sales"))):
        if payload and payload.get("collected") is False:
            undecidable.append({
                "code": "DQ-U", "rule": name,
                "why": payload.get("why") or "采集失败（无原因登记）",
                "observed": payload.get("why"),
            })
    for err in collect_issues:
        undecidable.append({"code": "DQ-U", "rule": "collection", "why": str(err), "observed": err})

    # ── DQ-1：被测商品面真的要有 SKU（用户 2026-10-23 投诉的那一条）──
    if _applicable(ran, "products"):
        total = _num(products.get("total"))
        with_skus = _num(products.get("with_skus"))
        if total is None or with_skus is None:
            undecidable.append({
                "code": "DQ-U", "rule": "DQ-1",
                "why": "商品快照缺 total/with_skus（无法判定 SKU 覆盖）",
                "observed": {"total": total, "with_skus": with_skus},
            })
        elif total >= 1 and with_skus < 1:
            violations.append({
                "code": "DQ-1", "rule": "product_sku_present",
                "why": f"{int(total)} 件商品里**没有任何一件**有 SKU（`product_skus` 覆盖 = 0）",
                "observed": {"products.total": int(total), "products.with_skus": int(with_skus)},
            })

    # ── DQ-2：冒烟自造的商品必须带 SKU（夹具不合格，下游全链没数据可测）──
    created = _num(fixtures.get("products_created"))
    created_with_skus = _num(fixtures.get("products_with_skus"))
    if created is not None and created > 0:
        if created_with_skus is None:
            undecidable.append({
                "code": "DQ-U", "rule": "DQ-2",
                "why": "fixtures 声明了 products_created 却没有 products_with_skus",
                "observed": fixtures,
            })
        elif created_with_skus < created:
            violations.append({
                "code": "DQ-2", "rule": "fixture_product_has_skus",
                "why": f"冒烟自造 {int(created)} 件商品，只有 {int(created_with_skus)} 件带 SKU",
                "observed": {"products_created": int(created), "products_with_skus": int(created_with_skus)},
            })

    # ── DQ-3：SKU 口径 canonical（`2.8` 不是 `2.8米`）──
    skus_collected = skus.get("collected") is not False
    noncanonical = _num(skus.get("door_width_noncanonical"))
    if skus_collected and _num(skus.get("total")) is not None:
        if noncanonical is None:
            undecidable.append({
                "code": "DQ-U", "rule": "DQ-3",
                "why": "SKU 快照缺 door_width_noncanonical（无法判定门幅口径）",
                "observed": skus,
            })
        elif noncanonical > 0:
            violations.append({
                "code": "DQ-3", "rule": "sku_door_width_canonical",
                "why": f"{int(_num(skus.get('total')) or 0)} 条 SKU 里 {int(noncanonical)} 条门幅不是裸数值",
                "observed": {"door_width_noncanonical": int(noncanonical),
                             "samples": skus.get("door_width_noncanonical_samples") or []},
            })

    # ── DQ-4：订单 / 客户 / 售后面非空（空态不得冒充绿）──
    for name, label in (("orders", "订单"), ("customers", "客户"), ("after_sales", "售后工单")):
        if not _applicable(ran, name):
            continue
        payload = _entity(snapshot, name)
        if not payload:
            undecidable.append({
                "code": "DQ-U", "rule": f"DQ-4:{name}",
                "why": f"快照没有 {name} 面（本轮跑了需要它的旅程，却没收数据）",
                "observed": None,
            })
            continue
        total = _num(payload.get("total"))
        if total is None:
            undecidable.append({
                "code": "DQ-U", "rule": f"DQ-4:{name}",
                "why": f"{name}.total 读数缺失",
                "observed": payload,
            })
        elif total < 1:
            violations.append({
                "code": "DQ-4", "rule": f"{name}_nonempty",
                "why": f"{label}面 0 行（相关旅程已跑 ⇒ 空态不能记通过）",
                "observed": {f"{name}.total": 0},
            })
    orders = _entity(snapshot, "orders")
    if _applicable(ran, "orders") and _num(orders.get("total")) and _num(orders.get("with_items")) == 0:
        violations.append({
            "code": "DQ-4", "rule": "order_items_nonempty",
            "why": "有订单但没有任何一张带明细（订单明细为空不是「有效订单」）",
            "observed": {"orders.total": int(_num(orders.get("total")) or 0),
                         "orders.with_items": 0},
        })

    # ── DQ-5：可删的自造对象必须清理干净（残留 = 污染下一轮）──
    residue = _num(fixtures.get("products_residue"))
    if residue is None and created is not None:
        undecidable.append({
            "code": "DQ-U", "rule": "DQ-5",
            "why": "fixtures 缺 products_residue（无法判定清理）",
            "observed": fixtures,
        })
    elif residue is not None and residue > 0:
        violations.append({
            "code": "DQ-5", "rule": "fixture_residue_cleaned",
            "why": f"冒烟自造商品残留 {int(residue)} 件（可删对象未清理）",
            "observed": {"products_residue": int(residue),
                         "samples": fixtures.get("residue_samples") or []},
        })

    return violations, undecidable


def render_markdown(snapshot: dict, violations: list[dict], undecidable: list[dict]) -> str:
    lines = ["# 冒烟数据质量体检（SDQS）", ""]
    run = snapshot.get("run") or {}
    lines += [
        f"时间：{snapshot.get('collected_at', '—')} ｜ 本轮旅程：{run.get('journeys_pass', '—')}/{run.get('journeys_total', '—')} 通过",
        "",
    ]
    if violations:
        lines += ["## ❌ 数据不合格（`DQ-*`，不随 UI 绿而变绿）", "", "| 代号 | 规则 | 现取读数 | 说明 |", "|---|---|---|---|"]
        for v in violations:
            lines.append(f"| {v['code']} | {v['rule']} | `{json.dumps(v.get('observed'), ensure_ascii=False)}` | {v['why']} |")
        lines.append("")
    if undecidable:
        lines += ["## ⚠️ 不可判定（`DQ-U`，**不得当作通过**）", ""]
        for u in undecidable:
            lines.append(f"- **{u['code']} / {u['rule']}**：{u['why']}")
        lines.append("")
    if not violations and not undecidable:
        lines += ["## ✅ 数据质量：通过", ""]
    lines += ["复算命令：`python3 scripts/smoke_data_quality.py --snapshot <本轮 smoke-data.json>`", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冒烟数据质量体检（SDQS）")
    parser.add_argument("--snapshot", required=True, help="spec.mjs 产出的 smoke-data.json")
    parser.add_argument("--md", help="把 Markdown 报告写到该路径")
    parser.add_argument("--json", action="store_true", help="把判定结果以 JSON 打到 stdout")
    args = parser.parse_args(argv)

    path = Path(args.snapshot)
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 读不到就是不可判定，不是通过
        print(f"DQ-U 不可判定：读不到数据快照 {path}（{exc}）", file=sys.stderr)
        return 3
    if not isinstance(snapshot, dict):
        print("DQ-U 不可判定：快照不是 JSON 对象", file=sys.stderr)
        return 3

    violations, undecidable = evaluate(snapshot)
    report = render_markdown(snapshot, violations, undecidable)
    if args.json:
        print(json.dumps({"violations": violations, "undecidable": undecidable}, ensure_ascii=False, indent=2))
    else:
        print(report)
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
    if violations:
        return 1
    if undecidable:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
