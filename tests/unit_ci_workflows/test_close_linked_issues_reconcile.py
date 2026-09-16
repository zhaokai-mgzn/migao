# case_ids: MC-012
"""`close-linked-issues` 对账的两个独立静默失效守卫（issue #3700）。

## 背景（2026-09-14 实测，全部为 run 级证据，非推断）

issue 原文只报了**一种**失效（固定 `--limit 50` → 合并高峰期 PR 被挤出窗口）。
本文件另锁**第二种**（与合并事件赛跑）以及其共同后果：**job 依然 success**。

| 失效 | 证据 |
|---|---|
| 窗口截断 | run `34849099546` / `34849723414` / `34849806775` 日志逐字 `📋 候选 PR 数：200`（= `--limit 200` 被顶满）；实测近 48h 已合并 PR **212** 个 → 12 个永远扫不到 |
| 与合并赛跑 | `pull_request_target [closed]` 对 bot 合并**不触发**（#3585）；`push` 对 bot 合并**也不触发**（本 PR 实测：PR #3722/#3723 `merged_by=github-actions[bot]`，squash `41c9a83a` 命中 `deploy-admin-api.yml` 的 `paths: backend/admin-api/**` 却**零 run**；同日**人工**合并 #3596 → push run 05:51:24Z）⇒ 合并后没有任何确定性时机 |
| 静默 | run `34849723414`：`== 完成：扫描 152 个有关键词的 PR，共关闭 0 个 issue ==`，job `success`，无任何告警 |

## 本守卫锁什么

1. **时间窗 + 分页越过窗口**：不再拿"最近 N 条"当窗口；按 `mergedAt` 过滤，且**取到服务端
   返回数 < 请求数**（= 窗口已穷尽）才算取齐；取不齐必须告警。
2. **自愈信号**：该关却没关成（issue 仍 OPEN、关闭失败、状态查询失败、窗口截断、
   补偿关闭延迟超过阈值）→ `::warning::` + step summary，**不得静默 success**。
3. **否定式护栏**（#3559 误关）：「不 `Closes #3559`」不得命中；同时**不得放宽**
   关键词集合（GitHub 官方那一组，逐字锁定）。

## 测试方式

**真跑** workflow 里的 `run:` 文本（不重写判定逻辑）——把它落到临时文件，PATH 前置一个
`gh` 桩（Python）提供完全可控的"已合并 PR / issue 状态 / 关闭失败"世界。判据全部来自
行为（stdout 标记 / step summary / gh 调用记录 / 退出码），不来自实现细节。
红证：每个新判据都配一个「坏世界」夹具或文本变异，证明判据**会红**（见各类 `*_goes_red`）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "close-linked-issues.yml"

# 关键词集合（GitHub 官方支持的那一组）：本测试**逐字锁定**，既防放宽也防收窄
EXPECTED_ALTERNATION = "close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved"
KEYWORD_RE = r"(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)"

STUB = r'''
import json, os, sys

fix = json.loads(open(os.environ["GH_FIXTURE"], encoding="utf-8").read())
log = os.environ.get("GH_CALL_LOG")
argv = sys.argv[1:]
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(" ".join(argv) + "\n")


def esc(s):
    """模仿 jq @tsv 的转义：制表/换行/回车 → \\t \\n \\r"""
    return (s or "").replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def prs_window():
    prs = fix.get("prs", [])
    return sorted(prs, key=lambda p: p.get("mergedAt") or "", reverse=True)


if not argv:
    sys.exit(2)

if argv[0] == "pr" and len(argv) > 1 and argv[1] == "list":
    if fix.get("list_fail"):
        sys.stderr.write("HTTP 403: API rate limit exceeded\n")
        sys.exit(1)
    limit = 30
    want_merged_at = False
    for i, a in enumerate(argv):
        if a in ("--limit", "-L"):
            limit = int(argv[i + 1])
        if a == "--jq" and "mergedAt" in argv[i + 1]:
            want_merged_at = True
    rows = prs_window()
    # list_max 模拟"服务端硬上限"（真实世界 = 搜索 API 1000 / 旧实现的固定 limit）
    cap = fix.get("list_max") or len(rows)
    rows = rows[: min(limit, cap)]
    for p in rows:
        fields = [str(p["number"]), p.get("sha", ""), esc(p.get("body", ""))]
        if want_merged_at:
            fields.append(p.get("mergedAt", ""))
        sys.stdout.write("\t".join(fields) + "\n")
    sys.exit(0)

if argv[0] == "pr" and len(argv) > 1 and argv[1] == "view":
    n = int(argv[2])
    for p in fix.get("prs", []):
        if p["number"] == n:
            fields = [str(p["number"]), p.get("sha", ""), esc(p.get("body", ""))]
            if any("mergedAt" in a for a in argv):
                fields.append(p.get("mergedAt", ""))
            sys.stdout.write("\t".join(fields) + "\n")
            sys.exit(0)
    sys.exit(1)

if argv[0] == "issue" and len(argv) > 1 and argv[1] == "view":
    n = str(int(argv[2]))
    if n in [str(x) for x in fix.get("issue_view_fail", [])]:
        sys.stderr.write("HTTP 403: rate limit\n")
        sys.exit(1)
    state = fix.get("issue_states", {}).get(n)
    if state is None:
        sys.stderr.write("not found\n")
        sys.exit(1)
    print(state)
    sys.exit(0)

if argv[0] == "issue" and len(argv) > 1 and argv[1] == "close":
    n = int(argv[2])
    if n in [int(x) for x in fix.get("close_fail", [])]:
        sys.stderr.write("HTTP 403: Resource not accessible by integration\n")
        sys.exit(1)
    sys.exit(0)

sys.stderr.write("stub gh: unhandled argv: %r\n" % (argv,))
sys.exit(2)
'''


def _load():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}


def _job(d):
    return (d.get("jobs") or {})["close-linked-issues"]


def _steps(d):
    return _job(d).get("steps") or []


def _run_text(d) -> str:
    """被测的 run: 文本（脚本本体，不含 workflow 表达式——表达式只在 env: 里）。"""
    return "\n".join(s.get("run") or "" for s in _steps(d))


class World:
    """一次可复现的对账世界：stub gh 桩 + 被测 run 文本 + 结果。"""

    def __init__(self, tmp_path, prs, issue_states=None, *, close_fail=(),
                 issue_view_fail=(), list_max=None, list_fail=False, env=None,
                 run_text=None):
        self.tmp = Path(tmp_path)
        self.bin = self.tmp / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        gh = self.bin / "gh"
        gh.write_text("#!/usr/bin/env python3\n" + STUB, encoding="utf-8")
        gh.chmod(0o755)

        fixture = {
            "prs": prs,
            "issue_states": issue_states or {},
            "close_fail": list(close_fail),
            "issue_view_fail": list(issue_view_fail),
        }
        if list_max is not None:
            fixture["list_max"] = list_max
        if list_fail:
            fixture["list_fail"] = True
        self.fixture_path = self.tmp / "fixture.json"
        self.fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

        self.call_log = self.tmp / "gh-calls.log"
        self.summary = self.tmp / "summary.md"
        self.run_file = self.tmp / "run.sh"
        self.run_file.write_text(run_text if run_text is not None else _run_text(_load()),
                                 encoding="utf-8")
        self.extra_env = dict(env or {})

    def run(self, *, event="pull_request_target", action="opened", **overrides):
        env = dict(os.environ)
        env.update({
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "GH_FIXTURE": str(self.fixture_path),
            "GH_CALL_LOG": str(self.call_log),
            "GH_TOKEN": "stub",
            "GH_REPO": "zhaokai-mgzn/migao",
            "EVENT_NAME": event,
            "EVENT_ACTION": action,
            "DISPATCH_PR": "",
            "EVENT_PR": "",
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "PAGE_LIMIT": "100",
            "MAX_LIMIT": "1000",
            "RECONCILE_HOURS": "48",
            "LATE_MINUTES": "15",
        })
        env.update(self.extra_env)
        env.update({k: str(v) for k, v in overrides.items()})
        self.proc = subprocess.run(["bash", str(self.run_file)], capture_output=True,
                                   text=True, env=env, timeout=120)
        return self

    @property
    def out(self):
        return self.proc.stdout + self.proc.stderr

    @property
    def calls(self):
        return self.call_log.read_text(encoding="utf-8").splitlines() if self.call_log.exists() else []

    def closed(self):
        return sorted(int(re.search(r"issue close (\d+)", c).group(1))
                      for c in self.calls if re.search(r"issue close (\d+)", c))

    def list_limits(self):
        return [int(re.search(r"--limit (\d+)", c).group(1))
                for c in self.calls if "pr list" in c]

    def summary_text(self):
        return self.summary.read_text(encoding="utf-8") if self.summary.exists() else ""


def _iso(hours_ago: float) -> str:
    """窗口内/外的 mergedAt（相对"现在"，格式与脚本的 cutoff 一致）。"""
    import datetime
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pr(n, body, hours_ago=1.0, sha=None):
    return {"number": n, "sha": sha or ("%08x" % n) * 5, "body": body,
            "mergedAt": _iso(hours_ago)}


class TestWindowAndPagination:
    """① 时间窗 + 分页越过窗口（issue #3700 失效 1：固定条数 = 静默漏扫）。"""

    def test_pagination_walks_past_the_requested_page(self, tmp_path):
        """25 个窗口内 PR、每页 10 ⇒ 必须**继续取**（10→20→40）直到取齐，
        最老的 PR 也要被扫到。旧实现（固定 limit）在这里必丢 15 个。"""
        prs = [_pr(2000 - i, f"Closes #{1000 - i}") for i in range(25)]
        states = {str(1000 - i): "OPEN" for i in range(25)}
        w = World(tmp_path, prs, states,
                  env={"PAGE_LIMIT": "10"}, run_text=_run_text(_load())).run()
        assert "候选 PR 数：25" in w.out, (
            f"未取齐 25 个窗口内 PR（分页没越过第一页）：\n{w.out}"
        )
        assert w.list_limits() == [10, 20, 40], (
            f"分页请求序列应为 10→20→40（返回数<请求数即取齐），实为 {w.list_limits()}"
        )
        assert 976 in w.closed(), (   # 最老 = PR #1976 → Closes #976
            f"最老的窗口内 PR 未被扫到 —— 正是 #3700 的静默漏扫：\n{w.out}"
        )

    def test_fixed_limit_goes_red_instead_of_silent(self, tmp_path):
        """红证：把可取上限压到 10（= 旧实现"固定条数"的等价形态）⇒
        **必须告警**「窗口被截断」，而不是像今天那样静默 success。"""
        prs = [_pr(2000 - i, f"Closes #{1000 - i}") for i in range(25)]
        states = {str(1000 - i): "OPEN" for i in range(25)}
        w = World(tmp_path, prs, states,
                  env={"PAGE_LIMIT": "10", "MAX_LIMIT": "10"},
                  run_text=_run_text(_load())).run()
        assert "::warning::" in w.out and "截断" in w.out, (
            f"窗口取不齐却没有告警 → 静默 success（#3700 原始症状复发）：\n{w.out}"
        )
        assert "截断=true" in w.summary_text(), (
            "step summary 未自证「本轮窗口可能不完整」"
        )
        # 且必须**明说漏了**：最老的那个确实没扫到（这是告警要解释的现象）
        assert 976 not in w.closed()

    def test_out_of_window_pr_is_skipped(self, tmp_path):
        """时间窗按 `mergedAt` 生效：窗口外（60h 前合并）的 PR 不得被处理。"""
        prs = [_pr(3111, "Closes #2222", hours_ago=60.0)]
        w = World(tmp_path, prs, {"2222": "OPEN"}).run()
        assert 2222 not in w.closed(), (
            f"窗口外（>48h）的 PR 被处理 —— 时间窗没生效：\n{w.out}"
        )
        assert "窗口内 PR 数：0" in w.out, (
            f"未把窗口外 PR 排除在候选之外：\n{w.out}"
        )

    def test_in_window_pr_is_processed(self, tmp_path):
        """窗口内（1h 前合并）的 PR 必须被处理（防"时间窗"把该做的活也挡掉）。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "OPEN"}).run()
        assert w.closed() == [3714], f"窗口内 PR 未被处理：\n{w.out}"


class TestSelfHealAlarm:
    """② 自愈信号（issue #3700 要求 3：别静默 success）。"""

    def test_found_but_closed_zero_warns(self, tmp_path):
        """发现带关键词的已合并 PR、其 issue 仍 OPEN，却一个都没关成 ⇒ `::warning::`。

        这正是 run 34849723414 的形态（扫描 152 个有关键词的 PR，关闭 0 个，
        job success、零告警）。"""
        prs = [_pr(3722, "Closes #3714\nCloses #3721", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "OPEN", "3721": "OPEN"},
                  close_fail=[3714, 3721]).run()
        assert w.proc.returncode != 0, (
            "关闭失败（该关却没关成）却以 0 退出 —— 与 #3585『run 成功但一个 issue 都关不掉』同形"
        )
        assert "::warning::" in w.out, f"该关却没关成，却没有告警：\n{w.out}"
        assert "已关闭：0" in w.summary_text() and "关闭失败：2" in w.summary_text(), (
            f"step summary 未把「需关闭/已关闭/关闭失败」写清楚：\n{w.summary_text()}"
        )

    def test_close_failure_is_loud_not_silent(self, tmp_path):
        """单条关闭失败也要响（③ 的窄形态），并给出 #3585 排查首项（issues: write）。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "OPEN"}, close_fail=[3714]).run()
        assert "::warning::" in w.out and "issues: write" in w.out, (
            f"关闭失败未提示权限排查项（#3585 首项）：\n{w.out}"
        )

    def test_issue_state_lookup_failure_warns(self, tmp_path):
        """issue 状态查询失败（gh 限流/静默失败）必须告警 —— 否则就是"看起来对账过"。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "OPEN"}, issue_view_fail=[3714]).run()
        assert "::warning::" in w.out and "状态" in w.out, (
            f"状态查询失败被当成『无需处理』静默跳过：\n{w.out}"
        )
        assert 3714 not in w.closed()

    def test_late_close_warns_about_trigger_gap(self, tmp_path):
        """补偿关闭发生在合并后远超阈值 ⇒ 告警（合并后触发链路有缺口 = #3700 失效 2）。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=6.0)]
        w = World(tmp_path, prs, {"3714": "OPEN"}, env={"LATE_MINUTES": "15"}).run()
        assert w.closed() == [3714], f"该关的 issue 没关：\n{w.out}"
        assert "::warning::" in w.out and "延迟" in w.out, (
            f"合并 6h 后才补偿关闭，却没有任何「链路有缺口」的信号：\n{w.out}"
        )
        assert "延迟关闭（>15min）：1" in w.summary_text(), (
            f"summary 未记录延迟关闭数：\n{w.summary_text()}"
        )

    def test_fast_close_is_quiet(self, tmp_path):
        """反向：及时关闭（1 分钟前合并）不得刷告警 —— 否则告警变噪音。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1 / 60)]
        w = World(tmp_path, prs, {"3714": "OPEN"}, env={"LATE_MINUTES": "15"}).run()
        assert w.closed() == [3714]
        assert "::warning::" not in w.out, f"及时关闭却刷告警（噪音）：\n{w.out}"

    def test_steady_state_no_keyword_prs_is_quiet(self, tmp_path):
        """稳态（窗口内 PR 全无 closing 关键词）不得刷告警。

        实证：run 34849723414 扫 152 个有关键词的 PR、关闭 0 个 —— 这是**常态**
        （引用过的 issue 早已关闭）。故告警判据带上「其中仍有 OPEN 的 issue」这一
        限定，否则会变成永久噪音（告警疲劳 = 真失败与噪音同形）。"""
        prs = [_pr(3722, "常规修复，未引用任何 issue", hours_ago=1.0),
               _pr(3723, "Closes #9999", hours_ago=1.0)]
        w = World(tmp_path, prs, {"9999": "CLOSED"}).run()
        assert w.proc.returncode == 0
        assert "::warning::" not in w.out, (
            f"稳态（引用过的 issue 早已关闭）刷了告警 → 永久噪音：\n{w.out}"
        )
        assert "已关闭：0" in w.summary_text(), "summary 仍应如实记录 0 关闭"


class TestNegationGuard:
    """③ 否定式护栏（#3559 误关）——只收窄，不放宽。"""

    def test_negated_keyword_is_not_closed(self, tmp_path):
        """「不 `Closes #3559`」不得被当成 closing 声明（#3559 曾因此被秒关）。"""
        prs = [_pr(3685, "本 PR 不改 #3559 的行为：不 Closes #3559（保持 OPEN）", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3559": "OPEN"}).run()
        assert 3559 not in w.closed(), (
            f"否定式命中 → 误关 live issue（#3559 复发）：\n{w.out}"
        )

    def test_english_negation_is_not_closed(self, tmp_path):
        """英文否定式同样不得命中（`does not close #12`）。"""
        prs = [_pr(4001, "This PR does not close #12 (still open).", hours_ago=1.0)]
        w = World(tmp_path, prs, {"12": "OPEN"}).run()
        assert 12 not in w.closed(), f"英文否定式命中 → 误关：\n{w.out}"

    def test_positive_still_matches(self, tmp_path):
        """护栏不得把正常声明一起收窄（防"修好即恒不命中"）。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "OPEN"}).run()
        assert w.closed() == [3714], f"正常 Closes 声明未被处理：\n{w.out}"

    def test_mixed_line_only_positive_target_is_closed(self, tmp_path):
        """同一行既有否定又有肯定 ⇒ 只关肯定的那个（否定护栏不得吃掉合法目标）。"""
        prs = [_pr(4002, "不 Closes #1；但 Closes #2（本次修复）", hours_ago=1.0)]
        w = World(tmp_path, prs, {"1": "OPEN", "2": "OPEN"}).run()
        assert w.closed() == [2], (
            f"混合行处理错误（应只关 #2，否定护栏不得跨句吃掉 #2）：\n{w.out}"
        )

    def test_negation_guard_goes_red_without_it(self, tmp_path):
        """红证：把否定护栏去掉（文本变异）⇒ 同一条 PR body 立刻误关 #3559。

        变异必须真的改到文本，否则本测试是空断言（前置条件不满足直接 fail）。"""
        run = _run_text(_load())
        mutated = run.replace("(不|勿|无需|不必|not|never|without)", "(NEVER_MATCHES_ANYTHING)")
        if mutated == run:
            pytest.fail("变异未命中否定护栏（判据锚点漂移）—— 红证不成立，需同步本测试")
        assert "NEVER_MATCHES_ANYTHING" in mutated
        prs = [_pr(3685, "不 Closes #3559（保持 OPEN）", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3559": "OPEN"}, run_text=mutated).run()
        assert 3559 in w.closed(), (
            "去掉否定护栏后仍未误关 —— 说明该夹具根本触发不到护栏，红证无效"
        )


class TestRegexSemanticsLocked:
    """关键词集合逐字锁定：既不放宽也不收窄（GitHub 官方那一组）。"""

    def test_keyword_set_unchanged(self):
        """逐字锁定官方那一组（用**字面量**比对，不用 findall——交替项的左优先会让
        findall 只回 'close'/'fix'/'resolve'，是假绿写法）。"""
        run = _run_text(_load())
        literal = f"({EXPECTED_ALTERNATION})"
        assert literal in run, (
            f"关键词正则未逐字保持官方那一组：期望字面量 {literal!r} 未出现在脚本里\n"
            f"（放宽会误关、收窄会漏关，两者都是回归）"
        )
        # 反向：正则里不得出现通配/额外关键词（如 `\w*clos\w*` 这类放宽写法）
        m = re.search(r"'\(([a-z|]+)\)\[\[:space:\]\]\*#\[0-9\]\+'", run)
        if m is None:
            pytest.fail("找不到关键词提取正则（判据锚点漂移）—— 无法证明它没被放宽")
        assert m.group(1) == EXPECTED_ALTERNATION, (
            f"关键词提取正则的交替项被改动：{m.group(1)!r}"
        )

    def test_prose_number_without_keyword_is_not_closed(self, tmp_path):
        """正文里出现 issue 号但没有关键词 ⇒ 不得关闭（#3541 形态：散文引用 ≠ 声明）。"""
        prs = [_pr(3554, "关联 #3549，另见 #3541 的讨论（未声明关闭）", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3549": "OPEN", "3541": "OPEN"}).run()
        assert w.closed() == [], f"无关键词却被关闭：{w.closed()}"


class TestTriggerChain:
    """触发链：确定性合并后触发 + 既有可靠路径 + 不依赖 cron（#3700 要求 1/4）。"""

    def test_push_to_main_is_a_trigger(self):
        """必须有 `push` → main：与合并同一因果链（人工合并/直推的确定性时机）。"""
        d = _load()
        triggers = d.get("on") or d.get(True) or {}
        push = triggers.get("push") or {}
        branches = push.get("branches") or []
        assert "main" in branches, (
            f"缺 push→main 触发（现为 {push!r}）—— 合并后只剩「下一个 PR opened」或 cron，"
            "而 cron 被节流至 2~5.5h（#3585/#3700）"
        )

    def test_push_event_admitted_by_job_gate(self):
        """job `if` 必须放行 push 事件，否则触发器加了也不干活（静默失效）。"""
        cond = _job(_load()).get("if") or ""
        assert "github.event_name == 'push'" in cond, (
            f"job if 未放行 push（if={cond!r}）→ 新触发器形同虚设"
        )

    def test_keeps_pull_request_opened_reliable_path(self):
        """保留 #3585 的可靠路径（opened/reopened 是 bot 合并后唯一可靠的对账时机）。"""
        d = _load()
        triggers = d.get("on") or d.get(True) or {}
        types = set((triggers.get("pull_request_target") or {}).get("types") or [])
        assert types & {"opened", "reopened"}, (
            f"pull_request_target.types={sorted(types)} 丢了 opened/reopened → #3585 复发"
        )

    def test_keeps_schedule_as_last_resort(self):
        d = _load()
        triggers = d.get("on") or d.get(True) or {}
        assert (triggers.get("schedule") or []), "丢了 schedule 定时兜底（最终保证，别只依赖它、也别删它）"

    def test_issues_write_permission_untouched(self):
        """#3585 排查首项：少 `issues: write` = run 成功但一个 issue 都关不掉。勿删。"""
        assert (_load().get("permissions") or {}).get("issues") == "write"


class TestIdempotenceAndSinglePrMode:
    """幂等 + 单 PR 补偿模式的静默失效补齐（#3700 同族）。"""

    def test_idempotent_when_issues_already_closed(self, tmp_path):
        """幂等：再次对账时 issue 已 CLOSED ⇒ no-op，不重复关闭、不刷告警。"""
        prs = [_pr(3722, "Closes #3714", hours_ago=1.0)]
        w = World(tmp_path, prs, {"3714": "CLOSED"}).run()
        assert w.closed() == [], f"已关闭的 issue 被重复关闭（非幂等）：{w.closed()}"
        assert w.proc.returncode == 0, f"稳态不该非零退出：\n{w.out}"
        assert "::warning::" not in w.out, f"稳态刷告警（噪音）：\n{w.out}"

    def test_single_pr_mode_requires_merged(self, tmp_path):
        """单 PR 补偿（dispatch 点名）也只对**已合并** PR 关闭 issue（防假关闭）。"""
        prs = [{"number": 999, "sha": "", "body": "Closes #123", "mergedAt": ""}]
        w = World(tmp_path, prs, {"123": "OPEN"}).run(
            event="workflow_dispatch", action="", DISPATCH_PR="999")
        assert w.closed() == [], f"拿未合并 PR 的 Closes 去关 issue（假关闭）：{w.closed()}"
        assert "未合并" in w.out, f"未说明为何跳过：\n{w.out}"

    def test_single_pr_lookup_failure_is_loud(self, tmp_path):
        """单 PR 模式查不到 PR（号码错/限流）⇒ 必须红，不得静默 success。

        旧写法是 `gh pr view … || true` → 0 行 → 「无待处理 PR，退出」→ **绿**，而人显式
        要求的补偿根本没做（与 #3709「绿的空跑」同族）。"""
        prs = [{"number": 1, "sha": "", "body": "", "mergedAt": _iso(1)}]
        w = World(tmp_path, prs, {}).run(
            event="workflow_dispatch", action="", DISPATCH_PR="424242")
        assert w.proc.returncode != 0, f"查不到 PR 却 success（静默空跑）：\n{w.out}"
        assert "::error::" in w.out, f"未以 ::error:: 显式报出：\n{w.out}"

    def test_reconcile_list_failure_is_loud(self, tmp_path):
        """对账模式 gh pr list 失败（限流/权限）⇒ 必须红，不得当成"窗口内无 PR"。

        旧写法的形态是 `gh pr list … 2>/dev/null || true` → 0 行 → 「无待处理 PR，退出」
        → **静默 success**（#3585 同族：gh 静默失败 = 不关）。"""
        prs = [{"number": 3722, "sha": "abc", "body": "Closes #3714", "mergedAt": _iso(1)}]
        w = World(tmp_path, prs, {"3714": "OPEN"}, list_fail=True,
                  run_text=_run_text(_load())).run()
        assert w.proc.returncode != 0, f"gh pr list 失败却 success（静默不关）：\n{w.out}"
        assert "::error::" in w.out, f"未以 ::error:: 显式报出：\n{w.out}"
        assert 3714 not in w.closed()
