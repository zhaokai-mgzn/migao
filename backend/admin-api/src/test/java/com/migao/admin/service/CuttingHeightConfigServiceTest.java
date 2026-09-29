package com.migao.admin.service;

// case_ids: PG-045

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import com.migao.admin.mapper.TenantParamAuditMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 裁高（定高）配置服务测试（V140，母单 #5161；设计单
 * {@code docs/design/cutting-height-config-and-terminal.md}）。
 *
 * <p>守五条会被下一位验收者重开的判据（每条都能红）：</p>
 * <ol>
 *   <li><b>缺行 = 默认种子</b>（{@code source='default'}）：7 项**逐字**（含「画线」有项无值）——
 *       红证：把种子里的值改掉 / 去掉画线 ⇒ 本条红；</li>
 *   <li><b>非法值 ⇒ 422 + 逐条理由</b>，<b>不得静默回退默认值</b>：红证：静默接受 ⇒ 不抛 + 落库 ⇒ 红；</li>
 *   <li><b>命中而<u>未配置取值</u>的项不计入、也不按 0 算</b>（壁达「画线」形态）：红证：按 0 算 / 静默吞 ⇒ 红；</li>
 *   <li><b>部位限定生效</b>：纱帘的项不得出现在布帘里：红证：忽略 {@code hit.position} ⇒ 红；</li>
 *   <li><b>upsert 单行</b>：无行 ⇒ insert（确定性 id），有行 ⇒ updateById（不产生第二行）。</li>
 * </ol>
 */
@DisplayName("CuttingHeightConfigService 裁高配置（V140 / 母单 #5161）")
class CuttingHeightConfigServiceTest {

    private static final Long TENANT = 7L;
    private static final Long OTHER_TENANT = 8L;

    private CuttingHeightConfigMapper mapper;
    private CuttingHeightConfigService service;

    @BeforeEach
    void setUp() {
        mapper = mock(CuttingHeightConfigMapper.class);
        // 变更留痕腿（§22 P6）：**真**服务 + mock mapper ⇒ 既能断言「写了哪一行」，也不因审计失败拖垮用例。
        service = new CuttingHeightConfigService(mapper, new TenantParamAuditService(
                mock(TenantParamAuditMapper.class), new SimpleMeterRegistry(), new ObjectMapper()));
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ────────────────────────── 1. 缺行 = 默认种子 ──────────────────────────

    @Test
    @DisplayName("缺行 ⇒ source=default + 壁达现场那 7 项（逐字，含「画线」有项无值）")
    void defaultsAreTheSevenItemsFromTheVendorDialog() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        Map<String, Object> data = service.get(TENANT);

        assertThat(data.get("source")).isEqualTo("default");
        List<Map<String, Object>> items = itemsOf(configOf(data));
        assertThat(items).extracting(i -> i.get("key"))
                .containsExactly("baobuzhe", "baobukong", "baoshazhe", "baoshakong", "huaxian", "butie", "shatie");
        assertThat(items).extracting(i -> i.get("name"))
                .containsExactly("包布折", "包布孔", "包纱折", "包纱孔", "画线", "布贴", "纱贴");
        assertThat(valueOf(items, "baobuzhe")).isEqualByComparingTo("0.08");
        assertThat(valueOf(items, "baobukong")).isEqualByComparingTo("0.1");
        assertThat(valueOf(items, "baoshazhe")).isEqualByComparingTo("0.08");
        assertThat(valueOf(items, "baoshakong")).isEqualByComparingTo("0.1");
        // 🔴 画线 = **有项无值**（壁达那边它就没值，现场因此要在机器上贴便签）⇒ 我们既不编数也不按 0 算。
        assertThat(valueOf(items, "huaxian")).isNull();
        assertThat(valueOf(items, "butie")).isEqualByComparingTo("0.015");
        assertThat(valueOf(items, "shatie")).isEqualByComparingTo("0.01");
    }

    @Test
    @DisplayName("默认取整 = 保留三位小数（机器三位小数，用 2.935）")
    void defaultRoundingKeepsThreeDecimals() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        Map<String, Object> rounding = asMap(configOf(service.get(TENANT)).get("rounding"));

        assertThat(rounding.get("mode")).isEqualTo("half_up");
        assertThat(rounding.get("digits")).isEqualTo(3);
    }

    // ────────────────────────── 2. 写面 fail-closed ──────────────────────────

    @Test
    @DisplayName("hit 与 hit_expr 同时给 ⇒ 422 并点名该字段（两套判据并存 = 迟早漂）")
    void hitAndHitExprTogetherAreRejected() {
        Map<String, Object> body = validBody();
        itemOf(body).put("hit_expr", "包含(特殊选项,\"包布折\")");

        assertThatThrownBy(() -> service.put(TENANT, body))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("items[0].hit_expr");
                });
        verify(mapper, never()).insert(any(CuttingHeightConfig.class));
        verify(mapper, never()).updateById(any(CuttingHeightConfig.class));
    }

    @Test
    @DisplayName("未知键 / 缺键 / 取值越界 ⇒ 422 逐条理由（不静默回退默认值）")
    void unknownMissingAndOutOfRangeKeysAreRejected() {
        Map<String, Object> unknown = validBody();
        unknown.put("formula", "x");
        assertThatThrownBy(() -> service.put(TENANT, unknown))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("formula"));

        Map<String, Object> missing = validBody();
        missing.remove("rounding");
        assertThatThrownBy(() -> service.put(TENANT, missing))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("rounding"));

        Map<String, Object> bad = validBody();
        itemOf(bad).put("value", "145");   // +0.145 米写成 mm = 145
        assertThatThrownBy(() -> service.put(TENANT, bad))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("items[0].value"));
    }

    @Test
    @DisplayName("取值允许 null（有项无值），但不允许负数")
    void nullValueIsAllowedButNegativeIsNot() {
        Map<String, Object> ok = validBody();
        itemOf(ok).put("value", null);
        assertThat(service.put(TENANT, ok).get("source")).isEqualTo("stored");

        Map<String, Object> bad = validBody();
        itemOf(bad).put("value", "-0.01");
        assertThatThrownBy(() -> service.put(TENANT, bad))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("items[0].value"));
    }

    // ────────────────────────── 5. upsert 单行 ──────────────────────────

    @Test
    @DisplayName("无行 ⇒ insert（确定性 id chc-<tenant>）；有行 ⇒ updateById（不产生第二行）")
    void upsertKeepsASingleRow() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);
        assertThat(service.put(TENANT, validBody()).get("source")).isEqualTo("stored");

        ArgumentCaptor<CuttingHeightConfig> inserted = ArgumentCaptor.forClass(CuttingHeightConfig.class);
        verify(mapper).insert(inserted.capture());
        assertThat(inserted.getValue().getId()).isEqualTo("chc-7");
        assertThat(inserted.getValue().getTenantId()).isEqualTo(TENANT);

        // 断言面收窄到「第二次写」：第一次的 insert 是**应该**发生的（缺行 ⇒ 建行）。
        clearInvocations(mapper);
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(CuttingHeightConfig.builder()
                .id("chc-7").tenantId(TENANT).status("active").deleted(0).build());
        service.put(TENANT, validBody());
        verify(mapper).updateById(any(CuttingHeightConfig.class));
        verify(mapper, never()).insert(any(CuttingHeightConfig.class));
    }

    @Test
    @DisplayName("不跨租户串：两个租户各自读各自的活跃行")
    void readsAreScopedByTenant() {
        when(mapper.selectActiveByTenant(OTHER_TENANT)).thenReturn(null);

        assertThat(service.get(OTHER_TENANT).get("source")).isEqualTo("default");
        verify(mapper).selectActiveByTenant(OTHER_TENANT);
        verify(mapper, never()).selectOne(any(LambdaQueryWrapper.class));
    }

    // ────────────────────────── 3/4. 预演：命中 + 部位 + 未配置取值 ──────────────────────────

    @Test
    @DisplayName("预演：同名匹配命中 ⇒ 裁剪高度 = 成品高 + 增量（2.92 + 0.015 = 2.935）")
    void previewAddsMatchedItems() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(storedBody());

        Map<String, Object> data = service.preview(TENANT, request("布帘", "2.92", List.of("布贴"), null, null, null));

        assertThat(data.get("source")).isEqualTo("stored");
        assertThat((BigDecimal) data.get("base")).isEqualByComparingTo("2.92");
        assertThat((BigDecimal) data.get("cutting_height")).isEqualByComparingTo("2.935");
        assertThat(asMap(data.get("rounding")).get("digits")).isEqualTo(3);
        assertThat(keysOf(data.get("hits"))).containsExactly("butie");
        assertThat(keysOf(data.get("misses"))).isEmpty();
    }

    @Test
    @DisplayName("预演：命中但**未配置取值**（画线）⇒ 进 misses(unresolved)、不计入、不按 0 算")
    void previewReportsUnresolvedInsteadOfAssumingZero() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(storedBody());

        Map<String, Object> data = service.preview(TENANT, request("布帘", "2.92", List.of("画线"), null, null, null));

        assertThat((BigDecimal) data.get("cutting_height")).isEqualByComparingTo("2.92");
        assertThat(keysOf(data.get("hits"))).isEmpty();
        List<Map<String, Object>> misses = asList(data.get("misses"));
        assertThat(misses).anySatisfy(m -> {
            assertThat(m.get("key")).isEqualTo("huaxian");
            assertThat(m.get("reason")).isEqualTo("unresolved");
        });
    }

    @Test
    @DisplayName("预演：部位限定生效（纱帘项不出现在布帘）；craft / shaped 触发同样按逐字比对")
    void previewHonoursPositionAndOtherTriggerKinds() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(storedBody());

        Map<String, Object> cloth = service.preview(TENANT, request("布帘", "2.92", List.of("纱贴"), null, null, null));
        assertThat(keysOf(cloth.get("hits"))).isEmpty();
        assertThat((BigDecimal) cloth.get("cutting_height")).isEqualByComparingTo("2.92");

        Map<String, Object> craft = service.preview(TENANT, request("布帘", "2.92", List.of(), "韩褶", null, null));
        assertThat(keysOf(craft.get("hits"))).containsExactly("hanzhe");

        Map<String, Object> shaped = service.preview(TENANT, request("布帘", "2.92", List.of(), null, null, true));
        assertThat(keysOf(shaped.get("hits"))).containsExactly("dingxing");
    }

    @Test
    @DisplayName("预演：取整规则生效（down + 2 位 ⇒ 2.935 → 2.93）；请求未知键 ⇒ 422")
    void previewHonoursRoundingAndRejectsUnknownRequestKeys() {
        CuttingHeightConfig row = storedBody();
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", "down");
        rounding.put("digits", 2);
        row.setRounding(rounding);
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(row);

        Map<String, Object> data = service.preview(TENANT, request("布帘", "2.92", List.of("布贴"), null, null, null));
        assertThat((BigDecimal) data.get("cutting_height")).isEqualByComparingTo("2.93");

        Map<String, Object> bad = request("布帘", "2.92", List.of(), null, null, null);
        bad.put("token", "abc");
        assertThatThrownBy(() -> service.preview(TENANT, bad))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("token"));
    }

    @Test
    @DisplayName("预演：成品高缺失 / 非数字 ⇒ 422（不猜、不按 0 算）")
    void previewRejectsMissingFinishedHeight() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(storedBody());

        assertThatThrownBy(() -> service.preview(TENANT, request("布帘", null, List.of(), null, null, null)))
                .isInstanceOfSatisfying(BusinessException.class,
                        e -> assertThat(fieldsOf(e)).contains("finished_height"));
    }

    // ────────────────────────── helpers ──────────────────────────

    /** 一份**合法**的全量配置（PUT 是全量替换 ⇒ 键必须齐）。 */
    static Map<String, Object> validBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", "option");
        hit.put("trigger_value", "包布折");
        hit.put("position", "布帘");
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", "baobuzhe");
        item.put("name", "包布折");
        item.put("value", "0.08");          // 字符串也要能收（前端表单原样发）
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("enabled", true);
        item.put("order", 10);
        items.add(item);
        body.put("items", items);
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", "half_up");
        rounding.put("digits", 3);
        body.put("rounding", rounding);
        return body;
    }

    /** 库里的那一行：4 项（同名匹配 / 人为改过的触发值 / 有项无值 / 部位限定）+ 两种其它触发类型。 */
    private static CuttingHeightConfig storedBody() {
        List<Map<String, Object>> items = new ArrayList<>();
        items.add(item("butie", "布贴", "0.015", "option", "布贴", "布帘"));
        items.add(item("shatie", "纱贴", "0.01", "option", "纱贴", "纱帘"));
        items.add(item("huaxian", "画线", null, "option", "画线", null));
        items.add(item("hanzhe", "韩褶加放", "0.015", "craft", "韩褶", "布帘"));
        items.add(item("dingxing", "定型加放", "0.02", "shaped", "true", "布帘"));
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", "half_up");
        rounding.put("digits", 3);
        return CuttingHeightConfig.builder()
                .id("chc-7").tenantId(TENANT).status("active").deleted(0)
                .items(items).rounding(rounding).build();
    }

    private static Map<String, Object> item(String key, String name, String value,
                                            String kind, String triggerValue, String position) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", kind);
        hit.put("trigger_value", triggerValue);
        hit.put("position", position);
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        item.put("order", 10);
        return item;
    }

    private static Map<String, Object> request(String position, String finishedHeight, List<String> options,
                                               String craft, List<String> processingItems, Boolean shaped) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("position", position);
        if (finishedHeight != null) {
            body.put("finished_height", finishedHeight);
        }
        body.put("special_options", options);
        if (craft != null) {
            body.put("craft", craft);
        }
        if (processingItems != null) {
            body.put("processing_items", processingItems);
        }
        if (shaped != null) {
            body.put("is_shaped", shaped);
        }
        return body;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> configOf(Map<String, Object> data) {
        return (Map<String, Object>) data.get("config");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> itemsOf(Map<String, Object> config) {
        return (List<Map<String, Object>>) config.get("items");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> itemOf(Map<String, Object> body) {
        return ((List<Map<String, Object>>) body.get("items")).get(0);
    }

    private static BigDecimal valueOf(List<Map<String, Object>> items, String key) {
        for (Map<String, Object> item : items) {
            if (key.equals(item.get("key"))) {
                Object value = item.get("value");
                return value == null ? null : new BigDecimal(String.valueOf(value));
            }
        }
        throw new AssertionError("找不到项：" + key);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object raw) {
        return (Map<String, Object>) raw;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asList(Object raw) {
        return (List<Map<String, Object>>) raw;
    }

    private static List<String> keysOf(Object rows) {
        List<String> keys = new ArrayList<>();
        for (Map<String, Object> row : asList(rows)) {
            keys.add(String.valueOf(row.get("key")));
        }
        return keys;
    }

    private static List<String> fieldsOf(BusinessException e) {
        List<String> fields = new ArrayList<>();
        if (e.getDetails() != null) {
            e.getDetails().forEach(d -> fields.add(d.getField()));
        }
        return fields;
    }
}
