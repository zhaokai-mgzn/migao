"""
跨模块 payload 契约门禁：ai-agent 下发的 payload 键 ⊆ admin-api 接收端可读键
# case_ids: UT-001, ON-003, AS-004, PR-002, PR-019, PR-020, PP-006, HR-001, CU-004, ST-004

① 契约层（docs/testing/interaction-verification.md「① 契约层」）：确定性、零 LLM、零网络。
静态解析 Python 工具源码的 payload 构造 + 静态解析 Java controller/DTO 源码的接收字段，
拦一类**长期批量存活且 CI 全绿**的缺陷：**工具下发的 payload 键，接收端根本不读**。

为什么必须新建这一层（issue #3570，五处漏检实证）：
1. `./contract-check.sh` 实跑 6/6 全绿 + 退出 0 —— 全是 grep 级单点断言，**无一条覆盖
   「payload 键 ∈ 接收端字段」**；
2. `tests/test_tool_schema_consistency.py` 只校验**「函数参数 → json_data 键」的内部一致性**
   （`_camel_case(param) in payload_keys`），**方向与跨模块契约相反**（它看的是
   「参数有没有进 payload」，不看「payload 键后端认不认」）→ 跨模块不一致天生不在射程；
3. 同文件 `ALWAYS_SKIP_PARAMS` 含 `"status"` → `product_update` 的缺陷字段被显式排除；
4. 同文件 `SKIP` 排除 `human_handoff.py`、`READ_ONLY` 排除 `product_search.py`
   → 缺陷文件被跳过；
5. 更结构性的洞：同文件只扫名字以 `_create/_update/...` 开头的写方法，而
   **`product_update.py` 整个文件只有一个 `execute()`**（缺陷 payload 就建在里面）
   → 改任何 skip 列表都扫不到它；`tests/test_tool_field_name_contract.py` 则是
   **运行期**形态（每条契约手写 `tool_kwargs` 并真跑一次工具），只覆盖「已登记且参数可构造」
   的少数调用点。本文件补的正是「全量调用点 × 静态键」这一层。

失效机制（为什么静默）：Python 侧 `AdminApiClient` 不校验 payload 键；Java 侧 Spring Boot
默认 `FAIL_ON_UNKNOWN_PROPERTIES=false`（`application.yml` 只配了 `default-property-inclusion`
与日期格式，未配命名策略）→ **未知键静默丢弃 + HTTP 200 + 工具 `success=True`
+ message 逐字回显未落库的键** ⇒ agent 与用户都确信改成了（`product_update.py:99`
逐字报「商品已更新: status」）。

## 命名口径（不造第二套规则）

**逐字相等（exact match），不做任何大小写转换。**
- 面向 LLM 的 schema 参数是 snake_case（`base.py:170` 的 schema 拼装）；
- 工具作者负责在 payload 里翻成 Java 的 camelCase 字段名（wire 形态）；
- 因此本门禁断言的是 **wire 形态的 payload key 必须与 Java 接收端字段名逐字相等**。
  若某工具下发 `snake_case` key 给 Java camelCase 字段，Spring 同样不绑定 → 也是真缺陷。
- Java 字段名的解析**复用** `tests/test_tool_field_name_contract.py::_dto_fields`
  （同一个正则、同一份 lru_cache、同一套「key 必须落在 Java 已声明字段上」口径）。
  刻意不复制第二份解析器：本项目已踩过「两套门禁各管一摊、口径漂移」的坑（见 #3570）；
  `test_sibling_contract_registry_agrees_with_scanner` 把两者口径互锁。

## 扫描范围（起步 = Agent 端点 + 显式登记表；可增量扩面）

- **Agent 端点**（自动派生，新增 Agent 工具自动纳入）：`AGENT_ENDPOINT_PREFIXES`；
- **显式登记端点**（`SCOPE_EXPLICIT_PATHS`）：承载已确证缺陷的存量端点 + 已确认干净的
  核心域端点（先把它们锁住防回退）；
- 其余 ~20 个端点**暂不在射程**，扩面路径见 issue #3570（每批加一条
  `SCOPE_EXPLICIT_PATHS` + 跑一次报告模式即可看到新批次的存量欠账清单）。

## 制度化的关键：只允许存量收敛，不允许新增

1. 射程内 payload key ∉ 接收端可读键 → **红**（未登记的新键一律红）；
2. 无法解析的 key（动态构造）的调用点必须在 `DYNAMIC_KEY_SITES` 显式登记并写明理由 → 否则红；
3. 带 payload 但路径无法静态归属的调用点必须在 `UNATTRIBUTABLE_CALLS` 登记 → 否则红
   （否则它会静默脱离射程）；
4. 已知存量缺陷必须在 `ALLOWLIST` 登记 `reason` + `owner` + `issue`，缺任一字段 → 红；
5. **白名单条目对应的缺陷一旦被修好（key 不再下发）→ 该条目变「陈旧」→ 红**，
   逼后续包逐条销账（白名单即工作清单，不允许变成垃圾场）；
6. 同族缺陷「工具调用的端点在后端不存在（404）」由 `ENDPOINT_ALLOWLIST` 同规则治理；
7. 显式登记端点必须在 Java 源码里真实存在（防登记表陈旧 → 静默不再覆盖）；
8. 扫描器自检（射程内调用点数与端点可解析性）→ 防扫描器静默退化造成「空转绿」。

报告模式（开发时看全量欠账，不改任何文件）：
    .venv/bin/python -c "import tests.conftest, runpy, sys; \\
        sys.argv=['r','--report']; \\
        runpy.run_module('tests.test_tool_payload_backend_contract', run_name='__main__')"
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 单一事实源复用：既有跨端契约测试的 Java 字段解析器（同一正则 / 同一缓存 / 同一口径）
from tests import test_tool_field_name_contract as _sibling_contract

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "app" / "tools"
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

# 工具源码里 payload 的四种形态（app/utils/http_client.py::AdminApiClient 的形参名）
PAYLOAD_KWARGS = ("json_data", "params", "data")

# ── 扫描范围 ────────────────────────────────────────────────────────────────

# Agent 端点前缀：自动化派生，新增 Agent 工具无需登记即纳入
AGENT_ENDPOINT_PREFIXES = ("/api/admin/agent", "/api/admin/agent-sessions")

# 显式登记端点（存量缺陷所在；扩面时逐条加）
SCOPE_EXPLICIT_PATHS = (
    "/api/admin/orders",                      # order_query 订单查询/统计（已确认干净，纳入防回归）
    "/api/admin/users/{}",                    # employee_manage（Map body，handler 作用域读键）
    "/api/admin/customers/{}",                # customer_manage（CustomerProfile 实体）
    "/api/admin/notifications",               # human_handoff 通知（恒 400）
    "/api/admin/products",                     # product_search / product_manage 查询与建品
    "/api/admin/processing-items/{}",         # processing_item_manage 更新单价
    "/api/admin/processing-categories",       # processing_item_manage 建分类
    "/api/admin/processing-categories/{}",    # processing_item_manage 改分类
    "/api/admin/after-sales",                 # aftersale_query / human_handoff 建工单
    "/api/admin/after-sales/{}/status",       # after_sales_manage 改状态
    "/api/admin/finance/transactions",        # finance_api 登记交易
)

# 无法静态解析 payload 键（动态构造）的调用点：必须显式登记（key = "文件:行"）
DYNAMIC_KEY_SITES: dict[str, str] = {
    "app/tools/customer_manage.py:305": (
        "update 走自由字典透传（data 的 key 由 LLM 直供），静态不可解析 → "
        "由 tests/test_tool_field_name_contract.py 的运行期契约 + customer_manage 字段白名单兜底"
        "（issue #3551 / PR #3562）"
    ),
}

# 带 payload 但路径无法静态渲染（会静默脱离射程）的调用点：必须显式登记（key = "文件:行"）
UNATTRIBUTABLE_CALLS: dict[str, str] = {
    # 例："app/tools/xxx.py:123": "为什么无法归属 + 由谁兜底"
}

# 工具调用指向 admin-api 不存在的端点（404 类跨模块契约缺陷）：
# key = (工具文件相对路径, HTTP 方法, 归一化端点)
ENDPOINT_ALLOWLIST: dict[tuple[str, str, str], dict[str, str]] = {
    ("app/tools/processing_item_manage.py", "PUT", "/api/admin/processing-items/{}/status"): {
        "reason": "ProcessingItemController 无 PUT /{id}/status 映射（只有 GET/POST/PUT/DELETE /{id} 与 POST /calculate）→ 启用/停用加工项恒 404",
        "owner": "processing 域归属包（processing_item_manage ↔ ProcessingItemController 端点对齐）",
        "issue": "#3543",
    },
}

# ── 白名单：存量缺陷工作清单（每条必须带 reason + owner + issue）─────────────
#
# key = (工具文件相对路径, 归一化端点, payload 键)
# 修复归属包改完 payload 后，**必须删除对应条目**（否则 test_allowlist_entries_are_current 红）。
ALLOWLIST: dict[tuple[str, str, str], dict[str, str]] = {
    # ── product 域（issue #3574）───────────────────────────────────────────
    ("app/tools/product_manage.py", "/api/admin/agent/products", "skus"): {
        "reason": "AgentProductCreateRequest 无 skus 字段（SKU 由 colors/doorWidths 等派生）→ 传了也不落库；schema 却声明该参数，反向诱导 LLM 传",
        "owner": "product 域归属包（product_manage schema+payload 对齐）",
        "issue": "#3574",
    },
    ("app/tools/product_search.py", "/api/admin/products", "minPrice"): {
        "reason": "ProductQueryRequest 无 minPrice（就近字段是 stockBelow）→ 价格筛选 100% 无效却返回全量 → 「幻觉式筛选」后 LLM 叙述成已筛出",
        "owner": "product 域归属包（product_search 价格/库存筛选）",
        "issue": "#3574",
    },
    ("app/tools/product_search.py", "/api/admin/products", "maxPrice"): {
        "reason": "同 minPrice：ProductQueryRequest 无 maxPrice → 静默忽略，价格区间筛选恒失效",
        "owner": "product 域归属包（product_search 价格/库存筛选）",
        "issue": "#3574",
    },
    ("app/tools/product_search.py", "/api/admin/products", "stockStatus"): {
        "reason": "ProductQueryRequest 无 stockStatus（就近字段是 stockBelow，语义不同）→ schema 教的 in_stock/low_stock/out_of_stock 词表后端不存在",
        "owner": "product 域归属包（product_search 价格/库存筛选）",
        "issue": "#3574",
    },
    ("app/tools/product_update.py", "/api/admin/agent/products/{}", "status"): {
        "reason": "AgentProductUpdateRequest 无 status 字段（改状态走 agent/products/{id}/status 独立端点）→ 静默丢弃 + message 逐字回显『商品已更新: status』",
        "owner": "product 域归属包（product_update ↔ AgentProductUpdateRequest）",
        "issue": "#3560",
    },
    # ── processing 域（issue #3543）────────────────────────────────────────
    ("app/tools/processing_item_manage.py", "/api/admin/processing-items/{}", "price"): {
        "reason": "ProcessingItemUpdateRequest 字段名是 unitPrice（无 price）→ 改单价 100% 无效，且 data 把 price 原样回显成「已更新」",
        "owner": "processing 域归属包（processing_item_manage 单价字段对齐）",
        "issue": "#3543",
    },
    ("app/tools/processing_item_manage.py", "/api/admin/processing-categories", "description"): {
        "reason": "ProcessingCategoryCreateRequest 只有 name/sortOrder/status（无 description）→ 建分类时 LLM 填的说明被丢弃",
        "owner": "processing 域归属包（加工分类 description 双方对齐）",
        "issue": "#3543",
    },
    ("app/tools/processing_item_manage.py", "/api/admin/processing-categories/{}", "description"): {
        "reason": "ProcessingCategoryUpdateRequest 只有 name/sortOrder/status（无 description）→ 改分类时说明被丢弃",
        "owner": "processing 域归属包（加工分类 description 双方对齐）",
        "issue": "#3543",
    },
    # ── HR / 通知 / 售后域 ────────────────────────────────────────────────
    ("app/tools/employee_manage.py", "/api/admin/users/{}", "phone"): {
        "reason": "PUT /users/{id} 的 @RequestBody Map 只读 name/avatar/role/position/password/permissions（无 phone）→ 改手机号静默失效但 HTTP 200",
        "owner": "HR 域归属包（employee_manage ↔ AdminUserController）",
        "issue": "#3550",
    },
    ("app/tools/employee_manage.py", "/api/admin/users/{}", "roleIds"): {
        "reason": "同 phone：handler 作用域 Map 只读单值 role（无 roleIds）→ 多岗位下发被丢弃（改角色假成功）",
        "owner": "HR 域归属包（employee_manage ↔ AdminUserController）",
        "issue": "#3550",
    },
    ("app/tools/human_handoff.py", "/api/admin/notifications", "recipientRole"): {
        "reason": "CreateNotificationRequest 无 recipientRole（是 recipientId + recipientType，且两者 @NotBlank）→ 通知恒 400 被吞成 warning，转人工通知静默不达",
        "owner": "handoff 域归属包（human_handoff 通知 payload ↔ CreateNotificationRequest）",
        "issue": "#3553",
    },
    ("app/tools/human_handoff.py", "/api/admin/notifications", "type"): {
        "reason": "CreateNotificationRequest 无 type 字段 → 静默丢弃（通知分类信息丢失）",
        "owner": "handoff 域归属包（human_handoff 通知 payload ↔ CreateNotificationRequest）",
        "issue": "#3553",
    },
    ("app/tools/aftersale_query.py", "/api/admin/after-sales", "customerId"): {
        "reason": "AfterSalesController 列表端点只声明 page/size/status/ticketType/keyword（无 customerId）→ 多查全量再本地裁剪，total 与分页语义已错",
        "owner": "aftersales 域归属包（本门禁新发现，待建 issue）",
        "issue": "#3570",
    },
    ("app/tools/after_sales_manage.py", "/api/admin/agent/after-sales", "source"): {
        "reason": "AgentAfterSalesCreateRequest 无 source 字段（本门禁新发现）→ 工单来源标记 'agent' 静默丢弃",
        "owner": "aftersales 域归属包（本门禁新发现，待建 issue）",
        "issue": "#3570",
    },
}
# 本门禁的**已知覆盖面边界**（不在射程内，别误以为已覆盖）：
# ① 「缺失的必填键」：如 human_handoff 通知少发 recipientId/recipientType（#3553）——
#    缺键不是「多发了接收端不读的键」，需必填校验层（validate_input/后端 @NotBlank）兜底；
# ② 「键对但值越界」：如 human_handoff 的 channel="system"（枚举合法值 wechat/sms/email/internal）
#    —— 键 ∈ DTO 字段所以本门禁放行，值域校验属各自 schema enum 与后端 @Pattern 的职责；
# ③ 射程外的 100+ 端点（见 SCOPE_EXPLICIT_PATHS 与 issue #3570 的扩面路径）。


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


def _strip_leading_annotations(sig: str) -> str:
    """剥掉方法签名前的连续方法级注解（含其括号参数），返回从返回类型开始的文本。"""
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
    return s


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


@lru_cache(maxsize=1)
def _java_sources() -> dict[str, str]:
    if not _JAVA_MAIN.is_dir():
        return {}
    return {
        str(p.relative_to(_JAVA_MAIN)): p.read_text(encoding="utf-8")
        for p in _JAVA_MAIN.rglob("*.java")
    }


@lru_cache(maxsize=1)
def _java_endpoints() -> dict[tuple[str, str], tuple[JavaEndpoint, ...]]:
    """解析全部 controller 的端点（verb + 归一化路径 → 端点；同路径多 verb 各自成条）。"""
    out: dict[tuple[str, str], list[JavaEndpoint]] = {}
    srcs = _java_sources()
    for rel, src in srcs.items():
        if "/controller/" not in rel.replace("\\", "/"):
            continue
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
            sig_head = _strip_leading_annotations(sig)
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
                    # 非注解 POJO 形参：Spring 按 query param 绑定到其字段（如 ProductQueryRequest）
                    try:
                        query_fields |= set(_sibling_contract._dto_fields(base_type))
                    except AssertionError:
                        pass
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


def _receiving_keys(ep: JavaEndpoint) -> frozenset[str] | None:
    """接收端「可读键」集合。

    - `@RequestBody Dto/Entity`：DTO 已声明字段（复用既有跨端契约测试的解析器）；
    - `@RequestBody Map`：handler 作用域内 `.get/.getOrDefault/.containsKey` 读到的键；
    - 一律并入 `@RequestParam` / `@PathVariable` / 非注解 POJO 形参（Spring 按 query 绑定）字段。
    返回 None 表示接收类型无法解析（登记表陈旧/解析器需扩面）→ 调用方应显式暴露而非静默跳过。
    """
    keys: set[str] = set(ep.params) | set(ep.path_vars) | set(ep.query_fields)
    if ep.body_var is not None:
        keys |= set(ep.map_reads)
    elif ep.body_type is not None:
        try:
            keys |= set(_sibling_contract._dto_fields(ep.body_type))
        except AssertionError:
            return None
    return frozenset(keys)


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


def _resolve_payload_expr(
    expr: ast.AST, func_node: ast.AST, before_line: int
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """解析 payload 表达式 → (静态键, 动态点)。

    `before_line` 之前的同名赋值 / `name["k"]=v` / `name.update(...)` 全部计入
    （只看调用点**之前**的语句，避免审计脚本「整函数作用域收键」导致的串扰假阳性）。
    """
    if isinstance(expr, ast.Dict):
        return _dict_keys(expr)
    if isinstance(expr, ast.Name):
        return _resolve_named(expr.id, func_node, before_line)
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "dict":
        keys = [
            (kw.arg, kw.lineno)
            for kw in expr.keywords
            if kw.arg
        ]
        return keys, [] if keys else [("<dict() 动态>", expr.lineno)]
    return [], [(ast.unparse(expr)[:40], getattr(expr, "lineno", 0))]


def _resolve_named(
    name: str, func_node: ast.AST, before_line: int, _seen: frozenset[str] = frozenset()
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
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
                        k, d = _resolve_named(node.value.id, func_node, node.lineno, _seen)
                        keys += k
                        dyn += d
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
def _tool_calls() -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        rel = f"app/tools/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
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
                    k, d = _resolve_payload_expr(kw.value, scope, node.lineno)
                    keys += k
                    dyn += d
                elif kw.arg is not None and kw.arg not in ("tenant_id", "user_id", "timeout"):
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


@lru_cache(maxsize=1)
def _template_regexes() -> dict[tuple[str, str], re.Pattern[str]]:
    """端点模板 → 具体路径的正则（`{}` 匹配任意单段），用于匹配带真实 id 的调用点。"""
    return {
        key: re.compile("^" + re.escape(p).replace(re.escape("{}"), "[^/]+") + "$")
        for key, p in ((k, k[1]) for k in _java_endpoints())
    }


def _lookup_endpoints(verb: str, path: str) -> tuple[JavaEndpoint, ...]:
    """按 (verb, 归一化路径) 查端点；归一化模板不匹配时按「具体 id ↔ 路径变量」正则回退。"""
    exact = _java_endpoints().get((verb, _norm_path(path)))
    if exact:
        return exact
    hits: list[JavaEndpoint] = []
    for (v, _p), rx in _template_regexes().items():
        if v == verb and rx.match(_norm_path(path)):
            hits.extend(_java_endpoints()[(v, _p)])
    return tuple(hits)


def _in_scope(endpoint: str) -> bool:
    if endpoint.startswith(AGENT_ENDPOINT_PREFIXES):
        return True
    return endpoint in {_norm_path(p) for p in SCOPE_EXPLICIT_PATHS}


def _scoped_calls() -> tuple[ToolCall, ...]:
    return tuple(c for c in _tool_calls() if c.payload_kwarg and _in_scope(c.endpoint))


def _resolve_endpoint(call: ToolCall) -> JavaEndpoint | None:
    eps = _lookup_endpoints(call.method, call.endpoint)
    return eps[0] if len(eps) == 1 else None


def _violations() -> list[tuple[ToolCall, JavaEndpoint, list[str]]]:
    """射程内、静态键完整、且键 ∈ 接收端可读键 不成立 → 违规清单。"""
    out = []
    for call in _scoped_calls():
        ep = _resolve_endpoint(call)
        if ep is None:
            continue
        readable = _receiving_keys(ep)
        if readable is None:
            continue
        bad = sorted(k for k in call.key_set if k not in readable)
        if bad:
            out.append((call, ep, bad))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 三、门禁断言
# ══════════════════════════════════════════════════════════════════════════


def test_scanner_sees_the_scope() -> None:
    """扫描器自检：射程内必须有调用点，且端点能在 Java 源码里解析出来。

    防「扫描器静默退化」——正则失配 / 路径口径漂移会让后面所有断言变成空转绿。
    """
    calls = _scoped_calls()
    assert len(calls) >= 8, (
        f"射程内只扫到 {len(calls)} 个 payload 调用点（预期 ≥8）——"
        f"扫描器或 SCOPE 配置已失效，禁止以空转绿收场"
    )
    unresolved = sorted(
        f"{c.file}:{c.line} {c.method} {c.endpoint}"
        for c in calls
        if _resolve_endpoint(c) is None
    )
    assert not unresolved, (
        "射程内调用点无法在 admin-api controller 源码里解析到端点（路径口径漂移？）：\n  "
        + "\n  ".join(unresolved)
    )
    no_body = sorted(
        {
            f"{c.method} {c.endpoint}（{_resolve_endpoint(c).controller}）"
            for c in calls
            if _resolve_endpoint(c) is not None
            and _receiving_keys(_resolve_endpoint(c)) is None
        }
    )
    assert not no_body, (
        "接收端类型无法解析（DTO 改名/移包 → 请同步扩面解析器）：\n  " + "\n  ".join(no_body)
    )


def test_payload_keys_are_readable_by_receiver() -> None:
    """核心门禁：射程内 payload 键 ⊆ 接收端可读键。

    未登记的新键 → 红（**允许存量收敛，不允许新增**）。
    存量缺陷修好后白名单条目会变陈旧 → 由 test_allowlist_entries_are_current 逼销账。
    """
    failures = []
    for call, ep, bad in _violations():
        unregistered = [
            k for k in bad if (call.file, call.endpoint, k) not in ALLOWLIST
        ]
        if not unregistered:
            continue
        readable = sorted(_receiving_keys(ep) or ())
        failures.append(
            f"\n  {call.file}:{call.line} → {call.method} {call.endpoint}"
            f"\n      接收类型: {ep.body_type or f'Map body ({ep.body_var})'}"
            f"（{ep.controller}:{ep.line}）"
            f"\n      未登记的不一致键: {unregistered}"
            f"\n      接收端可读键: {readable}"
        )
    assert not failures, (
        "❌ 工具下发的 payload 键在接收端读不到（Spring/Map 静默丢弃 → HTTP 200 假成功）："
        + "".join(failures)
        + "\n\n修复二选一：①工具 payload 改用接收端真实字段名；②接收端补字段。"
        "\n确认是存量欠账（归属别的包）→ 在 ALLOWLIST 登记 reason+owner+issue。"
        "\n禁止把『接收端不读的键』留在 payload 里凑数（详见 issue #3570）。"
    )


def _registry_problems(registry: dict, label: str) -> list[str]:
    """登记表纪律：每条必须带 reason + owner + issue（防白名单变成垃圾场）。"""
    problems = []
    for key, meta in sorted(registry.items(), key=lambda kv: str(kv[0])):
        for field in ("reason", "owner", "issue"):
            if not str(meta.get(field, "")).strip():
                problems.append(f"[{label}] {key}: 缺 {field}")
        if len(str(meta.get("reason", "")).strip()) < 10:
            problems.append(f"[{label}] {key}: reason 过于笼统（<10 字）")
        if not str(meta.get("issue", "")).startswith("#"):
            problems.append(f"[{label}] {key}: issue 必须写成 #<编号> 形式（当前 {meta.get('issue')!r}）")
    return problems


def test_registry_entries_are_complete() -> None:
    """登记表纪律：ALLOWLIST 与 ENDPOINT_ALLOWLIST 每条必须带 reason + owner + issue。"""
    problems = _registry_problems(ALLOWLIST, "ALLOWLIST") + _registry_problems(
        ENDPOINT_ALLOWLIST, "ENDPOINT_ALLOWLIST"
    )
    assert not problems, "❌ 登记表条目不完整：\n  " + "\n  ".join(problems)


def test_allowlist_entries_are_current() -> None:
    """白名单即工作清单：条目对应缺陷一旦修好（键不再下发/被丢弃），条目必须删除。

    「陈旧条目」= 该 (文件, 端点, 键) 现在已不在违规集里。
    若调用点含动态构造（静态扫不全），保守跳过该条目的陈旧判定。
    """
    live = {
        (call.file, call.endpoint, k)
        for call, _ep, bad in _violations()
        for k in bad
    }
    dynamic_sites = {(c.file, c.endpoint) for c in _scoped_calls() if c.dynamic}
    stale = sorted(
        k for k in ALLOWLIST
        if k not in live and (k[0], k[1]) not in dynamic_sites
    )
    assert not stale, (
        "🎉 下列白名单条目已不再命中（缺陷已修复）→ **请直接从 ALLOWLIST 删除这些条目**，"
        "让工作清单逐条销账（issue #3570）：\n  "
        + "\n  ".join(f"{f} → {p} 键 {k!r}" for f, p, k in stale)
    )


def test_explicit_scope_endpoints_exist() -> None:
    """显式登记端点必须真实存在（防登记表陈旧 → 静默不再覆盖）。"""
    known = set(_java_endpoints())
    known_paths = {p for _v, p in known}
    missing = sorted(p for p in (_norm_path(x) for x in SCOPE_EXPLICIT_PATHS) if p not in known_paths)
    assert not missing, (
        "❌ SCOPE_EXPLICIT_PATHS 登记了 admin-api 不存在的端点（改名/删除？）：\n  "
        + "\n  ".join(missing)
    )


def test_tool_call_endpoints_exist() -> None:
    """工具调用的 admin-api 端点必须真实存在（404 类跨模块契约缺陷）。

    与 payload 键同族的静默失效：路径写错 → 后端 404 → 工具把失败当普通错误吞掉。
    存量未修条目在 ENDPOINT_ALLOWLIST 登记（reason+owner+issue），修好即删（同白名单纪律）。
    """
    missing = sorted(
        (c.file, c.method, c.endpoint)
        for c in _tool_calls()
        if len(_lookup_endpoints(c.method, c.endpoint)) != 1
        and (c.file, c.method, c.endpoint) not in ENDPOINT_ALLOWLIST
    )
    assert not missing, (
        "❌ 下列工具调用指向 admin-api 不存在的端点（404，且不会被任何契约测试发现）：\n  "
        + "\n  ".join(f"{f}: {m} {p}" for f, m, p in missing)
        + "\n\n修复二选一：①改用后端真实端点；②后端补该端点。"
        "\n确认为存量欠账 → 在 ENDPOINT_ALLOWLIST 登记 reason+owner+issue。"
    )


def test_endpoint_allowlist_entries_are_current() -> None:
    """端点白名单销账：条目对应缺陷修好后必须删除。"""
    live = {
        (c.file, c.method, c.endpoint)
        for c in _tool_calls()
        if len(_lookup_endpoints(c.method, c.endpoint)) != 1
    }
    stale = sorted(k for k in ENDPOINT_ALLOWLIST if k not in live)
    assert not stale, (
        "🎉 下列端点白名单条目已不再命中（端点已对齐）→ **请从 ENDPOINT_ALLOWLIST 删除**：\n  "
        + "\n  ".join(f"{f}: {m} {p}" for f, m, p in stale)
    )


def test_dynamic_payload_sites_are_registered() -> None:
    """静态扫不到 payload 键的调用点必须显式登记理由（防「藏在动态构造后面」躲开门禁）。"""
    unregistered = sorted(
        f"{c.file}:{c.line} {c.method} {c.endpoint} → {[d[0] for d in c.dynamic]}"
        for c in _scoped_calls()
        if c.dynamic and f"{c.file}:{c.line}" not in DYNAMIC_KEY_SITES
    )
    assert not unregistered, (
        "❌ 下列射程内调用点的 payload 键无法静态解析，且未在 DYNAMIC_KEY_SITES 登记理由\n"
        "（动态构造会让本门禁静默失效 → 必须登记或改成静态可解析）：\n  "
        + "\n  ".join(unregistered)
    )


def test_unknown_payload_kwarg_names() -> None:
    """payload 只能走 client 支持的形态（json_data / params / data）。

    `json=`（httpx 风格）在自研 `AdminApiClient` 上必然 TypeError（issue #3548 曾恒失败）。
    """
    allowed = set(PAYLOAD_KWARGS) | {"tenant_id", "user_id", "timeout"}
    bad = []
    for call in _tool_calls():
        if not _in_scope(call.endpoint):
            continue
        for expr, _line in call.dynamic:
            if expr.startswith("未知 kwarg "):
                bad.append(f"{call.file}:{call.line} {call.method} {call.endpoint} → {expr}")
    assert not bad, (
        "❌ payload 传参形态不被 AdminApiClient 支持（会 TypeError）：\n  " + "\n  ".join(bad)
    )
    assert "json_data" in allowed  # 形参名单的单一事实源


def test_sibling_contract_registry_agrees_with_scanner() -> None:
    """与既有运行期契约测试（test_tool_field_name_contract.py）口径互锁。

    该测试的 REGISTRY 逐条登记「工具 → 端点 → DTO 类」；本测试用同一份 Java 解析器
    独立解析同端点，断言 DTO 类一致。两者口径漂移 → 这里红（防两套门禁各说各话）。
    """
    problems = []
    for contract in _sibling_contract.REGISTRY:
        ep = _lookup_endpoints(contract.client_method.upper(), contract.endpoint)
        if not ep:
            problems.append(
                f"{contract.tool_module} 登记端点 {contract.client_method.upper()} "
                f"{contract.endpoint} 在 admin-api controller 里不存在"
            )
            continue
        actual = {e.body_type for e in ep if e.body_type}
        if actual and contract.dto_class not in actual:
            problems.append(
                f"{contract.endpoint} 的 @RequestBody 实为 {sorted(actual)}，"
                f"但 test_tool_field_name_contract.REGISTRY 登记的是 {contract.dto_class}"
            )
    assert not problems, (
        "❌ 本门禁与 test_tool_field_name_contract.REGISTRY 口径漂移：\n  " + "\n  ".join(problems)
    )


def test_payload_calls_are_attributable_to_an_endpoint() -> None:
    """带 payload 的 admin-api 调用点必须能静态归属到某个端点路径。

    路径若完全无法渲染（如 `client.post(some_var, json_data=...)`），该调用点会从
    射程里**静默消失** —— 这正是本门禁最危险的失效方式。无法归属即红，必须改写成
    静态可读的路径字面量/f-string（或在 `UNATTRIBUTABLE_CALLS` 显式登记理由）。

    只约束 admin-api 客户端（`get_admin_api_client()` 的返回值）：工具里还有第三方
    HTTP 客户端（如 `httpx` + `settings.LOGISTICS_API_URL`），不在跨模块契约射程内。
    """
    unattributed = []
    for path in sorted(_TOOLS_DIR.glob("*.py")):
        rel = f"app/tools/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in _CLIENT_METHODS or not node.args:
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            enclosing = [
                f
                for f in ast.walk(tree)
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                and f.lineno <= node.lineno <= f.end_lineno
            ]
            if not enclosing:
                continue
            scope = min(enclosing, key=lambda f: f.end_lineno - f.lineno)
            if node.func.value.id not in _admin_client_names(scope):
                continue
            has_payload = any(kw.arg in PAYLOAD_KWARGS for kw in node.keywords)
            if not has_payload:
                continue
            rendered = _path_template(node.args[0])
            if rendered and rendered.startswith("/api"):
                continue
            site = f"{rel}:{node.lineno}"
            if site in UNATTRIBUTABLE_CALLS:
                continue
            unattributed.append(
                f"{site} {node.func.attr.upper()} 路径={ast.unparse(node.args[0])[:60]}"
            )
    assert not unattributed, (
        "❌ 带 payload 的 admin-api 调用点无法静态归属到端点（会静默脱离本门禁射程）：\n  "
        + "\n  ".join(sorted(unattributed))
    )


def _admin_client_names(scope: ast.AST) -> set[str]:
    """作用域内由 `get_admin_api_client()` 赋值的变量名。"""
    names: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "get_admin_api_client"
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                names.add(tgt.id)
    return names


def test_allowlist_entries_are_in_scope() -> None:
    """白名单条目必须落在当前射程内（否则条目永远不会被判定为陈旧 → 静默腐烂）。"""
    scoped = {(c.file, c.endpoint) for c in _scoped_calls()}
    orphan = sorted(
        f"{f} → {p} 键 {k!r}" for (f, p, k) in ALLOWLIST if (f, p) not in scoped
    )
    assert not orphan, (
        "❌ 下列白名单条目不在射程内（SCOPE_EXPLICIT_PATHS 尚未登记该端点 / 调用点已移除）：\n  "
        + "\n  ".join(orphan)
    )


if __name__ == "__main__":  # pragma: no cover - 开发期报告模式
    import sys

    if "--report" not in sys.argv:
        raise SystemExit("用法: python -m tests.test_tool_payload_backend_contract --report")
    print(f"扫描到 payload 调用点 {len(_tool_calls())} 个，射程内 {len(_scoped_calls())} 个\n")
    for call in _scoped_calls():
        ep = _resolve_endpoint(call)
        readable = _receiving_keys(ep) if ep else None
        bad = sorted(k for k in call.key_set if readable is not None and k not in readable)
        flag = "❌" if bad else "✅"
        print(
            f"{flag} {call.file}:{call.line} {call.method} {call.endpoint} "
            f"[{call.payload_kwarg}] keys={sorted(call.key_set)} bad={bad}"
            + (f" dyn={[d[0] for d in call.dynamic]}" if call.dynamic else "")
        )
    print("\n── 射程外但可解析的调用点（扩面候选）──")
    outside = [c for c in _tool_calls() if c.payload_kwarg and not _in_scope(c.endpoint)]
    print(f"共 {len(outside)} 个；涉及端点 {len({c.endpoint for c in outside})} 个")
    for ep in sorted({c.endpoint for c in outside}):
        print("   ", ep)
