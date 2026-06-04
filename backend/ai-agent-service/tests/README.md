# E2E 测试规范

## 测试环境架构

本项目 E2E 测试采用**混合环境**策略：

```
┌─────────────────────────────────────────────────────────┐
│  本地开发环境（Local）                                    │
├─────────────────────────────────────────────────────────┤
│  ✓ admin-web (Next.js)        http://localhost:3001     │
│  ✓ admin-api (NestJS)         http://localhost:3000     │
│  ✓ ai-agent-service (Python)  http://localhost:8000     │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ 连接
                     ▼
┌─────────────────────────────────────────────────────────┐
│  云 dev 环境基础设施（Cloud Dev）                         │
├─────────────────────────────────────────────────────────┤
│  ✓ PostgreSQL (RDS)           pgm-bp1p7w92k81ob5to      │
│  ✓ Redis (ElastiCache)        r-bp162hozkjd55e18rbpd    │
│  ✓ DashVector (向量数据库)      vrs-cn-hao4rohwn0002h   │
│  ✓ OSS (对象存储)              oss-cn-hangzhou           │
└─────────────────────────────────────────────────────────┘
```

**核心原则：**
- **本地服务**：3 个应用服务全部在本地启动，确保代码变更即时生效
- **云 dev 数据库**：PostgreSQL、Redis、DashVector 使用阿里云 dev 环境，避免本地安装和维护
- **OSS 双 Bucket**：使用 dev 环境的 OSS，验证路由逻辑

## 前置条件

### 1. Playwright 浏览器安装

```bash
cd tests
npm install
npx playwright install chromium
```

**验证安装：**
```bash
npx playwright --version
# 应输出版本号，如 Version 1.49.1
```

### 2. 环境变量配置

#### 2.1 admin-api (.env)

```bash
# 数据库（云 dev）
DB_HOST=pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com
DB_PORT=5432
DB_USERNAME=migao_admin
DB_PASSWORD=Migao2026!
DB_DATABASE=ai_customer_service

# Redis（云 dev）
REDIS_HOST=r-bp162hozkjd55e18rbpd.redis.rds.aliyuncs.com
REDIS_PORT=6379
REDIS_PASSWORD=Redis2026Migao!Secure

# OSS（云 dev，双 Bucket）
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=LTAI5t7vKsSNF1tif3vq4GTv
OSS_ACCESS_KEY_SECRET=<your-secret>
OSS_PERMANENT_BUCKET=youke-admin-dev
OSS_TEMPORARY_BUCKET=youke-chat-dev

# 服务端口
PORT=3000
```

#### 2.2 ai-agent-service (.env)

```bash
# 数据库（云 dev）
DATABASE_URL=postgresql+asyncpg://migao_admin:Migao2026!@pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com:5432/ai_customer_service

# Redis（云 dev）
REDIS_URL=redis://:Redis2026Migao!Secure@r-bp162hozkjd55e18rbpd.redis.rds.aliyuncs.com:6379/0

# DashVector（云 dev）
DASHVECTOR_API_KEY=<your-api-key>
DASHVECTOR_ENDPOINT=vrs-cn-hao4rohwn0002h.dashvector.cn-hangzhou.aliyuncs.com

# 服务端口
PORT=8000
```

#### 2.3 admin-web (.env.local)

```bash
# API 端点（本地）
NEXT_PUBLIC_API_BASE_URL=http://localhost:3000
NEXT_PUBLIC_AI_API_BASE_URL=http://localhost:8000

# OSS 域名（云 dev）
NEXT_PUBLIC_OSS_DOMAIN=https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com
```

### 3. 数据库 Schema 初始化

确保云 dev 数据库已执行最新的 schema 迁移：

```bash
cd backend/admin-api
npm run db:migrate:dev
```

**验证表结构：**
```bash
# 连接数据库
psql -h pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com \
     -U migao_admin \
     -d ai_customer_service

# 检查关键表
\dt
# 应包含：users, tenants, products, orders, chat_sessions 等
```

### 4. 网络连通性验证

```bash
# 测试 PostgreSQL 连通性
nc -zv pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com 5432
# 应输出：Connection to ... succeeded

# 测试 Redis 连通性
nc -zv r-bp162hozkjd55e18rbpd.redis.rds.aliyuncs.com 6379
# 应输出：Connection to ... succeeded

# 测试 OSS 连通性
curl -I https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com
# 应返回 HTTP/1.1 200 或 403（表示可访问）
```

## 启动测试环境

### 步骤 1：启动后端服务

```bash
# 终端 1：启动 admin-api
cd backend/admin-api
npm run start:dev

# 终端 2：启动 ai-agent-service
cd backend/ai-agent-service
npm run start:dev

# 终端 3：启动 admin-web（E2E 会自动启动，也可手动启动）
cd frontend/admin-web
npm run dev
```

**验证服务健康：**
```bash
curl http://localhost:3000/health  # admin-api
curl http://localhost:8000/health  # ai-agent-service
curl http://localhost:3001         # admin-web
```

### 步骤 2：运行 E2E 测试

```bash
cd tests

# 运行所有测试
npm run e2e

# 运行单个测试文件
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts

# 调试模式（带浏览器 UI）
npm run e2e:debug

# 查看测试报告
npm run e2e:report
```

## 测试文件组织

```
tests/
├── e2e/
│   ├── fixtures/           # 测试数据和工具
│   │   ├── auth.setup.ts   # 认证前置条件
│   │   └── test-image.png  # 测试图片
│   ├── specs/              # 测试用例
│   │   ├── auth/           # 认证相关
│   │   ├── products/       # 商品管理
│   │   ├── orders/         # 订单管理
│   │   ├── chat/           # 聊天功能
│   │   └── storage/        # 存储相关（OSS）
│   └── pages/              # Page Object Model
├── playwright.config.ts    # Playwright 配置
└── README.md               # 本文档
```

## TDD 流程集成

根据项目 TDD 规范，新增功能时必须：

1. **Red 阶段**：先写 E2E 测试，验证测试失败（功能不存在）
2. **Green 阶段**：实现功能，验证测试通过
3. **Refactor 阶段**：重构代码，保持测试通过

**示例：OSS 双 Bucket 功能**

```bash
# 1. Red：运行测试，确认失败
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts
# 预期：测试失败，因为 selectBucket 逻辑未实现

# 2. Green：实现 selectBucket 逻辑
# 在 OssService.java 中添加路由逻辑

# 3. Refactor：优化代码，保持测试通过
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts
# 预期：测试全部通过
```

## 常见错误排查

### 错误 1：Playwright 浏览器未安装

**错误信息：**
```
Executable doesn't exist at /Users/xxx/Library/Caches/ms-playwright/...
```

**解决方案：**
```bash
npx playwright install chromium
```

### 错误 2：数据库连接失败

**错误信息：**
```
Error: connect ECONNREFUSED pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com:5432
```

**排查步骤：**
1. 检查 `.env` 中的数据库配置是否正确
2. 验证网络连通性：`nc -zv <host> 5432`
3. 确认 IP 白名单是否包含本地 IP

### 错误 3：OSS Bucket 不存在

**错误信息：**
```
NoSuchBucket: The specified bucket does not exist.
```

**解决方案：**
1. 检查 `.env` 中的 `OSS_PERMANENT_BUCKET` 和 `OSS_TEMPORARY_BUCKET`
2. 确认 Bucket 已在阿里云控制台创建
3. 验证 Bucket 名称拼写（区分大小写）

### 错误 4：前端服务启动超时

**错误信息：**
```
Error: Page.goto: Timeout 30000ms exceeded.
```

**解决方案：**
1. 手动启动前端：`cd frontend/admin-web && npm run dev`
2. 检查端口占用：`lsof -i :3001`
3. 增加超时时间：修改 `playwright.config.ts` 中的 `timeout`

## 持续集成（CI）

在 CI 环境中，E2E 测试会自动运行：

```yaml
# .github/workflows/e2e.yml
- name: Run E2E tests
  run: |
    cd tests
    npm install
    npx playwright install --with-deps chromium
    npm run e2e
```

**CI 环境差异：**
- 使用 CI 专用的数据库和 Redis（避免污染 dev 环境）
- 禁用 webServer 自动启动（由 CI 脚本管理）
- 生成测试报告并上传到 Artifacts

## 参考文档

- [Playwright 官方文档](https://playwright.dev/docs/intro)
- [项目部署文档](../docs/deployment/deployment-aliyun.md)
- [OSS 双 Bucket 设计文档](../docs/deployment/oss-storage-strategy.md)
- [TDD 规范](../CLAUDE.md#tdd-规范)
