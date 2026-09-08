# 企业级 LLM WIKI 知识板块设计（词条化 + AI 提炼 + 行业模板）

> 版本 v1.1 ｜ 2026-09-08 ｜ Issue [#3051](https://github.com/zhaokai-mgzn/migao/issues/3051)
> 性质：功能板块设计文档（单一事实源）。实施按 §十四 Phase 1~9 推进，全部 AI-TDD（测试先行 + case_ids）。
> 背景决策：RAG（DashVector + 切块检索）维持下线（决策 D1，2026-08-29）。本设计以「**词条**」为知识单元，
> 检索用「结构化过滤 + 关键词匹配」，**不引入向量库**；「知识是生成的，不是检索的」。
> **v1.1（2026-09-08）**：**LLM WIKI 完全替代旧知识库**——RAG 文档模型（表/实体/Mapper/Controller/前端/文档/用例）整体移除，非并存；新板块必须**闭环**（词条生命周期/提炼采纳/检索使用全链路无死端）且**自洽**（schema/契约/文档/生成物一致，无孤儿引用）。

---

## 一、结论速览（TL;DR）

**问题**：中小商户几乎没有自己的知识文档，RAG「先有文档、再切块检索」的前提不成立（决策 D1 已下线）。
客服知识问答目前走 LLM 通用知识 + 免责，无租户定制能力，无法回答「本店」事实（价格、加工项、售后政策）。

**方案**：LLM WIKI **完全替代**旧知识库——以「**词条模型**」为唯一知识模型（非与文档模型并存），四层知识供给：

| 层 | 供给方式 | 知识单元 | 谁产生 |
|---|---|---|---|
| L1 行业模板 | 平台预置模板一键套用 | 行业通用词条（面料/测量/FAQ） | 平台（种子数据已存在，需结构化 + 丰富） |
| L2 商品/配置派生 | 商品/加工项/配置数据 → 自动生成词条 | 本店事实词条（价格/规格/计价方式） | 系统自动（商品数据即知识源） |
| L3 会话提炼 | 客服会话 → AI 提炼候选词条 → 人工一键采纳 | 本店经验词条（高频问答/售后话术） | AI 提炼 + 商家确认 |
| L4 文档提炼 | 上传文档 → AI 提炼候选词条 → 人工一键采纳 | 本店文档知识 | AI 提炼 + 商家确认 |

**运行时**：AI 客服知识问答按「词条检索（精确/关键词）→ LLM 通用兜底」两级走；词条回答**优先、可溯源、租户隔离**。
**无向量库**：词条量级几百~几千条，PG 结构化过滤 + 关键词匹配足够，租户隔离沿用 MyBatis 拦截器 + 显式 eq（吸取审计 07 P1-6 `.or()` 教训）。
**替代边界**：旧 RAG 知识库（`knowledge_documents` / `rag_chunks` / `knowledge_sync_history` / 文档 CRUD API / 知识库文档页）**全部移除**，见 §三·五 移除清单。

---

## 二、背景与问题定义

1. **RAG 对 SME 不成立**（本板块立项根因）：RAG 的前提是有一坨可切块的文档；中小商户没有。实测证据：决策 D1 下线后知识问答退回 LLM 通用知识，无本店事实能力。
2. **客服会话是 SME 唯一稳定存在的知识原料**：「聊天是入口，Wiki 才是产品」——人工客服在系统里答过的问题，就是本店最高价值的知识，当前**零沉淀**。
3. **商品/配置数据已经是知识**：商品名/价格/加工项计价方式/售后配置存在系统里，当前 AI 只做实时查询、不做知识化，导致「这个窗帘多少钱」类问题依赖工具逐次查询而非稳定话术。
4. **行业通用知识可预置**：`knowledge_base/` 已有 3 份种子数据（窗帘 FAQ/商品/测量），当前是 Markdown 文档形态、未进系统、未按行业结构化。

## 三、现状（代码核实，行号截至 2026-09-08）

| 项 | 现状 | 文件 |
|---|---|---|
| 数据模型 | `knowledge_documents`（title/doc_type/category/content/embedding_status/dashvector_collection）+ `rag_chunks` + `knowledge_sync_history`，RAG 时代形态 | `docs/sql/schema.sql:296-345` |
| 后台 API | 文档 CRUD + embed 重置（仅置 pending）+ 同步历史 + test-search（LIKE 检索，含 `.or()` 租户隔离修复） | `KnowledgeController.java` |
| Agent 侧 | `customer_knowledge_skill` 零工具模式（LLM 通用知识 + 免责）；`knowledge_search/knowledge_manage` 工具未注册（RAG 禁用） | `customer_knowledge_skill.py`；`registry.py` |
| 前端 | 知识库页：文档列表/上传/resync/删除/test-search/同步历史弹窗 | `frontend/admin-web/src/app/(dashboard)/knowledge/page.tsx` |
| 种子数据 | `knowledge_base/curtain_faq/faq.md`、`products/product_catalog.md`、`size_guide/measurement_guide.md`（Markdown，未结构化） | `knowledge_base/` |
| 相关领域 | 商品 SKU 矩阵 + 加工项（pricingMethod: per_meter/per_set/fixed/per_area，契约 §六）+ 租户 AI 配置（V10） | `CONTRACT-LEDGER.md` |

## 三·五、旧知识库完全移除清单（替代边界，v1.1）

LLM WIKI **完全替代**旧知识库：以下组件整体移除，不留并存、不留孤儿引用（grep 全仓核销）。

| 层 | 移除项 | 替代/动作 |
|---|---|---|
| 数据 | `knowledge_documents` / `rag_chunks` / `knowledge_sync_history` 三表 | V36 迁移 DROP（rag_chunks → knowledge_documents → knowledge_sync_history 顺序）；`docs/sql/schema.sql`/`schema_full.sql` 同步删除 |
| 后端实体 | `KnowledgeDocument` / `KnowledgeChunk` / `KnowledgeSyncHistory` | 删除 |
| 后端 Mapper | `KnowledgeDocumentMapper` / `KnowledgeChunkMapper` / `KnowledgeSyncHistoryMapper` | 删除（`SecurityConfigTest` 若引用同步清理） |
| 后端 Controller | `KnowledgeController`（文档 CRUD/embed/test-search/同步历史） | 删除，由 `KnowledgeEntryController`（词条 CRUD/检索/候选队列）替代 |
| 前端 API | `api.ts` knowledgeApi 文档方法（upload/resync/search/sync-history） | 替换为词条/候选/模板方法 |
| 前端页面 | 知识库页文档上传/同步历史 UI | 改造为词条管理/待采纳/模板 Tab（见 §十一） |
| 前端测试 | `frontend/admin-web/tests/unit/pages/knowledge.test.tsx` | 重写为词条页测试 |
| 后端测试 | `KnowledgeControllerTest`（文档端点 IDOR） | 删除，由 `KnowledgeEntryControllerTest` 覆盖 |
| 冒烟测试 | `ControllerSmokeTest` 中知识库端点断言 | 改为词条端点断言 |
| Agent | `registry.py` 知识工具禁用注释 / `SKILL-customer_knowledge.md` RAG 优先描述 | 改为词条检索工具 + 词条优先描述（Phase 7） |
| 用例 | `API-008`（RAG 降级）/ `API-011`（同步历史）→ 已过时 | 从 `.github/cases/api.yml` 删除或标注 removed，重渲染生成物 |
| 文档 | README 知识库(RAG) 说明、`docs/wiki/Home.md`、`AI-Agent.md` RAG Pipeline 节、`api-reference.md` §5.5、`rag-architecture.md`、`Database.md` 知识库行、`mibao-verification-cases.md` | 按现状改写为词条模型描述；`rag-architecture.md` 归档为历史 |
| 种子数据 | `knowledge_base/*.md`（Markdown 文档形态） | 结构化迁移为 `knowledge_base/templates/curtain/` 词条模板（Phase 3），原 md 删除 |
| CI 模板 | `.github/templates/knowledge-ai.yml`（若引用旧工具） | 按词条检索更新 |

**移除验收标准**：全仓 `grep -rn "knowledge_documents\|rag_chunks\|knowledge_sync_history\|KnowledgeDocument\|KnowledgeChunk\|KnowledgeSyncHistory"`（排除历史审计文档）为 0；`docs/sql/schema.sql` 无三表；三模块测试全绿。

## 三·六、闭环与自洽保证（新板块铁律，v1.1）

> 旧知识库的教训：`knowledge_sync_history` 曾被审计发现「表/实体/Mapper 就绪但**零读写**」（issue #2971）——功能没闭环。新板块把「无死端」作为验收前置。

**闭环一：词条生命周期**。`draft → pending_review → published → archived`（+ 编辑版本递增）每个状态都有 API 动作与 UI 入口；published 词条一定可被 `entries/search` 检索到（自洽测试断言：发布后可查、归档后不可查）。

**闭环二：提炼采纳流**。`会话/文档 → candidate（pending）→ 采纳/编辑后采纳 → entry（published）→ 可检索`；拒绝必须记 `status_note`。待采纳队列 UI 必须有读路径（列表）与写路径（采纳/编辑/拒绝）——**不重复 knowledge_sync_history 零读写事故**。

**闭环三：检索-会话飞轮**。`词条 → knowledge_search 命中 → 客服回答 → 会话结束 → 提炼候选 → 采纳 → 新词条`——会话沉淀持续反哺词条库，形成知识增长闭环。

**闭环四：替代闭环（无孤儿）**。旧知识库每层移除项都有核销点（grep 归零 + 测试断言），禁止「表删了实体还在 / API 删了前端还在调用 / 文档还宣称 RAG」的中间态；同一提交内后端+前端+文档同步移除。

**自洽保证**：schema.sql ↔ V35/V36 迁移 ↔ 实体字段 ↔ CONTRACT-LEDGER 枚举 ↔ 前端类型 ↔ Agent 过滤条件五方一致；每次改 `.github/cases/` 必跑 `render_cases.py` 并提交生成物（CI 新鲜度校验）；`contract-check.sh` 三端字段对齐。

## 四、总体架构：四层知识 + 检索链路

```
┌─────────────────────────── 运行时检索（Agent knowledge_search） ───────────────────────────┐
│  入参 query [+productId/category]                                                          │
│  ① 结构化过滤：tenant_id + is_active + status=published（租户隔离强制）                      │
│  ② 关键词匹配：title / keywords / question / answer（租户内 LIKE，title 命中优先）            │
│  ③ 变量填充：命中词条含 variables 模板 → 用商品/配置数据填充（如 {{price}} → 128 元/米）      │
│  ④ 未命中 → LLM 通用知识兜底（现 customer_knowledge 行为，保留免责）                         │
└────────────────────────────────────────────────────────────────────────────────────────────┘
     ▲                                ▲                              ▲
  L1 模板词条                     L2 派生词条                  L3/L4 人工确认词条
  （平台预置，按行业）           （商品/加工项/配置）         （会话/文档提炼 + 采纳）
     │                                │                              │
 knowledge_entries（租户内词条表，统一存储，source_type 标记来源）
     │
 knowledge_candidates（提炼候选队列：AI 提炼 → 商家采纳/编辑/拒绝）
```

**核心不变式**：所有词条落 `knowledge_entries`，租户隔离；提炼流统一进 `knowledge_candidates` 待采纳队列，**AI 只产生候选，发布权在商家**。

## 五、数据模型设计

### 5.1 词条表 `knowledge_entries`（替代 RAG 文档模型成为知识主表）

```sql
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,              -- 词条标题（如「雪尼尔面料会起球吗」）
    category VARCHAR(64),                      -- 分类：faq/product/measure/aftersale/config
    industry VARCHAR(64) DEFAULT 'curtain',    -- 行业（curtain=布艺，模板标识）
    source_type VARCHAR(32) NOT NULL,          -- template/product/config/conversation/document/manual
    source_ref VARCHAR(128),                   -- 来源引用：模板ID/商品ID/会话ID/文档ID
    question TEXT,                             -- 常见问法（提炼流产出，人工可改）
    answer TEXT NOT NULL,                      -- 标准回答/话术（变量模板，如 {{price}}）
    keywords TEXT,                             -- 逗号分隔关键词（轻量检索用）
    apply_products JSONB DEFAULT '[]',         -- 适用商品范围（可选）
    variables JSONB DEFAULT '{}',              -- 变量模板声明（L2 运行时填充）
    status VARCHAR(32) DEFAULT 'draft',        -- draft/pending_review/published/archived
    version INTEGER DEFAULT 1,                 -- 版本号（编辑递增）
    review_note TEXT,
    created_by VARCHAR(64),
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_tenant ON knowledge_entries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_status ON knowledge_entries(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_category ON knowledge_entries(category);
```

### 5.2 提炼候选表 `knowledge_candidates`

```sql
CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    source_type VARCHAR(32) NOT NULL,          -- conversation/document/product/config
    source_ref VARCHAR(128),                   -- 会话ID/文档ID/商品ID
    suggested_title VARCHAR(255) NOT NULL,
    suggested_answer TEXT NOT NULL,
    suggested_category VARCHAR(64),
    suggested_keywords TEXT,
    confidence NUMERIC(4,3),                   -- 提炼置信度 0~1
    evidence TEXT,                             -- 提炼依据（会话摘录/文档原文片段）
    status VARCHAR(32) DEFAULT 'pending',      -- pending/adopted/edited/rejected
    status_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_tenant ON knowledge_candidates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_status ON knowledge_candidates(status);
```

### 5.3 行业模板

- **v1 不做模板表**：模板以结构化文件存放 `knowledge_base/templates/<industry>/`（JSON，字段对齐 knowledge_entries），「模板目录」接口读取文件列表，「一键套用」接口把模板词条复制进租户（`source_type=template`, `source_ref=模板ID`）。
- 模板文件 = `{template_id, industry, name, version, entries: [{title, category, question, answer, keywords}]}`。
- 理由：模板是平台资产、低频变更，文件 + Git 版本管理最省；模板市场 UI 直接读目录即可。若未来需要跨租户共享/交易再升级为表。

## 六、L1 行业模板体系

1. 把现有 3 份 Markdown 种子数据**结构化迁移**为 `knowledge_base/templates/curtain/` 下的 JSON 模板（FAQ/商品/测量合并为一个布艺模板，词条粒度拆分，每 Q 一条）。
2. **丰富模板**：补齐布艺行业高频词条（加工项计价、下单流程、发货周期、定制规则、售后保修——对齐现有 FAQ 覆盖域并补缺）。
3. 模板套用 API：`POST /api/admin/knowledge/templates/{templateId}/apply` → 校验租户未套用 → 复制词条（重复标题跳过或覆盖策略 v1 取「跳过」）→ 返回套用统计。
4. 模板目录 API：`GET /api/admin/knowledge/templates`（平台资产，只读）。

## 七、L2 商品/配置派生词条（替代 RAG 的本店事实层）

**机制**：商品/加工项/配置是结构化的，直接**生成词条**而非检索。

- 触发：① 商品创建/更新/上下架时同步派生（admin-api 内同步调用派生服务）；② 定时全量对账（补偿漏触发）。
- 派生规则（v1 最小集）：
  - 每个上架商品生成词条：标题「{商品名}多少钱/价格」，answer 模板引用 SKU 价格变量，`variables: {"skuPrices": ...}`；
  - 每个加工项生成词条：标题「{加工项名}怎么计价」，answer 按 pricingMethod 模板（per_meter/per_set/fixed/per_area）；
  - 租户 AI 配置（V10 表）生成「店铺配置」词条（发货周期/售后说明，若字段存在）。
- 运行时变量填充：检索命中含 `variables` 的词条 → 用商品实时数据填充 → 保证与商品页一致（真值一致性）。
- 派生词条 `source_type=product/config`，**人工可改**；商品变更时重新生成该商品词条（保留人工修订则跳过——v1 简化：商品词条一律重新生成，人工修订词条需改 source_type=manual）。

## 八、L3 会话提炼（本板块差异化核心）

1. **触发**：会话结束后（人工会话关闭 / AI 会话结束），后台定时扫描 + 管理端手动触发接口 `POST /api/admin/knowledge/distill/conversations`。
2. **提炼**：取会话消息文本（≤ 最近 N 条，脱敏 PII）→ LLM 提炼为候选词条列表（`{title, answer, category, keywords, confidence, evidence}`），多条候选分条写入 `knowledge_candidates`。
3. **防噪**：① 仅提炼「知识类问答对」（人工客服的 A 段、AI 命中过的知识段）；② 重复候选按 (tenant_id, title) 去重（已有词条或待采纳候选跳过）；③ 单会话提炼上限（如 ≤5 条/会话）。
4. **采纳流**：管理后台「待采纳队列」→ 采纳（转 entries, status=published）/ 编辑后采纳（转 entries, status=published, 记录 edited）/ 拒绝（记 status_note）。
5. **闭环**：候选 → 采纳 → 词条生效 → 后续检索命中 → 可溯源（词条 source_ref 指向会话）。

## 九、L4 文档提炼

1. 复用现有文档上传入口（`knowledge_documents` 保留作「资料夹」），上传/编辑后触发提炼。
2. 提炼：取文档内容（文本截断上限）→ LLM 提炼候选词条 → `knowledge_candidates`（`source_type=document`）。
3. 定位：**文档→词条提炼**，不是文档→切块检索；资料夹原文仅作 evidence 保留，不参与运行时检索（v1）。

## 十、Agent 检索链路（knowledge_search 重启用）

1. 重注册 `knowledge_search` 工具（移除 RAG 禁用注释），语义改为「**词条检索**」：
   - 入参：`query`（必填）、`product_id`/`category`（可选）
   - 出参：词条列表（title/category/answer 填充后）
2. 实现：ai-agent 调 admin-api `GET /api/admin/knowledge/entries/search`（或走 internal 端口），租户隔离由 admin-api 强制。
3. `customer_knowledge` skill 的 system prompt 改为：**先调 knowledge_search，命中则基于词条回答（标注「📖 来自本店知识库」），未命中才用 LLM 通用知识 + 现有免责**；知识库命中词条时**禁止编造**词条之外的店铺事实。
4. 约束：词条检索结果 ≤3 条进上下文；answer 超长截断；变量未填充时提示「价格请以商品页为准」而非编造。

## 十一、前端改造（知识库页）

知识库页改造为 Tab 结构（保留 `/knowledge` 路由与权限码 `knowledge:manage`）：

| Tab | 内容 |
|---|---|
| 词条管理 | 列表（标题/分类/来源/状态/版本）+ 筛选（分类/来源/状态/关键词）+ 新建/编辑/发布/归档 + 来源徽标（模板/商品/会话/文档/人工） |
| 待采纳队列 | 候选列表（建议标题/答案/置信度/来源/依据）+ 采纳 / 编辑后采纳 / 拒绝 |
| 行业模板 | 模板列表 + 「一键套用」+ 套用结果提示（去重统计） |

> 说明：旧「文档资料/同步历史」Tab 随旧知识库移除（§三·五），L4 文档提炼入口并入「行业模板」旁的新「文档提炼」入口或词条管理页（Phase 6 定）。

## 十二、契约（新增，进 CONTRACT-LEDGER）

| 业务对象 | 合法值 | 三端一致要求 |
|---|---|---|
| 词条状态 | `draft / pending_review / published / archived` | Java `KnowledgeEntry.status` = TS `KnowledgeEntryStatus` = Agent 检索过滤条件 |
| 候选状态 | `pending / adopted / edited / rejected` | Java `KnowledgeCandidate.status` = TS 同 |
| 词条来源 | `template / product / config / conversation / document / manual` | Java `sourceType` = TS `sourceType` = Agent 展示徽标 |
| 候选来源 | `conversation / document / product / config` | 同上 |
| 词条分类 | `faq / product / measure / aftersale / config` | 前后端同枚举 |
| 提炼接口 | `POST /api/admin/knowledge/distill/conversations` | 触发+返回统计 |
| 词条检索端点 | `GET /api/admin/knowledge/entries/search?query=&productId=&category=` | 仅返回本租户 published 词条（显式 eq tenant_id + status） |

## 十三、分阶段实施计划（v1.1：每阶段独立提交，同一 PR 链最终 Closes #3051）

| Phase | 内容 | 交付物 | 状态 |
|---|---|---|---|
| P1 | 词条数据模型 | V35 迁移（entries/candidates）+ Entity/Mapper + 单测 + schema.sql 同步 + 契约 | ✅ 已提交（bf067c41） |
| P2 | **词条 CRUD + 检索 API + 旧知识库移除（后端）** | V36 DROP 三表 + 删旧实体/Mapper/Controller/测试 + KnowledgeEntryService/Controller（CRUD/发布/归档/search）+ 单测 + 用例更新 | 进行中 |
| P3 | 行业模板体系 | 种子 Markdown → 结构化 JSON 模板 + 丰富 + templates 目录/套用 API + 单测 | P2 |
| P4 | L2 派生 | 商品/加工项 → 派生词条（同步 + 定时对账）+ 变量填充 + 单测 | P2 |
| P5 | L3 会话提炼 | candidates 队列 API + 提炼 pipeline（LLM）+ 采纳流 + 单测 | P2 |
| P6 | L4 文档提炼 | 文档上传后提炼 + 单测 | P5 |
| P7 | Agent 检索 + 旧知识库移除（Agent） | knowledge_search 重注册为词条检索 + customer_knowledge prompt 更新 + registry/参考文档清理 + agent 单测 | P2/P4 |
| P8 | 前端改造 + 旧知识库移除（前端） | 知识库页改造（词条/待采纳/模板）+ api.ts 替换 + 旧 UI/测试移除 + 契约对齐 | P2~P6 |
| P9 | 文档与用例收口（自洽） | README/Home/AI-Agent/api-reference/rag-architecture 归档、cases API-008/011 移除、schema_full 同步、grep 归零核销 | P2~P8 |

## 十四、验收业务真值（映射 issue #3051，验收时逐条核对）

1. 商家创建/编辑词条（问题+标准回答+分类+关键词）并发布后，AI 客服回答知识类问题时优先采用本店词条内容，未命中才用通用知识兜底
2. 商家一键套用行业模板后，知识库自动获得该行业预置词条（布艺为第一个模板），无需逐条手写
3. 商品/加工项信息变更后，关联的派生词条自动更新，AI 回答价格/规格问题时与商品数据一致
4. 客服会话结束后，系统自动提炼候选词条进入「待采纳」队列；商家采纳（或编辑后采纳）后词条生效，拒绝则不生效
5. 商家上传文档后，系统提炼候选词条进入「待采纳」队列（文档→词条提炼，非文档→切块检索）
6. 词条检索严格按租户隔离，任何租户无法看到其他租户词条
7. **（v1.1 替代）旧知识库完全移除**：knowledge_documents/rag_chunks/knowledge_sync_history 三表、旧文档 CRUD API、知识库文档页全部下线；全仓 grep（排除历史审计文档）无旧组件引用
8. **（v1.1 闭环）无死端**：词条每状态有 API+UI 动作；待采纳队列有读+写路径；发布词条必可检索（发布后查得到、归档后查不到）；会话→提炼→采纳→检索形成闭环
