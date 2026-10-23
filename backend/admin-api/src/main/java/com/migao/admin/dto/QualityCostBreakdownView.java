package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.util.List;

/**
 * 质量成本的**维度汇总**（issue #7377 段 5，P1-5）：把三项成本按「客户」或「工序」摊开。
 *
 * <h3>为什么要有它</h3>
 * <p>整表只回答「这个月质量成本多少」，回答不了「贵在哪」 —— 是某个客户总在返工，还是某道工序总出错。
 * 这决定处置方向（挑客户 / 改工艺），所以必须按维度摊开。</p>
 *
 * <h3>🔴 恒等式：{@code 整表合计 == Σ行 + 未归属}</h3>
 * <p>维度摊开最容易犯的错是**悄悄丢数**：关联不上的行直接不出现，于是「各行之和」比整表小，
 * 而每一行单看都正常。所以本视图强制带 {@link Unattributed}：<b>归属不了的金额必须露出来</b>，
 * 并写明为什么归属不了。判据 = {@code QualityCostBreakdownTest#totalsEqualRowsPlusUnattributed}。</p>
 *
 * <h3>各维度的可归因性（照实写在 {@link #notes}）</h3>
 * <ul>
 *   <li><b>客户</b>：返工走「报工 → 加工单 → 订单 → 客户」；赔付走「退款流水 → 订单 → 客户」。
 *       任一环缺失 ⇒ 进未归属。</li>
 *   <li><b>工序</b>：返工直接取报工行的工序名；**赔付流水没有工序信息** ⇒ 工序维度下赔付整体进未归属
 *       （不是「赔付为 0」）。</li>
 * </ul>
 *
 * <p>⚠️ 报废料不进本视图：它在本仓**未采集**（整表已标未知），摊到任何维度都是编数。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QualityCostBreakdownView {

    /** 维度：`customer` / `process`（其它值 ⇒ 服务端 400，不是静默返回空）。 */
    private String dimension;

    /** 口径自述（前端直接展示，不另写一份）。 */
    private String scope;

    private String startDate;

    private String endDate;

    /** 有没有任何可展示的读数（行或未归属金额）。false ⇒ 页面写「暂无数据」，不画 ¥0.00。 */
    private boolean hasData;

    /** 按维度分行（金额倒序）。 */
    private List<Row> rows;

    /** 合计：{@code == Σ行 + 未归属}（每一项各自成立）。{@code hasData=false} 时为 null。 */
    private Totals totals;

    /** 归属不了的金额（必须露出来，不许静默丢弃）。 */
    private Unattributed unattributed;

    /** 已知但**不计金额**的读数（如未定价返工行数）与维度说明。 */
    private List<String> notes;

    /** 维度的一行。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Row {
        /** 稳定键（客户名 / 手机号；工序名）—— 前端用它做 key，不用下标。 */
        private String key;
        private String label;
        /** 返工工时金额（已定价那部分）。 */
        private BigDecimal rework;
        /** 该行命中的返工报工行数（金额可能是 0 但有行 ⇒ 不是「没有返工」）。 */
        private int reworkLines;
        /** 赔付（退款口径）金额。 */
        private BigDecimal compensation;
        /** 该行命中的退款流水条数。 */
        private int compensationCount;
        /** 合计 = rework + compensation。 */
        private BigDecimal total;
    }

    /** 合计（与行的口径同一套）。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Totals {
        private BigDecimal rework;
        private int reworkLines;
        private BigDecimal compensation;
        private int compensationCount;
        private BigDecimal total;
    }

    /** 归属不了的金额 + 原因。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Unattributed {
        private BigDecimal rework;
        private int reworkLines;
        private BigDecimal compensation;
        private int compensationCount;
        private BigDecimal total;
        /** 为什么归属不了（前端原样展示）。 */
        private String reason;
    }
}
