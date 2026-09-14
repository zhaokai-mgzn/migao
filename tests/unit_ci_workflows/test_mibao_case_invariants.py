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
# case_ids: OR-016, PR-019, PR-020, AS-003, AS-005, CH-011, FN-004, HR-003, DA-002, CU-003, PP-006, PR-021
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from render_cases import load_case_dicts  # noqa: E402
from eval_case_filter import (  # noqa: E402
    XIAOBU_TOOLS,
    PSEUDO_TOOLS,
    TOOL_NAME_RE,
    case_expectation_tools,
    case_persona,
    case_skip_reason,
)

CASES_DIR = REPO_ROOT / ".github" / "cases"
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# `none` = ontology 域用例的合法伪工具（ON-001~004：期望不调用工具，纯 data_checks 校验）。
# 只在本测试内按伪工具处理，不改 eval_case_filter.PSEUDO_TOOLS（那会牵动 C 端用例选择语义）。
PSEUDO_TOOL_NAMES = set(PSEUDO_TOOLS) | {"none"}

# 米宝声明的 skill（app/agents/agents/mibao.py 的 MIBAO_CONFIG.skill_names + fallback）
MIBAO_SKILL_FILES = [
    "order_skill", "product_skill", "aftersales_skill", "customer_skill",
    "staff_skill", "settings_skill", "data_skill", "knowledge_skill",
    "general_agent",  # fallback=general
]


def _skill_tools(skill_file: Path) -> set:
    """解析 skill 源码里的 *_TOOLS 列表字面量（纯文本，CI helper job 无 app 依赖）。"""
    src = skill_file.read_text(encoding="utf-8")
    found = set()
    for m in re.finditer(r"^[A-Z_]+_TOOLS\s*=\s*(\[[^\]]*\])", src, re.M):
        found |= set(re.findall(r'"([^"]+)"', m.group(1)))
    return found


def _mibao_real_toolset() -> set:
    """从源码解析：米宝各 skill 工具并集（B 端可跑工具集的单一真值来源）。"""
    tools = set()
    for name in MIBAO_SKILL_FILES:
        f = SKILLS_DIR / f"{name}.py"
        assert f.exists(), f"米宝声明的 skill 文件缺失: {f}"
        tools |= _skill_tools(f)
    return tools


def _expectation_branch_tools(exp) -> list:
    """单个 expectation 的 OR 分支工具列表（dict / 字符串形态；无工具形态返回 []）。

    与 eval_case_filter.case_expectation_tools 同一套提取语义，但**保留 OR 分支结构**
    —— 边界判定需要「至少一个分支可跑」，不能把分支合并后要求全部可跑
    （`after_sales_manage or aftersale_create` 合并后 aftersale_create 不在 B 端
    可跑集，但该期望在 B 端仍有合法路径）。
    """
    if isinstance(exp, dict):
        raw = str(exp.get("tool") or "")
    elif isinstance(exp, str):
        raw = exp
    else:
        return []
    branches = [b.strip() for b in re.split(r"\s+or\s+", raw, flags=re.IGNORECASE)]
    out = []
    for b in branches:
        tool = re.split(r"[\(:\s]", b, 1)[0]
        if tool and tool not in PSEUDO_TOOL_NAMES and TOOL_NAME_RE.match(tool):
            out.append(tool)
    return out


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
