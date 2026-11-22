# case_ids: OR-049
"""跨**进程**幂等键探针（issue #9017 / 集群审计 P0-4）—— 由
`tests/test_order_idempotency_key_deterministic.py` 以子进程方式拉起。

为什么必须在**独立 OS 进程**里跑：本单的缺陷正是「键挂在进程内的 `lru_cache` + `uuid4`
上」。同进程里跑两遍永远拿到同一个缓存值，**测不出**跨实例/重启的形态 —— 只有真开两个
进程（各自空的模块状态）才能复现「实例 A 算出的键 ≠ 实例 B 算出的键」。

用法（父进程只关心最后一行 JSON）：

    python tests/_order_key_probe.py <quantity>

环境变量：
- `PROBE_NOW`：钉住 `time.time()`（默认 `1700000000`，落在同一个 10 分钟窗内）——
  不钉时钟的话，两次探针一旦跨过窗口边界就会假红/假绿（幂等键是时间的函数）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

# 子进程的 cwd 是 service 根（父进程显式指定）；这里再兜一次，避免 cwd 漂移时 import 失败。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.base import ToolContext  # noqa: E402
from app.tools.order_create import CLIENT_REQUEST_ID_HEADER, OrderCreateTool  # noqa: E402

#: 钉死的"现在"（≈2023-11-14）：两次探针必须落在**同一个** 10 分钟窗内。
PINNED_NOW = float(os.environ.get("PROBE_NOW", "1700000000"))


def _fake_client(price: int = 168):
    """admin-api 替身：商品查询（单价接地）+ 下单 POST（记录下发的头）。"""
    client = AsyncMock()

    async def _get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):
            return {"success": True, "data": {"items": [{"id": "p1", "name": "遮光窗帘"}], "total": 1}}
        return {"success": True, "data": {
            "id": "p1", "name": "遮光窗帘", "price": price, "basePrice": price,
            "skus": [{"id": "p1-1", "skuCode": "SKU-1", "colorName": "米白", "price": price}]}}

    client.get = AsyncMock(side_effect=_get)
    client.post = AsyncMock(return_value={
        "success": True, "data": {"id": "order-1", "orderNo": "ORD-1", "totalAmount": 528.0}})
    return client


async def main() -> None:
    quantity = float(sys.argv[1]) if len(sys.argv) > 1 else 3
    # `role="agent"`（客服代下单）绕开 SMS 闸门：本探针只关心幂等键，不造 OTP 状态。
    ctx = ToolContext(tenant_id=1, user_id="u1", session_id="sess_A", role="agent")
    client = _fake_client()
    with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
         patch("app.tools.order_create.time.time", return_value=PINNED_NOW):
        result = await OrderCreateTool().execute(
            context=ctx,
            customer_name="张三",
            customer_phone="13800138000",
            items=[{"product_name": "遮光窗帘", "quantity": quantity,
                    "unit_price": 168, "subtotal": quantity * 168}],
        )
    assert result.success is True, f"探针下单没成功：{result.message}"
    headers = client.post.await_args.kwargs.get("headers") or {}
    print(json.dumps({
        "pid": os.getpid(),
        "key": headers.get(CLIENT_REQUEST_ID_HEADER),
        "quantity": quantity,
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
