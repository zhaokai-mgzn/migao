"""
AI 智能客服系统 - 认证中间件模块

提供两种认证方式：
1. Service Token 验证：用于 admin-api 调用本服务的内部 API
2. JWT 用户身份验证：用于 C 端用户调用聊天 API
"""

from typing import Optional, Dict, Any
from enum import Enum
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from fastapi import Header, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from loguru import logger

from app.config import settings


class UserRole(str, Enum):
    """用户角色枚举"""
    CUSTOMER = "customer"
    AGENT = "agent"
    ADMIN = "admin"


class UserIdentity(BaseModel):
    """
    统一用户身份模型
    
    从 JWT Claims 中提取的用户身份信息
    """
    user_id: str
    tenant_id: int
    identity_type: str  # wechat_mini / wechat_h5 / account / agent_wechat_mini
    role: UserRole
    external_id: Optional[str] = None  # 第三方平台用户 ID（如微信 openid）
    exp: Optional[int] = None  # Token 过期时间
    
    class Config:
        use_enum_values = True


# HTTP Bearer 认证（用于 Swagger UI 测试）
security_bearer = HTTPBearer(auto_error=False)


async def verify_service_token(
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token")
) -> bool:
    """
    验证 Service Token（用于内部 API 调用）
    
    由 admin-api 调用本服务时携带，用于验证请求来源
    
    Args:
        x_service_token: 请求头中的 X-Service-Token
    
    Returns:
        bool: 验证是否通过
    
    Raises:
        HTTPException: 401 如果 Token 无效
    
    使用方式：
        @router.post("/internal/tools/execute")
        async def execute_tool(
            authorized: bool = Depends(verify_service_token)
        ):
            ...
    """
    if not x_service_token:
        logger.warning("Service token authentication failed: missing X-Service-Token header")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "AUTH_REQUIRED",
                    "message": "Missing X-Service-Token header"
                }
            }
        )
    
    # 与配置中的 SERVICE_TOKEN 比对
    # 注意：生产环境应该使用更安全的验证方式（如 HMAC 签名）
    expected_token = settings.SERVICE_TOKEN
    
    if not expected_token:
        logger.warning("SERVICE_TOKEN not configured, skipping validation")
        return True
    
    if x_service_token != expected_token:
        logger.warning(f"Service token authentication failed: invalid token provided (token_prefix={x_service_token[:8]}...)")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "AUTH_REQUIRED",
                    "message": "Invalid service token"
                }
            }
        )
    
    return True


def verify_jwt_token(token: str) -> Dict[str, Any]:
    """
    验证 JWT Token
    
    使用 RS256 公钥验证 Token 签名，并解析 Claims
    
    Args:
        token: JWT Token 字符串
    
    Returns:
        Dict: JWT Payload
    
    Raises:
        HTTPException: 401 如果 Token 无效或过期
    """
    if not settings.JWT_PUBLIC_KEY:
        # 无公钥时拒绝所有请求，避免未验证签名的 Token 被接受
        raise HTTPException(
            status_code=500,
            detail={
                    "success": False,
                    "error": {
                        "code": "CONFIG_ERROR",
                        "message": "JWT_PUBLIC_KEY not configured"
                    }
                }
            )
    
    try:
        # 使用 RS256 公钥验证（禁用内置 audience 检查，手动验证以兼容 JJWT 数组格式）
        payload = jwt.decode(
            token,
            settings.JWT_PUBLIC_KEY,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        # 手动验证 audience（兼容字符串和数组格式）
        aud_claim = payload.get("aud", [])
        if isinstance(aud_claim, str):
            aud_claim = [aud_claim]
        if "migao" not in aud_claim:
            raise jwt.exceptions.InvalidTokenError(
                f"Audience doesn't match: expected 'migao', got {aud_claim}"
            )
        return payload
    except ExpiredSignatureError:
        logger.warning("JWT verification failed: token has expired")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "TOKEN_EXPIRED",
                    "message": "Token has expired"
                }
            }
        )
    except InvalidTokenError as e:
        logger.warning(f"JWT verification failed: invalid token - {str(e)}")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "TOKEN_INVALID",
                    "message": f"Invalid token: {str(e)}"
                }
            }
        )


async def get_current_user(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> UserIdentity:
    """
    获取当前用户身份（JWT 验证）
    
    从 Cookie 或 Authorization Header 中提取并验证 JWT
    
    Args:
        request: FastAPI Request 对象
        authorization: Authorization Header（Bearer Token）
    
    Returns:
        UserIdentity: 用户身份信息
    
    Raises:
        HTTPException: 401 如果认证失败
    
    使用方式：
        @router.post("/chat/messages")
        async def send_message(
            user: UserIdentity = Depends(get_current_user)
        ):
            # user.tenant_id, user.user_id 等
            ...
    """
    token: Optional[str] = None
    
    # 1. 优先从 Cookie 中获取（浏览器端）
    if "access_token" in request.cookies:
        token = request.cookies["access_token"]
    
    # 2. 其次从 Authorization Header 获取（小程序/移动端）
    if not token and authorization:
        token = authorization.credentials
    
    if not token:
        # 开发环境：如果未提供 Token 且 DEBUG=true，使用默认用户身份
        if settings.DEBUG:
            logger.warning("No auth token provided in DEBUG mode, using default user identity")
            default_user = UserIdentity(
                user_id="dev_user",
                tenant_id=1,
                identity_type="account",
                role=UserRole.ADMIN,
            )
            request.state.user = default_user
            return default_user
        
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(f"Authentication failed: no token provided, client_ip={client_ip}")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "AUTH_REQUIRED",
                    "message": "Authentication required"
                }
            }
        )
    
    # 验证 Token
    payload = verify_jwt_token(token)
    
    # 提取用户身份信息（兼容 camelCase 和 snake_case 字段名）
    try:
        # admin-api 签发的 JWT 使用 camelCase，但也兼容 snake_case
        user_id = payload.get("userId") or payload.get("user_id") or payload.get("sub")
        tenant_id_raw = payload.get("tenantId") or payload.get("tenant_id")
        tenant_id = int(tenant_id_raw) if tenant_id_raw is not None else None
        identity_type = payload.get("identityType") or payload.get("identity_type", "unknown")
        
        # role 字段兼容：admin-api 可能发 roles 数组，也可能发单个 role 字符串
        roles = payload.get("roles", [])
        role = payload.get("role")
        if not role:
            if isinstance(roles, list) and roles:
                role = roles[0]  # 取第一个角色
            else:
                role = "customer"
        
        external_id = payload.get("externalId") or payload.get("external_id")
        
        user = UserIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            identity_type=identity_type,
            role=role,
            external_id=external_id,
            exp=payload.get("exp")
        )
        
        # 验证必要字段
        if not user.user_id or not user.tenant_id:
            logger.warning(
                f"Authentication failed: missing required claims in token, "
                f"user_id={user.user_id}, tenant_id={user.tenant_id}"
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "success": False,
                    "error": {
                        "code": "TOKEN_INVALID",
                        "message": "Missing required claims in token"
                    }
                }
            )
        
        # 将用户信息存入 request state，方便后续使用
        request.state.user = user
        
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Authentication failed: error parsing user identity - {e}")
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": {
                    "code": "TOKEN_INVALID",
                    "message": "Invalid token payload"
                }
            }
        )


async def get_optional_user(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> Optional[UserIdentity]:
    """
    可选的用户身份验证
    
    用于不需要强制登录的接口，返回 None 表示未登录
    
    使用方式：
        @router.get("/public/info")
        async def get_info(
            user: Optional[UserIdentity] = Depends(get_optional_user)
        ):
            if user:
                return {"message": f"Hello, {user.user_id}"}
            return {"message": "Hello, guest"}
    """
    try:
        return await get_current_user(request, authorization)
    except HTTPException:
        return None


def require_roles(allowed_roles: list[UserRole]):
    """
    角色权限装饰器工厂
    
    创建依赖项，检查用户是否具有指定角色
    
    Args:
        allowed_roles: 允许的角色列表
    
    Returns:
        Callable: FastAPI 依赖函数
    
    使用方式：
        @router.post("/admin/config")
        async def update_config(
            user: UserIdentity = Depends(require_roles([UserRole.ADMIN]))
        ):
            ...
    """
    async def role_checker(user: UserIdentity = Depends(get_current_user)) -> UserIdentity:
        if user.role not in allowed_roles:
            logger.warning(
                f"Authorization failed: role '{user.role}' not allowed, "
                f"user_id={user.user_id}, tenant_id={user.tenant_id}, "
                f"required_roles={[r.value if hasattr(r, 'value') else r for r in allowed_roles]}"
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "success": False,
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": f"Role '{user.role}' is not allowed for this operation"
                    }
                }
            )
        return user
    
    return role_checker
