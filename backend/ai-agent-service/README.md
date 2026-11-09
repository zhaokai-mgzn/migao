# AI Agent Service

观星台 — 布艺行业 AI 经营平台 · Python AI 服务（米宝 + 黄金策双 Agent）

## 技术栈

- Python 3.11 + FastAPI + LangChain + LangGraph
- DeepSeek（主模型 / 视觉模型由 `PRIMARY_MODEL` / `VISION_MODEL` 配置）
- PostgreSQL + Redis（知识问答走 `knowledge_cards`，无向量库）

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
├── agents/      # 双 Agent 定义（黄金策/米宝）
├── graph/       # LangGraph 状态图 + Skill（数量现取：ls app/graph/skills/*_skill.py）
│   ├── skills/  # Skill 节点定义
│   └── nodes.py # Graph 节点逻辑
├── tools/       # 业务工具（数量以 app/tools/registry.py 为单一源）
├── memory/      # 会话记忆管理
├── api/         # FastAPI 路由（chat.py 核心）
└── utils/       # HTTP 客户端、日志脱敏等
```

## 关键配置

| 变量 | 说明 |
|------|------|
| `PRIMARY_API_KEY` | DeepSeek API Key |
| `VISION_API_KEY` | DeepSeek API Key（与主模型同 key） |
| `ADMIN_API_BASE_URL` | Java 后端地址 |
| `SERVICE_TOKEN` | 服务间认证 Token |
| `JWT_PUBLIC_KEY` | JWT 验证公钥 |
