package com.aikf.admin.config;

import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.exception.BusinessException;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.AuthenticationCredentialsNotFoundException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.NoHandlerFoundException;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 全局异常处理器
 * 统一处理各类异常，返回标准 ApiResponse 格式
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /**
     * 处理业务异常
     */
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiResponse<Void>> handleBusinessException(BusinessException e) {
        log.warn("业务异常: [{}] {}", e.getCode(), e.getMessage());
        ApiResponse<Void> response = ApiResponse.error(e.getCode(), e.getMessage());
        return ResponseEntity.status(e.getHttpStatus()).body(response);
    }

    /**
     * 处理参数校验异常（@Valid 注解）
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleValidationException(MethodArgumentNotValidException e) {
        List<ApiResponse.ErrorDetail> details = e.getBindingResult().getFieldErrors().stream()
                .map(this::mapFieldError)
                .collect(Collectors.toList());

        String message = details.stream()
                .map(ApiResponse.ErrorDetail::getMessage)
                .collect(Collectors.joining(", "));

        log.warn("参数校验失败: {}", message);
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", "参数校验失败", details);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理约束校验异常（@Validated 注解）
     */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolationException(ConstraintViolationException e) {
        List<ApiResponse.ErrorDetail> details = e.getConstraintViolations().stream()
                .map(this::mapConstraintViolation)
                .collect(Collectors.toList());

        String message = details.stream()
                .map(ApiResponse.ErrorDetail::getMessage)
                .collect(Collectors.joining(", "));

        log.warn("约束校验失败: {}", message);
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", "参数校验失败", details);
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理认证异常
     */
    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<ApiResponse<Void>> handleAuthenticationException(AuthenticationException e) {
        log.warn("认证失败: {}", e.getMessage());
        String code = "AUTH_REQUIRED";
        String message = "认证失败";

        if (e instanceof BadCredentialsException) {
            message = "用户名或密码错误";
        } else if (e instanceof AuthenticationCredentialsNotFoundException) {
            message = "未提供认证信息";
        }

        ApiResponse<Void> response = ApiResponse.error(code, message);
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(response);
    }

    /**
     * 处理访问拒绝异常
     */
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ApiResponse<Void>> handleAccessDeniedException(AccessDeniedException e) {
        log.warn("权限不足: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("PERMISSION_DENIED", "权限不足");
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(response);
    }

    /**
     * 处理非法参数异常
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiResponse<Void>> handleIllegalArgumentException(IllegalArgumentException e) {
        log.warn("非法参数: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("VALIDATION_ERROR", e.getMessage());
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(response);
    }

    /**
     * 处理非法状态异常
     */
    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<ApiResponse<Void>> handleIllegalStateException(IllegalStateException e) {
        log.warn("非法状态: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("ILLEGAL_STATE", e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理 405 —— 请求方法不被支持
     */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        log.warn("请求方法不被支持: {} (supported: {})", e.getMethod(), e.getSupportedHttpMethods());
        ApiResponse<Void> response = ApiResponse.error("METHOD_NOT_ALLOWED", "Method not allowed: " + e.getMethod());
        return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED).body(response);
    }

    /**
     * 处理 404 —— 请求的端点不存在
     */
    @ExceptionHandler(NoHandlerFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNoHandlerFound(NoHandlerFoundException e) {
        log.warn("请求的资源不存在: {} {}", e.getHttpMethod(), e.getRequestURL());
        ApiResponse<Void> response = ApiResponse.error("NOT_FOUND", "请求的资源不存在: " + e.getRequestURL());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(response);
    }

    /**
     * 处理请求体格式错误或缺失（JSON 解析失败、空 body、缺少 Content-Type 等）
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResponse<Void>> handleMessageNotReadable(HttpMessageNotReadableException e) {
        log.warn("请求体格式错误: {}", e.getMessage());
        ApiResponse<Void> response = ApiResponse.error("BAD_REQUEST", "请求体格式错误或缺失");
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(response);
    }

    /**
     * 处理不支持的 Content-Type
     */
    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMediaTypeNotSupported(HttpMediaTypeNotSupportedException e) {
        log.warn("不支持的 Content-Type: {}", e.getContentType());
        ApiResponse<Void> response = ApiResponse.error("UNSUPPORTED_MEDIA_TYPE",
                "不支持的 Content-Type: " + e.getContentType());
        return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE).body(response);
    }

    /**
     * 处理所有其他异常
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleException(Exception e) {
        log.error("系统异常: {}", e.getMessage(), e);
        ApiResponse<Void> response = ApiResponse.error("INTERNAL_ERROR", "服务器内部错误");
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(response);
    }

    // ========== 辅助方法 ==========

    private ApiResponse.ErrorDetail mapFieldError(FieldError error) {
        return new ApiResponse.ErrorDetail(error.getField(), error.getDefaultMessage());
    }

    private ApiResponse.ErrorDetail mapConstraintViolation(ConstraintViolation<?> violation) {
        String field = violation.getPropertyPath().toString();
        return new ApiResponse.ErrorDetail(field, violation.getMessage());
    }
}
