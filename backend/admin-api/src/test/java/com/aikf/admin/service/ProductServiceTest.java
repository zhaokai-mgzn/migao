package com.aikf.admin.service;

import com.aikf.admin.dto.*;
import com.aikf.admin.entity.Category;
import com.aikf.admin.entity.Product;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.mapper.ProductMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * ProductService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class ProductServiceTest {

    @InjectMocks
    private ProductService productService;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private CategoryMapper categoryMapper;

    private Product testProduct;
    private Category testCategory;

    @BeforeEach
    void setUp() {
        testCategory = Category.builder()
                .id("cat-001")
                .tenantId(1L)
                .name("窗帘")
                .status("active")
                .build();

        testProduct = Product.builder()
                .id("prod-001")
                .tenantId(1L)
                .name("蜂巢帘")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("299.00"))
                .description("隔热蜂巢帘")
                .mainImage("https://example.com/img.jpg")
                .images(List.of("https://example.com/img1.jpg", "https://example.com/img2.jpg"))
                .status("on_sale")
                .build();
    }

    // ======================== 分页查询测试 ========================

    @Test
    @DisplayName("商品列表查询 - 默认分页，无筛选条件")
    void getProducts_DefaultPagination() {
        // Given: 查询请求
        ProductQueryRequest query = new ProductQueryRequest();
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        when(productMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // When: 查询商品列表
        PageResponse<ProductResponse> result = productService.getProducts(query, 1L);

        // Then: 验证返回结果
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getName()).isEqualTo("蜂巢帘");
        assertThat(result.getItems().get(0).getCategoryName()).isEqualTo("窗帘");
    }

    @Test
    @DisplayName("商品列表查询 - 带关键词和分类筛选")
    void getProducts_WithFilters() {
        // Given: 带筛选条件的查询
        ProductQueryRequest query = new ProductQueryRequest();
        query.setKeyword("蜂巢");
        query.setCategoryId("cat-001");
        query.setStatus("on_sale");
        query.setPage(1L);
        query.setSize(10L);

        Page<Product> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        when(productMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // When: 查询商品列表
        PageResponse<ProductResponse> result = productService.getProducts(query, 1L);

        // Then: 验证返回结果
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(productMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("商品列表查询 - 空结果")
    void getProducts_EmptyResult() {
        // Given: 无匹配数据
        ProductQueryRequest query = new ProductQueryRequest();

        Page<Product> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(productMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // When
        PageResponse<ProductResponse> result = productService.getProducts(query, 1L);

        // Then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 商品详情测试 ========================

    @Test
    @DisplayName("查询商品详情 - 商品存在")
    void getProductById_Found() {
        // Given
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);

        // When
        ProductResponse result = productService.getProductById("prod-001", 1L);

        // Then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("蜂巢帘");
        assertThat(result.getCategoryName()).isEqualTo("窗帘");
        assertThat(result.getBasePrice()).isEqualByComparingTo(new BigDecimal("299.00"));
    }

    @Test
    @DisplayName("查询商品详情 - 商品不存在，抛出 BusinessException")
    void getProductById_NotFound() {
        // Given
        when(productMapper.selectById("nonexistent")).thenReturn(null);

        // When & Then
        assertThatThrownBy(() -> productService.getProductById("nonexistent", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                    assertThat(bex.getHttpStatus()).isEqualTo(404);
                });
    }

    // ======================== 创建商品测试 ========================

    @Test
    @DisplayName("创建商品成功")
    void createProduct_Success() {
        // Given
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("新商品");
        request.setCategoryId("cat-001");
        request.setBasePrice(new BigDecimal("199.00"));
        request.setDescription("新商品描述");
        request.setImages(List.of("https://example.com/new.jpg"));

        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(productMapper.insert(any(Product.class))).thenAnswer(invocation -> {
            Product p = invocation.getArgument(0);
            p.setId("prod-new");
            return 1;
        });
        // getProductById 调用
        Product savedProduct = Product.builder()
                .id("prod-new")
                .name("新商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("199.00"))
                .description("新商品描述")
                .images(List.of("https://example.com/new.jpg"))
                .status("off_sale")
                .build();
        when(productMapper.selectById("prod-new")).thenReturn(savedProduct);

        // When
        ProductResponse result = productService.createProduct(request, 1L);

        // Then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("新商品");
        verify(productMapper).insert(any(Product.class));
    }

    @Test
    @DisplayName("创建商品失败 - 分类不存在")
    void createProduct_CategoryNotFound() {
        // Given
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("新商品");
        request.setCategoryId("nonexistent-cat");
        request.setBasePrice(new BigDecimal("199.00"));

        when(categoryMapper.selectById("nonexistent-cat")).thenReturn(null);

        // When & Then
        assertThatThrownBy(() -> productService.createProduct(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("分类不存在");
    }

    // ======================== 更新商品测试 ========================

    @Test
    @DisplayName("更新商品成功")
    void updateProduct_Success() {
        // Given
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setName("更新后的商品");
        request.setCategoryId("cat-001");
        request.setBasePrice(new BigDecimal("399.00"));

        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        // getProductById 调用
        Product updatedProduct = Product.builder()
                .id("prod-001")
                .name("更新后的商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("399.00"))
                .build();
        // selectById 被调用两次：一次 updateProduct 内部验证，一次 getProductById
        when(productMapper.selectById("prod-001")).thenReturn(testProduct).thenReturn(updatedProduct);

        // When
        ProductResponse result = productService.updateProduct("prod-001", request, 1L);

        // Then
        assertThat(result).isNotNull();
        verify(productMapper).updateById(any(Product.class));
    }

    @Test
    @DisplayName("更新商品失败 - 商品不存在")
    void updateProduct_ProductNotFound() {
        // Given
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setName("更新");
        request.setCategoryId("cat-001");

        when(productMapper.selectById("nonexistent")).thenReturn(null);

        // When & Then
        assertThatThrownBy(() -> productService.updateProduct("nonexistent", request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 删除商品测试 ========================

    @Test
    @DisplayName("删除商品成功")
    void deleteProduct_Success() {
        // Given
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.deleteById("prod-001")).thenReturn(1);

        // When
        productService.deleteProduct("prod-001", 1L);

        // Then
        verify(productMapper).deleteById("prod-001");
    }

    @Test
    @DisplayName("删除商品失败 - 商品不存在")
    void deleteProduct_NotFound() {
        // Given
        when(productMapper.selectById("nonexistent")).thenReturn(null);

        // When & Then
        assertThatThrownBy(() -> productService.deleteProduct("nonexistent", 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 商品状态变更测试 ========================

    @Test
    @DisplayName("商品上架成功")
    void updateProductStatus_OnSale() {
        // Given
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        // When
        productService.updateProductStatus("prod-001", "on_sale", 1L);

        // Then
        verify(productMapper).updateById(argThat((Product p) -> "on_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("商品状态变更失败 - 无效状态值")
    void updateProductStatus_InvalidStatus() {
        // When & Then
        assertThatThrownBy(() -> productService.updateProductStatus("prod-001", "invalid_status", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("状态值无效");
    }
}
