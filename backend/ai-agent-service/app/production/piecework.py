"""窗帘计件与完工判定（issue #3993，M4-G-1）

计件工资 = **报工合格数量 × 工序单价 × 系数**，其中系数取**工序实例上的当时快照**
（issue #4604 用户裁定 B「不追溯」：历史实例仍按快照的 1.7 算，历史金额一字不变）；
issue #4589 起**新实例不再带 `factor` 键** ⇒ 缺省 1 ⇒ 新报工不乘系数
（「计件工资 = 数量 × 计件单价」的口径只对**新报工**成立）。
单工序一人制（2026-09 客户确认，无计件人数分摊）。**全部工序**完成 → 加工单生产完成。

⚠️ 口径与 Java 侧 `ProductionService.aggregate` **逐字同源**（两处公式必须一致，否则分叉）；
完工判定与 `ProductionService#allInstancesDone` 同口径（#4961「完工 = 全部工序全绿」）。
真值源：docs/curtain-production-rules.md §4/§5。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 报工类型：normal 正常 / rework 返工 / scrap 报废
WORK_TYPES = ("normal", "rework", "scrap")


def compute_piecework(
    instances: List[Dict[str, Any]],
    work_logs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """按人/按期计件汇总：每道工序金额 = Σ(合格数量 × 单价 × 系数)。

    系数取**实例上的当时快照**（issue #4604，用户裁定 B：不追溯）：历史实例带着快照
    `factor`（如「一分为二」的 1.7）⇒ 历史金额仍按 1.7×（**一字不变**）；
    issue #4589 起新实例**不带 `factor` 键** ⇒ 缺省 1.0 ⇒ 新报工不乘系数。

    Args:
        instances: instance_operations 输出（含 qty/unit_price/factor；
                   `factor` 缺省视为 1.0 —— `is_must_finish` 键自 #4961 起已退场，
                   实例上若仍有残留也不再被任何判据读取）
        work_logs: [{operation, worker, qty, qualified_qty, type(normal/rework/scrap),
                     work_date}]——返工/报废不计入工资
    Returns: {total, per_worker: {worker: 金额}, per_operation: [{operation, amount}],
              summary: "N 道工序完成，计件合计 ¥X"}
    """
    per_worker: Dict[str, float] = {}
    per_operation: List[Dict[str, Any]] = []
    total = 0.0
    price_by_op = {inst["operation"]: inst for inst in instances}

    for log in work_logs:
        op = log.get("operation")
        if log.get("type", "normal") not in ("normal",):
            continue  # 返工/报废不计件
        inst = price_by_op.get(op)
        if inst is None:
            continue
        qty = float(log.get("qualified_qty", log.get("qty", 0)))
        amount = qty * float(inst["unit_price"]) * float(inst.get("factor", 1.0))
        worker = log.get("worker") or "未分配"
        per_worker[worker] = round(per_worker.get(worker, 0.0) + amount, 2)
        total += amount
    total = round(total, 2)

    for inst in instances:
        op_logs = [l for l in work_logs if l.get("operation") == inst["operation"]
                   and l.get("type", "normal") == "normal"]
        op_amount = round(
            sum(float(l.get("qualified_qty", l.get("qty", 0))) for l in op_logs)
            * float(inst["unit_price"]) * float(inst.get("factor", 1.0)), 2
        )
        per_operation.append({"operation": inst["operation"], "amount": op_amount})

    return {
        "total": total,
        "per_worker": dict(sorted(per_worker.items())),
        "per_operation": per_operation,
        "summary": f"{len([l for l in work_logs if l.get('type', 'normal') == 'normal'])} 道报工，计件合计 ¥{total}",
    }


def is_production_done(
    instances: List[Dict[str, Any]],
    work_logs: List[Dict[str, Any]],
) -> bool:
    """**全部工序**完成 → 加工单可进入生产完成态（#4961，用户裁定 2026-09-21「完工 = 全部工序全绿」）。

    判定：**每一道**工序实例的合格报工数量 ≥ 应做数量（`qty`）。

    口径与 Java 侧 `ProductionService#allInstancesDone` **逐字同源**
    （Java 侧只看 `done_qty ≥ qty`，实例的 `done_qty` 由报工累加而来；本函数没有 `done_qty`，
    故按同一份报工流水现算合格累计）—— 两处必须一致，否则工人端与商家端对同一单给出两套结论。

    🔴 **`is_must_finish` 已退场**：改前本函数只检查 `is_must_finish` 工序，而实例侧自本单起
    **不再带该键** ⇒ 若继续读它，`inst.get("is_must_finish")` 恒 `None` ⇒ **恒判 True**
    （「一张单一行没报也算完工」的静默假完工）。故改判「全部实例完成」。
    实例上残留的该键**不再有任何语义**（历史载体，恒 false）。
    """
    done_logs: Dict[str, float] = {}
    for log in work_logs:
        op = log.get("operation")
        if log.get("type", "normal") != "normal":
            continue
        done_logs[op] = done_logs.get(op, 0.0) + float(log.get("qualified_qty", log.get("qty", 0)))
    for inst in instances:
        if done_logs.get(inst["operation"], 0.0) < float(inst["qty"]):
            return False
    return True
