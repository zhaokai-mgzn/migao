# case_ids: OR-014
# （OR-014 是「product_inquiry → 回锁到 order 流程」那条用例；本文件是该行为的**结构性守卫**
#   —— 回锁一旦不置位，OR-014 的链路就会在轮末被覆盖回原 skill，属它承重的编排前提。）
"""回锁必须**同时置位** `_relocked_this_round`（issue #4126）—— 机械守卫，不靠人记。

## 病根（#4126 原文 + 实测）

`finalize_turn` 第 10 节**只在** `_relocked_this_round` 为真时才不把 `pending_interact_skill`
覆盖回本轮 skill。而 `react_turn.py` 的 4 处 `await _relock_order_skill(...)` 里，
**3 处没置位**（文本级能力误宣 / `handoff_blocked_capability_denial` / `handoff_blocked_inflight`）
⇒ 回锁被轮末覆盖 = **「说了却没做」**（同 #3976 P3 形态）。

## 判据（AST，机械可判）

文件里**每一处** `await _relock_order_skill(...)` 调用，其**最近的语句块**内必须**先于它**
出现 `_relocked_this_round = True`。

## 红证（本文件自带两条合成语料的自证，另有实测）

| 注入 | 结果 |
|---|---|
| 删掉 3 处**新增**置位中任意一处（逐处实跑） | `test_every_relock_call_sets_the_flag` 报出那一处的**行号**（实测 3/3 真红，不是收集错误） |
| 合成语料：有调用、无置位 | `test_guard_rejects_missing_flag` 必须报违规（防守卫本身空转） |
| 合成语料：置位写在调用**之后** | `test_guard_rejects_flag_after_call` 必须报违规（防"顺序不算数"） |

⚠️ **红证要自证"真红"**：第一轮验证时我在**没有 venv 的 worktree** 里跑 pytest ⇒ 收集失败（`ModuleNotFoundError: fastapi`）
也是非零退出 ⇒ 被误读成"红证成立"（**空红证**）。改用主工作区 venv 重跑后才拿到真读数
（4 passed；3 处注入各报出对应行号）。`migao-dev-flow` §23.5 同族。

## 未固化项（照实登记）

本守卫**只覆盖 `await _relock_order_skill(...)` 调用**。实测发现**第 5 处**置位
（`cross_skill_target` 路由分支里的 `_relocked_this_round = True`）删掉**不会**让本守卫变红 ——
那不是 relock 调用，其"置位与结果被消费的相对位置"是**另一条路径的形状**（#3976/#4124 族）。
⇒ 本条**未**被本 PR 覆盖；要机械化需先定义那条路径的判据形态（另议，不硬凑）。
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "app" / "graph" / "skills" / "execution" / "react_turn.py")
CALL = "_relock_order_skill"
FLAG = "_relocked_this_round"


def _is_relock_call(stmt: ast.stmt) -> bool:
    """`await _relock_order_skill(...)`（表达式语句里的 await 调用）。"""
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
        return False
    call = stmt.value.value
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == CALL)


def _is_flag_set(stmt: ast.stmt) -> bool:
    """`_relocked_this_round = True`（字面 True，不是别的表达式）。"""
    if not isinstance(stmt, ast.Assign):
        return False
    if not any(isinstance(t, ast.Name) and t.id == FLAG for t in stmt.targets):
        return False
    return isinstance(stmt.value, ast.Constant) and stmt.value.value is True


def check_source(src: str) -> list[str]:
    """→ 违规清单（每条带行号）；空 = 全部合规。**纯函数**，便于用合成语料自证。"""
    tree = ast.parse(src)
    blocks: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block:
                blocks.append(block)

    problems: list[str] = []
    for block in blocks:
        for idx, stmt in enumerate(block):
            if not _is_relock_call(stmt):
                continue
            if not any(_is_flag_set(prev) for prev in block[:idx]):
                problems.append(
                    f"line {stmt.lineno}: `await {CALL}(...)` 之前**没有** `{FLAG} = True` "
                    f"⇒ 回锁会在轮末被覆盖（finalize_turn 第 10 节只在置位时不覆盖）"
                )
    return problems


def test_every_relock_call_sets_the_flag():
    """真实文件：**每一处** relock 调用前都必须先置位（删掉任一处 ⇒ 报出那一处的行号）。"""
    problems = check_source(SRC.read_text(encoding="utf-8"))
    assert not problems, "回锁未置位（issue #4126 形态）：\n  " + "\n  ".join(problems)


def test_guard_rejects_missing_flag():
    """守卫自证 ①：合成语料「有调用、无置位」必须被判违规（否则守卫本身在空转）。"""
    synthetic = (
        "async def f():\n"
        "    nonlocal _relocked_this_round\n"
        "    await _relock_order_skill('s', None, migrate_card_owner=True)\n"
    )
    assert check_source(synthetic), "守卫漏判了「无置位」的调用"


def test_guard_rejects_flag_after_call():
    """守卫自证 ②：置位写在调用**之后**不算（判据要求"先于调用"）。"""
    synthetic = (
        "async def f():\n"
        "    nonlocal _relocked_this_round\n"
        "    await _relock_order_skill('s', None, migrate_card_owner=True)\n"
        "    _relocked_this_round = True\n"
    )
    assert check_source(synthetic), "守卫漏判了「置位在调用之后」"


def test_guard_accepts_flag_before_call():
    """守卫自证 ③：置位在调用之前 ⇒ 合规（否则守卫会把正确写法判红）。"""
    synthetic = (
        "async def f():\n"
        "    nonlocal _relocked_this_round\n"
        "    _relocked_this_round = True\n"
        "    await _relock_order_skill('s', None, migrate_card_owner=True)\n"
    )
    assert not check_source(synthetic), "守卫把正确写法判红了"