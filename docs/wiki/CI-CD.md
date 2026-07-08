# CI/CD 流水线

## 10 个 GitHub Actions 工作流

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `deploy-admin-api` | push main `backend/admin-api/**` | 单测 → Maven 打 FatJar → 上传 OSS → SAE 部署 → 冒烟验证 |
| `deploy-ai-agent-service` | push main `backend/ai-agent-service/**` | Fast Gate 关键测试 → Docker build → ACR push → SAE 部署 |
| `deploy-frontend` | push main `frontend/admin-web/**` | tsc + vitest → Docker build → GHCR+ACR push → SAE 部署 |
| `pr-check` | PR → main | 三并行 job: 拦截 .env 文件 / admin-api 单测 / admin-web tsc+vitest |
| `smoke-test` | workflow_call (可复用) | P0 冒烟 (pytest+httpx)，被 deploy 工作流调用 |
| `e2e-real` | workflow_dispatch | AI Agent 真实 LLM 调用测试，失败自动建 Issue |
| `mini-app` | PR/push `frontend/mini-app/**` | tsc + 单测 |
| `junshi-case-draft` | issue opened/edited | 军师自动生成验收用例草稿 |
| `junshi-redraft` | issue_comment (reject) | 驳回后重新生成验收用例 |
| `junshi-verify-trigger` | PR closed (merged) | 触发双验收 → 通过自动 close issue |

## 部署目标

| 服务 | 目标 | 技术 |
|------|------|------|
| admin-api | SAE (Serverless App Engine) | FatJar, Java 21, 1C2G |
| ai-agent-service | SAE | Docker 容器, Python 3.11, 1C2G |
| admin-web | SAE (SSR) | Docker 容器, Node 20 |

## Fast Gate (关键测试门禁)

`deploy-ai-agent-service` 在构建前运行关键单测 + 集成测试：
- 意图分类正确性
- Tool 注册完整性
- pending_skill 死锁防护
- preference_tracker 类型安全

## 军师验收流水线

```
Issue 创建 → 军师自动生成验收草稿 (L2/L3/L4)
     → 研发 review → PR 合并
     → 自动触发双验收:
       主验收: spec + L2/L3 业务断言
       复核验收: DB/API 独立断言 (不看 spec, 避免合谋)
     → 双一致 + 100% → 自动 close issue
     → 不通过 → 留研发/凯总处理
```

## 关键环境变量 (GitHub Secrets)

| 变量 | 用途 |
|------|------|
| `ALIYUN_ACCESS_KEY_ID/SECRET` | 阿里云 CLI (OSS + SAE) |
| `ACR_USERNAME/PASSWORD` | 容器镜像推送 |
| `DASHSCOPE_API_KEY` | LLM API |
| `SMOKE_ADMIN_PASSWORD` | 冒烟测试登录 |
| `SMOKE_SERVICE_TOKEN` | 服务间调用 |

---
详见: [部署指南](../deployment/deployment-aliyun.md) · [部署检查清单](../deployment/deployment-checklist.md)
