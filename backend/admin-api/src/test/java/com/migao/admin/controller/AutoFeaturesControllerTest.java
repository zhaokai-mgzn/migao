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
 * 自动特征判定控制器测试（issue #4976 包 2）
 *
 * 判据：
 *   ① 端点 {@code POST /api/admin/orders/auto-features} 返回 {@code {success,data}} 外壳，
 *      {@code data} **原样**含 {@code auto_features} / {@code door_width} / {@code fullness_used} /
 *      {@code notice}（Java 侧只搬运、不重排、不补默认值）；
 *   ② 入参**全部可缺**（缺 ⇒ 交给引擎判「不判」并说明原因）—— 控制器**不**自己补默认值
 *      （补默认门幅 = 拿一个不是这张单的值判价，issue #4877）；
 *   ③ 权限 {@code @RequirePermission("order:list")}（与试算同域）；
 *   ④ **不落库**：只调客户端，不碰任何写路径（判定是纯读）。
 *
 * 红证（实现前）：{@code AutoFeaturesController} 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("AutoFeaturesController 自动特征判定端点（issue #4976 包 2）")
class AutoFeaturesControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/orders/auto-features";

    private CraftCalcClient craftCalcClient;
    private AutoFeaturesController controller;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        // 公共初始化（TenantContext + 管理员认证）由基类的 `@BeforeEach baseSetUp()` 自动执行
        craftCalcClient = mock(CraftCalcClient.class);
        controller = new AutoFeaturesController(craftCalcClient);
        mockMvc = buildMockMvc(controller);
    }

    @Test
    @DisplayName("① 端点原样返回引擎的 data（auto_features / door_width / fullness_used / notice）")
    void returnsEngineDataVerbatim() throws Exception {
        when(craftCalcClient.autoFeatures(any())).thenReturn(Map.of(
                "auto_features", List.of(Map.of(
                        "name", "超宽", "source", "推算",
                        "reason", "成品宽 1.6 + 左右余量 0.3 = 1.9 米 × 褶倍 2.0 = 3.8 米 > 门幅 2.8 米")),
                "door_width", 2.8,
                "fullness_used", 2.0,
                "notice", ""));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON)
                        .content("{\"width\":1.6,\"height\":2.0,\"fabric_width\":2.8,\"cutting_mode\":\"定宽买高\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.auto_features[0].name").value("超宽"))
                .andExpect(jsonPath("$.data.door_width").value(2.8))
                .andExpect(jsonPath("$.data.fullness_used").value(2.0))
                .andExpect(jsonPath("$.data.notice").value(""));
    }

    @Test
    @DisplayName("② 入参原样透传（控制器不补默认值）：缺门幅也照发，由引擎判「不判」并说明原因")
    void passesRequestThroughWithoutDefaults() throws Exception {
        // ⚠️ 用可变 Map：`Map.of` **不接受 null 值**（`door_width` 缺门幅时就是 null）
        Map<String, Object> stub = new LinkedHashMap<>();
        stub.put("auto_features", List.of());
        stub.put("door_width", null);
        stub.put("fullness_used", 2.0);
        stub.put("notice", "missing-door-width");
        when(craftCalcClient.autoFeatures(any())).thenReturn(stub);

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":1.6,\"height\":2.0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.auto_features").isEmpty())
                .andExpect(jsonPath("$.data.notice").value("missing-door-width"));

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).autoFeatures(captor.capture());
        // 注入：控制器自己补 fabric_width（如 2.8/3.2）⇒ 本断言红（那是「拿假门幅判价」）
        assertThat(captor.getValue()).doesNotContainKey("fabric_width");
        assertThat(captor.getValue()).containsEntry("width", 1.6);
    }

    @Test
    @DisplayName("④ 判定是纯读：只调客户端，不碰任何写路径")
    void isReadOnly() throws Exception {
        when(craftCalcClient.autoFeatures(any())).thenReturn(Map.of(
                "auto_features", List.of(), "door_width", 2.8, "fullness_used", 2.0, "notice", ""));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":1.6,\"height\":2.0}"))
                .andExpect(status().isOk());

        verify(craftCalcClient).autoFeatures(any());
        verify(craftCalcClient, never()).calc(any());
    }
}
