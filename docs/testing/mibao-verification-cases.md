# 米宝真实验证对话 Case

## 前置
启动服务后，打开 http://localhost:3001 → 登录 → 进入米宝对话

---

## Round 1: 基础查询（验证 tool 调用 + suggestion）

### Case 1.1 商品搜索
```
👤 有什么遮光窗帘
✅ 期望: 触发 product_search，返回商品列表，有 summary 信息
```

### Case 1.2 空搜索 → suggestion
```
👤 有没有xyz
✅ 期望: 触发 product_search，空结果，LLM 用 suggestion 引导"换个关键词试试"
```

### Case 1.3 订单查询
```
👤 查一下最近的订单
✅ 期望: 触发 order_query(list)，返回订单列表，标注 [工具返回]
```

### Case 1.4 物流追踪
```
👤 查一下 ORD-xxx 的物流（替换为实际订单号）
✅ 期望: 触发 logistics_track，展示物流状态
```

---

## Round 2: 写操作确认（验证 annotations + suggestion）

### Case 2.1 取消订单 — 破坏性操作确认
```
👤 取消 ORD-xxx（替换为实际订单号）
✅ 期望: LLM 先确认"真的要取消吗？"，不直接调 order_manage
```

### Case 2.2 确认取消
```
👤 确认取消
✅ 期望: 触发 order_manage(action=cancel)，返回取消结果
```

---

## Round 3: 复杂创建流程（验证 validate_input + pending skill）

### Case 3.1 创建商品 — 缺信息
```
👤 帮我创建一个窗帘商品
✅ 期望: LLM 先查 category_manage(tree)，然后引导提供名称+价格
```

### Case 3.2 补全信息
```
👤 简约纱帘，99元
✅ 期望: LLM 继续询问颜色、售卖方式等缺失字段
```

### Case 3.3 修正信息
```
👤 价格改成 76，加个米白色
✅ 期望: LLM 更新价格，展示汇总，请求确认
```

### Case 3.4 确认创建
```
👤 确认创建
✅ 期望: 触发 validate_input → product_manage(create)，返回创建成功
```

### Case 3.5 验证结果
```
👤 帮我确认一下刚才那个创建好了吗
✅ 期望: 触发 product_detail 或 product_search，确认商品存在
```

---

## Round 4: 多轮对话 + 话题切换（验证 escape hatch + pending skill）

### Case 4.1 开始创建
```
👤 创建一个订单，张三，13812345678
✅ 期望: LLM 进入订单创建流程，询问商品明细
```

### Case 4.2 中途切话题（escape hatch）
```
👤 算了先不创建了，帮我查一下现在有哪些订单在路上
✅ 期望: LLM 切到 order_query，不锁死在创建流程。输入长度 > 10 字符触发 escape hatch
```

### Case 4.3 重新创建
```
👤 回到刚才的订单，张三，13812345678，要2件雪尼尔窗帘
✅ 期望: LLM 展示汇总，确认创建
```

---

## Round 5: 跨领域对话

### Case 5.1 订单 → 商品 → 物流
```
👤 我最近买的那个窗帘
✅ 期望: 查 order_query
👤 看看详情
✅ 期望: 查 product_detail
👤 现在到哪了
✅ 期望: 查 logistics_track
```

---

## Round 6: 小布 C 端

### Case 6.1 问候
```
👤 你好呀
✅ 期望: 回复含"小布"、"米高窗帘"，语气亲切，不含"同事"、"工作"
```

### Case 6.2 咨询商品
```
👤 有没有适合卧室的窗帘
✅ 期望: 触发 product_search，回复含"亲"等亲切用语
```

---

## Round 7: 来源标注验证

### Case 7.1 查数据 → 验证标注
```
👤 今天销售额多少
✅ 期望: 触发 dashboard_stats，回复标注 [工具返回]（不再是旧的"不标注来源"规则）
```

---

## 验证清单

在每个 Case 完成后勾选：

□ tool 调用正确触发
□ 回复包含预期关键词
□ 写操作有确认步骤
□ 创建流程跨轮保持（pending skill）
□ 长文本能切换话题（escape hatch）
□ 来源标注正确（[工具返回] 不是旧规则）
□ suggestion 被 LLM 使用
□ 小布语气亲切（不含"同事"、"工作"）
