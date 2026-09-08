package com.migao.admin.controller;

// case_ids: API-020

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.KnowledgeDistillService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * KnowledgeDistillController 测试（LLM WIKI 板块 P5b，issue #3051 — 会话提炼触发端点）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDistillController 会话提炼端点测试")
class KnowledgeDistillControllerTest {

    private MockMvc mockMvc;

    @Mock
    private KnowledgeDistillService knowledgeDistillService;

    @InjectMocks
    private KnowledgeDistillController knowledgeDistillController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeDistillController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("POST /distill/conversations 触发提炼，返回统计")
    void distillConversations_success() throws Exception {
        when(knowledgeDistillService.distillConversations(eq(1L), eq(24)))
                .thenReturn(Map.of("sessions", 3, "candidates", 5, "created", 4, "skipped", 1));

        mockMvc.perform(post("/api/admin/knowledge/distill/conversations").param("hours", "24"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.sessions").value(3))
                .andExpect(jsonPath("$.data.created").value(4))
                .andExpect(jsonPath("$.data.skipped").value(1));
    }
}
