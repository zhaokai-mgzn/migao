package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;

/**
 * 裁剪智能排料 v1 —— <b>A 类「完整布并排」</b>的纯函数（issue #5142）。
 *
 * <h2>模型（统一，不分模式）</h2>
 * 每块料 = 一个矩形 <b>(占门幅宽 {@link Piece#doorSpanMeters()}, 沿卷长 {@link Piece#meters()})</b>：
 * <ul>
 *   <li><b>定高买宽</b>（{@link #MODE_FIXED_HEIGHT}）：一块 = 整窗
 *       ⇒ {@code 占门幅宽 = 窗高 + 卷边}、{@code 沿卷长 = 窗宽 × 褶倍}</li>
 *   <li><b>定宽买高</b>（{@link #MODE_FIXED_WIDTH}）：一块 = <b>每一幅</b>
 *       ⇒ {@code 占门幅宽 = 该幅宽}（等宽拼幅下 {@code = 窗宽 × 褶倍 ÷ 幅数}）、
 *       {@code 沿卷长 = 窗高 + 卷边（+ 对花花距）}</li>
 * </ul>
 * 装箱规则：同一行内 {@code Σ 占门幅宽 ≤ door_width}，<b>该行的长度 = max(该行各块的沿卷长)</b>；
 * 目标 = 最小化 {@code Σ 行长度}。同窗的多块可以分散在不同行（本来就如此），
 * 但<b>每块必须完整、不旋转、不重切</b>。
 *
 * <h2>两个模式各有一个受益场景（各有独立判据）</h2>
 * <ul>
 *   <li><b>定高买宽</b>：若干扇矮窗并排 —— 两扇 1.5m 宽 × 2 倍褶 × 窗高 1.1m（各领 3m）、
 *       门幅 2.8m、卷边 0.3m ⇒ 各占 1.4m（合计 2.8m ✓）⇒ 并排后<b>领 3m 而不是 6m</b>。</li>
 *   <li><b>定宽买高</b>：<b>P=1 的窄窗互补</b> —— 两扇单开窄窗（各 {@code 窗宽 × 褶倍 = 1.4m}、
 *       窗高 1.1m）、门幅 2.8m、卷边 0.3m ⇒ 各 1 幅、各占 1.4m（合计 2.8m ✓）、
 *       沿卷长各 1.4m ⇒ 并排后<b>1 行 / 领 1.4m</b>，而逐窗分开裁 = 2 行 / 2.8m。</li>
 * </ul>
 *
 * <h2>边界（本类有意不做的事，别在这里加）</h2>
 * <ul>
 *   <li><b>不算用料口径</b>：占门幅宽 / 沿卷长都是<b>入参</b>（真值源 = 算料引擎
 *       {@code backend/ai-agent-service/app/tools/curtain_calc.py} 的 {@code calculate_fabric_meters}）
 *       —— 本类只做<b>装箱/排版</b>，不重算「幅数 / 窗宽 × 褶倍 / 窗高 + 卷边」。
 *       重算 = 在本仓造出第二份会漂移的算料口径。</li>
 *   <li><b>不硬编码任何余量/门幅</b>：{@code doorWidth} 与 {@code hemMargin} 一律<b>调方传入</b>；
 *       {@code hemMargin} 只用于把「料排不下门幅」这件事报出来，<b>不</b>参与任何尺寸推导
 *       （占门幅宽已由调方给定，本类不替它算卷边）。</li>
 *   <li><b>不做 B 类</b>：不打破同窗等宽拼幅、不改加工类型、不混门幅、不旋转、不重切。
 *       未知/空的加工类型<b>照常按占门幅宽装箱</b>（物理可行即并排，不猜工艺）。</li>
 *   <li><b>不涉余料</b>：余料零价值（用户裁定），不做余料库存/复用，也不为利用余宽折损成品。</li>
 *   <li><b>算法是确定性启发式</b>（沿卷长降序 + 首次适配），不是最优解 —— 最小化
 *       {@code Σ 行长度} 的装箱面是 NP-hard，本单<b>不引入优化器依赖</b>，只保证确定性、
 *       顺序无关与「不倒退」。</li>
 *   <li><b>没有生产调用方</b>：池子（哪些料放一起排）由调用方决定，接线另开单。</li>
 * </ul>
 *
 * <h2>为什么不会<b>少</b>算（比不省料更严重）</h2>
 * 行内 {@code Σ 占门幅宽 ≤ door_width}（本类显式校验并 fail-closed）+ 行长度 = 行内<b>最大</b>沿卷长
 * ⇒ 任意一行里的每一块都拿得到「不小于自己所需」的卷长，且各自占的那段门幅互不重叠
 * ⇒ 领料量对每一块都足额（只多不少）。少算的唯一形态是「两块排进了同一行但门幅放不下」，
 * 已被上述校验挡住。
 */
public final class CuttingPlanCalculator {

    /**
     * 加工类型：<b>定高买宽</b> —— 一块 = 整窗，占门幅宽 = 窗高 + 卷边。
     */
    public static final String MODE_FIXED_HEIGHT = "fixed_height";

    /**
     * 加工类型：<b>定宽买高</b> —— 一块 = 每一幅，占门幅宽 = 该幅宽。
     */
    public static final String MODE_FIXED_WIDTH = "fixed_width";

    /**
     * 尺寸比较容差（米）—— 只用于「能否并排」这一处<b>判定</b>，不用于领料量计算。
     *
     * <p>病根（本仓已实证的同族形态）：{@code 1.1 + 0.3 + 1.1 + 0.3} 在 IEEE 754 下
     * {@code = 2.8000000000000003 > 2.8} ⇒ <b>恰好铺满门幅的合法并排被判「排不下」</b>
     * （少省料，且判定随取值漂移）。1e-6 米 = 1 微米，远小于任何业务分辨率（宽高按厘米报），
     * 故不会把物理上排不下的料误判为排得下。
     */
    private static final BigDecimal OVERFLOW_EPSILON = new BigDecimal("0.000001");

    /**
     * 利用率保留位数。领料量本身<b>不</b>取整（下游按 1 位小数落库存，见 #5063）。
     */
    private static final int UTILIZATION_SCALE = 4;

    private CuttingPlanCalculator() {
    }

    /**
     * 排料。
     *
     * @param pieces    待裁料（占门幅宽 / 沿卷长由算料引擎定尺，本方法<b>照用不重算</b>）
     * @param doorWidth 门幅（米，&gt; 0）—— 同批料必须同门幅（不混门幅）
     * @param hemMargin 上下卷边合计（米，≥ 0）—— <b>调方传入</b>，本类不持有该口径
     *                  （真值源 {@code docs/curtain-fabric-quote-rules.md} §0 的 {@code HEM_MARGIN}）
     * @return 排料方案：{@code rows[].pieces} + {@code rows[].length} + 应领米数 + 利用率
     * @throws IllegalArgumentException 入参缺失/非正数/非有限，或某块排不下门幅
     *                                  （fail-closed：宁可算不出来，也不产出一份切不出货的方案）
     */
    public static CuttingPlan plan(List<Piece> pieces, double doorWidth, double hemMargin) {
        if (pieces == null) {
            throw new IllegalArgumentException("pieces 不得为 null");
        }
        requireFinite(doorWidth, "doorWidth");
        requireFinite(hemMargin, "hemMargin");
        if (doorWidth <= 0) {
            throw new IllegalArgumentException("doorWidth 必须为正数（实际 " + doorWidth + "）");
        }
        if (hemMargin < 0) {
            throw new IllegalArgumentException("hemMargin 不得为负数（实际 " + hemMargin + "）");
        }
        for (Piece piece : pieces) {
            requirePiece(piece);
            requireFitsDoor(piece, doorWidth);
        }

        // 规范序：沿卷长降序、再占门幅宽降序、再 piece_id 升序
        // ⇒ ① 结果**与入参顺序无关**；② 长的先摆 ⇒ 「同长的凑一行」优先，
        //    这正是本目标（Σ 行长度）下最有判别力的启发式。
        List<Piece> ordered = new ArrayList<>(pieces);
        ordered.sort((a, b) -> {
            int byMeters = Double.compare(b.meters(), a.meters());
            if (byMeters != 0) {
                return byMeters;
            }
            int bySpan = Double.compare(b.doorSpanMeters(), a.doorSpanMeters());
            return bySpan != 0 ? bySpan : a.pieceId().compareTo(b.pieceId());
        });

        BigDecimal maxRowSpan = BigDecimal.valueOf(doorWidth).add(OVERFLOW_EPSILON);
        List<List<Piece>> rowPieces = new ArrayList<>();
        List<BigDecimal> rowSpans = new ArrayList<>();
        for (Piece piece : ordered) {
            BigDecimal span = BigDecimal.valueOf(piece.doorSpanMeters());
            int target = -1;
            for (int i = 0; i < rowPieces.size(); i++) {
                if (rowSpans.get(i).add(span).compareTo(maxRowSpan) <= 0) {
                    target = i;
                    break;
                }
            }
            if (target < 0) {
                rowPieces.add(new ArrayList<>(List.of(piece)));
                rowSpans.add(span);
            } else {
                rowPieces.get(target).add(piece);
                rowSpans.set(target, rowSpans.get(target).add(span));
            }
        }

        List<Row> rows = new ArrayList<>();
        BigDecimal issued = BigDecimal.ZERO;
        BigDecimal piecesArea = BigDecimal.ZERO;
        for (List<Piece> group : rowPieces) {
            rows.add(new Row(List.copyOf(group), maxMeters(group)));
            issued = issued.add(rows.get(rows.size() - 1).length());
        }
        for (Piece piece : pieces) {
            piecesArea = piecesArea.add(BigDecimal.valueOf(piece.doorSpanMeters())
                    .multiply(BigDecimal.valueOf(piece.meters())));
        }
        return new CuttingPlan(List.copyOf(rows), issued, utilization(piecesArea, issued, doorWidth));
    }

    /** 行长度 = 行内<b>最大</b>沿卷长（行内每块都拿它作领料长度 ⇒ 只领一次、谁都不缺）。 */
    private static BigDecimal maxMeters(List<Piece> group) {
        BigDecimal length = BigDecimal.ZERO;
        for (Piece piece : group) {
            BigDecimal meters = BigDecimal.valueOf(piece.meters());
            if (meters.compareTo(length) > 0) {
                length = meters;
            }
        }
        return length;
    }

    /**
     * 利用率 = <b>已被料占掉的布面积（Σ 占门幅宽 × 沿卷长）÷ 已领布面积（门幅 × 应领米数）</b>。
     *
     * <p>该口径恒 ≤ 1，而余料（零价值）即差额：两块正好铺满一行时 = 1，两块矮窗并排时
     * 已领的那一段里有一半是空的（差额就是要找机会填的缝）。<b>不</b>取「按成品尺寸算」
     * 的口径 —— 领料发生在裁剪之前，分母只能是已领的布。
     */
    private static BigDecimal utilization(BigDecimal piecesArea, BigDecimal issued, double doorWidth) {
        BigDecimal issuedArea = issued.multiply(BigDecimal.valueOf(doorWidth));
        if (issuedArea.signum() == 0) {
            return BigDecimal.ZERO;
        }
        return piecesArea.divide(issuedArea, UTILIZATION_SCALE, RoundingMode.HALF_UP);
    }

    /**
     * 一块料<b>比门幅还宽</b> ⇒ 不是「不省料」，是「切不出货」⇒ fail-closed 报错，
     * 不让它静默变成一行「排不下的料」。
     */
    private static void requireFitsDoor(Piece piece, double doorWidth) {
        BigDecimal overflow = BigDecimal.valueOf(piece.doorSpanMeters())
                .subtract(BigDecimal.valueOf(doorWidth));
        if (overflow.compareTo(OVERFLOW_EPSILON) > 0) {
            throw new IllegalArgumentException("piece[" + piece.pieceId() + "].doorSpanMeters = "
                    + piece.doorSpanMeters() + " 超过门幅 " + doorWidth
                    + " ⇒ 这块料切不出来");
        }
    }

    private static void requireFinite(double value, String name) {
        if (!Double.isFinite(value)) {
            throw new IllegalArgumentException(name + " 必须是有限数（实际 " + value + "）");
        }
    }

    private static void requirePiece(Piece piece) {
        if (piece == null) {
            throw new IllegalArgumentException("pieces 不得含 null 元素");
        }
        if (piece.pieceId() == null || piece.pieceId().isBlank()) {
            throw new IllegalArgumentException("piece.pieceId 不得为空");
        }
        requirePositive(piece.doorSpanMeters(), "doorSpanMeters", piece.pieceId());
        requirePositive(piece.meters(), "meters", piece.pieceId());
    }

    private static void requirePositive(double value, String field, String pieceId) {
        if (!Double.isFinite(value) || value <= 0) {
            throw new IllegalArgumentException(
                    "piece[" + pieceId + "]." + field + " 必须为正数（实际 " + value + "）");
        }
    }

    /**
     * 一块待裁料 —— <b>就是那个矩形</b>（定尺输入，单位米）。尺寸由调方从算料引擎的产物换算，
     * 本类不推导、不重算。
     *
     * @param pieceId         料的稳定标识（同一批内唯一；等长/等宽料的排序键，决定排料结果的确定性）
     * @param cuttingMode     加工类型（{@link #MODE_FIXED_HEIGHT} / {@link #MODE_FIXED_WIDTH}；
     *                        未知或 null 照常装箱 —— 装箱只看两条边长，不猜工艺）
     * @param doorSpanMeters  这块料<b>占门幅多宽</b>（米）：定高买宽 = {@code 窗高 + 卷边}；
     *                        定宽买高 = {@code 该幅宽}（等宽拼幅下 {@code = 窗宽 × 褶倍 ÷ 幅数}）。
     *                        这是唯一会被推导的尺寸，而它<b>由调方给定</b>（卷边口径不在本类内）
     * @param meters          这块料<b>沿卷长方向的长度</b>（米）= 卷上要裁下来的那一段有多长：
     *                        定高买宽 = {@code 窗宽 × 褶倍}（即算料引擎给的该块用料米数）；
     *                        定宽买高 = {@code 窗高 + 卷边（+ 对花花距）} = 每幅的幅长。
     *                        本类照用不重算，只用于「行长度 = 行内最大沿卷长」
     */
    public record Piece(String pieceId, String cuttingMode, double doorSpanMeters, double meters) {
    }

    /**
     * 一行下料：{@code pieces} 共同占用门幅上的同一段长度（{@code length}）。
     *
     * <p>不变式（{@link #plan} 保证）：① 行内 {@code Σ piece.doorSpanMeters() ≤ doorWidth}；
     * ② {@code length = max(行内 piece.meters())}；③ {@code pieces} 里的每块都是<b>原样</b>的入参记录
     * （未被切开、未被旋转、未被改写）。
     */
    public record Row(List<Piece> pieces, BigDecimal length) {
    }

    /**
     * 排料方案。
     *
     * @param rows         下料行（顺序 = 规范序，与入参顺序无关）
     * @param issuedMeters 应领米数 = {@code Σ rows[].length}（<b>不取整</b>：下游按 1 位小数落库存）
     * @param utilization  利用率（料面积 ÷ 已领布面积，保留 {@value #UTILIZATION_SCALE} 位）
     */
    public record CuttingPlan(List<Row> rows, BigDecimal issuedMeters, BigDecimal utilization) {
    }
}
