// case_ids: PR-134
// 商品颜色入参**字段名不合法**（issue #9012）：`POST /api/admin/products` 传
// `colors:[{"name":"米白","code":"#F5F5DC"}]`（正确字段名是 colorName / mainColorHex）⇒
// Jackson `FAIL_ON_UNKNOWN_PROPERTIES=false`（Spring Boot 缺省）**静默丢弃**未知字段 ⇒
// `colorName` 为 null ⇒ service 照常 insert ⇒ 撞 `product_colors.color_name` 的 NOT NULL ⇒
// `DataIntegrityViolationException` 冒到全局处理器 ⇒ **HTTP 500 INTERNAL_ERROR**。
// 生产实抓（requestId `req_809f888b9ae44438`，tenant 1）：
//   `PSQLException: ERROR: null value in column "color_name" of relation "product_colors"
//    violates not-null constraint`
//   `Detail: Failing row contains (…, null, null, null, null, 0, …)`
//   `INSERT INTO product_colors (id, tenant_id, product_id, sort_order, created_at, updated_at)`
//
// 本文件按铁律 8 分两层：
//   ① **实例判据**（本文件）：非法颜色入参 ⇒ **422 + 中文文案 + 指出字段名 colorName**（不是 500），
//      且 `product_colors` **零写入**；合法颜色不得被挡（边界正对照）；不走 Bean Validation 的
//      agent / Excel 路径同源拒绝（只给 DTO 加注解会漏掉它们 —— 见 #6302 的实测结论）。
//   ② **类级元守卫**（`GlobalExceptionHandlerDataIntegrityTest#notNullViolationIsMappedTo…`）：
//      非空约束违例这一类**不再以 500 冒充「服务器内部错误」**，且响应/日志都不泄漏列名表名 ——
//      即便将来另有一张表、另一个漏校验的字段撞上 NOT NULL，客户端拿到的也是 422「参数不合法」。
//      反向对照 = 同一文件 `uniqueViolationKeepsTheExistingFiveHundredContract`（唯一约束仍 5xx，
//      既有契约不因本单放宽）。
//
// 边界（如实登记）：本文件用**桩 mapper**（不连库、不连网，离线可跑）——`productColorMapper.insert`
// 抛的是**真的** PG 非空违例形状（SQLState `23502` + 逐字 message）。改前那条链会走到它 ⇒ 500（红），
// 改后走不到它 ⇒ 422（绿），判别力就来自这里。桩 mapper ≠ 真库：真库面（列是否真的 NOT NULL）
// 由 `docs/sql/schema.sql` 与 `ProductTextColumnAdmissionMetaGuardTest` 的现取对账承担。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.ProductController;
import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
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
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.sql.SQLException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;
import static org.hamcrest.Matchers.containsString;
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
@DisplayName("商品颜色入参字段名不合法 ⇒ 422 指出 colorName（issue #9012）")
class ProductColorNameAdmissionTest {

    /** PG 的 NOT NULL 违例（SQL:2003 完整性约束类 23 的非空码）。 */
    private static final String NOT_NULL_SQLSTATE = "23502";
    /** 与生产日志（requestId req_809f888b9ae44438）逐字同形的约束消息 —— 桩要像真库。 */
    private static final String PG_NOT_NULL_MESSAGE =
            "ERROR: null value in column \"color_name\" of relation \"product_colors\" violates not-null constraint";

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
        // 一路带到 `saveColorsAndSkus`（`List.of(null)` NPE），把「颜色名称准入有没有拦住」淹掉。
        when(productMapper.insert(any(Product.class))).thenAnswer(invocation -> {
            ((Product) invocation.getArgument(0)).setId("prod-9012");
            return 1;
        });

        // 端点面：真 ProductService（桩 mapper）+ 真 GlobalExceptionHandler ⇒ 422 是**真**走出来的。
        // 🔴 Jackson 必须与应用同口径：Spring Boot 缺省 `FAIL_ON_UNKNOWN_PROPERTIES=false`
        // （本仓 application.yml 未改这一项）⇒ 未知字段被**静默丢弃**，正是本 issue 的根因链第一节。
        // standalone MockMvc 的缺省 ObjectMapper 是 true（会先把未知字段拦成 400），
        // 那会**掩盖**根因链、把本判据变成假绿 ⇒ 显式对齐应用口径。
        ObjectMapper appJackson = new ObjectMapper()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        mockMvc = MockMvcBuilders.standaloneSetup(new ProductController(productService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(appJackson))
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ==================== ① 实例判据（本单的靶心）====================

    @Test
    @DisplayName("判据1：colors:[{name,code}]（字段名猜错）⇒ 422 + 指出 colorName，不是 500，且颜色表零写入")
    void unknownColorFieldNamesAreRejectedWithFieldNameNotServerError() throws Exception {
        // 桩 = 真库会怎么回：该入参若真走到 insert，PG 报的就是这条非空违例（改前 ⇒ 500）。
        when(productColorMapper.insert(any(ProductColor.class))).thenThrow(pgNotNullViolation());

        String body = mockMvc.perform(post("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"遮光窗帘布\",\"colors\":[{\"name\":\"米白\",\"code\":\"#F5F5DC\"}]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                // 中文文案 + **指出字段名**（客户端才知道该改哪个键）
                .andExpect(jsonPath("$.error.message").value(containsString("颜色名称")))
                .andExpect(jsonPath("$.error.message").value(containsString("colorName")))
                .andReturn().getResponse().getContentAsString();

        // 响应体不许泄漏数据库细节（列名 / 表名 / PG 原文）—— 也不许再是「服务器内部错误」
        assertThat(body)
                .doesNotContain("服务器内部错误")
                .doesNotContain("color_name")
                .doesNotContain("product_colors")
                .doesNotContain("not-null");

        // 「返回了 4xx」≠「没写进去」：非法颜色必须一处都不落 `product_colors`
        verify(productColorMapper, never()).insert(any(ProductColor.class));
    }

    @Test
    @DisplayName("判据2：colorName 只有空白（\"   \"）⇒ 同一道准入 422（NOT NULL 列不接受空白）")
    void blankColorNameIsRejectedWithTheSameFieldName() throws Exception {
        when(productColorMapper.insert(any(ProductColor.class))).thenThrow(pgNotNullViolation());

        mockMvc.perform(post("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"遮光窗帘布\",\"colors\":[{\"colorName\":\"   \"}]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(containsString("colorName")));

        verify(productColorMapper, never()).insert(any(ProductColor.class));
    }

    @Test
    @DisplayName("判据3（边界正对照）：合法 colorName ⇒ 准入放行到写面（不得把合法颜色挡掉）")
    void validColorNamePassesTheGate() throws Exception {
        mockMvc.perform(post("/api/admin/products")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"遮光窗帘布\",\"colors\":[{\"colorName\":\"米白\",\"mainColorHex\":\"#F5F5DC\"}]}"));

        ArgumentCaptor<ProductColor> inserted = ArgumentCaptor.forClass(ProductColor.class);
        verify(productColorMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getColorName())
                .as("合法颜色必须原样放行（准入是 fail-closed，不是 fail-all）")
                .isEqualTo("米白");
        assertThat(inserted.getValue().getMainColorHex()).isEqualTo("#F5F5DC");
    }

    @Test
    @DisplayName("判据4：改品路径（PUT）走同一道准入 ⇒ 422 + colorName，颜色表零写入")
    void updatePathUsesTheSameGate() throws Exception {
        Product existing = new Product();
        existing.setId("prod-9012");
        existing.setTenantId(1L);
        existing.setStatus("draft");
        when(productMapper.selectById("prod-9012")).thenReturn(existing);
        when(productColorMapper.insert(any(ProductColor.class))).thenThrow(pgNotNullViolation());

        mockMvc.perform(put("/api/admin/products/prod-9012")
                        .contentType(MediaType.APPLICATION_JSON)
                        // name 必填（`ProductUpdateRequest.name` 的 @NotBlank）⇒ 不带它会被 Bean Validation
                        // 先拦下，那样就测不到本单的颜色名称判据了。
                        .content("{\"name\":\"遮光窗帘布\",\"colors\":[{\"name\":\"米白\"}]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(containsString("colorName")));

        verify(productColorMapper, never()).insert(any(ProductColor.class));
    }

    // ==================== ② 家族覆盖：不走 Bean Validation 的路径 ====================

    @Test
    @DisplayName("判据5：agent / Excel 路径（手工 new DTO，**不经过 @Valid**）同源被拒 —— 只加 DTO 注解会漏掉它")
    void nonHttpPathsAreGatedTooEvenThoughTheySkipBeanValidation() {
        ProductCreateRequest agentShaped = new ProductCreateRequest();
        agentShaped.setName("agent 建品");
        // 生产里「字段名猜错」的等价形态：Jackson 丢掉了 name/code ⇒ colorName 仍是 null
        agentShaped.setColors(List.of(new ProductColorInput()));

        Throwable thrown = catchThrowable(() -> productService.createProduct(agentShaped, 1L));

        assertThat(thrown).isInstanceOf(BusinessException.class);
        BusinessException e = (BusinessException) thrown;
        assertThat(e.getCode()).as("参数不合法 ⇒ VALIDATION_ERROR（422）").isEqualTo("VALIDATION_ERROR");
        assertThat(e.getMessage())
                .as("文案必须指出字段名 colorName，否则 agent / 导入侧同样无法自救")
                .contains("颜色名称")
                .contains("colorName");
        verify(productColorMapper, never()).insert(any(ProductColor.class));
    }

    // ==================== 夹具 ====================

    /** 真库形状的非空违例（SQLState 23502 + 逐字 PG 消息），**不是**随便一个 RuntimeException。 */
    private static DataIntegrityViolationException pgNotNullViolation() {
        return new DataIntegrityViolationException(
                PG_NOT_NULL_MESSAGE, new SQLException(PG_NOT_NULL_MESSAGE, NOT_NULL_SQLSTATE));
    }
}
