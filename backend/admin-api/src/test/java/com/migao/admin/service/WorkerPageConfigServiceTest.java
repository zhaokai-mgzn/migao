package com.migao.admin.service;

// case_ids: PG-065, BM-006

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
import org.mockito.ArgumentCaptor;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人端页面开关服务测试（V141，母单 #5161）。
 *
 * <p>守六条会被下一位验收者重开的判据（每条都能红）：</p>
 * <ol>
 *   <li><b>缺行 = 默认全开</b>（{@code source='default'} + 4 个页面逐字）——
 *       红证：默认集合改一个键 / 去掉一项 ⇒ 本条红；</li>
 *   <li><b>未知页面键 ⇒ 422 + 逐条理由</b>，<b>不得静默忽略</b>（静默 = 商家以为开了却没开）——
 *       红证：把未知键吞掉 ⇒ 不抛 + 落库 ⇒ 红；</li>
 *   <li><b>缺键 ⇒ 422 点名该键</b>（PUT 是全量替换，缺键不得静默回落到默认全开）；</li>
 *   <li><b>重复键 ⇒ 422</b>（同一页面写两遍 = 配置二义）；</li>
 *   <li><b>upsert 单行</b>：无行 ⇒ insert（确定性 id），有行 ⇒ updateById（不产生第二行）；</li>
 *   <li><b>页面集不是权限</b>：写面只落 {@code worker_page_configs}，永不碰 {@code users.permissions}
 *       （红证：若哪天把页面码写进权限快照，本条与 {@code users.permissions} 的判据都会红）。</li>
 * </ol>
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
