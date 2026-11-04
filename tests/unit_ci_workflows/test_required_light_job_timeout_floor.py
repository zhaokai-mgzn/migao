# case_ids: MC-188
"""#8605：**required 的轻量 job 不许再把超时上限压到 2 分钟。**

病（本轮实测）：`pr-check.yml` 里三个 `timeout-minutes: 2` 的 required job，runner 一慢就在**步骤中途**
被取消；而在分支保护里 `cancelled` **等同于未通过** ⇒ PR 永久 BLOCKED，界面只显示「cancelled」，
**看起来像基础设施故障**。本轮为此烧掉约 2 小时，且中途反复 `gh run rerun`（每次都造新 attempt，越搅越乱）。

两条撞顶 incident（可复算）：
  · `block-env-files`  19:45:26Z→19:47:58Z = **152s** > 120s，卡在 `Run actions/checkout@v7`；
  · `case-truth-check` 19:49:37Z→19:51:41Z = **124s** > 120s，卡在 `Merge-result freshness`。

为什么判据是「下限」而不是「精确值」：上限是**值班判据**（`pr-check.yml` 既有口径），会随读数调整；
但**下限**是安全属性 —— 一个 required job 只要可能被 runner 慢化打成假红，它的上限就必须留够余量。
本判据只钉下限，抬得更高不红（数据驱动、不锁死现值）。

红证（实现前实测，注入后已恢复）：把 `block-env-files` 的 `timeout-minutes` 改回 `2` ⇒ 判据 1 红
（逐条具名「block-env-files = 2 分钟 < 下限 5 分钟」）。
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PR_CHECK = REPO / ".github" / "workflows" / "pr-check.yml"

# 本轮实证的三条：都属「required + 只做 checkout / merge 这类轻量动作」族。
# 新增同族站点时**显式**加进来（不靠名字模式猜 —— 猜错了会静默漏判）。
LIGHT_REQUIRED_JOBS = ("block-env-files", "case-truth-check", "label-needs-changes")

# 下限 = 实测 p90（≤ 11s）的 ~27 倍，同时容纳本轮实测的 15 倍慢化（152s）仍余 2 倍。
FLOOR_MINUTES = 5


def _jobs() -> dict:
    doc = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))
    return doc.get("jobs") or {}


def test_light_required_jobs_have_a_timeout_floor():
    jobs = _jobs()
    bad = []
    for job_id in LIGHT_REQUIRED_JOBS:
        if job_id not in jobs:
            bad.append(f"`{job_id}` **不在** pr-check.yml 里（本判据盯的对象已改名/已删 ⇒ 判据失明）")
            continue
        got = jobs[job_id].get("timeout-minutes")
        # 不写 `assert got is not None`：那是弱断言（新增文件一律 fail-closed）⇒ 用 if 收敛到下面的具名清单
        if not isinstance(got, int) or got < FLOOR_MINUTES:
            bad.append(f"`{job_id}` = {got!r} 分钟 < 下限 {FLOOR_MINUTES} 分钟（或未声明）")
    assert bad == [], (
        "required 轻量 job 的超时上限低于安全下限（#8605）：\n  "
        + "\n  ".join(bad)
        + "\n⇒ runner 慢一次就在步骤中途被 cancelled，而 cancelled 在分支保护里等同未通过"
        " ⇒ PR 永久 BLOCKED 且界面不可归因。"
    )


def test_the_floor_matches_the_measured_slowdown():
    """下限必须真的容得下本轮实测的慢化倍数（防有人把 FLOOR 调小到「好看但没用」）。"""
    jobs = _jobs()
    worst_observed_seconds = 152  # block-env-files 的实测耗时（见模块 docstring）
    too_small = []
    for job_id in LIGHT_REQUIRED_JOBS:
        got = jobs.get(job_id, {}).get("timeout-minutes")
        if not isinstance(got, int) or got * 60 < worst_observed_seconds * 2:
            too_small.append(f"`{job_id}` = {got!r} 分钟")
    assert too_small == [], (
        "这些 required 轻量 job 的上限容不下实测 152s 的 **2 倍**余量"
        "（#8605：抬上限的意义就是让「慢化 15 倍」仍有余量）："
        + "、".join(too_small)
    )
