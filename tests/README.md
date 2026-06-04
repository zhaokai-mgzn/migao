# E2E 测试规范

## 前置条件检查

在运行 E2E 测试前，**必须先检查**以下环境是否满足：

### 1. 浏览器检查（二选一即可）

Playwright 已配置使用本地 Chrome（通过 `channel: 'chrome'`），**不需要额外下载 Chromium**。

**检查方法：**

```bash
# 检查本地是否安装了 Chrome
ls -la "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" 2>/dev/null || echo "未找到 Chrome"

# 或者检查是否有 Chromium
ls -la ~/.cache/ms-playwright/ 2>/dev/null | grep chromium || echo "未找到 Chromium"
```

**规则：**
- ✅ 如果本地有 Chrome → **跳过安装，直接运行测试**
- ✅ 如果已有 Playwright Chromium → **跳过安装，直接运行测试**
- ❌ 只有两者都没有时，才需要安装：`npx playwright install chromium`

**配置说明：**

`playwright.config.ts` 已配置使用本地 Chrome：

```typescript
use: {
  ...devices['Desktop Chrome'],
  channel: 'chrome', // 使用本地已安装的 Chrome
},
```

### 2. 测试图片 fixture

**检查方法：**

```bash
ls -la tests/e2e/fixtures/test-image.png
```

**如果不存在，创建测试图片：**

```bash
# 创建 1x1 像素的透明 PNG
echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" | base64 -d > tests/e2e/fixtures/test-image.png
```

### 3. 环境变量配置（敏感信息，不提交 Git）

**⚠️ 重要：所有 `.env` 文件都在 `.gitignore` 中，不会被提交到远程仓库。**

需要配置以下文件（如果不存在则从 `.env.example` 复制）：

#### backend/admin-api/.env

```bash
# OSS 配置（双 Bucket 策略）
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=<your-key-id>
OSS_ACCESS_KEY_SECRET=<your-key-secret>
OSS_BUCKET_NAME=ai-customer-service-admin-dev
OSS_URL_PREFIX=https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com
OSS_PERMANENT_BUCKET=ai-customer-service-admin-dev
OSS_TEMPORARY_BUCKET=ai-customer-service-admin-dev
```

#### backend/ai-agent-service/.env

```bash
# 指向本地 admin-api
ADMIN_API_BASE_URL=http://localhost:8080

# OSS 配置（双 Bucket 策略）
OSS_PERMANENT_BUCKET=ai-customer-service-admin-dev
OSS_TEMPORARY_BUCKET=ai-customer-service-admin-dev

# JWT 公钥（必须与 admin-api 的 rsa/public.pem 一致）
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
```

#### frontend/admin-web/.env.development

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8080
NEXT_PUBLIC_AI_API_BASE_URL=http://localhost:8001
NEXT_PUBLIC_OSS_DOMAIN=https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com
```

## 启动本地服务

### ⚠️ 运行 E2E 前必须重启所有服务

**铁律：每次运行 E2E 测试前，必须先 kill 掉所有旧进程，再重新启动。**

旧进程可能加载了过期的 `.env` 配置（如 OSS bucket 名、JWT 公钥、端口号等），导致 E2E 测试出现假失败，掩盖真实的代码 bug。

```bash
# ═══════════════════════════════════════════════════════
# Step 1：清理旧进程
# ═══════════════════════════════════════════════════════
pkill -f "spring-boot\|AdminApiApplication\|mvn.*admin-api" 2>/dev/null
pkill -f "uvicorn.*8001\|ai-agent-service" 2>/dev/null
pkill -f "next.*3001\|next-server" 2>/dev/null
sleep 3

# 确认没有残留进程
ps aux | grep -E "admin-api|ai-agent|next.*3001" | grep -v grep || echo "✅ 所有旧进程已清理"

# ═══════════════════════════════════════════════════════
# Step 2：重启服务
# ═══════════════════════════════════════════════════════

# 终端 1：启动 admin-api（加载 .env 配置）
cd backend/admin-api
mvn spring-boot:run -Dspring-boot.run.arguments="--spring.config.import=optional:file:.env"

# 终端 2：启动 ai-agent-service（端口 8001）
cd backend/ai-agent-service
.venv/bin/python -m uvicorn app.main:app --port 8001 --reload

# 终端 3：启动 admin-web（E2E 测试会自动启动，也可手动启动）
cd frontend/admin-web
npm run dev
```

**验证服务健康：**

```bash
curl http://localhost:8080/actuator/health  # admin-api
curl http://localhost:8001/health            # ai-agent-service
curl http://localhost:3001                   # admin-web
```

## 运行 E2E 测试

### Step 0：Auth Setup（首次或 auth 过期时）

```bash
cd tests
npx playwright test --project=auth-setup
```

### 运行全部测试

```bash
cd tests
npm run e2e
```

### 运行单个测试文件

```bash
# 运行 OSS 双 Bucket 测试
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts

# 运行商品相关测试
npm run e2e -- specs/products/product-create.spec.ts
```

### 调试模式

```bash
# 带 UI 的调试模式
npm run e2e:debug

# 查看测试报告
npm run e2e:report
```

## 测试文件结构

```
tests/e2e/
├── specs/                    # 测试用例
│   ├── auth/                 # 认证相关
│   ├── products/             # 商品管理
│   ├── orders/               # 订单管理
│   ├── chat/                 # 聊天功能
│   └── storage/              # 存储相关（OSS）
│       └── oss-dual-bucket.spec.ts  # OSS 双 Bucket 路由测试
├── fixtures/                 # 测试数据
│   ├── auth.setup.ts         # 认证 setup
│   └── test-image.png        # 测试图片
└── helpers/                  # 辅助函数
    └── auth.helper.ts        # 认证 helper
```

## TDD 流程集成

根据项目 TDD 规范，新增功能时必须遵循 Red → Green → Refactor：

1. **Red 阶段**：先写 E2E 测试，运行确认 FAIL
2. **Green 阶段**：实现功能，运行确认 PASS
3. **Refactor 阶段**：重构代码，保持测试 PASS

**示例：OSS 双 Bucket 功能**

```bash
# 1. Red：运行测试，确认失败
cd tests
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts
# 预期：测试失败（功能未实现）

# 2. Green：实现功能
# 在 backend/admin-api 中实现 OssService.selectBucket()

# 3. Refactor：运行测试，确认通过
npm run e2e -- specs/storage/oss-dual-bucket.spec.ts
# 预期：测试全部通过
```

## 常见错误

### 1. "Executable doesn't exist" 错误

**错误信息：**
```
Executable doesn't exist at /Users/xxx/Library/Caches/ms-playwright/chromium-xxx
```

**解决方案：**
- 检查本地是否有 Chrome：`ls -la "/Applications/Google Chrome.app"`
- 如果有 Chrome，确认 `playwright.config.ts` 配置了 `channel: 'chrome'`
- 如果没有 Chrome，安装 Chromium：`npx playwright install chromium`

### 2. 数据库连接失败

**错误信息：**
```
Error: connect ECONNREFUSED pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com:5432
```

**解决方案：**
- 检查网络连接（云 dev 数据库需要公网访问）
- 验证 `.env` 中的数据库配置是否正确
- 确认 IP 白名单（如需要）

### 3. 本地服务未启动

**错误信息：**
```
Error: page.goto: Timeout 30000ms exceeded
```

**解决方案：**
- 确保 3 个本地服务都已启动（admin-api、ai-agent-service、admin-web）
- 验证服务健康检查：`curl http://localhost:8080/actuator/health`
- 检查端口占用：`lsof -i :8080`

### 4. 旧进程加载了过期配置

**症状：**
- 上传接口返回的 URL 包含错误的 bucket 名（如 `mgzn-admin` 而非 `ai-customer-service-admin-dev`）
- 图片 URL 返回 403 Forbidden（旧 bucket 是私有的）
- AI 服务 JWT 验签失败（`Could not parse the provided public key`）

**解决方案：**
- **立即重启所有服务**（见"启动本地服务"章节 Step 1）
- 确认 `.env` 中的 bucket 名、JWT 公钥、端口号与实际值一致
- 重启后先跑 auth-setup，再跑业务测试

## 参考资料

- [Playwright 官方文档](https://playwright.dev/docs/intro)
- [项目 TDD 规范](../CLAUDE.md)
- [OSS 双 Bucket 设计文档](../docs/fixes/oss-dual-bucket-storage.md)
