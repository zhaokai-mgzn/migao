"""商品健康度 · 归因（同款对照：问题出在这个变体，还是整个商品？）—— issue #8290 从 product_health.py 拆出

判据来源：issue #8279（P3「归因」）+ 缺陷 #8280（毛利 verdict 方向）。依赖 `product_numbers`
（读数值与精度）与 `product_judgement`（分档常量），**不 import 视图模块**（拆分前与视图同住
⇒ 循环依赖，见 issue #8290）。样本量读数复用内核读取器（`app.briefing.proactive._num`），不另写一份。

## 🔴 三条不许（写码时实测撞出来的，见 issue #8279 的自我纠正评论）

· **退货率是商品级数据**（`product_return_stats` 按 product_id 聚合）⇒ 同一商品下所有 SKU 拿到
  **同一个** `return_rate`，拿它做变体对照的 gap **恒等于 0** —— 那是假归因。⇒ 变体归因**只能用
  SKU 级信号（毛利）**；退货率只能落成 `product_level_only`（明说指不到变体）。
· **单独一个 SKU 不许给归因**：没有对照就没有差异，`None` 才是诚实的（不是「没问题」）。
· **兄弟的毛利未知不许算进来**：拿脏数据算差值，差值本身就成了噪音。
· **不给因果断言**：只说「差异指向这个变体的定价/成本」，不说「因为这个变体质量差」。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.briefing.product_judgement import VERDICT_BAD, VERDICT_WATCH
from app.briefing.product_numbers import _dec, _out
from app.briefing.proactive import _num

#: 归因自述（P3「归因」issue #8279）—— **差异不是因果**
ATTRIBUTION_BASIS = (
    "同款对照，**只对 SKU 级信号有效**（毛利）：同一商品下多个变体之间比毛利率，"
    "差异指向「问题更可能出在这个变体的**定价或成本维护**」。"
    "退货率是**商品级**数据（`product_return_stats` 按 product_id 聚合）⇒ 同一商品所有 SKU 拿到同一个数，"
    "**指不到具体变体** —— 这种情况只给「整款退货高」，不给变体归因。"
    "这是**差异证据，不是因果结论**：样本量差很多时差异可能只是样本量（销量并排给出，由人判断）"
)


def _attribution(
    row: Dict[str, Any], siblings: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """归因（issue #8279）—— 「问题出在这个变体，还是整个商品？」。

    🔴 关键约束（写码时实测撞出来的，见 issue #8279 的自我纠正评论）：
    **退货率是商品级数据**（`product_return_stats` 按 `product_id` 聚合）⇒ 同一商品下所有 SKU
    拿到**同一个** `return_rate`，拿它做变体对照的 gap **恒等于 0** —— 那是假归因。
    ⇒ 变体归因**只能用 SKU 级信号（毛利）**；退货率只能落成 `product_level_only`（明说指不到变体）。

    其余三条不许：
    · **单独一个 SKU 不许给归因**：没有对照就没有差异，`None` 才是诚实的（不是「没问题」）。
    · **兄弟的毛利未知不许算进来**：拿脏数据算差值，差值本身就成了噪音。
    · **不给因果断言**：只说「差异指向这个变体的定价/成本」，不说「因为这个变体质量差」。
    """
    rate_verdict = row.get("return_rate_verdict")
    margin_verdict = row.get("gross_margin_verdict")
    if rate_verdict not in (VERDICT_BAD, VERDICT_WATCH) and margin_verdict not in (
        VERDICT_BAD,
        VERDICT_WATCH,
    ):
        return None

    # ① 毛利（SKU 级）⇒ 可以指到变体
    mine = _dec(row.get("gross_margin"))
    if mine is not None and margin_verdict in (VERDICT_BAD, VERDICT_WATCH):
        peers = [
            item for item in siblings
            if item.get("sku_id") != row.get("sku_id") and _dec(item.get("gross_margin")) is not None
        ]
        if peers:
            best = max(peers, key=lambda item: _dec(item["gross_margin"]))
            best_margin = _dec(best["gross_margin"])
            if best_margin > mine:
                return {
                    "kind": "sibling_margin_contrast",
                    "level": "sku",
                    "sibling_count": len(peers) + 1,
                    "best_sibling_sku_id": best.get("sku_id"),
                    "best_sibling_gross_margin": _out(best_margin),
                    "gap": _out(mine - best_margin),
                    "sample_note": (
                        f"本 SKU 销量 {_sales_text(row)}、对比的兄弟 {_sales_text(best)}；"
                        "样本量差很多时差异可能只是样本量 —— 这是**差异证据，不是因果结论**"
                    ),
                }

    # ② 退货率（商品级）⇒ **指不到变体**，只如实说清「整款高的原因不在这份数据里」
    if rate_verdict in (VERDICT_BAD, VERDICT_WATCH):
        return {
            "kind": "product_level_only",
            "level": "product",
            "reason": (
                "退货率是**商品级**数据（按 product_id 聚合）⇒ 同一商品下所有变体拿到同一个数，"
                "这里**指不到具体变体**。要定位到变体，需要 SKU 级的退货原因数据（当前快照没有）"
            ),
        }

    return None


def _sales_text(row: Dict[str, Any]) -> str:
    count = _num(row.get("sales_count"))
    return "未知" if count is None else f"{int(count)} 件"
