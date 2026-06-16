package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * ProductController 单元测试（@WebMvcTest + MockMvc standalone）
 * 覆盖：12 个端点，含成功路径 / 参数校验 / 业务异常 / 租户隔离
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductController 商品管理测试")
class ProductControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProductService productService;

    @InjectMocks
    private ProductController productController;

    private static final String BASE = "/api/admin/products";
    private static final String PROD_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(productController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    // ==================== 辅助方法 ====================

    private ProductResponse buildProduct(String id, String name, String status) {
        ProductResponse p = new ProductResponse();
        p.setId(id);
        p.setName(name);
        p.setStatus(status);
        p.setBasePrice(new BigDecimal("299.00"));
        p.setCategoryId("cat-001");
        p.setCategoryName("遮光窗帘");
        p.setMainImage("https://img.example.com/p1.jpg");
        p.setCreatedAt(java.time.OffsetDateTime.now());
        p.setUpdatedAt(java.time.OffsetDateTime.now());
        return p;
    }

    // ==================== GET /api/admin/products ====================

    @Nested
    @DisplayName("GET /api/admin/products — 商品列表")
    class GetProducts {

        @Test
        @DisplayName("分页查询 -> 200 + PageResponse")
        void listPaginated() throws Exception {
            PageResponse<ProductResponse> page = PageResponse.of(2L, 1L, 20L,
                    List.of(buildProduct(PROD_ID, "遮光窗帘A", "on_sale"),
                            buildProduct("prod-002", "遮光窗帘B", "off_sale")));

            when(productService.getProducts(any(ProductQueryRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(page);

            mockMvc.perform(get(BASE).param("page", "1").param("size", "20"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.total").value(2))
                    .andExpect(jsonPath("$.data.items[0].name").value("遮光窗帘A"))
                    .andExpect(jsonPath("$.data.items[1].status").value("off_sale"));
        }

        @Test
        @DisplayName("关键词搜索 -> 200")
        void searchByKeyword() throws Exception {
            PageResponse<ProductResponse> page = PageResponse.of(1L, 1L, 20L,
                    List.of(buildProduct(PROD_ID, "遮光窗帘A", "on_sale")));

            when(productService.getProducts(argThat(q -> "窗帘".equals(q.getKeyword())), eq(TEST_TENANT_ID)))
                    .thenReturn(page);

            mockMvc.perform(get(BASE).param("keyword", "窗帘"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.items[0].name").value("遮光窗帘A"));
        }

        @Test
        @DisplayName("空列表 -> 200 + items=[]")
        void emptyList() throws Exception {
            when(productService.getProducts(any(ProductQueryRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.total").value(0))
                    .andExpect(jsonPath("$.data.items").isArray())
                    .andExpect(jsonPath("$.data.items").isEmpty());
        }
    }

    // ==================== GET /api/admin/products/{id} ====================

    @Nested
    @DisplayName("GET /api/admin/products/{id} — 商品详情")
    class GetProductById {

        @Test
        @DisplayName("查询详情 -> 200 + 完整字段")
        void detail() throws Exception {
            ProductResponse p = buildProduct(PROD_ID, "遮光窗帘A", "on_sale");
            when(productService.getProductById(PROD_ID, TEST_TENANT_ID)).thenReturn(p);

            mockMvc.perform(get(BASE + "/" + PROD_ID))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.id").value(PROD_ID))
                    .andExpect(jsonPath("$.data.name").value("遮光窗帘A"))
                    .andExpect(jsonPath("$.data.price").value(299.00));
        }

        @Test
        @DisplayName("商品不存在 -> 404")
        void notFound() throws Exception {
            when(productService.getProductById("nonexistent", TEST_TENANT_ID))
                    .thenThrow(new BusinessException("NOT_FOUND", "商品不存在", 404));

            mockMvc.perform(get(BASE + "/nonexistent"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        }
    }

    // ==================== POST /api/admin/products ====================

    @Nested
    @DisplayName("POST /api/admin/products — 创建商品")
    class CreateProduct {

        @Test
        @DisplayName("创建成功 -> 200")
        void create() throws Exception {
            ProductResponse p = buildProduct(PROD_ID, "新商品", "off_sale");
            when(productService.createProduct(any(ProductCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(p);

            String body = """
                    {"name":"新商品","categoryId":"cat-001","price":299.00,"status":"off_sale"}
                    """;

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.name").value("新商品"))
                    .andExpect(jsonPath("$.data.status").value("off_sale"));
        }

        @Test
        @DisplayName("缺少必填字段 -> 422")
        void missingRequiredField() throws Exception {
            String body = "{}";

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
        }
    }

    // ==================== PUT /api/admin/products/{id} ====================

    @Nested
    @DisplayName("PUT /api/admin/products/{id} — 编辑商品")
    class UpdateProduct {

        @Test
        @DisplayName("更新成功 -> 200")
        void update() throws Exception {
            ProductResponse p = buildProduct(PROD_ID, "已更新商品", "on_sale");
            when(productService.updateProduct(eq(PROD_ID), any(ProductUpdateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(p);

            String body = """
                    {"name":"已更新商品","price":399.00}
                    """;

            mockMvc.perform(put(BASE + "/" + PROD_ID)
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.name").value("已更新商品"));
        }

        @Test
        @DisplayName("更新不存在的商品 -> 404")
        void updateNotFound() throws Exception {
            when(productService.updateProduct(eq("nonexistent"), any(ProductUpdateRequest.class), eq(TEST_TENANT_ID)))
                    .thenThrow(new BusinessException("NOT_FOUND", "商品不存在", 404));

            String body = "{\"name\":\"x\"}";

            mockMvc.perform(put(BASE + "/nonexistent")
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isNotFound());
        }
    }

    // ==================== DELETE /api/admin/products/{id} ====================

    @Nested
    @DisplayName("DELETE /api/admin/products/{id} — 删除商品")
    class DeleteProduct {

        @Test
        @DisplayName("删除成功 -> 200")
        void deleteSuccess() throws Exception {
            doNothing().when(productService).deleteProduct(PROD_ID, TEST_TENANT_ID);

            mockMvc.perform(delete(BASE + "/" + PROD_ID))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            verify(productService).deleteProduct(PROD_ID, TEST_TENANT_ID);
        }

        @Test
        @DisplayName("删除不存在的商品 -> 404")
        void deleteNotFound() throws Exception {
            doThrow(new BusinessException("NOT_FOUND", "商品不存在", 404))
                    .when(productService).deleteProduct("nonexistent", TEST_TENANT_ID);

            mockMvc.perform(delete(BASE + "/nonexistent"))
                    .andExpect(status().isNotFound());
        }
    }

    // ==================== PUT /api/admin/products/{id}/status ====================

    @Nested
    @DisplayName("PUT /api/admin/products/{id}/status — 上下架")
    class UpdateStatus {

        @Test
        @DisplayName("上架 -> 200")
        void onShelf() throws Exception {
            doNothing().when(productService).updateProductStatus(PROD_ID, "on_sale", TEST_TENANT_ID);

            mockMvc.perform(put(BASE + "/" + PROD_ID + "/status")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"status\":\"on_sale\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("下架 -> 200")
        void offShelf() throws Exception {
            doNothing().when(productService).updateProductStatus(PROD_ID, "off_sale", TEST_TENANT_ID);

            mockMvc.perform(put(BASE + "/" + PROD_ID + "/status")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"status\":\"off_sale\"}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("非法状态值 -> 422")
        void invalidStatus() throws Exception {
            doThrow(new BusinessException("VALIDATION_ERROR", "非法的状态值: deleted", 422))
                    .when(productService).updateProductStatus(PROD_ID, "deleted", TEST_TENANT_ID);

            mockMvc.perform(put(BASE + "/" + PROD_ID + "/status")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"status\":\"deleted\"}"))
                    .andExpect(status().isUnprocessableEntity());
        }
    }

    // ==================== GET /api/admin/products/low-stock-by-color ====================

    @Nested
    @DisplayName("GET /api/admin/products/low-stock-by-color — 低库存告警")
    class LowStock {

        @Test
        @DisplayName("默认阈值 -> 200")
        void defaultThreshold() throws Exception {
            LowStockByColorResponse item = new LowStockByColorResponse();
            item.setColorName("深灰");
            item.setDoorWidth("2.5m");
            item.setStock(50);

            when(productService.getLowStockByColor(TEST_TENANT_ID, 100, 50))
                    .thenReturn(List.of(item));

            mockMvc.perform(get(BASE + "/low-stock-by-color"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data[0].colorName").value("深灰"))
                    .andExpect(jsonPath("$.data[0].stock").value(50));
        }
    }

    // ==================== POST /api/admin/products/batch/* ====================

    @Nested
    @DisplayName("POST /api/admin/products/batch/* — 批量操作")
    class BatchOps {

        @Test
        @DisplayName("批量上架 -> 200 + BatchOperationResult")
        void batchOnShelf() throws Exception {
            BatchOperationResult result = new BatchOperationResult();
            result.setSuccess(3);
            result.setFailed(0);

            when(productService.batchOnShelf(eq(List.of("a", "b", "c")), eq(TEST_TENANT_ID)))
                    .thenReturn(result);

            mockMvc.perform(post(BASE + "/batch/on-shelf")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"productIds\":[\"a\",\"b\",\"c\"]}"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.success").value(3));
        }

        @Test
        @DisplayName("批量下架 -> 200")
        void batchOffShelf() throws Exception {
            BatchOperationResult result = new BatchOperationResult();
            result.setSuccess(2);
            when(productService.batchOffShelf(anyList(), eq(TEST_TENANT_ID))).thenReturn(result);

            mockMvc.perform(post(BASE + "/batch/off-shelf")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"productIds\":[\"a\",\"b\"]}"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("批量删除 -> 200")
        void batchDelete() throws Exception {
            BatchOperationResult result = new BatchOperationResult();
            result.setSuccess(1);
            when(productService.batchDelete(anyList(), eq(TEST_TENANT_ID))).thenReturn(result);

            mockMvc.perform(post(BASE + "/batch/delete")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"productIds\":[\"a\"]}"))
                    .andExpect(status().isOk());
        }
    }

    // ==================== 租户隔离 ====================

    @Nested
    @DisplayName("租户隔离验证")
    class TenantIsolation {

        @Test
        @DisplayName("服务调用携带租户 ID")
        void tenantIdPassedToService() throws Exception {
            when(productService.getProducts(any(ProductQueryRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE));

            verify(productService).getProducts(any(ProductQueryRequest.class), eq(TEST_TENANT_ID));
        }
    }
}
