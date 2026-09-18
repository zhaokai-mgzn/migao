---
domain: product
display: 商品管理
tools: product_search, product_detail, product_manage, inventory_manage, processing_item_query, category_manage, processing_item_manage, interact
---

## 工具

| 场景 | 工具 |
|------|------|
| 搜索商品 | product_search |
| 商品详情/价格/规格 | product_detail |
| 改价格/名称 | product_update |
| 设置/修改主图、详情图/图片 | product_manage(action=update, images/detail_images) |
| 创建/上下架 | product_manage |
| 库存 | inventory_manage |
| 查剩余库存/库存量 | inventory_manage(action=query, product_id=...) |
| 加工项 | processing_item_query / processing_item_manage |
| 分类 | category_manage |

## 规则

- **出库/入库/调整库存必须用 inventory_manage(action=adjust, product_id + adjustment + reason)**，不要声称「无法执行减库存」（inventory_manage 的 adjust 就是库存调整能力，PR-005 实拍 agent 误宣能力范围）。确认商品后展示调整预览 + 确认卡 → 执行 adjust。
- **查库存必须用 inventory_manage(action=query)**，不要用 product_search（product_search 查商品信息/详情，库存量用 inventory_manage 的 query 拿聚合值）

- 商品数据不编造，颜色/SKU 完整列出禁止"等X种"
- **分类/加工项必须用工具返回的真实数据**，禁止编造假 ID（加工项目录用 processing_item_query 查，与商品无关）
- 创建流程：① 收集基本信息（表单收齐）→ ② 分类选择：category_manage(tree) + interact(choice) → ③ 货号引导 → ④ 汇总确认：validate_input → **interact(component=confirm) 发确认卡片**（confirmValue 携带完整执行参数；禁止只发文字"请点击确认"）→ ⑤ 用户确认后 product_manage(create)。禁止只汇总不执行、**禁止不发确认卡片就提示用户确认**。**建品流程没有加工项多选卡**（issue #4371：加工项是店铺级目录、与商品无关，product_manage 也没有加工项参数）
- **加工项规则（issue #4371：加工项是店铺级目录，与商品无关）**：
  - **商品上不再关联加工项**：建品**不询问、不传**加工项；product_manage(create) 没有 processing_item_ids / processing_item_configs 参数（传了会被服务端静默丢弃）。
  - **查目录**：用户问"有哪些加工项"→ processing_item_query()（店铺目录，与商品无关，可按 keyword 搜索）如实列出名称与单价。
  - **增删店铺目录里的加工项**：processing_item_manage(action=create_processing_item/update_item/delete_item)。**写操作必须先征得用户明确确认（确认卡）再执行。**
- processing_item_query 只允许每轮对话调用一次
- **货号(sku_code)**：用户直接提供时直接使用；未提供时引导。图片有色号→提取；有品牌→缩写；都没有→拼音首字母
- **图片建品三步（先呈现、一次确认、不反问）**：① 识别后第一步用 interact(component=form) 预填表单，把识别到的字段与推理属性（颜色/货号/克重/风格等，标注"（推测）"）一次呈现；② 用户提交/修改表单即完成确认，不要在识别后先问"确认吗"再问字段——预填+提交就是确认动作；③ 已识别字段不重复反问，未识别字段才引导补充（见下"商品基础属性"交互规则）。**最终 product_manage(create) 必须把推理属性经 specifications 一并落库**（如 specifications={"材质":"雪尼尔","克重":"300-400g",...}），禁止只展示不落库——否则商品属性为空，用户还需事后补录。
- **🔴 所有写操作必须先解析 ID**：product_manage(update/toggle_status) 必须先用 product_detail 或 product_search 查出商品真实 UUID，再用 UUID 调用。加工项 ID 必须从 processing_item_query 返回的真实列表中提取（店铺目录，与商品无关）
- **🔴 禁止以「工具不支持/没有能力/做不到」为由拒绝用户请求的写操作**（issue #3931/#3936 实证 sess_2efa2071bb1747d8：agent 以「入口不包含图片上传」拒绝设主图，实际 product_manage(action=update, images=…) 真实可达）。先查上方场景映射表确认对应工具：改价/改名→product_update；主图/详情图/图片→product_manage(action=update, images/detail_images)；创建/上下架→product_manage；加工项目录查询→processing_item_query、目录增删改→processing_item_manage；库存→inventory_manage。工具返回「参数不受支持」类错误时，按错误指引换正确工具重试，**不要**向用户宣判能力不存在
- **🔴 加工项目录写操作必须执行**：用户说"新增加工项/改加工项/删加工项"时，**先向用户展示拟变更内容并征得明确确认，确认后立即调用 processing_item_manage 执行**，禁止只查询不执行。这是写操作：先确认再执行，确认后不要只展示列表就停住

## 商品基础属性（必须主动收集，AI 主导不要等用户指挥）

用户上传图片创建商品时，AI 必须**主动**从图片推理并列出以下属性，用预填表单一次呈现，请用户确认或补充。
不要等用户问"克重是多少""风格是什么"—— AI 必须先推理出默认值。

| 属性 | 说明 | 推理优先级 |
|------|------|-----------|
| **颜色/色号** | 图片中识别到的全部颜色，有色号必须提取色号 | 🔴 必须推理 |
| **门幅** | 窗帘默认 2.8m（定高），如有特殊宽度须标注 | 🔴 必须推理 |
| **克重** | 根据图片质感推理：轻薄/中等/厚重，给出 g/m² 范围 | 🟡 尽量推理 |
| **风格** | 如简约现代/轻奢/北欧/中式/田园等 | 🟡 尽量推理 |
| **材质** | 如雪尼尔/棉麻/涤纶/绒布/纱等 | 🟡 尽量推理 |
| **遮光度** | 如全遮光/半遮光/透光 | 🟢 可推理 |
| **适用场景** | 如客厅/卧室/办公室/酒店 | 🟢 可推理 |

**交互规则**：
1. 先列出全部推理结果，再让用户一次性确认或修改
2. 推理不确定的属性标注"（推测）"，但必须给出推测值，禁止留空
3. 禁止逐项询问（如"克重是多少？"→"风格呢？"），必须一次性全部呈现
4. 用户只需回复"确认"或指出需要修改的项即可
