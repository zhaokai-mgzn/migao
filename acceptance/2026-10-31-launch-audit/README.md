# 上线前只读全量审计（issue #8197）— 2026-10-31

> **审计对象**：`origin/main` @ `32d4066e7`（2026-10-31 08:06 +08 的 main HEAD）+ 线上四个域。
> **线上被测版本**：`https://api.migaozn.com/api/version` 读到
> `{"app":"admin-api","sha":"32d4066e762b84e1c74d9c0ed7833d5ed1c1d2bc","tag":"sha-32d4066","builtAt":"2026-10-31T00:06:11Z"}`
> ⇒ **被测对象就是本报告的基线 SHA**（不是"大概是 main"）。
> **口径**：只读。没有改产品代码、没有跑全量测试、没有跑真实 LLM 评测、没有写任何生产数据；
> 线上只做 **GET / HEAD / OPTIONS 预检** 与一次 **无可写副作用的参数校验探测**（见 §6 边界）。
> **方法**：`migao-acceptance`（每条 findng 必带 durable 证据锚 / 线上复探读数 / 复算命令）；
> 假绿清单一律按 `docs/testing/smoke-data-quality.md`（空态/加载态不算通过）。
> **原始读数**：`raw/` 六个文件，均为当次**实跑输出**（`01`~`07`）。

---

## 0. 一页结论

**结论：** 代码层（登录/权限/租户隔离/涉钱写入/上传/幂等）**达到可交付水平**，
3 处高危面（越权、改价、上传）都有**服务端**判据而不是靠"按钮藏起来"；
但**上线所需的运行面（证书续期、发布新鲜度、白屏出口、可观测性）有 4 条 P0 缺口**，
其中 **P0-01（TLS 证书 27 天后到期且仓内无续期机制）** 是唯一一条**到点必然全站中断**的风险。

| 严重度 | 数量 | 一句话 |
|---|---|---|
| **P0** | **4** | 证书续期（到点全站 HTTPS 断）· C 端产物落后 5.0 天（口径分叉）· 无全局错误边界+零错误上报（白屏无出口）· 上线可观测性缺位（静默失败） |
| **P1** | **12** | 版本探针/日志轮转/夜间回归停摆/假红腿/回滚判据不可用/37 页无读失败出口/备份未证/HSTS 未达/静态域无安全头/短链 token/审计表只增/无容器健康检查 |
| **P2** | **3** | 迁移账本公开读数 · 短链 token 设计取舍 · 无 `not-found.tsx` |

**可上线判据（由本报告定义）**：4 条 P0 全部关闭 + P1 中 `P1-05`（回滚判据）与 `P1-07`（备份）
取得**可复核读数**（不必修完，但必须能读到值）。**当前不满足** ⇒ **不建议按"直接开放给试用客户"上线**，
建议按 §4 的"最小闭环"（P0-01 一条即可解除不可逆风险）后再开门。

**有哪些是"已经验过、确实没问题"的**（不是"没看"，见 §2）：
线上静态产物 404 计数 **0/21**、模块 MIME 全对（历史白屏病灶已不复现）、
未认证面 **401**、swagger/actuator/api-docs **404**、`/api/chat/` **401**、
工人登录有锁定窗口、短信有 60s+10 次/日、上传有扩展名+魔数双白名单、退款有 DB 层封顶并发保护、
盘点完成是 CAS + 审批、租户隔离在 MyBatis 拦截器 + `@TenantOwnedResource` 两层。

---

## 1. 证据链的三种来源（每条 finding 只允许挂在这三种上）

| 标记 | 含义 | 复核方式 |
|---|---|---|
| **L**（live） | 线上复探读数 | 报告里给**逐字可复制命令**；结果落在 `raw/0*.txt` |
| **C**（code） | 仓库内 durable 证据 | `<仓库相对路径>::<符号/文本锚>`（**不写裸行号**，行号会漂） |
| **R**（run） | CI/Actions 读数 | `gh run view <id> --log-failed` / `gh run list --json` |

> 「声明存在 ≠ 可达」：本报告只用 **C+R** 支撑"已实现"，用 **L** 支撑"线上真的这样"。
> 任何只有 C 没有 L 的条目，在 `findings.md` 的"证据强度"列标 `C`（不当线上事实）。

---

## 2. 已验证通过的面（复算命令，全部零写）

### 2.1 版本 / 新鲜度（四端）

| 对象 | 读数 | 判据 |
|---|---|---|
| admin-api | `sha=32d4066e7…` = main HEAD | `curl -s https://api.migaozn.com/api/version` |
| admin-web | `sha=a9f3f9c68…`（比 main 少 1 个 commit，`32d4066e7` 未触 `frontend/admin-web` ⇒ **不算落后**） | `curl -s https://merchant.migaozn.com/version.json` + `git log --oneline a9f3f9c68..32d4066e7 -- frontend/admin-web`（=0 行） |
| worker-h5 | 9 个发布文件 **逐字节相同**（sha256） | `for f in src/app.mjs …; do curl -s https://app.migaozn.com/w/$f \| shasum -a 256; shasum -a 256 frontend/worker-h5/$f; done` |
| bmini H5 | `/b/` last-modified `2026-10-30T22:41Z` ≥ 最近 bmini 提交 `2026-10-29T15:25Z` ⇒ 新鲜 | `curl -sI https://app.migaozn.com/b/` + `git log -1 --format=%ci -- frontend/bmini-app` |
| C 端 H5 | **陈旧 5.0 天**（见 P0-02） | `raw/07-cend-stale.txt` |

### 2.2 静态产物完整性（白屏最直接的一类成因）

`raw/03-asset-chain.out`：四个入口页 HTML 里的 `js/css/mjs/woff/png/svg/ico` 全部 GET 一遍
⇒ **admin-web 13 个资产 non200=0；C 端 3/0；bmini 3/0；worker-h5 2/0**。
`raw/06-mime-probe.txt`：`/w/src/*.mjs` 的 `Content-Type` = `application/javascript`
（nginx 注释里记录的「`mjs` 无 MIME ⇒ 模块脚本拒绝执行 ⇒ 整页白屏」历史病灶**线上不复现**）。
`/b/report/`（印刷二维码落地页）body 769B、`<title>工人报工</title>`、`location /b/report/ { rewrite … /w/ }` ⇒ **没有串到 C 端首页**。

### 2.3 鉴权 / 暴露面（线上）

| 探测 | 读数 | 结论 |
|---|---|---|
| `GET /api/admin/orders`（无凭据） | `401 {"code":"UNAUTHORIZED"}` | 未认证面 fail-closed |
| `GET /swagger-ui/index.html`、`/v3/api-docs` | `404`（nginx 整段屏蔽） | 文档面不出网 |
| `GET /actuator/health`（公网） | `404` | 健康面不出网（**副作用见 P1-05**） |
| `GET ai-api.migaozn.com/docs`、`/redoc`、`/openapi.json` | `404` | ai-agent 文档面不出网 |
| `POST https://api.migaozn.com/api/chat/stream`（无凭据） | `401` | AI 写面要认证 |
| `POST /api/worker/login {}` | `422` + 逐字段中文 | 错误形状是校验错误、不是 500 |
| `POST /api/auth/admin/login`（已禁用入口） | 线上 **422**（`@Valid` 先拦：缺 `tenantId`）；代码路径 `AuthService::adminLogin` 无条件抛 `AUTH_FAILED` | 禁用入口不可被绕过（**422 是校验层的形状，不是它可用**） |

### 2.4 代码层（durable 证据）

- **租户隔离两层**：`backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java::tenantLineInnerInterceptor`
  （SQL 层自动注入 `tenant_id`，白名单只有 `tenants/tenant_applications/platform_admins/notification_templates/notification_rules`）
  + `backend/admin-api/src/main/java/com/migao/admin/security/TenantOwnershipInterceptor.java::preHandle`（**参数解析之前**判归属）。
- **涉钱写面**：改价只允许 `pending`（`OrderController::updateOrderContent` → `OrderStatusTransitions.assertContentEditable`）；
  退款 `OrderService::refundOrder` 是 **DB 层 `COALESCE` 累加 + WHERE 上限**（并发双花防护，注释与实现同处）；
  计件金额过 `MoneyScale.requireTwoDecimalsOrNull`。
- **报工幂等**：`frontend/worker-h5/src/app.mjs::PENDING_REQUEST_KEY`（跨刷新复用同一 `X-Client-Request-Id`）+ 机台页同键。
- **上传**：`backend/admin-api/src/main/java/com/migao/admin/service/UploadGuard.java` 扩展名白名单 8 种 + **魔数族匹配** + 服务端计字节 ⇒ 传不了 `html/svg`（无存储型 XSS 面）。
- **登录防爆破**：`WorkerSessionService`（`LoginFailureGuard` 锁定窗口）、`SmsService`（60s + 每日上限 + 失败计数）。
- **水平越权 / 多租户歧义**：`AuthService::loginBySms` 同手机号多租户 **fail-closed**，不 `findFirst` 落错租户。

---

## 3. P0 清单（详情与验收标准见 `findings.md`）

| ID | 标题 | 上线后果 |
|---|---|---|
| **P0-01** | TLS 证书 **2026-11-27 到期**，仓库内**零续期机制**（compose 无 certbot 服务 / 无续期 workflow / 无 runbook 步骤），且已过 Let's Encrypt 30 天续期点仍未续 | **到点全站断**（商家端+工人端+C 端+API 同时不可用） |
| **P0-02** | C 端元元 H5 线上产物**落后主仓 5.0 天**；新鲜度判据连续 **8 次红**（含 10-31 00:05 手动 dispatch），发布腿默认 `notify`（不写盘） | 试用客户看到的是**旧口径**（缺 `e0500beff` 的 `craft-display` 改动）⇒ 选项/报价与后端口径分叉 |
| **P0-03** | admin-web **58 页只有 1 页**有 `error.tsx`，**无 `global-error.tsx`**；四端**零前端错误上报**（无 Sentry/`window.onerror`/`unhandledrejection`） | 任一条脏数据触发渲染异常 = **整页白屏、无重试出口**，且线上发生也**无人知道** |
| **P0-04** | 上线可观测性缺位：`docs/deployment/production-deployment.md` §5 把「SLS 采集 + 告警（5xx/健康检查）」列为**必须项**，仓库内**零落地**（无告警配置、无错误追踪、无合成探针、无值班触达面） | 出故障只能等客户投诉 —— **静默失败**（本项目自认最大失败模式） |

---

## 4. 达到"可以开门"的最小闭环

**必做（解除不可逆风险）**
1. **P0-01**：把续期机制**做成仓内可证**（certbot 服务 或 续期 workflow），并在报告里给一次
   `openssl ... -noout -dates` 的 **notAfter > 今天+60 天** 读数。
2. **P0-03**：加根级 `global-error.tsx` + `error.tsx`（每段路由组一个），并接一个错误上报面；
   判据 = 注入一个渲染异常后**用户看到重试按钮**、且上报面**收到一条事件**。

**建议（开门同一批）**
3. **P0-02**：`gh workflow run c-end-h5-publish.yml --ref main -f publish=true` 跑一次（**人工**，按用户 2026-09-27 裁定 B），
   然后给 `app.migaozn.com/js/app.js` 的新 `last-modified` 读数；C 端暂缓期间该条不阻塞 B 端。
4. **P0-04 / P1-05 / P1-07**：三条都是"取值动作"，不必开发：告警通道（哪怕只到群）、
   回滚健康检查地址改成线上真的 200 的那条（`/api/version`）、云侧 RDS 备份窗口读数（≥14 天）。

---

## 5. 未验证 / 不可判定（写明原因与重启条件）

| 项 | 状态 | 为什么 | 重启条件 |
|---|---|---|---|
| 登录后功能面（下单/发货/报工/计件的真实写链路） | **未验证** | 只读审计，无任何可用凭据；不得登录后写 | 拿到只读账号或独立栈（CI docker 考场）后按 `migao-dev-flow` §15 跑真实旅程 |
| 打印（标签/三联纸/A4）真机输出 | **未覆盖** | 需真打印机；仓库侧只能读到打印实现 | 现场真机一次，按 `docs/testing/production-readonly-verification-pack.md` R4 四项 |
| 微信后台（小程序审核/订阅消息/授权域名） | **未覆盖** | 需微信管理后台权限 | 商家/微信后台侧核对一次 |
| Android APK / Windows EXE 终端 | **未覆盖** | 本仓无构建产物与分发面（壳工程不在本仓） | 见 #5061 族；实机安装一次 |
| C 端 5 天分叉的**金额影响面** | **不可判定** | 需真库比对运行中订单的 `craft_display` 落库值 | 只读 SQL（`production-readonly-verification-pack.md` 同口径）+ 独立栈重放 |
| RDS 备份窗口 / PITR 是否 ≥14 天 | **不可判定** | 云控制台侧，仓库零证据 | 阿里云控制台读数一次（P1-07 升级判据） |
| ai-agent 线上 SHA | **不可判定** | 无版本探针（P1-01） | 加探针后复探 |
| 服务器 crontab 是否有证书续期 | **不可判定** | 只读审计看不到服务器计划任务 | 需 SSH 一次 `crontab -l`（本报告不把它当"没有"，见 P0-01 的写法） |

---

## 6. 边界与自证

- **只读自证**：线上命令全部是 `curl -sS`（GET/HEAD/OPTIONS）+ 一次 `POST /api/worker/login` 空 body、
  一次 `POST /api/auth/admin/login` 假凭据 —— 二者都是**校验层拒绝**（422/401），不建会话、不落业务数据。
  证据：`raw/04-live-headers-auth.txt` 的响应体（`VALIDATION_ERROR` / 已禁用文案）。
- **不碰主工作区**：本报告全部产出在 worktree `migao-wt/8197-launch-audit`（分支 `docs/8197-launch-audit`）。
- **不变量**：`git status --short` 只应有本目录文件；产品代码零改动。

## 7. 复算命令（一次跑完）

```bash
cd <repo>                                  # 分支 docs/8197-launch-audit
bash acceptance/2026-10-31-launch-audit/raw/03-asset-chain.sh        # 四端资产链
curl -s  https://api.migaozn.com/api/version                          # admin-api 线上 SHA
curl -s  https://merchant.migaozn.com/version.json                    # admin-web 线上 SHA
curl -sI https://app.migaozn.com/js/app.js | grep -i last-modified    # C 端新鲜度（P0-02）
echo | openssl s_client -servername merchant.migaozn.com -connect merchant.migaozn.com:443 2>/dev/null \
  | openssl x509 -noout -dates                                        # 证书到期（P0-01）
gh run list --workflow=c-end-h5-publish.yml --limit 8 --json createdAt,conclusion   # P0-02 红腿
gh run view 41148260773 --log-failed | grep 线上产物                              # P0-02 判据原文
find frontend -name error.tsx -o -name global-error.tsx               # P0-03（结果只有 1 个文件）
grep -rn "Sentry\|window.onerror\|unhandledrejection" frontend/admin-web/src \
  frontend/bmini-app/src frontend/worker-h5/src frontend/mini-app/src  # P0-03（0 命中）
grep -n "certbot" deploy/swas/docker-compose.yml .github/workflows/*.yml  # P0-01（无续期服务）
```

> 读数与命令**同时**给出才可复核；只给结论不给命令的条目，本报告一律不写。
