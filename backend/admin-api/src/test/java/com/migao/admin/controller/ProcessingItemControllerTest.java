package com.migao.admin.controller;
// case_ids: HR-004

import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.ProcessingItemCreateRequest;
import com.migao.admin.dto.ProcessingItemResponse;
import com.migao.admin.service.ProcessingItemService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProcessingItemController 单元测试
 * 覆盖：加工项列表查询、详情查询、创建（happy path）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProcessingItemController 加工项测试")
class ProcessingItemControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProcessingItemService processingItemService;

    @InjectMocks
    private ProcessingItemController processingItemController;

    private static final String BASE = "/api/admin/processing-items";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(processingItemController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("GET 列表 - 200 返回分页")
    void getProcessingItems_ok() throws Exception {
        when(processingItemService.getProcessingItems(any(), eq(TEST_TENANT_ID)))
                .thenReturn(PageResponse.of(0L, 1L, 20L, java.util.List.of()));

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("GET 详情 - 200 返回加工项")
    void getProcessingItemById_ok() throws Exception {
        ProcessingItemResponse resp = new ProcessingItemResponse();
        resp.setId("item-001");
        resp.setName("压边");
        when(processingItemService.getProcessingItemById("item-001", TEST_TENANT_ID))
                .thenReturn(resp);

        mockMvc.perform(get(BASE + "/item-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("item-001"))
                .andExpect(jsonPath("$.data.name").value("压边"));
    }

    @Test
    @DisplayName("POST 创建 - 200 返回创建结果")
    void createProcessingItem_ok() throws Exception {
        ProcessingItemResponse resp = new ProcessingItemResponse();
        resp.setId("item-new");
        resp.setName("锁边");
        when(processingItemService.createProcessingItem(any(), eq(TEST_TENANT_ID)))
                .thenReturn(resp);

        ProcessingItemCreateRequest req = new ProcessingItemCreateRequest();
        req.setName("锁边");
        req.setCategoryId("cat-1");
        req.setPricingMethod("per_meter");
        req.setUnitPrice(new java.math.BigDecimal("12.50"));

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("item-new"));

        verify(processingItemService).createProcessingItem(any(), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("POST 创建 - 缺少必填字段返回 422")
    void createProcessingItem_missingRequiredFields_422() throws Exception {
        ProcessingItemCreateRequest req = new ProcessingItemCreateRequest();
        req.setName("锁边"); // 缺 categoryId / pricingMethod / unitPrice

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isUnprocessableEntity());
    }
}
