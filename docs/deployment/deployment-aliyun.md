# 阿里云部署方案

> 版本：v9.0（DashVector 向量数据库 + 百炼 LLM/Embedding API + 管理前端 OSS 静态托管）
> 日期：2026-05-03
> 状态：2 个后端服务（admin-api + ai-agent-service），管理前端 OSS+CDN 静态托管，仅接入微信小程序

---

## 1. 部署架构概览

### 1.1 服务部署拓扑

```
┌──────────────────────────────────────────────────────────────────────────┐
│                             阿里云环境                                    │
│                                                                           │
│  ┌──────────────────────────────────┐  ┌──────────────────────────────┐ │
│  │  微信小程序（C端 + 客服工作台）   │  │ 管理前端 (Next.js)            │ │
│  │  (微信开发者工具)                │  │ (OSS + CDN 静态托管)         │ │
│  └──────────────────────────────────┘  └──────────────┬───────────────┘ │
│                                                              │            │
│  ┌─────────▼────────────────────────────────────────────────▼────────┐  │
│  │                        API Gateway                                 │  │
│  │              (路由/限流/WAF/SSL/CORS)                              │  │
│  └───┬──────────────────────────┬───────────────────────────────┐    │
│      │                          │                               │    │
│  ┌───▼──────────────────┐ ┌───▼──────────────────────────────┐  │    │
│  │ AI Agent 服务          │ │ 管理后端（含认证 + 管理业务）    │  │    │
│  │ (Python FastAPI, SAE) │ │ (Java Spring Boot 3, SAE)       │  │    │
│  │                       │ │                                 │  │    │
│  │ - 客服对话             │ │ - 认证服务（微信小程序登录）    │  │    │
│  │ - 管理助手             │ │ - 管理业务 API                 │  │    │
│  │                       │ │ - 客服工作台 API + WebSocket   │  │    │
│  └───────────┬───────────┘ └───────────┬───────────────────┘  │    │
│              │                          │                       │    │
│  ┌───────────▼──────────────────────────▼───────────────────┐  │
│  │                          VPC 内网                                 │  │
│  │  ┌──────────┐  ┌──────┐  ┌────────┐                             │  │
│  │  │ RDS PG   │  │Redis │  │ ACR    │                             │  │
│  │  │(主数据)  │  │(缓存) │  │(镜像)  │                             │  │
│  │  └──────────┘  └──────┘  └────────┘                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────────┐     │
│  │       阿里云百炼              │  │       DashVector 向量库      │  │        可观测性               │     │
│  │  ┌────────┐  ┌────────────┐ │  │  ┌────────────────────────┐  │  │  ┌────────┐  ┌────────────┐ │     │
│  │  │LLM API │  │Embedding   │ │  │  │ 向量存储 & 相似度检索   │  │  │  │SLS 日志│  │ARMS 监控   │ │     │
│  │  │        │  │API         │ │  │  │ (替代百炼知识库 RAG)   │  │  │  └────────┘  └────────────┘ │     │
│  │  └────────┘  └────────────┘ │  │  └────────────────────────┘  │  └──────────────────────────────┘     │
│  │  （不再提供知识库/RAG 功能）  │  └──────────────────────────────┘                                     │
│  └──────────────────────────────┘                                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.2 阿里云产品清单

| 产品 | 用途 | 规格（开发环境）| 月成本预估 |
|------|------|----------------|-----------|
| **SAE** | 应用托管（2 个后端服务）| 按量付费，Python 0.5C1G × 1 + Java 1C2G × 1 | ~170 元 |
| **RDS PostgreSQL** | 业务数据库 | pg.n2.small.1 (1C2G, 20GB) | ~100 元 |
| **Redis** | 缓存/会话/code 防重放 | redis.master.small.default (1G) | ~50 元 |
| **OSS + CDN** | 管理前端静态托管 + 静态资源存储加速 | 按量 | ~15 元 |
| **API Gateway** | API 路由/限流 | 按量 | ~20 元 |
| **ACR** | 容器镜像仓库 | 个人版（免费）| 0 元 |
| **SLS** | 日志服务 | 免费额度内 | 0 元 |
| **ARMS** | 应用监控 | 基础版（免费）| 0 元 |
| **百炼** | LLM API + Embedding API（不再提供知识库） | 按量 | ~0 元（免费额度内） |
| **DashVector** | 向量数据库（知识库 RAG 存储与检索） | 标准版 1 集合 | ~50 元 |
| **合计** | - | - | **~300 元/月** |

---

## 2. 前置准备

### 2.1 账号与权限

1. **注册阿里云账号**并完成实名认证
2. **创建 RAM 子账号**（推荐，不要使用主账号 AccessKey）
   - 登录 [RAM 控制台](https://ram.console.aliyun.com/)
   - 创建用户，勾选"OpenAPI 调用访问"
   - 授予权限策略：`AliyunSAEFullAccess`、`AliyunRDSFullAccess`、`AliyunVPCFullAccess`、`AliyunLogFullAccess`
   - 记录 AccessKey ID 和 AccessKey Secret

3. **开通必要服务**
   - Serverless 应用引擎 SAE
   - 云数据库 RDS
   - 云数据库 Redis
   - 对象存储 OSS
   - 日志服务 SLS
   - 阿里云百炼（LLM + Embedding API）
   - DashVector 向量数据库

### 2.2 获取百炼 API Key

1. 访问 [百炼控制台](https://bailian.console.aliyun.com/)
2. 开通百炼服务
3. 进入"API-KEY 管理"，创建 API Key
4. 记录 API Key（格式：`sk-xxxxxxxxxxxxxxxxxxxxxxxx`）

> **注意**：百炼现在仅提供 LLM API 和 Embedding API。知识库 RAG 功能已迁移至 DashVector 向量数据库。

### 2.3 配置 DashVector 向量数据库

1. 访问 [DashVector 控制台](https://dashvector.console.aliyun.com/)
2. 开通 DashVector 服务
3. 创建实例（开发环境选择标准版即可）
4. 创建 Collection（集合），配置维度与百炼 Embedding 模型输出维度一致（如 `text-embedding-v3` 输出 1024 维）
5. 获取 API Key 和 Endpoint

**创建 Collection 示例**：

```bash
# 使用 DashVector SDK 创建 Collection
curl -X POST "https://dashvector.cn-hangzhou.aliyuncs.com/v1/collections" \
  -H "Authorization: Bearer ${DASHVECTOR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "knowledge_base",
    "dimension": 1024,
    "metric": "cosine"
  }'
```

### 2.4 安装工具

```bash
# macOS
brew install terraform
brew install aliyun-cli
brew install --cask docker

# 配置阿里云 CLI
aliyun configure
# Access Key ID []: <your-access-key-id>
# Access Key Secret []: <your-access-key-secret>
# Default Region Id []: cn-hangzhou
# Default output format [json]: json
```

### 2.5 配置 Terraform

```bash
# 设置环境变量
export ALICLOUD_ACCESS_KEY="your-access-key-id"
export ALICLOUD_SECRET_KEY="your-access-key-secret"
export ALICLOUD_REGION="cn-hangzhou"

# 验证配置
terraform -v
```

---

## 3. 基础设施部署（Terraform）

### 3.1 Terraform 配置

```hcl
# deploy/terraform/main.tf
# ==================== 阿里云基础设施即代码配置 ====================
# 多租户 SaaS AI 智能客服系统 - 阿里云部署
# 使用前请确保：
# 1. 已安装 Terraform: brew install terraform (macOS)
# 2. 已配置阿里云 AccessKey: export ALICLOUD_ACCESS_KEY=xxx && export ALICLOUD_SECRET_KEY=xxx
# 3. 复制 terraform.tfvars.example 为 terraform.tfvars 并填写敏感变量

terraform {
  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = "~> 1.220.0"
    }
  }
}

provider "alicloud" {
  region = var.region
}

# ==================== 变量定义 ====================

variable "region" {
  description = "阿里云地域"
  type        = string
  default     = "cn-hangzhou"
}

variable "project_name" {
  description = "项目名称"
  type        = string
  default     = "youke"
}

variable "environment" {
  description = "环境名称（dev/staging/prod）"
  type        = string
  default     = "dev"
}

variable "db_password" {
  description = "RDS PostgreSQL 数据库密码"
  type        = string
  sensitive   = true
}

variable "redis_password" {
  description = "Redis 实例密码"
  type        = string
  sensitive   = true
}

variable "dashscope_api_key" {
  description = "阿里云百炼 DashScope API Key"
  type        = string
  sensitive   = true
}

variable "dashvector_api_key" {
  description = "阿里云 DashVector 向量检索 API Key"
  type        = string
  sensitive   = true
}

variable "dashvector_endpoint" {
  description = "DashVector 服务端点"
  type        = string
  default     = "https://dashvector.cn-hangzhou.aliyuncs.com"
}

variable "internal_service_secret" {
  description = "服务间 HMAC 认证密钥（admin-api 与 ai-agent-service 内部通信）"
  type        = string
  sensitive   = true
}

variable "cors_allowed_origins" {
  description = "CORS 允许的前端域名"
  type        = string
  default     = "https://merchant.migaozn.com"
}

variable "cookie_domain" {
  description = "Cookie 作用域"
  type        = string
  default     = ".migaozn.com"
}

variable "wechat_mini_appid" {
  description = "微信小程序 AppID"
  type        = string
}

variable "wechat_mini_appsecret" {
  description = "微信小程序 AppSecret"
  type        = string
  sensitive   = true
}

variable "jwt_public_key" {
  description = "JWT RS256 公钥内容（PEM 格式字符串，用于 ai-agent-service 验证 Token）"
  type        = string
  sensitive   = true
  default     = ""
}

variable "oss_access_key_id" {
  description = "OSS 访问密钥 ID"
  type        = string
}

variable "oss_access_key_secret" {
  description = "OSS 访问密钥 Secret"
  type        = string
  sensitive   = true
}

# ==================== 网络资源（VPC / VSwitch / 安全组）====================

resource "alicloud_vpc" "main" {
  vpc_name   = "${var.project_name}-${var.environment}-vpc"
  cidr_block = "172.16.0.0/16"
}

resource "alicloud_vswitch" "main" {
  vpc_id       = alicloud_vpc.main.id
  cidr_block   = "172.16.0.0/24"
  zone_id      = "${var.region}b"
  vswitch_name = "${var.project_name}-${var.environment}-vswitch"
}

# 安全组：仅允许 VPC 子网内部流量互通
resource "alicloud_security_group" "main" {
  name   = "${var.project_name}-${var.environment}-sg"
  vpc_id = alicloud_vpc.main.id
}

resource "alicloud_security_group_rule" "allow_vpc_internal" {
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "1/65535"
  priority          = 1
  security_group_id = alicloud_security_group.main.id
  cidr_ip           = "172.16.0.0/24"
}

# ==================== RDS PostgreSQL 数据库 ====================

resource "alicloud_db_instance" "postgres" {
  engine               = "PostgreSQL"
  engine_version       = "14.0"
  instance_type        = "pg.n2.small.1"
  instance_storage     = 20
  instance_name        = "${var.project_name}-${var.environment}-pg"
  vswitch_id           = alicloud_vswitch.main.id
  instance_charge_type = "PostPaid"
  security_ip_lists    = ["172.16.0.0/24"]
}

resource "alicloud_db_database" "app" {
  instance_id   = alicloud_db_instance.postgres.id
  name          = "ai_customer_service"
  character_set = "UTF8"
}

resource "alicloud_db_account" "app" {
  instance_id = alicloud_db_instance.postgres.id
  name        = "app_user"
  password    = var.db_password
  type        = "Normal"
}

resource "alicloud_db_account_privilege" "app" {
  instance_id  = alicloud_db_instance.postgres.id
  account_name = alicloud_db_account.app.name
  privilege    = "DBOwner"
  db_names     = [alicloud_db_database.app.name]
}

# ==================== Redis 缓存 ====================

resource "alicloud_kvstore_instance" "redis" {
  engine_version       = "7.0"
  instance_type        = "Redis"
  instance_class       = "redis.master.small.default"
  instance_name        = "${var.project_name}-${var.environment}-redis"
  vswitch_id           = alicloud_vswitch.main.id
  security_ips         = ["172.16.0.0/24"]
  instance_charge_type = "PostPaid"
  password             = var.redis_password
}

# ==================== ACR 容器镜像仓库 ====================

resource "alicloud_cr_namespace" "main" {
  name               = var.project_name
  auto_create        = true
  default_visibility = "PRIVATE"
}

resource "alicloud_cr_repo" "ai_agent_service" {
  namespace = alicloud_cr_namespace.main.name
  name      = "ai-agent-service"
  repo_type = "PRIVATE"
  summary   = "AI Agent 服务镜像（Python 3.11 / FastAPI）"
}

resource "alicloud_cr_repo" "admin_api" {
  namespace = alicloud_cr_namespace.main.name
  name      = "admin-api"
  repo_type = "PRIVATE"
  summary   = "管理后台 API 镜像（Java 21 / Spring Boot 3.3）"
}

# ==================== SAE 命名空间 ====================

resource "alicloud_sae_namespace" "main" {
  namespace_id          = "${var.region}:${var.project_name}-${var.environment}"
  namespace_name        = "${var.project_name}-${var.environment}"
  namespace_description = "AI 智能客服系统 ${var.environment} 环境"
}

# ==================== SAE 应用：admin-api（Java 21 / Spring Boot 3.3）====================

resource "alicloud_sae_application" "admin_api" {
  app_name          = "${var.project_name}-admin-api"
  namespace_id      = alicloud_sae_namespace.main.id
  package_type      = "Image"
  image_url         = "registry.${var.region}.aliyuncs.com/${alicloud_cr_namespace.main.name}/${alicloud_cr_repo.admin_api.name}:latest"
  replicas          = 1
  cpu               = 1000
  memory            = 2048
  vswitch_id        = alicloud_vswitch.main.id
  security_group_id = alicloud_security_group.main.id

  app_envs {
    name  = "SPRING_PROFILES_ACTIVE"
    value = "prod"
  }
  app_envs {
    name  = "RDS_HOST"
    value = alicloud_db_instance.postgres.connection_string
  }
  app_envs {
    name  = "RDS_PORT"
    value = "5432"
  }
  app_envs {
    name  = "RDS_DB"
    value = "ai_customer_service"
  }
  app_envs {
    name  = "RDS_USER"
    value = "app_user"
  }
  app_envs {
    name  = "RDS_PASSWORD"
    value = var.db_password
  }
  app_envs {
    name  = "REDIS_HOST"
    value = alicloud_kvstore_instance.redis.connection_domain
  }
  app_envs {
    name  = "REDIS_PORT"
    value = "6379"
  }
  app_envs {
    name  = "REDIS_PASSWORD"
    value = var.redis_password
  }
  app_envs {
    name  = "JWT_PRIVATE_KEY"
    value = "classpath:rsa/private.pem"
  }
  app_envs {
    name  = "JWT_PUBLIC_KEY"
    value = "classpath:rsa/public.pem"
  }
  app_envs {
    name  = "SERVICE_TOKEN_SECRET"
    value = var.internal_service_secret
  }
  app_envs {
    name  = "CORS_ALLOWED_ORIGINS"
    value = var.cors_allowed_origins
  }
  app_envs {
    name  = "COOKIE_DOMAIN"
    value = var.cookie_domain
  }
  app_envs {
    name  = "WECHAT_MINI_APPID"
    value = var.wechat_mini_appid
  }
  app_envs {
    name  = "WECHAT_MINI_SECRET"
    value = var.wechat_mini_appsecret
  }
  app_envs {
    name  = "OSS_ENDPOINT"
    value = "oss-cn-hangzhou-internal.aliyuncs.com"
  }
  app_envs {
    name  = "OSS_ACCESS_KEY_ID"
    value = var.oss_access_key_id
  }
  app_envs {
    name  = "OSS_ACCESS_KEY_SECRET"
    value = var.oss_access_key_secret
  }
  app_envs {
    name  = "OSS_BUCKET_NAME"
    value = alicloud_oss_bucket.admin_frontend.bucket
  }

  liveness = jsonencode({
    httpGet = {
      path = "/actuator/health"
      port = 8080
    }
    initialDelaySeconds = 30
    periodSeconds       = 10
  })

  readiness = jsonencode({
    httpGet = {
      path = "/actuator/health"
      port = 8080
    }
    initialDelaySeconds = 20
    periodSeconds       = 10
  })
}

# ==================== SAE 应用：ai-agent-service（Python 3.11 / FastAPI）====================

resource "alicloud_sae_application" "ai_agent_service" {
  app_name          = "${var.project_name}-ai-agent"
  namespace_id      = alicloud_sae_namespace.main.id
  package_type      = "Image"
  image_url         = "registry.${var.region}.aliyuncs.com/${alicloud_cr_namespace.main.name}/${alicloud_cr_repo.ai_agent_service.name}:latest"
  replicas          = 1
  cpu               = 500
  memory            = 1024
  vswitch_id        = alicloud_vswitch.main.id
  security_group_id = alicloud_security_group.main.id

  depends_on = [alicloud_sae_application.admin_api]

  app_envs {
    name  = "DATABASE_URL"
    value = "postgresql+asyncpg://app_user:${var.db_password}@${alicloud_db_instance.postgres.connection_string}:5432/ai_customer_service"
  }
  app_envs {
    name  = "REDIS_URL"
    value = "redis://:${var.redis_password}@${alicloud_kvstore_instance.redis.connection_domain}:6379/0"
  }
  app_envs {
    name  = "DASHSCOPE_API_KEY"
    value = var.dashscope_api_key
  }
  app_envs {
    name  = "DASHVECTOR_API_KEY"
    value = var.dashvector_api_key
  }
  app_envs {
    name  = "DASHVECTOR_ENDPOINT"
    value = var.dashvector_endpoint
  }
  app_envs {
    name  = "ADMIN_API_BASE_URL"
    value = "http://${alicloud_sae_application.admin_api.intranet_url}"
  }
  app_envs {
    name  = "SERVICE_TOKEN"
    value = var.internal_service_secret
  }
  app_envs {
    name  = "JWT_PUBLIC_KEY"
    value = var.jwt_public_key
  }
  app_envs {
    name  = "CORS_ALLOWED_ORIGINS"
    value = var.cors_allowed_origins
  }
  app_envs {
    name  = "APP_ENV"
    value = var.environment
  }

  liveness = jsonencode({
    httpGet = {
      path = "/health"
      port = 8000
    }
    initialDelaySeconds = 20
    periodSeconds       = 10
  })

  readiness = jsonencode({
    httpGet = {
      path = "/health"
      port = 8000
    }
    initialDelaySeconds = 15
    periodSeconds       = 10
  })
}

# ==================== OSS 静态资源存储（管理前端 Next.js 静态托管）====================

resource "alicloud_oss_bucket" "admin_frontend" {
  bucket = "${var.project_name}-admin-${var.environment}"
  acl    = "public-read"

  website {
    index_document = "index.html"
    error_document = "404.html"
  }
}

# ==================== 输出 ====================

output "database_connection" {
  description = "RDS PostgreSQL 内网连接地址"
  value       = alicloud_db_instance.postgres.connection_string
}

output "redis_connection" {
  description = "Redis 内网连接地址"
  value       = alicloud_kvstore_instance.redis.connection_domain
}

output "ai_agent_app_id" {
  description = "SAE ai-agent-service 应用 ID"
  value       = alicloud_sae_application.ai_agent_service.id
}

output "admin_api_app_id" {
  description = "SAE admin-api 应用 ID"
  value       = alicloud_sae_application.admin_api.id
}

output "oss_bucket_domain" {
  description = "OSS 前端静态资源访问域名"
  value       = "${alicloud_oss_bucket.admin_frontend.bucket}.oss-${var.region}.aliyuncs.com"
}

output "acr_namespace" {
  description = "ACR 镜像命名空间"
  value       = alicloud_cr_namespace.main.name
}
```

### 3.2 变量配置

```hcl
# deploy/terraform/terraform.tfvars.example
# ============================================================
# Terraform 变量配置
# 复制此文件为 terraform.tfvars 并填入实际值
# ============================================================

# 基础配置
region       = "cn-hangzhou"
project_name = "youke"
environment  = "dev"

# 数据库密码（建议随机生成: openssl rand -base64 32）
db_password = "ChangeMe123!@#"

# Redis 密码（建议随机生成: openssl rand -base64 32）
redis_password = "ChangeMe456!@#"

# 阿里云百炼 API Key（获取: https://bailian.console.aliyun.com/ → API-KEY 管理）
dashscope_api_key = "sk-your-dashscope-api-key"

# DashVector 向量数据库（获取: https://dashvector.console.aliyun.com/）
dashvector_api_key  = "sk-your-dashvector-api-key"
dashvector_endpoint = "https://your-instance.dashvector.cn-hangzhou.aliyuncs.com"

# 内部服务 HMAC 认证密钥（建议随机生成: openssl rand -hex 32）
# admin-api 和 ai-agent-service 共享此密钥
internal_service_secret = "your-internal-service-secret"

# CORS 允许的前端域名（逗号分隔）
cors_allowed_origins = "https://merchant.migaozn.com"

# HttpOnly Cookie 域名
cookie_domain = ".migaozn.com"

# 微信小程序配置（获取: https://mp.weixin.qq.com/ → 开发管理 → 开发设置）
wechat_mini_appid    = "wx-your-mini-app-id"
wechat_mini_appsecret = "wx-your-mini-app-secret"

# JWT RS256 公钥内容（ai-agent-service 验证 Token 用）
jwt_public_key = ""

# 阿里云 OSS 配置（获取: RAM 控制台创建子账号并授予 OSS 权限）
oss_access_key_id     = "your-oss-access-key-id"
oss_access_key_secret = "your-oss-access-key-secret"
```

### 3.3 执行部署

```bash
# 1. 初始化
cd deploy/terraform
terraform init

# 2. 预览变更
terraform plan

# 3. 部署
terraform apply

# 4. 记录输出
terraform output
```

---

## 4. 构建与推送镜像

### 4.1 登录 ACR

```bash
# 获取临时密码
aliyun cr GetAuthorizationToken

# 登录
docker login --username=your-username registry.cn-hangzhou.aliyuncs.com
```

### 4.2 构建 Python 服务镜像

> **注意**：Python 服务在 `backend/ai-agent-service/` 目录内构建。

```bash
# AI Agent 服务（客服对话 + 管理助手）
cd backend/ai-agent-service
docker build -t registry.cn-hangzhou.aliyuncs.com/youke/ai-agent-service:latest .
docker push registry.cn-hangzhou.aliyuncs.com/youke/ai-agent-service:latest
```

### 4.3 构建 Java 服务镜像（含认证服务）

```bash
cd backend/admin-api
# Maven 打包
./mvnw clean package -DskipTests

# 构建镜像
docker build -t registry.cn-hangzhou.aliyuncs.com/youke/admin-api:latest .
docker push registry.cn-hangzhou.aliyuncs.com/youke/admin-api:latest
```

### 4.4 Python Dockerfile

```dockerfile
# ai-agent-service/Dockerfile
# 构建: docker build -t ai-agent-service .

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# 复制并安装 Python 依赖（使用阿里云镜像源加速）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p logs

# 创建非 root 用户
RUN addgroup --system app && adduser --system --ingroup app app
USER app:app

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 4.5 Java Dockerfile

```dockerfile
# admin-api/Dockerfile

FROM maven:3-eclipse-temurin-21-alpine AS builder

WORKDIR /app
COPY pom.xml .
COPY src ./src

RUN mvn clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", \
    "-XX:+UseZGC", \
    "-XX:+ZGenerational", \
    "-XX:MaxRAMPercentage=75.0", \
    "-jar", "app.jar"]
```

---

## 5. 前端部署

### 5.1 客服前端 — 微信小程序

小程序代码包通过微信开发者工具上传至微信公众平台，不经过阿里云部署。

```bash
# 在微信开发者工具中打开小程序项目
# 点击"上传" → 填写版本号和备注 → 上传至微信公众平台
# 在微信公众平台提交审核 → 发布
```

### 5.2 管理前端 — OSS + CDN 静态托管

```bash
# 1. 构建静态文件（Next.js static export）
cd frontend/admin-web
npm run build           # output: 'export' + trailingSlash: true → 生成 out/<route>/index.html

# 2. 上传到 OSS
ossutil cp -r out/ oss://ai-customer-service-admin-dev/ --update

# 3. 应用 OSS 静态网站托管配置（关键）
./deploy/scripts/apply-oss-website.sh ai-customer-service-admin-dev cn-hangzhou oss-bucket-put-object

# 4. 清理 ossutil 上传时遗留的空目录标记 object（关键）
./deploy/scripts/clean-oss-dir-markers.sh ai-customer-service-admin-dev cn-hangzhou oss-bucket-put-object

# 5. CDN 刷新缓存（可选，更新后执行）
aliyun cdn RefreshObjectCaches --ObjectPath "https://merchant.migaozn.com/" --ObjectType Directory
```

**OSS 静态网站托管配置说明**（`deploy/oss-website.xml`）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<WebsiteConfiguration>
  <IndexDocument>
    <Suffix>index.html</Suffix>
    <SupportSubDir>true</SupportSubDir>   <!-- 支持子目录默认首页 -->
    <Type>0</Type>                         <!-- 0=Redirect, 1=Index, 2=NoSuchKey -->
  </IndexDocument>
  <ErrorDocument>
    <Key>404.html</Key>
    <HttpStatus>404</HttpStatus>           <!-- 必须 404；若设 200 会回退到首页伪装内容 -->
  </ErrorDocument>
</WebsiteConfiguration>
```

⚠️ **历史踩坑（已修复）**：

- ErrorDocument 历史配置为 `Key=index.html, HttpStatus=200`，任何 404 请求都会被改写为
  返回首页 HTML（HTTP 200），导致用户访问 `/dashboard/`、`/products/` 等受保护路由时
  浏览器看到的是营销首页，从而出现"登录后跳转却看到首页"的诡异现象。
  当前修复后：`Key=404.html, HttpStatus=404`，且 `SupportSubDir=true`。
- ossutil 上传时会为每个目录创建 0 字节占位 object（如 `dashboard/`），
  会遮挡 IndexDocument-SubDir 路由，必须运行 `clean-oss-dir-markers.sh` 清理。

**CDN 配置说明**：

1. 在阿里云 CDN 控制台添加加速域名（如 `merchant.migaozn.com`）。
2. **源站类型选择 OSS 域名，且填写「静态网站托管域名」**
   `ai-customer-service-admin-dev.oss-website-cn-hangzhou.aliyuncs.com`，
   而非 OSS REST 域名。只有这样 SubDir 路由 + ErrorDocument 才会经 CDN 透传到
   `https://merchant.migaozn.com/dashboard/` 等自定义域名 URL。
3. 配置 HTTPS 证书。
4. 启用压缩（Gzip/Brotli）。
5. 自定义错误页（可选）：CDN 配置 404 → `/404.html`。

**关于直接通过 OSS bucket-cname 自定义域名访问**：

- `aliyun oss bucket-cname` 将 `merchant.migaozn.com` 直接绑定到 bucket REST endpoint，
  此模式下 OSS 静态网站托管功能（SubDir、ErrorDocument）不会生效，
  访问 `/dashboard/` 等子路径将返回 `NoSuchKey 404`。
- 生产环境必须经过 CDN（或 Aliyun ESA），由 CDN 回源到 website endpoint，
  才能让 SPA 子路径路由可用。

---

## 6. API Gateway 配置

### 6.1 创建 API 分组

```bash
# 创建分组
aliyun apigateway CreateGroup --GroupName youke --Description "AI 客服 API"
```

### 6.2 配置路由

```yaml
# API Gateway 路由规则（按优先级从高到低排列）

# 认证接口（公开接口，不需要认证）
/api/auth/mini/login          →  admin-api (SAE)  [auth: false, method: POST]
/api/auth/account/login       →  admin-api (SAE)  [auth: false]

# 认证接口（需要认证）
/api/auth/*                   →  admin-api (SAE)  [auth: true]

# AI Agent 服务（客服对话 + 管理助手）
/api/chat/*                   →  ai-agent-service (SAE)  [auth: true]

# AI 管理助手（优先级高于 /api/admin/* 通配）
/api/admin/ai/*               →  ai-agent-service (SAE)  [auth: true]

# Java 管理后端（通配兜底，优先级最低，含认证 + 管理业务）
/api/admin/*                  →  admin-api (SAE)  [auth: true]
```

> **重要**：`/api/admin/ai/*` 必须排在 `/api/admin/*` 之前，确保 AI Agent 请求不被 Java 后端拦截。

### 6.3 配置限流

| API 路径 | QPS 限制 | IP 限制 |
|---------|---------|--------|
| /api/auth/account/login | 20 | 5/分钟 |
| /api/chat/* | 100 | 10/秒 |
| /api/admin/ai/* | 50 | 5/秒 |
| /api/admin/* | 200 | 20/秒 |

### 6.4 配置 WAF（可选）

1. 在 API Gateway 启用 WAF
2. 配置防 SQL 注入、XSS 防护
3. 配置 IP 黑名单

---

## 7. 可观测性配置

### 7.1 SLS 日志服务

**SAE 日志采集配置**：

在 SAE 控制台 → 应用配置 → 日志设置：

```yaml
logging:
  type: SLS
  config:
    project: youke-logs
    logstore: app-logs
    logtail_config:
      docker_file: true
      docker_include_label:
        ai-service: "true"
```

**日志格式**（Python）：

```python
# app/core/logging.py
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "tenant_id": getattr(record, "tenant_id", None),
            "request_id": getattr(record, "request_id", None)
        }
        return json.dumps(log_entry, ensure_ascii=False)
```

### 7.2 ARMS 应用监控

在 SAE 控制台启用 ARMS：

1. 进入应用 → 应用设置 → 监控
2. 开启"应用实时监控"
3. 开启"链路追踪"

**监控指标**：

| 指标 | 告警阈值 |
|------|---------|
| QPS | > 500 持续 5 分钟 |
| 平均响应时间 | > 2s 持续 5 分钟 |
| 错误率 | > 5% 持续 5 分钟 |
| CPU 使用率 | > 80% 持续 10 分钟 |
| 内存使用率 | > 85% 持续 10 分钟 |

### 7.3 云监控告警

```bash
# 创建告警规则
aliyun cms PutMetricRule \
  --RuleName "SAE-CPU-High" \
  --Namespace acs_sae \
  --MetricName cpu_utilization \
  --ComparisonOperator ">=" \
  --Threshold 80 \
  --ContactGroups "DevOps" \
  --NotifyType 1  # 邮件 + 短信
```

---

## 8. 数据库初始化

### 8.1 执行迁移

```bash
# 执行 SQL 迁移脚本（按顺序执行 docs/sql/ 下的脚本）
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/001_init.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/002_complete_tables.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/003_orders.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/004_tenant_applications.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/005_add_product_stock.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/006_add_updated_at.sql
psql -h <rds-connection-string> -U app_user -d ai_customer_service -f docs/sql/007_agent_workspace.sql
```

### 8.2 创建初始租户

```sql
INSERT INTO tenants (id, name, code, industry, status, bailian_config, created_at)
VALUES (
    'TENANT001',
    '示例窗帘企业',
    'demo_curtain',
    'curtain',
    'active',
    '{
        "api_key": "sk-tenant-demo-xxx",
        "default_model": "qwen-turbo",
        "knowledge_base_id": "kb_demo_general",
        "model_quota": {"qwen-turbo": 100000, "qwen-plus": 50000}
    }',
    NOW()
);
```

### 8.3 配置 RDS 备份

```bash
# 设置自动备份
aliyun rds ModifyBackupPolicy \
  --DBInstanceId <instance-id> \
  --PreferredBackupPeriod "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday" \
  --PreferredBackupTime "02:00Z-03:00Z" \
  --BackupRetentionPeriod 7
```

---

## 9. 安全加固

### 9.1 网络安全

- VPC 隔离：所有服务在同一 VPC 内网通信
- 安全组：仅开放必要端口
- API Gateway WAF：防护常见 Web 攻击

### 9.2 数据安全

- 数据库密码加密存储
- 敏感字段加密（如用户手机号）
- RDS 透明数据加密（TDE）

### 9.3 访问控制

- RAM 最小权限原则
- SAE 应用使用服务角色访问其他云产品
- API Key 轮换机制

### 9.4 审计

```sql
-- 开启数据库审计
ALTER SYSTEM SET pgaudit.log = 'read, write';
ALTER SYSTEM SET pgaudit.log_catalog = off;
```

---

## 10. CI/CD 流水线（GitHub Actions）

> 本项目使用 **GitHub Actions** 实现自动化部署。代码合并到 `main` 分支后自动触发对应服务的构建与部署，无需手动操作。

### 10.1 工作流概览

仓库 `.github/workflows/` 下有 3 个部署流水线：

| 工作流文件 | 名称 | 触发路径 | 构建方式 | 部署目标 |
|-----------|------|---------|---------|---------|
| `deploy-admin-api.yml` | admin-api | `backend/admin-api/**` | Maven → FatJar | SAE（FatJar 部署） |
| `deploy-ai-agent-service.yml` | ai-agent-service | `backend/ai-agent-service/**` | Docker build → ACR | SAE（镜像部署） |
| `deploy-admin-web.yml` | admin-web | `frontend/admin-web/**` | Next.js 静态导出 | OSS + CDN |

**触发规则**：
- **自动触发**：PR 合并到 `main` 分支，路径匹配时自动运行对应工作流
- **手动触发**：每个工作流支持 `workflow_dispatch`，可在 GitHub Actions 页面手动运行

### 10.2 标准部署流程

```
本地开发 → 创建功能分支 → 提交代码 → 创建 PR → Review 通过 → 合并到 main → GitHub Actions 自动部署
```

**具体步骤**：

```bash
# 1. 创建功能分支
git checkout -b feat/backend/xxx

# 2. 本地开发...

# 3. 提交并推送
git add .
git commit -m "feat(backend): 新增xxx功能"
git push origin feat/backend/xxx

# 4. 创建 PR
gh pr create --title "[backend] 新增xxx功能" --base main

# 5. Review 通过后合并（Squash merge 保持 main 整洁）
gh pr merge --squash --delete-branch

# 6. ✅ GitHub Actions 自动部署，无需任何额外操作
```

### 10.3 各工作流详解

#### admin-api（Java 后端）

```
触发条件：backend/admin-api/** 文件变更推送到 main
构建：JDK 21 (Temurin) + Maven → admin-api-*.jar (FatJar)
中间产物：FatJar 上传到 OSS（ai-customer-service-admin-dev/deploy/admin-api.jar）
部署：SAE DeployApplication（PackageType=FatJar）
健康检查：curl http://8.136.139.170/actuator/health (Host: admin-api.migaozn.com)
```

**关键实现细节**：
- **OSS URL 签名**：SAE 部署前会重新签名 OSS URL（有效期 86400s），避免使用过期 URL 导致部署失败
- **环境变量全量回传**：先通过 `DescribeApplicationConfig` 获取当前 SAE 环境变量，部署时通过 `--Envs` 全量重发。SAE 没有独立的环境变量更新 API，不传 `--Envs` 会清空所有环境变量
- **Python subprocess 调用**：使用 Python subprocess 调用 `aliyun` CLI，参数以 list 传入，避免 OSS URL 中的 `&`、密码中的 `@!$` 等特殊字符被 shell 误解析
- **等待前次部署**：部署前检查 `LastChangeOrderRunning` 状态，最多等待 120s

#### ai-agent-service（Python AI 服务）

```
触发条件：backend/ai-agent-service/** 文件变更推送到 main
构建：Docker build（时间戳标签 vYYYYMMDDHHMMSS）→ 推送到 ACR
部署：SAE DeployApplication（ImageUrl）
健康检查：curl https://ai-api.migaozn.com/health
```

**关键实现细节**：
- **ACR 登录**：Docker login 使用 `ACR_USERNAME` + `ACR_PASSWORD` Secrets
- **Pip 镜像**：CI 构建时 `--build-arg PIP_INDEX_URL=https://pypi.org/simple/` 覆盖默认阿里云镜像（CI 环境阿里云镜像反而更慢）
- **环境变量全量回传**：与 admin-api 相同，通过 `DescribeApplicationConfig` 获取后 `--Envs` 全量重发

#### admin-web（前端）

```
触发条件：frontend/admin-web/** 文件变更推送到 main
构建：Node 20 + npm ci + next build → out/ 静态目录
部署：aliyun oss cp out/ → OSS 静态托管
CDN：可选刷新 CDN 缓存（需配置 CDN_REFRESH_DOMAIN Secret）
健康检查：5 次重试检查 http://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com/index.html
```

**关键实现细节**：
- **构建时环境变量**：`NEXT_PUBLIC_*` 系列变量在构建时注入，会影响静态导出内容。优先读取 Secrets，回退到默认值
- **SPA 路由**：OSS 静态托管通过 `_spa-fallback.html` 实现 SPA 路由兜底（详见 `deploy/oss-website.xml`）

### 10.4 并发控制

每个工作流都配置了串行并发控制，防止同一服务的前次部署尚未完成时触发新部署：

```yaml
concurrency:
  group: deploy-admin-api    # 每个工作流独立的 group
  cancel-in-progress: false  # 不取消正在进行的部署，排队等待
```

此外，每个工作流在部署前会主动检查 SAE 是否有进行中的变更（`LastChangeOrderRunning`），最多等待 120s，超时则中止。

### 10.5 GitHub Secrets 配置

部署到新的生产环境时，需要在 GitHub 仓库 Settings → Secrets and variables → Actions 中配置以下 Secrets：

#### 阿里云凭证（必需）

| Secret 名称 | 说明 |
|-------------|------|
| `ALIYUN_ACCESS_KEY_ID` | RAM 子账号 AccessKey ID（需 SAE/OSS/CDN 权限） |
| `ALIYUN_ACCESS_KEY_SECRET` | RAM 子账号 AccessKey Secret |

#### ACR 容器镜像仓库（ai-agent-service 部署必需）

| Secret 名称 | 说明 |
|-------------|------|
| `ACR_USERNAME` | ACR 登录用户名 |
| `ACR_PASSWORD` | ACR 登录密码 |

#### 前端构建参数（admin-web 部署，可选覆盖）

| Secret 名称 | 默认值 | 说明 |
|-------------|-------|------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.migaozn.com` | Admin API 地址 |
| `NEXT_PUBLIC_AI_API_BASE_URL` | `https://ai-api.migaozn.com` | AI Agent API 地址 |
| `NEXT_PUBLIC_OSS_DOMAIN` | `https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com` | OSS 域名 |
| `NEXT_PUBLIC_COOKIE_DOMAIN` | `.migaozn.com` | Cookie 域名 |
| `NEXT_PUBLIC_ASSET_PREFIX` | （空） | 静态资源前缀 |
| `CDN_REFRESH_DOMAIN` | （空，不刷新） | CDN 刷新域名 |

### 10.6 迁移到新生产环境的注意事项

迁移部署到新环境时，CI/CD 层面需要调整以下内容：

1. **SAE 应用 ID**：修改各工作流 `env` 中的 `SAE_APP_ID` 为新环境的应用 ID
2. **OSS Bucket**：修改 `OSS_BUCKET` 为新环境的 Bucket 名称
3. **ACR 地址**：修改 `ACR_REGISTRY`、`ACR_NAMESPACE` 为新环境的镜像仓库
4. **健康检查地址**：修改 `HEALTH_CHECK_HOST`、`HEALTH_CHECK_IP`、健康检查 URL
5. **前端域名**：通过 Secrets 覆盖 `NEXT_PUBLIC_*` 系列变量
6. **GitHub Secrets**：更新阿里云凭证（AccessKey）、ACR 账号等
7. **SAE 环境变量**：新环境的 SAE 应用需要配置完整的环境变量（RDS、Redis、JWT 密钥、DashScope API Key 等），CI/CD 不会设置这些变量，只会在部署时全量回传已有变量
8. **CORS 白名单**：新环境的后端 `CORS_ALLOWED_ORIGINS` 需包含新前端域名
9. **Cookie 域名**：`COOKIE_DOMAIN` 必须设为新的根域名（如 `.newdomain.com`），不能是 `localhost`

> ⚠️ **重要**：SAE 环境变量必须在控制台或 Terraform 中预先配置好。CI/CD 部署时只做全量回传（防止清空），不会自动创建新的环境变量。

### 10.7 手动触发部署

每个工作流都支持手动触发，适用于：
- 代码未变更但需要重新部署（如 SAE 实例重启后重新拉取镜像）
- 紧急回滚

操作路径：GitHub 仓库 → Actions → 选择工作流 → Run workflow → 选择分支 → 运行

---

## 11. 成本优化

### 11.1 开发环境优化

| 优化项 | 说明 | 节省 |
|--------|------|------|
| 按量付费 | 不用时释放资源 | ~50% |
| 定时开关机 | 非工作时间关闭 SAE | ~30% |
| 百炼免费额度 | qwen-turbo 每月免费 | 100% |
| DashVector 低配 | 开发环境用小集合 | ~50% |
| SLS 免费额度 | 500MB/天免费 | 100% |

### 11.2 定时开关机脚本

```bash
#!/bin/bash
# 关闭 SAE 应用（晚上 8 点）
aliyun sae StopApplication --AppId <app-id>

# 开启 SAE 应用（早上 9 点）
aliyun sae StartApplication --AppId <app-id>
```

### 11.3 资源降配建议

| 服务 | 当前规格 | 建议规格 | 条件 |
|------|---------|---------|------|
| RDS | pg.n2.small.1 | pg.n2.micro.1 | 数据量 < 5GB |
| Redis | redis.master.small.default | redis.basic.small.default | 无集群需求 |
| SAE | 0.5C1G | 按需弹性 | 流量波动大 |

---

## 12. 故障排查

### 12.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| SAE 应用启动失败 | 镜像拉取失败 | 检查 ACR 权限 |
| 数据库连接超时 | 安全组未配置 | 添加入站规则 |
| 百炼 API 调用失败 | API Key 无效 | 检查 Key 是否过期 |
| DashVector 连接失败 | Endpoint 或 API Key 错误 | 检查 DASHVECTOR_ENDPOINT 和 DASHVECTOR_API_KEY |
| 前端 404 | OSS 路径错误 | 检查上传路径 |

### 12.2 日志查询

```bash
# 查询 SAE 日志
aliyun sae GetApplicationLog --AppId <app-id> --Lines 100

# 查询 SLS 日志
aliyun sls GetLogs \
  --project youke-logs \
  --logstore app-logs \
  --from 1704067200 \
  --to 1704153600 \
  --query "level: ERROR"
```

---

## 13. 部署检查清单

### 上线前检查

- [ ] Terraform 基础设施部署完成（2 后端 SAE + OSS Bucket）
- [ ] 数据库迁移执行完成（docs/sql/001~007）
- [ ] 初始租户创建
- [ ] Docker 镜像构建并推送（ai-agent-service, admin-api）
- [ ] SAE 应用部署完成
- [ ] 管理前端构建上传 OSS + CDN 配置
- [ ] API Gateway 路由配置
- [ ] SSL 证书配置
- [ ] 日志采集配置
- [ ] 监控告警配置
- [ ] 数据库备份配置
- [ ] 安全组规则检查
- [ ] DashVector 向量数据库实例创建 & Collection 初始化
- [ ] 百炼 Embedding API 连通性测试
- [ ] 健康检查通过
- [ ] 端到端测试通过（含小程序登录）

---

## 14. 扩容方案

### 14.1 水平扩容

```bash
# SAE 应用扩容
aliyun sae ScaleApplication \
  --AppId <app-id> \
  --Replicas 3
```

### 14.2 数据库扩容

```bash
# RDS 升配
aliyun rds ModifyDBInstanceSpec \
  --DBInstanceId <instance-id> \
  --DBInstanceClass pg.n2.medium.1
```

### 14.3 读写分离

当单实例无法支撑时：

```hcl
resource "alicloud_db_read_write_splitting_connection" "main" {
  instance_id       = alicloud_db_instance.postgres.id
  read_weight_distribution = "0:100,1:0"
}
```

---

这份文档涵盖了从基础设施部署到上线运维的完整流程。你觉得还有哪些地方需要补充或调整？
