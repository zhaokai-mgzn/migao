# case_ids: MC-012, MC-013
"""`dev-worktree.sh rebase` —— 预设快照不再挡住 `git rebase origin/main`（issue #3972）；
`land` 对「预设面 PR」的**假阻塞**（关联 #5707）。

守的这颗地雷（**夹具是真 git 仓库，不 mock**：判据本体就是 git 语义，mock 掉 git 等于把被测对象
换成替身，红证会变成假绿）：

`dev-worktree.sh add` 会用 `refresh_presets` 把 `.agent-presets/**` 对齐到 `origin/main`，
于是工作区相对**本分支 HEAD** 就出现了改动，`git rebase origin/main` 被 git 拒绝。实测两种形态：
  · 本分支 HEAD **未跟踪**该路径（旧分支，早于预设入库）⇒ 快照留在**索引**里（staged new files）
    → 「untracked working tree files would be overwritten by checkout」；
  · 本分支 HEAD 跟踪但版本较旧 ⇒ 相对 HEAD 变成**已修改** → 「cannot rebase: You have unstaged changes」。

用例分六组（①②③ 是 issue #3972 的原判据；④⑤⑥ + 元守卫是 #5707 追加）：
① **红证**：不加处置时 `git rebase origin/main` 必失败（直接断言失败，把形态钉住）；
② **绿证**：`dev-worktree.sh rebase <分支>` 一条命令成功、工作树干净、预设刷到 origin/main 版本；
③ **不许误伤**：预设内容与 origin/main **不一致**（= 开发者的在办改动）时必须**停手**：
   非零退出、且**不删除**那些文件（预设是主干资产，但别人的在办改动不能被静默吞掉）。
④ **已提交的**预设改动（= 研发模式固化工作的落点）**不是漂移**：分支 0 behind 时
   `dev-worktree.sh rebase` 必须放行（不得停在「拒绝自动丢弃」），且改动在**分支提交里 + 工作区里**
   都逐字节保留，工作区干净（不得留下「把分支产物改回去」的已暂存改动）；
⑤ **真的 behind** ⇒ **仍走 rebase**：分支提交被重放到最新 main 之上，预设改动照样逐字节保留；
⑥ 不许改松：**未提交**漂移（既非 HEAD 也非 origin/main）在任何一条分支形态下都必须仍被拒。

判据 ④⑤ 对应的**病灶**（本会话独立复现，读数见 PR 正文）：`discard_preset_snapshot` 原先**只用
`origin/main` 当参照物** ⇒ 分支**自己已提交**的预设改动被读成「与 origin/main 不一致的漂移」⇒
`land` 的①步（`scripts/issue_lifecycle.py::_land_do_step` 里的 `rebase`）拿到 rc≠0 ⇒ 判 failed ⇒ 整条
`land` 停下 —— 而现场（PR #5718）**0 behind、根本不需要 rebase**；即使放行，紧随其后的
`refresh_presets` 又会把工作区覆盖成 origin/main 版本（⇒ 判据 ④ 的「工作区干净 + 逐字节」两条）。

## 覆盖面登记：本判据面**覆盖不到**什么

（写法照 `migao-dev-flow` §25.6 与判据 12 的「明确的边界」；带 `::` 的每条都由
`test_coverage_boundary_faces_resolve` 现取解析 —— 锚解析不到即红，所以这里不许写散文。）

- ❌ **射程只到 `scripts/dev-worktree.sh` 里 `.agent-presets/**` 的两个写面**：别的写面不在射程 ——
  · 活锚镜像是**另一条写面**（它写的是专职只读镜像，与分支产物无关，判据不在本文件）：
    `scripts/preset-anchor-refresh.sh::--no-check`；
  · `land` 只**转发**判定，本文件不改那条映射（rc≠0 ⇒ `[rebase]` failed）：
    `scripts/issue_lifecycle.py::_land_do_step`。
- ❌ **不覆盖 `dev-worktree.sh` 的其它子命令语义**：`add` 的会话锁 / 并发语义（同分支两个 worktree）
  与本次改动无关，判据仍只覆盖它的预设刷新面（`scripts/dev-worktree.sh::cmd_add`）。
- ❌ **不覆盖运行期已存在的 worktree 状态**：落在收尾半径外或已被 `rm/prune` 收掉的检出不在射程
  （CI 上没有 `migao-wt/`，判据看不到）。
- ❌ **只保证「写面带守卫且守卫载重」，不保证「守卫的参照物选得对」**：参照物（HEAD vs 合并基点 vs
  origin/main）是**设计判断**，由本文件的 ④⑤⑥ 三条行为判据钉住，没有更强的机械锁。
- ❌ **元守卫的普查器只认两种命令行形态**（`checkout … -- .agent-presets/` 与 `rm -rf … .agent-presets`，
  且不在 `echo` 行上）⇒ 换个写法把预设写掉（变量拼接路径、`git stash`、`mv`、经别的脚本写）
  **不入册、也不会红**（漏报方向）。
- ❌ 普查器依赖「函数以**顶格 `}`** 结束」这一形态 ⇒ 写成一行函数 / 别的缩进风格的函数**不被普查到**
  （同样是漏报方向；发现方式是人工复核，不是判据）。
- ❌ **`preset_has_uncommitted_drift` 的未跟踪面用 `--exclude-standard`**：被 `.gitignore` 命中的文件
  不算漂移（与本脚本其它处同口径），因此「`.agent-presets/**` 下只有被忽略文件」这种形态不在射程。

case_ids 口径：本测试属 **dev 工具链**，与同族 `test_agent_presets_guard.py`（#3851）沿用同一组
case id。仓库目前没有「开发工具链」用例族，本 PR **未新建**用例——它不是 agent 行为，
塞进行为用例库会污染覆盖矩阵（见 PR 说明）。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
PRESET_FILE = ".agent-presets/migao/preset.yml"
#: 预设面 PR 的分支会改的三个文件（两个已跟踪 + 一个**新增** —— 新增面也要逐字节保留）
PRESET_SKILL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
NEW_PRESET_FILE = ".agent-presets/migao/skills/migao-dev-flow/NEW-SECTION.md"
PRESET_PATHS = (PRESET_FILE, PRESET_SKILL, NEW_PRESET_FILE)
#: `origin/main` 里**已存在**的预设文件（刷新只会覆盖它们；分支新增的那一个不在 main 的树里，
#: `checkout origin/main -- .agent-presets/` 碰不到它 —— M2 的读数只对这几个文件成立）
PRESET_PATHS_IN_MAIN = (PRESET_FILE, PRESET_SKILL)
BRANCH_EDIT_MSG = "feat(dev-mode): 本分支的预设改动（已提交）"
MAIN_ADVANCE_MSG = "main advances（含一个本分支没碰过的新预设文件）"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _script(repo: Path, *args: str, env: dict, check: bool = True):
    return subprocess.run(
        ["bash", str(repo / "scripts" / "dev-worktree.sh"), *args],
        cwd=str(repo),
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _sha(wt: Path, rev_path: str) -> str:
    """某个 rev 下某路径的 **blob sha**（`HEAD:<path>` / `origin/main:<path>`）。"""
    return _git(wt, "rev-parse", rev_path).stdout.strip()


def _worktree_sha(wt: Path, path: str) -> str:
    """工作区**实际字节**的 blob sha（与 `_sha` 同口径 ⇒ 两条读数可直接比）。"""
    return _git(wt, "hash-object", str(wt / path)).stdout.strip()


@pytest.fixture()
def scenario(tmp_path: Path):
    """真 git 仓库：main 已入库预设（v2），分支 `old` 早于预设入库（HEAD 不含该路径）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")

    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "branch", "old")  # ← 早于预设入库

    preset = repo / PRESET_FILE
    preset.parent.mkdir(parents=True)
    preset.write_text("version: 1.0.0\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v1")
    preset.write_text("version: 2.0.0\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v2")

    # 让脚本能解析到 origin/main（无远程时 refresh_presets 会警告并继续按本地 origin/main 刷新）
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    (repo / "scripts").mkdir()
    (repo / "scripts" / "dev-worktree.sh").write_bytes(SCRIPT.read_bytes())

    env = {**os.environ, "MIGAO_WT_BASE": str(tmp_path / "wt")}
    return repo, env, tmp_path / "wt" / "old"


def test_add_refreshes_presets_and_creates_the_trap(scenario):
    """① add 会把预设刷进工作区（这正是 rebase 被挡的来源）—— 红证的前提条件。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    assert (wt / PRESET_FILE).read_text(encoding="utf-8") == "version: 2.0.0\n", (
        "add 应把 .agent-presets/** 刷新到 origin/main 版本（v2）"
    )

    # ② 红证：不加处置时 rebase 必失败（git 拒绝覆盖/丢弃这些「本地改动」）
    failed = _git(wt, "rebase", "origin/main", check=False)
    assert failed.returncode != 0, (
        "夹具没造出 #3972 的形态：rebase 竟然成功了（预设差异没能挡住它）"
    )
    _git(wt, "rebase", "--abort", check=False)


def test_rebase_subcommand_discards_snapshot_then_rebases(scenario):
    """② 绿证：`dev-worktree.sh rebase` 一条命令走通，且收尾状态干净。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    out = _script(repo, "rebase", "old", env=env)
    assert "✅ rebase 完成" in out.stdout

    assert _git(wt, "log", "-1", "--format=%s").stdout.strip() == "presets v2", (
        "rebase 后应落在 origin/main 的最新提交上"
    )
    assert _git(wt, "status", "--porcelain").stdout.strip() == "", (
        "rebase 完成后工作树必须干净（预设差异已被丢弃并重新刷新）"
    )
    assert (wt / PRESET_FILE).read_text(encoding="utf-8") == "version: 2.0.0\n"

    # 幂等：再跑一次不应报错、状态不变
    _script(repo, "rebase", "old", env=env)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""


def test_rebase_subcommand_refuses_to_discard_foreign_preset_edits(scenario):
    """③ 不许误伤：预设与 origin/main 不一致（在办改动）⇒ 停手、非零退出、不删文件。"""
    repo, env, wt = scenario
    _script(repo, "add", "old", env=env)

    # 模拟开发者正在改研发模式：把刷新进来的快照改成与 origin/main 不同的内容
    edited = wt / PRESET_FILE
    edited.write_text("version: 9.9.9-local-wip\n", encoding="utf-8")

    failed = _script(repo, "rebase", "old", env=env, check=False)
    assert failed.returncode != 0, "与 origin/main 不一致的预设改动必须让子命令停手"
    assert "拒绝自动丢弃" in (failed.stdout + failed.stderr)
    assert edited.exists() and edited.read_text(encoding="utf-8") == "version: 9.9.9-local-wip\n", (
        "停手必须保留开发者的在办预设改动（不得静默删除）"
    )


# ── ④⑤⑥（关联 #5707）：「**已提交**的预设改动」是分支产物，不是快照漂移 ───────────────────
def _make_preset_pr(tmp_path: Path):
    """建「预设面 PR」形态：分支 `presetpr` 相对 origin/main **已提交**一次预设改动 ⇒ 0 behind。

    步骤与真实流程同形（`add` → 在工作区改研发模式 → `git commit`），因此工作区 == HEAD，
    而 HEAD 的 `.agent-presets/**` 与 origin/main 不同 —— 这正是被误判成「漂移」的形态。
    → (repo, env, wt)
    """
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")

    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")

    preset = repo / PRESET_FILE
    preset.parent.mkdir(parents=True, exist_ok=True)
    (repo / PRESET_SKILL).parent.mkdir(parents=True, exist_ok=True)
    preset.write_text("version: 1.0.0\n", encoding="utf-8")
    (repo / PRESET_SKILL).write_text("# dev flow v1\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v1")
    preset.write_text("version: 2.0.0\n", encoding="utf-8")
    (repo / PRESET_SKILL).write_text("# dev flow v2\n", encoding="utf-8")
    _git(repo, "add", ".agent-presets")
    _git(repo, "commit", "-qm", "presets v2")

    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "branch", "presetpr")  # ← 分支起点 = origin/main（0 behind 的形态）

    (repo / "scripts").mkdir()
    (repo / "scripts" / "dev-worktree.sh").write_bytes(SCRIPT.read_bytes())

    env = {**os.environ, "MIGAO_WT_BASE": str(tmp_path / "wt")}
    _script(repo, "add", "presetpr", env=env)
    wt = tmp_path / "wt" / "presetpr"

    # 开发者改研发模式：改两个已跟踪文件 + **新增**一个，然后提交（工作区 == HEAD）
    (wt / PRESET_FILE).write_text("version: 2.0.1\n", encoding="utf-8")
    (wt / PRESET_SKILL).write_text("# dev flow v2 + §99（本分支新增的固化内容）\n", encoding="utf-8")
    (wt / NEW_PRESET_FILE).write_text("# 新增小节（本分支新增的固化内容）\n", encoding="utf-8")
    _git(wt, "add", ".agent-presets")
    _git(wt, "commit", "-qm", BRANCH_EDIT_MSG)
    return repo, env, wt


@pytest.fixture()
def preset_pr(tmp_path: Path):
    """→ (repo, env, wt)：预设面分支 `presetpr`，已提交预设改动、0 behind、工作区干净。"""
    return _make_preset_pr(tmp_path)


def _preset_readings(wt: Path) -> dict:
    """三条读数：分支提交里的内容 / 工作区实际字节 / 工作区是否干净（都按 sha 或逐字比）。"""
    return {
        "head": _git(wt, "rev-parse", "HEAD").stdout.strip(),
        "committed": {p: _sha(wt, f"HEAD:{p}") for p in PRESET_PATHS},
        "worktree": {p: _worktree_sha(wt, p) for p in PRESET_PATHS},
        "status": _git(wt, "status", "--porcelain").stdout.strip(),
        "behind": _git(wt, "rev-list", "--count", "HEAD..origin/main").stdout.strip(),
    }


def test_rebase_at_zero_behind_keeps_committed_preset_edits(preset_pr):
    """④ 0 behind + 已提交预设改动 ⇒ **不再停在 `[rebase]`**，且改动逐字节保留、工作区干净。

    红证（改坏 ⇒ 必红）：把 `scripts/dev-worktree.sh` 的零漂移守卫改成 `if false` ⇒ rc≠0 且
    输出含「拒绝自动丢弃」（见 `test_mutation_dropping_the_zero_drift_guard_brings_the_false_block_back`）；
    把刷新守卫改成 `if false` ⇒ 工作区被 origin/main 覆盖、`status` 出现 `M `（见 M2）；
    把放行提示里的反引号**改回未转义** ⇒ 提示正文被命令替换吃掉、stderr 出现 `is a directory`（见本函数末两条）。
    """
    repo, env, wt = preset_pr
    before = _preset_readings(wt)
    assert before["behind"] == "0", f"夹具没造出 0 behind 的形态：behind={before['behind']}"

    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode == 0, (
        f"0 behind（根本不需要 rebase）不该停在 [rebase]：rc={out.returncode}\n{out.stdout}\n{out.stderr}"
    )
    assert "拒绝自动丢弃" not in (out.stdout + out.stderr), "走了「拒绝自动丢弃」分支 ⇒ #5707 的假阻塞仍在"
    assert "✅ rebase 完成" in out.stdout

    # 🔴 本批实测：**放行提示自己把主语吃掉了**（#5719 新增的那句）—— 提示正文在**双引号里**，
    #    却带了**未转义**的反引号 ⇒ bash 当**命令替换**执行 ⇒ ① stderr 打出
    #    `<脚本>: line N: .agent-presets/<...>: is a directory`（读输出的人会以为预设检查**失败**了）；
    #    ② 提示里的主语路径被替换成空 ⇒ 「跳过的是**哪个路径**」当场消失。
    #    修法 = 反引号**转义**（与 §23.6「含反引号的文本不走双引号参数」同源）；
    #    本仓实测普查：`scripts/**/*.sh` 里该形态共 5 处，**只有这 1 处会被执行**（其余 4 处在 Python heredoc 里，惰性）。
    assert "is a directory" not in (out.stdout + out.stderr), (
        "提示里的反引号被 bash 当命令替换执行了（stderr 出现 `is a directory`）——"
        f"读输出的人会以为预设检查失败：\n{out.stdout}\n{out.stderr}"
    )
    assert "`.agent-presets/**`" in out.stdout, (
        f"放行提示没有把它说的**路径**打出来（正文被命令替换吃掉）：\n{out.stdout}"
    )

    after = _preset_readings(wt)
    assert after["head"] == before["head"], "0 behind 时不应改写历史（HEAD 必须原地不动）"
    for p in PRESET_PATHS:
        assert after["committed"][p] == before["committed"][p], f"分支提交里的 {p} 变了"
        assert after["worktree"][p] == before["worktree"][p], f"工作区里的 {p} 被改写（origin/main 覆盖？）"
    assert after["status"] == "", (
        "工作区必须干净：不得留下「把分支产物改回去」的已暂存改动"
        "（一条 `git commit -a` 就会静默回退固化工作）—— 现取 status："
        f"{after['status']!r}"
    )


def test_rebase_when_behind_still_replays_committed_preset_edits(preset_pr):
    """⑤ 真的 behind ⇒ **仍走 rebase**（不是「跳过 rebase」），且分支产物在重放后逐字节保留。"""
    repo, env, wt = preset_pr
    before = _preset_readings(wt)

    _advance_main(repo, wt)

    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode == 0, f"真 behind + 已提交预设改动必须能 rebase：rc={out.returncode}\n{out.stdout}"
    assert "拒绝自动丢弃" not in (out.stdout + out.stderr)

    after = _preset_readings(wt)
    assert after["behind"] == "0", "rebase 后必须已跟上 origin/main（本步不是空转/跳过）"
    assert _git(wt, "log", "-1", "--format=%s").stdout.strip() == BRANCH_EDIT_MSG, (
        "分支自己的提交必须被重放到最新 main **之上**（且仍是那一条）"
    )
    assert (wt / "MAIN-ONLY.txt").exists() and (wt / ".agent-presets/migao/MAIN-ONLY.yml").exists(), (
        "main 侧的新文件（含新预设文件）必须随 rebase 带过来"
    )
    for p in PRESET_PATHS:
        assert after["committed"][p] == before["committed"][p], f"重放后分支提交里的 {p} 变了"
        assert after["worktree"][p] == before["worktree"][p], f"重放后工作区里的 {p} 变了"
    assert after["status"] == "", f"rebase 后工作区必须干净 —— 现取 status：{after['status']!r}"


def test_rebase_still_refuses_uncommitted_drift_on_a_preset_branch(preset_pr):
    """⑥ 不许改松：预设面分支上的**未提交**漂移（既非 HEAD 也非 origin/main）仍必须停手且不删文件。"""
    repo, env, wt = preset_pr
    head_before = _git(wt, "rev-parse", "HEAD").stdout.strip()
    wip = "# 在办改动（未提交，既不是 HEAD 也不是 origin/main）\n"
    (wt / PRESET_SKILL).write_text(wip, encoding="utf-8")
    committed_before = _sha(wt, f"HEAD:{PRESET_SKILL}")
    assert _worktree_sha(wt, PRESET_SKILL) != committed_before, "夹具没造出「未提交漂移」的形态"
    assert _worktree_sha(wt, PRESET_SKILL) != _sha(wt, f"origin/main:{PRESET_SKILL}"), (
        "夹具的漂移与 origin/main 撞成一致 ⇒ 那是「纯刷新产物」形态，不是本判据要钉的在办改动"
    )

    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode != 0, "未提交漂移必须仍被拒（fail-closed），不得为了放过 ④ 而改松"
    assert "拒绝自动丢弃" in (out.stdout + out.stderr)
    assert (wt / PRESET_SKILL).read_text(encoding="utf-8") == wip, "停手必须保留在办改动（不得静默删除）"
    assert _git(wt, "rev-parse", "HEAD").stdout.strip() == head_before, "停手时 HEAD 不得移动"


def test_rebase_still_refuses_staged_preset_drift_on_a_preset_branch(preset_pr):
    """⑥b 同上，且钉住**已暂存但未提交**这个形态（原始代码点名的「陷阱形态正是已暂存」）。

    它专门拦一个**放宽方向**：把「已提交」的口径写成「只要不在工作区未暂存改动里就算已提交」
    ⇒ 暂存区里的在办改动会被当成产物放行。
    """
    repo, env, wt = preset_pr
    head_before = _git(wt, "rev-parse", "HEAD").stdout.strip()
    staged = "version: 9.9.9-staged\n"
    (wt / PRESET_FILE).write_text(staged, encoding="utf-8")
    _git(wt, "add", ".agent-presets")
    assert _git(wt, "diff", "--cached", "--name-only").stdout.strip() != "", "夹具没造出「已暂存」形态"
    assert _worktree_sha(wt, PRESET_FILE) == _sha(wt, f":{PRESET_FILE}"), "夹具的暂存内容与工作区不一致"

    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode != 0, "已暂存的预设改动必须仍被拒（不得因「已提交才算产物」而放行）"
    assert "拒绝自动丢弃" in (out.stdout + out.stderr)
    assert (wt / PRESET_FILE).read_text(encoding="utf-8") == staged, "停手必须保留暂存区里的在办改动"
    assert _git(wt, "rev-parse", "HEAD").stdout.strip() == head_before, "停手时 HEAD 不得移动"


# ── 类级元守卫（铁律 8）：`.agent-presets/**` 的**写面未登记即红** ─────────────────────────
#: 写面登记：函数 → 它必须调用的守卫。**新增写面必须先登记**（否则将来又会长出一处
#: 「把分支已提交的预设产物写回 origin/main 版本」的路径，而没有任何东西会红）。
GUARDED_PRESET_WRITERS = {
    "discard_preset_snapshot": "preset_has_uncommitted_drift",
    "refresh_presets": "preset_touched_by_branch",
}
#: 「把 `.agent-presets/**` 写掉」的命令形态（**剥注释**后判；`echo` 行不算 —— 那只是提示文本）。
_WRITE_RE = re.compile(
    r"^(?!\s*echo\b).*(?:\bcheckout\b.*--\s+\.agent-presets/|\brm\s+-rf\b.*\.agent-presets)",
    re.M,
)


def _strip_comments(src: str) -> str:
    """剥掉整行 `#` 注释 —— 判据不许被它自己的说明文字满足（「举例即实例」的防线）。"""
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def _shell_functions(src: str) -> dict[str, str]:
    """→ {函数名: 函数体}（`name() {` … 到下一个顶格 `}`）。"""
    funcs: dict[str, str] = {}
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z_]\w*)\(\)\s*\{", lines[i])
        if not m:
            i += 1
            continue
        body = [lines[i]]
        i += 1
        while i < len(lines) and lines[i] != "}":
            body.append(lines[i])
            i += 1
        funcs[m.group(1)] = "\n".join(body)
        i += 1
    return funcs


def preset_writer_functions(src: str) -> dict[str, str]:
    """→ {函数名: 函数体}，只含**执行** `.agent-presets/**` 写入/删除的函数（剥注释后判）。"""
    return {
        name: body
        for name, body in _shell_functions(_strip_comments(src)).items()
        if _WRITE_RE.search(body)
    }


def test_every_preset_writer_in_dev_worktree_is_guarded():
    """元守卫：写面**未登记即红** + 每个登记项必须真的调用它的守卫（守卫被删 ⇒ 红）。"""
    src = SCRIPT.read_text(encoding="utf-8")
    writers = preset_writer_functions(src)
    assert set(writers) == set(GUARDED_PRESET_WRITERS), (
        "`scripts/dev-worktree.sh` 里 `.agent-presets/**` 的写面变了："
        f"现取 {sorted(writers)} vs 登记 {sorted(GUARDED_PRESET_WRITERS)} —— "
        "新增写面必须登记，并带「已提交的分支产物 vs 未提交快照」的守卫"
    )
    for name, guard in GUARDED_PRESET_WRITERS.items():
        assert guard in writers[name], (
            f"{name} 没调用守卫 {guard}（守卫没了 ⇒ 已提交的预设改动会被拒绝或覆盖）"
        )


def test_preset_writer_census_has_discriminating_power():
    """元守卫的判别力自证（**内存构造**，不写磁盘）：新写面 / 删守卫都能被抓到。"""
    src = SCRIPT.read_text(encoding="utf-8")
    new_writer = (
        "future_unregistered_writer() {\n"
        '  git -C "$1" checkout origin/main -- .agent-presets/\n'
        "}\n\n"
    )
    mutated = src + "\n" + new_writer
    assert mutated != src, "变异注入未生效（自证失败）"
    writers = preset_writer_functions(mutated)
    assert "future_unregistered_writer" in writers, "新写面没被普查到 ⇒ 本元守卫是空断言"
    assert set(writers) != set(GUARDED_PRESET_WRITERS), "未登记的新写面没让登记集合变化"

    guard_anchor = 'preset_has_uncommitted_drift "$wt"'
    assert src.count(guard_anchor) == 1, f"锚不唯一（现取 {src.count(guard_anchor)} 处）⇒ 红证会打偏"
    stripped = preset_writer_functions(src.replace(guard_anchor, "true", 1))
    assert "preset_has_uncommitted_drift" not in stripped["discard_preset_snapshot"], (
        "把守卫调用换成 `true` 后登记项仍「合规」⇒ 本判据只看名字不看调用，是空断言"
    )


# ── 行为级变异：**改坏 ⇒ 必须红**（含「只改注释」对照） ───────────────────────────────────
ZERO_DRIFT_GUARD = 'if ! preset_has_uncommitted_drift "$wt"; then'
REFRESH_GUARD = 'if preset_touched_by_branch "$wt"; then'
DRIFT_REFUSAL = 'if [ "$drifted" = "1" ]; then'
REBASE_CALL = 'if ! git -C "$path" rebase origin/main; then'


def _advance_main(repo: Path, wt: Path) -> None:
    """让 origin/main 前进一格（一个非预设文件 + 一个**本分支没碰过**的预设文件）⇒ 分支真的 behind。"""
    (repo / "MAIN-ONLY.txt").write_text("main only\n", encoding="utf-8")
    (repo / ".agent-presets" / "migao" / "MAIN-ONLY.yml").write_text("from: main\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", MAIN_ADVANCE_MSG)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _git(wt, "rev-list", "--count", "HEAD..origin/main").stdout.strip() == "1", "夹具没造出 behind"


def _mutated_repo(dir_path: Path, mutate, *, behind: bool = False):
    """建夹具（可先让 main 前进）→ 把脚本换成变异版本 → **读回自证**。→ (repo, env, wt)。"""
    repo, env, wt = _make_preset_pr(dir_path)
    if behind:
        _advance_main(repo, wt)
    target = repo / "scripts" / "dev-worktree.sh"
    src = target.read_text(encoding="utf-8")
    mutated = mutate(src)
    assert mutated != src, "变异未生效（自证失败 ⇒ 本红证是空断言）"
    target.write_text(mutated, encoding="utf-8")
    assert target.read_text(encoding="utf-8") == mutated, "变异没真正落到被判对象上（读回不一致）"
    return repo, env, wt


def _neutralize(anchor: str, replacement: str = "if false; then"):
    """把某条守卫的条件行换掉（守卫**永不生效**；锚必须唯一 —— 不唯一即 fail-closed 报错）。"""
    def mutate(src: str) -> str:
        assert src.count(anchor) == 1, f"锚不唯一（现取 {src.count(anchor)} 处）：{anchor!r}"
        return src.replace(anchor, replacement, 1)
    return mutate


def test_mutation_dropping_the_zero_drift_guard_brings_the_false_block_back(tmp_path):
    """M1（改坏 ⇒ 必红）：零漂移守卫失效 ⇒ ④ 的假阻塞**原样回来**（命中「拒绝自动丢弃」分支）。"""
    repo, env, _wt = _mutated_repo(tmp_path / "m1", _neutralize(ZERO_DRIFT_GUARD))
    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode != 0, "守卫失效后 0-behind 分支仍被放行 ⇒ 本判据没钉住该分支"
    assert "拒绝自动丢弃" in (out.stdout + out.stderr), "命中分支不是「拒绝自动丢弃」⇒ 红证打偏"


def test_mutation_dropping_the_refresh_guard_loses_the_worktree_copy(tmp_path):
    """M2（改坏 ⇒ 必红）：刷新守卫失效 ⇒ 分支产物被 origin/main 覆盖（工作区出现「改回去」的暂存改动）。"""
    repo, env, wt = _mutated_repo(tmp_path / "m2", _neutralize(REFRESH_GUARD))
    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode == 0, "本变异不该改变 rc（它改的是 rebase **之后**的刷新面）"
    assert _git(wt, "status", "--porcelain").stdout.strip() != "", (
        "刷新守卫失效后工作区仍干净 ⇒ 该守卫没被钉住（它正是「逐字节保留」的那一半）"
    )
    for p in PRESET_PATHS_IN_MAIN:
        assert _worktree_sha(wt, p) != _sha(wt, f"HEAD:{p}"), (
            f"刷新守卫失效后工作区的 {p} 仍等于分支提交内容 ⇒ M2 是空断言"
        )


def test_mutation_skipping_the_rebase_leaves_the_branch_behind(tmp_path):
    """M3（改坏 ⇒ 必红）：把 rebase 调用换掉（=「干脆不 rebase」）⇒ ⑤ 的分支仍 behind（命中「真 behind」分支）。"""
    repo, env, wt = _mutated_repo(tmp_path / "m3", _neutralize(REBASE_CALL, replacement="if ! true; then"),
                                 behind=True)
    _script(repo, "rebase", "presetpr", env=env, check=False)
    assert _git(wt, "rev-list", "--count", "HEAD..origin/main").stdout.strip() == "1", (
        "把 rebase 换掉后分支竟已跟上 origin/main ⇒ ⑤ 的「仍走 rebase」是空断言"
    )


def test_mutation_disabling_the_refusal_makes_the_drift_guard_vacuous(tmp_path):
    """M4（改坏 ⇒ 必红）：把「拒绝自动丢弃」那段关掉 ⇒ ⑥ 的具名断言失配（守卫本身是否载重）。"""
    repo, env, wt = _mutated_repo(tmp_path / "m4", _neutralize(DRIFT_REFUSAL))
    wip = "# 在办改动（未提交）\n"
    (wt / PRESET_SKILL).write_text(wip, encoding="utf-8")
    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert "拒绝自动丢弃" not in (out.stdout + out.stderr), (
        "关掉拒绝分支后仍打印「拒绝自动丢弃」⇒ 该文案另有来源，⑥ 的具名断言打偏"
    )


def test_comment_only_mutation_keeps_the_flow_green(tmp_path):
    """对照读数：**只改注释** ⇒ 不起任何作用（判据判的是语义，不是「文件变了没有」）。"""
    def mutate(src: str) -> str:
        anchor = ZERO_DRIFT_GUARD
        assert src.count(anchor) == 1, "锚不唯一"
        return src.replace(anchor, f"# 对照：只改注释（不得影响任何判定）\n{anchor}", 1)

    repo, env, wt = _mutated_repo(tmp_path / "control", mutate)
    out = _script(repo, "rebase", "presetpr", env=env, check=False)
    assert out.returncode == 0 and "拒绝自动丢弃" not in (out.stdout + out.stderr), (
        f"只改注释不该改变行为：rc={out.returncode}\n{out.stdout}"
    )
    assert _git(wt, "status", "--porcelain").stdout.strip() == "", "只改注释不该让工作区变脏"


# ── 覆盖面登记的承载体 ────────────────────────────────────────────────────────────────
#: 覆盖面节里的锚形态：`<仓库相对路径>::<符号>`（**不写行号** —— 行号会腐，见 `FM-A10`）。
FACE_RE = re.compile(r"`([\w./-]+\.(?:sh|py|md|json))::([\w.-]+)`")
BOUNDARY_HEADING = "## 覆盖面登记"


def boundary_faces(doc: str) -> list[tuple[str, str]]:
    """→ 覆盖面节里现取到的 `(路径, 符号)` 清单（纯函数 ⇒ 真文本与变异文本走同一条判据）。"""
    start = doc.find(BOUNDARY_HEADING)
    if start < 0:
        raise AssertionError(f"覆盖面登记节不存在（{BOUNDARY_HEADING}）⇒ 覆盖不到什么没有落点")
    rest = doc[start + len(BOUNDARY_HEADING):]
    nxt = rest.find("\n## ")
    section = rest if nxt < 0 else rest[:nxt]
    return FACE_RE.findall(section)


def boundary_violations(doc: str) -> list[str]:
    """→ 违规清单（空 = 覆盖面登记的每条锚都解析得到，且条数够）。"""
    faces = boundary_faces(doc)
    bad = [] if len(faces) >= 3 else [f"覆盖面登记只点了 {len(faces)} 个可解析的面（< 3）⇒ 覆盖面写成散文了"]
    for path, symbol in faces:
        p = REPO_ROOT / path
        if not p.is_file():
            bad.append(f"覆盖面登记点名的路径不存在：{path}")
        elif symbol not in p.read_text(encoding="utf-8"):
            bad.append(f"覆盖面登记点名的锚解析不到：{path}::{symbol}")
    return bad


def test_coverage_boundary_faces_resolve():
    """覆盖面登记**被判据钉住**：每条锚都要能解析（防「写成散文就算登记」），并给注入式红证。"""
    doc = __doc__ or ""
    assert boundary_violations(doc) == [], "\n".join(boundary_violations(doc))

    bogus = doc.replace("`scripts/dev-worktree.sh::cmd_add`", "`scripts/dev-worktree.sh::no_such_symbol_xyz`", 1)
    assert bogus != doc, "变异注入未生效（自证失败）"
    assert any("解析不到" in v for v in boundary_violations(bogus)), (
        "把锚换成不存在的符号后判据没报错 ⇒ 本判据是空断言"
    )
    with pytest.raises(AssertionError):
        boundary_violations(bogus[: bogus.find(BOUNDARY_HEADING)])
