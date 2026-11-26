# case_ids: MC-357
"""`UI Regression Check` 腿**不许全史克隆**（issue #9120 的成本追因）。

## 病

该 job 用 `fetch-depth: 0`（全史克隆，仓库 401 MiB / 1775 commits）⇒ **checkout 实测 16–20s**，
而它整腿的冻结预算是 **12s**、真正的判据步只有 **1s** —— 也就是说这条腿**光是拿代码就超预算**，
`ci_cost_ledger.py --measure` 因此一直拒绝写盘。

## 为什么可以只拿两个 tip

`check-ui-regression.sh` 只用两处 git 能力：`git show HEAD:<f>`（PR 侧）与
`git show origin/main:<f>`（基线侧），且它自己会 `git fetch origin main --quiet`（L54）。
⇒ 默认浅克隆（depth=1）+ 脚本里的那一次 fetch 就够了，**不需要**历史。

## 判据（两条）

1. `pr-check.yml` 的 `UI Regression Check` job 里**不得**出现 `fetch-depth: 0`；
2. `check-ui-regression.sh` **不得**引入需要历史的 git 命令（`log` / `rev-list` / `blame` /
   `describe` / `shortlog`）—— 一旦引入，浅克隆就会静默读不到 ⇒ 本判据当场红，
   逼改动方**显式**把 fetch-depth 加回并说明代价。
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
SCRIPT = REPO_ROOT / "check-ui-regression.sh"
JOB_NAME = "UI Regression Check"
HISTORY_OPS = ("log", "rev-list", "blame", "describe", "shortlog")


def _job_block(name: str) -> str:
    """切出某个 job 的 YAML 片段（从其 `name:` 行到下一个顶层 job 之前）。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(rf"^    name: {re.escape(name)}$", text, re.M)
    assert m, f"pr-check.yml 里找不到 job `{name}`（约束类判据必须与被约束对象对齐）"
    rest = text[m.start():]
    nxt = re.search(r"^    name: ", rest[1:], re.M)
    return rest[: nxt.start() + 1] if nxt else rest


def test_ui_regression_checkout_is_not_full_history():
    """全史克隆白花 10–14s，而这条腿预算只有 12s ⇒ 不许再出现 `fetch-depth: 0`。"""
    block = _job_block(JOB_NAME)
    # 只看**非注释**行：注释里说明「不要 fetch-depth: 0」是合法的（本 job 就有这样一段）
    effective = "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "fetch-depth: 0" not in effective, (
        "`UI Regression Check` 又用上 `fetch-depth: 0` 了 —— 这条腿只 `git show` 两个 tip"
        "（脚本自己 fetch origin/main），全史克隆实测白花 10–14s，直接把它顶出 12s 预算（issue #9120）。\n"
        "若真需要历史：请在本 job 注释里写明**哪条判据**需要、以及它对预算的影响。"
    )
    assert "check-ui-regression.sh --head" in block, "job 里没有跑那个脚本 ⇒ 本判据的被约束对象变了"


def test_ui_regression_script_needs_no_history():
    """浅克隆的前提：脚本不引入需要历史的 git 命令。"""
    body = SCRIPT.read_text(encoding="utf-8")
    offenders = []
    for op in HISTORY_OPS:
        for m in re.finditer(rf"\bgit\s+{re.escape(op)}\b", body):
            offenders.append(f"git {op} @ 偏移 {m.start()}")
    assert not offenders, (
        "`check-ui-regression.sh` 用到了需要**历史**的 git 命令 ⇒ 浅克隆下会静默读不到：\n  "
        + "\n  ".join(offenders)
        + "\n要么改回 `git show <ref>:<path>`（只需两个 tip），要么把 `fetch-depth: 0` 加回去并说明代价。"
    )
