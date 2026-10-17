// case_ids: PG-081
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.exception.BusinessException;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 质检记录的**待检清单读面**（`QualityCheckService.targets`）—— issue #7140。
 *
 * <p>对应用例：<b>PG-081</b>（`.github/cases/processing-order.yml`）。</p>
 *
 * <p>🔴 <b>为什么要有这个读面</b>：记录读面（{@code list}）只能读出**已录**的记录
 * ——「哪些成品帘还没检」它在结构上答不出（没有行 = 没有事实）⇒ 质检员在观星台上没有工作清单。
 * 本文件钉住它「怎么把加工单快照展开成成品帘行 + 取最新判定」这件事，**每条都能单独变红**：</p>
 *
 * <ol>
 *   <li><b>未检 ≠ 合格</b>：没有记录 ⇒ {@code state="pending"} 且 {@code latest=null}
 *       —— 不得回落成 {@code pass}（两句话语义不同：一件没检、一件检验合格）；</li>
 *   <li><b>最新一条胜出</b>：同一件成品帘多条记录（返工后复检）⇒ {@code latest} = 排在最前的那条
 *       （排序口径在服务端 {@code list()}，本方法只取第一条 —— 不另排一次）；</li>
 *   <li><b>计数是逐条状态计数</b>（不是合格率）：四态各自的条数与清单一致；</li>
 *   <li><b>状态过滤</b>：{@code status=pending} 只回未检行；未知取值 ⇒ 422 具名报错（不静默回落 all）；</li>
 *   <li><b>分页封顶</b>：{@code size} 超过上限被收到 100（服务端封顶，不信任调用方）；</li>
 *   <li><b>指不出的成品帘不出行</b>：快照行缺 {@code itemId}（存量数据）⇒ 不进来（不猜、不编）；</li>
 *   <li><b>已取消的加工单不质检</b>：只有活跃加工单参与（口列表见 {@code TARGET_PROCESSING_STATUSES}）；</li>
 *   <li><b>订单号随之给出</b>（issue #7160）：行上 {@code order_no} = 该加工单所属销售订单号；
 *       取不到 ⇒ {@code null}（不编值）—— 清单一行就能对上「哪张订单」。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("质检记录 · 待检清单读面（PG-081）")
class QualityCheckTargetsTest {

    private static final Long TENANT = 20L;
    private static final String PO_ID = "po-1";
    private static final String PO_NO = "JG-20261017-0001";
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "DD-20261017-0001";

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
    }

    /** 一件成品帘（快照行）—— 与 `ProcessingOrderItemBrief` 的键名一致。 */
    private static Map<String, Object> item(String itemId, String productName) {
        Map<String, Object> row = new LinkedHashMap<>();
        if (itemId != null) {
            row.put("itemId", itemId);
        }
        row.put("productName", productName);
        row.put("colorName", "米白");
        row.put("quantity", 2);
        row.put("unit", "套");
        return row;
    }

    private static ProcessingOrder po(String status, List<Map<String, Object>> items) {
        return ProcessingOrder.builder()
                .id(PO_ID)
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .processingOrderNo(PO_NO)
                .status(status)
                .deleted(0)
                .itemsSnapshot(items)
                .build();
    }

    private static QualityCheck record(String itemId, String result, String reason, String minute) {
        return QualityCheck.builder()
                .id("qi-" + itemId + "-" + minute)
                .tenantId(TENANT)
                .processingOrderId(PO_ID)
                .orderItemId(itemId)
                .positionName("布艺遮光帘A 米白")
                .inspectorId("user-inspector-1")
                .inspectorName("质检员小李")
                .inspectionResult(result)
                .reason(reason)
                .inspectedAt(OffsetDateTime.parse("2026-10-17T10:" + minute + ":00+08:00"))
                .deleted(0)
                .build();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> itemsOf(Map<String, Object> out) {
        return (List<Map<String, Object>>) out.get("items");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Integer> countsOf(Map<String, Object> out) {
        return (Map<String, Integer>) out.get("counts");
    }

    @Test
    @DisplayName("① 没有记录 ⇒ 未检（不是「合格」、也不是「0 条」）")
    void noRecordMeansPendingNotPass() {
        when(processingOrderMapper.selectList(any()))
                .thenReturn(List.of(po("in_processing", List.of(item("item-1", "布艺遮光帘A")))));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> out = service.targets(TENANT, null, null, 1, 20);

        assertThat(itemsOf(out)).hasSize(1);
        Map<String, Object> row = itemsOf(out).get(0);
        assertThat(row.get("state")).isEqualTo("pending");
        assertThat(row.get("latest")).isNull();
        assertThat(countsOf(out)).containsEntry("pending", 1).containsEntry("pass", 0);
        assertThat(out.get("total")).isEqualTo(1);
    }

    @Test
    @DisplayName("② 同一件多条记录 ⇒ 最新一条胜出（返工后复检）")
    void latestInspectionWins() {
        when(processingOrderMapper.selectList(any()))
                .thenReturn(List.of(po("in_processing", List.of(item("item-1", "布艺遮光帘A")))));
        // 服务端 list() 按 inspected_at 倒序 ⇒ 第一条就是最新（例如 10:30 复检合格、10:00 曾判返工）
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-1", "pass", null, "30"),
                record("item-1", "rework", "布面污渍", "00")));

        Map<String, Object> out = service.targets(TENANT, null, null, 1, 20);

        Map<String, Object> row = itemsOf(out).get(0);
        assertThat(row.get("state")).isEqualTo("pass");
        @SuppressWarnings("unchecked")
        Map<String, Object> latest = (Map<String, Object>) row.get("latest");
        assertThat(latest.get("result")).isEqualTo("pass");
        assertThat(latest.get("inspector_name")).isEqualTo("质检员小李");
        assertThat(countsOf(out)).containsEntry("pass", 1).containsEntry("pending", 0);
    }

    @Test
    @DisplayName("③ 四态计数 = 清单逐条状态（不是合格率）")
    void countsArePerStateTotals() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po("in_processing", List.of(
                item("item-1", "布艺遮光帘A"),
                item("item-2", "布艺遮光帘B"),
                item("item-3", "纱帘C"),
                item("item-4", "帘头D")))));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(
                record("item-1", "pass", null, "10"),
                record("item-2", "rework", "缝线开裂", "11"),
                record("item-3", "scrap", "尺寸偏差", "12")));

        Map<String, Object> out = service.targets(TENANT, null, "all", 1, 20);

        assertThat(itemsOf(out)).hasSize(4);
        assertThat(countsOf(out))
                .containsEntry("pending", 1)
                .containsEntry("pass", 1)
                .containsEntry("rework", 1)
                .containsEntry("scrap", 1);
    }

    @Test
    @DisplayName("④ 状态过滤：pending 只回未检行；未知取值 422（不静默回落 all）")
    void statusFilterAndUnknownValue() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po("in_processing", List.of(
                item("item-1", "布艺遮光帘A"),
                item("item-2", "布艺遮光帘B")))));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of(record("item-2", "pass", null, "10")));

        Map<String, Object> pendingOnly = service.targets(TENANT, null, "pending", 1, 20);
        assertThat(itemsOf(pendingOnly)).hasSize(1);
        assertThat(itemsOf(pendingOnly).get(0).get("order_item_id")).isEqualTo("item-1");
        // 计数报的是**全量四态**（过滤只改清单，不改「还有多少要检」这个读数）
        assertThat(countsOf(pendingOnly)).containsEntry("pending", 1).containsEntry("pass", 1);

        assertThatThrownBy(() -> service.targets(TENANT, null, "ok", 1, 20))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("status");
    }

    @Test
    @DisplayName("⑤ 分页：size 超上限被收到 100；第二页只回剩余行")
    void paginationIsCappedAndSliced() {
        List<Map<String, Object>> items = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            items.add(item("item-" + i, "布艺遮光帘" + i));
        }
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po("in_processing", items)));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> capped = service.targets(TENANT, null, null, 1, 5000);
        assertThat(capped.get("size")).isEqualTo(100);
        assertThat(itemsOf(capped)).hasSize(5);

        Map<String, Object> second = service.targets(TENANT, null, null, 2, 2);
        assertThat(itemsOf(second)).hasSize(2);
        assertThat(itemsOf(second).get(0).get("order_item_id")).isEqualTo("item-2");
        assertThat(second.get("total")).isEqualTo(5);
    }

    @Test
    @DisplayName("⑥ 快照行缺 itemId ⇒ 不出行（指不出「哪一件成品帘」就不猜）")
    void rowsWithoutItemIdAreSkipped() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        snapshot.add(item(null, "存量成品帘"));
        snapshot.add(item("item-1", "布艺遮光帘A"));
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po("in_processing", snapshot)));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> out = service.targets(TENANT, null, null, 1, 20);

        assertThat(itemsOf(out)).hasSize(1);
        assertThat(itemsOf(out).get(0).get("order_item_id")).isEqualTo("item-1");
        assertThat(countsOf(out)).containsEntry("pending", 1);
    }

    @Test
    @DisplayName("⑦ 没有活跃加工单 ⇒ 空清单 + 零计数（不是错误态）")
    void noActiveProcessingOrderIsEmptyNotError() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> out = service.targets(TENANT, null, null, 1, 20);

        assertThat(itemsOf(out)).isEmpty();
        assertThat(out.get("total")).isEqualTo(0);
        assertThat(countsOf(out))
                .containsEntry("pending", 0)
                .containsEntry("pass", 0)
                .containsEntry("rework", 0)
                .containsEntry("scrap", 0);
    }

    @Test
    @DisplayName("⑧ 行上带加工单所属销售订单号；订单取不到 ⇒ null（不编值）")
    void rowCarriesSalesOrderNo() {
        when(processingOrderMapper.selectList(any()))
                .thenReturn(List.of(po("in_processing", List.of(item("item-1", "布艺遮光帘A")))));
        when(qualityInspectionMapper.selectList(any())).thenReturn(List.of());
        when(orderMapper.selectBatchIds(any())).thenReturn(List.of(
                Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo(ORDER_NO).deleted(0).build()));

        Map<String, Object> out = service.targets(TENANT, null, null, 1, 20);

        // 同屏可对上订单：加工单号与订单号都给
        assertThat(itemsOf(out).get(0).get("processing_order_no")).isEqualTo(PO_NO);
        assertThat(itemsOf(out).get(0).get("order_no")).isEqualTo(ORDER_NO);

        // 订单取不到（存量单 / 订单不可见）⇒ null，界面渲染 —，不编值
        when(orderMapper.selectBatchIds(any())).thenReturn(List.of());
        Map<String, Object> missing = service.targets(TENANT, null, null, 1, 20);
        assertThat(itemsOf(missing).get(0).get("order_no")).isNull();
    }
}
