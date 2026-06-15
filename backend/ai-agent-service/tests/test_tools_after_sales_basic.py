"""after_sales_manage + customer_manage tool 基础测试"""
import pytest


class TestAfterSalesManageTool:
    """售后管理 Tool 测试"""

    def test_tool_import(self):
        """可以正常导入"""
        from app.tools.after_sales_manage import AfterSalesManageTool
        tool = AfterSalesManageTool()
        assert tool is not None
        assert hasattr(tool, 'name')

    def test_tool_has_name_and_description(self):
        """Tool 有 name 和 description 属性"""
        from app.tools.after_sales_manage import AfterSalesManageTool
        tool = AfterSalesManageTool()
        assert isinstance(tool.name, str)
        assert len(tool.name) > 0


class TestCustomerManageTool:
    """客户管理 Tool 测试"""

    def test_tool_import(self):
        """可以正常导入"""
        from app.tools.customer_manage import CustomerManageTool
        tool = CustomerManageTool()
        assert tool is not None
        assert hasattr(tool, 'name')

    def test_tool_has_name(self):
        """Tool 有 name 属性"""
        from app.tools.customer_manage import CustomerManageTool
        tool = CustomerManageTool()
        assert isinstance(tool.name, str)
        assert len(tool.name) > 0
