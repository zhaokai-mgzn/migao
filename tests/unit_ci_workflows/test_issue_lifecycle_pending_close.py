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
    log = tmp_path / "gh.log"
    env = {
        **os.environ,
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