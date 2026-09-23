# case_ids: MC-012
"""worktree 形态的依赖准备**不得**把主仓库 `node_modules` 软链进来（issue #5241）。

病灶（本机 Next 16.3.5 实测原文）：

    # 脚本自己的「依赖准备」段在 worktree 形态下做的事：
    ln -sfn <主仓库>/frontend/admin-web/node_modules <worktree>/frontend/admin-web/node_modules
    cd <worktree>/frontend/admin-web && npm run dev        # = next dev -p 3001（Next 16 默认 Turbopack）
     ✓ Ready in 1006ms
    FATAL: An unexpected Turbopack error occurred.
    Error [TurbopackInternalError]: Symlink [project]/node_modules is invalid, it points out of the filesystem root

⇒ 这条软链**形同虚设**：Turbopack 拒绝指向项目根之外的 `node_modules`。更坏的是它的**可观测形态**：
`next dev` 先打印 `✓ Ready`，脚本的健康检查是 `curl :3001/login`（45 次 ×2s）⇒ 90s 后才报
「✗ admin-web 启动失败（见 /tmp/ui-smoke-admin-web.log）」—— 文案把人指向日志，根因却在 bundler。
而 worktree 是**主用路径**（`scripts/dev-worktree.sh` + 多包并行），不是边角。

判据（可执行、不需要网络 / PG / 真装 —— 桩 `npm` 即可）：
① 从 `scripts/ui_smoke_merchant.sh` **现取**依赖准备段（不复制副本；定位 marker 取不到即 fail-closed），
   在沙箱里真跑：worktree 侧必须由 `npm ci` 装出**真目录**，且不得留下任何指向仓库外的
   `node_modules` 软链；
② 存量自愈：旧脚本已经留在 worktree 里的「指向主仓库」软链必须被摘掉后重装 —— 否则修完仍崩在同一处
   （判据只防「新装出软链」是不够的：`[ ! -e ]` 会跟着软链判真而跳过整段）；
③ fail-closed：真装失败必须非零退出，并把根因（Turbopack 拒绝根外软链）写进输出 ——
   不许静默退回「软链一下凑合」；
④ 幂等：依赖已就绪时不得重复安装（每次冒烟都重装 = 固定几分钟的税）；
⑤ 判据本体有判别力（红证/负控）：旧形态（指向仓库外的软链）必须被判否 ——
   保证 ①② 的「绿」不是判据恒真得来的；
⑥ 保真：不得用 `--webpack` 绕开 —— 那与生产/CI 的 Turbopack 不一致（issue #5241 修法乙需显式登记的差异）。

边界（照实登记，§19.1）：本文件**不真起 `next dev`**（CI 的 `ci workflow helper tests` job
不装前端依赖，起了也跑不起来）⇒ 它钉的是 Turbopack 报错的**成因**（根外 `node_modules` 软链），
不是日志字符串。真日志读数（红/绿两段）见 PR body 的「从零复算」序列。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / "scripts" / "ui_smoke_merchant.sh"
ADMIN_WEB_PKG = REPO_ROOT / "frontend" / "admin-web" / "package.json"

# 依赖准备段在脚本里由既有的分节注释界定（不新增 marker：这两个 header 本来就是给人读的分节）。
PREP_START = "# ── 1. 依赖准备"
PREP_END = "# ── 2. 起栈"

RUN_TIMEOUT_SECONDS = 120

STUB_NPM = """#!/usr/bin/env bash
# 桩 npm：记录 argv + cwd（判据只看「脚本有没有把真装委派给 worktree 里的 npm ci」），
# 并按 npm 的语义在 cwd 里落一个真 node_modules（不是软链）。
printf '%s :: %s\\n' "$PWD" "$*" >> "$STUB_NPM_LOG"
[ -z "${STUB_NPM_FAIL:-}" ] || exit 1
mkdir -p node_modules
"""


def _prep_segment() -> str:
    """取脚本里的依赖准备段。取不到即判红（fail-closed）：定位失效不得退化成「空片段扫描通过」。"""
    src = SMOKE.read_text(encoding="utf-8")
    start = src.find(PREP_START)
    end = src.find(PREP_END)
    if start < 0 or end < 0 or end <= start:
        pytest.fail(
            f"{SMOKE} 里定位不到依赖准备段（marker {PREP_START!r} → {PREP_END!r}）"
            "⇒ 本守卫未行使，不得读成通过"
        )
    seg = src[start:end]
    if len(seg) < 200 or "node_modules" not in seg:
        pytest.fail(f"依赖准备段只取到 {len(seg)} 字符 / 不含 node_modules ⇒ 判据定位失效，不得读成通过")
    return seg


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def out_of_root_node_modules(repo_root: Path) -> list[str]:
    """判据本体：仓库内**指向仓库根之外**的 `node_modules` 软链清单（空 = 合规）。

    Turbopack 的口径就是这条（`Symlink [project]/node_modules is invalid,
    it points out of the filesystem root`）—— 软链指到项目根外面即判死。
    """
    root = repo_root.resolve()
    bad: list[str] = []
    for path in repo_root.rglob("node_modules"):
        if path.is_symlink() and not _inside(path.resolve(), root):
            bad.append(str(path))
    return bad


class Sandbox:
    """worktree 形态沙箱：`main/` 有依赖（主仓库），`wt/` 无依赖（新 worktree）。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.main = tmp_path / "main"
        self.wt = tmp_path / "wt"
        self.npm_log = tmp_path / "npm.log"
        (self.main / "frontend/admin-web/node_modules/next").mkdir(parents=True)
        (self.main / "frontend/admin-web/node_modules/next/package.json").write_text(
            '{"name":"next","version":"16.3.5"}\n', encoding="utf-8"
        )
        aw = self.wt / "frontend/admin-web"
        aw.mkdir(parents=True)
        (aw / "package.json").write_text('{"name":"admin-web"}\n', encoding="utf-8")
        (aw / "package-lock.json").write_text("{}\n", encoding="utf-8")
        self.stub = tmp_path / "bin/npm"
        self.stub.parent.mkdir(parents=True, exist_ok=True)
        self.stub.write_text(STUB_NPM, encoding="utf-8")
        self.stub.chmod(0o755)

    @property
    def wt_node_modules(self) -> Path:
        return self.wt / "frontend/admin-web/node_modules"

    def run_prep(self, **env_extra: str) -> subprocess.CompletedProcess:
        script = self.tmp / "prep_run.sh"
        script.write_text("set -euo pipefail\n" + _prep_segment(), encoding="utf-8")
        env = {
            **os.environ,
            "REPO_ROOT": str(self.wt),
            "MAIN_REPO": str(self.main),
            "NPM_BIN": str(self.stub),
            "STUB_NPM_LOG": str(self.npm_log),
        }
        env.pop("PYTHON_BIN", None)
        env.update(env_extra)
        # cwd 故意放在 worktree 之外：判据要求脚本自己 `cd` 到 admin-web（不靠调用者 cwd）
        # 显式 utf-8（脚本输出含中文/勾叉）：不给 `text=True` 按宿主 locale 乱猜的机会。
        return subprocess.run(
            ["bash", str(script)],
            cwd=str(self.tmp),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=RUN_TIMEOUT_SECONDS,
        )

    def npm_calls(self) -> list[str]:
        if not self.npm_log.exists():
            return []
        return [ln for ln in self.npm_log.read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.fixture()
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_worktree_prep_installs_real_deps_instead_of_symlinking(sandbox: Sandbox):
    """① worktree 侧依赖必须真装（`npm ci` 在 worktree 内），不得软链主仓库。"""
    proc = sandbox.run_prep()
    assert proc.returncode == 0, f"依赖准备段在 worktree 形态下失败：\n{proc.stdout}\n{proc.stderr}"
    nm = sandbox.wt_node_modules
    assert nm.is_dir() and not nm.is_symlink(), (
        f"worktree 侧 {nm} 不是真目录（is_symlink={nm.is_symlink()}）—— Turbopack 拒绝根外软链（issue #5241）"
    )
    assert out_of_root_node_modules(sandbox.wt) == [], (
        f"依赖准备后 worktree 里仍有指向根外的 node_modules 软链：{out_of_root_node_modules(sandbox.wt)}"
    )
    calls = sandbox.npm_calls()
    assert len(calls) == 1, f"期望恰好一次 npm 调用（真装），实际 {calls}"
    cwd, _, args = calls[0].partition(" :: ")
    assert Path(cwd) == sandbox.wt / "frontend/admin-web", f"npm 的 cwd 必须在 worktree 的 admin-web 内：{cwd}"
    assert re.search(r"(^|\s)ci(\s|$)", args), f"必须以 `npm ci` 真装（锁文件一致），实际 argv：{args!r}"


def test_worktree_prep_heals_stale_symlink_left_by_old_script(sandbox: Sandbox):
    """② 存量自愈：旧脚本留下的根外软链必须被摘掉后重装（否则修完仍崩在同一处）。"""
    nm = sandbox.wt_node_modules
    nm.symlink_to(sandbox.main / "frontend/admin-web/node_modules")
    assert out_of_root_node_modules(sandbox.wt) != [], "前置不成立：沙箱里没造出旧形态的根外软链"
    proc = sandbox.run_prep()
    assert proc.returncode == 0, f"存量软链形态下依赖准备段失败：\n{proc.stdout}\n{proc.stderr}"
    assert not nm.is_symlink(), "旧的根外软链没被摘掉（`[ ! -e ]` 会跟着软链判真而跳过整段）"
    assert nm.is_dir(), "摘掉软链后必须真装出目录"
    assert len(sandbox.npm_calls()) == 1, f"摘链后必须真装一次，实际 {sandbox.npm_calls()}"


def test_worktree_prep_fails_closed_and_names_turbopack_root_cause(sandbox: Sandbox):
    """③ 真装失败必须非零退出 + 把根因写出来（不许静默退回软链）。"""
    proc = sandbox.run_prep(STUB_NPM_FAIL="1")
    assert proc.returncode != 0, f"真装失败却退出 0（= 后续 90s 超时 + 误导性文案）：\n{proc.stdout}"
    out = proc.stdout + proc.stderr
    assert "Turbopack" in out, f"失败文案未点出根因（Turbopack 拒绝根外 node_modules 软链）：{out!r}"
    assert sandbox.wt_node_modules.is_symlink() is False, "失败路径不得退回软链主仓库"


def test_worktree_prep_is_idempotent_when_deps_ready(sandbox: Sandbox):
    """④ 依赖已就绪 ⇒ 不重复安装（冒烟每次跑都重装是固定几分钟的税）。"""
    (sandbox.wt_node_modules / "next").mkdir(parents=True)
    (sandbox.wt_node_modules / "next/package.json").write_text('{"version":"16.3.5"}\n', encoding="utf-8")
    proc = sandbox.run_prep()
    assert proc.returncode == 0, f"依赖已就绪时依赖准备段失败：\n{proc.stdout}\n{proc.stderr}"
    assert sandbox.npm_calls() == [], f"依赖已就绪仍触发安装：{sandbox.npm_calls()}"


def test_criterion_is_not_vacuous_old_form_is_rejected(sandbox: Sandbox):
    """⑤ 负控/红证：判据本体必须判否旧形态 —— 否则 ①② 的绿可能是判据恒真。"""
    nm = sandbox.wt_node_modules
    nm.symlink_to(sandbox.main / "frontend/admin-web/node_modules")
    bad = out_of_root_node_modules(sandbox.wt)
    assert bad == [str(nm)], f"判据本体对旧形态（根外软链）必须判否，实际：{bad}"
    # 同一条判据对「真装形态」必须判过（否则它是恒否，红证无意义）
    nm.unlink()
    (nm / "next").mkdir(parents=True)
    assert out_of_root_node_modules(sandbox.wt) == [], "判据本体把真装的 node_modules 也判否（恒否 = 无判别力）"


def _effective_code(src: str) -> str:
    """去掉**整行注释**后的可执行面（判据只看真正会跑的命令）。

    ⚠️ 这条不是洁癖：脚本**必须**在注释里点名 `--webpack` / 软链这些禁忌（说明为什么不那么做），
    若判据扫全文，就会「被自己的文案喂红」（本仓已有多起同族实证）。判据要判的是**命令**。
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def test_var_expansions_are_braced_before_multibyte_chars():
    """类级回归锁：`$VAR` 紧跟非 ASCII 字符必须写成 `${VAR}`（macOS bash 3.2 会把那个字节并进变量名）。

    本机实测（本判据不是理论洁癖）：

        $ bash -c 'set -u; X=1; echo "v: $X（y）"'
        bash: X<0xEF>: unbound variable        # exit 127
        $ bash -c 'set -u; X=1; echo "v: ${X}（y）"'
        v: 1（y）                               # exit 0

    `set -u` 下这是**整个脚本当场死**（不是那句 echo 少印点东西）—— 本文件正是撞出来的：
    新写的 fail-closed 分支 `$ADMIN_WEB_DIR（` 一进就 unbound variable，根因文案根本没机会打印。
    同族既有约定见 `scripts/dev-worktree.sh`、`scripts/sync-main.sh` 的“注意”段（那两个脚本显式
    登记了这条）。本判据只锁本文件（另有两处同族存量在别的脚本里，已在 PR 里显式登记、未越界改动）。
    """
    src = _effective_code(SMOKE.read_text(encoding="utf-8"))
    bad = [
        f"第 {i} 行 ${m.group(1)}{m.group(2)}"
        for i, ln in enumerate(src.splitlines(), 1)
        for m in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)([^\x00-\x7F])", ln)
    ]
    assert bad == [], f"这些变量展开后紧跟非 ASCII 字符，必须写成 ${{VAR}}（否则 set -u 下 unbound variable）：{bad}"


def test_smoke_script_no_longer_symlinks_node_modules():
    """⑥ 回归锁：脚本里不得再出现「软链 node_modules」的命令（静态面，同族漏改处一扫即中）。"""
    code = _effective_code(SMOKE.read_text(encoding="utf-8"))
    hits = re.findall(r"^[^\n]*ln\s+-s\S*[^\n]*node_modules[^\n]*$", code, re.M)
    assert hits == [], f"脚本里仍有软链 node_modules 的命令：{hits}"
    seg = _prep_segment()
    assert re.search(r"npm", seg), f"依赖准备段必须走 npm 真装，实际片段：{seg!r}"


def test_dev_bundler_stays_turbopack_compatible_not_bypassed_with_webpack():
    """⑥ 保真：不得用 `--webpack` 绕开（与生产/CI 的 Turbopack 不一致，issue #5241 修法乙口径）。"""
    code = _effective_code(SMOKE.read_text(encoding="utf-8"))
    assert "--webpack" not in code, "冒烟脚本用 --webpack 绕开 Turbopack（保真度差异须显式登记）"
    dev = json.loads(ADMIN_WEB_PKG.read_text(encoding="utf-8"))["scripts"]["dev"]
    assert "--webpack" not in dev, f"admin-web 的 dev 脚本被改成 webpack：{dev!r}"
