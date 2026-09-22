package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 期初建账（批次建账/初始化入口）的**逐行校验报告**（issue #5153）。
 *
 * <p><b>语义 = 全或无</b>：只要有 1 行不通过，就**一行都不写**（不建单、不动库存），
 * 报告里逐行说明「第几行为什么不通过」。为什么不做部分成功（同族先例
 * {@code ProductService.importProducts} 是部分成功）：库存是资金级数据，部分成功会让
 * 「修好剩下的 2 行再用**同一次导入标识**重跑」变成一次**重复建账**（前 3 行会被再加一遍）
 * —— 因为幂等键的粒度是**整次导入运行**，不是行。全或无 + 幂等键 ⇒ 重跑恒安全。</p>
 *
 * <p>{@link #created} 区分「本次真的建了账」与「幂等命中（这次运行早已建过）」——
 * 两者都是成功，但对账的人必须看得出差别（前者动了库存，后者一个字都没动）。</p>
 */
@Data
public class OpeningImportReport {

    /** 本次导入的运行标识（= 建单幂等键，V117 的 {@code uk_inbound_orders_tenant_import_run}） */
    private String importRunId;

    /** 建成的期初入库单（未建账时为空） */
    private String inboundNo;

    private String orderId;

    /** 单据状态：{@code posted}（已建账）/ {@code draft}（只建了草稿）；未建账时为空 */
    private String status;

    /** 本次是否**真的建了账**（false = 幂等命中这次运行的既有单据，库存未被再次加） */
    private boolean created;

    /** 文件里的数据行数（不含表头） */
    private int total;

    private int okCount;

    private int failCount;

    /** 一句话结论（可直接展示给用户） */
    private String message;

    private List<Row> rows;

    public OpeningImportReport() {
    }

    public OpeningImportReport(String importRunId, List<Row> rows) {
        this.importRunId = importRunId;
        this.rows = rows;
        this.total = rows == null ? 0 : rows.size();
        this.okCount = rows == null ? 0
                : (int) rows.stream().filter(Row::isOk).count();
        this.failCount = this.total - this.okCount;
    }

    /** 一行 = 文件里的一行（行号用 Excel 的 1 基行号，与用户眼睛看到的一致） */
    @Data
    public static class Row {

        /** Excel 行号（1 基，**含表头**：表头是第 1 行 ⇒ 第 1 条数据是第 2 行） */
        private int rowNo;

        private String skuCode;

        private String productId;

        private Long skuId;

        /** 剩余米数（登记值；口径 = **登记时点的实物剩余量**，不是旧系统原始入库量） */
        private BigDecimal quantity;

        /** 供应商缸号（外部事实，可空） */
        private String dyeLot;

        /** 旧系统批次号（外部事实，可空；只在期初建账时可填） */
        private String legacyBatchNo;

        private BigDecimal unitCost;

        /** 本行是否通过校验 */
        private boolean ok;

        /** 不通过时的原因（可行动文案；通过时为空） */
        private String message;

        public void fail(String reason) {
            this.ok = false;
            this.message = reason;
        }
    }
}
