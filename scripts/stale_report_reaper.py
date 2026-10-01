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
import re
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
    #: ⚠️ 这一条是**窗口驱动**的腿（见 READING_REQUIRED_WORKFLOWS）：它的绿可能是"零动作/短路径"的绿
    "[post-merge]": "post-merge-verify.yml",
    #: 🔴 以下三条是 **2026-10-01 补的**（issue #5814 收口复核：它们**会自动开单却从未登记** ⇒ 腿转绿后
    #: 报告**永远挂着**；实测 #5866 —— main 侧生成物新鲜度腿自 05:45Z 起连续 success，而该单仍 open，
    #: 本脚本每轮只打印「前缀未登记」）。登记表是手工维护的，漏登记**不会红** ⇒ 类级元守卫 =
    #: `unregistered_issue_opening_legs()`，判据 = tests/unit_ci_workflows/test_stale_report_reaper.py。
    "[main-freshness]": "main-freshness-guard.yml",
    #: ⚠️ 读数口径与 `[post-merge]` **不同字面量**（`真跑 N 条`）⇒ 同批进了 READING_REQUIRED_WORKFLOWS
    "[red-proof]": "redproof-sweep.yml",
    #: ⚠️ 这条腿的开单载体是 `actions/github-script` 的 `issues.create(`（不是 `gh issue create`）
    "[Fixture]": "fixture-record.yml",
    #: 🔴 **一个根前缀、两条腿**（`[Agent Eval]` 下有冒烟 / 对抗两条）⇒ 必须登记**更具体的子前缀**：
    #: 映射到任一条都可能拿另一条的绿去关单（假关）。前缀匹配是 `startswith` + **表序**，
    #: 故这里逐字取标题里两条腿各自的措辞；`[Agent Eval]` 这个根前缀**故意不登记**
    #: （登记了就会把两条腿一起吞掉）—— 影子前缀由 `shadowed_prefixes()` 守着。
    "[Agent Eval] 米宝冒烟评测失败": "agent-eval.yml",
    "[Agent Eval] 米宝对抗评测失败": "agent-eval-adversarial.yml",
    "[E2E Real]": "e2e-real.yml",
    #: ⚠️ 边界（照实登记）：`[Agent Eval]×2` / `[E2E Real]` / `[Fixture]` 这四条腿的**读数口径未取证**
    #: （2026-10-01 现取：近期连一次 success run 都没有 ⇒ 采不到「跑判据 N」这类样本）
    #: ⇒ **未**纳入 READING_REQUIRED_WORKFLOWS，只按结论判；取证到样本后升格。
    #: 今天是 inert 的（`judge()` 会以「已完成 run < 3」判无法判定），故此刻不构成假关风险。
}

#: 会自动开单、但**有意不回收**的腿：前缀 → (workflow, 理由)。
#: 与 `PREFIX_TO_WORKFLOW` 的分界是**语义**、不是懒得登记：那边的腿，其自身 run 的绿**就是**「它报的那件事
#: 已恢复」的证据；而**看门人型**的腿报的是**别人**不出声 ⇒ 拿它自己的绿自动关单 = 把活故障当陈旧报告关掉。
NON_REAPABLE_PREFIXES: dict[str, tuple[str, str]] = {
    "[liveness]": (
        "mechanism-liveness.yml",
        "看门人型：报的是**别的**机制不再出声 ⇒ 本腿自己的绿**不是**「被报机制已恢复」的证据"
        "（恢复信号来自被报机制自己的心跳读数，由该单的值班流程人判）⇒ 自动关单会把活故障当陈旧报告关掉",
    ),
}

#: 「会自动开单」的**现取**形态（两种载体：shell 的 `gh issue create` / github-script 的 `issues.create(`）。
#: ⚠️ `issues.createComment(` **不算**（只评论不建单）—— 故一律带括号字面量区隔，不用宽泛子串。
ISSUE_OPENING_PATTERNS = ("gh issue create", "issues.create(")
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


#: **只在"窗口驱动"的腿上**要求的更强判据（见 `run_has_readings`）
READING_REQUIRED_WORKFLOWS = frozenset({"post-merge-verify.yml", "redproof-sweep.yml",
                                        "main-freshness-guard.yml"})

#: 允许被**自动关单**的作者（CI / 机器人）。**人写的单永不自动关**，哪怕标题前缀对得上。
BOT_AUTHORS = frozenset({"app/github-actions", "github-actions[bot]"})


def is_bot_authored(issue: dict) -> bool:
    """作者是不是 CI/机器人（2026-09-25 补：**人写的单不得被自动收**）。

    为什么：本脚本只按**标题前缀**认单（`[Post-Deploy] …`）—— 人完全可能写一个同前缀的标题，
    那种单里往往有**人补充的上下文**，被自动关掉就是**丢证据**。⇒ 加一道"作者必须是机器人"。
    """
    login = str(((issue.get("author") or {}) if isinstance(issue.get("author"), dict) else {}).get("login") or "")
    return login in BOT_AUTHORS or login.endswith("[bot]")


def run_has_readings(run_id: int) -> bool | None:
    """该 run 是否**真的判过**（日志里有读数行且「跑判据」> 0）。**取不到 ⇒ None（无法判定）**。

    为什么必须查（2026-09-25 实测两例"假绿"，都会**丢信号**）：
      · **零动作/短路径的绿**：`post-merge-verify` 在「窗口内无变更」时会 2m56s 就 success
        （**一条判据都没跑**）—— 真正的判定 run 是 11 分钟那种；
      · **判据自 skip 的绿**：`test_drift_audit_contract.py` 在 CI 的**浅检出**里自己 skip
        （`origin/main` 不可解析）⇒ 腿"绿"但那条判据**从没跑过**。
    ⇒ 只看 `conclusion == success` 就关单 = 把"**没判**"当成"**判过了**"。
    """
    proc = _run([gh_bin(), "run", "view", str(run_id), "--log"], timeout=180)
    if proc.returncode != 0:
        return None
    hits = re.findall(r"(?:跑判据|真跑)\s*(\d+)", proc.stdout or "")   # 两种腿的读数**字面量不同**
    if hits:
        return any(int(x) > 0 for x in hits)
    # ③ **共享发射器**读数（全仓唯一发射器 `.github/scripts/mechanism_liveness.sh`）：
    #    `::notice::MECHANISM-LIVENESS mech=<id> run=<id> rc=<0|1|3> seen=<n> acted=<n> why=…`
    #    `seen>0` = 本轮**真的看了东西**（如 main-freshness-guard 的 seen=2 = 比对了 2 个产物）；
    #    `seen=0` ⇒ 零动作 ⇒ **不得**当"判过了"。
    seen = re.findall(r"MECHANISM-LIVENESS\b[^\n]*?\bseen=(\d+)", proc.stdout or "")
    if seen:
        return any(int(x) > 0 for x in seen)
    return None                     # 没有任何读数行 ⇒ **不得当"判过"**（fail-closed）


def shadowed_prefixes(table: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """**影子前缀**（未登记即红）：`(被吃掉的更具体前缀, 吃掉它的更短前缀)`。

    为什么（2026-10-01 本单引入）：一个根前缀下**两条腿**时必须登记更具体的子前缀，而匹配是
    `startswith` + **表序** ⇒ 一旦有人把更短的那个登记在**前面**，更具体的条目永远匹配不到
    （静默失效），而**更短的那个会横跨两条腿** ⇒ 拿错腿的绿去关单（假关活故障）。
    """
    items = list((table if table is not None else PREFIX_TO_WORKFLOW).items())
    out: list[tuple[str, str]] = []
    for i, (longer, _) in enumerate(items):
        for shorter, _ in items[:i]:
            if longer != shorter and longer.startswith(shorter):
                out.append((longer, shorter))
    return out


def workflow_for(title: str) -> str | None:
    for prefix, wf in PREFIX_TO_WORKFLOW.items():
        if title.startswith(prefix):
            return wf
    return None


def non_reapable_for(title: str) -> tuple[str, str, str] | None:
    """标题命中「有意不回收」的前缀 ⇒ (前缀, workflow, 理由)；否则 None。"""
    for prefix, (wf, why) in NON_REAPABLE_PREFIXES.items():
        if title.startswith(prefix):
            return prefix, wf, why
    return None


def _without_yaml_comments(text: str) -> str:
    """去掉整行 YAML 注释后再扫。

    ⚠️ 为什么必须去：**注释里提一句 `gh issue create`** 就会被读成开单腿 —— 本仓反复踩过的
    「守卫被自己的文案喂红 / 判据扫到自己」形态（#5832 的两次自伤同族）。
    """
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def issue_opening_workflows(workflows: dict[str, str]) -> set[str]:
    """**现取**：这些 workflow 会自动开单（正文逐字含开单形态，注释不计）。"""
    return {name for name, text in workflows.items()
            if any(p in _without_yaml_comments(text) for p in ISSUE_OPENING_PATTERNS)}


def unregistered_issue_opening_legs(workflows: dict[str, str], *,
                                    reapable: set[str] | None = None,
                                    exempt: set[str] | None = None) -> dict[str, str]:
    """**未登记即红**：会自动开单、却既不在「可回收」表也不在「有意不回收」表的腿 ⇒ `{workflow: 处置}`。

    为什么必须有这一条（2026-10-01 现取，issue #5814 收口复核）：两张表都是**手维护**的，而新腿会
    自动出现 ⇒ 漏登记**不会红**，只会静默退化成「这张单**永远不会被回收**」（实测 #5866 就是这个形态：
    腿连续 success 而单子仍 open，唯一痕迹是运行日志里一行「前缀未登记」）。
    `reapable` / `exempt` 仅供判据做**内存注入**（判别力自证），默认取两张真表。
    """
    known = set(PREFIX_TO_WORKFLOW.values()) if reapable is None else set(reapable)
    known |= ({wf for wf, _ in NON_REAPABLE_PREFIXES.values()} if exempt is None else set(exempt))
    return {wf: "新腿 ⇒ 二选一：加进 PREFIX_TO_WORKFLOW（腿绿即回收），"
                "或加进 NON_REAPABLE_PREFIXES（有意不回收，必须写清理由）"
            for wf in sorted(issue_opening_workflows(workflows) - known)}


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
                      "--json", "number,title,labels,createdAt,author"])
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
        title = str(i.get("title", ""))
        nr = non_reapable_for(title)
        if nr:
            print(f"  🔒 #{i.get('number')} 前缀 `{nr[0]}`（{nr[1]}）**有意不回收**：{nr[2]}")
        else:
            print(f"  ⏭️  #{i.get('number')} 前缀未登记 ⇒ 不自动关：{title[:60]}")

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
        if not is_bot_authored(issue):      # 人写的单永不自动收（2026-09-25）
            print(f"  🙅 #{n} 作者不是 CI/机器人（{(issue.get('author') or {}).get('login')}）"
                  f"⇒ 单里可能有人补充的上下文，**不自动关**")
            continue
        if wf not in runs_cache:
            runs_cache[wf] = gh_json(["run", "list", "--workflow", wf, "--branch", "main",
                                      "--limit", "10", "--json", "status,conclusion,createdAt,databaseId"])
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
        if wf in READING_REQUIRED_WORKFLOWS:
            # ⚠️ 「绿」还必须**真的判过**（零动作 / 自 skip 的绿都不得算，见 `run_has_readings`）
            newest_run = next((r for r in runs if isinstance(r, dict)
                               and r.get("conclusion") == "success" and r.get("databaseId")), None)
            verdict = None if newest_run is None else run_has_readings(int(newest_run["databaseId"]))
            if verdict is not True:
                unknown += 1
                why_no = "取不到 run 记录" if newest_run is None else "日志无读数 / 跑判据 0"
                print(f"  ⚠️  #{n}（{wf}）：run 绿但**取不到「判过」的证据**（{why_no}）"
                      f"⇒ 不关（无法判定 ≠ 判过了）")
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