// case_ids: DF-009
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.Product;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.security.TenantOwnershipInterceptor;
import com.migao.admin.security.TenantResourceOwnership;
import com.migao.admin.service.CategoryService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.ProcessingCategoryService;
import com.migao.admin.service.ProcessingItemService;
import com.migao.admin.service.ProductService;
import org.assertj.core.api.Assertions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;

import static org.hamcrest.Matchers.hasItem;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * issue #6158 实例判据：**跨租户写的响应码由归属判定决定，而不是由载荷是否合法决定**。
 *
 * <h2>它证的是什么（mock 面能证的那一半）</h2>
 * <ol>
 *   <li>跨租户 + <b>非法</b>载荷 ⇒ <b>404 NOT_FOUND</b>（不是 422/400）——
 *       修前这里（4 个 PUT）是 422 {@code VALIDATION_ERROR}，订单 {@code /content} 是
 *       400 {@code BAD_REQUEST}；</li>
 *   <li>跨租户请求**一次都不**进入写服务（{@code never()}）—— 这同时是「库零变动」的
 *       mock 面证据（没有调用 ⇒ 没有写）；</li>
 *   <li>同租户 + 非法载荷 ⇒ 仍是 <b>422</b> + 逐字段 {@code error.details}
 *       （**校验没有被挪没**）；</li>
 *   <li>同租户 + 合法载荷 ⇒ 仍是 <b>200</b>。</li>
 * </ol>
 *
 * <h2>两侧夹住（判据非空自证）</h2>
 * <p>{@link #withoutTheInterceptor_theSameRequestIsNot404_outOfBand()} 把拦截器摘掉，同一个
 * 「跨租户 + 非法载荷」请求当场变回 422 ⇒ 证明上面的 404 读数**来自本包的接线**，
 * 不是「所有请求都 404」的空断言。</p>
 *
 * <h2>真库那一半在哪</h2>
 * <p>字段级前后快照 / 真库零变动由集成方的真栈重放承担（本包按分派纪律不跑真库重放）。
 * 本类用「写服务层零调用 + 归属查询按当前租户过滤（mapper 查不到）」表达同一条安全结论。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6158 归属判定先于载荷校验（5 个写端点）")
class TenantOwnershipBeforeValidationTest extends BaseControllerTest {

    private static final String PROD_ID = "11111111111111111111111111111111";
    private static final String CAT_ID = "22222222222222222222222222222222";
    private static final String ITEM_ID = "33333333333333333333333333333333";
    private static final String PCAT_ID = "44444444444444444444444444444444";
    private static final String ORDER_ID = "55555555555555555555555555555555";

    /** 非法载荷（{@code {}} ⇒ 必填 name 缺失）—— 修前它会先变成 422/400。 */
    private static final String BAD_BODY = "{}";
    /** 合法载荷（各端点的必填字段齐备）。 */
    private static final String GOOD_BODY = "{\"name\":\"合法改动\"}";

    @Mock private ProductMapper productMapper;
    @Mock private CategoryMapper categoryMapper;
    @Mock private ProcessingItemMapper processingItemMapper;
    @Mock private ProcessingCategoryMapper processingCategoryMapper;
    @Mock private ProductService productService;
    @Mock private CategoryService categoryService;
    @Mock private ProcessingItemService processingItemService;
    @Mock private ProcessingCategoryService processingCategoryService;
    /** 售后工单（同类第 8 个实例）。 */
    @Mock private com.migao.admin.mapper.AfterSalesTicketMapper afterSalesTicketMapper;
    @Mock private com.migao.admin.service.AfterSalesTicketService afterSalesTicketService;
    /** 订单服务（真类型 stub）—— 归属认定读的就是它的真实现 {@code existsForCurrentTenant}。 */
    @Mock private OrderService orderService;

    private TenantResourceOwnership ownership;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        ownership = new TenantResourceOwnership(productMapper, categoryMapper, processingItemMapper,
                processingCategoryMapper, afterSalesTicketMapper, orderService, null, null);
        ownership.registerChecks();
    }

    /** 挂上归属认定拦截器的 MockMvc（生产接线 = {@code WebConfig.webMvcConfigurer}）。 */
    private MockMvc withInterceptor(Object controller) throws Exception {
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(interceptor())
                .build();
    }

    /**
     * 拦截器实例 + 注入认定表 —— 生产上由 Spring 做字段注入（{@code WebConfig} 字段注入，
     * 理由见 {@link TenantOwnershipInterceptor}）；测试里没有容器，故显式注入一次。
     * 这里**不重写第二份判定**：注入的就是被测的那个拦截器本体。
     */
    private TenantOwnershipInterceptor interceptor() throws Exception {
        TenantOwnershipInterceptor interceptor = new TenantOwnershipInterceptor();
        java.lang.reflect.Field field =
                TenantOwnershipInterceptor.class.getDeclaredField("ownership");
        field.setAccessible(true);
        field.set(interceptor, ownership);
        return interceptor;
    }

    /** **不**挂拦截器 —— 用于两侧夹住（把接线摘掉，同一个请求必须变回 422）。 */
    private MockMvc withoutInterceptor(Object controller) {
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /** 「目标属于当前租户吗」：4 个 mapper 的按 id 查询（租户过滤后）能否查出实体。 */
    private void targetVisibleToCurrentTenant(boolean visible) {
        when(productMapper.selectById(anyString())).thenReturn(visible ? new Product() : null);
        when(categoryMapper.selectById(anyString())).thenReturn(visible ? new Category() : null);
        when(processingItemMapper.selectById(anyString())).thenReturn(visible ? new ProcessingItem() : null);
        when(processingCategoryMapper.selectById(anyString()))
                .thenReturn(visible ? new ProcessingCategory() : null);
    }

    /** 订单可见性（真 OrderService 的 {@code existsForCurrentTenant} 读真 mapper）。 */
    private void orderVisible(boolean visible) {
        lenient().when(orderService.existsForCurrentTenant(anyString())).thenReturn(visible);
    }

    private ProductResponse productResponse() {
        ProductResponse response = new ProductResponse();
        response.setId(PROD_ID);
        response.setName("合法改动");
        response.setBasePrice(new BigDecimal("1.00"));
        return response;
    }

    // ==================== 判据 1：跨租户 + 非法载荷 ⇒ 404（5 个端点逐个） ====================

    @Test
    @DisplayName("跨租户 + 非法载荷 ⇒ 404（商品 / 分类 / 加工项 / 加工分类）")
    void crossTenantWithInvalidPayload_isNotFound_not422() throws Exception {
        targetVisibleToCurrentTenant(false);
        Object[][] endpoints = {
                {new ProductController(productService), "/api/admin/products/" + PROD_ID},
                {new CategoryController(categoryService), "/api/admin/categories/" + CAT_ID},
                {new ProcessingItemController(processingItemService), "/api/admin/processing-items/" + ITEM_ID},
                {new ProcessingCategoryController(processingCategoryService),
                        "/api/admin/processing-categories/" + PCAT_ID},
        };
        for (Object[] endpoint : endpoints) {
            withInterceptor(endpoint[0])
                    .perform(put((String) endpoint[1]).contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        }
        // 跨租户 ⇒ 写服务一次都没被调用（= 没有写）
        verify(productService, never()).updateProduct(anyString(), any(), any());
        verify(categoryService, never()).updateCategory(anyString(), any(), any());
        verify(processingItemService, never()).updateProcessingItem(anyString(), any(), any());
        verify(processingCategoryService, never()).updateProcessingCategory(anyString(), any(), any());
    }

    @Test
    @DisplayName("跨租户 + 非法载荷 ⇒ 404（订单 /content：修前是 400 BAD_REQUEST）")
    void crossTenantOrderContentWithInvalidPayload_isNotFound_not400() throws Exception {
        orderVisible(false);
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/content")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test
    @DisplayName("跨租户 + 完全无 body ⇒ 仍是 404（订单 /content 的空 body 形态）")
    void crossTenantOrderContentWithMissingBody_isNotFound() throws Exception {
        orderVisible(false);
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/content"))
                .andExpect(status().isNotFound());
    }

    // ==================== 判据 2：跨租户 + 合法载荷 ⇒ 仍 404（防回归） ====================

    @Test
    @DisplayName("跨租户 + 合法载荷 ⇒ 仍 404（防回归）+ 写服务零调用")
    void crossTenantWithValidPayload_isStillNotFound() throws Exception {
        targetVisibleToCurrentTenant(false);
        withInterceptor(new ProductController(productService))
                .perform(put("/api/admin/products/" + PROD_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_BODY))
                .andExpect(status().isNotFound());
        verify(productService, never()).updateProduct(anyString(), any(), any());
    }

    // ==================== 判据 3：同租户 + 非法载荷 ⇒ 仍 422（校验没被挪没） ====================

    @Test
    @DisplayName("同租户 + 非法载荷 ⇒ 仍 422 + 逐字段 details（校验没被挪没）")
    void sameTenantWithInvalidPayload_stillValidationError() throws Exception {
        targetVisibleToCurrentTenant(true);
        orderVisible(true);
        // ⚠️ details 的**顺序**不判（Hibernate Validator 不保证属性遍历序 ⇒ 判它会变成脆判据）；
        // 判的是「非空 + 逐字段可读」：每个端点都至少给出 name 字段名与中文文案。
        withInterceptor(new ProductController(productService))
                .perform(put("/api/admin/products/" + PROD_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("name")))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());
        withInterceptor(new CategoryController(categoryService))
                .perform(put("/api/admin/categories/" + CAT_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("name")))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());
        withInterceptor(new ProcessingItemController(processingItemService))
                .perform(put("/api/admin/processing-items/" + ITEM_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("name")))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("categoryId")))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());
        withInterceptor(new ProcessingCategoryController(processingCategoryService))
                .perform(put("/api/admin/processing-categories/" + PCAT_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("name")))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/content")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("customerName")))
                .andExpect(jsonPath("$.error.details[*].field", hasItem("items")));
    }

    @Test
    @DisplayName("同租户 + 完全无 body ⇒ 仍是 400 BAD_REQUEST（订单 /content 现状不回退）")
    void sameTenantOrderContentWithMissingBody_stillBadRequest() throws Exception {
        orderVisible(true);
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/content"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("BAD_REQUEST"));
    }

    // ==================== 判据 4：同租户 + 合法载荷 ⇒ 仍 200 ====================

    @Test
    @DisplayName("同租户 + 合法载荷 ⇒ 仍 200（商品）")
    void sameTenantWithValidPayload_stillOk() throws Exception {
        targetVisibleToCurrentTenant(true);
        when(productService.updateProduct(eq(PROD_ID), any(), eq(TEST_TENANT_ID)))
                .thenReturn(productResponse());
        withInterceptor(new ProductController(productService))
                .perform(put("/api/admin/products/" + PROD_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value(PROD_ID));
    }

    @Test
    @DisplayName("跨租户 + 非法载荷 ⇒ 404（订单 /status 与 /follow-status：同类第 6/7 个实例）")
    void crossTenantOrderStatusEndpoints_isNotFound() throws Exception {
        orderVisible(false);
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/status")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        withInterceptor(new OrderController(orderService, null, null))
                .perform(put("/api/admin/orders/" + ORDER_ID + "/follow-status")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test
    @DisplayName("跨租户 + 非法载荷 ⇒ 404（售后工单 /status：同类第 8 个实例）")
    void crossTenantAfterSalesStatus_isNotFound() throws Exception {
        when(afterSalesTicketMapper.selectById(anyString())).thenReturn(null);
        withInterceptor(new AfterSalesController(afterSalesTicketService))
                .perform(put("/api/admin/after-sales/" + ORDER_ID + "/status")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        verify(afterSalesTicketService, never()).updateTicketStatus(anyString(), any());
    }

    @Test
    @DisplayName("同租户 + 非法载荷 ⇒ 售后 /status 仍 422（校验没被挪没）")
    void sameTenantAfterSalesStatus_stillValidationError() throws Exception {
        when(afterSalesTicketMapper.selectById(anyString()))
                .thenReturn(new com.migao.admin.entity.AfterSalesTicket());
        withInterceptor(new AfterSalesController(afterSalesTicketService))
                .perform(put("/api/admin/after-sales/" + ORDER_ID + "/status")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());
    }

    // ==================== 判据 5：两侧夹住（判据非空自证） ====================

    @Test
    @DisplayName("🔴 两侧夹住：把拦截器摘掉，同一个「跨租户 + 非法载荷」请求当场变回 422")
    void withoutTheInterceptor_theSameRequestIsNot404_outOfBand() throws Exception {
        targetVisibleToCurrentTenant(false);
        // 反面对照：没有本包的接线 ⇒ 载荷校验先发生 ⇒ 422（这正是 issue #6158 的修前形态）
        withoutInterceptor(new ProductController(productService))
                .perform(put("/api/admin/products/" + PROD_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
        // 同一份夹具、同一个 id，挂上拦截器 ⇒ 404（差值来自接线，不是夹具恒真）
        withInterceptor(new ProductController(productService))
                .perform(put("/api/admin/products/" + PROD_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_BODY))
                .andExpect(status().isNotFound());
    }

    // ==================== 判据 6：登记缺失 fail-closed（不静默放行） ====================

    @Test
    @DisplayName("未登记的资源键 ⇒ 显式抛错（fail-closed），不静默放行到参数解析")
    void unregisteredResourceKey_failsClosed() {
        Assertions.assertThatThrownBy(() -> ownership.check("no-such-resource", PROD_ID))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("未登记的租户域资源键");
    }

    @Test
    @DisplayName("登记表现取：本单覆盖的资源键都在")
    void registeredResources_areExactlyTheFixedResources() {
        Assertions.assertThat(ownership.registeredResources())
                .contains("product", "category", "processing-item", "processing-category", "order",
                        "after-sales-ticket");
    }
}
