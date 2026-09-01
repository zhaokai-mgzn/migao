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

## 6. 与测试环境的差异提醒

- **自动部署只在测试环境**：push main → 测试环境自动部署（快速迭代）；生产必须走受控发布
- 镜像 tag 全部不可变（git SHA / semver）；`latest` 仅测试环境使用
- 生产环境由 `deploy-prod.yml` + Environment 审批保证"人"的确认环节
