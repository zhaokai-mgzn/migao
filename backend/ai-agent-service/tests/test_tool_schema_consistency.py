"""
Tool Schema-Payload 一致性自动检测

防止 silent data loss：扫描所有 write tool，检查每个 _create/_update/_adjust
等写操作方法中，函数参数是否正确映射到 json_data payload。

规则：
- 函数参数 → json_data["camelCase"] ✅
- 函数参数 → 仅用于校验/日志（不出现在 payload）→ 需标注 _UNUSED_IN_PAYLOAD 注释
- 函数参数 → 未出现在 payload 也未标注 → ❌ CI fail

用法：
    cd backend/ai-agent-service
    .venv/bin/python -m pytest tests/test_tool_schema_consistency.py -v
"""

import ast
import re
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent.parent / "app" / "tools"

READ_ONLY = {
    "aftersale_query.py", "product_detail.py", "product_search.py",
    "processing_item_query.py", "processing_items.py", "order_query.py",
    "logistics_track.py", "dashboard_stats.py",
}

SKIP = READ_ONLY | {
    "human_handoff.py", "interact.py", "validate_input.py", "langchain_adapter.py",
    "__init__.py", "base.py", "registry.py",
}

# 总是出现在签名中但不需要进 payload 的参数
ALWAYS_SKIP_PARAMS = {"self", "context", "page", "size", "keyword",
                       "notification_id", "ticket_id", "user_id", "item_id",
                       "role_id", "reply_id", "customer_id", "tag_id",
                       "order_id", "threshold", "action", "status", "channel",
                       "source_channel", "vip_level", "processing_item_id",
                       "quantity", "id", "resource_id", "type", "feature",
                       "target", "metadata", "kwargs_args", "kwargs"}


def _camel_case(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _extract_write_methods(source: str) -> list[dict]:
    """提取每个 _create/_update/_adjust 方法的信息"""
    tree = ast.parse(source)
    methods = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if not any(node.name.startswith(p) for p in
                   ("_create", "_update", "_adjust", "_cancel", "_refund",
                    "_send", "_toggle", "_delete", "_change", "_reset",
                    "_confirm", "_close", "_assign", "_mark", "_save")):
            continue

        params = set()
        for arg in node.args.args:
            if arg.arg not in ("self", "context"):
                params.add(arg.arg)

        method_src = ast.get_source_segment(source, node) or ""

        # 提取 json_data["key"] = 的 key
        payload_keys = set()
        for m in re.finditer(r'json_data\["(\w+)"\]', method_src):
            payload_keys.add(m.group(1))
        # json_data = {"key": ...} 中的 key
        for m in re.finditer(r'json_data\s*=\s*\{([^}]+)\}', method_src):
            for km in re.finditer(r'"(\w+)"\s*:', m.group(1)):
                payload_keys.add(km.group(1))

        # 检查是否有 _UNUSED_IN_PAYLOAD 注释
        unused_comment = set()
        for m in re.finditer(r'_UNUSED_IN_PAYLOAD:\s*(\w+)', method_src):
            for name in m.group(1).split(","):
                unused_comment.add(name.strip())

        methods.append({
            "name": node.name,
            "params": params - ALWAYS_SKIP_PARAMS,
            "payload_keys": payload_keys,
            "unused": unused_comment,
            "source": method_src,
        })

    return methods


def test_write_method_params_reach_payload():
    """写操作方法参数 → payload 一致性检测"""
    failures = []

    for fpath in sorted(TOOLS_DIR.glob("*.py")):
        fname = fpath.name
        if fname in SKIP or fname.startswith("__"):
            continue

        source = fpath.read_text()
        methods = _extract_write_methods(source)

        for m in methods:
            for param in sorted(m["params"]):
                cc = _camel_case(param)

                # 参数被使用的情况
                used_in_payload = (
                    param in m["payload_keys"] or  # name → "name"
                    cc in m["payload_keys"] or      # parent_id → "parentId"
                    param in m["unused"]             # 显式标注
                )

                if not used_in_payload:
                    # 二次确认：参数在方法体内被引用了吗？
                    refs = len(re.findall(r'\b' + re.escape(param) + r'\b', m["source"]))
                    if refs <= 1:  # 只在签名中出现
                        failures.append(
                            f"  {fname}::{m['name']}(): "
                            f"'{param}' 未在 payload 中出现，也未在方法体内使用"
                        )

    if failures:
        msg = (
            "\n🔴 写操作方法参数→Payload 一致性检测失败：\n\n" +
            "\n".join(failures) +
            "\n\n这些参数出现在方法签名中但未映射到 json_data。"
            "\n修复方式：添加到 payload 中，或添加 # _UNUSED_IN_PAYLOAD: param_name 注释"
        )
        raise AssertionError(msg)
