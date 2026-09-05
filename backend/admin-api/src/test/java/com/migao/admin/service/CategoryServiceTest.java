// case_ids: CT-001, CT-002, CT-003
package com.migao.admin.service;

import com.migao.admin.dto.CategoryCreateRequest;
import com.migao.admin.dto.CategoryResponse;
import com.migao.admin.dto.CategoryUpdateRequest;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * CategoryService 单元测试
 *
 * 覆盖（issue #2905 — 分类排序重构：扁平分类、上下移动、移除排序输入）：
 * - 分类列表为扁平结构（无父子嵌套）
 * - 新分类默认追加到末尾（sortOrder = max + 1）
 * - 创建/更新忽略 parentId（父子概念移除）
 * - 删除不再因「存在子分类」被拦截
 * - moveCategory 上移/下移（边界幂等、非法方向、不存在 404）
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

    // ======================== 获取分类列表（扁平）测试 ========================

    @Test
    @DisplayName("获取分类列表 - 扁平返回全部分类（无父子嵌套）")
    void getCategoryTree_FlatAll() {
        // given
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(parentCategory, childCategory));

        // when
        List<CategoryResponse> tree = categoryService.getCategoryTree(1L);

        // then —— 父子不再嵌套，全部平铺返回
        assertThat(tree).hasSize(2);
        assertThat(tree).extracting(CategoryResponse::getId)
                .containsExactly("cat-001", "cat-002");
        assertThat(tree).allSatisfy(c -> assertThat(c.getChildren()).isEmpty());
    }

    @Test
    @DisplayName("获取分类列表 - 空列表")
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
    @DisplayName("获取分类列表 - 按 sortOrder 升序返回")
    void getCategoryTree_SortedBySortOrder() {
        // given
        Category anotherRoot = Category.builder()
                .id("cat-003")
                .tenantId(1L)
                .name("配件")
                .sortOrder(2)
                .status("active")
                .build();
        // selectList 的排序由 SQL wrapper 保证，这里模拟已排序的结果
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(parentCategory, anotherRoot, childCategory));

        // when
        List<CategoryResponse> tree = categoryService.getCategoryTree(1L);

        // then
        assertThat(tree).hasSize(3);
    }

    // ======================== 创建分类测试 ========================

    @Test
    @DisplayName("创建分类成功")
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
    @DisplayName("创建分类 - 请求携带的 sortOrder 持久化到插入实体")
    void createCategory_PersistsSortOrder() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("新分类");
        request.setSortOrder(7);

        when(categoryMapper.insert(any(Category.class))).thenAnswer(invocation -> {
            Category c = invocation.getArgument(0);
            c.setId("cat-sort");
            return 1;
        });

        // when
        CategoryResponse result = categoryService.createCategory(request, 1L);

        // then
        assertThat(result.getSortOrder()).isEqualTo(7);
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper).insert(captor.capture());
        assertThat(captor.getValue().getSortOrder()).isEqualTo(7);
    }

    @Test
    @DisplayName("创建分类 - 未指定排序时默认追加到末尾（sortOrder = max + 1）")
    void createCategory_AppendToEndWhenSortNull() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("新分类");
        request.setSortOrder(null);

        // 模拟「查询最大排序号」：desc LIMIT 1 → sortOrder=5
        Category last = Category.builder().id("cat-max").sortOrder(5).build();
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(last));
        when(categoryMapper.insert(any(Category.class))).thenAnswer(invocation -> {
            Category c = invocation.getArgument(0);
            c.setId("cat-new");
            return 1;
        });

        // when
        CategoryResponse result = categoryService.createCategory(request, 1L);

        // then —— 追加到末尾：max(5) + 1 = 6
        assertThat(result.getSortOrder()).isEqualTo(6);
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper).insert(captor.capture());
        assertThat(captor.getValue().getSortOrder()).isEqualTo(6);
    }

    @Test
    @DisplayName("创建分类 - 忽略 parentId（父子概念移除，不查父分类、不抛错）")
    void createCategory_IgnoresParentId() {
        // given
        CategoryCreateRequest request = new CategoryCreateRequest();
        request.setName("新分类");
        request.setParentId("cat-001");
        request.setLevel(null); // 模拟前端不传 level

        when(categoryMapper.insert(any(Category.class))).thenAnswer(invocation -> {
            Category c = invocation.getArgument(0);
            c.setId("cat-new");
            return 1;
        });

        // when & then —— 不校验父分类存在性、不抛 BusinessException
        assertThatCode(() -> categoryService.createCategory(request, 1L))
                .doesNotThrowAnyException();
        verify(categoryMapper, never()).selectById(anyString());
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
    @DisplayName("更新分类 - 请求携带的 sortOrder 持久化到更新实体")
    void updateCategory_PersistsSortOrder() {
        // given
        CategoryUpdateRequest request = new CategoryUpdateRequest();
        request.setName("更新后的分类");
        request.setSortOrder(10);

        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.updateById(any(Category.class))).thenReturn(1);

        // when
        CategoryResponse result = categoryService.updateCategory("cat-001", request, 1L);

        // then
        assertThat(result.getSortOrder()).isEqualTo(10);
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper).updateById(captor.capture());
        assertThat(captor.getValue().getSortOrder()).isEqualTo(10);
    }

    @Test
    @DisplayName("更新分类 - 未传 sort 时保留原排序值（防止 PUT 清空排序跳位）")
    void updateCategory_KeepsSortWhenNotProvided() {
        // given —— 原实体 sortOrder=1，请求只带 name（前端 issue #2905 不再提交 sort）
        CategoryUpdateRequest request = new CategoryUpdateRequest();
        request.setName("只改名字");

        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(categoryMapper.updateById(any(Category.class))).thenReturn(1);

        // when
        categoryService.updateCategory("cat-001", request, 1L);

        // then —— 持久化实体的 sortOrder 仍为 1
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper).updateById(captor.capture());
        assertThat(captor.getValue().getSortOrder()).isEqualTo(1);
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

    // ======================== 删除分类测试 ========================

    @Test
    @DisplayName("删除分类成功")
    void deleteCategory_Success() {
        // given
        when(categoryMapper.selectById("cat-002")).thenReturn(childCategory);
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
    @DisplayName("删除分类 - 存在旧子分类数据也不拦截（父子概念移除）")
    void deleteCategory_AllowsLegacyChildren() {
        // given —— 旧数据中存在 parentId 指向本分类，但不再视为「有子分类不能删」
        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(productMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(categoryMapper.deleteById("cat-001")).thenReturn(1);

        // when & then
        assertThatCode(() -> categoryService.deleteCategory("cat-001", 1L))
                .doesNotThrowAnyException();
        verify(categoryMapper).deleteById("cat-001");
    }

    @Test
    @DisplayName("删除分类失败 - 存在关联商品")
    void deleteCategory_HasProducts() {
        // given
        when(categoryMapper.selectById("cat-001")).thenReturn(parentCategory);
        when(productMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(5L);

        // when & then
        assertThatThrownBy(() -> categoryService.deleteCategory("cat-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("该分类下有关联商品，无法删除");
    }

    // ======================== 上下移动测试 ========================

    private Category cat(String id, int sort) {
        return Category.builder().id(id).tenantId(1L).name(id).sortOrder(sort).status("active").build();
    }

    @Test
    @DisplayName("上移 - 与前一分类交换顺序，sortOrder 重新编号")
    void moveCategory_Up() {
        // given —— 顺序：A(0) B(1) C(2)
        Category a = cat("A", 0);
        Category b = cat("B", 1);
        Category c = cat("C", 2);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(a, b, c));
        when(categoryMapper.updateById(any(Category.class))).thenReturn(1);

        // when —— 移动 B 上移一位（期望序列：B A C）
        categoryService.moveCategory("B", "up", 1L);

        // then —— A/B 被更新，sortOrder 反映新位置；C 位置未变无需更新
        verify(categoryMapper, times(2)).updateById(any(Category.class));
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper, atLeastOnce()).updateById(captor.capture());
        assertThat(captor.getAllValues())
                .filteredOn(x -> x.getId().equals("B"))
                .first()
                .extracting(Category::getSortOrder)
                .isEqualTo(0);
        assertThat(captor.getAllValues())
                .filteredOn(x -> x.getId().equals("A"))
                .first()
                .extracting(Category::getSortOrder)
                .isEqualTo(1);
    }

    @Test
    @DisplayName("下移 - 与后一分类交换顺序，sortOrder 重新编号")
    void moveCategory_Down() {
        // given —— 顺序：A(0) B(1) C(2)
        Category a = cat("A", 0);
        Category b = cat("B", 1);
        Category c = cat("C", 2);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(a, b, c));
        when(categoryMapper.updateById(any(Category.class))).thenReturn(1);

        // when —— 移动 B 下移一位（期望序列：A C B）
        categoryService.moveCategory("B", "down", 1L);

        // then
        ArgumentCaptor<Category> captor = ArgumentCaptor.forClass(Category.class);
        verify(categoryMapper, atLeastOnce()).updateById(captor.capture());
        assertThat(captor.getAllValues())
                .filteredOn(x -> x.getId().equals("B"))
                .first()
                .extracting(Category::getSortOrder)
                .isEqualTo(2);
        assertThat(captor.getAllValues())
                .filteredOn(x -> x.getId().equals("C"))
                .first()
                .extracting(Category::getSortOrder)
                .isEqualTo(1);
    }

    @Test
    @DisplayName("上移 - 已在首位时幂等不报错（无持久化）")
    void moveCategory_UpAtFirst_Noop() {
        // given
        Category a = cat("A", 0);
        Category b = cat("B", 1);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(a, b));

        // when & then
        assertThatCode(() -> categoryService.moveCategory("A", "up", 1L))
                .doesNotThrowAnyException();
        verify(categoryMapper, never()).updateById(any(Category.class));
    }

    @Test
    @DisplayName("下移 - 已在末尾时幂等不报错（无持久化）")
    void moveCategory_DownAtLast_Noop() {
        // given
        Category a = cat("A", 0);
        Category b = cat("B", 1);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(a, b));

        // when & then
        assertThatCode(() -> categoryService.moveCategory("B", "down", 1L))
                .doesNotThrowAnyException();
        verify(categoryMapper, never()).updateById(any(Category.class));
    }

    @Test
    @DisplayName("移动失败 - 分类不存在")
    void moveCategory_NotFound() {
        // given
        Category a = cat("A", 0);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(a));

        // when & then
        assertThatThrownBy(() -> categoryService.moveCategory("ghost", "up", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("移动失败 - 非法方向")
    void moveCategory_InvalidDirection() {
        // given —— 方向校验发生在查询之前，无需 stub selectList

        // when & then
        assertThatThrownBy(() -> categoryService.moveCategory("A", "left", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不支持的方向");
    }
}