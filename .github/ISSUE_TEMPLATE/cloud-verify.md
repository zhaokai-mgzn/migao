---
name: 云验收任务
about: 部署到云 dev/staging 后由研发 AI 验收
title: "[云验收] "
labels: ["needs-verification", "needs-cloud-verify"]
assignees: []
---

## 来源 issue
关联：#_____

## 环境变量
```
API_BASE_URL= WEB_BASE_URL=
DB_HOST= DB_USER= DB_NAME= DB_PWD=
E2E_ADMIN_PHONE= SMS_CODE=
```

## 业务真值（从原 issue 复制）
1. 
2. 

## 验收步骤
1. **API 校验**：curl 调对应端点，断言响应字段
2. **DB 直查**：psql 跑业务真值对应 SQL，断言 count
3. **页面校验**：Playwright headless 跑对应流程
4. **一致性**：3 层数据一致（API = DB = 页面）

## 验收报告
```json
{"issue":0,"step1_api":{"value":0,"passed":true},"step2_db":{"value":0,"passed":true},"step3_page":{"value":0,"passed":true},"verdict":"pass","timestamp":""}
```
verdict: `pass` / `fail` / `manual_review`

——军师（自动派工）

<!-- CONTRACT_JSON
{"schema_version":"1.0","type":"cloud-verify","parent_issue":0,"business_truths":[],"env_required":["API_BASE_URL","WEB_BASE_URL","DB_HOST","DB_USER","DB_NAME","DB_PWD"]}
-->
