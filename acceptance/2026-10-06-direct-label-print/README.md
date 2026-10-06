# 生产明细「免驱动直连打印机」页面多模态验收（issue #6439）

被测面：本机 **admin-web `:3000`**（worktree `feat/6439-production-label-direct-print` 的代码）+ admin-api `:8080`。
（`:3001` 上跑着**另一个 worktree（6430-saving-board-story）**的进程 ⇒ 本包改用 `:3000`；两个端口都在
`CORS_ALLOWED_ORIGINS` 白名单内，见 `migao-dev-flow` §15.7「唯一入口」。本条**只读页面、无写操作**，不污染他人会话。）

**被测代码 SHA = `71e5e86c4`**（`fix(admin-web): #6439 直连打印提示不再原样印出 markdown 星号`）——
截图时工作树与它**逐字节一致**（截完 `git status --porcelain` 为空）。本目录在其后追加：
**只加证据，不改代码**。测量时间 2026-10-06 18:04–18:06 (+08)。
登录：管理员手机验证码（`13800138000` + 本机 `SMS_BYPASS_CODE`），租户 25「米高测试环境」。
目标页：加工单 `JG-20261006-5271` 的 `/processing-orders/JG-20261006-5271/production`。

## 0. 一句话

**新增的「直连打印机打印」入口在真页面上是好的，并且与既有的「打印任务卡」并存**；
而这一轮**抓到了一个六条门禁全绿、只有肉眼看得见的真缺陷**（页面上裸露的 markdown 星号），已修并重放。

## 1. 一条命令复跑（承载体 = preset skill 的 `ui-multimodal-acceptance.mjs`）

```bash
node /Users/guangzhen.zk/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
  --site http://localhost:3000 --path "/processing-orders/JG-20261006-5271/production" \
  --out acceptance/2026-10-06-direct-label-print/out
```

读数：`loginOk=true` · `loginShape=login-tabs-v5485 ✓` · **`testids=129`** · **`http5xx=[]`**（`out/summary.json`）。

## 2. 多模态判定（我自己读图；写「看到了什么」而不是「应该是什么」）

| 截图 | 我看到的 | 判定项 |
|---|---|---|
| `out/01-before-markdown-leak.png` | 标题行右上仍是「生成二维码（测试用）/ 撤销二维码 / **打印任务卡**」；其下多了一枚带蓝牙图标的「**直连打印机打印**」；再下一行小字**把 `**免驱动**` 连星号一起印了出来** | 入口在 + 与系统打印**并存** + 🔴 **markdown 标记外溢**（缺陷） |
| `out/02-after-full.png` | 同上，但小字变成「点「直连打印机打印」后选一台标签机即可免驱动打印：不用装驱动，但只支持带网页蓝牙协议的机型。」**星号消失** | 修复生效 |

`out/page-text.txt` 里 `**` 命中数：修前 **1**、修后 **0**；
`error / 失败 / undefined / NaN` 命中数 **0**（两侧一致）。

## 3. 这一轮抓到的真缺陷（§15.7 的立项理由复现）

- **形态**：源码里写了 markdown 强调 `**免驱动**`，而渲染点没接 `@/lib/inline-markdown`
  ⇒ 星号**原样上屏**。单测 / 构建 / 契约 / UI 回退**全绿** —— 与 §15.7 记录的三条形态同类。
- **修法**：按仓既有裁定（`copy-no-markdown-emphasis.test.ts`：带标记要么**接渲染器并登记**、
  要么**删标记并说明**）⇒ 这只是一行可行动提示、强调不承载层级信息 ⇒ **删标记**，
  并在 `frontend/admin-web/src/lib/label-print/capability.ts` 写明「有意为之，别顺手加回」。
- **判据**：`frontend/admin-web/tests/unit/components/DirectLabelPrint.test.tsx` 补 **DOM 面**断言
  （`direct-print-ready` 的 `textContent` 不含 `*`）；类级守卫 `copy-no-markdown-emphasis` 的
  **判据 ③（未登记即红）**自动覆盖该文件 —— 标记加回去 ⇒ 必红。

## 4. 未覆盖项（照实登记，不粉饰）

1. **真机打印未端到端验**：Playwright 无人值守，**弹不出设备选择框** ⇒「点按钮 → 选设备 → 出纸」
   这一段未在页面上跑通；位图与传输只有单测层面判据（`tests/unit/lib/label-print-*.test.ts`），
   真机纸面效果（1:1 / 边距 / 短码可读）仍需人在打印机旁核对。
2. **不可用分支的文案面**：本机 Chrome **有** Web Bluetooth ⇒ 真实浏览器走的是**可用**分支
   （页面显示的是 `direct-print-ready`）；`direct-print-hint` 那条路径只有 jsdom 判据覆盖，
   真实浏览器下未复现到（`out/testids.txt` 里可核对：有 `direct-print-ready`、无 `direct-print-hint`）。
