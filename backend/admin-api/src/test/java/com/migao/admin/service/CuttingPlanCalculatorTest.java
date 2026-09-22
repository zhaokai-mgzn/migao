// case_ids: PG-059
package com.migao.admin.service;

import com.migao.admin.service.CuttingPlanCalculator.CuttingPlan;
import com.migao.admin.service.CuttingPlanCalculator.Piece;
import com.migao.admin.service.CuttingPlanCalculator.Row;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 裁剪智能排料 v1 —— A 类「完整布并排」的判据（issue #5142）。
 *
 * <p>被测对象 = 纯函数 {@link CuttingPlanCalculator#plan}（无 IO、无 Spring）。判据全部是
 * <b>逐值/结构断言</b>（不是「非空/存在性」）。
 *
 * <h2>算例口径（真值源 = 算料引擎，本测试不复算引擎公式）</h2>
 * 定高买宽的一块 = 整窗 ⇒ {@code 占门幅宽 = 窗高 + 卷边}、{@code 沿卷长 = 窗宽 × 褶倍}；
 * 定宽买高的一块 = 每一幅 ⇒ {@code 占门幅宽 = 该幅宽}、{@code 沿卷长 = 窗高 + 卷边}。
 * 卷边一律<b>由本测试作为入参给出</b>（本测试从不断言引擎里那个常量的数值）。
 *
 * <h2>逐条判据的红证（每条都写清了「什么变异会让它红」）</h2>
 * <ul>
 *   <li>{@link #fixedHeightTallWindowsPairIntoOneRow()}：若排料把两块同时占门幅宽的料排进同一行
 *       （或反过来拒绝对 {@code Σspan ≤ 门幅} 的两块并排）⇒ 绿变红。</li>
 *   <li>{@link #fixedWidthSinglePanelNarrowWindowsPairIntoOneRow()}：这条专门钉
 *       <b>定宽买高 P=1 的窄窗互补</b>。若把定宽料按「整窗宽」占门幅（而不是按幅宽）、
 *       或让定宽料不走装箱（旧「定宽买高原样返回」口径）⇒ 红。</li>
 *   <li>{@link #piecesThatDoNotFitTogetherKeepTheirOwnRows()}：把行内 {@code Σspan ≤ 门幅}
 *       的守卫放宽（例如换成「只看高度」）⇒ 红（会合出一行放不下的料 = 切不出货）。</li>
 *   <li>{@link #resultIsIndependentOfInputOrder()}：把排序键换成「入参顺序」
 *       （例如去掉 comparator 或改成 {@code (a,b) -> 0}）⇒ 红。</li>
 *   <li>{@link #randomizedInvariantsHold()}：任何一条不变式被破坏（行超门幅 / 行长度不等于行内最大
 *       沿卷长 / 料被改写或重切 / 顺序相关）⇒ 红。</li>
 *   <li>{@link #invalidInputsAreRejected()}：把任一入参校验删掉 ⇒ 红（少算 = 切不出货，
 *       宁可算不出来）。</li>
 * </ul>
 */
class CuttingPlanCalculatorTest {

    /** 门幅 2.8m（门幅本身由调方传入，不是本类持有的口径）。 */
    private static final double DOOR_WIDTH = 2.8;

    /** 上下卷边合计 0.3m —— <b>入参</b>（真值源：quote-rules §0 的 HEM_MARGIN；本测试不写它进实现）。 */
    private static final double HEM_MARGIN = 0.3;

    /** 逐窗分开裁（不并排）的口径 = 各块用料之和。 */
    private static BigDecimal perPieceMeters(List<Piece> pieces) {
        BigDecimal total = BigDecimal.ZERO;
        for (Piece piece : pieces) {
            total = total.add(BigDecimal.valueOf(piece.meters()));
        }
        return total;
    }

    private static void assertInRowOrder(Row row, String... expectedPieceIds) {
        List<String> actual = new ArrayList<>();
        for (Piece piece : row.pieces()) {
            actual.add(piece.pieceId());
        }
        assertEquals(List.of(expectedPieceIds), actual,
                "行内料的构成/顺序不符（行长度 " + row.length() + "）");
    }

    /**
     * 逐行复核**全部**不变式（断言面**独立**于被测实现算一遍，不拿被测自己的 `length()` 当真相）：
     * ① 行内 {@code Σ 占门幅宽 ≤ 门幅}；② {@code row.length() == 行内最大沿卷长}；
     * ③ 行内每块都是**原样的入参记录**。返回行长度以便调用方累加。
     */
    private static BigDecimal assertRowInvariants(Row row, List<Piece> input, double doorWidth,
                                                  String context) {
        BigDecimal spanSum = BigDecimal.ZERO;
        BigDecimal maxMeters = BigDecimal.ZERO;
        for (Piece piece : row.pieces()) {
            spanSum = spanSum.add(BigDecimal.valueOf(piece.doorSpanMeters()));
            if (BigDecimal.valueOf(piece.meters()).compareTo(maxMeters) > 0) {
                maxMeters = BigDecimal.valueOf(piece.meters());
            }
            assertTrue(input.contains(piece), context + "：输出的料必须是**原样**的入参记录"
                    + "（未被重切/改写）：" + piece);
        }
        assertTrue(spanSum.compareTo(BigDecimal.valueOf(doorWidth)) <= 0,
                context + "：行内 Σ占门幅宽 " + spanSum + " 超过门幅 ⇒ 这行切不出货（完整布不变式）");
        assertEquals(0, row.length().compareTo(maxMeters),
                context + "：行长度必须 == 行内最大沿卷长（实际 " + row.length()
                        + " / 应为 " + maxMeters + "）");
        return row.length();
    }

    @Test
    @DisplayName("定高买宽：两扇矮窗并排 ⇒ 1 行 / 领 3m（逐窗 = 6m），且料一字未改")
    void fixedHeightTallWindowsPairIntoOneRow() {
        // 两扇 1.5m 宽 × 2 倍褶 × 窗高 1.1m ⇒ 各领 3m；各占门幅 1.1 + 0.3 = 1.4m（合计 2.8 = 门幅 ✓）
        Piece a = new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3.0);
        Piece b = new Piece("B", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3.0);
        List<Piece> pieces = List.of(a, b);

        CuttingPlan plan = CuttingPlanCalculator.plan(pieces, DOOR_WIDTH, HEM_MARGIN);

        assertEquals(1, plan.rows().size(), "两块占门幅 1.4 + 1.4 = 2.8 = 门幅 ⇒ 必须并排成一行");
        assertEquals(0, plan.issuedMeters().compareTo(new BigDecimal("3.0")),
                "并排后应领 = max(3.0, 3.0) = 3.0（实际 " + plan.issuedMeters() + "）");
        assertEquals(0, perPieceMeters(pieces).compareTo(new BigDecimal("6.0")),
                "逐窗分开裁的对照口径 = 6.0 ⇒ 差额 3.0 即本单省下的米数");
        assertTrue(plan.issuedMeters().compareTo(perPieceMeters(pieces)) < 0,
                "并排必须**省**（issued < 逐窗口径）");
        Row row = plan.rows().get(0);
        assertInRowOrder(row, "A", "B");
        assertEquals(0, row.length().compareTo(new BigDecimal("3.0")), "行长度 = 行内最大沿卷长");
        assertEquals(a, row.pieces().get(0), "料必须原样（未被切开/旋转/改写）");
        assertEquals(b, row.pieces().get(1), "料必须原样（未被切开/旋转/改写）");
    }

    @Test
    @DisplayName("定宽买高：P=1 窄窗互补 ⇒ 1 行 / 领 1.4m（逐窗 = 2.8m）")
    void fixedWidthSinglePanelNarrowWindowsPairIntoOneRow() {
        // 两扇单开窄窗：各 窗宽 × 褶倍 = 1.4m ⇒ 各 1 幅、占门幅 1.4m（合计 2.8 = 门幅 ✓）；
        // 各幅沿卷长 = 窗高 1.1 + 卷边 0.3 = 1.4m
        Piece c = new Piece("C", CuttingPlanCalculator.MODE_FIXED_WIDTH, 1.4, 1.4);
        Piece d = new Piece("D", CuttingPlanCalculator.MODE_FIXED_WIDTH, 1.4, 1.4);
        List<Piece> pieces = List.of(c, d);

        CuttingPlan plan = CuttingPlanCalculator.plan(pieces, DOOR_WIDTH, HEM_MARGIN);

        assertEquals(1, plan.rows().size(), "两块各占 1.4m 幅宽 ⇒ 必须并排成一行（P=1 窄窗互补）");
        assertEquals(0, plan.issuedMeters().compareTo(new BigDecimal("1.4")),
                "并排后应领 = 1 段 1.4m（实际 " + plan.issuedMeters() + "）");
        assertEquals(0, perPieceMeters(pieces).compareTo(new BigDecimal("2.8")),
                "逐窗分开裁 = 2 行 / 2.8m ⇒ 差额 1.4m 即本单省下的整行");
        Row row = plan.rows().get(0);
        assertInRowOrder(row, "C", "D");
        assertEquals(0, row.length().compareTo(new BigDecimal("1.4")), "行长度 = 行内最大沿卷长");
        assertEquals(c, row.pieces().get(0), "料必须原样（未被切开/旋转/改写）");
    }

    @Test
    @DisplayName("不倒退：Σ占门幅宽 > 门幅 ⇒ 各占一行，应领米数与逐窗口径逐值相同")
    void piecesThatDoNotFitTogetherKeepTheirOwnRows() {
        // 两块各占 1.7m（合计 3.4 > 2.8）⇒ 排不进同一行；沿卷长 3.0 vs 2.0
        Piece a = new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.7, 3.0);
        Piece b = new Piece("B", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.7, 2.0);
        List<Piece> pieces = List.of(a, b);

        CuttingPlan plan = CuttingPlanCalculator.plan(pieces, DOOR_WIDTH, HEM_MARGIN);

        assertEquals(2, plan.rows().size(), "1.7 + 1.7 = 3.4 > 2.8 ⇒ 必须各占一行");
        assertEquals(0, plan.issuedMeters().compareTo(perPieceMeters(pieces)),
                "排不下时**一格都不许少**（少算 = 切不出货，比不省料严重）：issued "
                        + plan.issuedMeters() + " 必须 == 逐窗口径 " + perPieceMeters(pieces));
        assertEquals(0, plan.issuedMeters().compareTo(new BigDecimal("5.0")), "逐值锚点 = 3.0 + 2.0");
        for (Row row : plan.rows()) {
            assertEquals(1, row.pieces().size(), "排不下的料必须单独成行（与现状零差异）");
        }
    }

    @Test
    @DisplayName("完整布不变式：行内 Σ占门幅宽 ≤ 门幅、行长度 = 行内最大沿卷长、料一字未改")
    void keepsWholePiecesUnmodifiedAndRowsWithinDoorWidth() {
        // ⚠️ 数据是**被红证逼出来的**：同一行里两块**不等长**，且行的正确长度 = 首块（5.0）而非次块（3.0）
        //    ⇒ 「行长度取成行内最后一块」这种缺陷会算成 3.0（少算）⇒ 本判据能红。
        //    （若两块等长，两种取法同值 ⇒ 该缺陷**照样全绿**，这正是第一版判据的漏洞。）
        List<Piece> pieces = List.of(
                new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.8, 5.0),
                new Piece("B", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.0, 3.0),
                new Piece("C", CuttingPlanCalculator.MODE_FIXED_WIDTH, 1.0, 2.0));

        CuttingPlan plan = CuttingPlanCalculator.plan(pieces, DOOR_WIDTH, HEM_MARGIN);

        assertEquals(2, plan.rows().size(), "行1 = A+B（1.8+1.0 = 2.8 ✓）、行2 = C（1.8+1.0 已满）");
        assertEquals(0, plan.issuedMeters().compareTo(new BigDecimal("7.0")),
                "5.0（行1 max(5.0, 3.0)）+ 2.0（行2）"
                        + "—— 若行长度取错（取到非最大那一块），这里立刻不等");
        List<Piece> seen = new ArrayList<>();
        BigDecimal issued = BigDecimal.ZERO;
        for (Row row : plan.rows()) {
            issued = issued.add(assertRowInvariants(row, pieces, DOOR_WIDTH, "完整布不变式"));
            seen.addAll(row.pieces());
        }
        assertEquals(0, plan.issuedMeters().compareTo(issued), "应领米数必须 == Σ 行长度");
        assertEquals(pieces.size(), seen.size(), "每块料恰好出现一次（不重切、不丢料）");
        for (Piece piece : pieces) {
            assertTrue(seen.contains(piece), "料 " + piece.pieceId() + " 未出现在任何输出行里");
        }
        assertInRowOrder(plan.rows().get(0), "A", "B");
        assertInRowOrder(plan.rows().get(1), "C");
    }

    @Test
    @DisplayName("顺序无关：同一组料换输入顺序 ⇒ 行数/行构成/行长度/应领米数逐值相同")
    void resultIsIndependentOfInputOrder() {
        // 五块料、门幅 2.8（每行最多 2 块，各占 1.2）：
        // 规范序（沿卷长降序）⇒ P1(3.0) P2(3.0) P3(1.0) P4(0.8) P5(0.4)
        // ⇒ 行 {P1,P2} 长 3.0、{P3,P4} 长 1.0、{P5} 长 0.4 ⇒ 应领 4.4
        // ⚠️ 数据是**挑过的**：换顺序后首次适配会把长料拆到不同行（逆序 ⇒ 3.0 + 5.0 = 8.0）
        //    ⇒ 这条判据对「排序键失效」真有判别力（不是等价的恒真断言）。
        Piece p1 = new Piece("P1", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.2, 3.0);
        Piece p2 = new Piece("P2", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.2, 3.0);
        Piece p3 = new Piece("P3", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.2, 1.0);
        Piece p4 = new Piece("P4", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.2, 0.8);
        Piece p5 = new Piece("P5", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.2, 0.4);
        List<Piece> pieces = List.of(p1, p2, p3, p4, p5);
        List<Piece> reversed = new ArrayList<>(pieces);
        Collections.reverse(reversed);
        List<Piece> shuffled = new ArrayList<>(List.of(p3, p1, p5, p2, p4));

        CuttingPlan plan = CuttingPlanCalculator.plan(pieces, DOOR_WIDTH, HEM_MARGIN);
        CuttingPlan reversedPlan = CuttingPlanCalculator.plan(reversed, DOOR_WIDTH, HEM_MARGIN);
        CuttingPlan shuffledPlan = CuttingPlanCalculator.plan(shuffled, DOOR_WIDTH, HEM_MARGIN);

        assertEquals(0, plan.issuedMeters().compareTo(new BigDecimal("4.4")),
                "规范序下的应领米数锚点 = 3.0 + 1.0 + 0.4");
        assertEquals(3, plan.rows().size(), "规范序下的行数锚点 = 3");
        assertEquals(reversedPlan.issuedMeters(), plan.issuedMeters(), "逆序后应领米数必须相同");
        assertEquals(shuffledPlan.issuedMeters(), plan.issuedMeters(), "乱序后应领米数必须相同");
        assertEquals(reversedPlan.rows().size(), plan.rows().size(), "行数必须相同");
        assertEquals(shuffledPlan.rows().size(), plan.rows().size(), "行数必须相同");
        for (int i = 0; i < plan.rows().size(); i++) {
            assertEquals(reversedPlan.rows().get(i).length(), plan.rows().get(i).length(),
                    "第 " + i + " 行的行长度必须相同");
            // 行**构成**也必须与输入顺序无关（不只是米数相同）
            assertEquals(reversedPlan.rows().get(i).pieces(), plan.rows().get(i).pieces(),
                    "第 " + i + " 行的料与顺序必须相同");
            assertEquals(shuffledPlan.rows().get(i).pieces(), plan.rows().get(i).pieces(),
                    "第 " + i + " 行的料与顺序必须相同");
        }
        assertInRowOrder(plan.rows().get(0), "P1", "P2");
        assertInRowOrder(plan.rows().get(1), "P3", "P4");
        assertInRowOrder(plan.rows().get(2), "P5");
    }

    @Test
    @DisplayName("反空跑：随机输入下四条不变式恒成立（含顺序无关）")
    void randomizedInvariantsHold() {
        Random random = new Random(5142L);
        for (int round = 0; round < 200; round++) {
            double doorWidth = 1.0 + random.nextDouble() * 3.0;
            double hemMargin = random.nextDouble() * 0.4;
            int count = 1 + random.nextInt(8);
            List<Piece> pieces = new ArrayList<>();
            for (int i = 0; i < count; i++) {
                // 占门幅宽 ≤ 门幅 − 卷边（超门幅属 fail-closed 的非法输入，另有判据）
                double span = 0.5 + random.nextDouble() * (doorWidth - 0.6);
                double meters = 0.3 + random.nextDouble() * 1.5;
                String mode = random.nextBoolean()
                        ? CuttingPlanCalculator.MODE_FIXED_HEIGHT
                        : CuttingPlanCalculator.MODE_FIXED_WIDTH;
                pieces.add(new Piece("R" + round + "-" + i, mode, span, meters));
            }

            CuttingPlan plan = CuttingPlanCalculator.plan(pieces, doorWidth, hemMargin);
            BigDecimal expected = BigDecimal.ZERO;
            BigDecimal seen = BigDecimal.ZERO;
            for (Row row : plan.rows()) {
                expected = expected.add(
                        assertRowInvariants(row, pieces, doorWidth, "第 " + round + " 轮"));
                seen = seen.add(BigDecimal.valueOf(row.pieces().size()));
            }
            assertEquals(0, plan.issuedMeters().compareTo(expected),
                    "第 " + round + " 轮应领米数 ≠ Σ 行长度");
            assertEquals(0, seen.compareTo(BigDecimal.valueOf(pieces.size())),
                    "第 " + round + " 轮有料被丢/被重切");
            assertTrue(plan.issuedMeters().compareTo(perPieceMeters(pieces)) <= 0,
                    "第 " + round + " 轮应领米数超过了逐窗口径（把料重复计数了）");

            // 换输入顺序 ⇒ 应领米数必须相同。⚠️ 用**打乱**而不是逆序：逆序后的升序恰好等于
            // 降序的规范序，会让「排序键失效」这种缺陷**假绿**（实测：第一版就是这么漏的）。
            List<Piece> shuffled = new ArrayList<>(pieces);
            Collections.shuffle(shuffled, new Random(round));
            assertEquals(CuttingPlanCalculator.plan(shuffled, doorWidth, hemMargin).issuedMeters(),
                    plan.issuedMeters(), "第 " + round + " 轮换输入顺序后应领米数变了");
        }
    }

    @Test
    @DisplayName("残缺/非法入参 fail-closed：宁可算不出来，也不产出切不出货的方案")
    void invalidInputsAreRejected() {
        List<Piece> ok = List.of(new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3.0));
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(null, DOOR_WIDTH, HEM_MARGIN), "pieces 为 null");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(ok, 0, HEM_MARGIN), "门幅为 0");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(ok, -1.0, HEM_MARGIN), "门幅为负");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(ok, Double.NaN, HEM_MARGIN), "门幅为 NaN");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(ok, DOOR_WIDTH, -0.1), "卷边为负");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(Collections.singletonList(null), DOOR_WIDTH, HEM_MARGIN),
                "含 null 元素");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(
                        List.of(new Piece("  ", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3.0)),
                        DOOR_WIDTH, HEM_MARGIN), "piece_id 为空");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(
                        List.of(new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 0, 3.0)),
                        DOOR_WIDTH, HEM_MARGIN), "占门幅宽为 0");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(
                        List.of(new Piece("A", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, -3.0)),
                        DOOR_WIDTH, HEM_MARGIN), "沿卷长为负");
        assertThrows(IllegalArgumentException.class,
                () -> CuttingPlanCalculator.plan(
                        List.of(new Piece("TOO-WIDE", CuttingPlanCalculator.MODE_FIXED_HEIGHT, 3.0, 3.0)),
                        DOOR_WIDTH, HEM_MARGIN), "一块料比门幅还宽 ⇒ 切不出货，必须报错而不是静默成行");
        CuttingPlan empty = CuttingPlanCalculator.plan(List.of(), DOOR_WIDTH, HEM_MARGIN);
        assertEquals(0, empty.issuedMeters().compareTo(BigDecimal.ZERO), "空池 ⇒ 应领 0");
        assertTrue(empty.rows().isEmpty(), "空池 ⇒ 0 行（不得凭空造一行）");
        assertEquals(0, empty.utilization().compareTo(BigDecimal.ZERO), "空池 ⇒ 利用率 0（不得除零/NaN）");
    }
}
