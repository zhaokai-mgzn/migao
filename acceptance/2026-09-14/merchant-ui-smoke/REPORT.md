# 商家后端（admin-web）全面功能冒烟报告 — 2026-09-14

- **任务**：issue #3660 — 今日约 50 PR 合入 main 后，对商家后端全部页面做集成层功能冒烟（真浏览器 + 真后端 + 商家 persona）
- **执行人**：DSH 验证 worker（session 80fdf306 子代理）
- **时间**：2026-09-14 16:00 ~ 17:30
- **栈**：admin-api(:8090, SMS bypass) + admin-web(:3001, API→:8090) + ai-agent(:8001, DEBUG 测试模式) + 云 dev DB/Redis（公网 IP 已在 RDS dev_local 白名单）
- **账号**：13800138000（赵凯 / user_admin_001 / admin / 词元通达）+ 万能码 123456（SMS bypass）
- **方法**：Playwright（chromium）逐页走查 31 旅程；DOM 断言（§15.6 选择器优先级）+ 写操作结果可见（§15.1）+ 每页截图 + console/page error 全程监听；关键截图经 GLM-5.3-Flash 多模态视觉复核（§15.5）
- **可复跑**：`scripts/ui_smoke_merchant.sh`（一键起栈→31 旅程→停栈；spec 见 `scripts/ui-smoke-merchant/spec.mjs`）

## 结论

**31/31 旅程全部通过（pass）**，console/page error 全程 0 残留（2 处预期豁免见 §4）。

冒烟发现并修复 **3 个前端 UI 问题**（本 PR 附带，均经修复后重走验证）：
1. **订单列表 React key 警告**（OrderTable 采购明细 `key={item.id}`，而列表接口不下发 item.id → 恒 undefined → console error）— 已修复
2. **客户列表标签渲染空 chip + React key 警告**（列表接口 tags 为字符串 ID 数组，前端按对象取值）— 已修复
3. **发货页状态守卫缺 `producing`**（含不存在的 `processing`）→ 加工单流转后订单进入「生产中」即被发货页拦截「当前订单状态不允许发货」— 已修复

归因待派 **2 个后端/契约问题**（见 §5），另有 P2 观察项若干（不阻塞）。

## 旅程明细（31/31 ✅）

| # | 旅程 | 结果 | 证据/要点 |
|---|------|------|-----------|
| 01 | 登录（SMS 万能码 + 会话保持） | ✅ | 登录→/dashboard；刷新后会话保持；截图 `01-login.png` |
| 02 | 经营看板 | ✅ | 统计卡片渲染、数字非空（`smoke-run5.log`） |
| 03 | 每日经营简报 | ✅ | 简报页渲染 + 生成按钮可用（V44 daily_briefings） |
| 04 | /agent-workspace 重定向 | ✅ | 自动跳 /agent-workspace/human-sessions |
| 05 | 在线接待 | ✅ | 会话列表渲染（ai-agent 已起，真实数据） |
| 06 | 智能体会话历史 | ✅ | 列表渲染 0 error |
| 07 | 对话页 | ✅ | 输入框可用、会话渲染 |
| 08 | 商品列表 | ✅ | 485 商品渲染、分页/筛选可用 |
| 09 | 新建商品（SKU 矩阵） | ✅ | **门幅值/显示分离验证（#3641）**：下拉选项 `2.8|2.8米`（value=canonical），选中后表单值='2.8'，无第二种写法；真实建品（草稿+分类）→ 列表可见 |
| 10 | 商品详情 | ✅ | 列表行「查看」→ 详情渲染 |
| 11 | 编辑商品（门幅回显） | ✅ | **门幅口径必查（#3641）**：既有商品（doorWidth='2.8米'）回显下拉 value='2.8'、显示 '2.8米'，无空白、无第二种写法；截图 `11-product-edit-doorwidth.png` |
| 12 | 加工项管理 | ✅ | **新建（pricingMethod=per_meter + unitPrice 15.5）→ 列表可见 → 编辑（改名部分更新）→ 删除**（#3555/#3591 unitPrice 语义走查通过） |
| 13 | 商品分类 | ✅ | 新建→可见→行内删除 |
| 14 | 订单列表 | ✅ | 分页「下一页」可用（React key 警告已随修复消除） |
| 15 | 新建订单（UI 旅程） | ✅ | 选商品弹窗搜索「遮光窗帘」→ 提交 → 订单创建成功 |
| 16 | 订单详情 + 加工单 | ✅ | **加工单生成确认门禁 UI 侧验证**：确认收款（闸门弹窗）→「生成加工单」→ 加工单块出现（JG-20260914-9984 已生成）→ 发加工→开始加工→加工完成 全流程落库（DB 实证 status=completed）；`requires_confirmation=True`（ai-agent `processing_order_generate.py:40`）静态证据 |
| 17 | 发货页 | ✅ | **修复验证**：producing 订单可进入发货表单（修复前被守卫拦截） |
| 18 | 售后工单列表 | ✅ | 52 工单渲染 |
| 19 | 售后详情（关闭原因） | ✅ | **#3541 语义**：pending→接受处理→关闭工单（填写原因）→ 刷新后关闭原因回显（落库实证：截图 19-after-sales-detail.png 显示「已关闭」+ 原因） |
| 20 | 客户列表 | ✅ | wechatNickname 显示正常、无空名/报错（#3562；标签修复后无空 chip） |
| 21 | 客户详情 | ✅ | 详情渲染、编辑入口可用 |
| 22 | 财务对账 | ✅ | 渲染正常 |
| 23 | 员工管理 | ✅ | **新建（name/phone/岗位/权限）→ 列表可见（phone/roleIds 真实显示 #3561）→ 编辑改手机号 → 落库验证 → 删除**；HR-008 语义走查通过 |
| 24 | 岗位权限 | ✅ | 岗位列表 + 权限编辑弹窗可开（#2969/#3561） |
| 25 | 企业基础信息 | ✅ | 基本信息保存 + 修改密码表单 + 通知设置 Tab 可用（#3583） |
| 26 | 通知中心 | ✅ | 列表渲染 + 已读操作 |
| 27 | 官网首页 | ✅ | 渲染正常 |
| 28 | 官网 About | ✅ | 渲染正常 |
| 29 | 官网 Contact | ✅ | 渲染正常 |
| 30 | 官网 Services | ✅ | 渲染正常 |
| 31 | 注册页 | ✅ | 渲染 + 表单控件存在 |

## 发现并已修复的 UI 问题（本 PR）

| # | 问题 | 证据 | 修复 | 验证 |
|---|------|------|------|------|
| F1 | 订单列表 `OrderTable` 采购明细 `key={item.id}`，但**列表接口不下发 item.id**（#2916 已知）→ React key 警告（console error） | 冒烟 run1 `14-orders-list`：`Warning: Each child in a list should have a unique "key" prop... OrderTable`；API 实证 `order.items[].id = None` | `OrderTable.tsx` key 兜底：`item.id ?? ${order.id}-item-${idx}` | run5 14-orders-list ✅ 0 error |
| F2 | 客户列表 tags 列按对象取 `tag.id/tag.name`，但**列表接口返回字符串 ID 数组**（详情接口才是对象）→ key 警告 + 空 chip 显示 | 冒烟 run1 `20-customers-list`：`Warning... Table`；API 实证 `tags=["821556a8..."]` | `customers/page.tsx` getTags 容忍 string，渲染层用页内 tag 字典解析为对象 | run5 20/21 ✅ 0 error、标签 chip 正常 |
| F3 | **发货页状态守卫 `['pending_shipment','confirmed','processing']` 不含 `producing`**（且 `processing` 是不存在的状态）→ 加工单流转后订单进入 producing，发货页报「当前订单状态不允许发货」 | 冒烟 run2 `17-order-ship`：订单已是 producing（加工单 completed）但发货页无表单；`ShipOrder.tsx:142` | 守卫改为 `['pending_shipment','confirmed','producing']` | run5 17-order-ship ✅ 表单渲染 |

## 归因待派的后端/契约问题（不在本包修复）

| # | 问题 | 证据 | 归因 | 建议 |
|---|------|------|------|------|
| B1 | **商品草稿无分类保存 → 500**（`products_category_id_fkey` 违例）。前端草稿校验不要求分类（`!isDraft` 才校验 categoryId），后端 category_id 非空 FK → 插入 500 | 冒烟 run3 `09-products-new`：`保存商品失败 (draft): ... status 500`；admin-api 日志 `insert or update on table "products" violates foreign key constraint "products_category_id_fkey"` | **后端契约缺口**（ProductController/ProductService：草稿态应允许空分类或默认分类；或前端草稿也要求选分类——需产品裁定） | 二选一：① ProductCreateRequest 草稿态 categoryId 可空（表列改 nullable 或落默认分类）；② 前端草稿必填分类。冒烟走查用「选分类后存草稿」的正常路径通过 |
| B2 | **客户列表 tags 与详情 tags 形态不一致**：列表返回字符串 ID 数组（`profile.tags` 原样），详情返回标签对象数组。前端类型契约声明 `CustomerTag[]`（对象） | 冒烟 API 实证：list `tags=["821556a87113296f8a8c9579c2064d58"]` vs detail `tags=[{id,name,color,...}]`；`CustomerService.getCustomerDetail` 解析、list 原样返回 | **后端契约不一致**（CustomerService 列表序列化应同详情解析；本包已在**前端**做容忍修复，根因仍建议后端统一） | CustomerController.getCustomers 的 tags 改为按 id 解析为对象（与详情同口径） |

## P2 观察项（不阻塞，记录备查）

- **新建订单页面包屑显示「订单列表」**：`/orders/new` 页面标题「新增订单」，面包屑为「订单管理 / 订单列表」（父级语义），GLM 视觉复核标注「疑为父级面包屑设计，不构成缺陷」——如需精确可改面包屑为「订单管理 / 新增订单」。
- **加工单未生成时** `GET /api/admin/processing-orders/{orderId}` 返回 404（组件 catch→notFound→展示生成按钮），浏览器 console 出现 404 资源错误（预期探测行为，代码显式处理；已按预期豁免并记 note，见 run5 `16-order` 注）。
- **settings 页修改密码**：Tab 存在、密码表单渲染（#3583 闸门）；走查未实际提交改密（避免改动管理员凭据），仅验证表单可用。
- ai-agent 本地以 `DEBUG=true` 测试模式运行（本地冒烟专用，JWT 签名不校验）——**生产环境严禁**，仅本机临时栈。

## 视觉复核（§15.5，GLM-5.3-Flash 多模态）

10 张关键截图（dashboard/products-new/商品编辑门幅/加工项/订单列表/订单详情加工单块/售后详情/员工/新建订单/设置）逐项判定：**全部正常**——无白屏、无破版、无重叠遮挡、无分页被 FAB 压住；1 张（09-products-new）视觉模型未收到图像内容，退化为程序化像素统计（68.9% 近白典型值、无全宽空白带），结论正常（如实标注）。订单详情截图因页面下滚截断头部（截图时机问题，非缺陷）。详见 workflow 输出（10/10 PASS）。

## 证据位置

- 截图：`acceptance/2026-09-14/merchant-ui-smoke/screenshots/*.png`（31 张）
- 汇总：`acceptance/2026-09-14/merchant-ui-smoke/smoke-summary.md` / `smoke-results.json`
- 完整运行日志：`acceptance/2026-09-14/merchant-ui-smoke/smoke-run5.log`
- 可复跑：`scripts/ui_smoke_merchant.sh` + `scripts/ui-smoke-merchant/spec.mjs`

## 数据卫生

冒烟产生的测试数据（冒烟* 商品/订单/加工单/员工/分类/加工项）已全部从云 dev 库清理；SMS 限流键已清除；本地服务已停。**发现并复现问题的 DB 证据**：加工单 JG-20260914-9984（completed 全流程落库实证，清理前截图留证）。
