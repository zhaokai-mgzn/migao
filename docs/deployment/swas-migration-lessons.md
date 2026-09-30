# SWAS 部署迁移踩坑总结（2026-08-14/15 实战）

> 🔴 **2026-09-30 修订**：§一 的构建位置铁律**已被推翻并改写**（用户裁定 C′ = 服务器侧构建），
> 见 §1.1 现行口径 / §1.2 裁定记录与新证据 / §1.3 未固化边界 / §1.4 已不适用原文。
> §二.2「并发部署互踩」同批补了 C′ 下的处置。
>
> 用途：后续换部署平台、改 CI、迁移 compose、或部署类问题排查时，先读本页，避免重踩。
> 关联：`deploy/swas/deploy.sh`、`deploy/swas/docker-compose.yml`、`deploy/scripts/swas-deploy-ci.sh`、三个 `deploy-*.yml`。

## 一、部署模型（构建到底放在哪）—— **本节于 2026-09-30 被推翻并改写**

### 1.1 现行口径（2026-09-30 起）

**现行铁律：构建跑在 SWAS 服务器侧（`deploy/swas/deploy.sh` 内、其 flock 之内），
CI 只下发源码与驱动参数，`docker build` 的产物就地使用、不进 ACR。**

| 阶段 | SAE 时代 | SWAS 迁移初期（旧文档判为「错」） | 2026-09-30 之前 | **现在（2026-09-30 起）** |
|---|---|---|---|---|
| 构建位置 | CI | SWAS 服务器源码构建 | CI + 推 ACR | **SWAS 服务器源码构建（C′）** |
| 服务器动作 | 拉 jar/镜像 | 自己 build 3 个服务 | `pull + up` | **`docker build`（一个服务）+ `up`** |
| 单路耗时 | ~2-3min | 10-30min（**冷构建**） | 推送挂死 33-45min | **稳态改代码 2s／冷构建 29.7min** |
| 推 ACR | 是 | — | **是（事故根因）** | **否（根本不推）** |

> 换部署目标时，先对齐"构建在哪、服务器做什么"，别默认照搬旧脚本。

### 1.2 这条铁律**为什么被推翻**（裁定记录，必须有）

- **裁定日期**：2026-09-30。
- **裁定人**：用户（逐字：「**C′ 就是要迁服务器构建，铁律我来拍**」；并表态「如果必要我会扩容磁盘」）。
- **被推翻的旧结论**：本节原文（2026-08-14/15 实战）写的是
  「**铁律：构建跑在 CI（强机器、可并行、有缓存），服务器只拉预构建产物。**」，
  并把「SWAS 服务器源码构建」在对照表里标为 **「迁移初期（错）」**、记「自己 build 3 个服务（10-30min）」。
- **新证据（真机实测，`swas-open run-command` 现取，2026-09-30）**：

  | 场景 | 实测 |
  |---|---|
  | 冷构建（无缓存，国内 apt+pip 镜像；ai-agent 最重） | **1782 s（29.7 min）** = apt 1100 s + pip 675 s |
  | 代码未变的重复构建 | **1 s**（全层 CACHED） |
  | **改一个源码文件（日常部署的真实路径）** | **2 s**（apt/pip 层全 CACHED） |
  | 改 `requirements.txt`（依赖变更） | **592 s（9.9 min）**（apt 仍 CACHED，只重建 pip 层） |
  | 内存峰值 | **1792 MB**（可用从未低于 5669 MB）⇒ 内存不是问题 |
  | 磁盘 | 每次构建净增约 1 GB；构建缓存已 1.36 GB；**剩余 16 GB 是真约束** |
  | 服务器 | `x86_64` / 4 核 / 7462 MB / **磁盘 40 GB（不是 70）** / Docker 26.1.3 / Alibaba Cloud Linux 3 |
  | **默认 apt 源（不换镜像）** | 实测跑 **4009 s 仍未下完 189 MB（164/≈240 包）** ⇒ **不可用** |
  | 换 `mirrors.aliyun.com` | apt 降到 **1100 s**（吞吐 855.6 KB/s vs 94.9 KB/s ≈9×） |

  ⇒ 旧铁律记的「10–30min」是**冷构建**读数；**稳态（只改代码）是 2 秒**，且**根本不推 ACR**
  ⇒ 「从境外 GitHub 托管 runner 跨境推 1.12 GB 镜像到阿里云 ACR 会挂住」这个根因
  **从结构上消失**（旧形态实测：`Build and push` 步 32 个样本双峰 `2.0~4.2min`（健康）
  vs `11.7~43.4min`（病态，中位 37.6–40.2 min），被 job 的 `timeout-minutes: 45` 打死 ⇒ `cancelled`；
  失败率随镜像体积单调上升：admin-api 302MB→1/6、admin-web 954MB→2/6、ai-agent 1.12GB→**3/6**）。

- **配套前置（缺一不可，否则 C′ 不可用）**：① `APT_MIRROR` 参数化（默认 `deb.debian.org` 保持现状，
  服务器侧传 `mirrors.aliyun.com`）；② 服务器侧 pip 源改传国内 PyPI 镜像；③ 构建缓存必须保留
  （稳态秒级全靠它）；④ 磁盘余量监控/回收；⑤ 构建进 flock。
- **落地形态**：`deploy/swas/deploy.sh` 的 `BUILD_SERVICE` 段（在**同一把** flock 之内）+ 三个
  `deploy-*.yml` 传各自的服务键；判据 = `tests/unit_ci_workflows/test_swas_server_side_build.py`。

### 1.3 未固化 / 边界（照实登记，**不粉饰**）

- **冷构建 29.7 min**：某服务首次构建（或缓存被清）时仍要这么久；日常「只改代码」才是 2s。
  故**别拿冷构建读数当稳态**，也**别清掉构建缓存**（`docker builder prune -af` 是禁手）。
- **磁盘 16 GB 是真约束**：每次构建净增约 1 GB ⇒ 余量监控与回收是前提
  （可回收：`/opt/migao` 有 2026-08-13 遗留的 **2.2 GB** 旧源码克隆；`docker image prune` 约 2.4 GB）。
- **构建与线上测试环境抢 4 核**：内存峰值实测 1792 MB、可用从未低于 5669 MB（内存不是瓶颈），
  但**构建期间对线上延迟的影响未测** ⇒ 登记为缺口。
- **运行期读数**（冷构建/稳态秒数）**不进判据**：静态判据只钉住参数与形态，读数只作证据。

### 1.4 旧文档本条目的原文（保留作历史事实，**已不适用**）

> ~~**铁律：构建跑在 CI（强机器、可并行、有缓存），服务器只拉预构建产物。**~~
> ~~| 阶段 | SAE 时代 | SWAS 迁移初期（错） | SWAS 现在（对） |~~
> ~~| 构建位置 | CI | **SWAS 服务器源码构建** | CI |~~
> ~~| 服务器动作 | 拉 jar/镜像 | 自己 build 3 个服务（10-30min） | `pull + up`（秒级~1min） |~~
> ~~| 单路耗时 | ~2-3min | 10-30min | 3-7min（CI 构建占大头） |~~
>
> ⚠️ 上面三行是 **2026-08-14/15 的当时事实**，已被 2026-09-30 的裁定取代（理由见 §1.2）。
> 保留它是因为「当时为什么这么判」本身是有用信息（冷构建确实 10-30min）；**但不得据此行事**。

## 二、踩过的坑 → 现象 → 根因 → 规避

### 1. 误报服务下线（查了不存在的域名）
- 现象：一直报 admin-web 000，排查半天，实际前端是好的。
- 根因：`admin.migaozn.com` **没有 DNS 记录**，真实前端入口是 `migaozn.com` / `www` / `merchant` / `ops`。
- 规避：**健康检查先 `nslookup` 域名**，确认有解析再 curl；别拿无解析域名当服务状态依据。

### 2. 并发部署互踩（单机 flock 缺失）
- 现象：main 合并同时触发 3 个 deploy，单机并发 `docker build`，容器互踩。
- 规避：服务器脚本用 `flock` 串行化（已内置在 `deploy.sh`）。
- **2026-09-30 补充（C′ 下的处置）**：C′（§1）**重新引入了单机 `docker build`** ⇒ 本条的风险面回来了。
  处置 = **构建放在既有那把锁之内**：`deploy.sh` 第 1 段 `exec 9>"$LOCK"` 拿锁、`trap 'flock -u 9' EXIT` 释放，
  C′ 的 `docker build`（`BUILD_SERVICE` 段）就在这两者之间 ⇒ 后到的 run 要么等锁、要么等 600s 超时退出
  （与既有部署等待语义一致，**未新增第二把锁**；同一把锁在 `deploy.sh` 内**不得重复获取**，会自锁）。
  判据 = `tests/unit_ci_workflows/test_swas_server_side_build.py` 的 `test_build_happens_inside_the_existing_flock`
  （含「锁获取只允许一处」的机械断言）。

### 3. aliyun CLI 是「移动目标」
- 现象：同一份脚本，上午能跑、晚上挂；报 `'RunCommand' is not a valid api`、`unknown flag: --InstanceId`、`--biz-region-id is required`。
- 根因：`aliyun-cli-linux-latest-amd64.tgz` 的 **latest 版本会变**，新版把 API 名和参数逐步改成 kebab-case：`RunCommand→run-command`、`--InstanceId→--instance-id`、region 参数是 `--biz-region-id`。
- 规避（`swas-deploy-ci.sh` 已做）：① kebab/Camel **双兼容**（kebab 失败遇 "not a valid api"/"unknown flag" 回退 Camel）；② **失败时打印完整 CLI 报错**（别 `2>&1` 吞掉 stderr）；③ 首选**锁 CLI 版本**而不是 latest。

### 4. RAM 子账号权限（403 NoPermission）
- 现象：RunCommand 返回 `403 NoPermission ... swas-open:RunCommand`。
- 根因：CI 用的 AccessKey 是新迁移子账号，只有 OSS 权限，没有 SWAS 权限（旧部署其实是服务器侧手动做的，CI 从未真跑过）。
- 规避：① 换部署平台先核对 RAM 权限；② **从 403 的 `AuthPrincipalDisplayName`/`AuthPrincipalOwnerId` 读出确切子账号 UID**，再让用户精准授权，避免赋错账号。

### 5. 服务器脚本不自愈
- 现象：改了仓库里的 `deploy.sh`，部署行为不变。
- 根因：CI 调的是服务器上 `/opt/migao-deploy/deploy.sh` **手工副本**，仓库改动不同步。
- 规避：CI 每次先从 codeload 拉最新 `deploy.sh` 覆盖服务器副本再执行（已内置）。
- **2026-09-30 补充（C′ 的关键前提）**：这条规避正是 C′ **不需要新下发通道**的原因 ——
  `deploy.sh` 第 1 段本来就把**整棵仓库树**（与镜像 tag 同源的 codeload tarball）解到 `src/`，
  此前只为取 4 个配置文件、取完就闲置 ⇒ C′ 直接**复用这棵树**当构建上下文（零额外下载）。
  实测边界（同一通道）：`swas-open RunCommand` 的**命令体上限仅 43.8–50.7 KB**
  （38 000 字节正文 = 50 769 字符即被拒，`400 CmdContent.ExceedLimit`），
  而三服务源码树 gzip 后仍有 1.7–2.8 MB ⇒ **「一次 Base64 下发源码」不可实现**，
  必须走「服务器自己拉」这条路。
  ⚠️ **若将来转 private，则「私有可达的下发通道」成为**硬前置**（匿名 codeload 会 404，三条腿全断）。
  **集成侧已裁定：暂不转 private**（保持 public ⇒ 托管分钟免费；转 private 的动机「给自托管 runner
  提供安全边界」已随「不再用开发机当 CI 执行面」消失）⇒ 这**不是当前阻塞**，而是**转 private 的前置条件**。
  本单**不解**它（候选与实测代价见 PR body 的缺口节）。

### 6. 杭州机房访问 GitHub 域名
- 现象：`curl (56) SSL_ERROR_SYSCALL errno 110`。
- 根因：SWAS（杭州）访问 `raw.githubusercontent.com` 超时；`codeload.github.com` 可达。
- 规避：服务器拉源码统一走 **codeload.github.com**。

### 7. 容器重建后 nginx 502
- 现象：容器换镜像重建后，外部访问 502，但直连容器端口 200。
- 根因：nginx 启动时缓存了旧上游 IP（`proxy_pass http://ai-agent:8000`），容器重建 IP 变了。
- 规避：`docker compose up` 后 **`docker compose restart nginx`**。

### 8. 镜像化 compose 迁移丢配置
- 现象：换镜像模式后 ai-agent 容器起不来，502。
- 根因：canonical compose 漏了旧 compose 里硬编码的 `JWT_PUBLIC_KEY`；ai-agent 的 `config.py` 对缺失配置 **fail-fast 启动崩溃**。
- 规避：**迁移 compose 时逐服务 diff 旧 `environment:` 块**；公开密钥可入仓，私钥走 env_file。

### 9. nginx `depends_on` 连带拉缺失镜像
- 现象：某服务镜像尚未推送时，`up -d nginx` 因 depends_on 连带拉取该服务而失败。
- 规避：反代**不设 depends_on**；`up -d --no-deps`；逐服务 `pull`、缺失则跳过（首启容错）。

### 10. 多服务共用一个 compose + `:latest` 的 tag 漂移
- 现象：首次接入时，部分服务镜像还没推过 `:latest`，整体 pull 失败。
- 规避：每路 CI 都 push `:latest`；deploy.sh **逐服务 pull + 缺失跳过**，渐进补齐。

### 11. 服务器拉 ACR 需要登录
- 现象：`pull access denied ... may require 'docker login'`。
- 规避：CI 用已有 ACR 凭据写服务器 `.env.registry`，`deploy.sh` 检测到即 `docker login`（已内置）。

## 三、非部署的坑（QA/用例/前端，也在这轮踩过）

### 12. GitHub Secret 混入非 ASCII
- 现象：smoke 秒失败 `SERVICE_TOKEN 含非 ASCII 字符`。
- 根因：secret 里被贴了中文注释「（与云端一致）」。
- 规避：local_runner 已有 fail-fast 校验；secret 值只放纯 token，注释别进 value。

### 13. G5 测试文件判定过宽
- 现象：QA Growth Gate 把 `.sh`/`.md`/runner/生成物当「测试文件」误报 4 blockers。
- 规避：`_is_test_file` 只认「代码扩展名 + 文件名含 test/spec」，conftest/runner/生成物排除。

### 14. 行为用例期望 vs 真实设计流程
- 现象：smoke 持续失败，其实是用例写错了，不是米宝缺陷。
- 根因：OR-010 设计是「澄清+确认」多轮，用例写成单轮直下单；改价格设计走 `product_update`，用例却期望 `product_manage(action=update)`。
- 规避：**用例按 `SKILL-*.md`/`EXAMPLES-*.md` 校准**，先看技能文档再定 expectations，别拍脑袋。

### 15. 前端 flaky 测试（waitFor 不完整）
- 现象：`dashboard.test.tsx` 偶发 `expected null to be truthy`。
- 根因：`waitFor` 只等标题文本，没等 recharts SVG 异步挂载。
- 规避：**waitFor 包裹最终断言**（polyline/path/linearGradient 全就位）。

### 16. agent-eval 写操作用例污染生产 + 幂等写变 no-op → flaky
- 现象：`Agent Eval (smoke tier)` 随机失败，flaky 点是 `PR-010` 的「把价格改成 199」偶尔不调 `product_update`。
- 根因（两层）：
  1. agent-eval 跑在**生产**（`ai-api.migaozn.com` / `api.migaozn.com`），`PR-010` 是**写操作用例**（`product_update` + `product_processing_item_manage`）。
  2. 测试商品「2699 系列雪尼尔窗帘」种子统一定价就是 ¥199，所以「改成 199」是**幂等 no-op**，LLM 正确识别「已经是 ¥199，无需修改」而跳过 `product_update`，用例却硬性期望它被调用 → 随机 fail。
- 隐藏 bug：runner 的「数据隔离」快照关键词是「遮光窗帘」，命中的是「米白色遮光窗帘」，**快照/恢复错了商品**（PR-010 实际改「2699 系列雪尼尔窗帘」），改价后根本没被恢复。
- 关键：**LLM 跳过 no-op 是正确行为**，不是 bug。
- 最终修法（写操作价值保留，不降级只读）：
  1. **写目标值用非种子值**（`199 → 198`），使写成为真实变更，避免幂等 no-op；
  2. **快照/恢复覆盖全部被改商品**（`2699` + `遮光窗帘` 都备份恢复），修掉错商品快照；
  3. 写用例回归 smoke，确定性运行（本地 3 连跑全过 + 价格恢复 199 无漂移）。
- 教训：写操作用例要确定性，三件套缺一不可——「非种子目标值 + 正确快照恢复 + 保持写操作覆盖」；单纯「降级只读」是回避，不是根治。

## 四、操作纪律（全程教训）

1. **永远走 PR 合 main**，不要 `git push` 直推 main（即使能推）。
2. 部署类改动合入后，**三个 workflow 串行验证一遍**（首启要推齐各服务的 `:latest`）。
3. 服务健康以**真实入口域名 + 外部 curl** 为准，容器端口/直连只能作辅助。
4. 改动涉及密钥/权限时，**从报错里挖出精确主体**（子账号 UID、错误 Code/Message），再让人授权，别猜。
5. `latest` 类「移动目标」（CLI、镜像 tag）要么锁版本，要么双兼容 + 完整报错日志。

## 五、JWT 认证与密钥管理坑（2026-08-15）

### 1. RSA 私钥被 gitignore → 镜像无 key → 静默降级 HS256 →「alg not allowed」

- 现象：米宝「新建会话」（`POST /api/chat/sessions`）返回 `401 TOKEN_INVALID: The specified alg value is not allowed`。
- 根因：`backend/admin-api/src/main/resources/rsa/private.pem` 被 `.gitignore`（`**/rsa/private.pem`）排除、**从未进仓库**，因此也没进 Docker 镜像。admin-api 生产容器里没有 RSA 私钥，`JwtTokenProvider.init()` 静默回退 HS256（每次启动随机密钥）→ 签出 `alg=HS256` 的 token；而 ai-agent-service 的 `verify_jwt_token` 写死 `algorithms=["RS256"]` → 拒绝为 TOKEN_INVALID。
- 修复（PR 走研发闭环）：`JwtTokenProvider` 改为 **RS256-only + fail-fast**（密钥缺失抛 `IllegalStateException`，不再静默降级），并让私钥/公钥**各自独立加载**（`JWT_PRIVATE_KEY_PEM` 单独即可生效，公钥走 classpath）。
- 规避/必做：生产 `.env.admin-api` 必须注入 `JWT_PRIVATE_KEY_PEM`（PEM 内容，与 ai-agent 的 `JWT_PUBLIC_KEY` 是同一对；本地 gitignored 的 `rsa/private.pem` 即匹配的私钥）。**没配私钥就合入部署 → fail-fast 会让 admin-api 启动即崩**（比「聊天坏」更糟）。

### 2. CI 缺 private.pem → 单测全红（fail-fast 把历史隐患暴露出来）

- 现象：改完 fail-fast 后，`admin-api unit tests` 在 CI 全红，本地却全绿。
- 根因：`SecurityConfigTest` 等 `@SpringBootTest` 会实例化真实 `JwtTokenProvider` bean，走 `classpath:rsa/private.pem` 加载；CI 干净 checkout 里没有这个 gitignored 文件 → `init()` fail-fast 抛异常 → 上下文初始化失败；`JwtTokenProviderTest.readResource("/rsa/private.pem")` 也读不到。
- 规避：提交**测试专用** RSA 密钥对到 `src/test/resources/rsa/{private,public}.pem`（非敏感），并在 `.gitignore` 加例外 `!backend/admin-api/src/test/resources/rsa/private.pem`。测试专用密钥对不参与生产签名，安全无碍。

### 3. 本地开发环境要能连上「云 dev RDS」

- 现象：本地起 admin-api 报 `CannotGetJdbcConnectionException ... SocketTimeoutException`，MigrationRunner 迁移失败；ai-agent 同样 `Failed to initialize database connection`。`curl` 健康检查 HTTP 000 / 502。
- 根因：云 dev RDS（`pgm-*-pub.pg.rds.aliyuncs.com:5432`）对当前机器公网出口 IP 未放行（`nc -z` 5432 超时；Redis 6379 正常）。
- 规避：把本机公网出口 IP 加进 RDS 安全组白名单（或走 VPN 到 VPC）。改 IP 后**重启服务**，DB 相关流程（登录/建会话）才可用。
