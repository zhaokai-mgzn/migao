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
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / "scripts" / "ui_smoke_merchant.sh"
ADMIN_WEB_PKG = REPO_ROOT / "frontend" / "admin-web" / "package.json"
SCRIPTS_DIR = REPO_ROOT / "scripts"
_BASH = shutil.which("bash") or "/bin/bash"

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
    同族既有约定见 `scripts/dev-worktree.sh`、`scripts/sync-main.sh` 的“注意”段；**存量已清零**：
    `#5260` 修掉 `scripts/sync-main.sh` / `scripts/batch-integrate-check.sh` 那两处，**`#5284` 把类级
    守卫的射程从 `scripts/**` 扩到全仓**（含仓库根 —— 那是本条遗漏的覆盖面，issue #5283 残余②同批收口）
    ⇒ 全仓受控 `*.sh` 的同族存量 12 处全部修完，守卫见
    `tests/unit_ci_workflows/test_scripts_bash32_var_brace.py`；「**声称的射程 == 实际扫描集**」由
    `tests/unit_ci_workflows/test_guard_scope_declaration.py` 常驻钉住。本判据只锁**本文件**自己。
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


# ══════════════════════════════════════════════════════════════════════════════
# issue #6777：`set -u` 下的「**可能是空**的数组」展开（同一个 bash 3.2 兼容面）
# ══════════════════════════════════════════════════════════════════════════════

#: 脚本是否开了 `set -u`（没开 ⇒ 空数组展开无害，本判据不管）。
SET_U = re.compile(r"^set\s+-[A-Za-z]*u", re.M)
#: **空字面量**初始化（`NAME=()` / `declare -a NAME=()`）—— 空是该数组的**可能状态**（可静态判定）。
EMPTY_ARRAY_INIT = re.compile(r"^\s*(?:declare\s+-[A-Za-z]*a[A-Za-z]*\s+)?([A-Za-z_][A-Za-z0-9_]*)=\(\)\s*$")
#: `${NAME[@]}` / `${NAME[*]}` 的**内层**内容（`${#NAME[@]}` 是取长度，不在此列）。
ARRAY_EXPANSION_INNER = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[([@*])\]")
#: 空值护栏形态：`${NAME[@]+"${NAME[@]}"}` / `${NAME[@]-…}`。
GUARDED_PREFIX = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\[([@*])\]\s*[+-]")
#: 脚本里修过的那一处（注入式红证的还原点：改回右侧坏形态 ⇒ 判据当场红）。
GUARDED_EXTRA_ARGS = '${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}'


def _array_expansions(line: str) -> list[tuple[str, bool]]:
    """→ `[(数组名, 是否带空值护栏)]`；每个 `${…}` 构造**整体吃掉**（内层不再单独判）。

    为什么必须整体吃：护栏形态 `${A[@]+"${A[@]}"}` 的**内层**长着 `${A[@]}` —— 若逐个正则匹配，
    它会被当成「无护栏」判红（判据被自己的推荐写法喂红）。
    """
    out: list[tuple[str, bool]] = []
    i = 0
    while True:
        i = line.find("${", i)
        if i < 0:
            return out
        j, depth = i + 2, 1
        while j < len(line) and depth:
            if line[j] == "{":
                depth += 1
            elif line[j] == "}":
                depth -= 1
            j += 1
        inner = line[i + 2:j - 1]
        m = ARRAY_EXPANSION_INNER.fullmatch(inner)
        if m:
            out.append((m.group(1), j < len(line) and line[j] in "+-"))
        else:
            m2 = GUARDED_PREFIX.match(inner)
            if m2:
                out.append((m2.group(1), True))
        i = j


def _empty_state_is_bailed_out(lines: list[str], name: str, before: int) -> bool:
    """脚本是否在 `before` 行之前用「空则 exit」把该数组的空态挡掉了（这是**证明**，不是豁免名单）。

    形态：`if [ "${#NAME[@]}" -eq 0 ]; then … exit N … fi`（真语料形态见 `scripts/batch-gate.sh`）。
    """
    bail = re.compile(r'\[\s*"\$\{#' + re.escape(name) + r'\[@\]\}"\s+-eq\s+0\s*\]')
    for i in range(before):
        if bail.search(lines[i]) and any(
            lines[k].strip().startswith("exit") for k in range(i, min(i + 4, len(lines)))
        ):
            return True
    return False


def unguarded_empty_array_expansions(src: str) -> list[tuple[int, str]]:
    """→ `[(行号, 数组名)]`：`set -u` 脚本里对**可能为空**的数组的**无护栏**展开。

    判据（issue #6777；与 #5241 / #5260 同一个 macOS bash 3.2 兼容面）：
      ① 脚本开了 `set -u`（否则空数组展开无害）；
      ② 数组在本文件里被**空字面量**初始化（`NAME=()` / `declare -a NAME=()` ⇒ 空是可能状态）；
      ③ 展开处**没有**空值护栏（`${NAME[@]+"${NAME[@]}"}` / `${NAME[@]-…}`）；
      ④ 且脚本**没有**在它之前「空则 exit」把空态挡掉（可机械判定的「非空已证」）。

    命中的形态在 bash 3.2 下**整脚本当场死**（`NAME[@]: unbound variable`，exit 127），
    不是「少传一个参数」—— 本判据正是撞出来的：`scripts/ui_smoke_merchant.sh` 的
    `node … "${EXTRA_ARGS[@]}"` 在无参数调用时一步都没跑到 spec，却印「spec 退出码: 1」。
    判据只看**剥掉整行注释**后的代码面（脚本的注释里正讲解这个坑，不剥就是被自己的文案喂红）；
    剥注释**保行号**（注释行留成空行），故报出的行号就是文件里的真行号。
    """
    lines = ["" if ln.lstrip().startswith("#") else ln for ln in src.splitlines()]
    if not SET_U.search("\n".join(lines)):
        return []
    names: dict[str, int] = {}
    for i, ln in enumerate(lines):
        m = EMPTY_ARRAY_INIT.match(ln)
        if m:
            names.setdefault(m.group(1), i)
    hits: set[tuple[int, str]] = set()
    for name, init in names.items():
        for i in range(init + 1, len(lines)):
            for nm, guarded in _array_expansions(lines[i]):
                if nm == name and not guarded and not _empty_state_is_bailed_out(lines, name, i):
                    hits.add((i + 1, name))
    return sorted(hits)


def test_no_unguarded_empty_array_expansion_in_scripts():
    """类级回归锁（issue #6777）：`scripts/*.sh` 里不得再有 `set -u` 下的无护栏空数组展开。

    本机实测（macOS 自带 bash 3.2.57；同一形态在 bash 4.4+ 正常 ⇒ **只有这个版本上才现形**）：

        $ bash -c 'set -u; A=(); echo "${A[@]}"'
        bash: A[@]: unbound variable          # exit 127 —— 这一行之后的脚本全没跑
        $ bash -c 'set -u; A=(); echo "${A[@]+"${A[@]}"}"'
        (无输出)                               # exit 0：空数组展开成零个词（同 scripts/preset-anchor-check.sh 的既有约定）
    """
    bad = {
        sh.relative_to(REPO_ROOT).as_posix(): unguarded_empty_array_expansions(sh.read_text(encoding="utf-8"))
        for sh in sorted(SCRIPTS_DIR.glob("*.sh"))
    }
    bad = {f: h for f, h in bad.items() if h}
    assert bad == {}, (
        f"这些脚本在 `set -u` 下展开了「可能为空」的数组却没加空值护栏（bash 3.2 会 unbound variable"
        f"⇒ 整脚本当场死）：{bad}\n"
        f"  出口（真可行动）：写成 `${{NAME[@]+\"${{NAME[@]}}\"}}`（同 scripts/preset-anchor-check.sh 的既有约定）"
    )


def test_empty_array_guard_has_discriminating_power():
    """判别力自证（坏形态判红 + 护栏形态判绿 + **只改注释不红**）+ 真语料注入。

    前提自证：注入必须**真的**改动文本（`injected != src`），否则本判据的红证是空断言。
    """
    # ① 坏形态 ⇒ 必红（issue #6777 的病灶形态本身）
    assert unguarded_empty_array_expansions('set -u\nA=()\nrun "${A[@]}"\n') == [(3, "A")]
    # ② 护栏形态 ⇒ 必绿（含内层同名展开：不能把推荐写法自己判红）
    assert unguarded_empty_array_expansions('set -u\nA=()\nrun ${A[@]+"${A[@]}"}\n') == []
    # ③ 只把坏形态写进**注释** ⇒ 不红（判据不被自己的文案喂红）
    assert unguarded_empty_array_expansions('set -u\nA=()\n# run "${A[@]}"\n') == []
    # ④ 没开 `set -u` ⇒ 空数组展开无害，不在面内
    assert unguarded_empty_array_expansions('A=()\nrun "${A[@]}"\n') == []
    # ⑤ 空态被「空则 exit」挡掉 ⇒ 那是证明，不是漏判（真语料形态见 scripts/batch-gate.sh）
    bailed = 'set -u\nA=()\nif [ "${#A[@]}" -eq 0 ]; then\n  exit 2\nfi\nrun "${A[@]}"\n'
    assert unguarded_empty_array_expansions(bailed) == []
    # ⑥ 真语料：现役脚本必须干净；把护栏改回坏形态 ⇒ 当场命中（这就是回归时的红法）
    src = SMOKE.read_text(encoding="utf-8")
    assert unguarded_empty_array_expansions(src) == []
    injected = src.replace(GUARDED_EXTRA_ARGS, '"${EXTRA_ARGS[@]}"')
    assert injected != src, "注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    assert unguarded_empty_array_expansions(injected) != [], (
        '把护栏改回 "${EXTRA_ARGS[@]}" 后判据没红 ⇒ 本判据对 #6777 的病灶无判别力'
    )


# ── 判据 2：「没跑」必须长得像「没跑」—— 真语料（段落实跑）+ 桩 spec/node ──────────────
SMOKE_SPEC_START = "# ── 4. 跑冒烟 spec"
SMOKE_SPEC_END = "# ── 5. 停栈"

STUB_NODE = """#!/usr/bin/env bash
# 桩 node：① 记录 argv（= spec 真被调起的**标记**）② 按 spec.mjs 的成功路径落两个汇总文件。
printf '%s\\n' "$*" >> "$STUB_NODE_LOG"
if [ -n "${STUB_NO_ARTIFACTS:-}" ]; then exit "${STUB_EXIT_CODE:-0}"; fi
printf '# 商家后端 UI 冒烟结果\\n' > "$SMOKE_OUT_DIR/smoke-summary.md"
printf '[]\\n' > "$SMOKE_OUT_DIR/smoke-results.json"
exit "${STUB_EXIT_CODE:-0}"
"""


def _spec_segment() -> str:
    """取脚本里「跑冒烟 spec」那一段。取不到即判红（fail-closed）：定位失效不得退化成「空片段通过」。"""
    src = SMOKE.read_text(encoding="utf-8")
    start, end = src.find(SMOKE_SPEC_START), src.find(SMOKE_SPEC_END)
    if start < 0 or end < 0 or end <= start:
        pytest.fail(
            f"{SMOKE} 里定位不到冒烟 spec 段（marker {SMOKE_SPEC_START!r} → {SMOKE_SPEC_END!r}）"
            "⇒ 本守卫未行使，不得读成通过"
        )
    seg = src[start:end]
    if len(seg) < 200 or "spec.mjs" not in seg:
        pytest.fail(f"冒烟 spec 段只取到 {len(seg)} 字符 / 不含 spec.mjs ⇒ 判据定位失效，不得读成通过")
    return seg


def _host_bash_rejects_empty_array_expansion() -> bool:
    """宿主 bash 是否是 3.2 语义（空数组展开 ⇒ unbound variable）—— 行为腿的判别力前提。"""
    r = subprocess.run(
        [_BASH, "-c", 'set -u; A=(); echo "${A[@]}"'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    return r.returncode != 0 and "unbound variable" in (r.stderr + r.stdout)


def _run_spec_segment(tmp_path: Path, *, src: str | None = None, spec_present: bool = True,
                      extra_args: str = "EXTRA_ARGS=()", env_extra: dict | None = None):
    """在沙箱里跑「冒烟 spec」段（真语料 + 桩 `node`）：与真脚本同形，但不真起栈、不真跑 31 旅程。"""
    wt = tmp_path / "wt"
    (wt / "scripts/ui-smoke-merchant").mkdir(parents=True)
    out = wt / "out"
    out.mkdir()
    if spec_present:
        (wt / "scripts/ui-smoke-merchant/spec.mjs").write_text(
            "// 桩 spec（本判据不真跑 31 旅程）\n", encoding="utf-8"
        )
    binp = tmp_path / "bin"
    binp.mkdir()
    node = binp / "node"
    node.write_text(STUB_NODE, encoding="utf-8")
    node.chmod(0o755)
    marker = tmp_path / "node-calls.log"
    harness = tmp_path / "spec_run.sh"
    harness.write_text(
        "set -euo pipefail\n"
        f'SCRIPT_DIR="{wt}/scripts"\n'
        f'OUT_DIR="{out}"\n'
        f'MAIN_REPO="{wt}"\n'
        "WEB_PORT=3001\nPHONE=13800138000\nSMS_CODE=123456\n"
        f"{extra_args}\n"
        + (src if src is not None else _spec_segment())
        # 与真脚本同一终止形态（section 5 只做停栈、不改 EXIT）：见 test_smoke_script_still_exits_with_EXIT
        + '\nexit "${EXIT}"\n',
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{binp}:{os.environ.get('PATH', '')}",
        "STUB_NODE_LOG": str(marker),
        "SMOKE_OUT_DIR": str(out),
        **(env_extra or {}),
    }
    proc = subprocess.run(
        [_BASH, str(harness)], cwd=str(tmp_path), capture_output=True,
        encoding="utf-8", errors="replace", env=env, timeout=RUN_TIMEOUT_SECONDS,
    )
    calls = marker.read_text(encoding="utf-8").splitlines() if marker.exists() else []
    return proc, calls, out


def test_smoke_script_still_exits_with_EXIT():
    """前提自证：真脚本仍以 `exit "$EXIT"` 终止（沙箱 harness 的终止形态与它同形）。"""
    assert re.search(r'^exit "\$EXIT"$', SMOKE.read_text(encoding="utf-8"), re.M), (
        '冒烟脚本的终止形态变了 ⇒ 沙箱 harness 的 `exit "${EXIT}"` 不再等价，本判据的前提失效'
    )


def test_spec_really_runs_and_forwards_args(tmp_path):
    """判据 1（#6777 的病灶）：无参数调用时 spec 必须**真被调起**，且 `--group` 参数照旧转发。"""
    proc, calls, out = _run_spec_segment(tmp_path)
    assert calls, (
        f"桩 node 一次都没被调起 ⇒ spec 一行都没跑（bash 3.2 + `set -u` + 空数组的老形态）：\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "spec.mjs" in calls[0], f"调起的不是 spec.mjs：{calls}"
    assert proc.returncode == 0, f"spec 全绿却非零退出：\n{proc.stdout}\n{proc.stderr}"
    assert "spec 退出码: 0" in proc.stdout, f"真跑出结果时反而没印退出码：{proc.stdout!r}"
    assert (out / "smoke-summary.md").exists() and (out / "smoke-results.json").exists()

    proc2, calls2, _ = _run_spec_segment(tmp_path / "g", extra_args="EXTRA_ARGS=(--group 17-)")
    assert len(calls2) == 1 and calls2[0].endswith("--group 17-"), (
        f"护栏形态必须**逐字转发**参数（不许把 EXTRA_ARGS 吞掉）：{calls2}"
    )
    assert "spec 退出码: 0" in proc2.stdout


def test_injected_old_form_kills_invocation_on_bash32(tmp_path):
    """判据 1 的**注入式红证**：把护栏改回 `"${EXTRA_ARGS[@]}"` ⇒ spec 起不来（marker 消失）。

    判别力依赖宿主 bash：只有 3.2 会把空数组展开判成 unbound variable（bash 4.4+ 已修）。
    宿主不可复现时**退化为静态腿 + warning**，不静默变成「绿了但没判」（同族约定见
    `tests/unit_ci_workflows/test_scripts_bash32_var_brace.py`）。
    """
    injected = _spec_segment().replace(GUARDED_EXTRA_ARGS, '"${EXTRA_ARGS[@]}"')
    assert injected != _spec_segment(), "注入未生效（自证失败 ⇒ 本红证是空断言）"
    assert unguarded_empty_array_expansions("set -u\nEXTRA_ARGS=()\n" + injected) != [], (
        "注入形态没被类级判据判红 ⇒ 静态腿无判别力"
    )
    if not _host_bash_rejects_empty_array_expansion():
        warnings.warn(
            "宿主 bash 不是 3.2（空数组展开不报 unbound variable）⇒ 本判据的行为腿退化为静态腿；"
            "权威读数见 macOS bash 3.2.57 上的实测（PR body）",
            stacklevel=2,
        )
        return
    proc, calls, _ = _run_spec_segment(tmp_path, src=injected)
    assert calls == [], f"改回坏形态后 spec 仍被调起（判据没红）⇒ 红证无效：{calls}"
    assert "unbound variable" in (proc.stdout + proc.stderr), f"老形态应当场 unbound variable：\n{proc.stdout}"


def test_missing_spec_is_reported_as_not_executed(tmp_path):
    """判据 2（#6777）：spec 不存在 ⇒ 输出含「未执行」、**不含**「spec 退出码」、非零退出。"""
    proc, calls, _ = _run_spec_segment(tmp_path, spec_present=False)
    out = proc.stdout + proc.stderr
    assert "未执行" in out, f"spec 缺失时没写明「未执行」：{out!r}"
    assert "spec 退出码" not in out, f"spec 一行没跑却印了「spec 退出码」（#6777 的假陈述）：{out!r}"
    assert proc.returncode != 0, f"spec 未执行却退出 0（假绿）：{out!r}"
    assert calls == [], f"spec 都不存在却仍调起了 node：{calls}"


def test_node_without_artifacts_is_reported_as_not_executed(tmp_path):
    """判据 2 的第二半：node 跑了但**没产出汇总** ⇒ 同样是「一行旅程都没跑」，不许印退出码。"""
    proc, calls, out = _run_spec_segment(tmp_path, env_extra={"STUB_NO_ARTIFACTS": "1", "STUB_EXIT_CODE": "0"})
    text = proc.stdout + proc.stderr
    assert calls, "前置不成立：node 没被调起，本判据测的不是「跑了但没产出」"
    assert "未执行" in text, f"没产出 smoke-summary.md / smoke-results.json 却没报「未执行」：{text!r}"
    assert "spec 退出码" not in text, f"没产出汇总仍印「spec 退出码」（假陈述）：{text!r}"
    assert proc.returncode != 0, f"没产出汇总却退出 0（假绿）：{text!r}"


def test_real_journey_failure_still_reports_exit_code(tmp_path):
    """负控：**真的有旅程失败**（汇总已产出、退出码非零）时必须照旧报退出码 + 非零退出。"""
    proc, calls, out = _run_spec_segment(tmp_path, env_extra={"STUB_EXIT_CODE": "1"})
    assert calls, "前置不成立：node 没被调起"
    assert (out / "smoke-summary.md").exists(), "前置不成立：汇总没产出，测的就成了「未执行」那条"
    assert "spec 退出码: 1" in proc.stdout, f"真失败没报退出码：{proc.stdout!r}"
    assert "未执行" not in proc.stdout, f"真失败被读成「未执行」：{proc.stdout!r}"
    assert proc.returncode == 1, f"真失败没把退出码传出去：{proc.returncode}"
