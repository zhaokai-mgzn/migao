# case_ids: OR-014
"""缺陷二红证：`completion_verdict` 对 `prior_count=1` 的跨 run 复发漏报 systemic。

盲审出处（判定跑 `34923425338`，mibao 腿，`@7d930e34`）：`OR-014` 的 case 记录带
`cross_run_recurrence {prior_runs:[34916256903], prior_count: 1}`、
`flake-history-mibao` 同指纹含两 run（34916256903 + 本 run 34923425338），而
`completion.systemic_recurrence=[]` ⇒ 完成层对「跨 run 复发」漏报（本轮因 det
已阻塞 OR-014 而无害，但构成口径不合，与上轮 OR-016 漏放同族）。

根因：`completion_verdict` 的 `score<1.0` 失败路径**不查 `_is_recurring`** ——
OR-014（score=0.0、分类 reproducible、非旅程、非放行分类）落入 `deterministic`
分支，永不进 `systemic_recurrence`。判据注释写着「凡 `cross_run_recurrence.
prior_count>0` 且指纹同型 ⇒ 一律进 systemic，不因本轮通过/旅程身份/分类
llm-noise 而放行」，但上轮只把它落进 `score>=1.0` 分支与放行分类分支；失败路径
漏了。**无 `prior_count>=2` 隐式阈值**（`CROSS_RUN_RECURRENCE_MIN_PRIOR = 1`），
标注本身已挂上结果 —— 是判定循环的分支结构漏了。

修法：失败路径先判复发（与 `score>=1.0` 通过路径镜像）：复发 ⇒ 进 systemic，
不再落入 deterministic / journey_fail / flake_released。

红证：
- 改前：prior_count=1 复发夹具（真实 OR-014 形态）⇒ `systemic_recurrence=[]`（漏报，红）；
- 改后：进 `systemic_recurrence`（绿）；
- 不影响判定结论：ok 改前（det 阻塞）与改后（systemic 阻塞）都是 False；
- 反向：`prior_count=0` 首见（无 `cross_run_recurrence` 标注）⇒ 不进 systemic。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，单测不得真实 HTTP）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


# ── OR-014 真实形态夹具（判定跑 34923425338 的 artifact 逐字段复刻）─────────────

def _or014_recurring():
    """score<1.0 + 分类 reproducible + 跨 run 复发（prior_count=1）—— 真实漏报形态。"""
    return {
        "case_id": "OR-014",
        "score": 0.0,
        "classification": "reproducible",
        "cross_run_recurrence": {
            "case_id": "OR-014",
            "fingerprint": "amount_verify(order_create,unit_price)",
            "prior_runs": ["34916256903"],
            "prior_count": 1,
        },
    }


def _or014_first_seen():
    """反向：prior_count=0 首见 —— 无 `cross_run_recurrence` 标注（真实漏报形态的反面）。"""
    return {"case_id": "OR-014", "score": 0.0, "classification": "reproducible"}


def _legacy_failing_path(result, journey_set):
    """**改造前** `completion_verdict` 的 `score<1.0` 路径（独立复写，红证用）：
    失败路径不查 `_is_recurring` ⇒ 复发条目落入 deterministic（systemic 漏报）。
    """
    cid = str(result.get("case_id") or "?")
    if cid in journey_set:
        return "journey_fail"
    if str(result.get("classification") or "") in lr._COMPLETION_RELEASED_CLASSES:
        if result.get("cross_run_recurrence"):
            return "systemic"
        return "flake_released"
    return "deterministic"


class TestSystemicRecurrencePriorCountOne:
    def test_legacy_red_recurring_lands_in_deterministic(self):
        """**改前红证**：旧失败路径把带 `cross_run_recurrence`（prior_count=1）的
        OR-014 归到 `deterministic` —— `systemic_recurrence` 恒漏报该条
        （34923425338 实证：det=['OR-014'] 且 systemic=[]）。"""
        bucket = _legacy_failing_path(_or014_recurring(), set(lr.KEY_JOURNEYS_MIBAO))
        assert bucket == "deterministic", (
            f"旧逻辑给了桶 {bucket!r} —— 红证夹具没构造出「复发落 deterministic」形态")

    def test_prior_count_one_recurring_reported_in_systemic(self):
        """**改后**：凡 `cross_run_recurrence.prior_count>=1` 且指纹同型 ⇒ 进
        `systemic_recurrence`（改前该断言红：systemic=[] 漏报）。"""
        v = lr.completion_verdict([_or014_recurring()], ())
        assert "OR-014" in v["systemic_recurrence"], v
        assert "OR-014" not in v["deterministic_failures"], v
        assert "OR-014" not in v["journey_failures"], v

    def test_verdict_stays_blocked_ok_unchanged(self):
        """不影响本轮判定结论：改前 det 阻塞、改后 systemic 阻塞 —— `ok` 都是 False。"""
        v = lr.completion_verdict([_or014_recurring()], ())
        assert v["ok"] is False, v

    def test_reverse_first_seen_not_systemic(self):
        """反向：`prior_count=0` 首见（无复发标注）⇒ 不进 systemic，维持原桶。"""
        v = lr.completion_verdict([_or014_first_seen()], ())
        assert v["systemic_recurrence"] == [], v
        assert v["deterministic_failures"] == ["OR-014"], v
