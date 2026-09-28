# case_ids: OR-014
"""加工项明细的**字段级证据**：证据通道到达 `processingItems` + 值级断言接线（issue #3789）。

## 病灶（issue #3789 的验收判据 2，原文）

> 给 `processing_info.processingItems` 加机械可判断言…… 当前 `args=order_create{…}` 只是
> runner 的**摘要形态**，不展开该字段，成功 run 又不采集容器日志 ⇒ 这一条现在**没有**
> 字段级证据。

机制（本文件把它钉成可复算的事实）：轨迹的入参证据通道 `round_trace[*].call_args` 由
`_compact_call_args` 做**有界压缩**，深度上限旧值 = 3：

```
args["items"]                    → _arg_value(items, 3)     # list，深度 3
  └ item (dict)                  → _arg_value(item, 2)
      └ processing_info (dict)    → _arg_value(pinfo, 1)
          └ processingItems (list) → _arg_value(list, 0)   ⇒ "<list 1>"   ← 条目**整层丢失**
```

⇒ `items[].processing_info.processingItems[].{id,name,quantity,unit}` 在轨迹与 artifact 里
**一个字段都读不到**；而「数量 = 面料米数」此前只写在自然语义 `data_checks` 里
（按 `docs/testing/acceptance-protocol.md`，纯散文**不计分** ⇒ 不是断言）。

## 本文件锁什么（三层，全部零 LLM、零栈、零网络）

① **通道**：深度上限必须够到 `processingItems[]` 的**条目**（`_ARG_MAX_DEPTH = 5`），
   且截断**可见**（超 `_ARG_MAX_ITEMS` 时有 `…+N` 标记，不静默少报）；
② **值级可判**：`check_arg_values` 在**落盘**的 `call_args` 上判「数量 == 3」；
   回退到旧深度 ⇒ 同一断言**取不到值**（判违规，不是放行）；
③ **用例声明**：`OR-014` 真的声明了 `required_args`（四键逐项存在性）+ `arg_values`（数量 3），
   且原**散文**条目已由机器判据取代（散文形态 `is_machine_scored_data_check` = False，
   这就是它此前不是断言的原因）。

## 红证

| 断言 | 红形态（注入/回退） |
|---|---|
| ① 深度够到条目 | 把 `_ARG_MAX_DEPTH` 回退成 3 ⇒ `_arg_path_values` 取不到条目字段 ⇒ 必红 |
| ② 值级判红 | 数量改成 1（密度推导形态）⇒ `arg_value(order_create,…quantity)` 违规 |
| ③ 声明面接线 | 删掉用例里的 `arg_values` / 拿掉 loader 映射 ⇒ 必红（后者由 PROBES 守卫同族覆盖） |
"""
import json
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(REPO_ROOT / ".github"))

import local_runner as lr  # noqa: E402
import assertion_taxonomy as tax  # noqa: E402


#: 一次**成功**下单的入参（与 `order_create` 工具契约同形：`items[].processing_info.*`）
ORDER_ARGS = {"items": [{
    "product_name": "遮光窗帘", "quantity": 3, "unit_price": 168, "subtotal": 504,
    "processing_info": {
        "colorName": "米白",
        "processingItems": [{"id": "pi_punch", "name": "打孔", "quantity": 3, "unit": "米"}],
    },
}]}

QTY_PATH = "items[].processing_info.processingItems[].quantity"
ID_PATH = "items[].processing_info.processingItems[].id"
UNIT_PATH = "items[].processing_info.processingItems[].unit"


def _results(args: dict = None, *, rounds: int = 1) -> list:
    """逐轮结果（只保留本判据要用的三个键：轮次 / 调用 / 结果）。"""
    out = []
    for i in range(1, rounds + 1):
        calls = ([{"name": "order_create", "args": dict(args)}]
                 if (args is not None and i == rounds) else [])
        out.append({"__round": i, "tool_calls": calls, "final_text": "",
                    "tool_results": [{"name": "order_create", "success": True}]})
    return out


def _pre_fix_compaction(args: dict) -> dict:
    """**回放修复前**的压缩规则（深度上限 3），用**现成**的 `_arg_value` 逐值复算。

    不另写一套压缩实现：只把旧上限代进去，保证"回放的是同一条规则的不同参数"，
    而不是我手写的近似（`migao-dev-flow` §23.6：红证机具本身也要能被核对）。
    """
    return {str(k): lr._arg_value(v, 3) for k, v in args.items()}


class TestEvidenceChannelReachesProcessingItems:
    """① 通道：入参证据必须**到达加工项条目**（否则字段级断言无从取证）。"""

    def test_call_args_carries_every_processing_item_field(self):
        trace = lr.build_round_trace(_results(ORDER_ARGS))
        call = next(c for r in trace for c in r["call_args"]
                    if c["tool"] == "order_create")
        got = call["args"]
        assert lr._arg_path_values(got, QTY_PATH) == [3], (
            f"加工项数量读不到（深度不足/被压成摘要）：{got!r}")
        assert lr._arg_path_values(got, ID_PATH) == ["pi_punch"], got
        assert lr._arg_path_values(got, UNIT_PATH) == ["米"], got

    def test_pre_fix_depth_loses_the_whole_processing_item_layer(self):
        """**红证①（回放）**：旧深度上限 3 下这一层是 `"<list 1>"` —— 条目一个字段都读不到。

        这条同时是「args 只是**摘要形态**」这句话的可执行版本。
        """
        old = _pre_fix_compaction(ORDER_ARGS)
        assert lr._arg_path_values(old, QTY_PATH) == [], (
            f"旧深度下竟然还能读到数量（本红证的前提不成立）：{old!r}")
        assert lr._arg_path_values(old, "items[].processing_info.processingItems") == [
            "<list 1>"], f"旧形态不是「<list N>」占位：{old!r}"

    def test_depth_constant_is_pinned_by_the_property_not_the_number(self):
        """深度上限只由**可达性**约束（改值可以，读不到加工项条目就是红）。"""
        trace = lr.build_round_trace(_results(ORDER_ARGS))
        assert lr._arg_path_values(trace[-1]["call_args"][0]["args"], QTY_PATH) == [3]
        assert lr._ARG_MAX_DEPTH >= 5, (
            f"深度上限被调回 {lr._ARG_MAX_DEPTH} ⇒ 加工项条目又读不到了（#3789 的机制复发）")

    def test_truncation_is_visible_not_silent(self):
        """有界 ≠ 静默少报：超 `_ARG_MAX_ITEMS` 的加工项列表必须带 `…+N` 标记。"""
        many = [{"id": f"pi_{i}", "name": f"工序{i}", "quantity": 3, "unit": "米"}
                for i in range(lr._ARG_MAX_ITEMS + 2)]
        args = {"items": [{"processing_info": {"processingItems": many}}]}
        got = lr.build_round_trace(_results(args))[-1]["call_args"][0]["args"]
        items = lr._arg_path_values(got, "items[].processing_info.processingItems")[0]
        assert isinstance(items, list), items
        assert items[-1] == f"{lr._ARG_TRUNCATED}+2", items
        assert len(items) == lr._ARG_MAX_ITEMS + 1, len(items)


class TestValueLevelSemantics:
    """② 值级：`arg_values` 必须在落盘通道上判「数量 == 面料米数」。"""

    SPEC = [{"tool": "order_create", "values": {QTY_PATH: 3}}]

    def test_quantity_equal_to_fabric_meters_passes(self):
        trace = lr.build_round_trace(_results(ORDER_ARGS))
        assert lr.check_arg_values(trace, self.SPEC) == []

    def test_density_derived_quantity_is_red(self):
        """**红证②**：数量不是面料米数（densely-derived 形态：每米 2 个 ⇒ 6）⇒ 判红。"""
        args = json.loads(json.dumps(ORDER_ARGS))
        args["items"][0]["processing_info"]["processingItems"][0]["quantity"] = 6
        issues = lr.check_arg_values(lr.build_round_trace(_results(args)), self.SPEC)
        assert len(issues) == 1 and "期望 3" in issues[0], issues

    def test_pre_fix_evidence_makes_the_same_assertion_red(self):
        """**红证①的判定面**：即便用例声明了值级断言，**旧证据通道**下它取不到值 ⇒ 判违规。

        ⇒ 「回退深度上限」与「断言失效」是同一件事的两面（不许把"取不到证据"读成"相等"）。
        """
        trace = [{"round": 1, "call_args": [
            {"tool": "order_create", "args": _pre_fix_compaction(ORDER_ARGS)}]}]
        issues = lr.check_arg_values(trace, self.SPEC)
        assert len(issues) == 1 and "未传该参数" in issues[0], issues

    def test_missing_evidence_channel_fails_closed(self):
        """轨迹里没有 `call_args` 通道（改前形态/未接线）⇒ 判违规，**不得**按相等放行。"""
        issues = lr.check_arg_values([{"round": 1}], self.SPEC)
        assert len(issues) == 1 and "没有**逐调用入参通道" in issues[0].replace("**", "**"), issues

    def test_never_called_is_red(self):
        issues = lr.check_arg_values(
            lr.build_round_trace(_results(None)), self.SPEC)
        assert len(issues) == 1 and "未调用" in issues[0], issues

    def test_failure_atom_separates_value_from_existence(self):
        """指纹：值级违规与存在性违规必须**分属不同原子**（两种根因）。"""
        atom = lr._failure_atom(
            f"arg_values[order_create.{QTY_PATH}](R4): 期望 3，实际 [6]",
            lr._CASE_LEVEL_DETAIL)
        assert atom == f"arg_value(order_create,{QTY_PATH})", atom
        assert atom != lr._failure_atom(
            f"required_args[order_create.{QTY_PATH}](R4): 缺失或为空: {QTY_PATH}",
            lr._CASE_LEVEL_DETAIL)


class TestOr014DeclaresMachineScorableAssertions:
    """③ 用例声明面：OR-014 的加工项口径必须是**机器可判**的，且散文条目已被取代。"""

    PROSE = ("processing_info.processingItems 逐项含 `{id, name, quantity, unit}` —— "
             "`unitPrice` / `pricingMethod` / `subtotal` 三键已随 issue #4882 退场"
             "（订单快照不再承载加工项价与计价方式）")

    def _case(self):
        cases = {c.id: c for c in lr.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))}
        case = cases.get("OR-014")
        if case is None:
            pytest.fail("OR-014 不在用例库（本判据的前提不成立）")
        return case

    def test_prose_form_is_not_a_machine_assertion(self):
        """**为什么必须改**：散文形态在 runner 的计分口径下**不计分**（`MACHINE_DATA_CHECK_MARKERS`）。

        ⇒ 它此前只是说明文字，不是断言 —— 这正是 issue #3789 说的"没有字段级证据"。
        """
        assert tax.is_machine_scored_data_check(self.PROSE) is False, (
            "散文形态被判成机器计分项 —— 本判据的前提不成立（先核对计分口径）")

    def test_the_prose_entry_is_replaced_by_machine_assertions(self):
        case = self._case()
        assert self.PROSE not in (case.data_checks or []), (
            "OR-014 的加工项散文条目还在 data_checks 里 —— 机器判据与散文并存会让读者"
            "以为两处都在守（实际散文不计分）")
        assert case.required_args, "OR-014 没有 required_args（存在性判据缺失）"
        assert case.arg_values, "OR-014 没有 arg_values（值级判据缺失）"

    def test_required_args_covers_the_four_snapshot_keys(self):
        req = next((r for r in self._case().required_args
                    if r.get("tool") == "order_create"), None)
        if req is None:
            pytest.fail(f"required_args 里没有 order_create：{self._case().required_args}")
        fields = set(req.get("fields") or [])
        want = {f"items[].processing_info.processingItems[].{k}"
                for k in ("id", "name", "quantity", "unit")}
        assert want <= fields, f"快照键族不完整（issue #4882 的 {sorted(want)}）：{sorted(fields)}"

    def test_arg_values_pins_quantity_to_the_fabric_meters_of_round_one(self):
        """R1 台词「遮光窗帘 **3 米**，要打孔加工」⇒ 加工项数量必须 == 3（值级）。"""
        spec = next((s for s in self._case().arg_values
                     if s.get("tool") == "order_create"), None)
        if spec is None:
            pytest.fail(f"arg_values 里没有 order_create：{self._case().arg_values}")
        assert spec.get("values") == {QTY_PATH: 3}, spec

    def test_the_documented_contract_matches_the_declaration(self):
        """**端到端**：用 R1 台词声明的米数（3）造一次合法调用 ⇒ 两条判据都判绿；
        改成密度推导（6）⇒ 值级判据判红（存在性判据**照样绿** —— 这就是"存在性顶替值级"
        的假绿形态，#3823 的病灶）。"""
        case = self._case()
        trace = lr.build_round_trace(_results(ORDER_ARGS))
        assert lr.check_required_args(_results(ORDER_ARGS), case.required_args) == []
        assert lr.check_arg_values(trace, case.arg_values) == []

        wrong = json.loads(json.dumps(ORDER_ARGS))
        wrong["items"][0]["processing_info"]["processingItems"][0]["quantity"] = 6
        assert lr.check_required_args(_results(wrong), case.required_args) == [], (
            "存在性判据对值错**不该**判红（它不是值级判据）—— 若它红了，说明实现被改坏了")
        assert lr.check_arg_values(lr.build_round_trace(_results(wrong)), case.arg_values)

    def test_loader_maps_arg_values_from_yaml(self, tmp_path):
        """**CI 走 YAML 装载路径**：漏映射 = 值级断言在 CI 上静默不跑（#3417 同款假绿）。"""
        d = tmp_path / "cases"
        d.mkdir()
        (d / "x.yml").write_text(
            "cases:\n"
            "  - id: TMP-1\n"
            "    title: t\n"
            "    tier: normal\n"
            "    persona: xiaobu\n"
            "    user_inputs:\n"
            "      - \"你好\"\n"
            "    arg_values:\n"
            "      - tool: order_create\n"
            "        values:\n"
            f"          {QTY_PATH}: 3\n",
            encoding="utf-8")
        case = {c.id: c for c in lr.load_cases_from_yaml(str(d))}["TMP-1"]
        assert case.arg_values == [{"tool": "order_create", "values": {QTY_PATH: 3}}], (
            f"装载器没把 arg_values 送到用例对象：{case.arg_values!r}")

    def test_runtime_consumes_arg_values(self):
        src = Path(lr.__file__).read_text(encoding="utf-8")
        body = src.split("async def run_case", 1)[1].split("\nasync def ", 1)[0]
        assert "case_issues += check_arg_values(" in body, (
            "值级断言没有接到 case-level 装配处 ⇒ 声明了也不会被判（假绿）")
