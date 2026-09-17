"""
C 端收款二维码 API（小布支付页展示；issue #3990，M3-F-3）

- GET /chat/payment-qrcodes: 当前租户微信/支付宝收款码（顾客扫码直接付给商家，
  平台不经手资金，二清规避）。

安全设计（同 products.py）：JWT 认证（customer 角色）+ 服务端转发 admin-api
（X-Service-Token + X-Tenant-Id），C 端不直连 admin-api；只透出精简字段。
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from app.utils.auth import get_current_user, UserIdentity
from app.utils.http_client import get_admin_api_client
from app.api.response_models import make_response

router = APIRouter()


@router.get("/payment-qrcodes")
async def payment_qrcodes(
    user: UserIdentity = Depends(get_current_user),
) -> dict:
    """收款二维码：{wechat: {imageUrl,payeeName}, alipay: {...}}，缺省为空对象。"""
    tenant_id = user.tenant_id
    try:
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/agent/payment-qrcodes",
            tenant_id=tenant_id,
            user_id=user.user_id,
        )
    except Exception as e:
        logger.warning(f"[payment-qrcodes] admin-api call failed | tenant={tenant_id} error={e}")
        raise HTTPException(status_code=502, detail="收款服务暂时不可用")

    if not response.get("success"):
        logger.info(f"[payment-qrcodes] admin-api rejected | tenant={tenant_id} "
                    f"error={response.get('error', {}).get('message', 'unknown')}")
        return make_response(True, data={})

    data = response.get("data", {}) or {}
    lite = {}
    for ptype in ("wechat", "alipay"):
        q = data.get(ptype)
        if q:
            lite[ptype] = {
                "payment_type": ptype,
                "image_url": q.get("imageUrl") or q.get("image_url", ""),
                "payee_name": q.get("payeeName") or q.get("payee_name", ""),
            }
    return make_response(True, data=lite)
