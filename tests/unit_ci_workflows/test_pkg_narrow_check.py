# case_ids: PK-001
"""「包级定点清单」入口 `scripts/pkg-narrow-check.sh` 的判据（issue #6250）。

## 病灶（本轮实测 4 次，逐字红因见 issue #6250）

两类改动会**必然**顶穿两条冻结台账，而它们此前只在**全量档**（`verify-all.sh gate|full`）跑到：

| 触发改动 | 会红的判据 | 逐字红因（实例） |
|---|---|---|
| 新增 / 修改 Java 测试 | `BusinessClockTestSourceGuardTest.outOfScopeSpellingsPresenceIsFrozen` | `Expecting empty but was: ["覆盖外拼写 \\`System.nanoTime(\\` 登记 presentInTree=false 而现取=true"]`（#6237） |
| 新增 `[backend-contract]` 用例且 `expectations: []` | `test_case_machine_fail_channel.py::test_i3_anchor_matches_reality_and_is_only_shrinking` | `实测 backend_contract_scoring_zero=117 与锚点 116 不一致`（#6231/#6226/#6224/#6237） |

并行修复包按「只跑定点」的纪律（D 口径）**必然漏掉**这两条 ⇒ 直到 CI 才红。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 红证（注入式） |
|---|---|---|
| 1 | **自动探测 = 机械判定**：diff 里出现 `src/test/**/*.java` ⇒ **自动**带上 `--java-tests`（不靠人记得加开关） | 在沙箱里造一个真 `src/test/**/*.java` ⇒ 输出里出现该腿的 `▶ 跑` 且**真 runner 被调用** |
| 2 | 同上，`.github/cases/**` 或 `claims/**` 变动 ⇒ **自动**带上 `--new-cases` | 造一个真 `.github/cases/***.yml` ⇒ 该腿 `▶ 跑` 且真 runner 被调用 |
| 3 | **反向对照**：不改测试、不加用例的包 ⇒ **不跑**那两条（也不把它们拖成全量档） | 只有一条无关文件变动 ⇒ 两条都 `⏭️ 未跑` 且**两个 runner 都没被调用**（命令清单断言） |
| 4 | **不许静默跳过**：未跑的腿必须逐条打印「未跑 + 触发面 + 依据」 | 判据 3 的输出里必须出现 `⏭️  未跑：` + 触发面字面量 |
| 5 | 无开关时**只跑三条轻量门禁**，**不做全量** | 输出里**不得**出现 `verify-all.sh gate` / `batch-gate.sh` / 整目录 `pytest tests/unit_ci_workflows`（解析调用记录） |
| 6 | **fail-closed**：基准取不到 / 变更集为空 ⇒ 非零（`3`），且**不许**记成通过 | 删掉 `origin/main` ⇒ `rc=3`；零 diff 树 ⇒ `rc=3` |
| 7 | **只读**（issue #6250 交付要求 1）：整跑一遍**不写任何文件** | 全树快照前后逐字节相同（三个 runner 都是桩 ⇒ 无正当写点） |
| 8 | **判别力自证**：把「自动探测」那一行从脚本里摘掉 ⇒ 判据 1/2 **当场红** | 内存变异体（§28.1 出口①）在同一夹具上跑 |

## 边界（照实登记，§19.1）

- 判据跑的是**真脚本**（`install_real_script` 放进沙箱工作树），但三个 runner 是**桩**
  （`MIGAO_PKG_JAVA_RUNNER` / `MIGAO_PKG_PYTHON`）⇒ 它判的是**派发与选择**，
  **不判**那两条判据自身的红绿（那是它们各自文件的事）。
- ⚠️ 注入的是**路径**（触发面的形状），不注入真缺陷 —— 本判据证明「该跑的时候真的会跑、
  不该跑的时候真的不跑」（双向），**不声称**「跑起来一定会红」。
- **自动探测只看路径**：改名 / 换目录的传统 Java 测试目录（非 `src/test`）不在面内
  （`--java-tests` 是那条逃生口）。
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from unit_ci_workflows import heavy_entry_sandbox as hs

SCRIPT_REL = "scripts/pkg-narrow-check.sh"
REAL_SCRIPT = hs.REPO / SCRIPT_REL

#: 记录每次 runner 调用的桩（真 runner 的参数**逐字**转发到日志，便于断言「跑的是哪条腿」）。
RECORDER = """#!/usr/bin/env bash
if [ -n "${PROBE_LOG:-}" ]; then
  { echo "--- $0"; for a in "$@"; do printf '%s\\n' "$a"; done; } >> "$PROBE_LOG"
fi
exit "${PROBE_RC:-0}"
"""


def _probe_repo(tmp_path: Path) -> Path:
    """自足沙箱仓（真 `scripts/pkg-narrow-check.sh` + 桩 runner）—— 复用共享 harness，不手搓。"""
    sb = hs.build(tmp_path / "repo")
    (sb / "scripts").mkdir(exist_ok=True)
    (sb / "scripts" / "pkg-narrow-check.sh").write_text(
        REAL_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(sb / "scripts" / "pkg-narrow-check.sh", 0o755)
    # 必须**提交**：否则 `git status --porcelain -uall` 恒有它 ⇒ ①「零 diff」那条判据永远走不到，
    # ②「只读」快照把它算成「执行期间新增的文件」（实测：两条判据都因此假红）。
    hs.commit(sb, "probe: install real pkg-narrow-check.sh")
    return sb


def _probe_env(tmp_path: Path, sb: Path, **extra) -> dict:
    env = hs.clean_env(tmp_path, **extra)
    env["PROBE_LOG"] = str(tmp_path / "probe.log")
    env["MIGAO_PKG_JAVA_RUNNER"] = "mvnw-probe"
    env["MIGAO_PKG_PYTHON"] = "python-probe"
    return env


def _run(sb: Path, tmp_path: Path, *args, expect_rc: int | None = None, **env_extra):
    """跑**真脚本**（在**子包 worktree** 形态里跑：本入口不该受角色守卫影响 ⇒ 见判据 5/6 的读数）。"""
    env = _probe_env(tmp_path, sb, **env_extra)
    proc = hs.run([str(sb / "scripts" / "pkg-narrow-check.sh"), *args], sb, env, timeout=120)
    out = proc.stdout + proc.stderr
    if expect_rc is not None:
        assert proc.returncode == expect_rc, f"rc={proc.returncode}（期望 {expect_rc}）\n{out}"
    return proc.returncode, out


def _log(tmp_path: Path) -> str:
    path = tmp_path / "probe.log"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _write_and_commit(sb: Path, rel: str, text: str) -> None:
    p = sb / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    hs.commit(sb, f"probe {rel}")


def _idle_commit(sb: Path) -> None:
    """一条**不命中任何触发面**的变动（反向对照的输入）。"""
    _write_and_commit(sb, "docs/probe-notes.md", "无关变动\n")


@pytest.fixture()
def probe(tmp_path, monkeypatch):
    """一个沙箱 + 两个 runner 桩（`mvnw-probe` / `python-probe` 记录逐字参数）。"""
    sb = _probe_repo(tmp_path)
    bindir = tmp_path / "probe-bin"
    bindir.mkdir()
    for name in ("mvnw-probe", "python-probe"):
        p = bindir / name
        p.write_text(RECORDER, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    # 让 `cd backend/admin-api` 有地方可去（脚本的 Java 腿会真 cd 进去）。
    (sb / "backend" / "admin-api").mkdir(parents=True, exist_ok=True)
    return sb, tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# 3 · 反向对照：不改测试、不加用例 ⇒ 两条必然项**都不跑**
# ══════════════════════════════════════════════════════════════════════════════

class TestNoTrigger:
    def test_neither_inevitable_leg_runs_when_nothing_triggers(self, probe):
        sb, tmp = probe
        _idle_commit(sb)
        rc, out = _run(sb, tmp, expect_rc=0)
        assert "⏭️  未跑：必然项①" in out, out
        assert "⏭️  未跑：必然项②" in out, out
        assert "▶ 跑：必然项①" not in out and "▶ 跑：必然项②" not in out, out
        # ③ 命令清单断言（**不只是「没打印」**）：两条必然项的**那一条命令**都没进调用记录。
        log = _log(tmp)
        assert "mvnw-probe" not in log, log
        assert "test_case_machine_fail_channel.py" not in log, log
        assert "test_realdb_failclosed.py" in log, log   # 自证：日志桩真的在工作（防空断言）

    def test_skips_are_never_silent(self, probe):
        """④ 「没跑」必须长得像「没跑」：触发面 + 依据都要打印。"""
        sb, tmp = probe
        _idle_commit(sb)
        _, out = _run(sb, tmp, expect_rc=0)
        assert "触发面：src/test/**/*.java" in out, out
        assert "触发面：.github/cases/** 或 claims/**" in out, out
        assert "依据：自动探测" in out, out

    def test_lightweight_gates_run_and_no_full_suite_is_pulled(self, probe):
        """⑤ 无开关时**只**跑三条轻量门禁；绝不把全量档拖进来。"""
        sb, tmp = probe
        _idle_commit(sb)
        _, out = _run(sb, tmp, expect_rc=0)
        for leg in ("轻量门禁①", "轻量门禁②", "轻量门禁③"):
            assert f"▶ 跑：{leg}" in out, out
        log = _log(tmp)
        assert log.count("python-probe") >= 3, log          # 三条轻量门禁都真调了解释器
        assert "-m pytest tests/unit_ci_workflows -q" not in log, log   # 绝不拉起整目录
        assert "pkg-narrow-check.sh" not in log, log                    # 本入口不递归调用自己


# ══════════════════════════════════════════════════════════════════════════════
# 1 · 自动探测：出现 `src/test/**/*.java` ⇒ 自动带上 `--java-tests`
# ══════════════════════════════════════════════════════════════════════════════

class TestJavaTrigger:
    JAVA_REL = "backend/admin-api/src/test/java/com/migao/admin/time/ProbeGuardTest.java"

    def test_java_test_file_auto_enables_wall_clock_leg(self, probe):
        sb, tmp = probe
        _write_and_commit(sb, self.JAVA_REL,
                          "package com.migao.admin.time;\nclass ProbeGuardTest { }\n")
        rc, out = _run(sb, tmp, expect_rc=0)
        assert "▶ 跑：必然项①" in out, out
        assert "自动探测命中 src/test/**/*.java" in out, out
        assert "⏭️  未跑：必然项②" in out, out
        # 真 runner 被调用，且参数**逐字**是那条窄跑命令
        log = _log(tmp)
        assert "mvnw-probe" in log, log
        assert "-Dtest=BusinessClockTestSourceGuardTest" in log, log
        assert "\ntest\n" in log, log
        assert "python-probe" in log and "test_case_machine_fail_channel.py" not in log, log

    def test_no_auto_switch_really_disables_auto_detection(self, probe):
        """`--no-auto` = 「探测被关掉」，必须显式打印该措辞（不是「没命中」）。"""
        sb, tmp = probe
        _write_and_commit(sb, self.JAVA_REL,
                          "package com.migao.admin.time;\nclass ProbeGuardTest { }\n")
        rc, out = _run(sb, tmp, "--no-auto", expect_rc=0)
        assert "已按 --no-auto 关闭" in out, out
        assert "▶ 跑：必然项①" not in out, out
        assert "mvnw-probe" not in _log(tmp), _log(tmp)

    def test_explicit_switch_forces_the_leg(self, probe):
        """显式开关可**强制**（自动探测未命中也跑）—— 本节第 2 条交付要求。"""
        sb, tmp = probe
        _idle_commit(sb)
        _, out = _run(sb, tmp, "--java-tests", expect_rc=0)
        assert "▶ 跑：必然项①" in out, out
        assert "显式 --java-tests" in out, out
        assert "mvnw-probe" in _log(tmp), _log(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# 2 · 自动探测：出现 `.github/cases/**` 或 `claims/**` ⇒ 自动带上 `--new-cases`
# ══════════════════════════════════════════════════════════════════════════════

class TestCaseTrigger:
    CASE_REL = ".github/cases/probe.yml"
    CLAIM_REL = ".github/cases/claims/9999-PK-999.json"

    @pytest.mark.parametrize("rel,text", [
        (CASE_REL, "schema: \"case-contract/1.0\"\ndomain: probe\ncases: []\n"),
        (CLAIM_REL, '{"id": "PK-999", "pr": 9999, "title": "probe", "claimed_at": "2026-10-03"}\n'),
    ])
    def test_case_or_claim_change_auto_enables_anchor_leg(self, probe, rel, text):
        sb, tmp = probe
        _write_and_commit(sb, rel, text)
        rc, out = _run(sb, tmp, expect_rc=0)
        assert "▶ 跑：必然项②" in out, out
        assert "自动探测命中 .github/cases/** 或 claims/**" in out, out
        assert "⏭️  未跑：必然项①" in out, out
        log = _log(tmp)
        assert "python-probe" in log and "test_case_machine_fail_channel.py" in log, log
        assert "mvnw-probe" not in log, log

    def test_explicit_switch_forces_the_anchor_leg(self, probe):
        sb, tmp = probe
        _idle_commit(sb)
        _, out = _run(sb, tmp, "--new-cases", expect_rc=0)
        assert "▶ 跑：必然项②" in out, out
        assert "显式 --new-cases" in out, out
        assert "test_case_machine_fail_channel.py" in _log(tmp), _log(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# 6 · fail-closed（基准取不到 / 变更集为空 / 腿真红 ⇒ 非零）
# ══════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    def test_missing_base_ref_is_not_a_pass(self, probe):
        sb, tmp = probe
        _idle_commit(sb)
        rc, out = _run(sb, tmp, "--base", "origin/does-not-exist", expect_rc=3)
        assert "无法判定" in out and "fail-closed" in out, out
        assert "该跑的腿全部通过" not in out, out

    def test_empty_change_set_is_not_a_pass(self, probe):
        """零 diff 的树 ⇒ 不跑任何腿 ⇒ 非零（禁空跑）。"""
        sb, tmp = probe
        rc, out = _run(sb, tmp, "--base", "HEAD", expect_rc=3)
        assert "变更集为空" in out, out
        assert "该跑的腿全部通过" not in out, out

    def test_red_leg_makes_the_entry_nonzero(self, probe):
        sb, tmp = probe
        _write_and_commit(sb, TestCaseTrigger.CASE_REL, "schema: \"case-contract/1.0\"\ncases: []\n")
        rc, out = _run(sb, tmp, PROBE_RC="1", expect_rc=1)
        assert "❌ 非零退出" in out, out

    def test_dry_run_never_executes_anything(self, probe):
        """`--dry-run` 只打印计划（且**不**拿「没执行」冒充通过）。"""
        sb, tmp = probe
        _write_and_commit(sb, TestJavaTrigger.JAVA_REL, "package p;\nclass T { }\n")
        rc, out = _run(sb, tmp, "--dry-run", expect_rc=0)
        assert "--dry-run：未执行" in out, out
        assert "没有执行任何腿" in out, out
        assert _log(tmp) == "", _log(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# 7 · 只读：整跑一遍不写任何文件（交付要求 1）
# ══════════════════════════════════════════════════════════════════════════════

def _tree_snapshot(root: Path) -> dict:
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            snap[str(p.relative_to(root))] = p.read_bytes()
    return snap


class TestReadOnly:
    def test_entry_writes_nothing(self, probe, monkeypatch):
        """整跑一遍（两条必然项**都**触发）⇒ 工作树里**一个文件都不许多 / 不许改**。

        runner 换成**替换式桩**（先记一行调用、再 `exec` 真命令 ⇒ 沙箱里每条腿都真跑起来），
        这样「快照前后相同」才有判别力：任何写盘 / 改文件都会被抓住。
        """
        sb, tmp = probe
        _write_and_commit(sb, TestJavaTrigger.JAVA_REL, "package p;\nclass T { }\n")
        _write_and_commit(sb, TestCaseTrigger.CASE_REL, "schema: \"case-contract/1.0\"\ncases: []\n")
        bindir = tmp / "real-bin"
        bindir.mkdir()
        for name, real in (("mvnw-probe", "bash"), ("python-probe", sys.executable)):
            sp = bindir / name
            sp.write_text('#!/usr/bin/env bash\necho "--- %s" >> "$PROBE_LOG"\nexec "%s" "$@"\n' % (name, real),
                          encoding="utf-8")
            sp.chmod(sp.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        before = _tree_snapshot(sb)
        _, out = _run(sb, tmp, expect_rc=None)
        after = _tree_snapshot(sb)
        assert "▶ 跑：必然项①" in out and "▶ 跑：必然项②" in out, out
        assert after == before, (
            "本入口必须**只读**：新增 "
            f"{sorted(set(after) - set(before))} / 修改 {sorted(k for k in before if k in after and before[k] != after[k])}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 8 · 判别力自证：把「自动探测」摘掉 ⇒ 判据 1/2 当场红（§28.1 出口①）
# ══════════════════════════════════════════════════════════════════════════════

class TestMutationProvesDiscrimination:
    """内存变异体：`AUTO_JAVA=1` / `AUTO_CASES=1` 永不置位 ⇒ 自动探测退化成「恒不带」。"""

    MUTATIONS = (
        ("AUTO_JAVA=1", "AUTO_JAVA=0", TestJavaTrigger.JAVA_REL,
         "package com.migao.admin.time;\nclass ProbeGuardTest { }\n", "▶ 跑：必然项①"),
        ("AUTO_CASES=1", "AUTO_CASES=0", TestCaseTrigger.CASE_REL,
         "schema: \"case-contract/1.0\"\ncases: []\n", "▶ 跑：必然项②"),
    )

    @pytest.mark.parametrize("old,new,rel,text,expect_line", MUTATIONS)
    def test_disabling_auto_detection_turns_the_judgement_red(self, tmp_path, old, new, rel, text,
                                                              expect_line):
        real = REAL_SCRIPT.read_text(encoding="utf-8")
        assert real.count(old) == 1, f"变异锚点 '{old}' 命中 {real.count(old)} 次（要求恰好 1 次）"
        sb = hs.build(tmp_path / "repo")
        (sb / "scripts" / "pkg-narrow-check.sh").write_text(real.replace(old, new), encoding="utf-8")
        os.chmod(sb / "scripts" / "pkg-narrow-check.sh", 0o755)
        (sb / "backend" / "admin-api").mkdir(parents=True, exist_ok=True)
        bindir = tmp_path / "probe-bin"
        bindir.mkdir()
        for name in ("mvnw-probe", "python-probe"):
            p = bindir / name
            p.write_text(RECORDER, encoding="utf-8")
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bindir}{os.pathsep}{old_path}"
        try:
            _write_and_commit(sb, rel, text)
            env = _probe_env(tmp_path, sb)
            proc = hs.run([str(sb / "scripts" / "pkg-narrow-check.sh")], sb, env, timeout=120)
            out = proc.stdout + proc.stderr
        finally:
            os.environ["PATH"] = old_path
        # 变异体在**同一夹具、同一注入**下不再带上那条腿 ⇒ 判据 1/2 的断言当场红
        assert expect_line not in out, f"变异注入没生效（仍打印了 {expect_line}）：\n{out}"


# ══════════════════════════════════════════════════════════════════════════════
# 静态契约：判据与脚本对得上（防「给不存在的对象盖章」）
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticContract:
    def test_script_is_executable_and_reads_base_from_cli(self):
        assert REAL_SCRIPT.is_file(), f"缺 {SCRIPT_REL}"
        assert os.access(REAL_SCRIPT, os.X_OK), f"{SCRIPT_REL} 不可执行"
        text = REAL_SCRIPT.read_text(encoding="utf-8")
        for need in ('--java-tests', '--new-cases', '--base', '--no-auto', '--dry-run',
                     'src/test/', 'BusinessClockTestSourceGuardTest',
                     'test_case_machine_fail_channel.py',
                     'case_trust_gate.py', 'generated_artifacts_freshness.py',
                     'test_realdb_failclosed.py'):
            assert need in text, f"{SCRIPT_REL} 里找不到 '{need}'"

    def test_entry_never_pulls_the_full_suite(self):
        """⑤ 静态面：本入口**不许**把全量档写进任何一条腿（动态读数在 `TestNoTrigger`）。

        ⚠️ **只扫非注释行** —— 脚本头部有历史说明（「此前只在 `verify-all.sh gate|full` 跑到」），
        那是**引用**不是**调用**；连注释一起扫 = 「解释禁忌反成犯禁忌」的假红
        （同 `migao-dev-flow` §2.2 的「引用即实例」家族）。
        """
        code = "\n".join(l for l in REAL_SCRIPT.read_text(encoding="utf-8").splitlines()
                          if not l.lstrip().startswith("#"))
        # 判**全量入口的调用形态**（脚本正文里允许出现「全量属于批次」这类指路文字 —— 那是文档，不是调用）
        for forbidden in ("./verify-all.sh", "verify-all.sh gate", "verify-all.sh quick",
                          "pytest tests/unit_ci_workflows -q", "./scripts/batch-gate.sh"):
            assert forbidden not in code, f"{SCRIPT_REL} 的非注释行里出现了全量档调用 '{forbidden}'"
