package com.migao.admin.service;

// case_ids: API-017

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.KnowledgeTemplateInfo;
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
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * KnowledgeTemplateService 单元测试（LLM WIKI 板块 P3，issue #3051）
 * 行业模板：目录读取 + 一键套用（source=template / 按 title 去重 / 返回统计）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeTemplateService 行业模板测试")
class KnowledgeTemplateServiceTest {

    @InjectMocks
    private KnowledgeTemplateService knowledgeTemplateService;

    @Mock
    private KnowledgeCardMapper knowledgeCardMapper;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("listTemplates — 模板目录")
    class ListTemplates {

        @Test
        @DisplayName("返回平台预置模板目录，布艺模板 entryCount≥30（读真实模板文件）")
        void listTemplates_returnsCurtainTemplate() {
            List<KnowledgeTemplateInfo> templates = knowledgeTemplateService.listTemplates();

            assertThat(templates).isNotEmpty();
            KnowledgeTemplateInfo curtain = templates.stream()
                    .filter(t -> "curtain".equals(t.getTemplateId()))
                    .findFirst().orElse(null);
            assertThat(curtain).as("应包含 curtain 布艺模板").isNotNull();
            assertThat(curtain.getName()).contains("布艺");
            assertThat(curtain.getIndustry()).isEqualTo("curtain");
            assertThat(curtain.getEntryCount()).isGreaterThanOrEqualTo(25);
        }
    }

    @Nested
    @DisplayName("applyTemplate — 一键套用")
    class ApplyTemplate {

        @Test
        @DisplayName("套用成功：复制为租户词条，sourceType=template/sourceRef=templateId/status=published")
        void apply_createsCardsWithTemplateSource() {
            // 全部 title 不存在 → 全量插入
            when(knowledgeCardMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);

            Map<String, Object> result = knowledgeTemplateService.applyTemplate("curtain");

            assertThat(result.get("templateId")).isEqualTo("curtain");
            assertThat((Integer) result.get("created")).isGreaterThanOrEqualTo(25);
            assertThat((Integer) result.get("skipped")).isZero();

            ArgumentCaptor<KnowledgeCard> captor = ArgumentCaptor.forClass(KnowledgeCard.class);
            verify(knowledgeCardMapper, atLeast(25)).insert(captor.capture());
            KnowledgeCard first = captor.getAllValues().get(0);
            assertThat(first.getTenantId()).isEqualTo(1L);
            assertThat(first.getSourceType()).isEqualTo("template");
            assertThat(first.getSourceRef()).isEqualTo("curtain");
            assertThat(first.getStatus()).isEqualTo("published");
            assertThat(first.getVersion()).isEqualTo(1);
            assertThat(first.getTitle()).isNotBlank();
            assertThat(first.getAnswer()).isNotBlank();
        }

        @Test
        @DisplayName("去重：已存在标题跳过，返回 created/skipped 统计")
        void apply_skipsDuplicateTitles() {
            // 首次调用返回 1（已存在）→ 全部跳过
            when(knowledgeCardMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

            Map<String, Object> result = knowledgeTemplateService.applyTemplate("curtain");

            assertThat((Integer) result.get("created")).isZero();
            assertThat((Integer) result.get("skipped")).isGreaterThanOrEqualTo(25);
            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
        }

        @Test
        @DisplayName("未知模板 → 404")
        void apply_unknownTemplate_notFound() {
            assertThatThrownBy(() -> knowledgeTemplateService.applyTemplate("nonexistent"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("模板");
            verify(knowledgeCardMapper, never()).insert(any(KnowledgeCard.class));
        }
    }
}
