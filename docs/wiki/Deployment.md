# 部署

> **2026-08-14 起生产计算层已从 SAE 迁移到 SWAS 轻量应用服务器**。本页为当前事实；迁移踩坑见 `docs/deployment/swas-migration-lessons.md`，历史踩坑清单见 `docs/deployment/deployment-checklist.md`。

## CI/CD

合并 main 自动触发（路径过滤 + 可手动 dispatch）：

| 变更路径 | 工作流 | 部署方式 |
|---------|--------|---------|
| backend/admin-api/** | deploy-admin-api | 云助手触发 SWAS `deploy.sh`（拉 CI 预构建镜像 + up） |
| backend/ai-agent-service/** | deploy-ai-agent-service | 同上 |
| frontend/admin-web/** | deploy-frontend | 同上 |

三个工作流统一：CI 测试/构建 → `aliyun swas-open RunCommand` 在 SWAS 实例跑 `/opt/migao-deploy/deploy.sh` → post-deploy 冒烟（smoke-test.yml）。

## 生产拓扑（SWAS 单机 4 容器）

| 容器 | 端口 | 职责 |
|------|------|------|
| nginx | 80/443 | TLS 终结（Let's Encrypt），域名分流 |
| admin-api | 8080 | Java 管理后端 |
| ai-agent | 8000 | Python AI 服务 |
| admin-web | 3001 | Next.js 管理后台 |

域名分流（nginx）：
- `api.migaozn.com` → admin-api:8080
- `ai-api.migaozn.com` → ai-agent:8000
- `migaozn.com` / `www.migaozn.com` / `merchant.migaozn.com` / `ops.migaozn.com` → admin-web:3001

> 注：nginx `server_name` 里还列了 `admin.migaozn.com`，但该域名**无 DNS 解析**，实际前端入口是上面 4 个域名。

## 阿里云服务

| 服务 | 用途 |
|------|------|
| SWAS 轻量应用服务器 | 托管全部 4 个容器（nginx + 3 应用） |
| RDS PostgreSQL 15 | 主库 (RLS) |
| Redis (Tair 公网代理) | 会话/缓存（admin-api 强制 RESP2） |
| DashVector | 向量库 (RAG) |
| DeepSeek | LLM推理/视觉 |
| OSS | 静态资源/文件上传 |
| ACR | 容器镜像（历史遗留，线上已不消费） |

## 关键环境变量

**admin-api**: RDS_HOST/USER/PASSWORD, REDIS_HOST/PASSWORD, JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, SERVICE_TOKEN_SECRET

**ai-agent-service**: PRIMARY_API_KEY, DASHVECTOR_API_KEY/ENDPOINT, DATABASE_URL, REDIS_URL, OSS_*, SERVICE_TOKEN

**admin-web**: PORT（构建时 NEXT_PUBLIC_API_BASE_URL / NEXT_PUBLIC_AI_API_BASE_URL / NEXT_PUBLIC_COOKIE_DOMAIN）

## 服务器手动部署

```bash
# 在 SWAS 服务器上（/opt/migao-deploy/）：
bash deploy.sh
# 即：拉 main 源码 → RESP2 补丁 → docker compose up -d --build → 健康检查

# 查看状态/日志
docker compose ps
docker compose logs -f admin-api

# 健康检查
curl -s http://127.0.0.1:8080/actuator/health   # admin-api
curl -s http://127.0.0.1:8000/health            # ai-agent
curl -sI http://127.0.0.1:3001/                 # admin-web
```

## Terraform（历史遗留）

`deploy/terraform/` 中的 SAE 资源已弃用；RDS/OSS 等资源若仍由 Terraform 管理需单独确认。当前生产部署不依赖 Terraform。
