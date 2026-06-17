---
name: 云验收任务
about: 部署类问题的手动验收（基础设施变更时使用，日常不用）
title: "[云验收] "
labels: ["needs-cloud-verify"]
assignees: []
---

## 来源 issue
关联：#_____

## 环境变量
```
API_BASE_URL=https://api.migaozn.com
WEB_BASE_URL=https://admin.migaozn.com
DB_HOST= DB_USER= DB_NAME= DB_PWD=
```

## 验收步骤
1. API curl 对应端点
2. psql 跑业务真值 SQL
3. Playwright headless 跑对应页面
4. 三层数据一致

## 验收报告
```json
{"verdict":"pass|fail","timestamp":""}
```

> ⚠️ 日常业务流程 issue 不需要这个模板。只有改 Terraform/SAE 配置时才用。

<!-- CONTRACT_JSON
{"schema_version":"1.0","type":"cloud-verify","parent_issue":0,"business_truths":[]}
-->
