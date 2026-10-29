# case_ids: DA-026
"""经营日报条目带追问入口 —— 条目与**可执行动作**之间的桥（族 1 × 族 4，issue #8155）。

病：`daily_findings` 的条目读出来是**一段结论**（「2 个 SKU 库存告急」），商家想接着办
（「那帮我看看是哪几个」）时得自己把「要查什么」重新描述一遍；条目与可执行动作之间没有桥。
药：每条 finding 带 `follow_up = {prompt, tool_hint}` —— `prompt` 由**该条真值**派生、
`tool_hint` 指向**真能回答那个问题**的已注册工具。

四条判据（都要会红）：

1. **每条已登记规则都带 follow_up**：`FOLLOW_UPS` 的键集 ⇄ `RULES` 的 rule_id **双向相等**
   （漏登记新规则 / 登记了不存在的规则都红），且 `prompt` 非空、≤ 40 字、**由该条真实字段派生**；
2. **`tool_hint` 指向真能力**：工具名在**现取注册表**里、**不是 `briefing_query` 自己**，
   且其中的参数 / `action` 枚举在工具 schema 里真实存在（红证：把某个 `tool_hint` 改成不存在的
   `action` ⇒ 本条必红 —— 这就是「不许编造工具能力」的机械面）；
3. **判别力自证（fail-closed）**：合成一个未登记的 `rule_id` ⇒ 该条**不给** follow_up，
   而同一快照上未注入的规则**照常给**（防「引擎干脆不给所有 follow_up」也变绿）；
4. **`briefing_query` 逐字带上**：`data.proactive` 与 `daily_findings()` 的输出**逐字相同**
   （工具侧零重算、零改写）。

⚠️ 边界：`tool_hint` 只是**可执行提示**（工具名 + 参数形态），不是自动执行；本判据核的是
「工具与参数**存在**」这一半，核不了「模型的语义选择对不对」（那属 LLM 行为面，见用例 DA-026）。
"""

import json
import re
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from app.briefing.proactive import (
    FOLLOW_UP_MAX_PROMPT,
    FOLLOW_UPS,
    RULES,
    ProactiveConfig,
    daily_findings,
    follow_up_for,
    scan_snapshot,
)
from app.tools.base import ToolContext
from app.tools.briefing_query import BriefingQueryTool
from app.tools.registry import create_default_registry
from tests.test_briefing_proactive import BIZ_DATE, SNAPSHOT

#: `tool_hint` 的**唯一**形态：`<工具名>(<key>=<value>[, <key>=<value>…])`
TOOL_HINT = re.compile(r"^(?P<tool>[a-z][a-z0-9_]*)\((?P<args>.+)\)$")

ALLOWED = ToolContext(tenant_id=7, user_id="u-1", session_id="s-1", role="admin",
                      permissions=["dashboard:view"])


@pytest.fixture(scope="module")
def registry():
    """**现取**注册表（不写字面清单：工具改名/下线 ⇒ 判据自动跟随，而不是跟着一起烂）"""
    return create_default_registry()


#: 日报视图默认只留前 `max_findings`(5) 条；本文件的判据要**六条全在**，
#: 故显式把上限抬到规则条数（不是改默认口径 —— 默认值仍由 `test_briefing_proactive.py` 钉住）
ALL_RULES = ProactiveConfig(max_findings=len(RULES))


@pytest.fixture(scope="module")
def daily():
    """该快照上**六条规则各命中一条**（日报视图）—— 判据 1/2/4 的共同输入"""
    return daily_findings(SNAPSHOT, config=ALL_RULES)


def _by_rule(findings, rule_id):
    hits = [f for f in findings if f["rule_id"] == rule_id]
    assert len(hits) == 1, f"{rule_id} 期望恰好 1 条命中，实得 {len(hits)}"
    return hits[0]


def _parse_tool_hint(tool_hint):
    """拆出 `tool_hint` 的 (工具名, [(参数名, 值), …])；形态不对直接红。"""
    match = TOOL_HINT.match(tool_hint or "")
    assert match, f"tool_hint 形态不合法：{tool_hint!r}（应为 `<工具名>(<key>=<value>)`）"
    pairs = []
    for chunk in match.group("args").split(", "):
        key, sep, value = chunk.partition("=")
        assert sep == "=", f"tool_hint 参数段不合法：{chunk!r}"
        pairs.append((key.strip(), value.strip()))
    return match.group("tool"), pairs


class TestEveryFindingHasAFollowUp:
    """判据 1：六条规则**逐条**都有入口，且 prompt 是真的从这条命中里派生的"""

    def test_registry_covers_exactly_the_registered_rules(self):
        """键集**双向相等**：漏登记新规则 ⇒ 红；登记了不存在的规则 ⇒ 也红"""
        assert set(FOLLOW_UPS) == {rule.rule_id for rule in RULES}
        assert all(callable(builder) for builder in FOLLOW_UPS.values())

    def test_every_daily_finding_carries_a_wellformed_follow_up(self, daily):
        assert {f["rule_id"] for f in daily} == set(FOLLOW_UPS), "六条规则必须都真的产出了一条"
        for finding in daily:
            follow_up = finding.get("follow_up")
            assert isinstance(follow_up, dict), f"{finding['rule_id']} 缺 follow_up"
            assert set(follow_up) == {"prompt", "tool_hint"}, follow_up
            prompt = follow_up["prompt"]
            assert prompt.strip(), f"{finding['rule_id']} 的 prompt 为空"
            assert len(prompt) <= FOLLOW_UP_MAX_PROMPT, (
                f"{finding['rule_id']} 的 prompt {len(prompt)} 字 > {FOLLOW_UP_MAX_PROMPT}：{prompt!r}")
            assert follow_up["tool_hint"].strip()

    @pytest.mark.parametrize("rule_id", [rule.rule_id for rule in RULES])
    def test_prompt_is_derived_from_the_findings_own_fields(self, rule_id, daily):
        """prompt 必须由**该条**的真值派生（计数 / 窗口天数），不是一句固定模板"""
        finding = _by_rule(daily, rule_id)
        prompt = finding["follow_up"]["prompt"]
        thresholds = finding["criterion"]["thresholds"]
        if "repeat_return_window_days" in thresholds:
            # 窗口型规则：prompt 里的天数 = 该条 criterion 登记的窗口
            assert str(thresholds["repeat_return_window_days"]) in prompt
        else:
            # 计数型规则：prompt 里的条数 = 该条 impact.count
            assert str(finding["impact"]["count"]) in prompt, (
                f"{rule_id} 的 prompt 没带本条计数 {finding['impact']['count']}：{prompt!r}")

    def test_follow_up_is_deterministic(self):
        """同一份快照两次扫描 ⇒ 追问入口逐字一致（无时间、无随机、无模型参与）"""
        first = json.dumps([f["follow_up"] for f in daily_findings(SNAPSHOT, config=ALL_RULES)],
                           ensure_ascii=False, sort_keys=True)
        second = json.dumps([f["follow_up"] for f in daily_findings(SNAPSHOT, config=ALL_RULES)],
                            ensure_ascii=False, sort_keys=True)
        assert first == second


class TestToolHintPointsAtRealCapability:
    """判据 2：`tool_hint` 的每个工具与参数都**现取注册表**核实过（不编造工具能力）"""

    @pytest.mark.parametrize("rule_id", [rule.rule_id for rule in RULES])
    def test_tool_exists_and_is_not_the_briefing_tool_itself(self, rule_id, daily, registry):
        tool_name, _ = _parse_tool_hint(_by_rule(daily, rule_id)["follow_up"]["tool_hint"])
        # 追问入口不能指回日报自己（那等于「再查一遍日报」，不是接着办）
        assert tool_name != "briefing_query", f"{rule_id} 的 tool_hint 指回了 briefing_query"
        assert registry.get_tool(tool_name) is not None, f"{rule_id} 的 tool_hint 工具不存在：{tool_name}"

    @pytest.mark.parametrize("rule_id", [rule.rule_id for rule in RULES])
    def test_every_hinted_parameter_exists_in_the_tool_schema(self, rule_id, daily, registry):
        """参数名 + 枚举值都必须在工具 schema 里**真实存在**（值写成 `<…>` 的占位符跳过枚举核）"""
        tool_name, pairs = _parse_tool_hint(_by_rule(daily, rule_id)["follow_up"]["tool_hint"])
        tool = registry.get_tool(tool_name)
        properties = (tool.parameters or {}).get("properties", {})
        assert pairs, f"{rule_id} 的 tool_hint 没给参数形态（只给工具名不算可执行提示）"
        for key, value in pairs:
            assert key in properties, f"{tool_name} 没有参数 {key}（现有：{sorted(properties)}）"
            enum = properties[key].get("enum")
            if enum is None or value.startswith("<"):
                continue  # 非枚举参数 / 占位符（如 `<单号>`）：由模型按上下文填真值
            assert value in enum, f"{tool_name}({key}={value}) 不在枚举里：{enum}"


class TestUnknownTypeIsNotGuessed:
    """判据 3（判别力自证）：未登记的 rule_id ⇒ **不给** follow_up，且不影响其它条"""

    def test_unknown_rule_type_gets_no_follow_up(self):
        """把已有规则换成一个未登记的 rule_id（其余真值不变）⇒ 命中照旧、入口**必须缺席**"""
        unknown = replace(RULES[0], rule_id="made_up_rule_for_follow_up")
        findings = scan_snapshot(SNAPSHOT, as_of=BIZ_DATE, rules=(unknown,))
        assert findings, "注入的候选必须在同一快照上命中（否则本条是空断言）"
        assert any(f["detected_on"] == BIZ_DATE for f in findings), "注入的候选必须在当天命中"
        assert {f["rule_id"] for f in findings} == {"made_up_rule_for_follow_up"}
        for finding in findings:
            assert "follow_up" not in finding, (
                "未登记的 rule_id 不许猜一个工具：宁可没有入口，也不给一个错工具")

    def test_known_rules_keep_their_follow_up_in_the_same_run(self):
        """对照组：同一实现下，登记过的六条**照常**带 follow_up（防「干脆都不给」也变绿）"""
        assert all("follow_up" in f for f in daily_findings(SNAPSHOT, config=ALL_RULES))

    def test_follow_up_for_is_the_only_gate(self):
        """`follow_up_for()` 对空 / 未登记 / 近似的 rule_id 一律 None（不做前缀/模糊匹配）"""
        hit = object()  # 未登记 ⇒ 不应触碰 hit/cfg，直接返回 None（不猜就不该读数据）
        for bogus in ("", None, "made_up_rule_for_follow_up", "low_stock_v2", "LOW_STOCK"):
            assert follow_up_for(bogus, hit, None) is None, bogus


class TestBriefingToolCarriesItVerbatim:
    """判据 4：`briefing_query` 的输出逐字带上 `follow_up`（工具侧零重算、零改写）"""

    @patch("app.tools.briefing_query.get_admin_api_client")
    async def test_data_proactive_equals_the_engine_output(self, mock_get_client):
        client = AsyncMock()
        client.get = AsyncMock(return_value={
            "success": True,
            "data": {"bizDate": BIZ_DATE, "sourceSnapshot": SNAPSHOT},
        })
        mock_get_client.return_value = client

        result = await BriefingQueryTool().execute(context=ALLOWED)

        assert result.success is True
        # 工具侧原样转出引擎结果（含默认 `max_findings` 截断）—— 这里比的是**同一份调用**的输出
        engine = daily_findings(SNAPSHOT, as_of=BIZ_DATE)
        assert json.dumps(result.data["proactive"], ensure_ascii=False, sort_keys=True) == \
            json.dumps(engine, ensure_ascii=False, sort_keys=True)
        assert all(f["follow_up"]["prompt"] for f in result.data["proactive"])
