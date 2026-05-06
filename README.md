# AI 智能客服系统 - 布艺行业（窗帘生产与家装）

> 一个面向通用行业的 AI 智能客服开源项目，以布艺行业（窗帘生产与家装）为示例场景。

## 项目简介

本项目是一个基于大语言模型的多功能 AI 智能客服系统，支持：

- **售前咨询**：产品推荐、窗帘尺寸计算、材质介绍、风格搭配建议
- **订单查询**：订单状态跟踪、订单详情查询、历史订单查看
- **售后处理**：退货、换货、投诉处理、问题跟踪
- **物流查询**：实时物流状态查询、配送时间预估

## 技术栈

### 后端
- **框架**: Python 3.11+ / FastAPI（异步）
- **LLM**: 阿里云百炼 DashScope（通义千问系列）
- **AI 框架**: LangChain
- **数据库**: PostgreSQL（业务数据）+ Redis（会话/缓存）
- **向量数据库**: FAISS / Milvus（知识库检索）
- **消息队列**: Celery + Redis

### 前端
- **框架**: Next.js 14 (App Router)
- **UI**: React + Tailwind CSS
- **状态管理**: Zustand
- **实时通信**: WebSocket / Server-Sent Events

## 项目结构

```
youke/
├── backend/                 # 后端服务
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── core/           # 核心配置
│   │   ├── agents/         # AI Agent 实现
│   │   ├── models/         # 数据模型
│   │   ├── services/       # 业务服务
│   │   └── utils/          # 工具函数
│   ├── tests/              # 测试用例
│   └── scripts/            # 脚本工具
├── frontend/               # 前端应用
│   ├── app/               # Next.js 页面
│   ├── components/        # React 组件
│   └── lib/               # 工具库
├── docs/                  # 项目文档
└── knowledge_base/        # 知识库数据
    ├── products/          # 产品信息
    ├── curtain_faq/       # 窗帘常见问题
    └── size_guide/        # 尺寸指南
```

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Redis 7+

### 后端启动

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 配置环境变量（阿里云百炼 API Key 等）
uvicorn app.main:app --reload
```

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

## 学习路径

本项目适合作为 AI 应用开发的学习项目，建议按以下顺序学习：

1. **LLM 接入层** - 学习如何接入阿里云百炼 API
2. **对话管理** - 学习会话状态管理和上下文维护
3. **RAG 系统** - 学习检索增强生成和知识库构建
4. **Agent 开发** - 学习意图识别、工具调用和多 Agent 协作
5. **系统集成** - 学习完整的前后端集成和部署

## 许可证

MIT License
