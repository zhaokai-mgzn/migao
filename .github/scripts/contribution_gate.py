#!/usr/bin/env python3
"""Contribution Gate 的执行策略层：**「判不了」不等于「违规」**（issue #8395）。

## 病（实测，不是假说）

本闸门的两道判定都靠 GitHub REST API（`gh api`）。安装令牌限流时两道守卫按 fail-closed
返回 `exit 2` / `exit 3` ⇒ `run:` 步非零 ⇒ **job 判红**。2026-11-02 16:35 实测
（run `41483003592`，逐字）：

    ⛔ 无法判定（exit 3，**不得当 0 读**）：gh api 取 head 仓库失败：
       gh: API rate limit exceeded for installation. ... (HTTP 403)

⇒ 这条腿一旦是 **required**，每一次限流窗口都会**锁死所有合并**（当晚实测 4 次假红）。
裁定（2026-11-03）：**先证明「判不了 ≠ 违规」在 CI 层不会把 required 变红，再翻 required。**

## 三态口径（每条都有会红的判据）

| # | 形态 | 处置 |
|---|---|---|
| 1 | **可证明是限流**（退出码 ∉ {0,1} 且输出含限流标记）⇒ 有界重试（默认 3 次、退避 2s/8s）；重试后仍限流 | **不判红**：`exit 0` + 具名 `::warning::`「本次未判定」 |
| 2 | **真实命中**（退出码 `1`） | **原样透传 `exit 1`**。⚠️ 退出码 1 **永不**被重新归类成「限流」 |
| 3 | **非限流的读不到**（退出码 2 / 3 且无上述标记） | **原样透传**（仍判红 —— 既有口径一字不改） |

## 为什么「包一层」而不是改两个守卫

两道判定的唯一实现分别在 `scripts/external_authorship_guard.py` 与
`.github/scripts/sensitive_path_guard.py`（`pull_request_target` 面要求判定只读 base 里的实现）。
重试 / 宽容策略因此只写**一份**，两个守卫**一行不改** —— 改两份就是两份会漂的口径
（同 `migao-dev-flow` §28.2「判据实体只许有一份实现」）。

## 边界（照实登记）

- 判不了「限流是否真的瞬态」：重试 3 次仍限流 ⇒ 本次**确实没判定**（由 `::warning::` 具名播报，
  不是静默变绿）；值班面 = PR 页上的该 warning annotation。
- 判不了「非限流的读不到」会不会是瞬态：按裁定 ③ **保持 fail-closed 判红**（既有口径不变）。
- 本层**不改**任何判定逻辑：谁该红、谁该绿，仍由两个守卫决定。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence

#: 有界重试的次数上限（含首次判定）。实测限流窗口通常是秒级 ⇒ 3 次足够、且不会把
#: workflow 的 `timeout-minutes: 5` 撑破（最坏额外 10s 退避）。
MAX_ATTEMPTS = 3
#: 退避序列（秒）：第 1 次失败后等 2s，第 2 次后等 8s。超界取最后一个。
BACKOFF_SECONDS = (2.0, 8.0)
#: 「真实命中」的退出码 —— **只有它**是违规；永不参与限流归类。
EXIT_VIOLATION = 1
#: 「本次未判定但不判红」的退出码。
EXIT_TOLERATED_UNDECIDED = 0
#: 限流标记（小写比较）。要求**具体**：泛泛的 403 / 5xx **不算**（那是真故障，仍须判红）。
RATE_LIMIT_MARKERS = (
    "api rate limit exceeded",
    "secondary rate limit",
    "rate limit exceeded",
    "x-ratelimit-remaining: 0",
    "x-ratelimit-remaining:0",
)


def is_provable_rate_limit(rc: int, output: str) -> bool:
    """纯判定：这次失败**是否可证明是限流**（⇒ 可重试、可宽容）。

    🔴 退出码 `0`（放行）与 `1`（真实命中）**一律**返回 `False`：否则一段恰好含
    `rate limit` 字样的违规输出就能把闸门洗白（那正是「放宽」）。
    """
    if rc == 0 or rc == EXIT_VIOLATION:
        return False
    text = (output or "").lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def _run_once(argv: Sequence[str]) -> tuple[int, str]:
    """跑一次子命令 → `(退出码, stdout+stderr)`；输出**照常回显**（合并日志不丢诊断）。"""
    proc = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
        sys.stdout.flush()
    return proc.returncode, out


def run_with_retry(
    argv: Sequence[str],
    *,
    label: str,
    attempts: int = MAX_ATTEMPTS,
    backoff: Sequence[float] = BACKOFF_SECONDS,
    run: Callable[[Sequence[str]], tuple[int, str]] = _run_once,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """按三态口径跑一次判定 → 退出码（`0` 通过 / 未判定不判红、`1` 真实命中、`2|3` 非限流读不到）。"""
    if attempts < 1:
        raise ValueError(f"attempts 必须 ≥ 1（收到 {attempts}）")
    for attempt in range(1, attempts + 1):
        rc, out = run(argv)
        if rc == 0:
            print(f"✅ {label}：通过（第 {attempt}/{attempts} 次判定）")
            return 0
        if not is_provable_rate_limit(rc, out):
            print(f"❌ {label}：判红（exit {rc}；不可证明是限流 ⇒ 按既有口径透传，fail-closed）")
            return rc
        if attempt < attempts:
            delay = backoff[min(attempt - 1, len(backoff) - 1)] if backoff else 0.0
            print(f"⏳ {label}：可证明是 API 限流（第 {attempt}/{attempts} 次）⇒ {delay:g}s 后重试")
            sleep(delay)
    print(
        f"::warning::{label} 本次未判定（API 限流，有界重试 {attempts} 次后仍限流）—— "
        "不判红；限流是瞬态，重跑该腿即可"
    )
    return EXIT_TOLERATED_UNDECIDED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Contribution Gate 执行策略层（issue #8395）：限流有界重试 + 「判不了不判红」"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    retry = sub.add_parser("retry", help="跑一条判定（可证明限流时有界重试；重试后仍限流则不判红）")
    retry.add_argument("--label", required=True, help="该判定的具名标签（进 warning / 日志）")
    retry.add_argument("--attempts", type=int, default=MAX_ATTEMPTS, help=f"判定次数上限（默认 {MAX_ATTEMPTS}）")
    retry.add_argument(
        "--backoff-seconds",
        type=float,
        default=None,
        help="单值覆盖退避序列（CI 默认序列；判据用 0 ⇒ 不挂钟）",
    )
    retry.add_argument("command", nargs=argparse.REMAINDER, help="`--` 之后的真实判定命令")
    args = parser.parse_args(argv)

    command = [str(x) for x in args.command]
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("retry 需要 `--` 之后的一条命令（例：-- python3 scripts/external_authorship_guard.py …）")
    backoff: Sequence[float] = (
        BACKOFF_SECONDS if args.backoff_seconds is None else (max(args.backoff_seconds, 0.0),)
    )
    return run_with_retry(command, label=args.label, attempts=args.attempts, backoff=backoff)


if __name__ == "__main__":
    sys.exit(main())
