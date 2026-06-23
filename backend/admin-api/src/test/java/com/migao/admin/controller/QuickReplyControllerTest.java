package com.migao.admin.controller;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.QuickReplyCreateRequest;
import com.migao.admin.dto.QuickReplyResponse;
import com.migao.admin.service.QuickReplyTemplateService;
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
 * QuickReplyController 单元测试
 * 覆盖：分页查询、分类列表、创建（happy path + validation error）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("QuickReplyController 快捷回复测试")
class QuickReplyControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private QuickReplyTemplateService quickReplyTemplateService;

    @InjectMocks
    private QuickReplyController quickReplyController;

    private static final String BASE = "/api/admin/quick-replies";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(quickReplyController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("getTemplates — 分页查询快捷回复 → 200")
    void getTemplates_returnsPage() throws Exception {
        QuickReplyResponse r1 = QuickReplyResponse.builder()
                .id("qr-1").category("问候语").title("您好").content("您好，请问有什么可以帮您？").build();
        QuickReplyResponse r2 = QuickReplyResponse.builder()
                .id("qr-2").category("问候语").title("欢迎").content("欢迎光临！").build();

        PageResponse<QuickReplyResponse> page = PageResponse.of(2L, 1L, 20L, List.of(r1, r2));
        when(quickReplyTemplateService.getTemplatePage(eq(1L), eq(20L), eq(null), eq(null), eq(TEST_TENANT_ID)))
                .thenReturn(page);

        mockMvc.perform(get(BASE).param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.items[0].title").value("您好"))
                .andExpect(jsonPath("$.data.items[1].title").value("欢迎"));

        verify(quickReplyTemplateService).getTemplatePage(eq(1L), eq(20L), eq(null), eq(null), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("getTemplates — 带分类/关键词筛选 → 200")
    void getTemplates_withFilters() throws Exception {
        PageResponse<QuickReplyResponse> page = PageResponse.of(0L, 1L, 20L, List.of());
        when(quickReplyTemplateService.getTemplatePage(eq(1L), eq(10L), eq("问候语"), eq("您好"), eq(TEST_TENANT_ID)))
                .thenReturn(page);

        mockMvc.perform(get(BASE)
                        .param("page", "1")
                        .param("size", "10")
                        .param("category", "问候语")
                        .param("keyword", "您好"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items").isEmpty());

        verify(quickReplyTemplateService).getTemplatePage(eq(1L), eq(10L), eq("问候语"), eq("您好"), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("getCategories — 获取分类列表 → 200")
    void getCategories_returnsList() throws Exception {
        when(quickReplyTemplateService.getCategories(TEST_TENANT_ID))
                .thenReturn(List.of("问候语", "售后话术", "物流话术"));

        mockMvc.perform(get(BASE + "/categories"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[0]").value("问候语"))
                .andExpect(jsonPath("$.data[2]").value("物流话术"));

        verify(quickReplyTemplateService).getCategories(TEST_TENANT_ID);
    }

    @Test
    @DisplayName("createTemplate — 创建快捷回复成功 → 200")
    void createTemplate_success() throws Exception {
        QuickReplyResponse created = QuickReplyResponse.builder()
                .id("qr-new").category("问候语").title("新模板").content("感谢您的咨询").build();
        when(quickReplyTemplateService.createTemplate(any(QuickReplyCreateRequest.class), eq(TEST_TENANT_ID)))
                .thenReturn(created);

        QuickReplyCreateRequest req = QuickReplyCreateRequest.builder()
                .category("问候语").title("新模板").content("感谢您的咨询").build();

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(req)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.title").value("新模板"))
                .andExpect(jsonPath("$.data.category").value("问候语"));

        verify(quickReplyTemplateService).createTemplate(any(QuickReplyCreateRequest.class), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("createTemplate — 缺少必填字段 → 422")
    void createTemplate_missingRequiredFields() throws Exception {
        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }
}
