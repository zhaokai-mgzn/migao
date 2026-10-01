# case_ids: MC-012
r"""**机器级重活准入锁**的实例判据（issue #5814）：三态语义 / 孤儿回收 / 不误杀 / verify-all 接线。

## 治的形态（现场，不是推断）

2026-09-30 14:24 CST：三份**同样的**全量 `tests/unit_ci_workflows` 并发跑在 8 核开发机上
（① 自托管 runner 的 CI job ② 本会话一个 subagent ③ **另一个会话**一个 subagent），外加 6 个
`node (vitest)` 孤儿（PPID=1）烧了 28 分钟；`load average` 一度 45.44。
⇒ 类级病 = **同一台机器上的重活没有并发准入**。本文件判的是**实例**（锁本身的行为），
类级元守卫在 `tests/unit_ci_workflows/test_heavy_suite_entry_ledger.py`。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | 锁**语义三态**：活持有者 ⇒ `acquire` 非零退出 + 报文含「谁在跑 / PID / worktree / 已跑多久 / 可复制 kill 命令」；陈旧锁 ⇒ 回收并获取；无锁 ⇒ 获取成功 | 把「已被占」写成成功（静默跳过）⇒ 红；陈旧锁不回收 ⇒ 红 |
| 2 | 锁文件含 `name` / `pid` / `started_at` / `worktree` / `cwd` 五项 | 少写任一项 ⇒ 现场无法归因 ⇒ 红 |
| 3 | 释放只释放**自己**持有的那份（别人的锁不许删） | 谁都能删锁 ⇒ 准入形同虚设 ⇒ 红 |
| 4 | `PPID=1` **孤儿回收**：真造一个孤儿（父退出 ⇒ 复归 init）⇒ `acquire` 杀掉它 | 不回收 ⇒ 28 分钟纯浪费的形态回来 ⇒ 红 |
| 5 | **不误杀**：同名的**非孤儿**（活父进程）⇒ 不杀；路径**不在**已知工作根下的同名进程 ⇒ 不杀（射程靠路径前缀收敛，绝不按名字裸杀） | 按名字裸杀 ⇒ 用户自己的 node 服务被干掉 ⇒ 红 |
| 6 | `verify-all.sh` 的 `gate` 档**接线**：命中锁被占 ⇒ 非零退出 + 出声；且 `acquire` 必须在**任何**重活派发之前 | 删掉接线 ⇒ 红；把它挪到 `report`/`gate_check` 之后 ⇒ 红（重活已经开跑） |
| 7 | 静态契约：EXIT trap 兜异常退出 · 脚本可执行 · `bash -n` 语法过 | 删 trap ⇒ 一次 Ctrl-C 就死锁 ⇒ 红 |

## 红证口径

全部红证都**在自己造的进程上**跑（`sleep` 的替身脚本），**不碰任何别人的进程**；
`MIGAO_HEAVY_ROOTS` 一律指向 `tmp_path`（射程临时收窄 ⇒ 真杀面只可能是本文件造的那几个 PID）。
对照读数：只改**注释**（把 `acquire` 写进 `#` 注释）⇒ 判据 6 不红。

## 边界（照实登记，§19.1）

- 本判据**不判**「有人绕过 `verify-all.sh` 直接 `pytest tests/unit_ci_workflows`」—— 那一路没有锁，
  只在研发模式纪律与 PR body 的「未固化/边界」里登记；
- `status` 的**可读文本**（load / top CPU）只判「有输出、非空」，不判数值（数值随机器状态漂）；
- 本脚本**没有常驻守护**（不新增 launchd / 常驻进程）：值守面 = `acquire` 的拒绝行为 + `status`。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "machine-heavy-lock.sh"
VERIFY = REPO / "verify-all.sh"


def _run_lock(args: list[str], *, lock_file: Path, roots: Path | None = None, **kw):
    """跑锁脚本，锁文件与射程都指到临时面（**绝不碰机器上真的锁与真的进程**）。"""
    env = {
        **os.environ,
        "MIGAO_HEAVY_LOCK_FILE": str(lock_file),
        "MIGAO_HEAVY_ROOTS": str(roots if roots is not None else lock_file.parent / "roots-none"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        **kw,
    )


def _write_lock(lock_file: Path, *, name: str, pid: str, cwd: str = "/tmp") -> None:
    lock_file.write_text(
        f"name={name}\npid={pid}\nstarted_at=1700000000\nworktree=/tmp/wt\ncwd={cwd}\n",
        encoding="utf-8",
    )


#: 桩脚本的内容：一直活着、且**忽略参数**（`sleep 60 --held …` 会当场报错退出 ⇒ 造不出可观察的孤儿）。
_LONG_LIVED = "while :; do sleep 1; done\n"


def _write_stub(root: Path, name: str) -> Path:
    """写一个长命桩脚本 `root/_work/<name>`。

    ⚠️ 用 `sh` 而不是 `node`：CI 的 `ci workflow helper unit tests` job **不装 node**
    （它只装 python + PG 二进制）⇒ 依赖 `node` 的判据会在 CI 上整片红。`sh` 到处都有。
    进程命令行 = `sh <root>/_work/vitest --held` ⇒ token `vitest` 的 basename 命中**族**，
    且它落在给定工作根下 ⇒ 命中**射程**（两条都成立才会被回收）。
    """
    prog = root / "_work" / name
    prog.parent.mkdir(parents=True, exist_ok=True)
    prog.write_text("#!/bin/sh\n" + _LONG_LIVED, encoding="utf-8")
    prog.chmod(0o755)
    return prog


def launch_short_lived(source_lines: list[str], args: list[str]) -> None:
    """同步跑一小段 python（**不开管道**：孙进程继承管道会攒住父进程，见 `_spawn_orphan` 注释）。"""
    proc = subprocess.Popen(["python3", "-c", "\n".join(source_lines), *args])
    rc = proc.wait()
    assert rc == 0, f"桩进程启动失败（rc={rc}）"


def _spawn_orphan(root: Path) -> int:
    """造一个**真孤儿**：父进程起完就退场 ⇒ 子进程复归 init（PPID=1）。

    argv = `['sh', '<root>/_work/vitest', '--held']` —— 族判定取 token 的 basename（`vitest`），
    射程判定看到 `<root>/_work/vitest` 这个 token（落在给定的已知工作根下）。两条都成立才杀。
    ⚠️ 用 `sh` 不用 `node`：CI 那条 job 不装 node（详见 `_write_stub`）。
    """
    marker = root / "orphan.pid"
    marker.parent.mkdir(parents=True, exist_ok=True)
    prog = _write_stub(root, "vitest")
    launch_short_lived(
        [
            "import subprocess,sys,time",
            "p = subprocess.Popen(['sh', sys.argv[1], '--held'],"
            " start_new_session=True, stdin=subprocess.DEVNULL,"
            " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
            "open(sys.argv[2],'w').write(str(p.pid))",
            "time.sleep(0.15)",
        ],
        [str(prog), str(marker)],
    )
    return _remember(_wait_for_orphan(marker))


def _spawn_with_live_parent(root: Path) -> tuple[int, int]:
    """造一个**同名的非孤儿**：活着的父进程持有它 ⇒ 回收面必须放过它。返回 (child, parent)。"""
    marker = root / "live-child.pid"
    parent_marker = root / "live-parent.pid"
    marker.parent.mkdir(parents=True, exist_ok=True)
    prog = _write_stub(root, "vitest")
    holder = subprocess.Popen(
        [
            "python3", "-c",
            "import os,subprocess,sys,time\n"
            "p = subprocess.Popen(['sh', sys.argv[1], '--held'],"
            " start_new_session=True, stdin=subprocess.DEVNULL,"
            " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "open(sys.argv[2],'w').write(str(p.pid))\n"
            "open(sys.argv[3],'w').write(str(os.getpid()))\n"
            "time.sleep(120)\n",
            str(prog), str(marker), str(parent_marker),
        ],
    )  # ⚠️ 不开管道：孙进程继承管道会把「父进程」攒住不放（见上方注释）
    _remember(holder.pid)
    for _ in range(60):
        if marker.exists() and marker.read_text().strip() and parent_marker.exists():
            break
        time.sleep(0.05)
    child = int(marker.read_text().strip())
    parent = int(parent_marker.read_text().strip())
    assert parent == holder.pid, f"登记的父进程 {parent} != 起它的 Popen {holder.pid}"
    return _remember(child), _remember(parent)


def _wait_for_orphan(pid_file: Path) -> int:
    """等到那个进程真的复归 init（PPID=1）再返回它的 pid（一轮 bash 内轮询）。"""
    script = r"""
for _ in $(seq 1 100); do
  pid="$(cat "$1" 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [ "$ppid" = "1" ]; then echo "$pid"; exit 0; fi
  fi
  sleep 0.05
done
exit 1
"""
    r = subprocess.run(["bash", "-c", script, "_", str(pid_file)], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        # 失败路径也要登记：进程可能已经起来了只是没复归 init ⇒ 不登记就是**漏进程**
        raw = pid_file.read_text().strip() if pid_file.exists() else ""
        if raw.isdigit():
            _SPAWNED.append(int(raw))
        raise AssertionError(f"没能造出 PPID=1 的孤儿（等待超时；pid_file={pid_file}）")
    return int(r.stdout.strip())


def _alive(pid: int) -> bool:
    """活着 = 进程存在**且不是僵尸**。

    ⚠️ **为什么必须排除僵尸（CI 实测，2026-09-30；本判据首轮 CI 红的就是它）**：Linux 上被
    `kill -TERM` 杀掉、但父进程（这里是 PID 1）**还没回收**的进程会以 `Z` 状态留在进程表里，
    而 `kill -0 <pid>` 对僵尸**仍然成功** ⇒ 只看 `kill -0` 会把「已经杀掉了」读成「还活着」⇒ 假红
    （macOS 的 launchd 回收更快，本地看不到这个形态 —— 正是「本地绿 / CI 红」的教科书形态）。
    僵尸 = 进程**已经死了**、只是退出码还没被取走 ⇒ 「不再 alive」才是正确语义（不是放宽断言：
    「不误杀」那两条要的是**真在跑**的进程，其 `stat` 不含 `Z`，照旧判 True）。
    """
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return False
    return "Z" not in r.stdout.upper()


def _ps_command_of(pid: int, *, wide: bool = True) -> str:
    """用**与脚本同一调用形态**的 `ps` 取该 pid 的命令行（前置自断言用）。

    `wide=False` 复现 procps 的 80 列截断形态（红证用），`wide=True` = 脚本现在的形态。
    """
    argv = ["ps", "-A", "-ww" if wide else "-w", "-o", "pid=,ppid=,command="] if not wide else \
           ["ps", "-A", "-ww", "-o", "pid=,ppid=,command="]
    if not wide:
        argv = ["ps", "-A", "-o", "pid=,ppid=,command="]
    out = subprocess.run(argv, capture_output=True, text=True).stdout
    for line in out.split("\n"):
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0] == str(pid):
            return parts[2]
    return ""


def _assert_ps_sees_full_command(pid: int, token: str) -> None:
    """**前置自断言**：`ps` 必须看得见该进程命令行里的 `token`（否则族 / 射程判定没机会生效）。

    ⚠️ 这条不是装饰：CI 首轮实测过「`ps` 按 80 列截断 ⇒ 候选被族判定拒掉 ⇒ 打印『孤儿回收：无』」
    —— 在那样的环境里，**「不误杀」那两条判据会因为「根本没有候选」而恒绿**（假绿）。
    """
    cmd = _ps_command_of(pid)
    assert token in cmd, (
        f"前置：`ps` 必须看得见 pid={pid} 的完整命令行且含 {token!r}（否则本判据退化成空断言）—— "
        f"实得 cmd={cmd!r}"
    )


def _stat_of(pid: int) -> str:
    """给失败报文用的现场读数（`ps` 的 stat 列；空 = 进程已不在）。"""
    r = subprocess.run(["ps", "-o", "stat=,command=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip() or "（进程已不在）"


#: 本文件造出来的所有进程：测试收尾时**逐个杀干净**（不留后台 `sleep` —— 那会拖住 pytest 退出）
_SPAWNED: list[int] = []


def _remember(pid: int) -> int:
    _SPAWNED.append(pid)
    return pid


def _kill_all_spawned() -> None:
    while _SPAWNED:
        pid = _SPAWNED.pop()
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, PermissionError):
            continue  # 已经退出 / 不是本进程能杀的 —— 收尾尽力而为，不影响判定
    # 兜底（只对**本文件造出来的形状**、且只在 pytest 的临时目录下）：
    # `sh <tmp>/…/vitest --held` —— 射程靠 `pytest-of-` 前缀收敛，不碰任何别人的进程。
    subprocess.run(["pkill", "-f", "pytest-of-.*/vitest --held"], capture_output=True)


@pytest.fixture(autouse=True)
def _reap_processes_this_file_spawned():
    """每个用例收尾都把本文件造出来的进程杀干净（**不碰任何别人的进程**）。"""
    yield
    _kill_all_spawned()


@pytest.fixture
def clean_lock(tmp_path):
    return tmp_path / "heavy.lock"


# ── ① 三态语义 ───────────────────────────────────────────────────────────────

class TestLockThreeStates:
    def test_no_lock_acquire_succeeds_and_records_metadata(self, clean_lock):
        r = _run_lock(["acquire", "unit-test-entry"], lock_file=clean_lock)
        assert r.returncode == 0, f"空闲时 acquire 必须成功：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        text = clean_lock.read_text(encoding="utf-8")
        for field in ("name=", "pid=", "started_at=", "worktree=", "cwd="):
            assert field in text, f"锁文件缺 {field!r} —— 现场无法归因：\n{text}"
        assert "unit-test-entry" in text

    def test_live_holder_refuses_with_actionable_report(self, clean_lock):
        """活 PID 持有 ⇒ 非零退出 + 报「谁在跑」+ 可复制 kill 命令。"""
        _write_lock(clean_lock, name="sibling-session", pid=str(os.getppid()))
        r = _run_lock(["acquire", "intruder"], lock_file=clean_lock)
        assert r.returncode == 1, f"被占时必须**非零退出**（拒绝，不是静默跳过）：rc={r.returncode}\n{r.stdout}"
        for needle in ("sibling-session", str(os.getppid()), "kill"):
            assert needle in r.stdout, f"拒绝报文缺 {needle!r}（不可归因/不可行动）：\n{r.stdout}"
        assert "sibling-session" in clean_lock.read_text(encoding="utf-8"), "被拒时**不得**改写别人的锁"

    def test_stale_lock_is_reclaimed(self, clean_lock):
        """持有者 PID 已死（陈旧锁）⇒ 自己回收并获取。"""
        _write_lock(clean_lock, name="dead-holder", pid=str(os.getppid() + 100000))
        r = _run_lock(["acquire", "newcomer"], lock_file=clean_lock)
        assert r.returncode == 0, f"陈旧锁必须可回收：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        text = clean_lock.read_text(encoding="utf-8")
        assert "newcomer" in text and "dead-holder" not in text

    def test_release_only_removes_own_lock(self, clean_lock):
        """别人的锁不许删（准入的有效性依赖这一条）。"""
        _write_lock(clean_lock, name="someone-else", pid=str(os.getppid() + 100000))
        r = _run_lock(["release"], lock_file=clean_lock)
        assert r.returncode != 0, "非持有者的 release 必须非零退出"
        assert clean_lock.exists(), "非持有者的 release **不得**删锁"

    def test_release_removes_own_lock(self, clean_lock):
        _run_lock(["acquire", "mine"], lock_file=clean_lock)
        r = _run_lock(["release"], lock_file=clean_lock)
        assert r.returncode == 0, f"持有者自己 release 必须成功：{r.stdout}\n{r.stderr}"
        assert not clean_lock.exists(), "release 之后锁文件必须消失"

    def test_status_is_readonly_and_prints_guard_readings(self, clean_lock):
        lock_snapshot = "name=held-by-other\npid=%d\nstarted_at=1700000000\nworktree=/tmp/wt\ncwd=/tmp\n" % os.getppid()
        clean_lock.write_text(lock_snapshot, encoding="utf-8")
        r = _run_lock(["status"], lock_file=clean_lock)
        assert r.returncode == 0, f"status 是只读，必须成功：{r.stderr}"
        for needle in ("load average", "PPID=1", "top CPU", "held-by-other"):
            assert needle in r.stdout, f"status 缺值守读数 {needle!r}：\n{r.stdout}"
        assert clean_lock.read_text(encoding="utf-8") == lock_snapshot, "status **不得**写锁文件（只读）"

    def test_usage_error_exit_code_is_two(self, clean_lock):
        r = _run_lock([], lock_file=clean_lock)
        assert r.returncode == 2, f"用法错误必须是 2（与「拒绝」1、「不可判定」3 分开）：rc={r.returncode}"


# ── ④⑤ 孤儿回收 + 不误杀 ─────────────────────────────────────────────────────

class TestOrphanReaping:
    def test_orphan_under_work_root_is_reaped(self, tmp_path, clean_lock):
        root = tmp_path / "workroot"
        pid = _spawn_orphan(root)
        try:
            assert _alive(pid), "前置：孤儿必须真的活着（否则断言恒真）"
            _assert_ps_sees_full_command(pid, "vitest")
            r = _run_lock(["acquire", "reaper"], lock_file=clean_lock, roots=root)
            assert r.returncode == 0, f"acquire 必须成功：{r.stderr}"
            deadline = time.time() + 5
            while time.time() < deadline and _alive(pid):
                time.sleep(0.05)
            assert not _alive(pid), (
                f"PPID=1 的孤儿没被回收（pid={pid}，ps stat={_stat_of(pid)}）：\n{r.stdout}"
            )
            assert str(pid) in r.stdout, "回收必须**打印杀了什么**（机械动作要留痕）：\n" + r.stdout
        finally:
            if _alive(pid):
                os.kill(pid, 9)

    def test_same_name_with_live_parent_is_not_killed(self, tmp_path, clean_lock):
        """**防误杀的关键红证**：同名的非孤儿（活父进程）必须活着。"""
        root = tmp_path / "workroot"
        child, parent = _spawn_with_live_parent(root)
        try:
            assert _alive(child) and _alive(parent), "前置：父子都必须活着"
            _assert_ps_sees_full_command(child, "vitest")
            r = _run_lock(["acquire", "reaper"], lock_file=clean_lock, roots=root)
            assert r.returncode == 0, f"acquire 必须成功：{r.stderr}"
            time.sleep(0.3)
            assert _alive(child), (
                f"**误杀**了同名但父进程还活着的进程（pid={child}）—— 射程必须含「PPID=1」这一条\n{r.stdout}"
            )
        finally:
            for p in (child, parent):
                if _alive(p):
                    os.kill(p, 9)

    def test_same_name_outside_work_root_is_not_killed(self, tmp_path, clean_lock):
        """路径**不在**已知工作根下 ⇒ 不杀（**绝不按名字裸杀**的另一半）。"""
        outside = tmp_path / "outside"
        outside.mkdir(parents=True, exist_ok=True)
        pid = _spawn_orphan(outside)
        in_scope = tmp_path / "workroot"
        in_scope.mkdir(exist_ok=True)
        try:
            _assert_ps_sees_full_command(pid, "vitest")
            r = _run_lock(["acquire", "reaper"], lock_file=clean_lock, roots=in_scope)
            assert r.returncode == 0, f"acquire 必须成功：{r.stderr}"
            time.sleep(0.3)
            assert _alive(pid), (
                f"**按名字裸杀**了不在已知工作根下的进程（pid={pid}）—— 射程必须靠路径前缀收敛\n{r.stdout}"
            )
        finally:
            if _alive(pid):
                os.kill(pid, 9)


# ── ⑥⑦ verify-all.sh 的接线 ──────────────────────────────────────────────────

def _extract_fn(name: str) -> str:
    """从 verify-all.sh 抽 `name() { … }` 的函数体（到第 0 列的 `}`）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{[\s\S]*?^\}}", VERIFY.read_text(encoding="utf-8"), re.M)
    assert m, f"verify-all.sh 里抽不到 {name}()（结构变了要同步更新本判据）"
    return m.group(0) + "\n"


def _gate_branch() -> str:
    """抽 `verify-all.sh` **顶层** `case "$MODE" in` 的 `gate)` 分支（已剥注释）。

    ⚠️ 必须按 `case`/`esac` 配对找**顶层** case：脚本里的 `gate_check()` 函数体内含**嵌套** case
    （`case P in xiaobu|mibao)`），用 `;;` 裸切会把函数体当成分支内容 / 找错对象
    （本文件初版就是这么红的 —— 现取复算，见 PR body 的注入式红证）。
    """
    text = VERIFY.read_text(encoding="utf-8")
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
    start = next(i for i, ln in enumerate(lines) if 'case "$MODE" in' in ln)
    depth = 0
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if re.match(r"\s*case\b", ln):
            depth += 1
        elif re.match(r"\s*esac\b", ln):
            if depth == 0:
                break
            depth -= 1
        if depth == 0:
            if ln.strip() == "gate)":
                body = []
                j = i + 1
                while lines[j].strip() != ";;":
                    body.append(lines[j])
                    j += 1
                return "\n".join(body)
        i += 1
    raise AssertionError("verify-all.sh 顶层 case 里找不到 `gate)` 分支")


class TestVerifyAllWiring:
    def test_acquire_happens_before_any_heavy_dispatch(self):
        """`acquire` 必须在**任何**重活派发之前（否则重活已经开跑，锁等于没接）。

        接线形态是**顶层** `if ! macquire; then exit 1; fi`（`case "$MODE" in` **之前**）——
        踩坑记实：本判据初版去找 `gate` **分支体内**的 `acquire` ⇒ 恒红（真接线明明在）。
        """
        text = "\n".join(ln for ln in VERIFY.read_text(encoding="utf-8").split("\n")
                          if not ln.lstrip().startswith("#"))
        acquire_at = text.find("macquire")
        assert acquire_at >= 0, (
            "verify-all.sh 没有接机器级准入锁（macquire）—— 全量套件又可以在同一台机器上并发跑了"
        )
        case_at = text.find('case "$MODE" in')
        assert case_at > acquire_at, (
            "`macquire` 出现在顶层 `case \"$MODE\" in` **之后** —— 重活已经开始跑了才拿锁（接线顺序错）"
        )

    def test_only_the_full_suite_tier_takes_the_lock(self):
        """**只有会拉起全量套件的那一档拿锁** —— 其余档不拿（否则并行开发被无谓串行，另一种浪费）。

        ⚠️ 这条判的反方向坏形态：`heavy_lock_wanted` 恒真 ⇒ `quick/full/…` 也抢机器级锁 ⇒
        两个会话连「改一行 + 跑快档」都要排队。恒假那一侧由 `test_lock_is_held_while_the_heavy_leg_runs…` 兜。
        """
        fn = _extract_fn("heavy_lock_wanted")
        body = (
            fn + "\n"
            'for m in quick full frontend backend agent redproof gate; do\n'
            '  MODE="$m"\n'
            '  if heavy_lock_wanted; then echo "$m=WANT"; else echo "$m=NONE"; fi\n'
            "done\n"
        )
        r = subprocess.run(["bash", "-c", body], capture_output=True, text=True, cwd=str(REPO))
        got = dict(ln.split("=") for ln in r.stdout.split("\n") if "=" in ln)
        assert got.get("gate") == "WANT", f"gate 档（全量套件的唯一入口）**必须**拿锁：{got}\n{r.stderr}"
        others = {k: v for k, v in got.items() if k != "gate"}
        assert all(v == "NONE" for v in others.values()), (
            f"以下档位也拿锁了 —— 它们不是「同一台机器上的重活」：{others}"
        )

    def test_lock_is_held_while_the_heavy_leg_runs_and_released_on_exit(self, tmp_path):
        """**行为判据**（真进程，走 verify-all.sh 里**真实的**那两个函数）：重活期间锁必须持着。

        做法：装本脚本里真实的 `heavy_lock_wanted` / `macquire`，把「重活」换成 5 秒的 sleep，
        起一个后台持有者；随后在**外面**用锁脚本自己的 `acquire` 去抢 ⇒ 必须被拒。
        这判的正是「接上锁以后，`acquire` 不是秒被释放（子 shell trap 的形态）」。
        """
        lock = tmp_path / "wired.lock"
        harness = tmp_path / "holder.sh"
        harness.write_text(
            "#!/usr/bin/env bash\n"
            f'ROOT="{REPO}"\n'
            'MODE="gate"\n'
            + _extract_fn("heavy_lock_wanted")
            + _extract_fn("macquire")
            + "macquire\n"
            "LOCK_RC=$?\n"
            '[ "$LOCK_RC" -eq 0 ] || { echo "REFUSED"; exit "$LOCK_RC"; }\n'
            "sleep 5\n"
            "echo HEAVY_DONE\n",
            encoding="utf-8",
        )
        env = {**os.environ, "MIGAO_HEAVY_LOCK_FILE": str(lock)}
        holder = subprocess.Popen(["bash", str(harness)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            for _ in range(200):
                if lock.exists():
                    break
                time.sleep(0.05)
            assert lock.exists(), f"持有者没能拿到锁：{holder.stdout.read() if holder.poll() is not None else '(还在跑)'}"
            r = _run_lock(["acquire", "intruder"], lock_file=lock)
            assert r.returncode == 1, (
                "重活期间第二个人**拿到锁了** ⇒ 准入失效（形态：子 shell 一退出就把锁放了）\n" + r.stdout
            )
            holder.wait(timeout=30)
            for _ in range(40):
                if not lock.exists():
                    break
                time.sleep(0.05)
            assert not lock.exists(), (
                "持有者跑完退出后锁还在 ⇒ EXIT trap 没接上（下一次 acquire 会报「活持有者」）"
            )
        finally:
            if holder.poll() is None:
                holder.kill()

    def test_gate_branch_has_acquire_and_trap_release(self):
        text = VERIFY.read_text(encoding="utf-8")
        assert "machine-heavy-lock.sh" in text, "verify-all.sh 没有引用机器级准入锁脚本"
        assert re.search(r"machine-heavy-lock\.sh[^\n]*acquire", text), "缺 acquire 调用"
        assert re.search(r"trap[^\n]*machine-heavy-lock\.sh[^\n]*release", text), (
            "缺 EXIT trap 形态的 release —— 一次 Ctrl-C / 异常退出就把锁永久占住"
        )

    def test_guard_body_really_exits_nonzero(self):
        """**控制流判据**（不打桩、也不真跑脚本）：准入守卫必须在**非零**时 `exit 1`。

        只查「文件里出现过 macquire」是不够的 —— 本次现场两个真实坏形态：
        ① then 分支被抽空 / 改成 `exit 0` ⇒ **准入失效而静态 grep 照旧绿**；
        ② 把 `macquire` 放进**子 shell**（`if ! $(macquire)` 之类）⇒ 那个子 shell 一退出，
           `trap … EXIT` 当场释放锁，外层重活才刚要开始 ⇒ **锁等于没接，且不会有东西变红**。
        ⚠️ 刻意**不**在这里真跑 `verify-all.sh gate`：那一档会拉起全量套件（含本文件）⇒
        判据自我递归 + 把开发机重新打瘫 —— 正是本 issue 要治的形态。
        """
        text = "\n".join(ln for ln in VERIFY.read_text(encoding="utf-8").split("\n")
                          if not ln.lstrip().startswith("#"))
        m = re.search(r"^(?P<call>macquire|\$\(\s*macquire\s*\)|if\s+!\s*macquire)\s*$", text, re.M)
        assert m, (
            "verify-all.sh 里找不到顶层 `macquire` 调用 —— 拿不到锁时 gate 档会**照跑不误**"
            "（准入形同虚设）"
        )
        assert not re.search(r"\$\(\s*macquire", text), (
            "`macquire` 被命令替换（`$(macquire …)`）包住 —— 子 shell 退出即触发 EXIT trap "
            "⇒ **锁当场被释放**，外层重活才刚要开始（准入失效且不会有东西变红）"
        )
        assert m.group("call") == "macquire", (
            f"`macquire` 被放进子 shell（`{m.group('call')}`）—— 子 shell 退出即触发 EXIT trap "
            "⇒ **锁当场被释放**，外层重活才刚要开始（准入失效且无东西变红）"
        )
        assert re.search(r"^\s*exit\s+1\s*$", text[m.end():m.end() + 400], re.M), (
            "`macquire` 调用之后 400 字符内没有 `exit 1` —— 拿不到锁却继续跑（或被记成通过）"
        )
        # 光看调用点的 `exit 1` 还不够：`macquire` 自己**吞掉拒绝的退出码**时它恒返回 0，
        # 调用点永远走不到 `exit 1` —— 同一个坏结果，静态上却长得像接线完好。
        fn = _extract_fn("macquire")
        # 「吞码」的坏形态 = `acquire` 行之后的拒绝分支里 `return 0`（把拿不到锁写成成功）。
        # ⚠️ 函数开头的 `heavy_lock_wanted || return 0`（非 gate 档）是**合法**的，不能一起判红。
        m_blk = re.search(r"if\s+\[?\s*\"?\$?\{?rc\}?\"?[^\n]*-ne\s+0[^\n]*\n(?P<body>[\s\S]*?)\n\s*fi", fn)
        assert m_blk, (
            "`macquire` 里找不到「rc 非零 ⇒ 拒绝」的那个 if 块（准入判定链的结构变了）：\n" + fn
        )
        tail = m_blk.group("body")
        assert not re.search(r"^\s*return\s+0\s*$", tail, re.M), (
            "`macquire` 在 acquire 之后的拒绝分支里 `return 0` —— 它把「拿不到锁」吞成成功，"
            "调用点的 `exit 1` 永不触发：\n" + fn
        )
        assert re.search(r"^\s*return\s+\"?\$\{?rc\}?\"?\s*$", tail, re.M), (
            "`macquire` 没有把 acquire 的退出码返回给调用方（准入的判定链断了一环）：\n" + fn
        )

    def test_releasing_caller_releases_the_lock(self, clean_lock):
        """EXIT trap 形态：调用方退出后锁必须被释放（不靠人记得）。"""
        holder = clean_lock.parent / "holder.sh"
        holder.write_text(
            "#!/usr/bin/env bash\n"
            f'cd "{REPO}"\n'
            f'bash "{SCRIPT}" acquire trap-holder || exit $?\n'
            f'trap \'bash "{SCRIPT}" release >/dev/null 2>&1 || true\' EXIT\n'
            "true\n",
            encoding="utf-8",
        )
        env = {**os.environ, "MIGAO_HEAVY_LOCK_FILE": str(clean_lock)}
        r = subprocess.run(["bash", str(holder)], capture_output=True, text=True, env=env)
        assert r.returncode == 0, f"holder 脚本必须成功：{r.stderr}"
        assert not clean_lock.exists(), (
            "调用方退出后锁还在 ⇒ EXIT trap 没接上（或被误删的逻辑写坏了）"
        )


class TestPurePredicates:
    """`MIGAO_HEAVY_LIB=1` 时脚本只装函数、不上膛 ⇒ 纯谓词可**零子进程、零时钟**直接调用。

    这是**射程判定**的单元面（防误杀的最后一道）：`_runner_of_command`（族）与
    `_command_in_roots`（路径前缀）。误杀的两个已知坏形态（同名非孤儿 / 工作根之外）在
    `TestOrphanReaping` 已用**真进程**判过 —— 这里是它们的**纯函数版**，红得更快、更好定位。
    """

    def _call(self, body: str, roots: Path | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "MIGAO_HEAVY_LIB": "1"}
        if roots is not None:
            env["MIGAO_HEAVY_ROOTS"] = str(roots)
        return subprocess.run(
            ["bash", "-c", f'source "{SCRIPT}"\n{body}'],
            capture_output=True, text=True, env=env, cwd=str(REPO),
        )

    def test_runner_family_matches_the_observed_shapes(self):
        r = self._call(
            'for c in "node --import tsx/esm apps/cli/src/bin.ts web" '
            '"/usr/bin/python3 -m pytest tests/unit_ci_workflows" "node (vitest)" "bash scripts/x.sh"; do '
            '  if _runner_of_command "$c"; then echo "$RUNNER_NAME"; else echo NONE; fi; done'
        )
        got = [ln.strip() for ln in r.stdout.split("\n") if ln.strip()]
        assert got == ["node", "pytest", "node", "NONE"], (
            f"族判定与现场观测到的形态不符（2026-09-30 现场：`node …` / `node (vitest)`）：{got}"
        )

    def test_scope_is_prefix_based_and_outside_paths_do_not_match(self, tmp_path):
        inside = tmp_path / "work" / "vitest"
        outside = tmp_path / "elsewhere" / "vitest"
        r = self._call(
            f'_command_in_roots "{inside}" && echo IN || echo NO; '
            f'_command_in_roots "{outside}" && echo IN || echo NO',
            roots=tmp_path / "work",
        )
        got = [ln.strip() for ln in r.stdout.split("\n") if ln.strip()]
        assert got == ["IN", "NO"], (
            f"射程必须是**路径前缀**判定（工作根之下的命中、之外的不命中）：实得 {got}\n{r.stderr}"
        )


# ── ③.5 `--wait`：排队等待（issue #5863，2026-10-01） ────────────────────────

class TestWaitOption:
    """`acquire` 的**默认语义是立即拒绝**（`held` ⇒ `return 1`），它**不排队** ⇒ 「谁重试得勤谁拿到」。

    现场（2026-10-01 11:04~11:38 +08，本仓实测）：一个以 **30s 固定间隔**重试的客户端探测
    **56 次 / 约 34 分钟一次未中**；同期锁被 3 个持有者轮转（pid 48499 / 29770 / 75210）；
    60s 采样显示**释放瞬间总被当场接走**。⇒ 缺口不是「锁坏了」（三态 / 陈旧回收 / 孤儿回收都正常），
    而是**没有等待语义**。本节的判据都是**真跑脚本**，不是文本检查。
    """

    def test_wait_returns_immediately_when_lock_is_free(self, clean_lock):
        """空闲时 `--wait N` **不得**变慢 —— 等待必须是「被占时才排队」，不是无条件 sleep。"""
        t0 = time.monotonic()
        r = _run_lock(["acquire", "waiter-free", "--wait", "30"], lock_file=clean_lock)
        elapsed = time.monotonic() - t0
        assert r.returncode == 0, f"空闲时 --wait 必须立即成功：rc={r.returncode}\n{r.stdout}"
        assert elapsed < 5, f"空闲时不该等待（实测 {elapsed:.1f}s）"

    def test_wait_queues_until_the_holder_releases(self, clean_lock):
        """🔴 **牙齿**：锁被占住 ⇒ `--wait` 必须**等到释放**并成功（这正是缺的那个语义）。"""
        _write_lock(clean_lock, name="holder", pid=str(os.getppid()))

        def _release_later():
            time.sleep(2.0)
            clean_lock.unlink(missing_ok=True)

        th = threading.Thread(target=_release_later, daemon=True)
        th.start()
        r = _run_lock(["acquire", "waiter", "--wait", "40"], lock_file=clean_lock)
        th.join(timeout=5)
        assert r.returncode == 0, f"--wait 必须在锁释放后取得：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        # ⚠️ 输出里是 `**排队等待**后取得`（markdown 加粗是**字面字符**，不是渲染）⇒ 用正则容忍两侧星号，
        #    别写死无星号的子串（本判据第一版就是这么假红的）。
        assert re.search(r"排队等待\*{0,2}后取得", r.stdout), (
            f"拿锁后必须**出声**说明等过（否则读数不可归因）：\n{r.stdout}"
        )
        assert "waiter" in clean_lock.read_text(encoding="utf-8")

    def test_wait_times_out_and_names_the_holder(self, clean_lock):
        """超时 ⇒ 非零退出 + **具名**（可行动），且**不得**偷锁。"""
        _write_lock(clean_lock, name="stubborn", pid=str(os.getppid()))
        t0 = time.monotonic()
        r = _run_lock(["acquire", "late", "--wait", "2"], lock_file=clean_lock)
        elapsed = time.monotonic() - t0
        assert r.returncode == 1, f"超时必须非零退出：rc={r.returncode}\n{r.stdout}"
        assert elapsed < 25, f"超时上限必须真的生效（实测 {elapsed:.1f}s / 上限 2s）"
        for needle in ("stubborn", "等待已到上限", "没有跑"):
            assert needle in r.stdout, f"超时报文缺 {needle!r}：\n{r.stdout}"
        assert "stubborn" in clean_lock.read_text(encoding="utf-8"), "超时**不得**改写别人的锁"

    def test_wait_zero_is_identical_to_immediate_refusal(self, clean_lock):
        """`--wait 0` 与不传 `--wait` **等价**（默认语义没被改动的机械证据）。"""
        _write_lock(clean_lock, name="holder", pid=str(os.getppid()))
        a = _run_lock(["acquire", "x", "--wait", "0"], lock_file=clean_lock)
        b = _run_lock(["acquire", "x"], lock_file=clean_lock)
        assert (a.returncode, b.returncode) == (1, 1), f"两者都必须立即拒绝：{(a.returncode, b.returncode)}"
        assert "等待已到上限" not in a.stdout, "--wait 0 不该走超时路径（它就是「只试一次」）"
        assert "holder" in clean_lock.read_text(encoding="utf-8")

    def test_wait_rejects_malformed_seconds(self, clean_lock):
        """用法错误 ⇒ rc=2（**不得**退化成等待或静默按 0 处理）。"""
        for args in (["acquire", "x", "--wait"], ["acquire", "x", "--wait", "abc"], ["acquire", "x", "--wait", "-1"]):
            r = _run_lock(args, lock_file=clean_lock)
            assert r.returncode == 2, f"{args} 应判用法错误（rc=2）：rc={r.returncode}\n{r.stdout}"

    def test_backoff_is_bounded_and_not_constant(self):
        """抖动：落在 `[WAIT_MIN_SECONDS, WAIT_MAX_SECONDS]` 且**非常数**（防多个等待者同刻惊群）。"""
        body = (
            'source "' + str(SCRIPT) + '"\n'
            'for i in $(seq 1 24); do echo "$(_wait_backoff_seconds)"; done'
        )
        r = subprocess.run(
            ["bash", "-c", body], capture_output=True, text=True,
            env={**os.environ, "MIGAO_HEAVY_LIB": "1"}, cwd=str(REPO),
        )
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        assert len(vals) == 24, f"取不到退避值：{r.stdout!r} / {r.stderr!r}"
        assert all(2 <= v <= 5 for v in vals), f"退避必须落在 [2,5]（防惊群 + 防饿死）：{vals}"
        assert len(set(vals)) > 1, f"退避必须是**抖动**而不是常数：{vals}"

    def test_discriminating_power_on_injected_variant(self, tmp_path, clean_lock):
        """🔴 **变异红证**：把「可等待」那行拿掉 ⇒ `test_wait_queues_until_the_holder_releases`
        的断言对象（rc=0 / 「排队等待后取得」）必须**当场不成立** —— 证明判据不是空断言。"""
        src = SCRIPT.read_text(encoding="utf-8")
        old = '    [ "${wait_seconds}" -gt 0 ] || return 1'
        assert src.count(old) == 1, "变异锚点未命中（脚本结构变了 ⇒ 请同步更新本红证）"
        mutated = tmp_path / "machine-heavy-lock-mutated.sh"
        mutated.write_text(src.replace(old, '    return 1  # 变异：永不等待', 1), encoding="utf-8")
        _write_lock(clean_lock, name="holder", pid=str(os.getppid()))

        def _release_later():
            time.sleep(2.0)
            clean_lock.unlink(missing_ok=True)

        th = threading.Thread(target=_release_later, daemon=True)
        th.start()
        r = subprocess.run(
            ["bash", str(mutated), "acquire", "waiter", "--wait", "40"],
            capture_output=True, text=True, cwd=str(REPO),
            env={**os.environ, "MIGAO_HEAVY_LOCK_FILE": str(clean_lock)},
        )
        th.join(timeout=5)
        assert r.returncode == 1, f"变异体（永不等待）**必须**判红：rc={r.returncode}\n{r.stdout}"
        assert not re.search(r"排队等待\*{0,2}后取得", r.stdout), "变异体不得出现「排队等待…后取得」"


class TestStaticContract:
    def test_script_is_executable_and_syntax_clean(self):
        assert SCRIPT.is_file(), "缺少 scripts/machine-heavy-lock.sh"
        assert os.access(SCRIPT, os.X_OK), "锁脚本必须可执行（否则入口接线会静默失败）"
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert r.returncode == 0, f"bash -n 不过：\n{r.stderr}"

    def test_process_table_asks_for_unbounded_width(self):
        """`ps` 必须带 `-ww` —— procps 在**输出不是终端**时按 **80 列**截断命令行。

        CI 实测（2026-09-30，本脚本首轮 CI 红的真因）：同一台机器上 macOS 的 `ps` 不截断、Linux 的
        procps 截断 ⇒ 落在 80 列之后的工作根 token 被切断 ⇒ **族判定看不见 `vitest`** ⇒ 回收静默失效
        （报文是「孤儿回收：无」，而那个进程的 PPID 确实是 1）—— 教科书式「本地绿 / CI 红」。
        """
        text = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"^_process_table\(\) \{[\s\S]*?^\}", text, re.M)
        assert m, "抽不到 `_process_table()`（结构变了要同步更新本判据）"
        assert "-ww" in m.group(0), (
            "`_process_table` 的 `ps` 少了 `-ww`：procps 下命令行会被按 80 列截断 ⇒ 孤儿回收静默失效"
        )
        bare = [
            ln.strip() for ln in text.split("\n")
            if re.search(r"\bps\s+-A\b.*command=", ln) and "-ww" not in ln
            and not ln.lstrip().startswith("#")
        ]
        assert not bare, (
            "以下 `ps … command=` 调用没带 `-ww`（每一个都是同一类静默失效点）：\n  - "
            + "\n  - ".join(bare)
        )

    def test_script_documents_why_orphan_reaping_is_safe(self):
        """注释里必须写清「为什么回收是安全的」（父已死 ⇒ 不可能是任何人等的结果 + 路径前缀射程）。"""
        text = SCRIPT.read_text(encoding="utf-8")
        assert "PPID == 1" in text or "PPID=1" in text, "没有写清「PPID=1」这条判定"
        assert "绝不按名字裸杀" in text, "没有写清「不按名字裸杀」这条射程纪律"
        assert "不可能" in text, "没有写清「父进程已不存在 ⇒ 不可能是任何人正在等的结果」这条理由"

    def test_comment_only_mention_does_not_count_as_wiring(self):
        """对照读数：把 acquire 写进注释 ⇒ 判据 6 的接线判定**不**认它（不红）。"""
        text = "# ./scripts/machine-heavy-lock.sh acquire 'x'\n"
        code_only = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))
        assert "machine-heavy-lock.sh" not in code_only, "只改注释却被当成接线 ⇒ 判据吃自己的说明文字"
