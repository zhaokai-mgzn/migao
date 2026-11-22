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
import com.migao.admin.exception.BusinessException;
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
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 商品档案不再设置库存数值 —— 建品侧的行为判据（issue #7597，用户裁定 2026-10-24）。
 *
 * <h2>🔴 issue #9006（P2，2026-11-22 生产冒烟）后的口径变更</h2>
 * 改前：建品带 {@code stock: 100} ⇒ **200 创建成功、落库 0**，调用方以为设上了初始库存
 * （「静默偏差」，只读 SQL 实测 {@code select stock from products} ⇒ {@code 0.0}）。
 * 改后：**非 0 库存 ⇒ 422 显式拒绝**（判据 1）。库存口径本身**一个字没变**：
 * 仍然「只由真实入库/出库单据产生」（issue #7597 / V190 迁移把存量按单据净额重算）。
 *
 * ## 被钉住的行为（每条都会红）
 * ① 建品请求带 `stock=500` ⇒ **422**（改前：200 且静默落 0），且**一行都不写**；
 * ② 建品请求带 `skus[].stock=300` ⇒ 落库的 `product_skus.stock` 仍是 **0**（改前：300）；
 *    含笛卡尔积自动生成 SKU 那条路径（改前未给库存时**默认 100**，见 `saveColorsAndSkus`）——
 *    本文件第三条用例守它；
 * ③ 既然初始库存恒 0 ⇒ **不得**落「新 SKU 初始库存（基线行）」的 `manual` 台账
 *    （0 变更落行 = 台账噪声，且意味着库存是「建档建立的」而不是「真实单据产生的」）；
 * ④ 边界：`stock=0`（等价于不传、落库值本来就 0 ⇒ **没有偏差**）**不**拒绝 ——
 *    把 0 也判 422 只会打断「老客户端回传整对象」这类无害形态，换不到任何信息量。
 *
 * ## 边界（如实登记）
 * 本文件只裁**建品**；改品库存（批量库存调整 / Agent 调整走的同一条分支）仍是合法写面，
 * 由 `ProductStockNonNegativeGateTest` 承担 —— 本单**没有**改它。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("建品不建立库存：非 0 库存 ⇒ 422；SKU 级库存仍忽略（issue #7597 / #9006）")
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
    @DisplayName("issue #9045：部分更新不得携带 Java 侧初始值（否则建品的 stockWarningThreshold 被 SKU 同步覆写回 10）")
    void partialUpdateMustNotCarryJavaSideDefaults() {
        // 真实病灶（2026-11-22 生产实测）：建品传 stockWarningThreshold=7 ⇒ 给了 skus 时
        // syncProductStock() 走 `new Product()` + updateById（只打算改 stock），而实体上
        // threshold=10 / mode='on_order' 的**字段初始值**让 MyBatis-Plus 把这两列一并写回
        // ⇒ 用户设的 7 被静默改成 10（DB 只读核对确认）。
        Product partial = new Product();
        partial.setId("p-9045");
        partial.setStock(new java.math.BigDecimal("3"));

        assertThat(partial.getStockWarningThreshold())
                .as("实体不得给 stockWarningThreshold 初始值：部分更新会把它当「要改的值」写回（DB 默认 10 已兜底）")
                .isNull();
        assertThat(partial.getStockDeductionMode())
                .as("实体不得给 stockDeductionMode 初始值：同上（DB 默认 on_order 已兜底）")
                .isNull();
    }

    @Test
    @DisplayName("判据1（#9006）：stock=500 ⇒ 422 显式拒绝，且一行都不写（改前：200 + 静默落 0）")
    void createRejectsNonZeroRequestStock() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("库存探针");
        request.setSkuCode("PJ-7597");
        request.setBasePrice(new BigDecimal("199.00"));
        request.setStock(new BigDecimal("500"));

        assertThatThrownBy(() -> productService.createProduct(request, 1L))
                .as("「提交 100 落 0」的静默偏差必须变成显式拒绝（issue #9006 原始读数：POST stock=100 ⇒ 200，DB stock=0）")
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).as("必须是 422（可行动拒绝），不是 400/500").isEqualTo(422);
                    assertThat(e.getMessage())
                            .as("文案必须点明「商品档案不设置库存」+ 本次读数，用户才知道为什么被拒")
                            .contains("不设置库存")
                            .contains("500");
                    assertThat(e.getSuggestion())
                            .as("必须给出可行动出口（去入库单），否则用户只能猜")
                            .contains("入库");
                });

        verify(productMapper, never()).insert(any(Product.class));
    }

    @Test
    @DisplayName("判据2：不带商品级库存时 —— skus[].stock=300 仍被忽略、落库 0、且不落「建品基线」台账")
    void createIgnoresSkuStock() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("库存探针");
        request.setSkuCode("PJ-7597");
        request.setBasePrice(new BigDecimal("199.00"));

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
                .as("建品从不建立商品级库存（新商品从 0 起算）")
                .isEqualByComparingTo(BigDecimal.ZERO);

        ArgumentCaptor<ProductSku> skuCaptor = ArgumentCaptor.forClass(ProductSku.class);
        verify(productSkuMapper).insert(skuCaptor.capture());
        assertThat(skuCaptor.getValue().getStock())
                .as("建品请求里的 skus[].stock 必须被忽略（库存只由真实单据产生；issue #7597 口径未变）")
                .isEqualByComparingTo(BigDecimal.ZERO);

        // 0 变更不落账 ⇒「新 SKU 初始库存（基线行）」不应出现
        verify(stockLedgerService, never())
                .record(any(), any(), any(), any(), any(), any(), any(), any(), any());

        assertThat(response.getStock())
                .as("响应里的库存 = SKU 汇总（= 0）；调用方读回即可见「没有建立库存」")
                .isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Test
    @DisplayName("判据3（笛卡尔积路径）：只给 colors × doorWidths ⇒ 自动生成的 SKU 库存 0（改前默认 100）")
    void autoGeneratedSkusStartFromZero() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("矩阵探针");
        request.setSkuCode("PJ-MATRIX");
        request.setBasePrice(new BigDecimal("88.00"));

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

    @Test
    @DisplayName("判据4（边界）：显式 stock=0 ⇒ 接受（与不传等价，落库值本来就是 0 ⇒ 没有偏差、不制造无意义 422）")
    void explicitZeroStockIsAccepted() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("库存探针");
        request.setSkuCode("PJ-7597");
        request.setBasePrice(new BigDecimal("199.00"));
        request.setStock(BigDecimal.ZERO);

        ProductResponse response = productService.createProduct(request, 1L);

        assertThat(response.getId()).as("stock=0 与不传等价 ⇒ 必须照常建品").isEqualTo("prod-7597");
        ArgumentCaptor<Product> productCaptor = ArgumentCaptor.forClass(Product.class);
        verify(productMapper).insert(productCaptor.capture());
        assertThat(productCaptor.getValue().getStock())
                .as("落库仍是 0（库存由单据产生，建品不建立库存）")
                .isEqualByComparingTo(BigDecimal.ZERO);
    }
}
