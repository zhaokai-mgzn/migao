"""
Contract test fixtures — 抓取本地 admin-api 响应快照。

使用方式：
1. 启动本地 admin-api: cd backend/admin-api && ./mvnw spring-boot:run
2. 运行: pytest tests/contracts/ -v

快照缓存在 tests/contracts/snapshots/ 下，提交到 git。
CI 跑缓存的快照，不依赖本地服务。
"""

import json
import os
import pytest
import httpx

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
ADMIN_API = "http://localhost:8081"
SERVICE_TOKEN = "f4ac825ebdf8900b7b2fbcc13af93b29f352264823a3bf9a8098e7155a6961a8b"

os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def _load_snapshot(name: str) -> dict:
    path = os.path.join(SNAPSHOT_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_snapshot(name: str, data: dict) -> None:
    path = os.path.join(SNAPSHOT_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _fetch(endpoint: str, params: dict = None) -> dict:
    """从本地 admin-api 获取响应，失败时回退到缓存快照。"""
    headers = {
        "X-Service-Token": SERVICE_TOKEN,
        "X-Tenant-Id": "1",
    }
    snapshot_key = endpoint.replace("/", "_").lstrip("_")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{ADMIN_API}{endpoint}",
                params=params or {},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                _save_snapshot(snapshot_key, data)
                return data
            else:
                print(f"[contract] {endpoint} → {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[contract] {endpoint} → {e}")

    # Fallback to cached snapshot
    return _load_snapshot(snapshot_key)


# ═══════════════════════════════════════════════════════════════════
# Fixtures — 每个核心端点一个 fixture
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def products_response():
    return await _fetch("/api/admin/products", {"page": 1, "size": 5})


@pytest.fixture(scope="module")
async def orders_response():
    return await _fetch("/api/admin/orders", {"page": 1, "size": 5})


@pytest.fixture(scope="module")
async def customers_response():
    return await _fetch("/api/admin/customers", {"page": 1, "size": 5})


@pytest.fixture(scope="module")
async def after_sales_response():
    return await _fetch("/api/admin/after-sales", {"page": 1, "size": 5})


@pytest.fixture(scope="module")
async def processing_items_response():
    return await _fetch("/api/admin/processing-items", {"page": 1, "size": 20, "status": "active"})


@pytest.fixture(scope="module")
async def categories_tree_response():
    return await _fetch("/api/admin/categories/tree")


@pytest.fixture(scope="module")
async def dashboard_stats_response():
    return await _fetch("/api/admin/dashboard/stats")


@pytest.fixture(scope="module")
async def settings_response():
    return await _fetch("/api/admin/settings")
