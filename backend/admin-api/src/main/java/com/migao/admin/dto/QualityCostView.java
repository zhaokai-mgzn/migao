package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 质量成本报表（issue #7377，P1-5 段 1）。
 *
 * <p>🔴 三项**分列**（返工工时 / 报废料 / 赔付），每项自带 `known` 与口径说明；
 * 合计只累加已知项，`complete=false` 时列出未知分项 —— 绝不把未知折成 0。</p>
 */
@Data
@Builder
public class QualityCostView {

    private String startDate;

    private String endDate;

    /** 三项分项（顺序固定，便于人读与日志对齐）。 */
    private List<Component> components;

    /** 合计（只累加已知项；全未知 ⇒ null）。 */
    private BigDecimal total;

    /** 三项是否全部已知（false ⇒ 合计是「可算的那部分」，页面必须标注）。 */
    private boolean complete;

    /** 未知分项的 code 列表。 */
    private List<String> unknownComponents;

    @Data
    @Builder
    public static class Component {

        private String code;

        private String label;

        /** 金额；未知 ⇒ null（不是 0）。 */
        private BigDecimal amount;

        private boolean known;

        /** 口径与未知原因的说明（上屏）。 */
        private String note;

        /** 未定价条目数（`> 0` 且 known=false 时用于提示「有几条没定价」）。 */
        private int unknownItems;
    }
}
