package com.aikf.admin.dto;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 商品导入结果 DTO
 */
@Data
public class ProductImportResult {

    private int total;
    private int successCount;
    private int failCount;
    private List<ErrorDetail> errors;

    public ProductImportResult() {
        this.total = 0;
        this.successCount = 0;
        this.failCount = 0;
        this.errors = new ArrayList<>();
    }

    public static ProductImportResult create() {
        return new ProductImportResult();
    }

    public void addSuccess() {
        this.successCount++;
    }

    public void addError(int row, String message) {
        this.failCount++;
        this.errors.add(new ErrorDetail(row, message));
    }

    @Data
    public static class ErrorDetail {
        private int row;
        private String message;

        public ErrorDetail(int row, String message) {
            this.row = row;
            this.message = message;
        }
    }
}
