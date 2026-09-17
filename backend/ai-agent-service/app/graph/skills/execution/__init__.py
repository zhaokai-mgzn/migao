"""`execute_skill` 的三段实现（issue #4049；拆分源头是「关联 #4043」的 S3 条）。

## 为什么有这一层

`base_skill.execute_skill` 曾是**单函数 1699 行**、内含 9 类职责 ⇒ #4043 的其余四个包
（S-A / S-B / S-C / T-B）只能改同一个文件、只能串行排队。按职责切成三段后，
四个包可以各改一个文件：

| 模块 | 原 `execute_skill` 分节 | 职责 |
|---|---|---|
| `prepare_turn` | 0~6 节 | 防御层（速率/截断）/ 上下文与工具准备 / 消息准备 / LLM 准备 / system prompt 组装 / 跨轮注入与压缩 / Vision 分支 |
| `react_turn` | 第 7 节 | ReAct 循环（写门禁链、工具调用、卡片发射、纠偏） |
| `finalize_turn` | 8.3b~8.6 + 9/10 节 | 补发确认卡兜底 / 确认-执行链代码侧收口 / 草稿态回复归一 / 返回值组装 / 跨轮 `pending_skill` 持久化 |

## ⚠️ import 方向是**单向**的 —— 别「整理」

```text
app/graph/skills/base_skill.py ──(函数体内 import，调用期)──▶ execution/*
        ▲                                                        │
        └────────────(模块顶层 import，加载期)───────────────────┘
```

* 三个模块**顶层** `from app.graph.skills.base_skill import ...` 取**留在原文件**的模块级
  助手（`_execute_tool_safe` / `_self_correct_retry` / `_build_system_prompt` / `_inject_*` …）
  与常量 —— 它们**不搬**（`_execute_tool_safe` 的 `result_dict` 字面量是
  `tests/test_contract_wiring.py` 的真相源，搬走该守卫会 fail-closed 报错）。
* `base_skill.execute_skill` 的三条 import 写在**函数体内** —— 于是**加载期只有一个方向**。
  若把它们"整理"到 `base_skill` 模块顶层，加载期立刻成环：
  `base_skill` → `execution.react_turn` → `base_skill`（后者只加载到一半 ⇒ 取不到助手）。

## 搬迁纪律（本包的硬约束）

三段函数体是原 `execute_skill` 对应行的**去缩进逐字副本**（一个字符都没改）：
不改语义、不改话术、不"顺手优化"分支、不重排语句、不改注释。唯一的机械改动是
函数头收拢入参 + 函数尾补 `return` 交回状态。结构判据见
`tests/unit/test_execute_skill_split.py`（壳 ≤ 300 行、三段在、守卫未搬走、`nonlocal` 锚点在）。
"""
