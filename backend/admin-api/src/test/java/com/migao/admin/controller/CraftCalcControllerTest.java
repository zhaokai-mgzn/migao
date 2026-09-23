package com.migao.admin.controller;

// case_ids: OR-032

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.CraftCalcClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
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
 * 算料试算控制器测试（issue #4421）
 *
 * 判据：
 *   ① 端点 `POST /api/admin/orders/craft-calc` 返回 `{success,data}` 外壳，`data` 含
 *      `fabricMeters` / `pleatCount` / `formulaText`（**公式串由后端（ai-agent）产出**，
 *      控制器只搬运，绝不自拼）；
 *   ② 入参校验 fail-closed：缺 width / width ≤ 0 ⇒ 400，且**不调** ai-agent；
 *   ③ 权限：`@RequirePermission("order:list")`（下单页试算属订单读域）；
 *   ④ 不落库：控制器只调 `CraftCalcClient`，不碰任何 Repository/Service 写路径
 *      （试算 = 纯读，落库由下单接口负责）。
 *
 * 红证（实现前）：`CraftCalcController` 不存在 ⇒ 本文件编译失败（找不到符号）。
 */
@DisplayName("CraftCalcController 算料试算端点（issue #4421）")
class CraftCalcControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/orders/craft-calc";

    private CraftCalcClient craftCalcClient;
    private CraftCalcController controller;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        craftCalcClient = mock(CraftCalcClient.class);
        controller = new CraftCalcController(craftCalcClient);
        mockMvc = buildMockMvc(controller);
    }

    private static CraftCalcClient.CraftCalcResult frozen() {
        return new CraftCalcClient.CraftCalcResult(
                new BigDecimal("13.3"), 52, 26, new BigDecimal("0.25"),
                new BigDecimal("2.0"), new BigDecimal("2.02"),
                "fixed_height_pleats",
                "韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米",
                "formula", "standard", "",
                // issue #5201：未走三项输入通路 ⇒ `plan` 为 null（键恒在，值缺省）
                null);
    }

    /** 褶倍数公式（issue #4527）冻结样例：5.5m / 双开 / 2.0 倍 ⇒ 11.0 米（ERP 实证锚点）。 */
    private static CraftCalcClient.CraftCalcResult frozenFullness() {
        return new CraftCalcClient.CraftCalcResult(
                new BigDecimal("11.0"), 0, 0, null,
                new BigDecimal("2.0"), null,
                "fixed_height_fullness",
                "褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11.0米",
                "formula", "standard", "",
                null);
    }

    /** 自动推导 `plan`（issue #5201，契约 §四）冻结样例：倒幅 5 幅 / 拼 4 次 / 14.0 米。 */
    private static CraftCalcClient.CraftCalcResult frozenWithPlan() {
        Map<String, Object> plan = new java.util.LinkedHashMap<>();
        plan.put("cutting_mode", "定宽买高");
        plan.put("door_width", 3.2);
        plan.put("panels", 5);
        plan.put("splice_times", 4);
        plan.put("splice_option", null);
        plan.put("join_height_m", null);
        plan.put("join_width_m", null);
        plan.put("meters", 14.0);
        plan.put("auto", true);
        plan.put("reason", "自动推导：倒幅 5 幅 × 幅长 2.8 米");
        plan.put("candidates", java.util.List.of(
                Map.of("key", "fixed_height", "meters", 13.3, "feasible", true,
                        "splice_times", 0, "reason", "成品高 2.8 ≤ 门幅 3.2"),
                Map.of("key", "fixed_width", "meters", 14.0, "feasible", true,
                        "splice_times", 4, "reason", "倒幅 5 幅")));
        return new CraftCalcClient.CraftCalcResult(
                new BigDecimal("14.0"), 52, 26, new BigDecimal("0.25"),
                new BigDecimal("2.0"), new BigDecimal("2.12"),
                "fixed_width_pleats",
                "韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米",
                "formula", "standard", "", plan);
    }

    @Test
    @DisplayName("冻结样例：6.6m/2.5m/双开/标准档 ⇒ 13.3 米 / 52 折 + 后端公式串")
    void returnsFrozenSampleWithFormulaText() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":6.6,"height":2.5,"open_count":2,"mounting":"s_hook","craft_tier":"standard"}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.fabric_meters").value(13.3))
                .andExpect(jsonPath("$.data.pleat_count").value(52))
                .andExpect(jsonPath("$.data.per_panel_pleats").value(26))
                .andExpect(jsonPath("$.data.per_fold").value(0.25))
                .andExpect(jsonPath("$.data.fullness").value(2.0))
                .andExpect(jsonPath("$.data.fullness_actual").value(2.02))
                .andExpect(jsonPath("$.data.source").value("formula"))
                .andExpect(jsonPath("$.data.formula_text")
                        .value("韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米"));
    }

    @Test
    @DisplayName("#4527 formula 原样透传给 ai-agent（控制器不校验、不改写、不补默认值）")
    @SuppressWarnings("unchecked")
    void passesFormulaThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozenFullness());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":5.5,"open_count":2,"craft_tier":"standard","formula":"fullness"}
                        """))
                .andExpect(status().isOk());

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).calc(captor.capture());
        assertThat(captor.getValue()).containsEntry("formula", "fullness");
    }

    @Test
    @DisplayName("#4527 褶倍数公式：11.0 米 + 后端公式串（控制器**不自拼**公式，两种串形态都由引擎给）")
    void returnsFullnessFormulaResultVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozenFullness());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":5.5,"open_count":2,"craft_tier":"standard","formula":"fullness"}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.fabric_meters").value(11.0))
                .andExpect(jsonPath("$.data.formula_used").value("fixed_height_fullness"))
                .andExpect(jsonPath("$.data.formula_text")
                        .value("褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11.0米"));
    }

    @Test
    @DisplayName("入参原样透传给 ai-agent：控制器不补默认值、不重算（防第二份算料逻辑）")
    @SuppressWarnings("unchecked")
    void passesRequestBodyThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":6.6,"height":2.5,"open_count":2,"mounting":"s_hook","craft_tier":"standard"}
                        """))
                .andExpect(status().isOk());

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).calc(captor.capture());
        assertThat(captor.getValue())
                .containsEntry("width", 6.6)
                .containsEntry("height", 2.5)
                .containsEntry("open_count", 2)
                .containsEntry("mounting", "s_hook")
                .containsEntry("craft_tier", "standard");
    }

    @Test
    @DisplayName("拼色入参逐字透传：style + special_options 原样给 ai-agent（系数由后端定，Java 侧不自算）")
    @SuppressWarnings("unchecked")
    void passesMixedColorOptionsThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content(
                        "{\"width\":6.6,\"open_count\":2,\"style\":\"拼色\",\"special_options\":[\"拼1次\"]}"))
                .andExpect(status().isOk());

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).calc(captor.capture());
        assertThat(captor.getValue())
                .containsEntry("style", "拼色")
                .containsEntry("special_options", java.util.List.of("拼1次"));
    }

    @Test
    @DisplayName("缺 width ⇒ 400 且**不调** ai-agent（fail-closed，不猜窗宽）")
    void missingWidthRejectedWithoutCalling() throws Exception {
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"height\":2.5}"))
                .andExpect(status().isBadRequest());

        verify(craftCalcClient, never()).calc(any());
    }

    @Test
    @DisplayName("width ≤ 0 ⇒ 400 且**不调** ai-agent")
    void nonPositiveWidthRejectedWithoutCalling() throws Exception {
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":0}"))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":-1}"))
                .andExpect(status().isBadRequest());

        verify(craftCalcClient, never()).calc(any());
    }

    @Test
    @DisplayName("ai-agent 不可用 ⇒ 422 透传错误码（不静默给 0 米）")
    void unavailableAgentPropagatesFailClosed() throws Exception {
        when(craftCalcClient.calc(any())).thenThrow(new BusinessException(
                CraftCalcClient.ERR_CRAFT_CALC_UNAVAILABLE, "算料服务（ai-agent）不可用", 422, "请确认服务已启动"));

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":6.6}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("CRAFT_CALC_UNAVAILABLE"));
    }

    @Test
    @DisplayName("键名口径：响应算料键必须是 snake_case（设计文档 §4.5；改回 camelCase ⇒ 前端要写映射表 = 第二份口径）")
    void calcKeysAreSnakeCase() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        String body = mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":6.6}"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("fabric_meters").contains("pleat_count").contains("per_panel_pleats")
                .contains("per_fold").contains("fullness_actual").contains("formula_used")
                .contains("formula_text").contains("craft_tier");
        // 反证：任一 camelCase 算料键出现即红（`fullness`/`source`/`warning` 无大小写歧义，不在此列）
        assertThat(body).doesNotContain("fabricMeters").doesNotContain("pleatCount")
                .doesNotContain("perPanelPleats").doesNotContain("perFold")
                .doesNotContain("fullnessActual").doesNotContain("formulaUsed")
                .doesNotContain("formulaText").doesNotContain("craftTier");
    }

    @Test
    @DisplayName("权限声明：试算属订单读域 order:list（下单页可用，无需管理权限）")
    void requiresOrderListPermission() throws Exception {
        RequirePermission annotation = CraftCalcController.class
                .getMethod("craftCalc", Map.class).getAnnotation(RequirePermission.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).isEqualTo("order:list");
    }

    // ══════════════════════════════════════════════════════════════════════
    // 自动推导的 `plan`（issue #5201 = 母单 #5200 子单 A，契约 §四 / 判据 10）
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("#5201 plan 原样搬出（含 candidates 数组）+ 键恒在；控制器不重算、不补默认值")
    void planIsPassedThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozenWithPlan());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":6.6}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.plan.cutting_mode").value("定宽买高"))
                .andExpect(jsonPath("$.data.plan.door_width").value(3.2))
                .andExpect(jsonPath("$.data.plan.panels").value(5))
                .andExpect(jsonPath("$.data.plan.splice_times").value(4))
                .andExpect(jsonPath("$.data.plan.splice_option").doesNotExist())   // JSON null ⇒ jsonPath 视为不存在
                .andExpect(jsonPath("$.data.plan.auto").value(true))
                .andExpect(jsonPath("$.data.plan.candidates.length()").value(2))
                .andExpect(jsonPath("$.data.plan.candidates[0].key").value("fixed_height"))
                // 单点口径（判据 10）：plan.meters 与 data.fabric_meters **必须相等**
                // （两者在引擎里是同一个变量；控制器若自己再算一份，这里就会分叉）
                .andExpect(jsonPath("$.data.plan.meters").value(14.0))
                .andExpect(jsonPath("$.data.fabric_meters").value(14.0));
    }

    @Test
    @DisplayName("#5201 plan 键恒在：未走三项输入通路时为 null（调用方可区分「没走」与「走了」）")
    void planKeyIsAlwaysPresent() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozen());

        String body = mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("{\"width\":6.6}"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();

        // 键恒在（`null` 也是键）；反证：键缺席 ⇒ 前端无法区分「没走推导」与「端点没实现」
        assertThat(body).contains("\"plan\"");
        // 🔴 红证形态：把控制器改成「`plan == null` ⇒ 塞一个假方案」（如 `Map.of("meters", 0)`）
        // ⇒ 下面两条必红。为什么必须钉死 `null` 语义：`plan` 为 null = **本次调用没走三项输入通路**
        // （契约 §四），前端据此走「推导服务未就绪」的降级通路；换成 `{meters: 0}` 会绕过降级、
        // 直接渲染「用料 0 米」——0 不得当「未知」的替身（同族纪律：判据 10 与「不给估算值」）。
        assertThat(body).contains("\"plan\":null");
        assertThat(body).doesNotContain("\"meters\":0");
    }

    @Test
    @DisplayName("#5201 新入参（fabric_width/cutting_mode/splice_times/join_*）原样透传给 ai-agent，控制器不改写")
    @SuppressWarnings("unchecked")
    void planInputsArePassedThroughVerbatim() throws Exception {
        when(craftCalcClient.calc(any())).thenReturn(frozenWithPlan());

        mockMvc.perform(post(URL).contentType(APPLICATION_JSON).content("""
                        {"width":6.6,"height":2.5,"fabric_width":3.2,"cutting_mode":"定宽买高",
                         "splice_times":2,"join_height_m":0.05,"join_width_m":0.1}
                        """))
                .andExpect(status().isOk());

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(craftCalcClient).calc(captor.capture());
        Map<String, Object> sent = captor.getValue();
        // 缺省值/校验都在 ai-agent（契约 §四）：本层只搬运 ⇒ 收到什么发什么
        assertThat(sent).containsEntry("fabric_width", 3.2)
                .containsEntry("cutting_mode", "定宽买高")
                .containsEntry("splice_times", 2)
                .containsEntry("join_height_m", 0.05)
                .containsEntry("join_width_m", 0.1);
    }
}
