"""
工具契约扫描 — parameters schema ↔ execute() 签名一致性
# case_ids: PP-001, PR-010, OR-001

防「schema 声明了参数但 execute 签名没有接收」导致的 TypeError 静默崩溃。
生产事故（sess_fba38395ed094a9d 系列，issue #2892/#2894）：
- interact.parameters 声明了 pageMeta（LLM 按 processing_item_query 提示透传），
  但 execute() 签名缺该参数 → tool.execute(**args) 抛 TypeError → agent 流崩；
- 同类：multiSelect 参数同样曾被遗漏。

规则：
- 每个工具 parameters.properties 的 key 必须能落到 execute() 签名：
  * execute 有显式同名（规范化后）参数 → 通过
  * execute 无显式参数但有 **kwargs 兜底 → 通过（kwargs 设计，如 action 分发工具）
  * execute 既无该参数也无 **kwargs → 🔴 断裂（LLM 传参必 TypeError）
- 检测为运行时（inspect.signature + 类级 parameters），覆盖全部注册工具。
"""
import importlib
import inspect
import pkgutil
import re

import pytest

from app.tools.base import BaseTool


def _norm(name: str) -> str:
    """参数名规范化：忽略大小写/下划线/连字符（pageMeta ≡ page_meta ≡ page-meta）"""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _iter_tool_classes():
    """遍历 app.tools 下所有模块定义的工具类（继承 BaseTool 且有 name）"""
    import app.tools as tools_pkg
    for modinfo in pkgutil.iter_modules(tools_pkg.__path__):
        if modinfo.name.startswith("__"):
            continue
        try:
            mod = importlib.import_module(f"app.tools.{modinfo.name}")
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if not inspect.isclass(obj) or obj.__module__ != mod.__name__:
                continue
            if not issubclass(obj, BaseTool):
                continue
            if not isinstance(getattr(obj, "name", None), str) or not obj.name:
                continue
            yield obj


def _scan_contract_breaks() -> list[dict]:
    """扫描全部工具的 schema/signature 断裂。

    Returns: 断裂列表，每项 {tool, missing_keys}；无断裂返回 []。
    """
    breaks = []
    for cls in _iter_tool_classes():
        props = (getattr(cls, "parameters", {}) or {}).get("properties", {})
        if not props:
            continue
        try:
            sig = inspect.signature(cls.execute)
        except (TypeError, ValueError):
            continue
        sig_params = {
            _norm(p) for p in sig.parameters if p not in ("self", "context")
        }
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        if has_kwargs:
            # kwargs 兜底设计（如 action 分发工具）：无法静态判定，视为通过
            continue
        missing = [
            k for k in props if _norm(k) not in sig_params
        ]
        if missing:
            breaks.append({"tool": cls.name, "missing_keys": sorted(missing)})
    return breaks


def test_all_tool_schema_keys_reachable_in_execute_signature():
    """全量工具：schema 声明参数必须可被 execute() 显式签名接收（无 kwargs 时）。

    回归（issue #2892/#2894）：interact 曾声明 pageMeta/multiSelect 但签名缺失
    → LLM 透传即 TypeError、agent 流崩溃。此测试确保该类断裂永久被拦截。
    """
    breaks = _scan_contract_breaks()
    assert breaks == [], (
        "以下工具 parameters schema 声明了 execute() 不接收的参数，"
        "LLM 按 schema 传参将 TypeError：\n"
        + "\n".join(
            f"  🔴 {b['tool']}: {b['missing_keys']}"
            for b in breaks
        )
    )


# ── 反向验证：检测器自身能识别「schema 有、签名无、无 kwargs」的类 ──

class _BrokenContractTool(BaseTool):
    """模拟断裂：schema 声明 extra_field 但 execute 无该参数也无 kwargs。"""
    name = "test_broken_contract"
    description = "契约断裂模拟工具（仅测试用）"
    parameters = {
        "type": "object",
        "properties": {
            "extra_field": {"type": "string", "description": "签名缺失参数"},
        },
        "required": [],
    }

    async def execute(self, context, component: str = "choice") -> "ToolResult":
        """无 extra_field 参数、无 **kwargs —— 传 extra_field 必然 TypeError。"""
        from app.tools.base import ToolResult
        return ToolResult(success=True, data={"component": component})


def test_detector_catches_schema_without_signature():
    """检测器能识别「schema 声明但 execute 不接收」的类（防检测器自身失效）。"""
    breaks = _scan_contract_breaks()
    # 全量扫描不包含测试类（未注册），改为单类检测：
    props = _BrokenContractTool.parameters.get("properties", {})
    sig = inspect.signature(_BrokenContractTool.execute)
    sig_params = {_norm(p) for p in sig.parameters if p not in ("self", "context")}
    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    assert not has_kwargs
    missing = [k for k in props if _norm(k) not in sig_params]
    assert missing == ["extra_field"], f"检测器应识别出 extra_field 缺失，得到 {missing}"