# #4865 独立复核（正常实例化**永远产不出部位码/短码**）

> 环境：**云 dev RDS 对本机不可达**（实测 `psql … connect_timeout=8` ⇒ `timeout expired`；
> 与 `acceptance/2026-09-20/4789-set-no-allocator/FINDINGS.md` 记录的环境状况一致）
> ⇒ 判据跑在**本机自建等价栈**：一次性 PostgreSQL 16（`initdb` + `pg_ctl`，随机端口）+
> `docs/sql/schema.sql`（bootstrap 终态）+ 本仓 admin-api（`:8081`）+ 同源 nginx 替身（`:8080`）。
> 一次性栈跑完即拆，**未写入任何共享库/生产库**。

## ① 判别性实验（先做，不照抄假设）

真 PG + 真 `MybatisConfiguration` + 真 `ProcessingOrderMapper`：

```
[#4865 判别性实验] selectActiveByOrderId → itemsSnapshot 运行时类型 = java.lang.String
                    ；resultMap 类型处理器 = （无 —— 未绑 resultMap）
[#4865 判别性实验] instantiate 返回 = {qr_token=557c…, operation_count=3}
processing_order_sets = 0 行 / processing_set_part_tokens = 0 行
```

⇒ **假设成立**（根因 = 手写 `@Select` 未绑 MyBatis-Plus 的 autoResultMap ⇒ `JacksonTypeHandler` 不跑）。
与 issue 措辞的**差异（如实登记）**：运行时类型是 **`java.lang.String`（JSON 文本）**，不是 `PGobject`。

框架层核实（MP 3.5.8）：`MybatisMapperAnnotationBuilder.parseResultMap` **只**处理方法上的
`@Arg` / `@Result` / `@TypeDiscriminator`，**不会**自动绑 `@TableName(autoResultMap = true)` 生成的那份
⇒ 「不绑就不走处理器」是框架行为，不是本仓用法问题。

## ② 修好映射后**立刻显形**的第二个缺陷（此前被上游缺陷掩盖）

`ProcessingOrderSetMapper.lockSetsOfOrder` 同时含 `ORDER BY` 与 `FOR UPDATE` ⇒
多租户拦截器把 SQL 交 JSqlParser(4.9) 解析再序列化时**把 `FOR UPDATE` 重排到 `ORDER BY` 之前**。
真栈失败 SQL 原文（`generate` / `instantiate` 500 `INTERNAL_ERROR`）：

```
### SQL: SELECT id, tenant_id, processing_order_id, set_index, set_no, craft_line_id, deleted
         FROM processing_order_sets WHERE tenant_id = ? AND processing_order_id = ?
           AND deleted = 0 AND tenant_id = 1 FOR UPDATE ORDER BY set_index
### Cause: PSQLException: 错误: 语法错误 在 "ORDER" 或附近的
```

**为什么以前没人发现**：快照反序列化坏 ⇒ `ensureSetsFor` 在读快照那一步就 `return Map.of()`
⇒ **根本走不到分配器** ⇒ 第二个缺陷被第一个掩盖。
修法：该语句 WHERE 里已有**显式** `tenant_id = #{tenantId}`（拦截器追加的那份是冗余的）⇒
加 `@InterceptorIgnore(tenantLine = "true")`（与 `ProcessingSetPartTokenMapper.selectByShortCode` 同款处置；
**不削弱租户隔离**）。全仓 `FOR UPDATE` **仅此一处**（已扫）。

## ③ 验收剧本重放（U1 / U2 / U6）—— 全绿，原文见 `replay-output.txt`

```
generate 响应：{"success":true,"data":[{"orderRef":"acc-fix4865-order","success":true,"processingOrderNo":"JG-20260920-9205"}]}
instantiate 响应：{"success":true,"data":{"qr_token":"b950d567…(masked)","operation_count":19}}
 token_rows | with_short_code
------------+-----------------
          3 |               3
✅ U1 绿：真 short_code = SEGP72RT（对应 token = e25adfaa…(masked)）

HTTP/1.1 302 Found
Location: /w/?t=e25adfaa…(masked)&tenant_id=1
✅ U2 绿：302 + Location 形态 = /w/?t=<token>（相对路径，同源落地）

落地 status = 200
落地 body sha256      = f19e5bd1d8b4d970ac291ffbc9bcdfd56fa2bacd29f80c188115dcd9d9a51d03
origin/main 同名文件  = f19e5bd1d8b4d970ac291ffbc9bcdfd56fa2bacd29f80c188115dcd9d9a51d03
✅ U6 绿：落地页 == origin/main 的 frontend/worker-h5/index.html（逐字节）

短码 = SEGP72RT；长度 = 8；非法字符 = （无）
✅ 长度 8 + 字符集 = Crockford Base32 去 I/L/O/U
```

> **脱敏说明（两处，均不影响判据）**：① `qr_token` / `Location` 的 `t=` 是**凭据等价物**
> （持码即可报工）⇒ 日志只留前 8 位（`mask_secrets` 在 `run.sh` 里做）。这不是为了过门禁：
> CI 的 `Secret Scan (gitleaks)` 实测把 32 位 token 判成密钥（`generic-api-key`，
> 命中 `replay-output.txt` 第 19 行）⇒ 修法是**别把它提交进仓库**，不是加豁免。
> ② 日志里的裸 `文件:行号` token 按仓内 Case Trust 规则 G 抹去（行号只是栈帧/psql 噪音）。
> 异常类型、SQL 原文、状态码、短码、body 哈希**一字未动**；完整原文可用 `./run.sh` 复跑复现。

## ④ 留下的东西 / 未验证项（如实登记）

- **留下的东西**：无。一次性 PG 集群、admin-api 进程、静态替身、算料桩全部随 `run.sh` 退出拆掉
  （脚本尾部打印残留复查：PG 已停 / 端口 8080+8081+算料桩端口已释放 / `acc-fix4865-*` 实体随临时集群消失）。
  一次性库在 `/tmp`，从未写入共享库或生产库。
- **未验证**：① `generate` 的算料上游（真 ai-agent-service）在本机以桩顶替 —— 桩**直接加载本仓**
  `backend/ai-agent-service/app/production/routing.py::qty_and_source`（非第二份算料逻辑），
  但「走真 ai-agent 进程」这一环**未验证**；② 工人端 `/api/worker/**` 未验证（受 #4864 阻断，非本单）；
  ③ 线上 nginx 对 `/w/` 的服务（`deploy/scripts/worker-h5-verify-served.sh`）未在真实域名上跑。
- **鉴权口径**：登录走**真实端点** `POST /api/auth/sms/login`（本机实例启用仓内 POC 万能码
  `SMS_BYPASS_CODE`）；JWT 用**仓内测试密钥** `backend/admin-api/src/test/resources/rsa/*` 签。
  **未手搓 token、未读取任何环境的生产密钥**。
