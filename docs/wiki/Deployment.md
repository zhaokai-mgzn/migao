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
- `migaozn.com` / `www.migaozn.com` / `merchant.migaozn.com` → admin-web:3001

> 注：nginx `server_name` 里还列了 `admin.migaozn.com` 与 `ops.migaozn.com`（后者已废弃：商家入驻 2026-08-30 起由 AI 自动甄别，无人工审批页面），两域名均无实际前端入口。

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

## 上线清单项：对外入口收口 + 限流防刷（关联 #20）

三项拆开看，**不要混着读**：① 单入口在仓内可自证；③ 限流已实装（2026-09-26）；② 安全组在**云侧**，
本仓产不出证据 ⇒ 下面显式标注为「待人工取证」，**不写成已完成**。

### ① 单入口复核

仓内证据（可复算，读 `origin/main` 的**内容**而不是工作树）：

```bash
git show origin/main:deploy/swas/docker-compose.yml | grep -n '127\.0\.0\.1:'
# 期望：8080 / 8000 / 3001 三条都绑回环（只有 nginx 例外）
git show origin/main:deploy/swas/docker-compose.yml | grep -n -A3 '^  nginx:'
# 期望：nginx 的 ports 只有 "80:80" 与 "443:443"
git show origin/main:deploy/swas/nginx.conf | grep -n 'listen '
# 期望：只有 80 / 443（其余容器端口不对外）
```

部署机读数（**待人工取证** —— 仓内产不出）：

```bash
ss -lntp | grep -v '127\.0\.0\.1'
# 期望：非回环监听只有 nginx 的 :80 / :443（+ 运维用的 sshd），**没有** 8080 / 8000 / 3001
```

- **owner**：运维 / 凯总（需要部署机登录）。
- **重启条件**：`docker-compose.yml` 的 `ports` 有任何改动、或新增对外端口时，本项重新取证。

### ② 安全组收口（**外部，未取证**）

安全组在阿里云侧，仓内无法自证。控制台：轻量应用服务器 → 该实例 → **防火墙**；
或 CLI：

```bash
aliyun swas-open ListFirewallRules --RegionId <region> --InstanceId <SWAS 实例 ID>
# 期望：入方向只放行 80 / 443（+ 运维白名单端口，逐条有 owner 与理由），其余一律拒绝
```

- **owner**：运维 / 凯总。
- **重启条件**：任何一条安全组规则变更后重新取证（导出的规则截图上必须带日期）；
  新开端口必须写明 owner 与理由。

### ③ 限流防刷（已实装，`deploy/swas/nginx.conf`）

五档 zone（阈值按**实测**给余量，推导与判据见 `tests/unit_ci_workflows/test_swas_nginx_rate_limit.py`
—— 它会**重算**「一次最重页面加载 = 9 个动态请求」并在页面长大后判红）：

| zone | key | rate | burst | 面 |
|---|---|---|---|---|
| `api_perip` | per-IP（map） | 10 r/s | 200 | 通用动态面（`/api/**`、ai-agent） |
| `auth_perip` | per-IP（仅**密码/PIN 类**登录计入） | 1 r/s | 60 | B 端/工人端登录、交接班 |
| `abuse_perip` | per-IP（仅 `sms/send`+`register`） | 6 r/m | 10 | 花钱/可被刷 |
| `worker_sess` | **工人会话**（`X-Worker-Session-Id`） | 2 r/s | 60 | 工人报工（一机一会话，与 NAT 无关） |
| `worker_entry` | per-IP（`/s/` + `/api/worker/`） | 50 r/s | 1000 | 工人入口兜底 |

- **静态面一律不限流**：`/w/`（工人端）、C 端 H5、admin-web 的 JS/CSS 走各自 `location /`，那里**没有**限流
  —— 一次页面加载要取几十个静态文件，限流必然误伤。
- **超限响应 = 429**（`limit_req_status 429`，默认 503 会把人引向错误排查方向），日志 WARN
  `limiting requests ... by zone "..."`（`limit_req_log_level warn`）。
- **生效条件：下一次部署**（`deploy/swas/nginx.conf` 由 `deploy.sh` 从 repo 同步到服务器后再 reload）。
- 🔴 **部署前必须先验语法**（本机与 CI 都没有 nginx 二进制 / docker ⇒ `nginx -t` 只能在部署机上跑）：

  ```bash
  cd /opt/migao-deploy
  docker compose exec -T nginx nginx -t          # 必须先绿，再 reload
  docker compose exec -T nginx nginx -s reload
  ```

  ⚠️ 顺序不能反：`deploy.sh` 在 `nginx -s reload` 失败时会回落 `docker compose restart nginx` ——
  配置写坏时那一步会让 **nginx 起不来 ⇒ 全站不可用**。另外本文件是**单文件 bind mount**，
  改它必须**原地改写**（`mv`/`cp` 会换 inode 导致容器里仍是旧文件，且不报错，见 `docs/wiki/CI-CD.md`）。
- **已知残余（照实登记）**：per-IP 分档对 **CGNAT/运营商大出口** 的 C 端流量偏严
  （`app.migaozn.com/api/` = 10 r/s per IP）。**重启条件**：线上出现合法用户 429（日志按来源 IP 聚类、
  且不是攻击特征）⇒ 抬 burst 或把该档 key 换成会话/租户维度。
