# 米宝 B端 全覆盖验证 Case

> 启动服务后按顺序执行。每一轮覆盖一个 Skill 的全部 tool + action。
> 每轮 Case 独立，可单独验证。小布 C端后续 MVP 结束后再测。

---

## 1. 订单 Skill (8 case)

### 1.1 订单列表查询 (order_query list)
```
你: 查最近的订单
期望: order_query(action=list) → 订单列表含订单号/客户/金额/状态
```

### 1.2 按状态筛选 (order_query list + status)
```
你: 有哪些待发货的订单
期望: order_query(action=list, status=confirmed)
```

### 1.3 订单统计 (order_query statistics)
```
你: 订单统计数据
期望: order_query(action=statistics) → 各状态汇总
```

### 1.4 订单跟进统计 (order_query follow_status_stats)
```
你: 订单跟进情况
期望: order_query(action=follow_status_stats)
```

### 1.5 物流追踪 (logistics_track)
```
你: 查 ORD-xxx 物流（替换实际订单号）
期望: logistics_track → 快递公司/运单号/轨迹
```

### 1.6 更新订单状态 (order_manage update_status)
```
你: ORD-xxx 已经发货了，标记一下
期望: LLM 确认 → order_manage(action=update_status, status=shipped)
```

### 1.7 取消订单 (order_manage cancel)
```
你: 取消 ORD-xxx
期望: LLM 二次确认 → order_manage(action=cancel)
```

### 1.8 创建订单 (order_create)
```
你: 创建订单：张三 13812345678，窗帘2件
期望: 汇总确认 → order_create → 返回订单号
```

---

## 2. 商品 Skill (14 case)

### 2.1 商品搜索 (product_search)
```
你: 搜一下遮光窗帘
期望: product_search → 商品列表
```

### 2.2 带筛选搜索 (product_search + stock_status)
```
你: 有哪些缺货的商品
期望: product_search(stock_status="out_of_stock")
```

### 2.3 商品详情 (product_detail)
```
你: 看一下 xxx 的详情（替换实际商品ID）
期望: product_detail → 价格/颜色/规格/库存
```

### 2.4 查库存 (inventory_manage query)
```
你: xxx 还有多少库存
期望: inventory_manage(action=query) → 库存数量
```

### 2.5 调整库存 (inventory_manage adjust)
```
你: xxx 出库10件，备注样品寄出
期望: 确认 → inventory_manage(action=adjust) → 新库存
```

### 2.6 低库存预警 (inventory_manage low_stock_alert)
```
你: 看看哪些商品库存不足
期望: inventory_manage(action=low_stock_alert)
```

### 2.7 商品上架 (product_manage toggle_status)
```
你: 把 xxx 上架
期望: 确认 → product_manage(action=toggle_status, status=on_sale)
```

### 2.8 更新商品 (product_manage update)
```
你: 把 xxx 的价格改成 129
期望: 确认 → product_manage(action=update, price=129)
```

### 2.9 创建商品完整流程 (product_manage create)
```
你: 创建商品：花序窗帘 23.8元 米白/浅灰 散剪
期望: 查分类树 → 搜重名 → 汇总确认 → product_manage(create)
```

### 2.10 分类树 (category_manage tree)
```
你: 看看商品分类
期望: category_manage(action=tree) → 树形分类
```

### 2.11 创建分类 (category_manage create)
```
你: 在窗帘布艺下新建"轻奢系列"分类
期望: 确认 → category_manage(action=create)
```

### 2.12 删除分类 (category_manage delete)
```
你: 删除"轻奢系列"分类
期望: 二次确认 + 风险提示 → category_manage(action=delete)
```

### 2.13 查加工项 (processing_item_query)
```
你: 有哪些加工项
期望: processing_item_query → 名称/价格/分类
```

### 2.14 加工项管理 (processing_item_manage)
```
你: 基础加工分类下有哪些
期望: processing_item_manage(action=list_categories)
```

---

## 3. 售后 Skill (4 case)

### 3.1 工单列表 (after_sales_manage list)
```
你: 看看售后工单
期望: after_sales_manage(action=list) → 工单列表
```

### 3.2 工单详情 (after_sales_manage detail)
```
你: 看一下 xxx 工单详情（替换实际ID）
期望: after_sales_manage(action=detail)
```

### 3.3 创建退款工单 (after_sales_manage create)
```
你: ORD-xxx 颜色不符，创建退款工单
期望: 收集确认 → after_sales_manage(action=create, ticket_type=refund)
```

### 3.4 更新工单状态 (after_sales_manage update_status)
```
你: xxx 工单已处理完，关闭
期望: 确认 → after_sales_manage(action=update_status, status=closed)
```

---

## 4. 客户 Skill (4 case)

### 4.1 客户列表 (customer_manage list)
```
你: 查客户列表
期望: customer_manage(action=list)
```

### 4.2 客户详情 (customer_manage detail)
```
你: 看张三的客户档案
期望: customer_manage(action=detail) → 姓名/电话/标签
```

### 4.3 打标签 (customer_manage add_tag)
```
你: 给张三加VIP标签
期望: 确认 → customer_manage(action=add_tag, tag="VIP")
```

### 4.4 更新资料 (customer_manage update)
```
你: 张三手机号改成 13900001111
期望: 确认 → customer_manage(action=update)
```

---

## 5. 人事 Skill (5 case)

### 5.1 员工列表 (employee_manage list)
```
你: 有哪些员工
期望: employee_manage(action=list) → 姓名/角色/状态
```

### 5.2 创建员工 (employee_manage create)
```
你: 新客服王五 13812345678，开账号
期望: 收集确认 → employee_manage(action=create)
```

### 5.3 禁用员工 (employee_manage toggle_status)
```
你: 王五离职了，停用账号
期望: 二次确认 → employee_manage(action=toggle_status, status=disabled)
```

### 5.4 角色列表 (role_manage list)
```
你: 系统有哪些角色
期望: role_manage(action=list)
```

### 5.5 创建角色 (role_manage create)
```
你: 新建"库管"角色，给商品和库存权限
期望: 确认 → role_manage(action=create)
```

---

## 6. 设置 Skill (7 case)

### 6.1 系统设置 (settings_manage get_settings)
```
你: 查看系统设置
期望: settings_manage(action=get_settings) → 商户名/行业
```

### 6.2 AI 配置 (settings_manage get_ai_config)
```
你: AI客服配置是什么
期望: settings_manage(action=get_ai_config)
```

### 6.3 修改密码 (settings_manage change_password)
```
你: 改密码，旧密码xxx 新密码yyy
期望: 确认 → settings_manage(action=change_password)
```

### 6.4 通知列表 (notification_manage list)
```
你: 看看通知
期望: notification_manage(action=list) → 列表/未读数
```

### 6.5 标记已读 (notification_manage mark_read)
```
你: 把新订单通知标为已读
期望: notification_manage(action=mark_read)
```

### 6.6 快捷回复列表 (quick_reply_manage list)
```
你: 看看快捷回复模板
期望: quick_reply_manage(action=list)
```

### 6.7 创建快捷回复 (quick_reply_manage create)
```
你: 新建"欢迎语"快捷回复：您好，欢迎咨询词元通达！
期望: 确认 → quick_reply_manage(action=create)
```

---

## 7. 数据 Skill (4 case)

### 7.1 经营概览 (dashboard_stats overview)
```
你: 今天生意怎么样
期望: dashboard_stats(action=overview) → 订单数/销售额
```

### 7.2 订单趋势 (dashboard_stats order_trend)
```
你: 最近7天订单趋势
期望: dashboard_stats(action=order_trend, days=7)
```

### 7.3 最近订单 (dashboard_stats recent_orders)
```
你: 最近5条订单
期望: dashboard_stats(action=recent_orders, limit=5)
```

### 7.4 会话监控 (session_manage monitor)
```
你: 客服会话情况
期望: session_manage(action=monitor) → 在线/活跃/排队
```

---

## 8. 边界场景 (5 case)

### 8.1 空结果 + suggestion
```
你: 有没有xyz不存在的
期望: 空结果 → LLM 用 suggestion 引导"换个关键词试试"
```

### 8.2 创建中途取消 (escape hatch)
```
你: 创建一个商品
你: 算了不创建了，帮我查查今天的订单都怎么样
期望: 输入长度>10 触发 escape hatch → 切到 order_query
```

### 8.3 缺信息补全 (validate_input + suggestion)
```
你: 创建订单，只要窗帘
期望: 引导补全姓名电话 → 补全后创建成功
```

### 8.4 模糊意图引导
```
你: 帮我看看
期望: 不猜测，列出选项引导
```

### 8.5 来源标注
```
你: 今天数据怎么样
期望: 数据标注 [工具返回]，不是旧的"不标注"规则
```

---

## 覆盖统计

| Skill | Tool x Action | Case |
|-------|--------------|------|
| order | order_query x3, order_manage x3, order_create, logistics_track | 8 |
| product | product_search x2, detail, product_manage x3, inventory x3, category x3, processing x2 | 14 |
| aftersales | after_sales_manage x4 | 4 |
| customer | customer_manage x4 | 4 |
| staff | employee_manage x3, role_manage x2 | 5 |
| settings | settings_manage x3, notification x2, quick_reply x2 | 7 |
| data | dashboard_stats x3, session_manage | 4 |
| 边界 | escape hatch, validate_input, 空结果, 模糊, 标注 | 5 |
| **总计** | **21 tools, 51 case** | **51** |

---

## 验证清单

□ tool 触发正确（工具名匹配）
□ 写操作有确认（ANNOTATIONS 生效）
□ 破坏性操作二次确认
□ 创建流程跨轮保持（pending skill）
□ 长文本能切话题（escape hatch）
□ 缺信息引导补全（validate_input + suggestion）
□ 空结果友好提示（suggestion）
□ 来源标注 [工具返回]
□ 模糊意图引导而非猜测
□ 不编造数据（全由工具返回）
