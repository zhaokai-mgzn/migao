# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
r"""**子包 worktree 不许直跑全量**的角色判定判据（issue #6078）。

## 治的形态（两条实测事实，不是推断）

① 2026-10-02：在**集成 worktree** 里跑全量 gate，**挂死 26 分钟并握着机器级重活锁**
   （缺陷已修：`#6076` / PR `#6077` = `cbd0b9173`，套件自带准入现在「祖先持锁 ⇒ 立即拒绝 +
   有界等待」）。**修好不等于不会再被误跑** —— 误跑的入口仍然敞开。
② 在**子包 worktree** 里跑全量 = 把「批次那一次」**提前烧掉**（D 口径的全部意义就是**一批一次**），
   还会跟别人的重活抢同一把机器锁。
⇒ 本判据守的是「**让子包里直跑全量在机制上被拒绝**」：出声、可归因、可在命令行显式绕过。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | **子包 worktree ⇒ 拒绝**：真 `verify-all.sh` 在 linked worktree 里跑 ⇒ 非零退出（**5**）+ 报文三点齐全（为什么 / 替代 / 怎么显式跑） | 把守卫摘掉 ⇒ 脚本照常往下跑（进入重活）⇒ 红 |
| 2 | **拒绝先于任何重活**：同一次运行里**没有**任何 `pytest_*` 进程被起过（`PATH` 审计桩记录调用，判据自证桩生效）+ 机器级锁**没被创建** | 把守卫挪到 `macquire` / `case "$MODE"` 之后 ⇒ 审计桩里出现 pytest / 锁文件出现 ⇒ 红 |
| 3 | **批次集成 worktree（带标记）⇒ 放行**；**摘掉标记 ⇒ 拒绝** | 判别读的是**名字前缀**而不是标记 ⇒ 第 3 条在「名字不叫 batch-*」的集成工作区上放行 ⇒ 红 |
| 4 | **主检出 ⇒ 放行**（人工 / 批次的一次性全量在这里跑） | 把 primary 也拒了 ⇒ 人工的一次性全量没了出口 ⇒ 红 |
| 5 | `CI=true` ⇒ **不受影响**（托管 runner 不占本机资源；本块整段不适用） | 把 CI 也拒了 ⇒ CI 上那条 `pytest tests/unit_ci_workflows` 整目录腿永远红 ⇒ 红 |
| 6 | **显式 flag ⇒ 放行**且台账记一条 `override`；**不加 flag 的拒绝**记一条 `refused` | 放行却静默（不打印醒目行）/ 台账不分 refused·override ⇒ 红 |
| 7 | **台账幂等**：同一次调用（同一 `MIGAO_ROLE_LEDGER_ID`）记两笔 ⇒ 账上**只有一笔** | 幂等键没用上 ⇒ 重复计数（本台账是「批次粒度」重启条件的读数）⇒ 红 |
| 8 | **台账口径**：拒绝 / 放行**两类都能现取计数**（`count` 子命令分两行报） | 两类混成一个数 ⇒ 读不出「被拦下的浪费」与「人类明知故犯」⇒ 红 |
| 9 | **逃生口不得做成环境变量**：`--allow-package-heavy` 只认命令行；`MIGAO_*` 环境变量无效 | 有人加回环境变量逃生口（本仓刚按 #6056 删掉一个不可见的）⇒ 红 |
| 10 | **退出码 5 不复用 3/4**：3 = 无变更、4 = 有变更但零项真跑；5 = **角色被拒**（此时变更集根本没算） | 把角色拒绝写成 3/4 ⇒ 读者会去查 diff 而不是查调用位置（错误归因）⇒ 红 |
| 11 | **注入式红证**：把角色守卫整段摘掉（`#` 注释掉）⇒ 同一次运行**不再**被拦（可判读数：退出码不再是 5、且机器级锁真被创建） | 判据退化成「读真文件就绿」/ 守卫被删而无人发现 ⇒ 红 |
| 12 | **对照读数**：只改注释（把守卫调用写进 `#` 注释）⇒ **不红**（但变异自证先钉住语料里真有那一行） | 判据被自己的说明文字喂红 ⇒ 红 |
| 13 | **`batch-gate.sh` 的真接线**：真脚本跑一次批次 ⇒ 集成工作区里**真出现**标记文件（直连真脚本，不是重写第二份判定） | 标记只写在注释里 / 写错路径 ⇒ 第 3、13 条都红 |
| 14 | **`verify-all.sh` 既有面不破**：`--allow-package-heavy` 不是档位（不进 7 档白名单）、`macquire` 仍在顶层 `case` 之前 | 顺手把档位表改坏 ⇒ 红（本判据只查**新增**，不重判既有面） |

## 隔离（为什么这些判据是安全的）

判据**不跑任何重活**：
- 纯函数与「守卫生效」两条走**测试装的 harness**（把 `verify-all.sh` 的**真实函数与真实调用行**
  抽出来 source 进一个最小环境），因此不触及 `case "$MODE"` 那一大段；
- 「拒绝先于重活」那条跑**真脚本**，但只跑到守卫 ⇒ 既不需要 venv / node_modules，也不会跑测试；
- `batch-gate.sh` 那条走**自足临时仓库**（`git init` + 桩 `verify-all.sh`），与既有
  `test_batch_gate.py` 同一形态。

## 边界（照实登记，§19.1）

- 角色判定读的是 **`git rev-parse` 的现取输出 + 标记文件**：`git` 不可用 / 工作树外 ⇒ 判 `unknown`
  ⇒ **拒绝**（fail-closed）；这一形态的**行为面**（真在非 git 目录里跑脚本）**未固化**（登记在
  PR body 的「未固化 / 边界」）；
- 判据**不保证**有人不用 `verify-all.sh`（直连 `pytest tests/unit_ci_workflows`）—— 那一路由
  `tests/unit_ci_workflows/conftest.py` 的套件自带准入 + `test_suite_self_lock.py` 承担；
- 判据**不判**「批次粒度优化该不该重启」（那是 `docs/wiki/Dev-Mode-Balance.md` §10 的裁定；
  本台账只提供它的读数）；
- 标记文件是**可删的**（删了就被当成子包 worktree 拒绝）—— 这是**有意**的 fail-closed 方向；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import uuid

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VERIFY = REPO / "verify-all.sh"
BATCH = REPO / "scripts" / "batch-gate.sh"
LEDGER_SH = REPO / "scripts" / "package-heavy-entry-ledger.sh"
MARKER = "migao-package-heavy-entry-allow"

#: `PATH` **审计桩**：记下每个被查过的可执行名。用来证明「拒绝发生在任何重活之前」
#: （没有任何 `pytest*` 被查过 ⇒ 没有起过测试进程）。
#: ⚠️ 转发用**解析出来的绝对路径**（`__REAL_MAP__`，生成时按 `AUDIT_TOOLS` 现取），
#:    而不是「把 PATH 还原后再 `exec <name>`」—— 后者会让**子进程**继承被改过的 `PATH`
#:    ⇒ 树里之后每一次工具查找都绕过审计桩（审计**静默漏记**，判据变成空断言）；
#:    也不是「把桩目录再前置一次」—— 那会让 `PATH` 指数增长（实测第 5 层就
#:    `env: bash: Argument list too long`、退出码 126，而审计日志**空**）。
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
#: ⚠️ **不含裸 `node`**：`node` 不是本脚本任何一档的入口（真正会拉起重活的是 `node_modules/.bin/*`
#: 下的 `vitest` / `tsc` 与 `npx`）——把裸 `node` 算进来只会让判定吃「脚本内部任何 node 调用」
#: 这种噪声（假红方向：判据自己把自己喂红）。
TEST_RUNNER_PREFIXES = ("pytest", "py.test", "vitest", "jest", "playwright", "mvn", "mvnw",
                        "npm", "npx")


# ── 自足临时仓库（与 test_batch_gate.py 同形态）────────────────────────────────

def _run(cmd, cwd=None, env=None, timeout=180):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                          env=env, timeout=timeout)


def _env(**extra) -> dict:
    """干净的子进程环境：清掉会干扰判定的继承变量，再叠加 `extra`。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CI", "MIGAO_HEAVY_LOCK_HELD", "MIGAO_HEAVY_LOCK_FILE",
                        "MIGAO_HEAVY_ROOTS", "MIGAO_HEAVY_WAIT", "MIGAO_ROLE_LEDGER_ID",
                        "MIGAO_PACKAGE_HEAVY_LEDGER", "MIGAO_AUDIT_LOG",
                        "GIT_DIR", "GIT_WORK_TREE")}
    env.update({"GIT_AUTHOR_NAME": "guard@test.invalid", "GIT_AUTHOR_EMAIL": "guard@test.invalid",
                "GIT_COMMITTER_NAME": "guard@test.invalid",
                "GIT_COMMITTER_EMAIL": "guard@test.invalid"})
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _commit(root: pathlib.Path, msg: str) -> None:
    _run(["git", "add", "-A"], root, _env())
    _run(["git", "commit", "-q", "-m", msg], root, _env())


def _build_sandbox(root: pathlib.Path, verify_text: str | None = None) -> pathlib.Path:
    """造一个自足临时仓库：真 `verify-all.sh`（可注入变异体）+ 真 `scripts/` + 桩三把工具。

    ⚠️ 与 `test_batch_gate.py` 同一取舍：**桩**掉的是「本判据不判的那一面」（UI 回退 / 一个批次
    全量），留下的是**真** `verify-all.sh` 的角色守卫与真 `scripts/package-heavy-entry-ledger.sh`
    ⇒ 判的是「接线在不在 + 拒绝发生在重活之前」，不是「gate 档的通过条件」。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copy2(REPO / "scripts" / "machine-heavy-lock.sh", root / "scripts" / "machine-heavy-lock.sh")
    shutil.copy2(LEDGER_SH, root / "scripts" / "package-heavy-entry-ledger.sh")
    # 真 `verify-all.sh`（可注入变异体）：本判据判的正是**它**的角色守卫与接线。
    # ⚠️ 它必须在**最后**写 —— `dev-worktree.sh` 式地在别处再补一份桩会把真脚本整个盖掉。
    # ⚠️ `verify_text` 非 None 时 = 内存里的**变异体**（§28.1 出口①），与真对象同一条构建路径。
    (root / "verify-all.sh").write_text(verify_text if verify_text is not None else _verify_text(),
                                        encoding="utf-8")
    (root / "scripts" / "batch-gate.sh").write_text(BATCH.read_text(encoding="utf-8"), encoding="utf-8")
    for name, body in (("check-ui-regression.sh", "#!/usr/bin/env bash\nexit 0\n"),
                       ("contract-check.sh", "#!/usr/bin/env bash\nexit 0\n")):
        (root / name).write_text(body, encoding="utf-8")
    for p in [root / "verify-all.sh", root / "scripts" / "batch-gate.sh",
              root / "scripts" / "machine-heavy-lock.sh",
              root / "scripts" / "package-heavy-entry-ledger.sh",
              root / "check-ui-regression.sh", root / "contract-check.sh"]:
        os.chmod(p, 0o755)
    (root / "README.md").write_text("sandbox\n", encoding="utf-8")
    assert _run(["git", "init", "-q", "-b", "main"], root, _env()).returncode == 0
    _commit(root, "base")
    # 一个包分支：让 `verify-all.sh` 的「禁空跑」与「变更集」判定在这棵树上有东西可算。
    assert _run(["git", "checkout", "-q", "-b", "pkg", "main"], root, _env()).returncode == 0
    (root / "pkg.txt").write_text("pkg\n", encoding="utf-8")
    _commit(root, "pkg change")
    # ⚠️ `origin/main` **必须**存在：`verify-all.sh` 的变更集判据是 `origin/main...HEAD`，
    #    没有这个 ref 时它算不出 diff ⇒ 脚本会先走「无变更 ⇒ exit 3」那条早退**而根本走不到守卫**
    #    （实测：红证会变成「任何变异体都 rc=3」的假绿）。用**本地路径 remote**（不联网）。
    bare = root.parent / f"origin-{uuid.uuid4().hex}.git"
    assert _run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], root, _env()).returncode == 0
    assert _run(["git", "remote", "add", "origin", str(bare)], root, _env()).returncode == 0
    assert _run(["git", "push", "-q", "origin", "main", "pkg"], root, _env()).returncode == 0
    assert _run(["git", "fetch", "-q", "origin"], root, _env()).returncode == 0
    return root


def _verify_text() -> str:
    return VERIFY.read_text(encoding="utf-8")


def _make_worktree(root: pathlib.Path, name: str) -> pathlib.Path:
    """给 sandbox 建一个 linked worktree（= 「子包 worktree」形态），返回它的路径。"""
    wt = root.parent / f"wt-{name}-{uuid.uuid4().hex}"
    r = _run(["git", "worktree", "add", "--detach", str(wt), "pkg"], root, _env())
    assert r.returncode == 0, r.stdout + r.stderr
    return wt


def _audit_bin(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
    """造 `PATH` 审计桩目录：每个名字 → 记一行 + 转发**绝对路径**的真命令。

    返回 `(桩目录, {名字: 真实绝对路径})`。`__REAL_MAP__` 在**生成时**填好（现取 `shutil.which`），
    因此桩转发后子进程看到的 `PATH` 一字未改 ⇒ 树里每一次工具查找都照旧经过审计桩。
    """
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


class Verdict:
    """一次真运行的读数（退出码 + 输出 + 审计日志 + 锁文件 + 台账）。"""

    def __init__(self, proc, audit_log: pathlib.Path, lock_file: pathlib.Path,
                 ledger: pathlib.Path):
        self.proc = proc
        self.out = proc.stdout + proc.stderr
        self.audit = audit_log.read_text(encoding="utf-8").splitlines() if audit_log.exists() else []
        self.lock_exists = lock_file.exists()
        self.ledger = [json.loads(ln) for ln in ledger.read_text(encoding="utf-8").splitlines()
                       if ln.strip().startswith('{"id"')] if ledger.exists() else []

    @property
    def rc(self) -> int:
        return self.proc.returncode

    def heavy_calls(self) -> list[str]:
        """审计日志里**会拉起重活**的可执行名（空 ⇒ 没有起过测试进程）。"""
        return [n for n in self.audit
                if any(n == p or n.startswith(p) for p in TEST_RUNNER_PREFIXES)]


def run_verify(sandbox: pathlib.Path, cwd: pathlib.Path, tmp_path: pathlib.Path, *args,
               tier: str = "quick", audit: bool = True, env_extra: dict | None = None,
               ledger_id: str | None = None, script: pathlib.Path | None = None) -> Verdict:
    """在 `cwd` 里跑**真** `verify-all.sh`（可挂 PATH 审计桩）。

    ⚠️ `script` 必须指向**本工作树里**的那份副本（`script_in(wt)`）—— 真脚本的 `ROOT` 是
    `"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`：拿主检出那份副本去 worktree 里跑，
    `ROOT` 仍指主检出 ⇒ 角色算出 `primary` ⇒ 判据**假绿**（实测踩过）。
    `MIGAO_HEAVY_LOCK_FILE` 与台账都指到 `tmp_path`（**绝不碰共享检出**）。
    """
    audit_log = tmp_path / f"audit-{uuid.uuid4().hex}.log"
    ledger = tmp_path / f"ledger-{uuid.uuid4().hex}.jsonl"
    lock_file = tmp_path / f"lock-{uuid.uuid4().hex}"
    extra = {"MIGAO_HEAVY_LOCK_FILE": str(lock_file)}
    if audit:
        bindir, _real = _audit_bin(tmp_path)
        extra.update({"MIGAO_AUDIT_LOG": str(audit_log),
                      "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"})
    if env_extra:
        extra.update(env_extra)
    env = _env(**extra)
    # ⚠️ 台账路径**必须**在 tmp_path（否则判据会往仓库里写记录）。
    env["MIGAO_PACKAGE_HEAVY_LEDGER"] = str(ledger)
    if ledger_id is not None:
        env["MIGAO_ROLE_LEDGER_ID"] = ledger_id
    target = script if script is not None else (sandbox / "verify-all.sh")
    proc = _run(["bash", str(target), tier, *args], cwd, env)
    return Verdict(proc, audit_log, lock_file, ledger)


# ── ① 让脚本真跑起来的最小 harness（抽**真实的**函数与真实的调用行）────────────

def _guard_harness(script: str) -> str:
    """从 `verify-all.sh` 的**真文本**里抽：辅助函数 + 角色块 + **那句真实的守卫调用**。

    为什么抽出而不是「照抄一份」：复制一份就是**第二份判定**（本仓反复踩过的形态）——
    真实现改了而副本不改，判据照样绿。这里抽的是真行、真调用，**守卫一被摘掉这段就抽不到**
    （`_guard_harness` 找不到调用行 ⇒ 抛 `StopIteration` ⇒ 判据当场红）。
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
    return "\n".join(out)


def script_in(root: pathlib.Path, name: str = "verify-all.sh") -> pathlib.Path:
    """把一个**真** `verify-all.sh` 副本放进 `root`，返回脚本路径。

    🔴 为什么必须这样（本判据第一版就是在这里错的）：`verify-all.sh` 的 `ROOT` 是
    `"$(cd "$(dirname "$0")" && pwd)"` —— **由脚本自己所在位置**推出来的。因此「在子包
    worktree 里跑」这件事**不能**用「在 worktree 里执行主检出那份副本」来模拟：那样 `ROOT`
    仍指主检出、角色算出 `primary`，而判据会得到**假绿**（实测：真跑出来的角色是 primary）。
    脚本文件必须**物理落在**被判的那个工作树里。
    """
    dst = root / name
    dst.write_text(_verify_text(), encoding="utf-8")
    os.chmod(dst, 0o755)
    return dst


def run_guard(sandbox: pathlib.Path, cwd: pathlib.Path, tmp_path: pathlib.Path, *args,
              script: str | None = None, env_extra: dict | None = None) -> tuple[int, str]:
    """在 `cwd` 里 source 抽取出来的守卫 + **它那句真实调用**，返回 `(rc, 输出)`。

    `ROOT` 指到 `sandbox`（= 与真脚本 `ROOT="$(cd "$(dirname "$0")" && pwd)"` 同口径）：
    判据跑的是**真函数 + 真调用行**，只是不在 `case "$MODE"` 那一大段上花时间。
    """
    harness = tmp_path / f"guard-{uuid.uuid4().hex}.sh"
    # ⚠️ `ROOT` 是 `verify-all.sh` 顶层的变量（抽取面**之前**）⇒ 这里必须补上，否则
    #    `record_verdict`（用 `$ROOT/$LEDGER_SCRIPT`）会 `unbound variable` ⇒ **台账静默不记**
    #    （判据 6/7 会变成假绿：拒绝发生了、账上却什么都没有）。
    harness.write_text("set -uo pipefail\nROOT='" + str(sandbox) + "'\n"
                       + _guard_harness(script if script is not None else _verify_text()) + "\n",
                       encoding="utf-8")
    env = _env(**{"MIGAO_PACKAGE_HEAVY_LEDGER": str(tmp_path / "harness-ledger.jsonl")})
    if env_extra:
        env.update(env_extra)
    proc = _run(["bash", str(harness), *args], cwd, env)
    m = re.search(r"^RC=(\d+)$", proc.stdout, re.M)
    assert m, f"harness 没有产出 RC 读数（抽取失效？）：\n{proc.stdout}\n{proc.stderr}"
    return int(m.group(1)), proc.stdout + proc.stderr


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 1~2：子包 worktree ⇒ 拒绝，且**先于任何重活**
# ══════════════════════════════════════════════════════════════════════════════════════

class TestPackageWorktreeIsRefused:
    def test_package_worktree_is_refused_with_a_named_verdict(self, tmp_path):
        """判据 1：真 `verify-all.sh` 在 linked worktree（子包形态）里 ⇒ 非零 + 报文三点齐全。"""
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        script = script_in(wt)
        v = run_verify(sb, wt, tmp_path, script=script)
        assert v.rc == 5, f"子包 worktree 里跑全量应被拒（exit 5），实得 {v.rc}：\n{v.out}"
        assert "拒绝" in v.out, v.out
        # 三点：为什么 / 替代 / 怎么显式跑
        assert "子包 worktree" in v.out, f"报文没写清**为什么**：\n{v.out}"
        assert "batch-gate.sh" in v.out, f"报文没给**替代**（批次入口）：\n{v.out}"
        assert "--allow-package-heavy" in v.out, f"报文没给**怎么显式跑**：\n{v.out}"
        assert "没有跑" in v.out, f"「没跑」必须长得像「没跑」：\n{v.out}"

    def test_refusal_happens_before_any_heavy_dispatch(self, tmp_path):
        """判据 2：同一次运行里**没有**任何重活被起过（PATH 审计桩）+ 机器级锁没被创建。

        ⚠️ 先自证桩**真的生效**（审计日志里有转发过的命令）—— 否则「日志里没有 pytest」
        可能只是「桩根本没挂上」（本仓反复踩过的**空断言**形态）。
        """
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        script = script_in(wt)
        v = run_verify(sb, wt, tmp_path, script=script)
        assert v.rc == 5, f"前置：应被拒（exit 5），实得 {v.rc}：\n{v.out}"
        assert v.audit, "PATH 审计桩**没生效**（日志为空）⇒ 下面那条断言会是空断言"
        assert any(n == "git" for n in v.audit), f"审计桩没记到 git（桩没挂对）：{v.audit[:10]}"
        assert v.heavy_calls() == [], (
            f"拒绝之前起过重活（审计日志里出现测试运行器）：{v.heavy_calls()}"
        )
        assert not v.lock_exists, (
            "拒绝之前**拿了机器级锁** —— 守卫必须在 `macquire` 之前（拿锁本身就是重活面）"
        )


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 3~6：四态处置（批次集成 / 主检出 / CI / 显式 flag）
# ══════════════════════════════════════════════════════════════════════════════════════

class TestRoleVerdicts:
    def test_batch_integration_marker_allows_and_removing_it_refuses(self, tmp_path):
        """判据 3：**标记**决定放行；**摘掉标记** ⇒ 拒绝（证明判别读的是标记，不是名字）。

        ⚠️ 工作区名字**刻意不叫** `batch-*`（`wt-batch-…` 之外一律用随机名）——
        「按名字前缀判」的坏实现会在这里**放行一个未授权的子包 worktree** ⇒ 本判据当场红。
        """
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "integration-integration")     # 名字里没有 `batch`
        # 反例工作区：名字**故意**取成 batch-*（名字前缀不是判据）

        # 标记位置由 git 现取（判据**不写死**路径 —— 写死就成了第二份约定的副本）
        marker_path = _run(["git", "rev-parse", "--git-path", MARKER], wt, _env()).stdout.strip()
        marker_file = pathlib.Path(marker_path)
        assert marker_file.is_absolute(), f"git-path 没给出绝对路径：{marker_path}"
        marker_file.write_text("batch-integration\n", encoding="utf-8")
        rc_with, out_with = run_guard(sb, wt, tmp_path)
        assert rc_with == 0, f"带标记的批次集成工作区应**放行**，实得 rc={rc_with}：\n{out_with}"
        marker_file.unlink()
        rc_without, out_without = run_guard(sb, wt, tmp_path)
        assert rc_without == 5, (
            "**摘掉标记**后应被拒（判别必须读标记，而不是名字前缀 / 环境变量）："
            f"实得 rc={rc_without}\n{out_without}"
        )
        # 反向自证：名字里带 `batch-` 但**没有**标记 ⇒ 也必须拒（名字前缀不是判据）
        wt_named = _make_worktree(sb, "batch-991231-000000")
        rc_named, out_named = run_guard(sb, wt_named, tmp_path)
        assert rc_named == 5, (
            "工作区**名字**叫 `batch-*` 但没有标记 ⇒ 必须拒绝（名字前缀会漂、任何人手建一个就有）："
            f"实得 rc={rc_named}\n{out_named}"
        )

    def test_primary_checkout_is_allowed(self, tmp_path):
        """判据 4：主检出 ⇒ 放行（人工 / 批次的一次性全量在这里跑）。

        `run_guard`（不是真跑脚本）：判的是**角色判定**这一层，不跑 gate 档的重活
        （真跑全量的时序/退出码由上面判据 1~2 与 `test_machine_heavy_lock.py` 承担）。
        """
        sb = _build_sandbox(tmp_path / "repo")
        rc, out = run_guard(sb, sb, tmp_path)
        assert rc == 0, f"主检出应放行，实得 rc={rc}：\n{out}"
        assert "拒绝" not in out, out

    def test_ci_environment_is_unaffected(self, tmp_path):
        """判据 5：`CI` 为真 ⇒ 本块整段不适用（托管 runner 不占本机资源）。"""
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        rc, out = run_guard(sb, wt, tmp_path, env_extra={"CI": "true"})
        assert rc == 0, f"CI 上不得被拦（否则整目录那条腿在 CI 上永远红），实得 rc={rc}：\n{out}"
        assert "CI 为真" in out, f"「未跑」必须说出来（否则读者以为判过了）：\n{out}"
        # 真脚本这条路的读数：CI 为真时也不得出现 exit 5（把真脚本放进 worktree 跑一次）
        script = script_in(wt)
        v = run_verify(sb, wt, tmp_path, script=script, env_extra={"CI": "true"})
        assert v.rc != 5, f"CI 为真时真脚本仍被角色守卫拦下：rc={v.rc}\n{v.out}"

    def test_explicit_flag_allows_and_prints_a_loud_line(self, tmp_path):
        """判据 6：**显式 flag ⇒ 放行** + 醒目一行 + 台账记一条 `override`。"""
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        rc, out = run_guard(sb, wt, tmp_path, "--allow-package-heavy")
        assert rc == 0, f"显式 flag 应放行，实得 rc={rc}：\n{out}"
        assert "绕过了批次口径" in out, f"放行必须**醒目**地说出绕过了什么：\n{out}"
        assert "⚠️" in out, f"放行行必须醒目（带警示符）：\n{out}"

    def test_denied_and_allowed_are_counted_separately(self, tmp_path):
        """判据 8：台账口径 —— 拒绝 / 放行**两类都能现取计数**。"""
        ledger = tmp_path / "counts.jsonl"
        sh = "bash"
        ledger_sh = str(LEDGER_SH)
        env = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="a.1")
        assert _run([sh, ledger_sh, "append", "package", "refused", "子包直跑"], env=env).returncode == 0
        env2 = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="a.2")
        assert _run([sh, ledger_sh, "append", "package", "override", "flag"], env=env2).returncode == 0
        got = _run([sh, ledger_sh, "count"], env=_env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger)))
        assert got.returncode == 0, got.stdout + got.stderr
        assert "refused=1" in got.stdout, f"拒绝计数取不出来：{got.stdout!r}"
        assert "override=1" in got.stdout, f"放行计数取不出来：{got.stdout!r}"

    def test_ledger_is_idempotent_per_invocation(self, tmp_path):
        """判据 7：**同一次调用**（同一 `MIGAO_ROLE_LEDGER_ID`）记两笔 ⇒ 账上只有一笔。"""
        ledger = tmp_path / "idem.jsonl"
        sh = "bash"
        ledger_sh = str(LEDGER_SH)
        env = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="same.42")
        first = _run([sh, ledger_sh, "append", "package", "refused", "第一次"], env=env)
        second = _run([sh, ledger_sh, "append", "package", "refused", "第二次"], env=env)
        assert first.returncode == 0 and second.returncode == 0, first.stdout + second.stdout
        assert "dup" in second.stdout, f"重复调用没有走幂等分支：{second.stdout!r}"
        records = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                   if ln.strip().startswith('{"id"')]
        assert len(records) == 1, f"同一次调用被记了 {len(records)} 笔（应为 1）：{records}"
        # 反向自证：换一个 id（= 另一次调用）⇒ 照旧能记账（幂等不是「台账只记一笔」）
        env2 = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="other.43")
        _run([sh, ledger_sh, "append", "package", "refused", "另一次"], env=env2)
        assert len([ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                    if ln.strip().startswith('{"id"')]) == 2, "换 id 后没记上 ⇒ 台账成了写不进的死账"

    def test_the_refusal_itself_is_recorded(self, tmp_path):
        """判据 6 的另一半：**不加 flag 的拒绝**必须记一条 `refused`（不许静默）。"""
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        script = script_in(wt)
        v = run_verify(sb, wt, tmp_path, script=script)
        assert v.rc == 5, v.out
        assert v.ledger, f"拒绝没有被记账（静默！）：\n{v.out}"
        assert [r["decision"] for r in v.ledger] == ["refused"], v.ledger
        assert v.ledger[0]["role"] == "package", v.ledger


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 9~10：逃生口形态 + 退出码语义
# ══════════════════════════════════════════════════════════════════════════════════════

class TestEscapeHatchAndExitCodes:
    def test_escape_hatch_is_command_line_only(self, tmp_path):
        """判据 9：逃生口只认**命令行 flag**；环境变量**不得**成为逃生口（#6056 的口径）。"""
        sb = _build_sandbox(tmp_path / "repo")
        wt = _make_worktree(sb, "pkg")
        for var in ("MIGAO_ALLOW_PACKAGE_HEAVY", "MIGAO_PACKAGE_HEAVY_SKIP",
                    "MIGAO_BATCH_GATE_SKIP_READY", "MIGAO_PACKAGE_HEAVY_ENTRY_BAN_SKIP"):
            rc, out = run_guard(sb, wt, tmp_path, env_extra={var: "1"})
            assert rc == 5, (
                f"环境变量 {var}=1 竟然绕过了角色守卫 —— 逃生口必须是**命令行可见**的"
                f"（本仓刚按 #6056 删掉一个不可见的环境变量逃生口）：rc={rc}\n{out}"
            )
        # 反向自证：同一次 setUp 下真 flag 必须仍然有效（否则上面那条恒真）
        rc_flag, _ = run_guard(sb, wt, tmp_path, "--allow-package-heavy")
        assert rc_flag == 0, "反向自证失败：真 flag 也不放行 ⇒ 上面那组断言是恒真的空断言"

    def test_exit_code_five_is_distinct_from_three_and_four(self):
        """判据 10：退出码语义 —— 5 = **角色被拒**，与既有 3 / 4 **不复用**。

        判据（**现取脚本自述**，不写死文案）：`verify-all.sh` 的返回码段必须**同时**写明
        3 = 无变更、4 = 有变更但零项真跑、5 = 角色守卫拒绝，且写明**为什么不复用**。
        """
        text = _verify_text()
        head = "\n".join(ln for ln in text.split("\n")[:120] if ln.startswith("#"))
        assert "3=无变更（未执行任何检查）" in head, f"返回码段没有 3=无变更：\n{head}"
        assert "4=有变更但零项真跑（纯空跑）" in head, f"返回码段没有 4：\n{head}"
        assert re.search(r"^\s*#\s*5=\*\*角色守卫拒绝\*\*", head, re.M), (
            f"返回码段没有登记新码 5：\n{head}"
        )
        assert "不复用" in head, f"没有说明为什么不复用 3/4（错误归因是本条要防的形态）：\n{head}"
    def test_allow_flag_is_not_a_tier(self):
        """判据 14：`--allow-package-heavy` **不是档位** —— 7 档白名单不得被顺手改坏。"""
        text = _verify_text()
        m = re.search(r'if \[ "\$MODE" != quick \][\s\S]{0,400}?\nfi', text)
        assert m, "找不到档位白名单（结构变了？本判据不写死文案，但要知道它在哪）"
        assert "--allow-package-heavy" not in m.group(0), (
            "逃生口被混进了档位白名单 —— 它是**开关**，不是档位"
        )
        for tier in ("quick", "full", "frontend", "backend", "agent", "gate", "redproof"):
            assert f'[ "$MODE" != {tier} ]' in m.group(0), f"档位白名单缺 {tier}"
        # 守卫调用必须在顶层 `case "$MODE" in` 之前（领取锁也在之前 —— 判据同口径，现取顺序）
        stripped = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))
        guard_at = stripped.find('package_heavy_guard "$@"')
        case_m = re.search(r'^case "\$MODE" in', stripped, re.M)
        acquire_at = stripped.find("macquire\n")
        assert guard_at >= 0, "守卫调用不见了（接线被摘掉）"
        assert case_m and guard_at < case_m.start(), "守卫必须在档位分发**之前**"
        assert acquire_at >= 0 and guard_at < acquire_at, (
            "守卫必须在 `macquire` **之前** —— 拿锁本身就是重活面（判据 2 的时序就是这条）"
        )


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 11~13：注入式红证 + 真接线（batch-gate 的标记）
# ══════════════════════════════════════════════════════════════════════════════════════

#: 注入点：**把角色守卫整段摘掉**（唯一命中；命中数 ≠ 1 ⇒ 判红 = 变异没生效）。
#: 形态选「调用行注释掉 + 判定的 `case` 只留放行项」——这正是「有人把机制删了」的真实形态。
#: ⚠️ 每条显式写**注入面**（`verify` / `ledger`）：两个文件的锚点混在一个命名空间里，
#:    「变异没落到对象上」是这一类红证最容易出的空断言形态（本仓 #28.1 的口径）。
MUTATIONS = [
    (
        "verify",
        "把角色守卫的拒绝分支摘掉（package 也被当成放行）",
        "    primary|batch-integration) return 0 ;;",
        "    primary|batch-integration|package) return 0 ;;",
        "guard_rejects_removed",
    ),
    (
        "verify",
        "把守卫调用整行摘掉（退回「只有纪律」）",
        'package_heavy_guard "$@"\nPKG_RC=$?',
        '# package_heavy_guard "$@"\nPKG_RC=0',
        "guard_call_removed",
    ),
    (
        "verify",
        "逃生口做成环境变量（不可见的那种，本仓刚删掉一个）",
        "  if package_heavy_flag_given \"$@\"; then",
        "  if [ -n \"${MIGAO_ALLOW_PACKAGE_HEAVY:-}\" ] || package_heavy_flag_given \"$@\"; then",
        "env_escape_hatch_added",
    ),
    (
        "ledger",
        "台账幂等键失效（同一次调用重复计数）",
        '  if _seen "$id"; then',
        '  if false; then',
        "idempotency_removed",
    ),
]


def _mutated(rel: str, mut) -> str:
    """把变异**真的写到一个真对象**上（`rel` = 注入面），返回变异后的全文。"""
    _surface, _label, old, new, _expect = mut
    src = (REPO / rel).read_text(encoding="utf-8")
    hits = src.count(old)
    assert hits == 1, f"变异没生效（命中 {hits} 次，应为 1）：{old!r} ⇒ 红证会变成空断言"
    assert new != old, "变异体与原文逐字相同"
    return src.replace(old, new, 1)


def _mutated_verify(mut) -> str:
    return _mutated("verify-all.sh", mut)


@pytest.mark.parametrize("mut", MUTATIONS, ids=[m[1] for m in MUTATIONS])
def test_injected_mutations_turn_it_red(tmp_path, mut):
    """判据 11：**注入式红证** —— 每处变异必须让对应读数**真的变**（不是「看起来不绿」）。

    | 变异 | 应变的读数 |
    |---|---|
    | `guard_rejects_removed` / `guard_call_removed` | 子包 worktree 的 rc **不再是 5**；而且机器级锁**真被创建**（= 真的走到重活面前了） |
    | `env_escape_hatch_added` | 只设环境变量（不带 flag）就能放行 ⇒ rc=0 |
    | `idempotency_removed` | 同一 id 记两笔 ⇒ 账上出现 **2** 条（真脚本下必须是 1） |
    """
    surface, label, _old, _new, expect = mut
    if surface == "ledger":
        assert expect == "idempotency_removed", expect
        mutated_sh = tmp_path / f"ledger-mut-{uuid.uuid4().hex}.sh"
        mutated_sh.write_text(_mutated("scripts/package-heavy-entry-ledger.sh", mut),
                              encoding="utf-8")
        ledger = tmp_path / f"mut-ledger-{uuid.uuid4().hex}.jsonl"
        env = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="same.99")
        for _ in range(2):
            assert _run(["bash", str(mutated_sh), "append", "package", "refused", "x"],
                        env=env).returncode == 0
        n = len([ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                 if ln.strip().startswith('{"id"')])
        assert n == 2, (
            f"变异「{label}」没被抓住：摘掉幂等后应记 2 笔（实得 {n}）—— 判据 7 的读数不敏感"
        )
        # 对照读数：**真**台账脚本在同一形态下只记 1 笔
        real_ledger = tmp_path / f"real-ledger-{uuid.uuid4().hex}.jsonl"
        env_real = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(real_ledger), MIGAO_ROLE_LEDGER_ID="same.99")
        for _ in range(2):
            _run(["bash", str(LEDGER_SH), "append", "package", "refused", "x"], env=env_real)
        n_real = len([ln for ln in real_ledger.read_text(encoding="utf-8").splitlines()
                      if ln.strip().startswith('{"id"')])
        assert n_real == 1, f"对照读数错：真脚本下同 id 应记 1 笔（实得 {n_real}）"
        return

    sb = _build_sandbox(tmp_path / f"mut-{uuid.uuid4().hex}", verify_text=_mutated_verify(mut))
    if expect in ("guard_rejects_removed", "guard_call_removed"):
        wt = _make_worktree(sb, "pkg")
        # ⚠️ 变异脚本必须**物理落在这个 worktree 里**（真脚本的 ROOT 由自己所在位置算出）
        mut_script = wt / "verify-all.sh"
        mut_script.write_text(_mutated_verify(mut), encoding="utf-8")
        os.chmod(mut_script, 0o755)
        v = run_verify(sb, wt, tmp_path, script=mut_script)
        assert v.rc != 5, f"变异「{label}」**没被抓住**（仍被守卫拒绝）：rc={v.rc}\n{v.out}"
        assert "套件内全量入口被**拒绝**" not in v.out, (
            f"变异「{label}」仍打出了拒绝报文（只是退出码碰巧不是 5）⇒ 红证没抓住真对象：\n{v.out}"
        )
        assert v.rc not in (3, 4, 126, 127), (
            f"变异「{label}」的读数弱：退出码 {v.rc} 可能是「没走到守卫」或「环境坏了」而不是"
            f"「守卫失效」—— 那样这条红证就是**假绿**：\n{v.out}"
        )
        # ⚠️ 读数**不能**是「锁文件还在」：`macquire` 挂了 `trap … EXIT` ⇒ 脚本一退出锁就被删，
        #    事后看**恒 False**（本判据第一版正是这么写的 = 空断言，实测被抓出来）。
        #    改判**日志**：变异体必须真走到「拿到锁 + 进入档位分发」那一步。
        assert "已获取机器级重活锁" in v.out, (
            f"变异「{label}」没被抓住（也没走到重活面：没有拿到机器级锁）—— 读数太弱：\n{v.out[:800]}"
        )
        assert "MIGAO 快速验证" in v.out, (
            f"变异「{label}」没被抓住（没进入档位分发 = 重活还没开始）：\n{v.out[:800]}"
        )
        # 对照：真脚本在同一形态下 rc=5 且**不**创建锁（上面 TestPackageWorktreeIsRefused 已钉）
    elif expect == "env_escape_hatch_added":
        wt = _make_worktree(sb, "pkg")
        rc, out = run_guard(sb, wt, tmp_path, script=_mutated_verify(mut),
                            env_extra={"MIGAO_ALLOW_PACKAGE_HEAVY": "1"})
        assert rc == 0, (
            f"变异「{label}」没被抓住（环境变量仍绕不过去）⇒ 判据 9 对这条形态是空断言：rc={rc}\n{out}"
        )
    else:  # pragma: no cover - 防呆
        raise AssertionError(f"未知 expect：{expect!r}")


def test_control_real_script_has_no_mutation_marker():
    """判据 12（对照读数）：真脚本里没有任何变异痕迹（红证不是「冲着坏脚本测的」）。"""
    src = _verify_text()
    for surface, _label, old, new, _expect in MUTATIONS:
        target = (REPO / ("verify-all.sh" if surface == "verify"
                          else "scripts/package-heavy-entry-ledger.sh")).read_text(encoding="utf-8")
        assert old in target, f"真脚本里找不到变异锚点（红证失效）：{old!r}"
        assert new not in target, f"真脚本里出现了变异后的文本：{new!r}"
    # 「只改注释 ⇒ 不红」的对照：守卫调用**在代码面**（剥注释后仍能找到），而不只在说明里
    stripped = "\n".join(ln for ln in src.split("\n") if not ln.lstrip().startswith("#"))
    assert 'package_heavy_guard "$@"' in stripped, (
        "守卫调用只出现在注释里 —— 这就是「有人把它注释掉」的形态（判据 11 的红证正是它）"
    )
    # 反向对照：把守卫调用**写进注释**后，剥注释的代码面里必须找不到它（证明上一条不是恒真）
    commented = src.replace('package_heavy_guard "$@"\nPKG_RC=$?',
                            '# package_heavy_guard "$@"\nPKG_RC=0', 1)
    stripped_commented = "\n".join(ln for ln in commented.split("\n")
                                   if not ln.lstrip().startswith("#"))
    assert 'package_heavy_guard "$@"' not in stripped_commented, (
        "把守卫调用注释掉后代码面里竟然还在 ⇒ 上面那条断言恒真（空断言）"
    )


class TestBatchGateLeavesTheMarker:
    """判据 13：**直连真 `batch-gate.sh`** 测「标记真被留下」这一半接线。"""

    def _run_batch(self, sb: pathlib.Path, tmp_path: pathlib.Path, *args) -> subprocess.CompletedProcess:
        log = tmp_path / f"stub-{uuid.uuid4().hex}.log"
        env = _env(BATCH_GATE_STUB_LOG=str(log), BATCH_GATE_STUB_RC="0")
        return _run([str(sb / "scripts" / "batch-gate.sh"), "--base", "main", *args], sb, env)

    def test_marker_is_really_written_by_the_real_script(self, tmp_path):
        """真脚本跑一次批次（`--keep` 保留工作区）⇒ 工作区里**真出现**标记文件。

        ⚠️ 本判据只断「**标记真被留下**」这一半接线（`batch-gate.sh` 自己的行为/判据在
        `test_batch_gate.py`，**一字不重判**）⇒ 不拿它的退出码当读数（那一次 gate 在沙箱里
        因为缺依赖必然非零，与标记无关）。
        """
        sb = _build_sandbox(tmp_path / "repo")
        assert _run(["git", "checkout", "-q", "main"], sb, _env()).returncode == 0
        proc = self._run_batch(sb, tmp_path, "--no-require-ready", "--keep", "pkg")
        out = proc.stdout + proc.stderr
        assert "已留批次标记" in out, f"真脚本没有打印「留标记」那一步：\n{out}"
        # 工作区从 git 自己那本账里取（**不**按目录名 glob —— 判据不该假设路径约定）
        listing = _run(["git", "-C", str(sb), "worktree", "list", "--porcelain"],
                       sb, _env()).stdout
        mirs = [ln.split(" ", 1)[1] for ln in listing.splitlines() if ln.startswith("worktree ")]
        wts = [pathlib.Path(w) for w in mirs if w != str(sb)]
        assert wts, f"批次没留下集成工作区（--keep）：\n{out}"
        found = []
        for w in wts:
            r = _run(["git", "-C", str(w), "rev-parse", "--git-path", MARKER], sb, _env())
            mp = r.stdout.strip()
            if mp and pathlib.Path(mp).is_file():
                found.append((w, pathlib.Path(mp)))
        assert found, (
            f"真 batch-gate.sh 没有在集成工作区里留下标记 {MARKER} —— verify-all.sh 的判别读不到它：\n"
            f"{out}"
        )
        wt, marker_file = found[0]
        assert wt.name.startswith("batch-") or "batch-" in str(wt), f"非预期的工作区名：{wt}"
        # **端到端**：那个带标记的工作区里，角色守卫必须放行（标记 → 判定 的接线在）
        script_in(wt)
        rc, gout = run_guard(sb, wt, tmp_path)
        assert rc == 0, f"带标记的集成工作区应放行，实得 rc={rc}：\n{gout}"
        # 摘掉标记 ⇒ 立刻拒绝（同一工作区，唯一变量就是标记）
        marker_file.unlink()
        rc2, gout2 = run_guard(sb, wt, tmp_path)
        assert rc2 == 5, f"摘掉标记后应拒绝，实得 rc={rc2}：\n{gout2}"
