# case_ids: SMK-001
"""生产档冒烟基址判据（issue #8992）。

红证：在本文件加入前，`production` 档的基址是 `api.migaozn.com`（测试实例），
下面两条断言会红；修掉后转绿。
"""

from tests.smoke.config import get_config


def test_production_env_targets_cytda_not_test_instance(monkeypatch):
    monkeypatch.delenv("ADMIN_API_URL", raising=False)
    monkeypatch.delenv("AI_AGENT_URL", raising=False)
    cfg = get_config.__globals__["get_config"]
    monkeypatch.setenv("SMOKE_ENV", "production")
    production = cfg()

    assert "cytda.com" in production.admin_api_url, (
        f"生产档 admin_api_url 必须指向 cytda，实际 {production.admin_api_url}"
    )
    assert "cytda.com" in production.ai_agent_url, (
        f"生产档 ai_agent_url 必须指向 cytda，实际 {production.ai_agent_url}"
    )
    assert "migaozn" not in production.admin_api_url
    assert "migaozn" not in production.ai_agent_url


def test_staging_env_keeps_test_instance(monkeypatch):
    monkeypatch.delenv("ADMIN_API_URL", raising=False)
    monkeypatch.delenv("AI_AGENT_URL", raising=False)
    cfg = get_config.__globals__["get_config"]
    monkeypatch.setenv("SMOKE_ENV", "staging")
    staging = cfg()

    assert "migaozn" in staging.admin_api_url, (
        f"staging 档应仍指向测试实例，实际 {staging.admin_api_url}"
    )
