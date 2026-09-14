#!/usr/bin/env python3
"""
评测用例「能力覆盖体检」共享核心（issue #3555）。

**为什么单独成模块**：C 端（`xiaobu_coverage.py`）与 B 端（`mibao_coverage.py`）
体检必须**同一口径**——判据、端归属、薄覆盖定义只要复制一份就会漂移（历史教训：
两套并行实现 → 一处改了另一处不知道 → 「本地绿 CI 红」/ 假绿）。故：
  · 用例选择复用 `eval_case_filter.select_cases_for_persona`（运行器同一实现）；
  · 端工具集复用 `eval_case_filter.XIAOBU_TOOLS` / `mibao_real_toolset()`（源码解析真值）；
  · 本模块只补「覆盖矩阵 + 薄覆盖判定」这一层纯计算；
  · 两个 CLI 脚本只做参数解析与渲染，不含判据。

**判据（与 verify-all.sh 既有设计意图一致）**：
  ① 结构性缺失（**硬失败**）：工具 0 用例 / 只有对抗档或否定式用例（缺正向用例）/
     孤儿用例（用例挂到了错的端）/ 端用例集为空；
  ② 厚度不足（**只报告，不阻塞**）：某工具仅 1 条用例。条数是**随迭代收敛的活指标**
     —— verify-all.sh:66-68 明确拒绝 `--max-uncovered` 式硬编码阈值（制造返工式门禁）。
     本模块把两者分开输出，就是为了让"缺口"可见而"收敛中"不被拦。

零第三方依赖（仅标准库 + 仓库内纯函数），可在 CI 的 pytest+pyyaml 轻量 job 里跑。
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT / ".github"), str(REPO_ROOT / "tests" / "agent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_case_filter as lr  # noqa: E402

# 正向用例判据的唯一实现在 `eval_case_filter`（用例选择与覆盖判据同一处，防漂移）；
# 此处再导出，使"体检"的调用方与测试不必知道它住在哪个模块。
is_positive_case = lr.is_positive_case

PERSONAS = ("xiaobu", "mibao")

PERSONA_LABELS = {
    "xiaobu": "C 端小布",
    "mibao": "B 端米宝",
}

# ── 能力标签（缺口报告的人读性）────────────────────────────────────────────────
# 只覆盖能力矩阵里需要"说人话"的工具；缺标签的工具有名字也够用。
XIAOBU_TOOL_LABELS = {
    "customer_order_query": "查本人订单",
    "customer_logistics_track": "查物流（仅本人已发货）",
    "customer_address_query": "查收货地址",
    "order_create": "下单创建",
    "product_search": "商品搜索",
    "product_detail": "商品详情",
    "curtain_calc": "窗帘算料报价",
    "aftersale_query": "售后工单查询",
    "aftersale_create": "售后工单创建",
    "knowledge_search": "知识问答（本店知识库）",
    "human_handoff": "转人工",
    "interact": "交互卡片（choice/form/confirm）",
    "validate_input": "写操作前置校验",
}

MIBAO_TOOL_LABELS = {
    "order_query": "订单查询",
    "order_manage": "订单状态/操作（改状态、发货等）",
    "order_create": "代客下单",
    "logistics_track": "物流跟踪",
    "product_search": "商品搜索",
    "product_detail": "商品详情",
    "product_manage": "商品 CRUD（建品/上下架）",
    "product_update": "商品级统一定价",
    "sku_update": "SKU 单独调价",
    "product_processing_item_manage": "商品加工项关联",
    "processing_item_manage": "加工项 CRUD",
    "processing_item_query": "加工项查询",
    "processing_order_generate": "生成加工单（批量）",
    "processing_order_query": "加工单查询",
    "processing_order_update": "加工单状态更新",
    "inventory_manage": "库存管理",
    "category_manage": "商品分类管理",
    "after_sales_manage": "售后工单处理",
    "customer_manage": "客户档案/标签/跟进",
    "employee_manage": "员工账号管理",
    "role_manage": "角色与权限管理",
    "settings_manage": "系统/AI 配置",
    "notification_manage": "站内通知/公告",
    "dashboard_stats": "经营看板",
    "finance_api": "财务（收支/流水/对账）",
    "session_manage": "客服会话/转人工",
    "knowledge_search": "知识问答（本店知识库）",
    "validate_input": "写操作前置校验",
    "interact": "交互卡片（choice/form/confirm）",
}


def toolset_for(persona: str) -> set:
    """该端可跑工具集（单一真值来源，与用例边界守卫共用）。"""
    if persona == "xiaobu":
        return set(lr.XIAOBU_TOOLS)
    if persona == "mibao":
        return lr.mibao_real_toolset()
    raise ValueError(f"未知 persona: {persona!r}（应为 {PERSONAS}）")


def tool_label(persona: str, tool: str) -> str:
    table = XIAOBU_TOOL_LABELS if persona == "xiaobu" else MIBAO_TOOL_LABELS
    return table.get(tool, "")


def case_title(c) -> str:
    if isinstance(c, dict):
        return str(c.get("title") or c.get("id") or "")
    return str(getattr(c, "title", "") or getattr(c, "id", ""))


@dataclass
class CoverageReport:
    """一端的能力覆盖体检结果（纯数据，渲染见各 CLI 脚本）。"""

    persona: str
    cases_total: int = 0                      # 用例库总条数
    cases_run: int = 0                        # 该端实际会跑的条数
    tools: set = field(default_factory=set)   # 该端工具集
    cases: dict = field(default_factory=dict)         # tool → [用例 ID]（含对抗/否定）
    positive: dict = field(default_factory=dict)      # tool → [正向用例 ID]
    adversarial: dict = field(default_factory=dict)   # tool → [对抗档用例 ID]
    uncovered: list = field(default_factory=list)     # 0 用例（结构性缺失 → 阻塞）
    missing_positive: dict = field(default_factory=dict)   # 缺正向用例（结构性缺失 → 阻塞）
    thin_tools: list = field(default_factory=list)    # 仅 1 条用例（厚度不足 → 只报告）
    exempt: dict = field(default_factory=dict)        # tool → 显式豁免理由（非缺口）
    orphan_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 挂到了错的端 → 阻塞
    dangling_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 两端注册表都没有 → 阻塞

    @property
    def covered(self) -> int:
        return len(self.tools) - len(self.uncovered)

    def uncovered_actionable(self) -> list:
        """排除显式豁免后的真缺口。"""
        return [t for t in self.uncovered if t not in self.exempt]

    def check_problems(self) -> list:
        """--check 的失败条件（只含**结构性缺失**，不含厚度不足）。"""
        problems = []
        if self.cases_run == 0:
            problems.append(f"{PERSONA_LABELS[self.persona]}用例集为空（评测假绿）")
        if self.orphan_cases:
            problems.append(
                f"{len(self.orphan_cases)} 条孤儿用例（期望工具 {PERSONA_LABELS[self.persona]}没有，"
                f"用例挂到了错的端）: " + ", ".join(cid for cid, _ in self.orphan_cases)
            )
        if self.dangling_cases:
            problems.append(
                f"{len(self.dangling_cases)} 条用例断言了**两端注册表都没有**的工具"
                f"（拼错/已删除，期望永不满足）: "
                + ", ".join(f"{cid}({','.join(t)})" for cid, t in self.dangling_cases)
            )
        missing = self.uncovered_actionable()
        if missing:
            problems.append(
                f"{len(missing)} 个工具零用例覆盖（结构性缺失）: " + ", ".join(missing)
            )
        if self.missing_positive:
            problems.append(
                f"{len(self.missing_positive)} 个工具只有对抗/拒绝用例、**没有任何正向用例**"
                f"（能力未被证明）: "
                + ", ".join(f"{t}(现仅 {','.join(ids)})"
                            for t, ids in sorted(self.missing_positive.items()))
            )
        return problems


def build_coverage_report(cases, persona: str, tools=None, exempt=None) -> CoverageReport:
    """计算一端的覆盖矩阵与薄覆盖清单。

    cases  : `.github/cases` 加载出的用例 dict 列表（全库，本函数自己做端归属过滤）
    persona: "xiaobu" / "mibao"
    tools  : 该端工具集（缺省取真值；测试可注入小集合验证判据）
    exempt : 显式豁免（tool → 理由），豁免项不计入"零用例"缺口
             （**只用于客观无法跑的能力**，且理由写进报告；豁免会掩盖回归，故应尽量为空）
    """
    persona = (persona or "").strip().lower()
    if persona not in PERSONAS:
        raise ValueError(f"未知 persona: {persona!r}（应为 {PERSONAS}）")
    tools = set(tools) if tools is not None else toolset_for(persona)
    exempt = dict(exempt or {})

    selected = lr.select_cases_for_persona(cases, persona)
    known_anywhere = tools | set(lr.XIAOBU_TOOLS) | lr.mibao_real_toolset() | set(lr.PSEUDO_TOOLS)

    rep = CoverageReport(persona=persona, cases_total=len(list(cases)),
                         cases_run=len(selected), tools=tools, exempt=exempt)
    for case in selected:
        cid = case.get("id") if isinstance(case, dict) else getattr(case, "id", "?")
        tier = str(case.get("tier") if isinstance(case, dict) else getattr(case, "tier", ""))
        is_adv = tier.strip().lower() == "adversarial"
        positive = lr.is_positive_case(case)

        outside_end, dangling = set(), set()
        for exp in (case.get("expectations") if isinstance(case, dict)
                    else getattr(case, "expectations", None)) or []:
            branches = lr.expectation_branches(exp)
            if not branches:
                continue
            if not (set(branches) & tools):
                outside_end |= set(branches)
            if not (set(branches) & known_anywhere):
                dangling |= set(branches)
        if dangling:
            rep.dangling_cases.append((cid, sorted(dangling)))
        elif outside_end:
            # 该用例的**每一个**工具期望都落在此端能力之外 → 用例挂错了端（阻塞）
            rep.orphan_cases.append((cid, sorted(outside_end)))

        for tool in lr.case_expectation_tools(case):
            if tool in tools:
                rep.cases.setdefault(tool, []).append(cid)
                if is_adv:
                    rep.adversarial.setdefault(tool, []).append(cid)
        if positive:
            for tool in lr.case_expectation_tools(case):
                if tool in tools:
                    rep.positive.setdefault(tool, []).append(cid)

    for tool in sorted(tools):
        ids = rep.cases.get(tool) or []
        if not ids:
            rep.uncovered.append(tool)        # 0 用例 → 结构性缺失（阻塞）
        elif len(ids) == 1:
            rep.thin_tools.append(tool)       # 仅 1 条 → 厚度不足（只报告）
        # 缺正向用例（阻塞）：**已覆盖**却没有一条证明"该工具能力可用"的用例。
        # 零用例的工具由 uncovered 单独报，不在这里重复（避免同一件事报两遍）。
        if ids and not rep.positive.get(tool) and tool not in exempt:
            rep.missing_positive[tool] = list(ids)
    return rep
