"""AI 智能客服系统 - FastAPI 应用入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="基于阿里云百炼的 AI 智能客服系统",
    version="0.1.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "AI Customer Service API",
        "docs": "/docs",
        "health": "/health",
    }
