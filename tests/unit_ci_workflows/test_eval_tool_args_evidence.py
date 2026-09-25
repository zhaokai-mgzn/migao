# case_ids: KN-004
"""工具**入参**（args）的证据通道：**落盘** + 可被「**参数值相等**」级断言消费（issue #3823）。

## 病灶（一手取证，run 34907835734 的 mibao 腿，`purpose=debug`）

`PR-016` 本轮 `score=100%`、`completion.deterministic_failures=[]`：判据 1（卡顺序）与判据 3
（真落库）都能从产物闭合，**判据 2 只闭合了一半** —— 产物里只有
`post-deploy-eval-mibao/eval-summary-mibao.json`，用例条目仅 `{id, score, classification, pre_clean}`；
job log 的轨迹行对 `processing_item_query` **只打结果摘要**
（`data=processing_item_query(items=4 total=4 page=1 size=10 …)`），`applicable` 在 log 里 `grep -c`
**零命中**。⇒「该值 == 前一步分类确认得到的真实分类 ID」这条**值相等**级语义在产物与日志里都读不到，
只能退到自然语言 `data_checks`——按 `docs/testing/acceptance-protocol.md`，它不作机器证据。

## 改前：入参在哪一步被丢掉（逐字，四处）

| 环节 | 改前事实 |
|---|---|
| SSE 解析（内存） | `results[*].tool_calls[*].args` **在**（`check_required_args` / `check_forbidden_args` / `check_must_fail` 三个既有断言都读它）⇒ 缺口**不在采集** |
| `build_round_trace` | 入参**只在** `write_args` 里留（`_WRITE_TOOL_NAMES` ∪ `curtain_calc`）；其余工具（`processing_item_query` / `interact` / …）的 `args` 在这一步**被丢弃**，轨迹只剩工具名 |
| `format_round_trace` | `data=` 段是**结果**摘要（`_result_digest`），不是入参 ⇒ 日志里没有参数值 |
| `eval-summary*.json` | 用例条目不带轨迹也不带入参 ⇒ 离线复核**无从取数**（容器日志有保留期） |

## 本文件锁什么（**只加证据 + 一个只读校验函数**；不改任何既有判据、不放宽任何断言）

| # | 判据 | 形态 |
|---|---|---|
| ① | 入参通道落盘 | `round_trace[*].call_args` = `[{tool, args}]`，与 `write_args` **同键名同形状**；`write_args` 保持**写工具专属**的旧语义 ⇒ 两条**互不吞** |
| ② | 值级可读 | 判别性字段（`applicable_category_id` / `multiSelect` / `pageMeta.params.page`）按**值**取得到（不是"有就行"） |
| ③ | 日志可检索 | `format_round_trace` 打 `callargs=` 段。CI 的评测腿设 `AGENT_EVAL_TRACE_ALL=1` ⇒ **通过用例的轨迹也打**（该 env 的守卫已存在：`tests/unit_ci_workflows/test_schema_integrity.py`，本文件**不**重复实现同族守卫） |
| ④ | 值相等可断言 | `check_arg_values(round_trace, specs)`：**至少一次**调用的参数与期望**逐值相等**；比较复用既有 `_args_value_matches` 口径，**不另立第二套** |
| ⑤ | 失败关闭 | 轨迹**没有**入参通道 ⇒ **判违规**（不许"取不到就算过"，#3823 的形态）；配置写错（缺 tool / 空 values / dict 期望）同样判违规 |
| ⑥ | 只加不改 | 旧字段（`round/user/tools/results/cards/interactive/card_calls/write_args/text/error`）与**独立逐字副本**整字典相等；键集**恰好**是旧键集 ∪ `{call_args}` |

## 红证（每条都能红；回退修复或放宽口径 ⇒ 判据必红）

| 断言 | 红形态 |
|---|---|
| ① 通道落盘 | 回退 = 轨迹无 `call_args` 键 ⇒ `KeyError: 'call_args'` |
| ② 值级可读 | 回退/只记存在性 ⇒ 取到的值不等于 `7`（如实测的 R1 无 / R5 有形态会算成 `None`） |
| ③ 日志 | 回退 = `callargs=` 段不存在 ⇒ `not in` 命中 |
| ④ 值相等 | 回退 = 校验函数报「取不到参数值」⇒ 期望的 `== []` 不成立 |
| ⑤ 失败关闭 | 把"取不到"改成"放行" ⇒ 反向语料（无通道）会判成相等 ⇒ 断言 `len(issues) == 1` 红 |
| ⑥ 只加不改 | 顺手改了 `ok`/`digest`/`write_args` 任一 ⇒ 与逐字副本的整字典比对红；多出一个键同样红 |

## 为什么用单测而不是真实链路

真实链路要 docker 栈 + 真实 LLM（本机没有；PR 层真实 LLM 已按 #4034 裁定关闭）。
本改动是**纯序列化 + 一个只读校验函数**（`build_round_trace` → `format_round_trace` → `_summary_case`
的字段增补，外加 `check_arg_values` 消费那批字段），`run_case` 产出的 `results` 结构就是全部输入契约
（`migao-dev-flow` §16.1：能下层不上层）。**行为复核并入下一次全量档**（issue #3823 收口评论）。

⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（见 `.github/workflows/pr-check.yml`），而
`local_runner` 有模块级 `import httpx` ⇒ 用下方 `_load_runner()` 的最小替身
（与 `tests/unit_ci_workflows/test_eval_denial_trace_shape.py` 同形）。
"""
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，且一旦被调用即抛错）。"""
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


lr = _load_runner()

#: 本单新增的轨迹键（回归锚点用；改名即视为破坏"只加证据"的契约）。
NEW_TRACE_KEY = "call_args"


# ── fixtures ────────────────────────────────────────────────────────────────

def _call(tool, args):
    return {"name": tool, "args": args}


def _round(rnd, calls, results=(), text=""):
    """一轮 `results` 条目（`run_case` 的产出形状）。"""
    return {
        "__round": rnd,
        "tool_calls": list(calls),
        "tool_results": [{"tool": t, "result": r} for t, r in results],
        "final_text": text,
    }


#: PR-016 的实形（issue #3823 的一手取证）：R1 拉加工项目录**尚无分类**、R5 按已选分类过滤才带上。
#: `applicable_category_id` 本身已随 #4371（商品↔加工项解耦）退场 —— 本文件只用它作**语料值**，
#: 锁的是**通道**（值级证据能不能取到），不是那个字段的产品语义。
CORPUS = [
    _round(1, [_call("category_manage", {"action": "tree"})],
           [("category_manage", {"success": True, "data": {"tree": [1, 2]}})],
           text="已为您列出分类"),
    _round(5, [
        _call("processing_item_query", {"page": 1, "size": 10}),
        _call("processing_item_query", {"applicable_category_id": 7, "page": 1}),
        _call("interact", {"component": "choice", "title": "选择加工项",
                           "multiSelect": True, "pageMeta": {"params": {"page": 2}}}),
    ], [
        ("processing_item_query", {"success": True, "data": {"items": 4, "total": 4}}),
        ("processing_item_query", {"success": True, "data": {"items": 2}}),
        ("interact", {"success": True, "data": {"component": "choice"}}),
    ], text="请选择要加工的项"),
]

#: 「该工具的参数值 == 前一步得到的真实分类 ID 7」—— 值相等级断言的最小形态。
SPEC_VALUE = [{"tool": "processing_item_query",
               "values": {"applicable_category_id": 7}}]


def _trace():
    return lr.build_round_trace(CORPUS)


def _without_channel(trace):
    """把轨迹改回**改前形态**（剥掉入参通道）——失败关闭与判别力的注入夹具。"""
    return [{k: v for k, v in item.items() if k != NEW_TRACE_KEY} for item in trace]


def _legacy_build_round_trace(rounds):
    """issue #3823 **之前**的 `build_round_trace` 逐字副本（无 `call_args`）。

    刻意不复用 `build_round_trace`（否则两边同源 ⇒ 改了旧字段一起变 ⇒ 闸门失效）；
    只复用本单范围外的 helper（`_tool_result_status` / `_compact_write_args` / 掩码）。
    """
    trace = []
    for r in rounds or []:
        trace.append({
            "round": r.get("__round"),
            "user": str(r.get("user_message") or "")[:60],
            "tools": [str(tc.get("name", "")) for tc in (r.get("tool_calls") or [])],
            "results": lr._tool_result_status(
                r.get("tool_results") or [], r.get("tool_calls") or []),
            "cards": [str(c.get("type") or c.get("card_type") or "")
                      for c in (r.get("cards") or [])],
            "interactive": [str(iv.get("type") or iv.get("component") or "")
                            for iv in (r.get("interactive") or [])],
            "card_calls": [
                {"component": str((tc.get("args") or {}).get("component") or ""),
                 "title": str((tc.get("args") or {}).get("title") or "")[:24]}
                for tc in (r.get("tool_calls") or [])
                if str(tc.get("name", "")).lower() == "interact"
            ],
            "write_args": [
                {"tool": str(tc.get("name", "")),
                 "args": lr._compact_write_args(tc.get("args") or {})}
                for tc in (r.get("tool_calls") or [])
                if str(tc.get("name", "")).lower() in lr._WRITE_TOOL_NAMES
                or str(tc.get("name", "")).lower() == "curtain_calc"
            ],
            "text": (r.get("final_text") or "")[:60],
            "error": str(r.get("error"))[:120] if r.get("error") else None,
        })
    return trace


# ══════════════════════════════════════════════════════════════════════════════
# 一、入参通道落盘（**全工具**，不只写工具）—— 值级可读
# ══════════════════════════════════════════════════════════════════════════════

class TestCallArgsArePersisted:
    """`round_trace[*].call_args` 让**读/查类工具**的入参也成为证据（#3823 的取证盲区）。"""

    def test_read_tool_args_are_value_level_readable(self):
        """PR-016 实形：R1 无分类参数、R5 带 `applicable_category_id=7` —— 值本身必须读得到。"""
        trace = _trace()
        r5 = [c for c in trace[1][NEW_TRACE_KEY] if c["tool"] == "processing_item_query"]
        observed = [c["args"].get("applicable_category_id") for c in r5]
        assert observed == [None, 7], (
            f"入参必须按**值**落盘（R1 未带、R5 带 7，正是 #3823 的一手形态）：{observed}")
        # 红证：改前的轨迹**没有**该键 ⇒ 上面的表达式在回退后是 KeyError（红）。
        assert NEW_TRACE_KEY not in _legacy_build_round_trace(CORPUS)[1], (
            "夹具失效：改前的轨迹本就带 `call_args`，则本判据不是 #3823 的红证")

    def test_interact_discriminative_fields_are_readable(self):
        """`interact` 的 `multiSelect` / `pageMeta.params` 是判别性字段（issue 点名要求）。"""
        trace = _trace()
        card = [c for c in trace[1][NEW_TRACE_KEY] if c["tool"] == "interact"][0]
        assert card["args"]["multiSelect"] is True, card
        assert card["args"]["pageMeta"]["params"]["page"] == 2, card

    def test_channel_covers_every_tool_not_only_write_tools(self):
        """通道对所有调用**统一**（值级断言不必按写/读分两条口径）；`write_args` 旧语义不变。"""
        trace = _trace()
        assert [c["tool"] for c in trace[1][NEW_TRACE_KEY]] == \
            ["processing_item_query", "processing_item_query", "interact"]
        assert trace[1]["write_args"] == [], (
            "`write_args` 必须保持**写工具专属**（本轮的读工具不得混进去）")
        write_round = _round(2, [_call("order_create", {"items": [{"product_name": "窗帘",
                                                                  "quantity": 3}],
                                                  "customer_phone": "13800138000"})],
                             [("order_create", {"success": True, "data": {"order_id": "o1"}})])
        wtrace = lr.build_round_trace(CORPUS + [write_round])
        assert [w["tool"] for w in wtrace[2]["write_args"]] == ["order_create"]
        assert any(c["tool"] == "order_create" for c in wtrace[2][NEW_TRACE_KEY]), (
            "写工具也要在**通用**通道里（否则一条值级断言要按写/读查两个地方 = 第二套口径）")


# ══════════════════════════════════════════════════════════════════════════════
# 二、「参数值相等」级断言：消费落盘的轨迹（不是内存的 `results`）
# ══════════════════════════════════════════════════════════════════════════════

class TestArgValuesAssertion:
    """`check_arg_values(round_trace, specs)` —— 值级；证据取自**落盘**的轨迹。"""

    def test_expected_value_is_matched(self):
        """该值确实等于期望 ⇒ 无违规（这正是 #3320 判据 2 需要的那半格证据）。"""
        assert lr.check_arg_values(_trace(), SPEC_VALUE) == []

    def test_unequal_value_is_reported_with_round_and_expected(self):
        """值不等 ⇒ 违规，且报出**轮次 + 期望 + 实际**（值级红必须可归因，不许只说"不一致"）。"""
        issues = lr.check_arg_values(_trace(), [
            {"tool": "processing_item_query", "values": {"applicable_category_id": 8}}])
        assert len(issues) == 1, issues
        assert "applicable_category_id" in issues[0] and "8" in issues[0], issues
        assert "R5" in issues[0], f"必须指到**哪一轮**的调用：{issues[0]}"

    def test_action_can_scope_the_call(self):
        """可限定 `action`（与 required_args 同形）：作用域内命中、作用域外不命中。"""
        spec = [{"tool": "category_manage", "action": "tree", "values": {"action": "tree"}}]
        assert lr.check_arg_values(_trace(), spec) == []
        assert len(lr.check_arg_values(
            _trace(), [{"tool": "category_manage", "action": "create",
                        "values": {"action": "tree"}}])) == 1

    def test_nested_and_list_values_are_compared(self):
        """嵌套点分路径与列表都按值比对（复用既有容错口径：数字 str/int 混比）。"""
        trace = [
            _round(2, [_call("interact", {"multiSelect": True, "pageMeta": {"params": {"page": 2}},
                                          "selectedIndices": [0, 2]}),
                       _call("processing_item_query", {"applicable_category_id": "7"})]),
        ]
        built = lr.build_round_trace(trace)
        assert lr.check_arg_values(built, [
            {"tool": "interact", "values": {"multiSelect": True,
                                            "pageMeta.params.page": 2,
                                            "selectedIndices": [0, 2]}},
            {"tool": "processing_item_query", "values": {"applicable_category_id": 7}},
        ]) == []

    def test_all_declared_values_must_hold_in_one_call(self):
        """口径 = 「**同一次**调用满足全部声明值」（与 required_args 的调用选择器同源）。"""
        trace = [
            _round(1, [_call("processing_item_query", {"applicable_category_id": 7}),
                       _call("processing_item_query", {"page": 2})]),
        ]
        issues = lr.check_arg_values(lr.build_round_trace(trace), [
            {"tool": "processing_item_query",
             "values": {"applicable_category_id": 7, "page": 2}}])
        assert len(issues) == 1, issues


# ══════════════════════════════════════════════════════════════════════════════
# 三、失败关闭：**取不到入参**必须判违规（不许把判据放宽成"总有值"）
# ══════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    """「取不到」≠「相等」。证据通道缺失时必须**报违规**，且归因指向通道而非 agent。"""

    def test_missing_channel_is_a_violation_not_a_pass(self):
        """反向语料：改前形态（无 `call_args`）⇒ 断言**不得**判成相等。"""
        issues = lr.check_arg_values(_without_channel(_trace()), SPEC_VALUE)
        assert len(issues) == 1, issues
        assert NEW_TRACE_KEY in issues[0], (
            f"违规必须点名**缺的是入参通道**（否则会被读成 agent 没调工具）：{issues[0]}")

    def test_legacy_trace_reports_a_violation(self):
        """判别力自证：把「取不到 args」的形态喂给**同一**校验函数 ⇒ 必须报违规。"""
        legacy = _legacy_build_round_trace(CORPUS)
        assert NEW_TRACE_KEY not in legacy[1], (
            "夹具失效：注入的「改前形态」竟带新通道，则本判据不具判别力")
        assert len(lr.check_arg_values(legacy, SPEC_VALUE)) == 1

    def test_channel_present_but_value_absent_is_a_violation(self):
        """通道在、但该值**从未传过** ⇒ 违规（防把判据放宽成"总有值"）。"""
        trace = [_round(2, [_call("processing_item_query", {"page": 1})])]
        assert len(lr.check_arg_values(lr.build_round_trace(trace), SPEC_VALUE)) == 1

    def test_empty_trace_is_a_violation(self):
        """空轨迹同样判违规（不是空断言：没有证据 = 没有结论）。"""
        assert len(lr.check_arg_values([], SPEC_VALUE)) == 1

    def test_tool_never_called_is_reported_as_such(self):
        """通道在、但该工具没被调用 ⇒ 报「未调用」（与 required_args 同文案族，不混同于取不到）。"""
        trace = [_round(1, [_call("category_manage", {"action": "tree"})])]
        issues = lr.check_arg_values(lr.build_round_trace(trace), SPEC_VALUE)
        assert len(issues) == 1 and "未调用" in issues[0], issues

    def test_broken_spec_fails_closed(self):
        """配置写错（缺 tool / 空 values / dict 期望）⇒ 报违规，**不静默跳过**（#3367 同纪律）。"""
        trace = _trace()
        assert len(lr.check_arg_values(trace, [{"values": {"applicable_category_id": 7}}])) == 1
        assert len(lr.check_arg_values(trace, [{"tool": "processing_item_query"}])) == 1
        assert len(lr.check_arg_values(
            trace, [{"tool": "processing_item_query",
                     "values": {"pageMeta": {"params": {"page": 2}}}}])) == 1
        assert len(lr.check_arg_values(trace, ["not-a-dict"])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 四、日志通道：值进入 job log（`grep applicable` 从零命中变为可检索）
# ══════════════════════════════════════════════════════════════════════════════

class TestLogChannel:

    def test_render_is_deterministic_json_of_the_same_args(self):
        """渲染 = 与轨迹**同一份**压缩值的 JSON（同一真相源，不另写一套格式化）。"""
        assert lr._render_call_args(
            {"tool": "processing_item_query", "args": {"page": 1, "applicable_category_id": 7}}
        ) == 'processing_item_query{"applicable_category_id": 7, "page": 1}'

    def test_trace_line_carries_the_value(self):
        """端到端：`build_round_trace` → `format_round_trace` 的 `callargs=` 段带参数值。"""
        line = lr.format_round_trace(_trace())
        assert "callargs=" in line, line
        assert '"applicable_category_id": 7' in line, line
        assert "multiSelect" in line and "pageMeta" in line, line
        # 信息是**超集**：既有段（tools/data/ai/cardreq）一个不少
        assert "tools=" in line and "data=" in line, line

    def test_write_tools_keep_their_dedicated_segment(self):
        """写工具走既有 `args=` 段且**不**在 `callargs=` 重复打印（两条互不吞、日志不翻倍）。"""
        write_round = _round(1, [_call("order_create", {"items": [{"product_name": "窗帘",
                                                                   "quantity": 3}],
                                                   "customer_phone": "13800138000"})],
                             [("order_create", {"success": True, "data": {"order_id": "o1"}})])
        line = lr.format_round_trace(lr.build_round_trace([write_round]))
        assert "args=order_create{" in line, line
        assert "callargs=order_create" not in line, line
        # 非写工具仍然在 `callargs=` 段（同一轮里两类并行）
        mixed_round = _round(
            1,
            write_round["tool_calls"] + [_call("product_search", {"keyword": "窗帘"})],
            write_round["tool_results"] + [("product_search",
                                            {"success": True, "data": {"items": 2}})])
        mixed = lr.format_round_trace(lr.build_round_trace([mixed_round]))
        assert "args=order_create{" in mixed and "callargs=product_search{" in mixed, mixed


# ══════════════════════════════════════════════════════════════════════════════
# 五、压缩纪律：脱敏（手机号）/ 截断（自由文本）/ 有界（体积）+ 可序列化
# ══════════════════════════════════════════════════════════════════════════════

class TestCompaction:

    def test_phone_is_masked(self):
        """入参会进 CI 日志/产物 ⇒ 手机号按既有 `_FULL_PHONE_RE` 口径掩码（issue 的脱敏要求）。"""
        out = lr._compact_call_args({"customer_phone": "13800138000",
                                     "note": "打给 13900139000 确认"})
        assert out["customer_phone"] == "138****8000", out
        assert "13900139000" not in json.dumps(out, ensure_ascii=False), out

    def test_long_free_text_is_truncated(self):
        """自由文本截断（判别性字段是标量/短值，长文本只会把日志喂胖）。"""
        out = lr._compact_call_args({"keyword": "窗" * 100})
        assert len(out["keyword"]) <= lr._ARG_MAX_VALUE, out
        assert out["keyword"].startswith("窗" * 10), out

    def test_containers_are_bounded(self):
        """dict 键数 / 列表条数有界（轨迹是日志与产物，不是全量存档）。"""
        out = lr._compact_call_args({
            "big": {f"k{i}": i for i in range(50)},
            "many": list(range(50)),
        })
        assert len(out["big"]) <= lr._ARG_MAX_ITEMS, out
        assert len(out["many"]) <= lr._ARG_MAX_ITEMS + 1, out

    def test_discriminative_values_are_not_lost(self):
        """有界压缩**不得**吃掉判别性字段：数字/布尔/嵌套小对象原样可读。"""
        out = lr._compact_call_args({"applicable_category_id": 7, "multiSelect": True,
                                     "pageMeta": {"params": {"page": 2}},
                                     "items_count": 0, "flag_off": False})
        assert out["applicable_category_id"] == 7
        assert out["multiSelect"] is True
        assert out["pageMeta"]["params"]["page"] == 2
        assert out["items_count"] == 0 and out["flag_off"] is False

    def test_traces_and_summaries_are_json_serializable(self):
        """轨迹会进 artifact / flake 台账 ⇒ 必须可直接 JSON 序列化。"""
        trace = _trace()
        json.dumps(trace, ensure_ascii=False)
        assert json.loads(json.dumps(trace, ensure_ascii=False))[1][NEW_TRACE_KEY][1]["args"][
            "applicable_category_id"] == 7

    def test_non_dict_args_do_not_crash(self):
        """模型可能给出非 dict 入参（缺失/异常形态）⇒ 压缩按空对象处理，不抛。"""
        assert lr._compact_call_args(None) == {}
        assert lr._compact_call_args("oops") == {}


# ══════════════════════════════════════════════════════════════════════════════
# 六、产物通道：值级证据随 `eval-summary*.json` 落盘（绿用例也要有）
# ══════════════════════════════════════════════════════════════════════════════

class TestSummaryCarriesArgEvidence:

    def _result(self, **over):
        base = {"case_id": "KN-004", "score": 1.0, "classification": "",
                "failed": [], "pre_clean": [], "tool_calls": ["processing_item_query"]}
        base.update(over)
        return base

    def test_green_case_carries_args_in_the_artifact(self, tmp_path):
        """`score=1.0` 的用例同样落盘（#3823 的苦主正是一条 100% 的用例）。"""
        out = tmp_path / "eval-summary.json"
        lr.write_summary_json(str(out), "post-deploy", "", [self._result(round_trace=_trace())])
        entry = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert entry["score"] == 1.0
        got = [c for c in entry[NEW_TRACE_KEY] if c["tool"] == "processing_item_query"]
        assert [c["args"].get("applicable_category_id") for c in got] == [None, 7], entry

    def test_legacy_result_shape_stays_key_free(self, tmp_path):
        """不带轨迹的旧形态/合成夹具 ⇒ **不带**该键（"只加不改"的产物侧，逐字节不变）。"""
        out = tmp_path / "eval-summary.json"
        lr.write_summary_json(str(out), "post-deploy", "", [self._result()])
        entry = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert NEW_TRACE_KEY not in entry, entry


# ══════════════════════════════════════════════════════════════════════════════
# 七、**类级固化**（铁律 8）：三处通道必须覆盖**同一批**调用
# ══════════════════════════════════════════════════════════════════════════════

class TestChannelParityAcrossThreeFaces:
    """轨迹 / 日志 / artifact 三处通道**不得对任何一类工具做过滤**。

    为什么这是**类级**判据而不是实例判据：#3823 的病灶不是"少了一个字段"，而是
    **一整类**——"证据通道被选择性过滤"（`write_args` 只收写工具 ⇒ 读工具的入参在轨迹、
    日志、产物三处**都**消失，而报告里看不出区别）。只补 `call_args` 一个字段 = 只修了这一处；
    本类把"三处覆盖同一批调用"钉成清单式判据：任何一处再被过滤（加白名单/按工具名筛选/
    只记失败调用），**先红的是这里**。新增工具只需加进 `INVENTORY`（未登记即漏 ⇒ 红）。
    """

    #: 通道**不得**过滤的工具清单（读 / 写 / 卡 / 算料各一类）
    INVENTORY = ("processing_item_query", "product_search", "category_manage",
                 "employee_manage", "interact", "order_create", "curtain_calc")

    def _trace(self):
        return lr.build_round_trace(
            [_round(1, [_call(t, {"action": "list", "probe": t}) for t in self.INVENTORY])])

    def test_trace_covers_every_tool(self):
        assert [c["tool"] for c in self._trace()[0][NEW_TRACE_KEY]] == list(self.INVENTORY)

    def test_log_covers_every_tool(self):
        """日志并集（写工具的 `args=` 段 ∪ 其余工具的 `callargs=` 段）必须覆盖全部工具。"""
        line = lr.format_round_trace(self._trace())
        missing = [t for t in self.INVENTORY if f"{t}{{" not in line]
        assert missing == [], f"这些工具的入参在日志里取不到（通道被选择性过滤？）：{missing}"

    def test_artifact_covers_every_tool(self, tmp_path):
        out = tmp_path / "eval-summary.json"
        lr.write_summary_json(str(out), "post-deploy", "", [
            {"case_id": "KN-004", "score": 1.0, "classification": "", "failed": [],
             "pre_clean": [], "tool_calls": [], "round_trace": self._trace()},
        ])
        entry = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert [c["tool"] for c in entry[NEW_TRACE_KEY]] == list(self.INVENTORY)


# ══════════════════════════════════════════════════════════════════════════════
# 八、**只加证据**：旧字段逐字不变 + 键集恰好 +1（防止"顺手改了判定"）
# ══════════════════════════════════════════════════════════════════════════════

class TestOnlyEvidenceWasAdded:

    def test_legacy_round_fields_are_byte_identical(self):
        """逐轮比对：旧键必须与**独立逐字副本**整字典相等（含 `write_args` 的空列表口径）。"""
        new = _trace()
        old = _legacy_build_round_trace(CORPUS)
        legacy_view = [{k: v for k, v in item.items() if k != NEW_TRACE_KEY} for item in new]
        assert legacy_view == old, "旧字段被改动了（本单只许**加**证据）"

    def test_the_only_new_round_key_is_call_args(self):
        """键集**恰好**是旧键集 ∪ `{call_args}` —— 多一个键同样是口径变更。"""
        for i, item in enumerate(_trace()):
            assert set(item) == set(_legacy_build_round_trace(CORPUS)[i]) | {NEW_TRACE_KEY}, item

    def test_results_entries_are_untouched(self):
        """`results[*]` 的键集一字未动（`#4098` 的 `tool.error.code` 那批不因本单而变）。"""
        entry = _trace()[1]["results"][0]
        assert set(entry) == {"tool", "ok", "error", "error_code", "action", "digest"}, entry

    def test_value_level_comparison_reuses_the_existing_tolerance(self):
        """比较口径**复用** `must_fail.args` 的同一个函数（不另立第二套）。"""
        assert lr.check_arg_values(
            lr.build_round_trace([_round(1, [_call("processing_item_query",
                                                   {"applicable_category_id": "7"})])]),
            SPEC_VALUE) == [], "数字 str/int 混比必须与既有值级口径一致"

    def test_path_resolution_agrees_with_required_args(self):
        """点分路径与 `_check_required_field`（存在性）**机械钉等价**（同一批路径两边同判）。

        为什么必须钉：`required_args`（存在性）与 `check_arg_values`（值级）读的是同一批
        `args`、同一套路径口径 —— 两处各写一遍解析必然漂移（§17.3 的「同一真值两处投影」）。
        本判据只钉**两者本就该同判**的形态；两处**有意**分叉的边界另有专测钉住（见下一条）。
        """
        args = {"action": "list", "page": 1, "pageMeta": {"params": {"page": 2}},
                "items": [{"qty": 3}, {"qty": 5}]}
        for path in ("action", "page", "pageMeta.params.page", "items[].qty", "items.qty",
                     "missing", "missing.deep"):
            present, _detail = lr._check_required_field(args, path)
            assert bool(lr._arg_path_values(args, path)) is present, path

    def test_documented_boundaries_between_presence_and_value(self):
        """两条**有意**分叉（钉住，防被当 bug"顺手改"）：

        ① 空串/空列表：存在性算「缺」（`required_args` 要"非空"），值级算「取到了值」
           —— 值级必须能断言 `keyword: ""` 这种等值，否则"不要按关键词查"这类语义无法表达；
        ② `list[].x` 部分元素缺字段：存在性要求**全部**元素都带，值级只要求**任一**命中。
        """
        args = {"blank": "", "empty": [], "items": [{"qty": 3}, {}]}
        assert lr._check_required_field(args, "blank")[0] is False
        assert lr._arg_path_values(args, "blank") == [""]
        assert lr._check_required_field(args, "empty")[0] is False
        assert lr._arg_path_values(args, "empty") == [[]]
        assert lr._check_required_field(args, "items[].qty")[0] is False
        assert lr._arg_path_values(args, "items.qty") == [3]
        # 值级语义落地：任一次调用的 `items.qty == 3` 成立 ⇒ 命中（存在性口径不适用）
        assert lr.check_arg_values(
            lr.build_round_trace([_round(1, [_call("order_create", args)])]),
            [{"tool": "order_create", "values": {"items.qty": 3}}]) == []

    def test_over_long_call_lists_are_marked_not_silently_dropped(self):
        """调用数超上限时**标出来**（`(…+N more)`），不静默少报（同 `_result_digest` 纪律）。"""
        calls = [_call(f"tool_{i}", {"i": i}) for i in range(lr._ARG_LOG_MAX_CALLS + 2)]
        line = lr.format_round_trace(lr.build_round_trace([_round(1, calls)]))
        assert "more)" in line and "+2 more)" in line, line