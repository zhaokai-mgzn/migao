# 上传存储与多实例（本地盘 / OSS）

> 面向部署与运维。代码侧：`StorageDeploymentSelfCheck`（启动自检）、`StorageHealthIndicator` +
> `/api/version/storage`（读数）、`LocalFileStorageService` / `OssService`（两种实现）。
> 缺陷出处 = 集群就绪度审计报告 `docs/deployment/cluster-readiness-audit.md` 的 **P0-3**：
> 上传写本地磁盘，多实例「写 A 读 B ⇒ 404」，且**启动期没有任何提示**。

## 30 秒结论

| 部署形态 | 上传落点 | 启动行为 | 读数 |
|---|---|---|---|
| 单实例（默认，`MIGAO_REPLICAS` 未设或 `=1`）+ **未**配 OSS | 本机 `uploads/` | 正常启动 + **1 条 WARN**（仅限单实例） | `storage=local` |
| **多实例**（`MIGAO_REPLICAS` ≥ 2）+ **未**配 OSS | —— | **拒绝启动**（fail-close，报文给可行动指引） | —— |
| 任意实例数 + OSS 三项凭据齐备 | OSS 桶 | 正常启动 + INFO | `storage=oss` |
| `MIGAO_REPLICAS` 写错（非整数 / `<1`） | —— | **拒绝启动**（判不出来 = 不许当单实例放行） | —— |

一句话：**单实例可以继续用本地盘（但要接受「重建容器/换机就丢图」）；开第二个实例之前必须切 OSS。**

---

## 1. 两种存储形态

| | 本地盘（默认） | OSS（`aliyun.oss.*` 三项凭据齐备即启用） |
|---|---|---|
| 实现 | `LocalFileStorageService` | `OssService`（`@Primary`） |
| 落盘 | `<WORKDIR>/uploads/<目录>/<uuid>.<ext>`（容器里 = `/app/uploads`，compose 挂宿主机 `/opt/migao-deploy/uploads`） | `{目录}/{yyyy/MM/dd}/{uuid}.<ext>` |
| 访问 URL | `/api/files/static/<目录>/<uuid>.<ext>`，由 `WebConfig` 的 `file:uploads/` 静态面托管 | `<OSS_URL_PREFIX>/<objectKey>`（未配 `URL_PREFIX` 时回落 `https://<bucket>.<endpoint>/<key>`） |
| 聊天图 | 同上 | `chat/` 前缀 ⇒ **临时桶**（未配则回落永久桶） |
| 多实例 | ❌ 写 A 读 B 必 404；多机是**两份互不可见**的目录 | ✅ 共享 |

本地盘还有两个**不依赖实例数**的坑（审计 P0-3 ②）：
① `docker compose up -d` 重建容器 ⇒ 只要漏了那条宿主卷，用户上传的图片**全丢**；
② 换机器 / 迁移部署机 ⇒ `/opt/migao-deploy/uploads` 不跟过去。

> 目标形态：**生产切 OSS**（`OssService` 自动成为 `@Primary`，不改代码）。
> 本地静态面继续保留，只为「OSS 开通之前的历史文件」提供只读访问。

---

## 2. 「多实例」怎么判定：显式环境变量，不靠猜

**唯一判据 = `MIGAO_REPLICAS`（默认 `1`）**

- 扩容时由部署面**显式**注入：手工 `MIGAO_REPLICAS=2` / compose `deploy.replicas` / K8s `replicas` 同步写进同一个 env；
- 值 `>1` ⇒ 视为多实例；未设或 `=1` ⇒ 单实例；
- 非整数 / `0` / 负数 ⇒ **拒绝启动**（一个写错的值被静默当成单实例，护栏就正好在最需要它时失效）。

**为什么不用自动探测**（hostname 形态 / 是否在容器里 / 有没有编排环境变量）：这些信号单实例和多实例
会互相误判，而误判的代价是单向的 —— 漏判 = 图片静默 404，误判 = 正常环境起不来。

**为什么不用 `MIGAO_INSTANCE_ID`**：那个变量是**每实例的身份**（`AgentBatchLeaseService` 的租约心跳用），
它回答「我是谁」，不回答「一共有几个实例」。两者不能互相替代。

---

## 3. 启动期行为与日志原文

### 多实例 + 缺 OSS ⇒ 拒绝启动（fail-close）

启动失败，`Exit 1`，报错原文（`StorageDeploymentSelfCheck`，关键词可直接 grep）：

```
多实例部署必须配置 OSS：检测到 MIGAO_REPLICAS=2（>1），而 aliyun.oss.endpoint / access-key-id /
access-key-secret 未配齐（缺 OSS_ENDPOINT）。多实例下本地上传目录是各实例私有磁盘 ⇒ 上传打到实例 A、
图片读到实例 B ⇒ 404。修复（二选一）：① 在 .env.admin-api 配齐 OSS_ENDPOINT / OSS_ACCESS_KEY_ID /
OSS_ACCESS_KEY_SECRET（外加 OSS_PERMANENT_BUCKET_NAME / OSS_TEMPORARY_BUCKET_NAME）；② 若确为单实例，
把 MIGAO_REPLICAS 设为 1（或删掉）。详见 docs/deployment/upload-storage-and-multi-instance.md
```

⚠️ 它**早于**端口监听与探活（`@PostConstruct`）⇒ 不会「先上线再爆」，负载均衡也摘不到半启动的实例。

### 单实例 + 缺 OSS ⇒ 正常启动 + 一条 WARN

```
上传存储 = 本地磁盘（uploads/），仅限单实例部署：MIGAO_REPLICAS 未设置或 =1，且未配置 OSS。
多实例部署必须配置 OSS，否则「写 A 读 B」必 404（MIGAO_REPLICAS>1 且缺 OSS 时会拒绝启动）。
详见 docs/deployment/upload-storage-and-multi-instance.md
```

### OSS 齐备 ⇒ INFO

```
上传存储 = OSS（bucket=…，permanent=…，temporary=…），MIGAO_REPLICAS=1
```

---

## 4. 运维读数：这台实例的图片写在哪

两个面，**同一个数据源**（`StorageDeploymentSelfCheck`），字段面只有 4 个非敏感值
（`storage` / `multiInstance` / `replicas` / `ossConfigured`），**不含** endpoint / AccessKey / bucket / 本地路径。

```bash
# 生产可达（`/api/` 前缀 nginx 已放行）
curl -s https://<域名>/api/version/storage | jq .
# {
#   "storage": "oss",
#   "multiInstance": "false",
#   "replicas": "1",
#   "ossConfigured": "true"
# }

# 本机 / 内网（`/actuator/**` 在生产被 nginx 屏蔽，见 deploy/swas/nginx.conf）
curl -s http://127.0.0.1:8080/actuator/health | jq .components.uploadStorage
```

读数语义（**别把「取不到」当「单实例安全」**）：

| `storage` | 含义 | 能开多实例吗 |
|---|---|---|
| `oss` | 图片写共享桶 | ✅ |
| `local` | 图片只写这台机器的磁盘 | ❌（`MIGAO_REPLICAS>1` 会被启动自检拦下） |
| `unknown` | 端点被切片/未装配（非部署形态） | 不可判定 |

---

## 5. 切到 OSS（生产开通步骤）

1. **配凭据**（`.env.admin-api`，不进仓库）：
   ```dotenv
   OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
   OSS_ACCESS_KEY_ID=...
   OSS_ACCESS_KEY_SECRET=...
   OSS_BUCKET_NAME=...
   OSS_PERMANENT_BUCKET_NAME=...
   OSS_TEMPORARY_BUCKET_NAME=...
   OSS_URL_PREFIX=https://<公网前缀>
   ```
   ⚠️ **三项凭据都必须非空白**：`application.yml` 把 `endpoint` / `access-key-id` / `access-key-secret`
   默认成**空串**（`${OSS_ENDPOINT:}`），而「空串」≠「配了」——自检与 `OssService` 用的是同一份判据
   （`OssConfig.hasCredentials()`，三项都非空白）。
2. **重启 admin-api**，日志里应出现 `上传存储 = OSS（bucket=…）`。
3. **验读数**：`curl /api/version/storage` ⇒ `storage=oss`。
4. **验通路**：上传一张图 → 拿返回的 `url` → `curl -I` 应 200。
5. 之后**才**谈扩容：`MIGAO_REPLICAS=<实例数>` 与真实实例数保持一致。

---

## 6. 迁移已有本地文件到 OSS

> 顺序很重要：**先切 OSS（新写入进桶）→ 再迁存量 → 再回填 URL**。
> 迁移期间本地静态面**照旧在服务**，所以老 URL 不会因为「切了 OSS」而立刻 404。

### ① 盘点（只读）

```bash
LOCAL_UPLOAD_DIR=/opt/migao-deploy/uploads      # compose 挂载的宿主目录
find "$LOCAL_UPLOAD_DIR" -type f | wc -l        # 文件数
du -sh "$LOCAL_UPLOAD_DIR"                      # 体量
find "$LOCAL_UPLOAD_DIR" -type f -printf '%TY-%Tm-%Td\n' | sort | tail -3   # 最新写入时间
```

### ② 配 ossutil（用与服务同一套 AK，**不要**把 AK 写进仓库）

```bash
ossutil config      # 交互填 endpoint / accessKeyID / accessKeySecret
```

### ③ 复制：保留相对路径，**去掉** `uploads/` 前缀

对象 key 必须与「应用未来自己写入的 key 形态」对齐（`<目录>/<文件>`），否则回填后的 URL 指不到对象：

```bash
BUCKET=<永久桶名>
PREFIX=""            # 需要独立子目录时写 "legacy/"，但 URL 回填要同步带上
LOCAL_UPLOAD_DIR=/opt/migao-deploy/uploads

# 先 dry-run 看清要传什么
ossutil cp -r --update "$LOCAL_UPLOAD_DIR/" "oss://$BUCKET/$PREFIX" --dry-run

# 真传（--update：只传大小/时间有变化的）
ossutil cp -r --update "$LOCAL_UPLOAD_DIR/" "oss://$BUCKET/$PREFIX"

# 公网可读（永久桶的上传走 object 级 public-read；ossutil 搬过来的对象要显式设）
# 若桶已是 Bucket 级公共读，可跳过
ossutil set-acl "oss://$BUCKET/$PREFIX" public-read -r
```

> **聊天图（`chat/`）注意**：应用把 `chat/` 前缀写到**临时桶**。存量迁移前先决定这些对象进哪个桶，
> 并确认对应桶的公开读策略（临时桶是 bucket 级 ACL，不接受 object 级 public ACL）。

### ④ 校验（数量 + 抽样 + 公网）

```bash
# 数量对齐
find "$LOCAL_UPLOAD_DIR" -type f | wc -l
ossutil ls "oss://$BUCKET/$PREFIX" -s | tail -1        # 对象数 / 总大小

# 抽样：md5 与远端 ETag 对齐
f="products/<某个文件>.jpg"
ossutil stat "oss://$BUCKET/$PREFIX$f" | grep -i etag
md5sum "$LOCAL_UPLOAD_DIR/$f"

# 公网回读（URL_PREFIX 就是库里要回填的前缀）
curl -sI "https://<OSS_URL_PREFIX>/$PREFIX$f" | head -3
```

### ⑤ 回填 URL（**先备份，再分批，可重复执行**）

库里既有**相对**形态（`/api/files/static/...`）也有**绝对**形态（`https://<域名>/api/files/static/...`），
两种都要处理；先只读盘点哪些表/列还留着本地静态面 URL：

```sql
-- 只读：找出候选表/列（text / varchar / jsonb）
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type IN ('text', 'character varying', 'jsonb')
ORDER BY table_name, column_name;

-- 只读：按已知列盘点存量（示例：商品图）
SELECT count(*) FILTER (WHERE images::text       LIKE '%/api/files/static/%') AS images_hit,
       count(*) FILTER (WHERE detail_images::text LIKE '%/api/files/static/%') AS detail_hit,
       count(*) FILTER (WHERE color_image_url    LIKE '%/api/files/static/%') AS color_hit
FROM products;
```

回填模板（`<OSS 前缀>` = 上面的 `URL_PREFIX`，不带尾部 `/`）：

```sql
BEGIN;

-- ① 备份（迁移期保留，核实后才删）
CREATE TABLE IF NOT EXISTS _bak_products_images_20261122 AS
SELECT id, images, detail_images, color_image_url FROM products;

-- ② 绝对 URL → OSS 前缀
UPDATE products
SET images = replace(images::text, 'https://<域名>/api/files/static/', '<OSS 前缀>/')::jsonb
WHERE images::text LIKE '%https://<域名>/api/files/static/%';

UPDATE products
SET color_image_url = replace(color_image_url, 'https://<域名>/api/files/static/', '<OSS 前缀>/')
WHERE color_image_url LIKE '%https://<域名>/api/files/static/%';

-- ③ 相对 URL → OSS 前缀（上面没命中的那一半）
UPDATE products
SET images = replace(images::text, '/api/files/static/', '<OSS 前缀>/')::jsonb
WHERE images::text LIKE '%"/api/files/static/%';

COMMIT;
```

重复执行安全（`WHERE ... LIKE` 天然幂等：已回填的行不再命中）。其它表（`detail_images`、
工序/入库作业照片、收款码 `image_url` 等）照同一模板逐表处理 —— **每张表都先跑一次只读盘点**，
不要凭表名猜列名。迁移脚本落成 `docs/deployment/` 下的独立 SQL 文件再执行，别在会话里手写一次性 SQL。

### ⑥ 回滚与收尾

- 回滚：`_bak_*` 备份表还在 ⇒ 按 `id` 回写三列即可（本地文件**一个都别删**）。
- 本地文件保留**至少一个发布周期**，确认线上无 404 后再归档。
- 归档后仍保留 `/api/files/static/**` 的静态托管（遗留只读面），别急着删 `WebConfig` 那段 ——
  删了会让「没回填干净」的老 URL 从 404 变成 404（无收益、有风险）。

---

## 7. 排查清单

| 现象 | 先看什么 | 结论 |
|---|---|---|
| 启动失败，报「多实例部署必须配置 OSS」 | 报错里的「缺 X」那一项 | 补 `.env.admin-api` 的对应变量；确为单实例则把 `MIGAO_REPLICAS` 设回 1 |
| 以为配了 OSS，但 `/api/version/storage` 报 `local` | `aliyun.oss.endpoint/access-key-id/access-key-secret` 是否**都非空白** | 有一项是空串 = 没配（空串不等于配了） |
| 上传返回 200，但图片 404 | 两台实例各自的 `/api/version/storage` | 一台 `local` 一台 `local` ⇒ 就是 P0-3 本身，切 OSS |
| 重启/重建容器后图片全丢 | compose 的 `uploads` 宿主卷是否挂上 | 见 `deploy/swas/docker-compose.yml` 的注释；根治仍是切 OSS |
| 迁移后仍有零散 404 | 漏回填的表/列（JSONB 里嵌套的 URL） | 按 §6⑤ 逐表盘点，`replace(...::text ...)::jsonb` 覆盖嵌套 |

---

## 8. 本页**不**覆盖（照实登记）

- 静态本地托管**未**降级为「仅遗留只读」（仍按原样挂 `file:uploads/`）；要彻底关闭需另开单。
- 其它多实例缺陷（进程内 `access_token` 缓存、进程内取号、幂等键、nginx 无 upstream 等）
  见审计报告 `docs/deployment/cluster-readiness-audit.md`，本页只负责「上传存储 + 启动护栏 + 读数」。
