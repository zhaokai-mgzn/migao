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
# case_ids: OR-016, PR-019, PR-020, AS-003, AS-005, CH-011, FN-004, HR-003, DA-002, CU-003, PP-006, PR-021, PG-015, PG-016, DF-011
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
        """B 端工具集不得混入小布专属工具（customer_* 系 / aftersale_create 等）。

        ⚠️ 2026-09-19：`human_handoff` 已按用户裁定退场（模型不可达）⇒ 从"C 端专属工具"
        清单移除 —— 本清单的语义是「**某一端**有、另一端不得混入」，退场后它**两端都没有**，
        留着只会让"B 端混入了 C 端工具"这条判据对一个人人都不该有的名字产生僵尸命中面。
        """
        real = _mibao_real_toolset()
        c_only_expected = {
            "aftersale_create", "aftersale_query", "curtain_calc",
            "customer_address_query", "customer_logistics_track",
            "customer_order_query",
        }
        leaked = real & c_only_expected
        assert not leaked, f"B 端工具集混入 C 端专属工具: {sorted(leaked)}"
        # 自证：退场工具不得作为"任何一端"的工具出现在 B 端工具集里
        assert "human_handoff" not in real, "B 端工具集出现了已退场的转人工工具"


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
        """双向护栏：C 端专属工具不得出现在 B 端可跑用例的 must_succeed 里。

        （`human_handoff` 已于 2026-09-19 退场、两端都不可达 ⇒ 从本 C 端专属清单移除，
        与 `test_mibao_toolset_excludes_customer_only_tools` 同口径。）
        """
        c_only = {"aftersale_create", "curtain_calc", "customer_order_query",
                  "customer_address_query", "customer_logistics_track"}
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

    ⚠️ `skip_reason` 非空的用例**不参与**本检查（issue #3917 起生效）：被 skip 的
    用例不会跑，其期望引用未注册工具是**有意的休眠**（PG-013/015/016 引用已从
    注册表移除的 processing_order_*，工具类保留、恢复接入后启用）—— 若照扫，
    休眠引用会被判成「拼错/已删除」而恒红；「期望永不满足」只对**真实会跑**的
    用例构成假红/假绿。
    """

    def test_all_expectation_tools_known(self):
        known = _mibao_real_toolset() | set(XIAOBU_TOOLS) | PSEUDO_TOOL_NAMES
        bad = {}
        for c in load_case_dicts(str(CASES_DIR)):
            if case_skip_reason(c):
                continue
            unknown = case_expectation_tools(c) - known
            if unknown:
                bad[c["id"]] = sorted(unknown)
        assert not bad, f"引用未知工具名的用例（期望永不满足）: {bad}"


# ── B 端覆盖体检（scripts/mibao_coverage.py）与 C 端口径的一致性守卫（issue #3555）──
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from case_coverage import (  # noqa: E402
    BASELINE_PATH,
    _attach_baseline,
    build_coverage_report,
    load_baseline,
)


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
        """回归网：B 端**任何**结构性缺口都必须被体检报出并登记在清单里（防阈值放水到看不见）。

        **缺口已销账（2026-09-14，issue #3568 / #3592）**：加工单域的
        `processing_order_query` / `processing_order_update` 此前是**零覆盖**的结构性
        缺口（体检在 pristine main 上 exit 2 报出）。本包已补正向用例 **PG-015**（查询）
        / **PG-016**（更新状态），并**同步删除** `eval-coverage-baseline.yml` 里对应的
        两条 `uncovered` 阻断型条目（补用例与删条目必须同 PR，否则陈旧登记即红）。
        故本条不再硬编码工具名（销账后工具名会漂移）—— 见下不变式。
        **不硬编码具体工具**（加工单域已由 #3589 销账、order_manage 由 #3603 跟踪，
        工具集与缺口会随迭代变化）：断言的是**不变式** ——
          ① 体检报出的每个 blocking gap 都必须在存量豁免清单里有对应条目（不许隐形）；
          ② 清单里的**阻断型**条目必须对应当前真实缺口（陈旧即红，与运行时同判据）；
          ③ 判据没被削弱：人为注入一个零用例工具时必须被报出来。
        """
        cases = load_case_dicts(str(CASES_DIR))
        tools = _mibao_real_toolset()
        rep = _attach_baseline(build_coverage_report(cases, "mibao", tools=tools),
                               load_baseline(BASELINE_PATH, "mibao", tools))
        for tool, kind in rep.blocking_gaps():
            assert rep.is_baselined(tool, kind), (
                f"B 端结构性缺口 {tool}[{kind}] 未登记进存量豁免清单 —— "
                f"门禁会红，且清单里看不到它（补用例见 migao-dev-flow §14.5）"
            )
        assert not rep.baseline_stale_blocking, (
            f"清单有阻断型陈旧登记（销账后未删条目）: {rep.baseline_stale_blocking}"
        )
        synthetic = build_coverage_report([], "mibao", tools=tools | {"__synthetic_zero_case_tool__"})
        assert "__synthetic_zero_case_tool__" in synthetic.uncovered, (
            "零用例工具没被报出来 —— 判据被削弱了（check 恒绿的形态）"
        )


# ── 熔断类 truths：只能由 L0 契约测试证明，不能由端到端用例证明（#3679）──
# 归因实证（CI run 34838080233，DF-011）：端到端跑的是**真实 LLM + 真 HTTP**，
# 而「连续 N 次失败后 breaker 打开」的前提在「商品不存在」这类输入上**根本不成立** ——
# 404 是客户端错误，`http_client._do_call` 对 4xx 直接返回不抛异常（有意设计）
# ⇒ `failure_count` 恒 0、breaker 永不 OPEN。端到端只能证明"可观测的防御行为"，
# 契约本身必须落在 `CircuitBreaker` 的纯逻辑单测上（零 LLM、可注入假失败轨迹）。
_CIRCUIT_BREAKER_TEST_PATH = "backend/ai-agent-service/tests/unit/test_circuit_breaker.py"
BREAKER_TRUTHS = frozenset({"defense.breaker-threshold", "defense.breaker-no-retry"})


class TestCircuitBreakerTruthsHaveExecutableHome:
    """熔断类 truths 的机器断言**必须在 L0 契约测试里**（#3679 复发的静态拦截）。"""

    def test_breaker_cases_point_at_the_l0_contract_test(self):
        """引用了熔断 truths 的用例，`traces.tests` 必须指向真实存在的 L0 契约测试。

        为什么需要：DF-011 原先 `traces.tests` 指向
        `tests/test_performance_isolation.py` —— 该文件只覆盖并发/租户隔离，
        **一行熔断断言都没有**（`grep -c CircuitBreaker` = 0）。于是"用例声称有测试
        覆盖"这句话在追溯链上是假的：真出问题时没人能从 traces 找到断言。
        """
        cases = load_case_dicts(str(CASES_DIR))
        offenders = []
        seen = set()
        for c in cases:
            refs = set(c.get("truths_ref") or [])
            breaker_refs = sorted(refs & BREAKER_TRUTHS)
            if not breaker_refs:
                continue
            seen.add(c["id"])
            declared = set((c.get("traces") or {}).get("tests") or [])
            if _CIRCUIT_BREAKER_TEST_PATH not in declared:
                offenders.append(
                    f"{c['id']} 引用 {breaker_refs}，但 traces.tests 未声明 "
                    f"{_CIRCUIT_BREAKER_TEST_PATH}（现有: {sorted(declared) or '无'}）"
                )
        assert not offenders, (
            "熔断 truths 缺少机器断言归属（端到端证明不了熔断契约，见 #3679）：\n  "
            + "\n  ".join(offenders)
        )
        assert "DF-011" in seen, (
            "DF-011 不再声明熔断 truths —— 该用例是熔断契约的既有归属，"
            "删除即失去追溯（改语义请连带更新 BREAKER_TRUTHS）"
        )

    def test_declared_breaker_test_path_really_exists(self):
        """`traces.tests` 里声明的路径必须真的存在（防拼错路径的假追溯）。"""
        assert (REPO_ROOT / _CIRCUIT_BREAKER_TEST_PATH).exists(), (
            f"{_CIRCUIT_BREAKER_TEST_PATH} 不存在 —— traces.tests 指向了不存在的文件"
        )

    def test_df011_does_not_claim_an_unreachable_expectation(self):
        """DF-011 回归网：不得把 `product_detail` 写回期望。

        实证（run 34838080233，rounds=6）：agent 对「查不存在的ID-00X」调的是
        `product_search`，`product_detail` **一次都没被调用**（product skill 两个工具都有，
        属模型选择）⇒ 期望 `product_detail` 是恒不满足的误写，每次全量必红。
        """
        df011 = next(c for c in load_case_dicts(str(CASES_DIR)) if c.get("id") == "DF-011")
        tools = case_expectation_tools(df011)
        assert "product_detail" not in tools, (
            "DF-011 期望又写回了 product_detail —— 该工具在此链路中从未被调用过"
            "（误写会制造恒红噪音，见 #3679）"
        )
