package com.migao.admin.controller;

import com.migao.admin.dto.CategoryCreateRequest;
import com.migao.admin.dto.CategoryResponse;
import com.migao.admin.dto.CategoryUpdateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.CategoryService;
import org.junit.jupiter.api.AfterEach;
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
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * CategoryController 单元测试
 * 验证分类树查询、创建、更新、删除接口
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("CategoryController 分类管理测试")
class CategoryControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private CategoryService categoryService;

    @InjectMocks
    private CategoryController categoryController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(categoryController);
    }

    @Override
    @AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    private CategoryResponse buildCategoryResponse() {
        CategoryResponse resp = new CategoryResponse();
        resp.setId("cat-1");
        resp.setName("布料分类");
        resp.setParentId(null);
        resp.setLevel(1);
        resp.setSortOrder(0);
        resp.setIcon("icon-cloth");
        resp.setStatus("active");
        resp.setChildren(List.of());
        return resp;
    }

    @Nested
    @DisplayName("GET /api/admin/categories")
    class GetCategoryTree {

        @Test
        @DisplayName("返回分类树 -> 200")
        void getCategoryTree() throws Exception {
            when(categoryService.getCategoryTree(TEST_TENANT_ID))
                    .thenReturn(List.of(buildCategoryResponse()));

            mockMvc.perform(get("/api/admin/categories"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray())
                    .andExpect(jsonPath("$.data[0].name").value("布料分类"));
        }

        @Test
        @DisplayName("通过 /tree 路径返回分类树 -> 200")
        void getCategoryTreeViaTreePath() throws Exception {
            when(categoryService.getCategoryTree(TEST_TENANT_ID))
                    .thenReturn(List.of());

            mockMvc.perform(get("/api/admin/categories/tree"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }

        @Test
        @DisplayName("返回空树 -> 200")
        void emptyTree() throws Exception {
            when(categoryService.getCategoryTree(TEST_TENANT_ID))
                    .thenReturn(List.of());

            mockMvc.perform(get("/api/admin/categories"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isEmpty());
        }
    }

    @Nested
    @DisplayName("POST /api/admin/categories")
    class CreateCategory {

        @Test
        @DisplayName("创建分类 -> 200")
        void createCategory() throws Exception {
            CategoryResponse resp = buildCategoryResponse();
            when(categoryService.createCategory(any(CategoryCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(resp);

            String body = "{\"name\":\"新分类\",\"parentId\":null,\"sortOrder\":1}";

            mockMvc.perform(post("/api/admin/categories")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("布料分类"));
        }

        @Test
        @DisplayName("创建子分类（含 parentId） -> 200")
        void createChildCategory() throws Exception {
            CategoryResponse resp = buildCategoryResponse();
            resp.setId("cat-2");
            resp.setParentId("cat-1");
            resp.setLevel(2);
            when(categoryService.createCategory(any(CategoryCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(resp);

            String body = "{\"name\":\"子分类\",\"parentId\":\"cat-1\"}";

            mockMvc.perform(post("/api/admin/categories")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.parentId").value("cat-1"));
        }

        @Test
        @DisplayName("分类名称为空 -> 422")
        void emptyName_validationError() throws Exception {
            String body = "{\"name\":\"\"}";

            mockMvc.perform(post("/api/admin/categories")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("缺少 name 字段 -> 422")
        void missingName_validationError() throws Exception {
            String body = "{\"sortOrder\":1}";

            mockMvc.perform(post("/api/admin/categories")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("父分类不存在 -> 422")
        void parentNotFound() throws Exception {
            when(categoryService.createCategory(any(CategoryCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenThrow(BusinessException.validationError("父分类不存在"));

            String body = "{\"name\":\"子分类\",\"parentId\":\"nonexistent\"}";

            mockMvc.perform(post("/api/admin/categories")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/categories/{id}")
    class UpdateCategory {

        @Test
        @DisplayName("更新分类 -> 200")
        void updateCategory() throws Exception {
            CategoryResponse resp = buildCategoryResponse();
            resp.setName("已更新");
            when(categoryService.updateCategory(eq("cat-1"), any(CategoryUpdateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(resp);

            String body = "{\"name\":\"已更新\"}";

            mockMvc.perform(put("/api/admin/categories/cat-1")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.name").value("已更新"));
        }

        @Test
        @DisplayName("分类不存在 -> 404")
        void categoryNotFound() throws Exception {
            when(categoryService.updateCategory(eq("nonexistent"), any(CategoryUpdateRequest.class), eq(TEST_TENANT_ID)))
                    .thenThrow(BusinessException.notFound("分类"));

            String body = "{\"name\":\"更新\"}";

            mockMvc.perform(put("/api/admin/categories/nonexistent")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("更新名称缺失 -> 422")
        void emptyName_validationError() throws Exception {
            String body = "{\"name\":\"\"}";

            mockMvc.perform(put("/api/admin/categories/cat-1")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("将自己设为自己父分类 -> 422")
        void selfAsParent_validationError() throws Exception {
            when(categoryService.updateCategory(eq("cat-1"), any(CategoryUpdateRequest.class), eq(TEST_TENANT_ID)))
                    .thenThrow(BusinessException.validationError("不能将自己设为父分类"));

            String body = "{\"name\":\"分类\",\"parentId\":\"cat-1\"}";

            mockMvc.perform(put("/api/admin/categories/cat-1")
                            .contentType("application/json")
                            .content(body))
                    .andExpect(status().isUnprocessableEntity());
        }
    }

    @Nested
    @DisplayName("DELETE /api/admin/categories/{id}")
    class DeleteCategory {

        @Test
        @DisplayName("删除分类 -> 200")
        void deleteCategory() throws Exception {
            doNothing().when(categoryService).deleteCategory("cat-1", TEST_TENANT_ID);

            mockMvc.perform(delete("/api/admin/categories/cat-1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }

        @Test
        @DisplayName("分类不存在 -> 404")
        void categoryNotFound() throws Exception {
            doThrow(BusinessException.notFound("分类"))
                    .when(categoryService).deleteCategory("nonexistent", TEST_TENANT_ID);

            mockMvc.perform(delete("/api/admin/categories/nonexistent"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("有子分类无法删除 -> 422")
        void hasChildren_validationError() throws Exception {
            doThrow(BusinessException.validationError("该分类下有子分类，无法删除"))
                    .when(categoryService).deleteCategory("cat-1", TEST_TENANT_ID);

            mockMvc.perform(delete("/api/admin/categories/cat-1"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }

        @Test
        @DisplayName("有关联商品无法删除 -> 422")
        void hasProducts_validationError() throws Exception {
            doThrow(BusinessException.validationError("该分类下有关联商品，无法删除"))
                    .when(categoryService).deleteCategory("cat-1", TEST_TENANT_ID);

            mockMvc.perform(delete("/api/admin/categories/cat-1"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false));
        }
    }

    @Nested
    @DisplayName("租户隔离验证")
    class TenantIsolation {

        @Test
        @DisplayName("获取树形结构携带租户 ID")
        void getTreePassesTenantId() throws Exception {
            when(categoryService.getCategoryTree(TEST_TENANT_ID)).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/categories"));

            verify(categoryService).getCategoryTree(TEST_TENANT_ID);
        }

        @Test
        @DisplayName("创建分类携带租户 ID")
        void createPassesTenantId() throws Exception {
            when(categoryService.createCategory(any(CategoryCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(buildCategoryResponse());

            mockMvc.perform(post("/api/admin/categories")
                    .contentType("application/json")
                    .content("{\"name\":\"测试\"}"));

            verify(categoryService).createCategory(any(CategoryCreateRequest.class), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("删除分类携带租户 ID")
        void deletePassesTenantId() throws Exception {
            doNothing().when(categoryService).deleteCategory("cat-1", TEST_TENANT_ID);

            mockMvc.perform(delete("/api/admin/categories/cat-1"));

            verify(categoryService).deleteCategory("cat-1", TEST_TENANT_ID);
        }
    }
}
