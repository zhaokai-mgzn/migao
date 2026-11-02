# 回滚 Runbook

> 适用：测试环境（SWAS，自动部署）与未来生产环境（deploy-prod）。
> 原则：**镜像 tag 不可变**（git SHA / semver），ACR 中始终存在历史版本 → 回滚 = 重新部署指定旧版本。

## 1. 判定需要回滚的信号

> 🔴 **判据地址必须自己先 200**（issue #8197 P1-05，2026-10-31 上线审计）。
> 本节的每条判据都必须是**线上真的 200** 的面 —— 否则 runbook 会给出「永远命中」的错误信号。
> 曾经的错误形态（改前逐字）：第一条判据是 `curl api.migaozn.com/actuator/health`，而
> `deploy/swas/nginx.conf` 把 `/actuator` **整段 404**（`location ~ ^/(actuator|v3/api-docs|swagger-ui)`）
> ⇒ 线上实测 **404** ⇒ 按 runbook 执行**必然**得出「非 200 ⇒ 需要回滚」。
>
> **自检（一条命令；三条面必须都是 200）**：
> ```bash
> for u in https://api.migaozn.com/api/version https://ai-api.migaozn.com/health https://merchant.migaozn.com/login; do
>   printf '%s -> ' "$u"; curl -s -o /dev/null -w '%{http_code}\n' -m 10 "$u"
> done
> ```
> **判据（会红）**：`tests/unit_ci_workflows/test_rollback_runbook_criteria.py` —— 本文件里任何
> `https://…` 形态的判据地址，只要落在 nginx 的 404 屏蔽面里、或不在「线上 200 面」白名单里 ⇒ 判红。
> 新增一条判据地址时，**先跑上面那段自检**，再把地址加进该测试的白名单（并写明它的归属面）。

- 部署后冒烟失败（post-deploy smoke / frontend probe）
- 健康检查异常 —— **用线上真的 200 的面**（公网）：
  - `GET https://api.migaozn.com/api/version` **非 200**（admin-api 的版本面，nginx 放行 `/api/` 前缀）
  - `GET https://ai-api.migaozn.com/health` **非 200**（ai-agent 健康面，nginx 只屏蔽 `/docs` `/redoc` `/openapi.json`）
  - ⚠️ **不要**用 `/actuator/health` 判公网（它被 nginx 整段 404；容器内部面见 §3 的 `127.0.0.1` 那三条）
- 用户投诉 / 关键指标异常（订单、登录、AI 对话）

## 2. 快速回滚（推荐：GitHub 手动部署旧版本）

### 测试环境（SWAS）
1. 打开对应 workflow 手动运行：
   - `deploy-admin-api` / `deploy-ai-agent-service` / `deploy-frontend`
2. `workflow_dispatch` → **image_tag 填上一稳定版本**：
   - 上一版本 = 上次成功部署的镜像 tag（`sha-xxxxxxx`，从 Actions 运行记录或 ACR 仓库查）
   - 或填 release tag（`vX.Y.Z`，若该版本有镜像）
3. 运行 → 跳过构建 → 服务器 pull 旧镜像 + up → 健康检查 + 冒烟

> 找上一版本 tag：ACR 控制台 `ai-customer-service/<service>` 镜像列表，按时间排序；或 GitHub Actions 上次成功的 deploy run 中 "Resolve image tag" 步骤输出。

### 生产环境（未来，deploy-prod）
1. 运行 `deploy-prod.yml` → version 填上一稳定版本 → 人工审批 → 部署 → 冒烟
2. 若 deploy-prod 不可用（网络/凭据问题），走 3 手动回滚

## 3. 手动回滚（服务器 SSH，兜底）

```bash
# SSH 到 SWAS 实例
cd /opt/migao-deploy

# 查看当前运行的镜像 tag
docker compose ps
docker inspect $(docker compose ps -q admin-api) --format '{{.Config.Image}}'

# 拉取并切换到上一版本（把 sha-xxxxxxx 换成目标版本）
export IMAGE_TAG=sha-xxxxxxx
docker compose pull admin-api ai-agent admin-web   # 逐服务也可
docker compose up -d --no-deps admin-api
# （ai-agent / admin-web 同理）

# 重启 nginx 刷新上游 IP
docker compose restart nginx

# 健康检查（与 deploy.sh 相同）
# ⚠️ 这三条是**容器内部面**（127.0.0.1 + 服务端口）—— 它们 200 是合法的（`/actuator/health` 在
#    nginx 后面被 404 屏蔽，但**容器内部**仍然直接由 Spring 提供服务）⇒ 本节与 §1 的**公网面**
#    是两套坐标：公网判据不要抄这三条（见 §1 的自检）。
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/actuator/health
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3001/
```

## 4. 数据回滚（不适用代码回滚时）

- **误删/坏数据**：RDS 自动备份恢复（阿里云控制台 → 实例 → 备份恢复 → 恢复到新实例/时间点）。**恢复前确认备份策略 ≥14 天**（读数来源与值班复查步骤见 §4.1）。
- **配置漂移**：对比服务器 `.env.*` 与仓库 `.env.example` 模板；用模板 + 密文引用重建。
- **DB 迁移异常**：MigrationRunner 幂等（IF NOT EXISTS）；如半执行，修复迁移文件后重启（schema_migrations 记录为准）。

### 4.1 备份窗口读数（≥14 天）与值班复查（issue #8197 P1-07）

**为什么是读数而不是流程**：审计读数 —— `grep -rn "pg_dump\|backup" deploy/ .github/workflows/` ⇒ 只有 H5
静态根备份、**无数据库备份代码** ⇒ 误删 / 坏数据**不可自助恢复**；而「备份策略是否 ≥14 天」
**没有任何读数**（不可判定 ⇒ 不能算通过）。本节的落码只做**只读读数**：
⛔ 不新增 schedule / cron（铁律 10），⛔ 不碰云侧配置（改保留时长是人的动作）。

**读数来源（两条面，任选；控制台是兜底，CLI 可留痕）**

| 面 | 怎么取 | 性质 |
|---|---|---|
| 控制台 | 阿里云控制台 → **云数据库 RDS** → 实例（`rm-…`）→ **备份恢复 → 备份策略** → 「保留时长」 | 人工，无需配凭据 |
| CLI | `aliyun rds DescribeBackupPolicy --DBInstanceId <instance-id>` | **Describe 类只读 API**，不改任何配置 |

**仓内读数器**（把上面两条面统一成一条判据；只读、三态）：

```bash
# 必需环境变量：MIGAO_RDS_INSTANCE_ID（缺失 ⇒ rc=3「无法判定」，不得当通过）
MIGAO_RDS_INSTANCE_ID=rm-xxxx python3 scripts/rds_backup_window_readout.py

# 离线复核（把上一次 API 响应存成文件，随时可复算）
aliyun rds DescribeBackupPolicy --DBInstanceId rm-xxxx > /tmp/rds-backup-policy.json
python3 scripts/rds_backup_window_readout.py --from-json /tmp/rds-backup-policy.json
```

**判据口径**：`retention_days ≥ 14` ⇒ rc=0；`< 14` ⇒ rc=1（当班开单，把保留时长调到 ≥14 天）；
取不到（缺 `MIGAO_RDS_INSTANCE_ID` / 无 `aliyun` CLI / 凭据或网络失败 / 字段缺失）⇒ **rc=3「无法判定」**，
`3` 一律**不得**当 `0` 读。

**值班复查步骤**（每周一次；每次误删 / 坏数据事件之前必查）

1. 跑上面那条读数器命令（或按控制台路径取数）；
2. `rc=0` ⇒ 把 `retention_days` 与 rc **一起**写进当班记录（只有 rc 没有读数 = 无法复核）；
3. `rc=1` ⇒ 当班开单，并把保留时长调到 ≥14 天（**云侧动作**，本仓无凭据）；
4. `rc=3` ⇒ 按「无法判定」处理：先修取数面（实例 id / CLI / 凭据），**不许**读成通过。

**恢复演练记录：待补（用户云侧）** —— 「备份真的能恢复」这件事本仓**没有读数**（无库凭据、无演练环境）。
处置：由有云侧权限的人做一次「恢复到新实例 + 抽样核对」，把时间 / 实例 id / 核对项回填到本节；
在此之前，本节结论只到「备份窗口读数」这一层，**不得**被读成「恢复已就绪」。

判据 = `tests/unit_ci_workflows/test_ops_readouts.py`（替身 `aliyun` + 离线快照，零网络、零真库）。

## 5. 回滚后

1. 确认健康检查 + 冒烟 + 核心链路（登录/订单/AI 对话）
2. 定位根因（诊断 → 修复 → 测试 → 走正常发布）
3. 更新本 runbook（如有新坑）
