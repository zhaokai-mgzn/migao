# case_ids: MC-207
"""订单状态**三轴分离**的判据：动作面冻结、显示面放开、本体面独立（issue #8686）。

## 为什么这个文件存在

`packed`（已打包）在 DB 里是第 **7** 个取值，而 **Agent 工具面**只暴露 **6** 个、**前端展示层**
此前也没有「已打包」标签、**本体词表**（`app/ontology`）只登记 **6** 个 —— 三处**有意不同源**。
此前没有任何东西会把「悄悄同步」判红：裁定的理由只活在
`backend/ai-agent-service/app/constants/order_status.py` 的 docstring 里，而 **docstring 不会红**。

## 裁定的出处（成文，逐字引用）

`backend/admin-api/src/main/java/com/migao/admin/service/OrderShipmentService.java` 的打包方法 javadoc：

    口径（用户 2026-09-26 裁定「打包与发货都是工人的动作」）：`packed` 由工人在 H5 推进

⇒ `packed` 的动作主体是**工人**，B 端 Agent 服务的是**商家**：让商家侧 AI 去推进工人动作
不是「多做一点」，是**把动作主体搞错**。故 Agent 动作面**保持排除** `packed`（判据 1/2），
而商家侧展示**必须看得到**「已打包」（显示面判据在 `frontend/admin-web` 的 vitest，同一用例号 MC-207）。

## 三轴登记（本文件守护的正是这张表）

| 轴 | 取值 | 载体 | 今天 |
|---|---|---|---|
| Agent 动作面 | **6** | `app/constants/order_status.py::AGENT_ORDER_STATUSES` → 4 个工具 schema | 不含 `packed`（判据 1/2 锚住） |
| DB 全集 | **7** | 生成物 `app/constants/order_status_generated.py` | 含 `packed`（判据 1 用差集证明） |
| 本体 `order.status` | **6**、无 `packed` | `app/ontology/{loader.py,schema.yaml}`（独立真值源） | 有意不动（判据 3/4 锚住） |

**收敛条件**：三处同源需**同时**满足 —— ① 业务裁定 `packed` 属商家可推进动作（推翻 2026-09-26 裁定）；
② 权限码覆盖；③ 状态机允许的目标集写进工具描述；④ 本体侧同步扩词表且保留另一侧独立校验。

## 红证（注入式，双向；每条都能单独变红）

- 把 `AGENT_ORDER_STATUSES` 改成全集（`= ORDER_STATUSES`）⇒ 判据 1 红，报「Agent 面又拿到 packed 了」；
- 把构造式换成手写 6 个字面量 ⇒ 判据 2 红（构造式不再是「全集 − PACKED」）；
- 删掉模块 docstring 里的裁定出处 ⇒ 判据 2 红（理由不再可追溯）；
- 把本体词表补成 7 个 / 加 `packed` ⇒ 判据 3 红；schema.yaml 同步扩 ⇒ 判据 4 红。
"""
from __future__ import annotations

import ast
from pathlib import Path

import app.constants.order_status as order_status_module
from app.constants.order_status import AGENT_ORDER_STATUSES
from app.constants.order_status_generated import ORDER_STATUSES, PACKED
from app.ontology.loader import STATUS_LEXICON, load_ontology

#: 独立硬编码的真值（**不**从被测模块反推 —— 反推会让「改了生成物」同时改判据 = 假绿）。
#: 顺序 = Java `OrderStatusTransitions` 的常量声明顺序（= 生成物顺序）。
CANONICAL_DB_STATUSES = (
    "pending", "confirmed", "producing", "packed", "shipped", "completed", "cancelled",
)

#: Agent 动作面 / 本体词表冻结的 6 个（不含 `packed`，顺序同生成物去掉打包态）。
SIX_WITHOUT_PACKED = ("pending", "confirmed", "producing", "shipped", "completed", "cancelled")

#: 裁定出处（模块 docstring 必须一直引用它 —— 出处被删则判据 2 红）。
RULING_SOURCE = "backend/admin-api/src/main/java/com/migao/admin/service/OrderShipmentService.java"
RULING_DATE = "2026-09-26"
RULING_QUOTE = "打包与发货都是工人的动作"

PACKED_HINT = (
    "依据 = 用户 2026-09-26 裁定「打包与发货都是工人的动作」"
    f"（{RULING_SOURCE} 的打包方法 javadoc）；让商家侧 AI 推进工人动作是动作主体错位。"
)


def _module_source() -> str:
    return Path(order_status_module.__file__).read_text(encoding="utf-8")


def _top_level_assigned_value(name: str) -> ast.expr:
    """取模块顶层 `name` 的赋值表达式（`Assign` 与带注解的 `AnnAssign` 都认）。"""
    tree = ast.parse(_module_source())
    for node in tree.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == name:
            if value is None:
                raise AssertionError(f"`{name}` 只有类型注解、没有取值 —— 判据面读不到构造式")
            return value
    raise AssertionError(f"模块里找不到 `{name}` 的顶层赋值 —— 判据面本身失效（不是被测行为红）")


def test_agent_action_face_stays_the_full_set_minus_packed() -> None:
    """动作轴：Agent 面 == DB 全集 − {PACKED}（改成全集 / 改成别的集合 ⇒ 具名红）。"""
    expected = tuple(status for status in CANONICAL_DB_STATUSES if status != PACKED)
    assert PACKED in ORDER_STATUSES, (
        f"生成物里没有 `{PACKED}` ⇒ 「差集恰好是打包态」这条断言失去意义（DB 全集 = {ORDER_STATUSES}）"
    )
    assert AGENT_ORDER_STATUSES == expected, (
        f"Agent 面又拿到 packed 了：AGENT_ORDER_STATUSES 必须 == 生成物全集 − {{PACKED}}；"
        f"现取 {AGENT_ORDER_STATUSES}，期望 {expected}。" + PACKED_HINT
    )
    assert set(ORDER_STATUSES) - set(AGENT_ORDER_STATUSES) == {PACKED}, (
        "Agent 面与 DB 全集的差集不是恰好 {packed}：现取 "
        f"{sorted(set(ORDER_STATUSES) - set(AGENT_ORDER_STATUSES))}（DB 全集 = {ORDER_STATUSES}）。" + PACKED_HINT
    )


def test_agent_status_constant_is_derived_from_the_full_set_not_hand_copied() -> None:
    """构造式锚点：`tuple(s for s in ORDER_STATUSES if s != PACKED)` —— 改窄化逻辑即红。

    为什么连**构造式**也要锚：手写 6 个字面量今天取值一样（判据 1 绿），但集合的**来源**已经
    从「DB 全集 − 打包态」变成了第二份真值 —— 下一次改单一源时它就会静默分叉（MC-204 的同族缺陷）。
    """
    value = _top_level_assigned_value("AGENT_ORDER_STATUSES")
    hint = (
        "AGENT_ORDER_STATUSES 的构造式必须仍是 `tuple(s for s in ORDER_STATUSES if s != PACKED)`："
        "改成全集 = 放开 packed；手写字面量 = 第二份真值；改成别的集合 = Agent 面漂移。" + PACKED_HINT
    )
    assert isinstance(value, ast.Call), hint
    assert isinstance(value.func, ast.Name) and value.func.id == "tuple", hint
    assert len(value.args) == 1 and isinstance(value.args[0], ast.GeneratorExp), hint
    gen = value.args[0]
    assert len(gen.generators) == 1, hint
    comprehension = gen.generators[0]
    assert isinstance(gen.elt, ast.Name), hint
    assert isinstance(comprehension.target, ast.Name) and comprehension.target.id == gen.elt.id, hint
    assert isinstance(comprehension.iter, ast.Name) and comprehension.iter.id == "ORDER_STATUSES", hint
    assert len(comprehension.ifs) == 1, hint
    condition = comprehension.ifs[0]
    assert isinstance(condition, ast.Compare), hint
    assert len(condition.ops) == 1 and isinstance(condition.ops[0], ast.NotEq), hint
    assert isinstance(condition.left, ast.Name) and condition.left.id == gen.elt.id, hint
    assert isinstance(condition.comparators[0], ast.Name), hint
    assert condition.comparators[0].id == "PACKED", hint


def test_ruling_behind_the_exclusion_is_cited_where_the_narrowing_lives() -> None:
    """理由即判据：排除 `packed` 的**出处**（文件 + 裁定日期 + 原文）必须留在模块 docstring 里。

    「只活在 docstring 里的理由」此前不会红 —— 本判据让它会红：删掉出处 / 删掉原文 /
    删掉三轴不同源的登记 / 删掉收敛条件，各自具名报出（issue #8686 的 ①）。
    """
    doc = order_status_module.__doc__ or ""
    assert RULING_SOURCE in doc, (
        f"`packed` 排除理由的**出处**被删了：docstring 必须引用 `{RULING_SOURCE}`（用户 {RULING_DATE} 裁定）"
    )
    assert RULING_QUOTE in doc, (
        f"裁定**原文**「{RULING_QUOTE}」从 docstring 里消失 ⇒ 下一个人看不出这是已成文的用户裁定，"
        "而不是随手写的约束"
    )
    assert RULING_DATE in doc, f"裁定**日期** `{RULING_DATE}` 从 docstring 里消失（出处不可追溯）"
    assert "暂不同源" in doc, (
        "三轴（Agent 动作面 6 / DB 全集 7 / ontology 6）**不同源**的登记被删了："
        "docstring 必须显式写「暂不同源」（issue #8686 的 ③）"
    )
    assert "收敛条件" in doc, "三处词表何时收敛的**收敛条件**被删了（issue #8686 的 ③）"


def test_ontology_order_status_lexicon_stays_an_independent_six_state_source() -> None:
    """本体轴：`order.status` 词表 == 6 个且**不含** packed（被「顺手同步」成 7 个 ⇒ 红）。

    本体是**交叉校验的另一侧**（独立真值源）：同步它不叫「对齐」，叫**失去第二侧**。
    """
    lexicon = tuple(STATUS_LEXICON["order.status"])
    assert lexicon == SIX_WITHOUT_PACKED, (
        "本体 `order.status` 词表变了：现取 "
        f"{lexicon}，期望 {SIX_WITHOUT_PACKED}（6 个、不含 packed）。" + PACKED_HINT
    )
    assert len(lexicon) == 6, f"本体 order.status 词表必须恰好 6 个（现取 {len(lexicon)} 个）"
    assert PACKED not in lexicon, (
        "本体 order.status 词表被「顺手同步」出了 packed ⇒ 独立真值源失效、交叉校验失去另一侧。" + PACKED_HINT
    )
    assert set(ORDER_STATUSES) - set(lexicon) == {PACKED}, (
        "本体词表与 DB 全集不再只差 packed 一个：现取 "
        f"{sorted(set(ORDER_STATUSES) - set(lexicon))}（DB 全集 = {ORDER_STATUSES}）"
    )


def test_ontology_schema_order_status_carries_the_same_six_state_vocabulary() -> None:
    """schema.yaml 落到 `Ontology` 上的 `order.status` 枚举也必须还是 6 个、不含 packed。"""
    ontology = load_ontology()
    assert "order" in ontology.objects, "本体 schema 里没有 order 对象（判据面失效，不是被测行为红）"
    status_property = ontology.objects["order"].properties["status"]
    assert status_property.enum_values == STATUS_LEXICON["order.status"], (
        "schema.yaml 的 order.status 枚举与词表不一致（loader 的加载期铁律校验应已先行拒绝）"
    )
    assert PACKED not in status_property.enum_values, (
        "schema.yaml 的 order.status 枚举混进了 packed —— 本侧必须保持 6 个（issue #8686 的 ③）。" + PACKED_HINT
    )
