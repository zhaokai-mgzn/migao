---
name: 功能验收 (AI 验收)
about: 含 AI 自动验收契约的功能需求
title: "[功能] "
labels: ["needs-verification"]
assignees: []
---

## 业务背景
<!-- 凯总/娜总描述：要做什么业务？解决什么问题？ -->

## 业务真值（必填 — AI 验收的唯标准）
<!--
⚠️ 铁律：业务语言，不带 SQL/API。
✅ 正确：含加工待发货 = 状态为待发货 且 含加工项
❌ 错误：SELECT COUNT(*) FROM orders WHERE status='pending_shipment'
每条真值独立一行：编号. 条件 → 期望结果
-->
1. 
2. 
3. 

## 涉及范围
- [ ] 后端 admin-api（Java）
- [ ] 后端 ai-agent-service（Python）
- [ ] 前端 admin-web（Next.js）
- [ ] 前端 mini-app（Taro）
- [ ] 涉及新页面：_____
- [ ] 涉及新 API：_____
- [ ] 涉及新 Tool：_____
- [ ] 涉及 SSE 事件：_____

## 红牌标记 / 不在本次范围
- 

---

<!-- 以下由军师自动填充，研发 review -->

## Case 草稿（军师反推）
### L2 单测（军师自动填充）
### L3 E2E Web（军师自动填充）
### L4 业务断言（军师自动填充）

## 研发 review
- ✅ 同意 → 认领 issue + 写码 + 开 PR
- ❌ 不同意 → 评论 "X case 不合理，原因是 Y"
- ➕ 补 case → 直接编辑 issue body

<!-- CONTRACT_JSON
{
  "schema_version": "1.0",
  "type": "feature",
  "business_truths": [],
  "affected_modules": [],
  "red_flags": [],
  "exclusions": []
}
-->
