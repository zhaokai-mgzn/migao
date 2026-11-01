// case_ids: MIG-007

package com.migao.admin.controller;

import com.migao.admin.dto.CustomerImportAnalysis;
import com.migao.admin.dto.CustomerImportReport;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CustomerImportService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 客户导入 HTTP 契约（issue #8295）：三个端点 + customer:create 权限。
 */
@ExtendWith(MockitoExtension.class)
class CustomerImportControllerTest {

    @Mock
    private CustomerImportService customerImportService;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(
                new CustomerImportController(customerImportService)).build();
    }

    @Test
    void analyzeReturnsHeadersAndSuggestions() throws Exception {
        when(customerImportService.analyze(any())).thenReturn(CustomerImportAnalysis.builder()
                .headers(List.of("客户编号", "客户名称"))
                .samples(List.of(List.of("C001", "张三布行")))
                .totalRows(1)
                .suggestions(List.of())
                .fields(List.of())
                .aiDegraded(false)
                .aiMessage("")
                .build());

        mockMvc.perform(multipart("/api/admin/customers/import/analyze").file(file()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.headers[0]").value("客户编号"))
                .andExpect(jsonPath("$.data.totalRows").value(1));
        verify(customerImportService).analyze(any());
    }

    @Test
    void previewPassesMappingAndUpdateExisting() throws Exception {
        when(customerImportService.preview(any(), anyString(), anyBoolean()))
                .thenReturn(report("preview"));
        String mapping = "{\"externalId\":0,\"displayName\":1}";

        mockMvc.perform(multipart("/api/admin/customers/import/preview")
                        .file(file())
                        .param("mapping", mapping)
                        .param("updateExisting", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.mode").value("preview"))
                .andExpect(jsonPath("$.data.newCount").value(1));
        verify(customerImportService).preview(any(), eq(mapping), eq(true));
    }

    @Test
    void commitPassesMappingAndUpdateExisting() throws Exception {
        when(customerImportService.commit(any(), anyString(), anyBoolean()))
                .thenReturn(report("commit"));
        String mapping = "{\"externalId\":0,\"displayName\":1}";

        mockMvc.perform(multipart("/api/admin/customers/import/commit")
                        .file(file())
                        .param("mapping", mapping)
                        .param("updateExisting", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.mode").value("commit"))
                .andExpect(jsonPath("$.data.createdCount").value(1));
        verify(customerImportService).commit(any(), eq(mapping), eq(false));
    }

    @Test
    void allEndpointsRequireCustomerCreate() throws Exception {
        assertThat(CustomerImportController.class
                .getMethod("analyze", MultipartFile.class)
                .getAnnotation(RequirePermission.class).value())
                .isEqualTo("customer:create");
        assertThat(CustomerImportController.class
                .getMethod("preview", MultipartFile.class, String.class, boolean.class)
                .getAnnotation(RequirePermission.class).value())
                .isEqualTo("customer:create");
        assertThat(CustomerImportController.class
                .getMethod("commit", MultipartFile.class, String.class, boolean.class)
                .getAnnotation(RequirePermission.class).value())
                .isEqualTo("customer:create");
    }

    private static MockMultipartFile file() {
        return new MockMultipartFile("file", "customers.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", new byte[]{1, 2, 3});
    }

    private static CustomerImportReport report(String mode) {
        return CustomerImportReport.builder()
                .mode(mode)
                .total(1)
                .newCount("preview".equals(mode) ? 1 : 0)
                .createdCount("commit".equals(mode) ? 1 : 0)
                .rows(List.of(CustomerImportReport.Row.builder()
                        .rowNo(1).externalId("C001").displayName("张三布行")
                        .action("preview".equals(mode) ? "NEW" : "CREATED").build()))
                .build();
    }
}
