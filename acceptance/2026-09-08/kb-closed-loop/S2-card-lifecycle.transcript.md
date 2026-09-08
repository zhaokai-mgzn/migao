# 剧本 KB-CLOSED-LOOP S2：知识卡片生命周期（生产）
环境：admin-api 生产 / tenant1 / main 211f6503

## 动作
1. POST /api/admin/knowledge/cards
   body {title:"验收测试-定制窗帘交货周期", category:"aftersale", question:"定制的窗帘多久能做好？",
         answer:"常规面料 7-10 个工作日，特殊面料 15-20 个工作日（验收剧本测试数据）。", keywords:"交货,周期,定制"}
   → success:true, data:{id:"0e70a654c349a22818a0a41e39662ca9", status:"draft", sourceType:"manual", version:1}
2. POST /api/admin/knowledge/cards/0e70a654.../publish
   → data:{status:"published", reviewedAt:非空}
3. GET /api/admin/knowledge/cards/search?query=交货周期
   → 命中 1 条：[验收测试-定制窗帘交货周期|published]

## 验收点
- [x] L1 创建（draft/sourceType=manual/version=1）→ 发布（published+reviewedAt）→ 检索命中（发布后可查）
- [x] L1 生命周期闭环：draft→published→可检索（归档不可查由单测覆盖：KnowledgeCardServiceTest）
