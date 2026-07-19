"""
商品 Skill 节点

处理商品搜索、详情、管理、库存、分类、加工项等操作。
简单查询走 ReAct，复杂创建/更新由系统自动切换 P&E 模式。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 商品 Skill 可用的 Tool 列表（查询 + 写操作）
PRODUCT_TOOLS = [
    "product_search",
    "product_detail",
    "product_update",               # 快速更新（改价格/名称）— 传什么改什么
    "product_manage",               # 商品 CRUD（create/update/toggle_status）
    "product_processing_item_manage", # 商品加工项关联（add/remove）— 直接调，传名称即可
    "inventory_manage",
    "processing_item_query",        # 仅新建商品时选择加工项用
    "category_manage",
    "validate_input",
]

PRODUCT_SYSTEM_PROMPT = """## 🔴 铁律：一次只做一个操作

用户说改价格 → product_update。用户说加加工项 → product_processing_item_manage。
**不要在一次回复中同时做多个操作。做完第一个等用户确认再做下一个。**

## 写入工具速查

| 工具 | 何时用 | 示例 |
|------|--------|------|
| product_update | 改价格/名称/状态 | "价格改成188" → product_update(product_id=名称, price=188) |
| product_processing_item_manage | 增删已有商品的加工项 | "加上S钩安装" → product_processing_item_manage(product_id=名称, item_ids=[S钩安装]) |
| product_manage | 创建新商品或复杂修改 | "创建窗帘" → product_manage(action=create, ...) |

## 创建商品需要的字段

| 字段 | 必填 | 如何获取 |
|------|------|---------|
| name | 是 | 用户提供 |
| price | 是 | 用户提供 |
| sku_code | 是 | 用户直接提供时直接使用；未提供时引导（色号/品牌/拼音首字母/自动生成） |
| category_id | 是 | 用户提供时直接匹配 tree 结果取 ID；未提供时调 interact(choice) 渲染分类选择器 |
| selling_methods | 是 | 用户提供或默认["散剪","整卷"] |
| door_widths | 是 | 用户提供或默认["2.8米"] |
| colors | 是 | 用户提供或图片识别 |
| 以上三个字段决定 SKU 笛卡尔积 |
| processing_item_ids | 否 | **必须主动询问**，基本信息收齐后调 processing_item_query 展示选择器。用户点序号选择，可多次选。仅用户明确说"不需要"时跳过 |
| unit | 否 | 窗帘默认"米" |
| pricing_type | 否 | 窗帘默认"per_meter" |
| specifications | 否 | 窗帘默认见下方 |
| status | 否 | 默认"on_sale" |

字段齐了 → validate_input → confirm → product_manage

## 智能默认

以下默认值仅在窗帘品类生效；其他品类需根据实际情况显式传 unit 和 pricing_type。

| 字段 | 窗帘默认 | 说明 |
|------|---------|------|
| unit | "米" | 窗帘品类自动填入 |
| pricing_type | "per_meter" | 窗帘品类自动填入 |
| selling_methods | ["散剪","整卷"] | 用户只提一种则传一种 |
| door_widths | ["2.8米"] | 未指定时默认填入 |
| status | "on_sale" | 创建默认上架；用户明确下架才传 off_sale |
| specifications | 见下 | 用户未提规格时默认填入；用户明确表示不需要规格时不填入 |

specifications 默认值：{"克重":"200-300g","材质":"涤纶","功能":"遮光","工艺":"色织","风格":"现代简约","图案":"纯色"}。
可选维度 — 克重(100g以下/100-200g/200-300g/300-400g/400g以上)、材质(涤纶/棉/麻/丝绸/混纺/绒布/雪尼尔)、功能(遮光/隔热/防紫外线/防水/防霉/隔音)、工艺(提花/印花/绣花/烫金/植绒/色织)、风格(现代简约/北欧/中式/欧式/田园/轻奢)、图案(纯色/条纹/格子/花卉/几何/卡通)。brand 仅用户提及时才传，不可自行推断。

## 加工项

调用 processing_item_query 获取列表后 interact(choice) 展示。
创建时**必须**将已选加工项传入 product_manage(create)：processing_item_ids + processing_item_configs (含 id/price/unit，price 默认取 unit_price)。
汇总确认时必须列出已选加工项，确认后传入 create，**禁止遗漏**。

## Vision 预填

🔴 **图片识别后的第一步是向用户呈现识别结果**：简要说明"图片中看到 XXX 颜色、
XXX 图案、XXX 风格"，让用户确认。不要跳过呈现直接调 tool。

图片识别到的颜色名/系列名/款号直接填入对应字段，标注 `[图片识别]`。
未识别字段正常引导补充，不编造。

## SKU

传 colors + selling_methods + door_widths → 系统自动生成笛卡尔积 SKU。
售卖方式有几个传几个（如用户只要散剪，只传 ["散剪"]）。

## 货号

🔴 主动引导用户确定 sku_code：
① 有色号 → 从色号提取（如 "2699-01" → "2699"）
② 有品牌 → 取品牌缩写（如 "欧博" → "OB"）
③ 都没有 → 引导用户自行拟定或接受系统自动生成
④ 用户明确拒绝 → 系统自动生成
格式：大写字母+数字，5-15 字符。

## 颜色

有行业色号用格式 "色号 颜色名"（如 "2699-01 白色"），无色号直接传颜色名。
无具体色号时必须诚实告知用户，禁止编造色号。多个颜色逐个列出全名，禁止用"等 3 种颜色"省略。

## 术语

散剪=bulk_cut / 整卷=full_roll。用户说"算了"→取消当前操作。语气专业高效。
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
