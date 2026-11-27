#!/usr/bin/env python3
"""长任务（`ci workflow helper unit tests` 分片腿）被 cancel / 挂住时的**归因兜底**（issue #9114）。

## 病（durable 现场，不是估算）

required job 被 cancel 之后 **job 日志拿不到** —— `gh api …/actions/jobs/<id>/logs` 返回
`<Error><Code>BlobNotFound</Code>`（HTTP 404），`gh run view <run> --log-failed` / `--log` 都是空：

| job | 场景 | 观测 |
|---|---|---|
| `138101912467` | #9097 的长任务撞 20 分钟 | `steps[7]` 有 `started_at`、**无** `completed_at`；日志 `BlobNotFound` |
| `138155419427` | #9111 的「中后段」分片撞 20 分钟 | 同上；日志 `BlobNotFound` |

⇒ 「超时类事故」只能拿到 run 级的 `exceeded the maximum execution time`，**逐文件读数全丢**
（#9102 分片吃顶时最初就是零读数）。

## 三个归因面（**每个面都独立于 job 日志 blob**）

| 面 | 谁写 | 落点 |
|---|---|---|
| `$GITHUB_STEP_SUMMARY` | 运行中每 `--heartbeat-seconds` 一次 + 收尾一次 | step summary 文件（job 页面可见） |
| `::error::` annotation | 超过 `--suspect-seconds` 起每心跳一条（≤ `--max-annotations`）+ 收尾一条 | annotations 接口（与日志 blob 不是同一条链路） |
| stdout | 每进入一个判据文件一行 `[progress] ▶ <文件>` + 心跳 | job 日志（若它在） |

⚠️ **边界（照实登记，未定论）**：「cancel 之后 step summary / annotation 是否仍可读」本机**无法验证**
（要真 cancel 一次才知道）⇒ 所以**三个面同时写**，任一面活下来就有归因；本文件不声称已验证其中任何一个。

## 形态

    python3 scripts/ci_helper_progress.py --label "helper 3/4" -- <命令...>

- 子进程在**独立进程组**里跑（`start_new_session=True`）⇒ 收尾时能整组送走（不给 runner 留孤儿 pytest）；
- **五个出口都走同一个 `finalize()`**：SIGTERM / SIGINT / `--max-runtime-seconds` 预算耗尽 /
  子进程非零退出 / 子进程正常退出 ⇒ 「被掐死」不再是唯一结局；
- 进度读数由 **pytest 插件**（本文件同时是插件）写进 `--state-file`：
  `K <n>`（收集数）/ `S <epoch> <nodeid>` / `E <outcome> <nodeid>`。
  插件由本包装器**只注入给子进程**（`PYTHONPATH` + `PYTEST_ADDOPTS="-p <本模块>"`），**不改 pytest argv** ——
  同源契约 `tests/unit_ci_workflows/test_ci_helper_leg.py` 要求 CI 与 `verify-all.sh` 的 argv 逐字相同。

## 🔴 为什么走 `PYTEST_ADDOPTS` 而不是 `PYTEST_PLUGINS`（本包第一轮真红）

首版用 `PYTEST_PLUGINS=ci_helper_progress` 注入，`（中后段）` 整片判红（job `140299508024`）：
该变量会被**孙进程**继承 —— `tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py`
会把 `HEAD` 用 `git archive` 解成干净树再起**嵌套 pytest**，而它按既有惯例清掉
`PYTHONPATH` / `PYTEST_ADDOPTS` / `MIGAO_*`（`migao-dev-flow` §34.14「`MIGAO_CI_HELPER_SHARD` 泄漏进
嵌套 clean 检出 ⇒ 假红」同族）⇒ 嵌套 pytest 拿不到 `scripts/`，却仍被要求 import 插件 ⇒
`ImportError: Error importing plugin "ci_helper_progress"`，把「干净检出能不能跑」这条守卫判红。
⇒ 走**本仓已明确清理**的那条通道（`PYTEST_ADDOPTS`）：嵌套跑既不 import、也就不污染外层读数。
判据 = `tests/unit_ci_workflows/test_ci_helper_progress.py` 的
`test_nested_pytest_under_the_wrapper_does_not_inherit_the_plugin`（含「换回 `PYTEST_PLUGINS` ⇒ 红」的红证）。

## 判据

`tests/unit_ci_workflows/test_ci_helper_progress.py`（预算耗尽 / SIGTERM / 注入式红证 / 结构面）。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: 本机时区（issue #5352）：一切时间表达一律 +08，引用 GitHub 的 UTC 读数要换算。
CST = timezone(timedelta(hours=8))

#: 插件 ⇄ 包装器之间的事件流（子进程环境变量；未设 ⇒ 插件不产生任何写入/打印）。
STATE_ENV = "MIGAO_CI_PROGRESS_STATE"

#: 插件模块名（= 本文件名）⇒ 包装器给子进程注入 `PYTEST_ADDOPTS="-p ci_helper_progress"`。
#: 🔴 **不要改回 `PYTEST_PLUGINS`**：那个变量会被嵌套 pytest 继承（见模块 docstring 的「第一轮真红」）。
PLUGIN_MODULE = Path(__file__).stem

#: trap 覆盖的信号：cancel / 超时在 runner 侧表现为 SIGTERM，本地 Ctrl-C 是 SIGINT。
HANDLED_SIGNALS = (signal.SIGTERM, signal.SIGINT)

#: 摘要里最多点名几个「进行中」的文件（再多也不会更可归因，只会淹掉重点）。
MAX_STUCK_FILES = 4

_INTERRUPT: dict = {"reason": None}


# ══════════════════════════════════════════════════════════════════════════════════
# 三个归因面的原语
# ══════════════════════════════════════════════════════════════════════════════════

def _append(path: str, text: str) -> None:
    """往 step summary / 事件流追加一行：**单次 `os.write` + `O_APPEND`**。

    为什么不用 `open(..., "a").write()`：本函数的调用方可能不止一个进程（插件在 xdist 的
    每个 worker 里跑），而这里要的正是「多写者、单行、不重排」。
    """
    if not path:
        return
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _emit(kind: str, message: str) -> str:
    """打一条 GitHub 注解（`::error::` / `::warning::`）：单行、无 `%`、无换行。返回那一行。"""
    line = f"::{kind}::" + " ".join(str(message).replace("%", "％").split())
    print(line, flush=True)
    return line


def _stamp(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, CST).strftime("%Y-%m-%d %H:%M:%S +08")


def read_state(path: str) -> dict:
    """解析事件流 ⇒ `{total, completed, inflight:[(nodeid, start_epoch)]}`（按开始时间升序）。"""
    total, completed, started = 0, 0, {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"total": 0, "completed": 0, "inflight": []}
    for raw in text.splitlines():
        parts = raw.split(" ")
        if not parts:
            continue
        if parts[0] == "K" and len(parts) >= 2 and parts[1].isdigit():
            # xdist 下每个 worker 都收集**全量** ⇒ 取 max 才是本轮的总数（不是求和）。
            total = max(total, int(parts[1]))
        elif parts[0] == "S" and len(parts) >= 3:
            started.setdefault(" ".join(parts[2:]), float(parts[1]) if parts[1].replace(".", "").isdigit() else time.time())
        elif parts[0] == "E" and len(parts) >= 3:
            completed += 1
            started.pop(" ".join(parts[2:]), None)
    return {"total": total, "completed": completed,
            "inflight": sorted(started.items(), key=lambda kv: kv[1])}


def inflight_files(inflight: list) -> list:
    """进行中的**判据文件**（去重、保持「最久未完成在前」的顺序）。"""
    files: list = []
    for nodeid, _ in inflight:
        name = nodeid.split("::", 1)[0]
        if name not in files:
            files.append(name)
    return files


def finalize(*, summary: str, state_path: str, label: str, reason: str,
             elapsed: float, exit_code: int | None = None) -> str:
    """收尾（trap 面）：把「当前文件 + 已完成 N/M」落 summary + `::error::`，返回注解那一行。"""
    snap = read_state(state_path)
    files = inflight_files(snap["inflight"])
    total = snap["total"] or "?"
    lines = [
        f"## ⛔ 中断归因（{label} · issue #9114）",
        f"- 形态：{reason} · 已跑 {elapsed:.1f}s · 退出码 {exit_code if exit_code is not None else '无（被中断）'}",
        f"- 进度：已完成 **{snap['completed']}/{total}** 条用例",
    ]
    if files:
        lines.append(f"- 进行中（最久未完成在前，共 {len(files)} 个判据文件）：")
        for name in files[:MAX_STUCK_FILES]:
            began = next(b for nid, b in snap["inflight"] if nid.split("::", 1)[0] == name)
            lines.append(f"  - `stuck_file={name}`（该文件当前用例已运行 {max(0.0, time.time() - began):.0f}s）")
    else:
        lines.append("- 进行中：无（用例都已收尾 ⇒ 不是挂住；本段仍留作「谁中断了它」的证据）")
    lines.append(f"- 复算：事件流 `{state_path}`（`RUNNER_TEMP` 下，job 结束后不保证还在）")
    _append(summary, "\n".join(lines) + "\n\n")
    if not files:
        # ⚠️ 没有「进行中的文件」= 不是挂住（例如 pytest 真失败）⇒ **不发明**一个卡住的文件名：
        #    宁可少一条注解，也不给下一个人一个错的锚点。
        return ""
    return _emit("error",
                 f"{label} 被[{reason}]中断：当前文件 = {files[0]}"
                 f"（进行中 {len(files)} 个：{', '.join(files[:MAX_STUCK_FILES])}）；"
                 f"已完成 {snap['completed']}/{total} 条用例。"
                 f"若本 job 日志为 BlobNotFound（issue #9114），本注解 + step summary 就是唯一归因面")


def report_success(*, summary: str, state_path: str, label: str, elapsed: float) -> None:
    """正常结束面：只落一行「完成」，**不产生**任何 `::error::`（否则真红会被噪声淹没）。"""
    snap = read_state(state_path)
    total = snap["total"] or "?"
    _append(summary, f"## ✅ {label} 正常结束\n- 已完成 **{snap['completed']}/{total}** 条用例 · {elapsed:.1f}s\n\n")
    print(f"[progress] ✅ {label} 正常结束：{snap['completed']}/{total} 条用例 · {elapsed:.1f}s", flush=True)


def heartbeat(*, summary: str, state_path: str, label: str, elapsed: float, suspect: bool) -> None:
    """心跳面：summary 一行 + stdout 一行；过嫌疑阈时额外打一条 `::error::`（带进行中的文件）。"""
    snap = read_state(state_path)
    files = inflight_files(snap["inflight"])
    total = snap["total"] or "?"
    text = (f"- 心跳 {_stamp()}：已完成 {snap['completed']}/{total} 条用例 · 进行中 {len(files)} 个文件"
            + (f"：{', '.join(files[:MAX_STUCK_FILES])}" if files else ""))
    _append(summary, text + "\n")
    print(f"[progress] {text[2:]}", flush=True)
    if suspect and files:
        _emit("error", f"{label} 已运行 {elapsed:.0f}s（超过嫌疑阈）：当前文件 = {files[0]}"
                       f"（进行中 {len(files)} 个），已完成 {snap['completed']}/{total} 条用例")


# ══════════════════════════════════════════════════════════════════════════════════
# trap 面：信号
# ══════════════════════════════════════════════════════════════════════════════════

def install_signal_handlers(handler) -> list:
    """装上 trap（`SIGTERM` / `SIGINT`）并返回装上的信号列表。

    判据直接调它（`tests/unit_ci_workflows/test_ci_helper_progress.py`）——
    删掉任一信号 ⇒ 返回列表少一项 ⇒ 具名红。
    """
    installed = []
    for sig in HANDLED_SIGNALS:
        signal.signal(sig, handler)
        installed.append(sig)
    return installed


def _on_signal(signum, _frame) -> None:
    _INTERRUPT["reason"] = f"信号 {signal.Signals(signum).name}"


def _kill_group(child: subprocess.Popen, sig) -> None:
    """整组送走（子进程是 `start_new_session=True` 起的 ⇒ 组号 = 它的 pid）。"""
    try:
        os.killpg(os.getpgid(child.pid), sig)
    except (ProcessLookupError, PermissionError):
        pass


# ══════════════════════════════════════════════════════════════════════════════════
# pytest 插件面（本文件同时是插件：包装器只把它注入给**子进程**）
# ══════════════════════════════════════════════════════════════════════════════════

_SEEN_FILES: set = set()


def _state_line(line: str) -> None:
    _append(os.environ.get(STATE_ENV, ""), line + "\n")


def pytest_collection_modifyitems(session, config, items):  # noqa: ARG001 - pytest 钩子签名
    if os.environ.get(STATE_ENV):
        _state_line(f"K {len(items)}")


def pytest_runtest_logstart(nodeid, location):  # noqa: ARG001 - pytest 钩子签名
    if not os.environ.get(STATE_ENV):
        return
    _state_line(f"S {time.time():.3f} {nodeid}")
    name = nodeid.split("::", 1)[0]
    if name not in _SEEN_FILES:
        _SEEN_FILES.add(name)
        print(f"[progress] ▶ {name}", flush=True)


def pytest_runtest_logreport(report):
    if not os.environ.get(STATE_ENV):
        return
    if report.when == "call" or (report.when == "setup" and report.failed):
        _state_line(f"E {report.outcome} {report.nodeid}")


# ══════════════════════════════════════════════════════════════════════════════════
# 包装器
# ══════════════════════════════════════════════════════════════════════════════════

def _child_env(state_path: str) -> dict:
    """给**子进程**注入插件接线（不污染 workflow 的 step 级环境，不改 pytest argv）。

    🔴 通道选择见模块 docstring：`PYTEST_ADDOPTS` 是**本仓嵌套 pytest 会显式清掉**的变量
    （`tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py` 清 `PYTHONPATH` /
    `PYTEST_ADDOPTS` / `MIGAO_*`）⇒ 孙进程不会被迫 import 本模块。`PYTEST_PLUGINS` 不满足这一点。
    """
    env = dict(os.environ)
    scripts_dir = str(Path(__file__).resolve().parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = scripts_dir + (os.pathsep + existing if existing else "")
    addopts = env.get("PYTEST_ADDOPTS", "").strip()
    plugin_arg = f"-p {PLUGIN_MODULE}"
    if plugin_arg not in addopts:
        env["PYTEST_ADDOPTS"] = (addopts + " " + plugin_arg).strip()
    env[STATE_ENV] = state_path
    return env


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="长任务归因兜底（issue #9114）：trap + step summary + annotation")
    ap.add_argument("--label", default="ci helper", help="本片标签（写进 summary / 注解）")
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
                    help="step summary 落点（默认取 GITHUB_STEP_SUMMARY）")
    ap.add_argument("--state-file", default="", help="事件流落点（默认在临时目录新建）")
    ap.add_argument("--heartbeat-seconds", type=float, default=60.0)
    ap.add_argument("--suspect-seconds", type=float, default=600.0,
                    help="超过它就开始打 ::error::（默认 600s：实测合法最长 step ≈500s）")
    ap.add_argument("--max-runtime-seconds", type=float, default=0.0,
                    help=">0 时按预算主动收尾（默认 0 = 不主动收尾：**不改任何判据的通过条件**）")
    ap.add_argument("--max-annotations", type=int, default=3)
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="`--` 之后的真实命令")
    args = ap.parse_args(argv)

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("::error::scripts/ci_helper_progress.py 没拿到要跑的命令（用法：… -- <命令…>）", flush=True)
        return 2

    state_path = args.state_file or tempfile.mkstemp(prefix="migao-ci-progress-", suffix=".log")[1]
    Path(state_path).write_text("", encoding="utf-8")
    label = args.label
    started = time.time()
    _append(args.summary,
            f"## 🧭 {label} 进度（issue #9114：被 cancel 也要能归因）\n"
            f"- 命令：`{' '.join(cmd)}`\n- 开始：{_stamp(started)}\n"
            f"- 事件流：`{state_path}` · 心跳 {args.heartbeat_seconds:.0f}s · 嫌疑阈 {args.suspect_seconds:.0f}s\n\n")
    print(f"[progress] ▶▶ {label} 开始（{_stamp(started)}）：{' '.join(cmd)}", flush=True)

    child = subprocess.Popen(cmd, env=_child_env(state_path), start_new_session=True)
    signal_handler = lambda signum, frame: _on_signal(signum, frame)  # noqa: E731 - 需要可恢复的具名对象
    previous = {sig: signal.getsignal(sig) for sig in HANDLED_SIGNALS}
    install_signal_handlers(signal_handler)
    annotations = 0
    last_beat = started
    try:
        while True:
            now = time.time()
            elapsed = now - started
            reason = _INTERRUPT["reason"]
            if reason is None and args.max_runtime_seconds > 0 and elapsed >= args.max_runtime_seconds:
                reason = f"预算耗尽（--max-runtime-seconds {args.max_runtime_seconds:.0f}s）"
            if reason is not None:
                _kill_group(child, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    _kill_group(child, signal.SIGKILL)
                finalize(summary=args.summary, state_path=state_path, label=label,
                         reason=reason, elapsed=time.time() - started)
                return 1
            if child.poll() is not None:
                break
            if now - last_beat >= args.heartbeat_seconds:
                last_beat = now
                suspect = args.suspect_seconds > 0 and elapsed >= args.suspect_seconds and annotations < args.max_annotations
                if suspect:
                    annotations += 1
                heartbeat(summary=args.summary, state_path=state_path, label=label,
                          elapsed=elapsed, suspect=suspect)
            time.sleep(0.5)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    elapsed = time.time() - started
    rc = child.returncode
    if rc == 0:
        report_success(summary=args.summary, state_path=state_path, label=label, elapsed=elapsed)
        return 0
    finalize(summary=args.summary, state_path=state_path, label=label,
             reason=f"子进程退出码 {rc}", elapsed=elapsed, exit_code=rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
