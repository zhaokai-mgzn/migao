# B 端小程序（黄金策商家端）怎么发体验版

> 定于 2026-11-21（issue #8980）。AppID `wx6ee2f682c1b4822c`（主体：杭州词元通达科技有限公司）。
> 本页是**唯一入口**：`scripts/bmini-experience.sh` 三条子命令。手工拼 `npm run build:weapp` 的旧写法见
> [wechat-mini-program-qr.md](wechat-mini-program-qr.md) §5，**已不作为发布路径**（那正是「忘一个常量就静默发错包」的来源）。

## 三行命令

```bash
./scripts/cut-release.sh                                                # ① 生产包从发布线构建（release ⊆ main）
scripts/bmini-experience.sh build  --env prod                           # ② 注入 cytda 三件套 → build:weapp → 产物断言
scripts/bmini-experience.sh upload --version 1.0.0 --desc "首个体验版"    # ③ 先断言、再上传（断言不过拒绝上传）
```

- `build` + `upload` 想一条命令跑完：`scripts/bmini-experience.sh all --version 1.0.0 --desc "…"`。
- 版本号**必须显式给**（脚本不自动递增、不从 `package.json` 猜）。
- 上传完成后到**微信后台 → 版本管理 → 选为体验版** —— 这一步命令行做不了
  （`miniprogram-ci` 只提供上传/预览，提审/发布是后台动作）。

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
| ③ | 体积 | 全部文件合计 < `2097152 × 90% = 1887436` 字节；超限打印顶层条目占比 top5 | 先看 top5 归因；根治是分包（[#8979](https://github.com/zhaokai-mgzn/migao/issues/8979)） |
| ④ | 不可判定 | dist 不存在 / 不是目录 / 不可读 / **空目录** / 缺 `python3` ⇒ 退 **3** | 先构建；`3` **不得当 `0` 读** |

退出码：`0` 全绿 / `1` 有判据不成立 / `2` 用法错误 / `3` **不可判定**。

### ⚠️ 体积判据的边界（实测，必须一起读）

dist 字节和**微信后台报的包体**不是同一个数。2026-11-21 同一份产物实测：

| 读数 | 值 |
|---|---|
| `dist` 字节合计 | 1,459,140 |
| 微信后台报的主包 | **2,079,753** / 上限 2,097,152（余量 **17KB**） |

折算比 ≈ **1.425**。⇒ **闸门绿 ≠ 微信还有余量**（那次闸门还剩 428,296 字节，而真实余量只有 17KB）。
因此脚本在体积段额外交代一行「参考折算」读数（**不是判据**，不改变退出码）；口径不一致本身已开单
[#8981](https://github.com/zhaokai-mgzn/migao/issues/8981)，在做分包（#8979）之前**别把闸门绿读成安全**。

## CI 侧接线

`.github/workflows/bmini-app.yml` 的 `build` job 在 `npm run build:weapp` 之后跑**同一份**断言脚本，且用
**`--env test`** —— 因为 CI 的构建**不注入**生产常量（既有行为不变）⇒ 产物就该是测试域。真正的生产包只在
发布时由 `build --env prod` 构建并断言。判据（含「脚本写了没人跑」的红证）= `tests/unit_ci_workflows/test_bmini_dist_assert.py`。

## 判据（本地可复算，零网络）

```bash
python3 -m pytest tests/unit_ci_workflows/test_bmini_dist_assert.py -q
bash -n deploy/scripts/bmini-assert-dist.sh
bash -n scripts/bmini-experience.sh
```

## 边界 / 未固化项（照实登记）

- **两条上传通道本 PR 都没有真跑过**（本次任务的边界 = 只改代码、不部署、不上传）。通道的**参数面**由桩判据钉住
  （`--upload-version` 而不是 `--version`；`--appid` / `--project-path` / `--private-key-path`），但「真机上传成功」
  仍未取证。重启条件 = 下一次真发体验版时把 `upload` 的实际输出贴进该次发布的记录。
- **体积口径**不一致见上文 + [#8981](https://github.com/zhaokai-mgzn/migao/issues/8981)（本页不假装已解决）。
- 判不了「产物能不能跑起来」（要真机/模拟器），也判不了微信后台的域名白名单。
- 分包（[#8979](https://github.com/zhaokai-mgzn/migao/issues/8979)）落地后，`bmini-assert-dist.sh` 的体积段须按
  `app.json` 的 `subPackages[].root` 剔除子包，否则闸门会比微信更严（会误红）。
