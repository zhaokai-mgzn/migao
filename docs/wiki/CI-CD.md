# CI/CD 流水线

## 12 个 GitHub Actions 工作流

| 工作流 | 触发 | 说明 |
|--------|------|------|
| `deploy-admin-api` | push main `backend/admin-api/**` | 单测 → Maven 构建 → 云助手触发 SWAS `deploy.sh` → 冒烟验证 |
| `deploy-ai-agent-service` | push main `backend/ai-agent-service/**` | Fast Gate 关键测试 → 全量单测 → 云助手触发 SWAS `deploy.sh` → 冒烟验证 |
| `deploy-frontend` | push main `frontend/admin-web/**` | tsc + vitest → 云助手触发 SWAS `deploy.sh` |
| `pr-check` | PR → main | 多 job 门禁: 拦截 .env / admin-api 单测 / admin-web tsc+vitest / E2E 质量门禁 / QA Growth Gate(G1+G5) / Case Contract 校验 |
| `agent-eval` | schedule 每日 01:30 + 手动 | 米宝能力评测（smoke tier，真实 LLM + `cases/*.yml` 单一源） |
| `smoke-test` | workflow_call (可复用) | P0 冒烟 (pytest+httpx)，被 deploy 工作流调用 |
| `e2e-web` | PR (paths) | Playwright 全量 E2E（Record-Replay fixtures） |
| `e2e-real` | workflow_dispatch | AI Agent 真实 LLM 调用测试，失败自动建 Issue |
| `mini-app` | PR/push `frontend/mini-app/**` | tsc + 单测 |
| `issue-contract-check` | issue opened | 校验 CONTRACT_JSON → needs-verification / needs-truths + cases 引用校验 |
| `junshi-case-draft` | issue opened/edited/labeled | 军师自动生成验收用例草稿 + DRAFT cases 引用提醒 |
| `junshi-redraft` | issue_comment (reject) | 驳回后隐藏旧 DRAFT 重新生成 |
| `junshi-verify-trigger` | PR closed (merged) | 贴 VERIFY_TRIGGER → 双验收 → 通过自动 close issue |

## 部署目标（2026-08-14 起：SAE → SWAS）

| 服务 | 目标 | 技术 |
|------|------|------|
| admin-api | SWAS 单实例（docker compose 源码构建） | Java 21, 容器端口 8080 |
| ai-agent-service | SWAS 单实例（同上） | Python 3.11, 容器端口 8000 |
| admin-web | SWAS 单实例（同上） | Next.js, 容器端口 3001 |
| nginx | SWAS 同机 | 80/443 TLS 终结 + 域名分流 |

数据层不在 SWAS 上：PostgreSQL 用阿里云 RDS、Redis 用 Tair 公网代理（admin-api 已强制 Lettuce RESP2）、OSS/DashVector/DashScope 不变。

## 部署链路

```
push main（路径过滤）→ CI 测试/构建
  → aliyun swas-open RunCommand（实例 b23c69e5..., 超时 1800s）
  → 服务器执行 /opt/migao-deploy/deploy.sh：
     1. codeload 拉 main 源码
     2. RESP2 补丁兜底（RedisProtocolConfig）
     3. docker compose up -d --build
     4. 健康检查 8080/8000/3001（10 次重试）
  → CI 轮询 DescribeInvocationResult 至 Success
  → smoke-test.yml post-deploy 冒烟
```

## Fast Gate (关键测试门禁)

`deploy-ai-agent-service` 在构建前运行关键单测 + 集成测试：
- 意图分类正确性
- Tool 注册完整性
- pending_skill 死锁防护
- preference_tracker 类型安全

## 军师验收流水线

```
Issue 创建（CONTRACT_JSON 含 business_truths + cases 引用）→ 军师自动生成验收草稿 (L2/L3/L4)
     → 研发 review → PR 合并
     → 自动触发双验收:
       主验收: spec + L2/L3 业务断言 + 逐用例打分（case_results）
       复核验收: DB/API 独立断言 (不看 spec, 避免合谋)
     → 双一致 + 100% → 自动 close issue
     → 不通过 → 留研发/凯总处理
```

## 关键环境变量 (GitHub Secrets)

| 变量 | 用途 |
|------|------|
| `ALIYUN_ACCESS_KEY_ID/SECRET` | 阿里云 CLI（SWAS 云助手 RunCommand + OSS） |
| `ACR_USERNAME/PASSWORD` | 容器镜像推送（历史遗留，线上已不消费） |
| `DASHSCOPE_API_KEY` | LLM API |
| `SMOKE_ADMIN_PASSWORD` | 冒烟测试登录 |
| `SMOKE_SERVICE_TOKEN` | 服务间调用 + agent-eval 评测 |

---
详见: [部署指南](../deployment/deployment-aliyun.md)（SAE 章节为历史遗留）· [部署检查清单](../deployment/deployment-checklist.md)
