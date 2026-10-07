# case_ids: DA-022
"""**action 枚举源码解析器**：`"enum": list(CONST)` 形态必须解析出真实取值（L0 静态不变式）。

## 为什么要有这条（issue #6280 实测，2026-10-07）
`scripts/case_coverage.py::tool_declared_actions` 是「声明的 action 是否真实存在」这条判据的
**唯一取真值处**。它原先只认 `"enum": [ ... ]` 的**字面**形态 ⇒ 当工具把枚举归一到一条
模块级常量（`"enum": list(VALID_ACTION_ORDER)`）时，取值集解析为空 ⇒ 该工具被判成
**「没有 action 维度」** ⇒ `action_binding_violations` 对**每一条**声明过它的用例报
`action_dangling`（`no_action_param`）。

实测后果：`inventory_manage` 加第三个只读 action `material_shortage` 后，CI 的
**Case Coverage Gate 当场红**，报错指向**用例**（`DA-022` / 存量 `PR-004`）而不是工具 ——
而那条路径下「改用例」永远改不对（值是真实存在的）。这正是本仓最忌讳的
「判据把责任指错对象」形态，故落成 L0 判据。

## 判据面（都用真语料，不另写一份解析实现）
1. **注入式**：字面 `"enum": [...]` ⇒ 取值集逐字相符（回归基线，不许被兜底腿改写）；
2. **注入式**：`"enum": list(CONST)` ⇒ 必须解析到 `CONST` 的真实取值（本单的缺陷形态）；
3. **注入式**：无 enum 且无常量引用 ⇒ 空集（**不许**兜底腿凭空造值）；
4. **真语料对照**：仓内 `inventory_manage` 必须同时含 `query` / `low_stock_alert` /
   `material_shortage`，且**不得**把 `enum` 这个**键名**本身当成 action 取值（取值的假阳性
   同样会让判据飘）。
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT / "scripts", _REPO_ROOT / ".github", _REPO_ROOT / "tests" / "agent_eval"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from case_coverage import action_enum, tool_declared_actions  # noqa: E402

#: 真语料：本单新增的第三个只读 action 所在工具（`backend/ai-agent-service/app/tools/`）
REAL_TOOL = "inventory_manage"

_INLINE_ENUM_SRC = '''
class T:
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["query", "low_stock_alert", "material_shortage"],
            },
            "product_id": {"type": "string"},
        },
        "required": ["action"],
    }
'''

_CONST_REF_SRC = '''
VALID_ACTIONS = {"query", "low_stock_alert", "material_shortage"}
VALID_ACTION_ORDER = ("query", "low_stock_alert", "material_shortage")

class T:
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": list(VALID_ACTION_ORDER),
            },
            "product_id": {"type": "string"},
        },
        "required": ["action"],
    }
'''

_NO_ENUM_SRC = '''
class T:
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "操作类型"},
            "product_id": {"type": "string"},
        },
        "required": ["action"],
    }
'''

_EXPECTED = {"query", "low_stock_alert", "material_shortage"}


@pytest.fixture()
def tools_dir(tmp_path, monkeypatch):
    """把 `TOOLS_DIR` 指到临时目录 —— 注入式用例**不写仓内文件**（判据只读）。"""
    import case_coverage
    monkeypatch.setattr(case_coverage, "TOOLS_DIR", tmp_path)
    return tmp_path


def _declared(tools_dir, name, src):
    (tools_dir / f"{name}.py").write_text(src, encoding="utf-8")
    return tool_declared_actions(name)


def test_inline_enum_is_parsed_verbatim(tools_dir):
    """① 字面 enum ⇒ 逐字相符（这条不许被常量兜底腿改写）。"""
    assert _declared(tools_dir, "inline_tool", _INLINE_ENUM_SRC) == _EXPECTED


def test_const_ref_enum_is_resolved_from_module_constant(tools_dir):
    """② `"enum": list(CONST)` ⇒ 解析回常量取值（issue #6280 的缺陷形态）。"""
    assert _declared(tools_dir, "const_tool", _CONST_REF_SRC) == _EXPECTED


def test_no_enum_yields_empty_not_invented_values(tools_dir):
    """③ 没有枚举 ⇒ 空集（兜底腿不许凭空造值 = 不许把「无 action 维度」洗成有）。"""
    assert _declared(tools_dir, "no_enum_tool", _NO_ENUM_SRC) == set()


def test_enum_key_name_is_not_an_action_value(tools_dir):
    """④ `enum` 这个**键名**不得混进取值集（假阳性会让覆盖判据飘）。"""
    for src in (_INLINE_ENUM_SRC, _CONST_REF_SRC):
        assert "enum" not in _declared(tools_dir, "k_tool", src)


def test_real_tool_declares_the_three_read_only_actions():
    """真语料对照：`inventory_manage` 的三个只读 action 必须都被看见。

    🔴 若这条红 ⇒ **先查解析器**（`tool_declared_actions`），不要去改用例 ——
    值 `material_shortage` 在工具源码里真实存在，改用例只会把真缺陷藏起来。
    """
    assert action_enum(REAL_TOOL) == _EXPECTED, (
        "inventory_manage 的 action 枚举解析结果不符 —— 解析器（scripts/case_coverage.py）"
        "或工具的 enum 声明形态变了"
    )
