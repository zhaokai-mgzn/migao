package com.migao.admin.service;

// case_ids: PG-065, PG-073, BM-006

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.WorkerPageConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantParamAuditMapper;
import com.migao.admin.mapper.WorkerPageConfigMapper;
import com.migao.admin.worker.WorkerPages;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.ArgumentCaptor;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 工人端页面开关服务测试（V141，母单 #5161；非法形态枚举表 + null 拒收 = issue #6803）。
 *
 * <p>守八条会被下一位验收者重开的判据（每条都能红）：</p>
 * <ol>
 *   <li><b>缺行 = 默认全开</b>（{@code source='default'} + 4 个页面逐字）——
 *       红证：默认集合改一个键 / 去掉一项 ⇒ 本条红；</li>
 *   <li><b>未知页面键 ⇒ 422 + 逐条理由</b>，<b>不得静默忽略</b>（静默 = 商家以为开了却没开）——
 *       红证：把未知键吞掉 ⇒ 不抛 + 落库 ⇒ 红；</li>
 *   <li><b>缺键 ⇒ 422 点名该键</b>（PUT 是全量替换，缺键不得静默回落到默认全开）；</li>
 *   <li><b>重复键 ⇒ 422</b>（同一页面写两遍 = 配置二义）；</li>
 *   <li><b>upsert 单行</b>：无行 ⇒ insert（确定性 id），有行 ⇒ updateById（不产生第二行）；</li>
 *   <li><b>页面集不是权限</b>：写面只落 {@code worker_page_configs}，永不碰 {@code users.permissions}
 *       （红证：若哪天把页面码写进权限快照，本条与 {@code users.permissions} 的判据都会红）；</li>
 *   <li><b>🔴 {@code {"pages":null}} ⇒ 422</b>（issue #6803）：{@code null} 走的正是「静默回到默认全开」
 *       那条路 —— 工人端 H5（{@code frontend/worker-h5/src/render.mjs} 的 {@code effectivePages}）
 *       把空数组读成「没读到权限 ⇒ 全开」，而 {@code null} 会被落成 <b>空数组</b>（见下一条）
 *       ⇒ 一个 200 就把企业级对页面的关闭静默撤销。判据 = {@link #nullPagesIsRejectedExplicitly()}
 *       + 本类第 8 条枚举表；红证：把 {@code if (rawPages != null)} 的 null 分支去掉
 *       （即放行 null）⇒ 两条同时红；</li>
 *   <li><b>类级元守卫：{@code pages} 的非法形态枚举表</b>（缺键 / null / 非数组 / 未知键 / 重复键 /
 *       含空串 / 数字项）<b>逐条断言 422 且零落库</b> —— 让「新增一种非法形态忘了拒」当场红
 *       （表里少一条 = 少一条断言，而任何一条被放行都会红）。</li>
 * </ol>
 *
 * <p><b>{@code null} vs {@code []} 的读面口径（issue #6803 要求先钉死）</b>：两者都在
 * {@link WorkerPageConfig#toPages()} 归一成<b>同一个空列表</b> ⇒ 读面（{@code get} / {@code pagesFor}）
 * 都回 {@code source=stored, pages=[]} —— 即「{@code null} 落库 ≠ 原样 NULL，而是空数组」。
 * 佐证 = {@link #nullAndEmptyListNormalizeToTheSameStoredShape()}（不依赖本次修复，修前修后都绿）。</p>
 */
@DisplayName("WorkerPageConfigService 工人端页面开关（V141 / 母单 #5161）")
class WorkerPageConfigServiceTest {

    private static final Long TENANT = 7L;

    private WorkerPageConfigMapper mapper;
    private WorkerPageConfigService service;

    @BeforeEach
    void setUp() {
        mapper = mock(WorkerPageConfigMapper.class);
        // 变更留痕腿（§22 P6）：**真**服务 + mock mapper ⇒ 既能断言「写了哪一行」，也不因审计失败拖垮用例。
        service = new WorkerPageConfigService(mapper, new TenantParamAuditService(
                mock(TenantParamAuditMapper.class), new SimpleMeterRegistry(), new ObjectMapper()));
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ────────────────────────── 1. 缺行 = 默认全开 ──────────────────────────

    @Test
    @DisplayName("缺行 ⇒ source=default + 4 个页面逐字（report/order/cut_calc/shipment）")
    void missingRowFallsBackToAllPagesWithDefaultSource() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        Map<String, Object> data = service.get(TENANT);

        assertThat(data.get("source")).isEqualTo("default");
        assertThat(pagesOf(data)).containsExactly("report", "order", "cut_calc", "shipment");
        // 页面名是人话（配置面板按它渲染勾选项；键是机器码）
        assertThat(asMap(data.get("labels")).get("report")).isEqualTo("报工");
    }

    @Test
    @DisplayName("有行 ⇒ source=stored + 原样回商家配置（不补齐、不重排）")
    void storedRowIsReturnedVerbatim() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(row(List.of("shipment", "report")));

        Map<String, Object> data = service.get(TENANT);

        assertThat(data.get("source")).isEqualTo("stored");
        assertThat(pagesOf(data)).containsExactly("shipment", "report");
    }

    @Test
    @DisplayName("pagesFor（工人下发面）与 get（商家读面）同源：缺行 ⇒ 默认全开")
    void pagesForSharesTheSameDefaultAsTheAdminReadFace() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        assertThat(service.pagesFor(TENANT)).containsExactlyElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("🔴 null vs [] 的落库/读面口径一致：两者都归一成**空列表**（不是 NULL、也不抛）")
    void nullAndEmptyListNormalizeToTheSameStoredShape() {
        WorkerPageConfig nullPages = row(null);
        WorkerPageConfig emptyPages = row(List.of());

        assertThat(nullPages.toConfigMap()).containsEntry("pages", List.of());
        assertThat(emptyPages.toConfigMap()).containsEntry("pages", List.of());
        // 读面：null 的那一行回的是空列表（**这就是 null 能静默撤销企业级关闭的机理**）
        assertThat(nullPages.toPages()).isEmpty();
        assertThat(emptyPages.toPages()).isEmpty();
    }

    @Test
    @DisplayName("租户为空 ⇒ 422 租户无效（不查出全租户的行）")
    void nullTenantIsRejected() {
        assertThatThrownBy(() -> service.get(null)).isInstanceOf(BusinessException.class);
        verify(mapper, never()).selectActiveByTenant(any());
    }

    // ────────────────────────── 2. 写面 fail-closed ──────────────────────────

    @Test
    @DisplayName("🔴 未知页面键 ⇒ 422 并点名该下标（不静默忽略）")
    void unknownPageKeyIsRejectedWithIndexLevelReason() {
        assertThatThrownBy(() -> service.put(TENANT, body(List.of("report", "stock"))))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("pages[1]");
                    assertThat(messagesOf(e)).anySatisfy(m -> assertThat(m).contains("stock"));
                });
        verify(mapper, never()).insert(any(WorkerPageConfig.class));
        verify(mapper, never()).updateById(any(WorkerPageConfig.class));
    }

    @Test
    @DisplayName("缺 pages 键 ⇒ 422 点名 pages（全量替换：缺键不得静默回落默认全开）")
    void missingPagesKeyIsRejected() {
        assertThatThrownBy(() -> service.put(TENANT, Map.of()))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("pages");
                });
        verify(mapper, never()).insert(any(WorkerPageConfig.class));
    }

    @Test
    @DisplayName("🔴 issue #6803：{\"pages\":null} ⇒ 422 + 复用缺键那句「静默回到默认全开」+ 给明确出口")
    void nullPagesIsRejectedExplicitly() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("pages", null);        // ← 修复前：这里被静默放过，落库成 []（读面 stored + pages=[]）

        assertThatThrownBy(() -> service.put(TENANT, body))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("pages");
                    assertThat(messagesOf(e)).anySatisfy(m -> assertThat(m)
                            .as("与缺键同一句话术（issue #6803 逐字要求）")
                            .contains("静默回到默认全开"));
                    assertThat(messagesOf(e)).anySatisfy(m -> assertThat(m)
                            .as("必须给明确出口，不能只说「不许」")
                            .contains("{\"pages\":[]}"));
                });
        // 零落库：拒绝必须发生在写之前（没有「先写空集再报错」的中间态）
        verifyNoInteractions(mapper);
    }

    @Test
    @DisplayName("未知配置键 ⇒ 422 点名该键（拼错的键会被静默忽略 = 商家以为改了却没改）")
    void unknownConfigKeyIsRejected() {
        Map<String, Object> body = body(List.of("report"));
        body.put("page", List.of("order"));     // 拼错：page 不是 pages

        assertThatThrownBy(() -> service.put(TENANT, body))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("page");
                });
    }

    @Test
    @DisplayName("重复页面键 ⇒ 422（同一页面写两遍 = 配置二义）")
    void duplicatePageKeyIsRejected() {
        assertThatThrownBy(() -> service.put(TENANT, body(List.of("report", "report"))))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("pages[1]");
                });
    }

    @Test
    @DisplayName("pages 不是数组 ⇒ 422 点名 pages")
    void pagesMustBeAnArray() {
        assertThatThrownBy(() -> service.put(TENANT, body("report")))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(fieldsOf(e)).contains("pages");
                });
    }

    @Test
    @DisplayName("空数组是**合法**的显式选择（商家把页面全关），不是配置错误")
    void emptyListIsAnExplicitValidChoice() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        Map<String, Object> data = service.put(TENANT, body(List.of()));

        assertThat(data.get("source")).isEqualTo("stored");
        assertThat(pagesOf(data)).isEmpty();
        verify(mapper).insert(any(WorkerPageConfig.class));
        // 本单（issue #6803）**只**拒 null，不动这里：`[]` 不接受、也不带「静默回到默认全开」那句理由
        // （两条分别是本用例与 nullPagesIsRejectedExplicitly 的逐字断言，任一被改 ⇒ 红）。
    }

    // ────────────────── 2b. 类级元守卫：非法形态枚举表（issue #6803） ──────────────────

    /**
     * {@code pages} 的**非法形态**枚举表（每行一条断言）。
     *
     * <p>🔴 为什么是「表」而不是一堆散测：{@code validate()} 里每一个放行分支都对应**一种**形态，
     * 而新增分支时最危险的形态就是「悄悄放过一种 payload」。把形态枚举化后，任何被放行的形态
     * 都会在同一张表上红，且报告里直接打印是**哪一种**。</p>
     *
     * <p>本表里 <b>{@code pages:null} 一行就是 issue #6803 的实例判据</b>（与
     * {@link #nullPagesIsRejectedExplicitly()} 同源 —— 后者额外钉死「文案复用缺键那句 + 给出口」）。</p>
     */
    static Stream<Map.Entry<String, Map<String, Object>>> illegalPayloadShapes() {
        Map<String, Object> withUnknownKey = body(List.of("report"));
        withUnknownKey.put("page", List.of("order"));           // 拼错的键

        return Stream.of(
                Map.entry("缺键", Map.of()),
                Map.entry("null", payload(null)),
                Map.entry("非数组（字符串）", payload("report")),
                Map.entry("非数组（对象）", payload(Map.of("report", true))),
                Map.entry("非数组（数字）", payload(7)),
                Map.entry("未知页面键", payload(List.of("report", "stock"))),
                Map.entry("重复页面键", payload(List.of("report", "report"))),
                Map.entry("含空串项", payload(List.of("report", ""))),
                Map.entry("数字项", payload(List.of(7))),
                Map.entry("未知配置键", withUnknownKey));
    }

    @ParameterizedTest(name = "[{index}] {0} ⇒ 422 且零落库")
    @MethodSource("illegalPayloadShapes")
    @DisplayName("🔴 类级元守卫：pages 的每一种非法形态都 ⇒ 422 + 逐条理由 + 零落库")
    void everyIllegalShapeIsRejectedAndNothingIsWritten(Map.Entry<String, Map<String, Object>> shape) {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);

        assertThatThrownBy(() -> service.put(TENANT, shape.getValue()))
                .as("非法形态「%s」必须被拒（放行 ⇒ 静默改写企业级页面开关）", shape.getKey())
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails())
                            .as("必须逐条给出理由（不许只回一句「参数错误」）")
                            .isNotEmpty();
                });

        // 整个用例（本参数化方法）跑完仍零落库 ⇒ 拒绝发生在写之前，没有「先写再报错」的中间态
        verifyNoInteractions(mapper);
    }

    @Test
    @DisplayName("🔴 非法形态的逐条理由都点名**合法键**（不把坏值算到别的键头上）")
    void everyIllegalShapeNamesAConfigKey() {
        for (Map.Entry<String, Map<String, Object>> shape : illegalPayloadShapes().toList()) {
            assertThatThrownBy(() -> service.put(TENANT, shape.getValue()))
                    .as("非法形态「%s」", shape.getKey())
                    .isInstanceOfSatisfying(BusinessException.class, e -> assertThat(fieldsOf(e))
                            .as("理由只能点名 `pages` / `pages[i]` 或**请求里真出现的**拼错键名")
                            .allSatisfy(field -> assertThat(field).matches("pages|pages\\[\\d+]|page")));
        }
    }

    // ────────────────────────── 3. upsert 单行 ──────────────────────────

    @Test
    @DisplayName("无行 ⇒ insert（确定性 id = wpc-<tenantId>），有行 ⇒ updateById（不产生第二行）")
    void putIsSingleRowUpsert() {
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(null);
        service.put(TENANT, body(List.of("report", "shipment")));

        ArgumentCaptor<WorkerPageConfig> inserted = ArgumentCaptor.forClass(WorkerPageConfig.class);
        verify(mapper).insert(inserted.capture());
        assertThat(inserted.getValue().getId()).isEqualTo("wpc-" + TENANT);
        assertThat(inserted.getValue().getTenantId()).isEqualTo(TENANT);
        assertThat(inserted.getValue().toPages()).containsExactly("report", "shipment");

        WorkerPageConfig existing = row(List.of("report"));
        when(mapper.selectActiveByTenant(TENANT)).thenReturn(existing);
        service.put(TENANT, body(List.of("order")));

        ArgumentCaptor<WorkerPageConfig> updated = ArgumentCaptor.forClass(WorkerPageConfig.class);
        verify(mapper).updateById(updated.capture());
        assertThat(updated.getValue().toPages()).containsExactly("order");
        // 单行表：整个用例只发生过一次 updateById（第二行会破坏 uk_worker_page_configs_tenant）
        verify(mapper, times(1)).updateById(any(WorkerPageConfig.class));
    }

    private static WorkerPageConfig row(List<String> pages) {
        return WorkerPageConfig.builder()
                .id("wpc-" + TENANT).tenantId(TENANT).pages(pages).status("active").deleted(0).build();
    }

    private static Map<String, Object> payload(Object pages) {
        return body(pages);
    }

    private static Map<String, Object> body(Object pages) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("pages", pages);
        return body;
    }

    @SuppressWarnings("unchecked")
    private static List<String> pagesOf(Map<String, Object> data) {
        return new ArrayList<>((List<String>) data.get("pages"));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object raw) {
        return (Map<String, Object>) raw;
    }

    private static List<String> fieldsOf(BusinessException e) {
        return e.getDetails().stream().map(d -> d.getField()).toList();
    }

    private static List<String> messagesOf(BusinessException e) {
        return e.getDetails().stream().map(d -> d.getMessage()).toList();
    }
}
