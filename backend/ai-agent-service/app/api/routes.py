"""
API 路由

所有 API 路由注册在此统一管理。
"""

from fastapi import APIRouter

from app.api.asr import router as asr_router
from app.api.chat import router as chat_router
from app.api.internal import router as internal_router
from app.api.registration_review import router as registration_review_router
from app.api.upload import router as upload_router

router = APIRouter()

# 注册路由
# 对话相关 API
router.include_router(chat_router, prefix="/chat", tags=["chat"])

# 语音识别 API
router.include_router(asr_router, tags=["asr"])

# 图片上传 API（代理转发到 admin-api）
router.include_router(upload_router, prefix="/chat", tags=["chat"])

# 内部服务 API（Service Token 认证）
router.include_router(internal_router, prefix="/internal", tags=["internal"])
router.include_router(
    registration_review_router,
    prefix="/internal/registration",
    tags=["internal"],
)
