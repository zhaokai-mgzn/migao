# case_ids: MC-138
"""`scripts/dev-worktree.sh` 的「自动收尾（真删）」必须判**活占用**（issue #7008）。

## 病灶（2026-10-16 实测，逐字读数）

`:8101` 的 ai-agent 评测实例 `/health` = **200**，而 `lsof -p 30645 | grep cwd` 指向
`…/migao-wt/6985-confirm-execute/backend/ai-agent-service` —— 该目录**已被自动收尾删掉** ⇒
创建会话 **HTTP 500**（惰性 import 在已删的 cwd 上失败）。⇒「进程健康」与「进程可用」**脱钩**，
且症状把人引向**产品代码**（本次排查用了 3 轮读数才发现是 cwd 被删）。
根因：`dev-worktree.sh add` 内的自动收尾只判「GitHub 侧：有已合并 PR 且无 open PR」，
**从不问本机有没有进程正在用它**（见 `scripts/issue_lifecycle.py::classify_candidate`）。

## 判据（每条都会红；红证方式逐条写明）

| # | 判据 | 红证 |
|---|---|---|
| ① | 真进程 cwd 落在临时 worktree 内 ⇒ 拒删 + **报出 pid/cwd** | 物理摘掉 `live_occupants` 调用（变异副本）⇒ 同一夹具变「可收尾」 |
| ② | 有**未提交改动** / **未推送提交** ⇒ 拒删（具名） | 单变量对照：同一个 worktree 推上去之后 ⇒ 允许 |
| ③ | 干净且无占用 ⇒ **允许**（负控，防「一律拒删」的假修） | 若把 ① 改成恒拒，本条必红 |
| ④ | 端到端：`reap-merged --apply` 与 `dev-worktree.sh add` 都**不删**被占用的 worktree；占用消失后**仍会真删**（对照臂） | 同 ① |
| ⑤ | 变异自证：注入后源码确实变了、且仍是合法 Python（否则「红」来自语法错） | —— |
| ⑥ | `add` 的自动收尾 = **先 dry-run 打印、再真删**（`--force` 只跳过打印，不跳过拒绝条件） | 调换两段 / 去掉 `--apply` ⇒ 结构判据红 |
| ⑦ | **类级元守卫（§23）**：仓内**所有会删 worktree 的入口**必须登记（未登记即红 / 台账里有已消失的入口也红）；登记为**自动面**的入口必须走三条活占用保护 | 注入一个未登记的新删除入口 / 从 `classify_candidate` 摘掉 `live_occupants` ⇒ 元守卫各自单独红 |

夹具一律建在 **`tmp_path` 下的真 git 仓库 + 真 bare origin + 真 worktree**，占用者是**真子进程**
（`Popen(cwd=<worktree>)`）—— **绝不**碰任何真实 worktree（本包自己就跑在一个 worktree 里）。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"
GUARD_MODULE = REPO_ROOT / "scripts" / "agent-presets-guard.py"
DEV_WORKTREE = REPO_ROOT / "scripts" / "dev-worktree.sh"
ISSUE_LIFECYCLE_SH = REPO_ROOT / "scripts" / "issue-lifecycle.sh"

GIT_USER_ENV = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


@pytest.fixture(autouse=True)
def _isolate_machine_readings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """锁面 / 活锚 / 工作区根一律指向 tmp —— 否则判据读的是**本机真实状态**（不可复现）。"""
    monkeypatch.setenv("MIGAO_HEAVY_LOCK_FILE", str(tmp_path / "no-heavy.lock"))
    monkeypatch.setenv("MIGAO_ANCHOR", str(tmp_path / "no-anchor"))
    monkeypatch.setenv("MIGAO_WT_BASE", str(_r(tmp_path) / "wt"))


# ── 小工具 ────────────────────────────────────────────────────────────────────

def _r(path: Path) -> Path:
    """归一化（macOS 的 `/var` → `/private/var`：lsof 报的是真实路径，比较前必须同一坐标系）。"""
    return Path(path).resolve()


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("issue_lifecycle_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载被测模块（判定本体缺失即门禁空转）：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(GIT_USER_ENV)
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"fixture git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def _mk_repo(tmp_path: Path) -> Path:
    """真 bare origin + 真工作仓库（main 已推送）——**全部在 tmp_path 下**。"""
    bare = _r(tmp_path) / "origin.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q")
    repo = _r(tmp_path) / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _mk_worktree(repo: Path, tmp_path: Path, branch: str, *, push: bool = True) -> Path:
    """真 worktree（默认已推送 ⇒ 「干净且已推送」的基线）。"""
    wt_base = _r(tmp_path) / "wt"
    wt_base.mkdir(parents=True, exist_ok=True)
    path = wt_base / branch.replace("/", "-")
    _git(repo, "branch", branch, "main")
    _git(repo, "worktree", "add", str(path), branch)
    if push:
        _git(repo, "push", "-q", "-u", "origin", branch)
    return path


def _classify(mod, path: Path, branch: str, *, merged: bool = True, occupancy=None,
              heavy_lock=None):
    """走**真实** `classify_candidate`（不 mock 被测函数；只喂真实夹具与真实读数）。"""
    cand = mod.Candidate(branch, path=path)
    return mod.classify_candidate(
        cand, {branch} if merged else set(), {}, set(), [], set(), set(),
        Path(path).parent, occupancy=occupancy, heavy_lock=heavy_lock)


def _snapshot(mod):
    snap = mod.occupancy_snapshot()
    assert isinstance(snap, list), (
        "占用探针不可用（取不到 /proc 或 lsof ⇒ 契约值是 None）—— 判据必须报「无法判定」，"
        f"不得静默当没人用：{snap!r}")
    assert all(isinstance(o, mod.Occupant) for o in snap), "快照条目必须都是 Occupant（探针的返回契约）"
    return snap


def _spawn_cwd_holder(path: Path) -> subprocess.Popen:
    """真进程、其 cwd 落在 worktree 内（issue #7008 的**病灶本体**）。"""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(path))


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=30)


def _wait_occupant(mod, path: Path, pid: int, timeout: float = 20.0):
    """等真进程出现在快照里（探针是采样，不是实时订阅）。"""
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        snap = _snapshot(mod)
        hits = mod.live_occupants(path, snap)
        assert isinstance(hits, list), (
            f"占用面无法判定（契约值是 None，实际 {hits!r}）⇒ 不得把「读不到」当「没人用」：{path}")
        if any(h.pid == pid for h in hits):
            return snap
        last = hits
        time.sleep(0.1)
    raise AssertionError(f"夹具进程 {pid} 的 cwd 没被探针读到（现场命中：{last}）")


def _wait_no_occupant(mod, path: Path, timeout: float = 20.0):
    """等占用面变干净（macOS 的 Spotlight 等后台进程可能瞬时打开夹具文件 —— 那是真读数，不是假绿）。"""
    deadline = time.time() + timeout
    hits = []
    while time.time() < deadline:
        snap = _snapshot(mod)
        hits = mod.live_occupants(path, snap)
        assert isinstance(hits, list), (
            f"占用面无法判定（契约值是 None，实际 {hits!r}）⇒ 「干净」不许由无法判定推出：{path}")
        if not hits:
            return snap
        time.sleep(0.2)
    raise AssertionError(f"夹具 worktree 间歇被后台进程占用（现象真实，不掩盖）：{[h.line() for h in hits]}")


def _worktree_paths(repo: Path) -> list[str]:
    out = _git(repo, "worktree", "list", "--porcelain").stdout
    return [line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")]


def _branches(repo: Path) -> set[str]:
    return {line.strip() for line in _git(repo, "branch", "--format=%(refname:short)").stdout.splitlines()
            if line.strip()}


def _remote_branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)").stdout
    return {line.split("/", 1)[1] for line in out.splitlines() if "/" in line}


# ── ① 活占用 ⇒ 拒删 + 报出 pid（会红：见 ④）─────────────────────────────────────

def test_live_process_cwd_inside_worktree_refuses_reap(tmp_path: Path):
    mod = _load_module(MODULE)
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/in-use")
    holder = _spawn_cwd_holder(wt)
    try:
        snap = _wait_occupant(mod, wt, holder.pid)
        ok, key, why = _classify(mod, wt, "fix/in-use", occupancy=snap)
        assert ok is False, "有活进程 cwd 落在该 worktree 内 ⇒ **不得**判可收尾"
        assert key == "活占用", f"拒删原因必须具名到「活占用」这一条（实际 {key}：{why}）"
        assert f"pid {holder.pid}" in why, f"必须报出是谁在用：{why}"
        assert "cwd" in why, f"必须说明占用方式（cwd / 打开文件）：{why}"
        assert str(wt) in why, f"必须给出落在哪个路径：{why}"
    finally:
        _stop(holder)
    # 同一夹具、只把占用进程去掉 ⇒ 判据必须转「可收尾」（负控：拒删不是恒拒）
    snap = _wait_no_occupant(mod, wt)
    ok, key, _why = _classify(mod, wt, "fix/in-use", occupancy=snap)
    assert (ok, key) == (True, "可收尾"), "干净且无占用仍被拒 ⇒ 功能被删瘫"


# ── ② 未提交 / 未推送 ⇒ 拒删（单变量对照）──────────────────────────────────────

def test_uncommitted_change_refuses_reap(tmp_path: Path):
    mod = _load_module(MODULE)
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/dirty")
    (wt / "stray.txt").write_text("未提交的改动\n", encoding="utf-8")
    snap = _wait_no_occupant(mod, wt)
    ok, key, why = _classify(mod, wt, "fix/dirty", occupancy=snap)
    assert ok is False, "有未提交改动 ⇒ 不许删（删了就是丢工作）"
    assert key == "有未提交/未推送内容", f"原因必须具名（实际 {key}：{why}）"
    assert "未提交改动" in why and "stray.txt" in why, f"必须指名是哪个文件：{why}"
    assert mod.worktree_git_hygiene(wt) is not None


def test_unpushed_commit_refuses_reap_and_push_clears_it(tmp_path: Path):
    mod = _load_module(MODULE)
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/unpushed")
    _git(wt, "commit", "-q", "--allow-empty", "-m", "只在本地的一次提交")
    snap = _wait_no_occupant(mod, wt)
    ok, key, why = _classify(mod, wt, "fix/unpushed", occupancy=snap)
    assert ok is False, "有未推送提交 ⇒ 不许删"
    assert key == "有未提交/未推送内容", f"原因必须具名（实际 {key}：{why}）"
    assert "未推送提交" in why, f"必须说明是「未推送」：{why}（未提交与未推送不是同一件事）"
    # 对照臂：只把提交推上去（单变量）⇒ 同一条判据放行
    _git(wt, "push", "-q", "origin", "fix/unpushed")
    ok2, key2, _why2 = _classify(mod, wt, "fix/unpushed", occupancy=snap)
    assert (ok2, key2) == (True, "可收尾"), "推送后仍被拒 ⇒ 判据与「未推送」这个变量无关（假红）"


# ── ③ 干净且无占用 ⇒ 允许（负控）──────────────────────────────────────────────

def test_clean_unoccupied_worktree_is_allowed(tmp_path: Path):
    mod = _load_module(MODULE)
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/clean")
    snap = _wait_no_occupant(mod, wt)
    assert mod.live_occupants(wt, snap) == []
    assert mod.worktree_git_hygiene(wt) is None, "干净已推送的基线不该被判有未提交/未推送内容"
    ok, key, why = _classify(mod, wt, "fix/clean", occupancy=snap)
    assert (ok, key) == (True, "可收尾"), f"负控失败：干净且无占用被拒 ⇒ 自动收尾被挡死（{why}）"


# ── ④ 红证：物理摘掉活占用检测 ⇒ ① 的夹具变成「可收尾」（判据 ① 必红）──────────

def test_red_proof_removing_live_occupancy_detection_makes_it_reapable(tmp_path: Path):
    """**注入式红证**：把 `live_occupants` 那一行从源码里物理摘掉 ⇒ 判据 ① 必红。

    （不是 monkeypatch：变异落在**真源码的副本**上 ⇒ 证明的是「这条判据依赖那段检测」，
    而不是「测试替身能改结果」。）
    """
    source = MODULE.read_text(encoding="utf-8")
    anchor = "        occupants = live_occupants(c.path, occupancy)\n"
    assert source.count(anchor) == 1, f"注入锚点必须恰好命中 1 次（源码漂移 ⇒ 红证失效）：{anchor!r}"
    mutated = source.replace(
        anchor, "        occupants = []  # 注入：删掉「活占用检测」（issue #7008 红证）\n")
    assert mutated != source, "变异没落到源码上"

    dest = tmp_path / "mutated"
    dest.mkdir()
    target = dest / "issue_lifecycle.py"
    target.write_text(mutated, encoding="utf-8")
    shutil.copy(GUARD_MODULE, dest / "agent-presets-guard.py")
    compile(mutated, str(target), "exec")  # 自证 ⑤：变异后仍是合法 Python（红不许来自语法错）
    mut = _load_module(target)

    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/in-use")
    holder = _spawn_cwd_holder(wt)
    try:
        snap = _wait_occupant(mut, wt, holder.pid)
        ok, key, why = _classify(mut, wt, "fix/in-use", occupancy=snap)
        assert ok is True, (
            "摘掉活占用检测后同一夹具**必须**变成「可收尾」—— 否则判据 ① 是空断言"
            f"（现场：key={key} why={why}）")
        assert key == "可收尾"
    finally:
        _stop(holder)

    # 反向对照：**未变异**的真模块在同一夹具上必须拒删（证明上面的红不是夹具问题）
    mod = _load_module(MODULE)
    holder = _spawn_cwd_holder(wt)
    try:
        snap = _wait_occupant(mod, wt, holder.pid)
        ok, key, _why = _classify(mod, wt, "fix/in-use", occupancy=snap)
        assert (ok, key) == (False, "活占用")
    finally:
        _stop(holder)


# ── ⑤ 持有中的机器级重活锁 ⇒ 拒删（与「锁在别处 / 陈旧锁」两条负控）──────────────

def test_heavy_lock_held_on_worktree_refuses_reap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _load_module(MODULE)
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/locked")
    lock = tmp_path / "heavy.lock"
    lock.write_text(
        f"name=gate\npid={os.getpid()}\nstarted_at=0\nworktree={wt}\ncwd={_r(tmp_path)}\n",
        encoding="utf-8")
    monkeypatch.setenv("MIGAO_HEAVY_LOCK_FILE", str(lock))
    snap = _wait_no_occupant(mod, wt)
    ok, key, why = _classify(mod, wt, "fix/locked", occupancy=snap)
    assert ok is False, "该 worktree 上有持有中的重活锁 ⇒ 不许删"
    assert key == "持有重活锁", f"原因必须具名（实际 {key}：{why}）"
    assert "gate" in why and str(wt) in why, f"必须指名锁的持有者与落点：{why}"

    # 负控 1：锁在**别的** worktree ⇒ 与本次候选无关（不许把「有锁」一律读成「不许删」）
    elsewhere = _r(tmp_path) / "elsewhere"
    elsewhere.mkdir()
    lock.write_text(f"name=gate\npid={os.getpid()}\nworktree={elsewhere}\ncwd={elsewhere}\n",
                    encoding="utf-8")
    ok, key, _why = _classify(mod, wt, "fix/locked", occupancy=snap)
    assert (ok, key) == (True, "可收尾"), "锁落在别的工作区也被当成占用 ⇒ 判据过宽（假红）"

    # 负控 2：持有者已退出（陈旧锁）⇒ 不构成占用（下一个 acquire 会回收它）
    lock.write_text(f"name=gate\npid=999999\nworktree={wt}\ncwd={wt}\n", encoding="utf-8")
    ok, key, _why = _classify(mod, wt, "fix/locked", occupancy=snap)
    assert (ok, key) == (True, "可收尾"), "陈旧锁（PID 已退出）不该挡住收尾"


# ── ⑥ 端到端：真 `reap-merged --apply` / 真 `dev-worktree.sh add` ────────────────

_GH_STUB = '''#!/usr/bin/env python3
"""替身 gh：`pr list --state all` 回我们这条**已合并**读数（其余一律回 []）。"""
import json, sys

branch = "__BRANCH__"
if sys.argv[1:3] == ["pr", "list"]:
    print(json.dumps([{"number": 4242, "state": "MERGED", "headRefName": branch,
                       "baseRefName": "main"}]))
    sys.exit(0)
print("[]")
sys.exit(0)
'''


def _install_repo_scripts(repo: Path) -> Path:
    """把**真脚本**拷进夹具仓库（避免误操作真实仓库的 worktree —— 这是本包的红线）。"""
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    for src, name in ((DEV_WORKTREE, "dev-worktree.sh"), (ISSUE_LIFECYCLE_SH, "issue-lifecycle.sh"),
                      (MODULE, "issue_lifecycle.py"), (GUARD_MODULE, "agent-presets-guard.py")):
        shutil.copy(src, scripts / name)
    return scripts


def _runtime_env(tmp_path: Path, branch: str) -> dict[str, str]:
    stub = _r(tmp_path) / "gh-stub"
    stub.write_text(_GH_STUB.replace("__BRANCH__", branch), encoding="utf-8")
    stub.chmod(0o755)
    home = _r(tmp_path) / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(GIT_USER_ENV)
    env.update({
        "MIGAO_GH_BIN": str(stub),
        "MIGAO_WT_BASE": str(_r(tmp_path) / "wt"),
        "MIGAO_ANCHOR": str(_r(tmp_path) / "no-anchor"),
        "MIGAO_HEAVY_LOCK_FILE": str(_r(tmp_path) / "no-heavy.lock"),
        "HOME": str(home),  # 隔离：不读本机 git 全局配置 / 不读本机重活锁
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    return env


def _run(script: Path, args: list[str], repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], cwd=str(repo),
                          capture_output=True, text=True, env=env, timeout=300)


def test_reap_apply_keeps_worktree_in_use_and_reaps_it_after(tmp_path: Path):
    repo = _mk_repo(tmp_path)
    wt = _mk_worktree(repo, tmp_path, "fix/in-use")
    scripts = _install_repo_scripts(repo)
    env = _runtime_env(tmp_path, "fix/in-use")
    holder = _spawn_cwd_holder(wt)
    try:
        time.sleep(0.3)
        proc = _run(scripts / "issue-lifecycle.sh", ["reap-merged", "--apply"], repo, env)
        assert proc.returncode == 0, f"reap 本身不得因拒删而判红：\n{proc.stdout}\n{proc.stderr}"
        assert wt.is_dir(), "**活进程在用 ⇒ 真删不得发生**（issue #7008 的病灶）"
        assert f"pid {holder.pid}" in proc.stdout, f"输出必须具名报出占用者：\n{proc.stdout}"
        assert "活占用" in proc.stdout, f"输出必须点名是哪一条拒绝条件：\n{proc.stdout}"
        assert str(_r(wt)) in _worktree_paths(repo) or str(wt) in _worktree_paths(repo)
        assert "fix/in-use" in _branches(repo), "拒删必须**整条候选**不动（分支也不许删）"
        assert "fix/in-use" in _remote_branches(repo), "拒删必须连远程分支也不动"
    finally:
        _stop(holder)

    # 对照臂 B（同一夹具、同一命令，只去掉占用进程）⇒ 必须**真删**（证明没把功能删瘫）
    proc2 = _run(scripts / "issue-lifecycle.sh", ["reap-merged", "--apply"], repo, env)
    assert proc2.returncode == 0, f"占用消失后收尾应成功：\n{proc2.stdout}\n{proc2.stderr}"
    assert not wt.exists(), f"无占用仍不删 ⇒ 自动收尾被挡死：\n{proc2.stdout}"
    assert "fix/in-use" not in _branches(repo)
    assert "fix/in-use" not in _remote_branches(repo)


def test_dev_worktree_add_does_not_delete_a_worktree_in_use(tmp_path: Path):
    """病灶的**原始触发路径**：`add` 里的自动收尾（issue #7008 实测就是它删的）。"""
    repo = _mk_repo(tmp_path)
    stale = _mk_worktree(repo, tmp_path, "fix/in-use")
    scripts = _install_repo_scripts(repo)
    env = _runtime_env(tmp_path, "fix/in-use")
    _git(repo, "branch", "fix/newcomer", "main")

    holder = _spawn_cwd_holder(stale)
    try:
        time.sleep(0.3)
        proc = _run(scripts / "dev-worktree.sh", ["add", "fix/newcomer"], repo, env)
        assert proc.returncode == 0, f"add 不得被自动收尾影响：\n{proc.stdout}\n{proc.stderr}"
        assert (_r(tmp_path) / "wt" / "newcomer").is_dir(), "新工作区没建出来"
        assert stale.is_dir(), "**add 不得删掉正被活进程使用的 worktree**（这就是 #7008 的病灶）"
        assert f"pid {holder.pid}" in proc.stdout
        assert "活占用" in proc.stdout
        # 安全顺序：先 dry-run 预演（零删除）再真删 —— 两段都必须在输出里可见。
        # 🔴 锚用**模式令牌 / CLI 旗标**（`dry-run` / `APPLY`：issue_lifecycle.py 的 mode 常量、
        #    dev-worktree.sh 的两次 argv），**不拿中文文案当结构位置**（issue #6802 同族：同一句文案
        #    出现在更靠前的位置就会把位置判据带偏）。argv 的静态顺序判据见
        #    test_add_runs_dry_run_before_apply_and_documents_force（锚 = `reap-merged --no-artifacts` /
        #    `reap-merged --apply`，同样是代码面旗标）。
        assert proc.stdout.count("dry-run") == 1, f"自动收尾缺「dry-run 预演」这一段：\n{proc.stdout}"
        assert proc.stdout.count("APPLY") == 1, f"自动收尾缺「APPLY 真删」这一段：\n{proc.stdout}"
        assert proc.stdout.index("dry-run") < proc.stdout.index("APPLY"), (
            f"顺序错：必须先 dry-run 预演、再 APPLY 真删（顺序即安全顺序）：\n{proc.stdout}")
    finally:
        _stop(holder)


# ── ⑦ 类级元守卫（§23）：所有「删 worktree」入口必须登记；自动面必须走三条活占用保护 ──
#
# 为什么需要它（铁律 8）：本单修的是 `dev-worktree.sh add` 触发的那条自动收尾，
# 而仓内**还有别的**删 worktree 入口（显式 `finish` / `prune --apply` / `dev-worktree.sh rm` /
# batch-gate 与新鲜度检查的**自建自删**临时 worktree）。逐个手改不可持续 ⇒ 登记表 + 双向判据：
#   · 扫出来的入口 ⇄ 登记表**双向相等**（新入口未登记 ⇒ 红；台账里有已消失的入口 ⇒ 红）；
#   · 登记为「自动面」的入口，判定本体里必须**真的**含三条活占用保护调用（摘掉即红）。

SCRIPTS_DIR = REPO_ROOT / "scripts"
#: 删除原语本身不是「入口」（它只被入口调用）；扫动词时排除，避免把 primitives 当成候选。
DELETE_PRIMITIVES = {"remove_worktree"}
#: 三条活占用保护（issue #7008）—— 自动面必须同时具备。
GUARD_CALLS = ("live_occupants(", "worktree_git_hygiene(", "heavy_lock_holder(")

WORKTREE_DELETE_LEDGER: dict[str, str] = {
    "scripts/issue_lifecycle.py::cmd_reap_merged":
        "**自动面**（`dev-worktree.sh add` 每次建工作区都会触发）⇒ 必须走三条活占用保护（判据 ①~⑤ 钉住）",
    "scripts/issue_lifecycle.py::cmd_finish":
        "显式面：目标由操作者用参数点名（收尾自己的包）⇒ 不在自动半径内，有意不加活占用硬闸",
    "scripts/issue_lifecycle.py::cmd_prune":
        "显式面：默认 dry-run、`--apply` 才删、逐目标由操作者确认 ⇒ 同上",
    "scripts/dev-worktree.sh::cmd_rm":
        "显式面：`rm <分支|路径>` 由操作者当场指定目标 ⇒ 同上",
    "scripts/batch-gate.sh::cleanup":
        "自建自删：batch-gate 自己 `mktemp` 出来的合并校验 worktree（`OWNS_WT=1` 才删）⇒ 不需要占用面",
    "scripts/generated_artifacts_freshness.py::base_probe":
        "自建自删：`base_probe` 自己创建的临时 worktree，`finally` 里删 ⇒ 不需要占用面",
}

#: shell 里真正的 `git … worktree remove` 命令（注释 / `echo` 文案里的**提及**不算）
_SHELL_DELETE_RE = re.compile(r"(^|[;&|]\s*|\$\(\s*)\s*git\b[^\n]*\bworktree\s+remove\b")
_SHELL_FUNC_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{")


def _is_worktree_remove_call(node: ast.Call) -> bool:
    """任何形如 `f(..., "worktree", "remove", ...)` 的调用（`git(...)` / `_git_rc(...)` 都算）。"""
    consts = {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return {"worktree", "remove"} <= consts


def _py_delete_sites(path: Path, src: str | None = None) -> set[str]:
    src = src if src is not None else path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    sites: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in DELETE_PRIMITIVES:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "remove_worktree" or _is_worktree_remove_call(child):
                sites.add(f"{path.relative_to(REPO_ROOT)}::{node.name}")
                break
    return sites


def _shell_delete_sites(path: Path) -> set[str]:
    sites: set[str] = set()
    current = "__file_scope__"
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = _SHELL_FUNC_RE.match(line)
        if matched:
            current = matched.group(1)
            continue
        if line.lstrip().startswith("#"):
            continue
        if _SHELL_DELETE_RE.search(line):
            sites.add(f"{path.relative_to(REPO_ROOT)}::{current}")
    return sites


def _scan_delete_sites(overrides: dict[Path, str] | None = None) -> set[str]:
    """扫盘；`overrides` = 内存里的变异副本（红证要在**变异后**的源码上判，不是读回磁盘）。"""
    overrides = overrides or {}
    sites: set[str] = set()
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        sites |= _py_delete_sites(path, overrides.get(path))
    for path in sorted(SCRIPTS_DIR.glob("*.sh")):
        sites |= _shell_delete_sites(path)
    return sites


def _function_source(tree: ast.AST, src: str, name: str) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


def _class_guard_problems(src: str, overrides: dict[Path, str] | None = None) -> list[str]:
    """类级判据本体：入口登记双向相等 + 自动面必须含三条活占用保护。"""
    problems: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"源码不是合法 Python（判据不得在语法错上「红」）：{exc}"]
    actual = _scan_delete_sites(overrides)
    unregistered = sorted(actual - set(WORKTREE_DELETE_LEDGER))
    disappeared = sorted(set(WORKTREE_DELETE_LEDGER) - actual)
    if unregistered:
        problems.append(f"**未登记**的删 worktree 入口：{unregistered}（新增删除动作必须登记并说明是否走活占用保护）")
    if disappeared:
        problems.append(f"**台账未兑现**（已不存在的入口仍被登记）：{disappeared}")
    if not actual:
        problems.append("源码里扫不到任何删 worktree 入口 ⇒ 判据对象没了（fail-closed，别静默绿）")
    block = _function_source(tree, src, "classify_candidate")
    if block is None:
        problems.append("找不到 `classify_candidate`（自动面的判定本体缺失）⇒ 判据无法成立")
    else:
        missing = [call for call in GUARD_CALLS if call not in block]
        if missing:
            problems.append(f"自动面缺少活占用保护：{missing}（摘掉 = 自动收尾又回到「只问 GitHub」）")
    return problems


def test_every_worktree_delete_entry_is_registered():
    source = MODULE.read_text(encoding="utf-8")
    problems = _class_guard_problems(source, {MODULE: source})
    assert problems == [], "类级元守卫判红：\n  - " + "\n  - ".join(problems)
    # 台账只许由**真实调用者**组成（不是装饰）：至少要有自动面那一条
    assert "scripts/issue_lifecycle.py::cmd_reap_merged" in WORKTREE_DELETE_LEDGER


def test_class_guard_goes_red_when_liveness_check_is_removed():
    """判别力自证：从 `classify_candidate` 摘掉 `live_occupants` 调用 ⇒ 元守卫必红且具名。"""
    src = MODULE.read_text(encoding="utf-8")
    anchor = "        occupants = live_occupants(c.path, occupancy)\n"
    assert src.count(anchor) == 1
    mutated = src.replace(anchor, "        occupants = []\n")
    problems = _class_guard_problems(mutated, {MODULE: mutated})
    assert any("live_occupants" in p for p in problems), f"摘掉活占用检测后必须红：{problems}"


def test_class_guard_goes_red_when_a_new_delete_entry_appears_unregistered():
    """判别力自证：注入一个**未登记**的删 worktree 入口 ⇒ 元守卫必红且具名。"""
    src = MODULE.read_text(encoding="utf-8")
    anchor = "\nclass Candidate:"
    assert src.count(anchor) == 1
    mutated = src.replace(
        anchor,
        "\ndef cmd_undeclared_delete():\n    remove_worktree('/tmp/x', Path('/tmp'))\n"
        "\n\nclass Candidate:")
    problems = _class_guard_problems(mutated, {MODULE: mutated})
    assert any("cmd_undeclared_delete" in p for p in problems), f"未登记的新入口必须红：{problems}"


# ── ⑧ 结构判据：`add` 的两段顺序 + `--force` 只跳过打印 ───────────────────────

def _cmd_add_body(script_text: str) -> str:
    start = script_text.index("\ncmd_add() {")
    end = script_text.index("\n}\n", start)
    return script_text[start:end]


def test_add_runs_dry_run_before_apply_and_documents_force():
    src = DEV_WORKTREE.read_text(encoding="utf-8")
    body = _cmd_add_body(src)
    dry = body.find("reap-merged --no-artifacts")
    apply = body.find("reap-merged --apply")
    assert dry >= 0, "`add` 缺少「先 dry-run 打印」那一段（零删除的预演）"
    assert apply >= 0, "`add` 缺少真删那一段（缺了 = 自动收尾恒为空转）"
    assert dry < apply, "顺序错：必须先 dry-run 打印、再真删（顺序即安全顺序）"
    assert "--force" in body, "`--force` 必须能显式跳过预演（否则大存量时每轮都多一次全量读数）"
    assert 'force}" = "0"' in body or 'force}" = "0"' in body, "预演必须受 --force 控制"
    header = "\n".join(src.splitlines()[:130])
    assert "7008" in header, "文件头必须写明本守卫的出处（issue #7008）"
    assert "先 dry-run" in header, "文件头必须写明自动收尾的默认顺序"
    for face in ("活进程", "未提交", "未推送", "重活锁"):
        assert face in header, f"文件头必须点名拒绝条件「{face}」"
