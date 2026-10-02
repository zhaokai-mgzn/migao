# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
r"""批次统一验证入口 `scripts/batch-gate.sh` 的实例判据（issue #6012）。

## 治的形态（2026-10-02 17:24–17:29 CST 现场，读数现取）

机器级重活锁：1 个 `gate` 持锁、**7 个 gate 在跑**（6 个排队：已等 40 / 31 / 20 / 12 / 7 / 2 分钟）、
最高排队读数 `已等 2354s / 上限 2400s`；`load average` **21.6 / 43.6 / 61.3**（8 核）。
⇒ 类级病 = **「每个包各自跑一遍全量」× 「本机只装得下一份全量」**。
排他锁治的是 CPU 争用，治不了**份数**；本判据守的是份数。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | N 个包 ⇒ 那一次全量**恰好被调用 1 次** | 有人把 gate 挪进 merge 循环（退回「每包一次」）⇒ 调用数 = N |
| 2 | 调用数**不随 N 增长**（2 包 / 3 包都得 1） | 同上；这条是 1 的**判别力**对照（N 变而读数不变才叫「统一」） |
| 3 | 红 ⇒ 面级归因点到**碰该面的包**，且不把面外包算进来 | 归因退化成「把所有包都列一遍」/ 指认错包 ⇒ 红 |
| 4 | 分支不存在 ⇒ exit **3**（无法判定）且**没跑** gate | 把「读不到分支」读成「绿」或照跑一次 ⇒ 红 |
| 5 | 整合冲突 ⇒ exit **1**、**没跑** gate、**具名**冲突分支 | 冲突也照跑 gate（把「没跑」记成「跑过」）⇒ 红 |
| 6 | 跑完不残留 worktree（本命令自建的那份自己收） | 临时集成 worktree 堆积 ⇒ 红 |

## 隔离（为什么这些判据是安全的）

全部在**自足临时仓库**里跑（`git init` + 桩 `verify-all.sh`），**不碰共享检出、不跑真全量**：
判据造的是自己那几个分支与 worktree，`--base` 显式指向临时仓库的 `main`
（默认 `origin/main` 在临时仓库里不存在 —— 这正是「不许悄悄依赖环境」的形态）。

## 边界（照实登记，§19.1）

- 桩替换了真 `verify-all.sh`：本判据**不判**真 gate 的通过条件（那是 `test_verify_all_*` 的事），
  只判**调用份数 / 归因 / 三态**这三件事；
- 归因本身是**面级映射**：判据只锁「面内唯一候选时点名它、面内多候选时不指认唯一真凶」，
  不判「真凶确实是它」（那需要失败日志级语义，本仓没有该能力）；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import uuid

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_REL = "scripts/batch-gate.sh"
SCRIPT_SRC = REPO / SCRIPT_REL

#: 桩 `verify-all.sh`：把「被调用了几次」写成可计数的读数（= 本判据的主读数）。
#: 退出码与失败项由环境变量注入 ⇒ 同一个桩既能演绿也能演红。
STUB = """#!/usr/bin/env bash
echo "call" >> "${BATCH_GATE_STUB_LOG:?}"
echo "变更集：1 个文件（桩）"
echo "✅ QA Growth Gate 预检"
if [ -n "${BATCH_GATE_STUB_EXTRA:-}" ]; then eval "${BATCH_GATE_STUB_EXTRA}"; fi
exit "${BATCH_GATE_STUB_RC:-0}"
"""

CI_FAIL = (
    'echo "❌ ci workflow helper 判据集（本地跑 CI 同名 job） (exit 1)";'
    'echo "失败项: ci workflow helper 判据集（本地跑 CI 同名 job）"'
)


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: pathlib.Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def _branch_with(root: pathlib.Path, name: str, rel: str, text: str) -> None:
    """从 `main` 切一个新分支，改一个文件，提交，再切回 `main`。"""
    _git(root, "checkout", "-q", "-b", name, "main")
    _write(root, rel, text)
    _commit(root, name)
    _git(root, "checkout", "-q", "main")


@pytest.fixture
def sandbox(tmp_path: pathlib.Path) -> pathlib.Path:
    """自足临时仓库：`main` + 三个包分支 + 一对冲突分支 + 可计数的 verify-all 桩。"""
    assert SCRIPT_SRC.is_file(), f"载体不存在：{SCRIPT_REL}"
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "batch-gate@test.invalid")
    _git(root, "config", "user.name", "batch-gate-test")

    (root / "scripts").mkdir()
    dst = root / SCRIPT_REL
    shutil.copy2(SCRIPT_SRC, dst)
    os.chmod(dst, 0o755)
    _write(root, "verify-all.sh", STUB)
    os.chmod(root / "verify-all.sh", 0o755)
    _write(root, "backend/admin-api/A.java", "base\n")
    _write(root, "backend/ai-agent-service/c.py", "base\n")
    _write(root, "frontend/admin-web/b.ts", "base\n")
    _write(root, "tests/unit_ci_workflows/guard_a.py", "base\n")
    _commit(root, "base")

    # pkg-a 碰 ci-helper 面（tests/unit_ci_workflows/**）与 admin-api 面
    _branch_with(root, "pkg-a", "tests/unit_ci_workflows/guard_a.py", "a\n")
    _branch_with(root, "pkg-b", "frontend/admin-web/b.ts", "b\n")
    _branch_with(root, "pkg-c", "backend/ai-agent-service/c.py", "c\n")
    # 一对必然冲突的分支（同一文件同一行两侧都改）
    _branch_with(root, "conf-a", "shared.txt", "A\n")
    _branch_with(root, "conf-b", "shared.txt", "B\n")
    return root


def run_batch(root: pathlib.Path, *args: str, stub_rc: str = "0", stub_extra: str = ""):
    """跑真脚本；返回 (CompletedProcess, 桩被调用的次数)。"""
    log = root.parent / f"stub-{uuid.uuid4().hex}.log"
    env = dict(os.environ)
    env.pop("MIGAO_HEAVY_WAIT", None)
    env.update({"BATCH_GATE_STUB_LOG": str(log), "BATCH_GATE_STUB_RC": stub_rc,
                "BATCH_GATE_STUB_EXTRA": stub_extra})
    proc = subprocess.run(
        [str(root / SCRIPT_REL), "--base", "main", *args],
        cwd=str(root), capture_output=True, text=True, env=env, timeout=180,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, calls


def test_one_gate_for_the_whole_batch(sandbox):
    """判据 1：N 个包 ⇒ 全量**一次**（不是每包一次）。"""
    proc, calls = run_batch(sandbox, "pkg-a", "pkg-b")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1, f"gate 被调用 {len(calls)} 次（应为 1）：{calls}"
    assert "pkg-a" in proc.stdout and "pkg-b" in proc.stdout


def test_gate_call_count_does_not_scale_with_packages(sandbox):
    """判据 2（判别力）：2 包与 3 包的调用数都是 1 —— 与「每包一次」形态可判别。"""
    _, calls2 = run_batch(sandbox, "pkg-a", "pkg-b")
    _, calls3 = run_batch(sandbox, "pkg-a", "pkg-b", "pkg-c")
    assert (len(calls2), len(calls3)) == (1, 1), f"2 包 {len(calls2)} 次 / 3 包 {len(calls3)} 次"


def test_red_attributes_to_the_package_touching_the_face(sandbox):
    """判据 3：红 ⇒ 面级归因点到碰该面的包，且不把面外包算进来。"""
    proc, calls = run_batch(sandbox, "pkg-a", "pkg-b", stub_rc="1", stub_extra=CI_FAIL)
    assert proc.returncode == 1
    assert len(calls) == 1, "红的时候也只该跑一次"
    m = re.search(
        r"失败项：.*ci workflow helper.*\n\s+面：ci workflow helper.*\n\s+面内包（可能引入方）：(\S+)",
        proc.stdout,
    )
    assert m, "归因段没有按「失败项 → 面 → 面内包」的形态打印：\n" + proc.stdout
    assert m.group(1) == "pkg-a", f"面内唯一候选应是 pkg-a，实得 {m.group(1)}"
    # pkg-b 只碰 admin-web，**不**该出现在 ci-helper 面的候选里
    assert "面内包：pkg-a、pkg-b" not in proc.stdout


def test_unknown_branch_is_undecidable_and_runs_nothing(sandbox):
    """判据 4：读不到分支 ⇒ exit 3 且**没跑**（「没跑」必须长得像「没跑」）。"""
    proc, calls = run_batch(sandbox, "no-such-branch")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert calls == [], f"无法判定时不该跑 gate，实得 {calls}"
    assert "无法判定" in proc.stdout + proc.stderr


def test_conflict_stops_before_the_gate(sandbox):
    """判据 5：整合冲突 ⇒ exit 1、没跑 gate、具名冲突分支。"""
    proc, calls = run_batch(sandbox, "conf-a", "conf-b")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert calls == [], f"冲突时不该跑 gate，实得 {calls}"
    assert "conf-b" in proc.stdout, "冲突分支没有具名"
    assert "没有跑" in proc.stdout
    assert "conf-a" in proc.stdout


def test_in_mode_runs_in_the_existing_worktree(sandbox, tmp_path):
    """`--in <worktree>`：在既有集成工作区里只跑那一次（环境已备时的形态）。"""
    wt = tmp_path / "integration"
    _git(sandbox, "worktree", "add", "--detach", str(wt), "main")
    proc, calls = run_batch(sandbox, "--in", str(wt), "pkg-a")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1
    assert str(wt) in proc.stdout


def test_no_worktree_left_behind(sandbox):
    """判据 6：自建的那份临时集成 worktree 跑完自己收掉。"""
    run_batch(sandbox, "pkg-a", "pkg-b")
    out = _git(sandbox, "worktree", "list", "--porcelain").stdout
    wts = [ln for ln in out.splitlines() if ln.startswith("worktree ")]
    assert len(wts) == 1, f"临时集成 worktree 残留：{out}"


def test_help_and_usage_are_actionable(sandbox):
    """出口必须真可行动：usage 写清两种形态 + 「没跑 ≠ 通过」。"""
    proc = subprocess.run([str(sandbox / SCRIPT_REL)], cwd=str(sandbox),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "只跑一次" in proc.stderr, proc.stderr
    hel = subprocess.run([str(sandbox / SCRIPT_REL), "--help"], cwd=str(sandbox),
                         capture_output=True, text=True, timeout=60)
    assert hel.returncode == 0
    assert "--in" in hel.stdout and "退出码" in hel.stdout
