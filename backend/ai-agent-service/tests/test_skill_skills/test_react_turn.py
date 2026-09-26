# case_ids: CH-013, CH-014, CH-015
"""写调用门禁链的可组合性判据（issue #4081，**零行为变更**的结构包）。

被测契约（源头：issue #4081 = 「关联 #4043」的 S6 条）：

1. **顺序单一处**：写调用前的门禁由**同一处声明的有序列表**驱动，每条门禁带自己的身份名；
   调用点只做「按序求值 + 首个非空即拦」。改前顺序只由一串 `if` 语句的先后表达，
   插一条/挪一条**没有任何单一处可读**，也没有任何判据会红。
2. **确认门禁只求一次**：`_requires_confirmation(tool, args, last_user_msg)` 在同一次工具调用内
   只求值 **1** 次（改前 3 次：同一 tool / 同一 args / 同一 msg ⇒ 结果必然相同）。
3. **会话状态往返收敛**：门禁链内 `SessionStateStore().load()` **至多 1 次**
   （改前本场景实测 6 次内联 load；两个门禁 helper 内部各 1 次属既有语义、不在本包射程内）。
4. **话术逐字不变**：门禁区（= 链上每条门禁的函数体）的**字符串字面量集合**与本包落地时
   冻结的清单逐字相等 —— 这是「零行为变更」的机械形态，改一个字的用户可见文案即红。

为什么要有这个文件：这类「拆分 / 重组」最常见的失败形态不是崩，而是**判据自己选择沉默** ——
门禁被搬走了、列表里少了一条，而没有任何东西变红（顺序隐式时尤其如此：删掉一条 `if`，
日志里只是"少拦了一次"）。故四条判据**全部 fail-closed**：取不到链表 / 取不到门禁定义 /
求值探针缺席 ⇒ **报错**，不静默通过。

⚠️ 本文件只断言**结构 + 求值计数 + 字面量冻结**；行为面（每条门禁拦什么、话术说什么）由既有
用例（CH-013/CH-014/CH-015 等）与全量单测覆盖 —— 结构守卫**不替代**行为验证。

## 红证（本文件自带变异语料，另有实测）

| 注入 | 期望 |
|---|---|
| 从链表里摘掉任一条门禁（逐条实跑） | `test_write_gate_chain_is_a_single_ordered_table` 报出该门禁名 |
| 链表里两条门禁互换 | 同上，报「声明顺序 ≠ 定义顺序」 |
| 把「首个非空即拦」翻成 `is None` | 报「循环体里没有首个非空即拦」 |
| 把链表赋值改名（顺序又变隐式） | 报「链表不存在」 |
| 某条门禁自己 `SessionStateStore().load(...)`（绕过共享快照） | `test_write_gate_region_loads_session_state_at_most_once` 报 bypass > 0 |
| 共享快照不缓存（每次 load） | 同上，报共享 load > 1 |
| 把确认判定复制回第二处 | `test_confirmation_is_evaluated_once_per_tool_call` 报 2 次 |
| 改一个字的门禁话术 | `test_write_gate_literal_set_is_frozen` 报增删的字面量 |
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.skills.execution import react_turn as react_turn_mod

SRC = (Path(__file__).resolve().parents[2]
       / "app" / "graph" / "skills" / "execution" / "react_turn.py")

#: 链表的**唯一锚点**（判据靠它定位"顺序声明处"；改名即红，不许悄悄换掉）
CHAIN_NAME = "_WRITE_GATE_CHAIN"
#: 链上每条门禁的身份名前缀（`_gate_session_state` 是共享快照加载器，不是门禁）
GATE_PREFIX = "_gate_"
LOADER_NAME = "_gate_session_state"
#: 求值探针（生产恒为 None；测试把它设成 `list.append` 以机械观测"每条门禁都真的被求值"）
HOOK_NAME = "GATE_EVAL_HOOK"

#: 冻结的门禁清单（**顺序即语义**）。摘掉/挪动任何一条都必须同步改这里并写明理由 ——
#: 改前这套顺序只由语句先后表达（`_blocked`/`_blocked2`/`_blocked_q`/… 各自命名），
#: 插在哪、为什么插在那，没有任何单一处声明。
EXPECTED_GATES = (
    "write_input_recovery",      # 缺参等待期：不放行注定失败的写、不放行逐字重发的同一张卡
    "card_loop",                 # 同一张卡重复下发（死循环）
    "tool_available",            # 工具解析：注册表里没有 ⇒ 拦（并给可执行恢复路径）
    "quantity_choice",           # 产出层：顾客已报数量 → 不得给"用量/褶皱倍数"选项
    "form_prefill_fidelity",     # 产出层：收货信息预填保真（interact 是只读工具，单独接）
    "curtain_calc_dimension",    # 产出层：算料前提（只读工具，读写分流之前）
    "masked_phone_write",        # 写侧：掩码形态手机号（必须在 tool 解析之后 —— 见链表注释）
    "validation_failed_write",   # 写侧：校验失败禁止写（**故意在确认门禁之外、之前**）
    "handoff_guard",             # 兜底：在办流程中禁止"无信号误转人工"
    "order_grounding",           # 下单接地：本会话没查过商品详情不许下单
    "write_confirmation",        # 确认门禁（链尾：它要落 pending 状态并给可执行下一步）
)


# ── 静态判据：链表 / 门禁实现 / 顺序 / 分发循环 ────────────────────────────────

def _require(node, what: str):
    """fail-closed：取不到被测对象就**报错**（不静默通过）。

    ⚠️ 刻意用 `raise` 而不是 `assert x is not None` —— 后者是本仓判定表里的**弱断言形态**
    （`.github/growth_gate.py::_WEAK_PATTERNS`，新增测试文件会被 `gate` 的 `--check-weak` 扫）。
    """
    if node is None:
        raise AssertionError(f"{what} 不存在（fail-closed，不静默通过）")
    return node


def _find_react_turn(tree: ast.Module):
    return next((n for n in tree.body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "react_turn"), None)


def _find_router(react):
    """`react_turn` **内任意深度**的 `_run_one_tool`（工具调用执行点）。

    ⚠️ 必须递归找：它定义在 `if/else → for iteration → else` 的嵌套里，不是 `react.body` 的
    直接子节点 —— 只扫直接子节点会得到「找不到」并把**每一次**判据都变成假红（本文件首版即
    此错，靠红证当场发现）。
    """
    return next((n for n in ast.walk(react)
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_one_tool"), None)


def _router_of(src: str):
    react = _require(_find_react_turn(ast.parse(src)), "react_turn 函数")
    return _require(_find_router(react), "_run_one_tool（工具调用执行点）")


def _chain_assign(router):
    return next((s for s in router.body
                 if isinstance(s, ast.Assign) and len(s.targets) == 1
                 and isinstance(s.targets[0], ast.Name)
                 and s.targets[0].id == CHAIN_NAME
                 and isinstance(s.value, (ast.Tuple, ast.List))), None)


def _chain_entries(router):
    """链表 → [(身份名, 实现函数名)]；取不到返回 None（fail-closed 由调用方报错）。"""
    stmt = _chain_assign(router)
    if stmt is None:
        return None
    entries = []
    for elt in stmt.value.elts:
        if not (isinstance(elt, ast.Tuple) and len(elt.elts) == 2
                and isinstance(elt.elts[0], ast.Constant)
                and isinstance(elt.elts[0].value, str)
                and isinstance(elt.elts[1], ast.Name)):
            return []
        entries.append((elt.elts[0].value, elt.elts[1].id))
    return entries


def _gate_defs(router):
    """`_run_one_tool` 里定义的**门禁实现**（`_gate_*`，共享快照加载器不算门禁），按定义顺序。"""
    return [n.name for n in router.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith(GATE_PREFIX)
            and n.name != LOADER_NAME]


def _dispatcher_loop(router):
    """由链表驱动的「按序求值」循环。"""
    return next((s for s in router.body
                 if isinstance(s, ast.For) and isinstance(s.iter, ast.Name)
                 and s.iter.id == CHAIN_NAME), None)


def _is_not_none(test) -> bool:
    return (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.IsNot)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value is None)


def _first_block_guard(loop):
    """「首个非空即拦」那条 `if`：`is not None` 判定 **且** 体末是 `return`。

    ⚠️ 必须带「体末是 return」这一半：同一循环里还有求值探针的 `if GATE_EVAL_HOOK is not None:`，
    只按 `is not None` 取会选中探针分支（本文件首版即此错：红证注入打到了探针那一行）。
    """
    return next((s for s in loop.body
                 if isinstance(s, ast.If) and _is_not_none(s.test)
                 and s.body and isinstance(s.body[-1], ast.Return)), None)


def audit_chain(src: str) -> list:
    """审一条源码的「门禁链可组合性」，返回违规清单（空 = 通过）。

    抽成纯函数是为了能喂**变异语料**：证明每条判据真的会红（不是永远绿的空判据）。
    """
    problems: list = []
    tree = ast.parse(src)
    react = _find_react_turn(tree)
    if react is None:
        return ["react_turn 函数不存在 ⇒ 判据无法定位被测对象（fail-closed，不静默通过）"]
    router = _find_router(react)
    if router is None:
        return ["_run_one_tool 不存在（工具调用执行点被改名/搬走）⇒ fail-closed"]

    defs = _gate_defs(router)
    table = _chain_entries(router)
    if table is None:
        return [f"门禁链表 `{CHAIN_NAME}` 不存在 ⇒ 顺序重新变成隐式的（fail-closed 报错）"]
    names = [n for n, _ in table]
    impls = [c for _, c in table]

    if len(set(names)) != len(names):
        problems.append(f"门禁身份名重复：{names}")
    if names != list(EXPECTED_GATES):
        problems.append(
            "链表顺序/清单与冻结的门禁清单不一致（顺序即语义：摘掉/挪动一条都必须显式改这里）\n"
            f"  期望 = {list(EXPECTED_GATES)}\n  实际 = {names}")
    unlisted = [d for d in defs if d not in impls]
    if unlisted:
        problems.append(f"定义了但**没进链**的门禁（摘掉即静默放行、且没有任何东西会红）：{unlisted}")
    dangling = [c for c in impls if c not in defs]
    if dangling:
        problems.append(f"链里列了、但 `_run_one_tool` 里没有这个实现：{dangling}")
    in_def_order = [d for d in defs if d in impls]
    if in_def_order != impls:
        problems.append(
            "链表的声明顺序 ≠ 门禁的定义顺序 ⇒ 读代码得到的顺序与**求值顺序**不一致\n"
            f"  声明 = {impls}\n  定义 = {in_def_order}")

    loop = _dispatcher_loop(router)
    if loop is None:
        problems.append(f"没有「按 `{CHAIN_NAME}` 顺序求值」的循环 ⇒ 列表不驱动求值（等于没收敛）")
        return problems
    if not (isinstance(loop.target, ast.Tuple) and len(loop.target.elts) == 2
            and all(isinstance(e, ast.Name) for e in loop.target.elts)):
        problems.append("循环变量不是 (身份名, 实现) 二元组")
        return problems
    gate_var = loop.target.elts[1].id
    evaluated = [s for s in loop.body
                 if isinstance(s, (ast.Expr, ast.Assign))
                 and isinstance(getattr(s, "value", None), ast.Await)
                 and isinstance(s.value.value, ast.Call)
                 and isinstance(s.value.value.func, ast.Name)
                 and s.value.value.func.id == gate_var]
    if not evaluated:
        problems.append(f"循环体没有求值 `{gate_var}()` ⇒ 列表只是摆设")
    # 「首个非空即拦」= 一个 `if <block> is not None:` 且其体末是 `return <block>`
    # （注意别选中同在该循环里的求值探针分支：那个 If 的体不是 return）
    guard = _first_block_guard(loop)
    if guard is None:
        problems.append("循环体里没有「首个非空即拦」（`if <block> is not None: ...`）")
    else:
        ret = guard.body[-1] if guard.body else None
        if not (isinstance(ret, ast.Return) and isinstance(ret.value, ast.Name)
                and isinstance(guard.test.left, ast.Name) and ret.value.id == guard.test.left.id):
            problems.append("「首个非空即拦」返回的不是该门禁的 block 本身 ⇒ 不是 fail-closed")
    if not any(isinstance(s, ast.If) and isinstance(s.test, ast.Compare)
               and isinstance(s.test.left, ast.Name) and s.test.left.id == HOOK_NAME
               for s in loop.body):
        problems.append(
            f"求值探针 `{HOOK_NAME}` 不在循环里 ⇒ 「链上每条门禁都真的被求值」无法机械观测"
            f"（`{HOOK_NAME}` 默认 None，生产零行为改变）")
    return problems


def audit_nonlocal_coverage(src: str) -> list:
    """闭包向外层锚点写值时的 `nonlocal` 覆盖审计（空 = 通过）。

    **为什么要有这条**（本包实测的静默形态）：把门禁体搬进闭包后，闭包内
    `_relocked_this_round = True` 若**漏了 `nonlocal`**，赋值只会创建闭包的**新局部** ——
    不报错、不警告，轮末 `pending_skill` 被覆盖回原 skill（回锁白做）。首版即漏了门禁 3
    的那一处，由行为用例 `tests/test_order_cross_skill_tool_not_found.py` 抓到；
    本判据把它变成**机械**可判的（不依赖某条行为用例恰好覆盖到那条路径）。

    反向同样要守：`nonlocal <非 react_turn 参数>` 会撞 `tests/unit/test_execute_skill_split.py`
    的 `nonlocal` 目标守卫（首版把 `tool` 写成 nonlocal 即此形态 ⇒ 改法是把纯查表提到链前）。
    """
    problems: list = []
    react = _require(_find_react_turn(ast.parse(src)), "react_turn 函数")
    params = ({a.arg for a in react.args.args}
              | {a.arg for a in react.args.kwonlyargs})
    router = _require(_find_router(react), "_run_one_tool（工具调用执行点）")
    for node in router.body:
        if not (isinstance(node, ast.AsyncFunctionDef)
                and node.name.startswith(GATE_PREFIX) and node.name != LOADER_NAME):
            continue
        declared = {n for sub in ast.walk(node) if isinstance(sub, ast.Nonlocal)
                    for n in sub.names}
        assigned = {sub.id for sub in ast.walk(node)
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store)}
        lost = sorted((assigned & params) - declared)
        if lost:
            problems.append(
                f"{node.name} 给 react_turn 的锚点 {lost} 赋值却没声明 nonlocal ⇒ 置位静默丢失"
                f"（不报错、不警告，值只落在闭包自己的局部里）")
        stray = sorted(declared - params)
        if stray:
            problems.append(
                f"{node.name} 声明了 `nonlocal {stray}`，而它们不是 react_turn 的参数 ⇒ "
                f"撞 tests/unit/test_execute_skill_split.py 的 nonlocal 目标守卫")
    return problems


def _mutate(src: str, old: str, new: str) -> str:
    """变异注入（红证用）：命中数必须恰好 1，否则**报错**（防止注入落空后把"绿"当证据）。"""
    assert src.count(old) == 1, f"变异注入未生效（命中 {src.count(old)} 次）：{old!r}"
    return src.replace(old, new)


def _entry_lines(src: str) -> dict:
    """链表每一行的**源码原文**（按实现函数名索引）—— 由 AST 定位，不靠文本猜测。"""
    router = _router_of(src)
    stmt = _require(_chain_assign(router), f"链表 {CHAIN_NAME}")
    lines = src.splitlines()
    out = {}
    for elt in stmt.value.elts:
        if isinstance(elt, ast.Tuple) and isinstance(elt.elts[1], ast.Name):
            out[elt.elts[1].id] = lines[elt.lineno - 1]
    return out


class TestWriteGateChainIsOneOrderedTable:
    """① 顺序单一处：链表完整、每条门禁都有实现、声明顺序 = 求值顺序。"""

    def test_write_gate_chain_is_a_single_ordered_table(self):
        problems = audit_chain(SRC.read_text(encoding="utf-8"))
        assert problems == [], "门禁链可组合性判据报错：\n- " + "\n- ".join(problems)

    def test_every_gate_is_a_real_definition_not_a_name_in_a_comment(self):
        """反向：表里的每个实现名都必须是 `_run_one_tool` 里真实的 `async def`。

        没有这条，「表在、实现被删」可以同时骗过人类的 grep 与上一条（表本身仍自洽）。
        """
        src = SRC.read_text(encoding="utf-8")
        router = _router_of(src)
        table = _require(_chain_entries(router), f"链表 {CHAIN_NAME}")
        for _, impl in table:
            node = _require(next((n for n in router.body
                                  if isinstance(n, ast.AsyncFunctionDef) and n.name == impl), None),
                            f"链表里的 {impl}（须是 _run_one_tool 内的 async def）")
            assert len(node.body) > 0, f"{impl} 是空函数体 ⇒ 门禁空转"

    def test_guard_goes_red_when_a_gate_is_dropped_from_the_chain(self):
        """负例①：从链表里摘掉一条门禁 ⇒ 判据必报（摘掉即静默放行的形态）。"""
        src = SRC.read_text(encoding="utf-8")
        lines = _entry_lines(src)
        for impl in ("_gate_masked_phone_write", "_gate_card_loop", "_gate_write_confirmation"):
            dropped = _mutate(src, lines[impl] + "\n", "")
            problems = audit_chain(dropped)
            assert problems, f"摘掉 {impl} 后判据仍全绿 —— 这是空判据"
            assert any("不一致" in p or impl in p for p in problems), (
                f"摘掉 {impl} 后判据没点名它：{problems}")

    def test_guard_goes_red_when_two_gates_are_swapped(self):
        """负例②：链表里两条**相邻**门禁互换 ⇒ 报「声明顺序 ≠ 定义顺序」（顺序即语义）。"""
        src = SRC.read_text(encoding="utf-8")
        lines = _entry_lines(src)
        a, b = lines["_gate_form_prefill_fidelity"], lines["_gate_curtain_calc_dimension"]
        swapped = _mutate(src, a + "\n" + b, b + "\n" + a)
        problems = audit_chain(swapped)
        assert any("声明顺序 ≠ 门禁的定义顺序" in p for p in problems), (
            f"互换两条门禁后判据没报顺序问题：{problems}")

    def test_guard_goes_red_when_first_block_no_longer_wins(self):
        """负例③：把「首个非空即拦」翻成 `is None` ⇒ fail-closed 语义被破坏，必报。"""
        src = SRC.read_text(encoding="utf-8")
        router = _router_of(src)
        loop = _require(_dispatcher_loop(router), "由链表驱动的分发循环")
        guard = _require(_first_block_guard(loop), "「首个非空即拦」")
        line = src.splitlines()[guard.lineno - 1]
        broken = _mutate(src, line, line.replace("is not None", "is None"))
        problems = audit_chain(broken)
        assert any("首个非空即拦" in p for p in problems), (
            f"「首个非空即拦」被翻反后判据没报：{problems}")

    def test_guard_goes_red_when_the_chain_table_is_renamed(self):
        """负例④：链表改名（顺序又变隐式）⇒ 判据报「链表不存在」，不静默通过。"""
        src = SRC.read_text(encoding="utf-8")
        renamed = _mutate(src, f"{CHAIN_NAME} = (", "_SOMETHING_ELSE = (")
        problems = audit_chain(renamed)
        assert any("链表" in p for p in problems), f"链表改名后判据没报：{problems}"


class TestGateClosuresPublishStateCorrectly:
    """③ 闭包 ↔ 外层锚点：向 `react_turn` 的参数写值必须声明 `nonlocal`（否则静默丢失）。"""

    def test_every_closure_declares_the_nonlocals_it_writes(self):
        problems = audit_nonlocal_coverage(SRC.read_text(encoding="utf-8"))
        assert problems == [], "闭包 nonlocal 覆盖审计报错：\n- " + "\n- ".join(problems)

    def test_audit_goes_red_when_a_closure_forgets_its_nonlocal(self):
        """负例①：删掉门禁 3 的 `nonlocal _relocked_this_round` ⇒ 必报（回锁置位丢失形态）。"""
        src = SRC.read_text(encoding="utf-8")
        dropped = _mutate(src, "nonlocal _relocked_this_round\n                        if tool is None:",
                          "if tool is None:")
        problems = audit_nonlocal_coverage(dropped)
        assert any("_relocked_this_round" in p and "静默丢失" in p for p in problems), (
            f"删掉 nonlocal 后判据没报：{problems}")

    def test_audit_goes_red_when_a_closure_forgets_a_blocked_args_nonlocal(self):
        """负例②：删掉确认门禁的 `nonlocal _no_card_blocked_args` ⇒ 必报（补卡兜底失效形态）。"""
        src = SRC.read_text(encoding="utf-8")
        # 用**相邻两行**做唯一锚点：`nonlocal _no_card_blocked_args` 在 `_run_one_tool` 自己的
        # 声明里也有一处（只匹配单行会命中 2 次 ⇒ `_mutate` 会当场报"注入未生效"）
        dropped = _mutate(src,
                          "nonlocal _no_card_blocked_args\n                        nonlocal _no_card_blocked_tool\n",
                          "nonlocal _no_card_blocked_tool\n")
        problems = audit_nonlocal_coverage(dropped)
        assert any("_no_card_blocked_args" in p for p in problems), (
            f"删掉 nonlocal 后判据没报：{problems}")

    def test_audit_goes_red_on_a_nonlocal_that_is_not_a_param(self):
        """负例③：把 `nonlocal tool` 加回来（本包首版的形态）⇒ 必报（撞既有结构守卫）。"""
        src = SRC.read_text(encoding="utf-8")
        stray = _mutate(src, "                        if tool is None:",
                        "                        nonlocal tool\n                        if tool is None:")
        problems = audit_nonlocal_coverage(stray)
        assert any("不是 react_turn 的参数" in p for p in problems), (
            f"加了 `nonlocal tool` 后判据没报：{problems}")


# ── 运行期判据：顺序 / 可达性 / 求值计数 ───────────────────────────────────────

def _make_state(**overrides):
    state = {
        "messages": [HumanMessage(content="把这条商品下架")],
        "tenant_id": 1,
        "user_id": 100,
        "session_id": "sess_4081",
        "role": "admin",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
        "suggestions": [],
    }
    state.update(overrides)
    return state


class _CountingStore:
    """`SessionStateStore` 替身：记下每次 `load` 的**调用栈**（用于把 load 归因到门禁链）。

    归因口径（与判据同源）：
      · `in_tool_call` —— 栈里有 `_run_one_tool`（= 这一次工具调用内发生的 load）；
      · `shared`       —— 直接调用者是共享快照加载器 `_gate_session_state`；
      · `bypass`       —— 直接调用者是**某条门禁自己**（绕过共享快照 = 往返又变多）。
    """

    def __init__(self, shared: dict, calls: list):
        self._shared = shared
        self._calls = calls

    async def load(self, sid):
        frames = [f.function for f in inspect.stack()]
        self._calls.append(frames)
        return dict(self._shared)

    async def commit(self, sid, full):
        self._shared.clear()
        self._shared.update(full or {})
        return True

    async def clear(self, sid):
        return True


def _drive_write_call(*, trace: list | None = None, confirm_calls: list | None = None,
                      store_state: dict | None = None,
                      last_user_msg: str = "把这款窗帘下架"):
    """驱动一次 B 端写调用（`product_manage`）。

    配方沿用 `tests/test_b_end_confirm_card_fallback.py`（零真实 LLM）：假 LLM 先回一条
    写工具调用、再回纯文本；registry 只挂真实 B 端写工具 + interact；`_execute_tool_safe`
    用假实现记录调用（被拦下的写**不得**真的执行）。
    """
    from app.graph.skills.base_skill import execute_skill
    from app.tools.interact import InteractTool
    from app.tools.product_manage import ProductManageTool

    executed: list = []
    load_calls: list = []

    async def fake_execute(tool, args, ctx, state):
        executed.append(tool.name)
        return json.dumps({"success": True, "data": {}}), {"success": True, "data": {}}

    shared: dict = {} if store_state is None else store_state
    store = _CountingStore(shared, load_calls)

    # 默认末条消息刻意**不是**确认措辞：`_requires_confirmation` 才会判"需确认"
    # ⇒ 稳定走到链尾的确认门禁并被拦下（否则写会被放行、计数无意义）。
    # 点卡路径则把 `last_user_msg` 传成上一轮落库的 confirmValue（精确匹配 ⇒ 放行）。
    history = [HumanMessage(content="把这条商品下架"),
               HumanMessage(content=last_user_msg)]
    call = MagicMock(spec=AIMessage)
    call.content = ""
    call.tool_calls = [{"name": "product_manage",
                        "args": {"action": "toggle_status",
                                 "product_id": "prod_a1b2c3d4", "status": "off_sale"},
                        "id": "t1"}]
    final = MagicMock(spec=AIMessage)
    final.content = "好的，我先把操作卡片发给您"
    final.tool_calls = []

    with contextlib.ExitStack() as stack:
        mem_cls = stack.enter_context(patch("app.memory.session_memory.SessionMemory"))
        stack.enter_context(patch("app.memory.session_state_store.SessionStateStore",
                                  side_effect=lambda *a, **k: store))
        get_breaker = stack.enter_context(patch("app.graph.skills.base_skill.get_breaker"))
        get_llm = stack.enter_context(patch("app.graph.skills.base_skill.get_skill_llm"))
        create_reg = stack.enter_context(
            patch("app.graph.skills.base_skill.create_skill_registry"))
        stack.enter_context(patch("app.graph.skills.base_skill.set_tool_context"))
        stack.enter_context(patch("app.graph.skills.base_skill._execute_tool_safe",
                                  fake_execute))
        if trace is not None:
            stack.enter_context(patch.object(react_turn_mod, HOOK_NAME, trace.append))
        if confirm_calls is not None:
            real_confirm = react_turn_mod._requires_confirmation

            def _spy(tool, args, msg):
                confirm_calls.append((getattr(tool, "name", "?"), str(msg)[:20]))
                return real_confirm(tool, args, msg)

            stack.enter_context(
                patch.object(react_turn_mod, "_requires_confirmation", _spy))

        registry = MagicMock()
        registry.get_langchain_tools.return_value = []
        registry.get_tool.side_effect = lambda n: (
            ProductManageTool() if n == "product_manage"
            else (InteractTool() if n == "interact" else None))
        create_reg.return_value = registry
        breaker = MagicMock()

        async def _pt(fn):
            return await fn()

        breaker.call = _pt
        get_breaker.return_value = breaker
        llm = MagicMock()
        llm.bind_tools.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=[call, final])
        get_llm.return_value = llm
        mem_cls.return_value.set_pending_skill = AsyncMock(return_value=True)
        out = asyncio.run(execute_skill(
            state=_make_state(messages=history),
            skill_name="product",
            tool_names=["product_manage"],
            system_prompt="你是米宝（B 端商品助手），写操作必须先展示确认卡并取得用户确认。",
        ))
    return out, executed, load_calls


class TestChainIsDrivenByTheTableAtRuntime:
    """② 运行期：链上每条门禁都真的被求值，且顺序 = 链表的声明顺序。"""

    def test_gates_are_evaluated_in_the_declared_order(self):
        trace: list = []
        out, executed, _ = _drive_write_call(trace=trace)
        # 用例前提自断言（fail-closed）：这次调用确实走到了链尾的确认门禁并被拦下
        assert "confirmation_required_no_card" in str(out), (
            f"用例前提不成立：本次调用没被确认门禁拦下：{str(out)[:300]}")
        assert "product_manage" not in executed, "被拦下的写不得真的执行（#3414）"
        router = _router_of(SRC.read_text(encoding="utf-8"))
        declared = [n for n, _ in _chain_entries(router)]
        assert trace == declared, (
            "门禁求值序列 ≠ 链表的声明顺序\n"
            f"  实际求值 = {trace}\n  链上声明 = {declared}")

    def test_confirmation_is_evaluated_once_per_tool_call(self):
        """③ 确认判定：**恰好 1 次**（改前 3 次；同一 tool/args/msg ⇒ 结果必然相同）。"""
        confirm_calls: list = []
        out, _, _ = _drive_write_call(confirm_calls=confirm_calls)
        assert "confirmation_required_no_card" in str(out), (
            f"用例前提不成立：本次调用没被确认门禁拦下：{str(out)[:300]}")
        assert len(confirm_calls) == 1, (
            f"一次工具调用内 `_requires_confirmation` 求值了 {len(confirm_calls)} 次（应为 1）："
            f"{confirm_calls}")

    def test_confirmation_is_evaluated_once_when_the_card_was_clicked(self):
        """③′ 点卡放行路径同样只求 1 次 —— 那条路径会走到**另外两个**站点
        （`_card_confirmed` 为真时 `if _card_confirmed is False ...` 被跳过，
        改由 `(_card_confirmed or _write_was_confirmed)` 那一处承重）。
        """
        shared: dict = {}
        out1, _, _ = _drive_write_call(store_state=shared)
        cv = str(shared.get("last_confirm_value") or "")
        assert "confirmation_required_no_card" in str(out1) and cv, (
            f"第一轮没有走完「被拦 + 代码补卡 + confirmValue 落库」：{str(out1)[:200]}")
        confirm_calls: list = []
        out2, executed2, _ = _drive_write_call(store_state=shared, last_user_msg=cv,
                                               confirm_calls=confirm_calls)
        assert "confirmation_required" not in str(out2), (
            f"用例前提不成立：点卡之后仍被门禁拦下：{str(out2)[:300]}")
        assert "product_manage" in executed2, "点卡之后写没有被放行（用例前提不成立）"
        assert len(confirm_calls) == 1, (
            f"点卡路径上一次工具调用内 `_requires_confirmation` 求值了 {len(confirm_calls)} 次"
            f"（应为 1）：{confirm_calls}")

    def test_write_gate_region_loads_session_state_at_most_once(self):
        """④ 会话状态往返：门禁链内 load ≤ 1 次，且没有门禁绕过共享快照。

        **两条放行路径各测一遍**：同一张链上，不同路径走到的门禁站点不同 ——
        被拦路径承重的是站点 1/2/4，点卡放行路径才走到事实核对那一处（`_f10`）。
        只测一条路径会漏掉另一条上的内联 load（本文件首版即此形态：把 `_f10` 改回自己
        `load` 时判据**全绿** —— 因为那处站点在被拦路径上根本不可达）。
        """
        # 路径①：被拦路径
        _, _, blocked_loads = _drive_write_call()
        # 路径②：点卡放行路径（先跑一轮拿到代码补发卡的 confirmValue，再点它）
        shared: dict = {}
        _drive_write_call(store_state=shared)
        cv = str(shared.get("last_confirm_value") or "")
        assert cv, "点卡路径的前提（confirmValue 落库）不成立"
        _, executed, clicked_loads = _drive_write_call(store_state=shared, last_user_msg=cv)
        assert "product_manage" in executed, "点卡路径没有放行写（用例前提不成立）"

        for label, load_calls in (("被拦路径", blocked_loads), ("点卡放行路径", clicked_loads)):
            in_tool = [f for f in load_calls if "_run_one_tool" in f]
            shared_loads = [f for f in in_tool if len(f) > 1 and f[1] == LOADER_NAME]
            bypass = [f for f in in_tool
                      if len(f) > 1 and f[1].startswith(GATE_PREFIX) and f[1] != LOADER_NAME]
            assert len(shared_loads) == 1, (
                f"[{label}] 共享快照 load 了 {len(shared_loads)} 次（应恰好 1 次）⇒ 往返没收敛："
                f"{shared_loads}")
            assert bypass == [], (
                f"[{label}] 有门禁绕过共享快照自己 load（{len(bypass)} 次）⇒ 往返又变多："
                f"{[f[1] for f in bypass]}")
            # `_run_one_tool` 内的 load 总数 = 1（共享快照）+ 1（缺参恢复 helper 内部的既有
            # load，本包未改动它的语义）。**改前实测 7**（1 helper + 6 条门禁各自内联 load）。
            assert len(in_tool) == 2, (
                f"[{label}] `_run_one_tool` 内的 load 总数 = {len(in_tool)}"
                "（期望 2 = 共享快照 1 + helper 1）；若不是 2：要么门禁链又加了往返，"
                "要么那个 helper 的既有 load 语义变了（后者要同步改本行与上面的数字）")


# ── 话术冻结：门禁区字符串字面量逐字不变 ──────────────────────────────────────

#: 门禁区（= 链上每条门禁的函数体）的字符串字面量**冻结清单**（本包落地时的真值）。
#: 这是「零行为变更」的机械形态：门禁话术/短码/工具名改一个字即红（不靠人眼 diff）。
FROZEN_GATE_LITERALS = frozenset({
    # 111 条：由**改前**源码的门禁区（原 464~1093 行）机械提取；
    # 改后逐条相等（零增零删）。增删任何一条都必须写进 PR body ——
    # 话术变更属行为变更，另开行为包走。
    '',
    ' ',
    ' args=',
    ' equal=',
    ' last_msg=',
    ' msg=',
    ' reason=',
    ' tool=',
    ' | session=',
    ' | 校验错误=',
    ' 前轮已确认（值一致）→ 放行 | session=',
    ' 已校验的参数（**原样**用作卡片 fields，不要改写）：',
    ' 是写操作（可能不可逆或产生数据变更），必须先向用户展示确认卡片并取得明确确认。**不要再次调用 ',
    "'",
    "' | session=",
    "')→product_detail 完成，接地标记已落 | session=",
    '(action=',
    ') | session=',
    ') → 校验通过后再调用 ',
    '** —— 在顾客点击确认卡之前它会被同样拦下、白烧一轮。本轮唯一的下一步是：调用 interact(component=confirm, fields=[…]) 把将要执行的内容展示给顾客，等顾客**点击确认卡**之后再调用 ',
    ", target_action='",
    '-',
    '[',
    '] Tool not found: ',
    '] card-confirm check failed (non-fatal): ',
    '] card-confirm 诊断: stored=',
    '] card-confirm 诊断失败: ',
    '] confirmed_write_tool check failed (non-fatal): ',
    '] ground gate check failed (non-fatal): ',
    '] pending 参数回填失败（非致命）: ',
    '] 下单接地闸门：本会话未查商品详情，拦截 order_create | session=',
    '] 写工具 ',
    '] 前轮确认记录不覆盖本次调用（工具名或值不符）→ 仍需新卡 | session=',
    '] 单价接地校验失败（非致命）: ',
    '] 单价接地校验拦截 order_create: ',
    '] 卡片来源取值失败（非致命）: ',
    '] 拦截**校验失败后的写调用** ',
    '] 拦截「确认事实已变」的下单 ',
    '] 拦截「顾客在下单却无信号转人工」 | session=',
    '] 拦截商品图片域能力误宣式转人工 | session=',
    '] 拦截在办流程中的无信号转人工 | session=',
    '] 拦截未确认的写操作 ',
    '] 拦截能力误宣式转人工 | session=',
    '] 接地自动驾驶失败（回落到话术）: ',
    "] 接地自动驾驶：从会话历史取得商品关键词'",
    "] 接地自动驾驶：代跑 product_search('",
    '] 最近确认卡读取失败（非致命）: ',
    '] 校验失败账读取失败（非致命）: ',
    '] 点卡的卡值与本次调用不符 → 视为未确认 ',
    '] 确认事实核对失败（非致命）: ',
    '] 确认卡 confirmValue 精确匹配 → 放行写操作 ',
    'action',
    'aftersale_create',
    'confirmation_required_card_not_clicked',
    'confirmation_required_no_card',
    'confirmed_write_tool',
    'data',
    'error',
    'grounded_product_detail',
    'handoff_blocked_capability_denial',
    'handoff_blocked_inflight',
    'human_handoff',
    'id',
    'items',
    'keyword',
    'last_confirm_value',
    'message',
    'messages',
    'name',
    'order_confirmation_mismatch',
    'order_create',
    'params',
    'price',
    'productId',
    'product_detail',
    'product_id',
    'product_not_grounded',
    'product_search',
    'products',
    'read_only',
    'reason',
    'success',
    'suggestion',
    'summary',
    'target_tool',
    'tool_not_found',
    'tool_not_found_relocked',
    'unit_price_not_grounded',
    'validation_failed_write_blocked',
    '⚠️ 本次是**涉钱面（改价）**：确认形态**只认卡片点击**，商家打字「确认」不算（改价门禁只认卡值，issue #5317）。',
    '。',
    '」—— 但**你能下单**：`order_create` 就是本流程的写工具（参数齐了就能真实落单）。「无法代为提交订单」属**能力误宣**：顾客明明要买，却被告知系统做不到，转化路径被自己掐断。正确做法：缺收货信息就先 `customer_address_query` 查历史地址，没有再发 `interact(component=form)` 或用自然语言问姓名/手机号/地址；参数齐了走 confirm 卡 → `validate_input` → `order_create`（含 sms_code）。只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。',
    '下单被拦截（单价与商品库不符）：',
    '下单被拦截，但**已代为查询商品**：',
    '下单被拦截：本会话还没有**成功查询过商品详情**（价格/规格/加工项都无从确认）。请**立即**按顺序执行，**不要重复调用 order_create**（重复无效，这是硬性前置条件）：\n1) product_search(keyword=顾客提到的商品名) —— 顾客说「遮光窗帘 3 米」就用 keyword="遮光窗帘"；\n2) product_detail(product_id=第 1 步选中的商品)；\n3) 拿到真实单价/加工项/规格后，按顾客确认的信息再下单。\n禁止凭记忆填价格或加工项。',
    '下单被拦截：本次要执行的明细与**顾客确认过的那一份**不一致。顾客确认后明细（数量/单价/加工项/手机号）一旦变化，那张确认卡的确认即失效。',
    '你的转人工理由写的是「',
    "先补齐参数 → 重新调用 validate_input(target_tool='",
    '工具 ',
    '您的订单已确认，请再回复「继续」，我马上为您提交。',
    '把 items 改回顾客确认过的值；确实要改，就**重新发一张确认卡**（interact component=confirm）让顾客再点一次，不要直接落库。',
    '若顾客确实要求人工，需其明确说出「转人工/找人工/找客服」后再调用本工具。',
    '订单流程已切换到订单模块，请再回复「继续」，我马上为您提交。',
    '请按交互卡与提示继续下一步。',
    '顾客是在办**下单**：请继续收齐信息并调用 order_create 完成下单',
    '顾客是在办**售后**（退货/换货/退款/维修）：请先与顾客确认订单与原因（interact 卡），然后调用 aftersale_create 创建工单（order_id 用已查到的订单号）',
    '顾客正在下单（本轮消息仍在推进下单），且本会话已经查过商品详情 —— **不要转人工**：`order_create` 就是本流程的写工具，参数齐了就能真实落单。缺收货信息就先 `customer_address_query` 查历史地址，没有再发 `interact(component=form)` 或直接问；然后走 confirm 卡 → `validate_input` → `order_create`（含 sms_code）。只有当顾客**显式**要求人工、情绪激烈或诉求超出能力时，才允许转人工。',
    '顾客正在办理的业务尚未完成，且本轮消息没有要求转人工、没有情绪激动、也不涉及赔偿/法律。**不要再次调用 human_handoff**，继续完成当前流程。',
    '（product_id=',
    '）。请基于该真实商品与单价重新组织 items 并调用 order_create；加工项/规格请用 product_detail 结果中的值，不要凭记忆填。',
    '，单价 ¥',
})


def _gate_literals(src: str) -> set:
    """链上每条门禁函数体里的字符串字面量集合（跳过函数自身的 docstring）。"""
    router = _router_of(src)
    table = _chain_entries(router)
    assert table, f"链表为空/不存在（fail-closed）：{table!r}"
    out: set = set()
    for _, impl in table:
        node = next(n for n in router.body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == impl)
        body = node.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        for sub in body:
            for inner in ast.walk(sub):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    out.add(inner.value)
    return out


class TestWordingIsByteIdentical:
    """⑤ 话术不变：门禁区的字符串字面量集合与本包落地时**逐字相等**。"""

    def test_write_gate_literal_set_is_frozen(self):
        actual = _gate_literals(SRC.read_text(encoding="utf-8"))
        added = sorted(actual - FROZEN_GATE_LITERALS)
        removed = sorted(FROZEN_GATE_LITERALS - actual)
        assert actual == FROZEN_GATE_LITERALS, (
            "门禁区的字符串字面量集合变了（本包是**零行为变更**的结构重构；改话术属行为变更，"
            "必须另开行为包并同步改这份冻结清单）：\n"
            f"  新增 = {added}\n  删除 = {removed}")

    def test_the_criterion_goes_red_on_a_reworded_gate_message(self):
        """负例：改一个字的门禁话术 ⇒ 判据必报（不是永远绿的空判据）。"""
        src = SRC.read_text(encoding="utf-8")
        mutated = _mutate(src, "下单被拦截：本会话还没有**成功查询过商品详情**",
                          "下单被拦截：本会话还没有**成功查询过商品详情。**")
        actual = _gate_literals(mutated)
        assert actual != FROZEN_GATE_LITERALS, "改了一个字的门禁话术后判据仍全绿 —— 空判据"
