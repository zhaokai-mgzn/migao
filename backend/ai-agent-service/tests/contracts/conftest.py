"""
Contract test fixtures — 抓取本地 admin-api 响应快照。

使用方式：
1. 启动本地 admin-api: cd backend/admin-api && ./mvnw spring-boot:run
2. 运行: pytest tests/contracts/ -v

快照缓存在 tests/contracts/snapshots/ 下，提交到 git。
CI 跑缓存的快照，不依赖本地服务。

⚠️ **本文件写出的两类东西，语义完全不同**（issue #5474）：
- `snapshots/*.json` —— 抓到的**数据**（天天变，正常）；
- `snapshot-contract-fingerprints.json` —— 抓取时刻的**契约指纹**（键集现算自 Java 源码）。
  它回答「这次抓取对应哪一版契约」；契约键集变了而指纹没跟 ⇒
  `tests/test_contract_snapshot_freshness.py` 判红（这就是 2026-07-19 那批快照
  「契约变了没人重抓、且没有任何东西变红」的缺失判据）。
"""

import json
import os
import pytest
import httpx

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
ADMIN_API = "http://localhost:8081"
SERVICE_TOKEN = "f4ac825ebdf8900b7b2fbcc13af93b29f352264823a3bf9a8098e7155a6961a8b"

os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def _save_contract_fingerprint() -> None:
    """真实抓取成功时刷新契约指纹（best-effort：指纹写失败绝不能影响抓取本身）。

    ⚠️ 只在 **200** 分支调用 —— 回退路径（`_load_snapshot`）**不写任何文件**，
    这正是「移走旧快照后文件仍被重建 ⇒ 只可能来自线上 200」那条证据成立的原因。
    """
    try:
        from tests import contract_snapshot_registry

        contract_snapshot_registry.write_fingerprint()
    except Exception as exc:  # pragma: no cover - 环境缺 Java 源码时不该拖垮抓取
        print(f"[contract] 契约指纹未能刷新（不影响抓取结果）：{exc}")


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
                _save_contract_fingerprint()
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
