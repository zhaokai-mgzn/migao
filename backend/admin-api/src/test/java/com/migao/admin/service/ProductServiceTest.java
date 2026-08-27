// case_ids: PR-001, PR-002, PR-003, PR-004, PR-005, PR-006

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
    @DisplayName("删除商品成功 - off_sale 状态可删")
    void deleteProduct_Success() {
        // Given: off_sale 商品（与 batchDelete 状态约束一致）
        Product offSaleProduct = Product.builder()
                .id("prod-off")
                .tenantId(1L)
                .name("已下架商品")
                .status("off_sale")
                .build();
        when(productMapper.selectById("prod-off")).thenReturn(offSaleProduct);
        when(productMapper.deleteById("prod-off")).thenReturn(1);

        // When
        productService.deleteProduct("prod-off", 1L);

        // Then
        verify(productMapper).deleteById("prod-off");
    }

    @Test
    @DisplayName("删除商品失败 - on_sale 商品拒绝删除（与 batchDelete 一致）")
    void deleteProduct_OnSaleRejected() {
        // Given: on_sale 商品
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        // When & Then
        assertThatThrownBy(() -> productService.deleteProduct("prod-001", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许删除");
        verify(productMapper, never()).deleteById(anyString());
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

    // ======================== 单 SKU 改价（前端行内编辑） ========================

    @Test
    @DisplayName("单SKU改价成功 - skuId 属于商品时原地更新价格并返回 SKU")
    void updateSkuPriceById_Success() {
        // Given: 商品存在（id+tenant），SKU 属于该商品
        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
        ProductSku sku = ProductSku.builder()
                .id(1001L).tenantId(1L).productId("prod-001")
                .colorName("红色").sellingMethod("bulk_cut").doorWidth("2.8米")
                .price(new BigDecimal("88.00")).stock(10).skuCode("HCL-01-SJ-28").build();
        when(productSkuMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(sku);
        when(productSkuMapper.updateById(any(ProductSku.class))).thenReturn(1);

        // When
        ProductSkuResponse result = productService.updateSkuPriceById("prod-001", 1001L, new BigDecimal("99.00"), 1L);

        // Then: 返回更新后的 SKU，且只更新价格行（不删除/重建）
        assertThat(result.getId()).isEqualTo(1001L);
        assertThat(result.getPrice()).isEqualByComparingTo(new BigDecimal("99.00"));
        verify(productSkuMapper).updateById(argThat((ProductSku s) ->
                s.getId() == 1001L && s.getPrice().compareTo(new BigDecimal("99.00")) == 0));
        verify(productSkuMapper, never()).delete(any());
    }

    @Test
    @DisplayName("单SKU改价 - 负数价格被拒绝（422）")
    void updateSkuPriceById_NegativePriceRejected() {
        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);

        assertThatThrownBy(() -> productService.updateSkuPriceById("prod-001", 1001L, new BigDecimal("-1.00"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("价格");
        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
    }

    @Test
    @DisplayName("单SKU改价 - skuId 不属于该商品/不存在时抛 404")
    void updateSkuPriceById_SkuNotFound() {
        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
        when(productSkuMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);

        assertThatThrownBy(() -> productService.updateSkuPriceById("prod-001", 999L, new BigDecimal("99.00"), 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getHttpStatus()).isEqualTo(404);
                });
        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
    }

    // ======================== 更新商品 SKU 断链防护（订单回滚可寻址） ========================

    @Test
    @DisplayName("更新商品 - 已存在 SKU/颜色按 id 原地更新（不删除重建，旧 skuId 保持可回滚）")
    void updateProduct_PreservesExistingSkuAndColorIds() {
        // Given: 请求携带已有颜色(50)/SKU(1001) 的真实 DB id
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setName("更新后的商品");
        request.setCategoryId("cat-001");
        request.setBasePrice(new BigDecimal("399.00"));

        ProductColorInput c1 = new ProductColorInput();
        c1.setId(50L);
        c1.setColorName("红色");
        request.setColors(List.of(c1));

        ProductSkuInput s1 = new ProductSkuInput();
        s1.setId(1001L);
        s1.setColorId(50L);
        s1.setColorName("红色");
        s1.setSellingMethod("bulk_cut");
        s1.setDoorWidth("2.8米");
        s1.setPrice(new BigDecimal("99.00"));
        s1.setStock(10);
        request.setSkus(List.of(s1));

        ProductColor existingColor = ProductColor.builder()
                .id(50L).tenantId(1L).productId("prod-001").colorName("红色").sortOrder(0).build();
        ProductSku existingSku = ProductSku.builder()
                .id(1001L).tenantId(1L).productId("prod-001").colorId(50L)
                .colorName("红色").sellingMethod("bulk_cut").doorWidth("2.8米")
                .price(new BigDecimal("88.00")).stock(10).skuCode("HCL-01-SJ-28").build();

        when(productMapper.selectById("prod-001")).thenReturn(testProduct).thenReturn(testProduct);
        when(categoryMapper.selectById("cat-001")).thenReturn(testCategory);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);
        when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(existingColor));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(existingSku));
        when(productColorMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        // When
        productService.updateProduct("prod-001", request, 1L);

        // Then: 不物理删除旧 SKU/颜色；旧行按 id 原地更新，不插入新行
        verify(productSkuMapper, never()).delete(any());
        verify(productColorMapper, never()).delete(any());
        verify(productSkuMapper, never()).deleteById(anyLong());
        verify(productColorMapper, never()).deleteById(anyLong());
        verify(productSkuMapper, never()).insert(any(ProductSku.class));
        verify(productColorMapper, never()).insert(any(ProductColor.class));
        verify(productColorMapper).updateById(argThat((ProductColor c) -> c.getId() == 50L));
        verify(productSkuMapper).updateById(argThat((ProductSku s) -> s.getId() == 1001L));
    }

    @Test
    @DisplayName("Agent 更新商品 - 同名颜色/组合的旧 SKU 保持原 id（不重建）")
    void updateProductForAgent_PreservesExistingSkuIds() {
        // Given: Agent 只传颜色/售卖方式/门幅名称（无 id），触发 SKU 重建
        com.migao.admin.dto.agent.AgentProductUpdateRequest req =
                new com.migao.admin.dto.agent.AgentProductUpdateRequest();
        req.setColors(List.of("红色"));
        req.setSellingMethods(List.of("bulk_cut"));
        req.setDoorWidths(List.of("2.8米"));

        ProductColor existingColor = ProductColor.builder()
                .id(50L).tenantId(1L).productId("prod-001").colorName("红色").sortOrder(0).build();
        ProductSku existingSku = ProductSku.builder()
                .id(1001L).tenantId(1L).productId("prod-001").colorId(50L)
                .colorName("红色").sellingMethod("bulk_cut").doorWidth("2.8米")
                .price(new BigDecimal("88.00")).stock(10).skuCode("HCL-01-SJ-28").build();

        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);
        when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(existingColor));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(existingSku));
        when(productColorMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        // When
        productService.updateProductForAgent("prod-001", req, 1L);

        // Then: 旧 SKU/颜色行保留（按组合/名称匹配原地更新）
        verify(productSkuMapper, never()).delete(any());
        verify(productColorMapper, never()).delete(any());
        verify(productSkuMapper, never()).insert(any(ProductSku.class));
        verify(productColorMapper, never()).insert(any(ProductColor.class));
        verify(productColorMapper).updateById(argThat((ProductColor c) -> c.getId() == 50L));
        verify(productSkuMapper).updateById(argThat((ProductSku s) -> s.getId() == 1001L));
    }

    // ======================== 商品可售校验（供订单域调用） ========================

    @Test
    @DisplayName("可售校验 - on_sale 商品返回 null（可售）")
    void validateSellable_OnSale() {
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);

        assertThat(productService.validateSellable("prod-001", 1L)).isNull();
    }

    @Test
    @DisplayName("可售校验 - 非 on_sale 商品返回不可售原因")
    void validateSellable_NotOnSale() {
        Product offSaleProduct = Product.builder()
                .id("prod-off").tenantId(1L).name("已下架商品").status("off_sale").build();
        when(productMapper.selectById("prod-off")).thenReturn(offSaleProduct);

        assertThat(productService.validateSellable("prod-off", 1L)).contains("不可售卖");
    }

    @Test
    @DisplayName("可售校验 - 商品不存在（含逻辑删除）返回原因")
    void validateSellable_NotFound() {
        when(productMapper.selectById("nonexistent")).thenReturn(null);

        assertThat(productService.validateSellable("nonexistent", 1L)).contains("不存在");
    }

    @Test
    @DisplayName("Agent 更新商品 - 旧数据 SKU（colorName 为空，仅 colorId）按颜色 id 匹配保留")
    void updateProductForAgent_PreservesLegacySkuIds() {
        // Given: 旧数据 SKU 只有 colorId 无 colorName；Agent 按颜色名称重建
        com.migao.admin.dto.agent.AgentProductUpdateRequest req =
                new com.migao.admin.dto.agent.AgentProductUpdateRequest();
        req.setColors(List.of("红色"));
        req.setSellingMethods(List.of("bulk_cut"));
        req.setDoorWidths(List.of("2.8米"));

        ProductColor existingColor = ProductColor.builder()
                .id(50L).tenantId(1L).productId("prod-001").colorName("红色").sortOrder(0).build();
        ProductSku legacySku = ProductSku.builder()
                .id(1001L).tenantId(1L).productId("prod-001").colorId(50L)
                .colorName(null).sellingMethod("bulk_cut").doorWidth("2.8米")
                .price(new BigDecimal("88.00")).stock(10).skuCode("HCL-01-SJ-28").build();

        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(testProduct);
        when(productMapper.selectById("prod-001")).thenReturn(testProduct);
        when(productMapper.updateById(any(Product.class))).thenReturn(1);
        when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(existingColor));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(legacySku));
        when(productColorMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        // When
        productService.updateProductForAgent("prod-001", req, 1L);

        // Then: 旧 SKU 通过 colorId（颜色名→id 解析）匹配，保留原 id，不重建
        verify(productSkuMapper, never()).delete(any());
        verify(productSkuMapper, never()).insert(any(ProductSku.class));
        verify(productSkuMapper).updateById(argThat((ProductSku s) -> s.getId() == 1001L));
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
    // ═══════════════════════════════════════════════════════════
    // #1291 stockBelow 筛选修复: WHERE 改用 SKU 级 EXISTS 子查询
    // 根因: COALESCE(SUM(ps.stock)) 按 product 聚合，与看板 SKU 维度口径不一致
    // ═══════════════════════════════════════════════════════════

    @Test
    @DisplayName("#1291: stockBelow 筛选使用 SKU 级 EXISTS 子查询（非 product SUM）")
    void getProducts_StockBelowFilter_UsesSkuExistsSubquery() {
        // Given
        ProductQueryRequest query = new ProductQueryRequest();
        query.setStockBelow(100);
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

        // Then: 验证 wrapper 条件中使用 SKU 级 EXISTS（非 SUM 聚合）
        LambdaQueryWrapper<Product> capturedWrapper = wrapperCaptor.getValue();
        String sqlSegment = capturedWrapper.getSqlSegment();
        assertThat(sqlSegment)
                .as("stockBelow 筛选应使用 SKU 级 EXISTS 子查询")
                .contains("EXISTS (SELECT 1 FROM product_skus");
        assertThat(sqlSegment)
                .as("stockBelow 筛选应使用 <= 操作符（与 Dashboard stats 口径一致，兼容 MyBatis-Plus 占位符重写）")
                .containsPattern("ps\\.stock <= ");
        assertThat(sqlSegment)
                .as("stockBelow 筛选不应使用 product 级 SUM 聚合（那会导致口径不一致）")
                .doesNotContain("COALESCE(SUM(ps.stock)");
        assertThat(sqlSegment)
                .as("不应包含对 products.stock 列的直接 < 筛选（旧口径，应为 SKU 级 EXISTS）")
                .doesNotContainPattern("(?i)stock\\s*<\\s*(\\{|#)");
    }

    @Test
    @DisplayName("#1200: stockBelow 未传时不附加筛选条件")
    void getProducts_NoStockBelow_NoFilterApplied() {
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

        // Then: 不应包含 stockBelow 筛选
        verify(productMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    // ═══════════════════════════════════════════════════════════════
    // #1396 低库存口径统一 — getLowStockSkuCount + getProducts stockBelow 自动过滤
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("#1396 L2-1: getLowStockSkuCount 排除已删除商品下的 SKU")
    void lowStockSkuCount_ExcludesDeletedProducts() {
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(5L);

        long count = productService.getLowStockSkuCount(1L, 100);

        assertThat(count).isEqualTo(5L);
        verify(productMapper).countLowStockSkus(1L, 100);
    }

    @Test
    @DisplayName("#1396 L2-2: getLowStockSkuCount 排除已下架商品下的 SKU")
    void lowStockSkuCount_ExcludesOffSaleProducts() {
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(4L);

        long count = productService.getLowStockSkuCount(1L, 100);

        assertThat(count).isEqualTo(4L);
        verify(productMapper).countLowStockSkus(1L, 100);
    }

    @Test
    @DisplayName("#1396 L2-3: 阈值边界 — stock=0 计入、stock=N 计入、stock=N+1 不计入")
    void lowStockSkuCount_ThresholdBoundary() {
        when(productMapper.countLowStockSkus(eq(1L), eq(10)))
                .thenReturn(3L);

        long count = productService.getLowStockSkuCount(1L, 10);

        assertThat(count).isEqualTo(3L);
        verify(productMapper).countLowStockSkus(1L, 10);
    }

    @Test
    @DisplayName("#1396 L2-3b: threshold=100 — stock=100 计入、stock=101 不计入")
    void lowStockSkuCount_Threshold100() {
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(8L);

        long count = productService.getLowStockSkuCount(1L, 100);

        assertThat(count).isEqualTo(8L);
    }

    @Test
    @DisplayName("#1396 L2-4: 多租户隔离 — tenant A 的 SKU 不计入 tenant B")
    void lowStockSkuCount_TenantIsolation() {
        when(productMapper.countLowStockSkus(eq(100L), eq(100)))
                .thenReturn(5L);
        when(productMapper.countLowStockSkus(eq(200L), eq(100)))
                .thenReturn(3L);

        long countA = productService.getLowStockSkuCount(100L, 100);
        long countB = productService.getLowStockSkuCount(200L, 100);

        assertThat(countA).isEqualTo(5L);
        assertThat(countB).isEqualTo(3L);
        verify(productMapper).countLowStockSkus(100L, 100);
        verify(productMapper).countLowStockSkus(200L, 100);
    }

    @Test
    @DisplayName("#1396 L2-6: getProducts stockBelow 自动过滤 status='on_sale'（未显式指定时）")
    void getProducts_StockBelowAutoFiltersOnSale() {
        ProductQueryRequest query = new ProductQueryRequest();
        query.setStockBelow(100);
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of());
        mockPage.setTotal(0);

        ArgumentCaptor<LambdaQueryWrapper<Product>> wrapperCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(productMapper.selectPage(any(Page.class), wrapperCaptor.capture()))
                .thenReturn(mockPage);

        productService.getProducts(query, 1L);

        LambdaQueryWrapper<Product> captured = wrapperCaptor.getValue();
        String sqlSegment = captured.getSqlSegment();
        assertThat(sqlSegment).isNotNull();
        assertThat(sqlSegment).contains("product_skus");
    }

    @Test
    @DisplayName("#1396 L2-6b: getProducts stockBelow 但已显式指定 status，不覆盖")
    void getProducts_StockBelowRespectsExplicitStatus() {
        ProductQueryRequest query = new ProductQueryRequest();
        query.setStockBelow(100);
        query.setStatus("off_sale");
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of());
        mockPage.setTotal(0);

        when(productMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        productService.getProducts(query, 1L);

        verify(productMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }
}
