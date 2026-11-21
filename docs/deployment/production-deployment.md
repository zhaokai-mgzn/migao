# 生产环境部署方案（未来）

> 状态：**设计文档**。当前生产部署目标为测试环境（单台 SWAS，一张 6-SAN 证书覆盖 migaozn.com / www / api / ai-api / app / merchant；`admin.migaozn.com` 无 A 记录、`ops.migaozn.com` 已废弃，两者均于 2026-10-31 从证书移除，ops 的 DNS 记录同批删除），
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
   - **`deploy.sh` 现在自同步**（issue #8966）：第 1 段取到同源源码树（`src/`）后，会把它自己的
     `src/deploy/swas/deploy.sh` 与盘上 `/opt/migao-deploy/deploy.sh` 比对，不同则备份
     `deploy.sh.bak-<时间戳>` 后**原地覆盖**（`cat >` 保 inode）并打印两侧 sha256 前 8 位
     ⇒ **盘上版本随 target ref 走**，不再需要人工覆盖（2026-11-21 的「旧脚本 + 新配置」事故：
     旧脚本不读 `.env.site` ⇒ 域名静默回落 `migaozn.com` ⇒ 全站 401）。
     覆盖后**本次运行会立刻停下**（bash 按字节偏移续读脚本，换内容后继续执行会读到错位内容）⇒
     再跑一次即由新脚本执行（CI 会自动重试一次）。同日还加了两道 fail-closed 断言：nginx 渲染后
     `server_name` 必须含站点域名、构建后产物不得含 `migaozn.com`（取不到产物 = 不可判定，不判绿）。
     自查：`sha256sum /opt/migao-deploy/deploy.sh` 与 `git show <ref>:deploy/swas/deploy.sh | sha256sum` 对齐

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
  —— **已落地的形态**（5xx 计数 / 证书到期 / 发布失败三类事件各自的判据 + 值班通道 + 去重 + 演练读数，
  以及**仍未覆盖项**）见 [observability-minimum.md](observability-minimum.md)（issue #8203，上线审计 P0-04）
- 生产发布记录（发布日志/版本表）+ 季度恢复演练

### 5.1 安全响应头（issue #8197 P1-08 / P1-09 —— 已落地的形态，改它之前先读这一节）

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
（或加 build-time hash / nonce）后收紧到 `'self'`。`/`（C 端米宝）与 admin-web **暂不加 CSP**，
同一原因（Taro / Next 的内联脚本），**重启条件**同上。

**线上判据**（只读，0/1/3 三态，**3 不得当 0 读**）= `deploy/scripts/prod-security-headers.sh`，
挂在 `deploy-admin-api.yml` 的部署后探针位（该腿的 `on.push.paths` 同时覆盖 `backend/admin-api/**`
与 `deploy/swas/**` ⇒ 改了任一面都会被它探到；⛔ 不新增 schedule）。

### 5.2 短链 token：**有意取舍** + 日志侧脱敏（issue #8197 P1-10）

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

### 5.3 只增表体量 / 最老行年龄读数（issue #8197 P1-11 —— 只读，不新增无人值守删除）

**病**：`deploy/ops/db-retention.sql` 文件头逐字「**人工执行**，不是定时任务」
（`audit_logs` 365 天 / `notifications` 180 天），而仓内**无任何值守面**（无告警、无读数、无到期提醒）
⇒ 两张只增表**无界增长**（索引体积 / 备份窗口 / 查询变慢），且「**没有清理**这件事不会有人知道」。

**修法（只读读数）**：⛔ 不新增 schedule / cron（**铁律 10**：无人值守删除不安全）；删除仍是**人工执行**
`deploy/ops/db-retention.sql`（先 count 看量，再低峰 purge）。本节只补两件读数：**表多大**、**多久没清了**。

| 面 | 命令 | 性质 |
|---|---|---|
| 读数器（默认） | `python3 scripts/db_growth_readout.py` | 只读三态 `0/1/3` |
| 只读 SQL | `psql "$DATABASE_URL" -f deploy/ops/db-growth-readout.sql` | 值班可直接看表 |
| 离线复核 | `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --csv -f deploy/ops/db-growth-readout.sql > /tmp/db-growth.csv`，再 `python3 scripts/db_growth_readout.py --from-csv /tmp/db-growth.csv` | 零网络 |

**读数列**：`table_name` / `total_bytes`（`pg_total_relation_size`）/ `row_count` /
`oldest_created_at` / `oldest_age_days`。

**期望阈值与告警口径**（默认值与脚本同源）：

| 读数 | 期望 | 超限含义 | 值班动作 |
|---|---|---|---|
| `audit_logs` 的 `oldest_age_days` | ≤ **365** | 保留期口径**没人执行** | rc=1 ⇒ 当班开单：按 `deploy/ops/db-retention.sql` **人工执行**（先 count 看量，再低峰 purge） |
| `notifications` 的 `oldest_age_days` | ≤ **180** | 同上 | 同上 |
| 任一张表 `total_bytes` | ≤ **512 MiB** | 索引体积 / 备份窗口开始受拖累 | rc=1 ⇒ 先跑 count 读数确认增量是「活动量上涨」还是「没有清理」，再排 purge 期 |
| 取不到（缺 `DATABASE_URL` / 无 `psql` / 连接或 SQL 失败 / 少一张表的读数行 / 解析不了） | —— | **无法判定** | rc=3 ⇒ 修取数面，**不得**当通过（`DQ-U` 同族：读不到 ≠ 通过） |

**值班节奏**：每周一次（发布前必跑一次）；`rc=1` ⇒ 当班开单，`rc=3` ⇒ 先修取数面。
**不新增 schedule**：这是「人跑一条命令」，不是周期任务。

判据 = `tests/unit_ci_workflows/test_ops_readouts.py`（替身 `psql` + 离线 CSV，零网络、零真库；
另核 `deploy/ops/db-growth-readout.sql` 的只读性：可执行面出现任何写 / DDL 动词 ⇒ 红）。

### 5.4 宿主挂载契约：compose 的卷必须覆盖 env 里所有 `file:` 路径（issue #8969）

**病（2026-11-21 生产实测）**：`.env.admin-api` 用**文件式** JWT 私钥
（`JWT_PRIVATE_KEY=file:/opt/migao-deploy/jwt/private.pem`），而 canonical `deploy/swas/docker-compose.yml`
的 admin-api **没有 `volumes:`** ⇒ 容器里那个路径不存在 ⇒ `JwtTokenProvider` 的 RS256 fail-closed
直接打死进程（`api.cytda.com` 502 约 3 分钟，报「JWT RSA 密钥加载失败，无法启用 RS256 签名」）。
生产旧容器**看起来**有挂载，只因那份挂载来自**历史手工创建**（`docker inspect` 可见
`/opt/migao-deploy/jwt`、`/opt/migao-deploy/uploads`），仓库里从来没有 ⇒「按仓库 compose 重建容器」必然炸。

**口径（一条）**：**每个服务的 `volumes` 必须覆盖它 `env_file` 指向的 `.env*` 里所有 `file:<容器内路径>`，
以及运行期写盘的目录**。新增一条 `file:` 路径而不补卷 ⇒ 守卫判红（见下）。

| 服务 | 必须挂的卷 | 为什么 |
|---|---|---|
| `admin-api` | `/opt/migao-deploy/jwt:/opt/migao-deploy/jwt:ro` | `.env.admin-api` 的 `JWT_PRIVATE_KEY=file:…/private.pem`（RS256 fail-closed：缺了容器起来即崩） |
| `admin-api` | `/opt/migao-deploy/uploads:/app/uploads` | `LocalFileStorageService.UPLOAD_DIR="uploads"` + Dockerfile `WORKDIR /app` ⇒ 上传图片的落盘面（不挂卷 = 容器一重建就丢） |
| `ai-agent` | `/opt/migao-deploy/jwt:/opt/migao-deploy/jwt:ro` | `JWT_PUBLIC_KEY=file:/opt/migao-deploy/jwt/public.pem`（issue #8976：验签公钥与 admin-api 签名密钥**同一份文件** ⇒ 单一来源；缺卷 = 起不来，见 §5.5） |
| `nginx` | `./nginx/nginx.conf` · `/etc/letsencrypt` · `./certbot-www` · `./h5` | 配置 / 证书 / ACME / C 端静态文件（既有，未变） |

**ai-agent 的卷是 2026-11-21 补的（issue #8976）**：改前它不需要卷（图片与文件走 OSS 双 bucket、
`.env.ai-agent` 里没有 `file:` 路径）；现在它的 `JWT_PUBLIC_KEY` 是 **`file:` 取值**（与 admin-api 的
签名密钥同一份文件，见 §5.5）⇒ 必须挂 `/opt/migao-deploy/jwt:ro`。**admin-web 仍不需要卷**
（Next standalone，无运行期落盘目录）。
`.env*` 或 compose `environment:` 里将来若出现**新的** `file:` 路径，判据 12 / 12b 会当场判红
（不需要改守卫）。

**守卫（会红）**：

- `tests/unit_ci_workflows/test_swas_deploy_blue_green.py` —— `docker-compose.bluegreen.yml` 的每个
  green 与正式服务的 `volumes` **逐字一致**（删一个卷 / 改 `:ro` 标志 ⇒ 红；含注入式红证）；
- `tests/unit_ci_workflows/test_swas_container_runtime.py::test_admin_api_host_mounts_are_present`
  —— 上表 admin-api 的两条卷逐字在位；
- 同文件 `::test_env_file_referenced_paths_are_mounted` —— **类级**：扫 `.env.admin-api` /
  `.env.ai-agent` / `.env.admin-web` 里所有 `file:` 前缀路径，断言对应服务的卷**容器目标**覆盖它。
- 同文件 `::test_injection_compose_env_file_path_not_covered_is_caught` —— **类级（12b）**：compose
  `environment:` 的值里出现 `file:<路径>` 时同样必须被卷覆盖（issue #8976 的落法就是把路径写在
  `environment:` 里 ⇒ 只扫 `.env*` 的判据**看不到**它）。

### 5.5 JWT 验签**同源**：ai-agent 只认路径，部署期硬断言（issue #8976）

**病（2026-11-21 生产实测）**：admin-api 用 `.env.admin-api` 的 `JWT_PRIVATE_KEY/JWT_PUBLIC_KEY`
（`file:/opt/migao-deploy/jwt/*.pem`，公钥指纹 `c58e54d6…`）签发，而 ai-agent 用
`deploy/swas/docker-compose.yml` 里**硬编码的 PEM**（指纹 `ba01a29f…`）验签 ⇒ 同一个 token 配了两把钥匙
⇒ 生产 AI 接口**全部 401**（`TOKEN_INVALID: Signature verification failed`）。两侧都不报错，
**这类不一致永远不会自己好**。

**口径（三条）**：

1. **单一来源**：ai-agent 的 `JWT_PUBLIC_KEY` **只给路径**
   （`file:/opt/migao-deploy/jwt/public.pem`），不给内容；内容 = admin-api 私钥那一对的 public 半份
   ⇒ 换钥匙只换那一份文件，两侧同时跟上。缺文件 ⇒ ai-agent **起不来**（fail-closed：宁可这次部署失败，
   也不许拿错钥匙继续全 401）。
2. **兼容**：`backend/ai-agent-service/app/config.py` 仍接受**直接给 PEM 内容**（本地 `.env` / CI 的形态）
   —— 既有部署一行不改也能起。
3. **部署期硬断言**：`deploy/swas/deploy.sh` 在切完流量之后（`== 2.5.9`）比对两侧容器内**实际生效**的
   公钥指纹，三态写进部署日志：

   | 读数 | 含义 | 部署结果 |
   |---|---|---|
   | `JWT_KEY_SAME_SOURCE=OK` | 两侧同一把公钥（打印指纹 + 来源） | 继续 |
   | `JWT_KEY_SAME_SOURCE=MISMATCH` | 不同源（打印两侧指纹 + 来源 + 排查口） | **`exit 1`** |
   | `JWT_KEY_SAME_SOURCE=SKIPPED` | 取不到（env 未设置 / `file:` 读不到 / 不是公钥 PEM） | 继续，但**不判绿** |

   ⚠️ `SKIPPED` **不是通过**：它只说明这次读不到（例如容器里走 classpath 默认、本脚本读不到 jar 内资源）。
   让它可判定的办法 = 两侧都显式配 `JWT_*`（就是上面第 1 条）。
   指纹口径 = `sha256(公钥体)` 前 16 位，与 `scripts/align_agent_jwt_key.py` **同口径**
   （对拍判据 = `tests/unit_ci_workflows/test_swas_jwt_same_source.py`）。

**判据（会红）**：`tests/unit_ci_workflows/test_swas_jwt_same_source.py` —— compose 侧「只给路径 + 卷在位 +
无内联 PEM」、`deploy.sh` 侧「三态齐备 + 不一致 `exit 1` + SKIPPED 不判绿 + 指纹口径与工具同源」，
外加桩化 docker/curl 跑**真实** `deploy.sh` 的执行式红证（一致 ⇒ 绿 / 不一致 ⇒ 红 / 取不到 ⇒ SKIPPED）。
  **取不到 env 文件 ⇒ SKIPPED 不可判定，不判绿**（env 不入仓 ⇒ CI 里通常是 SKIPPED；在服务器上只读复核：
  `MIGAO_SWAS_ENV_DIR=/opt/migao-deploy python3 -m pytest tests/unit_ci_workflows/test_swas_container_runtime.py -q -k env_file`）。

## 6. 与测试环境的差异提醒

- **自动部署只在测试环境**：push main → 测试环境自动部署（快速迭代）；生产必须走受控发布
- 镜像 tag 全部不可变（git SHA / semver）；`latest` 仅测试环境使用
- 生产环境由 `deploy-prod.yml` + Environment 审批保证"人"的确认环节
