# 贡献指南

## 分支策略

```
feat/<scope>-<short-desc>     # 新功能
fix/<scope>-<short-desc>      # Bug 修复
chore/<scope>-<short-desc>    # 杂项/配置/文档
```

scope 取值：`frontend` / `backend` / `ai-agent` / `qa` / `infra`

## Commit 规范

```
feat(frontend): 新增商品管理页面
fix(backend): 修复 JWT Token 过期未正确返回 401
test: 补充订单 API 集成测试
refactor(backend): 优化商品查询 SQL 性能
chore: 更新部署文档
```

## 开发流程

1. 从 `main` 创建 feature/fix 分支
2. 遵循 **AI-TDD** 流程开发（详见 `CLAUDE.md`）
3. 本地测试通过后提交 PR
4. PR 必须关联 Issue（`Fixes #xxx` / `Closes #xxx`）
5. PR 需通过 CI 全绿 + Review approve 后方可合并

## 代码规范

- **Java 后端**: Spring Boot 3.3, MyBatis-Plus, JUnit 5
- **Python AI 服务**: FastAPI, LangGraph, pytest
- **前端**: Next.js 14, TypeScript, Tailwind CSS, Vitest
- **TDD 铁律**: 先写测试 → 确认 FAIL → 写实现 → 确认 PASS
- 详见 `CLAUDE.md` 和各模块 README
