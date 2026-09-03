# B/C 端 Agent「问题澄清能力」强化调研

> 版本 v1.1 ｜ 2026-09-03 ｜ 场景：低学历用户 ×「随手发图」意图澄清
> 方法：① MIGAO 代码逐文件核实（backend/ai-agent-service，行号截至调研日）；② 外部一手资料调研（论文/官方文档/专利，URL 见文末）
> 性质：调研与方案设计文档，非实施清单。落地前请按行号二次核对（AI-TDD 红线：测试先行 + case_ids）。

> **实施追踪（v1.1）**：本文件为设计源头，落地进展在仓库以分支 + PR 形式推进。
> 已复核确认的代码事实见 §九（人工逐文件复核，修正调研期子代理偏差），
> 修复与实施状态以 `docs/design/agent-clarification-impl-log.md`（或对应 PR）为准。

---

## 一、结论速览（TL;DR）

**问题**：未来 B/C 端用户可能是初中/高中文化水平、不熟悉与 AI 对话的人。典型场景：用户随手发来一张图片（照片/截图/随手拍），图片与商户已有信息（商品库/面料/订单/客户记录）存在关联，但用户不会表达意图——需要 AI **推理候选意图 → 澄清求证 → 再行动**，而不是"识别即用"或连环反问。

**现状（代码核实）**：MIGAO 已有完整图片链路（上传 ≤3 张 → vision LLM 分析 → 跨轮缓存）和三类澄清雏形，但存在系统断层：

| 层 | 现状 | 一句话缺口 |
|---|---|---|
| 意图感知 | 路由/分类器只吃**文本**，图片在路由前被剥离（`nodes.py:222-229`） | 图零意图感知：纯图消息=空文本进 L2 |
| 图片理解 | vision prompt 是**开放描述**（"识别关键信息+回答问题+建议工具"），无结构化输出、无商户关联求证（`base_skill.py:861-869`） | 识别即用：从不求证"这张图对应哪个已有商品/订单/客户，用户想让我干什么" |
| 澄清形态 | 米宝 B 端 general 澄清=纯文字列选项且 **interact 未绑定**（prompt 要求 interact 但工具不在列表 → LLM 无法兑现）；小布 C 端有 choice/form 卡但无"意图候选澄清" | 无"理解卡片 + 2~4 个可点选候选意图"形态 |
| 状态记忆 | 无澄清状态机（stage 字段无人读写）；vision 结果不写入 entities；新图覆盖旧图 | 澄清轮次/待确认项无槽位，多图一诉求/图+订单组合求证无支撑 |
| 评测 | eval 只断言工具序列，无澄清质量断言 | 澄清"越用越准"无闭环 |

**业界共识（外部调研）**：① 澄清是**付费行动**——默认基于上下文做最优猜测并给求证入口，只在"高不确定 × 答错代价高"时打断；② 澄清用**"呈现理解 + 可点选选项卡"**（2~4 候选），不用开放文本框，不用连环问（用户约 1 轮耐心）；③ 澄清候选必须 **grounded 到商户知识库实体**（商品/订单/客户/面料词表），杜绝编造式发问；④ 文案面向低学历：中文短句、平实词、给例子不给定义、禁反问/术语、永远可反悔；⑤ KPI（澄清采纳率/澄清后任务成功率/打扰税）与数据回流从第一天设计。

**建议路径（详见 §6）**：Phase 1 意图级澄清协议（无图也受益，改动小）→ Phase 2 图片意图澄清卡（核心，复用 interact choice + pending_skill + vision 缓存 + SessionStateStore）→ Phase 3 评测闭环（cases/eval + 数据回流）。

---

## 二、背景与问题定义

1. **目标用户**：初中/高中文化水平。特征（HCI 文献共识）：不会组织语言表达目标、读长句/术语吃力、自由文本输入是最大门槛、需要"可见可选的下一条"。
2. **典型输入**：随手拍一张图（家纺成品/布料/窗户实拍/订单截图/商户已有商品照片），可能**完全不带文字或只带口语短句**（"这个""跟这个一样""老板你看"）。
3. **AI 必须做的推理**：图可能关联商户已有的哪个信息（商品库 SKU/面料/某客户订单/售后凭证），用户可能是想——找同款/比价/查这笔订单/复购/做售后/把素材建成商品（B 端）/按图算料。
4. **本文的"澄清"定义**（与现状区分）：
   - **字段收集式澄清**（现状已有，成熟）：建订单/建商品/建工单时缺字段 → 引导补充。这是"表单流程"，不是本文重点。
   - **意图级澄清**（本文核心，现状几乎空白）：用户输入（尤其图片）**模糊/多义/与商户已有信息疑似关联**时，AI 先呈现自己的理解、给出候选意图让用户点选确认，再进入对应流程。

---

## 三、现状盘点（代码已核实）

代码根：`backend/ai-agent-service/`（下称 AIS）。双 Agent：C 端小布（xiaobu，小程序消费者）+ B 端米宝（mibao，后台商家）。

### 3.1 澄清机制现状总览

| # | 机制 | 位置 | 触发条件 | 现状缺陷 |
|---|---|---|---|---|
| A1 | 低置信度重写为 general 兜底澄清 | `router/intent_router.py:19,22-27,111-128` | L2 分类 confidence<0.55 且非豁免意图 | 信号只有 confidence 一个标量，无"该不该澄清/澄清什么"结构化输出；分类只看文本，图零感知 |
| A2 | L1 关键词/正则"打平→交 L2"不硬猜 | `router/rule_matcher.py:156-213,100-101` | 多意图特异性打平 | 只裁决"走哪个 skill"，不裁决"要不要先澄清"；纯图消息文本空直接 return None |
| A3 | general 兜底 prompt 引导 | `graph/skills/general_agent.py:66`、`references/prompts/general.md:24-27`、`EXAMPLES-general.md:5-13,52-57` | 意图=general | 只覆盖"文字列选项"一种形态；无图片澄清引导；仅米宝 persona |
| A4 | 写操作 confirm 卡守卫 | `graph/skills/base_skill.py:1082-1095,545-569,521-542` | destructive/requires_confirmation 且无确认词 | 是"执行前确认"，不是"信息澄清" |
| A5 | interact 流程占位（pending_skill） | `base_skill.py:1129-1133`、`graph/nodes.py:173-208,520-556` | interact 已下发等用户操作 | 最接近澄清状态机的机制，但只存 skill 名，无澄清轮数/待确认字段/候选 |
| A6 | interact 组件三件套（choice/confirm/form） | `tools/interact.py:62-162,204-292` | 需用户从固定选项选/确认/补字段 | **仅 C 端 4 个 skill 绑定**；B 端 prompt 反复要求 interact 但工具未绑定 → LLM 无法兑现（G6） |
| A7 | 表单字段不齐的补充提问 | `customer_order_skill.py:31`、`customer_quote_skill.py:53`、`product_skill.py:43,88-93` 等 | 创建类流程缺字段 | 话术具体有示例，最成熟的一档；但只服务字段收集，非意图澄清 |
| A8 | B 端图片建品的"推理→批量确认" | `product_skill.py:73-79`、`references/prompts/product.md:36-53` | 图片+创建商品意图 | 唯一的"识别后求证"范式，但只服务建商品字段，且与 `EXAMPLES-product.md:83`（"识别结果直接预填不做二次确认"）自相矛盾（G7） |
| A9 | 转人工引导 | `graph/nodes.py:156-171,290-345`、`handoff_judge.py` | 负面情绪/多轮未解决等 | 与澄清正交，但会抢占澄清机会 |
| A10 | 图片分析失败兜底 | `base_skill.py:963-964` | vision LLM 失败/空结果 | 单句道歉，无"已看图但不懂意图"的澄清兜底（G12） |

### 3.2 图片输入链路与"识别即用"断层

**链路（事实）**：上传校验（`api/chat.py:1103-1136`，≤3 张，仅 https//api/files）→ 路由前文本化（`nodes.py:222-229` 剥图）→ 带图强制不走 direct_reply（`nodes.py:435-452,500-507` → general vision mode）→ skill 内 vision 分支（`base_skill.py:924-997`：清旧缓存 → 2 次重试 vision LLM 纯分析 → 分析文本作为 SystemMessage 注入 → 绑工具进 ReAct）→ 跨轮缓存（`memory/session_memory.py:788-849`，PG JSON 截断 3000 字；`base_skill.py:871-891` 次轮注入"你上一轮已分析…"）。

**唯一的全服务图片理解 prompt（`base_skill.py:861-869`）**：要求模型"1. 仔细观察识别关键信息 2. 根据用户提问结合图片回答 3. 有可操作信息可主动建议工具"。**开放描述，无结构化字段、无置信度、无商户关联求证指令。**

**断层证据（"识别即用"）**：
- 意图分类阶段完全不看图（`intent_classifier.py:218-232` 只留 text）→ 图片无法参与"商品咨询/售后/算料/关联订单/建品"判定；
- vision prompt 不含商户上下文与求证指令 → 模型默认把图当"当前话题直接输入"，从不先回答"图可能对应哪个已有信息、用户想干什么"再行动；
- C 端识别后直接"搜相似/引导算料"（`customer_product_skill.py:33-37`、`customer_general_skill.py:40-44`），唯一澄清点是材质不确定可问——没有"您发这张图是想…？"；
- B 端只有"建商品"属性求证（`prompts/product.md:36-53`），order/aftersales/customer skill prompt 无任何图片段；
- **无图向量/以图搜图/OCR 工具**，embedding 仅知识库且 RAG 已禁用；vision 结果从不写入 entities → "图=哪个订单/客户/商品"无召回保障，只能靠 LLM 拿分析文本去猜。

**一句话**：现有链路 =「识别即用」+ 唯一内建求证点是 B 端建商品属性 + C 端两句"不确定可问"。**"图片疑似关联商户已有信息 → 推理候选 → 选项式澄清 → 再动作"整段在代码与 prompt 里不存在。**

### 3.3 双端差异（影响方案设计）

| 维度 | 米宝（B 端商家） | 小布（C 端消费者） |
|---|---|---|
| 技能集 | order/product/aftersales/customer/staff/settings/data（knowledge 禁用）；fallback=general | customer_order/product/quote/aftersales/knowledge；fallback=customer_general |
| interact 组件 | **不可用**（8 个 skill tool_names 均无 interact，但 prompt 全文在要求它 → G6） | 可用：choice/form/confirm 均已绑定 |
| 澄清载体 | 纯文字列选项（`prompts/general.md:24`），confirm 守卫退化文本 | choice 卡 + form 表单 + confirm 卡 + 转人工卡 |
| 图片链路 | 仅建商品有属性推理段；其余域无图片 prompt | 商品/兜底 skill 有"识别→搜相似→引导算料"；售后收图但无 vision 描述段 |
| 语气 | 同事语气（`references/base/identity.md:7`"干练靠谱"） | 导购语气 + 大白话替换术语（`customer_quote_skill.py:46,50-56`"绝不直接抛术语"） |

---

## 四、缺口清单（面向低学历 × 图片意图澄清，12 项）

| Gap | 描述 | 证据（AIS/ 下文件:行号） |
|---|---|---|
| G1 | **图片零意图感知**：路由/分类只吃文本，纯图消息=空文本进 L2 | `graph/nodes.py:222-229`；`router/intent_classifier.py:218-232`；`router/rule_matcher.py:100-101` |
| G2 | **vision prompt 无意图/关联求证引导**：开放描述+直接回答，无"先判断用户想干什么、图关联哪些商户信息" | `graph/skills/base_skill.py:861-869,966-969` |
| G3 | **无"该不该澄清"显式判定点**：分析成功即无条件进 ReAct；澄清唯一入口是文本低置信 | `base_skill.py:963-998` ↔ `intent_router.py:111-128` 之间无澄清决定点 |
| G4 | **无澄清状态机**：SessionStateStore docstring 列了 stage 但全仓无人读写 | `memory/session_state_store.py:5,31-111`；`session_memory.py:666-784` |
| G5 | **无"引导式意图选项"**：米宝 general 澄清=纯文字要求说出需求；小布 choice 卡无预置意图澄清选项 | `general_agent.py:66`；`prompts/general.md:24-25` |
| G6 | **B 端 prompt↔工具不一致**：prompt/EXAMPLES 反复要求 interact，skill 未绑定 → 静默退化文本（而 EXAMPLES 又禁文本序号） | `product_skill.py:13-24 vs 26,38,43`；`prompts/product.md:24,27`；`EXAMPLES-product.md:100-107` |
| G7 | **图片建品话术自相矛盾**："先呈现结果让用户确认" vs "识别结果直接预填"→ 行为漂移 | `product_skill.py:75-77` vs `EXAMPLES-product.md:83` |
| G8 | **vision 输出无结构化契约**：无字段/无置信度；PROMPT-rules 要"低置信请用户确认"却无置信度可依 | `base_skill.py:946-949`；`references/PROMPT-rules.md:13` |
| G9 | **跨轮澄清上下文缺失**：vision 缓存只支持同一图后续追问，新图覆盖旧图 | `base_skill.py:871-891,930-934` |
| G10 | **vision 结果不进入实体/商户关联记忆**：entities 只从查询工具结果提取 | `memory/context_manager.py:389-452,218-229`；`nodes.py:96-132` |
| G11 | **澄清质量无评测**：eval 只断言工具序列/未调用；无"澄清≤N 轮成交""话术含可点选项"断言 | `tests/agent_eval/local_runner.py:203-254`；`.github/cases/chat.yml:76-100` |
| G12 | **低学历文案障碍层缺失**：澄清话术无难度分级、失败兜底无示例引导 | `base_skill.py:964,1048-1136`；`customer_quote_skill.py:46` 的大白话原则未推广 |

---

## 五、业界实践调研（外部一手资料，五方向摘要）

> 完整来源列表见 §8。以下结论尽量以"能直接指导 MIGAO 改动"的形式转写。

### 方向1：澄清提问研究脉络（什么时候问 / 问什么 / 怎么问）
- 经典基线 Rao & Daumé III（SIGIR 2019）：澄清确实改变检索结果，但**用户约只有 1 次提问耐心**——"预算内只问最必要的"。
- **澄清是付费行动**："Act or Clarify?" 显式建模不确定性敏感度 × 提问成本，成本低且不确定高才问；"benefit-or-disturb"（IPM）证明低质/过多澄清有**打扰税**，降满意度。
- 澄清问题最优形式：**grounded 到知识条目的具体问题 > 宽泛开放问句**；单轮 1 问；可点选。
- 工程范式：AGENT-CQ/ClariQ 的 **topic–facet** 化——先生成候选问题列表再挑最关键的 1 个；RAC（Retrieval-Augmented Clarification）用**检索到的上下文支撑澄清问题**（faithful），杜绝编造式发问。

**→ 对 MIGAO**：澄清触发不应只看 L2 confidence，应引入"图片关联商户库命中度"作为不确定性信号；候选意图/候选答案只能来自商品库/面料词表/订单/客户记录。

### 方向2：多模态（图片）意图消歧
- **图片角色先于消歧**：图=要买的商品 / 风格款式参考（找同款）/ 证据问题截图（订单物流售后）/ 待录入素材（建商品）。同一张图+不同文本意图，需要"角色判断"。
- "Do Images Clarify?"：图像降低部分模糊，但引入"图里有什么 vs 用户想要什么"新歧义 → **图必须结合文本意图与领域知识做 grounded 澄清**。
- Plug-and-Play Clarifier（AAAI）：输出**多候选意图 + 支撑证据**让用户选 = 多模态 check-back，与需求形态一致。
- 业界产品形态（US Patent 11836777B2 视觉搜索助理）："用户发图 → bot **陈述式理解 + 提问 + 候选答案选项**"；VOGUE/MMShopBench 证明电商"属性化澄清 + 真实日志基准"可测。

**→ 对 MIGAO**：落地形态 = 图片入站 → vision 结构化识别（类目/面料/款式/是否订单截图/是否商户已有商品）→ 检索商户库命中候选 → 输出"理解卡片 + 3~4 候选意图按钮（找同款/识别面料/查这笔订单/建商品/算料）" → 点选进子流程。**图为主假设、文本为约束。**

### 方向3：为低学历/低数字素养用户设计
- Medhi et al.（ACM TOCHI 2011）印度实证：**线性流程 + 大图标 + 选项/编号菜单显著优于自由输入**；自由文本是最大门槛。
- 语音同样要"选项式"（低数字素养老年人研究：用户不会自发组织指令，需要可见可选的下一步）。
- 认知负担控制：一次一件事、短句平实词、给例子不给定义、容忍口语/错别字/方言、"你是说…吗？"回显纠正、永远可反悔。
- **结构化引导式对话优于裸表单**（印度政务系统对照实验）→ 澄清表现成"引导收集"而非"弹表单"。

**→ 对 MIGAO**：所有澄清/求证话术遵守"1 问 1 屏 + 可点选 + 短句 + 术语翻译 + 示例 + 反悔出口"；把 C 端已有的大白话原则（`customer_quote_skill.py:46`）推广为共享层（修复 G12）。

### 方向4：澄清质量评测与闭环
- 核心维度是 **usefulness（可行动性）**：问题能从上下文推断且答案改变下一步 = 有用；评测别看文本相似度。
- 离线+在线双层：离线（澄清有用性、检索增益）+ 在线（采纳率、任务完成）；语音 WoZ 实测**澄清降任务失败率但增轮次 → 必须同计用户努力**。
- 工程主流：LLM-as-judge + 规则 rubric 给澄清轮次打分（ClarQ4LLM 把澄清建模为 Clarify/Request-Info 显式动作；AskBench 用 rubric 分数作 **RL 奖励信号 RLVR** 训练"何时问/问什么"）。
- **数据回流闭环**：每轮记录（上下文快照、候选、用户点选/重输/放弃、最终成功）→ 打分 → 失败样本进 few-shot 或 RL。

**→ 对 MIGAO**：eval 增断言族（修复 G11）：澄清采纳率、澄清→任务成功转化、打扰税（放弃/重输）、单任务澄清轮上限、超时兜底猜测成功率；cases 补澄清 yml。

### 方向5：可落地的工程形态（LangGraph 式 agent）
- 两条主流：**a) 显式图节点 + interrupt（human-in-the-loop）**（LangGraph interrupts 官方文档、OpenAI Agents SDK HITL）——流程可控，推荐客服场景；**b) "ask-user"工具由 agent 自主调度**（Spring AI AskUserQuestionTool、LangChain deepagents ask_user）。
- **结构化澄清（选项卡片）优于自然语言追问**：Google Conversation Design 的 suggestions/confirmations 官方模式即"可点选回显确认"。
- check-back（识别→呈现理解→求证）有直接背书（Plug-and-Play Clarifier、Google confirmations、Anthropic"把确认做成工作流显式一步而非塞 prompt"）。
- **澄清 grounded 化**：澄清节点上下文注入已识别实体候选（SKU/面料词表/订单号/客户记录），模型只能"出题"不能"编答案"。

**→ 对 MIGAO**：MIGAO 已是 LangGraph 状态图，但澄清走的是"对话内自然语言+ReAct"而非显式节点。落地时优先**复用现有 interact choice 卡 + pending_skill 会话连续性**形成"伪 interrupt"（后端不必引入真 interrupt 即可呈现：下发澄清卡 → 用户点选 → 消息经 pending_skill 回原 skill），这是成本最低的形态；若后续要做超时兜底/澄清轮数强约束，再引入显式澄清节点 + SessionStateStore 澄清槽（G4）。

### 对低学历场景最关键的 5 条设计原则（综合）
1. **默认直接做、只在"高模糊 × 答错代价高"时澄清**——先给"我猜你是想…对吗"式求证执行，禁止连环发问。
2. **澄清永远用"呈现理解 + 可点选选项卡"**（2~4 候选 + 图片/卡片标签），开放文本框仅兜底。
3. **一次一问；中文短句、平实词、给例子不给定义、禁反问/术语**；emoji/缩略图降读字负担。
4. **候选 grounded 到商户库实体**：模型只出题不编内容；图+文本不一致时以图为主假设、文本为约束。
5. **KPI 与数据闭环第一天就设计**：让澄清"越用越少而准"。

---

## 六、落地建议（结合 MIGAO 可复用资产，分三阶段）

### Phase 1：意图级澄清协议（改动小、无图也受益，先做）
1. **vision prompt 加"意图/关联求证"引导**（改 `base_skill.py:861-869` + 相应 EXAMPLES）：
   分析图片后必须输出一段"我的理解"，含：图里是什么（类目/面料/款式/是否商户已有商品截图）、用户可能要干什么（候选 2~3 个，**只从商户能力域出候选**：找同款/识别面料/查订单/售后/算料/建商品）、不确定点。删除/弱化"直接回答+建议工具"的默认行动倾向。
2. **澄清决策点**（修 G3）：在 vision 分析成功后、进 ReAct 前加轻量判定——文本明确（意图置信高）→ 直接做；文本模糊/纯图 → 走"呈现理解 + 求证"；复用现有低置信阈值思路扩展为"澄清信号"。
3. **澄清状态槽**（修 G4/G9）：`SessionStateStore` 加 `clarification` 槽（轮次/待确认项/候选/来源图 id），与现有 pending_skill 共存；澄清轮数上限（如 2），超限走最优猜测或转人工。

### Phase 2：图片意图澄清卡（核心形态）
1. **B 端绑定 interact**（修 G6）：product/order/aftersales/customer/general 等 B 端 skill 的 tool_names 加 `interact`，一次性消除"prompt 要求卡、工具不存在"的静默退化（顺带修 G7 话术矛盾：统一为"识别结果先呈现、批量确认/改"）。
2. **"理解卡片 + 候选意图"澄清卡**（修 G1/G2/G5）：
   - C 端小布：customer_general/customer_product 识别图后，用 interact choice 下发"您发这张图是想：A 找同款/推荐 B 量尺寸算料 C 问价格/买这款 D 售后问题 E 其他（说给我听）"，每项带描述。
   - B 端米宝：general/product skill 图片入站后，choice 下发"这张图我识别为 [X 面料/XX 商品/像某订单的商品]，您是想：A 建/录成商品 B 查它是不是我们已有商品 C 关联某订单/客户 D 其他"。
   - 候选意图文案遵循方向3原则（短句、大白话、可点）。
3. **候选 grounded 到商户库**：澄清前对商户库做轻量检索（product_search/customer_manage/order 相关只读查询或内存词表），把**命中结果作为候选卡片内容**注入；模型只组织候选列表不编造条目（修 G8 的方向：vision 输出附置信度与"商户库命中"字段）。interact choice 已支持 label/value/description + 分页 + 50 上限（`interact.py:148-225`），够用。
4. **点选后衔接**：澄清卡走现有 pending_skill + `__FORM__` 回填协议（`chat.py:941-1008`）→ 用户点选内容注入 LLM 继续，无需新前端协议（C 端已有交互事件渲染链路；B 端若前端无 choice 卡渲染需补，见风险 §7）。

### Phase 3：评测闭环
1. **cases/eval 增澄清断言族**（修 G11）：新 `.github/cases/` yml（如澄清采纳、澄清≤2 轮成交、纯图消息必出澄清卡而非直接下单、澄清候选含商户库命中），渲染 `eval_cases.py`；runner 加"澄清卡下发次数/采纳轮次/无猜测性写工具"断言。文件头按域声明 `# case_ids:`。
2. **双端对齐**：把 C 端大白话原则（`customer_quote_skill.py:46`）提升为共享 rules（修 G12）；澄清/回执话术难度分级 + 失败兜底带示例（"您也可以直接说：帮我把这个做成商品"）。
3. **数据回流**：澄清样本（上下文快照/候选/点选/放弃/最终任务）落库，人工抽查 + LLM-judge 打分（usefulness/打扰分），失败样本回流 EXAMPLES few-shot。

---

## 七、关键风险与约束

| 风险 | 说明 | 对策 |
|---|---|---|
| 澄清打扰税 | 澄清过多/低质反而降满意度（IPM） | 默认行动+求证优先；澄清轮上限 2；KPI 含打扰税 |
| B 端前端能力 | B 端 skill 从未绑 interact，admin-web 端 choice 卡渲染链路是否就绪需核实 | Phase 2 前先验证 B 端交互事件渲染（参考 C 端 sse onInteractive 实现）；若缺失需前后端一起排期 |
| vision 结构化改动的回归 | vision prompt/输出格式改动影响 C 端"搜相似/引导算料"既有行为 | 先加 eval 断言旧行为（识别→搜相似仍工作）再改；跑 `verify-all.sh gate` + `check-ui-regression.sh` |
| RAG 已禁用/无图向量 | "图→已存商品/订单"召回无技术底座（G10） | Phase 2 用关键词级轻检索 + vision 结构化字段命中（sku_code/名称/颜色），不依赖向量；后续再评估图向量 |
| 话术矛盾漂移 | EXAMPLES 内部自相矛盾（G7）会致模型行为不稳定 | 以"先呈现、批量确认"为准统一，删冲突反例，快照测试守护（`test_prompt_snapshots.py`） |
| 多租户/DB 迁移 | SessionStateStore 加字段需兼容存量 JSON | 新字段可选、读取兜底；走契约核对（CONTRACT-LEDGER） |

---

## 八、参考来源

### 方向1 澄清提问研究
- Rao & Daumé III, [Asking Clarifying Questions in Open-Domain Information-Seeking Conversations](https://arxiv.org/abs/1907.06554)（SIGIR 2019）
- [ConvAI3 / ClariQ: Generating Clarifying Questions for Open-Domain Dialogue Systems](https://ar5iv.labs.arxiv.org/html/2009.11352)
- [apple/ml-qrecc（QReCC 数据集）](https://github.com/apple/ml-qrecc)、[arXiv:2010.04898](https://arxiv.org/abs/2010.04898v2)
- [Disambiguation in Conversational QA in the Era of LLMs and Agents: A Survey](https://scirate.com/arxiv/2505.12543)（arXiv:2505.12543，scirate 镜像）
- [AGENT-CQ: Automatic Generation and Evaluation of Clarifying Questions…（ACM TOIS）](https://dl.acm.org/doi/full/10.1145/3809182)
- [A Survey on Asking Clarification Questions Datasets in Conversational Systems（UCL Discovery）](https://discovery.ucl.ac.uk/id/eprint/10180976/)
- [Learning to Ask: When LLM Agents Meet Unclear Instruction（EMNLP 2025）](https://aclanthology.org/2025.emnlp-main.1104/)
- [Act or Clarify? Modeling Sensitivity to Uncertainty and Cost（OpenReview）](https://openreview.net/forum?id=AfQZlBn0BR)
- [Asking Clarifying Questions: to benefit or to disturb users in web search?（IPM）](https://www.sciencedirect.com/science/article/abs/pii/S0306457322002771)
- [When and What to Ask: AskBench and Rubric-Guided RLVR（ACL Findings 2026）](https://aclanthology.org/2026.findings-acl.845/)
- [RAC: Retrieval-Augmented Clarification for Faithful Conversational Search](https://ar5iv.labs.arxiv.org/html/2601.11722)（[HAL 版](https://hal.science/ISIR/hal-05527527v1)）
- [Clarifying the Path to User Satisfaction（arXiv:2402.01934）](https://arxiv.org/abs/2402.01934)

### 方向2 多模态意图消歧
- [Plug-and-Play Clarifier: Zero-Shot Multimodal Framework for Egocentric Intent Disambiguation](https://arxiv.org/abs/2511.08971v1)（[AAAI 页](https://ojs.aaai.org/index.php/AAAI/article/view/38851)）
- [Do Images Clarify? Effect of Images on Clarifying Questions in Conversational Search（ACM）](https://dl.acm.org/doi/full/10.1145/3698204.3716464)
- [VOGUE: Multimodal Dataset for Conversational Recommendation in Fashion（ACM UMAP）](https://dl.acm.org/doi/full/10.1145/3774935.3806177)
- [MMShopBench: Real-Log Benchmark for Multimodal Multi-Turn Shopping Agents（ar5iv 镜像，官方页待核）](https://ar5iv.labs.arxiv.org/html/2607.29002)
- [Intelligent online personal assistant with multi-turn dialog based on visual search（US Patent 11836777B2）](https://patents.google.com/patent/US11836777B2/en)
- [Enhancing intent understanding for ambiguous prompt: human–machine co-adaption（Neurocomputing）](https://www.sciencedirect.com/science/article/abs/pii/S0925231225010872)

### 方向3 低学历/低数字素养用户
- Medhi et al., [Designing Mobile Interfaces for Novice and Low-Literacy Users](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/ToCHI2711_Medhi.pdf)（ACM TOCHI 2011）
- [Visual Conversational Interfaces to Empower Low-Literacy Users（IFIP/HAL）](https://dl.ifip.org/hal-01510535v1/datacite)
- [Google Conversation Design: Suggestions](https://developers.google.com/assistant/conversation-design/suggestions)、[Confirmations](https://developers.google.com/assistant/conversation-design/confirmations)
- [Bridging the Cognitive Gap: Voice-Enabled Community Chatbot for Older Adults（arXiv:2603.11303）](https://arxiv.org/abs/2603.11303v1)
- [Form-Based vs Conversational Interfaces for Public Service Access in India（ACL HCINLP 2025）](https://aclanthology.org/2025.hcinlp-1.6/)
- [Readiness-Centered AI in Practice（Springer）](https://link.springer.com/chapter/10.1007/978-3-032-11108-1_24)
- [Equitable health chatbot implementation roadmap（PMC/PLOS）](https://pmc.ncbi.nlm.nih.gov/articles/PMC11065243/)

### 方向4 评测与闭环
- [Online and Offline Evaluation in Search Clarification（ACM TOIS，NSF PAR）](https://par.nsf.gov/biblio/10580778)
- [ClarQ4LLM（IEEE）](https://ieeexplore.ieee.org/abstract/document/11372194)、[数据集 GitHub ygan/ClarQ-LLM](https://github.com/ygan/ClarQ-LLM)
- [Tri-Agent Framework for Evaluating and Aligning Question Clarification（KDD GenAI-Eval 2025）](https://kdd-eval-workshop.github.io/genai-evaluation-kdd2025/assets/papers/Submission%2010.pdf)
- [Spoken Conversational Search: Effect of System Clarifications on UX（JASIST）](https://dl.acm.org/doi/10.1002/asi.24974)
- [MAC: Multi-Agent Framework for Interactive User Clarification（NeurIPS 2025）](https://neurips.cc/virtual/2025/loc/san-diego/127976)

### 方向5 工程形态
- [LangGraph: Interrupts](https://docs.langchain.com/oss/javascript/langgraph/interrupts)、[LangChain Human-in-the-loop](https://docs.langchain.com/oss/javascript/langchain/human-in-the-loop)
- [OpenAI Agents SDK: Human-in-the-loop](https://openai.github.io/openai-agents-js/guides/human-in-the-loop/)
- [Spring AI: AskUserQuestionTool——Agents That Clarify Before Acting](https://spring.io/blog/2026/01/16/spring-ai-ask-user-question-tool)
- [langchain-ai/deepagents: ask_user.py](https://github.com/langchain-ai/deepagents/blob/2d665804131961dfa7e2849248047deec818e4ef/libs/code/deepagents_code/ask_user.py)
- [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)、[Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents)

> 说明：个别 2026 年条目（MMShopBench、arXiv:2601.11722、arXiv:2603.11303 等）经镜像/代理访问，官方页待二次核验；引用前请按需确认。代码行号截至 2026-09-03 调研日，实施前以实际代码为准。

---

## 九、代码复核记录（人工逐文件核实，2026-09-03）

> 目标「推进建议路径」的第一步：动手前把调研期子代理结论中**直接影响改动安全性的关键事实**逐一复核。标记 ✅=核实一致；🔧=与调研表述有出入，以本次为准。

| 调研项 | 结论 | 核实结果 |
|---|---|---|
| G6 B 端 prompt↔工具不一致 | product/order 等 B 端 skill 的 prompt 要求 interact，但 tool_names 不含 interact | ✅ 确认：`product_skill.py:13-24`（PRODUCT_TOOLS 无 interact）vs `product_skill.py:26,38,69-70`（prompt 要求 interact(choice)）；`references/prompts/product.md:24,27` 同。其余 B 端 skill（order/aftersales/customer/staff/settings/data）prompt **未**直接引用 interact（已逐文件 grep），受影响面主要是 product（建品/选加工项/SKU 场景）与 general（低置信澄清）。C 端 4 个 skill 均绑定 interact（`customer_*_skill.py` tool_names）。 |
| G6 连带：代码层 confirm 拦截指令 | base_skill 拦截未确认写操作时 message 指示 LLM "请调用 interact（component=confirm）" | ✅ 确认：`base_skill.py:1079-1095`。B 端 skill 若无 interact 工具，LLM 会收到 tool_not_found → 澄清能力退化。**该 message 是共享代码路径，B/C 端一致**。 |
| G7 图片建品话术矛盾 | product_skill.py "先呈现识别结果让用户确认" vs EXAMPLES "直接预填不做二次确认" vs prompts/product.md "先列出全部推理结果再一次性确认" | ✅ 确认三方表述不一致：`product_skill.py:75-79`（内联，先呈现+确认）、`references/prompts/product.md:30`（"直接预填表单，不要让用户重复输入"）+`:49-53`（"先列出全部推理结果，再让用户一次性确认或修改"）、`references/EXAMPLES-product.md:68,83`（"识别结果直接预填，不做二次确认"）。`prompts/product.md:30` 与 `:49-53` 本身也有张力（预填 vs 逐项确认）。实施需统一仲裁口径。 |
| Vision prompt 现状 | 开放描述，无结构化输出/置信度/商户关联求证 | ✅ 确认：`base_skill.py:861-869`（唯一全服务图片理解段）+`:966-969`（分析后注入）+`:946-949`（自由文本分析结果直接入上下文）。 |
| 图片路由 | 带图强制走 general（vision mode） | 🔧 部分修正：`nodes.py:500-507` 仅在 `action=direct_reply`（greeting/capabilities 等）时强制重定向到 `general`；**其余图片消息按意图正常路由到领域 skill**（如 product / customer_product），skill 内由 `base_skill.py:924-997` vision 分支处理。→ 澄清能力须建在 base_skill（两端共享）或各领域 skill prompt，而非只靠 general。 |
| 澄清状态载体 | SessionStateStore 有 stage 字段但无人读写 | ✅ 确认：`session_state_store.py` 通用 JSON；全仓 grep 无 stage 读写。现有会话连续性靠 `pending_skill`（interact 成功 → `base_skill.py:1129-1133` set；`nodes.py:173-208,520-556` 回原 skill）。→ 澄清卡可先复用 pending_skill 语义，无需立即上澄清状态机。 |
| interact 组件能力 | choice/confirm/form 三件套完整 | ✅ 确认：`tools/interact.py:62-162`（schema：choice options 含 label/value/description，form 含预填 value，confirm 含 confirmValue）、`:204-292`（组装）、`:220-225`（choice 上限 50）。choice 支持 pageMeta 分页（`:148-159`）。 | 
| SSE 交互事件通道 | interact 成功 → interactive 事件 | ✅ 确认：`api/chat.py:596-600`（`tool_name=="interact"` 且 success → `SSEEvent.interactive(component_type, data)`）；`api/sse.py:124-139`（event: interactive）。__FORM__ 表单回填协议：`api/chat.py:937-1008,1039-1041`（`__FORM__|{json}` → 注入 LLM 上下文）。 |
| vision_analysis 跨轮缓存 | 图分析结果可跨轮复用 | ✅ 确认：`memory/session_memory.py:788-849`（set/get/clear_vision_analysis，PG session_states JSON，截断 3000 字）；`base_skill.py:871-891`（次轮无图注入缓存）；`:930-934`（新图上传清旧缓存）。 |
| 写操作 confirm 确认词判定 | 明确确认词开头才放行 | ✅ 确认：`base_skill.py:511-542`（_CONFIRM_EXACT/_CONFIRM_PREFIX/_is_explicit_confirmation）。 |
| Prompt 分层组装 | identity/principles/PROMPT-rules/prompts/{skill}/inline/EXAMPLES 六层 | ✅ 确认：`base_skill.py:391-443`（_build_system_prompt）+ `_read_cached` 缓存（`:370-388`）。references/ 文件改动会被缓存——**运行时需重启/清缓存生效**；`backend/ai-agent-service/tests/test_prompt_snapshots.py` 守护 references 改动。 |
| 图结构 | START → intent_router →(条件边 route_by_intent)→ Skill → END | ✅ 确认：`graph/builder.py:104-124`。澄清若做成显式图节点需改 builder + nodes；若走"skill 内 LLM 自主调 interact choice"则无需改图。 |
| 双端 role/工具差异 | B 端 8 skill（order/product/aftersales/customer/staff/settings/data/general）；C 端 6 skill（customer_order/product/quote/aftersales/knowledge/general） | ✅ 确认：`agents/agents/mibao.py:14-24`、`agents/agents/xiaobu.py:34-42`；interact allowed_roles 含 admin/agent/tenant_admin/customer（`tools/interact.py:60`）→ 工具本身不拦 B 端角色。 |
| 前置条件：B 端前端能否渲染交互卡 | 调研风险表首项 | ⏳ 子代理核实中（B 端 admin-web 是否消费 interactive 事件；C 端 mini-app 渲染链路）。结论决定 G6 修复方向（绑 interact vs 前端补渲染）。 |

**复核结论**：调研报告的核心缺口（G1-G12）与"识别即用"判断在关键点上均成立；两处需在实施时按上表修正认知（图片并非一律走 general；受影响面集中在 product/general skill）。下一步修复顺序建议：G6（B 端 product/general 绑定 interact，前置依赖前端渲染结论）→ G7（统一图片建品话术仲裁）→ Phase 1 vision prompt 澄清引导（base_skill 共享层 + cases/eval 断言）。

---

## 十、实施进度（issue #2777，2026-09-03）

> 实施分支：`feat/2777-clarify-capability`（独立 worktree，与并行开发隔离）。测试先行 + case_ids 合规。

| 项 | 状态 | 落地位置 | 验证 |
|---|---|---|---|
| G6 修复：interact 落地 B 端 | ✅ 已提交 | `product_skill.py`/`order_skill.py`/`aftersales_skill.py`/`customer_skill.py` 的 tool_names 绑定 interact；契约测试 `tests/test_skill_routing_integrity.py`（test_prompt_required_interact_tools_are_bound / test_all_write_skills_bind_interact_via_confirm_guard） | 后端全量 2140 passed |
| 修复 1：B 端 store 透传缺口 | ✅ 已提交 | `frontend/admin-web/src/store/chat.ts` interactive case 补 confirmLabel/confirmValue/cancelLabel/cancelValue/pageMeta | `tests/unit/store/chat.test.ts` +2（68 passed） |
| G7 仲裁：图片建品话术统一 | ✅ 已提交 | `product_skill.py` Vision 预填段、`references/prompts/product.md`、`references/EXAMPLES-product.md`（"不做二次确认"旧措辞删除）；快照断言 `test_prompt_snapshots.py::test_product_image_create_wording_unified` | 快照 34 passed |
| Phase 1：vision prompt 澄清引导 | ✅ 已提交 | `base_skill.py` 新增 `VISION_CLARIFY_GUIDE` 常量 + 多模态注入；单测 `test_graph_skills.py::TestVisionClarifyGuide`（含纯文本路径不注入断言） | graph skills 30 passed |
| cases 补测 | ✅ 已提交 | `.github/cases/chat.yml` 新增 CH-018（图片意图澄清）/ CH-019（B 端交互卡可用），重渲染生成物 | truth check ✅（真值全解析） |
| 前置核实结论：B 端前端渲染 | ✅ 核实 | admin-web `InteractiveMessage.tsx` 组件/事件/测试俱在，非从零开发；仅 store 字段透传缺口（已修） | 前端子代理逐文件核实 |
| 后端全量 / 前端全量 / 三把工具 | ⏳ 验证中 | — | — |
| Phase 2（图片意图澄清卡 + B 端澄清候选）+ Phase 3（评测闭环） | ⏳ 后续 | 依赖本 PR 合并后 cases 提级与真实图 eval 支持（runner 发图能力未具备） | — |

---

## 十一、实施进度 Phase 2（issue #2789，2026-09-03）

> 实施分支：`feat/2787-clarify-phase2`（独立 worktree）。承接 §十 Phase 1（#2777/PR #2784 已合并）。

| 项 | 状态 | 落地位置 | 验证 |
|---|---|---|---|
| runner 澄清语义扩展 | ✅ | `tests/agent_eval/local_runner.py`：`direct_reply or interact` 组合期望支持（澄清卡与文本引导皆算澄清）；顺带修复「X 未被调用」反转断言被工具名子串匹配提前误判的 bug | 自测 9/9 |
| Phase 2a：B 端 general 澄清承载 | ✅ | `general_agent.py` GENERAL_TOOLS 绑 interact + 内联 prompt 澄清引导升级；`prompts/general.md` + `EXAMPLES-general.md`（choice 候选卡示例） | 契约测试 test_general_binds_interact_for_clarify_cards + prompt 快照 |
| 修复 main 既有快照漂移 | ✅ | `test_prompt_snapshots.py` 长度边界上调（product 9586 由 #2784+#2785 累积；general 5465 由本 PR 澄清引导增长）——测试文档明示"故意改动→更新 expected" | 快照 38 passed |
| Phase 2b：C 端图片澄清候选 | ✅ | `customer_product_skill.py`/`customer_general_skill.py` 图片段：意图不明→interact choice 候选卡（找同款/识别面料/量尺寸算料/查订单/售后咨询），**不默认直接搜相似** | prompt 契约测试 4 条 |
| cases 更新 | ✅ | CH-003 期望放宽为 `direct_reply or interact`（澄清卡或文本皆可）；新增 CH-020（C 端随手发图→候选意图卡） | render 157 条 + truth check ✅ |
| 后端全量 / 三把工具 | ✅ | — | 2160 passed / gate、UI、contract 全绿 |
| Phase 2c：澄清候选 grounded 商户库（图→疑似实体检索注入） | ⏳ 后续 | 依赖以图搜图/OCR 底座（G10）；当前由 VISION_CLARIFY_GUIDE"不得编造图片不存在信息"prompt 层约束 | — |
| Phase 3（澄清 KPI 评测闭环 + runner 发图能力） | ⏳ 后续 | agent-eval runner 需支持 images 入参 + case schema images 字段 + 公网测试图 | — |

---

## 十二、实施进度 Phase 3 前置（issue #2794，2026-09-03）

> 实施分支：`feat/2791-clarify-eval-images`（独立 worktree）。打通 agent-eval 图片消息能力。

| 项 | 状态 | 落地位置 | 验证 |
|---|---|---|---|
| runner 图片支持 | ✅ | `tests/agent_eval/local_runner.py`：send_message 增 images 入参（body 透传后端 ChatSendRequest.images）；run_case 轮次支持 str/dict（{text, images}）混合 | 自测（纯文本不带 images/带图透传/轮次解析） |
| case schema 扩展 | ✅ | `.github/cases/*.yml` user_inputs 每轮可为 dict；render_cases EvalCase 注释 + md 渲染兼容（📷 附图数）；旧 str 形态 157 条全部兼容 | YAML 加载 158 条 |
| 端到端图片用例 | ✅ | CH-021：真实发图（picsum seed 图）→ vision 链路（澄清/识别不报错），期望 interact or product_search or direct_reply（三元 or，runner Phase 2 已支持） | 期望自测 4/4 |
| 守护脚本 | ✅ | `tests/agent_eval/selftest_images.py`（非 test 命名防 gate 误判）：send_message/run_case/YAML 三段自测 | venv python3.11 全绿 |
| 三把工具 | ✅ | — | gate / UI / contract 全绿 |
| 剩余：真实图 CI 触发 + 澄清 KPI 回流 | ⏳ 后续 | CH-021 tier normal 需手动/定时 agent-eval 触发；澄清样本落库评测属 Phase 3 后半 | — |

---

## 十三、实施进度 G4 澄清轮次护栏（issue #2796，2026-09-03）

> 实施分支：`feat/2796-clarify-round-guard`。承接调研 §6 Phase 1 第 3 点（澄清轮上限）与 §11 G4。

| 项 | 状态 | 落地位置 | 验证 |
|---|---|---|---|
| 纯函数状态机 | ✅ | `app/graph/clarify_guard.py`：judge_clarify / tick_clarify / should_force_example（澄清轮 +1、实质轮清零、上限封顶、force_example 标记） | 单测 17 例 |
| 异步守卫 | ✅ | `apply_clarify_guard`：SessionStateStore `clarify` 键持久化；连续澄清 ≥2 轮后改写路由为 direct_reply（CLARIFY_FORCE_EXAMPLE_TEXT：具体示例 + 转人工出口）；存储异常降级不阻断 | 单测（含端到端序列：轮1/轮2 给机会→轮3 兜底→实质轮清零） |
| 意图路由挂点 | ✅ | `nodes.py` intent_router_node：route() 后、D3 前——低置信重写 general（source=low_confidence）即澄清轮，接入守卫 | 受影响组 169 passed |
| 兜底话术 | ✅ | CLARIFY_FORCE_EXAMPLE_TEXT：低学历友好（①查订单 ②搜商品 ③算料 示例 + 转人工出口） | 断言含示例与出口 |
| 行为用例 | ✅ | CH-022（连续模糊→兜底示例）+ 渲染 159 条 + truth check | gate ✅ |
| 设计语义 | ✅ | 达上限的"本轮"仍正常澄清（用户最后机会），下一轮仍模糊才兜底——不激进打断 | 序列测试 |

---

## 十四、实施进度 Phase 2c 轻量版 grounded（issue #2799，2026-09-03）

> 实施分支：`feat/2799-clarify-grounded`。承接 §7 风险表方向：关键词级轻检索，不依赖向量/OCR（G10 全量版后续）。

| 项 | 状态 | 落地位置 | 验证 |
|---|---|---|---|
| 关键词提取纯函数 | ✅ | `app/graph/clarify_grounded.py`：extract_search_keywords（面料材质/颜色/风格，去"色"、行业色号、停用词过滤、去重上限）/ pick_primary_keyword（材质优先） | 单测 10 例（含边界：无命中/停用词/多色） |
| grounded 检索引导 | ✅ | `base_skill.py` VISION_CLARIFY_GUIDE 追加第 6 条：商品类候选先按图片特征调 product_search 命中真实商品作候选（名称+价格），无命中如实说明不编造 | 契约测试 TestVisionGroundedGuide |
| 行为用例 | ✅ | CH-023（图片澄清候选 grounded）+ 渲染 161 条 + truth check | gate ✅ |
| 三把工具 | ✅ | — | gate / UI / contract 全绿 |
| G10 全量版（图向量/OCR 底座） | ⏳ 后续 | 依赖向量检索/OCR 基础设施投入 | — |
