# case_ids: MC-012
"""`./verify-all.sh gate` 必须覆盖 **cases 受管面**（issue #4221）—— 本地预检 ↔ CI 门禁同源守卫。

## 缺陷（2026-09-18 实测，#4197 包，非推断）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 本地预检 | `./verify-all.sh gate` | ✅ **1 通过 / 0 失败** |
| CI 同规则门禁 | `python3 .github/case_trust_gate.py` | ❌ **exit 1**：`burn-down 预算未达标：本次净消减 0 条 < 每 PR 最低 1 条` |

根因：`gate` 档只跑 QA Growth Gate（`gate_check()`）⇒ 对被门禁管理的 **`.github/cases/**` 面是空的**，
而「空」在控制台上表现为 ✅ ⇒ 只碰了用例注释/`merge_log` 的 PR「本地绿、CI 红」，白跑一整轮 CI。
形态属 `migao-acceptance` 的「空跑/假绿」（没跑必须长得像没跑，`migao-dev-flow` §16.7）。

## 本守卫锁什么（零 LLM、零网络、不依赖真实 `origin/main`、不跑真实门禁）

1. **纯函数** `managed_case_paths()`：文件集合 → 命中的受管面（命中 / 不命中 / 混合 / 空输入 / 前缀边界）；
2. **同源判据（调用而非复制）**：命中时调用的三个脚本 + 参数 = CI `pr-check` 的 `case-truth-check`
   与 `case-trust-gate` job **同一批**（`case_trust_gate.py --base origin/main` / `truths.py check` /
   `render_cases.py`），并锁「CI 改了参数而本地没跟」的漂移；
3. **行为判据**：`cases_face_gate()` 把子门禁的**非零退出码传播出去**（stub `python3`，
   非真实门禁、零副作用）；命中时用 `::warning::` 声明**残余未覆盖**；
4. **反向红线**：不命中受管面时**一个门禁脚本都不调用**、且不红（否则会把不碰用例库的 PR
   卡在用例库上 —— 与 `burn_down.scope=case_touching_prs` 的既有取舍冲突，#4155）；
5. **派发点**：`gate` 档必须**命中才**把它作为独立检查项真跑；未命中时控制台显式声明「未跑」，
   **不许**出现 ✅（判据 2）。

⚠️ 本文件自身会被 CI 的 `--check-weak` 扫描（新增测试文件），故正文不得出现字面弱断言模式
（存在性断言 / 恒真断言 / 空 `pass`）。
"""
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "verify-all.sh"
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
_SCRIPT = SCRIPT.read_text(encoding="utf-8")

# CI `pr-check` 里三个 cases 面门禁的命令片段（**真值取自 workflow 文本**，见 TestCiParity）
CI_TRUST_CMD = "python3 .github/case_trust_gate.py --base origin/main"
CI_TRUTHS_CMD = "python3 .github/truths.py check --templates .github/templates --cases .github/cases"
CI_RENDER_CMD = "python3 .github/render_cases.py --cases .github/cases"
GENERATED = ("tests/agent_eval/eval_cases.py", "docs/testing/mibao-verification-cases.md")

_RUN_TIMEOUT = 120


def _extract(name: str) -> str:
    """从脚本里抽出 `name() { ... }` 的函数体（结束于第 0 列的 `}`）。"""
    m = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", _SCRIPT, re.M)
    assert m, f"未能从 verify-all.sh 抽出 {name}() —— 结构变了就同步更新本守卫"
    return m.group(0)


def _code_of(text: str) -> str:
    """剥掉注释后的**代码行**（注释里会引用这些命令，裸 grep 会假绿）。"""
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def _norm(text: str) -> str:
    """把多行命令折成单行（命令行续行 `\\` 换行后仍是同一条命令）。"""
    return re.sub(r"\s+", " ", text.replace("\\\n", " "))


def _run(code: str, *, env: dict = None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        ["bash", "-c", code], capture_output=True, text=True, env=e,
        cwd=str(REPO_ROOT), timeout=_RUN_TIMEOUT,
    )


def _filter_harness(paths) -> str:
    """只装 `managed_case_paths()` 的最小 harness（纯过滤器，无副作用）。"""
    body = "printf '%s\\n' " + " ".join(shlex.quote(p) for p in paths) if paths else "printf ''"
    return (
        "set -uo pipefail\n" + _extract("managed_case_paths") + "\n"
        + body + " | managed_case_paths\n"
    )


def _hit_harness(change_set) -> str:
    """装 `managed_case_paths()` + `cases_face_hit()`，打印 HIT / NOHIT。"""
    assign = ("CHANGE_SET=" + shlex.quote(change_set) + "\n") if change_set is not None else ""
    return (
        "set -uo pipefail\n" + assign
        + _extract("managed_case_paths") + "\n" + _extract("cases_face_hit") + "\n"
        + 'if cases_face_hit; then echo HIT; else echo NOHIT; fi\n'
    )


def _stub_python(tmp_path: Path, rc: int):
    """伪 `python3`：记下每次调用、按指定退出码退出（**不跑真实门禁**）。

    返回 (bin_dir, log_path)。stub 让「命中时到底调用了哪些脚本」「退出码是否传播」
    都可判定，且不依赖仓库真实门禁、零网络、零 LLM。
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "stub-calls.log"
    stub = bin_dir / "python3"
    stub.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$STUB_LOG"\nexit "${STUB_RC:-0}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir, log


def _stub_env(bin_dir: Path, log: Path, rc: int) -> dict:
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_LOG": str(log), "STUB_RC": str(rc)}


def _gate_harness(change_set: str) -> str:
    """装 `cases_face_gate()` 及其依赖，并执行它（cwd = 仓库根，相对路径可解析）。"""
    return (
        "set -uo pipefail\n"
        + "CHANGE_SET=" + shlex.quote(change_set) + "\n"
        + _extract("managed_case_paths") + "\n"
        + _extract("cases_face_hit") + "\n"
        + _extract("cases_face_gate") + "\n"
        + "cases_face_gate\n"
    )


def _mode_branch(mode: str) -> str:
    """抽取顶层 `case "$MODE" in` 里 `mode)` 分支的代码（到 `;;` 为止，已剥注释）。"""
    lines = _code_of(_SCRIPT).splitlines()
    start = next((i for i, ln in enumerate(lines) if 'case "$MODE" in' in ln), -1)
    assert start >= 0, 'verify-all.sh 里找不到顶层 `case "$MODE" in`'
    for i in range(start, len(lines)):
        if lines[i].strip() == f"{mode})":
            body = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != ";;":
                body.append(lines[j])
                j += 1
            assert j < len(lines), f"`{mode})` 分支没有被 `;;` 结束"
            return "\n".join(body)
    raise AssertionError(f"verify-all.sh 顶层 case 里找不到 `{mode})` 分支")


def _dispatch_harness(change_set: str) -> str:
    """用**脚本里真实的 `gate` 档派发文本**跑一遍：只把 `report()`/`gate_check()` 换成最小替身。

    这样「命中才派发」「未命中显式声明未跑」「命中失败 ⇒ 记 ❌」都是**行为**判定，
    不是文本 grep；且 stub `python3` 保证零真实门禁、零网络。
    """
    return (
        "set -uo pipefail\n"
        + "CHANGE_SET=" + shlex.quote(change_set) + "\n"
        + "PASS=0; FAIL=0; declare -a FAILED; declare -a NOT_READY; READY=0\n"
        + "gate_check() { return 0; }\n"
        + 'report() { local n="$1"; shift; if "$@"; then echo "PASS $n"; else echo "FAIL $n"; fi; }\n'
        + _extract("managed_case_paths") + "\n"
        + _extract("cases_face_hit") + "\n"
        + _extract("cases_face_gate") + "\n"
        + _mode_branch("gate") + "\n"
    )


# ── ① 纯函数：文件集合 → 是否命中受管面 ──────────────────────────────────────

class TestManagedCasePaths:
    """`managed_case_paths()` = 受管面命中判定的**单一实现**（issue #4221 判据 1）。"""

    def test_is_a_single_definition(self):
        """命中判定只许有一份实现（散落两份必然漂移 —— 同 `probe_ready` 的既有口径）。"""
        found = re.findall(r"^managed_case_paths\(\) \{", _SCRIPT, re.M)
        assert len(found) == 1, f"managed_case_paths() 必须恰好定义一次，实得 {len(found)} 次"

    @pytest.mark.parametrize(
        "path",
        [
            ".github/cases/hr.yml",
            ".github/cases/product.yml",
            ".github/cases/",
            ".github/case-trust-baseline.json",
            ".github/case-trust-unimplemented.json",
            "tests/agent_eval/eval_cases.py",
            "docs/testing/mibao-verification-cases.md",
        ],
    )
    def test_managed_face_paths_hit(self, path):
        """受管面路径必须命中（用例库 / 债务账本 / 两条生成物）。"""
        r = _run(_filter_harness([path]))
        assert r.returncode == 0, f"纯过滤器不得失败：{r.stderr}"
        assert r.stdout.strip() == path, f"{path} 应命中受管面，实得输出 {r.stdout!r}"

    @pytest.mark.parametrize(
        "path",
        [
            "verify-all.sh",
            "tests/unit_ci_workflows/test_verify_all_gate_parity.py",
            ".github/growth_gate.py",
            ".github/cases-other/hr.yml",
            ".github/case-trust-baseline.json.bak",
            "docs/testing/mibao-verification-cases.md.orig",
            "backend/admin-api/src/main/java/com/migao/Demo.java",
        ],
    )
    def test_non_managed_paths_do_not_hit(self, path):
        """**反向红线**：不碰受管面的路径一律不命中（否则全仓 PR 会被用例库卡住）。"""
        r = _run(_filter_harness([path]))
        assert r.returncode == 0, f"纯过滤器不得失败：{r.stderr}"
        assert r.stdout.strip() == "", f"{path} 不应命中受管面，实得输出 {r.stdout!r}"

    def test_mixed_set_keeps_only_managed_paths(self):
        """混合变更集只回吐命中的那几条（不吞不扩）。"""
        r = _run(_filter_harness(["verify-all.sh", ".github/cases/hr.yml", "README.md"]))
        assert r.stdout.split() == [".github/cases/hr.yml"], r.stdout

    def test_empty_input_hits_nothing_and_does_not_fail(self):
        """空变更集 ⇒ 不命中且退出 0（`set -u`/`pipefail` 下不得崩，否则空跑会变假红）。"""
        r = _run(_filter_harness([]))
        assert r.returncode == 0, f"空输入不得失败：rc={r.returncode} {r.stderr}"
        assert r.stdout.strip() == "", f"空输入不得命中：{r.stdout!r}"


class TestCaseFaceHit:
    """`cases_face_hit()` = 对**变更集**的判定（闸门本体只认它，别处不许再写一套）。"""

    def test_hits_when_change_set_touches_case_library(self):
        r = _run(_hit_harness("verify-all.sh\n.github/cases/hr.yml\n"))
        assert r.stdout.strip() == "HIT", r.stdout

    def test_does_not_hit_on_unrelated_change_set(self):
        r = _run(_hit_harness("verify-all.sh\ntests/unit_ci_workflows/test_x.py\n"))
        assert r.stdout.strip() == "NOHIT", r.stdout

    def test_does_not_hit_on_empty_change_set(self):
        r = _run(_hit_harness(""))
        assert r.stdout.strip() == "NOHIT", r.stdout

    def test_survives_unset_change_set(self):
        """`set -u` 下 `CHANGE_SET` 未定义必须判「不命中」而不是崩（崩了会把别人打红）。"""
        r = _run(_hit_harness(None))
        assert r.returncode == 0, f"CHANGE_SET 未定义时不得崩溃：rc={r.returncode} {r.stderr}"
        assert r.stdout.strip() == "NOHIT", r.stdout


# ── ② 同源判据：调用的脚本/参数与 CI pr-check 一致（不复制规则）──────────────

class TestCiParity:
    """本地判定必须与 CI 同名 job **同脚本同参数** —— 判据从 CI 文本取，防两边漂移。"""

    @staticmethod
    def _ci_text() -> str:
        return _norm(_code_of(PR_CHECK.read_text(encoding="utf-8")))

    @staticmethod
    def _local_text() -> str:
        return _norm(_code_of(_extract("cases_face_gate")))

    @pytest.mark.parametrize("cmd", [CI_TRUST_CMD, CI_TRUTHS_CMD, CI_RENDER_CMD])
    def test_ci_still_runs_this_command(self, cmd):
        """前提断言：CI 侧确实跑这一条（否则本守卫锁的是一条不存在的同源判据）。"""
        assert cmd in self._ci_text(), (
            f"CI pr-check 里找不到 `{cmd}` —— 门禁命令漂移了，请同步本守卫与本函数"
        )

    @pytest.mark.parametrize("cmd", [CI_TRUST_CMD, CI_TRUTHS_CMD, CI_RENDER_CMD])
    def test_local_runs_the_same_command(self, cmd):
        """本地命中受管面时必须跑**同一条**命令（调用而非复制规则）。"""
        assert cmd in self._local_text(), (
            f"cases_face_gate() 没有调用 `{cmd}` —— 本地与 CI 不同源（issue #4221 判据 3）"
        )

    @pytest.mark.parametrize("artifact", GENERATED)
    def test_freshness_check_covers_the_same_generated_artifacts(self, artifact):
        """生成物新鲜度校验的被测对象必须与 CI 一致（改了用例忘重渲染 = 分叉）。"""
        assert artifact in self._local_text(), f"本地新鲜度校验没覆盖 {artifact}"
        assert artifact in self._ci_text(), f"CI 新鲜度校验没覆盖 {artifact}（漂移了？）"

    def test_exit_code_is_propagated_to_the_caller(self):
        """子门禁非零 ⇒ 本函数非零（**退出码同源**：#4221 判据 3，不许吞码）。"""
        text = _code_of(_extract("cases_face_gate"))
        assert re.search(r"\|\|\s*rc=1", text), (
            "cases_face_gate() 没有把子门禁的非零退出码收敛到返回值（吞码 = 假绿）"
        )
        assert re.search(r"^\s*return\s+\"?\$?\{?rc", text, re.M), (
            "cases_face_gate() 没有 return rc —— 退出码传播链缺一环"
        )


# ── ③ 行为：命中才调用 + 非零退出码传播 + 残余未覆盖声明（stub python3）──────

class TestCaseFaceGateBehaviour:
    """命中 ⇒ 真调三个门禁 + 非零码传播 + 声明残余未覆盖。"""

    def test_hit_invokes_the_three_gates_and_propagates_nonzero(self, tmp_path):
        bin_dir, log = _stub_python(tmp_path, rc=1)
        r = _run(_gate_harness(".github/cases/hr.yml\n"), env=_stub_env(bin_dir, log, 1))
        assert r.returncode != 0, (
            f"子门禁非零时 cases_face_gate() 必须非零（本地绿 CI 红就是这个缺陷）：\n{r.stdout}"
        )
        calls = log.read_text(encoding="utf-8") if log.exists() else ""
        for needle in ("case_trust_gate.py", "truths.py", "render_cases.py"):
            assert needle in calls, f"命中受管面却没调用 {needle}：{calls!r}"

    def test_hit_declares_residual_non_coverage(self, tmp_path):
        """命中时也必须显式声明**残余未覆盖**（CI 仍有本地跑不了的 job，issue #4221 判据 2）。"""
        bin_dir, log = _stub_python(tmp_path, rc=0)
        r = _run(_gate_harness(".github/cases/hr.yml\n"), env=_stub_env(bin_dir, log, 0))
        assert "::warning::" in r.stdout, (
            f"命中受管面时必须用 ::warning:: 声明未覆盖范围（report() 才会抬到控制台）：{r.stdout!r}"
        )
        assert "未覆盖" in r.stdout, f"告警必须点名未覆盖了什么：{r.stdout!r}"


# ── ④ 派发点：gate 档命中才真跑；未命中显式声明未跑（真跑派发文本）───────────

class TestGateModeDispatch:
    """`gate` 档必须把 cases 面门禁接进来（issue #4221 修法 1），且只在命中时跑。"""

    def test_gate_mode_dispatches_on_hit(self):
        branch = _mode_branch("gate")
        assert "cases_face_hit" in branch, (
            "gate 档没有按「命中受管面」判定就派发 cases 面门禁 —— 会卡住不碰用例库的 PR"
        )
        assert re.search(r'^\s*report\s+"[^"]*cases 面门禁', branch, re.M), (
            "gate 档命中时没有把 cases 面门禁作为**独立检查项**真跑（report 调用缺失）"
        )

    def test_not_hit_prints_explicit_not_run_without_pass_mark(self):
        """未命中 ⇒ 控制台显式声明「未跑」，且**不得**出现 ✅（判据 2 / §16.7）。"""
        branch = _mode_branch("gate")
        assert "未跑" in branch, "gate 档未命中受管面时必须显式声明「未跑」（不许静默 ✅）"
        assert "✅" not in branch, (
            "未命中的声明里不得出现 ✅ —— 「没跑」与「通过」在控制台上必须可区分"
        )

    def test_dispatch_behaviour_on_unrelated_change_set(self, tmp_path):
        """**反向红线（行为版）**：不碰受管面 ⇒ 一个门禁脚本都不调用，且记 ✅ 前先声明未跑。"""
        bin_dir, log = _stub_python(tmp_path, rc=1)  # 一旦被调用就会非零 ⇒ 反向可判定
        r = _run(
            _dispatch_harness("verify-all.sh\nbackend/admin-api/src/main/java/Demo.java\n"),
            env=_stub_env(bin_dir, log, 1),
        )
        assert r.returncode == 0, f"派发文本不得自身失败：rc={r.returncode}\n{r.stdout}"
        assert not log.exists(), (
            "不命中受管面却调用了门禁脚本：" + (log.read_text(encoding="utf-8") if log.exists() else "")
        )
        assert "cases 面门禁" in r.stdout and "未跑" in r.stdout, (
            f"未命中时必须显式声明 cases 面门禁未跑：{r.stdout!r}"
        )
        assert "FAIL" not in r.stdout, f"不碰 cases 的 PR 不得因此变红：{r.stdout!r}"

    def test_dispatch_behaviour_on_hit_reports_failure(self, tmp_path):
        """命中 + 子门禁非零 ⇒ 该检查项必须记 ❌（本地不再对被管理面静默放行）。"""
        bin_dir, log = _stub_python(tmp_path, rc=1)
        r = _run(
            _dispatch_harness(".github/cases/hr.yml\n"), env=_stub_env(bin_dir, log, 1)
        )
        assert re.search(r"FAIL .*cases 面门禁", r.stdout), (
            f"命中受管面且子门禁非零时，该检查项必须判失败（本地绿 CI 红即此缺陷）：{r.stdout!r}"
        )

    def test_cases_face_gate_is_not_called_from_within_gate_check(self):
        """结构性：cases 面门禁**独立成项**，不塞进 `gate_check()`（否则它没有自己的日志/判定）。"""
        assert "cases_face_gate" not in _code_of(_extract("gate_check")), (
            "cases_face_gate 被塞进了 gate_check —— 应作为独立检查项，便于定位失败项"
        )
