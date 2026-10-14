# 2026-10-14 环境重建轮 · 全量回归任务书（BRIEF）

> 本文件是**执行规格的承载体**（铁律 12(d)：规格不得只活在会话上下文里）。
> 执行者 = 三条后台验收子代理 + 主会话（UI 面）。**主会话只做集成与独立复核**（不自我验收，铁律 1）。
> 时间口径：一律 **Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）时间戳时逐处标注换算。

## 0. 本轮是什么

用户口径（2026-10-14）：「清除现有测试租户，对所有功能再做一遍全量回归测试，使用全新租户，
发现问题就立即修复，本次还包含对 UI 界面&交互功能验收，**不包含黄金策的评测**，**不要跑真实 llm**」。

用户补充裁定（同轮问答）：被测面 = **本地三件套 + 云 dev 库**；清除口径 = **删掉 tenants 两行
（25 / 31）并清空其全部子表数据 → 走真实入驻流程新建一个全新租户 → 本轮只测它**。

## 1. 被测环境事实（**先钉事实，再看结论**）

| 项 | 值 | 复核命令 |
|---|---|---|
| **被测租户** | **tenant 32**「米高测试环境」· 企业编码 `shop-ttf1` · 管理员手机 **13800138000** · 短信万能码 **123456** | `select id,name,code from tenants` |
| 建租方式 | 真实入驻接口 `POST /api/auth/register`（HTTP 200，`applicationId=2110346504629841922`，`review_source=ai`，`review_summary` = 「规则层校验通过；大模型审查暂不可用，已按规则降级放行」） | `acceptance/2026-10-14/evidence/register-response.txt` |
| 租户 32 开箱种子 | users=1 · roles=7 · permissions=32 · role_permissions=100 · production_operations=41 · production_route_rules=27 · categories=1 · products=0 · orders=0 | psql 现取 |
| **被测构建点** | 本机主检出 **`90192bcac`**（= `origin/main`，2026-10-14 20:12 +08 现取；本轮读数全部归因到它） | `git rev-parse HEAD origin/main` |
| 本地三件套 | admin-api `http://127.0.0.1:8080`（PID 见 `start-stack.sh status`）· ai-agent `http://127.0.0.1:8001` · admin-web `http://127.0.0.1:3001` | `bash acceptance/2026-10-14/tools/start-stack.sh status` |
| AI 接线 | admin-api 启动时显式给 `AI_AGENT_BASE_URL=http://localhost:8001` + `AI_AGENT_SERVICE_TOKEN`（否则入驻静默 fail-closed） | 上面那份 `register-response.txt` = 反证（200 + approved） |
| **无真实 LLM** | 本机 `backend/ai-agent-service/.env` **无 `PRIMARY_API_KEY`** ⇒ 审查走**规则层**（`review_source=ai` + 「大模型审查暂不可用」）；本轮**不得**派发任何评测 workflow、不得调用真实 LLM 用例 | 上表入驻 summary |
| DB / Redis | 云 dev RDS `ai_customer_service`（参数从 `backend/admin-api/.env` 读）· Redis `r-bp162…`（清点后**只剩 `token:blacklist:*` 1411 键**，无租户态） | `acceptance/2026-10-14/evidence/wipe-tenants.json` |

**环境重建留档**：清除动作 = `acceptance/2026-10-14/tools/wipe-tenants.py --tenant-ids 25,31 --apply`
（拓扑序由 `pg_constraint` 现取，子表优先，单事务）⇒ **79 张表 / 9771 行 + tenants 2 行**，
残留自证：子表残留 **0**、tenants 点名行 **无**。另清掉 `tenant_applications` 6 条（属已删租户的入驻申请残留，
不重新清就无法用同一手机号再次入驻）。读数 = `evidence/wipe-tenants.json`。

## 2. 三条线射程与产物（各自写各自目录，零共享写路径）

| 线 | 目录（产出落这里） | 覆盖对象 |
|---|---|---|
| ① 工人端 / 小程序 / 配置写面 | `acceptance/2026-10-14/line1-worker-config/` | `worker-miniapp-writeface-sweep`（`/api/worker/**` 全写端点 + bmini/mini 写面）· `shipments-sweep` · `batch-writeface-sweep` · `config-writeface-sweep` |
| ② 钱 / 工资 / 库存时效 / 派工 / agent 服务 | `acceptance/2026-10-14/line2-money-production/` | `finance-stock-time-sweep` · `piecework-wage-sweep` · `dispatch-routing-sweep` · `agent-service-sweep`（**ai-agent 服务面，禁真实 LLM**） |
| ③ 售后退款 / 租户隔离 / 并发竞态 | `acceptance/2026-10-14/line3-aftersales-race/` | `acceptance/2026-10-04/aftersales-refund-sweep`（含退款精度/负例/回补开关两侧）· `tenant-isolation-sweep` · `tenant-concurrency-sweep` · `acceptance/2026-10-04/race-sweep` |

**统一启动口径（逐字可复算，从仓库根执行）**：

```bash
cd "/Users/guangzhen.zk/ai native/migao"
REPO_ROOT="$PWD" LIVE_WORKTREE="$PWD" \
API_BASE=http://127.0.0.1:8080 AGENT_BASE=http://127.0.0.1:8001 \
TENANT_ID=32 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
OUT_DIR="$PWD/acceptance/2026-10-14/<线目录>/out/<sweep 名>" \
node acceptance/2026-10-03/<sweep>/harness/run-all.mjs
```

> `API_BASE` 必须指 **本机 8080**（本轮被测面），**不要**打 `api.migaozn.com`（那是已部署面，
> 与 `90192bcac` 不等价 ⇒ 会得到假读数）。

## 3. 纪律（违反任一条 = 该线读数不可引用）

1. **不自我验收**：本线只产**读数 + 判定 + 证据**，**不得**写「验收通过 / 交付完成 / 已达标」。
2. **四态口径**：`pass` / `fail(产品)` / `skip(未覆盖)` / `假红(判据缺陷)`；**skip 永不折算成 pass**。
3. **判定必须引证据**（`out/**` 文件名 + 字段 + 原文片段）；**无引用 = 无判定**。
4. **归因强度必须匹配证据强度**：证据不足就写「证据不足 + 缺什么」，**不许编归因**，也不许一律甩给评测侧。
5. **禁改产品代码**：本线是**验收**，发现缺陷只**登记**（含最小复现 + 根因符号/文件 + 会红判据），修复由主会话统一派包。
6. **禁跑重活**：不得跑 `verify-all.sh gate` / `batch-gate` / 全量 pytest（机器级重活锁，主会话统一跑一次）。
7. **禁真实 LLM / 禁派评测 workflow**（用户 #4262 裁定 + 本轮口径）。
8. **写操作只碰探针对象**（harness 的 `PROBE_PREFIX` / `guardedWrite` 守卫；不得改删非探针行）。
9. **必须清理**：本线自建探针数据在收尾时清理（复用各 sweep 的 `p9-cleanup.mjs` / `residue.mjs`），
   并在报告给**清理前后现取读数**。**不得**把租户 32 清空（它是本轮被测租户，收尾时库里只该剩它）。
10. **已知「非产品」形态要在报告里单独一栏**，不要混进产品缺陷：
    - **构建点自检类**（如 `W0-00b` 依赖 `LIVE_WORKTREE`/`merge-base`）⇒ 环境注入问题，非产品；
    - **期望值过期伪影**（判据写死旧 sha / 旧种子口径，如 2026-10-04 `p0-env.mjs` 的 `EXPECTED='ff655a06c'`）；
    - **夹具漂移**（探针用旧口径造数据，被新校验拒，如「部位矩阵只接受布帘/纱帘/帘头/布料」）。
    这三类**必须给出判别证据**（谁判的、判据文件、为什么是判据侧），**不许**用「大概是环境问题」打发。

## 4. 产出物（每线）

- `out/<sweep 名>/*.json`（harness 原生产物）+ `out/<sweep 名>/run.log`；
- `REPORT.md`：一句话结论 / 四态汇总表 / **真缺陷清单**（每条 = 最小复现 + 会红判据 + 根因符号/文件 + 五层归因）
  / **判据侧问题清单**（假红 / 夹具漂移 / 期望过期，各带判别证据）/ 未覆盖清单（skip 及原因与重启条件）
  / 残留清理读数 / **被测构建点 sha**；
- `out/SUMMARY.json`：机器可读 `{line, buildpoint, counts:{pass,fail,skip,false_red}, findings:[...]}`。

## 5. 明确不做

黄金策（B 端 agent）评测、真实 LLM 调用/评测 workflow、打印/标签硬件通道、微信开发者工具真机模拟器
（未监听 ⇒ 登记 skip）、裁剪机等未落地模块、`verify-all.sh gate`/全量 pytest（主会话统一跑）。
