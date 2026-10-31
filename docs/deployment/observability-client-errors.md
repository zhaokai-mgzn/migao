# 客户端可观测面：白屏出口 / 错误上报 / 合成探针 / 构建身份（issue #8203 · 审计 P0-03）

> **这份文件的定位**：本仓**当前真的存在**的可观测面清单 —— 哪几个面能回答「线上坏了吗 / 跑的是哪个版本 / 用户在哪个页面看到白屏」，以及**刻意没做**的那部分。
> 它由 issue #8203 建立（审计 `acceptance/2026-10-31-launch-audit/findings.md` 的 P0-03「白屏无出口、线上无人知道」+ P0-04「无合成探针 / 无告警触达」）。
> 判据（会红的那些）在 `tests/unit_ci_workflows/test_synthetic_probe.py` 与各端测试里；本文件只写**口径与复算命令**。
>
> ⚠️ 本文件**不承诺**「已经接了 APM / 告警升级」—— 见 §5「已知不覆盖」。把「有探针」读成「有人被叫醒」是本单最想避免的误读。

---

## 1. 面 ①：白屏出口（前端错误边界）

浏览器渲染期异常（脏数据 / 接口形状变化 / hydration 崩）改前**整页白屏且无出口**：58 个页面里只有
`frontend/admin-web/src/app/(dashboard)/customers/error.tsx` 一个错误边界。

现覆盖（Next.js App Router 的就近原则，**越具体越优先**）：

| 边界文件 | 覆盖范围 | 回入口 |
|---|---|---|
| `frontend/admin-web/src/app/global-error.tsx` | **root layout 自身**崩（任何 `error.tsx` 都接不住） | `/` |
| `frontend/admin-web/src/app/error.tsx` | 没有自有边界的路由（`login/` / `register/` / `change-password/`）+ **路由组 layout 自身**崩 | `/login` |
| `frontend/admin-web/src/app/(dashboard)/error.tsx` | 工作台路由组内全部页面 | `/dashboard` |
| `frontend/admin-web/src/app/(corporate)/error.tsx` | 官网 / 企业站（**未登录访客**面） | `/` |
| `frontend/admin-web/src/app/(dashboard)/customers/error.tsx` | 客户管理页（更具体 ⇒ 优先于路由组边界） | `/dashboard` |

四个边界都渲染**同一个** `frontend/admin-web/src/components/common/ErrorFallback.tsx` ⇒
形态与行为只有一份实现：**重试（`reset()`）+ 回入口（原生 `<a>`，整页跳转）+ 上报一次**。
`digest` 是 React 给的**可检索编号**，有就展示（客服 / 研发据此查日志），没有就不编。

> 落点为什么各不相同（不是审美）：`app/error.tsx` 可能**正是**被「工作台 layout 崩了」触发的，
> 回 `/dashboard` 会立刻再崩一次 ⇒ 它回 `/login`（静态页）。
>
> ⚠️ `global-error.tsx` **只在生产构建里生效**：开发态的错误 overlay 会盖住它。验收以
> `npm run build && npm run start`（或线上）为准，`npm run dev` 里看不见它是**正常现象**。

## 2. 面 ②：客户端错误上报（`POST /api/client-errors`）

| 项 | 值 |
|---|---|
| 采集 / 归一 | `frontend/admin-web/src/lib/clientErrorReporter.ts`（纯函数 `buildClientErrorEvent`） |
| 装载 | `frontend/admin-web/src/components/ClientErrorReporter.tsx`（`'use client'` + **模块顶层**安装 ⇒ 早于 React 首次 commit，覆盖 hydration 崩溃；幂等） |
| 端点 | `POST /api/client-errors`（`backend/admin-api/src/main/java/com/migao/admin/controller/ClientErrorController.java`） |
| 鉴权 | **`permitAll`**（登录页崩了也要能上报；这是**刻意的**公开面） |
| 写面 | **一行 SLF4J WARN**（`CLIENT_ERROR source=… path=… …`）；不建表 / 不落库 / 不进 Redis / 不推外部 |
| 体积上限 | **8 KiB**（先看 `Content-Length`，再**有界读取** ⇒ 无声明长度的分块请求同样挡） |
| 限流 | 进程内固定窗口：**30 条/分钟/IP** + **全局 600 条/分钟** |
| 状态码 | `204` 收下 / `400` 字段或 JSON 非法 / `413` 超体积 / `415` 非 JSON·非 text / `429` 限流。**无 5xx**（本端点自己出错不污染服务端 5xx 读数） |

### 上报体（**恰好 8 个字段**）

`path`（只留 pathname）、`name`、`message`、`stack`、`digest`、`at`（ISO-8601）、`ua`、`source`。

`source` 白名单：`error-boundary` / `window.onerror` / `unhandledrejection`。加新值必须**同批**改前端
`ClientErrorSource` 与后端 `ALLOWED_SOURCES`（两边分叉 ⇒ 400）。

### 隐私边界（**硬约束，违反即缺陷**）

- **采集阶段就不取**：`ReportInput` 只有 `source` / `error` / `digest` / `pathname` —— 没有入参能把
  请求体、请求头、cookie、表单值、用户标识带进来；
- **前端第二道**：`sanitizeText()` 对摘要 / 栈再做模式化涂抹（JWT、`Bearer`、`token=`·`pin=`·`phone=` 等键值、
  11 位手机号、URL 后面的 query 串）+ 长度截断；
- **服务端第三道**：落日志前按**同一套模式**再涂一次（因为第三方库抛出的 message 可能自带凭据）；
- `path` 含 `?` / `#` ⇒ **直接 400**（那说明客户端把 query 带出来了，宁可拒收也不记进日志）。

判据：`frontend/admin-web/tests/unit/lib/clientErrorReporter.test.ts`（前端采集 / 去敏 / 截断 / 去重 / 不抛）、
`backend/admin-api/src/test/java/com/migao/admin/controller/ClientErrorControllerTest.java`（端点三态 + **日志里不出现** PIN / token / JWT / 手机号 / query）。

## 3. 面 ③：只读合成探针（`scripts/synthetic_probe.py`）

**从公网打三个只读面，失败即非零退出**。只发 `GET`、不写文件、不碰数据库、不需要凭据。

| 面 | 判据 | 为什么是它 |
|---|---|---|
| `https://api.migaozn.com/api/version` | `200` + JSON 含 `app` / `sha` / `builtAt` | 后端活着**且**是这次构建 |
| `https://app.migaozn.com/b/` | `200` + 非空 body | B 端 H5 落地（商家扫码入口） |
| `https://app.migaozn.com/w/` | `200` + 非空 body | 工人报工落地（车间入口） |

**刻意不探**：`merchant.migaozn.com/login`（200 只证静态壳，证明力弱）；`/terminal/latest.json`
（终端发布尚未上线 ⇒ 现在探它 = 做一个**永久红**，正是审计 P1-04「成功即红」的教训；将来接了发布
按脚本里 `Target(allow_status=(404,))` 的语义加一条即可）。

### 退出码三态（**消费方必须照此判**）

| 码 | 含义 | 怎么读 |
|---|---|---|
| `0` | 三个面全通过 | 通过 |
| `1` | 至少一条失败（连不上 / 状态码不符 / 非 JSON / 缺字段 / body 为空） | **判红**，输出逐条给「哪个 URL / 期望什么 / 实际拿到什么 / 复算命令」 |
| `3` | **无法判定**（没有可探目标） | **不得当 `0` 读**（空跑 = 假绿） |

重试（`--attempts`，默认 2）**只对瞬态生效**（连接失败 / 5xx）—— 滚动重启窗口内的 502 不该开值班单；
`4xx` 与形状不符**当场定案**（重试只会把红推后）。

### 接线与值守面

- 接在 **`.github/workflows/post-merge-verify.yml`** 的 main 侧（`if: github.event_name != 'pull_request'`，
  且**排在 `if: failure()` 的 P1 值班 issue 出口之前** —— 之后 ⇒ 判红不产生值班单 = 静默）；
- **不新增 schedule**（铁律 10：复用它既有的 `push` / `schedule` / `dispatch` 触发面）；
- **不新增 secret**（三个面都是公开读面），**不新造告警通道**（出口 = 该腿既有的 P1 值班 issue；
  该通道**不拦合并**）；
- PR 面**不跑**：PR 红应该反映 PR，不该因为「生产站点此刻不通」把业务 PR 判红（归因会指向错误对象）。

## 4. 面 ④：构建身份 `/version`（三态语义）

| 服务 | 端点 | 字段 |
|---|---|---|
| admin-api | `GET https://api.migaozn.com/api/version` | `app` / `sha` / `tag` / `builtAt` |
| ai-agent | `GET https://ai-api.migaozn.com/version` **与** `/api/version`（同一条命名口径） | `app` / `sha` / `builtAt` |

**值来自构建期注入，不是运行期现算** —— 部署镜像里**没有 `.git`**（C′ 服务器侧构建的上下文是 codeload
归档树）⇒ 任何运行期 `git rev-parse` 都是错的。

**五跳缺一跳都不成立**（判据在 `tests/unit_ci_workflows/test_synthetic_probe.py`，逐跳钉住 + 摘除注入）：

1. workflow 现取（`git rev-parse HEAD` + runner 时钟 `date -u` 的 ISO8601 时刻）；
2. `deploy/scripts/swas-deploy-ci.sh` 的**位置参数第 9 / 10 位**（`BUILD_SHA` / `BUILT_AT`）；
3. 远端 BOOTSTRAP 的 `__BUILD_SHA__` / `__BUILT_AT__` 占位符渲染；
4. `deploy/swas/deploy.sh` 的 `docker build --build-arg MIGAO_BUILD_SHA/BUILT_AT`（三条腿共用本段）；
5. `backend/ai-agent-service/Dockerfile` 与 `backend/admin-api/Dockerfile` 的 `ARG` + **`ENV`**（`ARG` 只在
   构建期存在 ⇒ 不转 `ENV` 的话容器里读不到）⇒ `ConfigMap`/`Settings` ⇒ `/version`。

### 消费方三态（**取不到 ≠ 一致**）

| 读数 | 判 |
|---|---|
| `sha` 非空且 == 期望 | 线上**就是**这次构建 ⇒ 通过 |
| `sha` 非空且 != 期望 | **判红**（这正是本端点存在的理由：发布漂移可发现） |
| `sha` 为空 | **探不到**（老镜像 / 非部署形态启动）⇒ `exit 3`，**不得判绿也不得判红** |

> 未注入时字段是**空串**，不是 `unknown` / `null` / `0`：`unknown` 会被读成「有身份但不一致」⇒ 假红。
> 回滚路径（`MODE=rollback` 拉 ACR 预构建镜像）下，身份 = **镜像自身构建时的那次部署真值**（不是回滚动作发生的时刻）。

## 5. 已知不覆盖（照实登记，别把这张表读成「都做了」）

| 缺口 | 现状 | 重启条件 |
|---|---|---|
| **外部 APM / Sentry** | 本包**明确不接**（不引依赖、不加 DSN secret） | 需要按用户会话 / 面包屑定位问题时 |
| **告警升级**（短信 / 电话 / IM 值班） | 只有「post-merge-verify 腿红 ⇒ P1 值班 issue」，且该通道**不拦合并** | 有人被叫醒成为硬要求时（属新单，另评通道与值守成本） |
| **5xx / 错误率聚合** | 无（日志有，但**没有聚合 / 没有阈值**） | 需要「多少条就开单」的机械判据时 |
| **前端错误采样 / 用户维度** | 无（**刻意**：不做采样、不记用户标识） | 需要「多少用户受影响」这个分母时（先过隐私评审） |
| **`sendBeacon` 通道** | 无（单一 `fetch` keepalive 通道，便于判据） | 若实测 `keepalive` 在卸载时丢得多 ⇒ 再加 |
| **C 端上报**（mini-app / bmini / worker-h5） | **未接**（issue #8203 范围只有 admin-web） | C 端白屏开始出现投诉时 |
| **限流的跨实例一致性** | 进程内计数（多实例 = 实例数 × 额度；实例重启清零） | 多实例部署且日志面被刷爆时（那才值得引入共享计数） |
| **合成探针的「业务可用性」** | 三个面都只证「HTTP 面活着 + 构建身份」；`/login` 的 200 只证静态壳 | 需要「登录 + 下单能走通」时（那是 e2e / 冒烟的面，不是探针） |
| **终端发布面**（`/terminal/latest.json`） | **不探**（未上线，探它 = 永久红） | 终端发布上线后，按 `allow_status` 语义加一条 |

## 6. 回滚与复算命令

### 判定「要不要回滚」的公开读数（三个都必须是 200）

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.migaozn.com/api/version
curl -s https://api.migaozn.com/api/version                       # ⇒ {"app","sha","tag","builtAt"}
curl -s -o /dev/null -w '%{http_code}\n' https://ai-api.migaozn.com/health
curl -s https://ai-api.migaozn.com/version                        # issue #8203 新增（{app,sha,builtAt}）
curl -s -o /dev/null -w '%{http_code}\n' https://app.migaozn.com/b/
curl -s -o /dev/null -w '%{http_code}\n' https://app.migaozn.com/w/
```

> 🔴 **不要用 `https://api.migaozn.com/actuator/health` 当回滚判据**：nginx 把 actuator 面整段屏蔽
> （`deploy/swas/nginx.conf` 的 `location ~ ^/(actuator|v3/api-docs|swagger-ui)(/|$)` ⇒ `return 404`）⇒
> 「非 200 ⇒ 回滚」这条规则会**永远命中**（审计 P1-05）。容器内的 `127.0.0.1:8080/actuator/health`
> 仍是 200，但那是**回环口径**，不能当公网判据。

### 一条命令复算全部

```bash
python3 scripts/synthetic_probe.py            # 0 全通过 / 1 至少一条失败 / 3 无法判定（3 不得当 0）
python3 scripts/synthetic_probe.py --attempts 1 --timeout 5   # 网络差时缩短等待
```

### 回滚动作本身

见 `docs/deployment/rollback.md`（`gh workflow run deploy-<svc>.yml -f image_tag=<tag>` = `MODE=rollback`，
永不跳过；部署后跑上面的公网复算）。

### 判据（提交 / 改完这些面后必跑）

```bash
# 探针本体 + 接线（零网络，秒级）
python3 -m pytest tests/unit_ci_workflows/test_synthetic_probe.py -q

# 端点三态 + 隐私（Java 单类）
cd backend/admin-api && ./mvnw test -Dtest=ClientErrorControllerTest -q

# ai-agent /version 三态
cd backend/ai-agent-service && python3 -m pytest tests/test_version_probe.py -q

# 前端上报器 / 错误页出口
cd frontend/admin-web && npx vitest run tests/unit/lib/clientErrorReporter.test.ts \
  tests/unit/components/ErrorFallback.test.tsx tests/unit/components/ClientErrorReporter.test.tsx
```

### 部署后自证（构建身份真的落到了线上）

```bash
# 期望 = 本次部署的 commit
curl -s https://api.migaozn.com/api/version | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])'
curl -s https://ai-api.migaozn.com/version   | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])'
```

`sha` 为空 ⇒ **探不到**（不是「一致」）：先查该腿的 `Resolve build identity` / 驱动脚本位置参数 /
`deploy.sh` 的 `--build-arg` 段，再查 Dockerfile 的 `ENV`。

## 7. 改动这些面时的连带义务

1. **加字段 / 加来源**：前端 `ClientErrorSource` 与后端 `ALLOWED_SOURCES` **同批**改，且同步更新本文件 §2 的字段表；
2. **加探针目标**：先自己跑一遍确认它**现在是 200**（否则等于加一条永久红），再在
   `scripts/synthetic_probe.py` 的 `default_targets()` 里加，并补 `tests/unit_ci_workflows/test_synthetic_probe.py` 的覆盖面判据；
3. **改 `/version` 字段**：`VersionController` / `app/main.py` 的字段白名单判据会红 ⇒ 必须重新过一遍
   「这个字段会不会泄露」（现有字段只有 `app` / `sha` / `tag` / `builtAt`）；
4. **别新增 schedule**（铁律 10）：探针接在既有触发面上；新增周期任务要过「非破坏性 / 幂等 / 失败可见 / PR body 显式声明」四条。
