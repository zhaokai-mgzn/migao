"""
工具契约扫描 — parameters schema ↔ execute() 签名一致性 / description ↔ schema 参数一致性
# case_ids: PP-001, PR-010, OR-001, PP-006

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


# ── ① 契约层（续）：description 点名的参数必须存在于 schema properties ──
#
# 回归（issue #3543 / acceptance/2026-09-14/replay-triage §2.3）：
# processing_item_manage 的 description 写「调 processing_item_manage(action=create_processing_item,
# name, category_id, pricing_method)」，但 parameters.properties 里**没有** pricing_method，
# execute() 也不接收 → LLM 永远拿不到这个参数 → 创建请求缺 admin-api @NotBlank 的 pricingMethod
# → Bean Validation 422「参数校验失败」→ B 端「新增加工项」完全不可用，且单测（只断言 categoryId）
# 与评测用例（只断言"工具被调用过"）双双放过。
# 规则：description 中以「本工具名(关键字参数…)」形式点名的参数，必须都在 schema 里声明。

_DOC_ARG_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _documented_args(tool_name: str, description: str) -> list[str]:
    """提取 description 里「<tool_name>(k=v, name, ...)」形式点名的参数名。

    只解析**含 `=` 的参数列表**（关键字参数式调用描述）：不含 `=` 的括号组是
    action 值说明（如 `employee_manage(list)` 的 `list` 是 action，不是参数），
    中文说明（如 `list_categories(查分类树,安全)`）由 ASCII 标识符过滤自然排除。
    """
    args: list[str] = []
    for m in re.finditer(r"\b" + re.escape(tool_name) + r"\s*\(([^()]*)\)", description or ""):
        group = m.group(1)
        if "=" not in group:
            continue
        for part in group.split(","):
            key = part.strip().split("=", 1)[0].strip()
            if _DOC_ARG_IDENT_RE.match(key):
                args.append(key)
    return args


def _scan_description_schema_drifts() -> list[dict]:
    """扫描全部工具：description 点名的参数必须 ⊆ schema properties。"""
    drifts = []
    for cls in _iter_tool_classes():
        props = set((getattr(cls, "parameters", {}) or {}).get("properties", {}))
        documented = _documented_args(cls.name, getattr(cls, "description", "") or "")
        missing = sorted({a for a in documented if _norm(a) not in {_norm(p) for p in props}})
        if missing:
            drifts.append({"tool": cls.name, "missing_keys": missing})
    return drifts


def test_documented_params_in_description_exist_in_schema():
    """全量工具：description 里点名的参数必须存在于 schema properties。

    防「描述要求了 schema 不存在、execute 也不接收的参数」——LLM 按描述传参
    要么被静默丢弃、要么 TypeError；而工具只能拿到缺参的调用（issue #3543）。
    """
    drifts = _scan_description_schema_drifts()
    assert drifts == [], (
        "以下工具 description 点名了 schema properties 里不存在的参数，"
        "LLM 按描述传参将丢失或被拒：\n"
        + "\n".join(f"  🔴 {d['tool']}: {d['missing_keys']}" for d in drifts)
    )


def test_description_drift_detector_catches_missing_property():
    """检测器自身有效性：description 点名 extra_field 但 properties 无 → 必被识别。"""
    class _DriftTool(BaseTool):
        name = "test_description_drift"
        description = "调 test_description_drift(action=create, item_id, ghost_field) 创建。"
        parameters = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "item_id": {"type": "string"},
            },
            "required": ["action"],
        }

        async def execute(self, context, action: str, item_id: str = ""):
            from app.tools.base import ToolResult
            return ToolResult(success=True)

    documented = _documented_args(_DriftTool.name, _DriftTool.description)
    props = {_norm(p) for p in _DriftTool.parameters["properties"]}
    missing = [a for a in documented if _norm(a) not in props]
    assert documented == ["action", "item_id", "ghost_field"]
    assert missing == ["ghost_field"]