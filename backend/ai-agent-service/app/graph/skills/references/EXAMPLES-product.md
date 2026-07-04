# Product Skill — 正确执行示例

## 示例 1：完整创建

用户: "创建遮光窗帘 50元"
Step 1: 米宝调 category_manage(tree) → 问名称/价格/颜色/售卖方式
Step 2: 用户回 "遮光窗帘，50元，米白色，散剪" → 米宝引导货号 → 调 processing_item_query → interact(choice,multiSelect=true,options=[{label:"打孔加工 ¥8/米",value:"pi_2934..."}])
Step 3: 用户选加工项 → 汇总确认(名称/货号/价格/颜色/加工项)
Step 4: 确认 → product_manage(action=create,name="遮光窗帘",price=50,status="on_sale",sku_code="ZG-001",processing_item_ids=["pi_2934...","pi_a8f3..."]) → 完成

## 示例 2：图片识别

用户上传图片说 "创建这个商品" → 识别结果预填表单 → 引导补充 → 货号从色卡提取 → 加工项 interact choice → 汇总→执行。图片结果直接引用，不让用户重复输入。

## 示例 3：信息不完整

用户 "创建一个商品" → 逐项引导：名称/价格/货号/分类/售卖方式/颜色。不编造数据。

## 反例

❌ 序号表格让用户输数字回选（UUID 丢失）
❌ 跳过货号引导
❌ 只汇总不执行(tools=0)
❌ 编造数据或跳过 validate_input
❌ 同一 turn 弹多个组件
