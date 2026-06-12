# Product Skill — 正确执行示例

## 示例 1：完整创建流程（form → choice → confirm → 执行）

用户: "创建一个遮光窗帘，价格 50 元"

### Step 1: 信息收集
米宝先调 category_manage(action="tree") 获取分类树，然后回复:
```
好的，我来帮您创建商品！请提供以下信息：
• 商品名称（必填）
• 价格（必填，元）
• 颜色（可选，多个用逗号分隔）
• 售卖方式（可选：散剪/整卷/按片）
• 分类（可选，从分类树中选择）
当前分类：窗帘布艺（卧室系列/客厅系列）
```
（不使用 interact form，改用文字引导收集信息）

### Step 2: 用户提供信息 → 确认加工项
用户消息: "遮光窗帘，50元，米白色，散剪"
米宝先调 processing_item_query 获取加工项列表，然后回复:
```
interact(component="choice", title="选择关联的加工项（可多选）",
  multiSelect=true,
  options=[
    {label:"打孔加工 - ¥8/米", value:"pi_punch_001"},
    {label:"挂钩加工 - ¥2/个", value:"pi_hook_001"},
    ...
  ])
```

### Step 3: 用户选完 → 确认卡片（interact confirm）【强制步骤】
米宝调:
```
interact(component="confirm", title="确认创建商品",
  confirmValue="确认创建商品",
  fields=[
    {label:"商品名称", value:"遮光窗帘"},
    {label:"价格", value:"50 元"},
    {label:"加工项", value:"打孔加工、挂钩加工"},
  ])
```

### Step 4: 用户点确认 → 执行创建
用户消息: "确认创建商品"
米宝调:
```
product_manage(action="create", name="遮光窗帘", price=50, processing_item_ids=["pi_punch_001", "pi_hook_001"])
```
米宝回复: "商品【遮光窗帘】创建成功！"


## 示例 2：图片识别 + 创建

用户上传窗帘图片，说: "创建这个商品"

米宝首先识别图片内容，然后:
1. 调 interact form（预填识别到的信息：名称、色号、材质等）
2. → choice（选加工项）
3. → confirm（确认）【强制】
4. → product_manage（执行）

**关键**: 图片识别结果全部预填到 form 中，不要在文本描述里说"我识别到了..."然后让用户手动输入。


## 示例 3：信息不完整时的处理

用户: "创建一个商品"

米宝调:
```
interact(component="form", title="创建商品",
  formFields=[
    {key:"name", label:"商品名称", placeholder:"请输入商品名称", required:true},
    ...
  ])
```
**不要**编造商品名称为"上坡"或其他虚假名称。留空让用户填写。


## 反例（禁止行为）

❌ 跳到步骤: form → 直接调 product_manage（跳过 choice 和 confirm）
❌ 编造数据: 用户没说价格，LLM 自己编一个 100
❌ 同一 turn 弹多个组件: form + choice 一起发
❌ 纯文本回复 "已弹出表单": 必须实际调用 interact tool
❌ confirmValue 用默认 "确认": 必须包含上下文如 "确认创建商品"
❌ 收集完信息后拒绝创建: product_skill 有 product_manage 工具，必须使用
