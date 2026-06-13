"""
订单查询 Tool 测试 — 验证 processingInfo 销售信息提取
"""
import pytest
from app.tools.order_query import OrderQueryTool


class TestFormatOrders:
    """_format_orders 方法：验证 processingInfo 提取"""

    def make_record(self, items):
        """构建测试用订单记录"""
        return {
            "id": "ord-1",
            "orderNo": "TEST-001",
            "customerName": "测试客户",
            "customerPhone": "13800138000",
            "totalAmount": 500.0,
            "status": "pending",
            "items": items,
            "createdAt": "2026-06-01T10:00:00Z",
        }

    def test_item_with_processingInfo_extracts_sales_info(self):
        """有 processingInfo 时提取销售信息"""
        tool = OrderQueryTool()
        record = self.make_record([{
            "productName": "窗帘",
            "productCode": "CL-001",
            "unitPrice": 168.0,
            "quantity": 2,
            "amount": 336.0,
            "processingInfo": {
                "colorName": "灰色",
                "sellingMethod": "bulk_cut",
                "doorWidth": "2.8米",
                "skuCode": "SKU-GREY-280",
                "processingFee": 50.0,
            },
        }])

        result = tool._format_orders([record])
        item = result[0]["items"][0]

        assert item["product_name"] == "窗帘"
        assert item["销售信息"] is not None
        assert item["销售信息"]["颜色"] == "灰色"
        assert item["销售信息"]["售卖方式"] == "散剪"
        assert item["销售信息"]["门幅"] == "2.8米"
        assert item["销售信息"]["SKU编码"] == "SKU-GREY-280"
        assert item["销售信息"]["加工费"] == "¥50.00"

    def test_item_without_processingInfo_has_none_sales_info(self):
        """无 processingInfo 时销售信息为 None"""
        tool = OrderQueryTool()
        record = self.make_record([{
            "productName": "样本册",
            "productCode": "SP-001",
            "unitPrice": 50.0,
            "quantity": 1,
            "amount": 50.0,
        }])

        result = tool._format_orders([record])
        item = result[0]["items"][0]

        assert item["product_name"] == "样本册"
        assert item["销售信息"] is None

    def test_selling_method_translation(self):
        """售卖方式正确翻译为中文"""
        tool = OrderQueryTool()
        test_cases = [
            ("bulk_cut", "散剪"),
            ("full_roll", "整卷"),
            ("per_meter", "按米"),
            ("per_piece", "按件"),
        ]
        for code, expected_label in test_cases:
            record = self.make_record([{
                "productName": "test",
                "unitPrice": 10.0,
                "quantity": 1,
                "amount": 10.0,
                "processingInfo": {"sellingMethod": code},
            }])
            result = tool._format_orders([record])
            assert result[0]["items"][0]["销售信息"]["售卖方式"] == expected_label

    def test_multiple_items_with_mixed_processingInfo(self):
        """多商品混合：有的有销售信息，有的没有"""
        tool = OrderQueryTool()
        record = self.make_record([
            {
                "productName": "有颜色",
                "unitPrice": 100.0,
                "quantity": 1,
                "amount": 100.0,
                "processingInfo": {"colorName": "米白"},
            },
            {
                "productName": "无颜色",
                "unitPrice": 50.0,
                "quantity": 1,
                "amount": 50.0,
            },
        ])

        result = tool._format_orders([record])
        items = result[0]["items"]

        assert items[0]["销售信息"] is not None
        assert items[0]["销售信息"]["颜色"] == "米白"
        assert items[1]["销售信息"] is None

    def test_order_top_level_fields_preserved(self):
        """订单顶层字段不受影响"""
        tool = OrderQueryTool()
        record = self.make_record([])

        result = tool._format_orders([record])
        order = result[0]

        assert order["id"] == "ord-1"
        assert order["order_no"] == "TEST-001"
        assert order["customer_name"] == "测试客户"
        assert order["total_amount"] == 500.0
        assert order["status"] == "pending"
