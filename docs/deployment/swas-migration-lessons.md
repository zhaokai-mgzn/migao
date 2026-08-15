# SWAS 部署迁移踩坑总结（2026-08-14/15 实战）

> 用途：后续换部署平台、改 CI、迁移 compose、或部署类问题排查时，先读本页，避免重踩。
> 关联：`deploy/swas/deploy.sh`、`deploy/swas/docker-compose.yml`、`deploy/scripts/swas-deploy-ci.sh`、三个 `deploy-*.yml`。

## 一、部署模型（为什么 SAE 快、SWAS 一开始慢）

**铁律：构建跑在 CI（强机器、可并行、有缓存），服务器只拉预构建产物。**

| 阶段 | SAE 时代 | SWAS 迁移初期（错） | SWAS 现在（对） |
|---|---|---|---|
| 构建位置 | CI | **SWAS 服务器源码构建** | CI |
| 服务器动作 | 拉 jar/镜像 | 自己 build 3 个服务（10-30min） | `pull + up`（秒级~1min） |
| 单路耗时 | ~2-3min | 10-30min | 3-7min（CI 构建占大头） |

> 换部署目标时，先对齐"构建在哪、服务器做什么"，别默认照搬旧脚本。

## 二、踩过的坑 → 现象 → 根因 → 规避

### 1. 误报服务下线（查了不存在的域名）
- 现象：一直报 admin-web 000，排查半天，实际前端是好的。
- 根因：`admin.migaozn.com` **没有 DNS 记录**，真实前端入口是 `migaozn.com` / `www` / `merchant` / `ops`。
- 规避：**健康检查先 `nslookup` 域名**，确认有解析再 curl；别拿无解析域名当服务状态依据。

### 2. 并发部署互踩（单机 flock 缺失）
- 现象：main 合并同时触发 3 个 deploy，单机并发 `docker build`，容器互踩。
- 规避：服务器脚本用 `flock` 串行化（已内置在 `deploy.sh`）。

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

## 四、操作纪律（全程教训）

1. **永远走 PR 合 main**，不要 `git push` 直推 main（即使能推）。
2. 部署类改动合入后，**三个 workflow 串行验证一遍**（首启要推齐各服务的 `:latest`）。
3. 服务健康以**真实入口域名 + 外部 curl** 为准，容器端口/直连只能作辅助。
4. 改动涉及密钥/权限时，**从报错里挖出精确主体**（子账号 UID、错误 Code/Message），再让人授权，别猜。
5. `latest` 类「移动目标」（CLI、镜像 tag）要么锁版本，要么双兼容 + 完整报错日志。
