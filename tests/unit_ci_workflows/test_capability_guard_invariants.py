"""能力自我否定族守卫的 **L0 静态不变式**（issue #3571，修复 #3389/#3477/#3443/#3476 复发 4 次）

## 为什么需要这一层

「能力自我否定族」= agent 在**工具明明可达**时断言自己做不到、并把顾客转人工
（核心转化路径被自己掐断）。复发 4 次的共同机制是**判据跟着名字/措辞走**：

  · 机制 1：`_has_order_write_tool(skill_name, registry)` 硬编码
    `skill_name != "customer_order" → False` —— **skill 名字面量白名单**；
  · 机制 2：转人工守卫只认 `skill_name in ("customer_order", "customer_aftersales")`；
  · 机制 3：正则/词表把字面间隔写死（`{0,8}` 窗口、精确子串）→ 措辞一变即漏。

因此第 5 次复发的最省事路径就是"**没把新 skill 加进白名单**"。本文件在**提交时（秒级、
零 LLM、零依赖）**把这个缺口焊死：判据**不可能**看到 skill 名字 —— 它只能读**工具注册表
事实**（本 skill 子集 / 全局注册表 / 工具属性 destructive·requires_confirmation）与
**会话状态事实**（跨轮 pending 锁、已接地商品、已校验下单参数）。

层归属：这是 `migao-dev-flow` §16.1 的 **L0**（结构性缺陷不允许流到 L2+ 真实 LLM 探测）。
行为面（真实跑 `execute_skill` 的跨 skill / 措辞变体 / 越权边界）由
`backend/ai-agent-service/tests/test_capability_denial_guard.py` 覆盖；本文件只锁**结构**。
"""
# case_ids: OR-021, OR-025, AS-009, CH-013, CH-014

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SKILL = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph"
              / "skills" / "base_skill.py")
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# 能力可达性 / 转人工守卫的**判据函数**（判据必须全在这里，禁止再内联回 execute_skill）
GUARD_PREDICATES = (
    "_order_write_tool_here",
    "_order_capability_available",
    "_registry_has_confirm_write_tool",
    "_handoff_guard_applies",
    "_order_flow_in_progress",
    "_flow_state_in_progress",
    "capability_denial_text_hit",
    "_capability_denial_reason",
)

# skill 名的**单一事实源**：从各 skill 模块的 `SkillConfig(name="...")` 声明里现取。
# ⚠️ 刻意不写死清单 —— 新增 skill 必须**自动**进入本不变式的覆盖（那正是复发机制）。
_SKILL_DECL_RE = re.compile(r'^\s*name="([a-z][a-z0-9_]*)"\s*,\s*$', re.M)


def _skill_names() -> set:
    names = set()
    for path in sorted(SKILLS_DIR.glob("*_skill.py")):
        names |= set(_SKILL_DECL_RE.findall(path.read_text(encoding="utf-8")))
    assert names, "未能从 skill 模块解析出任何 skill 名 —— 不变式失去意义（解析器需随声明格式更新）"
    return names


def _module() -> ast.Module:
    return ast.parse(BASE_SKILL.read_text(encoding="utf-8"))


def _functions(tree: ast.Module) -> dict:
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _body_without_docstring(fn: ast.AST) -> list:
    body = list(getattr(fn, "body", []) or [])
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def _string_constants(nodes: list) -> list:
    out = []
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Module):
                continue
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append(sub)
    return out


def _skill_name_literals(nodes: list, skill_names: set) -> list:
    """节点里作为**代码常量**出现的 skill 名（词边界比对，避免误伤事实名）。"""
    hits = []
    for const in _string_constants(nodes):
        for skill in skill_names:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(skill)}(?![A-Za-z0-9_])", const.value):
                hits.append(f"L{const.lineno}: {skill!r} in {const.value!r}")
    return hits


# ────────────────── 不变式 1：判据看不到 skill 名字 ──────────────────

def test_guard_predicates_exist():
    """判据必须**存在且独立成函数**（内联回 execute_skill 会重新变得不可锁、易漂移）。"""
    funcs = _functions(_module())
    missing = [name for name in GUARD_PREDICATES if name not in funcs]
    assert not missing, f"守卫判据函数缺失：{missing} —— 判据被内联/删除，L0 锁不住"


def test_guard_predicates_cannot_see_skill_name():
    """**核心不变式**：判据函数既不得接收 `skill_name`，也不得在函数体里引用它。

    只要判据看不到 skill 名，就**不可能**再出现"新增 skill 落进白名单缺口"这一复发机制
    （旧 `_has_order_write_tool(skill_name, registry)` 与
    `skill_name in ("customer_order", "customer_aftersales")` 都是这一形态）。
    """
    funcs = _functions(_module())
    offenders = []
    for name in GUARD_PREDICATES:
        fn = funcs[name]
        params = [a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs) + list(fn.args.posonlyargs)]
        if "skill_name" in params:
            offenders.append(f"{name}: 形参里出现 skill_name")
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == "skill_name":
                offenders.append(f"{name}: 函数体 L{node.lineno} 引用了 skill_name")
            if isinstance(node, ast.Attribute) and node.attr == "skill_name":
                offenders.append(f"{name}: 函数体 L{node.lineno} 引用了 .skill_name")
    assert not offenders, (
        "能力可达性判据又依赖 skill 名了（白名单复发形态，issue #3389/#3477/#3443/#3476）：\n"
        + "\n".join(offenders)
    )


def test_guard_predicates_have_no_skill_name_literal():
    """判据的**代码常量**里不得出现任何 skill 名（docstring 里写历史可以，判定里不行）。"""
    funcs = _functions(_module())
    names = _skill_names()
    offenders = []
    for fname in GUARD_PREDICATES:
        body = _body_without_docstring(funcs[fname])
        offenders += [f"{fname}: {hit}" for hit in _skill_name_literals(body, names)]
    assert not offenders, (
        "守卫判据里出现 skill 名字面量（等于把白名单换个地方写）：\n" + "\n".join(offenders)
    )


# ────────────────── 不变式 2：判据取自工具事实 / 会话状态 ──────────────────

def test_write_flow_coverage_derives_from_tool_attributes():
    """「业务办理型 skill」的覆盖必须**由工具属性派生**（destructive / requires_confirmation）。

    这样新增 skill 只要声明写工具就**自动**纳入守卫 —— 无需改任何名字清单；
    若有人把判据改回名字白名单，本测试必红。
    """
    funcs = _functions(_module())
    src = ast.unparse(funcs["_registry_has_confirm_write_tool"])
    for token in ("destructive", "requires_confirmation", "get_all_tools"):
        assert token in src, f"`_registry_has_confirm_write_tool` 不再读工具属性 {token!r} → 疑似退回白名单"
    # 该函数不得引用 skill 名（与不变式 1 正交的独立断言：它也可被单独改坏）
    assert not _skill_name_literals(_body_without_docstring(
        funcs["_registry_has_confirm_write_tool"]), _skill_names())


def test_order_capability_derives_from_tool_registry_facts():
    """下单能力可达性必须读**注册表事实**（本 skill 子集 / 全局注册表），不读 skill 名。"""
    funcs = _functions(_module())
    assert "ORDER_WRITE_TOOL" in ast.unparse(funcs["_order_write_tool_here"])
    avail = ast.unparse(funcs["_order_capability_available"])
    assert "_order_write_tool_here" in avail and "_tool_registered_globally" in avail, (
        "可达性判据不再是「本 skill 工具事实 ∨（在办流程状态 × 全局工具事实）」"
    )
    flow = ast.unparse(funcs["_order_flow_in_progress"])
    assert "pending_interact_skill" in flow or "_flow_state_in_progress" in flow, (
        "「在办下单」判据不再读跨轮状态（回落成措辞关键词驱动，正是 #3477 的漏网机制）"
    )


# ────────────────── 不变式 3：接线处不得再有旧白名单 ──────────────────

def _handoff_guard_tests(tree: ast.Module) -> list:
    """`execute_skill` 里「human_handoff 守卫」那个 If 的 test 节点。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Constant) and sub.value == "human_handoff":
                out.append(node.test)
                break
    return out


def test_handoff_guard_wiring_uses_fact_driven_predicate():
    """human_handoff 守卫的**适用性**必须走 `_handoff_guard_applies(...)`，不得再是 skill 名元组。"""
    tree = _module()
    tests = _handoff_guard_tests(tree)
    assert tests, "未定位到 human_handoff 守卫的接线（结构变了 → 本不变式需同步更新）"
    blob = " ".join(ast.unparse(t) for t in tests)
    assert "_handoff_guard_applies" in blob, (
        "human_handoff 守卫的适用性判据不再是事实驱动函数（疑似退回 `skill_name in (...)`）"
    )
    names = _skill_names()
    offenders = []
    for test in tests:
        offenders += _skill_name_literals([test], names)
        # 旧形态：`skill_name in ("customer_order", ...)` —— 左值 skill_name、右值是字面量集合
        for node in ast.walk(test):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                    and node.left.id == "skill_name":
                for op, comp in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)) and isinstance(
                            comp, (ast.Tuple, ast.List, ast.Set)):
                        offenders.append(
                            f"L{node.lineno}: skill_name in <字面量集合> —— 白名单复发形态")
    assert not offenders, (
        "转人工守卫的接线又出现 skill 名字面量白名单（#3477 机制 2）：\n" + "\n".join(offenders)
    )


def test_text_denial_wiring_uses_fact_driven_predicate():
    """文本级能力误宣纠正的**适用性**必须走 `_order_capability_available(...)`。"""
    tree = _module()
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)}
    assert "_order_capability_available" in calls, (
        "文本级纠正不再走事实驱动判据（旧形态：`_has_order_write_tool(skill_name, registry)`）"
    )
    assert "_has_order_write_tool" not in calls, (
        "旧的 skill 名白名单判据仍被调用 —— 必须彻底删除，不能两条判据并存"
    )


def test_capability_anchors_are_facts_not_wording():
    """「在办下单」的判定锚点必须是**事实**（跨轮状态 / 已校验参数），不是本轮措辞。

    措辞关键词（`_has_ordering_intent`）只能作为**兜底**：它**不得单独**让判据为真
    ——「本轮没说到"下单"」不能成为"不在办"的理由（那正是 #3477 的漏网机制：
    顾客改说「好的，就按这个来」就被判成不在办）。
    """
    funcs = _functions(_module())
    flow_src = ast.unparse(funcs["_order_flow_in_progress"])
    assert "pending_validated_input" in flow_src, "「已校验下单参数」这一最强在办证据丢失"
    assert "_flow_state_in_progress" in flow_src, "「跨轮在办状态」不再是判据的一部分"
    assert "_has_ordering_intent" in flow_src, "措辞兜底被删（需人工确认是否有意）"
    # 每个"含措辞兜底的 return 表达式"里必须**同时**带状态事实
    offenders = []
    for node in ast.walk(funcs["_order_flow_in_progress"]):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value_src = ast.unparse(node.value)
        if "_has_ordering_intent" in value_src and "_flow_state_in_progress" not in value_src:
            offenders.append(f"L{node.lineno}: return {value_src}")
    assert not offenders, (
        "措辞关键词成了在办下单的**充分**条件（#3477 复发形态）：\n" + "\n".join(offenders)
    )
