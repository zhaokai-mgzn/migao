package com.migao.admin.dto;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import java.util.List;

class DtoTest {

    @Test
    void productImportResult_shouldInitializeWithZeros() {
        ProductImportResult r = new ProductImportResult();
        assertEquals(0, r.getTotal());
        assertEquals(0, r.getSuccessCount());
        assertEquals(0, r.getFailCount());
        assertNotNull(r.getErrors());
        assertTrue(r.getErrors().isEmpty());
    }

    @Test
    void productImportResult_create_shouldReturnNewInstance() {
        ProductImportResult r = ProductImportResult.create();
        assertNotNull(r);
        assertEquals(0, r.getSuccessCount());
    }

    @Test
    void productImportResult_addSuccess_shouldIncrement() {
        ProductImportResult r = new ProductImportResult();
        r.addSuccess(); r.addSuccess();
        assertEquals(2, r.getSuccessCount());
    }

    @Test
    void productImportResult_addError_shouldIncrementAndRecord() {
        ProductImportResult r = new ProductImportResult();
        r.addError(3, "invalid price");
        assertEquals(1, r.getFailCount());
        assertEquals(1, r.getErrors().size());
        assertEquals(3, r.getErrors().get(0).getRow());
    }

    @Test
    void batchOperationResult_createAndAdd() {
        BatchOperationResult r = BatchOperationResult.create();
        r.addSuccess();
        r.addError("p1", "error");
        assertEquals(1, r.getSuccess());
        assertEquals(1, r.getFailed());
        assertEquals("p1", r.getErrors().get(0).getId());
    }

    @Test
    void pageResponse_of_shouldCreate() {
        PageResponse<String> r = PageResponse.of(100L, 1L, 20L, List.of("a","b"));
        assertEquals(100L, r.getTotal());
        assertEquals(2, r.getItems().size());
    }

    @Test
    void pageResponse_defaults() {
        PageResponse<String> r = new PageResponse<>();
        assertNull(r.getTotal());
    }
}
