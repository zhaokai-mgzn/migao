# 有客全栈部署终极清单

## 一、历史部署问题总结

按严重程度排列所有遇过的问题：

### P0 - 导致服务不可用

1. **SAE环境变量指向已释放实例** - RDS/Redis 实例更换后，SAE Envs 中的 HOST/USER/PASSWORD 未同步更新，导致连接池报认证失败，Pod 反复重启，API 返回 503
2. **SAE部署不带 --Envs 参数** - 环境变量被清空，服务启动失败（SAE 没有独立的环境变量更新API，必须 DeployApplication 时全量重发）
3. **CORS白名单不含前端实际域名** - 域名从 admin.migaozn.com 迁移到 merchant.migaozn.com 后，后端 CORS 白名单没有同步更新，Axios 将 CORS 错误包装为 "Network Error"
4. **OSS 签名 URL 过期** - 复用旧的 PackageUrl，SAE wget 下载失败（exit 8），部署超时
5. **JDK 版本不匹配** - 本地用 JDK 21 编译，SAE 运行环境配了 JDK 17，运行时崩溃
6. **Spring Bean 同名冲突** - 多个配置类注册同名 Bean，导致 SAE 部署后启动 BeanCreationException
7. **COOKIE_DOMAIN 配置为 localhost** - SAE 环境变量中 COOKIE_DOMAIN 设为 localhost，导致 Set-Cookie 响应头 Domain=localhost，浏览器在 merchant.migaozn.com 下拒绝写入 Cookie，Axios 将其包装为 "Network Error"。表现像 CORS 问题但实际是 Cookie 域名不匹配。修复：COOKIE_DOMAIN 必须设为 `.migaozn.com`（前导点表示所有子域名共享）

### P1 - 导致功能异常

8. **新 RDS 缺少增量 schema 迁移** - 更换 RDS 实例后只有基础 schema，缺少后续迁移创建的表/列，多个接口返回 500
9. **.env.local 覆盖生产构建** - Next.js .env.local 会覆盖所有环境（包括 production 构建），如果里面设了 API 地址则生产包也用本地地址
10. **前端构建后忘记上传 OSS** - build 和 upload 没有连续执行，部署后页面仍是旧版本
11. **CDN 缓存未刷新** - 前端文件已上传到 OSS 但 CDN 缓存了旧版，用户访问仍是旧页面
12. **Cookie 立即过期** - HttpOnly cookie 的 maxAge 配置为 days=0，Session 无法持久化
13. **AuthGuard 水合竞态** - 静态导出首次加载时 hydration 尚未完成就触发路由跳转

### P2 - 影响运维效率

14. **VPC 缺少 NAT 网关** - AI Agent 服务无法访问外网（百炼 API），导致 LLM 调用超时
15. **DNS 域名配置错误** - smoke 测试中使用了从未配置的域名，导致 NXDOMAIN
16. **SLB 内网端口错误** - 内网调用必须用 80 端口（非 8080），否则连接拒绝
17. **PR rebase 后文件丢失** - rebase 冲突解决时遗漏新增文件，main 分支编译失败

## 二、不可跳过的部署流程

### 阶段 0：前置条件确认（2分钟）

```bash
# 0.1 确认代码同步
cd /Users/zhaokai/migao/youke
git checkout main && git pull origin main
git status  # 确认没有未提交的修改

# 0.2 确认环境变量一致性
echo "检查 SAE admin-api 环境变量..."
CURRENT_ENVS=$(aliyun sae DescribeApplicationConfig \
  --AppId d6a22f49-0c01-48fc-8d0a-7254284a6a16 \
  --region cn-hangzhou --profile sae-deploy 2>/dev/null | jq -r '.Data.Envs')

# 必须校验以下关键变量存在且正确：
echo "$CURRENT_ENVS" | jq -r '.[] | select(.name | test("RDS_HOST|RDS_USER|RDS_PASSWORD|REDIS_HOST|REDIS_PASSWORD|CORS_ALLOWED_ORIGINS|COOKIE_DOMAIN")) | "\(.name)=\(.value)"'

# ⚠️ COOKIE_DOMAIN 必须为 .migaozn.com，绝对不能是 localhost！
COOKIE_DOMAIN_VAL=$(echo "$CURRENT_ENVS" | jq -r '.[] | select(.name=="COOKIE_DOMAIN") | .value')
if [ "$COOKIE_DOMAIN_VAL" != ".migaozn.com" ]; then
  echo "❌ 致命：COOKIE_DOMAIN=$COOKIE_DOMAIN_VAL，必须为 .migaozn.com"; exit 1
fi

# 0.3 确认 RDS/Redis 实例可达
# （如果近期更换了实例，必须确认凭据已更新）
```

**铁律：如果环境变量中的 RDS_HOST/REDIS_HOST 指向已释放的实例，必须先更新 SAE 环境变量再继续。**

### 阶段 1：编译门禁（3分钟，串行）

```bash
# 1.1 后端编译
cd /Users/zhaokai/migao/youke/backend/admin-api
mvn compile -q
if [ $? -ne 0 ]; then echo "❌ 后端编译失败，停止部署"; exit 1; fi

# 1.2 前端构建（同时生成 out/ 目录用于部署）
cd /Users/zhaokai/migao/youke/frontend/admin-web
npx next build
if [ $? -ne 0 ]; then echo "❌ 前端构建失败，停止部署"; exit 1; fi

echo "✅ 门禁通过"
```

**铁律：任一失败停止一切，先修后部署。**

### 阶段 2：三服务并行部署（5-8分钟）

#### 2.1 admin-api（手动）

```bash
cd /Users/zhaokai/migao/youke/backend/admin-api
mvn clean package -DskipTests -q

# 上传 JAR
ossutil cp target/admin-api-0.0.1-SNAPSHOT.jar \
  oss://ai-customer-service-admin-dev/deploy/admin-api.jar --force

# ⚠️ 每次部署必须重新签名！
SIGNED_URL=$(aliyun oss sign oss://ai-customer-service-admin-dev/deploy/admin-api.jar \
  --timeout 86400 --region cn-hangzhou \
  --endpoint oss-cn-hangzhou.aliyuncs.com --profile sae-deploy 2>/dev/null | grep -o 'https://[^ ]*')

# ⚠️ 必须全量获取当前环境变量！
CURRENT_ENVS=$(aliyun sae DescribeApplicationConfig \
  --AppId d6a22f49-0c01-48fc-8d0a-7254284a6a16 \
  --region cn-hangzhou --profile sae-deploy 2>/dev/null | jq -r '.Data.Envs')

# 部署
aliyun sae DeployApplication \
  --AppId d6a22f49-0c01-48fc-8d0a-7254284a6a16 \
  --PackageUrl "$SIGNED_URL" \
  --PackageType FatJar \
  --Envs "$CURRENT_ENVS" \
  --Jdk "Open JDK 21" \
  --region cn-hangzhou --profile sae-deploy
```

#### 2.2 ai-agent-service（自动）

```bash
# push 到 main 后 GitHub Actions 自动部署
gh run list --repo zhaokai-mgzn/youke --workflow=deploy-ai-agent-service.yml --limit 1
```

#### 2.3 admin-web（手动）

```bash
cd /Users/zhaokai/migao/youke/frontend/admin-web
# out/ 已在门禁阶段生成
ossutil cp -r out/ oss://ai-customer-service-admin-dev/ --update --force
```

### 阶段 3：部署后验证（必须全通过才算交付）

```bash
# 3.1 等待 SAE 部署完成（约 2-3 分钟）
sleep 180

# 3.2 后端健康检查
echo "--- admin-api 健康检查 ---"
curl -s -w "\nHTTP %{http_code}\n" https://api.migaozn.com/actuator/health
# 期望：HTTP 200 且 status: UP

# 3.3 前端可访问性
echo "--- admin-web 可访问性 ---"
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://merchant.migaozn.com/login
# 期望：HTTP 200

# 3.4 CORS 验证（关键！）
echo "--- CORS 预检验证 ---"
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  -X OPTIONS https://api.migaozn.com/api/auth/admin/login \
  -H "Origin: https://merchant.migaozn.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type"
# 期望：HTTP 200 且响应头包含 Access-Control-Allow-Origin

# 3.5 登录端点验证（含 Cookie Domain 检查）
echo "--- 登录接口验证 ---"
LOGIN_HEADERS=$(curl -s -D - -X POST https://api.migaozn.com/api/auth/admin/login \
  -H "Content-Type: application/json" \
  -H "Origin: https://merchant.migaozn.com" \
  -d '{"username":"admin","password":"Admin@2024","tenantId":1}')
echo "$LOGIN_HEADERS" | grep -i "Set-Cookie"
# ⚠️ 关键检查：Set-Cookie 头中 Domain 必须为 .migaozn.com，绝不能是 localhost
# 如果 Domain=localhost，说明 SAE 环境变量 COOKIE_DOMAIN 配置错误
echo "$LOGIN_HEADERS" | grep -i "Set-Cookie" | grep -i "Domain" | grep -q "migaozn.com" \
  && echo "✅ Cookie Domain 正确" \
  || echo "❌ Cookie Domain 异常！检查 SAE COOKIE_DOMAIN 环境变量"
# 期望：success=true 或 AUTH_FAILED（不能是 Network Error / CORS 拦截 / 500）

# 3.6 ai-agent-service 健康检查
echo "--- ai-agent-service 健康检查 ---"
curl -s -w "\nHTTP %{http_code}\n" https://ai-api.migaozn.com/health
# 期望：HTTP 200
```

**铁律：6 项验证全部通过才能宣布部署完成。任一失败必须立即定位修复。**

## 三、特殊场景补充清单

### 场景 A：更换 RDS/Redis 实例后

- [ ] 新实例已创建并可连接
- [ ] SAE 环境变量中 RDS_HOST/PORT/USER/PASSWORD 已更新
- [ ] SAE 环境变量中 REDIS_HOST/PORT/PASSWORD 已更新
- [ ] Redis 密码通过 ModifyInstanceAttribute + ResetAccountPassword 双重设置
- [ ] 新 RDS 已执行所有 SQL 迁移脚本（docs/sql/ 下全部文件）
- [ ] 新 RDS 已有种子数据（roles、permissions、admin 用户）
- [ ] 部署命令中包含 --Envs 全量重发
- [ ] 部署后 actuator/health 显示 db: UP, redis: UP

### 场景 B：域名迁移后

- [ ] DNS 记录已切换到新域名
- [ ] 后端 CORS_ALLOWED_ORIGINS 包含新域名
- [ ] SAE 环境变量中 CORS 已更新并重新部署
- [ ] 前端 .env.production 中 API 地址不变（仍是 api.migaozn.com）
- [ ] CDN/OSS 已配置新域名的回源规则
- [ ] SSL 证书覆盖新域名（通配符证书 *.migaozn.com）
- [ ] CORS 预检请求从新域名发起时返回 200

### 场景 C：前端更新后

- [ ] .env.local 中不含 NEXT_PUBLIC_API_BASE_URL（避免覆盖生产配置）
- [ ] next build 成功且 out/ 目录存在
- [ ] 构建产物中 API 地址正确：grep "api.migaozn.com" out/_next/static/chunks/*.js
- [ ] ossutil cp 上传完成
- [ ] CDN 缓存已刷新（如有 CDN）：aliyun cdn RefreshObjectCaches --ObjectPath "https://merchant.migaozn.com/"
- [ ] 浏览器清缓存后能正常加载新版本

## 四、关键配置速查表

| 项目 | 值 |
|------|-----|
| admin-api AppId | d6a22f49-0c01-48fc-8d0a-7254284a6a16 |
| ai-agent-service AppId | 01c0759f-4a81-494f-9947-0113d38b86c2 |
| OSS Bucket | ai-customer-service-admin-dev |
| 前端域名 | merchant.migaozn.com |
| 后端 API 域名 | api.migaozn.com |
| AI Agent 域名 | ai-api.migaozn.com |
| RDS Host | pgm-bp1p7w92k81ob5to.pg.rds.aliyuncs.com |
| RDS User | migao_admin |
| Redis Host | r-bp162hozkjd55e18rb.redis.rds.aliyuncs.com |
| SAE Region | cn-hangzhou |
| aliyun profile | sae-deploy（SAE操作）/ oss-bucket-put-object（OSS签名）|
| JDK 版本 | Open JDK 21 |
| COOKIE_DOMAIN | .migaozn.com（前导点，所有子域名共享） |
| CORS 白名单 | https://admin.migaozn.com,https://merchant.migaozn.com,http://localhost:3000 |

## 五、紧急回滚方案

如果部署后服务异常：

```bash
# 回滚 admin-api（部署前一个版本）
aliyun sae RollbackApplication \
  --AppId d6a22f49-0c01-48fc-8d0a-7254284a6a16 \
  --region cn-hangzhou --profile sae-deploy

# 回滚前端（OSS 无版本管理，需要 git checkout 上一版本重新 build + upload）
cd /Users/zhaokai/migao/youke/frontend/admin-web
git log --oneline -5  # 找到上一个稳定 commit
git checkout <commit>
npx next build && ossutil cp -r out/ oss://ai-customer-service-admin-dev/ --update --force
git checkout main  # 回到 main
```
