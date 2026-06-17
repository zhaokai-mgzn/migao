"""
AI 智能客服系统 - 测试公用 Fixtures

提供 JWT Token 生成、mock 配置等公用工具
"""

import os
import time
import jwt
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient


# ========== 在导入 app.* 前注入必需的环境变量 ==========
# Settings 中部分字段无默认值，pytest 收集阶段就会触发实例化，
# 因此必须在 import app.tools.base 之前把这些字段塞进 environ。
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ADMIN_API_BASE_URL", "http://admin-api:8080")
os.environ.setdefault("SERVICE_TOKEN", "test-service-token")
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    "-----BEGIN PUBLIC KEY-----\nTESTKEY\n-----END PUBLIC KEY-----",
)
os.environ.setdefault("LOGISTICS_API_URL", "https://wuliu.market.alicloudapi.com/kdi")
os.environ.setdefault("LOGISTICS_APPCODE", "test-appcode")
os.environ.setdefault("SSE_TIMEOUT", "300")
os.environ.setdefault("SSE_PING_INTERVAL", "30")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

from app.tools.base import ToolContext  # noqa: E402  (必须在环境变量注入之后)


# ========== 测试用 JWT 密钥对（仅用于测试） ==========

# 使用 HS256 对称算法简化测试
TEST_JWT_SECRET = "test-secret-key-for-unit-tests"


@pytest.fixture
def jwt_secret():
    """返回测试用 JWT 密钥"""
    return TEST_JWT_SECRET


@pytest.fixture
def make_jwt_token():
    """
    JWT Token 工厂 fixture

    返回一个可调用对象，支持自定义 payload 生成 Token
    """
    def _make_token(payload: dict, secret: str = TEST_JWT_SECRET, algorithm: str = "HS256") -> str:
        return jwt.encode(payload, secret, algorithm=algorithm)
    return _make_token


@pytest.fixture
def sample_camel_case_payload():
    """camelCase 风格的 JWT Payload（模拟 admin-api 签发）"""
    return {
        "userId": "user_001",
        "tenantId": 1,
        "identityType": "wechat_mini",
        "roles": ["customer"],
        "externalId": "wx_openid_abc",
        "exp": int(time.time()) + 3600,
        "sub": "user_001",
    }


@pytest.fixture
def sample_snake_case_payload():
    """snake_case 风格的 JWT Payload"""
    return {
        "user_id": "user_002",
        "tenant_id": 2,
        "identity_type": "account",
        "role": "admin",
        "external_id": "ext_002",
        "exp": int(time.time()) + 3600,
        "sub": "user_002",
    }


@pytest.fixture
def expired_payload():
    """过期的 JWT Payload"""
    return {
        "userId": "user_expired",
        "tenantId": 1,
        "identityType": "account",
        "role": "customer",
        "exp": int(time.time()) - 3600,  # 已过期
    }


# 测试用 RSA 公钥（与 admin-api 的 public.pem 一致，用于 JWT RS256 验证）
TEST_RSA_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyDkix6IDMt3wkCAY1Phk\n"
    "O56ihiAu9deWNU/kfRn0dnc/iKC3sqmjlE7Te854xOuy1EjvIbDAXDFbaKHMOM76\n"
    "itKKIvSpOzGsSaEuerNsQH6+il9KgnO2rk4z9fDEoX9ZYnzIjr3n/oM6mv3Nfh+x\n"
    "17QMdMo9n29cHlznQAVc4kAJ1ACu4eYJVxiH6WZNtXLu6PkiU+YqsaPOGchvp1Xy\n"
    "PmZXyJJl0r+xDEVCgfXLsStFTau/9B5YxMv28N5gg1JbwpZNBpBYZ00J90lQkT+5\n"
    "Lpl0Tto5k/R08bFvAn8uf0PcbpOQ70Ibs9R7T/MHfK0NKyBrwZnzEdcIEQ6Pdn9g\n"
    "RwIDAQAB\n"
    "-----END PUBLIC KEY-----"
)


@pytest.fixture
def mock_settings():
    """Mock 应用配置"""
    mock = MagicMock()
    mock.DEBUG = True
    # 测试环境使用真实 RSA 公钥，避免 DEBUG 模式绕过签名验证（#4 安全加固）
    mock.JWT_PUBLIC_KEY = TEST_RSA_PUBLIC_KEY
    mock.SERVICE_TOKEN = "test-service-token"
    mock.DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5432/test_db"
    mock.REDIS_URL = "redis://localhost:6379/0"
    mock.DASHSCOPE_API_KEY = "test-key"
    mock.DASHSCOPE_MODEL = "qwen-test"
    mock.APP_NAME = "ai-agent-service"
    mock.APP_VERSION = "1.0.0"
    mock.API_PREFIX = "/api"
    return mock


# ========== FastAPI TestClient ==========

@pytest.fixture
def test_client():
    """FastAPI TestClient fixture
    
    使用 mock 跳过实际的数据库/Redis 初始化
    """
    with patch("app.utils.database.init_db", new_callable=AsyncMock), \
         patch("app.utils.database.close_db", new_callable=AsyncMock), \
         patch("app.utils.redis_client.init_redis", new_callable=AsyncMock), \
         patch("app.utils.redis_client.close_redis", new_callable=AsyncMock), \
         patch("app.main.get_rag_pipeline", new_callable=AsyncMock, side_effect=ImportError), \
         patch("app.main.get_vector_store", new_callable=AsyncMock, side_effect=ImportError):
        from app.main import create_app
        app = create_app()
        with TestClient(app) as client:
            yield client


# ========== 数据库会话 Mock ==========

@pytest.fixture
def mock_db_session():
    """Mock 的 AsyncSession，模拟数据库操作"""
    session = AsyncMock()
    # 模拟 context manager 协议
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ========== Redis 客户端 Mock ==========

@pytest.fixture
def mock_redis():
    """Mock 的 Redis 客户端"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=0)
    redis.lpush = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.close = AsyncMock()
    return redis


# ========== LLM 响应 Mock ==========

@pytest.fixture
def mock_llm_response():
    """Mock 的 LLM API 响应"""
    return {
        "output": {
            "text": "这是一个模拟的 LLM 响应。我可以帮您查询商品信息。",
            "finish_reason": "stop",
        },
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
        "request_id": "test-request-id-001",
    }


# ========== 向量库 Mock ==========

@pytest.fixture
def mock_vector_store():
    """Mock 的向量库客户端"""
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.insert = AsyncMock(return_value=True)
    store.delete = AsyncMock(return_value=True)
    store.health_check = AsyncMock(return_value={"available": True})
    return store


# ========== Tool 上下文示例 ==========

@pytest.fixture
def sample_tool_context():
    """标准的 Tool 上下文 fixture"""
    return ToolContext(
        tenant_id=1,
        user_id="user_001",
        session_id="sess_test_001",
        role="customer",
    )


@pytest.fixture
def admin_tool_context():
    """管理员角色 Tool 上下文"""
    return ToolContext(
        tenant_id=1,
        user_id="admin_001",
        session_id="sess_test_002",
        role="admin",
    )


@pytest.fixture
def unauthorized_tool_context():
    """无权限角色 Tool 上下文"""
    return ToolContext(
        tenant_id=1,
        user_id="guest_001",
        session_id="sess_test_003",
        role="guest",
    )


# ========== Admin API Mock 响应工厂 ==========

@pytest.fixture
def mock_admin_api_client():
    """返回一个 mock 的 admin-api HTTP client"""
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    return client
