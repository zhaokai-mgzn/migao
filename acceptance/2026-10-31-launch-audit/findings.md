# findings — 上线前只读全量审计（issue #8197）

> 基线：`origin/main` @ `32d4066e7`（线上 admin-api `sha=32d4066e7…` 已核对，见 README §0）。
> 证据标记：**L** = 线上复探（命令可复制）/ **C** = 仓库 durable 证据（`路径::符号`，不写裸行号）/ **R** = CI 读数。
> 「空态/加载态」不作为通过证据（`docs/testing/smoke-data-quality.md` 的 `DQ-1/DQ-4`）。

## 总表

| ID | P | 面 | 证据（锚 / 线上读数） | 复现步骤 | 影响 | 建议 | 归属 |
|---|---|---|---|---|---|---|---|
| **P0-01** | P0 | 部署 / 全站 | **L** `openssl s_client … \| x509 -noout -dates` ⇒ `notAfter=Nov 27 10:29:18 2026 GMT`（merchant/api/ai-api/app **同一张证书**）；**C** `deploy/swas/docker-compose.yml::services`（只有 `admin-api/ai-agent/admin-web/nginx`，无 certbot 服务）；`.github/workflows/*` 无 renew 腿（`grep -rln certbot .github/workflows/` 空）；`docs/deployment/rollback.md` 无续期步骤 | 见 §P0-01 | **27 天后全站 HTTPS 中断**（四域同证书）；且已过 Let's Encrypt 建议的「剩 30 天」续期点（≈10-28）仍未续 ⇒ 续期链路事实上**此刻已失效** | 续期做成仓内可证（certbot 服务或续期 workflow + 失败告警）；把 `notAfter` 做成一条值守读数 | 部署 / 运维 |
| **P0-02** | P0 | C 端元元（暂缓）/ 发布 | **L** `curl -sI https://app.migaozn.com/js/app.js` ⇒ `last-modified: Sat, 24 Oct 2026 15:40:08 GMT`；**R** `gh run list --workflow=c-end-h5-publish.yml --limit 8` ⇒ **8/8 failure**（含 `2026-10-31T00:05:51Z` 的手动 dispatch，headSha=32d4066e7）；判据原文：`线上产物**陈旧**：2026-10-24T15:40Z 早于 frontend/mini-app 最近改动 2026-10-29T23:25Z（落后 5.0 天）`（`raw/07-cend-stale.txt`）；**C** `frontend/mini-app/src/utils/craft-display.ts` 最近改动 = `e0500beff`（在线上产物之后） | 见 §P0-02 | 试用客户打开的 C 端是 **5 天前**的构建：特殊选项（布绑带/纱绑带→绑带、余料带回）沿旧口径展示，而后端/知识库已是新口径 ⇒ **展示与落库分叉** | 人工发布一次（`-f publish=true`，用户 2026-09-27 裁定 B）+ 把该红腿的处置挂到值守面（当前红 8 次无人处置） | C 端 / 发布 |
| **P0-03** | P0 | admin-web + 四端前端 | **C** `find frontend -name error.tsx -o -name global-error.tsx` ⇒ **只有** `frontend/admin-web/src/app/(dashboard)/customers/error.tsx`（58 个 `page.tsx` 里唯一一个）；`frontend/admin-web/src/app/layout.tsx` 无错误边界；**C** `grep -rn "Sentry\|window.onerror\|unhandledrejection" frontend/*/src` ⇒ **0 命中**（四端零上报） | 见 §P0-03 | 任一页面渲染期异常（脏数据/接口形状变化）⇒ Next.js 默认错误页：**整页白屏 + 无重试出口**；且**线上发生无人知道**（无事件、无聚合） | 根级 `global-error.tsx` + 每个路由组 `error.tsx`；接最小上报面（失败也要有兜底） | admin-web / 前端基建 |
| **P0-04** | P0 | 可观测 / 部署 | **C** `docs/deployment/production-deployment.md::5. 生产安全基线` 把「SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）触达值班」列为**必须项**；仓库内 `grep -rln "sentry\|SLS\|alert" .github/workflows deploy/` 无告警实现；**L** 线上 `GET /api/version` 是唯一可信探针，`/actuator/health` 公网 404（`raw/01`） | 见 §P0-04 | 5xx / 白屏 / 证书到期 / 发布失败**都不会主动惊动人**；本项目自认的最大失败模式（告警疲劳 + 静默失败）在这里是"零告警"的极端形态 | 先落最小告警：外部合成探针（`/api/version` + `/b/` + `/w/`）+ 5xx 计数阈值 → 一个能真的响的通道 | 部署 / 运维 |
| **P1-01** | P1 | 发布 / AI | **L** `GET ai-api.migaozn.com/api/version|/version|/build-info` ⇒ **全 404**；对照 admin-api `/api/version` 200、admin-web `/version.json` 200；**C** `backend/ai-agent-service/app/main.py::health_check`（只有 `/health`、`/ready`，无 sha） | `for p in /api/version /version /build-info; do curl -s -o /dev/null -w "%{http_code}\n" https://ai-api.migaozn.com$p; done` | ai-agent 线上**跑的是哪个 commit 不可判定** ⇒ 发布漂移不可发现（admin-api 有 `sha`，它没有） | 加 `/api/version`（app/sha/builtAt），与 admin-api 同形 | ai-agent / 部署 |
| **P1-02** | P1 | 部署 / 容量 | **C** `deploy/swas/docker-compose.yml::services` 四个服务**均无 `logging:` 段**（默认 json-file，无 `max-size/max-file`） | `grep -n "logging" deploy/swas/docker-compose.yml`（空） | 单机 SWAS 上容器日志**无界增长** ⇒ 磁盘打满 → 四服务同时 502（`restart: unless-stopped` 救不了"写不进去"） | 每个服务加 `logging: options: max-size: 50m / max-file: 3`；加一条磁盘水位读数 | 部署 / 运维 |
| **P1-03** | P1 | 回归 / 可观测 | **C** `.github/workflows/nightly-verification.yml::on` 的 `schedule` **已被注释**（注释写明 2026-09-06 暂停，issue #2957「待根因排查 + 本地验证提速后恢复」）；**R** `gh run list --workflow=nightly-verification.yml` ⇒ 最后三次均 `workflow_dispatch` + `failure`（2026-09-14/15），**schedule 最后一次是 2026-09-05** | `gh run list --workflow=nightly-verification.yml --limit 5 --json createdAt,event,conclusion` | **夜间回归停了 55 天**；白天只有 `post-merge-verify`/`post-deploy-eval` 兜底，长周期回归（smoke p1 + fixture e2e）实际无人跑 | 要么恢复一条能绿的夜间腿（先修 #2957 的根因），要么显式登记为「已接受缺口 + 重启条件」 | CI / 测试 |
| **P1-04** | P1 | CI 读数 / 假红 | **C** `scripts/stale_report_reaper.py::EXIT_OK, EXIT_USAGE, EXIT_ACTED, EXIT_UNKNOWN = 0, 1, 2, 3`（**成功关单 = 2**）+ `.github/workflows/stale-report-reaper.yml` 步骤末 `exit ${RC}`；**R** run `41148096721` 日志：`MIGAO-REAPER-SUMMARY seen=3 acted=1 rc=2 why=可关 1 条，实关 1 条` → `##[error]Process completed with exit code 2` | `gh run view 41148096721 --log-failed \| tail -20` | **它成功干活的每一轮，腿都是红的**（每次 push 到 main 一次假红）⇒ 告警疲劳：真失败与"干完了"同形（正是 `migao-acceptance` 的「假红」形态） | workflow 侧把 `EXIT_ACTED` 映射为 success（`rc=2` 只进读数），或给该腿一个"acted 也是绿"的显式分支 | CI |
| **P1-05** | P1 | 回滚 / 运维 | **C** `docs/deployment/rollback.md::1. 判定需要回滚的信号` 的第一条 = `curl api.migaozn.com/actuator/health`；**L** 该 URL 线上 `404`（nginx `location ~ ^/(actuator|v3/api-docs|swagger-ui)` 整段屏蔽，`raw/01`） | `curl -s -o /dev/null -w "%{http_code}\n" https://api.migaozn.com/actuator/health` | **回滚判据不可用**：运维按 runbook 执行会得到"非 200 ⇒ 判定需要回滚"的**错误信号**（永远命中） | runbook 改成线上真的 200 的面（`/api/version` 或 `ai-api/health`），并加一条"判据地址必须 200"的自检 | 运维文档 |
| **P1-06** | P1 | admin-web 读面 | **C** `frontend/admin-web/src/components/common/ListLoadError.tsx`（常驻读失败出口）被 **28 个文件**引用；`find frontend/admin-web/src/app -name page.tsx \| wc -l` = **58** ⇒ **37 页没有**；点名高流量页：`(dashboard)/orders/[id]/page.tsx`、`(dashboard)/products/page.tsx`、`(dashboard)/dashboard/page.tsx`、`(dashboard)/production/page.tsx` | `for f in $(find frontend/admin-web/src/app -name page.tsx); do grep -q ListLoadError "$f" \|\| echo "$f"; done \| wc -l` | 读面故障被画成**空态**（列表空、数字 0），商家会当成"没数据"⇒ 按错数据做决定（`DQ-1` 明令不得冒充） | 把 `ListLoadError` 提到 layout 层或做成 hook 的默认行为，别逐页补 | admin-web |
| **P1-07** | P1 | 数据 / 运维 | **C** `docs/deployment/rollback.md::误删/坏数据` 的恢复路径 = **云控制台人工**（"RDS 自动备份恢复 … 恢复前确认备份策略 ≥14 天"）；仓库内 `grep -rn "pg_dump\|backup" deploy/ .github/workflows/` ⇒ 只有 H5 静态根备份，**无数据库备份代码** | `grep -rn "pg_dump" deploy/ .github/workflows/ \| head` | 误删/坏数据**不可自助恢复**；备份策略是否 ≥14 天**无读数**（不可判定 ⇒ 不能算通过） | 取一次云侧备份窗口读数并落进 runbook；补一次恢复演练记录（不新增无人值守删除，符合铁律 10） | 运维 |
| **P1-08** | P1 | 安全头 / 网关 | **C** `backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java::securityFilterChain`（`.headers(headers -> headers.hsts(... maxAge 31536000 ...))`）+ `backend/admin-api/src/main/resources/application.yml` **无 `server.forward-headers-strategy`**；**L** `curl -sI https://api.migaozn.com/api/version \| grep -i strict-transport` ⇒ **无输出**；merchant 页面同样无 HSTS（`raw/04`） | 两行：`curl -sI https://api.migaozn.com/api/version \| grep -ic strict-transport` = 0 | 代码声明了 HSTS，线上**一个域都没有**（机制级推断：nginx 终止 TLS 后 Spring 视请求为 http，HSTS 只在 secure 请求上发）⇒ 首次明文请求仍有劫持窗口 | 配 `forward-headers-strategy: framework` 后复探 HSTS；把"线上必须带 HSTS"做成一条判据（避免"声明存在≠可达"再犯） | admin-api / 网关 |
| **P1-09** | P1 | 安全头 / 静态度 | **L** `curl -sI https://app.migaozn.com/w/` 与 `/b/`：**无** `X-Content-Type-Options`、无 HSTS、无 CSP（`raw/04`）；**C** `frontend/bmini-app/src/utils/workerSession.ts::localStorage.setItem(H5_WORKER_SESSION_KEY, …)`（工人会话 id 落 localStorage） | `curl -sI https://app.migaozn.com/w/ \| grep -iE "strict-transport\|x-content-type\|content-security"`（空） | 静态域无 nosniff：一旦出现"内容嗅探"型注入，浏览器会按 HTML 解释；工人 session 在 localStorage ⇒ 任一 XSS 即可**冒用工人身份报工/入库**（涉钱） | 静态域加 `nosniff` + HSTS + 最小 CSP；工人会话优先 HttpOnly cookie | 网关 / worker-h5 / bmini |
| **P1-10** | P1 | 短链 / 泄漏面 | **C** `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShortLinkController.java::resolve`（`302 Location: /b/?t=<token>&tenant_id=…`）+ `InboundLabelShortLinkController`/`ProcessingOrderShortLinkController` 同族；**C** `frontend/worker-h5/src/api.mjs::login`（会话 id 走 header） | `grep -rn "b/?t=\|reportPageLocation" backend/admin-api/src/main/java \| head` | 报工/入库/加工单三种短码把 **token 放 URL query** ⇒ 进 nginx access log、浏览器历史、Referer；纸上二维码被拍照即可复用（改撤才失效） | 登记为**有意取舍**并在日志侧脱敏（access log 过滤 `t=`）；或换成一次性票据（与 `/api/auth/qr/exchange` 同族） | 后端 / 工人端 |
| **P1-11** | P1 | 数据增长 | **C** `deploy/ops/db-retention.sql` 文件头逐字：**"人工执行，不是定时任务"**、`audit_logs` 365 天 / `notifications` 180 天；仓库内**无任何值守面**（无告警、无读数、无到期提醒） | `head -12 deploy/ops/db-retention.sql` | 两张只增表**无界增长** ⇒ 索引体积/备份窗口/查询变慢；且"没有清理"这件事**不会有人知道**（无读数） | 加一条"表体积/最老行年龄"读数进值班面（只读，不新增无人值守删除） | 运维 / DB |
| **P1-12** | P1 | 部署 / 健康 | **C** `deploy/swas/docker-compose.yml::services`：只有 `ai-agent` 有 `healthcheck`；`admin-api`/`admin-web`/`nginx` **无健康检查** | `grep -n "healthcheck" deploy/swas/docker-compose.yml`（1 处） | 进程僵死（线程池耗尽/死锁）时容器仍 `Up`，`restart: unless-stopped` 不重启；nginx 也不会把它摘掉 ⇒ **假活** | 三服务补 healthcheck（admin-api 用内部 `curl 127.0.0.1:8080/actuator/health`），与 `deploy.sh::wait_healthy` 同源 | 部署 |
| **P2-01** | P2 | 信息面 | **L** `GET https://api.migaozn.com/api/version/migrations` ⇒ `{"migrationsFailedReal":"0","migrationsFailedBenign":"0","migrationsAppliedByLedger":"198"}`；**C** `SecurityConfig::permitAll` 同时放行 `/api/version` 与 `/api/version/migrations` | README §7 | 公开暴露迁移账本计数（版本指纹）——无业务数据，属低危信息面 | 只留 `/api/version`；`/migrations` 收到认证后 | 后端 |
| **P2-02** | P2 | admin-web 体验 | **C** `find frontend -name not-found.tsx` ⇒ 0 个；admin-web 无 `not-found.tsx` | `find frontend -name "not-found.tsx"` | 访问不存在路由 → Next 默认 404（英文 + 无返回入口） | 加一个中文 `not-found.tsx`（含返回工作台） | admin-web |
| **P2-03** | P2 | 观察项（不阻塞） | **L** `curl -sI https://merchant.migaozn.com/login` ⇒ `x-powered-by: Next.js`、`cache-control: s-maxage=31536000`（无 `max-age`，无 CDN 时无害）；**C** `frontend/admin-web/next.config.*` 无 `headers()` | README §7 | 一旦前面挂 CDN/反代缓存，登录页 HTML 会被**按年缓存** ⇒ 指向已删除 chunk ⇒ 白屏（当前无 CDN，故仅登记） | 若接 CDN：给 HTML 加短 `s-maxage` + `must-revalidate` | admin-web / 网关 |

---

## P0 逐条：可直接开单的标题与验收标准

### P0-01 · TLS 证书 27 天后到期，仓内无续期机制

**建议标题**：`[P0·上线] TLS 证书 2026-11-27 到期，仓库内无续期机制（compose 无 certbot / 无续期 workflow），已过 30 天续期点`

**现象（durable）**
- **L**：`echo | openssl s_client -servername merchant.migaozn.com -connect merchant.migaozn.com:443 2>/dev/null | openssl x509 -noout -dates -issuer`
  ⇒ `notBefore=Aug 29 10:29:19 2026 GMT` / `notAfter=Nov 27 10:29:18 2026 GMT` / `issuer=… CN=YR2 (Let's Encrypt)`
  —— `merchant/api/ai-api/app` **四域同一张证书**（`raw/05-tls-and-landing.txt`）。
- **C**：`deploy/swas/docker-compose.yml::services` 只有四个服务；`nginx` 只挂载 `./certbot-www:/var/www/certbot`（**ACME challenge 目录，不是续期器**）。
- **C**：`deploy/swas/nginx.conf::server` 的 `ssl_certificate /etc/letsencrypt/live/migao/fullchain.pem`。
- **C**：`ls .github/workflows | grep -iE "cert|renew"` ⇒ 空；`docs/deployment/*` 无续期步骤。
- **推断（明确标注强度）**：Let's Encrypt 的常规续期点是「剩 30 天」≈ **2026-10-28**，今天 **10-31** 仍未续
  ⇒ 续期链路**在本次审计时已错过一次**（服务器侧 crontab 不可见，属"不可判定"，但"已错过"是读数不是猜测）。

**验收标准**
1. 仓内可证续期：`docker-compose.yml` 有 `certbot` 服务（或 `.github/workflows/*renew*` 有排程），
   且 `acme.sh/certbot` 的 **renew hook 会 reload nginx**；
2. **读数**：复跑上面的 `openssl … -dates`，`notAfter` ≥ 今天 + 60 天；
3. **失败可见**：续期失败会进 P0-04 的告警通道（不许只写在容器日志里）；
4. 反向验证（会红）：把证书日期判据写进 CI/值守腿，喂一条 `notAfter` < 今天+30 的夹具 ⇒ 必须红。

### P0-02 · C 端 H5 线上产物落后主仓 5.0 天（工具本身已判红，8 轮无人处置）

**建议标题**：`[P0·C端] 元元 H5 线上产物落后主仓 5.0 天（新鲜度判据连续 8 次红），发布腿默认只报告`

**现象（durable）**
- **R**：`gh run list --workflow=c-end-h5-publish.yml --limit 8 --json createdAt,conclusion,event,headSha`
  ⇒ 8 条全 `failure`；最新一条 `2026-10-31T00:05:51Z workflow_dispatch 32d4066e7`（**当前 main HEAD**）。
- **R**：`gh run view 41148260773 --log-failed | grep 线上产物`
  ⇒ `##[error] 线上产物**陈旧**：2026-10-24T15:40Z 早于 frontend/mini-app 最近改动 2026-10-29T23:25Z（落后 5.0 天）`。
- **L**：`curl -sI https://app.migaozn.com/js/app.js | grep -i last-modified` ⇒ `Sat, 24 Oct 2026 15:40:08 GMT`。
- **C**：`frontend/mini-app/src/utils/craft-display.ts` 最近一次改动 = `e0500beff`（`git log -1 --format=%h -- frontend/mini-app/src/utils/craft-display.ts`），
  即线上产物**不含**该口径修复（同批还改了 `OptionFamilyNames` / `order_create.py` / `routing.py`）。
- 设计口径（不是缺陷）：`.github/workflows/c-end-h5-publish.yml::Resolve mode` —— `notify` 默认、`publish` 需 `workflow_dispatch + publish=true`（用户 2026-09-27 裁定 B：首次发布由人手动触发）。**红是判据在正常工作**；缺陷在"红了 8 次没人处置"。

**验收标准**
1. 人工发布一次：`gh workflow run c-end-h5-publish.yml --ref main -f publish=true`，
   run 为 `success` 且 `Assert served identity` 步通过；
2. **读数**：`curl -sI https://app.migaozn.com/js/app.js | grep last-modified` 的日期 ≥ `e0500beff` 的提交日期（2026-10-29T15:25Z）；
3. 该腿的红**有承接面**（进 P0-04 的告警通道或一条 `needs-human` 台账），不许"红了堆在 Actions 页面"；
4. 反向验证：把 `e0500beff` 的 `craft-display` 判据喂旧产物 ⇒ 新鲜度判据必须红（现有 `scripts/h5_freshness_guard.py` 已有 rc=2 语义，复算即可）。

### P0-03 · admin-web 无全局错误边界（58 页仅 1 页）+ 四端零错误上报

**建议标题**：`[P0·白屏] admin-web 无 global-error.tsx / 57 页无页面级 error.tsx，且四端零前端错误上报`

**现象（durable）**
- **C**：`find frontend -name error.tsx -o -name global-error.tsx` ⇒ 只有 `frontend/admin-web/src/app/(dashboard)/customers/error.tsx`；
  `frontend/admin-web/src/app/layout.tsx` 是最外层 layout，**没有** `global-error.tsx`；
- **C**：`grep -rn "Sentry\|window.onerror\|unhandledrejection\|reportError" frontend/admin-web/src frontend/bmini-app/src frontend/worker-h5/src frontend/mini-app/src`
  ⇒ 仅 6 处命中，全部是 `frontend/worker-h5/src/machine.mjs` 里的**局部状态字段名** `reportError`（报工失败态），与错误上报无关 ⇒ **上报面 0**；
- **C**：现有唯一错误页的形态（`customers/error.tsx`）证明范式存在，只是没铺开。

**为什么定 P0**：`P0` 判据里"白屏"这一条的形态是"用户卡在一个什么都没有的页面上、没有出口、你也不知道"。
本仓 58 个页面里 57 个正是这个形态；且**零上报**意味着发生频率**不可知**（不可判定 ⇒ 不能算通过）。

**验收标准**
1. 根级 `app/global-error.tsx` + 至少 `(dashboard)`、`(corporate)` 两个 `error.tsx`；错误页含**重试按钮**与**错误编号**；
2. 上报面接到一个真实可查的地方（Sentry/自建），且**上报失败不影响页面**（try/catch 包裹）；
3. **红证**：注入一个渲染期异常（测试里 throw），断言 ① 用户看到错误页而非空白 ② 上报被调用一次
   （`expect(report).toHaveBeenCalledWith(expect.objectContaining({digest}))`）；
4. 线上复探：部署后用一条受控异常页 URL 触发一次，值班面能看到 1 条事件（含 digest）。

### P0-04 · 上线可观测性缺位（无 5xx 告警 / 无错误追踪 / 无合成探针）

**建议标题**：`[P0·可观测] 上线可观测性缺位：无 5xx 告警、无错误追踪、无合成探针（production-deployment.md §5 必须项零落地）`

**现象（durable）**
- **C**：`docs/deployment/production-deployment.md::5. 生产安全基线` 明确把「SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）触达值班」列为必须项；
- **C**：仓库内无告警实现（`.github/workflows/` 无 alert/PagerDuty/SLS 腿；`deploy/` 无 metrics 配置）；
- **L**：线上唯一可信探针是 `/api/version`（200）与 `ai-api/health`（200）；`/actuator/health` 公网 **404**（`raw/01`）⇒ **没有外部合成探针**；
- **关联读数**：P0-02（红 8 次无人处置）、P1-03（夜间腿停 55 天）、P1-04（成功即红）三条都是"没有承接面"的实证。

**验收标准**
1. 外部合成探针（30s/1min 级）覆盖：`api.migaozn.com/api/version`、`merchant.migaozn.com/login`、`app.migaozn.com/b/`、`app.migaozn.com/w/`；
2. 5xx 计数阈值 + 证书到期（P0-01）+ 发布失败（P0-02/P1-04）三类事件**能真的响**（落到一个有人看的通道）；
3. **红证**：人为制造一次 5xx（受控端点或临时改探针目标）⇒ 通道在约定时限内收到 1 条；
4. 报告中给一条"告警演练"读数（时间 + 通道 + 内容），否则按"未验证"处理。

---

## 已读但**不**成立为缺陷的候选（避免下一轮重复劳动）

| 候选 | 为什么不算 |
|---|---|
| `POST /api/auth/admin/login` 仍在放行名单 | `AuthService::adminLogin` 直接抛 `AUTH_FAILED`（禁用入口不可绕过，#375） |
| `account/employee/login` 需要 body tenantId 才能过校验 | 前端只走 `/api/auth/employee/login`（identifier 内含企业编码），管理员走短信；`admin/login` 已禁用 |
| 上传可传 `.html`/`.svg` ⇒ 存储型 XSS | `UploadGuard` 只放 8 种扩展名 + **魔数族匹配**，`.html` 直接 422 |
| `/api/files/static/**` permitAll ⇒ 任意文件读 | `WebConfig::addResourceHandlers` 只映射 `file:uploads/`，文件名是 UUID；路径穿越由 `UploadGuard.resolveDirectory` + `safeResolve` 挡 |
| 退款可双花 | `OrderService::refundOrder` 是 DB 层 `COALESCE` 累加 + `WHERE` 封顶（注释与实现同处） |
| 盘点可绕过审批调库存 | `StocktakeService::complete` 差异必过 `approvalService.consume` + CAS 状态更新 |
| 工人 PIN 可爆破 | `WorkerSessionService` 有 `LoginFailureGuard` 锁定窗口（#5531） |
| 同手机号多租户登录会串租户 | `AuthService::loginBySms` 歧义 fail-closed（#6159） |
| `/w/src/*.mjs` MIME 错导致白屏 | 线上 `content-type: application/javascript`（`raw/06`），历史病灶未复现 |
| `/b/report/` 会被 C 端 SPA 兜底 200 串端 | 线上 body 769B + `<title>工人报工</title>`（`raw/06`） |
| admin-web 落后 1 个 commit | `32d4066e7` 未触 `frontend/admin-web`（`git log a9f3f9c68..32d4066e7 -- frontend/admin-web` = 0 行） |

---

## 复算命令（逐条可复制）

```bash
# P0-01
echo | openssl s_client -servername merchant.migaozn.com -connect merchant.migaozn.com:443 2>/dev/null \
  | openssl x509 -noout -dates -issuer
grep -rn "certbot" deploy/swas/docker-compose.yml deploy/swas/nginx.conf
ls .github/workflows | grep -iE "cert|renew" || echo "（无续期 workflow）"

# P0-02
gh run list --workflow=c-end-h5-publish.yml --limit 8 --json createdAt,conclusion,event,headSha
gh run view 41148260773 --log-failed | grep 线上产物
curl -sI https://app.migaozn.com/js/app.js | grep -i last-modified
git log -1 --format="%h %ci %s" -- frontend/mini-app/src/utils/craft-display.ts

# P0-03
find frontend -name "error.tsx" -o -name "global-error.tsx"
grep -rn "Sentry\|window.onerror\|unhandledrejection" frontend/*/src | wc -l
find frontend/admin-web/src/app -name page.tsx | wc -l

# P0-04 / P1-05
curl -s -o /dev/null -w "version=%{http_code}\n" https://api.migaozn.com/api/version
curl -s -o /dev/null -w "actuator=%{http_code}\n" https://api.migaozn.com/actuator/health
curl -s -o /dev/null -w "aihealth=%{http_code}\n" https://ai-api.migaozn.com/health

# P1-01 / P1-02 / P1-12
for p in /api/version /version /build-info; do echo -n "$p "; curl -s -o /dev/null -w "%{http_code}\n" https://ai-api.migaozn.com$p; done
grep -n "logging\|healthcheck" deploy/swas/docker-compose.yml

# P1-03 / P1-04
gh run list --workflow=nightly-verification.yml --limit 5 --json createdAt,event,conclusion
grep -n "EXIT_OK, EXIT_USAGE, EXIT_ACTED" scripts/stale_report_reaper.py
gh run view 41148096721 --log-failed | tail -5

# P1-06
for f in $(find frontend/admin-web/src/app -name page.tsx); do grep -q "ListLoadError\|LoadError" "$f" || echo "$f"; done | wc -l

# P1-08 / P1-09
curl -sI https://api.migaozn.com/api/version | grep -i strict-transport || echo "（无 HSTS）"
curl -sI https://app.migaozn.com/w/ | grep -iE "strict-transport|x-content-type|content-security" || echo "（静态域无安全头）"

# P1-10 / P1-11
grep -rn "b/?t=" backend/admin-api/src/main/java | head
head -12 deploy/ops/db-retention.sql
```
