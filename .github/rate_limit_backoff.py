#!/usr/bin/env python3
"""GitHub 安装令牌限流 ⇒ 有界退避原语（issue #7549）。**一处实现，多处调用。**

## 病（2026-11-03 现网实测，不是假想）

5 个在飞 PR（#8544 / #8545 / #8546 / #8549 / #8551）同时红在**同一组 4 条腿**：
`Danger Scan` / `Secret Scan (gitleaks)` / `QA Growth Gate` / `External Authorship Guard`。
逐字读数（PR #8551 的 job 日志）：

- `QA Growth Gate`：`GET /repos/.../issues/8551/comments - 403`，响应头
  `x-ratelimit-remaining: '0'`，报文 `API rate limit exceeded for installation`；
- `External Authorship Guard`：`gh api 取 head 仓库失败：gh: API rate limit exceeded for installation` ⇒ exit 3；
- `Secret Scan (gitleaks)`：action 内部 `GET /users/<owner>` 403 ⇒ 判不出账号类型 ⇒ 要求 license ⇒
  **早退、无报告**，而归因步骤把「无报告」读成「未判定 ⇒ exit 1」，与「真扫到密钥」同形；
- `Danger Scan`：评论读 / 写 403。

⇒ 四条腿里没有一条能分清「**限流**（等一个窗口就好）」与「**真没权限**（重试一万次也不会好）」。

## 唯一职责：判定 + 有界退避（**不碰任何门禁的通过条件**）

| 判定 | 触发 | 动作 |
|---|---|---|
| `rate_limited` | 429，或 403 且（`x-ratelimit-remaining == 0`，或报文含 `rate limit`） | **有界**退避重试 |
| `denied` | 401 / 403 且**不满足**限流条件（`remaining > 0` 且报文无限流字样） | **不重试**，原样抛出 ⇒ 调用方**直接红** |
| `other` | 其余 | 不重试 |

🔴 `denied` 那一行是**本模块最重要的负控**：把「限流」与「真没权限」一起重试，等于**把真红吞掉**
—— 真没权限的 403（`Resource not accessible by integration`）重试 3 次后照样失败，但错误文本
会被写成「限流」，下一个读红的人会先去怀疑 token 配额而不是权限。

⚠️ 报文里的 `rate limit` 字样**优先于** `remaining > 0`：GitHub 的**二级限流**（secondary rate
limit）正是「报文说限流、主配额还剩」的形态 ⇒ 那种**必须**重试；而「`remaining > 0` **且**报文
是权限类」才是真无权限。两条判据各管各的形态，不是同一个开关。

## 「有界」的三条同时成立（缺一条就不是有界）

① 次数上限（默认 `3` 次尝试）；
② 单次等待上限（指数退避 `base * 2**(n-1)`，封顶 `max_delay`，且**尊重 `retry-after`**）；
③ **总时长上限**（`budget`，默认 120s）—— 下一次等待会超出预算 ⇒ **立刻放弃**并打印限流读数与
   已重试次数，**绝不无限等**（CI 里等 40 分钟 = 把腿挂死，比红更糟）。

## 三态退出码（沿用本仓既有口径：`3` = 无法判定，**不得当 0 读**）

| 码 | 含义 | 调用方正确动作 |
|---|---|---|
| `0` | 成功（含重试后成功） | 继续 |
| `1` | 真失败（含 `denied`） | 判红，**不要**归因成限流 |
| `3` | 限流退避耗尽 ⇒ **未判定** | 按非零处理（fail-closed），但文案必须说「限流 / 未判定」 |

## 调用面（四处接线 + 一个 JS 桥）

1. `pr-check.yml` 的 Danger Scan **评论读取**步 —— `exec` 子命令（原先读失败 `exit 0`，红得无声无息）；
2. 同文件的 Danger Scan / QA Growth Gate 评论步 —— JS 经 `.github/scripts/rate-limit-backoff.js`
   调本模块的 `classify` 子命令 ⇒ **判定只有这一份实现**，JS 侧只做循环与等待；
3. 同文件的 gitleaks license 校验预检 —— `exec --best-effort`（预检失败不额外判红，扫描步自己判）；
4. `scripts/external_authorship_guard.py` —— `call()` 直接包住它的 `gh api`。

零第三方依赖、零隐式网络（网络动作全由调用方注入 ⇒ 判据可离线跑）。
承载体 = `tests/unit_ci_workflows/test_rate_limit_backoff.py`。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

RATE_LIMITED = "rate_limited"
DENIED = "denied"
OTHER = "other"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNDECIDABLE = 3

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_BUDGET = 120.0

#: 报文里出现这些字样 ⇒ 归「限流」（`gh` CLI 不带响应头时这是**唯一**信号）。
_RATE_LIMIT_HINTS = ("rate limit", "ratelimit", "abuse detection", "secondary rate")

_HTTP_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")


# ─────────────────────────── 判定 ───────────────────────────
def _header(headers: Mapping[str, Any] | None, name: str) -> str | None:
    """大小写不敏感地取响应头（GitHub / octokit / urllib 的键大小写不统一）。"""
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            return str(value)
    return None


def classify(status: Any, headers: Mapping[str, Any] | None = None, message: str = "") -> str:
    """把一次失败归成 `rate_limited` / `denied` / `other`（**唯一判定点**）。"""
    try:
        code = int(status or 0)
    except (TypeError, ValueError):
        code = 0
    text = str(message or "").lower()
    hinted = any(hint in text for hint in _RATE_LIMIT_HINTS)

    if code == 429:
        return RATE_LIMITED
    if code in (401, 403):
        remaining = _header(headers, "x-ratelimit-remaining")
        if remaining is not None:
            try:
                if int(remaining) <= 0:
                    return RATE_LIMITED  # 主配额打满（安装令牌现场）
            except ValueError:
                pass
        # 报文说限流 ⇒ 二级限流（此时 remaining 通常 > 0）；否则 = **真没权限**
        return RATE_LIMITED if hinted else DENIED
    return RATE_LIMITED if hinted else OTHER


class GithubError(RuntimeError):
    """适配层把各自的失败（subprocess / octokit / urllib）统一成这一种。"""

    def __init__(self, status: Any, headers: Mapping[str, Any] | None = None, message: str = ""):
        self.status = status
        self.headers = dict(headers or {})
        self.message = message
        super().__init__(f"HTTP {status}: {str(message)[:300]}")

    @property
    def outcome(self) -> str:
        return classify(self.status, self.headers, self.message)


class RetryExhausted(RuntimeError):
    """限流退避用尽 ⇒ **未判定**（不是「真失败」）。"""

    def __init__(self, label: str, attempts: int, error: GithubError, reason: str):
        self.label = label
        self.attempts = attempts
        self.error = error
        self.reason = reason
        super().__init__(
            f"{label}：限流退避用尽（{reason}，已尝试 {attempts} 次，最后一次 HTTP {error.status}）"
        )


# ─────────────────────────── 退避 ───────────────────────────
@dataclass(frozen=True)
class Policy:
    attempts: int = DEFAULT_ATTEMPTS
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    budget: float = DEFAULT_BUDGET

    def delay_for(self, attempt: int, headers: Mapping[str, Any] | None = None) -> float:
        """第 `attempt` 次失败后该等多久（秒）。指数退避 ∧ 尊重 `retry-after` ∧ 封顶。"""
        delay = self.base_delay * (2 ** max(attempt - 1, 0))
        hinted = _header(headers, "retry-after")
        if hinted is not None:
            try:
                delay = max(delay, float(hinted))
            except ValueError:
                pass
        return min(delay, self.max_delay)


def call(
    fn: Callable[[], Any],
    *,
    label: str,
    policy: Policy | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """执行 `fn()`，**只对限流**做有界退避 —— `denied` / `other` 原样抛出、**一次也不多试**。"""
    policy = policy or Policy()
    started = clock()
    for attempt in range(1, policy.attempts + 1):
        try:
            return fn()
        except GithubError as exc:
            if exc.outcome != RATE_LIMITED:
                raise  # 真没权限 / 其它 ⇒ 立刻红（**不许**吞）
            if attempt >= policy.attempts:
                raise RetryExhausted(label, attempt, exc, "次数上限") from exc
            delay = policy.delay_for(attempt, exc.headers)
            if (clock() - started) + delay > policy.budget:
                raise RetryExhausted(label, attempt, exc, "总时长上限") from exc
            print(
                f"⏳ {label}：限流（HTTP {exc.status}），{delay:.1f}s 后重试"
                f"（第 {attempt}/{policy.attempts} 次）",
                file=sys.stderr,
                flush=True,
            )
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


# ─────────────────────── 适配层：外部命令（gh api）───────────────────────
def _status_from_text(text: str) -> int:
    match = _HTTP_STATUS_RE.search(text or "")
    return int(match.group(1)) if match else 0


def call_command(
    argv: Sequence[str],
    *,
    label: str,
    policy: Policy | None = None,
    output: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], Any] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> subprocess.CompletedProcess:
    """跑一条命令并在**限流**时有界重试；成功后把 stdout 落到 `output`（重试不写半成品）。"""

    def attempt() -> subprocess.CompletedProcess:
        proc = runner(list(argv), capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            return proc
        body = (proc.stderr or proc.stdout or "").strip()
        raise GithubError(_status_from_text(body), {}, body[:400])

    proc = call(attempt, label=label, policy=policy, sleep=sleep, clock=clock)
    if output:
        Path(output).write_text(proc.stdout, encoding="utf-8")
    return proc


# ─────────────────────────── CLI ───────────────────────────
def _describe(payload: Mapping[str, Any], attempt: int | None) -> dict[str, Any]:
    outcome = classify(payload.get("status"), payload.get("headers") or {}, payload.get("message") or "")
    result: dict[str, Any] = {"outcome": outcome}
    if attempt is not None and outcome == RATE_LIMITED:
        result["delay"] = Policy().delay_for(attempt, payload.get("headers") or {})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub 限流判定 + 有界退避（issue #7549）")
    sub = parser.add_subparsers(dest="command", required=True)

    classify_p = sub.add_parser("classify", help="判一条失败响应（供 JS 桥调用）")
    classify_p.add_argument("--json", default="-", help="`{status,headers,message}` 或 `-` 读 stdin")
    classify_p.add_argument("--attempt", type=int, default=None, help="当前第几次尝试（给了才算 delay）")

    exec_p = sub.add_parser("exec", help="跑一条命令，限流时有界重试")
    exec_p.add_argument("--label", required=True)
    exec_p.add_argument("--output", default=None, help="成功后把 stdout 写入该文件")
    exec_p.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    exec_p.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    exec_p.add_argument("--base-delay", type=float, default=DEFAULT_BASE_DELAY)
    exec_p.add_argument("--max-delay", type=float, default=DEFAULT_MAX_DELAY)
    exec_p.add_argument(
        "--best-effort",
        action="store_true",
        help="退避耗尽也不非零退出（**仅限预检**：预检失败不额外判红，由被保护的步骤自己判）",
    )
    exec_p.add_argument("cmd", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)

    if args.command == "classify":
        raw = sys.stdin.read() if args.json == "-" else args.json
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"❌ classify 入参不是 JSON：{exc}", file=sys.stderr)
            return 2
        print(json.dumps(_describe(payload, args.attempt), ensure_ascii=False))
        return EXIT_OK

    cmd = list(args.cmd)
    while cmd and cmd[0] == "--":
        cmd.pop(0)
    if not cmd:
        print("❌ exec 缺少要执行的命令（用法：... exec --label X -- gh api ...）", file=sys.stderr)
        return 2

    policy = Policy(
        attempts=max(args.attempts, 1),
        base_delay=max(args.base_delay, 0.0),
        max_delay=max(args.max_delay, 0.0),
        budget=max(args.budget, 0.0),
    )
    try:
        call_command(cmd, label=args.label, policy=policy, output=args.output)
    except RetryExhausted as exc:
        print(f"⛔ {exc} —— **未判定**（exit {EXIT_UNDECIDABLE}，不得当 0 读）。", file=sys.stderr)
        print(f"   · 最后一次读数：HTTP {exc.error.status} {str(exc.error.message)[:200]}", file=sys.stderr)
        print("   · 这是**安装令牌限流**（瞬时态），不是本 PR 的问题；重跑该腿即可。", file=sys.stderr)
        return EXIT_OK if args.best_effort else EXIT_UNDECIDABLE
    except GithubError as exc:
        print(f"❌ {args.label} 失败：HTTP {exc.status}（**非限流**，不重试）", file=sys.stderr)
        print(f"   · 读数：{str(exc.message)[:300]}", file=sys.stderr)
        return EXIT_OK if args.best_effort else EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
