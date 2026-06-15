"""统一 API 响应模型测试 — 验证 make_response 与 Java ApiResponse 格式对齐"""
import pytest
from app.api.response_models import make_response, ErrorDetail, ErrorInfo


class TestMakeResponse:
    """make_response 格式验证"""

    def test_success_response(self):
        """成功响应含 success/data/requestId/timestamp"""
        resp = make_response(True, data={"id": "123", "name": "test"})
        assert resp["success"] is True
        assert resp["data"] == {"id": "123", "name": "test"}
        assert "requestId" in resp
        assert resp["requestId"].startswith("req_")
        assert "timestamp" in resp
        assert isinstance(resp["timestamp"], int)
        assert "error" not in resp

    def test_error_response(self):
        """错误响应含 error.code 和 error.message"""
        resp = make_response(False, error_code="NOT_FOUND", error_message="商品不存在")
        assert resp["success"] is False
        assert resp["data"] is None
        assert resp["error"]["code"] == "NOT_FOUND"
        assert resp["error"]["message"] == "商品不存在"

    def test_error_response_no_code(self):
        """无 error_code 时不含 error 字段"""
        resp = make_response(True, data="ok")
        assert "error" not in resp

    def test_request_id_unique(self):
        """每次调用生成不同的 requestId"""
        ids = {make_response(True)["requestId"] for _ in range(10)}
        assert len(ids) == 10  # 全部唯一

    def test_timestamp_monotonic(self):
        """timestamp 随调用递增"""
        t1 = make_response(True)["timestamp"]
        import time
        time.sleep(0.1)
        t2 = make_response(True)["timestamp"]
        assert t2 >= t1


class TestErrorModels:
    """ErrorDetail / ErrorInfo Pydantic 模型"""

    def test_error_detail(self):
        d = ErrorDetail(field="phone", message="手机号不能为空")
        assert d.field == "phone"
        assert d.message == "手机号不能为空"

    def test_error_info_no_details(self):
        info = ErrorInfo(code="VALIDATION_ERROR", message="参数校验失败")
        assert info.code == "VALIDATION_ERROR"
        assert info.details is None

    def test_error_info_with_details(self):
        info = ErrorInfo(
            code="VALIDATION_ERROR",
            message="参数校验失败",
            details=[ErrorDetail(field="phone", message="必填")],
        )
        assert len(info.details) == 1
        assert info.details[0].field == "phone"
