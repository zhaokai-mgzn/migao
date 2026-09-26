# 工人端 H5 扫码报工与计件 —— 任意扫一扫工具可用（码 = 标准 HTTPS URL）

> **状态**：**设计单**（docs-only，**不改生产代码、不碰 ai-agent**）。issue **#4716**。
>
> ## 用户裁定（**逐字，本文不得自行改判**）
>
> | # | 日期 | 逐字 | 落法 |
> |---|---|---|---|
> | 裁定① | 2026-09-20 | 「我们现在还缺乏一个**工人扫二维码登录后进行生产&计件**的页面和功能，我希望能支持**微信的扫一扫**能力」 | 工人端页面 + 扫码 → 报工 → 计件 |
> | 裁定② | 2026-09-20 | 「这个页面得设计成 **H5**，**手机 & PAD 端扫码操作**」 | **H5**（不是小程序页面）+ 手机/PAD 两断点 |
> | **裁定③** | 2026-09-20 | 「我们希望用**任意扫一扫工具**都能用，**不要限制死在微信端**」 | ⇒ **码 = 标准 HTTPS URL（唯一形态）**；页面**零 `wx.*`** |
> | 裁定④（澄清） | 2026-09-20 | 「微信的扫一扫功能也能扫吧？别不兼容」 | ⇒ **微信扫一扫是一等公民**（不是"可选便利"）：微信内置浏览器**必须**能走通全链路 |
>
> **裁定③④ 的合并含义（本文的技术选型根）**：
> 码里放 URL ⇒ **任意**扫码工具（微信扫一扫 / 系统相机 / 第三方扫码 App / PAD）扫到都能用**各自的浏览器**打开 ⇒
> **微信扫一扫在列**（扫 URL → 微信内置浏览器打开 → 正常用），**同时**不牺牲非微信环境。两者不冲突，**同一条路径**。
>
> **本单只出设计**：先设计，再动数据。所有「现状」结论均为**实测**（复算命令见 **附录 A**）；
> 无法判定的进 §8.2，不替业务决定的进 §8.4。
>
> **配套真值源 / 既有设计**：
> [set-code-and-scan-loop.md](set-code-and-scan-loop.md)（**#4687**，A 模式闭环 · 一部位一码 · 旧码双读）·
> [worker-scan-terminal.md](worker-scan-terminal.md)（工人扫码终端，**已定稿**）·
> [public-operations-and-craft-ui.md](public-operations-and-craft-ui.md)（**#4675**，两层模型 / 行业术语）·
> [c-end-tenant-domain-routing.md](c-end-tenant-domain-routing.md)（租户域名路由）·
> `docs/curtain-production-rules.md`（生产/计件规则真值源）·
> `docs/wiki/CONTRACT-LEDGER.md`（契约账本）· `docs/wiki/RBAC.md`（权限体系）。

---

## 0. 大白话：今天工人怎么报工（≥4 步）→ 改完几步

### 0.1 今天（**实测**：`frontend/bmini-app/src/pages/production/index/index.tsx`，578 行）

今天的「工人端」= **B 端商家小程序（米宝商家助手）里的生产页**，报工主体是**商家员工账号**：

| # | 动作 | 谁在做 |
|---|---|---|
| 1 | 打开微信 → 进「米宝商家助手」小程序（或从聊天/我的小程序进） | 人 |
| 2 | 登录（首次：`wx.login` + 手机号换号**跨租户匹配员工账号**；匹配不到 ⇒ **拒绝**） | 人 + 系统 |
| 3 | 进「生产」页 → 点【扫码报工】 | 人 |
| 4 | `Taro.scanCode` 扫加工单二维码（**码只到加工单级**：`processing_orders.qr_token`） | 人 |
| 5 | 在工序树里**肉眼找部位**（布帘 / 纱帘 / 帘头） | **人**（系统本该知道） |
| 6 | 在 ~11~14 道工序里**肉眼找该做哪一道** | **人**（系统本该推断） |
| 7 | **手输 / 心算数量** | **人**（算料引擎本该给出） |
| 8 | 点提交 | 人 |

⇒ **≥ 4 步**（issue #4716 的保守口径；实测 UI 上是 8 个动作）。
**病灶**：第 5/6/7 步是**人在做系统该做的事** —— 选错就把进度和钱记到**别人**头上。

### 0.2 改完（本设计 + #4687 闭环）

| # | 动作 | 步数 |
|---|---|---|
| 1 | 用**任意扫一扫**扫纸上的码（码 = `https://<稳定域名>/s/<短码>`） | **1 步** |
| 2 | （**首次**）输工号 + PIN 登录；之后设备记住，**不再有这步** | +2 步（**一次性**） |
| 3 | 看一屏：「**定型 · 布帘 · 应做 11.00 米**」+ 页头「**当前工人：张三**」 | 0 步（系统带出） |
| 4 | 点【**完成**】 | **1 步**（= 记账动作本身，**不是**额外交互） |

⇒ **一次扫码 = 1 步**（裁定②；与 #4687 §4「A 模式：完工必扫、开工不扫，零额外交互」逐条一致）。
**唯一的额外交互**是「**不是这道？改**」—— **只在工人需要时才点**（#4687 §4.1）。

### 0.3 「少掉的 3 步」去哪了（不是"少点一次按钮"）

```
部位  ← 码里带着（一部位一码，#4687 §2.3）
工序  ← 系统推断「下一道待做」+ 一键改（#4687 §3）
数量  ← 默认 = 算料引擎输出，报工只确认（真值源 docs/curtain-production-rules.md 逐字）
```

---

## 1. 四条扫码路径 × 设备/浏览器**可用性矩阵**（**核心难点**）

### 1.1 矩阵（**一屏**）

| 路径 | 手机 · **微信内** | 手机 · 普通浏览器 | **PAD · 普通浏览器** | 前提 | 代价 / 坑 |
|---|---|---|---|---|---|
| **① 扫一扫 → 打开 H5 URL**<br>（**唯一主路径**） | ✅ **微信扫一扫** → 微信内置浏览器打开 → 全链路可用 | ✅ 系统相机 / 第三方扫码 App → 各自浏览器 | ✅ PAD 系统相机 | 码 = **标准 HTTPS URL**；**域名已备案 + HTTPS** | ⚠️ 码**一旦打印就是 URL** ⇒ 换域名 / 改路径会让**旧码失效** ⇒ 见 §1.3（稳定短链）<br>⚠️ 微信对**未备案/风险域名**会拦截或显示警告页（页面直接打不开）<br>⚠️ 部分扫码 App **只显示文本不跳转** ⇒ 见 §1.4（短码兜底）<br>⚠️ **存量旧码（裸 token）不是 URL ⇒ 扫了不跳转** ⇒ 走 ② / ④（§1.5） |
| **② 页面内相机扫码**<br>（`getUserMedia` + JS QR 库）<br>**可选便利，非必经** | ⚠️ **可能不可用** —— iOS 微信 WKWebView 对 `getUserMedia` 有历史性限制 ⇒ **必须显式降级**到 ① 或 ④，**不得**把它当微信内主路径 | ✅ | ✅ **PAD 常驻工位最合适**（免反复掏手机） | **HTTPS** + 用户**授权相机** | ⚠️ 相机权限被拒 ⇒ 降级 ④（§4.6）<br>⚠️ 引入 JS QR 库 = **新依赖**，须过「最少代码」阶梯（§4.6）<br>✅ **额外价值**：能读**存量旧码（裸 token）**——这是 ① 做不到的（§1.5） |
| **③ 页面内调微信 JS-SDK**（`wx.scanQRCode`）<br>**出局** | ✅（需**公众号** + **JS 接口安全域名** + `wx.config` 签名） | ❌ | ❌ **完全不可用** | 公众号 + 域名备案 + JS 安全域名 | **与裁定③ 直接冲突**（页面**不得**依赖任何 `wx.*`）⇒ **本设计不做**。<br>若将来已配公众号，可作**可选增强**另立单，**不得**成为必经路径 |
| **④ 手动输短码**<br>（**兜底，人人可用**） | ✅ | ✅ | ✅ | 码旁**印 6~8 位人可读短码** + 页面**输码入口** | 需抄码/输码（比扫慢）；<br>✅ 旧码可输 **token** / **加工单号**（复用 `resolveOrder` 既有形态，§1.5） |

### 1.2 主路径：**码 = 标准 HTTPS URL（唯一形态）**

| 项 | 设计 | 依据 |
|---|---|---|
| 码内容 | `https://<稳定域名>/s/<短码>` | 裁定③：只有 URL 能让**任意**扫码工具都可用 |
| 码里**不放** | `wx.*` 参数、明文单号拼接串、工序、明文 token | 裁定③（零 `wx.*`）+ #4687 §2.3（**工序不进码**）+ 码量/作废论证 |
| 短码 → 部位 | 服务端解析（§1.3），**不是**客户端解析 | 换框架/改路径不得让旧码失效 |
| 页面 | **纯标准 Web API + HTTPS**，**零 `wx.*`** | 裁定③；PAD 场景天然满足 |

> ⚠️ **与现状的直接冲突（实测）**：今天的二维码内容 = **裸 `qr_token`**，不是 URL ——
> `frontend/admin-web/src/components/production/TaskCardPrint.tsx` 的 `QRCodeSVG` 取 `value={qrToken}`，
> 文件头注释逐字：「二维码内容只放 `qr_token`（token 化、可撤销），**不放单号拼接串**」。
> ⇒ **打印面必须改**（改的是**打印内容**，`qr_token` 列与撤销语义**一字不动**）。见 §6 C1。

### 1.3 🔴 **URL 稳定性 = 印刷品红线**（**最容易被忽略、代价最大**）

**问题**：码打印贴到实物上（筐 / 流水线 / 工件）**不可能回收重印**。
若码里写的是「当前页面路径」，那么**换域名 / 改路径 / 换前端框架**都会让**已打印的码全部失效**。

**解法（一条）**：**稳定短链 + 服务端 302 重定向**。

```
纸上的码（永不变）          服务端（可变）                     实际页面（随便换）
https://app.migaozn.com/s/7K3M9QP2  ──302──▶  https://app.migaozn.com/w/?t=<token>
                     │                                    │
        稳定域名 + 稳定路径段 /s/            ← 换框架/改路径只改这一跳的目标
```

| 项 | 设计 | 理由 |
|---|---|---|
| 稳定域名 | **复用 `app.migaozn.com`**（实测已在用：C 端 H5 / 小程序合法域名 / nginx 已分流） | **不引新域名** —— 新域名 = 重新备案 = 已打印的码的额外风险 |
| 稳定路径段 | `/s/<短码>`（服务端路由，**不是**前端路由） | 「换前端框架」时前端路由会变，服务端路由不会 |
| 重定向目标 | 当前报工页（`/w/...`，带 token） | **只改这一跳** ⇒ 已打印的码继续有效 |
| 谁实现 | **admin-api 新增端点** `GET /s/{shortCode}`（302）+ SecurityConfig 的 `permitAll` 列表**追加一条路径** | 短码 → token 要查库 ⇒ nginx 做不到；「只加不改」见 §7 |
| 码的寿命 | **长寿命**（印刷品）+ **可撤销** | 撤销复用既有语义（§1.3.1） |

#### 1.3.1 撤销语义（**逐字复用**，不新造）

| 既有机制 | 处置 |
|---|---|
| `processing_orders.qr_token` 撤销 = `UPDATE … SET qr_token = NULL` | **一字不动**（既有 `ProcessingOrderMapper.revokeQrToken`；注释逐字：「置 NULL 而不是换一个新 token：撤销的语义是「这张纸作废」」） |
| 新 token（#4687 §2.3 的 `processing_set_part_tokens.token`） | **同款语义**：撤销 = 置 NULL，**不换新 token** |
| `/s/{短码}` 解析 | 要求 `token IS NOT NULL AND deleted = 0` ⇒ 撤销后**解析不到** ⇒ **410/404**（**不得**静默回落到别的码） |

> 🔴 **撤销后必须 404/410 的断言**（红证形态）：撤销第 N 套·布帘的码 ⇒ 扫它 ⇒ **必须** 410/404；
> 若仍能打开报工页 ⇒ **红**。**反向**：删掉该断言 ⇒ 该测试必须变红（不会红的断言 = 空断言）。

### 1.4 人可读短码（**不是可选项**）

**为什么必须有**（车间现实，四条）：
① 「任意扫码工具」意味着**也可能扫了不跳转**（部分 App 只显示文本）；
② 码**磨损 / 脏污**；
③ **相机坏 / 权限被拒**；
④ 工人手上可能**根本没有扫码工具**（PAD 场景下页面已打开，只差输码）。

| 项 | 设计 |
|---|---|
| 形态 | **6~8 位**（建议 **8 位**），字符集 = **Crockford Base32**（去掉 `I` / `L` / `O` / `U` 四个易混字符） |
| **一码两用** | 同一串**既是 URL 路径段**（`/s/<短码>`），**也是纸面印的人可读短码** ⇒ 手输 = 扫码，**同一入口、零分叉** |
| 生成 | **随机**（**不是**顺序号 —— 顺序可枚举） |
| 唯一 | `UNIQUE(short_code) WHERE deleted = 0` + 碰撞重试（**不静默造重码**） |
| 落点 | `processing_set_part_tokens` **追加一列** `short_code`（不改 #4687 冻结的 `token` 形态：`VARCHAR(64)` / 32 位 UUID 去横线） |
| 页面入口 | 报工页首屏有「**输码**」入口（与扫码并列，**不是**藏在二级页） |
| 接受什么 | ① 短码（新码）② **裸 token**（存量旧码）③ **加工单号** ④ 订单号（②③④ 复用 `resolveOrder` 既有形态） |

> ⚠️ **为什么不把 URL 写成 `/s/<token>`**：token 是 32 位十六进制 ⇒ 手输 32 字符 = **不可用** ⇒
> 不满足「人可读短码」这条硬约束。**两个标识符各有分工**：`token` = 机器标识（#4687 冻结形态），
> `short_code` = 人可读入口。**这不是"第二套编号"**（#4687 §13 禁的是套号的第二套编号），
> 而是同一行记录的**两种表示**。

### 1.5 与 #4687 §2.6「**旧码双读**」的对齐（**新旧码 × 四条路径**）

| 码的世代 | 内容 | ① 扫一扫 | ② 页面内相机 | ④ 手输 |
|---|---|---|---|---|
| **新码**（#4687 落码后打印） | `https://<稳定域名>/s/<短码>` | ✅ 直达报工页 | ✅ | ✅ 输短码 |
| **存量旧码**（今天已打印） | **裸 `qr_token`**（不是 URL） | ❌ **扫了不跳转**（扫码工具只显示文本） | ✅ **能读**（复用 `productionQr.ts` 的三形态容错解析） | ✅ 输 token / 加工单号 |
| 手输兜底（任何世代） | 加工单号 / 订单号 | — | — | ✅ 复用 `resolveOrder` ④ / ② 形态 |

**旧码命中后的行为（逐字继承 #4687 §2.6，不改判）**：

- 返回**降级形态**：`{granularity: "order", set_no: null, position: null, …}` + `needs_selection: ["set", "position"]` + 可选清单；
- 🔴 **绝不默认取第 1 套**（默认 = 静默把进度记到错的套上，**正是要治的病**）；
- 旧码**不设强制失效日**（强制失效会打断在产单）；撤销端点（既有）提供「立即作废」的手动出路。

> 🔴 **本节的核心洞察（决定 ② 的存在价值）**：
> **① 对旧码无效**（旧码不是 URL）。所以 **② 不是"便利"，而是"读旧码"的唯一扫码路径**；
> **④ 是所有世代共用的最后兜底**。三条**互补**，不是三选一。

### 1.6 页面**零 `wx.*`** 纪律（可执行）

| 断言 | 红证形态 |
|---|---|
| 报工页源码/产物**不含** `wx.` / `WeixinJSBridge` / `jweixin` | 注入一行 `wx.config(...)` ⇒ **必红** |
| 页面在**无微信 UA**下功能**不降级**（登录/扫码/报工/计件全通） | 断言依赖微信 UA 分支 ⇒ **必红** |
| 「微信一键登录」按钮**仅在**检测到微信 UA **时额外**出现，**且**主路径（工号+PIN）**在微信内同样可用** | 断言「微信内只显示一键登录」⇒ **必红**（违反裁定④ 的硬约束②） |

---

## 2. 登录 / 身份 —— **必须两条腿**（H5 的必然要求）

### 2.1 腿 A（**主路径**，与浏览器无关）

| 项 | 设计 |
|---|---|
| 方式 | **工号 + PIN**（首选）；或 **一次性邀请码 + 设备记住登录**（新工人首次） |
| 为什么是主路径 | 裁定③：主路径**不得依赖微信授权**（PAD 普通浏览器**没有**微信授权）；裁定④②：**微信内也必须可用** |
| 工号 | 租户内唯一（`UNIQUE(tenant_id, worker_no) WHERE deleted = 0`） |
| PIN | **复用 `users.password_hash`**（BCrypt 哈希）—— **零新列** |
| 设备记住 | 长期 refresh token 落设备 `localStorage` + 服务端 `worker_sessions` 行（§3） |
| 端点 | **新增** `POST /api/worker/login`（工号 + PIN）、`POST /api/worker/session/refresh`、`POST /api/worker/session/logout` |

### 2.2 腿 B（**额外**的「微信一键登录」）

| 项 | 设计 | ⚠️ 实测现状 |
|---|---|---|
| 方式 | 微信网页授权（`snsapi_base` 拿 openid） | 🔴 **`AuthService.buildWechatH5AuthorizeUrl` 与 `handleWechatH5Callback` 是占位实现**：两处**逐字抛** `BusinessException("NOT_IMPLEMENTED", "微信公众号 OAuth 尚未实现", 501)` |
| 端点 | `GET /api/auth/h5/authorize` + `GET /api/auth/h5/callback` | ✅ 端点**已存在**且在 SecurityConfig 的 `permitAll` 列表里 —— 但**服务层是 501** |
| 配置 | 需**公众号 AppID/Secret** | 🔴 **不存在**：`backend/admin-api/src/main/resources/application.yml` 的 `wechat:` 只有 `mini.appid/secret` + `bmini.appid/secret` + `mock-enabled`，**无公众号段** |
| 定位 | **额外**的「一键登录」，**不得**成为唯一路径 | 裁定③② |

> 🔴 **必须更正的假设**：issue #4716 body 写「✅ 有基础：`AuthController` / `AuthService` / …（bmini/mini 两端的微信登录链路存在）」——
> **小程序侧成立**（`POST /api/auth/bmini/login`、`POST /api/auth/mini/login` 可用），
> **但 H5 网页授权不成立**（501 占位 + 无公众号配置）。⇒ 腿 B 是**新增工作**，不是「复用一条已实现的链路」。见 §8.3。

**真正能复用的部分（不新造第二套）**：

| 复用点 | 实测形态 |
|---|---|
| `user_identities` 表 | `id` / `tenant_id` / `user_id` / `identity_type` / `app_id` / `openid` / `unionid` / … |
| 🔑 `identity_type` 取值域 | `docs/sql/schema.sql` 列注释逐字：`-- wechat_mini / wechat_mp / password` ⇒ **`wechat_mp`（公众号）就是为此预留的** ⇒ **零新枚举值** |
| 绑定模式 | `AuthService.findOrCreateMiniProgramUser` 的「openid + tenantId 查身份 → 命中即用 / 未命中建号」模式 |
| JWT 签发 | `JwtTokenProvider.generateAccessToken(userId, tenantId, username, roles, permissions)` —— 工人 token 走**同一签发器**，`roles=["worker"]` + `permissions=[]` |

### 2.3 两条腿落到**同一个「工人」身份**（计件归属的唯一根）

**设计：复用 `users` + `user_identities`（不新造第二套身份表）**

```
users (role='worker', permissions=[], worker_no=<工号>, password_hash=<PIN 的 BCrypt>)
   ├── user_identities (identity_type='password')       ← 腿 A（工号 + PIN）
   └── user_identities (identity_type='wechat_mp')      ← 腿 B（微信网页授权 openid）
                          ↑ 两条腿 → 同一行 users ⇒ 同一个 worker_id ⇒ 计件归属唯一根
```

| 决策 | 取舍 |
|---|---|
| **复用 `users`** | ✅ 硬约束「复用既有 `UserIdentity` 链路，**别新造第二套**」；✅ `password_hash` 直接承载 PIN（**零新列**）；✅ `user_identities.user_id NOT NULL REFERENCES users(id)`（实测）⇒ **本来就必须有 `users` 行**，另立 `workers` 表反而要新造第二套绑定表 |
| **新增 `users.worker_no` 列** | 唯一必需的 schema 增量（工号）；`UNIQUE(tenant_id, worker_no) WHERE deleted = 0` |
| **不新增 `identity_type` 值** | `wechat_mp` 已在列注释取值域里（§2.2） |
| **代价（必须登记）** | 工人成为 `users` 行 ⇒ 与 `/api/admin/**` 门禁冲突（§2.4） |

### 2.4 🔴 **工人 ≠ 商家用户**（权限分层 —— 实测冲突，必须显式处置）

**实测的三条事实**：

| # | 事实 | 出处（仓库相对全路径） |
|---|---|---|
| P1 | 报工端点挂在 **`/api/admin/**`** 下，且类级 `@RequirePermission("order:list")` | `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java` |
| P2 | `/api/admin/**` 的门禁：`customer`/`agent` **一律 403**；**其余角色视为商户员工角色，允许进入**，细粒度由 `@RequirePermission` 拦 | `backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java` 的 `adminApiAuthorizationManager` |
| P3 | **10 个 controller 完全没有 `@RequirePermission`**（其中 `/api/admin/user`、`/api/admin/menus` 在 `/api/admin/**` 下） | 实测计数见 附录 A A6 |

**⇒ 冲突**：工人若持 `role='worker'`，P2 的第三分支会**放行进入 `/api/admin/**`**；
`permissions=[]` 只能保证**带 `@RequirePermission` 的端点 403**，**拦不住 P3 那批**。

**处置（推荐，最小必要改动）**：

| # | 动作 | 形态 |
|---|---|---|
| ① | 报工走**新路径** `/api/worker/**`（**新 controller**） | `/api/worker/**` **不匹配** `/api/admin/**` ⇒ 落到既有的 `.anyRequest().authenticated()` ⇒ **SecurityConfig 的既有分支一字不动** |
| ② | `adminApiAuthorizationManager` 的**拒绝集合追加一个角色码** `worker` | **只加一个元素**，既有三个分支逻辑**一字不改**（与「只加不改」的最小偏离，**必须登记**） |
| ③ | 工人 JWT：`roles=["worker"]`，`permissions=[]`（**零商家权限码**） | 断言：工人 token 调 `/api/admin/**` 任一端点 ⇒ **403**（含 P3 那批） |

> 🔴 **断言（红证形态）**：工人 token 请求 `/api/admin/user/info` 与 `/api/admin/menus` ⇒ **必须 403**。
> 若 200 ⇒ **红**（这就是「给了工人商家权限」的确切形态）。
> **反向**：把 ② 回退 ⇒ 该测试必须变红。

**「不许给工人商家权限」的可执行判据（三条，缺一不可）**：

1. 工人 JWT 的 `permissions` 恒为 `[]`（**断言**：签发处硬编码空列表，且不接受入参注入）；
2. `/api/admin/**` 对 `worker` 角色 **403**（断言 + 红证如上）；
3. 工人可达的端点**只有** `/api/worker/**`（断言：用工人 token 遍历 controller 映射，非 `/api/worker/**` 全 403）。

### 2.5 绑定 / 解绑 / 停用 / 换人 / 换手机 / 跨租户（**逐条口径 + 审计**）

| 场景 | 口径 | 审计 |
|---|---|---|
| **首次绑定**（工号+PIN 首登，或微信首登） | 工号+PIN：验证通过即绑定 `user_identities(password)`；微信：openid 未绑定 ⇒ **不自动建工人**，要求**先输工号 + PIN 完成绑定**（**绝不**「扫个码就给你一个工人身份」） | 绑定写 `worker_binding_audits`（只追加：`worker_id` / `identity_type` / `openid`（脱敏）/ `bound_at` / `bound_by` / `approved_by`） |
| **解绑**（换微信 / 换手机） | 置 `user_identities.deleted = 1`（**软删**，不物理删）⇒ 旧 openid 立即失效；**同一时刻一个 `identity_type` 只允许一条活跃绑定** | 同上表，`action='unbind'` + `reason` |
| **停用**（离职 / 停职） | `users.status = 'disabled'` ⇒ **登录拒绝 + 既有 session 全部 `ended_at` 落 `end_reason='revoked'`** | 同上表，`action='disable'` |
| **换人**（同一台 PAD 换工人） | 见 §3.2（**快速切换**）；**不是**解绑，是**新 session** | `worker_sessions.end_reason='switched'` |
| **换手机** | 腿 A：新设备登录即新 session（旧的靠 §3.3 超时自然退场）；腿 B：需**先解绑再重绑**（openid 变了） | 同绑定审计 |
| **一个工人多租户（跨商家打工）** | **工人档案按租户隔离**（`users.tenant_id`）⇒ 同一自然人跨商家 = **两条工人档案**；可用 `phone` / `unionid` 做「同人」**识别辅助**，但 🔴 **计件归属只按租户内的 `worker_id`**（**不跨租户合并工资**） | 登记为**待裁定**（§8.4 R1） |

> ⚠️ **绑定必须有审计**（issue #4716 要求「谁绑的、何时、由谁批准」）⇒ `worker_binding_audits` **只追加**。

---

## 3. 🔴 **共用 PAD 的计件归属风险**（H5 + PAD 最容易出事处）

> **病灶**：车间 PAD 常是**多工人共用**一台。若「登录一次就一直算这个人」⇒
> **把 A 的活记到 B 头上 ⇒ 发错工资**（本仓最忌的**静默**错误）。

### 3.1 提交前确认身份（**页面显示"当前工人：张三"**）

| 项 | 设计 |
|---|---|
| 显示 | 报工页**页头常驻**「当前工人：**张三**」（+ 工号），与【完成】按钮**同屏可见** |
| 数据来源 | **服务端 session**（`worker_sessions.worker_id`），**不是**前端 state |
| 🔴 服务端纪律 | 报工请求**只带 `X-Worker-Session-Id`**；`worker_id` **由服务端从 session 解出**，**绝不接受 body 里的 `worker_id`** |
| 理由 | 前端可被改；`production_work_logs.worker_id` 是**工资凭证** |

> 🔴 **断言（红证）**：body 里塞**别人的** `worker_id` ⇒ 落库的 `worker_id` **仍等于 session 的工人**。
> 若落库 = body 值 ⇒ **红**。

### 3.2 快速切换工人（PAD 上**一步**切换，**不必重扫**）

| 项 | 设计 |
|---|---|
| 交互 | 页头「当前工人：张三」**可点** ⇒ 弹出「切换工人」（工号 + PIN / 或已记住设备的工人列表一键切）⇒ **一步**回到同一屏 |
| 🔴 关键 | **不丢当前扫码上下文**（切完仍在「定型 · 布帘 · 应做 11.00 米」那一屏）⇒ **不必重扫** |
| 服务端 | `POST /api/worker/session/switch`：结束旧 session（`end_reason='switched'`）+ 建新 session；**返回新的 `X-Worker-Session-Id`** |
| 防呆 | 切换后**旧 session id 立即失效** ⇒ 用旧 id 报工 ⇒ **401/403**（不静默记到旧工人） |

> 🔴 **断言（红证）**：切换后**用旧 session id** 报工 ⇒ **必须 401/403**；若成功落库（记到旧工人）⇒ **红**。

### 3.3 自动登出 / 超时（闲置 N 分钟回落）

| 项 | 设计 |
|---|---|
| 默认 | **闲置 15 分钟** ⇒ 回落登录页（**租户可配**；数值本身列为待裁定，§8.4 R2） |
| 落点 | `worker_sessions.idle_expires_at`；每次成功请求刷新 `last_seen_at` + 顺延 `idle_expires_at` |
| 服务端 | 过期 session ⇒ 报工 **401**（**不静默续期**） |
| 前端 | 定时器 + `visibilitychange` 双保险（PAD 常被切到别的 App ⇒ **不能只靠定时器**） |
| 断网时 | 离线队列的**补传**若因 session 过期被拒 ⇒ **出队 + 显式回报**（不得静默丢单，复用 `productionOffline.ts` 的 `RejectedReport` 口径） |

> 🔴 **断言（红证）**：过期 session 报工 ⇒ **401**；若成功 ⇒ **红**。

### 3.4 每笔计件留 `worker_id` 快照（谁做的 / 何时 / **由哪个设备会话**）

| 需求 | 落点 | 今天有吗 |
|---|---|---|
| **谁做的** | `production_work_logs.worker_id` + `worker_name` | ✅ **已有**（`ProductionWorkLog` 实体实测）⇒ **复用**，不新造 |
| **何时** | `production_work_logs.created_at` + `work_date` | ✅ **已有** |
| **由哪个设备/会话** | 🔴 **不能**写进 `production_work_logs`（**红线**：#4687 §13 + `docs/design/worker-scan-terminal.md` §7 逐字「不改 `production_work_logs`」）⇒ **新增只追加旁路表** `worker_report_audits` | ❌ **无** |

**`worker_report_audits`（只追加，1:1 挂一次报工动作）**：

| 列 | 语义 |
|---|---|
| `client_request_id` | **复用既有幂等键**（`X-Client-Request-Id`，`ClientRequestIdService` 的 `(tenant_id, client_request_id)`）⇒ 与报工行**天然 1:1** |
| `tenant_id` / `work_log_id` / `worker_id` | 归属与关联 |
| `worker_session_id` | **由哪个会话**（→ `worker_sessions`） |
| `device_label` | 设备标签（PAD-车间-01 之类，登录时登记） |
| `created_at` | 落库时刻 |

> **为什么用旁路表而不是加列**：加列 = 改 `production_work_logs` = **踩红线**（明细不可变 + 既有冻结契约）。
> 旁路表**只追加**，删除它不影响工资口径（**报工明细仍是唯一凭证**）。

### 3.5 纠错必须留痕（**不许静默改历史**）

| 项 | 设计 |
|---|---|
| 允许改的字段（**白名单**） | `worker_id` / `worker_name` / `qty` / `qualified_qty` / `work_type` / `work_date` |
| 🔴 **禁止改的字段** | **`unit_price`** / **`factor`** / `id` / `tenant_id` / `processing_order_id` / `operation_id` / `created_at` |
| 留痕表 | **新增只追加** `production_work_log_corrections`：`work_log_id` / `field` / `old_value` / `new_value` / `reason`（**必填**）/ `operator_id` / `created_at` |
| 原子性 | 改字段 + 插留痕 **同一事务**（缺任一 ⇒ 回滚） |
| 谁可以做 | **管理端**（商家 / 班组长），**不是**工人本人（工人无权限码，§2.4） |
| 理由必填 | `reason` 空白 ⇒ **拒绝**（422），**不静默** |

### 3.6 🔴 **红线**：历史 `production_work_logs.unit_price` + `factor` **一字不动**

| 事实 | 出处 |
|---|---|
| 计件金额在**报工那一刻固化**：单价从工序实例取一次写进报工行快照，**聚合永不回查实例** | `ProductionWorkLog` 实体的 `unitPrice` 注释（issue #4351） |
| `factor` 列**保留**但自 #4589 起**无人写它** | `ProductionService.doReport` 注释逐字 |
| 未定价**不按 0 计件**：`price_state` 三态（V90，issue #4696） | `ProductionWorkLog.priceState` + `ProductionService` 的 `PRICE_STATE_*` |

⇒ **本设计的任何纠错/归属修正路径，都不得触碰这两列的**历史值**。

> 🔴 **断言（红证，两条）**：
> ① 纠错端点传 `unit_price` / `factor` ⇒ **必须 422/403 拒绝**；若接受 ⇒ **红**。
> ② 集成断言：纠错**前后** `SELECT unit_price, factor FROM production_work_logs WHERE id = ?` **逐字相等**；不等 ⇒ **红**。

### 3.7 逐条口径 ⇒ **可执行断言**（汇总，**每条必须能红**）

| # | 口径 | 断言 | 红证形态 |
|---|---|---|---|
| W1 | 提交前确认身份 | 页头常驻「当前工人：<name>」；服务端从 session 解 `worker_id`，**忽略 body** | body 传别人的 `worker_id` ⇒ 落库仍是 session 的；落 body 值 ⇒ **红** |
| W2 | 快速切换工人 | 切换后旧 session id **立即失效**；**不丢扫码上下文** | 旧 id 仍能报工 ⇒ **红**；切换后回到首页（丢上下文）⇒ **红** |
| W3 | 自动登出/超时 | 过期 session 报工 ⇒ **401**（不静默续期） | 过期仍成功 ⇒ **红** |
| W4 | 每笔留 `worker_id` 快照 | 报工行有 `worker_id` + `worker_report_audits` 有 1:1 行 | 删掉 audits 写入 ⇒ 该断言**必红** |
| W5 | 纠错留痕 | 改字段**必须**同事务插留痕（`reason` 必填） | 改字段无留痕行 ⇒ **红**；`reason` 空被接受 ⇒ **红** |
| W6 | 🔴 `unit_price`+`factor` 一字不动 | 纠错白名单外字段被拒 + 前后逐字相等 | 接受改 `unit_price` ⇒ **红** |
| W7 | 工人零商家权限 | 工人 token 调 `/api/admin/**`（含无 `@RequirePermission` 的那批）⇒ **403** | 任一 200 ⇒ **红** |
| W8 | 撤销后短链失效 | 撤销 ⇒ `/s/{短码}` ⇒ **410/404**（不回落） | 仍打开报工页 ⇒ **红** |
| W9 | 旧码不默认取第 1 套 | 旧码 ⇒ `granularity="order"` + `needs_selection` | 旧码直接落到第 1 套 ⇒ **红** |

---

## 4. H5 工程前提清单

### 4.1 域名 / HTTPS / 备案

| 项 | 设计 | 今天有吗 |
|---|---|---|
| **HTTPS** | 必需（`getUserMedia` 与安全上下文都要求） | ✅ 已有（实测域名均 https） |
| **稳定域名** | 复用 **`app.migaozn.com`**（已在用：C 端 H5 / 小程序合法域名 / nginx 已分流） | ✅ 已有 |
| **ICP 备案** | **必需**（微信对未备案/风险域名会**拦截或显示警告页** ⇒ 页面直接打不开） | ✅ **已备案**（用户裁定，2026-09-20；原「无法判定」见 §8.2 U1 的改判） |
| **域名稳定** | 与 §1.3「稳定短链」同一条要求 | 设计约束 |
| **微信风控** | 避免诱导分享/外链跳转等被拦行为 | 设计约束 |

### 4.2 响应式两断点（**手机 / PAD**）

| 断点 | 目标 | 关键约束 |
|---|---|---|
| **手机**（< 768px） | 单手可操作 | 【完成】按钮**底部固定**、触控目标 ≥ 44×44 px |
| **PAD**（≥ 768px） | **远距离可点**（PAD 常固定在工位支架上，工人站着/隔一段距离点） | 字号与按钮**显著放大**（建议主按钮高度 ≥ 88px、正文 ≥ 20px）；**一屏之内**放下「工序 + 应做数量 + 【完成】」（**不滚动**） |

> 🔴 **断言（红证）**：PAD 断点下主按钮的**渲染尺寸** ≥ 阈值；把字号改回手机档 ⇒ **必红**。

### 4.3 浏览器兼容（含**微信内置 X5 / WKWebView**）

| 环境 | 要求 |
|---|---|
| **微信内置浏览器**（iOS WKWebView / Android X5） | ✅ **必须全链路可用**（裁定④）：微信扫一扫 → 打开页面 → 登录 → 报工 → 计件 |
| 通用移动浏览器（Chrome / Safari / Android WebView） | ✅ **不得比微信内更差** |
| **in-app webview**（部分扫码 App 内置） | ✅ 可用（纯标准 Web API ⇒ 天然兼容） |
| PAD 浏览器 | ✅ 可用 |
| 🔴 纪律 | **零 `wx.*`**（§1.6）；不依赖微信特有 API/字体/布局 |

### 4.4 弱网 / 离线（**复用 bmini-app 既有口径，不新造**）

**既有实现（实测）**：`frontend/bmini-app/src/utils/productionOffline.ts`（issue #4206；真值源 `docs/curtain-production-rules.md` §5 逐字「【默】弱网降级：扫码页缓存待做清单，离线报工补传」）。

| 能力 | 既有口径（**逐字复用**） | H5 的差异 |
|---|---|---|
| **待做清单缓存** | `loadOrder` 成功即落盘；断网命中缓存仍出清单；**调用方必须显式标注离线**（不得把缓存冒充服务端真值） | 存储从 `Taro.setStorageSync` 换 `localStorage`/`IndexedDB` |
| **离线报工队列** | 仅**传输层**失败（**无 HTTP 状态码**）入队；**业务拒绝不入队**（服务端已答复且已 `discard` 释放幂等键 ⇒ 重发会真再执行一次） | 同 |
| **🔑 幂等键语义** | 入队时把**本次动作的** `requestId` 一起持久化，补传**复用同一个键**（服务端 `ClientRequestIdService` 按 `(tenant_id, client_request_id)` 去重，同键只回放首次结果）。**若补传时重新生成键 ⇒ 同一次报工被当两次首执 ⇒ `done_qty` 翻倍、计件虚高** | 同（**最关键的一处，错了就重复计件**） |
| **排队** | 按入队顺序逐条重发；传输层失败 ⇒ **停止本轮**（还在断网，继续发只是白等） | 同 |
| **去重** | 同 `requestId` **不重复入队**；本机明细同 `requestId` **只能有一行** | 同 |
| **冲突** | `advanceDoneQtyIfUnchanged` 的 CAS：影响行数 0 ⇒ **409 `OPERATION_ALREADY_ADVANCED`**（fail-closed，**绝不静默覆盖别人的报工**） | 同（服务端不变） |
| **补报** | 补传被**业务拒绝** ⇒ **出队 + 回报原因**（`RejectedReport`，**不得静默丢单**） | 同 |
| **本机明细** | `production:work-logs:<orderId>`，**上限 50 条** | 同口径（换存储） |

> ⚠️ **H5 特有的一条**：`localStorage` **多标签页共享** ⇒ PAD 上开两个标签会互踩队列。
> ⇒ 队列读写**加锁**（`navigator.locks` 或 storage 上的乐观锁版本号），并**登记为设计约束**（§8.4 R3）。

### 4.5 页面**不依赖微信**也能用（PAD 场景）

- 登录：腿 A（工号 + PIN）**在任何浏览器**可用（§2.1）；
- 扫码：① / ② / ④ 三条都不需要微信（§1.1）；
- 报工/计件：纯 HTTPS API。

### 4.6 相机权限被拒 ⇒ 降级到 ④ 手动输码

| 情形 | 降级 |
|---|---|
| 权限被拒 / 无相机 / 非 HTTPS | ② 不可用 ⇒ 页面**显式提示** + 引导到 ①（用扫码工具）或 ④（输短码） |
| 微信内 `getUserMedia` 不可用 | 同上（**必须显式降级**，不得白屏/静默失败） |
| 页面内扫码的**依赖** | JS QR 库 = **新依赖** ⇒ 须过「最少代码」阶梯（`docs/wiki/Code-Minimalism.md`）：<br>① YAGNI：**PAD 常驻工位**是真需求 ⇒ 保留；<br>② 复用：优先**复用** `frontend/bmini-app/src/utils/productionQr.ts` 的**解析**逻辑（纯函数，与 Taro 无关）；<br>③ 解码库：选**体积最小**且活跃维护的一个，**不引整个扫码 SDK** |

### 4.7 工程前提清单（汇总表）

| # | 前提 | 今天有吗 | 谁负责 |
|---|---|---|---|
| 1 | HTTPS 域名 | ✅ | 已有 |
| 2 | **ICP 备案** | ✅ **已备案**（用户裁定） | —（风险解除） |
| 3 | 稳定短链 + 服务端重定向 | ✅ **已落（issue #4802）** | 已落码：`GET /s/{短码}` ⇒ 服务端 **302** 到 `/w/?t=<token>&tenant_id=<id>`（§1.3） |
| 4 | 人可读短码 + 输码入口 | ✅ **已落**（短码 = issue #4802；输码入口 = issue #4765） | 已落码：**8 位 Crockford Base32**（避开 `0/O`、`1/I/L`），与 `token` 同行两种表示（§1.4） |
| 5 | 响应式两断点 | ❌ 待建 | 前端 |
| 6 | 零 `wx.*` | 设计约束 | 前端 |
| 7 | 弱网/离线（复用口径） | ✅ 口径已有（bmini-app）；H5 需换存储实现 | 前端 |
| 8 | 工号+PIN 登录 | ✅ **已落码（issue #4733）**；**建号入口**已落码（issue #4869） | 后端：登录 = `POST /api/worker/login`（`backend/admin-api/src/main/java/com/migao/admin/worker/WorkerSessionService.java` 的 `login`，PIN 走 BCrypt 比对 + `LoginFailureGuard` 防爆破 #5531）；**工人档案从哪来** = `POST /api/admin/workers` + 员工管理页「工人档案」面（见 §9.3 D7）。<br>⚠️ 原文「❌ 待建（`users.worker_no` 新列）」写于 #4733 落码之前，属**已修未销账**（本行按 issue #4869 销账，不改历史结论） |
| 9 | 微信网页授权（**额外**） | ❌ **501 占位 + 无公众号配置** | 后端 + 运维（§2.2） |
| 10 | `/api/worker/**` 门禁 | ✅ **已落码（issue #4733；拒绝集合由 #4727 预留）** | 后端（§2.4）：工人可达面 = `/api/worker/**`；`/api/admin/**` 走 `SecurityConfig` 的 `adminApiAuthorizationManager()`，其拒绝集合 `ADMIN_API_REJECTED_ROLES` 含 `customer` / `agent` / **`worker`**（工人身份一票否决）。<br>⚠️ 原「❌ 待建」同上属**已修未销账**——改判只追加结论，原文结论不改写 |

---

## 5. 报工页：**A 模式闭环的 H5 落地**（#4687 §4 逐条落）

### 5.1 一屏（扫 ⇒ 一屏 ⇒ 【开工】）

> 🔴 **2026-09-21 语义改判（issue #4967，用户逐字裁定①）**：扫码 = **开工 / 领活**（真实车间
> 「先扫码领活 → 再生产；完工不扫」）⇒ 按钮文案由【完成】改为【开工】。**记账时点与端点一字未变**。
> 下方 ASCII 图里的【 完 成 】是**改判前**的原文（**保留不删**），并在同一图内标注改后形态与
> 新增的「本套工序明细」。改判全貌见 `docs/design/set-code-and-scan-loop.md` 的 §4.1 改判块与 §11.5。

```
① 扫 / 输码 → 服务端解析（新 token 优先，未命中回落旧 qr_token 四形态，§1.5）
② 系统推断「下一道待做」工序（#4687 §3.2，含套级回落 rerouted）
③ 一屏显示：
     ┌──────────────────────────────────────┐
     │ 当前工人：张三（工号 A017）    [切换] │   ← §3.1 / §3.2
     ├──────────────────────────────────────┤
     │ 第 14 套 · 布帘                       │
     │ 定型 · 布帘                           │
     │ 应做 11.00 米                         │
     │                     【 开 工 】        │   ← 一个大按钮（改判前原文 =【 完 成 】）
     │ 不是这道？改                          │   ← 一键改（#4687 §3.3）
     ├──────────────────────────────────────┤
     │ 第 14 套 · 本套工序                    │   ← issue #4967 交付物 2（本套 → 部位 → 工序）
     │  布帘                                 │
     │   定型 · 应做 11.00 米 ¥3.50/米 待领 已报 0.00 米 │
     │   打卷 · 应做 1.00 套  未定价   待领 已报 0.00 套 │
     │  纱帘                                 │
     │   定型 · 应做 4.00 米  ¥2.00/米 已领 已报 4.00 米 │
     └──────────────────────────────────────┘
④ 点【开工】（= 领活）→ 一次事务（§5.2）
⑤ 返回：本道完成 + 本套进度 + 本单累计计件 + 下一道是什么 + **本套工序明细**（原样透传）
```

**本套工序明细的口径（issue #4967 交付物 2）**：数据**只**来自解析响应的 `set_overview`
（`ProductionScanService#setOverview`，与推断/进度/卡点**同源**）；回执**原样透传**同一份。
页面**不**自己聚合、也不另拉 `GET /api/worker/production/orders/{orderId}/operations` 再按套重排
（那就是**第二份口径**：部位名怎么取 / 算不算已完成的道 / 按什么排序 —— 两处迟早不同）。
🔴 **缺值不渲染**：`set_overview` 缺失 / `positions` 为空 / 工序缺 `operation_id` ⇒ 整块（或该行）不出现
（绝不渲染「undefined 米 / ¥NaN」）；`unit_price` 为 `null` = **未定价**（≠ 0 元，issue #4696）。

### 5.2 **一次事务**（#4687 §4.2 方案 A，**逐条落**）

| # | 动作 | 落点 |
|---|---|---|
| ⓪ | **幂等占位**（`X-Client-Request-Id`，**逐字复用** `ClientRequestIdService`） | 占位**在外层**（与既有 `report` 同款） |
| ① | 解析 → `(set_id, order_item_id)` + 校验工序归属（防呆④） | — |
| ② | **定工序**：显式 `operation_id` 则校验归属；否则 §3.2 推断 ⇒ 零道/多道 ⇒ **拒绝**（防呆⑤） | — |
| ③ | 防呆：幂等 / 数量上限（**拒绝不 clamp**）/ 非本部位码 | ⚠️ **不校验前道**（#4694 裁定） |
| ④ | **同事务**：insert `work_logs` → **写 `started_at` / `worker_id` / `worker_name`（领活时刻与领活人，issue #4967 转正）** → CAS 推进 `done_qty` + `done_at` → 全部活跃工序实例报满 ⇒ 加工单 `completed`（#4961 口径） → 首工序 ⇒ `in_processing` | **新增 `@Transactional` 的 `completeByScan(...)`**；**不改** 既有 `report`（它刻意不加 `@Transactional`）。🔴 `started_at` 用 `COALESCE` ⇒ 只有**第一次**领活落笔 |
| ⑤ | 追加 `worker_report_audits`（§3.4，**同事务**） | 新表 |

### 5.3 防呆逐条（#4687 §5.3，**含本设计对 H5 的增量**）

| # | 防呆 | H5 增量 |
|---|---|---|
| ① | **幂等**（同键回放 `replayed=true`） | ✅ 复用；**离线补传复用同一键**（§4.4） |
| ② | **越站**⇒ **不拦**（#4694 已删闸门），推断时自然避开 | 无 |
| ③ | **数量上限**（`done_qty + 本次合格数 ≤ qty`，**拒绝不 clamp**） | 无 |
| ④ | **非本部位码**（`op.order_item_id == token.order_item_id`） | 🔴 **H5 必须**：手输短码/旧码路径**同样**要过这条（**不是**"手输就放行"） |
| ⑤ | 🔴 **工序必须确定**（写 `work_logs` 前 `operation_id` **唯一确定**） | 🔴 **H5 必须**：`OPERATION_AMBIGUOUS` / `NO_PENDING_OPERATION` ⇒ **拒绝且不记账** |
| **⑥（本设计新增）** | **身份必须确定**：`worker_id` 从 **session** 解出（§3.1） | 🔴 **H5 + PAD 特有**：body 的 `worker_id` **一律忽略** |
| **⑦（本设计新增）** | **session 必须有效**（未过期、未切换、未撤销）（§3.2 / §3.3） | 🔴 **H5 + PAD 特有** |

### 5.4 「不是这道？改」（#4687 §3.3，**逐字继承**）

| 场景 | 行为 |
|---|---|
| 默认路径（绝大多数） | 系统推断值直接作为待报工序 ⇒ **零额外交互** |
| 工人要报的不是它 | 一屏内 `alternatives`（同套同部位其他未完成工序，按 `seq` 排）⇒ **一键改**（一次点选） |
| 接口层 | 完成端点接受**可选** `operation_id`：省略 ⇒ 服务端推断；给出 ⇒ **必须属于该套该部位**（否则 422） |
| 🔴 硬约束 | **绝不允许**「工序未确定」直接记账（§5.3 ⑤） |

### 5.5 离线报工（H5 版，**复用口径**）

见 §4.4。**H5 的唯一实现差异** = 存储后端（`localStorage`/`IndexedDB` 替代 `Taro.setStorageSync`），
**队列语义 / 幂等键 / 冲突处理 / 补报回报 逐字不变**。

---

## 6. 与既有资产的**依赖与冲突**（逐条：**谁为准、为什么**）

| # | 资产 | 关系 | **谁为准** | 为什么 |
|---|---|---|---|---|
| **C1** | 🔴 `frontend/admin-web/src/components/production/TaskCardPrint.tsx`（码 = **裸 `qr_token`**，注释逐字「不放单号拼接串」） | **冲突** | **本设计为准**（码 = 标准 HTTPS URL） | 裁定③「任意扫一扫工具都能用」**只有 URL 能做到**；裸 token 扫了**不跳转**。⇒ **改打印内容**；`processing_orders.qr_token` **列与撤销语义一字不动** |
| **C2** | **#4687** `docs/design/set-code-and-scan-loop.md`（**902 行**，已合并） | **依赖 + 追加** | **#4687 为准**（闭环/码粒度/token 形态/推断算法/防呆/旧码双读）<br>**本设计追加**：URL 形态 + 短码列 + 登录两条腿 + 会话/归属 | 本设计**不改** #4687 的任何冻结形态（token = 32 位 UUID、一部位一码、撤销 = 置 NULL）；只**追加** `short_code` 列与 URL 层 |
| **C3** | 🔴 **#4687 §11 写的迁移号 `V89`** | **冲突（已过期）** | **实测为准**（迁移号**现取，不写死**） | 实测 `origin/main` @ `042f32bca`：`V89` = `V89__backfill_fabric_seed_for_existing_tenants.sql`、`V90` = `V90__unpriced_is_not_zero.sql`、**`V92` = `V92__add_processing_order_sets_and_scan_loop.sql`（#4698 切片⓪，已落）** ⇒ **`V89` 已被占用**（#4687 定稿后 main 前进了），且**迁移头已从基线时的 V90 前进到 V92**（**口径订正**见表后注）。⇒ 本设计的迁移号**不写死**，落码时**现取**（附录 A A2 给命令） |
| **C4** | ✅ **#4687 / #4698 的载体表已在 main**（**口径订正**见表后注） | **依赖（顺序约束已解除）** | **落地顺序约束解除**（载体已落，本设计可直接追加） | 实测（`origin/main` @ `042f32bca`）：`V92__add_processing_order_sets_and_scan_loop.sql` 已建 `processing_order_sets` + `processing_set_part_tokens`（含 `uk_set_part_tokens_token` / `uk_set_part_tokens_part`），并给 `processing_position_operations` 加 **6 列**（`set_id` / `set_no` / **`done_at`** / `worker_id` / `worker_name` / `started_at`）⇒ 与 **#4687 §11.2 逐条一致** ⇒ 本设计的 `short_code` 列可**直接追加**（§7.3） |
| **C5** | 🔴 **#4694**（越站不拦 + 防呆⑤ 工序必须确定） | **依赖** | **#4694 为准** | 实测 `ProductionService.doReport` 逐字：缺 `operationId` 直接拒绝；**无**顺序闸门。本设计**继承**，**不得**加回顺序闸门 |
| **C6** | 🔴 **既有微信登录链路**（`AuthController` / `AuthService` / `UserIdentity`） | **部分依赖 + 假设被推翻** | **实测为准** | ✅ 小程序侧（`bmini` / `mini`）可用；🔴 **H5 网页授权是 501 占位**（`buildWechatH5AuthorizeUrl` / `handleWechatH5Callback` 逐字抛 `NOT_IMPLEMENTED`）+ **无公众号配置** ⇒ 「复用既有链路」只能复用 `UserIdentity` **表与模式**，**不能**复用一条已实现的 H5 OAuth（§2.2 / §8.3） |
| **C7** | **`docs/design/worker-scan-terminal.md`**（**已定稿**，2026-09-19，263 行） | **依赖 + 冲突** | **冲突处：本设计为准**（见下） | ✅ 依赖：§9 落码状态（规格字段/操作记录/计件下钻/逐笔可追溯/打包/发货 **均已 main**）⇒ 本设计**不重做**这些。<br>🔴 **冲突**：该文档裁定 5 逐字「**发货权限 = 工人身份直接可发**」，依据是「发货端点与扫码端点**同为 `order:list`** ⇒ 不需要「仓管」角色」—— 这**把「工人」等同于持 `order:list` 的商家员工**，与 #4716 的红线「**不许给工人商家权限**」**直接冲突**。<br>⇒ **以 #4716 为准**（更新的用户裁定 + 显式红线）；该文档的**能力**（发货下放）保留，**权限载体**改为新 `worker` 角色 + `/api/worker/**`（§2.4） |
| **C8** | **`frontend/bmini-app` 的离线口径**（`productionOffline.ts`，issue #4206） | **依赖（复用）** | **既有为准** | 硬约束「**复用，不新造**」⇒ 队列/幂等键/冲突/补报**逐字复用**，只换存储后端（§4.4） |
| **C9** | **`docs/design/public-operations-and-craft-ui.md`**（**#4675**，842 行，两层模型 / 行业术语） | **无冲突，有依赖** | **#4675 为准** | 本设计**不改**两层模型判据；报工页的工序显示名复用既有 `operationDisplayName` 单一口径（`frontend/admin-web/src/lib/operation-display.ts`） |
| **C10** | **`frontend/bmini-app/src/utils/productionQr.ts`** 的三形态容错解析（注释自述「与后端 `resolveOrder` 的三形态一致」） | **依赖 + 陈旧注释** | **后端为准** | 实测后端 `resolveOrder` 已是**四形态**（④ `processing_order_no`，issue #4222）⇒ 该注释**陈旧**。⇒ 本设计**复用**其**解析逻辑**（纯函数，与 Taro 无关），并登记注释待订正 |
| **C11** | 🔴 **`/api/admin/**` 门禁 vs 工人身份** | **冲突** | **本设计为准**（§2.4） | 实测：`ProductionController` 类级 `@RequirePermission("order:list")` 且挂在 `/api/admin/**`；该路径对非 `customer`/`agent` 角色**放行进入**；**10 个 controller 无 `@RequirePermission`**。⇒ 工人若走既有路径 = **拿到商家权限** ⇒ 违反红线 ⇒ 必须新 `/api/worker/**` + 拒绝集合追加 `worker` |
| **C12** | **`docs/design/c-end-tenant-domain-routing.md`**（`<tenantId>.app.migaozn.com`） | **依赖** | **既有为准** | H5 的租户解析可复用 `backend/admin-api/src/main/java/com/migao/admin/config/TenantDomainResolver.java`（`X-Tenant-Id` 头 > Host 正则）。⚠️ 但**稳定短链域名**取 `app.migaozn.com`（**不带** `<tenantId>` 子域）⇒ 租户由**短码**解出（短码全局唯一，天然带租户），**不依赖**域名子域 |

> 🔴 **口径订正（issue #4716，2026-09-20）：C3 / C4 两条结论已过期，按下述改判。**
> **依据**：**#4698 切片⓪（PR #4722，merge `d295097bb`，2026-09-20）** 落
> **`V92__add_processing_order_sets_and_scan_loop.sql`** —— 同时建好
> `processing_order_sets` + `processing_set_part_tokens`（含 `uk_set_part_tokens_token` / `uk_set_part_tokens_part`），
> 并给 `processing_position_operations` 加 **6 列**（`set_id` / `set_no` / **`done_at`** / `worker_id` / `worker_name` / `started_at`），
> 与 **#4687 §11.2 逐条一致**。
> **C4 改判**：载体表**已在 main** ⇒ **「#4687 必须先落」的落地顺序约束解除**（本设计的 `short_code` 可直接追加）。
> **C3 改判**：迁移头**已从基线时的 V90 前进到 V92**（`V92` 已落）⇒ **下一个自由号落码时现取**；
> 「**迁移号现取、不写死**」的**原则不变**（§7.1 / 附录 A A2 同款）。
> **历史留档（为什么改）**：本文测量基线 = `origin/main` @ `9462c7e18`，当时迁移头 = **V90**、
> `processing_order_sets` / `processing_set_part_tokens` 在 `backend/**` `docs/sql/**` `tests/**` **零命中**
> （只在 `docs/` 出现）⇒ 当时结论「本设计依赖它们先落」「追加到一张尚未存在的表上」**在当时为真**；
> 而 **#4722 恰在本设计合并前一刻落进 main** —— `d295097bb` 是本文合并点 `d1d9bd742` 的**直接父提交**
> ⇒ 基线事实变了、结论随之改判为「**已落码、顺序约束解除**」。
> 机械判据 = 附录 A **A2**（迁移头）与 **A4**（两表命中数）—— 同一组命令现在返回**非零命中**。

---

## 7. 迁移 / 接口 / 端点（**只加不改**；读面加键**同步契约账本**）

### 7.1 迁移（**号现取，不写死**）

```bash
# 落码时先取当前最大号（附录 A A2 同款命令）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ \
  | grep -oE 'V[0-9]+' | sort -t V -k2 -n | tail -1
```

| # | 动作 | 目标 | 幂等要求 |
|---|---|---|---|
| ① | **追加列** `short_code CHAR(8)` + `UNIQUE(short_code) WHERE deleted = 0` | `processing_set_part_tokens`（**#4687 建的表**） | `ADD COLUMN IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS` |
| ② | **追加列** `worker_no VARCHAR(32)` + `UNIQUE(tenant_id, worker_no) WHERE deleted = 0` | `users` | `ADD COLUMN IF NOT EXISTS`（**可空**：存量商家员工无工号） |
| ③ | **新表** `worker_sessions`（§3） | 新表 | `CREATE TABLE IF NOT EXISTS` |
| ④ | **新表** `worker_report_audits`（§3.4） | 新表 | 同上 |
| ⑤ | **新表** `worker_binding_audits`（§2.5） | 新表 | 同上 |
| ⑥ | **新表** `production_work_log_corrections`（§3.5） | 新表 | 同上 |
| ⑦ | **不碰** `production_work_logs` / `processing_orders.qr_token` | — | 🔴 **红线** |
| ⑧ | **同步 bootstrap 终态** `docs/sql/schema.sql` | — | 新建库路径不跑迁移链（既有逐字警告） |
| ⑨ | **登记迁移指纹** `tests/unit_ci_workflows/migration_fingerprints.json` | — | 新增迁移**必须**同 PR 登记（#4235） |

> ⚠️ **④⑤⑥ 三张审计表都是"只追加"** —— 与既有「明细不可变」同族纪律。
> **YAGNI 自检**：能否合并？④ 与 `worker_sessions` 是 **1:N**（一次会话多次报工）⇒ 不能合并；
> ⑤ 与 ④ 语义不同（绑定 vs 报工）⇒ 不能合并；⑥ 是纠错，独立。

### 7.2 端点（**只加不改**）

| 类型 | 端点 | 说明 |
|---|---|---|
| 🆕 **短链解析** | `GET /s/{shortCode}` → **302** | **稳定契约**（印刷品指向它）；SecurityConfig 的 `permitAll` 列表**追加一条** |
| 🆕 登录 | `POST /api/worker/login`（工号 + PIN / 邀请码） | 腿 A |
| 🆕 会话 | `POST /api/worker/session/refresh` / `logout` / `switch` | §3.2 / §3.3 |
| 🆕 解析 | `POST /api/worker/scan/resolve`（短码 / token / 加工单号 / 订单号） | 复用 `resolveOrder` 四形态 + #4687 §3.2 推断 |
| 🆕 **完成** | `POST /api/worker/complete` | §5.2（**新 `@Transactional` 方法**，幂等占位在外层） |
| 🆕 计件 | `GET /api/worker/piecework`（**本人**） | 工人只能看**自己**的计件（断言：传别人的 `worker_id` ⇒ 403/忽略） |
| 🆕 纠错（管理端） | `PUT /api/admin/production/work-logs/{id}`（**白名单字段** + 强制留痕） | §3.5；**不是** `/api/worker/**`（工人无此权限） |
| ♻️ **既有，一字不动** | `POST /api/admin/production/orders/{orderId}/operations/{operationId}/report` | bmini-app 仍在用 ⇒ **不得改**（#4687 §13） |
| ♻️ 既有 | `POST /api/admin/production/orders/{orderId}/qr-token/revoke` | 撤销语义**逐字保留** |
| ♻️ 既有 | `GET /api/auth/h5/authorize` / `h5/callback` | **501 占位**；腿 B 落码时**填实现**（**不改签名**） |

### 7.3 落地顺序（依赖决定）

```
#4687 切片⓪（V92：processing_order_sets + processing_set_part_tokens；**已落** = PR #4722）
   │   ← ✅ **顺序约束已解除**（C4 口径订正：载体表已在 main，本设计可直接追加）
   ├─① 短链 + 短码 + /s/{code}（§1.3 / §1.4）        ← ✅ **已落（issue #4802）**：V99 加列 + `WorkerShortLinkController`（302）
   ├─② 工人身份 + 登录两条腿 + /api/worker/**（§2）   ← 与 ① 同包（都要 users.worker_no）
   ├─③ 会话 / 归属 / 超时（§3.1~3.4）                ← 与 ② 同包
   ├─④ 纠错留痕（§3.5 / §3.6）                      ← 管理端，独立
   └─⑤ H5 报工页（§5）+ 离线（§4.4）                 ← 前端，依赖 ①②③ 的端点
```

### 7.4 契约账本（**读面加键必须同步**）

`docs/wiki/CONTRACT-LEDGER.md` 需**追加**（**不改既有行**）：

| 新增键 | 值 | 备注 |
|---|---|---|
| 工人角色码 | `worker` | **开放集合外的固定值**（与「岗位权限」页可创建任意岗位码不同：`worker` 是**身份分层**，不是岗位） |
| `worker_sessions.end_reason` | `logout` / `idle_timeout` / `switched` / `revoked` | 四态 |
| 报工身份头 | `X-Worker-Session-Id` | 与既有 `X-Client-Request-Id` 并列（**不替代**） |
| 短码 | `short_code`（8 位 Crockford Base32） | 与 `token`（32 位 UUID）**同一行两种表示** |
| 纠错白名单 | `worker_id` / `worker_name` / `qty` / `qualified_qty` / `work_type` / `work_date` | **白名单外一律拒绝** |
| 🔴 纠错禁改 | `unit_price` / `factor` / `id` / `tenant_id` / `processing_order_id` / `operation_id` / `created_at` | **红线** |

> 跨模块改动 ⇒ 提交前跑 `./contract-check.sh`。

---

## 8. 不做什么 / 无法判定 / 与假设不符的事实

### 8.1 本设计**不做**（边界）

- ❌ **不做**小程序报工页（裁定②：**H5**）；**不改** `frontend/bmini-app` 的既有商家视角生产页。
- ❌ **不做** `wx.scanQRCode`（裁定③：页面**零 `wx.*`**）；若将来配了公众号，作**可选增强另立单**。
- ❌ **不引新域名**（复用 `app.migaozn.com`；新域名 = 重新备案 = 已打印的码的额外风险）。
- ❌ **不改** `production_work_logs`（**红线**；设备/会话走旁路表，§3.4）。
- ❌ **不改** `processing_orders.qr_token` 列与撤销语义（**逐字保留**）。
- ❌ **不改** 既有 `report` 端点（bmini-app 在用）；**不改** #4687 冻结的 token 形态。
- ❌ **不把 `unit_price` / `factor` 纳入纠错白名单**（**红线**，§3.6）。
- ❌ **不新造第二套身份表**（复用 `users` + `user_identities`；`wechat_mp` 已在取值域里）。
- ❌ **不给工人任何商家权限码**（`permissions=[]`，§2.4）。
- ❌ **不发明**「闲置超时 N 分钟」的具体数值（列为待裁定 §8.4 R2）。
- ❌ **不替业务决定** §8.4 的待裁定项。

### 8.2 **无法判定**（如实登记，不猜）

| # | 无法判定的事 | 为什么判不了 | 需要什么才能判 |
|---|---|---|---|
| **U1** | ~~**`app.migaozn.com` 的 ICP 备案状态**~~ ✅ **已判定（用户裁定，2026-09-20）** | 仓库内**查不到**备案信息（代码/配置/文档均无备案号或备案状态） | ~~运维/客户提供备案号与主体；**未备案 ⇒ 微信内会拦截，主路径直接失效**~~ ⇒ **用户已答「已做过备案」** ⇒ **该前提成立，风险解除**（本文其余部分按「已备案」读） |
| **U2** | **微信内置浏览器（X5 / WKWebView）对 `getUserMedia` 的当前实际支持度** | 属**运行时/设备/版本相关**行为，静态不可判定；且「历史性限制」不等于「今天不支持」 | 真机实测矩阵（iOS 微信 / Android 微信 / 各版本）；**本设计已按"可能不可用"设计降级**（§1.1 / §4.6），故不阻塞 |
| **U3** | **扫码工具「只显示文本不跳转」的实际占比** | 依 App 而异，无仓库内数据 | 现场调研；**本设计已用 ④ 兜底**，故不阻塞 |
| **U4** | **PAD 断点的具体数值（字号/按钮尺寸阈值）** | 属**人因工程**，需现场实测（工位距离、光照、戴手套与否） | 现场实测；本设计只给**下限建议**（§4.2） |
| **U5** | **存量旧码的实际存量规模** | 需查生产库（`processing_orders.qr_token IS NOT NULL` 的行数） | 生产库查询；**不影响设计**（旧码双读已覆盖） |
| **U6** | **一个工人跨租户打工的工资合并口径** | 属**业务**（发工资口径），真值源 `docs/curtain-production-rules.md` 只写「工资报表 = 报工事件聚合（按人/按期/按单下钻）」 | 客户确认（§8.4 R1） |
| **U7** | **邀请码的发放渠道**（谁生成、怎么给到工人） | 属**运营流程**，无真值源 | 客户确认（§8.4 R4） |

### 8.3 与假设不符的事实（**实测推翻转述**）

| # | 被转述的假设 | **实测事实** | 复算 |
|---|---|---|---|
| **F1** | 「既有微信登录链路可复用（H5）」 | 🔴 **H5 网页授权是 501 占位**：`AuthService.buildWechatH5AuthorizeUrl` / `handleWechatH5Callback` **逐字抛** `BusinessException("NOT_IMPLEMENTED", "微信公众号 OAuth 尚未实现", 501)`；端点存在但服务层未实现 | 附录 A A5 |
| **F2** | 「有公众号配置」 | 🔴 `application.yml` 的 `wechat:` **只有** `mini` + `bmini` + `mock-enabled`，**无公众号段** | 附录 A A5 |
| **F3** | 「工人端页面 ❌ 没有」 | ✅ **对了一半**：**H5 工人端没有**；但 `frontend/bmini-app` 的 `pages/production/index` **已是工人扫码报工页**（578 行，含扫码/报工/计件/发货/离线队列），`docs/design/worker-scan-terminal.md` §9 记其落码状态 **✅ main** | 附录 A A1 |
| **F4** | 「#4687 的迁移号 = V89」 | 🔴 **已被占用**：main 上 `V89` = 面料种子回填、`V90` = 未定价≠0、**`V92` = 套号落库（#4698 切片⓪，已落）** ⇒ 迁移号**必须现取**（**订正**：迁移头已从基线时的 V90 前进到 **V92**；原写「→ V90」见表后「口径订正」注） | 附录 A A2 |
| **F5** | 「码是 token，改成 URL 就行」 | ⚠️ **不止改打印**：`frontend/admin-web/src/components/production/TaskCardPrint.tsx` 的注释把「只放 `qr_token`、不放拼接串」写成**纪律** ⇒ 改它 = **改一条既有纪律**，必须登记（C1） | 附录 A A9 |
| **F6** | 「#4687 / #4698 的表已落」 | ✅ **已落码**（**口径订正**见表后注）：`V92__add_processing_order_sets_and_scan_loop.sql` 已建 `processing_order_sets` + `processing_set_part_tokens`（含 `uk_set_part_tokens_token` / `uk_set_part_tokens_part`），并给 `processing_position_operations` 加 **6 列**（含 `done_at`）⇒ 与 #4687 §11.2 逐条一致 | 附录 A A4 |
| **F7** | 「工人身份可以直接用商家员工」 | 🔴 **与红线冲突**：`ProductionController` 类级 `@RequirePermission("order:list")` + `/api/admin/**` 对非 `customer`/`agent` 放行 + **10 个 controller 无 `@RequirePermission`** | 附录 A A6 / A7 |
| **F8** | 「`worker-scan-terminal.md` 的工人权限口径可继承」 | 🔴 其裁定 5 逐字「发货权限 = **工人身份直接可发**」，依据「发货端点与扫码端点**同为 `order:list`**」⇒ **把工人等同于商家员工**，与 #4716 红线**冲突** ⇒ 以 #4716 为准（C7） | 附录 A A10 |
| **F9** | 「`productionQr.ts` 的注释是当前真值」 | ⚠️ **陈旧**：其注释自述「与后端 `resolveOrder` 的**三形态**一致」，而后端已是**四形态**（④ `processing_order_no`，issue #4222） | 附录 A A11 |
| **F10** | 「`docs/design/set-code-and-scan-loop.md` = 898 行」 | ⚠️ 实测 **902 行**（差异不影响内容，如实登记） | 附录 A A1 |

> 🔴 **口径订正（issue #4716，2026-09-20）：F4 / F6 两条结论已过期**（完整依据与历史留档见 §6 表后的「口径订正」注）。
> **F4**：迁移头**已从基线时的 V90 前进到 V92**（`V92__add_processing_order_sets_and_scan_loop.sql` 已落，PR #4722）
> ⇒ 原写「→ V90」**不再是当前值**；「**迁移号现取、不写死**」的**原则不变**。
> **F6**：`processing_order_sets` / `processing_set_part_tokens` **已由 #4698 切片⓪ / V92 落码**
> （+ `processing_position_operations` 6 列含 `done_at`）⇒ 原写「零命中 ⇒ 尚未落码」**不再成立**。

### 8.4 待用户裁定（**集中列出，不替业务决定**）

| # | 问题 | 选项 | 设计建议（**仅供参考，不是决定**） |
|---|---|---|---|
| **R1** | 一个工人**跨租户打工**的工资口径 | ① 按租户隔离（各自出账）② 按自然人合并 | **①**（与既有 `tenant_id` 隔离一致；跨租户合并会造出「跨租户读工资」的越权面） |
| **R2** | **闲置超时**数值 `N` | ① 15 分钟（建议）② 5 分钟 ③ 30 分钟 ④ 租户可配 | **①默认 + ④可配**（PAD 共用场景偏短更安全，但过短会让工人频繁重登） |
| **R3** | 多标签页队列互踩的处理 | ① `navigator.locks` 加锁 ② 只允许单标签（打开新标签时提示） ③ 不管 | **①**（PAD 上工人可能误开新标签） |
| **R4** | **邀请码**的发放渠道 | ① 管理端生成 + 打印/口头给 ② 短信 ③ 班组长 PAD 上代建 | 需业务（§8.2 U7） |
| **R5** | **短码长度** 6 位 vs 8 位 | ① 8 位（建议，空间 32⁸ ≈ 1.1e12）② 6 位（空间 32⁶ ≈ 1.07e9） | **①**（碰撞概率与手输负担的平衡点；6 位在**全仓累计码量**上仍有碰撞风险） |
| **R6** | **稳定短链的域名** | ① `app.migaozn.com`（复用，建议）② 新域名（如 `s.migaozn.com`） | **①**（不引新域名 = 不重新备案 = 已打印的码零风险） |
| **R7** | 工人**能否看到别人的计件**（PAD 共用时的隐私） | ① 只看本人（建议）② 看全班 | **①**（PAD 是公共设备 ⇒ ② 会把全员工资公示） |

---

## 9. 落码状态（**第一切片**，issue #4716；落码单随本设计）

> **本单是 H5 第一切片**：能扫码 + 能登录 + 能看懂 + 能报工。设计 §7.3 的 ①~⑤ 里，
> 本切片只落 ⑤ 的**页面骨架 + 登录 + 扫码落地 + 报工** + ④ 的 CORS 补头。
> **本节是「已落码 / 未落码」的机械账**，不写"进行中"。
>
> 🔄 **口径订正（rebase 调和）**：本单最初自带一个工人端 `GET /scan`（当时工人确实没有任何解析入口）；
> **切片②（PR #4769，merge `916378c3c`）随后在 main 上落了同一个端点** ⇒ 两边重复。
> 调和结果：**`GET /scan` 以 main（切片②）为准，本单删掉自己那份重复实现**；
> 本单只保留 **CORS 补头** 与页面，并**补该端点的旧码降级契约断言**（见 9.2 ⑦）。

### 9.1 落点决定：`frontend/worker-h5/`（**零依赖 + 零构建步骤**）

| 候选 | 取舍 |
|---|---|
| ✅ **新建 `frontend/worker-h5/`**（本单采用） | 纯 ES module（`.mjs`）+ HTML + CSS，浏览器 `<script type="module">` **直接加载**；测试用 **Node 内置 `--test`**（零新依赖、零 `npm ci`）⇒ **无新构建腿、无新部署腿**（静态直出） |
| ❌ 挂 `frontend/admin-web/` 下 | 商家端域名 + 商家鉴权面，工人 H5 挂进去语义混淆；且 `frontend/admin-web/**` 属 #4746 的改动面 |
| ❌ 挂 `frontend/bmini-app` / `mini-app`（Taro H5） | **Taro H5 运行时自带 `wx.*` 适配层** ⇒ 与裁定③「页面零 `wx.*`」冲突；且 `frontend/bmini-app/**` 属 #4698 切片② 的改动面 |
| ❌ 新引 Vite / Next | 新构建腿 + 新依赖，与「最少代码阶梯」冲突；本页面**没有**需要打包的东西 |

### 9.2 已落码

| # | 内容 | 落点 |
|---|---|---|
| ① | H5 页面骨架（手机 <768px / PAD ≥768px 两断点；PAD 主按钮 **88px**、正文 **20px**；手机触控 ≥44px） | `frontend/worker-h5/index.html` + `src/styles.css` |
| ② | 扫码落地：URL 取码（`?t=` / `?token=` / `?code=` / `#t=` / `/s/<短码>` 路径段）+ **手输短码兜底**；前端**不判码的形态**（判形态是服务端 `resolveOrder` 的职责） | `src/scan-input.mjs` |
| ③ | 🔴 旧码降级：`granularity="order"` ⇒ **进「选套 + 选部位」态**，`set_no`/`position`/`operation` 一律 null，**绝不默认取第 1 套**；部位按钮**只在选了套之后**出现 | `src/render.mjs`（`reduce` / `canReport`） |
| ④ | 工人登录：**工号 + PIN**（复用 #4733 的 `POST /api/worker/login`）+ session 落 `localStorage` + 后续请求带 `X-Worker-Session-Id` | `src/api.mjs` |
| ⑤ | 共用 PAD 三条：页头常驻「当前工人」（取**服务端** `current-worker`）· 一步切换（**不丢扫码上下文**）· 闲置登出（定时器 + `visibilitychange` 双保险；401 ⇒ 回落未登录 + 清本地） | `src/app.mjs` |
| ⑥ | 报工：调**已合并**的 `POST /api/worker/production/orders/{orderId}/operations/{operationId}/report`（#4733）+ `X-Client-Request-Id` 幂等键<br>✅ **本行已被后续 PR 超越（issue #4792，PR #4801，merge `dcf11898f`）**：工人页**唯一写入口**现为 `POST /api/worker/production/scan/complete`，页面**不再**调用 `/report`（口径订正见 §9.3 D3） | `src/api.mjs` |
| ⑦ | 工人读面 `GET /api/worker/production/scan?token=…&operation_id=…` —— **端点本体属切片②（已在 main）**；本单**只消费**它，并补**旧码降级契约断言**（`set_no`/`position`/`operation`/`completed` 全 null + `needs_selection=["set","position"]`） | `WorkerScanEndpointTest`（断言） |
| ⑧ | 🔴 CORS：`allowedHeaders` **追加 `X-Worker-Session-Id`**（#4733 登记的缺口；**只加这一个头，origin 白名单一字不动**） | `SecurityConfig` |

### 9.3 未落码 / 依赖（**照实登记**）

| # | 项 | 状态 | 为什么 / 何时 |
|---|---|---|---|
| D1 | 🔴 **旧码「选完套+部位」之后的收口** | ✅ **已闭环（issue #4794）** | 契约扩展（**只加不改**）：`ProductionScanService.resolve(token, operationId, setId, orderItemId, tenantId)` 重载 + `GET /api/worker/production/scan?…&set_id=&order_item_id=` + `POST …/scan/complete` body 可选 `set_id`/`order_item_id` ⇒ 服务端按**同一份**推断口径重新解析出部位级视图（工序仍由**系统**推断 = 防呆⑤）。3 参 `resolve` 与「无选择 ⇒ `granularity="order"` + `needs_selection`」**逐字不变**；**新码路径不读**这两个入参。旧码端到端 = 扫码 ⇒ 选套 ⇒ 选部位 ⇒ **报工成功**（一次事务），实测输出见 PR #4794 |
| D2 | 稳定短链 `GET /s/{shortCode}`（302）+ `processing_set_part_tokens.short_code` 列（§1.3 / §1.4 / §7.1①②） | ✅ **已落码（issue #4802，V99）** | **落点取舍** = **admin-api 控制器**（`WorkerShortLinkController` + `WorkerShortLinkService`）：短码 ⇒ token 要**查库** ⇒ nginx / 静态页做不到；且用户裁定③「任意扫一扫工具都能用」⇒ 必须**服务端 302**（前端 JS 跳转对只认服务端跳转的扫码工具是白屏）。nginx 只承担**转发**（`deploy/swas/nginx.conf` 的 `location /s/` ⇒ admin-api）。<br>**核清结论**（谁生成 / 何时 / 与 `set_no` 的关系）：**谁生成** = `ProductionService.ensurePartTokens`（在**实例化**时与 token **同一次插入**分配，不在打印时）；**何时** = 首次实例化 ⇒ 重复实例化走 `ON CONFLICT … DO NOTHING` ⇒ **复用同一短码**（幂等，已打印的纸不作废）；**与 `set_no` 的关系** = **无关** —— 套号是「第几樘窗」（一单内有业务含义、有序、可读），短码是「哪一张纸」（**随机**、全局唯一、不可枚举）。一套 ≤3~4 部位 ⇒ ≤3~4 个短码。<br>短码 = **8 位 Crockford Base32**（`0-9` + `A-Z` 去掉 `I/L/O/U`）+ 全局唯一（部分唯一索引 `uk_set_part_tokens_short_code`）；手输归一化 = 去空白 + 大写 + 解码别名 `O→0`、`I/L→1`（生成面从不产出 `O/I/L` ⇒ 不造歧义）。未知短码 ⇒ **404**；已撤销（`token` 置 NULL）⇒ **410**（不静默回落、不换新码）。<br>⚠️ **存量行不回填**（V99 只加列，`short_code` 可空）；**打印面落码是跟随单**（要印的行必须有 `short_code`，否则印出来的码打不开）。⚠️ 本单**不扩**切片① 的冻结契约（`token` 解析语义一字未动；`/s/` **只**认短码，喂 token ⇒ 404） |
| D3 | 切片② 的 `completeByScan` 原子事务（§5.2） | ✅ **已落码（PR #4769，merge `916378c3c`）** | 端点 = `POST /api/worker/production/scan/complete`（**main**）。⚠️ **本单前端仍走既有的 `/orders/{orderId}/operations/{operationId}/report`**（父会话明示「不扩大范围」）⇒ **改用 `scan/complete` 是跟随单**（它才是 §5.2 的一次事务闭环：按 `token` 定位部位 + 幂等 + 审计旁路）<br>✅ **该跟随单已闭环（issue #4792，PR #4801，merge `dcf11898f`）**：工人页写入口已改成 `POST /api/worker/production/scan/complete`（见 `frontend/worker-h5/src/api.mjs`），页面**不再**调用 `/orders/{orderId}/operations/{operationId}/report`；防呆④⑤ 因此**在工人页真实闭环里生效**（改动前后对照见 `frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs` 的注释） |
| D4 | 微信网页授权（腿 B，§2.2） | **不做** | 服务层 501 占位 + 无公众号配置 ⇒ 按用户裁定「本单不做」 |
| D5 | 离线队列（§4.4） | **未落码** | 复用口径（幂等键语义 / 业务拒绝不入队 / 上限 50）**已在 #4733 之外的 bmini-app**；H5 版需换存储后端 + 多标签锁（§8.4 R3）⇒ 跟随单。**本切片：断网 ⇒ 显式报错**（不静默丢单） |
| D6 | 🔴 **CI 不跑 worker-h5 测试** | ✅ **已闭环（issue #4786，PR #4788，merge `588e1757e`）** | 跟随单已落：新增 `.github/workflows/worker-h5-tests.yml`（job 名逐字 = `worker-h5 unit tests (node --test)`，跑 `node --test frontend/worker-h5/tests/*.test.mjs`，触发面 = `frontend/worker-h5/**` + 本 workflow 自身），防回退锁 = `tests/unit_ci_workflows/test_worker_h5_ci_wiring.py`。<br>⚠️ **该 job 不拦合并**：`python3 scripts/merge_gate.py --required-diff` 把它列在「会判红但不拦合并」的裸判据里（分支保护的 required 集合里**没有**它）⇒ 它是**信息性 check**，判红照旧合并（workflow 头注释自述的同一条口径）。提升为 required 的前置条件（先删 workflow 级 `paths:`、改 job 内 diff 门控）登记在该 workflow 注释里。<br>⚠️ 原措辞的**红线保留**（判红 ≠ 覆盖）：**不得**据此说"CI 已覆盖本页面" —— 它只覆盖 `frontend/worker-h5/tests/` 的 `*.test.mjs`，页面**部署面**（§9.4 P2/P3）仍不在任何 CI 腿里。<br><s>原文（历史留档）：`pr-check.yml` 的前端腿只对 `frontend/admin-web/` 变更触发（`working-directory: frontend/admin-web`）⇒ 本目录的测试**只在本地**跑（`./verify-all.sh frontend` / `full` 已接入）。**接 CI 需要改 `.github/workflows/**`**（本单**禁止**触碰，且本机 token 无 `workflow` scope）⇒ 登记为跟随单（新 job：`node --test frontend/worker-h5/tests/*.test.mjs`）。**不得**因此说"CI 已覆盖本页面"</s> |

| D7 | 🔴 **工人档案怎么建（首个工人从哪来）** | ✅ **已落码（issue #4869）** | **要治的形态**：工人档案的定义 = `users.worker_no` 非空且 `role='worker'`（租户内唯一靠部分唯一索引 `uk_users_tenant_worker_no`，V98），而改前**全仓零写入方**（无控制台 / 无接口 / 无种子）⇒ 工号 + PIN 登录虽已落码却**没有可登录的对象**。<br>**落点（新增独立端点，不改员工创建语义）**：控制器 `backend/admin-api/src/main/java/com/migao/admin/controller/AdminWorkerController.java` —— `POST /api/admin/workers`（建号：工号 + 姓名 + PIN）+ `GET /api/admin/workers`（列表）；服务层 `backend/admin-api/src/main/java/com/migao/admin/service/WorkerAdminService.java`。不复用 `POST /api/admin/users`：那条路径强制 `phone` 非空、走岗位解析与权限快照、并关联 `user_roles`，是**员工**语义。<br>**权限码复用员工域**（`employee:create` / `employee:list`）—— 新增权限码要迁移 + 全租户回填岗位默认权限，属过度建设；**停用/启用复用** `PUT /api/admin/users/{id}/status`（不另造端点）。<br>**工人零商家权限**：只落 `role='worker'`（与登录侧 `WorkerSessionService.WORKER_ROLE`、门禁 `ADMIN_API_REJECTED_ROLES` **同一字面量**），不写 `user_roles` / `permissions` / `username` / `must_change_password` / `phone`；新入口落在 `/api/admin/**` 面内 ⇒ 与员工管理走**同一道**门禁（不新造第二套判定）。<br>**冲突 fail-closed**：工号重复 ⇒ **409 + 说清是哪个工号 + 给出出口**（不是 500、不静默改号）；并发由唯一索引兜底（`DuplicateKeyException` 同款拒绝）。**PIN** = 4~12 位数字（工人端 PIN 输入框是数字键盘，含字母的 PIN 工人打不出来）+ BCrypt 落 `users.password_hash`。<br>**前端入口**：员工管理页 `frontend/admin-web/src/app/(dashboard)/employees/page.tsx` 分「员工 / 工人档案」两个面（`frontend/admin-web/src/components/employees/WorkerProfilesPanel.tsx`）；工人**不混进员工列表** —— 服务端 `UserService.getUserPage` 也显式排除 `role=worker`（同 `customer` 口径）。<br>**判据**：`backend/admin-api/src/test/java/com/migao/admin/service/WorkerAdminServiceTest.java`（建号 ⇒ 工号+PIN 真登录成功 / 跨租户不可见 / 重复工号 409 / 零商家权限 / PIN 形态）、`backend/admin-api/src/test/java/com/migao/admin/controller/AdminWorkerControllerTest.java`、`backend/admin-api/src/test/java/com/migao/admin/security/AdminApiWorkerRoleGateTest.java`（角色码单一真值源 + 门禁必拒）、`backend/admin-api/src/test/java/com/migao/admin/security/SecurityConfigTest.java`（worker 身份访问新端点 ⇒ 403 且未进服务层）、`frontend/admin-web/tests/unit/components/WorkerProfilesPanel.test.tsx` |

> 🔴 **口径订正（issue #4826，2026-09-21）：D3 的「跟随单」与 D6 的「CI 不跑」两条结论已过期** ——
> **原文措辞一字未删**（上表 D6 的原文留在 ~~删除线~~ 里、D3 的原文留在「⚠️」句里），改判只**追加**「何时由谁闭环」。
> **D6**：#4786 已由 PR #4788（merge `588e1757e`）落码 —— `.github/workflows/worker-h5-tests.yml` +
> job `worker-h5 unit tests (node --test)`；「是否 required」**按元判据现查、不凭名字猜**：
> `python3 scripts/merge_gate.py --required-diff` ⇒ 本 job 出现在「裸判据（会判红但不拦合并）」清单里。
> 提升为 required 的前置条件（先改门控再改分支保护）已写在该 workflow 注释里，**本单不改 workflow**。
> **D3**：跟随单 #4792 已由 PR #4801（merge `dcf11898f`）落码 —— 工人页写入口改成 `scan/complete`。
> **同款写法**（先例）：本表 D1 的「✅ 已闭环（issue #4794）」、以及
> `docs/design/set-code-and-scan-loop.md` §1.2 表后的「口径订正」注。

### 9.4 工程前提（**前提，不是本单能解的**）

| # | 前提 | 谁负责 |
|---|---|---|
| P1 | ✅ **ICP 备案：用户已答「已做过备案」⇒ 该风险解除**（原判「未备案 ⇒ 微信内拦截 ⇒ 裁定④ 失效」不再成立） | **已解除**（用户裁定） |
| P2 | 静态文件落位：把 `frontend/worker-h5/` 的产物放到 `app.migaozn.com` 的静态根下的 `/w/`（与 C 端 H5 同一台 nginx） | ✅ **已落码**（issue #4837 / PR #4847）：CI 腿 `.github/workflows/worker-h5-publish.yml` 把 `index.html` + `src/**` **逐字**发布到 `<静态根>/w/`（零构建、不引 npm build），发布后由 `deploy/scripts/worker-h5-verify-served.sh` 断言线上 `/w/` 的 body 哈希 == 仓库文件且不含 C 端标识 —— **nginx 零改动**（现有 `location /` 的 `try_files` 已能命中 `w/index.html`） |
| P3 | 页面与 `/api` **同源** ⇒ 无跨域；若将来改跨域部署，需把 origin 加进 `CORS_ALLOWED_ORIGINS` | 部署 |

---

## 10. 本单（#4716 落码第一切片）实际落地位置（**不复用 §9 行号**）

> §9 写在本单 rebase 之前，行号会随 rebase 漂移 ⇒ **落码位置以本节 + `git diff` 为准**。

| # | 落点 |
|---|---|
| 页面骨架 / 两断点 | `frontend/worker-h5/index.html` + `src/styles.css` |
| 扫码入口解析 | `frontend/worker-h5/src/scan-input.mjs` |
| 旧码降级 / 一屏渲染 / 报工闸 | `frontend/worker-h5/src/render.mjs` |
| 登录 / session / 报工 API | `frontend/worker-h5/src/api.mjs` |
| 装配 / 共用 PAD 三条 | `frontend/worker-h5/src/app.mjs` |
| 页面测试（Node 内置 runner） | `frontend/worker-h5/tests/*.test.mjs` |
| 🔴 CORS 补头 | `SecurityConfig.allowedHeaders`（+`X-Worker-Session-Id`） |
| 旧码降级**契约断言** | `WorkerScanEndpointTest` |
| CORS 预检断言 | `SecurityConfigTest#cors_PreflightAllowsWorkerSessionHeader` |
| 本地验证接线 | `verify-all.sh`（三档各加一条 `worker-h5` 检查项） |

---

## 附录 A：所有实测命令与数字

> 全部命令在 `docs/worker-h5-scan-4716` 工作区执行，基线 = `origin/main` @ `9462c7e18`。
> **不写死易变数字**：凡随 main 前进而变者，只给**检索命令**。

```bash
cd <migao repo> && git fetch origin main -q
```

### A1 既有设计文档行数（F3 / F10）

```bash
git show origin/main:docs/design/set-code-and-scan-loop.md | wc -l      # → 902（#4687）
git show origin/main:docs/design/public-operations-and-craft-ui.md | wc -l  # → 842（#4675）
git show origin/main:docs/design/worker-scan-terminal.md | wc -l        # → 263（已定稿）
wc -l frontend/bmini-app/src/pages/production/index/index.tsx           # → 578（既有工人扫码报工页）
```

### A2 迁移头号（**现取，不写死**；F4）

```bash
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ \
  | grep -oE 'V[0-9]+' | sort -t V -k2 -n | tail -1        # → V92（口径订正时；基线时为 V90）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -E 'V89|V90|V92'
# → V89__backfill_fabric_seed_for_existing_tenants.sql / V90__unpriced_is_not_zero.sql
#   / V92__add_processing_order_sets_and_scan_loop.sql（#4698 切片⓪，已落）
# ⇒ #4687 §11 写的 V89 已被占用；迁移头会继续前进 ⇒ 本节数字只是**实测快照**，落码时**现取**
```

> 🔴 **口径订正（issue #4716，2026-09-20）**：上面 `# → V90（基线时）` 是**基线快照**、**不是当前值** ——
> 现为 **V92**（`V92__add_processing_order_sets_and_scan_loop.sql` 已落，PR #4722，实测 `origin/main` @ `042f32bca`）。
> **原则不变**：迁移号**现取、不写死**（正文 §7.1 同款）。

### A3 迁移指纹账本（新增迁移必须登记）

```bash
git show origin/main:tests/unit_ci_workflows/migration_fingerprints.json \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['migrations']))"
```

### A4 #4687 / #4698 的载体表是否已落码（F6）

```bash
git grep -l 'processing_order_sets'      origin/main -- 'backend/**' 'docs/sql/**' 'tests/**' | wc -l   # → 6（口径订正时；基线时为 0）
git grep -l 'processing_set_part_tokens' origin/main -- 'backend/**' 'docs/sql/**' 'tests/**' | wc -l   # → 5（口径订正时；基线时为 0）
# ⇒ 两张表**已落码**（命中 = V92 迁移 + 相关测试/bootstrap 终态）⇒ **顺序约束解除**（C4 口径订正）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql \
  | grep -cE 'CREATE TABLE IF NOT EXISTS (processing_order_sets|processing_set_part_tokens)'   # → 2
# ⇒ 与 #4687 §11.2 逐条一致（两表 + uk_set_part_tokens_token / uk_set_part_tokens_part + 实例 6 列含 done_at）
```

> 🔴 **口径订正（issue #4716，2026-09-20）**：本节原写「两张表零命中 ⇒ **尚未落码**」——
> 那是**基线 `9462c7e18` 的真值**；**#4698 切片⓪（PR #4722，merge `d295097bb`）在基线之后、
> 本设计合并之前落进 main**（`d295097bb` 是本文合并点 `d1d9bd742` 的**直接父提交**）
> ⇒ 同一组命令现在返回**非零命中**，结论改判为「**已落码**」（实测 `origin/main` @ `042f32bca`）。
> **历史留档**见 §6 表后的「口径订正」注。

### A5 微信 H5 网页授权与公众号配置（F1 / F2）

```bash
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java \
  | grep -c "NOT_IMPLEMENTED"                       # → 2（buildWechatH5AuthorizeUrl / handleWechatH5Callback）
git show origin/main:backend/admin-api/src/main/resources/application.yml | sed -n '/^wechat:/,/^logging:/p'
# ⇒ 只有 mini / bmini / mock-enabled，无公众号段
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/controller/AuthController.java \
  | grep -n "h5/authorize\|h5/callback"             # → 端点存在（服务层 501）
```

### A6 报工端点与 `/api/admin/**` 门禁（F7 / C11）

```bash
grep -n "RequirePermission" backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java | head -3
# → 类级 @RequirePermission("order:list")；各管理端点另加 processing:manage
grep -n 'operations/{operationId}/report' backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java
# → @PostMapping("/orders/{orderId}/operations/{operationId}/report") ⇒ 工序在 URL 路径里
grep -n "adminApiAuthorizationManager" -A 12 backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java
# → customer/agent 拒绝；其余角色视为商户员工角色
```

### A7 无 `@RequirePermission` 的 controller（F7 的残余风险面）

```bash
c=0; for f in backend/admin-api/src/main/java/com/migao/admin/controller/*.java; do
  grep -q "RequirePermission" "$f" || { echo "$f"; c=$((c+1)); }; done; echo "count=$c"
# → count=10（含 /api/admin/user、/api/admin/menus）
```

### A8 离线口径（C8）

```bash
git grep -l "offline" origin/main -- frontend/bmini-app | wc -l   # → 6
git show origin/main:frontend/bmini-app/src/utils/productionOffline.ts | head -40
# → 幂等键语义（补传复用同一 requestId）+ 业务拒绝不入队 + MAX_WORK_LOGS = 50
```

### A9 二维码打印内容（F5 / C1）

```bash
git show origin/main:frontend/admin-web/src/components/production/TaskCardPrint.tsx | grep -n "value={qrToken}"
# → value={qrToken}（裸 token，不是 URL）
git show origin/main:frontend/admin-web/src/components/production/TaskCardPrint.tsx | grep -n "只放"
# → 注释逐字「二维码内容只放 qr_token（token 化、可撤销），不放单号拼接串」
```

### A10 `worker-scan-terminal.md` 的工人权限口径（F8 / C7）

```bash
git show origin/main:docs/design/worker-scan-terminal.md | grep -n "发货权限"
# → 裁定 5「发货权限 = 工人身份直接可发」；依据「发货端点与扫码端点同为 order:list」
```

### A11 扫码解析形态数（F9 / C10）

```bash
git show origin/main:frontend/bmini-app/src/utils/productionQr.ts | grep -n "三形态"
# → 注释自述「与后端 resolveOrder 的三形态一致」
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java \
  | sed -n '/private Order resolveOrder/,/^    }/p' | grep -E '// [①②③④]'
# → 命中 ② order_no 兜底 / ③ qr_token 兜底 / ④ processing_order_no 兜底（三条显式标记）
#   + 首形态 ①（order_id，无标记注释）⇒ **共四形态** ⇒ productionQr.ts 的「三形态」注释陈旧
```

### A12 身份与权限模型（§2.3 / §2.4）

```bash
git show origin/main:docs/sql/schema.sql | sed -n '/^CREATE TABLE user_identities/,/^);/p'
# → user_id VARCHAR(64) NOT NULL REFERENCES users(id)；identity_type 注释：wechat_mini / wechat_mp / password
git show origin/main:docs/sql/schema.sql | sed -n '/^CREATE TABLE users/,/^);/p'
# → 已有 password_hash VARCHAR(255)（PIN 可直接复用，零新列）
git grep -n "CLAIM_ROLES\|CLAIM_PERMISSIONS\|CLAIM_TENANT_ID" origin/main \
  -- backend/admin-api/src/main/java/com/migao/admin/security/JwtTokenProvider.java
```

### A13 门禁自检（本单为 docs-only）

```bash
python3 .github/case_trust_gate.py --base origin/main    # → exit 0（基线绿）
./verify-all.sh gate                                     # commit 之后跑（弱断言检查依赖已提交 diff）
```
