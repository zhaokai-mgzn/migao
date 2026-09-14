# C 端（小布）评测体系

> 对齐 B 端（米宝）评测方法论的 C 端落地说明。**改动 C 端评测工具或用例前必读。**
> 单一事实源：`.github/cases/`（用例库）、`tests/agent_eval/local_runner.py`（runner）。
> 相关：`migao-dev-flow` §13/§14（行为体检与用例演进）、`acceptance-protocol`（验收协议）。

## 1. 为什么单独有一页

C 端小布与 B 端米宝是**两个 Agent、两套工具集**，但共用一套用例库与 runner（靠
`persona` 字段分流）。2026-09-11 查证发现 C 端评测长期处于「看起来有覆盖」状态
（issue #3266），本页固化正确的评测口径，防止再次退化。

## 2. 四层评测架构与外部依赖

| 层次 | 载体 | 依赖微信开发者工具 | 进 CI |
|---|---|---|---|
| ① 行为评测（**主力**） | `tests/agent_eval/local_runner.py` + `PERSONA=xiaobu` | ❌ 不需要（纯 HTTP/SSE） | ✅ `xiaobu-acceptance.yml` |
| ② H5 视觉回归 | `tests/playwright.xiaobu.config.ts` | ❌ 不需要（静态托管 Taro H5 产物 + 本地 Chrome） | ✅ `mini-app.yml::xiaobu-h5-visual` |
| ③ 组件单测 | `frontend/mini-app/tests/*.tsx` | ❌ 不需要（jest + jsdom，Taro 全 mock） | ✅ `mini-app.yml::typecheck-and-test` |
| ④ 真机小程序 E2E | `frontend/mini-app/e2e/run.js` | ✅ **唯一依赖** | ❌ 未接入 |

**④ 不作为评测骨架**：`miniprogram-automator` 需本机已登录的微信开发者工具
（`CLI_PATH` 硬编码 `/Applications/wechatwebdevtools.app/...`，还需在设置里开服务端口），
违背「零人工执行步骤」。定位为**可选补充证据层**，主力压在 ①②③。

## 3. ①行为评测的运行前提（关键约束）

`PERSONA=xiaobu` 的身份注入走 `X-Debug-Role: customer` 头，而该降级路径
**仅 `DEBUG=true` 时生效**（`app/utils/auth.py` fail-closed 加固）：

- ✅ **本地 DEBUG 栈**：`DEBUG=true` + 无 token + `X-Debug-Role: customer`
  → `UserIdentity(user_id="debug_customer_1", tenant_id=1, role=CUSTOMER)` → 路由小布
- ✅ **CI xiaobu-acceptance**：docker compose 起 DEBUG 栈
- ❌ **生产 `ai-api.migaozn.com`**：`DEBUG=false` → 该头被忽略 → 请求兜底路由到**米宝**，
  但 runner 仍按 xiaobu 语义打分（`order_query`→`customer_order_query` 映射照旧生效）
  → **结论不可信**。生产 C 端身份需微信 `wx.login()` 的 code 换 token
  （`POST /api/auth/mini/login`），评测无法直接复现。

> **铁律**：跑 C 端评测前先确认目标是 DEBUG 栈。打生产 URL 跑 `PERSONA=xiaobu`
> 得到的是米宝的结果，不要当成 C 端结论。

本地起 DEBUG 栈（无 docker 时）的最小做法：

```bash
cd backend/ai-agent-service
cp <主仓库>/.env .env                      # 含 DEBUG=true / PRIMARY_API_KEY / SERVICE_TOKEN
# ADMIN_API_BASE_URL 指向可用的 admin-api（云 dev 或本地 8080）
sed -i '' 's|^ADMIN_API_BASE_URL=.*|ADMIN_API_BASE_URL=https://api.migaozn.com|' .env
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

云端 RDS 需把当前公网 IP 加入白名单（`aliyun rds ModifySecurityIps`，
**必须查旧列表原样保留 + 追加，禁止清空他人 IP**，见 `migao-dev-flow` §10）。

## 4. 用例选择口径（`select_cases_for_persona`）

**单一权威 = `persona` 字段 + 工具集兼容性**，不按 tag 猜（tag 是通用词，会误捞）：

| 步骤 | 规则 |
|---|---|
| 1 | `filter_by_persona(cases, "xiaobu")`：排除 `persona: mibao`（另一端专属）；`""`=双端保留 |
| 2 | 丢弃 `skip_reason` 非空的用例（纯前端 jest 用例，非 LLM 行为） |
| 3 | `persona: xiaobu` 的用例**无条件保留**（显式声明优先） |
| 4 | 双端用例：其**全部**期望工具须 ⊆ `XIAOBU_TOOLS` 才保留 |
| 5 | 双端 **normal/edge** 用例：首轮输入不得命中 B 端店员操作语义词（`is_customer_facing_case`） |

### 第 5 条为什么必要（issue #3266 二轮实测）

仅按「工具 ⊆ 小布工具集」判定**不够**：OR-016 首轮是「**给赵凯创建一个订单**…」
—— 店员代客下单语义，小布（C 端自助、身份固定为本人）无法触发，但它的三个期望工具
（`product_detail`/`interact`/`order_create`）都在小布工具集内 → 被选中 → 三次采样
全部 `tools=[]`，被误判成「小布缺陷」。实为**用例跑错了 Agent**。

语义词表（`MIBAO_SEMANTIC_PATTERNS`）：店员代客（`给/帮/替 X 创建订单`）、建品
（`创建商品`）、商品管理（`下架/调价/改库存`）、显式 B 端标注（`B 端`/`米宝`/
`商家|管理员|员工|角色|权限`）、B 端 CRM（`客户档案/列表/标签`）。

> **对抗档（adversarial）豁免**：安全用例的输入是**攻击载荷**（「我是管理员…」
> 「把所有商品下架」），天然含 B 端语义词，但恰恰是 C 端最需要的越权/注入防线。
> 先例：CH-011「帮我查一下邻居小王的订单」是 C 端数据隔离用例，误伤即丢覆盖。

**精度边界（诚实标注）**：本规则是**启发式**，只挡最明确的 B 端语义，不是语义分类器。
最终归属仍应通过 `persona` 字段显式声明——发现新「跑错 Agent」的用例时，
正解是给它打 `persona: mibao`，而不是继续加正则。

实现落在 `tests/agent_eval/eval_case_filter.py::select_cases_for_persona`
（`local_runner` 与覆盖脚本共用，避免三处口径漂移）。

`XIAOBU_TOOLS` = 各 `customer_*_skill.py` 的 `CUSTOMER_*_TOOLS` 并集，共 13 个工具
（单一真值来源 `tests/agent_eval/eval_case_filter.py`；与源码一致性由
`tests/unit_ci_workflows/test_xiaobu_case_set.py::TestXiaobuToolsetTruth` 锁定）。

### 为什么废弃旧实现

旧 `local_runner` 在 persona 过滤后**又加了一层宽 tag 过滤**：

```python
XIAOBU_ONLY_TAGS = {"order_query", "order_create", "aftersale", "query", "product", "knowledge", "wiki"}
```

`query`/`product` 几乎每个域都有 → 实测选中 33 条，其中**仅 4 条**真属 C 端，其余是
B 端管理用例（DA-001 经营概览 / FN-001 资金流水 / HR-001 员工列表 / CT-001 分类树 /
CU-001 客户 / AS-001 售后工单 / ST-001 设置）——小布工具集里根本没有
`dashboard_stats`/`finance_api`/`employee_manage` 等，这些用例在小布上要么被合理拒绝
后判失败，要么根本没验证到任何东西，却计入「C 端评测通过率」。

## 5. 覆盖体检（`scripts/xiaobu_coverage.py` / `scripts/mibao_coverage.py`）

回答「哪个能力没被测」——`mibao-verification-cases.md` 只是用例**清单**生成物，
不回答这个问题。**B/C 两端对称**（issue #3555 补上 B 端；判据同一份实现
`scripts/case_coverage.py`，不复制平行实现）。

```bash
# 人读报告（矩阵 = 补用例任务书）
python3 scripts/xiaobu_coverage.py            # C 端小布
python3 scripts/mibao_coverage.py             # B 端米宝
# 门禁（结构性缺失 → exit 1）；已接入 verify-all.sh gate/quick/full 与 CI Case Coverage Gate
python3 scripts/xiaobu_coverage.py --check
python3 scripts/mibao_coverage.py  --check
# Markdown（供文档引用）
python3 scripts/xiaobu_coverage.py --md && python3 scripts/mibao_coverage.py --md
```

输出：① 工具覆盖矩阵（缺口标 ⚠️，含正向用例数）② 用例归属（按 tier）
③ 孤儿用例（期望工具该端没有 = 端点挂错，门禁拦截）④ **薄覆盖清单**
（缺正向用例 ❌ 阻塞 / 仅 1 条用例 ⚠️ 只报告）。
另有**显式豁免**区：有用例但声明了 `skip_reason` 的工具（如 C 端 `customer_address_query`
由 CH-025 覆盖但 skip，改由 pytest 验证）——豁免必须显式声明理由，不得靠「看起来有覆盖」。

### 判据（issue #3555 收紧）

| 判定 | 含义 | 门禁 |
|---|---|---|
| 工具 0 用例 | 能力完全没被测 | ❌ 阻塞 |
| 工具**只有拒绝/不调用式断言**（无正向用例） | 只证明越权防线，没证明能力可用 | ❌ 阻塞 |
| 用例期望工具该端没有（挂错端） | 该端每轮必挂的固定噪音 | ❌ 阻塞 |
| 断言了两端注册表都没有的工具 | 拼错/已删除 → 期望永不满足 | ❌ 阻塞 |
| 工具仅 1 条用例 | **厚度不足**（随迭代收敛的活指标） | ⚠️ 只报告，不阻塞 |

「正向用例」= 正常诉求下断言真实工具被调用（`eval_case_filter.is_positive_case`）；
判据只认**断言文本**（否定式期望排除），**不认 `tier` 标签** —— 实测 OR-007「取消订单」
/ CU-005「帮我发货」挂着 `tier: adversarial` 却是正常能力，按标签判会造假红。

> 脚本零第三方依赖（纯逻辑在 `tests/agent_eval/eval_case_filter.py`），
> `python3` 直接可跑。**为什么拆模块**：`local_runner` 有模块级 `import httpx`，
> 而 CI 的 `ci workflow helper unit tests` job 只装 `pytest pyyaml` →
> 测试一 import runner 就 ImportError（本地必装 httpx 故全绿，CI 红）。
> 拆出零依赖纯函数后，runner / 契约测试 / 覆盖体检三处共用同一实现且都能跑。

## 6. 当前基线（2026-09-11，issue #3266）

本地 DEBUG 栈实测（`deepseek-v4-pro`）：

| tier | 用例 | 覆盖能力 | 实测 |
|---|---|---|---|
| smoke | AS-008 | 售后进度查询（本人工单隔离） | ✅ 100% |
| smoke | KN-001 | 本店知识库检索 | ✅ 100% |
| smoke | OR-012 | 物流查询（仅本人已发货） | ✅ 100% |
| smoke | PR-001 | 商品搜索 | ✅ 100% |
| smoke | PR-003 | 商品详情（ID 解析） | ✅ 100%（偶发噪声重试放行） |

工具覆盖 **12/13**（唯一未覆盖 `customer_address_query` 已显式豁免）。

### 已实测发现的 C 端行为问题（待收敛）

| 用例 | 现象 | 性质 |
|---|---|---|
| OR-016 | 下单 confirm 前**未主动询问加工项**（商品绑定加工项时）；`interact[choice:processing_items] before interact[confirm]` 时序断言全程未命中 | 复现型（两次不同指纹，待多次采样定性） |
| OR-009 | 下单全流程 6 轮跑偏：首轮 `human_handoff`，无 `order_create`，末轮工具调用超时 180s | 待定性（含 infra 超时因素） |

> 这两条是「提高 C 端能力上下限」的直接输入，需按 `migao-dev-flow` §13.3 收敛为
> 可执行断言（`order_before` 时序 / `required_args` 参数完整性）并做 case 有效性验证。

## 5.1 业务数据 fixture（C 端验收栈必需）

B 端评测跑**生产**（有真实数据），C 端跑**全新 bootstrap 空库** —— 这是两者最大的环境差异。
空库下 agent 搜不到商品 → 反复重试 `product_search` → 从不进入 `product_detail`，
依赖数据的用例必然失败（实测 CI：PR-003 `tools=[product_search ×3]` 而期望 `product_detail`）。
**行为本身合理，缺的是数据。**

`tests/agent_eval/fixtures/xiaobu_eval_seed.sql` 提供最小业务数据：

| 实体 | 内容 | 服务的用例 |
|---|---|---|
| `categories` | 窗帘布艺 | 商品分类 |
| `processing_categories` / `processing_items` | 纳米圈打孔 ¥8/米、韩式波浪折边 ¥12/米、高温定型 ¥10/米 | 下单加工项环节 |
| `products` | **遮光窗帘**（on_sale/per_meter/has_processing）、北欧风窗帘 | PR-001 / PR-003 |
| `product_colors` / `product_skus` | 米白/浅灰/雾霾蓝 × 散剪 2.8m | 选品规格收集（colorId 等） |
| `product_processing_items` | 商品↔加工项关联（4 条） | OR-016 / OR-017 |
| `users` | `debug_customer_1`（与 `auth.py` DEBUG customer 身份同 id） | C 端身份一致性 |
| `orders` / `order_items` | **EVAL-ORD-0002 已发货**（最新）+ EVAL-ORD-0001 已完成，均带收货人/电话/地址 | CH-010 / CH-012 / OR-009 / OR-014 / OR-017 |
| `order_logistics` | 顺丰在途轨迹 | OR-012 物流查询 |

**为什么顾客本人 + 历史订单是必需项（不是"补点数据"）** —— 这三个缺口都会让 agent
的**正确行为**也拿 0 分：

1. `customer_address_query` 取"最近一笔有地址的订单"，空库永远未命中 → 下单表单无法
   预填 → agent 只能反复追问（实测 CH-010/OR-009/OR-011/OR-014 出现
   `customer_address_query` ×3~4 次空转），**看着像模型循环，实为环境缺数据**；
2. `aftersale_create` 的订单归属校验（#518）先拉 `GET /api/admin/agent/orders/mine`
   再匹配 `order_id` → 空库必不匹配 → 一律返回「该订单不属于您」→
   **售后建单在该库里根本不可能成功**（CH-012 实测 4 轮 0 建单）；
3. `customer_order_query` 列表为空 → 顾客说"第一笔订单/最近那笔"无从指代。

> 归因纪律：这三条属于**数据层（环境）缺陷**，不是「模型层能力缺陷」。
> 修测量环境 ≠ 修模型 —— 不先把环境补齐，得到的「能力分」是假的（详见 §6.2）。

**幂等**：全部 `ON CONFLICT DO NOTHING` / `WHERE NOT EXISTS`，每次起栈可安全重放。
fixture 末尾带 `DO $$ ... RAISE EXCEPTION $$` 自检：`debug_customer_1` 订单数 < 2 直接
报错，避免"注入了但没生效"静默通过。
**不并入** `docs/sql/schema.sql` —— 生产 bootstrap 不应含演示数据。
**注入时机**：workflow 在起栈之后、评测之前注入（见 `xiaobu-acceptance.yml` 的
「Seed C 端评测业务数据」步骤）。

> ⚠️ `orders.created_at` **必须显式给值且两笔不同**：`customer_order_query` 按
> `ORDER BY created_at DESC` 排序，同刻（`NOW()` 默认值）会让"最近那笔"随机命中 →
> 用例抖动。当前设定：0002 已发货（最新）> 0001 已完成。

本地手动注入（对着本地 docker 栈）：

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U app_user -d ai_customer_service \
  < tests/agent_eval/fixtures/xiaobu_eval_seed.sql
```

> 注意：商品 `status` 必须是 **`on_sale`** —— admin-api 未显式指定 status 时
> 只返回 on_sale 商品（`ProductService.java:144`），用 `active` 会搜不到。

## 6.1 已知基础设施破损（另行跟进 issue #3270）

C 端评测链路有三处破损，与用例库正确性无关，但会让「评测通过」结论失去意义：

| 破损 | 事实 | 影响 |
|---|---|---|
| `xiaobu-acceptance.yml` **从未绿过** | 9/9 run 全 failure；postgres 容器 exit 3 → ai-agent 未起 → `ConnectError` | C 端评测**零信号** |
| 该 workflow 的失败处理自崩 | 用 `github.rest.search.issues`（正确为 `search.issuesAndPullRequests`） | **issue 从未创建**，无人知晓在失败 |
| `LLM_BREAKER` 全局单一熔断器 | `base_skill.py:47` 一个 `llm_minimax` 名护所有 skill；单 skill 3×60s 超时 → 全部 skill OPEN | 用户看到「抱歉，AI 服务暂时不可用」；C 端查订单/下单/问答全挂 |

另：C 端 smoke 未进 PR 门禁（`pr-check` 的 `agent-eval-smoke` 不设 `PERSONA`）。

## 6.2 失败归因：逐轮轨迹（`round_trace`）

扁平 `tool_calls` 只说明「整场用过哪些工具」，**无法回答哪一轮走了哪个 Skill**——
于是「**路由层**：被路由到错误的 Skill」与「**工具层**：Skill 没绑定这个工具」
在报告里完全同形，而两者的修复方向相反（改路由 vs 加工具）。

轨迹每轮带 `ai=`（助手回复片段，手机号掩码）—— **必须打**：只说模型"调了什么"、不说它"说了什么"时，
「顾客答完卡、模型空转」（`tools=-`）与「模型在问别的、脚本没答它」在日志里同形，归因只能靠猜
（CH-010 首跑失败 run 34788143133 即此形，最后只能记 `llm-noise` 重试放行）。

实测 CH-012 报告：`rounds=4 tools=['customer_order_query','human_handoff','aftersale_query']`。
- 若 R1 落在 `customer_order`（该 Skill **无** `aftersale_create`）→ 路由缺陷；
- 若 R1 落在 `customer_aftersales`（当时**无** `interact`，confirm 门禁不可达）→ 工具缺陷。

### 按用例切分路由日志

CI 另有一段「Dump C 端逐轮路由轨迹」步骤，把 ai-agent 的
`intent_router` / `route_by_intent` 日志（带时间戳）打到构建日志里 ——
它回答 `round_trace` 回答不了的「**为什么**走这个 Skill」（意图分类结果）。

runner 为每个用例打印 UTC 起始锚点，据此把路由日志按用例切开：

```
  ⏱ CH-012 start=2026-09-11T15:16:02+00:00
  ...
23:16:02 C: intent=after_sales        → R: Routing to 'after_sales'
23:16:10 C: intent=order_query        → R: Routing to 'order_query'
```

**没有这个锚点就无法归属**：实测 CH-013 与 CH-014 的轮次在日志里交错，
仅凭时间顺序分不清哪一行属于谁（踩过）。

`local_runner.py` 现为每条失败用例打印逐轮轨迹：

```
trace: [R1 tools=customer_order_query data=customer_order_query(items=2 total=2)] [R2 tools=aftersale_create failed=aftersale_create!confirmation_required cards=confirm] [R3 tools=- ERR]
```

字段：每轮 `round / tools / results / cards / interactive / text(截断 60 字) / error`，
同时进入返回体与 CI 产物（可直接 JSON 序列化），也可用 `round_trace` 写更强的断言。

**「调了」≠「成了」**：`tools` 记的是 LLM **发起**的调用。写工具被 confirm 门禁拦截时
返回 `{"success": false, "error": "confirmation_required"}`，**调用名照样出现在 tools 里**
—— 报告读起来像「写操作正常执行」，实际一次都没落库（CH-012 的 `aftersale_create`
就是这种形态）。故每轮另记 `results: {tool, ok, error, digest}`，格式化时以
`failed=<tool>!<error>` 显性标出；缺 `success` 字段一律按**未成功**记。

**「成了」也分两种**：`data=<tool>(...)` 是结果的极简载荷摘要（列表给长度、标量给值）。
它回答「工具成功了，但它返回了什么」，用于区分两类**处置完全不同**的"卡住"：

| 形态 | 含义 | 处置 |
|---|---|---|
| `data=customer_order_query(items=0)` / `has_address=False` | 工具通了但**没数据** | 改 fixture（数据层） |
| `data=customer_order_query(items=2)` 但流程不推进 | 有数据但 **LLM 不往下走** | 改 prompt / 加代码兜底（引导层·模型层） |

摘要**无条件打印**（不能只在失败时附带）：CH-012 那种"工具全成功、流程不走"的形态
没有任何 `failed` 标记，若只在失败时打印，最能说明问题的那一轮反而没有证据
（实测踩到）。单轮最多展示 3 条摘要，整条摘要 ≤160 字符，超出时逐条丢弃字段
并保留 `(+N more)` 省略提示。

**用工具反推 Skill**：Skill 的工具集互不重叠，逐轮工具名即可反推该轮 Skill
（如 `customer_order_query` 只出现在 `customer_order`）。**映射以
`backend/ai-agent-service/app/graph/skills/*.py` 为单一事实源——本文档刻意不复制
这张表**，避免文档副本与代码漂移（历史上 `schema_full.sql` 就是被复制后漂移的）。

配合 `migao-acceptance` 的五层归因（数据 / 断言 / 引导 / 工具 / 模型）使用：
先看 `round_trace` 定位**哪一层**，再决定改 case、改工具、改 prompt 还是改路由。

### 6.4 合作型用户轮：`auto_respond`

静态脚本写死了"用户按某种顺序说什么"，而 agent 的**提问顺序与卡片类型随模型而变** ——
对不上就卡死。实测（run 34627856207，OR-014）：第 2 轮 agent 先发「收货信息 & 颜色」
表单、第 3 轮才发加工项 choice 卡，而脚本第 2 轮说的是「选有打孔的那件」→ 第 4–8 轮
每轮只重复 `customer_address_query`，**`order_create` 永不发生**（看着像模型不会下单）。

真实顾客不会照着脚本说话，而是**有什么卡就答什么卡**。`user_inputs` 支持这种轮次：

```yaml
user_inputs:
  - "帮我下单，遮光窗帘 3 米，要打孔加工"
  - auto_respond:
      fallback: "选有打孔的那件"          # 上一轮无卡片时发这句
  - auto_respond:
      fallback: "确认下单"
      form_values:                        # 表单卡按此回填（只填卡片自己声明的 key）
        customer_name: "张三"
        customer_phone: "13800138000"
        color: "米白"
  - auto_respond:
      fallback: "123456"                  # C 端下单的验证码轮
```

优先级（按"最能推进流程"排序）：**confirm → choice → form → fallback**
（confirm 回 `confirmValue`；choice 回第一个选项的 value；form 拼 `__FORM__|{json}` 走表单协议）。
case 级 `auto_fill` 轮声明的值会被所有 `auto_respond` 轮复用，避免同一份信息重复声明。

**边界**：`auto_respond` 只解决"卡片驱动的子流程顺序不定"，不替代必要的静态输入
（选品、数量、验证码这些**用户主动提供**的信息仍要写明）。
⚠️ 写用例请优先用 §6.4.1 的 `repeat_until`：固定轮次表对不上实际卡片序列时，
验证码会落到别的卡上 → 整场空转（issue #3430 实证）。

> **`auto_select` 轮必须"答任何待答卡"（OR-018 首跑实证）**：`{"auto_select": true}` 的本意是
> "点 choice 卡首项"，但待答是 **confirm/form** 卡时旧实现会发字面量「第一个」——agent 只能反问
> 「您说的『第一个』指的是哪一项」→ 流程变噪、**顾客还没给码时模型自造验证码** → 首跑失败。
> 现在：choice → 首项 label（前端协议）；confirm/form → 按卡作答；**完全没卡** → 保持「第一个」
> （那是答 agent 的**文本**提问，如重名澄清场景）。

> **加工项「已答不再问」（C-A1 重放 9 实证）**：顾客**已经答过**加工项（文本里点名加工项，
> 或更早一轮拒绝过）时，代码兜底**不得**再把 confirm 卡改写成加工项 choice 卡 ——
> 实测 C-A1：R2 小布在文本里问「需要一起加工吗？」→ R3 顾客答「纳米圈打孔」→
> R5 兜底又问一遍，顾客不得不再答一次才轮到确认下单（UA 判定"有条件通过"那条）。
> 账上为什么没痕迹：`PROC_ITEMS_ASKED_KEY` 只在**发卡**时记账，文本问答不在账上。
> 判据只看**最近一次 `product_detail` 之后**的用户消息（R1 就说「要打孔加工」属需求前置，
> 那时还没看过可选项与单价 → 仍要摆出来，OR-017 依赖这条）。

> **诊断噪声纪律（issue #3421 复盘）**：`prefer_text` 轮遇到待答卡片时会提示"忽略了卡片"，
> 但那是**作者显式声明**的正常形态（验证码轮 / 顾客主动打岔）——全量档每跑会打 7 条，
> 全是噪声。故该提示改为**只在用例失败时打印**（失败时它是第一归因线索："harness 是不是
> 把该答的卡吃了"），绿跑不再刷屏。

### 6.4.1 写用例的"统一一轮"：`repeat_until`（**优先用它**，issue #3430）

`auto_respond` 解决了"卡片顺序不定"，但仍要求作者**逐轮写死数量与位置**。实测证明这不够：
写用例的轮次表按某一种卡片序列写，实际序列一变就错位 —— `prefer_text` 的验证码轮落到
「加工项多选卡」上，顾客答非所问，卡没人答、流程不前进，**轮数耗尽时确认卡刚发出来就没人答它**
（OR-021 定向复跑 **0/1**；CH-025 首跑同形；两者 `handoff=0`，是纯空转不是转人工）。

验收剧本早就用 `repeat_until + click:auto` 解决过同一问题。评测侧同款语义：

```yaml
user_inputs:
  - "我想买遮光窗帘，米白 3 米，要纳米圈打孔加工"
  - "收货地址帮我改成浙江省杭州市西湖区文三路2号5幢202室"
  # 协作型顾客的"统一一轮"：有卡答卡 → 被问验证码就供码 → 否则说 fallback，
  # 直到 `order_create` **成功**（被门禁挡回不算成功 → 不会提前停）
  - repeat_until:
      tool_called: order_create
      max: 4
    code: "123456"                       # 被问验证码时发这句（dev/CI 栈 SMS_BYPASS_CODE）
    fallback: "确认下单"
    form_values:                         # 表单卡按此回填
      customer_name: "张三"
      customer_phone: "13800138000"
      customer_address: "浙江省杭州市西湖区文三路2号5幢202室"
```

规则（`resolve_repeat_turn`）：

| 上一轮状态 | 这一轮发什么 |
|---|---|
| 有待答卡片 | **答卡**（confirm→`confirmValue`；choice→首项；form→`__FORM__|json`） |
| 无卡，且 agent 在**索要验证码** | `code`（默认 `123456`） |
| 其它 | `fallback` |

契约（`TestRepeatUntilCases` 守卫，违反即红）：`tool_called` 必填、`max ∈ [1,6]`、
必须写 `fallback`、断言验证码写工具的用例**必须**写 `code`、不得与 `auto_respond` 混用同一轮。

**为什么 max 上限是 6**：重复轮是"顾客继续配合"，不是无限重试 —— 上限过大只会把模型空转的
时间烧进评测墙钟（而墙钟由最慢单条决定，见 `eval-pipeline-performance.md` §2.6）。

> 迁移建议：新写用例直接用 `repeat_until`；存量用例按 #3430 逐个迁移（OR-021 / CH-025 已迁）。

### 6.5 Eval 产物 DB 审计（§2.2 自动化）

评测步骤之后有一个 `if: always()` 的审计步骤，把 agent 在 DB 里**实际创建**的
会话/订单/售后工单/长期记忆 dump 出来，并对账：

```
── Eval 期间 agent 实际落库的产物（§2.2 审计）──
· 会话数（每用例一个）: 8
· 订单（含 fixture 2 笔）: …
· 售后工单: …
· 落库对账: orders=5 tickets=8
```

**为什么必须有**：`round_trace` 证明「工具被调用了」，但不证明「数据真的落库了」。
2026-09-12 实测两次假绿：

| 现象 | 真因 |
|---|---|
| 17/17 全绿、orders 恒为 2（仅 fixture） | 确认卡长 confirmValue 过不了 `_is_explicit_confirmation` 的 **24 字上限** → 写操作被门禁永久拦截（**mini-app 点确认卡下单同样被拦**，生产路径 bug） |
| CH-012 判 100% 但无 refund 工单 | fixture 订单主键**非 UUID** → admin-api 的 `^[0-9a-fA-F-]{20,}$` 二分启发式把它当订单号查 → 404「无法找到订单」 |

即：**「通过」必须与「落库」对得上**才算闭环。审计里的假绿告警（`orders ≤ 2` 时
打 `⚠️ 假绿风险`）把这类问题变成自动可见，不再依赖人逐行看日志。

配套：`AGENT_EVAL_TRACE_ALL=1` 让**通过**用例的写工具结果也打印出来
（默认只打失败用例，写工具的成败藏在通过的用例里看不见）。

### 6.3 工具健康度门槛（基础设施层优先）

跑完会打印一行工具健康度，失败率超阈值时打大横幅：

```
🔧 工具健康度: 工具调用 46 次，失败 12 次（26%）
    · customer_order_query!服务暂时不可用 × 9
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
⚠️  工具失败率 26% ≥ 阈值 20% —— **本轮结果不可用于能力判断**
    这是**基础设施层**问题（后端 5xx / 熔断 / schema 缺列），不是 agent 能力。
```

**为什么必须有（实测代价极大）**：C 端验收栈的 bootstrap schema 缺列
（`orders.actual_amount` / `product_skus.color_name` …）→ admin-api 500 →
工具返回 `服务暂时不可用`（`CIRCUIT_OPEN`）→ **熔断器打开** → 后续同类工具全失败。
报告长成「agent 不会下单/不会建售后单」，据此去改 prompt / 改工具 / 加引导 ——
**在错误的层上忙了整整一轮**，直到加了 `data=` 载荷摘要才看见真因。

结论：五层归因里**基础设施层必须排在最前** —— 工具本身在报错时，数据/断言/引导/模型
四层的结论一个都不成立。失败率超阈值时，正确动作是**修环境**，不是调 agent。

> 阈值 20%：正常波动（偶发超时/LLM 抖动）远低于此；真正的基础设施故障会瞬间打到
> 50%+（实测 26%~67%）。边界值恰好等于阈值即判可疑 —— 宁可显性可疑，不可静默当能力分。

### 6.6 逐轮卡片事件的**同轮重复**判定（issue #3445）

轨迹里的 `cards=` 是**逐轮**的 interactive 事件（顾客实际看到的卡）。同一轮出现两张
**同组件**卡 = 顾客看到重复卡 —— **判红**（`check_duplicate_cards`，C 端档生效），
轨迹里同时标成 `cards=confirm,confirm(⚠️重复)`，让日志自己说话：

```
R7 you=123456  tools=order_create!confirmation_required_no_card,interact  cards=confirm,confirm(⚠️重复)
```

为什么当初漏掉：这个指纹**一直在日志里**，但它是中性字段，没人会去数；直到本地把成因
复现出来（`interact` 工具路径与"解析回复文本里的 `<interact>` 块"是**两个独立发射点**，
代码兜底补卡时各发一张）才发现是缺陷。**组件不同不算**（先 form 收资料再 confirm 确认
是两件事，各有答案面）；跨轮重复也不算（顾客点了第一张才会有第二张）。

**正面证据落在哪**：补卡与发卡的日志行（`代码兜底补发确认卡` / `卡下发计数`）由完整档的
「Dump C 端逐轮路由轨迹」步骤 dump 出来（`if: always() && fast != 'true'`）。
`round_trace` 只能说"顾客收到几张卡"，**看不出卡是模型发的还是代码补的** ——
这两行才是唯一能证实"补卡真的触发过"的证据（白名单由 `TestFallbackCardLogWhitelist`
守卫，被删会被 CI 拦）。

**第二形态与代码侧收口**：同一轮两张**同组件**卡还有第二种成因 —— 模型**自己**在一条回复里
调了两次 `interact`（OR-023 首跑 R1：`tools=…,interact,interact` → `cards=choice,choice`，
一张问「两个颜色选哪个」、一张「颜色选好啦～」）。这会踩到会话侧的**单槽**待答卡
（`chat.py` 的 `last_interactive_payload`）：顾客点第一张，回传值与"当前待答卡"对不上。
agent 侧已收口：C 端**同一组件每轮只发一张**，第二张起回
`card_already_emitted_this_turn`（可执行的提示，不静默丢），由
`TestOneInteractiveCardPerTurn` 守卫。**不同组件不受限** —— OR-021 R3 的
`choice(加工项)+form(收货信息)` 是合法形态（一条消息两个问题），一律"整轮一张"会误伤它。

### 6.7 验证码**真值链**（issue #3365 / #3379 / #3434）

规则一句话：**顾客给过的码是唯一真值**。短信只发到顾客手机上，模型没有别的渠道拿到它 ——
它"自己写一个"只会让订单必然被拒（顾客点多少次确认都没用）。

执行前真值链（`resolve_sms_code`，`base_skill` 写工具执行前 + 8.4 确认收口两处同源）：

| 已知真值 | 模型入参 | 处理 |
|---|---|---|
| 本轮消息整条是码 / 会话记住的码（`last_sms_code`） | 缺失 | **补齐** |
| 同上 | 与真值不一致 | **纠正** |
| 同上 | 与真值一致 | 不动 |
| **没有** | 有值 | **拦下**（`sms_code_not_from_customer`）：模型在自造码，让它先向顾客要码（OR-018 首跑实证：自造码必然被拒、订单落不了库） |
| **没有** | 无值 | 不拦（工具自己会提示缺码，走缺参恢复回路） |

真值识别要**尽量准**（否则第二条会误伤）：空格归一（「1 2 3 4 5 6」）、口语前缀
（「验证码是 123456」）、尾随语气词（「123456哦」）都算；订单号/手机号仍不算（边界不变）。

实证（全量档 run 34786827410）：CH-025 / OR-014 的**首跑失败**指纹是
「order_create 因验证码失败，且参数里的验证码与顾客给过/用例声明的**都不一致**
—— 疑似模型自造验证码」；旧行为只管"漏参"，于是自造的码一路走到工具校验失败（重试碰巧对了才绿）。

评测侧的对应断言是 `check_write_code_provenance`（三态：**已经给过** / **始终没发出去** /
**都不一致（疑似自造）**），正面证据是容器日志里的
`代码补齐|代码纠正 order_create.sms_code` —— 由完整档的日志 dump 白名单兜住
（`TestFallbackCardLogWhitelist` 同时守卫卡片与验证码两类标记）。

### 6.8 在办下单 + 当前 skill 无写工具 → 守卫**跨 skill**生效（issue #3477 / #3476）

C-A1 实证（run 34791767013）：会话被 choice 卡锁在 `customer_product`，顾客「确认下单」后
小布回「**没有帮您下单的权限**」并 `human_handoff` 建单 —— 因为：
① 文本级能力误宣纠正只认"当前 skill 有 order_create"；② handoff 守卫只认
customer_order/customer_aftersales；③ 旧正则在"没有"与"权限"之间隔着「帮您下单的」时匹配不上。

修法（agent 侧，`base_skill`）：
- 文本级纠正与转人工拦截扩展到「顾客**在办下单**」（下单意图 × 已查过商品）这一**状态**，与 skill 名无关；
- 被拦/被纠正时把 `pending_interact_skill` **锁回 customer_order** —— 下一轮路由真能完成下单（恢复路径）；
- 措辞表补「协助下单」「没有X下单的权限」等**隔词权限话术**。

评测侧（`check_false_inability`）与 agent 侧**同源**同步覆盖（变体验证：去掉模糊权限形态 → 新用例红）。

**根治（issue #3571，2026-09-14）——判据从"skill 名白名单"彻底改为"状态 × 工具事实"**：

上面那次修法仍留了两处**名字/措辞驱动**的判据（`_has_order_write_tool(skill_name, …)` 硬编码
`skill_name != "customer_order"`；`_mid_order` 仍由**本轮措辞关键词** `_ORDER_INTENT_HINTS` 决定），
所以第四次复发（#3476）之后又出现同族形态。现在：

| 旧判据（名字/措辞驱动） | 新判据（事实/状态驱动） |
|---|---|
| `_has_order_write_tool(skill_name, registry)` | `_order_write_tool_here(registry)`：**工具注册表事实**（本 skill 子集有没有 `order_create`），判据看不到 skill 名 |
| `_mid_order = 意图关键词 × grounded` | `_order_flow_in_progress(...)`：**跨轮状态**（`pending_validated_input.target_tool` / `pending_interact_skill`+`grounded_product_detail` / 在办卡），措辞只作兜底 |
| `skill_name in ("customer_order","customer_aftersales")` | `_handoff_guard_applies(registry, …)`：**工具属性事实**（本 skill 有 `destructive`/`requires_confirmation` 写工具） |
| `_AGENT_INABILITY_RE` 正则窗口 `{0,8}` + 精确子串词表 | `capability_denial_text_hit`：**语义归一 + 结构化判据**（小句内"下单动作词 × 自我能力否定 × 非自我主体排除"，不设距离窗口；`没有`→`没` 归一，插词/语序无关） |

可达性判据 = 「**本 skill 工具事实** ∨（**在办流程状态** × **全局工具事实**）」——两条缺一不可
（只按全局判会放过越权/真不可达；只按状态判会在工具未注册时声称"你可以下单"）。
越权边界保留：非自我主体验证 + 顾客显式诉求/情绪/能力外诉求仍走 `has_escalation_signal` 放行
（DF-020/DF-021 边界）。

防第 5 次复发（**零 LLM 静态锁**，L0）：`tests/unit_ci_workflows/test_capability_guard_invariants.py`
（判据函数不得接收/引用 `skill_name`、不得出现 skill 名字面量、接线处不得再有 `skill_name in (…)`、
覆盖必须由工具属性派生 —— 新增 skill 自动纳入，无需改白名单）；
行为面回归：`backend/ai-agent-service/tests/test_capability_denial_guard.py`。
### 6.9 短消息路由：L1 规则优先于"合成意图"（issue #3476，C-A1 P1 的入口）

`pending_interact_skill` 存在时，≤5 字短消息走**合成意图**快捷路由 —— 旧实现的
`_SKILL_TO_INTENT` 键是**域**名（product/order…），C 端 pending 值
（customer_product/customer_order）**全部 miss → 一律 general**：
「确认下单」(4 字) 在 customer_product 锁里被合成成 general → escape 命中 order 域关键词
却路由到 customer_general（无 order_create）→ 模型只能说"我下不了单"并转人工。

修法：短消息先过 **L1 规则**（「确认下单」→ order_create，0.98；「查订单」→ order_query），
L1 不命中（"确认"/"好的"/"米白"这类点卡值/短确认）才用合成意图；合成映射补 C 端 skill 名
（customer_product→product_inquiry 等）。澄清护栏（#2796）在 L1 检查**之前** —— 模糊轮
优先给兜底示例，领域信号轮不算模糊。

## 7. 新增 C 端用例的检查单

1. 在对应域 `.github/cases/*.yml` 新增，**必写** `persona: xiaobu`（C 端专属）；
2. `tier`：稳定单/双轮且是核心能力 → `smoke`；多轮/复杂流转 → `normal`；
3. 断言优先用**可执行形态**（`order_before` / `required_args` / `forbidden_text` /
   `db_verify`），自然语义 `data_checks` 不算覆盖（`acceptance-protocol` §1.3）；
4. 涉及数据隔离的能力（订单/物流/售后/地址）必须断言「仅本人」+「无 B 端越权工具」；
5. 跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md` 提交生成物；
6. 跑覆盖体检 `--check` 确认无孤儿用例；
7. 用本地 DEBUG 栈实测该用例 ≥1 次（真实 LLM），确认断言与行为一致（先例：行为合理但
   断言过严的，按 §14.2 校准而非删用例）；
8. **断言写工具（`order_create`/`aftersales_create`）的 C 端用例必须"能答卡"**
   （§6.4.1 的 `repeat_until`，或非 `prefer_text` 的 `auto_respond`）——
   固定文本轮在 agent 先发卡时会答非所问 → 空转不下单（OR-021 定向复跑 0/1 的根因）。
   由 `TestWriteCasesCanAnswerCards` 守卫（CI 会拦）；**注意作用域**：只认
   `persona: xiaobu`，`persona` 留空是**未声明/双端**（实测那批是米宝流程用例，
   套 C 端判据会误伤 —— 我为此连错两次，见 issue #3430）。

## 8. 跑评测的三档与提速旋钮（issue #3417）

CI（`xiaobu-acceptance.yml`，dispatch-only）与 `local_runner` 都支持同样的三个旋钮：

```bash
# 完整档（下结论用）：语义不变，只是并发调高
gh workflow run xiaobu-acceptance.yml -R <repo> --ref <branch> \
  -f tier=normal -f shards=1 -f concurrency=6

# 收窄档（迭代复验 1~3 条）：只跑指定用例，与 tier/shard 正交
gh workflow run xiaobu-acceptance.yml -R <repo> --ref <branch> \
  -f tier=normal -f concurrency=6 -f case_ids=OR-019,OR-024

# 快速档（迭代）：不重试 + 跳过取证步骤（real E2E / 路由 dump / DB 审计）
gh workflow run xiaobu-acceptance.yml -R <repo> --ref <branch> \
  -f tier=normal -f concurrency=6 -f fast=true -f case_ids=OR-019,OR-024
```

本地等价（runner 侧）：

```bash
EVAL_CONCURRENCY=6 python tests/agent_eval/local_runner.py normal --cases .github/cases \
  --case-ids OR-019,OR-024 --max-retries 0
```

| 旋钮 | 什么时候用 | 不许用的时候 |
|---|---|---|
| `concurrency` | 任何时候（含下结论） | —— 语义不变，只影响墙钟 |
| `case_ids` | 只改了几条用例 / 复验已知缺陷 | 下结论（会漏掉回归面） |
| `fast` | "改一行看一眼" | **下结论前必须跑完整档** |

**红线**：`fast` 只跳过**取证**（E2E / 路由 dump / DB 审计），绝不跳过**判定**。
验收剧本（acceptance-protocol §2/§4）是独立判定源，永远保留 `always()`。
`--case-ids` 解析不到的 ID 会**报错退出**，不会静默少跑（少跑 ≠ 通过）。

迭代档（`fast=true` 或 `case_ids` 非空）失败时**不会**自动开「小布 C 端验收失败」issue ——
那张 issue 是每日全量结论，不能被分支迭代/局部失败污染（完整档照旧建 issue）。

性能账与实测数据见 [`eval-pipeline-performance.md`](eval-pipeline-performance.md) §2.6。

## 9. 顾客可见产物 × 断言矩阵（还有哪些面**没有**断言）

> 为什么单列一节（issue #3445 复盘）：`cards=confirm,confirm` 这个重复卡指纹**在 CI 日志里躺了很久**，
> 却没人发现 —— 因为评测只断言"结果型"事实（工具调没调、订单落没落库、金额对不对），
> **"顾客实际看到什么"这一整类没有断言面**。凡是没有断言的面，跑一万次也不会报。
> 本节把"顾客可见产物"逐项列出并标注断言状态；**标注"缺"的就是后续要补的**。

| 顾客可见产物 | 已有断言（可执行） | 状态 |
|---|---|---|
| **卡片是否出现** | `expectations: interact`（工具调用或 SSE interactive 事件任一命中，见 §6.2 三发射路径） | ✅ |
| **卡片数量/同轮重复** | `check_duplicate_cards`（同轮同组件 ≥2 张判红）+ 轨迹 `cards=X,X(⚠️重复)` | ✅（#3445 新增） |
| **卡片内容不编造** | `check_forbidden_card_text`（卡片文案禁词）；`check_form_prefill`（form 预填值必须来自真实来源） | ✅ |
| **卡片提问不重复问** | 加工项「已答不再问」（`_user_already_answered_processing`）+ `check_confirm_loop`（同事实 confirm ≥3 次）+ **`check_repeated_card_ask`**（同卡 + 顾客已作答 → 判红，confirm/choice/form 三类卡都覆盖） | ✅（矩阵补行） |
| **写用例必须"能答卡"** | `TestWriteCasesCanAnswerCards`（用例契约层） | ✅ |
| **文案反模式（禁词）** | `forbidden_text` / `want_text` | ✅ |
| **状态宣告必须有工具落地** | `check_unbacked_state_claim` | ✅ |
| **能力误宣（能做说做不了）** | `check_false_inability`（含转人工理由文本） | ✅ |
| **假成功（报错却说成功）** | `check_false_success`（细化：报错后有写成功则不算谎报） | ✅ |
| **隐私（完整手机号回显）** | `check_no_full_phone`（C 端全局） | ✅ |
| **金额/数量正确性** | `amount_verify`（与商品库真值比）、`output_verify`（工具 payload 真值）、`db_verify`（落库明细/号码） | ✅ |
| **号码/验证码来源可追溯** | `check_phone_provenance`、`check_write_code_provenance`（三态） | ✅ |
| **耗轮数（对话效率）** | 软监控（无硬断言） | **有意不做硬断言**：`repeat_until` 展开会把"协作等待轮"计入总轮数、LLM 方差使单跑轮数抖动 —— 硬上限必然误伤；拖沓由"首跑失败指纹 + flake 台账 + 每轮 `rounds=` 对比"间接显性化。若要硬断言，需先采集 ≥10 跑分用例基线 |
| **同一问题被问两遍（卡片维度）** | `check_repeated_card_ask`（同卡 + 已作答 → 判红；confirm/choice/form 全覆盖；防假阳性：未答过不报、改明细后新卡不报） | ✅（矩阵补行）；**文本提问**（非卡片）的重复问仍无判据 —— 无结构化信号，识别成本高于收益，**有意不做**（加工项文本问答已由 agent 守卫 #3473 覆盖） |
| **工具返回值载荷进 transcript** | ✅ `_tool_digest`：每轮打印 `📄 <tool> → orderNo=…, totalAmount=…, orders_n=…`（只摘顾客可感知字段，不落 PII 全量） | ✅（本批补齐 —— 复核 AI 在重放 2 指出的证据缺口） |
| **验收体验层（可懂度/诚实性）** | UA 判定（AI 用户代理：persona + 原文引用 + 基准对照，见 §acceptance-protocol） | ✅（人工零执行；每轮需按模板逐条判，模板见 `acceptance/*/REPORT.md`） |

### 用法

1. **新增/修改 C 端用例前**先看这张表：如果该用例验证的行为落在"缺"的行里，先补断言面（或在用例里显式声明为什么不需要）；
2. **复盘线上问题**时对照本表：多数"顾客抱怨但评测全绿"的问题，都能对应到某一行"缺"；
3. 每补一行，回到本表更新状态（本表是**活资产**，与 §14 的用例喂养同纪律）。
