package com.migao.admin.service;

// case_ids: API-019

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KnowledgeCandidate;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * KnowledgeCandidateService 单元测试（LLM WIKI 板块 P5，issue #3051 — 待确认队列闭环）
 * 闭环二：candidate → 采纳/编辑后采纳 → 卡片 published；拒绝记原因；读写路径齐全（无死端）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeCandidateService 待确认队列测试")
class KnowledgeCandidateServiceTest {

    @InjectMocks
    private KnowledgeCandidateService knowledgeCandidateService;

    @Mock
    private KnowledgeCandidateMapper knowledgeCandidateMapper;
    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;

    private KnowledgeCandidate sample(String id) {
        return KnowledgeCandidate.builder()
                .id(id).tenantId(1L).sourceType("conversation").sourceRef("sess-1")
                .suggestedTitle("窗帘多久洗一次")
                .suggestedAnswer("建议每 3-6 个月清洗一次。")
                .suggestedCategory("faq")
                .suggestedKeywords("清洗,周期")
                .confidence(new java.math.BigDecimal("0.92"))
                .status("pending")
                .build();
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("adopt — 采纳（读路径 → 写路径闭环）")
    class Adopt {

        @Test
        @DisplayName("采纳：候选转卡片 published，来源继承 conversation，候选置 adopted")
        void adopt_createsPublishedCard() {
            KnowledgeCandidate candidate = sample("c1");
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(candidate);

            KnowledgeCard card = knowledgeCandidateService.adopt("c1");

            ArgumentCaptor<KnowledgeCard> cardCaptor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).insert(cardCaptor.capture());
            KnowledgeCard saved = cardCaptor.getValue();
            assertThat(saved.getTitle()).isEqualTo("窗帘多久洗一次");
            assertThat(saved.getAnswer()).isEqualTo("建议每 3-6 个月清洗一次。");
            assertThat(saved.getSourceType()).isEqualTo("conversation");
            assertThat(saved.getSourceRef()).isEqualTo("sess-1");
            assertThat(saved.getStatus()).isEqualTo("published");
            assertThat(saved.getQuestion()).isEqualTo("窗帘多久洗一次");

            ArgumentCaptor<KnowledgeCandidate> candidateCaptor = ArgumentCaptor.forClass(KnowledgeCandidate.class);
            verify(knowledgeCandidateMapper).updateById(candidateCaptor.capture());
            assertThat(candidateCaptor.getValue().getStatus()).isEqualTo("adopted");
            assertThat(candidateCaptor.getValue().getReviewedAt()).isNotNull();
        }

        @Test
        @DisplayName("跨租户候选 → 404（IDOR）")
        void adopt_crossTenant_notFound() {
            KnowledgeCandidate other = sample("c1");
            other.setTenantId(999L);
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(other);

            assertThatThrownBy(() -> knowledgeCandidateService.adopt("c1"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("候选");
            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
        }

        @Test
        @DisplayName("非 pending 候选不可采纳")
        void adopt_nonPending_rejected() {
            KnowledgeCandidate candidate = sample("c1");
            candidate.setStatus("rejected");
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(candidate);

            assertThatThrownBy(() -> knowledgeCandidateService.adopt("c1"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("采纳");
        }
    }

    @Nested
    @DisplayName("adoptEdited — 编辑后采纳")
    class AdoptEdited {

        @Test
        @DisplayName("编辑后采纳：人工修订标题/回答覆盖，候选置 edited")
        void adoptEdited_overridesFields() {
            KnowledgeCandidate candidate = sample("c1");
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(candidate);

            KnowledgeCandidate patch = KnowledgeCandidate.builder()
                    .suggestedTitle("窗帘清洗周期")
                    .suggestedAnswer("每 3-6 个月清洗一次（修订版）。")
                    .suggestedCategory("faq")
                    .build();
            knowledgeCandidateService.adoptEdited("c1", patch);

            ArgumentCaptor<KnowledgeCard> cardCaptor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).insert(cardCaptor.capture());
            assertThat(cardCaptor.getValue().getTitle()).isEqualTo("窗帘清洗周期");
            assertThat(cardCaptor.getValue().getAnswer()).isEqualTo("每 3-6 个月清洗一次（修订版）。");

            ArgumentCaptor<KnowledgeCandidate> candidateCaptor = ArgumentCaptor.forClass(KnowledgeCandidate.class);
            verify(knowledgeCandidateMapper).updateById(candidateCaptor.capture());
            assertThat(candidateCaptor.getValue().getStatus()).isEqualTo("edited");
        }

        @Test
        @DisplayName("编辑后采纳：标题/回答必填（校验先于查库，直接 422）")
        void adoptEdited_missingFields_422() {
            KnowledgeCandidate emptyPatch = KnowledgeCandidate.builder().build();
            assertThatThrownBy(() -> knowledgeCandidateService.adoptEdited("c1", emptyPatch))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("标题");
            verify(knowledgeCandidateMapper, never()).selectById(any());
        }
    }

    @Nested
    @DisplayName("reject — 拒绝（记录原因）")
    class Reject {

        @Test
        @DisplayName("拒绝：置 rejected + 拒绝原因")
        void reject_recordsNote() {
            KnowledgeCandidate candidate = sample("c1");
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(candidate);

            knowledgeCandidateService.reject("c1", "非本店业务");

            ArgumentCaptor<KnowledgeCandidate> captor = ArgumentCaptor.forClass(KnowledgeCandidate.class);
            verify(knowledgeCandidateMapper).updateById(captor.capture());
            assertThat(captor.getValue().getStatus()).isEqualTo("rejected");
            assertThat(captor.getValue().getStatusNote()).isEqualTo("非本店业务");
            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
        }

        @Test
        @DisplayName("跨租户拒绝 → 404")
        void reject_crossTenant_notFound() {
            KnowledgeCandidate other = sample("c1");
            other.setTenantId(999L);
            when(knowledgeCandidateMapper.selectById("c1")).thenReturn(other);

            assertThatThrownBy(() -> knowledgeCandidateService.reject("c1", "x"))
                    .isInstanceOf(BusinessException.class);
        }
    }

    @Nested
    @DisplayName("pendingCount — 待确认数量")
    class PendingCount {

        @Test
        @DisplayName("返回 pending 计数")
        void pendingCount_returnsCount() {
            when(knowledgeCandidateMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(3L);
            assertThat(knowledgeCandidateService.pendingCount()).isEqualTo(3L);
        }
    }
}
