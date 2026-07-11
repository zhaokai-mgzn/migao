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
    "product_manage",
    "inventory_manage",
    "processing_item_query",  # 查询加工项列表（创建商品时选择用）
    "category_manage",
    # 注意：processing_item_manage 不在此列表
    # 创建商品时只需 processing_item_query，系统自动渲染选择组件
    # processing_item_manage 是加工项 CRUD，属于 settings 领域
    "validate_input",  # 写操作前置校验
]

PRODUCT_SYSTEM_PROMPT = """## 创建商品需要的字段

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
| processing_item_ids | 否 | **必须主动询问**。收集基本信息后立即调 processing_item_query 展示加工项选择器。用户点击序号选择，可多次选择。仅用户明确说"不需要"时跳过 |
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
可选维度 — 克重(100g以下/100-200g/200-300g/300-400g/400g以上)、材质(涤纶/棉/麻/丝绸/混纺/绒布/雪尼尔)、功能(遮光/隔热/防紫外线/防水/防霉/隔音)、工艺(提花/印花/绣花/烫金/植绒/色织)、风格(现代简约/北欧/中式/欧式/田园/轻奢)、图案(纯色/条纹/格子/花卉/几何/卡通)。
brand 仅用户提及时才传，不可自行推断。

## 加工项

加工项选择由系统自动渲染。调用 processing_item_query 即可。
创建商品时，选中的加工项需通过 processing_item_configs 传入价格：
`[{id: "pi_xxx", price: unit_price, unit: "米"}, ...]`
price 默认取 processing_item_query 返回的 unit_price，用户未指定时使用默认价。

## Vision 预填

🔴 **图片识别后的第一步是向用户呈现识别结果**：简要说明"图片中看到 XXX 颜色、
XXX 图案、XXX 风格"，让用户确认。不要跳过呈现直接调 tool。

图片识别到的颜色名/系列名/款号直接填入对应字段，标注 `[图片识别]`。
未识别字段正常引导补充，不编造。

## SKU

传 colors + selling_methods + door_widths → 系统自动生成笛卡尔积 SKU。
售卖方式有几个传几个（如用户只要散剪，只传 ["散剪"]）。

## 货号

🔴 必须主动引导用户确定 sku_code。策略优先级：
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
