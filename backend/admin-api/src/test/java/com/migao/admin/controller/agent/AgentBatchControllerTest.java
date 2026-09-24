// case_ids: PR-007, PR-010
package com.migao.admin.controller.agent;

import com.migao.admin.controller.BaseControllerTest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.AgentBatchService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 批量更新端点契约测试（issue #5314 服务端包；冻结契约见 issue #5314 评论）。
 *
 * <pre>
 * POST /api/admin/agent/batches                  req {batchType, items:[{resourceId, field, oldValue, newValue}]}
 *                                                resp {batchId, itemCount, status:"preview"}
 * POST /api/admin/agent/batches/{batchId}/execute resp {batchId, status, results:[{resourceId, success, error?}]}
 * POST /api/admin/agent/batches/{batchId}/revert  resp {batchId, status, results:[...]}
 * GET  /api/admin/agent/batches/{batchId}         查询进度/结果/可撤销性
 * </pre>
 *
 * <p><b>权限码判据</b>：与逐条写**同码**、不新开权限面 ——
 * 本类按**结构**断言（读注解真值，与 {@code AgentProductController} 的逐条写端点逐字相等），
 * 而不是在 standalone MockMvc 里假装测 403（那个拦截器不在这条链上，测出来的绿是空断言）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AgentBatchController —— /api/admin/agent/batches 四端点")
class AgentBatchControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/agent/batches";
    private static final String BATCH_ID = "batch-0001";

    private static final String BODY = """
            {
              "batchType": "product_price",
              "items": [
                {"resourceId": "prod-0001", "field": "basePrice", "oldValue": "10.00", "newValue": "12.00"}
              ]
            }
            """;

    private MockMvc mockMvc;

    @Mock
    private AgentBatchService batchService;

    @InjectMocks
    private AgentBatchController controller;

    @BeforeEach
    void setUp() {
        // 注：BaseControllerTest 的 @BeforeEach/@AfterEach（TenantContext + SecurityContext）
        // 由 JUnit 自动继承执行，无需（也无法：跨包不可见）显式调用 super.baseSetUp()
        mockMvc = buildMockMvc(controller);
    }

    private AgentBatchViews.Batch view(String status, List<AgentBatchViews.Result> results) {
        return AgentBatchViews.Batch.builder()
                .batchId(BATCH_ID)
                .batchType(AgentBatchService.TYPE_PRODUCT_PRICE)
                .status(status)
                .itemCount(1)
                .successCount(1)
                .failCount(0)
                .revertible(true)
                .results(results)
                .build();
    }

    @Nested
    @DisplayName("POST /api/admin/agent/batches — 创建（预演）")
    class Create {

        @Test
        @DisplayName("返回 {batchId, itemCount, status:preview}，身份取自认证上下文")
        void returnsFrozenPreviewShape() throws Exception {
            when(batchService.create(eq(TEST_TENANT_ID), eq(TEST_USER_ID), any()))
                    .thenReturn(view("preview", null));

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.batchId").value(BATCH_ID))
                    .andExpect(jsonPath("$.data.itemCount").value(1))
                    .andExpect(jsonPath("$.data.status").value("preview"));

            verify(batchService).create(eq(TEST_TENANT_ID), eq(TEST_USER_ID), any());
        }

        @Test
        @DisplayName("缺 batchType / items 为空 ⇒ 422 且不落批次")
        void rejectsBlankBatchTypeAndEmptyItems() throws Exception {
            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"items\":[]}"))
                    .andExpect(status().isUnprocessableEntity());

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"batchType\":\"product_price\",\"items\":[]}"))
                    .andExpect(status().isUnprocessableEntity());

            verify(batchService, org.mockito.Mockito.never()).create(any(), any(), any());
        }
    }

    @Nested
    @DisplayName("POST /{batchId}/execute — 执行")
    class Execute {

        @Test
        @DisplayName("返回 {batchId, status, results:[{resourceId, success, error?}]}；成功项**不带** error 键")
        void returnsFrozenResultShape() throws Exception {
            when(batchService.execute(TEST_TENANT_ID, BATCH_ID)).thenReturn(view("done", List.of(
                    AgentBatchViews.Result.builder().resourceId("prod-0001").success(true).build())));

            mockMvc.perform(post(BASE + "/" + BATCH_ID + "/execute"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.batchId").value(BATCH_ID))
                    .andExpect(jsonPath("$.data.status").value("done"))
                    .andExpect(jsonPath("$.data.results[0].resourceId").value("prod-0001"))
                    .andExpect(jsonPath("$.data.results[0].success").value(true))
                    .andExpect(jsonPath("$.data.results[0].error").doesNotExist());
        }

        @Test
        @DisplayName("部分失败：失败项带 error 文案（逐条报告）")
        void reportsPerItemError() throws Exception {
            when(batchService.execute(TEST_TENANT_ID, BATCH_ID)).thenReturn(view("partial", List.of(
                    AgentBatchViews.Result.builder().resourceId("prod-0001").success(true).build(),
                    AgentBatchViews.Result.builder().resourceId("prod-0002").success(false)
                            .error("商品 prod-0002 改价失败").build())));

            mockMvc.perform(post(BASE + "/" + BATCH_ID + "/execute"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.status").value("partial"))
                    .andExpect(jsonPath("$.data.results[1].success").value(false))
                    .andExpect(jsonPath("$.data.results[1].error").value("商品 prod-0002 改价失败"));
        }
    }

    @Nested
    @DisplayName("POST /{batchId}/revert — 撤销")
    class Revert {

        @Test
        @DisplayName("返回 {batchId, status, results:[...]}（与 execute 同形）")
        void returnsFrozenResultShape() throws Exception {
            when(batchService.revert(TEST_TENANT_ID, BATCH_ID)).thenReturn(view("reverted", List.of(
                    AgentBatchViews.Result.builder().resourceId("prod-0001").success(true).build())));

            mockMvc.perform(post(BASE + "/" + BATCH_ID + "/revert"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.batchId").value(BATCH_ID))
                    .andExpect(jsonPath("$.data.status").value("reverted"))
                    .andExpect(jsonPath("$.data.results[0].resourceId").value("prod-0001"))
                    .andExpect(jsonPath("$.data.results[0].success").value(true));
        }
    }

    @Nested
    @DisplayName("GET /{batchId} — 查询进度/结果/可撤销性")
    class Query {

        @Test
        @DisplayName("回 revertible + 逐条 before → after（撤销依据可核对）")
        void returnsRevertibleAndItems() throws Exception {
            when(batchService.get(TEST_TENANT_ID, BATCH_ID)).thenReturn(
                    AgentBatchViews.Batch.builder()
                            .batchId(BATCH_ID)
                            .status("done")
                            .itemCount(1)
                            .successCount(1)
                            .failCount(0)
                            .revertible(true)
                            .items(List.of(AgentBatchViews.Item.builder()
                                    .resourceId("prod-0001").field("basePrice")
                                    .oldValue("10.00").newValue("12.00")
                                    .status("success").build()))
                            .build());

            mockMvc.perform(get(BASE + "/" + BATCH_ID))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.revertible").value(true))
                    .andExpect(jsonPath("$.data.items[0].oldValue").value("10.00"))
                    .andExpect(jsonPath("$.data.items[0].newValue").value("12.00"))
                    .andExpect(jsonPath("$.data.items[0].status").value("success"));
        }
    }

    @Nested
    @DisplayName("权限码：与逐条写同码、不新开权限面")
    class Permission {

        @Test
        @DisplayName("四端点都要求 product:create —— 与 AgentProductController 的逐条写端点**逐字同码**")
        void requiresSameCodeAsSingleWrite() throws Exception {
            RequirePermission onBatch = AgentBatchController.class.getAnnotation(RequirePermission.class);
            assertThat(onBatch).as("类级注解覆盖四个端点（方法级优先、其次类级）").isNotNull();

            Method singleWrite = AgentProductController.class.getMethod(
                    "updateProduct", String.class, com.migao.admin.dto.agent.AgentProductUpdateRequest.class);
            RequirePermission onSingleWrite = singleWrite.getAnnotation(RequirePermission.class);
            assertThat(onSingleWrite).as("逐条写端点的权限注解").isNotNull();

            assertThat(onBatch.value())
                    .as("🔴 批量的权限码必须与逐条写一致（同码 = 同一批人能做同一件事）")
                    .isEqualTo(onSingleWrite.value());
            assertThat(onBatch.value())
                    .as("仓库里**没有** product:update 这个码 —— 用它 = 端点在所有角色上永久 403")
                    .isEqualTo("product:create");
        }

        @Test
        @DisplayName("未新开权限面：控制器源码里只出现既有权限码")
        void doesNotIntroduceNewPermissionCode() throws Exception {
            String source = java.nio.file.Files.readString(java.nio.file.Paths.get(
                    "src/main/java/com/migao/admin/controller/agent/AgentBatchController.java"));
            assertThat(source).contains("@RequirePermission(\"product:create\")");
            assertThat(source).doesNotContain("product:batch").doesNotContain("batch:update");
        }
    }

    @Nested
    @DisplayName("端点路径与动词（冻结契约）")
    class Endpoints {

        @Test
        @DisplayName("类级 @RequestMapping 与四个方法映射逐字对齐契约表")
        void pathsMatchFrozenContract() throws Exception {
            org.springframework.web.bind.annotation.RequestMapping classMapping =
                    AgentBatchController.class.getAnnotation(org.springframework.web.bind.annotation.RequestMapping.class);
            assertThat(classMapping.value()).containsExactly("/api/admin/agent/batches");

            Method create = AgentBatchController.class.getMethod("create", com.migao.admin.dto.agent.AgentBatchCreateRequest.class);
            assertThat(create.getAnnotation(PostMapping.class)).isNotNull();

            Method execute = AgentBatchController.class.getMethod("execute", String.class);
            assertThat(execute.getAnnotation(PostMapping.class).value()).containsExactly("/{batchId}/execute");

            Method revert = AgentBatchController.class.getMethod("revert", String.class);
            assertThat(revert.getAnnotation(PostMapping.class).value()).containsExactly("/{batchId}/revert");

            Method query = AgentBatchController.class.getMethod("get", String.class);
            assertThat(query.getAnnotation(GetMapping.class).value()).containsExactly("/{batchId}");
        }
    }
}