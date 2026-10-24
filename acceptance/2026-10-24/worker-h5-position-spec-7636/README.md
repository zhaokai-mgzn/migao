# 工人报工屏「本部位生产信息」收口（issue #7636）· 取证

用户 2026-10-24 逐字四条 → 本目录只放**读图证据**，判据在测试里（不在这里重复文案）。

## 怎么复现这张图（零真库、零登录）

```bash
cd frontend/worker-h5
# 1) 用与判据同一份夹具渲染真实 `renderPage` 产物（HTML 由 src/render.mjs 生成，CSS 用 src/styles.css）
node -e "…（见 PR body 的复现命令）…"
# 2) Chromium（playwright，来自 tests/node_modules）390×900 @2x 截图
NODE_PATH="<repo>/tests/node_modules" node /tmp/shot.cjs
```

## 读图判定（逐条对齐用户四条）

| 用户要求 | 屏上读数 |
|---|---|
| 只显示实际褶倍 | 「实际褶倍 2.1倍」；**没有**「理论褶倍」行 |
| 去掉无效的 0 | 「宽 3米」「高 2.6米」「面料米数 6.3米」「加工费米数 6.3米」 |
| 删用料公式 / 算料档位 | 两行都不在（改前是 `pleat` / `standard`） |
| 货号 = 2659 | 「货号 2659」（改前是 SKU 码 `2659-01-28`；颜色 / 门幅仍各自成行） |

## 边界（如实登记）

- 这张图是**本地渲染产物**（真实现 + 真 CSS + Chromium 390px），**不是**真机登录 + 真库数据的截图；
  上屏口径的机器判据 = `frontend/worker-h5/tests/worker-h5-position-spec.test.mjs`（逐字断言整块 HTML）。
- 机台屏（一体机）仍三位小数（机器读数），本目录不含机台屏截图；该面只改「货号」取值来源，
  既有 12 行由 `worker-h5-position-spec.test.mjs` 的负控逐字钉住。
