# case_ids: MC-049
"""类级固化 A：**用例里声明的每种 `precondition.type` 都必须在 runner 的实现集里**（issue #6041）。

## 病灶（本仓反复登记的「空断言」同族，方向是「声明了却不被求值」）

`.github/cases/**` 的 `precondition:` 是**声明层**的前置断言：runner 按 `type` 去
`tests/agent_eval/local_runner.py` 的 `_PRECONDITION_TYPES`（唯一真相源）取**靶子存在性下界**
并取基线/现值。若某条用例声明了一个**没人实现**的 `type`，那条前置**永远不会被求值** ——
用例照旧跑、报告照旧给分，而它自称依赖的那个前置**根本没被核过**。

⇒ 与「不会红的判据 = 空判据」同构：**声明了却不被求值的前置 = 装饰性前置 = 空断言**。

## 判据（纯静态，零 ai-agent 依赖）

1. **声明 ⊆ 实现**：真实用例库（`.github/cases/**` 的**真语料**，不写死清单）里每一条
   **结构化** `precondition[].type` 必须出现在 runner 的 `_PRECONDITION_TYPES` 键集里；
2. **台账不许空转**：键集为空 ⇒ 红（fail-closed —— 有人清空注册表「消红」时当场红）；
3. **每个已登记 type 都要有实现面**：`_PRECONDITION_TYPES` 的每个键都必须在 runner 源码里
   有对应的运行期接线（结构形状 `f"{t}:{src}"`，与 `_precondition_what` 的调用面同锚）
   —— 防「注册了但没人用」的反方向缺口；
4. **判别力自证**：把「未实现 type」注入**内存里**的用例副本 ⇒ 必须判红并**具名**报出该 type；
   真实语料不注入 ⇒ 不报（反向对照）。

## 边界（照实登记）

- **散文形态**的 `precondition`（值本身是 `str`，本仓现取 14 条）**不在本判据射程**：它们的
  `type` 语义不在声明层，由 `check_precondition_declared` 在运行期对逐条 `dict` 核 —— 本判据
  只输出**条数**作可见性登记，不判它的内容（避免宽到误伤）。
- 本判据**判不了**「该前置声明得对不对」（那是 `test_eval_id_arg_precondition.py` 与
  `test_precondition_target_present.py` 的面），也**不跑** runner / 不跑评测。
- 本判据**不改**任何门禁的通过条件、不新增豁免。

## 为什么是纯静态（CI 环境陷阱）

CI 的 `ci workflow helper unit tests` job **只装 `pytest` + `pyyaml`**（不装 `pydantic` /
`langchain_core` / `fastapi`）⇒ 本文件**不 import** `tests/agent_eval/local_runner.py`
（它在模块层 import ai-agent 依赖），只用 `ast` **反解**它的 `_PRECONDITION_TYPES` 字面量；
也**禁** `try/except ImportError: <skip>`（那会让判据在 CI 里永远是空的）。
自证造法：毒化 `PYTHONPATH`（`pydantic.py` / `langchain_core.py` / `app/__init__.py` 三个
`raise ImportError`）+ `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，再跑本文件。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_REL = "tests/agent_eval/local_runner.py"
RUNNER = REPO_ROOT / RUNNER_REL
CASES_DIR = REPO_ROOT / ".github" / "cases"

sys.path.insert(0, str(REPO_ROOT / ".github"))
from render_cases import load_case_dicts  # noqa: E402  —— 用例书解析的仓内单一实现（纯 stdlib + pyyaml）

#: 唯一真相源的名字（承载体 = runner 的那个模块级注解赋值）。
REGISTRY_NAME = "_PRECONDITION_TYPES"


def _registered_types() -> set:
    """从 runner **源码**反解 `_PRECONDITION_TYPES` 的键集（纯静态，不 import 该模块）。"""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == REGISTRY_NAME:
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)
                    and isinstance(k.value, str)}
    raise RuntimeError(f"{RUNNER_REL} 里找不到 {REGISTRY_NAME} 的字面量定义"
                       "（判据 fail-closed：找不到就报错，不得当成空集放行）")


def _declared_types(cases: list) -> dict:
    """真语料里每一条**结构化** `precondition[].type` → 声明它的用例 id。"""
    out: dict = {}
    for c in cases:
        pc = c.get("precondition")
        if not isinstance(pc, list):
            continue
        for spec in pc:
            if isinstance(spec, dict) and spec.get("type"):
                out.setdefault(str(spec["type"]), []).append(str(c.get("id") or "?"))
    return out


def _prose_precondition_entries(cases: list) -> int:
    """散文形态的前置条数（**有意不判内容**，只作可见性登记，见模块 docstring 边界）。"""
    return sum(1 for c in cases for pc in (c.get("precondition") or [])
               if isinstance(pc, str))


def _cases() -> list:
    return load_case_dicts(CASES_DIR)


def test_every_declared_precondition_type_is_implemented():
    """判据 1：声明的 type 必须有实现（红证 = 往任一条用例的 `precondition` 里加一个未实现的 type）。"""
    registered = _registered_types()
    declared = _declared_types(_cases())
    missing = {t: ids for t, ids in declared.items() if t not in registered}
    assert not missing, (
        "以下 precondition.type 被用例声明、但 runner 的 "
        f"{RUNNER_REL}::{REGISTRY_NAME} 里**没有实现**（该前置永远是装饰性的、不会被求值）："
        f"{missing}。出口：在 {RUNNER_REL} 的 {REGISTRY_NAME} 里实现它"
        "（并给出靶子存在性下界 min），或从用例里撤掉这条声明。")


def test_registry_is_not_empty():
    """判据 2：台账不许空转（有人清空注册表来「消红」时当场红）。"""
    registered = _registered_types()
    assert len(registered) >= 5, f"{REGISTRY_NAME} 只登记了 {sorted(registered)} —— 注册表被清空/删瘦了"


def test_every_registered_type_is_wired_in_the_runner():
    """判据 3：每个已登记 type 都要有实现面（结构形状 `f"{t}:{src}"`）—— 防「注册了但没人用」。"""
    text = RUNNER.read_text(encoding="utf-8")
    unwired = sorted(t for t in _registered_types() if f'"{{t}}:{{src}}"' not in text
                     and f"f\"{t}:" not in text and f"f'{t}:" not in text)
    assert not unwired, (
        f"{REGISTRY_NAME} 里登记了但没有运行期接线的 type（注册了却没人求值）：{unwired}"
        f" —— 实现面在 {RUNNER_REL} 的 `precondition_capture_shape` / 基线捕获点。")


def test_red_proof_unimplemented_type_is_named():
    """判据 4（注入式红证）：把未实现的 type 注入内存副本 ⇒ 判红并具名；真实语料 ⇒ 不报。"""
    registered = _registered_types()
    real = _cases()
    injected = [dict(c) for c in real]
    injected[0]["precondition"] = [{"type": "redproof_unimplemented_type", "source": "x"}]
    injected[0]["id"] = "REDPROOF-001"
    bad = {t: ids for t, ids in _declared_types(injected).items() if t not in registered}
    assert "redproof_unimplemented_type" in bad, "注入的未实现 type 未被判红（判据退化成永绿）"
    assert bad["redproof_unimplemented_type"] == ["REDPROOF-001"], f"未具名报出注入的用例：{bad}"
    clean = {t: ids for t, ids in _declared_types(real).items() if t not in registered}
    assert not clean, f"**真实语料**里有未实现的 precondition.type（本判据的核心缺口）：{clean}"


def test_only_comments_change_is_green():
    """判据 4b（对照读数）：只改注释落入的用例副本不得改变判定（防判据被自己的文案喂红）。"""
    registered = _registered_types()
    commented = [dict(c) for c in _cases()]
    commented[0]["merge_log"] = str(commented[0].get("merge_log") or "") + " # 只加一条注释"
    commented[0]["data_checks"] = list(commented[0].get("data_checks") or []) + ["# 只加一条注释"]
    assert not {t for t in _declared_types(commented) if t not in registered}


def test_this_judgement_is_pure_static_and_never_skips():
    """纯静态自证：零 ai-agent 依赖 + 禁「跑不了就跳」（跳 = 绿了但没跑）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = imported & {"pydantic", "langchain_core", "langchain", "fastapi", "app"}
    assert not forbidden, f"本判据不得依赖 ai-agent 运行时依赖（CI 里没装）：{sorted(forbidden)}"
