"""订单状态的**消费口径**（issue #8198 的 P2-2b）。

## 两层，各司其职

| 层 | 文件 | 谁写的 | 指什么 |
|---|---|---|---|
| 真值 | `order_status_generated.py`（**生成物**） | 生成器（源 = Java `OrderStatusTransitions`） | 订单状态的**全集**：7 个取值 + 流转表 + 标签 + 可编辑集合 |
| 口径 | 本文件 | 人 | Agent 工具面今天**暴露哪些**状态 |

**为什么中间还有一层口径**：生成物是真值，但「工具 schema 该放几个状态」是**产品口径**，
不是真值 —— 两者混在一起，会让「补一个状态到 Java」自动变成「放开一个 Agent 可写取值」
（那是行为变更，必须单独裁定）。所以窄化只在这里、只写一处，消费方一律引用本文件的常量。

## 今天的窄化：**不含** `packed`（冻结，行为零变化）

P2-2b 的硬约束是**前端/Agent 行为逐字不变**：今天 4 个工具 schema 的订单状态枚举都是
**6 个**（`pending` / `confirmed` / `producing` / `shipped` / `completed` / `cancelled`），
而 Java 的单一源已含 `packed`（issue #5648，2026-09-26 由工人在 H5 推进的打包态）。

⇒ 直接拿生成物的 7 个铺进 schema，等于**悄悄放开**「Agent 可以把订单改成 packed」。
本单不做这件事：`AGENT_ORDER_STATUSES` 显式排除 `PACKED`，取值与顺序都与改前逐字一致。

**重启条件**（把 `packed` 纳入 Agent 面 = 独立的行为变更单）：需要先裁定
① Agent 推进到 `packed` 是否是合法业务动作（工人动作 vs 商家动作）、② 权限码是否覆盖、
③ 状态机允许的目标集是否要在工具描述里同步。三条没裁之前，**窄化是默认**。
"""
from app.constants.order_status_generated import ORDER_STATUSES, PACKED

#: Agent 工具 schema / 前置校验闸门今天暴露的订单状态（**有序**，顺序即契约面顺序）。
#: 取值 = 生成物全集去掉 `PACKED`（用生成常量做排除，不写裸字面量）。
AGENT_ORDER_STATUSES: tuple[str, ...] = tuple(s for s in ORDER_STATUSES if s != PACKED)
