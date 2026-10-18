// case_ids: PG-087
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 质检**指标**读面（`QualityCheckService.stats`）—— issue #7192（P0 + P1）。
 *
 * <p>对应用例：<b>PG-087</b>（`.github/cases/processing-order.yml`）。</p>
 *
 * <p>🔴 本文件钉住口径，每条都能单独变红：</p>
 * <ol>
 *   <li><b>按件去重</b>：同一件两条记录（先合格、后返工）⇒ 已检 <b>1 件</b>、首检合格 1、当前合格 0、
 *       返工 1（按记录条数算会得到「已检 2」⇒ 红）；</li>
 *   <li><b>未检不进分母</b>：快照里没有记录的件不出现在任何计数/率里（未检 ≠ 不合格）；</li>
 *   <li><b>0 样本 ⇒ 率 = null</b>（前端显示「—」，<b>不是</b> 0%）—— 折成 0.0 ⇒ 红；</li>
 *   <li><b>窗口作用于首检时刻</b>：窗口外首检、窗口内复检的件<b>不进</b> cohort；</li>
 *   <li><b>趋势与分组自洽</b>：趋势 Σ已检 = 已检件数、分组 Σ已检 = 已检件数（第二份口径 ⇒ 红）；</li>
 *   <li><b>参数闸</b>：未知 bucket / 非法时间 ⇒ 422 具名（不静默回落）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("质检指标 · 首检合格率 / 当前合格率 / 趋势 / 分组（PG-087）")
class QualityCheckStatsTest {

    private static final Long TENANT = 21L;
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "JG-20261018-0001";
    private static final String ORDER_ID = "order-1";

    @Mock
    private QualityCheckMapper qualityInspectionMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;

    private QualityCheckService service;

    @BeforeEach
    void setUp() {
        service = new QualityCheckService(qualityInspectionMapper, orderItemMapper, processingOrderMapper,
                orderMapper, new ObjectMapper());
        when(processingOrderMapper.selectBatchIds(any())).thenReturn(List.of());
        when(orderItemMapper.selectBatchIds(any())).thenReturn(List.of());
    }

    private static QualityCheck record(String itemId, String result, String at) {
        return QualityCheck.builder()
                .id("qi-" + itemId + "-" + at)
                .tenantId(TENANT)
                .processingOrderId(PO_ID)
                .orderItemId(itemId)
                .positionName("布艺遮光帘A")
                .inspectorId("u-inspector")
                .inspectorName("质检员小李")
                .inspectionResult(result)
                .inspectedAt(OffsetDateTime.parse(at))
                .deleted(0)
                .build();
    }

    private static ProcessingOrder po(List<Map<String, Object>> items) {
        return ProcessingOrder.builder()
                .id(PO_ID)
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .processingOrderNo(PO_NO)
                .status("in_processing")
                .deleted(0)
                .createdAt(OffsetDateTime.parse("2026-10-01T09:00:00+08:00"))
                .itemsSnapshot(items)
                .build();
    }

    private static Map<String, Object> item(String itemId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("itemId", itemId);
        row.put("productName", "布艺遮光帘A");
        row.put("quantity", 1);
        return row;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> countsOf(Map<String, Object> out) {
        return (Map<String, Object>) out.get("counts");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> ratesOf(Map<String, Object> out) {
        return (Map<String, Object>) out.get("rates");
    }

    @Test
    @DisplayName("① 按件去重：同一件「先合格→后返工」⇒ 已检 1 件、首检合格 1、当前合格 0、返工 1")
    void aggregatesPerPieceNotPerRecord() {
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-1", "pass", "2026-10-17T10:00:00+08:00"),
                record("item-1", "rework", "2026-10-17T15:00:00+08:00")));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(List.of(item("item-1")))));

        Map<String, Object> out = service.stats(TENANT, "2026-10-01", "2026-11-01", "day");

        Map<String, Object> counts = countsOf(out);
        assertThat(counts.get("inspected")).isEqualTo(1);
        assertThat(counts.get("first_pass")).isEqualTo(1);
        assertThat(counts.get("current_pass")).isEqualTo(0);
        assertThat(counts.get("rework")).isEqualTo(1);
        assertThat(ratesOf(out).get("first_pass_rate")).isEqualTo(1.0);
        assertThat(ratesOf(out).get("current_pass_rate")).isEqualTo(0.0);
        assertThat(ratesOf(out).get("rework_rate")).isEqualTo(1.0);
    }

    @Test
    @DisplayName("② 未检不进分母：快照里没记录的件只出现在积压里，不出现在已检/率里")
    void pendingPiecesStayOutOfDenominator() {
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-1", "pass", "2026-10-17T10:00:00+08:00")));
        when(processingOrderMapper.selectList(any()))
                .thenReturn(List.of(po(List.of(item("item-1"), item("item-2")))));

        Map<String, Object> out = service.stats(TENANT, "2026-10-01", "2026-11-01", "day");

        assertThat(countsOf(out).get("inspected")).isEqualTo(1);
        // 未检那件只出现在积压里（不污染率）
        assertThat(backlogOf(out).get("pending")).isEqualTo(1);
    }

    @Test
    @DisplayName("③ 0 样本 ⇒ 率是 null（不是 0%）")
    void emptyCohortHasNullRates() {
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> out = service.stats(TENANT, "2026-10-01", "2026-11-01", "day");

        assertThat(countsOf(out).get("inspected")).isEqualTo(0);
        assertThat(ratesOf(out).get("first_pass_rate")).isNull();
        assertThat(ratesOf(out).get("current_pass_rate")).isNull();
        assertThat(ratesOf(out).get("rework_rate")).isNull();
        assertThat(ratesOf(out).get("scrap_rate")).isNull();
    }

    @Test
    @DisplayName("④ 窗口按首检时刻：窗口外首检、窗口内复检的件不进 cohort")
    void windowUsesFirstInspectionMoment() {
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-old", "rework", "2026-09-20T10:00:00+08:00"),
                record("item-old", "pass", "2026-10-17T10:00:00+08:00"),
                record("item-new", "pass", "2026-10-17T11:00:00+08:00")));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(List.of())));

        Map<String, Object> out = service.stats(TENANT, "2026-10-01", "2026-11-01", "day");

        // 只有 item-new 的首检落在 10 月
        assertThat(countsOf(out).get("inspected")).isEqualTo(1);
        assertThat(countsOf(out).get("first_pass")).isEqualTo(1);
    }

    @Test
    @DisplayName("⑤ 趋势与分组自洽：Σ趋势已检 = 已检件数 = Σ分组已检")
    @SuppressWarnings("unchecked")
    void trendAndGroupsAgreeWithCounts() {
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-1", "pass", "2026-10-17T10:00:00+08:00"),
                record("item-2", "rework", "2026-10-18T10:00:00+08:00")));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(List.of())));

        Map<String, Object> out = service.stats(TENANT, "2026-10-01", "2026-11-01", "day");

        int inspected = (int) countsOf(out).get("inspected");
        int trendSum = ((List<Map<String, Object>>) out.get("trend")).stream()
                .mapToInt(p -> (int) p.get("inspected")).sum();
        int groupSum = ((List<Map<String, Object>>) out.get("by_processing_order")).stream()
                .mapToInt(g -> (int) g.get("inspected")).sum();
        assertThat(inspected).isEqualTo(2);
        assertThat(trendSum).isEqualTo(inspected);
        assertThat(groupSum).isEqualTo(inspected);
    }

    @Test
    @DisplayName("⑥ 参数闸：未知 bucket / 非法时间 / 反向窗口 ⇒ 422 具名")
    void rejectsInvalidParameters() {
        assertThatThrownBy(() -> service.stats(TENANT, null, null, "hour"))
                .hasMessageContaining("bucket");
        assertThatThrownBy(() -> service.stats(TENANT, "2026-13-01", null, "day"))
                .hasMessageContaining("时间格式不合法");
        assertThatThrownBy(() -> service.stats(TENANT, "2026-10-10", "2026-10-01", "day"))
                .hasMessageContaining("时间窗不合法");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> backlogOf(Map<String, Object> out) {
        return (Map<String, Object>) out.get("backlog");
    }
}
