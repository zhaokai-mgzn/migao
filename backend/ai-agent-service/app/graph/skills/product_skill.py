"""
商品 / 库存 / 工艺 Skill 节点（B 端米宝，**只读**，issue #5247）

处理商品检索与详情、库存（台账 / 实时 / 批次）、商品分类查询、加工项目录、
工序库与工艺路线、算料配置的**查询与分析**。
🔴 写能力（建品 / 改价 / 调库存 / 分类增删改 / 加工项增删改）已按用户裁定 2026-09-23
从 B 端移除：本 skill 不得绑定任何 `read_only != True` 的工具。

⚠️ `route_keys` / `intents` 有意保持不变（改 intent 会连带改小布的意图路由 —— 见 order_skill 说明）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 商品域只读工具（全部 read_only=True）
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
    "interact",                  # 交互卡片只保留 choice 消歧（B 端不发写确认卡）
]

PRODUCT_SYSTEM_PROMPT = """## 🔴 本域已只读（issue #5247 用户裁定 2026-09-23）

商品/库存/工艺域**没有创建、改价、上下架、调库存、分类增删改、加工项增删改**能力。
商家提出这类请求时：如实说明「米宝现在只做查询与分析」+ 给出具体后台页面（商品列表 /products
的对应按钮）→ **不得**承诺代办、不得发写确认卡。

## 工具速查（全部只读）

| 场景 | 工具 |
|------|------|
| 搜商品 / 看商品档案与 SKU 价格 | product_search / product_detail |
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
