package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * 统一 API 响应信封
 * 所有接口返回统一格式，包含 success、data、error、requestId 字段
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ApiResponse<T> {

    /**
     * 请求是否成功
     */
    private boolean success;

    /**
     * 响应数据（成功时返回）
     */
    private T data;

    /**
     * 错误信息（失败时返回）
     */
    private ErrorInfo error;

    /**
     * 请求追踪 ID
     */
    private String requestId;

    /**
     * 时间戳
     */
    private Long timestamp;

    /**
     * LLM 友好的修复建议（Agent 端点使用）。
     * 当 success=false 时，告诉 LLM 如何引导用户修复问题。
     */
    private String suggestion;

    /**
     * 非阻塞警告列表（Agent 端点使用）。
     * 例如：["加工项'打孔'已存在，已跳过"]
     */
    @JsonInclude(JsonInclude.Include.NON_EMPTY)
    private List<String> warnings;

    /**
     * 私有构造方法，使用工厂方法创建实例
     */
    private ApiResponse() {
        this.requestId = generateRequestId();
        this.timestamp = Instant.now().getEpochSecond();
    }

    /**
     * 生成请求 ID
     */
    private static String generateRequestId() {
        return "req_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }

    /**
     * 创建成功响应
     *
     * @param data 响应数据
     * @param <T>  数据类型
     * @return ApiResponse
     */
    public static <T> ApiResponse<T> success(T data) {
        ApiResponse<T> response = new ApiResponse<>();
        response.setSuccess(true);
        response.setData(data);
        return response;
    }

    /**
     * 创建成功响应（无数据）
     *
     * @param <T> 数据类型
     * @return ApiResponse
     */
    public static <T> ApiResponse<T> success() {
        return success(null);
    }

    /**
     * 创建错误响应
     *
     * @param code    错误码
     * @param message 错误消息
     * @param details 错误详情
     * @param <T>     数据类型
     * @return ApiResponse
     */
    public static <T> ApiResponse<T> error(String code, String message, List<ErrorDetail> details) {
        ApiResponse<T> response = new ApiResponse<>();
        response.setSuccess(false);
        response.setError(new ErrorInfo(code, message, details));
        return response;
    }

    /**
     * 创建错误响应（无详情）
     *
     * @param code    错误码
     * @param message 错误消息
     * @param <T>     数据类型
     * @return ApiResponse
     */
    public static <T> ApiResponse<T> error(String code, String message) {
        return error(code, message, null);
    }

    /**
     * 创建含 suggestion 的错误响应（Agent 端点使用）
     */
    public static <T> ApiResponse<T> errorWithSuggestion(String code, String message, String suggestion) {
        ApiResponse<T> r = error(code, message, (List<ErrorDetail>) null);
        r.setSuggestion(suggestion);
        return r;
    }

    /**
     * 创建成功响应（含 warnings，Agent 端点使用）
     */
    public static <T> ApiResponse<T> success(T data, List<String> warnings) {
        ApiResponse<T> r = success(data);
        r.setWarnings(warnings);
        return r;
    }

    /**
     * 错误信息内部类
     */
    @Data
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ErrorInfo {
        private String code;
        private String message;
        private List<ErrorDetail> details;

        public ErrorInfo(String code, String message, List<ErrorDetail> details) {
            this.code = code;
            this.message = message;
            this.details = details;
        }
    }

    /**
     * 错误详情内部类
     */
    @Data
    public static class ErrorDetail {
        private String field;
        private String message;

        public ErrorDetail(String field, String message) {
            this.field = field;
            this.message = message;
        }

        public ErrorDetail(String message) {
            this.message = message;
        }
    }
}
