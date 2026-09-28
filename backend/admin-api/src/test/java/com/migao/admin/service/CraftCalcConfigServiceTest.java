package com.migao.admin.service;

// case_ids: OR-041

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.entity.TenantParamAudit;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import com.migao.admin.mapper.TenantParamAuditMapper;
import com.migao.admin.security.SecurityUser;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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
    private TenantParamAuditMapper auditMapper;
    private SimpleMeterRegistry meters;
    private CraftCalcConfigService service;

    @BeforeEach
    void setUp() {
        mapper = mock(CraftCalcConfigMapper.class);
        client = mock(CraftCalcClient.class);
        // 变更留痕腿（§22 P6）：**真**服务 + mock mapper ⇒ 既能断言「写了哪一行」，
        // 又能注入写失败（口径 B 的判据需要一个真的会抛的审计腿）。
        auditMapper = mock(TenantParamAuditMapper.class);
        meters = new SimpleMeterRegistry();
        service = new CraftCalcConfigService(mapper, client,
                new TenantParamAuditService(auditMapper, meters, new ObjectMapper()));
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
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
        // 🔴 issue #5130（V114）：两个**企业阈值**（超宽 / 超高判据）也是配置键 ⇒
        // 全量替换的「合法全量载荷」必须含它们（少了 = 每次 PUT 都 422 报缺键）
        body.put("oversize_width_threshold", 6);
        body.put("oversize_height_threshold", 4);
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

    // ══════════════════════════════════════════════════════════════════════
    // 判据 6（§22 P3 逐键「我改过没有」，issue #5131 增量 2）：`with_defaults`
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("默认（不带 with_defaults）⇒ 不含 defaults/defaults_source，且**不问引擎**（既有契约逐字节不变）")
    void getWithoutFlagKeepsLegacyShape() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(row(7L, "0.5", "0.4"));

        Map<String, Object> data = service.get(7L);

        assertThat(data.keySet()).containsExactly("source", "config");
        verify(client, never()).defaultConfig();
    }

    @Test
    @DisplayName("with_defaults=true + 有行 ⇒ defaults **逐值取自引擎**（不是回显 config）+ defaults_source=engine")
    void getWithDefaultsReturnsEngineDefaultsNotEcho() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(row(7L, "0.5", "0.4"));
        // 引擎默认值故意给**与 row 不同**的值：服务若把 config 回显成 defaults，本断言必红
        when(client.defaultConfig()).thenReturn(Map.of("per_fold_single", 0.25, "min_fullness", 1.5));

        Map<String, Object> data = service.get(7L, true);

        assertThat(data).containsEntry("defaults_source", CraftCalcConfigService.DEFAULTS_SOURCE_ENGINE);
        @SuppressWarnings("unchecked")
        Map<String, Object> defaults = (Map<String, Object>) data.get("defaults");
        assertThat(defaults).containsEntry("per_fold_single", 0.25);
        assertThat(defaults.get("per_fold_single")).isNotEqualTo(new BigDecimal("0.5"));
    }

    @Test
    @DisplayName("with_defaults=true + 有行 + 引擎不可达 ⇒ **不失败**且**显式** unavailable（静默回退 / 抛 422 ⇒ 红）")
    void getWithDefaultsDegradesExplicitlyWhenEngineDown() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(row(7L, "0.5", "0.4"));
        when(client.defaultConfig()).thenThrow(new RuntimeException("ai-agent 不可达"));

        Map<String, Object> data = service.get(7L, true);

        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_STORED);
        assertThat(data).containsEntry("defaults_source",
                CraftCalcConfigService.DEFAULTS_SOURCE_UNAVAILABLE);
        // 🔴 「拿不到」**不得**画成「就是默认值」
        assertThat(data).doesNotContainKey("defaults");
        @SuppressWarnings("unchecked")
        Map<String, Object> config = (Map<String, Object>) data.get("config");
        assertThat(config).containsEntry("per_fold_single", new BigDecimal("0.5"));
    }

    @Test
    @DisplayName("with_defaults=true + 无行 ⇒ defaults 与 config **同一份**（不第二次调用引擎）")
    void getWithDefaultsWithoutRowReusesTheSameMap() {
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);
        when(client.defaultConfig()).thenReturn(Map.of("per_fold_single", 0.99));

        Map<String, Object> data = service.get(7L, true);

        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_DEFAULT);
        assertThat(data.get("defaults")).isSameAs(data.get("config"));
        verify(client).defaultConfig();   // 恰好一次（verify 默认 times(1)）
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 7（§22 P6 变更留痕，issue #5131；口径 B = best-effort）：写面留痕
    // ══════════════════════════════════════════════════════════════════════

    /** 已认证的商家用户（写面的真实形态：控制器 → 服务，SecurityContext 里有 SecurityUser）。 */
    private static void authenticate() {
        SecurityUser user = new SecurityUser("u-9", 7L, "13800138000", List.of("admin"), List.of());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
    }

    /** 首次保存（无配置行）⇒ 返回**服务真正落进实体**的那一份（当「库里的行」用，不手搓夹具）。 */
    private CraftCalcConfig saveFirstTime(Map<String, Object> body) {
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);
        service.put(7L, body);
        ArgumentCaptor<CraftCalcConfig> captor = ArgumentCaptor.forClass(CraftCalcConfig.class);
        verify(mapper).insert(captor.capture());
        return captor.getValue();
    }

    @Test
    @DisplayName("PUT 必须把 hem_margin / 两个超阈键**落库**（改前：收下、校验、200，却一个字都没写）")
    void putPersistsHemMarginAndOversizeThresholds() {
        Map<String, Object> body = validBody();
        body.put("hem_margin", 0.25);
        body.put("oversize_width_threshold", 5.5);
        body.put("oversize_height_threshold", 3.5);

        // ① 首次保存（insert）：三列必须进实体（改前它们**不在** apply() 里 ⇒ 断言红）
        CraftCalcConfig inserted = saveFirstTime(body);
        assertThat(inserted.getHemMargin()).isEqualByComparingTo("0.25");
        assertThat(inserted.getOversizeWidthThreshold()).isEqualByComparingTo("5.5");
        assertThat(inserted.getOversizeHeightThreshold()).isEqualByComparingTo("3.5");

        // ② 已有行（updateById）：同样必须落库，且**读面回显**的就是刚存下的值
        when(mapper.selectActiveByTenant(7L)).thenReturn(inserted);
        Map<String, Object> changed = validBody();
        changed.put("hem_margin", 0.2);
        changed.put("oversize_width_threshold", 5.0);
        changed.put("oversize_height_threshold", 3.0);
        Map<String, Object> data = service.put(7L, changed);

        ArgumentCaptor<CraftCalcConfig> updated = ArgumentCaptor.forClass(CraftCalcConfig.class);
        verify(mapper).updateById(updated.capture());
        assertThat(updated.getValue().getHemMargin()).isEqualByComparingTo("0.2");
        assertThat(updated.getValue().getOversizeWidthThreshold()).isEqualByComparingTo("5.0");
        assertThat(updated.getValue().getOversizeHeightThreshold()).isEqualByComparingTo("3.0");
        assertThat(configOf(data)).containsEntry("hem_margin", new BigDecimal("0.2"));
    }

    @Test
    @DisplayName("只改一个键 ⇒ **恰好一行**审计（改前→改后逐值正确 + 谁改的）；同值的键不写行")
    void putWritesExactlyOneAuditRowForTheChangedKey() {
        authenticate();
        Map<String, Object> first = validBody();          // hem_margin = 0.3
        CraftCalcConfig stored = saveFirstTime(first);
        clearInvocations(auditMapper);                     // 只数第二次写（首次是 11 个键全新增）

        when(mapper.selectActiveByTenant(7L)).thenReturn(stored);
        Map<String, Object> second = validBody();
        second.put("hem_margin", 0.25);                    // 只改这一个键
        service.put(7L, second);

        ArgumentCaptor<TenantParamAudit> captor = ArgumentCaptor.forClass(TenantParamAudit.class);
        verify(auditMapper, times(1)).insert(captor.capture());
        TenantParamAudit row = captor.getValue();
        assertThat(row.getParamKey()).isEqualTo("hem_margin");
        assertThat(row.getOldValue()).isEqualTo("0.3");
        assertThat(row.getNewValue()).isEqualTo("0.25");
        assertThat(row.getParamDomain()).isEqualTo(TenantParamAuditService.DOMAIN_CRAFT_CALC);
        assertThat(row.getOperation()).isEqualTo(TenantParamAuditService.OPERATION_PUT);
        assertThat(row.getOperationId()).isNotBlank();
        assertThat(row.getActorId()).isEqualTo("u-9");
        assertThat(row.getActorName()).isEqualTo("13800138000");
    }

    @Test
    @DisplayName("口径 B：审计写失败 ⇒ 配置**照常保存**（值照落库、响应正常），且失败**可观测**")
    void putSurvivesAuditWriteFailureAndStaysObservable() {
        authenticate();
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);
        when(auditMapper.insert(any(TenantParamAudit.class)))
                .thenThrow(new org.springframework.dao.DataAccessResourceFailureException("审计表不可用"));

        ch.qos.logback.classic.Logger auditLogger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(TenantParamAuditService.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        auditLogger.addAppender(appender);
        Map<String, Object> data;
        try {
            // 🔴 本行就是判据 B：审计腿炸了，配置写入**必须不炸**（改前：异常直接冒到控制器 ⇒ 500）
            data = service.put(7L, validBody());
        } finally {
            auditLogger.detachAppender(appender);
        }

        // 配置照常落库 + 响应照常（商家看到的是「保存成功」）
        ArgumentCaptor<CraftCalcConfig> saved = ArgumentCaptor.forClass(CraftCalcConfig.class);
        verify(mapper).insert(saved.capture());
        assertThat(saved.getValue().getHemMargin()).isEqualByComparingTo("0.3");
        assertThat(data).containsEntry("source", CraftCalcConfigService.SOURCE_STORED);
        assertThat(configOf(data)).containsEntry("hem_margin", new BigDecimal("0.3"));

        // 可观测面 ①：计数（可画线/告警）
        assertThat(meters.get(TenantParamAuditService.WRITE_FAILED_METRIC)
                .tag("param_domain", TenantParamAuditService.DOMAIN_CRAFT_CALC)
                .counter().count()).isEqualTo(1.0d);
        // 可观测面 ②：结构化 ERROR（可 grep/告警）—— 「配置已保存但变更未留痕」不得静默
        assertThat(appender.list).anySatisfy(event -> {
            assertThat(event.getLevel()).isEqualTo(ch.qos.logback.classic.Level.ERROR);
            assertThat(event.getFormattedMessage()).contains("PARAM_AUDIT_WRITE_FAILED");
        });
    }

    @Test
    @DisplayName("被 422 拒的写 ⇒ 一行审计都不写（没保存就没有变更可留痕）")
    void rejectedWriteWritesNoAuditRow() {
        authenticate();
        when(mapper.selectActiveByTenant(7L)).thenReturn(null);

        assertThatThrownBy(() -> service.put(7L, withKey("min_fullness", 1.0)))
                .isInstanceOf(BusinessException.class);

        verify(auditMapper, never()).insert(any(TenantParamAudit.class));
    }

}
