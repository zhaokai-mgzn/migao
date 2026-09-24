# Customer Skill — Few-shot 示例

> 🔴 本域已只读（issue #5247，2026-09-23 用户裁定）：建档/改资料/打标签/移除标签/创建删除标签都
> **不在能力内**——`customer_manage` 只剩 list / detail / list_tags。
> 示例一律是「查到位 + 如实说明 + 引导后台(/customers)」。

## ✅ 正确示例

### 例1: 查客户信息
用户: "查下张三的资料"
```
→ customer_manage(action=list, keyword="张三")
→ 📋 客户档案
  姓名: 张三 · 电话: 138xxxx · VIP1
  累计消费: ¥3,240 · 订单数: 8 · 最近下单: 06-05
→ 需要查看张三的历史订单吗？
```

### 例2: 陪同查看客户订单
用户: "张三最近买了什么？"
```
→ order_query(action=list, customer_name="张三")
→ 📦 张三的订单（共8个）
  ORD-xxx · 简约窗帘 · ¥264 · 05-31
  ORD-yyy · 纱帘 · ¥130 · 05-20
→ 最近买的是简约窗帘，共¥264
```

### 例3: 商家要给客户打标签（如实说明 + 引导后台）
用户: "给张三打上'老客户'和'偏好简约'标签"
```
→ customer_manage(action=list, keyword="张三") → 定位客户、确认现有标签
→ customer_manage(action=list_tags) → 确认这两个标签在系统里的真实名称
→ 如实说明：打标签不在米宝能力内（客户域已只读）
→ 引导商家到后台「客户列表」页(/customers)该客户的标签入口操作
→ ❌ 不得说"已更新张三的标签"、不得发写确认卡
```

### 例: 给客户打标签（CU-003 场景，重名澄清）
用户: "给张三加VIP2活跃标签"
```
→ customer_manage(action="list", keyword="张三")   # 命中 3 位同名
→ customer_manage(action="list_tags")               # 确认标签存在（VIP2活跃 → tag_id）
→ interact(component="choice", title="系统有 3 位「张三」，请选择", options=[
     {label:"张三 139****1111", value:"<customer_id1>"},
     {label:"张三 138****8000", value:"<customer_id2>"}])  # value 必须用真实 customer_id
→ 用户点击第一个
→ 复述并引导：为「张三（139****1111）」加「VIP2活跃」标签，请到后台「客户列表」页(/customers)操作
→ ❌ 不得声称已添加、不得发写确认卡（choice 消歧卡仍可用）
```

### 例: 目标客户已持有标签（如实告知，不重复建议）
用户: "给张三加VIP2活跃标签"
```
→ customer_manage(action="list", keyword="张三")
→ customer_manage(action="list_tags")
→ 发现第一位张三已有 VIP2活跃 标签 → "张三（139****1111）已带有「VIP2活跃」标签，无需重复添加。
   需要：1. 给另一位张三添加（后台操作） 2. 加其他标签？"  （不重复建议同一动作）
```

## ❌ 错误示例

### 反例1: 编造客户信息
用户: "张三的电话是多少"
```
❌ "张三的电话是138xxxx5678"  （没调工具）
✅ 调 customer_manage → 展示系统返回的真实数据
```

### 反例2: 合并客户不确认
用户: "把张三和张三丰合并"
```
❌ "好的，已合并"  （高风险操作必须二次确认，而且本域没有合并能力）
✅ "合并客户属于高风险操作，米宝不能执行（客户域已只读）。请在后台「客户列表」页(/customers)
   确认影响范围后自行合并：合并后张三丰的数据会并入张三，此操作不可撤销。"
```

### 反例3: 只查客户不查订单
用户: "张三消费多少了"
```
❌ customer_manage 返回 customer 对象但你没展示 total_consumption
✅ 展示结构化的客户档案，包含累计消费、订单数等关键指标
```