package com.migao.admin.exception;

import lombok.Getter;
import org.springframework.security.access.AccessDeniedException;

/**
 * 细粒度权限拒绝异常（issue #4105 F1）
 *
 * <p>{@code PermissionInterceptor} 校验 {@code @RequirePermission} 失败时抛出本异常，
 * 用**结构化字段**携带缺失的权限码，供 {@code GlobalExceptionHandler} 生成可执行的 403 响应
 * （{@code error.details[requiredPermission]} + LLM 友好的 {@code suggestion}）。
 * 专用子类型取代「让下游解析异常 message 字符串」——后者一旦措辞调整就静默失效。</p>
 */
@Getter
public class PermissionDeniedException extends AccessDeniedException {

    /**
     * 缺失的权限码（如 "product:manage"）
     */
    private final String requiredPermission;

    /**
     * @param message            错误消息（保持既有措辞「权限不足，需要权限: X」，供日志与响应 message 使用）
     * @param requiredPermission 缺失的权限码
     */
    public PermissionDeniedException(String message, String requiredPermission) {
        super(message);
        this.requiredPermission = requiredPermission;
    }
}