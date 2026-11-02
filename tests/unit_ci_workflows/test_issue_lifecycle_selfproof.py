# case_ids: MC-133
"""`scripts/issue_lifecycle.py` 的**自证面** —— 「拿旧读数证明新状态」这一形态（issue #6617）。

## 这守的是什么

`_REMOTE_HEADS` 是**进程内快照**。自证（`verify_clean`）若读它，「**缓存先被读过 → 远程才被删**」
这个顺序就会让自证拿**删除前**的值判「还在不在」，报出与最终态**相反**的结论 —— 而自证的全部
意义就是**最后读一次真值**（issue #6617 的形态；#6261 里该路径出现过「已删干净却报 ❌」）。

⇒ 三条要求（本文件逐条落判据）：

1. 自证走**强制现取**入口 `remote_heads_refresh()`，**不读快照**；
2. 读不到（网络 / 限流 / origin 不可达）⇒ **无法判定**（三态 `None` → `exit 3`），
   **不得**判成功（`3` 不得当 `0` 读），也**不得**判「未清」（`False` 同样是假陈述）；
3. 批量路径允许把**一次**现取的读数传进每个自证（`NS-3`：逐目标现取 = N 次往返），
   但那份读数**必须**是现取的 —— 传快照 ⇒ 判红。

## 判据分组（每组都能**单独**变红）

- ① **实例（会红）**：快照说「还在」、真值「已删」⇒ 自证必须判**干净**（读快照的实现必红）；
- ② **读不到 ⇒ 无法判定**：用**真失败**的 origin（指向不存在的路径，不是 mock 返回值）⇒
  模块级 `None` + CLI 出口 `exit 3`，且**不**打印「✅ 收尾完成」；
- ③ **红证（注入式）**：把源码里的现取那一行变异成读快照 ⇒ ① 的夹具**必红**（`False`）；
- ④ **类级元守卫（AST）**：自证不得读快照 / `heads=` 只许来自现取 / **任何改远程状态的路径都必须自证**
  —— 新增一条删除路径却忘了自证 ⇒ 红；含「判别力自证」（四种坏形态在合成语料上各自判红）；
- ⑤ **审计面**：`close` 的 dry-run 必须能看出「这一条会用什么依据关」（判定 → `--reason` 映射 + 证据原文，
  不再截断 110 字）；**零 gh 调用**（dry-run 仍是只读）；
- ⑥ **往返不变式**：传读数的自证 **0 次** `ls-remote`、默认自证 **恰好 1 次**（`NS-3` 不许被本修法破坏）。

夹具一律是 `tmp_path` 下的**真 git 仓库 + 真 bare origin**（不 mock git 语义）；「读不到」用
**真不可达的 origin** 造 —— mock 掉 git 等于把被测对象换成替身（`migao-acceptance` §19.1「绿了但没跑」）。
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"
GUARD_MODULE = REPO_ROOT / "scripts" / "agent-presets-guard.py"

#: 「自证宣称自己守的接线」—— §28.2 的显式声明（已登记
#: `tests/unit_ci_workflows/wiring_claims_ledger.json`；摘掉 `verify_clean` 的现取 ⇒ 判红）。
WIRING_UNDER_TEST = "scripts/issue_lifecycle.py::verify_clean"

#: 注入锚点：**逐字**取自 `scripts/issue_lifecycle.py`（唯一命中 1 次才允许变异）
REFRESH_LINE = "    heads_reading = remote_heads_refresh(cwd) if heads is _UNREAD else heads"
SNAPSHOT_LINE = "    heads_reading = remote_heads(cwd) if heads is _UNREAD else heads"


def _load_module(path: Path = MODULE):
    """按文件路径加载被测模块（`scripts/` 不是包，无法 import）。"""
    spec = importlib.util.spec_from_file_location("issue_lifecycle_selfproof", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载被测模块（判定本体缺失即门禁空转）：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def _remote_branches(cwd: Path) -> set[str]:
    out = _git(cwd, "ls-remote", "--heads", "origin").stdout
    return {line.split("refs/heads/", 1)[1].strip() for line in out.splitlines() if "refs/heads/" in line}


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, Path]:
    """真 bare origin + 真工作仓库（一次提交 + `origin/main`）—— 不是 mock。"""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True)
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "selfproof@example.invalid")
    _git(work, "config", "user.name", "selfproof")
    _git(work, "checkout", "-q", "-b", "main")
    (work / "README.md").write_text("bootstrap\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")
    return work, origin


def _stale_snapshot_target(module, work: Path) -> object:
    """「**快照说还在**、真值已删」的夹具（并在每个环节自证夹具是承重的）。

    顺序即病根：**先读快照** → **再删远程**（快照不刷新）⇒ 自证若读快照必然报 ❌。
    """
    branch = "fix/selfproof"
    _git(work, "branch", branch)
    _git(work, "push", "-q", "origin", branch)
    _git(work, "branch", "-D", branch)              # 本地分支先清掉（本地面不参与本判据）
    snapshot = module.remote_heads(work)            # ① 快照：此刻**还在**
    assert branch in snapshot, f"夹具失效：快照里没有该分支（{sorted(snapshot or [])}）"
    assert branch in module._REMOTE_HEADS[str(work)], "夹具失效：快照没有落到进程内缓存"
    _git(work, "push", "-q", "origin", "--delete", branch)   # ② 真值：已删
    assert branch in module._REMOTE_HEADS[str(work)], (
        "夹具失效：删除后缓存竟然自动变了 —— 那就测不出「自证读快照」这个形态")
    assert branch not in _remote_branches(work), "夹具失效：真值里该分支还在（删除没生效）"
    return module.Target(branch, None, False, False, True)


def _mutated_module(dest_dir: Path, anchor: str, replacement: str) -> Path:
    """把真源码里的 `anchor` **逐字**替换成 `replacement`，落成一份可独立加载的副本。

    自证三件（§23 G7）：① 锚点**恰好命中 1 次** ② 替换后源码确实变了 ③ 变异后仍是**合法 Python**
    （否则「红」来自语法错，不来自判据）。
    """
    src = MODULE.read_text(encoding="utf-8")
    assert src.count(anchor) == 1, f"注入锚点必须恰好命中 1 次（源码漂移 ⇒ 红证失效）：{anchor!r}"
    mutated = src.replace(anchor, replacement)
    assert mutated != src, "变异没落到源码上"
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "issue_lifecycle.py"
    target.write_text(mutated, encoding="utf-8")
    shutil.copy(GUARD_MODULE, dest_dir / "agent-presets-guard.py")
    compile(mutated, str(target), "exec")
    return target


# ══════════════════════════════════════════════════════════════════════════════
# ① 实例判据：自证读**删除后**的真值，不读删除前的快照（issue #6617 的靶子）
# ══════════════════════════════════════════════════════════════════════════════

def test_selfproof_reads_the_truth_not_the_snapshot(repo):
    """快照说「还在」、真值「已删」⇒ 自证必须判**干净**（读快照的实现必报 ❌）。"""
    module = _load_module()
    work, _origin = repo
    target = _stale_snapshot_target(module, work)

    verdict = module.verify_clean(target, work, work)

    assert verdict is True, (
        "自证必须读**删除后**的真值：快照里该分支还在、真值已不在 ⇒ 应判干净（True）。"
        f"实测 {verdict!r} —— False = 读了删除前的快照（就是本单的病），"
        "None = 读不到（夹具或实现有问题）")


def test_snapshot_reader_is_still_allowed_but_only_for_stale_ref_scan(repo):
    """对照读数：**快照入口本身还在**（它不是被删掉，而是被限定用途）—— 防「修法 = 删功能」。"""
    module = _load_module()
    work, _origin = repo
    _git(work, "branch", "keep-me")
    _git(work, "push", "-q", "origin", "keep-me")

    module._REMOTE_HEADS.clear()
    heads = module.remote_heads(work)

    assert heads == {"main", "keep-me"}, f"快照读数必须仍然是真集合（实测 {heads!r}）"
    assert module.remote_heads(work) is heads, "第二次读必须命中缓存（省往返的语义没变）"


# ══════════════════════════════════════════════════════════════════════════════
# ② 读不到 ⇒ **无法判定**（三态；`3` 不得当 `0`/`1` 读）
# ══════════════════════════════════════════════════════════════════════════════

def test_unreadable_remote_is_undecidable_not_success(repo):
    """origin **真不可达**（不是 mock）⇒ 模块级自证必须给 `None`（既不是 True 也不是 False）。"""
    module = _load_module()
    work, _origin = repo
    branch = "fix/unreadable"
    _git(work, "branch", branch)
    _git(work, "branch", "-D", branch)
    # 真失败：origin 指向一个不存在的仓库路径（两种读数——批量与逐分支——都会失败）
    _git(work, "remote", "set-url", "origin", str(work.parent / "gone.git"))
    target = module.Target(branch, None, False, False, True)

    verdict = module.verify_clean(target, work, work)

    assert verdict is None, (
        "远程读数取不到 ⇒ 自证必须给「无法判定」（None）："
        "True = 拿读不到当「已清」（自证说谎）；False = 拿读不到当「未清」（同样是假陈述）。"
        f"实测 {verdict!r}")


def test_finish_exits_3_when_the_selfproof_cannot_read(repo, monkeypatch, capsys):
    """**接线**（§28.2）：`cmd_finish` 必须把 `None` 传成 `exit 3`，且**不许**报「收尾完成」。"""
    module = _load_module()
    work, _origin = repo
    branch = "fix/finish-unreadable"
    _git(work, "branch", branch)
    _git(work, "remote", "set-url", "origin", str(work.parent / "gone.git"))
    monkeypatch.setattr(module, "branch_pr_merged", lambda b, c: True)   # 只换 GitHub 状态这一边界
    monkeypatch.chdir(work)

    rc = module.cmd_finish(argparse.Namespace(target=branch, dry_run=False))
    captured = capsys.readouterr()

    assert rc == module.EXIT_UNKNOWN == 3, (
        f"读不到远程真值 ⇒ 必须 exit 3（无法判定），实测 rc={rc}\n"
        f"--- stdout ---\n{captured.out}\n--- stderr ---\n{captured.err}")
    assert "✅ 收尾完成" not in captured.out, (
        "读不到真值却报了「收尾完成」= 自证说谎（自证的全部意义是最后读一次真值）："
        f"\n{captured.out}")
    assert "无法判定" in captured.out, f"没有出声说明「无法判定」：\n{captured.out}"


# ══════════════════════════════════════════════════════════════════════════════
# ③ 红证（注入式）：把自证改回读快照 ⇒ ① 的夹具**必红**
# ══════════════════════════════════════════════════════════════════════════════

def test_reverting_the_selfproof_to_the_snapshot_turns_it_red(repo, tmp_path):
    """注入：`remote_heads_refresh` → `remote_heads`（读快照）⇒ 同一夹具从 True 变 False。"""
    module = _load_module()
    work, _origin = repo
    target = _stale_snapshot_target(module, work)
    assert module.verify_clean(target, work, work) is True, "先自证靶子在当前实现下是绿的"

    mutant = _load_module(_mutated_module(tmp_path / "mut-snapshot", REFRESH_LINE, SNAPSHOT_LINE))
    mutant._REMOTE_HEADS[str(work)] = {target.branch}      # 注入快照：说「还在」
    verdict = mutant.verify_clean(target, work, work)

    assert verdict is False, (
        "把自证改回读快照后**必须**判红（False）—— 否则 ① 的绿不是「读了真值」挣来的（空断言）。"
        f"实测 {verdict!r}")


# ══════════════════════════════════════════════════════════════════════════════
# ④ 类级元守卫（AST）：同类进不来
# ══════════════════════════════════════════════════════════════════════════════

def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                out.add(func.id)
            elif isinstance(func, ast.Attribute):
                out.add(func.attr)
    return out


def _bound_from(node: ast.AST, target_name: str, source: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call) \
                and isinstance(sub.value.func, ast.Name) and sub.value.func.id == source:
            if any(isinstance(t, ast.Name) and t.id == target_name for t in sub.targets):
                return True
    return False


def _selfproof_problems(src: str) -> list[str]:
    """类级判据本体（纯函数，便于「判别力自证」）：返回**违规清单**，空 = 合规。

    三条不变式（issue #6617 的判据 2 + 铁律 8 的类级固化）：
    ① 自证不得读快照 / 可缓存读数；
    ② 传给自证的 `heads=` 必须由**现取**入口产出；
    ③ **任何改远程状态的函数都必须自证**（新增删除路径忘了自证 ⇒ 红）。
    """
    tree = ast.parse(src)
    problems: list[str] = []
    verify = _find_func(tree, "verify_clean")
    if verify is None:
        return ["找不到 `verify_clean`（自证本体不见了 —— 判定会静默变成空跑）"]

    called = _called_names(verify)
    if "remote_heads_refresh" not in called:
        problems.append("`verify_clean` 没有走 `remote_heads_refresh`（自证必须**现取**真值）")
    for bad in ("remote_heads", "remote_branch_gone"):
        if bad in called:
            problems.append(f"`verify_clean` 读了快照/可缓存读数 `{bad}`（自证不得读快照）")

    # ② `heads=` 参数的来源：只许是现取（直接调用，或在同一函数里由现取绑定）
    for func in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        for call in [n for n in ast.walk(func) if isinstance(n, ast.Call)]:
            if not (isinstance(call.func, ast.Name) and call.func.id == "verify_clean"):
                continue
            for kw in call.keywords:
                if kw.arg != "heads":
                    continue
                direct = (isinstance(kw.value, ast.Call)
                          and isinstance(kw.value.func, ast.Name)
                          and kw.value.func.id == "remote_heads_refresh")
                via_name = (isinstance(kw.value, ast.Name)
                            and _bound_from(func, kw.value.id, "remote_heads_refresh"))
                if not (direct or via_name):
                    problems.append(
                        f"`{func.name}` 把**非现取**的读数传给了自证（第 {call.lineno} 行）"
                        "—— `heads=` 只许来自 `remote_heads_refresh`")

    # ③ 改远程状态的路径必须自证
    deleters = {"delete_remote_branch", "batch_delete_remote_branches"}
    for func in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        touches_remote = bool(_called_names(func) & deleters)
        if touches_remote and "verify_clean" not in _called_names(func):
            problems.append(f"`{func.name}` 改了远程状态却没有自证（缺 `verify_clean`）")
    return problems


def test_class_guard_holds_on_the_real_module():
    """真源码必须合规（**且**扫描不是空跑：删除路径与自证调用点都得真的被看见）。"""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    deleters = {"delete_remote_branch", "batch_delete_remote_branches"}
    remote_paths = [f.name for f in tree.body
                    if isinstance(f, ast.FunctionDef) and (_called_names(f) & deleters)]
    selfproof_calls = [n for n in ast.walk(tree)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "verify_clean"]

    assert _selfproof_problems(src) == [], _selfproof_problems(src)
    assert remote_paths, "扫描面为空 ⇒ 判据失明（不是通过）：没找到任何改远程状态的函数"
    assert len(selfproof_calls) >= 2, f"自证调用点只找到 {len(selfproof_calls)} 个 ⇒ 扫描面可疑"


def test_class_guard_has_discriminating_power():
    """**判别力自证**：四种坏形态在合成语料上各自判红，合规语料判绿（不只判真源码）。"""
    good = """
def remote_heads(cwd, *, refresh=False):
    return set()
def remote_heads_refresh(cwd):
    return remote_heads(cwd, refresh=True)
def verify_clean(target, cwd, root, *, heads=None):
    reading = remote_heads_refresh(cwd)
    return reading is not None
def batch_delete_remote_branches(branches, cwd):
    return {}
def cmd_x(b, cwd):
    heads = remote_heads_refresh(cwd)
    verify_clean(None, cwd, cwd, heads=heads)
    batch_delete_remote_branches(b, cwd)
    verify_clean(None, cwd, cwd)
"""
    assert _selfproof_problems(good) == [], _selfproof_problems(good)

    reads_snapshot = good.replace(
        "    reading = remote_heads_refresh(cwd)",
        "    reading = remote_heads(cwd)")
    assert any("快照" in p for p in _selfproof_problems(reads_snapshot)), \
        _selfproof_problems(reads_snapshot)

    stale_heads = good.replace(
        "    heads = remote_heads_refresh(cwd)", "    heads = remote_heads(cwd)")
    assert any("非现取" in p for p in _selfproof_problems(stale_heads)), \
        _selfproof_problems(stale_heads)

    unproved_deletion = good.replace(
        "    heads = remote_heads_refresh(cwd)\n    verify_clean(None, cwd, cwd, heads=heads)\n"
        "    batch_delete_remote_branches(b, cwd)\n    verify_clean(None, cwd, cwd)",
        "    batch_delete_remote_branches(b, cwd)")
    assert any("没有自证" in p for p in _selfproof_problems(unproved_deletion)), \
        _selfproof_problems(unproved_deletion)

    missing_body = good.replace("def verify_clean(", "def verify_cleaX(")
    assert any("verify_clean" in p for p in _selfproof_problems(missing_body)), \
        _selfproof_problems(missing_body)


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 审计面：`close` 的 dry-run 能看出「这一条会用什么依据关」
# ══════════════════════════════════════════════════════════════════════════════

def _close_args(issue: int, reason: str, evidence: str) -> argparse.Namespace:
    return argparse.Namespace(issue=issue, reason=reason, evidence=evidence,
                              batch_file=None, apply=False, ack_unimplemented_registry=False)


def test_close_dry_run_shows_the_basis_for_each_close(tmp_path, monkeypatch, capsys):
    """dry-run 是**审计面**：判定 → `gh --reason` 映射 + 证据原文（不再截断）+ 闸门读数，且**零外部调用**。"""
    module = _load_module()

    def _no_run(argv, cwd, timeout=None):   # dry-run 一旦真跑 gh ⇒ 判据当场红（不是「看着没跑」）
        raise AssertionError(f"dry-run（默认零写）不得有外部调用，实测试图跑：{argv}")

    monkeypatch.setattr(module, "_run", _no_run)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "case-trust-unimplemented.json").write_text(
        json.dumps({"unimplemented": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    long_evidence = "PR #1234 merged 2026-11-03T00:00:00Z；" + "git show origin/main:scripts/issue_lifecycle.py ⇒ 命中" * 4

    rc = module.cmd_close(_close_args(6617, "delivered", long_evidence))
    delivered = capsys.readouterr()
    rc2 = module.cmd_close(_close_args(7999, "superseded", "被后续裁定取代：见 #8000"))
    superseded = capsys.readouterr()

    assert rc == 0 and rc2 == 0, (rc, rc2)
    assert "[dry] #6617" in delivered.out and "[dry] #7999" in superseded.out, delivered.out
    assert "gh issue close --reason completed" in delivered.out, (
        f"dry-run 必须显示**会用什么依据关**（delivered → completed）：\n{delivered.out}")
    assert "gh issue close --reason not planned" in superseded.out, (
        f"superseded → not planned 未显示：\n{superseded.out}")
    assert long_evidence in delivered.out, (
        "证据被截断了 —— 审计面看不到完整依据（原实现截到 110 字）："
        f"\n{delivered.out}")
    assert "未实装登记 未命中" in delivered.out, f"闸门读数缺失：\n{delivered.out}"


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ 往返不变式：传读数 ⇒ 0 次远程读；默认 ⇒ 恰好 1 次（`NS-3` 不许被本修法破坏）
# ══════════════════════════════════════════════════════════════════════════════

def test_selfproof_round_trips_are_constant(repo):
    """自证**现取**一次；批量调用方传读数时**零**额外往返（逐目标现取 = N 次往返 ⇒ 回归）。"""
    module = _load_module()
    work, _origin = repo
    branch = "count-me"
    _git(work, "branch", branch)
    _git(work, "push", "-q", "origin", branch)
    _git(work, "push", "-q", "origin", "--delete", branch)   # 真值：本地与远程都已清
    _git(work, "branch", "-D", branch)
    target = module.Target(branch, None, False, False, True)

    real_git, calls = module.git, []

    def counting(*args, **kwargs):
        calls.append(tuple(args))
        return real_git(*args, **kwargs)

    module.git = counting
    try:
        fresh = module.remote_heads_refresh(work)
        calls.clear()
        shared = module.verify_clean(target, work, work, heads=fresh)
        shared_reads = [c for c in calls if c[0] == "ls-remote"]
        calls.clear()
        own = module.verify_clean(target, work, work)
        own_reads = [c for c in calls if c[0] == "ls-remote"]
    finally:
        module.git = real_git

    assert (shared, own) == (True, True), (shared, own)
    assert shared_reads == [], f"传了现取读数却仍去读远程 ⇒ `NS-3` 退化：{shared_reads}"
    assert len(own_reads) == 1, f"默认自证必须**恰好现取一次**（实测 {len(own_reads)} 次）：{own_reads}"
