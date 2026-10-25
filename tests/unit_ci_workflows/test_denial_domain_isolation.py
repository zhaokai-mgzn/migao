# case_ids: AG-008
"""**域隔离**类级元守卫：两个「能力自我否定」判据不得再串味（issue #7758）。

## 病（生产实证 sess_cf885dc3ef40435a，2026-10-25）

下单域判据 `capability_denial_text_hit` 末尾**代理**了图片域判据 `_product_image_denial_hit`
（起源 issue #3931 的"同一类能力误宣的另一张脸"），于是**海报/图片的能力边界陈述**被当成
**下单能力误宣**：`react_turn` 命中后 `_relock_order_skill` 把 `pending_skill` 锁到 `order`
并注入"缺信息就问缺的那一项" ⇒ 会话改口连问 3 轮下单规格（顾客亲口说「我不是要下单」后仍在订单流）。

## 为什么需要这一层（不是"再加一条行为断言"）

行为面已由 `backend/ai-agent-service/tests/test_order_lock_cross_domain.py` 覆盖（实例 + 正对照）。
但**复发形态**是结构性的：两条判据共处一个模块、都叫"能力误宣"，下一个人"顺手复用"一次
就把域隔离打回去，而行为断言只在**具体措辞**上红。所以这里锁**结构**（零依赖、秒级、AST）：

  · `capability_denial_text_hit` 的函数体**不得**调用 `_product_image_denial_hit`；
  · 图片域跨小句分支**只能**用「能力资源否定」形态（`_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE`），
    且 `_PRODUCT_IMAGE_UNABLE_RE` 必须由它组合而来（单一事实源，防两套正则漂移）;
  · 撤回解锁的三处接线必须存在（判据 → 在办判据 / 路由 / 轮末持久化）——只写函数不接线
    = 会话照旧"一直"粘在订单流。

## 判据**不许空跑**

每个 checker 都吃源码字符串，并在 `test_checkers_are_not_vacuous_*` 里喂**注入变异**的副本
（把缺陷写回去）断言"必须报出违规" ⇒ 判据自己会红，不是恒绿的装饰。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
BASE_SKILL = SKILLS_DIR / "base_skill.py"
FINALIZE_TURN = SKILLS_DIR / "execution" / "finalize_turn.py"
NODES = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "nodes.py"


def _func_src(src: str, name: str) -> str:
    """返回模块源码里某个顶层函数的**源码片段**（找不到抛断言，避免空跑）。"""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"源码里找不到函数 {name} —— 判据同步到新结构")


def _called_names(src: str, func_name: str) -> set[str]:
    """函数体内被**调用**的名字集合（`f(...)` 形态；不含属性调用）。"""
    seg = _func_src(src, func_name)
    names: set[str] = set()
    for node in ast.walk(ast.parse(seg)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def isolation_violations(src: str) -> list[str]:
    """域隔离的结构判据：返回违规清单（空 = 通过）。"""
    bad: list[str] = []
    if "_product_image_denial_hit" in _called_names(src, "capability_denial_text_hit"):
        bad.append(
            "capability_denial_text_hit 又调用了 _product_image_denial_hit —— "
            "图片域判据被下单域守卫吞并（域串味），会 relock 会话到 order")
    image_body = _func_src(src, "_product_image_denial_hit")
    if "_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE" not in image_body:
        bad.append(
            "_product_image_denial_hit 的跨小句分支没有用 _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE"
            "（只认能力资源否定形态）—— 裸 V不了 会把「改不了排版」算成图片能力否定")
    if "_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE.pattern" not in src:
        bad.append(
            "_PRODUCT_IMAGE_UNABLE_RE 没有由 _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE 组合而来 —— "
            "两套正则会各自漂移")
    return bad


def withdrawal_wiring_violations(base_src: str, finalize_src: str, nodes_src: str) -> list[str]:
    """撤回解锁的三处接线：在办判据 / 路由 / 轮末持久化（缺一处 = 会话仍会「一直」粘住）。"""
    bad: list[str] = []
    if "_is_ordering_withdrawal" not in _called_names(base_src, "_order_flow_in_progress"):
        bad.append("_order_flow_in_progress 没有调用 _is_ordering_withdrawal —— 撤回轮仍判为在办")
    if "ordering_withdrawn" not in nodes_src or "_is_ordering_withdrawal" not in nodes_src:
        bad.append("route_by_intent 没有撤回退出（未置位 ordering_withdrawn / 未判撤回）")
    if "ordering_withdrawn" not in finalize_src or \
            "_release_order_lock_on_withdrawal" not in finalize_src:
        bad.append("finalize_turn 没有清跨轮锁 —— 轮末又把 order 写回 pending_skill")
    return bad


def test_domain_isolation_holds():
    src = BASE_SKILL.read_text(encoding="utf-8")
    assert isolation_violations(src) == [], "\n".join(isolation_violations(src))


def test_withdrawal_wiring_holds():
    bad = withdrawal_wiring_violations(
        BASE_SKILL.read_text(encoding="utf-8"),
        FINALIZE_TURN.read_text(encoding="utf-8"),
        NODES.read_text(encoding="utf-8"),
    )
    assert bad == [], "\n".join(bad)


# ── 反空跑：把缺陷注入源码副本，判据必须报出违规 ──────────────────────────────

def test_isolation_checker_is_not_vacuous():
    src = BASE_SKILL.read_text(encoding="utf-8")
    mutated = src.replace(
        "    return _scope_misattribution_hit(text)",
        "    if _product_image_denial_hit(text):\n"
        "        return _product_image_denial_hit(text)\n"
        "    return _scope_misattribution_hit(text)",
        1,
    )
    assert mutated != src, "变异没生效 —— 判据同步到新源码（拒绝空跑）"
    assert isolation_violations(mutated), "把域串味写回去，判据居然还是绿的"


def test_narrowing_checker_is_not_vacuous():
    src = BASE_SKILL.read_text(encoding="utf-8")
    mutated = src.replace(
        "        for m in _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE.finditer(clause)]",
        "        for m in _PRODUCT_IMAGE_UNABLE_RE.finditer(clause)]",
        1,
    )
    mutated = mutated.replace("    + _PRODUCT_IMAGE_CAPABILITY_NEGATION_RE.pattern",
                              "")  # 同时去掉单一事实源组合
    assert mutated != src, "变异没生效 —— 判据同步到新源码（拒绝空跑）"
    assert isolation_violations(mutated), "把跨小句放宽写回去，判据居然还是绿的"


def test_wiring_checker_is_not_vacuous():
    final_src = FINALIZE_TURN.read_text(encoding="utf-8")
    base_src = BASE_SKILL.read_text(encoding="utf-8")
    nodes_src = NODES.read_text(encoding="utf-8")
    mutated = final_src.replace("_release_order_lock_on_withdrawal", "_noop_release")
    assert mutated != final_src, "变异没生效 —— 判据同步到新源码（拒绝空跑）"
    assert withdrawal_wiring_violations(base_src, mutated, nodes_src), \
        "拔掉 finalize 的解锁接线，判据居然还是绿的"


def test_no_vacuous_source_paths():
    """三份源码必须真实存在且非空（路径漂移会让上面的判据全部空跑）。"""
    for p in (BASE_SKILL, FINALIZE_TURN, NODES):
        assert p.is_file(), f"源码路径不存在（判据已空跑）：{p}"
        assert p.stat().st_size > 1000, f"源码文件异常小（判据已空跑）：{p}"
