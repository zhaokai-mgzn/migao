# 官网版式改版（参考校宝 ERP 产品页）视觉证据（issue #9139）

- 采集日期：2026-11-24
- 基线：`origin/main` @ `3890b3ca7`（改版前的现网站）
- 改后：本分支
- 参考：用户提供的 `https://www.xiaobaoonline.com/products/erp.html`（只参考版式节奏，不复制其文案、图片与数据）
- 采集：Playwright（Chromium）`--full-page`；PC `1440×980`，移动 `390×844`

| 文件 | 说明 |
|---|---|
| `before-home-desktop.jpg` / `after-home-desktop.jpg` | 官网首页，PC |
| `before-home-mobile.jpg` / `after-home-mobile.jpg` | 官网首页，移动 |
| `before-services-desktop.jpg` / `after-services-desktop.jpg` | 产品能力页，PC |

## 观测

- 首页全页高度：PC 6501 → 9291 px；移动 12124 → 15736 px（版式改为产品页的多场景分节，长度增加）。
- 产品能力页：4844 → 7683 px。
- 版式变化：浅色产品页头 + 工作台示意 → 八个能力域 → 四个场景分节（左文右图 / 左图右文）→ 优势 → 平台保障六格 → 适用企业 → 交付流程 → 能力边界 / 国标 → CTA。
- 未复制参考站：客户 logo / 客户证言 / 具体经营数字 / 认证类宣称；所有产品界面均标「界面示意」，不写真实订单量 / 销售额。
