# case_ids: MC-012
from __future__ import annotations

r"""**直连整目录 `pytest` 的套件自带机器级准入**的判据（issue #6019）。

## 治的形态（2026-10-02 现场读数，不是推断）

`scripts/machine-heavy-lock.sh` 的射程此前**只包 `verify-all.sh` 的档**；`heavy_entry_ledger.json`
的 `coverage_boundary` 与 `docs/wiki/Development.md` 的「机器级重活并发准入」节都逐字把这写成
**盖不到的**缺口。当天实测：机器上**同时有 3 个**直连整目录 `pytest tests/unit_ci_workflows`
（含 `--collect-only`）与持锁者抢 8 核，`load average` 一度 **21.6 / 43.6 / 61.3**；同日 7 个
`gate` 同跑、最高排队 **已等 2354s / 上限 2400s**。用户裁定：**把这个口子收进锁**。
⇒ 套件自己的 `tests/unit_ci_workflows/conftest.py` 拿锁（**绕过入口 = 没有入口可包**，
纪律盖不住它 ⇒ 准入点只能放套件自身）。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | **接线真跑**：起子进程跑整目录 `--collect-only`，锁被一个**活的**持有者占着 ⇒ 必须**非零退出**，且输出含**锁文件路径 + 持有者信息** | 把 conftest 的锁接线删掉 ⇒ 子进程退出 0 且正常收集 ⇒ 红 |
| 2 | **拦在收集之前**：上一条的输出里**没有**正常收集汇总 | 把 acquire 挪到收集之后（如 `pytest_collection_finish`）⇒ 红 |
| 3 | **纯函数·触发面只在整目录**：整目录（未收窄）⇒ 拿；单文件 / 多文件子集 / `-k` `-m` 收窄 ⇒ **不拿** | 判定放宽成「只要路径里含目录名就拿」⇒ 研发日常被子集也拿锁 ⇒ 红 |
| 4 | **纯函数·三类豁免**：`MIGAO_HEAVY_LOCK_HELD=1` / `CI` / xdist worker ⇒ 各自**不拿** | 删任一条豁免 ⇒ 死锁（祖先已持锁时自抢）/ 本机白排队 / N 个 worker 互抢 ⇒ 红 |
| 5 | **拿不到 ⇒ fail-closed**：`pytest.exit.Exception` + `returncode=1`，报文含锁文件路径 / 持有者 / 「怎么办」 | 退化成 `pytest.skip` 或 return ⇒ 「没跑」长得像「通过」⇒ 红 |
| 6 | **释放面**：conftest 里 acquire 与 release **都在**（结构性）；**行为级**：拿到锁后 release 真的把锁删掉、且只删自己那份 | 删 release ⇒ 一次异常退出就死锁 ⇒ 红 |
| 7 | **判别力自证**（注入式）：假 scope 造坏形态 ⇒ 纯函数当场判**不拿**（对照：真 scope 判拿） | 判据退化成「读真文件就绿」⇒ 红 |
| 8 | **子进程·整目录 + 空闲锁**：必须**真跑**（不拦），并在结束时把锁**释放**掉 | 拿锁后不释放 ⇒ 下一次 acquire 报「活持有者」⇒ 红 |
| 9 | **纪律同步**：`docs/wiki/Development.md` 不得再写旧读数「直连整目录那一路没有锁」 | 改了实现、纪律还写着「盖不到」⇒ 红 |
| 10 | 🔴 **不得挂死**（issue #6074，本缺口的形态）：祖先已持锁 + `MIGAO_HEAVY_WAIT=2700`（batch-gate 的默认值）⇒ 子进程必须在**硬超时内非零退出**并给可归因报文 | 把「祖先已持锁 ⇒ 立即拒绝」删掉 ⇒ 子进程**挂死** ⇒ 硬超时判红（这正是 2026-10-02 挂死 26 分钟的形态） |
| 11 | **有界等待不得被砍**（反向）：拿一个**永不返回**的假锁脚本 ⇒ `acquire_suite_lock` 必须在预算内返回 fail-closed 报文（不是空等） | 去掉 `subprocess` 的 `timeout` / 把预算写成无界 ⇒ 真跑硬超时 ⇒ 红 |
| 12 | **排队语义不得被误伤**（对照）：持有者**不是祖先**（真·无关会话）⇒ `--wait` 仍必须排队并等到释放 | 「祖先判定」写宽成「只要锁被占就立即拒绝」⇒ 无关会话的排队语义被砍 ⇒ 红 |

## 对照读数（不红的那种）

- 把 `acquire` 写进 `#` 注释 ⇒ 上面第 6 条的结构性判据**不看注释**（`_code_lines`）；
- 只跑**子集**（单文件）且锁被占着 ⇒ 子进程**照常跑**（第 3 条的真跑形态）；
- 第 10 条的正向对照：同一场景带上 `MIGAO_HEAVY_LOCK_HELD=1`（= 祖先已**正确**接线）⇒ 子进程照常跑。

## 成本

本文件**不跑整套**（不执行任何判据）：子进程一律 `--collect-only`，被锁拦下的那两条**立即返回**；
空闲锁那条只做**收集**（不执行）。全部锁文件都在 `tmp_path`，`MIGAO_HEAVY_ROOTS` 指向
`tmp_path` 下的空目录 ⇒ 孤儿回收的真杀面**只可能**是本文件造的进程。

## 边界（照实登记，§19.1）

- 触发面只认 pytest 的**位置参数**：目标由 `$(…)` / 变量拼接算出来的形态不在面内（假绿方向）；
- 本包**不测负载改善**（那是现场读数，不是判据）；
- 判据**不判** `verify-all.sh` 那条路（那是 `test_machine_heavy_lock.py` 的事）；
- 拿锁发生在 `pytest_collection` 钩子里 ⇒ 本文件第 1/2 条正是「收集之前」这个时序的判据；
- 第 10~12 条把真实调用塞进**硬超时的子进程**（`subprocess.run(..., timeout=…)` + `TimeoutExpired`
  ⇒ 判红）—— 这是**判据自己**的有界性；本机 `timeout(1)` 命令**不存在**（macOS 无 GNU coreutils，
  实测 `bash: timeout: command not found`）⇒ 不用它。
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFTEST_REL = "tests/unit_ci_workflows/conftest.py"
CONFTEST = REPO / CONFTEST_REL
SUITE = "tests/unit_ci_workflows"

sys.path.insert(0, str(REPO / "tests"))
from unit_ci_workflows import conftest as suite_conftest  # noqa: E402


def _code_lines(text: str) -> str:
    """剥掉整行注释（`#` 起）与反引号行 —— 「说到了」不算「接线在」（对照读数靠它）。"""
    return "\n".join(
        ln for ln in text.split("\n")
        if not ln.lstrip().startswith("#") and "`" not in ln
    )


def _child_env(lock_file: Path, extra: dict | None = None) -> dict:
    """子进程环境：清掉继承来的 `CI` / `MIGAO_HEAVY_LOCK_HELD`，锁与射程都指到临时面。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CI", "MIGAO_HEAVY_LOCK_HELD", "MIGAO_HEAVY_LOCK_FILE",
                        "MIGAO_HEAVY_ROOTS", "MIGAO_HEAVY_WAIT")}
    env.update({
        "MIGAO_HEAVY_LOCK_FILE": str(lock_file),
        "MIGAO_HEAVY_ROOTS": str(lock_file.parent / "no-roots-here"),
    })
    env.update(extra or {})
    return env


def _run_pytest(targets: list[str], lock_file: Path, extra_args: list[str] | None = None,
                extra_env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *targets, *(extra_args or []), "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(REPO), env=_child_env(lock_file, extra_env),
    )


def _write_live_holder(lock_file: Path, *, name: str, pid: int) -> None:
    lock_file.write_text(
        f"name={name}\npid={pid}\nstarted_at=1700000000\nworktree=/tmp/other-wt\ncwd=/tmp\n",
        encoding="utf-8",
    )


def _unrelated_live_holder(lock_file: Path) -> subprocess.Popen:
    """起一个**真活着的、且不是本进程祖先**的持有者（`sleep`；新会话 ⇒ 也不是本进程的子进程）。

    ⚠️ 为什么要这样：`_write_live_holder(..., pid=os.getpid())` 造的是「**祖先**持有者」——
    issue #6074 起那条会命中**另一条**立即拒绝分支（不走锁脚本、报文里没有锁的 `name`）⇒
    想判「锁被无关的活持有者占着」的判据必须用一个**真的**无关进程当持有者。
    """
    holder = subprocess.Popen(["sleep", "600"], start_new_session=True)
    _write_live_holder(lock_file, name="sibling-session", pid=holder.pid)
    return holder


# ── ①②③ 接线真跑（红证方向）+「拦在收集之前」 ─────────────────────────────────────

class TestWiringReallyRefuses:
    """**直连整目录 + 锁被活的持有者占着** ⇒ 必须出声拒绝，且**不能**真收集。"""

    def test_blocked_lock_makes_the_child_exit_nonzero_with_attribution(self, tmp_path):
        lock = tmp_path / "heavy.lock"
        # 真·活的持有者，且**不是**子进程的祖先（issue #6074 起「祖先持有者」走另一条分支；
        # 本判据守的是**锁脚本那一路**的具名拒绝）。
        holder = _unrelated_live_holder(lock)
        try:
            r = _run_pytest([SUITE], lock, extra_args=["--collect-only", "-q"])
            out = r.stdout + r.stderr

            assert r.returncode != 0, (
                "锁被活的持有者占着，子进程却**退出 0** ⇒ 直连整目录这一路没有锁"
                f"（issue #6019 的缺口原样回来）：\n{out[-2000:]}"
            )
            assert str(lock) in out, f"拒绝报文里没有**锁文件路径**（不可归因）：\n{out[-2000:]}"
            for needle in ("sibling-session", str(holder.pid), "machine-heavy-lock.sh"):
                assert needle in out, (
                    f"拒绝报文缺 {needle!r}（持有者名字 / PID / 「怎么办」）⇒ 不可归因、不可行动："
                    f"\n{out[-2000:]}"
                )
            assert lock.exists(), "被拒时**不得**动持有者的锁文件"
            assert "sibling-session" in lock.read_text(encoding="utf-8"), "被拒时**不得**改写持有者的锁"
        finally:
            holder.kill()
            holder.wait(timeout=10)

    def test_the_refusal_happens_before_any_collection(self, tmp_path):
        """拿锁必须在**收集之前** —— 否则「拒绝」是跑完才报，白烧一遍 CPU。"""
        lock = tmp_path / "heavy.lock"
        _write_live_holder(lock, name="sibling-session", pid=os.getpid())

        r = _run_pytest([SUITE], lock, extra_args=["--collect-only", "-q"])
        out = r.stdout + r.stderr
        assert r.returncode != 0, f"前置：应当被拒：\n{out[-1000:]}"
        assert f"{SUITE}/test_suite_self_lock.py" not in out, (
            "被拒的子进程里出现了**收集到的判据 nodeid** ⇒ 拿锁发生在收集**之后**"
            f"（重活已经开跑了才拿锁 = 准入形同虚设）：\n{out[-2000:]}"
        )
        assert not re.search(r"\d+ tests? collected", out), (
            "被拒的子进程里出现了**正常收集汇总**（`N tests collected`）⇒ 拿锁发生在收集**之后**"
            f"（重活已经开跑了才拿锁 = 准入形同虚设）：\n{out[-2000:]}"
        )
        assert "[6019]" in out or "准入被拒" in out, (
            f"拒绝报文没有可识别的具名标识（issue #6019）：\n{out[-2000:]}"
        )

    def test_free_lock_runs_and_releases_at_the_end(self, tmp_path):
        """**空闲锁 ⇒ 子进程照常跑**（不误伤），且它**自己**在会话结束时把锁放掉。

        成本控制：`--collect-only -q`（不执行任何判据）；`-q` 下不逐条打印 nodeid ⇒ 输出很短。
        """
        lock = tmp_path / "heavy.lock"
        r = _run_pytest([SUITE], lock, extra_args=["--collect-only", "-q"])
        out = r.stdout + r.stderr
        assert r.returncode == 0, (
            f"锁空闲时直连整目录**必须照常跑**（不误伤）：rc={r.returncode}\n{out[-2000:]}"
        )
        assert "tests collected in" in out, (
            f"空闲锁下没有出现正常收集汇总 ⇒ 可能根本没走到收集（判据会假绿）：\n{out[-2000:]}"
        )
        assert not lock.exists(), (
            "子进程跑完后锁还在 ⇒ 释放面没接上（下一次 acquire 会报「活持有者」，"
            "一次异常退出就死锁）"
        )

    def test_child_acquire_then_own_release_pairs_up(self, tmp_path):
        """**释放只释放自己那份**的行为判据：acquire 记的是**调用方的 pid**（`$PPID`）。

        做法：本测试进程 acquire（子进程形态，与 conftest 调用方式**逐字一致**）⇒ 锁文件里的
        `pid` 必须是**本进程**；本进程 release ⇒ 消失。这条正是「异常退出也能释放」的形态
        （`pytest_sessionfinish` 与 acquire 在**同一个**进程里）。
        """
        lock = tmp_path / "heavy.lock"
        env = _child_env(lock)
        ok, detail = suite_conftest.acquire_suite_lock(env)
        assert ok is True, f"空闲锁必须能拿到：{detail}"
        assert lock.exists(), "拿到锁却看不到锁文件"
        assert f"pid={os.getpid()}" in lock.read_text(encoding="utf-8"), (
            "锁里记的持有者不是**本进程**（acquire 用了 `$PPID`）⇒ 本进程的 release 会被判成"
            "「不是持有者」，一次异常退出就死锁"
        )
        suite_conftest.release_suite_lock(env)
        assert not lock.exists(), (
            "本进程（= acquire 记下的持有者）release 之后锁必须消失 ⇒ 释放面按 pid 配对"
        )


# ── ③④ 纯函数判据：触发面 + 三类豁免 ─────────────────────────────────────────────

class TestPurePredicate:
    """`conftest.suite_self_lock_wanted` 的逐条注入（零子进程、零时钟）。"""

    def _wanted(self, args, *, env=None, config=None):
        return suite_conftest.suite_self_lock_wanted(args, config=config, env=env or {})

    def test_whole_directory_wants_the_lock(self):
        for args in ([SUITE], [SUITE + "/"], ["./" + SUITE], [SUITE + "::TestFoo"],
                     ["--collect-only", "-q", "-p", "no:cacheprovider", SUITE],
                     ["-n", "4", SUITE]):
            assert self._wanted(args) is True, f"整目录形态必须拿锁，漏了：{args}"

    def test_subsets_do_not_want_the_lock(self):
        for args in ([f"{SUITE}/test_machine_heavy_lock.py"],
                     [f"{SUITE}/test_a.py", f"{SUITE}/test_b.py"],
                     [SUITE, "-k", "some_subset"],
                     [SUITE, "-k=some_subset"],
                     [SUITE, "-m", "not slow"]):
            assert self._wanted(args) is False, (
                f"子集运行**不得**拿锁（研发日常、很轻；拿锁会把日常动作串行化）：{args}"
            )

    def test_empty_arguments_do_not_want_the_lock(self):
        assert self._wanted([]) is False, "没有位置参数（未声明的目标）不得拿锁"

    def test_exemption_ancestor_already_holds_the_lock(self, monkeypatch):
        monkeypatch.setenv("MIGAO_HEAVY_LOCK_HELD", "1")
        assert self._wanted([SUITE], env=os.environ) is False, (
            "祖先（verify-all.sh）已持锁时**绝不能再 acquire** —— 自抢同一把锁 = 死锁"
        )

    def test_exemption_ci_environment(self):
        assert self._wanted([SUITE], env={"CI": "true"}) is False, (
            "CI（托管 runner）上跑同一套命令但**不占本机资源** ⇒ 不该拿本机锁"
        )
        assert self._wanted([SUITE], env={"CI": "1"}) is False
        assert self._wanted([SUITE], env={"CI": "false"}) is True, (
            "`CI=false` 不算 CI（否则本地跑 CI 形态会静默免锁）"
        )

    def test_exemption_xdist_worker(self):
        class _Cfg:
            workerinput: dict = {}

        assert self._wanted([SUITE], config=_Cfg()) is False, (
            "xdist worker 不得拿锁（只在控制器 / 单进程里拿一次）"
        )
        assert self._wanted([SUITE], config=object()) is True, (
            "非 worker 的 config 不该被误判成 worker（否则准入在控制器上也不生效）"
        )

    def test_scope_injection_makes_bad_shapes_visible(self):
        """**判别力自证**：注入假 scope 造坏形态 ⇒ 纯函数当场判**不拿**。"""
        real = {"files": {"test_a.py", "test_b.py"}, "dir_children": {"test_a.py", "test_b.py"}}
        assert suite_conftest._target_is_the_whole_suite(SUITE, real) is True, (
            "前置：正常 scope 必须判 True，否则下面的坏形态读数没有判别力"
        )
        missing = {"files": {"test_a.py", "test_b.py"}, "dir_children": {"test_a.py"}}
        assert suite_conftest._target_is_the_whole_suite(SUITE, missing) is False, (
            "目录里少了已登记的判据文件 ⇒ 「整套」不成立（fail-closed）"
        )
        empty = {"files": set(), "dir_children": set()}
        assert suite_conftest._target_is_the_whole_suite(SUITE, empty) is False, (
            "目录里一个判据文件都没有 ⇒ 不是「整个套件」"
        )
        assert suite_conftest._target_is_the_whole_suite(SUITE + "/test_a.py", real) is False
        assert suite_conftest._target_is_the_whole_suite("docs", real) is False, (
            "无关目标不得被判成整目录（否则任何 pytest 都拿锁）"
        )


# ── ⑤ fail-closed 报文与退出码 ────────────────────────────────────────────────────

class TestFailClosed:
    def test_refusal_message_names_lock_holder_and_the_way_out(self, tmp_path):
        lock = tmp_path / "heavy.lock"
        # ⚠️ 持有者 pid 必须是**一个活着的、且不是本进程祖先**的对象（issue #6074 起「祖先已持锁」会走
        #    **另一条**立即拒绝分支 ⇒ 原来写的 `os.getpid()` 现在会命中那条分支、报文里没有锁脚本的
        #    持有者信息）。换成一个真活着的无关进程（`sleep`），保留本判据的原意：**锁被活的无关持有者
        #    占着**时报文必须给出持有者信息与怎么办。
        holder = _unrelated_live_holder(lock)
        try:
            env = _child_env(lock)
            ok, detail = suite_conftest.acquire_suite_lock(env)
            assert ok is False, "锁被活的持有者占着却报「拿到」⇒ 准入形同虚设"
            assert str(lock) in detail, f"报文没有锁文件路径：\n{detail}"
            for needle in ("sibling-session", str(holder.pid), "machine-heavy-lock.sh status"):
                assert needle in detail, f"报文缺 {needle!r}（持有者信息 / 怎么办）：\n{detail}"
        finally:
            holder.kill()
            holder.wait(timeout=10)

    def test_hook_exits_nonzero_and_carries_the_detail(self, monkeypatch, tmp_path):
        """`pytest_collection` 钩子在拿不到锁时必须 `pytest.exit` 且 `returncode=1`。"""
        lock = tmp_path / "heavy.lock"
        _write_live_holder(lock, name="sibling-session", pid=os.getpid())
        monkeypatch.setenv("MIGAO_HEAVY_LOCK_FILE", str(lock))
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("MIGAO_HEAVY_LOCK_HELD", raising=False)

        class _Session:
            class config:                                    # noqa: N801
                invocation_params = type("P", (), {"args": [SUITE]})()

        with pytest.raises(BaseException) as caught:
            suite_conftest.pytest_collection(_Session())
        exc = caught.value
        assert getattr(exc, "returncode", None) == 1, (
            f"fail-closed 必须是**非零**退出码（实测拿到 {getattr(exc, 'returncode', None)!r}）"
        )
        assert str(lock) in str(exc), f"异常报文没有锁文件路径：{exc}"

    def test_acquire_is_skipped_when_the_scope_is_a_subset(self, monkeypatch, tmp_path):
        """子集运行不得真去 acquire（纯函数判定的接线形态）。"""
        lock = tmp_path / "heavy.lock"
        called = {"n": 0}

        def _boom(*_a, **_k):
            called["n"] += 1
            raise AssertionError("子集运行不该走到 acquire")

        monkeypatch.setattr(suite_conftest, "acquire_suite_lock", _boom)
        monkeypatch.setenv("MIGAO_HEAVY_LOCK_FILE", str(lock))
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("MIGAO_HEAVY_LOCK_HELD", raising=False)

        class _Session:
            class config:                                    # noqa: N801
                invocation_params = type("P", (), {"args": [f"{SUITE}/test_machine_heavy_lock.py"]})()

        assert suite_conftest.pytest_collection(_Session()) is None
        assert called["n"] == 0, "子集运行竟然调了 acquire ⇒ 研发日常被串行化"


# ── ⑥ 释放面：结构 + 行为 ────────────────────────────────────────────────────────

class TestReleaseFace:
    def test_conftest_has_both_acquire_and_release(self):
        text = _code_lines(CONFTEST.read_text(encoding="utf-8"))
        assert "machine-heavy-lock.sh" in text, "conftest 没有引用机器级准入锁脚本"
        assert re.search(r"\bacquire\b", text), (
            "conftest 里没有 acquire 调用 —— 直连整目录的准入不生效"
        )
        assert re.search(r"\brelease\b", text), (
            "conftest 里没有 release 调用 —— 一次异常退出就把锁永久占住"
        )

    def test_release_only_removes_our_own_lock(self, tmp_path):
        """行为级：拿到锁后 release 删掉自己那份；**别人的**锁不许删。"""
        lock = tmp_path / "heavy.lock"
        env = _child_env(lock)
        ok, detail = suite_conftest.acquire_suite_lock(env)
        assert ok is True, f"空闲锁必须能拿到：{detail}"
        assert lock.exists(), "拿到锁却看不到锁文件"
        suite_conftest.release_suite_lock(env)
        assert not lock.exists(), "自己 release 之后锁必须消失（否则下一次 acquire 报「活持有者」）"

        _write_live_holder(lock, name="someone-else", pid=os.getpid() + 100000)
        suite_conftest.release_suite_lock(env)
        assert lock.exists(), "非持有者的 release **不得**删别人的锁（准入有效性依赖这一条）"

    def test_the_sessionfinish_hook_really_releases(self, tmp_path, monkeypatch):
        """收口钩子必须真调 release（`test_machine_heavy_lock.py` 之外的另一半）。"""
        lock = tmp_path / "heavy.lock"
        env = _child_env(lock)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        ok, detail = suite_conftest.acquire_suite_lock(os.environ)
        assert ok is True, f"空闲锁必须能拿到：{detail}"
        assert lock.exists()

        class _Session:
            items: list = []
            testscollected = 0

            class config:                                    # noqa: N801
                class option:                                # noqa: N801
                    numprocesses = 0

        suite_conftest.pytest_sessionfinish(_Session(), 0)
        assert not lock.exists(), (
            "`pytest_sessionfinish` 跑完锁还在 ⇒ 释放面没接在这个钩子上（issue #5814 的形态："
            "同一模块两个同名钩子会互相覆盖）"
        )


# ── ⑩⑪⑫ 🔴 不得挂死：祖先已持锁 ⇒ 立即拒绝 / 有界等待 / 排队语义不误伤（issue #6074）────────────

#: 硬超时（秒）：**判据自己**的有界性。挂死形态 ⇒ `TimeoutExpired` ⇒ **判红**（不是"等下去"）。
_HANG_BUDGET_SECONDS = 60
#: 用了就不再等（墙钟读数比它大 ⇒ 这条判据没有牙）。
_HANG_FAIL_SECONDS = 30


def _probe_child(mode: str, tmp_path: Path, extra_env: dict | None = None) -> subprocess.Popen:
    """起一个**独立子进程**：把锁文件写给自己（⇒ 它对孙代就是**祖先持有者**）后跑真实函数。

    `mode` = `acquire`（直调 `acquire_suite_lock`，带 `MIGAO_HEAVY_WAIT=2700`）/
    `pytest`（真跑整目录 `--collect-only`，与本次缺陷的现场调用**逐字同形**）/
    `not-ancestor`（活持有者 = 一个**无关进程** ⇒ 排队语义的对照）。
    """
    lock = tmp_path / f"probe-{mode}.lock"
    env = _child_env(lock, {"MIGAO_HEAVY_WAIT": "2700", **(extra_env or {})})
    probe = tmp_path / f"probe-{mode}.py"
    holder = None
    if mode == "no-holder":
        # 故意**不写锁文件**：让 acquire 真的去调锁脚本（配合 extra_env 注入的假锁脚本 ⇒ 判「有界预算」）。
        holder_pid = None
    elif mode == "not-ancestor":
        holder = subprocess.Popen(["sleep", "600"], start_new_session=True)
        holder_pid = holder.pid
        holder_name = "unrelated-holder"
        _write_live_holder(lock, name=holder_name, pid=holder_pid)
    else:
        # ⚠️ **必须在父进程里就把锁文件写好**：`pytest` 那一档的子进程**不跑** probe 脚本
        #    （它直接 `python -m pytest …`）⇒ 「先写锁、再看子代是否拒绝」这个时序由父进程保证。
        holder_pid = os.getpid()
        holder_name = "self-as-ancestor"
        _write_live_holder(lock, name=holder_name, pid=holder_pid)
    if mode != "no-holder":
        assert lock.exists() and f"pid={holder_pid}" in lock.read_text(encoding="utf-8"), (
            "夹具前置失败：锁文件没有落到临时面（这一条不成立时下面就变成「没有持有者」的空断言）"
        )
    body = (
        "import os, sys, time\n"
        "sys.path.insert(0, os.path.abspath('tests'))\n"
        "from unit_ci_workflows import conftest as c\n"
        "lock = os.environ['MIGAO_HEAVY_LOCK_FILE']\n"

        "t0 = time.time()\n"
        "ok, detail = c.acquire_suite_lock(os.environ)\n"
        "print('ELAPSED %.1f OK %s' % (time.time() - t0, ok), flush=True)\n"
        "print('DETAIL', detail[:800], flush=True)\n"
    )
    probe.write_text(body, encoding="utf-8")
    cmd = [sys.executable, str(probe)]
    if mode == "pytest":
        cmd = [sys.executable, "-m", "pytest", SUITE, "--collect-only", "-q", "-p", "no:cacheprovider"]
    proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    proc._migao_holder = holder          # noqa: SLF001 —— 收尾要连它一起清理
    proc._migao_lock = lock              # noqa: SLF001
    return proc


def _finish(proc: subprocess.Popen) -> None:
    """收尾：杀干净（**整个进程组** + 无关持有者）+ 删临时锁 ⇒ 任何判据都不得留下锁或残留进程。

    ⚠️ 必须用 `killpg` 而不是 `proc.kill()`：被杀的 pytest 子进程底下还挂着**孙进程**
    （`machine-heavy-lock.sh` / 判据注入的假锁脚本）—— 只杀它自己会把孙进程变成孤儿继续跑
    （实测：`--wait 1` 的假锁脚本在判据结束后仍在后台自旋，`pgrep` 还能看到它）。

    ⚠️ 顺序：先 `communicate` 读空输出（子进程已退出时它立即返回）**再** `killpg` —— 反过来的话
    进程可能已经退出、`getpgid` 会抛 `ProcessLookupError`（本函数初版就这么踩过，且**只在
    「子进程已正常退出」时复现** ⇒ 单跑某条判据是绿的、连跑整套才会红）。
    """
    holder = getattr(proc, "_migao_holder", None)
    lock = getattr(proc, "_migao_lock", None)
    if proc.poll() is None:
        proc.kill()
    try:
        proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        # 正常到不了（上面那条 `communicate` 成功过就会把管道读空）；真发生也不影响收尾。
        proc.kill()
    if proc.poll() is None:
        # 兜底：只可能出现在「kill 之后仍不退出」的病态情形；不是 `pass`（空 `pass` = 弱断言形态）。
        proc.kill()
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)   # 孙进程（bash / 假锁脚本）
    except ProcessLookupError:
        holder = holder          # 组已随子进程一起消失（正常）⇒ 没有孙进程要杀
    except OSError:
        holder = holder          # 权限/平台差异 ⇒ 不把异常逃出收尾（锁仍会被删、断言仍在下面）
    if holder is not None:
        holder.kill()
        holder.wait(timeout=10)
    Path(lock).unlink(missing_ok=True)
    assert not Path(lock).exists(), "收尾失败：临时锁仍然存在"


def _completed_within(proc: subprocess.Popen, budget: float) -> tuple[str, float]:
    """`(输出, 墙钟)`；超出 `budget` ⇒ **杀进程并让判据红**（这就是「不得挂死」的牙）。"""
    t0 = time.monotonic()
    try:
        out, _ = proc.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=30)
        raise AssertionError(
            f"🔴 **挂死**：{budget:.0f}s 内没有返回（issue #6074 的缺陷形态 —— 祖先已持锁时去抢"
            f"祖先手里的同一把锁 = 死等）。已杀进程；读数：\n{out[-1500:]}"
        ) from None
    return out, time.monotonic() - t0


class TestNeverHangsWhenAnAncestorHoldsTheLock:
    """🔴 **有界 + 出声拒绝**（issue #6074）：豁免（`MIGAO_HEAVY_LOCK_HELD=1`）失效时**不得挂死**。

    现场形态（2026-10-02 23:00 +08 实测）：`verify-all.sh` 已持锁（泄漏了那行 export）+ 
    `scripts/batch-gate.sh` 注入的 `MIGAO_HEAVY_WAIT=2700` 被**继承** 
    ⇒ 子进程 pytest 死等 **26 分钟**、0% CPU，还全程握着机器级锁，只能 `kill -9`。
    """

    def test_pure_predicate_fires_immediately_with_a_bounded_budget(self, tmp_path):
        """纯函数 / 零子进程：锁文件写**本进程** ⇒ 祖先判定当场成立，且预算**有界**。"""
        lock = tmp_path / "self.lock"
        _write_live_holder(lock, name="self-as-ancestor", pid=os.getpid())
        env = {"MIGAO_HEAVY_LOCK_FILE": str(lock), "MIGAO_HEAVY_WAIT": "2700"}
        reason = suite_conftest._lock_holder_is_an_ancestor(lock, env)
        assert reason, "锁持有者就是本进程自己 ⇒ 祖先判定必须成立（否则下面那条会去死等）"
        assert str(os.getpid()) in reason, f"归因串必须具名 PID（可归因）：{reason!r}"
        assert suite_conftest._suite_lock_timeout_seconds({"MIGAO_HEAVY_WAIT": "2700"}) == 2760, (
            "有界预算必须**随 MIGAO_HEAVY_WAIT 增长而仍有界**（= WAIT + 缓冲），不能退化成无界等待"
        )
        assert suite_conftest._suite_lock_timeout_seconds({}) == 60, (
            "未设置 MIGAO_HEAVY_WAIT 时也必须有一个墙钟预算（锁脚本自己卡住时唯一的出口）"
        )

    def test_acquire_is_bounded_and_attributable_with_an_ancestor_holder(self, tmp_path):
        """祖先持锁 + `MIGAO_HEAVY_WAIT=2700` ⇒ `acquire_suite_lock` 必须**立即**返回拒绝。"""
        proc = _probe_child("acquire", tmp_path)
        try:
            out, elapsed = _completed_within(proc, _HANG_BUDGET_SECONDS)
        finally:
            _finish(proc)
        assert elapsed < _HANG_FAIL_SECONDS, (
            f"祖先已持锁却等了 {elapsed:.1f}s —— 那一路**注定等不到**（持有者要等本进程结束才释放）"
            f"⇒ 必须立即拒绝：\n{out[-1500:]}"
        )
        assert "OK False" in out, f"必须报拿不到锁（fail-closed）：\n{out[-1500:]}"
        for needle in (str(proc._migao_lock), "祖先", "MIGAO_HEAVY_LOCK_HELD"):
            assert needle in out, f"拒绝报文缺 {needle!r}（路径 / 归因 / 怎么办）：\n{out[-1500:]}"

    def test_real_whole_directory_pytest_exits_instead_of_hanging(self, tmp_path):
        """**与现场逐字同形**：真跑 `pytest tests/unit_ci_workflows --collect-only`（祖先持锁）⇒ 有界退出。"""
        proc = _probe_child("pytest", tmp_path)
        try:
            out, elapsed = _completed_within(proc, _HANG_BUDGET_SECONDS)
            rc = proc.returncode
        finally:
            _finish(proc)
        assert rc != 0, f"祖先已持锁、豁免又没生效 ⇒ 必须**非零退出**（不得静默跑）：rc={rc}\n{out[-1500:]}"
        assert elapsed < _HANG_FAIL_SECONDS, f"真跑调用等了 {elapsed:.1f}s ⇒ 挂死形态：\n{out[-1500:]}"
        for needle in ("准入被拒", str(proc._migao_lock)):
            assert needle in out, f"报缺 {needle!r}：\n{out[-1500:]}"

    def test_exemption_still_wins_when_the_marker_is_set(self, tmp_path):
        """**对照（不红的那种）**：同一场景带上 `MIGAO_HEAVY_LOCK_HELD=1` ⇒ 子进程**照常跑**。"""
        lock = tmp_path / "exempt.lock"
        _write_live_holder(lock, name="ancestor", pid=os.getpid())
        r = _run_pytest([SUITE], lock, extra_args=["--collect-only", "-q"],
                        extra_env={"MIGAO_HEAVY_LOCK_HELD": "1", "MIGAO_HEAVY_WAIT": "2700"})
        out = r.stdout + r.stderr
        assert r.returncode == 0, (
            f"带标记（= 祖先已正确接线）时**不得**被拦、更不得挂死：rc={r.returncode}\n{out[-1500:]}"
        )
        assert "tests collected in" in out, f"没有走到收集（判据会假绿）：\n{out[-1500:]}"

    def test_lock_script_that_never_returns_still_yields_a_bounded_refusal(self, tmp_path):
        """**反向**：锁脚本自己永不返回 ⇒ 仍必须在预算内 fail-closed（不得空等）。

        形态：`MIGAO_HEAVY_LOCK_SCRIPT` 指向一个 `sleep 3600` 的假脚本 + `MIGAO_HEAVY_WAIT=2`
        ⇒ 真预算 = 2 + 60 = 62s。判据自己是**硬超时**的：把 `subprocess` 的 `timeout` 去掉（或把预算
        写成无界）⇒ 这一条真跑 75s 硬超时 ⇒ 判红。这就是「有界」的牙。
        """
        stub = tmp_path / "never-returns.sh"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            # 兜底自毁：即使收尾没打到它（例如判据被硬杀），120s 后也自己退场，绝不常驻。
            "if command -v timeout >/dev/null 2>&1; then timeout 120 sleep 3600; else sleep 120; fi\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        # `MIGAO_HEAVY_WAIT=1` ⇒ 真预算 = 1 + 60 = 61s（本判据硬超时 75s，留 14s 余量）
        proc = _probe_child("no-holder", tmp_path,
                            extra_env={"MIGAO_HEAVY_LOCK_SCRIPT": str(stub),
                                       "MIGAO_HEAVY_WAIT": "1"})
        try:
            out, elapsed = _completed_within(proc, 75)
        finally:
            _finish(proc)
        assert "OK False" in out, f"假锁脚本永不返回时必须判「拿不到」（fail-closed）：\n{out[-1500:]}"
        assert 5 <= elapsed < 73, (
            f"墙钟 {elapsed:.1f}s ⇒ 既不能秒回（那就没走超时路径）、也不能越过预算（有界失效）：\n{out[-1500:]}"
        )
        for needle in ("有界预算", "没有退出"):
            assert needle in out, f"拒绝报文缺 {needle!r}（说清是「锁脚本没退出」而不是「锁被占」）：\n{out[-1500:]}"

    def test_unrelated_holder_still_queues_until_release(self, tmp_path):
        """**对照**：持有者**不是祖先**（真·无关会话）⇒ `--wait` 仍必须排队并**等到释放后拿到**。"""
        proc = _probe_child("not-ancestor", tmp_path)

        def _release_later():
            time.sleep(2.0)
            proc._migao_lock.unlink(missing_ok=True)      # noqa: SLF001 —— 模拟「无关会话跑完释放」

        th = threading.Thread(target=_release_later, daemon=True)
        th.start()
        try:
            out, elapsed = _completed_within(proc, _HANG_BUDGET_SECONDS)
        finally:
            th.join(timeout=5)
            _finish(proc)
        assert "OK True" in out, (
            f"持有者不是祖先 ⇒ 「祖先判定」**不得**误伤排队语义（必须等到释放后拿到）：\n{out[-1500:]}"
        )
        assert elapsed >= 1.0, f"没有真的等过（读数 {elapsed:.1f}s）⇒ 这条对照没有判别力：\n{out[-1500:]}"

    def test_hook_returns_none_and_exits_nonzero_with_an_ancestor_holder(self, monkeypatch, tmp_path):
        """`pytest_collection` 钩子在「祖先已持锁」时也必须 `pytest.exit`（非零 + 可归因）。"""
        lock = tmp_path / "hook.lock"
        _write_live_holder(lock, name="ancestor", pid=os.getpid())
        monkeypatch.setenv("MIGAO_HEAVY_LOCK_FILE", str(lock))
        monkeypatch.setenv("MIGAO_HEAVY_WAIT", "2700")
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("MIGAO_HEAVY_LOCK_HELD", raising=False)

        class _Session:
            class config:                                    # noqa: N801
                invocation_params = type("P", (), {"args": [SUITE]})()

        with pytest.raises(BaseException) as caught:
            suite_conftest.pytest_collection(_Session())
        assert getattr(caught.value, "returncode", None) == 1, (
            f"fail-closed 必须非零（实测 {getattr(caught.value, 'returncode', None)!r}）"
        )
        assert "祖先" in str(caught.value), f"报文必须点出「祖先已持锁」这一归因：{caught.value}"


# ── 文档/纪律接线（防「改了实现、纪律还写着盖不到」）────────────────────────────

class TestDisciplineIsUpdated:
    def test_docs_register_the_new_lock_face(self):
        """`docs/wiki/Development.md` 的「机器级重活并发准入」节必须登记这条路。"""
        text = (REPO / "docs/wiki/Development.md").read_text(encoding="utf-8")
        head = text.index("## 机器级重活并发准入")
        section = text[head:text.index("## 批次统一验证", head)]
        for needle in ("套件自带", "conftest.py", "pytest_collection", "MIGAO_HEAVY_LOCK_HELD=1",
                       "surface=suite-internal"):
            assert needle in section, (
                f"「机器级重活并发准入」节没有登记 {needle!r}"
                "（直连整目录也拿锁 / 三类豁免 / suite-internal 台账）"
            )
        assert "那一路没有锁" not in section, (
            "「机器级重活并发准入」节仍写着旧读数「直连整目录那一路没有锁」⇒ 文档与实现脱钩"
        )
