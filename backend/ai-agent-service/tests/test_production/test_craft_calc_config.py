"""算料公式**租户级配置**的引擎侧接线（issue #4528 = 包 E，依赖包 D #4527）。

## 本文件守什么

包 D（#4527）已把公式参数做成「**可注入 + 默认值**」（`curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`），
但没有消费者 —— 商家改不了口径。本包把它接到**租户级配置**上：admin-api 读本租户配置
（`craft_calc_configs` 单行表；缺行 ⇒ 用默认值）后，随算料请求传给 ai-agent。

引擎侧只有两件**必要接线**（不得再多，`backend/ai-agent-service/**` 本轮冻结）：

1. `POST /api/internal/production/craft-calc` 接受 `config` 并**逐值**交给算料引擎
   （配置在 Java 侧不落第二份算料逻辑 —— 唯一实现在 `curtain_calc.py`）；
2. `GET /api/internal/production/craft-calc-config` 回**引擎默认值**：缺配置行的租户要显示
   「当前用系统默认值」，而 Java 侧再抄一份默认常量 = **第二份会漂的默认值**
   （issue #4528 明确「不做开租播种」，同理不抄第二份）⇒ 默认值的唯一来源仍是引擎。

## 判据（期望值全部**写死**，不从实现推导 —— 从实现推导的断言不会红）

| # | 判据 | 红证（实现前/改坏后） |
|---|---|---|
| 1 | 缺 `config` ⇒ 与包 D 默认结果**逐值相同**（13.3 米） | 端点把 `config` 写死成某个非默认值 ⇒ 红 |
| 2 | 传 `config.margin_multi=0.5` ⇒ 折数法用料 13.3 → **13.5** | `config` 被忽略 ⇒ 仍 13.3 ⇒ 红 |
| 3 | 传 `config.per_fold_mixed_times={"1":0.5}` + 拼1次 ⇒ **26.3**（不是 34.1 / 不是 13.3） | ①忽略配置 ⇒ 34.1；②键没归一成 int ⇒ 引擎 `ValueError` ⇒ 400 |
| 4 | 传 `config.tiers.standard.fullness=2.2` ⇒ 折数/用料随档位变（**14.8**，不是 13.3） | 档位配置不生效 ⇒ 13.3 ⇒ 红 |
| 5 | 非法配置（`min_fullness=0`）⇒ **400**（不静默回退默认值） | 静默用默认值算出一个数 ⇒ 200 ⇒ 红 |
| 6 | 模块级默认**不被污染**：自定义配置调用后，`DEFAULT_CRAFT_CALC_CONFIG` 逐值不变 + 下一次不传配置仍 13.3 | 实现里 `cfg = DEFAULT; cfg.update(config)`（模块级可变全局）⇒ 红 |
| 7 | **不跨租户串**：连续两次不同配置各自正确（A 的 13.5 / B 的 13.3 各归各） | 全局变量实现 ⇒ 第二次拿到第一次的值 ⇒ 红 |
| 8 | `GET .../craft-calc-config` 回**引擎默认值**（逐键写死比对 + 键集 == 引擎键集） | 端点自造一份默认（少/多键、值不同）⇒ 红 |

判据 6/7 是同一根因（模块级可变全局 ⇒ 并发请求互相污染）的两面：
6 看**常量本体**有没有被改，7 看**两次调用的结果**有没有互相串。
"""

# case_ids: OR-041

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.tools import curtain_calc

CALC_ENDPOINT = "/api/internal/production/craft-calc"
CONFIG_ENDPOINT = "/api/internal/production/craft-calc-config"

# 冻结样例（与包 D `tests/test_production/test_craft_calc.py` 同口径）：
# 6.6m 窗 / 2.5m 高 / 双开 / 韩褶 / 标准档 / 韩折公式 ⇒ 52 折 / 13.3 米（默认配置）。
FROZEN = {"width": 6.6, "height": 2.5, "open_count": 2, "mounting": "s_hook",
          "craft_tier": "standard", "formula": "pleat"}

# 拼色·拼1次（同一扇窗）：默认每折吃布 0.65 ⇒ 0.65×52+0.3 = 34.1 米
FROZEN_MIXED = {**FROZEN, "style": "拼色", "special_options": ["拼1次"]}


@pytest.fixture
def client():
    """本地 TestClient（与 `test_production/test_craft_calc.py` 同款 fixture）。"""
    from fastapi.testclient import TestClient

    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock):
        from app.main import create_app
        with TestClient(create_app()) as c:
            yield c


def _post(client, payload, token=settings.SERVICE_TOKEN):
    headers = {} if token is None else {"X-Service-Token": token}
    return client.post(CALC_ENDPOINT, headers=headers, json=payload)


def _meters(client, payload):
    resp = _post(client, payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["fabric_meters"]


def _defaults_fingerprint():
    """引擎默认配置的**内容指纹**（判据 6：调用后不得被就地改写）。"""
    return json.dumps(dict(curtain_calc.DEFAULT_CRAFT_CALC_CONFIG), sort_keys=True, ensure_ascii=False)


class TestConfigPassthrough:
    """判据 1~4：配置真的进了算料引擎（不是被丢掉、不是被静默替换）。"""

    def test_no_config_equals_package_d_default(self, client):
        """判据 1：不传配置 ⇒ 与包 D 的默认结果**逐值相同**（13.3 米 / 52 折）。

        未配置租户必须与包 D 合并后的默认结果一致（issue #4528 判据 5）——
        这条是那条判据在引擎侧的一半。
        """
        resp = _post(client, FROZEN)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fabric_meters"] == 13.3
        assert data["pleat_count"] == 52
        assert data["margin"] == 0.3

    def test_margin_config_changes_meters(self, client):
        """判据 2：`margin_multi` 0.3 → 0.5 ⇒ 13.3 → **13.5**（0.25×52+0.5）。

        红证：配置被忽略 ⇒ 仍 13.3 ⇒ 红（改配置不生效 = 商家白改）。
        """
        assert _meters(client, FROZEN) == 13.3
        assert _meters(client, {**FROZEN, "config": {"margin_multi": 0.5}}) == 13.5

    def test_mixed_per_fold_config_uses_string_keys(self, client):
        """判据 3：拼1次系数 0.65 → 0.5 ⇒ **26.3** 米（0.5×52+0.3）。

        ⚠️ 配置在**线上是 JSON**：对象键恒为字符串（`{"1": 0.5}`），而引擎的
        `per_fold_mixed_times` 键必须是**正整数拼次**（`{1: 0.5}`，`resolve_craft_calc_config`
        逐键校验 `isinstance(int)`）⇒ 端点必须做键归一。
        红证（不归一）：引擎 `ValueError` ⇒ 400（不是 200/26.3）；
        红证（配置被忽略）：退回单色系数 0.25 ⇒ 13.3；红证（用默认系数）：34.1。
        """
        assert _meters(client, FROZEN_MIXED) == 34.1
        assert _meters(client, {**FROZEN_MIXED, "config": {"per_fold_mixed_times": {"1": 0.5}}}) == 26.3

    def test_tier_config_changes_pleats(self, client):
        """判据 4：标准档 fullness 2.0 → 2.2 ⇒ 折数/用料随档位变（**14.8** 米 / 58 折）。

        折数 = `round((6.6×2.2 − 0.3) / 0.25)` = 57 ⇒ 双开取整到 58 ⇒ `0.25×29+0.15` = 7.4/片 ⇒ 14.8 米。
        红证：档位配置不生效 ⇒ 13.3 ⇒ 红。
        """
        resp = _post(client, {**FROZEN, "config": {"tiers": {
            "standard": {"fullness": 2.2, "label": "标准工艺"},
            "economy": {"fullness": 1.8, "label": "经济工艺"},
        }}})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fabric_meters"] == 14.8
        assert data["pleat_count"] == 58
        assert data["fullness"] == 2.2

    def test_invalid_config_is_rejected_not_silently_defaulted(self, client):
        """判据 5：非法配置（`min_fullness=0`）⇒ **400**，**不得**静默回退默认值。

        静默回退 = 商家以为改了、系统按默认算 ⇒ 算错钱且无人知道（issue #4528 护栏）。
        红证：静默回退 ⇒ 200 + 13.3 ⇒ 红。
        """
        resp = _post(client, {**FROZEN, "config": {"min_fullness": 0}})
        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"]["error"]["code"] == "CRAFT_CALC_INVALID_INPUT"

    def test_unparseable_mixed_times_key_is_rejected(self, client):
        """判据 3 的负例：拼次键不是整数（`"一次"`）⇒ **400**，不得静默丢档。

        丢一档 = 拼色退回单色系数 = 少算用料（正是本包要防的静默失效）。
        """
        resp = _post(client, {**FROZEN_MIXED, "config": {"per_fold_mixed_times": {"一次": 0.5}}})
        assert resp.status_code == 400, resp.text


class TestNoGlobalPollution:
    """判据 6/7：配置**不得**进模块级可变全局（并发/重复请求互相污染）。"""

    def test_module_default_not_mutated_by_custom_config(self, client):
        """判据 6：自定义配置调用后，引擎默认配置**逐值不变**，且不传配置仍 13.3。

        红证：实现写成 `cfg = DEFAULT_CRAFT_CALC_CONFIG; cfg.update(config)` ⇒
        ① 指纹变化 ⇒ 红；② 第二次调用（不传配置）拿到 13.5 ⇒ 红。
        """
        before = _defaults_fingerprint()
        assert _meters(client, {**FROZEN, "config": {"margin_multi": 0.5}}) == 13.5
        assert _defaults_fingerprint() == before, "引擎默认配置被就地改写了（模块级可变全局）"
        assert _meters(client, FROZEN) == 13.3, "前一次的自定义配置污染了后一次请求"

    def test_two_tenants_do_not_share_config(self, client):
        """判据 7：连续两次不同配置**各归各**（A 的余量不泄漏到 B）。

        红证：全局变量实现 ⇒ 第二次拿到 A 的 13.5 ⇒ 红。
        """
        tenant_a = _meters(client, {**FROZEN, "config": {"margin_multi": 0.5}})
        tenant_b = _meters(client, {**FROZEN, "config": {"margin_multi": 0.2}})
        assert tenant_a == 13.5
        assert tenant_b == 13.2   # 0.25×52+0.2 = 13.2
        assert _meters(client, FROZEN) == 13.3


class TestEngineDefaultsEndpoint:
    """判据 8：默认值只有一个来源 —— 引擎常量（Java 侧不抄第二份）。"""

    def test_returns_engine_defaults(self, client):
        """逐键写死比对（**不从实现推导**：这些值来自真值源 / 包 D 既有常量）。"""
        resp = client.get(CONFIG_ENDPOINT, headers={"X-Service-Token": settings.SERVICE_TOKEN})
        assert resp.status_code == 200, resp.text
        config = resp.json()["data"]["config"]
        assert config["per_fold_single"] == 0.25
        assert config["per_fold_mixed_times"] == {"1": 0.65, "2": 1.2}
        assert config["margin_single"] == 0.2
        assert config["margin_multi"] == 0.3
        assert config["min_fullness"] == 1.5
        assert config["tiers"]["standard"]["fullness"] == 2.0
        assert config["tiers"]["economy"]["fullness"] == 1.8
        assert config["default_formula"] == "pleat"
        assert config["side_margin"] == 0.3
        assert config["meters_rounding_step"] == 0.1

    def test_key_set_equals_engine_key_set(self, client):
        """键集**恰好**等于引擎配置的键集（多一个/少一个 ⇒ 红）。

        红证：端点在引擎默认值之外自造键（如设计文档 §4.2 提案里的 `default_fabric_width`，
        实现里**不存在**）⇒ 红；漏掉一个键 ⇒ 红。
        """
        resp = client.get(CONFIG_ENDPOINT, headers={"X-Service-Token": settings.SERVICE_TOKEN})
        config = resp.json()["data"]["config"]
        assert set(config) == set(curtain_calc.DEFAULT_CRAFT_CALC_CONFIG)
        assert "default_fabric_width" not in config, (
            "设计文档 §4.2 提案键，实现里不存在（以代码事实为准）—— 端点不得凭空补键"
        )

    def test_requires_service_token(self, client):
        """无 Service Token ⇒ 401（与既有内部端点同款）。"""
        assert client.get(CONFIG_ENDPOINT).status_code == 401
