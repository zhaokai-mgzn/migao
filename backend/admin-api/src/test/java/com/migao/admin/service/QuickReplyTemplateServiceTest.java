package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.QuickReplyCreateRequest;
import com.migao.admin.dto.QuickReplyResponse;
import com.migao.admin.dto.QuickReplyUpdateRequest;
import com.migao.admin.entity.QuickReplyTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.QuickReplyTemplateMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * QuickReplyTemplateService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class QuickReplyTemplateServiceTest {

    @Mock
    private QuickReplyTemplateMapper quickReplyTemplateMapper;

    @InjectMocks
    private QuickReplyTemplateService quickReplyTemplateService;

    private QuickReplyTemplate testTemplate;

    @BeforeEach
    void setUp() {
        testTemplate = QuickReplyTemplate.builder()
                .id("tpl-001")
                .tenantId(1L)
                .category("销售话术")
                .title("欢迎语")
                .content("您好，欢迎咨询米高布艺")
                .shortcut("/welcome")
                .isPublic(true)
                .usageCount(5)
                .build();
    }

    // ======================== 分页查询测试 ========================

    @Test
    @DisplayName("分页查询模板 - 默认分页")
    void getTemplatePage_DefaultPagination() {
        Page<QuickReplyTemplate> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testTemplate));
        mockPage.setTotal(1);
        when(quickReplyTemplateMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        PageResponse<QuickReplyResponse> result = quickReplyTemplateService.getTemplatePage(1, 20, null, null, 1L);

        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getTitle()).isEqualTo("欢迎语");
    }

    @Test
    @DisplayName("分页查询模板 - 带分类和关键词筛选")
    void getTemplatePage_WithFilters() {
        Page<QuickReplyTemplate> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testTemplate));
        mockPage.setTotal(1);
        when(quickReplyTemplateMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        PageResponse<QuickReplyResponse> result = quickReplyTemplateService.getTemplatePage(
                1, 10, "销售话术", "欢迎", 1L);

        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
    }

    @Test
    @DisplayName("分页查询模板 - 空结果")
    void getTemplatePage_EmptyResult() {
        Page<QuickReplyTemplate> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);
        when(quickReplyTemplateMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        PageResponse<QuickReplyResponse> result = quickReplyTemplateService.getTemplatePage(1, 20, null, null, 1L);

        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 创建模板测试 ========================

    @Test
    @DisplayName("创建模板 - 成功")
    void createTemplate_Success() {
        QuickReplyCreateRequest request = new QuickReplyCreateRequest();
        request.setCategory("销售话术");
        request.setTitle("新品推荐");
        request.setContent("我们家最近上新了窗帘系列");
        request.setShortcut("/new");
        request.setIsPublic(true);

        when(quickReplyTemplateMapper.insert(any(QuickReplyTemplate.class))).thenAnswer(invocation -> {
            QuickReplyTemplate t = invocation.getArgument(0);
            t.setId("tpl-new");
            return 1;
        });

        QuickReplyResponse result = quickReplyTemplateService.createTemplate(request, 1L);

        assertThat(result).isNotNull();
        assertThat(result.getTitle()).isEqualTo("新品推荐");
        assertThat(result.getUsageCount()).isEqualTo(0);
        assertThat(result.getIsPublic()).isTrue();
        verify(quickReplyTemplateMapper).insert(any(QuickReplyTemplate.class));
    }

    @Test
    @DisplayName("创建模板 - isPublic 默认为 true")
    void createTemplate_DefaultIsPublic() {
        QuickReplyCreateRequest request = new QuickReplyCreateRequest();
        request.setCategory("销售话术");
        request.setTitle("测试");
        request.setContent("内容");
        request.setShortcut("/test");

        when(quickReplyTemplateMapper.insert(any(QuickReplyTemplate.class))).thenAnswer(invocation -> {
            QuickReplyTemplate t = invocation.getArgument(0);
            t.setId("tpl-default");
            return 1;
        });

        QuickReplyResponse result = quickReplyTemplateService.createTemplate(request, 1L);

        assertThat(result.getIsPublic()).isTrue();
    }

    // ======================== 更新模板测试 ========================

    @Test
    @DisplayName("更新模板 - 成功")
    void updateTemplate_Success() {
        QuickReplyUpdateRequest request = new QuickReplyUpdateRequest();
        request.setTitle("更新后的标题");
        request.setContent("更新后的内容");
        request.setCategory("新分类");

        when(quickReplyTemplateMapper.selectById("tpl-001")).thenReturn(testTemplate);
        when(quickReplyTemplateMapper.updateById(any(QuickReplyTemplate.class))).thenReturn(1);

        QuickReplyResponse result = quickReplyTemplateService.updateTemplate("tpl-001", request);

        assertThat(result).isNotNull();
        assertThat(result.getTitle()).isEqualTo("更新后的标题");
        assertThat(result.getCategory()).isEqualTo("新分类");
        verify(quickReplyTemplateMapper).updateById(any(QuickReplyTemplate.class));
    }

    @Test
    @DisplayName("更新模板 - 模板不存在")
    void updateTemplate_NotFound() {
        QuickReplyUpdateRequest request = new QuickReplyUpdateRequest();
        request.setTitle("不存在的模板");
        when(quickReplyTemplateMapper.selectById("nonexistent")).thenReturn(null);

        assertThatThrownBy(() -> quickReplyTemplateService.updateTemplate("nonexistent", request))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 获取分类测试 ========================

    @Test
    @DisplayName("获取所有分类 - 有数据")
    void getCategories_HasResults() {
        QuickReplyTemplate t1 = QuickReplyTemplate.builder().category("销售话术").build();
        QuickReplyTemplate t2 = QuickReplyTemplate.builder().category("售后话术").build();
        when(quickReplyTemplateMapper.selectList(any(com.baomidou.mybatisplus.core.conditions.query.QueryWrapper.class)))
                .thenReturn(List.of(t1, t2));

        List<String> categories = quickReplyTemplateService.getCategories(1L);

        assertThat(categories).containsExactly("销售话术", "售后话术");
    }

    @Test
    @DisplayName("获取所有分类 - 无数据")
    void getCategories_Empty() {
        when(quickReplyTemplateMapper.selectList(any(com.baomidou.mybatisplus.core.conditions.query.QueryWrapper.class)))
                .thenReturn(List.of());

        List<String> categories = quickReplyTemplateService.getCategories(1L);

        assertThat(categories).isEmpty();
    }

    // ======================== 使用计数测试 ========================

    @Test
    @DisplayName("增加使用计数 - 调用 update 语句")
    void incrementUsageCount_Success() {
        when(quickReplyTemplateMapper.update(isNull(), any(LambdaUpdateWrapper.class))).thenReturn(1);

        quickReplyTemplateService.incrementUsageCount("tpl-001");

        verify(quickReplyTemplateMapper).update(isNull(), any(LambdaUpdateWrapper.class));
    }
}
