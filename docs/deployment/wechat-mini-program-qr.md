# 微信小程序 A 档：扫普通链接二维码直接打开报工页

> 关联 issue #8196（**仓库侧**；用户侧的微信后台规则 / appid / 上传私钥 / 提审发布 **未做** ⇒ 部分交付）。
> 本文只讲「从仓库到小程序能扫开」这一段；工人扫码报工的页面口径见
> `frontend/bmini-app/src/pages/worker/report/index.tsx` 的类注释。

## 1. 范围与已定口径

| 项 | 口径 |
|---|---|
| A 档 | 微信「扫普通链接二维码打开小程序」：微信里扫纸上的 `https://app.migaozn.com/s/<短码>` ⇒ **直接打开小程序的报工页**（参数在 `q`） |
| 短码 | 🔴 **不可重印**：`/s/<短码>` 路径段与 8 位 Crockford Base32 短码**一字不动**；302 面继续服务浏览器与其它扫码工具 |
| 小程序范围 | 维持现有**三角色**（管理员 / 员工 / 工人）；**不改**三角色登录页（`pages/auth/login?tab=worker` 保留为常规入口） |
| 工人菜单 / 样式 | 与 `/b/` **单一真源**：`/b/` 就是同一份 `frontend/bmini-app/src` 的 `build:h5` 产物（Taro 双编译），不是第二套代码 |
| 不改 | `/w/`（worker-h5 兼容期）与 `/b/` 的既有语义；短链 302 的目标与查询键 |

**为什么还要一个 JSON 面**：小程序**不跟随 HTTP 302**。微信把整条链接放进
`getEnterOptionsSync().query.q`，页面手里只有一个短码；`/s/<短码>` 的 302 在小程序里等于一个空响应
（线上表现：扫码后停在报工页、报工按钮一直不出来，且不会有任何东西会变红）。`/s/` 不可重印 ⇒
仓库侧新增 **显式**的 JSON 解析面，而不是改短链语义。

## 2. 线上坐标（谁拥有什么）

| 件 | 值 / 位置 | 所有者 |
|---|---|---|
| 二维码内容（印在纸上） | `https://app.migaozn.com/s/<短码>` | 仓库（`WorkerShortLinkService`） |
| 短链 302（浏览器 / 任意扫码工具） | `https://app.migaozn.com/s/<短码>` ⇒ `302` `/b/report/?t=<token>&tenant_id=…&tenant_code=…` | 仓库（`WorkerShortLinkController`） |
| **短链 JSON 解析**（小程序 A 档） | `GET /s/<短码>/json` ⇒ `200 {"reportPath":"/b/report/","token":"<token>"}`；未知 ⇒ `404 {"error":"not_found"}`；已撤销 ⇒ `410 {"error":"revoked"}` | 仓库（`WorkerShortLinkController#resolveJson`） |
| 小程序页面 | `pages/worker/report/index` | 仓库（`frontend/bmini-app/src/pages/worker/report/`） |
| 校验文件（微信生成） | `https://app.migaozn.com/<名字>.txt`；源文件放 `deploy/swas/wechat-verify/` | **文件内容 = 用户侧**；承接 = 仓库（`deploy.sh` + `nginx.conf`） |
| 静态根 | `/opt/migaozn.com` → `/opt/migao-deploy/h5`（nginx `root`） | 仓库（发布腿 / `deploy.sh`） |
| appid / 上传私钥 / 后台规则 / 提审 | 微信公众平台（mp.weixin.qq.com） | **用户侧**（仓库里 `project.config.json` 的 `appid: "touristappid"` 是占位，**不要**把真 appid / 私钥写进仓） |

> 小程序请求 API 用的是 `TARO_APP_API_URL`（`frontend/bmini-app/src/utils/constants.ts::API_BASE_URL`）——
> 线上即 `https://api.migaozn.com`。这条链路上的 `/s/<短码>/json` 也由同一份 `/s/` 转发承担
> （`api.migaozn.com` 的 `location /` 反代到 admin-api；`worker_entry` 限流按 `/s/` 口径计账）。

## 3. 微信后台规则（用户侧，一次性）

1. 微信公众平台 → 小程序后台 → **开发 → 开发管理 → 扫普通链接二维码打开小程序** → 添加规则。
2. 填：

   | 字段 | 值 |
   |---|---|
   | 二维码规则（URL 前缀） | `https://app.migaozn.com/s/`（必须 https、以 `/` 结尾） |
   | 小程序功能页面 | `pages/worker/report/index` |
   | 测试链接 / 是否发布 | 先用「测试链接」验，通过后再发布规则（规则本身也可能进审核） |

3. 按后台提示**下载校验文件**，原样放进 `deploy/swas/wechat-verify/`（说明见该目录 README），
   部署后用 `curl` 自证（§4）。校验通过后后台才允许保存/发布规则。

**规则命中后 `q` 怎么映射**（真值 = `frontend/bmini-app/src/utils/scanInput.ts::resolveScanLanding`
与 `src/pages/worker/report/index.tsx` 的入口效果）：

| 扫到的链接 | `q`（URL-encoded 整条链接） | 解析 | 动作 |
|---|---|---|---|
| `…/s/7K3M9QP2` | `https%3A%2F%2Fapp.migaozn.com%2Fs%2F7K3M9QP2` | `code=7K3M9QP2`、`from=link-qr-short` | 调 `GET /s/7K3M9QP2/json` 换 **token** ⇒ 走既有报工流程（未登录 ⇒ 就地登录，登录后继续手里的码） |
| `…/b/report/?t=<token>` | 同上（302 落点形态） | `code=<token>`、`from=link-qr` | 直接用 `t`，**不**多打一跳 |
| 页面参数 `?t=<token>`（启动器 `redirectTo` 带过来） | — | `from=param-t` | 行为不变 |
| 直接打开 `/b/report/`（无码） | — | `kind=none` | 行为不变（手输码 / 扫一扫） |
| 未知 / 已撤销短码 | — | 404 / 410 | **明确错误**上屏（不白屏、不重试）；死码不跨登录带走 |
| JSON 面读不到（离线 / 旧后端无此路径） | — | 无状态码 | **退回既有行为**：短码原样交给工人扫码端点（`ProductionScanService` 本来就认短码）——已印出去的码不能因为新版前端而作废 |

> 规则前缀**没命中**时，微信按普通链接处理（浏览器打开 ⇒ 走 302 的 H5 路径）。
> `/o/<短码>`（加工单级）本包**不配** A 档规则（见 §9）。

## 4. 校验文件落位与部署（仓库侧已自动化）

- 承接位：[`deploy/swas/wechat-verify/`](../../deploy/swas/wechat-verify/README.md)（只有 README，**不预置任何 `.txt`**）。
- 落位：[`deploy/swas/deploy.sh`](../../deploy/swas/deploy.sh) 的 `1.3.1` 段把该目录下**所有 `*.txt`**
  **幂等**拷到静态根根下；只**增 / 覆盖**、**不删**任何别的文件（那个根同时是 C 端 h5 的落地面）；
  源目录空 / 源码树不在 / 静态根不存在 ⇒ **出声跳过**，不拖垮部署。
- 服务：[`deploy/swas/nginx.conf`](../../deploy/swas/nginx.conf) 的
  `location ~ ^/[^/]+\.txt$ { try_files $uri =404; }` —— **缺失就是 404**，
  **绝不**回落 SPA 的 `index.html`（回落 = HTTP 200 的一页 HTML，与「内容对不上」无法区分）；
  该正则只匹配**根下单段**，不劫持 `/b/` `/w/` `/terminal/`。

部署后自证（任意能上网的机器）：

```bash
NAME='<微信给的文件名，不含 .txt>'
curl -s "https://app.migaozn.com/${NAME}.txt" | diff - "deploy/swas/wechat-verify/${NAME}.txt" && echo OK
curl -sI "https://app.migaozn.com/${NAME}.txt" | grep -iE '^HTTP/|^content-type'   # 期望 200 + text/plain
curl -s -o /dev/null -w '%{http_code}\n' https://app.migaozn.com/__missing__.txt    # 期望 404（不是 200）
```

判据（本地可复算，零网络）：

```bash
python3 -m pytest tests/unit_ci_workflows/test_wechat_verify_route.py -q
```

## 5. 构建 / 上传 / 提审（用户侧）

```bash
cd frontend/bmini-app
npm ci                 # 与 main 同一份 package-lock
npm run build:weapp    # Taro 4.2.1 ⇒ dist/（project.config.json 的 miniprogramRoot = ./dist）
```

1. 微信开发者工具 → 导入项目 → 选 **`frontend/bmini-app` 目录**（不是 `dist/`），appid 填**自己的**。
2. 确认「不校验合法域名」**只在开发时**勾选；真机必须在小程序后台
   **开发管理 → 开发设置 → 服务器域名 → request 合法域名** 里加上实际 API 域名
   （线上 = `https://api.migaozn.com`；以构建时的 `TARO_APP_API_URL` 为准）。⚠️ 用户侧配置，仓库不代填。
3. 上传：开发者工具「上传」（需要你有该小程序的开发权限 / 上传私钥走 CI 时由你放
   `private.<appid>.key`，**绝不入库**）→ 后台 **版本管理** 里设为体验版。
4. 提审 → 发布。审核通过前，A 档规则用「测试链接」先验（测试链接也要先过校验文件）。

> 🔴 仓库侧**不**写 appid、不写私钥、不写校验文件内容：它们都是用户侧产物，写进仓只会造成
> 「看起来配好了」的假绿。判据 = `tests/unit_ci_workflows/test_wechat_verify_route.py` 的
> 「本目录不得预置 `*.txt`」。

## 6. 三角色范围与工人菜单单一真源（目标 ⑤）

口径：**`/b/` 与小程序是同一份源码**（`frontend/bmini-app/src` → `build:h5` / `build:weapp`），
菜单、样式、路由、登录页**不存在第二份实现**。可复算的命令：

```bash
# 工人面：未登录先分流（写入口台账，未登记即红 / 只许缩短）+ 菜单显隐 + 入口可达性 + 输入面
cd frontend/bmini-app
./node_modules/.bin/jest \
  tests/worker-surface-ledger.test.ts tests/worker-home-menu.test.tsx \
  tests/worker-home-page.test.tsx tests/page-entry-reachability.test.ts \
  tests/input-center-guard.test.ts tests/worker-menu-single-source.test.ts

# 三角色登录页（管理员 / 员工 / 工人）与角色守卫
./node_modules/.bin/jest tests/login-page.test.tsx tests/role-guard.test.tsx \
  tests/login-identifier-split.test.tsx tests/worker-login-parity.test.ts

# 后端页面键目录（菜单开关的**唯一**来源）与目录端点
cd ../../backend/admin-api
./mvnw -Dtest=WorkerPagesTest,WorkerPageCatalogControllerTest test
```

本次对「第二份映射」的处置：bmini 的 `src/utils/workerMenu.ts` 曾把后端页面键**字面量**抄了一份
（`WORKER_MENU_KEYS`），与 `backend/admin-api/.../worker/WorkerPages.java` 之间**没有判据**——
后端加了一个键、前端拼错一个键，都不会变红。新增判据
`frontend/bmini-app/tests/worker-menu-single-source.test.ts`：**bmini 的键集必须是后端
`WorkerPages` 常量值的子集**（只许缩小方向：后端新增键不强制小程序加菜单，但前端**不许发明**后端没有的键）。
菜单「标签 + 路由」仍只在 bmini 一份（后端只下发**可见页面键集合**），不存在第二份标签映射。

## 7. 验收步骤（仓库侧可做的 + 必须人做的）

| # | 步骤 | 谁做 | 怎么判 |
|---|---|---|---|
| 1 | 短链 JSON 面形状与不泄露（正常 / 未知 / 撤销 / 浏览器仍 302） | 仓库 | `cd backend/admin-api && ./mvnw -Dtest=WorkerShortLinkControllerTest test` |
| 2 | A 档 `q` 四种落地 + 解码边界（中文 / 百分号 / 重复参数 / 非法编码） | 仓库 | `cd frontend/bmini-app && ./node_modules/.bin/jest tests/worker-report-wechat-qr.test.tsx tests/worker-short-link-service.test.ts tests/report-landing.test.ts` |
| 3 | 校验文件 nginx 面 + 落位拷贝语义 | 仓库 | `python3 -m pytest tests/unit_ci_workflows/test_wechat_verify_route.py -q` |
| 4 | H5 回归：扫纸上的码 ⇒ 302 ⇒ `/b/report/?t=` ⇒ 就地登录 ⇒ 报工 | 人（真机 / 浏览器） | 页面能出工序与「报工」按钮；回执只认服务端 |
| 5 | 小程序真机：微信「扫一扫」纸上的码 ⇒ **直接进小程序**报工页 | **人（必须真机 + 真微信）** | 首屏是工人报工（未登录先登录）；不是浏览器、不是商家首页 |
| 6 | 后台规则 / 提审 / 发布 | **人** | 微信后台状态 = 已发布 |
| 7 | 服务器域名白名单 | **人** | 真机请求不被 `urlCheck` 拦 |

## 8. 回滚

| 面 | 回滚动作 | 影响 |
|---|---|---|
| 小程序版本 | 后台「版本管理 → 回退」到上一线上版本 | 已发布规则仍指向 `pages/worker/report/index` ⇒ 回退后仍可打开（旧版没有 `q` 解析 ⇒ 停在报工页，可手输） |
| A 档规则 | 后台停用 / 删除规则 | 微信里的同一个码**退回浏览器打开**（302 路径照旧可用）——纸上的码不失效 |
| 校验文件 | 删掉 `deploy/swas/wechat-verify/*.txt`（或从后台重新生成） | 只是规则无法重新校验，不影响已发布规则 |
| JSON 面 | 前端有 fallback（短码原样交给工人扫码端点）⇒ 服务端撤掉 JSON 面**不会**让已印出去的码失效 | 小程序首次扫码会慢一跳后仍可报工 |
| `deploy.sh` 段 | 删掉 `# >>> wechat-verify` ～ `# <<< wechat-verify` 之间 | 稳态无影响（只是不再落位校验文件） |
| 数据面 | **无 DB 迁移** | — |

## 9. 未覆盖（照实登记）

- **用户侧**：微信 appid、上传私钥、后台二维码规则（`https://app.migaozn.com/s/` → `pages/worker/report/index`）、
  规则发布与**审核**、服务器域名白名单 —— 仓库里**没有**也**不该有**这些值。
- **校验文件的真实文件名 / 内容**：微信生成，用户下载后原样放入；仓库只做承接（判据禁止预置假文件）。
- **真机扫码**：需要人 + 真微信 + 真纸码（本仓 CI 不跑真机）。
- **`/o/<短码>`（加工单级二维码）的 A 档规则**：本包只配 `/s/`。`/o/` 的码在浏览器路径下照旧 302 可用；
  若以后也要直开小程序，需要同款 JSON 面 + 规则（**另一张单**）。
- **多环境 appid**（云测试 / 正式各一个小程序）：未区分，属用户侧配置管理。
- **`q` 的微信端差异**（不同微信版本对 `q` 的编码形态）：解析侧对百分号 / 中文 / 重复参数都做了容错
  （判据在 `worker-report-wechat-qr.test.tsx`），但**真机读数**仍要 §7 的第 5 步人工确认。

## 10. 判据清单（改坏了会怎么红）

| 判据 | 覆盖 | 红证形态 |
|---|---|---|
| `backend/admin-api/src/test/java/com/migao/admin/controller/WorkerShortLinkControllerTest.java` | 302 面不变 + JSON 面（200/404/410、不泄露、手输归一、只认短码） | 删 JSON 映射 ⇒ 4 条红；改 `Location` / 加字段 ⇒ 具名红 |
| `frontend/bmini-app/tests/worker-report-wechat-qr.test.tsx` | A 档 `q` 四类落地 + 明确错误 + 不重试 + 解码边界 | 把短码直接当 token ⇒ ① 红；登录后才解析 ⇒ ② 红；无码也发请求 ⇒ ④b 红 |
| `frontend/bmini-app/tests/worker-short-link-service.test.ts` | JSON 面的客户端形状（路径 / Accept / 不带凭据 / 状态码） | 路径写错 / 带 Authorization ⇒ 红 |
| `frontend/bmini-app/tests/worker-menu-single-source.test.ts` | 工人菜单键命名空间的跨语言同源（子集） | 前端发明后端没有的键 ⇒ 具名红 |
| `tests/unit_ci_workflows/test_wechat_verify_route.py` | nginx 根下 `.txt` 显式面（缺失 404 / 不劫持命名空间）+ 落位拷贝（只拷 txt / 幂等 / 父目录哈希不变 / 出声跳过） | 删 location ⇒ 缺失变 `index.html`；改成 `rsync --delete` ⇒ 拷贝判据红 |
| `tests/unit_ci_workflows/test_bmini_h5_hosting.py` / `test_terminal_release_leg.py` | app 段「无正则 location」的类级不变式（唯一例外 = 本单的 `.txt` 面） | 再塞一条别的正则 location ⇒ 具名红 |
