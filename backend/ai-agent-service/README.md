# AI Agent Service

米高 AI 智能客服 — Python AI 服务（米宝 + 小布双 Agent）

## 技术栈

- Python 3.11 + FastAPI + LangChain + LangGraph
- DeepSeek V4 Pro（主模型）+ MiniMax M3（视觉模型）
- PostgreSQL + Redis + DashVector（向量检索）

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env  # 填入实际 API Key

# 3. 启动
python -m uvicorn app.main:app --port 8001 --reload
# 启动后访问: http://localhost:8001
# Swagger UI: http://localhost:8001/docs
```

## 测试

```bash
.venv/bin/python -m pytest tests/ -v           # 全量单测
.venv/bin/python -m pytest tests/test_xxx.py   # 指定文件
.venv/bin/python -m pytest tests/e2e/real/ -v  # 真实 LLM E2E（需 E2E_REAL_ENABLED=true）
```

## 项目结构

```
app/
├── agents/      # 双 Agent 定义（米宝/小布）
├── graph/       # LangGraph 状态图 + 23 个 Skill
│   ├── skills/  # Skill 节点定义
│   └── nodes.py # Graph 节点逻辑
├── tools/       # 22 个 Tool（调用 admin-api）
├── memory/      # 会话记忆管理
├── api/         # FastAPI 路由（chat.py 核心）
└── utils/       # HTTP 客户端、日志脱敏等
```

## 关键配置

| 变量 | 说明 |
|------|------|
| `PRIMARY_API_KEY` | DeepSeek API Key |
| `VISION_API_KEY` | MiniMax API Key |
| `ADMIN_API_BASE_URL` | Java 后端地址 |
| `SERVICE_TOKEN` | 服务间认证 Token |
| `JWT_PUBLIC_KEY` | JWT 验证公钥 |
