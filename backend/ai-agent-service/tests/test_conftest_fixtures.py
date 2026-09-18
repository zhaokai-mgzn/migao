"""
tests/test_conftest_fixtures.py — conftest 公用 fixture 的可用性守卫（issue #4227 / #4310）

被守卫的事实（#4227）：`tests/conftest.py` 的 `test_client` fixture 在**进入时**就对若干符号
逐个 `unittest.mock.patch`；`patch` 默认 `create=False` ⇒ **任一目标符号不存在**即当场抛
`AttributeError`（#4227：`app.main.get_rag_pipeline` / `get_vector_store` 已随 V36 RAG 下线移除
⇒ fixture 恒坏 ⇒ 依赖它的"测试通过"是空判据）。所以**消费该 fixture 本身就是全量守卫**。

被守卫的事实（#4310，**本条是本文件后半段用例的存在理由**）：`patch` 的目标必须与
**调用方实际引用的名字同源**。`app/main.py` 在导入期**按值绑定** ——
`from app.utils.database import init_db, close_db`（第 27 行）、
`from app.utils.redis_client import init_redis, close_redis`（第 28 行），lifespan 直接
`await init_db()`（第 96 行）⇒ 它读的是 **`app.main` 模块本地名**。
故 `patch("app.utils.database.init_db")` 只换掉源模块的属性，**不改变 `app.main.init_db`**
（patch 生效期内 `app.main.init_db is app.utils.database.init_db` 变 **False**）⇒ fixture
docstring 宣称的「使用 mock 跳过实际的数据库/Redis 初始化」**实际未达成**：真实 init 被
lifespan 的 `try/except` + `DEBUG=true` 兜住（`/health` 仍 200）⇒ **静默失效**
（看起来 mock 了、其实真连了）。下面 `..._patches_lifespan_call_targets_...` 就是这条的红证。

对齐用例：`.github/cases/misc.yml` MC-009「应用入口 - create_app/健康检查/生命周期」
（data_check：`create_app 返回 FastAPI，/health 返回 status=healthy+service+version；... api_router 挂 API_PREFIX`）。
"""
# case_ids: MC-009

from unittest.mock import Mock

from fastapi.testclient import TestClient

import app.main  # noqa: F401  —— 见下：必须在**进入 fixture 的 patch 之前**导入（前置条件显式化）
from app.config import settings

# ⚠️ 为什么必须在此处显式 `import app.main`（本文件的一条实证，勿删）：
# fixture 在 patch 生效期**内部**才 `from app.main import create_app`。若 `app.main` 尚未被导入，
# 它就会**在 patch 窗口内**首次执行 `from app.utils.database import init_db` ⇒ 拿到的是**mock**
# ⇒ 本文件单跑时 `app.main.init_db` 恰好是 mock（**假绿**），而 patch 退出后这个 mock 会**永久残留**
# 在 `app.main` 上（跨用例污染）。全量跑时 `app.main` 早已被其它测试模块导入（真实绑定）⇒ 才显出
# #4310 的真形态「patch 对 lifespan 无效」。这里把前置条件钉死，让红证与运行顺序无关。


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


# ========== #4310：patch 必须落在 lifespan 实际调用的名字上 ==========

# `app/main.py` 导入期按值绑定后，lifespan 实际调用的是 `app.main.<name>`（模块本地名）。
# 这四个名字是**唯一**的调用点（`grep -rn "init_db()\|close_db()\|init_redis()\|close_redis()" app/`
# 除 `app/main.py` 外只命中函数定义本身）⇒ patch `app.main.*` 即足够、且是**最小面**。
_LIFESPAN_CALL_TARGETS = ("init_db", "close_db", "init_redis", "close_redis")


def test_fixture_patches_lifespan_call_targets_on_app_main(test_client):
    """patch 生效期内，`app.main` 上 lifespan 真正调用的 4 个名字必须**已被替换为 mock**（#4310）。

    红证形态：若 fixture 只 patch 源模块（`app.utils.database.init_db` 等），
    则 `app.main.init_db` 仍是真实函数 ⇒ 本用例在 `isinstance(..., Mock)` 处红，
    并在 `await_count` 处再红一次（真实函数没有 await_count）。
    """
    import app.main as main_module

    for name in _LIFESPAN_CALL_TARGETS:
        on_main = getattr(main_module, name)
        assert isinstance(on_main, Mock), (
            f"patch 生效期内 app.main.{name} 必须是 mock（lifespan 调的就是这个名字，"
            f"只 patch 源模块 app.utils.*.{name} 对 lifespan 无效）；实际 {on_main!r}"
        )

    # 效果层断言（比 isinstance 更强）：lifespan 启动路径**真的** await 了被 patch 的 init_*。
    # 若 patch 没落在 app.main 上，这里读到的是真实函数（无 await_count）⇒ 红。
    for name in ("init_db", "init_redis"):
        assert getattr(main_module, name).await_count >= 1, (
            f"lifespan 启动必须已 await 被 patch 的 app.main.{name}"
            f"（证明 patch 真的作用在调用路径上）；await_count="
            f"{getattr(main_module, name).await_count!r}"
        )


def test_lifespan_patch_targets_restored_after_fixture_exit():
    """反向断言：fixture 退出后 4 个名字必须**还原**为源模块里的真实实现（防「永久替换」）。

    ⚠️ 顺序依赖（照实登记）：本用例只有在 `..._patches_lifespan_call_targets_...` **之后**
    （同文件定义序 = pytest 收集序）运行才真正测到「退出后」的状态；单独运行它是平凡通过，
    因此它只是反向护栏，不单独承担「patch 生效」这一正面判据。
    红证形态：把 fixture 改成永久 `setattr(app.main, name, AsyncMock())`（不还原）⇒ 本用例红。
    """
    import app.main as main_module
    from app.utils import database as db_module
    from app.utils import redis_client as rc_module

    for name in _LIFESPAN_CALL_TARGETS:
        on_main = getattr(main_module, name)
        src = getattr(db_module if name.endswith("_db") else rc_module, name)
        assert not isinstance(on_main, Mock), (
            f"fixture 退出后 app.main.{name} 仍是 mock ⇒ patch 未被还原（永久替换）；实际 {on_main!r}"
        )
        assert on_main is src, (
            f"fixture 退出后 app.main.{name} 必须与源模块同源（同一对象，即导入期按值绑定的原值）；"
            f"实际 {on_main!r} is not {src!r}"
        )
