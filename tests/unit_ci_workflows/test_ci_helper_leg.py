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


#: argv 之后的 **shell 控制尾巴**（`|| rc=1` / `&& …` / `; …`）**不是 argv 的一部分**。
#: 拆腿（issue #6164）后本地每片都写成
#: `MIGAO_CI_HELPER_SHARD=N/M python3 -m pytest … -n 4 || ci_helper_rc=1`
#: —— 片号**必须走环境变量**（两条既有契约：argv 逐字同源 + 全量命令只许出现一次）、
#: 每片的退出码**必须逐片收集**（一片红不许把另一片的结论吃掉）⇒ 比对前剥掉这条尾巴。
#: ⚠️ 剥的**只有**控制符之后的部分：argv 本身（含 `-n 4`）仍然逐字比。
_SHELL_TAIL_RE = re.compile(r"\s*(?:\|\||&&|;).*$")


def _argv_only(line: str) -> str:
    """去掉 shell 控制尾巴后的 argv 原文。"""
    return _SHELL_TAIL_RE.sub("", line or "").strip()


def _ci_pytest_argv(ci_text: str) -> str:
    """现取 CI 那条 job 里的 pytest 命令行（只取 argv，去掉解释器名）。

    取法：先定位 job 名，再在该 job 段落里找 `… -m pytest <target> …` 那一行。
    """
    idx = ci_text.find(CI_JOB_NAME)
    if idx < 0:
        return ""
    segment = ci_text[idx:]
    m = re.search(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", segment)
    return _argv_only(m.group(0)) if m else ""


def _local_pytest_argv(verify_text: str) -> str:
    """现取本地腿里的 pytest 命令行（同样只取 argv）—— 只取**第一条**（= 第一片）。"""
    body = _extract_function(verify_text, "ci_helper_leg")
    m = re.search(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body)
    return _argv_only(m.group(0)) if m else ""


def _local_pytest_argv_all(verify_text: str) -> list[str]:
    """现取本地腿里**全部** pytest 命令行（issue #6164 拆腿后本地是**两片** ⇒ 两行）。

    🔴 为什么必须取**全部**（本文件 2026-10-03 的一处真实退化）：拆腿后本地腿里有两行 argv，
    而 `re.search` 只拿**第一条** ⇒ 只改第二片（比如把片 2 的 `-n 4` 改成 `-n 8`）时
    **判据毫无反应** —— 并行度同源契约被钉住的只剩两片中的一片。
    「逐条都要逐字相同」才是原契约的意思（拆腿只该改**跑多少**，不该改**怎么跑**）。
    """
    body = _extract_function(verify_text, "ci_helper_leg")
    return [_argv_only(m.group(0))
            for m in re.finditer(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body)]


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

    # 判据 1：argv 逐字相同 —— **本地腿的每一条**（拆腿后 = 每一片）都必须与 CI 逐字相同
    ci_argv = _ci_pytest_argv(ci_text)
    local_all = _local_pytest_argv_all(verify_text)
    local_argv = local_all[0] if local_all else ""
    if not ci_argv:
        bad.append(f"CI 侧现取失败：在 {CI_REL} 的 `{CI_JOB_NAME}` 里找不到 `-m pytest {PYTEST_TARGET} …`")
    if not local_all:
        bad.append(f"本地腿现取失败：{VERIFY_REL} 的 `ci_helper_leg()` 里找不到 `-m pytest {PYTEST_TARGET} …`")
    if ci_argv and local_all:
        drifted = [a for a in local_all if a != ci_argv]
        if drifted:
            bad.append(
                f"本地腿与 CI 的 pytest argv 不再逐字相同（同源契约破了）—— 本地 {len(local_all)} 条里 "
                f"{len(drifted)} 条不一致（**每一条都要比**：只比第一条 ⇒ 只改第二片就没人拦）"
                f"\n    CI   = {ci_argv}\n    不一致 = {drifted}"
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


def test_red_proof_second_shard_argv_drift() -> None:
    """🔴 红证（内存构造）：**只改第二片**那行 argv ⇒ 判据 1 必须报红（#6164 补的真退化）。

    拆腿后本地腿有两行 argv；`re.search` 只取第一条 ⇒ 「只比第一条」的写法**放走了**
    「只改第二片」（实测：`-n 4 → -n 8` 只动第二片时判据毫无反应）。
    本红证就是那条退化的守门人：真语料下必须能报出**两片里有一片不一致**，且**点名**。
    """
    verify_text = (REPO / VERIFY_REL).read_text(encoding="utf-8")
    ci_text = (REPO / CI_REL).read_text(encoding="utf-8")
    all_local = _local_pytest_argv_all(verify_text)
    assert len(all_local) == 2, (
        f"本地腿现取到的 pytest 行数 = {len(all_local)}（拆腿后应为 2）⇒ 本红证无对象；先核对分片形态"
    )
    assert all_local[0] == all_local[1], "两片的 argv 本来就不一致 ⇒ 真语料已经红了（先修语料）"
    # **只动第二片**：先把 `ci_helper_leg()` 函数体里**真正那两条** pytest 行找出来（不能用裸
    # 字符串 `-n 4` 找 —— 注释里也写着 `-n 4`，会改错行），再改第二条的 `-n`。
    idx = verify_text.find("ci_helper_leg()")
    assert idx >= 0, "找不到本地腿函数（注入点漂移）"
    body = verify_text[idx:]
    matches = list(re.finditer(rf"-m\s+pytest\s+{re.escape(PYTEST_TARGET)}[^\n]*", body))
    assert len(matches) == 2, f"本地腿里现取到 {len(matches)} 条 pytest 行（应为 2）"
    second = matches[1]
    at = second.start() + second.group(0).rfind("-n 4")
    assert at > second.start(), f"第二条 pytest 行里找不到 `-n 4`：{second.group(0)!r}"
    mutated = verify_text[:idx] + body[:at] + "-n 8" + body[at + len("-n 4"):]
    hit = _local_pytest_argv_all(mutated)
    assert hit[0] == all_local[0] and hit[1] != all_local[0], f"变异点没命中第二片：{hit}"
    problems = leg_problems(mutated, ci_text)
    assert any("argv" in p for p in problems), (
        "只改第二片的 argv ⇒ 没有报红 ⇒ 并行度/同源契约只钉住了两片中的一片（#6164 的真退化）"
    )


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
