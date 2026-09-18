# Product Skill — 正确执行示例

## 示例 1：完整创建流程

用户: "帮我创建一个遮光窗帘，50 元一米"

### 轮次 1 — 收集基本信息 + 分类选择
```
→ category_manage(action="tree")   // 获取分类树（分类 ID 是建品归属的前提）
→ interact(
    component="form",
    title="新建商品 — 基本信息",
    formFields=[
      {key:"name", label:"商品名称", value:"遮光窗帘"},
      {key:"price", label:"单价(元)", value:"50"},
      {key:"selling_methods", label:"售卖方式", required:true, placeholder:"散剪/整卷"},
      {key:"door_widths", label:"门幅", placeholder:"如 2.8米"},
      {key:"sku_code", label:"货号", placeholder:"按色号/品牌缩写/拼音首字母生成"}
    ]
  )
→ 💬 "遮光窗帘已查到分类可选。货号可从色卡提取或按品牌首字母生成。"
```
🔴 分类未确认前不要发汇总确认卡（没有分类 ID ⇒ 建品归属缺失）。

### 轮次 2 — 分类确认 + 回填 → 货号
```
用户点选分类卡「窗帘」（= 已确认分类 ID，如 cat_curtain）+ 回填 form:
  name="遮光窗帘", price=50, selling_methods=["散剪","整卷"], door_widths=["2.8米"], sku_code="ZG-001"
→ 💬 "基本信息已收到。货号 ZG-001 可以吗？"
🔴 建品**没有**加工项多选卡（issue #4371：加工项是店铺级目录，与商品无关）——
   不要调 processing_item_query 问加工项，也不要把加工项写进 create 参数。
```

### 轮次 3 — 汇总确认
```
收集齐全部字段：
→ validate_input(action="create", name="遮光窗帘", price=50, ...)
→ 将校验结果展示给用户确认
```

### 轮次 4 — 执行
```
用户确认 → product_manage(
    action="create", name="遮光窗帘", price=50, status="on_sale",
    sku_code="ZG-001", colors=["2699-01 米白色"],
    selling_methods=["散剪","整卷"], door_widths=["2.8米"],
    specifications={"克重":"200-300g","材质":"涤纶","功能":"遮光","工艺":"色织","风格":"现代简约","图案":"纯色"},
    unit="米", pricing_type="per_meter"
  )
→ ✅ "遮光窗帘（ZG-001）已创建并上架。"
→ product_search 验证入库
```

## 示例 2：图片识别 + 创建

用户上传窗帘图片: "创建这个商品"

```
→ Vision 识别结果：名称="雪尼尔遮光窗帘"，颜色="3610-28 奶茶色、5112-03 灰色"
→ 将识别结果预填到 form，不要求用户重复输入
→ interact(
    component="form",
    title="新建商品 — 识别结果已预填",
    formFields=[
      {key:"name", label:"商品名称", value:"雪尼尔遮光窗帘"},
      {key:"price", label:"单价(元)", required:true, placeholder:"请输入价格"},
      {key:"colors", label:"颜色", value:"3610-28 奶茶色、5112-03 灰色"},
      {key:"sku_code", label:"货号", value:"XNE3610"}  // 色号 3610 + 雪尼尔首字母
    ]
  )
→ 💬 "图片识别到名称'雪尼尔遮光窗帘'、2 种颜色。价格和售卖方式还需补充。货号建议 XNE3610。"
用户回填 price=68, selling_methods=["散剪"] → confirm → validate_input → product_manage → 完成
```

关键点：识别结果**以预填 form 呈现（呈现即一次确认入口）**，不要跳过呈现直接建品；
已识别字段不重复反问，缺失字段引导补充。

## 示例 3：信息不完整的引导流程

用户: "创建一个商品"

```
→ 💬 "好的，请提供：① 商品名称 ② 单价"
用户: "简约窗帘" → 💬 "价格是多少？"
用户: "38 一米" → 💬 "好的。售卖方式？散剪还是整卷？"
用户: "散剪" → category_manage(tree) → 💬 "窗帘分类如下：[分类树]。归入哪个？"
用户: "客厅窗帘" → 💬 "还需要货号，比如 JY-001，您可以改。"
用户: "JY-001" → confirm → validate_input → product_manage → 完成
```

关键点：每次追问 1-2 个字段，缺失字段逐个补，不编造。

## 反例

**❌ 序号表格**
```
| 1 | 打孔加工 | ¥8/米 |
请输入序号
```
🔴 用户输入 "1,2" → 序号无法映射 UUID。正确：用 interact choice，value=真实UUID。

**❌ 只汇总不执行（tools=0 空转）**
```
→ 💬 "确认创建遮光窗帘，50元/米，货号 ZG-001…"（无工具调用）
```
✅ 正确：汇总伴随 validate_input → confirm → product_manage。

**❌ 跳过货号引导** → 商品创建后无货号

**❌ Vision 结果不利用** → 识别到 "2699-01 白色" 还反问 "什么颜色"

## 示例 4：改价格（product_update）

用户: "把遮光窗帘价格改成 199"

```
→ 先展示确认内容（interact(component=confirm)）：商品 遮光窗帘，价格 ¥旧价 → ¥199
→ 用户明确确认后 → product_update(product_id="遮光窗帘", price=199)
→ ✅ "遮光窗帘价格已更新为 ¥199"
```

关键点：改价格/名称/状态用 product_update，只传 product_id + 要改的字段。**必须先向用户展示确认卡、征得明确确认后再调用，禁止跳过确认直接改价。不要调 product_manage 或 validate_input。**

## 示例 5：多步操作（逐个执行，不要并行）

用户: "查遮光窗帘，改成 199"

```
轮次 1:
→ product_search(keyword="遮光窗帘")
→ 💬 "找到 1 件：米白色遮光窗帘 ¥99"

轮次 2:
→ product_update(product_id="遮光窗帘", price=199)
→ 💬 "价格已改为 ¥199"
```

关键点：**每个操作单独一轮，不要在一次回复中并行走两个操作。**

## 示例 6：店铺加工项目录（与商品无关）

用户: "有哪些加工项？"

```
→ processing_item_query()   // 🔴 店铺级目录：不带商品、不带商品分类
→ 💬 如实列出名称与单价（可多选展示，不要"等X项"省略）
```

关键点：加工项是**店铺级目录**（issue #4371），与具体商品无关；商品上不再关联加工项。
顾客要在**下单**时加加工项，属订单域流程（按店铺目录单独选），不在建品流程里代做。
