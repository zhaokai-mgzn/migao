# 390×844 视觉验收（issue #8194，2026-10-31）

## 图

- `bmini-report-login-390x844.png`：小程序 `/b/` 报工页**未登录就地登录**（修复后；CDP `Emulation.setDeviceMetricsOverride` 390×844 截图）。
- `wh5-login-390x844.png`：终端 `/w/` 工人登录参考（同一视口）。
- `bmini-report-card-2x.png` / `bmini-report-unauthorized-full-2x.png`：同一修复后的 2x DPR 截图（卡片局部 / 整页；整页可见「无扫码报工页头」）。

## 修前真形态（视觉验收抓到，几何腿没覆盖）

390 宽下小程序登录卡片右缘出屏：副标题「无需微信）」被切、输入框/按钮右侧不可见。CDP 读数（修前）：`document.documentElement.scrollWidth > innerWidth`，卡片 `getBoundingClientRect().right > 390`。
根因：卡片是 flex 列子项，默认 `min-width:auto` + `box-sizing:content-box`；Taro 的 rem 换算下卡片 padding 与输入框 padding 把右缘顶出视口。几何腿只量**竖向**居中，所以没红。

## 修后读数（CDP，390×844）

```
root   x=0     w=390    right=390
card   x=12.5  w=365.1  right=377.5   box=border-box
sub    x=29.1  w=331.8  right=360.9   h=21.8（单行完整）
input  x=29.1  w=331.8  right=360.9   h=49.9
button x=29.1  w=331.8  right=360.9   h=45.8
doc.scrollWidth=390 = innerWidth
```

## 复算

```bash
cd frontend/bmini-app && npm run build:h5
# 启静态服务后用 Chrome/CDP 以 390×844 打开 /#/pages/worker/report/index
# 或跑 e2e：tests/e2e/specs/bmini/bmini-input-center.spec.ts 的「报工页未登录的登录卡片在 390px 宽内不横向溢出」
```
