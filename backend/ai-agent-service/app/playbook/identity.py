"""口径卡的**身份**（issue #8175）：一条口径在哪个维度上是「同一条」。

## 为什么单独抽一个模块

「同一条口径」这个判定出现在**四个**地方，必须是同一份实现：

| 位置 | 用途 |
|---|---|
| `app/playbook/ingest.py` | 落库时判断「同 key 不同值」⇒ 两条并存 + 打 `conflict_key` |
| `app/playbook/prompt.py` | **读面兜底**：同 key 的两条 active 只许渲染一条（脏数据也一样） |
| `app/playbook/lifecycle.py` | 衰减/晋升的选举与「同组已有 active ⇒ 拒绝晋升」 |
| admin-api `PlaybookService` | 审批第二条同 `conflict_key` 的卡 ⇒ 默认拒绝（同一语义的写面实现） |

**为什么 key 不吃 `correct`**：key 回答的是「在什么情境下该按某条口径办」，`correct` 是「怎么办」。
同情境两个说法是**冲突**（两条并存待裁定），不是两条不同的口径。

**为什么 key 的输入是规范化 JSON**：`{"a":1,"b":2}` 与 `{"b":2,"a":1}` 是同一条条件。
落库面的 `trigger_json` 由本模块的 `canonical()` 产出，因此同一条口径在任何写路径上都得到同一个 key
（跨语言实现见 admin-api 的 `PlaybookService`：它只做**等价比较**，不复制哈希算法 ——
按 JSON 树比较，避免「两套 canonical 算法悄悄漂移」这种最难发现的形态）。
"""

import json
from hashlib import sha1
from typing import Any, Dict, Optional

#: 当前唯一的适用范围（P1；`role` 的晋升/衰减属 P2 未做面，见 PR body）
SCOPE_TENANT = "tenant"


def canonical(condition: Any) -> str:
    """条件的规范化 JSON：键排序 + 固定分隔符 + 不转义中文（同一条件 ⇒ 同一串）。"""
    return json.dumps(condition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def playbook_key(
    trigger: Any,
    scope: str = SCOPE_TENANT,
    scope_role: Optional[str] = None,
) -> str:
    """同一条口径的**身份**：范围 + 触发条件（`correct` 是「值」，不参与）。"""
    raw = f"{scope or ''}|{scope_role or ''}|{canonical(trigger)}"
    return sha1(raw.encode("utf-8")).hexdigest()[:16]


def value_key(
    trigger: Any,
    correct: Any,
    scope: str = SCOPE_TENANT,
    scope_role: Optional[str] = None,
) -> str:
    """同一身份下的**同一个说法**：`(key, 正解)` —— 晋升计数按它分组（不同说法不能合并计数）。"""
    raw = f"{playbook_key(trigger, scope, scope_role)}|{correct if correct is not None else ''}"
    return sha1(raw.encode("utf-8")).hexdigest()[:16]


def group_key(card: Dict[str, Any]) -> str:
    """一张卡在冲突消解里的组标识：**按内容现算**，不信任落库时打好的标记。

    为什么不信 `conflict_key`：它可能缺（P1 之前落的历史行）、可能过期（标记之后又被改过）。
    读面在**当场**要防的是「prompt 里出现互相矛盾的两条」，所以兜底必须由内容决定。
    """
    return playbook_key(
        card.get("trigger"),
        card.get("scope") or SCOPE_TENANT,
        card.get("scope_role"),
    )
