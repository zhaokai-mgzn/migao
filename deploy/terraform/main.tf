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
  description = "DashVector 服务端点（实例地址）"
  type        = string
  default     = "https://vrs-cn-hao4rohwn0002h.dashvector.cn-hangzhou.aliyuncs.com"
}

variable "internal_service_secret" {
  description = "服务间 HMAC 认证密钥（admin-api 与 ai-agent-service 内部通信）"
  type        = string
  sensitive   = true
}

variable "cors_allowed_origins" {
  description = "CORS 允许的前端域名（逗号分隔）"
  type        = string
  default     = "https://merchant.migaozn.com,https://admin.migaozn.com"
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
  zone_id      = "${var.region}-h"
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
  instance_type        = "pg.n2.1c.1m"
  instance_storage     = 20
  instance_name        = "${var.project_name}-${var.environment}-pg"
  vswitch_id           = alicloud_vswitch.main.id
  instance_charge_type = "Postpaid"
  security_ips         = ["172.16.0.0/24"]
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
# 使用已有的包年包月 Redis 实例 (r-bp162hozkjd55e18rb, Redis 7.0, 256MB)
# 原按量付费实例 r-bp11f138b581a864 已释放

locals {
  redis_connection_domain = "r-bp162hozkjd55e18rb.redis.rds.aliyuncs.com"
  redis_port              = "6379"
}

# ==================== SAE 环境变量（唯一真相源）====================
# 非敏感值直接写在 map 里，敏感值从 variable 注入。
# 新增环境变量只需在此加一行，无需定义 variable 或改 tfvars。

locals {
  admin_api_envs = merge({
    # 应用
    "SPRING_PROFILES_ACTIVE" = "prod"
    # 数据库
    "RDS_HOST"     = alicloud_db_instance.postgres.connection_string
    "RDS_PORT"     = "5432"
    "RDS_DB"       = "ai_customer_service"
    "RDS_USER"     = "app_user"
    "RDS_PASSWORD" = var.db_password
    # Redis
    "REDIS_HOST"     = local.redis_connection_domain
    "REDIS_PORT"     = "6379"
    "REDIS_PASSWORD" = var.redis_password
    # JWT
    "JWT_PRIVATE_KEY" = "classpath:rsa/private.pem"
    "JWT_PUBLIC_KEY"  = "classpath:rsa/public.pem"
    # 内部通信
    "SERVICE_TOKEN_SECRET" = var.internal_service_secret
    # CORS / Cookie
    "CORS_ALLOWED_ORIGINS" = var.cors_allowed_origins
    "COOKIE_DOMAIN"        = var.cookie_domain
    # 微信小程序
    "WECHAT_MINI_APPID"    = var.wechat_mini_appid
    "WECHAT_MINI_SECRET"   = var.wechat_mini_appsecret
    # OSS
    "OSS_ENDPOINT"        = "oss-cn-hangzhou-internal.aliyuncs.com"
    "OSS_ACCESS_KEY_ID"   = var.oss_access_key_id
    "OSS_ACCESS_KEY_SECRET" = var.oss_access_key_secret
    "OSS_BUCKET_NAME"     = alicloud_oss_bucket.admin_frontend.bucket
    "OSS_URL_PREFIX"      = "https://admin.migaozn.com"
  })

  ai_agent_envs = merge({
    # 应用基础
    "DEBUG"   = "false"
    "HOST"    = "0.0.0.0"
    "PORT"    = "8000"
    "APP_ENV" = var.environment
    # 数据库
    "DATABASE_URL" = "postgresql+asyncpg://app_user:${var.db_password}@${alicloud_db_instance.postgres.connection_string}:5432/ai_customer_service"
    "REDIS_URL"    = "redis://:${var.redis_password}@${local.redis_connection_domain}:${local.redis_port}/0"
    # DashScope LLM
    "DASHSCOPE_API_KEY"         = var.dashscope_api_key
    "DASHSCOPE_BASE_URL"        = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    "DASHSCOPE_MODEL"           = "qwen3.7-max"
    "DASHSCOPE_EMBEDDING_MODEL" = "text-embedding-v3"
    # DashVector
    "DASHVECTOR_API_KEY"    = var.dashvector_api_key
    "DASHVECTOR_ENDPOINT"   = var.dashvector_endpoint
    "DASHVECTOR_COLLECTION" = "ai_customer_service"
    # 内部通信
    "ADMIN_API_BASE_URL" = "http://172.16.0.122"
    "SERVICE_TOKEN"      = var.internal_service_secret
    "JWT_PUBLIC_KEY"     = var.jwt_public_key
    # 物流查询
    "LOGISTICS_API_URL" = "https://wuliu.market.alicloudapi.com/kdi"
    "LOGISTICS_APPCODE" = "d9fca154dd9c47578736b2de19056eb6"
    # SSE / CORS
    "SSE_TIMEOUT"          = "300"
    "SSE_PING_INTERVAL"    = "30"
    "CORS_ALLOWED_ORIGINS" = var.cors_allowed_origins
  })
}

# ==================== ACR 容器镜像仓库 ====================
# 注意：ACR 个人版需要先在控制台手动激活，Terraform 无法自动初始化
# 激活后可取消注释并重新 apply
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
#
# admin-api 已改为 FatJar 部署，不再需要 ACR 镜像仓库
# resource "alicloud_cr_repo" "admin_api" {
#   namespace = alicloud_cr_namespace.main.name
#   name      = "admin-api"
#   repo_type = "PRIVATE"
#   summary   = "管理后台 API 镜像（Java 21 / Spring Boot 3.3）"
# }

# ==================== SAE 命名空间 ====================

resource "alicloud_sae_namespace" "main" {
  namespace_id          = "${var.region}:${replace(var.project_name, "-", "")}${var.environment}"
  namespace_name        = "${var.project_name}-${var.environment}"
  namespace_description = "AI 智能客服系统 ${var.environment} 环境"
}

# ==================== SAE 应用：admin-api（Java 21 / Spring Boot 3.3）====================
# 部署方式：FatJar（JAR 包直接部署，无需 Docker 镜像）

resource "alicloud_sae_application" "admin_api" {
  app_name          = "${var.project_name}-admin-api"
  namespace_id      = alicloud_sae_namespace.main.id
  package_type      = "FatJar"
  package_url       = "https://${alicloud_oss_bucket.admin_frontend.bucket}.oss-cn-hangzhou.aliyuncs.com/deploy/admin-api.jar"
  package_version   = "1.0.0"
  jdk               = "Open JDK 21"
  replicas          = 1
  cpu               = 1000
  memory            = 2048
  vpc_id            = alicloud_vpc.main.id
  vswitch_id        = alicloud_vswitch.main.id
  security_group_id = alicloud_security_group.main.id

  envs = jsonencode([for k, v in local.admin_api_envs : { name = k, value = v }])

  liveness = jsonencode({
    httpGet = {
      path   = "/actuator/health"
      port   = 8080
      scheme = "HTTP"
    }
    initialDelaySeconds = 30
    periodSeconds       = 10
  })

  readiness = jsonencode({
    httpGet = {
      path   = "/actuator/health"
      port   = 8080
      scheme = "HTTP"
    }
    initialDelaySeconds = 20
    periodSeconds       = 10
  })

  sls_configs = jsonencode([
    {
      logDir       = ""
      logType      = "stdout"
      projectName  = alicloud_log_project.main.project_name
      logstoreName = alicloud_log_store.admin_api.logstore_name
    }
  ])
}

# ==================== SAE 应用：ai-agent-service（Python 3.11 / FastAPI）====================

resource "alicloud_sae_application" "ai_agent_service" {
  app_name          = "${var.project_name}-ai-agent"
  namespace_id      = alicloud_sae_namespace.main.id
  package_type      = "Image"
  image_url         = "registry.${var.region}.aliyuncs.com/${var.project_name}/ai-agent-service:latest"
  replicas          = 1
  cpu               = 1000
  memory            = 2048
  vpc_id            = alicloud_vpc.main.id
  vswitch_id        = alicloud_vswitch.main.id
  security_group_id = alicloud_security_group.main.id

  envs = jsonencode([for k, v in local.ai_agent_envs : { name = k, value = v }])

  liveness = jsonencode({
    httpGet = {
      path   = "/health"
      port   = 8000
      scheme = "HTTP"
    }
    initialDelaySeconds = 20
    periodSeconds       = 10
  })

  readiness = jsonencode({
    httpGet = {
      path   = "/health"
      port   = 8000
      scheme = "HTTP"
    }
    initialDelaySeconds = 15
    periodSeconds       = 10
  })

  sls_configs = jsonencode([
    {
      logDir       = ""
      logType      = "stdout"
      projectName  = alicloud_log_project.main.project_name
      logstoreName = alicloud_log_store.ai_agent_service.logstore_name
    }
  ])
}

# ==================== SLS 日志服务 ====================

resource "alicloud_log_project" "main" {
  project_name = "youke-logs"
  description  = "AI Customer Service 日志项目"
}

resource "alicloud_log_store" "ai_agent_service" {
  project_name          = alicloud_log_project.main.project_name
  logstore_name         = "ai-agent-service"
  shard_count           = 2
  auto_split            = true
  max_split_shard_count = 60
  retention_period      = 30
}

resource "alicloud_log_store" "admin_api" {
  project_name          = alicloud_log_project.main.project_name
  logstore_name         = "admin-api"
  shard_count           = 2
  auto_split            = true
  max_split_shard_count = 60
  retention_period      = 30
}

# ==================== OSS 静态资源存储（管理前端 Next.js 静态托管）====================

resource "alicloud_oss_bucket" "admin_frontend" {
  bucket = "${var.project_name}-admin-${var.environment}"
  website {
    index_document = "index.html"
    error_document = "404.html"
  }
}

resource "alicloud_oss_bucket_acl" "admin_frontend" {
  bucket = alicloud_oss_bucket.admin_frontend.bucket
  acl    = "public-read"
}

# ==================== 输出 ====================

output "database_connection" {
  description = "RDS PostgreSQL 内网连接地址"
  value       = alicloud_db_instance.postgres.connection_string
}

output "redis_connection" {
  description = "Redis 内网连接地址"
  value       = local.redis_connection_domain
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
  value       = var.project_name
}
