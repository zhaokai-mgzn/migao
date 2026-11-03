# case_ids: MC-183
"""`verify-all.sh` 的**准入判据**：全部实跑腿被 skip 时不得判绿（issue #5707 · FM-E10 的残余收口）。

## 病（issue #5707 的 `FM-E10` 残余；本包修）

`./verify-all.sh redproof` 档（人工入口）里有两群腿：

| 群 | 派发 | 缺工具链时 | 证明什么 |
|---|---|---|---|
| **9 条实跑腿**（pool-board / order-urgency / cutting-plan / auto-batch / auto-batch-due-scan / saving-metrics-backend / saving-metrics-web / product-batch / agent-batch-tenant） | `report_env` | `⏭️ 未就绪`（**根本没跑**） | **本档目标的唯一证明** |
| **2 项无条件跑**：`红证机具前提自检（前提能否成立）` / `红证实跑巡检（登记册逐条：注入 → 必红 → 还原）` | `report` | 照旧 ✅（不依赖 JDK/npm/PG） | 前提面 / **另一套**登记册机制 —— 都不证明那 9 条跑过 |

旧汇总口径 `EXECUTED = PASS + FAIL` ⇒ 9 条全 ⏭️ 时那 2 项 ✅ 仍把 `EXECUTED` 顶到 `> 0`
⇒ **进不了「纯空跑 ⇒ `exit 4`」判定** ⇒ 该档**退出 0**。形态属 `migao-acceptance` 的「空跑」：
**没跑 = 通过**（`FM-E10` 记的就是这一类）。

## 修法（本文件锁的口径）

`EXECUTED` 照旧 = 全部真跑项；**新增** `AUX_EXECUTED`（**辅助真跑**：无条件跑、但不证明本档目标，
登记在 `verify-all.sh::aux_step_name`）⇒ `MEANINGFUL_EXECUTED = EXECUTED - AUX_EXECUTED`，
**`exit 4` 按后者判**。那 2 项**照旧真跑**（各有别的用途，**不许删**），只是跑绿不再被读成
「本档目标已验证」。登记方向 **fail-closed**：未登记的名字一律算实质真跑（新腿天然计数）。

## 判据（每条都会红；红证写在用例里，全部是内存变异 + 抽出来的真 shell 函数，零网络 / 零 JDK）

| # | 判据 | 红证（同一份代码的对照读数） |
|---|---|---|
| 1 | **全部实跑腿被 skip ⇒ `exit 4`** | 把准入判据改回 `EXECUTED` ⇒ 同夹具退 0（判据 5） |
| 2 | **负控：至少一条实跑腿真跑 ⇒ 不 `exit 4`**（不许退回「一律红」） | 把准入判据改成恒 `0`（辅助也算实质）⇒ 同夹具变 `exit 4` |
| 3 | **那 2 项无条件腿仍存在、仍会跑、且计入 `EXECUTED`** | 删掉任一派发行 ⇒ 类级核对点名「未登记 / 缺失」 |
| 4 | **归因具名**：`exit 4` 报文逐条列出被 skip 的腿 + **`probe_ready` 给出的那句**缺什么工具链 | 删掉 `NOT_READY_WHY` 拼装 ⇒ 具名行整段消失 |
| 5 | **红证注入**（判据 1 不是空断言） | 见判据 1 那一行（同一注入的反向读数） |
| 6 | **类级元守卫**：辅助登记 ⇄ `redproof` 档实际的无条件派发**双向相等**（未登记即红 / 陈旧即红）+ 上限**只许缩短** + 实跑腿不得被登记成辅助 + 准入判据必须引用 `MEANINGFUL_EXECUTED` 且 `exit 4` 只有一处 | 新增一条无条件 `report` 腿而不登记 ⇒ 红并具名；只改**注释** ⇒ **不红**（对照） |

## 边界（照实登记，别把本文件读成覆盖面更大）

- ❌ **不判「某条腿该不该需要那个工具链」**（环境 / 业务口径）：本判据只判「全 skip 时不得判绿」。
- ❌ **不判 9 条腿各自的注入式红证**（那是 `test_redproof_live_sweep.py` / `test_redproof_harness_gate.py` 的面）。
- ❌ **不跑真机具**（JDK / npm / PG 一个都不需要）：本文件只跑**抽出来的 shell 函数 + 汇总块**，
  腿的命令被替换成 `true`（判的是**计数与判定**，不是腿的内容）。
- ❌ **登记按名字判**：改腿名会让它从「辅助」掉回「实质」（方向 fail-closed —— 只会更严，不会因此判绿）。
- ❌ 辅助腿的**内部行为**（前提锚点、登记册巡检）不在本文件射程。
"""
from __future__ import annotations

import os
import re

from unit_ci_workflows.injection import inject
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "verify-all.sh"
_SCRIPT = SCRIPT.read_text(encoding="utf-8")

RC_OK = 0
RC_PURE_NOOP = 4
#: 辅助真跑登记的**冻结上限**（现取 = 2）：只许缩短。新增一条辅助 = 削弱准入，必须先证明
#: 「它确实不证明本档目标」，不是「顺手把它也排除掉好让灯变绿」。
AUX_FROZEN = 2
#: 纯空跑报文里那条「具名 + 缺什么工具链」的行首（断言与红证都按它取）。
DETAIL_PREFIX = "  · "


# ══════════════════════════════════════════════════════════════════════════════
# 从真脚本里抽件（**单一实现**：断言与 harness 都读这里，不另写第二份口径）
# ══════════════════════════════════════════════════════════════════════════════


def _extract(text: str, name: str) -> str:
    """从脚本里抽出 `name() { ... }` 的函数体（结束于第 0 列的 `}`）。"""
    m = re.search(rf"^{name}\(\) \{{[\s\S]*?^\}}", text, re.M)
    assert m, f"未能从 verify-all.sh 抽出 {name}() —— 结构变了就同步更新本守卫"
    return m.group(0)


def _cut_trailing_comment(ln: str) -> str:
    """剥**行尾注释**，引号感知（`"缺料 #3 已补"` 里的 `#` 不是注释起点）。

    口径见 issue #5325 类别 1：判据面按 `#` 截断前**必须先清空字符串**，
    否则字符串里的 `#` 会吃掉行尾 ⇒ 假绿。
    """
    out = []
    quote: str | None = None
    i = 0
    while i < len(ln):
        ch = ln[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(ln):
                out.append(ln[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            # 只有「行首或前面是空白」才算注释起点（`a#b` 不是 shell 注释）
            if not out or out[-1].isspace():
                break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _code_of(text: str) -> str:
    """剥掉**整行注释**与行尾注释 —— 注释里会写 `report "…"` 之类的字样，裸 grep 会假绿/假红。"""
    out = []
    for ln in text.splitlines():
        if ln.lstrip().startswith("#"):
            out.append("")
            continue
        out.append(_cut_trailing_comment(ln))
    return "\n".join(out)


def _mode_branch(text: str, mode: str) -> str:
    """抽出顶层 `case "$MODE" in` 里 `mode)` 分支的**代码**（到 `;;` 为止，已剥注释）。"""
    lines = _code_of(text).splitlines()
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
    raise AssertionError(f"`case \"$MODE\" in` 里找不到 `{mode})` 分支")


def _summary_tail(text: str = _SCRIPT) -> str:
    """抽出脚本末尾的**汇总块**（从「汇总」标记到 EOF）—— 它含 `exit`，可直接跑。"""
    m = re.search(r"^# ── 汇总.*$", text, re.M)
    assert m, "verify-all.sh 里找不到汇总块标记（`# ── 汇总`）"
    return text[m.start():]


def _fake_pass_signature(text: str = _SCRIPT) -> str:
    m = re.search(r'^FAKE_PASS_SIGNATURE="([^"]*)"', text, re.M)
    assert m, "verify-all.sh 里找不到 FAKE_PASS_SIGNATURE 声明"
    return m.group(1)


def aux_registry_names(text: str = _SCRIPT) -> list[str]:
    """`aux_step_name()` 里登记的**辅助真跑**名字（现取；登记 = 单一实现）。"""
    body = _extract(text, "aux_step_name")
    return re.findall(r'^\s*"([^"]+)"\)\s*return 0 ;;', body, re.M)


def redproof_unconditional_names(text: str = _SCRIPT) -> list[str]:
    """`redproof` 档里**无条件** `report` 派发的检查项名（4 空格缩进 = 档位分支顶层，不在 if 里）。"""
    return re.findall(r'^[ ]{4}report[ \t]+"([^"]+)"', _mode_branch(text, "redproof"), re.M)


def redproof_env_legs(text: str = _SCRIPT) -> list[tuple[str, str]]:
    """`redproof` 档里 `report_env` 派发的**实跑腿**：`(env_key, 检查项名)`（现取）。"""
    return re.findall(
        r'^[ ]{4}report_env[ \t]+(\S+)[ \t]+"([^"]+)"', _mode_branch(text, "redproof"), re.M)


# ══════════════════════════════════════════════════════════════════════════════
# harness：把真函数 + 真汇总块装进最小 shell（零网络 / 零 JDK）
# ══════════════════════════════════════════════════════════════════════════════


def _harness(
    root: Path,
    *,
    text: str = _SCRIPT,
    summary: str | None = None,
    legs: list[tuple[str, str]] | None = None,
    aux_names: list[str] | None = None,
) -> str:
    """装 `probe_ready` + `aux_step_name` + `report` + `report_env` + 汇总块，真跑一遍。

    · `legs`：实跑腿（默认 = 真脚本里现取的那几条）；每条的**命令替换成 `true`** ——
      本判据判的是**计数与判定**，不是腿的内容（且一条也不许真跑机具）。
    · `aux_names`：无条件项（默认 = 真脚本里现取的那几条），同样以 `true` 派发。
    · `summary`：可注入改过的汇总块（红证用），默认 = 真脚本里抽出的那一份。
    """
    legs = redproof_env_legs(text) if legs is None else legs
    aux_names = redproof_unconditional_names(text) if aux_names is None else aux_names
    calls = "".join(
        f"report_env {shlex.quote(key)} {shlex.quote(name)} true\n" for key, name in legs)
    calls += "".join(f"report {shlex.quote(name)} true\n" for name in aux_names)
    return (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        f"FAKE_PASS_SIGNATURE={shlex.quote(_fake_pass_signature(text))}\n"
        "PASS=0; FAIL=0; READY=0; AUX_EXECUTED=0; declare -a FAILED; declare -a NOT_READY; NOT_READY_WHY=\"\"\n"
        + _extract(text, "probe_ready") + "\n"
        + _extract(text, "aux_step_name") + "\n"
        + _extract(text, "report") + "\n"
        + _extract(text, "report_env") + "\n"
        + calls
        # ⚠️ 清理必须**限定在本 harness 自己的作用域**（issue #4158）：全局通配 `rm -f /tmp/verify-all-*`
        #    会在 ~40 个 sibling worktree 并行跑测试时删掉**别的进程**正在用的日志 ⇒ 判据自己制造假红。
        + "rm -f /tmp/verify-all-$$-*.log\n"
        + (summary if summary is not None else _summary_tail(text))
    )


def _run_sh(code: str):
    env = dict(os.environ)
    # 本判据要的是「裸 root ⇒ 一律未就绪」，JAVA_HOME 之类不参与该结论（mvnw 缺失先短路）。
    return subprocess.run(["bash", "-c", code], capture_output=True, text=True, env=env, timeout=120)


def _fake_vitest(root: Path) -> None:
    """只造 `admin-web-vitest` 这一条腿的就绪条件（负控用；照脚本探测的**可执行文件**伪造）。"""
    f = root / "frontend" / "admin-web" / "node_modules" / ".bin" / "vitest"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    f.chmod(0o755)


def _probe_missing(root: Path, key: str, text: str = _SCRIPT) -> str:
    """在同一个 ROOT 上单独跑 `probe_ready <key>`，取它给出的「缺什么」原文（归因断言的**真值源**）。"""
    code = (
        "set -uo pipefail\n"
        f"ROOT={shlex.quote(str(root))}\n"
        + _extract(text, "probe_ready") + "\n"
        + f"probe_ready {shlex.quote(key)}; rc=$?\n"
        + 'printf "RC=%s\\nMISSING=%s\\n" "$rc" "$READY_MISSING"\n'
    )
    r = _run_sh(code)
    assert "RC=1" in r.stdout, (
        f"本判据要求**裸 root** 下 {key} 一律未就绪（否则夹具失效）：\n{r.stdout}\n{r.stderr}")
    return r.stdout.split("MISSING=", 1)[1].strip()


def _detail_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith(DETAIL_PREFIX)]


# ══════════════════════════════════════════════════════════════════════════════
# 类级元守卫（纯静态；判红具名）
# ══════════════════════════════════════════════════════════════════════════════


def class_problems(text: str) -> list[str]:
    """MC-183 的类级面：让「辅助项把纯空跑顶成绿」这一类**进不来**。"""
    problems: list[str] = []
    aux = aux_registry_names(text)
    unconditional = redproof_unconditional_names(text)
    legs = redproof_env_legs(text)

    if len(aux) > AUX_FROZEN:
        problems.append(
            f"辅助真跑登记 {len(aux)} 条 > 冻结上限 {AUX_FROZEN}（只许缩短）—— "
            f"新增一条辅助就等于把一条腿从准入里摘掉，必须先证明它**确实不证明本档目标**：{aux}")

    unregistered = sorted(set(unconditional) - set(aux))
    if unregistered:
        problems.append(
            "redproof 档里有**未登记的无条件项** ⇒ 它们会被算成实质真跑、把「全部实跑腿 skip」"
            f"顶成绿（本单的缺陷形态）：{unregistered}")

    stale = sorted(set(aux) - set(unconditional))
    if stale:
        problems.append(
            f"辅助登记里有**陈旧项**（redproof 档已无该名字的无条件派发）：{stale} —— "
            "要么把派发接回去，要么把它从 aux_step_name() 摘掉（登记必须活着）")

    if len(legs) < 2:
        problems.append(
            f"redproof 档的实跑腿现取只有 {len(legs)} 条 —— 抽出失效或腿被删（本判据 fail-closed）")

    for _key, name in legs:
        if name in aux:
            problems.append(
                f"实跑腿 {name!r} 被登记成**辅助真跑** ⇒ 「全部实跑腿 skip」将永远进不了纯空跑判定"
                "（把实质腿摘出准入 = 本单的缺陷形态本身）")

    summary = _summary_tail(text)
    if 'if [ "$MEANINGFUL_EXECUTED" -eq 0 ]; then' not in summary:
        problems.append(
            "汇总块的纯空跑判定没有按 `MEANINGFUL_EXECUTED` 判 —— 回退到 `EXECUTED`（= PASS + FAIL）"
            "就是本单要修的缺陷（辅助项会把纯空跑顶成绿）")
    if len(re.findall(r"^\s*exit 4$", summary, re.M)) != 1:
        problems.append("汇总块里 `exit 4` 不唯一 —— 纯空跑判定必须只有一处出口（否则归因读不准）")
    if "MEANINGFUL_EXECUTED=$((EXECUTED - AUX_EXECUTED))" not in summary:
        problems.append(
            "汇总块没有按 `MEANINGFUL_EXECUTED = EXECUTED - AUX_EXECUTED` 计算准入计数 —— "
            "这是「辅助真跑不计数」的**唯一**实现处")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1~5：行为面（真 shell 函数 + 真汇总块）
# ══════════════════════════════════════════════════════════════════════════════


class TestPureNoopOnAllRealRunLegsSkipped:
    """判据 1 / 3 / 4：全部实跑腿 ⏭️ ⇒ `exit 4`；辅助腿照旧跑；归因具名。"""

    def test_all_real_run_legs_skipped_exits_pure_noop(self, tmp_path):
        """**判据 1**：9 条实跑腿全 ⏭️（裸 root）+ 2 项辅助 ✅ ⇒ 必须 `exit 4`（修前退 0）。"""
        root = tmp_path / "root"
        root.mkdir()
        r = _run_sh(_harness(root))
        assert redproof_env_legs(), "redproof 档抽不出实跑腿 —— 夹具前提不成立"
        assert r.returncode == RC_PURE_NOOP, (
            f"全部实跑腿被 skip 却退出 {r.returncode}（修前形态 = 0）：\n{r.stdout}\n{r.stderr}")
        assert "无有效检查（纯空跑）" in r.stdout, r.stdout
        assert "全是辅助项" in r.stdout, f"没有把「真跑项全是辅助」说出来：\n{r.stdout}"

    def test_the_two_unconditional_legs_still_run_and_are_counted(self, tmp_path):
        """**判据 3**：那 2 项无条件腿**仍然存在且仍会跑**（不许为修空跑把它们删掉）。"""
        root = tmp_path / "root"
        root.mkdir()
        aux = redproof_unconditional_names()
        assert len(aux) == AUX_FROZEN, f"redproof 档的无条件项现取 {aux}（期望 {AUX_FROZEN} 条）"
        r = _run_sh(_harness(root))
        for name in aux:
            assert f"✅ {name}" in r.stdout, f"无条件腿没有真跑（或没被计成 ✅）：{name}\n{r.stdout}"
        assert f"辅助项 {len(aux)} 项" in r.stdout, (
            f"报文没说清「真跑的这些是辅助项」：\n{r.stdout}")

    def test_every_skipped_leg_is_named_with_the_toolchain_probe_reason(self, tmp_path):
        """**判据 4**：`exit 4` 报文逐条具名 + **就绪探测自己给出的**那句缺什么（不另写一套文案）。"""
        root = tmp_path / "root"
        root.mkdir()
        legs = redproof_env_legs()
        r = _run_sh(_harness(root))
        details = _detail_lines(r.stdout)
        assert len(details) == len(legs), (
            f"具名行 {len(details)} 条 ≠ 被 skip 的腿 {len(legs)} 条：\n{r.stdout}")
        assert "被跳过的腿（具名 · 缺什么工具链" in r.stdout, r.stdout
        for key, name in legs:
            expected = f"{DETAIL_PREFIX}{name} —— {_probe_missing(root, key)}"
            assert expected in r.stdout, (
                f"{name} 的归因与 probe_ready 的读数不一致（或根本没写）：\n期望: {expected}\n{r.stdout}")


class TestNegativeControl:
    """判据 2：至少一条实跑腿真跑 ⇒ **不** `exit 4`（不许退回「一律红」）。"""

    def test_one_ready_leg_keeps_the_tier_out_of_pure_noop(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _fake_vitest(root)          # 只让 admin-web-vitest 那一条腿就绪
        r = _run_sh(_harness(root))
        assert r.returncode == RC_OK, (
            f"有一条实跑腿真跑（其余 skip）却判了纯空跑：\n{r.stdout}\n{r.stderr}")
        assert "无有效检查（纯空跑）" not in r.stdout, r.stdout
        assert "实质真跑 1 项" in r.stdout, (
            f"实质真跑计数不等于 1（辅助项被算进去了？）：\n{r.stdout}")
        assert "✅" in r.stdout, r.stdout


class TestRedProofs:
    """判据 5 与各判据的红证（全部是**内存变异**：同一夹具、单变量对照）。"""

    @staticmethod
    def _noop_injection() -> tuple[str, str]:
        summary = _summary_tail()
        needle = "MEANINGFUL_EXECUTED=$((EXECUTED - AUX_EXECUTED))"
        assert needle in summary, (
            "汇总块的准入判据形态变了（红证锚点失配）—— 同步本守卫：期望一行 "
            f"`{needle}`")
        return summary, inject(summary, needle, "MEANINGFUL_EXECUTED=$EXECUTED", where="_noop_injection")

    def test_reverting_the_verdict_to_executed_turns_criterion_1_green(self, tmp_path):
        """**判据 5（红证）**：把准入判据改回 `EXECUTED` ⇒ 判据 1 的同夹具**变绿** ⇒ 它不是空断言。"""
        real_summary, mutated = self._noop_injection()
        assert mutated != real_summary, "注入没生效（锚点失配）—— 红证不成立"
        root = tmp_path / "root"
        root.mkdir()
        real = _run_sh(_harness(root, summary=real_summary))
        injected = _run_sh(_harness(root, summary=mutated))
        assert real.returncode == RC_PURE_NOOP, real.stdout
        assert injected.returncode == RC_OK, (
            f"把准入判据改回 EXECUTED 之后仍判纯空跑 ⇒ 判据 1 没在测 MEANINGFUL（空断言）：\n"
            f"{injected.stdout}\n{injected.stderr}")
        assert "无有效检查（纯空跑）" not in injected.stdout, injected.stdout

    def test_counting_auxiliary_as_meaningful_would_break_the_negative_control(self, tmp_path):
        """**判据 2 的红证**：把准入判据改成恒 `0`（= 辅助也算实质）⇒ 负控的同夹具**变红**。"""
        real_summary, _ = self._noop_injection()
        mutated = inject(
            real_summary,
            "MEANINGFUL_EXECUTED=$((EXECUTED - AUX_EXECUTED))",
            "MEANINGFUL_EXECUTED=0",
            where="test_counting_auxiliary_as_meaningful_would_break_the_negative_control")
        assert mutated != real_summary, "注入没生效（锚点失配）"
        root = tmp_path / "root"
        root.mkdir()
        _fake_vitest(root)
        real = _run_sh(_harness(root, summary=real_summary))
        injected = _run_sh(_harness(root, summary=mutated))
        assert real.returncode == RC_OK, real.stdout
        assert injected.returncode == RC_PURE_NOOP, (
            f"把辅助也算进准入后负控没有变红 ⇒ 判据 2 是空断言：\n{injected.stdout}")

    def test_dropping_the_attribution_removes_the_named_lines(self, tmp_path):
        """**判据 4 的红证**：删掉 `report_env()` 里的具名归因拼装 ⇒ 具名行整段消失。"""
        needle = (
            '    NOT_READY_WHY="${NOT_READY_WHY:-}  · ${name} —— ${READY_MISSING}\n"\n')
        assert needle in _SCRIPT, (
            "`report_env()` 的具名归因拼装形态变了（红证锚点失配）—— 同步本守卫")
        mutated = inject(_SCRIPT, needle, "", where="test_dropping_the_attribution_removes_the_named_lines")
        assert mutated != _SCRIPT, "注入没生效"
        root = tmp_path / "root"
        root.mkdir()
        injected = _run_sh(_harness(root, text=mutated))
        assert injected.returncode == RC_PURE_NOOP, injected.stdout
        assert _detail_lines(injected.stdout) == [], (
            f"删掉归因拼装后仍有具名行 ⇒ 判据 4 不是靠它成立的：\n{injected.stdout}")
        assert "被跳过的腿（具名 · 缺什么工具链" not in injected.stdout, injected.stdout


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：类级元守卫
# ══════════════════════════════════════════════════════════════════════════════


class TestClassLevelRegistry:
    def test_real_script_passes_the_class_judgment(self):
        assert class_problems(_SCRIPT) == [], "verify-all.sh 的准入/登记不自洽：" + repr(
            class_problems(_SCRIPT))

    def test_unregistered_unconditional_leg_is_named_red(self):
        """**未登记即红**：新增一条无条件 `report` 腿而不登记 ⇒ 具名报出（它会顶掉纯空跑判定）。"""
        # ⚠️ 锚点**必须带行首换行**：gate 档里同一条派发缩进 6 空格（在 `if` 里），
        #    裸 4 空格锚点会先命中它（`str.replace` 是子串匹配）⇒ 注入落到别的档、红证变空断言。
        anchor = f'\n    report "{redproof_unconditional_names()[0]}" redproof_preflight\n'
        assert anchor in _SCRIPT, "锚点失配（前提自检的派发行形态变了）—— 同步本守卫"
        new_leg = "红证机具新加的无条件腿"
        mutated = inject(_SCRIPT, anchor, anchor + f'    report "{new_leg}" true\n', where="test_unregistered_unconditional_leg_is_named_red")
        assert mutated != _SCRIPT, "注入没生效"
        problems = class_problems(mutated)
        assert any(new_leg in p for p in problems), (
            f"未登记的无条件腿没有被具名判红：{problems}")

    def test_stale_registration_is_named_red(self):
        """**陈旧即红**：登记了但 redproof 档已无该派发 ⇒ 具名报出（登记必须活着）。"""
        anchor = '\n    "红证机具前提自检（前提能否成立）") return 0 ;;\n'
        assert anchor in _SCRIPT, "锚点失配（aux_step_name 的登记形态变了）"
        stale = "红证机具早已删掉的腿"
        mutated = inject(
            _SCRIPT, anchor, anchor + f'    "{stale}") return 0 ;;\n',
            where="test_stale_registration_is_named_red")
        assert mutated != _SCRIPT, "注入没生效"
        problems = class_problems(mutated)
        assert any(stale in p for p in problems), f"陈旧登记没有被具名判红：{problems}"

    def test_wrapping_an_unconditional_leg_in_if_is_red(self):
        """那 2 项必须**无条件**派发：缩进到 `if` 里（变成条件派发）⇒ 判红。"""
        anchor = f'\n    report "{redproof_unconditional_names()[0]}" redproof_preflight\n'
        assert anchor in _SCRIPT
        mutated = inject(
            _SCRIPT, anchor,
            f'\n      report "{redproof_unconditional_names()[0]}" redproof_preflight\n',
            where="test_wrapping_an_unconditional_leg_in_if_is_red")
        assert mutated != _SCRIPT, "注入没生效"
        problems = class_problems(mutated)
        assert any("陈旧项" in p for p in problems), (
            f"条件化后的派发没有被判成「登记陈旧」并具名：{problems}")

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**：只改注释 ⇒ 一条都不报（守卫不该被自己的说明文字喂红）。"""
        anchor = "# ── 汇总（把「真跑了几项」摆到台面上）"
        assert anchor in _SCRIPT
        mutated = inject(
            _SCRIPT, anchor, "# ── 汇总（本判据只看代码行：改这里的注释不该变红）",
            where="test_comment_only_change_does_not_turn_red")
        assert mutated != _SCRIPT, "注入没生效"
        assert class_problems(mutated) == [], (
            "只改注释就判红 ⇒ 守卫在用散文判定：" + repr(class_problems(mutated)))
