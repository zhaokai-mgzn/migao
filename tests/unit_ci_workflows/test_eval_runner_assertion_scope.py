# case_ids: PG-016, PG-015, PP-006
"""`local_runner` 断言能力的**作用域**契约（issue #3667，确定性层）。

本文件锁住三条**已在真实重放里暴露**的 runner 能力缺口（零 LLM、纯函数，秒级）：

| 缺口 | 真实证据 |
|---|---|
| `repeat_until` 只有**工具级**停条件 | PG-016 `merge_log`（run 34821647043）：状态机三步都是 `processing_order_update`，`issue` 成功即整体停机 → start/complete 的重复轮被跳过、确认卡无人答；用例被迫改用 `auto_respond`（本质是能力缺口，不是写法问题） |
| `output_verify` 只认**字面顶层 key** | PG-016 `merge_log`（run 34822527203）：`expect: result.status` → 报「结果里没有字段 'result.status'」**假红**；用例只能把 expect 收敛成扁平键 → **丢掉了对嵌套产出的核对能力** |
| `_first_successful_payload` **同轮**取错 payload | PP-006 `merge_log`（run 34820346966）：首轮 `create_processing_item` 被拒后**同轮** `list_categories` 恢复成功 → 按工具名取首个成功 payload 又取到 `{'categories': [...]}` → 假红；此前只能靠改用例输入绕开（runner 侧当时属禁改区） |

为什么这些必须由**单测**锁住：三者都是"取错证据"型缺陷 —— 症状是假红/假绿，
而假绿在评测报告里**看不出来**（报告一片全绿）。真实 LLM 重放既慢又带方差，
不可能每次改动都靠它兜底（`migao-dev-flow` §16.1：L0 静态不变式优先）。

⚠️ 本目录（`tests/unit_ci_workflows`）跑在 CI 的 `ci workflow helper unit tests` job 里，
该 job 只 `pip install pytest pyyaml`（见 `.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` → 见下方 `_load_runner()` 的最小替身。
"""
import asyncio
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(REPO_ROOT / ".github"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身）。

    这些断言函数是**纯函数**（吃 `results` 列表、吐 issue 列表），不该因缺一个 HTTP
    客户端而不可测。替身只在 httpx 真的缺失时注入，且一旦被调用即抛错 ——
    单测不得真实发起 HTTP（`migao-dev-flow` §9.2 红线）。
    """
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:                  # 只满足模块级 `import httpx` 与类型引用
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _round(rnd, calls, results):
    """构造一轮 `results` 条目。

    calls   : [(tool, action)]（action=None 表示该调用不带 action 参数）
    results : [(tool, success, data)]（与该轮同名工具的调用**按顺序**对应）
    """
    return {
        "__round": rnd,
        "tool_calls": [
            {"name": t, "args": ({**({"action": a} if a else {})})} for t, a in calls
        ],
        "tool_results": [
            {"tool": t, "result": {"success": ok, "data": d}} for t, ok, d in results
        ],
    }


# ── ① `repeat_until` 的 action 级停条件（issue #3667 / PG-016）──────────────────

class TestRepeatUntilActionScope:
    """`repeat_until: {tool_called: X, action: Y}` = 「**X 的 Y 这次真的成了**才停」。

    为什么需要（PG-016 实证）：状态机三步（issue → start → complete）走的是**同一个**
    `processing_order_update`，工具级停条件在第一步就命中 → 后两步的重复轮被整体跳过。
    """

    def test_other_action_success_does_not_stop(self):
        """声明 action 后：同工具**其它** action 成功不算达成（旧语义会在这里停机）。"""
        results = [_round(1, [("processing_order_update", "issue")],
                          [("processing_order_update", True, {"status": "issued"})])]
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update", "action": "complete"}) is False
        # 反向锚点：不声明 action 时仍是工具级旧语义（向后兼容，不误伤既有用例）
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update"}) is True

    def test_declared_action_success_stops(self):
        """声明 action 后：该 action 真的成功 → 停。"""
        results = [
            _round(1, [("processing_order_update", "issue")],
                   [("processing_order_update", True, {"status": "issued"})]),
            _round(2, [("processing_order_update", "complete")],
                   [("processing_order_update", True, {"status": "completed"})]),
        ]
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update", "action": "complete"}) is True

    def test_same_round_alignment_beats_tool_level_success(self):
        """**同一轮**里别的 action 成功、声明的 action 失败 → 不许停。

        这是 action 级停条件的精度要求：只按工具名数成功次数会提前停机
        （confirm 卡还没人答，用例被钉死在失败态）。
        """
        results = [_round(
            1,
            [("processing_order_update", "issue"), ("processing_order_update", "complete")],
            [("processing_order_update", True, {"status": "issued"}),
             ("processing_order_update", False, {"error": "非法状态迁移"})],
        )]
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update", "action": "complete"}) is False

    def test_failed_declared_action_then_success_later(self):
        """声明 action 先失败、后成功 → 只在成功那轮停（被门禁挡回不算推进）。"""
        results = [
            _round(1, [("processing_order_update", "complete")],
                   [("processing_order_update", False, {"error": "缺少确认"})]),
            _round(2, [("processing_order_update", "complete")],
                   [("processing_order_update", True, {"status": "completed"})]),
        ]
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update", "action": "complete"}) is True

    def test_synthetic_round_without_results_keeps_unknown_fallback(self):
        """合成轨迹（无 tool_result）→ 保持「调用过即停」，但**必须先发起该 action**。"""
        results = [_round(1, [("processing_order_update", "complete")], [])]
        assert lr.repeat_stop_met(
            results, {"tool_called": "processing_order_update", "action": "complete"}) is True
        other = [_round(1, [("processing_order_update", "issue")], [])]
        assert lr.repeat_stop_met(
            other, {"tool_called": "processing_order_update", "action": "complete"}) is False

    def test_missing_tool_called_is_still_false(self):
        assert lr.repeat_stop_met(
            [{"tool_calls": [], "tool_results": []}], {"action": "complete"}) is False


# ── ② `output_verify` 的点号路径（issue #3667 / PG-016）────────────────────────

class TestOutputVerifyDottedPath:
    """`expect: {"result.status": "completed"}` —— 支持**点号路径**下钻嵌套产出。

    为什么需要：只认字面顶层 key 时，`result.status` 这类嵌套产出永远核不到
    （run 34822527203 实证假红），用例只能把断言收敛成扁平键 → 嵌套产出**失去核对能力**。
    """

    def _results(self):
        return [_round(
            1, [("processing_order_update", "complete")],
            [("processing_order_update", True,
              {"action": "complete", "result": {"status": "completed", "operator": "张三"}})],
        )]

    def test_nested_path_resolves_and_passes(self):
        issues = lr.check_output_verify(self._results(), [{
            "tool": "processing_order_update", "action": "complete",
            "expect": {"result.status": "completed"},
        }])
        assert issues == []

    def test_nested_path_mismatch_is_red_with_real_value(self):
        issues = lr.check_output_verify(self._results(), [{
            "tool": "processing_order_update", "action": "complete",
            "expect": {"result.status": "issued"},
        }])
        assert len(issues) == 1
        assert "result.status" in issues[0] and "issued" in issues[0]

    def test_nested_path_absent_is_red_not_silently_green(self):
        """路径不存在 → 报红（fail-closed），绝不静默跳过。"""
        issues = lr.check_output_verify(self._results(), [{
            "tool": "processing_order_update", "action": "complete",
            "expect": {"result.nope": "x"},
        }])
        assert len(issues) == 1 and "result.nope" in issues[0]

    def test_literal_key_wins_over_path(self):
        """兼容：payload 真有一个含点号的字面 key 时，字面 key 优先（不改既有语义）。"""
        results = [_round(
            1, [("t_multi", "")],
            [("t_multi", True, {"a.b": "literal", "a": {"b": "nested"}})],
        )]
        assert lr.check_output_verify(
            results, [{"tool": "t_multi", "expect": {"a.b": "literal"}}]) == []
        assert lr.check_output_verify(
            results, [{"tool": "t_multi", "expect": {"a.b": "nested"}}]) != []

    def test_top_level_key_still_works(self):
        """既有扁平键写法一字不改地照旧（防止点号支持改动误伤存量用例）。"""
        results = [_round(1, [("curtain_calc", "")],
                          [("curtain_calc", True, {"fabricMeters": 6.0})])]
        assert lr.check_output_verify(
            results, [{"tool": "curtain_calc", "expect": {"fabricMeters": 6.0}}]) == []
        assert lr.check_output_verify(
            results, [{"tool": "curtain_calc", "expect": {"fabricMeters": 9.0}}]) != []

    def test_numeric_tolerance_works_on_nested_path(self):
        issues = lr.check_output_verify(self._results(), [{
            "tool": "processing_order_update", "action": "complete",
            "expect": {"result.status": "completed"},
        }])
        assert issues == []


# ── ③ `_first_successful_payload` 的同轮作用域（issue #3667 / PP-006）──────────

class TestFirstSuccessfulPayloadSameRound:
    """同一轮里同名工具被调用多次（不同 action）→ 必须取**声明 action** 那个 payload。

    证据（PP-006 `merge_log`，run 34820346966）：首轮 create 被拒后**同轮**
    `list_categories` 恢复成功 → 取首个成功 payload 得到 `{'categories': [...]}` → 假红。
    """

    CRAETE = "create_processing_item"
    LIST = "list_categories"

    def _round(self):
        return _round(
            1,
            [("processing_item_manage", self.LIST), ("processing_item_manage", self.CRAETE)],
            [("processing_item_manage", True, {"categories": [{"id": 1, "name": "折边"}]}),
             ("processing_item_manage", True, {"id": 42, "name": "纳米圈打孔"})],
        )

    def test_picks_payload_of_declared_action(self):
        got = lr._first_successful_payload(
            [self._round()], "processing_item_manage", self.CRAETE)
        assert got == {"id": 42, "name": "纳米圈打孔"}

    def test_other_action_selector_still_picks_its_own(self):
        got = lr._first_successful_payload(
            [self._round()], "processing_item_manage", self.LIST)
        assert got == {"categories": [{"id": 1, "name": "折边"}]}

    def test_failed_declared_action_does_not_borrow_other_payload(self):
        """声明的 action 失败、同轮别的 action 成功 → 返回空（判红），不许借别人的 payload。

        这是「假绿」面：借用 `{'categories': [...]}` 后，若 expect 的键恰好撞上
        （如都叫 `items`），就会"核对了错的调用还说产出对"。
        """
        r = _round(
            1,
            [("processing_item_manage", self.CRAETE), ("processing_item_manage", self.LIST)],
            [("processing_item_manage", False, {"error": "加工分类不存在"}),
             ("processing_item_manage", True, {"name": "纳米圈打孔"})],
        )
        assert lr._first_successful_payload(
            [r], "processing_item_manage", self.CRAETE) == {}

    def test_second_round_is_used_when_first_round_action_failed(self):
        """跨轮语义不变：第一轮该 action 失败 → 继续找下一轮的成功 payload。"""
        results = [
            _round(1, [("processing_item_manage", self.CRAETE)],
                   [("processing_item_manage", False, {"error": "缺 category_id"})]),
            _round(2, [("processing_item_manage", self.CRAETE)],
                   [("processing_item_manage", True, {"id": 7})]),
        ]
        assert lr._first_successful_payload(
            results, "processing_item_manage", self.CRAETE) == {"id": 7}

    def test_unalignable_round_falls_back_to_first_success(self):
        """对不齐（结果数 ≠ 调用数，如合成轨迹）→ 回退旧的「首个成功」语义，不猜。"""
        r = {"__round": 1,
             "tool_calls": [{"name": "processing_item_manage",
                             "args": {"action": self.CRAETE}}],
             "tool_results": [
                 {"tool": "processing_item_manage",
                  "result": {"success": True, "data": {"id": 9}}}]}
        assert lr._first_successful_payload(
            [r], "processing_item_manage", self.CRAETE) == {"id": 9}

    def test_no_action_keeps_first_success(self):
        """不声明 action（单 action 工具）→ 旧语义原样。"""
        r = _round(1, [("curtain_calc", "")],
                   [("curtain_calc", True, {"fabricMeters": 6})])
        assert lr._first_successful_payload([r], "curtain_calc") == {"fabricMeters": 6}


# ── ④ `db_verify[processing_order]` 落库核对器契约（issue #3612 已落地，此处锁住）──

class TestProcessingOrderDbVerifyContract:
    """B 端加工单**落库**核对器的契约（能力已存在，本组防回归）。

    `output_verify` 只看工具**回显**的 payload；「改完真落库了吗」需要回读 admin-api
    （`GET /api/admin/processing-orders`）。本组锁住三件事：
      ① fetch 被正确分发（不被"不支持的配置"打回）；
      ② 配置写错（缺 checks / 无回读键）→ **报红**，绝不空转通过；
      ③ 谓词求值走**落库记录**（字段缺失与字段为空给不同报错）。
    """

    def _run(self, db_verify, results, fetcher):
        orig = lr._fetch_processing_order
        lr._fetch_processing_order = fetcher
        try:
            return asyncio.run(lr.check_db_verify("tok", db_verify, results))
        finally:
            lr._fetch_processing_order = orig

    def _results(self):
        return [_round(1, [("processing_order_update", "complete")],
                       [("processing_order_update", True,
                         {"processingOrderNo": "JG-2026-0001", "status": "completed"})])]

    def test_dispatch_is_supported(self):
        """fetch=processing_order 必须被分发（而非落入「不支持的 fetch 配置」）。"""
        async def _fake(token, ref="", keyword=""):
            return {"processingOrderNo": "JG-2026-0001", "status": "completed"}, ""

        issues = self._run(
            [{"fetch": "processing_order", "source": "processing_order_update",
              "action": "complete", "checks": ["status==completed"]}],
            self._results(), _fake)
        assert issues == []

    def test_missing_checks_is_a_config_error(self):
        issues = self._run(
            [{"fetch": "processing_order", "action": "complete", "checks": []}],
            self._results(), None)
        assert len(issues) == 1 and "checks" in issues[0]

    def test_no_readback_key_is_a_config_error(self):
        async def _fake(token, ref="", keyword=""):
            raise AssertionError("无回读键时不该发起查询")

        issues = self._run(
            [{"fetch": "processing_order", "action": "complete",
              "checks": ["status==completed"]}],
            [], _fake)
        assert len(issues) == 1 and "成功调用" in issues[0]

    def test_record_mismatch_is_red(self):
        async def _fake(token, ref="", keyword=""):
            return {"processingOrderNo": "JG-2026-0001", "status": "issued"}, ""

        issues = self._run(
            [{"fetch": "processing_order", "source": "processing_order_update",
              "action": "complete", "checks": ["status==completed"]}],
            self._results(), _fake)
        assert len(issues) == 1 and "落库字段 status" in issues[0]

    def test_record_not_found_is_red_not_skipped(self):
        async def _fake(token, ref="", keyword=""):
            return None, f"keyword={ref!r} 命中 0 条"

        issues = self._run(
            [{"fetch": "processing_order", "source": "processing_order_update",
              "action": "complete", "checks": ["status==completed"]}],
            self._results(), _fake)
        assert len(issues) == 1 and "查不到加工单" in issues[0]

    def test_dotted_record_path_is_supported(self):
        """落库谓词支持点号路径（`result.status` 形态的嵌套字段）。"""
        async def _fake(token, ref="", keyword=""):
            return {"processingOrderNo": "JG-2026-0001", "extra": {"status": "completed"}}, ""

        issues = self._run(
            [{"fetch": "processing_order", "source": "processing_order_update",
              "action": "complete", "checks": ["extra.status==completed"]}],
            self._results(), _fake)
        assert issues == []

    def test_fetcher_reads_back_by_processing_order_no(self):
        """回读键取自**声明 action** 的成功 payload（同轮取错会让回读定位到别的单据）。"""
        seen = {}

        async def _fake(token, ref="", keyword=""):
            seen["ref"] = ref
            return {"processingOrderNo": ref, "status": "completed"}, ""

        self._run(
            [{"fetch": "processing_order", "source": "processing_order_update",
              "action": "complete", "checks": ["status==completed"]}],
            self._results(), _fake)
        assert seen["ref"] == "JG-2026-0001"
