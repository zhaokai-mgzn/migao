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
from __future__ import annotations       # 前置类型注解（脚本需兼容 python3.9 系统解释器）

import re
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

# ── 存量豁免清单（burn-down baseline，issue #3575 决策记录）──────────────────────
# 为什么需要：门禁首次接入时必然与**存量**结构性缺口冲突（工具零用例 / 只有拒绝式断言）。
# 直接放宽判据 = 门禁变摆设；直接挡住所有 PR = 用存量债锁死流水线。第三条路是
# **显式、可收缩的清单**：只豁免**已登记**的存量缺口，任何**新出现**的缺口照旧阻塞。
#
# 防「白名单变垃圾场」的四道锁（缺一即红，全部由 `load_baseline` + 单测强制）：
#   ① 每条必须带齐 tool / kind / issue / reason（issue 必须是真实存在的 issue 号格式）；
#   ② 条目必须**指向该端真实工具**且**确实对应一种已知缺口 kind**；
#   ③ 条目若指向工具**当前不存在的缺口** = 陈旧登记（销账后没删）→ 阻塞；
#   ④ 条目 kind 必须与该工具**当前实际的缺口 kind** 一致（例如工具只有 1 条用例，
#      却登记成 `missing_positive` → 判陈旧，逼登记与实际对齐）。
# 清单是**工作清单不是免死金牌**：报告里逐条打印归属 issue，补完用例即删条目。
BASELINE_PATH = REPO_ROOT / ".github" / "eval-coverage-baseline.yml"
BLOCKING_KINDS = ("uncovered", "missing_positive")
REPORTING_KINDS = ("thin", "thin_positive")
GAP_KINDS = BLOCKING_KINDS + REPORTING_KINDS
ENTRY_REQUIRED_FIELDS = ("tool", "kind", "issue", "reason", "added")
_ISSUE_RE = re.compile(r"^#\d+$")
_MIN_REASON_LEN = 8


def load_baseline(path=None, persona: str = "", tools=None):
    """读并**校验**存量豁免清单（fail-closed：文件缺失/格式坏/条目不合规 → 抛 ValueError）。

    返回 `{"path", "meta", "entries", "by_tool", "entries_by_tool", "issues"}`；
    `entries` 只含该 persona 的条目（其它端的条目在此忽略，但仍会被格式校验）。
    """
    path = Path(path) if path else BASELINE_PATH
    if not path.exists():
        raise ValueError(
            f"存量豁免清单不存在: {path}\n"
            f"    ⇒ 门禁要么全绿（无存量缺口）要么无法豁免存量缺口，二者都必须显式 ——"
            f"若确实无存量缺口，创建一个只有 meta 的空清单文件"
        )
    try:
        # 用仓库自己的零依赖解析器（`yaml_light`，与 render_cases/truths 同一份实现）：
        # `case-coverage-gate` job 只做 setup-python，**没有** `pip install`
        # （pyyaml 只装在 `ci workflow helper unit tests` job）—— 这里 import yaml 会让门禁
        # 对每个 PR 常红（"覆盖体检无法执行：需要 pyyaml"），且与用例质量无关。
        from yaml_light import load_file as _load_yaml
        data = _load_yaml(path)
    except Exception as exc:
        raise ValueError(f"{path.name} YAML 解析失败: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 顶层必须是映射（含 version/entries）")
    entries = data.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError(f"{path.name} 的 entries 必须是列表")

    end_tools = set(tools) if tools is not None else None
    by_tool: dict = {}
    entries_by_tool: dict = {}
    issues = set()
    problems = []
    for i, raw in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{where}: 必须是映射（tool/kind/issue/reason/added）")
            continue
        missing = [f for f in ENTRY_REQUIRED_FIELDS if not str(raw.get(f) or "").strip()]
        if missing:
            problems.append(f"{where}: 缺字段 {missing}（防白名单变垃圾场：一条不许留空）")
            continue
        tool, kind = str(raw["tool"]).strip(), str(raw["kind"]).strip()
        entry_persona = str(raw.get("persona") or "").strip().lower()
        issue, reason = str(raw["issue"]).strip(), str(raw["reason"]).strip()
        where = f"entries[{i}] {tool}[{kind}]"
        if kind not in GAP_KINDS:
            problems.append(f"{where}: kind 必须是 {GAP_KINDS} 之一")
            continue
        if not _ISSUE_RE.match(issue):
            problems.append(f"{where}: issue 必须是 '#<数字>'（真实存在的追踪 issue），实际 {issue!r}")
            continue
        if len(reason) < _MIN_REASON_LEN:
            problems.append(f"{where}: reason 至少 {_MIN_REASON_LEN} 字（说清为什么暂时豁免）")
            continue
        if entry_persona and entry_persona not in PERSONAS:
            problems.append(f"{where}: persona 必须是 {PERSONAS} 之一或留空（双端共用）")
            continue
        # 归属**别的端**的条目不由本次体检负责（工具真值/缺口由那端的体检校验）
        if entry_persona and persona and entry_persona != persona:
            continue
        # 只对归属本端的条目校验工具真值
        if end_tools is not None and tool not in end_tools:
            problems.append(f"{where}: {tool} 不是{persona or '该端'}工具（拼错/工具已删除 → 登记无效）")
            continue
        by_tool.setdefault(tool, set()).add(kind)
        entries_by_tool.setdefault(tool, {})[kind] = raw
        issues.add(issue)
    if problems:
        raise ValueError(
            f"{path.name} 有 {len(problems)} 条不合规条目：\n  - " + "\n  - ".join(problems)
        )
    own = [e for e in entries if isinstance(e, dict)
           and (not e.get("persona") or not persona
                or str(e["persona"]).strip().lower() == persona)]
    return {"path": path, "meta": {k: v for k, v in data.items() if k != "entries"},
            "entries": own, "by_tool": by_tool, "entries_by_tool": entries_by_tool,
            "issues": issues}


def _attach_baseline(rep: CoverageReport, baseline: dict) -> CoverageReport:
    """把存量豁免挂到报告上，并算出「陈旧登记」（销账后未删）。

    陈旧 = 登记了某工具某 kind，但该工具**当前不再是**那种缺口（用例已补 / kind 变了）。
    这类登记必须删，否则清单会越攒越多、丧失"工作清单"的可读性。
    """
    rep.baseline = baseline
    rep.baseline_missing = [
        (tool, kind)
        for tool, kinds in baseline.get("by_tool", {}).items()
        for kind in sorted(kinds)
        if rep.baseline_is_stale(tool, kind)
    ]
    return rep


PERSONA_LABELS = {
    "xiaobu": "C 端小布",
    "mibao": "B 端米宝",
}

_KIND_LABELS = {
    "uncovered": "零用例（阻塞）",
    "missing_positive": "缺正向用例（阻塞）",
    "thin": "仅 1 条用例（只报告）",
    "thin_positive": "仅 1 条正向用例（只报告）",
}


def render_baseline_worklist(rep: CoverageReport, persona_label: str = "") -> str:
    """把存量豁免清单当**工作清单**打印：工具 + 缺口 + 归属 issue + 理由 + 销账方式。

    设计意图（issue #3575）：清单必须**可逐条销账**——
    「补完用例 → 删条目」；条目与当前缺口不一致会被判陈旧登记（job 红），
    所以清单只可能变短，不会变成免死金牌。
    """
    path = rep.baseline.get("path")
    out = ["=" * 68,
           f"  存量豁免工作清单（burn-down baseline）— {persona_label or rep.persona}",
           "=" * 68,
           f"清单文件: {Path(path).name if path else BASELINE_PATH.name}"
           f"（补完用例即删除对应条目；清单应单调缩短）"]
    entries = rep.baseline.get("entries") or []
    if not entries:
        out.append("  （空 —— 该端无存量缺口豁免，门禁为纯判据）")
        return "\n".join(out)
    for e in entries:
        tool, kind = str(e["tool"]), str(e["kind"])
        ids = rep.cases.get(tool) or []
        status = "已登记豁免" if rep.is_baselined(tool, kind) else "⚠️ 陈旧登记（当前不是该缺口）"
        out.append(f"  ▸ {tool}  [{_KIND_LABELS.get(kind, kind)}]  {status}")
        out.append(f"      归属: {e['issue']}   登记日期: {e['added']}")
        out.append(f"      理由: {e['reason']}")
        out.append(f"      现状: {len(ids)} 条用例" + (f" {', '.join(ids)}" if ids else "（无）"))
    stale = rep.baseline_missing
    if stale:
        out.append("")
        out.append("  ❌ 陈旧登记（销账后必须删除条目，否则本清单会越攒越多）:")
        for tool, kind in stale:
            out.append(f"     - {tool} [{kind}]")
    out.append("")
    out.append("  销账方式：补用例（migao-dev-flow §14.5）→ 删本文件对应条目 → CI 保持绿。")
    return "\n".join(out)

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
    thin_positive: list = field(default_factory=list)  # 仅 1 条且该条是正向（阈值：1 条）
    exempt: dict = field(default_factory=dict)        # tool → 显式豁免理由（非缺口）
    orphan_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 挂到了错的端 → 阻塞
    dangling_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 两端注册表都没有 → 阻塞
    baseline: dict = field(default_factory=dict)      # CoverageBaseline 或 {}（存量豁免，仅 --check）
    baseline_stale: list = field(default_factory=list)  # [(tool, kind)] 已销账但登记未删 → 阻塞
    baseline_missing: list = field(default_factory=list)  # 登记了但当前不是缺口 → 阻塞

    @property
    def covered(self) -> int:
        return len(self.tools) - len(self.uncovered)

    def uncovered_actionable(self) -> list:
        """排除显式豁免后的真缺口。"""
        return [t for t in self.uncovered if t not in self.exempt]

    # ── 存量豁免（burn-down baseline，issue #3575 决策）───────────────────────
    def blocking_gaps(self) -> list:
        """当前**结构性缺失**清单：[(tool, kind)]，kind ∈ {"uncovered", "missing_positive"}。

        kind 的区分是有意的（豁免条目要按真实形态登记，登记错判陈旧）：
          · `uncovered`        = 零用例（连证据都没有）；
          · `missing_positive` = 有用例、但**一条正向都没有**（只有对抗档/否定式断言）。
        """
        return [(t, "uncovered" if t in self.uncovered_actionable() else "missing_positive")
                for t in sorted(self.missing_positive)]

    def reporting_gaps(self) -> list:
        """**只报告**（不阻塞）的厚度不足清单：[(tool, kind)]，kind ∈ {"thin", "thin_positive"}。

        两种 kind 物理上等价（都只有 1 条用例），分开是为了让豁免条目能声明
        「这唯一一条是不是正向」—— 声明错了视为陈旧登记（见 `baseline_is_stale`）。
        """
        out = []
        for tool in self.thin_tools:
            out.append((tool, "thin_positive" if tool in self.thin_positive else "thin"))
        return out

    def all_gap_kinds(self) -> list:
        """全量缺口清单（含只报告的薄覆盖），既有语义锚点，也用于渲染工作清单。"""
        return sorted(set(list(self.blocking_gaps()) + self.reporting_gaps()))

    def is_baselined(self, tool: str, kind: str) -> bool:
        return kind in (self.baseline.get("by_tool", {}).get(tool, set()))

    def baseline_is_stale(self, tool: str, kind: str) -> bool:
        """已销账（当前不是缺口）但登记还在 → 陈旧登记，必须删（防白名单变垃圾场）。"""
        return kind in (self.baseline.get("by_tool", {}).get(tool, set())) \
            and (tool, kind) not in self.all_gap_kinds()

    def baseline_entry(self, tool: str, kind: str) -> dict:
        return (self.baseline.get("entries_by_tool", {}).get(tool, {}) or {}).get(kind) or {}

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
        if self.baseline_missing:
            problems.append(
                f"{len(self.baseline_missing)} 条存量豁免登记指向**当前不存在的缺口**"
                f"（销账后未删除 = 白名单会越攒越多）: "
                + ", ".join(f"{t}[{k}]" for t, k in self.baseline_missing)
            )
        new_gaps = [(t, k) for t, k in self.blocking_gaps() if not self.is_baselined(t, k)]
        if new_gaps:
            problems.append(
                f"{len(new_gaps)} 处**新出现**的结构性覆盖缺口（未登记存量豁免）: "
                + ", ".join(f"{t}[{k}]" for t, k in new_gaps)
                + f"\n     ⇒ 补用例（migao-dev-flow §14.5）；确有客观原因才登记进 "
                  f"{BASELINE_PATH.relative_to(REPO_ROOT)}（每条必须带 ≥4 字的 issue 号与理由）"
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
            if rep.positive.get(tool):
                rep.thin_positive.append(tool)   # 该唯一一条是正向（供豁免条目声明 kind）
        # 缺正向用例（结构性缺失 → 阻塞）：**被断言过**却没有一条证明"该工具能力可用"的用例
        # —— 包括两种形态：① 只有对抗档（拒绝/越权路径）② 只有否定式期望。
        # 零用例的工具也会落在这里，但 `blocking_gaps()` 用 uncovered 归类（避免同一件事报两遍）。
        if not rep.positive.get(tool) and tool not in exempt:
            rep.missing_positive[tool] = list(ids)
    return rep
