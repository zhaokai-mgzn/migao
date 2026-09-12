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
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))   # 复用运行器的选择语义

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


# 写工具（有副作用的）：断言它们就必须同时断言成功，否则"调了≠成了"的假绿会重现
WRITE_TOOLS = frozenset({
    "order_create", "aftersale_create", "human_handoff",
    "product_update", "order_update", "customer_update",
})


def _customer_tools() -> set:
    tools: set = set()
    for path in sorted(SKILLS_DIR.glob("customer*.py")):
        src = path.read_text(encoding="utf-8")
        for const in CUSTOMER_SKILL_TOOL_CONSTS:
            m = re.search(re.escape(const) + r"\s*=\s*\[(.*?)\]", src, re.S)
            if m:
                tools.update(re.findall(r'"([a-z_]+)"', m.group(1)))
    return tools


def _all_tool_constants() -> set:
    """全部 skill（含 B 端）的工具常量并集 —— 断言词汇表的工具部分。"""
    tools: set = set()
    for path in sorted(SKILLS_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"([A-Z_]+_TOOLS)\s*=\s*\[(.*?)\]", src, re.S):
            tools.update(re.findall(r'"([a-z_]+)"', m.group(2)))
    return tools


def _asserted_tools(case: dict) -> set:
    """用例断言到的工具名（expectations / must_succeed / order_before）。

    **按已知工具全集做词匹配**，而不是解析 YAML 结构 —— 首版用
    `re.match(r"\s*([a-z_]+)", entry)` 取首词，结果 `yaml_light` 把 `expectations`
    里的块状条目读成**多行原始字符串**（`'- tool: human_handoff\n    data_checks:…'`），
    首词落到 `send`/`create` 上 → `writes` 恒为空 → **守卫恒绿（假守卫，M84 变异实证）**。
    改法：拿工具全集去文本里找词边界命中，对 dict/字符串/多行块都成立。
    """
    known = _customer_tools()
    out = set()

    def scan(entry):
        if isinstance(entry, dict):
            t = entry.get("tool")
            if t:
                out.add(str(t))
            return
        text = str(entry)
        for name in known:
            if re.search(r"(?<![a-z_])" + re.escape(name) + r"(?![a-z_])", text):
                out.add(name)

    for e in case.get("expectations") or []:
        scan(e)
    for key in ("must_succeed", "required_args", "forbidden_args"):
        for e in case.get(key) or []:
            scan(e)
    for spec in case.get("order_before") or []:
        scan(spec)
    return out


class TestXiaobuCapabilityCoverage:
    def _measured_cases(self) -> list:
        """**运行器真正会跑**的 C 端集合（normal 档 = 每日回归）。

        为什么不能用 `persona == xiaobu` 了事（issue #3367 覆盖审计踩到）：
          - `skip_reason` 非空的不跑（CH-030/031/032 就是被 skip 的纯前端用例）；
          - smoke 档在 CI 里**没人跑**（xiaobu-acceptance 派发的是 normal）
            → 只看 persona 会把"从不执行的用例"算成覆盖，得出"已覆盖"的假结论；
          - 双端用例只要期望工具都在小布能力集内也会被选进来（select_cases_for_persona）。
        这里直接复用运行器的选择语义，保证"覆盖统计的面 = 真正被测的面"。
        """
        from eval_case_filter import select_cases_for_persona
        sel = select_cases_for_persona(load_case_dicts(str(CASES_DIR)), "xiaobu")
        return [c for c in sel if str(c.get("tier") or "").strip().lower() == "normal"]

    def _xiaobu_asserted(self) -> set:
        out = set()
        for c in self._measured_cases():
            out |= _asserted_tools(c)
        return out

    def test_every_customer_tool_is_covered_or_justified(self):
        tools = _customer_tools()
        assert len(tools) >= 10, f"C 端工具解析异常（只解析到 {len(tools)} 个）：{sorted(tools)}"
        measured = self._measured_cases()
        assert len(measured) >= 15, f"C 端 normal 档只剩 {len(measured)} 条，选择语义可能坏了"
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

    def test_expectations_resolve_to_known_vocabulary(self):
        """断言必须落在**已知词汇表**里，否则就是一条"死断言"（issue #3367）。

        为什么需要：`yaml_light` 是手写解析器，缩进/换行写坏时**不会报错**，只会把
        `- tool: human_handoff` 与后面一行粘成一个值（本轮实测：手工变异把 YAML 弄坏后
        解析成 `{'tool': 'human_handoff    data_checks:'}`，工具名对不上任何真实工具）。
        这类"解析悄悄坏掉"的危害是双向的：既可能让用例恒红（把解析问题报成 Agent 能力问题），
        也可能让覆盖率统计失真（本轮我就先被它骗过一次）。
        词汇表 = 工具全集 + 语义 token；支持 `A or B` 与 `tool(args=…)` 形态。
        """
        known = _customer_tools() | _all_tool_constants()
        # 评测器支持的语义 token（见 local_runner.check_expectation）：
        #   direct_reply → 该轮无工具调用且有文本；success=true → 该轮无 error
        semantic = {"direct_reply", "success"}
        bad = []
        for c in self._measured_cases():
            for key in ("expectations", "must_succeed"):
                for e in c.get(key) or []:
                    text = e.get("tool") if isinstance(e, dict) else str(e)
                    if not text:
                        bad.append(f"{c['id']}.{key}: 空条目")
                        continue
                    for part in re.split(r"\s+or\s+", str(text)):
                        token = re.match(r"\s*([a-z_]+)", part.strip())
                        name = token.group(1) if token else ""
                        if name in known or name in semantic:
                            continue
                        bad.append(f"{c['id']}.{key}: 无法解析出已知断言 {str(e)[:60]!r}")
        assert not bad, (
            "以下断言不在已知词汇表里（YAML 可能写坏，或用了新 token 却没登记）：\n  "
            + "\n  ".join(bad)
        )

    def test_write_tool_cases_assert_success(self):
        """C 端写用例必须同时断言**写成功**（issue #3367 覆盖审计）。

        「调了」≠「成了」：只断言工具名时，返回 success=false / tool_not_found 也判绿。
        issue #3361 已在 order_create 上实证（tool_not_found 而用例 100%）。
        本次审计发现 **5 条 human_handoff 用例**（C 端最大能力族：转人工）全部缺成功断言 ——
        而它们的业务价值（工作台可见/可回复、AI 上下文透传）完全建立在会话真的落库之上。
        """
        missing = []
        for c in self._measured_cases():
            writes = _asserted_tools(c) & WRITE_TOOLS
            if not writes:
                continue
            ok = set()
            for e in c.get("must_succeed") or []:
                t = e.get("tool") if isinstance(e, dict) else str(e)
                if t:
                    ok.add(t)
            for t in sorted(writes):
                if t not in ok:
                    missing.append(f"{c['id']} 断言了 {t} 但没有 must_succeed")
        assert not missing, (
            "以下 C 端写用例只有'调了'没有'成了'（补 must_succeed）：\n  " + "\n  ".join(missing)
        )

    def test_curtain_calc_is_covered(self):
        """算料报价是布艺行业核心能力，必须有链路级用例（issue #3367 的实证缺口）。"""
        assert "curtain_calc" in self._xiaobu_asserted(), (
            "curtain_calc 又变成零覆盖了（PR-013 的 persona: xiaobu 是否被误删？）"
        )
