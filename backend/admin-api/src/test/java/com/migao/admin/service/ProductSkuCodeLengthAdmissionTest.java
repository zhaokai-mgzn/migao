// case_ids: PR-122
// 商品 / SKU 短文本列**长度准入**（issue #6302）：`POST /api/admin/products` 传 31 个字符的 `skuCode`
// （库列 `products.sku_code` = `varchar(30)`）此前**无任何准入** ⇒ 一路带到 DB ⇒
// `ERROR: value too long for type character varying(30)` @ `ProductMapper.insert` ⇒ HTTP 500
// `INTERNAL_ERROR`「服务器内部错误」——用户无法自救（不知道该改哪一列、改成多长）。
//
// 本文件按铁律 8 分两层：
//   ① 实例判据：表单路径（`@Valid` 一侧）与 **agent / Excel 路径**（手工 new DTO、不走 Bean Validation）
//      **同源**拒绝超长；边界 = 列上限**放行**、超 1 个字符拒绝；拒绝时**零写入**。
//   ② 类级元守卫在 `ProductTextColumnAdmissionMetaGuardTest`（现取 information_schema 对账）。
//
// 边界（如实登记）：本文件用桩 mapper ⇒ 判的是「接口不再拿 500 兜底、而是 4xx + 可行动文案」；
// 「长度 = 列上限 ⇒ 真库 200」的真库读数在 ProductTextColumnAdmissionMetaGuardTest 的
// realDbBoundaryReadingMatchesLiveColumn（真 PG 直插：30 ⇒ 成功、31 ⇒ value too long）。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.ProductController;
import com.migao.admin.dto.ProductColorInput;
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

import java.math.BigDecimal;
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
@DisplayName("商品/SKU 文本列长度准入（issue #6302）")
class ProductSkuCodeLengthAdmissionTest {

    /** 库列 `products.sku_code` = varchar(30)（现取 information_schema，见元守卫的判据 1）。 */
    private static final int PRODUCTS_SKU_CODE_MAX = 30;
    /** 库列 `product_skus.sku_code` = varchar(50)。 */
    private static final int PRODUCT_SKUS_SKU_CODE_MAX = 50;
    /** 库列 `product_skus.door_width` = varchar(20)。 */
    private static final int PRODUCT_SKUS_DOOR_WIDTH_MAX = 20;
    /** 库列 `product_colors.color_name` = varchar(30)。 */
    private static final int PRODUCT_COLORS_COLOR_NAME_MAX = 30;

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
        // 桩：insert 后给出主键（真 mapper 由 `@TableId` 回填）—— 否则 createProduct 会把 null 主键
        // 一路带到 `saveColorsAndSkus`（`List.of(null)` NPE），把「长度准入有没有拦住」淹掉。
        when(productMapper.insert(any(Product.class))).thenAnswer(invocation -> {
            ((Product) invocation.getArgument(0)).setId("prod-6302");
            return 1;
        });
        // 端点面：真 ProductService（桩 mapper）+ 真 GlobalExceptionHandler —— 422 是**真**走出来的。
        mockMvc = MockMvcBuilders.standaloneSetup(new ProductController(productService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ==================== ① 实例判据：表单路径（本单的靶心）====================

    @Test
    @DisplayName("判据1：POST /api/admin/products 传 31 字符 skuCode ⇒ 422 + 可行动文案（不是 500）+ 零写入")
    void overlongProductSkuCodeIsRejectedWithActionableMessage() throws Exception {
        String long1 = "A".repeat(PRODUCTS_SKU_CODE_MAX + 1);

        mockMvc.perform(post("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"遮光窗帘布\",\"skuCode\":\"" + long1 + "\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                // 可行动文案：告诉用户**哪一列**、**上限多少**、**当前多长**、**怎么办**
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString(
                        "最长 " + PRODUCTS_SKU_CODE_MAX + " 个字符")))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString(
                        "当前 " + (PRODUCTS_SKU_CODE_MAX + 1) + " 个字符")))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("请缩短")));

        // 「返回了错误」≠「没写进去」：超长货号必须**一处都不落库**
        verify(productMapper, never()).insert(any(Product.class));
        verify(productMapper, never()).updateById(any(Product.class));
    }

    @Test
    @DisplayName("判据2（边界）：恰好 = 列上限 ⇒ 放行到写面（长度准入不拦它）")
    void productSkuCodeAtColumnLimitPassesTheLengthGate() throws Exception {
        String atLimit = "A".repeat(PRODUCTS_SKU_CODE_MAX);

        String body = mockMvc.perform(post("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"遮光窗帘布\",\"skuCode\":\"" + atLimit + "\"}"))
                .andReturn().getResponse().getContentAsString();

        assertThat(body)
                .as("长度 = 列上限是**合法**输入（issue #6302 实测 len=30 → 200）⇒ 不得被长度准入拦下")
                .doesNotContain("最长 " + PRODUCTS_SKU_CODE_MAX + " 个字符");
        verify(productMapper).insert(any(Product.class));
    }

    @Test
    @DisplayName("判据3：改品路径（PUT）同上 —— 30 字符放行到下一步、31 字符 422 + 可行动文案")
    void updateProductUsesTheSameGate() throws Exception {
        mockMvc.perform(put("/api/admin/products/prod-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        // name 必填（`ProductUpdateRequest.name` 的 @NotBlank）⇒ 不带它会被 Bean Validation
                        // 先拦下（422「参数校验失败」），那样就测不到本单的长度判据了。
                        .content("{\"name\":\"遮光窗帘布\",\"skuCode\":\""
                                + "B".repeat(PRODUCTS_SKU_CODE_MAX + 1) + "\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString(
                        "最长 " + PRODUCTS_SKU_CODE_MAX + " 个字符")));
        verify(productMapper, never()).updateById(any(Product.class));

        // 边界：30 字符 ⇒ 长度准入放行（此处落到「商品不存在」= 闸门之后的下一步）
        BusinessException atLimit = (BusinessException) org.assertj.core.api.Assertions.catchThrowable(
                () -> productService.updateProduct("prod-001",
                        updateRequestWithSkuCode("B".repeat(PRODUCTS_SKU_CODE_MAX)), 1L));
        assertThat(atLimit).as("长度 = 列上限必须在长度准入处放行").isNotNull();
        assertThat(atLimit.getCode()).as("放行后的失败原因必须是「商品不存在」，不是长度准入").isEqualTo("NOT_FOUND");
        assertThat(atLimit.getMessage()).doesNotContain("最长 " + PRODUCTS_SKU_CODE_MAX);
    }

    // ==================== ② 同族写面：SKU 编码 / 门幅 / 颜色名 ====================

    @Test
    @DisplayName("判据4：SKU 级 skuCode 超 50 / 门幅超 20 / 颜色名超 30 ⇒ 各自 422 + 具名文案（SKU/颜色表零写入）")
    void skuFaceOverlongFieldsAreRejectedFromOneGate() {
        Map<String, Executable> faces = new LinkedHashMap<>();
        faces.put("skus[].skuCode 51（库列 product_skus.sku_code varchar(50)）", () ->
                productService.createProduct(createRequestWithSku(
                        skuWith("B".repeat(PRODUCT_SKUS_SKU_CODE_MAX + 1), "2.8m", "米白")), 1L));
        faces.put("skus[].doorWidth 21（库列 product_skus.door_width varchar(20)）", () ->
                productService.createProduct(createRequestWithSku(
                        skuWith("SKU-OK", "2".repeat(PRODUCT_SKUS_DOOR_WIDTH_MAX + 1) + "m", "米白")), 1L));
        faces.put("colors[].colorName 31（库列 product_colors.color_name varchar(30)）", () ->
                productService.createProduct(createRequestWithColor(
                        "米".repeat(PRODUCT_COLORS_COLOR_NAME_MAX + 1)), 1L));

        assertThat(faces).as("三个同族写面缺一不可").hasSize(3);
        for (Map.Entry<String, Executable> face : faces.entrySet()) {
            assertThatThrownBy(face.getValue()::execute)
                    .as("写面「%s」必须被长度准入拒绝", face.getKey())
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("最长")
                    .hasMessageContaining("当前");
        }
        // 零写入（SKU / 颜色面）：长度准入先于这两张表的任何写。
        // 注：`products` 主表那一行是 createProduct 在收口**之前**插入的（#6228 同款既有顺序），
        // 生产由 `@Transactional(rollbackFor = Exception.class)` 回滚；桩测里没有事务管理器，故不判它。
        verify(productSkuMapper, never()).insert(any(ProductSku.class));
        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        verify(productColorMapper, never()).insert(any(ProductColor.class));
        verify(productColorMapper, never()).updateById(any(ProductColor.class));
    }

    // ==================== ③ 家族覆盖：不走 Bean Validation 的路径 ====================

    @Test
    @DisplayName("判据5：agent 路径（手工 new DTO，**不经过 @Valid**）同样被拒 —— 只加 DTO @Size 会漏掉它")
    void agentPathIsGatedTooEvenThoughItSkipsBeanValidation() {
        ProductCreateRequest agentShaped = new ProductCreateRequest();
        agentShaped.setName("agent 建品");
        agentShaped.setSkuCode("C".repeat(PRODUCTS_SKU_CODE_MAX + 1));

        // 这正是 ProductService#createProductForAgent 的形态：手工 new + 直接调 service ⇒ Bean Validation 不来
        BusinessException e = (BusinessException) org.assertj.core.api.Assertions
                .catchThrowable(() -> productService.createProduct(agentShaped, 1L));

        assertThat(e).isNotNull();
        assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(e.getMessage()).contains("商品货号 skuCode").contains("最长 30 个字符").contains("当前 31");
        verify(productMapper, never()).insert(any(Product.class));
    }

    // ==================== 夹具 ====================

    private ProductCreateRequest createRequestWithSku(ProductSkuInput sku) {
        ProductCreateRequest request = baseCreateRequest();
        request.setSkus(List.of(sku));
        return request;
    }

    private ProductCreateRequest createRequestWithColor(String colorName) {
        ProductCreateRequest request = baseCreateRequest();
        ProductColorInput color = new ProductColorInput();
        color.setColorName(colorName);
        request.setColors(List.of(color));
        return request;
    }

    private ProductCreateRequest baseCreateRequest() {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("遮光窗帘布");
        request.setSkuCode("MG-6302");
        request.setBasePrice(new BigDecimal("199.00"));
        return request;
    }

    private ProductSkuInput skuWith(String skuCode, String doorWidth, String colorName) {
        ProductSkuInput sku = new ProductSkuInput();
        sku.setSkuCode(skuCode);
        sku.setDoorWidth(doorWidth);
        sku.setColorName(colorName);
        sku.setPrice(new BigDecimal("199.00"));
        return sku;
    }

    private ProductUpdateRequest updateRequestWithSkuCode(String skuCode) {
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setSkuCode(skuCode);
        return request;
    }
}
