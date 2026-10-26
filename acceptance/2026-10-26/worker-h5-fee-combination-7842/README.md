# 工人报工屏：补「加工费组合」/ 移除实际褶倍 / 算料公式只印公式名（issue #7842）· 取证

用户 2026-10-26 逐字：

> 工人报工页面缺乏加工费组合中倒幅，超高 韩折 定型信息，可以参考pc端这样展示即可，移除实际褶倍，
> 算料公式只需要展示韩褶公式或者褶倍公式，后面的详细算法不要展示，可以移除

本目录只放**读图证据**；口径判据在测试里（`frontend/worker-h5/tests/worker-h5-position-spec.test.mjs`
的 ⑦ / ⑧ 与整块逐字断言），不在这里重复文案。

## 怎么复现这两张图（零真库、零登录；与 #7636 同一取证路径）

```bash
cd frontend/worker-h5
# 1) 用 `renderPage` 渲染真实产物（真实现 + 真 CSS；夹具与 `worker-h5-position-spec.test.mjs` 同形）
node /tmp/shot-worker-7842.mjs          # → /tmp/worker-7842.html（after）
node /tmp/shot-worker-before.mjs        # → /tmp/worker-7842-before.html（before = origin/main 的 position-spec.mjs）
# 2) Chromium（playwright 来自 <repo>/tests/node_modules）390×900 @2x：
#    全页截图 + 「本部位生产信息」逐元素截图
NODE_PATH="<repo>/tests/node_modules" node /tmp/shot-worker.cjs
```

`before-*` = `git show origin/main:frontend/worker-h5/src/position-spec.mjs` 那一份（其余文件同当前分支）；
`after-*` = 本分支。

## 读图判定（逐条对齐用户三条）

| 用户要求 | before（origin/main） | after（本分支） |
|---|---|---|
| 补「加工费组合」（倒幅 / 超高 / 韩褶 / 定型） | **没有这一行**（`before-spec.png`） | `加工费组合  定型、韩褶、超高、倒幅`（`after-spec.png`）|
| 移除实际褶倍 | `实际褶倍  2.05倍` | 该行**不在** |
| 算料公式只展示公式名 | `算料公式  韩褶公式：3×2−0.3 = 5.7 ÷ 0.25 = 22.8 → 23折 → 0.25×23+0.3 = 6.05米`（三行） | `算料公式  韩褶公式`（一行，推导链不上屏） |
| 其余行不回退（负控） | 商品身份 / 规格尺寸 / 安装工艺 / 总褶数 / 派工各行逐字在场 | 同左（`after-spec.png` 逐行比对无异） |

## 边界（如实登记，§19.1）

- 这两张图是**本地渲染产物**（真实现 + 真 CSS + Chromium 390px），**不是**真机登录 + 真库数据的截图
  —— 与 #7636 同一取证路径与同一登记口径；上屏口径的机器判据 = `worker-h5-position-spec.test.mjs`（逐字断言整块 HTML）。
- 「加工费组合」的**值来自服务端**（`fee_combination_items` ← `ProcessingFeeQueryService#featureNames`），
  本目录不覆盖服务端取数本身：那半边由 `ProductionScanServiceDetailFieldsTest` /
  `PositionDetailFieldsTest`（三条工人读面同源）判红。
