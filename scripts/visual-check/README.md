# 视觉验收脚本（本地）

## 为什么有它

issue #7376 复盘：**「最近几次界面都没验收过，样式有问题就直接部署了」**。单测断言的是文本，
看不出「留白对不对齐、金额错不错列、内部码有没有漏上屏」—— 那些只能**看**。

## 怎么用

```bash
cd frontend/admin-web && npm run build
npx next start -p 3124 &            # 生产构建（dev 模式下 AuthProvider 会一直转圈，别用 dev 验）

npm --prefix /tmp i playwright      # 仅首次
npx playwright install chromium     # 仅首次

node scripts/visual-check/reports-page.mjs        # 报表中心（在仓库根跑）
node scripts/visual-check/price-books-page.mjs    # 价格本
node scripts/visual-check/stocktakes-page.mjs     # 盘点单（issue #7373）
node scripts/visual-check/rework-orders-page.mjs   # 返工单（issue #7377）
node scripts/visual-check/after-sales-rework-entry.mjs  # 售后详情「发起返工」入口（issue #7377 段 4）
node scripts/visual-check/customer-detail-tags-empty.mjs # 客户详情「标签」空态 + 去处（issue #7526）
open /tmp/reports-filled.png /tmp/reports-empty.png
```

- 端口可用 `VISUAL_BASE=http://127.0.0.1:3001` 覆盖。
- 脚本 **mock 掉全部 `/api/**`**（不碰真库、不需要登录），所以任何机器都能跑。
- 断言靠**人看**：确认四条展示纪律 —— 空数据写「暂无数据」而不是 ¥0.00、未知项写「未采集 / 未知」、
  合计不完整有提示、金额右对齐不错列。

## 边界

- 只覆盖**报表中心**一页（新增视觉脚本时照它的形状加：`page.route` mock + 两个状态截图）。
- 不进 CI（runner 上没有浏览器二进制，装它会拖慢每条腿）⇒ 它是**本地验收工具**，不是门禁。
