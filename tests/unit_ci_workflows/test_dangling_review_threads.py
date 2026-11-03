# case_ids: MC-143
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC 号。
#   MC-143 = issue #6997「未解决评审线程 ⇒ 必须计入需要处置」的三分类判据。）
r"""悬空 PR 扫描的**评审线程面**（`scripts/dangling_pr_scan.py`）—— issue #6997 的 L0 守卫。

## 病（现场逐字，issue #6997）

PR **#6987**：27 pass / 0 fail、16 条 required **全部 SUCCESS**、`autoMergeRequest` **已 arm**，
而 `mergeStateStatus` 长期 `BLOCKED`、**永不合并**。手动合被拒：

> `X Pull request #6987 is not mergeable: the base branch policy prohibits the merge.`

真因 = 分支保护的 `required_conversation_resolution = true` + 一条**未解决**的 review thread
（`isOutdated = true` —— 密钥早已在后续提交里改掉，但**没人 resolve 它**）。而
`gh pr checks` / `statusCheckRollup` **完全不含**这一项 ⇒ 「不红、不通知、就是不合」。
本仓扫描器此前只把这一族当**提示文本**打印（`dangling_reason` 里的一句「未解决的评审线程，
后者见 `scripts/resolve_stale_bot_threads.py`」）⇒ **不计入「需要处置」**，于是「全绿却卡住」无声。

## 本文件锁什么（每条都能单独被注入式变异打红）

| # | 形态 | 判据 | 红证 / 负例 |
|---|---|---|---|
| 1 | 1 条 `isResolved=false ∧ isOutdated=false` 的线程（有人留了意见、代码没改过） | **必红**（退出码 1 + `::error::` + `path` + **首行摘要** + 分类计数） | 夹具 A；变异（摘掉线程判定）⇒ 不再红 |
| 2 | **只有** `isOutdated=true` 的未解决线程（代码已改过） | **不计入**（单独一类、**不算阻塞**，只出声） | 夹具 B（负控，否则每个被密钥扫描命中过的 PR 会永远红） |
| 3 | 全部 `isResolved=true` | **不计入** | 夹具 C（负控） |
| 4 | 线程面 API 返回错误 / 限流 | **无法判定 = 退出码 3**（**不得当 0 读**） | 夹具 D（stub 注入失败） |
| 5 | 分类与计数（fresh / outdated / resolved 混在一起） | 三栏读数**各自正确** | 夹具 E |
| 6 | 范围闸：draft / `block/merge` / 年龄 < `--minutes` | **不查线程面**（不发这次 API 调用 ⇒ 不刷假红） | 夹具 F（同时注入 API 失败 ⇒ 仍绿，证明真的没调） |

⚠️ **判据形态**：读的是**真脚本的行为**（子进程 + `gh` 替身，CLI 边界即注入点），
不 mock 被测逻辑、不联网。`gh` 替身走 `DANGLING_GH_BIN`（沿用 `MG_GH_BIN` / `SBT_GH_BIN` 先例）。
⚠️ **引用纪律**：本文件只给仓库相对全路径，**不写行号**（`Case Trust Gate` 规则 G 会判红裸文件名 + 冒号 + 行号）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dangling_pr_scan.py"


def _load_scan():
    spec = importlib.util.spec_from_file_location("dangling_pr_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SCAN = _load_scan()

GREEN_CHECK = {"__typename": "CheckRun", "name": "QA Growth Gate",
               "status": "COMPLETED", "conclusion": "SUCCESS"}

#: 真实线程形状（取自 issue #6997 的 GraphQL 读数：`path` / `isResolved` / `isOutdated` / 首条评论）
THREAD_FRESH = {
    "id": "PRRT_fresh",
    "isResolved": False,
    "isOutdated": False,
    "path": "backend/admin-api/src/test/java/com/migao/admin/service/StockLedgerTest.java",
    "comments": {"nodes": [{"author": {"login": "reviewer-a"},
                            "bodyText": "这里没有校验幂等键\n\n其余部分没问题，先改这一段。"}]},
}
THREAD_OUTDATED = {
    "id": "PRRT_outdated",
    "isResolved": False,
    "isOutdated": True,
    "path": "backend/admin-api/src/test/java/com/migao/admin/service/MerchantShipmentIdempotencyRealDbTest.java",
    "comments": {"nodes": [{"author": {"login": "github-actions"},
                            "bodyText": "🛑 Gitleaks has detected a secret with rule-id "
                                        "`generic-api-key` in commit a1377d92d"}]},
}
THREAD_RESOLVED = {
    "id": "PRRT_resolved",
    "isResolved": True,
    "isOutdated": False,
    "path": "scripts/dangling_pr_scan.py",
    "comments": {"nodes": [{"author": {"login": "reviewer-b"},
                            "bodyText": "文档里的判据清单需要补一行"}]},
}


def pr(number=6987, *, age_min=180, draft=False, state="CLEAN", labels=(), rollup=(GREEN_CHECK,),
       armed=True, sha="b" * 40, title="fix(ci): 幂等键校验", now=None, mergeable="MERGEABLE"):
    """PR 夹具 —— 形状取自 `gh pr list --json …` 的真读数（**全绿 + 已 arm** 的 #6987 现场）。

    ⚠️ 时间锚取**调用时的真实钟**（CLI 侧用 `datetime.now()` 算年龄；固定常量会让年龄漂）。
    """
    now = now or datetime.now(timezone.utc)
    return {"number": number, "title": title, "isDraft": draft,
            "createdAt": (now - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mergeStateStatus": state, "mergeable": mergeable,
            "labels": [{"name": n} for n in labels],
            "autoMergeRequest": ({"mergeMethod": "SQUASH"} if armed else None),
            "headRefOid": sha, "statusCheckRollup": list(rollup)}


GH_STUB = '''#!/usr/bin/env python3
"""`gh` 替身（夹具驱动）。`gh` CLI 边界即注入点（沿用 MG_GH_BIN / SBT_GH_BIN 先例）。"""
import json, os, sys

args = sys.argv[1:]
if args[:2] == ["pr", "list"]:
    if os.environ.get("STUB_PR_LIST_FAIL") == "1":
        sys.stderr.write("stub: pr list failed (injected)\\n")
        sys.exit(1)
    sys.stdout.write(open(os.environ["STUB_PRS"], encoding="utf-8").read())
    sys.exit(0)
if args[:2] == ["run", "list"]:
    sha = args[args.index("--commit") + 1]
    runs = json.load(open(os.environ["STUB_RUNS"], encoding="utf-8"))
    sys.stdout.write(json.dumps(runs.get(sha, [])))
    sys.exit(0)
if args[:2] == ["api", "graphql"]:
    # issue #6997：评审线程面。`STUB_THREADS_FAIL=1` = 注入 API 错误 / 限流。
    if os.environ.get("STUB_THREADS_FAIL") == "1":
        sys.stderr.write("stub: HTTP 403: API rate limit exceeded (injected)\\n")
        sys.exit(1)
    number = ""
    for index, arg in enumerate(args):
        if arg in ("-F", "--field") and index + 1 < len(args) \\
                and args[index + 1].startswith("number="):
            number = args[index + 1].split("=", 1)[1]
    threads = {}
    if os.environ.get("STUB_THREADS"):
        threads = json.load(open(os.environ["STUB_THREADS"], encoding="utf-8"))
    nodes = threads.get(number, [])
    sys.stdout.write(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "totalCount": len(nodes), "nodes": nodes}}}}}))
    sys.exit(0)
sys.stderr.write("stub: unhandled argv=%r\\n" % (args,))
sys.exit(9)
'''


class Out:
    """一次扫描的可观测结果（退出码 / 输出 / step summary）。"""

    def __init__(self, proc, summary):
        self.proc = proc
        self.summary = summary

    @property
    def rc(self):
        return self.proc.returncode

    @property
    def out(self):
        return self.proc.stdout + self.proc.stderr

    def has_error(self):
        return "\n::error::" in ("\n" + self.out)

    def has_warning(self):
        return "\n::warning::" in ("\n" + self.out)


def run_scan(tmp_path, prs, threads=None, *, runs=None, minutes=60, fail_threads=False,
             script=None):
    """跑一次真脚本。`threads` = `{PR 号: [GraphQL thread node, …]}`（缺省 = 没有线程）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "gh"
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    (tmp_path / "prs.json").write_text(json.dumps(prs), encoding="utf-8")
    (tmp_path / "runs.json").write_text(json.dumps(runs or {}), encoding="utf-8")
    (tmp_path / "threads.json").write_text(json.dumps(threads or {}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "STUB_"))}
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env.get("PATH", ""),
        "DANGLING_GH_BIN": str(stub),
        "STUB_PRS": str(tmp_path / "prs.json"),
        "STUB_RUNS": str(tmp_path / "runs.json"),
        "STUB_THREADS": str(tmp_path / "threads.json"),
        "GITHUB_STEP_SUMMARY": str(summary),
    })
    if fail_threads:
        env["STUB_THREADS_FAIL"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script or SCRIPT), "--repo", "o/r", "--minutes", str(minutes)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return Out(proc, summary.read_text(encoding="utf-8") if summary.exists() else "")


def mutate_script(tmp_path, old, new):
    """对**真脚本源码**做单点变异（锚点漂移即本判据自身失败）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert old in src, f"变异锚点不存在（脚本已漂移）：{old!r}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    mutated = tmp_path / "mutated_scan.py"
    mutated.write_text(src.replace(old, new, 1), encoding="utf-8")
    return mutated


# ══════════════════════════════════════════════════════════════════════════════
# 一、判据本体：未解决 ∧ 未过期 ⇒ 计入「需要处置」（必红）
# ══════════════════════════════════════════════════════════════════════════════

def test_unresolved_fresh_thread_counts_as_needs_disposition(tmp_path):
    """🔴 红证（**判据本体**，issue #6997）：1 条未解决且未过期的线程 ⇒ 该 PR 被计入「需要处置」。

    形状逐字取自 #6987 的**后半**（全绿 + 已 arm 却卡住），线程面换成「有人留了意见、代码没改过」。
    """
    out = run_scan(tmp_path, [pr()], {6987: [THREAD_FRESH]})
    assert out.rc == 1, (
        f"「全绿却挂着未解决评审线程」没有被计入需要处置（原缺陷）：rc={out.rc}\n{out.out}")
    assert out.has_error(), f"必须打 ::error::（可见信号）：\n{out.out}"
    assert "需要处置" in out.out, f"读数必须自述这是「需要处置」这一族：\n{out.out}"
    # `path` + **首行摘要**（不是整段 body、不是"看起来有问题"）
    assert THREAD_FRESH["path"] in out.out, f"必须报出 thread 的 path：\n{out.out}"
    assert "这里没有校验幂等键" in out.out, f"必须报出 thread 的**首行摘要**：\n{out.out}"
    assert "其余部分没问题" not in out.out, (
        f"只许报首行摘要（后面几行不该进读数，否则 summary 会被整段 body 撑爆）：\n{out.out}")
    assert "reviewer-a" in out.out, f"必须报出线程作者（可归因）：\n{out.out}"
    # **具体分类与计数**
    assert "未解决且未过期 1 条" in out.out, f"必须给出分类与计数：\n{out.out}"
    assert "1 条（需要处置）" in out.out, out.out
    assert "需要处置的评审线程 1 个 PR" in out.summary, f"summary 必须落笔：{out.summary!r}"
    assert THREAD_FRESH["path"] in out.summary, f"summary 必须点名 path：{out.summary!r}"


def test_dangling_pr_reading_names_the_thread(tmp_path):
    """issue #6997 的**要求 2**：命中悬空面的 PR 也必须报出线程面（`path` + 首行摘要）。

    形状 = #6987 的真形态（`BLOCKED` + required 全绿 + 已 arm）：**旧判据本来就会判「悬空」**，
    但只给一句泛泛的提示（「未解决的评审线程，见 `resolve_stale_bot_threads.py`」）⇒ 报了警却
    说不清为什么。现在读数里必须出现 thread 的 `path` 与首行摘要。
    """
    out = run_scan(
        tmp_path, [pr(number=6987, state="BLOCKED")], {6987: [THREAD_FRESH]},
        runs={"b" * 40: [{"status": "completed", "conclusion": "success",
                          "workflowName": "PR Check", "event": "pull_request"}]})
    assert out.rc == 1, out.out
    assert "悬空 PR" in out.out, out.out
    assert THREAD_FRESH["path"] in out.out and "这里没有校验幂等键" in out.out, (
        f"悬空的 PR 也必须报出线程面（否则「报了警说不清为什么」）：\n{out.out}")


# ══════════════════════════════════════════════════════════════════════════════
# 二、负控：outdated / 已解决 ⇒ **不计入**（否则会永远红）
# ══════════════════════════════════════════════════════════════════════════════

def test_outdated_thread_is_a_separate_class_not_blocking(tmp_path):
    """**负控（一）**：只有 `isOutdated = true` 的未解决线程 ⇒ **不红**，但必须出声（单独一类）。

    #6987 的真因就是这一族（`outdated ≠ resolved`）：它**仍会**把 PR 钉在 `BLOCKED`，
    但把它当阻塞会让每个被 Gitleaks / 评审工具命中过的 PR **永久判红** ⇒ 本判据统计它、
    出声给处置入口，**不**计入「需要处置」。
    """
    out = run_scan(tmp_path, [pr()], {6987: [THREAD_OUTDATED]})
    assert out.rc == 0, f"已过期线程不得判红（否则会永远红）：rc={out.rc}\n{out.out}"
    assert not out.has_error(), f"已过期线程不得打 ::error::：\n{out.out}"
    assert "已过期" in out.out and "不算阻塞" in out.out, (
        f"必须作为**单独一类**出声（可见 ≠ 阻塞）：\n{out.out}")
    assert THREAD_OUTDATED["path"] in out.out, f"已过期那一类也要点名 path（可处置）：\n{out.out}"
    assert "需要处置的评审线程 0 个 PR" in out.summary, f"summary 的计数必须为 0：{out.summary!r}"
    assert "已过期 **1** 条" in out.summary, f"summary 必须分类计数：{out.summary!r}"


def test_all_resolved_threads_are_not_counted(tmp_path):
    """**负控（二）**：全部 `isResolved = true` ⇒ 完全不计入（只进计数读数）。"""
    out = run_scan(tmp_path, [pr()], {6987: [THREAD_RESOLVED, dict(
        THREAD_RESOLVED, id="PRRT_resolved_2")]})
    assert out.rc == 0, f"已解决线程不得判红：rc={out.rc}\n{out.out}"
    assert not out.has_error(), out.out
    assert "需要处置" not in out.out, f"已解决的不许出现在「需要处置」面：\n{out.out}"
    assert "已解决 **2** 条" in out.summary, f"summary 必须分类计数：{out.summary!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 三、三态：读不到线程面 ⇒ **无法判定 = 3**（不得当 0 读）
# ══════════════════════════════════════════════════════════════════════════════

def test_thread_api_failure_is_exit_3_not_zero(tmp_path):
    """🔴 API 错误 / 限流 ⇒ 退出码 **3**，且**不许**顺手打一句「✅ 无悬空项」。

    「没跑成」必须长得像「没跑成」（与 `scripts/merge_gate.py` 同口径的三态）。
    """
    out = run_scan(tmp_path, [pr()], fail_threads=True)
    assert out.rc == 3, (
        f"线程面读不到却报 0 = 把「没跑成」装成「没问题」：rc={out.rc}\n{out.out}")
    assert out.has_error(), f"必须打 ::error::（可见信号）：\n{out.out}"
    assert "无法判定" in out.out, f"读数必须自述「无法判定」：\n{out.out}"
    assert "不得当 0" in out.out or "不得当通过" in out.out, out.out
    assert "✅" not in out.out, (
        f"读不到线程面时**不许**再说「无悬空项」（那会把未判定读成通过）：\n{out.out}")
    assert "评审线程面未判定" in out.summary, f"summary 必须分栏写未判定：{out.summary!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 四、分类与范围（计数正确性 + 不查的那一族）
# ══════════════════════════════════════════════════════════════════════════════

def test_mixed_threads_are_classified_into_three_readings(tmp_path):
    """三分类**各自计数**：1 条需要处置 / 1 条已过期 / 1 条已解决 ⇒ 三栏读数互不串味。"""
    out = run_scan(tmp_path, [pr()],
                   {6987: [THREAD_FRESH, THREAD_OUTDATED, THREAD_RESOLVED]})
    assert out.rc == 1, f"混有未解决且未过期的线程 ⇒ 必须判红：rc={out.rc}\n{out.out}"
    assert "未解决且未过期 1 条" in out.out and "已过期 1 条" in out.out, (
        f"分类计数必须互不串味（1/1）：\n{out.out}")
    assert "已解决" in out.out, out.out
    for token in ("已解决 **1** 条", "已过期 **1** 条", "未解决且未过期 **1** 条"):
        assert token in out.summary, f"summary 缺少分类计数 {token!r}：{out.summary!r}"


def test_thread_face_is_not_queried_for_out_of_scope_prs(tmp_path):
    """**范围闸**：draft / `block/merge` / 年龄 < `--minutes` ⇒ **不查**线程面（也不发那次 API 调用）。

    判据用「**同时注入 API 失败**」实现：若它真的去查了，退出码必然变 `3`；
    仍在 `0` ⇒ 证明这一族**根本没发**这次调用（异步窗口内留意见是正常工作，报它才是假红）。
    """
    cases = {
        "draft": pr(number=6987, draft=True),
        "block/merge 人工闸": pr(number=6988, labels=("block/merge",)),
        "仅 open 5 分钟（< 阈值）": pr(number=6989, age_min=5),
    }
    for index, (label, fixture) in enumerate(cases.items()):
        out = run_scan(tmp_path / str(index), [fixture], {fixture["number"]: [THREAD_FRESH]},
                       fail_threads=True)
        assert out.rc == 0, (
            f"「{label}」不该进线程面，却去查了（注入的 API 失败把它变成 rc={out.rc}）：\n{out.out}")
        assert not out.has_error(), f"「{label}」不得判红：\n{out.out}"


# ══════════════════════════════════════════════════════════════════════════════
# 五、红证：把 reviewThreads 判定摘掉 ⇒ 判据本体（夹具 A）必红
# ══════════════════════════════════════════════════════════════════════════════

def test_removing_thread_judgement_turns_the_primary_case_red(tmp_path):
    """🔴 **注入式红证**：摘掉线程判定（`if classified["needs_disposition"]:` → `if False:`）
    ⇒ 夹具 A **不再判红**、且 `path` 从读数里消失（证明判据本体真的被这条闸解释）。

    没有这条闸，扫描器就退回到 issue #6997 的原形态：**全绿 + 已 arm 却卡住 ⇒ 无声**。
    """
    out = run_scan(tmp_path, [pr()], {6987: [THREAD_FRESH]})
    assert out.rc == 1 and THREAD_FRESH["path"] in out.out, (
        f"先决条件不成立（未变异的真脚本必须红）：\n{out.out}")
    mutated = mutate_script(tmp_path / "mutant",
                            'if classified["needs_disposition"]:',
                            "if False:  # mutated: 摘掉 reviewThreads 判定")
    out2 = run_scan(tmp_path / "mutant" / "run", [pr()], {6987: [THREAD_FRESH]},
                    script=mutated)
    assert out2.rc == 0, (
        f"摘掉 reviewThreads 判定后**仍然判红** ⇒ 该闸没在挡东西：rc={out2.rc}\n{out2.out}")
    assert not out2.has_error(), out2.out
    assert THREAD_FRESH["path"] not in out2.out, (
        f"摘掉判定后仍报出 path ⇒ 判据本体没被这条闸解释：\n{out2.out}")
