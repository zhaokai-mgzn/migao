package com.aikf.admin.controller;

import com.aikf.admin.config.GlobalExceptionHandler;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.service.CategoryService;
import com.aikf.admin.service.FileStorageService;
import com.aikf.admin.service.ProcessingItemService;
import com.aikf.admin.service.ProductService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 综合业务流程集成测试
 * 覆盖：分类管理、加工项 CRUD、价格计算、商品关联、文件上传
 */
@ExtendWith(MockitoExtension.class)
class BusinessFlowIntegrationTest {

    private MockMvc categoryMockMvc;
    private MockMvc processingItemMockMvc;
    private MockMvc productMockMvc;
    private MockMvc uploadMockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private CategoryService categoryService;

    @Mock
    private ProcessingItemService processingItemService;

    @Mock
    private ProductService productService;

    @Mock
    private FileStorageService fileStorageService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        GlobalExceptionHandler exceptionHandler = new GlobalExceptionHandler();

        CategoryController categoryController = new CategoryController(categoryService);
        categoryMockMvc = MockMvcBuilders.standaloneSetup(categoryController)
                .setControllerAdvice(exceptionHandler)
                .build();

        ProcessingItemController processingItemController = new ProcessingItemController(processingItemService);
        processingItemMockMvc = MockMvcBuilders.standaloneSetup(processingItemController)
                .setControllerAdvice(exceptionHandler)
                .build();

        ProductController productController = new ProductController(productService);
        productMockMvc = MockMvcBuilders.standaloneSetup(productController)
                .setControllerAdvice(exceptionHandler)
                .build();

        UploadController uploadController = new UploadController(fileStorageService);
        uploadMockMvc = MockMvcBuilders.standaloneSetup(uploadController)
                .setControllerAdvice(exceptionHandler)
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 分类管理 ========================

    @Test
    @DisplayName("创建分类并查询分类树")
    void testCategoryCreateAndList() throws Exception {
        // Given: 创建分类
        CategoryResponse createdCategory = new CategoryResponse();
        createdCategory.setId("cat-001");
        createdCategory.setName("窗帘");
        createdCategory.setLevel(1);
        createdCategory.setSortOrder(0);
        createdCategory.setStatus("active");
        createdCategory.setCreatedAt(OffsetDateTime.now());

        when(categoryService.createCategory(any(CategoryCreateRequest.class), eq(1L)))
                .thenReturn(createdCategory);

        CategoryCreateRequest createRequest = new CategoryCreateRequest();
        createRequest.setName("窗帘");
        createRequest.setLevel(1);
        createRequest.setSortOrder(0);

        // Step 1: 创建分类
        categoryMockMvc.perform(post("/api/admin/categories")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(createRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("cat-001"))
                .andExpect(jsonPath("$.data.name").value("窗帘"));

        // Given: 查询分类树（含子分类）
        CategoryResponse childCategory = new CategoryResponse();
        childCategory.setId("cat-002");
        childCategory.setName("遮光窗帘");
        childCategory.setParentId("cat-001");
        childCategory.setLevel(2);
        childCategory.setStatus("active");

        CategoryResponse parentWithChild = new CategoryResponse();
        parentWithChild.setId("cat-001");
        parentWithChild.setName("窗帘");
        parentWithChild.setLevel(1);
        parentWithChild.setStatus("active");
        parentWithChild.setChildren(List.of(childCategory));

        when(categoryService.getCategoryTree(1L)).thenReturn(List.of(parentWithChild));

        // Step 2: 查询分类树
        categoryMockMvc.perform(get("/api/admin/categories")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data").isArray())
                .andExpect(jsonPath("$.data[0].name").value("窗帘"))
                .andExpect(jsonPath("$.data[0].children[0].name").value("遮光窗帘"));
    }

    // ======================== 加工项 CRUD ========================

    @Test
    @DisplayName("加工项 CRUD 全流程 - 创建、查询、更新、删除")
    void testProcessingItemCRUD() throws Exception {
        // Given: 创建加工项
        ProcessingItemResponse createdItem = new ProcessingItemResponse();
        createdItem.setId("pi-001");
        createdItem.setName("打孔加工");
        createdItem.setCategoryId("cat-001");
        createdItem.setCategoryName("窗帘");
        createdItem.setPricingMethod("per_meter");
        createdItem.setUnitPrice(new BigDecimal("15.00"));
        createdItem.setUnit("元/米");
        createdItem.setMinQuantity(1);
        createdItem.setMaxQuantity(100);
        createdItem.setProcessingDays(1);
        createdItem.setAiRecommended(true);
        createdItem.setStatus("active");
        createdItem.setOptions(List.of(Map.of("name", "纳米圈", "price", 0)));

        when(processingItemService.createProcessingItem(any(ProcessingItemCreateRequest.class), eq(1L)))
                .thenReturn(createdItem);

        ProcessingItemCreateRequest createRequest = new ProcessingItemCreateRequest();
        createRequest.setName("打孔加工");
        createRequest.setCategoryId("cat-001");
        createRequest.setPricingMethod("per_meter");
        createRequest.setUnitPrice(new BigDecimal("15.00"));

        // Step 1: 创建
        processingItemMockMvc.perform(post("/api/admin/processing-items")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(createRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("pi-001"))
                .andExpect(jsonPath("$.data.name").value("打孔加工"))
                .andExpect(jsonPath("$.data.pricingMethod").value("per_meter"));

        // Step 2: 查询详情
        when(processingItemService.getProcessingItemById("pi-001", 1L)).thenReturn(createdItem);

        processingItemMockMvc.perform(get("/api/admin/processing-items/pi-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("打孔加工"));

        // Step 3: 更新
        ProcessingItemResponse updatedItem = new ProcessingItemResponse();
        updatedItem.setId("pi-001");
        updatedItem.setName("打孔加工-升级");
        updatedItem.setCategoryId("cat-001");
        updatedItem.setPricingMethod("per_meter");
        updatedItem.setUnitPrice(new BigDecimal("20.00"));
        updatedItem.setStatus("active");

        when(processingItemService.updateProcessingItem(eq("pi-001"), any(ProcessingItemUpdateRequest.class), eq(1L)))
                .thenReturn(updatedItem);

        ProcessingItemUpdateRequest updateRequest = new ProcessingItemUpdateRequest();
        updateRequest.setName("打孔加工-升级");
        updateRequest.setCategoryId("cat-001");
        updateRequest.setPricingMethod("per_meter");
        updateRequest.setUnitPrice(new BigDecimal("20.00"));

        processingItemMockMvc.perform(put("/api/admin/processing-items/pi-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(updateRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("打孔加工-升级"))
                .andExpect(jsonPath("$.data.unitPrice").value(20.00));

        // Step 4: 删除
        doNothing().when(processingItemService).deleteProcessingItem("pi-001", 1L);

        processingItemMockMvc.perform(delete("/api/admin/processing-items/pi-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(processingItemService).deleteProcessingItem("pi-001", 1L);
    }

    // ======================== 价格计算 ========================

    @Test
    @DisplayName("价格计算器 - 按米计价")
    void testPriceCalculation() throws Exception {
        // Given
        PriceCalculateResponse calcResponse = new PriceCalculateResponse();
        calcResponse.setProcessingItemId("pi-001");
        calcResponse.setProcessingItemName("打孔加工");
        calcResponse.setPricingMethod("per_meter");
        calcResponse.setUnitPrice(new BigDecimal("15.00"));
        calcResponse.setQuantity(new BigDecimal("5.0"));
        calcResponse.setTotalPrice(new BigDecimal("75.00"));
        calcResponse.setProcessingDays(1);

        PriceCalculateResponse.PriceDetail detail = new PriceCalculateResponse.PriceDetail();
        detail.setName("打孔加工");
        detail.setUnitPrice(new BigDecimal("15.00"));
        detail.setQuantity(new BigDecimal("5.0"));
        detail.setSubtotal(new BigDecimal("75.00"));
        calcResponse.setDetails(List.of(detail));

        when(processingItemService.calculatePrice(any(PriceCalculateRequest.class), eq(1L)))
                .thenReturn(calcResponse);

        PriceCalculateRequest calcRequest = new PriceCalculateRequest();
        calcRequest.setProcessingItemId("pi-001");
        calcRequest.setQuantity(new BigDecimal("5.0"));

        // When & Then
        processingItemMockMvc.perform(post("/api/admin/processing-items/calculate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(calcRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.processingItemName").value("打孔加工"))
                .andExpect(jsonPath("$.data.pricingMethod").value("per_meter"))
                .andExpect(jsonPath("$.data.totalPrice").value(75.00))
                .andExpect(jsonPath("$.data.details[0].subtotal").value(75.00));
    }

    // ======================== 商品关联分类和加工项 ========================

    @Test
    @DisplayName("商品关联分类和加工项 - 创建商品并查询")
    void testProductWithCategoryAndProcessing() throws Exception {
        // Given
        ProductResponse productResponse = new ProductResponse();
        productResponse.setId("prod-001");
        productResponse.setName("豪华遮光窗帘");
        productResponse.setCategoryId("cat-001");
        productResponse.setStatus("on_sale");

        when(productService.createProduct(any(ProductCreateRequest.class), eq(1L)))
                .thenReturn(productResponse);

        ProductCreateRequest createRequest = new ProductCreateRequest();
        createRequest.setName("豪华遮光窗帘");
        createRequest.setCategoryId("cat-001");
        createRequest.setBasePrice(new BigDecimal("299.00"));

        // Step 1: 创建商品
        productMockMvc.perform(post("/api/admin/products")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(createRequest)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("prod-001"))
                .andExpect(jsonPath("$.data.name").value("豪华遮光窗帘"))
                .andExpect(jsonPath("$.data.categoryId").value("cat-001"));

        // Step 2: 查询商品详情
        when(productService.getProductById("prod-001", 1L)).thenReturn(productResponse);

        productMockMvc.perform(get("/api/admin/products/prod-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("豪华遮光窗帘"));
    }

    // ======================== 文件上传 ========================

    @Test
    @DisplayName("文件上传到本地存储 - 单文件上传")
    void testFileUploadToLocalStorage() throws Exception {
        // Given
        UploadedFileInfo fileInfo = UploadedFileInfo.builder()
                .id("file-001")
                .url("/api/files/static/images/test.jpg")
                .name("test.jpg")
                .size(1024L)
                .type("image/jpeg")
                .createdAt(LocalDateTime.now())
                .build();

        when(fileStorageService.upload(any(), eq("images"))).thenReturn(fileInfo);
        when(fileStorageService.getStorageType()).thenReturn("local");

        MockMultipartFile mockFile = new MockMultipartFile(
                "file",
                "test.jpg",
                "image/jpeg",
                "fake-image-content".getBytes()
        );

        // When & Then
        uploadMockMvc.perform(multipart("/api/admin/files/upload")
                        .file(mockFile)
                        .param("directory", "images"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("file-001"))
                .andExpect(jsonPath("$.data.url").value("/api/files/static/images/test.jpg"))
                .andExpect(jsonPath("$.data.name").value("test.jpg"))
                .andExpect(jsonPath("$.data.size").value(1024))
                .andExpect(jsonPath("$.data.type").value("image/jpeg"));

        verify(fileStorageService).upload(any(), eq("images"));
    }
}
