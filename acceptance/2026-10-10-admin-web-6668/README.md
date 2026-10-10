# admin-web 设计基线几何探针（issue #6668 盲区③）

**本目录 = 几何盲区的可复算入口**（真读数必须在真浏览器里取，jsdom 不做布局）。

## 怎么跑

```bash
# ① 起本地站点（生产构建；dev 也能跑，但读数会带 Fast Refresh 注入的节点）
cd frontend/admin-web && npm ci && npm run build && npm start &   # :3001

# ② 装浏览器驱动（首次；admin-web 自己不装 playwright）
cd ../../tests && npm ci && npx playwright install chromium

# ③ 跑探针（默认 http://localhost:3001；也可传 URL 参数）
node acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs http://localhost:3001
```

- 输出：stdout 一行 JSON（机器读数）+ `out/*.png`（三页截图，1440×980）+ `out/report.json`；
- 退出码：`0` = 四条判据全过；`1` = 有判据判红（逐条具名）；`2` = 环境缺失（如找不到 playwright）。

## 量什么（口径 = `docs/design/design-baseline.md` §几何）

| 读数 | 判据 |
|---|---|
| 主控件（`button` / `[role=button]`）高 | ≥ 36（= `h-9`） |
| 常驻面（`header` / `nav` / `*-bar` / `*-warnings` / sticky）高 | ≤ 96 |
| 滚到底后**叶子文本底边 − `fixed`/`sticky` 面顶边** | ≤ 0.5（> 0.5 即被压住） |
| 首屏被常驻面占掉的垂直比 | ≤ 0.4 |

## ⚠️ 本包**没有跑**（照实登记，§19.1）

- **本机没起 `:3001`，探针的浏览器腿一次都没跑** ⇒ 本目录**只有口径与入口，没有实测读数**。
- 触屏门面（`worker-h5` / 两个 Taro app）**不在本探针射程**（它们有各自的
  `acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs`）。
- 判据文件 `frontend/admin-web/tests/unit/design-baseline-geometry.test.ts` 守的是**本探针的
  可复算入口 + 四条判据的判别力**（内存注入），**不等于**「几何已验过」。
