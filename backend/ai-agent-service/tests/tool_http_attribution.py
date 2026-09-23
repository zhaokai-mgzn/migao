"""跨端**静态归属机具**（工具 HTTP 调用点 ↔ admin-api 端点）—— issue #5246 抽出共用。

本文件由 `tests/test_tool_payload_backend_contract.py`（issue #3570 建的 payload 契约门禁）
**原样搬出**，唯一改动 = 把「非注解 POJO 形参 → 字段集合」解析器改为**显式注入**：
本模块**只用标准库**（ast / re / dataclasses / functools / pathlib），才能被仓库根的
`tests/unit_ci_workflows/` 复用 —— 那个 CI job 只 `pip install pytest pyyaml`，没有 pydantic。
而 Java DTO 字段解析器住在 `tests/test_tool_field_name_contract.py`（`from app.tools.base import BaseTool`
⇒ 需要 pydantic），因此由需要 `query_fields` 的调用方自己传进来。

**不复制第二份解析器**（#3570 的教训：两套门禁各管一摊必然口径漂移）：两个消费方共用本文件 ——
① `tests/test_tool_payload_backend_contract.py` —— payload 键 ⊆ 接收端可读键；
② `tests/unit_ci_workflows/test_agent_permission_parity.py` —— 工具权限码 ↔ 端点生效码 ↔ 菜单节点。

> 谁需要 `query_fields`（Spring 把非注解 POJO 形参按 query 绑定到其字段）：传 `resolve_pojo_fields`。
> 不传 ⇒ 该来源不并入（对「只判端点/权限码」的消费方无影响）。**这是显式参数而不是静默默认**，
> 因为静默默认会让「忘了传」退化成一条永远为空的断言。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional


_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "app" / "tools"
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

# 工具源码里 payload 的四种形态（app/utils/http_client.py::AdminApiClient 的形参名）
PAYLOAD_KWARGS = ("json_data", "params", "data")

# payload 之外的合法透传 kwarg（同一 client 形参，非 payload 载体）：
#   tenant_id / user_id → X-Tenant-Id / X-User-Id 头；timeout → 请求超时；
#   headers             → extra_headers（`_get_headers` 合并，logistics_track.py 已在用）
# 单一事实源：扫描器（_tool_calls）与「未知 kwarg」用例共用本常量，避免两处漂移。
CLIENT_PASSTHROUGH_KWARGS = ("tenant_id", "user_id", "timeout", "headers")
# ══════════════════════════════════════════════════════════════════════════
# 一、Java 侧：端点 → 接收端可读键
# ══════════════════════════════════════════════════════════════════════════


def _path_template(node: ast.AST) -> str | None:
    """把路径表达式渲染成模板字符串（f-string 占位符 → `{...}`）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            else:
                out.append("{...}")
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # 无法静态求值的操作数（f-string 之外的拼接，如 "/api/x/" + ticket_id）→ 视作路径变量 `{}`
        left = _path_template(node.left)
        right = _path_template(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else "{}") + (right if right is not None else "{}")
    return None


def _norm_path(path: str) -> str:
    """归一化端点路径：去 query、`{var}`/`{...}`→`{}`、去尾斜杠。"""
    path = path.split("?", 1)[0]
    path = re.sub(r"\{[^{}]*\}", "{}", path)
    return path.rstrip("/")


#: `@RequirePermission("x")` / `@RequirePermission(value = "x")` —— 生效权限码的唯一来源。
_REQUIRE_PERMISSION_RE = re.compile(
    r"@RequirePermission\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']"
)
_CLASS_DECL_RE = re.compile(r"\bclass\s+\w+")


#: Java 注释（`//…` 与 `/* … */`）—— 注解解析前必须先剥掉：本仓大量 javadoc/行内注释
#: 逐字写着 `@RequirePermission("…")` 作为**说明**（如「本方法无 @RequirePermission」），
#: 不剥会把说明当成真注解 ⇒ 生效码判错（issue #5246 实测）。
_JAVA_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)

#: 向前回看的窗口（映射注解之前紧邻的注解区不会超过这个长度）。
_ANNOTATION_BACK_WINDOW = 400


def _strip_java_comments(text: str) -> str:
    return _JAVA_COMMENT_RE.sub(" ", text)


def _annotations_before(src: str, idx: int) -> str:
    """映射注解 `idx` **之前紧邻**的注解区（截止上一个 `}`/`{`/`;`）。

    为什么必须向后看：本仓两种写法并存 —— `@RequirePermission(...)` 既可写在
    `@GetMapping` **之后**（`AfterSalesController` 的类级），也可写在**之前**
    （`StockBatchController` 七个端点全部如此，`BriefingController` / `ProductionPoolController`
    / `StockLedgerController` 同款）。只向前看会把前一类整片判成「未注解」⇒ 漏判。
    """
    window = _strip_java_comments(src[max(0, idx - _ANNOTATION_BACK_WINDOW):idx])
    cut = max(window.rfind("}"), window.rfind("{"), window.rfind(";"))
    return window[cut + 1:]


def _class_permission(src: str) -> str | None:
    """controller 的**类级** `@RequirePermission`（= 第一个类声明的注解区里的那一个）。

    取第一个类声明**之前**的注解区：一个 controller 文件里后续/嵌套类的注解不属于
    controller 本体。找不到 ⇒ `None`（未注解；由消费方的判据处置，不在这里静默兜底）。
    """
    m = _CLASS_DECL_RE.search(src)
    if not m:
        return None
    hits = _REQUIRE_PERMISSION_RE.findall(_strip_java_comments(src[: m.start()]))
    return hits[-1] if hits else None


class _JavaParse:
    """Java controller 静态解析（verb + 路径 → @RequestBody 类型 / Map 体读键 / query 参数）。"""

    _METHOD_RE = re.compile(r"@(Get|Post|Put|Patch|Delete)Mapping\b")
    _CLASS_MAPPING_RE = re.compile(r"@RequestMapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']")
    _PATH_ATTR_RE = re.compile(r"(?:value|path)\s*=\s*[\"']([^\"']*)[\"']")


def _split_sig_args(sig: str) -> list[str]:
    """按顶层逗号切分方法形参（跳过泛型尖括号与括号嵌套）。"""
    parts, depth, angle, buf = [], 0, 0, []
    in_str: str | None = None
    for ch in sig:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "<":
            angle += 1
            buf.append(ch)
        elif ch == ">":
            angle -= 1
            buf.append(ch)
        elif ch == "," and depth == 0 and angle == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _method_signature(src: str, start: int) -> tuple[str, int] | None:
    """从注解结束处向后取方法签名（到方法体 `{` 为止），返回 (签名, `{` 下标)。

    先跳过注解自身的参数列表（`@PostMapping("/x")` 的括号），否则括号配平会整体偏移。
    """
    i = start
    while i < len(src) and src[i].isspace():
        i += 1
    if i < len(src) and src[i] == "(":
        depth_, in_str_ = 0, None
        while i < len(src):
            ch = src[i]
            if in_str_:
                if ch == in_str_ and src[i - 1] != "\\":
                    in_str_ = None
            elif ch in "\"'":
                in_str_ = ch
            elif ch == "(":
                depth_ += 1
            elif ch == ")":
                depth_ -= 1
                if depth_ == 0:
                    i += 1
                    break
            i += 1
    start = i
    i, depth, in_str = start, 0, None
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == in_str and src[i - 1] != "\\":
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "{" and depth == 0:
            return src[start:i], i
        elif ch == ";" and depth == 0:
            return None
        i += 1
    return None


def _split_leading_annotations(sig: str) -> tuple[str, str]:
    """切出「方法签名前导注解区」与「从返回类型开始的余下文本」。

    前导注解区是 `@RequirePermission` **唯一**可能出现的位置（方法级注解必须紧邻签名），
    权限对账（issue #5246）靠它取方法级生效码 ⇒ 返回而不是丢弃。
    """
    s = sig.lstrip()
    while s.startswith("@"):
        m = re.match(r"@[\w.]+", s)
        if not m:
            break
        s = s[m.end() :].lstrip()
        if not s.startswith("("):
            continue
        depth, in_str, i = 0, None, 0
        while i < len(s):
            ch = s[i]
            if in_str:
                if ch == in_str and s[i - 1] != "\\":
                    in_str = None
            elif ch in "\"'":
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        s = s[i:].lstrip()
    consumed = len(sig) - len(s)
    return sig[:consumed], s


def _strip_leading_annotations(sig: str) -> str:
    """剥掉方法签名前的连续方法级注解，只返回从返回类型开始的文本（保持既有调用口径）。"""
    return _split_leading_annotations(sig)[1]


def _balanced_block(src: str, open_idx: int) -> str:
    """取 `{` 开始的整段配平代码块。"""
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx : i + 1]
    return src[open_idx:]


_NON_POJO_TYPES = frozenset(
    {
        "String", "Integer", "Long", "Boolean", "Double", "Float", "BigDecimal",
        "int", "long", "boolean", "double", "float",
        "HttpServletRequest", "HttpServletResponse", "HttpSession", "Principal",
        "Authentication", "MultipartFile", "List", "Set", "Collection", "Page",
        "Map", "Optional", "Object",
    }
)

@dataclass(frozen=True)
class JavaEndpoint:
    verb: str
    path: str                     # 归一化
    controller: str               # 相对 java 根的文件名（含目录）
    line: int
    body_type: str | None         # @RequestBody 的类名；Map 体为 None
    body_var: str | None
    map_reads: frozenset[str]     # Map 体在 handler 作用域内读到的键
    params: frozenset[str]        # @RequestParam 名
    path_vars: frozenset[str]     # @PathVariable 名
    query_fields: frozenset[str]  # 非注解 POJO 形参（Spring 按 query param 绑定）字段
    class_permission: str | None = None   # 类级 @RequirePermission（无注解 ⇒ None）
    method_permission: str | None = None  # 方法级 @RequirePermission（覆盖类级；无 ⇒ None）

    @property
    def permission(self) -> str | None:
        """端点的**生效**权限码：方法级优先、其次类级。

        与 `PermissionInterceptor` 的解析顺序同口径（`docs/wiki/RBAC.md`
        「方法级注解优先、其次类级」）—— 本属性是权限对账（issue #5246）的唯一取值口。
        """
        return self.method_permission or self.class_permission

@lru_cache(maxsize=1)
def _java_sources() -> dict[str, str]:
    if not _JAVA_MAIN.is_dir():
        return {}
    return {
        str(p.relative_to(_JAVA_MAIN)): p.read_text(encoding="utf-8")
        for p in _JAVA_MAIN.rglob("*.java")
    }


def java_endpoints(
    resolve_pojo_fields: Optional[Callable[[str], frozenset]] = None,
    java_sources: Optional[dict] = None,
) -> dict[tuple[str, str], tuple[JavaEndpoint, ...]]:
    """解析全部 controller 的端点（verb + 归一化路径 → 端点；同路径多 verb 各自成条）。

    `java_sources`：**显式传入**的 {相对 java 根路径: 源码}（缺省 = 读磁盘）。存在的理由 =
    注入式红证：消费方要能对「改过的源码文本」跑同一份解析器，而不是只能对被篡改过的磁盘
    文件跑（否则「注入改内存文本、判据仍读磁盘」⇒ 判据永远不变红 = 空断言，issue #5246 实测踩过）。
    """
    out: dict[tuple[str, str], list[JavaEndpoint]] = {}
    srcs = _java_sources() if java_sources is None else java_sources
    for rel, src in srcs.items():
        if "/controller/" not in rel.replace("\\", "/"):
            continue
        class_permission = _class_permission(src)
        class_base = ""
        cm = _JavaParse._CLASS_MAPPING_RE.search(src)
        if cm and cm.start() < src.find("class "):
            class_base = cm.group(1)
        for mm in _JavaParse._METHOD_RE.finditer(src):
            verb = mm.group(1).upper()
            ann_tail = src[mm.end() : mm.end() + 200]
            # 同注解内的 path（`@PostMapping("/x")` / `@PostMapping(value="/x")` /
            # `@GetMapping({"", "/tree"})` 数组形态 —— 一个方法可映射多条路径）
            subs = _annotation_paths(ann_tail)
            sig_info = _method_signature(src, mm.end())
            if sig_info is None:
                continue
            sig, brace = sig_info
            body_type = body_var = None
            params: set[str] = set()
            path_vars: set[str] = set()
            query_fields: set[str] = set()
            # 方法名前的**方法级注解**（如 @RequirePermission("...")）必须先剥掉，
            # 否则 `find("(")` 会定位到注解的括号 → 形参整体错位（曾漏掉 GET/POST /users 的
            # `page` 与 `@RequestBody Map body`）。
            ann_head, sig_head = _split_leading_annotations(sig)
            # 方法级生效码：**映射注解之前**的注解区 + 之后的紧邻注解区里那一个
            # （两种书写顺序都覆盖；方法级覆盖类级 —— 同 `PermissionInterceptor.resolveRequirePermission`）
            ann_region = _annotations_before(src, mm.start()) + ann_head
            method_permission = (_REQUIRE_PERMISSION_RE.findall(ann_region) or [None])[-1]
            params_src = (
                sig_head[sig_head.find("(") + 1 : sig_head.rfind(")")]
                if "(" in sig_head
                else ""
            )
            for raw in _split_sig_args(params_src):
                # 去掉前置注解，取类型 + 变量名
                ann_names = re.findall(r"@(\w+)", raw)
                stripped = re.sub(r"@\w+(?:\([^)]*\))?", " ", raw).strip()
                tm = re.match(r"([\w.<>,\[\]\s]+?)\s+(\w+)$", stripped)
                if not tm:
                    continue
                type_raw, name = tm.group(1).strip(), tm.group(2)
                base_type = type_raw.split("<")[0].split(".")[-1].strip()
                if "RequestBody" in ann_names:
                    if base_type == "Map":
                        body_var = name
                    else:
                        body_type = base_type
                elif "RequestParam" in ann_names:
                    nm = re.search(r"\b(?:name|value)\s*=\s*[\"']([^\"']+)[\"']", raw)
                    params.add(nm.group(1) if nm else name)
                elif "PathVariable" in ann_names:
                    nm = re.search(r"\b(?:name|value)\s*=\s*[\"']([^\"']+)[\"']", raw)
                    path_vars.add(nm.group(1) if nm else name)
                elif base_type not in _NON_POJO_TYPES and base_type[:1].isupper():
                    # 非注解 POJO 形参：Spring 按 query param 绑定到其字段（如 ProductQueryRequest）；
                    # 不是 DTO 命名的类解析不到字段 → 不追加来源（不影响断言）
                    try:
                        pojo_fields = (
                            resolve_pojo_fields(base_type)
                            if resolve_pojo_fields is not None
                            else frozenset()
                        )
                    except AssertionError:
                        pojo_fields = frozenset()
                    query_fields |= set(pojo_fields)
            map_reads: set[str] = set()
            if body_var:
                body = _balanced_block(src, brace)
                for pat in (
                    rf"\b{re.escape(body_var)}\.get\s*\(\s*[\"']([^\"']+)[\"']",
                    rf"\b{re.escape(body_var)}\.getOrDefault\s*\(\s*[\"']([^\"']+)[\"']",
                    rf"\b{re.escape(body_var)}\.containsKey\s*\(\s*[\"']([^\"']+)[\"']",
                ):
                    map_reads |= set(re.findall(pat, body))
            # Spring：方法级 path 一律**相对**类级 base 拼接（不以 "/" 覆盖 base），
            # 但类级 base 缺失时（部分 controller 直接写全路径）方法级即全路径。
            ep_base = dict(
                verb=verb,
                controller=rel,
                line=src[: mm.start()].count("\n") + 1,
                body_type=body_type,
                body_var=body_var,
                map_reads=frozenset(map_reads),
                params=frozenset(params),
                path_vars=frozenset(path_vars),
                query_fields=frozenset(query_fields),
                class_permission=class_permission,
                method_permission=method_permission,
            )
            for sub in subs or [""]:
                seg = sub.strip()
                if not class_base or (seg and seg.startswith(_norm_path(class_base))):
                    full = _norm_path(seg)
                else:
                    full = _norm_path(f"{class_base.rstrip('/')}/{seg.lstrip('/')}")
                out.setdefault((verb, full), []).append(JavaEndpoint(path=full, **ep_base))
    return {k: tuple(v) for k, v in out.items()}


def _annotation_paths(ann_tail: str) -> list[str]:
    """取 `@XxxMapping(...)` 里的路径列表（支持数组形态与 value=/path= 属性）。"""
    text = ann_tail.lstrip()
    if not text.startswith("("):
        return [""]
    depth, end, in_str = 0, None, None
    for i, ch in enumerate(text):
        if in_str:
            if ch == in_str and text[i - 1] != "\\":
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    seg = text[1:end] if end is not None else text[1:]
    if not seg.strip():
        return [""]
    pm = _JavaParse._PATH_ATTR_RE.search(seg)
    if pm:
        # value=/path= 属性：取该属性值（可能为 {...} 数组），只收大括号内的字符串
        tail = seg[pm.start() :]
        brace = tail.find("{")
        tail = tail[: tail.find(")", 1)] if brace < 0 else tail[: tail.find("}") + 1]
        return _quoted(tail)
    # 位置参数写法：仅当首个 token 是字符串或数组括号时才当路径（避免把 produces= 当路径）
    if re.match(r"\s*[\[\{]\s*[\"']|\s*[\"']", seg):
        return _quoted(seg)
    return [""]


def _quoted(seg: str) -> list[str]:
    return re.findall(r"[\"']([^\"']*)[\"']", seg)
# ══════════════════════════════════════════════════════════════════════════
# 二、Python 侧：工具 payload 键静态提取
# ══════════════════════════════════════════════════════════════════════════

_CLIENT_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


@dataclass
class ToolCall:
    file: str                              # app/tools/xxx.py
    line: int
    method: str
    path: str                              # 原始（模板化）
    endpoint: str                          # 归一化
    payload_kwarg: str | None              # json_data / params / data（None = 未传 payload）
    keys: tuple[tuple[str, int], ...] = ()  # 静态解析出的 payload 键
    dynamic: tuple[tuple[str, int], ...] = ()  # 无法静态解析的构造点

    @property
    def key_set(self) -> frozenset[str]:
        return frozenset(k for k, _ in self.keys)


def _dict_keys(node: ast.Dict) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    keys, dyn = [], []
    for k in node.keys:
        if k is None:  # `{**other}`
            dyn.append(("<** 展开>", node.lineno))
            continue
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.append((k.value, k.lineno))
        else:
            dyn.append((ast.unparse(k)[:40], k.lineno))
    return keys, dyn


def _helper_return_keys(
    callee: str, module_funcs: dict[str, ast.AST]
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]] | None:
    """跟随模块/类内 payload 构造 helper（`payload = _build_notify_payload(...)`）。

    只认「helper 里有 return 字典字面量」这一种形态（收其 `return {...}` 的键）；
    认不出就返回 None，让调用方按动态构造登记 —— 不猜、不静默放过。
    """
    fdef = module_funcs.get(callee)
    if fdef is None:
        return None
    keys: list[tuple[str, int]] = []
    dyn: list[tuple[str, int]] = []
    found = False
    for node in ast.walk(fdef):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        if isinstance(node.value, ast.Dict):
            k, d = _dict_keys(node.value)
            keys += k
            dyn += d
            found = True
        elif isinstance(node.value, ast.Name):
            k, d = _resolve_named(node.value.id, fdef, node.lineno, module_funcs)
            keys += k
            dyn += d
            found = True
    if not found:
        return None
    return keys, dyn


def _resolve_payload_expr(
    expr: ast.AST,
    func_node: ast.AST,
    before_line: int,
    module_funcs: dict[str, ast.AST] | None = None,
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """解析 payload 表达式 → (静态键, 动态点)。

    `before_line` 之前的同名赋值 / `name["k"]=v` / `name.update(...)` 全部计入
    （只看调用点**之前**的语句，避免审计脚本「整函数作用域收键」导致的串扰假阳性）。
    """
    module_funcs = module_funcs or {}
    if isinstance(expr, ast.Constant) and expr.value is None:
        return [], []  # `params or None` 的兜底分支：语义是「不传 payload」，不是动态键
    if isinstance(expr, ast.Dict):
        return _dict_keys(expr)
    if isinstance(expr, ast.Name):
        return _resolve_named(expr.id, func_node, before_line, module_funcs)
    if isinstance(expr, ast.BoolOp):
        # `params=params or None`（短路兜底写法）：各操作数都可能是实际发出的 payload
        keys: list[tuple[str, int]] = []
        dyn: list[tuple[str, int]] = []
        for v in expr.values:
            k, d = _resolve_payload_expr(v, func_node, before_line, module_funcs)
            keys += k
            dyn += d
        return keys, dyn
    if isinstance(expr, ast.IfExp):
        keys = []
        dyn = []
        for v in (expr.body, expr.orelse):
            k, d = _resolve_payload_expr(v, func_node, before_line, module_funcs)
            keys += k
            dyn += d
        return keys, dyn
    if isinstance(expr, ast.Call):
        callee = (
            expr.func.id
            if isinstance(expr.func, ast.Name)
            else expr.func.attr
            if isinstance(expr.func, ast.Attribute)
            else ""
        )
        if callee == "dict":
            keys = [(kw.arg, kw.lineno) for kw in expr.keywords if kw.arg]
            return keys, [] if keys else [("<dict() 动态>", expr.lineno)]
        followed = _helper_return_keys(callee, module_funcs)
        if followed is not None:
            return followed
    return [], [(ast.unparse(expr)[:40], getattr(expr, "lineno", 0))]


def _resolve_named(
    name: str,
    func_node: ast.AST,
    before_line: int,
    module_funcs: dict[str, ast.AST] | None = None,
    _seen: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    module_funcs = module_funcs or {}
    if name in _seen:
        return [], []
    _seen = _seen | {name}
    keys: list[tuple[str, int]] = []
    dyn: list[tuple[str, int]] = []
    resolved_any = False
    for node in ast.walk(func_node):
        if not hasattr(node, "lineno") or node.lineno >= before_line:
            continue
        # name = {...} / name: Dict = {...} / name = other
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is None:
                continue
            for tgt in targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    resolved_any = True
                    if isinstance(node.value, ast.Dict):
                        k, d = _dict_keys(node.value)
                        keys += k
                        dyn += d
                    elif isinstance(node.value, ast.Name):
                        k, d = _resolve_named(
                            node.value.id, func_node, node.lineno, module_funcs, _seen
                        )
                        keys += k
                        dyn += d
                    elif isinstance(node.value, ast.Call):
                        callee = (
                            node.value.func.id
                            if isinstance(node.value.func, ast.Name)
                            else getattr(node.value.func, "attr", "")
                        )
                        followed = _helper_return_keys(callee, module_funcs)
                        if followed is None:
                            dyn.append((ast.unparse(node.value)[:40], node.lineno))
                        else:
                            keys += followed[0]
                            dyn += followed[1]
                    else:
                        dyn.append((ast.unparse(node.value)[:40], node.lineno))
        # name["k"] = v
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == name
                ):
                    resolved_any = True
                    if isinstance(tgt.slice, ast.Constant) and isinstance(tgt.slice.value, str):
                        keys.append((tgt.slice.value, tgt.lineno))
                    else:
                        dyn.append((f"{name}[{ast.unparse(tgt.slice)[:30]}]", tgt.lineno))
        # name.update({...}) / name.update(k=v)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "update"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == name
            ):
                resolved_any = True
                for a in node.args:
                    if isinstance(a, ast.Dict):
                        k, d = _dict_keys(a)
                        keys += k
                        dyn += d
                    else:
                        dyn.append((ast.unparse(a)[:40], node.lineno))
                for kw in node.keywords:
                    if kw.arg:
                        keys.append((kw.arg, kw.lineno))
    if not resolved_any:
        # 形参 / 外部来源（如 LLM 直供的自由字典）→ 静态不可解析，必须显式登记
        dyn.append((f"<{name} 来自函数形参或外部，静态不可解析>", before_line))
    return keys, dyn


@lru_cache(maxsize=1)
def tool_calls() -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        rel = f"app/tools/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        # helper 名 → 定义（payload 常由 `_build_xxx_payload(...)` 返回字典构造）
        funcs_by_name = {f.name: f for f in funcs}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr not in _CLIENT_METHODS:
                continue
            if not node.args:
                continue
            raw_path = _path_template(node.args[0])
            if not raw_path or not raw_path.startswith("/api"):
                continue
            # 只保留最内层闭包函数（payload 一般在同一函数内构造）
            enclosing = [f for f in funcs if f.lineno <= node.lineno <= f.end_lineno]
            enclosing.sort(key=lambda f: (f.end_lineno - f.lineno))
            scope = enclosing[0] if enclosing else tree
            payload_kw = None
            keys: list[tuple[str, int]] = []
            dyn: list[tuple[str, int]] = []
            for kw in node.keywords:
                if kw.arg in PAYLOAD_KWARGS:
                    payload_kw = kw.arg
                    k, d = _resolve_payload_expr(kw.value, scope, node.lineno, funcs_by_name)
                    keys += k
                    dyn += d
                elif kw.arg is not None and kw.arg not in CLIENT_PASSTHROUGH_KWARGS:
                    dyn.append((f"未知 kwarg {kw.arg}=（client 不支持 → TypeError）", node.lineno))
            calls.append(
                ToolCall(
                    file=rel,
                    line=node.lineno,
                    method=fn.attr.upper(),
                    path=raw_path,
                    endpoint=_norm_path(raw_path),
                    payload_kwarg=payload_kw,
                    keys=tuple(sorted(set(keys))),
                    dynamic=tuple(dyn),
                )
            )
    return tuple(calls)


# ══════════════════════════════════════════════════════════════════════════
# 端点索引（verb + 归一化路径 → 端点）—— 供两个消费方共用
# ══════════════════════════════════════════════════════════════════════════


class JavaEndpointIndex:
    """`java_endpoints()` 的索引：端点表 + 路径模板正则 + 查表。

    `resolve_pojo_fields` 见模块头：需要 `query_fields` 的消费方必须显式传入。
    """

    def __init__(
        self,
        resolve_pojo_fields: Optional[Callable[[str], frozenset]] = None,
        java_sources: Optional[dict] = None,
    ):
        self._by_key = java_endpoints(resolve_pojo_fields, java_sources)
        self._regexes = {
            key: re.compile("^" + re.escape(p).replace(re.escape("{}"), "[^/]+") + "$")
            for key, p in ((k, k[1]) for k in self._by_key)
        }

    def endpoints(self) -> dict:
        return self._by_key

    def regexes(self) -> dict:
        return self._regexes

    def lookup(self, verb: str, path: str):
        """按 (verb, 归一化路径) 查端点；模板不匹配时按「具体 id ↔ 路径变量」正则回退。"""
        exact = self._by_key.get((verb, _norm_path(path)))
        if exact:
            return exact
        hits = []
        for (v, _p), rx in self._regexes.items():
            if v == verb and rx.match(_norm_path(path)):
                hits.extend(self._by_key[(v, _p)])
        return tuple(hits)
