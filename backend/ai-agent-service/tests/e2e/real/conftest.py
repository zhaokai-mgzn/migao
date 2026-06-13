"""
真实 E2E 公共基础设施 — 零 Mock

每个测试：
  1. 通过 SSE API 与真实 Agent 对话
  2. 真实 LLM 处理 → 真实工具调用 → 真实 admin-api
  3. 通过 admin-api 直接查询验证结果
"""
import json
import os
import time
import pytest
import httpx
import requests

AGENT = os.environ.get("AI_AGENT_URL", "http://localhost:8001")
ADMIN = os.environ.get("ADMIN_API_BASE_URL", "http://localhost:8080")

# Service Token（ai-agent 调用 admin-api 的认证凭据）
# 本地：从 app.config 读取；CI：从 SERVICE_TOKEN 环境变量读取
if os.environ.get("SERVICE_TOKEN"):
    SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]
else:
    import sys; sys.path.insert(0, ".")
    from app.config import settings as _s
    SERVICE_TOKEN = _s.SERVICE_TOKEN
ADMIN_HEADERS = {"X-Service-Token": SERVICE_TOKEN, "X-Tenant-Id": "1"}


# ═══ CI 安全保护 ═══

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_e2e: real LLM E2E tests (requires running ai-agent-service + admin-api + real API tokens)"
    )

@pytest.fixture(autouse=True)
def skip_real_e2e_in_ci(request):
    """在 CI 环境中默认跳过 real_e2e 测试，避免 crash。

    本地运行：直接执行 pytest tests/e2e/real/
    CI 中运行：设置 E2E_REAL_ENABLED=true 指向已部署的服务
    """
    if os.environ.get("CI") and not os.environ.get("E2E_REAL_ENABLED") == "true":
        if request.node.get_closest_marker("real_e2e"):
            pytest.skip("Real E2E disabled in CI (set E2E_REAL_ENABLED=true to run)")


# ═══ SSE 解析 ═══

def parse_sse(raw):
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(": "): continue
        et = dt = None
        for line in block.split("\n"):
            if line.startswith("event: "): et = line[7:]
            elif line.startswith("data: "): dt = line[6:]
        if et and dt:
            try: events.append({"event": et, "data": json.loads(dt)})
            except: events.append({"event": et, "data": dt})
    return events

def sse_text(events):
    return " ".join(e["data"]["content"] for e in events if e["event"] == "text")

def sse_tools(events):
    return [e["data"]["tool"] for e in events if e["event"] == "tool_call"]

def sse_results(events):
    return [e["data"]["result"] for e in events if e["event"] == "tool_result"]


# ═══ 会话管理 ═══

class Session:
    """真实 Agent 会话"""
    def __init__(self):
        self.id = None

    def create(self):
        r = requests.post(f"{AGENT}/api/chat/sessions", json={"title": "E2E"})
        assert r.status_code == 200, f"Create session: {r.text}"
        self.id = r.json()["data"]["id"]
        return self

    def send(self, message, timeout=60):
        """发送消息 → 返回解析后的 SSE 事件"""
        with httpx.Client(timeout=timeout) as c:
            r = c.post(f"{AGENT}/api/chat/send",
                       json={"session_id": self.id, "message": message})
        assert r.status_code == 200, f"Send failed: {r.text[:200]}"
        return parse_sse(r.text)


# ═══ admin-api 验证 ═══

def admin_get(path, params=None):
    r = requests.get(f"{ADMIN}{path}", params=params, headers=ADMIN_HEADERS)
    assert r.status_code == 200, f"Admin API {path}: {r.text[:200]}"
    return r.json()

def admin_search_products(keyword):
    """搜索商品 → 返回 items 列表"""
    data = admin_get("/api/admin/products", {"keyword": keyword, "page": 1, "size": 10})
    return data.get("data", {}).get("items", []) if data.get("success") else []

def admin_search_orders(keyword):
    data = admin_get("/api/admin/orders", {"keyword": keyword, "page": 1, "size": 10})
    return data.get("data", {}).get("items", []) if data.get("success") else []


# ═══ Fixtures ═══

@pytest.fixture
def sess():
    """新会话"""
    return Session().create()
