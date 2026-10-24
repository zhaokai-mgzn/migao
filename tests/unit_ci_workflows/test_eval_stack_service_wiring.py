# case_ids: PP-015
"""评测栈的服务间接线守卫（issue #7027）。

PP-015（算料试算）在 2026-10-19 的 B 端基线里红在
「算料服务（ai-agent）不可用……未配置 ai-agent.service-token」——
**不是 agent 行为缺陷**，而是栈里 admin-api 没配 ai-agent 的地址与令牌：
`backend/admin-api/src/main/resources/application.yml` 的两个默认值都是坏的
（`base-url` = `http://localhost:8000` = 容器内自己；`service-token` = 空）⇒
不给就**静默** fail-closed，而 ai-agent 容器看起来完全健康（AGENTS.md 也记过这个坑）。

判据：`deploy/docker-compose.yml` 的 admin-api 服务必须显式声明这两个键，
且地址指向**服务名**（不是 localhost）、令牌非空。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

COMPOSE_PATH = REPO / "deploy" / "docker-compose.yml"
APP_YML = REPO / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"


def admin_api_env(compose: dict) -> dict:
    """compose 里 admin-api 服务的 environment（形态变化 ⇒ fail-closed）。"""
    svc = (compose.get("services") or {}).get("admin-api") or {}
    env = svc.get("environment") or {}
    assert isinstance(env, dict), f"admin-api.environment 形态变了：{type(env)}"
    return {str(k): str(v) for k, v in env.items()}


def test_admin_api_declares_ai_agent_wiring():
    import yaml

    env = admin_api_env(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")) or {})
    url = env.get("AI_AGENT_BASE_URL", "")
    token = env.get("AI_AGENT_SERVICE_TOKEN", "")
    assert "ai-agent-service" in url and ":8000" in url, (
        f"admin-api 的 AI_AGENT_BASE_URL={url!r} 没指向容器内服务名 ai-agent-service:8000 —— "
        "localhost:8000 在容器里指向它自己，算料桥会静默 fail-closed（PP-015）"
    )
    assert "DEV_SERVICE_TOKEN" in token, (
        f"admin-api 的 AI_AGENT_SERVICE_TOKEN={token!r} 必须取服务间共享令牌（DEV_SERVICE_TOKEN）—— "
        "空/缺省 ⇒「未配置 ai-agent.service-token」（PP-015）"
    )


def test_application_yml_defaults_are_still_the_broken_ones():
    """反向登记：`application.yml` 的默认值仍是坏的 —— 所以栈**必须**显式覆盖。

    这条不是「应当修 application.yml」的判据：默认值对**非容器**部署（localhost:8000 前向端口）
    仍可用，改它会影响生产口径。本判据只钉住「默认值一旦被修好，上面的守卫可以放宽」这件事
    需要一次显式复核。
    """
    text = APP_YML.read_text(encoding="utf-8")
    assert "base-url: ${AI_AGENT_BASE_URL:http://localhost:8000}" in text
    assert "service-token: ${AI_AGENT_SERVICE_TOKEN:}" in text


def test_red_proof_missing_wiring_is_detectable():
    """判别力自证：admin-api 没声明这两个键 ⇒ 取值为空 ⇒ 上面的断言必红。"""
    env = admin_api_env({"services": {"admin-api": {"environment": {"TZ": "Asia/Shanghai"}}}})
    assert env.get("AI_AGENT_BASE_URL", "") == ""
    assert env.get("AI_AGENT_SERVICE_TOKEN", "") == ""
