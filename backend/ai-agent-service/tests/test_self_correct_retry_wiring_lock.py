# case_ids: DF-017, CH-001
"""生产路径**真的**把 `error_code` 递给不可重试闸门吗？—— 接线锁（issue #4149 G7）。

## 病灶形状（复核实测）

闸门 `if result_dict.get("error_code") in NON_RETRYABLE_ERROR_CODES` 在
`app/graph/skills/base_skill.py::_self_correct_retry` 里，而**生产路径**上调用它的是
`app/graph/skills/execution/react_turn.py`。既有测试（9 个文件 167 条）**全部手工构造**
`result_dict` 再喂闸门，于是下面两种改动**全绿通过**：

- 把调用点交给闸门的字典**去掉 `error_code`**
  （如 `{k: v for k, v in result_dict.items() if k != "error_code"}`）；
- 干脆**删掉这次调用** —— 闸门在生产路径上再也不会被执行。

「闸门在生产路径上真的会触发」这件事因此从未被断言（#4109 的护栏会不会真的生效，取决于
一个没有任何判据的接线跳）。既有两个同类锁覆盖的是**两头**：
`test_tool_permission_retry_guard.py` 锁「出口字典带 `error_code`」（产出侧）与
「闸门读 `result_dict["error_code"]`」（消费侧）—— 缺的正是**中间那一跳**：调用点把
**哪一份**字典递给**谁**。

## 本文件锁的不变式（每条都有处方红证）

1. `TestProductionWiring` —— `react_turn` 的生产路径上**确实存在**对 `_self_correct_retry`
   的调用（删调用即红）；
2. 递给闸门的 `result_dict` 实参必须是 `_execute_tool_safe(...)` 的返回值之一，且是**裸名字**
   （重建 / 过滤 / 传 `None` 即红）—— `error_code` 从出口到闸门是**同一份对象**；
3. 闸门名在 `react_turn` 里不得被局部定义遮蔽（真体必须来自 `base_skill` 的 import）；
4. `TestWiringLockCanGoRed` —— 判据自身**可红**：把处方改动注入 `react_turn.py` 的
   **逐字节副本**再喂同一个纯函数，两种点名改动必须各自报出；未改动的真源码必须不报。

## 为什么用结构锁而不是跑一遍 turn

`react_turn()` 是上千行的编排函数（LLM 循环 + 会话状态 + 卡片发射 + 多轮聚合），驱动它需要
整套替身 ⇒ 判别力会被替身自身的噪声稀释（那正是本单要治的「167 条全绿」的成因）。
本仓既有同款形态并已复用其形状：`test_tool_permission_retry_guard.py::TestFieldNameIsSingleSourced`
（AST 锁 `base_skill.py`）与 `test_behavior_mapping.py`（对 `react_turn.py` 的源码级断言）。
判据是**源码文本的纯函数** ⇒ 少一次「真跑一遍」的脆弱性，多一条能指名到行的红。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
REACT_TURN = SERVICE_DIR / "app" / "graph" / "skills" / "execution" / "react_turn.py"

GATE = "_self_correct_retry"
PRODUCER = "_execute_tool_safe"
FIELD = "error_code"

#: 闸门签名 `(tool, args, tool_context, skill_name, result_dict, session_id, tenant_id, state)`
#: 里 `result_dict` 的实参下标。
RESULT_DICT_INDEX = 4


def _awaited_call(node: ast.AST) -> ast.Call | None:
    """`await f(...)` / `f(...)` 里的调用节点（`result_str, result_dict = await …` 是 `Await`）。"""
    if isinstance(node, ast.Await):
        node = node.value
    return node if isinstance(node, ast.Call) else None


def _callee_name(node: ast.AST) -> str:
    """调用表达式被调者的名字（`f(...)` / `m.f(...)` 都取末段）。"""
    call = _awaited_call(node) if not isinstance(node, ast.Call) else node
    if call is None:
        return ""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def gate_call_args(tree: ast.AST) -> list[list[ast.expr]]:
    """生产路径上所有 `_self_correct_retry(...)` 调用点的实参列表（每个调用点恰好一条）。"""
    return [
        node.args for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == GATE
    ]


def produced_result_names(tree: ast.AST) -> set[str]:
    """被赋值为 `_execute_tool_safe(...)` 返回值的名字（`a, b = await _execute_tool_safe(...)`）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = _awaited_call(node.value)
        if call is None or _callee_name(call) != PRODUCER:
            continue
        for target in node.targets:
            if isinstance(target, ast.Tuple):
                names.update(e.id for e in target.elts if isinstance(e, ast.Name))
    return names


def shadowed_gate_names(tree: ast.AST) -> list[str]:
    """`react_turn` 里对闸门名的**重新定义**（局部 def / 赋值）—— 遮蔽即接线可疑。"""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == GATE:
            offenders.append(f"def:{node.lineno}")
        if isinstance(node, ast.Assign):
            offenders.extend(
                f"assign:{node.lineno}" for t in node.targets
                if isinstance(t, ast.Name) and t.id == GATE
            )
    return sorted(offenders)


def wiring_gaps(tree: ast.AST) -> list[str]:
    """生产接线的缺口清单（**空 = 接线成立**）。抽成纯函数以便喂处方副本做红证。"""
    calls = gate_call_args(tree)
    if not calls:
        return [f"生产路径没有调用 `{GATE}` ⇒ 不可重试闸门在生产上无人执行"]
    produced = produced_result_names(tree)
    gaps: list[str] = []
    for args in calls:
        if len(args) <= RESULT_DICT_INDEX:
            gaps.append(f"调用点只传了 {len(args)} 个实参（`result_dict` 位置缺失）")
            continue
        handed = args[RESULT_DICT_INDEX]
        if not isinstance(handed, ast.Name):
            gaps.append(
                f"递给闸门的不是裸名字而是 `{ast.unparse(handed)[:60]}`"
                f"（重建/过滤过的字典会丢 `{FIELD}`）"
            )
        elif handed.id not in produced:
            gaps.append(
                f"递给闸门的是 `{handed.id}`，它不是 `{PRODUCER}(...)` 的返回值"
                "（`error_code` 未必在同一份对象上）"
            )
    return gaps


def _read() -> str:
    return REACT_TURN.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# ① 生产接线：调用存在 + 递给闸门的是执行结果本体 + 名字未被遮蔽
# ──────────────────────────────────────────────────────────────────────────────

class TestProductionWiring:
    """`react_turn` 的生产路径必须真的把 `_execute_tool_safe` 的结果交给闸门。"""

    def test_the_source_tree_is_real(self):
        """fail-closed：被扫文件消失/变成空文件 ⇒ 判据空跑，宁可红。"""
        assert REACT_TURN.exists(), f"`{REACT_TURN}` 不见了 —— 真相源消失（fail-closed）"
        source = _read()
        assert len(source) > 5000, "`react_turn.py` 内容异常短（判据会空转通过）"
        assert produced_result_names(ast.parse(source)), (
            f"抽不到任何 `{PRODUCER}(...)` 的赋值 —— 产出侧的锚点已失效"
        )

    def test_production_path_invokes_the_gate(self):
        """**删掉这次调用即红**（复核实测的第二种改动）。"""
        calls = gate_call_args(ast.parse(_read()))
        assert calls, (
            f"生产路径（`react_turn.py`）没有调用 `{GATE}` —— "
            "不可重试闸门只活在测试里（`error_code` 再准也没人读）"
        )

    def test_the_gate_receives_the_execution_result_object(self):
        """**给闸门的字典去掉 `error_code` 即红**（复核实测的第一种改动）。"""
        gaps = wiring_gaps(ast.parse(_read()))
        assert gaps == [], (
            "生产接线断了：\n  " + "\n  ".join(gaps)
            + f"\n\n修法：把 `{PRODUCER}(...)` 的返回值**原样**传给 `{GATE}`"
            f"（不要重建字典、不要摘 `{FIELD}`）—— "
            "`test_tool_permission_retry_guard.py` 锁的是两头，这一跳归本文件。"
        )

    def test_the_gate_name_is_not_shadowed_in_the_production_module(self):
        """局部重定义（`_self_correct_retry = None` / 同名 def）会让接线指向别的东西。"""
        offenders = shadowed_gate_names(ast.parse(_read()))
        assert offenders == [], (
            f"`react_turn.py` 里重新定义了 `{GATE}`：{offenders} —— "
            "接线必须指向 `base_skill` 的真体（否则闸门被判据之外的东西替换）"
        )

    def test_the_imported_gate_is_the_real_gate(self):
        """运行时自证：`react_turn` 命名空间里的闸门 **就是** `base_skill` 的那一个。"""
        from app.graph.skills import base_skill
        from app.graph.skills.execution import react_turn

        assert react_turn._self_correct_retry is base_skill._self_correct_retry, (
            "`react_turn` 引用的闸门不是 `base_skill._self_correct_retry` —— "
            "结构锁指向的名字与真实体不是同一个对象"
        )


# ──────────────────────────────────────────────────────────────────────────────
# ② 判据自身可红（处方改动注入真源码的**逐字节副本**）
# ──────────────────────────────────────────────────────────────────────────────

#: 真源码里的接线语句（**唯一锚点**，改动其一即处方）
_WIRING_LINE = (
    "corrected = await _self_correct_retry(tool, args, tool_context, skill_name, "
    "result_dict, session_id, tenant_id, state)"
)

#: 处方 1：交给闸门的字典**去掉 `error_code`**（复核点名的改动）
_STRIP_KEY_MUTATION = (
    "corrected = await _self_correct_retry(tool, args, tool_context, skill_name, "
    '{k: v for k, v in result_dict.items() if k != "error_code"}, '
    "session_id, tenant_id, state)"
)

#: 处方 2：**删掉调用**（闸门在生产路径上再也执行不到）
_NO_CALL_MUTATION = "corrected = None  # 处方：闸门被拔掉"

#: 处方 3：局部**遮蔽**闸门名（真体被替换）—— 缩进取真源码里那行的缩进（不写死空格数）
_SHADOW_SUFFIX = f"{GATE} = None  # 处方：遮蔽"


class TestWiringLockCanGoRed:
    """**:red_circle: 红证**：两种点名改动必须被抓到，真源码必须放行。

    实现手法 —— 把处方注入 `react_turn.py` 的**逐字节副本**（`tmp_path`）再喂**同一个**
    纯函数：判据本来就是源码文本的函数，注入副本 ≡ 注入真文件，但**不动**归属他人的文件
    （issue #4149 的边界：`react_turn.py` 只读）。每个处方都先自断言锚点唯一，
    防「锚点漂了 ⇒ 夹具空跑 ⇒ 假红证」。
    """

    @staticmethod
    def _mutated_tree(tmp_path: Path, old: str, new: str) -> ast.AST:
        source = _read()
        assert source.count(old) == 1, (
            f"处方锚点在真源码里出现 {source.count(old)} 次（期望恰好 1 次）—— "
            "接入点变了，红证夹具必须先对齐（否则是空跑）"
        )
        fixture = tmp_path / "react_turn_mutated.py"
        fixture.write_text(source.replace(old, new), encoding="utf-8")
        return ast.parse(fixture.read_text(encoding="utf-8"))

    def test_unmutated_copy_passes(self, tmp_path):
        """**阴性负例**：未改动副本必须不报（防恒红 —— 判据不能对真源码也喊狼）。"""
        assert wiring_gaps(self._mutated_tree(tmp_path, _WIRING_LINE, _WIRING_LINE)) == []

    def test_stripping_error_code_from_the_gate_argument_is_caught(self, tmp_path):
        """**:red_circle: 处方 1** —— 交给闸门的字典去掉 `error_code` ⇒ 必须报出。"""
        tree = self._mutated_tree(tmp_path, _WIRING_LINE, _STRIP_KEY_MUTATION)
        gaps = wiring_gaps(tree)
        assert len(gaps) == 1 and "不是裸名字" in gaps[0], (
            f"去键改动未被报出（判据是空的）：{gaps}"
        )
        assert gate_call_args(tree), "调用仍在（是「换了字典」而不是「拔了调用」）—— 夹具语义错位"

    def test_removing_the_gate_call_is_caught(self, tmp_path):
        """**:red_circle: 处方 2** —— 删掉调用 ⇒ 必须报出「生产路径没有调用」。"""
        gaps = wiring_gaps(self._mutated_tree(tmp_path, _WIRING_LINE, _NO_CALL_MUTATION))
        assert len(gaps) == 1 and "没有调用" in gaps[0], (
            f"删调用未被报出（判据是空的）：{gaps}"
        )

    def test_shadowing_the_gate_name_is_caught(self, tmp_path):
        """**:red_circle: 处方 3** —— 局部遮蔽闸门名 ⇒ 必须报出（行号精确到那处 assign）。"""
        fixture = tmp_path / "react_turn_shadowed.py"
        source = _read()
        wiring_line_text = next(
            line for line in source.splitlines() if line.strip() == _WIRING_LINE.strip())
        indent = wiring_line_text[: len(wiring_line_text) - len(wiring_line_text.lstrip())]
        mutated = source.replace(
            _WIRING_LINE, f"{_WIRING_LINE}\n{indent}{_SHADOW_SUFFIX}")
        fixture.write_text(mutated, encoding="utf-8")
        wiring_line = next(
            i for i, line in enumerate(mutated.splitlines(), 1)
            if line.strip() == _WIRING_LINE.strip()
        )
        assert shadowed_gate_names(ast.parse(mutated)) == [f"assign:{wiring_line + 1}"], (
            "遮蔽未被报出（应当是紧跟接线语句的那处 `assign`）"
        )
        assert wiring_gaps(ast.parse(mutated)) == [], (
            "遮蔽不改实参 —— 本处方只该被 shadowed_gate_names 抓到（判据分工要清楚）"
        )

    def test_passing_something_other_than_the_execution_result_is_caught(self, tmp_path):
        """**:red_circle: 处方 4（同族）** —— 传一份**别处**构造的字典同样必须报出。"""
        tree = self._mutated_tree(
            tmp_path, _WIRING_LINE,
            _WIRING_LINE.replace("result_dict, session_id", "dict(result_dict), session_id"),
        )
        gaps = wiring_gaps(tree)
        assert len(gaps) == 1 and "不是裸名字" in gaps[0], f"重建字典未被报出：{gaps}"

    @staticmethod
    def _goes_red(lock: TestProductionWiring, method: str) -> bool:
        """该接线判据在处方副本下是否**变红**（True = 抓到）。"""
        try:
            getattr(lock, method)()
        except AssertionError:
            return True
        return False

    def test_the_production_lock_fails_on_a_mutated_production_source(self, tmp_path):
        """端到端红证：把**本文件的锁**指向处方副本 ⇒ `TestProductionWiring` 必红。

        判据是源码文本的纯函数 ⇒ 指向处方副本 ≡ 在真文件上改动，
        但零写入归属他人的文件（issue #4149 的边界：`react_turn.py` 只读）。
        """
        lock = TestProductionWiring()
        module = sys.modules[__name__]
        for mutation, expected_red in (
            (_STRIP_KEY_MUTATION, "test_the_gate_receives_the_execution_result_object"),
            (_NO_CALL_MUTATION, "test_production_path_invokes_the_gate"),
            (_NO_CALL_MUTATION, "test_the_gate_receives_the_execution_result_object"),
        ):
            fixture = tmp_path / "react_turn_mutated.py"
            fixture.write_text(_read().replace(_WIRING_LINE, mutation), encoding="utf-8")
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(module, "REACT_TURN", fixture)
                assert self._goes_red(lock, expected_red) is True, (
                    f"处方 `{mutation[:40]}…` 下 `{expected_red}` 竟然没红 —— 判据是空的"
                )