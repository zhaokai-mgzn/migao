# UI 级重放报告（2026-10-03，Asia/Shanghai）

**为什么单开这一轮（证据面降级）**：#6103 / #6128 两条前端修复此前只有 jsdom 单测 + `check-ui-regression.sh`，
两者都**从夹具出发**，照不到真实链路上最可能失败的两处（见下）。本轮把它们放到**真机 chromium + 真 API + 真库**
上判。

**被测构建点**：API `:8080` 与 WEB `:3001` **同源** = `/Users/guangzhen.zk/migao-wt/main-live` @ `d160c4c96`
（`:3001` 的 dev server 一直是从 main-live 起的 —— 见"事实订正"）。真机浏览器 = 仓内 `tests/node_modules` 的
chromium（**未安装任何新依赖**）；登录走 `POST /api/auth/sms/login` + 万能码（本机 `:8080` 已启用）。

## 一、读数：8/8

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| U1 | 登录后进入工艺配置页 | ✅ | `out/u1-routings-page.png` |
| U2 | 新建**目录外**工序 ⇒ 写面提示条出现、不阻断创建 | ✅ | 文案逐字「该工序不在算料目录内，派工应做数量将按 1 计」；`out/u2b-after-create.png` |
| **U3** | **刷新后该行出现「数量按 1 计」徽标**（按逻辑工序名 **join 两张读面**） | ✅ | `matrix-qty-fallback-<探针名>` 命中 1 且可见；`out/u3-after-reload.png` |
| U4 | 负对照·界面：目录内「韩褶」**不得**有徽标 | ✅ | 命中 0 |
| U5 | 抽屉里的解释行 `operations-manage-qty-fallback` 在场 | ✅ | 文案逐字；`out/u5-drawer.png` |
| **U6** | **#6103 停用**：无 4xx **且 DB `status` 真的变 `disabled`** | ✅ | 网络面新增 4xx = `[]`；DB `status=disabled`；`out/u6-after-disable.png` |
| U7 | 负对照·读面：目录内「韩褶」的 `qty_rule_missing` 为 falsy | ✅ | `false` |
| U8 | 零残留：探针工序不存活（读面 + **DB** 双证） | ✅ | catalog 存活 0 / DB 存活 0；本轮另清理历史遗留 1 个 |

**U3 是这轮的核心**：`qty_rule_missing` **只长在工序库读面**（`GET /production/operations-catalog`），
而工艺项表的行来自**价目读面** ⇒ 徽标必须**按逻辑工序名跨读面 join**。jsdom 里这个字段是夹具直接给的，
**join 失配在单测里永远照不到**；真机上它**成立**（探针名 `UI重放工序NNNNNN` 命中且可见）。
**U6 是"按钮真的生效"**：修前是字典域取错（UI 发 `inactive`、后端只认 `active|disabled`），
本轮以**DB 真值**判定（读面根本不返回 `status`，只看界面必然假绿）。

## 二、我自己的三处假绿（判据缺陷，已修，留档）

1. **零残留假绿**：首版把读面响应解析错了 ⇒ 列表恒空 ⇒ 「存活 0」**平凡成立**。
   ⇒ 改成**读面 + DB 双证**，并**先把 run1/run2 遗留的探针清掉**（否则"零残留"是拿坏查询骗自己）。
2. **查了不存在的字段**：首版 U6 判 `读面.status === 'disabled'`，而 `CatalogOperation` **没有 `status` 键**
   （`undefined === 'disabled'` 恒假 ⇒ 反而"安全地红"，但判据本身无效）⇒ 改用 **DB `production_operations.status`**。
3. **用读面清场会漏**：run2 的探针被**停用**后再清场时，它在**读面里已经看不见**（读面按不显示停用工序过滤）
   ⇒ 残留躲过了"按读面找残留"的清理。⇒ 清场改为**按 DB 找**（`name like 'UI重放工序%' and deleted = 0`），
   并顺带收掉了 3 个历史遗留（含 run1/run2 各 1 个）。

## 三、事实订正（铁律 11(a)）

| 原说法 | 订正 |
|---|---|
| 线③ F3「UI 实发 `status=inactive` ⇒ 422，未修」被我记为「**主检出**（`feat/5939-shipments-menu`）在跑」 | 归属**订正**：`:3001` 的 dev server cwd 实测 = `/Users/guangzhen.zk/migao-wt/main-live/frontend/admin-web`（Next 的按目录锁把 PID/Dir 逐字打了出来）。**结论不变**（当时 main-live 停在 `402be478b`，早于 #6103 ⇒ 服务的是旧代码），但"是主检出在跑"这句是错的。 |
| —— | 另：本机**不能**在 main-live 里再起一个 dev server（Next 16 按目录单例锁），换端口也绕不过；`ADMIN_WEB_PORT` 只对"占用者属于别的检出"有效。 |

## 四、未覆盖面（照实）

- 只在**一个视口**（1512×950）跑，未做多模态读图判定（`migao-dev-flow` §15.7 的截图 AI 判定未做）。
- 未覆盖工艺配置页的**其它 tab**（工艺路线 / 算料 / 裁高）与移动端。
- 探针只覆盖"目录外工序"这一形态；未覆盖同名工序、跨租户等边界。
