# 剧本 KB-CLOSED-LOOP S1：行业模板套用（生产）
环境：admin-api 生产（api.migaozn.com）/ tenant1（词元通达）/ main 211f6503
执行时间：2026-09-08 23:1x

## 动作
1. GET /api/admin/knowledge/templates（Bearer admin token）
   → success:true, data:[{templateId:"curtain", entryCount:32, name:"布艺窗帘行业模板"}]
2. POST /api/admin/knowledge/templates/curtain/apply
   → success:true, data:{skipped:0, templateId:"curtain", created:32}
3. GET /api/admin/knowledge/cards/search?query=清洗
   → 命中 4 条：[窗帘多久清洗一次？怎么清洗？|template|published]、[窗帘发霉了怎么处理？|template|published]、[窗帘面料有甲醛吗？环保吗？|template|published]

## 验收点
- [x] L1 模板目录返回 curtain（entryCount=32）
- [x] L1 一键套用 created=32（全量复制，无跳过）
- [x] L1 套用后检索命中模板卡片（sourceType=template, status=published）
