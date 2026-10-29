# case_ids: PP-023
"""`craft_calc_config_restore` 的行为判据（PP-023 的写方复位手段）。

为什么需要这个夹具动作：`craft_calc_config_update`（issue #7514）改的是**租户级共享配置**，
而 admin-api 的 `PUT /api/admin/production/craft-calc-config` 是 upsert + **全量替换**
⇒ 不复位时同栈按配置算料/省料的用例读到被改过的世界（issue #4075 同族），
且重跑同一用例时 `before` 仍与服务端相符（#3751 的重试前置等价被破坏）。

每条断言都能红（把被测行为改回旧形态即失败）：
1. 只写**声明的键**、其余键逐字保留（`PUT` 全量替换 ⇒ 少带一个键就等于把它清空）；
2. 当前值已等于声明值 ⇒ **不发 PUT**（幂等，不是"每次都写一遍"）；
3. 回读与声明值不符 ⇒ fail-closed（走 `_clean_not_applied` 的稳定标记，不得算成功）；
4. 缺 `keys` ⇒ 配置错误（不得静默跳过 —— 静默跳过 = 夹具脏着、用例照跑）；
5. 数值按容差比较（`0.3` 与 `0.3+1e-12` 视为同值，避免浮点噪声把复位判成失败）。

全部走 mock（`unittest.mock` 替 `httpx.AsyncClient`）—— 不连真 admin-api。
"""
import asyncio
from unittest.mock import patch

import tests.agent_eval.local_runner as lr

PREFIX_POST = "PRECONDITION_NOT_RESTORED"
URL_TAIL = "/api/admin/production/craft-calc-config"


class _Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """最小的 httpx.AsyncClient 替身：GET 返回给定配置，PUT 记录请求体。"""

    def __init__(self, configs, put_ok=True):
        self._configs = list(configs)   # 每次 GET 依次取一份（回读用第二份）
        self._put_ok = put_ok
        self.put_bodies = []
        self.get_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, timeout=None):
        assert url.endswith(URL_TAIL), url
        self.get_calls += 1
        idx = min(self.get_calls - 1, len(self._configs) - 1)
        return _Resp(200, {"success": True, "data": {"source": "stored",
                                                    "config": dict(self._configs[idx])}})

    async def put(self, url, headers=None, json=None, timeout=None):
        assert url.endswith(URL_TAIL), url
        self.put_bodies.append(dict(json or {}))
        return _Resp(200 if self._put_ok else 500, {"success": self._put_ok})


def _run(spec, client):
    with patch.object(lr.httpx, "AsyncClient", lambda *a, **k: client), \
            patch.object(lr, "_admin_headers", lambda token: {"Authorization": token}):
        return asyncio.run(lr._restore_craft_calc_config("tok", spec, "post"))


def test_restores_only_declared_keys_and_keeps_the_rest():
    before = {"hem_margin": 0.3, "margin_single": 0.2, "min_fullness": 1.5}
    after = {**before, "hem_margin": 0.25}
    c = _FakeClient([before, after])
    msg = _run({"keys": {"hem_margin": 0.25}}, c)
    assert c.put_bodies == [{**before, "hem_margin": 0.25}], c.put_bodies
    assert "已复位" in msg and PREFIX_POST not in msg, msg
    assert "margin_single" in c.put_bodies[0] and c.put_bodies[0]["margin_single"] == 0.2


def test_idempotent_when_already_at_target():
    c = _FakeClient([{"hem_margin": 0.3, "margin_single": 0.2}])
    msg = _run({"keys": {"hem_margin": 0.3}}, c)
    assert c.put_bodies == [], "已等于声明值 ⇒ 不得再写"
    assert "幂等" in msg, msg


def test_readback_mismatch_is_visible():
    # PUT 声称 200，但回读仍是旧值 ⇒ 必须判"未生效"（2xx ≠ 值已落地）
    c = _FakeClient([{"hem_margin": 0.3}, {"hem_margin": 0.3}])
    msg = _run({"keys": {"hem_margin": 0.25}}, c)
    assert PREFIX_POST in msg, msg
    assert "未生效" in msg, msg


def test_missing_keys_is_a_config_error():
    c = _FakeClient([{"hem_margin": 0.3}])
    msg = _run({}, c)
    assert PREFIX_POST in msg and "keys" in msg, msg
    assert c.get_calls == 0, "配置错误不得先发请求"


def test_missing_config_payload_is_visible():
    class _Empty(_FakeClient):
        async def get(self, url, headers=None, timeout=None):
            return _Resp(200, {"success": True, "data": {}})

    msg = _run({"keys": {"hem_margin": 0.25}}, _Empty([{}]))
    assert PREFIX_POST in msg and "data.config" in msg, msg


def test_float_noise_counts_as_same_value():
    c = _FakeClient([{"hem_margin": 0.3 + 1e-12}])
    msg = _run({"keys": {"hem_margin": 0.3}}, c)
    assert c.put_bodies == [], "浮点噪声不该触发一次写入"
    assert "幂等" in msg, msg
