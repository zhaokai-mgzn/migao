# 部署

## CI/CD

合并 main 自动触发：

| 变更路径 | 工作流 | 目标 |
|---------|--------|------|
| backend/admin-api/** | deploy-admin-api | SAE (FatJar) |
| backend/ai-agent-service/** | deploy-ai-agent-service | SAE (Docker) |
| frontend/admin-web/** | deploy-admin-web | OSS + CDN |

## 阿里云服务

| 服务 | 用途 |
|------|------|
| SAE | 托管 admin-api + ai-agent-service |
| RDS PostgreSQL 15 | 主库 (RLS) |
| Redis 7 | 会话/缓存 |
| DashVector | 向量库 (RAG) |
| DeepSeek / MiniMax | LLM推理 |
| OSS | 静态资源/文件上传 |
| CDN | 前端加速 |
| ACR | 容器镜像 |
| SLS | 日志 |
| API Gateway | 统一入口 |

## 关键环境变量

**admin-api**: DB_URL, REDIS_URL, JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, SERVICE_TOKEN

**ai-agent-service**: PRIMARY_API_KEY, DASHVECTOR_API_KEY, DASHVECTOR_ENDPOINT, DB_URL, REDIS_URL, OSS_*

**admin-web**: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_AI_URL

## Terraform

管理: VPC, RDS, Redis, SAE, OSS, CDN, DashVector, SLS

```bash
cd deploy/terraform
terraform plan && terraform apply
```

## 手动部署

```bash
# admin-api
cd backend/admin-api && ./mvnw clean package -DskipTests
# 上传 target/*.jar 到 SAE

# ai-agent-service
cd backend/ai-agent-service
docker build -t registry.cn-hangzhou.aliyuncs.com/migao/ai-agent:latest .
docker push registry.cn-hangzhou.aliyuncs.com/migao/ai-agent:latest

# admin-web
cd frontend/admin-web && npm run build
# 上传 out/ 到 OSS，刷新 CDN
```
