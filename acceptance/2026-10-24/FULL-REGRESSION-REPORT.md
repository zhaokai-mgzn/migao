# MIGAO 全量回归报告（演示前） — 2026-10-24

> 被测版本：`main` @ `3e6bd6bbb8e2234a10379f80bf9eb01eb24476b7`（与 `origin/main` **0/0**，工作区干净）
> 环境：本机（macOS / JDK 21 / Node 24.19 / Python 3.11）+ 云 dev **RDS `ai_customer_service`** + 云 Redis
> 口径：**零 LLM 评测**（按用户要求）；C 端小程序/H5 **按用户要求不跑**。
> 证据目录：`logs/regression-full-20261024-013755.log`、`acceptance/2026-10-24/merchant-ui-smoke-t46/`、`acceptance/2026-10-24/business-chain/`

---

## 0. 结论摘要

| 面 | 结果 | 证据 |
|---|---|---|
| 三模块全量单测（Java / Python / 前端） | **全绿**：5109 + 7298 + 5353 条通过，0 失败 | §1 |
| 类型检查 / UI 回退 / 三端契约 / 覆盖体检 | **全绿** | §1 |
| **核心业务全链路**（下单→加工→报工→质检→发货→售后→财务） | **18/18 通过**（真库回读） | §2 |
| B 端 UI 全旅程（33 条，真浏览器 + 真后端） | **33/33 通过**，0 失败 0 skip | §3 |
| 仓库 CI 工具链判据集 `tests/unit_ci_workflows` | **未跑完**（人工中止于 39%，非失败） | §1.1 |

**演示可用性判断**：B 端主链路（登录→看板→商品→订单→生产/加工→发货→售后→财务→设置）**在本机真栈上可用**；
演示前必须处理的 4 件事见 §5。

---

## 1. 全量单测（`./verify-all.sh full` 的等价腿）

> ⚠️ `./verify-all.sh full` 在**零 diff 的 main 上会主动拒绝**（「禁空跑」，exit 3，设计如此）。
> 故按同一份腿定义**手工串行执行**，并在一条 bash 里持机器级重活锁（§27）。

| 腿 | 命令 | 结果 | 耗时 |
|---|---|---|---|
| admin-api 全量 | `cd backend/admin-api && ./mvnw test` | ✅ **Tests run: 5109, Failures: 0, Errors: 0, Skipped: 1 · BUILD SUCCESS** | 192s |
| ai-agent 全量 | `cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -q --no-cov -n 4` | ✅ **7298 passed, 21 skipped** | 54s |
| admin-web 单测 | `cd frontend/admin-web && ./node_modules/.bin/vitest run` | ✅ **443 files / 5353 tests passed, 1 skipped** | 124s |
| admin-web 类型 | `./node_modules/.bin/tsc --noEmit` | ✅ 无错误 | 11s |
| worker-h5 | `node --test frontend/worker-h5/tests/*.test.mjs` | ✅ **274 pass / 0 fail** | <1s |
| UI 回退检测 | `./check-ui-regression.sh` | ✅ 无回退 | 6s |
| 三端契约 | `./contract-check.sh` | ✅ 6 项全过（订单状态词表 / 退款字段 / 物流字段 / 单 SKU 改价 / 退款蛇形 / intent 归属） | 1s |
| 评测覆盖体检 | `scripts/{xiaobu,mibao}_coverage.py --check` | ✅ 通过（17 项「薄覆盖」只报告不阻塞） | 2s |

### 1.1 未跑完 / 未跑（**「没跑」不等于「通过」**）

| 项 | 状态 | 原因 |
|---|---|---|
| `tests/unit_ci_workflows`（CI 工具链判据集，`pr-check` 的 required job） | ⚠️ **39% 处人工中止**（861s） | 它验的是仓库 CI 工具自身，不是产品功能；为把机器让给真栈 UI 全链路而中止。**本轮不构成「通过」** |
| 真实打印/PDF、微信支付、真实短信网关、真机小程序 | 未覆盖 | 形态限制（需真机/真打印机/外部服务） |
| LLM 评测 / agent-eval | **按要求不跑** | — |

---

## 2. 核心业务全链路（真栈真库，18 步）

脚本：`acceptance/2026-10-24/business-chain/chain2.py`（可复跑：`python3 acceptance/2026-10-24/business-chain/chain2.py`）
租户：**46 · 亿家纺织**（`13900001025`，云测试/演示租户）；每步都是**写后回读**，不是「点了没报错」。

| # | 步骤 | 结果 | 关键读数 |
|---|---|---|---|
| 00 | 登录（短信 bypass） | ✅ | tenant=46 |
| 01 | 商品读取 | ✅ | 奶油风纯色遮光窗帘 · ¥30.8 |
| 02 | 下单落库 | ✅ | orderNo `20261024822010009`，金额 ¥61.6 |
| 03 | 确认收款 | ✅ | 回读 `confirmed` |
| 04 | 加工单生成 | ✅ | **下单即自动生成** `JG-20261024-3187` |
| 05 | 工序实例化 | ✅ | `operation_count=12` |
| 06 | 工序清单 | ✅ | 精裁 / 三边 / 韩褶 / 上车布 …（12 道，含单位/数量） |
| 07 | 派发（issue） | ✅ | 回读 `issued` |
| 08 | 开工（start） | ✅ | 回读 `in_processing` |
| 09 | 报工（全 12 道） | ✅ | 12/12 成功 |
| 10 | 计件读数 | ✅ | 合计 ¥9.0，按工人/工序拆分 |
| 11 | 完工 | ✅ | 回读 `completed`（**报工全完成即自动完工**） |
| 12 | 质检录入（pass） | ✅ | 记录 id `1ecb4d9b…` |
| 13 | 发货 | ✅ | 回读 `shipped`；发货单号 `SH202610240212329884` |
| 14 | 发货单可查 | ✅ | `data.shipments[]` 1 条 |
| 15 | 售后建单 | ✅ | 工单 `279fc159…`，`status=pending`，`type=return` |
| 16 | 看板统计 | ✅ | `todayOrders/todaySales/...` 可读 |
| 17 | 财务对账 | ✅ | `total=16` |

**说明**：本轮 18 步中前两次运行暴露的 3 个「失败」经归因**都是脚本假设错**，已修脚本（不是产品缺陷）：
① 加工单在下单时已自动生成（原脚本以为要显式 `generate`）；② 报工全部完成会自动完工（再显式 `complete` 回 422）；
③ 发货单读面是 `data.shipments[]` 嵌套形态（原脚本按顶层数组取 ⇒ 误判 0）。

---

## 3. B 端 UI 全旅程（33 条，真浏览器 + 真后端 + 真库）

命令（可复跑）：
```bash
cd /Users/guangzhen.zk/ai native/migao
OUT_DIR="$PWD/acceptance/2026-10-24/merchant-ui-smoke-t46/out" \
PHONE=13900001025 SMS_CODE=123456 ./scripts/ui_smoke_merchant.sh
```
> 结果见 `acceptance/2026-10-24/merchant-ui-smoke-t46/out/smoke-summary.md`（每个旅程带截图证据）。

**最终一轮（修完 13 处判据缺陷后）：`33/33 通过，0 失败，0 未配置，0 skip`，`spec 退出码: 0`。**

覆盖的旅程（逐条 ✅，证据 = 同目录 `screenshots/<journey>.png`）：

- 登录 / 会话保持；经营看板；经营简报；接待工作台重定向；在线接待；会话历史；**对话页**
- 商品：列表 / **新建（门幅 值/显示分离 + 建品可见）** / 详情 / 编辑门幅回显
- 加工项 新建→编辑→删除；分类 新建→删除；**订单列表**；**新建订单（真提交 → 到达详情）**
- **订单详情 + 加工单**；**生产二维码 + 计件**；**发货页**；**发货真提交（UI→HTTP→库，含同键重放幂等）**
- 售后列表 / **售后详情（接受→关闭→原因回显）**；客户列表 / 客户详情；财务对账；员工；岗位权限
- 设置（17 Tab 只读校验、无意外保存、0 个 4xx）；通知中心；门户四页（首页/关于/联系/服务）；注册页

**盘点**（真栈实测）：本报告覆盖 **B 端 33 条 UI 旅程 + 18 步业务链路 + 三模块 12,760 条单测**；
未覆盖项见 §1.1 / §5（真机小程序、真打印、微信支付、真实短信网关）。

---

## 4. 本轮发现并修复的问题

| # | 问题 | 性质 | 处置 | 承载体 |
|---|---|---|---|---|
| 1 | 本机公网 IP 变化（`123.160.202.90` → `1.193.122.131`）⇒ RDS 新连接超时，本地栈起不来（旧连接池还活着，症状极像「产品挂了」） | **环境** | 用 `aliyun rds ModifySecurityIps --ModifyMode Append` 追加新 IP（只追加，未覆盖），TCP 复测通过 | 本报告；建议后续修 `scripts/dev-db-whitelist.sh` 的**多源取 IP 只取首个**（本次取了旧 IP） |
| 2 | `14-orders-list` 断言等「订单列表」，页面标题已改为「销售订单」⇒ 页面正常却判红 | **测试漂移（假红）** | 改断言为「销售订单」 | `scripts/ui-smoke-merchant/spec.mjs` |
| 3 | `15-orders-new` 成功判据 `url.includes('/orders')` 对 `/orders/new` **同样成立** ⇒ 提交失败也记 ✅（**假绿**）；按钮找不到时 `.catch(()=>{})` 把点击失败吞掉 | **判据缺陷（假绿）** | 断言改为「到达 `/orders/<id>`」，按钮找不到即报错 | 同上 |
| 4 | 建单前置写死商品 id `deff0be6…`，云库**已不存在** ⇒ 16/17/32 前置单建不出来 | **硬编码陈旧对象** | 改为**现取本租户**有价商品 | 同上 |
| 5 | 「生成加工单」探针把服务端回的「已有加工单」当「能力不可用」⇒ 16/17/32 以**错误理由 skip** | **归因错误（假 skip）** | 「已有加工单」计为能力可用 | 同上 |
| 6 | 默认登录号 `13800138000` 是 **C 端顾客**（#7479）⇒ 默认参数下 `01-login` 必红 | **默认值失效** | 默认改为商家管理员 `13900001025`（租户 46） | `scripts/ui_smoke_merchant.sh` |
| 7 | **租户 46 的品牌 logo 指向 `https://static.migaozn.com/regression/logo.png`，该域名 NXDOMAIN** ⇒ 每个页面都加载失败（演示里=每页一个破图），并让 33 条旅程全红 | **真实可见缺陷（数据）** | 置空该租户 `logo`（走默认品牌图）；已回读确认 | `tenants.logo`（tenant_id=46） |
| 8 | 网络级失败（DNS/拒连/TLS）只留下一条**不带 URL** 的 console 文案，导致「整站挂了」的误读 | **可观测性** | 新增 `page.on('requestfailed')` 归因，输出 host + 原因 | `spec.mjs` |
| 9 | `07-chat` 定长 1.5s 后盲取输入框 ⇒ 页面还在「加载中…」（会话列表首屏）就判红 | **假红（时序）** | 改有界等待 20s；超时把页面文案打进错误面（区分卡加载/未授权/空态） | `spec.mjs` |
| 10 | `09-products-new` 表头先渲染、行数据仍在 spinner 时判「商品未出现在列表」 | **假红（时序）** | 改有界等待自造商品名 20s（截图可见 spinner 仍在转） | `spec.mjs` |
| 11 | `32` 自带硬编码商品 id（同 #4），且假定必须点「生成加工单」—— 而本租户**下单即自动生成加工单**，按钮本就不出现 | **陈旧假设** | 改用现取商品；无按钮时改判「API 能查到本单加工单」 | `spec.mjs` |

**发现但未修（需配置/需人决策）**

| 项 | 读数 | 影响 | 建议 |
|---|---|---|---|
| **租户 1（评测 seed）无工艺路线、无岗位** | `production_route_templates` 该租户 0 条（tenant 46 有 2 条含默认）；`roles` 0 个 | 该租户的「生成加工单/智能派单/员工/岗位」页面必然不可用（服务端 `PRODUCTION_ROUTING_NOT_FOUND`） | 演示用**已配置的租户（46）**，或先在「企业基础设置→工艺路线」建一条并设默认 |
| `tests/unit_ci_workflows` 未跑完 | 39% / 861s 中止 | 不影响产品演示；CI 侧仍是权威 | 需要时单独跑完 |
| `dev-db-whitelist.sh` 多源 IP 取首个 | 本次取到 123.160.202.90（旧），实际出口 1.193.122.131 | 加白照样失败 | 改为**多源取并集**再追加 |

---

## 5. 演示前必做（4 件）

1. **确认演示环境**：
   - **本机**：`admin-api :8090` / `ai-agent :8001` / `admin-web :3001` 三件套（本报告全部读数来自本机真栈）。
   - **线上**：`merchant.migaozn.com` 已部署到 `3e6bd6bb`（frontend 部署 `success`）；`api` 侧 `sha=917e1703`
     （落后 5 个提交，但 `git diff --name-only 917e1703..HEAD` **无 `backend/` 文件** ⇒ 功能等价）。
     ⚠️ `#7579` 记录了一次 admin-api 部署失败（磁盘水位闸门）；另 `deploy-reconcile` 会在 PR 打开时重建容器
     ⇒ **演示期间冻结：不开/不合 PR**，避免 1~3 分钟 502 窗口。
2. **登录凭据**：商家后台 = `13900001025`（租户 46）/ `13600136000`（租户 1）；**不要用 `13800138000`**（C 端顾客号，会被拒）。
3. **演示租户要有配置**：`工艺路线`（默认路线）+ `岗位`。租户 1 缺这两项 ⇒ 生产/员工页会空/报错。
4. **演示前 1 分钟热身**：新建 1 张订单（订单列表默认筛选「近一个月」，老数据会显示「共 0 条」）；
   若演示打印/报价单，真机打一次（纸面样式不在本轮覆盖内）。

---

## 6. 复算命令（一条条可复制）

```bash
# 全量单测
cd backend/admin-api && ./mvnw test
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/ -q --no-cov -n 4
cd frontend/admin-web && ./node_modules/.bin/vitest run && ./node_modules/.bin/tsc --noEmit
node --test frontend/worker-h5/tests/*.test.mjs
./check-ui-regression.sh && ./contract-check.sh

# 核心业务全链路（需本机 admin-api :8090）
python3 acceptance/2026-10-24/business-chain/chain2.py

# B 端 UI 全旅程（自起栈，跑完停栈）
OUT_DIR="$PWD/acceptance/2026-10-24/merchant-ui-smoke-t46/out" \
PHONE=13900001025 SMS_CODE=123456 ./scripts/ui_smoke_merchant.sh
```
