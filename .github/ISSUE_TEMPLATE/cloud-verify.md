---
name: 云验收任务
about: 部署到云 dev/staging 后由研发 AI 验收
title: "[云验收] "
labels: ["needs-verification", "needs-cloud-verify"]
---

## 环境变量（自行设置，git ignore）

```
API_BASE_URL=
WEB_BASE_URL=
DB_HOST= DB_USER= DB_NAME= DB_PWD=
E2E_ADMIN_PHONE= SMS_CODE=
```

## 业务真值（issue #N）

<!-- 复制原 issue 的业务真值段 -->

## 验收步骤

1. **API 校验**：curl 调对应端点，断言响应字段
2. **DB 直查**：psql 跑业务真值对应 SQL，断言 count
3. **页面校验**：Playwright headless 跑对应流程，断言 DOM 文本 / 跳转 URL
4. **一致性**：3 层数据必须一致（API 数字 = DB 数字 = 页面数字）

## 验收报告（请贴 JSON 在本 issue 评论）

```json
{
  "issue": N,
  "step1_api": {"value": 0, "passed": true},
  "step2_db": {"value": 0, "passed": true},
  "step3_page": {"value": 0, "passed": true},
  "verdict": "pass",
  "timestamp": "..."
}
```

verdict: `pass` / `fail` / `manual_review`

## 参考

- 协议：`docs/cloud-verify-protocol.md`
- 模板：`docs/verification-templates/*.yml`（参考反推的 spec）

——军师（自动派工）
