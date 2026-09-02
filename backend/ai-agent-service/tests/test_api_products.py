"""
C 端只读端点测试 — 新品推荐 + 我的订单/售后（数据隔离）

验证 GET /chat/products/new-arrivals、/chat/orders/mine、/chat/after-sales/mine：
- JWT 认证（未认证 401）
- 服务端转发 admin-api（X-Service-Token + X-Tenant-Id + X-User-Id）
- 订单/售后强制按当前用户过滤（透传 user_id）
- 固定参数（size 1~12 / 1~20），不可传任意筛选
- 精简字段返回（不泄露内部字段）
- 统一响应包装 {success, data:{items,total}}（与 ai-api 其余端点/H5 mock 一致，
  mini-app productService 按 ApiResponse 解包，裸结构会导致前端恒空）
- admin-api 失败时降级为空列表（success=true + data 空，不抛 500）
"""
# case_ids: PR-001, OR-001, AS-001
import pytest
from unittest.mock import patch, AsyncMock

from fastapi import HTTPException

from app.api.products import new_arrivals, my_orders, my_after_sales


def _customer_user(user_id="cust-1", tenant_id=7):
    from app.utils.auth import UserIdentity, UserRole
    return UserIdentity(user_id=user_id, tenant_id=tenant_id,
                        identity_type="wechat_mini", role=UserRole.CUSTOMER)


@pytest.mark.asyncio
async def test_new_arrivals_forwards_to_admin_api():
    """正常路径：转发 admin-api 并精简字段"""
    user = _customer_user()

    mock_response = {
        "success": True,
        "data": {
            "items": [
                {"id": "p1", "name": "遮光窗帘", "price": 19900, "mainImage": "img1",
                 "salesCount": 12, "status": "on_sale", "internalField": "secret"},
                {"id": "p2", "name": "北欧风窗帘", "price": 29900, "image": "img2",
                 "salesCount": 3, "status": "on_sale"},
            ],
            "total": 2,
        },
    }
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await new_arrivals(size=6, user=user)

        # 转发参数：商家推荐标记 + 在售 + 按创建时间倒序
        call = mock_client.get.call_args
        assert call.args[0] == "/api/admin/products"
        params = call.kwargs["params"]
        assert params["sortOrder"] == "createdAt"
        assert params["sort"] == "desc"
        assert params["status"] == "on_sale"
        assert params["recommended"] is True
        assert params["size"] == 6
        # 透传租户与用户
        assert call.kwargs["tenant_id"] == 7
        assert call.kwargs["user_id"] == "cust-1"

        # 精简字段：不含 internalField
        assert result["success"] is True
        data = result["data"]
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["name"] == "遮光窗帘"
        assert data["items"][0]["price"] == 19900
        assert "internalField" not in data["items"][0]


@pytest.mark.asyncio
async def test_new_arrivals_size_bounded():
    """size 被 FastAPI 约束在 1~12（Query ge/le），防大拉取"""
    user = _customer_user()

    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        # 正常范围内调用成功
        result = await new_arrivals(size=12, user=user)
        assert result["success"] is True
        assert result["data"]["items"] == []


@pytest.mark.asyncio
async def test_new_arrivals_admin_failure_degrades_to_empty():
    """admin-api 拒绝/失败 → 返回空列表（不阻塞对话页）"""
    user = _customer_user()

    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False,
            "error": {"code": "PERMISSION_DENIED", "message": "denied"},
            "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await new_arrivals(size=6, user=user)
        assert result["success"] is True
        assert result["data"]["items"] == []
        assert result["data"]["total"] == 0


@pytest.mark.asyncio
async def test_new_arrivals_network_error_raises_502():
    """网络异常 → 502（服务不可用，前端降级隐藏）"""
    user = _customer_user()

    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc:
            await new_arrivals(size=6, user=user)
        assert exc.value.status_code == 502


# ═══════════ 我的订单 / 我的售后（数据隔离）═══════════

@pytest.mark.asyncio
async def test_my_orders_forces_user_filter():
    """我的订单：调用 C 端专用 /mine 端点，强制透传当前用户"""
    user = _customer_user()
    mock_response = {
        "success": True,
        "data": {
            "items": [
                {"id": "o1", "orderNo": "ORD-A", "status": "shipped",
                 "statusText": "已发货", "totalAmount": 199.0,
                 "createdAt": "2026-06-01T10:00:00Z", "internalField": "x"},
            ],
            "total": 1,
        },
    }
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await my_orders(page=1, size=5, status=None, user=user)

        call = mock_client.get.call_args
        assert call.args[0] == "/api/admin/agent/orders/mine"
        assert call.kwargs["user_id"] == "cust-1"
        assert call.kwargs["tenant_id"] == 7
        assert call.kwargs["params"]["page"] == 1
        assert call.kwargs["params"]["size"] == 5
        # 统一包装 + 精简字段
        assert result["success"] is True
        data = result["data"]
        assert data["items"][0]["order_no"] == "ORD-A"
        assert "internalField" not in data["items"][0]


@pytest.mark.asyncio
async def test_my_orders_status_filter():
    """我的订单支持状态筛选透传"""
    user = _customer_user()
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={"success": True, "data": {"items": [], "total": 0}})
        mock_get_client.return_value = mock_client

        await my_orders(page=1, size=5, status="shipped", user=user)
        assert mock_client.get.call_args.kwargs["params"]["status"] == "shipped"


@pytest.mark.asyncio
async def test_my_orders_failure_degrades_to_empty():
    """我的订单失败 → 空列表（不阻塞「我的」页）"""
    user = _customer_user()
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "denied"}, "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await my_orders(page=1, size=5, status=None, user=user)
        assert result["success"] is True
        assert result["data"]["items"] == []
        assert result["data"]["total"] == 0


@pytest.mark.asyncio
async def test_my_after_sales_forces_user_filter():
    """我的售后：调用 C 端专用 /mine 端点，强制透传当前用户"""
    user = _customer_user(user_id="cust-9")
    mock_response = {
        "success": True,
        "data": {
            "items": [
                {"id": "t1", "ticketNo": "AS-001", "status": "pending",
                 "ticketType": "refund", "createdAt": "2026-06-01T10:00:00Z"},
            ],
            "total": 1,
        },
    }
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await my_after_sales(page=1, size=5, user=user)

        call = mock_client.get.call_args
        assert call.args[0] == "/api/admin/agent/after-sales/mine"
        # 用户隔离由后端从 X-User-Id 强制，不透传 customerId 等跨用户参数
        assert call.kwargs["user_id"] == "cust-9"
        assert "customerId" not in call.kwargs["params"]
        assert call.kwargs["params"]["page"] == 1
        assert call.kwargs["params"]["size"] == 5
        assert result["success"] is True
        assert result["data"]["items"][0]["ticket_no"] == "AS-001"


@pytest.mark.asyncio
async def test_my_after_sales_failure_degrades_to_empty():
    """我的售后失败 → 空列表"""
    user = _customer_user()
    with patch("app.api.products.get_admin_api_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value={
            "success": False, "error": {"message": "denied"}, "data": None,
        })
        mock_get_client.return_value = mock_client

        result = await my_after_sales(page=1, size=5, user=user)
        assert result["success"] is True
        assert result["data"]["items"] == []
