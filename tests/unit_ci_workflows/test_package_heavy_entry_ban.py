# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
r"""**子包 worktree 不许直跑全量**的角色判定判据（issue #6084）。

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
  ⇒ **拒绝**（fail-closed）。🔴 这一形态的**行为面**原本**未固化**，本包把它固化了，并**因此修掉
  一个真实缺陷**（判据 19~20）：
  ① `package_heavy_role` 原先**两次独立**调用 `git rev-parse` ⇒ 两次失败都返回空串 ⇒
     `[ "" = "" ]` 判真 ⇒ 非 git 目录被算成 `primary`（**放行**）；
  ② 角色守卫原先排在**「禁空跑」判定之后** ⇒ 非 git 目录里 `origin/main` 也不存在 ⇒ 变更集为空
     ⇒ 先 `exit 3`（「无变更」）早退 ⇒ **永远走不到拒绝分支**（文档承诺的 `exit 5` 是空头支票）。
  实测：修前 `cwd=/tmp` 跑 `quick` 得 **rc=3**；修后 **rc=5** + 三点报文 + 台账记一条
  `role=unknown`。修法 = 取值口 `_git_rev_parse`（退出码 / 空输出收进同一条判据）
  + 守卫**前移**到「禁空跑」之前（顺序即语义：**能不能跑**优先于**跑什么**）；
- 判据**不保证**有人不用 `verify-all.sh`（直连 `pytest tests/unit_ci_workflows`）—— 那一路由
  `tests/unit_ci_workflows/conftest.py` 的套件自带准入 + `test_suite_self_lock.py` 承担；
- 判据**不判**「批次粒度优化该不该重启」（那是 `docs/wiki/Dev-Mode-Balance.md` §10 的裁定；
  本台账只提供它的读数）；
- 标记文件是**可删的**（删了就被当成子包 worktree 拒绝）—— 这是**有意**的 fail-closed 方向；
- **夹具已抽成共享 harness**：`tests/unit_ci_workflows/heavy_entry_sandbox.py`（本文件不再自带
  那份自足临时仓夹具；血泪教训逐条在它的模块 docstring 里）。**新写同类判据请 import 它，
  不要再抄一份** —— 抄一份 = 第二份判定，真实现改了副本不改，判据会静默假绿；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import uuid

import pytest


# ── 共享沙箱夹具（issue #6085 的后续包）──────────────────────────────────────
# 本文件**不再自带**那份自足临时仓夹具：它已抽成可 import 的共享 harness
# `tests/unit_ci_workflows/heavy_entry_sandbox.py`（`test_batch_gate.py` 当年抄了第二份）。
# 为什么必须共享（血泪教训逐条写在 harness 的模块 docstring 里）：**仓根那份 `verify-all.sh`
# 必须是桩** —— 放真脚本会让每次 `batch-gate.sh` 都去跑一次真 gate ⇒ 互等机器级重活锁 ⇒
# 180s 超时（`#6085` 首轮 CI 实测；修后同一条腿 0:35）。判据一多，这个坑就会被抄进第二份副本。
from unit_ci_workflows import heavy_entry_sandbox as hs   # noqa: E402

REPO = hs.REPO
VERIFY = hs.VERIFY
BATCH = hs.BATCH
LEDGER_SH = str(hs.LEDGER_SH)
MARKER = hs.MARKER

_run = hs.run            # 带**显式 timeout** 的子进程调用（本机没有 `timeout(1)`）


def _env(**extra) -> dict:
    """干净子进程环境，锁 / 台账一律落在 `tmp_path`（`hs.clean_env` 的**结构保证**）。

    `tmp_path` 取本判据自己那本的目录（显式传了 `MIGAO_PACKAGE_HEAVY_LEDGER` 时按它的父目录，
    否则落 `tests/unit_ci_workflows/`）—— 两者都**不在 `$HOME` 下**，因此**不可能**是真锁 /
    真台账（真锁 = `$HOME/.migao-heavy.lock`）。判据只认 `extra` 里显式给的那条路径。
    """
    explicit = extra.get("MIGAO_PACKAGE_HEAVY_LEDGER")
    tmp = pathlib.Path(explicit).parent if explicit else         pathlib.Path(__file__).resolve().parent
    return hs.clean_env(tmp, **extra)


def _verify_text() -> str:
    return hs.real_verify_text()


def _mutated(rel: str, mut) -> str:
    """把变异**真的写到一个真对象**上（`rel` = 注入面），返回变异后的全文。"""
    _surface, _label, old, new, _expect = mut
    return hs.mutate(rel, old, new)


def _mutated_verify(mut) -> str:
    return _mutated("verify-all.sh", mut)


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 1~2：子包 worktree ⇒ 拒绝，且**先于任何重活**
# ══════════════════════════════════════════════════════════════════════════════════════

class TestPackageWorktreeIsRefused:
    def test_package_worktree_is_refused_with_a_named_verdict(self, tmp_path):
        """判据 1：真 `verify-all.sh` 在 linked worktree（子包形态）里 ⇒ 非零 + 报文三点齐全。"""
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        script = hs.install_real_script(wt)
        v = hs.run_verify(sb, wt, tmp_path, script=script)
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
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        script = hs.install_real_script(wt)
        v = hs.run_verify(sb, wt, tmp_path, script=script)
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
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "integration-integration")     # 名字里没有 `batch`
        # 反例工作区：名字**故意**取成 batch-*（名字前缀不是判据）

        # 标记位置由 git 现取（判据**不写死**路径 —— 写死就成了第二份约定的副本）
        marker_path = hs.run(["git", "rev-parse", "--git-path", MARKER], wt, _env()).stdout.strip()
        marker_file = pathlib.Path(marker_path)
        assert marker_file.is_absolute(), f"git-path 没给出绝对路径：{marker_path}"
        marker_file.write_text("batch-integration\n", encoding="utf-8")
        rc_with, out_with = hs.run_guard(sb, wt, tmp_path)
        assert rc_with == 0, f"带标记的批次集成工作区应**放行**，实得 rc={rc_with}：\n{out_with}"
        marker_file.unlink()
        rc_without, out_without = hs.run_guard(sb, wt, tmp_path)
        assert rc_without == 5, (
            "**摘掉标记**后应被拒（判别必须读标记，而不是名字前缀 / 环境变量）："
            f"实得 rc={rc_without}\n{out_without}"
        )
        # 反向自证：名字里带 `batch-` 但**没有**标记 ⇒ 也必须拒（名字前缀不是判据）
        wt_named = hs.build_worktree(sb, "batch-991231-000000")
        rc_named, out_named = hs.run_guard(sb, wt_named, tmp_path)
        assert rc_named == 5, (
            "工作区**名字**叫 `batch-*` 但没有标记 ⇒ 必须拒绝（名字前缀会漂、任何人手建一个就有）："
            f"实得 rc={rc_named}\n{out_named}"
        )

    def test_primary_checkout_is_allowed(self, tmp_path):
        """判据 4：主检出 ⇒ 放行（人工 / 批次的一次性全量在这里跑）。

        `run_guard`（不是真跑脚本）：判的是**角色判定**这一层，不跑 gate 档的重活
        （真跑全量的时序/退出码由上面判据 1~2 与 `test_machine_heavy_lock.py` 承担）。
        """
        sb = hs.build(tmp_path / "repo")
        rc, out = hs.run_guard(sb, sb, tmp_path)
        assert rc == 0, f"主检出应放行，实得 rc={rc}：\n{out}"
        assert "拒绝" not in out, out

    def test_ci_environment_is_unaffected(self, tmp_path):
        """判据 5：`CI` 为真 ⇒ 本块整段不适用（托管 runner 不占本机资源）。"""
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        rc, out = hs.run_guard(sb, wt, tmp_path, env_extra={"CI": "true"})
        assert rc == 0, f"CI 上不得被拦（否则整目录那条腿在 CI 上永远红），实得 rc={rc}：\n{out}"
        assert "CI 为真" in out, f"「未跑」必须说出来（否则读者以为判过了）：\n{out}"
        # 真脚本这条路的读数：CI 为真时也不得出现 exit 5（把真脚本放进 worktree 跑一次）
        script = hs.install_real_script(wt)
        v = hs.run_verify(sb, wt, tmp_path, script=script, env_extra={"CI": "true"})
        assert v.rc != 5, f"CI 为真时真脚本仍被角色守卫拦下：rc={v.rc}\n{v.out}"

    def test_explicit_flag_allows_and_prints_a_loud_line(self, tmp_path):
        """判据 6：**显式 flag ⇒ 放行** + 醒目一行 + 台账记一条 `override`。"""
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        rc, out = hs.run_guard(sb, wt, tmp_path, "--allow-package-heavy")
        assert rc == 0, f"显式 flag 应放行，实得 rc={rc}：\n{out}"
        assert "绕过了批次口径" in out, f"放行必须**醒目**地说出绕过了什么：\n{out}"
        assert "⚠️" in out, f"放行行必须醒目（带警示符）：\n{out}"

    def test_denied_and_allowed_are_counted_separately(self, tmp_path):
        """判据 8：台账口径 —— 拒绝 / 放行**两类都能现取计数**。"""
        ledger = tmp_path / "counts.jsonl"
        sh = "bash"
        ledger_sh = str(LEDGER_SH)
        env = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="a.1")
        assert hs.run([sh, ledger_sh, "append", "package", "refused", "子包直跑"], env=env).returncode == 0
        env2 = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="a.2")
        assert hs.run([sh, ledger_sh, "append", "package", "override", "flag"], env=env2).returncode == 0
        got = hs.run([sh, ledger_sh, "count"], env=_env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger)))
        assert got.returncode == 0, got.stdout + got.stderr
        assert "refused=1" in got.stdout, f"拒绝计数取不出来：{got.stdout!r}"
        assert "override=1" in got.stdout, f"放行计数取不出来：{got.stdout!r}"

    def test_ledger_is_idempotent_per_invocation(self, tmp_path):
        """判据 7：**同一次调用**（同一 `MIGAO_ROLE_LEDGER_ID`）记两笔 ⇒ 账上只有一笔。"""
        ledger = tmp_path / "idem.jsonl"
        sh = "bash"
        ledger_sh = str(LEDGER_SH)
        env = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="same.42")
        first = hs.run([sh, ledger_sh, "append", "package", "refused", "第一次"], env=env)
        second = hs.run([sh, ledger_sh, "append", "package", "refused", "第二次"], env=env)
        assert first.returncode == 0 and second.returncode == 0, first.stdout + second.stdout
        assert "dup" in second.stdout, f"重复调用没有走幂等分支：{second.stdout!r}"
        records = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                   if ln.strip().startswith('{"id"')]
        assert len(records) == 1, f"同一次调用被记了 {len(records)} 笔（应为 1）：{records}"
        # 反向自证：换一个 id（= 另一次调用）⇒ 照旧能记账（幂等不是「台账只记一笔」）
        env2 = _env(MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger), MIGAO_ROLE_LEDGER_ID="other.43")
        hs.run([sh, ledger_sh, "append", "package", "refused", "另一次"], env=env2)
        assert len([ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                    if ln.strip().startswith('{"id"')]) == 2, "换 id 后没记上 ⇒ 台账成了写不进的死账"

    def test_the_refusal_itself_is_recorded(self, tmp_path):
        """判据 6 的另一半：**不加 flag 的拒绝**必须记一条 `refused`（不许静默）。"""
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        script = hs.install_real_script(wt)
        v = hs.run_verify(sb, wt, tmp_path, script=script)
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
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        for var in ("MIGAO_ALLOW_PACKAGE_HEAVY", "MIGAO_PACKAGE_HEAVY_SKIP",
                    "MIGAO_BATCH_GATE_SKIP_READY", "MIGAO_PACKAGE_HEAVY_ENTRY_BAN_SKIP"):
            rc, out = hs.run_guard(sb, wt, tmp_path, env_extra={var: "1"})
            assert rc == 5, (
                f"环境变量 {var}=1 竟然绕过了角色守卫 —— 逃生口必须是**命令行可见**的"
                f"（本仓刚按 #6056 删掉一个不可见的环境变量逃生口）：rc={rc}\n{out}"
            )
        # 反向自证：同一次 setUp 下真 flag 必须仍然有效（否则上面那条恒真）
        rc_flag, _ = hs.run_guard(sb, wt, tmp_path, "--allow-package-heavy")
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
            assert hs.run(["bash", str(mutated_sh), "append", "package", "refused", "x"],
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
            hs.run(["bash", str(LEDGER_SH), "append", "package", "refused", "x"], env=env_real)
        n_real = len([ln for ln in real_ledger.read_text(encoding="utf-8").splitlines()
                      if ln.strip().startswith('{"id"')])
        assert n_real == 1, f"对照读数错：真脚本下同 id 应记 1 笔（实得 {n_real}）"
        return

    sb = hs.build(tmp_path / f"mut-{uuid.uuid4().hex}", verify_text=_mutated_verify(mut))
    if expect in ("guard_rejects_removed", "guard_call_removed"):
        wt = hs.build_worktree(sb, "pkg")
        # ⚠️ 变异脚本必须**物理落在这个 worktree 里**（真脚本的 ROOT 由自己所在位置算出）
        mut_script = hs.install_real_script(wt, text=_mutated_verify(mut))
        v = hs.run_verify(sb, wt, tmp_path, script=mut_script)
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
        wt = hs.build_worktree(sb, "pkg")
        rc, out = hs.run_guard(sb, wt, tmp_path, script=_mutated_verify(mut),
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
        return hs.run([str(sb / "scripts" / "batch-gate.sh"), "--base", "main", *args], sb, env)

    def test_marker_is_really_written_by_the_real_script(self, tmp_path):
        """真脚本跑一次批次（`--keep` 保留工作区）⇒ 工作区里**真出现**标记文件。

        ⚠️ 本判据只断「**标记真被留下**」这一半接线（`batch-gate.sh` 自己的行为/判据在
        `test_batch_gate.py`，**一字不重判**）⇒ 不拿它的退出码当读数（那一次 gate 在沙箱里
        因为缺依赖必然非零，与标记无关）。
        """
        sb = hs.build(tmp_path / "repo")
        assert hs.run(["git", "checkout", "-q", "main"], sb, _env()).returncode == 0
        proc = self._run_batch(sb, tmp_path, "--no-require-ready", "--keep", "pkg")
        out = proc.stdout + proc.stderr
        assert "已留批次标记" in out, f"真脚本没有打印「留标记」那一步：\n{out}"
        # 工作区从 git 自己那本账里取（**不**按目录名 glob —— 判据不该假设路径约定）
        listing = hs.run(["git", "-C", str(sb), "worktree", "list", "--porcelain"],
                       sb, _env()).stdout
        mirs = [ln.split(" ", 1)[1] for ln in listing.splitlines() if ln.startswith("worktree ")]
        wts = [pathlib.Path(w) for w in mirs if w != str(sb)]
        assert wts, f"批次没留下集成工作区（--keep）：\n{out}"
        found = []
        for w in wts:
            r = hs.run(["git", "-C", str(w), "rev-parse", "--git-path", MARKER], sb, _env())
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
        hs.install_real_script(wt)
        rc, gout = hs.run_guard(sb, wt, tmp_path)
        assert rc == 0, f"带标记的集成工作区应放行，实得 rc={rc}：\n{gout}"
        # 摘掉标记 ⇒ 立刻拒绝（同一工作区，唯一变量就是标记）
        marker_file.unlink()
        rc2, gout2 = hs.run_guard(sb, wt, tmp_path)
        assert rc2 == 5, f"摘掉标记后应拒绝，实得 rc={rc2}：\n{gout2}"


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据 19~21：非 git 目录 / `git` 不可用 ⇒ `unknown` ⇒ 拒绝（**行为面**；issue #6084 未固化项）
# ══════════════════════════════════════════════════════════════════════════════════════

#: 注入点：把角色判定换成「算不出角色也当 `primary`」——**这正是本包修掉的那个真实缺陷形态**
#: （两次 `git rev-parse` 都失败 ⇒ 两个空串相等 ⇒ 误判 `primary` ⇒ **fail-open**）。
#: 命中数 ≠ 1 ⇒ 判红 = 变异没生效（红证会变成空断言）。
ROLE_MUTATIONS = [
    (
        "unknown_became_primary",
        """package_heavy_role() {
  local abs common
  #: `git` 不可用 / 工作树外 ⇒ **unknown**（调用方 fail-closed 拒绝）。
  abs="$(_git_rev_parse --absolute-git-dir)" || { echo unknown; return 0; }
  common="$(_git_rev_parse --path-format=absolute --git-common-dir)" || { echo unknown; return 0; }""",
        """package_heavy_role() {
  local abs common
  abs="$(_git_rev_parse --absolute-git-dir)" || { echo primary; return 0; }
  common="$(_git_rev_parse --path-format=absolute --git-common-dir)" || { echo primary; return 0; }""",
    ),
]


def _non_git_dir(tmp_path: pathlib.Path, script_text: str | None = None) -> pathlib.Path:
    """造一个**非 git 目录**（`tmp_path` 下），把真 `verify-all.sh` + 真 `scripts/` 放进去。

    ⚠️ 脚本必须**物理落在这个目录里**（真脚本的 `ROOT` 由自己所在位置算出，且它一开始就
    `cd "$ROOT"`）—— 否则那个 `cd` 会把它带**回真仓库**，于是跑出来的是**真仓库**的读数，
    「非 git 目录」这个形态根本走不到（实测：拿真仓那份副本 + `cwd=/tmp` 跑，脚本 cd 回仓库、
    角色算成 `package` ⇒ 判的是**另一种**形态；这正是 harness docstring「血泪教训 2」那条坑）。
    真 `scripts/` 一并放进去：这样「拒绝被记一笔」这一半也能在**真台账脚本**上判。
    """
    d = tmp_path / "not-a-repo"
    d.mkdir(exist_ok=True)
    shutil.copytree(REPO / "scripts", d / "scripts", dirs_exist_ok=True)
    hs.install_real_script(d, text=script_text)
    return d


def _run_non_git(d: pathlib.Path, tmp_path: pathlib.Path, *args: str, tier: str = "quick",
                 extra_env: dict | None = None, path: str | None = None):
    """在非 git 目录里跑真脚本；返回 `(CompletedProcess, ctx)`（`ctx` 里有锁 / 台账路径读数）。"""
    lock = tmp_path / f"ng-lock-{uuid.uuid4().hex}"
    ledger = tmp_path / f"ng-ledger-{uuid.uuid4().hex}.jsonl"
    env = _env(MIGAO_HEAVY_LOCK_FILE=str(lock), MIGAO_PACKAGE_HEAVY_LEDGER=str(ledger))
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    if path is not None:
        env["PATH"] = path
    # ⚠️ 用**绝对路径**的 bash 起（PATH 桩那一路可能没有 `bash` ⇒ 否则死在「找不到 bash」上，
    #    而不是死在角色判定上 = 读数指错对象）。
    proc = subprocess.run([shutil.which("bash") or "/bin/bash", str(d / "verify-all.sh"),
                           tier, *args], cwd=str(d), capture_output=True, text=True,
                          env=env, timeout=180)
    return proc, {"lock": lock, "ledger": ledger}


class TestNonGitFailsClosed:
    """判据 19：**行为面**——非 git 目录 / `git` 不可用 ⇒ 角色 `unknown` ⇒ **拒绝**（fail-closed）。

    ⚠️ 这条判据守的是「**文档承诺 = 代码行为**」：`docs/wiki/Development.md` 与
    `test_package_heavy_entry_ban.py` 的边界段都写着「`git` 不可用 ⇒ 判 `unknown` ⇒ **拒绝**
    （fail-closed）」，但**修前**实测是 `rc=3`（「无变更」）—— 因为两个取值点各自 `git rev-parse`，
    失败都返回空串 ⇒ `[ "" = "" ]` 判真 ⇒ 算成 `primary`（**放行**）。⇒ 本包两处一起修：
    ① `verify-all.sh` 的 `_git_rev_parse` 把「退出码 / 空输出」收进同一条判据；
    ② 角色守卫**前移到「禁空跑」判定之前**（否则非 git 目录里变更集也算不出来 ⇒ 先 `exit 3` 早退，
    仍然走不到拒绝分支）。
    """

    def test_plain_non_git_directory_is_refused(self, tmp_path):
        """非 git 目录（`git` 可用、但 cwd 不是工作树）⇒ 非零（5）+ 三点报文 + 台账记一笔。"""
        d = _non_git_dir(tmp_path)
        proc, ctx = _run_non_git(d, tmp_path)
        out = proc.stdout + proc.stderr
        assert proc.returncode == 5, (
            f"非 git 目录里跑全量必须 fail-closed 拒绝（exit 5），实得 {proc.returncode}：\n{out}"
        )
        assert "没有跑" in out, f"「没跑」必须长得像「没跑」：\n{out}"
        # 三点：为什么 / 替代 / 怎么显式跑（与判据 1 同口径，**不写死文案**）
        assert "子包 worktree" in out, f"报文没写清**为什么**：\n{out}"
        assert "batch-gate.sh" in out, f"报文没给**替代**（批次入口）：\n{out}"
        assert "--allow-package-heavy" in out, f"报文没给**怎么显式跑**：\n{out}"
        assert not ctx["lock"].exists(), (
            "拒绝之前拿了机器级锁 —— 守卫必须在 `macquire` 之前（拿锁本身就是重活面）"
        )

    def test_the_unknown_refusal_is_recorded_as_unknown(self, tmp_path):
        """这一半是**台账口径**：非 git 目录的拒绝按 `role=unknown` 记，不许混进 `package`。

        （修前这一形态**根本走不到**守卫 ⇒ 账上一条都没有 —— 台账读不出「有人在工作树外跑全量」。）
        """
        d = _non_git_dir(tmp_path)
        proc, ctx = _run_non_git(d, tmp_path)
        assert proc.returncode == 5, proc.stdout + proc.stderr
        records = hs.ledger_records(ctx["ledger"].read_text(encoding="utf-8"))
        assert [r["role"] for r in records] == ["unknown"], (
            f"非 git 目录的拒绝没有按 role=unknown 记一笔：{records}"
        )
        assert [r["decision"] for r in records] == ["refused"], records

    def test_git_missing_from_path_is_refused(self, tmp_path):
        """变体：`PATH` 里**没有 `git`**（PATH 桩驱动）⇒ 同样 fail-closed（`exit 5`）+ 记一笔。

        ⚠️ 这条路**只能**靠 PATH 桩驱动 —— 靠环境「碰巧没有 git」写断言在开发机 / CI 上
        **永远走不到**（空断言形态）。故先自证桩生效。
        """
        d = _non_git_dir(tmp_path)
        slim = hs.slim_path(tmp_path, ("bash", "sh", "env", "date", "sed", "grep", "awk", "sort",
                                       "tr", "cut", "head", "tail", "cat", "rm", "mkdir",
                                       "mktemp", "chmod", "ls", "dirname", "basename", "uname",
                                       "printf", "wc", "python3"))
        assert shutil.which("git", path=slim) is None, f"PATH 桩失效（还能找到 git）：{slim}"
        proc, ctx = _run_non_git(d, tmp_path, path=slim)
        out = proc.stdout + proc.stderr
        assert proc.returncode == 5, (
            f"`git` 不在 PATH 时必须 fail-closed（exit 5），实得 {proc.returncode}：\n{out}"
        )
        assert "子包 worktree" in out and "batch-gate.sh" in out, f"三点报文不全：\n{out}"
        assert "--allow-package-heavy" in out, out
        assert not ctx["lock"].exists(), "拒绝之前拿了机器级锁（守卫顺序错了）"
        records = hs.ledger_records(ctx["ledger"].read_text(encoding="utf-8"))
        assert [r["role"] for r in records] == ["unknown"], (
            f"`git` 不可用 ⇒ 角色应是 unknown：{records}"
        )


class TestUnknownRoleInjectionIsCaught:
    """判据 20：**注入式红证** —— 把「`unknown` ⇒ 拒绝」这一支换成「当 `primary`」⇒ 上面必红。"""

    def test_unknown_as_primary_is_caught(self, tmp_path):
        """变异体 = 「算不出角色也当 `primary`」（**修前的真实缺陷形态**）⇒ 本判据当场抓住。

        判红读数（三条**互相独立**，缺一条这条红证就是空的）：
        ① 退出码**不再是 5**（守卫放行了）；
        ② 脚本**继续往下走** —— 打出了「无变更 ⇒ exit 3」那句早退报文（= 它真的进了后续流程）；
        ③ 台账里**没有** `role=unknown` 的拒绝记录。
        """
        _label, old, new = ROLE_MUTATIONS[0]
        mutated = hs.mutate("verify-all.sh", old, new)      # 命中数 ≠ 1 ⇒ 这里就判红
        d = _non_git_dir(tmp_path, script_text=mutated)
        proc, ctx = _run_non_git(d, tmp_path)
        out = proc.stdout + proc.stderr
        assert proc.returncode != 5, (
            f"变异「unknown 当 primary」**没被抓住**（仍被守卫拒绝）：rc={proc.returncode}\n{out}"
        )
        assert "套件内全量入口被**拒绝**" not in out, (
            f"变异体仍打出了拒绝报文（只是退出码碰巧不是 5）⇒ 红证没抓住真对象：\n{out}"
        )
        assert "无变更 ⇒ 未执行任何检查" in out, (
            f"变异体**没走到**后续流程（读数太弱：既没拒绝、也没继续）—— 这条红证证明不了判别力：\n{out}"
        )
        assert not ctx["lock"].exists(), (
            "变异体在非 git 目录里仍走到了 `macquire`？—— 那说明它进了重活面（与「继续往下走」一致）"
        )
        # 台账在 fail-open 路径下可能**根本没被创建**（没有拒绝要记）——「不存在」与「空」都算没记。
        records = (hs.ledger_records(ctx["ledger"].read_text(encoding="utf-8"))
                   if ctx["ledger"].exists() else [])
        assert records == [], f"变异体下不该有 unknown 拒绝记录（它是 fail-open 的）：{records}"

    def test_control_real_script_has_no_role_mutation_marker(self):
        """对照读数：真脚本里没有变异痕迹，且**真有**那句 fail-closed 的 `unknown` 分支。"""
        src = _verify_text()
        for _label, old, new in ROLE_MUTATIONS:
            assert old in src, f"真脚本里找不到变异锚点（红证失效）：{old!r}"
            assert new not in src, f"真脚本里出现了变异后的文本：{new!r}"
        assert "_git_rev_parse" in src and "echo unknown" in src, (
            "真脚本里没有 fail-closed 的 unknown 分支（判据 19 会变成空断言）"
        )


class TestHarnessKeepsOffSharedFiles:
    """判据 21：**隔离保证的形状** —— 真锁 / 真台账在跑完本文件那几条真跑判据后**原封不动**。

    为什么是「形状」而不是「纪律」：`hs.clean_env` 把 `MIGAO_HEAVY_LOCK_FILE` /
    `MIGAO_PACKAGE_HEAVY_LEDGER` 收口到 `tmp_path`（`setdefault` + 显式路径也必须过
    `unscoped_tmp_root`）⇒ 判据**结构上**拿不到真锁 / 真台账的路径。本判据是那次结构设计的
    **读数**：跑一遍真跑形态（真 `verify-all.sh` + 真 `scripts/`），真锁与真台账必须一字未动。

    ⚠️ 本判据**不创建**真锁 / 真台账：只在「不存在」与「未变（mtime / size / inode）」两个方向上断言。
    """

    def test_real_lock_and_ledger_are_untouched_by_a_real_run(self, tmp_path):
        """跑一次真跑形态 ⇒ 真 `~/.migao-heavy.lock` 与真台账的存在性 / stat 三项逐项相同。"""
        before = hs.true_and_ledger_states()
        sb = hs.build(tmp_path / "repo")
        wt = hs.build_worktree(sb, "pkg")
        v = hs.run_verify(sb, wt, tmp_path, script=hs.install_real_script(wt))
        assert v.rc == 5, f"前置：子包 worktree 里应被拒（exit 5），实得 {v.rc}：\n{v.out}"
        rc, out = hs.run_guard(sb, wt, tmp_path)
        assert rc == 5, f"前置：守卫应拒绝，实得 {rc}：\n{out}"
        hs.assert_nothing_touched(before, hs.true_and_ledger_states(),
                                  what="跑完真跑形态之后")

    def test_harness_env_pins_lock_and_ledger_under_tmp(self, tmp_path):
        """结构性自证：`hs.clean_env` 的两个落点**必在 `$HOME` 之外**，且显式路径也受同一约束。

        反向对照：显式把锁指到 `$HOME` 下 ⇒ `clean_env` **拒绝**（否则「结构保证」只是口号）。
        """
        env = hs.clean_env(tmp_path)
        for key in ("MIGAO_HEAVY_LOCK_FILE", "MIGAO_PACKAGE_HEAVY_LEDGER"):
            hs.unscoped_tmp_root(env[key])          # 不在 $HOME 下 ⇒ 不可能是真锁 / 真台账
        with pytest.raises(AssertionError):
            hs.clean_env(tmp_path, MIGAO_HEAVY_LOCK_FILE=str(hs.DEFAULT_REAL_LOCK))
