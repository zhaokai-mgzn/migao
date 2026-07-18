package com.migao.admin.exception;

import lombok.Getter;

/**
 * 业务异常类
 * 用于封装业务逻辑错误，包含错误码和错误消息
 */
@Getter
public class BusinessException extends RuntimeException {

    /**
     * 错误码
     */
    private final String code;

    /**
     * HTTP 状态码
     */
    private final int httpStatus;

    /**
     * LLM 友好的修复建议（Agent 端点使用）
     */
    @Getter
    private String suggestion;

    /**
     * 构造业务异常
     *
     * @param code       错误码
     * @param message    错误消息
     */
    public BusinessException(String code, String message) {
        super(message);
        this.code = code;
        this.httpStatus = 400;
    }

    /**
     * 构造业务异常（含 suggestion）
     */
    public BusinessException(String code, String message, int httpStatus) {
        super(message);
        this.code = code;
        this.httpStatus = httpStatus;
    }

    /**
     * 构造业务异常（含 suggestion + HTTP 状态码）
     */
    public BusinessException(String code, String message, int httpStatus, String suggestion) {
        super(message);
        this.code = code;
        this.httpStatus = httpStatus;
        this.suggestion = suggestion;
    }

    /**
     * 构造业务异常
     *
     * @param code       错误码
     * @param message    错误消息
     * @param cause      原始异常
     */
    public BusinessException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
        this.httpStatus = 400;
    }

    // ========== 预定义的业务异常工厂方法 ==========

    /**
     * 参数校验错误
     */
    public static BusinessException validationError(String message) {
        return new BusinessException("VALIDATION_ERROR", message, 422);
    }

    /**
     * 资源不存在
     */
    public static BusinessException notFound(String resource) {
        return new BusinessException("NOT_FOUND", resource + "不存在", 404);
    }

    /**
     * 认证失败
     */
    public static BusinessException authFailed(String message) {
        return new BusinessException("AUTH_FAILED", message, 401);
    }

    /**
     * 权限不足
     */
    public static BusinessException permissionDenied() {
        return new BusinessException("PERMISSION_DENIED", "权限不足", 403);
    }

    /**
     * 租户无效
     */
    public static BusinessException tenantInvalid() {
        return new BusinessException("TENANT_INVALID", "租户无效", 401);
    }
}
