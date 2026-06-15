"""
统一 API 响应模型

匹配 Java canonical format: ApiResponse<T> { success, data, error, requestId, timestamp }
"""
from typing import Any, Dict, List, Optional
import time
import uuid

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """字段级错误详情 — 匹配 Java ApiResponse.ErrorDetail"""
    field: str = Field(..., description="出错字段名")
    message: str = Field(..., description="字段级错误消息")


class ErrorInfo(BaseModel):
    """错误信息 — 匹配 Java ApiResponse.ErrorInfo"""
    code: str = Field(..., description="错误码 (e.g. VALIDATION_ERROR, NOT_FOUND)")
    message: str = Field(..., description="人类可读错误消息")
    details: Optional[List[ErrorDetail]] = Field(None, description="字段级错误详情")


def make_response(
    success: bool,
    data: Any = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> dict:
    """构建统一 JSON 响应 dict，匹配 Java ApiResponse 格式

    示例:
        make_response(True, data={"id": "123"})
        make_response(False, error_code="NOT_FOUND", error_message="商品不存在")
    """
    resp: Dict[str, Any] = {
        "success": success,
        "data": data,
        "requestId": f"req_{uuid.uuid4().hex[:16]}",
        "timestamp": int(time.time()),
    }
    if not success and error_code:
        resp["error"] = {"code": error_code, "message": error_message or ""}
    return resp
