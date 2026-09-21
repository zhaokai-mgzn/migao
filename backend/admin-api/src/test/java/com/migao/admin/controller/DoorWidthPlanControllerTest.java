package com.migao.admin.controller;

// case_ids: OR-040

import com.migao.admin.service.CraftCalcClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 门幅规则控制器测试（issue #5043 包 2b）
 *
 * 判据：
 *   ① 端点 {@code POST /api/admin/orders/door-width-plan} 返回 {@code {success,data}} 外壳，
 *      {@code data} **原样**含 {@code state} / {@code code} / {@code effective_cutting_mode} /
 *      {@code door_width} / {@code panels} / {@code splice} / {@code verdict} / {@code suggestion} /
 *      {@code reason}（Java 侧只搬运、**不重排、不补默认值、不复制规则**）；
 *   ② 入参**原样透传**（控制器**不**自己补候选门幅 / 加工类型 —— 补一个不是这张单的值 = 第二份口径，
 *      issue #4877 / #5043）；
 *   ③ 权限 {@code @RequirePermission("order:list")}（与试算 / 判定同域）；
 *   ④ **只读**：只调客户端，不碰任何写路径（规则不产生米数、不落库、不取价）。
 *
 * 红证（实现前）：{@code DoorWidthPlanController} 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("DoorWidthPlanController 门幅规则端点（issue #5043 包 2b）")
class DoorWidthPlanControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/orders/door-width-plan";

    private CraftCalcClient craftCalcClient;
    private DoorWidthPlanController controller;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        // 公共初始化（TenantContext + 管理员认证）由基类的 `@BeforeEach baseSetUp()` 自动执行
        craftCalcClient = mock(CraftCalcClient.class);
        controller = new DoorWidthPlanController(craftCalcClient);
        mockMvc = buildMockMvc(controller);
    }

    @Test
    @DisplayName("① 端点原样返回引擎的 data（state/door_width/panels/verdict/suggestion）")
    void returnsEngineDataVerbatim() throws Exception {
        when(craftCalcClient.doorWidthPlan(any())).thenReturn(Map.of(
                "state", "single_panel",
                "code", "",
                "effective_cutting_mode", "定高买宽",
                "door_width", 2.8,
                "panels", 1,
                "splice", false,
                "verdict", "suboptimal",
                "suggestion", "规则解是 2.8 米门幅（可行集里最小）",
                "reason", "成品高 2.4 + 上下卷边 0.3 = 2.7 米 ≤ 门幅 2.8 米"));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON)
                        .content("{\"width\":3.0,\"height\":2.4,\"door_widths\":[2.8,3.2],\"selected_door_width\":3.2}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.state").value("single_panel"))
                .andExpect(jsonPath("$.data.effective_cutting_mode").value("定高买宽"))
                .andExpect(jsonPath("$.data.door_width").value(2.8))
                .andExpect(jsonPath("$.data.panels").value(1))
                .andExpect(jsonPath("$.data.verdict").value("suboptimal"))
                .andExpect(jsonPath("$.data.suggestion").exists());
    }

    @Test
    @DisplayName("② 入参原样透传（控制器不补候选门幅 / 加工类型）：判不了也照发，由引擎给 code")
    void passesRequestThroughWithoutDefaults() throws Exception {
        // ⚠️ 用可变 Map：`Map.of` **不接受 null 值**（`door_width` 不可判定时就是 null）
        Map<String, Object> stub = new LinkedHashMap<>();
        stub.put("state", "undecidable");
        stub.put("code", "no-door-width");
        stub.put("effective_cutting_mode", null);
        stub.put("door_width", null);
        stub.put("panels", null);
        stub.put("splice", false);
        stub.put("verdict", "unknown");
        stub.put("suggestion", null);
        stub.put("reason", "该规格没有可用门幅");
        when(craftCalcClient.doorWidthPlan(any())).thenReturn(stub);

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON)
                        .content("{\"width\":1.5,\"height\":2.6}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.state").value("undecidable"))
                .andExpect(jsonPath("$.data.code").value("no-door-width"))
                .andExpect(jsonPath("$.data.verdict").value("unknown"));

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).doorWidthPlan(captor.capture());
        // 注入：控制器自己补 door_widths（如 [2.8]）⇒ 本断言红（那是「拿假门幅算规则」）
        assertThat(captor.getValue()).doesNotContainKey("door_widths");
        assertThat(captor.getValue()).doesNotContainKey("cutting_mode");
        assertThat(captor.getValue()).containsEntry("width", 1.5);
    }

    @Test
    @DisplayName("④ 规则是纯读：只调客户端，不碰任何写路径（不算料、不取价、不落库）")
    void isReadOnly() throws Exception {
        when(craftCalcClient.doorWidthPlan(any())).thenReturn(Map.of(
                "state", "single_panel", "code", "",
                "effective_cutting_mode", "定高买宽",
                "door_width", 2.8, "panels", 1, "splice", false,
                "verdict", "unknown", "suggestion", "", "reason", ""));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON)
                        .content("{\"width\":1.5,\"height\":2.6,\"door_widths\":[2.8]}"))
                .andExpect(status().isOk());

        verify(craftCalcClient).doorWidthPlan(any());
        verify(craftCalcClient, never()).calc(any());
        verify(craftCalcClient, never()).autoFeatures(any());
    }

    @Test
    @DisplayName("①' 响应里**没有**金额字段（只读规则面，不取价）")
    void carriesNoMoneyFields() throws Exception {
        when(craftCalcClient.doorWidthPlan(any())).thenReturn(Map.of(
                "state", "single_panel", "code", "",
                "effective_cutting_mode", "定高买宽",
                "door_width", 2.8, "panels", 1, "splice", false,
                "verdict", "optimal", "suggestion", "", "reason", ""));

        String body = mockMvc.perform(post(URL).contentType(APPLICATION_JSON)
                        .content("{\"width\":1.5,\"height\":2.4,\"door_widths\":[2.8]}"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();

        for (String money : List.of("total_price", "fabric_price", "amount")) {
            assertThat(body).doesNotContain(money);
        }
    }
}
