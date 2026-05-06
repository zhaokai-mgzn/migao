package com.aikf.admin.service;

import com.aikf.admin.dto.CategoryCreateRequest;
import com.aikf.admin.dto.CategoryResponse;
import com.aikf.admin.dto.CategoryUpdateRequest;
import com.aikf.admin.entity.Category;
import com.aikf.admin.entity.Product;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.mapper.ProductMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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
 * CategoryService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class CategoryServiceTest {

    @InjectMocks
    private CategoryService categoryService;

    @Mock
    private CategoryMapper categoryMapper;

    @Mock
    private ProductMapper productMapper;

    private Category parentCategory;
    private Category childCategory;

    @BeforeEach
    void setUp() {
        parentCategory = Category.builder()
                .id("cat-001")
                .tenantId(1L)
                .name("窗帘")
                .parentId(null)
                .level(1)
                .sortOrder(1)
                .status("active")
                .build();

        childCategory = Category.builder()
                .id("cat-002")
                .tenantId(1L)
                .name("蜂巢帘")
                .parentId("cat-001")
                .level(2)
                .sortOrder(1)
                .status("active")
                .build();
    }

    // ======================== 获取分类树测试 ========================

    @Test
    @DisplayName("获取分类树 - 包含父子关系")
    void getCategoryTree_Success() {
        // given
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(parentCategory, childCategory));

        // when
        List<CategoryResponse> tree = categoryService.getCategoryTree(1L);

        // then
        assertThat(tree).hasSize(1);
        assertThat(tree.get(0).getName()).isEqualTo("窗帘");
        assertThat(tree.get(0).getChildren()).hasSize(1);
        assertThat(tree.get(0).getChildren().get(0).getName()).isEqualTo("蜂巢帘");
    }

    @Test
    @DisplayName("获取分类树 - 空列表")
    void getCategoryTree_Empty() {
        // given
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of());

        // when
        List<CategoryResponse> tree = categoryService.getCategoryTree(1L);

        // then
        assertThat(tree).isEmpty();
    }

    @Test
    @DisplayName("获取分类树 - 多个顶级分类")
    void getCategoryTree_MultipleRoots() {
        // given
        Category anotherRoot = Category.builder()
                .id("cat-003")
                .tenantId(1L)
                .name("配件")
                .parentId(null)
                .level(1)
                .sortOrder(2)
                .status("active")
                .build();
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(parentCategory, anotherRoot, childCategory));

        // when
        List<CategoryResponse> tree = categoryService.getCategoryTree(1L);

        // then
        assertThat(tree).hasSize(2);
    }

    // ======================== 创建分类测试 ========================

    @Test
    @DisplayName("创建顶级分类成功")
    void createCategory_TopLevelSuccess() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("新分类");
        request.setStatus("active");

        when(categoryMapper.insert(any(Category.class))).thenAnswer(invocation -> {
            Category c = invocation.getArgument(0);
            c.setId("cat-new");
            return 1;
        });

        // when
        CategoryResponse result = categoryService.createCategory(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("新分类");
        verify(categoryMapper).insert(any(Category.class));
    }

    @Test
    @DisplayName("创建子分类成功 - 校验父分类存在")
    void createCategory_WithParentSuccess() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("子分类");
        request.setParentId("cat-001");

        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.insert(any(Category.class))).thenAnswer(invocation -> {
            Category c = invocation.getArgument(0);
            c.setId("cat-new");
            return 1;
        });

        // when
        CategoryResponse result = categoryService.createCategory(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("子分类");
        // 验证层级被设置为 parentLevel + 1
        assertThat(request.getLevel()).isEqualTo(2);
    }

    @Test
    @DisplayName("创建子分类失败 - 父分类不存在")
    void createCategory_ParentNotFound() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("子分类");
        request.setParentId("nonexistent");

        when(categoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> categoryService.createCategory(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("父分类不存在");
    }

    // ======================== 更新分类测试 ========================

    @Test
    @DisplayName("更新分类成功")
    void updateCategory_Success() {
        // given
        CategoryUpdateRequest request = new CategoryUpdateRequest();
        request.setName("更新后的分类");
        request.setStatus("active");

        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.updateById(any(Category.class))).thenReturn(1);

        // when
        CategoryResponse result = categoryService.updateCategory("cat-001", request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("更新后的分类");
        verify(categoryMapper).updateById(any(Category.class));
    }

    @Test
    @DisplayName("更新分类失败 - 分类不存在")
    void updateCategory_NotFound() {
        // given
        CategoryUpdateRequest request = new CategoryUpdateRequest();
        request.setName("更新");

        when(categoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> categoryService.updateCategory("nonexistent", request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("更新分类失败 - 不能将自己设为父分类")
    void updateCategory_SelfParent() {
        // given
        CategoryUpdateRequest request = new CategoryUpdateRequest();
        request.setName("更新");
        request.setParentId("cat-001");

        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);

        // when & then
        assertThatThrownBy(() -> categoryService.updateCategory("cat-001", request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("不能将自己设为父分类");
    }

    // ======================== 删除分类测试 ========================

    @Test
    @DisplayName("删除分类成功")
    void deleteCategory_Success() {
        // given
        when(categoryMapper.selectById("cat-002")).thenReturn(childCategory);
        when(categoryMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(productMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(categoryMapper.deleteById("cat-002")).thenReturn(1);

        // when
        categoryService.deleteCategory("cat-002", 1L);

        // then
        verify(categoryMapper).deleteById("cat-002");
    }

    @Test
    @DisplayName("删除分类失败 - 分类不存在")
    void deleteCategory_NotFound() {
        // given
        when(categoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> categoryService.deleteCategory("nonexistent", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("删除分类失败 - 存在子分类")
    void deleteCategory_HasChildren() {
        // given
        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        // when & then
        assertThatThrownBy(() -> categoryService.deleteCategory("cat-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("该分类下有子分类，无法删除");
    }

    @Test
    @DisplayName("删除分类失败 - 存在关联商品")
    void deleteCategory_HasProducts() {
        // given
        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(productMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(5L);

        // when & then
        assertThatThrownBy(() -> categoryService.deleteCategory("cat-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("该分类下有关联商品，无法删除");
    }
}
