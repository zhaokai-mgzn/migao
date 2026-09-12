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

## 5. 覆盖体检（`scripts/xiaobu_coverage.py`）

回答「哪个 C 端能力没被测」——B 端的 `mibao-verification-cases.md` 是用例清单生成物，
不回答这个问题。

```bash
# 人读报告
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py
# CI 门禁（孤儿用例/空用例集 → exit 1）；已接入 verify-all.sh gate/quick/full
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py --check
# Markdown（供文档引用）
backend/ai-agent-service/.venv/bin/python scripts/xiaobu_coverage.py --md
```

输出三部分：① 工具覆盖矩阵（缺口标 ⚠️）② 用例归属（按 tier）③ 孤儿用例
（声明 `persona: xiaobu` 却断言非小布工具 = 配置错误，门禁拦截）。
另有**显式豁免**区：有用例但声明了 `skip_reason` 的工具（如 `customer_address_query`
由 CH-025 覆盖但 skip，改由 pytest 验证）——豁免必须显式声明理由，不得靠「看起来有覆盖」。

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

## 7. 新增 C 端用例的检查单

1. 在对应域 `.github/cases/*.yml` 新增，**必写** `persona: xiaobu`（C 端专属）；
2. `tier`：稳定单/双轮且是核心能力 → `smoke`；多轮/复杂流转 → `normal`；
3. 断言优先用**可执行形态**（`order_before` / `required_args` / `forbidden_text` /
   `db_verify`），自然语义 `data_checks` 不算覆盖（`acceptance-protocol` §1.3）；
4. 涉及数据隔离的能力（订单/物流/售后/地址）必须断言「仅本人」+「无 B 端越权工具」；
5. 跑 `python3 .github/render_cases.py --cases .github/cases --out-eval tests/agent_eval/eval_cases.py --out-md docs/testing/mibao-verification-cases.md` 提交生成物；
6. 跑覆盖体检 `--check` 确认无孤儿用例；
7. 用本地 DEBUG 栈实测该用例 ≥1 次（真实 LLM），确认断言与行为一致（先例：行为合理但
   断言过严的，按 §14.2 校准而非删用例）。
