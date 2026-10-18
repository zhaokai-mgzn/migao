"""
冒烟测试环境配置

通过 SMOKE_ENV 环境变量切换测试目标:
- local: 本地 Docker Compose 环境
- staging: 预发布环境
- production: 生产环境
"""

import os
from dataclasses import dataclass


#: 云端冒烟账号的租户 ID（issue #7179，用户裁定 2026-10-18）：
#: 冒烟固定登录账号改为**新账号 · 租户 46**（企业「词元通达」，管理员 `13900001025`）——
#: 原来的 `13800138000` 在云库 `users` 里已不存在 ⇒ 部署后的 P0 冒烟腿结构上必然红
#: （2026-10-17 那次部署实证：健康检查 4/4 过、登录 401 `该手机号未注册`）。
#: `local` 档**有意不动**（仍是 tenant 1 + `13800138000`）：本地 Docker 栈的 tenant 1 由栈内种子创建，与云端无关。
CLOUD_TENANT_ID = "46"


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
            admin_phone=os.getenv("ADMIN_PHONE", "13900001025"),
            admin_sms_code=os.getenv("ADMIN_SMS_CODE", "123456"),
            tenant_id=int(os.getenv("TENANT_ID", CLOUD_TENANT_ID)),
            service_token=os.getenv("SERVICE_TOKEN", ""),
        ),
        "production": EnvConfig(
            name="production",
            admin_api_url=admin_api_url or "https://api.migaozn.com",
            ai_agent_url=ai_agent_url or "https://ai-api.migaozn.com",
            admin_phone=os.getenv("ADMIN_PHONE", "13900001025"),
            admin_sms_code=os.getenv("ADMIN_SMS_CODE", "123456"),
            tenant_id=int(os.getenv("TENANT_ID", CLOUD_TENANT_ID)),
            service_token=os.getenv("SERVICE_TOKEN", ""),
        ),
    }

    if env not in configs:
        raise ValueError(f"Unknown SMOKE_ENV: {env}. Use: local, staging, production")

    return configs[env]
