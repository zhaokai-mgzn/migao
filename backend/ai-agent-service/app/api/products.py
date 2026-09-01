"""
C 端商品/订单/售后只读 API（小布）

提供对话/「我的」页的数据端点：
- GET /chat/products/new-arrivals: 新品推荐（商家显式打标的在售商品）
- GET /chat/orders/mine: 我的订单（强制按当前用户过滤）
- GET /chat/after-sales/mine: 我的售后工单（强制按当前用户过滤）

安全设计：
- JWT 认证（customer 角色）
- 服务端转发 admin-api（X-Service-Token + X-Tenant-Id），C 端不直连 admin-api
- 只读、固定参数（size 上限），不接受任意筛选参数（防绕过）
- 订单/售后强制按 X-User-Id 透传的当前用户过滤（数据隔离）
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.utils.auth import get_current_user, UserIdentity
from app.utils.http_client import get_admin_api_client

router = APIRouter()


@router.get("/products/new-arrivals")
async def new_arrivals(
    size: int = Query(default=6, ge=1, le=12),
    user: UserIdentity = Depends(get_current_user),
) -> dict:
    """新品推荐：商家显式打标的在售商品（C 端只读）。

    业务闭环：商家在商品管理页 PUT /api/admin/products/{id}/recommend 打标 →
    admin-api 落库 recommended=true → 本端点只查 recommended=true 的商品 →
    C 端 mini-app「新品推荐」位展示。
    """
    tenant_id = user.tenant_id
    try:
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/products",
            params={"page": 1, "size": size, "status": "on_sale",
                    "recommended": True,
                    "sortOrder": "createdAt", "sort": "desc"},
            tenant_id=tenant_id,
            user_id=user.user_id,
        )
    except Exception as e:
        logger.warning(f"[new-arrivals] admin-api call failed | tenant={tenant_id} error={e}")
        raise HTTPException(status_code=502, detail="商品服务暂时不可用")

    if not response.get("success"):
        logger.info(f"[new-arrivals] admin-api rejected | tenant={tenant_id} "
                    f"error={response.get('error', {}).get('message', 'unknown')}")
        return {"items": [], "total": 0}

    data = response.get("data", {})
    items = data.get("items", []) or []
    # 精简 C 端展示字段（不泄露内部字段）
    lite = []
    for p in items[:size]:
        lite.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "price": p.get("price") or p.get("basePrice") or 0,
            "image": p.get("image") or p.get("mainImage") or
                     (p.get("images") or [None])[0],
            "sales_count": p.get("salesCount") or p.get("sales_count") or 0,
        })
    return {"items": lite, "total": data.get("total", len(lite))}


@router.get("/orders/mine")
async def my_orders(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=5, ge=1, le=20),
    status: Optional[str] = Query(default=None),
    user: UserIdentity = Depends(get_current_user),
) -> dict:
    """我的订单（「我的」页入口）：强制按当前用户过滤。

    复用 C 端专用端点 /api/admin/agent/orders/mine（数据隔离强制点：
    admin-api 从 X-User-Id 强制按用户过滤，此处仅透传展示字段）。
    """
    tenant_id = user.tenant_id
    try:
        client = get_admin_api_client()
        params: dict = {"page": page, "size": size}
        if status:
            params["status"] = status
        response = await client.get(
            "/api/admin/agent/orders/mine",
            params=params,
            tenant_id=tenant_id,
            user_id=user.user_id,
        )
    except Exception as e:
        logger.warning(f"[my-orders] admin-api call failed | tenant={tenant_id} error={e}")
        raise HTTPException(status_code=502, detail="订单服务暂时不可用")

    if not response.get("success"):
        logger.info(f"[my-orders] admin-api rejected | tenant={tenant_id} "
                    f"error={response.get('error', {}).get('message', 'unknown')}")
        return {"items": [], "total": 0}

    data = response.get("data", {})
    items = data.get("items", []) or []
    # 精简 C 端订单展示字段
    lite = []
    for o in items[:size]:
        lite.append({
            "id": o.get("id"),
            "order_no": o.get("orderNo") or o.get("order_no", ""),
            "status": o.get("status", ""),
            "status_text": o.get("statusText") or o.get("status_text", o.get("status", "")),
            "total_amount": o.get("totalAmount") or o.get("total_amount") or 0,
            "created_at": o.get("createdAt") or o.get("created_at", ""),
        })
    return {"items": lite, "total": data.get("total", len(lite))}


@router.get("/after-sales/mine")
async def my_after_sales(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=5, ge=1, le=20),
    user: UserIdentity = Depends(get_current_user),
) -> dict:
    """我的售后工单（「我的」页入口）：强制按当前用户过滤。

    复用售后查询的用户隔离参数（customerId 透传当前用户），
    后端 after-sales 列表同样按 tenant + customer 双重过滤。
    """
    tenant_id = user.tenant_id
    try:
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/after-sales",
            params={"page": page, "size": size,
                    "customerId": user.user_id},
            tenant_id=tenant_id,
            user_id=user.user_id,
        )
    except Exception as e:
        logger.warning(f"[my-after-sales] admin-api call failed | tenant={tenant_id} error={e}")
        raise HTTPException(status_code=502, detail="售后服务暂时不可用")

    if not response.get("success"):
        logger.info(f"[my-after-sales] admin-api rejected | tenant={tenant_id} "
                    f"error={response.get('error', {}).get('message', 'unknown')}")
        return {"items": [], "total": 0}

    data = response.get("data", {})
    items = data.get("items", []) or []
    # 精简 C 端售后工单展示字段
    lite = []
    for t in items[:size]:
        lite.append({
            "id": t.get("id"),
            "ticket_no": t.get("ticketNo") or t.get("ticket_no", ""),
            "status": t.get("status", ""),
            "ticket_type": t.get("ticketType") or t.get("ticket_type", ""),
            "created_at": t.get("createdAt") or t.get("created_at", ""),
        })
    return {"items": lite, "total": data.get("total", len(lite))}
