# case_ids: MC-351
"""只读流式探针 `/internal/stream-probe`（M1-b / issue #9098）。

## 它为什么存在（问题不是「不够优雅」）

M1-b 的判据原来只有**静态配置**（`--timeout-graceful-shutdown 200` / `stop_grace_period`）：
能证明「配了」，**不能**证明「SIGTERM 下正在生成的 SSE 流真的收尾了」。而真正会写库的
`/api/chat/send` 不能当探针（要鉴权 + **落库** + 调 LLM）⇒ 「发布期长流是否被切断」这条读数
一直**不可判定**。本端点就是那条可重复、零写的探针。

## 判据面（每条都能被「把实现删掉」打红）

| # | 判据 | 红证注入（改哪一处 ⇒ 红） |
|---|---|---|
| 1 | 缺 `X-Service-Token` ⇒ **401**（不许匿名可达） | 摘掉 `Depends(verify_service_token)` ⇒ 200 ⇒ 红 |
| 2 | token 错 ⇒ **401**（只判「头存在」不算） | 只判非空不判值 ⇒ 红 |
| 3 | `seconds` 夹到 **200** 上限，且**先发一条 `event: notice`** 自报（不静默） | 去掉夹取 / 去掉 notice ⇒ 红 |
| 4 | `seconds=0` / 负数 ⇒ 夹到 **1**（不许出现 0 长度空流） | 用 `max(0, …)` ⇒ 空流 ⇒ 红 |
| 5 | 正常调用：`content-type` 是 `text/event-stream`，且**至少一条** `event: ping` | 换成 JSON 响应 ⇒ 红 |
| 6 | 客户端断开（`is_disconnected()` 为真）⇒ **立刻**结束，不把剩下的时长跑完 | 不判断开 ⇒ 红 |

## 为什么用「模块级事件生成器 + 路由只拼响应」

`seconds=200` 这条流**不能**在 HTTP 层被完整消费（要真等 200s）⇒ 夹取 / notice / 断开这三条判据
驱动模块级 `_probe_events()` / `_probe_limit()`（同一份实现，路由也是调它们）：
判据测的不是「另写的一份逻辑」，HTTP 层只补「鉴权 + content-type + 真的在发 ping」。

## 边界（照实登记）

- 全本地事件流：**不连 DB / Redis / LLM**，零网络、零配额（心跳间隔在本文件里 patch 成 0）；
- 本文件只证**端点语义**：真机读数（切换期长流在 SIGTERM / upstream 切换下是否收尾）由
  `docs/deployment/zero-downtime-release.md` 的 M1-b「真机读数」表承载（本 PR **未填**）。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import create_app

#: 与 `tests/conftest.py` 的 `os.environ.setdefault("SERVICE_TOKEN", "test-service-token")` 同源
TOKEN = "test-service-token"
URL = "/internal/stream-probe"


@pytest.fixture(autouse=True)
def _instant_heartbeat(monkeypatch):
    """心跳间隔 patch 成 0：否则每条用例都要真等 N 秒（判据不该挂挂钟时长）。"""
    monkeypatch.setattr(main_module, "STREAM_PROBE_INTERVAL_SECONDS", 0)


@pytest.fixture()
def client() -> TestClient:
    """不用上下文管理器 ⇒ 不跑 lifespan（不初始化 DB / Redis，也不起后台会话扫描）。"""
    return TestClient(create_app())


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"X-Service-Token": token}


async def _collect(limit: int, requested: int, *, disconnected: bool = False) -> list[str]:
    async def _is_disconnected() -> bool:
        return disconnected

    return [chunk async for chunk in main_module._probe_events(limit, requested, _is_disconnected)]


# ── 判据 1 / 2：鉴权（缺 / 错都不许放行）────────────────────────────────────────

def test_missing_service_token_is_401(client: TestClient):
    response = client.get(URL)
    assert response.status_code == 401, (
        f"匿名请求 `/internal/stream-probe` 竟返回 {response.status_code} ⇒ 只读探针也不许匿名可达"
    )
    assert "AUTH_REQUIRED" in response.text, response.text


def test_wrong_service_token_is_401(client: TestClient):
    response = client.get(URL, headers=_auth("not-the-token"))
    assert response.status_code == 401, (
        f"错 token 竟返回 {response.status_code} ⇒ 鉴权只判了「头存在」没判值"
    )


# ── 判据 3 / 4：时长夹取 + 夹取必须**自报**（不静默）───────────────────────────

def test_seconds_above_max_is_clamped_to_the_shared_budget():
    assert main_module._probe_limit(999) == main_module.STREAM_PROBE_MAX_SECONDS == 200, (
        "上限必须夹到 200 —— 与 nginx `worker_shutdown_timeout 200s` / uvicorn "
        "`--timeout-graceful-shutdown 200` 同一个预算"
    )


def test_clamped_duration_is_announced_before_any_ping():
    chunks = asyncio.run(_collect(200, 999))
    assert chunks, "夹取后一条事件都没有"
    assert "event: notice" in chunks[0], f"被夹取时第一个事件必须是 notice（自报），实测：{chunks[0]!r}"
    assert "clamped to 200" in chunks[0], f"notice 没说清夹到多少：{chunks[0]!r}"


def test_seconds_below_floor_is_clamped_to_one():
    assert main_module._probe_limit(0) == 1, "`seconds=0` 必须夹到 1（否则是一条什么都不发就结束的空流）"
    assert main_module._probe_limit(-5) == 1, "负数同样夹到 1"
    chunks = asyncio.run(_collect(1, 0))
    assert "event: notice" in chunks[0] and "clamped to 1" in chunks[0], f"下限夹取没有自报：{chunks[0]!r}"


# ── 判据 5：真的是一条心跳流（HTTP 层）────────────────────────────────────────

def test_http_stream_emits_pings_and_is_sse(client: TestClient):
    with client.stream("GET", f"{URL}?seconds=2", headers=_auth()) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream"), (
            f"响应类型是 {response.headers.get('content-type')!r}，不是 SSE"
        )
        text = "\n".join(response.iter_lines())
    assert text.count("event: ping") >= 1, f"两秒的探针里一条 `event: ping` 都没有：{text!r}"


# ── 判据 6：断开 ⇒ 立刻结束（不把上限时长跑完）────────────────────────────────

def test_disconnect_ends_the_stream_immediately():
    chunks = asyncio.run(_collect(200, 200, disconnected=True))
    assert chunks == [], (
        "客户端已断开，生成器却还在发事件（会把上限 200s 跑完）⇒ `is_disconnected()` 没接进生成器"
    )
