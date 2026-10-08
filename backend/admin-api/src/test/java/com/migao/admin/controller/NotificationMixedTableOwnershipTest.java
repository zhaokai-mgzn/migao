// case_ids: DF-009
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.NotificationRuleDTO;
import com.migao.admin.dto.NotificationTemplateDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.NotificationRule;
import com.migao.admin.entity.NotificationTemplate;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.migao.admin.security.TenantOwnershipInterceptor;
import com.migao.admin.security.TenantResourceOwnership;
import com.migao.admin.service.NotificationRuleService;
import com.migao.admin.service.NotificationTemplateService;
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

import java.util.List;

import static org.hamcrest.Matchers.hasItem;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * issue #6167 实例判据：混合表（通知模板 / 通知规则）的**写归属**必须在载荷校验之前。
 *
 * <h2>被冻结的两条谓词（durable 依据 = {@code MybatisPlusConfig.IGNORE_TENANT_TABLES} 注释逐字）</h2>
 * <p>这两张表不在租户插件的作用面内（{@code ignoreTable} 判真）⇒ 业务层必须显式过滤：</p>
 * <ul>
 *   <li><b>可读</b> = {@code tenant_id = 当前租户 OR tenant_id = 0}（系统内置行对任何租户可见）</li>
 *   <li><b>可写</b> = {@code tenant_id = 当前租户}（{@code tenant_id=0} 的系统内置行**只读**）</li>
 * </ul>
 * <p>认定查询由 service 提供（{@code existsForCurrentTenant} / {@code isWritableByCurrentTenant}），
 * 与写路径**同一份谓词**；本判据不重写第二套归属逻辑。</p>
 *
 * <h2>mock 面能证的那一半 + 真库那一半在哪</h2>
 * <p>本类证「响应码归因」与「跨租户写服务零调用」（= 没有写）；字段级前后快照 / 真栈重放
 * 由集成方承担（分派纪律：本包不跑真库重放）。</p>
 *
 * <h2>两侧夹住（判据非空自证）</h2>
 * <p>{@link #withoutInterceptor_sameRequestIsNot404_outOfBand()} 把拦截器摘掉 ⇒ 同一个
 * 「跨租户 + 非法载荷」请求当场变回 422，证明 404 读数**来自本包的接线**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#6167 通知模板/规则（IGNORE_TENANT_TABLES 混合表）的写归属先于载荷校验")
class NotificationMixedTableOwnershipTest extends BaseControllerTest {

    private static final String TPL_ID = "tpl-11111111111111111111111111111111";
    private static final String RULE_ID = "rule-22222222222222222222222222222222";

    /** 非法载荷：模板缺 name + templateContent / 规则缺 eventType + templateId（校验在 service 层）。 */
    private static final String BAD_TEMPLATE_BODY = "{}";
    private static final String BAD_RULE_BODY = "{}";
    /** 合法载荷（逐字段齐备）。 */
    private static final String GOOD_TEMPLATE_BODY =
            "{\"name\":\"改名后\",\"type\":\"order\",\"channel\":\"internal\","
                    + "\"templateContent\":\"内容 {{orderNo}}\",\"status\":\"active\"}";
    private static final String GOOD_RULE_BODY =
            "{\"eventType\":\"order_created\",\"recipientType\":\"user\",\"channels\":\"internal\","
                    + "\"enabled\":true,\"templateId\":\"tpl-1\"}";

    @Mock private NotificationTemplateMapper templateMapper;
    @Mock private NotificationRuleMapper ruleMapper;
    @Mock private NotificationTemplateService templateService;
    @Mock private NotificationRuleService ruleService;

    private TenantResourceOwnership ownership;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        ownership = new TenantResourceOwnership(null, null, null, null, null, null,
                templateService, ruleService, null);
        ownership.registerChecks();
    }

    /** 生产接线 = {@code WebConfig.webMvcConfigurer} 里的 {@code addInterceptor}。 */
    private MockMvc withInterceptor(Object controller) {
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .addInterceptors(interceptor())
                .build();
    }

    /** **不**挂拦截器 —— 两侧夹住用（把接线摘掉，同一个请求必须变回 422）。 */
    private MockMvc withoutInterceptor(Object controller) {
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /** 注入的就是被测拦截器本体（生产由 Spring 字段注入）—— 不重写第二份判定。 */
    private TenantOwnershipInterceptor interceptor() {
        TenantOwnershipInterceptor interceptor = new TenantOwnershipInterceptor();
        try {
            java.lang.reflect.Field field = TenantOwnershipInterceptor.class.getDeclaredField("ownership");
            field.setAccessible(true);
            field.set(interceptor, ownership);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
        return interceptor;
    }

    /**
     * 夹具：目标行在**当前租户**下可见吗 / 可写吗。
     *
     * @param visible 可见（{@code tenant_id = 当前租户 OR tenant_id = 0}）
     * @param writable 可写（{@code tenant_id = 当前租户}，不含 0）
     */
    private void targetState(boolean visible, boolean writable) {
        when(templateService.existsForCurrentTenant(anyString())).thenReturn(visible);
        when(ruleService.existsForCurrentTenant(anyString())).thenReturn(visible);
        when(templateService.isWritableByCurrentTenant(anyString())).thenReturn(writable);
        when(ruleService.isWritableByCurrentTenant(anyString())).thenReturn(writable);
    }

    private static NotificationTemplateDTO templateDto() {
        NotificationTemplateDTO dto = new NotificationTemplateDTO();
        dto.setId(TPL_ID);
        dto.setName("改名后");
        return dto;
    }

    private static NotificationRuleDTO ruleDto() {
        NotificationRuleDTO dto = new NotificationRuleDTO();
        dto.setId(RULE_ID);
        dto.setEventType("order_created");
        return dto;
    }

    // ══════════ 判据 1：跨租户写（非法 / 合法两态）⇒ 404 ══════════

    @Test
    @DisplayName("判据 1：跨租户 + 非法载荷 ⇒ 404（不是 422）+ 写服务零调用（= 库零变动）")
    void crossTenantWithInvalidPayload_isNotFound() throws Exception {
        targetState(false, false);

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_TEMPLATE_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        withInterceptor(new NotificationRuleController(ruleService))
                .perform(put("/api/admin/notification-rules/" + RULE_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_RULE_BODY))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));

        // 归属认定不过 ⇒ 控制器方法体没执行 ⇒ 写服务一次都没被调用（没有写）
        verify(templateService, never()).updateTemplate(anyLong(), anyString(), any());
        verify(ruleService, never()).updateRule(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("判据 1b：跨租户 + 合法载荷 ⇒ 仍 404（防回归）+ 写服务零调用")
    void crossTenantWithValidPayload_isStillNotFound() throws Exception {
        targetState(false, false);

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_TEMPLATE_BODY))
                .andExpect(status().isNotFound());
        withInterceptor(new NotificationRuleController(ruleService))
                .perform(put("/api/admin/notification-rules/" + RULE_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_RULE_BODY))
                .andExpect(status().isNotFound());

        verify(templateService, never()).updateTemplate(anyLong(), anyString(), any());
        verify(ruleService, never()).updateRule(anyLong(), anyString(), any());
    }

    // ══════════ 判据 2：同租户（非法 ⇒ 422 / 合法 ⇒ 200）══════════

    @Test
    @DisplayName("判据 2：同租户自定义行 + 非法载荷 ⇒ 仍 422 + 逐字段可读（不许比修前更宽）")
    void sameTenantInvalidPayload_stillValidationError() throws Exception {
        targetState(true, true);
        // 同租户 ⇒ 认定通过、进入写路径；非法载荷由服务层校验挡下 ⇒ 422 逐字段
        when(templateService.updateTemplate(eq(TEST_TENANT_ID), eq(TPL_ID), any()))
                .thenThrow(com.migao.admin.exception.BusinessException
                        .validationError("模板名称与模板内容不能为空"));
        when(ruleService.updateRule(eq(TEST_TENANT_ID), eq(RULE_ID), any()))
                .thenThrow(com.migao.admin.exception.BusinessException
                        .validationError("规则事件类型不能为空"));

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_TEMPLATE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").isNotEmpty());
        withInterceptor(new NotificationRuleController(ruleService))
                .perform(put("/api/admin/notification-rules/" + RULE_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_RULE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").isNotEmpty());
    }

    @Test
    @DisplayName("判据 2b：同租户自定义行 + 合法载荷 ⇒ 200（写路径照旧执行）")
    void sameTenantValidPayload_stillOk() throws Exception {
        targetState(true, true);
        when(templateService.updateTemplate(eq(TEST_TENANT_ID), eq(TPL_ID), any()))
                .thenReturn(templateDto());
        when(ruleService.updateRule(eq(TEST_TENANT_ID), eq(RULE_ID), any()))
                .thenReturn(ruleDto());

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_TEMPLATE_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value(TPL_ID));
        withInterceptor(new NotificationRuleController(ruleService))
                .perform(put("/api/admin/notification-rules/" + RULE_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_RULE_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value(RULE_ID));
    }

    // ══════════ 判据 3：系统内置行（tenant_id=0）可读不可写 ══════════

    @Test
    @DisplayName("判据 3a 🔴 正对照：系统内置行**仍可读**（既有『可读』语义不许被收紧）")
    void systemBuiltInRow_isStillReadable() throws Exception {
        // 可读面 = OR 0 ⇒ 系统内置行（tenant_id=0）必须仍出现在列表里
        NotificationTemplateDTO builtIn = new NotificationTemplateDTO();
        builtIn.setId("tpl-system");
        builtIn.setName("系统内置：新订单通知");
        builtIn.setTenantId(0L);
        when(templateService.queryTemplates(eq(1L), eq(20L), eq(TEST_TENANT_ID)))
                .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(builtIn)));

        buildMockMvc(new NotificationTemplateController(templateService))
                .perform(get("/api/admin/notification-templates?page=1&size=20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].id").value("tpl-system"));
    }

    @Test
    @DisplayName("判据 3b：系统内置行 + 写 ⇒ 422「系统内置…不允许修改」，**不是** 404（可见但不可写）")
    void systemBuiltInRow_isReadableButNotWritable() throws Exception {
        // 可见（OR 0 命中）但不可写（tenant_id=0 ≠ 当前租户）—— 认定通过可见面，卡在可写面
        targetState(true, false);

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/tpl-system")
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_TEMPLATE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("系统内置")));
        withInterceptor(new NotificationRuleController(ruleService))
                .perform(put("/api/admin/notification-rules/rule-system")
                        .contentType(MediaType.APPLICATION_JSON).content(GOOD_RULE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("系统内置")));

        // 卡在可写面 ⇒ 写服务零调用（没有写）
        verify(templateService, never()).updateTemplate(anyLong(), anyString(), any());
        verify(ruleService, never()).updateRule(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("判据 3c：系统内置行 + **非法**载荷 ⇒ 仍 422（可写认定不改变非法载荷的读数）")
    void systemBuiltInRowWithInvalidPayload_stillValidationError() throws Exception {
        targetState(true, false);

        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/tpl-system")
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_TEMPLATE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("系统内置")));
        verify(templateService, never()).updateTemplate(anyLong(), anyString(), any());
    }

    // ══════════ 判据 5：两侧夹住（判据非空自证）══════════

    @Test
    @DisplayName("🔴 两侧夹住：摘掉拦截器 ⇒ 同一个「跨租户 + 非法载荷」请求当场变回 422")
    void withoutInterceptor_sameRequestIsNot404_outOfBand() throws Exception {
        targetState(false, false);
        NotificationTemplateController controller = new NotificationTemplateController(templateService);
        when(templateService.updateTemplate(anyLong(), anyString(), any()))
                .thenThrow(com.migao.admin.exception.BusinessException
                        .validationError("模板名称与模板内容不能为空"));

        // 反面对照：没有本包的接线 ⇒ 载荷校验（service 层）先发生 ⇒ 422
        withoutInterceptor(controller)
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_TEMPLATE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));

        // 同一份夹具、同一个 id，挂上拦截器 ⇒ 404（差值只来自接线）
        withInterceptor(new NotificationTemplateController(templateService))
                .perform(put("/api/admin/notification-templates/" + TPL_ID)
                        .contentType(MediaType.APPLICATION_JSON).content(BAD_TEMPLATE_BODY))
                .andExpect(status().isNotFound());
    }

    // ══════════ 判据 6：登记表现取 + fail-closed ══════════

    @Test
    @DisplayName("判据 6a：登记表现取 —— 混合表两个键都在（且可写认定只登记了这一族）")
    void registryCoversMixedTables() {
        org.assertj.core.api.Assertions.assertThat(ownership.registeredResources())
                .contains("notification-template", "notification-rule");
        org.assertj.core.api.Assertions.assertThat(ownership.writableResources())
                .containsExactlyInAnyOrder("notification-template", "notification-rule");
    }

    @Test
    @DisplayName("判据 6b：可写认定**只**登记混合表这一族 —— 其余资源键不重判 T1 的「可见即可写」形态")
    void writableCheckOnlyAppliesToRegisteredKeys() {
        // 可写认定是 T1 之上的**增量**：只有「可读面比可写面宽」的资源才登记它。
        // 若有人把 product/order 也塞进来，本判据当场红 —— 那意味着在重写 T1 的归属判定。
        org.assertj.core.api.Assertions.assertThat(ownership.writableResources())
                .doesNotContain("product", "order", "category", "processing-item",
                        "processing-category", "after-sales-ticket");
    }
}
