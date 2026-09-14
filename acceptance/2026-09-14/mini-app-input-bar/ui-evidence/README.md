# 小布 C 端输入条 UI 证据（2026-09-14，issue #3741）

> **本批证据对应「语音优先 v2.1」版设计**（宽胶囊「按住 说话」+ 语音优先 placeholder + 首访一次性引导 + 单行条）。
> 更早一版（仅单行对等、无语音优先）的证据**已被本批取代**，不要引用。

## 可复现元信息

| 项 | 值 |
|---|---|
| 被测代码 commit | `ba13ed5cfeb54fe6b8bf40b1c065e56225ca23da` |
| 构建产物 | `frontend/mini-app/dist/app.js` @ 2026-09-14 22:01:04 |
| 源码指纹 | `MessageInput.tsx` sha256:cefec3fe6654fe7d / `MessageInput.scss` sha256:165fcf8370526f2e |
| 产物指纹 | `dist/pages/chat/index/index.wxss` sha256:3d735c39b6cd7ad7 |
| 产物关键样式自证 | `.message-input__row{-webkit-align-items:flex-end;display:-webkit-flex;display:-ms-flexbox;display:flex;-ms-flex-align:end;align-items:flex-end;gap:4rpx}` |
| 产物关键样式自证 | `.message-input__icon-btn{-webkit-align-items:center;border-radius:50%;display:-webkit-flex;display:-ms-flexbox;display:flex;height:88rpx;width:88rpx;-ms-flex-align:center;align-items:center;-webkit-justify-content:center;-ms-flex-pack:center;-webkit-flex-shrink:0;justify-content:center;-ms-flex-negative:0;background:#e8f1fe;flex-shrink:0}` |
| 环境 | 微信开发者工具模拟器，机型 iPhone 12/13 (Pro)，SDKVersion 3.17.2；视口 390 CSS px ↔ 设计宽 750rpx（1 CSS px ≈ 1.923rpx） |

## ⚠️ 证据边界（必读）

1. **格式**：`*-bottom360.png` 是整屏截图**底部 360px 裁切**；全屏原图在 `full-screen/`。
2. **预览态缩略图是 mock 替身**：`after-03-image-preview-*.png` 里的缩略图内容由
   `wx.mockWxMethod('chooseImage', {tempFilePaths:['/assets/tabbar/chat.png']})` 注入
   （即 tabbar 图标），**几何真实、图像内容是替身**，不是真实相册图。
3. **登录态是注入的**：模拟器 `wx.login` 的 code 被后端判 `WECHAT_API_ERROR: code 无效` ⇒ 会掉登录页、
   输入条 disabled。本批证据用 `POST /api/auth/sms/login`（测试账号 13800138000/万能码）取 JWT 后
   `setStorageSync('auth_token'|'auth_user'|'tenant_id')` + `reLaunch` 注入登录态，**未改任何产品/后端鉴权代码**。
4. **帧稳定性**：同状态连拍两帧 + 帧前后各量一次几何，判据见 `frame-stability.md`
   （输入条区域两帧 md5 一致 / 全屏差异不触及输入条区域 / 跨状态区域 md5 必须不同）。
5. **几何数字以 DOM 探针为准**：独立多模态模型从降采样裁切图目测的数字只作定性佐证（其自述 ±5px）。
6. **⚠️ 原生 tabBar 覆盖输入条底部（本次新发现，改前就存在）**：模拟器里原生 tabBar
   （`app.config.ts` `backgroundColor:#ffffff`）从 **CSS y≈762** 起覆盖页面，而容器布局底边 = 771、
   发送键布局底边 = 767 ⇒ 截图中**容器底部 ~9px 与发送键下弧被 tabBar 盖住**（像素实测：`#f5f7fa` 到
   image y=1067 即 CSS 762.1 突然变纯白；**改前构建同一边界**）⇒ 与本次改动无关，属页面/tabBar 层级既有条件，
   本 PR 未改页面布局（超出授权文件范围），已另建 issue 跟踪。DOM 布局断言不受影响；真机 `windowHeight`
   是否同样包含 tabBar 区域**未验证**。

## 文件清单

| 文件 | 说明 |
|---|---|
| `before-0X-*.png` | 改前（单容器 column：文案左上、按钮右下） |
| `after-01-empty-voice-voice-first-*.png` | 改后·语音默认态（宽胶囊「按住 说话」+ 首访引导行） |
| `after-01b-hint-dismissed-*.png` | 改后·点 × 关闭引导后的同一状态（引导不再出现） |
| `after-02-draft-keyboard-send-*.png` | 改后·键盘/打字态（草稿非空 → 发送↑ 圆键） |
| `after-03-image-preview-*.png` | 改后·已选图片预览（容器变高，缩略图为 mock 替身） |
| `after-04-multiline-draft-*.png` | 改后·多行草稿（按钮贴底） |
| `geometry-summary.md` | 几何判据 A~E（改前/改后对照 + 阈值判定） |
| `frame-stability.md` | 帧稳定性判据（含两帧 md5 与全屏差异 bbox 定位） |
| `full-screen/*.png` | 上述各状态的整屏原图 |
