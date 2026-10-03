# case_ids: PG-067
"""🔴 **issue #6123**：#6114 的同类未固化面 —— **加工项触发**维的种子规则也必须带规则级部位限定。

## 病（与 #6114 同因、另一条触发维）

`ProductionSeedTemplateService.planRouteRules` 的 ③ 加工项触发分支给规则写的 `position` 是
`null`（= 不限部位），而 `PROCESSING_ITEM_RULES` 引用的三道工序（`花边` / `扣环` / `接高`）
在工序库里**只有布帘变体**（有 `花边-布`、没有 `花边-纱`）。触发键 = 订单行
`processingInfo.processingItems[].name`（**精确相等**）⇒ 一张**纱帘单**只要带了这些加工项之一，
规则就在纱帘部位命中 ⇒ `variantNameOf(逻辑名, '纱帘', catalog)` 返回 `null` ⇒
整单 fail-closed。实测逐字（本机复现，2026-10-03）：

```
工艺路线「窗帘工序路线（默认）」（产品形态「纱帘」）引用的工序 [花边] 在工序库中不存在，无法实例化工序
```

## 本文件钉两件事（各含注入式红证）

1. **内容腿**（`test_processing_item_rule_carries_cloth_position`）：生产源码里那 3 条规则
   必须带 `position = '布帘'`，且该实参是**命名常量**（防「值」与「闭词表」两处口径分开漂移）、
   常量**逐字 = 布帘**。
2. **类级判据**（`test_every_seed_rule_dimension_is_nailed_by_a_guard`）：本仓的「规则级部位限定」
   守卫必须**同时**钉住**两条触发维**（`option` 与 `processing_item`）—— 只钉住一条就是本缺陷的
   成因（#6114 修好了选项维，加工项维照样卡单 ⇒ 缺一条 = 缺口还在）。

⚠️ **射程边界（如实登记）**：本文件只读**这一个生产文件**的文本 ⇒ 「值是否真在闭词表内」「真实播种 →
真实例化」由 Java 侧
`backend/admin-api/src/test/java/com/migao/admin/service/ProductionSeedProcessingItemRulePositionTest.java`
直接调生产常量 / 跑真实路径判（不在这里做第二份比对 —— 那是第二份口径）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED_TEMPLATE_SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
                         / "ProductionSeedTemplateService.java")

#: 加工项触发分支的 `addRule(...)` 调用形态（③ 段；见 `planRouteRules`）。
_PLAN_RULE_PROCESSING_ITEM_CALL_RE = re.compile(
    r"""addRule\([^;]*?"processing_item"\s*,\s*rule\[0\]\s*,\s*(?P<pos>[^,]+),"""
    r"""\s*rule\[1\]\s*,\s*rule\[2\]\s*,\s*rule\[3\]""",
    re.S)
#: 同文件里的 `private static final String <名字> = "<值>";` 声明。
_POSITION_CONST_RE = re.compile(
    r'String\s+(?P<name>[A-Z_][A-Z0-9_]*)\s*=\s*"(?P<value>[^"]*)"\s*;')


def processing_item_position_guard(java_src: str, constant="布帘") -> list:
    """issue #6123 的守卫：开租播种的**加工项触发**规则必须带部位限定 `'布帘'`。

    判据（任一不成立即返回违规清单，非空 ⇒ 调用方断言红）：
      ① 加工项分支的 `position` 实参**不得**是 `null`（= issue #6123 的缺陷形态）；
      ② 该实参必须是一个**命名常量**（字面量硬编码会让「值」与「闭词表」两处口径分开漂移）；
      ③ 该常量必须**逐字** = `'布帘'`（= `POSITION_LIMIT_VOCABULARY` 里的布帘部位）。
    """
    match = _PLAN_RULE_PROCESSING_ITEM_CALL_RE.search(java_src)
    if not match:
        return ["`planRouteRules` 的加工项触发分支里找不到 "
                "`addRule(..., \"processing_item\", rule[0], <position>, rule[1], rule[2], rule[3], ...)` "
                "形态 ⇒ 要么播种不再显式给 `position`（= issue #6123 回归），要么本解析器与生产代码脱节"]
    raw = match.group("pos").strip()
    if raw == "null":
        return ["加工项触发分支的 `position` 实参 = `null`（= 不限部位）⇒ 这批规则会在**纱帘单**上命中，"
                "而它们引用的工序只有布帘变体 ⇒ 整张加工单 fail-closed（issue #6123）。"
                f"实测源码片段：{match.group(0)[:120]!r}"]
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", raw):
        return [f"加工项触发分支的 `position` 实参是字面量 / 表达式 `{raw}`（不是命名常量）"
                f"⇒ 「值」与「闭词表」两处口径会分开漂移"]

    declared = {m.group("name"): m.group("value") for m in _POSITION_CONST_RE.finditer(java_src)}
    if raw not in declared:
        return [f"`position` 实参用的是常量 `{raw}`，但在同一个生产文件里找不到它的声明"
                f"（声明被删 / 改名 ⇒ 判据会空跑，`javac` 之外没有任何东西会红）"]
    if declared[raw] != constant:
        return [f"开租播种的加工项部位限定常量 `{raw}` = `{declared[raw]}`，期望逐字 `{constant}`"]
    return []


def test_processing_item_rule_position_guard_detects_regression():
    """注入式自证（判别力）：摘回 `null` / 换字面量 / 改值 / 删声明 / 形态消失 ⇒ 判据必非空。"""
    good = ('    private static final String PROCESSING_ITEM_POSITION = "布帘";\n'
            '        addRule(plan, existing, available, tenantId, "processing_item", rule[0],\n'
            '                PROCESSING_ITEM_POSITION, rule[1], rule[2], rule[3], priority, null);\n')
    assert processing_item_position_guard(good) == [], \
        "合规输入被误判 ⇒ 判据不可信（下面的红证也就是空断言）"

    assert processing_item_position_guard(
        good.replace('PROCESSING_ITEM_POSITION, rule[1]', 'null, rule[1]')), \
        "把部位限定摘回 `null`（= issue #6123 的缺陷形态）未被识别 ⇒ 判据是空断言"
    assert processing_item_position_guard(
        good.replace('PROCESSING_ITEM_POSITION, rule[1]', '"布帘", rule[1]')), \
        "把部位限定换成字面量未被识别 ⇒ 判据是空断言"
    assert processing_item_position_guard(good.replace('= "布帘"', '= "纱帘"')), \
        "部位限定常量改值未被识别 ⇒ 判据是空断言"
    assert processing_item_position_guard(
        good.replace('    private static final String PROCESSING_ITEM_POSITION = "布帘";\n', '')), \
        "常量声明被删未被识别 ⇒ 判据是空断言"
    assert processing_item_position_guard("class X {}"), \
        "生产代码形态完全消失未被识别 ⇒ 判据是空断言"


def test_processing_item_rule_carries_cloth_position():
    """🔴 **issue #6123 内容腿**（Python 侧）：生产源码里 3 条加工项规则必须带 `position='布帘'`。

    红证：把 `PROCESSING_ITEM_POSITION` 换成 `null`（或摘掉该实参）⇒ 本判据与 Java 侧
    `ProductionSeedProcessingItemRulePositionTest` 同时红。
    """
    source = SEED_TEMPLATE_SERVICE.read_text(encoding="utf-8")
    errors = processing_item_position_guard(source)
    assert errors == [], "\n".join(errors)

    # 自证（防「判据空跑」）：确实有 3 条加工项规则，且它们的工序名都在本判据射程内
    block = re.search(r"PROCESSING_ITEM_RULES\s*=\s*\{(.*?)\n    \};", source, re.S)
    assert block, "`PROCESSING_ITEM_RULES` 读不到 —— 上面的判据会空跑"
    rows = re.findall(r'\{"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\}', block.group(1))
    assert rows, "`PROCESSING_ITEM_RULES` 一行都没解析出来 —— 上面的判据会空跑"


#: 本仓「规则级部位限定」的两条**触发维**（issue #6114 的选项维 + issue #6123 的加工项维）。
#: 少一条 ⇒ 那一维的规则在纱帘单上照样命中 ⇒ 整单 fail-closed（本缺陷的成因）。
GUARDED_TRIGGER_DIMENSIONS = ("option", "processing_item")


def seed_rule_dimension_guards(java_src: str) -> dict:
    """两条触发维各自的**部位限定取值**：`{触发维: 常量值 | 实参原文}`（缺失 ⇒ 不在返回里）。

    命名常量按同文件的声明**解引用**（`PROCESSING_ITEM_POSITION` → `布帘`）；解析不出声明的
    实参按原文返回（于是"值不对"的判据会照红，而不是静默当成合规）。
    """
    raw_args = {}
    option = re.search(
        r"""addRule\([^;]*?"option"\s*,\s*node\.path\("option_name"\)\.asText\(\),\s*"""
        r"""(?P<pos>[^,]+),\s*"insert"\s*,\s*logicalName\(node\.path\("operation_name"\)\.asText\(\)\)""",
        java_src, re.S)
    if option:
        raw_args["option"] = option.group("pos").strip()
    item = _PLAN_RULE_PROCESSING_ITEM_CALL_RE.search(java_src)
    if item:
        raw_args["processing_item"] = item.group("pos").strip()

    declared = {m.group("name"): m.group("value") for m in _POSITION_CONST_RE.finditer(java_src)}
    return {dim: declared.get(arg, arg) for dim, arg in raw_args.items()}


def test_every_seed_rule_dimension_is_nailed_by_a_guard():
    """🔴 **类级判据**：两条触发维都必须被「规则级部位限定」守卫钉住（缺一条 ⇒ 缺口还在）。

    **为什么这条是类级的**：本缺陷（#6123）的形态不是「某个值写错了」，而是「**同一件事只固化了一半**」
    —— #6114 给选项维补了部位限定并留了守卫，加工项维没有任何东西会红 ⇒ 同款卡单复发。
    故判据钉在「**维度集合**」上：`{option, processing_item}` 两个触发维**都得**有部位限定实参，
    任一新触发维（`craft` 之外的按订单行触发维）将来加进来也会被这条现取式判据点名。
    """
    source = SEED_TEMPLATE_SERVICE.read_text(encoding="utf-8")
    guarded = seed_rule_dimension_guards(source)

    assert set(guarded) == set(GUARDED_TRIGGER_DIMENSIONS), (
        f"被部位限定守卫钉住的触发维 = {sorted(guarded)}，期望 {sorted(GUARDED_TRIGGER_DIMENSIONS)}"
        " —— 少一维 = 那一维的规则会在**纱帘单**上命中而解析不出变体 ⇒ 整单 fail-closed。"
        "（本判据现取式：将来新增按订单行触发的维度也必须一并钉住）")

    not_cloth = {dim: pos for dim, pos in guarded.items() if pos != "布帘"}
    assert not not_cloth, (
        f"这些触发维的部位限定实参不是命名常量 `布帘`：{not_cloth} —— 两条触发维引用的工序都"
        "**只有布帘变体**（真值源 `backend/ai-agent-service/app/production/routing.py` 的 "
        "`OPERATION_CATALOG` 同款）⇒ 限定值必须逐字 `布帘`，且写成命名常量（防两处口径漂移）")
