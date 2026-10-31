# 试用客户上线 runbook（第一批 1~2 家，B 端）

> 关联 #8200（上线前只读审计 · issue #8197）；本文件是 issue #8218 目标①「先 1~2 家试用客户」的落地载体。
> **判据**（零人工即判的那一半）= `scripts/trial_onboarding_check.py`（只读、三态 `rc=0/1/3`）+
> `tests/unit_ci_workflows/test_trial_onboarding_check.py`（用例 **MC-012**）。
> **判不了的那一半**（微信后台、终端签名、真机安装、云侧备份窗口…）在 **§8 逐条登记**，不粉饰、不冒充已验证。
>
> 本文**不**重复终端发布（[terminal-release.md](terminal-release.md)）、微信 A 档规则（[wechat-mini-program-qr.md](wechat-mini-program-qr.md)）、
> 回滚判定（[rollback.md](rollback.md) §1）的正文 —— 只在需要时给出「该看哪一节 + 该跑哪条命令」。

---

## 0. 适用范围与铁口径

| 项 | 口径 |
|---|---|
| 谁 | 第一批 **1~2 家** B 端试用客户（布艺加工 / 窗帘门店），**先把链路跑通再扩量** |
| 终端 | **APK**（商米 V2s 手持机）+ **EXE**（Windows 一体机，WebView2） |
| 小程序 | 现有**三角色**（管理员 / 员工 / 工人）；工人扫码报工走 **A 档**（微信里扫普通链接二维码直接开小程序报工页） |
| 入口 | PC 端 `merchant.migaozn.com`；手机端 `/b/`（bmini h5）+ 小程序；兼容期工人端 `/w/` |
| **只读** | 上线验收只读。**脚本不登录、不 POST、不写库**（登录探测会触发 `LoginFailureGuard` 的失败计数 ⇒ 锁号，那本身就是写） |
| **无人值守删除** | 一律没有（铁律 10）。停用走可逆的 `tenants.status`，删除走人工工单（§6.5） |

**为什么先 1~2 家**：`app.migaozn.com/terminal/` 的清单至今**未发布**（§2.1 实测），微信 A 档规则要人工发布，
终端安装包**未签名**（§2.3）。这三件事都不是「上量能掩盖」的问题 —— 一家客户的现场反馈比十家的投诉便宜。

---

## 1. 前置：租户、企业编码、账号（上线前 T-2 天完成）

### 1.1 开租（两条路径，选一条）

| 路径 | 入口 | 谁做 | 副作用 |
|---|---|---|---|
| **A. 客户自助注册** | `https://merchant.migaozn.com/register`（`frontend/admin-web/src/app/register/page.tsx`）⇒ 提交后 **pending** | 客户填，运营审批 | 审批后建租户 |
| **B. 运营代开** | `POST /api/auth/register` + `PUT /api/super-admin/registrations/{id}/approve`（`RegistrationController`） | 运营 | 同上 |

审批（`RegistrationService.approve`，CAS `approveIfPending` 防重复开租）的**副作用链**：

1. **企业编码**自动生成 = 公司名 slug（≤24）+ `-` + 4 位随机（`LoginIdentifiers.defaultTenantCode`）；
   形态 `^[a-z0-9][a-z0-9_-]{1,31}$`（**允许下划线**，存量编码有 `tenant_7478359537` 这种），
   10 个保留字（`admin/api/www/app/platform/support/system/root/login/auth`）不可占用。
2. **八个默认岗位** + 每岗默认权限快照（管理员 / 客服 / 运营 / 销售 / 财务 / 商品管理员 / 知识编辑 / 质检员）。
3. **管理员账号**：`username` = 申请手机号，**随机初始密码**（短信验证码是主路径，密码是备用）⇒ 首登后必须改密。
4. **开租初始数据**（`OnboardingInitialData.REQUIRED` 逐条播种 + 后置现取校验）。

> 🔴 **企业编码一旦发出就是登录标识的一部分**（员工用 `<用户名>@<企业编码>` 登录）⇒ 试用期内**不要再改**。
> 客户如果要求换编码，等于让该租户**全部员工**重新登录 + 所有已打印的纸作废。

**判据**：脚本 `enterprise-code`（形态 + 保留字）；「这家企业的码是否只落到这家企业」由 `tenant-binding` 判（§5）。

### 1.2 三类人怎么建（页面 / API 对照）

| 角色 | 页面 | API | 必填 | 权限码 |
|---|---|---|---|---|
| **管理员** | 审批时自动创建 | `PUT /api/super-admin/registrations/{id}/approve` | 手机号 / 联系人 / 企业名 | —— |
| **员工**（客服/运营/财务…） | `/employees` 的**员工**页签 | `POST /api/admin/users` | `phone`、`username`（`^[a-z0-9][a-z0-9._-]{2,31}$`）、`password`、`position` 或 `role`/`roleIds` | `employee:create` |
| **工人**（车间报工） | `/employees` 的**工人**页签 | `POST /api/admin/workers` | `workerNo`（工号，**租户内唯一**）、`name`、`pin`（6 位；可省 ⇒ 服务端随机生成） | `employee:create` |
| 工人 PIN 重置 | `/employees` 工人页签 | `PUT /api/admin/workers/{id}/pin` | `pin`（可省 ⇒ 随机 6 位） | `employee:create` |

- **员工**登录 = `<username>@<企业编码>` + 密码；**工人**没有登录用户名、没有菜单权限 —— 只有**工号 + PIN**，
  只能进工人端（`/b/report/` 或 `/w/`）扫码报工。**别把工人建成员工**：建错了会「看起来像员工」
  （能改岗位/权限），而那条路对工人根本不成立。
- 岗位/角色是 **fail-closed**：三样都不给 ⇒ `422`（不兜底成运营级权限）。页面强制选岗位 ⇒ 只有 API 直连会撞到。
- 工号冲突是 `409` + 明确文案（不是 500）。

**判据**：建号这半边**没有公开面可判**（需要凭据）⇒ 它属于 §7.2 的人工 checklist，逐格勾选 + 截图留证。

### 1.3 试用客户隔离与数据边界

| 层 | 机制 | 试用期的检查动作 |
|---|---|---|
| 请求 | `TenantContext` + MyBatis 租户拦截器（admin-api） | 用**别家**企业编码登录 ⇒ 必须 `401` 同一文案（反枚举） |
| 登录 | 企业编码只在 `deleted=0 且 status='active'` 的租户里解析 | 停用该租户 ⇒ 全员立即登不进来（可逆，§6.5） |
| 数据 | 同库按 `tenant_id` 隔离（**不是**每家一个库） | 跨租户读到别家订单/客户 = **P0**（§6.3） |
| 印刷品 | 短码全局唯一，但 302 落点带 `tenant_code` | 脚本 `tenant-binding` 逐码核归属（§5） |

> ⚠️ 隔离是**代码层 + 租户列**，没有物理隔离。试用期必须**逐码核归属**：一张印错到别家的纸
> 等于把别家的报工入口贴到客户车间里（`/s/`、`/o/`、`/i/` 三类公开入口都是 `permitAll`）。

---

## 2. 终端（Windows 一体机 / Android 手持机）

### 2.1 线上坐标（程序里写死的地址，不是可选项）

| 件 | 地址 | 落在哪个域 |
|---|---|---|
| 官网下载页 | `https://migaozn.com/download`（`www` 308 → 裸域） | **裸域** |
| ❌ 假面 | `https://app.migaozn.com/download` ⇒ **200 但那是 C 端 SPA fallback**（实测 507 字节） | app 域 |
| 裸前缀归一 | `https://app.migaozn.com/terminal` ⇒ **301** → `/terminal/` | app 域 |
| Windows 清单 | `https://app.migaozn.com/terminal/latest.json` | app 域 |
| Android 清单 | `https://app.migaozn.com/terminal/android/latest.json` | app 域 |
| 安装包 | `https://app.migaozn.com/terminal/<清单里的 download_url 文件名>` | app 域 |

> 🔴 **`/download` 只有裸域是对的**。`app.migaozn.com/download` 回 200 但内容是 C 端元元那页 ——
> 只看状态码的验收会在这里**假绿**（脚本用「正文含『观星台终端』」判它，不是只看 200）。
> 🔴 `/terminal` 裸前缀必须 301，否则同样落 SPA fallback ⇒ **缺失文件也回 200**，客户端把 HTML 当清单解析。

### 2.2 校验：**没有 `SHA256SUMS.txt` 这回事**（口径更正）

发布腿**故意不搬** `SHA256SUMS.txt`（终端仓 Release 里有，但**不进**线上载荷）
⇒ 线上校验值只有清单里的 `sha256` + `size` 两个字段。
判据 = `tests/unit_ci_workflows/test_terminal_release_leg.py`（断言 `latest.json` 不含该文件名、发布后
`terminal/SHA256SUMS.txt` **不存在**）。发布腿另外在**写入之前**做清单⇄载荷的逐条比对（`sha256` / `size` / `download_url`）。

人工校验（下载后、安装前）：

```bash
# macOS / Linux
sha256sum GuanxingtaiSetup.exe        # 或 shasum -a 256
# Windows PowerShell
Get-FileHash .\GuanxingtaiSetup.exe -Algorithm SHA256
# 与清单里的 sha256 逐字比对（脚本已自动核「清单⇄载荷」一致，这里是人眼复核）
curl -fsS https://app.migaozn.com/terminal/latest.json | python3 -m json.tool
```

> 安装包文件名带版本（例：`GuanxingtaiTerminal-1.0.1.apk`；Windows 固定 `GuanxingtaiSetup.exe`）——
> **以清单里的 `download_url` 为准**，不要按记忆拼文件名。

### 2.3 签名现状（如实登记，不粉饰）

| 端 | 现状 | 用户会看到什么 | 现在能做的 |
|---|---|---|---|
| Windows EXE | **未签名**（已购证书是 DV TLS 域名证书，EKU=Server Authentication，**不能**做 Authenticode） | SmartScreen「Windows 已保护你的电脑」 | 下载页写明「更多信息 → 仍要运行」+ 公布 SHA-256；安装程序启动时把自身 SHA-256 写进日志 |
| Android APK | 自签 keystore，**只存终端仓 Secrets**（`ANDROID_KEYSTORE_BASE64` 等） | 首次安装需允许「未知来源应用」 | 下载页写明该步骤；**换 key = 已装机器无法升级，必须卸载重装** ⇒ 这把 key 是长期资产 |
| 应用市场 | **不上架**（企业内部工具） | —— | —— |

> **脚本不给签名结论**：Authenticode 要 `signtool verify`、APK 要 `apksigner verify`，公网读不到 ⇒ 这一条只能人工登记。

### 2.4 安装（真机步骤，人工）

**APK（商米 V2s 手持机）**
1. 手持机浏览器打开 `https://migaozn.com/download` → 下载 Android 包（或在 PC 下载后传过去）。
2. 设置 → 安全 → **允许未知来源**（商米的「安装未知应用」按应用授权）。
3. 安装 → 首次启动填 **企业编码 + 工号 + PIN**（与 §1.2 建的工人档案一致）。
4. 首屏应出现该工人可报的加工单；**报一单**（§7.2 第 5 步）。

**EXE（Windows 一体机）**
1. 前提：**WebView2 运行时**（Win10 1803+ 通常自带；没有则先装 Evergreen Runtime，否则界面白屏而进程活着）。
2. 下载 `GuanxingtaiSetup.exe` → 右键「属性 → 数字签名」**应为空**（未签名，见 §2.3）⇒ SmartScreen 走「更多信息 → 仍要运行」。
3. 安装后首次启动填 **企业编码 + 工号 + PIN**。
4. 检查更新能读到 `/terminal/latest.json`（§2.5）。

### 2.5 更新链路验证（`/terminal/latest.json`）

| 步 | 动作 | 通过判据 |
|---|---|---|
| 1 | `curl -fsS https://app.migaozn.com/terminal/latest.json` | 200 + JSON，含 `version` / `download_url` / `sha256`(64 位) / `size` / `published_at` |
| 2 | `curl -fsS https://app.migaozn.com/terminal/android/latest.json` | 同上 + `versionCode`（**正整数、单调递增** —— 它才是 Android 更新比较的唯一依据） |
| 3 | 终端里点「检查更新」 | 清单版本 **高于** 已装版本 ⇒ 出现升级提示；相同 ⇒ 无提示（**不弹错误**） |
| 4 | 装同版本再检查一次 | 仍然无提示（幂等，不是「每次都提示」） |

> ⚠️ **Windows 的版本比较是字符串比较**（`1.0.10.0` 会被判成小于 `1.0.9.0`）⇒ 发布时版本统一写 4 段 `x.y.z.0`，
> 跨十位时人工确认。根治在终端仓（terminal#12）。

**判据**：脚本 `windows-manifest` / `android-manifest` —— 清单语义 + **载荷真能下载且 size 对得上**。
清单**未发布**（404）⇒ `rc=3`（不是绿、也不是缺陷），见 §5。

---

## 3. 小程序 / H5（三角色）

### 3.1 登录矩阵

| 角色 | 入口 | 凭据 | 说明 |
|---|---|---|---|
| 管理员 | `merchant.migaozn.com` | 手机号（或 `<用户名>@<企业编码>`）+ 密码 | 首登强制改密 |
| 员工 | `/b/`（手机浏览器或小程序） | `<用户名>@<企业编码>` + 密码 | 与 PC 同一账号 |
| 工人 | `/b/report/?t=<token>`、`/w/`、或扫码进小程序 | **工号 + PIN** | 无用户名、无菜单 |
| 扫码交接 | `/b/` 顶栏「手机端」图标 → 二维码 | 一次性票据 `?qr=`（**120 秒、单次有效**） | 人坐在 PC 前把会话交到手机 |

### 3.2 工人扫码报工（A 档链路，逐跳）

```
纸上的码  https://app.migaozn.com/s/<短码>
   │
   ├─ 微信扫（A 档，需 §8-① 后台规则已发布）
   │     → 小程序 pages/worker/report/index，query.q = 整条链接
   │     → GET /s/<短码>/json  ⇒ 200 {reportPath:"/b/report/", token}
   │     → 走既有报工流程（未登录 ⇒ **就地登录**，登录后接着手里的码）
   │
   └─ 任意浏览器/扫码工具
         → GET /s/<短码> ⇒ 302 → /b/report/?t=<token>&tenant_id=…&tenant_code=…
         → 报工页（未登录 ⇒ 就地登录）
```

- **小程序不跟随 302** ⇒ A 档必须走 `/s/<短码>/json`（显式子路径，**不是** Accept 内容协商 ——
  否则已印出去的码在部分扫码工具里会变成一段 JSON）。
- 错误语义：**未知码 ⇒ 404 `{"error":"not_found"}`；已撤销 ⇒ 410 `{"error":"revoked"}`**
  ⇒ 页面给**明确错误**、不重试、不换新码（撤了就是那张纸作废）。
- 加工单级码 `/o/<短码>` **同族**：302 → 同一个报工页（带 `tenant_code`）。

### 3.3 `/b/` 与 `/w/` 同源核对

`/b/` 就是 `frontend/bmini-app` 的 `build:h5` 产物（Taro 双编译），`/w/` 是兼容期的 worker-h5。
**核对动作**（两人各持一端，同一工人、同一张码）：

1. 两边都能打开 200（脚本 `bmini-report-page` / `worker-h5-page`）。
2. 同一个码在两边落到**同一个**加工单/部位（不是「都能报工」就行，要对单号）。
3. 两边报工结果在 PC 端**同一处**可见（`/production` 或加工单详情）。
4. 菜单/入口一致（`/b/` 是单一真源 ⇒ 差异即缺陷）。

---

## 4. 二维码（三种，别混）

| 码 | 面 | 生成入口 | 用途 | 撤销 |
|---|---|---|---|---|
| **企业入口码** | `/b/`（可带 `?qr=<一次性票据>`） | PC 端顶栏「手机端」图标 → 弹层二维码（全站唯一入口） | 把会话交到手机；不是印刷品 | 票据 120 秒自过期 |
| **工人/部位码** | `/s/<短码>` | **实例化工序**时分配（`ProductionService` 的 `ensureShortCode` / 部位 token），随任务卡打印 | 工人扫部位码报工（一部位一码） | 撤销 = `token` 置空 ⇒ **410**（短码不回收、纸作废） |
| **加工单码** | `/o/<短码>` | 同一条实例化路径（`ensureShortCode`）+「重新发码」时**只补 token、短码不变** | 整单入口（不细分部位） | 同上（短码不动，已打印的纸不作废） |

**短码形态**（三处共用一份实现）：8 位 **Crockford Base32**（去掉 `I/L/O/U`），**随机**（不是顺序号 ⇒ 不可枚举），
全局唯一；同一串既是 URL 路径段也是纸面人读码 ⇒ **手输 = 扫码**，零分叉。
🔴 **短码不可重印**：`/s/<短码>` 的路径段与短码**一字不动**，换码 = 已贴的纸全部作废。

### 4.1 打印规范（纸型与码位，真值在组件里）

| 纸型 | 出处 | 硬约束 |
|---|---|---|
| 任务卡 `50×119` | `frontend/admin-web/src/components/production/TaskCardPrint.tsx` | 正文可裁，**二维码永不被裁**，码下沿距底虚线 ≥ 15mm，码 80 CSS px（≈21.17mm） |
| 专属唛 `50×140` | 同文件（专属唛分支） | 只印 5 行 + 二维码（货号/门幅/宽高/工艺/特殊选项）；上下各 15mm 留白 |
| 入库标签 | `frontend/admin-web/src/components/production/DirectLabelPrint.tsx` | `/i/<短码>` 同族 |

- **缺码不画假码**：部位没有 token/`scan_url` ⇒ 画占位框，**不**编一个码出来（画了假码 = 工人扫出白屏而页面一切正常）。
- 二维码内容只放**该部位自己的** `scan_url ?? part_token`，**不**放单号拼接串、不放加工单级 token。

### 4.2 张贴规范（现场，人工）

1. **一部位一码**，不要一张纸印多个部位（扫错没法判）。
2. 贴在**不反光、不弯折**的位置；不要塑封后贴在弧面上（微信扫不出的第一因是反光）。
3. **不要在码上叠贴**胶带/标签；不要手写涂改短码（短码是随机串，抄错必错）。
4. 加工单纸随工件走；一张单的多个部位分开贴，别把同一张纸裁成几段。

### 4.3 扫码验证步骤（上线当天必须走一遍，逐条截图）

| # | 动作 | 通过判据 | 失败怎么读 |
|---|---|---|---|
| 1 | 手机相机/扫一扫扫部位码 | 浏览器打开 ⇒ 落到 `/b/report/`，单号/部位**对** | 落到别处 ⇒ 短码被别的租户占用（P0） |
| 2 | 微信扫同一个码 | 直接打开小程序报工页（A 档已发布时） | 停在报工页但按钮不出来 ⇒ JSON 面 404/410 或后台规则未发布（§8-①） |
| 3 | 手工输错一位短码 | 明确「码无效」，**不**重试、不跳别处 | 跳到任意单 ⇒ 短码解析有洞（P0） |
| 4 | 扫一张**已撤销**的码 | 明确作废提示（410 语义） | 仍能报工 ⇒ 撤销没生效（P0） |
| 5 | 换一台**别家**企业的手持机扫这张码 | 落到**本企业**报工页（码只认企业，不认设备） | 落到别家 ⇒ `tenant-binding` 判红（脚本会抓） |

---

## 5. 上线验收：只读判据（零人工即判）

```bash
# 基础面（不需要任何凭据）
python3 scripts/trial_onboarding_check.py --enterprise-code <企业编码>

# 上线当天（拿到纸上真实短码之后）
python3 scripts/trial_onboarding_check.py \
  --enterprise-code <企业编码> \
  --worker-code <工人/部位短码> \
  --order-code <加工单短码>
```

### 5.1 三态退出码

| rc | 含义 | 怎么办 |
|---|---|---|
| **0** | 全部判据通过 ⇒ 可以进真机安装与首单报工 | —— |
| **1** | **确定的缺陷**：面非 200/404、清单语义坏、清单⇄载荷对不上、缺安全头、短码归属别家企业 | 按输出逐条修；**不许**当成「再跑一次就好了」 |
| **3** | **不可判定 / 缺配置**：连不上、清单**未发布**、没给工人短码 | **不是通过**。补齐配置（跑发布腿 / 拿到纸上的码）后复算 |

`1` 优先于 `3`：已经确定的缺陷不该被「另一面探不到」稀释成不可判定。

### 5.2 判据表（每条都能单独变红；红证见测试文件）

| 判据 | 面 | 通过形态 |
|---|---|---|
| `enterprise-code` | 入参 | 符合 `^[a-z0-9][a-z0-9_-]{1,31}$` 且非 10 个保留字之一 |
| `download-page` | `{site}/download` | 200 + `text/html` + 正文含「观星台终端」（挡 SPA fallback 假 200） |
| `terminal-dir-redirect` | `{app}/terminal` | **301** → `/terminal/` |
| `windows-manifest` | `{app}/terminal/latest.json` | 字段齐 + `sha256` 64 位 + `size`>0 + 载荷 200 且大小一致 |
| `android-manifest` | `{app}/terminal/android/latest.json` | 同上 + `versionCode` 正整数 |
| `bmini-report-page` | `{app}/b/report/` | 200 + HSTS + nosniff + CSP |
| `worker-h5-page` | `{app}/w/` | 200 + HSTS + nosniff + CSP |
| `shortlink-json-contract` | `{app}/s/<未知码>/json` | **404 + `application/json` + `{"error":"not_found"}`**；给了真码时还与 302 面 token 逐字一致 |
| `tenant-binding-{worker,order}` | `{app}/s/<码>`、`{app}/o/<码>` | 302 + 落点 `tenant_code` == 入参企业编码 |
| `headers-*` | 上述各面 | HSTS + nosniff（另 `/download` 也要） |

### 5.3 实测读数（2026-10-31 15:25 +08，`rc=3 passed=9 failed=0 unknown=3`）

```
✅ enterprise-code          demo-customer
✅ download-page            200 text/html，正文含「观星台终端」（29600 bytes）
✅ terminal-dir-redirect    301 → https://app.migaozn.com/terminal/
???? windows-manifest       /terminal/latest.json 404 未发布（先跑 terminal-publish.yml，见 §2）
???? android-manifest       /terminal/android/latest.json 404 未发布
✅ bmini-report-page        200 text/html（HSTS+nosniff+CSP）
✅ worker-h5-page           200 text/html（HSTS+nosniff+CSP）
✅ shortlink-json-contract  未知码 ⇒ 404 application/json + not_found
???? tenant-binding         缺 --worker-code / --order-code ⇒ 无法核企业编码归属
✅ headers-site-download    HSTS+nosniff
```

**这三条 `????` 就是现在**不能**发给客户的原因**：终端还没发布（装不上）、没有印出来的码（核不了归属）。
它们是**开通前置未执行**，不是线上缺陷 ⇒ 落 `3`，而 `3` **不得当 `0` 读**。

### 5.4 验收红线

- **只读**：脚本全 GET/HEAD，无登录、无 POST、无写盘（判据 = 测试里的 `test_check_script_is_read_only`）。
- **不写生产数据**：不建租户、不建号、不报工 —— 这些是 §7.2 人工步骤，出了事要能说是谁做的。
- **安全头的深度判定不在这里**：`max-age` 下限 / CSP 形态 / 各域全覆盖归
  `bash deploy/scripts/prod-security-headers.sh`（§6.2）。

---

## 6. 试用期（支持 / 周检 / 升级 / 回滚 / 退出）

### 6.1 谁看什么（值班面）

| 频率 | 谁 | 做什么 | 时长 |
|---|---|---|---|
| **每天** | 值班（研发轮值） | 跑一次 `trial_onboarding_check.py`（rc≠0 ⇒ 按 §6.3 分流）；看四端探活（§6.2 第 1 条） | 15 分钟 |
| **每周** | 试用负责人 | §6.2 周检清单逐条跑，读数贴进试用台账 | 30 分钟 |
| **每月** | 研发 | 回滚演练（**只在测试环境**，见 [rollback.md](rollback.md) §2） | 1 小时 |
| **随时** | 客户成功 | 收集现场问题 ⇒ 归类 P0/P1/P2（§6.3） | —— |

> ⚠️ **没有告警通道**：生产可观测性（5xx / CPU / 磁盘触达值班）在审计 P0-04 里是**未落地**项
> ⇒ 试用期的「异常发现」**靠上面这张表和客户微信**，不靠告警。这是**接受的缺口**，
> 重启条件 = 可观测性落地（见 [production-deployment.md](production-deployment.md) §5 的必须项）。

### 6.2 周检清单（每条给命令 + 判读）

| # | 检查 | 命令 | 判读 |
|---|---|---|---|
| 1 | 四端探活 | `for u in https://api.migaozn.com/api/version https://ai-api.migaozn.com/health https://merchant.migaozn.com/login; do printf '%s -> ' "$u"; curl -s -o /dev/null -w '%{http_code}\n' -m 10 "$u"; done` | 三条全 200；**别用 `/actuator/health`**（nginx 整段 404，见 rollback.md §1） |
| 2 | 开通面 | `python3 scripts/trial_onboarding_check.py --enterprise-code <码> --worker-code <码>` | `rc=0` 才算这条过；`3` 要写明缺什么 |
| 3 | 安全响应头 | `bash deploy/scripts/prod-security-headers.sh` | `rc=0`；`1` = 确定缺头；`3` = 探不到（**不当 0 读**） |
| 4 | TLS 证书 | `bash deploy/scripts/tls-expiry-check.sh` | `rc=0`（剩余 ≥21 天）；`1` = 临期/过期/SAN 不覆盖；`3` = 取不到证书 |
| 5 | 线上是否本次构建 | `bash deploy/scripts/served-version-verify.sh` | 版本自证（「推没推」≠「线上是它」） |
| 6 | **DB 增长率** | ❌ **`scripts/db_growth_readout.py` 不存在**（`grep -rln "db_growth_readout" .` 零命中） | 替代动作：DBA 在 PG 侧跑**只读**统计（`pg_database_size` / 表行数快照）并人工记入台账。**缺口已登记**（§9） |
| 7 | **RDS 备份窗口 / PITR** | ❌ **`scripts/rds_backup_window_readout.py` 不存在**（同上零命中） | 云控制台侧，**公网不可判定**（与审计 P1-07 同结论）⇒ 每周由 DBA 截图备份策略页留证。**缺口已登记**（§9） |
| 8 | 客户端版本分布 | 下载页 + 终端「检查更新」日志 | 老版本占比高 ⇒ 说明更新链路没走通（§2.5） |

> 🔴 第 6、7 条**原来是任务清单里点名的脚本，仓内不存在** —— 这里照实登记成缺口，
> 用「DBA 只读 + 人眼留证」替代，**不**假装有机械判据（铁律 11：转述即未核实）。
> 补齐方式见 §9「重启条件」。

### 6.3 P0 / P1 / P2 升级路径

| 级别 | 判定（命中任一） | 谁决定 | 动作 | 时限 |
|---|---|---|---|---|
| **P0** | ① 登录/报工**全不可用** ② **跨租户**读到别家数据 ③ 涉钱写入错（退款/改价/计件） ④ 全站 5xx / 证书到期 ⑤ 纸上码落到别家企业 | 值班当场定，**不需要审批** | ① **暂停新客户上线** ② 按 [rollback.md](rollback.md) §1 自检三条判据 ③ 回滚（§2）④ 在同一 issue 里写时间线 + 影响面 | 立即（15 分钟内给出「已止血/未止血」） |
| **P1** | 单面不可用但**有绕行**（例：小程序 A 档不通 ⇒ 用相机扫 302 面；更新链路不通 ⇒ 手动传包） | 值班定 | 记 issue、给客户绕行方案；当天排修复 | 24 小时内 |
| **P2** | 体验/文案/打印版式 | 试用负责人 | 进下一批迭代 | 按排期 |

**升级时必带三样**：① 复现步骤 ② 判定用的**原始读数**（脚本输出 / curl 原文）③ 归属（哪一层：面 / 数据 / 终端 / 微信后台）。

**回滚**：仓内模块回滚见 [rollback.md](rollback.md) §1 判定信号 + §2 快速回滚；
**终端**回滚见 [terminal-release.md](terminal-release.md) §5（`terminal/` 子树整份覆盖；Android `versionCode` 必须**大于**线上，
否则已升级机器只能手动重装）；**小程序**回滚 = 重发上一版 h5（`bmini-h5-publish.yml`）+ 小程序重新上传旧版。

### 6.4 上线当晚的「最小值守」

- 21:00 前跑一次 §6.2 的 1/2/3 条，读数贴台账。
- 客户首单报工**当场**看一遍（现场或远程），截图归档。
- 客户反馈第一小时内**不改生产**（先记录，第二天按 §6.3 分流）—— 试用期改代码 = 把变量搅在一起。

### 6.5 退出与数据删除口径

| 动作 | 手段 | 可逆 | 说明 |
|---|---|---|---|
| **停用（推荐第一步）** | `tenants.status` 改为非 `active` | ✅ 改回即恢复 | 登录只在 `status='active'` 的租户里解析 ⇒ 全员**立即**登不进来（`AuthService.employeeLogin`） |
| **数据导出** | 管理员在该租户内自查导出（各列表页导出） | —— | 试用期结束前**必须**由客户确认收到导出件 |
| **删除** | ❌ **仓内无删除实现**（`grep -rln "deleteTenant\|dropTenant\|terminateTenant"` 零命中） | ❌ | 删除 = **人工工单**：先全量备份 + 逐表清单 + 双人复核；**不做**无人值守删除（铁律 10） |

> **接受的缺口**：没有自助注销、没有「按租户一键导出」、没有删除 runbook 的逐表清单。
> 试用期只有 1~2 家、且删除必须人工介入 ⇒ **重启条件 = 客户数 > 5 或出现「客户要求删除并审计」时**，
> 届时补：① 逐表删除清单（含软删除列）② 导出工具 ③ 审计留痕。

---

## 7. 两家客户的差异化 + 上线当天 checklist

### 7.1 差异矩阵（按客户填，别按模板发）

| 维度 | 客户 A（建议：**一体机为主**） | 客户 B（建议：**手持机为主**） |
|---|---|---|
| 行业 | 窗帘成品加工（裁高/车位/烫工/质检/包装） | 布艺门店 + 代加工 |
| 规模 | 10~30 人，1 个车间 | 3~10 人，门店 + 小车间 |
| 终端组合 | **1 台 Windows 一体机**（裁床/质检岗）+ 0~2 台手持机 | **2~3 台商米手持机**（车位随手报工） |
| 用不用小程序 | **可以不用**（相机扫 `/s/` 走 302 面即可） | **建议启用**（工人习惯微信；A 档体验最好） |
| 二维码 | 任务卡（50×119）为主 | 部位码贴纸 + 加工单码（`/o/`） |
| 上线风险 | WebView2 缺失 ⇒ 白屏（§2.4） | 微信后台规则未发布 ⇒ 扫不进小程序（§8-①） |
| 先做哪家 | **先做 A**（依赖少、可控） | A 跑通后 1~2 周再做 B |

> 两家**不要同一天上**。同一天上 = 出问题时无法区分是「产品问题」还是「现场问题」。

### 7.2 上线当天 checklist（逐格勾选 + 截图留证）

| # | 步骤 | 谁 | 命令 / 动作 | 判据 | 留证 |
|---|---|---|---|---|---|
| T-2 | 租户已开、企业编码已确认 | 运营 | `/register` 或 super-admin 审批 | 客户确认编码 | 审批截图 |
| T-2 | 管理员能登、已改密 | 客户 | `merchant.migaozn.com/login` | 进得去工作台 | 首屏截图 |
| T-2 | 员工 + 工人工号/PIN 已建 | 运营 | `/employees`（员工页签 + 工人页签） | 每个工人都能用工号+PIN 登进 `/b/report/` | 工人列表截图 + **PIN 交付方式**（当面/短信，**别贴群**） |
| T-2 | 终端清单已发布 | 研发 | `gh workflow run terminal-publish.yml --ref main -f release_tag=<tag> …` | 脚本 `windows-manifest` / `android-manifest` 不再 `????` | 脚本输出 |
| T-1 | 终端安装包下载 + SHA256 核对 | 客户 IT | §2.2 命令 | 与清单 `sha256` 逐字一致 | 命令输出截图 |
| T-1 | 安装（APK 未知来源 / EXE WebView2） | 客户 IT | §2.4 | 首次启动能填企业编码 + 工号 + PIN 并进主界面 | 安装后首屏截图 |
| T-1 | 更新链路 | 研发 + 客户 IT | 终端「检查更新」 | 无新版本 ⇒ 不报错；有 ⇒ 出现提示 | 弹窗截图 |
| T0 | **只读验收** | 研发 | `python3 scripts/trial_onboarding_check.py --enterprise-code <码>` | `rc=0`（`3` **不算过**） | **完整输出**贴台账 |
| T0 | 业务数据就位（商品/客户/订单/加工单） | 客户 | PC 端建 1 个真实订单 → 生成加工单 → **实例化工序**（这一步才发码） | 加工单详情能看到码/打印入口 | 页面截图 |
| T0 | 打印 + 张贴 | 客户 | 任务卡/专属唛 | §4.1 码位合规、§4.2 张贴合规 | **拍摄贴好的实物** |
| T0 | 扫码链路 5 条 | 研发 + 客户 | §4.3 逐条 | 5 条全过 | 每条截图 |
| T0 | **首单报工** | 工人（客户在场） | 扫部位码 → 选工序 → 报工 | PC 端能看到这条报工 + 计件数 | 报工页 + PC 端截图 |
| T0 | 带真码复算 | 研发 | 脚本加 `--worker-code` / `--order-code` | `rc=0 passed` 且 `tenant-binding` 绿 | 脚本输出 |
| T0+1 | 客户反馈收集 | 客户成功 | 微信群 / 电话 | —— | 台账 |

**红线**：T0 的 `rc` 必须是 `0`。`3` 代表「有一项判定不了」——**判定不了就是没验收**，不许写成「已上线」。

---

## 8. 脚本判不了的外部项（必须人做，逐条登记）

| # | 外部项 | 现状 | 谁做 | 依据 |
|---|---|---|---|---|
| ① | **微信「扫普通链接二维码打开小程序」后台规则** | **未做**：规则 / 校验文件 / appid / 上传私钥 / 提审发布都在微信公众平台 | 用户（我们给步骤） | [wechat-mini-program-qr.md](wechat-mini-program-qr.md) §3 |
| ② | **终端仓出包**（`GuanxingtaiSetup.exe` / APK 的 Release 资产） | 终端仓**没有**发布 workflow（Windows 本地 `build/package.ps1`）⇒ terminal#12 | 终端仓 | [terminal-release.md](terminal-release.md) §2 |
| ③ | **`TERMINAL_REPO_TOKEN`**（跨仓读 Release） | 需人工 `gh secret set`（fine-grained PAT，仅 Contents: Read） | 用户 | 同 §3 |
| ④ | **Windows 代码签名** | **未签名**（DV TLS 证书不能做 Authenticode）⇒ SmartScreen | 商务/用户 | §2.3 |
| ⑤ | **Android keystore** | 自签，存终端仓 Secrets；换 key = 必须重装 | 终端仓 | §2.3 |
| ⑥ | **真机安装与现场网络** | 需人到现场（未知来源授权 / WebView2 / 反光） | 客户 IT + 我们 | §2.4 / §4.2 |
| ⑦ | **真机打印**（标签/三联纸/A4） | 未验证（只读审计覆盖不到） | 客户 + 我们 | 本文 §4.1 |
| ⑧ | **RDS 备份窗口 / PITR ≥14 天** | 云控制台侧，公网**不可判定** | DBA | §6.2 第 7 条 |
| ⑨ | **告警触达值班** | 未落地（审计 P0-04） | 研发 | §6.1 的缺口登记 |
| ⑩ | **短信通道**（管理员首登/工人 PIN 通知） | 走既有短信服务；**需确认余额与签名报备** | 运营 | —— |

---

## 9. 未覆盖 / 重启条件（如实登记）

| 缺口 | 为什么现在不做 | 重启条件 | 落点 |
|---|---|---|---|
| `db_growth_readout.py`（DB 增长读数） | 仓内**不存在**；新建要先定「增长看哪几张小表 + 阈值」 | 试用期出现「查询变慢」或数据库容量告警 | §6.2 第 6 条 |
| `rds_backup_window_readout.py`（备份窗口读数） | 云控制台侧、无 API 凭据；公网不可判定 | 拿到只读云凭据，或审计再要求一次 | §6.2 第 7 条 |
| 自助注销 / 按租户导出 / 删除逐表清单 | 客户数少、删除必须人工；无人值守删除**有意不做**（铁律 10） | 客户数 > 5，或客户要求「删除并审计」 | §6.5 |
| 小程序 A 档端到端真机验证 | 依赖 §8-① 的微信后台（用户侧） | 规则发布后：微信扫一次 + 截图，贴进试用台账 | §3.2 |
| 登录后的写链路（下单/报工/计件）自动验收 | 需要凭据；只读审计无凭据 | 给一个**试用租户的只读/测试账号**后可做成只读 GET 断言 | §1.2 |
| 终端签名自动校验（Authenticode / apksigner） | 公网读不到 | 终端仓在发布腿里做签名校验并把结果写进清单 | §2.3 |

> 本文件**不新增任何门禁、不改任何通过条件**；它是 runbook + 一个只读判据脚本。
> 判据脚本的红证在 `tests/unit_ci_workflows/test_trial_onboarding_check.py`（用例 **MC-012**）：
> 三态各一次 + 逐条注入式红证（清单未发布 / 语义坏 / 载荷大小不符 / 裸前缀 200 / SPA fallback 假 200 /
> 未知码 200 / 缺 HSTS / 码归属别家 / JSON token 不一致 / 连不上）。
