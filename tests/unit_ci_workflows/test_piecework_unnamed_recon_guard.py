# case_ids: MC-139
"""计件 A0b「逐人比对」假红的夹具判据 + 接线守卫 + 注入式红证（issue #7030）。

病（issue #7030，工装假红，实测误导过一次）：`acceptance/2026-10-03/finance-stock-time-sweep/harness/
famA-money.mjs` 的 A0b 拿独立 SQL 的 `worker_name` 分组（无署名那组是 NULL）去和接口 `per_worker`
**逐字**比对，而接口会把无署名的那笔钱归进一个**服务端下发的展示文案**（本仓今天叫「未分配」）
⇒ 「名不同、钱相同」⇒ 稳定判红，且失败文案（`{"worker_name":null,...}`）天然指向「接口漏了这笔钱」
（据此开出过错的「钱面缺陷」单 #7028）。**一条红不在真问题上的判据，会消耗掉一整轮排查并产出错误结论。**

本文件守四件事（全部靠 `node --test` 真跑；纯 CPU / 零网络 / 零 DB / 零时钟）：

| # | 判什么 | 怎么红 |
|---|---|---|
| 1 | 夹具判据是绿的（8 条，含 issue 要求的 ①②③），且**三条必需用例真的跑了**（防"零用例也全绿"） | 套件非零退出 / 必需用例名缺席 |
| 2 | **红证（注入式）**：把 `isUnassignedWorker` 改成 `return false`（= 删掉「无署名」特殊处理） | 判据①（有未分配行 ⇒ A0b 不判红）当场 `not ok` |
| 3 | **接线在**（§28.2）：`famA-money.mjs` 必须真的用 `judgePiecework(...)` 产出 A0b/A0c，旧的 `perWorker.get(...)` 逐字比对不许回潮 | 摘掉导入 / 摘掉调用 / 写回旧形态 ⇒ 各自判红 |
| 4 | 判定模块的**代码行**里不许出现服务端文案（文案只许出现在注释里） | 写死文案 = 本单病根回潮 |

⚠️ 边界（照实登记）：② 的注入是**本判据自己造的临时副本**（不写仓内文件）；
「服务端将来换成第三个文案」判不了（守卫只认已知的两个文案 + 结构无关性由 node 夹具的换文案用例承担）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

HARNESS = (
    Path(__file__).resolve().parents[2]
    / "acceptance/2026-10-03/finance-stock-time-sweep/harness"
)
RECON = HARNESS / "piecework-recon.mjs"
SUITE = HARNESS / "piecework-recon.test.mjs"
LIB = HARNESS / "lib.mjs"
FAM_A = HARNESS / "famA-money.mjs"

# 夹具套件里**必须真的跑过**的三条判据（与 `piecework-recon.test.mjs` 的 test() 名逐字对应）。
REQUIRED = (
    "判据① 夹具含无署名归集行 ⇒ A0b 不判红（当前假红消失）",
    "判据② 同夹具把真实工人的金额改错 ⇒ A0b 必红（判别力没被削弱）",
    "判据③ 无署名金额与总额的勾稽被断言（不是跳过）",
)
# 红证注入点：`isUnassignedWorker` 的函数体（唯一一行）。
INJECTION_ANCHOR = "  return !hasText(workerName)"
INJECTED_BODY = "  return false // 注入：删掉「无署名」特殊处理（issue #7030 判据④）"
# 服务端下发的归集文案（今天两个读面各叫一个，见 issue #4309 / #7030）。
SERVER_LABELS = ("未分配", "未署名")


def _node() -> str:
    node = shutil.which("node")
    assert node, "node 不可用（本判据的结构前提：夹具判据由 node --test 真跑）"
    return node


def _run_suite(directory: Path, out_dir: Path) -> subprocess.CompletedProcess:
    """在 `directory` 里跑该目录下的 piecework-recon.test.mjs（TAP 报告器，便于逐条读读数）。"""
    env = {**os.environ, "OUT_DIR": str(out_dir)}
    return subprocess.run(
        [_node(), "--test", "--test-reporter=tap", str(directory / SUITE.name)],
        cwd=str(directory),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )


def _tap_results(output: str) -> dict[str, str]:
    """TAP → {用例名: 'ok'|'not ok'}（只认顶层 `ok N - 名` 行）。"""
    results = {}
    for line in output.splitlines():
        m = re.match(r"^(not ok|ok) \d+ - (.+)$", line.strip())
        if m:
            results[m.group(2).strip()] = m.group(1)
    return results


# ── 判据 1：夹具套件是绿的，且三条必需用例真的跑了 ─────────────────────
def test_fixture_suite_is_green_and_runs_the_three_required_judgements(tmp_path):
    proc = _run_suite(HARNESS, tmp_path / "out")
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"夹具判据套件判红（rc={proc.returncode}）：\n{output}"
    results = _tap_results(proc.stdout)
    assert results, f"没读到任何 TAP 用例读数（空跑 = 假绿）：\n{output}"
    for name in REQUIRED:
        assert results.get(name) == "ok", f"必需用例没跑或没通过：{name!r}｜读数={results.get(name)!r}\n{output}"
    assert "not ok" not in results.values(), f"有判据判红：{results}\n{output}"


# ── 判据 2：红证（注入）—— 删掉「无署名」特殊处理 ⇒ 判据① 必红 ─────────
def test_red_proof_removing_unassigned_special_case_turns_case_one_red(tmp_path):
    source = RECON.read_text(encoding="utf-8")
    assert source.count(INJECTION_ANCHOR) == 1, (
        "注入点不再唯一 ⇒ 本红证失效（判据④ 会变成空断言）："
        f"命中 {source.count(INJECTION_ANCHOR)} 次｜锚点={INJECTION_ANCHOR!r}"
    )
    injected_dir = tmp_path / "injected"
    injected_dir.mkdir()
    (injected_dir / RECON.name).write_text(
        source.replace(INJECTION_ANCHOR, INJECTED_BODY), encoding="utf-8"
    )
    shutil.copy2(SUITE, injected_dir / SUITE.name)
    shutil.copy2(LIB, injected_dir / LIB.name)

    proc = _run_suite(injected_dir, tmp_path / "out")
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "注入「删掉无署名特殊处理」后套件仍然全绿 ⇒ 判据① 是**空断言**（修前红取不出来）：\n" + output
    )
    results = _tap_results(proc.stdout)
    assert results.get(REQUIRED[0]) == "not ok", (
        f"注入后红在了别处（不是判据①）⇒ 归因不成立：{results}\n{output}"
    )
    # 归因读数：注入后**只有**与「无署名归集」直接相关的判据变红，其余（如「漏一组必红」）仍绿 ——
    # 证明红确实是这条特殊处理承载的，而不是整个套件崩了。
    assert results.get("接口漏掉一个真实工人 ⇒ A0b 必红（missing-in-api）") == "ok", (
        f"注入把与归集无关的判据也弄红了 ⇒ 红证不可归因：{results}\n{output}"
    )


# ── 判据 3：接线在（§28.2「判据本体绿 ≠ 接线在」）─────────────────────
def _wiring_problems(source: str) -> list[str]:
    problems = []
    if "from './piecework-recon.mjs'" not in source:
        problems.append("famA 没有从 piecework-recon.mjs 导入（判定模块可能是死代码）")
    if "judgePiecework({" not in source:
        problems.append("famA 没有调用 judgePiecework({...})（A0b/A0c 没接上）")
    if "judge(R, v)" not in source:
        problems.append("judgePiecework 的结论没有被送进记录器（judge(R, v) 缺席）")
    if "perWorker.get(" in source:
        problems.append("旧的「按原始 worker_name 分组逐字比」形态还在（病根回潮）")
    if "new Map((got?.per_worker" in source:
        problems.append("旧的 per_worker → Map 归一还在（病根回潮）")
    return problems


def test_famA_wiring_uses_the_structural_judgement():
    source = FAM_A.read_text(encoding="utf-8")
    problems = _wiring_problems(source)
    assert not problems, "接线判据判红：" + "；".join(problems)


def test_wiring_guard_has_discriminating_power():
    """判别力自证：三种坏形态各自判红（否则接线守卫本身是空断言）。"""
    source = FAM_A.read_text(encoding="utf-8")
    assert _wiring_problems(source) == []

    dropped_import = source.replace("import { judgePiecework } from './piecework-recon.mjs'\n", "")
    assert _wiring_problems(dropped_import), "摘掉导入却没判红"

    dropped_call = source.replace("judgePiecework({", "notWired({")
    assert _wiring_problems(dropped_call), "摘掉调用却没判红"

    restored_legacy = source + (
        "\nconst perWorker = new Map((got?.per_worker || []).map((x) => [x.worker_name, x.amount]))\n"
        "const mism = expectRows.filter((e) => perWorker.get(e.worker_name) !== e.amount)\n"
    )
    assert _wiring_problems(restored_legacy), "写回旧的逐字比对却没判红"


# ── 判据 4：判定不许写死服务端文案（文案只许出现在注释里）──────────────
def _code_lines(text: str) -> list[str]:
    """剔掉注释行（`//` / `/*` / JSDoc 续行 `*`）；剩下的才算"代码行"。"""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("//", "/*", "*")):
            continue
        lines.append(line)
    return lines


def test_judgement_never_hardcodes_the_server_label():
    code = "\n".join(_code_lines(RECON.read_text(encoding="utf-8")))
    offenders = [label for label in SERVER_LABELS if label in code]
    assert not offenders, (
        f"判定模块把服务端文案 {offenders} 写进了**代码**（issue #7030 的病根正是它）；"
        "文案只能进证据/注释，判定必须看结构"
    )
    # 红证：把文案写成一行代码 ⇒ 当场判红（守卫有判别力，不是恒真）
    injected = RECON.read_text(encoding="utf-8") + "\nconst LABEL = '未分配'\n"
    assert [label for label in SERVER_LABELS if label in "\n".join(_code_lines(injected))]
