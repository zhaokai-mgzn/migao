"""
AI 智能客服系统 - 认证中间件模块

提供两种认证方式：
1. Service Token 验证：用于 admin-api 调用本服务的内部 API
2. JWT 用户身份验证：用于 C 端用户调用聊天 API
"""

import re
import secrets
from typing import Optional, Dict, Any
from enum import Enum
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from fastapi import Header, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from loguru import logger

from app.config import settings


# DEBUG C 端默认身份 id —— 单一事实源（评测种子夹具的顾客 id 必须与本值一致，
# 由 tests/unit_ci_workflows/test_schema_integrity.py 从本文件**源码解析**锁死；
# 那个 CI job 只装 pytest+pyyaml，无法 import 本模块，故必须保持字面量形态）。
DEBUG_CUSTOMER_USER_ID = "debug_customer_1"

# 多身份评测（issue #3391）：只认测试夹具常用的 `debug_` 前缀 id。
# 白名单而非"任意字符串"：DEBUG 误配时不得变成任意用户伪装后门。
_DEBUG_USER_ID_RE = re.compile(r"debug_[a-z0-9_]{1,32}")


class UserRole(str, Enum):
    """用户角色枚举

    注意：此枚举仅用于 require_roles 等端点级粗筛，且必须与 admin-api
    实际签发的角色码对齐——商户员工角色码（operator/product_manager/
    customer_service/knowledge_editor/super_admin）均须在此放行，否则
    admin-api JWT 在解析处被 pydantic 校验拒绝（401），员工无法使用米宝
    B 端对话（角色码漂移修复，POC 审查 D 项）。
    细粒度权限由 AgentConfig.allowed_roles / Tool.allowed_roles 判断。
    """
    CUSTOMER = "customer"
    AGENT = "agent"
    ADMIN = "admin"
    # ── admin-api 商户员工角色码（对齐 RegistrationService / RoleService）──
    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"
    PRODUCT_MANAGER = "product_manager"
    KNOWLEDGE_EDITOR = "knowledge_editor"
    CUSTOMER_SERVICE = "customer_service"


class UserIdentity(BaseModel):
    """
    统一用户身份模型
    
    从 JWT Claims 中提取的用户身份信息
    """
    user_id: str
    tenant_id: int
    identity_type: str  # wechat_mini / wechat_h5 / account / agent_wechat_mini
    # P1-C（RBAC 走查）：role 用 str 而非 UserRole 枚举——商户可在「角色管理」创建
    # 任意自定义角色码（如 poc_operator_custom），枚举强校验会拒绝未知码 → 401
    # TOKEN_INVALID，自定义角色员工无法使用米宝。已知枚举码仍定义于 UserRole 供
    # require_roles 白名单引用；此处放宽为 str 仅做格式透传，权限由 permissions claim 控制。
    role: str
    permissions: list[str] = []  # 细粒度权限码列表
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
        # fail-closed：未配置 SERVICE_TOKEN 时拒绝所有内部调用，而非静默放行。
        # 生产环境由 Settings.validate_production_secrets 强制非空，此分支仅在
        # DEBUG/误配时可达，必须以 503 暴露配置错误而非敞开内部 API。
        logger.error("SERVICE_TOKEN not configured — rejecting internal service call (fail-closed)")
        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "error": {
                    "code": "CONFIG_ERROR",
                    "message": "SERVICE_TOKEN not configured"
                }
            }
        )

    if not secrets.compare_digest(x_service_token, expected_token):
        logger.warning("Service token authentication failed: invalid token provided")
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
        # 无公钥配置 — 仅 DEBUG 模式允许未验证签名（开发便利）
        # 生产环境必须配置 JWT_PUBLIC_KEY，否则启动即报错
        if settings.DEBUG:
            logger.error(
                "🚨 SECURITY: JWT_PUBLIC_KEY not configured — accepting tokens WITHOUT signature verification. "
                "This MUST never happen in production. Set JWT_PUBLIC_KEY env var."
            )
            try:
                return jwt.decode(
                    token,
                    options={"verify_signature": False, "verify_aud": False},
                )
            except Exception as e:
                logger.warning(f"JWT verification failed (debug mode): invalid token format - {str(e)}")
                raise HTTPException(
                    status_code=401,
                    detail={
                        "success": False,
                        "error": {
                            "code": "TOKEN_INVALID",
                            "message": f"Invalid token format: {str(e)}"
                        }
                    }
                )
        else:
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
        # 开发环境：未提供 Token 且 DEBUG=true 时，可注入默认用户身份。
        # 【P0-3 安全加固 2026-09-03】DEBUG 降级必须带显式调试头 X-Debug-Role，
        # 禁止"无 token 无头 → 静默直通租户 1 管理员"：
        #   - 此前生产若误配 DEBUG=true，任何浏览器/客户端无 token 请求都会被
        #     降级为 tenant_id=1 的 dev_user 管理员，导致跨租户数据泄露
        #     （POC 实测：新商家 /chat 页面读到词元通达租户的全部订单/会话）。
        #   - 现在：DEBUG=true 且无 token 时，仅当请求带 X-Debug-Role 头才放行
        #     （本地验收 / CI xiaobu 显式注入该头）；无头一律 401 fail-closed。
        #   - 生产正确配置（DEBUG=false）永远不进入此分支，行为不变。
        debug_role = request.headers.get("X-Debug-Role", "").strip().lower()
        if settings.DEBUG and debug_role:
            if debug_role == "customer":
                _uid = DEBUG_CUSTOMER_USER_ID
                # ── 多身份评测（issue #3391）──
                # 为什么需要：debug_customer_1 在评测种子里有历史订单 →
                # `customer_address_query` 恒返回 has_address=true →「新客没有历史收货信息
                # → 主动收集」这条路径**在评测里不可达**，而那正是验收 C-A1 暴露问题的路径。
                # 安全约束（与 P0-3 同源：DEBUG 误配不得变成数据泄露后门）：
                #   · 仅 DEBUG=true + role=customer 时生效（生产 DEBUG=false 永不进本分支）；
                #   · 仅接受 `debug_` 前缀的**测试夹具** id（白名单正则，挡住 dev_user/
                #     管理员/注入式 id 的伪装）；B 端身份不接受覆盖。
                _req_user = request.headers.get("X-Debug-User", "").strip()
                if _req_user and _DEBUG_USER_ID_RE.fullmatch(_req_user):
                    _uid = _req_user
                    logger.warning(
                        f"DEBUG C 端身份覆盖（多身份评测）：user_id={_uid} "
                        f"—— 仅 DEBUG 模式且 debug_ 前缀白名单内可用，生产不可达")
                else:
                    if _req_user:
                        logger.warning(
                            f"忽略非法 X-Debug-User={_req_user!r}（仅接受 debug_ 前缀白名单）")
                    logger.warning("No auth token in DEBUG mode, using CUSTOMER identity (xiaobu)")
                default_user = UserIdentity(
                    user_id=_uid,
                    tenant_id=1,
                    identity_type="account",
                    role=UserRole.CUSTOMER,
                )
            else:
                logger.warning(
                    "No auth token in DEBUG mode with explicit X-Debug-Role=%s, "
                    "using ADMIN identity (mibao/dev)", debug_role
                )
                default_user = UserIdentity(
                    user_id="dev_user",
                    tenant_id=1,
                    identity_type="account",
                    role=UserRole.ADMIN,
                    # 通配权限（#3511 HR-003 归因）：DEBUG 管理员身份此前 permissions=[] →
                    # role=admin 只过 allowed_roles 粗筛，声明 required_permissions 的工具
                    # （employee_manage 等）一律「权限不足」——评测栈实测 `employee_manage!权限不足`，
                    # agent 行为正确却无法执行（环境缺陷被误读为能力缺陷）。
                    # 仅 DEBUG + 显式 X-Debug-Role 分支可达（生产 DEBUG=false 永不进入，
                    # 且"无 header 即 401"的 fail-closed 语义不变）。
                    permissions=["*"],
                )
            request.state.user = default_user
            return default_user
        
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(
            f"Authentication failed: no token provided (DEBUG={settings.DEBUG}, "
            f"x-debug-role={request.headers.get('X-Debug-Role', '')!r}), client_ip={client_ip}"
        )
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

        # 提取细粒度权限码
        permissions_raw = payload.get("permissions") or payload.get("perm") or []
        permissions: list[str] = []
        if isinstance(permissions_raw, list):
            permissions = [p for p in permissions_raw if isinstance(p, str)]
        elif isinstance(permissions_raw, str):
            import json
            try:
                permissions = json.loads(permissions_raw)
                permissions = [p for p in permissions if isinstance(p, str)]
            except (json.JSONDecodeError, TypeError):
                permissions = []

        user = UserIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            identity_type=identity_type,
            role=role,
            permissions=permissions,
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
