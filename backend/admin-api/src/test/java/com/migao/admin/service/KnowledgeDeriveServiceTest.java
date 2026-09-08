package com.migao.admin.service;

// case_ids: API-018

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.KnowledgeCardMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
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
 * KnowledgeDeriveService 单元测试（LLM WIKI 板块 P4，issue #3051 — L2 商品/配置派生）
 * 商品/加工项 → 派生知识卡片：价格区间自动生成、变更自动更新（upsert）、pricingMethod 文案
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeDeriveService 商品/配置派生测试")
class KnowledgeDeriveServiceTest {

    @InjectMocks
    private KnowledgeDeriveService knowledgeDeriveService;

    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;
    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    private Product product(String id, String name, Long tenantId) {
        return Product.builder().id(id).name(name).tenantId(tenantId).unit("米").build();
    }

    @Nested
    @DisplayName("deriveProductCard — 商品派生")
    class DeriveProductCard {

        @Test
        @DisplayName("新商品：生成「{名称}多少钱」卡片，answer 含 SKU 价格区间，sourceType=product")
        void deriveProductCard_createsCardWithPriceRange() {
            Product p = product("p1", "星空全遮光窗帘", 1L);
            when(productMapper.selectById("p1")).thenReturn(p);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    sku("p1", new BigDecimal("88")), sku("p1", new BigDecimal("128"))));
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

            knowledgeDeriveService.deriveProductCard(1L, "p1");

            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).insert(captor.capture());
            KnowledgeCard card = captor.getValue();
            assertThat(card.getTitle()).isEqualTo("星空全遮光窗帘多少钱");
            assertThat(card.getAnswer()).contains("88-128");
            assertThat(card.getAnswer()).contains("元/米");
            assertThat(card.getSourceType()).isEqualTo("product");
            assertThat(card.getSourceRef()).isEqualTo("p1");
            assertThat(card.getStatus()).isEqualTo("published");
            assertThat(card.getVersion()).isEqualTo(1);
            assertThat(card.getVariables()).contains("p1");
        }

        @Test
        @DisplayName("已有派生卡片：更新（version+1），不重复插入")
        void deriveProductCard_updatesExisting() {
            Product p = product("p1", "星空全遮光窗帘", 1L);
            when(productMapper.selectById("p1")).thenReturn(p);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku("p1", new BigDecimal("99"))));
            KnowledgeCard existing = KnowledgeCard.builder()
                    .id("c1").tenantId(1L).title("旧标题").answer("旧回答")
                    .sourceType("product").sourceRef("p1").status("published").version(3)
                    .build();
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(existing);

            knowledgeDeriveService.deriveProductCard(1L, "p1");

            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).updateById(captor.capture());
            assertThat(captor.getValue().getVersion()).isEqualTo(4);
            assertThat(captor.getValue().getAnswer()).contains("99");
        }

        @Test
        @DisplayName("跨租户商品：不派生")
        void deriveProductCard_crossTenant_ignored() {
            Product p = product("p9", "别人的商品", 999L);
            when(productMapper.selectById("p9")).thenReturn(p);
            knowledgeDeriveService.deriveProductCard(1L, "p9");
            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
        }
    }

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
            KnowledgeCard card2 = captor.getAllValues().get(1);
            assertThat(card2.getAnswer()).contains("固定价格 500 元");
        }
    }

    @Nested
    @DisplayName("deriveAll — 对账派生")
    class DeriveAll {

        @Test
        @DisplayName("全量商品+加工项派生，返回统计")
        void deriveAll_returnsCounts() {
            Product p1 = product("p1", "商品A", 1L);
            Product p2 = product("p2", "商品B", 1L);
            when(productMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(p1, p2));
            when(productMapper.selectById("p1")).thenReturn(p1);
            when(productMapper.selectById("p2")).thenReturn(p2);
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku("p1", new BigDecimal("100"))));
            when(knowledgeCardMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
            when(processingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(
                    ProcessingItem.builder().id("pi1").tenantId(1L).name("打孔").pricingMethod("per_meter").build()));

            Map<String, Object> result = knowledgeDeriveService.deriveAll(1L);

            assertThat(result.get("products")).isEqualTo(2);
            assertThat(result.get("processingItems")).isEqualTo(1);
        }
    }

    private ProductSku sku(String productId, BigDecimal price) {
        return ProductSku.builder().productId(productId).price(price).build();
    }
}
