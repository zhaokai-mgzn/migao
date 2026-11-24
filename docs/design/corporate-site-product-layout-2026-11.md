# 官网产品页版式改版（参考校宝 ERP，2026-11-24）

> 状态：已实施（2026-11-24，issue #9139）｜ 范围：`frontend/admin-web/src/app/(corporate)/**` + `components/corporate/**`
>
> 用户逐字：「我们生意管家的官网，UI设计保持现有色系风格规范的前提下，把官网的排版布局、内容展示改一版，你参考这个网站改一版。https://www.xiaobaoonline.com/products/erp.html」

## 1. 借什么 / 不借什么

参考站是典型的教育 SaaS 产品长页：浅色产品页头 + 工作台截图 → 能力域 → 多个「场景 + 标签 + 左文右图」分节 → 增值服务 / 行业 / 服务支持 / 客户证言 → 深色 CTA。

| 借用（版式节奏） | 不借（内容与视觉资产） |
|---|---|
| 浅色产品页头 + 产品界面示意 | 参考站的蓝色 / 紫色主色与玻璃拟态 |
| 居中的分节标题 + 标签 pills | 客户 logo、客户证言、具体经营数字 |
| 四个场景分节，左文右图 / 左图右文交替 | 参考站的截图、图标与文案 |
| 六格服务支持 / 三格行业 / 三步交付 | 「认证 / 第一 / 领先」类不可核实宣称 |
| 深色收口 CTA + 页脚 | 侧边悬浮客服条（本仓官网不挂第三方客服） |

## 2. 页面结构

| 页面 | 结构 |
|---|---|
| 首页 | 浅色 Hero（主标 + 双 AI 一句话 + 六能力标签 + 工作台示意）→ 八个能力域（只到域级）→ 四个场景分节（顾客经营 / 经营决策 / 生产与交付 / 库存与对账）→ 为什么选择（四卡）→ 平台保障（六格）→ 适用企业（三卡）→ 交付流程（三步）→ 能力边界 + 国标 → 深色 CTA |
| 产品能力 | 浅色 Hero → 四个场景分节 → 八个能力域 → 行业纵深四块 → 四个终端 → 交付与开通（三卡）→ CTA |
| 关于 / 联系 | 保持原有版式与内容，仅随全站导航 / 页脚 / 色板一致 |

## 3. 组件与真值

- `components/corporate/Showcase.tsx`：`SectionIntro`（居中分节标题）、`ShowcaseBlock`（标签 + 左文右图 / 反向）、`SupportGrid`（六格）。
- `components/corporate/FeatureTabs.tsx`：客户端标签切换；只切换**一句说明**，不切换产品示意（示意不依赖真实数据）。
- `components/corporate/ProductVisuals.tsx`：工作台 / 顾客对话 / 经营报表 / 生产看板 / 库存台账五张**纯 CSS/SVG 示意**；每张都带「界面示意」，不写具体订单量 / 销售额 / 客户名。
- 能力域名称与摘要真值仍在 `components/corporate/capability-map.ts`；官网只取 `name` + `summary`，不展开内部菜单。
- 颜色 / 字号 / 圆角 / 阴影仍走 `tailwind.config.ts` + `docs/design/design-baseline.md`；没有新增色值。
- 导航新增「预约演示」主 CTA（`/contact`），内测期仍不露出商家入驻（`SELF_SERVICE_ONBOARDING_OPEN = false`）。

## 4. 口径

- **不复制参考站内容**：客户 logo / 证言 / 具体经营数字 / 认证宣称一律不借。
- **示意不是读数**：产品界面统一标「界面示意」；不写「今日 12 单」「销售额 ¥xx」这类真实经营数字。
- **不泄露内部结构**：不写四层架构、业务工具层、多租户实现、AI 配置方式；能力域只到域级。
- **合规不变**：GB/T 47746-2026 标准号、四条机制与免责小字保留；「不构成认证 / 检测 / 备案结论」不改。
- **文案口吻不变**：能力陈述型书面语；不用「你」，官网统一「您」；不用「一套 / 一次 / 一个 / 一条」等量化排比。

## 5. 判据与证据

- `frontend/admin-web/tests/unit/pages/corporate-home.test.tsx`：Hero / 六标签 / 工作台示意 / 八个能力域 / 四个场景分节 / 标签切换 / 六格保障 / 三类行业 / 三步交付 / 国标 / 口吻与量词。
- `frontend/admin-web/tests/unit/pages/services.test.tsx`：浅色页头 / 四个场景 / 八个能力域 / 行业纵深 / 四端 / 交付 / CTA。
- `frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts`：新 pill 全带 `whitespace-nowrap`；旧首页深色 pill 死条目已删。
- `frontend/admin-web/tests/unit/pages/corporate-visual-copy-guards.test.ts`：色值单一源 / 中文小标签 / 敬语「您」/ 无厂商名与内部标识。
- 视觉证据：`docs/design/corporate-site-layout-2026-11-evidence/`（改前 / 改后，同页面 / 视口 / 主题）。
