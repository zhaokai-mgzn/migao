package com.migao.admin.controller;
// case_ids: ST-004, ST-005

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.NotificationTemplateDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationTemplateRequest;
import com.migao.admin.service.NotificationTemplateService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * NotificationTemplateController 单元测试 — 模板管理端点（issue #2965）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("NotificationTemplateController 模板管理测试")
class NotificationTemplateControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private NotificationTemplateService templateService;

    @InjectMocks
    private NotificationTemplateController templateController;

    private static final String BASE = "/api/admin/notification-templates";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(templateController);
    }

    @Override
    @AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("GET 模板列表 — 200")
    void listTemplates() throws Exception {
        NotificationTemplateDTO dto = new NotificationTemplateDTO();
        dto.setId("tpl-1");
        dto.setName("新订单通知");
        dto.setTenantId(TEST_TENANT_ID);

        when(templateService.queryTemplates(eq(1L), eq(20L), eq(TEST_TENANT_ID)))
                .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(dto)));

        mockMvc.perform(get(BASE + "?page=1&size=20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].name").value("新订单通知"));

        verify(templateService).queryTemplates(1L, 20L, TEST_TENANT_ID);
    }

    @Test
    @DisplayName("POST 创建模板 — 200")
    void createTemplate() throws Exception {
        NotificationTemplateDTO dto = new NotificationTemplateDTO();
        dto.setId("tpl-new");
        dto.setName("新订单通知");

        when(templateService.createTemplate(eq(TEST_TENANT_ID), any(SaveNotificationTemplateRequest.class)))
                .thenReturn(dto);

        String body = new ObjectMapper().writeValueAsString(
                java.util.Map.of("name", "新订单通知", "channel", "internal", "templateContent", "内容"));

        mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("tpl-new"));

        verify(templateService).createTemplate(eq(TEST_TENANT_ID), any(SaveNotificationTemplateRequest.class));
    }

    @Test
    @DisplayName("PUT 更新模板 — 200")
    void updateTemplate() throws Exception {
        NotificationTemplateDTO dto = new NotificationTemplateDTO();
        dto.setId("tpl-1");
        dto.setName("改名后");

        when(templateService.updateTemplate(eq(TEST_TENANT_ID), eq("tpl-1"), any(SaveNotificationTemplateRequest.class)))
                .thenReturn(dto);

        String body = new ObjectMapper().writeValueAsString(
                java.util.Map.of("name", "改名后", "channel", "internal", "templateContent", "内容"));

        mockMvc.perform(put(BASE + "/tpl-1").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("改名后"));

        verify(templateService).updateTemplate(eq(TEST_TENANT_ID), eq("tpl-1"), any(SaveNotificationTemplateRequest.class));
    }

    @Test
    @DisplayName("DELETE 删除模板 — 200")
    void deleteTemplate() throws Exception {
        mockMvc.perform(delete(BASE + "/tpl-1"))
                .andExpect(status().isOk());

        verify(templateService).deleteTemplate(TEST_TENANT_ID, "tpl-1");
    }
}