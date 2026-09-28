# case_ids: MC-031
r"""**ci-helper 腿**的常驻判据（issue #5770）：本地必须有一条与 CI 同名同命令的腿。

## 治的形态（本会话实测，代价可量化）

CI 的 job `ci workflow helper unit tests`（`.github/workflows/pr-check.yml`）跑的是
`tests/unit_ci_workflows/**` 一整套判据；而本地 `./verify-all.sh gate` **一条都不跑**
（只在控制台打一行「残余未覆盖…」）。⇒ 任何改 `.github/**` 的包，**只能等 CI 才知道红**，
而那次的三条红（未登记进 `declaration_gate_registry` / 撞「CI 腿 ⇄ 本地腿」同源契约 /
注释里写的弱断言字面量被当实例）**全部可以在本地复现** —— 代价是 3 轮 × ≈16.5 分钟 CI。

## 判据（四条，都能**单独变红**）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | `verify-all.sh` 的 `ci_helper_leg()` 里那条 pytest 命令的 **argv** 与 CI 的**逐字相同**（解释器名 `python` / `python3` 不参与比较） | 两边任一改参数（`-q` / `--tb=short` / `-p no:cacheprovider` / 目标目录）⇒ 红 |
| 2 | 触发面 `ci_helper_face_paths()` 必须覆盖 `.github/` 与 `tests/unit_ci_workflows/` | 删掉任一条 ⇒ 「改了门禁面却又不跑」的形态回来 ⇒ 红 |
| 3 | `gate` 档里必须**命中才派发**、**未命中显式声明「未跑」** | 把派发写成无条件（每个 PR 多等 ≈16 分钟）或删掉 else 声明（静默 ✅）⇒ 红 |
| 4 | 三条的红证都**用内存构造**（不靠改真文件） | 判据写死成「读真文件就绿」⇒ 红证跑不出来 |

## 边界（照实登记）

- 本判据**不保证**那条腿真的跑得起来（本机没装 pytest ⇒ 腿自己记 ❌，那是腿的事）；
- 也**不覆盖** CI 侧本地跑不了的格子（网络 / PG 二进制 / 服务侧检查）；
- 「≈16 分钟」是**实测时长**，刻意**不写进任何断言**（降成本的固化禁挂钟，见 §23 G6）。
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
VERIFY_REL = "verify-all.sh"
CI_REL = ".github/workflows/pr-check.yml"

#: CI 侧那条 job 的名字（现取用来定位它的 `run:`）
CI_JOB_NAME = "ci workflow helper unit tests"
#: pytest 目标（argv 的一部分，逐字比）
PYTEST_TARGET = "tests/unit_ci_workflows"
#: 触发面必须覆盖的两段（本 job 判的对象）
REQUIRED_FACE_FRAGMENTS = (".github/", "tests/unit_ci_workflows/")


def _extract_function(text: str, name: str) -> str:
    """抽 `name() { … }` 的函数体（到第 0 列的 `}` 为止）；抽不到 ⇒ 空串（调用方判红）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{[\s\S]*?^\}}", text, re.M)
    return m.group(0) if m else ""


def _ci_pytest_argv(ci_text: str) -> str:
    """现取 CI 那条 job 里的 pytest 命令行（只取 argv，去掉解释器名）。

    取法：先定位 job 名，再在该 job 段落里找 `… -m pytest <target> …` 那一行。
    """
    idx = ci_text.find(CI_JOB_NAME)
    if idx < 0:
        return ""
    segment = ci_text[idx:]
    m = re.search(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", segment)
    return m.group(0).strip() if m else ""


def _local_pytest_argv(verify_text: str) -> str:
    """现取本地腿里的 pytest 命令行（同样只取 argv）。"""
    body = _extract_function(verify_text, "ci_helper_leg")
    m = re.search(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body)
    return m.group(0).strip() if m else ""


def _gate_branch(verify_text: str) -> str:
    """`case "$MODE" in` 里 `gate)` 分支的原文（到 `;;` 为止）。"""
    start = verify_text.find('case "$MODE" in')
    if start < 0:
        return ""
    rest = verify_text[start:]
    m = re.search(r"^\s*gate\)\s*$([\s\S]*?)^\s*;;", rest, re.M)
    return m.group(1) if m else ""


def leg_problems(verify_text: str, ci_text: str) -> list[str]:
    """四条判据的**纯函数**实现（红证可在内存里构造，不必改真文件）。"""
    bad: list[str] = []

    # 判据 1：argv 逐字相同
    ci_argv = _ci_pytest_argv(ci_text)
    local_argv = _local_pytest_argv(verify_text)
    if not ci_argv:
        bad.append(f"CI 侧现取失败：在 {CI_REL} 的 `{CI_JOB_NAME}` 里找不到 `-m pytest {PYTEST_TARGET} …`")
    if not local_argv:
        bad.append(f"本地腿现取失败：{VERIFY_REL} 的 `ci_helper_leg()` 里找不到 `-m pytest {PYTEST_TARGET} …`")
    if ci_argv and local_argv and ci_argv != local_argv:
        bad.append(
            "本地腿与 CI 的 pytest argv 不再逐字相同（同源契约破了）——"
            f"\n    CI   = {ci_argv}\n    本地 = {local_argv}"
        )

    # 判据 2：触发面覆盖
    face = _extract_function(verify_text, "ci_helper_face_paths")
    if not face:
        bad.append(f"{VERIFY_REL} 里找不到 `ci_helper_face_paths()`（触发面无对象可判）")
    for fragment in REQUIRED_FACE_FRAGMENTS:
        if face and fragment not in face:
            bad.append(f"触发面缺 `{fragment}` ⇒ 改这条面时本地腿不会被派发（形态原样复发）")

    # 判据 3：命中才派发 + 未命中显式「未跑」
    gate = _gate_branch(verify_text)
    if not gate:
        bad.append(f"{VERIFY_REL} 里找不到 `gate)` 分支（派发面无从判定）")
    if gate:
        if "ci_helper_face_hit" not in gate:
            bad.append("gate 档里没有按触发面派发这条腿（要么永远不跑、要么每个 PR 都跑）")
        if "未跑" not in gate:
            bad.append("gate 档未命中时没有显式声明「未跑」⇒ 静默 ✅ 的形态回来了")
    return bad


def test_leg_matches_ci_and_is_dispatched() -> None:
    """真语料：本地腿 == CI 命令，且触发面/派发/未跑声明齐备。"""
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    problems = leg_problems(verify_text, ci_text)
    assert not problems, "\n".join(["ci-helper 腿的判据未通过：", *[f"  · {p}" for p in problems]])


def test_red_proof_argv_drift() -> None:
    """🔴 红证（内存构造）：把本地腿的 argv 改一个字符 ⇒ 判据 1 报红。"""
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    assert leg_problems(verify_text, ci_text) == []
    mutated = verify_text.replace("-p no:cacheprovider", "-p no:cacheproviderX", 1)
    assert mutated != verify_text, "变异没生效（注入点漂移）"
    problems = leg_problems(mutated, ci_text)
    assert any("argv" in p for p in problems), problems


def test_red_proof_face_fragment_removed() -> None:
    """🔴 红证：把触发面里的 `.github/` 去掉 ⇒ 判据 2 报红。"""
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    mutated = verify_text.replace(r"grep -E '^(\.github/|tests/unit_ci_workflows/)'", r"grep -E '^(tests/unit_ci_workflows/)'", 1)
    assert mutated != verify_text, "变异没生效（注入点漂移）"
    problems = leg_problems(mutated, ci_text)
    assert any(".github/" in p for p in problems), problems


def test_red_proof_silent_when_not_hit() -> None:
    """🔴 红证：删掉「未命中 ⇒ 显式未跑」的那句 ⇒ 判据 3 报红。"""
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    gate = _gate_branch(verify_text)
    assert "未跑" in gate
    mutated = verify_text.replace(gate, gate.replace("未跑", "跳过"), 1)
    problems = leg_problems(mutated, ci_text)
    assert any("未跑" in p for p in problems), problems
