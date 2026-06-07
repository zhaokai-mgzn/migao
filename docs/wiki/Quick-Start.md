# 快速开始

## 本地开发

本地只启 3 组件，DB/Redis/中间件全用云 dev：

```bash
# 1. Admin API (:8080)
cd backend/admin-api && ./mvnw spring-boot:run

# 2. AI Agent (:8001)
cd backend/ai-agent-service
.venv/bin/python -m uvicorn app.main:app --port 8001 --reload

# 3. Admin Web (:3001)
cd frontend/admin-web && npm run dev
```

## 构建/测试

```bash
# Java
cd backend/admin-api
./mvnw clean compile           # 编译
./mvnw test                    # 全量单测
./mvnw test -Dtest=XxxTest     # 增量

# Python
cd backend/ai-agent-service
.venv/bin/python -m pytest tests/ -v

# Frontend
cd frontend/admin-web
npx vitest run                 # 单测 (vitest, 非 jest)
npx tsc --noEmit               # 类型检查

# E2E
cd tests && npm run e2e
```

## 环境变量

各模块 `.env` 已预置云 dev 连接信息，禁止改 localhost。

| 模块 | 关键变量 |
|------|---------|
| admin-api | DB_URL, REDIS_URL, JWT_PRIVATE_KEY, JWT_PUBLIC_KEY |
| ai-agent-service | DASHSCOPE_API_KEY, DASHVECTOR_*, DB_URL, REDIS_URL |
| admin-web | NEXT_PUBLIC_API_URL, NEXT_PUBLIC_AI_URL |
