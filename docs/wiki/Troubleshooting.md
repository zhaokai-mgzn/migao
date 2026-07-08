# 常见问题排查

## 端口速查

| 服务 | 默认端口 | 配置文件 |
|------|---------|---------|
| admin-api | 8080 | `application.yml` → `server.port` |
| ai-agent-service | 8000 | `config.py` → `PORT` |
| admin-web | 3001 | `package.json` → `next dev -p` |

> CLAUDE.md 启动命令中 ai-agent 传了 `--port 8001` 覆盖默认值，wiki 文档以代码默认端口为准。

## 启动问题

**admin-api 启动失败**
- 检查 `application.yml` 中 DB_URL / REDIS_URL 指向云 dev
- `lsof -i :8080` 确认端口未被占用
- `./mvnw clean compile` 确认编译通过

**ai-agent-service 启动失败**
- 确认 `.venv` 已创建: `python -m venv .venv && .venv/bin/pip install -r requirements.txt`
- 检查 `.env` 中 PRIMARY_API_KEY 等密钥已配置
- Python 版本 ≥ 3.11

**admin-web 启动失败**
- `npm install` 确认依赖安装
- `npx tsc --noEmit` 确认类型无错误
- 检查 NEXT_PUBLIC_API_URL / NEXT_PUBLIC_AI_URL

## 数据库迁移

**迁移失败不阻塞启动** — `MigrationRunner` 会将错误记入日志但不阻止应用启动（可能已在 DB 手动执行过）。查看 SAE 日志确认：
```
✅ 迁移完成: V9__xxx.sql
❌ 迁移失败: V9__xxx.sql  (手动检查是否已执行)
```
手动标记已执行: `INSERT INTO schema_migrations (version) VALUES ('V9__xxx.sql');`

## AI 服务常见问题

**LLM 调用超时/失败**
- 检查 PRIMARY_API_KEY 是否有效、额度是否用尽
- 检查 DeepSeek API 服务状态
- 熔断器会记录连续失败，超过阈值自动降级为规则匹配

**RAG 检索返回空**
- 确认知识库文档已完成向量化 (`embedding_status = 'completed'`)
- 检查 DashVector collection 是否存在: `tenant_{tenant_id}` 格式
- 向量化异步任务可能还在队列中，查 `embedding_tasks` 表

**Tool 调用死循环**
- `SessionMemory` flag 防护: 同一 session 同一 tool 只触发一次
- 检查是否触发了 `pending_skill` 死锁 (已通过集成测试兜底)

## E2E 测试

**Playwright 认证失败**
- 删除 `tests/e2e/.auth/admin.json` 重新生成
- 确认本地服务已启动且可访问

**SSE 测试超时**
- 增加 `timeout` 配置
- 检查 ai-agent-service 日志确认 SSE 流正常推送

## SAE 部署

**健康检查失败**
- 检查 `/actuator/health` (admin-api) 或 `/health` (ai-agent) 可访问
- 确认 DB/Redis 连接在 SAE 安全组白名单内
- 查看 SLS 日志排查启动异常

---
详见: [部署检查清单](../deployment/deployment-checklist.md) · [SLS 日志查询 Skill](../../.claude/skills/aliyun-sls-log-query.md)
