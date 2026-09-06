package com.migao.admin.controller;
// case_ids: ST-004, ST-005

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.SaveNotificationRuleRequest;
import com.migao.admin.service.NotificationRuleService;
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
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * NotificationRuleController 单元测试 — 规则管理端点（issue #2965）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("NotificationRuleController 规则管理测试")
class NotificationRuleControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private NotificationRuleService ruleService;

    @InjectMocks
    private NotificationRuleController ruleController;

    private static final String BASE = "/api/admin/notification-rules";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(ruleController);
    }

    @Override
    @AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("GET 规则列表 — 200")
    void listRules() throws Exception {
        NotificationRuleDTO dto = new NotificationRuleDTO();
        dto.setId("rule-1");
        dto.setEventType("order_created");
        dto.setTenantId(TEST_TENANT_ID);

        when(ruleService.queryRules(eq(1L), eq(20L), eq(TEST_TENANT_ID), isNull()))
                .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(dto)));

        mockMvc.perform(get(BASE + "?page=1&size=20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].eventType").value("order_created"));

        verify(ruleService).queryRules(1L, 20L, TEST_TENANT_ID, null);
    }

    @Test
    @DisplayName("POST 创建规则 — 200")
    void createRule() throws Exception {
        NotificationRuleDTO dto = new NotificationRuleDTO();
        dto.setId("rule-new");
        dto.setEventType("order_created");

        when(ruleService.createRule(eq(TEST_TENANT_ID), any(SaveNotificationRuleRequest.class)))
                .thenReturn(dto);

        String body = new ObjectMapper().writeValueAsString(
                java.util.Map.of("eventType", "order_created", "templateId", "tpl-1"));

        mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("rule-new"));

        verify(ruleService).createRule(eq(TEST_TENANT_ID), any(SaveNotificationRuleRequest.class));
    }

    @Test
    @DisplayName("PUT 更新规则 — 200")
    void updateRule() throws Exception {
        NotificationRuleDTO dto = new NotificationRuleDTO();
        dto.setId("rule-1");
        dto.setEventType("order_created");

        when(ruleService.updateRule(eq(TEST_TENANT_ID), eq("rule-1"), any(SaveNotificationRuleRequest.class)))
                .thenReturn(dto);

        String body = new ObjectMapper().writeValueAsString(
                java.util.Map.of("eventType", "order_created", "templateId", "tpl-1"));

        mockMvc.perform(put(BASE + "/rule-1").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.eventType").value("order_created"));

        verify(ruleService).updateRule(eq(TEST_TENANT_ID), eq("rule-1"), any(SaveNotificationRuleRequest.class));
    }

    @Test
    @DisplayName("DELETE 删除规则 — 200")
    void deleteRule() throws Exception {
        mockMvc.perform(delete(BASE + "/rule-1"))
                .andExpect(status().isOk());

        verify(ruleService).deleteRule(TEST_TENANT_ID, "rule-1");
    }
}