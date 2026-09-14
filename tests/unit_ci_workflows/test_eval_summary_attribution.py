# case_ids: MC-012
"""结论档 summary 的**失败可归因**层（issue #3708 / `migao-acceptance` v1.2 §治法 3）。

## 症状（实测代价）

结论档 `post-deploy-eval`（run 34841029062）的 `eval-summary-<persona>.json` 里，
**每个用例只有 4 个字段**，没有任何失败原因：

```json
{ "id": "PG-016", "score": 0.0, "classification": "reproducible", "pre_clean": [] }
```

顶层 `completion` 也只给一串 ID：`"确定性失败 6 条: AS-003, CR-001, OR-008, OR-015, PG-016, PP-007"`。
（该串是 run 34841029062 的**原始产物原文**；口径变更后文案为「必须处理的失败 N 条」。）
⇒ 要分类这 6 条（真回归 / 用例缺陷 / 种子环境）**只能手工挖 2705 行作业日志**
（`gh run view --job … --log | grep ❌`）；而 CI 日志有保留期，**过期后这批失败永久失去可归因性**。

而 runner 本来就在构造这些原因串（`case_issues.append("❌ …")` 一系 → `failed_expectations`），
**只是没有序列化进 summary**。这与 `migao-acceptance` v1.2 原文直接冲突：

> **失败可归因**（L1）：summary 带「case × 轮次 × 断言」级判定 —— 否则 `score=0` 无从定位。

## 本文件锁什么（四条验收判据）

1. **失败用例**：条目带 `failures`，内容是**断言级原文**（如
   `output_verify[...]: 结果里没有字段 'price'`），不需要再挖日志；
2. **通过用例**：条目**不带** `failures` 键（缺省，不是几十条空数组刷屏）—— **无噪音**；
3. **顶层**：`completion.failure_reasons` = `ID → 首要原因`（确定性失败 / 关键旅程 / 放行波动全含），
   与既有 `deterministic_failures`（ID 列表，已有消费者）**并存**；
4. **纯序列化**：`score` / `classification` / `completion.ok` 的算法**逐字不变**，
   除新增字段外 summary 与改造前**逐字节等价**（否则与历史 run 的对比失效）。

## 红证（每条断言都会红）

| 断言 | 红证 |
|---|---|
| ①② `failures` 带原因 / 通过缺省 | 改造前本文件必红（`KeyError: 'failures'`），TDD 实测见 PR 描述 |
| ③ `failure_reasons` 映射 | 同上（改造前 `completion` 无该键） |
| ④ **逐字节等价** | `_legacy_payload()` 是改造前 `write_summary_json` 的**独立逐字副本**（刻意不复用新 helper，否则两边同源、改了旧字段一起变，闸门失效）；且断言"新增字段确实存在"防止锚点退化成**空断言** |
| ④ `completion_verdict` 语义冻结 | 整字典 `==`（键集 + `reason` 原文 + 三个 ID 列表 + 计数），改一个字即红 |
| 端到端（无栈） | 先断言"故意写错的字段名**必须让真实 `output_verify` 判红**"，再断言该原因原样进了 summary —— 前置断言失败即说明本用例是空断言 |

## 为什么用单测而不是真实链路

真实链路需要 docker 栈 + 真实 LLM（本机没有，CI 的结论档又是半天级）。
本改动是**纯序列化**（`summary` 写入处的字段增补），不含任何行为/判定逻辑 ——
`local_runner` 的 `run_case` 产出的 `results` 结构就是全部输入契约，
故用"构造 results → 调写入函数 → 读 JSON"即可完整覆盖（`migao-dev-flow` §16.1：能下层不上层）。

⚠️ 本目录（`tests/unit_ci_workflows`）在 CI 只 `pip install pytest pyyaml`（见
`.github/workflows/pr-check.yml`），而 `local_runner` 有模块级 `import httpx`
→ 见下方 `_load_runner()` 的最小替身（与 `test_eval_runner_same_round_scope.py` 同形）。
"""
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身）。

    被锁的是**纯序列化**函数（吃 `results` 列表、写一个 JSON 文件），不该因缺一个
    HTTP 客户端而不可测。替身只在 httpx 真的缺失时注入，且一旦被调用即抛错 ——
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

# 本 PR 新增的两个字段名（回归锚点用；改名即视为破坏"只加字段"的契约）
NEW_CASE_KEY = "failures"
NEW_COMPLETION_KEY = "failure_reasons"
# #3761/#3769 追加的顶层新增字段（成本可读信号 + verdict ledger 键）。与前两个同款纪律 ——
# 只加不改，且必须真的存在（否则下面的"逐字节等价"会退化成**空断言**）。
NEW_COST_KEY = "cost"
NEW_RUN_KEY_KEY = "run_key"
NEW_TOP_KEYS = {NEW_COST_KEY, NEW_RUN_KEY_KEY}


# ── fixtures ────────────────────────────────────────────────────────────────

def _case(cid, score, classification="", failed=(), pre_clean=(), tool_calls=()):
    """一个用例结果（`run_case` 返回值里 summary 用到的字段）。"""
    return {"case_id": cid, "score": score, "classification": classification,
            "failed": list(failed), "pre_clean": list(pre_clean),
            "tool_calls": list(tool_calls)}


def _round(rnd, calls, results):
    """构造一轮 results 条目（与 `test_eval_runner_same_round_scope.py` 同形）。

    calls   : [(tool, action)]（action=None/"" 表示该调用不带 action 参数）
    results : [(tool, success, data)]
    """
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": ({**({"action": a} if a else {})})} for t, a in calls],
        "tool_results": [{"tool": t, "result": {"success": ok, "data": d}} for t, ok, d in results],
        "final_text": "",
    }


def _write(tmp_path, results, label="post-deploy"):
    out = tmp_path / "eval-summary.json"
    lr.write_summary_json(str(out), label, "", results)
    return json.loads(out.read_text(encoding="utf-8"))


def _legacy_payload(label, shard, results):
    """改造前 `write_summary_json` 的 payload 构造 —— **独立逐字副本**（issue #3708 回归锚点）。

    刻意不复用新实现里的任何 helper：锚点的价值在于"独立重新表述旧行为"，
    两边同源则改了旧字段两边一起变，闸门失效。
    `completion_verdict` 是**本次未改**的判定函数（另有语义冻结测试），故此处按原样调用。
    """
    def _declares_order_write(r) -> bool:
        return "order_create" in (r.get("tool_calls") or [])

    return {
        "label": label,
        "shard": shard or "",
        "total": len(results),
        "passed": sum(1 for r in results if r.get("score", 0) >= 1.0),
        "failed": sum(1 for r in results if r.get("score", 0) < 1.0),
        "avg_score": (sum(r.get("score", 0) for r in results) / len(results)) if results else 0.0,
        "order_write_cases": sum(1 for r in results if _declares_order_write(r)),
        "write_cases_ok": sum(1 for r in results
                              if _declares_order_write(r) and r.get("score", 0) >= 1.0),
        "cases": [
            {"id": r.get("case_id"), "score": r.get("score", 0),
             "classification": r.get("classification", ""),
             "pre_clean": r.get("pre_clean") or []}
            for r in results
        ],
        "completion": lr.completion_verdict(
            results, lr.KEY_JOURNEYS_XIAOBU if lr.PERSONA == "xiaobu" else lr.KEY_JOURNEYS_MIBAO),
    }


def _strip_new(payload):
    """去掉本 PR 新增的字段（保序）→ 剩下的必须与改造前逐字节一致。"""
    out = {}
    for k, v in payload.items():
        if k == "cases":
            out[k] = [{kk: vv for kk, vv in c.items() if kk != NEW_CASE_KEY} for c in v]
        elif k == "completion":
            out[k] = {kk: vv for kk, vv in v.items() if kk != NEW_COMPLETION_KEY}
        elif k in NEW_TOP_KEYS:
            continue          # #3761/#3769：顶层新增键，整体剥掉
        else:
            out[k] = v
    return out


def _dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _journey_id():
    """当前 persona 下的一条关键旅程 ID（避免测试依赖 PERSONA 默认值）。"""
    journeys = lr.KEY_JOURNEYS_XIAOBU if lr.PERSONA == "xiaobu" else lr.KEY_JOURNEYS_MIBAO
    return journeys[0]


# ── ① 失败用例必须带断言级原因 ───────────────────────────────────────────────

class TestFailedCaseCarriesReason:
    """`score=0` 的条目必须自带"为什么"（否则 summary 只是一份 ID 列表）。"""

    def test_case_level_assertion_reason_is_serialized(self, tmp_path):
        """case 级断言的原文（issue #3708 的 PP-007 形态）必须原样进 summary。"""
        reason = "output_verify[processing_item_manage]: 结果里没有字段 'price'（实际字段: ['name']）"
        data = _write(tmp_path, [
            _case("PP-007", 0.0, "reproducible", [(reason, "case-level check")])])
        entry = data["cases"][0]
        assert entry["id"] == "PP-007"
        assert entry["failures"] == [reason], (
            "失败用例未带出断言级原因 —— summary 又退回「一串 ID」，红了只能手工挖日志")

    def test_multiple_reasons_all_kept(self, tmp_path):
        """同一用例多条失败断言（如 required_args + must_succeed）全部保留，不折叠成一条。"""
        r1 = "required_args: 未调用 order_create(action=None)"
        r2 = "must_succeed: order_create 从未被调用"
        data = _write(tmp_path, [_case("OR-008", 0.0, "reproducible", [(r1, ""), (r2, "")])])
        assert data["cases"][0]["failures"] == [r1, r2]

    def test_expectation_failure_keeps_detail(self, tmp_path):
        """expectations 失败（无 `case_issues`）也要带原因 + 详情 —— 这才是"能定位"。"""
        data = _write(tmp_path, [
            _case("CR-001", 0.5, "llm-noise", [("tool: order_create", "工具未被调用（0 次）")])])
        assert data["cases"][0]["failures"] == ["tool: order_create → 工具未被调用（0 次）"]

    def test_passing_case_has_no_failures_noise(self, tmp_path):
        """通过用例**不带** `failures` 键 —— 不是空数组刷屏（缺省语义与空数组等价）。

        为什么要"缺省"而不是 `[]`：一个 shard 里几十条通过用例，每条挂一个 `"failures": []`
        就是纯噪音；缺省时 `jq` 侧 `(.failures // [])` 一样好写。
        """
        data = _write(tmp_path, [
            _case("OR-016", 1.0, "pass"),
            _case("PP-007", 0.0, "reproducible", [("断言原文", "case-level check")])])
        assert "failures" not in data["cases"][0], "通过用例挂了 failures 键 → 空数组刷屏"
        assert data["cases"][1]["failures"] == ["断言原文"]

    def test_no_empty_array_flood_across_summary(self, tmp_path):
        """整份 summary 里**不存在空 `failures` 数组**（刷屏的机器可判形态）。"""
        results = ([_case(f"OR-{i:03d}", 1.0, "pass") for i in range(1, 21)]
                   + [_case("PP-007", 0.0, "reproducible", [("唯一失败原因", "")])])
        data = _write(tmp_path, results)
        empties = [c["id"] for c in data["cases"]
                   if "failures" in c and not c["failures"]]
        assert empties == [], f"这些用例带了空 failures 数组: {empties}"
        assert sum(1 for c in data["cases"] if "failures" in c) == 1


# ── ② 端到端（无栈）：真实断言 → summary ─────────────────────────────────────

class TestRealAssertionReachesSummary:
    """不做假装的 fixture：用**真实** `output_verify` 判红，再喂给真实写入函数。

    这是"必然失败的用例 → summary 带出断言级原因"的**无栈版**：链路 = 断言函数 →
    `results.failed` → 序列化。缺的只有"agent 真的跑一轮"（需要 docker + LLM）。
    """

    def test_wrong_field_name_reason_lands_in_summary(self, tmp_path):
        results = [_round(
            2,
            [("processing_item_manage", "create_processing_item")],
            [("processing_item_manage", True, {"name": "刺绣工艺", "pricingMethod": "area"})],
        )]
        issues = lr.check_output_verify(results, [
            {"tool": "processing_item_manage", "action": "create_processing_item",
             "expect": {"price": 45}}])
        # 红证前置：故意写错的字段名必须判红，否则本用例是**空断言**（永远绿）
        assert issues, "红证失败：该输入必须让 output_verify 判红，否则本用例什么都没测"
        assert "结果里没有字段 'price'" in issues[0], f"原因原文不符: {issues[0]}"

        data = _write(tmp_path, [
            _case("PP-007", 0.0, "reproducible",
                  [(i, "case-level check") for i in issues])])
        failures = data["cases"][0]["failures"]
        assert failures == issues, "真实断言产出的原因未原样进 summary"
        assert "结果里没有字段 'price'" in failures[0]

    def test_exception_record_reason_is_serialized(self, tmp_path):
        """跑崩的用例（`classification=error`）同样要带原因 —— 它是最需要归因的一类。"""
        data = _write(tmp_path, [_case(
            "AS-003", 0.0, "error", [("EXCEPTION: RuntimeError('boom')", "case crashed")])])
        assert data["cases"][0]["failures"] == ["EXCEPTION: RuntimeError('boom') → case crashed"]


# ── ③ 顶层 completion：既有 ID 列表 + 新增 ID→首要原因 ───────────────────────

class TestCompletionCarriesReasons:
    """`completion` 让"哪些用例 + 为什么"一次读全，且**既有字段一个不少**。"""

    def _results(self):
        return [
            _case("PP-007", 0.0, "reproducible",
                  [("output_verify[processing_item_manage]: 结果里没有字段 'price'", "case-level check"),
                   ("amount_verify: 总额不符", "")]),
            _case(_journey_id(), 0.0, "reproducible", [("关键旅程断言原文", "")]),
            _case("OR-014", 0.5, "llm-noise", [("波动断言原文", "")]),
            _case("KN-001", 1.0, "pass"),
        ]

    def test_reason_map_covers_every_failed_bucket(self, tmp_path):
        c = _write(tmp_path, self._results())["completion"]
        # 既有字段（历史消费者）必须仍在，且语义不变
        assert c["deterministic_failures"] == ["PP-007"]
        assert c["journey_failures"] == [_journey_id()]
        assert c["flake_released"] == ["OR-014"]
        assert c["ok"] is False and c["total"] == 4 and c["passed"] == 1
        # 新增映射：三个失败桶**全部**有原因（否则"哪些用例"读全了，"为什么"仍有空缺）
        assert set(c["failure_reasons"]) == {"PP-007", _journey_id(), "OR-014"}
        assert c["failure_reasons"]["PP-007"].startswith(
            "output_verify[processing_item_manage]: 结果里没有字段 'price'")
        assert c["failure_reasons"][_journey_id()] == "关键旅程断言原文"
        assert c["failure_reasons"]["OR-014"] == "波动断言原文"

    def test_reason_map_empty_when_all_pass(self, tmp_path):
        c = _write(tmp_path, [_case("OR-016", 1.0, "pass")])["completion"]
        assert c["ok"] is True
        assert c["failure_reasons"] == {}

    def test_reason_map_serializable_when_no_results(self, tmp_path):
        """零用例（环境/登录失败）也要能落盘，不让新增字段把汇总写崩（非致命路径）。"""
        data = _write(tmp_path, [])
        assert data["completion"]["ok"] is False
        assert data["completion"]["failure_reasons"] == {}

    def test_completion_verdict_semantics_frozen(self):
        """判定算法**逐字不变**（键集 + reason 原文 + 三个 ID 列表 + 计数）——改一字即红。

        为什么单独锁：`failure_reasons` 是**附加**字段，绝不能变成"顺手改判定口径"的入口
        （改了口径，历史 run 与本 run 就不可比了）。

        ⚠️ 本次**有意**改了两处口径，均在此处显式留痕（不是"顺手"）：
          ① `reason` 文案「确定性失败 N 条」→「必须处理的失败 N 条」——桶里现在也含
             `unstable`，"确定性"这个词已不准确；
          ② `unstable`（两次皆败但成因不同）移出放行档（`_COMPLETION_RELEASED_CLASSES`
             只剩 `llm-noise`）—— 见下方第二段断言（旧口径会把 OR-014 放进
             `flake_released`，新口径必须进 `deterministic_failures`）。
        """
        verdict = lr.completion_verdict(self._results(), (_journey_id(),))
        assert verdict == {
            "ok": False,
            "reason": f"必须处理的失败 1 条: PP-007；关键旅程失败 1 条: {_journey_id()}",
            "deterministic_failures": ["PP-007"],
            "journey_failures": [_journey_id()],
            "flake_released": ["OR-014"],
            "total": 4, "passed": 1,
        }
        # ② 口径锚点：同样是"两次皆败"，`unstable` 必须进阻塞桶（旧口径会放行）
        unstable = lr.completion_verdict(
            [_case("OR-014", 0.0, "unstable", [("断言原文", "")])], (_journey_id(),))
        assert unstable == {
            "ok": False,
            "reason": "必须处理的失败 1 条: OR-014",
            "deterministic_failures": ["OR-014"],
            "journey_failures": [],
            "flake_released": [],
            "total": 1, "passed": 0,
        }


# ── ④ 回归锚点：除新增字段外逐字节等价 ───────────────────────────────────────

class TestLegacyBytesUnchanged:
    """`summary` 是跨 job 传递的通道（`report` job 解析它组装 issue）→ **只加字段**。

    判据不是"看起来差不多"，而是同一组输入喂「改造前副本」与「新实现」，
    删掉新增字段后**序列化字符串完全相等**（`json.dumps` 字符串相等 = 键顺序也相等）。
    """

    def _results(self):
        return [
            _case("CH-010", 1.0, "pass", pre_clean=["已清理长期记忆"],
                  tool_calls=["product_search", "order_create"]),
            _case("OR-017", 0.0, "reproducible",
                  [("output_verify[curtain_calc]: 用布量 期望 6.4，实际 5.2", "case-level check")],
                  pre_clean=["商品去重完成", "⚠️ pre_clean 失败: 超时"],
                  tool_calls=["order_create"]),
            _case(_journey_id(), 0.75, "llm-noise", [("关键旅程断言原文", "详情")]),
            _case("KN-001", 1.0, "pass", tool_calls=["knowledge_search"]),
        ]

    def test_only_new_fields_added(self, tmp_path):
        results = self._results()
        new = _write(tmp_path, results)
        legacy = _legacy_payload("post-deploy", "", results)
        # 红证前置：新增字段必须真的存在，否则下面的"等价"是**空断言**
        assert NEW_CASE_KEY in new["cases"][1], "新增字段缺失 → 本锚点什么都没证明"
        assert NEW_COMPLETION_KEY in new["completion"], "新增字段缺失 → 本锚点什么都没证明"
        assert NEW_COST_KEY in new, "新增字段缺失 → 本锚点什么都没证明"
        assert NEW_RUN_KEY_KEY in new, "新增字段缺失 → 本锚点什么都没证明"
        assert _dump(_strip_new(new)) == _dump(legacy), (
            "除新增字段外 summary 变了（既有字段/键顺序被改动）—— "
            "与历史 run 的对比会失效，且 report job 等消费者可能受影响")

    def test_only_new_fields_added_for_empty_results(self, tmp_path):
        new = _write(tmp_path, [])
        assert _dump(_strip_new(new)) == _dump(_legacy_payload("post-deploy", "", []))

    def test_legacy_case_keys_kept(self, tmp_path):
        """逐字段点名（比整串相等更早、更明确地报出"哪个既有字段没了"）。"""
        data = _write(tmp_path, self._results())
        assert [c["id"] for c in data["cases"]] == ["CH-010", "OR-017", _journey_id(), "KN-001"]
        assert data["cases"][1]["pre_clean"] == ["商品去重完成", "⚠️ pre_clean 失败: 超时"]
        assert data["order_write_cases"] == 2 and data["write_cases_ok"] == 1
        assert data["avg_score"] == (1.0 + 0.0 + 0.75 + 1.0) / 4


# ── ⑤ 成本可见化（#3761）：`cost` 块必须**来自实测**，缺数据时不得编 ──────────

class TestCostBlockIsMeasuredNotFabricated:
    """评测成本只有可读才可管理；而"字段在、值恒空"是一种**伪装**（空断言）。

    故这里两条一起锁：
      ① 有实测输入 ⇒ `cost` 如实反映（墙钟 / 用例耗时 / 平均 / 最慢 / 重试）；
      ② 无实测输入 ⇒ **如实为空**（`cases == {}`、`avg_case_s is None`、`tokens is None`），
         绝不用 0 或估算值冒充 —— `tokens` 拿不到就必须是 null + 写明原因（不编数字）。
    """

    def test_cost_reflects_measured_timings(self, tmp_path):
        results = [
            _case("CH-010", 1.0, "pass"),
            _case("OR-017", 0.0, "reproducible", [("断言原文", "")]),
            _case("KN-001", 1.0, "pass"),
        ]
        results[0]["duration_s"] = 12.5
        results[1]["duration_s"] = 41.0
        results[2]["duration_s"] = 6.5
        results[1]["retried"] = True
        out = tmp_path / "s.json"
        lr.write_summary_json(str(out), "post-deploy", "", results, elapsed_s=123.4)
        cost = json.loads(out.read_text(encoding="utf-8"))["cost"]

        assert cost["wall_clock_s"] == 123.4, "注入的墙钟没进 summary（cost 与实际脱节）"
        assert cost["cases"] == {"CH-010": 12.5, "OR-017": 41.0, "KN-001": 6.5}
        assert cost["avg_case_s"] == round((12.5 + 41.0 + 6.5) / 3, 1)
        assert cost["slowest_cases"][0] == ["OR-017", 41.0], "最慢用例排序不对（成本归因入口失效）"
        assert cost["retried_cases"] == ["OR-017"], "重试用例没被记下（重试=成本翻倍的来源）"

    def test_tokens_is_null_with_reason(self, tmp_path):
        """token 用量 runner 侧不可得 ⇒ 必须 null + 写明原因，不许编一个 0。"""
        cost = _write(tmp_path, [_case("CH-010", 1.0, "pass")])["cost"]
        assert cost["tokens"] is None, "runner 拿不到 token 却给了值 —— 编数字"
        assert cost["tokens_note"], "tokens=null 却没写原因（下一个人会把它读成「零 token」）"

    def test_cost_is_empty_not_zero_when_nothing_measured(self, tmp_path):
        """没有任何耗时输入时，`cost` 必须**如实为空**（空断言的反面）。"""
        cost = _write(tmp_path, [_case("CH-010", 1.0, "pass")])["cost"]
        assert cost["cases"] == {}
        assert cost["avg_case_s"] is None
        assert cost["slowest_cases"] == []
        assert cost["retried_cases"] == []
        assert cost["wall_clock_s"] is None, "未注入墙钟却给了值 —— 说明是算出来的假数"

    def test_runner_actually_records_and_passes_timings(self):
        """静态防"字段在但永远为空"：runner 必须真的记用例耗时并把墙钟传进来。"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert 'r["duration_s"] = round(time.monotonic() - _t0, 1)' in src, \
            "`_run_one_case` 没记用例耗时 —— cost.cases 会永远是空字典（假功能）"
        assert "elapsed_s=time.monotonic() - _run_t0" in src, \
            "main 没把墙钟传给 write_summary_json —— cost.wall_clock_s 永远是 None"


# ── ⑥ 放行波动必须**列出来**（issue #3781）：`flake_released` 曾是恒空死字段 ──────
#
# 真实 run 34856561459 的产物原文（本用例的夹具就是照它构造的）：
#   · mibao `eval-summary-mibao.json`：`cases` 分类 `pass 67 / reproducible 5 /
#     llm-noise 6`；`agent-eval-flakes.json` 里 `released=True` 6 条
#     （PG-016 / OR-010 / OR-016 / PR-007 / PP-001 / PR-005）；
#   · **但** `completion.flake_released == []`；xiaobu 同形（1 条 llm-noise → `[]`）。
# 根因：放行档的语义前提是"重试**通过**" ⇒ 该用例最终 `score == 1.0`，而旧判定的断言序是
# 「`score >= 1.0` → `continue`」在前 ⇒ 放行条目永远走不到记录那一句。
#
# ⚠️ 这里**不是**改放行政策（政策仍由 `_COMPLETION_RELEASED_CLASSES` 表达，只放行
# `llm-noise`），改的是**报告口径**：台账说放行了 6 条，结论摘要就不能说 0 条。

class TestReleasedFlakesAreListed:
    # run 34856561459 的台账 `released=True` 6 条。**注意** `OR-016` 同时也在
    # `KEY_JOURNEYS_MIBAO` 里 —— 它在该 run 是「重试通过 ⇒ score=1.0」，因此**没有**
    # 触发旅程拦截（旅程拦截只对 `score<1` 生效）；而真正失败的旅程是 `HR-003`。
    # 本夹具照这个真实形态构造：失败旅程（HR-003）与放行条目（其余 5 条）**不相交**；
    # 「旅程用例失败 + 分类命中放行档 ⇒ 不许放行」由 `test_completion_verdict.py`
    # 的 `test_journey_failure_blocks_even_llm_noise` 单独锁（两者判据不同，别混）。
    RELEASED = ["PG-016", "OR-010", "PR-007", "PP-001", "PR-005"]
    FAILED_JOURNEY = "HR-003"

    def _real_run_shape(self, journey_id):
        """照 run 34856561459 的形状构造 results（放行条目 = score 1.0 + 标记）。"""
        released = []
        for cid in self.RELEASED:
            c = _case(cid, 1.0, "llm-noise", pre_clean=["重试前置复位: …"])
            c["flake_released"] = True          # = run_case 在「首败+重试通过」处打的标记
            released.append(c)
        return released + [
            _case(self.FAILED_JOURNEY, 0.0, "reproducible",
                  [("关键旅程断言原文", "case-level check")]),
            _case("PP-007", 0.0, "reproducible", [("output_verify[…]: 结果里没有字段 'price'", "")]),
        ]

    def test_summary_lists_the_released_flakes(self, tmp_path):
        """顶层 `completion.flake_released` 必须列出放行条目（且**不放宽** ok 判定）。"""
        journey = _journey_id()
        data = _write(tmp_path, self._real_run_shape(journey))
        c = data["completion"]
        assert sorted(c["flake_released"]) == sorted(self.RELEASED), (
            f"放行条目没被列出（旧 bug：恒空）：{c['flake_released']}")
        assert c["ok"] is False, "关键旅程失败 + 确定性失败仍在 ⇒ ok 必须为 false（未放宽）"
        assert self.FAILED_JOURNEY in c["journey_failures"]
        assert "PP-007" in c["deterministic_failures"]
        # 逐条留痕：`failure_reasons` 要覆盖放行条目（"为什么放行"不含空缺）
        assert set(c["failure_reasons"]) >= set(self.RELEASED)

    def test_case_entry_marks_the_released_flake(self, tmp_path):
        """条目级也留痕（`flake_released: true`）—— 顶层只有 ID，条目给出 score/分类。"""
        data = _write(tmp_path, self._real_run_shape(_journey_id()))
        by_id = {x["id"]: x for x in data["cases"]}
        for cid in self.RELEASED:
            assert by_id[cid].get("flake_released") is True, (
                f"{cid} 是放行波动，条目里没有标记（归因时读不出「为什么它没算失败」）")
            assert by_id[cid]["score"] == 1.0 and by_id[cid]["classification"] == "llm-noise"
        # 非放行条目**不带**该键（不给几十条通过用例刷屏）
        assert "flake_released" not in by_id["PP-007"]

    def test_legacy_guard_drops_them_red_proof(self, tmp_path):
        """**红证**：把判定循环还原成**改造前**写法 ⇒ 同一份输入下列表为空。

        刻意**不复用**新实现（复用会让两边同源、一起变，红证失效）：这里保留旧算法的
        独立副本，与新实现的输出对比 —— "改前 0 条 / 改后 6 条"。
        """
        results = self._real_run_shape(_journey_id())
        legacy = []
        for r in results:
            if r.get("score", 0) >= 1.0:
                continue                      # ← 改造前的第一句（放行条目在这里被丢掉）
            if str(r.get("classification") or "") in lr._COMPLETION_RELEASED_CLASSES:
                legacy.append(r["case_id"])
        assert legacy == [], "旧算法不该列出任何放行条目 —— 这正是要修的 bug"
        assert sorted(lr.completion_verdict(results, (_journey_id(),))["flake_released"]) \
            == sorted(self.RELEASED)

    def test_runner_actually_sets_the_marker(self):
        """静态防"字段在但永远不赋值"（假功能）：runner 必须在放行那刻打标记。"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert 'r["flake_released"] = True' in src, (
            "runner 没有在「首败 + 重试通过」处打 flake_released 标记 —— "
            "completion.flake_released 会重新变成恒空字段")
