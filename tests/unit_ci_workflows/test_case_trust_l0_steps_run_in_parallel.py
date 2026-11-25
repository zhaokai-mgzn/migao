# case_ids: MC-370
"""`case-trust-gate` 的 L0 退化守卫必须并行（issue #9120）。

## 现场（现取，CI step 明细）

`Case Trust Gate` 的 `L0 degenerate guards (判据不得是空壳)` 步跑
`pytest tests/unit_ci_workflows/test_case_trust_gate.py`（180 条），**单步 CI 实测 70s**，
是本腿仅次于 checkout 的开销（该腿总 98s）。慢的几条是**端到端驱动门禁脚本**的用例
（10.6s / 9.1s / 3.4s …）—— 它们各自解析全量用例库（1119 条）。

## 判据（三条）

1. 该步**必须**带 `-n N`（N ∈ [2,8]）；
2. 该步**必须**在同一个 `pip install` 行里装 `pytest-xdist`（否则 `-n` 只会 fail 成 unrecognized arguments）；
3. **不得**用 `--dist loadfile`：该步只指定**一个文件**，`loadfile` 会把整文件压到同一 worker
   ⇒ 等于串行、还多付 xdist 启动开销（实测：`loadfile` **50.8s** > 串行 43.6s > `load` **29.6s**）。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PR_CHECK = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"


def _l0_run() -> str:
    doc = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))
    for step in doc["jobs"]["case-trust-gate"]["steps"]:
        run = str(step.get("run") or "")
        if "test_case_trust_gate.py" in run:
            # 去注释行：注释里会**讨论** `--dist loadfile`（说明为什么不许用），别把它当成实际命令
            return "\n".join(ln for ln in run.splitlines() if not ln.strip().startswith("#"))
    raise AssertionError("找不到跑 `test_case_trust_gate.py` 的步骤")


def test_l0_guards_use_xdist():
    run = _l0_run()
    m = re.search(r"-n\s+(\d+)", run)
    assert m, (
        "L0 退化守卫没有 `-n` ⇒ 180 条判据串行跑，CI 实测 **70s**（慢的是几条端到端驱动门禁脚本的用例）：\n"
        + run
    )
    assert 2 <= int(m.group(1)) <= 8, f"`-n {m.group(1)}` 不在 [2,8]（runner 4 核）"


def test_pytest_xdist_is_installed_in_the_same_step():
    run = _l0_run()
    pip = [ln for ln in run.splitlines() if "pip install" in ln]
    assert pip, "该步没有 pip install 行（判据要求 xdist 与 pytest 同装）"
    assert "pytest-xdist" in pip[0], (
        f"`-n` 需要 pytest-xdist：{pip[0]!r} ⇒ 否则只会 fail 成 unrecognized arguments"
    )


def test_distribution_is_load_not_loadfile_for_a_single_file_target():
    run = _l0_run()
    assert "--dist loadfile" not in run, (
        "该步只跑**一个文件**，`--dist loadfile` 会把整文件压到同一 worker ⇒ 等于串行 + xdist 启动开销"
        "（实测 50.8s，比串行 43.6s 还慢；`load` 是 29.6s）"
    )
