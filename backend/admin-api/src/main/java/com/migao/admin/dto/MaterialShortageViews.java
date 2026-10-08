package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * 具名跨域视图 {@code material_shortage}（商品级用料缺口与耗尽风险，issue #6280）的**跨端契约**。
 *
 * <p>口径的唯一真值源 = issue #6280 的「冻结契约 v1」。本文件是它的 Java 侧承载：
 * <b>键名就是契约</b> —— 改名会让页面 / agent / 判据静默解绑，故此处的 record 分量名、
 * {@link #FIELD_KEYS} 与 {@link #ROW_FIELDS} 均**逐字**对应契约里的键。</p>
 *
 * <h2>三条纪律（都是「最容易做成假绿」的地方，逐条落在类型上）</h2>
 * <ol>
 *   <li><b>「未知 ≠ 0」</b>：单位不可比的商品 ⇒ {@code demandQty = null} + {@code band = unknown}，
 *       <b>不是 0</b>；真 0 需求（有订单行、可比、合计 0）⇒ 照实 {@code 0} + {@code safe}。
 *       两者在 {@link MaterialShortageRow} 上**可分**（{@code demandLines} 有值 ⟺ 可比）。</li>
 *   <li><b>逐字段三态</b>：{@code status ∈ {wired, not_wired, incomplete}}，不变式
 *       <b>{@code reason == null ⟺ status == wired}</b>；{@code truth ∈ {has_truth, no_truth}}。
 *       本包 v1 {@code rate_per_week} / {@code exhaust_date} 一律 {@code not_wired} + 具名理由
 *       （真值存在于台账，但 v1 装配层未接线 —— 见 {@code MaterialShortageService.NO_TRUTH_REASONS}）。</li>
 *   <li><b>确定性</b>：{@code as_of} 由调用方传入 / 由 {@code BusinessClock} 取业务「今天」，
 *       服务内**不出现**任何挂钟读取（机械判据 = {@code MaterialShortageServiceTest}）。</li>
 * </ol>
 *
 * <p>数值一律 {@link BigDecimal}（V115/#5063 口径）：米数逐值可比，不在传输层折算成 double。</p>
 */
public final class MaterialShortageViews {

    private MaterialShortageViews() {
    }

    // ── 契约枚举（逐字对应冻结契约；改名 = 跨端解绑）─────────────────────────────

    /** 视图名（跨端契约键）。 */
    public static final String VIEW_ID = "material_shortage";

    /**
     * 风险分层（**输出行序的第一键**，按紧急度降序）。
     *
     * <p>{@code unknown} 排最后 —— 它表示「该商品单位不可比」（供给口径与需求口径不可相减），
     * 与「不紧急」**不是**一回事。</p>
     */
    public static final List<String> RISK_BANDS =
            List.of("blocked", "critical", "soon", "short", "safe", "unknown");

    /** 三态词表（不变式：{@code reason == null ⟺ status == wired}）。 */
    public static final String WIRED = "wired";
    public static final String NOT_WIRED = "not_wired";
    public static final String INCOMPLETE = "incomplete";

    /** 真值有无（{@code no_truth} = 声明无真值，不是「这次没取到」）。 */
    public static final String HAS_TRUTH = "has_truth";
    public static final String NO_TRUTH = "no_truth";

    /** 行内字段清单 —— **行键集**的唯一声明处（判据：每行 keySet 与它逐字相等）。 */
    public static final List<String> ROW_FIELDS = List.of(
            "product_id", "product_name", "demand_qty", "demand_lines", "order_count",
            "stock_meters", "gap_meters", "risk_band", "days_to_deadline",
            "earliest_required_delivery_date", "rate_per_week", "exhaust_date", "unwired");

    // ── 视图结构 ────────────────────────────────────────────────────────────────

    /**
     * 响应根（键名 = 冻结契约的键名）。
     *
     * @param view            视图 id（{@link #VIEW_ID}）
     * @param tenantId        调用方租户（{@code TenantContext} 取，**原样回显**，不由行数据反推）
     * @param asOf            基准日（调用方传入 / {@code BusinessClock} 取；服务内不读挂钟）
     * @param basis           口径自述（粒度 / 单位 / 状态 / 两侧来源 / 行序 / 分层 / 真值源）
     * @param fields          逐字段三态（{@link FieldInfo}）
     * @param rows            行（**已截断**；聚合用全量行算，见 {@code bandCounts}）
     * @param count           本次返回行数
     * @param rowsTotal       全量候选行数（候选 = 有需求或有供给的商品）
     * @param truncated       {@code rowsTotal > limit}
     * @param noTruthFields   声明无真值的字段（排序，便于逐字比对）
     * @param hasTruthFields  声明有真值的字段（排序）
     * @param bandCounts      六档计数（**恒六键，空档回 0**；用全量行算，不随 limit 变）
     * @param nonComparable   单位不可比的披露（{@link NonComparable}）
     * @param nonComparableLines 单位不可比的订单行数（与 {@code nonComparable.lines} 同值，平铺冗余便于判据/页面）
     * @param nonComparableProducts 单位不可比的商品数（与 {@code nonComparable.products} 同值）
     * @param historyDepth    历史深度判定（{@link HistoryDepth}）—— 预测层是否启用的唯一开关
     */
    public record MaterialShortageView(
            String view,
            Long tenantId,
            String asOf,
            Map<String, String> basis,
            Map<String, FieldInfo> fields,
            List<MaterialShortageRow> rows,
            int count,
            int rowsTotal,
            boolean truncated,
            List<String> noTruthFields,
            List<String> hasTruthFields,
            Map<String, Integer> bandCounts,
            NonComparable nonComparable,
            int nonComparableLines,
            int nonComparableProducts,
            HistoryDepth historyDepth) {
    }

    /**
     * 视图行（一行 = 一个商品；粒度 = 商品，理由见 issue #6280 的 S0-bis：订单行没有 {@code sku_id}
     * 原生列，SKU 身份只在 {@code processing_info} 的 jsonb 里，覆盖率上限约 25%）。
     *
     * @param productId                  商品主键
     * @param productName                商品名（档案原样）
     * @param demandQty                  需求 = Σ{@code order_items.quantity}；**单位不可比 ⇒ null**（不是 0）
     * @param demandLines                需求订单行数；**单位不可比 ⇒ null**（不是 0）
     * @param orderCount                 涉及订单数；**单位不可比 ⇒ null**
     * @param stockMeters                供给 = Σ{@code product_skus.stock}（**不读** {@code products.stock}）
     * @param gapMeters                  {@code demandQty − stockMeters}（负 = 有余量，**照实返回**）
     * @param riskBand                   {@link #RISK_BANDS} 之一
     * @param daysToDeadline             距交期天数（**交期未知 ⇒ null**，不得回填 0）
     * @param earliestRequiredDeliveryDate 最早 {@code orders.required_delivery_date}（无 ⇒ null）
     * @param ratePerWeek                周速率 —— v1 恒 null（{@code not_wired}，见类注释纪律 2）
     * @param exhaustDate                预计耗尽日 —— v1 恒 null（{@code not_wired}）
     * @param unwired                    本行**读不出**的字段名（排序；空列表 = 本行无非可比格）
     */
    public record MaterialShortageRow(
            String productId,
            String productName,
            BigDecimal demandQty,
            Integer demandLines,
            Integer orderCount,
            BigDecimal stockMeters,
            BigDecimal gapMeters,
            String riskBand,
            Integer daysToDeadline,
            LocalDate earliestRequiredDeliveryDate,
            BigDecimal ratePerWeek,
            LocalDate exhaustDate,
            List<String> unwired) {
    }

    /**
     * 逐字段三态（承 {@code app/briefing/proactive.py::proactive_status} 的纪律，Java 侧重落）。
     *
     * @param status {@link #WIRED} / {@link #NOT_WIRED} / {@link #INCOMPLETE}
     * @param reason 未接线 / 不完整的原因；**{@code null} ⟺ {@code status == wired}**
     * @param source 权威来源（行名 + 必须存在的列）
     * @param truth  {@link #HAS_TRUTH} / {@link #NO_TRUTH}
     * @param note   字段的人话说明
     * @param label  字段的中文短标签
     */
    public record FieldInfo(
            String status,
            String reason,
            String source,
            String truth,
            String note,
            String label) {
    }

    /**
     * 单位不可比的披露（「未知 ≠ 0」的第 4 个落点）。
     *
     * @param lines    单位不可比的**订单行数**（分母 = 该状态集下的全部订单行）
     * @param products 单位不可比的**商品数**
     */
    public record NonComparable(int lines, int products) {
    }

    /**
     * 历史深度判定（预测层框架；**默认不启用**）。
     *
     * <p>🔴 {@code sufficient == false} ⇒ {@code rate_per_week} / {@code exhaust_date} 一律
     * {@code null} + {@code not_wired}，**禁止硬算、禁止回填 0**。</p>
     *
     * @param weeks         真实台账周桶**跨度**（含首尾）
     * @param activeWeeks   有数据的周数（不同 ISO 周）
     * @param requiredWeeks 要求深度（默认 8）
     * @param sufficient    是否达标（唯一的启用开关）
     * @param reason        不达标的原因（达标 ⇒ null）
     */
    public record HistoryDepth(
            int weeks,
            int activeWeeks,
            int requiredWeeks,
            boolean sufficient,
            String reason) {

        /** 不达标但还没算过原因时的安全缺省（fail-closed：**未知不许被读成达标**）。 */
        public static HistoryDepth insufficient(int weeks, int activeWeeks, int requiredWeeks) {
            return new HistoryDepth(weeks, activeWeeks, requiredWeeks, false,
                    String.format("真实台账周桶深度 %d 周 < 要求 %d 周 ⇒ 速率 / 耗尽日 / 预测区间"
                            + "一律未知（禁止硬算、禁止回填 0）", weeks, requiredWeeks));
        }
    }
}
