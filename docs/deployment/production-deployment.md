# 生产环境部署方案（未来）

> 状态：**设计文档**。当前生产部署目标为测试环境（单台 SWAS：api.migaozn.com / ai-api.migaozn.com / admin.migaozn.com），
> 自动部署已足够。本页定义**未来正式生产环境**的部署与发布方案。
> 关联：`deploy-prod.yml`（生产发布工作流）、[rollback.md](rollback.md)、[CI-CD.md](../wiki/CI-CD.md)。

## 1. 环境分离原则

| 维度 | 测试环境（现状） | 生产环境（目标） |
|------|-----------------|-----------------|
| 服务器 | 单台 SWAS（轻量应用服务器） | 独立生产服务器/集群（建议 ≥2 实例，可扩容） |
| 数据层 | 云 dev RDS/Redis | 生产 RDS（VPC 内网）+ 生产 Tair Redis（VPC 内网） |
| 镜像 | ACR `ai-customer-service/*`（dev 命名空间） | ACR 生产命名空间 `ai-customer-service-prod/*`，只接收 release tag 镜像 |
| 域名 | api.migaozn.com 等 | 生产域名（与测试域名区分，或同域名切换——建议独立） |
| 部署方式 | push main 自动部署（CI → SWAS pull） | **受控发布**：release tag + 人工审批 |
| 密钥 | GitHub Secrets + 服务器 .env.* | GitHub Environments secrets（production）+ KMS/SOPS 管理 |

## 2. 发布流程（生产）

```
测试环境验证（自动部署 SWAS + 冒烟）
    ↓ 通过
release.yml 手动运行（版本增量 patch/minor/major）
    ↓ 打 vX.Y.Z tag + GitHub Release notes
deploy-*.yml 的 tag 触发 → 构建 vX.Y.Z 镜像推 ACR（测试命名空间）+ 自动部署测试环境（回归）
    ↓ 测试环境回归通过
deploy-prod.yml 手动运行（生产发布入口）
    ├─ 输入 version（vX.Y.Z）与 services
    ├─ GitHub Environment `production` 人工审批（required reviewers）
    ├─ 部署到生产实例（pull vX.Y.Z 镜像 + up + 健康检查）
    └─ 生产冒烟（PROD_HEALTH_URLS）
    ↓ 故障
rollback.md 回滚（重新发布上一稳定版本）
```

## 3. 启用步骤（生产环境就绪后）

### 3.1 基础设施
1. 创建生产服务器/集群（≥2 实例，同 region；nginx 负载均衡或 SLB 前置）
2. 生产 RDS/Redis 走 VPC 内网（不暴露公网；测试环境当前用公网白名单，生产必须收敛）
3. ACR 建生产命名空间 `ai-customer-service-prod`；生产镜像只由 **tag 触发**构建推送（禁止 latest 直推生产命名空间）
4. OSS/DashVector/DashScope 使用生产账号资源

### 3.2 GitHub 配置
1. 创建 Environment `production`：
   - **required reviewers**：至少 1 名非触发人（防止单点合并）
   - 部署保护：等待时间（如 10 分钟冷却）/ 仅允许 main 分支部署
2. 仓库 Secrets 增加 `PROD_ALIYUN_ACCESS_KEY_ID/SECRET`、`PROD_ACR_USERNAME/PASSWORD`（生产最小权限 RAM 子账号，仅 SWAS/ACR 相关权限）
3. Variables：`PROD_SWAS_INSTANCE_IDS`、`PROD_SWAS_REGION`、`PROD_HEALTH_URLS`（生产健康检查地址）
4. 生产服务器部署脚本沿用 `deploy/swas/deploy.sh`（flock 串行 + 健康检查），由 `deploy-prod.yml` 触发

### 3.3 首次发布
1. 测试环境全量验证通过
2. `release.yml` 打 v0.1.0 → 测试环境自动部署回归
3. 运行 `deploy-prod.yml`（version=v0.1.0）→ 人工审批 → 生产部署 → 冒烟
4. 记录生产基线版本（回滚目标）

## 4. 回滚

见 [rollback.md](rollback.md)：生产回滚 = `deploy-prod.yml` 重新运行并指定上一稳定版本（镜像 tag 不可变）。

## 5. 生产安全基线（必须项）

- 生产凭据用 GitHub Environments secrets + 服务器侧 KMS/SOPS，**禁止**明文 .env 落盘
- 生产服务器端口收敛（仅 80/443 公网；应用端口 loopback——已由 compose 绑定）
- 生产 RDS/Redis 仅 VPC 内网白名单
- 生产镜像扫描（trivy）接入 tag 构建链（block critical）
- 生产可观测性：SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）触达值班
- 生产发布记录（发布日志/版本表）+ 季度恢复演练

### 5.1 安全响应头（issue #8218 P1-08 / P1-09 —— 已落地的形态，改它之前先读这一节）

| 面 | 谁发 | 带什么 | 备注 |
|---|---|---|---|
| `api.migaozn.com` | **Spring Security**（`backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java`） | HSTS `max-age=31536000; includeSubDomains` + `nosniff` + `X-Frame-Options: DENY` | 依赖 `backend/admin-api/src/main/resources/application.yml` 的 `server.forward-headers-strategy: native`（Tomcat RemoteIpValve；否则 nginx 终止 TLS 后应用认为请求是 http ⇒ HSTS **一个字都不发**，审计前的实际形态）。**不能选 `framework`**：它会剥离 `X-Forwarded-*` 请求头，而 `SameOriginOriginHeaderFilter` 直接读这些头 ⇒ 同源判定会翻成跨域（app 域写请求被 CORS 拦） |
| `ai-api.migaozn.com` | **nginx**（`deploy/swas/nginx.conf` 的 ai-api server 段） | HSTS + `nosniff` | FastAPI 一个安全头都不发 |
| `merchant.migaozn.com` / `migaozn.com` / `www` | **nginx**（admin-web server 段的 `location /`） | HSTS + `nosniff` | 含官网 `/download`；**有意不加 CSP**（Next.js App Router 内联 RSC 脚本，非 nonce 的最 CSP 会白屏） |
| `app.migaozn.com` 的 `/`、`/w/`、`/b/`、`/b/report/`、`/terminal/` | **nginx**（各静态 location） | HSTS + `nosniff`；`/w/` 与 `/b/` 另有 **CSP** | 见下方「CSP 的刻意放宽」 |

**红线**：`api.migaozn.com` 的 HSTS **只能由 Spring 发** —— nginx 再补一条 ⇒ 响应里出现两个 STS 头，
按 RFC 6797 浏览器会**整条忽略**（等于把 HSTS 关掉）。判据 = `tests/unit_ci_workflows/test_prod_security_headers.py`
（含「nginx 的 api server 段不得出现 `add_header … Strict-Transport-Security`」这条反向断言）。

**CSP 的刻意放宽（照实登记，不是遗漏）**：`/b/`（bmini h5）的 `script-src` 含 `'unsafe-inline'`
—— 它的 `frontend/bmini-app/src/index.html` 自带两段内联脚本（`window.TARO_ENV` 占位 + 响应式根字号，
后者是 issue #5721 的修法，删掉字号只剩设计值 40%）。**重启条件**：把这两段搬成外部脚本
（或加 build-time hash / nonce）后收紧到 `'self'`。`/`（C 端元元）与 admin-web **暂不加 CSP**，
同一原因（Taro / Next 的内联脚本），**重启条件**同上。

**线上判据**（只读，0/1/3 三态，**3 不得当 0 读**）= `deploy/scripts/prod-security-headers.sh`，
挂在 `deploy-admin-api.yml` 的部署后探针位（该腿的 `on.push.paths` 同时覆盖 `backend/admin-api/**`
与 `deploy/swas/**` ⇒ 改了任一面都会被它探到；⛔ 不新增 schedule）。

### 5.2 短链 token：**有意取舍** + 日志侧脱敏（issue #8218 P1-10）

**接受的取舍（有意，不是待修）**：报工 / 入库 / 加工单三种短码把 token 放在 URL query
（`/b/?t=<token>`、`/w/?t=<token>`，由 `WorkerShortLinkController` / `InboundLabelShortLinkController` /
`ProcessingOrderShortLinkController` 302 出来）。它同时出现在：浏览器历史、Referer、以及**任一**
访问日志。代价面：纸上的二维码被拍照即可复用，且**改撤前一直有效**（token 不是一次性票据）。
之所以接受：换一次性票据是**后端契约变更**（工人端 / 打印侧 / 扫码 SDK 全部要动），不在加固包内。
**重启条件**：与 `POST /api/auth/qr/exchange` 同族的一次性票据方案落地时，改为一次性票据并删掉本节的取舍。

**日志侧脱敏（已落地）**：`deploy/swas/nginx.conf` 用 `log_format migao_no_token` ——
请求行记 `$request_method $uri $server_protocol`（**不含** query），且**不带** `$http_referer`
⇒ token 在 access log 里**物理上不可能出现**（既不来自请求行、也不来自 Referer）。
**每个 `listen 443` 的 server 块都必须用这个格式**（判据 = `tests/unit_ci_workflows/test_nginx_log_redaction.py`，
新增 TLS 面忘了切 ⇒ 红）。代价：`?page=cut_calc` 这类非敏感 query 与 Referer 也不再进日志（诊断改走
浏览器侧 / 应用侧日志）。
**服务器侧复核（可复制）**：`docker compose exec -T nginx grep -c 't=' /var/log/nginx/access.log` ⇒ 期望 `0`
（改前该命令会数出成片的 token）。

## 6. 与测试环境的差异提醒

- **自动部署只在测试环境**：push main → 测试环境自动部署（快速迭代）；生产必须走受控发布
- 镜像 tag 全部不可变（git SHA / semver）；`latest` 仅测试环境使用
- 生产环境由 `deploy-prod.yml` + Environment 审批保证"人"的确认环节
