package com.migao.admin.controller;

// case_ids: API-019

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.KnowledgeCandidateService;
import com.fasterxml.jackson.databind.ObjectMapper;
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

import java.util.Map;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * KnowledgeCandidateController 测试（LLM WIKI 板块 P5，issue #3051 — 待确认队列端点）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeCandidateController 待确认队列端点测试")
class KnowledgeCandidateControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private KnowledgeCandidateService knowledgeCandidateService;

    @InjectMocks
    private KnowledgeCandidateController knowledgeCandidateController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeCandidateController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("GET /candidates/pending-count 返回待确认数")
    void pendingCount_success() throws Exception {
        when(knowledgeCandidateService.pendingCount()).thenReturn(5L);

        mockMvc.perform(get("/api/admin/knowledge/candidates/pending-count"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pending").value(5));
    }

    @Test
    @DisplayName("POST /{id}/adopt 采纳返回发布的卡片")
    void adopt_success() throws Exception {
        KnowledgeCard card = KnowledgeCard.builder()
                .id("card-1").title("窗帘多久洗一次").answer("建议每 3-6 个月清洗一次。")
                .sourceType("conversation").status("published").version(1).build();
        when(knowledgeCandidateService.adopt("c1")).thenReturn(card);

        mockMvc.perform(post("/api/admin/knowledge/candidates/c1/adopt"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("card-1"))
                .andExpect(jsonPath("$.data.status").value("published"));
    }

    @Test
    @DisplayName("POST /{id}/adopt-edited 编辑后采纳")
    void adoptEdited_success() throws Exception {
        KnowledgeCandidate patch = KnowledgeCandidate.builder()
                .suggestedTitle("窗帘清洗周期").suggestedAnswer("每 3-6 个月清洗一次（修订版）。").build();
        KnowledgeCard card = KnowledgeCard.builder()
                .id("card-2").title("窗帘清洗周期").answer("每 3-6 个月清洗一次（修订版）。")
                .sourceType("conversation").status("published").version(1).build();
        when(knowledgeCandidateService.adoptEdited(org.mockito.ArgumentMatchers.eq("c1"), org.mockito.ArgumentMatchers.any(KnowledgeCandidate.class)))
                .thenReturn(card);

        mockMvc.perform(post("/api/admin/knowledge/candidates/c1/adopt-edited")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(patch)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.title").value("窗帘清洗周期"));
    }

    @Test
    @DisplayName("POST /{id}/reject 拒绝；跨租户 404")
    void reject_successAndIdor() throws Exception {
        mockMvc.perform(post("/api/admin/knowledge/candidates/c1/reject")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"note\":\"非本店业务\"}"))
                .andExpect(status().isOk());

        org.mockito.Mockito.doThrow(BusinessException.notFound("提炼候选"))
                .when(knowledgeCandidateService).reject("c9", null);
        mockMvc.perform(post("/api/admin/knowledge/candidates/c9/reject"))
                .andExpect(status().isNotFound());
    }
}
