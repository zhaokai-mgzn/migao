package com.migao.admin.controller;

// case_ids: PG-036

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProductionSeedTemplateService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProductionSeedTemplateController 端点测试（issue #4361 交付物 2；收口 #4316）。
 *
 * <p><b>为什么必须有这个文件</b>：这两个端点是**契约冻结**面 —— 前端包 #4363（已合并）
 * 按「路径 + 响应键名」消费（`GET /api/admin/production/seed-templates`、
 * `POST .../{templateId}/apply`），而**改键名 = 静默打断前端**。服务层测试
 * （{@code ProductionSeedTemplateServiceTest}）钉的是行为，钉不到「路径/键名/权限」这一层
 * ⇒ 本文件补上端点级断言（形态照 {@link KnowledgeTemplateControllerTest} 的既有范式）。
 *
 * <p>租户上下文由 {@code TenantContext} 提供（端点从上下文取 tenantId，不信任请求体）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProductionSeedTemplateController 行业生产种子模板端点测试")
class ProductionSeedTemplateControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProductionSeedTemplateService productionSeedTemplateService;

    @InjectMocks
    private ProductionSeedTemplateController productionSeedTemplateController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(productionSeedTemplateController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("GET /api/admin/production/seed-templates — 模板目录")
    class ListTemplates {

        @Test
        @DisplayName("返回模板目录：逐键 = 契约冻结字段（templateId/industry/name/version + 计数）")
        void list_shapeFrozen() throws Exception {
            when(productionSeedTemplateService.listTemplates()).thenReturn(List.of(
                    ProductionSeedTemplateInfo.builder()
                            .templateId("curtain").industry("curtain")
                            .name("布艺窗帘行业模板").version(1)
                            .description("单价多为占位值，客户确认前不要当实证值")
                            .operationCount(35).routingCount(9).optionCount(16)
                            .build()));

            mockMvc.perform(get("/api/admin/production/seed-templates"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    // 逐键断言：任一键改名即红（前端按这些键消费，改名 = 静默打断）
                    .andExpect(jsonPath("$.data[0].templateId").value("curtain"))
                    .andExpect(jsonPath("$.data[0].industry").value("curtain"))
                    .andExpect(jsonPath("$.data[0].name").value("布艺窗帘行业模板"))
                    .andExpect(jsonPath("$.data[0].version").value(1))
                    .andExpect(jsonPath("$.data[0].operationCount").value(35))
                    .andExpect(jsonPath("$.data[0].routingCount").value(9))
                    .andExpect(jsonPath("$.data[0].optionCount").value(16));
        }
    }

    @Nested
    @DisplayName("POST /api/admin/production/seed-templates/{templateId}/apply — 一键套用")
    class Apply {

        @Test
        @DisplayName("套用成功：返回 created_operations / created_routings / skipped（契约键名）")
        void apply_shapeFrozen() throws Exception {
            when(productionSeedTemplateService.industryOfTemplate("curtain")).thenReturn("curtain");
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("templateId", "curtain");
            result.put("applied", true);
            result.put("reason", null);
            result.put("created_operations", 35);
            result.put("created_routings", 9);
            result.put("created_options", 16);
            result.put("skipped", 0);
            when(productionSeedTemplateService.applyTemplate(1L, "curtain")).thenReturn(result);

            mockMvc.perform(post("/api/admin/production/seed-templates/curtain/apply"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.applied").value(true))
                    .andExpect(jsonPath("$.data.created_operations").value(35))
                    .andExpect(jsonPath("$.data.created_routings").value(9))
                    .andExpect(jsonPath("$.data.skipped").value(0));
        }

        @Test
        @DisplayName("幂等第二次：created_* 全 0、skipped 全量（前端 toast 报「新增 0 / 跳过 44」）")
        void apply_idempotentSecondCall() throws Exception {
            when(productionSeedTemplateService.industryOfTemplate("curtain")).thenReturn("curtain");
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("templateId", "curtain");
            result.put("applied", true);
            result.put("created_operations", 0);
            result.put("created_routings", 0);
            result.put("created_options", 0);
            result.put("skipped", 60);
            when(productionSeedTemplateService.applyTemplate(1L, "curtain")).thenReturn(result);

            mockMvc.perform(post("/api/admin/production/seed-templates/curtain/apply"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.created_operations").value(0))
                    .andExpect(jsonPath("$.data.created_routings").value(0))
                    .andExpect(jsonPath("$.data.skipped").value(60));
        }

        @Test
        @DisplayName("未知 templateId → 404（显式失败，不静默空库）")
        void apply_unknownTemplate_404() throws Exception {
            when(productionSeedTemplateService.industryOfTemplate("nope"))
                    .thenThrow(BusinessException.notFound("生产种子模板"));

            mockMvc.perform(post("/api/admin/production/seed-templates/nope/apply"))
                    .andExpect(status().isNotFound());
        }

        @Test
        @DisplayName("tenantId 取自 TenantContext（不信任请求体）")
        void apply_usesTenantContext() throws Exception {
            TenantContext.setTenantId(77L);
            when(productionSeedTemplateService.industryOfTemplate("curtain")).thenReturn("curtain");
            when(productionSeedTemplateService.applyTemplate(77L, "curtain"))
                    .thenReturn(Map.of("templateId", "curtain", "applied", true,
                            "created_operations", 35, "created_routings", 9, "skipped", 0));

            mockMvc.perform(post("/api/admin/production/seed-templates/curtain/apply"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.created_operations").value(35));
        }
    }

    @Nested
    @DisplayName("权限声明（套用是批量写，不能落到读权限岗位）")
    class Permission {

        @Test
        @DisplayName("类级声明 processing:manage（不是 ProductionController 的 order:list）")
        void declaresManagePermission() throws Exception {
            RequirePermission onClass = ProductionSeedTemplateController.class
                    .getAnnotation(RequirePermission.class);
            assertThat(onClass)
                    .as("套用会真的批量落库（工序/路线/单价）⇒ 必须声明 processing:manage；"
                            + "缺类级声明 = 任何能调该端点的岗位都能批量写")
                    .isNotNull();
            assertThat(onClass.value()).isEqualTo("processing:manage");
        }

        @Test
        @DisplayName("两个端点都落在类级权限下（方法上没有更宽松的覆盖）")
        void endpointsInheritClassPermission() throws Exception {
            for (String name : new String[]{"list", "apply"}) {
                Method m = null;
                for (Method candidate : ProductionSeedTemplateController.class.getDeclaredMethods()) {
                    if (candidate.getName().equals(name)) {
                        m = candidate;
                        break;
                    }
                }
                assertThat(m).as("端点方法 %s 必须存在", name).isNotNull();
                assertThat(m.getAnnotation(RequirePermission.class))
                        .as("方法 %s 未声明更宽松的方法级权限（继承类级 processing:manage）", name)
                        .isNull();
            }
        }
    }
}
