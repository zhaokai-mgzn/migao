#!/usr/bin/env python3
"""陈旧 CI 报告收口（issue #5491）—— **腿转绿 ⇒ 自动关陈旧报告**。

## 病灶

本仓的 CI 腿失败时会**自动开单**（`[Post-Deploy] …` / `[Nightly] …` / `[drift] …` 一族）。
腿恢复之后，那张单子**一直挂着**、没有任何东西会发现 —— 2026-09-25 的存量清理里，
**7 条**这类报告是人工逐条核验后才关的（同族 open：#4194/#4093/#3955/#4182/#3951）。

## 判据（三条同时成立才关；任一不成立 ⇒ 不动）

1. 该报告映射到的 workflow **最近 `--consecutive`（默认 3）次已完成 run 全部 success**；
2. 最新一次 success 的时间**晚于**该 issue 的创建时间（⇒ 它报的那次失败已被取代）；
3. 该 issue 已存在 **> `--min-age-hours`（默认 24）小时**（不抢跑新报告）。

## 纪律

- **默认 dry-run**；`--apply` 才写（先贴证据评论、再关单，理由 `not planned`）。
- **fail-closed**：gh 取不到数 ⇒ **一条都不关**，退出码 `3`（「没跑」必须长得像「没跑」）。
- 触发面**不含 cron**（用户 2026-09-21 裁定）；读数**只由共享发射器**出（workflow 末尾
  `if: always()` 的独立步：`bash .github/scripts/mechanism_liveness.sh emit stale-report-reaper`），
  本脚本只交一行 `MIGAO-REAPER-SUMMARY seen=… acted=… rc=… why=…` 给它。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

GH_ENV = "MIGAO_GH_BIN"
MECH_ID = "stale-report-reaper"
EXIT_OK, EXIT_USAGE, EXIT_ACTED, EXIT_UNKNOWN = 0, 1, 2, 3

#: 标题前缀 → 该报告对应的 workflow（**显式表**：未登记的前缀一律跳过并点名，不静默）
PREFIX_TO_WORKFLOW = {
    "[Post-Deploy]": "post-deploy-eval.yml",
    "[Nightly]": "nightly-verification.yml",
    "[drift]": "drift-audit.yml",
    "[Xiaobu]": "xiaobu-acceptance.yml",
}
#: 人工"钉住"的标签：带了就永不自动关
PIN_LABELS = ("block/need-human", "ai-draft", "hold/auto-fail")


def gh_bin() -> str:
    return os.environ.get(GH_ENV) or "gh"


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"{type(exc).__name__}: {exc}")


def gh_json(args: list[str]) -> list | dict | None:
    """→ 解析后的 JSON；**任何失败都回 None**（= 无法判定，调用方必须与空集分开）。"""
    proc = _run([gh_bin(), *args])
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def workflow_for(title: str) -> str | None:
    for prefix, wf in PREFIX_TO_WORKFLOW.items():
        if title.startswith(prefix):
            return wf
    return None


def judge(issue: dict, runs: list[dict], *,
          now: datetime | None = None, consecutive: int = 3,
          min_age_hours: int = 24) -> tuple[bool, str]:
    """纯函数（可单测）⇒ (是否可关, 读数一行)。三条判据任一不成立 ⇒ (False, 原因)。"""
    now = now or datetime.now(timezone.utc)
    created = _parse(issue.get("createdAt"))
    if created is None:
        return False, "issue 创建时间不可解析 ⇒ 无法判定"
    age = now - created
    if age < timedelta(hours=min_age_hours):
        return False, f"报告太新（{age.total_seconds() / 3600:.1f}h < {min_age_hours}h）⇒ 不抢跑"

    done = [r for r in runs if isinstance(r, dict) and r.get("status") == "completed"]
    if len(done) < consecutive:
        return False, f"已完成 run 只有 {len(done)} 次（< {consecutive}）⇒ 无法判定腿是否转绿"
    window = done[:consecutive]
    reds = [r for r in window if r.get("conclusion") != "success"]
    if reds:
        return False, (f"最近 {consecutive} 次未全绿（{len(reds)} 次非 success："
                       f"{','.join(str(r.get('conclusion')) for r in reds)}）⇒ 腿仍红，不关")
    newest = max((_parse(r.get("createdAt")) for r in window if _parse(r.get("createdAt"))), default=None)
    if newest is None:
        return False, "最近成功 run 的时间不可解析 ⇒ 无法判定"
    if newest <= created:
        return False, (f"最新 success（{newest:%Y-%m-%dT%H:%MZ}）不晚于本报告创建"
                       f"（{created:%Y-%m-%dT%H:%MZ}）⇒ 本次失败未被取代")
    return True, (f"最近 {consecutive} 次已完成 run 全 success，最新 success {newest:%Y-%m-%dT%H:%MZ} "
                  f"晚于报告创建 {created:%Y-%m-%dT%H:%MZ}；报告已存在 {age.total_seconds() / 3600:.1f}h")


def pinned(issue: dict) -> str | None:
    labels = {l.get("name") for l in (issue.get("labels") or []) if isinstance(l, dict)}
    for lb in PIN_LABELS:
        if lb in labels:
            return lb
    return None


def evidence_comment(issue: int, wf: str, why: str) -> str:
    return (f"## ✅ 关闭：这条 CI 报告已被后续的绿取代\n\n"
            f"**判定（机械，可复算）**：`{wf}` 的 {why}\n\n"
            f"复算：`gh run list --workflow {wf} --branch main --limit 5 "
            f"--json status,conclusion,createdAt`；本单由 "
            f"`scripts/stale_report_reaper.py`（issue #5491）关闭，"
            f"若判定有误 `gh issue reopen {issue}` 即可恢复。\n")


def summarise(rc: int, seen: int, acted: int, why: str) -> None:
    """交出一行**机器可读**的计数，供 workflow 声明给共享发射器。

    ⚠️ 本脚本**不自己打** `::notice::MECHANISM-LIVENESS`：本仓的读数只有一个发射器
    （`.github/scripts/mechanism_liveness.sh`），自己再打一份 = **第二个发射器**，
    会被 `tests/unit_ci_workflows/test_mechanism_liveness.py` 的「同一语法两处投影」判据挑出来。
    """
    print("MIGAO-REAPER-SUMMARY "
          f"seen={seen} acted={acted} rc={rc} why={why.replace(chr(10), ' ')[:200]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stale-report-reaper",
                                 description="腿转绿 ⇒ 自动关陈旧 CI 报告（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真关（默认只打印；关闭前会贴证据评论）")
    ap.add_argument("--consecutive", type=int, default=3, help="要求最近 N 次已完成 run 全 success")
    ap.add_argument("--min-age-hours", type=int, default=24, help="报告至少存在多久才允许关")
    ap.add_argument("--only", type=int, action="append", default=None, help="只处理这些 issue 号（调试；可重复）")
    ap.add_argument("--reading-only", action="store_true", help="只输出读数行（给守卫/调试）")
    args = ap.parse_args(argv)

    issues = gh_json(["issue", "list", "--state", "open", "--limit", "500",
                      "--json", "number,title,labels,createdAt"])
    if issues is None:
        print("⏭️  gh 取不到 open issue ⇒ **一条都不关**（exit 3，无法判定 ≠ 空集）", file=sys.stderr)
        summarise(EXIT_UNKNOWN, 0, 0, "gh 不可用/未登录 ⇒ 无法判定")
        return EXIT_UNKNOWN

    targets = [i for i in issues if isinstance(i, dict) and workflow_for(str(i.get("title", "")))]
    if args.only:
        targets = [i for i in targets if int(i.get("number", 0)) in set(args.only)]
    skipped_unmapped = [i for i in issues
                        if isinstance(i, dict) and str(i.get("title", "")).startswith("[")
                        and not workflow_for(str(i.get("title", "")))]

    print(f"── 候选（标题前缀已登记）：{len(targets)} 条；未登记前缀跳过：{len(skipped_unmapped)} 条")
    for i in skipped_unmapped:
        print(f"  ⏭️  #{i.get('number')} 前缀未登记 ⇒ 不自动关：{str(i.get('title'))[:60]}")

    now = datetime.now(timezone.utc)
    unknown, closable, acted, actions = 0, [], 0, []
    runs_cache: dict[str, list[dict] | None] = {}
    for issue in targets:
        n, title = int(issue.get("number", 0)), str(issue.get("title", ""))
        wf = workflow_for(title)
        assert wf is not None
        pin = pinned(issue)
        if pin:
            print(f"  🔒 #{n} 带 `{pin}` ⇒ 钉住，不自动关")
            continue
        if wf not in runs_cache:
            runs_cache[wf] = gh_json(["run", "list", "--workflow", wf, "--branch", "main",
                                      "--limit", "10", "--json", "status,conclusion,createdAt"])
        runs = runs_cache[wf]
        if runs is None:
            unknown += 1
            print(f"  ⚠️  #{n}（{wf}）取不到 run 数据 ⇒ 不关（无法判定）")
            continue
        ok, why = judge(issue, runs, now=now, consecutive=args.consecutive,
                        min_age_hours=args.min_age_hours)
        print(f"  {'✅' if ok else '⏸️ '} #{n}（{wf}）：{why}")
        if not ok:
            continue
        closable.append((n, wf, why))
        if not args.apply:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(evidence_comment(n, wf, why))
            tmp = fh.name
        try:
            posted = _run([gh_bin(), "issue", "comment", str(n), "--body-file", tmp])
            if posted.returncode != 0:
                print(f"    ❌ 证据评论失败 ⇒ 跳过该条（不留无证据的关闭）", file=sys.stderr)
                continue
            closed = _run([gh_bin(), "issue", "close", str(n), "--reason", "not planned"])
            if closed.returncode != 0:
                print(f"    ⚠️  证据已贴但关单失败", file=sys.stderr)
                continue
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        acted += 1
        actions.append(n)
        print(f"    ✅ 已关（证据评论 + not planned）")

    print(f"\n汇总：候选 {len(targets)} / 可关 {len(closable)} / 实关 {acted} / 无法判定 {unknown}"
          + ("" if args.apply else "（dry-run：零写操作；加 --apply 才真关）"))
    if unknown and not closable:
        summarise(EXIT_UNKNOWN, len(targets), acted, f"{unknown} 条取不到 run 数据 ⇒ 无法判定")
        return EXIT_UNKNOWN
    summarise(EXIT_ACTED if acted else EXIT_OK, len(targets), acted,
              f"可关 {len(closable)} 条，实关 {acted} 条" + (f"：{actions}" if actions else ""))
    return EXIT_ACTED if acted else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())