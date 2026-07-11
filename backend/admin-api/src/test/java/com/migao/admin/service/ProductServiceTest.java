package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductProcessingItemMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import org.mockito.ArgumentCaptor;
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

    @Mock
    private ProductColorMapper productColorMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    @Mock
    private ProductProcessingItemMapper productProcessingItemMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private ProductAttributeMapper productAttributeMapper;

    private Product testProduct;
    private Category testCategory;

    @BeforeEach
    void setUp() {
        // Initialize MyBatis-Plus table info for LambdaQueryWrapper resolution in unit tests
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductColor.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Category.class);

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
        when(productColorMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(Collections.emptyList());

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
    @DisplayName("SKU编码生成 - 优先使用商品货号作为前缀")
    void generateSkuCode_UsesProductSkuCodePrefix() {
        // Given: 商品有货号 "2699"，配置颜色/售卖方式/门幅
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("测试商品");
        request.setCategoryId("cat-001");
        request.setBasePrice(new BigDecimal("68.00"));
        request.setStock(100);
        request.setSkuCode("2699"); // 货号
        ProductColorInput c1 = new ProductColorInput();
        c1.setColorName("黑色");
        ProductColorInput c2 = new ProductColorInput();
        c2.setColorName("灰色");
        request.setColors(List.of(c1, c2));
        request.setSellingMethods(List.of("bulk_cut", "full_roll"));
        request.setDoorWidths(List.of("2.8米", "3.2米"));

        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        when(productMapper.insert(productCaptor.capture())).thenAnswer(invocation -> {
            Product p = invocation.getArgument(0);
            p.setId("prod-sku-test");
            return 1;
        });
        // getProductById 兜底查询
        Product savedProduct = Product.builder()
                .id("prod-sku-test")
                .name("测试商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("68.00"))
                .skuCode("2699")
                .build();
        when(productMapper.selectById("prod-sku-test")).thenReturn(savedProduct);

        // When
        productService.createProduct(request, 1L);

        // Verify product.skuCode was set from request
        Product capturedProduct = productCaptor.getValue();
        assertThat(capturedProduct.getSkuCode()).isEqualTo("2699");

        // Then: 验证 SKU 插入时 skuCode 以货号 "2699" 为前缀
        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper, atLeastOnce()).insert(skuCaptor.capture());
        assertThat(skuCaptor.getAllValues()).allMatch(sku ->
                sku.getSkuCode() != null && sku.getSkuCode().startsWith("2699-"));
    }

    @Test
    @DisplayName("SKU编码生成 - 无货号时兜底用商品ID前缀")
    void generateSkuCode_FallbackToProductIdPrefix() {
        // Given: 商品无货号
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("无货号商品");
        request.setCategoryId("cat-001");
        request.setBasePrice(new BigDecimal("50.00"));
        request.setStock(50);
        // skuCode 不设置
        ProductColorInput c1 = new ProductColorInput();
        c1.setColorName("红色");
        request.setColors(List.of(c1));
        request.setSellingMethods(List.of("bulk_cut"));
        request.setDoorWidths(List.of("2.8米"));

        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(productMapper.insert(any(Product.class))).thenAnswer(invocation -> {
            Product p = invocation.getArgument(0);
            p.setId("prod-no-sku-code-test");
            return 1;
        });
        Product savedProduct = Product.builder()
                .id("prod-no-sku-code-test")
                .name("无货号商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("50.00"))
                .build();
        when(productMapper.selectById("prod-no-sku-code-test")).thenReturn(savedProduct);

        // When
        productService.createProduct(request, 1L);

        // Then: 验证 SKU 插入时 skuCode 以商品ID前缀为前缀
        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper, atLeastOnce()).insert(skuCaptor.capture());
        assertThat(skuCaptor.getAllValues()).allMatch(sku ->
                sku.getSkuCode() != null && sku.getSkuCode().startsWith("PROD-NO-"));
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
    @DisplayName("商品下架成功 - on_sale → off_sale")
    void updateProductStatus_OffShelf() {
        // Given: 商品当前状态为 on_sale
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        // When: 合法流转 on_sale → off_sale
        productService.updateProductStatus("prod-001", "off_sale", 1L);

        // Then
        verify(productMapper).updateById(argThat((Product p) -> "off_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("商品重新上架成功 - off_sale → on_sale")
    void updateProductStatus_OnShelf_FromOffSale() {
        // Given: 商品当前状态为 off_sale
        Product offSaleProduct = Product.builder()
                .id("prod-002")
                .tenantId(1L)
                .name("已下架商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("199.00"))
                .status("off_sale")
                .build();
        when(productMapper.selectById("prod-002")).thenReturn(offSaleProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        // When: 合法流转 off_sale → on_sale
        productService.updateProductStatus("prod-002", "on_sale", 1L);

        // Then
        verify(productMapper).updateById(argThat((Product p) -> "on_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("草稿直接上架 - draft → on_sale")
    void updateProductStatus_DraftToOnSale() {
        // Given: 商品当前状态为 draft
        Product draftProduct = Product.builder()
                .id("prod-003")
                .tenantId(1L)
                .name("草稿商品")
                .categoryId("cat-001")
                .basePrice(new BigDecimal("99.00"))
                .status("draft")
                .build();
        when(productMapper.selectById("prod-003")).thenReturn(draftProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        // When: 合法流转 draft → on_sale
        productService.updateProductStatus("prod-003", "on_sale", 1L);

        // Then
        verify(productMapper).updateById(argThat((Product p) -> "on_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("in_warehouse 已废弃 — 任何状态流转到 in_warehouse 均抛异常")
    void updateProductStatus_InWarehouseIsRejected() {
        // Given: 商品当前状态为 on_sale
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        // When & Then: in_warehouse 已废弃，不能作为目标状态
        assertThatThrownBy(() -> productService.updateProductStatus("prod-001", "in_warehouse", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("状态流转无效");
    }

    @Test
    @DisplayName("商品状态变更失败 - 无效状态值")
    void updateProductStatus_InvalidStatus() {
        // Given: mock商品存在，当前状态为 on_sale
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        // When & Then: on_sale 不能流转到 invalid_status
        assertThatThrownBy(() -> productService.updateProductStatus("prod-001", "invalid_status", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("状态流转无效");
    }

    // ═══════════════════════════════════════════════════════════
    // getLowStockByColor 测试（#316 库存告警按颜色维度）
    // ═══════════════════════════════════════════════════════════

    @Test
    @DisplayName("低库存查询(颜色维度) - 有结果")
    void getLowStockByColor_HasResults() {
        List<LowStockByColorResponse> mockResult = List.of(
            new LowStockByColorResponse(1L, "prod-001", "遮光窗帘", "8827-2",
                100L, "红色", "2.8m", 5, new BigDecimal("8.80"))
        );
        when(productMapper.findLowStockByColor(100, 50)).thenReturn(mockResult);

        List<LowStockByColorResponse> result = productService.getLowStockByColor(100, 50);

        assertThat(result).hasSize(1);
        assertThat(result.get(0).getProductName()).isEqualTo("遮光窗帘");
        assertThat(result.get(0).getColorName()).isEqualTo("红色");
        assertThat(result.get(0).getStock()).isEqualTo(5);
    }

    @Test
    @DisplayName("低库存查询(颜色维度) - 无低库存 SKU")
    void getLowStockByColor_Empty() {
        when(productMapper.findLowStockByColor(100, 50)).thenReturn(Collections.emptyList());

        List<LowStockByColorResponse> result = productService.getLowStockByColor(100, 50);

        assertThat(result).isEmpty();
    }

    // ═══════════════════════════════════════════════════════════
    // 批量操作测试
    // ═══════════════════════════════════════════════════════════

    @Test
    @DisplayName("批量上架 - off_sale 状态可上架")
    void batchOnShelf_AllSuccess() {
        Product offSaleProduct = Product.builder()
                .id("prod-off")
                .tenantId(1L)
                .name("已下架商品")
                .status("off_sale")
                .build();
        when(productMapper.selectById("prod-off")).thenReturn(offSaleProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        BatchOperationResult result = productService.batchOnShelf(List.of("prod-off"), 1L);

        assertThat(result.getSuccess()).isEqualTo(1);
        assertThat(result.getFailed()).isEqualTo(0);
        verify(productMapper).updateById(argThat((Product p) -> "on_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("批量上架 - 空列表直接返回")
    void batchOnShelf_EmptyList() {
        BatchOperationResult result = productService.batchOnShelf(List.of(), 1L);

        assertThat(result.getSuccess()).isEqualTo(0);
        assertThat(result.getFailed()).isEqualTo(0);
    }

    @Test
    @DisplayName("批量上架 - on_sale 状态不允许再上架")
    void batchOnShelf_InvalidStatus() {
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        BatchOperationResult result = productService.batchOnShelf(List.of("prod-001"), 1L);

        assertThat(result.getFailed()).isEqualTo(1);
        assertThat(result.getErrors().get(0).getMessage()).contains("不允许上架");
    }

    @Test
    @DisplayName("批量下架 - on_sale 状态可下架")
    void batchOffShelf_AllSuccess() {
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        BatchOperationResult result = productService.batchOffShelf(List.of("prod-001"), 1L);

        assertThat(result.getSuccess()).isEqualTo(1);
        assertThat(result.getFailed()).isEqualTo(0);
        verify(productMapper).updateById(argThat((Product p) -> "off_sale".equals(p.getStatus())));
    }

    @Test
    @DisplayName("批量删除 - draft 状态可删除")
    void batchDelete_DraftAllowed() {
        Product draftProduct = Product.builder()
                .id("prod-draft")
                .tenantId(1L)
                .status("draft")
                .build();
        when(productMapper.selectById("prod-draft")).thenReturn(draftProduct);
        when(productMapper.deleteById("prod-draft")).thenReturn(1);

        BatchOperationResult result = productService.batchDelete(List.of("prod-draft"), 1L);

        assertThat(result.getSuccess()).isEqualTo(1);
        assertThat(result.getFailed()).isEqualTo(0);
        verify(productMapper).deleteById("prod-draft");
    }

    @Test
    @DisplayName("批量删除 - on_sale 状态不可删除")
    void batchDelete_OnSaleNotAllowed() {
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        BatchOperationResult result = productService.batchDelete(List.of("prod-001"), 1L);

        assertThat(result.getFailed()).isEqualTo(1);
        assertThat(result.getErrors().get(0).getMessage()).contains("不允许删除");
        verify(productMapper, never()).deleteById(anyString());
    }

    // ═══════════════════════════════════════════════════════════
    // #1201 库存排序修复: ORDER BY 改用 SKU 汇总子查询
    // ═══════════════════════════════════════════════════════════

    @Test
    @DisplayName("#1201: sortBy=stock ASC → wrapper.last() 使用 SKU 汇总子查询排序")
    void getProducts_SortByStockAsc_UsesSkuSumSubquery() {
        // Given
        ProductQueryRequest query = new ProductQueryRequest();
        query.setSortBy("stock");
        query.setSortOrder("asc");
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        ArgumentCaptor<LambdaQueryWrapper<Product>> wrapperCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(productMapper.selectPage(any(Page.class), wrapperCaptor.capture()))
                .thenReturn(mockPage);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // When
        productService.getProducts(query, 1L);

        // Then: 验证 wrapper.last() 包含 SKU 汇总子查询并指定 ASC
        LambdaQueryWrapper<Product> capturedWrapper = wrapperCaptor.getValue();
        String customSql = capturedWrapper.getCustomSqlSegment();
        assertThat(customSql)
                .as("wrapper.last() 应包含 SKU 汇总子查询排序")
                .contains("COALESCE(SUM(ps.stock)");
        assertThat(customSql)
                .as("sortOrder=asc 时子查询应为 ASC")
                .contains("ASC");
    }

    @Test
    @DisplayName("#1201: sortBy=stock DESC → wrapper.last() 使用 SKU 汇总子查询排序")
    void getProducts_SortByStockDesc_UsesSkuSumSubquery() {
        // Given
        ProductQueryRequest query = new ProductQueryRequest();
        query.setSortBy("stock");
        query.setSortOrder("desc");
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        ArgumentCaptor<LambdaQueryWrapper<Product>> wrapperCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(productMapper.selectPage(any(Page.class), wrapperCaptor.capture()))
                .thenReturn(mockPage);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // When
        productService.getProducts(query, 1L);

        // Then
        LambdaQueryWrapper<Product> capturedWrapper = wrapperCaptor.getValue();
        String customSql = capturedWrapper.getCustomSqlSegment();
        assertThat(customSql)
                .as("wrapper.last() 应包含 SKU 汇总子查询排序")
                .contains("COALESCE(SUM(ps.stock)");
        assertThat(customSql)
                .as("sortOrder=desc 时子查询应为 DESC")
                .contains("DESC");
    }

    @Test
    @DisplayName("#1201: sortBy=stock 时排序键是 SKU 汇总值而非 products.stock")
    void getProducts_SortByStock_DoesNotUseProductStockColumn() {
        // Given
        ProductQueryRequest query = new ProductQueryRequest();
        query.setSortBy("stock");
        query.setSortOrder("asc");

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        ArgumentCaptor<LambdaQueryWrapper<Product>> wrapperCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(productMapper.selectPage(any(Page.class), wrapperCaptor.capture()))
                .thenReturn(mockPage);
        when(categoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // When
        productService.getProducts(query, 1L);

        // Then: 不应使用 product.stock 列做排序（这是 Bug 的根因）
        LambdaQueryWrapper<Product> capturedWrapper = wrapperCaptor.getValue();
        String sqlSegment = capturedWrapper.getSqlSegment();
        // 确认 SQL 片段中不含对 products.stock 列的直接 ORDER BY
        assertThat(sqlSegment)
                .as("不应包含对 products.stock 列的直接排序引用")
                .doesNotContainPattern("(?i)order\\s+by\\s+stock\\s+(asc|desc)");
    }

    @Test
    @DisplayName("#1201: sortBy 未指定时默认按 createdAt 降序")
    void getProducts_DefaultSort_ByCreatedAtDesc() {
        // Given
        ProductQueryRequest query = new ProductQueryRequest();
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testProduct));
        mockPage.setTotal(1);

        when(productMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // When
        productService.getProducts(query, 1L);

        // Then: 默认排序应正常工作
        verify(productMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }
}
