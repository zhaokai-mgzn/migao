# 企业级 LLM WIKI 知识板块设计（词条化 + AI 提炼 + 行业模板）

> 版本 v1.0 ｜ 2026-09-08 ｜ Issue [#3051](https://github.com/zhaokai-mgzn/migao/issues/3051)
> 性质：功能板块设计文档（单一事实源）。实施按 §十三 Phase 1~8 推进，全部 AI-TDD（测试先行 + case_ids）。
> 背景决策：RAG（DashVector + 切块检索）维持下线（决策 D1，2026-08-29）。本设计以「**词条**」为知识单元，
> 检索用「结构化过滤 + 关键词匹配」，**不引入向量库**；「知识是生成的，不是检索的」。

---

## 一、结论速览（TL;DR）

**问题**：中小商户几乎没有自己的知识文档，RAG「先有文档、再切块检索」的前提不成立（决策 D1 已下线）。
客服知识问答目前走 LLM 通用知识 + 免责，无租户定制能力，无法回答「本店」事实（价格、加工项、售后政策）。

**方案**：把知识库从「RAG 文档模型」升级为「**词条模型**」，四层知识供给：

| 层 | 供给方式 | 知识单元 | 谁产生 |
|---|---|---|---|
| L1 行业模板 | 平台预置模板一键套用 | 行业通用词条（面料/测量/FAQ） | 平台（种子数据已存在，需结构化 + 丰富） |
| L2 商品/配置派生 | 商品/加工项/配置数据 → 自动生成词条 | 本店事实词条（价格/规格/计价方式） | 系统自动（商品数据即知识源） |
| L3 会话提炼 | 客服会话 → AI 提炼候选词条 → 人工一键采纳 | 本店经验词条（高频问答/售后话术） | AI 提炼 + 商家确认 |
| L4 文档提炼 | 上传文档 → AI 提炼候选词条 → 人工一键采纳 | 本店文档知识 | AI 提炼 + 商家确认 |

**运行时**：AI 客服知识问答按「词条检索（精确/关键词）→ LLM 通用兜底」两级走；词条回答**优先、可溯源、租户隔离**。
**无向量库**：词条量级几百~几千条，PG 结构化过滤 + 关键词匹配足够，租户隔离沿用 MyBatis 拦截器 + 显式 eq（吸取审计 07 P1-6 `.or()` 教训）。

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
| 文档资料 | 保留现有文档上传/列表/同步历史（L4 入口） |
| 行业模板 | 模板列表 + 「一键套用」+ 套用结果提示（去重统计） |

## 十二、契约（新增，进 CONTRACT-LEDGER）

| 业务对象 | 合法值 | 三端一致要求 |
|---|---|---|
| 词条状态 | `draft / pending_review / published / archived` | Java `KnowledgeEntry.status` = TS `KnowledgeEntryStatus` = Agent 检索过滤条件 |
| 候选状态 | `pending / adopted / edited / rejected` | Java `KnowledgeCandidate.status` = TS 同 |
| 词条来源 | `template / product / config / conversation / document / manual` | Java `sourceType` = TS `sourceType` = Agent 展示徽标 |
| 候选来源 | `conversation / document / product / config` | 同上 |
| 词条分类 | `faq / product / measure / aftersale / config` | 前后端同枚举 |
| 提炼接口 | `POST /api/admin/knowledge/distill/conversations` | 触发+返回统计 |

## 十三、分阶段实施计划（每阶段独立 PR + Closes #3051 链条）

| Phase | 内容 | 交付物 | 依赖 |
|---|---|---|---|
| P1 | 词条数据模型 | V35 迁移（entries/candidates）+ Entity/Mapper + 单测 + schema.sql 同步 | 无 |
| P2 | 词条 CRUD + 检索 API | EntryController（CRUD/发布/归档）+ entries/search + 单测 | P1 |
| P3 | 行业模板体系 | 种子 Markdown → 结构化 JSON 模板 + 丰富 + templates 目录/套用 API + 单测 | P2 |
| P4 | L2 派生 | 商品/加工项 → 派生词条（同步 + 定时对账）+ 变量填充 + 单测 | P2 |
| P5 | L3 会话提炼 | candidates 队列 API + 提炼 pipeline（LLM）+ 采纳流 + 单测 | P2 |
| P6 | L4 文档提炼 | 文档上传后提炼 + 单测 | P5 |
| P7 | Agent 检索 | knowledge_search 重注册为词条检索 + customer_knowledge prompt 更新 + agent 单测 | P2/P4 |
| P8 | 前端改造 | 知识库页四 Tab + 契约对齐 | P2~P6 |

## 十四、验收业务真值（映射 issue #3051，验收时逐条核对）

1. 商家创建/编辑词条（问题+标准回答+分类+关键词）并发布后，AI 客服回答知识类问题时优先采用本店词条内容，未命中才用通用知识兜底
2. 商家一键套用行业模板后，知识库自动获得该行业预置词条（布艺为第一个模板），无需逐条手写
3. 商品/加工项信息变更后，关联的派生词条自动更新，AI 回答价格/规格问题时与商品数据一致
4. 客服会话结束后，系统自动提炼候选词条进入「待采纳」队列；商家采纳（或编辑后采纳）后词条生效，拒绝则不生效
5. 商家上传文档后，系统提炼候选词条进入「待采纳」队列（文档→词条提炼，非文档→切块检索）
6. 词条检索严格按租户隔离，任何租户无法看到其他租户词条
