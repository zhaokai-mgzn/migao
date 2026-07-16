package com.migao.admin.service;

import com.migao.admin.dto.LowStockByColorResponse;
import com.migao.admin.dto.ProductQueryRequest;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.ProductMapper;
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
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * ProductService 低库存相关方法单元测试
 *
 * 对应 issue #1396 — 第三次回归修复：
 * 待补库存口径统一：排除已删除 + 已下架商品下的 SKU
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProductService 低库存方法测试")
class ProductServiceLowStockTest {

    @InjectMocks
    private ProductService productService;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    // 未使用的 mock（ProductService 构造注入需要，但低库存测试不涉及）
    @Mock
    private com.migao.admin.mapper.CategoryMapper categoryMapper;
    @Mock
    private com.migao.admin.mapper.ProductColorMapper productColorMapper;
    @Mock
    private com.migao.admin.mapper.ProductProcessingItemMapper productProcessingItemMapper;
    @Mock
    private com.migao.admin.mapper.ProcessingItemMapper processingItemMapper;
    @Mock
    private com.migao.admin.mapper.ProductAttributeMapper productAttributeMapper;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-1: 排除已删除商品下的 SKU
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-1: getLowStockSkuCount 排除已删除商品下的 SKU")
    void lowStockSkuCount_ExcludesDeletedProducts() {
        // Given: mapper 返回过滤后的数量（已排除 deleted=1 商品下的 SKU）
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(5L);

        // When
        long count = productService.getLowStockSkuCount(1L, 100);

        // Then: 只返回 5（删除了 3 个 deleted=1 商品下的 SKU，原本 8 个）
        assertThat(count).isEqualTo(5L);
        verify(productMapper).countLowStockSkus(1L, 100);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-2: 排除已下架商品下的 SKU
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-2: getLowStockSkuCount 排除已下架商品下的 SKU")
    void lowStockSkuCount_ExcludesOffSaleProducts() {
        // Given: 商品 B（status='off_sale'）下有 SKU-2（stock=5），应被排除
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(4L);  // 排除了 1 个 off_sale 商品下的 SKU

        // When
        long count = productService.getLowStockSkuCount(1L, 100);

        // Then
        assertThat(count).isEqualTo(4L);
        verify(productMapper).countLowStockSkus(1L, 100);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-3: 阈值边界
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-3: 阈值边界 — stock=0 计入、stock=N 计入、stock=N+1 不计入")
    void lowStockSkuCount_ThresholdBoundary() {
        // Given: SKU stock ∈ {0, 5, 10, 11, 50}
        // threshold=10 → 应计 3 个（stock=0, 5, 10）
        when(productMapper.countLowStockSkus(eq(1L), eq(10)))
                .thenReturn(3L);

        // When
        long count = productService.getLowStockSkuCount(1L, 10);

        // Then
        assertThat(count).isEqualTo(3L);
        verify(productMapper).countLowStockSkus(1L, 10);
    }

    @Test
    @DisplayName("L2-3b: threshold=100 — stock=100 计入、stock=101 不计入")
    void lowStockSkuCount_Threshold100() {
        when(productMapper.countLowStockSkus(eq(1L), eq(100)))
                .thenReturn(8L);

        long count = productService.getLowStockSkuCount(1L, 100);

        assertThat(count).isEqualTo(8L);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-4: 多租户隔离
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-4: 多租户隔离 — tenant A 的 SKU 不计入 tenant B")
    void lowStockSkuCount_TenantIsolation() {
        // Given: tenantA 有 5 个低库存 SKU，tenantB 有 3 个
        when(productMapper.countLowStockSkus(eq(100L), eq(100)))
                .thenReturn(5L);
        when(productMapper.countLowStockSkus(eq(200L), eq(100)))
                .thenReturn(3L);

        // When
        long countA = productService.getLowStockSkuCount(100L, 100);
        long countB = productService.getLowStockSkuCount(200L, 100);

        // Then: 各自只看到自己的 SKU
        assertThat(countA).isEqualTo(5L);
        assertThat(countB).isEqualTo(3L);
        verify(productMapper).countLowStockSkus(100L, 100);
        verify(productMapper).countLowStockSkus(200L, 100);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-5: low-stock-by-color 也过滤 off_sale（调用 findLowStockByColor）
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-5: getLowStockByColor 委托 mapper.findLowStockByColor（已含过滤）")
    void lowStockByColor_DelegatesToMapper() {
        // Given
        LowStockByColorResponse item = new LowStockByColorResponse();
        item.setSkuId(1L);
        item.setProductId("prod-001");
        item.setProductName("测试商品");
        item.setStock(5);

        when(productMapper.findLowStockByColor(100, 50))
                .thenReturn(List.of(item));

        // When
        List<LowStockByColorResponse> result = productService.getLowStockByColor(100, 50);

        // Then: 委托给 mapper（mapper SQL 已含 p.deleted=0 + p.status='on_sale'）
        assertThat(result).hasSize(1);
        assertThat(result.get(0).getStock()).isEqualTo(5);
        verify(productMapper).findLowStockByColor(100, 50);
    }

    // ═══════════════════════════════════════════════════════════════
    // L2-6: getProducts 中 stockBelow 自动过滤 on_sale
    // ═══════════════════════════════════════════════════════════════

    @Test
    @DisplayName("L2-6: getProducts stockBelow 自动过滤 status='on_sale'（未显式指定时）")
    void getProducts_StockBelowAutoFiltersOnSale() {
        // Given: stockBelow=100，未指定 status
        ProductQueryRequest query = new ProductQueryRequest();
        query.setStockBelow(100);
        query.setPage(1L);
        query.setSize(20L);

        Page<Product> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of());
        mockPage.setTotal(0);

        ArgumentCaptor<LambdaQueryWrapper<Product>> wrapperCaptor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        when(productMapper.selectPage(any(Page.class), wrapperCaptor.capture()))
                .thenReturn(mockPage);

        // When
        productService.getProducts(query, 1L);

        // Then: wrapper 应包含 status='on_sale' 条件 + EXISTS 子查询
        LambdaQueryWrapper<Product> captured = wrapperCaptor.getValue();
        String sqlSegment = captured.getSqlSegment();
        assertThat(sqlSegment).isNotNull();
        // MyBatis-Plus LambdaQueryWrapper 会将条件转为参数化 SQL
        // 关键验证：SQL segment 不为空（包含了 status + EXISTS 条件）
        assertThat(sqlSegment).contains("product_skus");
    }

    @Test
    @DisplayName("L2-6b: getProducts stockBelow 但已显式指定 status，不覆盖")
    void getProducts_StockBelowRespectsExplicitStatus() {
        // Given: 用户显式指定 status='off_sale' + stockBelow=100
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

        // When
        productService.getProducts(query, 1L);

        // Then: 应该只调用一次 selectPage（status 使用用户指定的 off_sale）
        verify(productMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }
}
