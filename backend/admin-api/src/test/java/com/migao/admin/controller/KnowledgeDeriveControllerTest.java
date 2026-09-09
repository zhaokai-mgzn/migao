package com.migao.admin.controller;

// case_ids: API-023

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.KnowledgeDeriveService;
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
 * KnowledgeDeriveController 测试（P2-1 对账端点，issue #3051）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDeriveController 派生对账端点测试")
class KnowledgeDeriveControllerTest {

    private MockMvc mockMvc;

    @Mock
    private KnowledgeDeriveService knowledgeDeriveService;

    @InjectMocks
    private KnowledgeDeriveController knowledgeDeriveController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeDeriveController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("POST /derive/rebuild 触发存量对账（商品派生已移除，仅加工项），返回统计")
    void rebuild_success() throws Exception {
        when(knowledgeDeriveService.deriveAll(eq(1L)))
                .thenReturn(Map.of("processingItems", 6));

        mockMvc.perform(post("/api/admin/knowledge/derive/rebuild"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.processingItems").value(6))
                .andExpect(jsonPath("$.data.products").doesNotExist());
    }
}
