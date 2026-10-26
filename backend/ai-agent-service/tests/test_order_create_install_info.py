# case_ids: OR-046, OR-055
"""order_create 工具携带「安装小区 / 安装位置」（issue #7856）。

用户 2026-10-26 逐字：「订单，水洗唛，成品出库单，发货联上还缺了一个信息，窗帘的安装位置，是卧室还是
阳台，还有客户要求我们备注窗帘未来安装给哪个小区」；补充口径：「C 端/客服收单允许先空、后台再补」
⇒ 两个参数都**必须可选**、**不追问**（不改 prompt 追问）。

两条判据（零 LLM / 零网络）：

- ① **不传 ⇒ 不带键**：`install_community=None` / `items[].install_room` 缺省时，发给服务端的
  `json_data` 里**不出现** `installCommunity` / `installRoom`（服务端「缺值不落键」，不许拿空串或
  `null` 占位 —— 那会在 `processing_info` 里留下一个空字符串，纸面读侧分不清「没填」与「填了个空」）。
- ② **传了 ⇒ 原样透传**：`install_community` → `installCommunity`（顶层，与 `customer_address` 同层），
  `items[].install_room` → `installRoom`（件级，跟随 items 结构）。

为什么必须钉：工具侧是**逐键白名单**装配（`entry[java_key] = value`），少登记一个键就**静默丢掉**
——顾客/客服确实填了、服务端也确实支持，纸面上却没有这两行，而且没有任何东西会变红。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.base import ToolContext
from app.tools.order_create import OrderCreateTool
from tests.test_order_create_tool_price_grounding import _detail_response, _search_response


def _run(items, install_community=None):
    """执行 order_create（mock admin-api 商品库 + 记录真正发出的 POST body）。

    Returns:
        (result, sent_payload: dict|None)
    """
    client = MagicMock()

    async def fake_get(path, params=None, **kwargs):
        if path.rstrip("/").endswith("/products"):  # product_search
            return _search_response()
        return _detail_response()  # product_detail（库价 168 ⇒ 单价接地通过）

    client.get = AsyncMock(side_effect=fake_get)
    sent = {}

    async def fake_post(path, json_data=None, **kwargs):
        sent["payload"] = json_data
        return {"success": True, "data": {"id": "o1", "orderNo": "ORD-2026-0001"}}

    client.post = AsyncMock(side_effect=fake_post)

    with patch("app.tools.order_create.get_admin_api_client", return_value=client), \
         patch("app.tools.order_create.SMS_BYPASS_CODE", "123456"):
        tool = OrderCreateTool()
        result = asyncio.run(tool.execute(
            context=ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="agent"),
            customer_name="张三",
            customer_phone="13800138000",
            items=items,
            install_community=install_community,
        ))
    return result, sent.get("payload")


def _item(install_room=None):
    """一行明细（单价 = 库价 168 ⇒ 通过工具层的单价接地闸门）。"""
    item = {"product_name": "遮光窗帘", "quantity": 3, "unit_price": 168.0, "subtotal": 504.0}
    if install_room is not None:
        item["install_room"] = install_room
    return item


def test_install_info_absent_is_not_sent():
    """不传安装信息 ⇒ 请求体里**不带**这两个键（可选、允许先空）。"""
    result, payload = _run([_item()])

    assert result.success is True, result.message
    assert payload is not None, "下单必须真的发到服务端（否则本判据在空跑）"
    assert "installCommunity" not in payload, \
        f"未传 install_community ⇒ 不许自带该键（服务端「缺值不落键」）: {payload}"
    assert "installRoom" not in payload["items"][0], \
        f"明细未传 install_room ⇒ 不许自带该键: {payload['items'][0]}"


def test_install_info_is_passed_through_verbatim():
    """传了 ⇒ 原样透传（工具侧不归一、不编造；归一/准入在服务端）。"""
    result, payload = _run([_item(install_room="主卧")], install_community="春江花园 3栋2单元")

    assert result.success is True, result.message
    assert payload["installCommunity"] == "春江花园 3栋2单元", \
        f"订单级安装小区必须与入参逐字相同: {payload.get('installCommunity')!r}"
    assert payload["items"][0]["installRoom"] == "主卧", \
        f"件级安装位置必须与入参逐字相同: {payload['items'][0].get('installRoom')!r}"
