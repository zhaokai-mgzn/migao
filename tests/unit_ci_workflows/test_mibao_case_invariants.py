"""B 端（米宝）用例集静态不变式 —— 评测体系根本解 T1（#3483）

背景：C 端（#3266 后）已有完整静态校验（test_xiaobu_case_set.py：工具集真值 +
用例归属 + smoke 覆盖），**B 端对称面缺失**。B 端全量评测（normal/adversarial）
会把「mibao 专属 + 双端」用例全部带上，若某条期望在 B 端**没有任何可满足的分支**，
该用例每轮全量必挂 —— 此前只能靠真实 LLM 全量复测撞出来（差距分析 80 轮里反复
出现的"工具等价漂移"噪音即此类，每轮白烧 25-40 分钟）。本组在提交时秒级拦截。

探针实证（2026-09-14，#3483 T1）：
- AS-003/AS-005 的 `after_sales_manage or aftersale_create` 是 OR 分支 —— B 端走
  after_sales_manage、C 端走 aftersale_create，两端均可满足，合法；
- CH-011（跨用户订单查询拒绝，adversarial）期望 `customer_order_query`（小布专属、
  无 OR 分支）→ B 端必挂的固定噪音。它本质是 C 端数据隔离用例
  （merge_log: "C 端表单化交互方案"），已修为 `persona: xiaobu`。

与 C 端测试的关系：本文件只覆盖 B 端跑的一面（mibao 专属 + 双端）；C 端跑的一面
由 test_xiaobu_case_set.py 覆盖（选中用例不得含 B 端专属工具等）。
"""
# case_ids: OR-016, PR-019, PR-020, AS-003, AS-005, CH-011, FN-004, HR-003, DA-002, CU-003, PP-006, PR-021, PG-015, PG-016
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import eval_case_filter  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402
from eval_case_filter import (  # noqa: E402
    XIAOBU_TOOLS,
    PSEUDO_TOOLS,
    case_expectation_tools,
    case_persona,
    case_skip_reason,
    expectation_branches,
    mibao_real_toolset,
    skill_file,
    skill_files_without_tools,
)

CASES_DIR = REPO_ROOT / ".github" / "cases"
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
MIBAO_AGENT_SRC = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "agents"
                   / "agents" / "mibao.py")

# `none` = ontology 域用例的合法伪工具（ON-001~004：期望不调用工具，纯 data_checks 校验）。
# 只在本测试内按伪工具处理，不改 eval_case_filter.PSEUDO_TOOLS（那会牵动 C 端用例选择语义）。
PSEUDO_TOOL_NAMES = set(PSEUDO_TOOLS) | {"none"}

# 米宝声明的 skill（app/agents/agents/mibao.py 的 MIBAO_CONFIG.skill_names + fallback）。
# 解析真值/口径的唯一实现在 `eval_case_filter`（覆盖体检脚本与用例选择共用），
# 此处只做"声明齐全"的守卫。
MIBAO_SKILL_FILES = list(eval_case_filter.MIBAO_SKILL_FILES)


def _mibao_real_toolset() -> set:
    """从源码解析：米宝各 skill 工具并集（B 端可跑工具集的单一真值来源）。

    委托 `eval_case_filter.mibao_real_toolset()`（issue #3555 去重）——覆盖体检脚本
    `scripts/mibao_coverage.py` 用同一函数，两处口径不可能漂移。
    """
    tools = mibao_real_toolset()
    broken = skill_files_without_tools()
    assert not broken, f"米宝声明的 skill 解析不出工具（解析口径漂移/文件改名）: {broken}"
    assert tools, "B 端工具集解析为空 —— 覆盖矩阵会假绿"
    return tools


def _expectation_branch_tools(exp) -> list:
    """单个 expectation 的 OR 分支工具列表（委托 `eval_case_filter.expectation_branches`）。

    边界判定需要「至少一个分支可跑」，不能把分支合并后要求全部可跑
    （`after_sales_manage or aftersale_create` 合并后 aftersale_create 不在 B 端
    可跑集，但该期望在 B 端仍有合法路径）—— 故这里保留分支结构，共用同一解析实现。
    """
    return expectation_branches(exp)


def _bend_runnable_cases():
    """B 端全量会跑的用例：mibao 专属 + 双端（persona 缺省），去掉 skip 的纯前端用例。"""
    for c in load_case_dicts(str(CASES_DIR)):
        if case_skip_reason(c):
            continue
        if case_persona(c) == "xiaobu":
            continue
        yield c


class TestMibaoToolsetTruth:
    """B 端工具集真值：与 skill 源码一致，且不含 C 端专属工具（镜像 C 端真值测试）"""

    def test_mibao_toolset_contains_bend_admin_tools(self):
        """B 端管理工具必须全部在源码工具集内（防解析漏文件/漏常量）。"""
        real = _mibao_real_toolset()
        must_have = {
            "order_query", "order_manage", "order_create", "product_manage",
            "after_sales_manage", "customer_manage", "employee_manage",
            "role_manage", "dashboard_stats", "finance_api", "settings_manage",
            "category_manage", "inventory_manage", "knowledge_search",
        }
        missing = must_have - real
        assert not missing, f"B 端工具集缺 {sorted(missing)}（skill 源码解析不完整）"

    def test_every_declared_skill_file_is_parseable(self):
        """米宝**声明**的每个 skill 都必须存在且解析出工具（issue #3555 防假绿）。

        为什么需要：覆盖体检的"缺口 = 工具集 - 有用例的工具"。若某个 skill 文件改名/
        漏登记 → 它的工具静默从工具集消失 → 该能力的**零覆盖不再被报出来**，
        体检退化成"永远绿"。故"解析不到工具"必须报错，而不是当成"没有缺口"。
        """
        broken = skill_files_without_tools()
        assert not broken, (
            f"米宝声明的 skill 解析不出任何工具: {broken}\n"
            f"（文件改名/移动后请同步 eval_case_filter.MIBAO_SKILL_FILES）"
        )

    def test_declared_skills_cover_mibao_config(self):
        """MIBAO_CONFIG 声明的 skill 必须都在解析清单里（防新增 skill 漏出覆盖体检）。"""
        src = MIBAO_AGENT_SRC.read_text(encoding="utf-8")
        cfg = src[src.find("MIBAO_CONFIG"):]
        names = re.search(r"skill_names\s*=\s*\[(.*?)\]", cfg, re.S)
        assert names, "没能从 mibao.py 解析出 skill_names（本守卫失去意义，需同步解析口径）"
        declared = set(re.findall(r'"([a-z_]+)"', names.group(1)))
        fallback = re.search(r'fallback_skill\s*=\s*"([a-z_]+)"', cfg)
        if fallback:
            declared.add(fallback.group(1))
        covered = {p.stem.replace("_skill", "").replace("_agent", "")
                   for p in (skill_file(s) for s in MIBAO_SKILL_FILES)}
        missing = sorted(n for n in declared if n not in covered)
        assert not missing, (
            f"mibao.py 声明的 skill {missing} 不在覆盖体检解析清单里（其工具不会被体检）"
        )

    def test_toolset_size_above_floor(self):
        """工具集规模下界：源码解析静默缩水时体检会假绿，必须拦（不是覆盖门禁阈值）。"""
        real = _mibao_real_toolset()
        assert len(real) >= eval_case_filter.MIBAO_TOOLSET_MIN, (
            f"B 端工具集只解析到 {len(real)} 个（< 下界 {eval_case_filter.MIBAO_TOOLSET_MIN}）"
            f"—— 解析口径可能坏了；新增能力后请上调 MIBAO_TOOLSET_MIN"
        )

    def test_mibao_toolset_excludes_customer_only_tools(self):
        """B 端工具集不得混入小布专属工具（customer_* 系 / aftersale_create 等）。"""
        real = _mibao_real_toolset()
        c_only_expected = {
            "aftersale_create", "aftersale_query", "curtain_calc",
            "customer_address_query", "customer_logistics_track",
            "customer_order_query", "human_handoff",
        }
        leaked = real & c_only_expected
        assert not leaked, f"B 端工具集混入 C 端专属工具: {sorted(leaked)}"


class TestBendCaseToolBoundary:
    """B 端可跑性：mibao 专属 + 双端用例的**每个期望**至少一个 OR 分支工具在 B 端可跑集内。

    无工具形态（success=true / 中文断言）= 机器断言，两端都可判定，跳过。
    违反 = 该用例在 B 端全量每轮必挂（固定噪音 + 白烧真实 LLM），必须改为 OR 分支
    或标注 persona: xiaobu。
    """

    def test_every_expectation_has_bend_runnable_branch(self):
        bend_tools = _mibao_real_toolset()
        bad = {}
        for c in _bend_runnable_cases():
            for exp in c.get("expectations") or []:
                branches = _expectation_branch_tools(exp)
                if not branches:
                    continue
                if not (set(branches) & bend_tools):
                    bad.setdefault(c["id"], []).append(exp)
        assert not bad, (
            f"以下 B 端可跑用例存在 B 端无任何可满足分支的期望（全量每轮必挂）: {bad}"
        )

    def test_ch011_is_customer_only(self):
        """CH-011（跨用户订单查询拒绝）期望 customer_order_query —— 必须标 persona: xiaobu。

        回归防线：它本质是 C 端数据隔离用例；若被改成双端，B 端 adversarial 全量
        每轮必挂（探针实证的固定噪音源）。
        """
        ch = next(c for c in load_case_dicts(str(CASES_DIR)) if c.get("id") == "CH-011")
        assert case_persona(ch) == "xiaobu", "CH-011 必须是 C 端专属（persona: xiaobu）"

    def test_as003_as005_or_branch_is_legal(self):
        """AS-003/AS-005 的 OR 分支是合法形态，不得被误判（反向保护，防过度收紧）。"""
        bend_tools = _mibao_real_toolset()
        for cid in ("AS-003", "AS-005"):
            c = next(c for c in load_case_dicts(str(CASES_DIR)) if c.get("id") == cid)
            for exp in c.get("expectations") or []:
                branches = _expectation_branch_tools(exp)
                if not branches:
                    continue
                assert set(branches) & bend_tools, (
                    f"{cid} 期望 {exp} 在 B 端无可跑分支（OR 分支收紧过头了？）"
                )


class TestBendWriteToolSuccessAssertions:
    """B 端 `must_succeed` 的**工具集归属**（issue #3544：闸门对称面）。

    为什么必须补（闸门 bug 的对称面）：`test_xiaobu_case_set.py` 的
    `test_must_succeed_tools_are_customer_capabilities` 原先遍历**全部**用例、要求
    `must_succeed` 工具 ∈ XIAOBU_TOOLS —— 等于规定「B 端用例不得声明 must_succeed」，
    而它正是「调了 ≠ 成了」假绿的唯一机器防线（issue #3361）。修正为按 persona 过滤后，
    若没有本对称面，B 端用例就能 `must_succeed` 一个拼错/越界的工具名
    （断言永远无意义）而**无人拦截** —— C 端点名的「拼写错误或越界」风险会搬到 B 端。

    范围：B 端全量会跑的用例（mibao 专属 + 双端），与 `_bend_runnable_cases()` 一致。
    实证（2026-09-14）：`processing_item_manage` / `sku_update` 都在米宝 skill 工具集内，
    PP-006 / PR-021 因此可安全使用 `must_succeed` 升级假绿断言。
    """

    def test_must_succeed_tools_are_bend_capabilities(self):
        bend = _mibao_real_toolset()
        bad = []
        for c in _bend_runnable_cases():
            for m in c.get("must_succeed") or []:
                tool = m if isinstance(m, str) else (m or {}).get("tool")
                if tool and tool not in bend:
                    bad.append(f"{c['id']}: {tool}")
        assert not bad, (
            f"B 端可跑用例 must_succeed 声明了非 B 端工具（拼写错误或越界）: {bad}")

    def test_must_succeed_tool_matches_persona_boundary(self):
        """双向护栏：C 端专属工具不得出现在 B 端可跑用例的 must_succeed 里。"""
        c_only = {"aftersale_create", "curtain_calc", "customer_order_query",
                  "customer_address_query", "customer_logistics_track", "human_handoff"}
        bad = []
        for c in _bend_runnable_cases():
            for m in c.get("must_succeed") or []:
                tool = m if isinstance(m, str) else (m or {}).get("tool")
                if tool in c_only:
                    bad.append(f"{c['id']}: {tool}")
        assert not bad, (
            f"B 端可跑用例 must_succeed 了 C 端专属工具（B 端跑必挂 = 固定噪音）: {bad}")


class TestNoUnknownToolNames:
    """全 case（两端）期望引用的工具名必须存在于 B∪C 注册表。

    拼错/臆造工具名 = 期望永不满足（假红）或永不校验（假绿），且真实 LLM 评测
    只有在全量复测时才会暴露为"工具等价漂移"。
    """

    def test_all_expectation_tools_known(self):
        known = _mibao_real_toolset() | set(XIAOBU_TOOLS) | PSEUDO_TOOL_NAMES
        bad = {}
        for c in load_case_dicts(str(CASES_DIR)):
            unknown = case_expectation_tools(c) - known
            if unknown:
                bad[c["id"]] = sorted(unknown)
        assert not bad, f"引用未知工具名的用例（期望永不满足）: {bad}"


# ── B 端覆盖体检（scripts/mibao_coverage.py）与 C 端口径的一致性守卫（issue #3555）──
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from case_coverage import build_coverage_report  # noqa: E402


class TestMibaoCoverageReport:
    """B 端覆盖矩阵脚本必须与用例边界守卫**同一口径**（防「复制的平行实现」漂移）。

    issue #3555 要求 B 端体检复用既有契约（`eval_case_filter` 的纯函数 +
    `filter_by_persona`），而不是复制一套。本组测试把两处口径钉在一起：

      1. 脚本用的 B 端可跑用例集 == 本文件 `_bend_runnable_cases()` 的集合
         （`filter_by_persona(mibao)` 去 skip —— 与 `select_cases_for_persona` 一致）；
      2. 脚本的 B 端工具集 == 源码解析真值（`_mibao_real_toolset()`）；
      3. 脚本报出的 B 端**孤儿用例**（期望工具 B 端根本没有）必须为空 ——
         非空说明用例被挂到了错的端（历史上 CH-011 就是这一形态）。
    """

    def test_case_set_matches_boundary_guard(self):
        cases = load_case_dicts(str(CASES_DIR))
        rep = build_coverage_report(cases, "mibao", tools=_mibao_real_toolset())
        assert rep.cases_run == len(list(_bend_runnable_cases())), (
            "B 端覆盖体检用的用例集与用例边界守卫不一致（口径漂移）"
        )

    def test_toolset_matches_source_truth(self):
        cases = load_case_dicts(str(CASES_DIR))
        rep = build_coverage_report(cases, "mibao", tools=_mibao_real_toolset())
        assert rep.tools == _mibao_real_toolset(), (
            "B 端覆盖体检的工具集与源码解析真值不一致（口径漂移）"
        )

    def test_no_orphan_expectations_for_bend(self):
        """B 端可跑用例里不得有「期望工具 B 端根本没有」的用例。"""
        cases = load_case_dicts(str(CASES_DIR))
        rep = build_coverage_report(cases, "mibao", tools=_mibao_real_toolset())
        assert not rep.orphan_cases, (
            "以下 B 端可跑用例期望了 B 端不存在的工具（端点挂错/工具名拼错）:\n  "
            + "\n  ".join(f"{cid}: {tools}" for cid, tools in rep.orphan_cases)
        )

    def test_real_gaps_are_reported_not_papered_over(self):
        """回归网：B 端真实缺口必须被体检**报出来**（防阈值放水到看不见）。

        **缺口已销账（2026-09-14，issue #3568 / #3592）**：加工单域的
        `processing_order_query` / `processing_order_update` 此前是**零覆盖**的结构性
        缺口（体检在 pristine main 上 exit 2 报出、#3592 登记存量豁免）。本包已补正向
        用例 **PG-015**（查询）/ **PG-016**（更新状态），故断言由「必须仍在未覆盖清单里」
        改为**反向守卫** ——「**不得**重新变成未覆盖，且确实落在被覆盖集合里」。
        这是 fail-closed 的：若将来有人删掉这两条用例（或改坏它们的 `expectations`），
        本测试立刻变红，缺口不会被静默放回。
        """
        cases = load_case_dicts(str(CASES_DIR))
        rep = build_coverage_report(cases, "mibao", tools=_mibao_real_toolset())
        # 正向证据先立（防「不在 uncovered」只是因为解析两边都空 = 本测试空转假绿）。
        # `rep.cases` = tool → [用例 ID]（含对抗/否定）。
        assert rep.cases, "覆盖矩阵的 cases 为空 —— 解析疑似失效（本测试会空转假绿）"
        for tool in ("processing_order_query", "processing_order_update"):
            assert rep.cases.get(tool), f"{tool} 没有被任何用例覆盖（PG-015/PG-016 未生效）"
            assert tool not in rep.uncovered, (
                f"{tool} 又变回零覆盖（PG-015/PG-016 被删/被改坏？）——"
                f"B 端加工单域的正向覆盖不得回退")
        assert not rep.missing_positive, (
            "B 端出现「只有对抗/拒绝用例」的工具（需补正向用例）:\n  "
            + "\n  ".join(f"{t}: {ids}" for t, ids in sorted(rep.missing_positive.items()))
        )
