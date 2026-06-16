# 云验收协议（AI 研发 ↔ 军师）

## 适用场景

PR 合 main → 部署到云 dev/staging → 研发 AI 验收 → 出 JSON 报告 → 军师判定。

## 角色

- **军师**：派工 + 收报告 + 判定
- **研发 AI**：跑验收 + 出 JSON 报告
- **凯总/娜总**：看群里汇报

## 4 步验收（AI 研发自己跑）

1. **API 校验**：用 curl 调对应端点
2. **DB 直查**：用 psql 跑业务真值对应 SQL
3. **页面校验**：用 Playwright headless 跑流程，断言 DOM
4. **一致性**：3 层数据必须一致

## 报告格式

```json
{
  "issue": N,
  "step1_api": {"url": "...", "value": 0, "passed": true},
  "step2_db": {"sql": "...", "value": 0, "passed": true},
  "step3_page": {"url": "...", "value": 0, "passed": true},
  "consistency": {"api_db": true, "page_db": true},
  "verdict": "pass",
  "timestamp": "..."
}
```

verdict：
- `pass` — 4 步全过
- `fail` — 任何一步失败（需带原因）
- `manual_review` — 业务真值无法自动断言（需人工）

## 工具（AI 友好）

| 工具 | 用途 | 输出 |
|---|---|---|
| curl + jq | API 校验 | JSON |
| psql | DB 直查 | count / 字段 |
| Playwright headless | 页面校验 | DOM text / URL |

**0 视觉、0 截图、纯结构化**。

## 环境变量

研发 AI 自管（不在 git）：
- `API_BASE_URL`
- `WEB_BASE_URL`
- `DB_HOST` / `DB_USER` / `DB_NAME` / `DB_PWD`
- `E2E_ADMIN_PHONE` / `SMS_CODE`

## 失败处理

- 验收 fail → 军师 block + @对应研发
- 研发修完重提 PR → 重派云验收
- 凯总/娜总可在 issue 评论 override（标 `override/keep-open` 或 `override/close`）

## 反推的 case 在哪

- 模板库：`docs/verification-templates/*.yml`（8 个常见模式）
- 军师反推的 case 草稿：原 issue 的"待写 case 草稿"段
