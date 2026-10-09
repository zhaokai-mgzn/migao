# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 —— 见
#   tests/unit_ci_workflows/test_issue_lifecycle_finish.py 的同款声明与 `.github/cases/misc.yml`
#   MC-012「CI workflow 结构由 pytest 单测验证」的登记。本包不新建用例族。）
"""`scripts/issue_lifecycle.py` 的**收尾子命令不得删掉自己的 cwd**（issue #6261）。

## 病灶（一类缺陷）

收尾类子命令的第一段是「删掉目标 worktree」，而**调用者的 cwd 往往就是那个 worktree**
（包收尾的默认形态：站在包里跑 `finish`）。删掉之后，进程的 cwd 就是一个**已被 unlink 的目录**：

* `Path.cwd()` ⇒ `FileNotFoundError`；
* `subprocess.run(..., cwd=<已删目录>)` ⇒ `Popen.__init__` 当场抛 `FileNotFoundError`
  （**不是** `returncode != 0` —— `git()` 的 `check=True` 与 `delete_remote_branch` 的
  `check=False` 都接不住），于是脚本**中断在「删 worktree 之后、删分支之前」**。

⇒ 半收尾尾巴：**worktree 删了、本地/远程分支还在**（与铁律 12(d) 同族），而脚本的退出码是
**未捕获异常的 1**，不是任何有语义的 0/2/3。

`cmd_land` 早有一行 `os.chdir(root)` 正是为此（见其上方注释），而 `finish` / `prune` /
`reap-merged` **没有** —— 本文件把这一族钉住。

## 判据分组（每组都要能**单独**变红）

① **实例判据（端到端）**：从目标 worktree **内部**启动 `finish` ⇒ 三段收尾跑完 + `exit 0`
   + 三个面（worktree list / 本地分支 / 远程分支）逐项读数；带 ② 反向对照（从主检出启动）
   与 ③ 红证锚（本判据在旧实现下**实测** `exit=1` + 只删掉第一段）。
② **类级元守卫**：`CWD_DELETING_HELPERS`（会删掉调用者 cwd 的删除动作）与 `REGISTERED_COMMANDS`
   （已登记「先离开可能被删的目录」的子命令）**双向**一致，且每个登记项在源码里
   **确实有** `os.chdir(...)` 且它**先于**所有删除动作 —— 新子命令踩同一个坑 ⇒ **未登记即红**。
③ **判别力自证**：对**真源码文本**做内存变异（摘掉 chdir ⇒ 红 / 登记表漏项 ⇒ 红 / 改函数名 ⇒ 红），
   并带负控（只加注释 ⇒ 不红）。

夹具一律是 `tmp_path` 下的**真 git 仓库 + 真 bare origin + 真 worktree**，`gh` 用替身可执行文件
注入（`MIGAO_GH_BIN`）——**只换 CLI 边界，不 mock 被测函数**（同 `test_issue_lifecycle_finish.py`）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "scripts" / "issue_lifecycle.py"

# ── 类级元守卫的两个面（**登记表**，不是硬编码行号）──────────────────────────────
#
# `CWD_DELETING_HELPERS` = 「会删掉**调用者 cwd** 的删除动作」—— 判据本体是**它们的实现**
#   （`git worktree remove` 的 `path` 参数就是被删的目录），不是函数名像什么。
# `REGISTERED_COMMANDS` = 「会删 cwd 的子命令」的**完整台账**：每个都必须先离开可能被删的目录。
#   未登记的调用者 ⇒ 红（新子命令踩同一个坑进不来）；
#   登记了却摘掉离开动作 / 把离开放到删除之后 ⇒ 红（旧形态复发进不来）；
#   登记了却不调用删除动作（空转）⇒ 红（台账只许由**真实调用者**组成）。
# ⚠️ `cmd_land` **不在**表里：它自己不含删除动作（`os.chdir` 在它手里，是本修复的**先例**）；
#    它的形态由 `test_land_is_the_proven_precedent` 单独钉住。
CWD_DELETING_HELPERS: dict[str, str] = {
    "remove_worktree": "`git worktree remove <path>` —— 删掉的正是可能的 cwd",
}
REGISTERED_COMMANDS: dict[str, str] = {
    "cmd_finish": "收尾一个包（#6261 的原始形态：站在包里跑 ⇒ cwd 被删）",
    "cmd_prune": "批量收尾所有已注册 worktree（同一族的批量面）",
    "cmd_reap_merged": "自动收尾已合并分支（同一族的自动面）",
}


# ══════════════════════════════════════════════════════════════════════════════
# 一、源码面的读法（AST，不读注释文本 ⇒ 不会被自己的说明文字喂红）
# ══════════════════════════════════════════════════════════════════════════════

def _parse_module(source: str) -> ast.Module:
    return ast.parse(source, filename=str(MODULE))


def _call_name(node: ast.AST) -> str:
    """被调函数的**末段名**（`os.chdir` ⇒ `chdir`；`git(...)` ⇒ `git`）。"""
    target = node.func if isinstance(node, ast.Call) else None
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _top_level_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


#: 显式离开动作（`os.chdir(<安全目录>)`）—— 发现「离开助手」的种子，也是它自己的落码形态。
LEAVING_PRIMITIVE = "chdir"


def leaving_helpers(tree: ast.Module) -> dict[str, str]:
    """**发现**「离开可能被删目录」的助手：函数体里有 `os.chdir(...)` 就是。

    为什么**发现**而不是硬编码：硬编码函数名 ⇒ 有人改名 / 换实现（哪怕做得更安全）就假红
    （判据被自己的重构喂红）；而「体内有 chdir」是**结构事实**，改名照样成立。
    """
    found: dict[str, str] = {}
    for name, node in _top_level_functions(tree).items():
        if any(isinstance(sub, ast.Call) and _call_name(sub) == LEAVING_PRIMITIVE
               for sub in ast.walk(node)):
            found[name] = f"函数体内有 `os.chdir(...)`（{name}）"
    return found


def _call_sites(tree: ast.Module, callee: str) -> list[tuple[str, int]]:
    """全模块里对 `callee` 的调用点 ⇒ `[(所在函数名, 所在行), …]`（行用于排序）。"""
    hits: list[tuple[str, int]] = []
    for name, node in _top_level_functions(tree).items():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and _call_name(sub) == callee:
                hits.append((name, sub.lineno))
    return hits


def _leave_lines(node: ast.AST, helpers: set[str]) -> list[int]:
    """该函数体内的**离开动作**行号（显式 `os.chdir` 或调用「离开助手」），按出现顺序。"""
    return [sub.lineno for sub in ast.walk(node)
            if isinstance(sub, ast.Call)
            and (_call_name(sub) == LEAVING_PRIMITIVE or _call_name(sub) in helpers)]


def cwd_safety_violations(source: str,
                          helpers: dict[str, str] | None = None,
                          registered: dict[str, str] | None = None) -> list[str]:
    """返回**违规说明**清单（空 = 所有会删 cwd 的子命令都先离开了可能被删的目录）。

    三个面：
      (a) **未登记即红**：调用了 cwd-删除动作、却不在登记表里的顶层函数；
      (b) **登记未被兑现即红**：登记项没有离开动作（`os.chdir` / 离开助手都没有）；
      (c) **时序即安全顺序**：登记项的离开动作**晚于**它自己的删除动作 ⇒ 同样红。
    """
    helpers = CWD_DELETING_HELPERS if helpers is None else helpers
    registered = REGISTERED_COMMANDS if registered is None else registered
    tree = _parse_module(source)
    defined = _top_level_functions(tree)
    leavers = set(leaving_helpers(tree))

    violations: list[str] = []
    callers: dict[str, list[int]] = {}
    for helper, _why in helpers.items():
        for fn_name, lineno in _call_sites(tree, helper):
            callers.setdefault(fn_name, []).append(lineno)

    for fn_name in sorted(callers):
        if fn_name not in registered:
            violations.append(
                f"`{fn_name}()` 调用了会删掉调用者 cwd 的动作 {sorted(helpers)}，"
                f"但未登记进 REGISTERED_COMMANDS ⇒ 未登记即红（同类会从这个口子进来）")

    for fn_name in sorted(registered):
        node = defined.get(fn_name)
        if node is None:
            violations.append(f"登记表里的 `{fn_name}` 在源码里不存在 ⇒ 登记未被兑现")
            continue
        first_delete = min(callers.get(fn_name, [10 ** 9]))
        leaves = _leave_lines(node, leavers)
        if not leaves:
            violations.append(
                f"`{fn_name}()` 会删掉 cwd 却没有离开动作（`os.chdir` / 离开助手 {sorted(leavers)} "
                f"都没有）⇒ 删完之后 `Path.cwd()` / `git -C <已删目录>` 当场抛 FileNotFoundError")
            continue
        if min(leaves) > first_delete:
            violations.append(
                f"`{fn_name}()` 的离开动作（行 {min(leaves)}）**晚于**它的删除动作"
                f"（行 {first_delete}）⇒ 离开得太晚，等于没离开")
    return violations


# ══════════════════════════════════════════════════════════════════════════════
# 二、端到端夹具（真 git；gh 替身）—— 与 test_issue_lifecycle_finish.py 同款，不另造一套
# ══════════════════════════════════════════════════════════════════════════════

# 复用同目录既有夹具（判据本体就是真 git 语义，**不复制第二份夹具** —— 同
# `test_admin_web_devserver_identity.py` 的范式）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_issue_lifecycle_finish import (  # noqa: E402
    Fixture,
    _branches,
    _remote_branches,
    _worktree_paths,
)


@pytest.fixture()
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def _finish_from(fx: Fixture, branch: str, cwd: Path):
    """在 `cwd` 里启动 `finish <branch>`（`cwd` 可能是**会被这次调用删掉的**那个 worktree）。"""
    return fx.run("finish", branch, cwd=cwd)


def _snapshot(fx: Fixture) -> dict[str, object]:
    """收尾三面 + worktree 目录是否还在（**读数**，不是「好像失败了」）。"""
    return {
        "worktree_list": _worktree_paths(fx.repo),
        "local_branches": _branches(fx.repo),
        "remote_branches": _remote_branches(fx.repo),
    }


# ── 批量面（`prune --apply`）：两个目标连着删 ⇒ 戳穿「远程读数缓存键」这一层 ──────────
#
# 为什么要**两个**目标：`verify_clean` 的「远程分支不存在」那一项读的是**进程内快照**
# `_REMOTE_HEADS`，而 `cmd_prune` 的远程删除走**逐分支** `delete_remote_branch`
# （**不经过**自带 refresh 的 `batch_delete_remote_branches`）⇒ 只要自证在「缓存已被读过、
# 远程才被删」这一顺序上取值，它就会拿**删除前**的快照去判「还在不在」，报出与最终态相反的
# 结论（#6261 实测到该自证与最终态相反）。⇒ 删除段结束后**刷一次**再自证（脚本侧）；
# 本组判据钉住的是**外部可观察面**：两个目标全清、自证无 ❌、`exit 0`（单目标跑不出第二段自证）。

def _two_merged_targets(fx: Fixture, branches: tuple[str, str]) -> tuple[Path, Path]:
    first, second = branches
    wt_a = fx.add_branch_with_worktree(first)
    wt_b = fx.add_branch_with_worktree(second)
    fx.push_branch(first)
    fx.push_branch(second)
    fx.set_merged_prs([first, second])
    return wt_a, wt_b


def test_prune_apply_from_inside_a_target_worktree_has_no_false_red(fx: Fixture):
    """站在目标 worktree 里 `prune --apply` ⇒ 两个目标全清 + 自证无 ❌ + `exit 0`。"""
    branches = ("fix/one", "fix/two")
    wt_a, wt_b = _two_merged_targets(fx, branches)

    proc = fx.run("prune", "--apply", cwd=wt_a)

    assert proc.returncode == 0, (
        f"prune --apply 必须全清且 exit 0，实际 exit={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    assert "❌" not in proc.stdout, f"自证不得报未清项（最终态已干净）：\n{proc.stdout}"
    snap = _snapshot(fx)
    assert str(wt_a) not in snap["worktree_list"] and str(wt_b) not in snap["worktree_list"]
    for b in branches:
        assert b not in snap["local_branches"], f"本地分支未清：{b}"
        assert b not in snap["remote_branches"], f"远程分支未清：{b}"


def test_prune_apply_from_main_checkout_stays_green(fx: Fixture):
    """**反向对照**：从主检出 `prune --apply` 同样全清 + `exit 0`（两条入口读数一致）。"""
    branches = ("fix/one", "fix/two")
    wt_a, wt_b = _two_merged_targets(fx, branches)

    proc = fx.run("prune", "--apply", cwd=fx.repo)

    assert proc.returncode == 0, f"从主检出必须一致：\n{proc.stdout}\n{proc.stderr}"
    assert "❌" not in proc.stdout, f"不得有未清项：\n{proc.stdout}"
    snap = _snapshot(fx)
    assert str(wt_a) not in snap["worktree_list"] and str(wt_b) not in snap["worktree_list"]
    for b in branches:
        assert b not in snap["remote_branches"], f"远程分支未清：{b}"


# ══════════════════════════════════════════════════════════════════════════════
# 三、① 实例判据：从目标 worktree 内部启动 ⇒ 三段收尾跑完 + exit 0
# ══════════════════════════════════════════════════════════════════════════════

def test_finish_started_inside_target_worktree_completes_all_three(fx: Fixture):
    """**#6261 的实例判据**：站在包里跑 `finish` ⇒ worktree + 本地 + 远程 三段都清，退出码 0。

    红证（旧实现的实测读数，逐字见 PR body）：
      `EXIT CODE = 1` + `FileNotFoundError: …/migao-wt/done`（抛在 `delete_local_branch` 的
      `subprocess.run`），中断点 = 删 worktree **之后**、删分支 **之前**；
      中断时三面 = worktree list 里已无它 / 本地 `fix/done` 在 / 远程 `fix/done` 在。
    """
    wt = fx.add_branch_with_worktree("fix/done")
    fx.push_branch("fix/done")
    fx.set_merged_prs(["fix/done"])

    proc = _finish_from(fx, "fix/done", cwd=wt)

    assert proc.returncode == 0, (
        f"从目标 worktree 内部启动必须跑完三段收尾（exit 0），实际 exit={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")
    snap = _snapshot(fx)
    assert str(wt) not in snap["worktree_list"], "worktree 未清"
    assert "fix/done" not in snap["local_branches"], "本地分支未清（半收尾尾巴）"
    assert "fix/done" not in snap["remote_branches"], "远程分支未清（半收尾尾巴）"
    assert "自证" in proc.stdout, "必须跑到自证段（中断在半路时不会有）"
    assert not Path(wt).exists(), "worktree 目录本体应已消失"
    # 反向：中断的**典型证据**不得再出现（旧实现是**未捕获异常**而不是有语义的退出码）
    assert "FileNotFoundError" not in (proc.stdout + proc.stderr), "不得再抛未捕获异常"


def test_finish_from_main_checkout_behaviour_unchanged(fx: Fixture):
    """**反向对照（现状可过）**：从主检出启动 ⇒ 行为一字不变（同样三段清 + exit 0）。"""
    wt = fx.add_branch_with_worktree("fix/done")
    fx.push_branch("fix/done")
    fx.set_merged_prs(["fix/done"])

    proc = _finish_from(fx, "fix/done", cwd=fx.repo)

    assert proc.returncode == 0, f"从主检出启动应成功：\n{proc.stdout}\n{proc.stderr}"
    snap = _snapshot(fx)
    assert str(wt) not in snap["worktree_list"]
    assert "fix/done" not in snap["local_branches"]
    assert "fix/done" not in snap["remote_branches"]


def test_finish_via_worktree_path_arg_from_inside_that_worktree(fx: Fixture):
    """同一形态的第二条入口：`finish <工作区路径>`（**路径形态**）从该 worktree 内部启动。

    入口不同、病灶同一个 —— 判据本体是 `Path.cwd()` 而不是参数形态（避免只修一条入口）。
    """
    wt = fx.add_branch_with_worktree("fix/by-path")
    fx.push_branch("fix/by-path")
    fx.set_merged_prs(["fix/by-path"])

    proc = _finish_from(fx, str(wt), cwd=wt)

    assert proc.returncode == 0, (
        f"路径形态也必须跑完三段：exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    snap = _snapshot(fx)
    assert str(wt) not in snap["worktree_list"]
    assert "fix/by-path" not in snap["local_branches"]
    assert "fix/by-path" not in snap["remote_branches"]


# ══════════════════════════════════════════════════════════════════════════════
# 四、② 类级元守卫：**任何会删自己 cwd 的脚本动作**都要先离开那个目录
# ══════════════════════════════════════════════════════════════════════════════

def test_no_command_deletes_its_own_cwd_without_leaving_first():
    """真源码判据：每个会删 cwd 的收尾子命令都必须**先** `os.chdir` 到安全目录。"""
    violations = cwd_safety_violations(MODULE.read_text(encoding="utf-8"))
    assert not violations, "收尾子命令会删掉自己的 cwd：\n  - " + "\n  - ".join(violations)


def test_registry_matches_reality_both_ways():
    """两个面**双向**一致：登记表不空转（每条都能兑现），也不漏（每个调用者都登记）。"""
    source = MODULE.read_text(encoding="utf-8")
    tree = _parse_module(source)
    defined = _top_level_functions(tree)

    assert CWD_DELETING_HELPERS, "cwd-删除动作清单为空 ⇒ 守卫空转（fail-closed）"
    assert REGISTERED_COMMANDS, "登记表为空 ⇒ 守卫空转（fail-closed）"
    for helper in CWD_DELETING_HELPERS:
        assert helper in defined, f"清单里的 `{helper}` 在源码里不存在 ⇒ 清单未被兑现"
    actual = {fn for helper in CWD_DELETING_HELPERS for fn, _ in _call_sites(tree, helper)}
    assert actual == set(REGISTERED_COMMANDS), (
        "调用者集合与登记表必须逐项相等（多一个 ⇒ 漏登记；少一个 ⇒ 登记未被兑现）：\n"
        f"  实际调用者 = {sorted(actual)}\n  登记表     = {sorted(REGISTERED_COMMANDS)}")
    # 逐条重复一遍以**逐项归因**（集合相等只报「不相等」，不报是哪一项）
    for fn_name in sorted(actual):
        assert fn_name in REGISTERED_COMMANDS, f"`{fn_name}` 是 cwd-删除动作的调用者却没登记"


def test_registry_dropped_entry_goes_red():
    """登记表漏一项（哪怕只是**少写一行**）⇒ 判据必须**具名**报出未登记的那个调用者。"""
    source = MODULE.read_text(encoding="utf-8")
    thinned = dict(REGISTERED_COMMANDS)
    dropped = "cmd_prune"
    assert dropped in thinned, "变异注入前先自证生效：登记表里应有该项"
    del thinned[dropped]

    violations = cwd_safety_violations(source, registered=thinned)

    assert any(dropped in v and "未登记" in v for v in violations), (
        f"登记表漏项必须具名判红：{violations}")


def test_registry_stale_entry_goes_red():
    """登记表**空转**（登记了一个不存在 / 不调用删除动作的函数）⇒ 同样红。"""
    source = MODULE.read_text(encoding="utf-8")
    bloated = dict(REGISTERED_COMMANDS)
    bloated["cmd_imaginary"] = "登记了一个不存在的函数"

    violations = cwd_safety_violations(source, registered=bloated)

    assert any("cmd_imaginary" in v and "不存在" in v for v in violations), (
        f"登记未被兑现必须具名判红：{violations}")


# ══════════════════════════════════════════════════════════════════════════════
# 五、③ 判别力自证：对**真源码文本**做内存变异，坏形态各自判红 + 负控
# ══════════════════════════════════════════════════════════════════════════════

def _source() -> str:
    return MODULE.read_text(encoding="utf-8")


def _definition_block(source: str, func_name: str) -> str:
    """该顶层函数的**定义原文块**（从 `def <name>(` 到下一个顶层 `def` 之前）。

    用切分而不是 AST 源片段：本文件的测试要对这个块做**字面替换**后重新解析。
    """
    head = f"def {func_name}("
    assert head in source, f"源码里找不到 `{func_name}`（判据对象被改名 ⇒ fail-closed）"
    block = source.split(head, 1)[1]
    return block.split("\ndef ", 1)[0]


def test_guard_flags_the_pre_fix_shape_of_cmd_finish():
    """**自然红证**：把 `cmd_finish` 恢复成 #6261 的旧形态（摘掉离开动作）⇒ 判据当场红。"""
    source = _source()
    block = _definition_block(source, "cmd_finish")
    head = "    cwd, target_arg = leave_deletion_radius(root, args.target)\n"
    assert head in block, "变异注入前先自证生效：修复后的 cmd_finish 里应有离开动作"
    mutated = source.replace(block, block.replace(head, "    target_arg = args.target\n", 1), 1)

    violations = cwd_safety_violations(mutated)

    assert violations, "摘掉离开动作后判据必须红（否则本守卫是空断言）"
    assert any("cmd_finish" in v for v in violations), f"必须**具名**点出 cmd_finish：{violations}"


def test_guard_flags_leaving_placed_after_the_deleting_step():
    """时序面：离开动作存在但**晚于**删除动作 ⇒ 同样红（离开得太晚 = 没离开）。"""
    source = _source()
    block = _definition_block(source, "cmd_finish")
    moved = block.replace(
        "    cwd, target_arg = leave_deletion_radius(root, args.target)\n", "", 1).replace(
        "        remove_worktree(target.path, cwd)\n",
        "        remove_worktree(target.path, cwd)\n        os.chdir(root)\n", 1)
    assert moved != block, "变异注入必须生效"
    mutated = source.replace(block, moved, 1)

    violations = cwd_safety_violations(mutated)

    assert violations and any("晚于" in v for v in violations), f"离开晚于删除必须红：{violations}"


def test_guard_flags_unregistered_new_call_site():
    """口子面：**新子命令**调用同一个删除动作却没登记 ⇒ 未登记即红（同类进不来）。"""
    source = _source() + (
        "\n\ndef cmd_brand_new_finish(args: argparse.Namespace) -> int:\n"
        "    remove_worktree('/tmp/x', Path.cwd())\n"
        "    return EXIT_OK\n")
    # 登记表**原样**传入（只有源码长了新调用点）⇒ 命中「未登记即红」这一面
    violations = cwd_safety_violations(source)

    assert any("cmd_brand_new_finish" in v for v in violations), (
        f"新调用点未登记必须具名判红：{violations}")


def test_guard_negative_control_comment_only_change_is_green():
    """**负控**：只在源码里加注释 / 提及函数名 ⇒ 判据必须**不红**（不吃自己的文案）。"""
    source = _source()
    mutated = source.replace(
        "def cmd_finish(args: argparse.Namespace) -> int:",
        "# os.chdir(root) —— 注释里提及不算实现；leave_deletion_radius() 同理\n"
        "def cmd_finish(args: argparse.Namespace) -> int:", 1)

    assert cwd_safety_violations(mutated) == [], "只改注释不得判红（判据读的是 AST，不是原文）"


def test_leaving_helper_is_discovered_not_hardcoded():
    """**离开助手是「发现」出来的**：改名字照样被认（判据不会被自己的重构/改名喂红）。"""
    source = _source()
    known = leaving_helpers(_parse_module(source))
    assert "leave_deletion_radius" in known, f"体内有 os.chdir 的函数应被自动发现：{sorted(known)}"

    # 改名注入：`leave_deletion_radius` → `get_out_now`（含定义与全部调用点）⇒ 必须照旧认出来
    renamed = source.replace("leave_deletion_radius", "get_out_now")
    assert renamed != source, "改名注入必须生效"
    assert cwd_safety_violations(renamed) == [], (
        "改名后判据不得假红（它认的是「体内有 chdir」这个结构事实，不是函数名）")
    assert "get_out_now" in leaving_helpers(_parse_module(renamed))


def test_land_is_the_proven_precedent():
    """**先例对照**：`cmd_land` 自己就带 `os.chdir`（本修复的原型）—— 它不该进删除动作台账。"""
    source = _source()
    tree = _parse_module(source)
    land = _top_level_functions(tree)["cmd_land"]

    assert _leave_lines(land, set(leaving_helpers(tree))), "cmd_land 应有离开动作（先例）"
    assert "cmd_land" not in REGISTERED_COMMANDS, (
        "cmd_land 不含删除动作 ⇒ 台账里不该有它（否则台账空转、判据自己被喂红）")
    assert all(fn != "cmd_land" for helper in CWD_DELETING_HELPERS
               for fn, _ in _call_sites(tree, helper)), "cmd_land 不得直接调用 cwd-删除动作"


def test_guard_declares_its_own_cwd_deleting_helpers_are_real():
    """判据对象自证：清单里的 helper 实现里**真的**有 `git worktree remove`（否则清单纯属装饰）。"""
    tree = _parse_module(_source())
    defined = _top_level_functions(tree)
    body = ast.get_source_segment(_source(), defined["remove_worktree"]) or ""
    assert "worktree" in body and "remove" in body, (
        f"`remove_worktree` 的实现不再是 `git worktree remove` ⇒ 清单要跟着改：{body!r}")
