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


# DeepSeek 定价（元 / 百万 tokens，参考公开价目）
# 模型名统一使用 settings 常量，下线模型只需改 config.py
from app.config import settings
MODEL_PRICING: dict[str, dict[str, float]] = {
    settings.LLM_MODEL_FAST:    {"input": 1.00, "output": 4.00},       # deepseek-v4-flash
    settings.LLM_MODEL_PRIMARY: {"input": 1.00, "output": 4.00},       # deepseek-v4-flash
    # 视觉模型与主模型同价，但**必须显式登记**：缺失时视觉调用会在兜底查找中
    # KeyError，被调用点 try/except 吞掉 → token 静默不计费（issue #3270 成本账缺口）
    settings.VISION_MODEL:      {"input": 1.00, "output": 4.00},       # deepseek-v4-flash-vision-exp
}

# 最终兜底定价：**字面量**，不依赖任何 settings 字段。
# 目的：即使 PRIMARY_MODEL/VISION_MODEL 被配成定价表未跟进的新模型名，
# 成本计算也绝不抛异常（宁可偏高估算，不可静默漏算或中断主流程）。
_FALLBACK_PRICING: dict[str, float] = {"input": 1.00, "output": 4.00}


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录"""

    model: str
    input_tokens: int
    output_tokens: int
    cost_cny: float
    tenant_id: Optional[int] = None
    session_id: Optional[str] = None


def _resolve_pricing(model: str) -> tuple[dict[str, float], Optional[str]]:
    """定位模型定价，返回 (定价, 命中的模型名；未直接命中时为 None)

    查找顺序（逐级兜底，**任何一级都不得抛异常**）：
    1. 精确命中 MODEL_PRICING[model]
    2. 依次尝试主/快/视觉模型定价（settings 派生的默认档）
    3. 字面量 _FALLBACK_PRICING

    第 2/3 级命中说明定价表与 settings 存在漂移，调用方据此打 warning ——
    让「漏配定价」显性可见，而不是静默按错档计费。
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model], model

    for default_model in (
        getattr(settings, "LLM_MODEL_PRIMARY", ""),
        getattr(settings, "LLM_MODEL_FAST", ""),
        getattr(settings, "VISION_MODEL", ""),
    ):
        if default_model and default_model in MODEL_PRICING:
            return MODEL_PRICING[default_model], default_model

    return _FALLBACK_PRICING, None


def _calc_cost_cny(model: str, input_tokens: int, output_tokens: int) -> float:
    """按 MODEL_PRICING 计算单次调用人民币成本

    未匹配到的模型按默认档兜底（含字面量终兜底），避免成本被静默漏算，
    也避免默认档自身缺配时抛 KeyError 打断主流程。
    """
    pricing, matched = _resolve_pricing(model)
    if matched is None:
        logger.warning(
            "[LLM_COST] 模型 %s 无定价且默认档均未登记，按字面量兜底价计费"
            "（请在 MODEL_PRICING 补登记）",
            model,
        )
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
