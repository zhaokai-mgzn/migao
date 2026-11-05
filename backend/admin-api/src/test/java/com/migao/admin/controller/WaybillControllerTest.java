// case_ids: MC-217, MC-218
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import com.migao.admin.waybill.Carrier;
import com.migao.admin.waybill.TenantLogisticsConfigService;
import com.migao.admin.waybill.WaybillCreateRequest;
import com.migao.admin.waybill.WaybillCreateResult;
import com.migao.admin.waybill.WaybillService;
import com.migao.admin.waybill.WaybillUnsupportedException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 物流取号端点判据（issue #8698 P0）。
 *
 * <ol>
 *   <li><b>能力位是端点的下发字段</b>：{@code GET /carriers} 必须逐条带
 *       {@code canCreate/canCancel/canTrack/mode} —— 前端**不复制词表**（判据 2 的前半）；</li>
 *   <li><b>租户只来自 {@code TenantContext}</b>：请求体 / 参数都伪造不了租户；</li>
 *   <li><b>写面白名单</b>：{@code PUT} 把 {@code carrierCode} 原样交给服务（空 ⇒ {@code null} =
 *       全 manual），控制器不补默认值；</li>
 *   <li><b>取号 ≠ 发货</b>：{@code POST …/waybill} 只返回运单号，**不触碰**任何发货 / 状态写服务
 *       （控制器根本没有这些依赖 —— 判据 {@code verifyNoMoreInteractions} 的射程见下）；</li>
 *   <li><b>权限面</b>：读 {@code production:view} / 配置写 {@code system:manage} / 取号
 *       {@code production:execute}（红证：把取号改成读码 ⇒ 判据 5 红，且
 *       {@code test_rbac_submenu_granularity} 的「写动词挂读码」台账会被撑大）。</li>
 * </ol>
 */
@DisplayName("WaybillController 物流取号端点（issue #8698 P0）")
class WaybillControllerTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/logistics";

    private WaybillService waybillService;
    private TenantLogisticsConfigService configService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        waybillService = mock(WaybillService.class);
        configService = mock(TenantLogisticsConfigService.class);
        mockMvc = buildMockMvc(new WaybillController(waybillService, configService));
    }

    private static Carrier carrier(String code, String name, boolean canCreate, boolean canTrack) {
        return new Carrier(code, name, "express", "SF", canCreate, false, canTrack,
                canCreate ? Carrier.MODE_API : Carrier.MODE_MANUAL);
    }

    private static WaybillService.WaybillCapabilities capabilities() {
        return new WaybillService.WaybillCapabilities(
                List.of(Carrier.MANUAL, carrier("sf", "顺丰速运", false, false)),
                "sf",
                carrier("sf", "顺丰速运", false, false));
    }

    @Test
    @DisplayName("判据 1：GET /carriers 下发逐条能力位 + 生效承运商 + 兜底标记")
    void carriersExposeCapabilityBits() throws Exception {
        when(waybillService.capabilities(TEST_TENANT_ID)).thenReturn(capabilities());

        mockMvc.perform(get(BASE + "/carriers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.carriers[1].code").value("sf"))
                .andExpect(jsonPath("$.data.carriers[1].displayName").value("顺丰速运"))
                .andExpect(jsonPath("$.data.carriers[1].canCreate").value(false))
                .andExpect(jsonPath("$.data.carriers[1].canTrack").value(false))
                .andExpect(jsonPath("$.data.carriers[1].mode").value("manual"))
                .andExpect(jsonPath("$.data.carriers[1].trackQueryCode").value("SF"))
                .andExpect(jsonPath("$.data.configuredCarrier").value("sf"))
                .andExpect(jsonPath("$.data.effectiveCarrier.code").value("sf"))
                .andExpect(jsonPath("$.data.manualFallback").value(true));
    }

    @Test
    @DisplayName("判据 2：租户只来自 TenantContext（请求体伪造 tenantId 不生效）")
    void tenantComesFromContextOnly() throws Exception {
        when(waybillService.capabilities(TEST_TENANT_ID)).thenReturn(capabilities());

        mockMvc.perform(put(BASE + "/carrier-config")
                        .contentType(APPLICATION_JSON)
                        .content("{\"carrierCode\":\"sf\",\"tenantId\":999999}"))
                .andExpect(status().isOk());

        verify(configService).put(eq(TEST_TENANT_ID), eq("sf"));
        verify(configService, never()).put(eq(999999L), any());
    }

    @Test
    @DisplayName("判据 3：PUT 把 carrierCode 原样交给服务（缺键 ⇒ null = 全 manual）")
    void putHandsCarrierCodeVerbatim() throws Exception {
        when(waybillService.capabilities(TEST_TENANT_ID)).thenReturn(capabilities());

        mockMvc.perform(put(BASE + "/carrier-config").contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk());

        ArgumentCaptor<String> code = ArgumentCaptor.forClass(String.class);
        verify(configService).put(eq(TEST_TENANT_ID), code.capture());
        assertThat(code.getValue()).isNull();

        mockMvc.perform(put(BASE + "/carrier-config").contentType(APPLICATION_JSON)
                        .content("{\"carrierCode\":\"sja\"}"))
                .andExpect(status().isOk());
        verify(configService).put(TEST_TENANT_ID, "sja");
    }

    @Test
    @DisplayName("判据 4：POST …/waybill 调取号服务并原样返回运单号（不调任何发货服务）")
    void createReturnsTrackingNoAndTouchesNothingElse() throws Exception {
        when(waybillService.create(eq(TEST_TENANT_ID), eq("o-1"), any(WaybillCreateRequest.class)))
                .thenReturn(new WaybillCreateResult("SF0001", "sf", "顺丰速运"));

        mockMvc.perform(post(BASE + "/orders/o-1/waybill").contentType(APPLICATION_JSON)
                        .content("{\"receiverName\":\"张三\",\"receiverPhone\":\"13800000000\","
                                + "\"receiverAddress\":\"杭州市西湖区文三路 1 号 3 幢\",\"packageCount\":1}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.trackingNo").value("SF0001"))
                .andExpect(jsonPath("$.data.carrierName").value("顺丰速运"))
                // 结果体里**没有**订单状态：取号不是发货
                .andExpect(jsonPath("$.data.status").doesNotExist())
                .andExpect(jsonPath("$.data.orderStatus").doesNotExist());
    }

    @Test
    @DisplayName("判据 4b：未接入 ⇒ 422 + 可行动文案（不吞成 500、不改订单状态）")
    void unsupportedCarrierReturns422() throws Exception {
        when(waybillService.create(eq(TEST_TENANT_ID), eq("o-2"), any(WaybillCreateRequest.class)))
                .thenThrow(WaybillUnsupportedException.manualFallback("四季安物流"));

        mockMvc.perform(post(BASE + "/orders/o-2/waybill").contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.code").value(WaybillUnsupportedException.CODE))
                .andExpect(jsonPath("$.error.message").value(org.hamcrest.Matchers.containsString("手填单号")));
    }

    @Test
    @DisplayName("判据 5：权限面 —— 读 production:view / 配置写 system:manage / 取号 order:update（写码）")
    void permissionSurfaceIsExplicit() throws Exception {
        assertThat(WaybillController.class.getMethod("carriers").getAnnotation(RequirePermission.class).value())
                .isEqualTo("production:view");
        assertThat(WaybillController.class.getMethod("updateCarrierConfig", Map.class)
                .getAnnotation(RequirePermission.class).value()).isEqualTo("system:manage");
        assertThat(WaybillController.class.getMethod("create", String.class, Map.class)
                .getAnnotation(RequirePermission.class).value()).isEqualTo("order:update");
        assertThat(WaybillController.class.getMethod("track", String.class)
                .getAnnotation(RequirePermission.class).value()).isEqualTo("production:view");
    }
}
