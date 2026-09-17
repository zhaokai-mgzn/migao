"""app/utils/http_client.py 单元测试（issue #2430，defense 域熔断与 HTTP 封装）

覆盖：
- _get_headers：自动注入 X-Service-Token / X-Tenant-Id / X-User-Id / 额外头
- _get_client：惰性创建 httpx.AsyncClient（base_url / timeout / 默认头）
- _request：4xx → success=False 且不触发熔断 / 2xx success → 返回 data /
  2xx success=False → 计熔断失败并返回原始 error / 5xx → 向上抛 HTTPStatusError /
  CircuitBreakerOpenError → 降级返回 CIRCUIT_OPEN
- get/post/put/patch/delete 委托 _request
- close / 异步上下文管理器
- get_admin_api_client 单例 / reset_admin_api_client 重置
"""
# case_ids: DF-011

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.utils.http_client import (
    AdminApiClient,
    get_admin_api_client,
    reset_admin_api_client,
)

_BASE = "http://admin-api.test"


def _response(status_code, payload):
    req = httpx.Request("GET", f"{_BASE}/x")
    return httpx.Response(status_code, request=req, json=payload)


class TestGetHeaders:
    def test_injects_auth_tenant_user_and_extra(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok123")
        headers = client._get_headers(
            tenant_id=7,
            user_id="u1",
            extra_headers={"X-Custom": "c"},
        )
        assert headers["X-Service-Token"] == "tok123"
        assert headers["X-Tenant-Id"] == "7"
        assert headers["X-User-Id"] == "u1"
        assert headers["X-Custom"] == "c"

    def test_omits_missing_service_token(self):
        with patch.object(settings, "SERVICE_TOKEN", ""):
            client = AdminApiClient(base_url=_BASE, service_token="")
            headers = client._get_headers(tenant_id=1, user_id="u1")
            assert "X-Service-Token" not in headers
            assert headers["X-Tenant-Id"] == "1"
            assert headers["X-User-Id"] == "u1"


class TestGetClient:
    @pytest.mark.asyncio
    async def test_creates_httpx_client_with_timeout(self):
        with patch("httpx.AsyncClient") as mock_cls:
            client = AdminApiClient(base_url=_BASE, service_token="tok", timeout=5.0)
            got = await client._get_client()
            assert got is mock_cls.return_value
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["base_url"] == _BASE
            assert isinstance(kwargs["timeout"], httpx.Timeout)


class TestRequest:
    @pytest.mark.asyncio
    async def test_4xx_returns_error_without_breaker_failure(self):
        from app.core.circuit_breaker import get_breaker, reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(404, {"error": {"code": "NOT_FOUND", "message": "nope"}})
        )

        result = await client._request("GET", "/api/x")

        assert result["success"] is False
        assert result["error"]["code"] == "NOT_FOUND"
        assert get_breaker("admin_api:GET:/api/x").failure_count == 0

    @pytest.mark.asyncio
    async def test_4xx_passes_through_server_failure_details(self):
        """4xx 响应体必须**整份透传**（issue #4010 / A3）。

        修前只回 `{"success","error","data"}` 三个键 ⇒ 服务端给的 `suggestion` /
        `warnings` 全被丢弃，`product_manage.py` 读 `response["suggestion"]` 是死代码，
        `base_skill._self_correct_retry`（判据 = `result_dict["suggestion"]` 非空）
        对**一半失败面**永不启动。
        """
        from app.core.circuit_breaker import reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(400, {
                "success": False,
                "error": {"code": "PRODUCT_NAME_DUPLICATE", "message": "商品名已存在",
                          "details": [{"field": "name", "reason": "duplicate"}]},
                "suggestion": "换一个商品名后重试",
                "warnings": ["skuCode 已自动生成"],
            })
        )

        result = await client._request("POST", "/api/admin/agent/products")

        assert result["success"] is False
        assert result["suggestion"] == "换一个商品名后重试"
        assert result["warnings"] == ["skuCode 已自动生成"]
        assert result["error"]["code"] == "PRODUCT_NAME_DUPLICATE"
        assert result["error"]["details"] == [{"field": "name", "reason": "duplicate"}]

    @pytest.mark.asyncio
    async def test_4xx_server_success_flag_cannot_override_failure(self):
        """负例①：**失败语义不得被服务端 payload 反转** —— 4xx 一律 `success=False`。

        透传是「补字段」，不是「让服务端说了算」：即使 4xx 体里带 `success: true`
        或 `data`，也必须被强制为失败（回归保护，防 `{**body}` 写反覆盖顺序）。
        """
        from app.core.circuit_breaker import get_breaker, reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(422, {
                "success": True, "data": {"id": 9},
                "error": {"code": "VALIDATION", "message": "参数不合法"},
            })
        )

        result = await client._request("POST", "/api/admin/agent/products")

        assert result["success"] is False
        assert result["data"] is None
        assert result["error"]["code"] == "VALIDATION"
        assert get_breaker("admin_api:POST:/api/admin/agent/products").failure_count == 0

    @pytest.mark.asyncio
    async def test_4xx_without_suggestion_keeps_legacy_keys(self):
        """负例②：服务端**没给** `suggestion` 时不得凭空造一个（不许新增静默失效形态）。

        只补透传字段，不新增失败分支 —— 调用方原来的 `.get(..., 默认)` 兜底照旧生效。
        """
        from app.core.circuit_breaker import reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(403, {"error": {"code": "FORBIDDEN", "message": "无权访问"}})
        )

        result = await client._request("GET", "/api/x")

        assert result["success"] is False
        assert result["data"] is None
        assert "suggestion" not in result
        assert result["error"] == {"code": "FORBIDDEN", "message": "无权访问"}

    @pytest.mark.asyncio
    async def test_2xx_success_returns_data(self):
        from app.core.circuit_breaker import reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(200, {"success": True, "data": {"id": 1}})
        )

        result = await client._request("GET", "/api/x")

        assert result["success"] is True
        assert result["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_business_failure_counts_breaker_failure(self):
        from app.core.circuit_breaker import get_breaker, reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(
            return_value=_response(200, {
                "success": False,
                "error": {"code": "BIZ_ERR", "message": "bad"},
                "data": None,
            })
        )

        result = await client._request("GET", "/api/x")

        assert result["success"] is False
        assert result["error"]["code"] == "BIZ_ERR"
        assert get_breaker("admin_api:GET:/api/x").failure_count == 1

    @pytest.mark.asyncio
    async def test_5xx_raises_http_status_error(self):
        from app.core.circuit_breaker import reset_breakers

        reset_breakers()
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.request = AsyncMock(return_value=_response(500, {}))

        with pytest.raises(httpx.HTTPStatusError):
            await client._request("GET", "/api/x")

    @pytest.mark.asyncio
    async def test_circuit_open_returns_degraded(self):
        from app.core.circuit_breaker import CircuitBreakerOpenError

        client = AdminApiClient(base_url=_BASE, service_token="tok")
        breaker = MagicMock()
        breaker.state.value = "OPEN"
        breaker.failure_count = 3

        async def _raise_open(fn):
            raise CircuitBreakerOpenError("admin_api:GET:/api/x")

        breaker.call = _raise_open

        with patch("app.core.circuit_breaker.get_breaker", return_value=breaker):
            result = await client._request("GET", "/api/x")

        assert result["success"] is False
        assert result["error"]["code"] == "CIRCUIT_OPEN"


class TestHttpVerbs:
    @pytest.mark.asyncio
    async def test_get_delegates_to_request(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok")

        async def _spy(method, path, **kwargs):
            assert method == "GET"
            assert path == "/api/x"
            return {"success": True, "data": {}}

        with patch.object(client, "_request", new=_spy):
            result = await client.get("/api/x", params={"k": "v"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_post_delegates_to_request(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok")

        async def _spy(method, path, **kwargs):
            assert method == "POST"
            assert path == "/api/x"
            return {"success": True, "data": {}}

        with patch.object(client, "_request", new=_spy):
            result = await client.post("/api/x", json_data={"a": 1})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_put_patch_delete_delegate_to_request(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        seen = []

        async def _spy(method, path, **kwargs):
            seen.append(method)
            return {"success": True, "data": {}}

        with patch.object(client, "_request", new=_spy):
            await client.put("/api/x", json_data={"a": 1})
            await client.patch("/api/x", json_data={"a": 1})
            await client.delete("/api/x")

        assert seen == ["PUT", "PATCH", "DELETE"]


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_closes_underlying_client(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.aclose = AsyncMock()
        client._client = mock_http

        await client.close()

        mock_http.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_closes(self):
        client = AdminApiClient(base_url=_BASE, service_token="tok")
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.aclose = AsyncMock()
        client._client = mock_http

        async with client as c:
            assert c is client

        mock_http.aclose.assert_awaited_once()


class TestGlobalSingleton:
    def test_get_admin_api_client_singleton_and_reset(self):
        reset_admin_api_client()
        c1 = get_admin_api_client()
        c2 = get_admin_api_client()
        assert c1 is c2

        reset_admin_api_client()
        c3 = get_admin_api_client()
        assert c3 is not c1
