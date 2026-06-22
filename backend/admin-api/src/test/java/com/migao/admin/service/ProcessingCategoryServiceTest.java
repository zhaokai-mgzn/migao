package com.migao.admin.service;

import com.migao.admin.dto.ProcessingCategoryCreateRequest;
import com.migao.admin.dto.ProcessingCategoryResponse;
import com.migao.admin.dto.ProcessingCategoryUpdateRequest;
import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * ProcessingCategoryService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class ProcessingCategoryServiceTest {

    @Mock
    private ProcessingCategoryMapper processingCategoryMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @InjectMocks
    private ProcessingCategoryService processingCategoryService;

    private ProcessingCategory testCategory;
    private ProcessingItem testItem;

    @BeforeEach
    void setUp() {
        testCategory = ProcessingCategory.builder()
                .id("cat-001")
                .tenantId(1L)
                .name("裁剪")
                .sortOrder(1)
                .status("active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .build();

        testItem = ProcessingItem.builder()
                .id("item-001")
                .tenantId(1L)
                .categoryId("cat-001")
                .name("标准裁剪")
                .pricingMethod("by_meter")
                .unitPrice(new java.math.BigDecimal("15.00"))
                .unit("米")
                .status("active")
                .build();
    }

    // ======================== 查询分类列表测试 ========================

    @Test
    @DisplayName("获取加工分类列表 - 有数据")
    void getProcessingCategories_HasResults() {
        // given
        when(processingCategoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));
        when(processingItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testItem));

        // when
        List<ProcessingCategoryResponse> categories = processingCategoryService.getProcessingCategories(1L);

        // then
        assertThat(categories).hasSize(1);
        assertThat(categories.get(0).getName()).isEqualTo("裁剪");
        assertThat(categories.get(0).getItemCount()).isEqualTo(1);
    }

    @Test
    @DisplayName("获取加工分类列表 - 空列表")
    void getProcessingCategories_Empty() {
        // given
        when(processingCategoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of());

        // when
        List<ProcessingCategoryResponse> categories = processingCategoryService.getProcessingCategories(1L);

        // then
        assertThat(categories).isEmpty();
    }

    // ======================== 根据ID查询测试 ========================

    @Test
    @DisplayName("根据ID查询加工分类 - 存在")
    void getProcessingCategoryById_Found() {
        // given
        when(processingCategoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(processingItemMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(2L);

        // when
        ProcessingCategoryResponse result = processingCategoryService.getProcessingCategoryById("cat-001", 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("裁剪");
        assertThat(result.getItemCount()).isEqualTo(2);
    }

    @Test
    @DisplayName("根据ID查询加工分类 - 不存在")
    void getProcessingCategoryById_NotFound() {
        // given
        when(processingCategoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingCategoryService.getProcessingCategoryById("nonexistent", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 创建分类测试 ========================

    @Test
    @DisplayName("创建加工分类 - 成功")
    void createProcessingCategory_Success() {
        // given
        ProcessingCategoryCreateRequest request = new ProcessingCategoryCreateRequest();
        request.setName("缝纫");
        request.setSortOrder(2);
        request.setStatus("active");

        when(processingCategoryMapper.insert(any(ProcessingCategory.class))).thenAnswer(invocation -> {
            ProcessingCategory c = invocation.getArgument(0);
            c.setId("cat-new");
            return 1;
        });

        // when
        ProcessingCategoryResponse result = processingCategoryService.createProcessingCategory(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("缝纫");
        assertThat(result.getItemCount()).isEqualTo(0);
        verify(processingCategoryMapper).insert(any(ProcessingCategory.class));
    }

    // ======================== 更新分类测试 ========================

    @Test
    @DisplayName("更新加工分类 - 成功")
    void updateProcessingCategory_Success() {
        // given
        ProcessingCategoryUpdateRequest request = new ProcessingCategoryUpdateRequest();
        request.setName("高级裁剪");
        request.setSortOrder(3);
        request.setStatus("active");

        when(processingCategoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(processingCategoryMapper.updateById(any(ProcessingCategory.class))).thenReturn(1);

        // when
        ProcessingCategoryResponse result = processingCategoryService.updateProcessingCategory("cat-001", request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("高级裁剪");
        verify(processingCategoryMapper).updateById(any(ProcessingCategory.class));
    }

    @Test
    @DisplayName("更新加工分类 - 分类不存在")
    void updateProcessingCategory_NotFound() {
        // given
        ProcessingCategoryUpdateRequest request = new ProcessingCategoryUpdateRequest();
        request.setName("不存在");

        when(processingCategoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingCategoryService.updateProcessingCategory("nonexistent", request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 删除分类测试 ========================

    @Test
    @DisplayName("删除加工分类 - 无关联加工项，删除成功")
    void deleteProcessingCategory_Success() {
        // given
        when(processingCategoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(processingItemMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(processingCategoryMapper.deleteById("cat-001")).thenReturn(1);

        // when
        processingCategoryService.deleteProcessingCategory("cat-001", 1L);

        // then
        verify(processingCategoryMapper).deleteById("cat-001");
    }

    @Test
    @DisplayName("删除加工分类 - 分类不存在")
    void deleteProcessingCategory_NotFound() {
        // given
        when(processingCategoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingCategoryService.deleteProcessingCategory("nonexistent", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("删除加工分类 - 有关联加工项，拒绝删除")
    void deleteProcessingCategory_HasItems() {
        // given
        when(processingCategoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(processingItemMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(5L);

        // when & then
        assertThatThrownBy(() -> processingCategoryService.deleteProcessingCategory("cat-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("该分类下有关联加工项，无法删除");

        verify(processingCategoryMapper, never()).deleteById(anyString());
    }
}
