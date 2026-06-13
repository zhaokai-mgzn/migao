"""
LLM 成本追踪

进程内累计每次 LLM 调用产生的 input/output token 与人民币成本，
并按 settings.LLM_MONTHLY_BUDGET_CNY 校验预算上限。

设计要点：
- 仅依赖标准库（dataclasses + logging），不引入第三方
- 单实例进程内累计；跨进程汇总由日志采集（SLS）侧负责
- track_call 不做 I/O，只追加内存记录 + 一行结构化日志
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from app.config import settings


logger = logging.getLogger(__name__)


# MiniMax 定价（元 / 百万 tokens，参考公开价目）
# 模型名统一使用 settings 常量，下线模型只需改 config.py
from app.config import settings
MODEL_PRICING: dict[str, dict[str, float]] = {
    settings.LLM_MODEL_FAST:    {"input": 1.00, "output": 4.00},       # M2.7-highspeed
    settings.LLM_MODEL_PRIMARY: {"input": 4.00, "output": 16.00},      # MiniMax-M3
}


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录"""

    model: str
    input_tokens: int
    output_tokens: int
    cost_cny: float
    tenant_id: Optional[int] = None
    session_id: Optional[str] = None


def _calc_cost_cny(model: str, input_tokens: int, output_tokens: int) -> float:
    """按 MODEL_PRICING 计算单次调用人民币成本

    未匹配到的模型按 plus 档兜底，避免成本被静默漏算。
    """
    pricing = MODEL_PRICING.get(model) or MODEL_PRICING[settings.LLM_MODEL_PRIMARY]  # fallback 到主模型定价
    cost_input = (input_tokens / 1_000_000.0) * pricing["input"]
    cost_output = (output_tokens / 1_000_000.0) * pricing["output"]
    return round(cost_input + cost_output, 6)


class CostTracker:
    """LLM 调用成本追踪器（进程内累计）"""

    def __init__(self) -> None:
        self._records: list[CostRecord] = []
        self._total_cost: float = 0.0
        self._lock: Lock = Lock()
        self._budget_warned: bool = False

    # ---------- 写入 ----------
    def track_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        tenant_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Optional[CostRecord]:
        """记录一次 LLM 调用的成本

        Args:
            model: 模型名（用于查表定价）
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            tenant_id: 可选，租户 ID
            session_id: 可选，会话 ID

        Returns:
            写入的 CostRecord；当 LLM_COST_TRACKING_ENABLED=False 时返回 None
        """
        if not settings.LLM_COST_TRACKING_ENABLED:
            return None

        cost = _calc_cost_cny(model, input_tokens, output_tokens)
        record = CostRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cny=cost,
            tenant_id=tenant_id,
            session_id=session_id,
        )

        with self._lock:
            self._records.append(record)
            self._total_cost += cost

        logger.info(
            "[LLM_COST] model=%s input=%d output=%d cost=¥%.6f "
            "tenant=%s session=%s total=¥%.4f",
            model,
            input_tokens,
            output_tokens,
            cost,
            tenant_id if tenant_id is not None else "-",
            session_id or "-",
            self._total_cost,
        )

        # 预算检查（仅首次超额时 warning，避免日志刷屏）
        self.check_budget()
        return record

    # ---------- 读取 ----------
    @property
    def total_cost(self) -> float:
        """累计成本（人民币元）"""
        return self._total_cost

    def check_budget(self) -> bool:
        """检查是否超预算

        Returns:
            True 表示已超预算
        """
        budget = settings.LLM_MONTHLY_BUDGET_CNY
        if budget <= 0:
            return False
        over = self._total_cost >= budget
        if over and not self._budget_warned:
            logger.warning(
                "[LLM_COST] monthly budget exceeded: total=¥%.4f budget=¥%.2f",
                self._total_cost,
                budget,
            )
            self._budget_warned = True
        return over

    def get_summary(self) -> dict:
        """返回成本汇总，按模型分组

        Returns:
            {
                "total_cost": float,
                "total_calls": int,
                "by_model": {model: {"calls": int, "input_tokens": int,
                                      "output_tokens": int, "cost_cny": float}},
                "budget_cny": float,
                "over_budget": bool,
            }
        """
        by_model: dict[str, dict[str, float]] = {}
        for r in self._records:
            slot = by_model.setdefault(
                r.model,
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_cny": 0.0},
            )
            slot["calls"] += 1
            slot["input_tokens"] += r.input_tokens
            slot["output_tokens"] += r.output_tokens
            slot["cost_cny"] = round(slot["cost_cny"] + r.cost_cny, 6)

        return {
            "total_cost": round(self._total_cost, 6),
            "total_calls": len(self._records),
            "by_model": by_model,
            "budget_cny": settings.LLM_MONTHLY_BUDGET_CNY,
            "over_budget": self._total_cost >= settings.LLM_MONTHLY_BUDGET_CNY > 0,
        }

    def reset(self) -> None:
        """重置累计（仅用于测试）"""
        with self._lock:
            self._records.clear()
            self._total_cost = 0.0
            self._budget_warned = False
