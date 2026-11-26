# case_ids: MC-355
"""CI helper 分片的看门狗必须**有界且小于 job 上限**（issue #9105 家族，2026-11-24 诊断）。

## 病（2026-11-24 实测诊断，不是推断）

`ci workflow helper unit tests（中后段）`（3/4 片）在 CI 上**反复**烧满 20 分钟被 cancel（4 次），
而同一 commit 重跑能过、本机同片 296s（中位 266s、最慢成功 404s）。判据式排除：

- 被 cancel 的 job **前 6 个 step 全部 success**（checkout 18s / 生成 4s）⇒ runner 活着，**不是 runner 卡死**；
- `step 7`（pytest）有 `started_at`、永远没有 `completed_at` ⇒ 挂点在 pytest 内部；
- 同一次 run 的兄弟片 340/497/413s 全 success，且三次挂死分布在**三台不同 runner**；
- CI/local ≈ 0.96，撞 1200s 需要 4.5× 中位 ⇒ **纯慢做不到，只有无界等待做得到**。

## 为什么只有 3/4 片

全包 **>600s 的内部看门狗全部落在 3/4**（`1800` / `900×4` / `600`）；其它三片最大值 300s。
内部看门狗 > job 上限 ⇒ 挂住时**不会自己判红**，而是烧满 20 分钟被 cancel，
而 **GitHub 不为 cancelled job 上传日志** ⇒ 归因不出来（issue #9114）。

## 判据（两条，都是**现取**、不用手填台账）

1. `tests/unit_ci_workflows/**` 里任何 `subprocess` 调用的 `timeout=` 常量**不得超过**
   `MAX_INNER_WATCHDOG`（600s = job 上限 1200s 的一半）。
2. `test_reconcile_no_silent_skip.py` 里每个 `subprocess.run(...)` **必须显式带 `timeout=`**
   —— 那个文件里的 pipe 的 producer 是 `yes`（无限流），**只**在 consumer 早退时才结束。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
#: 内部看门狗上限：必须 **< job 上限的一半**。CI 的 pytest 步上限是 1200s（`.github/workflows/pr-check.yml`），
#: 任何超过 600s 的内部等待都可能「先被 job 掐死」⇒ 证据丢失（cancelled job 不上传日志）。
MAX_INNER_WATCHDOG = 600
_SENTINELS = {"run", "call", "check_call", "check_output", "Popen"}
_PIPE_FILE = "test_reconcile_no_silent_skip.py"


def _subprocess_calls(path: pathlib.Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name in _SENTINELS:
            out.append(node)
    return out


def _timeout_kw(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "timeout":
            return kw.value
    return None


def _files() -> list[pathlib.Path]:
    return sorted(p for p in DIR.glob("test_*.py"))


def test_no_inner_watchdog_exceeds_half_of_the_ci_job_cap():
    """超长内部看门狗 ⇒ 挂住时先被 job 掐死（cancelled 不上传日志）⇒ 必须 ≤ 600s。"""
    offenders = []
    for path in _files():
        for call in _subprocess_calls(path):
            value = _timeout_kw(call)
            if isinstance(value, ast.Constant) and isinstance(value.value, int):
                if value.value > MAX_INNER_WATCHDOG:
                    offenders.append(
                        f"{path.name}:{call.lineno} timeout={value.value} > {MAX_INNER_WATCHDOG}"
                    )
    assert not offenders, (
        "内部看门狗超过 job 上限的一半（挂住会先被 cancel，日志拿不到）：\n  "
        + "\n  ".join(offenders)
    )


def test_the_infinite_producer_pipe_always_has_a_timeout():
    """`test_reconcile_no_silent_skip.py` 的 pipe producer 是无限流 ⇒ 每个 `subprocess.run` 必须有 `timeout=`。"""
    path = DIR / _PIPE_FILE
    assert path.exists(), f"{_PIPE_FILE} 不存在 —— 本判据的被约束对象必须仍在（约束类判据要同 PR 补齐对象）"
    missing = [
        f"{path.name}:{call.lineno} 无 timeout"
        for call in _subprocess_calls(path)
        if _timeout_kw(call) is None
    ]
    assert not missing, (
        "无限 producer 的 pipe 缺 `timeout=`（命中不成立时会**永久挂住**，CI 表现为整片被 cancel）：\n  "
        + "\n  ".join(missing)
    )


def test_the_cap_is_documented_and_below_the_real_job_cap():
    """上限本身要有出处：必须写清「job 上限是多少、为什么取一半」，否则 600 是魔法数字。"""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "1200s" in text and "一半" in text, "上限没写清出处（job 上限 1200s、取一半的理由）"
    job = (REPO_ROOT / ".github" / "workflows" / "pr-check.yml").read_text(encoding="utf-8")
    assert "timeout-minutes: 20" in job, (
        "job 上限不再是 20 分钟 ⇒ `MAX_INNER_WATCHDOG=600` 的前提变了，必须重算并同步本判据"
    )
    assert MAX_INNER_WATCHDOG * 2 <= 20 * 60, f"上限 {MAX_INNER_WATCHDOG}s 已不小于 job 上限的一半"
