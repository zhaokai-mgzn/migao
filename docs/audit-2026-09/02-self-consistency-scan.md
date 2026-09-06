# P0/P1 自洽性扫描报告（2026-09-06）

> 依据：`docs/wiki/self-consistency-checklist.md`（issue #2968）执行 P0（可全自动）+ P1（半自动）谓词实体扫描。
> 范围原则：**AI 能确定的不自洽直接修复；需要业务语义判断的交人工决策，不做未经确认的功能开发。**
> 基线：origin/main @ 617b7b94。方法：schema.sql 521 列 → 全仓代码/prompt 消费端引用统计（脚本 /tmp/scan_dead_fields.py，排除 node_modules/dist/venv/schema 自身，snake+camel 双变体匹配）。

## 0. 结论速览

| 分类 | 数量 | 处置 |
|---|---|---|
| **已修复（本期）** | 1 组 | 知识库同步历史闭环（knowledge_sync_history 零读写 → 补写读 + 展示） |
| **设计文档已跟踪（无需修）** | 1 组 | 订单 payment_status / stock_deducted（支付 M3/M5 预留死列，tenant-miniapp-launch-and-payment.md 显式记录） |
| **交人工决策（P2 语义）** | 6 组 | 加工组合规则整表 / CRM(RFM/地区) / 客群标签规则 / AI 配置推荐字段 / 向量集合列 / 租户应用与杂项 |
| **噪声确认** | — | id 等通用短列、audit_logs 读写齐全、users.session_ttl 有 mapper 读取 |

**健康面**：加工项适用商品分类（#2964，PR #2966）同类问题已先修；本次扫描未发现新的「前端已实现但后端无接口」或「接口存在但前端无消费」的断链（契约快照 + 三端枚举由 contract-check 持续守护）。

---

## 1. 本期已修复：知识库同步历史闭环（KNOWN-01）

**症状**（P0-1 死数据 + 孤儿功能）：`knowledge_sync_history` 表（schema）+ 实体 + Mapper 全部就绪，但**全仓零使用**——`POST /documents/{id}/embed`（resync）只把文档置 pending，不写历史；无任何列表接口；知识库页无历史展示。管理员「重新同步」后看不到任何反馈记录。

**修复**（PR 随本报告合入）：
1. `KnowledgeController.resyncDocument`：校验通过后写入 `KnowledgeSyncHistory`（syncType=single / sourceType=manual / sourceIds=[id] / status=processing / totalCount=1 / startedAt）
2. 新增 `GET /api/admin/knowledge/sync-history` 分页接口（tenant 隔离，created_at 倒序）
3. admin-web 知识库页新增「同步历史」按钮 + 弹窗展示（来源文档 sourceIds→标题映射、类型、状态、结果、时间；空态提示）
4. 测试：MockMvc（resync 写历史断言 + 跨租户不写 + 列表/空态）、vitest（UI-027 展示 + 空态）；cases：API-011 / UI-027

## 2. 设计文档已跟踪（KNOWN-02，不修）

| 列 | 现状 | 依据 |
|---|---|---|
| `orders.payment_status` | 代码零引用 | tenant-miniapp-launch-and-payment.md §194「列已在 DB，Order.java 实体尚未映射 → 落地时补上」；M5「payment_status 启用、回调驱动 pending→confirmed」（§292 勾选清单） |
| `orders.stock_deducted` | 代码零引用 | 同上，库存扣减随支付回调落地 |

→ 属「有计划的预留死列」，由设计文档持续跟踪，无需本次处理；**扫描工具应对此类加豁免登记**，否则每次扫都误报。

## 3. 交人工决策（KNOWN-03~08，P2 语义，本期不修）

### 3.1 `processing_rules` 整表（加工项组合规则，KNOWN-03）
- 表结构完整（rule_type: mutually_exclusive/required/optional/stackable + applicable_category_id + processing_item_ids JSONB），**全仓 0 代码引用（连实体都没有）**。
- 对应设计 docs/design/admin-dashboard-design.md §6.1.1「组合规则：必选其一、互斥、可叠加、可选叠加」——设计意图无落点（P1-2 实证）。
- **决策点**：加工项组合规则的消费方是建品/下单流程的「加工项可组合性校验」与「价格计算器」——人工确认是否排期；不排期则建议 schema 标注 DEPRECATED 防误解。

### 3.2 `customer_profiles` RFM/地区/微信字段（KNOWN-04）
- `f_score/m_score/r_score`（RFM 评分）、`first_order_at/last_order_at`、`region_province/city/district`、`wechat_unionid` 仅 entity 引用（region_province 在 CustomerService 有合并写入，但无前端入口/无展示）。
- **决策点**：CRM/RFM 价值度——看板是否要展示 RFM 分；客户资料是否补地区/微信字段的表单与展示。属功能开发，需产品排期。

### 3.3 `customer_segments` / `customer_tags` 规则字段（KNOWN-05）
- `segment_type/update_frequency/last_calculated_at`、`rule_type/rule_condition/tag_type/hit_count/auto_update_frequency` 仅 entity 引用（tag_type/hit_count 在 CustomerServiceTest 出现）。
- **决策点**：自动客群/标签引擎是否实现（当前客户域只有 tag 手动管理）。

### 3.4 `tenant_ai_configs` AI 推荐/转人工字段（KNOWN-06）
- `recommend_count/recommend_strategy/recommend_trigger/ai_fallback_handoff/ai_fallback_threshold` 仅 entity + 测试引用；ai-agent `tenant_config.py` 只有注释「emotionHandoff / recommendStrategy 等（后续扩展）」——**设置页可写、Agent 从不读**（与加工项同类，但属 Agent 行为功能）。
- **决策点**：商品推荐策略与情绪转人工阈值是否接入 Agent 行为；不接入则应在前端设置页标注「暂未生效」防止误导。

### 3.5 `knowledge_documents.dashvector_collection` / `rag_chunks.chunk_index`（KNOWN-07）
- 仅 entity 引用；ai-agent 侧向量链路当前禁用（memory/__init__「当前禁用」），检索 collection 用约定而非该列。
- **决策点**：向量化重启时决定 collection 命名来源（列 vs 约定）。

### 3.6 `tenant_apps` / `tenants` / `sessions` 杂项（KNOWN-08）
- `tenant_apps.app_type/encoding_aes_key/msg_encrypt_mode/server_url`（微信加解密配置）、`tenants.auth_config/bailian_config`（认证/百炼配置）、`sessions.assigned_agent_id`（人工坐席分配）——仅 entity 引用。
- **决策点**：微信事件回调加解密、人工坐席分配均为「已设计未实现」；对照 multi-tenant-wechat.md / session-management-redesign.md 排期。

## 4. 噪声确认（已排除）
- **`*.id` 全量列**：脚本短 token 噪音（已修脚本排除）。
- **`audit_logs.action_details/resource_name`**：写入（AuditLogService）+ 读取（SettingsController.getLoginLogs 分页接口）齐全，非死数据。
- **`users.session_ttl`**：entity + UserMapper @Select 显式映射，登录链路可读，半活非死。
- **`knowledge_sync_history.sync_type/source_type`**：与 mini-app imageUpload / api/internal 的命中为同名词误报，实体引用仅 1 处属实，已按 KNOWN-01 处理。

## 5. 工具化建议（Phase 1 落地）
扫描脚本 `/tmp/scan_dead_fields.py`（schema 列枚举 + snake/camel 双变体引用统计）已验证可复现本报告全部发现。建议：
1. 入库为 `scripts/scan-dead-fields.py`，输出零引用/低引用清单；
2. 豁免登记（KNOWN-02 预留列 + id 等公共列），避免每次误报；
3. Phase 2 挂 contract-check 或单独 CI job，对新 schema 变更强制过扫描。

## 6. 关联
- issues：#2968（清单）、#2971（本次扫描修复）
- PR：随本报告代码合入（KnowledgeController sync-history 闭环）
- 引用谓词：P0-1（死数据字段）、P0-5（schema 列无映射）、P1-2（设计意图无落点）