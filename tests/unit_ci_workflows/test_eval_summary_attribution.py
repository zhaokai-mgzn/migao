# case_ids: MC-012
"""结论档 summary 的**失败可归因**层（issue #3708 / `migao-acceptance` v1.2 §治法 3）。

## 症状（实测代价）

结论档 `post-deploy-eval`（run 34841029062）的 `eval-summary-<persona>.json` 里，
**每个用例只有 4 个字段**，没有任何失败原因：

```json
{ "id": "PG-016", "score": 0.0, "classification": "reproducible", "pre_clean": [] }
```

顶层 `completion` 也只给一串 ID：`"确定性失败 6 条: AS-003, CR-001, OR-008, OR-015, PG-016, PP-007"`。
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
    """去掉本 PR 新增的两个字段（保序）→ 剩下的必须与改造前逐字节一致。"""
    out = {}
    for k, v in payload.items():
        if k == "cases":
            out[k] = [{kk: vv for kk, vv in c.items() if kk != NEW_CASE_KEY} for c in v]
        elif k == "completion":
            out[k] = {kk: vv for kk, vv in v.items() if kk != NEW_COMPLETION_KEY}
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
        """
        verdict = lr.completion_verdict(self._results(), (_journey_id(),))
        assert verdict == {
            "ok": False,
            "reason": f"确定性失败 1 条: PP-007；关键旅程失败 1 条: {_journey_id()}",
            "deterministic_failures": ["PP-007"],
            "journey_failures": [_journey_id()],
            "flake_released": ["OR-014"],
            "total": 4, "passed": 1,
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
