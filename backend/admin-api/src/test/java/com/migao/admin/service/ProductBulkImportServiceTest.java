// case_ids: PR-059
//
// 商品 + SKU 批量导入（issue #5154）—— 迁移/批次建账的**前置**（SKU 不存在 ⇒ 批次挂不上）。
//
// 本文件是**行为判据**，不是实现照抄。每条判据都带「怎么让它红」：
//   判据 1（逐字段可比对）：改前 `importProducts` 只落商品、**不落 SKU**（`parseProductFromRow` 里
//                        没有任何 SKU 维度）⇒ `importsProductAndSkusFieldByField` 直接红；
//                        HTTP 面的 404 红证见 ProductImportControllerTest。
//   判据 2（幂等）       ：把 upsert 的查重改成恒 null（每次都 insert）⇒ `insert` 调用数变 2、SKU 行翻倍。
//   判据 3（不静默跳过）  ：把 `addError(...)` 换成 `continue`（或删掉空行计数）
//                       ⇒ `total == success + fail + blank` 不再成立。
//   判据 4（1 位小数）    ：把 `StockQuantity.requireOneDecimal` 换回静默取整
//                       ⇒ 60.5 落成 60、2.755 不报错。
//   判据 5（不损失客户）  ：导入路径**只增改不删**（pruneMissing=false）⇒ 既有 SKU 不被物理删除。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.ProductImportResult;
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
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批量导入用**内存库**模拟：mapper 全部「真存真取」，因此「同一文件跑两遍」能被真正观察到。
 * （只 mock「返回固定值」的形式区分不了幂等与不幂等 —— 两次都返回空列表时任何实现都"通过"。）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商品 + SKU 批量导入（#5154）")
class ProductBulkImportServiceTest {

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

    private static final Long TENANT = 1L;

    /** 导入模板表头（表头驱动 ⇒ 定位按**名字**，列序无关）。 */
    private static final String[] HEADERS =
            {"商品名称", "货号", "分类ID", "价格", "库存", "描述", "颜色", "门幅", "SKU编码"};

    // ===== 内存库 =====
    private final List<Product> products = new ArrayList<>();
    private final List<ProductColor> colors = new ArrayList<>();
    private final List<ProductSku> skus = new ArrayList<>();
    private long colorSeq = 0L;
    private long skuSeq = 0L;
    /** 「当前正在被写入的商品」—— 见 {@link #skusForCurrent()} 的注释。 */
    private String currentProductId;

    @BeforeEach
    void setUp() {
        for (Class<?> c : List.of(Product.class, ProductColor.class, ProductSku.class)) {
            TableInfoHelper.initTableInfo(
                    new MapperBuilderAssistant(new MybatisConfiguration(), ""), c);
        }
        products.clear();
        colors.clear();
        skus.clear();
        currentProductId = null;

        when(productMapper.insert(any(Product.class))).thenAnswer(inv -> {
            Product p = inv.getArgument(0);
            if (p.getId() == null) {
                p.setId("prod-" + (products.size() + 1));
            }
            products.add(p);
            currentProductId = p.getId();
            return 1;
        });
        // 幂等键查询是**租户内**的（幂等键 = 租户 + 货号）⇒ 内存库照抄这个语义
        when(productMapper.selectByTenantAndSkuCode(any(), any())).thenAnswer(inv -> {
            Long tenantId = inv.getArgument(0);
            String skuCode = inv.getArgument(1);
            return products.stream()
                    .filter(p -> Objects.equals(p.getTenantId(), tenantId)
                            && Objects.equals(p.getSkuCode(), skuCode))
                    .findFirst().orElse(null);
        });
        when(productMapper.updateById(any(Product.class))).thenAnswer(inv -> {
            Product patch = inv.getArgument(0);
            Product cur = products.stream()
                    .filter(p -> Objects.equals(p.getId(), patch.getId())).findFirst().orElse(null);
            if (cur == null) {
                return 0;
            }
            // MyBatis-Plus 的 updateById 只写非 null 字段 —— 内存库照抄这个语义
            if (patch.getName() != null) cur.setName(patch.getName());
            if (patch.getCategoryId() != null) cur.setCategoryId(patch.getCategoryId());
            if (patch.getBasePrice() != null) cur.setBasePrice(patch.getBasePrice());
            if (patch.getDescription() != null) cur.setDescription(patch.getDescription());
            if (patch.getStock() != null) cur.setStock(patch.getStock());
            currentProductId = cur.getId();
            return 1;
        });

        when(productColorMapper.insert(any(ProductColor.class))).thenAnswer(inv -> {
            ProductColor c = inv.getArgument(0);
            c.setId(++colorSeq);
            colors.add(c);
            return 1;
        });
        when(productColorMapper.selectList(any())).thenAnswer(inv -> new ArrayList<>(colorsForCurrent()));

        when(productSkuMapper.insert(any(ProductSku.class))).thenAnswer(inv -> {
            ProductSku s = inv.getArgument(0);
            s.setId(++skuSeq);
            skus.add(s);
            return 1;
        });
        when(productSkuMapper.updateById(any(ProductSku.class))).thenAnswer(inv -> 1);
        when(productSkuMapper.selectList(any())).thenAnswer(inv -> new ArrayList<>(skusForCurrent()));
    }

    /**
     * SKU/颜色查询按「当前商品」过滤。
     *
     * <p><b>为什么不用 wrapper 里的参数</b>：MyBatis-Plus 3.5.16 的
     * {@code AbstractWrapper.getParamNameValuePairs()} 实测**恒为空**（参数值落在懒加载的
     * SharedString 里，SQL 片段只剩 {@code #{ew.paramNameValuePairs.MPGENVAL1}} 占位符）——
     * 这是实测结论，不是推断。改用「生产代码里 {@code saveColorsAndSkus} /
     * {@code syncProductStockFromSkus} 都紧接该商品的 insert/update 调用」这一结构事实来定位。</p>
     */
    private List<ProductColor> colorsForCurrent() {
        return colors.stream().filter(c -> Objects.equals(c.getProductId(), currentProductId)).toList();
    }

    private List<ProductSku> skusForCurrent() {
        return skus.stream().filter(s -> Objects.equals(s.getProductId(), currentProductId)).toList();
    }

    // ==================== 判据 1：逐字段可比对 ====================

    @Test
    @DisplayName("判据1：导入 3 行 ⇒ 商品 + 3 个 SKU 落库且逐字段可比对")
    void importsProductAndSkusFieldByField() throws Exception {
        MockMultipartFile file = workbook(
                row("雪尼尔遮光帘", "MH-001", null, 128.50, 60.5, "米白色雪尼尔", "米白", "2.8m", "MH-001-01-28"),
                row("雪尼尔遮光帘", "MH-001", null, 128.50, 12, "米白色雪尼尔", "米白", "3.2m", "MH-001-01-32"),
                row("雪尼尔遮光帘", "MH-001", null, 128.50, 0.5, "米白色雪尼尔", "浅灰", "2.8m", "MH-001-02-28"));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isZero();
        assertThat(result.getSuccessCount()).isEqualTo(3);
        assertThat(result.getCreatedProducts()).isEqualTo(1);
        assertThat(result.getUpdatedProducts()).isZero();

        Product saved = onlyProduct();
        assertThat(saved.getName()).isEqualTo("雪尼尔遮光帘");
        assertThat(saved.getSkuCode()).isEqualTo("MH-001");
        assertThat(saved.getBasePrice()).isEqualByComparingTo(new BigDecimal("128.50"));
        assertThat(saved.getDescription()).isEqualTo("米白色雪尼尔");
        assertThat(saved.getTenantId()).isEqualTo(TENANT);
        assertThat(saved.getStatus()).isEqualTo("draft");
        // 商品级库存是**派生列**（#4038）：有 SKU 时 = SKU 汇总
        assertThat(saved.getStock()).isEqualByComparingTo(new BigDecimal("73"));

        assertThat(skus).hasSize(3);
        ProductSku first = skuOf("米白", "2.8m");
        assertThat(first.getProductId()).isEqualTo(saved.getId());
        assertThat(first.getTenantId()).isEqualTo(TENANT);
        assertThat(first.getSkuCode()).isEqualTo("MH-001-01-28");
        // 判据 4：60.5 必须原样落库（不是 60、不是 61）
        assertThat(first.getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
        assertThat(first.getPrice()).isEqualByComparingTo(new BigDecimal("128.50"));
        assertThat(skuOf("米白", "3.2m").getStock()).isEqualByComparingTo(new BigDecimal("12"));
        assertThat(skuOf("浅灰", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("0.5"));
        // 颜色卡（product_colors）同样落库：SKU 的 colorId 要挂得上
        assertThat(colors).extracting(ProductColor::getColorName)
                .containsExactlyInAnyOrder("米白", "浅灰");
        assertThat(first.getColorId()).isNotNull();
    }

    @Test
    @DisplayName("判据1：无 SKU 维度的行 ⇒ 只落商品（stock 取文件值），不臆造 SKU")
    void importsProductWithoutSkuDimensions() throws Exception {
        MockMultipartFile file = workbook(
                row("罗马杆配件", "PJ-001", null, 35, 8, "2.8m 杆", null, null, null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getSuccessCount()).isEqualTo(1);
        assertThat(skus).isEmpty();
        assertThat(onlyProduct().getStock()).isEqualByComparingTo(new BigDecimal("8"));
    }

    @Test
    @DisplayName("判据1：门幅/货号写成**数字单元格**也按十进制原样读（2.8 不能变 2）")
    void numericCellsAreReadAsPlainDecimals() throws Exception {
        // Excel 里把门幅敲成数字 2.8、把货号敲成数字 12345 都很常见
        MockMultipartFile file = workbook(
                row("雪尼尔遮光帘", 12345, null, 99, 60.5, null, "米白", 2.8, null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isZero();
        assertThat(onlyProduct().getSkuCode()).isEqualTo("12345");
        // 红证：把 getCellStringValue 的数字分支换回 `String.valueOf((long) v)` ⇒ 门幅落成 "2"，
        // `skuOf("米白","2.8")` 当场抛「找不到 SKU」（本行即判据）
        ProductSku sku = skuOf("米白", "2.8");
        assertThat(sku.getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    // ==================== 判据 2：幂等 ====================

    @Test
    @DisplayName("判据2：同一文件重跑 ⇒ 不新增商品、不新增 SKU（幂等键 = 租户 + 货号）")
    void reimportingSameFileIsIdempotent() throws Exception {
        MockMultipartFile file = workbook(
                row("雪尼尔遮光帘", "MH-001", null, 128.50, 60.5, "米白色雪尼尔", "米白", "2.8m", null),
                row("雪尼尔遮光帘", "MH-001", null, 128.50, 12, "米白色雪尼尔", "浅灰", "3.2m", null));

        ProductImportResult first = productService.importProducts(file, TENANT);
        ProductImportResult second = productService.importProducts(file, TENANT);

        assertThat(first.getCreatedProducts()).isEqualTo(1);
        assertThat(second.getCreatedProducts()).isZero();
        assertThat(second.getUpdatedProducts()).isEqualTo(1);
        assertThat(second.getSuccessCount()).isEqualTo(2);
        assertThat(second.getFailCount()).isZero();

        assertThat(products).hasSize(1);
        assertThat(skus).hasSize(2);
        // 商品主键与 SKU 主键都**原地保留**（订单/批次里存的旧 id 不断链）
        verify(productMapper, times(1)).insert(any(Product.class));
        verify(productSkuMapper, times(2)).insert(any(ProductSku.class));
        assertThat(skus).extracting(ProductSku::getId).containsExactly(1L, 2L);
        // 逐值不变：重跑不得把 60.5 变成别的数
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    @Test
    @DisplayName("判据2：门幅归一化后相同（2.8 与 2.8米）⇒ 视为同一 SKU，不新增行")
    void reimportingWithNormalizedDoorWidthDoesNotDuplicate() throws Exception {
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-002", null, 99, 10, null, "米白", "2.8", null)), TENANT);
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-002", null, 99, 10, null, "米白", "2.8米", null)), TENANT);

        assertThat(skus).hasSize(1);
        verify(productSkuMapper, times(1)).insert(any(ProductSku.class));
    }

    @Test
    @DisplayName("判据5：导入只增改不删 —— 文件里没有的既有 SKU 不被物理删除")
    void importNeverDeletesExistingSkus() throws Exception {
        // 库里先有一个商品 + 两个 SKU（上一次导入建的）
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-003", null, 99, 10, null, "米白", "2.8m", null),
                row("雪尼尔遮光帘", "MH-003", null, 99, 20, null, "浅灰", "2.8m", null)), TENANT);
        assertThat(skus).hasSize(2);

        // 第二次只导入其中一个组合 ⇒ 另一个必须**留着**
        // （不能静默删掉 —— 批次挂着的 SKU 被删 = 断链）
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-003", null, 99, 10, null, "米白", "2.8m", null)), TENANT);

        assertThat(skus).hasSize(2);
        assertThat(skuOf("浅灰", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("20"));
    }

    @Test
    @DisplayName("判据2：库存留空 ⇒ 不改既有 SKU 库存（「未填 = 不改」，不是「未填 = 清零」）")
    void blankStockKeepsExistingStock() throws Exception {
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-004", null, 99, 60.5, null, "米白", "2.8m", null)), TENANT);
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-004", null, 99, null, null, "米白", "2.8m", null)), TENANT);

        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    @Test
    @DisplayName("判据2：租户不同 ⇒ 同货号各自建品（幂等键是「租户 + 货号」，不是全局货号）")
    void sameSkuCodeInAnotherTenantIsNotDeduplicated() throws Exception {
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-005", null, 99, 10, null, "米白", "2.8m", null)), TENANT);
        productService.importProducts(workbook(
                row("雪尼尔遮光帘", "MH-005", null, 99, 10, null, "米白", "2.8m", null)), 2L);

        verify(productMapper, times(2)).insert(any(Product.class));
        // SKU 也各建一行（SKU 查询是按 productId 走的，不跨商品/跨租户串行）
        assertThat(skus).hasSize(2);
        assertThat(skus).extracting(ProductSku::getProductId).containsExactly("prod-1", "prod-2");
    }

    // ==================== 判据 3：逐行校验报告，不静默跳过 ====================

    @Test
    @DisplayName("判据3：非法行 ⇒ 显式报错 + 行号 + 货号 + 原因；且 total == success + fail + blank")
    void invalidRowsAreReportedNotSilentlySkipped() throws Exception {
        MockMultipartFile file = workbook(
                row("合法商品", "OK-001", null, 10, 1, null, "米白", "2.8m", null),   // 第 2 行：合法
                row(null, "NO-NAME", null, 10, 1, null, null, null, null),          // 第 3 行：缺商品名称
                row("缺货号", null, null, 10, 1, null, null, null, null),           // 第 4 行：缺货号
                row("价格非数字", "BAD-P", null, "abc", 1, null, null, null, null), // 第 5 行：价格非数字
                row("颜色缺门幅", "BAD-C", null, 10, 1, null, "米白", null, null),  // 第 6 行：颜色/门幅不成对
                new Object[0]);                                                    // 第 7 行：空白行

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getTotal()).isEqualTo(6);
        assertThat(result.getSuccessCount()).isEqualTo(1);
        assertThat(result.getFailCount()).isEqualTo(4);
        assertThat(result.getBlankRows()).isEqualTo(1);
        // ★ 不静默跳过的**机械判据**：每一行都必须落在「成功 / 失败 / 空白」三桶之一
        assertThat(result.getSuccessCount() + result.getFailCount() + result.getBlankRows())
                .isEqualTo(result.getTotal());

        List<ProductImportResult.ErrorDetail> errors = result.getErrors();
        assertThat(errors).extracting(ProductImportResult.ErrorDetail::getRow)
                .containsExactly(3, 4, 5, 6);
        // 可定位：行号 + 货号（**没有货号的那一行本来就是因为它缺货号才报错**，此时行号即定位）
        assertThat(errors).extracting(ProductImportResult.ErrorDetail::getMessage).doesNotContainNull();
        assertThat(errorAt(result, 3).getSkuCode()).isEqualTo("NO-NAME");
        assertThat(errorAt(result, 4).getSkuCode()).isNull();
        assertThat(errorAt(result, 5).getSkuCode()).isEqualTo("BAD-P");
        assertThat(errorAt(result, 6).getSkuCode()).isEqualTo("BAD-C");
        assertThat(errorAt(result, 3).getMessage()).contains("商品名称");
        assertThat(errorAt(result, 4).getMessage()).contains("货号");
        assertThat(errorAt(result, 5).getMessage()).contains("价格");
        assertThat(errorAt(result, 6).getMessage()).contains("门幅");
        // 非法行的货号不得落库（不静默少导，也不静默半导）
        assertThat(products).extracting(Product::getSkuCode).containsExactly("OK-001");
        assertThat(onlyProduct().getStock()).isEqualByComparingTo(new BigDecimal("1"));
    }

    @Test
    @DisplayName("判据3：同一货号内 (颜色,门幅) 重复 ⇒ 报错，不让后者静默覆盖前者")
    void duplicateColorWidthInSameFileIsReported() throws Exception {
        MockMultipartFile file = workbook(
                row("雪尼尔", "DUP-001", null, 10, 5, null, "米白", "2.8m", null),
                row("雪尼尔", "DUP-001", null, 10, 7, null, "米白", "2.8m", null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isEqualTo(1);
        assertThat(errorAt(result, 3).getMessage()).contains("重复");
        // 只有第一行落库（5 米），第二行被显式拒绝而不是静默覆盖成 7
        assertThat(skus).hasSize(1);
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("5"));
    }

    @Test
    @DisplayName("判据3：同一货号的产品级字段互相矛盾 ⇒ 报错（价格不一致 = 涉钱字段不许含糊）")
    void conflictingProductLevelFieldsAreReported() throws Exception {
        MockMultipartFile file = workbook(
                row("雪尼尔", "CONF-001", null, 10, 5, null, "米白", "2.8m", null),
                row("雪尼尔", "CONF-001", null, 12, 7, null, "浅灰", "2.8m", null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isEqualTo(1);
        assertThat(errorAt(result, 3).getMessage()).contains("价格");
        assertThat(onlyProduct().getBasePrice()).isEqualByComparingTo(new BigDecimal("10"));
        assertThat(skus).hasSize(1);
    }

    @Test
    @DisplayName("判据3：表头缺必填列 ⇒ 整包拒绝 + 可行动文案（不逐行刷屏）")
    void missingRequiredHeaderFailsWholeFile() throws Exception {
        MockMultipartFile file = workbookWithHeaders(
                new String[]{"商品名称", "价格"},          // 缺「货号」
                new Object[]{"雪尼尔", 10});

        assertThatThrownBy(() -> productService.importProducts(file, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("货号");
        assertThat(products).isEmpty();
    }

    // ==================== 判据 4：1 位小数精度 ====================

    @Test
    @DisplayName("判据4：2.755 ⇒ 显式拒绝 + 该行零落库副作用（不静默取整成 2.8）")
    void twoDecimalStockIsRejectedWithNoSideEffects() throws Exception {
        MockMultipartFile file = workbook(
                row("非法精度", "BAD-DEC", null, 10, 2.755, null, "米白", "2.8m", null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getSuccessCount()).isZero();
        assertThat(result.getFailCount()).isEqualTo(1);
        assertThat(errorAt(result, 2).getMessage())
                .contains("1 位小数").contains("2.755").contains("0.1 米");   // 可行动
        // 零副作用：商品 / 颜色 / SKU 一张都没写
        assertThat(products).isEmpty();
        assertThat(colors).isEmpty();
        assertThat(skus).isEmpty();
        verify(productMapper, times(0)).insert(any(Product.class));
        verify(productSkuMapper, times(0)).insert(any(ProductSku.class));
        verify(productColorMapper, times(0)).insert(any(ProductColor.class));
    }

    @Test
    @DisplayName("判据4：非法行与合法行同批 ⇒ 合法行照常落库，非法行零副作用（行级原子，非整包回滚）")
    void invalidRowDoesNotBlockValidRowsInSameFile() throws Exception {
        MockMultipartFile file = workbook(
                row("合法商品", "MIX-OK", null, 10, 60.5, null, "米白", "2.8m", null),
                row("非法精度", "MIX-BAD", null, 10, 2.755, null, "米白", "2.8m", null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getSuccessCount()).isEqualTo(1);
        assertThat(result.getFailCount()).isEqualTo(1);
        assertThat(products).extracting(Product::getSkuCode).containsExactly("MIX-OK");
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    @Test
    @DisplayName("判据4：2.70（书写 2 位 / 有效 1 位）合法 —— 与 StockQuantity 同口径，不另立判据")
    void twoDotSevenZeroIsAccepted() throws Exception {
        MockMultipartFile file = workbook(
                row("雪尼尔", "DEC-270", null, 10, 2.70, null, "米白", "2.8m", null));

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isZero();
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("2.7"));
    }

    // ==================== 表头驱动（一进一出同构） ====================

    @Test
    @DisplayName("同构：表头按**名字**定位 ⇒ 列序打乱、带 * 号、多余列都不影响导入")
    void headerDrivenColumnMapping() throws Exception {
        MockMultipartFile file = workbookWithHeaders(
                new String[]{"库存", "商品名称*", "门幅", "货号*", "颜色", "价格*", "备注无关列"},
                new Object[]{60.5, "雪尼尔遮光帘", "2.8m", "HDR-001", "米白", 128.50, "随便写"});

        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getFailCount()).isZero();
        assertThat(onlyProduct().getSkuCode()).isEqualTo("HDR-001");
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    @Test
    @DisplayName("同构：导入表头 ∩ 导出表头 = 逐字同名的那 5 列；SKU 维度只有 颜色 + 门幅（不含售卖方式）")
    void importHeaderFaceIsIsomorphicToExport() {
        java.util.Set<String> shared = new java.util.LinkedHashSet<>(List.of(ProductService.IMPORT_HEADERS));
        shared.retainAll(new java.util.LinkedHashSet<>(List.of(ProductService.EXPORT_HEADERS)));

        assertThat(shared).containsExactly("商品名称", "货号", "价格", "库存", "描述");
        assertThat(ProductService.IMPORT_HEADERS).contains("颜色", "门幅");
        // #5058：SKU 组合 = 颜色 × 门幅；售卖方式是**商品级**属性 ⇒ 不得成为导入的 SKU 维度
        assertThat(ProductService.IMPORT_HEADERS).doesNotContain("售卖方式");
    }

    @Test
    @DisplayName("同构：模板下载下来的文件能**原样导回去**（表头与解析共用同一常量 ⇒ 不可能分叉）")
    void templateCanBeImportedBackAsIs() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();
        productService.generateImportTemplate(response);
        assertThat(response.getContentAsByteArray()).isNotEmpty();

        MockMultipartFile file = new MockMultipartFile("file", "商品导入模板.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                response.getContentAsByteArray());
        ProductImportResult result = productService.importProducts(file, TENANT);

        assertThat(result.getErrors()).isEmpty();
        assertThat(result.getBlankRows()).isZero();
        assertThat(result.getSuccessCount()).isEqualTo(result.getTotal());
        // 模板示例行：MH-001 两行 = 1 个商品 2 个 SKU；PJ-001 一行 = 1 个无 SKU 商品
        assertThat(products).extracting(Product::getSkuCode).containsExactly("MH-001", "PJ-001");
        assertThat(skus).hasSize(2);
        assertThat(skuOf("米白", "2.8m").getStock()).isEqualByComparingTo(new BigDecimal("60.5"));
    }

    // ==================== 辅助 ====================
    private Product onlyProduct() {
        assertThat(products).hasSize(1);
        return products.get(0);
    }

    private ProductSku skuOf(String colorName, String doorWidth) {
        return skus.stream()
                .filter(s -> Objects.equals(s.getColorName(), colorName)
                        && Objects.equals(s.getDoorWidth(), doorWidth))
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "找不到 SKU " + colorName + "/" + doorWidth + "，现有："
                                + skus.stream().map(s -> s.getColorName() + "/" + s.getDoorWidth()).toList()));
    }

    private static ProductImportResult.ErrorDetail errorAt(ProductImportResult r, int row) {
        return r.getErrors().stream().filter(e -> e.getRow() == row).findFirst()
                .orElseThrow(() -> new AssertionError("第 " + row + " 行没有报错：" + r.getErrors()));
    }

    /** 一行数据：列序与 HEADERS 一致；null = 该单元格留空。 */
    private static Object[] row(Object name, Object skuCode, Object categoryId, Object price,
                                Object stock, Object description, Object color,
                                Object doorWidth, Object skuCodeOfSku) {
        return new Object[]{name, skuCode, categoryId, price, stock, description, color, doorWidth, skuCodeOfSku};
    }

    private static MockMultipartFile workbook(Object[]... rows) throws Exception {
        return workbookWithHeaders(HEADERS, rows);
    }

    private static MockMultipartFile workbookWithHeaders(String[] headers, Object[]... rows) throws Exception {
        try (Workbook wb = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = wb.createSheet("商品导入");
            Row header = sheet.createRow(0);
            for (int i = 0; i < headers.length; i++) {
                header.createCell(i).setCellValue(headers[i]);
            }
            for (int r = 0; r < rows.length; r++) {
                Row row = sheet.createRow(r + 1);
                Object[] values = rows[r];
                for (int c = 0; c < values.length; c++) {
                    if (values[c] == null) {
                        continue;
                    }
                    if (values[c] instanceof Number n) {
                        row.createCell(c).setCellValue(n.doubleValue());
                    } else {
                        row.createCell(c).setCellValue(String.valueOf(values[c]));
                    }
                }
            }
            wb.write(out);
            return new MockMultipartFile("file", "商品导入.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.toByteArray());
        }
    }
}
