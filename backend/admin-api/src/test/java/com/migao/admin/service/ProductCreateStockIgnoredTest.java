// case_ids: PR-132
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.ProductSkuInput;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 商品档案不再设置库存数值 —— 建品侧的行为判据（issue #7597，用户裁定 2026-10-24）。
 *
 * ## 被钉住的行为（三条，每条都会红）
 * ① 建品请求带 `stock=500` ⇒ 落库的 `products.stock` 是 **0**（改前：500 原样落库）；
 * ② 建品请求带 `skus[].stock=300` ⇒ 落库的 `product_skus.stock` 是 **0**（改前：300）；
 *    含笛卡尔积自动生成 SKU 那条路径（改前未给库存时**默认 100**，见 {@code saveColorsAndSkus}）——
 *    本文件第二条用例守它；
 * ③ 既然初始库存恒 0 ⇒ **不得**再落「新 SKU 初始库存（基线行）」的 `manual` 台账
 *    （0 变更落行 = 台账噪声，且意味着库存是「建档建立的」而不是「真实单据产生的」）。
 *
 * ## 边界（如实登记）
 * 本文件只裁**建品**；改品库存（批量库存调整 / Agent 调整走的同一条分支）仍在射程内并由
 * {@code ProductStockNonNegativeGateTest} 承担。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商品档案不再建立库存（issue #7597）")
class ProductCreateStockIgnoredTest {

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
    private ProductAttributeMapper productAttributeMapper;
    @Mock
    private StockLedgerService stockLedgerService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductColor.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Category.class);
        TenantContext.setTenantId(1L);

        // 建品成功的**最小桩集**：insert 时补主键（真实 MyBatis 会回填），回读返回同一行
        when(productMapper.insert(any(Product.class))).thenAnswer(invocation -> {
            invocation.getArgument(0, Product.class).setId("prod-7597");
            return 1;
        });
        Product saved = new Product();
        saved.setId("prod-7597");
        saved.setTenantId(1L);
        saved.setName("库存探针");
        saved.setSkuCode("PJ-7597");
        saved.setStatus("draft");
        saved.setBasePrice(new BigDecimal("199.00"));
        saved.setStock(BigDecimal.ZERO);
        when(productMapper.selectById("prod-7597")).thenReturn(saved);
        when(productColorMapper.selectList(any())).thenReturn(List.of());
        when(productSkuMapper.selectList(any())).thenReturn(List.of());
        when(stockLedgerService.snapshotSkus(any())).thenReturn(Map.of());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("判据1/3：stock=500 + skus[].stock=300 ⇒ 落库全 0，且不落「建品基线」台账")
    void createIgnoresRequestStockAndSkuStock() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("库存探针");
        request.setSkuCode("PJ-7597");
        request.setBasePrice(new BigDecimal("199.00"));
        request.setStock(new BigDecimal("500"));

        ProductColorInput color = new ProductColorInput();
        color.setColorName("米白");
        request.setColors(List.of(color));
        request.setDoorWidths(List.of("2.8"));

        ProductSkuInput sku = new ProductSkuInput();
        sku.setColorName("米白");
        sku.setDoorWidth("2.8");
        sku.setPrice(new BigDecimal("199.00"));
        sku.setStock(new BigDecimal("300"));
        request.setSkus(List.of(sku));

        ProductResponse response = productService.createProduct(request, 1L);

        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productMapper).insert(productCaptor.capture());
        assertThat(productCaptor.getValue().getStock())
                .as("建品请求里的 stock 必须被忽略（新商品从 0 起算）")
                .isEqualByComparingTo(BigDecimal.ZERO);

        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper).insert(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getStock())
                .as("建品请求里的 skus[].stock 必须被忽略（库存只由真实单据产生）")
                .isEqualByComparingTo(BigDecimal.ZERO);

        // 0 变更不落账 ⇒「新 SKU 初始库存（基线行）」不应出现
        verify(stockLedgerService, never())
                .record(any(), any(), any(), any(), any(), any(), any(), any(), any());

        assertThat(response.getStock())
                .as("响应里的库存 = SKU 汇总（= 0）；调用方读回即可见「没有建立库存」")
                .isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    @DisplayName("判据2（笛卡尔积路径）：只给 colors × doorWidths ⇒ 自动生成的 SKU 库存 0（改前默认 100）")
    void autoGeneratedSkusStartFromZero() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("矩阵探针");
        request.setSkuCode("PJ-MATRIX");
        request.setBasePrice(new BigDecimal("88.00"));
        request.setStock(new BigDecimal("500"));

        ProductColorInput color = new ProductColorInput();
        color.setColorName("浅灰");
        request.setColors(List.of(color));
        request.setDoorWidths(List.of("2.8", "3.2"));
        // 刻意不给 skus ⇒ 走 saveColorsAndSkus 的笛卡尔积自动生成分支
        productService.createProduct(request, 1L);

        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper, org.mockito.Mockito.times(2)).insert(skuCaptor.capture());
        assertThat(skuCaptor.getAllValues())
                .as("自动生成的每个 SKU 都从 0 起算（issue #7597 删除了「默认 100」）")
                .allSatisfy(s -> assertThat(s.getStock()).isEqualByComparingTo(BigDecimal.ZERO));
    }
}
