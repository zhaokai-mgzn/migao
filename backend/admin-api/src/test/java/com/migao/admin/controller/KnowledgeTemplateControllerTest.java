package com.migao.admin.controller;

// case_ids: API-017

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.KnowledgeTemplateInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.KnowledgeTemplateService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * KnowledgeTemplateController 测试（LLM WIKI 板块 P3，issue #3051）
 * 行业模板目录 + 一键套用端点
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeTemplateController 行业模板端点测试")
class KnowledgeTemplateControllerTest {

    private MockMvc mockMvc;

    @Mock
    private KnowledgeTemplateService knowledgeTemplateService;

    @InjectMocks
    private KnowledgeTemplateController knowledgeTemplateController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeTemplateController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("GET /api/admin/knowledge/templates — 模板目录")
    class ListTemplates {

        @Test
        @DisplayName("返回模板目录")
        void list_success() throws Exception {
            when(knowledgeTemplateService.listTemplates()).thenReturn(List.of(
                    KnowledgeTemplateInfo.builder()
                            .templateId("curtain").industry("curtain")
                            .name("布艺窗帘行业模板").version(1).entryCount(26)
                            .build()));

            mockMvc.perform(get("/api/admin/knowledge/templates"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data[0].templateId").value("curtain"))
                    .andExpect(jsonPath("$.data[0].entryCount").value(26));
        }
    }

    @Nested
    @DisplayName("POST /api/admin/knowledge/templates/{templateId}/apply — 一键套用")
    class Apply {

        @Test
        @DisplayName("套用返回统计")
        void apply_success() throws Exception {
            when(knowledgeTemplateService.applyTemplate("curtain"))
                    .thenReturn(Map.of("templateId", "curtain", "created", 26, "skipped", 0));

            mockMvc.perform(post("/api/admin/knowledge/templates/curtain/apply"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.created").value(26));
        }

        @Test
        @DisplayName("未知模板 → 404")
        void apply_unknown_404() throws Exception {
            when(knowledgeTemplateService.applyTemplate("nope"))
                    .thenThrow(BusinessException.notFound("行业模板"));

            mockMvc.perform(post("/api/admin/knowledge/templates/nope/apply"))
                    .andExpect(status().isNotFound());
        }
    }
}
