# case_ids: MC-012
"""admin-web E2E 腿的「本地服务身份」前置断言（issue #4313）。

## 守的这颗地雷

`tests/playwright.config.ts` 的 `webServer` 曾是本形态：

```ts
command: 'npm run dev',            // cwd: ../frontend/admin-web —— 按请求编译**当前源码**的 dev server
port: 3001,
reuseExistingServer: !process.env.CI,   // 本地 = true
```

本地 `true` ⇒ 只要 3001 上**已有服务在听**（**另一个 checkout** / 上一轮跑留下的进程），
Playwright **直接复用**它、一条命令都不执行 ⇒ 断言与截图都在**本检出**上判定，
而页面实际来自**别的检出**的代码 ⇒ 同族的「本地/CI 行为分叉 + 静默假绿」。
CI 侧 `CI=true` ⇒ 本来就是 false ⇒ 不受影响。

**与 #4249（xiaobu H5）同族但病根不同**：#4249 那条的病根是「构建与起服务写在同一条
`webServer.command` ⇒ 复用旧服务时构建不执行 ⇒ 服务旧 `dist/`」，其对策
（`tests/xiaobu_dist_freshness.py` 的**产物内容指纹**）针对的是「构建产物」这一层；
本文件的 `command` 是 `npm run dev`，**没有构建产物层** ⇒ 内容指纹不适用（详见正式实现的 docstring）。
这里的等价判据是**服务身份**：听 3001 的进程，其工作目录是否本检出的 `frontend/admin-web`。

## 判据（`tests/admin_web_devserver_identity.py`，三态 0/1/3）

- `0` = 起服务前**无外来服务风险**：端口空闲（Playwright 会起本检出的 dev server），
  或占用者**已核实为本检出**（此时只提示「先停掉它」，因为 `reuseExistingServer: false` 会拒复用）；
- `1` = 端口被**不属于本检出**的服务占用 ⇒ **必红**（复用它会测到别的 checkout 的代码）；
- `3` = **未判定**（无 `lsof` / 取不到占用者身份）——「看不了」不得当「没问题」，故**不是 0**；
  该态由配置侧**只告警不阻塞**（硬拦面由 `reuseExistingServer: false` 独立承担）。

配置侧：`reuseExistingServer: false`（字面量；CI 侧原本就是 false ⇒ **CI 行为不变**）
+ 配置**加载期**（早于 webServer 启动）调用上述判据，且**整块包在 `if (!process.env.CI)` 里**
（CI 侧零新增路径）。

## 用例分四组

① **静态：静默复用已关闭**（本文件 + 同族全量 `tests/playwright*.config.ts`）——
   `reuseExistingServer` 必须是字面量 `false`；同族扫描落成判据（不只落成报告里的散文）。
② **静态：身份判据真的接进了配置** —— 判据文件被调用、调用点在 `webServer:` **之前**
   （配置加载期 = 起服务之前），且**只在本地**跑（`if (!process.env.CI)` 包裹 ⇒ CI 侧行为等价）。
③ **红证（对修复前文本）** —— 同一条静态判据跑**修复前**的配置文本必须**拒绝**它
   （否则判据是空断言：「不会红的判据」等于没有）。锚点 = `PRE_FIX_WEBSERVER_SNIPPET`
   （逐字节内联，出处 `9673df68`）+ 一条 git 溯源交叉校验（取不到该 commit 时**显式 skip**）。
   ⚠️ **不得把锚点绑 `origin/main` 这类可变引用**（§18.3「按可变键定位被测对象」）：本文件首版就是这么写的，
   结果 PR #4320 一合并进 main，锚点文本立刻变成「修复后」⇒ 断言**恒红**。
   **恒红面 = 本机 / 任何有完整历史的检出**；而 CI 的 pr-check 用 `fetch-depth: 1` ⇒
   `git show origin/main:…` 取不到 ⇒ 该断言当时走的是 **skip**（`1 skipped`）⇒ **CI 看不出问题**
   （本地红、CI 绿，比两边都红更难发现）。故本文件的**能力断言改为不依赖 git**（内联片段 ⇒ CI 也真跑），
   git 溯源交叉校验单独成一条、只作**保真**用途（取不到历史时显式 skip 并打印人工核法）。
④ **运行期（真监听进程 + 真 cwd + 真子进程跑 CLI）** ——
   端口空闲 ⇒ 0（且不依赖 lsof）；**外来 checkout 的服务占用 ⇒ 1 且点名外来路径**（本单核心场景，
   旧形态下它会静默测错对象）；本检出的服务占用 ⇒ 0 但提示先停掉（身份可区分）；
   目录**长得像** admin-web（同名 + 有 package.json）但 realpath 不同 ⇒ **仍判外来**（不靠名字/内容自报）；
   无 lsof ⇒ 3（未判定 ≠ 通过）；`--project` 给错 ⇒ 3。

## 边界（照实登记，别把「有护栏」读成「无死角」）

- 身份判据 = **本机进程表**（`lsof`）上的 cwd，**只覆盖同机**：跨主机/容器复用的服务（把
  `BASE_URL` 指到外部）不在本判据视野内 —— 但那种形态下 3001 上没有监听者，
  `reuseExistingServer: false` 会让 Playwright 自己起本检出的服务，故仍不会「静默测错对象」。
- 无 `lsof` 的机器 ⇒ 身份**未判定**（3，只告警）：此时**硬拦面**由 `reuseExistingServer: false`
  承担（任何已存在的监听者 ⇒ Playwright 报错退出），本判据只是把「谁在听」这件事**说清楚**。
- 本包**未新增用例**：沿用 `tests/unit_ci_workflows/` 同族既有 case id `MC-012`
  （同 `test_xiaobu_h5_dist_freshness.py`（#4249）/ `test_red_proof_guard.py`（#4260）口径），
  塞进行为用例库会污染覆盖矩阵。

## 沿革（照实登记）

- #4313 首次交付（PR #4320，合并 commit `8bf2eac0`）：`reuseExistingServer: false` + 服务身份前置断言 +
  本文件。当时红证锚点绑的是 **`origin/main`**。
- 跟随修复（本 PR，issue 4331）：**锚点改绑不可变引用**（内联片段 + `9673df68` 溯源校验）。原写法在合并后自红 ——
  病根与 #4313 同族（**按可变键定位被测对象**）：`origin/main` 是移动靶，修复一进 main，锚点就变成「修复后」文本。
  **归因照实**：恒红面 = **本机 / 任何有完整历史的检出**（实测 `1 failed, 11 passed`）；
  CI 的 pr-check 用 `fetch-depth: 1` ⇒ `git show origin/main:…` 取不到 ⇒ 原写法在 CI 走 **skip**
  ⇒ **CI 绿、本地红**（不是「阻塞所有 PR」—— 父会话复核 PR #4326 的该 job：失败清单 5 条全是另一个包的
  `test_pr_body_guard.py`，本文件命中 0 次）。本 PR 把**能力断言改成不依赖 git** ⇒ CI 也真跑；
  只留一条 git 溯源交叉校验按需 skip（**显式**，且打印人工核法：
  `git show 9673df68:tests/playwright.config.ts` 与内联片段对读）。
- 顺带裁定（**不做**）：考虑过给判据加 Linux `/proc` 解析以摆脱 `lsof` 依赖。CI 实证**不需要** ——
  合并后 `ci workflow helper unit tests` 在 ubuntu runner 上 **pass**（2m4s），说明 12 条含 `lsof` 路径的
  判据在 CI 真跑过（`lsof` 在该 runner 上存在；`actions/runner-images` 的 apt 清单不含它，但清单不是全集）。
  故按「最少代码」不引入第二套机制（缺 `lsof` 时判据退化为「未判定 + 告警」，硬拦面 `reuseExistingServer: false`
  不受影响）。
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
CONFIG = TESTS_DIR / "playwright.config.ts"
GUARD = TESTS_DIR / "admin_web_devserver_identity.py"
GUARD_BASENAME = GUARD.name
ADMIN_WEB_DIR = "frontend/admin-web"

# 复用 #4249 的判据实现（`_slice_block` / `find_reuse_setting`），**不复制第二份**
# —— 同族文件同口径，避免两套解析各自漂移。
sys.path.append(str(Path(__file__).resolve().parent))
from test_xiaobu_h5_dist_freshness import find_reuse_setting  # noqa: E402


# ── 静态判据（纯文本，可对任意版本的配置文本跑 —— 红证靠它跑内联的修复前片段）──

def scan_family_reuse_settings() -> dict:
    """同族全量核对表：`tests/playwright*.config.ts` → 各自的 `reuseExistingServer` 右值。"""
    return {
        path.name: find_reuse_setting(path.read_text(encoding="utf-8"))
        for path in sorted(TESTS_DIR.glob("playwright*.config.ts"))
    }


def guard_runs_before_webserver(text: str) -> bool:
    """身份判据的调用点是否在 `webServer:` 之前（= 配置加载期，早于起服务）。"""
    guard_at = text.find(GUARD_BASENAME)
    webserver_at = text.find("webServer:")
    return guard_at >= 0 and webserver_at >= 0 and guard_at < webserver_at


def guard_is_ci_gated(text: str) -> bool:
    """身份判据是否整块包在 `if (!process.env.CI)` 里（CI 侧零新增行为）。

    形态假设（本仓库 2 空格缩进、块结束的 `}` 顶格）：判据调用点之前最近的
    `if (!process.env.CI)` 与调用点之间不得出现顶格的块结束 `}`。
    """
    guard_at = text.find(GUARD_BASENAME)
    if guard_at < 0:
        return False
    marker = text.rfind("if (!process.env.CI)", 0, guard_at)
    if marker < 0:
        return False
    return "\n}" not in text[marker:guard_at]


# 修复前的原样片段（**不可变引用**）：逐字节取自 `9673df68:tests/playwright.config.ts`（#4313 的
# 修复基线提交）。红证锚点**不得**绑 `origin/main` 这类**可变**引用 —— 那正是本仓 §18.3 的病
# 「按可变键定位被测对象」：修复一合并进 main，锚点就变成「修复后」文本 ⇒ 断言恒红
# （实测：PR #4320 合并后，本机 `1 failed, 11 passed`；CI 因 `fetch-depth: 1` 取不到 `origin/main`
#  ⇒ 原写法在 CI 走 skip ⇒ **CI 绿、本地红**）。
PRE_FIX_CONFIG_REF = "9673df68"
# 修复前 `reuseExistingServer` 的右值（保真判据的**精确**锚点，不依赖 git ⇒ CI 也真跑）
PRE_FIX_REUSE_VALUE = "!process.env.CI"
PRE_FIX_WEBSERVER_SNIPPET = """
  // CI 也启动本地 Next.js dev server，E2E 测的是 PR 新代码而非旧部署
  webServer: {
    command: 'npm run dev',
    cwd: '../frontend/admin-web',
    port: 3001,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      // 前端 API 请求走远程 dev admin-api（CI 里没有本地 Java 后端）
      NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080',
    },
  },
});
"""


def historical_config_text(ref: str = PRE_FIX_CONFIG_REF):
    """`ref` 上的配置文本；取不到（浅克隆 / 无 git / 该 commit 不在本地）⇒ None（调用方显式 skip）。"""
    try:
        r = subprocess.run(
            ["git", "show", f"{ref}:tests/{CONFIG.name}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
    except OSError:  # 环境里没有 git：与「取不到该 commit」同等对待（显式 skip，不是崩）
        return None
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


# ── ① 静态：静默复用已关闭 ──

def test_admin_web_config_does_not_reuse_existing_dev_server():
    setting = find_reuse_setting(CONFIG.read_text(encoding="utf-8"))
    assert setting == "false", (
        f"`reuseExistingServer` = `{setting or '(缺失)'}` —— 本地复用「已在 3001 上监听的服务」时，"
        "Playwright 一条 webServer 命令都不执行，可能打的是**另一个检出**的代码，"
        "而断言与截图都在本检出上判定 ⇒ 静默假绿（issue #4313）。"
        "必须显式 false：端口被占 ⇒ 报错退出（可行动），而不是静默复用。"
    )


def test_no_playwright_config_allows_silent_reuse():
    table = scan_family_reuse_settings()
    assert table, "没扫到任何 tests/playwright*.config.ts —— 同族扫描空跑（判据失效）"
    offenders = {name: value or "(缺失)" for name, value in table.items() if value != "false"}
    assert offenders == {}, (
        f"同族配置里仍有允许本地静默复用的：{offenders}\n全表：{table}"
    )


# ── ② 静态：身份判据真的接进了配置（加载期 + 只在本地）──

def test_identity_guard_is_wired_at_config_load_time():
    text = CONFIG.read_text(encoding="utf-8")
    assert GUARD_BASENAME in text, (
        f"配置里没有接本地服务身份判据 `{GUARD_BASENAME}`（issue #4313 的结构化判据）"
    )
    assert guard_runs_before_webserver(text), (
        "身份判据必须写在配置加载期（`webServer:` 之前）—— 放在测试体 / globalSetup 里"
        "不能保证早于 Playwright 连上那个已被占用的 3001。"
    )


def test_identity_guard_does_not_run_in_ci():
    text = CONFIG.read_text(encoding="utf-8")
    assert guard_is_ci_gated(text), (
        "身份判据必须整块包在 `if (!process.env.CI)` 里 —— CI 侧（`CI=true`）行为必须与改动前"
        "完全等价：那里 `reuseExistingServer` 本来就是 false，且本地进程表的判据在 CI 上无意义。"
    )
    assert "reuseExistingServer: false" in text, (
        "硬拦面必须是字面量 `reuseExistingServer: false`（CI 侧原本即 false ⇒ 行为不变）；"
        "身份判据只负责把「谁在听」说清楚，不能是唯一防线。"
    )
    assert re.search(r"status\s*===\s*3", text), (
        "exit 3（未判定：无 lsof）必须只告警不阻塞 —— 否则装了本地 E2E 却缺少 lsof 的机器会假红。"
    )


# ── ③ 红证：同一条判据对「修复前」文本必须拒绝（锚点 = 不可变引用，见 PRE_FIX_WEBSERVER_SNIPPET）──

def test_criterion_rejects_pre_fix_config_text():
    """判据的**判别力**：修复前的形态必须被拒（否则是空断言）。

    锚点逐字节内联 ⇒ **不依赖 git** ⇒ CI（`fetch-depth: 1`）也真跑、**永不 skip**。
    """
    old_setting = find_reuse_setting(PRE_FIX_WEBSERVER_SNIPPET)
    # ① 保真：内联片段必须原样保留修复前的右值（防「把片段改成好过的样子」来糊弄锚点）
    assert old_setting == PRE_FIX_REUSE_VALUE, (
        f"内联的修复前片段右值 = `{old_setting}`，与修复前的 `{PRE_FIX_REUSE_VALUE}` 不一致 —— "
        f"锚点数据被改过？（出处见 PRE_FIX_CONFIG_REF，人工核法："
        f"`git show {PRE_FIX_CONFIG_REF}:tests/playwright.config.ts`）"
    )
    # ② 判别力：判据对「修复前」形态必须给出「未修」的结论
    assert old_setting != "false", (
        f"对修复前的旧文本，判据居然也判「已修」（读到 `{old_setting}`）—— 说明这条判据是空断言"
        "（不会红的判据 = 没有判据）。"
    )
    assert not guard_is_ci_gated(PRE_FIX_WEBSERVER_SNIPPET), (
        "旧文本里居然存在「受 CI 门控的身份判据」—— 红证取错对象了"
    )


def test_pre_fix_snippet_matches_history_when_available():
    """溯源交叉校验：内联片段确实与 `PRE_FIX_CONFIG_REF` 的历史文本一致（防锚点被悄悄改好过）。

    ⚠️ 本条**只作保真用途**，能力断言（上一条）不依赖它 ⇒ 它 skip 时判别力仍在。
    该 commit 不在本地（浅克隆 / CI 默认 `fetch-depth: 1`）或环境无 git ⇒ **显式 skip**（不是静默通过），
    并打印人工核法。
    """
    historical = historical_config_text()
    if historical is None:
        pytest.skip(
            f"取不到 {PRE_FIX_CONFIG_REF}:tests/{CONFIG.name}（浅克隆 / 无 git）—— 溯源交叉校验跳过；"
            f"人工核法：`git show {PRE_FIX_CONFIG_REF}:tests/{CONFIG.name}` 与内联片段对读。"
            "判别力不受影响：test_criterion_rejects_pre_fix_config_text 用的是内联锚点，不读 git。"
        )
    assert find_reuse_setting(historical) == find_reuse_setting(PRE_FIX_WEBSERVER_SNIPPET), (
        "内联的修复前片段与历史文本不一致（`reuseExistingServer` 右值不同）—— 锚点被改过？"
    )
    assert not guard_is_ci_gated(historical), (
        f"{PRE_FIX_CONFIG_REF} 的历史文本里已有受 CI 门控的身份判据 —— 基线 commit 取错了"
    )


# ── ④ 运行期：真监听进程 + 真 cwd + 真子进程 ──

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_listening(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"夹具监听进程没能在 {timeout}s 内起在 {port} 上")


class Listener:
    """夹具：在 `cwd` 目录里起一个真监听进程（真进程表里真 cwd，不 mock 判据）。"""

    def __init__(self, cwd: Path, port: int):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=str(cwd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_listening(port)
        except BaseException:
            self.proc.kill()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 收尾兜底
            self.proc.kill()


def run_guard(*args: str, path_override: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if path_override is not None:
        env["PATH"] = path_override
    return subprocess.run(
        [sys.executable, str(GUARD), "check", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120, env=env,
    )


def make_checkout(root: Path, name: str) -> Path:
    """造一个「检出」目录（`<root>/<name>/frontend/admin-web`，带 package.json）。"""
    project = root / name / ADMIN_WEB_DIR
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name": "admin-web"}\n', encoding="utf-8")
    return project


def test_free_port_is_ok(tmp_path):
    port = free_port()
    r = run_guard("--project", str(make_checkout(tmp_path, "this-checkout")), "--port", str(port))
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"端口空闲却判红了：\n{out}"
    assert "空闲" in out, f"端口空闲的判定没点名（信息不可读）：\n{out}"


def test_free_port_check_does_not_depend_on_lsof(tmp_path):
    port = free_port()
    r = run_guard(
        "--project", str(make_checkout(tmp_path, "this-checkout")),
        "--port", str(port), path_override="/nonexistent-bin",
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, (
        f"「端口空闲」这个结论只靠一次 TCP 探测即可得出，不该因为机器上没有 lsof 就变成未判定：\n{out}"
    )


def test_foreign_checkout_listener_is_red_and_named(tmp_path):
    """本单核心场景：3001 已被**另一个 checkout**的服务占用 ⇒ 判据必红、且点名外来路径。"""
    mine = make_checkout(tmp_path, "this-checkout")
    foreign = make_checkout(tmp_path, "other-checkout")
    port = free_port()
    with Listener(foreign, port):
        r = run_guard("--project", str(mine), "--port", str(port))
    out = r.stdout + r.stderr
    assert r.returncode == 1, (
        f"3001 被另一个 checkout 的服务占用却判绿 —— 这正是本单要治的形态"
        f"（跑出来的绿是别人代码的绿）：\n{out}"
    )
    assert "被不属于本检出的服务占用" in out, f"报错没点名判据（外来服务）：\n{out}"
    assert os.path.realpath(foreign) in out, f"报错没点名外来服务的 cwd（不可行动）：\n{out}"
    assert os.path.realpath(mine) in out, f"报错没点名本检出期望的 cwd（不可行动）：\n{out}"


def test_own_checkout_listener_is_identity_verified(tmp_path):
    """听 3001 的确实是本检出的进程 ⇒ 身份核实通过（0），但仍提示先停掉（reuse=false 会拒复用）。"""
    mine = make_checkout(tmp_path, "this-checkout")
    port = free_port()
    with Listener(mine, port):
        r = run_guard("--project", str(mine), "--port", str(port))
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"占用者就是本检出的进程却被判成外来（假红）：\n{out}"
    assert "被本检出的 dev server 占用" in out, f"没有把「是本检出」这个身份结论说出来：\n{out}"


def test_identity_is_not_fooled_by_lookalike_directory(tmp_path):
    """目录**长得像** admin-web（同名目录 + 同名 package.json）但 realpath 不同 ⇒ 仍判外来。"""
    mine = make_checkout(tmp_path, "this-checkout")
    foreign = make_checkout(tmp_path, "other-checkout")
    assert foreign.name == mine.name, "夹具失效：两边目录名应该一样（判据不许靠名字认亲）"
    port = free_port()
    with Listener(foreign, port):
        r = run_guard("--project", str(mine), "--port", str(port))
    out = r.stdout + r.stderr
    assert r.returncode == 1, (
        f"仅凭「目录名/包名像 admin-web」就认定是本检出 ⇒ 判据退化成自报家门：\n{out}"
    )


def test_undecidable_without_lsof_is_not_a_pass(tmp_path):
    mine = make_checkout(tmp_path, "this-checkout")
    foreign = make_checkout(tmp_path, "other-checkout")
    port = free_port()
    with Listener(foreign, port):
        r = run_guard("--project", str(mine), "--port", str(port), path_override="/nonexistent-bin")
    out = r.stdout + r.stderr
    assert r.returncode == 3, (
        f"取不到占用者身份（没有 lsof）时**不得**当「没问题」——必须是未判定 exit 3：\n{out}"
    )
    assert "未判定" in out, f"未判定的报错没点名（会被读成通过）：\n{out}"


def test_missing_project_dir_is_undecidable(tmp_path):
    port = free_port()
    r = run_guard("--project", str(tmp_path / "no-such-dir"), "--port", str(port))
    out = r.stdout + r.stderr
    assert r.returncode == 3, f"`--project` 给错（判不了身份）必须是未判定而不是通过：\n{out}"
