# 剧本 KB-CLOSED-LOOP S4：提炼采纳流（生产，含 P1 发现）
环境：admin-api 生产 / tenant1 / main 211f6503

## 动作（部署前 211f6503 未部署时，ai-agent 为 0fc27850 旧版）
1. POST /api/admin/knowledge/distill/documents（标题：验收-售后手册，内容 ~250 字售后政策）
   → data:{candidates:0, created:0, skipped:0}
   （before：ai-agent 旧版无 /internal/knowledge/distill，admin-api 降级空候选）

## 动作（部署完成后，ai-agent 已更新 211f6503）
2. POST /api/admin/knowledge/distill/documents（同内容重放）
   → data:{candidates:0, created:0, skipped:0}   ← after 仍为 0
3. POST /api/admin/knowledge/distill/conversations?hours=72
   → data:{sessions:0, candidates:0, created:0, skipped:0}（72h 内无 ended 人工会话，数据状态所致）
4. GET /api/admin/knowledge/candidates/pending-count → {pending:0}

## 验收点
- [x] L1 待确认队列读写路径存在（candidates/pending-count 端点可用、空态正常）
- [ ] L1 文档提炼在生产产出候选（**失败：重放前后均为 0 候选**）→ P1 发现
- [ ] L1 采纳闭环生产端到端（**未验证**：候选为空，无对象可采纳；采纳→卡片逻辑由单测 L1 覆盖 KnowledgeCandidateServiceTest 8 用例）
- [x] L1 提炼链路容错：ai-agent 不可用/无候选时接口不报错、返回空统计（fail-closed 降级生效）

## P1 发现：生产文档提炼返回 0 候选
- 证据：S4 步骤 1/2（部署前后均 candidates:0）
- 机制假设（待 issue 排查）：① admin-api 生产 AI_AGENT_SERVICE_TOKEN 缺失/不匹配 → internal 401 → 降级空；② distill LLM 在生产返回不可解析内容（模型/超时）；③ 30s 读超时截断
- 对照：小布公开聊天 knowledge_search 正常（S3）→ ai-agent 本身可用；问题在 admin-api→ai-agent internal 链路或 distill LLM 解析
