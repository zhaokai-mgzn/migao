// case_ids: PR-059
//
// 批量导入的 **HTTP 入口**（issue #5154）。判据 1 的红证就在本文件：
// 改前 `ProductController` **只有** `@GetMapping("/export")` ⇒ 本文件的 multipart 请求
// 在 standalone MockMvc 上得到 **404**（`No mapping for POST /api/admin/products/import`）——
// 即「导出侧是完整四件套、导入侧零入口」的形态判据。
package com.migao.admin.controller;

import com.migao.admin.dto.ProductImportResult;
import com.migao.admin.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

import jakarta.servlet.http.HttpServletResponse;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 「导入」对「导出」的对偶入口（#5154）：
 * <ul>
 *   <li>{@code GET  /api/admin/products/export}（既有）↔ {@code GET /api/admin/products/import-template}</li>
 *   <li>（无）↔ {@code POST /api/admin/products/import}</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductController 批量导入端点（#5154）")
class ProductImportControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/products";
    private static final String XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

    private MockMvc mockMvc;

    @Mock
    private ProductService productService;

    @InjectMocks
    private ProductController controller;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(controller);
    }

    private static ProductImportResult report() {
        ProductImportResult r = ProductImportResult.create();
        r.setTotal(3);
        r.setSuccessCount(2);
        r.setBlankRows(0);
        r.setCreatedProducts(1);
        r.setUpdatedProducts(0);
        r.addError(3, "MH-001",
                "第 3 行库存 最多支持 1 位小数（库存按 0.1 米粒度记账），当前值 2.755 有 3 位小数");
        return r;
    }

    @Test
    @DisplayName("判据1：POST /api/admin/products/import ⇒ 有入口、租户取自上下文、逐行报告原样返回")
    void importEndpointExposesRowLevelReport() throws Exception {
        when(productService.importProducts(any(), eq(TEST_TENANT_ID))).thenReturn(report());
        MockMultipartFile file = new MockMultipartFile("file", "商品导入.xlsx", XLSX, "x".getBytes());

        mockMvc.perform(multipart(BASE + "/import").file(file))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(3))
                .andExpect(jsonPath("$.data.successCount").value(2))
                .andExpect(jsonPath("$.data.failCount").value(1))
                .andExpect(jsonPath("$.data.blankRows").value(0))
                .andExpect(jsonPath("$.data.createdProducts").value(1))
                .andExpect(jsonPath("$.data.updatedProducts").value(0))
                // 可定位：行号 + 货号 + 可行动原因，三者都要出现在响应里（前端才能逐行展示）
                .andExpect(jsonPath("$.data.errors[0].row").value(3))
                .andExpect(jsonPath("$.data.errors[0].skuCode").value("MH-001"))
                .andExpect(jsonPath("$.data.errors[0].message").value(
                        org.hamcrest.Matchers.containsString("1 位小数")));

        // 租户隔离：tenantId **只**来自 TenantContext，不接受客户端传入
        verify(productService).importProducts(any(), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("判据1（对偶）：GET /api/admin/products/import-template ⇒ 有入口且下载 xlsx")
    void importTemplateEndpointDownloadsXlsx() throws Exception {
        doAnswer(inv -> {
            HttpServletResponse response = inv.getArgument(0);
            response.setContentType(XLSX);
            response.setHeader("Content-Disposition", "attachment; filename=template.xlsx");
            response.getOutputStream().write(new byte[]{'P', 'K', 3, 4});
            return null;
        }).when(productService).generateImportTemplate(any());

        mockMvc.perform(get(BASE + "/import-template"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(XLSX))
                .andExpect(result -> org.assertj.core.api.Assertions
                        .assertThat(result.getResponse().getContentAsByteArray()).isNotEmpty());
    }

    @Test
    @DisplayName("判据1（边界）：文件为空 ⇒ 走 GlobalExceptionHandler 的 422（VALIDATION_ERROR），而不是 500")
    void emptyFileIsRejectedAsUnprocessable() throws Exception {
        when(productService.importProducts(any(), any()))
                .thenThrow(com.migao.admin.exception.BusinessException.validationError("Excel文件为空"));

        mockMvc.perform(multipart(BASE + "/import")
                        .file(new MockMultipartFile("file", "empty.xlsx", XLSX, new byte[0])))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.message").value("Excel文件为空"));
    }

    @Test
    @DisplayName("判据1：导出端点仍在（导入不得挤掉既有对偶面）")
    void exportEndpointStillMapped() throws Exception {
        mockMvc.perform(get(BASE + "/export"))
                .andExpect(status().isOk());
        verify(productService).exportProducts(any(), eq(TEST_TENANT_ID), any());
    }

}
