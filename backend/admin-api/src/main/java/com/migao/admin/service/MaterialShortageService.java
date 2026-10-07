package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.MaterialShortageViews;
import com.migao.admin.dto.MaterialShortageViews.FieldInfo;
import com.migao.admin.dto.MaterialShortageViews.HistoryDepth;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageRow;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageView;
import com.migao.admin.dto.MaterialShortageViews.NonComparable;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Date;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.temporal.IsoFields;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * 商品级用料缺口与耗尽风险（具名跨域视图 {@code material_shortage}，issue #6280）。
 *
 * <p><b>唯一真值源</b> = issue #6280 的「冻结契约 v1」。本服务是**取数 + 装配**，口径全在
 * {@link #compute} 这条**纯函数**里（无 DB、无挂钟、与输入行序无关）—— 页面与 agent 共用同一份数字。</p>
 *
 * <h2>权威口径（为什么是这两条 SQL）</h2>
 * <ol>
 *   <li><b>需求</b>：{@code Σ order_items.quantity}，条件 = {@code orders.status ∈ statuses}
 *       <b>且</b> {@code products.unit = '米'}。
 *       ⚠️ 单位真值在**商品档案**（{@code products.unit}），**不在** {@code order_items.selling_method}
 *       —— 后者实测只有 {@code NULL} / {@code bulk_cut} 两个取值，行级单位不可靠（issue #6280 实测）。</li>
 *   <li><b>供给</b>：{@code Σ product_skus.stock GROUP BY product_id}（**权威口径现场聚合**）。
 *       🔴 <b>绝对不读 {@code products.stock}</b> —— 它是派生冗余列，实测与 SKU 合计差 3.3%
 *       （2,881,009.5 m / 817 SKU vs 2,975,964.0 m / 539 商品）。</li>
 * </ol>
 *
 * <h2>三条纪律（每条都有会红的判据，见 {@code MaterialShortageServiceTest}）</h2>
 * <ol>
 *   <li>🔴 <b>「未知 ≠ 0」</b>：单位不可比 ⇒ {@code demandQty = null} + {@code band = unknown}；
 *       真 0 需求 ⇒ 照实 {@code 0} + {@code safe}；交期未知 ⇒ {@code daysToDeadline = null}
 *       （**不得回填 0** —— 0 天 = 今天到期，会把没填交期的商品排进最紧急一批）。</li>
 *   <li><b>逐字段三态</b>：{@code reason == null ⟺ status == wired}；
 *       {@code rate_per_week} / {@code exhaust_date} 一律 {@code not_wired} + 具名理由
 *       （{@link #NO_TRUTH_REASONS}：真值在台账，但 v1 装配层未接线）；截断 ⇒ 有真值字段落
 *       {@code incomplete} + 带上限与本次实际值的可归因读数。</li>
 *   <li><b>确定性</b>：本类**不调用** {@link LocalDate#now} / {@link Instant#now} /
 *       {@link OffsetDateTime#now} 这类挂钟读法 —— 业务「今天」由 {@link BusinessClock} 单点取
 *       （只需 {@code asOf}），或由调用方直接传入（机械判据 = 测试里的源码扫描）。</li>
 * </ol>
 *
 * <h2>有界与聚合</h2>
 * <p>{@code limit} 默认 {@value #DEFAULT_LIMIT}、必须 ≥1（非法值 ⇒ 400 显式拒绝，不静默回落）；
 * <b>聚合用全量行</b>（{@code bandCounts} / {@code nonComparable} 不随 {@code limit} 变）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MaterialShortageService {

    /** 视图默认行数上限（有界是热路径的硬前提）。 */
    public static final int DEFAULT_LIMIT = 50;

    /** 「缺口确定、紧迫性未知」的独立分层 —— 🔴 **不得并进 critical**。 */
    public static final String BAND_SHORT = "short";
    public static final String BAND_UNKNOWN = "unknown";
    public static final String BAND_SAFE = "safe";

    /** 分层阈值（天，{@code <=} 命中；口径进 {@code basis.risk_band} 可复算）。 */
    public static final int CRITICAL_DAYS = 3;
    public static final int SOON_DAYS = 7;

    /** 预测层的启用门槛：真实台账周桶深度 ≥ 本值。 */
    public static final int REQUIRED_WEEKS = 8;

    /** 可比性判据：单位真值在商品档案，且必须逐字等于本值。 */
    public static final String COMPARABLE_UNIT = "米";

    public static final String ERR_LIMIT_INVALID = "MATERIAL_SHORTAGE_LIMIT_INVALID";
    public static final String ERR_STATUS_UNKNOWN = "MATERIAL_SHORTAGE_STATUS_UNKNOWN";

    /**
     * 需求侧 SQL（**权威口径**）。
     *
     * <p>三条要点：① 单位过滤在 {@code JOIN products} 上（真值在档案，不在订单行）；
     * ② 租户闸 {@code o.tenant_id = ?} 与 {@code p.tenant_id = ?} 都在两侧；
     * ③ 软删（{@code orders.deleted} / {@code order_items.deleted} / {@code products.deleted}）
     * 逐表过滤 —— 缺一个就会把已删单算进需求。</p>
     */
    static final String DEMAND_SQL = """
            SELECT oi.product_id AS product_id,
                   MAX(p.name)  AS product_name,
                   SUM(oi.quantity) AS demand_qty,
                   COUNT(*)         AS demand_lines,
                   COUNT(DISTINCT oi.order_id) AS order_count
              FROM order_items oi
              JOIN orders o   ON o.id = oi.order_id
              JOIN products p ON p.id = oi.product_id
             WHERE o.tenant_id = ?
               AND p.tenant_id = ?
               AND o.deleted = 0
               AND oi.deleted = 0
               AND p.deleted = 0
               AND o.status IN (%s)
               AND p.unit = ?
             GROUP BY oi.product_id
            """;

    /**
     * 供给侧 SQL（**权威口径**）：SKU 级库存现场聚合，**不读** {@code products.stock}。
     *
     * <p>⚠️ {@code product_skus} **没有 {@code deleted} 列**（实测 DDL：id / tenant_id / product_id /
     * color_id / door_width / price / stock / sku_code / sales_count / created_at / updated_at /
     * color_name / avg_cost / cost_amount / latest_batch_no）⇒ 此处**不得**照抄别的表的软删写法。</p>
     */
    static final String SUPPLY_SQL = """
            SELECT sk.product_id AS product_id,
                   MAX(p.name)  AS product_name,
                   SUM(sk.stock) AS stock_meters
              FROM product_skus sk
              JOIN products p ON p.id = sk.product_id
             WHERE sk.tenant_id = ?
               AND p.tenant_id = ?
               AND p.deleted = 0
             GROUP BY sk.product_id
            """;

    /** 单位真值 SQL（可比性判据 + 商品名；只取候选面用到的商品）。 */
    static final String UNIT_SQL = """
            SELECT id AS product_id, name AS product_name, unit AS unit
              FROM products
             WHERE tenant_id = ?
               AND deleted = 0
            """;

    /** 交期 SQL：最早 {@code orders.required_delivery_date}（V120/#5177；**可空 = 未指定**）。 */
    static final String DEADLINE_SQL = """
            SELECT oi.product_id AS product_id,
                   MIN(o.required_delivery_date) AS earliest_required_delivery_date
              FROM order_items oi
              JOIN orders o ON o.id = oi.order_id
             WHERE o.tenant_id = ?
               AND o.deleted = 0
               AND oi.deleted = 0
               AND o.status IN (%s)
               AND o.required_delivery_date IS NOT NULL
             GROUP BY oi.product_id
            """;

    /** 不可比行计数 SQL（披露面：分母 = 该状态集下的全部订单行）。 */
    static final String NON_COMPARABLE_SQL = """
            SELECT COUNT(*) AS lines
              FROM order_items oi
              JOIN orders o   ON o.id = oi.order_id
              JOIN products p ON p.id = oi.product_id
             WHERE o.tenant_id = ?
               AND p.tenant_id = ?
               AND o.deleted = 0
               AND oi.deleted = 0
               AND p.deleted = 0
               AND o.status IN (%s)
               AND (p.unit IS NULL OR p.unit <> ?)
            """;

    /**
     * 历史深度 SQL（预测层的唯一开关）：销售台账（{@code reason='order'}）的**周桶跨度 / 有效周数**。
     *
     * <p>只读一行两列 —— 本查询**不参与**任何速率 / 耗尽日推算（v1 未接线），只用来判「深度够不够」。
     * 业务时区口径 {@code Asia/Shanghai} 与 {@link BusinessClock#BUSINESS_ZONE} 同源。</p>
     */
    static final String HISTORY_DEPTH_SQL = """
            SELECT MIN(created_at) AS first_at,
                   MAX(created_at) AS last_at,
                   COUNT(DISTINCT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'IYYY-IW'))
                       AS active_weeks
              FROM stock_ledger_entries
             WHERE tenant_id = ?
               AND deleted = 0
               AND reason = 'order'
            """;

    /** 订单状态白名单（现取 DB 实测：pending 686 / confirmed 374 / producing 58 / shipped 21 / completed 7 / cancelled 5）。 */
    public static final Set<String> KNOWN_STATUSES = Set.of(
            "pending", "confirmed", "producing", "shipped", "completed", "cancelled");

    /**
     * 声明**无真值**的字段 —— 逐条具名理由（三态纪律的「未接线」支，**不可行动**）。
     *
     * <p>两条都是「真值**存在**，但 v1 装配层**未接线**」（区别于「根本没有这个列」）——
     * 理由里写清真值在哪、以及今天为什么读不出，避免被读成「已解决」。</p>
     */
    public static final Map<String, String> NO_TRUTH_REASONS = Map.of(
            "rate_per_week", "真值存在于销售台账（stock_ledger_entries，reason='order'），"
                    + "但 v1 装配层未接线：真实周桶深度不足（首行 2026-09-20 起），"
                    + "8 周门槛未达 ⇒ 速率一律未知（禁止硬算、禁止回填 0；重启条件见 history_depth）",
            "exhaust_date", "真值存在于销售台账，但 v1 装配层未接线：同 rate_per_week，"
                    + "历史深度不足 8 周 ⇒ 耗尽日一律未知（不得由当期缺口外推 —— 那会把"
                    + "「缺口大」错读成「马上耗尽」）");

    /** 字段 → 权威来源（**单点声明**；行键集见 {@link MaterialShortageViews#ROW_FIELDS}）。 */
    static final Map<String, String> FIELD_SOURCES = Map.ofEntries(
            Map.entry("product_id", "products.id / order_items.product_id / product_skus.product_id"),
            Map.entry("product_name", "products.name"),
            Map.entry("demand_qty", "order_items.quantity（orders.status ∈ statuses 且 products.unit = '米'）"),
            Map.entry("demand_lines", "order_items 行数（同一需求口径）"),
            Map.entry("order_count", "COUNT(DISTINCT order_items.order_id)（同一需求口径）"),
            Map.entry("stock_meters", "SUM(product_skus.stock) GROUP BY product_id（**不读** products.stock）"),
            Map.entry("gap_meters", "demand_qty − stock_meters（负 = 有余量，照实返回）"),
            Map.entry("risk_band", "gap_meters + days_to_deadline（口径见 basis.risk_band）"),
            Map.entry("days_to_deadline", "orders.required_delivery_date − as_of（**null = 紧迫性未知**）"),
            Map.entry("earliest_required_delivery_date", "MIN(orders.required_delivery_date)"),
            Map.entry("rate_per_week", "声明无真值（v1 未接线，见 NO_TRUTH_REASONS）"),
            Map.entry("exhaust_date", "声明无真值（v1 未接线，见 NO_TRUTH_REASONS）"),
            Map.entry("unwired", "本行读不出的字段名（装配层计算）"));

    static final Map<String, String> FIELD_LABELS = Map.ofEntries(
            Map.entry("product_id", "商品ID"),
            Map.entry("product_name", "商品名"),
            Map.entry("demand_qty", "需求量(米)"),
            Map.entry("demand_lines", "需求订单行数"),
            Map.entry("order_count", "涉及订单数"),
            Map.entry("stock_meters", "库存(米)"),
            Map.entry("gap_meters", "缺口(米)"),
            Map.entry("risk_band", "风险分层"),
            Map.entry("days_to_deadline", "距交期(天)"),
            Map.entry("earliest_required_delivery_date", "最早要求到货日"),
            Map.entry("rate_per_week", "周速率(米/周)"),
            Map.entry("exhaust_date", "预计耗尽日"),
            Map.entry("unwired", "本行未接线字段"));

    static final Map<String, String> FIELD_NOTES = Map.ofEntries(
            Map.entry("product_id", "商品主键（粒度 = 商品，不是 SKU）"),
            Map.entry("product_name", "商品档案里的名称"),
            Map.entry("demand_qty", "未完成订单行的用量合计；**单位不可比 ⇒ null（不是 0）**"),
            Map.entry("demand_lines", "需求订单行数；单位不可比 ⇒ null"),
            Map.entry("order_count", "涉及订单数；单位不可比 ⇒ null"),
            Map.entry("stock_meters", "Σ SKU 库存（权威口径；products.stock 是派生冗余列，不读）"),
            Map.entry("gap_meters", "需求 − 供给；负数 = 有余量（照实返回，不夹到 0）"),
            Map.entry("risk_band", "safe / blocked / critical / soon / short / unknown（六档）"),
            Map.entry("days_to_deadline", "交期 − as_of；**null = 紧迫性未知**（不是「今天到期」）"),
            Map.entry("earliest_required_delivery_date", "客户要求到货日（orders.required_delivery_date，V120/#5177）"),
            Map.entry("rate_per_week", "周速率 —— v1 未接线，恒 null"),
            Map.entry("exhaust_date", "预计耗尽日 —— v1 未接线，恒 null"),
            Map.entry("unwired", "该行读不出的字段名（空列表 = 本行无非可比格）"));

    private final JdbcTemplate jdbc;
    private final BusinessClock businessClock;

    /**
     * 端点入口：取数 + 装配（租户取自 {@link TenantContext}，**原样回显**）。
     *
     * @param statusesRaw 订单状态过滤（逗号分隔或已拆分；空 / null ⇒ {@link #DEFAULT_STATUSES}）
     * @param limitRaw    行数上限（null ⇒ {@value #DEFAULT_LIMIT}；&lt;1 或非整数 ⇒ 400）
     * @param asOfRaw     基准日（null / 空 ⇒ {@link BusinessClock#today()}；服务内不读挂钟）
     */
    public MaterialShortageView shortage(String statusesRaw, String limitRaw, String asOfRaw) {
        List<String> statuses = parseStatuses(statusesRaw);
        int limit = parseLimit(limitRaw);
        LocalDate asOf = parseAsOf(asOfRaw);
        Long tenantId = TenantContext.getTenantId();
        log.info("用料缺口视图: tenantId={}, statuses={}, limit={}, asOf={}", tenantId, statuses, limit, asOf);

        List<DemandRow> demand = jdbc.query(String.format(DEMAND_SQL, placeholders(statuses)),
                demandMapper, tenantId, tenantId, statuses.toArray(), COMPARABLE_UNIT);
        List<SupplyRow> supply = jdbc.query(SUPPLY_SQL, supplyMapper, tenantId, tenantId);
        List<UnitRow> units = jdbc.query(UNIT_SQL, unitMapper, tenantId);
        List<DeadlineRow> deadlines = jdbc.query(String.format(DEADLINE_SQL, placeholders(statuses)),
                deadlineMapper, tenantId, statuses.toArray());
        Integer nonComparableLines = jdbc.queryForObject(
                String.format(NON_COMPARABLE_SQL, placeholders(statuses)),
                Integer.class, tenantId, tenantId, statuses.toArray(), COMPARABLE_UNIT);
        HistoryDepth historyDepth = readHistoryDepth(tenantId);

        return compute(tenantId, asOf, limit, demand, supply, units, deadlines,
                nonComparableLines == null ? 0 : nonComparableLines, historyDepth, statuses);
    }

    // ── 纯函数（可单测：无 DB、无挂钟、与输入行序无关）──────────────────────────

    /**
     * 装配视图 —— **纯函数**（同一输入 ⇒ 同一输出，逐字相同）。
     *
     * <p>{@code demand} / {@code supply} / {@code units} / {@code deadlines} 是四条取数面的**原始行**；
     * 本方法不碰 DB、不读挂钟。{@code limit} 只影响 {@code rows}（**聚合用全量行**）。</p>
     */
    public static MaterialShortageView compute(
            Long tenantId,
            LocalDate asOf,
            int limit,
            List<DemandRow> demand,
            List<SupplyRow> supply,
            List<UnitRow> units,
            List<DeadlineRow> deadlines,
            int nonComparableLines,
            HistoryDepth historyDepth,
            List<String> statuses) {

        Map<String, DemandRow> demandByProduct = index(demand, DemandRow::productId);
        Map<String, SupplyRow> supplyByProduct = index(supply, SupplyRow::productId);
        Map<String, UnitRow> unitByProduct = index(units, UnitRow::productId);
        Map<String, DeadlineRow> deadlineByProduct = index(deadlines, DeadlineRow::productId);

        // 候选面 = 有需求 **或** 有供给的商品（并集，按 product_id 升序 ⇒ 与输入行序无关）
        Set<String> candidates = new LinkedHashSet<>();
        candidates.addAll(demandByProduct.keySet());
        candidates.addAll(supplyByProduct.keySet());

        List<MaterialShortageRow> rows = new ArrayList<>(candidates.size());
        int nonComparableProducts = 0;
        for (String productId : new TreeSet<>(candidates)) {
            UnitRow unit = unitByProduct.get(productId);
            DemandRow d = demandByProduct.get(productId);
            SupplyRow s = supplyByProduct.get(productId);
            DeadlineRow dl = deadlineByProduct.get(productId);

            // 🔴 可比性 = **商品档案**的 unit 逐字等于 '米'；订单行的 selling_method 不参与（不可靠）
            boolean comparable = unit != null && COMPARABLE_UNIT.equals(unit.unit());
            if (!comparable) {
                nonComparableProducts++;
            }

            BigDecimal demandQty = comparable ? nullToZero(d == null ? null : d.demandQty()) : null;
            Integer demandLines = comparable ? intOrZero(d == null ? null : d.demandLines()) : null;
            Integer orderCount = comparable ? intOrZero(d == null ? null : d.orderCount()) : null;
            BigDecimal stockMeters = nullToZero(s == null ? null : s.stockMeters());

            LocalDate earliest = dl == null ? null : dl.earliest();
            Integer daysToDeadline = (earliest == null || !comparable) ? null : (int) (earliest.toEpochDay() - asOf.toEpochDay());

            // 🔴 缺口：单位不可比 ⇒ **null**（口径不可相减，不是 0），否则照实返回（负 = 有余量）
            BigDecimal gap = comparable ? demandQty.subtract(stockMeters) : null;

            List<String> unwired = new ArrayList<>();
            if (!comparable) {
                unwired.addAll(List.of("demand_qty", "demand_lines", "order_count", "gap_meters", "risk_band"));
            } else if (daysToDeadline == null) {
                unwired.add("days_to_deadline");
            }
            unwired.addAll(NO_TRUTH_REASONS.keySet());

            rows.add(new MaterialShortageRow(
                    productId,
                    nameOf(unit, d, s),
                    demandQty,
                    demandLines,
                    orderCount,
                    stockMeters,
                    gap,
                    band(comparable, gap, daysToDeadline),
                    daysToDeadline,
                    earliest,
                    null,   // rate_per_week —— v1 未接线（not_wired），**不得**回填
                    null,   // exhaust_date  —— v1 未接线（not_wired），**不得**回填
                    unwired));
        }

        // 行序：分层降序 → 缺口降序 → 商品 id 升序（同一快照逐字相同）
        rows.sort(Comparator
                .comparingInt((MaterialShortageRow r) -> MaterialShortageViews.RISK_BANDS.indexOf(r.riskBand()))
                .thenComparing(MaterialShortageRow::gapMeters,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(MaterialShortageRow::productId));

        // 🔴 聚合用**全量**行（不随 limit 变）；截断只动 rows
        Map<String, Integer> bandCounts = new LinkedHashMap<>();
        for (String bandName : MaterialShortageViews.RISK_BANDS) {
            bandCounts.put(bandName, 0);
        }
        for (MaterialShortageRow row : rows) {
            bandCounts.merge(row.riskBand(), 1, Integer::sum);
        }
        int rowsTotal = rows.size();
        boolean truncated = rowsTotal > limit;
        List<MaterialShortageRow> page = truncated ? List.copyOf(rows.subList(0, limit)) : List.copyOf(rows);

        Map<String, FieldInfo> fields = fieldStatus(page.size(), rowsTotal, truncated, limit,
                nonComparableProducts, nonComparableLines, unknownDeadlineRows(rows));

        List<String> noTruth = new ArrayList<>();
        List<String> hasTruth = new ArrayList<>();
        for (Map.Entry<String, FieldInfo> e : fields.entrySet()) {
            (MaterialShortageViews.NO_TRUTH.equals(e.getValue().truth()) ? noTruth : hasTruth).add(e.getKey());
        }
        noTruth.sort(Comparator.naturalOrder());
        hasTruth.sort(Comparator.naturalOrder());

        return new MaterialShortageView(
                MaterialShortageViews.VIEW_ID,
                tenantId,
                asOf.toString(),
                Map.of(
                        "granularity", "product（商品级）—— 订单行无原生 sku_id 列（SKU 身份仅在 processing_info jsonb），"
                                + "SKU 级覆盖率上限约 25% ⇒ v1 只做商品级",
                        "unit", "米（米）；可比性判据 = products.unit = '米'（**商品档案**是真值，"
                                + "订单行的 selling_method 只有 NULL / bulk_cut，不可靠）",
                        "statuses", String.join(",", statuses) + "（入参口径）",
                        "demand_source", "SUM(order_items.quantity) WHERE orders.status ∈ statuses "
                                + "AND products.unit = '米'（软删/租户逐表过滤）",
                        "supply_source", "SUM(product_skus.stock) GROUP BY product_id —— **不读** products.stock"
                                + "（派生冗余列，实测差 3.3%）",
                        "row_order", "risk_band 降序 " + MaterialShortageViews.RISK_BANDS
                                + " → gap_meters 降序 → product_id 升序",
                        "risk_band", "gap ≤ 0 ⇒ safe；gap > 0 且交期已过 ⇒ blocked；"
                                + "gap > 0 且 ≤ " + CRITICAL_DAYS + " 天 ⇒ critical；"
                                + "gap > 0 且 ≤ " + SOON_DAYS + " 天 ⇒ soon；"
                                + "gap > 0 且 > " + SOON_DAYS + " 天**或交期未知** ⇒ " + BAND_SHORT
                                + "（🔴 缺口确定、紧迫性未知**单列**，不并进 critical）；"
                                + "单位不可比 ⇒ " + BAND_UNKNOWN,
                        "truth_source", "MaterialShortageService 的 FIELD_SOURCES / NO_TRUTH_REASONS（**单点声明**）"),
                fields,
                page,
                page.size(),
                rowsTotal,
                truncated,
                noTruth,
                hasTruth,
                bandCounts,
                new NonComparable(nonComparableLines, nonComparableProducts),
                nonComparableLines,
                nonComparableProducts,
                historyDepth);
    }

    /** 分层（六档；{@link #BAND_SHORT} 是「缺口确定、紧迫性未知」—— 🔴 不得并进 critical）。 */
    public static String band(boolean comparable, BigDecimal gap, Integer daysToDeadline) {
        if (!comparable) {
            return BAND_UNKNOWN;
        }
        if (gap == null || gap.signum() <= 0) {
            return BAND_SAFE;
        }
        if (daysToDeadline == null) {
            // 缺口确定、紧迫性未知 ⇒ **单列 short**（并进 critical 会把没填交期的排进最紧急一批）
            return BAND_SHORT;
        }
        if (daysToDeadline < 0) {
            return "blocked";
        }
        if (daysToDeadline <= CRITICAL_DAYS) {
            return "critical";
        }
        if (daysToDeadline <= SOON_DAYS) {
            return "soon";
        }
        return BAND_SHORT;
    }

    /**
     * 逐字段三态（不变式：**{@code reason == null} ⟺ {@code status == wired}**）。
     *
     * <p>缺口（{@code gaps}）三种：① 有真值字段在**部分行**上读不出（单位不可比 / 交期未知）；
     * ② 视图输出被上限**截断**（带上限与本次实际值的可归因读数）；③ 声明无真值的字段
     * （恒 {@code not_wired} + 具名理由，**不是** {@code incomplete}）。</p>
     */
    static Map<String, FieldInfo> fieldStatus(int count, int rowsTotal, boolean truncated, int limit,
                                              int nonComparableProducts, int nonComparableLines,
                                              int unknownDeadlineRows) {
        Map<String, FieldInfo> out = new LinkedHashMap<>();
        for (String field : MaterialShortageViews.ROW_FIELDS) {
            String source = FIELD_SOURCES.get(field);
            String label = FIELD_LABELS.get(field);
            String note = FIELD_NOTES.get(field);
            if (NO_TRUTH_REASONS.containsKey(field)) {
                out.put(field, new FieldInfo(MaterialShortageViews.NOT_WIRED,
                        "声明无真值（v1 未接线）：" + NO_TRUTH_REASONS.get(field),
                        source, MaterialShortageViews.NO_TRUTH, note, label));
                continue;
            }
            List<String> gaps = new ArrayList<>();
            switch (field) {
                case "demand_qty", "demand_lines", "order_count", "gap_meters", "risk_band" ->
                        addIf(gaps, nonComparableProducts > 0, String.format(
                                "%d 个商品单位不可比（products.unit ≠ '米'，涉及 %d 个订单行）"
                                        + "⇒ 这些商品的该字段**未知**（不是 0）", nonComparableProducts,
                                nonComparableLines));
                case "days_to_deadline", "earliest_required_delivery_date" ->
                        addIf(gaps, unknownDeadlineRows > 0, String.format(
                                "%d 个候选商品的订单全部没有要求到货日（orders.required_delivery_date 为 NULL）"
                                        + "⇒ 紧迫性**未知**（不得回填 0 天）", unknownDeadlineRows));
                default -> {
                    // 其余字段无「部分行读不出」形态
                }
            }
            if (truncated) {
                gaps.add(String.format("视图输出被上限截断（上限 %d 行，本次给出 %d 行，共 %d 行）⇒ 结论不完整",
                        limit, count, rowsTotal));
            }
            out.put(field, new FieldInfo(
                    gaps.isEmpty() ? MaterialShortageViews.WIRED : MaterialShortageViews.INCOMPLETE,
                    gaps.isEmpty() ? null : String.join("；", gaps),
                    source, MaterialShortageViews.HAS_TRUTH, note, label));
        }
        return out;
    }

    /** 候选行里「可比但订单全无交期」的商品数（逐行判 —— 缺值不许被读成「今天到期」）。 */
    static int unknownDeadlineRows(List<MaterialShortageRow> rows) {
        int n = 0;
        for (MaterialShortageRow row : rows) {
            if (!BAND_UNKNOWN.equals(row.riskBand()) && row.earliestRequiredDeliveryDate() == null) {
                n++;
            }
        }
        return n;
    }

    /** 历史深度判定（🔴 {@code sufficient == false} ⇒ 速率 / 耗尽日一律 null + not_wired）。 */
    public static HistoryDepth historyDepth(LocalDate first, LocalDate last, int activeWeeks) {
        int weeks = 0;
        if (first != null && last != null && !last.isBefore(first)) {
            weeks = (int) Math.max(1, (last.toEpochDay() - first.toEpochDay() + 1) / 7);
        }
        int active = Math.max(0, activeWeeks);
        if (weeks >= REQUIRED_WEEKS && active >= REQUIRED_WEEKS) {
            return new HistoryDepth(weeks, active, REQUIRED_WEEKS, true, null);
        }
        String reason = weeks == 0
                ? String.format("销售台账无 %s 周桶（reason='order' 零行）⇒ 历史深度 0 周 < 要求 %d 周"
                        + " ⇒ 速率 / 耗尽日 / 预测区间一律未知（禁止硬算、禁止回填 0）",
                        REQUIRED_WEEKS, REQUIRED_WEEKS)
                : String.format("真实台账周桶跨度 %d 周 / 有效 %d 周 < 要求 %d 周 ⇒ 速率 / 耗尽日 / "
                        + "预测区间一律未知（禁止硬算、禁止回填 0）", weeks, active, REQUIRED_WEEKS);
        return new HistoryDepth(weeks, active, REQUIRED_WEEKS, false, reason);
    }

    // ── 入参解析（fail-closed：非法值显式拒绝，不静默回落）──────────────────────

    /** 默认状态集（与族 1 {@code UNSHIPPED_STATUSES} 同口径：不做 {@code pending}，避免未付款意向单放大缺口）。 */
    public static final List<String> DEFAULT_STATUSES = List.of("confirmed", "producing");

    /** 状态解析：空 ⇒ 缺省；未知状态 ⇒ 400（**不静默忽略**——静默会让判据悄悄变松）。 */
    public static List<String> parseStatuses(String raw) {
        if (!StringUtils.hasText(raw)) {
            return DEFAULT_STATUSES;
        }
        List<String> out = new ArrayList<>();
        for (String part : raw.split(",")) {
            String s = part.trim().toLowerCase(Locale.ROOT);
            if (s.isEmpty()) {
                continue;
            }
            if (!KNOWN_STATUSES.contains(s)) {
                throw new BusinessException(ERR_STATUS_UNKNOWN,
                        String.format("未知的订单状态：%s", part),
                        400,
                        "可选值：" + String.join(" / ", KNOWN_STATUSES) + "（缺省 "
                                + String.join(",", DEFAULT_STATUSES) + "）");
            }
            if (!out.contains(s)) {
                out.add(s);
            }
        }
        if (out.isEmpty()) {
            return DEFAULT_STATUSES;
        }
        return List.copyOf(out);
    }

    /** 上限解析：缺省 {@value #DEFAULT_LIMIT}；非整数 / &lt;1 ⇒ 400（**不夹到 1**——静默夹取会让判据失真）。 */
    public static int parseLimit(String raw) {
        if (!StringUtils.hasText(raw)) {
            return DEFAULT_LIMIT;
        }
        int limit;
        try {
            limit = Integer.parseInt(raw.trim());
        } catch (NumberFormatException e) {
            throw new BusinessException(ERR_LIMIT_INVALID,
                    String.format("limit 必须是整数且 ≥ 1：%s", raw), 400,
                    String.format("limit 必须 ≥ 1（缺省 %d）", DEFAULT_LIMIT));
        }
        if (limit < 1) {
            throw new BusinessException(ERR_LIMIT_INVALID,
                    String.format("limit 必须 ≥ 1：%d", limit), 400,
                    String.format("limit 必须 ≥ 1（缺省 %d）", DEFAULT_LIMIT));
        }
        return limit;
    }

    /** 基准日解析：空 ⇒ {@link BusinessClock#today()}（**唯一**读挂钟处，仅在调用方未传时）。 */
    public LocalDate parseAsOf(String raw) {
        if (!StringUtils.hasText(raw)) {
            return businessClock.today();
        }
        try {
            return LocalDate.parse(raw.trim());
        } catch (RuntimeException e) {
            throw new BusinessException("MATERIAL_SHORTAGE_AS_OF_INVALID",
                    String.format("as_of 必须是 YYYY-MM-DD：%s", raw), 400,
                    "例：as_of=2026-10-04（不传则取业务「今天」，Asia/Shanghai）");
        }
    }

    // ── 取数辅助 ────────────────────────────────────────────────────────────────

    private HistoryDepth readHistoryDepth(Long tenantId) {
        List<HistoryRow> rows = jdbc.query(HISTORY_DEPTH_SQL, historyMapper, tenantId);
        if (rows.isEmpty()) {
            return historyDepth(null, null, 0);
        }
        HistoryRow row = rows.get(0);
        return historyDepth(row.first(), row.last(), row.activeWeeks());
    }

    /** {@code IN (?, ?, …)} 的占位符（状态个数现取 —— 不拼字符串进 SQL）。 */
    static String placeholders(List<String> statuses) {
        return String.join(",", java.util.Collections.nCopies(Math.max(1, statuses.size()), "?"));
    }

    private static <T> Map<String, T> index(List<T> rows, java.util.function.Function<T, String> key) {
        Map<String, T> out = new HashMap<>();
        for (T row : rows) {
            if (row == null) {
                continue;
            }
            String k = key.apply(row);
            if (StringUtils.hasText(k)) {
                out.put(k, row);
            }
        }
        return out;
    }

    private static String nameOf(UnitRow unit, DemandRow d, SupplyRow s) {
        if (unit != null && StringUtils.hasText(unit.productName())) {
            return unit.productName();
        }
        if (d != null && StringUtils.hasText(d.productName())) {
            return d.productName();
        }
        return s == null ? null : s.productName();
    }

    private static void addIf(List<String> list, boolean condition, String message) {
        if (condition) {
            list.add(message);
        }
    }

    private static BigDecimal nullToZero(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value.setScale(1, RoundingMode.HALF_UP);
    }

    private static Integer intOrZero(Integer value) {
        return value == null ? 0 : value;
    }

    private static LocalDate toLocalDate(Object raw) {
        if (raw == null) {
            return null;
        }
        if (raw instanceof LocalDate ld) {
            return ld;
        }
        if (raw instanceof Date d) {
            return d.toLocalDate();
        }
        if (raw instanceof Timestamp ts) {
            return ts.toLocalDateTime().toLocalDate();
        }
        return LocalDate.parse(raw.toString());
    }

    // ── 取数行（四条取数面的**原始行**；测试可直接构造）────────────────────────

    /** 需求行（{@link #DEMAND_SQL}）。 */
    public record DemandRow(String productId, String productName, BigDecimal demandQty,
                            Integer demandLines, Integer orderCount) {
    }

    /** 供给行（{@link #SUPPLY_SQL}）。 */
    public record SupplyRow(String productId, String productName, BigDecimal stockMeters) {
    }

    /** 单位行（{@link #UNIT_SQL}）—— 可比性判据的**唯一**来源。 */
    public record UnitRow(String productId, String productName, String unit) {
    }

    /** 交期行（{@link #DEADLINE_SQL}）。 */
    public record DeadlineRow(String productId, LocalDate earliest) {
    }

    /** 历史深度行（{@link #HISTORY_DEPTH_SQL}）。 */
    record HistoryRow(LocalDate first, LocalDate last, Integer activeWeeks) {
    }

    // ── RowMapper ──────────────────────────────────────────────────────────────

    static final RowMapper<DemandRow> demandMapper = (rs, i) -> new DemandRow(
            rs.getString("product_id"), rs.getString("product_name"),
            rs.getBigDecimal("demand_qty"), (Integer) rs.getObject("demand_lines"),
            (Integer) rs.getObject("order_count"));

    static final RowMapper<SupplyRow> supplyMapper = (rs, i) -> new SupplyRow(
            rs.getString("product_id"), rs.getString("product_name"), rs.getBigDecimal("stock_meters"));

    /**
     * 单位行映射 —— **只读 {@code unit}**（可比性真值）。
     *
     * <p>行里即便出现 {@code selling_method} 之类的订单行字段也**不读**（那正是 #6280 实测不可靠的来源）。</p>
     */
    static final RowMapper<UnitRow> unitMapper = (rs, i) -> new UnitRow(
            rs.getString("product_id"), rs.getString("product_name"), rs.getString("unit"));

    static final RowMapper<DeadlineRow> deadlineMapper = (rs, i) -> new DeadlineRow(
            rs.getString("product_id"), toLocalDate(rs.getObject("earliest_required_delivery_date")));

    static final RowMapper<HistoryRow> historyMapper = (rs, i) -> new HistoryRow(
            toLocalDate(rs.getObject("first_at")), toLocalDate(rs.getObject("last_at")),
            (Integer) rs.getObject("active_weeks"));
}
