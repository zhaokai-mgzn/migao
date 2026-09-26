# 验收产物 — 登录重构（issue #5485）

> 剧本：`SCRIPT.md`　｜　报告：`REPORT.md`（结论 / 验收矩阵 / 问题清单含证据 / 复核抽验 / 沉淀记录）
> 协议：`docs/testing/acceptance-protocol.md` + DSH 技能 `migao-acceptance`

## 被测对象与 SHA（活环境结论必须绑定 SHA，否则不可复核）

| 面 | 对象 |
|---|---|
| 后端 | `origin/main`（PR #5492 合并后，A2 复算于纯检出）；**真栈**运行的本机 admin-api 含 P0 修复 |
| 数据库 | 云 dev RDS（真实 PostgreSQL；`V128` 由 `MigrationRunner` 真实应用，二次启动确认幂等） |
| 前端 | admin-web（PR #5517）/ bmini-app（PR #5519，已合并） |

## 产物结构

| 路径 | 内容 |
|---|---|
| `REPORT.md` | 验收报告（分档结论 / 验收矩阵 / 9+ 条缺陷含根因与红证 / 未取证与残余项） |
| `SCRIPT.md` | 验收剧本（验收点 × 期望的**用户可见结果** × 红证） |
| `accept-login-api.py` | API 级采集器（零第三方依赖；21 条断言，每条带红证注释） |
| `ua/recon.cjs` | 登录页 DOM 侦察（**选择器取自实测 DOM，不是猜的**） |
| `ua/journey2.cjs` | UA 档真实浏览器旅程 v2（18 条断言；证据不截断 + 网络轨迹 + 每旅程独立 context + 2 条负向旅程） |
| `ua/out2/transcript.json` | UA 逐条断言 + **27 条认证请求轨迹** |
| `ua/out2/*.png` | 7 张真实截图 |
| `ua/out2/db-ddl.txt` | `\d users` 原文 + `pg_indexes` 的部分唯一索引定义原文 |
| `ua/out2/db-flip-and-crosstenant.txt` | **配对**行为证据（`must_change_password` true→false）+ 跨租户探针（`X-Tenant-Id` 伪造无效） |
| `ua/out2/db-flip.txt` | ⚠️ v1 采集、**标签有误**（见文件头说明；权威在上一行那个文件） |

## 入库范围（**有意收窄**，如实登记）

本目录**只入仓"人读证据"**：报告 / 剧本 / 原始文本证据（DDL、配对翻转、跨租户探针、额外证伪项）/ 截图。
**未入仓**：两个采集器脚本（`accept-login-api.py` / `ua/journey2.cjs` / `ua/recon.cjs`）与原始 `transcript.json`。

**原因（实测）**：这些文件携带**请求/响应原文**，因而含**凭据形态**内容（`password` 字段、`accessToken` 的 JWT、夹具口令）。
即使把它们全部替换成脱敏占位符，**`Secret Scan (gitleaks)` 仍判红** —— 该扫描器**无法区分"脱敏占位符"与"真值"**（实测：重写历史 + 全量脱敏后仍红；注解只给 "Leaks detected"，明细写在 job summary 页，API 取不到）。
⇒ 处置：**把这些文件移出仓库**（它们只服务"如何重跑"，不影响结论的证据链 —— 结论所需的读数都已落进 `REPORT.md` 与 `.txt` 原始证据），
并在本文件保留**重跑说明**（凭据由环境变量注入）。采集器与原始 transcript 保留在会话工作区，可按需提供。

## 如何重跑（凭据不入库）

两个采集器的夹具凭据**一律由环境变量注入**，仓库里不出现任何口令/短信码/JWT：

```bash
# 员工夹具（用户名 + 初始密码由你在验收环境里先建/重置）
export UA_IDENT_T20='au_ua_a@<租户20企业编码>'  UA_IDENT_T21='au_ua_a@<租户21企业编码>'
export UA_PWD_INIT='<初始口令>'  UA_PWD_NEW='<新口令>'  UA_CODE='<短信码>'
export UA_T20_NAME='<租户20名>'  UA_T21_NAME='<租户21名>'  UA_T20_CODE='<租户20编码>'  UA_T20_ADMIN='<管理员手机号>'
node ua/journey2.cjs                       # UA 档（需 admin-web 在 :3001）
python3 accept-login-api.py --base http://127.0.0.1:8080   # API 档（需 admin-api 在 :8080）
```

## 已脱敏

入库前对全部文本产物做了**手机号脱敏**（`138****7889` 形态），并复核**残留 0**；短信验证码为 POC 桩固定值，企业编码/租户名为演示数据。截图未含手机号（登录页输入框截图已确认）。

## 本报告的办法论要点（值得复用的三条）

1. **真栈验收抓到单测抓不到的 P0**：员工登录在"用户名打错"时返回 **500** —— 根因是 mapper 漏 `@InterceptorIgnore`、未认证时租户拦截器 fail-closed 抛异常；**单测因 mock 掉 mapper 而全绿**（本仓点名的「mock 掉的依赖，其真实行为在生产才第一次执行」）。⇒ 关键认证路径必须有**真栈**证据。
2. **跨模型族复核会证伪"我的交付"**：第 2 轮裁判发现我送审载荷漏传 `rows`（序列化成 `undefined`）⇒ 该轮结论作废；第 3 轮又逐条点出我 4 处**产物标签与内容对不上**（汇总计数错、改密前后误标、空壳文件、响应体硬截断）。⇒ **装配产物也要自检**，与代码改动上的锚点断言/sha 自证同等重要。
3. **「未跑」不是「通过」**：本地 `verify-all.sh gate` 的 `cases` 面在变更集未命中时是**显式未跑**，而 `tests/unit_ci_workflows/**` 那层判据**本地根本不跑** ⇒ 本单先后有 3 条 required 红只出现在 CI（Case Trust 规则 G / 弱断言台账销账 / 此前的用例面）。
