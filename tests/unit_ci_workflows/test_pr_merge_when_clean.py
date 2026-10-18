# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
"""`scripts/pr-merge-when-clean.sh` —— 「PR 已绿、只等 main 不动」这条竞速的**单一命令**（issue #7206）。

## 这守的是什么（实测读数，不是推测）

main 的 `strict = true`（合并必须与 main 同版本）+ main 高频前进 ⇒ 落地变成竞速：

    PR 检查全绿 → mergeStateStatus = BEHIND → 合不了
    ⇒ 手工 update-branch → CI 重跑 ~8-10 min → 期间 main 又动 ⇒ 再 BEHIND

实测：2026-10-17 夜 4 条 PR 各撞 1~3 轮，单条最多 7 轮。铁律 10（一晚同一串动作 ≥3 次 ⇒ 收敛成一条命令）
就是本单的立项依据；`land` 覆盖不到这类「PR 已绿、没有 worktree」的场合，且它的 `wait-merge` 是**单发读**
（读到 OPEN 即停，设计正确 —— 不猜合并），把 BEHIND 的重试留给了人。

## 判据分组（每组都能**单独**变红）

① **BEHIND ⇒ 先 update-branch，再等，绝不直接 merge**（顺序即安全顺序：带着 BEHIND 调 merge 必然被拒，
   而「update 之后立刻 merge」会跳过新一轮 checks ⇒ 等于绕过门禁）。
   红证 = 把脚本里 `BEHIND` 分支的 `update_branch` 调用摘掉 ⇒ 本组必红（停在 BEHIND 直到轮次耗尽 ⇒ exit 3）。
② **required 红 ⇒ 立刻 1，且一次 merge / update 都不许发**（不许「带着红 update 白跑一轮 CI」，更不许合并）。
③ **update-branch 冲突（422）⇒ 立刻 1**，且**不**退化成「本地硬 rebase」（冲突要人看，偷换掉就是假绿）。
④ **读不到状态 ⇒ 3**（无法判定 ≠ 0）：`gh` 不可用 / `pr view` 报错。
⑤ **CLEAN 且无 pending ⇒ merge，观察到 MERGED ⇒ 0**。
⑥ `--dry-run` ⇒ **零动作**（不 update、不 merge），只打印将做什么。

替身口径：假 `gh` 按 `$STUB_VIEWS` 里的 JSON 队列逐次回放 `pr view` 读数，并把每次 argv **按序**写进
`$STUB_CALL_LOG` —— 判据读的是**实跑调用序**，不是源码文本。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr-merge-when-clean.sh"

PR = "7188"


# ── 替身 gh ─────────────────────────────────────────────────────────────────────

_GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log = os.environ["STUB_CALL_LOG"]
state_path = os.environ["STUB_STATE"]
with open(log, "a", encoding="utf-8") as f:
    f.write("gh " + " ".join(args) + "\n")
state = json.load(open(state_path, encoding="utf-8"))

def save():
    json.dump(state, open(state_path, "w", encoding="utf-8"))

def _project(row):
    """按脚本用的那套 `--jq` 投影：STATE|MERGE_STATE|FAILED|PENDING|HEAD（与真 gh 行为一致）。"""
    rollup = row.get("statusCheckRollup") or []
    failed = ",".join(c.get("name", "") for c in rollup
                      if (c.get("conclusion") or "") not in ("SUCCESS", "SKIPPED", "NEUTRAL", "CANCELLED", ""))
    pending = sum(1 for c in rollup if (c.get("status") or "") != "COMPLETED")
    return "|".join([row.get("state", ""), row.get("mergeStateStatus") or "UNKNOWN",
                     failed, str(pending), row.get("headRefOid") or ""])

if args[:2] == ["pr", "view"]:
    views = state["views"]
    if not views:
        print("stub: 没有更多 pr view 读数（用例没准备够）", file=sys.stderr); sys.exit(9)
    row = views.pop(0)
    save()
    # 真 gh 在带 --jq/-q 时输出**投影后的文本**，不带时输出 JSON。两者都要被覆盖，
    # 否则「脚本用了 --jq 而替身只会打印 JSON」会让用例在错的地方红（实测踩过）。
    if "-q" in args or "--jq" in args:
        print(_project(row))
    else:
        print(json.dumps(row))
    sys.exit(0)

if "graphql" in args:
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}))
    sys.exit(0)

if args[:1] == ["api"]:
    if state.get("api_should_fail"):
        print('{"message":"merge conflict between base and head"}', file=sys.stderr)
        sys.exit(1)
    state["api_called"] = True
    save()
    print('{"message":"Updating pull request branch."}')
    sys.exit(0)

if args[:2] == ["pr", "merge"]:
    if state.get("merge_should_fail"):
        print("X Pull request is not mergeable", file=sys.stderr)
        sys.exit(1)
    state["merged"] = True
    save()
    print("merged")
    sys.exit(0)

print("stub: 未预期的 gh 调用：" + " ".join(args), file=sys.stderr)
sys.exit(9)
'''


def _view(state="OPEN", merge_state="CLEAN", failures=(), pending=0, head="a" * 40):
    rollup = [{"name": n, "status": "COMPLETED", "conclusion": "FAILURE"} for n in failures]
    rollup += [{"name": f"ok-{i}", "status": "COMPLETED", "conclusion": "SUCCESS"} for i in range(2)]
    rollup += [{"name": f"run-{i}", "status": "IN_PROGRESS", "conclusion": None} for i in range(pending)]
    return {"state": state, "mergeStateStatus": merge_state, "headRefOid": head,
            "statusCheckRollup": rollup}


@pytest.fixture()
def run_script(tmp_path: Path):
    """在**隔离** PATH 里跑脚本：假 gh 只影响被测脚本，不动真环境。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(textwrap.dedent(_GH_STUB), encoding="utf-8")
    gh.chmod(0o755)
    # git rev-parse 得能跑（脚本用 `--show-toplevel`，失败也有兜底，不强制）
    if shutil.which("git") is None:  # pragma: no cover - 环境缺 git 时判据无意义
        pytest.skip("环境没有 git，无法跑本判据")

    def _run(views, *, args=(), api_should_fail=False, merge_should_fail=False, expect_rc=None):
        state_path = tmp_path / "state.json"
        log_path = tmp_path / "calls.log"
        state_path.write_text(json.dumps({
            "views": views,
            "api_should_fail": api_should_fail,
            "merge_should_fail": merge_should_fail,
            "api_called": False,
            "merged": False,
        }), encoding="utf-8")
        log_path.write_text("", encoding="utf-8")
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["STUB_STATE"] = str(state_path)
        env["STUB_CALL_LOG"] = str(log_path)
        env["PMWC_POLL_SECONDS"] = "0"
        env["PMWC_WAIT_TIMEOUT"] = os.environ.get("PMWC_WAIT_TIMEOUT", "30")
        proc = subprocess.run(["bash", str(SCRIPT), PR, *args], env=env, cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=120)
        calls = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if expect_rc is not None:
            assert proc.returncode == expect_rc, (
                f"退出码应在 {expect_rc}，实测 {proc.returncode}\n--- stdout ---\n{proc.stdout}"
                f"\n--- stderr ---\n{proc.stderr}\n--- gh 调用 ---\n" + "\n".join(calls))
        return proc, calls

    return _run


# ── 判据 ①：BEHIND ⇒ update 先于 merge ──────────────────────────────────────────

def test_behind_updates_branch_before_merging(run_script):
    proc, calls = run_script(
        [_view(merge_state="BEHIND"), _view(merge_state="CLEAN"), _view(state="MERGED", merge_state="CLEAN")],
        expect_rc=0)
    assert any("update-branch" in c for c in calls), f"必须调用 update-branch（gh 调用：{calls}）"
    upd = next(i for i, c in enumerate(calls) if "update-branch" in c)
    merged = next((i for i, c in enumerate(calls) if c.startswith(f"gh pr merge {PR}")), None)
    assert merged is not None, "CLEAN 之后必须真的调 merge"
    assert upd < merged, "顺序错：update-branch 必须发生在 merge 之前（否则带着 BEHIND 调 merge 必被拒）"
    assert "已合并" in proc.stdout


def test_behind_never_merges_in_the_same_round(run_script):
    """BEHIND 那一轮**不许**顺手 merge（否则跳过了新一轮 checks）。"""
    _, calls = run_script(
        [_view(merge_state="BEHIND"), _view(merge_state="BEHIND"), _view(state="MERGED", merge_state="CLEAN")],
        expect_rc=0)
    first_update = next(i for i, c in enumerate(calls) if "update-branch" in c)
    merges = [i for i, c in enumerate(calls) if c.startswith(f"gh pr merge {PR}")]
    assert all(i > first_update for i in merges), "update 之前的轮次不得出现 merge"


# ── 判据 ②：required 红 ⇒ 立刻 1 且零动作 ───────────────────────────────────────

def test_required_failure_stops_immediately_without_actions(run_script):
    proc, calls = run_script([_view(merge_state="BLOCKED", failures=("admin-api unit tests",))], expect_rc=1)
    assert not any("update-branch" in c for c in calls), "红的时候不许 update（白跑一轮 CI）"
    assert not any(c.startswith(f"gh pr merge {PR}") for c in calls), "红的时候绝不许 merge"
    assert "admin-api unit tests" in proc.stdout, "必须**具名**打印哪条判据红了（可归因）"


# ── 判据 ③：update 冲突 ⇒ 1，且不退化成本地硬 rebase ───────────────────────────

def test_update_conflict_stops_with_actionable_hint(run_script):
    proc, calls = run_script([_view(merge_state="BEHIND")], api_should_fail=True, expect_rc=1)
    assert "update-branch 失败" in proc.stdout
    assert "git fetch origin main" in proc.stdout, "出口必须真可行动（给出本地解法）"
    assert not any(c.startswith(f"gh pr merge {PR}") for c in calls)


# ── 判据 ④：读不到 ⇒ 3（无法判定 ≠ 0）──────────────────────────────────────────

def test_unreadable_state_is_three_not_zero(run_script):
    # 没有可回放的读数 ⇒ 替身 gh 报错 ⇒ 脚本必须 3
    run_script([], expect_rc=3)


# ── 判据 ⑤：CLEAN 且无 pending ⇒ merge，观察 MERGED ⇒ 0 ───────────────────────

def test_clean_merges_and_observes_merged(run_script):
    proc, calls = run_script([_view(merge_state="CLEAN"), _view(state="MERGED", merge_state="CLEAN")], expect_rc=0)
    assert any(c.startswith(f"gh pr merge {PR} --squash") for c in calls)
    assert "已合并" in proc.stdout


def test_already_merged_short_circuits(run_script):
    proc, calls = run_script([_view(state="MERGED", merge_state="CLEAN")], expect_rc=0)
    assert not any(c.startswith(f"gh pr merge {PR}") for c in calls), "已合并就不该再调 merge"
    assert "已合并" in proc.stdout


# ── 判据 ⑥：dry-run 零动作 ────────────────────────────────────────────────────

def test_dry_run_is_read_only(run_script):
    proc, calls = run_script([_view(merge_state="BEHIND")], args=("--dry-run",), expect_rc=0)
    assert not any("update-branch" in c for c in calls), "--dry-run 不许 update"
    assert not any(c.startswith(f"gh pr merge {PR}") for c in calls), "--dry-run 不许 merge"
    assert "将 update-branch" in proc.stdout


# ── 判据 ⑥b：等 pending **不消耗轮次**（实测教训：默认 4 轮连一轮 CI 都等不完）─────────

def test_waiting_for_pending_does_not_consume_attempts(run_script):
    """pending 多轮（CI 要跑 8-10 min）之后变 CLEAN ⇒ 必须仍然能合并。

    红证 = 把「等」也计入轮次（改前语义）⇒ 本用例会在 pending 的第 2~3 轮就把轮次耗尽 ⇒ exit 3。
    """
    views = [_view(merge_state="BLOCKED", pending=19) for _ in range(3)]
    views += [_view(merge_state="CLEAN"), _view(state="MERGED", merge_state="CLEAN")]
    proc, calls = run_script(views, args=("--max-attempts", "2"), expect_rc=0)
    assert any(c.startswith(f"gh pr merge {PR} --squash") for c in calls), "等完之后必须真的合并"
    assert "已合并" in proc.stdout


def test_wait_timeout_is_three(run_script):
    """一直 pending 且不前进 ⇒ 到 --timeout 必须 3（未判定），不许当成功。"""
    proc, calls = run_script([_view(merge_state="BLOCKED", pending=1) for _ in range(80)],
                             args=("--timeout", "1"), expect_rc=3)
    assert "未判定" in proc.stdout
    assert not any(c.startswith(f"gh pr merge {PR}") for c in calls)


# ── 判据 ⑥c：「全绿却 BLOCKED」必须诊断到评审线程（issue #7206 的实测真因）──────────

def test_blocked_without_red_diagnoses_review_threads(run_script):
    """#7188 实测：16 条 required 全绿、pending=0，仍 BLOCKED —— 真因是**未解决的评审线程**。

    红证 = 去掉脚本里那段诊断（`resolve_stale_bot_threads.py` 的调用）⇒ 本用例必红：
    输出里只剩「跑 gh pr view 看拦在哪」，人还得自己猜。
    """
    proc, calls = run_script([_view(merge_state="BLOCKED")], args=("--max-attempts", "1", "--timeout", "1"),
                             expect_rc=3)
    assert "评审线程" in proc.stdout, f"必须点名「未解决的评审线程」这个真因；实测输出：{proc.stdout}"
    assert "resolve_stale_bot_threads.py" in proc.stdout, "必须给出可执行出口（仓库既有判定器）"


# ── 判据 ⑦：脚本本体存在且可执行（防「判据在、工具没了」的假绿）──────────────────

def test_no_bare_variable_before_non_ascii():
    """类级固化（铁律 8）：`$VAR` 后紧跟非 ASCII 字符必须写成 `${VAR}`。

    实测踩了 **3 次**：bash 在多字节 locale 下会把全角标点并进变量名 ⇒ `PR\xef: unbound variable`
    （脚本直接崩，且崩溃信息里带着半个 UTF-8 字符，连报错都读不清）。
    红证 = 把任意一处 `${VAR}` 改回 `$VAR` 且后面跟全角标点 ⇒ 本用例必红。
    """
    import re
    body = SCRIPT.read_text(encoding="utf-8")
    bad = [m.group(0) for m in re.finditer(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])", body)]
    assert not bad, f"这些位置必须写成 ${{VAR}}（变量后紧跟全角字符会让 bash 把标点并进变量名）：{bad}"


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"工具缺失：{SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"工具不可执行（chmod +x 缺失）：{SCRIPT}"
    body = SCRIPT.read_text(encoding="utf-8")
    for must in ("update-branch", "gh pr merge", "exit 3", "exit 1"):
        assert must in body, f"脚本必须保留 `{must}`（三态退出码与 update 路径是判据对象）"
