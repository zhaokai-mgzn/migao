# 车间现场端页头按钮折行的修复 + 部署后重放（issue #6763）

> 本目录是**一次性验收记录**（不是常驻判据）。常驻判据在仓内两处：
> `frontend/worker-h5/tests/worker-h5-6763-header-nowrap.test.mjs`（静态类级判据）与
> `scripts/probe-worker-h5-touch.mjs`（真 Chrome + CDP 的三视口**行盒数**读数）。

## 1. 现场与根因

`app.migaozn.com/w/`（工人报工页）**登录后**，页头两个按钮的文字被拆成两行（「切 / 换」「登 / 出」），
360 / 390 / 430 三视口全现。

- **病根**：页头是 flex 行（`.wh5-header`），`.wh5-ghost` 走浏览器默认 `flex: 0 1 auto`（**可收缩**），
  而工人姓名 `.wh5-worker` 是 `flex: 1 1 auto` ⇒ 名字一长（`当前工人：<名字>（工号 X）`），
  按钮被压到 50~55px，**小于内容宽度**（2 字 × 15px + 左右 `padding` 14px×2 = 58px）⇒
  浏览器在字符间断行。
- **不是「少写了一条样式」，是「没有谁显式声明这块空间怎么分」** ⇒ 换个更长的名字、或再加一个按钮，
  同一缺陷能再来一次（所以修法是「显式化 + 类级判据」两件，而不是只改那一行值）。
- 修复：PR #6838 → `cbd03de2`（2026-10-13 18:59 +08）；发布腿
  `Publish worker-h5 (app.migaozn.com/w/)` 成功（含发布后落地面身份断言）。

## 2. 修前 / 修后读数（同一台机器、同一探针；真工人身份）

判别量 = **文字节点的行盒数**（`Range.getClientRects()`，一行一个矩形）。

| 读数 | 修前（issue 现场 / 仓内探针红证） | 修后（线上 19:00 +08） |
|---|---|---|
| 360px | 按钮宽 **50px** / **2 个行盒** | 按钮宽 **58px** / **1 个行盒** |
| 390px | 按钮宽 **52px** / **2 个行盒** | 按钮宽 **58px** / **1 个行盒** |
| 430px | 按钮宽 **55px** / **2 个行盒** | 按钮宽 **58px** / **1 个行盒** |
| 页头按钮触控高 | 44px | 44px（未被修坏） |
| 工人姓名宽 / 行数 | 212.8 / 238.1 / 271.9（折两行） | 192 / 222 / 262（**折两行，有意如此**） |

仓内探针（夹具 = 真渲染输出 + 真 styles.css + 真页同一条 viewport meta）：
**修前 31 条里 6 条不达标（exit 1）→ 修后 31 条全过（exit 0）**。

## 3. 读图判定（`migao-dev-flow` §15.7：真机截图 + 读图，逐条引证据）

`out/worker-h5-header-390.png`（线上 390px）：页头第一行是
「当前工人：UI验收-可删除（工号 UITEST01）」（**名字折两行** —— 它是被压缩的那一个），
右侧「切换」「登出」**各自单行**、两个按钮尺寸一致 —— 与 issue 现场的「切 / 换」「登 / 出」逐条对照成立。
`out/worker-h5-header-360.png` / `-430.png` 同形态。

## 4. 复算（任何人都能重跑）

```bash
# ① 线上重放（本目录脚本；真登录，390×844；三视口各出一张截图）
cd <repo>/tests
node ../acceptance/2026-10-13-worker-h5-header-6763-replay/worker-h5-header-6763-replay.mjs https://app.migaozn.com

# ② 仓内几何判据（真 Chrome + CDP，含同一批三视口行盒读数）
node scripts/probe-worker-h5-touch.mjs

# ③ 仓内静态类级判据 + 全量
node --test frontend/worker-h5/tests/*.test.mjs
```

## 5. 两条实测教训（已写进代码注释，防后人再踩）

1. **夹具缺 `<meta name="viewport">` ⇒ 探针恒绿**：本包第一次跑就是假绿（按钮 68px、只读到 1 个行盒）——
   `Emulation.setDeviceMetricsOverride({mobile:true})` 在**没有 viewport meta** 时不会把布局宽度
   设成手机宽（页面按默认 980px 排版，页头空间富余 ⇒ 缺陷复现不出来）。
   ⇒ 夹具已对齐真页 `frontend/worker-h5/index.html` 的同一条 viewport。
2. **「没溢出」不等于「没折行」**：修前 `scrollWidth <= clientWidth` **成立**（47 <= 47），
   `.wh5-ghost` 的 `min-height: 44px` 也会把两行包住（高 44px）⇒ **高度与 `scrollWidth` 都不是判别量**。
   差点被这两条假绿放过。

## 6. 边界（照实登记）

- 只动页头按钮的**伸缩性与换行**；**不动** `≥768px` PAD 断点，也不动 `.wh5-worker`（名字继续折行）。
- 观感终判仍属人（`migao-dev-flow` §31.4）。
