"""
冒烟测试工具函数
"""

import time
from typing import Any, Dict, List, Optional

import httpx


class SmokeTestClient:
    """封装 httpx 的测试客户端，支持认证和响应断言"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    @property
    def auth_headers(self) -> Dict[str, str]:
        """获取认证头"""
        if not self._access_token:
            return {}
        return {"Authorization": f"Bearer {self._access_token}"}

    def set_token(self, access_token: str, refresh_token: Optional[str] = None):
        """设置认证 Token"""
        self._access_token = access_token
        self._refresh_token = refresh_token

    def clear_token(self):
        """清除认证 Token"""
        self._access_token = None
        self._refresh_token = None

    def get(self, path: str, **kwargs) -> httpx.Response:
        """发送 GET 请求"""
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        return self._client.get(
            f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def post(self, path: str, **kwargs) -> httpx.Response:
        """发送 POST 请求"""
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        return self._client.post(
            f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def put(self, path: str, **kwargs) -> httpx.Response:
        """发送 PUT 请求"""
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        return self._client.put(
            f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def delete(self, path: str, **kwargs) -> httpx.Response:
        """发送 DELETE 请求"""
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        return self._client.delete(
            f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def stream_post(self, path: str, **kwargs):
        """发送 SSE 流式 POST 请求"""
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        headers["Accept"] = "text/event-stream"
        return self._client.stream(
            "POST", f"{self.base_url}{path}", headers=headers, **kwargs
        )

    def close(self):
        """关闭客户端"""
        self._client.close()


def assert_success_response(resp: httpx.Response, status_code: int = 200) -> Dict[str, Any]:
    """断言成功响应格式"""
    assert resp.status_code == status_code, (
        f"Expected {status_code}, got {resp.status_code}: {resp.text[:500]}"
    )
    data = resp.json()
    # 支持两种格式：{success: true, data: ...} 或 {code: 200, data: ...}
    if "success" in data:
        assert data["success"] is True, f"Response not success: {data}"
    elif "code" in data:
        assert data["code"] == 200 or data["code"] == 0, f"Response code error: {data}"
    return data


def assert_page_response(resp: httpx.Response) -> Dict[str, Any]:
    """断言分页响应格式"""
    data = assert_success_response(resp)
    page_data = data.get("data", data)
    # 验证分页字段
    assert "total" in page_data or "items" in page_data or "records" in page_data, (
        f"Missing pagination fields in: {list(page_data.keys())}"
    )
    return data


def measure_time(func):
    """测量函数执行时间（毫秒）"""
    start = time.perf_counter()
    result = func()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms


def parse_sse_events(response_text: str) -> List[Dict[str, Any]]:
    """解析 SSE 事件流"""
    import json
    events = []
    current_event = None
    current_data = []

    for line in response_text.split("\n"):
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            current_data.append(line[5:].strip())
        elif line == "" and current_event:
            data_str = "\n".join(current_data)
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = data_str
            events.append({"event": current_event, "data": data})
            current_event = None
            current_data = []

    return events
