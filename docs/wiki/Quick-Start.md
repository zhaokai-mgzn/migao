# 快速开始

## 前置：RDS 白名单（必做，否则本地服务连不上 dev 库）

本地起服务时，admin-api(:8080) / ai-agent-service(:8001) 会**真实连接云 dev 的 RDS**（`.env` 里是公网地址）。阿里云 RDS 有 IP 白名单：**当前公网 IP 不在白名单 → TCP 被 DROP → 连接挂起 30 秒超时**，本地服务起不来、测试也会被拖慢到小时级（issue #2957 实证）。

```bash
# 查当前公网 IP
curl -s https://ifconfig.me
```

阿里云 RDS 控制台 → 白名单设置 → 添加 `当前公网IP/32`（如 `183.129.118.190/32`）。运营商 IP 漂移时更新即可，**不建议 /0**。

**重要边界：白名单只服务于「本地起服务联调」，单测/verify-all 不需要也不允许白名单**——`tests/conftest.py` 已用环境变量把单测的 DATABASE_URL/REDIS_URL 钉死在 localhost（环境变量优先级高于 .env 文件），单测连不上/不连云库是**设计行为**（毫秒级失败走降级）。若本地验证变慢，先查 conftest 隔离是否被破坏，而不是加白名单（见 `docs/testing/test-engineering-standards.md` §6）。

## 本地开发

本地只启 3 组件，DB/Redis/中间件全用云 dev（需先完成上面 RDS 白名单）：

```bash
# 1. Admin API (:8080)
cd backend/admin-api && ./mvnw spring-boot:run

# 2. AI Agent (:8000)
cd backend/ai-agent-service
.venv/bin/python -m uvicorn app.main:app --port 8000 --reload

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
| ai-agent-service | PRIMARY_API_KEY, PRIMARY_MODEL, DASHVECTOR_*, DB_URL, REDIS_URL |
| admin-web | NEXT_PUBLIC_API_URL, NEXT_PUBLIC_AI_URL |
