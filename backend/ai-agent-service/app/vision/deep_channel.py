"""Agent **深通道**（issue #5368 包 2）——识别内核之上的**确定性半边**。

## 定位（issue #5368 / `docs/agent-feature-design.md` §四）

包 1（PR #5343）交付**页面快通道**；本模块是**深通道**，**不是替代品**。
Agent 只补页面做不到的三种，其中前两种的**可判定部分**落在本模块（纯函数）：

| 情况 | 例子 | 本模块的处置 |
|---|---|---|
| **歧义消解** | 识别出「雾霾蓝」但商品目录里没有 | 给**候选 + 为什么最接近**，**不填**（页面只能给个下拉，不会解释） |
| **领域解读** | 这是什么面料 / 工艺 | 独立来源 `[米宝解读]`，与 `[图片识别]` **标注不同** |
| 跨实体追问 | 「照这张图建个商品」分类/售价未定 | 不需新代码：Agent 用既有 `interact` 卡多轮澄清 |

## 三条铁律

1. 🔴 **一个内核**：识别仍走 `app/vision/recognizer.py`（本模块**不含**任何 vision 调用、
   不含第二份字段表），只做「内核字段表 → 填哪几格」的投影。
2. 🔴 **不确定的宁可不填**：目录未命中的取值**一格都不填**（给候选 + 解释让商家选）；
   订单侧的 Agent 解读**一格都不填**（客户信息错 ⇒ 货发错人）。
3. 🔴 **不落库、不落盘**：只产出「填哪几格 + 候选 + 解读」这一个出口形状（`page_fill` 计划）；
   本模块不 import 任何写入缝（机械判据 = 包 1 的 `TestNoWriteBoundary` 按 `app/vision/*.py` 扫描，
   射程自证见 `tests/test_vision/test_deep_channel.py::TestScannedByPackageOneGuard`），
   **日志只打 `log_summary()`**（target/计数/键名，值一律不进）。

## 出口形状（前后端冻结契约）

```python
{"component": "page_fill", "target_type": "product" | "order",
 "fields": [{"key", "label", "value", "source", "reason", "candidates", "note", "note_source"}]}
```

- `value` 非空 ⇒ `source` 必为 `[图片识别]` 或 `[米宝解读]`（**来源可区分**是硬要求：
  否则商家无法判断该信哪一格）；
- `value` 为空 ⇒ 必有 `reason`（看得懂的理由），`candidates` 只在歧义时非空。
"""
import difflib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.vision.recognizer import FIELD_MARKER
from app.vision.targets import TARGET_FIELDS, TargetField

#: 「识别来的」标记 —— **就是内核那一个对象**（`is` 身份，不是同值副本：抄一份必然漂移）
SOURCE_RECOGNIZED = FIELD_MARKER

#: 「Agent 解读/推荐的」标记 —— **必须与识别标记不同**（issue #5368 硬约束 3）
SOURCE_INTERPRETED = "[米宝解读]"

#: 同页填充计划的事件/组件名（前端 `PAGE_FILL_EVENT` 与 SSE `event: page_fill` 同源）
PAGE_FILL_COMPONENT = "page_fill"

#: 候选上限与相似度下限（`difflib` 是标准库 —— 消歧不需要第二套依赖，也不需要再调一次 LLM）
CANDIDATE_LIMIT = 3
CANDIDATE_CUTOFF = 0.0

#: 留空理由的**固定措辞**（判据按它断言；改措辞 = 改判据，必须同时改测试）
AMBIGUOUS_HINT = "宁可不填"

#: **哪些格允许 Agent 的领域解读填值**（issue #5368 的风险不对称）：
#: - 商品侧只放**看图看得出门道、且不直接进结算**的两格（材质 / 工艺）；
#: - 🔴 订单侧**一个都不放** —— 订单侧风险更高（客户信息错 ⇒ **货发错人**），
#:   解读只用来解释，绝不变成本单里的值（与包 1 `TARGET_POLICY` 的严格度同源）。
#: 售价 / 门幅**不在其中**：结算面只认图上写明的内容（猜出来的钱格比空格贵）。
INTERPRETABLE_KEYS: Dict[str, Tuple[str, ...]] = {
    "product": ("material", "craft"),
    "order": (),
}


def resolve_against_catalog(value: str, catalog: Optional[Sequence[str]]) -> Dict[str, Any]:
    """识别值 vs 店铺目录 ⇒ **命中 / 歧义 / 未校验** 三态（纯函数，标准库）。

    - `matched`：目录里**有**这个取值 ⇒ 原样可填；
    - `ambiguous`：目录里**没有** ⇒ 返回最接近的几个候选 + **为什么它们最接近**（相似度），
      并**明确要求留空**（`value` 不在这条路径的返回里 ⇒ 「擅自填值」在结构上不可能）；
    - `unchecked`：调用方**没给目录** ⇒ **不做无据的消歧**（既不说命中、也不说没命中）。

    ⚠️ 没有目录 ≠ 命中：把「不知道」当「没问题」正是本仓反复批判的形态。
    """
    if not catalog:
        return {"status": "unchecked", "matched": value, "candidates": [], "reason": None}
    pool = [str(c) for c in catalog]
    if value in pool:
        return {"status": "matched", "matched": value, "candidates": [], "reason": None}

    close = difflib.get_close_matches(value, pool, n=CANDIDATE_LIMIT, cutoff=CANDIDATE_CUTOFF)
    candidates: List[Dict[str, str]] = [
        {
            "value": candidate,
            "reason": f"与「{value}」最接近（相似度 {difflib.SequenceMatcher(None, value, candidate).ratio():.0%}）",
        }
        for candidate in close
    ]
    return {
        "status": "ambiguous",
        "matched": None,
        "candidates": candidates,
        "reason": (
            f"店铺目录里没有「{value}」⇒ {AMBIGUOUS_HINT}："
            + (
                "下面几个最接近，请商家挑一个，或手工填写"
                if candidates
                else "目录里也没有相近的取值，请商家手工填写"
            )
        ),
    }


def build_page_fill(
    target_type: str,
    fields: Sequence[dict],
    *,
    catalog: Optional[Dict[str, Sequence[str]]] = None,
    interpretations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """内核字段表 → **同页填充计划**（纯函数）。

    参数：
        target_type: `product` / `order`（未知值 fail-closed 抛 `ValueError`，不做默认回落）
        fields: **内核产出**的字段表（`recognizer.extract_fields()` 的形状，逐字段含 value/source/reason）
        catalog: `{字段键: [店铺已有取值]}` —— 给了就消歧，没给就**不猜**
        interpretations: `{字段键: {"value": 解读出的值, "note": 给商家看的解释}}` —— Agent 的领域解读

    三条处置（顺序不可颠倒）：
    1. 内核有值 ⇒ 先过**目录消歧**：命中/未校验 ⇒ 填（来源 `[图片识别]`）；
       歧义 ⇒ **留空 + 候选 + 解释**（商家来选）；
    2. 解读 ⇒ **只在「内核本来就没给出这一格」且该键在 `INTERPRETABLE_KEYS` 里**时才填
       （来源 `[米宝解读]`）——已识别 / 歧义的格**一律不覆盖**（不替商家拍板）；
    3. 解读的 `note` **永远**附上（来源 `note_source`），即使不能变成值 —— 解释本身是价值。
    """
    schema = _schema_for(target_type)
    interpretations = interpretations or {}
    catalog = catalog or {}

    plan_fields: List[Dict[str, Any]] = []
    for field in schema:
        source_field = _source_field(fields, field.key)
        original = _text(source_field.get("value"))
        resolution = resolve_against_catalog(original, catalog.get(field.key)) if original else None

        if original and resolution and resolution["status"] == "ambiguous":
            cell = _ambiguous_cell(field, original, resolution)
        else:
            cell = _empty_cell(field, _text(source_field.get("reason")) or "图片未给出该字段")
            if original:
                cell["value"] = original
                cell["source"] = SOURCE_RECOGNIZED

        _apply_interpretation(cell, target_type, interpretations.get(field.key))
        plan_fields.append(cell)

    return {
        "component": PAGE_FILL_COMPONENT,
        "target_type": target_type,
        "fields": plan_fields,
    }


def log_summary(plan: Dict[str, Any]) -> str:
    """**安全日志摘要**：target / 计数 / 键名 —— 🔴 **值一律不进日志**。

    为什么单独一个函数（而不是在调用点拼串）：PII 纪律要是「两处各拼一次」，
    漏一处就是不可撤销的泄露（订单侧这一格里装的是客户名 / 电话 / 地址）。
    单点实现 + 会被注入式红证钉住的判别力（`tests/test_vision/test_deep_channel.py`）。
    """
    fields = plan.get("fields") or []
    filled = [f for f in fields if _text(f.get("value"))]
    recognized = [f for f in filled if f.get("source") == SOURCE_RECOGNIZED]
    interpreted = [f for f in filled if f.get("source") == SOURCE_INTERPRETED]
    ambiguous = [f for f in fields if f.get("candidates")]
    keys = ",".join(str(f.get("key", "")) for f in fields)
    return (
        f"component={plan.get('component')} target={plan.get('target_type')} "
        f"filled={len(filled)} empty={len(fields) - len(filled)} "
        f"recognized={len(recognized)} interpreted={len(interpreted)} "
        f"ambiguous={len(ambiguous)} keys=[{keys}]"
    )


# ── 内部：纯函数分解（便于逐个写死断言）─────────────────────────────────────
def _schema_for(target_type: str) -> Tuple[TargetField, ...]:
    if target_type not in TARGET_FIELDS:
        raise ValueError(f"不支持的识别 target: {target_type!r}")
    return TARGET_FIELDS[target_type]


def _source_field(fields: Sequence[dict], key: str) -> dict:
    """取内核字段表里的一格（形状不可信时按「没认出来」处理，不猜）。"""
    for field in fields or ():
        if isinstance(field, dict) and field.get("key") == key:
            return field
    return {}


def _empty_cell(field: TargetField, reason: str) -> Dict[str, Any]:
    """空格子（`value` / `source` 为空，但**必给理由**）。"""
    return {
        "key": field.key,
        "label": field.label,
        "value": None,
        "source": None,
        "reason": reason,
        "candidates": [],
        "note": None,
        "note_source": None,
    }


def _ambiguous_cell(
    field: TargetField,
    original: str,
    resolution: Dict[str, Any],
) -> Dict[str, Any]:
    """**歧义格**：目录里没有这个取值 ⇒ 留空 + 候选 + 解释。

    🔴 判据 3 的唯一注入点：把下面这条 `"value": None` 改成 `original` ⇒
    `tests/test_vision/test_deep_channel.py::TestAmbiguityGivesCandidatesAndNeverFills`
    的注入式红证必须变红（红证实跑，不靠约定）。
    """
    cell = _empty_cell(field, resolution["reason"])
    cell["candidates"] = resolution["candidates"]
    # 🔴 **歧义 ⇒ 一格都不填**（本行即判据 3 的唯一注入点：把它改成写回 `original`
    # ⇒ `tests/test_vision/test_deep_channel.py` 的注入式红证必须变红）。
    cell["value"] = None
    cell["source"] = None
    return cell


def _apply_interpretation(
    cell: Dict[str, Any],
    target_type: str,
    interpretation: Any,
) -> None:
    """把 Agent 的领域解读挂到**一格**上（能不能变成值见 `INTERPRETABLE_KEYS`）。

    规则（顺序即优先级）：
    1. `note`（解释）**永远**挂上 —— 商家看得见「米宝怎么想的」，但来源标为解读；
    2. `value` 只在**内核本来就没给出这一格**（`cell["value"]` 仍为空）**且**该键可解读时才落地；
       已识别的格、以及**歧义格**（有候选）**一律不覆盖** —— 后者必须由商家挑。
    """
    if not isinstance(interpretation, dict):
        return
    note = _text(interpretation.get("note"))
    if note:
        cell["note"] = note
        cell["note_source"] = SOURCE_INTERPRETED

    value = _text(interpretation.get("value"))
    if not value or cell["value"] or cell["candidates"]:
        return
    if cell["key"] not in INTERPRETABLE_KEYS.get(target_type, ()):
        return
    cell["value"] = value
    cell["source"] = SOURCE_INTERPRETED


def _text(value: Any) -> str:
    """把任意值收成非空字符串（`None` / 空串 / 数字 0 之外的假值 ⇒ `""`）。"""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""