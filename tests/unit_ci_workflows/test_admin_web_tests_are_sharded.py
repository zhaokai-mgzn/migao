# case_ids: MC-363
"""`admin-web` 单测必须真的拆成**互补的两片**（issue #9153 ②）。

## 病

`Run unit tests` 实测 **455s** 且还在涨（三轮 295 → 426 → 455），是整个 `admin-web typecheck + unit tests`（635s）的绝对大头。
所以把它按 `vitest --shard=1/2` / `--shard=2/2` 拆成两条 required 腿。

## 这类拆片最容易出的三种假绿（所以判据要钉它们）

1. **两片跑同一半**（都写 `--shard=1/2`）⇒ 另一半永远没人跑，而两条腿都绿；
2. **两片触发面不同**（第 1 片看 `frontend/admin-web/**`、第 2 片忘加 worker-h5）⇒ 只改 worker-h5 的 PR 上第 2 片整段跳过，
   仍是绿 —— 「未跑」被读成「通过」；
3. **第 2 片带 job 级 `needs:`/`if:`** ⇒ required 检查永久悬空且**不会变红**（判定面根本没创建）。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
SHARD_JOBS = ("admin-web-test", "admin-web-tests-2")
EXPECTED = {"admin-web-test": "1/2", "admin-web-tests-2": "2/2"}


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")).get("jobs") or {}


def _shard_arg(job: str) -> str:
    steps = _jobs()[job].get("steps") or []
    for s in steps:
        run = str(s.get("run") or "")
        m = re.search(r"vitest run --shard=(\d+/\d+)", run)
        if m:
            return m.group(1)
    raise AssertionError(f"{job} 里找不到 `vitest run --shard=N/M`（拆片的那一半不见了 ⇒ 该片可能整段没跑）")


def test_two_shards_are_complementary():
    got = {job: _shard_arg(job) for job in SHARD_JOBS}
    assert got == EXPECTED, (
        "两片必须**互补**（1/2 与 2/2）—— 都写同一半时另一半永远没人跑，而两条腿都绿：\n"
        f"  现取：{got}\n  期望：{EXPECTED}"
    )


def test_both_shards_share_one_detect_predicate():
    jobs = _jobs()
    preds = {}
    for job in SHARD_JOBS:
        step = next((s for s in jobs[job]["steps"] if s.get("name") == "Detect admin-web changes"), None)
        assert step and "grep -E" in str(step.get("run") or ""), (
            f"{job} 的 `Detect admin-web changes` 步缺失或不再用 `grep -E` 判触发面"
            "（没有它就挡不住未命中面，本腿会在每个 PR 上整段真跑）"
        )
        preds[job] = "\n".join(str(step.get("run") or "").split("\n") if isinstance(step.get("run"), str) else [])
    a, b = preds["admin-web-test"], preds["admin-web-tests-2"]
    pat_a = re.search(r"grep -E '([^']+)'", a)
    pat_b = re.search(r"grep -E '([^']+)'", b)
    assert pat_a and pat_b, "两片的 detect 步里都应有 `grep -E '<谓词>'`"
    assert pat_a.group(1) == pat_b.group(1), (
        "两片的触发谓词必须逐字相同 —— 不同则「只改某一面」的 PR 上另一片整段跳过，仍绿（未跑≠通过）：\n"
        f"  第 1 片：{pat_a.group(1)}\n  第 2 片：{pat_b.group(1)}"
    )


def test_second_shard_has_no_job_level_gate():
    job = _jobs()["admin-web-tests-2"]
    assert "needs" not in job, "第 2 片是 required ⇒ **禁止** job 级 `needs:`（跳过 ⇒ 检查永久悬空且不会变红）"
    assert "if" not in job, "第 2 片是 required ⇒ **禁止** job 级 `if:`（同上；只许把 `if:` 放在步骤上）"
