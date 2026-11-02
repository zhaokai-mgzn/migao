# case_ids: MC-124
"""构建身份探针 `/version` / `/api/version` 的三态语义（issue #8203 · P0-04）。

## 病（改前，durable 读数）

审计 P1-01：`https://ai-api.migaozn.com/api/version|/version|/build-info` **全 404**
⇒ ai-agent 线上「跑的是哪个 commit」**不可判定**、发布漂移不可发现（与 admin-api 的
`/api/version` 同名面缺失）。而部署镜像里**没有 `.git`**（C′ 服务器侧构建的上下文是 codeload 归档树）
⇒ 任何运行期 `git rev-parse` 都是错的，取值只能来自**构建期注入**。

## 判据面

| # | 判据 | 会红的注入 |
|---|---|---|
| 1 | 两个路径 `/version` 与 `/api/version` 都 200，且**同一个响应**（一条命名口径） | 只挂一个路径 ⇒ 红 |
| 2 | 响应体**恰好 3 个字段** `app` / `sha` / `builtAt`（白名单；多一个字段就要重新过「会不会泄露」） | 多带 host / env / 依赖版本 ⇒ 红 |
| 3 | **空 sha**（未注入 / 老镜像）⇒ 空串，**不伪造** `unknown` / `null` / `0`（= 探不到） | 填 `unknown` ⇒ 红（会被读成「有身份但不一致」） |
| 4 | **非空 sha** ⇒ 原样回显（一致时消费方判绿；不一致时消费方判红 —— 端点不替消费方裁决） | 截断 / 归一化 / 大小写化 ⇒ 红 |
| 5 | 空白填充被 strip（`"  abc  "` ⇒ `"abc"`）；全空白 ⇒ 空串 | 不 strip ⇒ 前端拼进日志后有幽灵空格 ⇒ 红 |
| 6 | 默认配置项就是空串（未注入时**天然**是「探不到」，不是 `unknown`） | 默认值改成 `unknown` ⇒ 红 |

## 边界（照实登记）

- 本判据证的是**端点语义**，不证「线上真的注入了 sha」：那要部署后打真机
  （`python3 scripts/synthetic_probe.py` 的 `admin-api /api/version` 面同形；ai-agent 面见
  `docs/deployment/observability-minimum.md` 的复算命令）。
- 构建期注入链路（workflow `--build-arg` ⇒ Dockerfile `ARG`/`ENV` ⇒ `Settings`）由
  `tests/unit_ci_workflows/test_synthetic_probe.py` 的接线段判据覆盖。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings


def _app_with(monkeypatch: pytest.MonkeyPatch, sha: str, built_at: str):
    """用给定的构建身份建一个 app（不启 lifespan：`TestClient(app)` 不上下文管理就不跑 startup）。"""
    fake_settings = SimpleNamespace(
        APP_NAME="ai-agent-service",
        APP_VERSION="1.0.0",
        DEBUG=True,
        API_PREFIX="/api",
        CORS_ALLOWED_ORIGINS="http://localhost:3001",
        MIGAO_BUILD_SHA=sha,
        MIGAO_BUILT_AT=built_at,
    )
    monkeypatch.setattr(main_module, "settings", fake_settings)
    return main_module.create_app()


@pytest.mark.parametrize("path", ["/version", "/api/version"])
def test_both_paths_report_the_build_identity(monkeypatch, path):
    """判据 1/2/4：两个路径都 200，且只有 3 个字段（含原样回显的 sha）。"""
    app = _app_with(monkeypatch, "6f3aec2b" + "0" * 32, "2026-10-31T01:02:03Z")

    body = TestClient(app).get(path).json()

    assert set(body) == {"app", "sha", "builtAt"}
    assert body == {
        "app": "ai-agent-service",
        "sha": "6f3aec2b" + "0" * 32,
        "builtAt": "2026-10-31T01:02:03Z",
    }


def test_两个路径是同一个响应(monkeypatch):
    """判据 1：`/version` 与 `/api/version` 不能各说各话（运维/探针只有一条命名口径）。"""
    app = _app_with(monkeypatch, "abc1234", "2026-10-31T01:02:03Z")
    client = TestClient(app)

    assert client.get("/version").json() == client.get("/api/version").json()


def test_missing_identity_means_empty_not_fabricated(monkeypatch):
    """判据 3：未注入 ⇒ **空串**（探不到），不是 `unknown` / `null` / `0`。

    三态语义里 `sha=""` 必须能被消费方读成「探不到」—— 填 `unknown` 会让消费方把它当
    「有身份但不一致」判红（假红），或反过来当「一致」判绿（假绿）。
    """
    app = _app_with(monkeypatch, "", "")

    body = TestClient(app).get("/api/version").json()

    assert body["sha"] == ""
    assert body["builtAt"] == ""
    assert body["sha"] != "unknown"
    assert body["sha"] is not None
    assert body["sha"] != "0"


def test_identity_is_echoed_verbatim(monkeypatch):
    """判据 4：非空 sha 原样回显（端点不替消费方裁决「一致 / 不一致」）。"""
    sha = "deadbeef" * 5  # 40 位 hex，与 `git rev-parse HEAD` 同形
    app = _app_with(monkeypatch, sha, "2026-10-31T09:00:00Z")

    body = TestClient(app).get("/version").json()

    assert body["sha"] == sha
    # 负控：不一致时必须**看得出**不一致（端点不许截断成 7 位或做大小写归一）
    assert body["sha"] != sha[:7]
    assert body["sha"].lower() == body["sha"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  abc1234  ", "abc1234"),
        ("\tabc1234\n", "abc1234"),
        ("   ", ""),
        ("", ""),
    ],
)
def test_whitespace_is_stripped(monkeypatch, raw, expected):
    """判据 5：空白填充被 strip；全空白 ⇒ 空串（不是 `"   "` 被原样吐给消费方）。"""
    app = _app_with(monkeypatch, raw, raw)

    body = TestClient(app).get("/api/version").json()

    assert body["sha"] == expected
    assert body["builtAt"] == expected


def test_config_defaults_are_empty_strings():
    """判据 6：默认值就是空串 —— 「取不到 = 探不到」，不伪造身份。"""
    assert Settings.model_fields["MIGAO_BUILD_SHA"].default == ""
    assert Settings.model_fields["MIGAO_BUILT_AT"].default == ""
