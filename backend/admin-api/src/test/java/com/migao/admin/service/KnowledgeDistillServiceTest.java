package com.migao.admin.service;

// case_ids: API-020

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.mapper.AgentMessageMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.KnowledgeCandidateMapper;
import com.migao.admin.mapper.KnowledgeCardMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * KnowledgeDistillService 单元测试（LLM WIKI 板块 P5b，issue #3051 — L3 会话提炼）
 * 闭环三：已结束人工会话 → AI 提炼候选 → 待确认队列（去重：同名卡片/候选跳过）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDistillService 会话提炼测试")
class KnowledgeDistillServiceTest {

    @InjectMocks
    private KnowledgeDistillService knowledgeDistillService;

    @Mock
    private AgentSessionMapper agentSessionMapper;
    @Mock
    private AgentMessageMapper agentMessageMapper;
    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;
    @Mock
    private KnowledgeCandidateMapper knowledgeCandidateMapper;
    @Mock
    private KnowledgeDistillClient distillClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private AgentSession endedSession(String id) {
        return AgentSession.builder()
                .id(id).tenantId(1L).status("ended").endedAt(OffsetDateTime.now().minusHours(2)).build();
    }

    private JsonNode candidate(String title, String answer) {
        return objectMapper.createObjectNode()
                .put("title", title).put("answer", answer)
                .put("category", "faq").put("keywords", "清洗")
                .put("confidence", "0.9").put("evidence", "顾客原话");
    }

    @Nested
    @DisplayName("distillConversations — 会话提炼")
    class DistillConversations {

        @Test
        @DisplayName("提炼：会话文本 → 候选写入待确认队列（source=conversation/pending）")
        void distill_createsPendingCandidates() throws Exception {
            AgentSession session = endedSession("s1");
            when(agentSessionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(session));
            when(agentMessageMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    AgentMessage.builder().tenantId(1L).sessionId("s1").senderType("customer").content("多久洗一次？").isInternal(false).build(),
                    AgentMessage.builder().tenantId(1L).sessionId("s1").senderType("agent").content("建议每3-6个月清洗一次。").isInternal(false).build()));
            when(distillClient.distill(anyString(), eq(5), eq(1L))).thenReturn(List.of(
                    candidate("窗帘多久洗一次", "建议每 3-6 个月清洗一次。")));
            when(knowledgeCardMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
            when(knowledgeCandidateMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);

            Map<String, Object> result = knowledgeDistillService.distillConversations(1L, 24);

            assertThat(result.get("sessions")).isEqualTo(1);
            assertThat(result.get("candidates")).isEqualTo(1);
            assertThat(result.get("created")).isEqualTo(1);
            assertThat(result.get("skipped")).isEqualTo(0);

            ArgumentCaptor<KnowledgeCandidate> captor = ArgumentCaptor.forClass(KnowledgeCandidate.class);
            verify(knowledgeCandidateMapper).insert(captor.capture());
            KnowledgeCandidate saved = captor.getValue();
            assertThat(saved.getTenantId()).isEqualTo(1L);
            assertThat(saved.getSourceType()).isEqualTo("conversation");
            assertThat(saved.getSourceRef()).isEqualTo("s1");
            assertThat(saved.getSuggestedTitle()).isEqualTo("窗帘多久洗一次");
            assertThat(saved.getStatus()).isEqualTo("pending");
            assertThat(saved.getConfidence()).isEqualByComparingTo("0.900");
        }

        @Test
        @DisplayName("去重：同名知识卡片已存在 → 跳过")
        void distill_skipsExistingCardTitle() throws Exception {
            AgentSession session = endedSession("s1");
            when(agentSessionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(session));
            when(agentMessageMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    AgentMessage.builder().tenantId(1L).sessionId("s1").senderType("customer").content("Q").isInternal(false).build(),
                    AgentMessage.builder().tenantId(1L).sessionId("s1").senderType("agent").content("A").isInternal(false).build()));
            when(distillClient.distill(anyString(), eq(5), eq(1L))).thenReturn(List.of(
                    candidate("已存在的标题", "答案")));
            // 卡片已存在 → 去重跳过
            when(knowledgeCardMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

            Map<String, Object> result = knowledgeDistillService.distillConversations(1L, 24);

            assertThat(result.get("created")).isEqualTo(0);
            assertThat(result.get("skipped")).isEqualTo(1);
            verify(knowledgeCandidateMapper, never()).insert(any(KnowledgeCandidate.class));
        }

        @Test
        @DisplayName("无已结束会话 → 空统计，不调提炼")
        void distill_noSessions() {
            when(agentSessionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            Map<String, Object> result = knowledgeDistillService.distillConversations(1L, 24);

            assertThat(result.get("sessions")).isEqualTo(0);
            verify(distillClient, never()).distill(anyString(), anyInt(), any());
        }

        @Test
        @DisplayName("文档提炼：文档文本 → 候选（source=document/pending）")
        void distillDocument_createsPendingCandidates() throws Exception {
            when(distillClient.distill(anyString(), eq(5), eq(1L))).thenReturn(List.of(
                    candidate("文档里的知识", "提炼出的标准回答")));
            when(knowledgeCardMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
            when(knowledgeCandidateMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);

            Map<String, Object> result = knowledgeDistillService.distillDocument(1L, "面料手册", "这是一段足够长的文档内容。".repeat(10));

            assertThat(result.get("created")).isEqualTo(1);
            ArgumentCaptor<KnowledgeCandidate> captor = ArgumentCaptor.forClass(KnowledgeCandidate.class);
            verify(knowledgeCandidateMapper).insert(captor.capture());
            KnowledgeCandidate saved = captor.getValue();
            assertThat(saved.getSourceType()).isEqualTo("document");
            assertThat(saved.getSourceRef()).isEqualTo("面料手册");
            assertThat(saved.getStatus()).isEqualTo("pending");
        }

        @Test
        @DisplayName("文档提炼：内容过短 → 422")
        void distillDocument_tooShort_rejected() {
            assertThatThrownBy(() -> knowledgeDistillService.distillDocument(1L, "t", "太短"))
                    .isInstanceOf(com.migao.admin.exception.BusinessException.class)
                    .hasMessageContaining("过短");
            verify(distillClient, never()).distill(anyString(), anyInt(), any());
        }

        @Test
        @DisplayName("提炼接口不可用（空候选）→ 不写队列")
        void distill_clientDegraded() throws Exception {
            AgentSession session = endedSession("s1");
            when(agentSessionMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(session));
            when(agentMessageMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    AgentMessage.builder().tenantId(1L).sessionId("s1").senderType("customer").content("Q").isInternal(false).build()));
            when(distillClient.distill(anyString(), eq(5), eq(1L))).thenReturn(List.of());

            Map<String, Object> result = knowledgeDistillService.distillConversations(1L, 24);

            assertThat(result.get("candidates")).isEqualTo(0);
            verify(knowledgeCandidateMapper, never()).insert(any(KnowledgeCandidate.class));
        }
    }
}
