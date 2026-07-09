# Product Skill — 正确执行示例

## 示例 1：完整创建流程

用户: "帮我创建一个遮光窗帘，50 元一米"

### 轮次 1 — 收集基本信息
```
→ category_manage(action="tree")   // 获取分类树
→ processing_item_query()          // 获取可关联加工项
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

### 轮次 2 — 用户回填 + 加工项选择
```
用户回填 form: name="遮光窗帘", price=50, selling_methods=["散剪","整卷"], door_widths=["2.8米"], sku_code="ZG-001"
→ interact(
    component="choice",
    title="选择加工项（可多选）",
    multiSelect=true,
    options=[
      {label:"1. 打孔加工 ¥8/米", value:"pi_a1b2c3d4e5f6g7h8"},
      {label:"2. S钩安装 ¥5/米", value:"pi_i9j0k1l2m3n4o5p6"},
      {label:"3. 韩式褶加工 ¥12/米", value:"pi_q7r8s9t0u1v2w3x4"}
    ]
  )
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
    processing_item_ids=["pi_a1b2c3d4e5f6g7h8", "pi_q7r8s9t0u1v2w3x4"],
    specifications={"克重":"200-300g","材质":"涤纶","功能":"遮光","工艺":"色织","风格":"现代简约","图案":"纯色"},
    unit="米", pricing_type="per_meter"
  )
→ ✅ "遮光窗帘（ZG-001）已创建并上架，关联 2 个加工项。"
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
用户回填 price=68, selling_methods=["散剪"] → 加工项 choice → confirm → validate_input → product_manage → 完成
```

关键点：识别结果直接预填，不做二次确认。

## 示例 3：信息不完整的引导流程

用户: "创建一个商品"

```
→ 💬 "好的，请提供：① 商品名称 ② 单价"
用户: "简约窗帘" → 💬 "价格是多少？"
用户: "38 一米" → 💬 "好的。售卖方式？散剪还是整卷？"
用户: "散剪" → category_manage(tree) → 💬 "窗帘分类如下：[分类树]。归入哪个？"
用户: "客厅窗帘" → 💬 "还需要货号，比如 JY-001，您可以改。"
用户: "JY-001" → processing_item_query → interact choice → confirm → validate_input → product_manage → 完成
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
