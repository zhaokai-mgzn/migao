"""
商品 / 库存 / 工艺 Skill 节点（B 端米宝，**查询/分析 + 改价**）

处理商品检索与详情、库存（台账 / 实时 / 批次）、商品分类查询、加工项目录、
工序库与工艺路线、算料配置的**查询与分析**，以及**改价**（唯一补回的写能力）。
🔴 写边界（用户裁定 2026-09-23 / issue #5247 只读化 → issue #5303 A 档可逆写补回）：
除 `product_update` / `sku_update`（改价，`WRITE|IDEMPOTENT`、可逆）外，
本 skill **不得**绑定任何 `read_only != True` 的工具（建品 / 上下架 / 调库存 /
分类增删改 / 加工项增删改仍在 B 端下线）。

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
    "sku_update",                # 单规格调价（product_skus.price）
    "interact",                  # 交互卡：choice 消歧 + **改价确认卡**（before → after 预览）
]

PRODUCT_SYSTEM_PROMPT = """## 本域写边界（issue #5303：A 档可逆写补回）

商品/库存/工艺域**唯一可写的动作是改价**：商品级统一定价 `product_update` / 单规格调价 `sku_update`。
**其余写能力仍在 B 端下线**（建品 / 改名 / 改图 / 上下架 / 调库存 / 分类增删改 / 加工项增删改）：
商家提出这类请求时如实说明「米宝在商品域现在只做查询与改价」+ 给出具体后台页面
（商品列表 /products 的对应按钮）→ **不得**承诺代办、不得发写确认卡。

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

口径：改后价必须是商家明确给出的数字，**不得**自行加价/推算幅度（"统一上调 5%"这类批量改价尚未开放，
如实说明并引导后台）；价格改完可再调回（可逆），但仍须走上面的预览流程。

## 工具速查

| 场景 | 工具 |
|------|------|
| 搜商品 / 看商品档案与 SKU 价格 | product_search / product_detail |
| **改价（商品级 / 单规格）** | product_update / sku_update（**先 confirm 预览**） |
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
