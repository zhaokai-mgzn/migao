# case_ids: MC-373
"""`ci workflow helper unit tests` 被 cancel 之后的**归因判据**（issue #9114）。

## 病（durable 现场）

被 cancel 的 job **拿不到日志** —— `gh api …/actions/jobs/<id>/logs` 返回
`<Error><Code>BlobNotFound</Code>`（HTTP 404），`gh run view <run> --log-failed` / `--log` 都空。
实测两个样本（job `138101912467` / `138155419427`）的 `steps[]` 都停在
「`Run ci workflow helper tests` 有 `started_at`、**无** `completed_at`」⇒ 逐文件读数在 cancel 那一刻就断了。
于是「超时类事故」只剩 run 级一句 `exceeded the maximum execution time`（#9102 分片吃顶、
#9097 / #9111 两次 cancel 都是这个形态）。

## 兜底（`scripts/ci_helper_progress.py`）

包装器在**被掐死之前**把「当前跑到哪个文件」写到**不依赖 job 日志**的面上：
`$GITHUB_STEP_SUMMARY` + `::error::` annotation + stdout 进度行；SIGTERM / SIGINT / 预算耗尽 /
子进程非零退出 / 正常退出**五条出口共用同一个 `finalize()`**。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | **预算耗尽**（本地可跑、不等 CI 超时）：故意挂住的假用例 + 极小预算 ⇒ summary 里含**具名的当前文件名**（`stuck_file=…`），stdout 里有具名 `::error::` | 摘掉 `finalize()` 的 summary 写入 / 注解 ⇒ 红（红证见判据 4） |
| 2 | **SIGTERM trap**：向包装器发 SIGTERM（= runner cancel 的形态）⇒ 仍在退出前写完归因，且退出码 1 | 摘掉 trap（`HANDLED_SIGNALS` 清空）⇒ 进程被默认动作杀掉 ⇒ summary 没有归因段 ⇒ 红（红证见判据 3） |
| 3 | **红证（trap 面）**：变异体 `HANDLED_SIGNALS = ()` **先自证注入落下**，再跑同一场景 ⇒ 必须**不再**出现归因 ⇒ 证明判据 2 不是恒绿 | 判据对「有没有 trap」不敏感 ⇒ 红 |
| 4 | **红证（summary 面）**：变异体摘掉 `finalize()` 里的 `_append(summary, …)` ⇒ summary 不含文件名 ⇒ 证明判据 1 的 summary 断言有牙 | 同上 |
| 5 | **结构面（防后人删掉）**：`pr-check.yml` 该腿的**全量档与 narrow 档都必须走包装器**；`scripts/ci_helper_progress.py` 必须**同时**具备「trap 收尾」（SIGTERM/SIGINT 装上且 `finalize` 会写 summary）与「step summary 写入」两个面 | 少任一面 ⇒ 具名红（不会静默退化成「只有进度行」） |
| 6 | **对照（防假红）**：正常结束 ⇒ 退出码 0、summary 只有 `✅` 段、**零** `::error::` | 包装器把每次绿跑都标成中断 ⇒ 红 |
| 7 | **嵌套 pytest 泄漏面（行为式）**：包在包装器里的外层再起一个 pytest，并按本仓惯例清 `PYTHONPATH`/`PYTEST_ADDOPTS`/`MIGAO_*` ⇒ 必须仍绿、不出现 `ImportError` | 插件通道被孙进程继承（首版 `PYTEST_PLUGINS`，job `140299508024`）⇒ 红 |
| 8 | **红证（继承面，结构式）**：包装器导出集合**不许**含 `PYTEST_PLUGINS`、`PYTEST_ADDOPTS` 必须带 `-p`、真 helper 的过滤元组必须**同时**清两个变量 —— 三处任一被改坏都具名红（4 个变异各自具名） | 谓词恒真 / 看不见「读数面空壳」⇒ 红 |

## 边界（照实登记）

- 「cancel 之后 `$GITHUB_STEP_SUMMARY` / annotation 是否仍可读」**本机无法验证**（要真 cancel 一次才知道）
  ⇒ 本判据只证明**三个面确实被写了**，**不**证明它们在 cancel 后还在；这一点写在 PR body 的「边界」节。
- 判据 1/2 用**极小预算 + 短挂住**复现，**不**等 CI 的 20 分钟；也**不**改任何 `timeout-minutes`。
- ⚠️ **红证形态变过一次（照实登记，不是放宽）**：判据 8 原本是**行为式**重演（把通道改回 `PYTEST_PLUGINS`
  再跑嵌套 pytest，期待 `No module named 'ci_helper_progress'`）。修泄漏时给直接子进程加了 `PYTHONPATH`，
  且判据本身会被 CI 的包装器包着跑 ⇒ 变异体那行所在的条件分支因继承来的 `PYTEST_ADDOPTS` 为真而不执行
  （本地裸跑会红、CI 形状下不红 = 环境相关）⇒ 「行为式重演已不可复现（前提被修法消除）」。
  ⇒ 改成**继承面**的结构判据（断言「导出集合」与「清理面覆盖」两处），仍能单独变红。
  判据强度不变：要防的那件事（孙进程被要求 import 一个它 import 不到的插件）仍然是同一个。
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

from unit_ci_workflows.injection import inject

REPO = Path(__file__).resolve().parents[2]
WRAPPER_REL = "scripts/ci_helper_progress.py"
WRAPPER = REPO / WRAPPER_REL
CI_REL = ".github/workflows/pr-check.yml"
JOB_ID = "ci-workflow-tests"
STEP_NAME = "Run ci workflow helper tests"
HANG_FILE = "test_zz_hangs_9114.py"

#: 嵌套 pytest 的**真** helper（它的 env 过滤元组长什么样，是本判据的现取对象）。
NESTED_HELPER_REL = "tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py"
#: helper 必须**同时**清掉的两个变量（少一个 = 泄漏面重新打开）。
FILTER_TUPLE = '"PYTHONPATH", "PYTEST_ADDOPTS"'

#: 假用例：一条挂住（远超预算）的用例 —— 判据不依赖真实 CI 时长。
HANG_SOURCE = "import time\n\n\ndef test_hangs_9114():\n    time.sleep(30)\n"
#: 对照：一条立刻通过的用例（不写弱断言，也不用恒真比较）。
PASS_SOURCE = "def test_passes_9114():\n    pass\n"

#: 复现「嵌套 pytest」的同族形态：外层在自己的进程里再起一个 pytest，并按本仓既有惯例清掉
#: `PYTHONPATH` / `PYTEST_ADDOPTS` / `MIGAO_*`（与 `tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py`
#: 的 `_pytest_in()` 逐条同款）——首版把插件走 `PYTEST_PLUGINS` 注入时，这里会 `ImportError` ⇒ 判红。
NESTED_SOURCE = """
import os
import subprocess
import sys


def test_inner_pytest_never_inherits_our_progress_plugin():
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTEST_ADDOPTS") and not k.startswith("MIGAO_")}
    proc = subprocess.run([sys.executable, "-m", "pytest", "test_inner_ok.py", "-q", "-p", "no:cacheprovider"],
                          cwd=os.path.dirname(os.path.abspath(__file__)),
                          capture_output=True, text=True, env=env, timeout=300)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-800:]
    assert "ci_helper_progress" not in out, out[-800:]
"""


def _write_case(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(source, encoding="utf-8")
    return path


def _nested_case(directory: Path) -> Path:
    """外层用例 + 一个立刻通过的内层用例（内层由外层自己起 pytest，env 已按本仓惯例清过）。"""
    _write_case(directory, "test_inner_ok.py", "def test_inner_passes():\n    return\n")
    return _write_case(directory, "test_nested_pytest_env_leak.py", NESTED_SOURCE)


def _wrapper_argv(wrapper: Path, summary: Path, case_file: Path, extra: list[str] | None = None,
                  parallel: bool = True) -> list[str]:
    """包装器 argv（`--` 之后才是真实命令；`-n 2` 复现 CI 的 xdist 形态）。"""
    cmd = [sys.executable, str(wrapper), "--label", "unit-9114", "--summary", str(summary),
           "--heartbeat-seconds", "1", "--suspect-seconds", "600"]
    cmd += list(extra or [])
    cmd += ["--", sys.executable, "-m", "pytest", str(case_file), "-q", "-p", "no:cacheprovider"]
    if parallel:
        cmd += ["-n", "2"]
    return cmd


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _run_budget(wrapper: Path, tmp_path: Path, budget: str = "4") -> tuple[subprocess.CompletedProcess, str]:
    """预算耗尽面：本地就能跑完（不真等 CI 超时）。"""
    case_file = _write_case(tmp_path, HANG_FILE, HANG_SOURCE)
    summary = tmp_path / "summary-budget.md"
    summary.write_text("", encoding="utf-8")
    proc = subprocess.run(_wrapper_argv(wrapper, summary, case_file, ["--max-runtime-seconds", budget]),
                          capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
    return proc, _read(summary)


def _run_sigterm(wrapper: Path, tmp_path: Path) -> tuple[int, str, str]:
    """trap 面：向包装器发 SIGTERM（runner cancel 时对 step 进程就是这个信号）。"""
    case_file = _write_case(tmp_path, HANG_FILE, HANG_SOURCE)
    summary = tmp_path / "summary-sigterm.md"
    summary.write_text("", encoding="utf-8")
    out_path = tmp_path / "out-sigterm.txt"
    with out_path.open("w", encoding="utf-8") as sink:
        # ⚠️ 输出**落文件**而不是 PIPE：摘掉 trap 的变异体会留下孤儿 pytest（它继承了管道）⇒
        #    `communicate()` 会一直等到孤儿 30s 的 sleep 结束（实测把这条判据拖到 121s）。
        proc = subprocess.Popen(_wrapper_argv(wrapper, summary, case_file), stdout=sink,
                                stderr=subprocess.STDOUT, text=True, cwd=str(tmp_path))
        try:
            deadline = time.time() + 120
            while time.time() < deadline:
                # 等「真的有用例在跑」——不要拿 summary 里的命令行命中当前文件名（那会假等）。
                if "进行中 1 个文件" in _read(summary):
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("SIGTERM 场景准备超时：120s 内包装器没有进入「进行中」状态")
            proc.send_signal(signal.SIGTERM)
            rc = proc.wait(timeout=180)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=30)
    return rc, _read(out_path), _read(summary)


def _mutant(tmp_path: Path, old: str, new: str, note: str) -> Path:
    """把包装器复制成变异体（模块名必须仍是 `ci_helper_progress` ⇒ 插件注入照旧生效）。"""
    source = WRAPPER.read_text(encoding="utf-8")
    mutated = inject(source, old, new, where=WRAPPER_REL)
    # 自证注入真的落上了（§34.18.3：否则「判据没红」分不清是判据没牙还是注入没生效）。
    assert mutated != source and new in mutated and old not in mutated, (
        f"变异注入没生效（{note}）：锚点 {old[:50]!r} 仍在/替换后内容不一致 —— 后续「判据没红」不可采信"
    )
    target = tmp_path / "mutant" / WRAPPER.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(mutated, encoding="utf-8")
    return target


def _error_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("::error::")]


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1：预算耗尽 ⇒ summary + annotation 都点名当前文件
# ══════════════════════════════════════════════════════════════════════════════════

def test_budget_exhaustion_names_the_stuck_file(tmp_path: Path) -> None:
    proc, summary = _run_budget(WRAPPER, tmp_path)
    assert proc.returncode == 1, (
        f"预算耗尽后包装器应以 1 退出（而不是被 cancel 成 124/143），实际 {proc.returncode}；"
        f"stdout 尾部：{proc.stdout[-600:]}"
    )
    assert f"stuck_file={HANG_FILE}" in summary, (
        f"step summary 里没有具名的当前文件（断言找 `stuck_file={HANG_FILE}`）⇒ cancel 后仍无从归因。"
        f"现取 summary：\n{summary}"
    )
    assert "## ⛔ 中断归因" in summary, f"summary 缺「中断归因」段：\n{summary}"
    errors = _error_lines(proc.stdout)
    assert errors, f"stdout 里没有任何 `::error::` annotation ⇒ 注解面没写：{proc.stdout[-800:]}"
    assert any(HANG_FILE in line for line in errors), (
        f"`::error::` annotation 没有点名当前文件（{HANG_FILE}）⇒ 归因不具名。现取：{errors}"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 2：SIGTERM（trap 面）
# ══════════════════════════════════════════════════════════════════════════════════

def test_sigterm_trap_finalizes_with_the_running_file(tmp_path: Path) -> None:
    rc, output, summary = _run_sigterm(WRAPPER, tmp_path)
    assert rc == 1, f"SIGTERM 后包装器应主动收尾并以 1 退出（不是被默认动作杀掉成 -15），实际 {rc}"
    assert "信号 SIGTERM" in summary, f"归因段没记下中断形态（应为「信号 SIGTERM」）：\n{summary}"
    assert f"stuck_file={HANG_FILE}" in summary, f"trap 收尾没点名当前文件：\n{summary}"
    assert any(HANG_FILE in line for line in _error_lines(output)), (
        f"SIGTERM 收尾没有打出具名 `::error::`（{HANG_FILE}）。现取输出：{output[-800:]}"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 3 / 4：注入式红证（trap 面 / summary 面）
# ══════════════════════════════════════════════════════════════════════════════════

def test_red_proof_removing_the_trap_stops_the_attribution(tmp_path: Path) -> None:
    """摘掉 trap ⇒ SIGTERM 变成默认动作（进程直接死）⇒ summary 里**不再**有归因段。"""
    mutant = _mutant(tmp_path, "HANDLED_SIGNALS = (signal.SIGTERM, signal.SIGINT)",
                     "HANDLED_SIGNALS = ()  # 变异：摘掉 trap", note="摘掉 trap（SIGTERM/SIGINT）")
    rc, output, summary = _run_sigterm(mutant, tmp_path)
    assert "## ⛔ 中断归因" not in summary, (
        "摘掉 trap 之后 summary 里**仍然**出现了归因段 ⇒ 那条断言对「有没有 trap」不敏感（判据 2 无牙）：\n"
        f"{summary}"
    )
    assert rc != 1, f"摘掉 trap 后包装器不应再能「主动收尾 exit 1」，实际 rc={rc}；输出：{output[-400:]}"


def test_red_proof_removing_the_summary_write_breaks_the_summary_face(tmp_path: Path) -> None:
    """摘掉 `finalize()` 里的 summary 写入 ⇒ annotation 仍在，但 summary 面**空了**。"""
    mutant = _mutant(tmp_path, '_append(summary, "\\n".join(lines) + "\\n\\n")',
                     'pass  # 变异：摘掉 summary 写入', note="摘掉 summary 写入")
    proc, summary = _run_budget(mutant, tmp_path)
    assert f"stuck_file={HANG_FILE}" not in summary, (
        "摘掉 summary 写入之后 summary 里**仍然**有 `stuck_file=` ⇒ 判据 1 的 summary 断言没有牙：\n"
        f"{summary}"
    )
    # 单变量对照：同一个变异体仍会打 annotation（证明「变的是 summary 面，不是整个 finalize」）。
    assert any(HANG_FILE in line for line in _error_lines(proc.stdout)), (
        f"变异体应只丢 summary、annotation 仍具名 ⇒ 否则变异打偏了：{proc.stdout[-600:]}"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 5：结构面（workflow 接线 + 脚本两个面）
# ══════════════════════════════════════════════════════════════════════════════════

def _load_wrapper_module():
    spec = importlib.util.spec_from_file_location("ci_helper_progress_under_test", WRAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _helper_step_run() -> str:
    doc = yaml.safe_load((REPO / CI_REL).read_text(encoding="utf-8")) or {}
    steps = ((doc.get("jobs") or {}).get(JOB_ID) or {}).get("steps") or []
    bodies = [s.get("run", "") for s in steps if isinstance(s, dict) and s.get("name") == STEP_NAME]
    assert bodies, f"现取不到 `{CI_REL}` 的 `{JOB_ID}` 里名为 `{STEP_NAME}` 的步骤 ⇒ 判据会空跑"
    return bodies[0]


def test_ci_leg_wraps_both_branches_through_the_progress_wrapper() -> None:
    """workflow 面：全量档与 narrow 档**都必须**走包装器（少一条 = 那条路径被 cancel 时零归因）。"""
    run_text = _helper_step_run()
    wrapper_lines = [line for line in run_text.splitlines() if WRAPPER_REL in line]
    assert wrapper_lines, (
        f"`{CI_REL}` 的 `{STEP_NAME}` 没有调用 `{WRAPPER_REL}` ⇒ 被人删掉了：被 cancel 时只剩 run 级"
        "「exceeded the maximum execution time」，逐文件读数全丢（issue #9114 的病灶本身）"
    )
    full = [line for line in wrapper_lines if "-m pytest tests/unit_ci_workflows" in line]
    narrow = [line for line in wrapper_lines if "--run-narrow" in line]
    assert full, (
        "全量档没走包装器（`-m pytest tests/unit_ci_workflows …` 那一行前面没有包装器）⇒ "
        "本 job 的主要执行面没有归因"
    )
    assert narrow, "narrow 档没走包装器（`--run-narrow` 那一行）⇒ 让出档被 cancel 时没有归因面"


def test_script_has_both_faces_trap_and_step_summary(tmp_path: Path) -> None:
    """脚本面：**trap 收尾** 与 **step summary 写入** 两个面必须都在（少一个即红）。"""
    module = _load_wrapper_module()

    # 面 A：trap —— 装上 SIGTERM + SIGINT，且装上的确实是我们的 handler。
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        installed = module.install_signal_handlers(lambda *_args: None)
        assert installed == [signal.SIGTERM, signal.SIGINT], (
            f"trap 面缺信号：装上的是 {installed}，期望 {[signal.SIGTERM, signal.SIGINT]} ⇒ "
            "cancel（SIGTERM）或本地 Ctrl-C（SIGINT）时会直接死掉、不写归因"
        )
        assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL, (
            "SIGTERM 仍是默认动作 ⇒ 装 handler 没有真的落到进程上（trap 面形同虚设）"
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    # 面 B：step summary —— `finalize()` 必须把「进行中的文件」写进 summary（且注解具名）。
    state = tmp_path / "state.log"
    state.write_text("K 2\nS 1000.0 tests/unit_ci_workflows/test_example_9114.py::test_x\n", encoding="utf-8")
    summary = tmp_path / "summary-structural.md"
    summary.write_text("", encoding="utf-8")
    annotation = module.finalize(summary=str(summary), state_path=str(state), label="结构面",
                                reason="单测", elapsed=12.0)
    text = _read(summary)
    assert "stuck_file=tests/unit_ci_workflows/test_example_9114.py" in text, (
        f"step summary 写入面失效：`finalize()` 没把当前文件写进 summary ⇒ cancel 后无归因。现取：\n{text}"
    )
    assert "当前文件 = tests/unit_ci_workflows/test_example_9114.py" in annotation, (
        f"annotation 面没点名当前文件：{annotation!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 6：对照（正常结束不产生假红）
# ══════════════════════════════════════════════════════════════════════════════════

def test_success_path_is_green_and_emits_no_error_annotation(tmp_path: Path) -> None:
    case_file = _write_case(tmp_path, "test_passes_9114.py", PASS_SOURCE)
    summary = tmp_path / "summary-ok.md"
    summary.write_text("", encoding="utf-8")
    proc = subprocess.run(_wrapper_argv(WRAPPER, summary, case_file, parallel=False),
                          capture_output=True, text=True, timeout=180, cwd=str(tmp_path))
    assert proc.returncode == 0, f"正常结束应以 0 退出，实际 {proc.returncode}：{proc.stdout[-600:]}"
    text = _read(summary)
    assert "## ✅" in text and "## ⛔" not in text, f"正常结束的 summary 形状不对（应只有 ✅ 段）：\n{text}"
    assert _error_lines(proc.stdout) == [], (
        f"绿跑被打上了 `::error::`（会把真红淹没）⇒ 包装器在正常路径上误报：{_error_lines(proc.stdout)}"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 7 / 8：环境变量**不许泄漏进嵌套 pytest**（本包第一轮真红：job 140299508024）
# ══════════════════════════════════════════════════════════════════════════════════

def test_nested_pytest_under_the_wrapper_does_not_inherit_the_plugin(tmp_path: Path) -> None:
    """包装器注入的插件通道**不得**被孙进程继承。

    真实现场（issue #9114 第一轮 CI 全红）：`tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py`
    用 `git archive` 解出干净树再起嵌套 pytest，并清掉 `PYTHONPATH` / `PYTEST_ADDOPTS` / `MIGAO_*`；
    首版把插件走 `PYTEST_PLUGINS` 注入 ⇒ 孙进程仍被要求 import ⇒
    `ImportError: Error importing plugin "ci_helper_progress"` ⇒ 「干净检出必须能跑」这条守卫被判红。
    """
    # 把「模拟」钉到真实现上：真 helper 必须**同时**清掉那两个变量（只清一半时它就是新的泄漏源）。
    helper = REPO / "tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py"
    assert '"PYTHONPATH", "PYTEST_ADDOPTS"' in helper.read_text(encoding="utf-8"), (
        f"{helper.name} 的嵌套 env 过滤不再同时清 `PYTHONPATH` + `PYTEST_ADDOPTS` ⇒ 本判据的模拟与真实现脱钩"
        "（要么更新本判据，要么那条 helper 会变成新的泄漏源）"
    )
    case_file = _nested_case(tmp_path)
    summary = tmp_path / "summary-nested.md"
    summary.write_text("", encoding="utf-8")
    proc = subprocess.run(_wrapper_argv(WRAPPER, summary, case_file, parallel=False),
                          capture_output=True, text=True, timeout=600, cwd=str(tmp_path))
    assert proc.returncode == 0, (
        "包在包装器里的嵌套 pytest 判红了 ⇒ 插件通道被孙进程继承（环境变量泄漏，issue #9114 第一轮真红形态）。"
        f"\n输出尾部：{(proc.stdout or '')[-1200:]}"
    )
    assert "ImportError" not in proc.stdout, f"嵌套 pytest 里出现 ImportError：{proc.stdout[-1200:]}"


def inheritance_face_problems(child_env: dict, helper_src: str,
                              plugin_module: str = "ci_helper_progress") -> list:
    """**继承面**的纯谓词（红证可在内存里构造，不必改真文件）。

    三件事缺一条就是「归因面又会被 cancel 吃掉」或「泄漏面又打开」：
    ① 包装器**不许**导出 `PYTEST_PLUGINS`（它会被孙进程继承 ⇒ issue #9114 第一轮真红）；
    ② `PYTEST_ADDOPTS` 里必须有插件加载参数（否则进度读数面根本没接上）；
    ③ 嵌套 helper 的 env 过滤必须**同时**清 `PYTHONPATH` 与 `PYTEST_ADDOPTS`。
    """
    bad: list = []
    if "PYTEST_PLUGINS" in child_env:
        bad.append("包装器导出了 `PYTEST_PLUGINS` —— 该变量会被**孙进程**继承（issue #9114 第一轮真红，"
                   "job 140299508024 的 `ImportError: Error importing plugin`）")
    if f"-p {plugin_module}" not in (child_env.get("PYTEST_ADDOPTS") or ""):
        bad.append(f"`PYTEST_ADDOPTS` 里没有 `-p {plugin_module}` ⇒ 进度读数面没接上（包装器静默变成空壳）")
    if FILTER_TUPLE not in helper_src:
        bad.append(f"`{NESTED_HELPER_REL}` 的嵌套 env 过滤不再同时清 `PYTHONPATH` + `PYTEST_ADDOPTS` "
                   "⇒ 泄漏面重新打开（只清一半等于没清）")
    return bad


def test_red_proof_inheritance_face_is_structural(tmp_path: Path) -> None:
    """**红证（结构式）**：继承面三处任一被改坏 ⇒ 覆盖谓词具名红。

    ⚠️ 形态变更，照实登记（**不是放宽**）：本判据原本是**行为式**重演 —— 把通道改回 `PYTEST_PLUGINS`
    再跑嵌套 pytest，期待 `No module named 'ci_helper_progress'`。**该前提已被修法本身消除**：
    修泄漏时给直接子进程加了 `PYTHONPATH`，而这里又被包在 CI 的包装器里跑 ⇒ 变异体那行的
    条件分支因继承来的 `PYTEST_ADDOPTS` 为真而不执行（本地裸跑与 CI 形状下行为不一致）⇒
    「行为式重演不可复现」。⇒ 改成**继承面**的结构判据：断言的是「导出集合里没有会被继承的通道」
    与「清理面同时覆盖两个变量」，仍能单独变红（下面 4 个变异各自具名红）。
    """
    module = _load_wrapper_module()
    real_env = module._child_env(str(tmp_path / "state.log"))
    helper_src = (REPO / NESTED_HELPER_REL).read_text(encoding="utf-8")
    real_problems = inheritance_face_problems(real_env, helper_src)
    assert real_problems == [], (
        "现取的继承面已经是坏的（这正是本判据要抓的形态，不是空断言）：" + "；".join(real_problems)
    )

    # 红证 ①：包装器导出 `PYTEST_PLUGINS`（= 第一轮真红的形态）
    leaked = dict(real_env, PYTEST_PLUGINS=module.PLUGIN_MODULE)
    problems = inheritance_face_problems(leaked, helper_src)
    assert any("PYTEST_PLUGINS" in item for item in problems), (
        f"导出 `PYTEST_PLUGINS` 竟然没被判红 ⇒ 判据对「泄漏通道」不敏感：{problems}"
    )

    # 红证 ②：`PYTEST_ADDOPTS` 退出通道（插件不再被加载）
    silent = {key: value for key, value in real_env.items() if key != "PYTEST_ADDOPTS"}
    problems = inheritance_face_problems(silent, helper_src)
    assert any("PYTEST_ADDOPTS" in item and "进度读数面" in item for item in problems), (
        f"摘掉 `PYTEST_ADDOPTS` 竟然没被判红 ⇒ 谓词看不见「读数面空壳」：{problems}"
    )

    # 红证 ③④：真 helper 的过滤元组少一项（各自具名红；注入先自证落下）
    for keep in ('"PYTHONPATH"', '"PYTEST_ADDOPTS"'):
        broken = inject(helper_src, FILTER_TUPLE, keep, where=NESTED_HELPER_REL)
        assert broken != helper_src and FILTER_TUPLE not in broken, (
            f"变异注入没生效（过滤元组只留 {keep}）⇒ 后续「没判红」不可采信"
        )
        problems = inheritance_face_problems(real_env, broken)
        assert any("过滤" in item for item in problems), (
            f"helper 的过滤只剩 {keep} 竟然没被判红 ⇒ 泄漏面会静默重开：{problems}"
        )
