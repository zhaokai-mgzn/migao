"""具名跨域视图 · `product_health`（商品健康度：销量 + 库存 + 退货率 + 成本毛利）—— issue #5369

判据来源：issue #5369（族 3 · 包 2「按需消费」，设计文档 §三 族 3）。本模块是**视图语义**的唯一
判据源：给一份**内核快照**（与族 1 主动发现**同一份**行级快照 —— 同一内核、两种消费形态），产出
确定性的 SKU 级视图行 + **逐字段接线状态**。它不取数、不联网、不读挂钟。

## 三条纪律（逐条落在代码里）

1. **逐字段三态**（复用 #5358 的纪律，见 `app/briefing/proactive.py::proactive_status`）：
   每个字段是 `wired` / `not_wired` / `incomplete`（+ `reason`），不变式 **`reason is None` ⟺ `wired`**。
   ⇒ 调用方只要看这一条，就知道「空」能不能读成「没问题」。

2. 🔴 **「未知」与「0」不混**：
   · `avg_cost IS NULL`（`schema.sql` 的既有口径：存量不回填、不猜 0）⇒ 该行**成本未知**
     （`gross_margin=None` + `cost_known=False`），**不得**产出 `0` 毛利；
   · 售价 = 成本 ⇒ 毛利**真 0**（有真值时 0 是正确结论）—— 两者在输出上必须可分；
   · 退货率：有分母且 0 退货 ⇒ **真 0**；分母为 0（没有订单行）⇒ **未知**（不倒推 0）；
   · 库存读不出 ⇒ `low_stock=None`（**未知**），不得判成 `False`（那会被读成「没问题」）。

3. **口径同源（不得另写一份聚合）**：
   · 库存 / 销量的权威 = **SKU 级**（`product_skus.stock` / `product_skus.sales_count`，
     `#4038` + `schema.sql`：商品级同名列是**派生冗余列**）⇒ 本视图只取行里的权威列，不做第二份派生；
   · 低库存判定复用**既有业务口径**（`app/tools/stock_semantics.py` 的 `LOW_STOCK_THRESHOLD`，
     含上界 `≤`）—— 与族 1 的 `low_stock` 规则同一份阈值：判据
     `tests/test_briefing_product_health.py::TestSourceOfTruthIsShared::test_low_stock_judgement_equals_family1_rule`
     （同一快照下两侧的告急 SKU 集合必须逐字相同）；
   · 退货率的两端（`return_tickets` / `order_lines`）由装配层成对给出（同一窗口、同一口径），
     本视图**只做除法**，不各自另算一份。

## 退货率口径（本包定义，逐字进判据）

**某商品的退货率 = 该商品归属到的退货工单数 ÷ 该商品的订单行数**（同期窗口，窗口由装配层保证：
`DailyBriefingService.SNAPSHOT_RETURN_WINDOW_DAYS` 两端同源）。分子来自
`after_sales_tickets`（`ticket_type='return'`）按订单归属到商品（多商品订单**不猜** ⇒ `product_id`
为空的退货行会被计成 `incomplete`，而不是静默压低退货率）；分母来自 `order_items` 的**有效订单行数**
（口径同 `OrderItemMapper.selectProductRanking` 的有效状态集）。**不是**「退货件数 ÷ 销量米数」。

## 有界与租户

`limit`（默认 `MAX_VIEW_ROWS`）是有界的硬前提；**输出被截断时每个字段都落 `incomplete`**（有界不许
变成静默少报）。租户由调用方传入并原样回显（**不由行数据反推**）—— 隔离的关口在装配层（每条查询
带租户），视图不承担取数，也不提供绕过通道。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

# 内核读取器（声明优先 / 截断显式 / 行数组容错）—— 复用，不复制第二份（#5369 判据 3）
from app.briefing.proactive import (
    INCOMPLETE,
    NOT_WIRED,
    WIRED,
    _declared_fields,
    _num,
    _row_meta,
    _rows,
)
from app.tools.stock_semantics import LOW_STOCK_OPERATOR, LOW_STOCK_THRESHOLD, STOCK_AUTHORITY

__all__ = [
    "MAX_VIEW_ROWS",
    "VIEW_ID",
    "FIELD_LABELS",
    "FIELD_SOURCES",
    "REQUIRED_ROW_FIELDS",
    "LOW_STOCK_THRESHOLD",
    "NOT_ON_SALE",
    "filtered_skus",
    "field_status",
    "product_health",
]

#: 视图名（跨端契约键；改名会让判据与用例静默解绑）
VIEW_ID = "product_health"

#: 视图输出上限（有界是热路径的硬前提；截断必须显式 —— 见模块 docstring）
MAX_VIEW_ROWS = 200

#: 「SKU 到期连一行都没进视图」的第四态（issue #6347 Part B）。
#:
#: 🔴 它与 `not_wired`（系统没接）/ `incomplete`（接了但不完整）**并列、不可合并**：这里那个空是
#: **服务端过滤造成的、可行动的空** —— 事实（有几个 SKU / 几个商品 / 商品现在是什么状态）都在，
#: 出路也在（把商品上架，或在状态非法时先改回 `off_sale`/`draft` 再上架）。混成「没有数据」，
#: 用户就被引向**徒劳返工**（重录商品规格），真因一字未提。不变式 `reason is None ⟺ wired`
#: **不给本态开例外**（它的 `reason` 就是那句人话）。
NOT_ON_SALE = "not_on_sale"

#: 商品状态机**内**的合法值（唯一权威 = `ProductService.PRODUCT_STATUSES`，由测试逐字钉住）。
#: 不在其中的状态（如 `active` / `on_shelf`）是「状态机死行」：上架动作会被拒 ⇒ 出路只有先改回
#: 这两个可自救的状态再上架（Part A 已让这条流转可走）。**本模块不做第二份状态机判定** —— 这个
#: 集合只用来把**出路**说对：说错出路比不说更坏。
_RECOVERABLE_STATUSES = frozenset({"draft", "under_review", "on_sale", "off_sale"})

#: 装配层**读不到**该商品行时的占位（已删除 / 越租户）—— 与「读到了、值非法」**必须分开说**
#: （前者不许给「改回 off_sale/draft」的指引：我们并不知道它现在是什么）。
_UNKNOWN_STATUS = "unknown"

#: 给 LLM 的披露里**禁止**出现的归因错误表述（本单用户原话；由判据逐条钉住，见
#: `tests/test_briefing_product_health.py::TestFilteredSkusAreNotMisattributed`）。
FORBIDDEN_ATTRIBUTIONS = (
    "SKU 记录数 = 0",
    "SKU 记录数为 0",
    "SKU 层是空的",
    "SKU 层为空",
    "建议检查商品规格",
    "没有 SKU",
    "没有任何 SKU",
)

#: 金额 / 比率的输出精度（4 位小数：与 `product_skus.avg_cost NUMERIC(12,4)` 同粒度）
_OUTPUT_QUANT = Decimal("0.0001")

#: 逐字段来源（**单点声明**）：视图字段 → （权威行数组，该数组里必须存在的字段）
FIELD_SOURCES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "sales_count": ("skus", ("sales_count",)),
    "stock": ("skus", ("stock",)),
    "gross_margin": ("skus", ("price", "avg_cost")),
    "return_rate": ("product_return_stats", ("product_id", "return_tickets", "order_lines")),
}

#: 本视图需要的行字段（装配层 `row_fields` 必须声明它们；与 Java 侧契约机械钉住）
REQUIRED_ROW_FIELDS: Dict[str, Tuple[str, ...]] = {
    "skus": ("sku_id", "product_id", "product_name", "stock", "sales_count", "price", "avg_cost"),
    "returns": ("product_id",),
    "product_return_stats": ("product_id", "return_tickets", "order_lines"),
}

#: 「行来自 `skus` 数组」的字段（服务端过滤事实只推翻这些字段的结论）—— 从 `FIELD_SOURCES` 现取
_SKU_SOURCED_FIELDS: Tuple[str, ...] = tuple(
    name for name, (array, _) in FIELD_SOURCES.items() if array == "skus"
)

#: 字段的中文短标签（披露文案的单点来源：工具层不另写一份，避免两处措辞漂移）
FIELD_LABELS = {
    "sales_count": "销量",
    "stock": "库存",
    "gross_margin": "成本毛利",
    "return_rate": "退货率",
}

#: 字段的人话说明（LLM / 调用方可见；与 `FIELD_SOURCES` 一一对应）
_FIELD_NOTES = {
    "sales_count": "SKU 累计销量（权威 = product_skus.sales_count）",
    "stock": "SKU 库存（0.1 米粒度；权威 = product_skus.stock）",
    "gross_margin": "毛利 = 售价 − 移动加权成本；成本未知 ⇒ 该行未知（不产出 0）",
    "return_rate": "退货率 = 退货工单数 ÷ 订单行数（同期窗口）；无分母 ⇒ 未知（不产出 0）",
}


# ── 数值读取（确定性：非数值 / 缺字段一律「未知」，不猜 0）─────────────────────


def _dec(value: Any) -> Optional[Decimal]:
    """读成 `Decimal`；非数值 / 非有限 / 缺省 ⇒ `None`（未知）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            return None
    return parsed if parsed.is_finite() else None


def _int_or_none(value: Any) -> Optional[int]:
    """整数计数（条数）：读不出或为负 ⇒ `None`（未知）。"""
    parsed = _dec(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def _out(value: Optional[Decimal]) -> Optional[float]:
    """`Decimal` ⇒ JSON 原生 `float`（定精度），`None` 原样透出。"""
    if value is None:
        return None
    return float(value.quantize(_OUTPUT_QUANT, rounding=ROUND_HALF_UP))


def _gross_margin(price: Optional[Decimal], avg_cost: Optional[Decimal]) -> Optional[Decimal]:
    """毛利 = 售价 − 成本；**任一端未知 ⇒ `None`**（🔴 不得用 0 冒充「成本为零」）。

    这是「未知 vs 0」的唯一接缝：注入式红证（`test_injected_zero_filling_turns_the_same_assertion_red`）
    就是把本函数换成「未知当 0」的版本，同一断言必须变红。
    """
    if price is None or avg_cost is None:
        return None
    return price - avg_cost


# ── 同行基线（peer baseline）与判断（verdict）—— issue #8234 ─────────────────

#: 判定所需的最小有效样本量：少于它 ⇒ `unknown`（**样本太少不装懂**）
MIN_BASELINE_SAMPLE = 5

VERDICT_GOOD = "good"
VERDICT_WATCH = "watch"
VERDICT_BAD = "bad"
VERDICT_UNKNOWN = "unknown"

#: 基线性质自述（纪律 3：别让调用方把「相对」读成「绝对」）
BASELINE_BASIS = (
    "同行基线 = 同一份快照内全部 SKU 的中位数（peer_median）/ 上四分位（peer_p75，最近秩法）；"
    "这是**相对**判断、**非绝对**标准 —— 全店整体偏高时，相对 good 不代表单店健康"
)


def _median(values: List[Decimal]) -> Optional[Decimal]:
    """中位数（奇数取中位、偶数取中间两数均值）；空集 ⇒ `None`。"""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _p75(values: List[Decimal]) -> Optional[Decimal]:
    """上四分位（最近秩法，NIST 口径）：取第 `ceil(0.75n)` 个（1-based）；空集 ⇒ `None`。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = -((-3 * len(ordered)) // 4)  # ceil(3n/4)，不引入 math
    return ordered[max(0, min(rank - 1, len(ordered) - 1))]


def _peer_baseline(values: List[Optional[float]]) -> Optional[Dict[str, Any]]:
    """`{peer_median, peer_p75, sample_size}`；`None` 值**不进样本**，样本不足 ⇒ `None`。"""
    known = [Decimal(str(value)) for value in values if value is not None]
    if len(known) < MIN_BASELINE_SAMPLE:
        return None
    return {
        "peer_median": _out(_median(known)),
        "peer_p75": _out(_p75(known)),
        "sample_size": len(known),
    }


#: 指标方向 —— **登记即契约**（issue #8293）。
#:
#: 为什么方向不能由调用方传参：缺陷 #8280 就是这么来的 —— `_verdict` 只为退货率写（「越小越好」），
#: 毛利复制粘贴调用时**忘了传方向**，于是毛利越低越判「好」，而**那条单测也一起写反了**，CI 一直是绿的。
#: ⇒ 方向必须来自**这张表**：调用方连传错的机会都没有；新指标没登记 ⇒ `KeyError` ⇒ 当场红。
METRIC_DIRECTIONS: Dict[str, bool] = {
    "return_rate": False,     # 越低越好：退货率高是坏事
    "gross_margin": True,     # 越高越好：毛利高是好事
}


def _verdict(
    metric: str,
    value: Optional[float],
    baseline: Optional[Dict[str, Any]],
    *,
    absolute_bad: bool = False,
) -> str:
    """分档。**方向从 `METRIC_DIRECTIONS` 查**（不由调用方传）。

    默认（退货率这类「越小越好」的量）：`<= peer_median` ⇒ good；`<= peer_p75` ⇒ watch；
    `> peer_p75` ⇒ bad。

    `higher_is_better=True`（毛利这类「越大越好」的量）：`>= peer_median` ⇒ good；否则
    `watch`（`< 0` 由 `absolute_bad` 先兜成 bad）。🔴 少传这个参数会让**毛利越低越被判好**
    —— issue #8280 就是这么来的：`_verdict` 原本只为退货率写，毛利直接复用了它。

    `absolute_bad=True` 时**先判绝对**（`value < 0` ⇒ bad）—— 毛利为负**不因**「全店都亏、
    中位数也是负」而被相对判成 good（注入式红证见
    `test_negative_margin_is_bad_even_when_the_whole_store_loses_money`）。
    值未知或基线不可用（样本不足）⇒ `unknown`（**不装懂**）。
    """
    try:
        higher_is_better = METRIC_DIRECTIONS[metric]
    except KeyError:
        raise KeyError(
            f"指标 `{metric}` 没有登记方向 —— 在 `METRIC_DIRECTIONS`（product_health.py）里加一行："
            "越高越好写 True、越低越好写 False。方向不许猜（issue #8293 / 缺陷 #8280）"
        ) from None
    if value is None:
        return VERDICT_UNKNOWN
    if absolute_bad and Decimal(str(value)) < 0:
        return VERDICT_BAD
    if baseline is None:
        return VERDICT_UNKNOWN
    current = Decimal(str(value))
    median = Decimal(str(baseline["peer_median"]))
    if higher_is_better:
        # 越大越好：毛利有绝对判据兜底 bad（< 0），相对判据只需要「低于同行中位 ⇒ 值得看一眼」
        return VERDICT_GOOD if current >= median else VERDICT_WATCH
    if current <= median:
        return VERDICT_GOOD
    if current <= Decimal(str(baseline["peer_p75"])):
        return VERDICT_WATCH
    return VERDICT_BAD


def _baselines(rows: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    """两条基线（退货率 / 毛利率）—— 用**全量**行算，不受输出截断影响。"""
    return {
        "return_rate": _peer_baseline([row.get("return_rate") for row in rows]),
        "gross_margin": _peer_baseline([row.get("gross_margin") for row in rows]),
    }


# ── 可选动作（next options）—— issue #8251 ───────────────────────────────────
# 判据：P0 让视图能说「判 bad」，但**然后呢？** 没有下文。给人一个方案叫「通知」，
# 给几个选项**带代价与可逆性**才叫「帮决策」。
#
# v1 只收**可逆 + 低成本**的动作（清仓 / 下架 / 换供应商这类不可逆动作不进 v1，
# 登记在 issue #8251「不在本单」—— 它们需要业务裁定，不是代码能替老板决定的）。

#: 选项性质自述（纪律 3：别让调用方把「行业常见做法」读成「对你这家店的建议」）
OPTIONS_BASIS = (
    "行业常见做法，**不是**对具体店铺的建议；每条都需人工判断后再执行"
)

#: 试调价的固定步长（选项表是**确定性规则表** ⇒ 不做参数化，同一行永远同一组数）
PRICE_UP_STEP = Decimal("0.05")

#: 归因自述（P3「归因」issue #8279）—— **差异不是因果**
ATTRIBUTION_BASIS = (
    "同款对照，**只对 SKU 级信号有效**（毛利）：同一商品下多个变体之间比毛利率，"
    "差异指向「问题更可能出在这个变体的**定价或成本维护**」。"
    "退货率是**商品级**数据（`product_return_stats` 按 product_id 聚合）⇒ 同一商品所有 SKU 拿到同一个数，"
    "**指不到具体变体** —— 这种情况只给「整款退货高」，不给变体归因。"
    "这是**差异证据，不是因果结论**：样本量差很多时差异可能只是样本量（销量并排给出，由人判断）"
)

#: 金额自述（纪律 2：别让「给定情景的算术」被读成「预测」）
MONEY_BASIS = (
    "金额 = 给定情景下的**算术**，不是预测：成本未知的行不算钱（未知 ≠ 0）；"
    "调价只算「每件多赚多少」—— 销量会怎么变我们没有**价格弹性**数据，不猜"
)

_COST_LOW = ("low", "低成本：只看数据 / 改文案")

_OPTIONS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
    "return_rate": {
        VERDICT_BAD: [
            {
                "action": "先看这批退货的售后原因分布（色差 / 尺寸 / 物流 / 质量）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "售后工单按原因分组的条数；先知道「主要怪谁」再决定改什么",
            },
            {
                "action": "在商品描述里补「实物色差 / 尺寸以实物为准」提示",
                "cost": "low",
                "cost_note": "改文案，不动物流与价格",
                "reversible": True,
                "verify": "两周后该 SKU 的退货率是否回落（对比本视图的 peer_median）",
            },
        ],
        VERDICT_WATCH: [
            {
                "action": "先看这批退货的售后原因分布（色差 / 尺寸 / 物流 / 质量）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "售后工单按原因分组的条数",
            },
        ],
    },
    "gross_margin": {
        VERDICT_BAD: [
            {
                "action": "先核对成本价是否已维护（成本未知时毛利根本不可算，本行的负数可能是脏数据）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "该 SKU 的 avg_cost 是否有值；有值才是真亏，无值只是「算不出来」",
            },
            {
                "action": "核对近期是否有低于成本价的成交（改价 / 折扣叠加）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "改价记录与订单折扣：看这笔低价是「定价」还是「一次性的让利」",
            },
            {
                "action": "小范围试调价（如 +5%），观察 2 周销量再决定是否扩大",
                "cost": "medium",
                "cost_note": "调价影响转化，需盯销量",
                "reversible": True,
                "verify": "两周内该 SKU 的销量与毛利双向变化；只涨毛利不涨销量的价格要慎用",
                # 唯一能算钱的选项：+5% 每件多赚多少（见 _option_money）
                "money_kind": "price_step",
            },
        ],
        VERDICT_WATCH: [
            {
                "action": "核对成本价是否已维护（成本未知时毛利不可算）",
                "cost": "low",
                "cost_note": _COST_LOW[1],
                "reversible": True,
                "verify": "该 SKU 的 avg_cost 是否有值",
            },
        ],
    },
}


def _attribution(
    row: Dict[str, Any], siblings: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """归因（issue #8279）—— 「问题出在这个变体，还是整个商品？」。

    🔴 关键约束（写码时实测撞出来的，见 issue #8279 的自我纠正评论）：
    **退货率是商品级数据**（`product_return_stats` 按 `product_id` 聚合）⇒ 同一商品下所有 SKU
    拿到**同一个** `return_rate`，拿它做变体对照的 gap **恒等于 0** —— 那是假归因。
    ⇒ 变体归因**只能用 SKU 级信号（毛利）**；退货率只能落成 `product_level_only`（明说指不到变体）。

    其余三条不许：
    · **单独一个 SKU 不许给归因**：没有对照就没有差异，`None` 才是诚实的（不是「没问题」）。
    · **兄弟的毛利未知不许算进来**：拿脏数据算差值，差值本身就成了噪音。
    · **不给因果断言**：只说「差异指向这个变体的定价/成本」，不说「因为这个变体质量差」。
    """
    rate_verdict = row.get("return_rate_verdict")
    margin_verdict = row.get("gross_margin_verdict")
    if rate_verdict not in (VERDICT_BAD, VERDICT_WATCH) and margin_verdict not in (
        VERDICT_BAD,
        VERDICT_WATCH,
    ):
        return None

    # ① 毛利（SKU 级）⇒ 可以指到变体
    mine = _dec(row.get("gross_margin"))
    if mine is not None and margin_verdict in (VERDICT_BAD, VERDICT_WATCH):
        peers = [
            item for item in siblings
            if item.get("sku_id") != row.get("sku_id") and _dec(item.get("gross_margin")) is not None
        ]
        if peers:
            best = max(peers, key=lambda item: _dec(item["gross_margin"]))
            best_margin = _dec(best["gross_margin"])
            if best_margin > mine:
                return {
                    "kind": "sibling_margin_contrast",
                    "level": "sku",
                    "sibling_count": len(peers) + 1,
                    "best_sibling_sku_id": best.get("sku_id"),
                    "best_sibling_gross_margin": _out(best_margin),
                    "gap": _out(mine - best_margin),
                    "sample_note": (
                        f"本 SKU 销量 {_sales_text(row)}、对比的兄弟 {_sales_text(best)}；"
                        "样本量差很多时差异可能只是样本量 —— 这是**差异证据，不是因果结论**"
                    ),
                }

    # ② 退货率（商品级）⇒ **指不到变体**，只如实说清「整款高的原因不在这份数据里」
    if rate_verdict in (VERDICT_BAD, VERDICT_WATCH):
        return {
            "kind": "product_level_only",
            "level": "product",
            "reason": (
                "退货率是**商品级**数据（按 product_id 聚合）⇒ 同一商品下所有变体拿到同一个数，"
                "这里**指不到具体变体**。要定位到变体，需要 SKU 级的退货原因数据（当前快照没有）"
            ),
        }

    return None


def _sales_text(row: Dict[str, Any]) -> str:
    count = _num(row.get("sales_count"))
    return "未知" if count is None else f"{int(count)} 件"


def _money(row: Dict[str, Any], margin_baseline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """权衡的刻度（issue #8276）—— 「这批货压了多少钱 / 离同行差多少 / 每件多赚多少」。

    🔴 三条不许：
    · **成本未知不许当 0**：`stock_value = None` + 自述 `cost_unknown`。把未知写成 0 等于
      说「这批货不占钱」，与事实**正好相反**（注入式红证见 `test_unknown_cost_is_not_zero_capital`）。
    · **不乘销量**：`sales_count` 的周期口径在快照契约里没标注，乘上去就是编
      （红证见 `test_price_step_does_not_multiply_by_sales_count`）。
    · **不给「建议价」**：没有弹性数据，只算「+5% 这个情景下每件多赚多少」。
    """
    stock = _dec(row.get("stock"))
    price = _dec(row.get("price"))
    cost = _dec(row.get("avg_cost"))
    margin = _dec(row.get("gross_margin"))

    if cost is None:
        stock_value, value_basis = None, "cost_unknown"
    elif stock is None:
        stock_value, value_basis = None, "stock_unknown"
    else:
        stock_value, value_basis = stock * cost, "stock × avg_cost"

    peer_median = _dec((margin_baseline or {}).get("peer_median"))
    gap = (peer_median - margin) if (margin is not None and peer_median is not None) else None

    return {
        "stock_value": _out(stock_value),
        "stock_value_basis": value_basis,
        # 正数 = 每件比同行中位**少赚**这么多（方向写反是最难发现的错）
        "margin_gap_per_unit": _out(gap),
        "margin_gap_basis": (
            "peer_median − 本行毛利；正数 = 每件比同行中位少赚"
            if gap is not None
            else "基线样本不足（< 最小样本量）或本行毛利未知 ⇒ 算不出差额"
        ),
        "price_up_5pct_per_unit": _out(price * PRICE_UP_STEP) if price is not None else None,
    }


def _option_money(row: Dict[str, Any], money_kind: str) -> Optional[Dict[str, Any]]:
    """选项层面的钱：**算得出才给**（算不出的不给字段，而不是给 0）。"""
    if money_kind != "price_step":
        return None
    price = _dec(row.get("price"))
    if price is None:
        return None
    return {
        "per_unit": _out(price * PRICE_UP_STEP),
        "premise": "销量不变假设下每件多赚这么多；销量会怎么变没有弹性数据（不猜）",
    }


def _next_options(row: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """按行的 verdict 产出去重后的可选动作；**没问题（good / unknown）⇒ 不产出**。

    纯规则表（不读 LLM）⇒ 同一组 verdict 必然产出同一组选项（确定性由规则表保证，不需要额外排序）。
    """
    options: List[Dict[str, Any]] = []
    seen = set()
    for metric, verdict_field in (
        ("return_rate", "return_rate_verdict"),
        ("gross_margin", "gross_margin_verdict"),
    ):
        verdict = row.get(verdict_field)
        if verdict not in (VERDICT_BAD, VERDICT_WATCH):
            continue
        for option in _OPTIONS.get(metric, {}).get(verdict, []):
            key = (metric, option["action"])
            if key in seen:
                continue
            seen.add(key)
            entry = {**option, "metric": metric, "for_verdict": verdict}
            money_kind = option.get("money_kind")
            impact = _option_money(row, money_kind) if money_kind else None
            if impact is not None:
                entry["money_impact"] = impact
            # 内部标记不外泄（它是规则表的元数据，不是给调用方看的）
            entry.pop("money_kind", None)
            options.append(entry)
    return options or None


def _blank_rows(snapshot: Any, array: str, field: str) -> int:
    """某个行数组里 `field` 缺值的行数（维度缺值 ⇒ 结论不完整，不是「这些行没问题」）。"""
    return sum(1 for row in _rows(snapshot, array) if row.get(field) in (None, ""))


# ── 服务端过滤事实（issue #6347 Part B：「有 SKU 但商品不在售」必须自己说出来）─────


def _int_field(value: Any) -> Optional[int]:
    """非负整数计数；读不出 / 为负 ⇒ `None`（未知）。"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _status_buckets(raw: Any) -> Dict[str, int]:
    """`filtered_by_status` → `{商品状态: SKU 行数}`（只认非负整数计数；其余**不猜**、丢弃）。"""
    if not isinstance(raw, dict):
        return {}
    buckets: Dict[str, int] = {}
    for name, count in raw.items():
        parsed = _int_field(count)
        if parsed is not None:
            buckets[str(name)] = parsed
    return buckets


def _product_ids(raw: Any) -> List[str]:
    return [str(item) for item in raw if isinstance(item, (str, int))] if isinstance(raw, list) else []


def filtered_skus(snapshot: Any) -> Dict[str, Any]:
    """`skus` 数组的**服务端过滤事实**（issue #6347 Part B）—— 装配层经 `row_meta.skus` 透出。

    返回 `{"available", "rows_before_filter", "filtered_count", "filtered_by_status",
    "filtered_product_ids", "message"}`：`available=False` ⇒ **老快照**（该键面世前）⇒
    调用方必须退回旧口径（把空当「未接线/无数据」），**不得**凭空断言「被过滤了」。

    🔴 为什么这是一个**独立于三态**的事实：三态判的是「这个字段接没接、全不全」，
    而过滤判的是「接上了、也全，但服务端**按商品在售口径**把行排除了」。两者可以同时为真，
    混在一起就会把**可行动**的空说成**不可行动**的空（本单的用户就是被这么引去重录规格的）。
    """
    meta = _row_meta(snapshot, "skus")
    before = _int_field(meta.get("rows_before_filter"))
    if before is None:
        return {"available": False, "rows_before_filter": None, "filtered_count": None,
                "filtered_by_status": {}, "filtered_product_ids": [], "message": None}
    count = _int_field(meta.get("count"))
    # `count` 缺席 ⇒ 用**实际行数**（引擎与装配层都别猜：两处口径分叉时以能亲眼看见的那个为准）
    count = len(_rows(snapshot, "skus")) if count is None else count
    buckets = _status_buckets(meta.get("filtered_by_status"))
    ids = _product_ids(meta.get("filtered_product_ids"))
    filtered = max(before - count, 0)
    info: Dict[str, Any] = {
        "available": True,
        "rows_before_filter": before,
        "filtered_count": filtered,
        "filtered_by_status": buckets,
        "filtered_product_ids": ids,
        "message": None,
    }
    if not filtered:
        return info
    info["message"] = _filtered_reason(before, filtered, _prod_count(ids, filtered), buckets)
    return info


def _prod_count(ids: List[str], filtered: int) -> Optional[int]:
    """被排除的**商品数**（只在读数自洽时给出：id 去重后 0 < 数 ≤ 被排除的 SKU 数）。

    不自洽（老快照没给 id / id 数与行数矛盾）⇒ `None`：宁可只说 SKU 数，也不说一个错的商品数。
    """
    unique = len(set(ids))
    return unique if 0 < unique <= filtered else None


def _filtered_reason(before: int, filtered: int, products: Optional[int],
                     buckets: Dict[str, int]) -> str:
    """说清**原因**（不是没建 SKU，而是因未上架未纳入）+ **出路**（issue #6347 用户口径 1/2/3）。"""
    scale = f"{filtered} 个 SKU" + (f"（{products} 个商品）" if products else "")
    statuses = "、".join(f"{name} {count} 个" for name, count in sorted(buckets.items()))
    message = (
        f"商品健康度快照里 skus 过滤前有 {before} 行、按商品在售口径过滤后剩 {before - filtered} 行 —— "
        f"有 {scale} 因**商品未上架**（不在售）未纳入本次视图，"
        f"被过滤商品的状态分布：{statuses or '未知'}。"
        "🔴 卡点在**商品状态**，不在 SKU 有没有建过：把商品上架（状态置 on_sale）后，"
        "它们的 SKU 即纳入本视图。"
    )
    odd = {name: count for name, count in buckets.items() if name not in _RECOVERABLE_STATUSES}
    if not odd:
        return message
    detail = "、".join(f"{name} {count} 个" for name, count in sorted(odd.items()))
    message += f"⚠️ 额外：其中有商品的状态是 {detail} —— 这些值不在商品状态机内"
    if set(odd) - {_UNKNOWN_STATUS}:
        # 状态**读到了**且不在状态机内（如 `active` / `on_shelf`）⇒ 出路明确且**可执行**
        # （Part A 已把这条恢复边做通：只许先改回 off_sale / draft，不许直接上架）。
        message += (
            "（合法值 draft / under_review / on_sale / off_sale），**上架动作会被拒**"
            "（「状态流转无效…允许的目标状态: 无」）⇒ 需先把这些商品改回 off_sale（已下架）或 "
            "draft（草稿），再执行上架；改状态后它们的 SKU 同样纳入本视图。"
        )
    if _UNKNOWN_STATUS in odd:
        # 🔴 状态**读不到**（商品已删 / 越租户）⇒ **不猜**：不说「改回某个值」这种可能不对的指引，
        # 只说清「先去商品列表核实它现在的状态」（说错出路比不说更坏）。
        message += (
            "；其中 `unknown` = 装配层读不到该商品行（可能已删除或不属于本租户）⇒ "
            "无法推断出路，请先在商品列表核实这些商品当前的状态。"
        )
    return message


# ── 逐字段三态（判据 1；与族 1 的 `proactive_status` 同一纪律）────────────────


def field_status(snapshot: Any) -> Dict[str, Dict[str, Any]]:
    """**逐字段**接线状态 + 未接线 / 不完整原因（issue #5369 判据 1）。

    返回 `{field: {"status", "reason", "missing", "gaps", "source", "note"}}`：
    `status` ∈ {`wired`（本次完整可用）, `not_wired`（未接入）, `incomplete`（本次不完整）,
    `not_on_sale`（**已接入且完整，但该数组被服务端按在售口径过滤空了** —— issue #6347 Part B）}；
    不变式：**`reason is None` ⟺ `status == wired`**。

    纯函数、只读：同一 `snapshot` ⇒ 同一结果（与视图行互不影响 —— 状态不改判据、不改行）。
    """
    status: Dict[str, Dict[str, Any]] = {}
    for field, (array, needed) in FIELD_SOURCES.items():
        declared = _declared_fields(snapshot, array)
        source = f"{array}.{'/'.join(needed)}"
        if declared is None:
            status[field] = {
                "status": NOT_WIRED,
                "reason": f"快照未提供 {array} 行数组（装配层未接线）",
                "missing": [array],
                "gaps": [],
                "source": source,
                "note": _FIELD_NOTES[field],
            }
            continue
        missing = [name for name in needed if name not in declared]
        if missing:
            status[field] = {
                "status": NOT_WIRED,
                "reason": f"快照 {array} 行缺字段 {'、'.join(missing)}（数据层无此来源）",
                "missing": missing,
                "gaps": [],
                "source": source,
                "note": _FIELD_NOTES[field],
            }
            continue

        # 🔴 服务端过滤（issue #6347 Part B）：数组**接到了、字段也齐**，但这一轮一行都没进来，
        # 且过滤事实（filtered_skus）证明**过滤前是有行的** ⇒ 本字段的空**不是**「没数据」。
        # 判在 `line = 过滤后 0 行` 这一支（部分保留时字段照旧可用，但仍如实披露）。
        info = filtered_skus(snapshot)
        if field in _SKU_SOURCED_FIELDS and info["available"] and info["message"]:
            if not _rows(snapshot, array):
                status[field] = {
                    "status": NOT_ON_SALE,
                    "reason": info["message"],
                    "missing": [],
                    "gaps": [],
                    "source": source,
                    "note": _FIELD_NOTES[field],
                }
                continue

        gaps: List[str] = []
        meta = _row_meta(snapshot, array)
        if meta.get("truncated"):
            gaps.append(
                f"{array} 数组已被行数上限截断（上限 {meta.get('limit')} 行，"
                f"本次给出 {meta.get('count')} 行）⇒ 结论不完整"
            )
        if field == "return_rate":
            # 分子来自退货行：它的截断 / 归属缺失同样让结论不完整（否则退货率静默偏低）
            if _declared_fields(snapshot, "returns") is None:
                gaps.append("快照未提供 returns 行数组（退货单数来源未接线）⇒ 退货率不完整")
            else:
                returns_meta = _row_meta(snapshot, "returns")
                if returns_meta.get("truncated"):
                    gaps.append(
                        f"returns 数组已被行数上限截断（上限 {returns_meta.get('limit')} 行，"
                        f"本次给出 {returns_meta.get('count')} 行）⇒ 退货单数偏低"
                    )
                unattached = _blank_rows(snapshot, "returns", "product_id")
                if unattached:
                    gaps.append(
                        f"returns 数组有 {unattached} 行退货无法归属到商品（多商品订单，装配层不猜）"
                        "⇒ 受影响的商品退货率偏低"
                    )
        status[field] = {
            "status": INCOMPLETE if gaps else WIRED,
            "reason": "；".join(gaps) if gaps else None,
            "missing": [],
            "gaps": gaps,
            "source": source,
            "note": _FIELD_NOTES[field],
        }
    return status


# ── 视图行（SKU 级 = 唯一权威）───────────────────────────────────────────────


def _row(sku_row: Dict[str, Any], stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """一行 = 一个 SKU（库存 / 销量 / 成本在 SKU 级才是权威 —— `#4038`）。"""
    product_id = sku_row.get("product_id")
    stock = _num(sku_row.get("stock"))
    price, avg_cost = _dec(sku_row.get("price")), _dec(sku_row.get("avg_cost"))
    margin = _gross_margin(price, avg_cost)

    stat = stats.get(str(product_id)) if product_id not in (None, "") else None
    if stat is None:
        tickets = lines = None
        basis = "no_product_stats"
    else:
        tickets, lines = _int_or_none(stat.get("return_tickets")), _int_or_none(stat.get("order_lines"))
        basis = "tickets/order_lines"
    rate: Optional[Decimal] = None
    if tickets is not None and lines is not None:
        if lines > 0:
            rate = Decimal(tickets) / Decimal(lines)
        else:
            # 没有分母 ⇒ 退货率**未知**（`0` 会被读成「没有退货」—— 那是另一件事）
            basis = "no_order_lines"

    return {
        "sku_id": sku_row.get("sku_id") or sku_row.get("id"),
        "product_id": product_id,
        "product_name": sku_row.get("product_name"),
        "stock": stock,
        # 告急 = 既有业务口径（`stock_semantics`，含上界 ≤）—— 未知库存 ⇒ None（不是「不告急」）
        "low_stock": None if stock is None else stock <= LOW_STOCK_THRESHOLD,
        "sales_count": _num(sku_row.get("sales_count")),
        "price": _out(price),
        "avg_cost": _out(avg_cost),
        "gross_margin": _out(margin),
        "cost_known": avg_cost is not None,
        "return_tickets": tickets,
        "order_lines": lines,
        "return_rate": _out(rate),
        "return_rate_basis": basis,
    }


def product_health(
    snapshot: Any, *, tenant_id: Any, limit: int = MAX_VIEW_ROWS
) -> Dict[str, Any]:
    """产出 `product_health` 视图（按需消费）—— 纯函数、确定性、有界。

    Args:
        snapshot: 内核快照（与族 1 同一份；`row_fields` / `row_meta` / 行数组契约见
            `DailyBriefingService.SNAPSHOT_ROW_FIELDS`）
        tenant_id: 调用方所在租户（原样回显；隔离关口在装配层）
        limit: 输出行数上限（≥1；截断时逐字段落 `incomplete`）

    Returns:
        `{"view", "tenant_id", "fields", "rows", "row_meta", "count", "rows_total",
          "truncated", "unknown_cost_rows", "unattributed_returns", "not_on_sale", "basis"}`；
        `not_on_sale` = 服务端过滤事实（issue #6347 Part B，见 `filtered_skus`）—— 行为与
        「表里没有 SKU」**不可合并**：有它就必须说清「有 N 个 SKU（M 个商品）因未上架未纳入」+ 出路。
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 ≥1 的整数，实得 {limit!r}")

    fields = field_status(snapshot)
    stats: Dict[str, Dict[str, Any]] = {}
    for row in _rows(snapshot, "product_return_stats"):
        product_id = row.get("product_id")
        if product_id not in (None, ""):
            stats[str(product_id)] = row

    rows = [_row(sku_row, stats) for sku_row in _rows(snapshot, "skus")]
    rows.sort(key=lambda item: (str(item["product_id"] or ""), str(item["sku_id"] or "")))

    total = len(rows)
    # 基线用**全量**行算（不受输出截断影响）—— issue #8234
    baselines = _baselines(rows)
    # 同款分组也基于全量行（issue #8279）：用截断后的 rows 会让「兄弟」随上限漂移
    all_rows = list(rows)
    truncated = total > limit
    if truncated:
        rows = rows[:limit]
        # 🔴 有界不许变成静默少报：输出被截断 ⇒ 每个字段的结论都不完整（带可归因读数）
        for entry in fields.values():
            entry["gaps"] = list(entry["gaps"]) + [
                f"视图输出被上限截断（上限 {limit} 行，本次给出 {len(rows)} 行，共 {total} 行）"
                "⇒ 结论不完整"
            ]
            entry["status"] = INCOMPLETE
            entry["reason"] = "；".join(entry["gaps"])

    # ── 同行基线 + 判断（issue #8234）：基线放视图级（不逐行重复），行内只放分档 ──
    rate_baseline, margin_baseline = baselines["return_rate"], baselines["gross_margin"]
    # 同款分组（issue #8279）：按 product_id 聚合 —— 基线用的是**全量**行（不受截断影响），
    # 所以归因的兄弟集合也从全量行取，不用截断后的 rows。
    by_product: Dict[str, List[Dict[str, Any]]] = {}
    for item in all_rows:
        key = item.get("product_id")
        if key not in (None, ""):
            by_product.setdefault(str(key), []).append(item)

    def siblings_of(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        key = item.get("product_id")
        return by_product.get(str(key), []) if key not in (None, "") else []
    for row in rows:
        row["return_rate_verdict"] = _verdict(
            "return_rate", row.get("return_rate"), rate_baseline
        )
        row["gross_margin_verdict"] = _verdict(
            "gross_margin", row.get("gross_margin"), margin_baseline, absolute_bad=True
        )
        # 「然后呢？」—— 只给有问题的行（issue #8251）
        # 权衡的刻度（issue #8276）：钱是**事实**，所以 good 行也给；选项才是建议
        row["money"] = _money(row, margin_baseline)
        # 归因（issue #8279）：同款对照 —— 只在有问题的行给（没问题时解释「为什么好」是噪音）
        row["attribution"] = _attribution(row, siblings_of(row))
        row["next_options"] = _next_options(row)

    row_meta = snapshot.get("row_meta") if isinstance(snapshot, dict) else None
    return {
        "view": VIEW_ID,
        "tenant_id": tenant_id,
        "fields": fields,
        "rows": rows,
        "row_meta": dict(row_meta) if isinstance(row_meta, dict) else {},
        "count": len(rows),
        "rows_total": total,
        "truncated": truncated,
        "unknown_cost_rows": sum(1 for item in rows if item["cost_known"] is False),
        "unattributed_returns": _blank_rows(snapshot, "returns", "product_id"),
        # 服务端过滤事实（issue #6347 Part B）：**独立于三态**，工具层据它把原因与出路说给模型
        "not_on_sale": filtered_skus(snapshot),
        # 同行基线与性质自述（issue #8234；基线放视图级，行内只放 verdict）
        "baselines": baselines,
        "baseline_basis": BASELINE_BASIS,
        "options_basis": OPTIONS_BASIS,
        "money_basis": MONEY_BASIS,
        "attribution_basis": ATTRIBUTION_BASIS,
        "basis": {
            "stock_authority": STOCK_AUTHORITY,
            "sales_authority": STOCK_AUTHORITY,
            "cost_authority": STOCK_AUTHORITY,
            "low_stock": f"stock {LOW_STOCK_OPERATOR} {LOW_STOCK_THRESHOLD}",
            "return_rate": "退货工单数 ÷ 订单行数（同期窗口，装配层同源）",
            "return_rate_baseline": BASELINE_BASIS,
            "return_rate_verdict": (
                "good ≤ peer_median；watch ≤ peer_p75；bad > peer_p75；"
                f"值未知或有效样本 < {MIN_BASELINE_SAMPLE} ⇒ unknown"
            ),
            "gross_margin_verdict": (
                "毛利 < 0 ⇒ bad（绝对判据）；否则 >= peer_median ⇒ good，< peer_median ⇒ watch"
                "（毛利**越大越好**，与退货率方向相反 —— issue #8280）"
            ),
            "next_options": OPTIONS_BASIS + "；只给 bad / watch 行，good 与 unknown 不给",
            "money": MONEY_BASIS + "；stock_value = stock × avg_cost（压货占用资金）",
        },
    }