# Agent 行为缺口冻结清单（#3557 / AS-007 / 模块越界拒绝族 / per_area 契约断裂）

> **issue**：#3557（本报告**不**关闭它）｜ **分支**：`infra/agent-gap-triage`（worktree `migao-wt/infra-agent-gap-triage`）
> **基线与口径**：`origin/main` = `9f5dee5f`（主工作区落后 61 提交 → 本报告所有 `file:line` **一律按 origin/main 核对**，
> 与主工作区行号不一致处已显式标注）｜ **报告日期**：2026-09-15
> **作者角色**：归因 worker（**只读分析**，不改业务代码/用例期望值；本 PR 只新增本报告文件）
> **一句话**：缺口 1/3 的根因**不是 LLM 方差**，而是一条**零 LLM 可复现的确定性路由链**——
> 系统自己生成的确认卡文案里含「下单」二字，被 L1 规则表与 escape hatch **同源的两处关键词判据**
> 判成"切到订单域"，于是商品上下架在答卡轮被路由进 `order` skill（该 skill **没有** `product_manage`）；
> AS-007 主因是**用例断言侧**（能力存在、真实重放过），并附带一条可证伪的断言实现缺陷；
> `_calculate_price` 的 per_area 是**独立**的工具层契约断裂（100% 不可达，非偶发）。

---

## 0. 结论速览（冻结清单）

| # | 缺口 | 归因层级 | 建议最小修法（文件所有权） | 可执行验收判据（机器断言优先） | 能被哪一层拦住 |
|---|---|---|---|---|---|
| **G1** | #3557 商品上下架确认卡答卡后不执行（PR-007 R2 零工具 + 「订单模块」口径拒绝） | **引导层（路由）＝主因**；模型层仅贡献措辞；断言层次要 | 卡答轮豁免：`intent_router_node` 内"消息逐字==本会话最后确认卡 `confirmValue`"→ 不做意图重判（`nodes.py`；需 `base_skill.py` 存"发卡 skill"）。**必守契约**：`test_graph_nodes.py:421` 的 quote→order 切换不许红 | ①L0/L1（零 LLM）：`route_by_intent` 对 R2 原文必须返回 `product`（现测 `order`）；②L1 反例：去掉「下单」字样的卡值仍 `product`；③L2：PR-007 升 `must_succeed[tool=product_manage,action=toggle_status]` + `required_args`；④L2 终点：`db_verify` 状态流转（需补 `product_status` fetcher，见 §6-D2） | **L0/L1 可拦**（纯函数断言，秒级零 LLM）；L2 拦"卡答了但没执行"的复现 |
| **G2** | AS-007 换货不查/不问加工项 | **断言层＝主因（b）**；能力不存在被否证（a）不成立 | ①`local_runner.py:844-852` 文本分支放宽到与卡片分支同口径；②`aftersales.yml` 把 `success=true` 升 `must_succeed`+ `db_verify[after_sales_ticket]`；③（存疑）`pre_clean` 的 `price: 23.8` 限定，见 §3.5 | ①L1：给一条"文本询问但不含『加工项』三字"的假轨迹，`_processing_ask_in_round` 必须 True（现测 False）；②L2：AS-007 `skip_reason` 空 + 真重放 `must_succeed` 通过；③L2：`db_verify[after_sales_ticket,expect_status=pending]` 回读到工单 | **L1 可拦**断言实现缺陷（构造轨迹即可）；**行为面无 L0 可拦**，靠 L2 迭代档 |
| **G3** | 模块越界拒绝（「订单场景执行不了商品管理操作」）——**两个触发源，非同一根因** | T1＝引导层（与 G1 **同一根因**）；T2＝引导层（**独立**：escape hatch 不认商品域**动作**词，丢弃了 L1 已判出的 `product_inquiry`） | T1 与 G1 合并（同一修法）；T2 独立一行：`_SKILL_DOMAIN_KEYWORDS["product"]` 补 `"上架","下架"`（**勿顺手加「价格」「库存」**，见 §4.4 风险）或把 L1 高置信结果接入 escape hatch | ①T1 判据同 G1；②T2 L0/L1：`pending=order` + 「再把它上架」必须路由到 `product`（现测 `order`）；③T2 反例：`pending=customer_quote`+「确认下单」仍须切 `customer_order`（#3361 契约） | **L0/L1 可拦**（`route_by_intent` 纯函数断言） |
| **G4** | `processing_item_manage(action=calculate_price)` 对 `per_area` 加工项 **100% 失败**（复核主会话线索：成立，且比线索更严重） | **工具层**（schema↔后端契约断裂）；与 G2 **同域不同层 → 独立缺口，不得合并修法** | `processing_item_manage.py` 补 `width`/`height` 参数并下发 `dimensions`（最小 3 处）。**明确不要**按 `acceptance-protocol.md:225` 的「per_area → quantity=宽×高」去修——该口径只适用于 order_create 路径，用在 calculate_price 上仍必失败且会双计（§5.3） | ①L1（mock，零 LLM）：per_area 调用的 POST payload 必含 `dimensions={width,height}` 且 `quantity` 为计数值；②L1：schema 暴露 width/height（schema↔签名契约）；③L2：新增 per_area 用例 `must_succeed[processing_item_manage,action=calculate_price]` + `output_verify(totalPrice=30×8=240.00)` | **L1 契约层可拦**（工具单测/payload 契约），当前**零用例零断言**（见 §5.4） |
| **D1** | 待裁定依赖：`OrderCreateRequest.quantity` 是 `Integer`（`docs/sql/schema_full.sql:428` 亦 `INTEGER`）→ 合法小数面积被截断 | **数据层（契约）**，**产品裁定项**，本报告只登记 | 不改（登记依赖） | 阻塞类：任何"单价×非整数数量"的金额类用例的可复现性 | 目前**无层可拦**（L1 只查 payload 键∈接收端字段，不查类型宽度） |

---

## 1. 方法与证据边界

### 1.1 证据来源（全部可核验）

| 项 | 位置 |
|---|---|
| 基线代码 | `origin/main` `9f5dee5f`（本 worktree = 该 sha，`git log --oneline -1` 可验） |
| PR-007 失败轨迹 | issue #3557；`acceptance/2026-09-14/replay-triage/REPORT-3528-verify.md` §2.2（run `34808115143`：`rounds=5 tools=['product_search','interact'] score=50%`） |
| 同 run 成功形态 | 同上 §0：PR-016 / PR-020 / CR-001 / PR-005 **4/4** 成功（run `34808115143`、`34808435561`） |
| AS-007 用例 | `.github/cases/aftersales.yml:258+`（`skip_reason: ""`，`merge_log` 内含 3 次真重放 run id） |
| AS-007 CI 真实结果 | PR #3589 的 `agent-behavior-eval` 评论：run `34812509606` → AS-007 **0.75 unstable**；run `34817668476`（head `5cab5167`＝**最终断言集**）→ AS-007 **1.00 pass** |
| 五层归因定义 | `docs/testing/xiaobu-eval-tooling.md:307`、`:449`（**基础设施层排最前**——本报告已先排除，见 §1.3） |
| 断言降级阶梯 | `docs/testing/acceptance-protocol.md` §1.2/§1.3/§3.1/§3.2 |

### 1.2 我新增的**确定性探针**（本报告最硬的一类证据）

`route_by_intent`（`app/graph/nodes.py:664`）与 `RuleMatcher`（`app/router/rule_matcher.py`）都是
**同步纯函数**，不需要 LLM、不需要 DB/Redis → 可以直接喂"R2 实发原文"复现路由判定。
探针脚本见附录 A（**仅 /tmp，未进 commit**）。实测输出（逐字抄录）：

```
R1 把遮光窗帘下架           -> L1=None               conf=None kw=None
R2 confirmValue             -> L1='order_create'      conf=0.98 kw=['下单']          ← 决定性
R3 再把它上架               -> L1='product_inquiry'   conf=0.95 kw=['上架']          ← 被路由层丢弃
R4 确认                     -> L1=None               conf=None kw=None
PR-016 confirmValue(样本)   -> L1='product_inquiry'   conf=0.95 kw=['商品','价格']
mibao intent->route: {order_create:'order', product_inquiry:'product', after_sales:'aftersales', ...}

pending='product' intent='order_query'     -> route='order'    after_pending=''        ← G1 复现
   msg='确认：商品名称=遮光窗帘；当前价格=¥168.00；当前状态=在售；操作=下架（改为停售，买家不可下单）'
pending='product' intent='product_inquiry' -> route='product'  after_pending=''
pending='product' intent='*'  msg=<同一句去掉「（改为停售，买家不可下单）」> -> route='product' after_pending='product'  ← 反事实：去掉「下单」即不复现
pending='product' intent='*'  msg=PR-016 形态 confirmValue                  -> route='product' after_pending='product'  ← 成功形态对照
pending='order'   msg='再把它上架'          L1=product_inquiry -> route='order'          ← G3-T2 复现
pending='order'   msg='把遮光窗帘下架'       L1=<no-L1>         -> route='order'
pending='order'   msg='改一下遮光窗帘的价格'  L1=product_inquiry -> route='order'
pending='order'   msg='查一下库存'          L1=product_inquiry -> route='order'
pending='aftersales' msg='把遮光窗帘下架'    L1=<no-L1>         -> route='aftersales'
pending='order'   msg='创建商品' / '查商品'   L1=product_inquiry -> route='product'    ← 对照：表内有词就正常切换
pending='product' msg='再把它上架'          L1=product_inquiry -> route='product'
```

### 1.3 证据边界（勿越界解读）

| 边界 | 说明 |
|---|---|
| **基础设施层已排除在先** | ① PR-007 所在的 run `34808115143`：本用例**零工具调用**（`tools=['product_search','interact']`），**不是**工具报错，且同 run 另外 4 条用例的写工具**全部落地**（4/4）⇒ 无 infra 故障；② 同族 run `34817668476` 的 CI 评论原文 `🔧 工具健康度: 工具调用 32 次，失败 0 次（0%）`。按 `xiaobu-eval-tooling.md:449`（基础设施层排最前），前置层不成立，下面的层级判定有效 |
| **未做真 LLM 重放（诚实标注）** | 本机 `docker info` 失败、`backend/ai-agent-service/.env` 不存在、shell 无 `PRIMARY_API_KEY`、本地无 `:8001` 服务（四条均实测）→ 与 PR #3589 §4.1 记录的限制同源。**本报告的确定性结论不依赖 LLM**；凡依赖 LLM 采样处均已显式标注 |
| **原报告轨迹只含 60 字摘要** | 不含完整 `final_text`、不含只读工具入参、不含 SSE 原始事件（`REPORT-3528-verify.md` §2.2）→ "模型为什么选择那个措辞"属**推断**，故 G1 把"措辞归因"与"路由归因"分开写（只有后者是确证的） |
| **issue 自述的服务端旁证不足** | issue #3557 已自认 `docker logs --tail=100` 被截断、不足以定位 → 本报告**不复述其猜测**，改为给出可证伪的代码级根因（§2.1） |
| **不采信"模型方差"作为主因** | 跨 run 同签名（`34805827043` 改前 / `34808115143` 改后）+ 同 run 同类答卡轮 4/4 成功 + **本报告确定性探针复现** → 方差不是主因 |

---

## 2. 缺口 1（G1）：#3557 商品上下架确认卡答卡后不执行

### 2.1 根因：确定性三步链（不是"引导层"这么笼统，而是三处具体判据）

**R1（正常）**：`把遮光窗帘下架` → L1 无规则命中 → LLM 归类 `product_inquiry` → `product` skill
（`nodes.py:769-773` 的 `_INTENT_TO_ROUTE['mibao']['product_inquiry']='product'`）→
`product_search` + `interact(confirm)`；轮末因 `product ∈ CREATION_SKILL_NAMES`
（`base_skill.py:321`）且 `final_content` 不含 success marker（`base_skill.py:4108-4128`）
→ 会话锁 `pending_interact_skill='product'` 落库（另见 `base_skill.py:3941-3944` interact 成功路径）。
卡片 `confirmValue` 由**模型**按 `tools/interact.py:114` 的强制要求写成含上下文的长值。

**R2（断裂）**：答卡轮 harness 逐字回传该 `confirmValue`（`local_runner.py:2831-2833`，issue 已排除 harness 问题，采信）→
该字符串含 **「…买家不可下单）」**：

1. **判据点 ①（L1 规则表，先于一切）**：`IntentRouter.route()` 先跑 L1（`app/router/intent_router.py:66-73`），
   `_KEYWORD_MAP[IntentType.ORDER_CREATE]` 含 `"下单"`（`app/router/rule_matcher.py:38`）
   → **实探针命中 `order_create` conf 0.98 kw=['下单']**；`_make_decision` 直接返回该结果，
   **LLM 分类器根本不被调用**。
2. **判据点 ②（escape hatch）**：`route_by_intent` 里 `_pending_domain='product'`，
   本领域词表 `{"查商品","搜商品","创建商品","商品管理"}`（`nodes.py:35`）**不含**卡值里的任何词
   → "本领域信号优先"（`nodes.py:736-742`）不成立 → 进入 escape hatch（`nodes.py:743-755`），
   order 域词 `"下单"` 命中（`nodes.py:31`）→ **主动清空 `pending_interact_skill`**（探针实测 `after_pending=''`）。
3. **判据点 ③（意图→skill 映射）**：`nodes.py:769-773` 用 intent 兜底 →
   `order_create → 'order'` → 进入 `order` skill。

**R2 的结果为何是"零工具调用 + 订单模块口径"**：`order_skill.py:11-19` 的 `ORDER_TOOLS`
**没有 `product_manage`**（只有 `product_search`/`product_detail` 等只读商品工具）→
模型手上没有任何可执行的写工具；且 `prompts/order.md:5` 写着"当前对话聚焦在订单/物流/加工单领域"，
skill 的 `display_name="订单管理"`（`order_skill.py:28`）→ 模型据此**自述**「我们在订单处理模块」。
⇒ **"订单模块"这句措辞是模型层的自由文本，但它是被引导层的错误路由喂出来的**。

**R3-R5 为何持续拒绝**：R2 轮末 `order ∈ CREATION_SKILL_NAMES` 且无 success marker
→ 会话锁被改成 `'order'`（`base_skill.py:4108-4128`）。此后：

| 轮 | 实发 | L1 | escape hatch | 结果 |
|---|---|---|---|---|
| R3 | `再把它上架` | **`product_inquiry` 0.95**（kw=`上架`） | 未触发（`上架` 不在 product 词表）→ **坚守 `order`** | 拒绝（"上架属于商品管理"） |
| R4/R5 | `确认`（2 字） | 无 | 短消息分支按 `pending_skill` 合成 `order_query`（`nodes.py:262-279`）→ 坚守 `order` | 「没有待确认的操作」 |

⇒ **5 轮全部由确定性判据解释完毕，无需假设模型方差**。R3 甚至是个更刺眼的 bug：
**L1 已经高置信判出 `product_inquiry`，却被 escape hatch 的"只认关键词表"覆盖**（= G3-T2）。

### 2.2 同 run 成功形态 vs 失败形态：链路数据差异（可对照）

| | PR-007（失败） | PR-016 / PR-020 / CR-001 / PR-005（成功） |
|---|---|---|
| 发卡 skill | `product`（`product_manage` 在工具集内） | `product` / `order` 等（写工具在各自工具集内） |
| `confirmValue` 文本 | 含 **`下单`**（"买家不可下单"） | 探针用 PR-016 形态卡值：含 `商品`/`价格`，**无任何跨域关键字** |
| L1 规则命中 | **`order_create`（0.98）** | `product_inquiry`（0.95） |
| `pending=product` + 该文本 → `route_by_intent` | **`order`**（含 `after_pending=''`，锁被清） | **`product`**（锁保留） |
| 写工具可达性 | ❌ 目标 skill 无 `product_manage` | ✅ 有 |
| 结果 | 零工具调用 + 拒执行 | 写工具成功落库 |

**判据一句话（可编码）**：**差异不在答卡机制，而在"卡值文本是否命中跨域关键词"**。
⇒ 只要卡值里出现任一**其他域**的词，答卡轮就会脱离原 skill；这是"内容耦合"缺陷，
不是单条文案的运气问题（同类可触发词：`下单`、`订单`、`发货`、`物流`、`退货`、`退款`…）。

### 2.3 采信 issue #3557 已排除项（不重复劳动）

| issue 结论 | 采信 | 本报告补充 |
|---|---|---|
| ① 不是 harness 答卡协议错（`local_runner.py:2831-2833`） | ✅ 采信 | 探针与该结论一致：问题在 agent 侧路由 |
| ② 不是"答卡轮机制整体坏"（同 run 4/4 成功） | ✅ 采信 | 并给出**差异的具体判据**（§2.2）——issue 只说"应落在上下文/路由链路"，本报告定位到三处判据点 |
| ③ 不是数据缺口（#3528 已自包含化） | ✅ 采信 | 独立旁证：`pre_clean:「遮光窗帘」无重复（1 件）`（#3528 修好 price 过滤后，`REPORT-3528-verify.md` §1） |
| ④ 不是 flake | ✅ 采信 | 升级为**确定性**：探针在零 LLM 下复现 |
| 服务端日志旁证（`tail=100` 被截断） | ✅ 采信"不足以定位" | **不复述猜测**；但记录一处需留意的**未对齐点**：该 dump 里的 `[product] Flow complete, pending_skill cleared` 若确属 R1 轮末，则 R2 根本没有会话锁——此时走的是"判据点 ①+③"（无 ②），**结论不变**（同样落到 `order`）。两条路径都因 L1 的「下单」而失败 ⇒ 根因表述对锁状态**鲁棒** |

### 2.4 归因层级

- **引导层（主因）**：路由判定链（`rule_matcher.py:38` + `nodes.py:31/736-755/769-773`）在"卡答轮"上没有豁免。
- **模型层（非主因，仅措辞）**：`confirmValue` 里那句"（改为停售，买家不可下单）"与拒绝话术
  "我们在订单处理模块"都是模型自由文本。**但模型只是触发器**——触发词由系统自己的发卡协议强制要求
  含上下文（`interact.py:114`），且**同一句卡值在修复后必须仍然能通过**（不许靠改文案绕开）。
- **工具层（未触达但对结果有贡献）**：`order` skill 无 `product_manage` → 零工具调用（这是"拒绝"的物理原因）。
- **断言层（次要缺口，须一并修）**：PR-007 现有断言 `expectations[product_manage(toggle_status,status=on_sale)]`
  + `data_checks: ["success=true"]`（`.github/cases/product.yml:225-231`）**只能证明"某轮调用过"**，
  证明不了"卡答后真的执行了"；`success=true` 属计分白名单，但它对"哪个 action 成功"无判别力
  （`action=toggle_status` 成功 1 次即可，且**先下架后上架**的顺序/终态无断言）。

### 2.5 建议最小修法（爬「最少代码」阶梯）

**阶梯判定**：YAGNI 不成立（本地报会拒执行，用户可见）；复用已有机制成立
（`_is_card_confirm_value`、`_SKILL_TO_INTENT`、`guard_forced` 都是现成的）→ 走"复用 + 最小实现"。

**首选（约 10 行，跨 2~3 文件）——卡答轮豁免**：

1. `base_skill.py:3947-3963`（interact 成功路径，`skill_name` 就在作用域内）
   在写 `last_confirm_value` 的同处**顺手多存一个键**：`_full["last_confirm_skill"] = skill_name`
   （代码兜底发卡处 `base_skill.py:4016-4027` 同样加一行）。
2. `intent_router_node`（`nodes.py:251` 之后、`nodes.py:374` 调 `IntentRouter().route()` **之前**）：
   当 `pending_skill` 非空且 `last_user_msg` **逐字等于** 本会话的 `last_confirm_value`
   （复用 `base_skill.py:681 _is_card_confirm_value` 的精确匹配语义，**不要另写启发式**）：
   - 若 `last_confirm_skill == pending_skill` → **不做意图重判**，直接按 `_SKILL_TO_INTENT[pending_skill]`
     合成 intent（复用 `nodes.py:263-278` 现成映射）并 `return`；探针已证该 intent 会映射回原 skill
     （`product_inquiry → 'product'`），故**无需新增 flag**，escape hatch 清锁无害（skill 轮末会重新落锁）。
   - 若 `last_confirm_skill != pending_skill`（如 `customer_quote` 发的卡）→ **保持现行为**（放行切换）。
3. **必守契约（不许踩）**：`tests/test_graph_nodes.py:421 test_quote_skill_下单_escapes_to_order_skill`
   要求 `pending=customer_quote` + 「确认下单/我要下单/帮我下单」**必须**切到 `customer_order`
   （issue #3361，C 端报价→下单死路的防治）。⇒ 修法**不能**是"卡答轮一律不切域"，
   必须是"**本 skill 自己发的卡**，答卡轮不切域"（`last_confirm_skill` 正是这条判据）。
   同族先例 `test_graph_nodes.py:446`（C 端 `customer_*` 前缀导致的同域误判，已修）**保持绿**。

**明确不做（防过度建设 / 防踩坑）**：

- ❌ 不要改 `_SKILL_DOMAIN_KEYWORDS["order"]` 删掉 `"下单"`：那是 #3361 的修复（`nodes.py:22-31` 注释 + `test_graph_nodes.py:421` 锁着），删了会复发 OR-017 的"报价卡后无法下单"。
- ❌ 不要靠"让模型别在 confirmValue 里写『下单』"：文案由模型生成，且系统协议**要求**含上下文；修 prompt 只能降低概率，判据仍是内容耦合。
- ❌ 不要把 `last_confirm_value` 的提升做成"给 `_SKILL_DOMAIN_KEYWORDS` 打补丁"：治不了同类（任何跨域词都会触发）。

**升级项（非必需，建议随特征修法一起做）**：把这套判据抽成 `nodes.py` 内的
`_is_card_confirm_round(state)` 纯函数 + L0 不变式（禁止"卡答轮"走 L1 重判），
使"第 5 次复发"无法以"再加一个关键词例外"的方式发生（同 #3625 的 L0 焊死思路）。

### 2.6 可执行验收判据（优先机器断言）

| 判据 | 层 | 具体写法（可直接抄） | 现状（改前） |
|---|---|---|---|
| **A1** | L0/L1 零 LLM | `route_by_intent`：`pending='product'`、`intent='order_create'`、消息=R2 原文 → 断言 `== 'product'` **且** `state['pending_interact_skill'] == 'product'` | **红**（实测 `'order'` / `''`） |
| **A2** | L0/L1 零 LLM | 反例：同一句**去掉**「（改为停售，买家不可下单）」→ 仍 `'product'`（防"靠删词过测"） | 绿（但需与 A1 同时锁） |
| **A3** | L0/L1 零 LLM | 契约锁：`test_graph_nodes.py:421/446` 两条既有测试必须保持绿（quote→order 切换、C 端同域不逃逸） | 绿（不许变红） |
| **A4** | L1（可选，零 LLM） | 断言 `interact.py:114` 描述的协议不变：卡值仍要求含上下文（防"用缩短 confirmValue 绕过"） | — |
| **A5** | L2 迭代档（真 LLM） | PR-007 断言升级：`must_succeed: [{tool: product_manage, action: toggle_status}]`（`.github/cases/product.yml`，`must_succeed` 的 persona 口径已由 #3544/#3580 修好，`tests/unit_ci_workflows/test_xiaobu_case_set.py:356-375` 现按 persona 过滤 → B 端可声明）+ 保留 `status=on_sale` 期望 + `required_args[product_manage].fields=[product_id, status]` | **红**（`unmatched expectation`；仅"调用过"级别的断言也判不出"没执行"） |
| **A6** | L2 终点（需依赖 D2） | `db_verify` 断言状态流转 `on_sale → off_sale → on_sale` 落库（**当前无 fetcher**，见 §6-D2） | 缺能力 |

**"修好了"的判据**：A1+A2+A3 全绿（零 LLM，秒级，可进 required 候选）+ A5 真实重放由 50% 转 100%。

### 2.7 能被哪一层拦住

- **L0/L1 完全可拦**：A1/A2/A3 是纯函数断言（`route_by_intent` 是同步纯函数，探针已证），
  毫秒级、零 LLM、零网络 ⇒ 按 §16.1 铁律"能由 L0/L1 拦截的缺陷不允许流到 L2+"，
  **本修法必须带这类静态/单元不变式**，禁止只靠真 LLM 全旅程去撞。
- L2 只承担"行为回归确认"（A5/A6），不承担定位。

---

## 3. 缺口 2（G2）：AS-007 换货不查/不问加工项

### 3.1 判定：**(b) 用例断言/资产问题为主**；(a) 能力缺口**不成立**

**否证 (a) 的一手证据（三条独立）**：

1. **prompt 有这条路径**：`app/graph/skills/references/prompts/aftersales.md:27-31`
   「换货/维修流程（🔴 选目标商品后必须确认加工项）」明确要求 `product_detail` 取完整档案 →
   `processing_items` 非空则 `interact(choice, multiSelect=true)` 主动询问（该规则 2026-09-08 由 issue #3033 加入）。
   工具侧 `product_detail` 确实返回 `processing_items`（PR-016 run `34808115143` R4 实测 `processing_item_query(items=4)`）。
2. **真实重放里 agent 做到过**：run `34815074088`（作者记录，`merge_log` 原文）：
   「R2 product_detail（发现 2 条同名）→ 选品卡 → **R3 agent 主动发加工项 choice 卡** → R5 order_query →
   R8 after_sales_manage 建单成功」；run `34812509606` 亦「**换货工单已真实创建**（`ticketNo=AS-20260914-9002`）」。
3. **最终断言集下真重放 100%**：PR #3589 的 CI 行为映射（run `34817668476`，head `5cab5167`
   = 已删掉作者那条错断言、`fallback: "好的"` 的**最终形态**）→ AS-007 **1.00 pass**。

⇒ 结论：**"换货不查/不问加工项"作为能力缺口已被否证**；它作为"用例恒不可达"的存量缺口也已被 #3568 修掉
（`skip_reason: ""`）。**剩下的成分是断言侧**——见 3.3/3.4。**按 §14.2，这次该校准断言，不该默认改代码。**

### 3.2 为什么不能反过来判"行为合理但要改代码"

- 0.75/1.00 的波动（run `34812509606` vs `34817668476`）**不是**能力缺失签名：两次都走到建单，
  差异在"这一轮 agent 是否恰好先发卡"，属 LLM 合法变体（§14.2「有效性漂移」的形态）。
- §14.2 已给 AS-007 一次校准先例（`expectations` 改为 `interact or direct_reply`）：**先例支持"该校准就校准"，
  但前提是"真实重放 fail 且行为合理"**。本轮重放 = pass（`34817668476`）⇒ **不满足放宽断言的前提**，
  只能做**断言可执行化/去歧义**，不能删断言。

### 3.3 断言实现缺陷（**可证伪的具体缺陷，本报告新发现**）

**事实**：`_processing_ask_in_round`（`tests/agent_eval/local_runner.py:844-852`，由 `order_before` 的
语义 token `processing_ask` 调起，`:817/:885-886`）两条分支的宽严**不一致**：

```python
# 卡片分支：title 含「加工项」**或「加工」** 都算（OR-017 run 34670989760 实证修过）
# 文本分支：text 里必须含字面「加工项」三字，再叠加 选择/需要/是否/加
return "加工项" in text and any(k in text for k in ("选择", "需要", "是否", "加"))
```

⇒ agent 用**文本**主动询问但不写"加工项"三字时（例：「这款面料需要加**刺绣工艺**吗？」
「这款支持**打孔加工**，要一起做吗？」），检测为 **False** → `check_order_before` 判
「`order_before[processing_ask before …]: 全程未调用 processing_ask`」（`:966-967`）
→ **整例判红（score 0）**。
而 AS-007 的 `data_checks` 自己写着「**文本询问亦可，语义由 order_before 保证**」
（`.github/cases/aftersales.yml:346`）⇒ **用例声明与检测实现不一致 = 假红温床**。

**为什么这很可能就是 0.75 那次的失败点**：AS-007 的 `fallback: "好的"`（中性）设计**故意**让
"agent 不问 → 加工项为空 → `processing_ask` 判红"暴露缺口；但反过来，agent**问了**（文本形态无"加工项"三字）
也会判红 —— 检测器分不清这两种情形。**证据不足处**：我没有 run `34812509606` 的逐轮轨迹
（B 端 acceptance 步骤不上传 artifact，见 `REPORT.md` §1.2「无 artifact」），
故只能标为"高可信推断 + 一条可先跑的证伪判据"（见 3.6-B1）。

### 3.4 建议最小修法

**阶梯**：YAGNI 不成立（假红会持续污染结论）；复用成立（卡片分支已有正确口径）→ **对齐两分支口径**（1 行级）。

| # | 文件 | 改法 | 理由 |
|---|---|---|---|
| M1 | `tests/agent_eval/local_runner.py:852` | 文本分支与卡片分支同口径：`("加工项" in text or "加工" in text)` + 询问意图词（沿用 `选择/需要/是否/加`，并建议补 `吗/要不要/可以` 中的至少一个问句标记） | 消除"卡问算、文本问不算"的不一致；**不放宽语义**——仍要求"询问意图"，只是不再要求字面三字 |
| M2 | `.github/cases/aftersales.yml`（`data_checks` + 新断言） | ① `success=true` 升 **`must_succeed: [{tool: after_sales_manage, action: create}]`**（口径守卫已按 persona 收窄，可直接用）② 新增 `db_verify: [{fetch: after_sales_ticket, source: after_sales_manage, expect_status: pending}]`（`local_runner.py:3218-3260` 已支持该 fetcher；建单默认态见 `AfterSalesTicketService.java:346 setStatus("pending")`；**字段名以 `/api/admin/after-sales/{id}` 详情实际键为准，勿臆造**） | 把"工单真的落库 + 真的是换货"从自然语义升为机器断言（§3.2/§1.3 铁律） |
| M3 | `.github/cases/aftersales.yml`（`order_before`） | 保留 3 条时序（`order_query before after_sales_manage`、两条 `processing_ask`），**不得**回加 `order_query before product_detail`（作者已证业务上不成立，`merge_log` ③） | 防复发"过度约束假红" |
| M4（存疑，需先取证） | `.github/cases/aftersales.yml:pre_clean` | 若 CI 日志证明 `pre_clean` 返回"无重复（≤1 件）"却仍出现同名多件 → 去掉 `price: 23.8` 限定（先例：PR-017/`REPORT-3528-verify.md` §1 的 `price` 过滤恒不匹配） | 见 §3.5 |

**明确不做**：❌ 不放宽/删除 `processing_ask` 时序断言（那是本条的真值内核）；
❌ 不把 `product_detail`/`after_sales_manage` 期望降级；❌ 不改 `aftersales.md` 的规则（能力已存在，改 prompt 属无据）。

### 3.5 存疑项：`pre_clean` 的 `price` 限定（**证据不足，标注清楚**）

**代码事实**：`local_runner.py:233-236`：

```python
matched = [p for p in items if kw in str(p.get("name","")) and (price is None or p.get("price") == price)]
if len(matched) <= 1:
    return f"「{kw}」无重复（{len(matched)} 件），无需去重"        # ← 静默短路
```

⇒ 带 `price` 限定只清"**同名同价**"的重复；异价同名重复不清，且**静默**返回"无需去重"。
AS-007 的 `pre_clean` 带 `price: 23.8`，而种子价确为 `23.80`（`tests/agent_eval/fixtures/mibao_eval_seed.sql:30`）
⇒ 单看数值**应当命中**，故**不能判定它是 no-op**（与 #3518 的 `price: 100 vs ¥168` 情形不同）。
但 run `34815074088` 的 trace 又记录"R2 product_detail **发现 2 条同名**" ⇒ 重复**确实存在且没被清掉**，
成因未定（可能是并发用例在清理窗口之后建了同名商品、或该轮 pre_clean 未命中）。
**处置**：标为**待取证**，取证命令见 3.6-B2；在拿到该 run 的 `🧹 pre_clean:` 与 `data=product_detail(...)` 两行前，
**不要**据此改 `pre_clean`（避免又一次"按猜测改用例"）。

### 3.6 可执行验收判据

| 判据 | 层 | 写法 | 现状 |
|---|---|---|---|
| **B1** | **L1 零 LLM**（构造假轨迹即可，不需要 LLM） | 构造 `results=[{tool_calls:[], final_text:"这款面料需要加刺绣工艺吗？"}]` → 断言 `_processing_ask_in_round(r) is True`；另加反例 `final_text:"您的订单已发货"` → `False`（防过度放宽） | **红**（现实现要求字面「加工项」） |
| **B2** | L2 取证（不改断言，先读日志） | `gh run view <run> --log \| grep -E "pre_clean:「2699…»\|product_detail\(.*name=2699"` → 判定 M4 是否成立 | 待跑 |
| **B3** | L2 机器断言（修后必过） | AS-007：`skip_reason==''` + `must_succeed[after_sales_manage(action=create)]` 通过 + `db_verify[after_sales_ticket,expect_status=pending]` 回读到工单 | 部分缺（`success=true` 已有；`must_succeed`/`db_verify` 需补） |
| **B4** | L2 行为（§13.3 有效性验证） | 旧形态重放必 fail：把 `user_inputs` 回退成 #3568 前的单轮形态 → `skip_reason` 空时该用例必须判红（#3589 §4.1 已用确定性结构判定做过，可复用） | 已做过（结构判定） |
| **B5** | L2 波动治理（§14.2） | 修后连跑 3 次 AS-007（迭代档）：若仍时而 0.75，则按 B1 结论检查是否仍是 `processing_ask` 假红；若行为本身波动 → 记 flake 台账并收窄断言 | 待跑 |

### 3.7 能被哪一层拦住

- **B1 是 L1 级可拦**（纯函数 + 构造轨迹，零 LLM）⇒ 断言实现类缺陷**本可以**被 L1 拦住，
  历史漏检原因是"没人给检测器写反向用例"（这正是 §14.5 / #3555「覆盖厚度」要治的形态）。
- AS-007 的**行为面**（agent 是否主动问加工项）无 L0 可拦，只能靠 L2 迭代档（1-3min）。
- **L0 可拦项**：`.github/cases/aftersales.yml` 的 `order_before` 语法/契约（`TestRepeatUntilCases`
  等既有守卫）、`processing_ask` token 白名单（若新增 token 必须进 `_parse_qualified_order_before` 的解析集）。

---

## 4. 缺口 3（G3）：模块越界拒绝（「订单场景执行不了商品管理操作」）

### 4.1 结论：**两个触发源；T1 与 G1 同一根因（合并修法），T2 是独立根因（单独一行修法）**

**不草率合并的理由**：T1 的失败点是"卡答轮被 L1 关键词劫持"，T2 的失败点是
"escape hatch 的词表缺商品域**动作**词、并因此**丢弃了 L1 已给出的高置信判定**"。
两者的修法行不同、判据不同、且 T2 在**没有卡答轮**的普通轮次也会发生。

### 4.2 T1（= G1 根因）：卡答轮 `confirmValue` 含跨域词 → 被确定性路由到 `order`

复现输入序列（与 #3557 逐字一致，PR-007）：
`把遮光窗帘下架` → 〔卡：`confirmValue=确认：商品名称=遮光窗帘；当前价格=¥168.00；当前状态=在售；操作=下架（改为停售，买家不可下单）`〕
→ 逐字回传 → agent 答「这个操作当前没法在**订单模块**完成」。
**判据与修法完全继承 §2.5/§2.6（A1/A2/A3/A5）**，不重复。

### 4.3 T2（独立根因）：`pending_skill` 锁在非商品域时，商品域**动作**词无法逃逸

**触发条件（探针实测，全部确定性）**：

| 前置（会话锁） | 用户输入 | L1 判定 | 实际路由 | 用户可见结果 |
|---|---|---|---|---|
| `pending=order` | `再把它上架` | ✅ `product_inquiry` 0.95 | ❌ **`order`** | 「上架属于商品管理，不在订单模块」 |
| `pending=order` | `把遮光窗帘下架` | 无 L1 | ❌ **`order`** | 同族拒绝 |
| `pending=order` | `改一下遮光窗帘的价格` | ✅ `product_inquiry` | ❌ **`order`** | 同族拒绝 |
| `pending=order` | `查一下库存` | ✅ `product_inquiry` | ❌ **`order`** | 同族拒绝 |
| `pending=aftersales` | `把遮光窗帘下架` | 无 L1 | ❌ **`aftersales`** | 同族拒绝 |
| `pending=order` | `创建商品` / `查商品` | ✅ `product_inquiry` | ✅ `product` | 正常（对照：表内有词就切换） |
| `pending=product` | `再把它上架` | ✅ `product_inquiry` | ✅ `product` | 正常 |

**机制**：`_SKILL_DOMAIN_KEYWORDS["product"] = {"查商品","搜商品","创建商品","商品管理"}`
（`nodes.py:35`）全是**管理端查询口径**，**不含任何动作词**（上架/下架/改价/库存调整）；
句式表 `_SKILL_DOMAIN_PATTERNS`（`nodes.py:50-56`）也**刻意只收询问型**
（注释说明：裸词会让下单流程「遮光窗帘 3 米」被判成切商品域，OR-014/OR-017 依赖此约束）。
⇒ escape hatch（`nodes.py:743-755`）不触发 → 坚守原 skill → 原 skill 无 `product_manage`（如 `ORDER_TOOLS`）
→ 零工具调用 + 拒绝。**同时**：`route_by_intent` 完全没有参考 `intent`（L1 的高置信结果）
来决定是否允许切域 —— 这是"信息已算出却被丢弃"的浪费。

**最小复现输入序列（可直接抄进 case/pytest）**：
```
R1: "查一下最近的订单"            # 把会话锁进 order skill（order_query 正常返回）
R2: "再把它上架"                  # 期望：切到 product skill 并调用 product_manage(toggle_status)
```
> 注：同一现象在 C 端 `customer_quote` 锁下更危险——`_skill_keyword_domain('customer_quote')='quote'`
> 而 `"quote"` **不在** `_SKILL_DOMAIN_KEYWORDS` 里（`nodes.py:21-37` 无该键）⇒ 该 skill 的
> "本领域信号优先"检查恒为空集（`nodes.py:728 → set()`）。本报告不把它列为独立缺口，
> 但**修 G3-T2 时必须回归这一条**（`test_graph_nodes.py:421` 就是它的守卫）。

### 4.4 建议最小修法（T2）

**首选（1 行，覆盖已观测）**：`nodes.py:35` 的 product 词表补 `"上架", "下架"`。
- **为什么安全**：这两个词是**商品管理专属动作**，在 C 端下单/报价/售后话术里不出现
  （`_SKILL_DOMAIN_PATTERNS` 的注释解释了为什么裸名词会坏事，动词没有这个问题）。
- **连带影响（正向）**：`_msg_has_domain_keyword`（`nodes.py:85`）也用它判"澄清轮"，
  加了之后"上架/下架"不再被当澄清轮 → 更准。

**次选（更广但风险略高，可作后续）**：把 **L1 高置信判定接入 escape hatch**——
即 `nodes.py:743` 循环前，若 `intent`（`nodes.py:715` 已取出）在 `_INTENT_TO_ROUTE[agent_type]`
里映射到的 skill 域 ≠ `_pending_domain` **且** `route_decision.source == "rule"`（L1 命中、高置信）
→ 允许切换。优点：修整类（不止上架/下架）；风险：短答卡值/UUID 被误判的历史问题
（`nodes.py:719-723` 注释）依赖"L1 只认关键词表、置信度高"这一前提 → **必须与新判据一起补回归测试**。

**明确不做**：❌ 不要给 `_SKILL_DOMAIN_KEYWORDS["product"]` 顺手加 `"价格"`/`"库存"`（这两个词在
C 端报价/下单话术里高频出现，会与 `customer_quote` 的锁产生新的误逃逸）；
❌ 不要用"回复文本纠正"（`capability_denial_text_hit`，`base_skill.py:1279/1447/1490`）来盖住这个拒绝——
该守卫的动作词是**下单族**（`_ORDER_ACTION_WORDS`），且**语义上不该**把"这个 skill 真做不到"的话术纠正掉
（`order` skill 确实没有 `product_manage`）。**正解是让请求路由到能做的 skill，而不是让 agent 嘴上答应。**

### 4.5 验收判据（T2，均 L0/L1 零 LLM）

| 判据 | 写法 | 现状 |
|---|---|---|
| **C1** | `route_by_intent(pending='order', intent='product_inquiry', msg='再把它上架') == 'product'` | **红**（实测 `'order'`） |
| **C2** | 同上，msg ∈ {`把遮光窗帘下架`, `改一下遮光窗帘的价格`, `查一下库存`} 三条都 `== 'product'`（覆盖动作词与查询词两类） | 红 |
| **C3** | 反向契约：`pending='customer_quote'` + `确认下单` → `== 'customer_order'` **且** `pending_interact_skill==''`（沿用 `test_graph_nodes.py:421`） | 绿（不许变红） |
| **C4** | 反向契约：`pending='order'` + `确认`（无域信号）→ **仍 `'order'`**（防"逃逸过宽"把短确认文本甩走） | 绿（现行为正确，需锁住） |
| **C5** | C 端 `_skill_keyword_domain('customer_quote')` 的 `quote` 域不在词表 → 若采纳"次选修法"，必须新增用例证明报价中的"价格/门幅"不误逃逸 | 新增 |

**可合并性判定**：T1 与 G1 同一根因 ⇒ **合并为一条修法**，但**两组判据都要**（G1 的 A1/A2/A5 锁"卡答轮"；G3 的 C1-C4 锁"跨域动作词"）——它们各自能独立失败，删任一组都会漏一半。

---

## 5. G4（复核主会话线索）：`per_area` 加工项价格计算 **100% 走不通**

### 5.1 复核结论：**成立**（且比线索描述更严重）

| 环节 | 证据（origin/main） | 结论 |
|---|---|---|
| 工具 schema **无** `width/height/dimensions` | `app/tools/processing_item_manage.py:80-152`（properties = action/item_id/category_id/name/price/pricing_method/description/unit/processing_item_id/quantity:143/status） | agent **拿不到**传尺寸的参数 |
| 工具**从不**下发 `dimensions` | `processing_item_manage.py:696`（`_calculate_price`；payload 在 `:723-727`）= `{"processingItemId":…, "quantity":…}` | 后端必然收到 `dimensions=null` |
| 后端 **强校验** `dimensions` | `ProcessingItemService.java:310-318 calculateArea`：缺 `width`/`height` → `BusinessException.validationError("按面积计价需要提供 width 和 height 尺寸")`；调用点 `:248-253`（`per_area` 分支） | **每次必抛** → `AdminApiClient.post` 返回 `success=False`（`app/utils/http_client.py:218-234`）→ 工具返回失败 |
| 端到端可达性 | `read_only_actions` 含 `calculate_price`（`:75`）→ 不触发确认门禁，链路本身是通的 | 失败**唯一**原因就是缺 `dimensions` ⇒ **100% 确定性，非偶发** |

> **行号勘误（给主会话）**：线索里的 `processing_item_manage.py:541` 是**落后 61 提交的主工作区**行号；
> `origin/main` 上 `_calculate_price` 在 **`:696`**，payload 在 **`:723-727`**。两处代码体一致（已对比）。

### 5.2 是"独立缺口"还是与 AS-007 同族？

**判定：独立缺口（不同层、不同文件、不同判据）——不得合并修法；但同域且有真实交集，必须交叉记录。**

- **层级不同**：G4 是**工具层 schema↔后端契约断裂**（确定性、零 LLM 即 100% 失败）；
  G2/AS-007 是**引导层+断言层**（LLM 采样相关、可达）。按 §16.1「能由 L1 拦的不许流到 L2」，
  G4 **本可以且本应该**被 L1 契约层拦住。
- **真实交集（必须记）**：AS-007 的换货目标商品 `prod_eval_2699` 恰好**绑定了 `per_area` 加工项**
  `pi_eval_embroidery`（刺绣工艺 30 元/㎡，`mibao_eval_seed.sql:73-96`，`sort_order=4`）。
  ⇒ 若换货流程（或任何流程）走到"需要该加工项价格"的一步，agent 无论怎么问都会失败；
  这会让 AS-007 的「所选名称与**计价**写入换货方案汇总」这条 data_check 长期不可判定。
- **合并会掩盖什么**：若把 G4 并进 AS-007 的修法，修好工具很可能让 AS-007"看起来绿了"，
  从而**永久掩盖** §3.3 的 `processing_ask` 假红检测缺陷 ⇒ 必须分开。

### 5.3 最小修法（**注意**：不要按 `acceptance-protocol.md:225` 去修）

⚠️ **重要区分（本条最容易修错的地方）**：`docs/testing/acceptance-protocol.md:225` 与
`.github/cases/order.yml:639`、`tests/test_order_create_processing_quantity.py:7` 都写着
「`per_area` → `quantity` = 宽×高」。该口径**只适用于 order_create 路径**（该路径由 agent 自己算
`processing_info.processingItems[].quantity` 并作为 JSON 下发，后端只做 `unitPrice × quantity`）。
**`calculate_price` 端点走的是另一套契约**：后端从请求体的 `dimensions` 算 `area`，
再算 `unitPrice × area × quantity`（`ProcessingItemService.java:248-253`，`#3005` 注释明确
"`per_area` 传 1 或实际计数值"）。⇒

- ❌ 按 §225 传 `quantity=8.4` 去修：`dimensions` 仍为 null → **照样抛错**；即使补了 dimensions，
  会变成 `area × 8.4` = **双计**（30×8.4×8.4 = ¥2116.8，应为 ¥252）。
- ✅ 正确最小修法：给工具补 `width`/`height` 两个**必填（per_area 时）**参数并下发
  `dimensions={"width":w,"height":h}`，`quantity` 保持"计数值"语义（缺省 1）。

**爬阶梯结果**（YAGNI → 复用 → 最小实现）：

1. **YAGNI 不成立**：工具在 schema/prompt 里**宣称支持** `calculate_price`，
   且目录里存在 `per_area` 种子项 → agent 被问"刺绣多少钱一平/这个窗户绣花多少钱"时**必须**能答。
2. **复用**：`AdminApiClient.post` 已支持任意 JSON；`PriceCalculateRequest.dimensions` 已存在
   （`backend/admin-api/.../dto/PriceCalculateRequest.java`，`Map<String,BigDecimal>`）→ **不需要改 Java**。
3. **最小实现（3 处，单文件）**：
   - `processing_item_manage.py:143` 附近加 `width`/`height` property（描述里写明"per_area 计价必填"）；
   - `execute()` 签名（`:156-168`）加 `width: Optional[float] = None, height: Optional[float] = None`；
   - `_calculate_price`（`:696`）签名 + payload（`:723-727`）加 `dimensions`，并在 `per_area` 且缺尺寸时
     **前置 fail-fast**（清晰话术"按面积计价需要宽和高"），而不是把后端的 400 原样抛给用户。
4. **附带修正过期口径**：`acceptance-protocol.md:225` / `.github/cases/order.yml:639` 的表述
   应补一句限定（"**order_create 路径**：per_area → quantity = 宽×高；**calculate_price 端点**：
   另有 `dimensions` 契约，quantity 为计数值"）→ 否则下一个修的人还会踩 §5.3 的坑。
5. **明确不做**：❌ 不改 `ProcessingItemService.calculatePrice` 去"兼容 quantity 当面积"
   （与 #3005 的语义冲突 + 双计风险）；❌ 不加第二套并行解析（§Code-Minimalism / #3570 的教训）。

### 5.4 覆盖现状（为什么这条缺口一直隐形）

- **`calculate_price` 在用例库中零覆盖**：`grep -rn "calculate_price" .github/cases/*.yml` → **0 命中**；
  `tests/agent_eval/` 内亦无（只有 `backend/ai-agent-service/tests/*` 的单测，且**不传 dimensions 也被判绿**：
  `tests/test_tools_processing_item_manage.py:579-604` 只断言"缺 item_id/quantity 报错 + 端点正确"）。
- **它在"工具级"覆盖矩阵里永远看不见**：`processing_item_manage` 已有多条正向用例（PP-002/PP-006 走 create/query），
  所以 §14.5 的覆盖门禁（工具级）**恒绿**——这正是 PR #3589 §6.5「矩阵只到工具级、不到 action 级」指出的隐形机制。
- **既有 L1 契约门禁也拦不住它**：`tests/test_tool_payload_backend_contract.py` 的判据是
  "**payload 键 ⊆ 接收端可读键**"（`:1-14` 注释），拦的是"发了接收端不认识的键"，
  **不拦"接收端要有、工具没发"**（缺必填）。

### 5.5 可执行验收判据（G4）

| 判据 | 层 | 写法 | 现状 |
|---|---|---|---|
| **D1-1** | **L1（mock，零 LLM）** | `tool.execute(action="calculate_price", processing_item_id="pi_eval_embroidery", width=3.2, height=2.5)` → 断言 `mock_client.post` 的 payload 含 `dimensions == {"width":3.2,"height":2.5}` 且 `quantity` 为计数值（默认 1） | **红**（现无该参数/该键） |
| **D1-2** | **L1（schema↔签名契约）** | 断言 schema `properties` 含 `width`/`height`（防"加了参数但 LLM 看不见"） | 红 |
| **D1-3** | **L1（fail-fast）** | `per_area` 项缺 width/height → 工具**自己**返回 `success=False` + 中文话术，**不发起** HTTP（断言 `post.assert_not_called()`） | 新增 |
| **D1-4** | **L2 迭代档** | 新增用例（建议 `PP-007` 之后编号，`processing.yml`）：输入点名 `刺绣工艺` + 明确尺寸 → `must_succeed: [{tool: processing_item_manage, action: calculate_price}]` + `required_args[processing_item_manage].fields=[processing_item_id, width, height]` + `output_verify(totalPrice=240.00)`（30 元/㎡ × 3.2 × 2.5 = 240 = `unitPrice×area×1`） | 新增 |
| **D1-5** | L0（门禁射程） | **不**改 `test_tool_payload_backend_contract.py` 的全量判据（会过度建设）；改为在 §14.5 的覆盖矩阵里补 **action 级**统计（`tool:action`），使 `calculate_price` 的零覆盖变成**可见缺口**（该改进已在 #3589 §6.5 提出，尚未落地） | 新增 |

---

## 6. 待裁定依赖（**产品裁定项，本报告只登记，不改**）

### D1：`quantity` 类型宽度导致合法小数被截断

| 项 | 位置 | 事实 |
|---|---|---|
| 入参 DTO | `backend/admin-api/src/main/java/com/migao/admin/dto/OrderCreateRequest.java:88` | `private Integer quantity;` |
| 落库列 | `docs/sql/schema_full.sql:428` | `quantity INTEGER DEFAULT 1` |
| 影响 | — | 合法小数面积（如 8.4 ㎡ × 30 元/㎡ = ¥252）经 Jackson float→int **截断为 8** → ¥240，**少收 ¥12** |

**它阻塞了哪些用例的可复现性**：凡是"加工费 = 单价 × **非整数**数量、且数量经 order_create 下发"的用例
（`per_area` 类：本报告 §5 的刺绣工艺；以及任何 `per_meter` 非整数米数的用例）——
其**金额断言在口径上不可能稳定成立**（`order.yml:639-640/753/842` 的 `processingFee = Σ unitPrice×quantity` 与
`chat.yml:464` 记的「总额 ≠ Σ小计+加工费」是同一族现象）。⇒ 在裁定前，
涉及非整数数量的金额类断言应**显式标注为"受 D1 阻塞"**，不要反复归因给 agent。

**为什么不在本报告范围**：类型宽度是**契约/产品裁定**（影响对外 API 兼容性），
且按 §0 的层级它属**数据层**，需标准定义者裁定后再由实现包处理。

### D2：状态流转类 `db_verify` 缺 fetcher（阻塞 G1 的 A6）

现有 db_verify fetcher：`product_by_name`（只核对 `processing_item_configs`，见
`local_runner.py:3269-3281`）、`order_phone`、`order_items`、`employee`、`after_sales_ticket`、
`processing_order`、`user_memories`。**没有读"商品状态"的 fetcher** ⇒ G1 的 A6（`on_sale→off_sale→on_sale` 落库）
需先补 `product_status` fetcher（runner 归属包，`tests/agent_eval/local_runner.py`）。
**A6 不是 A1-A5 的前置**：A1-A3（L0/L1）+ A5（`must_succeed`）已足以判定 G1 修好；A6 属加分项。

### D3：`chat.yml:408` 注释的**正确读法**（防误读，主会话特别提醒）

`.github/cases/chat.yml:408` 那段注释：
> 「它绑定了 `per_area` 加工项刺绣工艺（30 元/㎡）→ **加工数量只能靠模型猜（8 vs 8.4）**，金额不可复现
> （首跑签名 `总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4`）」

- ✅ **它的语境是 CH-006 的"用例非确定性"**：`product_search` 默认 `ORDER BY created_at DESC`
  → 在叠加 B 端种子的栈里「第一款」落到 `prod_eval_2699`（**选错了商品**）→ 于是才牵扯到 per_area 与金额漂移。
  该注释的目的是论证"必须点名商品"（自包含化），**已经据此改完**。
- ❌ **它不是"整数截断 bug 的观测证据"**：注意 `加工费252.0 = 30 × 8.4` —— 说明那一跑**用的是 8.4**，
  恰恰**没有**被截断成 8；`总额≠Σ小计` 的差值是**另一个**现象（口径/字段不一致，见 D1 的影响栏）。
- ⇒ 请勿把 D1 的"截断"判定建立在这段注释上；D1 的依据是**代码与 DDL 的类型宽度**
  （`OrderCreateRequest.java:88` + `schema_full.sql:428`），**尚无生产/评测中的截断实例证据**（本报告如实标注）。

---

## 7. 任务包切分建议（按文件所有权，供 §17 并行派发）

| 包 | 文件（独占） | 覆盖缺口 | 说明 |
|---|---|---|---|
| **P1 路由** | `backend/ai-agent-service/app/graph/nodes.py`、`app/graph/skills/base_skill.py`（只加"发卡 skill"持久化几行）、`tests/test_graph_nodes.py` | G1 + G3（T1+T2） | **必须同包**：G1/G3 都改 `nodes.py`，拆开必冲突。`base_skill.py` 是热点文件，改动面须压到最小并回报冲突风险 |
| **P2 用例** | `.github/cases/product.yml`（PR-007 断言）、`.github/cases/aftersales.yml`（AS-007 断言） | G1 的 A5、G2 的 M2/M3/M4 | 改 case 的包**独占**生成物（`tests/agent_eval/eval_cases.py`、`docs/testing/mibao-verification-cases.md`），改后必须 `render_cases.py` |
| **P3 加工项工具** | `backend/ai-agent-service/app/tools/processing_item_manage.py` | G4 | 单文件、无 case 生成物依赖；补 `tests/test_tools_processing_item_manage.py` 用例（头部需 `# case_ids:`） |
| **P4 评测 runner** | `tests/agent_eval/local_runner.py` | G2 的 M1（`processing_ask` 文本分支）、D2（`product_status` fetcher） | runner 是多方争用文件，**独占**；M1 先做可立刻拿回判别力 |
| **P5 文档口径** | `docs/testing/acceptance-protocol.md:225`、`.github/cases/order.yml:639` 的表述限定（§5.3-4） | G4 附带 | 若 P2 已持有 `order.yml`，则并入 P2 以免同文件冲突 |

**并行度**：P1/P3 是代码包、P2/P4/P5 是资产/文档包 → 同时 ≤3 条**评测型**流水线（§17.2）；
本组里只有 P2 会触发真 LLM 评测。

---

## 8. 我无法确定或证据不足的点（如实列出）

1. **AS-007 run `34812509606` 得 0.75 的精确失败项**：**证据不足**。B 端 acceptance 步骤不上传 artifact
   （`REPORT.md` §1.2 原文「无 artifact」），我拿不到该 run 的逐轮轨迹。
   §3.3 的"`processing_ask` 文本分支假红"是**高可信推断**（机制确证 + 用例声明与实现不一致确证），
   但**没有**"那一次就是它"的直接证据 → 判据 B1 可先零成本证伪/证实该机制本身。
2. **R2 那一刻 `pending_interact_skill` 到底还在不在**：证据不足（服务端日志被 `tail` 截断）。
   §2.1 已证明**两种情形结论相同**（都因 L1「下单」落到 `order`），故不影响修法与判据；
   但若要写进回溯报告，需本地栈的完整日志（issue 自己也这么要求）。
3. **触发 G1 的"完整跨域词清单"**：我只证了 `下单`（确证）与 `订单/发货/物流/退货/退款`（按同一代码路径推断，
   **未逐一探针验证**）。建议实现时用探针脚本批量跑一遍 `_SKILL_DOMAIN_KEYWORDS` 全表，
   作为 L0 用例的参数化数据源（而不是我把推断词写进报告当事实）。
4. **AS-007 `pre_clean` 的 `price: 23.8` 是否失效**：**存疑，见 §3.5**。代码语义（精确相等 + 静默短路）确证，
   但该栈上重复商品从哪来**未定**；需要该 run 的 `🧹 pre_clean:` 与 `data=product_detail(...)` 两行日志。
5. **G4 的 per_area 是否在真实会话中已被用户触发过**：**未知**（无生产/评测会话证据）。
   本报告的"100% 走不通"是对**能力可达性**的确定性判定（代码级必失败），不代表业务侧已发生损失。
   若要定性为 P0/P1，需补一条真实重放（D1-4）看 agent 实际怎么回应这个请求。
6. **未做真 LLM 重放**（本机 docker/凭据/服务三缺，§1.3）⇒ 本报告所有 L2 级结论均引用既有 run，
   未新增采样。需要新采样时的命令（照抄可执行）：
   ```bash
   cd "/Users/guangzhen.zk/ai native/migao"
   gh workflow run xiaobu-acceptance.yml --ref main \
     -f persona=mibao -f tier=normal -f case_ids=PR-007,AS-007 -f fast=true
   ```
   ⚠️ 派发前确认 §17.2 的在跑评测流水线 ≤3（真 LLM 成本）。

---

## 附录 A：确定性探针（可复现，**未进 commit**）

保存为 `/tmp/probe_route.py` 后执行（用主工作区 venv 即可；**注意 `PYTHONPATH=.` 与 cwd 指向 worktree**）：

```bash
cd "<worktree>/backend/ai-agent-service"
PYTHONPATH=. <venv>/python /tmp/probe_route.py
```

```python
# /tmp/probe_route.py —— 前置：把 tests/conftest.py:20-39 的环境 setdefault 抄到文件头
import os
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("ADMIN_API_BASE_URL", "http://admin-api:8080")
os.environ.setdefault("SERVICE_TOKEN", "test-service-token")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nTESTKEY\n-----END PUBLIC KEY-----")
os.environ.setdefault("LOGISTICS_API_URL", "https://example.com/kdi")
os.environ.setdefault("LOGISTICS_APPCODE", "test-appcode")
os.environ.setdefault("SSE_TIMEOUT", "300"); os.environ.setdefault("SSE_PING_INTERVAL", "30")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from langchain_core.messages import HumanMessage
from app.router.rule_matcher import RuleMatcher
from app.graph import nodes

CONFIRM_R2 = "确认：商品名称=遮光窗帘；当前价格=¥168.00；当前状态=在售；操作=下架（改为停售，买家不可下单）"

def probe(pending, msg, intent="order_query", agent_type="mibao"):
    st = {"messages": [HumanMessage(content=msg)], "pending_interact_skill": pending,
          "route_decision": {"action": "full_agent"},
          "intent_result": {"intent": intent, "confidence": 0.9, "source": "classifier"},
          "session_id": "probe", "agent_type": agent_type}
    print(f"pending={pending!r} intent={intent!r} -> {nodes.route_by_intent(st)!r} "
          f"after={st.get('pending_interact_skill')!r}")

rm = RuleMatcher()
for m in ("把遮光窗帘下架", CONFIRM_R2, "再把它上架", "确认", "查一下库存"):
    r = rm.match(m)
    print(f"L1 {m[:16]!r:22} -> {getattr(r, 'intent', None) and r.intent.value!r} "
          f"kw={getattr(r, 'matched_keywords', None)}")
probe("product", CONFIRM_R2)                       # G1 复现：-> order, after=''
probe("order", "再把它上架", "product_inquiry")     # G3-T2 复现：-> order
print(nodes._get_intent_to_route("mibao"))
```

**为什么这类探针值得固化**：它把"引导层缺陷"从"要靠真 LLM 全旅程撞"降级为
`migao-dev-flow` §16.1 的 **L1 层确定性信号**（秒级、零 token）；G1/G3 的 A1-C4 判据可直接由它派生为单测。

---

## 附录 B：引用清单（按出现顺序）

- issue **#3557**（本报告关联，不关闭）
- `acceptance/2026-09-14/replay-triage/REPORT.md`（#3520）、`REPORT-3528-verify.md`（#3528 有效性校验）
- `acceptance/2026-09-14/bend-repro/REPORT.md` §2.2（AS-003：**同族观察但明确不许计入 #3557 证据链**，本报告遵此）
- PR #3589（#3568：AS-007 自包含化 + 解 skip）、PR #3625（#3571 能力自我否定族根治）、PR #3544/#3580（`must_succeed` 口径）
- `docs/testing/xiaobu-eval-tooling.md`（五层归因、§6.5 DB 审计）、`docs/testing/acceptance-protocol.md`（§1.2/§1.3/§3.1/§3.2/§3.6/§14.2 语义）
- `migao-dev-flow` §13/§14/§16/§17（行为体检、用例库演进、分层探测、并行修复）
