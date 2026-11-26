# B 端小程序（黄金策商家端）怎么发体验版

> 定于 2026-11-21（issue #8980）。AppID `wx6ee2f682c1b4822c`（主体：杭州词元通达科技有限公司）。
> **发布路径 = 一条命令** `scripts/bmini-release.sh`（2026-11-23 起，issue #9069）：它把下面「底层三步」按
> 安全顺序串起来，并把**三处人肉记忆**（顺序 / 只在部署机 / 上传后回填 `TOTAL`）变成判据。
> 底层三步仍是**判据本体**（`scripts/cut-release.sh` / `scripts/bmini-experience.sh` /
> `deploy/scripts/bmini-assert-dist.sh`），一条命令只编排、不自造。手工拼 `npm run build:weapp` 的旧写法见
> [wechat-mini-program-qr.md](wechat-mini-program-qr.md) §5，**已不作为发布路径**（那正是「忘一个常量就静默发错包」的来源）。

## 一条命令（底层三步仍在）

在**部署机**上（`ssh migao-deploy`；生产包只在部署机构建 + 上传 —— 2026-11-23 用户裁定，见 §一）：

```bash
scripts/bmini-release.sh --upload --version 1.0.3 --desc "这次发了什么"
```

它按**顺序即安全顺序**走六道关，任一道不成立就当场拒绝（不猜、不自动放行）：

| # | 关 | 判据 | 不满足时 |
|---|---|---|---|
| ① | **机器闸门** | 本机身份 == `ssh -G migao-deploy` 解析出的 `HostName`（**不写死 IP**：那台机器走 DHCP） | 退 **1**，具名打出两台机器的读数 + 三个出口（`ssh migao-deploy` 去部署机 / 改 ssh 别名 / 只构建不发布）；读数拿不到 ⇒ 退 **3** |
| ② | **顺序闸门** | `origin/release` ⊆ `origin/main`（复算 = `scripts/cut-release.sh --check`，退 2 即旁路）**且** 本检出 `HEAD == origin/release` **且** 无未提交改动 | 退 **1**，出口 = 在部署机上跑 `./scripts/cut-release.sh`（**cut 是显式动作，本脚本永不自己 cut**）；取不到远端 ⇒ 退 **3** |
| ③ | **构建** | 复用 `scripts/bmini-experience.sh build --env prod`（三个 `TARO_APP_*` 注入 + `build:weapp` + 产物断言，全是它的实现） | 退 1 |
| ④ | **上传前断言** | 再跑一次 `deploy/scripts/bmini-assert-dist.sh <dist> --env prod`（dist 可能是上一次留下的） | 不过 ⇒ **拒绝上传**（1 / 不可判定 3） |
| ⑤ | **上传** | 复用 `scripts/bmini-experience.sh upload --env prod --version <显式给的版本号>` | 退 1 |
| ⑥ | **回读 + 记录行** | 从上传日志抓 `TOTAL` 字节；`dist ÷ TOTAL` 必须落在「`deploy/scripts/bmini-dist-budget.json` 的 `calibration` 台账比值 ±3%」内 | 打印**可直接粘贴**进 §六 发布记录表的 Markdown 行；比值越界 ⇒ 警告并退 **3**（不静默通过）；抓不到 `TOTAL` ⇒ 退 **3** |

- **不带 `--upload`** ⇒ 只做 ①~④（构建 + 断言），明确打「未上传」，**不产出**记录行（没有 `TOTAL` 就不猜读数）。
  只想要「一个生产域产物 + 断言」也用它：`scripts/bmini-release.sh`。
- `--host-assert`：只判「本机是不是部署机」（零副作用，排障用）。
- 退出码沿用仓库三态：`0` 成功 / `1` 判红 / `3` **不可判定**（`3` 不得当 `0` 读）；用法错误 = `2`。
- 没有 `--env`：这是**发布**路径，恒为 `prod`（test 包那条腿是 `bmini-experience.sh build --env test`，不是发布）。

### 底层三步（一条命令调的就是它们；手工排障时按这个顺序）

```bash
./scripts/cut-release.sh                                                # ① 生产包从发布线构建（release ⊆ main）
scripts/bmini-experience.sh build  --env prod                           # ② 注入 cytda 三件套 → build:weapp → 产物断言
scripts/bmini-experience.sh upload --version 1.0.0 --desc "首个体验版"    # ③ 先断言、再上传（断言不过拒绝上传）
```

- `build` + `upload` 想一条命令跑完（**仍会跳过机器闸门与顺序闸门**，只在排障时用）：
  `scripts/bmini-experience.sh all --version 1.0.0 --desc "…"`。
- 版本号**必须显式给**（脚本不自动递增、不从 `package.json` 猜）。
- 上传完成后到**微信后台 → 版本管理 → 选为体验版** —— 这一步命令行做不了
  （`miniprogram-ci` 只提供上传/预览，提审/发布是后台动作）。
- 上传成功后，⑥ 打印的那一行**直接粘进 §六 发布记录表**（版本 / 时间 / 部署机与 `origin/release` sha /
  `TOTAL` 字节 / dist 字节 / 比值）；审核列与发布者列照旧人手填。

## 需要什么（一次配好，之后不用再想）

| 项 | 要求 | 谁配 |
|---|---|---|
| AppID | `wx6ee2f682c1b4822c`（脚本内置常量，不是密钥） | 仓库 |
| 构建入库 | **从 `release` 构建**（`git rev-parse origin/release`），不要拿停在旧特性分支的工作区构建 —— 2026-11-21 那次差点用「`truth.ts` 还写死 origin」的旧分支发出去 | 人 |
| 依赖 | `cd frontend/bmini-app && npm ci`（依赖装在**本工作区内**，别软链别的 worktree） | 人 |
| 上传通道 A（无 key 时走它） | macOS + 微信开发者工具**已登录**该小程序的开发者账号；「设置 → 安全设置」打开 CLI/HTTP 调用 | 人（本机） |
| 上传通道 B（有 key 时走它） | 小程序后台「开发管理 → 开发设置 → 小程序代码上传」生成的**代码上传私钥**（`private.<appid>.key`，**绝不入库**）+ 把出口 IP 加进**代码上传 IP 白名单**；传 `--key <路径>` 或设 `MINIPROGRAM_UPLOAD_KEY` | 人（外部后台） |
| 服务器域名白名单 | 后台「开发管理 → 开发设置 → 服务器域名」的 **request 合法域名**必须含 `https://app.cytda.com` | 人（外部后台） |

🔴 仓库侧**不代填、也判不了**上表里的账号 / 白名单状态（那是微信后台的状态，命令行读不到）。
特别是**服务器域名白名单**：2026-11-21 首次体验版上传成功，但上传前后 24h **零小程序流量**
⇒ 白名单是否已含 `app.cytda.com` 仍**未验证**（只能后台看，或等首次真机打开时从生产日志判定）。

## 注入了什么常量

| `--env` | `TARO_APP_API_URL` / `TARO_APP_AI_API_URL` / `TARO_APP_PUBLIC_APP_ORIGIN` |
|---|---|
| `prod`（`build`/`all`/`upload` 的**缺省**） | 三个都 `https://app.cytda.com`（该域的 nginx 已把 `/api/` 代理到 admin-api，与 h5 发布腿同一口径） |
| `test` | 三个都 `https://app.migaozn.com`（测试环境唯一合法域名） |

为什么缺省是 `prod`：本脚本的存在意义是**发布**。缺省 prod 时误跑一次只是「构建了一个生产包」（惰性、无害且会被断言验一遍）；
而缺省 test 时误跑一次会把**指向测试域的包**上传成体验版 —— 那正是本单要根治的形态。

> 三个常量都**必须在构建期**注入（`frontend/bmini-app/config/index.ts` 的 `defineConstants`）：
> 少给一个就回落到 `http://localhost:8080` / `:8001`，真机连不上，而开发者工具勾了「不校验合法域名」时看不见这个错。

## 产物断言：一条命令、四条判据

```bash
deploy/scripts/bmini-assert-dist.sh frontend/bmini-app/dist --env prod   # 也可 --env test（CI 用这个）
```

| # | 判据 | 口径 | 红了怎么处置 |
|---|---|---|---|
| ① | 结构 | `app.json` 的 `pages` 非空、`app.js` 在、每页 `.js` / `.wxml` / `.json` 齐备（`.wxss` **允许缺省**，Taro 对无样式页面本就不产出） | 重新构建；持续缺件看 Taro 编译日志 |
| ② | 域名策略 | `prod` ⇒ `migaozn.com` 出现 **0** 次、`cytda.com` **≥1** 次、**无 `localhost`**；`test` ⇒ 反向 | 别手拼构建：三个常量必须一起注入（`build --env prod`） |
| ③ | 体积 | **主包** ≤ 单包上限 − 主包预留（预留 = #8979 的 ≥300KB 余量）、**每个分包** ≤ 单包上限、**总包** ≤ 总包上限；常量**唯一来源** = `deploy/scripts/bmini-dist-budget.json`（主包上限 2,097,152 / 总包上限 20,971,520 / 主包预留 307,200） | 先看归因（哪个包 / 超多少字节 / 该包最大的文件 / 复算命令）；真的要降主包先看 §体积读数的 top 表 |
| ④ | 不可判定 | dist 不存在 / 不是目录 / 不可读 / **空目录** / 缺 `python3` ⇒ 退 **3** | 先构建；`3` **不得当 `0` 读** |

退出码：`0` 全绿 / `1` 有判据不成立 / `2` 用法错误 / `3` **不可判定**。

### 体积判据的口径（#8981 的收口：**等价**，不是 ×1.425）

判的是 **dist 字节**，它与微信开发者工具上传后报的 `TOTAL` **等价** —— 2026-11-23 部署机实测：

| 读数 | 值 | 怎么取的 |
|---|---|---|
| `frontend/bmini-app/dist` 字节合计 | **1,465,245** | `find frontend/bmini-app/dist -type f -exec cat {} + \| wc -c`（`~/prod/migao-bmini-main`，HEAD = `origin/release` `f78dff52c`） |
| 开发者工具上传后报的 `TOTAL` | **1,461,748** | 同一台机器 `scripts/bmini-experience.sh all --version 1.0.2 --env prod` 的输出 |

比值 **0.998** ⇒ dist 字节**略大于**上传读数，用 dist 判是**偏严**方向，**不叠折算系数**。
旁证：`~/migao-bmini-experience/dist.bak-11222310`（11-22 23:10 备份的生产域产物）字节合计 1,459,203，
与 [#8981](https://github.com/zhaokai-mgzn/migao/issues/8981) 记的 dist 1,459,140 只差 63 字节。

🔴 **那 `2,079,753` 是怎么回事**：它在部署机四份产物（1,459,203 / 1,465,247 / 1,840,656 / 1,465,245）里
一个都对不上；开发者工具日志（`~/Library/Application Support/微信开发者工具/**`；检索面 = `find … -newermt "2026-11-20"` 命中的
88 个文件，逐份 `grep -a "TOTAL\|2079753\|1461748\|包体\|包大小"`）里也没有留下带该数字的回执 ⇒ 登记为**不可复现读数**
（见 `deploy/scripts/bmini-dist-budget.json` 的 `unreproducibleReadings`）。
按它推出来的「×1.425」若当成口径，会把闸门错误压到 ≈1.47MB、**制造假红** ⇒ 已整块删掉，
原来那行「参考折算」读数也一并删除（它曾在 1,465,251 字节的产物上报出「余量 9,170 字节」这种假读数）。

### 体积读数（2026-11-23 实跑，用于判断「要不要分包」）

`./scripts/bmini-experience.sh build --env test` → `frontend/bmini-app/dist`，合计 **1,465,251 字节**（25 页 / 122 文件）：

| 组成 | 字节 | 占比 |
|---|---|---|
| `vendors.js`（webpack 第三方依赖） | 519,832 | 35.5% |
| `common.js` | 183,244 | 12.5% |
| `taro.js` + `app.js` + `runtime.js` | 237,232 | 16.2% |
| `base.wxml` + `common.wxss` + `utils.wxs` + `app-origin.wxss` | 72,821 | 5.0% |
| `pages/**`（25 页合计） | 433,509 | 29.6% |
| `assets/`（tabBar 图标等） | 14,770 | 1.0% |
| 其余（`app.json` / `*.LICENSE.txt` / `project.config.json` / `comp.*` / `app.wxss`） | 3,843 | 0.3% |

页面侧最大的几组：`pages/chat/index` 124,485（AI 对话）· `pages/worker/stock` 28,816 ·
`pages/worker/inbound` 24,291 · `pages/worker/shipment` 23,614。
被 #8979 点名的**四个管理页**（`pages/admin/{pool,inbound,after-sales,piecework}`）合计 **30,866 字节（2.1%）**。

⇒ **余量**：对 2MB 上限还有 **631,901 字节（30.1%）**，扣掉 300KB 预留后仍余 **324,701 字节**。
⇒ 按「不为拆分而拆分」：**本次不拆分包**。拆 4 个管理页只挪走 31KB（对 940KB 的 JS 主体无影响），
而主包离上限还有 30% —— 真正会撞线的是 JS 主体，那是「加依赖 / 加页」时才会发生的事。
分包判据**已就绪**（`subPackages[].root` 已实现并有真实形状红证），重启条件 = 主包余量 < 300KB
（判据会在那一刻先红，见 [#8979](https://github.com/zhaokai-mgzn/migao/issues/8979)）。

## CI 侧接线

`.github/workflows/bmini-app.yml` 的 `build` job 在 `npm run build:weapp` 之后跑**同一份**断言脚本，且用
**`--env test`** —— 因为 CI 的构建**不注入**生产常量（既有行为不变）⇒ 产物就该是测试域。真正的生产包只在
发布时由 `build --env prod` 构建并断言。判据（含「脚本写了没人跑」的红证）= `tests/unit_ci_workflows/test_bmini_dist_assert.py`。

## 判据（本地可复算，零网络）

```bash
python3 -m pytest tests/unit_ci_workflows/test_bmini_dist_assert.py -q     # 结构 / 域名 / 不可判定 / 发布入口
python3 -m pytest tests/unit_ci_workflows/test_bmini_dist_budget.py -q     # 体积判据 + 口径等价 + 单一来源元守卫
python3 -m pytest tests/unit_ci_workflows/test_bmini_release_one_command.py -q  # 一条命令的六道关（机器 / 顺序 / 断言 / 上传 / 回读 / 默认不上传）
bash -n deploy/scripts/bmini-assert-dist.sh
bash -n scripts/bmini-experience.sh
bash -n scripts/bmini-release.sh
bash -n scripts/cut-release.sh
```

## 边界 / 未固化项（照实登记）

- **上传通道实测状态（2026-11-23 更新）**：
  - **微信开发者工具 CLI 通道：已实测通过**。2026-11-23 10:06 在部署机（`ssh migao-deploy`，仓检出
    `~/prod/migao-bmini-main`，HEAD = `origin/release` `f78dff52c`）执行
    `scripts/bmini-experience.sh all --version 1.0.2 --env prod`：四条断言全绿 →
    `✔ Using AppID: wx6ee2f682c1b4822c` → `✔ upload`，开发者工具侧包体读数 **TOTAL 1,461,748 字节**
    （同日 dist 1,465,245）。**这两个读数的关系已收口**（等价，比值 0.998）——见上文「体积判据的口径」节；
    2026-11-21 记的那个 ×1.425（2,079,753）已登记为**不可复现读数**
    （[#8981](https://github.com/zhaokai-mgzn/migao/issues/8981)；台账 = `deploy/scripts/bmini-dist-budget.json` 的 `unreproducibleReadings`）。
  - `miniprogram-ci` 通道（私钥）：**仍未真跑过**，参数面由桩判据钉住
    （`--upload-version` 而不是 `--version`；`--appid` / `--project-path` / `--private-key-path`）。
    重启条件 = 首次真用时把 `upload` 的实际输出贴进发布记录。
- **体积口径**已收口（等价，见上文「体积判据的口径」）；`2,079,753` 登记为不可复现读数
  （[#8981](https://github.com/zhaokai-mgzn/migao/issues/8981) 的缺陷面 = 当时没人钉口径；现由预算文件的
  `calibration` 台账 + 元守卫（第二把尺子判红）承接）。判据 = `tests/unit_ci_workflows/test_bmini_dist_budget.py`。
- 判不了「产物能不能跑起来」（要真机/模拟器），也判不了微信后台的域名白名单。
- **分包（[#8979](https://github.com/zhaokai-mgzn/migao/issues/8979)）本次不拆**（照实登记）：实测主包余量
  631,901 字节（≥300KB 地板）、拆 4 个管理页只挪走 30,866 字节 ⇒ 不为拆分而拆分。
  判据侧**已就绪**（`app.json` 的 `subPackages[].root` 已实现：主包剔除子包、每包各自判、总包判，
  真实形状红证见上）；重启条件 = 主包余量 < 300KB（那时闸门会先红，读数与拆法都在本节）。

## 提审前检查清单（2026-11-23 实战沉淀）

> 起因：11-22 23:06 主工作区被裸 `build:weapp` 覆盖成指向 `http://localhost:8080` 的漂移包，
> 传成体验版后真机每个接口 `request:fail errcode:-102`（= `ERR_CONNECTION_REFUSED`）；个人信息页靠缓存
> 仍能渲染 ⇒ 现场看着像「网络异常」，实际是**包连的地址没人监听**。

### 一、生产包**只在部署机上构建 + 上传**（2026-11-23 用户裁定）

- 构建与上传**一律在部署机**（微信开发者工具已登录的那台 Mac）上执行：产物与「真正上传的那份」必须同机同源。
  开发机**只做只读判据复算**，不产出小程序包。
- 🔴 **不许写死 IP**：部署机走 DHCP，地址会变。一律用 **SSH 别名**（`~/.ssh/config` 里 `Host migao-deploy`）
  或 mDNS 名字（`<LocalHostName>.local`）；命令、文档、判据都只认别名。
- 为什么钉死：本机产出的包会堆在本地工作区，和真正上传的那份**脱钩**——11-22 23:06 主工作区被裸
  `build:weapp` 覆盖成指向 `http://localhost:8080` 的包，传成体验版后真机每个接口
  `request:fail errcode:-102`（= `ERR_CONNECTION_REFUSED`）。

```bash
# 以下命令在部署机上执行（本机用 ssh migao-deploy 进去；别记 IP）
scripts/bmini-release.sh --upload --version X.Y.Z --desc "…"   # 一条命令：机器闸门 → 顺序闸门 → 构建 → 断言 → 上传 → 回读

# 底层三步（排障时分开跑；见上文「底层三步」）
./scripts/cut-release.sh                        # 发布线 ⊆ main
scripts/bmini-experience.sh build  --env prod   # 四条断言全绿
scripts/bmini-experience.sh upload --version X.Y.Z --desc "…"
```

**本机不许直接 `npm run build:weapp`**：不注入三个 `TARO_APP_*` 时 `constants.ts` 会回落到
`http://localhost:8080`，包照样能传上去，只有真机才炸（开发者工具勾了「不校验合法域名」时连错都看不见）。

### 二、微信后台（仓库判不了，只能人看）

| # | 项 | 口径 |
|---|---|---|
| 1 | request 合法域名 | 含 `https://app.cytda.com`（不带路径/端口；每月 5 次修改机会） |
| 2 | **uploadFile 合法域名** | 同上——拍照入库 / 语音输入走 `Taro.uploadFile`，只配 request 会「扫码能用、一拍照就挂」 |
| 3 | 用户隐私保护指引 | 只勾 **照片/视频 + 摄像头 + 麦克风**；位置 / 蓝牙 / 设备信息必须不勾（代码已删声明） |
| 4 | 隐私指引状态 | **已通过**（不是「审核中」）；审核中隐私接口被拦截 ⇒ 审核员按「功能不完整」驳回 |
| 5 | 服务类目 / 小程序备案 | 与「商家经营助手 + 扫码 + 拍照」匹配；备案已通过 |

### 三、提审表单（可直接抄）

功能页面（1–5 条，按审核员先看什么排序）：

```
pages/chat/index/index          问黄金策（AI 对话）
pages/dashboard/index/index     经营数据看板
pages/worker/report/index       工人扫码报工
pages/worker/inbound/index      工人拍照入库
pages/auth/login/index          登录（三种身份入口）
```

审核备注必须给**能登录的生产账号**（不给 = 按「无法完整体验功能」驳回）：

```
本小程序为布艺/窗帘商家的内部经营助手，需登录后使用。
【商家端】用户名 xxx@<企业编码>，密码 ***
【工人端】工号 xxx，PIN ***
体验路径：登录 → 问黄金策 → 数据看板；工人端扫码报工（首次弹隐私授权属正常）。
```

### 四、错误码对照（先看真机 vConsole 里这一行）

| 文案 | 含义 | 处置 |
|---|---|---|
| `request:fail url not in domain list` | 域名没进白名单 | 补 request / uploadFile 列表，杀进程重进 |
| `request:fail errcode:-102` | `ERR_CONNECTION_REFUSED` | **包连的地址不对**（localhost / 测试域）⇒ 重新出 prod 包 |
| `request:fail timeout` | 手机网络 / 代理 | 换网络复测 |

### 五、提审之后

审核 1–7 天（每月 1 次加急，首版建议用）；驳回按原因改完可重提，**不要连提**；
通过后仍需在后台点「发布」才真正上线。

### 六、发布记录

| 版本 | 构建 + 上传 | 审核通过并发布 | 发布者 | 包体（devtools 读数） | 备注 |
|---|---|---|---|---|---|
| 1.0.2 | 2026-11-23 10:06 · 部署机 `migao-deploy`（`~/prod/migao-bmini-main`，HEAD = `origin/release` `f78dff52c`） | 2026-11-23 10:49:54 | 得胜 | 1,461,748 字节 | 首个线上版：生产域 + 隐私授权弹窗 + 登录页修复；审核「加急」档 |
| 1.0.1 | 2026-11-23 上午（来源待查） | — | — | — | **作废**：`request:fail errcode:-102`（连 `localhost` 的漂移包），未发布 |
| 1.0.0 | 2026-11-21 15:20（部署机手工 devtools CLI） | — | — | 2,079,753（后台读数） | 首个体验版；缺 `#9013` 隐私弹窗，未提审 |
