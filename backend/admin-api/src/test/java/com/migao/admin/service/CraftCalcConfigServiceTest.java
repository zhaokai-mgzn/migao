package com.migao.admin.service;

// case_ids: OR-041

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 算料配置服务测试（issue #4528 = 包 E）—— 本包**核心护栏**的落点。
 *
 * <p>守四条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>缺行 = 引擎默认值</b>（{@code source='default'}）：默认值取自
 *       {@link CraftCalcClient#defaultConfig()}，<b>不在本服务里写死</b> ——
 *       红证：把 mock 的默认值改成 0.99，读面必须原样回 0.99（服务自带一份常量 ⇒ 红）；</li>
 *   <li><b>非法值 ⇒ 422 + 逐条理由</b>（{@code error.details:[{field,message}]}），
 *       <b>不得静默回退默认值</b>：红证：静默回退 ⇒ 不抛异常 + 落库 ⇒ 红；</li>
 *   <li><b>不跨租户串</b>：连续读两个租户各归各（无字段/静态缓存）；</li>
 *   <li><b>upsert</b>：无行 ⇒ insert（确定性 id），有行 ⇒ updateById（同一行，不产生第二行）。</li>
 * </ol>
 */
@DisplayName("CraftCalcConfigService 算料配置（issue #4528）")
class CraftCalcConfigServiceTest {

    private CraftCalcConfigMapper mapper;
    private CraftCalcClient client;
    private CraftCalcConfigService service;

    @BeforeEach
    void setUp() {
        mapper = mock(CraftCalcConfigMapper.class);
        client = mock(CraftCalcClient.class);
        service = new CraftCalcConfigService(mapper, client);
    }

    /** 一份**合法**的全量配置（PUT 是全量替换 ⇒ 键必须齐）。 */
    static Map<String, Object> validBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("per_fold_single", 0.25);
        body.put("per_fold_mixed_times", new LinkedHashMap<>(Map.of("1", 0.65, "2", 1.2)));
        body.put("margin_single", 0.2);
        body.put("margin_multi", 0.3);
        body.put("min_fullness", 1.5);
        body.put("tiers", new LinkedHashMap<>(Map.of(
                "standard", new LinkedHashMap<>(Map.of("fullness", 2.0, "label", "标准工艺")),
                "economy", new LinkedHashMap<>(Map.of("fullness", 1.8, "label", "经济工艺")))));
        body.put("default_formula", "pleat");
        body.put("hem_margin", 0.3);
        body.put("meters_rounding_step", 0.1);
        return body;
    }

    private static Map<String, Object> withKey(String key, Object value) {
        Map<String, Object> body = validBody();
        body.put(key, value);
        return body;
    }

    /** 把 422 的**逐条理由**取出来（{@code field=message} 列表），便于逐条断言。 */
    @SuppressWarnings("unchecked")
    private static List<ApiResponse.ErrorDetail> detailsOf(BusinessException e) {
        assertThat(e.getHttpStatus()).isEqualTo(422);
        return (List<ApiResponse.ErrorDetail>) e.getDetails();
    }

    private static String fieldsOf(List<ApiResponse.ErrorDetail> details) {
        return details.stream().map(ApiResponse.ErrorDetail::getField).toList().toString();
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 1：缺行 ⇒ 引擎默认值 + source='default'
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("无配置行 ⇒ source=default 且值**逐值取自引擎**（凭空造一份默认 ⇒ 红）")
    void getWithoutRowUsesEngineDefaults() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);
        // 引擎默认值故意给一个**非 0.25** 的值：服务若自带一份默认常量，本断言必红
        when(client.defaultConfig()).thenReturn(Map.of("per_fold_single", 0.99, "min_fullness", 1.5));

        Map<String, Object> data = service.get(7L);

        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_DEFAULT);
        @SuppressWarnings("unchecked")
        Map<String, Object> config = (Map<String, Object>) data.get("config");
        assertThat(config).containsEntry("per_fold_single", 0.99);
        verify(mapper, never()).insert(any(CraftCalcConfig.class));
    }

    @Test
    @DisplayName("有配置行 ⇒ source=stored 且逐值回显本租户行")
    void getWithRowReturnsStored() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(row(7L, "0.5", "0.4"));

        Map<String, Object> data = service.get(7L);

        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_STORED);
        @SuppressWarnings("unchecked")
        Map<String, Object> config = (Map<String, Object>) data.get("config");
        assertThat(config).containsEntry("per_fold_single", new BigDecimal("0.5"));
        assertThat(config).containsEntry("margin_multi", new BigDecimal("0.4"));
        verify(client, never()).defaultConfig();   // 有行就不该去问引擎要默认值
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 3：护栏 —— 非法值 422 + 逐条理由（不静默回退默认值）
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("min_fullness 低于行业红线 1.5 ⇒ 422（可配但不可关）")
    void minFullnessBelowRedLineRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("min_fullness", 1.0)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    List<ApiResponse.ErrorDetail> details = detailsOf((BusinessException) e);
                    assertThat(fieldsOf(details)).contains("min_fullness");
                    assertThat(details.toString()).contains("行业红线");
                });
        verify(mapper, never()).insert(any(CraftCalcConfig.class));
    }

    @Test
    @DisplayName("每折吃布 / 余量 ≤ 0 ⇒ 422（引擎也会拒 0 ⇒ 存进去也算不出料）")
    void nonPositiveNumbersRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("per_fold_single", 0)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("per_fold_single"));
        assertThatThrownBy(() -> service.put(7L, withKey("margin_single", -1)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("margin_single"));
    }

    @Test
    @DisplayName("tiers 空 / 档位倍数低于 min_fullness / 非对象 ⇒ 422 逐条（field 指到具体档位）")
    void tierGuardrailsRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("tiers", Map.of())))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e))).contains("tiers"));

        Map<String, Object> lowTier = Map.of("economy", Map.of("fullness", 1.2, "label", "经济工艺"));
        assertThatThrownBy(() -> service.put(7L, withKey("tiers", lowTier)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    List<ApiResponse.ErrorDetail> details = detailsOf((BusinessException) e);
                    assertThat(fieldsOf(details)).contains("tiers.economy.fullness");
                    assertThat(details.toString()).contains("min_fullness");
                });

        assertThatThrownBy(() -> service.put(7L, withKey("tiers", Map.of("standard", "标准工艺"))))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("tiers.standard"));
    }

    @Test
    @DisplayName("拼次键非正整数 / 系数 ≤ 0 ⇒ 422（丢一档 = 拼色退回单色 = 少算用料）")
    void mixedTimesGuardrailsRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("per_fold_mixed_times", Map.of("一次", 0.5))))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("per_fold_mixed_times.一次"));
        assertThatThrownBy(() -> service.put(7L, withKey("per_fold_mixed_times", Map.of("1", 0))))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("per_fold_mixed_times.1"));
        assertThatThrownBy(() -> service.put(7L, withKey("per_fold_mixed_times", Map.of())))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("per_fold_mixed_times"));
    }

    @Test
    @DisplayName("default_formula 不在枚举内 ⇒ 422（pleat / fullness）")
    void unknownFormulaRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("default_formula", "hanzhe")))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    List<ApiResponse.ErrorDetail> details = detailsOf((BusinessException) e);
                    assertThat(fieldsOf(details)).contains("default_formula");
                    assertThat(details.toString()).contains("pleat");
                });
    }

    @Test
    @DisplayName("缺键 ⇒ 422 逐键报缺（PUT 是全量替换：缺键不得静默按默认值存）")
    void missingKeysRejected() {
        Map<String, Object> body = validBody();
        // ⚠️ issue #5030：原判据删的是 `side_margin` —— 该键（宽方向左右覆盖余量）已整体退场
        // ⇒ 改用**仍存在**的 `hem_margin`（高方向上下卷边）。判据强度**不变**：
        // 缺键必须逐键报缺、不得静默按默认值存（PUT 是全量替换）。
        body.remove("hem_margin");
        assertThatThrownBy(() -> service.put(7L, body))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    List<ApiResponse.ErrorDetail> details = detailsOf((BusinessException) e);
                    assertThat(fieldsOf(details)).contains("hem_margin");
                    assertThat(details.toString()).contains("全量替换");
                });
    }

    @Test
    @DisplayName("未知键 ⇒ 422（拼错的键被静默忽略 = 商家以为改了却没改）")
    void unknownKeysRejected() {
        assertThatThrownBy(() -> service.put(7L, withKey("per_fold_singel", 0.3)))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(fieldsOf(detailsOf((BusinessException) e)))
                        .contains("per_fold_singel"));
    }

    @Test
    @DisplayName("多处以同时不合法 ⇒ **一次**返回全部逐条理由（不是只报第一条）")
    void allViolationsReportedAtOnce() {
        Map<String, Object> body = validBody();
        body.put("min_fullness", 1.0);
        body.put("default_formula", "hanzhe");
        body.put("meters_rounding_step", 0);

        assertThatThrownBy(() -> service.put(7L, body))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    List<ApiResponse.ErrorDetail> details = detailsOf((BusinessException) e);
                    assertThat(fieldsOf(details))
                            .contains("min_fullness", "default_formula", "meters_rounding_step");
                    assertThat(details).hasSize(3);
                    assertThat(((BusinessException) e).getSuggestion()).contains("craft-calc-config");
                });
    }

    // ══════════════════════════════════════════════════════════════════════
    // upsert + 租户隔离
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("无行 ⇒ insert（确定性 id ccc-<tenant>，不产生第二份默认值）")
    void putInsertsWhenNoRow() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);

        Map<String, Object> data = service.put(7L, withKey("per_fold_single", 0.5));

        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_STORED);
        ArgumentCaptor<CraftCalcConfig> captor = ArgumentCaptor.forClass(CraftCalcConfig.class);
        verify(mapper).insert(captor.capture());
        CraftCalcConfig inserted = captor.getValue();
        assertThat(inserted.getId()).isEqualTo("ccc-7");
        assertThat(inserted.getTenantId()).isEqualTo(7L);
        assertThat(inserted.getPerFoldSingle()).isEqualByComparingTo("0.5");
        assertThat(inserted.getDeleted()).isZero();
        verify(mapper, never()).updateById(any(CraftCalcConfig.class));
    }

    @Test
    @DisplayName("有行 ⇒ updateById 同一行（不产生第二行）")
    void putUpdatesWhenRowExists() {
        CraftCalcConfig existing = row(7L, "0.25", "0.3");
        when(mapper.selectActiveByTenant(7L)).thenReturn(existing);

        service.put(7L, withKey("per_fold_single", "0.5"));   // 字符串形态也必须接受（表单常见）

        ArgumentCaptor<CraftCalcConfig> captor = ArgumentCaptor.forClass(CraftCalcConfig.class);
        verify(mapper).updateById(captor.capture());
        assertThat(captor.getValue().getId()).isEqualTo("ccc-7");
        assertThat(captor.getValue().getPerFoldSingle()).isEqualByComparingTo("0.5");
        verify(mapper, never()).insert(any(CraftCalcConfig.class));
    }

    @Test
    @DisplayName("不跨租户串：连续读两个租户各归各（无字段/静态缓存）")
    void doesNotLeakAcrossTenants() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(row(7L, "0.5", "0.3"));
        when(mapper.selectActiveByTenant(8L)).thenReturn(row(8L, "0.2", "0.9"));

        assertThat(configOf(service.get(7L))).containsEntry("per_fold_single", new BigDecimal("0.5"));
        assertThat(configOf(service.get(8L))).containsEntry("per_fold_single", new BigDecimal("0.2"));
        assertThat(configOf(service.get(8L))).containsEntry("margin_multi", new BigDecimal("0.9"));
    }

    @Test
    @DisplayName("无租户上下文 ⇒ 401 租户无效（不猜一个租户去读别人的配置）")
    void nullTenantRejected() {
        assertThatThrownBy(() -> service.get(null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode()).isEqualTo("TENANT_INVALID"));
        assertThatThrownBy(() -> service.put(null, validBody()))
                .isInstanceOf(BusinessException.class);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> configOf(Map<String, Object> data) {
        return (Map<String, Object>) data.get("config");
    }

    private static CraftCalcConfig row(Long tenantId, String perFoldSingle, String marginMulti) {
        return CraftCalcConfig.builder()
                .id("ccc-" + tenantId)
                .tenantId(tenantId)
                .perFoldSingle(new BigDecimal(perFoldSingle))
                .perFoldMixedTimes(Map.of("1", new BigDecimal("0.65")))
                .marginSingle(new BigDecimal("0.2"))
                .marginMulti(new BigDecimal(marginMulti))
                .minFullness(new BigDecimal("1.5"))
                .tiers(Map.of("standard", Map.of("fullness", new BigDecimal("2.0"))))
                .defaultFormula("pleat")
                .metersRoundingStep(new BigDecimal("0.1"))
                .status("active")
                .deleted(0)
                .build();
    }
}
