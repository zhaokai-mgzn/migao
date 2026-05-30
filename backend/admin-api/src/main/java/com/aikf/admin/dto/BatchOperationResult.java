package com.aikf.admin.dto;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 批量操作结果 DTO
 */
@Data
public class BatchOperationResult {

    private int success;
    private int failed;
    private List<ErrorDetail> errors;

    public BatchOperationResult() {
        this.success = 0;
        this.failed = 0;
        this.errors = new ArrayList<>();
    }

    public static BatchOperationResult create() {
        return new BatchOperationResult();
    }

    public void addSuccess() {
        this.success++;
    }

    public void addError(String id, String message) {
        this.failed++;
        this.errors.add(new ErrorDetail(id, message));
    }

    @Data
    public static class ErrorDetail {
        private String id;
        private String message;

        public ErrorDetail(String id, String message) {
            this.id = id;
            this.message = message;
        }
    }
}
