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
| `1` | 端口被**不属于本检出**的服务占用 ⇒ **必红**（复用它会测到别的 checkout 的代码） |
| `3` | **未判定**：端口有服务在听，但取不到占用者身份（无 `lsof` / 无权限 / 非本机进程）—— 「看不了」不得当「没问题」，故**不是 0** |

配置侧对三态的处理：`0` 放行、`1` **失败关闭**、`3` **只告警不阻塞**。
「未判定不阻塞」之所以安全，是因为**硬拦面不在这里**：`reuseExistingServer: false` 独立地保证
「任何已存在的监听者 ⇒ Playwright 报错退出、绝不复用」。本判据的价值是把「谁在听」**说清楚**
（点名外来 cwd），而不是充当唯一防线 —— 这也是它敢在缺少 `lsof` 的机器上只告警的原因。

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
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FOREIGN = 1
EXIT_UNDECIDABLE = 3

DEFAULT_PORT = 3001
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


def check(project, port: int = DEFAULT_PORT) -> Verdict:
    """判定「起服务前，`port` 上有没有不属于 `project`（本检出）的服务在听」。"""
    project = Path(str(project)).expanduser()
    if not project.is_dir():
        return Verdict(
            EXIT_UNDECIDABLE,
            f"⚠️ 未判定：{project} 不是目录 —— 判不了「占用者是不是本检出」（项目根给错了？）",
        )
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
            EXIT_FOREIGN,
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
