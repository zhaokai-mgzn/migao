# Agent Skill/Tool 设计范式

> 米宝 Agent 的 Skill Prompt 和 Tool Schema 设计规范。

## 核心原则

**ReAct 自主推理 + Tool Schema 驱动行为 + Skill Prompt 只放领域知识。**

三层分离：

| 层 | 放什么 | 不放什么 |
|----|--------|---------|
| **Tool Schema** (description) | 何时用、前置条件、参数含义、反例 | — |
| **Skill Prompt** | 领域默认值、字段格式、术语映射、业务规则 | ❌ 行为指令（"先调X再调Y"） |
| **Base Prompt** (identity + principles) | 身份、安全铁律、回复风格 | ❌ 领域知识 |

## 一、Tool Schema 设计

**每个 tool 的 `description` 必须回答 LLM 三个问题：**

1. **何时用** — 用户说什么时触发
2. **前置条件** — 需要什么数据才能调
3. **与相似 tool 的区别** — 什么情况下不调它

### 正确示例

```python
name = "processing_item_query"
description = (
    "查询店铺加工项目录。用于创建流程阶段2（用户已确认名称/价格等基本信息后）。"
    "支持按 keyword/category_id/status 筛选。"
    "创建/修改/删除加工项用 processing_item_manage。READONLY"
)
```

```python
name = "order_create"
description = (
    "创建新订单。用户说'创建订单''下单'时直接调用，不要先调 product_search。"
    "商品明细接受用户口头提供的信息，无需验证。"
    "必填: customer_name + customer_phone + items。缺字段时引导补充。WRITE"
)
```

### 反例

```python
# ❌ 太简略，LLM 不知道何时用
description = "查询加工项"

# ❌ 只有触发条件，没有前置条件
description = "用户说'加工项'时调用"

# ❌ 行为指令写在这里不如写在 tool schema
```

## 二、Skill Prompt 设计

**只放 LLM 无法从 tool schema 推断的领域知识。**

### 应该放的

- 智能默认值（如窗帘默认单位="米"、默认门幅="2.8米"）
- 字段格式规范（如颜色格式 "色号 颜色名"）
- 术语映射（如 散剪=bulk_cut, 整卷=full_roll）
- 业务枚举值（如 specifications 的可选维度）
- 展示格式指引（如表格结构、emoji 用法）

### 不应该放的

- ❌ "先调 X，再调 Y" → Tool schema
- ❌ "禁止调 X" → Tool schema 的反例说明
- ❌ "用户说 X 时进入下一步" → LLM ReAct 推理
- ❌ "不要只查不创建" → Tool schema 的前置/触发

### 正确示例

```python
PRODUCT_SYSTEM_PROMPT = """## 创建商品需要的字段

| 字段 | 必填 | 如何获取 |
|------|------|---------|
| name | 是 | 用户提供 |
| price | 是 | 用户提供 |
| sku_code | 是 | 引导用户 |
| category_id | 是 | category_manage(tree) |
| selling_methods | 否 | 默认["散剪","整卷"] |

## 智能默认

| 字段 | 默认值 | 何时用 |
|------|--------|--------|
| unit | "米" | 窗帘品类 |
| door_widths | ["2.8米"] | 用户未指定时 |

## 颜色

有色号→"色号 颜色名"（"2699-01 白色"），无色号→颜色名。

## 术语

散剪=bulk_cut / 整卷=full_roll
"""
```

### 反例

```python
# ❌ 行为指令不应在 skill prompt 中
PRODUCT_SYSTEM_PROMPT = """## 创建流程
① 名称+价格 ② 分类 ③ 货号 ...
⚠️ 禁止阶段1调 category_manage
⚠️ 用户选完加工项后禁止重新查询
"""
```

## 三、边界：什么时候用代码兜底

**10% 的场景 LLM 即使有完美 schema 也做不对，这时用代码：**

| 场景 | 代码方案 |
|------|---------|
| 加工项选择组件渲染 | auto-interact PostHook（自动构造 interact choice） |
| 死循环防护 | SessionMemory flag（同一 session 只触发一次） |
| 用户取消 | 关键词检测 + 跳过 tool loop |
| 意图路由 | L1 关键词匹配 + L2 LLM 分类 |

**判断标准**：如果改了 3 次 prompt 还修不好 → 就是代码该管的。

## 四、设计检查清单

新增或修改 Skill/Tool 时：

- [ ] Tool description 回答了"何时用、前置条件、反例"三个问题？
- [ ] Skill prompt 只含领域知识，没有行为指令？
- [ ] 行为指令是否在 tool schema 中（而非 prompt）？
- [ ] 是否需要代码兜底（连续 3 次 prompt 改不好）？
- [ ] Base prompt（identity + principles）的内容没有在 skill prompt 中重复？
