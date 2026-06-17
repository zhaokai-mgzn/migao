---
name: Bug 验收
about: 含 AI 自动验收契约的 Bug 修复
title: "[Bug] "
labels: ["bug", "needs-verification"]
assignees: []
---

## Bug 现象
<!-- 业务语言：什么场景出问题？用户看到什么？ -->

## 复现步骤
1. 
2. 
3. 

## 业务真值（修复后必须满足）
<!-- 业务语言，不带 SQL/API。每条：编号. 条件 → 期望结果 -->
1. 
2. 

## 复现失败测试（TDD 铁律）
<!-- 修复前必须写一个能复现 Bug 的失败测试 -->
- **测试文件**：_____
- **测试场景**：_____
- **期望结果**（修复前应 FAIL）：_____

## 涉及范围
- [ ] admin-api（Java）
- [ ] ai-agent-service（Python）
- [ ] admin-web（Next.js）
- [ ] mini-app（Taro）

---

## Case 草稿（军师反推）
### L2 单测 / L3 E2E / L4 断言（军师自动填充）

<!-- CONTRACT_JSON
{
  "schema_version": "1.0",
  "type": "bug",
  "business_truths": [],
  "repro_steps": [],
  "failing_test": { "file": "", "scenario": "", "expected_fail": "" },
  "affected_modules": []
}
-->
