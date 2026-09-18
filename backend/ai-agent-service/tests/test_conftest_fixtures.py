"""
tests/test_conftest_fixtures.py — conftest 公用 fixture 的可用性守卫（issue #4227）

被守卫的事实：`tests/conftest.py` 的 `test_client` fixture 在**进入时**就对
`app.utils.database.init_db` / `close_db`、`app.utils.redis_client.init_redis` / `close_redis`、
`app.main.*` 逐个 `unittest.mock.patch`；`patch` 默认 `create=False` ⇒ **任一目标符号不存在**
即当场抛 `AttributeError`（issue #4227：`app.main.get_rag_pipeline` / `get_vector_store`
已随 V36 RAG 下线移除 ⇒ fixture 恒坏 ⇒ 依赖它的"测试通过"是空判据）。

所以**消费该 fixture 本身就是全量守卫**：只要 conftest 里还留着指向已移除符号的 patch，
下面的用例就会在 fixture 建立阶段直接红（`AttributeError: <module 'app.main'> does not exist: ...`），
无需为每个 patch 目标再单写一条断言。

对齐用例：`.github/cases/misc.yml` MC-009「应用入口 - create_app/健康检查/生命周期」
（data_check：`create_app 返回 FastAPI，/health 返回 status=healthy+service+version；... api_router 挂 API_PREFIX`）。
"""
# case_ids: MC-009

from fastapi.testclient import TestClient

from app.config import settings


def test_test_client_fixture_constructs_and_serves_health(test_client):
    """fixture 必须真能构造出可用的 TestClient，并端到端服务 /health（不是只 yield 了个对象）"""
    assert isinstance(test_client, TestClient), "fixture 必须产出 FastAPI TestClient 实例"

    resp = test_client.get("/health")
    assert resp.status_code == 200, f"/health 应 200，实际 {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["status"] == "healthy", f"/health.status 应为 healthy，实际 {body!r}"
    assert body["service"] == settings.APP_NAME, f"/health.service 应为 {settings.APP_NAME}，实际 {body!r}"
    assert body["version"] == settings.APP_VERSION, f"/health.version 应为 {settings.APP_VERSION}，实际 {body!r}"


def test_test_client_fixture_mounts_api_router(test_client):
    """fixture 产出的 app 必须已挂载业务路由（api_router 挂 API_PREFIX），不是空壳 FastAPI"""
    paths = set(test_client.app.openapi()["paths"])
    assert "/health" in paths, f"缺 /health 路由：{sorted(paths)}"
    assert "/api/chat/send" in paths, f"api_router 未挂到 API_PREFIX 下：{sorted(paths)}"
