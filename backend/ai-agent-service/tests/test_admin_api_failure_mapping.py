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
5. 判据自身**可红 + 不恒真**（`TestMapperGuardIsNotVacuous`：注入式夹具必报、合法形态必不报）。

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
from pathlib import Path

import pytest

from app.tools.base import (
    NON_RETRYABLE_ERROR_CODES,
    ToolContext,
    ToolResult,
    admin_api_failure,
)

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


def _is_response_failure_test(test: ast.AST) -> bool:
    """`not X.get("success")` 或 `X.get("success") is False` —— admin-api 失败分支。"""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _success_get_call(test.operand)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op = test.ops[0]
        is_false = any(
            isinstance(c, ast.Constant) and c.value is False for c in test.comparators
        )
        if is_false and (isinstance(op, (ast.Is, ast.Eq))):
            return _success_get_call(test.left) or (
                bool(test.comparators) and _success_get_call(test.comparators[0])
            )
    return False


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

    def test_the_guard_reads_a_non_trivial_number_of_branches(self):
        """守卫不得空转：本体里必须解析出足量已映射的失败分支（fail-closed）。"""
        total = sum(
            mapped_failure_returns(ast.parse(p.read_text(encoding="utf-8")))
            for p in tool_source_files()
        )
        assert total >= 90, (
            f"`app/tools/*.py` 只解析出 {total} 个走映射点的失败分支（期望 ≥90）"
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