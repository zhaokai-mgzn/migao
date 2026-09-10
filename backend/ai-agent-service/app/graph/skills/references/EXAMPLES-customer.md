# Customer Skill — Few-shot 示例

## ✅ 正确示例

### 例1: 查客户信息
用户: "查下张三的资料"
```
→ customer_manage(action=search, keyword="张三")
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

### 例3: 添加客户标签
用户: "给张三打上'老客户'和'偏好简约'标签"
```
→ "确认给张三添加标签：老客户、偏好简约？"
→ 用户: "确认"
→ customer_manage(action=update, tags=["老客户", "偏好简约"])
→ "已更新张三的标签"
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
❌ "好的，已合并"  （高风险操作必须二次确认）
✅ "确认合并张三和张三丰？合并后张三丰的数据会并入张三，此操作不可撤销。"
```

### 反例3: 只查客户不查订单
用户: "张三消费多少了"
```
❌ customer_manage 返回 customer 对象但你没展示 total_consumption
✅ 展示结构化的客户档案，包含累计消费、订单数等关键指标
```

### 例: 给客户打标签（CU-003 场景，重名澄清 + 确认卡）
用户: "给张三加VIP2活跃标签"
```
→ customer_manage(action="list", keyword="张三")   # 命中 3 位同名
→ customer_manage(action="list_tags")               # 确认标签存在（VIP2活跃 → tag_id）
→ interact(component="choice", title="系统有 3 位「张三」，请选择", options=[
     {label:"张三 139****1111", value:"<customer_id1>"},
     {label:"张三 138****8000", value:"<customer_id2>"}])  # value 必须用真实 customer_id
→ 用户点击第一个
→ validate_input(target_tool="customer_manage", target_action="add_tag", params={customer_id:"<customer_id1>", tag_id:"<tag_id>"})
→ interact(component="confirm", fields=[{label:"客户",value:"张三（139****1111）"},{label:"操作",value:"添加标签"},{label:"标签",value:"VIP2活跃"}])
→ 用户: "确认"
→ customer_manage(action="add_tag", customer_id="<customer_id1>", tag_id="<tag_id>")
→ "已为张三（139****1111）添加「VIP2活跃」标签 ✅"
```

### 例: 目标客户已持有标签（幂等跳过）
用户: "给张三加VIP2活跃标签"
```
→ customer_manage(action="list", keyword="张三")
→ customer_manage(action="list_tags")
→ 发现第一位张三已有 VIP2活跃 标签 → "张三（139****1111）已带有「VIP2活跃」标签，无需重复添加。
   需要：1. 给另一位张三添加 2. 加其他标签？"  （不盲目重复 add_tag）
```
