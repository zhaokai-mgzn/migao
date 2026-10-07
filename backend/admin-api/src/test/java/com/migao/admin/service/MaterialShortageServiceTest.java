// case_ids: DA-022
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.MaterialShortageViews;
import com.migao.admin.dto.MaterialShortageViews.FieldInfo;
import com.migao.admin.dto.MaterialShortageViews.HistoryDepth;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageRow;
import com.migao.admin.dto.MaterialShortageViews.MaterialShortageView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.MaterialShortageService.DeadlineRow;
import com.migao.admin.service.MaterialShortageService.DemandRow;
import com.migao.admin.service.MaterialShortageService.SupplyRow;
import com.migao.admin.service.MaterialShortageService.UnitRow;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * {@code material_shortage}（商品级用料缺口与耗尽风险，issue #6280）的**确定性判据**。
 *
 * <p>核心是**纯函数装配层**（{@link MaterialShortageService#compute}）：需求 / 供给 / 缺口 /
 * 分层 / 三态 / 深度判据全是纯计算，不碰 DB、不读挂钟 —— DB 只负责取数（取数面由集成面覆盖，
 * 本判据不为了它起 PG）。</p>
 *
 * <h2>会红的三条（本视图最容易做成假绿的地方）</h2>
 * <ol>
 *   <li><b>「未知 ≠ 0」</b>：单位不可比 ⇒ {@code demandQty = null} + {@code band = unknown}；
 *       真 0 需求 ⇒ 照实 {@code 0} + {@code safe}；交期未知 ⇒ {@code daysToDeadline = null}
 *       （**不得回填 0 天**）。注入式红证：把 {@code null} 回填成 0 ⇒ 本组判据当场红。</li>
 *   <li><b>逐字段三态</b>：不变式 {@code reason == null ⟺ status == wired}；
 *       {@code rate_per_week} / {@code exhaust_date} 恒 {@code not_wired} + 具名理由；
 *       截断 ⇒ 有真值字段落 {@code incomplete} + 带上限与实际值的可归因读数。</li>
 *   <li><b>确定性</b>：{@code src/main} 的服务源码里**不出现**挂钟读取（源码扫描，机械判据）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("MaterialShortageService 用料缺口视图")
class MaterialShortageServiceTest {

    private static final String SERVICE_REL =
            "backend/admin-api/src/main/java/com/migao/admin/service/MaterialShortageService.java";
    private static final String WIRING_UNDER_TEST =
            "backend/admin-api/src/main/java/com/migao/admin/service/MaterialShortageService.java::DEMAND_SQL";
    private static final LocalDate AS_OF = LocalDate.of(2026, 10, 4);

    @Mock
    private JdbcTemplate jdbc;

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────────

    private static DemandRow demand(String id, String name, String qty, int lines, int orders) {
        return new DemandRow(id, name, new BigDecimal(qty), lines, orders);
    }

    private static SupplyRow supply(String id, String name, String stock) {
        return new SupplyRow(id, name, new BigDecimal(stock));
    }

    private static UnitRow unit(String id, String name, String u) {
        return new UnitRow(id, name, u);
    }

    private static DeadlineRow deadline(String id, LocalDate date) {
        return new DeadlineRow(id, date);
    }

    private static MaterialShortageView build(int limit,
                                              List<DemandRow> demand,
                                              List<SupplyRow> supply,
                                              List<UnitRow> units,
                                              List<DeadlineRow> deadlines) {
        return MaterialShortageService.compute(1L, AS_OF, limit, demand, supply, units, deadlines,
                0, MaterialShortageService.historyDepth(null, null, 0),
                MaterialShortageService.DEFAULT_STATUSES);
    }

    private static MaterialShortageRow row(MaterialShortageView view, String productId) {
        return view.rows().stream()
                .filter(r -> productId.equals(r.productId()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("缺行：" + productId + "，实际行 = "
                        + view.rows().stream().map(MaterialShortageRow::productId).toList()));
    }

    // ── 纪律 1：「未知 ≠ 0」 ─────────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 单位不可比 ⇒ demand_qty=null + band=unknown（**不是 0**），且与「真 0 需求」可分")
    void nonComparableUnitIsUnknownNotZero() {
        MaterialShortageView view = build(50,
                List.of(demand("p-piece", "非米商品", "400.0", 3, 2),
                        demand("p-zero", "真零需求商品", "0.0", 1, 1)),
                List.of(supply("p-piece", "非米商品", "41.0"),
                        supply("p-zero", "真零需求商品", "0.0")),
                List.of(unit("p-piece", "非米商品", "件"),
                        unit("p-zero", "真零需求商品", "米")),
                List.of());

        MaterialShortageRow piece = row(view, "p-piece");
        // 「件」不可比：读不出，因此**未知** —— 把它写成 0 就是「把读不出记成没有需求」
        assertThat(piece.riskBand()).isEqualTo("unknown");
        assertThat(piece.demandQty()).isNull();
        assertThat(piece.demandLines()).isNull();
        assertThat(piece.orderCount()).isNull();
        assertThat(piece.gapMeters()).isNull();
        assertThat(piece.unwired()).contains("demand_qty", "gap_meters", "risk_band");
        assertThat(view.bandCounts().get("unknown")).isEqualTo(1);
        assertThat(view.nonComparable().products()).isEqualTo(1);

        // 真 0 需求：可比、合计确为 0 ⇒ 照实 0，且**不是** unknown
        MaterialShortageRow zero = row(view, "p-zero");
        assertThat(zero.demandQty()).isEqualByComparingTo("0");
        // 夹具固定 1 个需求行 ⇒ 照实回显 1；关键是**与不可比行的 null 可分**（不是 0/未知混同）
        assertThat(zero.demandLines()).isEqualTo(1);
        assertThat(zero.riskBand()).isEqualTo("safe");
        assertThat(zero.unwired()).doesNotContain("demand_qty");
    }

    @Test
    @DisplayName("🔴 交期未知 ⇒ days_to_deadline=null + band=short（**不得回填 0 天**）")
    void missingDeadlineIsShortNotZeroDays() {
        MaterialShortageView view = build(50,
                List.of(demand("p1", "缺货无交期", "10.0", 1, 1)),
                List.of(supply("p1", "缺货无交期", "4.0")),
                List.of(unit("p1", "缺货无交期", "米")),
                List.of());

        MaterialShortageRow r = row(view, "p1");
        assertThat(r.gapMeters()).isEqualByComparingTo("6.0");
        assertThat(r.daysToDeadline()).isNull();
        // 缺口确定、紧迫性未知 ⇒ 单列 short（并进 critical 会把没填交期的排进最紧急一批）
        assertThat(r.riskBand()).isEqualTo("short");
        assertThat(r.unwired()).contains("days_to_deadline");
    }

    @Test
    @DisplayName("缺口 = 需求 − 供给（**负 = 有余量照实返回**，不夹到 0）")
    void gapIsSignedAndTruthful() {
        MaterialShortageView view = build(50,
                List.of(demand("p-short", "缺", "10.0", 1, 1),
                        demand("p-over", "余", "1.0", 1, 1),
                        demand("p-even", "平", "5.0", 1, 1)),
                List.of(supply("p-short", "缺", "4.0"),
                        supply("p-over", "余", "9.0"),
                        supply("p-even", "平", "5.0")),
                List.of(unit("p-short", "缺", "米"), unit("p-over", "余", "米"), unit("p-even", "平", "米")),
                List.of());

        assertThat(row(view, "p-short").gapMeters()).isEqualByComparingTo("6.0");
        assertThat(row(view, "p-over").gapMeters()).isEqualByComparingTo("-8.0");
        assertThat(row(view, "p-even").gapMeters()).isEqualByComparingTo("0");
        assertThat(row(view, "p-over").riskBand()).isEqualTo("safe");
        assertThat(row(view, "p-even").riskBand()).isEqualTo("safe");
    }

    @Test
    @DisplayName("有交期时六档正确：blocked / critical / soon / short（边界 ≤3、≤7）")
    void bandsWithDeadline() {
        MaterialShortageView view = build(50,
                List.of(demand("p-blocked", "已过", "10.0", 1, 1),
                        demand("p-critical", "三天", "10.0", 1, 1),
                        demand("p-soon", "七天", "10.0", 1, 1),
                        demand("p-short", "八天", "10.0", 1, 1)),
                List.of(supply("p-blocked", "已过", "0.0"), supply("p-critical", "三天", "0.0"),
                        supply("p-soon", "七天", "0.0"), supply("p-short", "八天", "0.0")),
                List.of(unit("p-blocked", "已过", "米"), unit("p-critical", "三天", "米"),
                        unit("p-soon", "七天", "米"), unit("p-short", "八天", "米")),
                List.of(deadline("p-blocked", AS_OF.minusDays(1)),
                        deadline("p-critical", AS_OF.plusDays(3)),
                        deadline("p-soon", AS_OF.plusDays(7)),
                        deadline("p-short", AS_OF.plusDays(8))));

        assertThat(row(view, "p-blocked").riskBand()).isEqualTo("blocked");
        assertThat(row(view, "p-critical").riskBand()).isEqualTo("critical");
        assertThat(row(view, "p-soon").riskBand()).isEqualTo("soon");
        assertThat(row(view, "p-short").riskBand()).isEqualTo("short");
        assertThat(row(view, "p-critical").daysToDeadline()).isEqualTo(3);
        assertThat(row(view, "p-blocked").daysToDeadline()).isEqualTo(-1);
        assertThat(view.bandCounts()).containsEntry("blocked", 1).containsEntry("critical", 1)
                .containsEntry("soon", 1).containsEntry("short", 1).containsEntry("safe", 0)
                .containsEntry("unknown", 0);
    }

    @Test
    @DisplayName("行序 = 分层降序 → 缺口降序 → product_id 升序（同一快照逐字相同，与输入行序无关）")
    void rowOrderIsDeterministic() {
        List<DemandRow> demand = List.of(
                demand("p-c2", "c2", "30.0", 1, 1),
                demand("p-b2", "b2", "30.0", 1, 1),
                demand("p-a1", "a1", "99.0", 1, 1),
                demand("p-u1", "u1", "5.0", 1, 1),
                demand("p-b1", "b1", "40.0", 1, 1));
        List<SupplyRow> supply = List.of(supply("p-c2", "c2", "0.0"), supply("p-b2", "b2", "0.0"),
                supply("p-a1", "a1", "0.0"), supply("p-u1", "u1", "0.0"), supply("p-b1", "b1", "0.0"));
        List<UnitRow> units = List.of(unit("p-c2", "c2", "米"), unit("p-b2", "b2", "米"),
                unit("p-a1", "a1", "米"), unit("p-u1", "u1", "件"), unit("p-b1", "b1", "米"));
        List<DeadlineRow> deadlines = List.of(deadline("p-a1", AS_OF.minusDays(2)),
                deadline("p-b1", AS_OF.minusDays(1)), deadline("p-b2", AS_OF.minusDays(1)),
                deadline("p-c2", AS_OF.minusDays(1)));

        MaterialShortageView view = build(50, demand, supply, units, deadlines);
        // 行序 = 分层**紧急度降序**（blocked0 → critical1 → short3 → safe4）→ gap 降序 → product_id 升序。
        // p-a1 = blocked（交期已过 2 天，gap 99）；p-b1/p-b2/p-c2 = critical（交期 1 天前）；
        // 三档内 gap 降序 = 40 / 30 / 30，同 gap 再按 product_id 升序（p-b2 < p-c2）；
        // p-u1 = unknown（单位「件」不可比）恒排最后。
        assertThat(view.rows().stream().map(MaterialShortageRow::productId).toList())
                .containsExactly("p-a1", "p-b1", "p-b2", "p-c2", "p-u1");

        // 反向输入行序 ⇒ 逐字相同输出（同一快照确定性）
        List<DemandRow> reversed = new ArrayList<>(demand);
        java.util.Collections.reverse(reversed);
        MaterialShortageView again = build(50, reversed, supply, units, deadlines);
        assertThat(again.rows().stream().map(MaterialShortageRow::productId).toList())
                .isEqualTo(view.rows().stream().map(MaterialShortageRow::productId).toList());
    }

    // ── 纪律 2：逐字段三态 ──────────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 不变式 reason == null ⟺ status == wired；rate_per_week / exhaust_date 恒 not_wired + 具名理由")
    void fieldTriStateInvariantAndUnwiredPrediction() {
        MaterialShortageView view = build(50,
                List.of(demand("p1", "a", "10.0", 1, 1)),
                List.of(supply("p1", "a", "1.0")),
                List.of(unit("p1", "a", "米")),
                List.of(deadline("p1", AS_OF.plusDays(1))));

        for (Map.Entry<String, FieldInfo> e : view.fields().entrySet()) {
            FieldInfo info = e.getValue();
            assertThat(info.status()).as("%s 状态", e.getKey())
                    .isIn(MaterialShortageViews.WIRED, MaterialShortageViews.NOT_WIRED,
                            MaterialShortageViews.INCOMPLETE);
            assertThat(info.truth()).as("%s 真值", e.getKey())
                    .isIn(MaterialShortageViews.HAS_TRUTH, MaterialShortageViews.NO_TRUTH);
            // 不变式：reason 有值 ⟺ 不是 wired
            assertThat(info.reason() == null)
                    .as("%s：reason=%s / status=%s（不变式 reason==null ⟺ wired）",
                            e.getKey(), info.reason(), info.status())
                    .isEqualTo(MaterialShortageViews.WIRED.equals(info.status()));
        }

        // 字段字典必须覆盖行里的每一个键（缺一个 = 契约静默漏字段）
        assertThat(view.fields().keySet())
                .containsExactlyInAnyOrderElementsOf(MaterialShortageViews.ROW_FIELDS);
        assertThat(view.noTruthFields()).containsExactly("exhaust_date", "rate_per_week");
        assertThat(view.fields().get("rate_per_week").status()).isEqualTo(MaterialShortageViews.NOT_WIRED);
        assertThat(view.fields().get("rate_per_week").reason()).contains("未接线");
        assertThat(view.fields().get("exhaust_date").status()).isEqualTo(MaterialShortageViews.NOT_WIRED);

        // 声明无真值的两格恒 null（不得回填）
        assertThat(view.rows().get(0).ratePerWeek()).isNull();
        assertThat(view.rows().get(0).exhaustDate()).isNull();
    }

    @Test
    @DisplayName("🔴 截断：有真值字段落 incomplete + 带上限与本次实际值的可归因读数；声明无真值字段**不受截断影响**")
    void truncationMarksIncompleteWithAttributableReading() {
        List<DemandRow> demand = new ArrayList<>();
        List<SupplyRow> supply = new ArrayList<>();
        List<UnitRow> units = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            demand.add(demand("p" + i, "n" + i, "10.0", 1, 1));
            supply.add(supply("p" + i, "n" + i, "0.0"));
            units.add(unit("p" + i, "n" + i, "米"));
        }
        MaterialShortageView view = build(2, demand, supply, units, List.of());

        assertThat(view.truncated()).isTrue();
        assertThat(view.count()).isEqualTo(2);
        assertThat(view.rowsTotal()).isEqualTo(3);
        assertThat(view.rows()).hasSize(2);

        FieldInfo gap = view.fields().get("gap_meters");
        assertThat(gap.status()).isEqualTo(MaterialShortageViews.INCOMPLETE);
        assertThat(gap.reason()).contains("上限 2 行").contains("本次给出 2 行").contains("共 3 行");

        // 「声明无真值」不是「本次不完整」⇒ 截断不许把 not_wired 翻成 incomplete
        assertThat(view.fields().get("rate_per_week").status()).isEqualTo(MaterialShortageViews.NOT_WIRED);
        assertThat(view.fields().get("rate_per_week").reason()).doesNotContain("截断");
    }

    @Test
    @DisplayName("🔴 聚合用**全量行**：band_counts / non_comparable 不随 limit 变")
    void aggregateUsesFullRowSetNotTruncatedPage() {
        MaterialShortageView full = build(50,
                List.of(demand("p1", "a", "10.0", 1, 1), demand("p2", "b", "10.0", 1, 1),
                        demand("p3", "c", "400.0", 1, 1)),
                List.of(supply("p1", "a", "0.0"), supply("p2", "b", "0.0"), supply("p3", "c", "0.0")),
                List.of(unit("p1", "a", "米"), unit("p2", "b", "米"), unit("p3", "c", "件")),
                List.of());
        MaterialShortageView truncated = build(1,
                List.of(demand("p1", "a", "10.0", 1, 1), demand("p2", "b", "10.0", 1, 1),
                        demand("p3", "c", "400.0", 1, 1)),
                List.of(supply("p1", "a", "0.0"), supply("p2", "b", "0.0"), supply("p3", "c", "0.0")),
                List.of(unit("p1", "a", "米"), unit("p2", "b", "米"), unit("p3", "c", "件")),
                List.of());

        assertThat(truncated.rows()).hasSize(1);
        assertThat(truncated.bandCounts()).isEqualTo(full.bandCounts());
        assertThat(truncated.bandCounts().get("unknown")).isEqualTo(1);
        assertThat(truncated.nonComparable().products()).isEqualTo(1);
        assertThat(truncated.rowsTotal()).isEqualTo(3);
    }

    // ── 契约键 / 常量 / 深度判据 ────────────────────────────────────────────────

    @Test
    @DisplayName("契约常量与行键集逐字冻结：view / 六档 / 行键")
    void contractKeysAreFrozen() {
        assertThat(MaterialShortageViews.VIEW_ID).isEqualTo("material_shortage");
        assertThat(MaterialShortageViews.RISK_BANDS)
                .containsExactly("blocked", "critical", "soon", "short", "safe", "unknown");
        assertThat(MaterialShortageViews.ROW_FIELDS).containsExactly(
                "product_id", "product_name", "demand_qty", "demand_lines", "order_count",
                "stock_meters", "gap_meters", "risk_band", "days_to_deadline",
                "earliest_required_delivery_date", "rate_per_week", "exhaust_date", "unwired");
        assertThat(MaterialShortageService.DEFAULT_LIMIT).isEqualTo(50);
        assertThat(MaterialShortageService.REQUIRED_WEEKS).isEqualTo(8);
        assertThat(MaterialShortageService.COMPARABLE_UNIT).isEqualTo("米");

        MaterialShortageView view = build(50, List.of(), List.of(), List.of(), List.of());
        assertThat(view.view()).isEqualTo("material_shortage");
        assertThat(view.asOf()).isEqualTo("2026-10-04");
        assertThat(view.bandCounts().keySet())
                .containsExactlyElementsOf(MaterialShortageViews.RISK_BANDS);
        assertThat(view.basis().keySet()).containsExactlyInAnyOrder(
                "granularity", "unit", "statuses", "demand_source", "supply_source",
                "row_order", "risk_band", "truth_source");
        assertThat(view.rows()).isEmpty();
        assertThat(view.count()).isZero();
        assertThat(view.truncated()).isFalse();
    }

    @Test
    @DisplayName("history_depth：达标 ⟺ 跨度与有效周数**都** ≥ 8；不达标 ⇒ sufficient=false + 具名理由")
    void historyDepthGating() {
        HistoryDepth real = MaterialShortageService.historyDepth(LocalDate.of(2026, 9, 20),
                LocalDate.of(2026, 10, 3), 3);
        assertThat(real.weeks()).isEqualTo(2);
        assertThat(real.activeWeeks()).isEqualTo(3);
        assertThat(real.requiredWeeks()).isEqualTo(8);
        assertThat(real.sufficient()).isFalse();
        assertThat(real.reason()).contains("禁止硬算").contains("禁止回填 0");

        // 达标形态必须**真的**能达标（否则「默认不启用」会退化成「永远不启用」）
        HistoryDepth enough = MaterialShortageService.historyDepth(LocalDate.of(2026, 1, 1),
                LocalDate.of(2026, 3, 1), 9);
        assertThat(enough.weeks()).isGreaterThanOrEqualTo(8);
        assertThat(enough.sufficient()).isTrue();
        assertThat(enough.reason()).isNull();

        // 零行 ⇒ 0 周 + 不达标（未知不许被读成达标）
        assertThat(MaterialShortageService.historyDepth(null, null, 0).sufficient()).isFalse();
        assertThat(MaterialShortageService.historyDepth(null, null, 0).weeks()).isZero();
    }

    // ── 纪律 3：确定性 + 入参 fail-closed ───────────────────────────────────────

    // 「本类不读挂钟」**不在这里自建一份源码扫描**：`src/main` 侧的挂钟读取点由既有全仓守卫
    // `com.migao.admin.time.BusinessClockSourceGuardTest#onlyTheClockComponentReadsBusinessTimeFromMain`
    // 统一判（面 = 整个 `src/main/java`，比单文件扫描更强）—— 这里再写一份就是**平行实现**
    // （判据漂移 + 本文件的 needle 字面量会被那套守卫的族级普查判成「新命中」，实测两侧同时红）。
    // 本类的确定性由「纯函数 compute(...) 不碰 DB / 不读挂钟」的用例本身承担。

    @Test
    @DisplayName("🔴 取数 SQL 的权威口径：需求按 products.unit 过滤（不是订单行 selling_method）；供给**不读** products.stock")
    void sqlUsesAuthoritativeSources() {
        String demand = MaterialShortageService.DEMAND_SQL;
        assertThat(demand).contains("SUM(oi.quantity)").contains("JOIN products")
                .contains("o.status IN (%s)").contains("p.unit = ?");
        // 单位真值在商品档案 —— 订单行的 selling_method 一个字都不许进需求口径
        assertThat(demand).doesNotContain("selling_method");

        String supply = MaterialShortageService.SUPPLY_SQL;
        assertThat(supply).contains("SUM(sk.stock)").contains("product_skus").contains("GROUP BY sk.product_id");
        assertThat(supply).as("货品档案的 stock 是派生冗余列（实测与 SKU 合计差 3.3%%）")
                .doesNotContain("p.stock");
        // product_skus 没有 deleted 列（实测 DDL）⇒ 不得照抄别的表的软删写法
        assertThat(supply).doesNotContain("sk.deleted");
        assertThat(UNIT_SQL_IS_PRESENT).isTrue();
        assertThat(MaterialShortageService.UNIT_SQL).contains("unit");
    }

    /** 自证：UNIT_SQL 常量确实存在（防止上面那条断言被静默改成空断言）。 */
    private static final boolean UNIT_SQL_IS_PRESENT = MaterialShortageService.UNIT_SQL.contains("products");

    @Test
    @DisplayName("🔴 limit 非法（0 / 负数 / 非整数）⇒ 400 显式拒绝，且**不触达 DB**")
    void invalidLimitIsRejectedBeforeAnyQuery() {
        MaterialShortageService service = new MaterialShortageService(provider(jdbc), businessClock());
        for (String bad : List.of("0", "-1", "-50", "abc", "1.5")) {
            assertThatThrownBy(() -> service.shortage("confirmed,producing", bad, "2026-10-04"))
                    .as("limit=%s", bad)
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("≥ 1")
                    .extracting(e -> ((BusinessException) e).getHttpStatus())
                    .isEqualTo(400);
        }
        verify(jdbc, never()).query(contains("order_items"), any(org.springframework.jdbc.core.RowMapper.class),
                any(Object[].class));
        assertThat(MaterialShortageService.parseLimit(null))
                .isEqualTo(MaterialShortageService.DEFAULT_LIMIT);
        assertThat(MaterialShortageService.parseLimit(" 7 ")).isEqualTo(7);
    }

    @Test
    @DisplayName("🔴 未知订单状态 ⇒ 400（不静默忽略 —— 静默会让判据悄悄变松）；缺省 = confirmed,producing")
    void unknownStatusIsRejected() {
        assertThat(MaterialShortageService.parseStatuses(null))
                .containsExactly("confirmed", "producing");
        assertThat(MaterialShortageService.parseStatuses(""))
                .isEqualTo(MaterialShortageService.DEFAULT_STATUSES);
        assertThat(MaterialShortageService.parseStatuses(" confirmed , producing "))
                .containsExactly("confirmed", "producing");
        assertThatThrownBy(() -> MaterialShortageService.parseStatuses("confirmed,wat"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("wat")
                .extracting(e -> ((BusinessException) e).getHttpStatus())
                .isEqualTo(400);
    }

    @Test
    @DisplayName("租户原样回显（不由行数据反推）+ 候选面 = 有需求或有供给（无供给也成行）")
    void tenantEchoedAndSupplyAbsentIsStillARow() {
        MaterialShortageView view = build(50,
                List.of(demand("p1", "只有需求", "10.0", 1, 1)),
                List.of(),
                List.of(unit("p1", "只有需求", "米")),
                List.of());
        assertThat(view.tenantId()).isEqualTo(1L);
        assertThat(view.rows()).hasSize(1);
        // 供给缺失 = 0（**不是**「读不出」——SKU 表里没有该商品的 SKU 就是真没有库存）
        assertThat(view.rows().get(0).stockMeters()).isEqualByComparingTo("0");
        assertThat(view.rows().get(0).gapMeters()).isEqualByComparingTo("10.0");
    }

    private static BusinessClock businessClock() {
        return new BusinessClock(Clock.fixed(Instant.parse("2026-10-04T00:00:00Z"), ZoneOffset.UTC));
    }

    /** 把 mock JdbcTemplate 包成 ObjectProvider（生产代码用它做「无 DataSource 上下文」降级）。 */
    private static ObjectProvider<JdbcTemplate> provider(JdbcTemplate jdbc) {
        return new ObjectProvider<>() {
            @Override
            public JdbcTemplate getObject() {
                return jdbc;
            }

            @Override
            public JdbcTemplate getObject(Object... args) {
                return jdbc;
            }

            @Override
            public JdbcTemplate getIfAvailable() {
                return jdbc;
            }

            @Override
            public JdbcTemplate getIfUnique() {
                return jdbc;
            }
        };
    }

    @Test
    @DisplayName("as_of 缺省取业务「今天」（Asia/Shanghai，注入时钟钉住），显式传入则原样使用")
    void asOfComesFromBusinessClockOrCaller() {
        MaterialShortageService service = new MaterialShortageService(provider(jdbc), businessClock());
        assertThat(service.parseAsOf(null)).isEqualTo(LocalDate.of(2026, 10, 4));
        assertThat(service.parseAsOf("2026-01-02")).isEqualTo(LocalDate.of(2026, 1, 2));
        assertThatThrownBy(() -> service.parseAsOf("2026/01/02"))
                .isInstanceOf(BusinessException.class)
                .extracting(e -> ((BusinessException) e).getHttpStatus())
                .isEqualTo(400);
    }

    /** 判据只读性自证：本测试不写任何库（无写面调用）。 */
    @Test
    @DisplayName("只读：服务类不含任何写面 SQL（INSERT / UPDATE / DELETE / MERGE）")
    void serviceIsReadOnly() throws IOException {
        Path path = Path.of(SERVICE_REL);
        if (!Files.exists(path)) {
            path = Path.of("src/main/java/com/migao/admin/service/MaterialShortageService.java");
        }
        String upper = Files.readString(path, StandardCharsets.UTF_8).toUpperCase(java.util.Locale.ROOT);
        for (String needle : List.of("INSERT INTO", "UPDATE ", "DELETE FROM", "MERGE INTO")) {
            assertThat(upper).as("只读视图不得出现写面：%s", needle).doesNotContain(needle);
        }
    }

    /** 空 JDBC 桩（证明计算层不需要 DB —— 上面所有判据都走这条）。 */
    @Test
    @DisplayName("计算层与 DB 解耦：空取数面 ⇒ 空视图（不是异常、不是空指针）")
    void emptyInputsProduceEmptyView() {
        JdbcTemplate unused = mock(JdbcTemplate.class);
        assertThat(unused).isNotNull();
        MaterialShortageView view = build(50, List.of(), List.of(), List.of(), List.of());
        assertThat(view.rowsTotal()).isZero();
        assertThat(view.rows()).isEmpty();
        assertThat(view.nonComparable()).isEqualTo(new com.migao.admin.dto.MaterialShortageViews.NonComparable(0, 0));
    }
}
