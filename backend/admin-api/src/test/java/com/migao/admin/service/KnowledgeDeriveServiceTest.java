package com.migao.admin.service;

// case_ids: API-018

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.KnowledgeCardMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * KnowledgeDeriveService 单元测试（LLM WIKI 板块，issue #3083 — 商品派生已移除，仅保留加工项派生）
 * 加工项 → 「{加工项名}怎么计价」派生卡片：pricingMethod 文案生成、同源 upsert、对账只对账加工项
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDeriveService 加工项派生测试")
class KnowledgeDeriveServiceTest {

    @InjectMocks
    private KnowledgeDeriveService knowledgeDeriveService;

    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;
    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @Nested
    @DisplayName("deriveAllProcessingCards — 加工项派生")
    class DeriveProcessingCards {

        @Test
        @DisplayName("按 pricingMethod 生成计价文案（per_meter 按米 / fixed 固定价格）")
        void deriveProcessingCards_pricingMethodText() {
            ProcessingItem perMeter = ProcessingItem.builder()
                    .id("pi1").tenantId(1L).name("打孔加工").pricingMethod("per_meter").unit("米").build();
            ProcessingItem fixed = ProcessingItem.builder()
                    .id("pi2").tenantId(1L).name("上门安装").pricingMethod("fixed").unitPrice(new BigDecimal("500")).build();
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(perMeter, fixed));
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

            int count = knowledgeDeriveService.deriveAllProcessingCards(1L);

            assertThat(count).isEqualTo(2);
            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper, times(2)).insert(captor.capture());
            KnowledgeCard card1 = captor.getAllValues().get(0);
            assertThat(card1.getTitle()).isEqualTo("打孔加工怎么计价");
            assertThat(card1.getAnswer()).contains("按米计价");
            assertThat(card1.getSourceType()).isEqualTo("config");
            assertThat(card1.getStatus()).isEqualTo("published");
            KnowledgeCard card2 = captor.getAllValues().get(1);
            assertThat(card2.getAnswer()).contains("固定价格 500 元");
        }

        @Test
        @DisplayName("已有派生卡片：同源 upsert 更新 version+1，不重复插入")
        void deriveProcessingCards_updatesExisting() {
            ProcessingItem item = ProcessingItem.builder()
                    .id("pi1").tenantId(1L).name("打孔加工").pricingMethod("per_meter").unit("米").build();
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(item));
            KnowledgeCard existing = KnowledgeCard.builder()
                    .id("c1").tenantId(1L).title("旧标题").answer("旧回答")
                    .sourceType("config").sourceRef("pi1").status("published").version(3)
                    .build();
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(existing);

            knowledgeDeriveService.deriveAllProcessingCards(1L);

            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).updateById(captor.capture());
            assertThat(captor.getValue().getVersion()).isEqualTo(4);
            assertThat(captor.getValue().getTitle()).isEqualTo("打孔加工怎么计价");
        }
    }

    @Nested
    @DisplayName("deriveAll — 对账派生（商品派生已移除，#3083）")
    class DeriveAll {

        @Test
        @DisplayName("仅对账加工项派生，返回 {processingItems}")
        void deriveAll_onlyProcessingItems() {
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    ProcessingItem.builder().id("pi1").tenantId(1L).name("打孔").pricingMethod("per_meter").build()));
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

            Map<String, Object> result = knowledgeDeriveService.deriveAll(1L);

            assertThat(result).containsOnlyKeys("processingItems");
            assertThat(result.get("processingItems")).isEqualTo(1);
        }
    }
}
