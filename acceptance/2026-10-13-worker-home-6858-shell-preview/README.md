# 工人工作台「管理面外壳」的合并前预览（issue #6858）

用户 2026-10-13 反馈「这版本的菜单主页不太符合我们整体样式设计，为什么搞成纯白色背景了？」

**归因**：#6847 只补了**页面底色**（`#f5f7fa`，别的页面也在用的"底"），而工人工作台**连页头都没有**
—— 同族三页（拍照入库 / 补打入库标签 / 拍照发货）都是 `src/styles/admin-surfaces.scss` 的
**深蓝→蓝渐变页头 + 灰底 + 白卡**。只有底色时它落在灰白底上仍然「看着是白的、没有层次」。

**本目录** = 合并前给人看的预览（真实 Taro H5 构建产物 + 打桩工人接口，390×844）：

| 文件 | 是什么 |
|---|---|
| `out/worker-home-after-390.png` | 改后 · 登录态（渐变页头 + 身份卡 + 四条入口 + 退出） |
| `out/worker-home-after-gate-390.png` | 改后 · 未登录态（页头在，引导块不被挤坏） |
| `preview-6858.mjs` | 可复算的预览探针（打桩接口，不需要真后端） |

对照「现状」（同页面今日线上）：`acceptance/2026-10-13-worker-home-6760-replay/out/worker-home-6847-surface-after.png`。

## 复算

```bash
cd frontend/bmini-app && npm run build:h5
python3 -m http.server 8099 --directory dist &
cd <repo>/tests && PREVIEW_BASE=http://127.0.0.1:8099 \
  node ../acceptance/2026-10-13-worker-home-6858-shell-preview/preview-6858.mjs
```

读数（预览实测）：`__header` 的 `background-image` = `linear-gradient(135deg, rgb(10, 37, 64), rgb(26, 115, 232))`，
高 71.5；`__title` 白字；`__subtitle` `rgba(255,255,255,0.78)`；`__card` 仍白、`entryCount=4`。
