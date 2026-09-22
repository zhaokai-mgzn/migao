#!/usr/bin/env python3
"""tests/admin_web_devserver_identity.py — admin-web E2E 腿的「本地服务身份」前置断言（issue #4313）。

## 病根（本文件是它的直接对策）

`tests/playwright.config.ts` 的 `webServer`：

```ts
command: 'npm run dev',                 // cwd: ../frontend/admin-web
port: 3001,
reuseExistingServer: !process.env.CI,   // 本地 = true
```

本地 `true` ⇒ 只要 3001 上**已有服务在听**（**另一个 checkout** / 上一轮跑留下的进程），
Playwright **直接复用它**、一条命令都不执行 ⇒ **断言与截图都在本检出上判定，页面却来自别的检出**
⇒ 同族的「本地/CI 行为分叉 + 静默假绿」。CI 侧 `CI=true` ⇒ 本来就是 false ⇒ 不受影响。

## 为什么不能复用 #4249 的 `tests/xiaobu_dist_freshness.py`（照实说明）

#4249 那条的病根是「`taro build` 与起静态服务写在同一条 `webServer.command` ⇒ 复用旧服务时整条命令
（含构建）不执行 ⇒ 服务旧 `dist/`」，其判据是**构建产物的内容指纹**（`sourceHash` / `distHash`）。
本文件的 `command` 是 `npm run dev` —— Next dev server **按请求编译当前源码**，
**不存在「构建产物」这一层**：既没有 `dist/.build-stamp.json` 可落，也没有"旧产物 vs 新源码"可分。
⇒ 内容指纹在这里**无从下手**（硬套等于给 dev server 编一个不存在的产物层）；故本文件只做它该做的那件事。

**同一颗地雷在 dev server 形态下的等价判据 = 服务身份**：
「在 3001 上监听的那个进程，其工作目录是不是本检出的 `frontend/admin-web`？」
身份来自**本机进程表**（`lsof` 的 `cwd`），**不依赖任何自报信息**（目录名/包名/响应内容都不算数）。

## 三态退出码（与仓内既有口径一致：`0` / `1` / `3`）

| code | 含义 |
|---|---|
| `0` | 起服务前**无外来服务风险**：端口空闲（Playwright 会起本检出的 dev server），或占用者**已核实为本检出**（只提示先停掉它 —— `reuseExistingServer: false` 会拒复用） |
| `1` | **必红**（两种形态）：① 端口被**不属于本检出**的服务占用（复用它会测到别的 checkout 的代码）；② **本检出已有一个活着的 `next dev`** —— Next 16 起按目录单例，换端口也起不来（见下节，issue #5121） |
| `3` | **未判定**：端口有服务在听，但取不到占用者身份（无 `lsof` / 无权限 / 非本机进程）—— 「看不了」不得当「没问题」，故**不是 0** |

配置侧对三态的处理：`0` 放行、`1` **失败关闭**、`3` **只告警不阻塞**。
「未判定不阻塞」之所以安全，是因为**硬拦面不在这里**：`reuseExistingServer: false` 独立地保证
「任何已存在的监听者 ⇒ Playwright 报错退出、绝不复用」。本判据的价值是把「谁在听」**说清楚**
（点名外来 cwd），而不是充当唯一防线 —— 这也是它敢在缺少 `lsof` 的机器上只告警的原因。

## Next 16「按目录单例」—— 第二种必红形态（issue #5121，Next 16.3.5 实测）

Next 16 起 `next dev` 在 `<projectDir>/.next/dev/lock` 上取一把 `flock`
（`node_modules/next/dist/server/lib/router-utils/setup-dev-bundler.js` 的
`Lockfile.acquireWithRetriesOrExit(path.join(distDir, 'lock'), 'next dev', ...)`）。
⇒ 同检出里第二个 `next dev` **哪怕换了端口**也会取锁失败，打印
`⨯ Another next dev server is already running.` 并 exit 1。

⇒ `ADMIN_WEB_PORT` 换端口**只在「占用者属于别的检出」时**有效；对「**本检出自己**已有一个
dev server」这个场景**不再成立** —— 这正是「端口隔离策略静默失效」：旧形态下端口空闲 ⇒ 判绿，
随后 E2E 才去撞 Next 的报错（或连错对象），而不是在起服务前被显式拒绝。

判据 = **flock 本身**（能否非阻塞取到 `LOCK_EX`），**不是**「锁文件存在」：server 崩掉会留下
锁文件（POSIX 上 flock 随进程退出释放）⇒ 只看存在性会**假红**。持有者信息（`pid` / `port` /
`appUrl`）就写在锁文件内容里，故报错能给出**可执行的**停服命令与替代做法（独立 worktree）。

边界（照实登记）：本判据读的是 **Next 的实现细节（锁路径）** —— 若上游改了这个约定，探测会
**静默退化为「没探测到」**（退回既有端口判据，不会假绿）；非 POSIX（无 `fcntl`）同理。

## 边界（照实登记）

- 身份判据看的是**本机进程表** ⇒ **只覆盖同机**。跨主机/容器（把 `BASE_URL` 指到外部服务）不在视野内；
  但那种形态下 3001 上不会有监听者，Playwright 会起本检出的服务 ⇒ 仍不会「静默测错对象」。
- 判据**与时间无关**（不读 mtime）—— 只看进程表里的 cwd；同一个 checkout 的 dev server 无论起得多早，
  都是本检出的代码（Next dev 按请求编译当前源码）⇒ 这里**不存在**「产物陈旧」这一维。
- 端口空闲的结论只需一次 TCP 探测（不需要 `lsof`）；`lsof` 只用于「占了端口的是谁」。

红证与用例见 `tests/unit_ci_workflows/test_admin_web_devserver_identity.py`（`case_ids: MC-012`）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

try:
    import fcntl  # POSIX：下面的 dev 锁判据靠 flock；非 POSIX ⇒ 该判据退化（见 docstring 边界）
except ImportError:  # pragma: no cover - 本仓只在 macOS / Linux 上跑
    fcntl = None

EXIT_OK = 0
# 必红：① 端口被别的检出占用；② 本检出已有活着的 dev server（Next 16 按目录单例，换端口也起不来）
EXIT_RED = 1
EXIT_UNDECIDABLE = 3

DEFAULT_PORT = 3001
# Next 16 的 dev server 锁（相对 admin-web 根）：`next dev` 在它上面取 flock ⇒ 按目录单例。
DEV_LOCK_RELATIVE = os.path.join(".next", "dev", "lock")
# 占用者身份（cwd）只能从进程表拿；拿不到 ⇒ 未判定（不是通过）
LSOF = "lsof"


class Verdict:
    """判定结果（`code` 即退出码）。"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message

    @property
    def ok(self) -> bool:
        return self.code == EXIT_OK

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Verdict(code={self.code}, message={self.message!r})"


def port_has_listener(port: int, timeout: float = 0.5) -> bool:
    """TCP 探测：127.0.0.1 / ::1 任一可连上 ⇒ 有服务在听（**不依赖 lsof**）。"""
    for family, addr in ((socket.AF_INET, ("127.0.0.1", port)), (socket.AF_INET6, ("::1", port, 0, 0))):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                if sock.connect_ex(addr) == 0:
                    return True
        except OSError:
            continue
    return False


def _lsof_path():
    return shutil.which(LSOF)


def listening_pids(port: int):
    """监听 `port` 的 PID 列表；`None` = 没有 lsof（未判定）；空列表 = 探到了但列不出进程。"""
    lsof = _lsof_path()
    if not lsof:
        return None
    proc = subprocess.run(
        [lsof, "-nP", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    return [int(token) for token in proc.stdout.split() if token.strip().isdigit()]


def process_cwd(pid: int):
    """进程 `pid` 的工作目录；取不到 ⇒ None（未判定）。"""
    lsof = _lsof_path()
    if not lsof:
        return None
    proc = subprocess.run(
        [lsof, "-nP", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True, text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("n"):
            name = line[1:].strip()
            return Path(name) if name else None
    return None


def _same_dir(a, b) -> bool:
    """路径等价判定（realpath 归一：符号链接 / macOS `/var` vs `/private/var` 都不算差异）。"""
    try:
        return Path(os.path.realpath(str(a))) == Path(os.path.realpath(str(b)))
    except OSError:  # pragma: no cover - realpath 对不存在的路径也不抛，这里只是兜底
        return False


def dev_lock_path(project):
    """本检出里 Next 16 dev server 的锁文件路径（`<project>/.next/dev/lock`）。"""
    return Path(project) / DEV_LOCK_RELATIVE


def read_locked_dev_server(lock_path):
    """`lock_path` 上是否**真的**有活着的 `next dev` 持有 flock。

    有 ⇒ 返回它写进锁文件的 serverInfo（`{pid, port, appUrl, ...}`；内容坏掉时给空 dict）；
    没有 ⇒ `None`（含「文件不存在」与「文件在但没人持锁」两种 —— 后者是崩掉留下的残留，不得当红）。
    """
    if fcntl is None:  # 非 POSIX：没有 flock 语义 ⇒ 不判（退回既有端口判据）
        return None
    try:
        handle = open(lock_path, "r")
    except OSError:  # 文件不存在 / 不可读 ⇒ 没有活着的持有者
        return None
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # 取不到锁 ⇒ 有别的进程持着它（Next 的 dev server）
            handle.seek(0)
            try:
                info = json.loads(handle.read())
            except ValueError:
                info = {}
            return info if isinstance(info, dict) else {}
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return None
    finally:
        handle.close()


def check_dev_server_lock(project):
    """本检出是否**已经**有一个活着的 `next dev`（Next 16 按目录单例 ⇒ 再起一个必失败）。

    返回 `Verdict`（必红 + 可行动提示）；没有 ⇒ `None`（交给既有端口判据）。
    """
    lock_path = dev_lock_path(project)
    info = read_locked_dev_server(lock_path)
    if info is None:
        return None
    pid, port = info.get("pid"), info.get("port")
    url = info.get("appUrl") or f"http://localhost:{port}"
    stop = f"kill {pid}" if pid else "先停掉本检出里那个 next dev"
    return Verdict(
        EXIT_RED,
        f"❌ 本检出已经有一个 `next dev` 在跑，而 Next 16 起 `next dev` 是**按目录单例**（issue #5121）：\n"
        f"  · 持有者：PID {pid} · port {port} · {url}\n"
        f"  · 它持着 {lock_path} 上的 flock ⇒ 再起一个 `next dev`（**哪怕换端口**）会被 Next 拒绝：\n"
        f"    `⨯ Another next dev server is already running.`\n"
        f"  ⇒ `ADMIN_WEB_PORT=<别的空闲端口>` **不能**绕开它（换端口只对「占用者属于别的检出」有效）。\n"
        f"  二选一：\n"
        f"    a) 停掉它再跑 E2E：`{stop}`\n"
        f"    b) 要留着这个 dev server ⇒ 在**独立 worktree** 里跑 E2E（独立 checkout 有自己的锁）：\n"
        f"       `./scripts/dev-worktree.sh add <branch>`",
    )


def check(project, port: int = DEFAULT_PORT) -> Verdict:
    """判定「起服务前，`port` 上有没有不属于 `project`（本检出）的服务在听」。"""
    project = Path(str(project)).expanduser()
    if not project.is_dir():
        return Verdict(
            EXIT_UNDECIDABLE,
            f"⚠️ 未判定：{project} 不是目录 —— 判不了「占用者是不是本检出」（项目根给错了？）",
        )

    # Next 16 起 `next dev` 按目录单例（**与端口无关**）⇒ 先判「本检出是否已有活着的 dev server」：
    # 那种状态下换端口也起不来，必须在起服务前就显式拒绝（而不是让 Playwright 去撞 Next 的报错）。
    already_running = check_dev_server_lock(project)
    if already_running is not None:
        return already_running

    if not port_has_listener(port):
        return Verdict(
            EXIT_OK,
            f"✔ 端口 {port} 空闲：本检出的 dev server 将由 Playwright 自己起（无外来服务风险）。",
        )

    pids = listening_pids(port)
    if pids is None:
        return Verdict(
            EXIT_UNDECIDABLE,
            f"⚠️ 未判定：端口 {port} 有服务在听，但本机没有 `{LSOF}` ⇒ 取不到占用者身份。\n"
            "  （这不是「没问题」：硬拦面由 `reuseExistingServer: false` 独立承担 —— "
            "任何已存在的监听者都会被 Playwright 拒绝复用。）",
        )
    if not pids:
        return Verdict(
            EXIT_UNDECIDABLE,
            f"⚠️ 未判定：端口 {port} 有服务在听，但 `{LSOF}` 列不出占用进程（权限不足 / 非本机监听）。\n"
            "  （同上：硬拦面由 `reuseExistingServer: false` 承担。）",
        )

    foreign, ours, unknown = [], [], []
    for pid in pids:
        cwd = process_cwd(pid)
        if cwd is None:
            unknown.append(pid)
        elif _same_dir(cwd, project):
            ours.append((pid, cwd))
        else:
            foreign.append((pid, cwd))

    if foreign:
        detail = "\n".join(f"  · PID {pid} cwd={cwd}" for pid, cwd in foreign)
        return Verdict(
            EXIT_RED,
            f"❌ 端口 {port} 被不属于本检出的服务占用：\n{detail}\n"
            f"  本检出期望的 dev server 工作目录：{Path(os.path.realpath(str(project)))}\n"
            "  ⇒ 复用它会跑在**别的 checkout**（或别的项目）的代码上，而断言与截图都在本检出上判定"
            " ⇒ 静默假绿（issue #4313）。请先停掉占用者（如 `pkill -f 'next dev -p "
            f"{port}'`），Playwright 会起本检出的 dev server。",
        )

    if ours:
        detail = "\n".join(f"  · PID {pid} cwd={cwd}" for pid, cwd in ours)
        return Verdict(
            EXIT_OK,
            f"⚠️ 端口 {port} 被本检出的 dev server 占用（身份已核实）：\n{detail}\n"
            "  `reuseExistingServer: false` ⇒ Playwright 会拒绝复用它并报错退出；"
            f"请先停掉（`pkill -f 'next dev -p {port}'`）再跑，Playwright 会起本检出的服务。",
        )

    return Verdict(
        EXIT_UNDECIDABLE,
        f"⚠️ 未判定：端口 {port} 有服务在听，但取不到其 cwd（PID {unknown}，权限不足？）。\n"
        "  （同上：硬拦面由 `reuseExistingServer: false` 承担。）",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="admin-web E2E 腿的本地服务身份前置断言（issue #4313）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    checker = sub.add_parser("check", help="判定端口占用者是否本检出（0/1/3 三态）")
    checker.add_argument("--project", required=True, help="本检出的 admin-web 目录（期望的 dev server cwd）")
    checker.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"dev server 端口（默认 {DEFAULT_PORT}）")
    args = parser.parse_args(argv)

    verdict = check(args.project, args.port)
    print(verdict.message)
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
