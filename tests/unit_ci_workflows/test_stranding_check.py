# case_ids: MC-012, MC-013
"""`scripts/stranding-check.sh` —— §17.3「交付物搁浅」内容级检测（issue #4065）。

守的这颗地雷（**夹具是真 git 仓库 + 真 bare 远端，不 mock git**：判据本体就是 git/blob 语义，
mock 掉 git 等于把被测对象换成替身，红证会变成假绿）：

`auto-merge` **秒合** ⇒ PR 的 `headRefOid` 之后再推的 commit 不进 main（squash 只带走合并那一刻的树）
⇒ 「CI 绿 / auto-merge 绿」而「交付物不在 main」。本仓已复发两次（#3842→#3847、#3819→#3826），
此前只有散文判据（`grep -nE "搁浅|strand" scripts/batch-integrate-check.sh` ⇒ 0 命中）。

用例分五组（每组都要有**判别力**，不是「跑通就算」）：

① **真搁浅必红**：合并后往分支追加 commit（新增内容不在合并点）⇒ 该文件报 `STRANDED`；同一条命令
   **不加**尾随 commit ⇒ 必须 exit=0 —— 两个方向都钉住，防「永远红」与「永远绿」两种空判据。
② **分支陈旧 ≠ 搁浅**：分支没动、base 单方前进的文件 ⇒ `STALE-BRANCH`，不进搁浅清单
   （本仓明确记过：commit 可达性不是判据，用错了会把**已交付**判成搁浅 = 假警报）。
③ **squash 的并发并入 ≠ 搁浅**：合并点把 base 对同一文件的并发改动一起并入 ⇒ 与分支 tip **逐字节不同**，
   但分支自己的新增内容都在合并点里 ⇒ `LANDED-MERGED`，不进搁浅清单。
   （这条是**回归护栏**：判据若只比 blob，这一形态必假红；实证 #4127 的 `docs/sql/schema.sql`。）
④ **三态**：`gh` 不在 PATH / PR 未合并 / 元数据不全 / 远端不可达 ⇒ **exit=3，不是 0**
   （「看不了」不得当「没问题」）。
⑤ **接入口**：`batch-integrate-check.sh <branch> <pr>` 真的调用本检测，且 exit=3 被计成 FAIL。

case_ids 口径：本测试属 **dev/CI 工具链**，与同族 `test_dev_worktree_rebase.py`（#3972）、
`test_agent_presets_guard.py`（#3851）沿用同一组 case id —— 仓库目前没有「开发工具链」用例族，
本 PR **未新建**用例：塞进行为用例库会污染覆盖矩阵（同族 PR 的既有裁定）。
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "stranding-check.sh"
BATCH_SCRIPT = REPO_ROOT / "scripts" / "batch-integrate-check.sh"
# 脚本用到的命令（PATH 屏蔽用例里逐个软链，刻意**不含 gh**）
NEEDED_BINS = ("bash", "git", "sed", "awk", "grep", "mktemp", "rm", "cat", "head", "tail",
               "printf", "dirname", "basename", "python3", "wc", "sort", "uniq", "tr", "cut")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}
PR_NUMBER = 4242


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV})


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _epoch(repo: Path, ref: str) -> int:
    return int(_git(repo, "log", "-1", "--format=%ct", ref).stdout.strip())


def _iso(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Scenario:
    """真仓库 + 真 bare 远端：模拟「PR 分支 → squash 合入 main（含 base 并发改动）→ 源分支继续推进」。"""

    def __init__(self, root: Path):
        self.root = root
        self.origin = root / "origin.git"
        self.repo = root / "work"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.origin.mkdir()
        _git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "remote", "add", "origin", str(self.origin))

        _write(self.repo, "docs/shared.md", "base line one\nbase line two\n")
        _write(self.repo, "docs/stale.md", "stale v1\n")
        _commit(self.repo, "base")
        _git(self.repo, "push", "-q", "origin", "main")

        # PR 分支：本 PR 的交付物 docs/deliver.md + 与 base 并发改动的同一文件 docs/shared.md
        _git(self.repo, "checkout", "-q", "-b", "feat/pr")
        _write(self.repo, "docs/deliver.md", "deliverable v1\n" * 3)
        _commit(self.repo, "pr commit 1")
        _write(self.repo, "docs/shared.md", "base line one\nPR line AAAA\nbase line two\n")
        self.head_oid = _commit(self.repo, "pr commit 2")
        self.merged_at = _epoch(self.repo, self.head_oid) + 1        # 合并发生在 tip 之后 1 秒
        _git(self.repo, "push", "-q", "origin", "feat/pr")

        # base 侧并发改动：shared.md 尾部加一行（与 PR 的改动不重叠 ⇒ 三方合并干净）
        #                  stale.md 改内容（分支没动它 ⇒ 后面必须被判「陈旧」而不是「搁浅」）
        _git(self.repo, "checkout", "-q", "main")
        _write(self.repo, "docs/shared.md", "base line one\nbase line two\nmain line BBBB\n")
        _write(self.repo, "docs/stale.md", "stale v2 (base 单方前进)\n")
        _commit(self.repo, "main concurrent change")

        # squash 合入：main 的树 = base 当前 + PR 的 diff（`git merge --squash` 正是这个语义）
        _git(self.repo, "merge", "-q", "--squash", "feat/pr")
        self.merge_commit = _commit(self.repo, f"squash merge PR (#{PR_NUMBER})")
        _git(self.repo, "push", "-q", "origin", "main")

        # 合并后 main 再单独推进 stale.md（核法必须看**内容**，不是可达性）
        _write(self.repo, "docs/stale.md", "stale v3 (main 合并后再前进)\n")
        _commit(self.repo, "main advances stale.md")
        _git(self.repo, "push", "-q", "origin", "main")
        _git(self.repo, "fetch", "-q", "origin")

    def push_after_merge(self) -> None:
        """病根形态：分支 tip 在合并后继续前进（后推的内容没进 main）。"""
        _git(self.repo, "checkout", "-q", "feat/pr")
        _write(self.repo, "docs/deliver.md", "deliverable v1\n" * 3 + "deliverable v2 (合并后追加)\n")
        _write(self.repo, "docs/late.md", "late file (合并后新增，body 未声明)\n")
        _commit(self.repo, "post-merge commit")
        _git(self.repo, "push", "-q", "origin", "feat/pr")

    def gh(self, *, body: str = "## 交付物\n\n- `docs/deliver.md`\n", files=None, **overrides) -> Path:
        """gh 替身：只回答 `pr view <n> --json ...`（脚本只调这一处）。"""
        data = {
            "number": PR_NUMBER, "state": "MERGED", "mergedAt": _iso(self.merged_at),
            "mergeCommit": {"oid": self.merge_commit}, "headRefOid": self.head_oid,
            "headRefName": "feat/pr", "files": [{"path": p} for p in (files or ["docs/deliver.md"])],
            "body": body,
        }
        data.update(overrides)
        js = self.root / "pr.json"
        js.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        stub = self.bin / "gh"
        stub.write_text(f'#!/bin/sh\ncat "{js}"\n', encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def run(self, *args: str, gh: Path | None = None, path: str | None = None):
        env = {**os.environ, **GIT_ENV, "SC_REPO": str(self.repo)}
        if gh is not None:
            env["SC_GH_BIN"] = str(gh)
        if path is not None:
            env["PATH"] = path
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(self.repo),
                              capture_output=True, text=True, env=env)

    @property
    def gh_stub(self) -> Path:
        return self.bin / "gh"


@pytest.fixture()
def scenario(tmp_path: Path) -> Scenario:
    return Scenario(tmp_path)


def test_stranded_after_merge_push_is_red(scenario: Scenario):
    """① 真搁浅必红：合并后追加的内容不在合并点 ⇒ STRANDED + exit 1。"""
    scenario.gh()
    scenario.push_after_merge()
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STRANDED" in r.stdout
    assert "docs/deliver.md" in r.stdout and "docs/late.md" in r.stdout   # 未在 body 声明的也覆盖到
    assert "合并后新 push：**有**" in r.stdout
    assert f"headRefOid {scenario.head_oid[:8]}" in r.stdout
    red_block = r.stdout.split("── 汇总")[-1]
    assert "docs/deliver.md" in red_block and "docs/late.md" in red_block


def test_no_push_after_merge_is_not_red(scenario: Scenario):
    """① 反例（防假红）：同一夹具**不加**尾随 commit ⇒ exit 0 且无 STRANDED。"""
    scenario.gh()
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STRANDED" not in r.stdout
    assert "合并后无新 push ⇒ **无搁浅**" in r.stdout
    assert "docs/deliver.md" in r.stdout          # 交付物确实被核过（不是空跑）


def test_stale_branch_is_not_red(scenario: Scenario):
    """② 判别力：同一跑里既要红出真搁浅，又**不能**把「base 单方前进」判成搁浅。"""
    scenario.gh(files=["docs/deliver.md", "docs/stale.md"],
                body="## 交付物\n\n- `docs/deliver.md`\n- `docs/stale.md`\n")
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STALE-BRANCH" in r.stdout and "docs/stale.md" in r.stdout
    assert "docs/stale.md" not in r.stdout.split("── 汇总")[-1]


def test_squash_concurrent_merge_is_not_red(scenario: Scenario):
    """③ 回归护栏：合并点把 base 的并发改动并入同一文件 ⇒ 逐字节不等于分支 tip，
    但分支自己的改动都在 ⇒ 必须 `LANDED-MERGED`，**不得**判搁浅（否则本判据每天假红）。"""
    scenario.gh(files=["docs/shared.md"], body="## 交付物\n\n- `docs/shared.md`\n")
    scenario.push_after_merge()          # 有合并后 push ⇒ 不靠「无 push」那条门兜底
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert "docs/shared.md" in r.stdout
    assert "LANDED-MERGED" in r.stdout, r.stdout
    assert "docs/shared.md" not in r.stdout.split("── 汇总")[-1]


def test_gh_missing_is_exit3_not_0(scenario: Scenario, tmp_path: Path):
    """④ 三态：PATH 里根本没有 gh ⇒ 3（**不许**把「看不了」当「没问题」）。"""
    scenario.gh()
    masked = tmp_path / "no-gh-path"
    masked.mkdir()
    for b in NEEDED_BINS:
        found = subprocess.run(["bash", "-lc", f"command -v {b}"],
                               capture_output=True, text=True).stdout.strip()
        if found:
            (masked / b).symlink_to(found)
    assert not (masked / "gh").exists()
    r = scenario.run("--pr", str(PR_NUMBER), path=str(masked))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "无法判定" in r.stdout + r.stderr and "gh" in r.stdout + r.stderr


def test_pr_metadata_incomplete_is_exit3(scenario: Scenario):
    """④ 三态：PR 未合并 / 缺 mergeCommit ⇒ 3（判不了就说判不了）。"""
    scenario.gh(state="OPEN")
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 3
    assert "未合并" in r.stdout + r.stderr

    scenario.gh(mergeCommit={"oid": ""})
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 3
    assert "元数据不全" in r.stdout + r.stderr


def test_remote_unreachable_is_exit3(scenario: Scenario):
    """④ 三态：远端读不到（看不到「合并后是否有新 push」）⇒ 3，不是 0。"""
    scenario.gh()
    _git(scenario.repo, "remote", "set-url", "origin", str(scenario.root / "gone.git"))
    r = scenario.run("--pr", str(PR_NUMBER), gh=scenario.gh_stub)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "无法判定" in r.stdout + r.stderr


def test_branch_mode_unmerged_deliverable_is_red(scenario: Scenario):
    """输入允许是分支/commit：分支自己新增、base 上没有的内容 ⇒ STRANDED + exit 1。"""
    scenario.gh()
    scenario.push_after_merge()
    r = scenario.run("--branch", "origin/feat/pr")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STRANDED" in r.stdout and "docs/deliver.md" in r.stdout
    assert "docs/late.md" in r.stdout


def test_batch_entrypoint_wires_stranding_check():
    """⑤ 单一入口：批量检查带 PR 号时自动跑本检测，且 exit=3 被计成 FAIL（不许当通过）。"""
    src = BATCH_SCRIPT.read_text(encoding="utf-8")
    assert "stranding-check.sh --pr" in src, "批量入口没有接搁浅检测（单一入口要求）"
    assert "不许当通过" in src, "无法判定（exit=3）没有被计成 FAIL"
    assert subprocess.run(["bash", "-n", str(BATCH_SCRIPT)]).returncode == 0
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0