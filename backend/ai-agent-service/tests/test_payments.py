"""C 端收款二维码 API 单元测试（app/api/payments.py，issue #3990，M3-F-3）

覆盖：代理 admin-api /api/admin/agent/payment-qrcodes + 精简字段（image_url/payee_name）、
缺省返回空对象。
"""
# case_ids: ST-011
import pytest

from app.api import payments



class FakeUser:
    tenant_id = 1
    user_id = "u-1"


class FakeClient:
    def __init__(self, payload: dict):
        self._payload = payload

    async def get(self, *args, **kwargs):
        return {"success": True, "data": self._payload}


@pytest.mark.asyncio
async def test_payment_qrcodes_proxy_lite_fields(monkeypatch):
    """代理成功 → 精简字段（wechat/alipay）"""
    monkeypatch.setattr(
        payments, "get_current_user", lambda: FakeUser(),
        raising=False,
    )
    admin_payload = {
        "wechat": {"paymentType": "wechat", "imageUrl": "https://img/w.png",
                   "payeeName": "亿家纺织"},
        "alipay": {"paymentType": "alipay", "imageUrl": "https://img/a.png",
                   "payeeName": "亿家纺织"},
    }
    monkeypatch.setattr(payments, "get_admin_api_client",
                        lambda: FakeClient(admin_payload))
    # 直接调用路由函数（绕过 HTTP 层）
    result = await payments.payment_qrcodes(user=FakeUser())
    assert result["success"] is True
    assert result["data"]["wechat"]["image_url"] == "https://img/w.png"
    assert result["data"]["wechat"]["payee_name"] == "亿家纺织"
    assert result["data"]["alipay"]["payment_type"] == "alipay"


@pytest.mark.asyncio
async def test_payment_qrcodes_empty(monkeypatch):
    """无收款码 → 空对象"""
    monkeypatch.setattr(payments, "get_current_user", lambda: FakeUser(), raising=False)
    monkeypatch.setattr(payments, "get_admin_api_client",
                        lambda: FakeClient({}))
    result = await payments.payment_qrcodes(user=FakeUser())
    assert result["success"] is True
    assert result["data"] == {}
