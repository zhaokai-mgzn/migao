# case_ids: PR-008
"""**抄写 vs 推理**的分工按字段定死（issue #6386，2026-10-05 真跑验收发现）。

## 这条判据要治什么

真跑读数（用户提供的色卡图 + `deepseek-flash`，同图同提示词、仅 `hint` 不同，跑两次）：

| 格 | 拿到的来源标记 | 实际来源 | 图上有吗 |
|---|---|---|---|
| `name` = `常青藤系列窗帘面料色卡` | `[图片识别]`（=抄的） | vision **生成**的 | ❌ |
| `description` = `<p>常青藤系列…轻柔手洗…</p>` | `[图片识别]` | vision **生成**的 | ❌ |

两次 `description` 文案**不同** ⇒ 生成而非抄写。更糟的是模型**一边给值、一边**把
`reason` 写成「图片未给出该字段」—— 自己都说图上没有。

⇒ 两个后果：
1. **来源标记撒谎**：「猜的」被标成「抄的」，比留空更危险（来源标记的全部意义就是区分两者）；
2. **米宝生成的描述永远落不了值**：落值规则「识别有值 ⇒ 解读不覆盖」是对的，
   但 `description` 已被 vision 抢先填 ⇒ 米宝那段被丢掉。

用户 2026-10-05 裁定（逐字「B」）= 我在选项里给的 (b)：**`name` 让米宝推、标 `[米宝解读]`**。

## 判据分两层

- **实例**：`name` / `description` 必须来自 `[米宝解读]`、vision 的字段表里不得有这两键；
- **类级元守卫**：**凡 `recognizable=False` 的字段，`[图片识别]` 直填路径永不许产出它的值**
  —— 将来新增同类字段（例如「卖点文案」）自动受约束，不必再想起这条。
"""
from __future__ import annotations

import pytest

from app.vision import deep_channel, recognizer
from app.vision.targets import TARGET_FIELDS

#: 真跑实测被模型编造的两格（本单的实例面）
GENERATED_KEYS = ("name", "description")


def _product_field(key):
    return next(f for f in TARGET_FIELDS["product"] if f.key == key)


# ══════════════════════════════════════════════════════════════════════════════
# 一、字段表：谁是「图上的事实」、谁是「文案」
# ══════════════════════════════════════════════════════════════════════════════

def test_generated_fields_are_marked_not_recognizable():
    """`name` / `description` 的 `recognizable` 必须为 `False`。

    红证：把 `TargetField.recognizable` 删掉 / 改回 `True` ⇒ 本判据红。
    """
    for key in GENERATED_KEYS:
        assert _product_field(key).recognizable is False, (
            f"`{key}` 是文案不是图上的事实 ⇒ 必须 recognizable=False"
        )


def test_copied_fields_stay_recognizable():
    """反向对照组：**真能印在图上**的格子照旧 `recognizable=True`。

    防「把识别面一刀砍掉」的假绿 —— 若这里全变 `False`，本单就变成了「禁用识别」。
    """
    for key in ("color", "material", "craft", "door_width", "price"):
        assert _product_field(key).recognizable is True, f"`{key}` 应仍由 vision 直接抄"


def test_vision_schema_excludes_generated_fields():
    """**发给 vision 的**字段表里不得有 `name` / `description`（= 模型连编的机会都没有）。

    红证：`recognizer._schema_for` 改回直接返回 `TARGET_FIELDS[target_type]` ⇒ 本判据红。
    """
    keys = [f.key for f in recognizer._schema_for("product")]
    for key in GENERATED_KEYS:
        assert key not in keys, f"`{key}` 不该出现在发给 vision 的字段表里：{keys}"
    assert "color" in keys and "door_width" in keys, f"识别面被误砍：{keys}"


def test_page_fill_schema_keeps_all_fields():
    """页面填充用的字段表**仍含**这两格 —— 否则它们会从表单上消失。

    （两处 `_schema_for` 语义不同：`recognizer` = 发给模型问什么；
    `deep_channel` = 页面上要出现哪些格子。）
    """
    keys = [f.key for f in deep_channel._schema_for("product")]
    for key in GENERATED_KEYS:
        assert key in keys, f"`{key}` 必须仍在页面字段表里（否则表单少一格）：{keys}"


# ══════════════════════════════════════════════════════════════════════════════
# 二、类级元守卫：`recognizable=False` ⇒ `[图片识别]` 永不许直填
# ══════════════════════════════════════════════════════════════════════════════

def _recognized_shape(fields):
    """把**已识别**字段摆成内核交回 `build_page_fill` 的形状。"""
    return [
        {"key": f["key"], "label": f["label"], "value": "图上抄来的值", "confidence": 0.95, "reason": None}
        for f in fields
    ]


@pytest.mark.parametrize("target_type", sorted(TARGET_FIELDS))
def test_non_recognizable_fields_are_never_filled_as_recognized(target_type):
    """**类级**：`recognizable=False` 的字段，就算内核硬塞给它一个值，也不得成为 `[图片识别]`。

    做法：把**全量**字段表都摆成「已识别且有值」再跑 `build_page_fill`
    ⇒ 其中 `recognizable=False` 的那些格必须**不是** `[图片识别]` 来源。

    红证：把 `build_page_fill` 的直填条件改成不看 `field.recognizable`（或把该标志删掉）
    ⇒ 本判据红（`name` 会带着 `[图片识别]` 出现）。
    """
    schema = deep_channel._schema_for(target_type)
    fields = _recognized_shape([
        {"key": f.key, "label": f.label} for f in schema
    ])
    plan = deep_channel.build_page_fill(target_type, fields)
    by_key = {c["key"]: c for c in plan["fields"]}

    offenders = [
        k for k, cell in by_key.items()
        if cell.get("source") == deep_channel.SOURCE_RECOGNIZED
        and not _field_of(target_type, k).recognizable
    ]
    assert offenders == [], (
        f"`recognizable=False` 的格子被标成「从图上抄的」：{offenders}"
        "（来源标记撒谎 = 把猜的当抄的）"
    )


def _field_of(target_type, key):
    return next(f for f in TARGET_FIELDS[target_type] if f.key == key)


def test_generated_cells_never_carry_the_recognized_source():
    """实例面：内核硬塞值，`name` / `description` 的来源**不得**是 `[图片识别]`。"""
    fields = [
        {"key": k, "label": _product_field(k).label, "value": "模型编的文案",
         "confidence": 0.95, "reason": None}
        for k in GENERATED_KEYS
    ]
    plan = deep_channel.build_page_fill("product", fields)
    by_key = {c["key"]: c for c in plan["fields"]}
    for key in GENERATED_KEYS:
        cell = by_key[key]
        assert cell.get("source") != deep_channel.SOURCE_RECOGNIZED, (
            f"`{key}` 被标成了「从图上抄的」：{cell}"
        )


def test_generic_old_blanket_reason_is_not_used_for_generated_fields():
    """空格理由不许自相矛盾：这两格不能说「图片未给出该字段」。

    红证：`_empty_reason` 改回「照抄内核 reason / 图片未给出该字段」⇒ 本判据红。
    """
    plan = deep_channel.build_page_fill("product", [])
    by_key = {c["key"]: c for c in plan["fields"]}
    for key in GENERATED_KEYS:
        reason = by_key[key].get("reason") or ""
        assert "图片未给出该字段" not in reason, (
            f"`{key}` 的理由与它的定义自相矛盾（它是文案、不是识别没看清）：{reason!r}"
        )
        assert "米宝解读" in reason, f"`{key}` 的理由应指向米宝解读：{reason!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 三、自否证的值必须丢掉（模型一边给值一边说「图上没有」）
# ══════════════════════════════════════════════════════════════════════════════

def test_value_with_self_denying_reason_is_dropped():
    """模型给值 + `reason` 说「图上没有」⇒ 值是编的，丢掉。

    真跑原样：`name` 给了 `常青藤系列窗帘面料卡`，`reason` 逐字「图片未给出该字段」。

    红证：把 `_resolve` 里那段自否证判断删掉 ⇒ 本判据红。
    """
    for reason in ("图片未给出该字段", "图上没有这一格", "看不清，无法识别", "未标注"):
        value, out_reason = recognizer._resolve(
            "product",
            _product_field("color"),
            {"value": "编出来的颜色", "confidence": 0.9, "reason": reason},
            recognizer.TARGET_POLICY["product"],
        )
        assert value is None, f"自否证的值得留下来了：reason={reason!r} value={value!r}"
        assert out_reason == reason


def test_normal_copy_without_self_denial_still_lands():
    """对照组：`reason` 正常（或不给）时，抄到的值照旧落地 —— 防「把识别闸一刀切死」。"""
    value, _ = recognizer._resolve(
        "product",
        _product_field("color"),
        {"value": "常青藤-1# 轻轻茉莉", "confidence": 0.95, "reason": "图上第二行"},
        recognizer.TARGET_POLICY["product"],
    )
    assert value == "常青藤-1# 轻轻茉莉"
