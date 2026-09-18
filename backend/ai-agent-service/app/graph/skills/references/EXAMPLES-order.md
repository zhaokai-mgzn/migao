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
→ product_detail → 商品档案（SKU/规格；**不含**加工项）
→ **加工项环节（confirm 前必做）**：processing_item_query() 拿**店铺目录**（与商品无关，#4371）
   → interact(choice, multiSelect=true) 展示（透传 pageMeta；目录为空才告知"暂无可用加工项"）
→ 用户: "不需要加工项" / 选择加工项
→ confirm: "确认创建？张三 138xxxx，翻领刺绣客厅窗帘×2"（含加工项则列出名称+金额）
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
→ product_detail(遮光窗帘) → skus=[...]；processing_item_query() → 店铺目录=[{id:"pi_shape_high", name:"高温定型", unit_price:20, unit:"米", pricing_method:"per_meter"}, ...]
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
规则：用户要求加工时，**必须**把加工项填入 processing_info.processingItems 且 processingFee 计入 subtotal。按米计价的加工项加工数量 = 面料米数。

### 例5b: 按米计价加工项（数量=面料米数，辅料含在加工费中）
用户: "王先生 13900139000，遮光窗帘 3 米，要打孔加工"
```
→ processing_item_query(keyword="打孔") → 目录=[{id:"pi-punch", name:"打孔（罗马圈）", unit_price:8, pricing_method:"per_meter"}]
→ 加工费：8 元/米 × 3 米 = 24 元（罗马圈等辅料已含在按米加工费中）
→ order_create(items=[{product_name:"遮光窗帘", quantity:3, unit_price:88, subtotal:288,
    processing_info:{processingFee:24, processingItems:[{id:"pi-punch", name:"打孔（罗马圈）", unitPrice:8, quantity:3, pricingMethod:"per_meter", subtotal:24}]}}])
→ ✅ 总额 ¥288（面料 ¥264 + 打孔加工 ¥24.00）
```
规则：per_meter 数量 = 面料米数；per_set/fixed 数量 = 1；per_area 数量 = 宽×高。禁止「每米几个」的密度推导（辅料含在按米加工费中，issue #3005）。

### 例6: 完成订单被拒（状态不符合）
用户: "把 ORD-002 完成"
```
→ order_query(order_no="ORD-002") → 当前状态: confirmed（待发货）
→ "订单 ORD-002 当前状态为「待发货」，需先发货后才能确认收货。
   要我先帮您发货吗？"
```
规则：状态不符合前置条件时，告知用户并引导下一步。

### 例7: 用指代查物流（订单号 → 轨迹，同一轮走完）
用户: "那用我最近一笔订单的订单号查一下物流"
```
→ order_query(action=list, page_size=1)           # 第 1 步：拿到真实订单号（入参）
→ logistics_track(order_id="20260915294490006")   # 第 2 步：**同一轮内继续**查轨迹（交付物）
→ "【顺丰速运】SF1234…，当前状态：运输中；最新：快件已到达【杭州转运中心】（04-18 14:30）"
```
规则：订单号只是**入参** ⇒ 查到后**必须继续**调 `logistics_track(order_id=…)` 再回复；
**查到订单号就停下汇报订单信息 = 没完成**。工具答「尚未发货/未找到该订单」同样如实转述（也要真调工具）。

## ❌ 错误示例

### 反例1: 编造物流数据 / 把中间结果当交付物
用户: "查下 ORD-xxx 的物流"
```
❌ "物流显示已签收，签收人是..."  （未调用 logistics_track，凭印象编造）
✅ 调 logistics_track(order_id="ORD-xxx") → 展示真实数据
```
用户: "那用我最近一笔订单的订单号查一下物流"
```
❌ 只调 order_query → "您最近一笔订单是 20260915294490006（赵凯，待付款）" 就停手
   （订单号只是**入参**，顾客要的轨迹一个字都没给 = 链只走了一半）
✅ order_query 拿到 20260915294490006 → **继续**调 logistics_track(order_id="20260915294490006")
   → 如实回复工具返回的状态/轨迹（未发货就照实说"该订单尚未发货"）
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

### 反例4: 编造分色价（库价 168 却写「米白 150」）
用户: "遮光窗帘 3 米，要米白，散剪，门幅 2.8m"
```
❌ 规格卡/确认卡写「米白 ¥150/米」（product_detail 已返回库价 168、SKU 无分色差价）
   → order_create(unit_price=150) 被系统拦截（单价与商品库不符），浪费一轮；
   ✅ 每个颜色统一标库价 ¥168（库价/所选 SKU 价），order_create(unit_price=168)
   → 系统校验通过、落单成功
```
```
❌ 用户说「¥168/米」，agent 却坚持「商品库里这个规格的单价是 ¥150/米」
   （库价 168 就是 168——以 product_detail 的 price / skus[].price 为准，
   不要自己推导/记住一个不同的数，更不要反过来纠正用户）
```
