"""P0 冒烟的**瞬态**重试策略（issue #4182 的判据层）—— 纯 stdlib，**不 import httpx**。

## 病根（2026-09-17 现场，实测读数）

`Post-Deploy Smoke Test` 在 `d5435e45` 上 `3 failed, 17 passed`，失败形态只有两种：
`httpx.RemoteProtocolError: Server disconnected` 与 `AssertionError: Expected 200, got 502`；
同一部署腿的前一个 SHA（`f752f980`）端到端全绿、部署本身（Buildx/Push/Deploy）也全过。
⇒ 「服务正在滚动重启」的**窗口**被判成了「服务坏了」。同形态 2026-09-19 再复现一次
（`3 failed, 17 passed`，全 502）。而当时的失败证据只在 job log 里，判不了红 —— 两条一起修。

## 口径（本文件是唯一实现，判据读**行为**不读文案）

| 面 | 规则 | 为什么 |
|---|---|---|
| 瞬态签名 | HTTP `502`/`503`/`504` **或** 传输层断开（`RemoteProtocolError`/`ConnectError`/`*Timeout`/`ReadError`/`WriteError`/`PoolTimeout`） | 网关在换实例时的两种表现 |
| 重试位置 | **请求层**（拿到响应/异常之后、任何断言之前） | 真断言（`resp.status_code == 200`、响应体校验）**一次都不会被重跑** |
| 非瞬态 | `500`/`401`/`404`/… 立即原样返回 | 真有东西坏了必须当场红；`500` **永不**被当成瞬态 |
| 有界 | 单请求 ≤ 5 次尝试，失败后等 `2/4/8/15s`（单请求最多多等 29s）；**整个 pytest 会话**额外等待上限 180s | 短窗口自愈；长窗口 = 真回归，不许被"等"成绿 |
| 预算用尽 | 瞬态签名**立即**失败（不再等待） | 同上：等待只买时间，不买结论 |
| 耗尽后 | 原样交出**最后一次**的响应/异常 | 上层断言照旧红，文案照旧 `Expected 200, got 502` |
| 可见 | 每次重试打一行（含累计等待/上限） | 有重试就不是"干净的绿"，summary 与 artifact 里看得见 |

## 为什么不复用 `tests/agent_eval/local_runner.py::_retry_502`

那边是**评测**面（async、`max_retries=6`、等 `20s×n`），且 `local_runner` 有模块级副作用
（服务 token 校验 + `sys.exit(1)`）⇒ 部署腿的同步冒烟不能 import 它。两者口径同源
（只重试 502/503/504 与连接失败，400/401/403/404 不重试），实现各自一份 ——
本文件的行为由 `tests/unit_ci_workflows/test_smoke_transient_retry.py` 钉住。
"""

import time

#: 网关层瞬态（实例正在被换掉）。**`500` 不在这里**：真有东西坏了必须当场红（issue #4182）。
TRANSIENT_STATUS = (502, 503, 504)

#: 传输层断开。按**类名**判定（httpx 各版本与子类的继承关系会漂移，类名才是稳定面）。
TRANSIENT_EXCEPTION_NAMES = frozenset({
    "RemoteProtocolError", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "ReadError", "WriteError", "WriteTimeout", "PoolTimeout",
})

#: 单请求：最多 5 次尝试，失败后等待 2 / 4 / 8 / 15s（即单请求最多多等 29s）。
MAX_ATTEMPTS = 5
DELAYS = (2.0, 4.0, 8.0, 15.0)

#: 整个 pytest 会话允许的额外等待上限（秒）。用尽 ⇒ 瞬态签名立即失败。
SESSION_WAIT_BUDGET_S = 180.0


def is_transient_status(status_code) -> bool:
    """`502`/`503`/`504` = 瞬态；其余（含 `500`）= 非瞬态，立即判红。"""
    return isinstance(status_code, int) and status_code in TRANSIENT_STATUS


def is_transient_exception(exc) -> bool:
    """传输层断开（类名命中即瞬态）；其余异常（含断言/解析错误）不得重试。"""
    return type(exc).__name__ in TRANSIENT_EXCEPTION_NAMES


class WaitLedger:
    """整个 pytest 会话共享的等待账本（预算用尽即停止等待；读数供 summary 使用）。"""

    def __init__(self, budget_s: float = SESSION_WAIT_BUDGET_S):
        self.budget_s = float(budget_s)
        self.waited = 0.0
        self.retries = 0
        self.transient_events = 0

    def remaining(self) -> float:
        return max(0.0, self.budget_s - self.waited)

    def reset(self) -> None:
        self.waited = 0.0
        self.retries = 0
        self.transient_events = 0


#: 进程内唯一账本（`admin_client` / `ai_client` 共用同一份预算 —— 预算必须是**会话级**的）。
SESSION_LEDGER = WaitLedger()


class TransientRetrier:
    """把「瞬态」与「真失败」分开的那一处实现。

    `run(call)`：`call()` 返回带 `.status_code` 的响应对象（或抛异常）。
    返回值 = 第一个非瞬态响应；若全程瞬态 ⇒ **最后一次**的响应（或抛出最后一次的异常）。
    """

    def __init__(self, *, max_attempts: int = MAX_ATTEMPTS, delays=DELAYS,
                 ledger: WaitLedger | None = None, sleep=time.sleep, log=print):
        self.max_attempts = int(max_attempts)
        self.delays = tuple(delays)
        self.ledger = SESSION_LEDGER if ledger is None else ledger
        self.sleep = sleep
        self.log = log
        #: 最近一次 `run()` 的尝试次数（读数：非瞬态必须恒为 1）。
        self.attempts = 0

    def run(self, call):
        self.attempts = 0
        last_exc = None
        response = None
        for attempt in range(1, self.max_attempts + 1):
            self.attempts = attempt
            last_exc = None
            try:
                response = call()
            except Exception as exc:                       # noqa: BLE001 —— 由白名单决定是否瞬态
                if not is_transient_exception(exc):
                    raise                                   # 非瞬态异常原样上抛（断言/解析错误照旧红）
                last_exc = exc
                reason = f"{type(exc).__name__}: {exc}"
            else:
                if not is_transient_status(response.status_code):
                    return response                          # 含 500：立即返回，断言照旧执行
                reason = f"HTTP {response.status_code}"
            self.ledger.transient_events += 1
            if attempt >= self.max_attempts:
                break
            budget_left = self.ledger.remaining()
            if budget_left <= 0:
                self.log(f"::warning::冒烟瞬态等待预算已耗尽（累计 {self.ledger.waited:.0f}s / "
                         f"上限 {self.ledger.budget_s:.0f}s）⇒ {reason} 不再重试（照旧判红，issue #4182）")
                break
            delay = min(self.delays[attempt - 1], budget_left)
            self.ledger.retries += 1
            self.ledger.waited += delay
            self.log(f"::warning::冒烟遇瞬态（第 {attempt}/{self.max_attempts} 次）：{reason} —— "
                     f"等待 {delay:.1f}s 后重试（部署滚动重启窗口，issue #4182；"
                     f"累计等待 {self.ledger.waited:.0f}s / 上限 {self.ledger.budget_s:.0f}s）")
            self.sleep(delay)
        if last_exc is not None:
            raise last_exc
        return response
