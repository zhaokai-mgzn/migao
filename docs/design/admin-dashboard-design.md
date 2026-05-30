# 企业管理后台产品设计

> 版本：v8.0  
> 日期：2026-04-12  
> 定位：单租户商家后台（多租户技术架构，企业管理员视角）  
> 技术栈：Next.js SSR 部署到 SAE

---

## 一、产品定位与架构

### 1.1 产品定位

企业管理后台是 AI 客服系统的**运营管理中枢**，提供：
- 混合数据看板（业务指标 + 客服指标）
- AI 客服配置（欢迎语、营业时间、转人工规则、快捷回复）
- 客服团队管理（员工、会话分配、服务质量）
- 业务管理（商品、订单、售后工单）
- RBAC 权限（按角色控制菜单和数据）

### 1.2 多租户设计原则

- 商家后台不出现"租户管理"菜单
- 所有 API 的 `tenant_id` 从 JWT Claims 提取，禁止客户端传递
- 数据库所有业务表含 `tenant_id`，PostgreSQL RLS 强制隔离

### 1.3 角色与权限矩阵

| 角色 | 代码 | 菜单权限 | 数据权限 |
|------|------|---------|---------|
| 企业管理员 | admin | 全部菜单 | 本租户全部数据 |
| 运营经理 | operation_manager | 看板、AI配置、客服团队、业务管理 | 本租户全部数据 |
| 客服主管 | support_supervisor | 看板、客服团队、快捷回复 | 本租户客服数据 |
| 客服员工 | support_agent | 看板(仅客服指标)、我的会话、快捷回复 | 仅本人会话 |
| 商品管理员 | product_manager | 商品管理、订单管理(只读) | 本租户商品/订单 |

**RBAC 实现**：前端按角色渲染菜单 → 后端校验 JWT `role` → 数据层 RLS 策略兜底

---

## 二、导航结构

### 2.1 菜单树

| 一级菜单 | 二级菜单 | 可见角色 |
|---------|---------|---------|
| 📊 数据看板 | 混合Dashboard / 客服看板 / 业务看板 | 全部(内容按角色过滤) |
| 🤖 AI客服配置 | 基础配置 / 转人工规则 / 快捷回复 / 推荐策略 | admin, operation_manager |
| 👥 客服团队 | 员工管理 / 会话监控 / 服务质量 | admin, operation_manager, support_supervisor |
| 📦 商品管理 | 商品列表 / 分类 / 加工项 / 库存 | admin, operation_manager, product_manager |
| 📚 知识库管理 | 文档管理 / 检索测试 / 同步管理 | admin, operation_manager |
| 📋 订单管理 | 订单列表 / 订单详情 | admin, operation_manager, product_manager |
| 👤 客户管理 | 列表 / 详情 / 标签 / 分群 / 生命周期 / 跟进 / 沟通 / 商机 | admin, operation_manager, support_supervisor |
| 🔄 售后工单 | 工单列表 / 工单详情 | admin, operation_manager, support_supervisor |
| ⚙️ 系统设置 | 租户配置 / 通知 / 员工角色 / 日志 | admin |

---

## 三、数据看板

### 3.1 混合 Dashboard（默认首页）

**指标区**：

| 业务指标 | 客服指标 |
|---------|---------|
| 今日订单(环比) | AI 会话量(环比) |
| 今日营收(环比) | 转人工率(环比) |
| 活跃客户(环比) | 平均响应时长(环比) |
| 转化率(环比) | 满意度(环比) |

**图表区**：
- 订单 & 会话量趋势（双轴折线图）
- 客服渠道占比（环形图）
- 常见问题 TOP10（横向柱状图）
- 转人工原因分布（饼图）

**AI 智能洞察区**：待处理事项 + 优化建议 + 自然语言查询入口

**实时客服状态**：在线客服列表（头像+当前会话数/上限）+ 排队会话数 + 平均等待时长

### 3.2 客服数据看板

核心指标：总会话量、AI 解决率、转人工数、平均响应、满意度  
图表：会话量趋势(按小时/天/周)、转人工率趋势  
员工绩效表：处理会话、平均响应、满意度、解决率、排名  
问题分析：AI 无法回答 TOP10、负向反馈关键词云

### 3.3 业务数据看板

核心指标：订单量、营收、客单价、退款率、复购率  
图表：营收趋势(柱状+折线)、热销商品 TOP10、新客户增长、客户来源分布

---

## 四、AI 客服配置

### 4.1 基础配置

| 配置项 | 说明 |
|-------|------|
| 欢迎语模板 | 支持变量 `{company_name}` `{agent_name}` `{business_hours}` |
| 快捷按钮 | JSON数组，最多6个，含 id/label/prompt |
| 营业时间 | 工作日/周末分别设置，时区选择 |
| 非营业时间策略 | AI继续响应 / 收集留言 / 转人工 |
| 推荐策略 | 按销量/随机/分类匹配/不推荐，可配数量和触发时机 |

### 4.2 转人工规则

| 配置项 | 说明 |
|-------|------|
| 关键词触发 | 可自定义关键词列表 |
| 情绪触发 | 检测负面情绪自动转人工 |
| AI无法解决触发 | 连续N次无法理解时触发 |
| 分配方式 | 自动轮询 / 固定分配 / 抢单模式 |
| 最大并发数 | 每个客服最大同时服务会话数 |
| 无在线客服策略 | 留言等待 / AI继续响应 |
| 转接话术 | 自定义提示语，可启用会话摘要 |

### 4.3 快捷回复模板

列表管理：分类筛选、搜索、编辑  
模板字段：分类、标题、内容、使用次数、可见范围(全团队/仅自己)

---

## 五、客服团队管理

### 5.1 员工管理

统计卡片：总员工数、当前在线、忙碌中、离线  
员工表格：姓名、角色、状态(🟢🟡🔴)、当前会话/上限、今日处理、满意度  
邀请流程：填写姓名/手机/角色/最大并发 → 生成邀请码 → 员工微信扫码绑定

### 5.2 会话监控

统计：进行中、排队中、已结束、平均等待  
实时会话列表：会话ID、客户、客服、状态、等待时长、消息数、操作(查看/分配)

### 5.3 服务质量统计

总体指标：总会话、平均响应、平均解决时长、满意度、解决率  
员工对比表：按响应/解决/满意度排名  
满意度分布图 + 客户评价详情列表

---

## 六、业务管理

### 6.1 商品管理

商品列表：名称、分类、价格、库存、状态(上架/下架/缺货)、知识库同步状态  
支持：新建/编辑商品、批量操作、导入

### 6.1.1 加工项管理（布艺行业专用）

**业务背景**：窗帘布料最终价格 = 布料费 + 加工费。AI 客服需要自动计算总价。

加工项字段：

| 字段 | 说明 |
|------|------|
| 名称 | 如打孔加工、折边加工 |
| 分类 | 窗帘加工/窗帘配件/纱窗加工/卷帘加工 |
| 适用商品分类 | 多选 |
| 计价方式 | 按个/按米/按平米/按固定价 |
| 单价 | 如 ¥5.00/个 |
| 最少/最多数量 | 限制范围 |
| AI展示 | 是否允许AI推荐 |

组合规则：必选其一、互斥、可叠加、可选叠加  
价格计算器预览：选商品+数量+加工项 → 实时计算总价

### 6.2 商品分类

表格：分类名称、商品数、关联加工分类、状态、排序

### 6.3 知识库管理

#### 文档管理
- 多租户隔离：DashVector 用 `tenant_{id}` 命名 collection，DB 用 RLS
- 统计卡片：文档总数、已向量化、向量化中、失败
- 文档表：标题、类型(产品说明/FAQ/工艺指南等)、分类、关联商品、分块数、向量化状态
- 上传支持：手动录入/文件上传(PDF/Word/MD)，可选自动向量化

#### 检索测试
输入问题 → 显示命中分块(匹配分数、来源、检索方式) → AI回答预览

#### 同步管理
- 同步模式：增量/全量
- 同步范围：全部/指定分类/指定商品
- 自动生成：产品说明、加工说明(可选)
- 同步历史记录表

### 6.4 订单管理

筛选：状态、时间、关键词  
列表：订单号、客户、金额、状态、下单时间

### 6.5 售后工单

**售后类型**：退款、退货退款、换货、补发、维修

**工单状态流转**：
```
待处理 → 处理中 → 待客户确认 → 已完成
              ↘ 客户拒绝 → 处理中
待处理 → 已关闭（取消/超时/协商不一致）
```

工单列表：统计卡片(全部/待处理/处理中/待确认/已完成) + 工单表格  
工单详情：左侧(工单信息+关联订单+客户信息+退款信息) / 右侧(处理时间线+操作区)

**处理流程**：
- 退款：客户申请 → 自动分配 → 客服审核 → 客户确认 → 退款执行
- 换货：申请 → 审核 → 确认方案 → 客户寄回 → 仓库收货 → 新品发货
- 补发：申请 → 审核凭证 → 确认补发 → 仓库出库 → 发货

---

## 七、系统设置

### 7.1 租户配置（admin 独占）

| 配置区域 | 内容 |
|---------|------|
| 基本信息 | 名称、Logo、行业、联系人、电话、地址 |
| 微信小程序 | AppID、AppSecret、消息Token、EncodingAESKey、加密方式、域名 |
| 短信服务 | 服务商、AK/SK、签名、模板列表(用途/ID/状态) |
| 支付配置 | 商户号、API密钥、证书、退款回调 |

### 7.2 通知设置

通知渠道：微信模板消息、短信、邮件、站内消息  
通知规则表：

| 通知类型 | 接收人 | 渠道 | 默认状态 |
|---------|--------|------|---------|
| 新工单分配 | 处理客服 | 站内+微信 | 启用 |
| 工单状态变更 | 客户 | 短信+微信 | 启用 |
| 退款成功 | 客户 | 微信 | 启用 |
| 发货通知 | 客户 | 微信+短信 | 启用 |
| 工单超时预警 | 客服主管 | 站内+短信 | 启用 |
| 库存预警 | 运营经理 | 站内 | 启用 |
| AI客服异常 | 运营经理 | 站内+短信 | 启用 |

模板支持变量：`{customer_name}` `{ticket_no}` `{new_status}` `{handler_name}` `{company_name}` 等

### 7.3 员工与角色管理

角色定义表 + 员工列表(姓名/手机/角色/状态/最后登录)

### 7.4 操作日志

筛选：操作类型、员工、时间  
列表：时间、操作人、类型、内容、IP

---

## 八、客户管理（CRM）

### 8.1 客户列表

筛选：昵称/手机/ID、等级、状态、来源渠道、消费区间、注册时间、标签  
统计卡片：客户总数、本月新增、活跃客户、高价值客户、流失预警  
列表字段：昵称(含活跃状态点)、账号、订单数、累计消费、最后成交、标签  
批量操作：添加标签、发送消息、导出、标记流失

### 8.2 客户详情

**左侧档案**：基本信息、客户标签(+添加)、客服备注、快捷操作(发消息/改标签/加备注/建工单/导出)

**右侧 Tab**：
- **概览**：RFM 评分(R/F/M 各维度)、综合评分、价值分层、关键指标、最近订单、互动动态
- **订单**：历史订单列表
- **互动**：时间线(AI会话/人工会话/订单支付等事件，含详情)
- **价值**：RFM 模型分析表、消费趋势柱状图、商品偏好(分类/加工方式/客单价)、生命周期预测

### 8.3 标签管理

**自动标签**（系统根据行为打标）：

| 标签 | 规则 | 示例 |
|------|------|------|
| VIP客户 | 累计消费 ≥ ¥10,000 | |
| 高价值 | RFM评分 ≥ 80 | |
| 活跃 | 近30天有下单 | |
| 沉默 | 30-90天未下单 | |
| 流失预警 | 90-180天未下单 | |
| 已流失 | 180+天未下单 | |
| 复购率高 | 复购率 ≥ 50% | |
| 批发商 | 月均订单 ≥ 10 | |

**手动标签**：客服手动添加，如窗帘偏好、价格敏感、品质要求高等  
标签配置：名称、颜色、打标规则/条件、频率(每日/实时/手动)、适用范围

### 8.4 客户分群

**价值分层**（RFM模型）：高价值 / 成长 / 新客 / 沉默 / 流失预警 / 已流失  
**行为分群**：高频购买 / 大额消费 / 促销敏感 / 单品类偏好 / 多品类购买  
**自定义规则**：组合条件(消费金额+时间+分类+频率)，支持每日/每周/手动更新

### 8.5 客户生命周期

漏斗阶段：潜在客户 → 新客户 → 成长客户 → 成熟客户 → 沉默客户 → 流失预警 → 已流失  
每阶段字段：客户数、占比、转化率、平均停留时长

各阶段策略配置：触发条件、自动动作、触达渠道、执行频率、启用状态

### 8.6 跟进任务

统计：待处理、今日到期、已逾期、已完成、完成率  
任务列表：优先级(紧急/高/普通/低)、标题、关联客户、负责人、截止日期、状态  
新建任务：类型(回访/流失跟进/投诉跟进/订单跟进/VIP维护/商机跟进)、关联客户、描述、优先级、负责人、时间、提醒设置  
任务详情：基本信息+描述+关联信息 / 执行记录时间线+快捷操作

### 8.7 沟通记录

统计：今日沟通、AI会话、人工会话、电话外呼、满意度  
列表：时间、客户、渠道(AI/人工/电话/微信/短信)、客服、主题、结果

### 8.8 商机管理（B2B）

统计：商机总数、预计总额、本月成交、成交率、平均周期  
阶段漏斗：需求确认 → 方案报价 → 商务谈判 → 合同签署 → 已成交  
商机列表：名称、客户、阶段、预计金额、负责人、预计成交时间  
新建商机：名称、客户、来源、金额、阶段、时间、负责人、描述、关联商品、赢单概率

### 8.9 数据导入导出

导入：下载模板 → 上传Excel/CSV → 字段映射 → 预览确认(有效/重复/错误统计) → 导入策略(新增跳过/新增更新/仅更新)  
导出：范围(筛选结果/全部/已选择)、字段勾选、格式(xlsx/csv)

---

## 九、响应式设计

| 端 | 布局 |
|----|------|
| 桌面(≥1280px) | 顶部栏 + 左侧导航 + 主内容区 |
| 平板(768-1279px) | 导航收起为图标、表格改卡片、图表自适应 |
| 手机(<768px) | 仅提供看板核心指标(只读)、会话监控(只读)、紧急通知 |

---

## 十、技术实现

### 10.1 前端目录结构

```
web/admin/src/
├── pages/
│   ├── index.tsx                    # 混合Dashboard
│   ├── dashboard/                   # 客服看板、业务看板
│   ├── ai-config/                   # 基础配置、转人工、快捷回复
│   ├── team/                        # 员工、会话监控、质量
│   ├── products/                    # 列表、分类、加工项
│   ├── orders/                      # 订单列表
│   ├── after-sales/                 # 工单列表、详情
│   ├── customers/                   # 列表、详情、标签、分群、生命周期、跟进、沟通、商机
│   ├── knowledge/                   # 文档、检索测试、同步
│   └── settings/                    # 租户、通知、角色、日志
├── components/
│   ├── Layout.tsx / Sidebar.tsx     # 布局(角色动态渲染)
│   ├── Dashboard/                   # MetricCard, TrendChart, AIInsightPanel, AgentStatus
│   ├── AIConfig/                    # GreetingEditor, BusinessHours, HandoffRules, QuickReplyManager
│   ├── Team/                        # EmployeeTable, InviteModal, SessionMonitor
│   └── CRM/                         # CustomerTable, CustomerProfile, RFMAnalysis, TagManager, SegmentBuilder
├── hooks/
│   ├── useRole.ts                   # 角色权限 hook
│   └── useWebSocket.ts             # WebSocket 实时数据
└── middleware/
    └── auth.ts                      # SSR 认证中间件
```

### 10.2 RBAC 前端实现

```typescript
const ROLE_PERMISSIONS = {
  admin: ['*'],
  operation_manager: ['dashboard:view', 'ai-config:edit', 'team:view', 'products:edit', 'orders:view', 'after-sales:view', 'knowledge:view', 'customers:view', 'customers:edit', 'tags:manage'],
  support_supervisor: ['dashboard:view', 'team:view', 'team:quality', 'quick-replies:edit', 'after-sales:view', 'customers:view', 'customers:edit-notes'],
  support_agent: ['dashboard:cs-view', 'my-sessions:view', 'quick-replies:view'],
  product_manager: ['products:edit', 'orders:view']
};
```

### 10.3 SSR 认证中间件

从 Cookie 提取 JWT → 验证 → 注入 x-user-id / x-tenant-id / x-user-role 到请求头

### 10.4 WebSocket 实时数据

连接 `wss://api.migaozn.com/ws/agent?token=<JWT>`，监听事件：
- `session_update` → 更新会话状态
- `agent_status_change` → 更新客服状态
- `new_session` → 新增会话

---

## 十一、API 接口对应

| 页面 | API | 说明 |
|------|-----|------|
| 混合Dashboard | GET /api/admin/stats/dashboard | 混合指标 |
| 客服看板 | GET /api/admin/stats/customer-service | 客服专项 |
| 业务看板 | GET /api/admin/stats/business | 业务专项 |
| AI配置 | GET/PUT /api/admin/tenant/ai-config | AI配置 |
| 转人工规则 | GET/PUT /api/admin/tenant/ai-config/handoff | 转人工 |
| 快捷回复 | GET /api/agent/quick-replies | 模板列表 |
| 员工管理 | GET /api/admin/agents | 员工列表 |
| 邀请员工 | POST /api/auth/agent/invite | 生成邀请码 |
| 会话监控 | GET /api/admin/sessions?status=active | 实时会话 |
| 服务质量 | GET /api/admin/sessions/stats | 统计 |
| 商品列表 | GET /api/admin/products | 商品 |
| 加工项 | GET/POST /api/admin/processing-items | 加工项CRUD |
| 加工规则 | GET/POST /api/admin/processing-rules | 组合规则 |
| 价格计算 | POST /api/admin/processing-items/calculate | 计算 |
| 知识库文档 | GET/POST /api/admin/knowledge/documents | 文档CRUD |
| 向量化 | POST /api/admin/knowledge/documents/{id}/embed | 触发 |
| 检索测试 | POST /api/admin/knowledge/test-search | 混合检索 |
| 批量同步 | POST /api/admin/knowledge/batch-sync | 知识同步 |
| 客户列表 | GET /api/admin/customers | 客户 |
| 客户详情 | GET /api/admin/customers/{id} | 完整档案 |
| 客户价值 | GET /api/admin/customers/{id}/value-analysis | RFM |
| 标签管理 | GET/POST/PUT/DELETE /api/admin/tags | 标签CRUD |
| 客户分群 | GET/POST/PUT /api/admin/customer-segments | 分群 |
| 操作日志 | GET /api/admin/audit-logs | 日志 |

---

## 十二、页面路由清单

| 路由 | 页面 | 角色限制 |
|------|------|---------|
| `/` | 混合Dashboard | 全部 |
| `/dashboard/customer-service` | 客服看板 | admin/manager/supervisor |
| `/dashboard/business` | 业务看板 | admin/manager |
| `/ai-config/basic` | AI基础配置 | admin/manager |
| `/ai-config/handoff-rules` | 转人工规则 | admin/manager |
| `/ai-config/quick-replies` | 快捷回复 | admin/manager/supervisor |
| `/team/employees` | 员工管理 | admin/manager/supervisor |
| `/team/sessions` | 会话监控 | admin/manager/supervisor |
| `/team/quality` | 服务质量 | admin/manager/supervisor |
| `/products` | 商品列表 | admin/manager/product_manager |
| `/products/processing-items` | 加工项 | admin/manager/product_manager |
| `/products/categories` | 商品分类 | admin/manager/product_manager |
| `/knowledge/documents` | 文档管理 | admin/manager |
| `/knowledge/test-search` | 检索测试 | admin/manager |
| `/knowledge/sync` | 同步管理 | admin/manager |
| `/orders` | 订单管理 | admin/manager/product_manager |
| `/after-sales` | 售后工单 | admin/manager/supervisor |
| `/customers` | 客户列表 | admin/manager/supervisor |
| `/customers/:id` | 客户详情 | admin/manager/supervisor |
| `/customers/tags` | 标签管理 | admin/manager |
| `/customers/segments` | 客户分群 | admin/manager |
| `/customers/lifecycle` | 生命周期 | admin/manager |
| `/customers/tasks` | 跟进任务 | admin/manager/supervisor |
| `/customers/communications` | 沟通记录 | admin/manager/supervisor |
| `/customers/opportunities` | 商机管理 | admin/manager |
| `/settings/tenant` | 租户配置 | admin |
| `/settings/notifications` | 通知设置 | admin |
| `/settings/roles` | 角色管理 | admin |
| `/settings/logs` | 操作日志 | admin |
