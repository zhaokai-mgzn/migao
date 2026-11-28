"""
API 路由

所有 API 路由注册在此统一管理。
"""

from fastapi import APIRouter

from app.api.asr import router as asr_router
from app.api.chat import router as chat_router
from app.api.internal import router as internal_router
from app.api.kf_judge import router as kf_judge_router
from app.api.kf_reply import router as kf_reply_router
from app.api.migration import router as migration_router
from app.api.payments import router as payments_router
from app.api.products import router as products_router
from app.api.registration_review import router as registration_review_router
from app.api.upload import router as upload_router

router = APIRouter()

# 注册路由
# 对话相关 API
router.include_router(chat_router, prefix="/chat", tags=["chat"])

# C 端商品只读 API（新品推荐等）
router.include_router(products_router, prefix="/chat", tags=["chat"])

# C 端收款二维码 API（支付页展示，issue #3990）
router.include_router(payments_router, prefix="/chat", tags=["chat"])

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

# 微信客服语义判定（issue #9196 / 母单 #9194 子项 1）：admin-api 的 KfDecisionService 在
# 规则未命中时调用它补召回；失败即回退规则（本端点不抛 500）。
router.include_router(
    kf_judge_router,
    prefix="/internal/kf",
    tags=["internal"],
)

# 微信客服 AI 回复生成（issue #9302）：判定为 AI_REPLY 后由 admin-api 取**一条**客户可见正文，
# 再经 KfSendService 入 outbox。失败即判不可用（admin-api 转人工），本端点不发半成品。
router.include_router(
    kf_reply_router,
    prefix="/internal/kf",
    tags=["internal"],
)

# 客户迁移：旧 ERP 表头 → 规范客户字段的**映射建议**（issue #8295）
# 最终路径 = settings.API_PREFIX + /internal/migration + /customer-mapping
# = /api/internal/migration/customer-mapping（与 internal_router 的 /internal/* 不重叠）。
router.include_router(
    migration_router,
    prefix="/internal/migration",
    tags=["internal"],
)
