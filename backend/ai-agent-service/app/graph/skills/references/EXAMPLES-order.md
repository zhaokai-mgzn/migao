# Order Skill — Few-shot 示例

## ✅ 正确示例

### 例1: 查待发货订单
用户: "查下待发货的订单"
```
→ order_query(action=list, status="pending_ship")
→ 📦 待发货订单（共3个）
  ORD-xxx · 张三 · ¥264 · 2件 · 05-31
→ 需要查看哪个订单的详情？
```

### 例2: 创建订单（P&E 引导）
用户: "给张三创建一个订单"
```
→ 进入 P&E 流程
→ ask: "请提供客户姓名、电话、地址、商品名称和数量"
→ 用户: "张三，138xxxx，翻领刺绣客厅窗帘，2件"
→ query: product_search(keyword="翻领刺绣客厅窗帘") → 显示商品列表
→ 用户: "选1"
→ confirm: "确认创建？张三 138xxxx，翻领刺绣客厅窗帘×2"
→ 用户: "确认"
→ order_create(...) → "订单已创建 ORD-xxx"
```

### 例3: 修正商品选择
用户: "等一下，不是这个窗帘，换简约窗帘"
```
→ 系统检测到修正意图 → 回到 query 步重新搜索
→ product_search(keyword="简约窗帘") → 新列表
→ 用户: "2"
→ 继续流程
```

### 例4: 确认收货（完成订单）
用户: "ORD-001 的货收到了，帮我完成这个订单"
```
→ order_query(order_no="ORD-001") → 当前状态: shipped
→ confirm: "确认将订单 ORD-001 标记为已完成（确认收货）？"
→ 用户: "确认"
→ order_manage(action=update_status, order_id="ORD-001", status="completed")
→ ✅ "订单 ORD-001 已确认收货，交易完成"
```
规则：只有 shipped 状态才能 completed；先查状态再操作。

### 例5: 创建带加工项的订单（加工费必须计入）
用户: "李女士 13800138000，买遮光窗帘 3 米，要高温定型加工，地址杭州西湖区"
```
→ product_detail(遮光窗帘) → skus=[...], processing_items=[{id:"pi_shape_high", name:"高温定型", finalPrice:20, unit:"米", pricingMethod:"per_meter"}, ...]
→ 用户确认 3 米 + 高温定型
→ order_create(
    customer_name="李女士", customer_phone="13800138000",
    items=[{
      product_id="...", product_name="遮光窗帘", quantity=3, unit_price=88,
      subtotal=264 + 60 = 324,   # 面料小计 + 加工费，必须含加工费！
      processing_info={
        colorId=..., colorName=..., sellingMethod="bulk_cut", doorWidth="2.8米",
        processingFee=60,  # 3米 × ¥20/米
        processingItems=[{id:"pi_shape_high", name:"高温定型", unitPrice:20, quantity:3, unit:"米", pricingMethod:"per_meter", subtotal:60}]
      }
    }])
→ ✅ 订单已创建，总额 ¥324（面料 ¥264 + 加工费 ¥60）
```
规则：用户要求加工时，**必须**把加工项填入 processing_info.processingItems 且 processingFee 计入 subtotal。按米计价的加工项加工数量 = 面料米数。漏传加工项/漏算加工费 = 订单金额错误。

### 例6: 完成订单被拒（状态不符合）
用户: "把 ORD-002 完成"
```
→ order_query(order_no="ORD-002") → 当前状态: confirmed（待发货）
→ "订单 ORD-002 当前状态为「待发货」，需先发货后才能确认收货。
   要我先帮您发货吗？"
```
规则：状态不符合前置条件时，告知用户并引导下一步。

## ❌ 错误示例

### 反例1: 编造订单数据
用户: "查下 ORD-xxx 的物流"
```
❌ "物流显示已签收，签收人是..."  （未调用 logistics_track）
✅ 调 logistics_track(order_no="ORD-xxx") → 展示真实数据
```

### 反例2: 跳过确认直接创建
用户: "创建订单，张三 138xxxx 简约窗帘 2件"
```
❌ 直接调 order_create(...) （跳过了确认步骤）
✅ 进入 P&E: ask → query → confirm → execute
```

### 反例3: 不展示关键信息
用户: "查订单"
```
❌ "查到了3个订单"  （没有订单号、客户、金额）
✅ 用表格展示：订单号、客户、金额、时间、状态
```
