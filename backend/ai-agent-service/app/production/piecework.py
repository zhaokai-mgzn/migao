"""窗帘计件与完工判定（issue #3993，M4-G-1）

计件工资 = Σ(报工合格数量 × 工序单价 × 特殊选项系数)；单工序一人制
（2026-09 客户确认，无计件人数分摊）。必完工序全绿 → 订单自动生产完成。

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

    Args:
        instances: instance_operations 输出（含 qty/unit_price/factor/is_must_finish）
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
    """必完工序全绿 → 订单可自动进入生产完成态。

    判定：每个 is_must_finish 工序的合格报工数量 ≥ 应做数量（qty）。
    """
    done_logs: Dict[str, float] = {}
    for log in work_logs:
        op = log.get("operation")
        if log.get("type", "normal") != "normal":
            continue
        done_logs[op] = done_logs.get(op, 0.0) + float(log.get("qualified_qty", log.get("qty", 0)))
    for inst in instances:
        if inst.get("is_must_finish") and done_logs.get(inst["operation"], 0.0) < float(inst["qty"]):
            return False
    return True
