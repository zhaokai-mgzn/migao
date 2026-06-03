package com.aikf.admin.config;

import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.servlet.NoHandlerFoundException;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * GlobalExceptionHandler 单元测试
 */
class GlobalExceptionHandlerTest {

    private GlobalExceptionHandler handler;

    @BeforeEach
    void setUp() {
        handler = new GlobalExceptionHandler();
    }

    // ======================== BusinessException 处理测试 ========================

    @Test
    @DisplayName("处理 BusinessException - 认证失败(401)")
    void handleBusinessException_AuthFailed() {
        // Given
        BusinessException ex = BusinessException.authFailed("用户名或密码错误");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleBusinessException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().isSuccess()).isFalse();
        assertThat(response.getBody().getError().getCode()).isEqualTo("AUTH_FAILED");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("用户名或密码错误");
    }

    @Test
    @DisplayName("处理 BusinessException - 资源不存在(404)")
    void handleBusinessException_NotFound() {
        // Given
        BusinessException ex = BusinessException.notFound("商品");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleBusinessException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody().getError().getCode()).isEqualTo("NOT_FOUND");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("商品不存在");
    }

    @Test
    @DisplayName("处理 BusinessException - 参数校验错误(422)")
    void handleBusinessException_ValidationError() {
        // Given
        BusinessException ex = BusinessException.validationError("分类不存在");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleBusinessException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody().getError().getCode()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    @DisplayName("处理 BusinessException - 权限不足(403)")
    void handleBusinessException_PermissionDenied() {
        // Given
        BusinessException ex = BusinessException.permissionDenied();

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleBusinessException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertThat(response.getBody().getError().getCode()).isEqualTo("PERMISSION_DENIED");
    }

    // ======================== ValidationException 处理测试 ========================

    @Test
    @DisplayName("处理 MethodArgumentNotValidException - 参数校验失败")
    void handleValidationException() {
        // Given: 模拟参数校验错误
        BindingResult bindingResult = mock(BindingResult.class);
        FieldError fieldError1 = new FieldError("loginRequest", "username", "用户名不能为空");
        FieldError fieldError2 = new FieldError("loginRequest", "password", "密码不能为空");
        when(bindingResult.getFieldErrors()).thenReturn(List.of(fieldError1, fieldError2));

        MethodArgumentNotValidException ex = new MethodArgumentNotValidException(null, bindingResult);

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleValidationException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().isSuccess()).isFalse();
        assertThat(response.getBody().getError().getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(response.getBody().getError().getDetails()).hasSize(2);
    }

    // ======================== NoHandlerFoundException 处理测试 ========================

    @Test
    @DisplayName("处理 NoHandlerFoundException - 返回 404")
    void handleNoHandlerFound() {
        // Given
        NoHandlerFoundException ex = new NoHandlerFoundException("GET", "/api/nonexistent", null);

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleNoHandlerFound(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().getError().getCode()).isEqualTo("NOT_FOUND");
        assertThat(response.getBody().getError().getMessage()).contains("/api/nonexistent");
    }

    // ======================== 认证异常处理测试 ========================

    @Test
    @DisplayName("处理 AuthenticationException - BadCredentialsException")
    void handleAuthenticationException_BadCredentials() {
        // Given
        BadCredentialsException ex = new BadCredentialsException("凭据无效");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleAuthenticationException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(response.getBody().getError().getCode()).isEqualTo("AUTH_REQUIRED");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("用户名或密码错误");
    }

    // ======================== 访问拒绝异常测试 ========================

    @Test
    @DisplayName("处理 AccessDeniedException - 返回 403")
    void handleAccessDeniedException() {
        // Given
        AccessDeniedException ex = new AccessDeniedException("权限不足");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleAccessDeniedException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
        assertThat(response.getBody().getError().getCode()).isEqualTo("PERMISSION_DENIED");
    }

    // ======================== 请求体格式异常处理测试 ========================

    @Test
    @DisplayName("处理 HttpMessageNotReadableException - 请求体格式错误或缺失，返回 400")
    void handleMessageNotReadable() {
        // Given
        HttpMessageNotReadableException ex = new HttpMessageNotReadableException("JSON parse error");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleMessageNotReadable(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().isSuccess()).isFalse();
        assertThat(response.getBody().getError().getCode()).isEqualTo("BAD_REQUEST");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("请求体格式错误或缺失");
    }

    @Test
    @DisplayName("处理 HttpMediaTypeNotSupportedException - 不支持的 Content-Type，返回 415")
    void handleMediaTypeNotSupported() {
        // Given
        HttpMediaTypeNotSupportedException ex = new HttpMediaTypeNotSupportedException(
                MediaType.TEXT_PLAIN, List.of(MediaType.APPLICATION_JSON));

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleMediaTypeNotSupported(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().isSuccess()).isFalse();
        assertThat(response.getBody().getError().getCode()).isEqualTo("UNSUPPORTED_MEDIA_TYPE");
        assertThat(response.getBody().getError().getMessage()).contains("text/plain");
    }

    // ======================== 通用异常处理测试 ========================

    @Test
    @DisplayName("处理未知异常 - 返回 500")
    void handleException_InternalError() {
        // Given
        RuntimeException ex = new RuntimeException("未知错误");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody().getError().getCode()).isEqualTo("INTERNAL_ERROR");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("服务器内部错误");
    }

    @Test
    @DisplayName("处理 IllegalArgumentException - 返回 422")
    void handleIllegalArgumentException() {
        // Given
        IllegalArgumentException ex = new IllegalArgumentException("参数不合法");

        // When
        ResponseEntity<ApiResponse<Void>> response = handler.handleIllegalArgumentException(ex);

        // Then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody().getError().getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(response.getBody().getError().getMessage()).isEqualTo("参数不合法");
    }
}
