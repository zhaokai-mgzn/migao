# case_ids: PR-013, OR-017, CH-010
"""C 端能力覆盖守卫（issue #3367）。

为什么需要：C 端评测面此前是**手工维护**的 18 条用例 —— 能力加了、用例没加，
没有任何机制会发现。实证：`curtain_calc`（算料报价，布艺行业核心能力）的用例
PR-013 被写成**不带 persona 的 B 端档位** + skip_reason 挂起 → C 端该能力
**零覆盖**（只有单测覆盖公式，没有真实 LLM 链路证据），而 CI 一片绿。

本守卫把「C 端 skill 的工具全集」与「C 端用例的断言」对齐：
**任何 C 端工具若没有任何用例断言它，就报红** —— 要么补用例，要么显式登记进
`INTERNAL_NO_CASE`（并写清为什么不需要链路级用例）。

工具全集**从源码解析**（不 import app.*：本目录是零依赖测试，CI 的
unit_ci_workflows job 只装了 pytest+pyyaml；app 侧依赖 langchain 装不上）。
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# C 端（小布）skill 的工具常量 —— 新增 C 端 skill 时必须登记到这里，
# 否则它的工具不会被本守卫纳入（这是有意的：新增能力面要显式过一次评审）。
CUSTOMER_SKILL_TOOL_CONSTS = (
    "CUSTOMER_ORDER_TOOLS",
    "CUSTOMER_AFTERSALES_TOOLS",
    "CUSTOMER_GENERAL_TOOLS",
    "CUSTOMER_KNOWLEDGE_TOOLS",
    "CUSTOMER_PRODUCT_TOOLS",
    "CUSTOMER_QUOTE_TOOLS",
)

# 允许"没有链路级用例断言"的工具：必须逐条写明理由（这道门是防遗忘，不是防写用例）
INTERNAL_NO_CASE = {
    # 写操作前的内部校验步骤；其正确性由写用例的前置条件（参数正确才允许写）间接覆盖
    "validate_input": "内部校验步骤：由写用例的成功/被拦间接覆盖，单独断言无独立业务语义",
    # 收货地址查询：下单用例的必经内部步骤（CH-010/OR-017 轨迹里都有），
    # 但没有"C 端顾客直接问地址"的独立业务场景
    "customer_address_query": "下单流程内部步骤（取默认地址），无独立顾客诉求场景",
}


def _customer_tools() -> set:
    tools: set = set()
    for path in sorted(SKILLS_DIR.glob("customer*.py")):
        src = path.read_text(encoding="utf-8")
        for const in CUSTOMER_SKILL_TOOL_CONSTS:
            m = re.search(re.escape(const) + r"\s*=\s*\[(.*?)\]", src, re.S)
            if m:
                tools.update(re.findall(r'"([a-z_]+)"', m.group(1)))
    return tools


def _asserted_tools(case: dict) -> set:
    """用例断言到的工具名（expectations / must_succeed / order_before / forbidden_*）。"""
    out = set()

    def add(entry):
        if isinstance(entry, dict):
            t = entry.get("tool")
        else:
            m = re.match(r"\s*([a-z_]+)", str(entry))
            t = m.group(1) if m else None
        if t:
            out.add(t)

    for e in case.get("expectations") or []:
        add(e)
    for key in ("must_succeed", "required_args", "forbidden_args"):
        for e in case.get(key) or []:
            add(e)
    for spec in case.get("order_before") or []:
        for tok in re.split(r"\s+before\s+|\s+", str(spec)):
            t = tok.split("[")[0].strip()
            if t:
                out.add(t)
    return out


class TestXiaobuCapabilityCoverage:
    def _xiaobu_asserted(self) -> set:
        out = set()
        for c in load_case_dicts(str(CASES_DIR)):
            if c.get("persona") != "xiaobu":
                continue
            out |= _asserted_tools(c)
        return out

    def test_every_customer_tool_is_covered_or_justified(self):
        tools = _customer_tools()
        assert len(tools) >= 10, f"C 端工具解析异常（只解析到 {len(tools)} 个）：{sorted(tools)}"
        asserted = self._xiaobu_asserted()
        uncovered = sorted(t for t in tools if t not in asserted and t not in INTERNAL_NO_CASE)
        assert not uncovered, (
            "以下 C 端能力在评测里零覆盖（补用例，或登记进 INTERNAL_NO_CASE 并写明理由）：\n  "
            + "\n  ".join(f"{t}" for t in uncovered)
        )

    def test_internal_allowlist_entries_are_real_tools(self):
        """豁免表不能挂空名（防"改名后豁免悄悄失效"）—— 要么是真实工具，要么删掉。"""
        tools = _customer_tools()
        stale = sorted(t for t in INTERNAL_NO_CASE if t not in tools)
        assert not stale, f"INTERNAL_NO_CASE 里的 {stale} 已不是 C 端工具，应删除"

    def test_curtain_calc_is_covered(self):
        """算料报价是布艺行业核心能力，必须有链路级用例（issue #3367 的实证缺口）。"""
        assert "curtain_calc" in self._xiaobu_asserted(), (
            "curtain_calc 又变成零覆盖了（PR-013 的 persona: xiaobu 是否被误删？）"
        )
