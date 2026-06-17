"""
冒烟测试环境配置

通过 SMOKE_ENV 环境变量切换测试目标:
- local: 本地 Docker Compose 环境
- staging: 预发布环境
- production: 生产环境
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvConfig:
    """测试环境配置"""
    name: str
    admin_api_url: str
    ai_agent_url: str
    admin_phone: str
    admin_sms_code: str
    tenant_id: int
    service_token: str


def get_config() -> EnvConfig:
    """根据环境变量获取测试配置"""
    env = os.getenv("SMOKE_ENV", "local")

    # 支持直接覆盖 URL
    admin_api_url = os.getenv("ADMIN_API_URL")
    ai_agent_url = os.getenv("AI_AGENT_URL")

    configs = {
        "local": EnvConfig(
            name="local",
            admin_api_url=admin_api_url or "http://localhost:8080",
            ai_agent_url=ai_agent_url or "http://localhost:8001",
            admin_phone=os.getenv("ADMIN_PHONE", "13800138000"),
            admin_sms_code=os.getenv("ADMIN_SMS_CODE", "123456"),
            tenant_id=int(os.getenv("TENANT_ID", "1")),
            service_token=os.getenv("SERVICE_TOKEN", "test-service-token"),
        ),
        "staging": EnvConfig(
            name="staging",
            admin_api_url=admin_api_url or "https://api.migaozn.com",
            ai_agent_url=ai_agent_url or "https://ai-api.migaozn.com",
            admin_phone=os.getenv("ADMIN_PHONE", "13800138000"),
            admin_sms_code=os.getenv("ADMIN_SMS_CODE", "123456"),
            tenant_id=int(os.getenv("TENANT_ID", "1")),
            service_token=os.getenv("SERVICE_TOKEN", ""),
        ),
        "production": EnvConfig(
            name="production",
            admin_api_url=admin_api_url or "https://api.migaozn.com",
            ai_agent_url=ai_agent_url or "https://ai-api.migaozn.com",
            admin_phone=os.getenv("ADMIN_PHONE", "13800138000"),
            admin_sms_code=os.getenv("ADMIN_SMS_CODE", "123456"),
            tenant_id=int(os.getenv("TENANT_ID", "1")),
            service_token=os.getenv("SERVICE_TOKEN", ""),
        ),
    }

    if env not in configs:
        raise ValueError(f"Unknown SMOKE_ENV: {env}. Use: local, staging, production")

    return configs[env]
