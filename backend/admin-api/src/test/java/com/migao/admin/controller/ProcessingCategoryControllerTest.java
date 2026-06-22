package com.migao.admin.controller;

import com.migao.admin.dto.ProcessingCategoryCreateRequest;
import com.migao.admin.dto.ProcessingCategoryResponse;
import com.migao.admin.service.ProcessingCategoryService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProcessingCategoryController 单元测试
 * 覆盖：获取分类列表、创建分类（happy path + validation error）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingCategoryController 加工分类测试")
class ProcessingCategoryControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProcessingCategoryService processingCategoryService;

    @InjectMocks
    private ProcessingCategoryController processingCategoryController;

    private static final String BASE = "/api/admin/processing-categories";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(processingCategoryController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("getProcessingCategories — 获取分类列表 → 200")
    void getProcessingCategories_returnsList() throws Exception {
        ProcessingCategoryResponse cat1 = new ProcessingCategoryResponse();
        cat1.setId("cat-1");
        cat1.setName("裁剪");
        cat1.setSortOrder(1);
        cat1.setStatus("active");
        cat1.setItemCount(5L);

        ProcessingCategoryResponse cat2 = new ProcessingCategoryResponse();
        cat2.setId("cat-2");
        cat2.setName("缝纫");
        cat2.setSortOrder(2);
        cat2.setStatus("active");
        cat2.setItemCount(3L);

        when(processingCategoryService.getProcessingCategories(TEST_TENANT_ID))
                .thenReturn(List.of(cat1, cat2));

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[0].name").value("裁剪"))
                .andExpect(jsonPath("$.data[0].itemCount").value(5))
                .andExpect(jsonPath("$.data[1].name").value("缝纫"));

        verify(processingCategoryService).getProcessingCategories(TEST_TENANT_ID);
    }

    @Test
    @DisplayName("createProcessingCategory — 创建分类成功 → 200")
    void createProcessingCategory_success() throws Exception {
        ProcessingCategoryResponse created = new ProcessingCategoryResponse();
        created.setId("cat-new");
        created.setName("新分类");
        created.setSortOrder(0);
        created.setStatus("active");
        created.setItemCount(0L);

        when(processingCategoryService.createProcessingCategory(any(ProcessingCategoryCreateRequest.class), eq(TEST_TENANT_ID)))
                .thenReturn(created);

        ProcessingCategoryCreateRequest req = new ProcessingCategoryCreateRequest();
        req.setName("新分类");
        req.setSortOrder(0);

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.name").value("新分类"));

        verify(processingCategoryService).createProcessingCategory(any(ProcessingCategoryCreateRequest.class), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("createProcessingCategory — 缺少分类名称 → 422")
    void createProcessingCategory_missingName() throws Exception {
        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }
}
