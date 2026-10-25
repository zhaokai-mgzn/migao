// case_ids: DF-017, PG-020, OR-045
package com.migao.admin.shipment;

import com.migao.admin.controller.WorkerShipmentController;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.service.OrderShipmentService;
import com.migao.admin.service.ProcessingSetReadService;
import com.migao.admin.service.WorkerShipmentReadyService;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.lang.reflect.Method;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.Mockito.when;

/**
 * 工人端「**全完工待发货**」列表 + 50×70 发货标签的读数侧判据（issue #7761）。
 *
 * <h3>这张列表的危险形态（本类逐条钉住）</h3>
 * <ol>
 *   <li><b>半完工单出现在列表里</b> ⇒ 工人会把还差几套的订单发走（客户投诉 / 补发运费）；</li>
 *   <li><b>套都做完但作业单没置完成</b> 的单出现在列表里 ⇒ 点发货被服务端 422 拒，
 *       「看得见却发不出去」比少一行更坏（工人会反复刷新、来问人）；</li>
 *   <li><b>没有套的订单</b>（无作业单 / 无需报工）被算成「全完工」⇒ 把「没有这件事」说成
 *       「这件事做完了」（同 {@code ProcessingSetReadService.isCompleted} 的空套口径）；</li>
 *   <li><b>物流方式缺失被猜成「快递」</b> ⇒ 客户要物流专线（四季安）时按快递发。</li>
 * </ol>
 *
 * <h3>红证方向（改回旧形态 ⇒ 必红）</h3>
 * <p>把 {@link WorkerShipmentReadyService#listReadyOrders} 的过滤改成只看订单状态
 * （不看套完成度）⇒ 第 2 条用例当场红；把 {@code logisticsTypeLabel} 的未知取值改成回落
 * 「快递」⇒ 第 6 条红；把控制器映射改回 {@code /api/admin/**} ⇒ 第 7 条红。
 *
 * <p>⚠️ 本类**不**验证「套怎么算完工」（那是 {@code ProcessingSetReadService} 的既有判据，
 * 见 {@code ProcessingSetReadServiceTest}）；这里只验证**本列表怎么消费它**（判据唯一性）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class WorkerShipmentReadyServiceTest {

    private static final Long TENANT = 32L;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private ProcessingSetReadService processingSetReadService;

    private WorkerShipmentReadyService service;

    @BeforeEach
    void setUp() {
        service = new WorkerShipmentReadyService(orderMapper, processingSetReadService);
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────

    private static Order order(String id, String orderNo) {
        return Order.builder()
                .id(id)
                .tenantId(TENANT)
                .orderNo(orderNo)
                .status("producing")
                .customerName("肖风伟")
                .customerPhone("13849944707")
                .customerAddress("洛阳市涧西区某某路 18 号 3 单元 502")
                .logisticsType("logistics")
                .logisticsCompany("四季安")
                .remark("样品货款 600 元")
                .createdAt(OffsetDateTime.parse("2026-09-01T10:00:00+08:00"))
                .build();
    }

    private static Map<String, Object> sets(String poNo, int total, int completed, String poStatus) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("processing_order_id", "po-" + poNo);
        row.put("processing_order_no", poNo);
        row.put("processing_order_status", poStatus);
        row.put("total_sets", total);
        row.put("completed_sets", completed);
        return row;
    }

    private void givenCandidates(Order... orders) {
        when(orderMapper.selectList(any())).thenReturn(List.of(orders));
    }

    private void givenCompletion(Map<String, Map<String, Object>> completion) {
        when(processingSetReadService.setCompletionByOrderIds(anyCollection(), any())).thenReturn(completion);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> items(Map<String, Object> payload) {
        return (List<Map<String, Object>>) payload.get("items");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> scan(Map<String, Object> payload) {
        return (Map<String, Object>) payload.get("scan");
    }

    // ── ① 只有「多套全完工 + 作业单已完工」才进列表 ─────────────────────────────

    @Test
    @DisplayName("#7761 全完工单进列表；半完工单不得出现（否则工人会发半成品）")
    void onlyFullyCompletedOrdersAreListed() {
        givenCandidates(order("o-1", "0901-000084"), order("o-2", "0901-000085"));
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        completion.put("o-1", sets("JG-20260901-001", 3, 3, "completed"));
        completion.put("o-2", sets("JG-20260901-002", 3, 1, "in_processing"));
        givenCompletion(completion);

        Map<String, Object> payload = service.listReadyOrders(TENANT);
        List<Map<String, Object>> rows = items(payload);

        assertThat(rows).as("只有全完工那单进列表").hasSize(1);
        assertThat(rows.get(0))
                .as("行内要有发货标签要的全部事实（免去逐单回查）")
                .containsEntry("order_id", "o-1")
                .containsEntry("order_no", "0901-000084")
                .containsEntry("customer_name", "肖风伟")
                .containsEntry("customer_phone", "13849944707")
                .containsEntry("customer_address", "洛阳市涧西区某某路 18 号 3 单元 502")
                .containsEntry("logistics_type", "logistics")
                .containsEntry("logistics_type_label", "物流专线")
                .containsEntry("logistics_company", "四季安")
                .containsEntry("total_sets", 3)
                .containsEntry("completed_sets", 3)
                .containsEntry("processing_order_no", "JG-20260901-001");
        assertThat(payload.get("total")).isEqualTo(1);
    }

    @Test
    @DisplayName("#7761 套数缺键 / 0 套 ⇒ 不进列表（「没有可完工的套」不是「全完工」）")
    void ordersWithoutSetsAreNotListed() {
        givenCandidates(order("o-1", "0901-000084"), order("o-2", "0901-000085"));
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        completion.put("o-1", sets("JG-1", 0, 0, "completed"));
        // o-2 完全没有活跃加工单 ⇒ setCompletionByOrderIds 里没有它的键
        givenCompletion(completion);

        assertThat(items(service.listReadyOrders(TENANT)))
                .as("无套 / 0 套的订单不得被当成「全完工」")
                .isEmpty();
    }

    @Test
    @DisplayName("#7761 套都做完了但作业单还没置 completed ⇒ 不进列表（可见即应可发）")
    void setsDoneButProcessingOrderNotCompletedIsHidden() {
        givenCandidates(order("o-1", "0901-000084"));
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        completion.put("o-1", sets("JG-1", 3, 3, "in_processing"));
        givenCompletion(completion);

        assertThat(items(service.listReadyOrders(TENANT)))
                .as("这种单点发货会被服务端 422 拒（发货守卫读的正是作业单状态）⇒ 不该出现在列表里")
                .isEmpty();
    }

    @Test
    @DisplayName("#7761 列表里没有「第二套完工口径」的字段：读的是 ProcessingSetReadService 的读数")
    void listConsumesTheSingleSourceOfSetCompletion() {
        givenCandidates(order("o-1", "0901-000084"));
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        completion.put("o-1", sets("JG-1", 2, 2, "completed"));
        givenCompletion(completion);

        Map<String, Object> row = items(service.listReadyOrders(TENANT)).get(0);
        assertThat(row).containsKeys("total_sets", "completed_sets");
        org.mockito.Mockito.verify(processingSetReadService)
                .setCompletionByOrderIds(anyCollection(), any());
    }

    // ── ② 截断不静默 ───────────────────────────────────────────────────────

    @Test
    @DisplayName("#7761 候选超过扫描上限 ⇒ scan.truncated = true 且只取上限条（截断不静默）")
    void truncationIsExplicit() {
        List<Order> many = new ArrayList<>();
        for (int i = 0; i < WorkerShipmentReadyService.CANDIDATE_SCAN_LIMIT + 1; i++) {
            many.add(order("o-" + i, "0901-" + i));
        }
        when(orderMapper.selectList(any())).thenReturn(many);
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        for (Order o : many) {
            completion.put(o.getId(), sets("JG-" + o.getId(), 1, 1, "completed"));
        }
        givenCompletion(completion);

        Map<String, Object> payload = service.listReadyOrders(TENANT);
        assertThat(items(payload)).hasSize(WorkerShipmentReadyService.CANDIDATE_SCAN_LIMIT);
        assertThat(scan(payload)).containsEntry("truncated", true)
                .containsEntry("limit", WorkerShipmentReadyService.CANDIDATE_SCAN_LIMIT);
    }

    @Test
    @DisplayName("#7761 未截断时 truncated = false（不是恒 true 的空判据）")
    void notTruncatedWhenUnderLimit() {
        givenCandidates(order("o-1", "0901-000084"));
        Map<String, Map<String, Object>> completion = new LinkedHashMap<>();
        completion.put("o-1", sets("JG-1", 1, 1, "completed"));
        givenCompletion(completion);
        assertThat(scan(service.listReadyOrders(TENANT))).containsEntry("truncated", false);
    }

    // ── ③ 物流方式：映射与「未知不编造」 ───────────────────────────────────────

    @Test
    @DisplayName("#7761 物流方式中文映射：express 快递 / logistics 物流专线；未知与 null 一律 null（不猜成快递）")
    void logisticsTypeLabels() {
        assertThat(WorkerShipmentReadyService.logisticsTypeLabel("express")).isEqualTo("快递");
        assertThat(WorkerShipmentReadyService.logisticsTypeLabel("logistics")).isEqualTo("物流专线");
        assertThat(WorkerShipmentReadyService.logisticsTypeLabel(null))
                .as("未采集 ⇒ null（纸面按「—」处理），不得编造成「快递」")
                .isNull();
        assertThat(WorkerShipmentReadyService.logisticsTypeLabel("air"))
                .as("未知取值 ⇒ null，不得回退默认值（回退会把物流专线发成快递）")
                .isNull();
    }

    // ── ④ 端点在工人面上、且不挂商家权限码 ──────────────────────────────────

    @Test
    @DisplayName("#7761 列表端点在 /api/worker/shipment/** 上、GET /orders、且无商家权限码注解")
    void endpointIsOnWorkerSurfaceWithoutMerchantPermissionCode() throws Exception {
        RequestMapping classMapping = WorkerShipmentController.class.getAnnotation(RequestMapping.class);
        assertThat(classMapping).isNotNull();
        assertThat(classMapping.value()).containsExactly("/api/worker/shipment");

        Method readyOrders = null;
        for (Method method : WorkerShipmentController.class.getDeclaredMethods()) {
            GetMapping mapping = method.getAnnotation(GetMapping.class);
            if (mapping != null && List.of(mapping.value()).contains("/orders")) {
                readyOrders = method;
            }
        }
        assertThat(readyOrders).as("GET /orders 不在 WorkerShipmentController 上（工人端走不到）").isNotNull();
        assertThat(readyOrders.getParameterTypes())
                .as("只读一次 session 头 + 不接收任何客户端声称的身份")
                .hasSize(1);
        assertThat(readyOrders.isAnnotationPresent(
                com.migao.admin.security.RequirePermission.class))
                .as("工人 permissions=[]，挂商家权限码只会恒 403（与 WorkerProductionController 同口径）")
                .isFalse();
    }

    @Test
    @DisplayName("#7761 无工人 session ⇒ 401（fail-closed，不降级成空列表）")
    void requiresWorkerSession() {
        WorkerSessionService sessions = org.mockito.Mockito.mock(WorkerSessionService.class);
        when(sessions.resolveIdentity(any())).thenReturn(null);
        WorkerShipmentController controller = new WorkerShipmentController(
                org.mockito.Mockito.mock(OrderShipmentService.class), service, sessions);

        assertThatThrownBy(() -> controller.readyOrders(null))
                .as("无 session 必须 401 —— 否则「谁发的货」这条责任凭证会失去前提")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("登录");
    }
}
