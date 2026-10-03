// case_ids: PR-048, PR-059
// 商品库存**非负**准入（issue #6199）：改品路径此前只过 `StockQuantity.requireOneDecimalOrNull`（只校精度、不校符号）
// ⇒ `PUT /api/admin/products/{id}` 传 `stock=-5` 得 200 且落库（`products.stock` / `product_skus.stock` / 台账全为负）。
// 同族的盘点盘亏（422 INSUFFICIENT_STOCK）与入库/库存调整（`StockQuantity` 精度准入）**都有护栏** —— 漏的就是这一处。
//
// 本文件按铁律 8 分两层：
//   ① 实例判据：create / update / SKU 库存**三处写面同源**拒绝负值（同源断言，避免只修一处）；
//      端点面 `PUT /products/{id}` ⇒ 4xx 且**零写入**；边界 `0` 合法、`-0.1` 拒绝。
//   ② 类级元守卫：「凡 `ProductService` 里写 `products/product_skus.stock` 的绝对库存准入，
//      必须过**同一个**非负收口」—— 精度-only 的可空调用点**未登记即红**（登记表 = 空），
//      非负收口的调用点数 = 现取台账（少了 ⇒ 某个写面掉了收口）。
//
// 边界（如实登记）：本守卫只裁 `ProductService`（本包的写面所有权）；
// 别的服务里若有「写绝对库存」的入口（如 `AgentBatchService` 的批量改后值）不在它射程内，
// 那些路径的负值由它们各自的准入面承担（`AgentBatchService` 走的是 `productService.updateProductForAgent`
// ⇒ 真正落库仍在 ProductService 的收口上，见判据 2 的第三个写面）。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.ProductController;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductSkuInput;
import com.migao.admin.dto.ProductUpdateRequest;
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
import org.junit.jupiter.api.function.Executable;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商品库存非负准入（issue #6199）")
class ProductStockNonNegativeGateTest {

    private static final String PRODUCT_SERVICE_SOURCE =
            "src/main/java/com/migao/admin/service/ProductService.java";

    /**
     * 类级元守卫的**登记表**（未登记即红）：允许在 `ProductService` 里保留
     * 「只校精度、不校符号」的可空库存准入（`requireOneDecimalOrNull`）的调用点。
     *
     * <p>本包修完后为**空**：`ProductService` 里凡「可空 + 绝对值」的库存准入都必须走
     * `StockQuantity.requireNonNegativeOrNull`。将来新增一处精度-only 的可空准入 ⇒ 判据当场红，
     * 必须在同一 diff 里显式登记并说明「为什么它写的是绝对值却允许负数」。</p>
     */
    private static final List<String> PRECISION_ONLY_NULLABLE_CALL_SITES_ALLOWED = List.of();

    /**
     * 非负收口的调用点数（**现取台账**）：create 商品级 / update 商品级 / SKU 库存 / 导入行 —— 共 4 处。
     * 少了 ⇒ 某个写面掉了收口；多了 ⇒ 新增写面，必须显式抬这个数（评审可见）。
     */
    private static final int REQUIRED_NON_NEGATIVE_GATE_CALL_SITES = 4;

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

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductColor.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Category.class);

        TenantContext.setTenantId(1L);
        // 端点面：真 ProductService（桩 mapper）+ 真 GlobalExceptionHandler —— 4xx 是**真**走出来的，
        // 不是「mock 一个异常处理器」摆样子。
        mockMvc = MockMvcBuilders.standaloneSetup(new ProductController(productService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ==================== ① 实例判据 ====================

    @Test
    @DisplayName("判据1：PUT /api/admin/products/{id} 传 stock=-5 ⇒ 4xx 且零写入（一处都不落库）")
    void putNegativeStockIsRejectedWithZeroWrites() throws Exception {
        mockMvc.perform(put("/api/admin/products/prod-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"stock\":-5}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));

        // 「返回了错误」≠「没写进去」：写面必须一次都没被碰到（含负值会经的直写 SKU 那条路）
        verify(productMapper, never()).updateById(any(Product.class));
        verify(productMapper, never()).insert(any(Product.class));
        verify(productMapper, never()).selectById(any());
        verify(productSkuMapper, never()).update(any(), any());
        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        verify(productSkuMapper, never()).insert(any(ProductSku.class));
        verify(stockLedgerService, never()).snapshotSkus(any());
    }

    @Test
    @DisplayName("判据2：create / update / SKU 库存 三处写面**同源**拒绝 -5（避免只修一处）")
    void allAbsoluteStockWriteFacesRejectNegativeFromOneGate() {
        Map<String, Executable> writeFaces = new LinkedHashMap<>();
        writeFaces.put("createProduct → products.stock", () -> {
            productService.createProduct(createRequestWithStock(new BigDecimal("-5")), 1L);
            verify(productMapper, never()).insert(any(Product.class));
        });
        writeFaces.put("updateProduct → products.stock", () -> {
            productService.updateProduct("prod-001", updateRequestWithStock(new BigDecimal("-5")), 1L);
            verify(productMapper, never()).updateById(any(Product.class));
        });
        writeFaces.put("saveColorsAndSkus → product_skus.stock", () -> {
            productService.createProduct(createRequestWithSkuStock(new BigDecimal("-5")), 1L);
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
        });

        assertThat(writeFaces).as("三处写面缺一不可").hasSize(3);
        for (Map.Entry<String, Executable> face : writeFaces.entrySet()) {
            assertThatThrownBy(face.getValue()::execute)
                    .as("写面「%s」必须与其它写面**同源**拒绝负库存", face.getKey())
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("不能为负");
        }
    }

    @Test
    @DisplayName("判据3（边界）：0 合法（放行到下一步）、-0.1 拒绝且零写入")
    void boundaryZeroAllowedNegativeTenthRejected() {
        // 0：非负收口放行 ⇒ 继续走到「商品不存在」（NOT_FOUND），而不是被库存准入拦下
        BusinessException zero = (BusinessException) org.assertj.core.api.Assertions
                .catchThrowable(() -> productService.updateProduct("prod-001", updateRequestWithStock(BigDecimal.ZERO), 1L));
        assertThat(zero).as("0 是合法库存（实物可以为 0 米）⇒ 必须放行到下一步").isNotNull();
        assertThat(zero.getCode()).as("放行后的失败原因必须是「商品不存在」，不是库存准入").isEqualTo("NOT_FOUND");
        assertThat(zero.getMessage()).doesNotContain("不能为负");

        // -0.1：同样是负数，同样拒绝（边界就在 0 与 0 以下之间）
        BusinessException negative = (BusinessException) org.assertj.core.api.Assertions
                .catchThrowable(() -> productService.updateProduct("prod-001", updateRequestWithStock(new BigDecimal("-0.1")), 1L));
        assertThat(negative).as("-0.1 必须被拒").isNotNull();
        assertThat(negative.getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(negative.getMessage()).contains("不能为负");
        verify(productMapper, never()).updateById(any(Product.class));
    }

    // ==================== ② 类级元守卫 ====================

    @Test
    @DisplayName("判据4（类级）：ProductService 里精度-only 的可空库存准入**未登记即红**，非负收口点数 = 现取台账")
    void everyAbsoluteStockAdmissionGoesThroughTheNonNegativeGate() throws IOException {
        String source = productServiceSource();

        assertThat(countOccurrences(source, "requireOneDecimalOrNull("))
                .as("凡「可空 + 绝对值」的库存准入都必须走 requireNonNegativeOrNull；"
                        + "登记表（允许保留精度-only 的调用点）= %s ⇒ 未登记即红",
                        PRECISION_ONLY_NULLABLE_CALL_SITES_ALLOWED)
                .isEqualTo(PRECISION_ONLY_NULLABLE_CALL_SITES_ALLOWED.size());

        assertThat(countOccurrences(source, "requireNonNegativeOrNull("))
                .as("非负收口的调用点数必须 = 现取台账 %d（少了 ⇒ 某个写面掉了收口；多了 ⇒ 显式抬台账）",
                        REQUIRED_NON_NEGATIVE_GATE_CALL_SITES)
                .isEqualTo(REQUIRED_NON_NEGATIVE_GATE_CALL_SITES);
    }

    @Test
    @DisplayName("判据5（判别力自证）：扫描器必须能认出「回退成精度-only」的写面 —— 否则判据 4 是空跑")
    void scannerHasTeeth() {
        assertThat(countOccurrences("request.setStock(StockQuantity.requireOneDecimalOrNull(request.getStock(), \"库存 stock\"));",
                "requireOneDecimalOrNull("))
                .as("回退形态（改品的旧写法）必须被扫出来")
                .isEqualTo(1);
        assertThat(countOccurrences("request.setStock(StockQuantity.requireNonNegativeOrNull(request.getStock(), \"库存 stock\"));",
                "requireNonNegativeOrNull("))
                .as("加固形态必须被认成非负收口")
                .isEqualTo(1);
        assertThat(countOccurrences("// 注释里提到 requireOneDecimalOrNull( 也只算一次出现", "requireOneDecimalOrNull("))
                .as("扫描器不解析 Java 语法：它数的是**文本出现次数**（判据 4 的登记表按同一口径现取）")
                .isEqualTo(1);
    }

    // ==================== 夹具 ====================

    private ProductCreateRequest createRequestWithStock(BigDecimal stock) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("负库存商品");
        request.setSkuCode("PJ-NEG");
        request.setBasePrice(new BigDecimal("199.0"));
        request.setStock(stock);
        return request;
    }

    private ProductUpdateRequest updateRequestWithStock(BigDecimal stock) {
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setStock(stock);
        return request;
    }

    private ProductCreateRequest createRequestWithSkuStock(BigDecimal skuStock) {
        ProductCreateRequest request = createRequestWithStock(BigDecimal.ZERO);
        ProductSkuInput sku = new ProductSkuInput();
        sku.setColorName("米白");
        sku.setDoorWidth("2.8");
        sku.setPrice(new BigDecimal("199.0"));
        sku.setStock(skuStock);
        request.setSkus(List.of(sku));
        return request;
    }

    private static int countOccurrences(String source, String needle) {
        int count = 0;
        int index = source.indexOf(needle);
        while (index >= 0) {
            count++;
            index = source.indexOf(needle, index + needle.length());
        }
        return count;
    }

    private static String productServiceSource() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(PRODUCT_SERVICE_SOURCE))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 %s（守卫的真值源 = 仓库里的源文件）", PRODUCT_SERVICE_SOURCE).isNotNull();
        return Files.readString(root.resolve(PRODUCT_SERVICE_SOURCE));
    }
}
