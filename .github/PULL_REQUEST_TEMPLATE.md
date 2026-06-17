## 关联 Issue

Closes #_____

<!-- 如果是修复验收 block 的 PR，还需标注父 issue -->
Fixes #_____（父 issue，如适用）

## 改动摘要

<!-- 一句话：改了什么，为什么 -->

## 测试清单

- [ ] L2 单测：_____（文件路径，N 个测试）
- [ ] L3 E2E：_____（spec 路径）
- [ ] L0 持久化：_____（如涉及 State/路由，必填；不涉及填 N/A）

## 涉及模块

- [ ] admin-api（Java）
- [ ] ai-agent-service（Python）
- [ ] admin-web（Next.js）
- [ ] mini-app（Taro）

## 验收状态

<!-- merge 后军师会自动跑验收，此处为自检 -->

- [ ] 已本地跑全量单测（CP-5）
- [ ] 已本地跑增量集成测试（CP-6）
- [ ] 类型检查通过（`npx tsc --noEmit`）

<!-- PR_CONTRACT
{
  "issue_id": 0,
  "parent_issue": null,
  "l2_tests": [],
  "l3_specs": [],
  "l0_required": false,
  "modules": []
}
-->
