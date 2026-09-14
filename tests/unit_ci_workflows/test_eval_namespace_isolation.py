# case_ids: HR-003, AS-003, HR-002
"""并行污染的**声明式数据隔离**（issue #3781）—— 隔离前互相污染、隔离后不会（红证）。

## 病灶（真实 run 34856561459，两次独立 AI 审计共同确认）

同一 persona 腿内 78 条用例**共用一套栈/库**、`EVAL_CONCURRENCY=6` 并行 ⇒
用例之间通过**全局命名空间**互相改写前置，产生与 agent 能力无关的假红：

| 污染对 | 铁证（run 34856561459 产物原文） |
|---|---|
| `HR-002` → `HR-003` | HR-003 的 trace：`employee_manage(users=2 total=2)` + agent 原文「系统里有两个「王五」…我需要知道停用哪一个才能安全执行」⇒ `toggle_status` 永不成立。HR-002 创建的同名「王五」（`13812345678`）是种子「王五」（`13700137000`）之外的第二个。**HR-003 在 `KEY_JOURNEYS_MIBAO` ⇒ B 端 `completion.ok` 被永久压住** |
| `OR-016`/`CR-001`/`CH-010` → `AS-003` | AS-003 的 trace：R1 `order_query(orders=10 total=11)` → R4 `order_query(orders=13 total=13)` —— **运行期间**该手机号名下订单数还在增长，其"按手机号定位唯一目标单"的前置被并行建单用例改写（GLM 盲审判 `missing_precondition`，另一包判产品缺陷 —— 同一份证据两种归因） |

## 治法（数据隔离优先，**不做全局降并发**）

用例**声明**它依赖/写哪个全局资源（`EvalCase.namespaces`，key 形态 `<kind>:<值>`）；
两条声明有交集的用例**自动**进串行（独占）道，其余照旧并行。
`migao-dev-flow` §17.4 要求"不要只声明『几乎免费』"⇒ 本文件还用 `serialize_seconds`
把代价**算出来**（见 `TestCostIsMeasured`）。

## 红证（每条断言都会红）

- `test_real_collisions_would_recur_if_declarations_are_removed`：把 `namespaces` 清空
  再算一次 ⇒ 必然**不再分道**（旧行为复现）；不清空则必然分道。**去掉任一用例的声明即红。**
- `test_unsynchronized_access_corrupts_and_isolation_does_not`：构造两条读改写同一
  namespace 键的用例，未隔离时交错 → 结果被覆盖；隔离（同一条道 = 不重叠）→ 两条都拿到
  自己的值。这是"隔离前污染 / 隔离后不污染"的可执行证明（零 LLM、零 docker）。
- 真值主张反例：本文件**没有**"仓库当下恰有该缺陷"式自毁断言 —— 隔离生效后
  `test_isolation_actually_applies_on_the_real_case_set` 仍要求这两对**同处一条道**，
  修好不会把它判红（判红条件是"声明丢了"）。
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。

    被锁的是**纯函数**（声明 → 争用组 → 分道 → 代价），不该因缺一个 HTTP 客户端而不可测。
    """
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


def _load_cases():
    import eval_cases
    return list(eval_cases.ALL_CASES)


lr = _load_runner()


class _C:
    """最小用例替身（只要 id/tags/post_session/namespaces —— 与 run_suite 的鸭子类型一致）。"""

    def __init__(self, cid, namespaces=(), tags=(), post_session=None):
        self.id = cid
        self.namespaces = list(namespaces)
        self.tags = list(tags)
        self.post_session = post_session


class TestDeclarationLayerIsSound:
    def test_real_cases_declare_the_two_proven_collisions(self):
        """**铁证对**必须在用例资产里显式声明（否则隔离机制对它们无效）。"""
        by_id = {c.id: c for c in _load_cases()}
        must = {
            "HR-002": "employee_name:王五",
            "HR-003": "employee_name:王五",
            "AS-003": "customer_phone:13800138000",
            "OR-016": "customer_phone:13800138000",
        }
        missing = [f"{cid} 缺 {key}" for cid, key in must.items()
                   if key not in lr.namespace_claims(by_id[cid])]
        assert missing == [], (
            "这些用例没有声明它争用的全局命名空间 —— 隔离机制对它们失效"
            f"（#3781 的两次审计铁证对）：{missing}")

    def test_declared_namespace_keys_are_wellformed(self):
        """声明形态必须带 `kind:` 前缀（裸值无法分辨"员工名"与"客户手机号"同名撞车）。"""
        bad = []
        for c in _load_cases():
            for k in lr.namespace_claims(c):
                if ":" not in k or not k.split(":", 1)[0].strip() or not k.split(":", 1)[1].strip():
                    bad.append(f"{c.id}: {k!r}")
        assert bad == [], f"命名空间声明形态非法（应为 `<kind>:<值>`）：{bad}"


class TestIsolationBeforeAfter:
    def test_real_collisions_would_recur_if_declarations_are_removed(self):
        """红证：**去掉声明即回到旧行为**（污染对重新并行）——隔离不是靠"看起来对了"。"""
        real = _load_cases()
        # ① 现在（有声明）：两对铁证对必须被判进**同一条**（串行）道
        ns = lr.namespace_conflict_groups(real)
        conflicted = {i for g in ns.values() for i in g}
        for cid in ("HR-002", "HR-003", "AS-003", "OR-016"):
            c = next(x for x in real if x.id == cid)
            assert lr.needs_serial_lane(c, conflicted), (
                f"{cid} 未进串行道 —— 它声明的资源正被别的用例争用（这正是污染的来源）")
        # ② 把声明全部清掉 = 复现**改造前**的判据 ⇒ 铁证对重新落回并行道
        stripped = [x for x in real]
        for x in stripped:
            x.namespaces = []
        ns0 = lr.namespace_conflict_groups(stripped)
        assert ns0 == {}, "清掉声明后仍有争用组（说明争用不是从声明推出来的，模型不自洽）"
        conflicted0 = frozenset()
        still_serial = [x.id for x in stripped
                        if lr.needs_serial_lane(x, conflicted0)
                        and x.id in ("HR-002", "HR-003", "AS-003", "OR-016")]
        assert still_serial == [], (
            "清掉声明后这些用例仍被判独占（说明分道另有来源，本红证无判别力）："
            f"{still_serial}")

    def test_unsynchronized_access_corrupts_and_isolation_does_not(self):
        """**污染的可执行证明**（L0，零 LLM）：未隔离 → 互相覆盖；隔离 → 各自增量都在。

        模型化真实形态：两条用例都写同一个全局命名空间（= 同一个手机号名下各建一单 /
        同一个员工姓名下各建一个账号）。**先按真实判据取分道结果**，再按该分道跑两种
        调度 —— 这样"隔离前/隔离后"的差别**完全**由 `needs_serial_lane` 决定，而不是我
        手写的假设（否则测试自己就把结论预设了）。
        """
        KEY = "customer_phone:13800138000"
        declared = [_C("AAA", [KEY]), _C("BBB", [KEY])]
        undeclared = [_C("AAA", []), _C("BBB", [])]

        def lanes(cases):
            conflicted = {i for g in lr.namespace_conflict_groups(cases).values() for i in g}
            return ([c.id for c in cases if c.id not in
                     {x.id for x in cases if lr.needs_serial_lane(x, conflicted)}],
                    [c.id for c in cases if lr.needs_serial_lane(c, conflicted)])

        def store_after(par, ser) -> list:
            """该手机号名下"各用例的产物"（用元素表示；被覆盖的会消失）。

            并行道 = 两条**同窗口**（各自读快照 → 各自写回）⇒ 后写者覆盖前写者；
            串行道 = 读改写不重叠（这正是"互斥"的含义）。
            """
            store: list = []
            snapshots = {cid: list(store) for cid in par}
            for cid in par:
                store[:] = snapshots[cid] + [cid]
            for cid in ser:
                store[:] = list(store) + [cid]
            return store

        # ① 改造前（**没有** namespace 声明）⇒ 两条都进并行道、同窗口 ⇒ 互相覆盖
        par0, ser0 = lanes(undeclared)
        assert par0 == ["AAA", "BBB"] and ser0 == [], (
            f"未隔离的分道没有复现（par={par0} ser={ser0}）—— 本红证无判别力")
        uniso = store_after(par0, ser0)
        assert uniso == ["BBB"], f"未隔离时未复现互相覆盖（实得 {uniso}）"

        # ② 隔离后（**声明了** namespace）⇒ 两条都进串行道 ⇒ 互斥 ⇒ 两条产物都在
        par1, ser1 = lanes(declared)
        assert par1 == [] and sorted(ser1) == ["AAA", "BBB"], (
            f"隔离未生效：par={par1} ser={ser1} —— 它们会互相覆盖对方的前置")
        iso = store_after(par1, ser1)
        assert iso == ["AAA", "BBB"], f"隔离后仍互相覆盖（实得 {iso}）"

    def test_isolation_is_derived_not_hardcoded(self):
        """红线：分道必须**由声明推出**。若哪天有人改成"按用例 ID 硬编码名单"，这条即红。"""
        a, b = _C("AAA", ["k:1"]), _C("BBB", ["k:1"])
        conflicted = {i for g in lr.namespace_conflict_groups([a, b]).values() for i in g}
        assert lr.needs_serial_lane(a, conflicted) and lr.needs_serial_lane(b, conflicted)
        # 换掉其中一个的声明 → 争用消失 → 两条都回到并行道（证明推导链活着）
        b2 = _C("BBB", ["k:2"])
        conflicted2 = {i for g in lr.namespace_conflict_groups([a, b2]).values() for i in g}
        assert conflicted2 == set()
        assert not lr.needs_serial_lane(a, conflicted2)
        assert not lr.needs_serial_lane(b2, conflicted2)


class TestIsolationActuallyApplies:
    def test_conflict_groups_are_derived_from_declarations(self):
        """争用组 = 恰好"被两条以上用例声明的键"（关系式断言，与仓库真值解耦）。"""
        cases = [_C("A", ["k:1", "k:2"]), _C("B", ["k:1"]), _C("C", ["k:3"])]
        assert lr.namespace_conflict_groups(cases) == {"k:1": ["A", "B"]}

    def test_readonly_case_without_declaration_stays_parallel(self):
        """没声明资源的用例**不受影响**（隔离的作用域是撞车组，不是全局降并发）。"""
        cases = [_C("A", ["k:1"]), _C("B", ["k:1"]), _C("C")]
        conflicted = {"A", "B"}
        assert lr.needs_serial_lane(cases[2], conflicted) is False

    def test_tag_and_post_session_lanes_are_unchanged(self):
        """既有分道判据不被本次改动破坏（回归护栏）。"""
        conflicted = frozenset()
        assert lr.needs_serial_lane(_C("X", tags=["id_reuse"]), conflicted) is True
        assert lr.needs_serial_lane(_C("X", tags=["full_lifecycle"]), conflicted) is True
        assert lr.needs_serial_lane(_C("X", post_session=[{"fetch": "user_memories"}])) is True
        # **声明了 pre_clean 不再**整体独占（#3361 提速第三轮的结论，必须保持）
        c = _C("X")
        c.pre_clean = [{"type": "product_dedupe"}]
        assert lr.needs_serial_lane(c, conflicted) is False


class TestCostIsMeasured:
    """`migao-dev-flow` §17.4：不要只声明「几乎免费」——代价必须**算出来**。"""

    def test_isolation_cost_is_finite_and_bounded(self):
        """隔离的代价必须是**有限且可解释**的（不是"全局降并发"那种数量级）。"""
        cases = _load_cases()
        d = {c.id: 10.0 for c in cases}          # 每条 10s 的合成时长（与真实值无关，只比结构）
        cost = lr.serialize_seconds(cases, d, concurrency=6)
        assert cost["cases"] == len(cases)
        assert cost["serial_lane"] >= 1 and cost["parallel_lane"] >= 1
        # 串行道时长 = 该道用例数 × 单条时长（串行 = 不重叠）
        assert cost["serial_s"] == cost["serial_lane"] * 10.0
        # 墙钟 = max(并行摊派, 串行累加) —— 量级必须是"用例数/K"而不是"用例数"
        assert cost["wall_s"] <= cost["cases"] * 10.0
        assert cost["wall_s"] < cost["cases"] * 10.0 / 6 * 4, (
            "墙钟量级接近串行全量 ⇒ 隔离退化成了全局降并发（本 PR 明确拒绝该手段）"
            f"：{cost}")

    def test_no_global_concurrency_downgrade(self):
        """**并行道必须仍占多数**：若隔离把绝大多数用例拖进串行，这条即红。

        判据取"并行道占比 > 60%"（当前真实集合实测约 73%）——它直接对应
        "不许把全局降到 1 并发当作唯一手段"：那种做法下并行道占比 = 0。
        """
        cases = _load_cases()
        d = {c.id: 10.0 for c in cases}
        cost = lr.serialize_seconds(cases, d, concurrency=6)
        ratio = cost["parallel_lane"] / cost["cases"]
        assert ratio > 0.60, (
            f"并行道占比仅 {ratio:.0%}（{cost}）—— 隔离范围过大，退化成全局降并发")
