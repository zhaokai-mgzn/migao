# case_ids: MC-012, MC-013
"""`scripts/prune-merged-branches.sh` —— 远程分支卫生清理（**手动、attended**）的守卫与红证。

被守的东西（本仓实测，2026-09-22）：
  本仓合并含 **squash** ⇒ 原分支提交**永远不是** `origin/main` 的祖先、`git cherry` 全是 `+`
  ⇒ `git branch -r --merged origin/main` 在本仓**失效**（实测只列出 **1** 条 = main 自己）。
  唯一可靠判据 = 「GitHub 上这条分支的 PR 已 MERGED」（#5070 在 `scripts/dev-worktree.sh`
  的 `prune` 子命令补过同一判据；本脚本沿用同一形态，不是第二套口径）。
  ⇒ 本脚本会**删远程分支**（不可逆）⇒ 每个安全条件都必须有**能单独让它变红**的红证。

夹具形态（**真 git 仓库 + 桩 `gh`，不 mock git**）：判据本体是「gh 的 PR 状态 + 保护名单」
的合取，git 侧只提供分支清单与删除动作 ⇒ 用真 bare origin + 真 push 才能证明
「删了 / 没删」；把 git 也 mock 掉等于把被测对象换成替身（红证会变假绿）。

红证纪律：每条用例的**变异体**见测试函数 docstring 的「红证」一行 —— 把该行描述的实现改动
注入后，本用例必须失败。R1~R7 逐条对应验收判据 ①~⑦，R8 是幂等。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("PRUNE_SCRIPT_UNDER_TEST") or (REPO_ROOT / "scripts" / "prune-merged-branches.sh"))
#: 变异注入跑法（见 PR body 红证表）：把被测脚本指向一份注入过的副本时，跳过读真实脚本的静态守卫。
MUTATING = bool(os.environ.get("PRUNE_SCRIPT_UNDER_TEST"))

MAIN = "main"
PROTECTED = "chore/flaky-ledger"
MERGED_ONLY = "feat/merged-only"          # ① 有已合并 PR、无 open PR、非保护 ⇒ 删
MERGED_BUT_OPEN = "feat/merged-but-open"  # ② 有已合并 PR 但有 open PR ⇒ 不删
OPEN_ONLY = "feat/open-only"              # ④ 仅 open PR ⇒ 不删
NO_PR = "feat/no-pr"                      # ④ 从未有 PR ⇒ 不删

#: 桩 `gh`：只认 `pr list`，按参数从环境变量取「该分支的 PR 状态」。
#: **不对 `--head` 之外的形态作答** ⇒ 若实现退化成别的取数方式，桩会返回非 JSON ⇒ fail-closed 红。
GH_STUB = """#!/usr/bin/env bash
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  [ "${GH_STUB_FAIL:-0}" = "1" ] && { echo "stub: simulated API failure" >&2; exit 1; }
  head=""; state=""
  shift 2
  while [ $# -gt 0 ]; do
    case "$1" in
      --head) head="$2"; shift 2 ;;
      --state) state="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  case "$state" in
    merged) [ "${GH_STUB_MERGED_FAIL:-0}" = "1" ] && { echo "stub: merged API failure" >&2; exit 1; }
             data="${GH_STUB_MERGED:-[]}" ;;
    open)   data="${GH_STUB_OPEN:-[]}"
            [ "${GH_STUB_FAIL_OPEN_HEAD:-0}" = "1" ] && [ -n "$head" ] && { echo "stub: open-head API failure" >&2; exit 1; }
            [ "${GH_STUB_OPEN_HEAD_EMPTY:-0}" = "1" ] && [ "$head" = "feat/merged-but-open" ] && { printf '[]'; exit 0; }
            if [ -n "${GH_STUB_OPEN_HEAD:-}" ] && [ -n "$head" ]; then
              printf '[{"headRefName": "%s", "number": 999}]' "$head"
              exit 0
            fi ;;
    *)      echo "stub: unexpected state '$state'" >&2; exit 1 ;;
  esac
  [ -n "$head" ] || head="__ALL__"
  printf '%s' "$data" | GH_STUB_HEAD="$head" python3 -c '
import json, os, sys
rows = json.load(sys.stdin)
head = os.environ["GH_STUB_HEAD"]
print(json.dumps(rows if head == "__ALL__" else [r for r in rows if r.get("headRefName") == head]))
'
  exit $?
fi
echo "stub: unexpected invocation: $*" >&2
exit 1
"""

#: 桩 git 包装：记录每条子命令，然后透传真 git（真删才判得出「删了 / 没删」）。
GIT_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GIT_STUB_LOG"
exec "$GIT_STUB_REAL" "$@"
"""


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture()
def sandbox(tmp_path: Path):
    """真 bare `origin` + 真工作仓库 + 桩 `gh`/`git`。返回 (repo, env, gh_state)。"""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git("init", "--bare", "-b", MAIN, str(origin), cwd=tmp_path)
    _git("init", "-b", MAIN, str(repo), cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)
    (repo / "README.md").write_text("sandbox\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    _git("remote", "add", "origin", str(origin), cwd=repo)
    _git("push", "-u", "origin", MAIN, cwd=repo)

    wt = tmp_path / "wt"
    _git("worktree", "add", "-b", MERGED_ONLY, str(wt), cwd=repo)
    for branch in (MERGED_BUT_OPEN, OPEN_ONLY, NO_PR, PROTECTED):
        (wt / "f.txt").write_text(f"{branch}\n", encoding="utf-8")
        _git("add", "f.txt", cwd=wt)
        _git("commit", "-m", f"work on {branch}", cwd=wt)
        _git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
    # MERGED_ONLY 也必须带一个**不在 main 上**的提交（squash 后不可达 ⇒ 复现真实形态）
    (wt / "f.txt").write_text("merged-only\n", encoding="utf-8")
    _git("add", "f.txt", cwd=wt)
    _git("commit", "-m", "work on merged-only", cwd=wt)
    _git("push", "origin", f"HEAD:refs/heads/{MERGED_ONLY}", cwd=wt)
    _git("worktree", "remove", str(wt), "--force", cwd=repo)

    _git("fetch", "origin", cwd=repo)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    gitw = bindir / "git-wrapper"
    gitw.write_text(GIT_STUB, encoding="utf-8")
    gitw.chmod(0o755)

    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}:{os.environ['PATH']}",
        GH_BIN=str(gh),
        GIT_BIN=str(gitw),
        GIT_STUB_LOG=str(tmp_path / "git.log"),
        GIT_STUB_REAL="git",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
    )
    return repo, env, tmp_path


def _run(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True, text=True, env=env, timeout=120,
    )


def _remote_branches(repo: Path) -> set[str]:
    """**直接问 remote 本身**（`git ls-remote --heads`），不看本地 tracking ref。

    🔴 这里踩过一次假绿：`refs/remotes/origin/<b>` 在远端分支被删后**不会自动消失**
    （只在 `fetch --prune` 时才清）⇒ 用 for-each-ref 观测「删了没」对真删**不敏感**，
    变异体删了分支、断言却照样绿。观测口径必须与"真删"同源。
    """
    out = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"], cwd=str(repo),
        capture_output=True, text=True, check=True,
    ).stdout
    return {ln.split("\t", 1)[1][len("refs/heads/"):] for ln in out.splitlines() if "\t" in ln}


def _apply_open(env: dict, mapping: dict[str, list[int]]) -> None:
    env["GH_STUB_OPEN"] = _json_of(mapping)


def _apply_merged(env: dict, mapping: dict[str, list[int]]) -> None:
    env["GH_STUB_MERGED"] = _json_of(mapping)


def _json_of(mapping: dict[str, list[int]]) -> str:
    import json

    return json.dumps(
        [{"headRefName": b, "number": n} for b, nums in mapping.items() for n in nums]
    )


def _git_log(env: dict) -> str:
    """桩 git 的调用记录（**只**记录脚本发出的子命令）；文件不存在 = 脚本没调过 git。"""
    f = Path(env["GIT_STUB_LOG"])
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _baseline(env: dict) -> None:
    """桩默认态：MERGED_ONLY 有已合并 PR；MERGED_BUT_OPEN 有已合并 PR + open PR；
    OPEN_ONLY 仅 open PR；PROTECTED 有已合并 PR。"""
    _apply_merged(env, {MERGED_ONLY: [101], MERGED_BUT_OPEN: [102], PROTECTED: [103]})
    _apply_open(env, {MERGED_BUT_OPEN: [202], OPEN_ONLY: [201]})


# ── R1：dry-run 默认零删除（验收判据 ①）───────────────────────────────────────
def test_r1_dry_run_deletes_nothing(sandbox) -> None:
    """默认（不带 --apply）只打印，**零删除**；且清单里恰好只有满足四条的 1 条。

    红证：把 `APPLY` 的默认值改成 1（`APPLY=1`）⇒ 本例 `_remote_branches` 少一条 ⇒ 红。
    """
    repo, env, tmp = sandbox
    _baseline(env)
    before = _remote_branches(repo)

    r = _run(repo, env)

    assert r.returncode == 0, r.stderr
    assert "dry-run" in r.stdout
    assert MERGED_ONLY in r.stdout and "merged PR #101" in r.stdout
    assert _remote_branches(repo) == before, "dry-run 不得删除任何分支"
    assert _git_log(env).count("--delete") == 0


# ── R2：--apply 只删满足四条的（验收判据 ②）───────────────────────────────────
def test_r2_apply_deletes_only_fully_qualified(sandbox) -> None:
    """`--apply` ⇒ 删 `MERGED_ONLY`，其余三条一律不动；且逐条留痕 `branch ← merged PR #N`。

    红证：去掉 ②/③/④ 任一判定（例如把 `in_protect` 的 return 改成 1）⇒ 多删一条 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    after = _remote_branches(repo)
    assert MERGED_ONLY not in after
    assert after == before - {MERGED_ONLY}
    assert f"{MERGED_ONLY} ← merged PR #101" in r.stdout
    assert _git_log(env).count("--delete") == 1


# ── R3：有已合并 PR 但有 open PR ⇒ 不删（验收判据 ③）──────────────────────────
def test_r3_merged_but_open_pr_is_kept(sandbox) -> None:
    """安全条件 ②/④：`MERGED_BUT_OPEN` 同时有已合并与 open PR ⇒ 不删，且理由逐条打印。

    红证（**两条独立注入，各自都能让它红**）：
      ① 短路全量 head 交叉核对（④，`if head_is_open "$b"` → `if false`）⇒ 跳过理由里不再出现
         "有 open PR" ⇒ 红；
      ② 短路逐分支 open 判定（②，`if [ "$open_n" != "0" ]` → `if false`）⇒ 同上 ⇒ 红。
      （②/④ 是**双保险**：单短路一条仍不会真删 —— 这正是"任一不满足即跳过"的冗余设计。
        要真正误删必须两条同时失效，见 PR body 红证表的 R3-合并注入。）
    """
    repo, env, _ = sandbox
    _baseline(env)
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    assert MERGED_BUT_OPEN in _remote_branches(repo)
    assert MERGED_BUT_OPEN in r.stdout, "被跳过的分支必须出现在日志里（可审计）"
    assert f"⛔ {MERGED_BUT_OPEN}（有 open PR）" in r.stdout, \
        "跳过理由必须是「有 open PR」（②/④ 任一失效 ⇒ 这条理由消失 ⇒ 红）"
    assert _remote_branches(repo) == before - {MERGED_ONLY}


# ── R4：保护名单 ⇒ 不删（验收判据 ③）─────────────────────────────────────────
def test_r3_global_open_list_check_is_independently_necessary(sandbox) -> None:
    """安全条件 **④** 单独可判红（反向 TOCTOU）：分支**在全量 open 列表里**（④ 看得见），
    但**逐分支** open 查返回空（② 看不见 —— 模拟 PR 在两次调用之间被关闭）。
    此时只有 ④ 能拦住删除。

    红证：短路 ④（`if head_is_open "$b"` → `if false`）⇒ 该分支被删 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    env["GH_STUB_OPEN_HEAD_EMPTY"] = "1"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    assert MERGED_BUT_OPEN in _remote_branches(repo), "全量 open 列表判定必须独立生效"
    assert _remote_branches(repo) == before - {MERGED_ONLY}, "其余分支不受影响"
    assert f"⛔ {MERGED_BUT_OPEN}（有 open PR）" in r.stdout


def test_r3b_per_branch_open_check_is_independently_necessary(sandbox) -> None:
    """安全条件 **②** 单独可判红：造 TOCTOU 夹具 —— 分支**不在**全量 open 列表里
    （④ 看不见），但**逐分支** open 查得到（② 看得见）。此时只有 ② 能拦住删除。

    红证：短路 ②（`if [ "$open_n" != "0" ]` → `if false`）⇒ 该分支被删 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    # 全量 open 列表里**不含** MERGED_ONLY（④ 看不见它），但逐分支查返回「有 open PR」
    env["GH_STUB_OPEN_HEAD"] = "1"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    assert MERGED_ONLY in _remote_branches(repo), "逐分支 open 判定必须独立生效（不得只靠全量列表）"
    assert _remote_branches(repo) == before, "TOCTOU 窗口内不得删任何分支"
    assert f"⛔ {MERGED_ONLY}（有 open PR）" in r.stdout


def test_r4_protected_branches_are_kept(sandbox) -> None:
    """安全条件 ③：`main` 与 `chore/flaky-ledger`（台账滚动分支，合并后会被重建）永不删。

    红证：把 `PROTECT_DEFAULT` 改成空串 ⇒ 两条被删 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    after = _remote_branches(repo)
    assert MAIN in after and PROTECTED in after
    assert "保护名单" in r.stdout


# ── R5：没有已合并 PR ⇒ 不删（验收判据 ④）────────────────────────────────────
def test_r5_no_merged_pr_is_kept(sandbox) -> None:
    """安全条件 ①：仅 open PR / 从未有 PR 的分支都不删（含"仅 closed 未合并"同形态）。

    红证：把「已合并 PR 非空」判定改成 `True`（只要分支存在就算满足）⇒ 三条被删 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)

    r = _run(repo, env, "--apply")

    assert r.returncode == 0, r.stderr
    after = _remote_branches(repo)
    assert OPEN_ONLY in after and NO_PR in after
    assert "无已合并 PR" in r.stdout
    assert OPEN_ONLY not in _git_log(env)


# ── R6：gh API 失败 ⇒ 一条都不删 + 非零退出（验收判据 ⑤）─────────────────────
def test_r6_api_failure_is_fail_closed(sandbox) -> None:
    """fail-closed：`gh` 失败 ⇒ 零删除 + 非零退出（**不得**退化成"删不掉就跳过"的静默）。

    红证：把取数失败的 `exit 1` 改成 `continue`/跳过 ⇒ 退出码变 0 且清单继续 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    # 只让**顶层**那次 open 列表取数坏掉（非 JSON）；逐分支查仍正常 ⇒
    # 若顶层守卫退化，脚本会因 open_heads 为空而**删掉 MERGED_BUT_OPEN** ⇒ 必红。
    env["GH_STUB_OPEN"] = "<html>rate limited</html>"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode != 0, "顶层取数失败必须非零退出"
    assert "[top]" in r.stderr, \
        "必须由**顶层**守卫拦下（[top] 是它独有标记；短路它 ⇒ 逐分支守卫接不住 ⇒ 红）"
    assert "fail-closed" in r.stderr, "必须显式声明 fail-closed（不得退化成别的原因碰巧非零）"
    assert _remote_branches(repo) == before, "API 失败时一条都不许删"
    assert "--delete" not in _git_log(env)


def test_r6b_per_branch_api_failure_is_fail_closed(sandbox) -> None:
    """fail-closed 第二形态：**只有逐分支那次** `--state merged` 查失败（顶层取数正常）⇒
    仍必须零删除 + 非零退出 + 显式 fail-closed 文案。

    红证：把逐分支的 `exit 1` 改成 `continue`/跳过 ⇒ 退出码 0 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    env["GH_STUB_MERGED_FAIL"] = "1"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode != 0, "逐分支取数失败必须非零退出"
    assert "fail-closed" in r.stderr
    assert _remote_branches(repo) == before, "逐分支取数失败时一条都不许删"
    assert "--delete" not in _git_log(env)


def test_r6c_per_branch_open_failure_is_fail_closed(sandbox) -> None:
    """fail-closed 第三形态：逐分支 **open** 查失败（顶层与 merged 查都正常）⇒ 零删除 + 非零。

    红证：把该处的 `exit 1` 改成 `continue` ⇒ 退出码 0 且继续删 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    env["GH_STUB_FAIL_OPEN_HEAD"] = "1"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode != 0, "逐分支 open 取数失败必须非零退出"
    assert "fail-closed" in r.stderr
    assert _remote_branches(repo) == before
    assert "--delete" not in _git_log(env)


def test_r6d_malformed_response_is_fail_closed(sandbox) -> None:
    """fail-closed 第二形态：返回体**不是 JSON**（例如实现退化成别的取数方式）⇒ 同上。

    红证：把解析失败的分支改成当作"空列表"处理 ⇒ 退出码 0 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)
    env["GH_STUB_OPEN"] = "not json at all"
    before = _remote_branches(repo)

    r = _run(repo, env, "--apply")

    assert r.returncode != 0
    assert _remote_branches(repo) == before


# ── R7：单次上限 + 剩余数（验收判据 ⑥）──────────────────────────────────────
def test_r7_limit_caps_deletions_and_reports_remaining(sandbox) -> None:
    """`--limit 2` ⇒ 只删 2 条（按 PR 号升序），并打印剩余待清理数。

    红证：去掉 `head -n "$LIMIT"`（改成全量）⇒ 删 3 条 ⇒ 红。
    """
    repo, env, tmp = sandbox
    # 再造两条满足条件的（真分支 + 真 PR 号）
    wt = tmp / "wt2"
    _git("worktree", "add", "-b", "feat/extra-a", str(wt), cwd=repo)
    for branch in ("feat/extra-a", "feat/extra-b"):
        (wt / "f.txt").write_text(f"{branch}\n", encoding="utf-8")
        _git("add", "f.txt", cwd=wt)
        _git("commit", "-m", branch, cwd=wt)
        _git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=wt)
    _git("worktree", "remove", str(wt), "--force", cwd=repo)
    _git("fetch", "origin", cwd=repo)

    _apply_merged(
        env,
        {MERGED_ONLY: [101], MERGED_BUT_OPEN: [102], PROTECTED: [103],
         "feat/extra-a": [104], "feat/extra-b": [105]},
    )
    _apply_open(env, {MERGED_BUT_OPEN: [202], OPEN_ONLY: [201]})

    r = _run(repo, env, "--apply", "--limit", "2")

    assert r.returncode == 0, r.stderr
    after = _remote_branches(repo)
    deleted = {"feat/merged-only", MERGED_BUT_OPEN, PROTECTED, OPEN_ONLY, NO_PR,
               "feat/extra-a", "feat/extra-b"} - after
    assert deleted == {MERGED_ONLY, "feat/extra-a"}, f"应按 PR 号升序删 2 条，实删 {deleted}"
    assert "剩余待清理：1" in r.stdout


# ── R8：幂等（重复跑不报错、不误删）──────────────────────────────────────────
def test_r8_idempotent_second_run(sandbox) -> None:
    """连跑两次 `--apply`：第二次零动作、退出 0（已删的分支不在 `origin` 里）。

    红证：把「无待删分支」的提前 return 0 改成 return 1 ⇒ 第二次非零 ⇒ 红。
    """
    repo, env, _ = sandbox
    _baseline(env)

    first = _run(repo, env, "--apply")
    second = _run(repo, env, "--apply")

    assert first.returncode == 0 and second.returncode == 0, second.stderr
    assert "无待删分支" in second.stdout
    assert _git_log(env).count("--delete") == 1


# ── 静态守卫：不得退化成定时任务 / 不得用失效判据 ────────────────────────────
@pytest.mark.skipif(MUTATING, reason="变异跑法：静态守卫读的是真实脚本，不参与注入")
def test_script_is_not_scheduled_and_avoids_dead_criteria() -> None:
    """本单形态是**手动 attended**：脚本自身不得被任何 workflow 的 `schedule:` 引用；
    且实现里**不得**出现 `--merged` / `git cherry` 这类在本仓失效的合入判据。

    红证：在实现里加一行 `git branch -r --merged origin/main` ⇒ 本例红。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    # 只看**可执行行**（注释里必须能说明"为什么不用它"，否则这条守卫会逼着人删掉论据）
    code = "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )
    assert "--merged" not in code, "不得用本仓失效的 --merged 判据"
    assert "cherry" not in code, "不得用本仓失效的 cherry 判据"
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
    hits = [w.name for w in workflows if "prune-merged-branches" in w.read_text(encoding="utf-8")]
    assert hits == [], f"本脚本是手动 attended 形态，不得挂到定时 workflow：{hits}"
