# case_ids: CH-001, DF-011, DF-012
"""admin-api 失败响应 → ToolResult 的**单一映射点** + 授权失败不得被降级成「稍后重试」（issue #4106 F6）。

## 病灶形状

`app/utils/http_client.py` 已经把 4xx 响应体**整份透传**
（`{**result, "success": False, "data": None, "error": result.get("error", {})}`）——
服务端的 `error.code` / `error.message` / 顶层 `suggestion` 都完好到手。

但 `app/tools/*.py` 里：

- 38 个文件中只有 **1 个**读 `response["suggestion"]`（`product_manage.py`）；
- 只有 **2 个**读 `error.code`，且只比 `NOT_FOUND`；字面量 `PERMISSION_DENIED` 在 `app/` 里出现 **0 次**；
- ~100 个 `if not response.get("success"):` 分支里 **36 处**把服务端的修复建议
  覆盖成不可执行的套话（「请稍后重试，如持续失败请联系技术支持」/「请检查参数格式后重试」）；
- `error.code` 从未到达 `ToolResult`。

后果：**授权失败被当成参数问题**。模型收到「请稍后重试」⇒ 反复重试同一调用；
用户被告知「稍后重试」而不是「你的账号没有这个权限、去哪里开通」——F6 要治的就是这条。

## 本文件锁的不变式

1. `TestAuthorizationFailureIsExecutable` —— 授权类失败（`NON_RETRYABLE_ERROR_CODES`）
   必须产生**可执行**的 suggestion：说明这是权限限制、**不要重试**、指向管理后台的授权路径，
   并尽量带上服务端给的 `requiredPermission`；
2. `TestNonAuthorizationFailureKeepsServiceGuidance` —— 其它失败：服务端的 `suggestion`
   / `message` 非空时**优先保留**，只有都没有时才落到调用方给的默认文案；
3. `TestErrorCodeContract` —— `ToolResult.error_code` 存在且被赋值；
   `NON_RETRYABLE_ERROR_CODES` 是**跨包契约**（另一个包 `from app.tools.base import …`
   用它停止重试），名字与成员都必须稳定；
4. `TestNoAdminApiFailureBranchBypassesTheMapper` —— **L0 静态锁**：`app/tools/*.py` 里
   每个 admin-api 失败分支的返回都必须走共享映射点，否则授权失败又会被就地降级；
   **分母口径**（#4149 G4）不取自检测器自己：凡提到 `.get("success")` 的 `if` 判据都必须在
   失败支/成功支里归得了类，每一处 `.get("success")` 读取都必须在判据认识的决策上下文里
   —— 认不出的形态一律报出（`Or` 形态当年就是这么漏掉两个降级分支的）；
5. 判据自身**可红 + 不恒真**（`TestMapperGuardIsNotVacuous`：注入式夹具必报、合法形态必不报，
   含 #4149 G4 新形态 `Or` 组合 + 「认不出的形态」两条盲区红证）。

## 授权码集合的核定口径（不猜）

admin-api 能产出的授权/认证类字面量（逐个有出处）：

| 码 | 出处 | HTTP |
|---|---|---|
| `PERMISSION_DENIED` | `GlobalExceptionHandler.java` 第 117 行 / `BusinessException.java` 第 109 行 | 403 |
| `FORBIDDEN` | `SecurityConfig.java` 第 179 行（裸 JSON 直写） | 403 |
| `AUTH_REQUIRED` | `GlobalExceptionHandler.java` 第 98 行（`AuthenticationException`） | 401 |
| `AUTH_FAILED` | `BusinessException.java` 第 102 行 | 401 |
| `UNAUTHORIZED` | `SecurityConfig.java` 第 172 行（entry point 裸 JSON）/ `UserController.java` 第 63 行 | 401 |

`TENANT_INVALID`（`BusinessException.java` 第 116 行，401）**刻意不收**：它是租户配置问题，
不是「当前账号缺权限」，交给调用方的默认文案更诚实（登记在此，不是漏判）。

## 明确不在本守卫范围内

- `except Exception` 兜底分支：没有 admin-api 响应可映射，套话在这里是**恰当**的
  （不允许它把授权失败降级 —— 授权失败根本不会走异常分支，4xx 由 `_do_call` 直接返回）。
- 参数校验失败（`if not name:` 之类）：与 admin-api 无关，保持原样。
- `_execute_tool_safe` 出口 JSON 里的 `code` 键：由 `app/graph/**` 拥有，本包不改
  （本包只保证 `ToolResult.error_code` 被赋值 —— 那是另一个包的消费契约）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.skills.base_skill import _execute_tool_safe, _self_correct_retry
from app.tools.base import (
    NON_RETRYABLE_ERROR_CODES,
    ToolContext,
    ToolResult,
    admin_api_failure,
)
from app.tools.piecework_query import PieceworkQueryTool
from app.tools.production_progress_query import ProductionProgressQueryTool

SERVICE_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = SERVICE_DIR / "app" / "tools"

MAPPER_NAME = "admin_api_failure"

#: 授权/认证类码（跨包契约的一部分，见文件头表格）
EXPECTED_NON_RETRYABLE = frozenset({
    "PERMISSION_DENIED", "FORBIDDEN", "AUTH_REQUIRED", "AUTH_FAILED", "UNAUTHORIZED",
})

#: F6 点名的套话（授权失败落到这些文案上 = 让模型去重试）
RETRY_BOILERPLATE = (
    "请稍后重试，如持续失败请联系技术支持",
    "请检查参数格式后重试",
)


def _denial_response(**overrides) -> dict:
    """一份最小可用的 admin-api 403 响应（形状对齐 `ApiResponse` + `ErrorInfo`）。"""
    payload = {
        "success": False,
        "data": None,
        "error": {"code": "PERMISSION_DENIED", "message": "权限不足"},
        "requestId": "req_test",
        "timestamp": 1758000000,
    }
    payload.update(overrides)
    return payload


def _ok_call(result: ToolResult) -> bool:
    return result.success is False


# ──────────────────────────────────────────────────────────────────────────────
# ① 授权失败必须是可执行的
# ──────────────────────────────────────────────────────────────────────────────

class TestAuthorizationFailureIsExecutable:
    """授权类失败 ⇒ 说明「这是权限限制、不要重试、去哪开通」，绝不落套话。"""

    @pytest.mark.parametrize("code", sorted(EXPECTED_NON_RETRYABLE))
    def test_authorization_codes_are_mapped_as_non_retryable(self, code):
        assert code in NON_RETRYABLE_ERROR_CODES, f"{code} 是授权类码，必须在不可重试集合里"

    @pytest.mark.parametrize("code", sorted(EXPECTED_NON_RETRYABLE))
    def test_authorization_failure_yields_an_executable_suggestion(self, code):
        result = admin_api_failure(
            _denial_response(error={"code": code, "message": "权限不足"}),
            error="权限不足",
            message="查询失败：权限不足",
            suggestion="请稍后重试，如持续失败请联系技术支持",  # ← 调用方的套话必须被顶掉
        )
        text = result.suggestion or ""
        assert _ok_call(result)
        assert "权限" in text, f"{code}: 必须点明这是权限限制（实际：{text!r}）"
        assert "不要重试" in text, f"{code}: 必须明确禁止重试（实际：{text!r}）"
        assert "管理员" in text, f"{code}: 必须指向管理后台的授权路径（实际：{text!r}）"
        for boiler in RETRY_BOILERPLATE:
            assert boiler not in text, f"{code}: 授权失败不得落重试套话（{boiler!r}）"

    def test_service_required_permission_is_preserved(self):
        """服务端若能给出缺哪个码 ⇒ 必须带进建议（当前 admin-api 只在 message 里带）。"""
        result = admin_api_failure(
            _denial_response(error={
                "code": "PERMISSION_DENIED",
                "message": "权限不足",
                "requiredPermission": "product:category",
            }),
            message="分类管理失败",
        )
        assert "product:category" in (result.suggestion or ""), (
            "服务端给出的 requiredPermission 必须保留在建议里"
        )

    def test_required_permission_in_top_level_field_is_preserved(self):
        """`http_client` 会把顶层字段一起透传 ⇒ 顶层 `requiredPermission` 同样要认。"""
        result = admin_api_failure(
            _denial_response(requiredPermission="system:manage"), message="角色管理失败",
        )
        assert "system:manage" in (result.suggestion or "")

    def test_required_permission_in_error_details_is_preserved(self):
        """**admin-api 现状真值**（#4105/#4112）：结构化载体是
        `error.details[{"field": "requiredPermission", "message": "<code>"}]`
        （`PermissionDeniedResponse.of()`）。工具层必须读它，否则「缺哪个码」这一路白给。
        """
        result = admin_api_failure(
            _denial_response(error={
                "code": "PERMISSION_DENIED",
                "message": "权限不足，需要权限: product:category",
                "details": [{"field": "requiredPermission", "message": "product:category"}],
            }),
            message="分类管理失败",
        )
        assert "product:category" in (result.suggestion or ""), (
            "error.details 里的 requiredPermission 必须被提取并保留"
        )

    def test_required_permission_details_without_a_code_is_tolerated(self):
        """`details` 里没有该条（路径级拒绝传 null）⇒ 仍给可执行建议，不得崩。"""
        result = admin_api_failure(
            _denial_response(error={
                "code": "PERMISSION_DENIED",
                "message": "权限不足",
                "details": [{"field": "other", "message": "x"}],
            }),
        )
        text = result.suggestion or ""
        assert "权限" in text and "不要重试" in text, "拿不到码也要可执行"

    def test_required_permission_in_the_message_text_is_preserved(self):
        """现状真值：`PermissionInterceptor` 把码拼进异常 message（`需要权限: <code>`）。"""
        result = admin_api_failure(
            _denial_response(error={
                "code": "PERMISSION_DENIED",
                "message": "权限不足，需要权限: processing:manage",
            }),
        )
        assert "processing:manage" in (result.suggestion or ""), (
            "服务端 message 里的 `需要权限: <code>` 必须被提取并保留"
        )

    def test_missing_required_permission_still_yields_executable_guidance(self):
        """拿不到具体码时也要可执行（不能因为缺字段就退回套话）。"""
        result = admin_api_failure(_denial_response(), suggestion="请稍后重试")
        text = result.suggestion or ""
        assert "权限" in text and "管理员" in text
        for boiler in RETRY_BOILERPLATE:
            assert boiler not in text


# ──────────────────────────────────────────────────────────────────────────────
# ② 其它失败：服务端的引导优先，调用方默认只是兜底
# ──────────────────────────────────────────────────────────────────────────────

class TestNonAuthorizationFailureKeepsServiceGuidance:
    """非授权失败：服务端 `suggestion` / `message` 非空 ⇒ 保留；否则才用调用方默认。"""

    def test_service_suggestion_wins_over_the_callers_default(self):
        result = admin_api_failure(
            {
                "success": False,
                "error": {"code": "NOT_FOUND", "message": "商品不存在"},
                "suggestion": "请检查 ID 是否正确。如果使用了商品名称，请先用 product_search 查出 UUID 后重试",
            },
            error="商品不存在",
            message="查询商品失败：商品不存在",
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
        assert result.suggestion == (
            "请检查 ID 是否正确。如果使用了商品名称，请先用 product_search 查出 UUID 后重试"
        ), "服务端给了修复建议时，不得用调用方的套话覆盖它"

    def test_caller_default_is_the_fallback_when_service_gives_nothing(self):
        result = admin_api_failure(
            {"success": False, "error": {"code": "INTERNAL_ERROR", "message": "服务开小差"}},
            error="服务开小差",
            message="查询失败：服务开小差",
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
        assert result.suggestion == "请稍后重试，如持续失败请联系技术支持"
        assert result.message == "查询失败：服务开小差", "调用方给出的用户可见文案必须原样保留"

    def test_service_message_fills_in_when_caller_passes_none(self):
        result = admin_api_failure(
            {"success": False, "error": {"code": "NOT_FOUND", "message": "工单不存在"}},
        )
        assert result.message == "工单不存在", "调用方没给 message 时必须用服务端的 message"
        assert result.error == "工单不存在", "error 字段同样回落到服务端 message"

    def test_blank_service_suggestion_is_treated_as_absent(self):
        """空串 / 纯空白 ≠ 建议（否则模型收到空引导＝静默失效）。"""
        for blank in ("", "   "):
            result = admin_api_failure(
                {"success": False, "error": {"code": "NOT_FOUND", "message": "x"},
                 "suggestion": blank},
                suggestion="请改用 product_search 按名称查询后重试",
            )
            assert result.suggestion == "请改用 product_search 按名称查询后重试"

    def test_authorization_with_blank_service_suggestion_still_maps(self):
        """授权失败即使服务端 suggestion 为空，也必须走可执行分支（不得落到调用方套话）。"""
        result = admin_api_failure(
            _denial_response(suggestion=""), suggestion="请稍后重试，如持续失败请联系技术支持",
        )
        assert "不要重试" in (result.suggestion or "")


# ──────────────────────────────────────────────────────────────────────────────
# ③ 跨包契约：error_code 字段 + 常量名
# ──────────────────────────────────────────────────────────────────────────────

class TestErrorCodeContract:
    """`ToolResult.error_code` 与 `NON_RETRYABLE_ERROR_CODES` 是另一个包消费的契约。"""

    def test_non_retryable_codes_is_a_frozenset_with_the_reviewed_members(self):
        assert isinstance(NON_RETRYABLE_ERROR_CODES, frozenset), (
            "必须是 frozenset（跨包契约里按 `code in NON_RETRYABLE_ERROR_CODES` 使用）"
        )
        assert NON_RETRYABLE_ERROR_CODES == EXPECTED_NON_RETRYABLE, (
            "不可重试集合变了 ⇒ 另一个包的重试抑制行为随之变化，必须同步评审"
        )

    def test_tool_result_carries_the_error_code(self):
        result = admin_api_failure(_denial_response())
        assert result.error_code == "PERMISSION_DENIED", "error_code 必须带上服务端的错误码"

    def test_non_authorization_codes_are_also_carried(self):
        result = admin_api_failure(
            {"success": False, "error": {"code": "NOT_FOUND", "message": "商品不存在"}},
        )
        assert result.error_code == "NOT_FOUND", "非授权码同样要落进 error_code（供上层诊断）"

    def test_absent_error_code_is_empty(self):
        result = admin_api_failure({"success": False, "error": {}, "message": "无码失败"})
        assert (result.error_code or "") == "", "服务端没给码时不得臆造（保持空）"

    def test_error_code_defaults_to_empty_on_a_plain_result(self):
        assert (ToolResult(success=True).error_code or "") == "", (
            "error_code 必须是**向后兼容的新增字段**（缺省为空，不影响既有构造调用）"
        )

    def test_error_code_survives_model_side_reads(self):
        """消费方按属性取值（`getattr(result, "error_code", None)`）—— 字段必须真的在模型上。"""
        result = admin_api_failure(_denial_response())
        assert getattr(result, "error_code", "") == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────────────
# ④ L0 静态锁：admin-api 失败分支不得绕过映射点
# ──────────────────────────────────────────────────────────────────────────────

def _success_get_call(node: ast.AST) -> bool:
    """`<expr>.get("success")` 形态。"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "success"
    )


def _mentions_success(node: ast.AST) -> bool:
    """表达式里是否出现 `.get("success")` 读取 —— **任意用法**，与判据形态无关。"""
    return any(_success_get_call(n) for n in ast.walk(node))


def _success_predicate(node: ast.AST) -> bool:
    """`X.get("success")` 被**正向**判成功：裸真值 / `is True` / `== True`（含布尔组合）。"""
    if _success_get_call(node):
        return True
    if (isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Is, ast.Eq))):
        truthy = any(isinstance(c, ast.Constant) and c.value is True for c in node.comparators)
        if truthy and (_success_get_call(node.left)
                       or (bool(node.comparators) and _success_get_call(node.comparators[0]))):
            return True
    if isinstance(node, ast.BoolOp):
        return any(_success_predicate(v) for v in node.values)
    return False


def _is_response_failure_test(test: ast.AST) -> bool:
    """admin-api 失败分支的形态判据（四种，同一含义「这次调用没成功」）。

    ① `not X.get("success")`
    ② `X.get("success") is False` / `== False`
    ③ 成功判据**取反**：`not (… X.get("success") …)`（含 `not (A and B)` 形态）
    ④ 上述任一项作为 `or` / `and` 的操作数
       —— `if not isinstance(response, dict) or not response.get("success"):`

    ③④ 由 **#4149 G4** 补入：旧判据只认 ①②，于是 ④ 形态的分支**既没被迁移、也没被计数**
    —— 授权失败在那里被就地降级成「请稍后重试」，而本文件全绿（看不见的形态报告不出来）。
    """
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _mentions_success(test.operand)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op = test.ops[0]
        is_false = any(
            isinstance(c, ast.Constant) and c.value is False for c in test.comparators
        )
        if is_false and (isinstance(op, (ast.Is, ast.Eq))):
            return _success_get_call(test.left) or (
                bool(test.comparators) and _success_get_call(test.comparators[0])
            )
    if isinstance(test, ast.BoolOp):
        return any(_is_response_failure_test(v) for v in test.values)
    return False


def _is_success_path_test(test: ast.AST) -> bool:
    """**成功路径**判据：`X.get("success")` 被正向当条件用（裸真值 / `is True`）。

    只认正向形态；认不出的用法（如 `X.get("success") == 1`）会落进
    `unclassified_success_tests()` 被报出 —— 判据看不见的形态不得静默存在。
    """
    return _success_predicate(test)


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def response_failure_branches(tree: ast.AST) -> list[tuple[int, list[str]]]:
    """每个 admin-api 失败分支 → (分支行号, 该分支里所有 return 的被调函数名)。"""
    found: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_response_failure_test(node.test):
            continue
        names: list[str] = []
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call):
                names.append(_callee_name(stmt.value))
        found.setdefault(node.lineno, []).extend(names)
    return sorted(found.items())


def mapped_failure_returns(tree: ast.AST) -> int:
    """走共享映射点的失败分支返回数（守卫「不得空转」的分母）。"""
    return sum(
        names.count(MAPPER_NAME) for _, names in response_failure_branches(tree)
    )


def unmapped_failure_sites(source: str) -> list[str]:
    """返回**没有走共享映射点**的 admin-api 失败分支，形如 `"文件:行号"`（升序）。

    只判 `if not X.get("success"):` 这类**有 admin-api 响应可映射**的分支：
    `except Exception` 兜底与参数校验分支不在适用域（见文件头「明确不在本守卫范围内」）。
    """
    tree = ast.parse(source)
    bad: list[str] = []
    for lineno, names in response_failure_branches(tree):
        for name in names:
            if name != MAPPER_NAME:
                bad.append(f"{lineno}:{name}")
    return sorted(bad)


def success_mention_tests(tree: ast.AST) -> list[ast.If]:
    """**与检测器无关**地数：所有提到 `.get("success")` 的 `if` 判据（分母的真值源）。"""
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If) and _mentions_success(node.test)
    ]


def unclassified_success_tests(tree: ast.AST) -> list[str]:
    """提到 `.get("success")` 却**判据认不出**的 `if` 判据 → `"行号:源码"`（升序）。

    这是分母口径的另一半（#4149 G4）：`mapped_failure_returns` 只数**检测器看得见**的分支，
    于是新形态（`Or` 形态就是这么漏的）在计数里**根本不存在** —— 看不见的形态报告不出来。
    这里的分子分母都取自**源码真值**：凡提到 `success` 的判据都必须归到失败支或成功支，
    归不进即报出（fail-closed）。
    """
    return sorted(
        f"{node.lineno}:{ast.unparse(node.test)[:80]}"
        for node in success_mention_tests(tree)
        if not _is_response_failure_test(node.test) and not _is_success_path_test(node.test)
    )


def unaccounted_success_reads(tree: ast.AST) -> list[str]:
    """**每一个** `.get("success")` 读取都必须落进判据认识的决策上下文 → 漏掉的读取行号。

    认识的上下文三种：① 被归类的 `if` 判据；② 三元条件（`IfExp`）；③ 推导式过滤
    （`comprehension.ifs`）。落在别处（如先 `ok = x.get("success")` 再拿 `ok` 判）⇒ 报出：
    **判据看不见的读取 = 报告不出的缺口**（与 `Or` 形态漏检同族）。
    """
    accounted: set[int] = set()

    def _collect(node: ast.AST) -> None:
        accounted.update(id(n) for n in ast.walk(node) if _success_get_call(n))

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and (
                _is_response_failure_test(node.test) or _is_success_path_test(node.test)):
            _collect(node.test)
        elif isinstance(node, ast.IfExp):
            _collect(node.test)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in node.generators:
                for cond in generator.ifs:
                    _collect(cond)
    return sorted(
        str(node.lineno) for node in ast.walk(tree)
        if _success_get_call(node) and id(node) not in accounted
    )


def tool_source_files() -> list[Path]:
    """本体源码清单（`app/tools/*.py`）—— 不递归、不扫 `tests/**`。"""
    return sorted(TOOLS_DIR.glob("*.py"))


class TestNoAdminApiFailureBranchBypassesTheMapper:
    """每个 admin-api 失败分支都必须走 `admin_api_failure`（否则授权失败会被就地降级）。"""

    def test_every_response_failure_return_goes_through_the_mapper(self):
        offenders: list[str] = []
        for path in tool_source_files():
            for site in unmapped_failure_sites(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.name}:{site}")
        assert offenders == [], (
            f"{len(offenders)} 处 admin-api 失败分支绕过了 `{MAPPER_NAME}`：\n  "
            + "\n  ".join(offenders[:40])
            + "\n\n修法：把该分支的 `ToolResult(success=False, error=…, message=…, suggestion=…)`"
            " 换成 `admin_api_failure(response, error=…, message=…, suggestion=…)`"
            "（suggestion 作为**兜底**，服务端给了建议时自动优先）。"
        )

    def test_every_success_mention_is_classified(self):
        """**分母口径（#4149 G4）**：凡提到 `.get("success")` 的判据都必须被归类。

        只数「检测器看得见的分支」的守卫**报告不出自己看不见的形态** —— `Or` 形态正是
        这样漏掉两个「授权失败被降级成套话」的分支。这里的分母与检测器无关地从源码数出来。
        """
        offenders: list[str] = []
        for path in tool_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for site in unclassified_success_tests(tree):
                offenders.append(f"{path.name}:{site}")
        assert offenders == [], (
            f"{len(offenders)} 处提到 `.get(\"success\")` 的判据无法归类"
            "（不在失败支、也不在成功支）：\n  "
            + "\n  ".join(offenders[:20])
            + "\n\n修法：把该形态加进 `_is_response_failure_test`（失败支）或 "
            "`_is_success_path_test`（成功支），并**为新形态补注入式红证夹具**"
            "（否则下一次同款盲区照样无人报出）。"
        )

    def test_every_success_read_is_accounted_for(self):
        """**分母口径（#4149 G4）**：每个 `.get("success")` 读取都必须在判据认识的上下文中。

        比上一条更细：即使判据分类得对，被读到中间变量里再判也算盲区 —— 那一处读取
        永远不会被任何分类看见。
        """
        offenders: list[str] = []
        for path in tool_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for lineno in unaccounted_success_reads(tree):
                offenders.append(f"{path.name}:{lineno}")
        assert offenders == [], (
            f"{len(offenders)} 处 `.get(\"success\")` 读取落在判据看不见的上下文里：\n  "
            + "\n  ".join(offenders[:20])
            + "\n\n修法：把判据写成 `if` 直接判（失败支/成功支各由判据形态识别），"
            "或在 `unaccounted_success_reads` 的合法上下文清单里显式登记该形态。"
        )

    def test_the_guard_reads_a_non_trivial_number_of_branches(self):
        """守卫不得空转：**源码真值口径**的分母与走映射点的返回数都必须足量（fail-closed）。

        分母不取自检测器自己：`mentions` = 源码里提到 `.get("success")` 的 `if` 判据条数
        （与 `_is_response_failure_test` 无关地数），`mapped` = 走共享映射点的失败分支返回数。
        """
        mentions = mapped = 0
        for path in tool_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mentions += len(success_mention_tests(tree))
            mapped += mapped_failure_returns(tree)
        assert mentions >= 100, (
            f"`app/tools/*.py` 只数出 {mentions} 个提到 `.get(\"success\")` 的判据（期望 ≥100）"
            "—— 真值源变了（工具被移动/重命名），分母口径会空转"
        )
        assert mapped >= 90, (
            f"`app/tools/*.py` 只解析出 {mapped} 个走映射点的失败分支（期望 ≥90）"
            f"（源码真值口径的分母 = {mentions} 条 success 判据）"
            "—— 判据口径已失效（守卫会空转通过），请核对工具是否被移动/重命名"
        )

    def test_the_guard_sees_the_real_source_tree(self):
        files = tool_source_files()
        assert len(files) >= 30, f"`{TOOLS_DIR}` 只找到 {len(files)} 个 .py —— 真相源消失（fail-closed）"
        assert (TOOLS_DIR / "base.py").exists(), "`app/tools/base.py` 不见了（fail-closed）"


# ──────────────────────────────────────────────────────────────────────────────
# ⑤ 判据自身可红 + 不恒真（落盘夹具注入：真写文件、真扫目录）
# ──────────────────────────────────────────────────────────────────────────────

_RAW_BOILERPLATE_FIXTURE = '''"""夹具：admin-api 失败分支就地返回套话（判据必须报出）。"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if not response.get("success"):
        return ToolResult(
            success=False,
            error="查询失败",
            message="查询失败",
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
    return ToolResult(success=True)
'''

_RAW_IS_FALSE_FIXTURE = '''"""夹具：`is False` 形态的失败分支同样必须走映射点。"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if response.get("success") is False:
        return ToolResult(success=False, error="x", message="x", suggestion="请重试")
    return ToolResult(success=True)
'''

_MAPPED_FIXTURE = '''"""夹具：同一失败分支改走共享映射点（判据必须不报）。"""
from app.tools.base import admin_api_failure


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if not response.get("success"):
        return admin_api_failure(
            response,
            error="查询失败",
            message="查询失败",
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
    return admin_api_failure(response, message="兜底")
'''

_LEGAL_FIXTURE = '''"""阴性负例：四类合法形态一律不得报出。"""
from app.tools.base import ToolResult


async def run(client, ctx, name=None):
    if not name:
        # 参数校验失败：与 admin-api 无关
        return ToolResult(success=False, error="缺少参数", message="缺少参数", suggestion="请补齐后重试")
    try:
        response = await client.get("/api/admin/things")
        if not response.get("success"):
            return admin_api_failure(response, suggestion="请稍后重试，如持续失败请联系技术支持")
        return ToolResult(success=True)
    except Exception as e:
        # 兜底分支：没有 admin-api 响应可映射
        return ToolResult(
            success=False, error="tool_execution_failed", message="失败",
            suggestion="请稍后重试，如持续失败请联系技术支持",
        )
'''


_OR_SHAPE_FIXTURE = '''"""夹具（#4149 G4 的缺口形态）：`Or` 布尔组合里的失败分支。

逐字节复刻 `piecework_query.py` / `production_progress_query.py` 的原始形态：
`if not isinstance(response, dict) or not response.get("success"):` → 就地返回套话。
旧判据只认 `not X.get("success")` / `is False` 两种**顶层**形态 ⇒ 这个分支
既没被迁移、也没被计入分母（判据是空的，报告不出来）。
"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if not isinstance(response, dict) or not response.get("success"):
        return ToolResult(success=False, error="x", message="x", suggestion="请稍后重试")
    return ToolResult(success=True)
'''

_OR_SHAPE_MAPPED_FIXTURE = '''"""阴性负例：同一 `Or` 形态**改走映射点**后判据必须放行（防恒红）。"""
from app.tools.base import admin_api_failure


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if not isinstance(response, dict) or not response.get("success"):
        return admin_api_failure(response, error="x", message="x", suggestion="请稍后重试")
    return admin_api_failure(response, message="兜底")
'''

_UNRECOGNISED_SHAPE_FIXTURE = '''"""夹具：判据**认不出**的 success 形态（`== 1`）—— 必须报出，不得静默落进盲区。"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if response.get("success") == 1:
        return ToolResult(success=True)
    return ToolResult(success=False, error="x", message="x", suggestion="请稍后重试")
'''

_HOISTED_READ_FIXTURE = '''"""夹具：`.get("success")` 被读到中间变量里再判 —— 该读取落在判据视野之外。"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    ok = response.get("success")
    if not ok:
        return ToolResult(success=False, error="x", message="x", suggestion="请稍后重试")
    return ToolResult(success=True)
'''

_LEGAL_READS_FIXTURE = '''"""阴性负例：三种合法决策上下文（成功判据 / 三元 / 推导式过滤）一律不得报出。"""
from app.tools.base import ToolResult


async def run(client, ctx):
    response = await client.get("/api/admin/things")
    if response.get("success"):
        rows = ((response.get("data") or {}).get("items") or []) if response.get("success") else []
        ok = [r for r in rows if r.get("success")]
        return ToolResult(success=True, data={"n": len(ok)})
    return ToolResult(success=False, error="x", message="x", suggestion="请稍后重试")
'''


class TestMapperGuardIsNotVacuous:
    """**:red_circle: 红证**（注入式）+ **阴性负例**：判据必须能报出，也必须能不报。"""

    def test_injected_raw_boilerplate_branch_is_reported(self, tmp_path):
        fixture = tmp_path / "fixture_raw_boilerplate.py"
        fixture.write_text(_RAW_BOILERPLATE_FIXTURE, encoding="utf-8")
        sites = unmapped_failure_sites(fixture.read_text(encoding="utf-8"))
        assert sites == ["7:ToolResult"], (
            f"绕过映射点的失败分支未被报出（判据是空的）：{sites!r}；"
            "期望恰好命中第 7 行的 `ToolResult(...)`"
        )

    def test_injected_is_false_form_is_reported(self, tmp_path):
        fixture = tmp_path / "fixture_is_false.py"
        fixture.write_text(_RAW_IS_FALSE_FIXTURE, encoding="utf-8")
        assert unmapped_failure_sites(fixture.read_text(encoding="utf-8")) == ["7:ToolResult"], (
            "`if response.get(\"success\") is False:` 形态必须同样被判据覆盖（否则是静默缺口）"
        )

    def test_injected_or_shape_is_reported(self, tmp_path):
        """**:red_circle: 红证（#4149 G4 的新形态）** —— `Or` 组合里的失败分支必须被报出。

        旧判据在此恒返回 `[]`（形态看不见）⇒ 这一支曾被静默跳过。
        """
        fixture = tmp_path / "fixture_or_shape.py"
        fixture.write_text(_OR_SHAPE_FIXTURE, encoding="utf-8")
        source = fixture.read_text(encoding="utf-8")
        sites = unmapped_failure_sites(source)
        assert sites == ["13:ToolResult"], (
            f"`Or` 形态的失败分支未被报出（判据仍看不见该形态）：{sites!r}"
        )
        assert response_failure_branches(ast.parse(source)) == [(13, ["ToolResult"])], (
            "该分支必须真的进了分母（否则计数口径仍在盲区）"
        )

    def test_or_shape_mapped_branch_is_not_reported(self, tmp_path):
        """**阴性负例**：同一 `Or` 形态改走映射点后必须不报（防恒红，修好后守卫让路）。"""
        fixture = tmp_path / "fixture_or_mapped.py"
        fixture.write_text(_OR_SHAPE_MAPPED_FIXTURE, encoding="utf-8")
        source = fixture.read_text(encoding="utf-8")
        assert unmapped_failure_sites(source) == []
        assert mapped_failure_returns(ast.parse(source)) == 1, (
            "改写后的分支必须被计入「走映射点」的分母"
        )

    def test_unrecognised_success_shape_is_reported(self, tmp_path):
        """**:red_circle: 盲区红证** —— 判据认不出的形态必须报出。

        这是「看不见的形态报告不出来」的**元判据**：`Or` 形态当年若落在这里，
        本单的缺口第一次出现时就会红，而不是等到人工复核才发现。
        """
        fixture = tmp_path / "fixture_unrecognised.py"
        fixture.write_text(_UNRECOGNISED_SHAPE_FIXTURE, encoding="utf-8")
        gaps = unclassified_success_tests(ast.parse(fixture.read_text(encoding="utf-8")))
        assert len(gaps) == 1 and gaps[0].startswith("7:") and "== 1" in gaps[0], (
            f"判据认不出的 `success` 形态未被报出（分母仍在盲区）：{gaps!r}"
        )

    def test_hoisted_success_read_is_reported(self, tmp_path):
        """**:red_circle: 盲区红证** —— 读取被挪进中间变量的形态同样必须报出。"""
        fixture = tmp_path / "fixture_hoisted.py"
        fixture.write_text(_HOISTED_READ_FIXTURE, encoding="utf-8")
        assert unaccounted_success_reads(ast.parse(fixture.read_text(encoding="utf-8"))) == ["7"], (
            "被读到变量里的 `.get(\"success\")` 未被报出（判据看不见这处读取）"
        )

    def test_legal_decision_contexts_are_not_flagged(self, tmp_path):
        """**阴性负例**：成功判据 / 三元 / 推导式过滤三种上下文必须放行（不得误伤）。"""
        fixture = tmp_path / "fixture_legal_reads.py"
        fixture.write_text(_LEGAL_READS_FIXTURE, encoding="utf-8")
        source = fixture.read_text(encoding="utf-8")
        assert unclassified_success_tests(ast.parse(source)) == []
        assert unaccounted_success_reads(ast.parse(source)) == [], (
            "判据误伤了合法读取形态（成功判据 / 三元 / 推导式过滤）"
        )
        assert unmapped_failure_sites(source) == []

    def test_mapped_branch_is_not_reported(self, tmp_path):
        """负例：改走映射点后**必须不报**（防恒红 —— 修好后守卫必须让路）。"""
        fixture = tmp_path / "fixture_mapped.py"
        fixture.write_text(_MAPPED_FIXTURE, encoding="utf-8")
        assert unmapped_failure_sites(fixture.read_text(encoding="utf-8")) == []

    def test_legal_shapes_are_not_flagged(self, tmp_path):
        """**阴性负例（证明没有拦掉原本合法的输入）** —— 参数校验 / except 兜底必须放行。"""
        fixture = tmp_path / "fixture_legal.py"
        fixture.write_text(_LEGAL_FIXTURE, encoding="utf-8")
        assert unmapped_failure_sites(fixture.read_text(encoding="utf-8")) == [], (
            "判据误伤了合法形态（参数校验分支 / except 兜底分支都必须放行）"
        )

    def test_mapper_returns_were_counted_in_the_fixture(self, tmp_path):
        """守卫的分母口径自证：走映射点的返回必须被数到（否则 `>= 90` 是空断言）。"""
        tree = ast.parse(_MAPPED_FIXTURE)
        assert mapped_failure_returns(tree) == 1, (
            "映射点调用未被计入分母 —— 守卫的 fail-closed 断言会空转"
            "（口径：只数**失败分支体内**的返回，分支外的成功/兜底返回不计）"
        )

# ──────────────────────────────────────────────────────────────────────────────
# ⑥ 真实 403 响应体穿过**曾被漏掉的两条分支**（#4149 G4 的后果闭环）
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_PERMISSION = "order:list"

#: 两条漏检分支的宿主：`(模块, 工具类, 会话上下文, 调用参数, 该分支调用方的套话文案)`。
#: 权限码恒为 `order:list`：`AgentProductionController` 类级 `@RequirePermission("order:list")`
#: 同时覆盖 `/production/progress` 与 `/production/piecework`。两工具的**授权层不同**
#: （计件声明权限码 `order:list`、仅 B 端；进度是双端角色白名单，B 端角色码是 `agent`）
#: ⇒ 上下文各给一份，免得把「工具层拒绝」误当成「admin-api 拒绝」。
_DENIAL_BRANCHES = [
    ("app.tools.piecework_query", PieceworkQueryTool,
     ToolContext(tenant_id=1, user_id="u-g4", session_id="s-g4", role="operator",
                 permissions=[REQUIRED_PERMISSION]),
     {"worker_name": "王师傅", "period": "2026-09"}, "查询计件失败，请稍后重试"),
    ("app.tools.production_progress_query", ProductionProgressQueryTool,
     ToolContext(tenant_id=1, user_id="u-g4", session_id="s-g4", role="agent"),
     {"order_no": "ORD-20260917-0001"}, "查询生产进度失败，请稍后重试"),
]


def _permission_denied_body(required: str = REQUIRED_PERMISSION) -> dict:
    """`PermissionDeniedResponse.of()` 产出的 403 响应体（含结构化 `details` 载体）。"""
    return {
        "success": False,
        "data": None,
        "error": {
            "code": "PERMISSION_DENIED",
            "message": f"权限不足，需要权限: {required}",
            "details": [{"field": "requiredPermission", "message": required}],
        },
        "requestId": "req_403",
        "timestamp": 1758000000,
    }


_STATE = {"session_id": "s-g4", "tenant_id": 1}


@pytest.fixture(autouse=True)
def _clear_read_only_tool_cache():
    """清 `_execute_tool_safe` 的只读结果缓存（同名工具 + 同参数会「不执行就成功」，跨用例污染）。"""
    _execute_tool_safe._cache = {}
    _execute_tool_safe._cache_lock = asyncio.Lock()
    yield
    _execute_tool_safe._cache = {}


class TestRealDenialBodyThroughTheToolBranch:
    """**:red_circle: 后果闭环**：真实 403 体穿过这两条**曾被 L0 锁漏掉的分支**。

    修复前复核实测（#4149）：`error_code=None`、服务端 `requiredPermission` 被丢弃、
    suggestion 落回调用方套话，且**自修复重试真的又调了一次工具**（同一身份再买一次拒绝）。
    本类把这条后果链逐环钉住 —— 只断言「走了映射点」是不够的（映射点走对了、错误码
    却在出口丢了，闸门照样恒判「可重试」）。
    """

    @pytest.mark.parametrize("module,tool_cls,ctx,args,boilerplate", _DENIAL_BRANCHES,
                             ids=["piecework", "production_progress"])
    async def test_the_denial_body_yields_an_executable_suggestion(
            self, module, tool_cls, ctx, args, boilerplate):
        with patch(f"{module}.get_admin_api_client") as factory:
            factory.return_value.get = AsyncMock(return_value=_permission_denied_body())
            result = await tool_cls().execute(context=ctx, **args)

        text = result.suggestion or ""
        assert result.success is False
        assert result.error_code == "PERMISSION_DENIED", (
            "错误码丢了 ⇒ 重试闸门读不到（恒判可重试，403 被当成参数问题）"
        )
        assert REQUIRED_PERMISSION in text, "服务端给出的缺失权限码必须保留在建议里"
        assert "不要重试" in text, "授权失败必须明确禁止重试"
        assert boilerplate not in text, "授权失败不得落回调用方套话"

    @pytest.mark.parametrize("module,tool_cls,ctx,args,boilerplate", _DENIAL_BRANCHES,
                             ids=["piecework", "production_progress"])
    async def test_the_denial_does_not_trigger_the_self_correct_retry(
            self, module, tool_cls, ctx, args, boilerplate):
        """走**生产出口**再交闸门：授权拒绝必须零重放（修复前实测工具被再调一次）。"""
        tool = tool_cls()
        with patch(f"{module}.get_admin_api_client") as factory:
            factory.return_value.get = AsyncMock(return_value=_permission_denied_body())
            _, result_dict = await _execute_tool_safe(tool, dict(args), ctx, dict(_STATE))
            assert result_dict["error_code"] == "PERMISSION_DENIED", (
                "出口字典没带错误码 ⇒ 闸门恒判「可重试」"
            )
            with patch(
                "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            ) as suggestion_llm:
                outcome = await _self_correct_retry(
                    tool, dict(args), ctx, "production", dict(result_dict),
                    "s-g4", 1, dict(_STATE),
                )
            assert suggestion_llm.call_count == 0, (
                "授权拒绝不得进入自修复（重试入口会把拒绝改写成「参数怎么补」）"
            )
            assert factory.return_value.get.call_count == 1, (
                f"工具被重放了（实际调用 {factory.return_value.get.call_count} 次）"
                "—— 403 又被当成参数问题重试了一遍"
            )
        assert outcome is None, "闸门必须短路（不返回修正后的结果）"
