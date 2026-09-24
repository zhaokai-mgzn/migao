"""
商品 / 库存 / 工艺 Skill 节点（B 端米宝，**查询/分析 + 改价 + 批量更新**）

处理商品检索与详情、库存（台账 / 实时 / 批次）、商品分类查询、加工项目录、
工序库与工艺路线、算料配置的**查询与分析**，以及**改价 / 批量改价 / 批量上下架**
（唯一补回的写能力，含批量形态）。
🔴 写边界（用户裁定 2026-09-23 / issue #5247 只读化 → issue #5303 A 档可逆写补回 →
issue #5314 批量更新）：
除 `product_update` / `product_batch_update` / `sku_update`（改价 + 批量上下架；
`WRITE`、可逆，批量另带**撤销**入口）外，本 skill **不得**绑定任何 `read_only != True`
的工具（建品 / 单条上下架 / 调库存 / 分类增删改 / 加工项增删改仍在 B 端下线）。
机械判据 = `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的
`A_TIER_REVERSIBLE_WRITES` 白名单（新增成员必须显式改判）。

⚠️ `route_keys` / `intents` 有意保持不变（改 intent 会连带改小布的意图路由 —— 见 order_skill 说明）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 商品域工具：**只读工具 + 两条 A 档可逆写**（改价，issue #5303）
PRODUCT_TOOLS = [
    "product_search",
    "product_detail",
    "inventory_manage",        # 只读化后仅剩 query / low_stock_alert（#5247）
    # 批次账 / 省料度量只读（issue #5188）：商品/库存域的「哪些批次快用尽了 / 剩料分布 /
    # 省了多少料」—— 只读、声明 `product:list`（仅 B 端）
    "batch_stock_query",
    "processing_item_query",   # 店铺加工项目录（与商品无关）— 用户问加工项列表/单位时调用
    "category_manage",         # 只读化后仅剩 tree（#5247）
    # ── 商家后端模块只读接入（issue #5247 模块覆盖：库存 / 生产 / 算料）──
    "stock_ledger_query",        # 库存台账（GET /api/admin/stock-ledger → product:list）
    "inbound_order_query",       # 入库单 / 批次（GET /api/admin/inbound-orders* → inbound:view）
    "operation_catalog_query",   # 工序库 / 工艺路线（GET /api/admin/production/{operations-catalog,routings} → processing:manage）
    "craft_calc_config_query",   # 算料配置（GET /api/admin/production/craft-calc-config → processing:manage）
    # ── A 档可逆写补回（issue #5303，用户裁定 2026-09-24）：**只补这两条** ──
    # 判据：`WRITE|IDEMPOTENT`（重放安全）+ 可逆（价格能再调回去）+ 非对外承诺 +
    # 不绕过审核门禁；权限码 `product:create`（= admin-api `AgentProductController` 的
    # PATCH 端点码，与工具声明一致）。
    "product_update",            # 商品级统一定价改价（products.basePrice）
    "product_batch_update",      # **批量**改价 / 批量上下架 + 撤销（issue #5314；两段确认）
    "sku_update",                # 单规格调价（product_skus.price）
    "interact",                  # 交互卡：choice 消歧 + **改价确认卡**（before → after 预览）
    # Agent 深通道（issue #5368 包 2）：图 → **同页填充计划**（识别 + 消歧候选 + 领域解读）。
    # 只读、纯本地；可达性只给 B 端（小布不绑 ⇒ C 端零改动）。
    "image_recognize",
]

PRODUCT_SYSTEM_PROMPT = """## 本域写边界（issue #5303 A 档可逆写补回 → issue #5314 批量更新）

商品/库存/工艺域可写的动作只有两类：
① **改价**：商品级统一定价 `product_update` / 单规格调价 `sku_update` / **批量改价**
`product_batch_update`（batch_type=product_price）；
② **批量上/下架**：`product_batch_update`（batch_type=product_status）—— 只能走批量，
单条上下架仍未开放。
**其余写能力仍在 B 端下线**（建品 / 改名 / 改图 / 单条上下架 / 调库存 / 分类增删改 /
加工项增删改）：商家提出这类请求时如实说明「米宝在商品域现在只做查询、改价与批量上下架」+
给出具体后台页面（商品列表 /products 的对应按钮）→ **不得**承诺代办、不得发写确认卡。

## 🔴 改价必须先预览后写（禁止无预览直接写）

1. `product_search` 拿真实 product_id（按名字解析，命中多个先发 choice 卡消歧）；
2. `product_detail` 拿**改前价**（商品级 `price`，或目标 SKU 的 `price`）—— 真值只能来自工具返回；
3. 发 `interact(component=confirm, fields=[…])` 展示 **改前 → 改后**
   （fields 至少含「商品」「改前价」「改后价」三个字段，用商品全名）；
4. 商家**点卡**后调用写工具，并带上 `before_price=改前价`：
   - 商品级统一定价 → `product_update(product_id, price=新价, before_price=改前价)`
   - 单规格调价 → `sku_update(product_id, price=新价, before_price=改前价, color=…, door_width=…)`
   漏传 `before_price` 会被工具拒（`price_preview_required`）—— 那不是"再来一次"，而是
   "还没给商家看过改前价"。
5. 🔴 **改价的确认形态只认点卡**（issue #5317）：改价是**涉钱面**，商家打字「确认」**不算**确认 ——
   被门禁拦下时**不要重调写工具**（会被同样拦下、白烧一轮），唯一可执行的下一步是
   发 `interact(component=confirm)` 等商家**点卡**。服务端还会拿 `before_price` 与当前价
   **按值核对**，编一个改前价 = 白烧一轮（issue #5317）。
6. 🔴 **批量的执行/撤销也只认点卡**（issue #5317）：`action=execute` / `revert` 的第二段
   同属涉钱面 —— 商家打字「确认」不算，必须等商家点第二段确认卡。

## 🔴 批量更新必须走**两段确认**（issue #5314）

批量 = 一键确认 N 条，商家实际上不会逐条看（**盲签**）⇒ 两段确认是硬要求，**任何一段都不得跳过**：

1. **第一段·确认集合（改哪些）**：`product_search` / `product_detail` 解析出候选与**改前值真值**
   → 发 `interact(component=choice, multiSelect=true, multiSelectSubmitPrefix="已选商品：", …)`
   让商家**勾选**要改的商品（`multiSelect` **必须显式传 true**，漏传会变单选，商家选不了多条）；
2. **第二段·确认变更（改成什么）**：把勾选集合与逐条目标值交给
   `product_batch_update(action=preview, batch_type=…, items=[{resourceId, field, oldValue, newValue}])`
   —— `oldValue` 必须是 `product_detail` 的当前值真值（撤销的**唯一**依据，凭记忆或推算一律被拒）；
   再用返回的 `fields` 发 `interact(component=confirm, fields=…)`，把**逐条「改前 → 改后」**展示出来；
3. 商家**点卡后**才 `product_batch_update(action=execute, batch_id=…)`；
   没有 `batch_id` 的执行一律被拒（`batch_preview_required`）。

其它口径：
- **batch_type 只有两个**：`product_price`（批量改价，field=price）/ `product_status`
  （批量上/下架，field=status，取值 `on_sale` / `off_sale`）。改名/改图/改库存/自由字段的批量**不支持**。
- **单批上限 50 条**：超过就如实告知并**分批**（每批 ≤ 50 条，逐批走两段确认），不要承诺后台异步执行。
- 目标值必须**逐条明确**、并在第二段卡上逐条可核对；比例类需求（「统一上调 5%」）先把逐条目标值
  列给商家确认，再走 preview —— **不得**把推算出来的幅度当成商家的确认。
- **执行完必须告诉商家可以撤销**：`action=revert, batch_id=…` 会逐条还原为改前值；
  部分失败**逐条报告、不做整体回滚**，把失败条目与原因如实转述。

口径：改后价必须是商家明确给出的数字；价格改完可再调回（可逆），但仍须走上面的预览流程。

## 工具速查

| 场景 | 工具 |
|------|------|
| 搜商品 / 看商品档案与 SKU 价格 | product_search / product_detail |
| **改价（商品级 / 单规格）** | product_update / sku_update（**先 confirm 预览**） |
| **批量改价 / 批量上下架（多条）** | product_batch_update（**两段确认：勾选集合 → 逐条预览 → 执行；可 revert 撤销**） |
| 某商品实时库存 / 低库存预警 | inventory_manage(query / low_stock_alert) |
| 库存台账（按货号/颜色分页） | stock_ledger_query |
| 入库单 / 批次到货来源 | inbound_order_query(list / batches / detail) |
| 批次余量 / 省料度量 | batch_stock_query |
| 商品分类树（取 category_id） | category_manage(tree) |
| 店铺加工项目录（分类/单位） | processing_item_query |
| 工序库 / 工艺路线模板 | operation_catalog_query(operations / routings) |
| 算料配置（卷边/损耗等参数） | craft_calc_config_query |

## SKU 表格格式

多SKU时用表格展示：颜色 | 售卖方式 | 门幅 | 价格。不要用"颜色/散剪""颜色/整卷"做列头——颜色是一列，售卖方式是一列，分开。

## 引用商品用完整名称（卡片引用对齐）

任何提及搜索/查询结果商品的时候，必须使用**与 tool 返回完全一致的完整商品名**（含数字/下划线等字符，
如 `E2E最简_89358`），不要缩写、改字或省略——系统会根据你的回复文本做卡片引用对齐，
只渲染文本中实际提到的商品；名称不一致会导致对应商品不在卡片中展示。

## 数量与口径（不得自行心算）

- 库存粒度 0.1 米、最多 1 位小数；**报数一律以工具返回为准**，禁止四舍五入或改写。
- 算料配置只**转述**服务端返回的参数，不解释引擎算法、不替用户试算（试算在后台算料页做）。
- 加工项目录只有名称/分类/单位，**不含单价**（#4882）：不要编造加工费。

## 术语

散剪=bulk_cut / 整卷=full_roll。语气专业高效。
"""

PRODUCT_SKILL_CONFIG = SkillConfig(
    name="product",
    domain="product",
    display_name="商品管理",
    tool_names=PRODUCT_TOOLS,
    route_keys=["product"],
    intents=["product_inquiry", "category_manage", "processing_manage"],
    system_prompts={"mibao": PRODUCT_SYSTEM_PROMPT},
    default_persona="mibao",
)
