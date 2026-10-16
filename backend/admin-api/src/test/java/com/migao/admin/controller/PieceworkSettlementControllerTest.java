package com.migao.admin.controller;

// case_ids: PG-073

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PieceworkSettlementService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 计件结算单端点契约测试（issue #5653）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>不可改在接口层不存在</b>：本 controller 的映射里**没有** PUT / PATCH / DELETE
 *       （源码面 + 运行时 404/405 两面都判 —— 「不可改」不是「前端不给按钮」）；</li>
 *   <li><b>幂等回执语义在端点级</b>（{@code ON CONFLICT} 原子闸的那一族）：服务层抛的具名 409
 *       必须在 HTTP 层拿到 **409 + error.code**，而不是 500（服务级绿、端点级红是这一族
 *       唯一的可见面 —— 见 tests/unit_ci_workflows/test_endpoint_receipt_race_guard.py 的口径）；</li>
 *   <li><b>四个动作各自声明权限码</b>：读 {@code production:view} / 写 {@code processing:manage}
 *       （未注解端点 = 沉默放行，正是 sibling 判据要治的形态；写码**刻意不用** {@code production:execute}
 *       —— 那个码由 #5699 的 I4 台账把守恰好四条执行类写端点、判据是零外溢）；</li>
 *   <li><b>参数透传</b>：period / worker_name / reason 原样交给服务端（不在端侧算任何数）。</li>
 * </ol>
 */
@DisplayName("PieceworkSettlementController 计件结算单端点（#5653）")
class PieceworkSettlementControllerTest extends BaseControllerTest {

    /** 类级前缀（方法级逐条带 `/settlements…`：路径级解析器只认「注解带字符串字面量」的方法映射）。 */
    private static final String CLASS_BASE = "/api/admin/production/piecework";
    private static final String BASE = CLASS_BASE + "/settlements";
    private static final String SETTLEMENT_ID = "st-0001";

    private PieceworkSettlementService settlementService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        settlementService = mock(PieceworkSettlementService.class);
        mockMvc = buildMockMvc(new PieceworkSettlementController(settlementService));
    }

    @Test
    @DisplayName("🔴 不可改：源码面**没有** PUT / PATCH / DELETE 映射（只有 POST + GET）")
    void controllerDeclaresNoUpdateSurface() {
        List<String> forbidden = new ArrayList<>();
        for (Method method : PieceworkSettlementController.class.getDeclaredMethods()) {
            if (method.isAnnotationPresent(PutMapping.class)) {
                forbidden.add("PUT " + method.getName());
            }
            if (method.isAnnotationPresent(PatchMapping.class)) {
                forbidden.add("PATCH " + method.getName());
            }
            if (method.isAnnotationPresent(DeleteMapping.class)) {
                forbidden.add("DELETE " + method.getName());
            }
        }
        assertThat(forbidden).as("结算单出现了改写面（生成即冻结 ⇒ 接口层不该存在）").isEmpty();
        // 正向对照：写面只由 POST 承担（生成 / 作废两个动作）；读面只有两个 GET
        long posts = Arrays.stream(PieceworkSettlementController.class.getDeclaredMethods())
                .filter(m -> m.isAnnotationPresent(PostMapping.class)).count();
        long gets = Arrays.stream(PieceworkSettlementController.class.getDeclaredMethods())
                .filter(m -> m.isAnnotationPresent(GetMapping.class)).count();
        assertThat(posts).isEqualTo(2);
        assertThat(gets).isEqualTo(2);
    }

    @Test
    @DisplayName("🔴 不可改（运行时）：PUT / PATCH 落到本路径 ⇒ 405（路由层就没有那个动词）")
    void runtimeRejectsUpdateVerbs() throws Exception {
        mockMvc.perform(put(BASE + "/" + SETTLEMENT_ID).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isMethodNotAllowed());
        mockMvc.perform(patch(BASE + "/" + SETTLEMENT_ID).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isMethodNotAllowed());
    }

    @Test
    @DisplayName("🔴 生成：200 + 冻结金额逐值下发（服务端算的钱原样出）")
    void generateReturnsTheFrozenAmount() throws Exception {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", SETTLEMENT_ID);
        view.put("period", "2026-10");
        view.put("worker_name", "张三");
        view.put("total_amount", new BigDecimal("7.40"));
        view.put("generated_by", TEST_USER_ID);
        when(settlementService.generate(eq("2026-10"), eq("张三"), eq(TEST_TENANT_ID))).thenReturn(view);

        mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"period\":\"2026-10\",\"worker_name\":\"张三\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total_amount").value(7.40))
                .andExpect(jsonPath("$.data.worker_name").value("张三"));

        verify(settlementService).generate("2026-10", "张三", TEST_TENANT_ID);
    }

    @Test
    @DisplayName("🔴 端点级回执：重复生成 ⇒ HTTP 409 + error.code（**不是** 500）")
    void duplicateGenerationIsAReceiptNotAServerError() throws Exception {
        when(settlementService.generate(any(), any(), anyLong()))
                .thenThrow(new BusinessException(PieceworkSettlementService.CODE_EXISTS,
                        "「张三」在 2026-10 已有一张生效的结算单（生成即冻结、不可改）。", 409));

        mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"period\":\"2026-10\",\"worker_name\":\"张三\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value(PieceworkSettlementService.CODE_EXISTS));
    }

    @Test
    @DisplayName("🔴 作废：200 + 留痕三件套（谁 / 何时 / 为什么）；原因透传给服务端")
    void voidReturnsTheTrail() throws Exception {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", SETTLEMENT_ID);
        view.put("voided", true);
        view.put("voided_by", TEST_USER_ID);
        view.put("void_reason", "单价录错，重开");
        when(settlementService.voidSettlement(eq(SETTLEMENT_ID), eq("单价录错，重开"), eq(TEST_TENANT_ID)))
                .thenReturn(view);

        mockMvc.perform(post(BASE + "/" + SETTLEMENT_ID + "/void").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"reason\":\"单价录错，重开\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.voided").value(true))
                .andExpect(jsonPath("$.data.void_reason").value("单价录错，重开"));
    }

    @Test
    @DisplayName("🔴 列 / 详情：GET 直达服务端（期间与 include_voided 原样透传）")
    void listAndDetailPassParametersThrough() throws Exception {
        when(settlementService.list(eq("2026-10"), eq(Boolean.TRUE), eq(TEST_TENANT_ID)))
                .thenReturn(Map.of("total", 2, "voided_count", 1));
        when(settlementService.detail(eq(SETTLEMENT_ID), eq(TEST_TENANT_ID)))
                .thenReturn(Map.of("id", SETTLEMENT_ID, "total_amount", new BigDecimal("7.40")));

        mockMvc.perform(get(BASE).param("period", "2026-10").param("include_voided", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.voided_count").value(1));
        mockMvc.perform(get(BASE + "/" + SETTLEMENT_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total_amount").value(7.40));
    }

    @Test
    @DisplayName("🔴 权限：四个动作逐个声明码（读 production:view / 写 processing:manage，无未注解端点）")
    void everyMappingDeclaresItsPermissionCode() {
        Map<String, String> expected = Map.of(
                "generate", "processing:manage",
                "voidSettlement", "processing:manage",
                "list", "production:view",
                "detail", "production:view");
        Map<String, String> actual = new LinkedHashMap<>();
        for (Method method : PieceworkSettlementController.class.getDeclaredMethods()) {
            if (!method.isAnnotationPresent(RequirePermission.class)) {
                continue;
            }
            actual.put(method.getName(), method.getAnnotation(RequirePermission.class).value());
        }
        assertThat(actual).isEqualTo(expected);
        // 类级不得有兜底注解（那会让「漏注解」变成沉默放行）
        assertThat(PieceworkSettlementController.class.isAnnotationPresent(RequirePermission.class)).isFalse();
        // 端点族逐字（与前端 / Agent 侧引用的一致寻址口径 = 类级前缀 + 方法级 /settlements…）
        assertThat(PieceworkSettlementController.class.getAnnotation(RequestMapping.class).value())
                .containsExactly(CLASS_BASE);
        assertThat(methodPath("generate")).isEqualTo("/settlements");
        assertThat(methodPath("list")).isEqualTo("/settlements");
        assertThat(methodPath("detail")).isEqualTo("/settlements/{id}");
        assertThat(methodPath("voidSettlement")).isEqualTo("/settlements/{id}/void");
    }

    /** 方法级映射路径（无参 / 数组写法在本仓不存在；取不到 ⇒ 直接失败，不静默跳过）。 */
    private static String methodPath(String name) {
        for (Method method : PieceworkSettlementController.class.getDeclaredMethods()) {
            if (!method.getName().equals(name)) {
                continue;
            }
            PostMapping post = method.getAnnotation(PostMapping.class);
            if (post != null) {
                return post.value()[0];
            }
            GetMapping get = method.getAnnotation(GetMapping.class);
            if (get != null) {
                return get.value()[0];
            }
        }
        throw new IllegalStateException("找不到方法级映射：" + name);
    }
}
