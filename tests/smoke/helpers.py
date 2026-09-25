"""
冒烟测试工具函数

⚠️ 请求层带**有界瞬态重试**（issue #4182）：`502`/`503`/`504` 与传输层断开会被当作
"服务还没就绪"等待重试；而 `500` / `401` / 真断言失败**照旧当场红**。
策略与预算（尝试次数 / 等待 / 会话上限）单点在 `retry_policy.py`，
判据在 `tests/unit_ci_workflows/test_smoke_transient_retry.py`。
"""

import time
from typing import Any, Dict, List, Optional

import httpx

from .retry_policy import SESSION_LEDGER, TransientRetrier, is_transient_status


class SmokeTestClient:
    """封装 httpx 的测试客户端，支持认证和响应断言"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        #: 瞬态重试器（预算走**会话级**账本 —— 两个 client 共用同一份上限）
        self._retrier = TransientRetrier()

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

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """**所有动词的唯一出口**：瞬态签名（502/503/504 与传输层断开）走有界等待重试。

        非瞬态（含 500）立即返回 ⇒ 断言照旧执行；重试耗尽 ⇒ 把**最后一次**的响应/异常
        原样交出去 ⇒ 该红的还是红（不会把 500、也不会把真断言失败"重试"成绿）。
        策略/预算见 `retry_policy.py`；判据见 `tests/unit_ci_workflows/test_smoke_transient_retry.py`。

        ⚠️ 重试会复用 `kwargs`（`json=` / `params=` 可安全重发）；流式 `stream_post` **不走**这里
        （`httpx` 的流式接口是一次性上下文管理器，重发要重开会话）—— P0 档不消费它。
        """
        url = f"{self.base_url}{path}"
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        return self._retrier.run(
            lambda: self._client.request(method, url, headers=headers, **kwargs)
        )

    def get(self, path: str, **kwargs) -> httpx.Response:
        """发送 GET 请求"""
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        """发送 POST 请求"""
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        """发送 PUT 请求"""
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        """发送 DELETE 请求"""
        return self._request("DELETE", path, **kwargs)

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


def transient_diagnostics(resp: httpx.Response) -> str:
    """瞬态签名下的**可复现最小证据**（issue #4182 第 2 条：现在的失败输出取不到 ⇒ 判不了红）。

    只在 `502`/`503`/`504` 上追加：请求 URL + 本轮重试读数 + 一条可复制的 `curl`。
    非瞬态（含 `500`）返回空串 —— 那种红不需要"部署窗口"叙事，就是需要人读代码/日志。
    """
    if not is_transient_status(resp.status_code):
        return ""
    url = str(getattr(getattr(resp, "request", None), "url", "") or "<未知>")
    return (
        f"\n  ↳ 瞬态签名 HTTP {resp.status_code}：已按 #4182 的策略重试"
        f"（本轮累计重试 {SESSION_LEDGER.retries} 次 / 累计等待 {SESSION_LEDGER.waited:.0f}s，"
        f"会话上限 {SESSION_LEDGER.budget_s:.0f}s）后**仍然**如此"
        f" ⇒ 至少已排除短窗口瞬态，按**回归优先**排查。"
        f"\n  ↳ 最小复现：curl -i -m 10 '{url}'  （需鉴权的接口自行附 header）"
    )


def assert_success_response(resp: httpx.Response, status_code: int = 200) -> Dict[str, Any]:
    """断言成功响应格式（瞬态签名附可复现证据；断言本身**不**重试）"""
    assert resp.status_code == status_code, (
        f"Expected {status_code}, got {resp.status_code}: {resp.text[:500]}"
        + transient_diagnostics(resp)
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
