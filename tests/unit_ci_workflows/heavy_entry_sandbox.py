r"""**重活入口判据**的共享沙箱夹具（issue #6085 的后续包）。

## 这个模块解决什么问题

「子包 worktree 不许直跑全量 / 一批只跑一次 / 拿到机器级锁才动手」这类判据都要在
**自足沙箱**里跑**真脚本**（`verify-all.sh` / `batch-gate.sh` / `machine-heavy-lock.sh` /
`package-heavy-entry-ledger.sh`）。这套沙箱最初是写在
`test_package_heavy_entry_ban.py` 里的**私有夹具**，随后
`test_batch_gate.py` 又**手搓了一份同形夹具** —— 「各自手搓」= 同一个坑要被踩第二次：
下面的血泪教训全都会在第二份副本里**静默失效**（副本不改 ⇒ 判据假绿）。
⇒ 本模块把它抽成**可 import 的共享 harness**：新写同类判据请 `import` 本模块，**不要再抄**。

## 血泪教训（为什么夹具长这样 —— 每一条都是实测踩出来的）

1. 🔴 **沙箱仓根那份 `verify-all.sh` 必须是桩（`exit 0`）** —— 它**只**被真 `batch-gate.sh`
   当「那一次 gate」调用（判据 13）。放**真**脚本在这里，每次 `batch-gate.sh` 都会去跑一次
   **真 gate** ⇒ 而真 gate 要拿机器级重活锁 ⇒ 组合运行（`-p no:randomly` 顺序 / 与其它判据并发）
   时**互等机器级锁**，挂到 `180s` `TimeoutExpired`（`#6085` 首轮 CI 实测；修后同一条腿 **0:35**）。
   要判**真脚本**的用例一律用 `install_real_script(root)` 把它放进**被测的那个工作树**。
2. 🔴 **真脚本的 `ROOT` 由「脚本自己所在位置」算出**
   （`ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`）⇒ 拿主检出那份副本去 worktree 里跑，
   `ROOT` 仍指主检出 ⇒ 角色算出 `primary` ⇒ 判据**假绿**（实测踩过）。
   ⇒ 脚本文件必须**物理落在**被判的那个目录里（`install_real_script`）。
3. 🔴 **`MIGAO_HEAVY_LOCK_FILE` 与 `MIGAO_PACKAGE_HEAVY_LEDGER` 必须指到 `tmp_path`**：
   前者默认 `$HOME/.migao-heavy.lock`（**机器级共享**），后者默认
   `tests/unit_ci_workflows/package_heavy_entry_ledger.jsonl`（**真台账**，会被提交）。
   判据碰它们 = 污染共享状态（手工验证曾往真台账写进一条，见 `#6085` body §8.2 的形态）。
   ⇒ `_base_env()` 把两者**无条件**指向 `tmp_path`（结构保证，不是纪律）。
4. 🔴 **`origin/main` 必须存在**：`verify-all.sh` 的变更集判据是 `origin/main...HEAD`，没有这个 ref
   时它算不出 diff ⇒ 脚本先走「无变更 ⇒ `exit 3`」早退**而根本走不到守卫** ⇒
   红证退化成「任何变异体都 `rc=3`」的假绿。夹具用**本地路径 remote**（不联网）。
5. 🔴 **`PATH` 审计桩要转发「解析出来的绝对路径」**（`__REAL_MAP__`，生成时按 `AUDIT_TOOLS` 现取）：
   - 转发成「还原 PATH 再 `exec <name>`」⇒ **子进程**继承被改过的 `PATH` ⇒ 树里之后每一次工具
     查找都绕过审计桩（**静默漏记** ⇒ 判据变空断言）；
   - 转发成「把桩目录再前置一次」⇒ `PATH` **指数增长**（实测第 5 层
     `env: bash: Argument list too long`、退出码 126，而审计日志**空**）。
6. 🔴 **先自证桩生效**（审计日志非空、且记到了 `git`）再断言「日志里没有测试运行器」——
   否则「没有 pytest」可能只是**桩根本没挂上**（本仓反复踩过的空断言形态）。
7. 🔴 **读数不许用「锁文件还在不在」**：`macquire` 挂了 `trap … EXIT`，脚本一退出锁就被删 ⇒
   事后看**恒 `False`**（本判据第一版正是这么写的 = 空断言，实测被抓出来）。
   要判「真的走到重活面前」就判**日志**（拿到了锁 + 进入档位分发）。
8. ⚠️ **非 git 目录里 `git rev-parse` 两次失败都为「空串」** ⇒ 若实现写成
   `abs=$(...); common=$(...)` 再 `[ "$abs" = "$common" ]`，`"" = ""` **为真** ⇒
   算成 `primary`（放行）而不是 `unknown`（拒绝）。实测缺陷：`cwd=/tmp` 跑 `quick` 得
   `rc=3`（「无变更」）而非文档承诺的 `exit 5`。判据钉在
   `test_package_heavy_entry_ban.py::TestNonGitFailsClosed`（行为面）。

## 接口清单（别的判据文件直接 import，不要抄）

| 名字 | 解决什么问题 |
|---|---|
| `REPO` / `VERIFY` / `BATCH` / `LEDGER_SH` / `MARKER` / `TESTS_ROOT` | 仓库内真对象的**只读**路径（`REPO` 由本文件位置算出 ⇒ 与判据文件无关） |
| `DEFAULT_REAL_LOCK` / `DEFAULT_REAL_LEDGER` | **机器级真锁 / 真台账**的默认路径（隔离判据只读它们，**绝不创建**） |
| `unscoped_tmp_root(path)` | 断言「这个路径不在 `$HOME` 下」——防止有人把真锁路径塞进 `tmp_path` 之外的共享面 |
| `clean_env(**extra)` | 干净子进程环境：清掉 `CI` / `MIGAO_HEAVY_*` / `GIT_DIR`… 并**强制**锁与台账指向 `tmp_path` |
| `run(cmd, ...)` | **带显式 `timeout`** 的 `subprocess.run`（本机**没有** `timeout(1)`） |
| `build(root, verify_text=None)` | 自足临时仓：`git init` + 包分支 `pkg` + 本地 `origin/main` + 真 `scripts/` + 桩三把工具 |
| `build_worktree(root, name)` | 给沙箱建 linked worktree（= 「子包 worktree」形态），返回路径 |
| `install_real_script(root, text=None)` | 把**真** `verify-all.sh` 放进 `root`（`text` = 内存变异体，§28.1 出口①） |
| `real_verify_text()` | 真 `verify-all.sh` 全文（**只读工作树一次**，供变异注入与结构判据） |
| `mutate(rel, old, new)` | 把变异**真写到一个真对象**上；命中数 ≠ 1 ⇒ 断言失败（防「变异没生效」的空断言） |
| `make_audit_bin(tmp_path)` | `PATH` 审计桩目录（记调用名 + 转发绝对路径的真命令） |
| `slim_path(tmp_path, tools)` | **真的没有某命令**的 PATH 桩（如驱动「git 不在 PATH」那条分支） |
| `Verdict` | 一次真运行的读数：`rc` / `out` / `audit` / `lock_exists` / `ledger` / `heavy_calls()` |
| `run_verify(root, cwd, tmp_path, ...)` | 在 `cwd` 跑**真**脚本（可挂 PATH 审计桩），锁与台账**强制**在 `tmp_path` |
| `run_guard(root, cwd, tmp_path, ...)` | source **真**脚本里抽出的角色守卫 + **它那句真实调用**，返回 `(rc, 输出)` |
| `true_and_ledger_states()` | 真锁 / 真台账的**只读**快照（`exists` + `stat` 三项）—— 供隔离判据前后对照 |
| `ledger_records(text)` | 从台账文本里取**判定记录**（排除 schema 头行） |

## 边界（照实登记，§19.1）

- `run_guard` 跑的是**真函数 + 真调用行**（从真文本里抽），**不**跑 `case "$MODE"` 那一大段
  ⇒ 它判**角色判定**这一层，不判 gate 档的通过条件；
- 本模块**不碰**真锁 / 真台账（`DEFAULT_REAL_*` 只用于**只读**对照）；夹具造的一切都在 `tmp_path`；
- 本模块**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import uuid

REPO = pathlib.Path(__file__).resolve().parents[2]
VERIFY = REPO / "verify-all.sh"
BATCH = REPO / "scripts" / "batch-gate.sh"
LEDGER_SH = REPO / "scripts" / "package-heavy-entry-ledger.sh"
MARKER = "migao-package-heavy-entry-allow"
TESTS_ROOT = REPO / "tests" / "unit_ci_workflows"

#: **机器级真锁**（`machine-heavy-lock.sh` 的默认路径）—— 判据只**读**它，绝不创建。
DEFAULT_REAL_LOCK = pathlib.Path(os.environ.get("HOME", "/nonexistent")) / ".migao-heavy.lock"

#: **真台账**（`verify-all.sh` / 台账脚本的默认路径）—— 判据只**读**它，绝不追加。
DEFAULT_REAL_LEDGER = TESTS_ROOT / "package_heavy_entry_ledger.jsonl"

#: `PATH` **审计桩**：记下每个被查过的可执行名。用来证明「拒绝发生在任何重活之前」
#: （没有任何 `pytest*` 被查过 ⇒ 没有起过测试进程）。
#: ⚠️ 转发用**解析出来的绝对路径**（`__REAL_MAP__`，生成时按 `AUDIT_TOOLS` 现取）——
#: 见模块 docstring「血泪教训 5」的两条实测反例。
AUDIT_SHIM = """#!/bin/bash
name="${0##*/}"
{ printf '%s\\n' "$name" >> "$MIGAO_AUDIT_LOG"; } 2>/dev/null || true
case "$name" in
__REAL_MAP__
  *) echo "audit shim: 没有对应的真实命令：$name" >&2; exit 127 ;;
esac
"""

#: 审计桩需要转发给**真命令**的那些（脚本跑到守卫之前会用到）。
AUDIT_TOOLS = ("git", "bash", "sh", "env", "date", "sed", "grep", "awk", "printf", "sort",
               "tr", "cut", "head", "tail", "cat", "rm", "mkdir", "mktemp", "chmod", "ls",
               "dirname", "basename", "uname", "ps", "kill", "python3", "wc")

#: 会拉起重活的运行器名（审计日志里出现任何一个 ⇒ 「拒绝先于重活」当场红）。
#: ⚠️ **不含裸 `node`**：`node` 不是 `verify-all.sh` 任何一档的入口（真正会拉起重活的是
#: `node_modules/.bin/*` 下的 `vitest` / `tsc` 与 `npx`）—— 把裸 `node` 算进来只会让判定吃
#: 「脚本内部任何 node 调用」这种噪声（假红方向：判据自己把自己喂红）。
TEST_RUNNER_PREFIXES = ("pytest", "py.test", "vitest", "jest", "playwright", "mvn", "mvnw",
                        "npm", "npx")

#: 子进程环境里**必须清掉**的继承变量（放进来 = 判定被外部状态左右）。
_ENV_DROP = ("CI", "MIGAO_HEAVY_LOCK_HELD", "MIGAO_HEAVY_LOCK_FILE", "MIGAO_HEAVY_ROOTS",
             "MIGAO_HEAVY_WAIT", "MIGAO_ROLE_LEDGER_ID", "MIGAO_PACKAGE_HEAVY_LEDGER",
             "MIGAO_AUDIT_LOG", "GIT_DIR", "GIT_WORK_TREE")


def unscoped_tmp_root(path) -> pathlib.Path:
    """断言 `path` 在 `$HOME` **之外**（= 它不可能是那把机器级共享锁 / 真台账）。

    用途：`_base_env` 之外的判据要自己造一条路径时，先自证它没落在共享面上。
    返回 `path`（便于串联），并在落在 `$HOME` 下时当场失败。
    """
    p = pathlib.Path(path).resolve()
    home = pathlib.Path(os.environ.get("HOME", "/nonexistent")).resolve()
    assert home not in p.parents and p != home, (
        f"路径落在 $HOME 之下（= 可能是机器级共享面）：{p} —— 判据一律用 tmp_path"
    )
    return p


def run(cmd, cwd=None, env=None, timeout: int = 180) -> subprocess.CompletedProcess:
    """跑一个子进程：**显式** `timeout`（本机**没有** `timeout(1)`，macOS 无 GNU coreutils）。"""
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                          env=env, timeout=timeout)


def clean_env(tmp_path, **extra) -> dict:
    """干净的子进程环境：清掉会干扰判定的继承变量，再叠加 `extra`。

    🔴 **锁文件与台账的落点由本函数收口**（「判据不碰真锁 / 真台账」的**结构保证**）：
      - 调用方**没**显式给 `MIGAO_HEAVY_LOCK_FILE` / `MIGAO_PACKAGE_HEAVY_LEDGER` ⇒ 一律落
        `tmp_path`（即使判据作者忘了传，也落不到共享面上）；
      - 调用方**显式**给了 ⇒ 尊重它，但先用 `unscoped_tmp_root` 自证它**不在 `$HOME` 下**
        （⇒ 它**不可能**是 `$HOME/.migao-heavy.lock` 那把机器级共享锁 / 真台账）。
    见模块 docstring「血泪教训 3」。
    """
    for key in ("MIGAO_HEAVY_LOCK_FILE", "MIGAO_PACKAGE_HEAVY_LEDGER"):
        if extra.get(key):
            unscoped_tmp_root(extra[key])          # 显式路径也必须落在共享面之外
    env = {k: v for k, v in os.environ.items() if k not in _ENV_DROP}
    env.update({"GIT_AUTHOR_NAME": "guard@test.invalid", "GIT_AUTHOR_EMAIL": "guard@test.invalid",
                "GIT_COMMITTER_NAME": "guard@test.invalid",
                "GIT_COMMITTER_EMAIL": "guard@test.invalid"})
    env.update({k: str(v) for k, v in extra.items()})
    tmp = pathlib.Path(tmp_path)
    env.setdefault("MIGAO_HEAVY_LOCK_FILE", str(tmp / "sandbox-heavy.lock"))
    env.setdefault("MIGAO_PACKAGE_HEAVY_LEDGER", str(tmp / "sandbox-ledger.jsonl"))
    return env


def scoped_paths(tmp_path) -> dict:
    """`clean_env` 强制注入的那两条路径（判据要断言「确实在 tmp_path 下」时用它，别写死名）。"""
    tmp = pathlib.Path(tmp_path)
    return {"lock": tmp / "sandbox-heavy.lock", "ledger": tmp / "sandbox-ledger.jsonl"}


def commit(root, msg: str) -> None:
    run(["git", "add", "-A"], root, clean_env(root))
    run(["git", "commit", "-q", "-m", msg], root, clean_env(root))


def _stub_verify() -> str:
    """沙箱**仓根**那份桩 `verify-all.sh`（`exit 0`）—— 理由见模块 docstring「血泪教训 1」。

    它带一个**可计数**的副作用（`BATCH_GATE_STUB_LOG`），让「那一次 gate 被调用了几次」
    成为可读读数；`BATCH_GATE_STUB_RC` 让同一个桩既能演绿也能演红。
    """
    return ('#!/usr/bin/env bash\n'
            'if [ -n "${BATCH_GATE_STUB_LOG:-}" ]; then echo "gate" >> "$BATCH_GATE_STUB_LOG"; fi\n'
            'exit "${BATCH_GATE_STUB_RC:-0}"\n')


def build(root, verify_text: str | None = None) -> pathlib.Path:
    """造一个自足临时仓库：桩/变异 `verify-all.sh` + 真 `scripts/` + 桩三把工具 + 本地 `origin/main`。

    | 放进沙箱的东西 | 真 / 桩 | 为什么 |
    |---|---|---|
    | `scripts/machine-heavy-lock.sh` | **真** | 判「拒绝先于拿锁」要读到真的锁行为 |
    | `scripts/package-heavy-entry-ledger.sh` | **真** | 判「拒绝被记一笔」要读真的台账脚本 |
    | `scripts/batch-gate.sh` | **真** | 判「标记真被留下」要直连真脚本 |
    | 仓根 `verify-all.sh` | **桩** | 它只被真 `batch-gate.sh` 当「那一次 gate」调用 |
    | `check-ui-regression.sh` / `contract-check.sh` | **桩** | 本判据不判 UI 回退与契约面 |

    真 `verify-all.sh` 不放在这里 —— 用 `install_real_script(root)` 放进**被测的那个**工作树。
    `verify_text` 非 None 时 = 内存里的**变异体**（§28.1 出口①），与真对象同一条构建路径。
    """
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copy2(REPO / "scripts" / "machine-heavy-lock.sh",
                 root / "scripts" / "machine-heavy-lock.sh")
    shutil.copy2(LEDGER_SH, root / "scripts" / "package-heavy-entry-ledger.sh")
    (root / "verify-all.sh").write_text(verify_text if verify_text is not None else _stub_verify(),
                                        encoding="utf-8")
    (root / "scripts" / "batch-gate.sh").write_text(BATCH.read_text(encoding="utf-8"),
                                                    encoding="utf-8")
    for name, body in (("check-ui-regression.sh", "#!/usr/bin/env bash\nexit 0\n"),
                       ("contract-check.sh", "#!/usr/bin/env bash\nexit 0\n")):
        (root / name).write_text(body, encoding="utf-8")
    for p in [root / "verify-all.sh", root / "scripts" / "batch-gate.sh",
              root / "scripts" / "machine-heavy-lock.sh",
              root / "scripts" / "package-heavy-entry-ledger.sh",
              root / "check-ui-regression.sh", root / "contract-check.sh"]:
        os.chmod(p, 0o755)
    (root / "README.md").write_text("sandbox\n", encoding="utf-8")
    # 提交用 clean_env(root)（它把锁/台账指到 tmp_path）—— 这几步只碰沙箱自己的 git。
    env = clean_env(root)
    assert run(["git", "init", "-q", "-b", "main"], root, env).returncode == 0
    commit(root, "base")
    # 一个包分支：让 `verify-all.sh` 的「禁空跑」与「变更集」判定在这棵树上有东西可算。
    assert run(["git", "checkout", "-q", "-b", "pkg", "main"], root, env).returncode == 0
    (root / "pkg.txt").write_text("pkg\n", encoding="utf-8")
    commit(root, "pkg change")
    # 🔴 `origin/main` **必须**存在（模块 docstring「血泪教训 4」）。用**本地路径 remote**（不联网）。
    bare = root.parent / f"origin-{uuid.uuid4().hex}.git"
    assert run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], root, env).returncode == 0
    assert run(["git", "remote", "add", "origin", str(bare)], root, env).returncode == 0
    assert run(["git", "push", "-q", "origin", "main", "pkg"], root, env).returncode == 0
    assert run(["git", "fetch", "-q", "origin"], root, env).returncode == 0
    return root


def build_worktree(root, name: str) -> pathlib.Path:
    """给沙箱建一个 linked worktree（= 「子包 worktree」形态），返回它的路径。"""
    wt = pathlib.Path(root).parent / f"wt-{name}-{uuid.uuid4().hex}"
    r = run(["git", "worktree", "add", "--detach", str(wt), "pkg"], root, clean_env(root))
    assert r.returncode == 0, r.stdout + r.stderr
    return wt


def real_verify_text() -> str:
    """真 `verify-all.sh` 全文（只读工作树**一次**；变异注入与结构判据都用它）。"""
    return VERIFY.read_text(encoding="utf-8")


def mutate(rel: str, old: str, new: str) -> str:
    """把变异**真的写到一个真对象**上（`rel` = 注入面，如 `verify-all.sh`），返回变异后全文。

    ⚠️ 命中数 ≠ 1 ⇒ 断言失败 = **变异没生效**（红证会变成空断言，本仓 #28.1 的口径）。
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    hits = src.count(old)
    assert hits == 1, f"变异没生效（命中 {hits} 次，应为 1）：{old!r} ⇒ 红证会变成空断言"
    assert new != old, "变异体与原文逐字相同"
    return src.replace(old, new, 1)


def install_real_script(root, text: str | None = None) -> pathlib.Path:
    """把一个**真** `verify-all.sh` 副本放进 `root`，返回脚本路径。

    🔴 为什么必须这样（模块 docstring「血泪教训 2」）：`ROOT` 由**脚本自己所在位置**算出 ⇒
    脚本文件必须**物理落在**被判的那个工作树 / 目录里，否则角色算的是主检出。
    `root` 可以是 linked worktree，也可以是**普通（非 git）目录** —— 后者正是
    「非 git 目录 ⇒ `unknown` ⇒ 拒绝」的行为面判据要用的形态。
    """
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    dst = root / "verify-all.sh"
    dst.write_text(real_verify_text() if text is None else text, encoding="utf-8")
    os.chmod(dst, 0o755)
    return dst


def make_audit_bin(tmp_path) -> tuple[pathlib.Path, dict[str, str]]:
    """造 `PATH` 审计桩目录：每个名字 → 记一行 + 转发**绝对路径**的真命令。

    返回 `(桩目录, {名字: 真实绝对路径})`。`__REAL_MAP__` 在**生成时**填好（现取 `shutil.which`），
    因此桩转发后子进程看到的 `PATH` 一字未改 ⇒ 树里每一次工具查找都照旧经过审计桩。
    """
    tmp_path = pathlib.Path(tmp_path)
    bindir = tmp_path / f"auditbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    real: dict[str, str] = {}
    for tool in AUDIT_TOOLS:
        found = shutil.which(tool)
        if found:
            real[tool] = str(pathlib.Path(found).resolve())
    table = "\n".join(f'  {name}) exec "{path}" "$@" ;;' for name, path in real.items())
    shim = bindir / "_shim"
    shim.write_text(AUDIT_SHIM.replace("__REAL_MAP__", table), encoding="utf-8")
    os.chmod(shim, 0o755)
    for name in real:
        (bindir / name).symlink_to(shim)
    return bindir, real


def slim_path(tmp_path, tools) -> str:
    """造一个**真的没有 `tools` 内外命令**的 PATH（只有列进来的那些软链）。

    用途：驱动「`git` 不在 PATH」这条分支 —— 靠环境「碰巧没有 git」写断言在开发机 /
    CI 上**永远走不到**（空断言形态）。⚠️ **只返回软链目录**，不缀 `/usr/bin:/bin`
    （否则系统里存在的命令照样命中，分支永远走不到）。
    """
    bindir = pathlib.Path(tmp_path) / f"slimbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    for tool in tools:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    return str(bindir)


class Verdict:
    """一次真运行的读数（退出码 + 输出 + 审计日志 + 锁文件 + 台账）。"""

    def __init__(self, proc, audit_log: pathlib.Path, lock_file: pathlib.Path,
                 ledger: pathlib.Path):
        self.proc = proc
        self.out = proc.stdout + proc.stderr
        self.audit = (audit_log.read_text(encoding="utf-8").splitlines()
                      if audit_log.exists() else [])
        self.lock_exists = lock_file.exists()
        self.ledger = (ledger_records(ledger.read_text(encoding="utf-8"))
                       if ledger.exists() else [])

    @property
    def rc(self) -> int:
        return self.proc.returncode

    def heavy_calls(self) -> list[str]:
        """审计日志里**会拉起重活**的可执行名（空 ⇒ 没有起过测试进程）。"""
        return [n for n in self.audit
                if any(n == p or n.startswith(p) for p in TEST_RUNNER_PREFIXES)]


def ledger_records(text: str) -> list[dict]:
    """台账文本 ⇒ **判定记录**列表（排除首行 schema 头：它没有 `"id"` 键）。"""
    return [json.loads(ln) for ln in text.splitlines() if ln.strip().startswith('{"id"')]


def run_verify(root, cwd, tmp_path, *args, tier: str = "quick", audit: bool = True,
               env_extra: dict | None = None, ledger_id: str | None = None,
               script: pathlib.Path | None = None) -> Verdict:
    """在 `cwd` 里跑**真** `verify-all.sh`（可挂 PATH 审计桩）。

    `script` 必须指向**本工作树 / 本目录里**那份副本（`install_real_script(...)` 的返回值）；
    缺省 = 沙箱仓根那份（多是**桩**）。锁文件与台账**无条件**指到 `tmp_path`。
    """
    tmp_path = pathlib.Path(tmp_path)
    audit_log = tmp_path / f"audit-{uuid.uuid4().hex}.log"
    ledger = tmp_path / f"ledger-{uuid.uuid4().hex}.jsonl"
    lock_file = tmp_path / f"lock-{uuid.uuid4().hex}"
    extra = {"MIGAO_HEAVY_LOCK_FILE": str(lock_file)}
    if audit:
        bindir, _real = make_audit_bin(tmp_path)
        extra.update({"MIGAO_AUDIT_LOG": str(audit_log),
                      "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"})
    if env_extra:
        extra.update(env_extra)
    env = clean_env(tmp_path, **extra)
    env["MIGAO_HEAVY_LOCK_FILE"] = str(lock_file)       # 显式，不被 extra 覆盖掉
    env["MIGAO_PACKAGE_HEAVY_LEDGER"] = str(ledger)
    if ledger_id is not None:
        env["MIGAO_ROLE_LEDGER_ID"] = ledger_id
    target = script if script is not None else (pathlib.Path(root) / "verify-all.sh")
    proc = run(["bash", str(target), tier, *args], cwd, env)
    return Verdict(proc, audit_log, lock_file, ledger)


# ── 让脚本真跑起来的最小 harness（抽**真实的**函数与真实的调用行）────────────

def guard_harness_text(script: str, root) -> str:
    """从 `verify-all.sh` 的**真文本**里抽：辅助函数 + 角色块 + **那句真实的守卫调用**。

    为什么抽出而不是「照抄一份」：复制一份就是**第二份判定**（本仓反复踩过的形态）——
    真实现改了而副本不改，判据照样绿。这里抽的是真行、真调用，**守卫一被摘掉这段就抽不到**
    （找不到调用行 ⇒ `StopIteration` ⇒ 判据当场红）。
    """
    lines = script.split("\n")
    call_at = next(i for i, ln in enumerate(lines)
                   if ln.startswith("package_heavy_guard ") and "$@" in ln)
    # ⚠️ 起点取 `MARKER_NAME=` 那一行**之前**的块首注释：`MARKER_NAME` / `LEDGER_SCRIPT` /
    #    `MIGAO_ROLE_LEDGER_ID` 都定义在 `_env_truthy()` **之前** —— 从 `_env_truthy()` 起抽会
    #    把它们漏在面外（实测：harness 里 `MARKER_NAME: unbound variable` ⇒ 假红）。
    marker_at = next(i for i, ln in enumerate(lines) if ln.startswith("MARKER_NAME="))
    start = marker_at
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1                                     # 连同它的说明注释一起带走（可读性）
    start -= 1                                         # 上一个 `# ====` 分隔行
    assert start < call_at, "角色块的函数定义出现在调用之后（脚本结构变了）"
    out = list(lines[start:call_at])              # **到调用点为止**（不含 `PKG_RC=$?` / `if`）
    out.append(lines[call_at])                    # 真调用行
    out.append('PKG_RC=$?')
    out.append('echo "RC=${PKG_RC}"')
    out.append("exit 0")
    # ⚠️ `ROOT` 是 `verify-all.sh` 顶层的变量（抽取面**之前**）⇒ 这里必须补上，否则
    #    `record_verdict`（用 `$ROOT/$LEDGER_SCRIPT`）会 `unbound variable` ⇒ **台账静默不记**
    #    （判据 6/7 会变成假绿：拒绝发生了、账上却什么都没有）。
    return "set -uo pipefail\nROOT='" + str(root) + "'\n" + "\n".join(out) + "\n"


def run_guard(root, cwd, tmp_path, *args, script: str | None = None,
              env_extra: dict | None = None) -> tuple[int, str]:
    """在 `cwd` 里 source 抽取出来的守卫 + **它那句真实调用**，返回 `(rc, 输出)`。

    `ROOT` 指到 `root`（= 与真脚本 `ROOT="$(cd "$(dirname "$0")" && pwd)"` 同口径）：
    判据跑的是**真函数 + 真调用行**，只是不在 `case "$MODE"` 那一大段上花时间。
    """
    tmp_path = pathlib.Path(tmp_path)
    harness = tmp_path / f"guard-{uuid.uuid4().hex}.sh"
    harness.write_text(guard_harness_text(script if script is not None else real_verify_text(),
                                          root), encoding="utf-8")
    env = clean_env(tmp_path)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
        # `extra` 不得把锁/台账拽回共享面 —— 强制回 tmp_path（与 `clean_env` 同口径）。
        env["MIGAO_HEAVY_LOCK_FILE"] = str(scoped_paths(tmp_path)["lock"])
        env["MIGAO_PACKAGE_HEAVY_LEDGER"] = str(scoped_paths(tmp_path)["ledger"])
    proc = run(["bash", str(harness), *args], cwd, env)
    m = re.search(r"^RC=(\d+)$", proc.stdout, re.M)
    assert m, f"harness 没有产出 RC 读数（抽取失效？）：\n{proc.stdout}\n{proc.stderr}"
    return int(m.group(1)), proc.stdout + proc.stderr


# ── 隔离保证：真锁 / 真台账的**只读**快照 ─────────────────────────────────────

def true_and_ledger_states() -> dict:
    """真锁 / 真台账的现状 —— `{"exists": bool, "stat": (mtime, size, inode)|None}`（**只读**）。

    ⚠️ 本函数**绝不创建**这两个文件：不存在 ⇒ 报 `exists=False`（对「不存在」的判据就是
    「跑完仍然不存在」）。用 `stat` 三项（mtime / size / inode）而不是内容哈希：内容哈希读的是
    同一份字节，`stat` 还能抓「被重写但内容恰好相同」这种（本判据要防的正是**写入**本身）。
    """
    def _one(p: pathlib.Path) -> dict:
        if not p.exists():
            return {"exists": False, "stat": None}
        st = p.stat()
        return {"exists": True, "stat": (st.st_mtime_ns, st.st_size, st.st_ino)}

    return {"lock": _one(DEFAULT_REAL_LOCK), "ledger": _one(DEFAULT_REAL_LEDGER)}


def assert_nothing_touched(before: dict, after: dict, *, what: str) -> None:
    """`before` / `after` 两份快照必须**逐项相同**（不存在 ⇒ 仍不存在；存在 ⇒ mtime/size/inode 未变）。

    判红文案给出**具名**的差异（哪个对象 / 变在哪一项）+ 可复制的复核命令（铁律 8）。
    """
    for key, label in (("lock", "真机器级锁"), ("ledger", "真台账")):
        b, a = before[key], after[key]
        assert a["exists"] == b["exists"], (
            f"{what} 之后 {label} 的**存在性**变了：{b['exists']} → {a['exists']}"
            f"（{DEFAULT_REAL_LOCK if key == 'lock' else DEFAULT_REAL_LEDGER}）—— "
            f"判据碰了共享面（复核：ls -la {DEFAULT_REAL_LOCK if key == 'lock' else DEFAULT_REAL_LEDGER}）"
        )
        if b["exists"]:
            assert a["stat"] == b["stat"], (
                f"{what} 之后 {label} 被改动：mtime/size/inode "
                f"{b['stat']} → {a['stat']}（复核：stat -f '%m %z %i' "
                f"{DEFAULT_REAL_LOCK if key == 'lock' else DEFAULT_REAL_LEDGER}）"
            )
