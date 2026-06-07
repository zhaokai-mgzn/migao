# 本地开发环境配置（铁律，禁止混淆）

## 核心原则

> **本地只启动有客系统组件，数据库/缓存/中间件全部使用云 dev 环境。**

```
┌──────────────────────────────────────────────────────────┐
│ 本地启动（你本机跑）                                       │
│ ┌──────────┐ ┌────────────────┐ ┌───────────┐           │
│ │ admin-api │ │ ai-agent-service│ │ admin-web  │           │
│ │ Java :8080│ │ Python :8001    │ │ Next :3001 │           │
│ └──────────┘ └────────────────┘ └───────────┘           │
│                                                          │
│ 云 dev 环境（已配置好，只连不用启）                        │
│ ┌──────────┐ ┌───────┐ ┌──────────┐ ┌──────────┐       │
│ │PostgreSQL│ │ Redis │ │DashVector │ │DashScope │       │
│ │  (RDS)   │ │ (云)  │ │  (向量库) │ │ (LLM API)│       │
│ └──────────┘ └───────┘ └──────────┘ └──────────┘       │
└──────────────────────────────────────────────────────────┘
```

## 本地启动命令（唯一标准）

```bash
# ⚠️ 只需要启动这 3 个。不要尝试启动本地 DB/Redis/向量库。

# 1. admin-api（Java，端口 8080）
cd backend/admin-api && ./mvnw spring-boot:run &

# 2. ai-agent-service（Python，端口 8001）
cd backend/ai-agent-service && .venv/bin/python -m uvicorn app.main:app --port 8001 --reload &

# 3. admin-web（Next.js，端口 3001）
cd frontend/admin-web && npm run dev &

# 验证就绪
lsof -i :8080 -sTCP:LISTEN && lsof -i :8001 -sTCP:LISTEN && lsof -i :3001 -sTCP:LISTEN
```

## 云 dev 环境配置（在 .env 中，已预配好）

| 服务 | 来源 | 说明 |
|------|------|------|
| PostgreSQL | `backend/ai-agent-service/.env` → `DATABASE_URL` | RDS 公网地址，端口 5432 |
| Redis | `backend/ai-agent-service/.env` → `REDIS_URL` | 云 Redis，端口 6379 |
| DashVector | `backend/ai-agent-service/.env` → `DASHVECTOR_*` | 阿里云向量库 |
| DashScope | `backend/ai-agent-service/.env` → `DASHSCOPE_*` | 百炼 LLM API |
| OSS | `backend/ai-agent-service/.env` → `IMAGE_URL_REWRITE_TO` | 图片存储 |

## 禁止行为

```
❌ 不要在本地启动 PostgreSQL（brew services start postgresql）
❌ 不要在本地启动 Redis（redis-server）
❌ 不要用 docker-compose up 启动中间件
❌ 不要修改 .env 中的 DATABASE_URL 指向 localhost
❌ 不要把 .env 中的云 dev 连接信息改成其他的
```

## 连接验证

```bash
# 确认 DB 可达（白名单含本机 IP 时）
python3 -c "
import socket; s=socket.socket(); s.settimeout(5)
s.connect(('pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com',5432))
print('DB OK'); s.close()
"

# 如果 DB 不可达，检查 RDS 白名单
# aliyun rds DescribeDBInstanceIPArrayList --DBInstanceId pgm-bp1p7w92k81ob5to --region cn-hangzhou
# 如需添加本机 IP:
# aliyun rds ModifySecurityIps --DBInstanceId pgm-bp1p7w92k81ob5to \
#   --SecurityIps "115.196.136.12,$(curl -s ifconfig.me)" \
#   --DBInstanceIPArrayName dev_local --ModifyMode Cover --region cn-hangzhou
```

## 测试时的服务依赖

| 测试类型 | 需要本地服务 | 需要云 dev |
|---------|:-----------:|:---------:|
| 单元测试（mock） | ❌ | ❌ |
| 持久化集成测试 | ❌ | ✅ DB |
| 真实 LLM 集成测试 | ❌ | ✅ DashScope |
| Playwright E2E 测试 | ✅ 全部 3 个 | ✅ 全部 |
