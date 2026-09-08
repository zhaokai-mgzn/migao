package com.migao.admin.controller;

// case_ids: API-015, API-016

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.KnowledgeCardService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * KnowledgeCardController 测试（LLM WIKI 板块 P2，issue #3051）
 * 知识卡片端点 + 租户隔离（IDOR 防护）+ 检索仅 published
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeCardController 知识卡片端点测试")
class KnowledgeCardControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private KnowledgeCardService knowledgeCardService;

    @InjectMocks
    private KnowledgeCardController knowledgeCardController;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, KnowledgeCard.class);

        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeCardController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private KnowledgeCard sample() {
        return KnowledgeCard.builder()
                .id("entry-1")
                .tenantId(1L)
                .title("雪尼尔面料会起球吗")
                .answer("雪尼尔织物起球概率较低……")
                .sourceType("manual")
                .status("published")
                .version(2)
                .build();
    }

    @Nested
    @DisplayName("POST /api/admin/knowledge/cards — 创建知识卡片")
    class Create {

        @Test
        @DisplayName("创建成功返回 200 + 知识卡片")
        void create_success() throws Exception {
            KnowledgeCard input = KnowledgeCard.builder().title("标题").answer("内容").build();
            KnowledgeCard saved = sample();
            when(knowledgeCardService.create(any(KnowledgeCard.class))).thenReturn(saved);

            mockMvc.perform(post("/api/admin/knowledge/cards")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(input)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.id").value("entry-1"))
                    .andExpect(jsonPath("$.data.title").value("雪尼尔面料会起球吗"));
        }

        @Test
        @DisplayName("title 缺失 → 422 中文 error.message（service 抛 validationError）")
        void create_missingTitle_400() throws Exception {
            when(knowledgeCardService.create(any(KnowledgeCard.class)))
                    .thenThrow(BusinessException.validationError("知识卡片标题不能为空"));

            mockMvc.perform(post("/api/admin/knowledge/cards")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"answer\":\"内容\"}"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.message").value("知识卡片标题不能为空"));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/knowledge/cards/search — 知识卡片检索")
    class Search {

        @Test
        @DisplayName("返回知识卡片列表（仅 published，service 侧强制租户）")
        void search_success() throws Exception {
            when(knowledgeCardService.search(eq("起球"), any(), any()))
                    .thenReturn(List.of(sample()));

            mockMvc.perform(get("/api/admin/knowledge/cards/search")
                            .param("query", "起球"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data[0].title").value("雪尼尔面料会起球吗"))
                    .andExpect(jsonPath("$.data[0].status").value("published"));
        }
    }

    @Nested
    @DisplayName("状态机端点 — publish/archive/delete")
    class StatusEndpoints {

        @Test
        @DisplayName("POST /{id}/publish → published")
        void publish_success() throws Exception {
            KnowledgeCard published = sample();
            when(knowledgeCardService.publish("entry-1")).thenReturn(published);

            mockMvc.perform(post("/api/admin/knowledge/cards/entry-1/publish"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("published"));
        }

        @Test
        @DisplayName("跨租户 publish → 404")
        void publish_crossTenant_404() throws Exception {
            when(knowledgeCardService.publish("entry-1"))
                    .thenThrow(BusinessException.notFound("知识卡片"));

            mockMvc.perform(post("/api/admin/knowledge/cards/entry-1/publish"))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("POST /{id}/archive → archived")
        void archive_success() throws Exception {
            KnowledgeCard archived = sample();
            archived.setStatus("archived");
            when(knowledgeCardService.archive("entry-1")).thenReturn(archived);

            mockMvc.perform(post("/api/admin/knowledge/cards/entry-1/archive"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("archived"));
        }

        @Test
        @DisplayName("DELETE /{id} → 200")
        void delete_success() throws Exception {
            mockMvc.perform(delete("/api/admin/knowledge/cards/entry-1"))
                    .andExpect(status().isOk());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/knowledge/cards — 分页列表")
    class Page {

        @Test
        @DisplayName("分页返回知识卡片列表")
        void page_success() throws Exception {
            com.migao.admin.dto.PageResponse<KnowledgeCard> pageResp =
                    com.migao.admin.dto.PageResponse.of(1L, 1L, 10L, List.of(sample()));
            when(knowledgeCardService.page(eq(1L), eq(10L), any(), any(), any(), any()))
                    .thenReturn(pageResp);

            mockMvc.perform(get("/api/admin/knowledge/cards")
                            .param("page", "1").param("size", "10"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.total").value(1));
        }
    }
}
