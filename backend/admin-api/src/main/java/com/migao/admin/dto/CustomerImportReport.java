package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 客户主数据迁移的逐行报告（issue #8295）。
 *
 * <p>preview 填 new/update/skip/error；commit 填 created/updated/skipped/failed。
 * 同一行在任何模式下都不会既算成功又算失败。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class CustomerImportReport {

    private String mode;

    private int total;

    private int newCount;

    private int updateCount;

    private int skipCount;

    private int errorCount;

    private int warnCount;

    private int createdCount;

    private int updatedCount;

    private int skippedCount;

    private int failedCount;

    private List<Row> rows;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Row {

        /** 数据行号（从 1 开始，不含表头）。 */
        private int rowNo;

        private String externalId;

        private String displayName;

        private String phone;

        /** NEW / UPDATE / SKIP / ERROR（preview）；CREATED / UPDATED / SKIPPED / FAILED（commit）。 */
        private String action;

        private String message;

        private String customerId;
    }
}
