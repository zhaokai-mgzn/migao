# 商品域涉钱面修复（issue #6662）—— 证据与现场读数

本目录是**证据**（脚本 + 冻结读数），不是产品代码。

## ① 判据 3 的现场核实：弹窗遮罩 vs 底部固定栏

**结论：审计的「遮罩下『提交并上架』仍可点」——不成立；但审计的担心指向了一个真问题。**

- `ProductForm.tsx` 底部固定操作栏 = `z-30`；`Modal.tsx` 根节点 = `fixed inset-0 z-50`，
  两者是**兄弟节点、同一层叠上下文** ⇒ 弹窗打开时遮罩**确实压在**底部栏之上。
- 量法（真实 Chromium，1440×980，用**应用自己编译出的 Tailwind CSS**）：

```bash
# 前置：本 worktree 内起 dev server（只需它提供编译后的 CSS）
cd frontend/admin-web && npx next dev -p 3011
# 跑探针（playwright 用仓库 tests/ 的依赖）
cd frontend/admin-web && PW_PATH="<repo>/tests/node_modules/@playwright/test" \
  node ../../acceptance/2026-10-10-6662-products-money/probe-modal-vs-fixed-bar.cjs
```

**冻结读数**（`probe-modal-vs-fixed-bar.reading.json`）：

| 量 | 读数 |
|---|---|
| `z` | `{ bar: "30", modal: "50" }` |
| 「提交并上架」按钮中心 `elementFromPoint` | `DIV#tracker`（Modal 的 `absolute inset-0 flex items-center justify-center` 容器） |
| `hitIsSubmit` | `false` |
| Playwright 真实点击 `#submit` | `TimeoutError: page.click: Timeout 2500ms exceeded`（hit-target 被挡） |
| 在按钮中心坐标真实鼠标点击 | `submit=0 / mask=0 / tracker=1`（事件被 tracker 收下，按钮**没收到**） |
| 在遮罩空白区真实鼠标点击 | `submit=0 / mask=0 / tracker=2`（被 tracker 收下，**遮罩也没收到**） |

**所以：**
1. **点击不会穿透到底部栏的按钮** —— 审计的「仍可点」**证伪**（没有人能改到底下那份表单）。
2. **但也没有「命中遮罩」** —— 事件被 Modal 的**内容容器** `absolute inset-0` 吞掉。
   本处 `maskClosable={false}`，遮罩点不开弹窗，所以商家看到的是**点了没反应**（静默无效），
   不是「误触改了东西」。这一条**不在本包文件族**（`components/ui/Modal.tsx` 属公共原语，
   本包只拥有 `components/products/**` 与 `app/(dashboard)/products/**`）⇒ **如实登记，未改**。

### 这个探针**没**证明的那一半（照实登记）

它是**静态同构复现**（DOM 结构 + 应用的编译后 CSS 逐字相同），**不是**在跑真实 `ProductForm` 组件：
真实 Next dev server 上的 `/products/new` 需要登录会话（本 worktree 起 dev server 时
`AuthProvider → /api/auth/me` 无 cookie ⇒ 跳登录页），未能自动化登录 ⇒ 没能直接量真页。
**因此：弹窗打开时底部栏的命中关系已由探针证实；但「真页面上弹窗长什么样」的视觉验收
仍待批次级 §15.7 真机多模态那一轮**（本包新增的探针路由只用于量层叠，已删除、未入库）。
