# 集群 / 多机房部署就绪度审计（只读审计）

> 审计对象：`backend/admin-api`（Java Spring Boot）、`backend/ai-agent-service`（Python FastAPI）、
> `deploy/`（compose / nginx / deploy.sh）、`frontend/`（仅与后端契约相关部分）。
> 审计方式：**只读代码**，未跑测试、未改业务代码、未连生产、未读任何 `.env`。
> 基线 commit：`604de4ee9`（`fix/8996-terminal-prod-publish`）。
> 凡「仓内找不到代码级证据」的，一律写 **未证实**，不做推断。

---

## 结论

**不能直接上集群。** 现在这套代码在**单实例**下是自洽的，但代码里至少还有 **5 处进程内状态/进程内取号**承担了
「跨请求正确性」职责，其中 4 处一开第二个实例就会立刻产生重复副作用或核心链路失败；
另外有 3 处「多实例只是降级」可以与实例数一起放行。

一句话：**先修 3 件（共享 Redis + 对象存储、定时腿 claim 化、幂等键确定性化），才允许开第 2 个实例。**

---

## 审计口径说明（先说清判定标准，避免误读）

- **P0 = 会在多实例下产生错误数据 / 重复副作用 / 核心链路成片失败**（有一条就阻断上集群）。
- **P1 = 会降级但不坏数据**（可在集群里跑，但必须排期改）。
- **P2 = 仅性能 / 运维面**（可以带着上集群）。
- 本报告**不复述**仓库文档里的设计意图，只以**代码实际行为**为准。设计意图与代码不一致处会显式指出。

---

# P0 阻断项

## P0-1 微信 `access_token` 是**进程内单例缓存**（最容易被忽略、也最致命）

**现象**
`WechatService` 把微信小程序 `access_token` 缓存在**实例字段**里，刷新走 `synchronized (this)`（只锁本进程），
注释原文写着「进程内缓存（**单实例足够**）」。

**证据**
- `backend/admin-api/src/main/java/com/migao/admin/service/WechatService.java:74-79` —— 四个 `volatile` 实例字段
  （`cachedAccessToken` / `accessTokenExpireAt` / `bminiCachedAccessToken` / `bminiAccessTokenExpireAt`）。
- `WechatService.java:240-283` —— `obtainAccessToken(...)`：命中则返回本进程缓存，否则 `synchronized (this)` 内
  **再取一次新 token**（注释：`进程内缓存（单实例足够）`）。
- 消费方（登录主链路）：`WechatService.java:184` → `GET_PHONE_URL`
  （`https://api.weixin.qq.com/wxa/business/getuserphonenumber?access_token=%s`，`WechatService.java:71-72`）；
  调用链 `MiniPhoneBindService.java:20-22,36`、`AuthController.java:176,200`。

**多实例下会发生什么**
微信侧对一个 appid **只维持一把有效调用凭证**（新 token 签发后旧 token 仅剩短暂过渡期，具体秒数以官方文档为准 —— 本仓**未证实**）。
两个实例各自按 7200s 独立刷新、各自缓存：实例 A 刷新后，实例 B 手里那把被作废，但 B **自己以为还有效**
（`accessTokenExpireAt` 是本进程算的），于是 B 的 `getuserphonenumber` 持续回 `40001 / invalid credential`，
**一直持续到 B 自己的 TTL 到期**（最长约 2 小时）。表现是「一半概率登录/绑手机失败，重试有时好有时坏」，
而且**没有任何读数会先变红** —— 这正是最难归因的一类故障。

**最小改造建议**
token 必须收敛成**全实例一份**：落 Redis（`SET NX` + `TTL = expires_in - 300`，只有一个实例真正去换），
或由一个专用「取 token 腿」统一换发、其它实例只读。**不要**上分布式锁去串行化刷新 —— 那只是把竞态换成排队。

**验证方式（怎么判改好了）**
1. 两实例并发打一次 `/api/auth/mini/phone` 预热；`docker exec` 两实例各打一条「token 指纹」日志 ⇒ 两处**同指纹**。
2. 在 A 上强制刷新（缩短 TTL 或手工删 Redis 键），B 立刻取到**同一把**新 token；
3. 连续 24h 交替调用 `getuserphonenumber`，`40001` 计数为 0。

---

## P0-2 定时待办扫描是「先查后写」，多实例会**重复投递站内提醒**

**现象**
`ScheduledTaskService` 的扫描腿：`selectList(status=pending, fire_at<=now)` → 逐条 `createNotification()` →
`updateById(status=fired)`。**整条链没有任何原子占位**（不是 `UPDATE … WHERE status='pending' RETURNING`，也没有锁）。

**证据**
- 触发载体：`backend/admin-api/src/main/java/com/migao/admin/config/ScheduledTaskScanScheduler.java:43-54`
  （`@Scheduled(cron = "0 * * * * *")`，缺省**每分钟**、**每个实例都跑**）。
- 先查：`backend/admin-api/src/main/java/com/migao/admin/mapper/ScheduledTaskMapper.java:30-38`
  （`status='pending' AND deleted=0 AND fire_at<=now`，普通 `selectList`，无 `FOR UPDATE`）。
- 后写：`backend/admin-api/src/main/java/com/migao/admin/service/ScheduledTaskService.java:192-212`（`scanDue` 逐租户）、
  `:217-228`（`deliverDueForTenant`）、`:240-250`（`deliver`：**先** `notificationService.createNotification(...)`，
  **再** `updateById(status=fired)` —— 两件事不在一个原子动作里）。
- 通知侧**没有带幂等键**：`backend/admin-api/src/main/java/com/migao/admin/service/NotificationService.java:64-82`
  （构造 `Notification` 时**没有** `dedupeKey`）⇒ 迁移里那条唯一索引对本次写入**不生效**：
  `backend/admin-api/src/main/resources/db/migration/V187__notification_biz_context_and_inbound_events.sql:49-52`
  （`uk_notifications_dedupe … WHERE dedupe_key IS NOT NULL`）。
- 对照：同仓另外三条定时腿是**对的**（原子 UPDATE 裁行）——`AutoCompleteShippedScanService`（发货后自动完成）、
  `AgentBatchLeaseService`（租约回收）、`DailyBriefingService`（Redis `setIfAbsent` + 唯一键）。
  **只有这一条腿是纯 read-modify-write。**

**多实例下会发生什么**
两个实例在同一分钟秒级同时醒来（cron 都是 `0 * * * * *`），各自读到**同一批** `pending` 行 ⇒
**每人写一条 notifications** ⇒ 员工收到**重复的到点提醒**（N 实例 = N 条）。
`updateById` 无状态谓词 ⇒ 后写覆盖先写，两行都变成 `fired`，事后从数据上**看不出**重复发生过。

**最小改造建议**
把「占位」提到投递之前，一条语句裁决：`UPDATE scheduled_tasks SET status='delivering' WHERE id=? AND status='pending' RETURNING id`
（影响行数 0 ⇒ 不是我的，跳过）—— 与仓内既有范式同款（`OrderMapper.autoCompleteShippedOrders`）。
更省的一行版：`createNotification` 时传 `dedupeKey = "scheduled_task:" + task.getId()`，让 V187 的唯一索引兜底。

**验证方式**
真库双连接并发跑两轮 `scanDue()`（不是 mock），断言：`notifications` 新增行数 == 到期任务数（不是 2 倍），
且 `deliver` 只被调用一次。判据形态照抄 `AutoCompleteShippedRealDbTest` 的双连接并发。

---

## P0-3 上传落**本地磁盘**，多实例 = 图片 404 / 重建即丢

**现象**
默认文件存储实现写宿主相对路径 `uploads/`，静态面固定从 `file:uploads/` 暴露；compose 把本地目录挂进容器。

**证据**
- `backend/admin-api/src/main/java/com/migao/admin/service/LocalFileStorageService.java:37`
  （`private static final String UPLOAD_DIR = "uploads"`）、`:43-44`（`@Value("${migao.upload.local-dir:uploads}")`）、
  `:49`（`ACCESS_PATH_PREFIX = "/api/files/static/"`）。
- 静态托管：`backend/admin-api/src/main/java/com/migao/admin/config/WebConfig.java:74-75`
  （`addResourceHandler("/api/files/static/**").addResourceLocations("file:uploads/")` —— **只认本机磁盘**）。
- 生产挂载：`deploy/swas/docker-compose.yml:60-62`（`/opt/migao-deploy/uploads:/app/uploads`）。
- 只有**配齐 OSS 三项凭据**时才改走 OSS：`OssService.java:43-46`（`@Primary` + `@ConditionalOnExpression`）、
  `OssConfig.java:57-70`（`endpoint` / `access-key-id` / `access-key-secret` 全非空才注册）。
  ⇒ **生产到底走哪条腿取决于 `.env.admin-api`（本审计未读）⇒ 「生产是否已启用 OSS」= 未证实。**
- `ai-agent` 侧无本地落盘：`backend/ai-agent-service/app/api/asr.py:134-170` 的 `tempfile.NamedTemporaryFile`
  是**请求内临时文件**（`finally` 里 `unlink`，两条分支都清）⇒ **无害**；`app/api/upload.py:1-9`（聊天图片
  **代理转发** admin-api，不在 Python 侧落盘）⇒ 也无害。

**多实例下会发生什么**
① 上传被负载均衡打到实例 A，A 写 `/app/uploads/...`；随后图片 GET 被路由到实例 B ⇒
`/api/files/static/**` 在 B 的磁盘上**不存在** ⇒ 404 / 商品图裂 / 作业照片打不开。
② 更隐蔽的一半：**即使不分实例**，`deploy.sh` 的 `docker compose up -d` 会**重建**容器 —— 只要漏了那条宿主卷，
用户上传的图片就**全丢**（`docker-compose.yml:47-56` 已把这条事故写进注释，说明踩过）。
③ 多机房时两台机器各自的 `/opt/migao-deploy/uploads` 是**两份互不可见的目录** ⇒ 跨机房 100% 读不到。

**最小改造建议**
把生产切到 `OssService`（三项凭据齐备即自动 `@Primary`），并**同时**把 `/api/files/static/**` 的本地托管降级为
「仅遗留文件只读」；未配 OSS 就**不要**上多实例（fail-closed 在地基层做，而不是靠人记得）。
若短期必须用共享盘：NFS/OSS-FUSE 只当过渡，且必须显式登记为「单点」。

**验证方式**
两实例各传一张图，交换 `url` 互相 GET 均 200；杀掉实例 A 后 B 仍能取到 A 上传的那张 ——
这才算「对象存储生效」，而不是「刚好命中了同一台」。

---

## P0-4 下单幂等键是「进程内 `lru_cache` + `uuid4` + 10 分钟窗口」⇒ 跨实例/重启**必漏判**

**现象**
`ai-agent` 生成的 `X-Client-Request-Id` 不是由请求内容推导出来的**确定性值**，而是**第一次算出来就冻在进程缓存里**的
随机串（值里带 `uuid4().hex[:12]`）。服务端去重是 DB 表（这部分是**对的**），但**键的产生**是进程内的。

**证据**
- `backend/ai-agent-service/app/tools/order_create.py:193-213`
  （`@lru_cache(maxsize=_IDEMPOTENCY_CACHE_SIZE)` 装饰 `_window_id(window, scope, *, op)`；返回值
  `f"{window}-{scope_token}-{op_token}-{uuid.uuid4().hex[:12]}"` —— **随机成分**）。
- 窗口与容量：`order_create.py:143`（`_IDEMPOTENCY_WINDOW_SECONDS = 600.0`）、`:157-159`（`_IDEMPOTENCY_CACHE_SIZE = 12288`）、
  `:226-231`（`window = int(time.time() // _IDEMPOTENCY_WINDOW_SECONDS)`）。
- 服务端（**这一半是集群安全的**）：`backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java:96-110`
  （`INSERT … ON CONFLICT (tenant_id, client_request_id) DO NOTHING`，按影响行数判首次）、`:127`（`replay` 回放快照）；
  表与唯一约束：`backend/admin-api/src/main/resources/db/init/schema.sql:3934-3943`
  （`UNIQUE (tenant_id, client_request_id)`）。
- 三个写路径共用一把键入口：`order_create.py:216-231`（`_request_window_id`）。

**多实例下会发生什么（具体触发场景）**
1. **滚动部署中途断流（最常见）**：顾客说「下单」→ 实例 A 的 `order_create` 已让服务端**落库并写入快照** →
   SSE 还没推完 A 就被 `deploy.sh` 重建 → 顾客看到断流 → 重发（前端重试 / 用户手动再发）→ 落到实例 B →
   B 的 `lru_cache` 里没有这条 `(window, scope, op)` ⇒ 生成**全新 uuid 键** ⇒ 服务端按
   `(tenant_id, client_request_id)` 查不到 ⇒ **再落一单**（同手机号、同 SKU、同数量）。资金级重复。
2. **10 分钟窗口跨边界**：LLM 在 599s 发起、重试发生在 601s ⇒ `window` 变了 ⇒ 新键 ⇒ 同样漏判。
3. **LRU 挤出**：同窗内活跃会话数超 12288 条排队（三写路径 × 会话数）⇒ 旧条目被挤出 ⇒ 重试取到新键。
   注释 `:157-159` 自己承认「容量不足 ⇒ F19 静默失效」。
4. **多机房**：DNS/轮询把重试打到另一机房 ⇒ 与场景 1 同形。

> ⚠️ 注意方向：这是**漏判重复**（多下一单），不是「误判重复把正常单吞掉」。单机时它靠「同进程 + 同窗口」成立，
> 一旦实例数 > 1 或进程重启，这个前提就没了。

**最小改造建议**
把键改成**可重算**的：`hash(session_id + op + 确认卡 id / 本轮 turn_id)`（同一轮重试必然同键，跨实例也同键），
窗口语义保留在服务端（`created_at` + 陈旧占位回收，`ClientRequestIdService.java:65` 已有 30 分钟口径）。
或者退一步：把 `_window_id` 的结果写 Redis（`SET NX` + 10min TTL），让「同键」跨实例成立 —— 但这只是把
「进程内」换成「共享」，仍不解决 LRU/重启，**首选确定性键**。

**验证方式**
两实例交替用**同一份**下单载荷调 `order_create`（模拟重试）：`orders` 只增 1 行、`client_request_keys` 只有 1 行，
且第二次返回的订单号与第一次**逐字相同**（走 replay）。再加一条：杀进程重启后重试，仍只有 1 单。

---

## P0-5 加工单号 `JG-yyyyMMdd-NNNN` 是**进程内随机起点 + 无取号重试**

**现象**
加工单号用进程内 `AtomicInteger` 生成，起点是 `ThreadLocalRandom` 随机值；撞号时**没有换号重试**，
而 `DuplicateKeyException` 被映射成一句**错误的诊断**。

**证据**
- 序列本体：`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:707-708`
  （`PO_SEQ = new AtomicInteger(ThreadLocalRandom.current().nextInt(1000, 9999))`）。
- 生成：`ProcessingOrderService.java:2108-2112`（`"JG-" + yyyyMMdd + "-" + format("%04d", PO_SEQ.incrementAndGet())`，
  注释：「DB 唯一约束兜底」）。
- 唯一约束：`backend/admin-api/src/main/resources/db/init/schema.sql:917-918`（`uk_processing_orders_no (processing_order_no)`）。
- 撞号后的处置：`ProcessingOrderService.java:1650-1655` —— `catch (DuplicateKeyException) { throw
  BusinessException.validationError("订单 … 加工单已生成（并发操作），请刷新后重试") }`。
- **同族已有正确修法，但没传染到这里**：`InboundOrderMapper.java:126-140`（原子取号 + `ON CONFLICT … DO NOTHING`）、
  `InboundOrderService.java:1176-1192`（`INBOUND_NO_ATTEMPTS = 20` 换号重来）、
  `OutboundOrderService.java:64-65,357-365`（同一范式）。三个单据族里**只有加工单还留着旧写法**。

**多实例下会发生什么**
每个实例（以及**每次容器重建**）都从 `[1000, 9999)` 里随机取起点，两段递增区间一旦重叠，重叠区的号会**被两边都用到**；
谁后到谁撞 `uk_processing_orders_no`。撞上时：
① 该次派单**直接失败**（4xx）；② 失败文案说「加工单已生成」—— **而实际上没有生成**（这是最坏的一半：
运营看到这句话以为已派出，不再重试 ⇒ 订单停在「已确认」却永远没有作业单）。
重叠区可能有几十到几百个号，等价于**一段成片的派单失败**。

**最小改造建议**
把 `InboundOrderService` 的 `insertWithFreshNo`（取号 → `ON CONFLICT DO NOTHING` → 0 行就换下一个号，≤20 次）**
原样搬到 `commit()`**，并把涉及号唯一约束的 `DuplicateKeyException` 映射**收窄**（只映射 `uk_processing_orders_active`
那种「真的重复派单」，不要再把号冲突说成「已生成」）。

**验证方式**
真库双连接 + 测试探针钉住同一候选号（`InboundOrderService` 已有同款探针先例）：断言第一方落库成功、
第二方**换号后仍成功**（不是 4xx）；再断言「真·重复派单」那条路径仍然被 `uk_processing_orders_active` 拒绝。

---

# P1 需改造（会降级但不坏数据）

## P1-1 `MigrationRunner` 无分布式锁，多实例同时启动会互撞台账

**现象**：自研迁移器（不是 Flyway），`CommandLineRunner` 在启动时跑；**没有** `pg_advisory_lock`，
「查已执行 → 执行 → 记台账」是三步读改写。
**证据**：`backend/admin-api/src/main/java/com/migao/admin/config/MigrationRunner.java:206`（`run`）、
`:265-293`（`migrate`：`getAppliedMigrations` → 逐条 `jdbc.execute` → `recordMigration`）、
`:899-904`（建 `schema_migrations` 表）、`:921-923`（`INSERT INTO schema_migrations` 裸插）、
`:280-282`（"stale artifact" 判定也基于同一份快照）。
**多实例下**：两实例同时起 ⇒ 都读到「未执行」⇒ 都执行同一份 DDL。幂等 SQL 两边都成功 ⇒ 第二个
`recordMigration` 撞主键 ⇒ 被 `catch (Exception)` 收成 **内容类失败**（`:295-318`）⇒ 记 ERROR + `lastFailedRealCount++`
+ **应用照常启动**（`:230-235`）。后果不是坏数据，而是**归因被污染**：一次正常的并发启动长得像「迁移失败」。
更坏的边角：`getAppliedMigrations` 异常时 `return List.of()`（`MigrationRunner.java:907-913`）⇒ 瞬时报错会让整条链
**被当成全未执行重跑**。
**最小改造**：`migrate()` 外层包一把 `SELECT pg_advisory_lock(hashtextextended('migao:migrate',0))`（仓内已有
`pg_advisory_xact_lock` 先例：`backend/admin-api/src/main/java/com/migao/admin/mapper/WarehouseLocationMapper.java:86`），
拿不到锁就**等**，拿到后**重新读**一次台账；`getAppliedMigrations` 的异常**不要**再降级成「空表」。
**验证**：两 JVM 同时启动，日志里只有一方出现 `🔄 执行迁移`，另一方出现「等待迁移锁后跳过」；
`schema_migrations` 无重复、无 ERROR。

## P1-2 SSE 流式回复**只在流末尾落库**，实例中途被摘 ⇒ 回复静默丢失

**现象**：AI 回复的 `save_message` 在生成器尾部执行；`done` 事件无论保存成败都发。
**证据**：`backend/ai-agent-service/app/api/chat.py:602`（`message_id = await _save_message_or_report(...)`）、
`:657-659`（`_done_sent = True; yield SSEEvent.done(...)`）、`:314-315`（`stream_timeout = 180`、`heartbeat_interval = 15`）。
**多实例下**：单条 SSE 请求本来就绑在一个实例上 ⇒ **不需要 sticky**（这点可以放心）；但滚动部署/伸缩时该实例被
`SIGTERM` ⇒ 用户消息已入库、AI 回复**一个字都没落** ⇒ 历史里只剩用户那句，客服看起来「没回」。
**最小改造**：流结束前把 `full_response` 的**已生成部分**增量落一条（或异常分支落一条 `error` 标记消息），
让「断流」在会话历史里**可归因**；部署侧再配「先摘流量、等在途请求结束」。
**验证**：SSE 进行中 `docker kill` 该实例，刷新历史：能看到一条「（本次回复中断）」而不是空白。

## P1-3 共享 Redis 是**硬依赖**：多机房各自一套 Redis 会同时打断登录、登出、验证码

**现象**：验证码、JWT 黑名单、简报锁、限流、ai-agent 的 OTP 全部落 Redis；`deploy/swas/docker-compose.yml`
里**没有 redis 服务**（连接串在 `.env.*`，本审计未读 ⇒ 「生产 Redis 是容器还是云实例」= **未证实**）。
**证据**：`backend/admin-api/src/main/java/com/migao/admin/service/SmsService.java:54,88-109`（`codeKey` / `limitKey` / 日计数）、
`backend/admin-api/src/main/java/com/migao/admin/security/JwtAuthenticationFilter.java:49,190-202`
（`token:blacklist:` 前缀，Redis 异常时 **fail-closed** 当已吊销）、
`backend/admin-api/src/main/java/com/migao/admin/service/DailyBriefingService.java:86,435-449`（`setIfAbsent` + `afterCompletion` 释放）、
`backend/ai-agent-service/app/tools/order_create.py:1496-1530`（下单短信验证码 `order_create.py::_otp_key(phone, tenant_id)`）。
**多实例下**：只要**共享同一个 Redis**，上面这些**全是集群安全的**（登出即时传播、验证码跨实例可验）。
一旦每机房一套：验证码 A 发 B 验不过（登录失败）、登出只在本机房生效（安全面）、简报锁失效（唯一键兜底不重复）。
**最小改造**：明确「Redis 是全实例单点」，跨机房只允许**一个写主**（读副本不能用于黑名单/验证码）；
把「Redis 不可用」的降级方向逐条登记（`JwtAuthenticationFilter` 已是 fail-closed，`DailyBriefingService` 是 fail-open+唯一键）。
**验证**：在 A 发验证码、B 校验通过；A 登出后 B 立刻 401。

## P1-4 会话工作状态是「读-改-写」合并，同会话并发会丢更新

**现象**：`context_manager.save()` 先 `load` 再 `update` 再 `commit`（JSONB 整存整取）。
**证据**：`backend/ai-agent-service/app/memory/context_manager.py:68-72`（进程内 `_cache`）、`:386-408`（`save`/`load`）、
`:437-439`（`_cache` 上限 100，FIFO 淘汰）；落库侧 `backend/ai-agent-service/app/memory/session_state_store.py:1-12,44-85`（PG `session_states`，**这部分是对的**）。
**多实例下**：跨轮连续性是**保住的**（每轮 `load` 从 PG 恢复）——这点比预期好，不是 P0。
真正的缺口是**同会话并发两轮**（多标签页 / 双击重发 / 前端重试）：两个实例各自 `load→merge→commit`，
后提交者覆盖前者 ⇒ 丢掉一轮的 `entities`（"刚才那个订单"变哑）。
**最小改造**：把合并下推到 SQL —— `UPDATE session_states SET state = state || :patch::jsonb`，让 PG 做原子合并。
**验证**：并发两轮各注入一种实体，最终 `session_states.state` 里**两者都在**。

## P1-5 加工单/出库单的「唯一约束兜底」只在单实例成立（P0-5 的同类残留）

**证据**：`ProcessingOrderService.java:2110`（注释「DB 唯一约束兜底」）、
`OrderSharedParts.java:68,391-398`（订单号 = 日期 + 5 位随机 + 4 位原子序列，**无取号重试**，靠概率避碰）。
**多实例下**：订单号（`ORD`/`JG` 主单）碰撞是**小概率**（1e5 × 1e4 组合），但一旦撞上同样是 4xx；
加工单已在 P0-5 单列。
**最小改造**：把「取号 + 落库」统一收敛到 P0-5 引入的那个 `insertWithFreshNo` 帮助函数，三个单据族共用一份。
**验证**：同 P0-5。

---

# P2 可接受（仅性能 / 运维面）

| 项 | 证据 | 多实例下的实际影响 | 备注 |
|---|---|---|---|
| 五条定时腿**每实例都跑** | `AdminApiApplication.java:17-18`（`@EnableScheduling`）、`BriefingScheduler.java:23`、`AutoBatchDueScanScheduler.java:52`、`AutoCompleteShippedScanScheduler.java:52`、`AgentBatchLeaseRecoveryScheduler.java:54`、`ScheduledTaskScanScheduler.java:43` | 只有 P0-2 那条会重复投递；其余四条靠**原子 UPDATE 裁行**（`AutoCompleteShippedScanService` 类注释 + `AgentBatchLeaseService:106`）或 **Redis 锁 + DB 唯一键**（`DailyBriefingService:399-449`）⇒ 重复扫描只是空转 | 建议给每条腿加「本轮扫描租户数 / 命中行数」读数，便于确认「重复扫描但 0 副作用」 |
| 会话自动关闭/清理**每实例都跑** | `backend/ai-agent-service/app/main.py:38-43,51-113,116`（`_session_auto_close_loop`）、`session_memory.py:1065-1090,1098-1169` | `UPDATE … WHERE status='active' AND last_activity < cutoff` + `DELETE … WHERE status='closed' AND updated_at < cutoff` ⇒ 幂等，重复执行同结果 | 有 600s 启动宽限（`main.py:43`），重启风暴不会误杀 |
| 进程内限流 | `backend/admin-api/src/main/java/com/migao/admin/security/ClientErrorRateLimiter.java:54,65` | 额度 = 实例数 × 上限（注释已登记）；nginx 的 `limit_req_zone`（`deploy/swas/nginx.conf:104-114`）同理，每机一份 | 若要做「真·全局限流」再上 Redis 计数 |
| 进程内熔断 / 供应商健康标志 | `backend/ai-agent-service/app/core/circuit_breaker.py:213`、`app/utils/llm_health.py:98-189` | 各实例独立开合 ⇒ 局部降级不一致，属**预期行为** | 只影响体验一致性 |
| 只读常量级 `lru_cache` | `app/graph/skills/cheatsheet.py:104`（`_ontology`）、`app/agents/capability_boundary.py:295`（工具可达集）、`app/graph/nodes.py:352`（意图表）、`app/tools/registry.py:601-613`（注册表单例） | 缓存对象是**代码里的静态事实**（不读 DB、不随租户变）⇒ 无害 | 与「进程内可变状态」区分清楚：这些**不是**问题 |
| 租户配置 60s TTL 本地缓存 | `backend/ai-agent-service/app/agents/tenant_config.py:23,31,53-64` | 改配置后各实例最多 60s 不一致 | 纯展示/话术面 |
| DB 连接池**线性放大** | `backend/admin-api/src/main/resources/application.yml:52-57`（Hikari `maximum-pool-size: 20`）、`backend/ai-agent-service/app/utils/database.py:26-43`（asyncpg `pool_size=20, max_overflow=10`） | N 个 admin-api = 20N；N 个 ai-agent = 最多 30N ⇒ 4+4 实例即 **200** 连接 | **RDS 的 `max_connections` 本审计未证实**，上集群前必须先核算 |
| 时钟依赖 | `backend/admin-api/src/main/java/com/migao/admin/time/BusinessClock.java:42-45`（`Clock.system(Asia/Shanghai)`）、`ScheduledTaskService.java:193`（`now` 由应用给）、`order_create.py:226`（窗口由 `time.time()` 给） | 各机墙钟漂移 ⇒ 到期判定早/晚、单号日期段跨零点分叉、幂等窗口边界错位 | 要求 NTP 强同步；更稳的做法是到期判定改用 DB `NOW()` |
| 记忆抽取「在途表」 | `backend/ai-agent-service/app/memory/extraction_tasks.py:39`（`_inflight`） | 关闭会话时只能 drain **本实例**的在途任务，别的实例上的抽取不会被等 | 最多丢一次画像抽取，不涉及业务数据 |

---

# 多机房特有（跨机房才会出现、单机房看不到）

### 1. 跨机房写同一套 RDS：延迟会放大**锁持有时间**

- 现状：所有写都在应用侧开事务（例如 `ProcessingOrderService.commit` 里「加工单 + 批次扣减 + 工序实例化」同一事务，
  `ProcessingOrderService.java:1650-1673`），行锁/`uk_processing_orders_active` 等唯一索引竞争随 RTT 变长。
- 跨机房 RTT（10–40ms）下，同一事务的持锁时间近似**按语句数线性放大** ⇒ 同租户并发派单更容易互相等锁，
  表现为「偶发 5s+ 的派单延迟」。
- 若用**跨机房悲观锁**（`pg_advisory_lock`、`FOR UPDATE SKIP LOCKED`）：锁的持有时间包含跨机房往返 ⇒
  这把锁会变成**跨机房串行点**。⇒ 建议：所有「掐点扫描」的写都保持**单条原子语句**（本仓绝大多数已经是），
  **不要**引入跨机房长事务；P0-2 的修法要刻意选「一条 UPDATE…RETURNING」而不是「锁 + 两段写」。

### 2. 跨机房 Redis：只能「单写主」，读副本不能服务安全/验证码

- JWT 黑名单查询（`JwtAuthenticationFilter.java:190-202`）与验证码校验（`order_create.py:1496-1506`）
  **都要求读到最新值**；一旦就近读副本，会出现「刚登出的 token 还能用」「刚发的验证码说错」。
- ⇒ 这两类 key 必须走**写主**；只有 `admin_api_cache`（`app/core/admin_api_cache.py:1-30`，商品搜索/分类树，
  TTL 5/30min）这类**纯缓存**才可以就近读。

### 3. 对象存储「就近」：不要为了低延迟回退本地盘

- `OssService` 是单 region 客户端（`OssConfig.java:57-70` 只吃一个 `endpoint`）⇒ 跨机房的**上传**走公网/内网回源，
  延迟是**一次上传**的量级（可接受）；但**图片读取**会被每个页面放大 ⇒ 建议上 CDN / OSS 传输加速，
  而不是把图片再放回本地盘（那会退回 P0-3）。

### 4. 证书与 DNS 切换：现在这套 certbot 是**单机假设**

- 证书是**每台机器**一份：`deploy/swas/nginx.conf:151-152`（`/etc/letsencrypt/live/migao/*.pem`）。
- 续期用 **webroot HTTP-01**：`deploy/scripts/tls-renew.sh:1-40`（`WEBROOT=${DEPLOY_DIR}/certbot-www`），
  并靠宿主 cron（`/etc/cron.d/migao-tls-renew`，`deploy/swas/deploy.sh:1678-1685`）触发。
  ⇒ 多机时**只有 DNS 指向的那台**能应答 `/.well-known/acme-challenge/`；两台各自续期会**互相抢**同一个域名，
  且 Let's Encrypt 有速率限制。
- ⇒ 最小改造：改 **DNS-01**（或只在一台续期、把证书目录**只读**分发到其它机器），并把「证书到期天数」做成读数。
- DNS 切换：客户端持有的是**长连接**（SSE 最长 180s，`chat.py:314`）⇒ 切 DNS 后旧机房仍会收完在途请求，
  新请求进新机房；不需要 sticky，但**要接受**「切换瞬间两机房同时在服务」。

### 5. nginx 现在是「一台机器 + Docker DNS」，**没有 upstream**

- 证据：`deploy/swas/nginx.conf:172,210,261,482,545`（全部直接 `proxy_pass http://admin-api:8080` /
  `http://ai-agent:8000`，**没有 `upstream {}`、没有 `resolver`**）。
- 这套写法的已知行为在仓内被**明确记录**过：`deploy/swas/deploy.sh:1444-1450`
  ——「`docker compose up -d` 会重建容器（新 IP），而 nginx 在**启动 / reload 时**解析 `proxy_pass` 的 DNS 名
  并**缓存**该 IP ⇒ 重建后不 reload 就 502」。etcd/scale 出多副本时同理：**nginx 只会钉住其中一个 IP**。
- ⇒ 多副本必须改成 `upstream admin_api { server admin-api:8080; }` + `resolver 127.0.0.11 valid=10s;`
  （compose 内置 DNS）或 `proxy_pass http://$backend;`，并在**扩容/缩容事件后 reload**；
  跨机房的正确形态是「每机房一套 nginx + 本机房 upstream，DNS/GSLB 做机房级分流」。
- 健康检查：`deploy/swas/docker-compose.yml:73,111,134,158`（四个容器各自 healthcheck）与
  `deploy.sh` 的 `wait_healthy`/`nginx_expect_upstream_ok` 都是**本机 127.0.0.1 探测** ⇒ 跨机房要做成
  「LB 只摘本机房成员」，不能靠单机脚本。

### 6. 其它单机假设（逐条）

| 假设 | 证据 | 多机房要改成 |
|---|---|---|
| 部署锁是**宿主本地**文件 | `deploy/swas/deploy.sh:39-44`（`LOCK=/tmp/migao-deploy.lock` + `flock`） | 锁只在同一台机器内串行 ⇒ 两台机器可同时部署；要么串行到一台「发布机」，要么换成外部锁 |
| 端口绑 `127.0.0.1` | `deploy/swas/docker-compose.yml:44,101,126`（8080/8000/3001 全绑回环） | 单机是对的（只让 nginx 访问）；跨机则需要**机房间私有网络** + LB，而不是把端口暴露公网 |
| 蓝绿是「同机第二端口」 | `deploy/swas/docker-compose.bluegreen.yml:1-30,45-70`（`green` 绑 `127.0.0.1:18080` 等） | 跨机蓝绿 = 新机房整体起来 + GSLB 切权重；同机第二端口那套只能用于**单机房内**灰度 |
| `.env.*` 与密钥是**每机一份手工文件** | `deploy/swas/docker-compose.yml:27`（`env_file: .env.admin-api`）、`deploy.sh:745,1097-1112`（自愈补齐 `.env.admin-api`）、证书与 JWT 私钥在 `/opt/migao-deploy/jwt`（`:60-62,106-107`） | 必须收敛成**一个受控来源**（密钥管理/配置中心）+ 一致性校验；否则「两台机器两把钥匙」会重现 `#8976`（AI 接口全 401） |
| 静态发布面在**本机磁盘** | `deploy/swas/docker-compose.yml:164-169`（`./h5:/opt/migao-deploy/h5:ro`） | 多机要改成对象存储/CDN 发布，或每台都跑一遍发布腿 |

---

# 建议的上集群顺序（先修这 3 件，再开第 2 个实例）

**第 0 步（必须在动手前）**：核算 RDS `max_connections` 与 PgBouncer 方案。
20（admin-api）+ 30（ai-agent）× 实例数，4+4 就 200 连接。**这是唯一一条「不修代码也会炸」的资源约束**（本审计未证实现值）。

**先修 3 件（缺一不可，顺序即依赖顺序）**

1. **共享有状态面收敛**：**一个**共享 Redis（写主唯一）+ 生产切 `OssService`（图片不再落本地盘）。
   —— 这两件不修，第 2 个实例一上来就是「验证码验不过 / 登出不生效 / 图片 404」三连。
2. **消除「进程内承担正确性」的三处**：
   - 微信 `access_token` → Redis 单令牌（P0-1）
   - 到期待办扫描 → 原子 claim 或 `dedupeKey`（P0-2）
   - 加工单号 → 换成 inbound 那套 `insertWithFreshNo`（P0-5）
3. **幂等键确定性化**（P0-4）：`_window_id` 改成「由会话 + 操作 + 轮次」推导的稳定值，或落 Redis。
   —— 这条决定「滚动部署期间会不会重复下单」，属于资金面，必须在上第 2 个实例**之前**。

**然后按这个顺序扩**

4. 先扩 **ai-agent**（它的状态最轻：会话状态在 PG、OTP 在 Redis、定时腿幂等），观察 24h：
   看 `client_request_keys` 是否出现同内容双行、`orders` 是否出现同手机号同 SKU 的重复单。
5. 再扩 **admin-api**（定时腿与微信 token 修好之后），并**同时**把 nginx 改成 `upstream` + `resolver`。
6. 最后才谈**多机房**：先做「同城双活 + 单写主库」，跨机房写同一 RDS 的延迟问题（见上）留到第 3 期；
   对象存储/CDN、DNS-01 证书、GSLB 分流必须在切机房**之前**就位。

---

# 附：本次审计**未证实**的清单（不猜，留给下一步核实）

| 事项 | 为什么未证实 | 建议的核实方式（零代码改动） |
|---|---|---|
| 生产是否已启用 OSS | `OssService` 需三项凭据齐备才 `@Primary`（`OssService.java:43-46`），值在 `.env.admin-api` | `docker compose exec -T admin-api printenv | grep '^OSS_'`（只看键是否存在，不打印值） |
| 生产 Redis 是容器还是云实例 | `deploy/swas/docker-compose.yml` 里**没有** redis 服务 | `docker compose exec -T admin-api printenv | grep '^REDIS_'`；确认是否跨机共享 |
| RDS `max_connections` / 是否 PgBouncer | 仓内无该读数 | `SELECT setting FROM pg_settings WHERE name='max_connections';` |
| 微信 `access_token` 旧令牌过渡期的**确切秒数** | 属供应商行为，仓内无证据 | 官方文档 + 一次双实例实测（见 P0-1 的验证方式） |
| 生产实例数 / 是否已有第二副本 | 仓外编排面 | `docker compose ps` + 服务器清单 |
| 是否存在仓外定时任务（crontab / 云函数） | 仓内 `deploy/` 只看到 TLS 续期一条 cron（`deploy.sh:1678-1685`） | 服务器 `crontab -l` + `/etc/cron.d/*` |
