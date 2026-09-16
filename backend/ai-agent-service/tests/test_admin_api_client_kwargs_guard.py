"""
仓库级守卫 — app/tools/*.py 内禁止用 httpx 风格的 `json=` 调用自研 admin-api 客户端

issue #3548（P0）：finance_api.create_transaction 用 `client.post(..., json=payload)`
调用自研客户端，而 `app/utils/http_client.py::AdminApiClient.post` 只接受 `json_data`
且无 `**kwargs` → 每次调用必然 `TypeError: post() got an unexpected keyword argument 'json'`
→ 米宝「登记线下收支」100% 失效（评测用例 FN-001 恒失败）。

同类缺陷的通用形态：调用自研客户端时的关键字拼写错误（`json=` vs `json_data=`）。
本测试把该约束**上升为仓库级守卫**：扫描全部工具模块，任何 admin-api 客户端调用
出现 `json=` 关键字即失败，防止同类回归。

检测器用 AST（而非纯正则）的原因：多行调用 / 嵌套括号会让正则在调用边界上误判；
AST 还能精确区分 `json=` 与 `json_data=`（后者合法，不得误报）。
"""
# case_ids: FN-001

import ast
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"

# admin-api 客户端调用的 HTTP 方法（self 客户端封装为 post/put/patch/request）
_HTTP_METHODS = {"post", "put", "patch", "request"}
# 说明该调用是「自研 admin-api 客户端调用」的标记：多租户透传参数 / admin 端点前缀
_ADMIN_CALL_MARKER_KWARGS = {"tenant_id", "user_id"}
_ADMIN_PATH_PREFIX = "/api/admin"


def _is_admin_api_call(node: ast.Call) -> bool:
    """判定 ast.Call 是否为自研 admin-api 客户端调用"""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
        return False
    if any(kw.arg in _ADMIN_CALL_MARKER_KWARGS for kw in node.keywords):
        return True
    for arg in node.args:
        # 路径常量以 /api/admin 开头（如 client.post("/api/admin/finance/transactions", ...)）
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                and arg.value.startswith(_ADMIN_PATH_PREFIX):
            return True
    return False


def _find_json_kwarg_violations(source: str, filename: str = "<source>") -> list:
    """返回 [(文件名, 行号, 关键字名)]——admin-api 客户端调用中出现的 `json=` 关键字"""
    violations = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not _is_admin_api_call(node):
            continue
        for kw in node.keywords:
            if kw.arg == "json":
                violations.append((filename, node.lineno, kw.arg))
    return violations


def _iter_tool_sources():
    for path in sorted(TOOLS_DIR.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")


class TestDetectorSelfCheck:
    """检测器自校验——守卫测试不得静默失效（永远绿的空扫描）"""

    def test_detects_httpx_style_json_kwarg(self):
        src = (
            "async def f(client, payload):\n"
            "    return await client.post(\n"
            '        "/api/admin/finance/transactions",\n'
            "        json=payload,\n"
            "        tenant_id=1,\n"
            "    )\n"
        )
        assert _find_json_kwarg_violations(src, "sample.py") == [("sample.py", 2, "json")]

    def test_detects_json_kwarg_without_path_literal(self):
        """仅靠 tenant_id 标记也能命中（路径为变量时）"""
        src = (
            "async def f(client, path, payload):\n"
            "    return await client.put(path, json=payload, tenant_id=1, user_id='u1')\n"
        )
        assert len(_find_json_kwarg_violations(src, "sample.py")) == 1

    def test_does_not_flag_json_data(self):
        """json_data= 是自研客户端的正确关键字——不得误报"""
        src = (
            "async def f(client, payload):\n"
            "    return await client.post(\n"
            '        "/api/admin/finance/transactions",\n'
            "        json_data=payload,\n"
            "        tenant_id=1,\n"
            "    )\n"
        )
        assert _find_json_kwarg_violations(src, "sample.py") == []

    def test_does_not_flag_non_admin_http_client(self):
        """第三方 httpx 调用（无 tenant_id/user_id、非 /api/admin 端点）不属本守卫范围"""
        src = (
            "async def f(client, url, payload):\n"
            "    return await client.post(url, json=payload)\n"
        )
        assert _find_json_kwarg_violations(src, "sample.py") == []


class TestNoJsonKwargInTools:
    """全量工具模块扫描：admin-api 客户端调用必须用 json_data="""

    def test_app_tools_have_no_admin_api_json_kwarg(self):
        violations = []
        for path, source in _iter_tool_sources():
            violations.extend(_find_json_kwarg_violations(source, path.name))
        assert violations == [], (
            "app/tools/ 内存在 httpx 风格 json= 调用自研 admin-api 客户端（应为 json_data=）：\n"
            + "\n".join(f"  {name}:{lineno} json={kw}" for name, lineno, kw in violations)
        )

    def test_tools_dir_actually_scanned(self):
        """防止 TOOLS_DIR 路径漂移导致扫描零文件（守卫假绿）"""
        files = [p.name for p, _ in _iter_tool_sources()]
        assert "finance_api.py" in files, f"工具目录扫描异常: {files[:5]}"


@pytest.mark.parametrize("module_name", ["finance_api"])
def test_finance_tool_source_uses_json_data(module_name):
    """FN-001 定点回归：finance_api 的登记收支必须传 json_data=payload"""
    source = (TOOLS_DIR / f"{module_name}.py").read_text(encoding="utf-8")
    assert "json_data=payload" in source
