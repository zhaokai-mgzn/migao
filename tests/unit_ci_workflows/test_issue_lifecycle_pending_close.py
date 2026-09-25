# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` MC-012「CI workflow 结构由 pytest 单测验证」。本 PR 不新建用例族。）
"""`issue-lifecycle.sh pending-close` / `close` —— 「已交付却悬挂」的发现面 + 「无证据不关单」的执行面。

## 这守的是什么（issue #5480 漏洞 2）

PR 做**部分交付**时按 §23 G9 **有意不写**关闭词 ⇒ issue 悬挂，而**没有任何东西会变红**。
2026-09-25 实测代价：靠人工逐条对账才发现 **37 条**「已交付 / 已被取代却仍 open」，
外加 8 个核验员逐条内容级取证 —— 这些成本本该由一条**发现面**省掉。
而同一天 37 次关单又全靠手写 `gh issue comment` + `gh issue close`（顺序、理由、证据格式都得记）。

⇒ 两条命令：`pending-close`（**只发现、零写**）与 `close`（**无 `--evidence` 即拒**，默认 dry-run）。

## 红证（每条都能单独变红，缺一条就是空判据）

| 注入 | 会红在哪 |
|---|---|
| 去掉 `cmd_close` 里的 `if missing: ... return EXIT_USAGE`（放行无证据关单） | `test_close_without_evidence_is_fail_closed` |
| 调换 `post-评论` / `close` 两步的顺序 | `test_close_apply_comments_before_closing` |
| 去掉 `pending_close_rows` 里的 `& open_nums`（把已关的也算进来） | `test_pending_close_lists_only_still_open_refs` |
| 把 dry-run 分支删掉（默认就真写） | `test_dry_run_writes_nothing` |
| 去掉 `cmd_close` 里的「未实装登记追踪单 ⇒ 拒关」分支（issue #5506） | `test_close_refuses_when_issue_is_an_unimplemented_tracking_issue` |
| 把登记册不可解析时的 fail-closed 改成放行 | `test_close_fails_closed_when_registry_unreadable` |
| 把 `--ack-unimplemented-registry` 的旁路删掉 | `test_close_ack_flag_allows_it` |

`gh` 一律用**替身可执行文件**注入（`MIGAO_GH_BIN`，与 `test_issue_lifecycle_finish.py` 同款）：
只换 CLI 边界，不 mock 被测函数；命令走**真 argparse + 真 dispatch**（subprocess 跑真 CLI）。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "issue_lifecycle.py"

STUB = """#!/usr/bin/env bash
# 替身 gh：记 argv + 按子命令吐罐头 JSON（写类命令一律 exit 0，不做任何真事）
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr list")    cat "$GH_PRS" ;;
  "issue list") cat "$GH_ISSUES" ;;
esac
exit 0
"""


def _fixture(tmp_path: Path, prs: list[dict] | None = None, issues: list[dict] | None = None,
             pr_list_rc: int = 0):
    """→ (env, gh 调用日志路径)。"""
    stub = tmp_path / "gh"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "prs.json").write_text(json.dumps(prs or []), encoding="utf-8")
    (tmp_path / "issues.json").write_text(json.dumps(issues or []), encoding="utf-8")
    # 守卫里有一处**字面量** `"gh"`（`agent-presets-guard._pr_merged_branches`，不走 MIGAO_GH_BIN）
    # ⇒ 再把替身放上 PATH 首位，两边都拦得住（仍只换 CLI 边界，不 mock 被测函数）。
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(STUB, encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    log = tmp_path / "gh.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "MIGAO_GH_BIN": str(stub),
        "GH_LOG": str(log),
        "GH_PRS": str(tmp_path / "prs.json"),
        "GH_ISSUES": str(tmp_path / "issues.json"),
    }
    if pr_list_rc:
        # 让 `pr list` 失败：用不可读的罐头文件路径 ⇒ cat 非零 ⇒ 该方法回 None
        env["GH_PRS"] = str(tmp_path / "does-not-exist.json")
    return env, log


def _run(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)


def _calls(log: Path) -> list[str]:
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] if log.exists() else []


# ── pending-close：只发现，零写 ───────────────────────────────────────────────

def test_pending_close_lists_only_still_open_refs(tmp_path):
    """引用了但没写关闭词、**且仍 open** 的才进清单（已关的 / 写了关闭词的都不进）。

    ⚠️ 夹具里**必须**有一个「被引用但已 CLOSED」的 issue（#102），否则「与 open 集合相交」
    这一步删掉也不会红（本用例的红证实测过一次：第一版夹具缺它 ⇒ 注入不红）。
    """
    prs = [
        {"number": 900, "body": "关联 #101\n关联 #102\nCloses #103", "mergedAt": "2026-09-24T01:00:00Z"},
        {"number": 901, "body": "Closes #101", "mergedAt": "2026-09-24T02:00:00Z"},
        {"number": 902, "body": "没有引用", "mergedAt": "2026-09-24T03:00:00Z"},
    ]
    # open = {101, 103}；#102 曾被引用但**已 CLOSED** ⇒ 不该进清单
    env, log = _fixture(tmp_path, prs=prs, issues=[{"number": 101}, {"number": 103}])
    out = _run(tmp_path, env, "pending-close")
    assert out.returncode == 0, out.stderr
    assert "PR #900" in out.stdout and "#101" in out.stdout, out.stdout
    assert "#102" not in out.stdout, f"已 CLOSED 的引用不该进清单：{out.stdout}"
    assert "PR #901" not in out.stdout, "写了关闭词的不该进清单"
    assert "PR #902" not in out.stdout, "没有引用的不该进清单"
    writes = [c for c in _calls(log) if c.startswith("issue comment") or c.startswith("issue close")]
    assert not writes, f"pending-close 必须零写操作，实测：{writes}"


def test_pending_close_unknown_when_gh_fails(tmp_path):
    """取不到数 ⇒ exit 3（**不得当 0 读**：空集与取不到必须分开）。"""
    env, _ = _fixture(tmp_path, prs=[], issues=[], pr_list_rc=1)
    out = _run(tmp_path, env, "pending-close")
    assert out.returncode == 3, (out.returncode, out.stdout, out.stderr)
    assert "不得当 0 读" in out.stderr, out.stderr


def test_pending_close_since_days_filters_old_prs(tmp_path):
    """`--since-days` 按合并日过滤（旧 PR 不进清单，避免清单长到没人看）。"""
    prs = [
        {"number": 910, "body": "关联 #101", "mergedAt": "2020-01-01T00:00:00Z"},
    ]
    env, _ = _fixture(tmp_path, prs=prs, issues=[{"number": 101}])
    assert "PR #910" in _run(tmp_path, env, "pending-close").stdout
    out = _run(tmp_path, env, "pending-close", "--since-days", "7")
    assert "PR #910" not in out.stdout, out.stdout


# ── close：无证据不关单 ───────────────────────────────────────────────────────

def test_close_without_evidence_is_fail_closed(tmp_path):
    """缺 `--evidence` ⇒ 拒绝执行，且**一条 gh 都不发**（不留无证据的关闭）。"""
    env, log = _fixture(tmp_path)
    out = _run(tmp_path, env, "close", "42")
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "无证据不关单" in out.stderr, out.stderr
    assert not _calls(log), f"fail-closed 时不该有任何 gh 调用：{_calls(log)}"


def test_dry_run_writes_nothing(tmp_path):
    """默认 dry-run：打印计划、零写操作（破坏性命令一律默认只读）。"""
    env, log = _fixture(tmp_path)
    out = _run(tmp_path, env, "close", "42", "--evidence", "PR #1 merged；git grep X ⇒ 命中")
    assert out.returncode == 0, out.stderr
    assert "[dry] #42" in out.stdout, out.stdout
    assert not _calls(log), f"dry-run 不该有任何 gh 调用：{_calls(log)}"


def test_close_apply_comments_before_closing(tmp_path):
    """`--apply`：**先贴证据评论、再关单**（顺序错 = 可能出现无证据的关闭）。"""
    env, log = _fixture(tmp_path)
    out = _run(tmp_path, env, "close", "42", "--reason", "superseded",
               "--evidence", "取代者 #7 CLOSED；git grep X ⇒ 命中", "--apply")
    assert out.returncode == 0, (out.stdout, out.stderr)
    calls = _calls(log)
    assert calls, "应至少发两条 gh 命令"
    comment_at = next(i for i, c in enumerate(calls) if c.startswith("issue comment 42"))
    close_at = next(i for i, c in enumerate(calls) if c.startswith("issue close 42"))
    assert comment_at < close_at, f"必须先评论后关单，实测顺序：{calls}"
    assert "--reason not planned" in calls[close_at], calls[close_at]


def test_close_delivered_maps_to_completed(tmp_path):
    """`delivered` ⇒ `--reason completed`（判定与关闭理由不许混）。"""
    env, log = _fixture(tmp_path)
    _run(tmp_path, env, "close", "43", "--reason", "delivered", "--evidence", "PR #2 merged", "--apply")
    close_calls = [c for c in _calls(log) if c.startswith("issue close 43")]
    assert close_calls and "--reason completed" in close_calls[0], close_calls


def test_close_batch_file_tsv(tmp_path):
    """批量 TSV：每行 `<issue>\\t<reason>\\t<证据>`；列数不对 ⇒ 拒绝执行。"""
    env, _ = _fixture(tmp_path)
    good = tmp_path / "verdicts.tsv"
    good.write_text("101\tdelivered\tPR #1 merged\n# 注释行\n\n102\tsuperseded\t取代者 #9 CLOSED\n",
                    encoding="utf-8")
    out = _run(tmp_path, env, "close", "--batch-file", str(good))
    assert out.returncode == 0, out.stderr
    assert "[dry] #101" in out.stdout and "[dry] #102" in out.stdout, out.stdout

    bad = tmp_path / "bad.tsv"
    bad.write_text("101|delivered|证据\n", encoding="utf-8")
    out2 = _run(tmp_path, env, "close", "--batch-file", str(bad))
    assert out2.returncode == 1, (out2.returncode, out2.stdout)
    assert "三列" in out2.stderr, out2.stderr


def test_close_batch_file_requires_evidence_every_row(tmp_path):
    """批量里**任一行**缺证据 ⇒ 整批拒绝（不让「凑数」的行混过去）。"""
    env, log = _fixture(tmp_path)
    f = tmp_path / "v.tsv"
    f.write_text("101\tdelivered\tPR #1 merged\n102\tdelivered\t\n", encoding="utf-8")
    out = _run(tmp_path, env, "close", "--batch-file", str(f), "--apply")
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert not _calls(log), f"整批拒绝 ⇒ 零写操作，实测：{_calls(log)}"

# ── 漏洞 1：临时（点号）worktree 的堆积必须**出声**（只报不删）────────────────────

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"})


def _repo_with_dot_worktrees(tmp_path: Path, count: int):
    """真 git 仓库 + `count` 个**真**点号 worktree（不是 mock：判据本体就是 git 语义）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    base = tmp_path / "migao-wt"
    base.mkdir()
    paths = []
    for i in range(count):
        p = base / f".tmp-verify-{i}"
        _git(repo, "worktree", "add", "--detach", "-q", str(p))
        paths.append(p)
    # ⚠️ 罐头里**必须**有 ≥1 条已合并 PR：`all_merged_branches` 对**空结果**判「无法判定」
    #    （exit 3）——那是刻意的 fail-closed 口径，不是本用例要测的东西。
    env, log = _fixture(tmp_path, prs=[{"number": 1, "state": "MERGED",
                                        "headRefName": "some-merged-branch", "baseRefName": "main"}],
                         issues=[])
    env["MIGAO_WT_BASE"] = str(base)
    return repo, paths, env, log


def test_dot_worktree_pileup_warns_and_deletes_nothing(tmp_path):
    """> 阈值 ⇒ `::warning::` + 逐条路径；且**零删除**（无人值守删除不安全，用户裁定）。"""
    repo, paths, env, _ = _repo_with_dot_worktrees(tmp_path, 4)
    out = _run(repo, env, "prune")
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert "::warning::" in out.stderr, f"堆积 4 个应出声：{out.stderr}"
    assert "4 个" in out.stderr, out.stderr
    for p in paths:
        assert str(p) in out.stderr, f"应逐条列出 {p}：{out.stderr}"
    assert all(p.is_dir() for p in paths), "只报不删：点号 worktree 必须还在"


def test_dot_worktree_below_threshold_is_silent(tmp_path):
    """≤ 阈值 ⇒ 不出声（避免噪音把真信号淹掉）。"""
    repo, paths, env, _ = _repo_with_dot_worktrees(tmp_path, 1)
    out = _run(repo, env, "prune")
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert "::warning::" not in out.stderr, f"1 个不该出声：{out.stderr}"
    assert paths[0].is_dir()


# ── close：**未实装登记的追踪单必须拒关**（issue #5506） ──────────────────────
#
# 实测代价（2026-09-25）：#3822 / #3483 按其自身判据交付关闭，却仍留在
# `.github/case-trust-unimplemented.json` 的「未实装」登记里 ⇒ 门禁规则
# `CASE-TRUST-UNIMPL-ISSUE-CLOSED` 在**下一个 PR** 上判红 ⇒ **全队列 6 条 PR 同时 BLOCKED**
# （而它们的 diff 与登记册毫无关系）。本组判据把这一步拦在**关单那一刻**。


def _registry(tmp_path: Path, entries: list[dict]) -> None:
    d = tmp_path / ".github"
    d.mkdir(exist_ok=True)
    (d / "case-trust-unimplemented.json").write_text(
        json.dumps({"_comment": "夹具", "unimplemented": entries}, ensure_ascii=False), encoding="utf-8")


def test_close_refuses_when_issue_is_an_unimplemented_tracking_issue(tmp_path):
    """追踪单仍被登记为「未实装」⇒ **拒关**（且**零写**：连证据评论都不许贴）。"""
    env, log = _fixture(tmp_path)
    _registry(tmp_path, [{"code": "CASE-TRUST-CROSS-LEG-NARROW-RUN", "issue": 3822,
                          "expires": "2027-01-31"}])
    out = _run(tmp_path, env, "close", "3822", "--reason", "delivered",
               "--evidence", "PR #5487 merged 2026-09-25T02:08Z（夹具）")
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert "CASE-TRUST-UNIMPL-ISSUE-CLOSED" in out.stderr, out.stderr
    assert "#3822" in out.stderr and "撤登记" in out.stderr, out.stderr
    assert _calls(log) == [], f"拒关时不得写任何东西，实测调用：{_calls(log)}"


def test_close_refuses_before_apply_too(tmp_path):
    """`--apply` 也拦得住（否则就是"打印计划拒、真关放行"的假守卫）。"""
    env, log = _fixture(tmp_path)
    _registry(tmp_path, [{"code": "CASE-TRUST-X", "issue": 3822, "expires": "2027-01-31"}])
    out = _run(tmp_path, env, "close", "3822", "--reason", "delivered",
               "--evidence", "夹具", "--apply")
    assert out.returncode == 1, (out.returncode, out.stdout, out.stderr)
    assert _calls(log) == [], f"--apply 时也不得写：{_calls(log)}"


def test_close_ack_flag_allows_it(tmp_path):
    """显式承担（如登记已在同批修复 PR 里同步）⇒ 放行。"""
    env, _ = _fixture(tmp_path)
    _registry(tmp_path, [{"code": "CASE-TRUST-X", "issue": 3822, "expires": "2027-01-31"}])
    out = _run(tmp_path, env, "close", "3822", "--reason", "delivered",
               "--evidence", "夹具", "--ack-unimplemented-registry")
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "[dry] #3822" in out.stdout, out.stdout


def test_close_unrelated_issue_is_allowed(tmp_path):
    """登记册里没有的 issue ⇒ 正常走（守卫不得把正常关单也拦了）。"""
    env, _ = _fixture(tmp_path)
    _registry(tmp_path, [{"code": "CASE-TRUST-X", "issue": 3822, "expires": "2027-01-31"}])
    out = _run(tmp_path, env, "close", "9999", "--reason", "delivered", "--evidence", "夹具")
    assert out.returncode == 0 and "[dry] #9999" in out.stdout, (out.returncode, out.stdout, out.stderr)


def test_close_fails_closed_when_registry_unreadable(tmp_path):
    """登记册在但**解析不了** ⇒ 拒关（fail-closed：宁可不关，也不误关）。"""
    env, log = _fixture(tmp_path)
    d = tmp_path / ".github"; d.mkdir(exist_ok=True)
    (d / "case-trust-unimplemented.json").write_text("{ 这不是 JSON", encoding="utf-8")
    out = _run(tmp_path, env, "close", "9999", "--reason", "delivered", "--evidence", "夹具")
    assert out.returncode == 1 and "fail-closed" in out.stderr, (out.returncode, out.stderr)
    assert _calls(log) == []


def test_close_without_registry_file_warns_but_proceeds(tmp_path):
    """**没有**该文件（不在仓库根跑）⇒ 出声但放行（不是本仓结构 ⇒ 不拦）。"""
    env, _ = _fixture(tmp_path)
    out = _run(tmp_path, env, "close", "9999", "--reason", "delivered", "--evidence", "夹具")
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "跳过" in out.stderr and "未实装登记" in out.stderr, out.stderr


# ── 会话内零新开：机械判据（2026-09-25 用户裁定，铁律 11(a) / §24.0）─────────────

def _load_il():
    """从 `scripts/issue_lifecycle.py` 加载被测模块（零依赖，importlib 文件加载）。

    本文件既有判据走 CLI 子进程；这两条是**纯函数**判据，直接加载模块更快也更准。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "issue_lifecycle_under_test", Path(__file__).resolve().parents[2] / "scripts" / "issue_lifecycle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_human_request_marker_is_the_only_exemption():
    """带 `人为要求：` 标记的单**不算违规**；没标记的**逐条列出**（政策：会话内零新开）。"""
    rows = [
        {"number": 1, "title": "人为要求开的", "createdAt": "2026-09-25T01:00:00Z",
         "body": "人为要求：用户在对话里说「顺手开一张跟踪单」"},
        {"number": 2, "title": "会话自己开的", "createdAt": "2026-09-25T02:00:00Z",
         "body": "## 现象\n…"},
        {"number": 3, "title": "标记在下文也算", "createdAt": "2026-09-25T03:00:00Z",
         "body": "## 背景\n\n人为要求：用户原话见会话 2026-09-25"},
    ]
    bad = _load_il().non_human_requested(rows)
    assert [n for n, _c, _t in bad] == [2], f"应只报 #2，实得 {bad}"


def test_new_issues_check_is_fail_closed_when_gh_is_unavailable(tmp_path, monkeypatch):
    """`--check-new-issues` 取不到 issue 列表 ⇒ **无法判定（rc=3）**，不得当 0 读。"""
    import argparse
    monkeypatch.chdir(tmp_path)
    mod = _load_il()
    monkeypatch.setattr(mod, "_gh_json", lambda *a, **k: None)   # 契约：失败回 None
    rc = mod.cmd_check_new_issues(argparse.Namespace(since="2026-09-25", limit=100))
    assert rc == 3, f"取不到数据必须 rc=3（实得 {rc}）"


def test_workflow_runs_the_new_issues_check():
    """main 侧腿必须真的跑这条判据（否则政策只有文档、没有机械面）。"""
    import yaml
    from pathlib import Path

    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "post-merge-verify.yml"
    text = wf.read_text(encoding="utf-8")
    assert "check-new-issues" in text, "main 侧腿没有接线 `check-new-issues` ⇒ 零新开政策无人核验"
    steps = yaml.safe_load(text)["jobs"]["verify"]["steps"]
    hit = [s for s in steps if "check-new-issues" in str(s.get("run") or "")]
    assert len(hit) == 1, f"「零新开核验」步必须恰好一个（实得 {len(hit)}）"
    run = str(hit[0]["run"])
    assert "exit ${RC}" in run or "exit $RC" in run, "该步必须把退出码带出去（有违规 ⇒ 腿红）"


def test_new_issues_policy_is_not_retroactive():
    """**规则不追溯**：政策生效前创建的单**豁免**，生效后新建且无标记的才算违规。

    为什么必须有这条（实测）：政策生效当天，main 侧腿立刻因**当天早些时候**创建的 28 条存量
    判定为「有违规」而红 —— 即"让机制上线"本身制造了一条**天天红**的腿（本仓明确要避免的形态）。
    ⇒ 口径：规则只在**生效之后**适用；历史存量按生效前豁免（读数里分列，不静默丢）。

    红证形态：去掉 `created < effective` 的豁免分支 ⇒ 本判据立刻红。
    """
    mod = _load_il()
    eff = mod.NEW_ISSUES_POLICY_EFFECTIVE
    before = {"number": 1, "title": "政策前建的", "createdAt": "2026-09-25T01:00:00Z", "body": "## 现象"}
    after = {"number": 2, "title": "政策后建的", "createdAt": "2026-09-25T13:00:00Z", "body": "## 现象"}
    human = {"number": 3, "title": "人为要求", "createdAt": "2026-09-25T13:00:00Z",
             "body": "人为要求：用户在对话里让开的"}
    bad = mod.violates_new_issues_policy([before, after, human], eff)
    assert [n for n, _c, _t in bad] == [2], f"应只报政策生效后且无标记的 #2，实得 {bad}"
    assert eff == "2026-09-25T12:01:24Z", "生效时刻是政策 PR 的合并时间；改了它等于改了追溯边界，需同步说明"
