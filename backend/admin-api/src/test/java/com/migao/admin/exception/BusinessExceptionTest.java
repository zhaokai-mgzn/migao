package com.migao.admin.exception;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BusinessExceptionTest {

    @Test
    void constructor_shouldSetCodeAndMessage() {
        BusinessException ex = new BusinessException("E001", "error message");
        assertEquals("E001", ex.getCode());
        assertEquals("error message", ex.getMessage());
        assertEquals(400, ex.getHttpStatus());
    }

    @Test
    void constructor_withHttpStatus() {
        BusinessException ex = new BusinessException("E002", "nf", 404);
        assertEquals(404, ex.getHttpStatus());
    }

    @Test
    void constructor_withCause() {
        RuntimeException cause = new RuntimeException("root");
        BusinessException ex = new BusinessException("E003", "w", cause);
        assertEquals(cause, ex.getCause());
        assertEquals(400, ex.getHttpStatus());
        assertEquals("w", ex.getMessage());
    }

    @Test
    void validationError_has422() {
        BusinessException ex = BusinessException.validationError("bad");
        assertEquals("VALIDATION_ERROR", ex.getCode());
        assertEquals(422, ex.getHttpStatus());
    }

    @Test
    void notFound_has404() {
        BusinessException ex = BusinessException.notFound("Product");
        assertEquals("NOT_FOUND", ex.getCode());
        assertEquals(404, ex.getHttpStatus());
        assertEquals("Product不存在", ex.getMessage());
    }

    @Test
    void authFailed_has401() {
        BusinessException ex = BusinessException.authFailed("bad token");
        assertEquals("AUTH_FAILED", ex.getCode());
        assertEquals(401, ex.getHttpStatus());
    }

    @Test
    void permissionDenied_has403() {
        BusinessException ex = BusinessException.permissionDenied();
        assertEquals("PERMISSION_DENIED", ex.getCode());
        assertEquals(403, ex.getHttpStatus());
        assertEquals("权限不足", ex.getMessage());
    }

    @Test
    void tenantInvalid_has401() {
        BusinessException ex = BusinessException.tenantInvalid();
        assertEquals("TENANT_INVALID", ex.getCode());
        assertEquals(401, ex.getHttpStatus());
        assertEquals("租户无效", ex.getMessage());
    }
}
