# 官网（企业站）整体重构设计 — 织物质感 + 按真实能力写文案

> 状态：已实施（2026-10-04）｜ issue [#6291](https://github.com/zhaokai-mgzn/migao/issues/6291) ｜ 承接分支 `feat/corporate-site-redesign`
> 范围：`frontend/admin-web/src/app/(corporate)/**`（首页 / 产品与服务 / 关于我们 / 联系我们）+
> `frontend/admin-web/src/components/corporate/**`（导航 / 页脚 / 共用版式 / 能力地图数据）。**不新增路由。**

## 1. 要解决的两个问题

| # | 问题 | 证据 |
|---|---|---|
| 1 | **官网没穿自己的衣服**：企业站通篇 `bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800` 通用蓝色模板 + blur 光斑 + 白色波浪 SVG；而产品全套是「织物质感」token（`frontend/admin-web/tailwind.config.ts`：primary `#48618f` 靛蓝 / accent `#c06a3e` 陶土 / neutral `#faf7f2` 暖亚麻），Logo 是织金「帘成 M」（`frontend/admin-web/src/components/ui/Logo.tsx`） | 旧 `(corporate)/page.tsx` 的 hero 与四个内页页头逐字可查 |
| 2 | **文案与系统真实能力脱节**：只讲「商品 / 订单 / 知识库」三件事，布艺纵深（算料、SKU 矩阵、工序、批次、计件）一个字没提；而真实后台有六个能力域共 22 个菜单项（`frontend/admin-web/src/config/menu.ts`） | 旧 `services/page.tsx` 的 5 张卡 vs `config/menu.ts` |
| 3 | **占位假值**：电话 `400-888-8888`、邮箱 `contact@migao-ai.com`、地址「文一西路000号」、「距地铁5号线创景路站步行10分钟」 | 旧 `contact/page.tsx`、旧 `CorporateFooter.tsx`；合规底稿 `docs/wiki/gb47746-2026-compliance.md` §5 的 GB-05 早已登记 |

## 2. 设计口径

### 2.1 视觉：用产品自己的 token，不再用通用模板

- **底色**：暖亚麻 `neutral-50`，区块在 `white` / `neutral-50` 间交替；卡片 `border-neutral-200 + shadow-card`。
- **主色**：靛蓝 `primary-500/600/700`；**点缀**：陶土 `accent-500/600`；**高光**：Logo 织金 `#d48806`（仅用于 hero 标题渐变、深色区块图标）。
- **Hero 与页脚**：深暖炭 `neutral-900` + 靛蓝/陶土/织金三团柔光 —— 让织金 Logo 与暖中性底形成品牌辨识度。
- **判据**：四页渲染结果的 `innerHTML` **不含** `from-blue-600` / `to-indigo-800`（见 `.github/cases/ui.yml` 的 UI-082）。

### 2.2 文案：只写代码里能看到的形态

- **单一源**：能力域与菜单名来自 `frontend/admin-web/src/components/corporate/capability-map.ts`，它逐字对齐
  `frontend/admin-web/src/config/menu.ts`（六个分组 + 商品管理 / 通知中心两个独立入口）。首页与产品页共用这一份，
  避免「两处各写一份必然漂移」。
- **每位 AI 都带能力边界**（把「不做什么」写进页面，是可信度的一部分）：
  - 米宝：写操作只有改价 / 批量上下架 / 批量库存调整；改价必须带改前价并点确认卡；建单、建品 AI 不做。
  - 小布：不改价、不取消订单、不退款、不承诺优惠折扣、不报库存数量；报价一律说明为估算。
- **行业纵深用行业正名**：裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）。
- **禁用词（判据钉住）**：拼版（全仓无实现）、质检（工序库有行但不在任何工艺路线）、毫秒级、批量操作库存、
  智能工单流转（`inventory_manage` / `after_sales_manage` 已只读化）、自动学习 / 越用越懂 / 越用越精准（GB-05 已清退）。
- **合规红线（`docs/wiki/gb47746-2026-compliance.md` §2）**：只写「遵循 / 对标 GB/T 47746-2026 + 具体能力点」；
  禁「认证 / 通过检测 / 备案 / 无缝接管」；免责小字为强制配套。米宝不在该标准宣称范围内。
- **价格不公示**：`product/pricing-design.md` 明示「方案已定，暂不落地，等 POC 结束后实施」。

### 2.3 有意接受的口径（用户 2026-10-04 裁定，留档）

> 用户裁定原文（选项 B + 补充）：「**选择 B，这个功能未来仍会做回来**」。

⇒ 首页「人机协同 / 自动转人工 / 转人工即同步上下文 / 转人工规则可配置」与 GB/T 47746-2026 区块
**原样保留**。**已知缺口（照实登记）**：`human_handoff` 工具已模型不可达（用户 2026-09-19 裁定
「不应该存在 human_handoff 这种东西，以后全是 AI 来判断」；2026-09-26 裁定「保留现状，不删」；
反回退判据 `tests/unit_ci_workflows/test_human_handoff_retired.py`），C 端当前无人工转接通道。
**重启条件** = 转人工能力回归（回归后本页宣称自动为真）。

## 3. 页面信息架构

| 页面 | 结构 |
|---|---|
| 首页 `(corporate)/page.tsx` | Hero（双 AI 一句话分工 + 4 条可核实事实标签）→ 双 AI 完整分工（含能力边界）→ **一条窗帘订单跑完六步** → **行业纵深四块** → 能力地图（六域 + 两个独立入口）→ 人机协同 + 国标区块 → 平台保障（6 条）→ 适合行业 → 三步开通 → 底部 CTA |
| 产品与服务 `services/page.tsx` | 页头（4 条事实标签）→ 两位 AI 大卡（能力点 + 边界）→ 四个终端 → 六个能力域逐项摊开（22 项）→ 行业纵深四块 → 交付与开通 → CTA |
| 关于我们 `about/page.tsx` | 页头 → 我们是谁（布艺行业真实流程）→ 使命 / 愿景 → **产品原则四条**（答不出就明说 / 价格不由模型定 / 敏感事项不做决定 / 边界写在明处）→ 价值观 → 发展历程 → CTA |
| 联系我们 `contact/page.tsx` | 页头 → 左：四类常见诉求 + 入驻通道；右：在线留言表单（保留校验与成功反馈）→ 常见问题四条 |
| 导航 `CorporateNav.tsx` | 顶部织金细线 + 暖底毛玻璃吸顶 + 四个导航项 + 商家登录 / 商家入驻（移动端抽屉不变） |
| 页脚 `CorporateFooter.tsx` | 品牌与主体 → 快速链接 → 产品能力入口 → 开始使用；底部为合规免责小字 + 版本口径声明 + 版权 |

## 4. 判据与红证

- 用例：`.github/cases/ui.yml` 的 **UI-082**（traces = 5 个 vitest 文件）；国标宣称仍由 **OB-005** 守、
  入驻秒审口径仍由 **OB-004** 守。
- 红证（改前实测，2026-10-04）：把四页 + 导航 + 页脚替换回 `origin/main` 版本后跑本用例 5 个测试文件
  ⇒ **28 failed / 58**；恢复后 **58 passed**。
- 页面级视觉：Playwright 截图 + 多模态读图一轮（`migao-dev-flow` §15.7）。

## 5. 未收口项（照实登记）

1. **留言表单未接后端**：`contact/page.tsx` 的提交仍是前端 `setTimeout` 演示；接真实留言接口属新增后端面，
   另行开单。
2. **联系信息缺真实值**：用户裁定「先只保留在线留言」，电话 / 邮箱 / 地址上线前需补真实值（当前一律不展示）。
3. **ICP 备案号 / 统一社会信用代码缺失**：仓内查不到，故官网不展示；补备案号需用户提供。
4. **`(corporate)/layout.tsx` 的 OG 图仍指 `https://www.migaozn.com/og-image.png`**（未验证该资源是否存在）。
