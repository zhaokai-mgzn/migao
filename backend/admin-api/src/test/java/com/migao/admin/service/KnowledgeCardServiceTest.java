package com.migao.admin.service;

// case_ids: API-015, API-016

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KnowledgeCard;
import com.migao.admin.exception.BusinessException;
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

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * KnowledgeCardService 单元测试（LLM WIKI 板块 P2，issue #3051）
 * 覆盖：知识卡片 CRUD + 状态机（draft→published→archived）+ 租户隔离（IDOR）+ 检索（仅 published）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeCardService 知识卡片服务测试")
class KnowledgeCardServiceTest {

    @InjectMocks
    private KnowledgeCardService knowledgeCardService;

    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;

    private KnowledgeCard sampleEntry() {
        return KnowledgeCard.builder()
                .id("entry-1")
                .tenantId(1L)
                .title("雪尼尔面料会起球吗")
                .category("faq")
                .answer("雪尼尔织物起球概率较低，但日常摩擦仍可能产生起球，建议使用毛球修剪器。")
                .sourceType("manual")
                .status("draft")
                .version(1)
                .build();
    }

    @BeforeEach
    void setUp() {
        // 纯单测环境需初始化 MP 实体元数据（LambdaQueryWrapper 依赖 lambda 缓存，防测试顺序侥幸）
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, KnowledgeCard.class);
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("create — 创建知识卡片")
    class Create {

        @Test
        @DisplayName("title/answer 必填，缺则 400")
        void create_missingTitleOrAnswer_rejected() {
            KnowledgeCard noTitle = KnowledgeCard.builder().answer("内容").build();
            assertThatThrownBy(() -> knowledgeCardService.create(noTitle))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("标题");

            KnowledgeCard noAnswer = KnowledgeCard.builder().title("标题").build();
            assertThatThrownBy(() -> knowledgeCardService.create(noAnswer))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("回答");
        }

        @Test
        @DisplayName("创建成功：tenant 注入、sourceType=manual、version=1、status 缺省 draft")
        void create_success_defaults() {
            KnowledgeCard input = KnowledgeCard.builder().title("标题").answer("内容").build();
            knowledgeCardService.create(input);

            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).insert(captor.capture());
            KnowledgeCard saved = captor.getValue();
            assertThat(saved.getTenantId()).isEqualTo(1L);
            assertThat(saved.getSourceType()).isEqualTo("manual");
            assertThat(saved.getVersion()).isEqualTo(1);
            assertThat(saved.getStatus()).isEqualTo("draft");
        }

        @Test
        @DisplayName("显式 status=published 时直接发布")
        void create_explicitPublished() {
            KnowledgeCard input = KnowledgeCard.builder()
                    .title("标题").answer("内容").status("published").build();
            knowledgeCardService.create(input);
            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper).insert(captor.capture());
            assertThat(captor.getValue().getStatus()).isEqualTo("published");
        }
    }

    @Nested
    @DisplayName("update — 编辑知识卡片")
    class Update {

        @Test
        @DisplayName("编辑成功：version 递增")
        void update_success_versionIncrement() {
            KnowledgeCard existing = sampleEntry();
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(existing);

            KnowledgeCard patch = KnowledgeCard.builder()
                    .title("雪尼尔面料会起球吗（修订）")
                    .answer("更新后的回答")
                    .build();
            KnowledgeCard result = knowledgeCardService.update("entry-1", patch);

            assertThat(result.getVersion()).isEqualTo(2);
            assertThat(result.getTitle()).isEqualTo("雪尼尔面料会起球吗（修订）");
            verify(knowledgeCardMapper).updateById(existing);
        }

        @Test
        @DisplayName("跨租户编辑 → 404（IDOR 防护）")
        void update_crossTenant_notFound() {
            KnowledgeCard other = sampleEntry();
            other.setTenantId(999L);
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(other);

            assertThatThrownBy(() -> knowledgeCardService.update("entry-1", new KnowledgeCard()))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("知识卡片");
            verify(knowledgeCardMapper, never()).updateById(any(KnowledgeCard.class));
        }
    }

    @Nested
    @DisplayName("状态机 — publish/archive/delete")
    class StatusMachine {

        @Test
        @DisplayName("publish：draft → published，记录 reviewedAt")
        void publish_fromDraft() {
            KnowledgeCard existing = sampleEntry();
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(existing);

            KnowledgeCard result = knowledgeCardService.publish("entry-1");
            assertThat(result.getStatus()).isEqualTo("published");
            assertThat(result.getReviewedAt()).isNotNull();
            verify(knowledgeCardMapper).updateById(existing);
        }

        @Test
        @DisplayName("publish：archived 拒绝")
        void publish_fromArchived_rejected() {
            KnowledgeCard existing = sampleEntry();
            existing.setStatus("archived");
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(existing);

            assertThatThrownBy(() -> knowledgeCardService.publish("entry-1"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("发布");
        }

        @Test
        @DisplayName("archive：published → archived")
        void archive_fromPublished() {
            KnowledgeCard existing = sampleEntry();
            existing.setStatus("published");
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(existing);

            KnowledgeCard result = knowledgeCardService.archive("entry-1");
            assertThat(result.getStatus()).isEqualTo("archived");
        }

        @Test
        @DisplayName("delete：跨租户 → 404")
        void delete_crossTenant_notFound() {
            KnowledgeCard other = sampleEntry();
            other.setTenantId(999L);
            when(knowledgeCardMapper.selectById("entry-1")).thenReturn(other);

            assertThatThrownBy(() -> knowledgeCardService.delete("entry-1"))
                    .isInstanceOf(BusinessException.class);
            verify(knowledgeCardMapper, never()).deleteById(eq("entry-1"));
        }
    }

    @Nested
    @DisplayName("search — 知识卡片检索")
    class Search {

        @Test
        @DisplayName("仅 published + 租户过滤（.or() 嵌套在 eq 内，P1-6 回归）")
        void search_onlyPublishedTenantScoped() {
            knowledgeCardService.search("起球", null, null);

            @SuppressWarnings("unchecked")
            ArgumentCaptor<LambdaQueryWrapper<KnowledgeCard>> captor =
                    ArgumentCaptor.forClass(LambdaQueryWrapper.class);
            verify(knowledgeCardMapper).selectList(captor.capture());
            String sql = captor.getValue().getSqlSegment() + " " + captor.getValue().getParamNameValuePairs();

            assertThat(sql).contains("tenant_id = #{ew.paramNameValuePairs.MPGENVAL1}");
            assertThat(sql).contains("status = #{ew.paramNameValuePairs.MPGENVAL2}");
            assertThat(sql).contains("published");
        }

        @Test
        @DisplayName("分类软过滤：category 筛选为空 → 去掉分类重试（issue #3064 P1-2 二层缺陷）")
        void search_categorySoftFilter_retriesWithoutCategory() {
            when(knowledgeCardMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(java.util.List.of())
                    .thenReturn(java.util.List.of(sampleEntry()));
            List<KnowledgeCard> result = knowledgeCardService.search("退换货政策", null, "aftersale");
            assertThat(result).hasSize(1);
            verify(knowledgeCardMapper, times(2)).selectList(any(LambdaQueryWrapper.class));
        }

        @Test
        @DisplayName("关键词命中 title/keywords/question/answer，返回结果透传")
        void search_returnsMapperResults() {
            KnowledgeCard hit = sampleEntry();
            hit.setStatus("published");
            when(knowledgeCardMapper.selectList(any())).thenReturn(List.of(hit));

            List<KnowledgeCard> results = knowledgeCardService.search("起球", null, null);
            assertThat(results).hasSize(1);
            assertThat(results.get(0).getTitle()).isEqualTo("雪尼尔面料会起球吗");
        }
    }
}
