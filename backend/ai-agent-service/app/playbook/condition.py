"""口径卡的**可执行触发条件**（issue #8175 判据 2 / 6）。

口径不是自由文本：一条口径必须能被机器判定「这一轮到底该不该套用」。本模块是那套**条件语言**
的**唯一实现**（读面求值）；写面校验在 admin-api 的 `PlaybookConditionValidator`，
两处算子表由 `tests/unit_ci_workflows/test_playbook_condition_contract.py` 现取对账
（对账是判据：漏同步 ⇒ 红，而不是「写了但没人读」）。

## 形态

    叶子：{"field": "intent", "op": "in", "value": ["quote", "product_quote"]}
    组合：{"all": [cond, ...]} · {"any": [cond, ...]} · {"not": cond}

## 算子白名单（`OPS`；白名单之外一律判**不成立**）

| 算子 | 语义 |
|---|---|
| `eq` / `ne` | `context[field] == value` / `!=` |
| `in` / `not_in` | `context[field]` 属于 / 不属于 `value`（`value` **必须是数组**） |
| `contains` / `not_contains` | `value`（字符串）是 `str(context[field])` 的子串 / 不是 |
| `exists` / `not_exists` | 字段存在且非空 / 缺失或空（**不得**带 `value`） |

## fail-closed（三条，缺一条就会退化成「字段在架没人读」）

1. 结构不合法（缺 `field`、未知算子、`value` 类型不对、`all`/`any` 为空、嵌套过深）
   ⇒ `validate` 报错、`evaluate` 返回 `False`；**不是**「校验不过就放行」；
2. 条件本身是**字符串**（自由文本）⇒ 同样不合法 ⇒ 该卡**不出现在任何出口**；
3. `context` 缺字段 ⇒ 叶子求值 `False`（宁可不用，不可乱用）。

`evaluate` **永不抛异常**（调用点在 system prompt 组装路径上，抛出去会毁掉整轮对话）。
"""

from typing import Any, Dict, List, Optional

#: 算子白名单 —— **两端唯一真值**（Java 侧同表，对账判据见模块 docstring）
OPS = (
    "eq",
    "ne",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
)

_ARRAY_OPS = frozenset({"in", "not_in"})
_SUBSTRING_OPS = frozenset({"contains", "not_contains"})
_NO_VALUE_OPS = frozenset({"exists", "not_exists"})

#: 组合条件的键（与算子互斥：一个对象里不许既写 all 又写 op）
_GROUP_KEYS = ("all", "any", "not")

#: 嵌套上限：条件语言是给人写、给机器判的小语言，深层嵌套只会掩盖错误
MAX_DEPTH = 6

_FIELD_LABELS = {
    "intent": "意图",
    "skill": "技能域",
    "agent_type": "会话端",
    "role": "岗位",
    "scope": "口径范围",
    "user_text": "用户原话",
}

_OP_LABELS = {
    "eq": "等于",
    "ne": "不等于",
    "in": "属于",
    "not_in": "不属于",
    "contains": "包含",
    "not_contains": "不包含",
    "exists": "有值",
    "not_exists": "无值",
}


def _blank(value: Any) -> bool:
    """「空」的唯一口径：None / 空串 / 纯空白。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def validate(condition: Any, _depth: int = 0) -> List[str]:
    """返回**问题清单**（空列表 = 合法）。纯函数，永不抛。"""
    problems: List[str] = []
    if _depth > MAX_DEPTH:
        return [f"条件嵌套超过 {MAX_DEPTH} 层"]
    if not isinstance(condition, dict):
        # 自由文本 / 数字 / 列表 ⇒ 不可执行（判据 2 的核心：不接受自然语言）
        return [f"条件必须是 JSON 对象，实际是 {type(condition).__name__}"]
    if not condition:
        return ["条件是空对象"]

    groups = [k for k in _GROUP_KEYS if k in condition]
    if groups:
        if len(groups) > 1:
            return [f"一个条件里同时出现多个组合键：{sorted(groups)}"]
        if len(condition) > 1:
            return [f"组合键 {groups[0]} 不得与其它键共存：{sorted(condition)}"]
        key = groups[0]
        if key == "not":
            problems.extend(validate(condition["not"], _depth + 1))
            return problems
        children = condition[key]
        if not isinstance(children, list) or not children:
            return [f"{key} 必须是非空数组"]
        for i, child in enumerate(children):
            for p in validate(child, _depth + 1):
                problems.append(f"{key}[{i}]: {p}")
        return problems

    # ── 叶子 ──
    field = condition.get("field")
    op = condition.get("op")
    if _blank(field) or not isinstance(field, str):
        return ["叶子条件缺 field（或 field 不是字符串）"]
    if op not in OPS:
        return [f"未知算子 {op!r}（白名单：{', '.join(OPS)}）"]

    has_value = "value" in condition
    if op in _NO_VALUE_OPS:
        if has_value:
            problems.append(f"算子 {op} 不得带 value")
        return problems
    if not has_value:
        return [f"算子 {op} 必须带 value"]

    value = condition["value"]
    if op in _ARRAY_OPS:
        if not isinstance(value, (list, tuple)) or not value:
            problems.append(f"算子 {op} 的 value 必须是非空数组")
    elif op in _SUBSTRING_OPS:
        if not isinstance(value, str) or _blank(value):
            problems.append(f"算子 {op} 的 value 必须是非空字符串")
    else:  # eq / ne
        if isinstance(value, (dict, list)):
            problems.append(f"算子 {op} 的 value 必须是标量")
    return problems


def is_executable(condition: Any) -> bool:
    """这条条件能不能被机器判？（自由文本 / 结构不合法 ⇒ False）"""
    return bool(condition) and isinstance(condition, dict) and not validate(condition)


def _evaluate(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    if "all" in condition:
        return all(_evaluate(c, context) for c in condition["all"])
    if "any" in condition:
        return any(_evaluate(c, context) for c in condition["any"])
    if "not" in condition:
        return not _evaluate(condition["not"], context)

    field = condition["field"]
    op = condition["op"]
    # 缺字段 ⇒ 叶子为假（fail-closed）。`not_exists` 是唯一「缺字段为真」的算子。
    present = field in context and not _blank(context.get(field))
    if op == "exists":
        return present
    if op == "not_exists":
        return not present
    if not present:
        return False

    actual = context[field]
    value = condition.get("value")
    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "in":
        return actual in value
    if op == "not_in":
        return actual not in value
    if op == "contains":
        return value in str(actual)
    if op == "not_contains":
        return value not in str(actual)
    return False  # 白名单之外（validate 已拦住，这里是不抛异常的第二道）


def evaluate(condition: Any, context: Optional[Dict[str, Any]] = None) -> bool:
    """这条条件在**当前语境**下成立吗？不合法 / 缺语境 / 任何异常 ⇒ False。"""
    if not is_executable(condition):
        return False
    try:
        return _evaluate(condition, dict(context or {}))
    except Exception:  # noqa: BLE001 — 调用点在 prompt 组装路径上，绝不传播
        return False


def describe(condition: Any) -> str:
    """把结构化条件渲染成一句人类 / 模型都能读的说明（**由结构生成，不接受自由文本**）。

    渲染失败（非法条件）⇒ 返回空串，调用方据此把整张卡排除。
    """
    if not is_executable(condition):
        return ""
    try:
        return _describe(condition)
    except Exception:  # noqa: BLE001
        return ""


def _describe(condition: Dict[str, Any], depth: int = 0) -> str:
    if depth > MAX_DEPTH:
        return ""
    if "all" in condition:
        return "（且 " + "；".join(_describe(c, depth + 1) for c in condition["all"]) + "）"
    if "any" in condition:
        return "（或 " + "；".join(_describe(c, depth + 1) for c in condition["any"]) + "）"
    if "not" in condition:
        return "（非 " + _describe(condition["not"], depth + 1) + "）"

    field = condition["field"]
    op = condition["op"]
    label = _FIELD_LABELS.get(field, field)
    op_label = _OP_LABELS[op]
    if op in _NO_VALUE_OPS:
        return f"{label}{op_label}"
    value = condition["value"]
    if op in _ARRAY_OPS:
        rendered = "、".join(str(v) for v in value)
        return f"{label}{op_label}［{rendered}］"
    return f"{label}{op_label}「{value}」"
